// API contract v1 types (mirror backend/app/schemas.py)
export type Priority = "unassessed" | "low" | "medium" | "high" | "critical";
export type DataSource = "real" | "uploaded" | "simulated" | "demo";
export type ReviewStatus = "new" | "under_review" | "confirmed" | "monitoring" | "false_positive" | "repaired" | "closed";
export type Vec3 = [number, number, number];

export interface Asset {
  id: string; name: string; asset_type: string; description: string | null;
  latitude: number | null; longitude: number | null; site_description: string | null; commissioning_date: string | null;
  model_kind: string; model_ref: string | null; geo_transform: Record<string, unknown> | null;
  monitoring_status: string; is_demo: boolean; created_at: string; updated_at: string;
  model_meta: { filename?: string; size_bytes?: number; uploaded_at?: string; nodes?: number; mesh_nodes?: number;
    bounds?: { min: Vec3; max: Vec3 } | null; generator?: string | null; convention?: string } | null;
}

export type Geometry =
  | { type: "group" }
  | { type: "box"; size: Vec3 }
  | { type: "beam"; start: Vec3; end: Vec3; section: [number, number] }
  | { type: "cable"; start: Vec3; end: Vec3; radius: number }
  | { type: "gltf_node"; source: "gltf"; node: number };

export interface Component {
  id: string; asset_id: string; parent_id: string | null; name: string; component_type: string; mesh_ref: string | null;
  geometry: Geometry | null; model_x: number; model_y: number; model_z: number;
  bbox: { min: Vec3; max: Vec3 } | null; latitude: number | null; longitude: number | null; geo_method: string | null;
  material: string | null; notes: string | null;
}

export interface Connection {
  status: "online" | "stale" | "offline" | "never_connected" | "simulated" | "simulated_idle" | "maintenance" | "decommissioned";
  label: string; age_s: number | null; physically_connected: boolean; is_simulated: boolean;
}

export type Capability = "acceleration" | "temperature" | "humidity" | "image";
export interface DeviceStatusReport { fw?: string; rssi?: number; uptime_s?: number; ip?: string; mpu_ok?: boolean; env_ok?: boolean; free_heap?: number; received_at?: string; [k: string]: unknown }

export interface Device {
  id: string; device_type: "camera" | "accelerometer" | "sensor_node" | "environment"; name: string;
  capabilities: Capability[] | null; config: { last_status?: DeviceStatusReport; transport?: string; [k: string]: unknown } | null; hardware_model: string | null; asset_id: string;
  component_id: string | null; monitored_region: string | null; model_x: number; model_y: number; model_z: number;
  yaw_deg: number; pitch_deg: number; roll_deg: number; latitude: number | null; longitude: number | null;
  data_source: "real" | "simulated"; operational_status: string; last_seen_at: string | null; firmware_version: string | null;
  config_version: string | null; sample_rate_hz: number | null; fov_deg: number | null; resolution_w: number | null;
  resolution_h: number | null; intrinsics: Record<string, unknown> | null; stream_url: string | null; notes: string | null;
  created_at: string; connection: Connection | null;
}

export interface PriorityRationale { rule: string; effect: string; detail: string; refs?: string[] }

export interface Defect {
  id: string; asset_id: string; component_id: string | null; inspection_id: string | null; image_id: string | null;
  category: string; detection_source: string; description: string | null; observed_at: string;
  model_id: string | null; model_version: string | null; model_label: string | null; model_confidence: number | null;
  location_kind: "component" | "surface"; pos_x: number | null; pos_y: number | null; pos_z: number | null;
  normal_x: number | null; normal_y: number | null; normal_z: number | null; localization_method: string;
  location_confidence: string; localization_notes: string | null; image_region: Record<string, unknown> | null;
  overlay: { polyline?: Vec3[] } | null; measured_extent: Record<string, unknown> | null; latitude: number | null; longitude: number | null;
  priority: Priority; priority_source: "rules" | "manual"; priority_rationale: PriorityRationale[] | null;
  review_status: ReviewStatus; assigned_reviewer: string | null; notes: string | null; follow_up_actions: string | null;
  related_defect_id: string | null; data_source: DataSource; created_at: string; updated_at: string;
}

