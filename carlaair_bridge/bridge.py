"""
bridge.py — CarlaAirBridge: unified CARLA ground + AirSim drone bridge.

CarlaAir runs CARLA and AirSim in a single Unreal Engine process:
  - Port 2000:  CARLA API  (ground vehicles, weather, sensors)
  - Port 41451: AirSim API (multirotor drone flight)

This bridge plugs into simulation.py via the on_step callback:

    from carlaair_bridge import CarlaAirBridge
    bridge = CarlaAirBridge()
    bridge.connect()
    run(args, on_step=bridge.sync)
    bridge.close()
"""

import random
import time
import sys

# Force line-buffered stdout so logs appear in real-time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

try:
    import carla
except ImportError:
    sys.exit("ERROR: 'carla' package not installed.")

try:
    import airsim
except ImportError:
    sys.exit("ERROR: 'airsim' package not installed.")

import traci
import traci.exceptions

import arrival_handler as _ah_mod

from .config import (
    CARLA_HOST, CARLA_PORT, CARLA_TIMEOUT, CARLA_MAP,
    AIRSIM_HOST, AIRSIM_PORT,
    PASSENGER_BLUEPRINTS, RENTAL_BLUEPRINTS,
    GROUND_Z, SYNC_MODE, SHOW_DEBUG_TEXT,
)
from .coordinate_map import (
    sumo_to_carla, sumo_angle_to_carla_yaw,
    vertiport_carla, vertiport_airsim,
)
from .drone_controller import DroneController
from .pedestrian_manager import PedestrianManager


