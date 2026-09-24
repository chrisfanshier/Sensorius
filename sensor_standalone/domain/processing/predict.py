"""
Forward recoil / freefall prediction from a population regression calibration.

Ported from core_prediction_playground.py and recoil_model_validation.ipynb, using
sensor_tool's real piston_position helpers and the corer-anchored seafloor formula.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .calculations import DEFAULT_PISTON_OFFSET_M, DEFAULT_WEIGHT_STAND_LENGTH_M
from .piston_position import compute_piston_position, detect_start_core

FT_TO_M = 1.0 / 3.28
WEIGHT_STAND_LENGTH_M = DEFAULT_WEIGHT_STAND_LENGTH_M
PISTON_OFFSET_M = DEFAULT_PISTON_OFFSET_M

CURVE_TYPES = [
    "physics",
    "exponential",
    "critically_damped",
    "gamma_pulse",
    "damped_sine",
    "single_lobe_damped",
]

CURVE_LABELS = {
    "physics": "Physics recoil (regressed E)",
    "exponential": "Exponential recoil",
    "critically_damped": "Critically damped recoil",
    "gamma_pulse": "Gamma-pulse recoil",
    "damped_sine": "Damped-sine recoil",
    "single_lobe_damped": "Single-lobe recoil",
}


@dataclass
class Inputs:
    depth_m: float
    corer_lbs: float
    rope_type: str
    rope_diameter_mm: float
    v0_mean_ms: float
    v0_std_ms: float
    v0_min_ms: float
    v0_max_ms: float
    v0_scenarios: int
    random_seed: int
    time_before_s: float
    time_after_s: float
    dt_s: float
    release_above_corer_m: float
    displaced_volume_m3: float
    added_mass_coefficient: float
    barrel_diameter_in: float
    lead_flow_diameter_in: float
    lead_drag_coefficient: float
    scope_ft: float
    main_core_length_ft: float
    trigger_line_length_ft: float
    trigger_core_length_ft: float
    trigger_core_penetration_ft: float


def _rule_value(rule: dict, *, depth_m: float, corer_lbs: float) -> tuple[float, str]:
    if rule["mode"] == "linear":
        predictor = rule["predictor"]
        if predictor == "WL":
            x = corer_lbs * depth_m
        elif predictor == "depth_m":
            x = depth_m
        elif predictor == "log_depth_m":
            x = math.log(depth_m)
        else:
            raise ValueError(f"Unknown predictor: {predictor}")
        value = rule["slope"] * x + rule["intercept"]
        source = f"{predictor}, n={rule.get('n')}, R²={rule.get('r2', float('nan')):.2f}"
        return float(value), source
    return float(rule["value"]), f"{rule.get('source', rule['mode'])}, n={rule.get('n')}"


def _safe_positive(value: float, floor: float = 0.01) -> float:
    if not np.isfinite(value):
        return floor
    return max(float(value), floor)


def predict_recoil_parameters(
    inputs: Inputs,
    calibration: dict[str, Any],
) -> tuple[dict, pd.DataFrame]:
    depth_m = inputs.depth_m
    corer_lbs = inputs.corer_lbs
    rope = inputs.rope_type

    params: dict[str, dict] = {}
    audit_rows = []

    phys = calibration["physics"][rope]
    x = math.log(depth_m) if phys.get("use_log") else depth_m
    e_gpa = _safe_positive(phys["slope"] * x + phys["intercept"], 1.0)
    c_drag = float(calibration["c_drag"][rope])
    params["physics"] = {"E_gpa": e_gpa, "C_drag": c_drag}
    audit_rows.extend(
        [
            {
                "curve_type": "physics",
                "parameter": "E_gpa",
                "value": e_gpa,
                "source": f"{phys['predictor']}, n={phys['n']}, R²={phys['r2']:.2f}",
            },
            {
                "curve_type": "physics",
                "parameter": "C_drag",
                "value": c_drag,
                "source": "rope default",
            },
        ]
    )

    sld = calibration["sld"][rope]
    h_m, h_src = _rule_value(sld["h_m"], depth_m=depth_m, corer_lbs=corer_lbs)
    t_p_s, tp_src = _rule_value(sld["t_p_s"], depth_m=depth_m, corer_lbs=corer_lbs)
    alpha = _safe_positive(sld["alpha_mean"], 0.01)
    params["single_lobe_damped"] = {
        "H_m": _safe_positive(h_m),
        "t_p_s": _safe_positive(t_p_s),
        "alpha": alpha,
    }
    audit_rows.extend(
        [
            {
                "curve_type": "single_lobe_damped",
                "parameter": "H_m",
                "value": params["single_lobe_damped"]["H_m"],
                "source": h_src,
            },
            {
                "curve_type": "single_lobe_damped",
                "parameter": "t_p_s",
                "value": params["single_lobe_damped"]["t_p_s"],
                "source": tp_src,
            },
            {
                "curve_type": "single_lobe_damped",
                "parameter": "alpha",
                "value": alpha,
                "source": f"mean alpha, n={sld['n']}",
            },
        ]
    )

    for curve in ["exponential", "critically_damped", "gamma_pulse", "damped_sine"]:
        curve_rules = calibration["empirical"][curve][rope]
        a_m, a_src = _rule_value(curve_rules["A_m"], depth_m=depth_m, corer_lbs=corer_lbs)
        tau_s, tau_src = _rule_value(curve_rules["tau_s"], depth_m=depth_m, corer_lbs=corer_lbs)
        params[curve] = {"A_m": _safe_positive(a_m), "tau_s": _safe_positive(tau_s)}
        audit_rows.extend(
            [
                {"curve_type": curve, "parameter": "A_m", "value": params[curve]["A_m"], "source": a_src},
                {"curve_type": curve, "parameter": "tau_s", "value": params[curve]["tau_s"], "source": tau_src},
            ]
        )
        if curve == "damped_sine":
            omega, omega_src = _rule_value(
                curve_rules["omega_rads"], depth_m=depth_m, corer_lbs=corer_lbs
            )
            params[curve]["omega_rads"] = _safe_positive(omega)
            audit_rows.append(
                {
                    "curve_type": curve,
                    "parameter": "omega_rads",
                    "value": params[curve]["omega_rads"],
                    "source": omega_src,
                }
            )

    return params, pd.DataFrame(audit_rows)


def make_v0_scenarios(inputs: Inputs) -> np.ndarray:
    rng = np.random.default_rng(int(inputs.random_seed))
    values = np.clip(
        rng.normal(inputs.v0_mean_ms, inputs.v0_std_ms, int(inputs.v0_scenarios)),
        inputs.v0_min_ms,
        inputs.v0_max_ms,
    )
    if len(values):
        values[0] = inputs.v0_mean_ms
    return values


def barrel_length_m(inputs: Inputs) -> float:
    """Core barrel length for freefall drag (same as main core length, metres)."""
    return inputs.main_core_length_ft * FT_TO_M


def corer_acceleration_factory(inputs: Inputs):
    rho_w = 1025.0
    g = 9.81
    mu = 1.065e-3
    mass_kg = inputs.corer_lbs * 0.453592
    barrel_dia_m = inputs.barrel_diameter_in * 0.0254
    barrel_len_m = barrel_length_m(inputs)
    lead_dia_m = inputs.lead_flow_diameter_in * 0.0254
    lead_area = math.pi * ((lead_dia_m / 2.0) ** 2 - (barrel_dia_m / 2.0) ** 2)
    barrel_wet_area = math.pi * barrel_dia_m * barrel_len_m
    added_mass = inputs.added_mass_coefficient * rho_w * inputs.displaced_volume_m3
    effective_mass = mass_kg + added_mass
    drive_force = mass_kg * g - rho_w * inputs.displaced_volume_m3 * g

    def barrel_cd(speed: float) -> float:
        speed = abs(float(speed))
        if speed < 0.001:
            return 0.003
        reynolds = rho_w * speed * barrel_len_m / mu
        return 0.455 / (math.log10(reynolds) ** 2.58) if reynolds > 1e5 else 0.003

    def accel(v: float) -> float:
        speed = abs(float(v))
        lead_drag = 0.5 * rho_w * inputs.lead_drag_coefficient * lead_area * v * speed
        skin_drag = 0.5 * rho_w * barrel_cd(speed) * barrel_wet_area * v * speed
        return (drive_force - lead_drag - skin_drag) / effective_mass

    return accel


def integrate_freefall(inputs: Inputs, post_time: np.ndarray, v0: float) -> np.ndarray:
    accel = corer_acceleration_factory(inputs)
    dt = min(0.002, max(inputs.dt_s / 5.0, 0.0005))
    sim_t = np.arange(0.0, inputs.time_after_s + dt, dt)
    z = np.zeros_like(sim_t)
    v = np.zeros_like(sim_t)
    v[0] = v0
    for i in range(1, len(sim_t)):
        z0, v0i = z[i - 1], v[i - 1]

        def deriv(vi: float) -> tuple[float, float]:
            return vi, accel(vi)

        k1z, k1v = deriv(v0i)
        k2z, k2v = deriv(v0i + 0.5 * dt * k1v)
        k3z, k3v = deriv(v0i + 0.5 * dt * k2v)
        k4z, k4v = deriv(v0i + dt * k3v)
        z[i] = z0 + dt * (k1z + 2 * k2z + 2 * k3z + k4z) / 6.0
        v[i] = v0i + dt * (k1v + 2 * k2v + 2 * k3v + k4v) / 6.0
    return np.interp(post_time, sim_t, z)


def physics_recoil(inputs: Inputs, params: dict, post_time: np.ndarray, v0: float) -> np.ndarray:
    p = params["physics"]
    rho_w = 1025.0
    dia_m = inputs.rope_diameter_mm / 1000.0
    a_cs = math.pi * (dia_m / 2.0) ** 2
    a_wet = math.pi * dia_m * inputs.depth_m
    k = (p["E_gpa"] * 1e9 * a_cs) / inputs.depth_m
    rho_rope = 970.0 if inputs.rope_type == "hmpe" else 7850.0
    m_eff = 0.5 * a_cs * rho_rope * inputs.depth_m + rho_w * a_cs * inputs.depth_m
    f_drive = inputs.corer_lbs * 0.4536 * 9.81 * (1 - rho_w / 7850.0)
    dt = inputs.dt_s
    sim_t = np.arange(0.0, inputs.time_after_s + dt, dt)
    x = 0.0
    v = -float(v0)
    out = np.zeros_like(sim_t)

    def accel(xi: float, vi: float) -> float:
        return (
            f_drive - k * xi - 0.5 * rho_w * p["C_drag"] * a_wet * vi * abs(vi)
        ) / m_eff

    for i in range(len(sim_t)):
        out[i] = x
        a1 = accel(x, v)
        a2 = accel(x + 0.5 * dt * v, v + 0.5 * dt * a1)
        a3 = accel(x + 0.5 * dt * (v + 0.5 * dt * a1), v + 0.5 * dt * a2)
        a4 = accel(x + dt * (v + dt * a2), v + dt * a3)
        v += dt * (a1 + 2 * a2 + 2 * a3 + a4) / 6.0
        x += dt * v
    return np.interp(post_time, sim_t, out)


def empirical_recoil(curve: str, params: dict, post_time: np.ndarray) -> np.ndarray:
    t = post_time
    p = params[curve]
    if curve == "single_lobe_damped":
        u = t / p["t_p_s"]
        return np.where(
            (u >= 0.0) & (u <= 1.0),
            p["H_m"] * np.power(np.clip(u, 1e-10, None), p["alpha"]) * (1.0 - u),
            0.0,
        )
    a = p["A_m"]
    tau = p["tau_s"]
    if curve == "exponential":
        return a * (1.0 - np.exp(-t / tau))
    if curve == "critically_damped":
        return a * (1.0 - (1.0 + t / tau) * np.exp(-t / tau))
    if curve == "gamma_pulse":
        return a * (t / tau) * np.exp(1.0 - t / tau)
    if curve == "damped_sine":
        return a * np.exp(-t / tau) * np.sin(p["omega_rads"] * t)
    raise ValueError(curve)


def bands(matrix: np.ndarray) -> dict[int, np.ndarray]:
    return {q: np.percentile(matrix, q, axis=0) for q in (10, 50, 90)}


def trigger_offset_m(inputs: Inputs) -> float:
    """Planned trigger-line offset below corer at trip (metres, depth-positive)."""
    return inputs.trigger_line_length_ft * FT_TO_M


def build_trigger_paths(
    corer_paths: np.ndarray,
    time: np.ndarray,
    trigger_line_m: float,
) -> np.ndarray:
    """
    Trigger core/weight depth relative to corer @ trip.

    Pre-trip: rigidly offset below corer by planned trigger line length.
    From trip onward: frozen at trip depth (decoupled from corer/release motion).
    """
    post_mask = time >= 0.0
    trigger_paths = corer_paths + trigger_line_m
    trigger_paths[:, post_mask] = trigger_line_m
    return trigger_paths


def run_prediction(
    inputs: Inputs | dict[str, Any],
    calibration: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(inputs, dict):
        inputs = Inputs(**inputs)

    params, parameter_table = predict_recoil_parameters(inputs, calibration)

    time = np.arange(-inputs.time_before_s, inputs.time_after_s + inputs.dt_s / 2.0, inputs.dt_s)
    pre_mask = time < 0.0
    post_mask = ~pre_mask
    post_time = time[post_mask]
    trip_idx = int(np.argmin(np.abs(time)))
    v0_values = make_v0_scenarios(inputs)

    corer_paths = []
    release_paths = {curve: [] for curve in CURVE_TYPES}
    empirical_post = {
        curve: empirical_recoil(curve, params, post_time)
        for curve in CURVE_TYPES
        if curve != "physics"
    }

    for v0 in v0_values:
        corer = np.empty_like(time)
        corer[pre_mask] = v0 * time[pre_mask]
        corer[post_mask] = integrate_freefall(inputs, post_time, v0)
        corer_paths.append(corer)

        for curve in CURVE_TYPES:
            release = np.empty_like(time)
            release[pre_mask] = v0 * time[pre_mask] - inputs.release_above_corer_m
            recoil = (
                physics_recoil(inputs, params, post_time, v0)
                if curve == "physics"
                else empirical_post[curve]
            )
            release[post_mask] = -inputs.release_above_corer_m - recoil
            release_paths[curve].append(release)

    corer_paths = np.vstack(corer_paths)
    release_paths = {curve: np.vstack(paths) for curve, paths in release_paths.items()}
    trigger_line_m = trigger_offset_m(inputs)
    trigger_paths = build_trigger_paths(corer_paths, time, trigger_line_m)

    release_depth_at_trip = inputs.depth_m
    release_rel_at_trip = -inputs.release_above_corer_m
    corer_depth_at_trip = release_depth_at_trip - release_rel_at_trip
    seafloor_m = (
        corer_depth_at_trip
        + inputs.trigger_line_length_ft * FT_TO_M
        + inputs.trigger_core_length_ft * FT_TO_M
        - inputs.trigger_core_penetration_ft * FT_TO_M
    )
    seafloor_relative_m = seafloor_m - corer_depth_at_trip
    main_core_length_m = inputs.main_core_length_ft * FT_TO_M

    piston_paths = {}
    event_rows = []
    for curve in CURVE_TYPES:
        piston_rows = []
        for i in range(len(v0_values)):
            release_rel = release_paths[curve][i]
            corer_rel = corer_paths[i]
            release_abs = release_depth_at_trip + (release_rel - release_rel_at_trip)
            corer_abs = release_depth_at_trip + (corer_rel - release_rel_at_trip)
            start_core_idx = detect_start_core(
                corer_abs, release_abs, inputs.scope_ft, trip_idx
            )
            sep_m = abs(float(release_abs[start_core_idx] - corer_abs[start_core_idx]))
            start_core_detected = (
                start_core_idx >= trip_idx and sep_m > inputs.scope_ft * FT_TO_M
            )

            piston_abs = compute_piston_position(
                corer_abs,
                release_abs,
                inputs.scope_ft,
                inputs.main_core_length_ft,
                start_core_idx,
                offset_constant=PISTON_OFFSET_M,
            )
            piston_rows.append(piston_abs - corer_depth_at_trip)

            core_tip_abs = corer_abs + WEIGHT_STAND_LENGTH_M + main_core_length_m
            pen_candidates = np.flatnonzero(core_tip_abs[trip_idx:] >= seafloor_m)
            start_pen_idx = int(trip_idx + pen_candidates[0]) if len(pen_candidates) else None
            start_pen_detected = start_pen_idx is not None

            event_rows.append(
                {
                    "curve_type": curve,
                    "start_core_detected": start_core_detected,
                    "start_core_time_s": float(time[start_core_idx]) if start_core_detected else np.nan,
                    "piston_alt_start_core_m": (
                        seafloor_m - float(piston_abs[start_core_idx])
                        if start_core_detected else np.nan
                    ),
                    "start_pen_detected": start_pen_detected,
                    "start_pen_time_s": float(time[start_pen_idx]) if start_pen_detected else np.nan,
                    "piston_alt_start_pen_m": (
                        seafloor_m - float(piston_abs[start_pen_idx])
                        if start_pen_detected else np.nan
                    ),
                    "start_pen_before_start_core": bool(
                        start_pen_idx < start_core_idx
                        if start_pen_detected and start_core_detected else False
                    ),
                }
            )
        piston_paths[curve] = np.vstack(piston_rows)

    event_detail = pd.DataFrame(event_rows)
    summary_rows = []
    for curve, detail in event_detail.groupby("curve_type"):
        summary_rows.append(
            {
                "curve_type": curve,
                "start_core_detected_n": int(detail["start_core_detected"].sum()),
                "start_pen_detected_n": int(detail["start_pen_detected"].sum()),
                "start_pen_before_start_core_n": int(detail["start_pen_before_start_core"].sum()),
                "start_core_time_median_s": float(np.nanmedian(detail["start_core_time_s"])),
                "piston_alt_start_core_median_m": float(np.nanmedian(detail["piston_alt_start_core_m"])),
                "start_pen_time_median_s": float(np.nanmedian(detail["start_pen_time_s"])),
                "piston_alt_start_pen_median_m": float(np.nanmedian(detail["piston_alt_start_pen_m"])),
            }
        )

    return {
        "inputs": inputs,
        "time": time,
        "corer_paths": corer_paths,
        "release_paths": release_paths,
        "piston_paths": piston_paths,
        "trigger_paths": trigger_paths,
        "corer_bands": bands(corer_paths),
        "trigger_bands": bands(trigger_paths),
        "release_bands": {curve: bands(paths) for curve, paths in release_paths.items()},
        "piston_bands": {curve: bands(paths) for curve, paths in piston_paths.items()},
        "trigger_line_m": trigger_line_m,
        "parameter_table": parameter_table,
        "event_summary": pd.DataFrame(summary_rows),
        "seafloor_relative_m": seafloor_relative_m,
        "seafloor_m": seafloor_m,
        "corer_depth_at_trip_m": corer_depth_at_trip,
        "release_depth_at_trip_m": release_depth_at_trip,
        "v0_values": v0_values,
    }


def draw_curve(
    result: dict[str, Any],
    selected_curves: list[str],
    show_piston: bool,
    show_trigger: bool = True,
) -> plt.Figure:
    time = result["time"]
    corer = result["corer_bands"]
    trigger = result.get("trigger_bands")
    event_summary = result["event_summary"].set_index("curve_type")
    seafloor_rel = result["seafloor_relative_m"]

    n = len(selected_curves)
    cols = 2 if n > 1 else 1
    rows = int(math.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(10 * cols, 5.8 * rows), sharex=True, squeeze=False)

    y_values = [corer[10].min(), corer[90].max(), seafloor_rel]
    if show_trigger and trigger is not None:
        y_values.extend([trigger[10].min(), trigger[90].max()])
    for curve in selected_curves:
        rel = result["release_bands"][curve]
        y_values.extend([rel[10].min(), rel[90].max()])
        if show_piston:
            pist = result["piston_bands"][curve]
            y_values.extend([pist[10].min(), pist[90].max()])
    y_min = float(np.nanmin(y_values)) - 0.5
    y_max = float(np.nanmax(y_values)) + 0.75

    for ax, curve in zip(axes.flat, selected_curves):
        release = result["release_bands"][curve]
        ax.fill_between(time, corer[10], corer[90], color="#e6550d", alpha=0.16, label="Corer 10-90%")
        ax.plot(time, corer[50], color="#e6550d", lw=2.6, label="Corer median")
        if show_trigger and trigger is not None:
            ax.fill_between(time, trigger[10], trigger[90], color="#41ab5d", alpha=0.14, label="Trigger 10-90%")
            ax.plot(time, trigger[50], color="#238b45", lw=2.2, label="Trigger median")
        ax.fill_between(time, release[10], release[90], color="#3182bd", alpha=0.18, label="Release 10-90%")
        ax.plot(time, release[50], color="#3182bd", lw=2.4, label="Release median")

        if show_piston:
            piston = result["piston_bands"][curve]
            ax.fill_between(time, piston[10], piston[90], color="#756bb1", alpha=0.14, label="Piston 10-90%")
            ax.plot(time, piston[50], color="#756bb1", lw=2.2, label="Piston median")

        ax.axvline(0.0, color="black", ls="--", lw=1.0, label="Trip")
        ax.axhline(seafloor_rel, color="#444444", ls=":", lw=1.5, label="Estimated seafloor")

        if curve in event_summary.index:
            row = event_summary.loc[curve]
            sc_t = row["start_core_time_median_s"]
            sp_t = row["start_pen_time_median_s"]
            if np.isfinite(sc_t):
                ax.axvline(sc_t, color="#2ca02c", ls="-.", lw=1.7, label="Start core")
            if np.isfinite(sp_t):
                ax.axvline(sp_t, color="#984ea3", ls="--", lw=1.7, label="Start pen")

        title = CURVE_LABELS[curve]
        if curve == "gamma_pulse":
            title += "\n(sparse training data - low confidence)"
        ax.set_title(title)
        ax.set_xlabel("Time relative to trip (s)")
        ax.set_ylabel("Relative depth (m; downward positive)")
        ax.set_ylim(y_max, y_min)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="best")

    for ax in axes.flat[n:]:
        ax.axis("off")

    fig.tight_layout()
    return fig


def training_warnings(inputs: Inputs, calibration: dict[str, Any]) -> list[str]:
    warnings = []
    ranges = calibration["training_ranges"].get(inputs.rope_type)
    if not ranges:
        return warnings
    wl = inputs.depth_m * inputs.corer_lbs
    if not ranges["depth_min_m"] <= inputs.depth_m <= ranges["depth_max_m"]:
        warnings.append(
            f"Depth {inputs.depth_m:.0f} m is outside the {inputs.rope_type.upper()} "
            f"training range ({ranges['depth_min_m']:.0f}-{ranges['depth_max_m']:.0f} m)."
        )
    if not ranges["wl_min"] <= wl <= ranges["wl_max"]:
        warnings.append(
            f"Weight x depth {wl:,.0f} lb·m is outside the {inputs.rope_type.upper()} "
            f"training range ({ranges['wl_min']:,.0f}-{ranges['wl_max']:,.0f} lb·m)."
        )
    return warnings


def default_inputs() -> Inputs:
    """Default deployment inputs (validation notebook / playground conventions)."""
    return Inputs(
        depth_m=1500.0,
        corer_lbs=6000.0,
        rope_type="hmpe",
        rope_diameter_mm=14.3,
        v0_mean_ms=-0.10,
        v0_std_ms=0.45,
        v0_min_ms=-0.75,
        v0_max_ms=1.50,
        v0_scenarios=301,
        random_seed=20260706,
        time_before_s=1.0,
        time_after_s=3.0,
        dt_s=0.01,
        release_above_corer_m=0.50,
        displaced_volume_m3=0.347,
        added_mass_coefficient=0.0,
        barrel_diameter_in=5.0,
        lead_flow_diameter_in=24.0,
        lead_drag_coefficient=1.10,
        scope_ft=25.0,
        main_core_length_ft=60.0,
        trigger_line_length_ft=30.0,
        trigger_core_length_ft=10.0,
        trigger_core_penetration_ft=0.0,
    )


def inputs_to_dict(inputs: Inputs) -> dict[str, Any]:
    return asdict(inputs)
