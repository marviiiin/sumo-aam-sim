"""
plot_dt_signal.py — Distance-time diagram with traffic signal phase coloration.

Single direction (eastbound), 15 minutes, with signal state bands at junctions.
"""

import os
import sys
import collections

from config import SUMO_BINARY, SUMOCFG_PATH, STEP_LENGTH_S

import traci
import traci.exceptions

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
import numpy as np

# ── Corridor (eastbound) ────────────────────────────────────────────────────
EDGES = ["-18", "-19", "-20", "-21"]

# Signalised junctions on the eastbound corridor.
# Each entry: (tls_id, link_index for EB through, cumulative_distance_m)
# link_index is the index into the signal state string for -19->-20 or -21->2 etc.
SIGNAL_JUNCTIONS = [
    # Junction 189 (VP-Alpha): -19 -> -20  (link indices 10, 12 — use 10)
    {"tls_id": "189", "link_idx": 10, "label": "J-189\n(VP-Alpha)"},
    # Junction 532: -21 -> 2  (link indices 7,8 — use 7)
    {"tls_id": "532", "link_idx": 7, "label": "J-532"},
]

SIM_DURATION = 900    # 15 minutes
PLOT_DURATION = 900   # plot 15 minutes


def run_and_collect():
    cmd = [
        SUMO_BINARY, "-c", SUMOCFG_PATH,
        "--step-length", str(STEP_LENGTH_S),
        "--end", str(SIM_DURATION),
        "--seed", "42",
        "--no-step-log", "true",
        "--time-to-teleport", "-1",
    ]
    print("Starting SUMO for signal-phase distance-time diagram ...")
    traci.start(cmd)

    # Edge lengths & cumulative offsets
    lengths = {}
    for eid in EDGES:
        lengths[eid] = traci.lane.getLength(f"{eid}_0")
    offsets = {}
    cum = 0.0
    for eid in EDGES:
        offsets[eid] = cum
        cum += lengths[eid]
    corridor_len = cum

    # Compute junction positions (at the END of each edge before the junction)
    # Junction 189 is at end of -19 (offset[-19] + length[-19])
    # Junction 532 is at end of -21 (offset[-21] + length[-21])
    junc_positions = {
        "189": offsets["-19"] + lengths["-19"],
        "532": offsets["-21"] + lengths["-21"],
    }
    for sj in SIGNAL_JUNCTIONS:
        sj["position"] = junc_positions[sj["tls_id"]]

    print(f"Corridor: {corridor_len:.1f}m")
    for sj in SIGNAL_JUNCTIONS:
        print(f"  Signal {sj['tls_id']} at {sj['position']:.1f}m")

    edges_set = set(EDGES)
    trajectories = collections.defaultdict(list)

    # Signal state log: list of (time_s, tls_id, state_char)
    # state_char: 'G'/'g' = green, 'r' = red, 'y' = yellow
    signal_log = collections.defaultdict(list)

    step = 0
    try:
        while True:
            traci.simulationStep()
            t = traci.simulation.getTime()

            # Collect vehicle positions
            try:
                for vid in traci.vehicle.getIDList():
                    eid = traci.vehicle.getRoadID(vid)
                    if eid in edges_set:
                        pos = traci.vehicle.getLanePosition(vid)
                        spd = traci.vehicle.getSpeed(vid)
                        dist = offsets[eid] + pos
                        trajectories[vid].append((t, dist, spd))
            except traci.exceptions.TraCIException:
                pass

            # Collect signal states
            for sj in SIGNAL_JUNCTIONS:
                try:
                    state_str = traci.trafficlight.getRedYellowGreenState(sj["tls_id"])
                    char = state_str[sj["link_idx"]]
                    signal_log[sj["tls_id"]].append((t, char))
                except Exception:
                    pass

            step += 1
            if t >= SIM_DURATION:
                break
    except traci.exceptions.FatalTraCIError as exc:
        print(f"TraCI error: {exc}")
    finally:
        try:
            traci.close()
        except Exception:
            pass

    print(f"Collected {len(trajectories)} vehicle trajectories")
    return trajectories, signal_log, SIGNAL_JUNCTIONS, corridor_len


