"""Видимость из окон: море, горы, закат. Лучевой анализ по поверхности
«рельеф (Copernicus DEM, очищенный от застройки) + здания OSM» с Монте-Карло
по неизвестным высотам зданий.

Для каждого фасада и этажа считаем по S сценариям высот:
  * какую долю обзора (±60° от нормали фасада) занимает видимая морская гладь;
  * видна ли гора (рельеф ≥ 600 м дальше 4 км);
  * горизонт по каждому азимуту → видно ли низкое солнце на закате в каждом месяце.
Вероятность = доля сценариев, где ответ «да». Это и есть вычисленная уверенность.
"""
import math

import numpy as np

from .sun import monthly_sunset_tracks

R_EARTH_EFF = 6_371_000 / 0.87  # с учётом рефракции
FOV = 60
AZ_STEP = 2
NEAR_MAX = 4000.0
FAR_MAX = 60000.0
MOUNTAIN_Z = 600.0
EYE = 1.6
FLOOR_H = 3.0

FLOORS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20, 23, 26, 30]


def floors_for(levels):
    top = levels or 9
    fl = [f for f in FLOORS if f <= top]
    if top not in fl:
        fl.append(top)
    return sorted(set(fl))


def _rays(ctx, ox, oy, azs, own_idx):
    d = np.arange(8.0, NEAR_MAX, ctx.cell * 0.9)
    sa, ca = np.sin(np.radians(azs))[:, None], np.cos(np.radians(azs))[:, None]
    X, Y = ox + sa * d, oy + ca * d
    ci = np.round((X - ctx.x0) / ctx.cell).astype(int)
    ri = np.round((Y - ctx.y0) / ctx.cell).astype(int)
    inside = (ci >= 0) & (ri >= 0) & (ci < ctx.nx) & (ri < ctx.ny)
    ci, ri = np.clip(ci, 0, ctx.nx - 1), np.clip(ri, 0, ctx.ny - 1)
    T = np.where(inside, ctx.dtm[ri, ci], -1e4)
    B = np.where(inside, ctx.bid[ri, ci], -1)
    if own_idx is not None:
        B = np.where(B == own_idx, -1, B)
    S = inside & ctx.sea[ri, ci]
    df = np.arange(NEAR_MAX, FAR_MAX, ctx.fcell)
    FXp, FYp = ox + sa * df, oy + ca * df
    fci = np.round((FXp - ctx.fx0) / ctx.fcell).astype(int)
    fri = np.round((FYp - ctx.fy0) / ctx.fcell).astype(int)
    fin = (fci >= 0) & (fri >= 0) & (fci < ctx.far.shape[1]) & (fri < ctx.far.shape[0])
    TF = np.where(fin, ctx.far[np.clip(fri, 0, ctx.far.shape[0] - 1), np.clip(fci, 0, ctx.far.shape[1] - 1)], -1e4)
    return d, T, B, S, df, TF


def facade_view(ctx, facade, floors, own_idx, H, sunset_tracks):
    """Возвращает по каждому этажу вероятности и описатели вида для одного фасада."""
    ox, oy, normal = facade["x"], facade["y"], facade["az"]
    azs = (normal + np.arange(-FOV, FOV + 0.1, AZ_STEP)) % 360
    d, T, B, SEA, df, TF = _rays(ctx, ox, oy, azs, own_idx)
    curv = d ** 2 / (2 * R_EARTH_EFF)
    curvf = df ** 2 / (2 * R_EARTH_EFF)
    g0 = facade.get("ground", float(ctx.ground(ox, oy)))
    centre = np.abs(((azs - normal + 180) % 360) - 180) <= 30
    mtn = (TF >= MOUNTAIN_Z)
    out = {}
    nS = H.shape[0]
    HB = H[:, B]  # S×R×N высоты зданий на лучах
    surf = T[None] + HB
    for f in floors:
        E = g0 + (f - 1) * FLOOR_H + EYE
        ang = (surf - E - curv) / d
        cm = np.maximum.accumulate(ang, axis=2)
        prior = np.concatenate([np.full(cm.shape[:2] + (1,), -np.inf, dtype=cm.dtype), cm[..., :-1]], axis=2)
        sea_ang = (0.3 - E - curv) / d
        vis_sea = SEA[None] & (sea_ang[None] > prior + 1e-5)
        sea_ray = vis_sea.any(axis=2)                            # S×R
        first = np.where(vis_sea.any(axis=2), np.argmax(vis_sea, axis=2), -1)
        near_h = cm[..., -1]                                      # S×R
        fang = (TF - E - curvf) / df
        fcm = np.maximum.accumulate(fang, axis=1)
        fprior = np.concatenate([np.full((fang.shape[0], 1), -np.inf), fcm[:, :-1]], axis=1)
        vis_m = mtn[None] & (fang[None] > np.maximum(fprior[None], near_h[..., None]))
        mtn_ray = vis_m.any(axis=2)
        horizon = np.maximum(near_h, fcm[:, -1][None])            # S×R, тангенс угла горизонта

        n_sea = sea_ray.sum(axis=1)
        p_sea = float(np.mean(n_sea >= 3))                        # ≥ 3 лучей = полоса моря ≥ ~6° обзора
        p_sea_front = float(np.mean((sea_ray & centre[None]).sum(axis=1) >= 3))
        share = float(np.median(sea_ray.mean(axis=1)))
        dists = d[first[first >= 0]]
        p_mtn = float(np.mean(mtn_ray.sum(axis=1) >= 5))         # горы хотя бы на ~10° панорамы, а не в щель
        sunset = []
        sunset_sea = []
        for m in range(1, 13):
            pts = sunset_tracks[m]
            cnt = np.zeros(nS, dtype=int)
            cnt_sea = np.zeros(nS, dtype=int)
            for az, el in pts:
                if el < 0.3:
                    continue
                rel = ((az - normal + 180) % 360) - 180
                if abs(rel) > FOV:
                    continue
                r = int(round((rel + FOV) / AZ_STEP))
                v = math.tan(math.radians(el)) > horizon[:, r]
                cnt += v
                cnt_sea += v & sea_ray[:, r]
            # закат «виден», если солнце над горизонтом видно хотя бы 10 минут из последнего часа
            sunset.append(round(float((cnt >= 5).mean()), 2))
            sunset_sea.append(round(float((cnt_sea >= 5).mean()), 2))
        out[f] = {
            "p_sea": round(p_sea, 2), "p_sea_front": round(p_sea_front, 2),
            "sea_share": round(share, 2),
            "sea_dist_m": int(np.median(dists)) if len(dists) else None,
            "p_mountain": round(p_mtn, 2),
            "sunset": sunset, "sunset_over_sea": sunset_sea,
            "sea_rays": [int(a) for a, v in zip(azs, sea_ray.mean(axis=0) >= 0.5) if v],
            "horizon_deg": [round(math.degrees(math.atan(float(h))), 1) for h in np.median(horizon, axis=0)],
        }
    return {"az": normal, "side": facade["side"], "azs": [round(float(a), 1) for a in azs], "floors": out}


