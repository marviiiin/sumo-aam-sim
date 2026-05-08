"""
coordinate_map.py — Bidirectional SUMO ↔ CARLA coordinate transform.

All public functions return plain Python floats / tuples so this module
has no dependency on the `carla` package itself (making unit-testing easier).
"""

import math
from .config_carla import SCALE, OFFSET_X, OFFSET_Y, GROUND_Z, YAW_OFFSET


def sumo_to_carla_location(sumo_x: float, sumo_y: float) -> tuple[float, float, float]:
    """
    Convert a SUMO (x, y) coordinate to a CARLA (x, y, z) world location.

    SUMO  : x east,  y north.
    CARLA : x east,  y south  (Y-axis flipped).
    """
    cx = SCALE * sumo_x  + OFFSET_X
    cy = SCALE * (-sumo_y) + OFFSET_Y
    cz = GROUND_Z
    return cx, cy, cz


def sumo_to_carla_location_elevated(
    sumo_x: float, sumo_y: float, altitude: float
) -> tuple[float, float, float]:
    """Same as sumo_to_carla_location but at a given altitude (for eVTOL)."""
    cx, cy, _ = sumo_to_carla_location(sumo_x, sumo_y)
    return cx, cy, altitude


def sumo_angle_to_carla_yaw(sumo_angle_deg: float) -> float:
    """
    Convert SUMO compass bearing (0=N, 90=E, clockwise) to CARLA yaw.

    CARLA axes: X=east, Y=south (right), Z=up.
    CARLA yaw:  0=+X(east), 90=+Y(south), clockwise.

    With the Y-flip in sumo_to_carla_location (+sumo_Y → -carla_Y):
        SUMO 0°(N)  → carla 270° (facing −Y = north) ✓
        SUMO 90°(E) → carla 0°   (facing +X = east)  ✓
        SUMO 180°(S)→ carla 90°  (facing +Y = south) ✓
        SUMO 270°(W)→ carla 180° (facing −X = west)  ✓

    Formula: carla_yaw = (sumo_angle − 90 + YAW_OFFSET) % 360
    YAW_OFFSET = 0 for a standard CARLA Town map; tune if your map is rotated.
    """
    return (sumo_angle_deg - 90.0 + YAW_OFFSET) % 360.0


def carla_to_sumo_location(carla_x: float, carla_y: float) -> tuple[float, float]:
    """Inverse transform — useful for debugging / map alignment."""
    sumo_x = (carla_x - OFFSET_X) / SCALE
    sumo_y = -((carla_y - OFFSET_Y) / SCALE)
    return sumo_x, sumo_y


# ── Vertiport centre helpers ───────────────────────────────────────────────────

# SUMO network coordinates of each vertiport's parking-lot centre
# (derived from vertiport_generator.py NODES).
_VP_SUMO_CENTRES: dict[str, tuple[float, float]] = {
    "vp_a": (300.0, -255.0),   # midpoint of VP-Alpha parking edge
    "vp_b": (950.0, -255.0),   # midpoint of VP-Beta parking edge
}


def vertiport_carla_location(
    vp_id: str, altitude: float = 0.0
) -> tuple[float, float, float]:
    """Return CARLA world location for the centre of a vertiport, at given altitude."""
    sx, sy = _VP_SUMO_CENTRES[vp_id]
    cx, cy, cz = sumo_to_carla_location(sx, sy)
    return cx, cy, cz + altitude
