"""Сырые открытые данные → подготовленный гео-контекст региона (data/processed).

Что строится:
  grid.npz   — сетка 10 м: рельеф без зданий (DTM), id здания в клетке, маска моря,
               «горб» DSM−DTM (подсказка высоты зданий без тегов)
  far.npz    — грубая сетка 150 м на ~60 км: дальний рельеф для гор и горизонта
  geo.pkl    — здания с априорными распределениями высоты, дороги, ж/д, POI, пляжи,
               пешеходный граф с высотами, аэропорт
  hotels.json — отели с контуром, фасадами и этажностью
"""
import json
import math
import pickle
import re
import time

import networkx as nx
import numpy as np
import shapely
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import linemerge, polygonize, unary_union

from ..config import PROC, RAW, region_cfg
from . import osm
from .dem import Dem
from .proj import LocalProj, az_name, bbox_center, pad_bbox

FLOOR_H = 3.0

WALKABLE = {"footway", "path", "pedestrian", "steps", "living_street", "residential", "service",
            "unclassified", "tertiary", "tertiary_link", "secondary", "secondary_link", "primary",
            "primary_link", "trunk", "trunk_link", "track", "cycleway", "corridor", "road", "platform"}
DRIVABLE = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
            "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street",
            "service", "road"}
MAJOR = {"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link"}

# Априорные диапазоны высоты (м) для зданий без тегов height/levels: (lo, hi)
HEIGHT_PRIORS = {
    "house": (3, 10), "detached": (3, 10), "semidetached_house": (3, 10), "terrace": (3, 10),
    "garage": (2.5, 4), "garages": (2.5, 4), "shed": (2, 4), "hut": (2, 4), "kiosk": (2.5, 4),
    "roof": (3, 6), "carport": (2.5, 4), "service": (3, 6), "toilets": (2.5, 4),
    "apartments": (9, 60), "residential": (6, 45), "hotel": (6, 40), "dormitory": (9, 30),
    "commercial": (4, 25), "retail": (4, 15), "office": (6, 40), "supermarket": (5, 10),
    "industrial": (5, 15), "warehouse": (5, 14), "church": (8, 30), "school": (8, 16),
    "kindergarten": (4, 8), "hospital": (9, 30), "train_station": (6, 20), "construction": (3, 50),
}


