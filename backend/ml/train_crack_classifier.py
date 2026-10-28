"""Train a binary concrete crack / no-crack CNN and export it as an installable ONNX model.

Methodological starting point: the binary CNN crack-classification approach described in
"Applicability of IoT and AIML in Monitoring the Health of Mega Civil Structures"
(40,000-image concrete dataset). Results reported in that paper belong to that paper's
model and are NOT attributed to this implementation: this script measures and records
its own metrics on its own held-out test split.

Dataset: any verified, appropriately licensed folder with one sub-folder of crack images
and one of non-crack images, e.g. the "Concrete Crack Images for Classification" dataset
(Özgenel, Mendeley Data, CC BY 4.0, layout Positive/ and Negative/). You must record its
provenance (name, version, URL, licence, checksum) via the CLI flags below.

Pipeline:
  1. Stratified split 70/15/15 (fixed seed) → files written to <out>/splits/*.txt.
  2. Train a small CNN (3×[conv-BN-ReLU-pool] + GAP + FC) on the train split.
  3. Choose the decision threshold on the VALIDATION split: best F1 subject to
     recall ≥ --min-recall (false negatives are the costliest error).
  4. Export ONNX (softmax output) and write model_card.json.
  5. Evaluate on the untouched TEST split with ml/evaluate.py (same inference code as
     the backend) and record precision, recall, F1, confusion matrix and latency.

Example:
  python -m ml.train_crack_classifier --data-dir /data/concrete --out model_store/crack-cnn-v1 \
     --dataset-name "Concrete Crack Images for Classification" --dataset-version 2 \
     --dataset-url https://data.mendeley.com/datasets/5y9wdsg2zt/2 --dataset-license "CC BY 4.0"

Requires: torch (CPU is fine), onnx, onnxruntime, opencv-python-headless, numpy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ml.evaluate import evaluate  # noqa: E402
from ml.metrics import binary_metrics, select_threshold  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]


def gather(data_dir: Path, pos: str, neg: str) -> list[tuple[str, int]]:
    items = [(str(p.relative_to(data_dir)), 1) for p in sorted((data_dir / pos).rglob("*")) if p.suffix.lower() in IMG_EXT]
    items += [(str(p.relative_to(data_dir)), 0) for p in sorted((data_dir / neg).rglob("*")) if p.suffix.lower() in IMG_EXT]
    return items


def stratified_split(items, seed: int, fractions=(0.7, 0.15, 0.15)):
    rng = random.Random(seed)
    splits = {"train": [], "val": [], "test": []}
    for label in (0, 1):
        group = [it for it in items if it[1] == label]
        rng.shuffle(group)
        n = len(group)
        a, b = int(n * fractions[0]), int(n * (fractions[0] + fractions[1]))
        splits["train"] += group[:a]
        splits["val"] += group[a:b]
        splits["test"] += group[b:]
    for v in splits.values():
        rng.shuffle(v)
    return splits


def load(data_dir: Path, rel: str, size: int) -> np.ndarray:
    bgr = cv2.imread(str(data_dir / rel), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"unreadable image {rel}")
    rgb = cv2.cvtColor(cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return ((rgb - MEAN) / STD).transpose(2, 0, 1).astype(np.float32)


def build_model(torch):
    nn = torch.nn

    def block(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True), nn.MaxPool2d(2))

    return nn.Sequential(block(3, 16), block(16, 32), block(32, 64), nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.2), nn.Linear(64, 2))


def predict_scores(torch, model, data_dir, items, size, batch=128) -> np.ndarray:
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(items), batch):
            x = torch.from_numpy(np.stack([load(data_dir, r, size) for r, _ in items[i : i + batch]]))
            out.append(torch.softmax(model(x), dim=1)[:, 1].numpy())
    return np.concatenate(out) if out else np.array([])


def sha256_of_list(items) -> str:
    h = hashlib.sha256()
    for rel, label in sorted(items):
        h.update(f"{label}\t{rel}\n".encode())
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--positive-dir", default="Positive")
    ap.add_argument("--negative-dir", default="Negative")
    ap.add_argument("--size", type=int, default=128)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-recall", type=float, default=0.95)
    ap.add_argument("--limit", type=int, default=0, help="Use at most N images per class (quick experiments)")
    ap.add_argument("--model-id", default="crack-cnn")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--dataset-name", required=True)
    ap.add_argument("--dataset-version", default="unspecified")
    ap.add_argument("--dataset-url", default="unspecified")
    ap.add_argument("--dataset-license", required=True)
    ap.add_argument("--dataset-notes", default="")
    args = ap.parse_args()

    import torch

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    items = gather(args.data_dir, args.positive_dir, args.negative_dir)
    if args.limit:
        items = [i for i in items if i[1] == 1][: args.limit] + [i for i in items if i[1] == 0][: args.limit]
    if len({lbl for _, lbl in items}) < 2:
        raise SystemExit("Both positive and negative images are required.")
    splits = stratified_split(items, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "splits").mkdir(exist_ok=True)
    for name, its in splits.items():
        (args.out / "splits" / f"{name}.txt").write_text("".join(f"{lbl}\t{rel}\n" for rel, lbl in its))
    print({k: len(v) for k, v in splits.items()})

    model = build_model(torch)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = torch.nn.CrossEntropyLoss()
    train = splits["train"]
    history = []
    for epoch in range(args.epochs):
        model.train()
        random.shuffle(train)
        t0, total, n = time.time(), 0.0, 0
        for i in range(0, len(train), args.batch):
            chunk = train[i : i + args.batch]
            x = np.stack([load(args.data_dir, r, args.size) for r, _ in chunk])
            if random.random() < 0.5:
                x = x[:, :, :, ::-1].copy()  # horizontal flip augmentation
            xb, yb = torch.from_numpy(x), torch.tensor([lbl for _, lbl in chunk])
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
            total += float(loss) * len(chunk)
            n += len(chunk)
        val_scores = predict_scores(torch, model, args.data_dir, splits["val"], args.size)
        val_m = binary_metrics([l for _, l in splits["val"]], val_scores, 0.5)
        history.append({"epoch": epoch + 1, "train_loss": round(total / n, 4), "val_f1@0.5": val_m["f1"], "val_recall@0.5": val_m["recall"], "seconds": round(time.time() - t0, 1)})
        print(history[-1])

    val_y = [l for _, l in splits["val"]]
    val_scores = predict_scores(torch, model, args.data_dir, splits["val"], args.size)
    threshold = select_threshold(val_y, val_scores, args.min_recall)
    val_metrics = binary_metrics(val_y, val_scores, threshold)

    export = torch.nn.Sequential(model, torch.nn.Softmax(dim=1)).eval()
    torch.onnx.export(export, torch.zeros(1, 3, args.size, args.size), str(args.out / "model.onnx"), input_names=["input"],
                      output_names=["probabilities"], dynamic_axes={"input": {0: "batch"}, "probabilities": {0: "batch"}}, opset_version=17)

    card = {
        "id": args.model_id, "name": "Concrete crack / no-crack CNN", "version": args.version, "task": "classification",
        "framework": "onnx", "file": "model.onnx", "labels": ["no_crack", "crack"], "positive_label": "crack",
        "category_map": {"crack": "suspected_crack"}, "output": "softmax", "threshold": round(float(threshold), 6),
        "input": {"size": [args.size, args.size], "color": "rgb", "layout": "NCHW", "scale": 1 / 255, "mean": MEAN, "std": STD},
        "dataset": {"name": args.dataset_name, "version": args.dataset_version, "url": args.dataset_url, "license": args.dataset_license,
                    "notes": args.dataset_notes, "n_images": len(items), "split": {k: len(v) for k, v in splits.items()},
                    "split_seed": args.seed, "file_list_sha256": sha256_of_list(items)},
        "training": {"epochs": args.epochs, "batch": args.batch, "lr": args.lr, "augmentation": ["horizontal_flip"], "history": history,
                     "trained_at": dt.datetime.now(dt.timezone.utc).isoformat(), "script": "ml/train_crack_classifier.py"},
        "threshold_selection": {"split": "val", "rule": f"max F1 subject to recall >= {args.min_recall}", "val_metrics": val_metrics},
        "intended_use": "Screening aid that flags images likely to contain crack-like features for engineering review. "
                        "Whole-image classification: no localisation, no width/length measurement, no severity.",
        "limitations": ["Performance outside the training distribution (lighting, surfaces, camera) is unknown.",
                        "Confidence is not a measure of structural severity."],
        "metrics": None,
    }
    (args.out / "model_card.json").write_text(json.dumps(card, indent=2))
    test_items = [(args.data_dir / rel, lbl) for rel, lbl in splits["test"]]
    test_metrics = evaluate(args.out, test_items)
    test_metrics.update({"split": "test", "evaluated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "evaluation_tool": "ml/evaluate.py"})
    card["metrics"] = test_metrics
    (args.out / "model_card.json").write_text(json.dumps(card, indent=2))
    print(json.dumps(test_metrics, indent=2))
    print(f"Model written to {args.out}. Copy the folder into SS_MODEL_DIR and use 'Rescan models'.")


if __name__ == "__main__":
    main()
