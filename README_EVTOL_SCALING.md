# Scaling the eVTOL Drone Mesh in CarlaAir

## Problem

The default AirSim quadrotor mesh in CarlaAir v0.1.7 is very small — roughly 1m across — making it nearly invisible when viewed from typical camera distances in a city-scale simulation. AirSim does not provide a working API to scale vehicle pawns at runtime:

- **`simSetObjectScale()`** returns `True` and updates the internal scale value, but produces **no visual change** on vehicle pawns. AirSim separates physics from rendering for vehicles.
- **`simSpawnObject()`** hangs indefinitely in CarlaAir v0.1.7 and cannot be used.
- **AirSim `settings.json`** has no scale parameter for vehicles.

## Solution: Direct Mesh Vertex Scaling

The approach that works is **modifying the cooked UE4 static mesh files** (`.uexp`) on disk before launching CarlaAir. By scaling the raw vertex positions in the binary mesh data, the drone renders larger in-engine without any runtime API calls.

### Target Files

Located in:
```
CarlaAir-v0.1.7-Windows11-x86_64\WindowsNoEditor\
  CarlaUE4\Plugins\AirSim\Content\Models\QuadRotor1\
```

| File | Description | Vertices |
|------|-------------|----------|
| `Quadrotor1.uexp` | Main drone body mesh | ~9,057 |
| `Propeller.uexp` | Propeller blade mesh | ~1,557 |

### How It Works

UE4 cooked static meshes store vertex positions in **FPositionVertexBuffer** regions:

```
[uint32: stride=12] [uint32: num_verts] [uint32: stride=12] [uint32: num_verts]
[float32 x, float32 y, float32 z] * num_verts
```

Each vertex is 3 consecutive `float32` values (12 bytes per vertex). The script:

1. **Locates** all FPositionVertexBuffer regions by scanning for the stride=12 header pattern
2. **Scales** every vertex position (x, y, z) by the scale factor (10x)
3. **Scales** matching bounding box floats in the file header and trailer so UE4's culling/LOD still works correctly
4. **Writes** the modified binary back to the same file

### Running the Script

```bash
# From the sumo_aam_sim directory
python scale_evtol_mesh.py
```

The script accepts an optional scale factor argument and uses the `CARLAAIR_MESH_DIR` environment variable for the mesh path:

```bash
# Set mesh directory (or edit MESH_DIR in the script)
export CARLAAIR_MESH_DIR="/path/to/CarlaAir/.../Models/QuadRotor1"

python scale_evtol_mesh.py        # Default 10x scale
python scale_evtol_mesh.py 5.0    # Custom scale factor
```

**You must restart CarlaAir after running the script** for changes to take effect — UE4 loads meshes at startup.

### Backups

The script does not create backups automatically. Before first run, manually back up the originals:

```bash
cp Quadrotor1.uexp Quadrotor1.uexp.bak
cp Propeller.uexp Propeller.uexp.bak
```

To restore originals:
```bash
cp Quadrotor1.uexp.bak Quadrotor1.uexp
cp Propeller.uexp.bak Propeller.uexp
```

## Known Limitations

### Propeller Attachment Positions

The drone blueprint (`BP_FlyingPawn.uexp`) defines where propellers attach to the body at hardcoded positions (e.g., x=25, y=25). When the body mesh is scaled 10x, these attachment points are no longer at the correct relative positions — the propellers appear offset from the body ("dislocated fans").

**Why we don't patch the blueprint:** Binary patching `BP_FlyingPawn.uexp` to update the propeller attachment offsets (from 25 to 250, etc.) broke the rendering entirely — the eVTOL stopped appearing in the scene. UE4 blueprint serialization includes checksums or dependent fields that become inconsistent when individual floats are modified.

### Approaches That Don't Work

| Approach | Result |
|----------|--------|
| `simSetObjectScale()` API | Returns True, no visual change |
| `simSpawnObject()` API | Hangs indefinitely |
| Blueprint binary patching | Breaks rendering |
| Scaling ALL floats in .uexp | Corrupts UVs, normals, tangents |
| AirSim settings.json scale | No such parameter exists |

## Integration with SUMO-AAMSim

The mesh scaling is independent of the simulation code. The drone controller (`carlaair_bridge/drone_controller.py`) uses `simSetVehiclePose()` to teleport the drone each tick — this works identically regardless of mesh size. No code changes are needed in the bridge.

## Workflow

1. Back up original `.uexp` files
2. Run `python scale_evtol_mesh.py`
3. Launch CarlaAir: `powershell -ExecutionPolicy Bypass -File CarlaAir.ps1 Town10HD --no-traffic`
4. Launch SUMO bridge: `python run_with_carlaair.py --gui --seed 42 --duration 600`
5. Wait for an eVTOL flight to depart (~420s with default passenger data)
6. Observe the scaled drone in the 3D view