def log(msg):
    print(f"[prepare {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ helpers

def building_prior(t, area, bump):
    """Возвращает (lo, hi, источник). Чем точнее источник, тем уже диапазон."""
    h = osm.parse_float(t.get("height"))
    if h and 2 <= h <= 400:
        return h - 0.5, h + 0.5, "osm:height"
    lv = osm.parse_float(t.get("building:levels"))
    if lv and 1 <= lv <= 100:
        rl = osm.parse_float(t.get("roof:levels")) or 0
        base = (lv + 0.5 * rl) * FLOOR_H
        return base - 0.5, base + 2.0, "osm:building:levels"
    if bump is not None and area >= 500 and bump >= 6:
        return max(3.0, 0.8 * bump), min(150.0, 1.6 * bump + 3), "copernicus:dsm-dtm"
    b = t.get("building", "yes")
    if b in HEIGHT_PRIORS:
        lo, hi = HEIGHT_PRIORS[b]
        return lo, hi, f"prior:{b}"
    if area < 150:
        return 3.0, 9.0, "prior:area<150"
    if area < 600:
        return 3.0, 20.0, "prior:area<600"
    return 6.0, 45.0, "prior:area>=600"


def facades_from_polygon(poly: Polygon, min_len=4.0):
    """Делит контур на 4 стороны по осям минимального прямоугольника. Для каждой стороны
    возвращает точку наблюдателя у самого длинного ребра и наружную нормаль (азимут)."""
    p = shapely.geometry.polygon.orient(poly.simplify(1.0), 1.0)  # CCW
    mrr = p.minimum_rotated_rectangle
    mc = list(mrr.exterior.coords)
    ex, ey = mc[1][0] - mc[0][0], mc[1][1] - mc[0][1]
    base = math.degrees(math.atan2(ex, ey))
    axes = [(base + 90 * k) % 360 for k in range(4)]
    cs = list(p.exterior.coords)
    best = {}
    for (x1, y1), (x2, y2) in zip(cs[:-1], cs[1:]):
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-6:
            continue
        # наружная нормаль для CCW-контура: вектор ребра, повернутый по часовой
        nx_, ny_ = (y2 - y1) / L, -(x2 - x1) / L
        naz = math.degrees(math.atan2(nx_, ny_)) % 360
        k = min(range(4), key=lambda i: abs((naz - axes[i] + 180) % 360 - 180))
        if L >= min_len and (k not in best or L > best[k][0]):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            best[k] = (L, mx + 1.5 * nx_, my + 1.5 * ny_, naz)
    out = []
    for k, (L, x, y, naz) in sorted(best.items(), key=lambda kv: kv[1][3]):
        out.append({"az": round(naz, 1), "side": az_name(naz), "x": x, "y": y, "len": round(L, 1)})
    return out


def synthetic_facades(x, y, r=10.0):
    return [{"az": a, "side": az_name(a), "x": x + r * math.sin(math.radians(a)),
             "y": y + r * math.cos(math.radians(a)), "len": 0.0, "synthetic": True}
            for a in (0, 90, 180, 270)]


def parse_levels(t):
    lv = osm.parse_float(t.get("building:levels"))
    if lv and 1 <= lv <= 80:
        return int(round(lv))
    h = osm.parse_float(t.get("height"))
    if h and 3 <= h <= 300:
        return max(1, int(h // FLOOR_H))
    return None


def parse_stars(t):
    s = t.get("stars")
    m = re.match(r"(\d)", str(s or ""))
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ main

def prepare():
    cfg = region_cfg()
    PROC.mkdir(parents=True, exist_ok=True)
    hb = cfg["hotels_bbox"]
    lat0, lon0 = bbox_center(hb)
    proj = LocalProj(lat0, lon0)
    pb = pad_bbox(hb, cfg["pad_m"])
    xmin, ymin = proj.to_xy(pb[0], pb[1])
    xmax, ymax = proj.to_xy(pb[2], pb[3])
    xmin, ymin, xmax, ymax = (math.floor(v / 10) * 10 for v in (xmin, ymin, xmax, ymax))
    cell = float(cfg.get("dsm_cell_m", 10))
    nx_, ny_ = int((xmax - xmin) / cell) + 1, int((ymax - ymin) / cell) + 1
    log(f"сетка {nx_}×{ny_} клеток по {cell:.0f} м")
    gx = xmin + np.arange(nx_) * cell
    gy = ymin + np.arange(ny_) * cell

    dem = Dem(RAW)
    log(f"рельеф: {dem.source}")

    # --- рельеф 30 м → DTM (морфологическое открытие убирает здания/деревья) → 10 м
    c30 = 30.0
    gx30 = np.arange(xmin, xmax + c30, c30)
    gy30 = np.arange(ymin, ymax + c30, c30)
    X30, Y30 = np.meshgrid(gx30, gy30)
    LA30, LO30 = proj.to_ll(X30, Y30)
    dsm30 = dem.sample(LA30, LO30)
    dsm30 = np.where(np.isnan(dsm30), 0, dsm30)
    dtm30 = ndimage.grey_opening(dsm30, size=(5, 5))
    dtm30 = ndimage.uniform_filter(dtm30, size=3)

    def up(a):
        fx = (gx - xmin) / c30
        fy = (gy - ymin) / c30
        FX, FY = np.meshgrid(fx, fy)
        return ndimage.map_coordinates(a, [FY, FX], order=1, mode="nearest").astype("float32")

    dtm = up(dtm30)
    bump = up(np.clip(dsm30 - dtm30, 0, None))

    # --- море по линии берега OSM: суша слева от направления линии, море справа
    nature = []
    for nm in ("nature", "coast", "beach", "leisure", "construction"):
        nature += osm.load(RAW / f"osm_{nm}.json")
    coast = []
    for el in nature:
        if osm.tags(el).get("natural") == "coastline" and el["type"] == "way":
            g = osm.element_geometry(el, proj, as_area=False)
            if isinstance(g, LineString):
                coast.append(g)
    frame = box(xmin, ymin, xmax, ymax)
    sea_poly = None
    if coast:
        lines = [c.intersection(frame) for c in coast]
        lines = [l for l in lines if not l.is_empty]
        polys = list(polygonize(unary_union(lines + [frame.exterior])))
        votes = {i: 0 for i in range(len(polys))}
        tree = shapely.STRtree(polys)
        for c in coast:
            cs = list(c.coords)
            for (x1, y1), (x2, y2) in zip(cs[:-1], cs[1:]):
                L = math.hypot(x2 - x1, y2 - y1)
                if L < 1:
                    continue
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                rx, ry = (y2 - y1) / L, -(x2 - x1) / L  # вправо от направления
                for sgn in (1, -1):
                    pt = Point(mx + sgn * 3 * rx, my + sgn * 3 * ry)
                    for i in tree.query(pt, predicate="within"):
                        votes[int(i)] += sgn
        sea_parts = [polys[i] for i, v in votes.items() if v > 0]
        if sea_parts:
            sea_poly = unary_union(sea_parts)
            log(f"море: из {len(coast)} линий берега, {len(sea_parts)} полигон(ов)")
    X, Y = np.meshgrid(gx, gy)
    if sea_poly is not None:
        sea = shapely.contains_xy(sea_poly, X, Y)
    else:
        sx, sy = proj.to_xy(*cfg["sea_point"])
        low = dtm <= 0.5
        lab, _ = ndimage.label(low)
        i0 = int(round((sy - ymin) / cell)), int(round((sx - xmin) / cell))
        i0 = (min(max(i0[0], 0), ny_ - 1), min(max(i0[1], 0), nx_ - 1))
        sea = lab == lab[i0] if lab[i0] > 0 else np.zeros_like(low)
        log("море: линии берега нет, взял по рельефу ≤0.5 м от sea_point")
    dtm = np.where(sea, np.minimum(dtm, 0.0), dtm).astype("float32")

    # --- здания
    belts = osm.load(RAW / "osm_buildings.json")
    buildings, bpolys = [], []
    for el in belts:
        t = osm.tags(el)
        g = osm.element_geometry(el, proj, as_area=True)
        for p in osm.polygons_of(g):
            if p.area < 8:
                continue
            buildings.append({"osm": f"{el['type']}/{el['id']}", "tags": {k: t[k] for k in t if k in (
                "building", "height", "building:levels", "roof:levels", "name", "start_date",
                "building:architecture", "heritage", "addr:street", "addr:housenumber", "tourism")},
                "area": round(p.area, 1)})
            bpolys.append(p)
    log(f"здания: {len(buildings)}")
    bid = np.full((ny_, nx_), -1, dtype="int32")
    order = np.argsort([-p.area for p in bpolys])  # крупные сначала, мелкие поверх
    for i in order:
        p = bpolys[i]
        x1, y1, x2, y2 = p.bounds
        c1, c2 = int((x1 - xmin) // cell), int((x2 - xmin) // cell) + 1
        r1, r2 = int((y1 - ymin) // cell), int((y2 - ymin) // cell) + 1
        c1, r1 = max(c1, 0), max(r1, 0)
        c2, r2 = min(c2, nx_ - 1), min(r2, ny_ - 1)
        if c2 < c1 or r2 < r1:
            continue
        sx_ = gx[c1:c2 + 1]
        sy_ = gy[r1:r2 + 1]
        SX, SY = np.meshgrid(sx_, sy_)
        m = shapely.contains_xy(p, SX, SY)
        if not m.any():  # маленькое здание меньше клетки: ставим в центроид
            cx, cy = p.centroid.x, p.centroid.y
            ci, ri = int(round((cx - xmin) / cell)), int(round((cy - ymin) / cell))
            if 0 <= ri < ny_ and 0 <= ci < nx_:
                bid[ri, ci] = i
            continue
        sub = bid[r1:r2 + 1, c1:c2 + 1]
        sub[m] = i
    lab = bid.ravel() + 1
    cnt = np.bincount(lab, minlength=len(buildings) + 1)
    sm = np.bincount(lab, weights=bump.ravel().astype("float64"), minlength=len(buildings) + 1)
    bump_mean = np.where(cnt > 0, sm / np.maximum(cnt, 1), np.nan)[1:]
    for i, b in enumerate(buildings):
        bb_ = float(bump_mean[i]) if not np.isnan(bump_mean[i]) else None
        lo, hi, src = building_prior(b["tags"], b["area"], bb_)
        b.update({"h_lo": round(lo, 1), "h_hi": round(hi, 1), "h_src": src})
    known = sum(1 for b in buildings if b["h_src"].startswith("osm"))
    log(f"высоты зданий: из OSM {known}/{len(buildings)} ({100 * known / max(1, len(buildings)):.0f}%), "
        f"по DSM {sum(1 for b in buildings if b['h_src'].startswith('copernicus'))}, остальные — априорно")

    # --- дальний рельеф
    fb = cfg["far_bbox"]
    fstep = float(cfg.get("far_step_m", 150))
    fx0, fy0 = proj.to_xy(fb[0], fb[1])
    fx1, fy1 = proj.to_xy(fb[2], fb[3])
    fgx = np.arange(fx0, fx1, fstep)
    fgy = np.arange(fy0, fy1, fstep)
    FX, FY = np.meshgrid(fgx, fgy)
    FLA, FLO = proj.to_ll(FX, FY)
    far = dem.sample(FLA, FLO)
    far = np.where(np.isnan(far), 0, far).astype("float32")
    log(f"дальний рельеф {far.shape}, максимум {np.nanmax(far):.0f} м")

    np.savez_compressed(PROC / "grid.npz", dtm=dtm, bid=bid, sea=sea, bump=bump.astype("float16"),
                        x0=xmin, y0=ymin, cell=cell, lat0=lat0, lon0=lon0)
    np.savez_compressed(PROC / "far.npz", z=far, x0=fgx[0], y0=fgy[0], cell=fstep)

    def ground(x, y):
        ci = np.clip(np.round((np.asarray(x) - xmin) / cell).astype(int), 0, nx_ - 1)
        ri = np.clip(np.round((np.asarray(y) - ymin) / cell).astype(int), 0, ny_ - 1)
        return dtm[ri, ci]

    # --- дороги и пешеходный граф
    roads_raw = osm.load(RAW / "osm_roads.json")
    G = nx.Graph()
    roads = []
    for el in roads_raw:
        t = osm.tags(el)
        hw = t.get("highway")
        geom = el.get("geometry") or []
        nodes = el.get("nodes") or []
        if not hw or len(geom) < 2:
            continue
        line = osm.element_geometry(el, proj, as_area=False)
        if isinstance(line, Polygon):
            line = line.exterior
        roads.append({"hw": hw, "name": t.get("name", ""), "geom": line,
                      "bridge": t.get("bridge") not in (None, "no"), "tunnel": t.get("tunnel") not in (None, "no"),
                      "motor": hw in DRIVABLE and t.get("motor_vehicle") not in ("no", "private")
                      and t.get("access") not in ("no", "private"), "osm": el["id"],
                      "maxspeed": t.get("maxspeed"), "lanes": t.get("lanes")})
        walk_ok = hw in WALKABLE and t.get("foot") not in ("no",) and \
            (t.get("access") not in ("no", "private") or t.get("foot") in ("yes", "designated"))
        if not walk_ok or len(nodes) != len(geom):
            continue
        xy = [proj.to_xy(p["lat"], p["lon"]) for p in geom]
        flat = t.get("bridge") not in (None, "no") or t.get("tunnel") not in (None, "no")
        for k in range(len(nodes) - 1):
            a, b = nodes[k], nodes[k + 1]
            (x1, y1), (x2, y2) = xy[k], xy[k + 1]
            L = math.hypot(x2 - x1, y2 - y1)
            if L < 0.1:
                continue
            G.add_node(a, x=x1, y=y1)
            G.add_node(b, x=x2, y=y2)
            G.add_edge(a, b, length=L, hw=hw, name=t.get("name", ""), flat=flat,
                       tunnel=t.get("tunnel") not in (None, "no"), bridge=t.get("bridge") not in (None, "no"),
                       crossing=t.get("footway") == "crossing", way=el["id"])
    if G.number_of_nodes():
        comp = max(nx.connected_components(G), key=len)
        G = G.subgraph(comp).copy()
    ids = list(G.nodes)
    nxy = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in ids]) if ids else np.zeros((0, 2))
    nz = ground(nxy[:, 0], nxy[:, 1]) if len(ids) else np.zeros(0)
    for n, z in zip(ids, nz):
        G.nodes[n]["z"] = float(z)
    for a, b, d in G.edges(data=True):
        dz = 0.0 if d["flat"] else G.nodes[b]["z"] - G.nodes[a]["z"]
        s = dz / d["length"]
        v = 6 * math.exp(-3.5 * abs(s + 0.05))  # Тоблер, км/ч, a→b
        v2 = 6 * math.exp(-3.5 * abs(-s + 0.05))
        mult = 1.6 if d["hw"] == "steps" else 1.0
        d["t"] = d["length"] / (1000 * (v + v2) / 2) * 60 * mult  # минуты, среднее туда/обратно
        d["dz"] = dz
    log(f"пешеходный граф: {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер")

    # --- ж/д, природа, POI, аэропорт
    rails, rail_nodes = [], []
    for el in osm.load(RAW / "osm_rail.json"):
        t = osm.tags(el)
        if el["type"] == "node":
            rail_nodes.append({"kind": t.get("railway"), "name": t.get("name", ""),
                               "x": proj.to_xy(el["lat"], el["lon"])[0], "y": proj.to_xy(el["lat"], el["lon"])[1],
                               "id": el["id"]})
            continue
        g = osm.element_geometry(el, proj, as_area=False)
        if g is None:
            continue
        kind = t.get("railway")
        if kind == "platform":
            continue
        if t.get("service") in ("yard", "siding", "spur") or t.get("usage") == "industrial":
            kind = "rail_service"
        rails.append({"kind": kind, "geom": g if isinstance(g, LineString) else g.boundary,
                      "bridge": t.get("bridge") not in (None, "no"), "tunnel": t.get("tunnel") not in (None, "no"),
                      "name": t.get("name", "")})
    beaches, playgrounds, parks, construction, peaks = [], [], [], [], []
    for el in nature:
        t = osm.tags(el)
        g = osm.element_geometry(el, proj)
        if g is None:
            continue
        if t.get("natural") == "beach" or t.get("leisure") == "beach_resort":
            beaches.append({"geom": g, "name": t.get("name", ""), "surface": t.get("surface", ""),
                            "osm": f"{el['type']}/{el['id']}"})
        elif t.get("leisure") == "playground":
            playgrounds.append({"geom": g, "name": t.get("name", ""), "osm": f"{el['type']}/{el['id']}"})
        elif t.get("leisure") in ("park", "garden"):
            parks.append({"geom": g, "name": t.get("name", "")})
        elif t.get("landuse") == "construction" or t.get("building") == "construction":
            construction.append({"geom": g, "name": t.get("name", ""), "osm": f"{el['type']}/{el['id']}",
                                 "timestamp": el.get("timestamp"), "tags": t})
        elif t.get("natural") == "peak":
            peaks.append({"geom": g, "name": t.get("name", ""), "ele": t.get("ele")})
    pois = []
    for el in osm.load(RAW / "osm_pois.json"):
        t = osm.tags(el)
        if el["type"] == "node":
            x, y = proj.to_xy(el["lat"], el["lon"])
        elif "center" in el:
            x, y = proj.to_xy(el["center"]["lat"], el["center"]["lon"])
        else:
            continue
        pois.append({"x": x, "y": y, "tags": t, "osm": f"{el['type']}/{el['id']}",
                     "timestamp": el.get("timestamp")})
    aero = []
    for el in osm.load(RAW / "osm_aero.json"):
        t = osm.tags(el)
        if t.get("aeroway") == "runway":
            g = osm.element_geometry(el, proj, as_area=False)
            if g is not None:
                aero.append({"kind": "runway", "geom": g if isinstance(g, LineString) else g.exterior,
                             "ref": t.get("ref", "")})
    log(f"ж/д линий {len(rails)}, пляжей {len(beaches)}, площадок {len(playgrounds)}, строек {len(construction)}, "
        f"POI {len(pois)}, ВПП {len(aero)}")

    # --- отели
    btree = shapely.STRtree(bpolys) if bpolys else None
    kdt = cKDTree(nxy) if len(ids) else None
    kind_rank = {"hotel": 0, "apartment": 2, "guest_house": 1, "hostel": 3, "motel": 2, "chalet": 3}
    cand = []
    for el in osm.load(RAW / "osm_hotels.json"):
        t = osm.tags(el)
        name = t.get("name") or t.get("name:ru") or t.get("name:en")
        if not name:
            continue
        g = osm.element_geometry(el, proj, as_area=True)
        if g is None:
            continue
        footprint, bidx = None, None
        if isinstance(g, Polygon) or osm.polygons_of(g):
            footprint = max(osm.polygons_of(g), key=lambda p: p.area)
            if btree is not None:
                hits = btree.query(footprint.centroid, predicate="within")
                if len(hits):
                    bidx = int(max(hits, key=lambda i: bpolys[int(i)].intersection(footprint).area))
        else:
            pt = g if isinstance(g, Point) else g.centroid
            if btree is not None:
                hits = btree.query(pt, predicate="within")
                if len(hits):
                    bidx = int(hits[0])
                else:
                    near = btree.query(pt.buffer(15))
                    if len(near):
                        bidx = int(min(near, key=lambda i: bpolys[int(i)].distance(pt)))
            if bidx is not None:
                footprint = bpolys[bidx]
        c = footprint.centroid if footprint is not None else (g if isinstance(g, Point) else g.centroid)
        btags = buildings[bidx]["tags"] if bidx is not None else {}
        levels = parse_levels(t) or parse_levels(btags)
        levels_src = "osm" if levels else None
        if not levels:
            b = buildings[bidx] if bidx is not None else None
            if b is not None and not b["h_src"].startswith("prior"):
                levels = max(1, int(round((b["h_lo"] + b["h_hi"]) / 2 / FLOOR_H)))
            else:
                levels = {"guest_house": 3, "hostel": 3, "chalet": 2, "motel": 2, "apartment": 9}.get(t.get("tourism"), 5)
            levels_src = "estimate"
        lat, lon = proj.to_ll(c.x, c.y)
        facades = facades_from_polygon(footprint) if footprint is not None else synthetic_facades(c.x, c.y)
        if not facades:
            facades = synthetic_facades(c.x, c.y)
        for f in facades:
            f["ground"] = float(ground(f["x"], f["y"]))
        node = None
        if kdt is not None:
            dist, j = kdt.query([c.x, c.y])
            if dist < 250:
                node = ids[int(j)]
        score = (kind_rank.get(t.get("tourism"), 3) * -1 + (2 if footprint is not None else 0)
                 + (1 if levels_src == "osm" else 0) + (1 if t.get("stars") else 0) + (1 if t.get("website") or t.get("contact:website") else 0)
                 + (0.5 if t.get("phone") or t.get("contact:phone") else 0))
        fp_ll = None
        if footprint is not None:
            fp_ll = [[round(v, 6) for v in proj.to_ll(x, y)] for x, y in footprint.exterior.coords]
        cand.append({
            "id": f"osm-{el['type'][0]}{el['id']}", "osm": f"{el['type']}/{el['id']}",
            "name": name, "kind": t.get("tourism"), "lat": round(lat, 6), "lon": round(lon, 6),
            "x": c.x, "y": c.y, "stars": parse_stars(t), "levels": levels,
            "levels_src": levels_src, "building_idx": bidx,
            "footprint_ll": fp_ll, "footprint_known": footprint is not None,
            "facades": facades, "node": node,
            "address": " ".join(x for x in [t.get("addr:street") or btags.get("addr:street"),
                                            t.get("addr:housenumber") or btags.get("addr:housenumber")] if x),
            "website": t.get("website") or t.get("contact:website"),
            "phone": t.get("phone") or t.get("contact:phone"),
            "tags": t, "building_tags": btags, "osm_timestamp": el.get("timestamp"),
            "score": score})
    cand.sort(key=lambda h: -h["score"])
    seen, hotels = set(), []
    for h in cand:
        k = (h["name"].lower(), round(h["x"] / 30), round(h["y"] / 30))
        if k in seen:
            continue
        seen.add(k)
        hotels.append(h)
        if len(hotels) >= cfg.get("max_hotels", 250):
            break
    log(f"отели: {len(cand)} с названием, взял {len(hotels)}; "
        f"с контуром здания {sum(h['footprint_known'] for h in hotels)}, с этажностью из OSM {sum(h['levels_src'] == 'osm' for h in hotels)}")

    geo = {"proj": proj.to_dict(), "buildings": buildings, "roads": roads, "rails": rails,
           "rail_nodes": rail_nodes, "beaches": beaches, "playgrounds": playgrounds, "parks": parks,
           "construction": construction, "peaks": peaks, "pois": pois, "aero": aero, "graph": G,
           "sea_poly": sea_poly, "dem_source": dem.source, "frame": (xmin, ymin, xmax, ymax),
           "built_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(PROC / "geo.pkl", "wb") as f:
        pickle.dump(geo, f, protocol=pickle.HIGHEST_PROTOCOL)
    (PROC / "hotels.json").write_text(json.dumps(hotels, ensure_ascii=False, indent=1), encoding="utf-8")
    log("готово: data/processed/")
    return hotels
