"""Скачивает открытые данные региона в data/raw/. Только стандартная библиотека Python —
запускается на любом Mac/Linux без pip install:

    python3 scripts/fetch_data.py              # всё
    python3 scripts/fetch_data.py osm dem      # только части

Источники:
  * OpenStreetMap через Overpass API: отели, здания, дороги, ж/д, пляжи, POI, аэропорт
  * Рельеф: Copernicus DEM GLO-30 (AWS Open Data, без ключа)
  * Климат: Open-Meteo Historical (ERA5), море: Open-Meteo Marine, воздух: Open-Meteo Air Quality (CAMS)

Повторный запуск продолжает с места остановки: скачанное не качается заново.
Обработка (растры, графы, факты) — отдельно: scripts/prepare_region.py.
"""
import json
import math
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
CFG = json.loads((ROOT / "config" / "region.json").read_text(encoding="utf-8"))
UA = "odin-shag-hackathon/0.1 (open data prototype)"

OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def pad_bbox(b, pad_m):
    s, w, n, e = b
    dlat = pad_m / 110_574.0
    dlon = pad_m / (111_320.0 * math.cos(math.radians((s + n) / 2)))
    return [s - dlat, w - dlon, n + dlat, e + dlon]


def _curl(url, timeout, data=None):
    cmd = ["curl", "-sSfL", "--max-time", str(timeout), "-A", UA]
    if data is not None:
        cmd += ["--data-binary", "@-"]
    cmd.append(url)
    r = subprocess.run(cmd, input=data, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl {r.returncode}: {r.stderr.decode()[:200]}")
    return r.stdout


def http(url, timeout=120, data=None, retries=3):
    """urllib, а при проблемах с SSL-сертификатами на macOS — системный curl."""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if "CERTIFICATE" in str(e) or "SSL" in str(e):
                try:
                    return _curl(url, timeout, data)
                except Exception as e2:  # noqa: BLE001
                    last = e2
            wait = 5 * (i + 1)
            print(f"   ! {type(last).__name__}: {str(last)[:150]} — повтор через {wait}с")
            time.sleep(wait)
    raise last


def bb(b):
    return ",".join(f"{x:.5f}" for x in b)


def overpass(query, name):
    out = RAW / f"osm_{name}.json"
    if out.exists() and out.stat().st_size > 100:
        print(f"[osm] {name}: уже есть")
        return
    body = urllib.parse.urlencode({"data": query}).encode()
    for ep in OVERPASS:
        try:
            print(f"[osm] {name} ← {ep}")
            raw = http(ep, timeout=300, data=body, retries=2)
            js = json.loads(raw)
            if "elements" not in js:
                raise ValueError("в ответе нет elements")
            out.write_bytes(raw)
            print(f"[osm] {name}: {len(js['elements'])} объектов")
            return
        except Exception as e:  # noqa: BLE001
            print(f"   ! не вышло: {str(e)[:150]}")
    raise SystemExit(f"Overpass недоступен для {name}. Попробуйте позже или через VPN.")


def fetch_osm():
    hb = CFG["hotels_bbox"]
    H, P = bb(hb), bb(pad_bbox(hb, CFG["pad_m"]))
    A = bb(pad_bbox(hb, 8000))
    head = "[out:json][timeout:250];"
    queries = {
        "hotels": f'{head}(nwr["tourism"~"^(hotel|guest_house|hostel|motel|apartment|chalet)$"]({H}););out meta geom;',
        "buildings": f'{head}(way["building"]({P});relation["building"]({P}););out body geom;',
        "roads": f'{head}(way["highway"]({P}););out body geom;',
        "rail": f'{head}(way["railway"~"^(rail|light_rail|narrow_gauge|platform)$"]({P});'
                f'node["railway"~"^(crossing|level_crossing|station|halt)$"]({P}););out body geom;',
        # «природа» разбита на лёгкие запросы; геометрия обрезается рамкой, чтобы огромные
        # мультиполигоны (реки, парки) не тянулись целиком
        "coast": f'{head}way["natural"="coastline"]({P});out body geom({P});',
        "beach": f'{head}(nwr["natural"="beach"]({P});nwr["leisure"="beach_resort"]({P}););out meta geom({P});',
        "leisure": f'{head}nwr["leisure"~"^(playground|dog_park|park|garden)$"]({P});out meta geom({P});',
        "construction": f'{head}(nwr["landuse"="construction"]({P});way["building"="construction"]({P}););out meta geom({P});',
        "pois": f'{head}(nwr["amenity"]({P});nwr["shop"]({P});nwr["healthcare"]({P});'
                f'nwr["tourism"~"^(attraction|viewpoint|museum)$"]({P}););out center meta;',
        "aero": f'{head}(nwr["aeroway"~"^(aerodrome|runway)$"]({A}););out body geom;',
    }
    for name, q in queries.items():
        overpass(q, name)
        time.sleep(2)


def fetch_dem():
    near = pad_bbox(CFG["hotels_bbox"], CFG["pad_m"] + 500)
    far = CFG["far_bbox"]
    s = min(near[0], far[0]); w = min(near[1], far[1])
    n = max(near[2], far[2]); e = max(near[3], far[3])
    for la in range(math.floor(s), math.floor(n) + 1):
        for lo in range(math.floor(w), math.floor(e) + 1):
            name = f"Copernicus_DSM_COG_10_N{la:02d}_00_E{lo:03d}_00_DEM"
            p = RAW / f"{name}.tif"
            if p.exists() and p.stat().st_size > 1_000_000:
                print(f"[dem] {name}: уже есть")
                continue
            url = f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
            print(f"[dem] качаю {name} (30–50 МБ)…")
            p.write_bytes(http(url, timeout=900))
            print(f"[dem] {name}: {p.stat().st_size // 1_000_000} МБ")


def fetch_climate():
    la, lo = CFG["climate_point"]
    sla, slo = CFG["sea_point"]
    jobs = [
        ("climate_daily.json",
         "https://archive-api.open-meteo.com/v1/archive?"
         f"latitude={la}&longitude={lo}&start_date=2016-01-01&end_date=2025-12-31"
         "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,sunshine_duration"
         "&timezone=Europe%2FMoscow"),
        ("marine_hourly.json",
         "https://marine-api.open-meteo.com/v1/marine?"
         f"latitude={sla}&longitude={slo}&start_date=2023-01-01&end_date=2025-12-31"
         "&hourly=sea_surface_temperature&timezone=Europe%2FMoscow"),
        ("air_quality.json",
         "https://air-quality-api.open-meteo.com/v1/air-quality?"
         f"latitude={la}&longitude={lo}&start_date=2024-01-01&end_date=2025-12-31"
         "&hourly=pm2_5,pm10&timezone=Europe%2FMoscow"),
    ]
    for fname, url in jobs:
        out = RAW / fname
        if out.exists() and out.stat().st_size > 100:
            print(f"[climate] {fname}: уже есть")
            continue
        try:
            out.write_bytes(http(url, timeout=300))
            print(f"[climate] {fname}: готово")
        except Exception as e:  # noqa: BLE001
            print(f"[climate] {fname}: недоступно ({str(e)[:120]}) — продолжаю без него")


if __name__ == "__main__":
    parts = sys.argv[1:] or ["osm", "dem", "climate"]
    t0 = time.time()
    if "osm" in parts:
        fetch_osm()
    if "dem" in parts:
        fetch_dem()
    if "climate" in parts:
        fetch_climate()
    print(f"\nГотово за {time.time() - t0:.0f}с. Файлы в {RAW}")
