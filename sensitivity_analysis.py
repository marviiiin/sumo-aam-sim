"""
sensitivity_analysis.py — Sensitivity analysis for SUMO-AAMSim.

Varies demand multiplier and traffic congestion (v/c ratio) to compute:
  - Passenger reneging rate, wait times, time saved
  - Break-even distances for eVTOL vs ground transport
  - Decision boundaries for mode choice

Uses analytical calculations based on the base simulation results.
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Base simulation parameters ──────────────────────────────────────────────
VP_DISTANCE_KM = 30.0           # Tampa <-> Brandon
EVTOL_CRUISE_KMH = 100.0
EVTOL_CAPACITY = 4
FIRST_LAST_MILE_KM = 5.0       # avg taxi distance to/from vertiport
TAXI_SPEED_KMH = 30.0           # avg rideshare speed in urban area

# Base passenger data from simulation
BASE_PAX_TOTAL = 316            # 168 + 148
BASE_PAX_PER_HR = 63.2          # 316 / 5 hrs
BASE_FLIGHTS_PER_HR = 16.0      # 80 / 5 hrs
BASE_LOAD_FACTOR = 3.93         # 314 / 80

# Boarding rule timeouts (minutes)
RENEGE_TIMEOUT = 30.0
FIRST_PAX_TIMEOUT = 15.0
SECOND_PAX_TIMEOUT = 10.0

# Speed-flow relationship (BPR function for urban network)
# v = v_free / (1 + alpha * (v/c)^beta)
# Calibrated: at v/c=0.92 -> 25 km/h (matches SUMO simulation ground trip of 72 min)
BPR_ALPHA = 0.85
BPR_BETA = 4.0
FREE_FLOW_SPEED_KMH = 40.0     # urban free-flow (includes signals, turns)


def ground_trip_time_min(distance_km: float, vc_ratio: float) -> float:
    """Ground trip time using BPR speed-flow model."""
    effective_speed = FREE_FLOW_SPEED_KMH / (1 + BPR_ALPHA * (vc_ratio ** BPR_BETA))
    return (distance_km / effective_speed) * 60.0


def evtol_trip_time_min(distance_km: float, ovwt_min: float, ivwt_min: float) -> float:
    """Total eVTOL door-to-door trip time."""
    taxi_to = (FIRST_LAST_MILE_KM / TAXI_SPEED_KMH) * 60.0
    flight = (distance_km / EVTOL_CRUISE_KMH) * 60.0
    taxi_from = taxi_to
    return taxi_to + ovwt_min + ivwt_min + flight + taxi_from


def compute_wait_times(demand_multiplier: float) -> dict:
    """
    Estimate OVWT, IVWT, and reneging based on demand multiplier.

    Higher demand -> more passengers per unit time -> shorter waits for others
    but potentially more reneging if flights can't keep up.

    Model: passengers arrive at rate lambda = BASE_PAX_PER_HR * multiplier
    Flights can serve EVTOL_CAPACITY pax every (EVTOL_CAPACITY / lambda_per_vp) hours
    """
    pax_per_hr = BASE_PAX_PER_HR * demand_multiplier
    pax_per_hr_per_vp = pax_per_hr / 2  # split across 2 vertiports

    # Average inter-arrival time (minutes)
    if pax_per_hr_per_vp > 0:
        avg_interarrival_min = 60.0 / pax_per_hr_per_vp
    else:
        avg_interarrival_min = 999.0

    # Time to fill eVTOL (4 pax)
    fill_time_min = avg_interarrival_min * (EVTOL_CAPACITY - 1)

    # IVWT: average time boarded passengers wait for the flight to fill
    # First pax waits longest, last pax waits ~0
    # With timeout rules, actual IVWT is min(fill_time, timeout)
    if fill_time_min <= SECOND_PAX_TIMEOUT:
        # Fills within timeout -> most flights are full
        avg_ivwt = fill_time_min / 2  # average wait
        avg_load = EVTOL_CAPACITY
        renege_rate = 0.0
    elif fill_time_min <= FIRST_PAX_TIMEOUT:
        # 2+ pax flights, second pax timeout triggers
        avg_ivwt = min(SECOND_PAX_TIMEOUT, fill_time_min) / 2
        avg_load = max(2, min(EVTOL_CAPACITY, 60.0 / avg_interarrival_min * (SECOND_PAX_TIMEOUT / 60.0) + 1))
        renege_rate = 0.0
    elif fill_time_min <= RENEGE_TIMEOUT:
        # Single pax flights possible
        avg_ivwt = min(FIRST_PAX_TIMEOUT, fill_time_min) / 2
        avg_load = max(1, min(EVTOL_CAPACITY, 60.0 / avg_interarrival_min * (FIRST_PAX_TIMEOUT / 60.0) + 1))
        renege_rate = 0.0
    else:
        # Some passengers may renege
        avg_ivwt = FIRST_PAX_TIMEOUT / 2
        avg_load = 1.5
        # Fraction that can't be served before 30 min
        served_rate = (EVTOL_CAPACITY / fill_time_min) * 60.0  # pax/hr that can be served
        renege_rate = max(0, 1 - (served_rate * 2) / pax_per_hr) * 0.5  # approximate

    # OVWT: time waiting in queue before boarding
    # With current system, boarding is immediate (queue -> board -> wait for flight)
    # At high demand, may need to wait for previous flight to depart
    flights_per_hr = pax_per_hr_per_vp / max(avg_load, 1)
    flight_interval_min = 60.0 / max(flights_per_hr, 0.1)

    if pax_per_hr_per_vp * (flight_interval_min / 60.0) <= EVTOL_CAPACITY:
        ovwt = 0.0  # Can board immediately
    else:
        ovwt = max(0, (pax_per_hr_per_vp * flight_interval_min / 60.0 - EVTOL_CAPACITY)
                   * avg_interarrival_min / 2)

    return {
        "ovwt_min": min(ovwt, RENEGE_TIMEOUT),
        "ivwt_min": avg_ivwt,
        "renege_rate": min(renege_rate, 1.0),
        "avg_load": avg_load,
        "flights_per_hr": flights_per_hr * 2,  # both directions
        "pax_per_hr": pax_per_hr,
    }


def break_even_distance(vc_ratio: float, ovwt: float, ivwt: float) -> float:
    """
    Find distance where eVTOL trip time = ground trip time.

    Ground: d / v_ground(vc) * 60
    eVTOL: taxi_to + ovwt + ivwt + d/v_evtol*60 + taxi_from

    Set equal and solve for d:
    d / v_g * 60 = 2 * taxi_time + ovwt + ivwt + d / v_e * 60
    d * (1/v_g - 1/v_e) * 60 = 2 * taxi_time + ovwt + ivwt
    d = (2 * taxi_time + ovwt + ivwt) / ((1/v_g - 1/v_e) * 60)
    """
    v_ground = FREE_FLOW_SPEED_KMH / (1 + BPR_ALPHA * (vc_ratio ** BPR_BETA))
    v_evtol = EVTOL_CRUISE_KMH
    taxi_time = (FIRST_LAST_MILE_KM / TAXI_SPEED_KMH) * 60.0

    speed_diff = (1.0 / v_ground - 1.0 / v_evtol)
    if speed_diff <= 0:
        return float('inf')  # eVTOL never faster

    overhead = 2 * taxi_time + ovwt + ivwt
    d = overhead / (speed_diff * 60.0)
    return d


def run_sensitivity():
    """Run full sensitivity analysis and generate plots."""
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "output", "report_20260428_113016")
    os.makedirs(out_dir, exist_ok=True)

    # ── 1. Demand sensitivity ────────────────────────────────────────────
    demand_multipliers = np.arange(0.25, 3.01, 0.25)
    vc_base = 0.92

    demand_results = []
    for dm in demand_multipliers:
        wt = compute_wait_times(dm)
        gt = ground_trip_time_min(VP_DISTANCE_KM, vc_base)
        et = evtol_trip_time_min(VP_DISTANCE_KM, wt["ovwt_min"], wt["ivwt_min"])
        demand_results.append({
            "multiplier": dm,
            "pax_per_hr": wt["pax_per_hr"],
            "renege_rate": wt["renege_rate"] * 100,
            "ovwt": wt["ovwt_min"],
            "ivwt": wt["ivwt_min"],
            "time_saved": gt - et,
            "ground_time": gt,
            "evtol_time": et,
            "avg_load": wt["avg_load"],
            "flights_per_hr": wt["flights_per_hr"],
        })

    # ── 2. Congestion sensitivity ────────────────────────────────────────
    vc_ratios = np.arange(0.3, 1.01, 0.05)
    dm_base = 1.0
    wt_base = compute_wait_times(dm_base)

    congestion_results = []
    for vc in vc_ratios:
        gt = ground_trip_time_min(VP_DISTANCE_KM, vc)
        et = evtol_trip_time_min(VP_DISTANCE_KM, wt_base["ovwt_min"], wt_base["ivwt_min"])
        bed = break_even_distance(vc, wt_base["ovwt_min"], wt_base["ivwt_min"])
        congestion_results.append({
            "vc": vc,
            "ground_time": gt,
            "evtol_time": et,
            "time_saved": gt - et,
            "break_even_km": bed,
            "ground_speed": FREE_FLOW_SPEED_KMH / (1 + BPR_ALPHA * (vc ** BPR_BETA)),
        })

    # ── 3. Break-even distance matrix ────────────────────────────────────
    vc_grid = np.arange(0.3, 1.01, 0.05)
    dm_grid = np.arange(0.5, 2.51, 0.25)
    be_matrix = np.zeros((len(dm_grid), len(vc_grid)))

    for i, dm in enumerate(dm_grid):
        wt = compute_wait_times(dm)
        for j, vc in enumerate(vc_grid):
            bed = break_even_distance(vc, wt["ovwt_min"], wt["ivwt_min"])
            be_matrix[i, j] = min(bed, 100)  # cap at 100 km

    # ── 4. Distance sensitivity ──────────────────────────────────────────
    distances = np.arange(5, 101, 5)
    vc_scenarios = [0.5, 0.7, 0.85, 0.92, 1.0]

    # ── PLOT 1: Demand sensitivity ───────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Sensitivity Analysis: Demand Variation (v/c = 0.92)",
                 fontsize=16, fontweight="bold")

    mults = [r["multiplier"] for r in demand_results]

    ax = axes[0, 0]
    ax.plot(mults, [r["time_saved"] for r in demand_results], "b-o", markersize=5)
    ax.axhline(y=0, color="r", linestyle="--", alpha=0.5)
    ax.set_xlabel("Demand Multiplier")
    ax.set_ylabel("Time Saved (min)")
    ax.set_title("Time Saved per Passenger")
    ax.grid(True, alpha=0.3)

    ax = axes[0, 1]
    ax.plot(mults, [r["renege_rate"] for r in demand_results], "r-o", markersize=5)
    ax.set_xlabel("Demand Multiplier")
    ax.set_ylabel("Reneging Rate (%)")
    ax.set_title("Passenger Reneging Rate")
    ax.grid(True, alpha=0.3)

    ax = axes[1, 0]
    ax.plot(mults, [r["ovwt"] for r in demand_results], "g-o", markersize=5, label="OVWT")
    ax.plot(mults, [r["ivwt"] for r in demand_results], "m-o", markersize=5, label="IVWT")
    ax.set_xlabel("Demand Multiplier")
    ax.set_ylabel("Wait Time (min)")
    ax.set_title("Wait Times")
    ax.legend()
    ax.grid(True, alpha=0.3)

    ax = axes[1, 1]
    ax.plot(mults, [r["avg_load"] for r in demand_results], "c-o", markersize=5, label="Avg Load")
    ax.axhline(y=4, color="gray", linestyle="--", alpha=0.5, label="Capacity")
    ax.set_xlabel("Demand Multiplier")
    ax.set_ylabel("Passengers per Flight")
    ax.set_title("Flight Load Factor")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path1 = os.path.join(out_dir, "sensitivity_demand.png")
    plt.savefig(path1, dpi=150)
    plt.close()
    print(f"  Demand sensitivity: {path1}")

    # ── PLOT 2: Congestion sensitivity ───────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle("Sensitivity Analysis: Traffic Congestion (v/c Ratio)",
                 fontsize=16, fontweight="bold")

    vcs = [r["vc"] for r in congestion_results]

    ax = axes[0]
    ax.plot(vcs, [r["ground_time"] for r in congestion_results], "r-o",
            markersize=4, label="Ground")
    ax.plot(vcs, [r["evtol_time"] for r in congestion_results], "b-o",
            markersize=4, label="eVTOL")
    ax.set_xlabel("Volume/Capacity Ratio")
    ax.set_ylabel("Trip Time (min)")
    ax.set_title(f"Trip Time vs Congestion ({VP_DISTANCE_KM:.0f} km)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    ax.plot(vcs, [r["time_saved"] for r in congestion_results], "g-o", markersize=4)
    ax.axhline(y=0, color="r", linestyle="--", alpha=0.5)
    ax.fill_between(vcs, [r["time_saved"] for r in congestion_results],
                    0, alpha=0.15, color="green")
    ax.set_xlabel("Volume/Capacity Ratio")
    ax.set_ylabel("Time Saved (min)")
    ax.set_title("eVTOL Time Savings vs Congestion")
    ax.grid(True, alpha=0.3)

    ax = axes[2]
    be_vals = [r["break_even_km"] for r in congestion_results]
    ax.plot(vcs, be_vals, "m-o", markersize=4)
    ax.axhline(y=VP_DISTANCE_KM, color="gray", linestyle="--", alpha=0.5,
               label=f"Tampa-Brandon ({VP_DISTANCE_KM:.0f} km)")
    ax.set_xlabel("Volume/Capacity Ratio")
    ax.set_ylabel("Break-Even Distance (km)")
    ax.set_title("Minimum Distance for eVTOL Advantage")
    ax.set_ylim(0, 80)
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path2 = os.path.join(out_dir, "sensitivity_congestion.png")
    plt.savefig(path2, dpi=150)
    plt.close()
    print(f"  Congestion sensitivity: {path2}")

    # ── PLOT 3: Break-even distance heatmap ──────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 7))
    im = ax.imshow(be_matrix, aspect="auto", origin="lower",
                   extent=[vc_grid[0], vc_grid[-1], dm_grid[0], dm_grid[-1]],
                   cmap="RdYlGn_r", vmin=5, vmax=80)
    cbar = plt.colorbar(im, ax=ax, label="Break-Even Distance (km)")

    # Add contour for 30 km (Tampa-Brandon distance)
    cs = ax.contour(vc_grid, dm_grid, be_matrix, levels=[30],
                    colors=["white"], linewidths=[2.5], linestyles=["--"])
    ax.clabel(cs, fmt="30 km", fontsize=11, colors="white")

    ax.set_xlabel("Volume/Capacity Ratio (v/c)", fontsize=12)
    ax.set_ylabel("Demand Multiplier", fontsize=12)
    ax.set_title("Break-Even Distance: eVTOL vs Ground Transport\n"
                 "(Below contour line = eVTOL advantageous for Tampa-Brandon 30 km)",
                 fontsize=14, fontweight="bold")

    plt.tight_layout()
    path3 = os.path.join(out_dir, "breakeven_heatmap.png")
    plt.savefig(path3, dpi=150)
    plt.close()
    print(f"  Break-even heatmap: {path3}")

    # ── PLOT 4: Distance-based mode choice ───────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    ax = axes[0]
    for vc in vc_scenarios:
        gt = [ground_trip_time_min(d, vc) for d in distances]
        ax.plot(distances, gt, "--", alpha=0.7, label=f"Ground v/c={vc:.2f}")

    et = [evtol_trip_time_min(d, 0.0, 3.0) for d in distances]
    ax.plot(distances, et, "b-", linewidth=2.5, label="eVTOL (IVWT=3min)")

    ax.set_xlabel("Trip Distance (km)", fontsize=12)
    ax.set_ylabel("Door-to-Door Trip Time (min)", fontsize=12)
    ax.set_title("Mode Choice: Trip Time vs Distance", fontsize=14, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(5, 100)

    ax = axes[1]
    for vc in vc_scenarios:
        savings = [ground_trip_time_min(d, vc) - evtol_trip_time_min(d, 0.0, 3.0)
                   for d in distances]
        ax.plot(distances, savings, "-o", markersize=3, label=f"v/c={vc:.2f}")

    ax.axhline(y=0, color="black", linestyle="-", linewidth=0.8)
    ax.fill_between(distances, -20, 0, alpha=0.08, color="red", label="Ground faster")
    ax.fill_between(distances, 0, 80, alpha=0.08, color="green", label="eVTOL faster")
    ax.set_xlabel("Trip Distance (km)", fontsize=12)
    ax.set_ylabel("Time Saved by eVTOL (min)", fontsize=12)
    ax.set_title("eVTOL Advantage by Distance and Congestion",
                 fontsize=14, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(5, 100)

    plt.tight_layout()
    path4 = os.path.join(out_dir, "mode_choice.png")
    plt.savefig(path4, dpi=150)
    plt.close()
    print(f"  Mode choice: {path4}")

    # ── Print summary ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SENSITIVITY ANALYSIS SUMMARY")
    print("=" * 60)

    print("\nBreak-even distances (eVTOL becomes faster than ground):")
    for vc in [0.5, 0.7, 0.85, 0.92, 1.0]:
        bed = break_even_distance(vc, 0.0, 3.0)
        gt = ground_trip_time_min(VP_DISTANCE_KM, vc)
        et = evtol_trip_time_min(VP_DISTANCE_KM, 0.0, 3.0)
        print(f"  v/c={vc:.2f}: break-even = {bed:.1f} km  "
              f"(30km: ground={gt:.1f}min, eVTOL={et:.1f}min, "
              f"saved={gt-et:.1f}min)")

    print("\nDemand sensitivity (at v/c=0.92, 30km):")
    for r in demand_results:
        if r["multiplier"] in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
            print(f"  {r['multiplier']:.1f}x demand: "
                  f"saved={r['time_saved']:.1f}min, "
                  f"renege={r['renege_rate']:.1f}%, "
                  f"OVWT={r['ovwt']:.1f}min, IVWT={r['ivwt']:.1f}min, "
                  f"load={r['avg_load']:.1f}")

    print("=" * 60)

    return {
        "demand_results": demand_results,
        "congestion_results": congestion_results,
        "be_matrix": be_matrix,
        "plots": [path1, path2, path3, path4],
    }


if __name__ == "__main__":
    run_sensitivity()
