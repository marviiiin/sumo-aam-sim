"""
run_with_unity.py — Run the SUMO–AAMSim simulation, streaming state to Unity via UDP.

Prerequisites
-------------
1. Unity project is open with the Assets/Scripts/ from unity_bridge/ imported.
2. A GameObject in the scene has SumoReceiver, TrafficManager, EvtolManager
   and (optionally) VertiportHUD components.
3. Press Play in the Unity Editor.
4. Then start this script.

Usage
-----
    python run_with_unity.py [--seed 42] [--duration 3600] [--host 127.0.0.1] [--port 9000]
    python run_with_unity.py --every 2    # send every 2nd step (reduce bandwidth)
"""

import argparse

from simulation import run as _run
from unity_bridge import UnityBridge


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SUMO–AAMSim → Unity UDP streamer")
    p.add_argument("--seed",     type=int,   default=None)
    p.add_argument("--duration", type=int,   default=7200)
    p.add_argument("--gui",      action="store_true",
                   help="Also open sumo-gui while streaming to Unity")
    p.add_argument("--host",     type=str,   default="127.0.0.1",
                   help="Unity UDP host (default 127.0.0.1)")
    p.add_argument("--port",     type=int,   default=9000,
                   help="Unity UDP port (default 9000)")
    p.add_argument("--every",    type=int,   default=1,
                   help="Send every N steps (default 1 = every step)")
    return p.parse_args()


def main() -> None:
    args  = parse_args()
    bridge = UnityBridge(host=args.host, port=args.port, send_every=args.every)
    try:
        _run(args, on_step=bridge.sync)
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
