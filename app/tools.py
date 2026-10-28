"""Инструменты агента-сборщика. Каждый инструмент получает (ctx, hotel, spec, cache) и
возвращает список кандидатов в факты. Новые характеристики переиспользуют инструменты
через params — код инструментов не меняется.

Каждый кандидат: {value, confidence, scope, detail, source_type, source_ref, method, note}
"""
import re
import json
import math

import numpy as np
from shapely.geometry import Point

from .config import METHOD_VERSION, RAW
from .geo import noise as noise_mod
from .geo.osm import hours_ru, hw_ru, poi_name
from .geo import view as view_mod
from .geo import walk as walk_mod
from .geo.proj import az_name, side_word

MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_IN = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре",
             "октябре", "ноябре", "декабре"]


# человеческие названия инструментов — для журнала агентов
TOOL_RU = {"viewshed": "расчёт вида", "facade_noise": "модель шума", "walk_route": "пеший маршрут",
           "poi_nearby": "места рядом", "distance_to": "расстояние", "drive_access": "подъезд на машине",
           "construction_nearby": "стройки рядом", "building_history": "история здания", "osm_tag": "теги карты",
           "hotelier_only": "только у отельера", "climate": "климат"}
PARSER_RU = {"rules": "по правилам", "llm": "языковой моделью"}

PARKING_RU = {"underground": "подземная", "surface": "наземная", "multi-storey": "многоуровневая", "rooftop": "на крыше",
              "street_side": "вдоль улицы", "lane": "вдоль улицы", "yes": "есть", "no": "нет", "private": "своя"}


