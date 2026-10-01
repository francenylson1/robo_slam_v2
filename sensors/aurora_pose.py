"""
sensors/aurora_pose.py
A pose do Slamtec Aurora dentro do frota-robo (Fase 4, desenho de 29/09/2026).

ONDE VIVE (decisão 1): thread própria. O SDK fala pela rede e uma chamada pode
travar se o Aurora for desligado ou o cabo sair. Se a leitura estivesse no loop
de 50 Hz, o travamento congelaria o loop, o watchdog reiniciaria o serviço e o
robô ASSISTIVO pararia por causa do Aurora. Aqui o loop só lê o último valor.

RISCO CONHECIDO: o SDK é nativo (C++). Um segfault derruba o processo inteiro,
bumper junto — o robô para e o systemd o traz de volta em ~8 s. Prova de
bancada antes da missão: 1 h ligado + cabo do Aurora puxado com o serviço no
ar. Se o SDK derrubar o processo, o Aurora vai para um serviço separado.

UM CLIENTE SÓ (decisão 6): este é o único cliente do Aurora durante a
operação. Os scripts de bancada se recusam a rodar com o frota-robo ativo.

A PARTIDA (decisão 4) roda AQUI, na mesma thread, porque é o mesmo cliente:
zerar → carregar o mapa → relocalizar → conferir com a fita. É a sequência de
scripts/aurora_carregar_mapa.py, provada na bancada em 25 e 28/09. Só com o
robô parado; aborta se ele andar. Quem pede é o botão do dashboard (com login).

Só fala com o Aurora — não comanda motor nem toca em GPIO.
"""

import hashlib
import logging
import math
import os
import statistics
import threading
import time

from sensors.pose_source import Pose, PoseValidator, centro_do_robo

log = logging.getLogger(__name__)

# Valores do SDK (slamtec_aurora_sdk.data_types, DEVICE_STATUS_*), conferidos
# no SDK 2.1.1 da Pi em 29/09/2026.
ST_INICIALIZADO       = 0
ST_INIT_FALHOU        = 1
ST_TRACKING_PERDIDO   = 4
ST_TRACKING_RECUPERADO = 5
ST_MAPA_ZERADO        = 7
ST_MAPA_TROCADO       = 8
ST_CARREGANDO_MAPA    = 9
ST_MAPA_CARREGADO     = 11
ST_RELOC_OK           = 13
ST_RELOC_FALHOU       = 14
ST_RELOC_CANCELADA    = 15
ST_RELOC_INICIADA     = 16
RELOC_SUCCEED         = 2    # DEVICE_RELOCALIZATION_STATUS_SUCCEED (outro canal)

# Eventos que tiram o Aurora do mapa carregado: depois deles, só a fita de novo.
ST_PERDE_MAPA = {ST_INIT_FALHOU, ST_MAPA_ZERADO, ST_MAPA_TROCADO,
                 ST_CARREGANDO_MAPA, ST_RELOC_FALHOU, ST_RELOC_CANCELADA,
                 ST_RELOC_INICIADA}


class PartidaAbortada(Exception):
    """repetir=True: falha do lado do Aurora (vale tentar de novo sozinho).
    repetir=False: o robô andou, mapa errado, fora da fita — o operador decide."""
    def __init__(self, msg, repetir=False):
        super().__init__(msg)
        self.repetir = repetir


def sha256_arquivo(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _sdk_real():
    from slamtec_aurora_sdk import AuroraSDK
    return AuroraSDK()


def _laser_do_sdk(sdk, max_pontos):
    """(info, pontos, pose_se3) da última volta do laser do Aurora, ou None.
    O get_recent_lidar_scan() do SDK 2.1.1 joga fora a pose da varredura;
    a função C por baixo dele a entrega — é ela que usamos."""
    dp = sdk.data_provider
    return dp._c_bindings.peek_recent_lidar_scan(dp._controller.session_handle,
                                                 max_pontos)


def _yaw_do_quaternion(q) -> float:
    return math.degrees(math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                                   1.0 - 2.0 * (q.y * q.y + q.z * q.z)))


