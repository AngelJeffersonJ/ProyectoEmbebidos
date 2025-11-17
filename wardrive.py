#!/usr/bin/env python
"""
wardrive.py

Flask "single-file" entrypoint for the Wardrive project.

Rutas expuestas:
 - GET  /           -> UI (index.html must estar en templates/)
 - POST /api/samples -> Recibe muestras desde el Pico (JSON)
 - GET  /api/networks -> Devuelve todas las redes y clusters calculados

Persistencia ligera:
 - Guarda cada muestra como JSONL en storage/offline_buffer.jsonl

Clustering:
 - Si sklearn está instalado, calcula DBSCAN (haversine) sobre redes INSEGURAS (OPEN/WEP).
 - Si sklearn NO está instalado, devuelve clusters = [] sin error.

Config (opcional):
 - Coloca un .env en la raíz con DEBUG=1 o SERVER_HOST/PORT si quieres cambiarlos.
"""

from __future__ import annotations
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

# Intenta cargar dotenv si existe (opcional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import os

# Optional ML imports (scikit-learn)
try:
    from math import radians
    import numpy as np
    from sklearn.cluster import DBSCAN
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False

# Config
STORAGE_DIR = Path("storage")
STORAGE_DIR.mkdir(exist_ok=True)
BUFFER_FILE = STORAGE_DIR / "offline_buffer.jsonl"

DEBUG = os.getenv("DEBUG", "0") in ("1", "true", "True")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", os.getenv("PORT", 5000)))

# Security labeling we treat as insecure for clustering
INSECURE_TYPES = {"OPEN", "WEP"}

# Logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("wardrive")


# -------------------------
# Storage helpers (JSONL)
# -------------------------
def append_sample(sample: Dict[str, Any]) -> None:
    """Append a JSON-line to buffer file (create if missing)."""
    try:
        sample.setdefault("timestamp", time.time())
        with open(BUFFER_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
    except Exception:
        log.exception("Error appending sample to buffer")


def load_all_samples() -> List[Dict[str, Any]]:
    """Read all JSONL entries and return as list."""
    if not BUFFER_FILE.exists():
        return []
    items: List[Dict[str, Any]] = []
    try:
        with open(BUFFER_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    log.exception("Ignoring malformed line in buffer")
    except Exception:
        log.exception("Error reading buffer file")
    return items


# -------------------------
# Clustering helpers
# -------------------------
def compute_clusters(networks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Compute DBSCAN clusters over insecure networks (latitude/longitude present).
    Returns list of clusters with simple aggregates (avg lat/lon, avg_rssi, count).
    If sklearn not available, returns empty list.
    """
    if not SKLEARN_AVAILABLE:
        log.info("scikit-learn not available -> skipping clustering")
        return []

    # Filter only insecure networks with coords
    points = []
    meta = []
    for n in networks:
        sec = str(n.get("security", "")).upper()
        lat = n.get("latitude")
        lon = n.get("longitude")
        if sec in INSECURE_TYPES and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            points.append((lat, lon))
            meta.append(n)

    if not points:
        return []

    # Convert to radians for haversine metric
    coords = np.array([[radians(p[0]), radians(p[1])] for p in points])

    # DBSCAN with haversine requires eps in radians. eps ~ 0.05 rad ~ 5.5 km
    # For wardrive we probably want ~ 100-200m: 100m / earth_radius(6371000) -> ~0.0000157 rad
    eps_meters = float(os.getenv("DBSCAN_EPS_METERS", "200"))  # default 200m
    eps_radians = eps_meters / 6371000.0
    min_samples = int(os.getenv("DBSCAN_MIN_SAMPLES", "3"))

    db = DBSCAN(eps=eps_radians, metric="haversine", min_samples=min_samples)
    labels = db.fit_predict(coords)

    clusters = {}
    for lbl, m in zip(labels, meta):
        if lbl == -1:
            continue  # noise
        clusters.setdefault(lbl, []).append(m)

    out = []
    for lbl, members in clusters.items():
        avg_lat = sum(m["latitude"] for m in members) / len(members)
        avg_lon = sum(m["longitude"] for m in members) / len(members)
        avg_rssi = sum(m.get("rssi", 0) for m in members) / len(members)
        out.append(
            {
                "cluster": int(lbl),
                "count": len(members),
                "avg_latitude": avg_lat,
                "avg_longitude": avg_lon,
                "avg_rssi": float(round(avg_rssi, 2)),
            }
        )
    return out


# -------------------------
# App / Routes
# -------------------------
def create_app():
    app = Flask(__name__, template_folder="app/templates", static_folder="app/static")
    CORS(app)
    app.logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

    @app.route("/")
    def index():
        # The template index.html should exist in app/templates/
        try:
            return render_template("index.html")
        except Exception:
            # Fallback minimal UI if template missing
            return "<h1>Wardrive System</h1><p>Frontend missing (app/templates/index.html)</p>"

    @app.route("/api/samples", methods=["POST"])
    def receive_sample():
        # Accept JSON POSTs from devices
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "invalid or missing json body"}), 400

        # Normalize some fields (best-effort)
        network = data.get("network", {})
        gps = data.get("gps", {})

        # If gps contains lat/lon under nested keys, ensure floats
        try:
            if "latitude" in gps:
                gps["latitude"] = float(gps["latitude"])
            if "longitude" in gps:
                gps["longitude"] = float(gps["longitude"])
        except Exception:
            pass

        # Ensure network.rssi numeric
        try:
            if "rssi" in network:
                network["rssi"] = int(network["rssi"])
        except Exception:
            pass

        # Compose stored payload (include received timestamp)
        payload = {"network": network, "gps": gps, "received_at": time.time()}
        append_sample(payload)
        log.info("Received sample: SSID=%s MAC=%s", network.get("ssid"), network.get("mac"))
        return jsonify({"status": "ok"}), 201

    @app.route("/api/networks", methods=["GET"])
    def api_networks():
        # Load all samples and flatten to 'networks' list
        samples = load_all_samples()
        networks = []
        for s in samples:
            net = s.get("network", {}).copy()
            gps = s.get("gps", {})
            # Merge gps fields (latitude/longitude) into network for UI convenience
            if isinstance(gps, dict):
                if "latitude" in gps and "longitude" in gps:
                    net["latitude"] = gps["latitude"]
                    net["longitude"] = gps["longitude"]
            # Add timestamp if available
            net["timestamp"] = s.get("received_at", s.get("timestamp"))
            networks.append(net)

        clusters = compute_clusters(networks)
        return jsonify({"count": len(networks), "networks": networks, "clusters": clusters})

    return app


# -------------------------
# Entrypoint
# -------------------------
if __name__ == "__main__":
    log.info("Starting Wardrive server on %s:%s", SERVER_HOST, SERVER_PORT)
    if SKLEARN_AVAILABLE:
        log.info("scikit-learn detected -> DBSCAN clustering enabled")
    else:
        log.info("scikit-learn NOT detected -> clustering disabled (clusters: [])")

    app = create_app()
    # Useful for local dev; in production use a WSGI server
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=DEBUG)
