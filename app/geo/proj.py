"""Локальная метрическая проекция (equirectangular) вокруг центра региона.
На масштабе ~20 км ошибка < 0.1%, этого достаточно для видимости и маршрутов."""
import math

M_PER_DEG_LAT = 110_574.0


class LocalProj:
    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.ky = M_PER_DEG_LAT

    def to_xy(self, lat, lon):
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky

    def to_ll(self, x, y):
        return self.lat0 + y / self.ky, self.lon0 + x / self.kx

    def to_dict(self):
        return {"lat0": self.lat0, "lon0": self.lon0}

    @classmethod
    def from_dict(cls, d):
        return cls(d["lat0"], d["lon0"])


def bbox_center(b):
    s, w, n, e = b
    return (s + n) / 2, (w + e) / 2


def pad_bbox(b, pad_m):
    s, w, n, e = b
    lat_c = (s + n) / 2
    dlat = pad_m / M_PER_DEG_LAT
    dlon = pad_m / (111_320.0 * math.cos(math.radians(lat_c)))
    return [s - dlat, w - dlon, n + dlat, e + dlon]


AZ_NAMES = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]


def az_name(az: float) -> str:
    return AZ_NAMES[int(((az % 360) + 22.5) // 45) % 8]


# Стороны света словами — для текстов гостю (короткие «З», «Ю» читаются как цифры)
SIDE_WORD = {"С": "север", "СВ": "северо-восток", "В": "восток", "ЮВ": "юго-восток", "Ю": "юг",
             "ЮЗ": "юго-запад", "З": "запад", "СЗ": "северо-запад"}


def side_word(code: str) -> str:
    return SIDE_WORD.get(code, code)
