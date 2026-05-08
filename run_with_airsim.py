"""
run_with_airsim.py — Run the SUMO–AAMSim simulation with live AirSim/UE5
                     visualisation of every eVTOL flight.

Prerequisites
-------------
1.  AirSim settings.json must declare the eVTOL fleet. Generate it with:
        python "Documents/Unreal Projects/evttolll/Scripts/evtol_settings.py" --dual
    (or edit ~/Documents/AirSim/settings.json manually to add eVTOL1, eVTOL2, …)

2.  UE5 editor with the `evttolll` project must be open and Play pressed
    (this starts the AirSim RPC server on port 41451).

3.  SUMO network must be generated:
        python generate_network.py

4.  The airsim Python client must be installed:
        pip install airsim

5.  The CesiumGeoreference actor's Origin Latitude/Longitude in NewMap.umap
    must match CESIUM_ORIGIN_LAT/LON in airsim_bridge/config_airsim.py.

Usage
-----
    python run_with_airsim.py                 # real AirSim + UE5
    python run_with_airsim.py --dry-run       # mock AirSim (no UE5 needed)
    python run_with_airsim.py --seed 42 --duration 900 --dry-run
"""

import argparse
import sys

from simulation import run as _run
from airsim_bridge import AirSimBridge


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SUMO–AAMSim + AirSim/UE5 eVTOL visualisation",
    )
    p.add_argument("--seed",     type=int, default=None)
    p.add_argument("--duration", type=int, default=7200,
                   help="Simulation duration in seconds (default 7200)")
    p.add_argument("--gui",      action="store_true",
                   help="Also open sumo-gui alongside AirSim")
    p.add_argument("--dry-run",  action="store_true",
                   help="Use a mock AirSim client — no UE5 / AirSim RPC needed. "
                        "Proves the full SUMO↔bridge plumbing without a renderer.")
    p.add_argument("--mirror",   action="store_true",
                   help="Force-enable the ground-vehicle mirror (SUMO cars "
                        "spawned as UE5 actors), overriding GROUND_CAR_ENABLED "
                        "in config_airsim.py.")
    p.add_argument("--realtime-factor", type=float, default=1.0,
                   help="Wall-clock pacing: 1.0 = real-time (default), "
                        "0.5 = 2× faster, 2.0 = half-speed.  Set to 0 to "
                        "disable throttling entirely (only useful in dry-run).")
    return p.parse_args()


def _install_mock_airsim() -> None:
    """
    Pre-install a synthetic ``airsim`` module into sys.modules so that
    AirSimBridge.connect() can import it without the real package, then
    monkey-patch MultirotorClient to point at our MockAirSimClient.
    """
    from airsim_bridge.mock_client import install_fake_airsim_module
    install_fake_airsim_module()


def main() -> None:
    args = parse_args()

    if args.dry_run:
        print("[AirSim] DRY-RUN — mock client, no UE5 connection.")
        _install_mock_airsim()

    if args.mirror:
        # Override the config flag before the bridge (and VehicleMirror)
        # read it.  Importing config_airsim happens at bridge import time,
        # so mutate the module attribute here.
        import airsim_bridge.config_airsim as cfg
        cfg.GROUND_CAR_ENABLED = True
        print("[AirSim] --mirror: ground-vehicle mirror enabled")

    # Dry-run doesn't need wall-clock throttling.
    factor = 0.0 if args.dry_run else args.realtime_factor
    bridge = AirSimBridge(realtime_factor=factor)
    try:
        bridge.connect()
    except Exception as exc:
        sys.exit(
            f"[AirSim] Connection failed: {exc}\n"
            f"Is the UE5 editor open and Play pressed for the evttolll "
            f"project?  (Or re-run with --dry-run to skip AirSim.)"
        )

    try:
        _run(args, on_step=bridge.sync)
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
