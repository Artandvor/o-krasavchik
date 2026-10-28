"""HTTP API + раздача фронтенда.  Запуск: python run.py  →  http://localhost:8000"""
import threading

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import metrics, truth
from .agents import collector, compiler, hotelier, refresher
from .agents.search import INDEX, search
from .config import STATIC, region_cfg
from .geo.context import get_ctx
from .llm import get_llm
from .registry import get_registry
from .store import get_store
from .tools import TOOLS

app = FastAPI(title="О!дин шаг — агентная система характеристик отелей")
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
app.add_middleware(GZipMiddleware, minimum_size=2000)
_BASEMAP = None
LOCK = threading.Lock()
JOBS = {}


def _ctx():
    ctx = get_ctx()
    if not getattr(ctx, "_whatif_applied", False):
        for b in get_store().kv_get("what_if_buildings", []):
            ctx.add_building(refresher.rect_ll(ctx, b["lat"], b["lon"], b["width"], b["depth"], b["angle"]), b["height"])
        ctx._whatif_applied = True
    return ctx


def _resolved(hid):
    store, reg = get_store(), get_registry()
    out = []
    for s in reg.all():
        fid = "_region" if s["scope"] == "region" else hid
        r = truth.resolve(s, store.facts(fid, s["key"]), store, fid, create=False)
        out.append({"key": s["key"], "title": s["title"], "group": s["group"], "scope": s["scope"], "type": s["type"],
                    "unit": s.get("unit"), "description": s.get("description"), "sources_hint": s.get("sources", []),
                    "ttl_days": s["ttl_days"], "resolved": r})
    return out


@app.get("/health")
def health():
    return {"status": "ok", "hotels": len(get_store().hotels())}


@app.get("/api/meta")
def meta():
    store, reg, llm = get_store(), get_registry(), get_llm()
    cfg = region_cfg()
    groups = {}
    for s in reg.all():
        groups.setdefault(s["group"], []).append({"key": s["key"], "title": s["title"], "type": s["type"], "scope": s["scope"]})
    ctx = _ctx()
    return {"region": cfg["name"], "bbox": cfg["hotels_bbox"], "hotels": len(store.hotels()),
            "characteristics": len(reg.all()), "groups": groups,
            "llm": {"available": llm.available, "provider": llm.provider, "model": llm.model},
            "dem_source": ctx.dem_source, "data_built_at": ctx.built_at,
            "open_questions": len(store.questions()), "open_conflicts": len(store.conflicts())}


@app.get("/api/hotels")
def hotels():
    store = get_store()
    out = []
    for h in store.hotels():
        r = INDEX.get(h["id"])
        badges = []
        for k, label in (("sea_view", "море"), ("sunset_view", "закат"), ("mountain_view", "горы")):
            if r.get(k) and r[k]["value"] is True:
                badges.append(label)
        if r.get("quiet_night") and r["quiet_night"]["value"] == "тихо":
            badges.append("тихо")
        bw = r.get("beach_walk")
        out.append({"id": h["id"], "name": h["name"], "kind": h["kind"], "lat": h["lat"], "lon": h["lon"],
                    "stars": h.get("stars"), "levels": h.get("levels"), "badges": badges,
                    "beach_min": bw["value"] if bw else None})
    return out


@app.get("/api/hotels/{hid}")
def hotel(hid: str):
    store = get_store()
    h = store.hotel(hid)
    if not h:
        raise HTTPException(404)
    return {"hotel": {k: v for k, v in h.items() if k not in ("x", "y")},
            "facts": _resolved(hid), "questions": store.questions(hid, status=None),
            "conflicts": store.conflicts(hid, status=None), "log": store.logs(hid, 80)}


@app.get("/api/hotels/{hid}/history/{key}")
def history(hid: str, key: str):
    return get_store().history(hid, key)


@app.get("/api/search")
def api_search(q: str, limit: int = 20, log: bool = True, month: int = 0):
    return search(q, max(1, min(limit, 100)), log=log, month=month if 1 <= month <= 12 else None)


@app.get("/api/showcase")
def showcase(month: int = 7):
    """Окно для главного экрана: высокий этаж, много моря и закат над морем в этом месяце."""
    best = None
    for h in get_store().hotels():
        r = INDEX.get(h["id"])
        ss = ((r.get("sunset_view") or {}).get("detail") or {}).get("by_side") or {}
        sea = ((r.get("sea_view") or {}).get("detail") or {}).get("by_side") or {}
        for side, v in ss.items():
            if not v.get("over_sea") or month not in (v.get("months") or []) or side not in sea:
                continue
            lv = h.get("levels") or 3
            score = (sea[side].get("share") or 0) * 2 + min(lv, 16) / 16 + (0.3 if h.get("levels_src") == "osm" else 0)
            if best is None or score > best[0]:
                best = (score, h["id"], side, lv)
    if not best:
        return {}
    return {"id": best[1], "side": best[2], "floor": best[3]}


