"""Evaluate an installed ONNX classifier on a labelled image folder and record the
results in its model card. Uses exactly the same inference code as the backend.

Usage:
  python -m ml.evaluate --model-dir model_store/crack-cnn \
      --data-dir /data/concrete_cracks --positive-dir Positive --negative-dir Negative \
      [--file-list model_store/crack-cnn/test_split.txt] [--write-card]

Only run this on data the model was NOT trained or tuned on.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.inference.onnx_classifier import OnnxImageClassifier  # noqa: E402
from ml.metrics import binary_metrics, latency_summary  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def list_images(data_dir: Path, pos: str, neg: str, file_list: Path | None):
    if file_list:
        items = []
        for line in file_list.read_text().splitlines():
            if not line.strip():
                continue
            label, rel = line.split("\t", 1)
            items.append((data_dir / rel, int(label)))
        return items
    out = [(p, 1) for p in sorted((data_dir / pos).rglob("*")) if p.suffix.lower() in IMG_EXT]
    out += [(p, 0) for p in sorted((data_dir / neg).rglob("*")) if p.suffix.lower() in IMG_EXT]
    return out


def evaluate(model_dir: Path, items, threshold: float | None = None) -> dict:
    card = json.loads((model_dir / "model_card.json").read_text())
    clf = OnnxImageClassifier(card, model_dir / card["file"])
    pos_label = clf.positive_labels[0]
    y, scores, ms = [], [], []
    for path, label in items:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        r = clf.predict(bgr)
        y.append(label)
        scores.append(r.raw["probabilities"][pos_label])
        ms.append(r.inference_ms)
    if not y:
        raise SystemExit("No readable images found.")
    m = binary_metrics(y, scores, threshold if threshold is not None else clf.threshold)
    m["inference_time"] = latency_summary(ms)
    m["positives"], m["negatives"] = int(sum(y)), int(len(y) - sum(y))
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--positive-dir", default="Positive")
    ap.add_argument("--negative-dir", default="Negative")
    ap.add_argument("--file-list", type=Path)
    ap.add_argument("--split-name", default="test")
    ap.add_argument("--write-card", action="store_true")
    args = ap.parse_args()
    items = list_images(args.data_dir, args.positive_dir, args.negative_dir, args.file_list)
    m = evaluate(args.model_dir, items)
    m.update({"split": args.split_name, "evaluated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "evaluation_tool": "ml/evaluate.py"})
    print(json.dumps(m, indent=2))
    if args.write_card:
        card_path = args.model_dir / "model_card.json"
        card = json.loads(card_path.read_text())
        card["metrics"] = m
        card_path.write_text(json.dumps(card, indent=2))
        print(f"metrics written to {card_path}")


if __name__ == "__main__":
    main()
