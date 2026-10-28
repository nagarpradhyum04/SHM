"""Tests for the model-evaluation tooling (not for any trained model's quality)."""
import json

import numpy as np

from ml.metrics import binary_metrics, select_threshold
from tests.conftest import build_test_onnx_model


def test_binary_metrics_confusion_matrix():
    y = [1, 1, 1, 0, 0, 0, 0, 1]
    s = [0.9, 0.8, 0.3, 0.1, 0.6, 0.2, 0.4, 0.7]
    m = binary_metrics(y, s, 0.5)
    assert m["confusion_matrix"]["tp"] == 3 and m["confusion_matrix"]["fn"] == 1
    assert m["confusion_matrix"]["fp"] == 1 and m["confusion_matrix"]["tn"] == 3
    assert m["precision"] == 0.75 and m["recall"] == 0.75 and m["f1"] == 0.75 and m["false_negative_rate"] == 0.25


def test_threshold_selection_prioritises_recall():
    y = [1, 1, 1, 1, 0, 0, 0, 0]
    s = [0.9, 0.8, 0.35, 0.3, 0.32, 0.2, 0.1, 0.05]
    t = select_threshold(y, s, min_recall=1.0)
    assert binary_metrics(y, s, t)["recall"] == 1.0
    assert t <= 0.3


def test_evaluate_uses_backend_inference_and_writes_metrics(tmp_path):
    import cv2

    from ml.evaluate import evaluate

    model_dir = build_test_onnx_model(tmp_path / "m")
    for lbl, val in (("Positive", 10), ("Negative", 245)):
        (tmp_path / "data" / lbl).mkdir(parents=True)
        for i in range(3):
            cv2.imwrite(str(tmp_path / "data" / lbl / f"{i}.png"), np.full((40, 40, 3), val + i, np.uint8))
    items = [(p, 1) for p in (tmp_path / "data" / "Positive").iterdir()] + [(p, 0) for p in (tmp_path / "data" / "Negative").iterdir()]
    m = evaluate(model_dir, items)
    assert m["positives"] == 3 and m["negatives"] == 3
    assert m["recall"] == 1.0 and m["precision"] == 1.0  # trivially separable synthetic fixture
    assert m["inference_time"]["n"] == 6
    json.dumps(m)
