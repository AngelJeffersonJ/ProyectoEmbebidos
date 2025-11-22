# Wardrive System

Sistema Wardriving completo para Raspberry Pi Pico W + GPS NEO-6M y backend Flask. Incluye firmware MicroPython, sincronización con Adafruit IO y frontend Leaflet para visualizar redes detectadas.

## 🚀 Características
- Escaneo periódico de redes Wi-Fi desde Pico W y envío vía MQTT a Adafruit IO.
- Buffer offline automático cuando no hay conectividad.
- Backend Flask modular con Blueprints, servicios y análisis DBSCAN.
- Frontend Leaflet que distingue redes seguras e inseguras.
- Herramienta `tools/mock_client.py` para pruebas locales sin hardware.

## 📂 Estructura
```
.
├── app/
│   ├── analytics/        # Utilidades de análisis (DBSCAN)
│   ├── models/           # Modelos de datos (NetworkObservation)
│   ├── routes/           # Blueprints API y vistas
│   ├── services/         # Integraciones (Adafruit, storage, etc.)
│   ├── static/           # JS y assets frontend
│   ├── templates/        # Plantillas Jinja (Leaflet)
│   └── tasks/            # Scheduler simple para sincronización
├── firmware/
│   └── pico/             # Código MicroPython principal
├── storage/              # Archivos JSONL locales
├── tools/                # Scripts de soporte (mock client)
├── wardrive.py           # Punto de entrada Flask
├── requirements.txt      # Dependencias backend
└── README.md             # Este archivo
```

## 🛠️ Backend Flask
1. **Crear entorno**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # En Windows
   pip install -r requirements.txt
   ```
2. **Configurar variables**
   ```bash
   copy .env.example .env
   ```
   Edita `.env` con tus credenciales de Adafruit IO y rutas deseadas. Este mismo archivo puedes copiarlo (o una versión reducida) a cada Pico W para evitar `secrets.py`. Si el repositorio vive en GitHub usa [Secrets/Variables de entorno](https://docs.github.com/es/actions/security-guides/encrypted-secrets) para injectar `AIO_*`, `SECRET_KEY`, etc., en tus despliegues y nunca subas el `.env` real.
3. **Ejecutar servidor**
   ```bash
   python wardrive.py
   ```
   El mapa estará disponible en `http://127.0.0.1:5000/`.

   > El backend usa `WardriveService`: cada muestra recibida se guarda en `storage/data.jsonl`, se intenta publicar al feed de Adafruit IO (HTTP) y, si falla, pasa a `storage/offline_buffer.jsonl` para reintentos. `GET /api/networks` primero consulta Adafruit IO y, si no hay conectividad, cae al almacenamiento local, cumpliendo el requisito de que la visualización consuma los datos remotos.

### Endpoints principales
- `GET /` → interfaz Leaflet + leyenda.
- `GET /api/health` → estado general, conteo de colas.
- `GET /api/networks` → listado de redes (Adafruit > storage > buffer) + clusters inseguros.

### Análisis DBSCAN manual
Puedes invocar el módulo directamente desde un shell interactivo:
```bash
python - <<'PY'
from app.analytics.clustering import cluster_insecure_networks
from app.services.storage_queue import StorageQueue

records = StorageQueue('storage/data.jsonl').read_all()
print(cluster_insecure_networks(records, eps_meters=60))
PY
```
Esto mostrará los clústeres de redes Open/WEP usando DBSCAN (métrica haversine).

## 🌐 Frontend Leaflet
- `app/templates/index.html` monta Leaflet y panel lateral.
- `app/static/js/map.js` consulta `/api/networks` cada 2 minutos, pinta puntos rojos (Open/WEP) y azules (WPA+), además de una leyenda.

## 📡 Firmware Pico W
1. **Preparar MicroPython**
   - Flashea MicroPython UF2 oficial en la Pico W.
   - Copia `firmware/pico/main.py` o `firmware/pico/http_client.py` al dispositivo (renómbralo como `main.py`).
2. **Configurar `.env` por equipo**
   - Copia tu `.env` (o crea uno nuevo) en la Pico W junto al `main.py` con algo como:
     ```
     WIFI_SSID=TuSSID
     WIFI_PASSWORD=TuPassword
     AIO_USERNAME=tu_usuario
     AIO_KEY=tu_aio_key
     AIO_FEED_KEY=wardrive
     BACKEND_URL=http://192.168.1.50:5000
     ```
3. **Cableado GPS NEO-6M**
   - TX → GP4, RX → GP5, GND común y alimentación 3V3/5V según módulo.
4. **Funcionamiento**
   - Ambos firmwares esperan un fix GPS válido antes de medir. Sin fix → el ciclo se aplaza.
   - `main.py` publica exclusivamente por MQTT hacia Adafruit IO y mantiene `offline_buffer.jsonl` hasta confirmar que todos los registros pendientes se publicaron.
   - `http_client.py` publica simultáneamente por MQTT (Adafruit IO) y HTTP (`/api/samples`) para contar con telemetría local extra; si MQTT falla, almacena los payloads y los reintenta automáticamente cuando vuelve la conectividad.
   - Cada payload incluye SSID/MAC/canal/RSSI/seguridad + latitud/longitud para visualizar la cobertura capturada localmente.

## 🧪 Mock Client
`tools/mock_client.py` genera datos ficticios para pruebas rápidas.
```bash
python tools/mock_client.py --count 10 --mode storage   # escribe en storage/data.jsonl
python tools/mock_client.py --mode adafruit             # envía al feed remoto
```
Útil para poblar el mapa mientras se desarrolla el firmware.

## ♻️ Scheduler opcional
`app/tasks/scheduler.py` ofrece un `start_offline_sync(service)` que puedes invocar desde procesos background para subir colas offline regularmente.

## ✅ Buenas prácticas incluidas
- Código Python 3.10+ con anotaciones y comentarios breves.
- Configuración por entorno (`.env`) y dotenv.
- Rutas separadas (views/API) + servicios reutilizables.
- Módulos claros para analytics, storage, firmware y herramientas.

¡Listo! Conecta tu hardware, configura las credenciales y comienza a mapear redes de manera segura.
