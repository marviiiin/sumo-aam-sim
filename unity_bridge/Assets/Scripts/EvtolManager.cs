// EvtolManager.cs
// Animates eVTOL arrival and departure sequences in Unity.
//
// On each EvtolEvent received:
//   • Spawns the eVTOL prefab at altitude above the correct vertiport.
//   • Plays a descend coroutine (lands on the pad).
//   • Holds briefly, plays a particle burst (optional).
//   • Ascends and despawns.
//
// Setup:
//   1. Add this component to the SimManager GameObject.
//   2. Assign evtolPrefab (a drone/helicopter mesh, or a cyan capsule).
//   3. Assign trafficManager so we can reuse its SumoToUnity() transform.
//   4. Optionally assign a landingParticlePrefab for dust/rotor effects.

using System.Collections;
using System.Collections.Generic;
using UnityEngine;

namespace SumoAAMSim
{
    public class EvtolManager : MonoBehaviour
    {
        // ── Inspector ─────────────────────────────────────────────────────────

        [Header("Prefabs")]
        public GameObject evtolPrefab;
        public GameObject landingParticlePrefab;   // optional — plays on touchdown

        [Header("References")]
        [Tooltip("Needed for the coordinate transform")]
        public TrafficManager trafficManager;

        [Header("Animation")]
        public float altitudeMetres  = 80f;
        public float descentSeconds  = 8f;
        public float holdSeconds     = 5f;
        public float ascentSeconds   = 8f;

        // ── Vertiport ground positions (SUMO coordinates) ─────────────────────
        // Must match coordinate_map.py _VP_SUMO_CENTRES.
        private static readonly Dictionary<string, Vector2> _vpSumoCentres = new()
        {
            { "vp_a", new Vector2(300f, -255f) },
            { "vp_b", new Vector2(950f, -255f) },
        };

        // ── Public API ────────────────────────────────────────────────────────

        public void OnFrame(SumoFrame frame)
        {
            if (frame.evtol_events == null) return;
            foreach (var ev in frame.evtol_events)
                StartCoroutine(ArrivalSequence(ev));
        }

        // ── Animation coroutine ───────────────────────────────────────────────

        private IEnumerator ArrivalSequence(EvtolEvent ev)
        {
            if (!_vpSumoCentres.TryGetValue(ev.vp_id, out Vector2 sumoXY))
            {
                Debug.LogWarning($"[EvtolManager] Unknown vertiport id: {ev.vp_id}");
                yield break;
            }

            // Spawn at altitude
            Vector3 ground = trafficManager.SumoToUnity(sumoXY.x, sumoXY.y);
            Vector3 sky    = ground + Vector3.up * altitudeMetres;

            GameObject evtol = SpawnEvtol(sky, ev);
            Debug.Log($"[EvtolManager] eVTOL arriving at {ev.vp_id}  pax={ev.passengers}");

            // ── Descend ──────────────────────────────────────────────────────
            yield return AnimateMove(evtol, sky, ground, descentSeconds);

            // ── Touch-down effect ─────────────────────────────────────────────
            if (landingParticlePrefab != null)
            {
                var fx = Instantiate(landingParticlePrefab, ground, Quaternion.identity);
                Destroy(fx, 3f);
            }

            // ── Hold on pad ───────────────────────────────────────────────────
            yield return new WaitForSeconds(holdSeconds);

            // ── Ascend ────────────────────────────────────────────────────────
            yield return AnimateMove(evtol, ground, sky, ascentSeconds);

            Debug.Log($"[EvtolManager] eVTOL departed from {ev.vp_id}");
            Destroy(evtol);
        }

        private IEnumerator AnimateMove(
            GameObject obj, Vector3 from, Vector3 to, float duration)
        {
            float elapsed = 0f;
            while (elapsed < duration)
            {
                if (obj == null) yield break;
                elapsed += Time.deltaTime;
                float t = Mathf.SmoothStep(0f, 1f, elapsed / duration);
                obj.transform.position = Vector3.Lerp(from, to, t);
                yield return null;
            }
            if (obj != null)
                obj.transform.position = to;
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private GameObject SpawnEvtol(Vector3 position, EvtolEvent ev)
        {
            GameObject go = (evtolPrefab != null)
                ? Instantiate(evtolPrefab, position, Quaternion.identity)
                : CreateEvtolPlaceholder();

            go.name = $"eVTOL_{ev.vp_id}_{ev.t:F0}";
            go.transform.position = position;
            go.transform.SetParent(transform, worldPositionStays: true);
            return go;
        }

        private static GameObject CreateEvtolPlaceholder()
        {
            // Rotors suggestion: four small cubes around a central body
            var root  = new GameObject("eVTOL_placeholder");
            var body  = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            body.transform.SetParent(root.transform);
            body.transform.localScale    = new Vector3(3f, 1f, 3f);
            body.transform.localPosition = Vector3.zero;

            var rend  = body.GetComponent<Renderer>();
            var mat   = new Material(Shader.Find("Standard"));
            mat.color = new Color(0f, 0.8f, 1f, 0.9f);    // cyan
            rend.material = mat;

            Destroy(body.GetComponent<CapsuleCollider>());

            // Simple "rotors"
            for (int i = 0; i < 4; i++)
            {
                float angle = i * 90f * Mathf.Deg2Rad;
                var rotor   = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                rotor.transform.SetParent(root.transform);
                rotor.transform.localScale    = new Vector3(1.5f, 0.1f, 1.5f);
                rotor.transform.localPosition = new Vector3(
                    Mathf.Cos(angle) * 2.5f, 0.5f, Mathf.Sin(angle) * 2.5f);
                Destroy(rotor.GetComponent<CapsuleCollider>());
            }

            return root;
        }
    }
}