@app.post("/api/compare")
def compare(ids: list[str] = Body(..., embed=True)):
    store, reg = get_store(), get_registry()
    hs = [store.hotel(i) for i in ids if store.hotel(i)]
    rows = []
    for s in reg.all():
        if s["scope"] == "region":
            continue
        row = {"key": s["key"], "title": s["title"], "group": s["group"], "cells": []}
        for h in hs:
            r = INDEX.get(h["id"]).get(s["key"])
            row["cells"].append(None if not r else {"value": r["value"], "scope": r["scope"], "confidence": r["confidence"],
                                                    "conflict": bool(r.get("conflict") and not r["conflict"]["resolved"])})
        rows.append(row)
    return {"hotels": [{"id": h["id"], "name": h["name"], "stars": h.get("stars"), "levels": h.get("levels")} for h in hs],
            "rows": rows}


# ------------------------------------------------------------------ характеристики

@app.get("/api/characteristics")
def chars():
    return {"specs": [{k: v for k, v in s.items() if not k.startswith("_")} for s in get_registry().all()],
            "tools": {k: {"description": v["description"], "params": v["params"]} for k, v in TOOLS.items()}}


@app.post("/api/characteristics/compile")
def compile_char(text: str = Body(..., embed=True)):
    spec = compiler.compile_text(text)
    errs = compiler.validate(spec)
    preview = []
    if not errs:
        ctx = _ctx()
        for h in ctx.hotels[:8]:
            try:
                c = TOOLS[spec["tool"]]["fn"](ctx, h, spec, {})
                preview.append({"hotel": h["name"], "value": c[0]["value"] if c else None,
                                "scope": c[0]["scope"] if c else "нет данных — спросим отельера",
                                "confidence": c[0]["confidence"] if c else None})
            except Exception as e:  # noqa: BLE001
                errs.append(f"{h['name']}: {e}")
                break
    return {"spec": spec, "errors": errs, "preview": preview}


def _bg_collect(job, key):
    ctx = _ctx()
    store = get_store()
    with LOCK:
        for i, h in enumerate(ctx.hotels):
            collector.collect_hotel(ctx, h, keys=[key], force=True, store=store)
            JOBS[job] = {"done": i + 1, "total": len(ctx.hotels)}
            if i % 10 == 0:
                store.commit()
        for h in ctx.hotels:
            hotelier.plan_questions(h, store)
        store.commit()
        INDEX.invalidate()


@app.post("/api/characteristics")
def save_char(spec: dict = Body(...)):
    errs = compiler.validate(spec)
    if errs:
        raise HTTPException(400, "; ".join(errs))
    s = get_registry().save(spec)
    get_store().log("compiler", "new_characteristic", f"добавлена характеристика «{s['title']}» (инструмент {s['tool']})",
                    None, s["key"], {"spec": {k: v for k, v in s.items() if not k.startswith("_")}})
    job = f"collect:{s['key']}"
    JOBS[job] = {"done": 0, "total": len(_ctx().hotels)}
    threading.Thread(target=_bg_collect, args=(job, s["key"]), daemon=True).start()
    return {"ok": True, "key": s["key"], "job": job}


@app.get("/api/jobs/{job}")
def job_status(job: str):
    return JOBS.get(job, {"done": 0, "total": 0})


# ------------------------------------------------------------------ отельер

@app.get("/api/hotelier/{hid}")
def cabinet(hid: str):
    store = get_store()
    h = store.hotel(hid)
    if not h:
        raise HTTPException(404)
    return {"hotel": {"id": h["id"], "name": h["name"]}, "facts": _resolved(hid),
            "questions": store.questions(hid, status="open"), "answered": store.questions(hid, status="answered"),
            "conflicts": store.conflicts(hid, status=None)}


@app.post("/api/hotelier/{hid}/plan")
def plan(hid: str):
    store = get_store()
    h = _ctx().hotel_by_id.get(hid) or store.hotel(hid)
    return {"created": hotelier.plan_questions(h, store)}


@app.post("/api/questions/{qid}/answer")
def answer(qid: int, text: str = Body(..., embed=True)):
    store = get_store()
    q = store.question(qid)
    if not q:
        raise HTTPException(404)
    with LOCK:
        r = hotelier.answer(qid, text, store)
        INDEX.invalidate(q["hotel_id"])
    return r


