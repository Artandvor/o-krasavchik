"""Поиск по запросу на естественном языке.

1. Разбор запроса в критерии (LLM с каталогом характеристик, иначе — правила по синонимам).
2. Оценка каждого отеля по сведённым фактам: соответствие × уверенность.
3. Подбор НОМЕРА: для «номерных» характеристик (вид, тишина) ищем сторону и этаж,
   где все пожелания выполняются одновременно, и честно говорим, если так не бывает.
4. Объяснение: что подходит, что нет, откуда данные, насколько уверены. Готовый текст
   просьбы к отелю — «поселите на ЮЗ сторону не ниже 6 этажа».
"""
import re

from .. import truth
from ..llm import get_llm
from ..registry import get_registry
from ..store import get_store
from ..geo.proj import side_word
from ..tools import MONTHS_FULL, months_text

MONTH_STEMS = ["январ", "феврал", "март", "апрел", "ма[йея]", "июн", "июл", "август", "сентябр", "октябр",
               "ноябр", "декабр"]


class Index:
    """Сведённые значения всех характеристик по отелям в памяти (пересчитываются точечно)."""

    def __init__(self):
        self.data = {}

    def get(self, hid):
        if hid not in self.data:
            self.refresh(hid)
        return self.data[hid]

    def refresh(self, hid=None):
        store, reg = get_store(), get_registry()
        ids = [hid] if hid else [h["id"] for h in store.hotels()]
        region = {s["key"]: truth.resolve(s, store.facts("_region", s["key"]), store, "_region", create=False)
                  for s in reg.all() if s["scope"] == "region"}
        for i in ids:
            d = {}
            for s in reg.all():
                if s["scope"] == "region":
                    d[s["key"]] = region.get(s["key"])
                else:
                    d[s["key"]] = truth.resolve(s, store.facts(i, s["key"]), store, i, create=False)
            self.data[i] = d

    def invalidate(self, hid=None):
        if hid:
            self.data.pop(hid, None)
        else:
            self.data = {}


INDEX = Index()


# ------------------------------------------------------------------ разбор запроса

def rule_parse(text):
    reg = get_registry()
    t = " " + text.lower().replace("ё", "е") + " "
    crit = []
    months = [i + 1 for i, st in enumerate(MONTH_STEMS) if re.search(r"\b" + st, t)]
    for s in reg.all():
        syn = [x.lower().replace("ё", "е") for x in s.get("search", {}).get("synonyms", [])]
        hit = next((x for x in syn if x in t), None)
        if not hit:
            continue
        c = {"key": s["key"], "weight": 1.0, "hard": False, "matched": hit}
        if s["type"] == "number":
            c["op"] = s["search"].get("op", "<=")
            c["number"] = s["search"].get("default")
            m = re.search(r"(\d+)\s*(мин|минут)", t)
            if m:
                c["number"] = float(m.group(1))
            m = re.search(r"(\d{2,4})\s*(м|метр)\b", t)
            if m and s["key"] == "beach_walk":
                c["number"] = round(float(m.group(1)) / 75, 1)  # ~75 м/мин
            m = re.search(r"(\d+[.,]?\d*)\s*км", t)
            if m and s.get("unit") == "км":
                c["number"] = float(m.group(1).replace(",", "."))
            if any(w in t for w in ("первая линия", "у моря", "у самого моря")) and s["key"] == "beach_walk":
                c["number"] = 4
        elif s["type"] in ("bool", "months"):
            c["want"] = s["search"].get("desired", True)
            if s["key"] == "construction_nearby":
                c["want"] = False
        elif s["type"] == "enum":
            if s["search"].get("desired_from_query"):
                c["want"] = next((v for v in s.get("values", []) if v[:4] in t), s.get("values", [None])[0])
                if "песчан" in t or "песок" in t:
                    c["want"] = "песок"
            else:
                c["want"] = s["search"].get("desired")
        if months and s["key"] in ("sunset_view", "swim_season"):
            c["months"] = months
        if re.search(r"(обязательно|главное|важно|точно)[^,.;]{0,40}" + re.escape(hit), t):
            c["weight"], c["hard"] = 2.0, True
        # слабые, «подразумеваемые» критерии
        if hit in ("дети", "с детьми", "ребен", "ребён") and s["key"] in ("beach_no_crossing", "playground"):
            c["weight"] = 0.6
        crit.append(c)
    if months and not any(c["key"] == "swim_season" for c in crit) and re.search(r"купа|мор", t):
        crit.append({"key": "swim_season", "want": True, "months": months, "weight": 0.5, "hard": False})
    return {"criteria": crit, "parser": "rules", "months": months}


