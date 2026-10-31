"""One-command crack-model setup on your own laptop (needs internet once, for the dataset).

1. Download "Concrete Crack Images for Classification" (Özgenel, Mendeley Data, CC BY 4.0):
   https://data.mendeley.com/datasets/5y9wdsg2zt/2  → extract it so you have …/Positive and …/Negative.
2. Install training extras:   pip install torch onnx
3. Run (backend running on :8000):
       python -m ml.setup_crack_model --data-dir "C:/datasets/concrete-cracks"
   It trains (a few minutes to ~1 h on a laptop CPU depending on --limit), evaluates on a held-out
   test split, and installs the model into the running backend (Settings → AI crack-detection model).

The recorded precision/recall/F1 come from YOUR test split — check them before trusting detections.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--out", type=Path, default=ROOT / "model_store_build" / "crack-cnn-metu")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--size", type=int, default=96)
    ap.add_argument("--limit", type=int, default=6000, help="images per class to use (0 = all 20,000)")
    args = ap.parse_args()
    if not (args.data_dir / "Positive").is_dir() or not (args.data_dir / "Negative").is_dir():
        raise SystemExit(f"{args.data_dir} must contain the extracted 'Positive' and 'Negative' folders.")
    cmd = [sys.executable, "-m", "ml.train_crack_classifier", "--data-dir", str(args.data_dir), "--out", str(args.out),
           "--epochs", str(args.epochs), "--size", str(args.size), "--limit", str(args.limit), "--model-id", "crack-cnn-metu",
           "--dataset-name", "Concrete Crack Images for Classification (Özgenel)", "--dataset-version", "2",
           "--dataset-url", "https://data.mendeley.com/datasets/5y9wdsg2zt/2", "--dataset-license", "CC BY 4.0"]
    print("Training:", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)
    url = args.api.rstrip("/") + "/api/v1/models/upload"
    res = post_multipart_two(url, args.out / "model.onnx", args.out / "model_card.json")
    print("Installed:", res)


def post_multipart_two(url: str, onnx: Path, card: Path) -> dict:
    """Upload both files in one multipart request."""
    import json
    import urllib.request
    import uuid

    b = uuid.uuid4().hex
    parts = []
    for name, path, ctype in (("onnx_file", onnx, "application/octet-stream"), ("card_file", card, "application/json")):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{path.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                     + path.read_bytes() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    main()
