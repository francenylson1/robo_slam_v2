"""
slam/poi_manager.py
Gerenciador de Pontos de Interesse (POIs).
Implementado na Fase 2.
"""

import json
import os
import logging

log = logging.getLogger(__name__)

from config.settings import POIS_FILE, DATA_DIR


class POIManager:
    """Lê, grava e lista POIs em pois.json."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._file = os.path.join(DATA_DIR, "pois.json")
        self._pois = self._load()

    def _load(self) -> list:
        if not os.path.exists(self._file):
            return []
        try:
            with open(self._file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self):
        with open(self._file, "w") as f:
            json.dump(self._pois, f, indent=2, ensure_ascii=False)

    def add(self, name: str, x: float, y: float, angle: float = 0.0):
        poi = {"name": name, "x": x, "y": y, "angle": angle}
        self._pois.append(poi)
        self._save()
        log.info(f"[POIManager] POI salvo: {poi}")
        return poi

    def list_all(self) -> list:
        return list(self._pois)

    def get(self, name: str) -> dict | None:
        for p in self._pois:
            if p["name"] == name:
                return p
        return None

    def remove(self, name: str) -> bool:
        before = len(self._pois)
        self._pois = [p for p in self._pois if p["name"] != name]
        if len(self._pois) < before:
            self._save()
            return True
        return False
