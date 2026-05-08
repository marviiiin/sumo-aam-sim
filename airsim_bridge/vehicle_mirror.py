"""
vehicle_mirror.py — Mirror SUMO ground vehicles as UE5 actors via AirSim's
simAddVehicle / simSetVehiclePose RPCs.

Each SUMO step:
  1. Query traci for all active vehicle IDs + positions + heading
  2. Spawn a SimpleFlight vehicle for any SUMO vehicle we haven't seen yet
  3. Teleport every existing mirror vehicle to its SUMO vehicle's pose
  4. Park vehicles whose SUMO IDs left the simulation far offscreen

Why simAddVehicle instead of simSpawnObject?
--------------------------------------------
The evttolll AirSim build's simSpawnObject RPC hangs indefinitely for all
asset types (blueprints AND static meshes).  simAddVehicle('SimpleFlight')
works instantly (<0.1 s) and produces a visible drone pawn that can be
repositioned with simSetVehiclePose (teleport=True).

The drones won't look like cars, but they're visible 3-D objects at the
correct road positions — proving the SUMO ↔ UE5 bridge pipeline works.
Replace with real car meshes once simSpawnObject is fixed or a car asset
pack is imported.

Coordinate mapping
------------------
SUMO network is 2-D with x = east, y = north, in metres.  The bridge maps
SUMO (x, y) directly to AirSim NED (north = sy, east = sx), anchored at
the CesiumGeoreference origin (Tampa Downtown in the default config).
"""

import math

from . import config_airsim as _cfg
from .config_airsim import (
    MIRROR_MAX_VEHICLES, MIRROR_SPAWNS_PER_TICK, MIRROR_MAX_SPAWN_FAILURES,
    SUMO_COORD_FLIP_Y, SUMO_X_OFFSET_M, SUMO_Y_OFFSET_M,
    VERBOSE,
)

# Vehicle type to spawn via simAddVehicle.  SimpleFlight is guaranteed to
# exist in every AirSim build and is the lightest pawn type.
_VEHICLE_TYPE = "SimpleFlight"

# When a SUMO vehicle leaves, we can't truly delete an AirSim vehicle at
# runtime.  Instead we teleport it far below ground so it's invisible,
# and recycle the slot for the next SUMO vehicle that needs one.
_PARKED_POS = (0.0, 0.0, 500.0)  # NED: 500 m underground


