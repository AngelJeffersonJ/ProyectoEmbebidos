# Wardrive System

Sistema de wardriving con Raspberry Pi Pico W + GPS NEO-6M, backend Flask y mapa Leaflet. El Pico escanea Wi-Fi, envia los datos a Adafruit IO (MQTT) y el backend los muestra/almacena con clustering DBSCAN o KMeans cuando scikit-learn esta disponible.

## Caracteristicas
- Escaneo periodico de redes Wi-Fi desde la Pico W y envio via MQTT a Adafruit IO.
- Buffer offline automatico cuando no hay conectividad.
- Backend Flask monolitico (`wardrive.py`) con clustering DBSCAN/KMeans.
- Frontend Leaflet que distingue redes seguras e inseguras.
- Script `tools/mock_client.py` para poblar datos sin hardware.

## Estructura
```
.
├── app/
│   ├── models/        # Modelos de datos (NetworkObservation)
│   ├── routes/        # Blueprints API y vistas
│   ├── services/      # Integraciones (Adafruit, storage, etc.)
│   ├── static/        # JS y assets frontend
│   └── templates/     # Plantillas Jinja (Leaflet)
├── firmware/
│   └── pico/          # Codigo MicroPython principal
├── storage/           # Archivos JSONL locales
├── tools/             # Scripts de soporte (mock client)
├── wardrive.py        # Punto de entrada Flask
├── requirements.txt   # Dependencias backend
└── README.md
```

## Backend Flask
1. Crear entorno
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # En Windows
   pip install -r requirements.txt
   ```
2. Configurar variables
   - Crea un `.env` con tus credenciales Adafruit IO (`AIO_USERNAME`, `AIO_KEY`, `AIO_FEED_KEY`) y rutas si quieres sobreescribir `storage/data.jsonl` u `offline_buffer.jsonl`.
3. Ejecutar servidor
   ```bash
   python wardrive.py
   ```
   El mapa quedara en `http://127.0.0.1:5000/`. El servicio guarda cada muestra en `storage/data.jsonl`, intenta publicarla al feed de Adafruit IO y, si falla, la manda a `storage/offline_buffer.jsonl` para reintentos. `GET /api/networks` consulta primero Adafruit IO y luego cae a storage/buffer, devolviendo tambien los clusters calculados.

### Endpoints principales
- `GET /`               -> interfaz Leaflet.
- `POST /api/samples`   -> recibe muestras desde Pico (JSON).
- `GET /api/networks`   -> lista redes (Adafruit > storage > buffer) + clusters y algoritmo usado.

## Frontend Leaflet
- `app/templates/index.html` monta el mapa y panel lateral.
- `app/static/js/map.js` consulta `/api/networks`, pinta puntos (rojo OPEN/WEP, verde WPA+) y zonas/clusters con colores aleatorios (sin rojo/verde).

## Firmware Pico W
1. Flashea MicroPython UF2 oficial en la Pico W.
2. Copia `firmware/pico/main.py` (solo MQTT) o `firmware/pico/http_client.py` (MQTT + POST HTTP) al dispositivo como `main.py`.
3. Crea un `.env` en la Pico junto a `main.py` con:
   ```
   WIFI_SSID=tu_ssid
   WIFI_PASSWORD=tu_password
   AIO_USERNAME=tu_usuario
   AIO_KEY=tu_aio_key
   AIO_FEED_KEY=wardrive
   BACKEND_URL=http://192.168.1.50:5000   # solo para http_client.py
   DEVICE_ID=pico-node
   ```
4. Cablea GPS NEO-6M: TX->GP4, RX->GP5, GND comun y 3V3/5V segun modulo. Ambos firmwares esperan fix GPS valido antes de medir. Mantienen `offline_buffer.jsonl` en la Pico hasta que el publish via MQTT se confirma.

## Mock Client
`tools/mock_client.py` genera datos ficticios para pruebas rapidas:
```bash
python tools/mock_client.py --count 10 --mode storage   # escribe en storage/data.jsonl
python tools/mock_client.py --mode adafruit             # envia al feed remoto
```

## Buenas practicas incluidas
- Python 3.10+ con anotaciones y dotenv.
- Configuracion por entorno (.env) y servicios separados (Adafruit, storage, dedupe/clustering en el backend).
- Frontend ligero con Leaflet y polling periodico a `/api/networks`.
