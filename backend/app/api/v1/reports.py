from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_or_404, get_session
from app.models import Asset, Report
from app.schemas import ReportIn, ReportOut
from app.services.reports import collect_report_data, generate_report, render_html
from app.services.storage import get_storage
from app.timeutil import ensure_utc, utcnow

router = APIRouter(tags=["reports"])


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(body: ReportIn, db: Session = Depends(get_session)):
    get_or_404(db, Asset, body.asset_id, "Asset")
    try:
        rep = generate_report(db, body.asset_id, ensure_utc(body.period_start), ensure_utc(body.period_end), body.actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return rep


@router.get("/reports", response_model=list[ReportOut])
def list_reports(asset_id: str | None = None, db: Session = Depends(get_session)):
    q = db.query(Report)
    if asset_id:
        q = q.filter(Report.asset_id == asset_id)
    return q.order_by(Report.generated_at.desc()).all()


@router.get("/reports/{report_id}/download")
def download(report_id: str, db: Session = Depends(get_session)):
    rep = get_or_404(db, Report, report_id, "Report")
    st = get_storage()
    if not st.exists(rep.storage_key):
        raise HTTPException(410, "Report file is missing from storage")
    return Response(st.read(rep.storage_key), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{rep.id}.pdf"'})


@router.get("/reports/{report_id}/print", response_class=HTMLResponse)
def print_view(report_id: str, db: Session = Depends(get_session)):
    rep = get_or_404(db, Report, report_id, "Report")
    data = collect_report_data(db, rep.asset_id, rep.period_start, rep.period_end)
    return render_html(data, rep.id, rep.generated_at or utcnow())
