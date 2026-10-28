"""Агент актуализации.

* refresh_stale — пересчитывает факты с истёкшим сроком (у каждой характеристики свой TTL:
  стройки — 30 дней, часы работы — 90, вид из окна — год) и факты, которые отельер оспорил.
* what_if_building — «рядом построили дом»: добавляет здание в модель и пересчитывает
  характеристики только у затронутых отелей, сообщая, что изменилось.
"""
import math

from ..registry import get_registry
from ..store import get_store
from . import collector
from .search import INDEX

AGENT = "refresher"
VIEW_KEYS = ("sea_view", "sunset_view", "mountain_view", "quiet_night")


def refresh_stale(ctx, limit=None):
    store = get_store()
    reg = get_registry()
    stale = store.stale_facts()
    by_hotel = {}
    for f in stale:
        if f["source_type"] in ("hotelier", "human"):
            continue
        by_hotel.setdefault(f["hotel_id"], set()).add(f["key"])
    n = 0
    report = []
    for hid, keys in list(by_hotel.items())[:limit]:
        h = ctx.hotel_by_id.get(hid) if hid != "_region" else (ctx.hotels[0] if ctx.hotels else None)
        if h is None:
            continue
        before = {k: [f["value"] for f in store.facts(hid, k) if f["source_type"] not in ("hotelier", "human")] for k in keys}
        store.log(AGENT, "recheck", f"перепроверка {len(keys)} устаревших характеристик: {', '.join(sorted((reg.get(k) or {}).get('title', k) for k in keys))}", hid)
        collector.collect_hotel(ctx, h, keys=keys, force=True, store=store)
        for k in keys:
            after = [f["value"] for f in store.facts(hid, k) if f["source_type"] not in ("hotelier", "human")]
            if before.get(k) != after:
                report.append({"hotel_id": hid, "key": k, "before": before.get(k), "after": after})
        INDEX.invalidate(hid)
        n += 1
    store.commit()
    return {"hotels": n, "facts": len(stale), "changed": report}


def rect_ll(ctx, lat, lon, width, depth, angle):
    x, y = ctx.proj.to_xy(lat, lon)
    a = math.radians(angle)
    ux, uy = math.sin(a), math.cos(a)
    vx, vy = math.sin(a + math.pi / 2), math.cos(a + math.pi / 2)
    pts = []
    for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        pts.append((x + su * width / 2 * ux + sv * depth / 2 * vx, y + su * width / 2 * uy + sv * depth / 2 * vy))
    return pts


def what_if_building(ctx, lat, lon, height=45.0, width=60.0, depth=20.0, angle=135.0, radius=1200.0):
    store = get_store()
    reg = get_registry()
    poly = rect_ll(ctx, lat, lon, width, depth, angle)
    ctx.add_building(poly, height)
    store.kv_set("what_if_buildings", store.kv_get("what_if_buildings", []) +
                 [{"lat": lat, "lon": lon, "height": height, "width": width, "depth": depth, "angle": angle}])
    x, y = ctx.proj.to_xy(lat, lon)
    affected = [h for h in ctx.hotels if math.hypot(h["x"] - x, h["y"] - y) <= radius]
    changes = []
    keys = [k for k in VIEW_KEYS if reg.get(k)]
    for h in affected:
        before = {k: _main(store, h["id"], k) for k in keys}
        collector.collect_hotel(ctx, h, keys=keys, force=True, store=store)
        after = {k: _main(store, h["id"], k) for k in keys}
        for k in keys:
            b, a = before[k], after[k]
            if b is None or a is None:
                continue
            if _sig(b) != _sig(a):
                changes.append({"hotel_id": h["id"], "hotel": h["name"], "key": k, "title": reg.get(k)["title"],
                                "before": b["scope"], "after": a["scope"], "value_before": b["value"],
                                "value_after": a["value"]})
                store.log(AGENT, "changed", f"новое здание {height:.0f} м: {reg.get(k)['title']} — было «{b['scope']}», "
                                            f"стало «{a['scope']}»", h["id"], k)
        INDEX.invalidate(h["id"])
    store.commit()
    poly_ll = [list(ctx.to_ll(px, py)) for px, py in poly]
    return {"checked": len(affected), "changes": changes, "polygon": poly_ll}


def _sig(f):
    """Существенное в факте: значение и «с какого этажа» по сторонам (не мелкие цифры в тексте)."""
    d = f.get("detail") or {}
    sides = {k: v.get("from_floor") for k, v in (d.get("by_side") or {}).items() if isinstance(v, dict)}
    if f["key"] == "quiet_night":
        sides = {k: round(v["night"] / 3) for k, v in (d.get("by_side") or {}).items()}
    return (str(f["value"]), tuple(sorted(sides.items())))


def _main(store, hid, key):
    fs = [f for f in store.facts(hid, key) if f["source_type"] == "geo"]
    return fs[-1] if fs else None
