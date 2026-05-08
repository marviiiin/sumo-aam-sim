"""
plot_distance_time.py — Generate distance-time (time-space) diagram for vehicles
on the main E-W corridor. Each line represents one vehicle's trajectory.

Runs a short headless SUMO simulation to collect per-vehicle positions.
"""

import os
import sys
import collections

# Config imports set up SUMO_HOME / sys.path
from config import (
    SUMO_BINARY, SUMOCFG_PATH, STEP_LENGTH_S, VERTIPORTS,
)

import traci
import traci.exceptions

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

# ── Corridor definition ─────────────────────────────────────────────────────
# Eastbound: -18 -> -19 -> -20 -> -21  (west to east)
# Westbound:  21 ->  20 ->  19 ->  18  (east to west)

EASTBOUND_EDGES = ["-18", "-19", "-20", "-21"]
WESTBOUND_EDGES = ["21", "20", "19", "18"]

# Simulation parameters
SIM_DURATION = 3600    # 1 hour for good density of trajectories
COLLECT_INTERVAL = 1   # collect every N steps


def _get_edge_lengths(edges):
    """Get edge lengths from SUMO and compute cumulative offsets."""
    lengths = {}
    for eid in edges:
        try:
            lengths[eid] = traci.lane.getLength(f"{eid}_0")
        except Exception:
            lengths[eid] = 0.0
    offsets = {}
    cum = 0.0
    for eid in edges:
        offsets[eid] = cum
        cum += lengths[eid]
    return lengths, offsets, cum


def run_and_collect():
    """Run SUMO headless and collect per-vehicle trajectory data."""
    cmd = [
        SUMO_BINARY,
        "-c", SUMOCFG_PATH,
        "--step-length", str(STEP_LENGTH_S),
        "--end", str(SIM_DURATION),
        "--seed", "42",
        "--no-step-log", "true",
        "--time-to-teleport", "-1",
    ]

    print(f"Starting SUMO (headless) for trajectory collection ...")
    print(f"Duration: {SIM_DURATION}s")
    traci.start(cmd)

    # Get edge geometry
    eb_lengths, eb_offsets, eb_total = _get_edge_lengths(EASTBOUND_EDGES)
    wb_lengths, wb_offsets, wb_total = _get_edge_lengths(WESTBOUND_EDGES)

    print(f"Eastbound corridor: {eb_total:.1f}m  edges: {EASTBOUND_EDGES}")
    print(f"Westbound corridor: {wb_total:.1f}m  edges: {WESTBOUND_EDGES}")

    eb_edges_set = set(EASTBOUND_EDGES)
    wb_edges_set = set(WESTBOUND_EDGES)

    # Per-vehicle trajectory: vid -> list of (time_s, distance_m, speed_ms)
    eb_trajectories = collections.defaultdict(list)
    wb_trajectories = collections.defaultdict(list)

    step = 0
    try:
        while True:
            traci.simulationStep()
            t = traci.simulation.getTime()

            if step % COLLECT_INTERVAL == 0:
                try:
                    for vid in traci.vehicle.getIDList():
                        eid = traci.vehicle.getRoadID(vid)
                        if eid in eb_edges_set:
                            pos = traci.vehicle.getLanePosition(vid)
                            spd = traci.vehicle.getSpeed(vid)
                            dist = eb_offsets[eid] + pos
                            eb_trajectories[vid].append((t, dist, spd))
                        elif eid in wb_edges_set:
                            pos = traci.vehicle.getLanePosition(vid)
                            spd = traci.vehicle.getSpeed(vid)
                            dist = wb_offsets[eid] + pos
                            wb_trajectories[vid].append((t, dist, spd))
                except traci.exceptions.TraCIException:
                    pass

            step += 1
            if t >= SIM_DURATION:
                break

            if step % 600 == 0:
                print(f"  t={t:.0f}s  EB vehicles tracked: {len(eb_trajectories)}  "
                      f"WB: {len(wb_trajectories)}")

    except traci.exceptions.FatalTraCIError as exc:
        print(f"TraCI error: {exc}")
    finally:
        try:
            traci.close()
        except Exception:
            pass

    print(f"\nCollection complete: {len(eb_trajectories)} EB vehicles, "
          f"{len(wb_trajectories)} WB vehicles")

    return eb_trajectories, wb_trajectories, eb_total, wb_total


