"""
slam/nova_fita.py
FITA NOVA num ambiente PRONTO (29/10/2026, pedido do Prof.): mudar a fita de
lugar sem mapear de novo. Página: https://claude.ai/artifact/EMSb9CLbarGxp2uWUUQCAP

A fita tem dois papéis: é o ponto que "Localizar na fita" confere (15 cm / 5°)
e é a BASE das missões. Mudar só a fita do chão quebra os dois. Aqui:

  1. medir(quem)      → robô parado sobre a fita nova: o Aurora zera, carrega o
                        mapa do ambiente ATIVO, relocaliza e mede duas vezes
                        (a mesma medida do mapeamento)       [medindo → medida]
  2. o operador confere no /mapa onde a fita nova caiu (/api/nav "fita_nova")
  3. confirmar(quem)  → grava na ficha (a antiga fica guardada) e o servidor
                        reinicia o serviço; depois, "Localizar na fita"
     descartar(quem)  → nada é gravado; "Localizar na fita" na fita antiga

Recusa a fita nova fora da planta ou com o centro dentro do limite do vigia
(o robô nem sairia dali). Abaixo da margem, só avisa: a missão sai pela faixa
de tolerância, como já sai hoje de perto de mesa.

A medida não troca a fita do validador: até confirmar, a pose não vale. Nada
aqui move o robô.
"""

import logging
import math
import threading
import time

from sensors.pose_source import fita_do_centro

log = logging.getLogger(__name__)


