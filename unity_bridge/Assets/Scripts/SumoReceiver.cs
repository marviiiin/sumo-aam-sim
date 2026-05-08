// SumoReceiver.cs
// Listens on a UDP port, deserialises incoming SumoFrame JSON packets,
// and distributes data to TrafficManager and EvtolManager.
//
// Setup:
//   1. Add this component to a GameObject in your scene (e.g. "SimManager").
//   2. Assign TrafficManager and EvtolManager references in the Inspector.
//   3. Make sure listenPort matches UnityBridge.UNITY_PORT (default 9000).
//
// The UDP receive loop runs on a background thread; dispatching to Unity
// main-thread components is done via a thread-safe queue.

using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Concurrent;
using UnityEngine;

namespace SumoAAMSim
{
    public class SumoReceiver : MonoBehaviour
    {
        [Header("Network")]
        [Tooltip("UDP port to listen on (must match UnityBridge.UNITY_PORT in Python)")]
        public int listenPort = 9000;

        [Header("References")]
        public TrafficManager  trafficManager;
        public EvtolManager    evtolManager;
        public VertiportHUD    vertiportHUD;    // optional — assign if HUD exists

        [Header("Debug")]
        public bool logEveryFrame = false;

        // ── Threading ─────────────────────────────────────────────────────────

        private UdpClient                          _udpClient;
        private Thread                             _receiveThread;
        private ConcurrentQueue<SumoFrame>         _frameQueue = new();
        private volatile bool                      _running;

        // ── Unity lifecycle ───────────────────────────────────────────────────

        void Start()
        {
            try
            {
                _udpClient = new UdpClient(listenPort);
                _running   = true;
                _receiveThread = new Thread(ReceiveLoop) { IsBackground = true };
                _receiveThread.Start();
                Debug.Log($"[SumoReceiver] Listening on UDP port {listenPort}");
            }
            catch (Exception e)
            {
                Debug.LogError($"[SumoReceiver] Failed to open UDP port {listenPort}: {e.Message}");
            }
        }

        void Update()
        {
            // Drain the queue on the main thread (safe for Unity API calls)
            while (_frameQueue.TryDequeue(out SumoFrame frame))
            {
                if (logEveryFrame)
                    Debug.Log($"[SumoReceiver] t={frame.t:F1}s  veh={frame.vehicles?.Length}");

                trafficManager?.OnFrame(frame);
                evtolManager?.OnFrame(frame);
                vertiportHUD?.OnFrame(frame);
            }
        }

        void OnDestroy()
        {
            _running = false;
            _udpClient?.Close();
            _receiveThread?.Join(500);
        }

        // ── Background receive loop ───────────────────────────────────────────

        private void ReceiveLoop()
        {
            IPEndPoint remote = new IPEndPoint(IPAddress.Any, 0);
            while (_running)
            {
                try
                {
                    byte[] data = _udpClient.Receive(ref remote);
                    string json = Encoding.UTF8.GetString(data);
                    SumoFrame frame = JsonUtility.FromJson<SumoFrame>(json);
                    if (frame != null)
                        _frameQueue.Enqueue(frame);
                }
                catch (SocketException)
                {
                    // Socket closed on shutdown — exit loop cleanly
                    break;
                }
                catch (Exception e)
                {
                    Debug.LogWarning($"[SumoReceiver] Parse error: {e.Message}");
                }
            }
        }
    }
}
