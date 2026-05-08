"""
arrival_handler.py
Manages eVTOL departures and arrival detection for one vertiport.

Flight lifecycle
----------------
1. Passenger queue triggers departure → inject an eVTOL vehicle on the flight-path route.
2. eVTOL vehicle reaches end of last flight edge → SUMO removes it;
   its ID appears in traci.simulation.getArrivedIDList().
3. Arrival detected → inject N rental cars at the destination vertiport.

eVTOL IDs encode the destination:  "evtol_to_vp_b_00042"
Each vertiport handler scans arrivedIDs for its own prefix ("evtol_to_vp_a_").

A module-level flight manifest (_MANIFEST) carries the passenger count from
the departing vertiport's handler to the arriving vertiport's handler.
"""

import random
import traci
import traci.exceptions

from config import (
    EVTOL_VTYPE,
    RENTAL_VTYPE,
)

# Shared flight manifest:  evtol_id → passenger_count
_MANIFEST: dict[str, int] = {}

# Bridge departure log (see bridge.py for details)
_BRIDGE_DEPARTURES: list[dict] | None = None


class EvtolArrivalHandler:
    """
    Handles eVTOL departure scheduling and arrival detection for one vertiport.

    Parameters
    ----------
    vp_id  : str  – vertiport key (e.g. "vp_a")
    vp_cfg : dict – vertiport config block from config.VERTIPORTS
    pax_queue : VertiportQueue or None – passenger queue (data-driven dispatch)
    """

    def __init__(self, vp_id: str, vp_cfg: dict, pax_queue=None) -> None:
        self.vp_id  = vp_id
        self.vp_cfg = vp_cfg
        self.name   = vp_cfg["name"]
        self.pax_queue = pax_queue

        # Sequence counters
        self._depart_seq: int  = 0
        self._rental_seq: int  = 0

        # Cumulative totals (read by MetricsLogger)
        self.total_arrivals:   int = 0
        self.total_passengers: int = 0
        self.total_rentals:    int = 0

        # Per-step snapshots
        self.step_arrivals:   int = 0
        self.step_passengers: int = 0
        self.step_rentals:    int = 0

    # ── Public interface ──────────────────────────────────────────────────────

    def step(self, t: float) -> None:
        """Called once per simulation step."""
        self.step_arrivals  = 0
        self.step_passengers = 0
        self.step_rentals   = 0

        self._check_departures(t)
        self._check_arrivals(t)

    # ── Departure logic ───────────────────────────────────────────────────────

    def _check_departures(self, t: float) -> None:
        if self.pax_queue is None:
            return
        dispatch = self.pax_queue.step(t)
        if dispatch is not None:
            self._dispatch_evtol(t, dispatch)

    def _dispatch_evtol(self, t: float, dispatch: dict) -> None:
        """Inject one eVTOL vehicle with passengers from the queue."""
        dest_vp_id = dispatch["dest_vp"]
        passengers = dispatch["passengers"]

        flight_routes = self.vp_cfg.get("flight_routes", {})
        route_id = flight_routes.get(dest_vp_id)
        if not route_id:
            return

        self._depart_seq += 1
        evtol_id = f"evtol_to_{dest_vp_id}_{self._depart_seq:05d}"

        _MANIFEST[evtol_id] = passengers

        try:
            traci.vehicle.add(
                evtol_id,
                routeID=route_id,
                typeID=EVTOL_VTYPE,
                depart="now",
                departLane="first",
                departSpeed="max",
            )
            print(
                f"[{t:>7.1f}s] ✈  eVTOL DEPARTS {self.name} → "
                f"{dest_vp_id.upper()}  ({passengers} pax)  [{evtol_id}]"
            )
            if _BRIDGE_DEPARTURES is not None:
                _BRIDGE_DEPARTURES.append({
                    "evtol_id":   evtol_id,
                    "origin_vp":  self.vp_id,
                    "dest_vp":    dest_vp_id,
                    "passengers": passengers,
                    "t":          t,
                })
        except traci.exceptions.TraCIException as exc:
            print(f"[WARN] Could not dispatch eVTOL {evtol_id}: {exc}")
            _MANIFEST.pop(evtol_id, None)

    # ── Arrival detection ─────────────────────────────────────────────────────

    def _check_arrivals(self, t: float) -> None:
        prefix = self.vp_cfg.get("evtol_arrival_prefix", "")
        if not prefix:
            return

        try:
            arrived = traci.simulation.getArrivedIDList()
        except traci.exceptions.TraCIException:
            return

        for evtol_id in arrived:
            if not evtol_id.startswith(prefix):
                continue

            passengers = _MANIFEST.pop(evtol_id, 1)

            self.total_arrivals   += 1
            self.total_passengers += passengers
            self.step_arrivals    += 1
            self.step_passengers  += passengers

            print(
                f"[{t:>7.1f}s] ✈  eVTOL ARRIVED  @ {self.name}  "
                f"({passengers} pax)  [{evtol_id}]"
            )

            injected = self._inject_rental_cars(t, passengers)
            self.total_rentals += injected
            self.step_rentals  += injected

    # ── Rental car injection ──────────────────────────────────────────────────

    def _inject_rental_cars(self, t: float, passengers: int) -> int:
        occupancy = self._get_parking_occupancy()
        available = max(0, self.vp_cfg["max_parking"] - occupancy)
        to_inject = min(passengers, available)

        if to_inject < passengers:
            print(
                f"            ⚠  Parking near capacity "
                f"({occupancy}/{self.vp_cfg['max_parking']}): "
                f"{passengers - to_inject} rental car(s) cannot be placed."
            )

        for _ in range(to_inject):
            self._add_rental_vehicle()

        print(
            f"            → {to_inject} rental car(s) injected | "
            f"parking {occupancy + to_inject}/{self.vp_cfg['max_parking']}"
        )
        return to_inject

    def _add_rental_vehicle(self) -> None:
        self._rental_seq += 1
        veh_id   = f"rental_{self.vp_id}_{self._rental_seq:05d}"
        route_id = random.choice(self.vp_cfg["rental_routes"])
        try:
            traci.vehicle.add(
                veh_id,
                routeID=route_id,
                typeID=RENTAL_VTYPE,
                depart="now",
                departLane="best",
                departSpeed="max",
            )
        except traci.exceptions.TraCIException as exc:
            print(f"            [WARN] Could not inject rental car {veh_id}: {exc}")

    def _get_parking_occupancy(self) -> int:
        try:
            return traci.parkingarea.getVehicleCount(self.vp_cfg["parking_area"])
        except traci.exceptions.TraCIException:
            return 0
