// ===========================================================
// Wardrive System - Visualización en tiempo real (Aguascalientes)
// ===========================================================

// Crear mapa centrado en Aguascalientes (lat, lon)
const map = L.map('map').setView([21.8823, -102.2826], 13);

// Fondo oscuro profesional (Stadia Maps)
L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
  maxZoom: 20,
  attribution:
    '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> | © OpenStreetMap contributors',
}).addTo(map);

// Capas para puntos y zonas (los clústeres van detrás)
const markerLayer = L.layerGroup().addTo(map);
const clusterLayer = L.layerGroup().addTo(map);
const insecureTypes = new Set(['OPEN', 'WEP']);
let viewportLocked = false;

// ===========================================================
// Función principal: obtener datos desde el backend Flask
// ===========================================================
async function fetchNetworks() {
  try {
    console.log('[INFO] Solicitando /api/networks ...');
    const response = await fetch('/api/networks');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const payload = await response.json();
    const networks = payload.networks || [];
    const netCount = networks.length;
    const cluCount = payload.clusters?.length || 0;
    console.log(`[INFO] Recibidos ${netCount} redes y ${cluCount} clústeres.`);

    if (netCount === 0) {
      console.warn('[WARN] No se recibieron redes, esperando próxima actualización...');
    }

    const safetyStatus = computeSafetyStatus(networks);
    renderNetworks(networks);
    renderClusters(payload.clusters || [], safetyStatus);
  } catch (error) {
    console.error('[ERROR] Falló la carga de redes:', error);
  }
}

// ===========================================================
// Renderizado de puntos (redes Wi-Fi)
// ===========================================================
function renderNetworks(networks) {
  markerLayer.clearLayers();
  let firstCoords = null;

  if (!Array.isArray(networks) || networks.length === 0) {
    console.warn('[WARN] No hay redes para renderizar.');
    return;
  }

  networks.forEach((network, idx) => {
    if (typeof network.latitude !== 'number' || typeof network.longitude !== 'number') {
      return;
    }

    // Guardar la primera coordenada válida
    if (!firstCoords) {
      firstCoords = [network.latitude, network.longitude];
    }

    const key = (network.mac && typeof network.mac === 'string' ? network.mac.toUpperCase() : `${network.ssid || ''}::${network.channel || ''}`);
    const sec = String(network.security || '').toUpperCase();
    const color = insecureTypes.has(sec) ? '#dc2626' : '#22c55e'; // rojo insegura, verde segura

    const coords = jitterCoords(network, idx);

    const marker = L.circleMarker([coords[0], coords[1]], {
      radius: 6,
      color,
      fillColor: color,
      fillOpacity: 0.85,
      weight: 1,
    });

    marker.bindTooltip(`
      <b>SSID:</b> ${network.ssid || '(sin nombre)'}<br>
      <b>MAC:</b> ${network.mac || 'N/A'}<br>
      <b>RSSI:</b> ${network.rssi ?? '?'} dBm<br>
      <b>Seguridad:</b> ${network.security || 'Desconocida'}<br>
      <b>Canal:</b> ${network.channel ?? '?'}<br>
      <b>Dispositivo:</b> ${network.device_id || 'N/A'}
    `);

    marker.addTo(markerLayer);
  });

  // Centrar el mapa en el primer punto recibido (solo una vez)
  if (firstCoords && !viewportLocked) {
    map.setView(firstCoords, 15);
    viewportLocked = true;
    console.log(`[INFO] Mapa centrado en primera coordenada: ${firstCoords}`);
  }

  console.log(`[INFO] Renderizadas ${networks.length} redes.`);
}

// ===========================================================
// Generar un resumen corto a partir de los clusters inseguros
// ===========================================================
function renderClusterSummary(clusters) {
  if (!Array.isArray(clusters) || clusters.length === 0) {
    return 'Sin zonas de riesgo detectadas.';
  }
  const sorted = [...clusters].sort((a, b) => (b.count || 0) - (a.count || 0));
  const top = sorted.slice(0, 3);
  const parts = top.map((c, idx) => {
    const lat = typeof c.avg_latitude === 'number' ? c.avg_latitude.toFixed(5) : '?';
    const lon = typeof c.avg_longitude === 'number' ? c.avg_longitude.toFixed(5) : '?';
    return `${idx + 1}) ${c.count} redes en (${lat}, ${lon})`;
  });
  const totalInsecure = clusters.reduce((acc, c) => acc + (c.count || 0), 0);
  return `Zonas de riesgo detectadas: ${parts.join('; ')}. Total redes inseguras: ${totalInsecure}.`;
}

