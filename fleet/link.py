"""
fleet/link.py — Elo de comunicação da frota (Fase 2.5 — Torre de Controle).

Cada robô (e a Torre) cria um FleetLink para publicar/assinar tópicos.
Dois backends, escolhidos automaticamente:

  mqtt — paho-mqtt → broker mosquitto na Torre (produção; 100% offline na
         rede local do roteador). Reconexão automática do próprio paho;
         status online/offline via LWT (Last Will and Testament).
  mock — barramento em memória (_MockBus, singleton do processo): vários
         FleetLink no MESMO processo conversam entre si. Usado no dev/PC,
         no harness de validação e no demo da Torre (scripts/demo_torre.py).

FAIL-SOFT: se o broker estiver fora do ar ou o paho ausente, o robô segue
100% funcional sem a Torre — apenas loga o aviso e degrada para mock.
"""

import json
import logging
import threading

from config.settings import (
    MOCK_MODE, MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE_S,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# BACKEND MOCK — barramento pub/sub em memória
# ─────────────────────────────────────────────
class _MockBus:
    """Singleton do processo. Suporta wildcards MQTT (+ e #) e retained."""

    def __init__(self):
        self._lock     = threading.Lock()
        self._subs     = []    # [(topic_filter, callback)]
        self._retained = {}    # topic → payload

    @staticmethod
    def _match(topic_filter: str, topic: str) -> bool:
        f, t = topic_filter.split("/"), topic.split("/")
        for i, seg in enumerate(f):
            if seg == "#":
                return True
            if i >= len(t):
                return False
            if seg != "+" and seg != t[i]:
                return False
        return len(f) == len(t)

    def publish(self, topic: str, payload: str, retain: bool = False):
        with self._lock:
            if retain:
                self._retained[topic] = payload
            subs = list(self._subs)
        for filt, cb in subs:
            if self._match(filt, topic):
                try:
                    cb(topic, payload)
                except Exception as e:
                    log.error(f"[MockBus] Callback falhou em '{topic}': {e}")

    def subscribe(self, topic_filter: str, cb):
        with self._lock:
            self._subs.append((topic_filter, cb))
            retained = [(t, p) for t, p in self._retained.items()
                        if self._match(topic_filter, t)]
        for t, p in retained:      # entrega retained na assinatura (como MQTT)
            try:
                cb(t, p)
            except Exception as e:
                log.error(f"[MockBus] Callback retained falhou em '{t}': {e}")


_mock_bus = _MockBus()    # compartilhado por todos os FleetLink do processo


# ─────────────────────────────────────────────
# FLEET LINK
# ─────────────────────────────────────────────
class FleetLink:
    """
    Interface única de pub/sub da frota.

    Parâmetros:
      client_id    — identidade no broker (ex.: "robo-3", "torre").
      status_topic — se fornecido, publica "online" (retained) ao conectar e
                     "offline" via LWT/stop() — presença do robô na Torre.
      backend      — None (auto: mock em MOCK_MODE, mqtt no robô real),
                     "mock" ou "mqtt" para forçar.
    """

    def __init__(self, client_id: str, status_topic: str | None = None,
                 backend: str | None = None):
        self.client_id    = client_id
        self.status_topic = status_topic
        self._subs        = []     # [(topic_filter, callback)] p/ (re)assinatura
        self._client      = None   # cliente paho (backend mqtt)
        self.backend      = backend or ("mock" if MOCK_MODE else "mqtt")

        if self.backend == "mqtt":
            try:
                import paho.mqtt.client as mqtt
                self._mqtt = mqtt
            except ImportError:
                log.warning(f"[FleetLink:{client_id}] paho-mqtt ausente — "
                            "degradando para backend mock (robô segue sem Torre).")
                self.backend = "mock"

    # ─────────────────────────────────────────
    # CICLO DE VIDA
    # ─────────────────────────────────────────
    def start(self):
        if self.backend == "mock":
            log.info(f"[FleetLink:{self.client_id}] Backend MOCK (bus em memória).")
            if self.status_topic:
                _mock_bus.publish(self.status_topic, "online", retain=True)
            return

        mqtt = self._mqtt
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        if self.status_topic:
            self._client.will_set(self.status_topic, "offline", retain=True)

        def _on_connect(client, userdata, flags, reason_code, properties):
            log.info(f"[FleetLink:{self.client_id}] Conectado ao broker "
                     f"{MQTT_HOST}:{MQTT_PORT} ({reason_code}).")
            if self.status_topic:
                client.publish(self.status_topic, "online", retain=True)
            for filt, _ in self._subs:          # (re)assina após reconexão
                client.subscribe(filt)

        def _on_message(client, userdata, msg):
            payload = msg.payload.decode("utf-8", errors="replace")
            for filt, cb in self._subs:
                if _MockBus._match(filt, msg.topic):
                    try:
                        cb(msg.topic, payload)
                    except Exception as e:
                        log.error(f"[FleetLink] Callback falhou em "
                                  f"'{msg.topic}': {e}")

        self._client.on_connect = _on_connect
        self._client.on_message = _on_message
        # connect_async + loop_start: reconexão automática em thread própria;
        # broker fora do ar NÃO bloqueia nem derruba o robô (fail-soft).
        self._client.connect_async(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE_S)
        self._client.loop_start()

    def stop(self):
        if self.backend == "mock":
            if self.status_topic:
                _mock_bus.publish(self.status_topic, "offline", retain=True)
            return
        if self._client:
            try:
                if self.status_topic:
                    self._client.publish(self.status_topic, "offline", retain=True)
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass

    # ─────────────────────────────────────────
    # PUB/SUB
    # ─────────────────────────────────────────
    def publish(self, topic: str, payload, retain: bool = False):
        """payload: str ou dict (dict é serializado em JSON)."""
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        if self.backend == "mock":
            _mock_bus.publish(topic, payload, retain=retain)
        elif self._client:
            self._client.publish(topic, payload, retain=retain)

    def subscribe(self, topic_filter: str, callback):
        """callback(topic: str, payload: str) — wildcards + e # suportados."""
        self._subs.append((topic_filter, callback))
        if self.backend == "mock":
            _mock_bus.subscribe(topic_filter, callback)
        elif self._client and self._client.is_connected():
            self._client.subscribe(topic_filter)
