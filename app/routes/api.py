from flask import Blueprint, request, jsonify

api_bp = Blueprint('api', __name__)

# Memoria temporal (en producción se usaría JSON o DB)
NETWORKS = []

@api_bp.route('/api/samples', methods=['POST'])
def receive_sample():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'no data'}), 400
    NETWORKS.append(data)
    return jsonify({'status': 'ok', 'count': len(NETWORKS)})

@api_bp.route('/api/networks')
def get_networks():
    items = []
    for item in NETWORKS:
        net = item.get('network', {})
        gps = item.get('gps', {})
        net.update(gps)
        items.append(net)
    return jsonify({'count': len(items), 'networks': items, 'clusters': []})
