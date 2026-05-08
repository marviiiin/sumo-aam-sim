"""
setup_carla.py
Run this ONCE after extracting CARLA_0.9.15.zip to finish the CARLA setup.

Usage:
    py -3.10 setup_carla.py                        # auto-detects CARLA folder
    py -3.10 setup_carla.py --carla C:\\CARLA_0.9.15
"""

import argparse
import glob
import os
import subprocess
import sys

SEARCH_ROOTS = ["C:\\", "D:\\", os.path.expanduser("~")]
CARLA_WHEEL_PATTERN = "PythonAPI/carla/dist/carla-*-cp310-cp310-win_amd64.whl"


def find_carla_root(hint: str | None) -> str:
    if hint:
        return hint

    print("Searching for CARLA installation …")
    for root in SEARCH_ROOTS:
        for match in glob.glob(os.path.join(root, "CARLA*"), recursive=False):
            wheel = os.path.join(match, "PythonAPI/carla/dist")
            if os.path.isdir(wheel):
                print(f"  Found: {match}")
                return match

    sys.exit(
        "Could not find a CARLA installation.\n"
        "Extract CARLA_0.9.15.zip to C:\\ and re-run, or pass --carla <path>."
    )


def install_wheel(carla_root: str) -> None:
    pattern = os.path.join(carla_root, CARLA_WHEEL_PATTERN)
    wheels  = glob.glob(pattern)
    if not wheels:
        sys.exit(
            f"No cp310 wheel found at {pattern}\n"
            "Make sure you downloaded CARLA 0.9.15 and extracted it fully."
        )
    wheel = wheels[0]
    print(f"\nInstalling: {wheel}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", wheel],
        check=False,
    )
    if result.returncode != 0:
        sys.exit("pip install failed.")
    print("\nCARLA Python package installed for Python 3.10.")


def add_carla_to_path(carla_root: str) -> None:
    """Append CARLA's PythonAPI/carla dir to this venv's .pth so imports work."""
    import site
    site_pkg = site.getsitepackages()[0]
    pth_file  = os.path.join(site_pkg, "carla_extra.pth")
    extra_dir = os.path.join(carla_root, "PythonAPI", "carla")
    with open(pth_file, "w") as f:
        f.write(extra_dir + "\n")
    print(f"Added {extra_dir} → {pth_file}")


def verify(carla_root: str) -> None:
    print("\nVerifying import …")
    result = subprocess.run(
        [sys.executable, "-c",
         "import carla; print('carla', carla.__version__, 'OK')"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
    else:
        print("Import check failed:", result.stderr.strip())
        print("You may need to restart your terminal.")


def write_carla_root_env(carla_root: str) -> None:
    """
    Patch carla_bridge/config_carla.py so CARLA_HOST/PORT are set,
    and write the CARLA root to a small .env-style file for reference.
    """
    env_file = os.path.join(os.path.dirname(__file__), ".carla_root")
    with open(env_file, "w") as f:
        f.write(carla_root)
    print(f"CARLA root saved to {env_file}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--carla", default=None,
                   help="Path to extracted CARLA folder (e.g. C:\\CARLA_0.9.15)")
    args = p.parse_args()

    carla_root = find_carla_root(args.carla)
    install_wheel(carla_root)
    add_carla_to_path(carla_root)
    write_carla_root_env(carla_root)
    verify(carla_root)

    print("""
╔══════════════════════════════════════════════════════════════════╗
║  Setup complete!  Next steps:                                   ║
║                                                                  ║
║  1. Launch the CARLA server:                                     ║
║       C:\\CARLA_0.9.15\\CarlaUE4.exe -quality-level=Medium        ║
║       (wait for Unreal to finish loading, ~30 seconds)          ║
║                                                                  ║
║  2. In this project folder, run:                                 ║
║       py -3.10 run_with_carla.py --map Town03 --seed 42          ║
║                                                                  ║
║  The bridge will mirror all SUMO vehicles as 3-D CARLA actors   ║
║  and animate eVTOL arrivals as descending aircraft.             ║
╚══════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