// ===========================================================
// Estado de seguridad (seguras vs inseguras) para colorear capas
// ===========================================================
function computeSafetyStatus(networks) {
  let insecure = 0;
  let secure = 0;
  networks.forEach((n) => {
    const sec = String(n.security || '').toUpperCase();
    if (insecureTypes.has(sec)) insecure += 1;
    else secure += 1;
  });
  if (insecure > secure) {
    return { color: '#dc2626', insecure, secure }; // rojo
  }
  if (secure > insecure) {
    return { color: '#22c55e', insecure, secure }; // verde
  }
  // empate o sin datos
  return { color: '#f59e0b', insecure, secure }; // ámbar
}

// ===========================================================
// Renderizado de clústeres DBSCAN
// ===========================================================
function renderClusters(clusters, safetyStatus) {
  const container = document.querySelector('#cluster-list');
  if (!container) return;
  clusterLayer.clearLayers();

  if (!Array.isArray(clusters) || clusters.length === 0) {
    container.innerHTML = '<p>No hay clústeres inseguros detectados.</p>';
    return;
  }

  const summary = renderClusterSummary(clusters);

  const items = clusters.map((cluster) => {
    const avgRssi = typeof cluster.avg_rssi === 'number'
      ? cluster.avg_rssi.toFixed(1)
      : 'n/a';
    const lat = cluster.avg_latitude?.toFixed(5) ?? 'n/a';
    const lon = cluster.avg_longitude?.toFixed(5) ?? 'n/a';
    const sampleText = Array.isArray(cluster.samples)
      ? cluster.samples.slice(0, 5).map((s) => `${s.ssid} (${s.security || '?'})`).join('<br>')
      : '';
    return `
      <li>
        <b>Cluster ${cluster.cluster}</b><br>
        Redes: ${cluster.count}<br>
        RSSI prom: ${avgRssi} dBm<br>
        Posición: (${lat}, ${lon})<br>
        ${sampleText ? `Ejemplos:<br>${sampleText}` : ''}
      </li>`;
  });

  container.innerHTML = `<p>${summary}</p><ul>${items.join('')}</ul>`;

  // Pinta áreas circulares en el mapa para zonas inseguras
  clusters.forEach((cluster, idx) => {
    if (typeof cluster.avg_latitude !== 'number' || typeof cluster.avg_longitude !== 'number') {
      return;
    }
    const radiusMeters = Math.min(400, 80 + cluster.count * 20); // radio acorde al tamaño del clúster
    const areaColor = clusterColor(idx);
    const circle = L.circle([cluster.avg_latitude, cluster.avg_longitude], {
      radius: radiusMeters,
      color: areaColor,
      fillColor: areaColor,
      fillOpacity: 0.12,
      weight: 1,
      interactive: false, // no bloquea los tooltips de los puntos
    });
    const sampleText = Array.isArray(cluster.samples)
      ? cluster.samples.slice(0, 5).map((s) => `${s.ssid} (${s.security || '?'})`).join('<br>')
      : '';
    circle.bindTooltip(
      `Cluster ${cluster.cluster} · Redes: ${cluster.count}<br>${sampleText}`,
      { sticky: true }
    );
    circle.addTo(clusterLayer);
    if (circle.bringToBack) circle.bringToBack();
  });
}

// ===========================================================
// Generar colores distintos por cluster
// ===========================================================
function clusterColor(index) {
  const palette = ['#2563eb', '#eab308', '#8b5cf6', '#06b6d4', '#f97316', '#0ea5e9', '#c084fc'];
  if (index < palette.length) return palette[index];
  // fallback aleatorio para índices mayores
  const hue = (index * 47) % 360;
  return `hsl(${hue}, 80%, 55%)`;
}

// ===========================================================
// Jitter para evitar solapamiento de puntos (determinista)
// ===========================================================
function jitterCoords(network, idx) {
  const key = (network.mac && typeof network.mac === 'string'
    ? network.mac.toUpperCase()
    : `${network.ssid || ''}::${network.channel || ''}::${idx}`);
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = key.charCodeAt(i) + ((hash << 5) - hash);
    hash |= 0;
  }
  const angle = (Math.abs(hash) % 360) * (Math.PI / 180);
  const radius = (Math.abs(hash) % 7) * 0.00001; // ~0 a 7e-5 grados (~0-8 m)
  const lat = network.latitude + Math.cos(angle) * radius;
  const lon = network.longitude + Math.sin(angle) * radius;
  return [lat, lon];
}

// ===========================================================
// Leyenda (colores de seguridad)
// ===========================================================
function renderLegend() {
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const div = L.DomUtil.create('div', 'legend');
    div.innerHTML = `
      <h4>Referencias de color</h4>
      <p><span class="dot insecure"></span> Red insegura (OPEN/WEP)</p>
      <p><span class="dot secure"></span> Red segura (WPA/WPA2/WPA3)</p>
      <p>Las zonas usan colores aleatorios por clúster.</p>
    `;
    return div;
  };
  legend.addTo(map);
}

// ===========================================================
// Inicialización del mapa
// ===========================================================
renderLegend();
fetchNetworks();

// Refrescar cada 10 segundos para sentirlo en "tiempo real"
setInterval(fetchNetworks, 10000);
