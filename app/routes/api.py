from __future__ import annotations

from flask import Blueprint, request, jsonify

try:
    import wardrive as monolith  # reutiliza la lógica del entrypoint principal
except Exception:  # pragma: no cover - wardrive.py no disponible
    monolith = None

api_bp = Blueprint('api', __name__)


def _core():
    if monolith is None:
        raise RuntimeError('wardrive.py no está disponible; usa el entrypoint monolítico.')
    return monolith


@api_bp.route('/samples', methods=['POST'])
def receive_sample():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'no data'}), 400
    try:
        core = _core()
    except RuntimeError as exc:
        return jsonify({'error': str(exc)}), 503

    try:
        normalized = core.normalize_sample(data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    core.storage_queue.append(normalized)
    published = False
    if core.adafruit_client.is_configured:
        try:
            core.adafruit_client.publish(normalized)
            published = True
        except Exception:
            core.log.exception('Failed to publish sample to Adafruit IO (blueprint)')
    if not published:
        core.offline_buffer.append(normalized)
    else:
        core.wardrive_service.sync_offline_buffer()
    return jsonify({'status': 'ok', 'adafruit_published': published})


@api_bp.route('/networks')
def get_networks():
    try:
        core = _core()
    except RuntimeError as exc:
        return jsonify({'error': str(exc)}), 503

    records, source = core.wardrive_service.fetch_networks()
    clusters = core.compute_clusters(records)
    return jsonify({'count': len(records), 'source': source, 'networks': records, 'clusters': clusters})
