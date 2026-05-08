"""
mock_client.py — Stand-in AirSim client used by run_with_airsim.py --dry-run.

Lets us prove the bridge plumbing (SUMO → queue_departure → FlightController
state machine → landed events, plus VehicleMirror spawn/move/destroy) without
needing a running UE5 + AirSim RPC server.

Every RPC method simply logs (optionally) and returns a small fake result
shaped like AirSim's real return values.
"""

import math
import sys
import types
from dataclasses import dataclass


def install_fake_airsim_module() -> None:
    """
    Register a synthetic ``airsim`` top-level module in sys.modules so that
    ``import airsim`` inside flight_controller / flight_fleet / vehicle_mirror
    succeeds without the real package being installed.  Only the small handful
    of symbols we actually reference need to be defined.
    """
    if "airsim" in sys.modules:
        return

    mod = types.ModuleType("airsim")

    class Vector3r:
        def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
            self.x_val, self.y_val, self.z_val = float(x), float(y), float(z)

    class Quaternionr:
        def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0, w: float = 1.0):
            self.x_val, self.y_val, self.z_val, self.w_val = x, y, z, w

    class Pose:
        def __init__(self, position: Vector3r = None, orientation: Quaternionr = None):
            self.position    = position    or Vector3r()
            self.orientation = orientation or Quaternionr()

    class DrivetrainType:
        ForwardOnly = 0
        MaxDegreeOfFreedom = 1

    class YawMode:
        def __init__(self, is_rate: bool = True, yaw_or_rate: float = 0.0):
            self.is_rate, self.yaw_or_rate = is_rate, yaw_or_rate

    def to_quaternion(roll: float, pitch: float, yaw: float) -> Quaternionr:
        cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
        cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
        cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
        return Quaternionr(
            x=sr * cp * cy - cr * sp * sy,
            y=cr * sp * cy + sr * cp * sy,
            z=cr * cp * sy - sr * sp * cy,
            w=cr * cp * cy + sr * sp * sy,
        )

    mod.Vector3r      = Vector3r
    mod.Quaternionr   = Quaternionr
    mod.Pose          = Pose
    mod.DrivetrainType = DrivetrainType
    mod.YawMode       = YawMode
    mod.to_quaternion = to_quaternion
    # Bridge.connect() calls `airsim.MultirotorClient(...)`. In dry-run we
    # swap in MockAirSimClient directly, but some code paths still reference
    # the class, so expose a stub too.
    mod.MultirotorClient = MockAirSimClient

    sys.modules["airsim"] = mod


@dataclass
class _FakeVec3:
    x_val: float = 0.0
    y_val: float = 0.0
    z_val: float = 0.0


@dataclass
class _FakeQuat:
    w_val: float = 1.0
    x_val: float = 0.0
    y_val: float = 0.0
    z_val: float = 0.0


class _FakePose:
    def __init__(self) -> None:
        self.position    = _FakeVec3()
        self.orientation = _FakeQuat()


class _FakeKinematics:
    def __init__(self) -> None:
        self.position          = _FakeVec3()
        self.linear_velocity   = _FakeVec3()


class _FakeMultirotorState:
    def __init__(self) -> None:
        self.kinematics_estimated = _FakeKinematics()


