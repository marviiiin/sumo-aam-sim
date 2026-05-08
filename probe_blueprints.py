"""Probe CARLA for available blueprints — find anything aircraft/drone-like."""
import carla

client = carla.Client("localhost", 2000)
client.set_timeout(10.0)
world = client.get_world()
lib = world.get_blueprint_library()

print("=== ALL VEHICLE BLUEPRINTS ===")
for bp in sorted(lib.filter("vehicle.*"), key=lambda b: b.id):
    print(f"  {bp.id}")

print("\n=== STATIC PROPS (interesting) ===")
for bp in sorted(lib.filter("static.*"), key=lambda b: b.id):
    print(f"  {bp.id}")

print("\n=== ANYTHING WITH 'air' or 'fly' or 'drone' ===")
for bp in lib:
    bid = bp.id.lower()
    if any(k in bid for k in ("air", "fly", "drone", "heli", "plane", "prop")):
        print(f"  {bp.id}")
