"""
metrics_logger.py
Writes per-timestep simulation metrics to a timestamped CSV file.

CSV schema (one row per log interval):
    timestep_s,
    <vp_id>_evtol_arrivals,        # cumulative arrivals
    <vp_id>_passengers_served,     # cumulative passengers
    <vp_id>_rental_cars_injected,  # cumulative rental cars put into network
    <vp_id>_parking_occupancy,     # current number of parked vehicles
    <vp_id>_queue_length,          # vehicles on approach edge (spillback indicator)
    <vp_id>_spillback_events,      # cumulative spillback episodes
    ...repeated for each vertiport...
"""

import csv
import os
from datetime import datetime

from config import METRICS_OUT_DIR


class MetricsLogger:
    """
    Parameters
    ----------
    vertiports : dict – config.VERTIPORTS mapping
    """

    def __init__(self, vertiports: dict) -> None:
        os.makedirs(METRICS_OUT_DIR, exist_ok=True)
        self._vp_ids = list(vertiports.keys())

        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sim_metrics_{ts}.csv"
        self.filepath = os.path.join(METRICS_OUT_DIR, filename)

        self._fieldnames = self._build_fieldnames()
        self._fh     = open(self.filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=self._fieldnames)
        self._writer.writeheader()
        self._fh.flush()

        print(f"Metrics → {self.filepath}")

    # ── Public interface ──────────────────────────────────────────────────────

    def log(
        self,
        t: float,
        arrival_handlers: dict,   # vp_id → EvtolArrivalHandler
        parking_managers: dict,   # vp_id → ParkingManager
    ) -> None:
        row: dict = {"timestep_s": f"{t:.1f}"}
        for vp_id in self._vp_ids:
            ah = arrival_handlers[vp_id]
            pm = parking_managers[vp_id]
            row.update({
                f"{vp_id}_evtol_arrivals":       ah.total_arrivals,
                f"{vp_id}_passengers_served":    ah.total_passengers,
                f"{vp_id}_rental_cars_injected": ah.total_rentals,
                f"{vp_id}_parking_occupancy":    pm.current_occupancy,
                f"{vp_id}_queue_length":         pm.current_queue_length,
                f"{vp_id}_spillback_events":     pm.spillback_events,
            })
        self._writer.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()
        print(f"Metrics saved → {self.filepath}")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_fieldnames(self) -> list:
        fields = ["timestep_s"]
        for vp_id in self._vp_ids:
            fields += [
                f"{vp_id}_evtol_arrivals",
                f"{vp_id}_passengers_served",
                f"{vp_id}_rental_cars_injected",
                f"{vp_id}_parking_occupancy",
                f"{vp_id}_queue_length",
                f"{vp_id}_spillback_events",
            ]
        return fields
