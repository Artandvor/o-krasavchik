"""Агент-сборщик. Для каждого отеля и каждой характеристики решает:
  1. есть ли свежий факт → пропустить;
  2. какой инструмент вызвать (по спецификации) → получить кандидатов → записать факты;
  3. свести источники, заметить противоречия;
  4. если уверенность ниже порога и отельер может знать ответ → поставить вопрос (через hotelier.plan_questions).
Все решения пишутся в журнал агента — видно, почему он сделал то, что сделал."""
import time
import traceback

from ..registry import get_registry
from ..store import get_store, now_iso
from ..tools import TOOL_RU, TOOLS
from .. import truth

AGENT = "collector"


def collect_hotel(ctx, hotel, keys=None, force=False, store=None, reg=None, cache=None, verbose=False):
    store = store or get_store()
    reg = reg or get_registry()
    cache = {} if cache is None else cache
    done = []
    for spec in reg.all():
        if keys and spec["key"] not in keys:
            continue
        hid = "_region" if spec["scope"] == "region" else hotel["id"]
        existing = [f for f in store.facts(hid, spec["key"]) if f["source_type"] not in ("hotelier", "human")]
        if existing and not force and all(f["valid_until"] > now_iso() for f in existing):
            continue
        tool = TOOLS.get(spec["tool"])
        if tool is None:
            store.log(AGENT, "error", f"нет инструмента {spec['tool']}", hid, spec["key"])
            continue
        t0 = time.time()
        try:
            cands = tool["fn"](ctx, hotel, spec, cache)
        except Exception as e:  # noqa: BLE001
            store.log(AGENT, "error", f"{TOOL_RU.get(spec['tool'], spec['tool'])}: {e}", hid, spec["key"], {"trace": traceback.format_exc()[-800:]})
            if verbose:
                traceback.print_exc()
            continue
        if not cands:
            msg = ("в открытых данных этого нет — спросим отельера" if spec["tool"] == "hotelier_only"
                   else f"{TOOL_RU.get(spec['tool'], spec['tool'])}: в открытых данных нет ответа")
            store.log(AGENT, "no_data", msg, hid, spec["key"])
            continue
        for c in cands:
            prev = store.facts(hid, spec["key"])
            prev_same = [f for f in prev if f["source_type"] == c["source_type"]]
            fid = store.add_fact(hid, spec["key"], c["value"], c["confidence"], c["source_type"],
                                 c.get("source_ref", ""), c.get("scope", ""), c.get("detail"),
                                 c.get("method", ""), spec["ttl_days"], c.get("note", ""))
            changed = prev_same and prev_same[-1]["value"] != c["value"]
            store.log(AGENT, "changed" if changed else "fact",
                      f"{spec['title']}: {truth.fmt(c['value'])} — {c.get('scope', '')} "
                      f"(уверенность {c['confidence']:.0%}, {time.time() - t0:.1f} с)",
                      hid, spec["key"], {"fact_id": fid, "tool": spec["tool"],
                                         "prev": prev_same[-1]["value"] if changed else None})
            done.append((spec["key"], fid))
        truth.resolve(spec, store.facts(hid, spec["key"]), store, hid)
    return done


def collect_all(ctx, hotels=None, keys=None, force=False, progress=True):
    store = get_store()
    reg = get_registry()
    hotels = hotels or ctx.hotels
    region_cache = {}
    t0 = time.time()
    for i, h in enumerate(hotels):
        cache = {"climate": region_cache.get("climate")} if region_cache.get("climate") else {}
        collect_hotel(ctx, h, keys, force, store, reg, cache)
        if "climate" in cache:
            region_cache["climate"] = cache["climate"]
        store.commit()
        if progress and (i % 10 == 0 or i == len(hotels) - 1):
            el = time.time() - t0
            print(f"[collector] {i + 1}/{len(hotels)} отелей, {el:.0f} с", flush=True)
    store.commit()
