"""Сведение фактов из разных источников в одно значение + обнаружение противоречий.

Правила:
  * вес факта = уверенность × доверие к типу источника (из спецификации характеристики)
    × штраф за устаревание;
  * источники согласны → уверенности складываются как независимые свидетельства
    1 − Π(1 − wᵢ);
  * источники противоречат → берём значение с бо́льшим весом, но уверенность снижаем,
    открываем конфликт и ставим уточняющий вопрос отельеру.
"""
from datetime import datetime, timezone

from .store import now_iso


def _stale(f):
    return f["valid_until"] < now_iso()


def same_value(spec, a, b):
    va, vb = a["value"], b["value"]
    if spec["type"] == "number":
        if va is None or vb is None:
            return True
        return abs(float(va) - float(vb)) <= max(2.0, 0.3 * max(abs(float(va)), abs(float(vb))))
    if spec["type"] == "months":
        sa, sb = set(va or []), set(vb or [])
        return len(sa ^ sb) <= 2
    if spec["type"] == "text":
        return True
    if spec.get("ordinal") and spec.get("values") and va in spec["values"] and vb in spec["values"]:
        # соседние классы («тихо» и «умеренно») — не противоречие, а разная точка измерения
        return abs(spec["values"].index(va) - spec["values"].index(vb)) <= 1
    if va != vb:
        return False
    # для «номерных» характеристик сравниваем ещё и с какого этажа
    fa = (a.get("detail") or {}).get("from_floor_min")
    fb = (b.get("detail") or {}).get("from_floor_min")
    if fa and fb and abs(fa - fb) > 2:
        return False
    return True


def weight(spec, f):
    trust = spec.get("trust", {}).get(f["source_type"], 0.6)
    w = f["confidence"] * trust
    if _stale(f):
        w *= 0.7
    return w


def resolve(spec, facts, store=None, hotel_id=None, create=True):
    """Возвращает сведённое значение {value, confidence, scope, sources[], conflict, stale}.
    create=False — только смотрим статус конфликта, новые не открываем (для поискового индекса)."""
    facts = [f for f in facts if f["status"] == "active" and f["value"] is not None]
    if not facts:
        return None
    ranked = sorted(facts, key=lambda f: -weight(spec, f))
    top = ranked[0]
    agree = [f for f in ranked if same_value(spec, top, f)]
    disagree = [f for f in ranked if not same_value(spec, top, f)]
    # уверенность главного факта + независимые подтверждения (с весом доверия к источнику)
    miss = 1 - top["confidence"] * (0.7 if _stale(top) else 1.0)
    for f in agree[1:]:
        if f["source_type"] == top["source_type"]:
            continue
        miss *= 1 - 0.8 * weight(spec, f)
    conf = 1 - miss
    conflict = None
    if disagree:
        d = disagree[0]
        status = None
        if store is not None and hotel_id:
            status = store.conflict_status(hotel_id, spec["key"], top["id"], d["id"])
            if status is None and create:
                store.open_conflict(hotel_id, spec["key"], top["id"], d["id"],
                                    f"{source_name(top['source_type'])}: {fmt(top['value'])} ({top['scope']}) ≠ "
                                    f"{source_name(d['source_type'])}: {fmt(d['value'])} ({d['scope']})")
                status = {"status": "open", "resolution": None}
        resolved = bool(status and status["status"] == "resolved")
        if not resolved:
            conf *= 0.6
        conflict = {"with_fact": d["id"], "with_source": d["source_type"], "with_value": d["value"],
                    "with_scope": d["scope"], "resolved": resolved,
                    "resolution": status["resolution"] if status else None}
    # подтверждение отельера наследует детализацию расчёта (стороны, этажи, сетка)
    detail, scope = top["detail"], top["scope"]
    if not (detail or {}).get("grid"):
        rich = next((f for f in agree if (f.get("detail") or {}).get("grid")), None)
        if rich is not None:
            detail = rich["detail"]
            if top["source_type"] == "hotelier":
                scope = f"{rich['scope']} — подтвердил отельер"
    geo_grid = next(((f.get("detail") or {}).get("grid") for f in ranked if (f.get("detail") or {}).get("grid")), None)
    return {"value": top["value"], "confidence": round(min(conf, 0.98), 3), "scope": scope, "geo_grid": geo_grid,
            "detail": detail, "source_type": top["source_type"], "fact_id": top["id"],
            "obtained_at": top["obtained_at"], "valid_until": top["valid_until"], "stale": _stale(top),
            "sources": [{"id": f["id"], "type": f["source_type"], "value": f["value"], "confidence": f["confidence"],
                         "scope": f["scope"], "ref": f["source_ref"], "method": f["method"],
                         "obtained_at": f["obtained_at"], "agrees": f in agree} for f in ranked],
            "conflict": conflict}


SOURCE_NAMES = {"geo": "расчёт по геоданным", "osm_tag": "OpenStreetMap", "hotelier": "отельер",
                "open_api": "открытые данные", "llm_extract": "разбор текста", "human": "разметка",
                "guest": "гость после поездки"}


def source_name(t):
    return SOURCE_NAMES.get(t, t)


def fmt(v):
    if v is True:
        return "да"
    if v is False:
        return "нет"
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return str(v)


def age_days(iso):
    try:
        dt = datetime.fromisoformat(iso)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:  # noqa: BLE001
        return None