class VehicleMirror:
    """Mirrors SUMO vehicles into UE5 as lightweight drone pawns."""

    def __init__(self, client) -> None:
        self.client = client
        self.enabled = _cfg.GROUND_CAR_ENABLED
        self._mirrored: dict[str, str] = {}  # sumo_vid → vehicle_name
        self._recycled: list[str] = []        # vehicle names parked offscreen
        self._seq = 0
        self._traci = None
        self._probed = False
        self._spawn_failures = 0

    # ── Public ────────────────────────────────────────────────────────────────

    def tick(self) -> None:
        """Called once per SUMO step."""
        if not self.enabled:
            return

        if self._traci is None:
            try:
                import traci
                self._traci = traci
            except ImportError:
                print("[Mirror] traci not available — mirror disabled")
                self.enabled = False
                return

        if not self._probed:
            self._probe()
            self._probed = True

        traci = self._traci

        # 1. Snapshot active vehicles (skip eVTOL routing vehicles)
        try:
            active_ids = {v for v in traci.vehicle.getIDList()
                          if not v.startswith("evtol_")}
        except Exception:
            return

        # 2. Spawn / recycle for new SUMO vehicles
        spawns_this_tick = 0
        for vid in active_ids:
            if vid in self._mirrored:
                continue
            if len(self._mirrored) >= MIRROR_MAX_VEHICLES:
                break
            if spawns_this_tick >= MIRROR_SPAWNS_PER_TICK:
                break
            if self._assign(vid):
                spawns_this_tick += 1

        # 3. Move existing, park departed
        for vid, veh_name in list(self._mirrored.items()):
            if vid not in active_ids:
                self._park(vid, veh_name)
                continue
            try:
                sx, sy = traci.vehicle.getPosition(vid)
                angle = traci.vehicle.getAngle(vid)
                self._move(veh_name, sx, sy, angle)
            except Exception:
                pass

    def destroy_all(self) -> None:
        """Park every mirrored vehicle offscreen on shutdown."""
        for vid, veh_name in list(self._mirrored.items()):
            self._park(vid, veh_name, announce=False)
        self._mirrored.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _probe(self) -> None:
        """One-time startup: test that simAddVehicle works."""
        import airsim
        test_name = "_mirror_probe_"
        pose = airsim.Pose(airsim.Vector3r(*_PARKED_POS),
                           airsim.to_quaternion(0, 0, 0))
        try:
            ok = self.client.simAddVehicle(test_name, _VEHICLE_TYPE, pose)
            if ok:
                print(f"[Mirror] simAddVehicle('{_VEHICLE_TYPE}') works — "
                      f"mirror enabled (max {MIRROR_MAX_VEHICLES} vehicles)")
                # Park the probe underground; recycle its slot
                self._recycled.append(test_name)
            else:
                print(f"[Mirror] simAddVehicle returned False — mirror disabled")
                self.enabled = False
        except Exception as exc:
            print(f"[Mirror] simAddVehicle probe failed: {exc} — disabled")
            self.enabled = False

    def _assign(self, sumo_vid: str) -> bool:
        """Assign a UE5 vehicle to a SUMO vehicle (recycle or spawn new)."""
        if self._recycled:
            veh_name = self._recycled.pop()
            self._mirrored[sumo_vid] = veh_name
            if VERBOSE:
                print(f"[Mirror] REUSE  {sumo_vid} → {veh_name}")
            return True

        # Spawn a fresh SimpleFlight vehicle
        import airsim
        self._seq += 1
        veh_name = f"sumo_car_{self._seq:04d}"
        pose = airsim.Pose(airsim.Vector3r(*_PARKED_POS),
                           airsim.to_quaternion(0, 0, 0))
        try:
            ok = self.client.simAddVehicle(veh_name, _VEHICLE_TYPE, pose)
        except Exception as exc:
            self._spawn_failures += 1
            print(f"[Mirror] simAddVehicle failed "
                  f"(#{self._spawn_failures}/{MIRROR_MAX_SPAWN_FAILURES}): {exc}")
            if self._spawn_failures >= MIRROR_MAX_SPAWN_FAILURES:
                print("[Mirror] too many failures — disabling mirror")
                self.enabled = False
            return False

        if not ok:
            self._spawn_failures += 1
            if self._spawn_failures >= MIRROR_MAX_SPAWN_FAILURES:
                print("[Mirror] too many False returns — disabling mirror")
                self.enabled = False
            return False

        self._spawn_failures = 0
        self._mirrored[sumo_vid] = veh_name
        if VERBOSE:
            print(f"[Mirror] SPAWN  {sumo_vid} → {veh_name}")
        return True

    def _move(self, veh_name: str, sx: float, sy: float, angle_deg: float) -> None:
        import airsim
        ned_east  = sx + SUMO_X_OFFSET_M
        ned_north = (-sy if SUMO_COORD_FLIP_Y else sy) + SUMO_Y_OFFSET_M

        yaw_rad = math.radians((angle_deg + 180.0) % 360.0 - 180.0)

        pose = airsim.Pose(
            airsim.Vector3r(ned_north, ned_east, 0.0),
            airsim.to_quaternion(0.0, 0.0, yaw_rad),
        )
        try:
            self.client.simSetVehiclePose(pose, True, vehicle_name=veh_name)
        except Exception:
            pass

    def _park(self, sumo_vid: str, veh_name: str, announce: bool = True) -> None:
        """Teleport underground and add to recycle pool."""
        import airsim
        pose = airsim.Pose(airsim.Vector3r(*_PARKED_POS),
                           airsim.to_quaternion(0, 0, 0))
        try:
            self.client.simSetVehiclePose(pose, True, vehicle_name=veh_name)
        except Exception:
            pass
        self._mirrored.pop(sumo_vid, None)
        self._recycled.append(veh_name)
        if announce and VERBOSE:
            print(f"[Mirror] PARK   {sumo_vid} ({veh_name})")
