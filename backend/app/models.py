"""Relational schema for StructuraSense AI.

Coordinate conventions (kept deliberately distinct):
* ``model_*`` / ``pos_*`` columns: local 3D model coordinates (metres, Y-up) of the
  digital-twin scene. They are NOT geographic coordinates.
* ``latitude`` / ``longitude``: optional WGS84 coordinates, only when known.
* Image coordinates (pixels) live inside JSON ``image_region`` fields.
* The mapping from model to world coordinates is stored on the asset
  (``geo_transform``) and is flagged as calibrated or not.

Provenance: every observation-like record carries a ``data_source``
(``real`` | ``uploaded`` | ``simulated`` | ``demo``) so simulated and real data
can never be mixed silently.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime
from app.timeutil import utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


# --------------------------------------------------------------------------- assets


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False, default="bridge")
    description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    site_description: Mapped[str | None] = mapped_column(Text)
    commissioning_date: Mapped[date | None] = mapped_column(Date)
    model_kind: Mapped[str] = mapped_column(String(20), default="procedural")  # procedural | gltf
    model_ref: Mapped[str | None] = mapped_column(String(300))
    # {"origin_lat", "origin_lon", "origin_alt_m", "heading_deg", "scale", "calibrated": bool, "method": str}
    geo_transform: Mapped[dict | None] = mapped_column(JSON)
    # Uploaded GLB/GLTF structural model (opaque storage key, never exposed) and parsed metadata
    model_file_key: Mapped[str | None] = mapped_column(String(300))
    model_meta: Mapped[dict | None] = mapped_column(JSON)
    monitoring_status: Mapped[str] = mapped_column(String(30), default="active")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    components: Mapped[list[Component]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class Component(TimestampMixin, Base):
    __tablename__ = "components"
    __table_args__ = (Index("ix_components_asset_type", "asset_id", "component_type"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("components.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    component_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Reference to the 3D object: "proc:<id>" for procedural, or a GLB node name.
    mesh_ref: Mapped[str | None] = mapped_column(String(200))
    # Procedural geometry descriptor rendered by the frontend (box/beam/cable/...).
    geometry: Mapped[dict | None] = mapped_column(JSON)
    model_x: Mapped[float] = mapped_column(Float, default=0.0)
    model_y: Mapped[float] = mapped_column(Float, default=0.0)
    model_z: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[dict | None] = mapped_column(JSON)  # {"min": [x,y,z], "max": [x,y,z]} model coords
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geo_method: Mapped[str | None] = mapped_column(String(40))  # surveyed | derived_uncalibrated | None
    material: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)

    asset: Mapped[Asset] = relationship(back_populates="components")


# --------------------------------------------------------------------------- devices


class Device(TimestampMixin, Base):
    """Generic device registry covering cameras and sensors."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_type: Mapped[str] = mapped_column(String(30), nullable=False)  # camera | accelerometer | sensor_node | environment
    # Measurement channels: acceleration, temperature, humidity, image
    capabilities: Mapped[list | None] = mapped_column(JSON)
    # Per-device options (e.g. transport, camera agent settings)
    config: Mapped[dict | None] = mapped_column(JSON)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hardware_model: Mapped[str | None] = mapped_column(String(100))
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[str | None] = mapped_column(ForeignKey("components.id"), index=True)
    monitored_region: Mapped[str | None] = mapped_column(String(200))
    model_x: Mapped[float] = mapped_column(Float, default=0.0)
    model_y: Mapped[float] = mapped_column(Float, default=0.0)
    model_z: Mapped[float] = mapped_column(Float, default=0.0)
    yaw_deg: Mapped[float] = mapped_column(Float, default=0.0)
    pitch_deg: Mapped[float] = mapped_column(Float, default=0.0)
    roll_deg: Mapped[float] = mapped_column(Float, default=0.0)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # real | simulated. A simulated device is never reported as physically connected.
    data_source: Mapped[str] = mapped_column(String(20), default="real")
    operational_status: Mapped[str] = mapped_column(String(30), default="active")  # active | maintenance | decommissioned
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    firmware_version: Mapped[str | None] = mapped_column(String(60))
    config_version: Mapped[str | None] = mapped_column(String(60))
    sample_rate_hz: Mapped[float | None] = mapped_column(Float)
    # Camera geometry (only meaningful for cameras)
    fov_deg: Mapped[float | None] = mapped_column(Float)
    resolution_w: Mapped[int | None] = mapped_column(Integer)
    resolution_h: Mapped[int | None] = mapped_column(Integer)
    intrinsics: Mapped[dict | None] = mapped_column(JSON)  # {"fx","fy","cx","cy","calibrated": bool}
    stream_url: Mapped[str | None] = mapped_column(String(300))
    token_hash: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- images / inspections


