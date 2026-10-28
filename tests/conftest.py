"""Перед импортом app.* собираем синтетический регион во временной папке и направляем туда систему."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="odin-test-"))
os.environ["ODIN_DATA"] = str(TMP)
os.environ["ODIN_REGION"] = str(TMP / "region.json")
os.environ["LLM_PROVIDER"] = "none"
sys.path.insert(0, str(ROOT))

subprocess.run([sys.executable, str(ROOT / "tests" / "synth.py"), str(TMP)], check=True, capture_output=True)
subprocess.run([sys.executable, str(ROOT / "scripts" / "prepare_region.py")], check=True, capture_output=True,
               env=os.environ.copy())
subprocess.run([sys.executable, str(ROOT / "scripts" / "run_agents.py"), "--fresh", "--no-simulate"], check=True,
               capture_output=True, env=os.environ.copy())