def plot(trajectories, signal_log, junctions, corridor_len):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "output", "report_20260428_113016")
    os.makedirs(out_dir, exist_ok=True)

    fig, ax = plt.subplots(figsize=(20, 10))

    # ── 1. Draw signal phase bands at each junction ─────────────────────────
    BAND_HEIGHT = 2.5  # metres above/below junction line
    COLORS = {"G": "#2ecc40", "g": "#2ecc40", "y": "#ffdc00", "r": "#ff4136"}

    for sj in junctions:
        tls_id = sj["tls_id"]
        pos_y = sj["position"]
        log = signal_log.get(tls_id, [])
        if not log:
            continue

        # Group consecutive same-state intervals
        intervals = []
        start_t = log[0][0]
        cur_state = log[0][1]
        for t_s, char in log[1:]:
            if char != cur_state:
                intervals.append((start_t, t_s, cur_state))
                start_t = t_s
                cur_state = char
        intervals.append((start_t, log[-1][0] + 1, cur_state))

        for t_start, t_end, state in intervals:
            color = COLORS.get(state.upper(), "#cccccc")
            alpha = 0.45 if state in ("G", "g") else 0.55
            rect = mpatches.FancyBboxPatch(
                (t_start / 60.0, pos_y - BAND_HEIGHT),
                (t_end - t_start) / 60.0, BAND_HEIGHT * 2,
                boxstyle="square,pad=0",
                facecolor=color, edgecolor="none", alpha=alpha,
                zorder=1,
            )
            ax.add_patch(rect)

        # Junction label
        ax.text(-0.25, pos_y, sj["label"], fontsize=9, fontweight="bold",
                ha="right", va="center", color="#333333")

    # ── 2. Draw vehicle trajectories ────────────────────────────────────────
    cmap = plt.cm.RdYlGn
    norm = mcolors.Normalize(vmin=0, vmax=14)

    vids = sorted(trajectories.keys(),
                  key=lambda v: trajectories[v][0][0] if trajectories[v] else 0)

    for vid in vids:
        pts = trajectories[vid]
        if len(pts) < 2:
            continue
        # Only plot within PLOT_DURATION
        pts = [(t, d, s) for t, d, s in pts if t <= PLOT_DURATION]
        if len(pts) < 2:
            continue

        times = [p[0] / 60.0 for p in pts]
        dists = [p[1] for p in pts]
        speeds = [p[2] for p in pts]

        for i in range(len(times) - 1):
            color = cmap(norm(speeds[i]))
            ax.plot([times[i], times[i + 1]], [dists[i], dists[i + 1]],
                    color=color, linewidth=0.6, alpha=0.85, zorder=2)

    # ── 3. Axes formatting ──────────────────────────────────────────────────
    ax.set_xlim(0, PLOT_DURATION / 60.0)
    ax.set_ylim(-2, corridor_len + 2)
    ax.set_xlabel("Time (minutes)", fontsize=14)
    ax.set_ylabel("Distance along corridor (m)", fontsize=14)
    ax.set_title("Distance-Time Diagram with Signal Phases — Eastbound Corridor (v/c = 0.92)",
                 fontsize=16, fontweight="bold")

    # 3-minute interval gridlines
    for t_min in range(0, int(PLOT_DURATION / 60) + 1, 3):
        ax.axvline(x=t_min, color="gray", linewidth=1.2, linestyle="--", alpha=0.4)
        if t_min > 0:
            ax.text(t_min, corridor_len + 1, f"{t_min} min", fontsize=9,
                    ha="center", color="gray")

    # Junction position lines
    for sj in junctions:
        ax.axhline(y=sj["position"], color="black", linewidth=0.5,
                    linestyle=":", alpha=0.5)

    ax.grid(True, alpha=0.15)

    # ── 4. Legend ────────────────────────────────────────────────────────────
    legend_elements = [
        mpatches.Patch(facecolor="#2ecc40", alpha=0.5, label="Signal: GREEN"),
        mpatches.Patch(facecolor="#ffdc00", alpha=0.6, label="Signal: YELLOW"),
        mpatches.Patch(facecolor="#ff4136", alpha=0.6, label="Signal: RED"),
        plt.Line2D([0], [0], color=cmap(norm(0)), linewidth=2, label="Vehicle: stopped"),
        plt.Line2D([0], [0], color=cmap(norm(7)), linewidth=2, label="Vehicle: ~25 km/h"),
        plt.Line2D([0], [0], color=cmap(norm(14)), linewidth=2, label="Vehicle: ~50 km/h"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=10,
              framealpha=0.9)

    # Colorbar for speed
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="vertical", fraction=0.015, pad=0.02)
    cbar.set_label("Speed (m/s)", fontsize=11)
    cbar.set_ticks([0, 3.5, 7, 10.5, 14])
    cbar.set_ticklabels(["0\n(0 km/h)", "3.5\n(12.6)", "7\n(25.2)",
                          "10.5\n(37.8)", "14\n(50.4)"])

    plt.tight_layout()
    path = os.path.join(out_dir, "distance_time_signal_phases.png")
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {path}")
    return path


if __name__ == "__main__":
    traj, sig, juncs, clen = run_and_collect()
    plot(traj, sig, juncs, clen)
