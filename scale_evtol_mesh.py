"""Scale eVTOL drone mesh vertices in the cooked .uexp files.

Targets both Quadrotor1.uexp (body) and Propeller.uexp (props).
Locates FPositionVertexBuffer regions in UE4 cooked static mesh files
and multiplies all vertex positions by the given scale factor.

Usage:
    python scale_evtol_mesh.py              # Scale 10x (default)
    python scale_evtol_mesh.py 5.0          # Scale 5x
    python scale_evtol_mesh.py 1.0          # Restore to original (if run on .bak)

IMPORTANT: Back up the original .uexp files before running this script!
    cp Quadrotor1.uexp Quadrotor1.uexp.bak
    cp Propeller.uexp Propeller.uexp.bak
"""
import struct
import sys
import os

SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

# Path to CarlaAir's AirSim drone mesh files.
# Adjust this to match your CarlaAir installation directory.
MESH_DIR = os.environ.get(
    "CARLAAIR_MESH_DIR",
    os.path.join(
        os.path.expanduser("~"), "Desktop", "CarlaAir",
        "CarlaAir-v0.1.7-Windows11-x86_64", "WindowsNoEditor",
        "CarlaUE4", "Plugins", "AirSim", "Content", "Models", "QuadRotor1",
    ),
)


def find_position_buffers(data):
    """Find FPositionVertexBuffer regions: stride=12, then vertex data."""
    stride_bytes = struct.pack('<I', 12)
    buffers = []
    offset = 0

    # Double-header pattern: 12, N, 12, N, then N*3 floats
    while True:
        idx = data.find(stride_bytes, offset)
        if idx < 0 or idx + 16 > len(data):
            break
        num_verts = struct.unpack_from('<I', data, idx + 4)[0]
        val2 = struct.unpack_from('<I', data, idx + 8)[0]
        val3 = struct.unpack_from('<I', data, idx + 12)[0]

        if num_verts > 10 and num_verts < 500000 and val2 == 12 and val3 == num_verts:
            data_start = idx + 16
            data_size = num_verts * 12
            if data_start + data_size <= len(data):
                valid = 0
                for s in range(0, min(30, num_verts * 3), 3):
                    off = data_start + s * 4
                    x = struct.unpack_from('<f', data, off)[0]
                    y = struct.unpack_from('<f', data, off + 4)[0]
                    z = struct.unpack_from('<f', data, off + 8)[0]
                    if all(-50000 < v < 50000 for v in [x, y, z]):
                        valid += 1
                if valid >= 3:
                    buffers.append({
                        'header_off': idx,
                        'data_start': data_start,
                        'num_verts': num_verts,
                        'data_size': data_size,
                    })
        offset = idx + 4

    # Single-header pattern: 12, N, N*12, then data
    offset = 0
    while True:
        idx = data.find(stride_bytes, offset)
        if idx < 0 or idx + 12 > len(data):
            break
        num_verts = struct.unpack_from('<I', data, idx + 4)[0]
        data_size_val = struct.unpack_from('<I', data, idx + 8)[0]
        if (num_verts > 10 and num_verts < 500000
                and data_size_val == num_verts * 12):
            data_start = idx + 12
            if not any(b['header_off'] == idx for b in buffers):
                if data_start + data_size_val <= len(data):
                    x0 = struct.unpack_from('<f', data, data_start)[0]
                    if -50000 < x0 < 50000:
                        buffers.append({
                            'header_off': idx,
                            'data_start': data_start,
                            'num_verts': num_verts,
                            'data_size': data_size_val,
                        })
        offset = idx + 4

    return buffers


def scale_mesh(filepath, scale):
    """Scale all vertex positions and bounding boxes in a .uexp mesh file."""
    print(f"\n{'='*60}")
    print(f"Scaling: {os.path.basename(filepath)}  (x{scale})")
    print(f"{'='*60}")

    with open(filepath, 'rb') as f:
        data = bytearray(f.read())
    data_orig = bytes(data)
    print(f"  File size: {len(data)} bytes")

    buffers = find_position_buffers(data)
    if not buffers:
        print("  WARNING: No position vertex buffers found!")
        return False

    print(f"  Found {len(buffers)} position buffer(s)")

    # Scale vertices and collect original bounds
    all_mins = [float('inf')] * 3
    all_maxs = [float('-inf')] * 3
    total_verts = 0

    for buf in buffers:
        start = buf['data_start']
        n = buf['num_verts']

        for v in range(n):
            for c in range(3):
                off = start + v * 12 + c * 4
                val = struct.unpack_from('<f', data_orig, off)[0]
                if val < all_mins[c]:
                    all_mins[c] = val
                if val > all_maxs[c]:
                    all_maxs[c] = val
                struct.pack_into('<f', data, off, val * scale)

        total_verts += n
        print(f"  Scaled {n} vertices in buffer at 0x{buf['header_off']:X}")

    print(f"  Total vertices scaled: {total_verts}")
    print(f"  Original bounds: ({all_mins[0]:.1f},{all_mins[1]:.1f},{all_mins[2]:.1f}) - "
          f"({all_maxs[0]:.1f},{all_maxs[1]:.1f},{all_maxs[2]:.1f})")

    # Scale FBox bounding boxes (6 consecutive floats matching known bounds)
    # Collect exact float patterns from the bounds
    known_patterns = set()
    for val in all_mins + all_maxs:
        known_patterns.add(struct.pack('<f', val))
        known_patterns.add(struct.pack('<f', -val))

    # Scan header (before first vertex buffer) for bounding box floats
    header_end = buffers[0]['data_start']
    bbox_scaled = 0
    for i in range(0, header_end, 4):
        raw = bytes(data_orig[i:i+4])
        if raw in known_patterns:
            val = struct.unpack_from('<f', data_orig, i)[0]
            struct.pack_into('<f', data, i, val * scale)
            bbox_scaled += 1

    # Also scan AFTER vertex data for trailing bounding boxes
    trail_start = buffers[-1]['data_start'] + buffers[-1]['data_size']
    for i in range(trail_start, len(data) - 4, 4):
        raw = bytes(data_orig[i:i+4])
        if raw in known_patterns:
            val = struct.unpack_from('<f', data_orig, i)[0]
            struct.pack_into('<f', data, i, val * scale)
            bbox_scaled += 1

    print(f"  Scaled {bbox_scaled} bounding box coordinates")

    with open(filepath, 'wb') as f:
        f.write(data)
    print(f"  Written: {filepath}")
    return True


# Scale both meshes
body = os.path.join(MESH_DIR, "Quadrotor1.uexp")
prop = os.path.join(MESH_DIR, "Propeller.uexp")

ok1 = scale_mesh(body, SCALE)
ok2 = scale_mesh(prop, SCALE)

if ok1:
    print(f"\nDone! eVTOL mesh scaled by {SCALE}x.")
    print("Restart CarlaAir to see the change.")
else:
    print("\nFailed to scale body mesh!")
    sys.exit(1)