export interface ImageRec {
  id: string; asset_id: string; component_id: string | null; device_id: string | null; original_filename: string | null;
  content_type: string; width: number; height: number; size_bytes: number; sha256: string; data_source: DataSource;
  quality: { issues: string[]; ok: boolean; laplacian_variance: number; mean_brightness: number; contrast_std: number; method: string } | null;
  captured_at: string | null; created_at: string;
}

export interface Inspection {
  id: string; asset_id: string; component_id: string | null; device_id: string | null; image_id: string | null;
  inspection_type: string; data_source: DataSource; status: string; model_id: string | null; model_version: string | null;
  inference_output: Record<string, any> | null; inference_ms: number | null; performed_by: string | null; notes: string | null;
  observed_at: string; created_at: string; defect_count?: number;
}

export interface DefectEvent { id: number; event_type: string; from_value: string | null; to_value: string | null; actor: string | null; note: string | null; created_at: string }

export interface Clip { id: string; inspection_id: string | null; device_id: string | null; content_type: string; size_bytes: number; duration_s: number | null; started_at: string | null; data_source: string; created_at: string; url: string }

export interface EnvPoint { t: string; source: string; n: number; temp_mean: number | null; temp_min: number | null; temp_max: number | null; rh_mean: number | null; rh_max: number | null; dew_point_mean: number | null; zero_crossings: number }
export interface EnvSeries {
  device_id: string; note: string; series: EnvPoint[];
  sensor_spec: { temp_accuracy_c: number; rh_accuracy_pct: number; resolution: string; temp_range_c: [number, number]; rh_range_pct: [number, number] } | null;
  latest: { ts: string; temperature_c: number | null; humidity_pct: number | null; sensor_model: string | null; quality: string; source: string; dew_point_c: number | null; age_s: number } | null;
}

export interface MqttStatus {
  enabled: boolean; state: string; broker: string; topic: string; last_error: string | null; connected_since: string | null; auth: string;
  counts: { received: number; accepted: number; rejected: number };
  recent: { ts: string; topic: string; bytes: number; device_id: string | null; outcome: string; detail: string }[];
}

export interface DefectDetail {
  clips?: Clip[];
  defect: Defect; component: { id: string; name: string; component_type: string } | null; image: ImageRec | null;
  inspection: Inspection | null; camera: { id: string; name: string } | null; events: DefectEvent[]; related: Defect[]; alert_ids: string[];
}

export interface Alert {
  id: string; rule_id: string | null; rule_type: string; rule_version: number | null; rule_snapshot: Record<string, any> | null;
  asset_id: string; component_id: string | null; device_id: string | null; title: string; message: string | null;
  priority: Priority; status: "open" | "acknowledged" | "resolved"; dedup_key: string; occurrence_count: number;
  first_seen_at: string; last_seen_at: string; acknowledged_by: string | null; acknowledged_at: string | null;
  assigned_to: string | null; follow_up_action: string | null; resolution_notes: string | null; resolved_by: string | null;
  resolved_at: string | null; data_source: string; created_at: string;
}
export interface AlertEvidence { id: number; evidence_type: string; ref_id: string | null; summary: string | null; data: Record<string, any> | null; created_at: string }
export interface AlertEvent { id: number; event_type: string; from_status: string | null; to_status: string | null; actor: string | null; note: string | null; created_at: string }
export interface AlertDetail { alert: Alert; evidence: AlertEvidence[]; history: AlertEvent[] }

export interface AlertRule { id: string; rule_type: string; name: string; description: string | null; enabled: boolean; priority: Priority; cooldown_s: number; params: Record<string, any> | null; version: number; updated_at: string }

