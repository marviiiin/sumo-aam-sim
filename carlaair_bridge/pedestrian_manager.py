"""
pedestrian_manager.py — CARLA pedestrian spawning and vertiport passenger animation.

Two responsibilities:
1. Ambient pedestrians: random walkers on sidewalks for visual realism.
2. Vertiport passengers: groups that walk toward/away from the eVTOL on landing.

All passenger spawning is deferred to tick() so it never blocks the SUMO TraCI loop.
"""

import math
import random

try:
    import carla
except ImportError:
    carla = None

from .config import GROUND_Z
from .coordinate_map import vertiport_carla, _VP_CARLA_GROUND_Z


# How many ambient pedestrians to maintain
AMBIENT_COUNT = 15

# Passenger spawn radius from vertiport centre (metres)
PAX_SPAWN_RADIUS = 12.0
# How close passengers walk to the eVTOL
PAX_TARGET_RADIUS = 3.0
# Walk speed (m/s)
PAX_SPEED = 1.4


class PedestrianManager:
    """Manages CARLA walkers: ambient sidewalk pedestrians + vertiport passengers."""

    def __init__(self, world: "carla.World") -> None:
        self._world = world
        self._bp_lib = world.get_blueprint_library()

        # Collect walker blueprints
        self._walker_bps = list(self._bp_lib.filter("walker.pedestrian.*"))
        self._controller_bp = self._bp_lib.find("controller.ai.walker")

        # Ambient walkers: list of (walker_actor, controller_actor)
        self._ambient: list[tuple] = []

        # Vertiport passenger groups: list of (walker, controller, vp_id)
        self._passengers: list[tuple] = []

        # Track cleanup timers for passenger groups
        self._pax_cleanup: list[tuple[float, list[tuple]]] = []

        # Deferred passenger spawn queue: each entry is one passenger to spawn
        # (vp_id, cx, cy, ground_z, target_loc, sim_time, group_ref)
        self._spawn_queue: list[dict] = []

        # Pending controller starts (spawned last tick, start this tick)
        self._pending_starts: list[tuple] = []

        print(f"[Pedestrians] {len(self._walker_bps)} walker blueprints available")

    # -- Public API ------------------------------------------------------------

    def spawn_ambient(self) -> None:
        """Spawn ambient pedestrians at random navigation points.
        Safe to call during connect() before the SUMO loop starts."""
        if not self._walker_bps:
            print("[Pedestrians] No walker blueprints — skipping ambient spawn")
            return

        spawned = 0
        for _ in range(AMBIENT_COUNT):
            pair = self._spawn_random_walker()
            if pair:
                self._ambient.append(pair)
                spawned += 1
        print(f"[Pedestrians] Spawned {spawned}/{AMBIENT_COUNT} ambient walkers")

        # Start ambient AI (safe here — called during connect, before SUMO loop)
        try:
            self._world.wait_for_tick()
        except Exception:
            pass
        for walker, controller in self._ambient:
            try:
                controller.start()
                dest = self._world.get_random_location_from_navigation()
                if dest:
                    controller.go_to_location(dest)
                controller.set_max_speed(1.0 + random.random() * 0.8)
            except Exception:
                pass

    def spawn_passengers_at(self, vp_id: str, count: int, sim_time: float) -> None:
        """Queue passengers to spawn near a vertiport. Actual spawning is spread
        across subsequent tick() calls (one per tick) to avoid blocking SUMO."""
        if not self._walker_bps or count <= 0:
            return

        cx, cy, _ = vertiport_carla(vp_id)
        # Use standard road-level Z for walker spawning — CARLA navigation mesh
        # is at road height, not terrain height. CARLA will snap walkers down.
        spawn_z = GROUND_Z
        target_loc = carla.Location(x=cx, y=cy, z=spawn_z + 0.5)

        group_ref = []  # shared list for cleanup tracking
        for i in range(count):
            angle = (2.0 * math.pi * i) / max(count, 1) + random.uniform(-0.3, 0.3)
            self._spawn_queue.append({
                "vp_id": vp_id,
                "sx": cx + PAX_SPAWN_RADIUS * math.cos(angle),
                "sy": cy + PAX_SPAWN_RADIUS * math.sin(angle),
                "ground_z": spawn_z,
                "target_loc": target_loc,
                "group_ref": group_ref,
            })

        # Schedule cleanup 25s from now
        self._pax_cleanup.append((sim_time + 25.0, group_ref))
        print(f"[Pedestrians] Queued {count} passengers for {vp_id}")

    def tick(self, sim_time: float) -> None:
        """Called every SUMO step. Spawns at most one deferred passenger per tick."""
        # 1. Start controllers deferred from previous tick
        if self._pending_starts:
            for walker, ctrl, dest in self._pending_starts:
                try:
                    ctrl.start()
                    ctrl.go_to_location(dest)
                    ctrl.set_max_speed(PAX_SPEED)
                except Exception:
                    pass
            self._pending_starts.clear()

        # 2. Spawn one queued passenger (one per tick to avoid blocking)
        if self._spawn_queue:
            req = self._spawn_queue.pop(0)
            pair = self._spawn_one_passenger(req)
            if pair:
                walker, ctrl = pair
                req["group_ref"].append((walker, ctrl, req["vp_id"]))
                self._passengers.append((walker, ctrl, req["vp_id"]))
                # Defer controller start to next tick
                offset_x = random.uniform(-PAX_TARGET_RADIUS, PAX_TARGET_RADIUS)
                offset_y = random.uniform(-PAX_TARGET_RADIUS, PAX_TARGET_RADIUS)
                dest = carla.Location(
                    x=req["target_loc"].x + offset_x,
                    y=req["target_loc"].y + offset_y,
                    z=req["target_loc"].z,
                )
                self._pending_starts.append((walker, ctrl, dest))

        # 3. Clean up expired passenger groups
        remaining = []
        for deadline, group_ref in self._pax_cleanup:
            if sim_time >= deadline:
                for walker, ctrl, _ in group_ref:
                    try:
                        ctrl.stop()
                        ctrl.destroy()
                    except Exception:
                        pass
                    try:
                        walker.destroy()
                    except Exception:
                        pass
                for item in group_ref:
                    if item in self._passengers:
                        self._passengers.remove(item)
            else:
                remaining.append((deadline, group_ref))
        self._pax_cleanup = remaining

        # 4. Periodically re-target ambient walkers
        if int(sim_time) % 30 == 0:
            for walker, ctrl in self._ambient:
                try:
                    dest = self._world.get_random_location_from_navigation()
                    if dest:
                        ctrl.go_to_location(dest)
                except Exception:
                    pass

    def destroy_all(self) -> None:
        """Clean up all walkers on shutdown."""
        self._spawn_queue.clear()
        self._pending_starts.clear()

        for walker, ctrl, _ in self._passengers:
            try:
                ctrl.stop()
                ctrl.destroy()
            except Exception:
                pass
            try:
                walker.destroy()
            except Exception:
                pass
        self._passengers.clear()
        self._pax_cleanup.clear()

        for walker, ctrl in self._ambient:
            try:
                ctrl.stop()
                ctrl.destroy()
            except Exception:
                pass
            try:
                walker.destroy()
            except Exception:
                pass
        self._ambient.clear()
        print("[Pedestrians] All walkers destroyed")

    # -- Internal --------------------------------------------------------------

    def _spawn_one_passenger(self, req: dict):
        """Spawn a single passenger walker+controller. Returns (walker, ctrl) or None.
        Uses CARLA navigation mesh to find a safe spawn point near the target."""
        bp = random.choice(self._walker_bps)
        if bp.has_attribute("is_invincible"):
            bp.set_attribute("is_invincible", "true")

        # Try navigation-mesh-based spawn first (avoids segfaults in invalid areas)
        walker = None
        for _attempt in range(5):
            nav_loc = self._world.get_random_location_from_navigation()
            if nav_loc is None:
                continue
            # Check if this nav point is within reasonable range of our target
            dx = nav_loc.x - req["sx"]
            dy = nav_loc.y - req["sy"]
            dist = (dx*dx + dy*dy) ** 0.5
            if dist < 40.0:
                spawn_tf = carla.Transform(
                    carla.Location(x=nav_loc.x, y=nav_loc.y, z=nav_loc.z + 0.5),
                    carla.Rotation(yaw=random.uniform(0, 360)),
                )
                try:
                    walker = self._world.try_spawn_actor(bp, spawn_tf)
                except Exception:
                    continue
                if walker:
                    break

        # Fallback: try raw coordinates (works for vp_a area)
        if not walker:
            spawn_tf = carla.Transform(
                carla.Location(x=req["sx"], y=req["sy"], z=req["ground_z"] + 1.0),
                carla.Rotation(yaw=random.uniform(0, 360)),
            )
            try:
                walker = self._world.try_spawn_actor(bp, spawn_tf)
            except Exception:
                return None
            if not walker:
                return None

        try:
            ctrl = self._world.try_spawn_actor(
                self._controller_bp, carla.Transform(), walker)
        except Exception:
            walker.destroy()
            return None
        if not ctrl:
            walker.destroy()
            return None

        return (walker, ctrl)

    def _spawn_random_walker(self):
        """Spawn a single walker at a random navigation location. Returns (walker, ctrl) or None."""
        bp = random.choice(self._walker_bps)
        if bp.has_attribute("is_invincible"):
            bp.set_attribute("is_invincible", "true")

        loc = self._world.get_random_location_from_navigation()
        if not loc:
            return None

        spawn_tf = carla.Transform(
            carla.Location(x=loc.x, y=loc.y, z=loc.z + 1.0),
            carla.Rotation(yaw=random.uniform(0, 360)),
        )
        walker = self._world.try_spawn_actor(bp, spawn_tf)
        if not walker:
            return None

        ctrl = self._world.try_spawn_actor(self._controller_bp, carla.Transform(), walker)
        if not ctrl:
            walker.destroy()
            return None

        return (walker, ctrl)
