"""
vehicle_sync.py — Synchronises the SUMO vehicle pool with CARLA actors.

Each SUMO step:
  • New vehicles   → spawn CARLA actor with the correct blueprint + color.
  • Moved vehicles → teleport actor to updated position + heading.
  • Removed vehicles → destroy CARLA actor immediately.

Vehicle type → blueprint / color mapping is driven by config_carla.py.
"""

import random
import traci
import traci.exceptions

try:
    import carla
except ImportError:
    raise ImportError(
        "The 'carla' Python package is not installed.\n"
        "Install it from your CARLA installation:\n"
        "  pip install <CARLA_ROOT>/PythonAPI/carla/dist/carla-*.whl"
    )

from .coordinate_map import sumo_to_carla_location, sumo_angle_to_carla_yaw
from .config_carla import (
    PASSENGER_BLUEPRINTS,
    RENTAL_BLUEPRINTS,
    GROUND_Z,
)


class VehicleSync:
    """
    Maintains a mirror of the SUMO vehicle population as CARLA actors.

    Parameters
    ----------
    world   : carla.World
    lib     : carla.BlueprintLibrary  (from world.get_blueprint_library())
    """

    def __init__(self, world: "carla.World", lib: "carla.BlueprintLibrary") -> None:
        self._world  = world
        self._lib    = lib
        self._actors: dict[str, "carla.Actor"] = {}   # sumo_id → carla actor

        # Pre-select blueprints so we don't search the library every step
        self._bp_passenger = self._pick_blueprint(PASSENGER_BLUEPRINTS, "vehicle.tesla.model3")
        self._bp_rental    = self._pick_blueprint(RENTAL_BLUEPRINTS,    "vehicle.audi.tt")

        # Tint rental cars orange so they stand out
        if self._bp_rental and self._bp_rental.has_attribute("color"):
            self._bp_rental.set_attribute("color", "255,140,0")

    # ── Public ────────────────────────────────────────────────────────────────

    def sync(self) -> None:
        """Call once per SUMO step to apply all add/move/remove operations."""
        try:
            current_ids = set(traci.vehicle.getIDList())
        except traci.exceptions.TraCIException:
            return

        tracked_ids = set(self._actors.keys())

        # Spawn new vehicles
        for vid in current_ids - tracked_ids:
            self._spawn(vid)

        # Update positions
        for vid in current_ids & tracked_ids:
            self._move(vid)

        # Destroy removed vehicles
        for vid in tracked_ids - current_ids:
            self._destroy(vid)

    def destroy_all(self) -> None:
        """Remove all managed actors — call on simulation shutdown."""
        for actor in self._actors.values():
            try:
                actor.destroy()
            except Exception:
                pass
        self._actors.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _spawn(self, vid: str) -> None:
        try:
            vtype = traci.vehicle.getTypeID(vid)
        except traci.exceptions.TraCIException:
            return

        bp = self._bp_rental if "rental" in vtype else self._bp_passenger
        if bp is None:
            return

        transform = self._get_transform(vid)
        if transform is None:
            return

        try:
            actor = self._world.try_spawn_actor(bp, transform)
            if actor is not None:
                actor.set_simulate_physics(False)   # pure kinematic — no physics
                self._actors[vid] = actor
        except Exception as exc:
            print(f"[CARLA] Could not spawn actor for {vid}: {exc}")

    def _move(self, vid: str) -> None:
        transform = self._get_transform(vid)
        if transform is None:
            return
        try:
            self._actors[vid].set_transform(transform)
        except Exception:
            pass

    def _destroy(self, vid: str) -> None:
        actor = self._actors.pop(vid, None)
        if actor is not None:
            try:
                actor.destroy()
            except Exception:
                pass

    def _get_transform(self, vid: str) -> "carla.Transform | None":
        try:
            x, y  = traci.vehicle.getPosition(vid)
            angle = traci.vehicle.getAngle(vid)
        except traci.exceptions.TraCIException:
            return None

        cx, cy, cz = sumo_to_carla_location(x, y)
        yaw        = sumo_angle_to_carla_yaw(angle)
        return carla.Transform(
            carla.Location(x=cx, y=cy, z=cz),
            carla.Rotation(yaw=yaw),
        )

    def _pick_blueprint(
        self, preferences: list[str], fallback: str
    ) -> "carla.ActorBlueprint | None":
        """Return the first blueprint from the preference list that exists."""
        for name in preferences:
            bps = self._lib.filter(name)
            if bps:
                bp = random.choice(list(bps))
                print(f"[CARLA] Blueprint selected: {bp.id}")
                return bp
        # Try fallback
        bps = self._lib.filter(fallback)
        if bps:
            bp = random.choice(list(bps))
            print(f"[CARLA] Blueprint fallback: {bp.id}")
            return bp
        print(f"[CARLA WARN] No matching blueprint found (tried {preferences + [fallback]}).")
        return None
