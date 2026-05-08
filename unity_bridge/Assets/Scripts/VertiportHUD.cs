// VertiportHUD.cs
// Displays real-time parking occupancy, queue length, and spillback status
// as world-space billboarded labels above each vertiport.
//
// Requires: Unity UI (TextMesh Pro or legacy UI Text).
// This implementation uses legacy UI Text world-space canvas for simplicity;
// swap for TextMeshPro if you have the package installed.
//
// Setup:
//   1. Add this component to the SimManager GameObject.
//   2. Assign trafficManager (for coordinate transform).
//   3. Labels are created automatically at runtime.

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace SumoAAMSim
{
    public class VertiportHUD : MonoBehaviour
    {
        [Header("References")]
        public TrafficManager trafficManager;
        public Camera         mainCamera;

        [Header("Label settings")]
        public float   labelAltitude   = 25f;     // metres above ground
        public float   labelScale      = 0.05f;   // world-space canvas scale
        public Color   normalColor     = Color.green;
        public Color   spillbackColor  = Color.red;
        public Color   nearFullColor   = Color.yellow;

        private Dictionary<string, (Canvas canvas, Text text)> _labels = new();

        // ── Public API ────────────────────────────────────────────────────────

        public void OnFrame(SumoFrame frame)
        {
            if (frame.vertiports == null) return;
            foreach (var vp in frame.vertiports)
                UpdateLabel(vp);
        }

        // ── Label management ──────────────────────────────────────────────────

        private void UpdateLabel(VertiportState vp)
        {
            if (!_labels.TryGetValue(vp.id, out var label))
                label = CreateLabel(vp);

            float pct   = (vp.capacity > 0) ? (float)vp.occupancy / vp.capacity : 0f;
            string body = $"<b>{vp.name}</b>\n"
                        + $"Parking  {vp.occupancy}/{vp.capacity}  ({pct:P0})\n"
                        + $"Queue    {vp.queue} veh\n"
                        + (vp.spillback ? "⚠  SPILLBACK" : "OK");

            label.text.text  = body;
            label.text.color = vp.spillback ? spillbackColor
                             : (pct > 0.85f ? nearFullColor : normalColor);
        }

        private (Canvas, Text) CreateLabel(VertiportState vp)
        {
            // World-space canvas
            var canvasGo = new GameObject($"HUD_{vp.id}");
            canvasGo.transform.SetParent(transform, false);

            var canvas              = canvasGo.AddComponent<Canvas>();
            canvas.renderMode       = RenderMode.WorldSpace;
            canvas.worldCamera      = mainCamera ?? Camera.main;

            var rt                  = canvasGo.GetComponent<RectTransform>();
            rt.sizeDelta            = new Vector2(400, 160);
            canvasGo.transform.localScale = Vector3.one * labelScale;

            // Position above vertiport
            Vector3 world = trafficManager.SumoToUnity(vp.cx, vp.cy);
            world.y      += labelAltitude;
            canvasGo.transform.position = world;

            // Text child
            var textGo = new GameObject("Label");
            textGo.transform.SetParent(canvasGo.transform, false);
            var text               = textGo.AddComponent<Text>();
            text.font              = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize          = 28;
            text.alignment         = TextAnchor.UpperLeft;
            text.color             = normalColor;
            text.supportRichText   = true;
            var trText             = textGo.GetComponent<RectTransform>();
            trText.sizeDelta       = rt.sizeDelta;

            _labels[vp.id] = (canvas, text);
            return (canvas, text);
        }

        // ── Billboard: always face camera ─────────────────────────────────────

        void LateUpdate()
        {
            Camera cam = mainCamera ?? Camera.main;
            if (cam == null) return;

            foreach (var (canvas, _) in _labels.Values)
            {
                if (canvas != null)
                    canvas.transform.LookAt(
                        canvas.transform.position + cam.transform.rotation * Vector3.forward,
                        cam.transform.rotation * Vector3.up);
            }
        }

        void OnDestroy()
        {
            foreach (var (canvas, _) in _labels.Values)
                if (canvas != null) Destroy(canvas.gameObject);
            _labels.Clear();
        }
    }
}
