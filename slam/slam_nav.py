"""
slam/slam_nav.py
Navegação autônoma via Slamtec Aurora.
Implementado na Fase 4 — placeholder por enquanto.
"""

import logging
log = logging.getLogger(__name__)


class SlamNav:
    """
    Placeholder para navegação autônoma.
    Fase 4: integrar Aurora SDK + pathfinding + loop de controle autônomo.
    """

    def __init__(self, motors, poi_manager):
        self.motors      = motors
        self.poi_manager = poi_manager
        self.active      = False
        self.target_poi  = None
        log.info("[SlamNav] Placeholder inicializado — aguardando Fase 4.")

    def navigate_to(self, poi_name: str):
        poi = self.poi_manager.get(poi_name)
        if not poi:
            log.error(f"[SlamNav] POI '{poi_name}' não encontrado.")
            return False
        self.target_poi = poi
        self.active     = True
        log.info(f"[SlamNav] Navegando para: {poi}")
        return True

    def stop(self):
        self.active     = False
        self.target_poi = None
        self.motors.stop()

    def tick(self, state: dict):
        """Chamado a cada ciclo de 20ms pelo main.py quando em modo AUTONOMO."""
        if not self.active:
            return
        # TODO Fase 4: implementar loop de navegação com Aurora SDK
        pass
