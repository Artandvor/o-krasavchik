"""Хранилище фактов. Каждый факт = значение + источник + уверенность + дата + срок годности.
Старые факты не удаляются: новая версия помечает предыдущую 'superseded', история видна."""
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotels(
  id TEXT PRIMARY KEY, name TEXT, kind TEXT, lat REAL, lon REAL, stars REAL,
  data_json TEXT);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hotel_id TEXT, key TEXT, value_json TEXT, scope TEXT, detail_json TEXT,
  confidence REAL, source_type TEXT, source_ref TEXT, method TEXT,
  obtained_at TEXT, valid_until TEXT, status TEXT DEFAULT 'active', note TEXT);
CREATE INDEX IF NOT EXISTS ix_facts ON facts(hotel_id, key, status);
CREATE TABLE IF NOT EXISTS conflicts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, hotel_id TEXT, key TEXT,
  fact_a INTEGER, fact_b INTEGER, description TEXT, status TEXT DEFAULT 'open',
  resolution TEXT, created_at TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, hotel_id TEXT, key TEXT, text TEXT,
  hypothesis_json TEXT, options_json TEXT, priority REAL, reason TEXT,
  status TEXT DEFAULT 'open', created_at TEXT, answered_at TEXT,
  answer_text TEXT, parsed_json TEXT);
CREATE TABLE IF NOT EXISTS agent_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, agent TEXT, hotel_id TEXT,
  key TEXT, action TEXT, message TEXT, data_json TEXT);
