"""Binary classification metrics shared by training and evaluation (numpy only).

All metrics are computed on a held-out split. False negatives (missed defects)
are reported explicitly because they are the costliest error for inspection.
"""
from __future__ import annotations

import numpy as np


def confusion(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true).astype(bool)
    y_pred = np.asarray(y_pred).astype(bool)
    return {
        "tp": int(np.sum(y_true & y_pred)),
        "fp": int(np.sum(~y_true & y_pred)),
        "tn": int(np.sum(~y_true & ~y_pred)),
        "fn": int(np.sum(y_true & ~y_pred)),
    }


def binary_metrics(y_true, scores, threshold: float) -> dict:
    scores = np.asarray(scores, dtype=float)
    cm = confusion(y_true, scores >= threshold)
    tp, fp, tn, fn = cm["tp"], cm["fp"], cm["tn"], cm["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    n = tp + fp + tn + fn
    return {
        "threshold": threshold,
        "n": n,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round((tp + tn) / n, 4) if n else 0.0,
        "false_negative_rate": round(fn / (tp + fn), 4) if tp + fn else 0.0,
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "confusion_matrix": {"labels": ["negative", "positive"], "rows_true_cols_pred": [[tn, fp], [fn, tp]], **cm},
    }


def select_threshold(y_true, scores, min_recall: float = 0.95) -> float:
    """Highest-F1 threshold among those achieving at least ``min_recall`` on the validation split.
    Falls back to the threshold with maximum recall if none reach the target."""
    scores = np.asarray(scores, dtype=float)
    candidates = np.unique(np.concatenate([scores, [0.5]]))
    best, best_f1, best_recall_t, best_recall = 0.5, -1.0, 0.5, -1.0
    for t in candidates:
        m = binary_metrics(y_true, scores, float(t))
        if m["recall"] > best_recall or (m["recall"] == best_recall and t > best_recall_t):
            best_recall, best_recall_t = m["recall"], float(t)
        if m["recall"] >= min_recall and m["f1"] > best_f1:
            best, best_f1 = float(t), m["f1"]
    return best if best_f1 >= 0 else best_recall_t


def latency_summary(ms: list[float]) -> dict:
    a = np.asarray(ms, dtype=float)
    return {"mean_ms": round(float(a.mean()), 3), "p50_ms": round(float(np.percentile(a, 50)), 3),
            "p95_ms": round(float(np.percentile(a, 95)), 3), "n": int(a.size)}
