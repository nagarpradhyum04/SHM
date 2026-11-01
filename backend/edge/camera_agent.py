"""StructuraSense webcam agent.

Runs next to a USB webcam (normally on the same laptop as the backend):

1. captures frames continuously into a ring buffer (the last few seconds);
2. every ``--interval`` seconds sends the newest frame to ``POST /api/v1/cameras/<id>/frames``.
   The backend runs the installed model. Frames are stored only when the model reports a finding
   (plus one periodic reference snapshot every ``--keep-every`` seconds);
3. when the backend reports a finding it keeps recording for ``--post`` seconds and uploads a
   short WebM clip (``--pre`` seconds before + ``--post`` seconds after) to
   ``POST /api/v1/inspections/<id>/clip``;
4. serves a live MJPEG preview at ``http://<bind>:<preview-port>/stream`` and reports it in its
   heartbeat so the dashboard can show it.

Without an installed model the backend cannot detect cracks: the agent then only stores the
periodic reference snapshots (status "model unavailable"). It never invents detections.

Usage:
  python -m edge.camera_agent --api http://127.0.0.1:8000 --device-id CAM-WEB-01 --token <token>
  python -m edge.camera_agent ... --source path/to/test_video.mp4      # test without a webcam
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("camera_agent")


def post_multipart(url: str, fields: dict, file_field: str, filename: str, content: bytes, content_type: str, token: str, timeout=30) -> dict:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                 f"Content-Type: {content_type}\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Device-Token": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def post_json(url: str, body: dict, token: str, timeout=10) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Device-Token": token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


class FrameBuffer:
    """Ring buffer of JPEG-compressed frames (60 s of 720p at 10 fps ≈ 50 MB instead of ≈ 1.6 GB raw)
    plus the latest raw frame for analysis/preview and an optional detection overlay for the preview."""

    def __init__(self, seconds: float, fps: float, quality: int = 80):
        self.frames: deque = deque(maxlen=max(1, int(seconds * fps)))
        self.lock = threading.Lock()
        self.latest = None
        self.quality = quality
        self.overlay: dict | None = None  # {"bbox": [x0,y0,x1,y1], "label": str, "until": epoch}

    def add(self, ts: float, frame):
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        with self.lock:
            if ok:
                self.frames.append((ts, jpg.tobytes()))
            self.latest = (ts, frame)

    def window(self, t0: float, t1: float) -> list[tuple[float, bytes]]:
        with self.lock:
            return [(t, f) for t, f in self.frames if t0 <= t <= t1]

    def newest_ts(self) -> float:
        with self.lock:
            return self.frames[-1][0] if self.frames else 0.0

    def preview_frame(self):
        latest = self.latest
        if latest is None:
            return None
        frame = latest[1]
        ov = self.overlay
        if ov and time.time() < ov["until"]:
            frame = frame.copy()
            x0, y0, x1, y1 = (int(v) for v in ov["bbox"])
            cv2.rectangle(frame, (x0, y0), (x1, y1), (0, 0, 255), 3)
            cv2.putText(frame, ov["label"], (x0, max(20, y0 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        return frame


class Capture(threading.Thread):
    def __init__(self, source, fps: float, width: int | None, buf: FrameBuffer, loop_file: bool):
        super().__init__(daemon=True)
        self.source, self.fps, self.buf, self.loop_file = source, fps, buf, loop_file
        self.cap = open_capture(source)
        if width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if not self.cap.isOpened():
            raise SystemExit(f"Cannot open video source {source!r}")
        self.running = True
        self.failures = 0

    def run(self):
        period = 1.0 / self.fps
        while self.running:
            t = time.time()
            ok, frame = self.cap.read()
            if not ok:
                if self.loop_file and isinstance(self.source, str):
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                self.failures += 1
                time.sleep(0.5)
                continue
            self.buf.add(t, frame)
            time.sleep(max(0.0, period - (time.time() - t)))


def open_capture(source):
    """Open a webcam index or a file/URL. On Windows, USB webcams open faster and more reliably via DirectShow."""
    if isinstance(source, int) and os.name == "nt":
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
    return cv2.VideoCapture(source)


def list_cameras(max_index: int = 6) -> list[dict]:
    cv2.setLogLevel(0)  # silent: probing absent indices is expected to fail
    found = []
    for i in range(max_index):
        cap = open_capture(i)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                found.append({"index": i, "width": frame.shape[1], "height": frame.shape[0]})
        cap.release()
    return found


def write_clip(frames: list[tuple[float, bytes]], fps: float, max_width: int = 960) -> bytes | None:
    """Encode buffered JPEG frames as a browser-playable WebM (VP8), downscaled to ``max_width``."""
    if not frames:
        return None
    first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
    h, w = first.shape[:2]
    if w > max_width:
        h, w = int(h * max_width / w), max_width
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "clip.webm")
        vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"VP80"), fps, (w, h))
        if not vw.isOpened():
            log.error("VP8/WebM encoder unavailable in this OpenCV build; clip not written")
            return None
        for _, jpg in frames:
            f = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if f is not None:
                vw.write(f if f.shape[:2] == (h, w) else cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA))
        vw.release()
        return Path(path).read_bytes()


def record_clip(api: str, token: str, buf: FrameBuffer, inspection_id: str, ts: float, pre: float, post: float, fps: float) -> None:
    """Wait until ``post`` seconds after the detection are buffered, then upload pre+post seconds as one clip."""
    deadline = time.time() + post + 15
    while buf.newest_ts() < ts + post and time.time() < deadline:
        time.sleep(0.5)
    frames = buf.window(ts - pre, ts + post)
    clip = write_clip(frames, fps)
    if not clip:
        return
    try:
        post_multipart(f"{api}/inspections/{inspection_id}/clip",
                       {"started_at": iso(frames[0][0]), "duration_s": f"{frames[-1][0] - frames[0][0]:.2f}"},
                       "file", "clip.webm", clip, "video/webm", token, timeout=300)
        log.info("uploaded %.1f s clip (%.1f s before + %.1f s after, %d frames, %d KB)", frames[-1][0] - frames[0][0],
                 ts - frames[0][0], frames[-1][0] - ts, len(frames), len(clip) // 1024)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        log.error("clip upload failed: %s", exc)


def make_preview_server(buf: FrameBuffer, bind: str, port: int):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/snapshot"):
                frame = buf.preview_frame()
                if frame is None:
                    self.send_error(503, "no frame yet")
                    return
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(jpg.tobytes())
                return
            if not self.path.startswith("/stream"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    frame = buf.preview_frame()
                    if frame is not None:
                        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError):
                return

    srv = ThreadingHTTPServer((bind, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def run(args) -> None:
    api = args.api.rstrip("/") + "/api/v1"
    buf = FrameBuffer(args.pre + args.post + 2, args.fps)
    source = int(args.source) if str(args.source).isdigit() else args.source
    cap = Capture(source, args.fps, args.width, buf, loop_file=args.loop)
    cap.start()
    stream_url = None
    if args.preview_port:
        make_preview_server(buf, args.bind, args.preview_port)
        host = args.public_host or ("127.0.0.1" if args.bind in ("0.0.0.0", "") else args.bind)
        stream_url = f"http://{host}:{args.preview_port}/stream"
        log.info("live preview at %s", stream_url)
    last_keep = 0.0
    last_beat = 0.0
    clip_threads: list[threading.Thread] = []
    deadline = time.time() + args.run_for if args.run_for else None
    log.info("analysing a frame every %.0f s; clips keep %.0f s before + %.0f s after a detection", args.interval, args.pre, args.post)
    while deadline is None or time.time() < deadline:
        now = time.time()
        try:
            if now - last_beat >= args.heartbeat:
                post_json(f"{api}/devices/{args.device_id}/heartbeat",
                          {"stream_url": stream_url, "fw": "camera-agent-0.1", "info": {"source": str(args.source), "fps": args.fps,
                                                                                        "capture_failures": cap.failures}}, args.token)
                last_beat = now
            latest = buf.latest
            if latest is None:
                time.sleep(0.2)
                continue
            ts, frame = latest
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            keep = args.keep_every and now - last_keep >= args.keep_every
            res = post_multipart(f"{api}/cameras/{args.device_id}/frames", {"store": "always" if keep else "on_finding", "captured_at": iso(ts)},
                                 "file", "frame.jpg", jpg.tobytes(), "image/jpeg", args.token)
            if keep:
                last_keep = now
            if res.get("suppressed_by"):
                log.info("finding already open (%s); not stored again", res["suppressed_by"])
            elif res.get("stored"):
                log.info("stored inspection %s (%s, %d finding(s))", res["inspection"]["id"], res["model_status"], len(res["defects"]))
            if res.get("defects"):
                d = res["defects"][0]
                region = d.get("image_region") or {}
                if region.get("bbox"):
                    where = f" @ ({d['pos_x']:.2f}, {d['pos_y']:.2f}, {d['pos_z']:.2f}) m" if d.get("pos_x") is not None else ""
                    buf.overlay = {"bbox": region["bbox"], "label": f"{d['category'].replace('_', ' ')} {d.get('model_confidence') or 0:.2f}{where}",
                                   "until": time.time() + 15}
                log.info("DETECTED %s (%s) — %s", d["category"], d["id"], d.get("localization_notes") or "")
            if res.get("request_clip") and res.get("inspection"):
                # finish the clip in the background so analysis continues while the next seconds are recorded
                t = threading.Thread(target=record_clip, args=(api, args.token, buf, res["inspection"]["id"], ts, args.pre, args.post, args.fps),
                                     daemon=True, name="clip")
                t.start()
                clip_threads.append(t)
        except urllib.error.HTTPError as exc:
            log.error("backend rejected request: %s %s", exc.code, exc.read()[:300])
            if exc.code == 401:
                raise SystemExit("Invalid device token or device not registered as a real camera.") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            log.warning("backend unreachable: %s (retrying)", exc)
        time.sleep(max(0.0, args.interval - (time.time() - now)))
    for t in clip_threads:  # let pending clip uploads finish (--run-for / shutdown)
        t.join(timeout=args.post + 60)
    cap.running = False


AUTO_FILE = Path(__file__).resolve().parent.parent / "data" / "camera_agent.json"


def _api_json(base: str, path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(base.rstrip("/") + "/api/v1" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"null")


def auto_setup(args) -> None:
    """--auto: register this webcam (once), remember its token in backend/data/camera_agent.json, pick the camera."""
    saved = {}
    if AUTO_FILE.exists():
        try:
            saved = json.loads(AUTO_FILE.read_text())
        except ValueError:
            saved = {}
    try:
        _api_json(args.api, "/health")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"Backend not reachable at {args.api} ({exc}). Start it first (scripts\\dev.ps1), then run this again.") from None
    dev_id = args.device_id or saved.get("device_id") or "WEBCAM-01"
    token = args.token or (saved.get("token") if saved.get("device_id") == dev_id else None)
    try:
        dev = _api_json(args.api, f"/devices/{dev_id}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        dev = None
    if dev is None:
        assets = _api_json(args.api, "/assets") or []
        if not assets:
            raise SystemExit("No structure exists yet. Create one in the app (Structures), then run this again.")
        asset = next((a for a in assets if a["id"] == args.asset), None) or next((a for a in assets if not a.get("is_demo")), assets[0])
        r = _api_json(args.api, "/devices", "POST", {"id": dev_id, "device_type": "camera", "name": "USB webcam", "asset_id": asset["id"],
                                                     "data_source": "real", "capabilities": ["image"], "hardware_model": "USB webcam"})
        token = r["ingestion_token"]
        print(f"Registered camera {dev_id} on '{asset['name']}'. Place it on the 3D model later: Devices -> {dev_id} -> Edit placement.")
    elif dev.get("data_source") != "real":
        raise SystemExit(f"{dev_id} is a simulated device; use another id: --device-id WEBCAM-02")
    elif not token:
        token = _api_json(args.api, f"/devices/{dev_id}/rotate-token", "POST")["ingestion_token"]
        print(f"New token issued for {dev_id} (the old one no longer works).")
    if args.source == "auto":
        if saved.get("source") is not None and saved.get("device_id") == dev_id:
            args.source = str(saved["source"])
        else:
            cams = list_cameras()
            if not cams:
                raise SystemExit("No webcam delivered frames. Plug it in and close Zoom/Teams/Camera app/browser tabs using it.")
            # on a laptop index 0 is usually the built-in camera; a plugged-in USB camera is usually 1
            pick = next((c for c in cams if c["index"] == 1), cams[0])
            print("Cameras found: " + ", ".join(f"{c['index']} ({c['width']}x{c['height']})" for c in cams)
                  + f". Using {pick['index']}. Wrong one? add --source <number>")
            args.source = str(pick["index"])
    AUTO_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_FILE.write_text(json.dumps({"device_id": dev_id, "token": token, "source": args.source}))
    args.device_id, args.token = dev_id, token
    print(f"Camera {dev_id} (source {args.source}) starting. Live view: open the app -> Live cameras. Stop with Ctrl+C.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--device-id")
    ap.add_argument("--token")
    ap.add_argument("--list-cameras", action="store_true", help="print the webcam indices that deliver frames, then exit")
    ap.add_argument("--source", default=None, help="webcam index (0, 1, …), video file or stream URL (--auto: auto)")
    ap.add_argument("--auto", action="store_true", help="register this webcam if needed, remember its token, pick the USB camera")
    ap.add_argument("--asset", default=None, help="--auto: structure id to register the camera on")
    ap.add_argument("--loop", action="store_true", help="loop a video file source")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--interval", type=float, default=2, help="seconds between analysed frames")
    ap.add_argument("--pre", type=float, default=30, help="clip seconds before the detection")
    ap.add_argument("--post", type=float, default=30, help="clip seconds after the detection")
    ap.add_argument("--keep-every", type=float, default=3600, help="store a reference snapshot this often (0 = never)")
    ap.add_argument("--heartbeat", type=float, default=30)
    ap.add_argument("--preview-port", type=int, default=8081, help="0 disables the MJPEG preview")
    ap.add_argument("--bind", default="127.0.0.1", help="preview bind address (0.0.0.0 to share on the LAN)")
    ap.add_argument("--public-host", default=None, help="host name/IP the dashboard should use for the preview")
    ap.add_argument("--run-for", type=float, default=0, help="stop after N seconds (testing)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.list_cameras:
        cams = list_cameras()
        print("\n".join(f"--source {c['index']}   ({c['width']}x{c['height']})" for c in cams) or "No webcam delivered frames (is another app using it?).")
        return
    if args.auto:
        args.source = args.source or "auto"
        auto_setup(args)
    args.source = args.source or "0"
    if not args.device_id or not args.token:
        ap.error("--device-id and --token are required (or use --auto)")
    run(args)


if __name__ == "__main__":
    main()
