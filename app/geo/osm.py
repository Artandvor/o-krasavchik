"""Разбор ответов Overpass (out geom / out center) в shapely-геометрии в локальных метрах."""
import json
import re
from pathlib import Path

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

from .proj import LocalProj


def load(path: Path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("elements", [])


def _coords(geom, proj: LocalProj):
    return [proj.to_xy(p["lat"], p["lon"]) for p in geom if p]


def _merge(lines):
    u = unary_union(lines)
    if isinstance(u, LineString):
        return u
    try:
        return linemerge(u)
    except (ValueError, TypeError):
        return u


def element_geometry(el, proj: LocalProj, as_area=None):
    """Возвращает shapely-геометрию элемента. as_area: True/False/None(авто по замкнутости)."""
    t = el["type"]
    if t == "node":
        return Point(proj.to_xy(el["lat"], el["lon"]))
    if "center" in el and "geometry" not in el and "members" not in el:
        return Point(proj.to_xy(el["center"]["lat"], el["center"]["lon"]))
    if t == "way":
        cs = _coords(el.get("geometry", []), proj)
        if len(cs) < 2:
            return None
        closed = len(cs) >= 4 and cs[0] == cs[-1]
        if (as_area is True or (as_area is None and closed)) and len(cs) >= 4:
            p = Polygon(cs)
            return p if p.is_valid else p.buffer(0)
        return LineString(cs)
    if t == "relation":
        outers, inners = [], []
        for m in el.get("members", []):
            if m.get("type") != "way" or "geometry" not in m:
                continue
            cs = _coords(m["geometry"], proj)
            if len(cs) < 2:
                continue
            (inners if m.get("role") == "inner" else outers).append(LineString(cs))
        if not outers:
            return None
        polys = list(polygonize(_merge(outers)))
        if not polys:
            return unary_union(outers)
        area = unary_union(polys)
        if inners:
            holes = list(polygonize(_merge(inners)))
            if holes:
                area = area.difference(unary_union(holes))
        return area if area.is_valid else area.buffer(0)
    return None


def tags(el):
    return el.get("tags", {}) or {}


def osm_ref(el):
    return f"https://www.openstreetmap.org/{el['type']}/{el['id']}"


def osm_meta(el):
    return {"osm": f"{el['type']}/{el['id']}", "timestamp": el.get("timestamp"),
            "version": el.get("version")}


def parse_float(v):
    if v is None:
        return None
    try:
        s = str(v).replace(",", ".").split(";")[0].strip().lower()
        for suf in (" m", "m", " м", "м"):
            if s.endswith(suf):
                s = s[: -len(suf)]
        return float(s)
    except ValueError:
        return None


def polygons_of(g):
    if g is None:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    if hasattr(g, "geoms"):
        return [x for x in g.geoms if isinstance(x, Polygon)]
    return []


# Коды OSM → по-русски, чтобы в тексты гостю не попадала латиница
HW_RU = {"motorway": "шоссе", "trunk": "трасса", "primary": "магистраль", "secondary": "оживлённая улица",
         "tertiary": "улица", "unclassified": "дорога", "residential": "жилая улица", "living_street": "жилая зона",
         "service": "проезд", "pedestrian": "пешеходная улица", "footway": "пешеходная дорожка", "path": "тропинка",
         "steps": "лестница", "track": "грунтовка", "cycleway": "велодорожка", "road": "дорога"}
AMENITY_RU = {"pharmacy": "аптека", "cafe": "кафе", "restaurant": "ресторан", "fast_food": "фастфуд", "bar": "бар",
              "pub": "паб", "nightclub": "ночной клуб", "parking": "парковка", "charging_station": "зарядная станция",
              "hospital": "больница", "clinic": "клиника", "doctors": "врач", "convenience": "магазин у дома",
              "supermarket": "супермаркет", "alcohol": "алкомаркет", "kiosk": "киоск", "atm": "банкомат",
              "bank": "банк", "playground": "детская площадка", "fuel": "АЗС", "marketplace": "рынок",
              "bus_stop": "остановка", "toilets": "туалет", "fitness_centre": "фитнес-клуб", "laundry": "прачечная"}


def hw_ru(hw: str) -> str:
    return HW_RU.get(str(hw).replace("_link", ""), "дорога")


def poi_name(tags: dict) -> str:
    """Название объекта или его тип по-русски (а не код OSM)."""
    if tags.get("name"):
        return tags["name"]
    for k in ("amenity", "shop", "healthcare", "leisure", "highway"):
        if tags.get(k):
            return AMENITY_RU.get(tags[k], "объект")
    return "объект"


_DAYS = {"Mo": "пн", "Tu": "вт", "We": "ср", "Th": "чт", "Fr": "пт", "Sa": "сб", "Su": "вс", "PH": "праздники"}


def hours_ru(oh: str) -> str:
    """Часы работы OSM по-русски: «Mo-Su 10:00-01:00» → «ежедневно 10:00–01:00»."""
    if not oh:
        return ""
    s = oh.strip()
    if s in ("24/7", "Mo-Su 00:00-24:00"):
        return "круглосуточно"
    s = s.replace("Mo-Su", "ежедневно").replace("24/7", "круглосуточно").replace(" off", " выходной")
    for en, ru in _DAYS.items():
        s = re.sub(rf"\b{en}\b", ru, s)
    s = re.sub(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", r"\1–\2", s)
    return s.replace(";", ",")
