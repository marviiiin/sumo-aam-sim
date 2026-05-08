"""
generate_town10hd_net.py — Merge town10hd.net.xml with vertiport + eVTOL infrastructure.

The town10hd.net.xml was converted from CARLA's OpenDRIVE export.  This script
adds vertiport sub-networks (parking, waiting, rental, approach/exit) and eVTOL
sky-path edges, then runs netconvert to produce a merged network.

Coordinate system (town10hd):
    SUMO_x = CARLA_x        (no flip, no scale)
    SUMO_y = -CARLA_y        (y-flipped)

Key town10hd junctions used:
    189  (-47.06, -22.85)  — VP-Alpha attachment point (main E-W road)
    841  ( 41.91, -30.50)  — VP-Beta  attachment point (main E-W road)

Main E-W road edges (south road):
    Eastbound: -18 → -19 → -20 → -21
    Westbound:  21 →  20 →  19 →  18

Usage:
    python generate_town10hd_net.py
"""

import os
import sys
import subprocess
import textwrap

from config import NETWORK_DIR, NETCONVERT_BINARY, MAX_PARKING_SPACES

# ── Paths ──────────────────────────────────────────────────────────────────────
TOWN10HD_NET   = os.path.join(NETWORK_DIR, "town10hd.net.xml")
MERGED_NET     = os.path.join(NETWORK_DIR, "town10hd_vp.net.xml")
VP_NODES_FILE  = os.path.join(NETWORK_DIR, "vp_patch_nodes.nod.xml")
VP_EDGES_FILE  = os.path.join(NETWORK_DIR, "vp_patch_edges.edg.xml")
VP_CONN_FILE   = os.path.join(NETWORK_DIR, "vp_patch_connections.con.xml")

# ── Existing town10hd junction IDs ─────────────────────────────────────────────
JCT_VPA = "189"    # VP-Alpha attaches here
JCT_VPB = "841"    # VP-Beta  attaches here

# ── New node coordinates (SUMO frame: y = -CARLA_y) ───────────────────────────
# VP-Alpha sub-network (south of junction 189 in CARLA = more positive y in SUMO)
# Going "south" in CARLA from junction 189 (-47, -23):
#   CARLA south → SUMO +y direction
NODES = {
    # VP-Alpha vertiport (west of the existing N-S road at x≈-47)
    "n_vpa_entry":  (-55, -16),
    "n_vpa_wait":   (-55,  -6),
    "n_vpa_park":   (-55,  16),
    "n_vpa_rental": (-48,  16),
    "n_vpa_exit":   (-48,  -6),

    # VP-Beta vertiport (west of junction 841)
    "n_vpb_entry":  ( 34, -24),
    "n_vpb_wait":   ( 34, -14),
    "n_vpb_park":   ( 34,   8),
    "n_vpb_rental": ( 42,   8),
    "n_vpb_exit":   ( 42, -14),

    # Sky-path nodes (along main road corridor, offset 3-4 m in y)
    "n_sky_a": (-47, -19),
    "n_sky_1": (-20, -21),
    "n_sky_m": (  0, -24),
    "n_sky_2": ( 20, -27),
    "n_sky_b": ( 42, -27),
}

