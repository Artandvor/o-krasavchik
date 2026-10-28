import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("ODIN_DATA", ROOT / "data"))
RAW = DATA / "raw"
PROC = DATA / "processed"
DB_PATH = Path(os.environ.get("ODIN_DB", DATA / "odin-demo.sqlite"))
CHAR_DIR = ROOT / "characteristics"
STATIC = ROOT / "app" / "static"

try:  # .env опционален
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def region_cfg():
    p = Path(os.environ.get("ODIN_REGION", ROOT / "config" / "region.json"))
    return json.loads(p.read_text(encoding="utf-8"))


# Метод/версия расчёта — пишется в каждый факт, чтобы понимать, чем он получен
METHOD_VERSION = "2026.10-a"
