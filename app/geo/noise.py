"""Оценка шума у каждого фасада. Упрощённая инженерная модель (по мотивам ISO 9613 / CNOSSOS):
источники разбиты на элементы ≤ 20 м, для каждого элемента — сферическое расхождение,
поглощение воздухом, экранирование зданиями (по растру), самоэкранирование фасадом.

Открытых шумовых карт по России нет (в отличие от END-карт ЕС), поэтому уровни
излучения взяты типовые по классу дороги — это модель, а не измерение; уверенность
факта отражает это (≤ 0.65), а отельер может подтвердить/уточнить.
"""
import math

import numpy as np
import shapely

from .osm import hw_ru, poi_name

# уровень у дороги на 10 м, дБА: (день, ночь)
ROAD_LREF = {
    "motorway": (77, 71), "trunk": (74, 68), "primary": (71, 63), "secondary": (67, 59),
    "tertiary": (63, 54), "unclassified": (58, 48), "residential": (55, 45), "living_street": (50, 40),
    "service": (50, 40), "road": (55, 45),
}
RAIL_LREF = {"rail": (70, 68), "light_rail": (64, 56), "narrow_gauge": (62, 55), "rail_service": (60, 55)}  # на 25 м
POINT_LREF = {"nightclub": (68, 75), "bar": (60, 62), "pub": (60, 62), "stadium": (70, 50)}  # на 10 м
RUNWAY_LREF = (66, 60)  # эквивалентный уровень на 300 м от оси ВПП и траекторий (полёты эпизодические)
ELEM = 20.0


def _split(line, step=ELEM):
    L = line.length
    if L <= 0:
        return []
    n = max(1, int(math.ceil(L / step)))
    pts = [line.interpolate((i + 0.5) * L / n) for i in range(n)]
    return [(p.x, p.y, L / n) for p in pts]


def build_sources(ctx):
    if getattr(ctx, "_noise_src", None) is not None:
        return ctx._noise_src
    rows = []  # x, y, len, Lw_day, Lw_night, kind, name
    for r in ctx.roads:
        lref = ROAD_LREF.get(r["hw"].replace("_link", ""))
        if not lref or r["tunnel"]:
            continue
        k = -3 if r["hw"].endswith("_link") else 0
        for x, y, l in _split(r["geom"]):
            rows.append((x, y, l, lref[0] + k + 13, lref[1] + k + 13, "road", r["name"] or hw_ru(r["hw"])))
    for r in ctx.rails:
        lref = RAIL_LREF.get(r["kind"])
        if not lref or r["tunnel"]:
            continue
        for x, y, l in _split(r["geom"]):
            rows.append((x, y, l, lref[0] + 17, lref[1] + 17, "rail", "железная дорога"))
    for p in ctx.pois:
        a = p["tags"].get("amenity") or p["tags"].get("leisure")
        if a in POINT_LREF:
            d, n = POINT_LREF[a]
            rows.append((p["x"], p["y"], 1.0, d + 28, n + 28, "venue", poi_name(p["tags"])))
    for a in ctx.aero:
        line = a["geom"]
        cs = list(line.coords)
        (x1, y1), (x2, y2) = cs[0], cs[-1]
        L = math.hypot(x2 - x1, y2 - y1) or 1
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        ext = shapely.geometry.LineString([(x1 - ux * 3000, y1 - uy * 3000), (x2 + ux * 3000, y2 + uy * 3000)])
        for x, y, l in _split(ext, 50):
            rows.append((x, y, l, RUNWAY_LREF[0] + 28, RUNWAY_LREF[1] + 28, "air", "аэропорт (ВПП и траектории)"))
    if not rows:
        ctx._noise_src = None
        return None
    arr = np.array([r[:5] for r in rows], dtype="float64")
    ctx._noise_src = {"xy": arr[:, :2], "len": arr[:, 2], "lw_d": arr[:, 3], "lw_n": arr[:, 4],
                      "kind": np.array([r[5] for r in rows]), "name": np.array([r[6] for r in rows])}
    return ctx._noise_src


def facade_noise(ctx, facade, own_idx):
    src = build_sources(ctx)
    if src is None:
        return {"day": 40.0, "night": 35.0, "top": []}
    fx, fy, az = facade["x"], facade["y"], facade["az"]
    dx, dy = src["xy"][:, 0] - fx, src["xy"][:, 1] - fy
    r = np.hypot(dx, dy)
    rng = np.where(src["kind"] == "air", 9000, np.where(src["kind"] == "rail", 1500, 700))
    m = r < rng
    if not m.any():
        return {"day": 40.0, "night": 35.0, "top": []}
    dx, dy, r = dx[m], dy[m], np.maximum(r[m], 5.0)
    nxv, nyv = math.sin(math.radians(az)), math.cos(math.radians(az))
    cos = (dx * nxv + dy * nyv) / r
    orient = np.where(cos < -0.1, -18.0, np.where(cos < 0.25, -4.0, 0.0))
    # самолёт сверху: стена дома от него почти не закрывает
    orient = np.where(src["kind"][m] == "air", np.maximum(orient, -6.0), orient)
    # экранирование: 12 точек по линии «фасад → источник»
    t = np.linspace(0.08, 0.92, 12)
    px = fx + dx[:, None] * t[None]
    py = fy + dy[:, None] * t[None]
    ci = np.clip(np.round((px - ctx.x0) / ctx.cell).astype(int), 0, ctx.nx - 1)
    ri = np.clip(np.round((py - ctx.y0) / ctx.cell).astype(int), 0, ctx.ny - 1)
    b = ctx.bid[ri, ci]
    blocked = ((b >= 0) & (b != (own_idx if own_idx is not None else -2))).any(axis=1)
    screen = np.where(blocked & (src["kind"][m] != "air"), -10.0, 0.0)
    absorb = np.where(src["kind"][m] == "air", 0.001, 0.005)
    geo = 10 * np.log10(src["len"][m]) - 10 * np.log10(2 * math.pi * r ** 2) - absorb * r + orient + screen
    Ld = src["lw_d"][m] + geo
    Ln = src["lw_n"][m] + geo
    day = 10 * math.log10(np.sum(10 ** (Ld / 10)) + 10 ** 3.5)    # фон 35 дБ
    night = 10 * math.log10(np.sum(10 ** (Ln / 10)) + 10 ** 3.0)  # фон 30 дБ
    # главные источники ночью
    names = src["name"][m]
    kinds = src["kind"][m]
    agg = {}
    for nm, kd, ln, rr in zip(names, kinds, Ln, r):
        k = (kd, nm)
        e = agg.setdefault(k, [0.0, 1e9])
        e[0] += 10 ** (ln / 10)
        e[1] = min(e[1], rr)
    top = sorted(agg.items(), key=lambda kv: -kv[1][0])[:3]
    top = [{"kind": k[0], "name": k[1], "night_db": round(10 * math.log10(v[0]), 1), "dist_m": int(v[1])}
           for k, v in top if 10 * math.log10(v[0]) > 30]
    return {"day": round(day, 1), "night": round(night, 1), "top": top}


def night_class(db):
    if db is None:
        return None
    if db < 45:
        return "тихо"
    if db < 55:
        return "умеренно"
    return "шумно"
