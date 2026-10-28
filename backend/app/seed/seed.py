"""Seeds the clearly-labelled demonstration dataset.

Everything created here is marked as demo/simulated:
* the asset is ``is_demo=True`` and its 3D model is procedural;
* images are synthetic (watermarked) with ``data_source='demo'``;
* findings are entered as *manual* demo findings (no AI model is shipped);
* devices are registered as ``data_source='simulated'`` and never shown as connected;
* sensor data comes from the simulation provider (``source='simulated'``).
Alerts are produced by running the real alert engine on these records.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Alert, Asset, Component, Device
from app.seed.demo_bridge import ASSET_ID, build_components
from app.seed.demo_images import generate_demo_image
from app.services import alert_engine, simulation, vibration
from app.services.imaging import validate_image
from app.services.operations import create_defect, run_image_inspection
from app.services.settings_store import get_setting, set_setting
from app.services.spatial import look_at_angles, project_pixel_to_component
from app.timeutil import utcnow

log = logging.getLogger(__name__)

SENSORS = [
    # id, name, component, position
    ("ACC-01", "Accelerometer — west side span", "DECK-S03", (-140.0, 26.9, 10.0)),
    ("ACC-02", "Accelerometer — main span west quarter", "DECK-S06", (-50.0, 26.9, 10.0)),
    ("ACC-03", "Accelerometer — main span midspan", "DECK-S09", (5.0, 26.9, 10.0)),
    ("ACC-04", "Accelerometer — main span east quarter", "DECK-S11", (50.0, 26.9, 10.0)),
    ("ACC-05", "Accelerometer — west pylon top", "TWR-W-XB-UP", (-100.0, 101.6, 0.0)),
    ("ACC-06", "Accelerometer — east pier cap", "PIER-E-CAP", (150.0, 25.5, 0.0)),
]

CAMERAS = [
    ("CAM-01", "Camera — west pylon, main span girder", "GIR-M-S", (-96.0, 24.0, 16.0), (-60.0, 28.0, 11.0)),
    ("CAM-02", "Camera — east pier, column inspection", "PIER-E-COL-S", (165.0, 8.0, 22.0), (150.0, 10.0, 8.0)),
    ("CAM-03", "Camera — midspan deck soffit", "DECK-S09", (10.0, 20.0, 18.0), (8.0, 29.2, 3.0)),
    ("CAM-04", "Camera — west pylon leg", "TWR-W-LEG-S", (-80.0, 32.0, 30.0), (-100.0, 40.0, 14.0)),
]


def seed_demo(db: Session, sim_minutes_baseline: int = 60, sim_minutes_recent: int = 30) -> bool:
    alert_engine.ensure_default_rules(db)
    if db.get(Asset, ASSET_ID):
        return False
    log.info("Seeding demonstration dataset")
    now = utcnow()
    asset = Asset(
        id=ASSET_ID, name="Demonstration Cable-Stayed Bridge", asset_type="bridge", is_demo=True,
        description="Procedurally generated cable-stayed bridge used for development and demonstration. "
                    "Not a model of any real structure; all associated data is synthetic or simulated.",
        site_description="Fictional river crossing (no geographic location).", model_kind="procedural", model_ref="procedural:cable-stayed-v1",
        geo_transform=None, monitoring_status="demonstration",
    )
    db.add(asset)
    for c in build_components():
        ctr = c["center"] or [0, 0, 0]
        db.add(Component(
            id=c["id"], asset_id=ASSET_ID, parent_id=c["parent_id"], name=c["name"], component_type=c["component_type"],
            mesh_ref=f"proc:{c['id']}", geometry=c["geometry"], model_x=ctr[0], model_y=ctr[1], model_z=ctr[2], bbox=c["bbox"],
            material=c.get("material"),
        ))
    db.flush()

    for did, name, comp, pos in SENSORS:
        db.add(Device(id=did, device_type="accelerometer", name=name, hardware_model="MPU6050 (simulated)", asset_id=ASSET_ID,
                      component_id=comp, model_x=pos[0], model_y=pos[1], model_z=pos[2], data_source="simulated", sample_rate_hz=10.0,
                      firmware_version=None, config_version="sim-1", notes="Simulated device: no physical hardware."))
    for cid, name, comp, pos, target in CAMERAS:
        yaw, pitch = look_at_angles(pos, target)
        db.add(Device(id=cid, device_type="camera", name=name, hardware_model="Unspecified (demo registration)", asset_id=ASSET_ID,
                      component_id=comp, model_x=pos[0], model_y=pos[1], model_z=pos[2], yaw_deg=yaw, pitch_deg=pitch,
                      data_source="simulated", fov_deg=40.0, resolution_w=1920, resolution_h=1080,
                      intrinsics={"calibrated": False, "note": "nominal FOV only"},
                      notes="Demo camera registration; no physical camera or stream is connected."))
    db.flush()

    _seed_vibration(db, now, sim_minutes_baseline, sim_minutes_recent)
    _seed_inspections(db, now)
    set_setting(db, "simulation", {**get_setting(db, "simulation"), "live_enabled": True}, actor="seed")
    db.flush()
    return True


def _seed_vibration(db: Session, now, base_min: int, recent_min: int) -> None:
    t0 = now - timedelta(minutes=base_min + recent_min)
    t1 = now - timedelta(minutes=recent_min)
    sensors = db.query(Device).filter(Device.device_type == "accelerometer").all()
    for i, dev in enumerate(sensors):
        simulation.generate(db, dev, t0, t1, seed=100 + i)
        vibration.process_device(db, dev, "simulated", t1)
        vibration.create_baseline(db, dev, "simulated", t0, t1, actor="seed", notes="Demo baseline from simulated data.")
    for i, dev in enumerate(sensors):
        anomalies = []
        if dev.id == "ACC-03":
            a0 = now - timedelta(minutes=max(recent_min - 10, 1))
            anomalies = [(a0, a0 + timedelta(minutes=3))]
        simulation.generate(db, dev, t1, now, anomaly_windows=anomalies, seed=200 + i)
        vibration.process_device(db, dev, "simulated", now, on_anomaly=alert_engine.on_feature_anomaly)


def _inspect(db, variant, seed, comp, when, device=None):
    data, _ = generate_demo_image(variant, seed)
    img = validate_image(data)
    insp, _ = run_image_inspection(db, img, asset_id=ASSET_ID, component_id=comp, device_id=device, data_source="demo",
                                   original_filename=f"synthetic_{variant}_{seed}.png", observed_at=when, performed_by="demo-seed",
                                   notes="Synthetic demonstration image.")
    return insp


def _demo_defect(db, insp, **kw):
    base = {"asset_id": ASSET_ID, "inspection_id": insp.id if insp else None, "image_id": insp.image_id if insp else None,
            "detection_source": "manual", "data_source": "demo", "observed_at": kw.get("observed_at"), "created_at": kw.get("observed_at")}
    base.update(kw)
    base["description"] = "DEMO — " + kw.get("description", "")
    return create_defect(db, base, actor="demo-seed")


def _seed_inspections(db: Session, now) -> None:
    d = lambda days, hours=0: now - timedelta(days=days, hours=hours)  # noqa: E731
    # Repeated crack observations on the midspan deck soffit
    for days, off, seed in ((100, 0.0, 11), (40, 0.4, 12), (0, 0.7, 13)):
        when = d(days, 0.2 if days == 0 else 0)
        insp = _inspect(db, "crack", seed, "DECK-S09", when, "CAM-03")
        _demo_defect(db, insp, component_id="DECK-S09", category="suspected_crack", observed_at=when, location_kind="surface",
                     pos_x=8.0 + off, pos_y=29.2, pos_z=3.0 + off / 2, normal_x=0, normal_y=-1, normal_z=0,
                     localization_method="manual_surface_pick", localization_notes="Approximate point picked on the 3D model by the demo seeder.",
                     overlay={"polyline": [[7.0 + off, 29.18, 2.2], [8.0 + off, 29.18, 3.0 + off / 2], [9.2 + off * 1.3, 29.18, 3.6 + off]]},
                     description="Hairline crack-like line on deck soffit (synthetic image).")
    # Bearing corrosion — earlier finding repaired, newer one open
    insp = _inspect(db, "corrosion", 21, "BRG-PIER-W-N", d(75))
    old = _demo_defect(db, insp, component_id="BRG-PIER-W-N", category="suspected_corrosion", observed_at=d(75),
                       description="Rust staining around bearing plate.")
    old.review_status = "repaired"
    old.follow_up_actions = "DEMO: bearing cleaned and recoated (fictional record)."
    insp = _inspect(db, "corrosion", 22, "BRG-PIER-W-N", d(20))
    _demo_defect(db, insp, component_id="BRG-PIER-W-N", category="suspected_corrosion", observed_at=d(20),
                 description="Renewed staining at bearing plate.", related_defect_id=old.id)
    # Exposed reinforcement on east pier column (surface)
    insp = _inspect(db, "exposed_rebar", 31, "PIER-E-COL-S", d(12), "CAM-02")
    _demo_defect(db, insp, component_id="PIER-E-COL-S", category="exposed_reinforcement", observed_at=d(12), location_kind="surface",
                 pos_x=150.0, pos_y=10.0, pos_z=9.5, normal_x=0, normal_y=0, normal_z=1, localization_method="manual_surface_pick",
                 description="Spalled cover with exposed bars (synthetic image).", follow_up_actions="Schedule hands-on inspection.")
    # Pylon leg crack (surface)
    insp = _inspect(db, "crack", 41, "TWR-W-LEG-S", d(6), "CAM-04")
    _demo_defect(db, insp, component_id="TWR-W-LEG-S", category="suspected_crack", observed_at=d(6), location_kind="surface",
                 pos_x=-98.0, pos_y=40.0, pos_z=13.8, normal_x=1, normal_y=0, normal_z=0, localization_method="manual_surface_pick",
                 description="Crack-like line on pylon leg face (synthetic image).")
    # Girder finding localised by projecting a pixel from CAM-01 onto the girder bounding box
    cam = db.get(Device, "CAM-01")
    girder = db.get(Component, "GIR-M-S")
    proj = project_pixel_to_component(cam, girder, 960, 540)
    insp = _inspect(db, "crack", 51, "GIR-M-S", d(3), "CAM-01")
    _demo_defect(db, insp, component_id="GIR-M-S", category="suspected_crack", observed_at=d(3), location_kind="surface",
                 pos_x=proj["position"][0], pos_y=proj["position"][1], pos_z=proj["position"][2],
                 normal_x=proj["normal"][0], normal_y=proj["normal"][1], normal_z=proj["normal"][2],
                 localization_method="camera_ray_aabb", location_confidence=proj["location_confidence"], localization_notes=proj["notes"],
                 image_region={"point_px": [960, 540]}, description="Crack-like feature on main girder web (synthetic image).")
    # Component-level only
    _demo_defect(db, None, component_id="ABT-E", category="surface_deformation", observed_at=d(30),
                 description="Reported settlement at approach slab (manual observation, no image).")
    insp = _inspect(db, "clean", 61, "DECK-S03", d(9))
    _demo_defect(db, insp, component_id="DECK-S03", category="other", observed_at=d(9), description="Unclear surface marking; needs review.")
    # Image-quality issue
    _inspect(db, "blurry", 71, "FB-08", d(1), "CAM-03")
    _inspect(db, "clean", 72, "DECK-S12", d(2))
    # Exercise the alert workflow on a couple of alerts (audit trail is recorded)
    corr = db.query(Alert).filter(Alert.component_id == "BRG-PIER-W-N").order_by(Alert.created_at).first()
    if corr:
        alert_engine.transition(db, corr, "acknowledge", "demo.engineer")
    iq = db.query(Alert).filter(Alert.rule_type == "image_quality").first()
    if iq:
        alert_engine.transition(db, iq, "resolve", "demo.engineer", "DEMO: image retaken (fictional).")
