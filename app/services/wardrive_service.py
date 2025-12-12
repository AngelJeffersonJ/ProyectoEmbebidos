from __future__ import annotations

import logging
from typing import Dict, List, Tuple, Any

import requests

from app.models.network import NetworkObservation
from .adafruit_client import AdafruitClient
from .storage_queue import StorageQueue

LOGGER = logging.getLogger(__name__)


class WardriveService:
    """High level coordinator between Adafruit IO and local storage."""

    def __init__(self, adafruit_client: AdafruitClient, storage: StorageQueue, offline_buffer: StorageQueue):
        self.adafruit_client = adafruit_client
        self.storage = storage
        self.offline_buffer = offline_buffer

    def fetch_networks(self) -> Tuple[List[Dict[str, Any]], str]:
        # Prioridad: storage local -> offline buffer -> Adafruit (solo si no hay nada local)
        records: List[Dict[str, Any]] = self.storage.read_all()
        source = 'storage'

        if not records:
            records = self.offline_buffer.read_all()
            source = 'offline-buffer'

        if not records and self.adafruit_client.is_configured:
            try:
                remote_entries = self.adafruit_client.fetch_feed_data()
                records = self._normalize_remote_entries(remote_entries)
                if records:
                    self.storage.write_all(records)
                source = 'adafruit'
            except requests.RequestException as exc:
                LOGGER.warning('Unable to fetch Adafruit feed: %s', exc)

        return records, source

    def _normalize_remote_entries(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for entry in entries:
            payload = self.adafruit_client.extract_payload(entry)
            if not payload:
                continue
            try:
                observation = NetworkObservation.from_payload(payload)
            except (ValueError, TypeError) as exc:
                LOGGER.debug('Skipping invalid payload: %s', exc)
                continue
            record = observation.to_dict()
            for key in ('satellites', 'hdop'):
                if key in payload:
                    record[key] = payload[key]
            normalized.append(record)
        return normalized

    def sync_offline_buffer(self) -> int:
        pending = self.offline_buffer.pop_all()
        if not pending:
            return 0
        if not self.adafruit_client.is_configured:
            self.offline_buffer.extend(pending)
            return 0
        failed = self.adafruit_client.publish_batch(pending)
        if failed:
            LOGGER.warning('Failed to upload %s offline records', len(failed))
            self.offline_buffer.extend(failed)
        return len(pending) - len(failed)
