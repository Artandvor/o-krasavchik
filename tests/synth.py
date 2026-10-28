"""Синтетический мини-регион «как Адлер» с известной правдой — для тестов и разработки.

Берег идёт с СЗ на ЮВ, море на ЮЗ. Вдоль берега: пляж, ж/д (в 90 м), трасса (в 160 м).
Отели:
  H_front   — первая линия, 5 этажей, ничего не закрывает море       → вид на море ДА
  H_blocked — за 60-метровой башней со стороны моря, 4 этажа          → вид на море НЕТ
  H_tall    — за невысокими домами (9 м), 12 этажей                    → с низа нет, с верха ДА
  H_inland  — 2 км от моря среди 15-метровой застройки, 3 этажа        → НЕТ
Пешеходный путь к пляжу: от H_front через подземный переход под ж/д; от H_inland — через
наземный переход по трассе.
"""
import json
import math
from pathlib import Path

import numpy as np

LAT0, LON0 = 43.43, 39.94
KX = 111_320.0 * math.cos(math.radians(LAT0))
KY = 110_574.0
# ось «вдоль берега» u (на ЮВ) и «вглубь суши» v (на СВ); азимут берега 135°
ALONG = math.radians(135)
UX, UY = math.sin(ALONG), math.cos(ALONG)          # вдоль берега
VX, VY = math.sin(ALONG - math.pi / 2), math.cos(ALONG - math.pi / 2)  # от моря вглубь суши (на СВ)


def ll(u, v):
    x = u * UX + v * VX
    y = u * UY + v * VY
    return LAT0 + y / KY, LON0 + x / KX


_nid = [1000]


def nid():
    _nid[0] += 1
    return _nid[0]


def way(id_, pts, tags, closed=False):
    pts = list(pts)
    if closed:
        pts = pts + [pts[0]]
    nodes = [nid() for _ in pts]
    if closed:
        nodes[-1] = nodes[0]
    return {"type": "way", "id": id_, "nodes": nodes, "tags": tags,
            "geometry": [{"lat": a, "lon": b} for a, b in (ll(u, v) for u, v in pts)]}


def shared_way(id_, node_pts, tags):
    """Путь из заранее заданных (node_id, u, v) — для общих узлов графа."""
    return {"type": "way", "id": id_, "nodes": [n for n, _, _ in node_pts], "tags": tags,
            "geometry": [{"lat": a, "lon": b} for a, b in (ll(u, v) for _, u, v in node_pts)]}


def rect(cu, cv, w, d):
    return [(cu - w / 2, cv - d / 2), (cu + w / 2, cv - d / 2), (cu + w / 2, cv + d / 2), (cu - w / 2, cv + d / 2)]


