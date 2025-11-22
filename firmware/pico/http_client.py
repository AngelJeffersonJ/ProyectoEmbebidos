"""
Wardriving client for Pico W that publishes to Adafruit IO (MQTT) and optionally
POSTs to a Flask backend. Reads config from a .env file placed alongside this
script on the Pico filesystem. Designed for MicroPython (no type hints, ASCII).
"""

import time
import ubinascii
import ujson
from machine import Pin, UART
import network
import urequests
from umqtt.simple import MQTTClient
from micropyGPS import MicropyGPS


def load_env(path='.env'):
    env = {}
    try:
        with open(path) as handle:  # type: ignore
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


ENV = load_env()


def env(key, default=''):
    return ENV.get(key, default)


WIFI_SSID = env('WIFI_SSID', 'ssid')
WIFI_PASSWORD = env('WIFI_PASSWORD', 'password')
SERVER_BASE = env('BACKEND_URL', 'http://192.168.146.11:5000').strip()
POST_ENDPOINT = SERVER_BASE.rstrip('/') + '/api/samples' if SERVER_BASE else ''
AIO_USERNAME = env('AIO_USERNAME', '')
AIO_KEY = env('AIO_KEY', '')
AIO_FEED_KEY = env('AIO_FEED_KEY', 'wardrive')
DEVICE_ID = env('DEVICE_ID', 'pico-node')

GPS_TX = 4
GPS_RX = 5
GPS_BAUD = 9600
OFFLINE_FILE = 'offline_buffer.jsonl'
SYNC_INTERVAL = 60  # seconds between cycles
MQTT_HOST = 'io.adafruit.com'
MQTT_KEEPALIVE = 60


class GPSReader:
    def __init__(self):
        print('[GPS] Inicializando UART...')
        self.uart = UART(1, baudrate=GPS_BAUD, tx=Pin(GPS_TX), rx=Pin(GPS_RX))
        self.parser = MicropyGPS()
        print('[GPS] UART lista (TX=GP%s | RX=GP%s | %s baud)' % (GPS_TX, GPS_RX, GPS_BAUD))

    def read_fix(self, timeout=30):
        print('[GPS] Esperando FIX (timeout=%ss)...' % timeout)
        start = time.time()
        while time.time() - start < timeout:
            self._pump_parser()
            elapsed = int(time.time() - start)
            print('[GPS] t=%ss | fix_stat=%s | sat=%s | HDOP=%s' %
                  (elapsed, self.parser.fix_stat, self.parser.satellites_in_use, self.parser.hdop))
            if self.parser.fix_stat >= 1:
                lat = self._to_decimal(self.parser.latitude)
                lon = self._to_decimal(self.parser.longitude)
                if lat is not None and lon is not None:
                    print('[GPS] FIX obtenido (%s, %s)' % (lat, lon))
                    return {
                        'latitude': lat,
                        'longitude': lon,
                        'satellites': self.parser.satellites_in_use,
                        'hdop': self.parser.hdop,
                    }
            time.sleep(1)
        print('[GPS] No se logro obtener fix a tiempo.')
        return None

    def _pump_parser(self):
        while self.uart.any():
            chunk = self.uart.read(1)
            if not chunk:
                return
            try:
                self.parser.update(chr(chunk[0]))
            except ValueError:
                pass

    @staticmethod
    def _to_decimal(coord):
        if not coord or coord[0] == 0:
            return None
        degrees, minutes, direction = coord
        decimal = degrees + minutes / 60
        if direction in ('S', 'W'):
            decimal *= -1
        return decimal


