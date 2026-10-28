"""Inspection report generation (PDF via ReportLab + print-friendly HTML).

Both outputs are rendered from the same ``collect_report_data`` dictionary so
they always agree. Only stored records are reported; data provenance is shown
for every section and simulated/demo content is explicitly marked.
"""
from __future__ import annotations

import html
import io
from collections import Counter
from datetime import datetime

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ids import new_id
from app.models import Alert, Asset, Baseline, Component, Defect, Device, ImageRecord, Inspection, ModelRecord, Report, VibrationFeature
from app.services.events import log_event
from app.services.settings_store import get_setting
from app.services.storage import get_storage
from app.timeutil import utcnow

DISCLAIMER = (
    "This report summarises records stored in StructuraSense AI. Review priorities are rule-based indicators of review "
    "urgency, not certified structural assessments or failure probabilities. AI outputs are screening aids whose "
    "performance depends on the installed model and its recorded evaluation. Locations marked approximate are not survey-grade. "
    "No remaining-useful-life estimate is provided. All findings require verification by a qualified structural engineer."
)

PRIORITY_COLORS = {"critical": "#b91c1c", "high": "#dc2626", "medium": "#ea580c", "low": "#ca8a04", "unassessed": "#6b7280"}


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "—"


def collect_report_data(db: Session, asset_id: str, start: datetime, end: datetime) -> dict:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError("Unknown asset")
    comps = {c.id: c for c in db.query(Component).filter(Component.asset_id == asset_id).all()}
    inspections = db.query(Inspection).filter(Inspection.asset_id == asset_id, Inspection.observed_at >= start,
                                              Inspection.observed_at <= end).order_by(Inspection.observed_at).all()
    defects = db.query(Defect).filter(Defect.asset_id == asset_id, Defect.observed_at >= start, Defect.observed_at <= end).order_by(Defect.observed_at).all()
    alerts = db.query(Alert).filter(Alert.asset_id == asset_id, Alert.last_seen_at >= start, Alert.first_seen_at <= end).order_by(Alert.first_seen_at).all()
    devices = db.query(Device).filter(Device.asset_id == asset_id).all()
    dev_ids = [d.id for d in devices]
    feats = (
        db.query(VibrationFeature)
        .filter(VibrationFeature.device_id.in_(dev_ids), VibrationFeature.window_start >= start, VibrationFeature.window_end <= end)
        .order_by(VibrationFeature.window_start)
        .all()
    )
    sources = Counter([d.data_source for d in defects] + [i.data_source for i in inspections] + [f.source for f in feats])
    warnings = []
    if any(s in ("simulated", "demo") for s in sources):
        warnings.append("This report contains SIMULATED and/or DEMONSTRATION data. These are not measurements of a real structure.")
    unavailable = [i for i in inspections if i.status == "model_unavailable"]
    if unavailable:
        warnings.append(f"{len(unavailable)} image inspection(s) were stored without AI analysis because no model was installed.")
    poor = [i for i in inspections if i.image_id and (db.get(ImageRecord, i.image_id).quality or {}).get("issues")]
    if poor:
        warnings.append(f"{len(poor)} inspection image(s) were flagged by image-quality heuristics.")
    incomplete = [f for f in feats if f.data_quality != "ok"]
    if incomplete:
        warnings.append(f"{len(incomplete)} vibration window(s) were incomplete and not evaluated for anomalies.")
    from app.services.device_status import connection_status

    dev_status = {d.id: connection_status(db, d) for d in devices}
    for d in devices:
        if dev_status[d.id]["status"] in ("offline", "stale", "never_connected"):
            warnings.append(f"Device {d.name} ({d.id}) status: {dev_status[d.id]['label']}. Missing data is not evidence of normal condition.")

    by_device: dict[str, list] = {}
    for f in feats:
        by_device.setdefault(f.device_id, []).append(f)
    baselines = {b.device_id: b for b in db.query(Baseline).filter(Baseline.device_id.in_(dev_ids), Baseline.active.is_(True)).all()}
    models_used = sorted({(i.model_id, i.model_version) for i in inspections if i.model_id})
    model_records = [db.get(ModelRecord, m) for m, _ in models_used]

    return {
        "asset": asset,
        "components": comps,
        "period": (start, end),
        "inspections": inspections,
        "images_analyzed": sum(1 for i in inspections if i.status == "completed"),
        "images_stored": sum(1 for i in inspections if i.image_id),
        "defects": defects,
        "defect_by_priority": Counter(d.priority for d in defects),
        "defect_by_category": Counter(d.category for d in defects),
        "alerts": alerts,
        "devices": devices,
        "device_status": dev_status,
        "features": feats,
        "features_by_device": by_device,
        "anomalies": [f for f in feats if f.anomaly],
        "baselines": baselines,
        "warnings": warnings,
        "sources": dict(sources),
        "models": [(m, v, r) for (m, v), r in zip(models_used, model_records)],
        "config": {"priority_rules": get_setting(db, "priority_rules"), "vibration": get_setting(db, "vibration")},
    }


