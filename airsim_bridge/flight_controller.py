"""
flight_controller.py — Per-vehicle non-blocking eVTOL flight state machine.

Each eVTOL in the fleet owns one FlightController.  The bridge calls .tick()
once per SUMO step; the controller issues AirSim async commands without
blocking, and advances its phase based on vehicle pose vs target.

Phases
------
  IDLE      — parked, awaiting a flight assignment
  TAKEOFF   — taking off from pad (arm, takeoffAsync)
  CLIMB     — climbing to cruise altitude
  CRUISE    — horizontal flight toward destination NED
  DESCEND   — landing at destination pad
  LANDED    — touched down; re-enter IDLE after one tick for event reporting
"""

import math
import time
from dataclasses import dataclass, field
from enum import Enum

from .config_airsim import (
    ALT_TOL_M, POS_TOL_M, LAND_VEL_TOL_MS, LAND_ALT_TOL_M,
    MIN_PHASE_S,
    CLIMB_SPEED_MS, CRUISE_SPEED_MS,
    VERBOSE,
)


class Phase(Enum):
    IDLE    = "idle"
    TAKEOFF = "takeoff"
    CLIMB   = "climb"
    CRUISE  = "cruise"
    DESCEND = "descend"
    LANDED  = "landed"


@dataclass
class FlightEvent:
    """Returned from tick() when something notable happens."""
    kind:      str              # "departed" | "landed"
    flight_id: str
    vehicle:   str
    vp:        str              # origin_vp (departed) or dest_vp (landed)
    t:         float            # SUMO simulation time
    passengers: int = 0


