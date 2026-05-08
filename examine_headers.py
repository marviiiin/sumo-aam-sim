import struct
import sys

def read_header(path, label):
    with open(path, 'rb') as f:
        data = f.read(200)
    tag = struct.unpack_from('<I', data, 0)[0]
    legacy_ver = struct.unpack_from('<i', data, 4)[0]
    print(f'{label}:')
    print(f'  Tag: 0x{tag:08X}  LegacyFileVersion: {legacy_ver}')
    print(f'  First 80 bytes hex:')
    for i in range(0, 80, 16):
        hex_str = ' '.join(f'{b:02x}' for b in data[i:i+16])
        print(f'    {i:04x}: {hex_str}')

read_header(r'C:\Users\okmar\Desktop\CarlaAir\CarlaAir-v0.1.7-Windows11-x86_64\WindowsNoEditor\CarlaUE4\Plugins\AirSim\Content\Models\QuadRotor1\_backup\Quadrotor1.uasset.bak', 'CarlaAir UE4 Original')
print()
read_header(r'C:\Users\okmar\Desktop\MeshCooker\Saved\Cooked\Windows\MeshCooker\Plugins\AirSim\Content\Models\QuadRotor1\Quadrotor1.uasset', 'Our UE5 Cook')
