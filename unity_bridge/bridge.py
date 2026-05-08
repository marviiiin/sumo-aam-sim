"""
unity_bridge/bridge.py — UnityBridge: streams simulation state to Unity via UDP.

Protocol
--------
Every SUMO step the bridge serialises the current state into a compact JSON
datagram and sends it to a Unity UDP listener (default localhost:9000).

Message schema  (matches Assets/Scripts/SumoMessage.cs)
---------------------------------------------------------------------------
{
  "t": 123.5,
  "vehicles": [
    { "id":"visitor_vp_a_00001", "vtype":"passenger",
      "x":300.0, "y":-150.0, "speed":4.2, "angle":270.0 }
  ],
  "evtol_events": [
    { "vp_id":"vp_a", "passengers":3, "t":600.0 }
  ],
  "vertiports": [
    { "id":"vp_a", "name":"Vertiport Alpha",
      "occupancy":12, "capacity":20, "queue":3, "spillback":false,
      "cx":300.0, "cy":-255.0 }
  ]
}
---------------------------------------------------------------------------

No external dependencies — uses only Python's built-in socket + json modules.
Max UDP payload is ~65 KB; with 500 vehicles @ ~80 bytes each that is ~40 KB,
well within limit.  For very large scenarios switch to TCP (config below).
"""

import json
import socket
from config import VERTIPORTS

try:
    import traci
    import traci.exceptions as _traci_exc
    _HAS_TRACI = True
except ImportError:
    _HAS_TRACI = False


# ── Unity endpoint config (tune to match UnityBridge.cs inspector values) ─────
UNITY_HOST = "127.0.0.1"
UNITY_PORT = 9000
SEND_EVERY_N_STEPS = 1          # 1 = every step; increase to reduce bandwidth


class UnityBridge:
    """
    Serialises SUMO state and sends it to Unity over UDP every N steps.

    Usage in simulation.py
    ----------------------
        bridge = UnityBridge()
        run(args, on_step=bridge.sync)
        bridge.close()
    """

    def __init__(
        self,
        host: str = UNITY_HOST,
        port: int = UNITY_PORT,
        send_every: int = SEND_EVERY_N_STEPS,
    ) -> None:
        self._host       = host
        self._port       = port
        self._every      = send_every
        self._sock       = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._step_count = 0
        self._pending_evtol: list[dict] = []   # buffered across steps
        print(f"[Unity] UDP bridge → {host}:{port}  (every {send_every} step(s))")

    # ── Public interface ──────────────────────────────────────────────────────

    def sync(self, t: float, arrival_handlers: dict, parking_managers: dict) -> None:
        """Callback for simulation.run(on_step=...)."""
        # Collect eVTOL events (may fire on any step)
        for vp_id, ah in arrival_handlers.items():
            if ah.step_arrivals > 0:
                self._pending_evtol.append({
                    "vp_id":      vp_id,
                    "passengers": ah.step_passengers,
                    "t":          t,
                })

        self._step_count += 1
        if self._step_count % self._every != 0:
            return

        payload = self._build_payload(t, arrival_handlers, parking_managers)
        self._send(payload)

    def close(self) -> None:
        self._sock.close()
        print("[Unity] UDP bridge closed.")

    # ── Payload builder ───────────────────────────────────────────────────────

    def _build_payload(
        self, t: float, arrival_handlers: dict, parking_managers: dict
    ) -> dict:
        return {
            "t":            round(t, 2),
            "vehicles":     self._collect_vehicles(),
            "evtol_events": self._flush_evtol_events(),
            "vertiports":   self._collect_vertiports(parking_managers),
        }

    def _collect_vehicles(self) -> list[dict]:
        if not _HAS_TRACI:
            return []
        vehicles = []
        try:
            for vid in traci.vehicle.getIDList():
                try:
                    x, y  = traci.vehicle.getPosition(vid)
                    speed  = traci.vehicle.getSpeed(vid)
                    angle  = traci.vehicle.getAngle(vid)
                    vtype  = traci.vehicle.getTypeID(vid)
                    vehicles.append({
                        "id":    vid,
                        "vtype": vtype,
                        "x":     round(x, 2),
                        "y":     round(y, 2),
                        "speed": round(speed, 2),
                        "angle": round(angle, 1),
                    })
                except _traci_exc.TraCIException:
                    pass
        except _traci_exc.TraCIException:
            pass
        return vehicles

    def _flush_evtol_events(self) -> list[dict]:
        events, self._pending_evtol = self._pending_evtol, []
        return events

    def _collect_vertiports(self, parking_managers: dict) -> list[dict]:
        result = []
        for vp_id, pm in parking_managers.items():
            cfg = VERTIPORTS[vp_id]
            # SUMO centre of parking edge (hardcoded to match coordinate_map.py)
            centres = {"vp_a": (300.0, -255.0), "vp_b": (950.0, -255.0)}
            cx, cy = centres.get(vp_id, (0.0, 0.0))
            result.append({
                "id":        vp_id,
                "name":      cfg["name"],
                "occupancy": pm.current_occupancy,
                "capacity":  cfg["max_parking"],
                "queue":     pm.current_queue_length,
                "spillback": pm.spillback_events > 0 and pm._spillback_active,
                "cx":        cx,
                "cy":        cy,
            })
        return result

    # ── Networking ────────────────────────────────────────────────────────────

    def _send(self, payload: dict) -> None:
        try:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self._sock.sendto(data, (self._host, self._port))
        except OSError as exc:
            print(f"[Unity WARN] UDP send failed: {exc}")
