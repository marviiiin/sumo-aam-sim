// TrafficManager.cs
// Spawns, moves, and removes ground vehicle GameObjects based on incoming
// SumoFrame data.  One GameObject per SUMO vehicle ID.
//
// Setup:
//   1. Add this component to the same GameObject as SumoReceiver.
//   2. Assign passengerPrefab and rentalPrefab in the Inspector.
//      (Plain coloured capsules / cubes work as placeholders.)
//   3. Set sumoScale and sumoOrigin to match your Unity scene layout.

using System.Collections.Generic;
using UnityEngine;

namespace SumoAAMSim
{
    public class TrafficManager : MonoBehaviour
    {
        // ── Inspector ─────────────────────────────────────────────────────────

        [Header("Vehicle Prefabs")]
        [Tooltip("Prefab for standard passenger cars (blue)")]
        public GameObject passengerPrefab;

        [Tooltip("Prefab for rental cars injected after eVTOL arrival (orange)")]
        public GameObject rentalPrefab;

        [Header("Coordinate Transform")]
        [Tooltip("SUMO world origin in Unity world space (metres).  " +
                 "Set so the SUMO network sits on your Unity terrain.")]
        public Vector3 sumoOrigin = new Vector3(-650f, 0f, 165f);

        [Tooltip("Uniform scale: Unity metres per SUMO metre")]
        public float sumoScale = 1f;

        [Tooltip("Y-axis flip: SUMO Y increases north; Unity Z increases north " +
                 "in a typical top-down layout.  Leave true for standard setup.")]
        public bool flipSumoY = true;

        [Header("Heading")]
        [Tooltip("Additive offset (degrees) applied to SUMO compass bearing → Unity Y-rotation. " +
                 "Adjust if vehicles face the wrong direction in your scene. Try 90 or -90.")]
        public float sumoYawOffset = 90f;

        [Header("Smoothing")]
        [Tooltip("Lerp speed for vehicle position updates (higher = snappier)")]
        public float positionLerpSpeed = 20f;

        // ── Runtime ───────────────────────────────────────────────────────────

        private Dictionary<string, GameObject> _vehicles = new();
        private Dictionary<string, Vector3>    _targets  = new();

        // ── Public API ────────────────────────────────────────────────────────

        /// <summary>Called by SumoReceiver on the main thread each UDP frame.</summary>
        public void OnFrame(SumoFrame frame)
        {
            if (frame.vehicles == null) return;

            var seen = new HashSet<string>();

            foreach (var vs in frame.vehicles)
            {
                seen.Add(vs.id);

                Vector3 worldPos = SumoToUnity(vs.x, vs.y);

                if (!_vehicles.TryGetValue(vs.id, out GameObject go))
                    go = SpawnVehicle(vs);

                // Store target for smooth lerp in Update()
                _targets[vs.id] = worldPos;

                // Rotate to heading.
                // SUMO angle: 0=north, 90=east, clockwise (compass bearing).
                // Unity Y-rotation (with flipSumoY=true, north = -Z):
                //   0=+Z, 90=+X, 180=-Z, 270=-X
                // Correct formula: unityYaw = sumo_angle + 90
                // (north SUMO = -Z Unity = 180° but +90 offset gives 90°... tune
                //  YawOffset below if vehicles point the wrong way in your scene)
                float unityYaw = vs.angle + sumoYawOffset;
                go.transform.rotation = Quaternion.Euler(0f, unityYaw, 0f);
            }

            // Destroy vehicles that left the simulation
            var toRemove = new List<string>();
            foreach (var kvp in _vehicles)
                if (!seen.Contains(kvp.Key))
                    toRemove.Add(kvp.Key);

            foreach (var id in toRemove)
            {
                Destroy(_vehicles[id]);
                _vehicles.Remove(id);
                _targets.Remove(id);
            }
        }

        // ── Unity lifecycle ───────────────────────────────────────────────────

        void Update()
        {
            float step = positionLerpSpeed * Time.deltaTime;
            foreach (var kvp in _targets)
            {
                if (_vehicles.TryGetValue(kvp.Key, out GameObject go))
                    go.transform.position = Vector3.MoveTowards(
                        go.transform.position, kvp.Value, step);
            }
        }

        void OnDestroy()
        {
            foreach (var go in _vehicles.Values)
                if (go != null) Destroy(go);
            _vehicles.Clear();
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private GameObject SpawnVehicle(VehicleState vs)
        {
            GameObject prefab = (vs.vtype == "rental_car") ? rentalPrefab : passengerPrefab;

            // Fallback: primitive cube if no prefab assigned
            GameObject go = (prefab != null)
                ? Instantiate(prefab, SumoToUnity(vs.x, vs.y), Quaternion.identity)
                : CreatePlaceholder(vs.vtype);

            go.name = vs.id;
            go.transform.SetParent(transform, worldPositionStays: true);
            _vehicles[vs.id] = go;
            return go;
        }

        private GameObject CreatePlaceholder(string vtype)
        {
            var go     = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.transform.localScale = new Vector3(2f, 1f, 4.5f);   // car-sized box

            var rend   = go.GetComponent<Renderer>();
            var mat    = new Material(Shader.Find("Standard"));
            mat.color  = (vtype == "rental_car")
                ? new Color(1f, 0.55f, 0f)    // orange
                : new Color(0.2f, 0.6f, 1f);  // blue
            rend.material = mat;

            // Disable physics collider (kinematic scene objects)
            Destroy(go.GetComponent<BoxCollider>());
            return go;
        }

        /// <summary>Convert SUMO (x, y) to Unity world position.</summary>
        public Vector3 SumoToUnity(float sx, float sy)
        {
            float ux = sumoScale * sx + sumoOrigin.x;
            float uz = sumoScale * (flipSumoY ? -sy : sy) + sumoOrigin.z;
            return new Vector3(ux, sumoOrigin.y, uz);
        }
    }
}
