"""
config.py — Central configuration for SUMO–AAMSim eVTOL ground-traffic integration.
Edit this file to tune every aspect of the simulation without touching any other module.
"""
import os
import sys

# ── SUMO paths ────────────────────────────────────────────────────────────────
SUMO_HOME = os.environ.get("SUMO_HOME", "")
if not SUMO_HOME:
    raise EnvironmentError(
        "SUMO_HOME environment variable is not set. "
        "Set it to your SUMO installation directory (e.g. C:\\Program Files (x86)\\Eclipse\\Sumo)."
    )

_bin_ext = ".exe" if sys.platform == "win32" else ""
SUMO_BINARY        = os.path.join(SUMO_HOME, "bin", f"sumo{_bin_ext}")
SUMO_GUI_BINARY    = os.path.join(SUMO_HOME, "bin", f"sumo-gui{_bin_ext}")
NETCONVERT_BINARY  = os.path.join(SUMO_HOME, "bin", f"netconvert{_bin_ext}")

# Add SUMO Python tools to sys.path (required for traci / sumolib)
_tools_dir = os.path.join(SUMO_HOME, "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

# ── Project paths ─────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
NETWORK_DIR      = os.path.join(_HERE, "network")
SUMOCFG_PATH     = os.path.join(_HERE, "sumo_aam_sim.sumocfg")
NET_XML_PATH     = os.path.join(NETWORK_DIR, "town10hd_vp.net.xml")
ADD_XML_PATH     = os.path.join(NETWORK_DIR, "additionals.add.xml")
ROUTES_XML_PATH  = os.path.join(NETWORK_DIR, "routes.rou.xml")
METRICS_OUT_DIR  = os.path.join(_HERE, "output")

# ── Simulation control ────────────────────────────────────────────────────────
SIMULATION_DURATION_S = 18_000  # seconds (5 hours, matches passenger data span)
STEP_LENGTH_S         = 1.0     # simulation step length in seconds
USE_GUI               = False   # True → launches sumo-gui for visual debugging

# ── eVTOL arrival parameters ─────────────────────────────────────────────────
# Passenger arrival rates from Tampa Bay AAM study (evtol in and out of vehicle.xlsx).
# Tampa ↔ Brandon pair over ~5 hrs: Tampa→Brandon 33.7 pax/hr, Brandon→Tampa 30.0 pax/hr.
# With 4 pax/flight: vp_a→vp_b ~8.4 flights/hr (7.1 min), vp_b→vp_a ~7.5 flights/hr (8.0 min).
# Mean inter-arrival: (7.1+8.0)/2 ≈ 7.5 min.  Using Uniform[5.5, 9.5] to approximate.
EVTOL_ARRIVAL_INTERVAL_MIN_M = 5.5   # minutes (mean ~7.5 min ≈ 8 flights/hr/vertiport)
EVTOL_ARRIVAL_INTERVAL_MAX_M = 9.5   # minutes
PASSENGERS_PER_FLIGHT_MIN    = 4
PASSENGERS_PER_FLIGHT_MAX    = 4

# ── Parking & visitor ────────────────────────────────────────────────────────
MAX_PARKING_SPACES        = 20      # spaces per vertiport parking lot
VISITOR_PARK_DURATION_MIN = 120     # seconds a visitor car stays parked (min)
VISITOR_PARK_DURATION_MAX = 600     # seconds a visitor car stays parked (max)
VISITOR_INTERVAL_MIN      = 90      # seconds between visitor vehicle injections
VISITOR_INTERVAL_MAX      = 360

# ── Spillback detection ───────────────────────────────────────────────────────
# Approach edge vehicle count at or above this → spillback event logged.
SPILLBACK_THRESHOLD = 5

# ── Metrics logging ───────────────────────────────────────────────────────────
METRICS_LOG_INTERVAL_S = 30     # write one CSV row every N simulation seconds

# ── Vehicle type IDs (must match routes.rou.xml <vType> ids) ─────────────────
VISITOR_VTYPE = "passenger"
RENTAL_VTYPE  = "rental_car"
EVTOL_VTYPE   = "evtol"

# ─────────────────────────────────────────────────────────────────────────────
# Vertiport definitions — 2-vertiport scenario: Alpha (vp_a) and Beta (vp_b)
#
# Edge / stop IDs here must match what generate_town10hd_net.py produces.
# Re-run generate_town10hd_net.py if you need a different physical layout.
# ─────────────────────────────────────────────────────────────────────────────
VERTIPORTS: dict = {
    "vp_a": {
        "name":            "Vertiport Alpha",
        "approach_edge":   "e_vp1_approach",
        "waiting_stop":    "bs_vp1_wait",
        "parking_area":    "pa_vp1",
        "rental_edge":     "e_vp1_rental",
        "rental_routes":   ["rental_vp1_east", "rental_vp1_west"],
        "visitor_routes":  ["visitor_from_west_vp1", "visitor_from_east_vp1"],
        "max_parking":     MAX_PARKING_SPACES,
        # eVTOL flight: route ID when departing TO each partner, keyed by partner vp_id
        "flight_routes":   {"vp_b": "evtol_vpa_to_vpb"},
        # Prefix used to identify eVTOLs ARRIVING at this vertiport
        "evtol_arrival_prefix": "evtol_to_vp_a_",
    },
    "vp_b": {
        "name":            "Vertiport Beta",
        "approach_edge":   "e_vp2_approach",
        "waiting_stop":    "bs_vp2_wait",
        "parking_area":    "pa_vp2",
        "rental_edge":     "e_vp2_rental",
        "rental_routes":   ["rental_vp2_east", "rental_vp2_west"],
        "visitor_routes":  ["visitor_from_west_vp2", "visitor_from_east_vp2"],
        "max_parking":     MAX_PARKING_SPACES,
        "flight_routes":   {"vp_a": "evtol_vpb_to_vpa"},
        "evtol_arrival_prefix": "evtol_to_vp_b_",
    },
}
