"""Положение солнца (алгоритм NOAA, точность ~0.5°) и азимут заката по датам."""
import math
from datetime import datetime, timedelta, timezone


def _solar(dt: datetime, lat: float, lon: float):
    """Возвращает (азимут от севера по часовой, высота) в градусах для UTC-времени dt."""
    jd = dt.timestamp() / 86400.0 + 2440587.5
    jc = (jd - 2451545.0) / 36525.0
    gml = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    gma = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    ma = math.radians(gma)
    eqc = (math.sin(ma) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
           + math.sin(2 * ma) * (0.019993 - 0.000101 * jc) + math.sin(3 * ma) * 0.000289)
    true_long = gml + eqc
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    mean_obl = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obl = math.radians(mean_obl + 0.00256 * math.cos(math.radians(omega)))
    decl = math.asin(math.sin(obl) * math.sin(math.radians(app_long)))
    y = math.tan(obl / 2) ** 2
    l0 = math.radians(gml)
    eot = 4 * math.degrees(y * math.sin(2 * l0) - 2 * ecc * math.sin(ma)
                           + 4 * ecc * y * math.sin(ma) * math.cos(2 * l0)
                           - 0.5 * y * y * math.sin(4 * l0) - 1.25 * ecc * ecc * math.sin(2 * ma))
    minutes = dt.hour * 60 + dt.minute + dt.second / 60
    tst = (minutes + eot + 4 * lon) % 1440
    ha = tst / 4 - 180 if tst / 4 >= 0 else tst / 4 + 180
    lat_r = math.radians(lat)
    cos_zen = (math.sin(lat_r) * math.sin(decl)
               + math.cos(lat_r) * math.cos(decl) * math.cos(math.radians(ha)))
    zen = math.acos(max(-1, min(1, cos_zen)))
    elev = 90 - math.degrees(zen)
    az_den = math.cos(lat_r) * math.sin(zen)
    if abs(az_den) < 1e-9:
        az = 180.0
    else:
        c = ((math.sin(lat_r) * math.cos(zen)) - math.sin(decl)) / az_den
        c = max(-1, min(1, c))
        if ha > 0:
            az = (math.degrees(math.acos(c)) + 180) % 360
        else:
            az = (540 - math.degrees(math.acos(c))) % 360
    return az, elev


def sun_position(dt: datetime, lat: float, lon: float):
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return _solar(dt, lat, lon)


def sunset_track(year: int, month: int, day: int, lat: float, lon: float, min_elev=-0.8, max_elev=6.0):
    """Точки (азимут, высота) солнца в последний час перед закатом.
    Используется, чтобы проверить, видно ли низкое солнце из окна."""
    t = datetime(year, month, day, 10, 0)  # UTC, вечер в Сочи ~ 14-17 UTC
    pts = []
    for i in range(0, 12 * 60, 2):
        az, el = _solar(t + timedelta(minutes=i), lat, lon)
        if az > 180 and min_elev <= el <= max_elev:
            pts.append((az, el))
    return pts


def monthly_sunset_tracks(lat: float, lon: float, year: int = 2026):
    return {m: sunset_track(year, m, 15, lat, lon) for m in range(1, 13)}


def day_track(lat, lon, y, m, d, tz_hours=3, step_min=5):
    """Положение солнца за день по местному времени (Сочи: UTC+3): [(«HH:MM», азимут, высота)],
    плюс время восхода и заката (центр диска на −0.833°)."""
    start = datetime(y, m, d, 0, 0) - timedelta(hours=tz_hours)
    pts, rise, sset = [], None, None
    prev = None
    for i in range(0, 24 * 60, step_min):
        t = start + timedelta(minutes=i)
        az, el = _solar(t, lat, lon)
        loc = t + timedelta(hours=tz_hours)
        if prev is not None:
            if prev[1] < -0.833 <= el and rise is None:
                rise = (loc.strftime("%H:%M"), round(az, 1))
            if prev[1] >= -0.833 > el and sset is None:
                sset = (loc.strftime("%H:%M"), round(prev[0], 1))
        prev = (az, el)
        if el > -8:
            pts.append((loc.strftime("%H:%M"), round(az, 2), round(el, 2)))
    return {"track": pts, "sunrise": rise, "sunset": sset}
