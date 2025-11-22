import time
import ujson
import network
import ubinascii
from machine import UART, Pin
from umqtt.simple import MQTTClient


def load_env(path='.env'):
    env = {}
    try:
        with open(path) as handle:  # type: ignore[call-arg]
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


GPS_UART = UART(1, baudrate=9600, tx=Pin(4), rx=Pin(5))
WLAN = network.WLAN(network.STA_IF)
OFFLINE_BUFFER = 'offline_buffer.jsonl'
LOOP_DELAY = 120  # seconds
SECURITY_MAP = {
    0: 'OPEN',
    1: 'WEP',
    2: 'WPA-PSK',
    3: 'WPA2-PSK',
    4: 'WPA/WPA2-PSK',
    5: 'WPA3',
}
WIFI_SSID = env('WIFI_SSID', 'YOUR_WIFI_SSID')
WIFI_PASSWORD = env('WIFI_PASSWORD', 'YOUR_WIFI_PASSWORD')
AIO_USERNAME = env('AIO_USERNAME', 'your_aio_username')
AIO_KEY = env('AIO_KEY', 'your_aio_key')
AIO_FEED_KEY = env('AIO_FEED_KEY', 'wardrive')
DEVICE_ID = env('DEVICE_ID', 'pico-main')


def connect_wifi() -> None:
    if WLAN.isconnected():
        return
    print('[WiFi] Connecting to', WIFI_SSID)
    WLAN.active(True)
    WLAN.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(30):
        if WLAN.isconnected():
            print('[WiFi] Connected, IP:', WLAN.ifconfig()[0])
            return
        time.sleep(1)
    print('[WiFi] Failed to connect')


def scan_networks():
    if not WLAN.active():
        WLAN.active(True)
    networks = []
    for result in WLAN.scan():
        ssid, mac, channel, rssi, security, _hidden = result
        mac_str = ':'.join('{:02X}'.format(byte) for byte in mac)
        security_label = SECURITY_MAP.get(security, 'UNKNOWN')
        networks.append({
            'ssid': ssid.decode() if isinstance(ssid, bytes) else ssid,
            'mac': mac_str,
            'channel': channel,
            'rssi': rssi,
            'security': security_label,
        })
    print(f'[Scan] Found {len(networks)} networks')
    return networks


def read_sentence():
    if GPS_UART.any():
        try:
            return GPS_UART.readline().decode().strip()
        except Exception:
            return None
    return None


def parse_gga(sentence):
    if not sentence or not sentence.startswith('$G'):
        return None
    parts = sentence.split(',')
    if len(parts) < 10 or parts[6] == '0':
        return None
    lat = to_decimal(parts[2], parts[3])
    lon = to_decimal(parts[4], parts[5])
    if lat is None or lon is None:
        return None
    satellites = int(parts[7] or 0)
    hdop = float(parts[8] or 99.9)
    fix_quality = parts[6]
    return {'lat': lat, 'lon': lon, 'satellites': satellites, 'hdop': hdop, 'fix_quality': fix_quality}


def to_decimal(raw, hemi):
    if not raw:
        return None
    split = 2 if hemi in ('N', 'S') else 3
    try:
        degrees = float(raw[:split])
        minutes = float(raw[split:])
    except (ValueError, TypeError):
        return None
    value = degrees + minutes / 60
    if hemi in ('S', 'W'):
        value *= -1
    return value


def get_fix(timeout=5000):
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < timeout:
        sentence = read_sentence()
        fix = parse_gga(sentence)
        if fix:
            print('[GPS] Fix lat:', fix['lat'], 'lon:', fix['lon'], 'sat:', fix['satellites'], 'hdop:', fix['hdop'])
            return fix
    print('[GPS] Waiting for fix...')
    return None


def mqtt_client():
    client_id = ubinascii.hexlify(WLAN.config('mac')).decode()
    return MQTTClient(client_id, 'io.adafruit.com', user=AIO_USERNAME, password=AIO_KEY, keepalive=60)


def save_offline(payload):
    with open(OFFLINE_BUFFER, 'a') as handle:
        handle.write(ujson.dumps(payload) + '\n')
    print('[Buffer] Stored offline payload')


def flush_offline(client):
    try:
        with open(OFFLINE_BUFFER, 'r') as handle:
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
        try:
            publish_payload(client, payload)
            sent += 1
        except Exception as exc:
            print('[Buffer] Failed to publish cached payload:', exc)
            remaining.append(payload)
    with open(OFFLINE_BUFFER, 'w') as handle:
        for item in remaining:
            handle.write(ujson.dumps(item) + '\n')
    return sent


def publish_payload(client, payload):
    topic = f"{AIO_USERNAME}/feeds/{AIO_FEED_KEY}"
    client.publish(topic, ujson.dumps(payload))
    print('[MQTT] Published payload for', payload.get('ssid'))


def main():
    connect_wifi()
    client = None
    while True:
        fix = get_fix()
        if not fix:
            time.sleep(5)
            continue
        networks = scan_networks()
        if not networks:
            time.sleep(LOOP_DELAY)
            continue
        timestamp = time.time()
        payloads = []
        for network_info in networks:
            payload = {
                'ssid': network_info['ssid'],
                'mac': network_info['mac'],
                'channel': network_info['channel'],
                'rssi': network_info['rssi'],
                'security': network_info['security'],
                'latitude': fix['lat'],
                'longitude': fix['lon'],
                'timestamp': timestamp,
                'device_id': DEVICE_ID,
            }
            payloads.append(payload)
        if WLAN.isconnected():
            try:
                if client is None:
                    client = mqtt_client()
                    client.connect()
                    print('[MQTT] Connected to Adafruit IO')
                for payload in payloads:
                    publish_payload(client, payload)
                flushed = flush_offline(client)
                if flushed:
                    print(f'[Buffer] Flushed {flushed} cached payloads')
            except Exception as exc:
                print('[MQTT] Error, caching payloads:', exc)
                for payload in payloads:
                    save_offline(payload)
                client = None
        else:
            print('[WiFi] Offline, caching payloads')
            for payload in payloads:
                save_offline(payload)
            connect_wifi()
        time.sleep(LOOP_DELAY)


if __name__ == '__main__':
    main()
