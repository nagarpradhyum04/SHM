"""One-command crack-model setup on your own laptop (needs internet once, for the dataset).

    python -m ml.setup_crack_model                       # download dataset, train, evaluate, install
    python -m ml.setup_crack_model --data-dir <zip|folder> # use a dataset you downloaded yourself

Dataset: "Concrete Crack Images for Classification" (Özgenel, Mendeley Data v2, CC BY 4.0,
https://data.mendeley.com/datasets/5y9wdsg2zt/2): 20,000 + 20,000 227×227 concrete-surface images.
Steps: install torch + onnx if missing → download (≈235 MB) → extract (.zip and the .rar inside it) →
train a small CNN → evaluate on a held-out test split → install into the running backend.
The same steps run from Settings → AI model → "Train on this computer".

The recorded precision/recall/F1 come from YOUR test split of that dataset — check detections on your own
camera images before trusting them.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_PAGE = "https://data.mendeley.com/datasets/5y9wdsg2zt/2"
DOWNLOAD_URLS = [
    "https://data.mendeley.com/public-api/zip/5y9wdsg2zt/download/2",
]
FILES_API = "https://data.mendeley.com/public-api/datasets/5y9wdsg2zt/files?folder_id=root&version=2"
DEFAULT_DOWNLOAD_DIR = ROOT / "data" / "datasets" / "concrete-crack-images"
MODEL_ID = "crack-cnn-metu"


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, help="extracted dataset folder, any parent of it, or the downloaded .zip/.rar "
                                                  "(omit to download automatically)")
    ap.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    ap.add_argument("--api", default="http://127.0.0.1:8000", help="running backend to install into")
    ap.add_argument("--no-upload", action="store_true", help="only train; do not install into the backend")
    ap.add_argument("--out", type=Path, default=ROOT / "model_store_build" / MODEL_ID)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--size", type=int, default=96)
    ap.add_argument("--limit", type=int, default=6000, help="images per class to use (0 = all 20,000)")
    ap.add_argument("--skip-deps", action="store_true", help="do not pip-install torch/onnx when missing")
    args = ap.parse_args()

    if not args.skip_deps:
        ensure_deps()
    data = find_dataset(args.data_dir) if args.data_dir else find_dataset(download(args.download_dir))
    log(f"STEP dataset ready: {data}")
    args.out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", "-m", "ml.train_crack_classifier", "--data-dir", str(data), "--out", str(args.out),
           "--epochs", str(args.epochs), "--size", str(args.size), "--limit", str(args.limit), "--model-id", MODEL_ID,
           "--dataset-name", "Concrete Crack Images for Classification (Özgenel)", "--dataset-version", "2",
           "--dataset-url", DATASET_PAGE, "--dataset-license", "CC BY 4.0"]
    log("STEP training (this takes a few minutes to ~1 h on a laptop CPU)")
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        raise SystemExit("Training failed — see the error above.")
    log(f"STEP model written to {args.out}")
    if args.no_upload:
        return
    res = post_multipart_two(args.api.rstrip("/") + "/api/v1/models/upload", args.out / "model.onnx", args.out / "model_card.json")
    log(f"STEP installed: {res.get('installed')} v{res.get('version')}")


def ensure_deps() -> None:
    missing = [m for m in ("torch", "onnx", "onnxscript") if importlib.util.find_spec(m) is None]
    if missing:
        log(f"STEP installing {', '.join(missing)} with pip (≈200 MB for torch, once)")
        subprocess.run([sys.executable, "-m", "pip", "install", *missing], check=True)


def _fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "StructuraSense-setup/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            pct = int(done * 100 / total) if total else -1
            if (pct // 5 != last // 5) if total else done // (20 << 20) != last:
                log(f"PROGRESS download {done / 1e6:.0f} MB" + (f" / {total / 1e6:.0f} MB ({pct} %)" if total else ""))
                last = pct if total else done // (20 << 20)
    tmp.rename(dest)


def download(folder: Path) -> Path:
    """Download the dataset archive once (re-used on later runs)."""
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / "dataset.zip"
    if not archive.exists():
        errors = []
        urls = list(DOWNLOAD_URLS)
        try:  # the public files API lists direct download links
            with urllib.request.urlopen(urllib.request.Request(FILES_API, headers={"User-Agent": "StructuraSense-setup/1.0"}), timeout=30) as r:
                for f in json.loads(r.read()):
                    link = (f.get("content_details") or {}).get("download_url")
                    if link:
                        urls.append(link)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"files API: {exc}")
        for url in urls:
            log(f"STEP downloading dataset from {url}")
            try:
                _fetch(url, archive)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")
        else:
            raise SystemExit("Automatic download failed (" + "; ".join(errors) + f").\nOpen {DATASET_PAGE}, click 'Download All', "
                             "then run again with --data-dir <the downloaded zip> (or paste its path in Settings → AI model).")
    return archive


def extract_rar(rar: Path, dest: Path) -> None:
    """Windows 10/11 'tar' (libarchive) reads RAR; otherwise 7-Zip / unrar."""
    dest.mkdir(parents=True, exist_ok=True)
    tools = [["tar", "-xf", str(rar), "-C", str(dest)]]
    for exe in ("7z", "7za", r"C:\Program Files\7-Zip\7z.exe"):
        tools.append([exe, "x", "-y", f"-o{dest}", str(rar)])
    tools.append(["unrar", "x", "-o+", str(rar), str(dest) + "/"])
    errors = []
    for cmd in tools:
        if shutil.which(cmd[0]) is None and not Path(cmd[0]).exists():
            continue
        log(f"STEP extracting {rar.name} with {Path(cmd[0]).name} (40,000 images, a few minutes)")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and any(dest.rglob("Positive")):
            return
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        errors.append(f"{cmd[0]}: {(r.stderr or r.stdout).strip()[:200]}")
    raise SystemExit(f"Could not extract {rar} ({'; '.join(errors) or 'no extractor found'}). "
                     "Extract it with 7-Zip or WinRAR (right-click → Extract here) and run again.")


DONE_MARKER = ".structurasense-extracted"


def extract_archive(archive: Path) -> Path:
    """Extract next to the archive; reuse only a folder whose extraction finished (marker file)."""
    dest = archive.with_name(archive.stem + "-extracted")
    if (dest / DONE_MARKER).exists():
        return dest
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    if archive.suffix.lower() == ".zip":
        import zipfile

        log(f"STEP extracting {archive.name}")
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        extract_rar(archive, tmp)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    (dest / DONE_MARKER).write_text("ok")
    return dest


def find_dataset(path: Path) -> Path:
    """Accept the extracted folder, any parent of it, or the downloaded .zip/.rar (extracted next to it)."""
    path = path.expanduser().resolve()
    if path.is_file() and path.suffix.lower() in (".zip", ".rar"):
        path = extract_archive(path)
    if not path.is_dir():
        raise SystemExit(f"{path} is not a folder, .zip or .rar file.")
    for cand in [path, *sorted(p for p in path.rglob("*") if p.is_dir())]:
        if (cand / "Positive").is_dir() and (cand / "Negative").is_dir():
            return cand
    rars = sorted(path.rglob("*.rar"))
    if rars:
        return find_dataset(extract_archive(rars[0]))
    raise SystemExit(f"No folder with 'Positive' and 'Negative' sub-folders found under {path}.")


def post_multipart_two(url: str, onnx: Path, card: Path) -> dict:
    """Upload both files in one multipart request."""
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
    try:
        main()
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(f"ERROR {exc.code}", flush=True)
            sys.exit(1)
        raise