def llm_parse(text):
    llm = get_llm()
    if not llm.available:
        return None
    reg = get_registry()
    cat = [{"key": s["key"], "title": s["title"], "type": s["type"], "values": s.get("values"),
            "unit": s.get("unit"), "about": s.get("description", "")[:120]} for s in reg.all()]
    sys_p = ("Разбери запрос путешественника в критерии поиска отелей. Используй ТОЛЬКО ключи из каталога. "
             "Формат: {\"criteria\":[{\"key\":..., \"want\": значение (для bool/enum), \"op\":\"<=\", \"number\": число "
             "(для number, в единицах характеристики; минуты пешком ≈ метры/75), \"months\":[1..12] если упомянуты месяцы, "
             "\"weight\": 0.5|1|2, \"hard\": true если пользователь настаивает}], \"unmatched\": \"что из запроса нет в каталоге\"}. "
             "Для construction_nearby желаемое want=false. Для quiet_night want=\"тихо\".")
    js = llm.json(sys_p, f"Каталог: {cat}\nЗапрос: {text}")
    if not isinstance(js, dict) or "criteria" not in js:
        return None
    valid = {s["key"] for s in reg.all()}
    js["criteria"] = [c for c in js["criteria"] if c.get("key") in valid]
    js["parser"] = f"llm:{llm.model}"
    return js


def parse(text):
    return llm_parse(text) or rule_parse(text)


# ------------------------------------------------------------------ оценка

def _room_p(spec, res, crit):
    """Вероятности по сторонам/этажам для «номерной» характеристики: {side: {floor: p}}."""
    d = (res or {}).get("detail") or {}
    g = d.get("grid") or (res or {}).get("geo_grid") or {}
    out = {}
    for side, v in g.items():
        if spec["key"] == "quiet_night":
            out[side] = {"*": v.get("p_quiet", 0)}
        else:
            ps = {}
            for f, p in v.get("p", {}).items():
                if isinstance(p, list):  # закат по месяцам
                    ms = crit.get("months") or list(range(1, 13))
                    p = max(p[m - 1] for m in ms)
                ps[int(f)] = p
            out[side] = ps
    return out


def score_criterion(spec, res, crit):
    """→ (соответствие 0..1 или None если нет данных, текст)."""
    if res is None or res.get("value") is None:
        return None, "нет данных"
    v = res["value"]
    if spec["scope"] == "room" and spec["type"] == "bool" and res["source_type"] == "geo":
        rp = _room_p(spec, res, crit)
        best = max((p for s in rp.values() for p in s.values()), default=0)
        return (best if crit.get("want", True) else 1 - best), res["scope"]
    if spec["key"] == "quiet_night":
        rp = _room_p(spec, res, crit)
        best = max((p for s in rp.values() for p in s.values()), default=None)
        if best is None:
            return (1.0 if v == "тихо" else 0.5 if v == "умеренно" else 0.1), res["scope"]
        return best, res["scope"]
    if spec["type"] == "number":
        x, lim = float(v), crit.get("number")
        if lim is None:
            return 1.0, res["scope"]
        if crit.get("op", "<=") == "<=":
            return (1.0 if x <= lim else max(0.0, 1 - (x - lim) / max(lim, 1))), res["scope"]
        return (1.0 if x >= lim else max(0.0, x / lim)), res["scope"]
    if spec["type"] == "months":
        ms = crit.get("months")
        if ms:
            ok = [m for m in ms if m in (v or [])]
            return len(ok) / len(ms), res["scope"]
        return (1.0 if v else 0.0), res["scope"]
    want = crit.get("want", spec.get("search", {}).get("desired", True))
    if isinstance(v, str) and isinstance(want, str):
        return (1.0 if v.startswith(want[:4]) else 0.0), res["scope"]
    return (1.0 if v == want else 0.0), res["scope"]


