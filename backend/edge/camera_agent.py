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
    def __init__(self, seconds: float, fps: float):
        self.frames: deque = deque(maxlen=max(1, int(seconds * fps)))
        self.lock = threading.Lock()
        self.latest = None

    def add(self, ts: float, frame):
        with self.lock:
            self.frames.append((ts, frame))
            self.latest = (ts, frame)

    def window(self, t0: float, t1: float):
        with self.lock:
            return [(t, f) for t, f in self.frames if t0 <= t <= t1]


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


def write_clip(frames, fps: float) -> bytes | None:
    if not frames:
        return None
    h, w = frames[0][1].shape[:2]
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "clip.webm")
        vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"VP80"), fps, (w, h))
        if not vw.isOpened():
            log.error("VP8/WebM encoder unavailable in this OpenCV build; clip not written")
            return None
        for _, f in frames:
            vw.write(f if f.shape[:2] == (h, w) else cv2.resize(f, (w, h)))
        vw.release()
        return Path(path).read_bytes()


def make_preview_server(buf: FrameBuffer, bind: str, port: int):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/snapshot"):
                latest = buf.latest
                if latest is None:
                    self.send_error(503, "no frame yet")
                    return
                ok, jpg = cv2.imencode(".jpg", latest[1], [cv2.IMWRITE_JPEG_QUALITY, 80])
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
                    latest = buf.latest
                    if latest is not None:
                        ok, jpg = cv2.imencode(".jpg", latest[1], [cv2.IMWRITE_JPEG_QUALITY, 70])
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
    deadline = time.time() + args.run_for if args.run_for else None
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
            if res.get("request_clip") and res.get("inspection"):
                time.sleep(args.post)
                frames = buf.window(ts - args.pre, ts + args.post)
                clip = write_clip(frames, args.fps)
                if clip:
                    post_multipart(f"{api}/inspections/{res['inspection']['id']}/clip",
                                   {"started_at": iso(frames[0][0]), "duration_s": f"{frames[-1][0] - frames[0][0]:.2f}"},
                                   "file", "clip.webm", clip, "video/webm", args.token, timeout=120)
                    log.info("uploaded %.1f s clip (%d frames, %d KB)", frames[-1][0] - frames[0][0], len(frames), len(clip) // 1024)
        except urllib.error.HTTPError as exc:
            log.error("backend rejected request: %s %s", exc.code, exc.read()[:300])
            if exc.code == 401:
                raise SystemExit("Invalid device token or device not registered as a real camera.") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            log.warning("backend unreachable: %s (retrying)", exc)
        time.sleep(max(0.0, args.interval - (time.time() - now)))
    cap.running = False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--device-id")
    ap.add_argument("--token")
    ap.add_argument("--list-cameras", action="store_true", help="print the webcam indices that deliver frames, then exit")
    ap.add_argument("--source", default="0", help="webcam index (0, 1, …), video file or stream URL")
    ap.add_argument("--loop", action="store_true", help="loop a video file source")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--interval", type=float, default=5, help="seconds between analysed frames")
    ap.add_argument("--pre", type=float, default=5, help="clip seconds before the detection")
    ap.add_argument("--post", type=float, default=5, help="clip seconds after the detection")
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
    if not args.device_id or not args.token:
        ap.error("--device-id and --token are required")
    run(args)


if __name__ == "__main__":
    main()