CREATE TABLE IF NOT EXISTS search_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, query TEXT, parsed_json TEXT, n_results INTEGER);
CREATE TABLE IF NOT EXISTS demand(key TEXT PRIMARY KEY, count INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS labels(
  hotel_id TEXT, key TEXT, value_json TEXT, labeler TEXT, evidence TEXT, ts TEXT,
  PRIMARY KEY(hotel_id, key));
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def plus_days(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


class _Result:
    """Результат запроса, полностью прочитанный под блокировкой (курсор не живёт между потоками)."""

    def __init__(self, cur):
        self.rows = cur.fetchall() if cur.description else []
        self.lastrowid, self.rowcount = cur.lastrowid, cur.rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _Locked:
    """Одно соединение SQLite на процесс, но запросы из разных потоков FastAPI — строго по очереди."""

    def __init__(self, con):
        object.__setattr__(self, "_con", con)
        object.__setattr__(self, "_lock", threading.RLock())

    def execute(self, *a):
        with self._lock:
            return _Result(self._con.execute(*a))

    def executescript(self, sql):
        with self._lock:
            return self._con.executescript(sql)

    def commit(self):
        with self._lock:
            return self._con.commit()

    def __getattr__(self, name):
        return getattr(self._con, name)

    def __setattr__(self, name, value):
        setattr(self._con, name, value)


class Store:
    def __init__(self, path=None):
        self.path = str(path or DB_PATH)
        self.db = _Locked(sqlite3.connect(self.path, check_same_thread=False, timeout=30))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # без WAL: база может лежать на внешнем диске (exFAT), где WAL ненадёжен
        self.db.execute("PRAGMA journal_mode=DELETE")

    # ---------------------------------------------------------------- hotels
    def upsert_hotel(self, h: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO hotels(id,name,kind,lat,lon,stars,data_json) VALUES(?,?,?,?,?,?,?)",
            (h["id"], h["name"], h.get("kind"), h["lat"], h["lon"], h.get("stars"),
             json.dumps(h, ensure_ascii=False)))

    def hotels(self):
        return [json.loads(r["data_json"]) for r in self.db.execute("SELECT data_json FROM hotels ORDER BY name")]

    def hotel(self, hid):
        r = self.db.execute("SELECT data_json FROM hotels WHERE id=?", (hid,)).fetchone()
        return json.loads(r["data_json"]) if r else None

    # ---------------------------------------------------------------- facts
    def add_fact(self, hotel_id, key, value, confidence, source_type, source_ref="", scope="",
                 detail=None, method="", ttl_days=180, note="", supersede_same_source=True):
        if supersede_same_source:
            self.db.execute(
                "UPDATE facts SET status='superseded' WHERE hotel_id=? AND key=? AND source_type=? AND status='active'",
                (hotel_id, key, source_type))
        cur = self.db.execute(
            "INSERT INTO facts(hotel_id,key,value_json,scope,detail_json,confidence,source_type,source_ref,"
            "method,obtained_at,valid_until,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (hotel_id, key, json.dumps(value, ensure_ascii=False), scope,
             json.dumps(detail or {}, ensure_ascii=False), round(float(confidence), 3), source_type,
             source_ref, method, now_iso(), plus_days(ttl_days), note))
        return cur.lastrowid

    def facts(self, hotel_id, key=None, status="active"):
        q = "SELECT * FROM facts WHERE hotel_id=?"
        args = [hotel_id]
        if key:
            q += " AND key=?"
            args.append(key)
        if status:
            q += " AND status=?"
            args.append(status)
        return [self._fact(r) for r in self.db.execute(q + " ORDER BY id", args)]

    def fact(self, fid):
        r = self.db.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
        return self._fact(r) if r else None

    def history(self, hotel_id, key):
        return [self._fact(r) for r in self.db.execute(
            "SELECT * FROM facts WHERE hotel_id=? AND key=? ORDER BY id", (hotel_id, key))]

    def set_fact_status(self, fid, status, note=None):
        if note is None:
            self.db.execute("UPDATE facts SET status=? WHERE id=?", (status, fid))
        else:
            self.db.execute("UPDATE facts SET status=?, note=? WHERE id=?", (status, note, fid))

    def expire_fact(self, fid):
        """Пометить факт на перепроверку (например, отельер сообщил об изменениях)."""
        self.db.execute("UPDATE facts SET valid_until=? WHERE id=?", (now_iso(), fid))

    def stale_facts(self):
        return [self._fact(r) for r in self.db.execute(
            "SELECT * FROM facts WHERE status='active' AND valid_until < ?", (now_iso(),))]

    @staticmethod
    def _fact(r):
        d = dict(r)
        d["value"] = json.loads(d.pop("value_json"))
        d["detail"] = json.loads(d.pop("detail_json") or "{}")
        return d

    # ---------------------------------------------------------------- conflicts
    def open_conflict(self, hotel_id, key, fa, fb, description):
        ex = self.db.execute(
            "SELECT id FROM conflicts WHERE hotel_id=? AND key=? AND status='open' AND "
            "((fact_a=? AND fact_b=?) OR (fact_a=? AND fact_b=?))", (hotel_id, key, fa, fb, fb, fa)).fetchone()
        if ex:
            return ex["id"]
        return self.db.execute(
            "INSERT INTO conflicts(hotel_id,key,fact_a,fact_b,description,created_at) VALUES(?,?,?,?,?,?)",
            (hotel_id, key, fa, fb, description, now_iso())).lastrowid

    def conflict_status(self, hotel_id, key, fa, fb):
        r = self.db.execute(
            "SELECT status, resolution FROM conflicts WHERE hotel_id=? AND key=? AND "
            "((fact_a=? AND fact_b=?) OR (fact_a=? AND fact_b=?)) ORDER BY id DESC LIMIT 1",
            (hotel_id, key, fa, fb, fb, fa)).fetchone()
        return dict(r) if r else None

    def conflicts(self, hotel_id=None, status="open"):
        q, a = "SELECT * FROM conflicts WHERE 1=1", []
        if hotel_id:
            q += " AND hotel_id=?"
            a.append(hotel_id)
        if status:
            q += " AND status=?"
            a.append(status)
        return [dict(r) for r in self.db.execute(q, a)]

    def resolve_conflict(self, cid, resolution):
        self.db.execute("UPDATE conflicts SET status='resolved', resolution=?, resolved_at=? WHERE id=?",
                        (resolution, now_iso(), cid))

    # ---------------------------------------------------------------- questions
    def add_question(self, hotel_id, key, text, hypothesis, options, priority, reason):
        ex = self.db.execute("SELECT id FROM questions WHERE hotel_id=? AND key=? AND status='open'",
                             (hotel_id, key)).fetchone()
        if ex:
            self.db.execute("UPDATE questions SET text=?, hypothesis_json=?, options_json=?, priority=?, reason=? "
                            "WHERE id=?", (text, json.dumps(hypothesis, ensure_ascii=False),
                                           json.dumps(options, ensure_ascii=False), priority, reason, ex["id"]))
            return ex["id"]
        return self.db.execute(
            "INSERT INTO questions(hotel_id,key,text,hypothesis_json,options_json,priority,reason,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (hotel_id, key, text, json.dumps(hypothesis, ensure_ascii=False),
             json.dumps(options, ensure_ascii=False), priority, reason, now_iso())).lastrowid

    def questions(self, hotel_id=None, status="open"):
        q, a = "SELECT * FROM questions WHERE 1=1", []
        if hotel_id:
            q += " AND hotel_id=?"
            a.append(hotel_id)
        if status:
            q += " AND status=?"
            a.append(status)
        out = []
        for r in self.db.execute(q + " ORDER BY priority DESC", a):
            d = dict(r)
            d["hypothesis"] = json.loads(d.pop("hypothesis_json") or "null")
            d["options"] = json.loads(d.pop("options_json") or "[]")
            d["parsed"] = json.loads(d.pop("parsed_json") or "null")
            out.append(d)
        return out

    def question(self, qid):
        for q in self.questions(status=None):
            if q["id"] == qid:
                return q
        return None

    def answer_question(self, qid, text, parsed):
        self.db.execute("UPDATE questions SET status='answered', answered_at=?, answer_text=?, parsed_json=? WHERE id=?",
                        (now_iso(), text, json.dumps(parsed, ensure_ascii=False), qid))

    # ---------------------------------------------------------------- logs / demand
    def log(self, agent, action, message, hotel_id=None, key=None, data=None):
        self.db.execute("INSERT INTO agent_log(ts,agent,hotel_id,key,action,message,data_json) VALUES(?,?,?,?,?,?,?)",
                        (now_iso(), agent, hotel_id, key, action, message,
                         json.dumps(data or {}, ensure_ascii=False)))

    def logs(self, hotel_id=None, limit=200):
        q, a = "SELECT * FROM agent_log", []
        if hotel_id:
            q += " WHERE hotel_id=?"
            a.append(hotel_id)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id DESC LIMIT ?", a + [limit])]

    def log_search(self, query, parsed, n):
        self.db.execute("INSERT INTO search_log(ts,query,parsed_json,n_results) VALUES(?,?,?,?)",
                        (now_iso(), query, json.dumps(parsed, ensure_ascii=False), n))
        for c in parsed.get("criteria", []):
            self.db.execute("INSERT INTO demand(key,count) VALUES(?,1) ON CONFLICT(key) DO UPDATE SET count=count+1",
                            (c["key"],))

    def demand(self):
        return {r["key"]: r["count"] for r in self.db.execute("SELECT * FROM demand")}

    # ---------------------------------------------------------------- labels
    def set_label(self, hotel_id, key, value, labeler="human", evidence=""):
        self.db.execute("INSERT OR REPLACE INTO labels VALUES(?,?,?,?,?,?)",
                        (hotel_id, key, json.dumps(value, ensure_ascii=False), labeler, evidence, now_iso()))

    def labels(self):
        out = []
        for r in self.db.execute("SELECT * FROM labels"):
            d = dict(r)
            d["value"] = json.loads(d.pop("value_json"))
            out.append(d)
        return out

    def kv_get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def kv_set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False)))

    def commit(self):
        self.db.commit()


_store = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def ts():
    return time.time()
