// SumoMessage.cs
// Deserializable data structs that mirror the Python UnityBridge JSON schema.
// Uses only Unity's built-in JsonUtility (no external packages required).
//
// Attach nothing — this file is pure data classes used by other scripts.

using System;
using UnityEngine;

namespace SumoAAMSim
{
    // ── Top-level frame ──────────────────────────────────────────────────────

    [Serializable]
    public class SumoFrame
    {
        public float            t;
        public VehicleState[]   vehicles;
        public EvtolEvent[]     evtol_events;
        public VertiportState[] vertiports;
    }

    // ── Per-vehicle state ────────────────────────────────────────────────────

    [Serializable]
    public class VehicleState
    {
        /// <summary>SUMO vehicle ID (e.g. "visitor_vp_a_00001")</summary>
        public string id;

        /// <summary>SUMO vType ID: "passenger" or "rental_car"</summary>
        public string vtype;

        /// <summary>SUMO X coordinate (metres, east)</summary>
        public float x;

        /// <summary>SUMO Y coordinate (metres, north — negative = south of origin)</summary>
        public float y;

        /// <summary>Speed in m/s</summary>
        public float speed;

        /// <summary>Compass bearing: 0=north, 90=east, clockwise</summary>
        public float angle;
    }

    // ── eVTOL arrival event ──────────────────────────────────────────────────

    [Serializable]
    public class EvtolEvent
    {
        /// <summary>Vertiport key: "vp_a" or "vp_b"</summary>
        public string vp_id;

        /// <summary>Number of passengers on this flight</summary>
        public int passengers;

        /// <summary>Simulation time of arrival (seconds)</summary>
        public float t;
    }

    // ── Vertiport state ──────────────────────────────────────────────────────

    [Serializable]
    public class VertiportState
    {
        public string id;
        public string name;
        public int    occupancy;
        public int    capacity;
        public int    queue;
        public bool   spillback;

        /// <summary>SUMO X of vertiport parking centre</summary>
        public float cx;

        /// <summary>SUMO Y of vertiport parking centre (negative = south)</summary>
        public float cy;
    }
}
