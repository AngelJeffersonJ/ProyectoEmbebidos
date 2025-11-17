from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GPSFix:
    latitude: float
    longitude: float
    satellites: int
    hdop: float


class NMEAParser:
    """Very small NMEA parser used for local debugging or tests."""

    def parse_gga(self, sentence: str) -> Optional[GPSFix]:
        if not sentence.startswith('$GPGGA') and not sentence.startswith('$GNGGA'):
            return None
        parts = sentence.split(',')
        if len(parts) < 15 or parts[6] == '0':  # 0 => no fix
            return None
        latitude = self._to_decimal(parts[2], parts[3])
        longitude = self._to_decimal(parts[4], parts[5])
        satellites = int(parts[7] or 0)
        hdop = float(parts[8] or 99.9)
        return GPSFix(latitude=latitude, longitude=longitude, satellites=satellites, hdop=hdop)

    @staticmethod
    def _to_decimal(value: str, hemisphere: str) -> float:
        if not value:
            return 0.0
        degrees = float(value[:2]) if len(value) > 4 else 0.0
        minutes = float(value[2:]) if len(value) > 4 else 0.0
        decimal = degrees + minutes / 60
        if hemisphere in ('S', 'W'):
            decimal *= -1
        return decimal
