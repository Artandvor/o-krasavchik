"""Полный прогон агентов над подготовленным регионом → data/odin.sqlite (демо-база).

    python scripts/run_agents.py                 # сбор + вопросы + симуляция части ответов
    python scripts/run_agents.py --no-simulate   # без имитации ответов отельеров
    python scripts/run_agents.py --keys sea_view,beach_walk --force
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import collector, hotelier  # noqa: E402
from app.config import DB_PATH  # noqa: E402
from app.geo.context import get_ctx  # noqa: E402
from app.store import get_store  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-simulate", action="store_true")
    ap.add_argument("--simulate-share", type=float, default=0.35, help="доля отелей, где «отельер» уже ответил")
    ap.add_argument("--fresh", action="store_true", help="удалить базу и собрать с нуля")
    a = ap.parse_args()
    if a.fresh and DB_PATH.exists():
        DB_PATH.unlink()
        for suf in ("-wal", "-shm"):
            p = Path(str(DB_PATH) + suf)
            if p.exists():
                p.unlink()
    t0 = time.time()
    ctx = get_ctx()
    store = get_store()
    for h in ctx.hotels:
        store.upsert_hotel({k: v for k, v in h.items() if k not in ("score",)})
    store.commit()
    keys = [k for k in a.keys.split(",") if k] or None
    collector.collect_all(ctx, keys=keys, force=a.force)
    print(f"[run] сбор: {time.time() - t0:.0f} с")
    nq = 0
    for h in ctx.hotels:
        nq += len(hotelier.plan_questions(h, store))
    print(f"[run] вопросов отельерам: {nq} ({nq / max(1, len(ctx.hotels)):.1f} на отель)")
    import random
    if not a.no_simulate:
        rnd = random.Random(42)
        chosen = [h for h in ctx.hotels if rnd.random() < a.simulate_share]
        na = 0
        for h in chosen:
            for q in store.questions(h["id"]):
                txt = hotelier.simulate_answer(q, store)
                hotelier.answer(q["id"], txt, store)
                na += 1
        print(f"[run] симулированных ответов: {na} в {len(chosen)} отелях; "
              f"открытых конфликтов: {len(store.conflicts())}")
    if not a.no_simulate:
        # демо-поток запросов гостей: из него считается спрос, который видит отельер
        from app.agents.search import INDEX, search
        INDEX.invalidate()
        demo_q = ["тихий номер с видом на закат недалеко от моря", "вид на море", "закат над морем из окна",
                  "с детьми, чтобы к морю без перехода через железную дорогу", "вид на горы и можно с собакой",
                  "первая линия, тихо", "купаться в октябре", "рядом аптека ночью", "на машине с парковкой",
                  "выспаться, плотные шторы", "вид на море и горы", "у моря без стройки рядом", "кафе ночью рядом",
                  "с собакой до 10 кг", "песчаный пляж", "тихий номер", "закат", "до пляжа 5 минут",
                  "с ребёнком, детская площадка", "вид на море с балкона", "панорама моря", "тишина ночью"]
        rnd2 = random.Random(7)
        for _ in range(140):
            search(rnd2.choice(demo_q), limit=1)
        print(f"[run] демо-запросов гостей: 140")
    store.commit()
    print(f"[run] готово за {time.time() - t0:.0f} с → {DB_PATH}")
