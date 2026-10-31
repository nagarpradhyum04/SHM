"""Fatigue-based remaining-life estimate under repeated loading (rainflow + S-N + Miner's rule).

Method (``fatigue-miner-v1``):

1. Take the measured acceleration of one axis (or the magnitude) from the sensor on the component,
   remove the mean, and ignore reversals smaller than a noise gate.
2. Count load cycles with rainflow counting (ASTM E1049-85, three-point method, residue as half cycles).
3. Convert each acceleration range to a stress range with an engineer-supplied factor (MPa per g).
   The factor must come from a strain-gauge calibration or a validated structural model of the detail;
   it cannot be derived from acceleration alone.
4. Damage per cycle from the EN 1993-1-9 S-N curve of the chosen detail category Δσ_C:
       Δσ ≥ Δσ_D:        N = 2·10⁶ · (Δσ_C / (γ·Δσ))³
       Δσ_L ≤ Δσ < Δσ_D: N = 5·10⁶ · (Δσ_D / (γ·Δσ))⁵
       Δσ < Δσ_L:        no damage (cut-off)
   with Δσ_D = (2/5)^(1/3)·Δσ_C, Δσ_L = (5/100)^(1/5)·Δσ_D and γ = γ_Ff·γ_Mf.
5. Palmgren–Miner: D_obs = Σ n_i/N_i over the observed period; damage rate = D_obs / duration.
   Remaining life = (1 − D_prior) / damage rate, assuming the observed loading is representative of
   future loading.

The result is an engineering estimate, not a validated prediction. Its uncertainty is dominated by
the stress factor (damage ∝ factor^m), the S-N category, the representativeness of the observed
period and the prior damage. Results from simulated data are labelled demonstration-only.
"""
from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Component, Device, RULResult, SensorReading
from app.services.settings_store import get_setting, set_setting
from app.timeutil import utcnow

METHOD = "fatigue-miner-v1"
# EN 1993-1-9 Table 8.x detail categories (Δσ_C in MPa at 2·10⁶ cycles)
DETAIL_CATEGORIES = [160, 140, 125, 112, 100, 90, 80, 71, 63, 56, 50, 45, 40, 36]
SECONDS_PER_YEAR = 365.25 * 86400
MIN_OBSERVATION_S = 600
MAX_SAMPLES = 2_000_000

DEFAULT_CONFIG = {
    "device_id": None,          # sensor on the component (defaults to the first acceleration device found)
    "axis": "z",                # x | y | z | magnitude
    "stress_per_g_mpa": None,   # REQUIRED: MPa of stress range per g of acceleration range at the detail
    "factor_source": "",        # how the factor was obtained (strain-gauge calibration, FE model, …)
    "factor_uncertainty_pct": 20.0,
    "detail_category_mpa": None,  # REQUIRED: Δσ_C (EN 1993-1-9)
    "gamma_ff": 1.0,
    "gamma_mf": 1.35,
    "prior_damage": 0.0,        # damage already consumed (0–1), e.g. from service history
    "noise_gate_g": 0.002,      # ignore acceleration reversals smaller than this
    "observation_hours": 24.0,  # analyse the most recent N hours of data
    "source": "real",           # real | uploaded | simulated (simulated → demonstration only)
}


def config_key(component_id: str) -> str:
    return f"rul_config:{component_id}"


def get_config(db: Session, component_id: str) -> dict:
    stored = get_setting(db, config_key(component_id)) or {}
    return {**DEFAULT_CONFIG, **stored}


def save_config(db: Session, component_id: str, cfg: dict, actor: str | None) -> dict:
    unknown = set(cfg) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"Unknown fields: {sorted(unknown)}")
    merged = {**get_config(db, component_id), **cfg}
    if merged["axis"] not in ("x", "y", "z", "magnitude"):
        raise ValueError("axis must be x, y, z or magnitude")
    if merged["source"] not in ("real", "uploaded", "simulated"):
        raise ValueError("source must be real, uploaded or simulated")
    if merged["detail_category_mpa"] is not None and float(merged["detail_category_mpa"]) <= 0:
        raise ValueError("detail category must be positive")
    if merged["stress_per_g_mpa"] is not None and float(merged["stress_per_g_mpa"]) <= 0:
        raise ValueError("stress factor must be positive")
    if not 0 <= float(merged["prior_damage"]) < 1:
        raise ValueError("prior damage must be between 0 and 1")
    set_setting(db, config_key(component_id), merged, actor=actor)
    return merged


# --------------------------------------------------------------------------- algorithms (pure)


