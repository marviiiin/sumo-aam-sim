"""
coordinate_map.py — SUMO <-> CARLA <-> AirSim NED coordinate transforms.

CarlaAir runs both CARLA and AirSim in one UE4 process.  The measured
offsets for Town10HD (CarlaAir v0.1.7) are baked into config.py.

The SUMO network was converted from Town10HD's OpenDRIVE export:
    SUMO_x =  CARLA_x   (same x-axis)
    SUMO_y = -CARLA_y    (y-axis flipped)
"""

from .config import (
    SCALE, OFFSET_X, OFFSET_Y, GROUND_Z, YAW_OFFSET,
    AIRSIM_OFFSET_X, AIRSIM_OFFSET_Y, AIRSIM_OFFSET_Z,
)


# -- SUMO -> CARLA -----------------------------------------------------------

def sumo_to_carla(sumo_x: float, sumo_y: float) -> tuple[float, float, float]:
    cx = SCALE * sumo_x + OFFSET_X
    cy = -(SCALE * sumo_y + OFFSET_Y)    # y-flip: OpenDRIVE conversion flips y
    return cx, cy, GROUND_Z


def sumo_angle_to_carla_yaw(sumo_angle_deg: float) -> float:
    # SUMO: 0=north(+y_sumo), 90=east(+x), clockwise
    # With y-flip: SUMO north(+y) = CARLA south(-y)
    # CARLA: 0=east(+x), 90=north(+y), counterclockwise
    # Derivation: heading vector (sin(a), cos(a)) in SUMO -> (sin(a), -cos(a)) in CARLA
    #   carla_yaw = atan2(-cos(a), sin(a)) = (a - 90) mod 360
    return (sumo_angle_deg - 90.0 + YAW_OFFSET) % 360.0


# -- CARLA -> AirSim NED -----------------------------------------------------

def carla_to_airsim(cx: float, cy: float, cz: float) -> tuple[float, float, float]:
    ax = cx + AIRSIM_OFFSET_X
    ay = cy + AIRSIM_OFFSET_Y
    az = -cz + AIRSIM_OFFSET_Z
    return ax, ay, az


# -- AirSim NED -> CARLA (reverse) -------------------------------------------

def airsim_to_carla(ax: float, ay: float, az: float) -> tuple[float, float, float]:
    cx = ax - AIRSIM_OFFSET_X
    cy = ay - AIRSIM_OFFSET_Y
    cz = -(az - AIRSIM_OFFSET_Z)
    return cx, cy, cz


# -- SUMO -> AirSim NED (convenience) ----------------------------------------

def sumo_to_airsim(sumo_x: float, sumo_y: float) -> tuple[float, float, float]:
    cx, cy, cz = sumo_to_carla(sumo_x, sumo_y)
    return carla_to_airsim(cx, cy, cz)


# -- Vertiport helpers --------------------------------------------------------

# SUMO centres of each vertiport (parking node coordinates)
_VP_SUMO_CENTRES: dict[str, tuple[float, float]] = {
    "vp_a": (-55.0,  16.0),   # n_vpa_park in town10hd_vp network
    "vp_b": ( 34.0,   8.0),   # n_vpb_park in town10hd_vp network
}

# Actual CARLA ground-Z at each vertiport (measured via ray cast).
# These differ because Town10HD terrain is not flat.
_VP_CARLA_GROUND_Z: dict[str, float] = {
    "vp_a":  0.00,
    "vp_b": 38.64,
}

# Home (AirSim origin) CARLA ground-Z
HOME_CARLA_GROUND_Z = 0.15


def vertiport_carla(vp_id: str) -> tuple[float, float, float]:
    sx, sy = _VP_SUMO_CENTRES[vp_id]
    return sumo_to_carla(sx, sy)


def vertiport_airsim(vp_id: str) -> tuple[float, float, float]:
    sx, sy = _VP_SUMO_CENTRES[vp_id]
    return sumo_to_airsim(sx, sy)


def vertiport_ground_z_airsim(vp_id: str) -> float:
    """AirSim NED ground-Z for the given vertiport (actual terrain height)."""
    carla_z = _VP_CARLA_GROUND_Z[vp_id]
    return -carla_z + AIRSIM_OFFSET_Z


def home_ground_z_airsim() -> float:
    """AirSim NED ground-Z at the AirSim origin (home)."""
    return -HOME_CARLA_GROUND_Z + AIRSIM_OFFSET_Z
