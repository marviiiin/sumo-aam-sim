"""
vertiport_generator.py
Programmatically generates SUMO network source XML files for the 2-vertiport scenario.

Network topology (all coordinates in metres, y-axis points north):

  n_w(0,0) ── n_vp1_main(611,0) ── n_mid(857,0) ── n_vp2_main(1104,0) ── n_e(1300,0)
                      │                                         │
               n_vp1_entry(611,-25)                   n_vp2_entry(1104,-25)
                      │                                         │
               n_vp1_wait (611,-45)  [bus stop]        n_vp2_wait (1104,-45)
                      │                                         │
               n_vp1_park (611,-85)  [parking area]    n_vp2_park (1104,-85)
                      │                                         │
               n_vp1_rental(665,-85) [rental centre]   n_vp2_rental(1050,-85)
                      │                                         │
               n_vp1_exit (665,-35) ─────────────      n_vp2_exit (1050,-35)
                      │                                         │
               n_vp1_main(611,0)                       n_vp2_main(1104,0)

Main road is bidirectional (2 lanes each direction), aligned to Town10HD's
east-west road (CARLA y~24.5, x from -89 to +98).

Vertiport junctions are placed at Town10HD side streets:
  VP-Alpha at CARLA x=-1  (SUMO x=611)  — side street Road 20
  VP-Beta  at CARLA x=+70 (SUMO x=1104) — side street Road 21
"""

import os
import textwrap
from config import NETWORK_DIR, MAX_PARKING_SPACES

# ── Node coordinates ──────────────────────────────────────────────────────────
NODES = {
    # Main road (east-west, y=0) — maps to CARLA y~26
    "n_w":          (0,    0),
    "n_vp1_main":   (611,  0),
    "n_mid":        (857,  0),
    "n_vp2_main":   (1104, 0),
    "n_e":          (1300, 0),
    # Vertiport Alpha cluster (south of main road at x=611)
    "n_vp1_entry":  (611,  -25),
    "n_vp1_wait":   (611,  -45),
    "n_vp1_park":   (611,  -85),
    "n_vp1_rental": (665,  -85),
    "n_vp1_exit":   (665,  -35),
    # Vertiport Beta cluster (south of main road at x=1104)
    "n_vp2_entry":  (1104, -25),
    "n_vp2_wait":   (1104, -45),
    "n_vp2_park":   (1104, -85),
    "n_vp2_rental": (1050, -85),
    "n_vp2_exit":   (1050, -35),
    # ── eVTOL sky nodes (y=+5, just above the main road) ────────────────────
    # Flight path follows the road corridor so the drone mirrors the road
    # horizontally while flying at cruise altitude in the 3-D bridge.
    "n_sky_a": (611,  5),    # above VP-Alpha road junction
    "n_sky_1": (740,  5),    # intermediate waypoint
    "n_sky_m": (857,  5),    # above road midpoint
    "n_sky_2": (980,  5),    # intermediate waypoint
    "n_sky_b": (1104, 5),    # above VP-Beta road junction
}