@app.post("/api/questions/{qid}/simulate")
def simulate(qid: int):
    store = get_store()
    q = store.question(qid)
    if not q:
        raise HTTPException(404)
    txt = hotelier.simulate_answer(q, store)
    return {"text": txt}


@app.post("/api/facts/{hid}/{key}/correct")
def correct(hid: str, key: str, value=Body(..., embed=True), comment: str = Body("", embed=True)):
    """Кабинет отельера: подтвердить или исправить значение без вопроса."""
    store, reg = get_store(), get_registry()
    spec = reg.get(key)
    if not spec:
        raise HTTPException(404)
    if isinstance(value, str) and spec["type"] == "bool":
        value = value.lower() in ("true", "да", "1", "yes")
    fid = store.add_fact(hid, key, value, 0.9, "hotelier", "кабинет отельера", comment or "указал отельер в кабинете",
                         {}, "hotelier cabinet", spec["ttl_days"], note=comment)
    res = truth.resolve(spec, store.facts(hid, key), store, hid)
    store.log("hotelier", "cabinet", f"отельер указал: {truth.fmt(value)}" + (f" ({comment})" if comment else ""), hid, key)
    if res and not res["conflict"]:
        for c in store.conflicts(hid):
            if c["key"] == key:
                store.resolve_conflict(c["id"], "подтверждено в кабинете отельера")
    store.commit()
    INDEX.invalidate(hid)
    return {"fact_id": fid, "resolved": res}


