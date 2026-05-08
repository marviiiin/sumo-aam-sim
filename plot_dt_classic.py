"""
plot_dt_classic.py — Publication-quality distance-time (time-space) diagram
with prominent traffic signal phase bands.

Textbook-style: clean white background, full-width signal bands,
clearly visible vehicle trajectories with speed colouring.
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
import matplotlib.collections as mcoll
import numpy as np

# ── Corridor (eastbound) ────────────────────────────────────────────────────
EDGES = ["-18", "-19", "-20", "-21"]

SIGNAL_JUNCTIONS = [
    {"tls_id": "189", "link_idx": 10, "label": "Signal 1\n(VP-Alpha)"},
    {"tls_id": "532", "link_idx": 7,  "label": "Signal 2"},
]

SIM_DURATION   = 420   # 7 min sim to let traffic warm up
PLOT_START     = 60    # skip first 60s warm-up
PLOT_END       = 360   # plot from 60s to 360s = 5 min window
PLOT_WINDOW    = PLOT_END - PLOT_START  # 300s = 5 min


def run_and_collect():
    cmd = [
        SUMO_BINARY, "-c", SUMOCFG_PATH,
        "--step-length", str(STEP_LENGTH_S),
        "--end", str(SIM_DURATION),
        "--seed", "42",
        "--no-step-log", "true",
        "--time-to-teleport", "-1",
    ]
    print("Starting SUMO for distance-time diagram ...")
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

    # Junction positions
    junc_positions = {
        "189": offsets["-19"] + lengths["-19"],
        "532": offsets["-21"] + lengths["-21"],
    }
    for sj in SIGNAL_JUNCTIONS:
        sj["position"] = junc_positions[sj["tls_id"]]

    print(f"Corridor length: {corridor_len:.1f} m")
    for sj in SIGNAL_JUNCTIONS:
        print(f"  {sj['label'].replace(chr(10),' ')}: {sj['position']:.1f} m")

    edges_set = set(EDGES)
    trajectories = collections.defaultdict(list)
    signal_log = collections.defaultdict(list)

    step = 0
    try:
        while True:
            traci.simulationStep()
            t = traci.simulation.getTime()

            # Vehicle positions
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

            # Signal states
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


def _build_signal_intervals(log, t_start, t_end):
    """Convert raw signal log to list of (start_s, end_s, state_char) within window."""
    intervals = []
    if not log:
        return intervals

    # Group consecutive same-state intervals
    raw_intervals = []
    s_t = log[0][0]
    cur = log[0][1]
    for t_s, char in log[1:]:
        if char != cur:
            raw_intervals.append((s_t, t_s, cur))
            s_t = t_s
            cur = char
    raw_intervals.append((s_t, log[-1][0] + 1, cur))

    # Clip to plot window
    for a, b, state in raw_intervals:
        if b <= t_start or a >= t_end:
            continue
        intervals.append((max(a, t_start), min(b, t_end), state))

    return intervals


def plot(trajectories, signal_log, junctions, corridor_len):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "output", "report_20260428_113016")
    os.makedirs(out_dir, exist_ok=True)

    # ── Figure setup ──────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(16, 9))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # ── 1. Signal phase bands (full-width, prominent) ─────────────────────
    BAND_HALF = corridor_len * 0.04   # 4% of corridor height each side
    SIG_COLORS = {
        "G": "#27ae60", "g": "#27ae60",   # green
        "y": "#f1c40f",                     # yellow
        "r": "#e74c3c",                     # red
    }
    SIG_ALPHA = {"G": 0.35, "g": 0.35, "y": 0.50, "r": 0.40}

    for sj in junctions:
        tls_id = sj["tls_id"]
        pos_y = sj["position"]
        intervals = _build_signal_intervals(
            signal_log.get(tls_id, []), PLOT_START, PLOT_END)

        for t_start, t_end, state in intervals:
            color = SIG_COLORS.get(state.upper(), "#cccccc")
            alpha = SIG_ALPHA.get(state, 0.3)
            # Draw band at junction position
            rect = mpatches.Rectangle(
                (t_start, pos_y - BAND_HALF),
                t_end - t_start,
                BAND_HALF * 2,
                facecolor=color, edgecolor="none", alpha=alpha,
                zorder=1,
            )
            ax.add_patch(rect)

        # Junction horizontal reference line
        ax.axhline(y=pos_y, color="#555555", linewidth=0.8,
                    linestyle="-", alpha=0.6, zorder=1)

    # ── 2. Vehicle trajectories ───────────────────────────────────────────
    cmap = plt.cm.RdYlGn
    norm = mcolors.Normalize(vmin=0, vmax=14)  # 0-50 km/h

    vids = sorted(trajectories.keys(),
                  key=lambda v: trajectories[v][0][0] if trajectories[v] else 0)

    traj_count = 0
    for vid in vids:
        pts = trajectories[vid]
        if len(pts) < 2:
            continue
        # Filter to plot window
        pts = [(t, d, s) for t, d, s in pts if PLOT_START <= t <= PLOT_END]
        if len(pts) < 2:
            continue

        times = np.array([p[0] for p in pts])
        dists = np.array([p[1] for p in pts])
        speeds = np.array([p[2] for p in pts])

        # Draw as colored line segments using LineCollection for efficiency
        points = np.column_stack([times, dists]).reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        colors = [cmap(norm(s)) for s in speeds[:-1]]

        lc = mcoll.LineCollection(segments, colors=colors,
                                  linewidths=0.9, alpha=0.85, zorder=2)
        ax.add_collection(lc)
        traj_count += 1

    print(f"Plotted {traj_count} vehicle trajectories in [{PLOT_START}s, {PLOT_END}s]")

    # ── 3. Axes formatting ────────────────────────────────────────────────
    ax.set_xlim(PLOT_START, PLOT_END)
    ax.set_ylim(-3, corridor_len + 5)

    # Time axis: ticks every 30 seconds, labels every 60 seconds
    major_ticks = np.arange(PLOT_START, PLOT_END + 1, 60)
    minor_ticks = np.arange(PLOT_START, PLOT_END + 1, 30)
    ax.set_xticks(major_ticks)
    ax.set_xticks(minor_ticks, minor=True)
    ax.set_xticklabels([f"{int(t)}s\n({(t-PLOT_START)/60:.0f} min)" for t in major_ticks],
                       fontsize=11)

    ax.set_xlabel("Simulation Time", fontsize=14, fontweight="bold", labelpad=10)
    ax.set_ylabel("Distance Along Corridor (m)", fontsize=14,
                  fontweight="bold", labelpad=10)

    ax.set_title(
        "Time-Space Diagram with Signal Phases\n"
        "Eastbound Corridor  |  v/c = 0.92  |  5-Minute Window",
        fontsize=16, fontweight="bold", pad=15
    )

    # Grid
    ax.grid(True, which="major", axis="x", color="#cccccc",
            linewidth=0.8, linestyle="-", alpha=0.5)
    ax.grid(True, which="minor", axis="x", color="#e0e0e0",
            linewidth=0.5, linestyle="--", alpha=0.4)
    ax.grid(True, which="major", axis="y", color="#e8e8e8",
            linewidth=0.5, linestyle="-", alpha=0.3)

    # Junction labels on right y-axis
    for sj in junctions:
        ax.annotate(
            sj["label"], xy=(PLOT_END + 2, sj["position"]),
            fontsize=10, fontweight="bold", color="#333333",
            ha="left", va="center",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor="#999999", alpha=0.9),
        )

    # ── 4. Legend ─────────────────────────────────────────────────────────
    legend_elements = [
        mpatches.Patch(facecolor="#27ae60", alpha=0.45, label="GREEN phase"),
        mpatches.Patch(facecolor="#f1c40f", alpha=0.55, label="YELLOW phase"),
        mpatches.Patch(facecolor="#e74c3c", alpha=0.50, label="RED phase"),
        plt.Line2D([0], [0], color=cmap(norm(0)), linewidth=2.5,
                   label="Stopped (0 km/h)"),
        plt.Line2D([0], [0], color=cmap(norm(7)), linewidth=2.5,
                   label="Mid-speed (~25 km/h)"),
        plt.Line2D([0], [0], color=cmap(norm(14)), linewidth=2.5,
                   label="Free-flow (~50 km/h)"),
    ]
    legend = ax.legend(
        handles=legend_elements, loc="upper left", fontsize=10,
        framealpha=0.95, edgecolor="#cccccc", fancybox=True,
        title="Legend", title_fontsize=11,
    )
    legend.get_title().set_fontweight("bold")

    # ── 5. Colorbar ───────────────────────────────────────────────────────
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation="vertical",
                        fraction=0.018, pad=0.08, aspect=30)
    cbar.set_label("Vehicle Speed (m/s)", fontsize=12, fontweight="bold")
    cbar.set_ticks([0, 3.5, 7, 10.5, 14])
    cbar.set_ticklabels(["0\n(0 km/h)", "3.5\n(13 km/h)", "7\n(25 km/h)",
                          "10.5\n(38 km/h)", "14\n(50 km/h)"])

    # ── 6. Info box ───────────────────────────────────────────────────────
    info_text = (
        f"Corridor: {corridor_len:.0f} m\n"
        f"Vehicles plotted: {traj_count}\n"
        f"Window: {PLOT_START}s - {PLOT_END}s"
    )
    ax.text(0.99, 0.02, info_text, transform=ax.transAxes,
            fontsize=9, color="#666666", ha="right", va="bottom",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#f8f8f8",
                      edgecolor="#dddddd", alpha=0.9))

    # Spine styling
    for spine in ax.spines.values():
        spine.set_color("#999999")
        spine.set_linewidth(0.8)
    ax.tick_params(axis="both", which="major", labelsize=11, colors="#333333")

    plt.tight_layout()
    path = os.path.join(out_dir, "dt_classic.png")
    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"\nSaved: {path}")
    return path


if __name__ == "__main__":
    traj, sig, juncs, clen = run_and_collect()
    plot(traj, sig, juncs, clen)