def recommend_room(hotel, crits, resolved, reg):
    """Ищем сторону × этаж, где одновременно выполняются все «номерные» пожелания."""
    room = [(c, reg.get(c["key"])) for c in crits if reg.get(c["key"]) and reg.get(c["key"])["scope"] == "room"]
    room = [(c, s) for c, s in room if resolved.get(c["key"]) and
            ((resolved[c["key"]].get("detail") or {}).get("grid") or resolved[c["key"]].get("geo_grid"))]
    if not room:
        return None
    grids = [(c, s, _room_p(s, resolved[c["key"]], c)) for c, s in room]
    sides = set.intersection(*[set(g.keys()) for _, _, g in grids])
    best = None
    for side in sides:
        floors = sorted({f for _, _, g in grids for f in g[side] if f != "*"}) or ["*"]
        for f in floors:
            p = 1.0
            parts = []
            for c, s, g in grids:
                pg = g[side]
                pv = pg.get(f, pg.get("*", 0)) if f != "*" else max(pg.values())
                p *= pv
                parts.append((s["title"], pv))
            cand = (p, side, f, parts)
            # при равной вероятности — ниже этаж (больше таких номеров)
            if best is None or p > best[0] + 1e-6 or (abs(p - best[0]) < 1e-6 and f != "*" and best[2] != "*" and f < best[2]):
                best = cand
    if best is None or best[0] < 0.02:
        return {"ok": False, "p": 0.0, "parts": [],
                "text": "в одном окне всё сразу не сходится: нужное — с разных сторон здания"}
    p, side, f, parts = best
    if p < 0.5:
        weak = min(parts, key=lambda t: t[1])
        return {"ok": False, "side": side, "floor": f, "p": round(p, 2),
                "parts": [{"title": t, "p": round(pv, 2)} for t, pv in parts],
                "text": f"гарантировать всё сразу нельзя; лучший шанс — окна на {side_word(side)}"
                        + (f", с {f}-го этажа" if f not in ("*", 1) else "") + ": "
                        + ", ".join(f"{t.lower()} {pv:.0%}" for t, pv in parts) + f" (слабое место — {weak[0].lower()})"}
    floor_txt = f"не ниже {f}-го этажа" if f not in ("*", 1) else ""
    titles = ", ".join(t.lower() for t, _ in parts)
    req = (f"Здравствуйте! Планирую бронирование. Если возможно, поселите, пожалуйста, в номер с окнами на "
           f"{side_word(side)}" + (f" {floor_txt}" if floor_txt else "") + f" — для нас важно: {titles}. Спасибо!")
    return {"ok": True, "side": side, "floor": f, "p": round(p, 2),
            "parts": [{"title": t, "p": round(pv, 2)} for t, pv in parts],
            "text": f"номер с окнами на {side_word(side)}" + (f", {floor_txt}" if floor_txt else "") + f" — вероятность {p:.0%}",
            "request": req}


