"""
analyze_metrics.py — Quick post-run analysis of the metrics CSV.

Usage:
    python analyze_metrics.py                     # latest file in output/
    python analyze_metrics.py output/sim_metrics_20240101_120000.csv
"""

import csv
import os
import sys
from pathlib import Path

from config import METRICS_OUT_DIR, VERTIPORTS


def load_latest_csv() -> Path:
    candidates = sorted(Path(METRICS_OUT_DIR).glob("sim_metrics_*.csv"))
    if not candidates:
        sys.exit(f"No metrics files found in '{METRICS_OUT_DIR}'.")
    return candidates[-1]


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def summarise(rows: list[dict]) -> None:
    if not rows:
        print("CSV is empty.")
        return

    vp_ids = list(VERTIPORTS.keys())
    t_end  = float(rows[-1]["timestep_s"])

    print(f"\n{'=' * 62}")
    print(f"  METRICS SUMMARY   ({len(rows)} rows, sim end = {t_end:.0f} s)")
    print(f"{'=' * 62}")

    for vp_id in vp_ids:
        name = VERTIPORTS[vp_id]["name"]
        print(f"\n  ── {name}  [{vp_id}] ──────────────────────────────")

        # Last-row cumulative values
        last = rows[-1]
        print(f"    eVTOL arrivals (total)      : {last[f'{vp_id}_evtol_arrivals']}")
        print(f"    Passengers served (total)   : {last[f'{vp_id}_passengers_served']}")
        print(f"    Rental cars injected (total): {last[f'{vp_id}_rental_cars_injected']}")
        print(f"    Spillback events (total)    : {last[f'{vp_id}_spillback_events']}")

        # Time-averaged occupancy and queue
        occs   = [float(r[f"{vp_id}_parking_occupancy"]) for r in rows]
        queues = [float(r[f"{vp_id}_queue_length"])       for r in rows]
        print(f"    Mean parking occupancy      : {sum(occs)/len(occs):.2f} vehicles")
        print(f"    Peak parking occupancy      : {max(occs):.0f} vehicles")
        print(f"    Mean approach queue length  : {sum(queues)/len(queues):.2f} vehicles")
        print(f"    Peak approach queue length  : {max(queues):.0f} vehicles")

        # Fraction of time parking was ≥ 90 % full
        cap      = VERTIPORTS[vp_id]["max_parking"]
        n_full   = sum(1 for o in occs if o >= 0.9 * cap)
        pct_full = 100.0 * n_full / len(occs)
        print(f"    Time parking ≥ 90 % full    : {pct_full:.1f} %")

    print(f"\n{'=' * 62}\n")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else load_latest_csv()
    print(f"Loading {path} …")
    rows = load_csv(path)
    summarise(rows)


if __name__ == "__main__":
    main()