def reversals(x: np.ndarray, gate: float = 0.0) -> np.ndarray:
    """Turning points of a signal, skipping excursions smaller than ``gate`` (hysteresis filter)."""
    x = np.asarray(x, float)
    if x.size < 2:
        return x.copy()
    out = [x[0]]
    direction = 0
    for v in x[1:]:
        last = out[-1]
        if direction == 0:
            if abs(v - last) > gate:
                direction = 1 if v > last else -1
                out.append(v)
        elif direction > 0:
            if v >= out[-1]:
                out[-1] = v
            elif out[-1] - v > gate:
                out.append(v)
                direction = -1
        else:
            if v <= out[-1]:
                out[-1] = v
            elif v - out[-1] > gate:
                out.append(v)
                direction = 1
    return np.array(out)


def rainflow(turning_points) -> list[tuple[float, float]]:
    """ASTM E1049-85 rainflow counting on turning points. Returns (range, count) with count 0.5 or 1."""
    stack: list[float] = []
    cycles: list[tuple[float, float]] = []
    for p in turning_points:
        stack.append(float(p))
        while len(stack) >= 3:
            x = abs(stack[-1] - stack[-2])
            y = abs(stack[-2] - stack[-3])
            if x < y:
                break
            if len(stack) == 3:
                cycles.append((y, 0.5))
                stack.pop(0)
            else:
                cycles.append((y, 1.0))
                last = stack.pop()
                stack.pop()
                stack.pop()
                stack.append(last)
    for a, b in zip(stack, stack[1:]):
        cycles.append((abs(b - a), 0.5))
    return cycles


def sn_cycles_to_failure(stress_range: float, dc: float, gamma: float = 1.0) -> float:
    """EN 1993-1-9 tri-linear S-N curve (direct stress). Returns math.inf below the cut-off."""
    s = gamma * stress_range
    d = (2 / 5) ** (1 / 3) * dc
    cutoff = (5 / 100) ** (1 / 5) * d
    if s <= 0 or s < cutoff:
        return math.inf
    if s >= d:
        return 2e6 * (dc / s) ** 3
    return 5e6 * (d / s) ** 5


def miner_damage(stress_cycles: list[tuple[float, float]], dc: float, gamma: float) -> float:
    return sum(n / sn_cycles_to_failure(s, dc, gamma) for s, n in stress_cycles)


# --------------------------------------------------------------------------- estimation


def _unavailable(db, asset_id, component_id, reasons: list[str], cfg: dict | None, source: str | None) -> RULResult:
    res = RULResult(
        id=new_id("RUL"), asset_id=asset_id, component_id=component_id, status="unavailable", estimate=None, units="years",
        horizon=None, model_version=METHOD, input_coverage=None, validation_status="not_estimated",
        limitations=reasons, message="RUL prediction unavailable: " + " ".join(reasons), details={"config": cfg}, data_source=source,
    )
    db.add(res)
    db.flush()
    return res


