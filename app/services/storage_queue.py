from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Dict, Any


class StorageQueue:
    """Simple JSONL storage helper used for data snapshots and queues."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, payload: Dict[str, Any]) -> None:
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(payload) + '\n')

    def extend(self, payloads: Iterable[Dict[str, Any]]) -> None:
        for payload in payloads:
            self.append(payload)

    def read_all(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        with self.path.open('r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return items

    def write_all(self, payloads: Iterable[Dict[str, Any]]) -> None:
        with self.path.open('w', encoding='utf-8') as handle:
            for payload in payloads:
                handle.write(json.dumps(payload) + '\n')

    def pop_all(self) -> List[Dict[str, Any]]:
        data = self.read_all()
        self.clear()
        return data

    def clear(self) -> None:
        self.path.write_text('', encoding='utf-8')

    def count(self) -> int:
        return sum(1 for _ in self._iter_lines())

    def _iter_lines(self):
        with self.path.open('r', encoding='utf-8') as handle:
            yield from handle
