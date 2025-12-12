// ===========================================================
// Wardrive System - Visualizacion en tiempo real (Aguascalientes)
// ===========================================================

// Crear mapa centrado en Aguascalientes (lat, lon)
const map = L.map('map').setView([21.8823, -102.2826], 13);

// Fondo oscuro profesional (Stadia Maps)
L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
  maxZoom: 20,
  attribution:
    '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> | © OpenStreetMap contributors',
}).addTo(map);

// Capas para puntos y zonas
const markerLayer = L.layerGroup().addTo(map);
const clusterLayer = L.layerGroup().addTo(map);
const insecureTypes = new Set(['OPEN', 'WEP']);
const clusterColorCache = new Map();
let viewportLocked = false;
let currentNetworks = [];

// ===========================================================
// Utilidades geograficas
// ===========================================================
function metersDistance(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * (Math.PI / 180);
  const dLon = (lon2 - lon1) * (Math.PI / 180);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function radiusForCluster(count) {
  return Math.min(400, 80 + (count || 1) * 20);
}

function offsetByMeters(lat, lon, meters, angleRad) {
  const dLat = (meters / 111320) * Math.cos(angleRad);
  const dLon = (meters / (111320 * Math.cos(lat * Math.PI / 180))) * Math.sin(angleRad);
  return [lat + dLat, lon + dLon];
}

function findNonOverlappingPosition(baseLat, baseLon, radiusMeters, placed, angleSeed) {
  if (!Number.isFinite(baseLat) || !Number.isFinite(baseLon)) return [baseLat, baseLon];
  const margin = 20; // separacion minima entre circulos
  const golden = 137.5 * (Math.PI / 180);
  let angle = angleSeed;
  let dist = 0;
  for (let i = 0; i < 40; i += 1) {
    const [lat, lon] = offsetByMeters(baseLat, baseLon, dist, angle);
    const overlaps = placed.some((p) => metersDistance(lat, lon, p.lat, p.lon) < (radiusMeters + p.radius + margin));
    if (!overlaps) return [lat, lon];
    dist += Math.max(40, radiusMeters * 0.35);
    angle += golden;
  }
  return [baseLat, baseLon];
}

// ===========================================================
// Funci�n principal: obtener datos desde el backend Flask
// ===========================================================
async function fetchNetworks() {
  try {
    const response = await fetch('/api/networks');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const payload = await response.json();
    const networks = payload.networks || [];
    const clusterAlgorithm = payload.cluster_algorithm || 'dbscan';
    currentNetworks = networks;

    const safetyStatus = computeSafetyStatus(networks);
    renderNetworks(networks);
    renderClusters(payload.clusters || [], safetyStatus, clusterAlgorithm, networks);
  } catch (error) {
    console.error('[ERROR] Fallo la carga de redes:', error);
  }
}

// ===========================================================
// Renderizado de puntos (redes Wi-Fi)
// ===========================================================
function renderNetworks(networks) {
  markerLayer.clearLayers();
  let firstCoords = null;

  if (!Array.isArray(networks) || networks.length === 0) {
    return;
  }

  networks.forEach((network, idx) => {
    if (typeof network.latitude !== 'number' || typeof network.longitude !== 'number') {
      return;
    }

    if (!firstCoords) {
      firstCoords = [network.latitude, network.longitude];
    }

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

  if (firstCoords && !viewportLocked) {
    map.setView(firstCoords, 15);
    viewportLocked = true;
  }
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
  return { color: '#f59e0b', insecure, secure }; // ambar
}

// ===========================================================
// Narrativa en lenguaje natural por zona y veredictos
// ===========================================================
function buildZoneVerdict(cluster) {
  const typeLabel = cluster.category === 'secure' ? 'seguras' : cluster.category === 'insecure' ? 'inseguras' : 'mixtas';
  const count = cluster.count || 0;
  const signal = typeof cluster.avg_rssi === 'number' ? cluster.avg_rssi : null;
  const signalText = signal === null
    ? 'senal desconocida'
    : signal > -65 ? 'senal fuerte'
      : signal > -80 ? 'senal media'
        : 'senal debil';

  if (cluster.category === 'secure') {
    if (count >= 10) return `Zona de redes ${typeLabel} densas; riesgo muy bajo (${signalText}).`;
    if (count >= 5) return `Concentracion de redes ${typeLabel}; riesgo bajo (${signalText}).`;
    return `Pocas redes ${typeLabel}; riesgo muy bajo (${signalText}).`;
  }
  if (cluster.category === 'insecure') {
    if (count >= 10) return `Riesgo alto: muchas redes ${typeLabel} juntas (${signalText}).`;
    if (count >= 5) return `Riesgo medio: agrupacion notable de redes ${typeLabel} (${signalText}).`;
    return `Riesgo bajo: pocas redes ${typeLabel} (${signalText}).`;
  }
  // mixtas
  return `Zonas mixtas de redes; vigilar (${signalText}).`;
}

function buildZoneNarratives(clusters, safetyStatus, algorithmUsed) {
  if (!Array.isArray(clusters) || clusters.length === 0) {
    return {
      paragraphs: [],
      zoneVerdicts: [],
      verdict: 'Sin agrupamientos detectados; el mapa se mantiene estable.',
    };
  }

  const paragraphs = clusters.map((cluster) => {
    const lat = typeof cluster.avg_latitude === 'number' ? cluster.avg_latitude.toFixed(5) : 'lat?';
    const lon = typeof cluster.avg_longitude === 'number' ? cluster.avg_longitude.toFixed(5) : 'lon?';
    const typeLabel = cluster.category === 'secure' ? 'seguras' : cluster.category === 'insecure' ? 'inseguras' : 'mixtas';
    const density = cluster.count >= 12 ? `una concentracion muy alta de redes ${typeLabel}`
      : cluster.count >= 7 ? `una concentracion marcada de redes ${typeLabel}`
        : cluster.count >= 4 ? `varias redes ${typeLabel} agrupadas`
          : `pocas redes ${typeLabel} cercanas`;
    const signal = typeof cluster.avg_rssi === 'number' ? cluster.avg_rssi : null;
    const signalText = signal === null
      ? 'sin dato de potencia'
      : signal > -65 ? 'con senal fuerte'
        : signal > -80 ? 'con senal media'
          : 'con senal debil';
    return `Agrupa ${cluster.count} redes ${typeLabel} en (${lat}, ${lon}), ${density} y ${signalText}.`;
  });

  const zoneVerdicts = clusters.map((cluster) => buildZoneVerdict(cluster));

  const insecure = safetyStatus?.insecure ?? 0;
  const secure = safetyStatus?.secure ?? 0;
  let verdict = '';
  if (insecure === 0) {
    verdict = 'Solo hay redes seguras visibles; no se observan riesgos inmediatos.';
  } else if (insecure > secure * 1.5) {
    verdict = 'Predominan las redes inseguras; se recomienda intervencion prioritaria en las zonas marcadas.';
  } else if (insecure > secure) {
    verdict = 'Hay mas redes inseguras que seguras; conviene inspeccion detallada de campo.';
  } else {
    verdict = 'Existen redes inseguras, pero la mayoria parece protegida; mantener vigilancia periodica.';
  }
  if (algorithmUsed && algorithmUsed !== 'none') {
    verdict = `${verdict} Agrupamiento calculado con ${String(algorithmUsed).toUpperCase()}.`;
  }
  return { paragraphs, verdict, zoneVerdicts };
}

// ===========================================================
// Merge de clustres proximos para evitar zonas duplicadas
// ===========================================================
function combineClusters(a, b) {
  const totalCount = (a.count || 0) + (b.count || 0);
  const weightA = (a.count || 0) / Math.max(totalCount, 1);
  const weightB = (b.count || 0) / Math.max(totalCount, 1);
  const avgLat = (a.avg_latitude || 0) * weightA + (b.avg_latitude || 0) * weightB;
  const avgLon = (a.avg_longitude || 0) * weightA + (b.avg_longitude || 0) * weightB;
  const avgRssi = ((a.avg_rssi || 0) * (a.count || 0) + (b.avg_rssi || 0) * (b.count || 0)) / Math.max(totalCount, 1);
  const category = a.category === b.category ? a.category : 'mixed';
  const seen = new Set();
  const samples = [];
  [a.samples || [], b.samples || []].flat().forEach((s) => {
    const key = `${s.ssid || ''}::${s.security || ''}`;
    if (seen.has(key) || samples.length >= 8) return;
    seen.add(key);
    samples.push(s);
  });
  const id = Array.isArray(a.cluster_ids) ? a.cluster_ids.slice() : [a.cluster];
  if (Array.isArray(b.cluster_ids)) id.push(...b.cluster_ids);
  else id.push(b.cluster);
  return {
    cluster: a.cluster,
    cluster_ids: id,
    count: totalCount,
    avg_latitude: avgLat,
    avg_longitude: avgLon,
    avg_rssi: avgRssi,
    samples,
    category,
  };
}

function mergeOverlappingClusters(clusters) {
  const result = [];
  const sorted = [...clusters].sort((a, b) => (b.count || 0) - (a.count || 0));
  sorted.forEach((c) => {
    const r = radiusForCluster(c.count);
    let mergedInto = null;
    for (let i = 0; i < result.length; i += 1) {
      const other = result[i];
      const dist = metersDistance(
        c.avg_latitude || 0,
        c.avg_longitude || 0,
        other.avg_latitude || 0,
        other.avg_longitude || 0
      );
      const rOther = radiusForCluster(other.count);
      if (dist < Math.max(r, rOther)) {
        mergedInto = i;
        break;
      }
    }
    if (mergedInto === null) {
      result.push({ ...c, cluster_ids: [c.cluster] });
    } else {
      result[mergedInto] = combineClusters(result[mergedInto], c);
    }
  });
  return result;
}

// ===========================================================
// Renderizado de cl�steres (DBSCAN o KMeans)
// ===========================================================
function renderClusters(clusters, safetyStatus, algorithmUsed = 'dbscan', networks = []) {
  const container = document.querySelector('#cluster-list');
  if (!container) return;
  clusterLayer.clearLayers();

  const mergedClusters = mergeOverlappingClusters(Array.isArray(clusters) ? clusters : []);

  if (mergedClusters.length === 0) {
    const narrative = buildZoneNarratives([], safetyStatus, algorithmUsed);
    container.innerHTML = `
      <p>No hay cl�steres detectados.</p>
      <p class="verdict"><strong>Veredicto:</strong> ${narrative.verdict}</p>
    `;
    return;
  }

  const narrative = buildZoneNarratives(mergedClusters, safetyStatus, algorithmUsed);
  const items = mergedClusters.map((cluster, idx) => {
    const avgRssi = typeof cluster.avg_rssi === 'number'
      ? cluster.avg_rssi.toFixed(1)
      : 'n/a';
    const lat = cluster.avg_latitude?.toFixed(5) ?? 'n/a';
    const lon = cluster.avg_longitude?.toFixed(5) ?? 'n/a';
    const sampleText = Array.isArray(cluster.samples)
      ? cluster.samples.slice(0, 5).map((s) => `${s.ssid} (${s.security || '?'})`).join('<br>')
      : '';
    const color = getClusterColor(cluster);
    const paragraphText = narrative.paragraphs[idx] || '';
    const zoneVerdict = narrative.zoneVerdicts ? narrative.zoneVerdicts[idx] : '';
    const typeLabel = cluster.category === 'secure' ? 'seguras' : cluster.category === 'insecure' ? 'inseguras' : 'mixtas';
    return `
      <p class="zone-paragraph" data-lat="${lat}" data-lon="${lon}">
        <span class="dot zone-dot" data-lat="${lat}" data-lon="${lon}" style="background:${color}"></span>
        <strong>Zona ${idx + 1}:</strong> ${paragraphText}
        <br><small>Tipo: ${typeLabel} | RSSI prom: ${avgRssi} dBm | Centro: (${lat}, ${lon})</small>
        ${zoneVerdict ? `<br><small><strong>Veredicto zona:</strong> ${zoneVerdict}</small>` : ''}
        ${sampleText ? `<br><small>Ejemplos:<br>${sampleText}</small>` : ''}
      </p>`;
  });

  container.innerHTML = `
    ${items.join('')}
    <p class="verdict"><strong>Veredicto:</strong> ${narrative.verdict}</p>
  `;

  container.querySelectorAll('.zone-paragraph, .zone-dot').forEach((el) => {
    el.addEventListener('click', (evt) => {
      const target = evt.currentTarget;
      const lat = parseFloat(target.getAttribute('data-lat'));
      const lon = parseFloat(target.getAttribute('data-lon'));
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        map.setView([lat, lon], 16);
      }
    });
  });

  // Pinta areas rellenas basadas en los puntos del cluster
  mergedClusters.forEach((cluster) => {
    if (typeof cluster.avg_latitude !== 'number' || typeof cluster.avg_longitude !== 'number') {
      return;
    }
    const radiusMeters = radiusForCluster(cluster.count);
    const areaColor = getClusterColor(cluster);
    const typeLabel = cluster.category === 'secure' ? 'seguras' : cluster.category === 'insecure' ? 'inseguras' : 'mixtas';

    const hull = buildClusterHull(cluster, networks, radiusMeters);
    let shape;
    if (hull && hull.length >= 3) {
      shape = L.polygon(hull, {
        color: areaColor,
        fillColor: areaColor,
        fillOpacity: 0.18,
        weight: 1,
        interactive: true,
      });
    } else {
      shape = L.circle([cluster.avg_latitude, cluster.avg_longitude], {
        radius: radiusMeters,
        color: areaColor,
        fillColor: areaColor,
        fillOpacity: 0.12,
        weight: 1,
        interactive: true,
      });
    }
    const sampleText = Array.isArray(cluster.samples)
      ? cluster.samples.slice(0, 5).map((s) => `${s.ssid} (${s.security || '?'})`).join('<br>')
      : '';
    shape.bindTooltip(
      `Cluster ${Array.isArray(cluster.cluster_ids) ? cluster.cluster_ids.join(',') : cluster.cluster} (${typeLabel}) - Redes: ${cluster.count}<br>${sampleText}`,
      { sticky: true }
    );
    shape.on('click', () => {
      map.setView([cluster.avg_latitude, cluster.avg_longitude], 16);
    });
    shape.addTo(clusterLayer);
    if (shape.bringToBack) shape.bringToBack();
  });
}

// ===========================================================
// Generar colores distintos por cluster (sin rojo o verde)
// ===========================================================
function randomColorExcludingRedGreen() {
  const forbidden = [
    [350, 360], // rojos altos
    [0, 15],    // rojos bajos
    [90, 160],  // verdes
  ];
  for (let i = 0; i < 24; i += 1) {
    const hue = Math.floor(Math.random() * 360);
    const blocked = forbidden.some(([start, end]) => hue >= start && hue <= end);
    if (blocked) continue;
    const saturation = 68 + Math.random() * 22;
    const lightness = 48 + Math.random() * 14;
    return `hsl(${hue}, ${saturation.toFixed(0)}%, ${lightness.toFixed(0)}%)`;
  }
  return 'hsl(210, 80%, 55%)';
}

function clusterKey(cluster) {
  const cat = cluster.category || 'any';
  if (typeof cluster.cluster === 'number') return `cat:${cat}|id:${cluster.cluster}`;
  const lat = typeof cluster.avg_latitude === 'number' ? cluster.avg_latitude.toFixed(3) : 'x';
  const lon = typeof cluster.avg_longitude === 'number' ? cluster.avg_longitude.toFixed(3) : 'y';
  return `cat:${cat}|pos:${lat},${lon}`;
}

function getClusterColor(cluster) {
  const key = clusterKey(cluster);
  if (clusterColorCache.has(key)) return clusterColorCache.get(key);
  const color = randomColorExcludingRedGreen();
  clusterColorCache.set(key, color);
  return color;
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
// Poligono envolvente (convex hull) para rellenar la zona real
// ===========================================================
function buildClusterHull(cluster, networks, radiusMeters) {
  if (!Array.isArray(networks) || networks.length === 0) return null;
  const centerLat = cluster.avg_latitude;
  const centerLon = cluster.avg_longitude;
  const searchRadius = Math.max(radiusMeters * 1.8, 1200); // ampliar cobertura para recorridos largos
  const category = cluster.category || 'mixed';
  const nearbyPoints = [];
  networks.forEach((n, idx) => {
    if (!Number.isFinite(n.latitude) || !Number.isFinite(n.longitude)) return;
    const [lat, lon] = jitterCoords(n, idx); // usa las coords que se muestran en el mapa
    const sec = String(n.security || '').toUpperCase();
    const isInsecure = insecureTypes.has(sec);
    if (category === 'insecure' && !isInsecure) return;
    if (category === 'secure' && isInsecure) return;
    if (metersDistance(centerLat, centerLon, lat, lon) <= searchRadius) {
      nearbyPoints.push([lat, lon]);
    }
  });
  if (nearbyPoints.length < 3) {
    return nearbyPoints;
  }
  const hull = convexHull(nearbyPoints);
  return inflatePolygon(hull, 25); // agrega ~25m de margen para cubrir puntos en el borde
}

function convexHull(points) {
  if (points.length < 3) return points;
  const rad = Math.PI / 180;
  const refLat = points.reduce((acc, [lat]) => acc + lat, 0) / points.length;
  const projected = points.map(([lat, lon]) => ({
    lat,
    lon,
    x: lon * Math.cos(refLat * rad),
    y: lat,
  }));
  projected.sort((a, b) => (a.x === b.x ? a.y - b.y : a.x - b.x));

  const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower = [];
  projected.forEach((p) => {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  });
  const upper = [];
  for (let i = projected.length - 1; i >= 0; i -= 1) {
    const p = projected[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  const hull = lower.slice(0, -1).concat(upper.slice(0, -1));
  return hull.map((p) => [p.lat, p.lon]);
}

// Expande un poligono unos metros para asegurar que todos los puntos queden dentro
function inflatePolygon(points, bufferMeters = 10) {
  if (points.length === 0 || bufferMeters <= 0) return points;
  const rad = Math.PI / 180;
  const centerLat = points.reduce((acc, [lat]) => acc + lat, 0) / points.length;
  const centerLon = points.reduce((acc, [, lon]) => acc + lon, 0) / points.length;
  const cosLat = Math.cos(centerLat * rad);

  return points.map(([lat, lon]) => {
    const dx = (lon - centerLon) * 111320 * cosLat;
    const dy = (lat - centerLat) * 111320;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const scale = (dist + bufferMeters) / dist;
    const nx = dx * scale;
    const ny = dy * scale;
    const newLat = centerLat + (ny / 111320);
    const newLon = centerLon + (nx / (111320 * cosLat));
    return [newLat, newLon];
  });
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
      <p>Zonas (seguras e inseguras) usan colores aleatorios sin rojo ni verde.</p>
    `;
    return div;
  };
  legend.addTo(map);
}

// ===========================================================
// Inicializacion del mapa
// ===========================================================
renderLegend();
fetchNetworks();
setInterval(fetchNetworks, 10000);
