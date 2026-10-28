"""Реальная пешая доступность: маршрут по графу OSM с учётом рельефа (функция Тоблера),
переходов через железную дорогу и крупные дороги."""
import math
import re

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, Point

from .osm import hw_ru
from .prepare import MAJOR

SURFACE_RU = {"pebblestone": "галька", "pebbles": "галька", "gravel": "галька", "sand": "песок", "shingle": "галька",
              "sand_pebbles": "песок и галька", "paving_stones": "плитка", "grass": "трава",
              "fine_gravel": "мелкая галька", "concrete": "бетон", "rock": "камни", "stone": "камни",
              "wood": "деревянный настил"}


def _targets_near(ctx, geoms, radius):
    if not geoms or ctx.node_tree is None:
        return set()
    out = set()
    for g in geoms:
        b = g.buffer(radius)
        x1, y1, x2, y2 = b.bounds
        idx = ctx.node_tree.query_ball_point([(x1 + x2) / 2, (y1 + y2) / 2], math.hypot(x2 - x1, y2 - y1) / 2)
        if not idx:
            continue
        pts = ctx.node_xy[idx]
        inside = shapely.contains_xy(b, pts[:, 0], pts[:, 1])
        out.update(ctx.node_ids[i] for i, ok in zip(idx, inside) if ok)
    return out


def beach_field(ctx):
    """Мульти-источниковый Дейкстра от всех входов на пляж: время до ближайшего пляжа для каждого узла."""
    if getattr(ctx, "_beach_field", None) is not None:
        return ctx._beach_field
    geoms = [b["geom"] for b in ctx.beaches]
    targets = _targets_near(ctx, geoms, 35)
    src_kind = "osm:natural=beach"
    if not targets and ctx.sea_poly is not None:
        targets = _targets_near(ctx, [ctx.sea_poly.boundary], 60)
        src_kind = "osm:coastline"
    if not targets:
        ctx._beach_field = (None, None, None)
        return ctx._beach_field
    from networkx.algorithms.shortest_paths.weighted import _dijkstra_multisource, _weight_function
    pred = {}
    dist = _dijkstra_multisource(ctx.graph, targets, _weight_function(ctx.graph, "t"), pred=pred)
    ctx._beach_field = (dist, pred, src_kind)
    return ctx._beach_field


def _path_from_pred(pred, n):
    """Путь от узла n до ближайшего пляжа по дереву предшественников."""
    path = [n]
    seen = {n}
    while pred.get(path[-1]):
        nxt = pred[path[-1]][0]
        if nxt in seen:
            break
        seen.add(nxt)
        path.append(nxt)
    return path


def _trees(ctx):
    if getattr(ctx, "_cross_trees", None) is None:
        rails = [r for r in ctx.rails if r["kind"] in ("rail", "light_rail", "narrow_gauge")]
        majors = [r for r in ctx.roads if r["hw"] in MAJOR and not r["tunnel"]]
        ctx._cross_trees = (rails, shapely.STRtree([r["geom"] for r in rails]) if rails else None,
                            majors, shapely.STRtree([r["geom"] for r in majors]) if majors else None)
    return ctx._cross_trees


def analyze_path(ctx, path):
    G = ctx.graph
    rails, rtree, majors, mtree = _trees(ctx)
    length = t = gain = 0.0
    rail_x, road_x = [], []
    coords = []
    for a, b in zip(path[:-1], path[1:]):
        e = G.edges[a, b]
        length += e["length"]
        t += e["t"]
        za, zb = G.nodes[a]["z"], G.nodes[b]["z"]
        if not e["flat"] and zb > za:
            gain += zb - za
        seg = LineString([(G.nodes[a]["x"], G.nodes[a]["y"]), (G.nodes[b]["x"], G.nodes[b]["y"])])
        coords.append((G.nodes[a]["x"], G.nodes[a]["y"]))
        if rtree is not None:
            for i in rtree.query(seg, predicate="intersects"):
                r = rails[int(i)]
                how = "подземный переход" if e["tunnel"] or r["bridge"] else \
                    "надземный переход" if e["bridge"] or r["tunnel"] else "наземный переход через пути"
                rail_x.append(how)
        if mtree is not None and e["hw"] not in MAJOR:
            for i in mtree.query(seg, predicate="crosses"):
                r = majors[int(i)]
                how = "подземный переход" if e["tunnel"] else "надземный переход" if e["bridge"] else \
                    "пешеходный переход" if e["crossing"] else "переход"
                road_x.append({"road": r["name"] or hw_ru(r["hw"]), "hw": r["hw"], "how": how})
    # переход крупной дороги через общий узел: пришли и ушли по «немагистральным» рёбрам,
    # а узел лежит на магистрали, и точки до/после — по разные стороны от неё
    for a, b, c in zip(path[:-2], path[1:-1], path[2:]):
        if G.edges[a, b]["hw"] in MAJOR or G.edges[b, c]["hw"] in MAJOR:
            continue
        for m in G.neighbors(b):
            e = G.edges[b, m]
            if e["hw"] not in MAJOR:
                continue
            bx, by = G.nodes[b]["x"], G.nodes[b]["y"]
            rx, ry = G.nodes[m]["x"] - bx, G.nodes[m]["y"] - by
            s1 = rx * (G.nodes[a]["y"] - by) - ry * (G.nodes[a]["x"] - bx)
            s2 = rx * (G.nodes[c]["y"] - by) - ry * (G.nodes[c]["x"] - bx)
            if s1 * s2 < 0:
                how = "пешеходный переход" if G.edges[b, c]["crossing"] or G.edges[a, b]["crossing"] else "переход"
                road_x.append({"road": e["name"] or hw_ru(e["hw"]), "hw": e["hw"], "how": how})
            break
    if path:
        coords.append((G.nodes[path[-1]]["x"], G.nodes[path[-1]]["y"]))
    # убираем дубли: одна дорога/одна ж/д линия в одном месте
    rail_x = list(dict.fromkeys(rail_x))
    seen, roads = set(), []
    for r in road_x:
        if r["road"] not in seen:
            seen.add(r["road"])
            roads.append(r)
    return {"length_m": int(length), "minutes": round(t, 1), "gain_m": round(gain, 1),
            "rail_crossings": rail_x, "road_crossings": roads, "coords": coords}


