# SUMO-AAMSim: eVTOL Air-Ground Traffic Co-Simulation

A multi-modal traffic simulation integrating **SUMO** (ground vehicles), **CARLA** (3D rendering), and **AirSim** (drone/eVTOL flight) via **CarlaAir** — a unified Unreal Engine environment that runs CARLA and AirSim simultaneously.

The simulation models an urban Advanced Air Mobility (AAM) corridor between two vertiports, with data-driven passenger demand from the Tampa Bay AAM Feasibility Study. Passengers arrive at vertiports, board eVTOL aircraft, fly between vertiports, and are dispatched as ground vehicles (rental cars) upon landing — all visualized in real-time 3D.

![Architecture](docs/architecture.png)

## Features

- **Data-driven passenger demand** from Tampa Bay AAM study (316 passengers over 5-hour peak)
- **Queuing model** with boarding rules: capacity=4, timeout-based dispatch
- **SUMO ground traffic** with vertiport approach roads, parking lots, spillback detection
- **CARLA 3D visualization** of ground vehicles mirrored from SUMO
- **AirSim eVTOL drone** flying between vertiports with pose-interpolated flight
- **Pedestrian simulation** with ambient walkers and vertiport passenger spawning
- **Metrics logging** with CSV output

## Architecture

```
┌────────────────────────────────────────────────────────┐
│                     CarlaAir v0.1.7                    │
│              (Single Unreal Engine Process)            │
│                                                        │
│   ┌─────────────┐              ┌──────────────┐       │
│   │   CARLA API  │              │  AirSim API  │       │
│   │  Port 2000   │              │  Port 41451  │       │
│   │              │              │              │       │
│   │ Ground cars  │              │ eVTOL drone  │       │
│   │ Pedestrians  │              │ Pose control │       │
│   │ Weather/HUD  │              │              │       │
│   └──────┬───────┘              └──────┬───────┘       │
│          │                             │               │
└──────────┼─────────────────────────────┼───────────────┘
           │                             │
    ┌──────┴──────────────────────────────┴───────┐
    │           CarlaAirBridge (Python)           │
    │                                              │
    │  • Vehicle sync: SUMO → CARLA actors        │
    │  • Drone controller: flight state machine   │
    │  • Pedestrian manager: walkers at vertiports│
    │  • Coordinate transforms: SUMO↔CARLA↔AirSim│
    └──────────────────┬───────────────────────────┘
                       │
              ┌────────┴────────┐
              │   SUMO (TraCI)  │
              │                 │
              │ • Road network  │
              │ • Traffic flow  │
              │ • eVTOL routes  │
              │ • Parking lots  │
              └─────────────────┘
```

## Prerequisites

### 1. SUMO (Simulation of Urban MObility)

Download and install SUMO >= 1.18.0:
- **Windows**: https://sumo.dlr.de/docs/Downloads.php (use the installer)
- Set the `SUMO_HOME` environment variable to your SUMO installation directory:
  ```
  set SUMO_HOME=C:\Program Files (x86)\Eclipse\Sumo
  ```

### 2. CarlaAir v0.1.7

CarlaAir bundles CARLA 0.9.15 and AirSim 1.8.1 in a single UE4 binary.

1. Download CarlaAir v0.1.7 for Windows from the releases page
2. Extract to a directory (e.g., `C:\CarlaAir\CarlaAir-v0.1.7-Windows11-x86_64`)
3. The directory should contain:
   ```
   CarlaAir-v0.1.7-Windows11-x86_64/
   ├── CarlaAir.ps1          # Launch script
   ├── AirSimConfig/
   │   └── settings.json     # AirSim settings (auto-copied on launch)
   └── WindowsNoEditor/
       └── CarlaUE4.exe      # Main binary
   ```

### 3. Python Environment

Create a conda environment with all dependencies:

```bash
conda create -n carlaAir python=3.10
conda activate carlaAir
pip install -r requirements.txt
```

