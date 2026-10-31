"""Install a trained ONNX classifier + model card (shared by the upload endpoint and the training job)."""
from __future__ import annotations

import json
import re
import shutil

from sqlalchemy.orm import Session

from app.services.events import log_event
from app.services.inference import get_model_registry
from app.services.settings_store import set_setting


class InstallError(ValueError):
    pass


def install_model(db: Session, card: dict, data: bytes, actor: str | None = None) -> dict:
    """The model is loaded once to prove it works before it is activated; nothing is installed on failure."""
    from app.services.inference.registry import REQUIRED_CARD_FIELDS

    missing = [f for f in REQUIRED_CARD_FIELDS if f not in card]
    if missing:
        raise InstallError(f"model card is missing fields: {missing}")
    if card["framework"] != "onnx" or card["task"] != "classification":
        raise InstallError("Only ONNX classification models are supported by this release.")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", str(card["id"])):
        raise InstallError("model id may only contain letters, digits, '.', '_' and '-'")
    reg = get_model_registry()
    target = reg.model_dir / str(card["id"])
    backup = None
    if target.exists():
        backup = target.with_name(f".{target.name}.previous")  # hidden: the registry scan skips it
        shutil.rmtree(backup, ignore_errors=True)
        target.rename(backup)
    target.mkdir(parents=True)
    card = {**card, "file": "model.onnx"}
    (target / "model.onnx").write_bytes(data)
    (target / "model_card.json").write_text(json.dumps(card, indent=2))
    reg.scan()
    if card["id"] not in {m["id"] for m in reg.status()["loaded"]}:
        error = next(iter(reg.status()["errors"].values()), "model could not be loaded")
        shutil.rmtree(target, ignore_errors=True)
        if backup:
            backup.rename(target)
        reg.scan()
        raise InstallError(f"Model could not be loaded: {error}")
    if backup:
        shutil.rmtree(backup, ignore_errors=True)
        reg.scan()
    set_setting(db, "active_model", {"model_id": card["id"]}, actor=actor)
    reg.sync_db(db)
    log_event(db, event_type="config_changed", title=f"AI model {card['id']} v{card['version']} installed", actor=actor)
    db.commit()
    return {"installed": card["id"], "version": card["version"], "metrics_recorded": card.get("metrics") is not None, **reg.status()}
