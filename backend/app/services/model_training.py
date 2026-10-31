"""Background job: download the crack dataset, train the CNN and install it — started from Settings → AI model.

Runs ``python -m ml.setup_crack_model --no-upload`` as a child process (same Python as the backend), streams
its output into a log the UI polls, then installs the produced model through ``model_install``.
One job at a time; the job lives as long as the backend process.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from app.config import BACKEND_DIR
from app.timeutil import utcnow

OUT_DIR = BACKEND_DIR / "model_store_build" / "crack-cnn-metu"


class TrainingJob:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.state = "idle"  # idle | running | installing | done | failed | cancelled
        self.step = ""
        self.log: deque[str] = deque(maxlen=400)
        self.started_at = self.finished_at = None
        self.result: dict | None = None
        self.error: str | None = None
        self.params: dict = {}

    def status(self) -> dict:
        return {"state": self.state, "step": self.step, "log": list(self.log)[-80:], "params": self.params, "result": self.result,
                "error": self.error, "started_at": self.started_at.isoformat() if self.started_at else None,
                "finished_at": self.finished_at.isoformat() if self.finished_at else None}

    def start(self, data_path: str | None, limit: int, epochs: int, cmd_override: list[str] | None = None) -> dict:
        with self.lock:
            if self.state in ("running", "installing"):
                raise RuntimeError("A training job is already running.")
            if data_path and not Path(data_path).expanduser().exists():
                raise ValueError(f"{data_path} does not exist on this computer.")
            cmd = cmd_override or [sys.executable, "-u", "-m", "ml.setup_crack_model", "--no-upload", "--out", str(OUT_DIR),
                                   "--limit", str(limit), "--epochs", str(epochs)]
            if data_path and not cmd_override:
                cmd += ["--data-dir", data_path]
            self.log.clear()
            self.state, self.step, self.result, self.error = "running", "starting", None, None
            self.params = {"data_path": data_path, "limit": limit, "epochs": epochs}
            self.started_at, self.finished_at = utcnow(), None
            self.proc = subprocess.Popen(cmd, cwd=BACKEND_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace", bufsize=1)
            threading.Thread(target=self._pump, daemon=True).start()
            return self.status()

    def cancel(self) -> dict:
        with self.lock:
            if self.proc and self.state == "running":
                self.proc.terminate()
                self.state = "cancelled"
        return self.status()

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("PROGRESS ") and self.log and self.log[-1].startswith("PROGRESS "):
                self.log[-1] = line  # keep one live progress line
            else:
                self.log.append(line)
            if line.startswith("STEP "):
                self.step = line[5:]
            elif line.startswith("PROGRESS "):
                self.step = line[9:]
        code = self.proc.wait()
        if self.state == "cancelled":
            self.finished_at = utcnow()
            return
        if code != 0:
            self.state, self.finished_at = "failed", utcnow()
            self.error = self._failure_reason(code)
            return
        self._install()

    def _failure_reason(self, code: int) -> str:
        """Most useful line: the last Python exception (e.g. 'ModuleNotFoundError: …'), plus the setup script's ERROR line."""
        lines = [l for l in self.log if l and not l[0].isspace()]
        err = next((l[6:] for l in reversed(lines) if l.startswith("ERROR ")), None)
        exc = next((l for l in reversed(lines) if re.match(r"^[A-Za-z_.]*(Error|Exception)\b", l)), None)
        if exc and err:
            return f"{exc} — {err}"
        return exc or err or (lines[-1] if lines else f"exit code {code}")

    def _install(self) -> None:
        from app.db import get_database
        from app.services.model_install import install_model

        self.state, self.step = "installing", "installing the model"
        db = get_database().session()
        try:
            card = json.loads((OUT_DIR / "model_card.json").read_text())
            self.result = install_model(db, card, (OUT_DIR / "model.onnx").read_bytes(), actor="training job")
            self.result["metrics"] = card.get("metrics")
            self.state, self.step = "done", "installed"
            self.log.append(f"Installed {card['id']} v{card['version']}.")
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            self.state, self.error = "failed", f"install failed: {exc}"
        finally:
            db.close()
            self.finished_at = utcnow()


job = TrainingJob()
