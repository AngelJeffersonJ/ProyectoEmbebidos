from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict

MAC_RE = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')


@dataclass
class NetworkObservation:
    ssid: str
    mac: str
    channel: int
    rssi: int
    security: str
    latitude: float
    longitude: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> 'NetworkObservation':
        """Create a validated observation from a generic dict."""
        mac = str(payload.get('mac', '')).strip()
        if not MAC_RE.match(mac):
            raise ValueError(f'Invalid MAC address: {mac}')
        security = str(payload.get('security', 'unknown')).upper()
        timestamp_value = payload.get('timestamp')
        timestamp = cls._coerce_timestamp(timestamp_value)
        return cls(
            ssid=str(payload.get('ssid', 'unknown')),
            mac=mac.upper(),
            channel=int(payload.get('channel', 1)),
            rssi=int(payload.get('rssi', -100)),
            security=security,
            latitude=float(payload.get('latitude')),
            longitude=float(payload.get('longitude')),
            timestamp=timestamp,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @staticmethod
    def _coerce_timestamp(value: Any) -> datetime:
        if value is None:
            return datetime.utcnow()
        try:
            if isinstance(value, (int, float)):
                return datetime.utcfromtimestamp(float(value))
            if isinstance(value, str):
                return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            pass
        return datetime.utcnow()
