"""
config_airsim.py — AirSim/UE5-specific settings for the SUMO–AAMSim bridge.

Coordinate pipeline
-------------------
Each vertiport has a real-world GPS anchor (lat, lon). The bridge converts
those to AirSim NED meters using CESIUM_ORIGIN_LAT/LON as the reference —
this must match the CesiumGeoreference origin in the UE5 project (the
lat/lon you set on the CesiumGeoreference actor inside NewMap.umap).

AirSim axes : X = north (+N), Y = east (+E), Z = down (+D, negative = up)

Flight profile
--------------
Bridge-launched eVTOL flights use the same 3-phase profile you already
validated: climb -> cruise -> land, scaled to the inter-vertiport distance.
"""

# ── AirSim RPC server ─────────────────────────────────────────────────────────
AIRSIM_HOST    = "127.0.0.1"
AIRSIM_PORT    = 41451          # default AirSim port; override in settings.json
AIRSIM_TIMEOUT_S = 30.0    # larger than default so simSpawnObject (blueprint
                            # pawns with construction scripts) doesn't time out

# ── Cesium / UE5 world anchor ────────────────────────────────────────────────
# This MUST match the Origin Latitude / Origin Longitude on the
# CesiumGeoreference actor in your UE5 level (NewMap.umap).
# Default here is Tampa Downtown (Curtis Hixon Waterfront Park), matching
# the previous tampa_usf_evtol script.  If your CesiumGeoreference origin
# is somewhere else (e.g. USF campus), change these two numbers.
CESIUM_ORIGIN_LAT = 27.9506
CESIUM_ORIGIN_LON = -82.4594

# ── Fleet composition ────────────────────────────────────────────────────────
# Must match vehicle names registered in ~/Documents/AirSim/settings.json.
# Generate that file with:
#     python ../Documents/Unreal\ Projects/evttolll/Scripts/evtol_settings.py --dual
# Or add more vehicles manually in settings.json.
EVTOL_FLEET = [
    "eVTOL1",
    "eVTOL2",
]
# If True, the bridge will also register "Drone1" as a fallback vehicle.
INCLUDE_DRONE_FALLBACK = True
FALLBACK_DRONE_NAME = "Drone1"

# ── Vertiport GPS anchors (real-world) ───────────────────────────────────────
# vp_id → (latitude, longitude).  These are the physical landing pads the
# AirSim eVTOLs fly between.  Tune to match your Cesium world's geography.
# Default: Tampa Downtown (vp_a) and USF Tampa (vp_b).
VERTIPORT_GPS = {
    "vp_a": (27.9506, -82.4594),   # Curtis Hixon / Downtown Tampa
    "vp_b": (28.0619, -82.4128),   # USF Tampa campus
}

# ── Flight parameters ────────────────────────────────────────────────────────
CRUISE_ALT_M      = 305.0   # 1000 ft — FAA min over congested urban
HOVER_ALT_M       = 50.0    # low-altitude hover for take-off / transition
CLIMB_SPEED_MS    = 8.0     # ~1575 ft/min — typical eVTOL climb rate
CRUISE_SPEED_MS   = 60.0    # ~135 mph — conservative Joby S4-class cruise
DESCENT_SPEED_MS  = 4.0

# Controller tolerances (when to consider a phase "done")
ALT_TOL_M         = 3.0
POS_TOL_M         = 10.0
LAND_VEL_TOL_MS   = 0.3
LAND_ALT_TOL_M    = 1.5     # metres above ground_z considered "on pad"

# Minimum time in each phase (prevents false-positive early advance)
MIN_PHASE_S = {
    "takeoff": 3.0,
    "climb":   2.0,
    "cruise":  2.0,
    "descend": 2.0,
}

# ── Telemetry ────────────────────────────────────────────────────────────────
LOG_FLIGHTS   = True            # write a CSV row per completed flight
FLIGHT_LOG_DIR = "output"       # relative to sumo_aam_sim/ root

# ── Ground-vehicle mirror (SUMO cars → UE5 actors) ──────────────────────────
# Mirrors every SUMO vehicle into the UE5 world each tick via
# simSpawnObject / simSetObjectPose / simDestroyObject.  Requires an AirSim
# plugin build that exposes those RPCs (evttolll's bundled plugin does).
#
# Off by default: spawning blueprint pawns (the evttolll project's car
# assets) via AirSim RPC can freeze the editor.  Flip to True once you've
# confirmed a spawn-safe asset name in CAR_ASSET_NAMES below.  Pass
# --mirror on the command line to override without editing this file.
GROUND_CAR_ENABLED = False

# First-match-wins list of UE5 asset names to use for spawned cars.
# simListAssets() is queried first; the bridge picks the first candidate
# that appears (exact match, then case-insensitive substring).  If
# simListAssets isn't available, the first name here is tried blindly.
CAR_ASSET_NAMES = [
    "SuvCarPawn",        # evttolll's AirSim Vehicle BP — real drivable SUV
    "VehicleAdvPawn",    # generic vehicle BP fallback
    "SedanSUV",          # AirSim default static mesh
    "Sedan",
    "SUV",
    "Car",
]
# Whether the matched asset is an Unreal Blueprint (spawns as a full pawn)
# vs a static mesh actor.  True for *Pawn / *_BP assets, False for plain
# static meshes.  Controls the `is_blueprint` flag passed to simSpawnObject.
CAR_ASSET_IS_BLUEPRINT = True

# Hard cap to protect the UE5 renderer from runaway vehicle counts.
MIRROR_MAX_VEHICLES = 20
# Max number of spawn RPCs to issue per SUMO step (blueprint pawns take
# hundreds of ms each, so spawning a whole flight of cars in one tick
# would block the bridge).  Excess vehicles are spawned next tick.
MIRROR_SPAWNS_PER_TICK = 2
# How many consecutive simSpawnObject failures before we give up and
# disable the mirror for the rest of the run.  One transient RPC timeout
# shouldn't kill the whole feature.
MIRROR_MAX_SPAWN_FAILURES = 5

# SUMO→NED coordinate mapping.  SUMO's 2-D network uses +x = east, +y = north.
# If your SUMO network was generated with an inverted Y axis, set this True.
SUMO_COORD_FLIP_Y = False
# Translate SUMO coordinates before mapping to NED.  Use this to line the
# SUMO network up with the visible UE5 world (Cesium origin).  Metres.
SUMO_X_OFFSET_M = 0.0
SUMO_Y_OFFSET_M = 0.0

# ── Verbose ──────────────────────────────────────────────────────────────────
VERBOSE = True                  # print per-phase transitions
