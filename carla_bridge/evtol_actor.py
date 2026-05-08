"""
evtol_actor.py — eVTOL arrival / departure animation in CARLA.

On each eVTOL arrival event (detected via EvtolArrivalHandler.step_arrivals > 0):
  1. Spawn a CARLA actor at EVTOL_ALTITUDE_M above the vertiport.
  2. Smoothly descend to ground level over EVTOL_DESCEND_S seconds.
  3. Hold briefly on the pad, then ascend and despawn.

Since CARLA actors don't self-animate in Python, we drive the motion by calling
set_transform() every SUMO step from a lightweight state machine.
"""

import time
from dataclasses import dataclass, field
from enum import Enum, auto

try:
    import carla
except ImportError:
    raise ImportError("carla package not found — see carla_bridge/vehicle_sync.py")

from .coordinate_map import vertiport_carla_location
from .config_carla import (
    EVTOL_ALTITUDE_M,
    EVTOL_DESCEND_S,
    EVTOL_BLUEPRINTS,
    GROUND_Z,
)


class _Phase(Enum):
    DESCEND = auto()
    HOLD    = auto()
    ASCEND  = auto()
    DONE    = auto()


@dataclass
class _EvtolInstance:
    actor:      "carla.Actor"
    vp_id:      str
    phase:      _Phase = _Phase.DESCEND
    phase_start: float = field(default_factory=time.monotonic)
    passengers: int = 0

    HOLD_S    = 5.0                          # seconds on pad before departure
    ASCEND_S  = EVTOL_DESCEND_S             # same duration for ascent


class EvtolActorManager:
    """
    Manages active eVTOL actors in CARLA for all vertiports.

    Parameters
    ----------
    world : carla.World
    lib   : carla.BlueprintLibrary
    """

    def __init__(
        self, world: "carla.World", lib: "carla.BlueprintLibrary"
    ) -> None:
        self._world    = world
        self._lib      = lib
        self._bp       = self._select_blueprint()
        self._active: list[_EvtolInstance] = []
        self._seq      = 0

    # ── Public ────────────────────────────────────────────────────────────────

    def spawn_arrival(self, vp_id: str, passengers: int) -> None:
        """Trigger an eVTOL arrival animation at the named vertiport."""
        if self._bp is None:
            return

        cx, cy, _ = vertiport_carla_location(vp_id, altitude=EVTOL_ALTITUDE_M)
        transform  = carla.Transform(
            carla.Location(x=cx, y=cy, z=EVTOL_ALTITUDE_M),
            carla.Rotation(pitch=0, yaw=0, roll=0),
        )
        actor = self._world.try_spawn_actor(self._bp, transform)
        if actor is None:
            print(f"[CARLA] Could not spawn eVTOL actor at {vp_id}")
            return

        actor.set_simulate_physics(False)
        self._seq += 1
        instance = _EvtolInstance(
            actor=actor, vp_id=vp_id, passengers=passengers
        )
        self._active.append(instance)
        print(
            f"[CARLA] eVTOL spawned at {vp_id} altitude={EVTOL_ALTITUDE_M}m "
            f"({passengers} pax)"
        )

    def tick(self) -> None:
        """
        Advance animation state for every active eVTOL.
        Call once per SUMO step (= once per CarlaBridge.sync() call).
        """
        still_active: list[_EvtolInstance] = []
        now = time.monotonic()

        for ev in self._active:
            phase_elapsed = now - ev.phase_start

            if ev.phase == _Phase.DESCEND:
                frac = min(phase_elapsed / EVTOL_DESCEND_S, 1.0)
                z    = EVTOL_ALTITUDE_M * (1.0 - frac) + GROUND_Z
                self._set_altitude(ev, z)
                if frac >= 1.0:
                    ev.phase       = _Phase.HOLD
                    ev.phase_start = now

            elif ev.phase == _Phase.HOLD:
                self._set_altitude(ev, GROUND_Z)
                if phase_elapsed >= _EvtolInstance.HOLD_S:
                    ev.phase       = _Phase.ASCEND
                    ev.phase_start = now

            elif ev.phase == _Phase.ASCEND:
                frac = min(phase_elapsed / _EvtolInstance.ASCEND_S, 1.0)
                z    = GROUND_Z + EVTOL_ALTITUDE_M * frac
                self._set_altitude(ev, z)
                if frac >= 1.0:
                    ev.phase = _Phase.DONE

            if ev.phase == _Phase.DONE:
                try:
                    ev.actor.destroy()
                except Exception:
                    pass
                print(f"[CARLA] eVTOL departed from {ev.vp_id}")
            else:
                still_active.append(ev)

        self._active = still_active

    def destroy_all(self) -> None:
        for ev in self._active:
            try:
                ev.actor.destroy()
            except Exception:
                pass
        self._active.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _set_altitude(self, ev: _EvtolInstance, z: float) -> None:
        cx, cy, _ = vertiport_carla_location(ev.vp_id)
        try:
            ev.actor.set_transform(
                carla.Transform(
                    carla.Location(x=cx, y=cy, z=z),
                    carla.Rotation(yaw=0),
                )
            )
        except Exception:
            pass

    def _select_blueprint(self) -> "carla.ActorBlueprint | None":
        for name in EVTOL_BLUEPRINTS:
            bps = self._lib.filter(name)
            if bps:
                import random
                bp = random.choice(list(bps))
                # Give it a distinctive color if supported
                if bp.has_attribute("color"):
                    bp.set_attribute("color", "0,200,255")   # cyan
                print(f"[CARLA] eVTOL blueprint: {bp.id}")
                return bp
        print("[CARLA WARN] No eVTOL blueprint found — arrivals will not be visualised.")
        return None
