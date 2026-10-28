"""Загружает подготовленный гео-контекст региона один раз на процесс."""
import json
import pickle

import numpy as np
from scipy.spatial import cKDTree

from ..config import PROC
from .proj import LocalProj


class GeoContext:
    def __init__(self, proc_dir=PROC):
        g = np.load(proc_dir / "grid.npz")
        self.dtm = g["dtm"].astype("float32")
        self.bid = g["bid"].astype("int32")
        self.sea = g["sea"].astype(bool)
        self.bump = g["bump"].astype("float32")
        self.x0, self.y0, self.cell = float(g["x0"]), float(g["y0"]), float(g["cell"])
        self.ny, self.nx = self.dtm.shape
        f = np.load(proc_dir / "far.npz")
        self.far = f["z"].astype("float32")
        self.fx0, self.fy0, self.fcell = float(f["x0"]), float(f["y0"]), float(f["cell"])
        with open(proc_dir / "geo.pkl", "rb") as fh:
            geo = pickle.load(fh)
        self.__dict__.update({k: v for k, v in geo.items() if k != "proj"})
        self.proj = LocalProj.from_dict(geo["proj"])
        self.hotels = json.loads((proc_dir / "hotels.json").read_text(encoding="utf-8"))
        self.hotel_by_id = {h["id"]: h for h in self.hotels}
        G = self.graph
        self.node_ids = list(G.nodes)
        self.node_xy = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in self.node_ids]) \
            if self.node_ids else np.zeros((0, 2))
        self.node_tree = cKDTree(self.node_xy) if len(self.node_ids) else None
        self.h_lo = np.array([b["h_lo"] for b in self.buildings], dtype="float32")
        self.h_hi = np.array([b["h_hi"] for b in self.buildings], dtype="float32")
        self.extra_buildings = []  # «что если построят дом» — добавляется на лету

    # ------------------------------------------------------------------
    def ground(self, x, y):
        ci = np.clip(np.round((np.asarray(x) - self.x0) / self.cell).astype(int), 0, self.nx - 1)
        ri = np.clip(np.round((np.asarray(y) - self.y0) / self.cell).astype(int), 0, self.ny - 1)
        return self.dtm[ri, ci]

    def sample_heights(self, n_samples: int, seed: int = 7):
        """Матрица S×(Nb+1) высот зданий. Последний столбец = 0 (клетка без здания, bid=-1).
        Неизвестные высоты разыгрываются равномерно в априорном диапазоне — так неопределённость
        данных честно переходит в неопределённость ответа."""
        rng = np.random.default_rng(seed)
        u = rng.random((n_samples, len(self.h_lo)), dtype="float32")
        H = self.h_lo + u * (self.h_hi - self.h_lo)
        return np.concatenate([H, np.zeros((n_samples, 1), dtype="float32")], axis=1)

    def nearest_node(self, x, y, max_d=300):
        if self.node_tree is None:
            return None
        d, j = self.node_tree.query([x, y])
        return self.node_ids[int(j)] if d <= max_d else None

    def to_ll(self, x, y):
        return self.proj.to_ll(x, y)

    def add_building(self, poly_xy, height):
        """Актуализация: рядом построили дом. Растеризуем его в сетку с известной высотой."""
        import shapely
        from shapely.geometry import Polygon
        p = Polygon(poly_xy)
        idx = len(self.h_lo)
        self.h_lo = np.append(self.h_lo, np.float32(height))
        self.h_hi = np.append(self.h_hi, np.float32(height))
        x1, y1, x2, y2 = p.bounds
        c1, c2 = max(int((x1 - self.x0) // self.cell), 0), min(int((x2 - self.x0) // self.cell) + 1, self.nx - 1)
        r1, r2 = max(int((y1 - self.y0) // self.cell), 0), min(int((y2 - self.y0) // self.cell) + 1, self.ny - 1)
        gx = self.x0 + np.arange(c1, c2 + 1) * self.cell
        gy = self.y0 + np.arange(r1, r2 + 1) * self.cell
        SX, SY = np.meshgrid(gx, gy)
        m = shapely.contains_xy(p, SX, SY)
        sub = self.bid[r1:r2 + 1, c1:c2 + 1]
        sub[m] = idx
        self.buildings.append({"osm": "user/new", "tags": {"building": "construction"}, "area": p.area,
                               "h_lo": height, "h_hi": height, "h_src": "user:what-if"})
        self.extra_buildings.append({"poly": poly_xy, "height": height, "idx": idx})
        return idx


_ctx = None


def get_ctx():
    global _ctx
    if _ctx is None:
        _ctx = GeoContext()
    return _ctx


def reset_ctx():
    global _ctx
    _ctx = None
