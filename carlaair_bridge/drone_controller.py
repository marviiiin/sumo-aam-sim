"""
drone_controller.py — Single-drone flight controller for CarlaAir.

Uses simSetVehiclePose for reliable drone positioning along flight paths.
AirSim's async movement commands are unreliable after direction changes,
so we interpolate the position ourselves and teleport the drone each tick.

Phases: IDLE -> FLYING -> DESCEND -> LANDED
        -> RETURN_FLY -> RETURN_LAND -> IDLE
"""

import math
import time
from enum import Enum

import airsim
import traci
import traci.exceptions

from .config import (
    DRONE_VEHICLE,
    CRUISE_ALT_M, CRUISE_SPEED_MS, CLIMB_SPEED_MS,
    POS_TOL_M, MIN_PHASE_S,
)
from .coordinate_map import (
    sumo_to_airsim, vertiport_airsim,
    vertiport_ground_z_airsim, home_ground_z_airsim,
)


class Phase(Enum):
    IDLE        = "idle"
    FLYING      = "flying"
    DESCEND     = "descend"
    LANDED      = "landed"
    RETURN_FLY  = "return_fly"
    RETURN_LAND = "return_land"


class DroneController:
    """
    Controls a single AirSim drone that mirrors eVTOL flights.
    Uses pose interpolation for reliable movement.
    """

    def __init__(self, client) -> None:
        self.client = client
        self.vn = DRONE_VEHICLE

        self.phase = Phase.IDLE
        self._phase_start = 0.0

        # Per-location ground Z (AirSim NED)
        self._home_ground_z = home_ground_z_airsim()

        # Reset drone to known state
        try:
            client.reset()
            client.enableApiControl(True, vehicle_name=self.vn)
            client.armDisarm(True, vehicle_name=self.vn)
        except Exception:
            pass

        # Home = AirSim origin at ground level
        self.home_ned = (0.0, 0.0, self._home_ground_z)

        # Current interpolated position
        self._pos = list(self.home_ned)
        self._yaw = 0.0

        # Per-flight ground/cruise altitudes (set in _start_next)
        self._dest_ground_z = self._home_ground_z
        self._cruise_z = self._home_ground_z - CRUISE_ALT_M

        print(f"[Drone] Home NED: ({self.home_ned[0]:.1f}, "
              f"{self.home_ned[1]:.1f}, {self.home_ned[2]:.1f})  "
              f"home_ground_z={self._home_ground_z:.1f}")

        # Current flight
        self.flight_id: str | None = None
        self.evtol_sumo_id: str | None = None
        self.origin_vp: str | None = None
        self.dest_vp: str | None = None
        self.passengers = 0
        self.dest_ned: tuple[float, float, float] = (0, 0, 0)

        self._queue: list[dict] = []

    def queue_flight(self, flight_id: str, origin_vp: str, dest_vp: str,
                     passengers: int) -> None:
        self._queue.append({
            "flight_id": flight_id,
            "evtol_sumo_id": flight_id,
            "origin_vp": origin_vp,
            "dest_vp": dest_vp,
            "passengers": passengers,
        })
        print(f"[Drone] Queued flight {flight_id}: {origin_vp} -> {dest_vp} "
              f"({passengers} pax)  [queue={len(self._queue)}]")

    def tick(self) -> None:
        """Advance state machine. Call once per SUMO step (~1s)."""
        if self.phase == Phase.IDLE:
            if self._queue:
                self._start_next()
            return

        age = time.monotonic() - self._phase_start

        if self.phase == Phase.FLYING:
            # Determine target: track eVTOL if alive, else fly to destination
            if self._is_evtol_alive():
                sumo_pos = self._get_evtol_sumo_position()
                if sumo_pos is not None:
                    sx, sy = sumo_pos
                    tx, ty, _ = sumo_to_airsim(sx, sy)
                    tz = self._cruise_z
                else:
                    tx, ty, tz = self.dest_ned[0], self.dest_ned[1], self._cruise_z
            else:
                tx, ty, tz = self.dest_ned[0], self.dest_ned[1], self._cruise_z

            # Move toward target
            arrived = self._move_toward(tx, ty, tz, CRUISE_SPEED_MS)

            # Check if at destination (only when eVTOL is gone)
            dx = self._pos[0] - self.dest_ned[0]
            dy = self._pos[1] - self.dest_ned[1]
            dist_to_dest = math.hypot(dx, dy)

            if not self._is_evtol_alive() and dist_to_dest < POS_TOL_M:
                print(f"[Drone] Arrived at {self.dest_vp} (dist={dist_to_dest:.0f}m)")
                self._transition(Phase.DESCEND)
            elif age >= 120.0:
                print(f"[Drone] Flight timeout (dist={dist_to_dest:.0f}m)")
                self._transition(Phase.DESCEND)

        elif self.phase == Phase.DESCEND:
            # Descend to actual ground at destination vertiport
            tx, ty = self.dest_ned[0], self.dest_ned[1]
            tz = self._dest_ground_z
            arrived = self._move_toward(tx, ty, tz, CLIMB_SPEED_MS)
            if arrived or age >= 15.0:
                # Snap to ground
                self._pos = [tx, ty, tz]
                self._set_pose()
                print(f"[Drone] LANDED {self.flight_id} at {self.dest_vp} "
                      f"({self.passengers} pax)  ground_z={tz:.1f}")
                self._transition(Phase.LANDED)

        elif self.phase == Phase.LANDED:
            # Stay on the ground for 5 seconds so it's visually clear
            if age < 5.0:
                return
            print(f"[Drone] Returning home from {self.dest_vp} ...")
            self._clear()
            self._transition(Phase.RETURN_FLY)

        elif self.phase == Phase.RETURN_FLY:
            # Use home cruise altitude for return
            home_cruise_z = self._home_ground_z - CRUISE_ALT_M
            tx, ty, tz = self.home_ned[0], self.home_ned[1], home_cruise_z
            arrived = self._move_toward(tx, ty, tz, CRUISE_SPEED_MS)
            if arrived or age >= 60.0:
                self._transition(Phase.RETURN_LAND)

        elif self.phase == Phase.RETURN_LAND:
            tx, ty, tz = self.home_ned[0], self.home_ned[1], self._home_ground_z
            arrived = self._move_toward(tx, ty, tz, CLIMB_SPEED_MS)
            if arrived or age >= 15.0:
                print(f"[Drone] Returned home. Ready for next flight.")
                self._transition(Phase.IDLE)

    def land_now(self) -> None:
        """Emergency land on shutdown."""
        try:
            self.client.landAsync(vehicle_name=self.vn)
        except Exception:
            pass

    # -- Movement ---------------------------------------------------------------

    def _move_toward(self, tx: float, ty: float, tz: float,
                     speed: float, dt: float = 1.0) -> bool:
        """
        Move self._pos toward (tx, ty, tz) at given speed.
        Updates the AirSim drone pose. Returns True if arrived.
        """
        dx = tx - self._pos[0]
        dy = ty - self._pos[1]
        dz = tz - self._pos[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        if dist < 1.0:
            self._pos = [tx, ty, tz]
            self._set_pose()
            return True

        # Move at most speed*dt meters this tick
        step = min(speed * dt, dist)
        ratio = step / dist
        self._pos[0] += dx * ratio
        self._pos[1] += dy * ratio
        self._pos[2] += dz * ratio

        # Update yaw to face direction of travel
        horiz = math.hypot(dx, dy)
        if horiz > 1.0:
            self._yaw = math.degrees(math.atan2(dy, dx))

        self._set_pose()
        return False

    def _set_pose(self) -> None:
        """Teleport the drone to self._pos with self._yaw."""
        try:
            pose = airsim.Pose(
                airsim.Vector3r(self._pos[0], self._pos[1], self._pos[2]),
                airsim.to_quaternion(0, 0, math.radians(self._yaw)),
            )
            self.client.simSetVehiclePose(pose, True, vehicle_name=self.vn)
        except Exception as exc:
            print(f"[Drone] setPose failed: {exc}")

    # -- Internal ---------------------------------------------------------------

    def _is_evtol_alive(self) -> bool:
        if not self.evtol_sumo_id:
            return False
        try:
            return self.evtol_sumo_id in traci.vehicle.getIDList()
        except traci.exceptions.TraCIException:
            return False

    def _get_evtol_sumo_position(self) -> tuple[float, float] | None:
        if not self.evtol_sumo_id:
            return None
        try:
            return traci.vehicle.getPosition(self.evtol_sumo_id)
        except traci.exceptions.TraCIException:
            return None

    def _start_next(self) -> None:
        req = self._queue.pop(0)
        self.flight_id = req["flight_id"]
        self.evtol_sumo_id = req["evtol_sumo_id"]
        self.origin_vp = req["origin_vp"]
        self.dest_vp = req["dest_vp"]
        self.passengers = req["passengers"]
        self.dest_ned = vertiport_airsim(self.dest_vp)

        # Per-vertiport ground heights
        origin_ground_z = vertiport_ground_z_airsim(self.origin_vp)
        self._dest_ground_z = vertiport_ground_z_airsim(self.dest_vp)
        # Cruise altitude: above the HIGHER of origin/dest ground
        higher_ground = min(origin_ground_z, self._dest_ground_z)  # NED: more negative = higher
        self._cruise_z = higher_ground - CRUISE_ALT_M

        # Start from origin vertiport position at origin ground level
        origin_ned = vertiport_airsim(self.origin_vp)
        self._pos = [origin_ned[0], origin_ned[1], origin_ground_z]
        self._set_pose()

        print(f"[Drone] DEPARTING {self.flight_id}: {self.origin_vp} -> "
              f"{self.dest_vp}  tracking '{self.evtol_sumo_id}'")
        self._transition(Phase.FLYING)

    def _transition(self, new_phase: Phase) -> None:
        self.phase = new_phase
        self._phase_start = time.monotonic()

    def _clear(self) -> None:
        self.flight_id = None
        self.evtol_sumo_id = None
        self.origin_vp = None
        self.dest_vp = None
        self.passengers = 0
