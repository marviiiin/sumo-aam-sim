# airsim_bridge package
#
# The pip-published `airsim` wheel is broken on Python >=3.12 (it pulls in
# tornado 4.x which fails to import).  If the user has the Cosys-AirSim fork
# checked out (or a custom plugin PythonClient folder), we re-export that
# under the name `airsim` so every downstream `import airsim` still works.
#
# Order of preference:
#   1. Real `airsim` package, if importable.
#   2. Cosys-AirSim's `cosysairsim` client, aliased to `airsim`.
#   3. Nothing — the bridge will raise in connect() if neither is available.
import os
import sys


def _install_airsim_alias() -> None:
    try:
        import airsim   # noqa: F401
        return                           # real airsim works, nothing to do
    except Exception:
        pass

    candidates = [
        r"C:\Users\okmar\Cosys-AirSim\PythonClient",
        os.path.join(os.path.expanduser("~"), "Cosys-AirSim", "PythonClient"),
    ]
    for p in candidates:
        if os.path.isdir(os.path.join(p, "cosysairsim")):
            if p not in sys.path:
                sys.path.insert(0, p)
            break
    else:
        return                           # no shim available

    try:
        import cosysairsim as _cs
    except Exception:
        return

    # Alias: map cosysairsim → airsim, plus re-export renamed symbols.
    sys.modules["airsim"] = _cs
    if not hasattr(_cs, "to_quaternion") and hasattr(_cs, "euler_to_quaternion"):
        _cs.to_quaternion = _cs.euler_to_quaternion


_install_airsim_alias()

from .bridge import AirSimBridge  # noqa: E402