def _chart(feats: list[VibrationFeature], baseline: Baseline | None, title: str) -> Drawing:
    d = Drawing(170 * mm, 55 * mm)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 12 * mm, 8 * mm, 150 * mm, 38 * mm
    t0 = feats[0].window_start.timestamp()
    pts = [((f.window_start.timestamp() - t0) / 3600.0, f.rms_dyn) for f in feats]
    data = [pts]
    if baseline:
        data.append([(pts[0][0], baseline.rms_dyn_mean), (pts[-1][0], baseline.rms_dyn_mean)])
    lp.data = data
    lp.lines[0].strokeColor = colors.HexColor("#0e7490")
    lp.lines[0].strokeWidth = 1
    if baseline:
        lp.lines[1].strokeColor = colors.HexColor("#9ca3af")
        lp.lines[1].strokeDashArray = [3, 2]
    lp.xValueAxis.labelTextFormat = "%.1f h"
    lp.yValueAxis.labelTextFormat = "%.3f"
    lp.xValueAxis.labels.fontSize = lp.yValueAxis.labels.fontSize = 7
    d.add(lp)
    d.add(String(12 * mm, 50 * mm, title, fontSize=8, fillColor=colors.HexColor("#111827")))
    return d


def render_pdf(data: dict, report_id: str, generated_at: datetime) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Inspection report {report_id}", author="StructuraSense AI")
    ss = getSampleStyleSheet()
    h1, h2, body = ss["Title"], ss["Heading2"], ss["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    warn = ParagraphStyle("warn", parent=body, textColor=colors.HexColor("#92400e"), fontSize=9)
    asset: Asset = data["asset"]
    s, e = data["period"]
    story = [
        Paragraph("StructuraSense AI — Inspection Report", h1),
        Paragraph(f"<b>Report ID:</b> {report_id} &nbsp; <b>Generated:</b> {_fmt(generated_at)}", body),
        Paragraph(f"<b>Asset:</b> {html.escape(asset.name)} ({asset.id}) — {asset.asset_type}" + (" — DEMONSTRATION ASSET" if asset.is_demo else ""), body),
        Paragraph(f"<b>Reporting period:</b> {_fmt(s)} to {_fmt(e)}", body),
        Spacer(1, 4 * mm),
    ]
    tstyle = TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                         ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9ca3af")), ("VALIGN", (0, 0), (-1, -1), "TOP")])

    story.append(Paragraph("Data-quality warnings", h2))
    for w in data["warnings"] or ["None recorded."]:
        story.append(Paragraph("• " + html.escape(w), warn))
    story.append(Paragraph(f"Record sources in period: {html.escape(str(data['sources'] or 'none'))}", small))

    story.append(Paragraph("Summary", h2))
    summary = [["Inspections performed", len(data["inspections"])], ["Images analysed by a model", data["images_analyzed"]],
               ["Images stored", data["images_stored"]], ["Findings recorded", len(data["defects"])],
               ["Vibration windows analysed", len(data["features"])], ["Vibration anomaly windows", len(data["anomalies"])],
               ["Alerts (active in period)", len(data["alerts"])]]
    story.append(Table([["Metric", "Value"]] + summary, colWidths=[90 * mm, 40 * mm], style=tstyle))
    if data["defects"]:
        story.append(Spacer(1, 3 * mm))
        rows = [["Priority", "Count"]] + [[p, n] for p, n in sorted(data["defect_by_priority"].items())]
        story.append(Table(rows, colWidths=[40 * mm, 20 * mm], style=tstyle))

    story.append(Paragraph("Findings and evidence", h2))
    if not data["defects"]:
        story.append(Paragraph("No findings recorded in this period.", body))
    for d in data["defects"]:
        comp = data["components"].get(d.component_id)
        block = [Paragraph(f"<b>{d.id}</b> — {d.category.replace('_', ' ')} — <font color='{PRIORITY_COLORS.get(d.priority, '#000')}'>"
                           f"priority {d.priority}</font> ({d.priority_source}) — status {d.review_status.replace('_', ' ')}", body)]
        lines = [
            f"Component: {html.escape(comp.name) if comp else '—'} ({d.component_id or 'unassigned'})",
            f"Observed: {_fmt(d.observed_at)} · Source: {d.detection_source} · Data: {d.data_source.upper()}",
            f"Location: {d.location_kind}-level · method {d.localization_method} · confidence {d.location_confidence}"
            + (f" · model coords ({d.pos_x:.2f}, {d.pos_y:.2f}, {d.pos_z:.2f})" if d.pos_x is not None else ""),
        ]
        if d.model_id:
            lines.append(f"Model: {d.model_id} v{d.model_version} · label '{d.model_label}' · confidence {d.model_confidence:.3f} (not a severity measure)")
        if d.measured_extent:
            lines.append(f"Measured extent: {html.escape(str(d.measured_extent))}")
        if d.description:
            lines.append(f"Description: {html.escape(d.description)}")
        for r in d.priority_rationale or []:
            lines.append(f"Priority rule — {html.escape(r.get('rule', ''))}: {html.escape(r.get('detail', ''))}")
        if d.follow_up_actions:
            lines.append(f"Follow-up: {html.escape(d.follow_up_actions)}")
        block += [Paragraph(x, small) for x in lines]
        if d.image_id:
            img = data_image(d.image_id)
            if img is not None:
                block.append(img)
        block.append(Spacer(1, 3 * mm))
        story.append(KeepTogether(block))

    story.append(Paragraph("Vibration analysis", h2))
    if not data["features"]:
        story.append(Paragraph("No vibration features recorded in this period.", body))
    for dev_id, feats in data["features_by_device"].items():
        dev = next(x for x in data["devices"] if x.id == dev_id)
        src = sorted({f.source for f in feats})
        b = data["baselines"].get(dev_id)
        title = f"{dev.name} — rms_dyn (g) per {int(feats[0].window_s)} s window [{', '.join(s.upper() for s in src)}]"
        story.append(_chart(feats, b, title))
        n_anom = sum(f.anomaly for f in feats)
        story.append(Paragraph(f"{len(feats)} windows, {n_anom} anomalous. Feature definition {feats[0].feature_version}. "
                               + (f"Baseline v{b.version} ({b.source}, {b.n_windows} windows), dashed line." if b else "No active baseline."), small))
    if data["anomalies"]:
        rows = [["Window start", "Device", "rms_dyn", "Ratio", "Reasons", "Source"]]
        for f in data["anomalies"][:40]:
            rows.append([_fmt(f.window_start), f.device_id, f"{f.rms_dyn:.4f}", f"{f.baseline_ratio:.2f}" if f.baseline_ratio else "—",
                         ", ".join(f.anomaly_reasons or []), f.source.upper()])
        story.append(Table(rows, style=tstyle, repeatRows=1))

    story.append(Paragraph("Alerts", h2))
    if not data["alerts"]:
        story.append(Paragraph("No alerts in this period.", body))
    else:
        rows = [["Alert", "Rule", "Priority", "Status", "First seen", "Count", "Resolution / ack"]]
        for a in data["alerts"]:
            note = a.resolution_notes or (f"ack by {a.acknowledged_by}" if a.acknowledged_by else "")
            rows.append([a.id, a.rule_type, a.priority, a.status, _fmt(a.first_seen_at), a.occurrence_count,
                         Paragraph(html.escape(note or "—"), small)])
        story.append(Table(rows, style=tstyle, repeatRows=1, colWidths=[24 * mm, 32 * mm, 16 * mm, 20 * mm, 28 * mm, 11 * mm, 47 * mm]))

    story.append(Paragraph("Devices", h2))
    rows = [["Device", "Type", "Data source", "Status"]] + [
        [f"{d.name} ({d.id})", d.device_type, d.data_source.upper(), data["device_status"][d.id]["label"]] for d in data["devices"]]
    story.append(Table(rows, style=tstyle, repeatRows=1))

    story.append(Paragraph("Models and configuration", h2))
    if not data["models"]:
        story.append(Paragraph("No AI model produced results in this period.", body))
    for mid, ver, rec in data["models"]:
        metrics = rec.metrics if rec else None
        story.append(Paragraph(f"{mid} v{ver} — recorded metrics: {html.escape(str(metrics)) if metrics else 'none recorded'}", small))
    pr = data["config"]["priority_rules"]
    story.append(Paragraph(f"Priority rules: category_base={html.escape(str(pr['category_base']))}; min_ai_confidence={pr['min_ai_confidence']}; "
                           f"extent_rules={html.escape(str(pr['extent_rules']))}.", small))
    story.append(Paragraph(f"Vibration settings: {html.escape(str(data['config']['vibration']))}.", small))

    story.append(Paragraph("Limitations and engineering-review disclaimer", h2))
    story.append(Paragraph(DISCLAIMER, body))
    story.append(Paragraph("RUL prediction unavailable: insufficient validated data.", body))

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        label = " · CONTAINS SIMULATED/DEMO DATA" if any(k in data["sources"] for k in ("simulated", "demo")) else ""
        canvas.drawString(16 * mm, 9 * mm, f"StructuraSense AI · {report_id}{label} · page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def data_image(image_id: str):
    from app.db import get_database

    with get_database().session() as db:
        rec = db.get(ImageRecord, image_id)
        if rec is None or not get_storage().exists(rec.storage_key):
            return None
        w = 55 * mm
        h = w * rec.height / rec.width
        img = Image(str(get_storage().path(rec.storage_key)), width=w, height=min(h, 70 * mm))
        img.hAlign = "LEFT"
        return img


def render_html(data: dict, report_id: str, generated_at: datetime) -> str:
    asset: Asset = data["asset"]
    s, e = data["period"]
    esc = html.escape
    parts = [f"""<!doctype html><html><head><meta charset="utf-8"><title>Report {report_id}</title>
<style>body{{font-family:system-ui,sans-serif;color:#111;max-width:900px;margin:24px auto;padding:0 16px;font-size:13px}}
h1{{font-size:22px}}h2{{font-size:16px;border-bottom:1px solid #ccc;padding-bottom:4px;margin-top:24px}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}td,th{{border:1px solid #bbb;padding:4px 6px;text-align:left;vertical-align:top}}
th{{background:#eee}}.warn{{color:#92400e}}.small{{font-size:11px;color:#444}}img{{max-width:220px;border:1px solid #ccc}}
@media print{{button{{display:none}}}}</style></head><body>
<button onclick="window.print()">Print</button>
<h1>StructuraSense AI — Inspection Report</h1>
<p><b>Report ID:</b> {report_id} · <b>Generated:</b> {_fmt(generated_at)}</p>
<p><b>Asset:</b> {esc(asset.name)} ({asset.id}){' — DEMONSTRATION ASSET' if asset.is_demo else ''}<br>
<b>Period:</b> {_fmt(s)} to {_fmt(e)}</p><h2>Data-quality warnings</h2>"""]
    parts += [f'<p class="warn">• {esc(w)}</p>' for w in data["warnings"] or ["None recorded."]]
    parts.append(f"<h2>Summary</h2><table><tr><th>Inspections</th><td>{len(data['inspections'])}</td></tr>"
                 f"<tr><th>Images analysed by a model</th><td>{data['images_analyzed']}</td></tr>"
                 f"<tr><th>Findings</th><td>{len(data['defects'])}</td></tr><tr><th>Vibration anomaly windows</th><td>{len(data['anomalies'])}</td></tr>"
                 f"<tr><th>Alerts</th><td>{len(data['alerts'])}</td></tr></table><h2>Findings</h2>")
    for d in data["defects"]:
        comp = data["components"].get(d.component_id)
        img = f'<img src="/api/v1/images/{d.image_id}/file" alt="evidence">' if d.image_id else ""
        rules = "<br>".join(esc(f"{r.get('rule')}: {r.get('detail')}") for r in d.priority_rationale or [])
        parts.append(f"<table><tr><th colspan=2>{d.id} — {d.category.replace('_', ' ')} — priority {d.priority} — {d.review_status}</th></tr>"
                     f"<tr><td>Component</td><td>{esc(comp.name) if comp else '—'}</td></tr><tr><td>Observed</td><td>{_fmt(d.observed_at)} · {d.detection_source} · {d.data_source.upper()}</td></tr>"
                     f"<tr><td>Location</td><td>{d.location_kind} · {d.localization_method} · {d.location_confidence}</td></tr>"
                     f"<tr><td>Priority rationale</td><td class=small>{rules}</td></tr><tr><td>Evidence</td><td>{img}</td></tr></table>")
    parts.append("<h2>Alerts</h2><table><tr><th>Alert</th><th>Rule</th><th>Priority</th><th>Status</th><th>First seen</th><th>Notes</th></tr>")
    for a in data["alerts"]:
        parts.append(f"<tr><td>{a.id}</td><td>{a.rule_type}</td><td>{a.priority}</td><td>{a.status}</td><td>{_fmt(a.first_seen_at)}</td><td>{esc(a.resolution_notes or '')}</td></tr>")
    parts.append("</table><h2>Vibration</h2>")
    for dev_id, feats in data["features_by_device"].items():
        parts.append(f"<p>{dev_id}: {len(feats)} windows, {sum(f.anomaly for f in feats)} anomalous ({', '.join(sorted({f.source.upper() for f in feats}))}).</p>")
    parts.append(f"<h2>Limitations</h2><p>{esc(DISCLAIMER)}</p><p>RUL prediction unavailable: insufficient validated data.</p></body></html>")
    return "".join(parts)


def generate_report(db: Session, asset_id: str, start: datetime, end: datetime, actor: str | None = None) -> Report:
    if end <= start:
        raise ValueError("period_end must be after period_start")
    data = collect_report_data(db, asset_id, start, end)
    rid = new_id("RPT")
    now = utcnow()
    pdf = render_pdf(data, rid, now)
    key = f"reports/{asset_id}/{rid}.pdf"
    get_storage().save(key, pdf)
    rep = Report(
        id=rid, asset_id=asset_id, period_start=start, period_end=end, storage_key=key, size_bytes=len(pdf), generated_by=actor,
        params={"app_version": get_settings().app_name}, generated_at=now,
        includes_simulated=any(k in data["sources"] for k in ("simulated", "demo")),
        summary={"inspections": len(data["inspections"]), "defects": len(data["defects"]), "alerts": len(data["alerts"]),
                 "anomalies": len(data["anomalies"]), "warnings": data["warnings"], "sources": data["sources"],
                 "by_priority": dict(data["defect_by_priority"])},
    )
    db.add(rep)
    log_event(db, event_type="report_generated", title=f"Report {rid} generated", asset_id=asset_id, ref_type="report", ref_id=rid, actor=actor, ts=now)
    db.flush()
    return rep

