# Crack-classification model pipeline

No trained model is shipped with StructuraSense AI. Until one is installed, image inspections are
stored with status `model_unavailable` and **no prediction is generated**.

## Install a model

A model is a folder in `SS_MODEL_DIR` (default `backend/model_store/`) containing:

* `model_card.json` – id, version, task, framework (`onnx`), file, labels, positive label,
  `category_map` (e.g. `{"crack": "suspected_crack"}`), output kind (`softmax`/`logits`/`sigmoid`),
  decision `threshold`, `input` preprocessing (size, colour order, layout, scale, mean, std),
  `dataset` provenance and evaluated `metrics`;
* the model file (`model.onnx`).

Then use **Settings → Model registry → Rescan models** (or `POST /api/v1/models/reload`).

## Train (PyTorch → ONNX)

```bash
cd backend
pip install torch onnx   # in addition to requirements.txt
python -m ml.train_crack_classifier --data-dir /data/concrete --out model_store/crack-cnn-v1 \
  --dataset-name "Concrete Crack Images for Classification" --dataset-version 2 \
  --dataset-url https://data.mendeley.com/datasets/5y9wdsg2zt/2 --dataset-license "CC BY 4.0"
```

The script splits the data 70/15/15 (stratified, fixed seed, split lists saved), trains a small CNN,
selects the threshold on the validation split (best F1 with recall ≥ `--min-recall`, default 0.95, to
limit false negatives), exports ONNX, and evaluates the untouched test split with the backend's own
inference code, writing precision, recall, F1, false-negative rate, confusion matrix and latency into
the model card.

The research paper "Applicability of IoT and AIML in Monitoring the Health of Mega Civil Structures"
motivates the binary CNN approach and describes a 40,000-image dataset. Its reported results apply to
its own model only and are not claimed for models produced here.

## Re-evaluate an installed model

```bash
python -m ml.evaluate --model-dir model_store/crack-cnn-v1 --data-dir /data/concrete \
  --file-list model_store/crack-cnn-v1/splits/test.txt --write-card
```

## Verification status in this repository

* `ml/metrics.py` and `ml/evaluate.py` are covered by `tests/test_ml_pipeline.py`.
* See the root README "Test results" section for whether the training script was smoke-tested in the
  development environment. Real-dataset training has **not** been performed here (the dataset host
  was not reachable from the build environment), so no real metrics exist.