def plot_distance_time(eb_traj, wb_traj, eb_total, wb_total):
    """Generate distance-time diagram with individual vehicle trajectories."""
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "output", "report_20260428_113016")
    os.makedirs(out_dir, exist_ok=True)

    # Speed colormap
    cmap = plt.cm.RdYlGn
    norm = mcolors.Normalize(vmin=0, vmax=14)  # 0-50 km/h in m/s

    fig, axes = plt.subplots(2, 1, figsize=(18, 12), sharex=True)
    fig.suptitle("Distance-Time Diagram — Main Corridor (v/c = 0.92)",
                 fontsize=18, fontweight="bold", y=0.98)

    # ── Eastbound ────────────────────────────────────────────────────────────
    ax = axes[0]
    ax.set_title("Eastbound (-18 -> -19 -> -20 -> -21)", fontsize=14, fontweight="bold")
    ax.set_ylabel("Distance along corridor (m)", fontsize=12)

    # Plot a subset of trajectories for clarity (every Nth vehicle)
    eb_vids = sorted(eb_traj.keys(), key=lambda v: eb_traj[v][0][0] if eb_traj[v] else 0)
    plot_count = 0
    for vid in eb_vids:
        pts = eb_traj[vid]
        if len(pts) < 3:
            continue
        times = [p[0] / 60.0 for p in pts]  # minutes
        dists = [p[1] for p in pts]
        speeds = [p[2] for p in pts]

        # Plot as colored line segments
        for i in range(len(times) - 1):
            color = cmap(norm(speeds[i]))
            ax.plot([times[i], times[i+1]], [dists[i], dists[i+1]],
                    color=color, linewidth=0.4, alpha=0.7)
        plot_count += 1

    ax.set_ylim(0, eb_total)
    ax.grid(True, alpha=0.2)
    ax.text(0.02, 0.95, f"{plot_count} vehicles", transform=ax.transAxes,
            fontsize=10, color="gray", va="top")

    # ── Westbound ────────────────────────────────────────────────────────────
    ax = axes[1]
    ax.set_title("Westbound (21 -> 20 -> 19 -> 18)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Time (minutes)", fontsize=12)
    ax.set_ylabel("Distance along corridor (m)", fontsize=12)

    wb_vids = sorted(wb_traj.keys(), key=lambda v: wb_traj[v][0][0] if wb_traj[v] else 0)
    plot_count = 0
    for vid in wb_vids:
        pts = wb_traj[vid]
        if len(pts) < 3:
            continue
        times = [p[0] / 60.0 for p in pts]
        dists = [p[1] for p in pts]
        speeds = [p[2] for p in pts]

        for i in range(len(times) - 1):
            color = cmap(norm(speeds[i]))
            ax.plot([times[i], times[i+1]], [dists[i], dists[i+1]],
                    color=color, linewidth=0.4, alpha=0.7)
        plot_count += 1

    ax.set_ylim(0, wb_total)
    ax.grid(True, alpha=0.2)
    ax.text(0.02, 0.95, f"{plot_count} vehicles", transform=ax.transAxes,
            fontsize=10, color="gray", va="top")

    # Colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=axes, orientation="vertical", fraction=0.02, pad=0.02)
    cbar.set_label("Speed (m/s)", fontsize=12)
    # Add km/h ticks
    cbar.set_ticks([0, 3.5, 7, 10.5, 14])
    cbar.set_ticklabels(["0", "12.6", "25.2", "37.8", "50.4 km/h"])

    plt.tight_layout(rect=[0, 0, 0.95, 0.96])
    path = os.path.join(out_dir, "distance_time_diagram.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nDistance-time diagram saved: {path}")

    # ── Also generate a zoomed view (first 10 minutes) ───────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(16, 12), sharex=True)
    fig.suptitle("Distance-Time Diagram — Zoomed (First 10 Minutes)",
                 fontsize=18, fontweight="bold", y=0.98)

    for idx, (traj_dict, direction, total, edge_label) in enumerate([
        (eb_traj, "Eastbound", eb_total, "-18 -> -19 -> -20 -> -21"),
        (wb_traj, "Westbound", wb_total, "21 -> 20 -> 19 -> 18"),
    ]):
        ax = axes[idx]
        ax.set_title(f"{direction} ({edge_label})", fontsize=14, fontweight="bold")
        ax.set_ylabel("Distance along corridor (m)", fontsize=12)

        vids = sorted(traj_dict.keys(),
                       key=lambda v: traj_dict[v][0][0] if traj_dict[v] else 0)
        count = 0
        for vid in vids:
            pts = traj_dict[vid]
            if len(pts) < 3:
                continue
            # Only plot if vehicle appears in first 10 min
            if pts[0][0] > 600:
                continue
            times = [p[0] / 60.0 for p in pts if p[0] <= 600]
            dists = [p[1] for p in pts if p[0] <= 600]
            speeds = [p[2] for p in pts if p[0] <= 600]
            if len(times) < 2:
                continue

            for i in range(len(times) - 1):
                color = cmap(norm(speeds[i]))
                ax.plot([times[i], times[i+1]], [dists[i], dists[i+1]],
                        color=color, linewidth=0.8, alpha=0.8)
            count += 1

        ax.set_ylim(0, total)
        ax.set_xlim(0, 10)
        ax.grid(True, alpha=0.3)
        ax.text(0.02, 0.95, f"{count} vehicles", transform=ax.transAxes,
                fontsize=10, color="gray", va="top")

    axes[1].set_xlabel("Time (minutes)", fontsize=12)

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=axes, orientation="vertical", fraction=0.02, pad=0.02)
    cbar.set_label("Speed (m/s)", fontsize=12)
    cbar.set_ticks([0, 3.5, 7, 10.5, 14])
    cbar.set_ticklabels(["0", "12.6", "25.2", "37.8", "50.4 km/h"])

    plt.tight_layout(rect=[0, 0, 0.95, 0.96])
    path2 = os.path.join(out_dir, "distance_time_zoomed.png")
    plt.savefig(path2, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Zoomed distance-time diagram saved: {path2}")

    return path, path2


if __name__ == "__main__":
    eb, wb, eb_t, wb_t = run_and_collect()
    plot_distance_time(eb, wb, eb_t, wb_t)