class FlightController:
    """One instance per AirSim eVTOL vehicle."""

    def __init__(self, client, vehicle_name: str) -> None:
        self.client  = client
        self.vn      = vehicle_name

        # Current assignment (None when IDLE)
        self.flight_id: str | None = None
        self.origin_vp: str | None = None
        self.dest_vp:   str | None = None
        self.passengers = 0

        # Targets (NED metres — AirSim x=N, y=E, z=D)
        self.origin_xy: tuple[float, float] = (0.0, 0.0)
        self.dest_xy:   tuple[float, float] = (0.0, 0.0)
        self.cruise_alt_m = 0.0
        self.cruise_z_ned = 0.0
        self.ground_z: float | None = None

        # State
        self.phase: Phase = Phase.IDLE
        self._cmd_issued = False
        self._phase_start_wall = 0.0   # time.monotonic()

    # ── Public interface ──────────────────────────────────────────────────────

    def is_idle(self) -> bool:
        return self.phase == Phase.IDLE

    def launch(self, flight_id: str, origin_vp: str, dest_vp: str,
               origin_ned: tuple[float, float],
               dest_ned: tuple[float, float],
               cruise_alt_m: float, passengers: int, t: float) -> FlightEvent:
        """Assign a flight to this vehicle. Controller begins next tick()."""
        self.flight_id    = flight_id
        self.origin_vp    = origin_vp
        self.dest_vp      = dest_vp
        self.origin_xy    = origin_ned
        self.dest_xy      = dest_ned
        self.cruise_alt_m = cruise_alt_m
        self.passengers   = passengers

        # Snapshot ground z from current pose (may be mid-air if re-used vehicle)
        st = self.client.getMultirotorState(vehicle_name=self.vn)
        self.ground_z     = st.kinematics_estimated.position.z_val
        self.cruise_z_ned = self.ground_z - cruise_alt_m

        self._transition(Phase.TAKEOFF)
        if VERBOSE:
            print(f"[FC/{self.vn}] launch {flight_id}: {origin_vp} -> {dest_vp}  "
                  f"cruise={cruise_alt_m:.0f}m  dest_NED=({dest_ned[0]:.1f},"
                  f"{dest_ned[1]:.1f})")
        return FlightEvent(
            kind="departed", flight_id=flight_id, vehicle=self.vn,
            vp=origin_vp, t=t, passengers=passengers,
        )

    def tick(self, t: float) -> FlightEvent | None:
        """
        Advance state machine.
        Returns a FlightEvent on phase boundary (currently just 'landed'),
        else None.
        """
        if self.phase == Phase.IDLE:
            return None

        try:
            st = self.client.getMultirotorState(vehicle_name=self.vn)
        except Exception as exc:
            print(f"[FC/{self.vn}] getMultirotorState failed: {exc}")
            return None
        pos = st.kinematics_estimated.position
        vel = st.kinematics_estimated.linear_velocity
        phase_age = time.monotonic() - self._phase_start_wall

        if self.phase == Phase.TAKEOFF:
            if not self._cmd_issued:
                try:
                    self.client.enableApiControl(True,  vehicle_name=self.vn)
                    self.client.armDisarm      (True,  vehicle_name=self.vn)
                    self.client.takeoffAsync(vehicle_name=self.vn)
                except Exception as exc:
                    print(f"[FC/{self.vn}] takeoff failed: {exc}")
                self._cmd_issued = True
                return None
            # Advance once we've been taking off long enough — the takeoff
            # future completes asynchronously inside AirSim.
            if phase_age >= MIN_PHASE_S["takeoff"]:
                self._transition(Phase.CLIMB)

        elif self.phase == Phase.CLIMB:
            if not self._cmd_issued:
                try:
                    self.client.moveToZAsync(
                        self.cruise_z_ned, CLIMB_SPEED_MS,
                        vehicle_name=self.vn,
                    )
                except Exception as exc:
                    print(f"[FC/{self.vn}] moveToZ failed: {exc}")
                self._cmd_issued = True
                return None
            if (phase_age >= MIN_PHASE_S["climb"] and
                    abs(pos.z_val - self.cruise_z_ned) < ALT_TOL_M):
                self._transition(Phase.CRUISE)

        elif self.phase == Phase.CRUISE:
            if not self._cmd_issued:
                try:
                    import airsim
                    yaw_deg = self._yaw_to_dest()
                    self.client.moveToPositionAsync(
                        self.dest_xy[0], self.dest_xy[1], self.cruise_z_ned,
                        CRUISE_SPEED_MS,
                        drivetrain=airsim.DrivetrainType.ForwardOnly,
                        yaw_mode=airsim.YawMode(is_rate=False, yaw_or_rate=yaw_deg),
                        vehicle_name=self.vn,
                    )
                except Exception as exc:
                    print(f"[FC/{self.vn}] moveToPosition failed: {exc}")
                self._cmd_issued = True
                return None
            dx = pos.x_val - self.dest_xy[0]
            dy = pos.y_val - self.dest_xy[1]
            if (phase_age >= MIN_PHASE_S["cruise"]
                    and math.hypot(dx, dy) < POS_TOL_M):
                self._transition(Phase.DESCEND)

        elif self.phase == Phase.DESCEND:
            if not self._cmd_issued:
                try:
                    self.client.landAsync(vehicle_name=self.vn)
                except Exception as exc:
                    print(f"[FC/{self.vn}] land failed: {exc}")
                self._cmd_issued = True
                return None
            # Detect touchdown: near-zero vertical velocity AND close to ground
            near_ground  = (self.ground_z is not None
                            and (self.ground_z - pos.z_val) < LAND_ALT_TOL_M)
            vel_settled  = abs(vel.z_val) < LAND_VEL_TOL_MS
            if phase_age >= MIN_PHASE_S["descend"] and near_ground and vel_settled:
                event = FlightEvent(
                    kind="landed",
                    flight_id=self.flight_id or "",
                    vehicle=self.vn,
                    vp=self.dest_vp or "",
                    t=t,
                    passengers=self.passengers,
                )
                try:
                    self.client.armDisarm(False, vehicle_name=self.vn)
                except Exception:
                    pass
                self._transition(Phase.LANDED)
                return event

        elif self.phase == Phase.LANDED:
            # Single-tick stay in LANDED; bridge has consumed the event;
            # now return to IDLE so fleet can reuse the vehicle.
            self._clear_assignment()
            self._transition(Phase.IDLE)

        return None

    def abort_and_land(self) -> None:
        """Emergency land — used on bridge shutdown or error."""
        try:
            self.client.landAsync(vehicle_name=self.vn)
        except Exception:
            pass
        self._transition(Phase.DESCEND)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _transition(self, new_phase: Phase) -> None:
        if VERBOSE and new_phase != self.phase:
            print(f"[FC/{self.vn}] {self.phase.value} -> {new_phase.value}")
        self.phase = new_phase
        self._cmd_issued = False
        self._phase_start_wall = time.monotonic()

    def _clear_assignment(self) -> None:
        self.flight_id = None
        self.origin_vp = None
        self.dest_vp   = None
        self.passengers = 0

    def _yaw_to_dest(self) -> float:
        """AirSim yaw in [-180, 180] pointing from origin_xy toward dest_xy."""
        dn = self.dest_xy[0] - self.origin_xy[0]
        de = self.dest_xy[1] - self.origin_xy[1]
        yaw = math.degrees(math.atan2(de, dn))  # 0=N, 90=E
        if yaw > 180:
            yaw -= 360
        return yaw
