"""
flight_fleet.py — Fleet of AirSim eVTOL vehicles, assigns flights from SUMO.

One FlightController per vehicle; FlightFleet dispatches new departure
intents to idle controllers and returns landing events to the bridge.
"""

import csv
import os
from datetime import datetime

from .config_airsim import (
    EVTOL_FLEET, INCLUDE_DRONE_FALLBACK, FALLBACK_DRONE_NAME,
    CRUISE_ALT_M, LOG_FLIGHTS, FLIGHT_LOG_DIR,
)
from .flight_controller import FlightController, FlightEvent
from .coordinate_map import vertiport_ned


class FlightFleet:
    """
    Manages a pool of eVTOL vehicles registered with the AirSim server.

    Parameters
    ----------
    client  : airsim.MultirotorClient  (already connected)
    """

    def __init__(self, client) -> None:
        self.client = client

        # Build controllers for each named vehicle in the fleet
        names = list(EVTOL_FLEET)
        if INCLUDE_DRONE_FALLBACK and FALLBACK_DRONE_NAME not in names:
            names.append(FALLBACK_DRONE_NAME)

        self.controllers: dict[str, FlightController] = {}
        for name in names:
            try:
                # Probe the vehicle: getMultirotorState raises if not registered
                client.getMultirotorState(vehicle_name=name)
                self.controllers[name] = FlightController(client, name)
                print(f"[Fleet] Registered eVTOL: {name}")
            except Exception as exc:
                print(f"[Fleet] Skipping '{name}' — not in AirSim settings.json "
                      f"({exc.__class__.__name__})")

        if not self.controllers:
            raise RuntimeError(
                "No usable vehicles. Generate AirSim settings.json with:\n"
                "  python Documents/Unreal\\ Projects/evttolll/Scripts/"
                "evtol_settings.py --dual"
            )

        # Pending departure requests queued from SUMO
        self._pending: list[dict] = []

        # Completed flights log
        self._completed: list[dict] = []
        self._log_path: str | None = None
        if LOG_FLIGHTS:
            self._init_log_file()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def arm_all(self) -> None:
        """Enable API control and arm each vehicle (safe to call repeatedly)."""
        for vn in self.controllers:
            try:
                self.client.enableApiControl(True, vehicle_name=vn)
                self.client.armDisarm      (True, vehicle_name=vn)
            except Exception as exc:
                print(f"[Fleet] arm({vn}) failed: {exc}")

    def disarm_all(self) -> None:
        for vn in self.controllers:
            try:
                self.client.armDisarm      (False, vehicle_name=vn)
                self.client.enableApiControl(False, vehicle_name=vn)
            except Exception:
                pass

    def land_all(self) -> None:
        for fc in self.controllers.values():
            fc.abort_and_land()

    def close(self) -> None:
        if LOG_FLIGHTS and self._log_path and self._completed:
            self._flush_log()

    # ── Dispatch ──────────────────────────────────────────────────────────────

    def queue_departure(self, flight_id: str, origin_vp: str, dest_vp: str,
                        passengers: int, t: float) -> None:
        """Append a new SUMO-originated flight intent to the pending queue."""
        self._pending.append({
            "flight_id":  flight_id,
            "origin_vp":  origin_vp,
            "dest_vp":    dest_vp,
            "passengers": passengers,
            "t":          t,
        })

    def tick(self, t: float) -> list[FlightEvent]:
        """
        Called every SUMO step.
          1. Assign pending departures to idle controllers (FIFO).
          2. Advance every controller's state machine.
          3. Collect and return any FlightEvents (departures + landings).
        """
        events: list[FlightEvent] = []

        # 1. Assignment
        still_pending: list[dict] = []
        for req in self._pending:
            fc = self._first_idle_controller()
            if fc is None:
                still_pending.append(req)                # fleet saturated
                continue
            origin_ned = vertiport_ned(req["origin_vp"])
            dest_ned   = vertiport_ned(req["dest_vp"])
            ev = fc.launch(
                flight_id   = req["flight_id"],
                origin_vp   = req["origin_vp"],
                dest_vp     = req["dest_vp"],
                origin_ned  = origin_ned,
                dest_ned    = dest_ned,
                cruise_alt_m= CRUISE_ALT_M,
                passengers  = req["passengers"],
                t           = req["t"],
            )
            events.append(ev)
        self._pending = still_pending

        # 2. Per-vehicle state-machine tick
        for fc in self.controllers.values():
            ev = fc.tick(t)
            if ev is not None:
                events.append(ev)
                if ev.kind == "landed":
                    self._record_completion(ev)

        return events

    # ── Internal ──────────────────────────────────────────────────────────────

    def _first_idle_controller(self) -> FlightController | None:
        for fc in self.controllers.values():
            if fc.is_idle():
                return fc
        return None

    def _init_log_file(self) -> None:
        os.makedirs(FLIGHT_LOG_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(FLIGHT_LOG_DIR, f"airsim_flights_{ts}.csv")
        with open(self._log_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["flight_id", "vehicle", "dest_vp",
                        "passengers", "landed_t_s"])
        print(f"[Fleet] Flight log -> {self._log_path}")

    def _record_completion(self, ev: FlightEvent) -> None:
        row = {
            "flight_id":  ev.flight_id,
            "vehicle":    ev.vehicle,
            "dest_vp":    ev.vp,
            "passengers": ev.passengers,
            "landed_t_s": round(ev.t, 2),
        }
        self._completed.append(row)
        # Append immediately so partial runs still leave usable data
        if LOG_FLIGHTS and self._log_path:
            with open(self._log_path, "a", newline="") as f:
                w = csv.writer(f)
                w.writerow([row[k] for k in ["flight_id", "vehicle",
                                              "dest_vp", "passengers",
                                              "landed_t_s"]])

    def _flush_log(self) -> None:
        # Already appended row-by-row in _record_completion; nothing else to do.
        print(f"[Fleet] {len(self._completed)} flight(s) logged in {self._log_path}")