def estimate(db: Session, component_id: str, now=None) -> RULResult:
    comp = db.get(Component, component_id)
    if comp is None:
        raise ValueError("Unknown component")
    cfg = get_config(db, component_id)
    now = now or utcnow()
    missing = []
    if cfg["stress_per_g_mpa"] is None:
        missing.append("Enter the stress-per-g factor for this detail (from a strain-gauge calibration or a validated structural model).")
    if cfg["detail_category_mpa"] is None:
        missing.append("Choose the S-N detail category (EN 1993-1-9) of the fatigue-critical detail.")
    dev_q = db.query(Device).filter(Device.component_id == component_id, Device.device_type.in_(["accelerometer", "sensor_node"]))
    device = db.get(Device, cfg["device_id"]) if cfg["device_id"] else dev_q.first()
    if device is None:
        missing.append("Install an acceleration sensor on this component.")
    if missing:
        return _unavailable(db, comp.asset_id, component_id, missing, cfg, cfg["source"])

    source = cfg["source"]
    since = now - timedelta(hours=float(cfg["observation_hours"]))
    rows = (db.query(SensorReading.ts, SensorReading.ax, SensorReading.ay, SensorReading.az)
            .filter(SensorReading.device_id == device.id, SensorReading.source == source, SensorReading.ts >= since,
                    SensorReading.quality != "invalid")
            .order_by(SensorReading.ts).limit(MAX_SAMPLES).all())
    if len(rows) < 2:
        return _unavailable(db, comp.asset_id, component_id, [f"No {source} readings from {device.id} in the last {cfg['observation_hours']} h."], cfg, source)
    ts = np.array([r[0].timestamp() for r in rows])
    a = np.array([[r[1], r[2], r[3]] for r in rows], float)
    duration = float(ts[-1] - ts[0])
    rate = device.sample_rate_hz or (len(ts) - 1) / max(duration, 1e-9)
    coverage = min(1.0, len(ts) / (duration * rate)) if duration > 0 else 0.0
    if duration < MIN_OBSERVATION_S:
        return _unavailable(db, comp.asset_id, component_id,
                            [f"Only {duration / 60:.1f} min of data; at least {MIN_OBSERVATION_S // 60} min are needed."], cfg, source)
    sig = np.linalg.norm(a, axis=1) if cfg["axis"] == "magnitude" else a[:, "xyz".index(cfg["axis"])]
    sig = sig - sig.mean()
    tp = reversals(sig, float(cfg["noise_gate_g"]))
    acc_cycles = rainflow(tp)
    k = float(cfg["stress_per_g_mpa"])
    dc = float(cfg["detail_category_mpa"])
    gamma = float(cfg["gamma_ff"]) * float(cfg["gamma_mf"])
    stress_cycles = [(r * k, n) for r, n in acc_cycles]
    d_obs = miner_damage(stress_cycles, dc, gamma)
    u = float(cfg["factor_uncertainty_pct"]) / 100.0
    d_hi = miner_damage([(s * (1 + u), n) for s, n in stress_cycles], dc, gamma)
    d_lo = miner_damage([(s * max(1 - u, 1e-6), n) for s, n in stress_cycles], dc, gamma)
    remaining = 1.0 - float(cfg["prior_damage"])
    per_year = lambda d: d / duration * SECONDS_PER_YEAR  # noqa: E731
    life = lambda d: remaining / per_year(d) if d > 0 else None  # noqa: E731

    s_max = max((s for s, _ in stress_cycles), default=0.0)
    edges = np.linspace(0, max(s_max, 1e-9), 13)
    hist = np.histogram([s for s, _ in stress_cycles], bins=edges, weights=[n for _, n in stress_cycles])[0] if stress_cycles else np.zeros(12)
    cutoff = (5 / 100) ** (1 / 5) * (2 / 5) ** (1 / 3) * dc / gamma
    details = {
        "method": METHOD, "device_id": device.id, "axis": cfg["axis"], "observed_s": duration, "samples": len(ts),
        "data_coverage": round(coverage, 3), "cycles_counted": float(sum(n for _, n in acc_cycles)),
        "damaging_cycles": float(sum(n for s, n in stress_cycles if s >= cutoff)),
        "max_stress_range_mpa": s_max, "cutoff_stress_range_mpa": cutoff, "damage_observed": d_obs,
        "damage_per_year": per_year(d_obs), "prior_damage": cfg["prior_damage"],
        "histogram": {"edges_mpa": edges.tolist(), "cycles": hist.tolist()},
        "sn_curve": {"standard": "EN 1993-1-9", "detail_category_mpa": dc, "m1": 3, "m2": 5, "gamma": gamma},
        "config": cfg,
    }
    limitations = [
        "Assumes the observed period is representative of future loading (traffic, temperature, wind).",
        f"Stress = {k:g} MPa/g × acceleration range — only as good as that factor ({cfg['factor_source'] or 'source not recorded'}).",
        "Uses an EN 1993-1-9 steel S-N curve; other materials/details need a different curve.",
        "Miner's rule ignores load-sequence effects; corrosion, existing cracks and repairs are not modelled.",
        "Requires review and sign-off by a qualified structural engineer.",
    ]
    validation = "demonstration_only" if source == "simulated" else "unvalidated_engineering_estimate"
    if d_obs <= 0:
        msg = (f"No damaging cycles in {duration / 3600:.1f} h of {source} data (all stress ranges below the "
               f"{cutoff:.1f} MPa cut-off): fatigue life is not limited by the loading observed so far.")
        res = RULResult(id=new_id("RUL"), asset_id=comp.asset_id, component_id=component_id, status="no_damaging_cycles", estimate=None,
                        units="years", horizon=f"{duration / 3600:.1f} h observed", model_version=METHOD, validation_status=validation,
                        limitations=limitations, message=msg, details=details, data_source=source)
    else:
        est = life(d_obs)
        res = RULResult(
            id=new_id("RUL"), asset_id=comp.asset_id, component_id=component_id, status="estimated", estimate=est, units="years",
            horizon=f"extrapolated from {duration / 3600:.1f} h observed", interval_low=life(d_hi), interval_high=life(d_lo),
            model_version=METHOD, validation_status=validation, limitations=limitations, data_source=source, details=details,
            message=(("DEMONSTRATION ONLY (simulated input). " if source == "simulated" else "")
                     + f"About {est:,.0f} years of fatigue life remaining at the observed loading "
                       f"(range {life(d_hi):,.0f}–{life(d_lo):,.0f} years for ±{u * 100:.0f} % stress-factor uncertainty)."),
        )
    res.input_coverage = {"time_series_structural_measurements": {"available": True, "source": source, "hours": duration / 3600,
                                                                   "coverage": round(coverage, 3)}}
    db.add(res)
    db.flush()
    return res
