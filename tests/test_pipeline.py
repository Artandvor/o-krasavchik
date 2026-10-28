"""Проверки на синтетическом берегу, где правда известна по построению (см. tests/synth.py)."""
from app import truth
from app.agents import compiler, hotelier
from app.agents.search import rule_parse, search
from app.geo.walk import open_after
from app.registry import get_registry
from app.store import get_store


def by_name(name):
    return next(h for h in get_store().hotels() if h["name"] == name)


def resolved(name, key):
    spec = get_registry().get(key)
    hid = by_name(name)["id"]
    return truth.resolve(spec, get_store().facts(hid, key))


# ---------------------------------------------------------------- вид из окна

def test_front_line_sees_sea():
    r = resolved("Отель Первая линия", "sea_view")
    assert r["value"] is True
    assert "ЮЗ" in r["detail"]["by_side"]


def test_tower_blocks_sea_facing_side():
    r = resolved("Отель За башней", "sea_view")
    assert "ЮЗ" not in r["detail"]["by_side"], "60-метровая башня закрывает море с ЮЗ"


def test_tall_hotel_sees_sea_from_upper_floors_only():
    r = resolved("Отель Высотка", "sea_view")
    sw = r["detail"]["by_side"]["ЮЗ"]
    assert sw["from_floor"] >= 3, "ряд 9-метровых домов закрывает нижние этажи"
    grid = {int(k): v for k, v in r["detail"]["grid"]["ЮЗ"]["p"].items()}
    assert grid[1] < 0.3 and grid[max(grid)] > 0.6


def test_inland_no_sea():
    r = resolved("Отель Нагорный", "sea_view")
    assert r["value"] is False


def test_sunset_months_follow_sun_azimuth():
    r = resolved("Отель Первая линия", "sunset_view")
    nw = r["detail"]["by_side"]["СЗ"]["months"]
    sw = r["detail"]["by_side"]["ЮЗ"]["months"]
    assert 6 in nw, "летом солнце садится на СЗ"
    assert 12 in sw, "зимой — на ЮЗ"


# ---------------------------------------------------------------- доступность

def test_beach_route_crossings():
    assert resolved("Отель Первая линия", "beach_no_crossing")["value"] is True
    r = resolved("Отель За башней", "beach_no_crossing")
    assert r["value"] is False
    assert any("наземный" in x for x in r["detail"]["rail"])
    r = resolved("Отель Нагорный", "beach_no_crossing")
    assert any("подземный" in x for x in r["detail"]["rail"])


def test_walk_time_reasonable():
    m = resolved("Отель Нагорный", "beach_walk")["value"]
    assert 20 < m < 60


def test_night_pois():
    assert resolved("Отель Первая линия", "night_pharmacy")["value"] is True
    assert resolved("Отель Нагорный", "night_pharmacy")["value"] is False


def test_open_after():
    assert open_after("24/7") is True
    assert open_after("Mo-Su 10:00-01:00") is True
    assert open_after("Mo-Fr 09:00-21:00") is False
    assert open_after("") is None


# ---------------------------------------------------------------- шум

def test_rail_side_is_louder():
    r = resolved("Отель Первая линия", "quiet_night")
    sides = r["detail"]["by_side"]
    assert sides["СВ"]["night"] > sides["ЮЗ"]["night"], "сторона к ж/д и трассе громче, чем к морю"


# ---------------------------------------------------------------- отельер и противоречия

def test_hotelier_parse_rules():
    spec = get_registry().get("pets")
    p = hotelier.rule_parse(spec, "Да, с собаками можно, до 10 кг. Доплата 700 руб в сутки.", None)
    assert p["value"] is True and p["max_weight_kg"] == 10 and p["fee_rub"] == 700
    p = hotelier.rule_parse(spec, "К сожалению, с животными не размещаем.", None)
    assert p["value"] is False


def test_conflict_detected_and_confidence_drops():
    store = get_store()
    h = by_name("Отель Первая линия")
    before = resolved("Отель Первая линия", "sea_view")["confidence"]
    qid = store.add_question(h["id"], "sea_view", "Видно ли море?", {"value": True, "scope": "..."},
                             ["Да, верно", "Нет"], 1.0, "тест")
    hotelier.answer(qid, "Нет, вид закрыл новый дом.", store)
    after = truth.resolve(get_registry().get("sea_view"), store.facts(h["id"], "sea_view"))
    assert after["conflict"] is not None
    assert after["confidence"] < before
    assert any(c["key"] == "sea_view" for c in store.conflicts(h["id"]))


# ---------------------------------------------------------------- поиск и расширяемость

def test_query_parsing():
    q = rule_parse("тихий номер с видом на закат недалеко от моря")
    keys = {c["key"] for c in q["criteria"]}
    assert {"quiet_night", "sunset_view", "beach_walk"} <= keys


def test_search_ranks_front_line_for_kids():
    r = search("с детьми, к морю без перехода через трассу", log=False)
    assert r["results"][0]["name"] == "Отель Первая линия"


def test_compile_new_characteristic_from_text():
    spec = compiler.compile_text("рядом есть кафе, открытое после 23:00, в 300 метрах")
    assert spec["tool"] == "poi_nearby"
    assert spec["params"]["radius_m"] == 300 and spec["params"]["open_after"] == "23:00"
    assert not compiler.validate(spec)
