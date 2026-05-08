"""
config_carla.py — CARLA-specific settings for the SUMO–AAMSim bridge.

Coordinate system
-----------------
SUMO  : X = east (+right), Y = north (+up on screen). Network spans:
          X ∈ [0, 1300],  Y ∈ [-330, 200]
CARLA : X = forward (east in Town03), Y = right (south), Z = up.
        CARLA Y increases southward — opposite to SUMO Y.

Transform:
    carla.x = SCALE * sumo.x  + OFFSET_X
    carla.y = SCALE * (-sumo.y) + OFFSET_Y    ← Y-axis flip
    carla.z = GROUND_Z  (or altitude for eVTOL)

Yaw:  carla_yaw = (sumo_angle - 90 + YAW_OFFSET) % 360
  SUMO 0°(N)→270°  90°(E)→0°  180°(S)→90°  270°(W)→180°  ✓

Town03 world extents: roughly X ∈ [-200, 200], Y ∈ [-200, 200].
With SCALE=0.14, the 1300 m SUMO network fits in ~182 m of CARLA space,
centred at (0, 0).  Tune below if you use a different map.
"""

import os

# ── Server connection ─────────────────────────────────────────────────────────
CARLA_HOST    = "localhost"
CARLA_PORT    = 2000
CARLA_TIMEOUT = 15.0

# ── Map ───────────────────────────────────────────────────────────────────────
# Town03 is a medium-sized urban map with roundabouts — good fit for this sim.
# Set to None to use whatever is already loaded.
CARLA_MAP = "Town03"

# ── Coordinate transform (SUMO → CARLA world space) ──────────────────────────
# Town03 centre ≈ (0, 0).  Scale 0.14 maps 1300m SUMO → 182m CARLA (fits).
SCALE    = 0.14
OFFSET_X = -91.0    # centreX = -(1300*0.14)/2
OFFSET_Y =  23.0    # centreY = (330*0.14)/2  (SUMO Y ∈ [-330,200] → centre)
GROUND_Z = 0.5      # lift off road surface to avoid clipping

# ── Yaw ───────────────────────────────────────────────────────────────────────
YAW_OFFSET = 0.0    # fine-tune if vehicles face the wrong direction on your map

# ── eVTOL animation ───────────────────────────────────────────────────────────
EVTOL_ALTITUDE_M = 60.0     # spawn altitude above ground (metres, CARLA Z)
EVTOL_DESCEND_S  = 8.0      # seconds for descent / ascent animation

# ── Blueprint preferences ─────────────────────────────────────────────────────
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
EVTOL_BLUEPRINTS = [
    # No UAM blueprint in stock CARLA — use a small vehicle elevated at altitude.
    # It will be tinted cyan and physics-disabled so it floats.
    "vehicle.micro.microlino",
    "vehicle.tesla.cybertruck",
    "vehicle.mini.cooperst",
]

# ── Rendering ─────────────────────────────────────────────────────────────────
SYNC_MODE       = True      # tick CARLA once per SUMO step (deterministic)
SHOW_DEBUG_TEXT = True      # draw parking / queue labels in world space
SPECTATOR_ZOOM  = 120.0     # camera height for initial overview

# ── Weather preset (applied at startup) ──────────────────────────────────────
# Options: Default, ClearNoon, CloudyNoon, WetNoon, HardRainNoon,
#          MidRainyNoon, SoftRainNoon, ClearSunset, CloudySunset, ...
WEATHER_PRESET  = "ClearNoon"