@app.post("/api/conflicts/{cid}/resolve")
def resolve_conflict(cid: int, winner: str = Body(..., embed=True)):
    store = get_store()
    c = [x for x in store.conflicts(status=None) if x["id"] == cid]
    if not c:
        raise HTTPException(404)
    c = c[0]
    loser = c["fact_b"] if winner == "a" else c["fact_a"]
    store.set_fact_status(loser, "rejected", "отклонён при разборе конфликта")
    store.resolve_conflict(cid, f"принят факт #{c['fact_a'] if winner == 'a' else c['fact_b']}")
    store.commit()
    INDEX.invalidate(c["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------------ актуализация, метрики, разметка

@app.post("/api/refresh/stale")
def refresh_stale():
    with LOCK:
        return refresher.refresh_stale(_ctx())


@app.post("/api/whatif/building")
def whatif(lat: float = Body(...), lon: float = Body(...), height: float = Body(45.0), width: float = Body(60.0),
           depth: float = Body(20.0), angle: float = Body(135.0)):
    with LOCK:
        return refresher.what_if_building(_ctx(), lat, lon, height, width, depth, angle)


@app.get("/api/metrics")
def api_metrics():
    return metrics.compute()


@app.get("/api/labels/queue")
def label_queue(key: str = "sea_view", n: int = 40):
    """Выборка для ручной разметки, стратифицированная по предсказанию: да / нет / неуверенно."""
    store, reg = get_store(), get_registry()
    spec = reg.get(key)
    done = {(l["hotel_id"], l["key"]) for l in store.labels()}
    buckets = {"yes": [], "no": [], "unsure": []}
    for h in store.hotels():
        if (h["id"], key) in done:
            continue
        r = INDEX.get(h["id"]).get(key)
        if not r:
            continue
        b = "unsure" if r["confidence"] < 0.65 else "yes" if r["value"] is True else "no"
        buckets[b].append({"id": h["id"], "name": h["name"], "lat": h["lat"], "lon": h["lon"],
                           "pred": r["value"], "confidence": r["confidence"], "scope": r["scope"]})
    out = []
    while len(out) < n and any(buckets.values()):
        for b in ("yes", "no", "unsure"):
            if buckets[b] and len(out) < n:
                out.append(buckets[b].pop(0))
    return {"key": key, "title": spec["title"] if spec else key, "items": out,
            "labeled": sum(1 for l in store.labels() if l["key"] == key)}


@app.post("/api/labels")
def add_label(hotel_id: str = Body(...), key: str = Body(...), value=Body(...), evidence: str = Body("")):
    store = get_store()
    store.set_label(hotel_id, key, value, "human", evidence)
    store.commit()
    return {"ok": True}


@app.get("/api/log")
def api_log(limit: int = 150):
    return get_store().logs(limit=limit)


# ------------------------------------------------------------------ гость: вид из окна и «совпало?»

def _parse_date(s):
    """«2027-07-15» или «07-15»; всё непонятное → 15 июля."""
    import datetime as dt
    parts = [p for p in (s or "").split("-") if p.isdigit()]
    if len(parts) == 2:
        parts = [str(dt.date.today().year)] + parts
    try:
        x = dt.date(*(int(p) for p in parts[:3]))
        return x.year, x.month, x.day
    except (TypeError, ValueError):
        return dt.date.today().year + 1, 7, 15


@app.get("/api/panorama/{hid}")
def panorama(hid: str, floor: int = 0, date: str = "2027-07-15"):
    from .geo import sun as sun_mod
    from .geo import view as view_mod
    ctx = _ctx()
    h = ctx.hotel_by_id.get(hid)
    if not h:
        raise HTTPException(404)
    floors = view_mod.floors_for(h.get("levels"))
    f = floor if floor > 0 else floors[min(len(floors) - 1, max(0, len(floors) // 2))]
    f = min(max(1, f), max(floors))
    y, m, d = _parse_date(date)
    date = f"{y:04d}-{m:02d}-{d:02d}"
    return {"hotel": {"id": h["id"], "name": h["name"], "levels": h.get("levels"), "levels_src": h.get("levels_src")},
            "floor": f, "floors": list(range(1, max(floors) + 1)), "date": date,
            "sides": [view_mod.panorama(ctx, h, fc, f) for fc in h["facades"]],
            "sun": sun_mod.day_track(h["lat"], h["lon"], y, m, d)}


@app.get("/api/brief/{hid}")
def api_brief(hid: str):
    from .agents.search import brief
    return brief(INDEX.get(hid))


@app.post("/api/guest/feedback")
def guest_feedback(hotel_id: str = Body(...), key: str = Body(...), value=Body(...), comment: str = Body(""),
                   side: str = Body(""), floor: int = Body(0)):
    """Гость после поездки: совпало или нет. Это самый сильный источник проверки — он жил в номере."""
    store, reg = get_store(), get_registry()
    spec = reg.get(key)
    if not spec:
        raise HTTPException(404)
    where = ", ".join(x for x in [f"сторона {side}" if side else "", f"{floor}-й этаж" if floor else ""] if x)
    detail = {"from_floor_min": floor} if floor and spec["scope"] == "room" and value is True else {}
    fid = store.add_fact(hotel_id, key, value, 0.9, "guest", "отзыв гостя после поездки",
                         f"гость: {truth.fmt(value)}" + (f" ({where})" if where else "") + (f" — «{comment}»" if comment else ""),
                         detail, "ответ гостя после поездки", spec["ttl_days"], note=comment, supersede_same_source=False)
    res = truth.resolve(spec, store.facts(hotel_id, key), store, hotel_id)
    if res and res.get("conflict") and not res["conflict"]["resolved"]:
        for f in store.facts(hotel_id, key):
            if f["source_type"] in ("geo", "osm_tag"):
                store.expire_fact(f["id"])
        store.log("guest", "conflict", f"гость не подтвердил «{spec['title']}» — расчёт поставлен на перепроверку",
                  hotel_id, key)
    else:
        store.log("guest", "confirm", f"гость подтвердил «{spec['title']}»: {truth.fmt(value)}", hotel_id, key)
    store.commit()
    INDEX.invalidate(hotel_id)
    return {"fact_id": fid, "resolved": res}


# ------------------------------------------------------------------ отельер: сильные стороны и спрос

def _metric(key, r):
    """Число для сравнения с соседями (больше — лучше) или None."""
    if not r or r.get("value") is None:
        return None
    d = r.get("detail") or {}
    v = r["value"]
    if key in ("sea_view", "mountain_view"):
        f = d.get("from_floor_min")
        return (40 - f) if (v is True and f) else (0 if v is False else None)
    if key == "sunset_view":
        bs = d.get("by_side") or {}
        return max((len(x.get("months") or []) for x in bs.values()), default=0) if v is True else 0
    if key == "quiet_night":
        g = d.get("grid") or r.get("geo_grid") or {}
        n = [x.get("night") for x in g.values() if x.get("night") is not None]
        return -min(n) if n else None
    if key == "beach_walk":
        return -float(v)
    if isinstance(v, bool):
        return 1 if v else 0
    return None


STRENGTH_TEXT = {
    "sea_view": "Вид на море", "sunset_view": "Закаты из окон", "mountain_view": "Горы в окне",
    "quiet_night": "Тишина ночью", "beach_walk": "Близость к пляжу", "beach_no_crossing": "К морю без перехода через трассу и пути",
    "late_food": "Еда рядом после 23:00", "night_pharmacy": "Ночная аптека рядом", "playground": "Детская площадка рядом",
}


@app.get("/api/hotelier/{hid}/insights")
def insights(hid: str):
    store, reg = get_store(), get_registry()
    hs = store.hotels()
    me = INDEX.get(hid)
    strengths = []
    for key, title in STRENGTH_TEXT.items():
        mine = _metric(key, me.get(key))
        if mine is None:
            continue
        others = [x for x in (_metric(key, INDEX.get(h["id"]).get(key)) for h in hs if h["id"] != hid) if x is not None]
        if not others:
            continue
        pct = sum(1 for x in others if x < mine) / len(others)
        strengths.append({"key": key, "title": title, "percentile": round(pct, 2),
                          "scope": me[key]["scope"], "confidence": me[key]["confidence"]})
    strengths.sort(key=lambda s: -s["percentile"])
    counts = store.demand()
    total = sum(counts.values()) or 1
    demand = []
    for s in reg.all():
        if s["scope"] == "region":
            continue
        r = me.get(s["key"])
        demand.append({"key": s["key"], "title": s["title"], "searches": counts.get(s["key"], 0),
                       "share": round(counts.get(s["key"], 0) / total, 3),
                       "you": None if not r else r["value"], "confidence": None if not r else r["confidence"]})
    demand.sort(key=lambda d: -d["searches"])
    known = sum(1 for s in reg.all() if me.get(s["key"]))
    return {"strengths": strengths, "demand": demand[:8], "known": known, "total": len(reg.all()),
            "searches_total": sum(counts.values())}


@app.get("/api/basemap")
def basemap():
    """Своя подложка карты из тех же данных OSM: море, пляжи, парки, дороги, ж/д — без внешних тайлов."""
    global _BASEMAP
    if _BASEMAP is not None:
        return _BASEMAP
    from shapely.geometry import mapping
    ctx = _ctx()

    def ll(geom, tol):
        g = geom.simplify(tol, preserve_topology=False)
        m = mapping(g)

        def conv(c):
            if isinstance(c[0], (int, float)):
                la, lo = ctx.to_ll(c[0], c[1])
                return [round(lo, 5), round(la, 5)]
            return [conv(x) for x in c]
        m["coordinates"] = conv(m["coordinates"]) if m.get("coordinates") else []
        return m

    feats = []
    from shapely.geometry import box as _box
    land = _box(*ctx.frame)
    if ctx.sea_poly is not None:
        land = land.difference(ctx.sea_poly)
    feats.append({"type": "Feature", "properties": {"k": "land"}, "geometry": ll(land, 8)})
    if ctx.sea_poly is not None:
        feats.append({"type": "Feature", "properties": {"k": "sea"}, "geometry": ll(ctx.sea_poly, 8)})
    for b in ctx.beaches:
        if b["geom"].geom_type in ("Polygon", "MultiPolygon"):
            feats.append({"type": "Feature", "properties": {"k": "beach"}, "geometry": ll(b["geom"], 3)})
    for p in ctx.parks:
        if p["geom"].geom_type in ("Polygon", "MultiPolygon") and p["geom"].area > 4000:
            feats.append({"type": "Feature", "properties": {"k": "park"}, "geometry": ll(p["geom"], 5)})
    rank = {"motorway": 1, "trunk": 1, "primary": 2, "secondary": 2, "tertiary": 3, "unclassified": 4, "residential": 4,
            "living_street": 4, "pedestrian": 5}
    for r in ctx.roads:
        k = rank.get(r["hw"].replace("_link", ""))
        if k:
            feats.append({"type": "Feature", "properties": {"k": "road", "r": k}, "geometry": ll(r["geom"], 4)})
    for r in ctx.rails:
        if r["kind"] in ("rail", "light_rail"):
            feats.append({"type": "Feature", "properties": {"k": "rail"}, "geometry": ll(r["geom"], 4)})
    _BASEMAP = {"type": "FeatureCollection", "features": feats}
    return _BASEMAP


@app.get("/api/conflicts")
def all_conflicts(status: str = "open"):
    store = get_store()
    out = []
    for c in store.conflicts(status=status or None):
        h = store.hotel(c["hotel_id"]) or {}
        fa, fb = store.fact(c["fact_a"]), store.fact(c["fact_b"])
        out.append({**c, "hotel": h.get("name", c["hotel_id"]),
                    "a": {k: fa[k] for k in ("source_type", "value", "scope", "confidence", "obtained_at")} if fa else None,
                    "b": {k: fb[k] for k in ("source_type", "value", "scope", "confidence", "obtained_at")} if fb else None})
    return out


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
