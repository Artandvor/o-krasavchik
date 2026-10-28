"""Новая характеристика из текстового описания → YAML-спецификация на существующих инструментах.

«рядом есть кафе, открытое после 23:00, в 300 метрах» →
    tool: poi_nearby, params: {filter: {amenity: cafe}, radius_m: 300, open_after: "23:00"}

LLM получает каталог инструментов и подбирает инструмент и параметры. Без LLM работает
правиловый компилятор для самых частых шаблонов («<объект> в N м [работает после HH:MM]»).
Результат всегда проверяется: инструмент существует, прогон на нескольких отелях без ошибок.
"""
import re

from ..llm import get_llm
from ..tools import TOOLS, catalog

# словарь «слово → теги OSM» для правилового компилятора
WORDS = [
    (r"кофейн", {"amenity": "cafe", "cuisine": "coffee_shop"}, "кофейня"),
    (r"кафе", {"amenity": "cafe"}, "кафе"),
    (r"ресторан", {"amenity": "restaurant"}, "ресторан"),
    (r"бар\b|бары|паб", {"amenity": ["bar", "pub"]}, "бар"),
    (r"фастфуд|шаурм|бургер", {"amenity": "fast_food"}, "фастфуд"),
    (r"аптек", {"amenity": "pharmacy", "healthcare": "pharmacy"}, "аптека"),
    (r"супермаркет|продукт|магазин", {"shop": ["supermarket", "convenience"]}, "магазин"),
    (r"банкомат", {"amenity": "atm"}, "банкомат"),
    (r"банк\b", {"amenity": "bank"}, "банк"),
    (r"прачечн", {"shop": ["laundry", "dry_cleaning"]}, "прачечная"),
    (r"рынок", {"amenity": "marketplace"}, "рынок"),
    (r"храм|церк", {"amenity": "place_of_worship"}, "храм"),
    (r"музей", {"tourism": "museum"}, "музей"),
    (r"смотровая|видовая", {"tourism": "viewpoint"}, "смотровая площадка"),
    (r"больниц|клиник|травмпункт", {"amenity": ["hospital", "clinic"]}, "больница"),
    (r"ветеринар|ветклиник", {"amenity": "veterinary"}, "ветклиника"),
    (r"заправк|азс", {"amenity": "fuel"}, "АЗС"),
    (r"прокат велос|велопрокат", {"amenity": "bicycle_rental"}, "велопрокат"),
    (r"туалет", {"amenity": "toilets"}, "туалет"),
    (r"кинотеатр", {"amenity": "cinema"}, "кинотеатр"),
    (r"мороженое", {"shop": "ice_cream", "cuisine": "ice_cream"}, "мороженое"),
]


POI_KEYS = {"amenity", "shop", "healthcare", "tourism", "cuisine", "name", "opening_hours"}

STOP = {"рядом", "есть", "открытое", "открыто", "метрах", "метров", "минутах", "минут", "после", "около", "чтобы",
        "можно", "недалеко", "пешком", "работает", "отеля", "отель", "ближайший", "ближайшая", "круглосуточно"}


def slug(s):
    tr = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                  ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                   "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
    s = "".join(tr.get(ch, ch) for ch in s.lower())
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40] or "custom"


def rule_compile(text):
    t = text.lower()
    for pat, flt, name in WORDS:
        if re.search(pat, t):
            break
    else:
        return None
    m = re.search(r"(\d+[.,]?\d*)\s*(км|километр)", t)
    radius = float(m.group(1).replace(",", ".")) * 1000 if m else None
    if radius is None:
        m = re.search(r"(\d{2,4})\s*(м\b|метр)", t)
        radius = float(m.group(1)) if m else None
    m = re.search(r"(\d{1,2})\s*мин", t)
    if radius is None and m:
        radius = float(m.group(1)) * 75
    radius = radius or 500
    params = {"layer": "pois", "filter": flt, "radius_m": int(radius)}
    m = re.search(r"(?:после|до|позже)\s*(\d{1,2})(?::(\d{2}))?", t)
    if "круглосуточ" in t or "24/7" in t:
        params["open_after"] = "23:59"
    elif m:
        params["open_after"] = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    title = f"{name.capitalize()} в {int(radius)} м" + (f", открыто после {params['open_after']}" if "open_after" in params else "")
    key = slug(f"{name}_{int(radius)}" + ("_late" if "open_after" in params else ""))
    return {"key": key, "title": title, "group": "Мои характеристики", "description": text.strip(), "scope": "hotel",
            "type": "bool", "tool": "poi_nearby", "params": params, "sources": ["OpenStreetMap"], "ttl_days": 90,
            "trust": {"osm_tag": 0.6, "hotelier": 0.8}, "demand": 0.05,
            "search": {"synonyms": [name, *[w for w in re.findall(r"[а-яё]{5,}", t) if w not in STOP and w != name][:2]],
                       "desired": True},
            "_compiler": "rules"}


