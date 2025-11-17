from __future__ import annotations

import json
from typing import Iterable, List, Dict, Any

import requests

BASE_URL = 'https://io.adafruit.com/api/v2'


class AdafruitClient:
    """Small wrapper around the Adafruit IO REST API."""

    def __init__(self, username: str, key: str, feed_key: str, timeout: float = 10):
        self.username = username
        self.key = key
        self.feed_key = feed_key
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return all([self.username, self.key, self.feed_key])

    @property
    def _feed_url(self) -> str:
        return f"{BASE_URL}/{self.username}/feeds/{self.feed_key}"

    def fetch_feed_data(self, limit: int = 200) -> List[Dict[str, Any]]:
        if not self.is_configured:
            return []
        response = requests.get(
            f"{self._feed_url}/data",
            params={'limit': limit},
            headers=self._headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def publish(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            f"{self._feed_url}/data",
            headers=self._headers,
            json={'value': json.dumps(payload)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def publish_batch(self, payloads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        failed: List[Dict[str, Any]] = []
        for payload in payloads:
            try:
                self.publish(payload)
            except requests.RequestException:
                failed.append(payload)
        return failed

    @staticmethod
    def extract_payload(entry: Dict[str, Any]) -> Dict[str, Any] | None:
        raw_value = entry.get('value')
        if isinstance(raw_value, dict):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return json.loads(raw_value)
            except json.JSONDecodeError:
                return None
        return None

    @property
    def _headers(self) -> Dict[str, str]:
        return {'X-AIO-Key': self.key, 'Content-Type': 'application/json'}