class NovaFita:

    def __init__(self, ambientes, aurora, *, impedimentos_fn, parado_fn, braco_m,
                 plan_fn=lambda: None, fita_tol=(0.02, 1.0)):
        self.ambientes      = ambientes
        self.aurora         = aurora
        self._impedimentos  = impedimentos_fn
        self._parado        = parado_fn
        self.braco_m        = braco_m
        self._plan          = plan_fn
        self.fita_tol       = fita_tol
        self._lock          = threading.RLock()
        self._pedido_em     = 0.0
        self.e              = None         # {"fase": "medindo"|"medida", ...}
        self.ultimo         = None         # {"ok", "msg"} do último que terminou

    @property
    def ativo(self) -> bool:
        return self.e is not None

    def estado(self) -> dict:
        with self._lock:
            d = dict(self.e) if self.e else {"fase": None}
            d["ultimo"] = self.ultimo
            if self.aurora is not None and self.aurora.trabalho.get("nome") == "medir_fita_nova":
                d["aurora_passo"] = self.aurora.trabalho.get("passo")
            return d

    def centro_pendente(self):
        """(x, y, rumo) do CENTRO do robô na fita nova medida, para o /mapa."""
        with self._lock:
            if self.e is None or self.e["fase"] != "medida":
                return None
            return self.e["centro"]

    # ─── os passos ────────────────────────────
    def medir(self, quem):
        with self._lock:
            if self.e is not None:
                return False, ("já há uma fita nova medida — confirme ou descarte"
                               if self.e["fase"] == "medida" else "a medida já está em andamento")
            if self.aurora is None:
                return False, "este robô não tem Aurora — só o robô 1 mede a fita"
            a = self.ambientes.ativo() if self.ambientes is not None else None
            if a is None or a["estado"] == "invalido":
                return False, "nenhum ambiente válido ativo — escolha um em Ambientes"
            imp = self._impedimentos()
            if imp:
                return False, imp
            if not self._parado():
                return False, "o robô precisa estar parado sobre a fita nova"
            if self.aurora.ocupado:
                return False, "o Aurora está ocupado (partida ou mapeamento em andamento?)"
            ok, msg = self.aurora.pedir_trabalho("medir_fita_nova", self._parado,
                                                 tol_m=self.fita_tol[0], tol_deg=self.fita_tol[1])
            if not ok:
                return False, msg
            self._pedido_em = time.time()
            self.e = {"fase": "medindo", "quem": quem, "ambiente": a["id"],
                      "nome": a["nome"], "antiga": a["fita"], "erro": None}
            self.ultimo = None
            log.info(f"[NovaFita] {quem} pediu a medida da fita nova em {a['id']}.")
            return True, "medindo a fita nova — não mexa no robô (~20 s)"

    def confirmar(self, quem):
        with self._lock:
            if self.e is None or self.e["fase"] != "medida":
                return False, "não há fita nova medida para confirmar"
            imp = self._impedimentos()
            if imp:
                return False, imp
            if not self._parado():
                return False, "o robô precisa estar parado (o serviço vai reiniciar)"
            ok, msg = self.ambientes.trocar_fita(self.e["ambiente"], self.e["nova"], quem,
                                                 medida=self.e["medida"])
            if not ok:
                return False, msg
            self.ultimo = {"ok": True, "msg": "fita nova gravada — o robô reinicia; "
                                              "depois, 'Localizar na fita' sobre ela"}
            self.e = None
            return True, self.ultimo["msg"]

    def descartar(self, quem):
        with self._lock:
            if self.e is None:
                return False, "não há fita nova medida"
            if self.e["fase"] != "medida":
                return False, "aguarde a medida terminar"
            self.e = None
            self.ultimo = {"ok": False, "msg": "fita nova descartada — nada foi gravado; "
                                               "'Localizar na fita' na fita de antes"}
            log.info(f"[NovaFita] {quem} descartou a fita nova.")
            return True, self.ultimo["msg"]

    # ─── acompanhamento (o main chama a cada ~0,5 s) ─
    def tick(self):
        with self._lock:
            if self.e is None or self.e["fase"] != "medindo":
                return
            t = self.aurora.trabalho
            if (t.get("nome") != "medir_fita_nova" or t.get("passo") is not None
                    or t.get("resultado") is None or (t.get("quando") or 0) < self._pedido_em):
                return
            if t["resultado"] != "ok":
                self.ultimo = {"ok": False, "msg": t["resultado"]}
                self.e = None
                return
            dados = t.get("dados") or {}
            nova = [float(v) for v in dados["fita"]]
            centro = fita_do_centro(nova, self.braco_m)
            problema, folga = self._conferir_lugar(centro)
            if problema:
                self.ultimo = {"ok": False, "msg": problema}
                self.e = None
                log.warning(f"[NovaFita] Fita nova recusada: {problema}")
                return
            antiga = self.e.get("antiga")
            dist = da = None
            if antiga:
                dist = round(math.hypot(nova[0] - antiga[0], nova[1] - antiga[1]) * 100, 1)
                da = round(abs((nova[2] - antiga[2] + 180.0) % 360.0 - 180.0), 1)
            self.e.update(fase="medida", nova=nova, centro=[round(v, 4) for v in centro],
                          medida=dados, distancia_cm=dist, rumo_dif_deg=da,
                          folga_cm=None if folga is None else round(folga * 100),
                          margem_cm=(round(self._plan().margem_m * 100)
                                     if self._plan() is not None else None))
            log.info(f"[NovaFita] Fita nova medida: {nova} ({dist} cm, {da}° da antiga; "
                     f"folga {self.e['folga_cm']} cm).")

    def _conferir_lugar(self, centro):
        """(motivo de recusa ou None, folga do centro em m ou None)."""
        plan = self._plan()
        if plan is None:
            return None, None
        x, y = centro[0], centro[1]
        if not plan.pl.dentro(*plan.pl.celula(x, y)):
            return "a fita nova caiu fora da planta deste ambiente — o Aurora se achou no lugar errado?", None
        folga = plan.folga(x, y)
        if not plan.seguro(x, y):
            return (f"o centro do robô na fita nova fica a {folga * 100:.0f} cm de parede ou área "
                    f"proibida — perto demais para sair dali (afaste a fita)"), folga
        return None, folga