def brief(resolved):
    """Компактная сводка фактов для карточки гостя: из неё строятся «обещания»."""
    def r(k):
        return resolved.get(k) or {}
    out = {"views": {}, "conflicts": [k for k, v in resolved.items() if v and v.get("conflict") and not v["conflict"]["resolved"]]}
    for k in ("sea_view", "sunset_view", "mountain_view"):
        d = (r(k).get("detail") or {}).get("by_side") or {}
        out["views"][k] = {side: v.get("from_floor") for side, v in d.items() if isinstance(v, dict)}
        out[k + "_conf"] = r(k).get("confidence")
        out[k + "_value"] = r(k).get("value")
    bw = r("beach_walk")
    if bw:
        det = bw.get("detail") or {}
        out["beach"] = {"min": bw.get("value"), "m": det.get("length_m"), "straight": det.get("straight_to_sea_m"),
                        "rail": det.get("rail_crossings") or [], "roads": [x.get("road") for x in det.get("road_crossings") or []],
                        "name": det.get("beach_name"), "surface": det.get("beach_surface"), "gain": det.get("gain_m"),
                        "conf": bw.get("confidence")}
    qn = r("quiet_night")
    g = (qn.get("detail") or {}).get("grid") or qn.get("geo_grid") or {}
    out["quiet"] = {side: v.get("night") for side, v in g.items()}
    out["quiet_conf"] = qn.get("confidence")
    for k in ("late_food", "night_pharmacy", "playground", "pets", "car_access", "construction_nearby", "beach_no_crossing"):
        out[k] = r(k).get("value")
    sw = r("swim_season")
    if sw:
        out["climate"] = {"sea": (sw.get("detail") or {}).get("sea"), "air": (sw.get("detail") or {}).get("air_max"),
                          "swim": sw.get("value")}
    return out


def search(text, limit=20, log=True, month=None):
    store, reg = get_store(), get_registry()
    q = parse(text)
    crits = q["criteria"]
    if month:  # месяц поездки: закат и купание проверяем именно для него
        for c in crits:
            if c["key"] in ("sunset_view", "swim_season") and not c.get("months"):
                c["months"] = [int(month)]
    hotels = store.hotels()
    results = []
    for h in hotels:
        resolved = INDEX.get(h["id"])
        total = wsum = 0.0
        lines, excluded = [], False
        for c in crits:
            spec = reg.get(c["key"])
            if not spec:
                continue
            w = float(c.get("weight", 1.0))
            res = resolved.get(c["key"])
            s, why = score_criterion(spec, res, c)
            wsum += w
            if s is None:
                total += w * 0.3
                status = "?"
                conf = 0
            else:
                conf = res["confidence"]
                total += w * s * (0.6 + 0.4 * conf)
                status = "✓" if s >= 0.7 else "~" if s >= 0.35 else "✗"
                if c.get("hard") and s < 0.3 and conf >= 0.6:
                    excluded = True
            src = ""
            if res:
                src = ", ".join(sorted({truth.source_name(x["type"]) for x in res["sources"]}))
            lines.append({"key": c["key"], "title": spec["title"], "status": status, "match": None if s is None else round(s, 2),
                          "confidence": conf, "text": why, "sources": src,
                          "conflict": bool(res and res.get("conflict") and not res["conflict"]["resolved"]),
                          "stale": bool(res and res.get("stale"))})
        if excluded:
            continue
        score = total / wsum if wsum else 0.0
        room = recommend_room(h, crits, resolved, reg)
        n_room = sum(1 for c in crits if reg.get(c["key"]) and reg.get(c["key"])["scope"] == "room")
        if room is not None and n_room >= 2:
            # несколько «оконных» желаний должны сбыться в ОДНОМ окне, а не в разных
            score *= 0.45 + 0.55 * room.get("p", 0)
        results.append({"id": h["id"], "name": h["name"], "kind": h["kind"], "lat": h["lat"], "lon": h["lon"],
                        "stars": h.get("stars"), "address": h.get("address"), "score": round(100 * score),
                        "levels": h.get("levels"), "lines": lines, "room": room, "brief": brief(resolved)})
    results.sort(key=lambda r: -r["score"])
    if log:
        store.log_search(text, {"criteria": crits, "parser": q.get("parser")}, len(results))
        store.commit()
    return {"query": text, "parsed": q, "results": results[:limit], "total": len(results)}


__all__ = ["search", "parse", "INDEX", "months_text", "MONTHS_FULL"]