# ── Edge definitions (id, from, to, lanes, speed_m_s, priority) ───────────────
EDGES = [
    # Main road eastbound
    ("e_main_0",  "n_w",          "n_vp1_main",  2, 13.89, 7),
    ("e_main_1",  "n_vp1_main",   "n_mid",        2, 13.89, 7),
    ("e_main_2",  "n_mid",        "n_vp2_main",   2, 13.89, 7),
    ("e_main_3",  "n_vp2_main",   "n_e",          2, 13.89, 7),
    # Main road westbound
    ("e_main_0r", "n_vp1_main",   "n_w",          2, 13.89, 7),
    ("e_main_1r", "n_mid",        "n_vp1_main",   2, 13.89, 7),
    ("e_main_2r", "n_vp2_main",   "n_mid",        2, 13.89, 7),
    ("e_main_3r", "n_e",          "n_vp2_main",   2, 13.89, 7),
    # VP-Alpha internal (approach road monitored for spillback)
    ("e_vp1_approach",      "n_vp1_main",   "n_vp1_entry",  1, 5.56, 5),
    ("e_vp1_wait",          "n_vp1_entry",  "n_vp1_wait",   1, 4.17, 3),
    ("e_vp1_park",          "n_vp1_wait",   "n_vp1_park",   1, 4.17, 3),
    ("e_vp1_rental",        "n_vp1_park",   "n_vp1_rental", 1, 4.17, 3),
    ("e_vp1_exit_internal", "n_vp1_rental", "n_vp1_exit",   1, 4.17, 3),
    ("e_vp1_exit",          "n_vp1_exit",   "n_vp1_main",   1, 5.56, 5),
    # ── eVTOL flight path (follows road corridor at altitude) ─────────────────
    # Climb from parking to road level, cruise along the road, then descend.
    # Speed: climb/descend 20 m/s (~72 km/h), cruise 40 m/s (~144 km/h).
    ("e_takeoff_a",   "n_vp1_park", "n_sky_a",   1, 20.0, 9),   # VP-A ascent
    ("e_cruise_ab_1", "n_sky_a",    "n_sky_1",   1, 40.0, 9),   # eastbound seg 1
    ("e_cruise_ab_2", "n_sky_1",    "n_sky_m",   1, 40.0, 9),   # eastbound seg 2
    ("e_cruise_ab_3", "n_sky_m",    "n_sky_2",   1, 40.0, 9),   # eastbound seg 3
    ("e_cruise_ab_4", "n_sky_2",    "n_sky_b",   1, 40.0, 9),   # eastbound seg 4
    ("e_land_b",      "n_sky_b",    "n_vp2_park",1, 20.0, 9),   # VP-B descent
    ("e_takeoff_b",   "n_vp2_park", "n_sky_b",   1, 20.0, 9),   # VP-B ascent
    ("e_cruise_ba_1", "n_sky_b",    "n_sky_2",   1, 40.0, 9),   # westbound seg 1
    ("e_cruise_ba_2", "n_sky_2",    "n_sky_m",   1, 40.0, 9),   # westbound seg 2
    ("e_cruise_ba_3", "n_sky_m",    "n_sky_1",   1, 40.0, 9),   # westbound seg 3
    ("e_cruise_ba_4", "n_sky_1",    "n_sky_a",   1, 40.0, 9),   # westbound seg 4
    ("e_land_a",      "n_sky_a",    "n_vp1_park",1, 20.0, 9),   # VP-A descent

    # VP-Beta internal
    ("e_vp2_approach",      "n_vp2_main",   "n_vp2_entry",  1, 5.56, 5),
    ("e_vp2_wait",          "n_vp2_entry",  "n_vp2_wait",   1, 4.17, 3),
    ("e_vp2_park",          "n_vp2_wait",   "n_vp2_park",   1, 4.17, 3),
    ("e_vp2_rental",        "n_vp2_park",   "n_vp2_rental", 1, 4.17, 3),
    ("e_vp2_exit_internal", "n_vp2_rental", "n_vp2_exit",   1, 4.17, 3),
    ("e_vp2_exit",          "n_vp2_exit",   "n_vp2_main",   1, 5.56, 5),
]

# ── Lane connections (from_edge, to_edge, from_lane, to_lane) ─────────────────
CONNECTIONS = [
    # ── n_mid: main road through ──────────────────────────────────────────────
    ("e_main_1",  "e_main_2",  0, 0),
    ("e_main_1",  "e_main_2",  1, 1),
    ("e_main_2r", "e_main_1r", 0, 0),
    ("e_main_2r", "e_main_1r", 1, 1),

    # ── n_vp1_main: through + VP-A turn + VP-A exit ───────────────────────────
    ("e_main_0",   "e_main_1",        0, 0),
    ("e_main_0",   "e_main_1",        1, 1),
    ("e_main_0",   "e_vp1_approach",  0, 0),   # eastbound -> VP-A (right turn)
    ("e_main_1r",  "e_main_0r",       0, 0),
    ("e_main_1r",  "e_main_0r",       1, 1),
    ("e_main_1r",  "e_vp1_approach",  0, 0),   # westbound -> VP-A (left turn)
    ("e_vp1_exit", "e_main_1",        0, 0),   # exit VP-A -> east
    ("e_vp1_exit", "e_main_0r",       0, 0),   # exit VP-A -> west

    # ── n_vp2_main: through + VP-B turn + VP-B exit ───────────────────────────
    ("e_main_2",   "e_main_3",        0, 0),
    ("e_main_2",   "e_main_3",        1, 1),
    ("e_main_2",   "e_vp2_approach",  0, 0),   # eastbound -> VP-B
    ("e_main_3r",  "e_main_2r",       0, 0),
    ("e_main_3r",  "e_main_2r",       1, 1),
    ("e_main_3r",  "e_vp2_approach",  0, 0),   # westbound -> VP-B
    ("e_vp2_exit", "e_main_3",        0, 0),   # exit VP-B -> east
    ("e_vp2_exit", "e_main_2r",       0, 0),   # exit VP-B -> west

    # ── VP-Alpha internal chain ───────────────────────────────────────────────
    ("e_vp1_approach",      "e_vp1_wait",          0, 0),
    ("e_vp1_wait",          "e_vp1_park",          0, 0),
    ("e_vp1_park",          "e_vp1_rental",        0, 0),
    ("e_vp1_rental",        "e_vp1_exit_internal", 0, 0),
    ("e_vp1_exit_internal", "e_vp1_exit",          0, 0),

    # ── VP-Beta internal chain ────────────────────────────────────────────────
    ("e_vp2_approach",      "e_vp2_wait",          0, 0),
    ("e_vp2_wait",          "e_vp2_park",          0, 0),
    ("e_vp2_park",          "e_vp2_rental",        0, 0),
    ("e_vp2_rental",        "e_vp2_exit_internal", 0, 0),
    ("e_vp2_exit_internal", "e_vp2_exit",          0, 0),

    # ── eVTOL flight path connections (segmented along road) ──────────────────
    # Eastbound: A -> sky_a -> sky_1 -> sky_m -> sky_2 -> sky_b -> B
    ("e_takeoff_a",   "e_cruise_ab_1", 0, 0),
    ("e_cruise_ab_1", "e_cruise_ab_2", 0, 0),
    ("e_cruise_ab_2", "e_cruise_ab_3", 0, 0),
    ("e_cruise_ab_3", "e_cruise_ab_4", 0, 0),
    ("e_cruise_ab_4", "e_land_b",      0, 0),
    # Westbound: B -> sky_b -> sky_2 -> sky_m -> sky_1 -> sky_a -> A
    ("e_takeoff_b",   "e_cruise_ba_1", 0, 0),
    ("e_cruise_ba_1", "e_cruise_ba_2", 0, 0),
    ("e_cruise_ba_2", "e_cruise_ba_3", 0, 0),
    ("e_cruise_ba_3", "e_cruise_ba_4", 0, 0),
    ("e_cruise_ba_4", "e_land_a",      0, 0),
]


