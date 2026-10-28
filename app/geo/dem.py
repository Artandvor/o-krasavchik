"""Чтение рельефа: тайлы Copernicus DEM GLO-30 (GeoTIFF) или подготовленный npz."""
import math
from pathlib import Path

import numpy as np


class DemTile:
    def __init__(self, z, lat_top, lon_left, dlat, dlon, nodata=None):
        self.z = z.astype("float32")
        if nodata is not None:
            self.z[self.z == nodata] = np.nan
        self.lat_top, self.lon_left, self.dlat, self.dlon = lat_top, lon_left, dlat, dlon

    def sample(self, lat, lon):
        r = (self.lat_top - lat) / self.dlat
        c = (lon - self.lon_left) / self.dlon
        out = np.full(lat.shape, np.nan, dtype="float32")
        ok = (r >= 0) & (c >= 0) & (r < self.z.shape[0] - 1) & (c < self.z.shape[1] - 1)
        r, c = r[ok], c[ok]
        r0, c0 = np.floor(r).astype(int), np.floor(c).astype(int)
        fr, fc = r - r0, c - c0
        z = self.z
        out[ok] = (z[r0, c0] * (1 - fr) * (1 - fc) + z[r0 + 1, c0] * fr * (1 - fc)
                   + z[r0, c0 + 1] * (1 - fr) * fc + z[r0 + 1, c0 + 1] * fr * fc)
        return out


def read_geotiff(path: Path) -> DemTile:
    import tifffile
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        z = page.asarray()
        sx, sy = page.tags["ModelPixelScaleTag"].value[:2]
        tie = page.tags["ModelTiepointTag"].value
        i, j, x, y = tie[0], tie[1], tie[3], tie[4]
        pixel_is_point = False
        gk = page.tags.get("GeoKeyDirectoryTag")
        if gk is not None:
            v = list(gk.value)
            for k in range(4, len(v), 4):
                if v[k] == 1025 and v[k + 3] == 2:  # GTRasterTypeGeoKey = RasterPixelIsPoint
                    pixel_is_point = True
        # sample() ждёт координаты ЦЕНТРА пикселя (0,0)
        lon_left = x - i * sx + (0 if pixel_is_point else 0.5 * sx)
        lat_top = y + j * sy - (0 if pixel_is_point else 0.5 * sy)
        nodata = None
        nd = page.tags.get("GDAL_NODATA")
        if nd is not None:
            try:
                nodata = float(str(nd.value).strip("\x00 "))
            except ValueError:
                nodata = None
        return DemTile(z, lat_top, lon_left, sy, sx, nodata)


class Dem:
    """Набор тайлов. Источники по приоритету: GeoTIFF Copernicus, затем dem_*.npz (lats, lons, z)."""

    def __init__(self, raw_dir: Path):
        self.tiles, self.source = [], None
        tifs = sorted(raw_dir.glob("Copernicus_DSM_*.tif"))
        if tifs:
            self.tiles = [read_geotiff(p) for p in tifs]
            self.source = "Copernicus DEM GLO-30 (ESA, AWS Open Data)"
        for p in sorted(raw_dir.glob("dem_*.npz")):
            d = np.load(p, allow_pickle=False)
            lats, lons = d["lats"], d["lons"]
            self.tiles.append(DemTile(d["z"], float(lats[0]), float(lons[0]),
                                      float(abs(lats[1] - lats[0])), float(abs(lons[1] - lons[0]))))
            if not self.source:
                self.source = str(d["source"]) if "source" in d.files else "DEM npz"
        if not self.tiles:
            raise FileNotFoundError("Нет рельефа в data/raw: запустите scripts/fetch_data.py dem")

    def sample(self, lat, lon):
        lat = np.asarray(lat, dtype="float64")
        lon = np.asarray(lon, dtype="float64")
        out = np.full(lat.shape, np.nan, dtype="float32")
        for t in self.tiles:
            v = t.sample(lat, lon)
            m = np.isnan(out) & ~np.isnan(v)
            out[m] = v[m]
        return out


def grid_axes(x0, y0, nx, ny, cell):
    return x0 + np.arange(nx) * cell, y0 + np.arange(ny) * cell


def meters_to_deg(lat_c):
    return 1 / 110_574.0, 1 / (111_320.0 * math.cos(math.radians(lat_c)))