class WardriveClient:
    def __init__(self):
        print('[SYSTEM] Iniciando cliente HTTP/MQTT...')
        self.gps = GPSReader()
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.mqtt = None

    def ensure_wifi(self):
        if self.wlan.isconnected():
            print('[WiFi] Conectado:', self.wlan.ifconfig())
            return True
        print("[WiFi] Intentando conectar a '%s' ..." % WIFI_SSID)
        self.wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for attempt in range(20):
            if self.wlan.isconnected():
                print('[WiFi] Conexion exitosa:', self.wlan.ifconfig())
                return True
            print('[WiFi] Esperando conexion (%s/20)' % (attempt + 1))
            time.sleep(1)
        print('[WiFi] No se logro conectar.')
        return False

    def ensure_mqtt(self):
        if not (AIO_USERNAME and AIO_KEY and AIO_FEED_KEY):
            return False
        if self.mqtt:
            return True
        try:
            client_id = ubinascii.hexlify(self.wlan.config('mac')).decode()
            self.mqtt = MQTTClient(
                client_id,
                MQTT_HOST,
                user=AIO_USERNAME,
                password=AIO_KEY,
                keepalive=MQTT_KEEPALIVE,
            )
            self.mqtt.connect()
            print('[MQTT] Conectado a Adafruit IO')
            return True
        except Exception as exc:
            print('[MQTT] Error al conectar:', exc)
            self.mqtt = None
            return False

    def publish_mqtt(self, payload):
        if not self.mqtt:
            return False
        topic = '%s/feeds/%s' % (AIO_USERNAME, AIO_FEED_KEY)
        try:
            self.mqtt.publish(topic, ujson.dumps(payload))
            return True
        except Exception as exc:
            print('[MQTT] Error al publicar:', exc)
            try:
                self.mqtt.disconnect()
            except Exception:
                pass
            self.mqtt = None
            return False

    def post_sample(self, payload):
        if not POST_ENDPOINT or not self.wlan.isconnected():
            return False
        print('[HTTP] POST %s' % POST_ENDPOINT)
        try:
            res = urequests.post(
                POST_ENDPOINT,
                data=ujson.dumps(payload),
                headers={'Content-Type': 'application/json'},
            )
            res.close()
            print('[HTTP] Payload enviado.')
            return True
        except Exception as exc:
            print('[HTTP] Error HTTP:', exc)
            return False

    def append_offline(self, payload):
        try:
            with open(OFFLINE_FILE, 'a') as handle:
                handle.write(ujson.dumps(payload) + '\n')
            print('[OFFLINE] Guardado en buffer local.')
        except Exception as exc:
            print('[OFFLINE] Error al guardar:', exc)

    def flush_offline(self):
        if not self.mqtt:
            return 0
        try:
            with open(OFFLINE_FILE, 'r') as handle:
                lines = handle.readlines()
        except OSError:
            return 0
        if not lines:
            return 0
        sent = 0
        remaining = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = ujson.loads(line)
            except Exception:
                continue
            if self.publish_mqtt(payload):
                sent += 1
            else:
                remaining.append(payload)
        try:
            with open(OFFLINE_FILE, 'w') as handle:
                for item in remaining:
                    handle.write(ujson.dumps(item) + '\n')
        except Exception:
            pass
        if sent:
            print('[OFFLINE] %s registros sincronizados.' % sent)
        return sent

    def run_cycle(self):
        print('\n========== NUEVO CICLO ==========')
        fix = self.gps.read_fix()
        if not fix:
            print('[SYSTEM] No hay fix GPS, se reintenta en el proximo ciclo.')
            return

        networks = self.scan_networks()
        if not networks:
            print('[SYSTEM] No se detectaron redes, fin del ciclo.')
            return

        online = self.ensure_wifi()
        mqtt_ready = self.ensure_mqtt() if online else False
        timestamp = time.time()

        gps_payload = {
            'latitude': fix['latitude'],
            'longitude': fix['longitude'],
            'satellites': fix.get('satellites'),
            'hdop': fix.get('hdop'),
        }

        for ssid, bssid, channel, rssi, auth_mode, hidden in networks:
            network_payload = {
                'ssid': ssid.decode() if isinstance(ssid, bytes) else ssid,
                'mac': ':'.join('{:02X}'.format(b) for b in bssid),
                'channel': int(channel),
                'rssi': int(rssi),
                'security': self.SECURITY_LABEL(auth_mode),
                'timestamp': timestamp,
                'device_id': DEVICE_ID,
            }
            mqtt_payload = {}
            mqtt_payload.update(network_payload)
            mqtt_payload.update(gps_payload)

            mqtt_sent = self.publish_mqtt(mqtt_payload) if mqtt_ready else False
            if POST_ENDPOINT:
                self.post_sample({'network': network_payload, 'gps': gps_payload})
            if not mqtt_sent:
                self.append_offline(mqtt_payload)

        if mqtt_ready:
            self.flush_offline()

    def scan_networks(self):
        print('[WiFi] Escaneando entorno...')
        try:
            results = self.wlan.scan() or []
            print('[WiFi] Detectadas %s redes.' % len(results))
            return results
        except Exception as exc:
            print('[WiFi] Error durante el escaneo:', exc)
            return []

    @staticmethod
    def SECURITY_LABEL(auth):
        lookup = {0: 'OPEN', 1: 'WEP', 2: 'WPA-PSK', 3: 'WPA2-PSK', 4: 'WPA/WPA2-PSK', 5: 'WPA3'}
        return lookup.get(auth, 'UNKNOWN')

    def loop_forever(self):
        while True:
            self.run_cycle()
            print('[SYSTEM] Esperando %ss...' % SYNC_INTERVAL)
            time.sleep(SYNC_INTERVAL)


def main():
    client = WardriveClient()
    client.loop_forever()


if __name__ == '__main__':
    main()