def llm_compile(text):
    llm = get_llm()
    if not llm.available:
        return None
    example = {"key": "late_cafe_300", "title": "Кафе в 300 м, открыто после 23:00", "group": "Мои характеристики",
               "description": "...", "scope": "hotel", "type": "bool", "tool": "poi_nearby",
               "params": {"layer": "pois", "filter": {"amenity": "cafe"}, "radius_m": 300, "open_after": "23:00"},
               "sources": ["OpenStreetMap"], "ttl_days": 90, "trust": {"osm_tag": 0.6, "hotelier": 0.8}, "demand": 0.05,
               "hotelier": {"ask_below": 0.6, "question": "..."},
               "search": {"synonyms": ["кафе ночью"], "desired": True}}
    sys_p = ("Ты проектируешь характеристику отеля для агентной системы. Выбери ОДИН инструмент из каталога и параметры. "
             "Для объектов на карте используй теги OpenStreetMap. Если открытых данных нет — tool: hotelier_only и "
             "заполни hotelier.question. scope: hotel|room|region. type: bool|number|enum|text.")
    js = llm.json(sys_p, f"Каталог инструментов: {catalog()}\nПример: {example}\nОписание: {text}")
    if isinstance(js, dict) and js.get("tool") in TOOLS:
        js.setdefault("group", "Мои характеристики")
        js.setdefault("description", text)
        js["key"] = slug(js.get("key") or js.get("title", "custom"))
        js["_compiler"] = f"llm:{llm.model}"
        return js
    return None


def compile_text(text):
    spec = llm_compile(text) or rule_compile(text)
    if spec is not None and any("нет тегов" in e for e in validate(spec)):
        spec = None  # по открытым данным это не посчитать — честно отдаём отельеру
    if spec is None:
        spec = {"key": slug(text[:30]), "title": text.strip()[:60], "group": "Мои характеристики",
                "description": text.strip(), "scope": "hotel", "type": "bool", "tool": "hotelier_only", "params": {},
                "sources": ["отельер"], "ttl_days": 365, "trust": {"hotelier": 0.9}, "demand": 0.05,
                "hotelier": {"ask_below": 0.9, "question": f"{text.strip().rstrip('?')}?"},
                "search": {"synonyms": re.findall(r"[а-яё]{5,}", text.lower())[:3], "desired": True},
                "_compiler": "fallback: открытых данных нет — спросим отельера"}
    return spec


def validate(spec):
    errs = []
    for k in ("key", "title", "type", "tool", "scope"):
        if not spec.get(k):
            errs.append(f"нет поля {k}")
    if spec.get("tool") not in TOOLS:
        errs.append(f"неизвестный инструмент {spec.get('tool')}")
    if spec.get("type") not in ("bool", "number", "enum", "text", "months"):
        errs.append("type должен быть bool|number|enum|text|months")
    # слой pois собран только по этим тегам OSM: искать по другим — значит всегда получать «нет»
    p = spec.get("params") or {}
    if spec.get("tool") in ("poi_nearby", "distance_to") and p.get("layer", "pois") == "pois":
        bad = [k for k in (p.get("filter") or {}) if k.split(":")[0].rstrip("~") not in POI_KEYS]
        if bad:
            errs.append(f"в собранных данных нет тегов {', '.join(bad)} — такую характеристику пока может заполнить только отельер")
    return errs
