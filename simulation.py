"""
simulation.py — Main SUMO–AAMSim simulation loop.

Usage
-----
    python simulation.py           # headless (sumo)
    python simulation.py --gui     # visual (sumo-gui)
    python simulation.py --seed 42 # fixed random seed for reproducibility

Prerequisite
------------
    Run `python generate_network.py` once first to produce the .net.xml file.
"""

import argparse
import io
import os
import random
import sys
import time

# Force UTF-8 stdout/stderr so Unicode symbols print correctly on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import traci
import traci.exceptions

from config import (
    SIMULATION_DURATION_S,
    STEP_LENGTH_S,
    SUMOCFG_PATH,
    SUMO_BINARY,
    SUMO_GUI_BINARY,
    METRICS_LOG_INTERVAL_S,
    USE_GUI,
    VERTIPORTS,
)
from arrival_handler import EvtolArrivalHandler
from parking_manager import ParkingManager
from metrics_logger import MetricsLogger
from passenger_queue import load_passenger_queues


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SUMO–AAMSim eVTOL ground-traffic simulation")
    p.add_argument("--gui",  action="store_true",
                   help="Launch sumo-gui instead of headless sumo")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducibility (default: random)")
    p.add_argument("--duration", type=int, default=SIMULATION_DURATION_S,
                   help=f"Simulation duration in seconds (default: {SIMULATION_DURATION_S})")
    p.add_argument("--begin", type=int, default=0,
                   help="Simulation begin time in seconds (default: 0)")
    return p.parse_args()


# ── SUMO command builder ──────────────────────────────────────────────────────

def build_sumo_cmd(use_gui: bool, seed: int | None, duration: int, begin: int = 0) -> list[str]:
    binary = SUMO_GUI_BINARY if use_gui else SUMO_BINARY
    if not os.path.isfile(binary):
        sys.exit(
            f"ERROR: SUMO binary not found at '{binary}'.\n"
            f"Check SUMO_HOME={os.environ.get('SUMO_HOME', '<not set>')} "
            f"or install SUMO."
        )
    if not os.path.isfile(SUMOCFG_PATH):
        sys.exit(
            f"ERROR: SUMO config not found at '{SUMOCFG_PATH}'.\n"
            "Run `python generate_network.py` first."
        )

    cmd = [
        binary,
        "-c",            SUMOCFG_PATH,
        "--step-length", str(STEP_LENGTH_S),
        "--end",         str(duration),
        "--no-step-log", "true",
        "--waiting-time-memory", "1000",
        "--time-to-teleport",    "-1",   # disable teleport (let vehicles queue)
    ]
    if begin > 0:
        cmd += ["--begin", str(begin)]
    if use_gui:
        cmd += [
            "--start",          # auto-start without waiting for Play button
            "--delay", "50",    # 50 ms/step delay so traffic is visible (0 = max speed)
        ]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    return cmd


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace, on_step=None) -> None:
    """
    Parameters
    ----------
    args    : parsed CLI namespace
    on_step : optional callable(t, arrival_handlers, parking_managers)
              Called every simulation step after all vertiport updates.
              Visualization bridges (CARLA, Unity) pass their sync method here.
    """
    if args.seed is not None:
        random.seed(args.seed)

    use_gui  = args.gui or USE_GUI
    duration = args.duration

    begin = getattr(args, 'begin', 0)
    sumo_cmd = build_sumo_cmd(use_gui, args.seed, duration, begin)

    # Load data-driven passenger queues
    pax_queues = load_passenger_queues()

    # Initialise handlers (before TraCI start, so random seeds are set)
    arrival_handlers = {
        vp_id: EvtolArrivalHandler(vp_id, cfg, pax_queue=pax_queues.get(vp_id))
        for vp_id, cfg in VERTIPORTS.items()
    }
    parking_managers = {
        vp_id: ParkingManager(vp_id, cfg)
        for vp_id, cfg in VERTIPORTS.items()
    }
    logger = MetricsLogger(VERTIPORTS)

    log_every = max(1, int(METRICS_LOG_INTERVAL_S / STEP_LENGTH_S))  # steps

    # Trajectory data for fundamental diagram / space-time plots
    # Collected every 5 seconds to keep memory reasonable
    _traj_data = {"time": [], "edge": [], "speed": [], "density": [],
                  "flow": [], "veh_pos": []}

    print(f"\nStarting SUMO ({'gui' if use_gui else 'headless'}) …")
    print(f"Duration: {duration}s   Step: {STEP_LENGTH_S}s   "
          f"Seed: {args.seed if args.seed is not None else 'random'}\n")

    wall_start = time.perf_counter()
    traci.start(sumo_cmd)

    step = 0
    try:
        while True:
            traci.simulationStep()
            t = traci.simulation.getTime()

            # ── Per-vertiport updates ─────────────────────────────────────────
            for vp_id in VERTIPORTS:
                arrival_handlers[vp_id].step(t)
                parking_managers[vp_id].step(t)

            # ── Visualization bridge hook ─────────────────────────────────────
            if on_step is not None:
                try:
                    on_step(t, arrival_handlers, parking_managers)
                except Exception as exc:
                    print(f"[VIZ WARN] on_step error at t={t:.1f}s: {exc}")

            # ── Trajectory collection (every 5s) ────────────────────────────
            if step % 5 == 0:
                try:
                    _collect_trajectories(t, _traj_data)
                except Exception:
                    pass

            # ── Metrics snapshot ──────────────────────────────────────────────
            if step % log_every == 0:
                logger.log(t, arrival_handlers, parking_managers)

            step += 1

            # Honour the configured end time
            if t >= duration:
                break

    except traci.exceptions.FatalTraCIError as exc:
        print(f"\nTraCI connection lost: {exc}")
    finally:
        try:
            traci.close()
        except Exception:
            pass
        logger.close()

    wall_elapsed = time.perf_counter() - wall_start
    _print_summary(arrival_handlers, parking_managers, wall_elapsed, step)

    # Generate analysis report with passenger metrics and traffic diagrams
    try:
        from report import generate_report
        generate_report(pax_queues, arrival_handlers, parking_managers,
                        _traj_data, duration)
    except Exception as exc:
        print(f"[WARN] Report generation failed: {exc}")
        import traceback
        traceback.print_exc()