class CarlaAirBridge:
    """
    Mirrors SUMO ground traffic in CARLA and flies eVTOL drones via AirSim.
    """

    def __init__(self) -> None:
        self._carla_client: "carla.Client | None" = None
        self._world: "carla.World | None" = None
        self._debug = None
        self._settings = None

        self._airsim_client = None
        self._drone: "DroneController | None" = None
        self._ped_mgr: "PedestrianManager | None" = None

        # CARLA ground vehicle pool: sumo_id -> carla.Actor
        self._actors: dict[str, "carla.Actor"] = {}
        self._bp_passenger = None
        self._bp_rental = None

        # Wall-clock pacer for real-time sync
        self._wall_start: float | None = None
        self._sim_start_t: float | None = None
        self._step_count = 0

    # -- Lifecycle ------------------------------------------------------------

    def connect(self) -> None:
        # 1. Connect to CARLA
        print(f"[CarlaAir] Connecting to CARLA {CARLA_HOST}:{CARLA_PORT} ...")
        self._carla_client = carla.Client(CARLA_HOST, CARLA_PORT)
        self._carla_client.set_timeout(CARLA_TIMEOUT)

        if CARLA_MAP:
            self._world = self._carla_client.load_world(CARLA_MAP)
        else:
            self._world = self._carla_client.get_world()
        print(f"[CarlaAir] CARLA map: {self._world.get_map().name}")

        # Synchronous mode
        self._settings = self._world.get_settings()
        if SYNC_MODE:
            s = self._world.get_settings()
            s.synchronous_mode = True
            s.fixed_delta_seconds = 0.05  # 20 FPS
            self._world.apply_settings(s)

        self._debug = self._world.debug
        lib = self._world.get_blueprint_library()
        self._bp_passenger = self._pick_bp(lib, PASSENGER_BLUEPRINTS)
        self._bp_rental = self._pick_bp(lib, RENTAL_BLUEPRINTS)
        if self._bp_rental and self._bp_rental.has_attribute("color"):
            self._bp_rental.set_attribute("color", "255,140,0")

        # 2. Connect to AirSim
        print(f"[CarlaAir] Connecting to AirSim {AIRSIM_HOST}:{AIRSIM_PORT} ...")
        self._airsim_client = airsim.MultirotorClient(
            ip=AIRSIM_HOST, port=AIRSIM_PORT,
        )
        self._airsim_client.confirmConnection()
        print("[CarlaAir] AirSim connected.")

        self._drone = DroneController(self._airsim_client)

        # Print vertiport positions
        for vp_id in ("vp_a", "vp_b"):
            cx, cy, cz = vertiport_carla(vp_id)
            ax, ay, az = vertiport_airsim(vp_id)
            print(f"  {vp_id}: CARLA=({cx:.1f},{cy:.1f},{cz:.1f})  "
                  f"AirSim=({ax:.1f},{ay:.1f},{az:.1f})")

        # Enable departure log so arrival_handler publishes events
        if _ah_mod._BRIDGE_DEPARTURES is None:
            _ah_mod._BRIDGE_DEPARTURES = []

        # Pedestrian manager: ambient walkers + vertiport passengers
        self._ped_mgr = PedestrianManager(self._world)
        self._ped_mgr.spawn_ambient()

        # Position spectator above city centre
        self._aim_spectator()
        print("[CarlaAir] Bridge ready.")

    def sync(self, t: float, arrival_handlers: dict,
             parking_managers: dict) -> None:
        """Called every SUMO step."""
        self._step_count += 1
        if self._step_count % 30 == 1:
            print(f"[CarlaAir] step={self._step_count} t={t:.0f}s "
                  f"actors={len(self._actors)} drone={self._drone.phase.value}")

        # Real-time pacing
        self._pace(t)

        try:
            self._sync_inner(t, arrival_handlers, parking_managers)
        except Exception as exc:
            # Never let a CARLA/AirSim error kill the SUMO simulation
            if self._step_count % 60 == 1:
                print(f"[CarlaAir] sync error at t={t:.0f}s: {exc}")

    def _sync_inner(self, t: float, arrival_handlers: dict,
                    parking_managers: dict) -> None:
        # 1. Mirror ground vehicles
        self._sync_vehicles()

        # 2. Consume eVTOL departures from SUMO and queue drone flights
        pending = _ah_mod._BRIDGE_DEPARTURES
        if pending:
            while pending:
                rec = pending.pop(0)
                self._drone.queue_flight(
                    flight_id=rec["evtol_id"],
                    origin_vp=rec["origin_vp"],
                    dest_vp=rec["dest_vp"],
                    passengers=rec["passengers"],
                )

        # 3. Advance drone flight state machine
        prev_phase = self._drone.phase
        self._drone.tick()

        # 3b. Spawn passengers when drone lands at a vertiport
        if prev_phase != self._drone.phase:
            from .drone_controller import Phase
            if self._drone.phase == Phase.LANDED and self._ped_mgr:
                self._ped_mgr.spawn_passengers_at(
                    self._drone.dest_vp,
                    self._drone.passengers,
                    t,
                )

        # 3c. Tick pedestrian manager
        if self._ped_mgr:
            self._ped_mgr.tick(t)

        # 4. HUD overlay
        if SHOW_DEBUG_TEXT and self._debug:
            self._draw_hud(t, parking_managers)

        # 5. Tick CARLA world (synchronous mode)
        #    Multiple ticks per SUMO step to keep CARLA rendering smooth
        if SYNC_MODE and self._world:
            for _ in range(5):
                try:
                    self._world.tick()
                except Exception as exc:
                    print(f"[CarlaAir] world.tick() error: {exc}")
                    break

    def close(self) -> None:
        print("[CarlaAir] Shutting down ...")
        # Destroy ground vehicles
        for actor in self._actors.values():
            try:
                actor.destroy()
            except Exception:
                pass
        self._actors.clear()

        # Destroy pedestrians
        if self._ped_mgr:
            self._ped_mgr.destroy_all()

        # Land drone
        if self._drone:
            self._drone.land_now()

        # Restore CARLA settings
        if self._world and self._settings and SYNC_MODE:
            try:
                self._world.apply_settings(self._settings)
            except Exception:
                pass
        print("[CarlaAir] Bridge closed.")

    # -- Ground vehicle sync --------------------------------------------------

    def _sync_vehicles(self) -> None:
        try:
            current_ids = set(traci.vehicle.getIDList())
        except traci.exceptions.TraCIException:
            return

        # Filter out eVTOL vehicles (those are handled by the drone)
        current_ids = {v for v in current_ids if not v.startswith("evtol_")}
        tracked = set(self._actors.keys())

        for vid in current_ids - tracked:
            self._spawn_vehicle(vid)
        for vid in current_ids & tracked:
            self._move_vehicle(vid)
        for vid in tracked - current_ids:
            self._destroy_vehicle(vid)

    def _spawn_vehicle(self, vid: str) -> None:
        try:
            vtype = traci.vehicle.getTypeID(vid)
        except traci.exceptions.TraCIException:
            return
        bp = self._bp_rental if "rental" in vtype else self._bp_passenger
        if bp is None:
            return
        tf = self._vehicle_transform(vid)
        if tf is None:
            return
        try:
            actor = self._world.try_spawn_actor(bp, tf)
            if actor:
                actor.set_simulate_physics(False)
                self._actors[vid] = actor
                if len(self._actors) <= 5:
                    print(f"[CarlaAir] Spawned {vid} at "
                          f"({tf.location.x:.1f},{tf.location.y:.1f},{tf.location.z:.1f})")
        except Exception as exc:
            if len(self._actors) <= 2:
                print(f"[CarlaAir] Spawn failed for {vid}: {exc}")

    def _move_vehicle(self, vid: str) -> None:
        tf = self._vehicle_transform(vid)
        if tf is None:
            return
        try:
            self._actors[vid].set_transform(tf)
        except Exception:
            pass

    def _destroy_vehicle(self, vid: str) -> None:
        actor = self._actors.pop(vid, None)
        if actor:
            try:
                actor.destroy()
            except Exception:
                pass

    def _vehicle_transform(self, vid: str):
        try:
            x, y = traci.vehicle.getPosition(vid)
            angle = traci.vehicle.getAngle(vid)
        except traci.exceptions.TraCIException:
            return None
        cx, cy, cz = sumo_to_carla(x, y)
        yaw = sumo_angle_to_carla_yaw(angle)
        return carla.Transform(
            carla.Location(x=cx, y=cy, z=cz),
            carla.Rotation(yaw=yaw),
        )

    # -- Helpers --------------------------------------------------------------

    def _pace(self, t: float) -> None:
        """Keep simulation roughly in real-time so drone flights have time."""
        if self._wall_start is None:
            self._wall_start = time.monotonic()
            self._sim_start_t = t
        sim_elapsed = t - (self._sim_start_t or 0.0)
        wall_elapsed = time.monotonic() - self._wall_start
        if sim_elapsed > wall_elapsed:
            time.sleep(min(sim_elapsed - wall_elapsed, 1.0))

    def _aim_spectator(self) -> None:
        try:
            cx_a, cy_a, _ = vertiport_carla("vp_a")
            cx_b, cy_b, _ = vertiport_carla("vp_b")
            mid_x = (cx_a + cx_b) / 2
            mid_y = (cy_a + cy_b) / 2
            self._world.get_spectator().set_transform(
                carla.Transform(
                    carla.Location(x=mid_x, y=mid_y - 30.0, z=100.0),
                    carla.Rotation(pitch=-55, yaw=90),
                )
            )
        except Exception:
            pass

    def _draw_hud(self, t: float, parking_managers: dict) -> None:
        for vp_id, pm in parking_managers.items():
            cx, cy, _ = vertiport_carla(vp_id)
            drone_status = self._drone.phase.value if self._drone else "?"
            label = (
                f"{vp_id.upper()}  "
                f"Park: {pm.current_occupancy}/{pm.vp_cfg['max_parking']}  "
                f"Q: {pm.current_queue_length}  "
                f"Drone: {drone_status}"
            )
            self._debug.draw_string(
                carla.Location(x=cx, y=cy, z=15.0),
                label,
                draw_shadow=True,
                color=carla.Color(r=255, g=220, b=0),
                life_time=2.0,
                persistent_lines=False,
            )

    @staticmethod
    def _pick_bp(lib, preferences):
        for name in preferences:
            bps = lib.filter(name)
            if bps:
                bp = random.choice(list(bps))
                print(f"[CarlaAir] Blueprint: {bp.id}")
                return bp
        return None