**Note on CARLA Python API**: The `carla` package version must match your CarlaAir version. For CarlaAir v0.1.7 (CARLA 0.9.15):
```bash
pip install carla==0.9.15
```

### 4. AirSim Settings

CarlaAir auto-copies settings on launch, but ensure `Documents/AirSim/settings.json` contains:
```json
{
  "SettingsVersion": 1.2,
  "SimMode": "Multirotor",
  "Vehicles": {
    "SimpleFlight": {
      "VehicleType": "SimpleFlight",
      "AutoCreate": true
    }
  }
}
```

## Quick Start

### 1. Generate SUMO Network (first time only)

```bash
python generate_town10hd_net.py
```

This creates the SUMO road network with vertiport infrastructure in `network/`.

### 2. Scale eVTOL Mesh (optional, recommended)

The default AirSim drone mesh is tiny. Scale it 10x for visibility:

```bash
# Back up originals first
cd <CarlaAir>/WindowsNoEditor/CarlaUE4/Plugins/AirSim/Content/Models/QuadRotor1/
cp Quadrotor1.uexp Quadrotor1.uexp.bak
cp Propeller.uexp Propeller.uexp.bak

# Run the scaling script (edit MESH_DIR in the script to match your path)
cd <this-repo>
python scale_evtol_mesh.py
```

See [README_EVTOL_SCALING.md](README_EVTOL_SCALING.md) for details on how this works.

### 3. Launch CarlaAir

```bash
cd <CarlaAir-directory>
powershell -ExecutionPolicy Bypass -File CarlaAir.ps1 Town10HD --no-traffic
```

Wait until both ports are ready:
```
CARLA (port 2000): Ready
AirSim (port 41451): Ready
CarlaAir is ready.
```

### 4. Run the Simulation

```bash
conda activate carlaAir
python run_with_carlaair.py --gui --seed 42 --duration 600
```

**Arguments:**
| Flag | Description | Default |
|------|-------------|---------|
| `--gui` | Open SUMO GUI alongside CarlaAir | off |
| `--seed N` | Random seed for reproducibility | random |
| `--duration N` | Simulation duration in seconds | 900 |
| `--begin N` | Start time in seconds | 0 |

### 5. Observe

- **CarlaAir window**: 3D view of ground vehicles, drone flights, pedestrians
- **SUMO GUI** (if `--gui`): 2D traffic view with vertiport infrastructure
- **Console**: Flight departures, landings, passenger counts

The first eVTOL flight typically departs around t=420s (7 min) due to passenger boarding timeouts.

## Running Without CarlaAir

The simulation can run standalone (SUMO only) for headless analysis:

```bash
python simulation.py --seed 42 --duration 18000
```

This runs the full 5-hour passenger demand scenario without 3D visualization.

## Project Structure