# ── New edges ──────────────────────────────────────────────────────────────────
# (id, from, to, numLanes, speed_m_s, priority)
EDGES = [
    # -- VP-Alpha internal -------------------------------------------------------
    ("e_vp1_approach",      JCT_VPA,        "n_vpa_entry",  1,  5.56, 5),
    ("e_vp1_wait",          "n_vpa_entry",  "n_vpa_wait",   1,  4.17, 3),
    ("e_vp1_park",          "n_vpa_wait",   "n_vpa_park",   1,  4.17, 3),
    ("e_vp1_rental",        "n_vpa_park",   "n_vpa_rental", 1,  4.17, 3),
    ("e_vp1_exit_internal", "n_vpa_rental", "n_vpa_exit",   1,  4.17, 3),
    ("e_vp1_exit",          "n_vpa_exit",   JCT_VPA,        1,  5.56, 5),

    # -- VP-Beta internal --------------------------------------------------------
    ("e_vp2_approach",      JCT_VPB,        "n_vpb_entry",  1,  5.56, 5),
    ("e_vp2_wait",          "n_vpb_entry",  "n_vpb_wait",   1,  4.17, 3),
    ("e_vp2_park",          "n_vpb_wait",   "n_vpb_park",   1,  4.17, 3),
    ("e_vp2_rental",        "n_vpb_park",   "n_vpb_rental", 1,  4.17, 3),
    ("e_vp2_exit_internal", "n_vpb_rental", "n_vpb_exit",   1,  4.17, 3),
    ("e_vp2_exit",          "n_vpb_exit",   JCT_VPB,        1,  5.56, 5),

    # -- eVTOL sky-path (A → B eastbound) ----------------------------------------
    ("e_takeoff_a",   "n_vpa_park", "n_sky_a",    1, 20.0, 9),
    ("e_cruise_ab_1", "n_sky_a",    "n_sky_1",    1, 40.0, 9),
    ("e_cruise_ab_2", "n_sky_1",    "n_sky_m",    1, 40.0, 9),
    ("e_cruise_ab_3", "n_sky_m",    "n_sky_2",    1, 40.0, 9),
    ("e_cruise_ab_4", "n_sky_2",    "n_sky_b",    1, 40.0, 9),
    ("e_land_b",      "n_sky_b",    "n_vpb_park", 1, 20.0, 9),

    # -- eVTOL sky-path (B → A westbound) ----------------------------------------
    ("e_takeoff_b",   "n_vpb_park", "n_sky_b",    1, 20.0, 9),
    ("e_cruise_ba_1", "n_sky_b",    "n_sky_2",    1, 40.0, 9),
    ("e_cruise_ba_2", "n_sky_2",    "n_sky_m",    1, 40.0, 9),
    ("e_cruise_ba_3", "n_sky_m",    "n_sky_1",    1, 40.0, 9),
    ("e_cruise_ba_4", "n_sky_1",    "n_sky_a",    1, 40.0, 9),
    ("e_land_a",      "n_sky_a",    "n_vpa_park", 1, 20.0, 9),
]

# ── Connections ────────────────────────────────────────────────────────────────
# (from_edge, to_edge, fromLane, toLane)
CONNECTIONS = [
    # -- Junction 189: main road ↔ VP-Alpha ----------------------------------
    # Eastbound turn into VP-Alpha
    ("-19",         "e_vp1_approach",  0, 0),
    # Westbound turn into VP-Alpha
    ("20",          "e_vp1_approach",  0, 0),
    # Exit VP-Alpha → continue east
    ("e_vp1_exit",  "-20",             0, 0),
    # Exit VP-Alpha → continue west
    ("e_vp1_exit",  "19",              0, 0),

    # -- Junction 841: main road ↔ VP-Beta -----------------------------------
    ("-20",         "e_vp2_approach",  0, 0),
    ("21",          "e_vp2_approach",  0, 0),
    ("e_vp2_exit",  "-21",             0, 0),
    ("e_vp2_exit",  "20",              0, 0),

    # -- VP-Alpha internal chain ----------------------------------------------
    ("e_vp1_approach",      "e_vp1_wait",          0, 0),
    ("e_vp1_wait",          "e_vp1_park",          0, 0),
    ("e_vp1_park",          "e_vp1_rental",        0, 0),
    ("e_vp1_park",          "e_takeoff_a",         0, 0),  # eVTOL takeoff
    ("e_vp1_rental",        "e_vp1_exit_internal", 0, 0),
    ("e_vp1_exit_internal", "e_vp1_exit",          0, 0),
    ("e_land_a",            "e_vp1_rental",        0, 0),  # eVTOL landing

    # -- VP-Beta internal chain -----------------------------------------------
    ("e_vp2_approach",      "e_vp2_wait",          0, 0),
    ("e_vp2_wait",          "e_vp2_park",          0, 0),
    ("e_vp2_park",          "e_vp2_rental",        0, 0),
    ("e_vp2_park",          "e_takeoff_b",         0, 0),
    ("e_vp2_rental",        "e_vp2_exit_internal", 0, 0),
    ("e_vp2_exit_internal", "e_vp2_exit",          0, 0),
    ("e_land_b",            "e_vp2_rental",        0, 0),

    # -- eVTOL sky-path chain (A → B) ----------------------------------------
    ("e_takeoff_a",   "e_cruise_ab_1", 0, 0),
    ("e_cruise_ab_1", "e_cruise_ab_2", 0, 0),
    ("e_cruise_ab_2", "e_cruise_ab_3", 0, 0),
    ("e_cruise_ab_3", "e_cruise_ab_4", 0, 0),
    ("e_cruise_ab_4", "e_land_b",      0, 0),

    # -- eVTOL sky-path chain (B → A) ----------------------------------------
    ("e_takeoff_b",   "e_cruise_ba_1", 0, 0),
    ("e_cruise_ba_1", "e_cruise_ba_2", 0, 0),
    ("e_cruise_ba_2", "e_cruise_ba_3", 0, 0),
    ("e_cruise_ba_3", "e_cruise_ba_4", 0, 0),
    ("e_cruise_ba_4", "e_land_a",      0, 0),
]


