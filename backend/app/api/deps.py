from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import get_session  # noqa: F401  (re-export)


def get_or_404(db: Session, model, key, what: str | None = None):
    obj = db.get(model, key)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{what or model.__name__} '{key}' not found")
    return obj