class ImageRecord(Base):
    __tablename__ = "image_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[str | None] = mapped_column(ForeignKey("components.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)  # never exposed via API
    original_filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(60))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    data_source: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded | demo | real
    quality: Mapped[dict | None] = mapped_column(JSON)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (Index("ix_inspections_asset_time", "asset_id", "observed_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[str | None] = mapped_column(ForeignKey("components.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"))
    image_id: Mapped[str | None] = mapped_column(ForeignKey("image_records.id"))
    inspection_type: Mapped[str] = mapped_column(String(30), default="image_upload")  # image_upload | manual | camera_capture
    data_source: Mapped[str] = mapped_column(String(20), default="uploaded")
    # completed | model_unavailable | inference_failed | rejected_quality
    status: Mapped[str] = mapped_column(String(30), default="completed")
    model_id: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(60))
    inference_output: Mapped[dict | None] = mapped_column(JSON)
    inference_ms: Mapped[float | None] = mapped_column(Float)
    performed_by: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# --------------------------------------------------------------------------- defects


class Defect(TimestampMixin, Base):
    __tablename__ = "defects"
    __table_args__ = (
        Index("ix_defects_asset_priority", "asset_id", "priority"),
        Index("ix_defects_asset_status", "asset_id", "review_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[str | None] = mapped_column(ForeignKey("components.id"), index=True)
    inspection_id: Mapped[str | None] = mapped_column(ForeignKey("inspections.id"))
    image_id: Mapped[str | None] = mapped_column(ForeignKey("image_records.id"))
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    detection_source: Mapped[str] = mapped_column(String(30), nullable=False)  # ai_model | manual | sensor_rule
    description: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    model_id: Mapped[str | None] = mapped_column(String(80))
    model_version: Mapped[str | None] = mapped_column(String(60))
    model_label: Mapped[str | None] = mapped_column(String(60))
    model_confidence: Mapped[float | None] = mapped_column(Float)
    # Spatial location
    location_kind: Mapped[str] = mapped_column(String(20), default="component")  # component | surface
    pos_x: Mapped[float | None] = mapped_column(Float)
    pos_y: Mapped[float | None] = mapped_column(Float)
    pos_z: Mapped[float | None] = mapped_column(Float)
    normal_x: Mapped[float | None] = mapped_column(Float)
    normal_y: Mapped[float | None] = mapped_column(Float)
    normal_z: Mapped[float | None] = mapped_column(Float)
    localization_method: Mapped[str] = mapped_column(String(40), default="manual_component")
    location_confidence: Mapped[str] = mapped_column(String(20), default="component_only")
    localization_notes: Mapped[str | None] = mapped_column(Text)
    image_region: Mapped[dict | None] = mapped_column(JSON)  # pixel bbox/polygon in the evidence image
    overlay: Mapped[dict | None] = mapped_column(JSON)  # {"polyline": [[x,y,z],...]} model coords
    measured_extent: Mapped[dict | None] = mapped_column(JSON)  # {"length_mm","width_mm","area_cm2","method"}
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # Review priority (NOT certified structural severity)
    priority: Mapped[str] = mapped_column(String(20), default="unassessed")
    priority_source: Mapped[str] = mapped_column(String(20), default="rules")  # rules | manual
    priority_rationale: Mapped[list | None] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(30), default="new")
    assigned_reviewer: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    follow_up_actions: Mapped[str | None] = mapped_column(Text)
    related_defect_id: Mapped[str | None] = mapped_column(ForeignKey("defects.id"))
    data_source: Mapped[str] = mapped_column(String(20), default="uploaded")


class DefectEvent(Base):
    __tablename__ = "defect_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    defect_id: Mapped[str] = mapped_column(ForeignKey("defects.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    from_value: Mapped[str | None] = mapped_column(String(200))
    to_value: Mapped[str | None] = mapped_column(String(200))
    actor: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# --------------------------------------------------------------------------- sensors


class SensorReading(Base):
    """Raw accelerometer samples. Derived window features live in ``vibration_features``."""

    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_readings_device_ts", "device_id", "source", "ts"),
        Index("ix_readings_device_seq", "device_id", "source", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    component_id: Mapped[str | None] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ax: Mapped[float] = mapped_column(Float)  # g
    ay: Mapped[float] = mapped_column(Float)
    az: Mapped[float] = mapped_column(Float)
    gx: Mapped[float | None] = mapped_column(Float)  # deg/s
    gy: Mapped[float | None] = mapped_column(Float)
    gz: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(20), default="ok")  # ok | suspect | invalid
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # real | uploaded | simulated
    processing_status: Mapped[str] = mapped_column(String(20), default="raw")  # raw | processed
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EnvironmentReading(Base):
    """Ambient temperature / relative humidity samples (e.g. DHT22 on the sensor node)."""

    __tablename__ = "environment_readings"
    __table_args__ = (Index("ix_env_device_ts", "device_id", "source", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    component_id: Mapped[str | None] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    seq: Mapped[int | None] = mapped_column(Integer)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    sensor_model: Mapped[str | None] = mapped_column(String(40))
    quality: Mapped[str] = mapped_column(String(20), default="ok")
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MediaClip(Base):
    """Short video clip around a camera event (stored as a file, referenced by opaque key)."""

    __tablename__ = "media_clips"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), index=True)
    inspection_id: Mapped[str | None] = mapped_column(ForeignKey("inspections.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(60))
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    data_source: Mapped[str] = mapped_column(String(20), default="real")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Baseline(Base):
    __tablename__ = "baselines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime)
    n_windows: Mapped[int] = mapped_column(Integer)
    feature_version: Mapped[str] = mapped_column(String(30))
    rms_dyn_mean: Mapped[float] = mapped_column(Float)
    rms_dyn_std: Mapped[float] = mapped_column(Float)
    peak_dyn_mean: Mapped[float] = mapped_column(Float)
    peak_dyn_std: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class VibrationFeature(Base):
    __tablename__ = "vibration_features"
    __table_args__ = (Index("ix_features_device_window", "device_id", "source", "window_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    component_id: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime)
    window_s: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)
    expected_count: Mapped[int | None] = mapped_column(Integer)
    missing_ratio: Mapped[float | None] = mapped_column(Float)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    gap_count: Mapped[int] = mapped_column(Integer, default=0)
    mean_x: Mapped[float] = mapped_column(Float)
    mean_y: Mapped[float] = mapped_column(Float)
    mean_z: Mapped[float] = mapped_column(Float)
    std_x: Mapped[float] = mapped_column(Float)
    std_y: Mapped[float] = mapped_column(Float)
    std_z: Mapped[float] = mapped_column(Float)
    rms_x: Mapped[float] = mapped_column(Float)
    rms_y: Mapped[float] = mapped_column(Float)
    rms_z: Mapped[float] = mapped_column(Float)
    rms_dyn: Mapped[float] = mapped_column(Float)
    peak_dyn: Mapped[float] = mapped_column(Float)
    feature_version: Mapped[str] = mapped_column(String(30))
    baseline_id: Mapped[str | None] = mapped_column(String(64))
    baseline_version: Mapped[int | None] = mapped_column(Integer)
    baseline_ratio: Mapped[float | None] = mapped_column(Float)
    anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_reasons: Mapped[list | None] = mapped_column(JSON)
    thresholds: Mapped[dict | None] = mapped_column(JSON)
    data_quality: Mapped[str] = mapped_column(String(20), default="ok")  # ok | incomplete | insufficient
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# --------------------------------------------------------------------------- alerts


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    cooldown_s: Mapped[int] = mapped_column(Integer, default=3600)
    params: Mapped[dict | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_asset_status", "asset_id", "status"), Index("ix_alerts_dedup", "dedup_key", "status"))

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("alert_rules.id"))
    rule_type: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[int | None] = mapped_column(Integer)
    rule_snapshot: Mapped[dict | None] = mapped_column(JSON)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    component_id: Mapped[str | None] = mapped_column(String(80), index=True)
    device_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | acknowledged | resolved
    dedup_key: Mapped[str] = mapped_column(String(300))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    follow_up_action: Mapped[str | None] = mapped_column(Text)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    data_source: Mapped[str] = mapped_column(String(20), default="real")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AlertEvidence(Base):
    __tablename__ = "alert_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40))  # defect | image | inspection | vibration_feature | device
    ref_id: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AlertEvent(Base):
    """Audit trail for alert status changes."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    actor: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# --------------------------------------------------------------------------- history / reports / config


class EventLog(Base):
    """Asset-level timeline of everything that happened (inspections, findings, alerts, config)."""

    __tablename__ = "event_log"
    __table_args__ = (Index("ix_event_log_asset_ts", "asset_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str | None] = mapped_column(String(64))
    component_id: Mapped[str | None] = mapped_column(String(80), index=True)
    device_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    ref_type: Mapped[str | None] = mapped_column(String(40))
    ref_id: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[str | None] = mapped_column(String(20))
    data_source: Mapped[str | None] = mapped_column(String(20))
    actor: Mapped[str | None] = mapped_column(String(100))
    data: Mapped[dict | None] = mapped_column(JSON)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[datetime] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime)
    storage_key: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    generated_by: Mapped[str | None] = mapped_column(String(100))
    params: Mapped[dict | None] = mapped_column(JSON)
    summary: Mapped[dict | None] = mapped_column(JSON)
    includes_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ModelRecord(Base):
    """Model registry: provenance and recorded evaluation of installed inference models."""

    __tablename__ = "model_registry"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    task: Mapped[str] = mapped_column(String(30))  # classification | detection | segmentation
    categories: Mapped[list | None] = mapped_column(JSON)
    version: Mapped[str] = mapped_column(String(60))
    framework: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))  # installed | missing_file | invalid
    threshold: Mapped[float | None] = mapped_column(Float)
    dataset: Mapped[dict | None] = mapped_column(JSON)
    preprocessing: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    model_card: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RULResult(Base):
    __tablename__ = "rul_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    component_id: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))  # unavailable | estimated
    estimate: Mapped[float | None] = mapped_column(Float)
    units: Mapped[str | None] = mapped_column(String(30))
    horizon: Mapped[str | None] = mapped_column(String(60))
    interval_low: Mapped[float | None] = mapped_column(Float)
    interval_high: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str | None] = mapped_column(String(60))
    input_coverage: Mapped[dict | None] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(String(40))
    limitations: Mapped[list | None] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
