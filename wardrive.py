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
import time
import logging
from pathlib import Path
from typing import List, Dict, Any

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

# Intenta cargar dotenv si existe (opcional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import os
from app.models.network import NetworkObservation
from app.services.adafruit_client import AdafruitClient
from app.services.storage_queue import StorageQueue
from app.services.wardrive_service import WardriveService

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

DEBUG = os.getenv("DEBUG", "0") in ("1", "true", "True")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", os.getenv("PORT", 5000)))
AIO_USERNAME = os.getenv("AIO_USERNAME", "")
AIO_KEY = os.getenv("AIO_KEY", "")
AIO_FEED_KEY = os.getenv("AIO_FEED_KEY", "wardrive")
STORAGE_PATH = Path(os.getenv("STORAGE_PATH", STORAGE_DIR / "data.jsonl"))
OFFLINE_BUFFER_PATH = Path(os.getenv("OFFLINE_BUFFER_PATH", STORAGE_DIR / "offline_buffer.jsonl"))

# Security labeling we treat as insecure for clustering
INSECURE_TYPES = {"OPEN", "WEP"}

# Logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("wardrive")
storage_queue = StorageQueue(str(STORAGE_PATH))
offline_buffer = StorageQueue(str(OFFLINE_BUFFER_PATH))
adafruit_client = AdafruitClient(AIO_USERNAME, AIO_KEY, AIO_FEED_KEY)
wardrive_service = WardriveService(adafruit_client, storage_queue, offline_buffer)

if adafruit_client.is_configured:
    log.info("Adafruit IO client enabled for feed '%s'", AIO_FEED_KEY)
else:
    log.warning("Adafruit IO credentials missing -> running in offline/demo mode")


def normalize_sample(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten payloads from Pico devices into NetworkObservation dictionaries."""
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")

    flattened: Dict[str, Any] = {}
    network = data.get("network")
    if isinstance(network, dict):
        flattened.update(network)
    else:
        for field in ("ssid", "mac", "channel", "rssi", "security", "timestamp"):
            if field in data:
                flattened[field] = data[field]

    gps = data.get("gps")
    lat_source = None
    lon_source = None
    if isinstance(gps, dict):
        lat_source = gps.get("latitude")
        lon_source = gps.get("longitude")
    lat_source = lat_source if lat_source is not None else data.get("latitude")
    lon_source = lon_source if lon_source is not None else data.get("longitude")
    try:
        flattened["latitude"] = float(lat_source)
        flattened["longitude"] = float(lon_source)
    except (TypeError, ValueError):
        raise ValueError("missing GPS coordinates (latitude/longitude)")

    if "channel" in flattened:
        try:
            flattened["channel"] = int(flattened["channel"])
        except (TypeError, ValueError):
            flattened["channel"] = 1
    if "rssi" in flattened:
        try:
            flattened["rssi"] = int(flattened["rssi"])
        except (TypeError, ValueError):
            flattened["rssi"] = -100
    if "security" in flattened and isinstance(flattened["security"], str):
        flattened["security"] = flattened["security"].upper()

    observation = NetworkObservation.from_payload(flattened)
    normalized = observation.to_dict()
    normalized["received_at"] = data.get("timestamp") or time.time()

    if isinstance(gps, dict):
        for key in ("satellites", "hdop"):
            if key in gps:
                normalized[key] = gps[key]
    return normalized


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
        # Resumen con SSID únicos
        seen_ssid = set()
        samples = []
        for m in members:
            ssid_val = (m.get("ssid") or "(sin nombre)").strip()
            sec_val = m.get("security") or "Desconocida"
            key = (ssid_val, sec_val)
            if key in seen_ssid:
                continue
            seen_ssid.add(key)
            samples.append({"ssid": ssid_val, "security": sec_val, "rssi": m.get("rssi")})
            if len(samples) >= 8:
                break
        out.append(
            {
                "cluster": int(lbl),
                "count": len(members),
                "avg_latitude": avg_lat,
                "avg_longitude": avg_lon,
                "avg_rssi": float(round(avg_rssi, 2)),
                "samples": samples,
            }
        )
    return out


def dedupe_networks(networks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the freshest (or strongest) sample per network key."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for net in networks:
        mac = str(net.get("mac", "")).strip().upper()
        ssid = str(net.get("ssid", "")).strip()
        chan = net.get("channel")
        key = mac or f"{ssid}::{chan}"
        if not key:
            continue
        prev = by_key.get(key)
        if not prev:
            by_key[key] = net
            continue
        # Prefer newer timestamp, else higher RSSI
        prev_ts = prev.get("timestamp", 0)
        curr_ts = net.get("timestamp", 0)
        if curr_ts > prev_ts:
            by_key[key] = net
            continue
        prev_rssi = prev.get("rssi", -9999)
        curr_rssi = net.get("rssi", -9999)
        if curr_ts == prev_ts and curr_rssi > prev_rssi:
            by_key[key] = net
    return list(by_key.values())


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

        try:
            normalized = normalize_sample(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        storage_queue.append(normalized)
        published = False
        if adafruit_client.is_configured:
            try:
                adafruit_client.publish(normalized)
                published = True
            except Exception:
                log.exception("Failed to publish sample to Adafruit IO")
        if not published:
            offline_buffer.append(normalized)
        else:
            # Try to flush any pending backlog so multi-equipo pruebas stay in sync
            wardrive_service.sync_offline_buffer()

        log.info(
            "Received sample: SSID=%s MAC=%s (adafruit=%s)",
            normalized.get("ssid"),
            normalized.get("mac"),
            "ok" if published else "pending",
        )
        return jsonify({"status": "ok", "adafruit_published": published}), 201

    @app.route("/api/networks", methods=["GET"])
    def api_networks():
        records, source = wardrive_service.fetch_networks()
        deduped = dedupe_networks(records)
        clusters = compute_clusters(deduped)
        return jsonify({"count": len(deduped), "source": source, "networks": deduped, "clusters": clusters})

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
