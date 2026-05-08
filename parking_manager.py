"""
parking_manager.py
Real-time parking lot monitor and visitor vehicle manager for one vertiport.

Responsibilities
----------------
1. Periodically inject visitor vehicles (drop-off / pick-up trips) with a
   timed parking stop at the vertiport's parking area.
2. Monitor parking area occupancy via TraCI.
3. Detect and log queue spillback on the approach road.
"""

import random
import traci
import traci.exceptions

from config import (
    SPILLBACK_THRESHOLD,
    VISITOR_PARK_DURATION_MIN,
    VISITOR_PARK_DURATION_MAX,
    VISITOR_INTERVAL_MIN,
    VISITOR_INTERVAL_MAX,
    VISITOR_VTYPE,
)


class ParkingManager:
    """
    Manages visitor vehicles and monitors spillback for one vertiport.

    Parameters
    ----------
    vp_id  : str  – vertiport key (e.g. "vp_a")
    vp_cfg : dict – vertiport config block from config.VERTIPORTS
    """

    def __init__(self, vp_id: str, vp_cfg: dict) -> None:
        self.vp_id  = vp_id
        self.vp_cfg = vp_cfg

        # State snapshots (updated every step, read by MetricsLogger)
        self.current_occupancy:    int = 0
        self.current_queue_length: int = 0
        self.spillback_events:     int = 0

        # Internal state
        self._spillback_active: bool = False
        self._visitor_seq: int = 0
        self._next_visitor_s: float = random.uniform(
            VISITOR_INTERVAL_MIN, VISITOR_INTERVAL_MAX
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def step(self, t: float) -> None:
        """Called once per simulation step."""
        self._poll_parking_occupancy()
        self._poll_approach_queue(t)
        self._maybe_inject_visitor(t)

    # ── Polling helpers ───────────────────────────────────────────────────────

    def _poll_parking_occupancy(self) -> None:
        try:
            self.current_occupancy = traci.parkingarea.getVehicleCount(
                self.vp_cfg["parking_area"]
            )
        except traci.exceptions.TraCIException:
            pass  # parking area not in sim yet

    def _poll_approach_queue(self, t: float) -> None:
        """
        Count vehicles on the approach edge.
        If count ≥ SPILLBACK_THRESHOLD, log a spillback event (edge-triggered:
        only fires once per continuous overload episode, not every step).
        """
        try:
            edge = self.vp_cfg["approach_edge"]
            total   = traci.edge.getLastStepVehicleNumber(edge)
            halted  = traci.edge.getLastStepHaltingNumber(edge)
            self.current_queue_length = total

            if total >= SPILLBACK_THRESHOLD and not self._spillback_active:
                self._spillback_active = True
                self.spillback_events += 1
                print(
                    f"[{t:>7.1f}s] 🚨 SPILLBACK @ {self.vp_cfg['name']}: "
                    f"{total} vehicles on '{edge}' ({halted} halted) — "
                    f"event #{self.spillback_events}"
                )
            elif total < SPILLBACK_THRESHOLD and self._spillback_active:
                self._spillback_active = False
                print(
                    f"[{t:>7.1f}s]    Spillback cleared @ {self.vp_cfg['name']} "
                    f"(queue now {total} vehicles)"
                )
        except traci.exceptions.TraCIException:
            pass

    # ── Visitor vehicle injection ─────────────────────────────────────────────

    def _maybe_inject_visitor(self, t: float) -> None:
        if t < self._next_visitor_s:
            return

        # Reschedule regardless of whether injection succeeds
        self._next_visitor_s = t + random.uniform(
            VISITOR_INTERVAL_MIN, VISITOR_INTERVAL_MAX
        )

        is_full = self.current_occupancy >= self.vp_cfg["max_parking"]
        if is_full:
            # Still inject — vehicle will queue on approach edge (spillback)
            print(
                f"[{t:>7.1f}s] ℹ  Parking full @ {self.vp_cfg['name']} "
                f"({self.current_occupancy}/{self.vp_cfg['max_parking']}). "
                f"Visitor will queue on approach road."
            )

        self._visitor_seq += 1
        veh_id    = f"visitor_{self.vp_id}_{self._visitor_seq:05d}"
        route_id  = random.choice(self.vp_cfg["visitor_routes"])
        park_dur  = random.uniform(VISITOR_PARK_DURATION_MIN, VISITOR_PARK_DURATION_MAX)

        try:
            traci.vehicle.add(
                veh_id,
                routeID=route_id,
                typeID=VISITOR_VTYPE,
                depart="now",
                departLane="best",
                departSpeed="max",
            )
            # Insert a timed parking stop at the vertiport's parking area.
            # SUMO will queue the vehicle on the approach edge if the lot is full,
            # naturally producing the spillback behaviour we want to measure.
            traci.vehicle.setParkingAreaStop(
                veh_id,
                self.vp_cfg["parking_area"],
                duration=park_dur,
            )
        except traci.exceptions.TraCIException as exc:
            print(f"[WARN] Could not add visitor {veh_id}: {exc}")
