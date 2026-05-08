"""
bridge.py — AirSimBridge: top-level AirSim/UE5 visualisation controller.

Parallel to carla_bridge.CarlaBridge.  Plugs into simulation.py:

    from airsim_bridge import AirSimBridge
    bridge = AirSimBridge()
    bridge.connect()
    run(args, on_step=bridge.sync)
    bridge.close()

Or use the convenience entry point: python run_with_airsim.py
"""

from .config_airsim import (
    AIRSIM_HOST, AIRSIM_PORT, AIRSIM_TIMEOUT_S,
    VERTIPORT_GPS, VERBOSE,
)
from .coordinate_map import vertiport_ned, distance_m, bearing_deg

# NOTE: `airsim` and `flight_fleet` (which imports `flight_controller`) are
# imported lazily inside AirSimBridge.connect() so that this module — and the
# package as a whole — can be imported even when the `airsim` wheel is not
# installed (e.g. for unit tests of coordinate_map / config).


class AirSimBridge:
    """
    Connects to a running AirSim server (UE5 + evttolll project) and flies
    real eVTOL vehicles for every flight dispatched by the SUMO arrival
    handler.

    Lifecycle
    ---------
    bridge = AirSimBridge()
    bridge.connect()
    # ... simulation.run(..., on_step=bridge.sync) ...
    bridge.close()
    """

    def __init__(self, realtime_factor: float = 1.0) -> None:
        self._client: "airsim.MultirotorClient | None" = None
        self._fleet:  "FlightFleet | None"             = None
        self._mirror: "VehicleMirror | None"           = None
        # Wall-clock pacing: 1.0 = real-time, 0.5 = 2x speed, 2.0 = half speed.
        # AirSim state machines rely on wall-clock time, so without pacing a
        # headless SUMO run finishes before any flight completes.
        self._realtime_factor = realtime_factor
        self._wall_start: float | None = None
        self._sim_start_t: float | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        # Lazy imports: only require `airsim` when actually connecting
        try:
            import airsim
        except ImportError as exc:
            raise RuntimeError(
                "'airsim' package not installed. Run: pip install airsim"
            ) from exc
        from .flight_fleet import FlightFleet
        from .vehicle_mirror import VehicleMirror
        import arrival_handler   # module-level departure log lives here
        self._arrival_handler_mod = arrival_handler

        print(f"[AirSim] Connecting to {AIRSIM_HOST}:{AIRSIM_PORT} …")
        self._client = airsim.MultirotorClient(ip=AIRSIM_HOST, port=AIRSIM_PORT,
                                                timeout_value=AIRSIM_TIMEOUT_S)
        self._client.confirmConnection()
        print("[AirSim] Connected.")

        # Pre-print the NED positions so the user can sanity-check georef
        print("[AirSim] Vertiport NED positions (from Cesium origin):")
        for vp_id in VERTIPORT_GPS:
            n, e = vertiport_ned(vp_id)
            print(f"    {vp_id}: x_n={n:>9.1f}  y_e={e:>9.1f}  "
                  f"GPS=({VERTIPORT_GPS[vp_id][0]:.4f},"
                  f" {VERTIPORT_GPS[vp_id][1]:.4f})")

        # Inter-vertiport distances / bearings (diagnostic)
        vp_ids = list(VERTIPORT_GPS.keys())
        for i, a in enumerate(vp_ids):
            for b in vp_ids[i+1:]:
                d  = distance_m(a, b)
                br = bearing_deg(a, b)
                print(f"    {a} -> {b}: {d/1000:.2f} km  bearing {br:.1f}°")

        # Enable the vehicle fleet
        self._fleet = FlightFleet(self._client)
        self._fleet.arm_all()

        # Enable the ground-vehicle mirror (no-op if disabled in config)
        self._mirror = VehicleMirror(self._client)

        # Enable the module-level departure log inside arrival_handler
        if self._arrival_handler_mod._BRIDGE_DEPARTURES is None:
            self._arrival_handler_mod._BRIDGE_DEPARTURES = []

        print("[AirSim] Bridge ready.")

    def sync(self, t: float, arrival_handlers: dict, parking_managers: dict) -> None:
        """
        Called every SUMO step by simulation.run(on_step=bridge.sync).
        """
        assert self._fleet is not None

        # ── Wall-clock pacer ──────────────────────────────────────────────────
        # Keep (t - sim_start) * factor roughly equal to wall-clock elapsed.
        # This ensures AirSim state-machine phases (which use time.monotonic)
        # have real seconds to make progress.
        if self._realtime_factor > 0:
            import time
            if self._wall_start is None:
                self._wall_start  = time.monotonic()
                self._sim_start_t = t
            sim_elapsed  = t - (self._sim_start_t or 0.0)
            target_wall  = sim_elapsed * self._realtime_factor
            wall_elapsed = time.monotonic() - self._wall_start
            if target_wall > wall_elapsed:
                time.sleep(min(target_wall - wall_elapsed, 1.0))

        # 1. Consume every new SUMO departure and queue an AirSim flight
        pending = getattr(self._arrival_handler_mod,
                          "_BRIDGE_DEPARTURES", None)
        if pending:
            while pending:
                rec = pending.pop(0)
                # Only queue if both vertiports are in our GPS map
                if (rec["origin_vp"] in VERTIPORT_GPS
                        and rec["dest_vp"] in VERTIPORT_GPS):
                    self._fleet.queue_departure(
                        flight_id  = rec["evtol_id"],
                        origin_vp  = rec["origin_vp"],
                        dest_vp    = rec["dest_vp"],
                        passengers = rec["passengers"],
                        t          = rec["t"],
                    )
                    if VERBOSE:
                        print(f"[AirSim] queued flight {rec['evtol_id']}  "
                              f"{rec['origin_vp']} -> {rec['dest_vp']}")
                else:
                    print(f"[AirSim] no GPS for {rec['origin_vp']}->"
                          f"{rec['dest_vp']} — skipped")

        # 2. Advance all flight state machines
        events = self._fleet.tick(t)

        # 2b. Mirror SUMO ground vehicles into the UE5 world
        if self._mirror is not None:
            self._mirror.tick()

        # 3. Report events to stdout (arrivals are already handled by SUMO's
        #    route-based vehicle lifecycle — see arrival_handler._check_arrivals)
        for ev in events:
            if ev.kind == "landed":
                print(f"[AirSim {t:>7.1f}s]  ✈  LANDED  {ev.flight_id}  "
                      f"@ {ev.vp}  ({ev.passengers} pax, vehicle {ev.vehicle})")

    def close(self) -> None:
        print("[AirSim] Shutting down bridge …")
        if self._mirror is not None:
            try:
                self._mirror.destroy_all()
            except Exception as exc:
                print(f"[AirSim] mirror shutdown: {exc}")
        if self._fleet is not None:
            try:
                self._fleet.land_all()
            except Exception as exc:
                print(f"[AirSim] land_all: {exc}")
            try:
                self._fleet.disarm_all()
            except Exception:
                pass
            self._fleet.close()
        print("[AirSim] Bridge closed.")
