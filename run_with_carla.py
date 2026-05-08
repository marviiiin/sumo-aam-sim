"""
run_with_carla.py — Run the SUMO–AAMSim simulation with live CARLA visualisation.

Prerequisites
-------------
1. CARLA server must be running:
       cd <CARLA_ROOT> && CarlaUE4.exe -quality-level=Low   (Windows)
       cd <CARLA_ROOT> && ./CarlaUE4.sh                     (Linux)
2. CARLA Python API must be installed:
       pip install <CARLA_ROOT>/PythonAPI/carla/dist/carla-*.whl
3. SUMO network must be generated:
       python generate_network.py

Usage
-----
    python run_with_carla.py [--seed 42] [--duration 3600] [--map Town03]
"""

import argparse
import sys

from simulation import parse_args as _base_parse_args, run as _run
from carla_bridge import CarlaBridge


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        parents=[],
        description="SUMO–AAMSim + CARLA visualisation",
        add_help=True,
    )
    p.add_argument("--seed",     type=int, default=None)
    p.add_argument("--duration", type=int, default=7200)
    p.add_argument("--gui",      action="store_true",
                   help="Also open sumo-gui (alongside CARLA)")
    p.add_argument("--map",      type=str, default=None,
                   help="CARLA map to load, e.g. Town03 (overrides config_carla.py)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Optionally override map from CLI
    if args.map:
        import carla_bridge.config_carla as _cc
        _cc.CARLA_MAP = args.map

    bridge = CarlaBridge()
    try:
        bridge.connect()
    except Exception as exc:
        sys.exit(f"[CARLA] Connection failed: {exc}\nIs the CARLA server running?")

    # Reuse simulation.run(), injecting the CARLA sync callback
    try:
        _run(args, on_step=bridge.sync)
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