class AuroraPose:
    """Fonte de pose do Aurora. Interface: ver sensors/pose_source.py."""

    fonte = "aurora"

    def __init__(self, *, ip: str, mapa: str, mapa_sha256: str,
                 validator: PoseValidator, poll_s: float = 0.1,
                 backoff_s=(1.0, 2.0, 5.0, 10.0), partida_limite_s: float = 60.0,
                 espera_zerar_s: float = 2.0, espera_mapa_s: float = 4.0,
                 mediana_s: float = 1.0, status_mapa_s: float = 10.0,
                 quieto_s: float = 3.0, tentativas: int = 2,
                 braco_m=(0.0, 0.0), laser_periodo_s: float = 0.0,
                 laser_max_pontos: int = 8192, laser_fn=None,
                 sdk_factory=None, clock=time.monotonic, sleep=time.sleep):
        self.ip               = ip
        # Onde o ponto do Aurora fica em relação ao centro de giro (frente,
        # esquerda), em metros. Toda pose sai daqui já no CENTRO do robô, e o
        # validador recebe a fita convertida da mesma forma (main.py).
        self.braco_m          = tuple(braco_m)
        self.mapa             = mapa
        self.mapa_sha256      = mapa_sha256
        self.v                = validator
        self.poll_s           = poll_s
        self.backoff_s        = tuple(backoff_s)
        self.partida_limite_s = partida_limite_s
        # Esperas medidas na bancada de 25/09 (o harness as encurta):
        # depois de zerar, o rastreio assenta; depois de carregar, o mapa.
        self.espera_zerar_s   = espera_zerar_s
        self.espera_mapa_s    = espera_mapa_s
        self.mediana_s        = mediana_s
        self.status_mapa_s    = status_mapa_s   # quanto esperar pelo 11 depois do upload
        self.quieto_s         = quieto_s        # depois de zerar: 0 e silêncio por este tempo
        self.tentativas       = tentativas
        self._sdk_factory     = sdk_factory or _sdk_real
        self._clock           = clock
        self._sleep           = sleep
        self._sdk             = None
        self._conectado       = False
        self._running         = False
        self._thread          = None
        self._pose_ts         = None     # carimbo do SDK da última pose lida
        self._status_ts       = None     # carimbo do SDK do último status lido
        self._lock            = threading.Lock()
        self._partida_pedida  = None     # parado_fn, enquanto houver pedido
        self.partida          = {"passo": None, "resultado": None, "quando": None}
        self.reconexoes       = 0
        self.ultimo_status    = None
        # Varredura do LASER do Aurora (a 1,45 m), só para gravar — 01/10/2026:
        # mede com dados reais o quanto um C1 naquela altura localizaria.
        # 0 = desligado. Nunca afeta a pose: erro aqui é contado e esquecido.
        self.laser_periodo_s  = laser_periodo_s
        self.laser_max_pontos = laser_max_pontos
        self._laser_fn        = laser_fn or _laser_do_sdk
        self._laser           = None     # último registro (dict), ou None
        self._laser_lido_em   = None
        self.laser_lidos      = 0
        self.laser_erros      = 0

    # ─────────────────────────────────────────
    # INTERFACE DE FONTE DE POSE
    # ─────────────────────────────────────────
    def pose_valida(self, max_idade_s=None):
        return self.v.avaliar(max_idade_s)[0]

    def motivo(self, max_idade_s=None) -> str:
        return self.v.avaliar(max_idade_s)[1]

    def health(self) -> dict:
        p, motivo = self.v.avaliar()
        ult = p or self.v.ultima()
        idade = None if ult is None else round(self._clock() - ult.t, 2)
        return {
            "fonte":      "aurora",
            "conectado":  self._conectado,
            "valida":     p is not None,
            "motivo":     motivo,
            # Os números aparecem mesmo com a pose inválida (para a bancada),
            # mas o dashboard só desenha o robô quando "valida" é True.
            "x_cm":       None if ult is None else round(ult.x_m * 100, 1),
            "y_cm":       None if ult is None else round(ult.y_m * 100, 1),
            "rumo_deg":   None if ult is None else round(ult.rumo_deg, 1),
            "idade_s":    idade,
            "partida":    dict(self.partida),
            "saltos":     self.v.saltos,
            "reconexoes": self.reconexoes,
            "status_aurora": self.ultimo_status,
            "laser": {"lidos": self.laser_lidos, "erros": self.laser_erros},
        }

    # ─────────────────────────────────────────
    # PARTIDA — pedida pelo dashboard, executada na thread
    # ─────────────────────────────────────────
    def pedir_partida(self, parado_fn) -> tuple[bool, str]:
        """Enfileira a partida. parado_fn() → True se o robô está parado."""
        with self._lock:
            if self._partida_pedida is not None or self.partida["passo"]:
                return False, "a partida já está em andamento"
            if not self._conectado:
                return False, "Aurora desconectado"
            if not parado_fn():
                return False, "o robô precisa estar parado"
            self._partida_pedida = parado_fn
            self.partida = {"passo": "na fila", "resultado": None,
                            "quando": time.time()}
        return True, "partida iniciada"

    # ─────────────────────────────────────────
    # CICLO DE VIDA
    # ─────────────────────────────────────────
    def start(self):
        # Importar o SDK AQUI, na thread principal, antes do loop de 50 Hz
        # começar. Medido na Pi em 29/09/2026: o import leva ~146 ms (numpy +
        # bindings) e segura o GIL o tempo todo. Feito dentro da thread, com o
        # loop já rodando, deu um ciclo atrasado de 144 ms na partida do
        # serviço. As chamadas ao SDK depois disso são por ctypes.CDLL, que
        # solta o GIL — não atrasam o loop.
        if self._sdk_factory is _sdk_real:
            try:
                import slamtec_aurora_sdk  # noqa: F401
            except ImportError as e:
                log.error(f"[AuroraPose] SDK do Aurora ausente: {e} — pose inválida.")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="AuroraPose")
        self._thread.start()
        log.info(f"[AuroraPose] Iniciado — Aurora em {self.ip}.")

    def stop(self):
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._desconectar()

    # ─────────────────────────────────────────
    # THREAD
    # ─────────────────────────────────────────
    def _loop(self):
        tentativa = 0
        while self._running:
            try:
                self._conectar()
                tentativa = 0
                while self._running:
                    if self._partida_pedida is not None:
                        self._executar_partida()
                    if not self._ler():
                        raise ConnectionError("conexão com o Aurora caiu")
                    self._sleep(self.poll_s)
            except Exception as e:
                if self._running:
                    log.error(f"[AuroraPose] {e}")
            finally:
                self._desconectar()
            if not self._running:
                break
            espera = self.backoff_s[min(tentativa, len(self.backoff_s) - 1)]
            tentativa += 1
            self.reconexoes += 1
            log.warning(f"[AuroraPose] Sem Aurora — pose inválida. Reconectando em "
                        f"{espera:g} s (tentativa {tentativa}).")
            self._esperar(espera)

    def _esperar(self, s: float):
        fim = self._clock() + s
        while self._running and self._clock() < fim:
            self._sleep(min(0.2, s))

    def _conectar(self):
        self._sdk = self._sdk_factory()
        self._sdk.connect(connection_string=self.ip)
        self._pose_ts = None
        # O status que já estava guardado no Aurora não é notícia: anota o
        # carimbo para só reagir a eventos NOVOS (o erro de 25/09).
        try:
            st, self._status_ts = self._sdk.data_provider.get_last_device_status()
            self.ultimo_status = st
        except Exception:
            self._status_ts = None
        self.v.on_conectou()
        self._conectado = True
        log.info(f"[AuroraPose] Conectado ao Aurora em {self.ip}. "
                 f"Pose inválida até 'Localizar na fita'.")

    def _desconectar(self):
        if self._conectado:
            log.warning("[AuroraPose] Desconectado do Aurora.")
        self._conectado = False
        self.v.on_desconectou()
        sdk, self._sdk = self._sdk, None
        if sdk is not None:
            for fn in ("disconnect", "release"):
                try:
                    getattr(sdk, fn)()
                except Exception:
                    pass
        with self._lock:
            if self._partida_pedida is not None or self.partida["passo"]:
                self.partida = {"passo": None,
                                "resultado": "falhou: Aurora desconectou",
                                "quando": time.time()}
            self._partida_pedida = None

    def _ler(self) -> bool:
        """Uma leitura de pose e de status. False = a conexão caiu."""
        sdk = self._sdk
        try:
            if not sdk.controller.is_device_connection_alive():
                return False
        except Exception:
            return False
        try:
            pos, rpy, ts = sdk.data_provider.get_current_pose(use_se3=False)
            if ts != self._pose_ts:
                self._pose_ts = ts
                self.v.on_pose(self._pose_do_centro(pos, rpy, self._clock()))
        except Exception as e:
            log.debug(f"[AuroraPose] Pose indisponível: {e}")
        try:
            st, ts = sdk.data_provider.get_last_device_status()
            if ts != self._status_ts:
                self._status_ts = ts
                self._on_status(st)
        except Exception as e:
            log.debug(f"[AuroraPose] Status indisponível: {e}")
        self._talvez_ler_laser(sdk)
        return True

    # ─────────────────────────────────────────
    # LASER DO AURORA — só para o gravador
    # ─────────────────────────────────────────
    def ultimo_laser(self):
        """Último registro do laser: {"t", "ts", "dyaw", "kf", "pose", "p"},
        ou None. "t" é do relógio monotônico do serviço (para a idade)."""
        return self._laser

    def _talvez_ler_laser(self, sdk):
        if self.laser_periodo_s <= 0 or self.partida["passo"]:
            return
        agora = self._clock()
        if self._laser_lido_em is not None and agora - self._laser_lido_em < self.laser_periodo_s:
            return
        self._laser_lido_em = agora
        try:
            r = self._laser_fn(sdk, self.laser_max_pontos)
            if r is None:
                return
            info, pontos, pose = r
            p = [[int(round(math.degrees(pt.angle) * 100)) % 36000,
                  int(round(pt.dist * 1000)), int(pt.quality)]
                 for pt in pontos if pt.quality > 0 and pt.dist > 0]
            t = pose.translation
            self._laser = {
                "t": agora, "ts": int(info.timestamp_ns),
                "dyaw": round(float(info.dyaw), 4), "kf": int(info.binded_kf_id),
                # pose do PRÓPRIO Aurora na hora da varredura (não do centro):
                # [x_m, y_m, z_m, rumo_graus]
                "pose": [round(t.x, 4), round(t.y, 4), round(t.z, 4),
                         round(_yaw_do_quaternion(pose.quaternion), 2)],
                "p": p}
            self.laser_lidos += 1
        except Exception as e:
            self.laser_erros += 1
            if self.laser_erros == 1 or self.laser_erros % 60 == 0:
                log.warning(f"[AuroraPose] Laser do Aurora indisponível "
                            f"({self.laser_erros}x): {e} — a pose não é afetada.")

    def _pose_do_centro(self, pos, rpy, t) -> Pose:
        rumo = math.degrees(rpy[2])
        x, y = centro_do_robo(pos[0], pos[1], rumo, self.braco_m)
        return Pose(x, y, rumo, t)

    def _on_status(self, st):
        self.ultimo_status = st
        log.info(f"[AuroraPose] Status do Aurora: {st}")
        if st == ST_TRACKING_PERDIDO:
            log.warning("[AuroraPose] Rastreio PERDIDO — pose inválida.")
            self.v.on_tracking(False)
        elif st == ST_TRACKING_RECUPERADO:
            log.info("[AuroraPose] Rastreio recuperado — 1 s estável para valer.")
            self.v.on_tracking(True)
        elif st in ST_PERDE_MAPA and not self.partida["passo"]:
            # Fora de uma partida nossa, alguém mexeu no mapa do Aurora.
            self.v.invalidar_localizacao("o Aurora saiu do mapa — localizar na fita")

    # ─────────────────────────────────────────
    # A SEQUÊNCIA DA PARTIDA
    # ─────────────────────────────────────────
    def _passo(self, nome: str):
        with self._lock:
            self.partida = {"passo": nome, "resultado": None,
                            "quando": time.time()}
        log.info(f"[AuroraPose] Partida: {nome}")

    def _executar_partida(self):
        parado_fn = self._partida_pedida
        resultado = "falhou"
        self.v.invalidar_localizacao("partida em andamento")
        try:
            for tentativa in range(1, self.tentativas + 1):
                try:
                    msg = self._sequencia(parado_fn, tentativa)
                    resultado = f"ok: {msg}" + (f" (na {tentativa}ª tentativa)"
                                                if tentativa > 1 else "")
                    log.info(f"[AuroraPose] Partida VERDE — {resultado}.")
                    break
                except PartidaAbortada as e:
                    resultado = f"falhou: {e}"
                    log.error(f"[AuroraPose] Partida FALHOU (tentativa {tentativa}) — {e}")
                    self.v.invalidar_localizacao(f"partida falhou: {e}")
                    if not e.repetir or tentativa == self.tentativas:
                        break
                    log.warning("[AuroraPose] Falha do lado do Aurora — repetindo a sequência.")
        except Exception as e:
            self.v.invalidar_localizacao(f"partida falhou: {e}")
            resultado = f"falhou: {e}"
            log.error(f"[AuroraPose] Partida FALHOU — {e}")
            raise           # erro de SDK: deixa o laço reconectar
        finally:
            with self._lock:
                self._partida_pedida = None
                self.partida = {"passo": None, "resultado": resultado,
                                "quando": time.time()}

    def _sequencia(self, parado_fn, tentativa: int) -> str:
        sufixo = f" (tentativa {tentativa})" if tentativa > 1 else ""
        self._passo("conferindo o mapa" + sufixo)
        if not os.path.isfile(self.mapa):
            raise PartidaAbortada(f"mapa não encontrado: {self.mapa}")
        if sha256_arquivo(self.mapa) != self.mapa_sha256:
            raise PartidaAbortada("o arquivo do mapa não é o combinado (sha diferente)")
        self._checar_parado(parado_fn)

        # ZERAR. Bancada de 29/09 (10:29 e 11:23): o Aurora às vezes responde
        # "falhou" (1) e "inicializado" (0) quase juntos, e manda OUTRO 0
        # segundos depois — reinicializa e apaga o mapa que acabamos de
        # carregar. Por isso: esperar o 0 e depois SILÊNCIO por quieto_s.
        self._passo("zerando" + sufixo)
        self._pedir(self._sdk.controller.require_map_reset,
                    {ST_INICIALIZADO}, set(), self.partida_limite_s, parado_fn)
        self._esperar_quieto(ST_INICIALIZADO, parado_fn)
        self._aguardar(self.espera_zerar_s, parado_fn)

        # CARREGAR. Exige o 11 ("mapa carregado"). Sem ele, a tentativa falha.
        self._passo("carregando o mapa" + sufixo)
        self._pedir(lambda: self._sdk.map_manager.upload_map(
                        self.mapa, timeout_seconds=180),
                    {ST_MAPA_CARREGADO}, set(), self.status_mapa_s, parado_fn,
                    exige_true=True)
        self._aguardar(self.espera_mapa_s, parado_fn)

        # RELOCALIZAR. O True do SDK é "pedido aceito", NÃO sucesso (visto em
        # 29/09 11:23: devolveu True e depois veio 14). Vale o 13 novo ou o
        # canal próprio da relocalização (2 = SUCCEED).
        self._passo("relocalizando" + sufixo)
        self._pedir(lambda: self._sdk.controller.require_relocalization(
                        timeout_ms=20000),
                    {ST_RELOC_OK}, {ST_RELOC_FALHOU, ST_RELOC_CANCELADA},
                    25.0, parado_fn, exige_true=True,
                    confirma=lambda: self._sdk.controller
                    .get_last_relocalization_status() == RELOC_SUCCEED)

        self._passo("conferindo com a fita" + sufixo)
        pose = self._pose_mediana(self.mediana_s, parado_fn)
        ok, msg = self.v.on_localizou(pose)
        if not ok:
            raise PartidaAbortada(msg)
        return msg

    def _esperar_quieto(self, esperado, parado_fn):
        """Depois do status esperado, nenhum status novo por quieto_s. Um novo
        'falhou' (1) volta a esperar o esperado; um novo esperado reinicia o
        silêncio."""
        fim = self._clock() + self.partida_limite_s
        quieto_ate = self._clock() + self.quieto_s
        aguardando = False
        while self._clock() < fim:
            self._checar_parado(parado_fn)
            if not self._running:
                raise PartidaAbortada("serviço encerrando")
            st, carimbo = self._sdk.data_provider.get_last_device_status()
            if carimbo != self._status_ts:
                self._status_ts = carimbo
                self.ultimo_status = st
                log.info(f"[AuroraPose]   status novo: {st} (esperando o Aurora sossegar)")
                aguardando = st != esperado
                quieto_ate = self._clock() + self.quieto_s
            if not aguardando and self._clock() >= quieto_ate:
                return
            self._sleep(self.poll_s)
        raise PartidaAbortada("o Aurora não sossegou depois de zerar", repetir=True)

    def _checar_parado(self, parado_fn):
        if not parado_fn():
            raise PartidaAbortada("o robô andou durante a partida")

    def _aguardar(self, s: float, parado_fn):
        fim = self._clock() + s
        while self._clock() < fim:
            self._checar_parado(parado_fn)
            if not self._running:
                raise PartidaAbortada("serviço encerrando")
            self._sleep(min(0.25, s))

    def _pedir(self, acao, esperados, falhas, limite_s, parado_fn, *,
                exige_true=False, confirma=None):
        """
        Anota o carimbo do status, executa a ação e espera um status NOVO.
        Só vale resposta nova: o Aurora guarda o último status (erro de 25/09).

        exige_true      — a ação precisa devolver True (upload, relocalização).
        confirma        — outra prova de sucesso, consultada a cada volta.
        Todo status novo visto vai para o log, para a próxima surpresa ter
        registro.
        """
        _, carimbo0 = self._sdk.data_provider.get_last_device_status()
        ret = acao()
        if ret is False or (exige_true and ret is not True):
            raise PartidaAbortada("o Aurora recusou o pedido", repetir=True)
        vistos = []
        fim = self._clock() + limite_s
        while True:
            self._checar_parado(parado_fn)
            if not self._running:
                raise PartidaAbortada("serviço encerrando")
            st, carimbo = self._sdk.data_provider.get_last_device_status()
            if carimbo != carimbo0:
                if carimbo != self._status_ts:
                    vistos.append(st)
                    log.info(f"[AuroraPose]   status novo: {st}")
                self._status_ts = carimbo
                self.ultimo_status = st
                if st in esperados:
                    return st
                if st in falhas:
                    raise PartidaAbortada(f"o Aurora respondeu status {st}", repetir=True)
            if confirma is not None and confirma():
                log.info("[AuroraPose]   confirmado pelo canal próprio.")
                return st
            if self._clock() >= fim:
                break
            self._sleep(self.poll_s)
        raise PartidaAbortada(f"o Aurora não deu o status {sorted(esperados)} em "
                              f"{limite_s:g} s (vistos: {vistos or 'nenhum'})",
                              repetir=True)

    def _pose_mediana(self, s: float, parado_fn) -> Pose:
        """Mediana das poses por `s` segundos (como o pose_ref.sh da bancada)."""
        xs, ys, rs = [], [], []
        fim = self._clock() + s
        ref = None
        while self._clock() < fim:
            self._checar_parado(parado_fn)
            pos, rpy, _ = self._sdk.data_provider.get_current_pose(use_se3=False)
            p = self._pose_do_centro(pos, rpy, 0.0)
            r = p.rumo_deg
            ref = r if ref is None else ref
            # Rumo "desenrolado" em torno da 1ª leitura: a mediana de 179° e
            # −179° tem que dar 180°, não 0°.
            rs.append(ref + ((r - ref + 180.0) % 360.0 - 180.0))
            xs.append(p.x_m)
            ys.append(p.y_m)
            self._sleep(self.poll_s)
        if not xs:
            raise PartidaAbortada("nenhuma pose lida para conferir com a fita")
        return Pose(statistics.median(xs), statistics.median(ys),
                    statistics.median(rs), self._clock())