def _print_summary(
    arrival_handlers: dict,
    parking_managers: dict,
    wall_elapsed: float,
    steps: int,
) -> None:
    print("\n" + "=" * 60)
    print("SIMULATION SUMMARY")
    print("=" * 60)
    print(f"  Wall-clock runtime : {wall_elapsed:.1f} s  ({steps} steps)")
    for vp_id, ah in arrival_handlers.items():
        pm = parking_managers[vp_id]
        print(f"\n  {VERTIPORTS[vp_id]['name']}  [{vp_id}]")
        print(f"    eVTOL arrivals     : {ah.total_arrivals}")
        print(f"    Passengers served  : {ah.total_passengers}")
        print(f"    Rental cars added  : {ah.total_rentals}")
        print(f"    Spillback episodes : {pm.spillback_events}")
    print("=" * 60)


# ── Trajectory collection ─────────────────────────────────────────────────────

_MAIN_EDGES = ["-18", "-19", "-20", "-21", "18", "19", "20", "21"]


def _collect_trajectories(t: float, traj: dict) -> None:
    """Collect per-edge traffic data and per-vehicle positions."""
    for eid in _MAIN_EDGES:
        try:
            n_veh = traci.edge.getLastStepVehicleNumber(eid)
            mean_speed = traci.edge.getLastStepMeanSpeed(eid)
            length = traci.lane.getLength(f"{eid}_0")
            n_lanes = traci.edge.getLaneNumber(eid)
            density = (n_veh / (length * n_lanes / 1000.0)) if length > 0 else 0
            flow = density * mean_speed * 3.6
            traj["time"].append(t)
            traj["edge"].append(eid)
            traj["speed"].append(mean_speed)
            traj["density"].append(density)
            traj["flow"].append(flow)
        except Exception:
            pass

    try:
        for vid in traci.vehicle.getIDList():
            eid = traci.vehicle.getRoadID(vid)
            if eid in _MAIN_EDGES:
                pos = traci.vehicle.getLanePosition(vid)
                spd = traci.vehicle.getSpeed(vid)
                traj["veh_pos"].append((t, vid, eid, pos, spd))
    except Exception:
        pass


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run(parse_args())