# ── XML generators ─────────────────────────────────────────────────────────────

def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  wrote {os.path.relpath(path)}")


def generate_node_patch() -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<nodes>"]
    for nid, (x, y) in NODES.items():
        lines.append(f'    <node id="{nid}" x="{x}" y="{y}" type="priority"/>')
    lines.append("</nodes>")
    _write(VP_NODES_FILE, "\n".join(lines))


def generate_edge_patch() -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<edges>"]
    for eid, frm, to, lanes, speed, prio in EDGES:
        lines.append(
            f'    <edge id="{eid}" from="{frm}" to="{to}" '
            f'numLanes="{lanes}" speed="{speed}" priority="{prio}"/>'
        )
    lines.append("</edges>")
    _write(VP_EDGES_FILE, "\n".join(lines))


def generate_connection_patch() -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<connections>"]
    for frm, to, fl, tl in CONNECTIONS:
        lines.append(
            f'    <connection from="{frm}" to="{to}" '
            f'fromLane="{fl}" toLane="{tl}"/>'
        )
    lines.append("</connections>")
    _write(VP_CONN_FILE, "\n".join(lines))


def generate_additionals() -> None:
    cap = MAX_PARKING_SPACES
    content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <additional>

            <!-- Vertiport Alpha -->

            <busStop id="bs_vp1_wait"
                     lane="e_vp1_wait_0"
                     startPos="1" endPos="9"
                     friendlyPos="true"
                     name="VP-Alpha Waiting Area"/>

            <parkingArea id="pa_vp1"
                         lane="e_vp1_park_0"
                         startPos="2" endPos="20"
                         roadsideCapacity="{cap}"
                         friendlyPos="true"
                         name="VP-Alpha Parking Lot"/>

            <!-- Vertiport Beta -->

            <busStop id="bs_vp2_wait"
                     lane="e_vp2_wait_0"
                     startPos="1" endPos="9"
                     friendlyPos="true"
                     name="VP-Beta Waiting Area"/>

            <parkingArea id="pa_vp2"
                         lane="e_vp2_park_0"
                         startPos="2" endPos="20"
                         roadsideCapacity="{cap}"
                         friendlyPos="true"
                         name="VP-Beta Parking Lot"/>

        </additional>
    """)
    _write(os.path.join(NETWORK_DIR, "additionals.add.xml"), content)


def generate_routes() -> None:
    content = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <routes>

            <!-- Vehicle types -->

            <vType id="passenger"   vClass="passenger" length="4.5"
                   accel="2.6" decel="4.5" maxSpeed="50" color="0.2,0.6,1.0"/>

            <vType id="rental_car"  vClass="passenger" length="4.5"
                   accel="2.6" decel="4.5" maxSpeed="50" color="1.0,0.6,0.0"
                   personCapacity="4"/>

            <!-- eVTOL: aircraft shape, cyan, large so it is visible -->
            <vType id="evtol" vClass="passenger" length="18" width="18"
                   accel="6" decel="8" maxSpeed="45"
                   color="0,204,255"
                   guiShape="aircraft"
                   personCapacity="4"
                   lcStrategic="0" lcCooperative="0"/>

            <!-- ============================================================
                 Background traffic on Town10HD main E-W road
                 Eastbound: -18 -> -19 -> -20 -> -21
                 Westbound:  21 ->  20 ->  19 ->  18
                 ============================================================ -->

            <route id="bg_east" edges="-18 -19 -20 -21"/>
            <route id="bg_west" edges="21 20 19 18"/>

            <flow id="bg_flow_east" route="bg_east" type="passenger"
                  begin="0" end="7200" vehsPerHour="120"
                  departLane="random" departSpeed="random"/>
            <flow id="bg_flow_west" route="bg_west" type="passenger"
                  begin="0" end="7200" vehsPerHour="120"
                  departLane="random" departSpeed="random"/>

            <!-- ============================================================
                 Visitor routes — VP-Alpha (junction 189)
                 ============================================================ -->

            <route id="visitor_from_west_vp1"
                   edges="-18 -19
                          e_vp1_approach e_vp1_wait e_vp1_park
                          e_vp1_rental e_vp1_exit_internal e_vp1_exit
                          -20 -21"/>

            <route id="visitor_from_east_vp1"
                   edges="21 20
                          e_vp1_approach e_vp1_wait e_vp1_park
                          e_vp1_rental e_vp1_exit_internal e_vp1_exit
                          19 18"/>

            <!-- ============================================================
                 Visitor routes — VP-Beta (junction 841)
                 ============================================================ -->

            <route id="visitor_from_west_vp2"
                   edges="-18 -19 -20
                          e_vp2_approach e_vp2_wait e_vp2_park
                          e_vp2_rental e_vp2_exit_internal e_vp2_exit
                          -21"/>

            <route id="visitor_from_east_vp2"
                   edges="21
                          e_vp2_approach e_vp2_wait e_vp2_park
                          e_vp2_rental e_vp2_exit_internal e_vp2_exit
                          20 19 18"/>

            <!-- ============================================================
                 Rental car routes
                 ============================================================ -->

            <route id="rental_vp1_east"
                   edges="e_vp1_rental e_vp1_exit_internal e_vp1_exit -20 -21"/>

            <route id="rental_vp1_west"
                   edges="e_vp1_rental e_vp1_exit_internal e_vp1_exit 19 18"/>

            <route id="rental_vp2_east"
                   edges="e_vp2_rental e_vp2_exit_internal e_vp2_exit -21"/>

            <route id="rental_vp2_west"
                   edges="e_vp2_rental e_vp2_exit_internal e_vp2_exit 20 19 18"/>

            <!-- ============================================================
                 eVTOL flight routes (sky path along road corridor)
                 ============================================================ -->

            <route id="evtol_vpa_to_vpb"
                   edges="e_takeoff_a e_cruise_ab_1 e_cruise_ab_2 e_cruise_ab_3 e_cruise_ab_4 e_land_b"/>

            <route id="evtol_vpb_to_vpa"
                   edges="e_takeoff_b e_cruise_ba_1 e_cruise_ba_2 e_cruise_ba_3 e_cruise_ba_4 e_land_a"/>

        </routes>
    """)
    _write(os.path.join(NETWORK_DIR, "routes.rou.xml"), content)


