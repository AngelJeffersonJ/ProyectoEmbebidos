from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.adafruit_client import AdafruitClient  # noqa: E402
from app.services.storage_queue import StorageQueue  # noqa: E402

load_dotenv(PROJECT_ROOT / '.env', override=False)

SECURE_TYPES = ['WPA-PSK', 'WPA2-PSK', 'WPA3']
INSECURE_TYPES = ['OPEN', 'WEP']


def random_network(lat: float, lon: float) -> dict:
    rssi = random.randint(-90, -30)
    security = random.choice(SECURE_TYPES + INSECURE_TYPES)
    channel = random.randint(1, 11)
    ssid = f"TestNet-{random.randint(100, 999)}"
    mac = ':'.join(f"{random.randint(0, 255):02X}" for _ in range(6))
    jitter_lat = lat + random.uniform(-0.001, 0.001)
    jitter_lon = lon + random.uniform(-0.001, 0.001)
    return {
        'ssid': ssid,
        'mac': mac,
        'channel': channel,
        'rssi': rssi,
        'security': security,
        'latitude': round(jitter_lat, 6),
        'longitude': round(jitter_lon, 6),
        'timestamp': time.time(),
    }


def publish_to_storage(records: list[dict]) -> None:
    storage_path = os.getenv('STORAGE_PATH', PROJECT_ROOT / 'storage' / 'data.jsonl')
    queue = StorageQueue(str(storage_path))
    queue.extend(records)
    print(f'Saved {len(records)} records to {storage_path}')


def publish_to_adafruit(records: list[dict]) -> None:
    client = AdafruitClient(
        username=os.getenv('AIO_USERNAME', ''),
        key=os.getenv('AIO_KEY', ''),
        feed_key=os.getenv('AIO_FEED_KEY', 'wardrive'),
    )
    if not client.is_configured:
        raise RuntimeError('AIO credentials missing. Set them in the .env file.')
    failed = client.publish_batch(records)
    if failed:
        print(f'Failed to publish {len(failed)} records, inspect network/credentials.')
    else:
        print(f'Published {len(records)} records to Adafruit IO feed {client.feed_key}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Mock client for wardrive backend testing.')
    parser.add_argument('--count', type=int, default=5, help='Number of fake networks to generate.')
    parser.add_argument('--lat', type=float, default=19.4326, help='Base latitude for generated points.')
    parser.add_argument('--lon', type=float, default=-99.1332, help='Base longitude for generated points.')
    parser.add_argument('--mode', choices=['storage', 'adafruit'], default='storage', help='Where to send the fabricated data.')
    args = parser.parse_args()

    records = [random_network(args.lat, args.lon) for _ in range(args.count)]
    if args.mode == 'storage':
        publish_to_storage(records)
    else:
        publish_to_adafruit(records)


if __name__ == '__main__':
    main()