def beach_route(ctx, hotel):
    dist, pred, src = beach_field(ctx)
    if dist is None:
        return None
    n = hotel.get("node") or ctx.nearest_node(hotel["x"], hotel["y"])
    if n is None or n not in dist:
        return None
    p = _path_from_pred(pred, n)
    a = analyze_path(ctx, p)
    end = p[-1]
    ex, ey = ctx.graph.nodes[end]["x"], ctx.graph.nodes[end]["y"]
    beach = None
    best = 1e9
    for b in ctx.beaches:
        d = b["geom"].distance(Point(ex, ey))
        if d < best:
            best, beach = d, b
    straight = None
    if ctx.sea_poly is not None:
        straight = int(ctx.sea_poly.distance(Point(hotel["x"], hotel["y"])))
    surf = ((beach or {}).get("surface") or "").split(";")[0].strip()
    a.update({"beach_name": (beach or {}).get("name") or "", "beach_surface": SURFACE_RU.get(surf, ""),
              "beach_osm": (beach or {}).get("osm"), "straight_to_sea_m": straight, "target_source": src})
    a["coords_ll"] = [[round(v, 6) for v in ctx.to_ll(x, y)] for x, y in a.pop("coords")[::2]]
    return a


def reachable(ctx, hotel, cutoff_m=1500):
    """Расстояния пешком от отеля до всех узлов в радиусе cutoff (кэшируется)."""
    cache = ctx.__dict__.setdefault("_reach", {})
    if hotel["id"] in cache:
        return cache[hotel["id"]]
    n = hotel.get("node") or ctx.nearest_node(hotel["x"], hotel["y"])
    if n is None:
        cache[hotel["id"]] = {}
        return {}
    d = nx.single_source_dijkstra_path_length(ctx.graph, n, cutoff=cutoff_m, weight="length")
    cache[hotel["id"]] = d
    return d


def poi_node_index(ctx):
    if getattr(ctx, "_poi_nodes", None) is None:
        if ctx.node_tree is None or not ctx.pois:
            ctx._poi_nodes = []
        else:
            xy = np.array([[p["x"], p["y"]] for p in ctx.pois])
            dd, jj = ctx.node_tree.query(xy)
            ctx._poi_nodes = [(ctx.node_ids[int(j)], float(d)) for d, j in zip(dd, jj)]
    return ctx._poi_nodes


def match_filter(tags, flt):
    """flt: {"amenity": ["cafe", "bar"], "shop": "*"} — совпадение по любому ключу.
    Значения поддерживают регэкспы в виде "re:...". Ключ "name~" ищет подстроку в name."""
    for k, vals in flt.items():
        if k == "name~":
            nm = (tags.get("name") or "").lower()
            if any(v.lower() in nm for v in (vals if isinstance(vals, list) else [vals])):
                return True
            continue
        v = tags.get(k)
        if v is None:
            continue
        vals = vals if isinstance(vals, list) else [vals]
        for want in vals:
            if want == "*" or want == v or (isinstance(want, str) and want.startswith("re:") and re.search(want[3:], v)):
                return True
    return False


_T = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")


def open_after(oh, hhmm="23:00"):
    """True/False/None: работает ли заведение после указанного времени хотя бы в какие-то дни."""
    if not oh:
        return None
    s = oh.strip().lower()
    if "24/7" in s or "00:00-24:00" in s.replace(" ", ""):
        return True
    h, m = map(int, hhmm.split(":"))
    want = h * 60 + m
    found = False
    for a, b, c, d in _T.findall(s):
        found = True
        start, end = int(a) * 60 + int(b), int(c) * 60 + int(d)
        if end <= start:  # через полночь
            return True
        if end >= want:
            return True
    return False if found else None