export interface EventLog {
  id: number; asset_id: string | null; component_id: string | null; device_id: string | null; event_type: string; title: string;
  ref_type: string | null; ref_id: string | null; priority: Priority | null; data_source: string | null; actor: string | null;
  data: Record<string, any> | null; ts: string;
}

export interface Summary {
  asset_id: string; components: number; inspections: number; inspections_last_30d: number; latest_inspection_at: string | null;
  open_findings: number; open_by_priority: Partial<Record<Priority, number>>; high_priority_reviews: number;
  devices_total: number; devices_online_real: number; devices_stale: number; devices_offline: number; devices_never_connected: number;
  devices_simulated: number; alerts_open: number; alerts_acknowledged: number; alerts_high_unresolved: number;
  finding_sources: Record<string, number>;
}

export interface Reading { ts: string; seq: number; ax: number; ay: number; az: number; gx: number | null; gy: number | null; gz: number | null; temperature_c: number | null; quality: string; source: string; processing_status: string }

export interface Feature {
  id: number; device_id: string; component_id: string | null; source: string; window_start: string; window_end: string; window_s: number;
  sample_count: number; expected_count: number | null; missing_ratio: number | null; duplicate_count: number; gap_count: number;
  mean_x: number; mean_y: number; mean_z: number; std_x: number; std_y: number; std_z: number; rms_x: number; rms_y: number; rms_z: number;
  rms_dyn: number; peak_dyn: number; feature_version: string; baseline_id: string | null; baseline_version: number | null;
  baseline_ratio: number | null; anomaly: boolean; anomaly_reasons: string[] | null; thresholds: Record<string, any> | null; data_quality: string;
}

export interface Baseline {
  id: string; device_id: string; version: number; source: string; window_start: string; window_end: string; n_windows: number;
  feature_version: string; rms_dyn_mean: number; rms_dyn_std: number; peak_dyn_mean: number; peak_dyn_std: number;
  active: boolean; notes: string | null; created_by: string | null; created_at: string;
}

export interface Report { id: string; asset_id: string; period_start: string; period_end: string; size_bytes: number; generated_by: string | null; summary: Record<string, any> | null; includes_simulated: boolean; generated_at: string }

export interface ModelRec { id: string; name: string; task: string; categories: string[] | null; version: string; framework: string; status: string; threshold: number | null; dataset: Record<string, any> | null; preprocessing: Record<string, any> | null; metrics: Record<string, any> | null; is_active: boolean; registered_at: string }

export interface RULResult { id: string; asset_id: string; component_id: string | null; status: string; estimate: number | null; units: string | null; horizon: string | null; interval_low: number | null; interval_high: number | null; model_version: string | null; input_coverage: Record<string, any> | null; validation_status: string; limitations: string[] | null; message: string | null; created_at: string }

export interface SystemStatus {
  app: string; environment: string; api_version: string; database: { ok: boolean; dialect: string };
  storage: { ok: boolean; files?: number; bytes?: number; disk_free_bytes?: number; writable?: boolean; error?: string };
  models: { available: boolean; loaded: { id: string; version: string; task: string; categories: string[] }[]; errors: Record<string, string>; ai_supported_categories: string[] };
  data_source: { mode: "real" | "uploaded" | "simulated" | "all" }; simulation: { live_enabled: boolean; sample_rate_hz: number };
  readings_by_source: Record<string, number>; features_by_source: Record<string, number>; real_data_configured: boolean;
  last_real_reading_received_at: string | null; device_auth_required: boolean; shared_device_key_configured: boolean;
  background_enabled: boolean; max_upload_mb: number;
  mqtt: { enabled: boolean; state: string; broker: string; last_error: string | null; counts: { received: number; accepted: number; rejected: number } }; security: { user_authentication: string; note: string };
  categories: string[]; priority_levels: Priority[];
}

export interface ComponentDetail {
  component: Component; children: Component[]; devices: Device[]; defects: Defect[]; inspections: Inspection[];
  geo: { latitude: number; longitude: number; method: string; calibrated?: boolean } | null; coordinate_note: string;
}
