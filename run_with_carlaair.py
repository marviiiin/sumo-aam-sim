"""
run_with_carlaair.py — Run SUMO-AAMSim with CarlaAir 3D visualisation.

CarlaAir provides unified air-ground co-simulation:
  - CARLA (port 2000): ground vehicles mirrored from SUMO
  - AirSim (port 41451): eVTOL drone flights between vertiports

Prerequisites
-------------
1. CarlaAir must be running (Town10HD):
       cd CarlaAir-v0.1.7-Windows11-x86_64
       powershell -File CarlaAir.ps1 Town10HD
2. SUMO network must be generated:
       python generate_network.py
3. conda activate carlaAir  (carla + airsim + traci)

Usage
-----
    python run_with_carlaair.py
    python run_with_carlaair.py --gui --seed 42 --duration 600
"""

import argparse
import sys

from simulation import run as _run
from carlaair_bridge import CarlaAirBridge


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SUMO-AAMSim + CarlaAir (CARLA ground + AirSim drone)",
    )
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--duration", type=int, default=900,
                   help="Simulation duration in seconds (default: 900 = 15 min)")
    p.add_argument("--gui", action="store_true",
                   help="Also open sumo-gui alongside CarlaAir")
    p.add_argument("--begin", type=int, default=0,
                   help="Simulation begin time in seconds (default: 0)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    bridge = CarlaAirBridge()
    try:
        bridge.connect()
    except Exception as exc:
        sys.exit(
            f"[CarlaAir] Connection failed: {exc}\n"
            f"Is CarlaAir running?  Launch with:\n"
            f"  cd Desktop/CarlaAir/CarlaAir-v0.1.7-Windows11-x86_64\n"
            f"  powershell -File CarlaAir.ps1 Town10HD"
        )

    try:
        _run(args, on_step=bridge.sync)
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