class MockAirSimClient:
    """
    Minimal stand-in for airsim.MultirotorClient.  Just enough surface for
    FlightFleet + FlightController + VehicleMirror to run through a full
    SUMO co-simulation in dry-run mode.
    """

    def __init__(self, ip: str = "", port: int = 0,
                 timeout_value: float = 0.0, verbose: bool = False,
                 **_: object) -> None:
        self._verbose = verbose
        self._poses: dict[str, _FakePose] = {}   # vehicle_name → pose
        self._objects: dict[str, _FakePose] = {} # object_name → pose
        self._targets: dict[str, tuple[float, float, float]] = {}  # per-vehicle NED goal

    # ── Connection / arm ──────────────────────────────────────────────────────
    def confirmConnection(self) -> None:
        if self._verbose:
            print("[MockAirSim] confirmConnection()")

    def enableApiControl(self, enable: bool, vehicle_name: str = "") -> None:
        if self._verbose:
            print(f"[MockAirSim] enableApiControl({enable}, {vehicle_name!r})")

    def armDisarm(self, arm: bool, vehicle_name: str = "") -> bool:
        if self._verbose:
            print(f"[MockAirSim] armDisarm({arm}, {vehicle_name!r})")
        return True

    # ── State ────────────────────────────────────────────────────────────────
    def getMultirotorState(self, vehicle_name: str = "") -> _FakeMultirotorState:
        pose = self._poses.setdefault(vehicle_name, _FakePose())
        st = _FakeMultirotorState()
        st.kinematics_estimated.position.x_val = pose.position.x_val
        st.kinematics_estimated.position.y_val = pose.position.y_val
        st.kinematics_estimated.position.z_val = pose.position.z_val
        # Pretend we've reached any goal we were commanded to
        goal = self._targets.get(vehicle_name)
        if goal is not None:
            self._poses[vehicle_name].position.x_val = goal[0]
            self._poses[vehicle_name].position.y_val = goal[1]
            self._poses[vehicle_name].position.z_val = goal[2]
        return st

    # ── Commands (all return a dummy "future" object with .join()) ───────────
    class _DummyFuture:
        def join(self) -> None: return None
        def __bool__(self) -> bool: return True

    def takeoffAsync(self, timeout_sec: float = 20.0, vehicle_name: str = ""):
        pose = self._poses.setdefault(vehicle_name, _FakePose())
        pose.position.z_val = -5.0
        if self._verbose:
            print(f"[MockAirSim] takeoffAsync({vehicle_name!r}) → z=-5")
        return self._DummyFuture()

    def landAsync(self, timeout_sec: float = 60.0, vehicle_name: str = ""):
        pose = self._poses.setdefault(vehicle_name, _FakePose())
        pose.position.z_val = 0.0
        if self._verbose:
            print(f"[MockAirSim] landAsync({vehicle_name!r}) → z=0")
        # Clear target so next state query doesn't overwrite z
        self._targets.pop(vehicle_name, None)
        return self._DummyFuture()

    def moveToPositionAsync(self, x, y, z, velocity, timeout_sec=120,
                            drivetrain=0, yaw_mode=None, lookahead=-1,
                            adaptive_lookahead=1, vehicle_name: str = ""):
        self._targets[vehicle_name] = (float(x), float(y), float(z))
        if self._verbose:
            print(f"[MockAirSim] moveToPositionAsync({vehicle_name!r}) → "
                  f"({x:.1f}, {y:.1f}, {z:.1f}) @ {velocity} m/s")
        return self._DummyFuture()

    def moveToZAsync(self, z, velocity, timeout_sec=60, yaw_mode=None,
                     lookahead=-1, adaptive_lookahead=1, vehicle_name: str = ""):
        pose = self._poses.setdefault(vehicle_name, _FakePose())
        self._targets[vehicle_name] = (pose.position.x_val,
                                        pose.position.y_val, float(z))
        if self._verbose:
            print(f"[MockAirSim] moveToZAsync({vehicle_name!r}) → z={z:.1f}")
        return self._DummyFuture()

    def hoverAsync(self, vehicle_name: str = ""):
        if self._verbose:
            print(f"[MockAirSim] hoverAsync({vehicle_name!r})")
        return self._DummyFuture()

    def cancelLastTask(self, vehicle_name: str = "") -> None:
        self._targets.pop(vehicle_name, None)

    def reset(self) -> None: pass

    # ── Object spawn / move / destroy (for VehicleMirror) ────────────────────
    def simListAssets(self) -> list[str]:
        # Pretend the UE5 project has the AirSim Vehicles content pack
        return ["SedanSUV", "SUV_C", "Truck_C", "Motorcycle"]

    def simSpawnObject(self, object_name, asset_name, pose, scale,
                       physics_enabled=False, is_blueprint=False):
        self._objects[object_name] = _FakePose()
        if self._verbose:
            print(f"[MockAirSim] simSpawnObject({object_name!r}, {asset_name!r})")
        return object_name

    def simSetObjectPose(self, object_name, pose, teleport: bool = True) -> bool:
        self._objects[object_name] = pose  # not a real FakePose but close enough
        return True

    def simDestroyObject(self, object_name: str) -> bool:
        self._objects.pop(object_name, None)
        return True
