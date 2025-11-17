// ===========================================================
// Wardrive System - Visualización en tiempo real (Aguascalientes)
// ===========================================================

// 🗺️ Crear mapa centrado en Aguascalientes (lat, lon)
const map = L.map('map').setView([21.8823, -102.2826], 13);

// 🌍 Fondo oscuro profesional (Stadia Maps)
L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
  maxZoom: 20,
  attribution:
    '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> | © OpenStreetMap contributors',
}).addTo(map);

// Capa para los marcadores dinámicos
const markerLayer = L.layerGroup().addTo(map);
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
    const netCount = payload.networks?.length || 0;
    const cluCount = payload.clusters?.length || 0;
    console.log(`[INFO] Recibidos ${netCount} redes y ${cluCount} clústeres.`);

    if (netCount === 0) {
      console.warn('[WARN] No se recibieron redes, esperando próxima actualización...');
    }

    renderNetworks(payload.networks || []);
    renderClusters(payload.clusters || []);
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

  networks.forEach((network) => {
    if (typeof network.latitude !== 'number' || typeof network.longitude !== 'number') {
      return;
    }

    // Guardar la primera coordenada válida
    if (!firstCoords) {
      firstCoords = [network.latitude, network.longitude];
    }

    const secure = !insecureTypes.has(String(network.security).toUpperCase());
    const color = secure ? '#22c55e' : '#dc2626'; // verde (segura) / rojo (insegura)

    const marker = L.circleMarker([network.latitude, network.longitude], {
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
      <b>Canal:</b> ${network.channel ?? '?'}
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
// Renderizado de clústeres DBSCAN
// ===========================================================
function renderClusters(clusters) {
  const container = document.querySelector('#cluster-list');
  if (!container) return;

  if (!Array.isArray(clusters) || clusters.length === 0) {
    container.innerHTML = '<p>No hay clústeres inseguros detectados.</p>';
    return;
  }

  const items = clusters.map((cluster) => {
    const avgRssi = typeof cluster.avg_rssi === 'number'
      ? cluster.avg_rssi.toFixed(1)
      : 'n/a';
    const lat = cluster.avg_latitude?.toFixed(5) ?? 'n/a';
    const lon = cluster.avg_longitude?.toFixed(5) ?? 'n/a';
    return `
      <li>
        <b>Cluster ${cluster.cluster}</b><br>
        Redes: ${cluster.count}<br>
        RSSI prom: ${avgRssi} dBm<br>
        Posición: (${lat}, ${lon})
      </li>`;
  });

  container.innerHTML = `<ul>${items.join('')}</ul>`;
}

// ===========================================================
// Leyenda (colores de seguridad)
// ===========================================================
function renderLegend() {
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const div = L.DomUtil.create('div', 'legend');
    div.innerHTML = `
      <h4>Estado de seguridad</h4>
      <p><span class="dot insecure"></span> Insegura (Open/WEP)</p>
      <p><span class="dot secure"></span> Segura (WPA/WPA2/WPA3)</p>
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

// Refrescar cada 2 minutos (120000 ms)
setInterval(fetchNetworks, 120000);
