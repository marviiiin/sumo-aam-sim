"""
bridge.py — CarlaBridge: top-level CARLA visualisation controller.

Integrates with simulation.py via the on_step callback:

    from carla_bridge import CarlaBridge
    bridge = CarlaBridge()
    bridge.connect()
    run(args, on_step=bridge.sync)
    bridge.close()

Or use the convenience entry point run_with_carla.py.
"""

import sys

try:
    import carla
except ImportError:
    sys.exit(
        "ERROR: 'carla' package not installed.\n"
        "Install it from your CARLA installation directory:\n"
        "  pip install <CARLA_ROOT>/PythonAPI/carla/dist/carla-*.whl"
    )

from .config_carla import (
    CARLA_HOST, CARLA_PORT, CARLA_TIMEOUT, CARLA_MAP,
    SYNC_MODE, SHOW_DEBUG_TEXT, EVTOL_ALTITUDE_M,
)
from .vehicle_sync  import VehicleSync
from .evtol_actor   import EvtolActorManager
from .coordinate_map import vertiport_carla_location


class CarlaBridge:
    """
    Connects to a running CARLA server and mirrors SUMO simulation state.

    Lifecycle
    ---------
    bridge = CarlaBridge()
    bridge.connect()              # must be called before simulation starts
    # ... pass bridge.sync as on_step to simulation.run() ...
    bridge.close()                # cleans up actors
    """

    def __init__(self) -> None:
        self._client:  "carla.Client | None"  = None
        self._world:   "carla.World  | None"  = None
        self._vsync:   "VehicleSync  | None"  = None
        self._evtol:   "EvtolActorManager | None" = None
        self._debug:   "carla.DebugHelper | None" = None
        self._settings: "carla.WorldSettings | None" = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Connect to CARLA server. Call before starting the SUMO simulation."""
        print(f"[CARLA] Connecting to {CARLA_HOST}:{CARLA_PORT} …")
        self._client = carla.Client(CARLA_HOST, CARLA_PORT)
        self._client.set_timeout(CARLA_TIMEOUT)

        # Load map if specified
        if CARLA_MAP:
            print(f"[CARLA] Loading map '{CARLA_MAP}' …")
            self._world = self._client.load_world(CARLA_MAP)
        else:
            self._world = self._client.get_world()

        print(f"[CARLA] Connected. Map: {self._world.get_map().name}")

        # Configure synchronous mode
        self._settings = self._world.get_settings()
        if SYNC_MODE:
            s = self._world.get_settings()
            s.synchronous_mode  = True
            s.fixed_delta_seconds = None   # let simulation.py control step
            self._world.apply_settings(s)
            print("[CARLA] Synchronous mode ON")

        # Disable default vehicle physics (we drive everything kinematically)
        lib = self._world.get_blueprint_library()
        self._vsync = VehicleSync(self._world, lib)
        self._evtol = EvtolActorManager(self._world, lib)
        self._debug = self._world.debug

        # Position spectator above the vertiport Alpha zone
        self._aim_spectator_at_vertiports()

        print("[CARLA] Bridge ready.")

    def sync(self, t: float, arrival_handlers: dict, parking_managers: dict) -> None:
        """
        Called every SUMO step by simulation.run(on_step=bridge.sync).
        """
        # 1. Mirror ground vehicles
        self._vsync.sync()

        # 2. Animate eVTOL actors (state machine advance)
        self._evtol.tick()

        # 3. Trigger new eVTOL arrivals
        for vp_id, ah in arrival_handlers.items():
            if ah.step_arrivals > 0:
                self._evtol.spawn_arrival(vp_id, ah.step_passengers)

        # 4. HUD overlay
        if SHOW_DEBUG_TEXT:
            self._draw_hud(t, parking_managers)

        # 5. Advance CARLA frame (synchronous mode only)
        if SYNC_MODE and self._world is not None:
            self._world.tick()

    def close(self) -> None:
        """Destroy all managed actors and restore CARLA world settings."""
        print("[CARLA] Shutting down bridge …")
        if self._vsync:
            self._vsync.destroy_all()
        if self._evtol:
            self._evtol.destroy_all()
        if self._world and self._settings and SYNC_MODE:
            self._world.apply_settings(self._settings)   # restore original settings
        print("[CARLA] Bridge closed.")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _aim_spectator_at_vertiports(self) -> None:
        """Position the CARLA free-fly camera above VP-Alpha at start."""
        try:
            cx, cy, _ = vertiport_carla_location("vp_a", altitude=0)
            self._world.get_spectator().set_transform(
                carla.Transform(
                    carla.Location(x=cx, y=cy - 20.0, z=120.0),
                    carla.Rotation(pitch=-60, yaw=90),
                )
            )
        except Exception as exc:
            print(f"[CARLA] Could not set spectator: {exc}")

    def _draw_hud(self, t: float, parking_managers: dict) -> None:
        """Draw parking occupancy labels above each vertiport."""
        if self._debug is None:
            return
        for vp_id, pm in parking_managers.items():
            cx, cy, _ = vertiport_carla_location(vp_id, altitude=0)
            label = (
                f"{vp_id.upper()}  "
                f"Park: {pm.current_occupancy}/{pm.vp_cfg['max_parking']}  "
                f"Q: {pm.current_queue_length}  "
                f"Spill: {pm.spillback_events}"
            )
            self._debug.draw_string(
                carla.Location(x=cx, y=cy, z=15.0),
                label,
                draw_shadow=True,
                color=carla.Color(r=255, g=220, b=0),
                life_time=2.0,   # seconds — redrawn each call so it persists
                persistent_lines=False,
            )