```
sumo_aam_sim/
├── README.md                    # This file
├── README_EVTOL_SCALING.md      # How eVTOL mesh scaling works
├── requirements.txt             # Python dependencies
├── .gitignore
│
├── simulation.py                # Main SUMO simulation loop
├── run_with_carlaair.py         # Entry point: SUMO + CarlaAir
├── run_with_carla.py            # Entry point: SUMO + CARLA (no AirSim)
├── run_with_airsim.py           # Entry point: SUMO + standalone AirSim
├── config.py                    # Central simulation configuration
├── sumo_aam_sim.sumocfg         # SUMO configuration file
│
├── arrival_handler.py           # eVTOL departure/arrival logic per vertiport
├── passenger_queue.py           # Data-driven passenger queue & boarding rules
├── parking_manager.py           # Vertiport parking lot management
├── metrics_logger.py            # CSV metrics output
│
├── generate_town10hd_net.py     # Generate SUMO network from Town10HD
├── generate_network.py          # Generic network generation
├── vertiport_generator.py       # Vertiport infrastructure generation
├── scale_evtol_mesh.py          # Scale AirSim drone mesh (10x)
├── sensitivity_analysis.py      # Parameter sensitivity analysis
│
├── carlaair_bridge/             # CarlaAir bridge (CARLA + AirSim)
│   ├── __init__.py
│   ├── bridge.py                # Main bridge: vehicle sync + drone + peds
│   ├── config.py                # CarlaAir connection & coordinate settings
│   ├── coordinate_map.py        # SUMO ↔ CARLA ↔ AirSim transforms
│   ├── drone_controller.py      # Drone flight state machine
│   └── pedestrian_manager.py    # Ambient walkers + vertiport passengers
│
├── airsim_bridge/               # Standalone AirSim bridge (multi-drone)
│   ├── __init__.py
│   ├── bridge.py
│   ├── config_airsim.py
│   ├── coordinate_map.py
│   ├── flight_controller.py
│   ├── flight_fleet.py
│   ├── mock_client.py
│   └── vehicle_mirror.py
│
├── carla_bridge/                # Standalone CARLA bridge (no AirSim)
│   ├── __init__.py
│   ├── bridge.py
│   ├── config_carla.py
│   ├── coordinate_map.py
│   ├── evtol_actor.py
│   └── vehicle_sync.py
│
├── data/
│   └── evtol_in_and_out_of_vehicle.xlsx  # Passenger arrival data
│
├── network/                     # Generated SUMO network files
│   ├── town10hd_vp.net.xml      # Main network with vertiports
│   ├── routes.rou.xml           # Vehicle routes
│   ├── additionals.add.xml      # Detectors, parking areas, bus stops
│   └── ...
│
├── output/                      # Simulation output (gitignored)
│   └── sim_metrics_*.csv
│
└── saved_runs/                  # Reference run results
    └── *.csv
```

## Coordinate System

Three coordinate systems are used, with transforms handled by `carlaair_bridge/coordinate_map.py`:

| System | X | Y | Z | Notes |
|--------|---|---|---|-------|
| SUMO | East (+) | North (+) | - | 2D, from OpenDRIVE conversion |
| CARLA | East (+) | South (+) | Up (+) | Y-flipped from SUMO |
| AirSim NED | North (+) | East (+) | Down (+) | Offset from CARLA origin |

**SUMO → CARLA**: `carla_x = sumo_x`, `carla_y = -sumo_y`

**CARLA → AirSim**: `airsim_x = carla_x + 172.20`, `airsim_y = carla_y - 183.86`, `airsim_z = -carla_z + 27.45`

## Configuration

All simulation parameters are in `config.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `SIMULATION_DURATION_S` | 18,000 | 5-hour simulation (full passenger data) |
| `EVTOL_CAPACITY` | 4 | Passengers per eVTOL flight |
| `MAX_PARKING_SPACES` | 20 | Parking spaces per vertiport |
| `SPILLBACK_THRESHOLD` | 5 | Vehicles on approach edge triggering spillback |

CarlaAir bridge settings are in `carlaair_bridge/config.py`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `CRUISE_ALT_M` | 25 | Drone cruise altitude (metres) |
| `CRUISE_SPEED_MS` | 30 | Horizontal flight speed (m/s) |
| `CARLA_PORT` | 2000 | CARLA API port |
| `AIRSIM_PORT` | 41451 | AirSim API port |

## Passenger Boarding Rules

From the Tampa Bay AAM study data (316 passengers, 5-hour peak):

1. **Full eVTOL** (4 pax) → immediate takeoff
2. **Single passenger** waiting 15 min alone → takeoff with 1 pax
3. **2+ passengers**, second waited 10 min → takeoff
4. **Renege**: passenger leaves queue after 30 min wait

## Data Source

Passenger arrival times from:
> Tampa Bay AAM Feasibility Study — "evtol in and out of vehicle.xlsx"
>
> Tampa → Brandon: 168 passengers, Brandon → Tampa: 148 passengers

The Excel file is included in `data/` and read by `passenger_queue.py`.

## License

Research/academic use. Contact the authors for licensing details.
