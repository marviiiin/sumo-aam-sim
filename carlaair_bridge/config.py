"""
config.py — CarlaAir bridge settings for Town10HD.

CarlaAir runs CARLA (port 2000) and AirSim (port 41451) in a single
Unreal Engine process.  Ground vehicles are mirrored via the CARLA API;
eVTOL flights are flown as real AirSim drones.

Coordinate pipeline (Town10HD OpenDRIVE-converted SUMO network):
    SUMO_x  =  CARLA_x        (1:1, no scale or offset)
    SUMO_y  = -CARLA_y         (y-flipped by OpenDRIVE conversion)

    CARLA:   carla_x =  sumo_x
             carla_y = -sumo_y
             carla_z = GROUND_Z

    AirSim:  airsim_x =  carla_x + 172.20
             airsim_y =  carla_y - 183.86
             airsim_z = -carla_z +  27.45

Town10HD main E-W road in SUMO: y ~ -23, x from -101 to +96
    VP-Alpha at junction 189 (SUMO -47, -23  |  CARLA -47, 23)
    VP-Beta  at junction 841 (SUMO  42, -31  |  CARLA  42, 31)
"""

# -- Server connection --------------------------------------------------------
CARLA_HOST    = "localhost"
CARLA_PORT    = 2000
CARLA_TIMEOUT = 15.0

AIRSIM_HOST   = "127.0.0.1"
AIRSIM_PORT   = 41451

# -- Map (don't reload — CarlaAir boots with Town10HD already) ----------------
CARLA_MAP = None  # None = use whatever is loaded (Town10HD)

# -- SUMO -> CARLA coordinate transform (Town10HD OpenDRIVE) -----------------
# 1:1 scale, y-flipped.  The y-flip is handled in coordinate_map.py.
SCALE    = 1.0
OFFSET_X = 0.0
OFFSET_Y = 0.0
GROUND_Z = 0.6            # Town10HD road surface

YAW_OFFSET = 0.0

# -- CARLA -> AirSim NED offset (Town10HD, measured) --------------------------
AIRSIM_OFFSET_X =  172.20
AIRSIM_OFFSET_Y = -183.86
AIRSIM_OFFSET_Z =   27.45

# -- Drone flight parameters --------------------------------------------------
DRONE_VEHICLE   = "SimpleFlight"       # AirSim vehicle name
CRUISE_ALT_M    = 25.0                 # metres above ground
CRUISE_SPEED_MS = 30.0                 # m/s horizontal flight speed
CLIMB_SPEED_MS  = 8.0
DESCENT_SPEED_MS = 5.0

# Phase completion tolerances
ALT_TOL_M       = 3.0
POS_TOL_M       = 25.0                 # close enough to vertiport to begin landing
MIN_PHASE_S     = 2.0                  # minimum seconds in each phase

# -- CARLA vehicle blueprints ------------------------------------------------
PASSENGER_BLUEPRINTS = [
    "vehicle.tesla.model3",
    "vehicle.audi.a2",
    "vehicle.nissan.micra",
    "vehicle.mini.cooperst",
]
RENTAL_BLUEPRINTS = [
    "vehicle.audi.tt",
    "vehicle.lincoln.mkz_2020",
    "vehicle.ford.mustang",
    "vehicle.seat.leon",
]

# -- Rendering ----------------------------------------------------------------
SYNC_MODE       = False    # async is more stable with CarlaAir
SHOW_DEBUG_TEXT  = True
