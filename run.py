"""Запуск прототипа:  python run.py  →  http://localhost:8080

Демо-база data/odin-demo.sqlite лежит в репозитории. Если задан ODIN_DB (так в Docker),
при первом старте она копируется туда — рабочая база пишется отдельно, демо остаётся чистым."""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from app.config import DATA, DB_PATH, PROC
    demo = DATA / "odin-demo.sqlite"
    if not DB_PATH.exists() and demo.exists() and DB_PATH != demo:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(demo, DB_PATH)
        print(f"[run] рабочая база создана из демо: {DB_PATH}", flush=True)
    if not (PROC / "grid.npz").exists() or not DB_PATH.exists():
        sys.exit("[run] нет демо-данных: data/processed/ и data/odin-demo.sqlite. "
                 "Пересборка: make seed (или python scripts/fetch_data.py && python scripts/prepare_region.py && "
                 "python scripts/run_agents.py --fresh)")
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"[run] О!дин шаг слушает {host}:{port} → http://localhost:{port}", flush=True)
    reload = os.environ.get("RELOAD") == "1"  # для разработки (docker-compose.override.yml.example)
    uvicorn.run("app.api:app", host=host, port=port, log_level="info", reload=reload,
                reload_dirs=[str(ROOT / "app")] if reload else None)