def ru_date(iso):
    """2023-05-01 → 01.05.2023"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m[3]}.{m[2]}.{m[1]}" if m else (iso or "")


MONTHS_FULL = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь",
               "октябрь", "ноябрь", "декабрь"]

TOOLS = {}


def tool(name, description, params_doc):
    def deco(fn):
        TOOLS[name] = {"fn": fn, "description": description, "params": params_doc}
        return fn
    return deco


def months_text(ms):
    """[4,5,6,7,8] → 'апр–авг'; учитывает разрывы."""
    if not ms:
        return ""
    ms = sorted(ms)
    groups, start, prev = [], ms[0], ms[0]
    for m in ms[1:]:
        if m == prev + 1:
            prev = m
            continue
        groups.append((start, prev))
        start = prev = m
    groups.append((start, prev))
    if len(groups) > 1 and groups[0][0] == 1 and groups[-1][1] == 12:  # дек–фев
        groups = [(groups[-1][0], groups[0][1])] + groups[1:-1]
    if len(ms) == 12:
        return "круглый год"
    return ", ".join(MONTHS[a - 1] if a == b else f"{MONTHS[a - 1]}–{MONTHS[b - 1]}" for a, b in groups)


def osm_url(ref):
    return f"https://www.openstreetmap.org/{ref}" if ref else ""


# ====================================================================== viewshed

def _views(ctx, hotel, cache):
    if "views" not in cache:
        cache["views"] = view_mod.hotel_views(ctx, hotel)
    return cache["views"]


@tool("viewshed", "Расчёт прямой видимости из окон по рельефу и зданиям с Монте-Карло по неизвестным высотам.",
      {"target": "sea | sunset | mountain", "min_prob": "порог вероятности для «да», 0..1"})
def t_viewshed(ctx, hotel, spec, cache):
    V = _views(ctx, hotel, cache)
    target = spec["params"]["target"]
    thr = spec["params"].get("min_prob", 0.6)
    q = V["quality"]
    by_side, grid = {}, {}
    best = (0.0, None, None)
    for fv in V["facades"]:
        side = fv["side"]
        g = {}
        for f, r in fv["floors"].items():
            if target == "sea":
                p = r["p_sea"]
            elif target == "mountain":
                p = r["p_mountain"]
            else:
                p = max(r["sunset"])
            g[int(f)] = [round(x * q, 3) for x in r["sunset"]] if target == "sunset" else round(p * q, 3)
            if p > best[0]:
                best = (p, side, int(f))
        grid[side] = {"az": fv["az"], "p": g}
        good = [int(f) for f, r in fv["floors"].items() if
                (r["p_sea"] if target == "sea" else r["p_mountain"] if target == "mountain" else max(r["sunset"])) >= thr]
        if good:
            f0 = min(good)
            r0 = fv["floors"][f0]
            info = {"from_floor": f0, "p": round(
                (r0["p_sea"] if target == "sea" else r0["p_mountain"] if target == "mountain" else max(r0["sunset"])) * q, 2)}
            if target == "sea":
                info.update({"share": r0["sea_share"], "dist_m": r0["sea_dist_m"],
                             "front": r0["p_sea_front"] >= thr})
            if target == "sunset":
                ms = [i + 1 for i, p in enumerate(r0["sunset"]) if p >= thr]
                info.update({"months": ms, "months_text": months_text(ms),
                             "over_sea": max(r0["sunset_over_sea"]) >= thr})
            by_side[side] = info
    anyv = bool(by_side)
    if anyv:
        parts = []
        for side, i in sorted(by_side.items(), key=lambda kv: kv[1]["from_floor"]):
            s = f"окна на {side_word(side)}, с {i['from_floor']}-го этажа"
            if target == "sunset" and i.get("months_text"):
                s += f" ({i['months_text']}{', над морем' if i.get('over_sea') else ''})"
            if target == "sea":
                q_ = []
                if not i.get("front"):
                    q_.append("боковой вид")
                if i.get("dist_m") and i["dist_m"] > 1500:
                    q_.append(f"море вдали, ~{i['dist_m'] / 1000:.1f} км")
                elif i.get("share") is not None and i["share"] < 0.15:
                    q_.append("узкая полоска моря")
                if q_:
                    s += " (" + ", ".join(q_) + ")"
            parts.append(s)
        summary = "; ".join(parts)
        conf = max(i["p"] for i in by_side.values())
    else:
        summary = "ни из одного окна, ни с одного этажа"
        conf = (1 - best[0]) * q
    detail = {"by_side": by_side, "grid": grid, "floors": V["floors"], "quality": q,
              "from_floor_min": min((i["from_floor"] for i in by_side.values()), default=None),
              "notes": V["notes"], "n_samples": V["n_samples"],
              "unknown_height_share": V["unknown_height_share"], "built_share": V["built_share"]}
    if target == "sea":
        detail["sea_rays"] = {fv["side"]: fv["floors"][max(fv["floors"])]["sea_rays"] for fv in V["facades"]}
    if target in ("sunset", "mountain"):
        detail["horizon"] = {fv["side"]: {"azs": fv["azs"], "deg": fv["floors"][min(fv["floors"])]["horizon_deg"]}
                             for fv in V["facades"]}
    method = (f"viewshed/{target} {METHOD_VERSION}: лучи через 2° в секторе ±60° от фасада, шаг 9 м до 4 км "
              f"+ 150 м до 60 км; {V['n_samples']} сценариев высот зданий")
    return [{"value": anyv, "confidence": round(min(conf, 0.9), 3), "scope": summary, "detail": detail,
             "source_type": "geo", "source_ref": "Copernicus DEM GLO-30 + OSM buildings", "method": method}]


# ====================================================================== noise

@tool("facade_noise", "Модель ночного/дневного шума у каждого фасада от дорог, ж/д, заведений, аэропорта.", {})
def t_noise(ctx, hotel, spec, cache):
    if "noise" not in cache:
        cache["noise"] = {f["side"]: {**noise_mod.facade_noise(ctx, f, hotel.get("building_idx")), "az": f["az"]}
                          for f in hotel["facades"]}
    N = cache["noise"]
    quiet = min(N.items(), key=lambda kv: kv[1]["night"])
    loud = max(N.items(), key=lambda kv: kv[1]["night"])
    cls = noise_mod.night_class(quiet[1]["night"])
    margin = min(abs(quiet[1]["night"] - 45), abs(quiet[1]["night"] - 55))
    conf = 0.65 if margin >= 4 else 0.5
    if not hotel.get("footprint_known"):
        conf *= 0.8
    grid = {s: {"az": v["az"], "night": v["night"], "day": v["day"],
                "p_quiet": round(1 / (1 + math.exp((v["night"] - 45) / 2.5)), 3)} for s, v in N.items()}
    src = ", ".join(f"{t['name']} {t['dist_m']} м" for t in loud[1]["top"][:2])
    summary = (f"тише всего окна на {side_word(quiet[0])}: ночью ~{quiet[1]['night']:.0f} дБ ({cls}); "
               f"громче всего на {side_word(loud[0])}: ~{loud[1]['night']:.0f} дБ" + (f" ({src})" if src else ""))
    return [{"value": cls, "confidence": round(conf, 3), "scope": summary,
             "detail": {"by_side": N, "grid": grid, "quiet_side": quiet[0], "loud_side": loud[0]},
             "source_type": "geo", "source_ref": "OSM roads/rail/amenities/aeroway",
             "method": f"noise {METHOD_VERSION}: элементы источников ≤20 м, сферическое расхождение, "
                       f"поглощение, экранирование по растру зданий, самоэкранирование фасада"}]


# ====================================================================== walking

@tool("walk_route", "Пеший маршрут по графу OSM с рельефом (Тоблер), переходы через ж/д и крупные дороги.",
      {"target": "beach", "metric": "minutes | no_crossing | surface"})
def t_walk(ctx, hotel, spec, cache):
    if "beach" not in cache:
        cache["beach"] = walk_mod.beach_route(ctx, hotel)
    r = cache["beach"]
    metric = spec["params"].get("metric", "minutes")
    if r is None:
        return []
    ref = r.get("beach_osm")
    base_conf = 0.85 if r["target_source"] == "osm:natural=beach" else 0.65
    if metric == "minutes":
        parts = ["первая линия, выход к пляжу сразу" if r["length_m"] < 40 else
                 f"{max(1, round(r['minutes']))} мин пешком, {r['length_m']} м"]
        if r.get("straight_to_sea_m") is not None:
            parts.append(f"по прямой до воды {r['straight_to_sea_m']} м")
        if r["gain_m"] >= 5:
            parts.append(f"набор высоты {r['gain_m']:.0f} м")
        if r["rail_crossings"]:
            parts.append("переход через ж/д: " + r["rail_crossings"][0])
        if r["beach_name"]:
            parts.append(f"пляж «{r['beach_name']}»")
        return [{"value": r["minutes"], "confidence": base_conf, "scope": ", ".join(parts), "detail": r,
                 "source_type": "geo", "source_ref": osm_url(ref),
                 "method": f"walk {METHOD_VERSION}: Дейкстра по пешеходному графу OSM, скорость по Тоблеру"}]
    if metric == "no_crossing":
        ok = not r["rail_crossings"] and not r["road_crossings"]
        bits = []
        if r["rail_crossings"]:
            bits.append("ж/д (" + "; ".join(r["rail_crossings"]) + ")")
        for x in r["road_crossings"]:
            bits.append(f"{x['road']} ({x['how']})")
        summary = "переходить ничего не нужно" if ok else "по пути: " + ", ".join(bits)
        return [{"value": ok, "confidence": round(base_conf - 0.05, 3), "scope": summary,
                 "detail": {"rail": r["rail_crossings"], "roads": r["road_crossings"], "route": r["coords_ll"]},
                 "source_type": "geo", "source_ref": osm_url(ref),
                 "method": f"walk {METHOD_VERSION}: пересечения маршрута с railway=* и highway∈{{trunk,primary,secondary}}"}]
    if metric == "surface":
        if not r.get("beach_surface"):
            return []
        return [{"value": r["beach_surface"], "confidence": 0.65,
                 "scope": f"пляж «{r['beach_name'] or 'без названия'}»: {r['beach_surface']}",
                 "detail": {"beach": r["beach_name"]}, "source_type": "osm_tag", "source_ref": osm_url(ref),
                 "method": "osm natural=beach surface"}]
    return []


# ====================================================================== POI

def _layer(ctx, name):
    cache = ctx.__dict__.setdefault("_layers", {})
    if name not in cache:
        cache[name] = _build_layer(ctx, name)
    return cache[name]


def _build_layer(ctx, name):
    if name == "pois":
        return [{"x": p["x"], "y": p["y"], "tags": p["tags"], "osm": p["osm"], "timestamp": p.get("timestamp")}
                for p in ctx.pois]
    items = getattr(ctx, name, [])
    out = []
    for it in items:
        c = it["geom"].centroid if hasattr(it["geom"], "centroid") else it["geom"]
        label = {"playgrounds": "детская площадка", "parks": "парк", "beaches": "пляж"}.get(name, "")
        out.append({"x": c.x, "y": c.y, "tags": {"name": it.get("name") or label}, "osm": it.get("osm"),
                    "timestamp": it.get("timestamp")})
    return out


@tool("poi_nearby", "Ищет объекты OSM по тегам в пешей доступности (по графу), опционально с часами работы.",
      {"layer": "pois | playgrounds | parks | beaches", "filter": "{тег: значение|[значения]|'*'|'re:...'}",
       "radius_m": "радиус пешком, м", "open_after": "HH:MM — работает после этого времени", "min_count": "мин. число"})
def t_poi(ctx, hotel, spec, cache):
    p = spec["params"]
    layer = p.get("layer", "pois")
    items = _layer(ctx, layer)
    flt = p.get("filter")
    radius = float(p.get("radius_m", 500))
    reach = walk_mod.reachable(ctx, hotel, cutoff_m=max(radius, 1500))
    found, unknown_hours = [], 0
    hx, hy = hotel["x"], hotel["y"]
    for it in items:
        if flt and not walk_mod.match_filter(it["tags"], flt):
            continue
        straight = math.hypot(it["x"] - hx, it["y"] - hy)
        if straight > radius * 1.2:
            continue
        n = ctx.nearest_node(it["x"], it["y"], max_d=150)
        dist = None
        if n is not None and n in reach:
            snap = math.hypot(ctx.graph.nodes[n]["x"] - it["x"], ctx.graph.nodes[n]["y"] - it["y"])
            dist = reach[n] + snap
        if dist is None:
            dist = straight * 1.4 if not reach else None
        if dist is None or dist > radius:
            continue
        if p.get("open_after"):
            oa = walk_mod.open_after(it["tags"].get("opening_hours"), p["open_after"])
            if oa is None:
                unknown_hours += 1
                continue
            if not oa:
                continue
        found.append({"name": poi_name(it["tags"]),
                      "dist_m": int(dist), "hours": it["tags"].get("opening_hours"), "osm": it["osm"],
                      "edited": it.get("timestamp"),
                      "ll": [round(v, 6) for v in ctx.to_ll(it["x"], it["y"])]})
    found.sort(key=lambda f: f["dist_m"])
    ok = len(found) >= int(p.get("min_count", 1))
    if ok:
        conf = 0.75
        stale = [f for f in found[:3] if f.get("edited") and f["edited"][:4] < "2023"]
        if stale and len(stale) == len(found[:3]):
            conf = 0.6
        summary = ", ".join(f"{f['name']} — {f['dist_m']} м" + (f" ({hours_ru(f['hours'])})" if f["hours"] and p.get("open_after") else "")
                            for f in found[:3])
    else:
        # «не нашли» менее надёжно, чем «нашли»: в OSM может просто не быть данных
        conf = 0.45 if unknown_hours else 0.55
        summary = f"в {int(radius)} м не найдено" + (f" (ещё {unknown_hours} — часы работы не указаны)" if unknown_hours else "")
    return [{"value": ok, "confidence": conf, "scope": summary,
             "detail": {"items": found[:10], "count": len(found), "unknown_hours": unknown_hours, "radius_m": radius},
             "source_type": "osm_tag", "source_ref": osm_url(found[0]["osm"]) if found else "OpenStreetMap",
             "method": f"poi_nearby {METHOD_VERSION}: {json.dumps(flt, ensure_ascii=False)} в {int(radius)} м по графу"
                       + (f", открыто после {p['open_after']}" if p.get("open_after") else "")}]


@tool("distance_to", "Расстояние по прямой до ближайшего объекта OSM, подходящего под фильтр.",
      {"layer": "pois", "filter": "теги (ИЛИ)", "require": "обязательные теги (ИЛИ)"})
def t_distance(ctx, hotel, spec, cache):
    p = spec["params"]
    best = None
    for it in _layer(ctx, p.get("layer", "pois")):
        if p.get("require") and not walk_mod.match_filter(it["tags"], p["require"]):
            continue
        if p.get("filter") and not walk_mod.match_filter(it["tags"], p["filter"]):
            continue
        d = math.hypot(it["x"] - hotel["x"], it["y"] - hotel["y"])
        if best is None or d < best[0]:
            best = (d, it)
    if best is None:
        return [{"value": None, "confidence": 0.3, "scope": "в данных OSM не найдено", "detail": {},
                 "source_type": "osm_tag", "source_ref": "OpenStreetMap", "method": "distance_to"}]
    d, it = best
    return [{"value": round(d / 1000, 1), "confidence": 0.7,
             "scope": f"{poi_name(it['tags'])} — {d / 1000:.1f} км по прямой",
             "detail": {"name": it["tags"].get("name"), "osm": it["osm"],
                        "ll": [round(v, 6) for v in ctx.to_ll(it["x"], it["y"])]},
             "source_type": "osm_tag", "source_ref": osm_url(it["osm"]), "method": f"distance_to {METHOD_VERSION}"}]


@tool("drive_access", "Есть ли проезжая дорога у входа, пешеходная ли зона, парковки рядом.",
      {"max_road_m": "м до проезжей дороги", "parking_radius_m": "м до парковки"})
def t_drive(ctx, hotel, spec, cache):
    p = spec["params"]
    pt = Point(hotel["x"], hotel["y"])
    fp_r = 0.0
    if hotel.get("building_idx") is not None:
        fp_r = math.sqrt(ctx.buildings[hotel["building_idx"]]["area"] / math.pi)
    if getattr(ctx, "_road_tree", None) is None:
        import shapely
        ctx._road_tree = shapely.STRtree([r["geom"] for r in ctx.roads]) if ctx.roads else None
    cand = [ctx.roads[int(i)] for i in ctx._road_tree.query(pt.buffer(300))] if ctx._road_tree is not None else []
    near = [(r["geom"].distance(pt) - fp_r, r) for r in cand if r["motor"]]
    near = [t for t in near if t[0] < 300]
    near.sort(key=lambda t: t[0])
    ped = [r for r in cand if r["hw"] == "pedestrian" and r["geom"].distance(pt) < 25 + fp_r]
    ok = bool(near) and near[0][0] <= p.get("max_road_m", 30)
    parkings = []
    for it in ctx.pois:
        if it["tags"].get("amenity") == "parking":
            d = math.hypot(it["x"] - hotel["x"], it["y"] - hotel["y"])
            if d <= p.get("parking_radius_m", 300):
                parkings.append({"name": poi_name(it["tags"]), "dist_m": int(d),
                                 "fee": it["tags"].get("fee"), "osm": it["osm"]})
    parkings.sort(key=lambda x: x["dist_m"])
    if ok:
        r = near[0][1]
        summary = f"подъезд: {r['name'] or hw_ru(r['hw'])}, ~{max(0, int(near[0][0]))} м до входа"
    else:
        summary = "проезжей дороги рядом со входом нет" + (" — пешеходная зона" if ped else "")
    summary += f"; парковок в {p.get('parking_radius_m', 300)} м: {len(parkings)}"
    tags = hotel.get("tags", {})
    if tags.get("parking"):
        summary += f"; у отеля на карте указана парковка: {PARKING_RU.get(tags['parking'], tags['parking'])}"
    return [{"value": ok, "confidence": 0.7 if hotel.get("footprint_known") else 0.55, "scope": summary,
             "detail": {"nearest_road": near[0][1]["name"] if near else None, "pedestrian_zone": bool(ped),
                        "parkings": parkings[:5]},
             "source_type": "geo", "source_ref": "OSM highway + amenity=parking",
             "method": f"drive_access {METHOD_VERSION}"}]


@tool("construction_nearby", "Стройки из OSM рядом с отелем.", {"radius_m": "радиус, м"})
def t_construction(ctx, hotel, spec, cache):
    pt = Point(hotel["x"], hotel["y"])
    rad = spec["params"].get("radius_m", 300)
    hits = []
    for c in ctx.construction:
        d = c["geom"].distance(pt)
        if d <= rad:
            hits.append({"dist_m": int(d), "name": c.get("name") or "стройка",
                         "osm": c["osm"], "edited": c.get("timestamp")})
    hits.sort(key=lambda h: h["dist_m"])
    if hits:
        h = hits[0]
        summary = f"{h['name']} в {h['dist_m']} м, на карте с правкой от {ru_date(h['edited'])}"
        conf = 0.6 if (h["edited"] or "") >= "2025" else 0.4  # старая отметка — стройка могла закончиться
    else:
        summary, conf = f"в {rad} м не отмечено", 0.55
    return [{"value": bool(hits), "confidence": conf, "scope": summary, "detail": {"items": hits[:5]},
             "source_type": "osm_tag", "source_ref": osm_url(hits[0]["osm"]) if hits else "OpenStreetMap",
             "method": f"construction {METHOD_VERSION}"}]


@tool("building_history", "Год постройки, стиль и статус памятника из тегов OSM.", {})
def t_history(ctx, hotel, spec, cache):
    t = {**hotel.get("building_tags", {}), **hotel.get("tags", {})}
    bits = []
    if t.get("start_date"):
        bits.append(f"построено: {t['start_date']}")
    if t.get("building:architecture"):
        bits.append(f"стиль: {t['building:architecture']}")
    if t.get("heritage"):
        bits.append("объект культурного наследия")
    if not bits:
        return []
    return [{"value": "; ".join(bits), "confidence": 0.6, "scope": "; ".join(bits), "detail": {},
             "source_type": "osm_tag", "source_ref": osm_url(hotel["osm"]), "method": "osm tags"}]


@tool("osm_tag", "Прямое чтение тега OSM у объекта отеля с отображением значений.",
      {"tags": "{тег: {значение_osm: значение_характеристики}}"})
def t_osm_tag(ctx, hotel, spec, cache):
    t = hotel.get("tags", {})
    for tag, mapping in spec["params"].get("tags", {}).items():
        if tag in t:
            v = t[tag]
            val = mapping.get(v, v) if isinstance(mapping, dict) else v
            edited = hotel.get("osm_timestamp") or ""
            conf = 0.55 if edited >= "2023" else 0.4
            shown = {True: "да", False: "нет"}.get(val, val)
            return [{"value": val, "confidence": conf, "scope": f"по данным OpenStreetMap: {shown} (правка от {ru_date(edited)})",
                     "detail": {"tag": tag, "raw": v}, "source_type": "osm_tag",
                     "source_ref": osm_url(hotel["osm"]), "method": "osm tag"}]
    return []


@tool("hotelier_only", "Нет открытого источника — значение получаем только от отельера.", {})
def t_hotelier_only(ctx, hotel, spec, cache):
    return []


# ====================================================================== climate (регион)

def climate_table():
    """Средние по месяцам из Open-Meteo: воздух (ERA5 2016–2025), море (Marine 2023–2025), солнце."""
    out = {"air_max": [None] * 12, "air_min": [None] * 12, "sea": [None] * 12, "sun_h": [None] * 12,
           "rain_days": [None] * 12, "pm25": [None] * 12, "sources": []}
    p = RAW / "climate_daily.json"
    if p.exists():
        d = json.loads(p.read_text())["daily"]
        months = np.array([int(s[5:7]) for s in d["time"]])
        years = len(set(s[:4] for s in d["time"]))
        for key, src in (("air_max", "temperature_2m_max"), ("air_min", "temperature_2m_min")):
            a = np.array([np.nan if v is None else v for v in d[src]], dtype=float)
            out[key] = [round(float(np.nanmean(a[months == m])), 1) for m in range(1, 13)]
        sun = np.array([np.nan if v is None else v for v in d["sunshine_duration"]], dtype=float) / 3600
        out["sun_h"] = [round(float(np.nanmean(sun[months == m])), 1) for m in range(1, 13)]
        pr = np.array([0 if v is None else v for v in d["precipitation_sum"]], dtype=float)
        out["rain_days"] = [round(float(np.sum((pr >= 1) & (months == m)) / years), 1) for m in range(1, 13)]
        out["sources"].append("Open-Meteo Historical Weather (ERA5), 2016–2025")
    p = RAW / "marine_hourly.json"
    if p.exists():
        d = json.loads(p.read_text()).get("hourly", {})
        if d.get("sea_surface_temperature"):
            months = np.array([int(s[5:7]) for s in d["time"]])
            a = np.array([np.nan if v is None else v for v in d["sea_surface_temperature"]], dtype=float)
            out["sea"] = [round(float(np.nanmean(a[months == m])), 1) if np.any(~np.isnan(a[months == m])) else None
                          for m in range(1, 13)]
            out["sources"].append("Open-Meteo Marine API, 2023–2025")
    p = RAW / "air_quality.json"
    if p.exists():
        d = json.loads(p.read_text()).get("hourly", {})
        if d.get("pm2_5"):
            months = np.array([int(s[5:7]) for s in d["time"]])
            a = np.array([np.nan if v is None else v for v in d["pm2_5"]], dtype=float)
            out["pm25"] = [round(float(np.nanmean(a[months == m])), 1) for m in range(1, 13)]
            out["sources"].append("Open-Meteo Air Quality (CAMS), 2024–2025")
    return out


@tool("climate", "Климат и море по месяцам из открытых исторических данных (на регион).",
      {"sea_min": "°C моря", "air_min": "°C воздуха днём"})
def t_climate(ctx, hotel, spec, cache):
    if "climate" not in cache:
        cache["climate"] = climate_table()
    c = cache["climate"]
    if not c["sources"]:
        return []
    p = spec["params"]
    if p.get("metric") == "air":
        pm = c["pm25"]
        if not any(v is not None for v in pm):
            return []
        lim = p.get("pm25_max", 10)
        ms = [i + 1 for i, v in enumerate(pm) if v is not None and v <= lim]
        avg = sum(v for v in pm if v is not None) / len([v for v in pm if v is not None])
        worst = max(range(12), key=lambda i: pm[i] or 0)
        summary = (f"PM2.5 в среднем {avg:.0f} мкг/м³; чище всего: {months_text(ms) or '—'}; "
                   f"хуже всего в {MONTHS_IN[worst]} ({pm[worst]:.0f})")
        return [{"value": ms, "confidence": 0.7, "scope": summary, "detail": {"pm25": pm},
                 "source_type": "open_api", "source_ref": "Open-Meteo Air Quality (CAMS), 2024–2025",
                 "method": f"air {METHOD_VERSION}: среднемесячный PM2.5 модели CAMS (сетка ~11 км)"}]
    ms = []
    for m in range(12):
        sea_ok = c["sea"][m] is None or c["sea"][m] >= p.get("sea_min", 20)
        air_ok = c["air_max"][m] is not None and c["air_max"][m] >= p.get("air_min", 22)
        if sea_ok and air_ok and (c["sea"][m] is not None or c["air_max"][m] >= 26):
            ms.append(m + 1)
    summary = f"купальный сезон: {months_text(ms)}" + (
        f"; в октябре море ~{c['sea'][9]:.0f} °C" if c["sea"][9] is not None else "")
    return [{"value": ms, "confidence": 0.85 if c["sea"][0] is not None else 0.6, "scope": summary,
             "detail": c, "source_type": "open_api", "source_ref": "; ".join(c["sources"]),
             "method": f"climate {METHOD_VERSION}: средние по месяцам"}]


def catalog():
    """Описание инструментов для LLM-компилятора характеристик."""
    return {k: {"description": v["description"], "params": v["params"]} for k, v in TOOLS.items()}


__all__ = ["TOOLS", "catalog", "months_text", "az_name", "MONTHS", "MONTHS_FULL", "MONTHS_IN", "ru_date", "TOOL_RU", "PARSER_RU"]