def generate_sumocfg() -> None:
    content = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!--
            sumo_aam_sim.sumocfg — SUMO config for Town10HD + vertiport scenario.
        -->
        <configuration>

            <input>
                <net-file          value="network/town10hd_vp.net.xml"/>
                <additional-files  value="network/additionals.add.xml"/>
                <route-files       value="network/routes.rou.xml"/>
            </input>

            <time>
                <begin       value="0"/>
                <end         value="7200"/>
                <step-length value="1.0"/>
            </time>

            <processing>
                <time-to-teleport value="-1"/>
                <waiting-time-memory value="1000"/>
            </processing>

            <report>
                <verbose      value="false"/>
                <no-step-log  value="true"/>
            </report>

        </configuration>
    """)
    _write(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "sumo_aam_sim.sumocfg"), content)


# ── Network merge ──────────────────────────────────────────────────────────────

def merge_network() -> None:
    if not os.path.isfile(TOWN10HD_NET):
        print(f"ERROR: {TOWN10HD_NET} not found. "
              "Export it from CARLA first (map.to_opendrive -> netconvert).")
        sys.exit(1)

    cmd = [
        NETCONVERT_BINARY,
        "--sumo-net-file",                TOWN10HD_NET,
        "--node-files",                   VP_NODES_FILE,
        "--edge-files",                   VP_EDGES_FILE,
        "--connection-files",             VP_CONN_FILE,
        "--output-file",                  MERGED_NET,
        "--offset.disable-normalization", "true",
        "--no-turnarounds",               "true",
        "--verbose",
    ]

    print("\nRunning netconvert to merge town10hd + vertiport patches ...")
    print("  " + " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print("ERROR: netconvert merge failed.\n")
        print(result.stderr)
        sys.exit(1)

    print(f"\nMerged network written to: {MERGED_NET}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    os.makedirs(NETWORK_DIR, exist_ok=True)

    print("Generating vertiport patch files ...")
    generate_node_patch()
    generate_edge_patch()
    generate_connection_patch()

    print("\nGenerating additionals + routes for Town10HD network ...")
    generate_additionals()
    generate_routes()
    generate_sumocfg()

    merge_network()

    print("\nAll done. You can now run:  python simulation.py")


if __name__ == "__main__":
    main()
