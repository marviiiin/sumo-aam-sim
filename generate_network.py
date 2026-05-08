"""
generate_network.py
Run this script ONCE before your first simulation to build two_vertiport.net.xml.

Usage:
    python generate_network.py [--gui]

    --gui   Open the generated network in netedit for inspection.

Steps performed:
    1. Generate network source XML files (nodes, edges, connections,
       additionals, routes) via vertiport_generator.py.
    2. Call SUMO's netconvert to compile them into a .net.xml file.
    3. Optionally open netedit for visual inspection.
"""

import os
import sys
import subprocess
import argparse

from config import NETWORK_DIR, NET_XML_PATH, NETCONVERT_BINARY, SUMO_HOME
from vertiport_generator import generate_all


def run_netconvert() -> None:
    nod = os.path.join(NETWORK_DIR, "nodes.nod.xml")
    edg = os.path.join(NETWORK_DIR, "edges.edg.xml")
    con = os.path.join(NETWORK_DIR, "connections.con.xml")

    cmd = [
        NETCONVERT_BINARY,
        "--node-files",       nod,
        "--edge-files",       edg,
        "--connection-files", con,
        "--output-file",      NET_XML_PATH,
        "--no-internal-links",         "false",
        "--junctions.corner-detail",   "4",
        "--offset.disable-normalization", "true",
        "--geometry.remove",           "false",
        "--verbose",
    ]

    print("\nRunning netconvert …")
    print("  " + " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print("ERROR: netconvert failed.\n")
        print(result.stderr)
        sys.exit(1)

    print(f"\nNetwork written to: {NET_XML_PATH}")


def open_netedit(net_path: str) -> None:
    _ext = ".exe" if sys.platform == "win32" else ""
    netedit = os.path.join(SUMO_HOME, "bin", f"netedit{_ext}")
    if not os.path.isfile(netedit):
        print(f"netedit not found at {netedit}. Skipping GUI.")
        return
    print("Opening netedit …")
    subprocess.Popen([netedit, "--sumo-net-file", net_path])


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SUMO network for AAMSim.")
    parser.add_argument("--gui", action="store_true",
                        help="Open the generated network in netedit")
    args = parser.parse_args()

    # Step 1 – write source XMLs
    generate_all(NETWORK_DIR)

    # Step 2 – compile to net.xml
    run_netconvert()

    # Step 3 – optional GUI inspection
    if args.gui:
        open_netedit(NET_XML_PATH)

    print("\nAll done. You can now run:  python simulation.py")


if __name__ == "__main__":
    main()