# ── XML writers ───────────────────────────────────────────────────────────────

def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  wrote {os.path.relpath(path)}")


def generate_nodes(out_dir: str = NETWORK_DIR) -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for node_id, (x, y) in NODES.items():
        lines.append(f'    <node id="{node_id}" x="{x}" y="{y}" type="priority"/>')
    lines.append("</nodes>")
    _write(os.path.join(out_dir, "nodes.nod.xml"), "\n".join(lines))


def generate_edges(out_dir: str = NETWORK_DIR) -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for (eid, frm, to, lanes, speed, prio) in EDGES:
        lines.append(
            f'    <edge id="{eid}" from="{frm}" to="{to}" '
            f'numLanes="{lanes}" speed="{speed}" priority="{prio}"/>'
        )
    lines.append("</edges>")
    _write(os.path.join(out_dir, "edges.edg.xml"), "\n".join(lines))


def generate_connections(out_dir: str = NETWORK_DIR) -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    for (frm, to, fl, tl) in CONNECTIONS:
        lines.append(
            f'    <connection from="{frm}" to="{to}" '
            f'fromLane="{fl}" toLane="{tl}"/>'
        )
    lines.append("</connections>")
    _write(os.path.join(out_dir, "connections.con.xml"), "\n".join(lines))


def generate_additionals(out_dir: str = NETWORK_DIR) -> None:
    """
    Parking areas and bus stops (waiting areas).
    Parking area on e_vpX_park (40 m edge).
    """
    cap = MAX_PARKING_SPACES
    content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <additional>

            <!-- Vertiport Alpha -->

            <busStop id="bs_vp1_wait"
                     lane="e_vp1_wait_0"
                     startPos="2" endPos="18"
                     friendlyPos="true"
                     name="VP-Alpha Waiting Area"/>

            <parkingArea id="pa_vp1"
                         lane="e_vp1_park_0"
                         startPos="2" endPos="38"
                         roadsideCapacity="{cap}"
                         friendlyPos="true"
                         name="VP-Alpha Parking Lot"/>

            <!-- Vertiport Beta -->

            <busStop id="bs_vp2_wait"
                     lane="e_vp2_wait_0"
                     startPos="2" endPos="18"
                     friendlyPos="true"
                     name="VP-Beta Waiting Area"/>

            <parkingArea id="pa_vp2"
                         lane="e_vp2_park_0"
                         startPos="2" endPos="38"
                         roadsideCapacity="{cap}"
                         friendlyPos="true"
                         name="VP-Beta Parking Lot"/>

        </additional>
        """)
    _write(os.path.join(out_dir, "additionals.add.xml"), content)


def generate_routes(out_dir: str = NETWORK_DIR) -> None:
    """
    Defines:
      - vTypes for passenger cars and rental cars
      - Named routes used by TraCI-injected vehicles
      - Background traffic flows (constant stream on main road)
    """
    content = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <routes>

            <!-- Vehicle types -->

            <vType id="passenger"   vClass="passenger" length="4.5"
                   accel="2.6" decel="4.5" maxSpeed="50" color="0.2,0.6,1.0"/>

            <vType id="rental_car"  vClass="passenger" length="4.5"
                   accel="2.6" decel="4.5" maxSpeed="50" color="1.0,0.6,0.0"
                   personCapacity="4"/>

            <!-- eVTOL: aircraft shape, cyan, large so it is visible at sim scale -->
            <vType id="evtol" vClass="passenger" length="18" width="18"
                   accel="6" decel="8" maxSpeed="45"
                   color="0,204,255"
                   guiShape="aircraft"
                   personCapacity="4"
                   lcStrategic="0" lcCooperative="0"/>

            <!-- Background traffic routes -->

            <route id="bg_east"
                   edges="e_main_0 e_main_1 e_main_2 e_main_3"/>
            <route id="bg_west"
                   edges="e_main_3r e_main_2r e_main_1r e_main_0r"/>

            <!-- Constant background flows (120 veh/h each direction) -->
            <flow id="bg_flow_east" route="bg_east"    type="passenger"
                  begin="0" end="7200" vehsPerHour="120"
                  departLane="random" departSpeed="random"/>
            <flow id="bg_flow_west" route="bg_west"    type="passenger"
                  begin="0" end="7200" vehsPerHour="120"
                  departLane="random" departSpeed="random"/>

            <!-- Visitor vehicle routes (TraCI adds vehicles dynamically) -->

            <!-- VP-Alpha visitors -->
            <route id="visitor_from_west_vp1"
                   edges="e_main_0
                          e_vp1_approach e_vp1_wait e_vp1_park
                          e_vp1_rental e_vp1_exit_internal e_vp1_exit
                          e_main_1 e_main_2 e_main_3"/>

            <route id="visitor_from_east_vp1"
                   edges="e_main_3r e_main_2r e_main_1r
                          e_vp1_approach e_vp1_wait e_vp1_park
                          e_vp1_rental e_vp1_exit_internal e_vp1_exit
                          e_main_0r"/>

            <!-- VP-Beta visitors -->
            <route id="visitor_from_west_vp2"
                   edges="e_main_0 e_main_1 e_main_2
                          e_vp2_approach e_vp2_wait e_vp2_park
                          e_vp2_rental e_vp2_exit_internal e_vp2_exit
                          e_main_3"/>

            <route id="visitor_from_east_vp2"
                   edges="e_main_3r
                          e_vp2_approach e_vp2_wait e_vp2_park
                          e_vp2_rental e_vp2_exit_internal e_vp2_exit
                          e_main_2r e_main_1r e_main_0r"/>

            <!-- Rental car routes (TraCI adds vehicles on eVTOL arrival) -->

            <!-- VP-Alpha rentals -->
            <route id="rental_vp1_east"
                   edges="e_vp1_rental e_vp1_exit_internal e_vp1_exit
                          e_main_1 e_main_2 e_main_3"/>

            <route id="rental_vp1_west"
                   edges="e_vp1_rental e_vp1_exit_internal e_vp1_exit
                          e_main_0r"/>

            <!-- VP-Beta rentals -->
            <route id="rental_vp2_east"
                   edges="e_vp2_rental e_vp2_exit_internal e_vp2_exit
                          e_main_3"/>

            <route id="rental_vp2_west"
                   edges="e_vp2_rental e_vp2_exit_internal e_vp2_exit
                          e_main_2r e_main_1r e_main_0r"/>

            <!-- eVTOL flight routes (follow road corridor) -->
            <route id="evtol_vpa_to_vpb"
                   edges="e_takeoff_a e_cruise_ab_1 e_cruise_ab_2 e_cruise_ab_3 e_cruise_ab_4 e_land_b"/>

            <route id="evtol_vpb_to_vpa"
                   edges="e_takeoff_b e_cruise_ba_1 e_cruise_ba_2 e_cruise_ba_3 e_cruise_ba_4 e_land_a"/>

        </routes>
        """)
    _write(os.path.join(out_dir, "routes.rou.xml"), content)


def generate_all(out_dir: str = NETWORK_DIR) -> None:
    """Write all network source XML files to out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    print(f"Generating network source files in '{out_dir}' ...")
    generate_nodes(out_dir)
    generate_edges(out_dir)
    generate_connections(out_dir)
    generate_additionals(out_dir)
    generate_routes(out_dir)
    print("Done.")


if __name__ == "__main__":
    generate_all()
