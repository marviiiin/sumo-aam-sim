"""
coordinate_map.py — Bidirectional WGS84 ↔ AirSim NED transform for the bridge.

Pure Python, no airsim / traci dependency (unit-testable in isolation).

Convention
----------
AirSim NED (relative to UE5 origin / CesiumGeoreference anchor):
    x =  north (metres, +N)
    y =  east  (metres, +E)
    z =  down  (metres, +D — negative means altitude above ground)

Accuracy
--------
Equirectangular projection with the vertiport anchor near the Cesium origin
has sub-metre error for distances < 20 km (Tampa → USF is ~13 km).  Accurate
enough for simulation; swap to pyproj if you need survey-grade precision.
"""

import math

from .config_airsim import (
    CESIUM_ORIGIN_LAT,
    CESIUM_ORIGIN_LON,
    VERTIPORT_GPS,
)

# Mean Earth radius (metres) for equirectangular projection
_R_EARTH_M = 6_371_000.0


def wgs84_to_ned(lat: float, lon: float,
                 ref_lat: float = CESIUM_ORIGIN_LAT,
                 ref_lon: float = CESIUM_ORIGIN_LON) -> tuple[float, float]:
    """
    Convert (lat, lon) to AirSim (north_m, east_m) from the Cesium origin.

    Returns
    -------
    (n, e) : tuple of metres   (AirSim x = n, y = e)
    """
    dlat = math.radians(lat - ref_lat)
    dlon = math.radians(lon - ref_lon)
    mean_lat = math.radians((lat + ref_lat) / 2.0)

    north_m = _R_EARTH_M * dlat
    east_m  = _R_EARTH_M * dlon * math.cos(mean_lat)
    return north_m, east_m


def ned_to_wgs84(n: float, e: float,
                 ref_lat: float = CESIUM_ORIGIN_LAT,
                 ref_lon: float = CESIUM_ORIGIN_LON) -> tuple[float, float]:
    """Inverse of wgs84_to_ned.  Useful for debugging / logs."""
    lat = ref_lat + math.degrees(n / _R_EARTH_M)
    mean_lat = math.radians((lat + ref_lat) / 2.0)
    lon = ref_lon + math.degrees(e / (_R_EARTH_M * math.cos(mean_lat)))
    return lat, lon


def vertiport_ned(vp_id: str) -> tuple[float, float]:
    """
    Return AirSim (n, e) in metres for the named vertiport.
    Raises KeyError if vp_id is not in config_airsim.VERTIPORT_GPS.
    """
    lat, lon = VERTIPORT_GPS[vp_id]
    return wgs84_to_ned(lat, lon)


def bearing_deg(from_vp: str, to_vp: str) -> float:
    """Compass bearing from one vertiport to another (0°=N, 90°=E)."""
    n1, e1 = vertiport_ned(from_vp)
    n2, e2 = vertiport_ned(to_vp)
    dn, de = n2 - n1, e2 - e1
    return (math.degrees(math.atan2(de, dn))) % 360.0


def distance_m(from_vp: str, to_vp: str) -> float:
    """Straight-line distance between two vertiports in metres."""
    n1, e1 = vertiport_ned(from_vp)
    n2, e2 = vertiport_ned(to_vp)
    return math.hypot(n2 - n1, e2 - e1)
