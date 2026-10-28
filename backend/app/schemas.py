"""Pydantic request/response schemas (API contract v1)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Priority = Literal["unassessed", "low", "medium", "high", "critical"]
Category = Literal["suspected_crack", "suspected_corrosion", "exposed_reinforcement", "vibration_anomaly", "surface_deformation", "other", "unclassified"]
ReviewStatus = Literal["new", "under_review", "confirmed", "monitoring", "false_positive", "repaired", "closed"]
LocMethod = Literal["manual_component", "manual_surface_pick", "camera_ray_aabb", "photogrammetry", "survey"]


class Schema(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class ORM(Schema):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


# ------------------------------------------------------------------ assets / components


class GeoTransform(Schema):
    origin_lat: float = Field(ge=-90, le=90)
    origin_lon: float = Field(ge=-180, le=180)
    origin_alt_m: float | None = None
    heading_deg: float = 0.0
    scale: float = Field(1.0, gt=0)
    calibrated: bool = False
    method: str = "manual_uncalibrated"


class AssetIn(Schema):
    id: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-]{2,64}$")
    name: str = Field(min_length=1, max_length=200)
    asset_type: Literal["bridge", "flyover", "dam", "building", "tunnel", "tower", "other"] = "bridge"
    description: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    site_description: str | None = None
    commissioning_date: date | None = None
    model_kind: Literal["procedural", "gltf", "none"] = "none"
    model_ref: str | None = None
    geo_transform: GeoTransform | None = None
    monitoring_status: str = "planned"


class AssetPatch(Schema):
    name: str | None = None
    description: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    site_description: str | None = None
    commissioning_date: date | None = None
    model_ref: str | None = None
    geo_transform: GeoTransform | None = None
    monitoring_status: str | None = None


class AssetOut(ORM):
    id: str
    name: str
    asset_type: str
    description: str | None
    latitude: float | None
    longitude: float | None
    site_description: str | None
    commissioning_date: date | None
    model_kind: str
    model_ref: str | None
    geo_transform: dict | None
    monitoring_status: str
    is_demo: bool
    created_at: datetime
    updated_at: datetime


class ComponentIn(Schema):
    id: str = Field(pattern=r"^[A-Za-z0-9_\-:.]{1,80}$")
    name: str
    component_type: str
    parent_id: str | None = None
    mesh_ref: str | None = None
    geometry: dict | None = None
    model_x: float = 0
    model_y: float = 0
    model_z: float = 0
    bbox: dict | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    geo_method: str | None = None
    material: str | None = None
    notes: str | None = None


class ComponentPatch(Schema):
    name: str | None = None
    mesh_ref: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    geo_method: str | None = None
    material: str | None = None
    notes: str | None = None


class ComponentOut(ORM):
    id: str
    asset_id: str
    parent_id: str | None
    name: str
    component_type: str
    mesh_ref: str | None
    geometry: dict | None
    model_x: float
    model_y: float
    model_z: float
    bbox: dict | None
    latitude: float | None
    longitude: float | None
    geo_method: str | None
    material: str | None
    notes: str | None


# ------------------------------------------------------------------ devices


class DeviceIn(Schema):
    id: str = Field(pattern=r"^[A-Za-z0-9_\-]{2,64}$")
    device_type: Literal["camera", "accelerometer"]
    name: str = Field(min_length=1, max_length=200)
    hardware_model: str | None = None
    asset_id: str
    component_id: str | None = None
    monitored_region: str | None = None
    model_x: float = 0
    model_y: float = 0
    model_z: float = 0
    yaw_deg: float = 0
    pitch_deg: float = 0
    roll_deg: float = 0
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    data_source: Literal["real", "simulated"] = "real"
    sample_rate_hz: float | None = Field(None, gt=0, le=2000)
    firmware_version: str | None = None
    config_version: str | None = None
    fov_deg: float | None = Field(None, gt=1, lt=179)
    resolution_w: int | None = Field(None, gt=0)
    resolution_h: int | None = Field(None, gt=0)
    intrinsics: dict | None = None
    stream_url: str | None = None
    notes: str | None = None


class DevicePatch(Schema):
    name: str | None = None
    hardware_model: str | None = None
    component_id: str | None = None
    monitored_region: str | None = None
    model_x: float | None = None
    model_y: float | None = None
    model_z: float | None = None
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    operational_status: Literal["active", "maintenance", "decommissioned"] | None = None
    sample_rate_hz: float | None = Field(None, gt=0, le=2000)
    firmware_version: str | None = None
    config_version: str | None = None
    fov_deg: float | None = Field(None, gt=1, lt=179)
    resolution_w: int | None = None
    resolution_h: int | None = None
    intrinsics: dict | None = None
    stream_url: str | None = None
    notes: str | None = None


class DeviceOut(ORM):
    id: str
    device_type: str
    name: str
    hardware_model: str | None
    asset_id: str
    component_id: str | None
    monitored_region: str | None
    model_x: float
    model_y: float
    model_z: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    latitude: float | None
    longitude: float | None
    data_source: str
    operational_status: str
    last_seen_at: datetime | None
    firmware_version: str | None
    config_version: str | None
    sample_rate_hz: float | None
    fov_deg: float | None
    resolution_w: int | None
    resolution_h: int | None
    intrinsics: dict | None
    stream_url: str | None
    notes: str | None
    created_at: datetime
    connection: dict | None = None


# ------------------------------------------------------------------ sensor ingestion


class ReadingIn(Schema):
    seq: int = Field(ge=0)
    ts: datetime | None = None
    ax: float
    ay: float
    az: float
    gx: float | None = None
    gy: float | None = None
    gz: float | None = None
    temperature_c: float | None = None


class ReadingBatchIn(Schema):
    device_id: str
    firmware_version: str | None = None
    readings: list[dict[str, Any]] = Field(min_length=1)


class ReadingOut(ORM):
    ts: datetime
    seq: int
    ax: float
    ay: float
    az: float
    gx: float | None
    gy: float | None
    gz: float | None
    temperature_c: float | None
    quality: str
    source: str
    processing_status: str


class FeatureOut(ORM):
    id: int
    device_id: str
    component_id: str | None
    source: str
    window_start: datetime
    window_end: datetime
    window_s: float
    sample_count: int
    expected_count: int | None
    missing_ratio: float | None
    duplicate_count: int
    gap_count: int
    mean_x: float
    mean_y: float
    mean_z: float
    std_x: float
    std_y: float
    std_z: float
    rms_x: float
    rms_y: float
    rms_z: float
    rms_dyn: float
    peak_dyn: float
    feature_version: str
    baseline_id: str | None
    baseline_version: int | None
    baseline_ratio: float | None
    anomaly: bool
    anomaly_reasons: list | None
    thresholds: dict | None
    data_quality: str


class BaselineIn(Schema):
    source: Literal["real", "uploaded", "simulated"]
    window_start: datetime
    window_end: datetime
    notes: str | None = None
    actor: str | None = None


class BaselineOut(ORM):
    id: str
    device_id: str
    version: int
    source: str
    window_start: datetime
    window_end: datetime
    n_windows: int
    feature_version: str
    rms_dyn_mean: float
    rms_dyn_std: float
    peak_dyn_mean: float
    peak_dyn_std: float
    active: bool
    notes: str | None
    created_by: str | None
    created_at: datetime


class SimulationGenerateIn(Schema):
    device_id: str | None = None
    minutes: float = Field(10, gt=0, le=240)
    inject_anomaly: bool = False


# ------------------------------------------------------------------ inspections / defects


class ImageOut(ORM):
    id: str
    asset_id: str
    component_id: str | None
    device_id: str | None
    original_filename: str | None
    content_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    data_source: str
    quality: dict | None
    captured_at: datetime | None
    created_at: datetime


class InspectionOut(ORM):
    id: str
    asset_id: str
    component_id: str | None
    device_id: str | None
    image_id: str | None
    inspection_type: str
    data_source: str
    status: str
    model_id: str | None
    model_version: str | None
    inference_output: dict | None
    inference_ms: float | None
    performed_by: str | None
    notes: str | None
    observed_at: datetime
    created_at: datetime


class DefectIn(Schema):
    asset_id: str
    component_id: str | None = None
    inspection_id: str | None = None
    image_id: str | None = None
    category: Category
    description: str | None = Field(None, max_length=4000)
    observed_at: datetime | None = None
    location_kind: Literal["component", "surface"] = "component"
    pos_x: float | None = None
    pos_y: float | None = None
    pos_z: float | None = None
    normal_x: float | None = None
    normal_y: float | None = None
    normal_z: float | None = None
    localization_method: LocMethod = "manual_component"
    localization_notes: str | None = None
    image_region: dict | None = None
    measured_extent: dict | None = None
    priority: Priority | Literal["auto"] = "auto"
    assigned_reviewer: str | None = None
    notes: str | None = None
    follow_up_actions: str | None = None
    actor: str | None = None

    @field_validator("measured_extent")
    @classmethod
    def _extent(cls, v):
        if v is not None and not v.get("method"):
            raise ValueError("measured_extent must state the measurement 'method'")
        return v


class DefectPatch(Schema):
    review_status: ReviewStatus | None = None
    priority: Priority | Literal["auto"] | None = None
    assigned_reviewer: str | None = None
    notes: str | None = None
    follow_up_actions: str | None = None
    description: str | None = None
    component_id: str | None = None
    category: Category | None = None
    location_kind: Literal["component", "surface"] | None = None
    pos_x: float | None = None
    pos_y: float | None = None
    pos_z: float | None = None
    normal_x: float | None = None
    normal_y: float | None = None
    normal_z: float | None = None
    localization_method: LocMethod | None = None
    localization_notes: str | None = None
    measured_extent: dict | None = None
    actor: str | None = None


class DefectOut(ORM):
    id: str
    asset_id: str
    component_id: str | None
    inspection_id: str | None
    image_id: str | None
    category: str
    detection_source: str
    description: str | None
    observed_at: datetime
    model_id: str | None
    model_version: str | None
    model_label: str | None
    model_confidence: float | None
    location_kind: str
    pos_x: float | None
    pos_y: float | None
    pos_z: float | None
    normal_x: float | None
    normal_y: float | None
    normal_z: float | None
    localization_method: str
    location_confidence: str
    localization_notes: str | None
    image_region: dict | None
    overlay: dict | None
    measured_extent: dict | None
    priority: str
    priority_source: str
    priority_rationale: list | None
    review_status: str
    assigned_reviewer: str | None
    notes: str | None
    follow_up_actions: str | None
    related_defect_id: str | None
    data_source: str
    created_at: datetime
    updated_at: datetime


class DefectEventOut(ORM):
    id: int
    event_type: str
    from_value: str | None
    to_value: str | None
    actor: str | None
    note: str | None
    created_at: datetime


class ProjectionIn(Schema):
    camera_id: str
    component_id: str
    u: float = Field(ge=0)
    v: float = Field(ge=0)


# ------------------------------------------------------------------ alerts


class AlertOut(ORM):
    id: str
    rule_id: str | None
    rule_type: str
    rule_version: int | None
    rule_snapshot: dict | None
    asset_id: str
    component_id: str | None
    device_id: str | None
    title: str
    message: str | None
    priority: str
    status: str
    dedup_key: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    assigned_to: str | None
    follow_up_action: str | None
    resolution_notes: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    data_source: str
    created_at: datetime


class AlertEvidenceOut(ORM):
    id: int
    evidence_type: str
    ref_id: str | None
    summary: str | None
    data: dict | None
    created_at: datetime


class AlertEventOut(ORM):
    id: int
    event_type: str
    from_status: str | None
    to_status: str | None
    actor: str | None
    note: str | None
    created_at: datetime


class AlertActionIn(Schema):
    actor: str = Field(min_length=1, max_length=100)
    note: str | None = Field(None, max_length=4000)
    assigned_to: str | None = None


class AlertRuleOut(ORM):
    id: str
    rule_type: str
    name: str
    description: str | None
    enabled: bool
    priority: str
    cooldown_s: int
    params: dict | None
    version: int
    updated_at: datetime


class AlertRulePatch(Schema):
    enabled: bool | None = None
    priority: Priority | None = None
    cooldown_s: int | None = Field(None, ge=0, le=30 * 86400)
    params: dict | None = None
    actor: str | None = None


# ------------------------------------------------------------------ events / reports / misc


class EventOut(ORM):
    id: int
    asset_id: str | None
    component_id: str | None
    device_id: str | None
    event_type: str
    title: str
    ref_type: str | None
    ref_id: str | None
    priority: str | None
    data_source: str | None
    actor: str | None
    data: dict | None
    ts: datetime


class ReportIn(Schema):
    asset_id: str
    period_start: datetime
    period_end: datetime
    actor: str | None = None


class ReportOut(ORM):
    id: str
    asset_id: str
    period_start: datetime
    period_end: datetime
    size_bytes: int
    generated_by: str | None
    summary: dict | None
    includes_simulated: bool
    generated_at: datetime


class ModelOut(ORM):
    id: str
    name: str
    task: str
    categories: list | None
    version: str
    framework: str
    status: str
    threshold: float | None
    dataset: dict | None
    preprocessing: dict | None
    metrics: dict | None
    is_active: bool
    registered_at: datetime


class RULIn(Schema):
    asset_id: str
    component_id: str | None = None


class RULOut(ORM):
    id: str
    asset_id: str
    component_id: str | None
    status: str
    estimate: float | None
    units: str | None
    horizon: str | None
    interval_low: float | None
    interval_high: float | None
    model_version: str | None
    input_coverage: dict | None
    validation_status: str
    limitations: list | None
    message: str | None
    created_at: datetime


class SettingIn(Schema):
    value: Any
    actor: str | None = None