def build(raw: Path):
    raw.mkdir(parents=True, exist_ok=True)
    wid = [1]

    def W():
        wid[0] += 1
        return wid[0]

    # ---- рельеф: 0 на море, плавный подъём вглубь суши + гора 1500 м в 35 км на СВ
    lats = np.arange(43.80, 43.15, -0.0008)
    lons = np.arange(39.55, 40.50, 0.0008)
    LON, LAT = np.meshgrid(lons, lats)
    X, Y = (LON - LON0) * KX, (LAT - LAT0) * KY
    v = X * VX + Y * VY
    z = np.where(v < 0, 0.0, 1.0 + v * 0.008)
    mx, my = 35000 * VX, 35000 * VY
    z += 1500 * np.exp(-(((X - mx) ** 2 + (Y - my) ** 2) / (2 * 6000 ** 2)))
    np.savez_compressed(raw / "dem_synth.npz", lats=lats, lons=lons, z=z.astype("float32"),
                        source="synthetic DEM")

    # ---- природа: берег (море справа по направлению), пляж
    coast = way(W(), [(-6000, 0), (6000, 0)], {"natural": "coastline"})
    beach = way(W(), [(-3000, 2), (3000, 2), (3000, 40), (-3000, 40)], {"natural": "beach", "surface": "pebblestone",
                                                                          "name": "Пляж Синтетический"}, closed=True)
    playground = way(W(), rect(-400, 300, 30, 30), {"leisure": "playground"}, closed=True)
    constr = way(W(), rect(600, 400, 80, 60), {"landuse": "construction"}, closed=True)
    constr["timestamp"] = "2026-05-01T00:00:00Z"
    json.dump({"elements": [coast, beach, playground, constr]}, open(raw / "osm_nature.json", "w"))

    # ---- здания
    B = []
    hotels_b = {
        "front": rect(0, 70, 30, 20), "blocked": rect(-800, 260, 30, 20),
        "tall": rect(800, 420, 30, 24), "inland": rect(0, 2000, 30, 20),
    }
    B.append(way(W(), hotels_b["front"], {"building": "hotel", "building:levels": "5"}, closed=True))
    B.append(way(W(), hotels_b["blocked"], {"building": "hotel", "building:levels": "4"}, closed=True))
    B.append(way(W(), hotels_b["tall"], {"building": "hotel", "building:levels": "12"}, closed=True))
    B.append(way(W(), hotels_b["inland"], {"building": "hotel", "building:levels": "3", "start_date": "1937"}, closed=True))
    B.append(way(W(), rect(-800, 200, 400, 30), {"building": "apartments", "height": "60"}, closed=True))  # башня
    for k in range(-8, 9):
        B.append(way(W(), rect(800 + k * 30, 360, 30, 25), {"building": "house", "height": "9"}, closed=True))
    for i in range(-6, 7):
        for j in range(1, 8):
            cu, cv = i * 80, 2000 - 400 + j * 100
            if abs(cu) < 40 and abs(cv - 2000) < 40:
                continue
            B.append(way(W(), rect(cu, cv, 40, 30), {"building": "apartments", "height": "15"}, closed=True))
    json.dump({"elements": B}, open(raw / "osm_buildings.json", "w"))

    # ---- дороги: трасса v=160, ж/д v=90, променад v=50, перпендикулярные улицы
    n = {}

    def N(key, u, v):
        if key not in n:
            n[key] = (nid(), u, v)
        return n[key]

    R = []
    us = list(range(-3000, 3001, 200))
    R.append(shared_way(W(), [N(("trunk", u), u, 160) for u in us], {"highway": "trunk", "name": "ул. Ленина"}))
    R.append(shared_way(W(), [N(("prom", u), u, 50) for u in us], {"highway": "footway", "name": "Набережная"}))
    for u in us:
        # улица от трассы вглубь суши
        R.append(shared_way(W(), [N(("trunk", u), u, 160), N(("st1", u), u, 1000), N(("st2", u), u, 2400)],
                            {"highway": "residential", "name": f"ул. {u}"}))
    # переходы к морю: через тоннель под ж/д в u=0, наземный в u=-800 и u=800
    for u, tags in ((0, {"highway": "footway", "tunnel": "yes", "layer": "-1"}),
                    (-800, {"highway": "footway"}), (800, {"highway": "footway"})):
        R.append(shared_way(W(), [N(("trunk", u), u, 160), N(("mid", u), u, 110), N(("prom", u), u, 50)], tags))
    # подходы от отелей к улицам
    R.append(shared_way(W(), [N(("hf", 0), 0, 58), N(("prom", 0), 0, 50)], {"highway": "footway"}))
    R.append(shared_way(W(), [N(("hb", 0), -800, 272), N(("trunk", -800), -800, 160)], {"highway": "service"}))
    R.append(shared_way(W(), [N(("ht", 0), 800, 434), N(("trunk", 800), 800, 160)], {"highway": "service"}))
    R.append(shared_way(W(), [N(("hi", 0), 0, 2012), N(("st2", 0), 0, 2400)], {"highway": "service"}))
    json.dump({"elements": R}, open(raw / "osm_roads.json", "w"))
    rail = way(W(), [(-6000, 90), (6000, 90)], {"railway": "rail"})
    json.dump({"elements": [rail]}, open(raw / "osm_rail.json", "w"))

    # ---- отели (как узлы внутри зданий)
    H = []
    for i, (k, name, uv) in enumerate([("front", "Отель Первая линия", (0, 70)), ("blocked", "Отель За башней", (-800, 260)),
                                        ("tall", "Отель Высотка", (800, 420)), ("inland", "Отель Нагорный", (0, 2000))]):
        la, lo = ll(*uv)
        tags = {"tourism": "hotel", "name": name}
        if k == "front":
            tags["pets"] = "yes"
        H.append({"type": "node", "id": 900 + i, "lat": la, "lon": lo, "tags": tags, "timestamp": "2025-06-01T00:00:00Z"})
    json.dump({"elements": H}, open(raw / "osm_hotels.json", "w"))

    # ---- POI
    P = []
    for k, (tags, uv) in enumerate([
        ({"amenity": "pharmacy", "opening_hours": "24/7", "name": "Аптека 24"}, (100, 200)),
        ({"amenity": "cafe", "opening_hours": "Mo-Su 10:00-01:00", "name": "Кафе Полночь"}, (-100, 180)),
        ({"amenity": "nightclub", "name": "Клуб Бас"}, (800, 470)),
        ({"amenity": "parking"}, (0, 190)),
        ({"amenity": "hospital", "name": "Детская больница"}, (0, 3000)),
    ]):
        la, lo = ll(*uv)
        P.append({"type": "node", "id": 5000 + k, "lat": la, "lon": lo, "tags": tags, "timestamp": "2025-01-01T00:00:00Z"})
    json.dump({"elements": P}, open(raw / "osm_pois.json", "w"))
    json.dump({"elements": []}, open(raw / "osm_aero.json", "w"))

    # ---- климат (минимально)
    days = [f"2024-{m:02d}-15" for m in range(1, 13)]
    air = [10, 11, 13, 17, 21, 26, 29, 30, 26, 21, 15, 12]
    json.dump({"daily": {"time": days, "temperature_2m_max": air, "temperature_2m_min": [a - 7 for a in air],
                         "precipitation_sum": [3] * 12, "sunshine_duration": [8 * 3600] * 12}},
              open(raw / "climate_daily.json", "w"))
    sea = [10, 9, 10, 12, 17, 22, 25, 26, 24, 20, 16, 12]
    json.dump({"hourly": {"time": [f"2024-{m:02d}-15T12:00" for m in range(1, 13)], "sea_surface_temperature": sea}},
              open(raw / "marine_hourly.json", "w"))

    s, w = ll(-3000, -1500)
    nn, e = ll(3000, 3500)
    cfg = {"name": "Синтетический берег", "hotels_bbox": [min(s, nn) , min(w, e), max(s, nn), max(w, e)],
           "pad_m": 800, "far_bbox": [43.15, 39.55, 43.80, 40.49], "far_step_m": 150, "dsm_cell_m": 10,
           "climate_point": [LAT0, LON0], "sea_point": list(ll(0, -500)), "max_hotels": 50}
    # отели лежат в bbox по построению; bbox берём по крайним точкам района
    pts = [ll(u, v) for u in (-3000, 3000) for v in (-200, 3200)]
    cfg["hotels_bbox"] = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
    return cfg


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/odin-synth")
    cfg = build(out / "raw")
    (out / "region.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    print("ok", out)