def hotel_views(ctx, hotel, n_samples=48, seed=7):
    H = ctx.sample_heights(n_samples, seed)
    tracks = monthly_sunset_tracks(hotel["lat"], hotel["lon"])
    floors = floors_for(hotel.get("levels"))
    res = [facade_view(ctx, f, floors, hotel.get("building_idx"), H, tracks) for f in hotel["facades"]]
    # оценка полноты застройки вокруг: если в OSM почти нет зданий — видимость завышена
    r = int(200 / ctx.cell)
    ci = int(round((hotel["x"] - ctx.x0) / ctx.cell))
    ri = int(round((hotel["y"] - ctx.y0) / ctx.cell))
    win = ctx.bid[max(ri - r, 0):ri + r, max(ci - r, 0):ci + r]
    built = float((win >= 0).mean()) if win.size else 0.0
    unknown_h = 0.0
    ids = np.unique(win[win >= 0])
    if len(ids):
        unknown_h = float(np.mean([not ctx.buildings[i]["h_src"].startswith("osm") for i in ids]))
    q = 0.92  # модельная погрешность: DEM 30 м, деревья и рекламные щиты не учитываются
    notes = ["деревья не учитываются (их нет в данных) — вид может быть хуже расчётного"]
    if not hotel.get("footprint_known"):
        q *= 0.7
        notes.append("контур здания отеля не найден на открытой карте — стороны условные")
    if built < 0.04:
        q *= 0.8
        notes.append(f"вокруг мало зданий на открытой карте ({built:.0%} площади) — возможно, застройка не нанесена")
    if hotel.get("levels_src") == "estimate":
        notes.append(f"этажность на карте не указана — оценена как {hotel.get('levels')} эт. по высоте и типу здания")
    return {"facades": res, "floors": floors, "quality": round(q, 2), "built_share": round(built, 3),
            "unknown_height_share": round(unknown_h, 2), "n_samples": n_samples, "notes": notes}


def panorama(ctx, hotel, facade, floor, step=1.0):
    """Профиль вида из окна для рисования: по каждому азимуту в секторе ±60° —
    угол ближних препятствий (здания, рельеф до 4 км), угол дальнего рельефа (горы),
    видно ли море и на каком расстоянии. Высоты зданий — середина априорного диапазона."""
    H = ((ctx.h_lo + ctx.h_hi) / 2)[None, :]
    H = np.concatenate([H, np.zeros((1, 1), dtype=H.dtype)], axis=1)
    normal = facade["az"]
    azs = (normal + np.arange(-FOV, FOV + 0.1, step)) % 360
    d, T, B, SEA, df, TF = _rays(ctx, facade["x"], facade["y"], azs, hotel.get("building_idx"))
    curv = d ** 2 / (2 * R_EARTH_EFF)
    curvf = df ** 2 / (2 * R_EARTH_EFF)
    g0 = facade.get("ground", float(ctx.ground(facade["x"], facade["y"])))
    E = g0 + (floor - 1) * FLOOR_H + EYE
    surf = T + H[0, B]
    ang = (surf - E - curv) / d
    cm = np.maximum.accumulate(ang, axis=1)
    prior = np.concatenate([np.full((len(azs), 1), -np.inf), cm[:, :-1]], axis=1)
    vis_sea = SEA & ((0.3 - E - curv) / d > prior + 1e-5)
    sea_any = vis_sea.any(axis=1)
    first = np.where(sea_any, np.argmax(vis_sea, axis=1), -1)
    fang = (TF - E - curvf) / df
    near = np.degrees(np.arctan(np.maximum(cm[:, -1], -0.2)))
    far = np.degrees(np.arctan(fang.max(axis=1)))
    built = (B >= 0) & (ang >= cm[:, -1:] - 1e-6)  # что именно образует ближний горизонт: здание или рельеф
    return {
        "side": facade["side"], "az": normal, "floor": floor, "eye_m": round(E, 1),
        "azs": [round(float(a), 1) for a in azs],
        "near": [round(float(v), 2) for v in near],
        "far": [round(float(v), 2) for v in far],
        "sea": [bool(v) for v in sea_any],
        "sea_d": [int(d[i]) if i >= 0 else None for i in first],
        "near_is_building": [bool(v) for v in built.any(axis=1)],
    }
