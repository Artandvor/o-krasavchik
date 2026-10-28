"""Метрики качества: покрытие, доля вопросов отельеру, точность и калибровка уверенности
по ручной разметке (таблица labels / файл data/labels.csv)."""
import csv
import json
from collections import defaultdict

from . import truth
from .config import DATA
from .registry import get_registry
from .store import get_store


def load_labels_csv(store):
    p = DATA / "labels.csv"
    if not p.exists():
        return 0
    n = 0
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("value"):
                continue
            v = row["value"].strip().lower()
            val = True if v in ("1", "да", "true", "yes") else False if v in ("0", "нет", "false", "no") else v
            store.set_label(row["hotel_id"], row["key"], val, row.get("labeler", "csv"), row.get("evidence", ""))
            n += 1
    store.commit()
    return n


def _match(spec, pred, label):
    if spec["type"] == "number":
        try:
            return abs(float(pred) - float(label)) <= max(2.0, 0.3 * float(label))
        except (TypeError, ValueError):
            return False
    if isinstance(label, str) and isinstance(pred, str):
        return pred.strip().lower().startswith(label.strip().lower()[:4])
    return pred == label


def compute():
    store, reg = get_store(), get_registry()
    hotels = store.hotels()
    H = len(hotels)
    cov = {}
    per_hotel_q = defaultdict(int)
    for q in store.questions(status=None):
        per_hotel_q[q["hotel_id"]] += 1
    for s in reg.all():
        if s["scope"] == "region":
            r = truth.resolve(s, store.facts("_region", s["key"]))
            cov[s["key"]] = {"title": s["title"], "any": 1.0 if r else 0.0, "confident": 1.0 if r and r["confidence"] >= 0.7 else 0.0,
                             "auto": 1.0 if r else 0.0, "hotelier": 0.0, "group": s["group"]}
            continue
        any_ = conf_ = auto_ = hot_ = 0
        for h in hotels:
            fs = store.facts(h["id"], s["key"])
            r = truth.resolve(s, fs, store, h["id"], create=False)
            if r:
                any_ += 1
                conf_ += r["confidence"] >= 0.7
            auto_ += any(f["source_type"] in ("geo", "osm_tag", "open_api") for f in fs)
            hot_ += any(f["source_type"] == "hotelier" for f in fs)
        cov[s["key"]] = {"title": s["title"], "group": s["group"], "any": round(any_ / max(H, 1), 3),
                         "confident": round(conf_ / max(H, 1), 3), "auto": round(auto_ / max(H, 1), 3),
                         "hotelier": round(hot_ / max(H, 1), 3)}
    qs = store.questions(status=None)
    answered = [q for q in qs if q["status"] == "answered"]
    parsed_ok = [q for q in answered if q["parsed"] and q["parsed"].get("value") is not None]
    conflicts_all = store.db.execute("SELECT status, COUNT(*) c FROM conflicts GROUP BY status").fetchall()

    # точность по разметке + калибровка (насколько «80% уверенности» правда означает 80%)
    load_labels_csv(store)
    labels = store.labels()
    acc = defaultdict(lambda: {"n": 0, "correct": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0, "no_pred": 0})
    calib = defaultdict(lambda: [0, 0])
    brier, nb = 0.0, 0
    rows = []
    for lb in labels:
        s = reg.get(lb["key"])
        if not s:
            continue
        hid = "_region" if s["scope"] == "region" else lb["hotel_id"]
        r = truth.resolve(s, [f for f in store.facts(hid, lb["key"]) if f["source_type"] != "human"])
        a = acc[lb["key"]]
        a["n"] += 1
        if not r:
            a["no_pred"] += 1
            continue
        ok = _match(s, r["value"], lb["value"])
        a["correct"] += ok
        if isinstance(lb["value"], bool) and isinstance(r["value"], bool):
            a["tp" if r["value"] and lb["value"] else "fp" if r["value"] else "fn" if lb["value"] else "tn"] += 1
            p_true = r["confidence"] if r["value"] else 1 - r["confidence"]
            brier += (p_true - (1.0 if lb["value"] else 0.0)) ** 2
            nb += 1
        b = min(int(r["confidence"] * 10), 9)
        calib[b][0] += 1
        calib[b][1] += ok
        rows.append({"hotel_id": lb["hotel_id"], "key": lb["key"], "label": lb["value"], "pred": r["value"],
                     "confidence": r["confidence"], "ok": ok, "evidence": lb.get("evidence")})
    accuracy = {}
    for k, a in acc.items():
        pred = a["n"] - a["no_pred"]
        prec = a["tp"] / (a["tp"] + a["fp"]) if a["tp"] + a["fp"] else None
        rec = a["tp"] / (a["tp"] + a["fn"]) if a["tp"] + a["fn"] else None
        accuracy[k] = {"title": reg.get(k)["title"], "n": a["n"], "accuracy": round(a["correct"] / pred, 3) if pred else None,
                       "precision": round(prec, 3) if prec is not None else None,
                       "recall": round(rec, 3) if rec is not None else None, "coverage": round(pred / a["n"], 3) if a["n"] else None}
    calibration = [{"bin": f"{b / 10:.1f}–{(b + 1) / 10:.1f}", "n": n, "accuracy": round(c / n, 3)}
                   for b, (n, c) in sorted(calib.items()) if n]
    return {
        "hotels": H,
        "characteristics": len(reg.all()),
        "coverage": cov,
        "avg_confident_coverage": round(sum(c["confident"] for c in cov.values()) / max(len(cov), 1), 3),
        "questions": {"total": len(qs), "per_hotel": round(len(qs) / max(H, 1), 2),
                      "hotels_asked": round(len(per_hotel_q) / max(H, 1), 3),
                      "answered": len(answered), "parsed_ok": round(len(parsed_ok) / max(len(answered), 1), 3)},
        "conflicts": {r["status"]: r["c"] for r in conflicts_all},
        "labels": {"n": len(labels), "accuracy": accuracy, "calibration": calibration,
                   "brier": round(brier / nb, 3) if nb else None, "rows": rows[:300]},
    }


if __name__ == "__main__":
    print(json.dumps(compute(), ensure_ascii=False, indent=1))
