"""O monitor da pauta: sincroniza sozinho com o e-SAJ e o eProc (seção 8.7).

Com [pauta] monitorar ligado, uma thread do programa sincroniza as fontes
que já têm rota (a URL que funcionou na última sincronização ou captura) a
cada 'intervalo_horas' e logo ao abrir o programa, se a última passou do
intervalo - no período de 'dias_atras' a 'dias_a_frente'.

Ninguém está olhando: se o portal pedir código (e-mail, dois fatores), o
monitor NÃO bloqueia esperando - o Contexto de fundo recusa a pergunta, o
portal desiste do login, e fica o aviso "Entre no portal para continuar o
monitoramento" (evento 'aviso' e pendência na tela Início). A próxima
sincronização feita pelo usuário (que responde ao código) limpa a pendência.

Se o navegador dos portais estiver ocupado (um download em andamento), o
monitor tenta de novo em ADIAR_S - não disputa o perfil do navegador.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta

from ..servidor.trabalhos import ContextoFundo, Recusa
from ..tarefas import NAVEGADOR

log = logging.getLogger("aplicativo.monitor")

ATRASO_INICIAL_S = 20.0
ADIAR_S = 15 * 60
SEM_PAUTA_S = 3600.0
TITULO_AVISO = "Monitoramento da pauta"
MENSAGEM_LOGIN = ("Entre no portal para continuar o monitoramento: o portal pediu o código de "
                  "verificação durante a sincronização automática. Na tela Pauta, clique em "
                  "Sincronizar e informe o código.")


def _inteiro(cfg, chave: str, padrao: int) -> int:
    try:
        valor = str(cfg.texto("pauta", chave)).strip()
        return int(valor) if valor else padrao
    except (TypeError, ValueError):
        return padrao


class MonitorPauta:
    def __init__(self, app, atraso_inicial_s: float = ATRASO_INICIAL_S):
        self.app = app
        self.atraso_inicial_s = atraso_inicial_s
        self.proxima: datetime | None = None
        self.ultima_execucao: datetime | None = None
        self._acordar = threading.Event()
        self._fim = threading.Event()
        self._thread: threading.Thread | None = None

    def iniciar(self) -> "MonitorPauta":
        self._thread = threading.Thread(target=self._rodar, name="monitor-pauta", daemon=True)
        self._thread.start()
        return self

    def acordar(self) -> None:
        """A configuração mudou: reavalia agora."""
        self._acordar.set()

    def parar(self) -> None:
        self._fim.set()
        self._acordar.set()

    @property
    def ativo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ laço
    def _rodar(self) -> None:
        espera = self.atraso_inicial_s
        while not self._fim.is_set():
            self._acordar.wait(max(1.0, espera))
            self._acordar.clear()
            if self._fim.is_set() or self.app.fechando:
                break
            try:
                espera = self.ciclo()
            except Exception:
                log.exception("falha no monitoramento da pauta")
                espera = ADIAR_S

    def ciclo(self, agora: datetime | None = None) -> float:
        """Uma avaliação: sincroniza se for a hora. Devolve quantos segundos
        esperar até a próxima avaliação."""
        servico = self.app.pauta_ou_none()
        if servico is None:
            self.proxima = None
            return SEM_PAUTA_S
        try:
            estado = dict(servico.monitoramento() or {})
        except Exception:
            estado = {}
        ativo = bool(estado.get("ativo", self.app.cfg.flag("pauta", "monitorar")))
        horas = int(estado.get("intervalo_horas") or _inteiro(self.app.cfg, "intervalo_horas", 6))
        horas = max(1, horas)
        if not ativo:
            self.proxima = None
            return SEM_PAUTA_S
        intervalo = timedelta(hours=horas)
        ultima = servico.ultima_sincronizacao()
        agora = agora or datetime.now(ultima.tzinfo if ultima is not None else None)
        if ultima is not None and agora - ultima < intervalo:
            self.proxima = ultima + intervalo
            return max(1.0, (self.proxima - agora).total_seconds())
        fontes = [f for f in (servico.fontes() or [])
                  if f.get("url") or f.get("rota") or f.get("url_lembrada")]
        if not fontes:
            self.proxima = agora + intervalo
            return intervalo.total_seconds()
        if not self.sincronizar(servico, [str(f.get("id")) for f in fontes if f.get("id")]):
            self.proxima = agora + timedelta(seconds=ADIAR_S)
            return ADIAR_S
        self.proxima = datetime.now(agora.tzinfo) + intervalo
        return intervalo.total_seconds()

    def sincronizar(self, servico, fontes: list[str]) -> bool:
        """Roda a sincronização como tarefa (aparece na barra lateral) e
        espera ela acabar. False: o navegador estava ocupado."""
        app = self.app
        hoje = date.today()
        de = hoje - timedelta(days=max(0, _inteiro(app.cfg, "dias_atras", 7)))
        ate = hoje + timedelta(days=max(1, _inteiro(app.cfg, "dias_a_frente", 60)))
        pediu = {"login": False}

        def alvo(tw):
            ctx = ContextoFundo(tw, TITULO_AVISO, MENSAGEM_LOGIN)
            try:
                return servico.sincronizar(ctx, fontes or None, de, ate)
            finally:
                pediu["login"] = ctx.pediu_login

        try:
            tw = app.tarefas.iniciar("pauta_sincronizar", "Monitoramento da pauta", alvo,
                                     (NAVEGADOR,), chave="pauta_sincronizar")
        except Recusa as erro:
            log.info("monitoramento da pauta adiado: %s", erro)
            return False
        while not tw.esperar(1.0):
            if self._fim.is_set():
                tw.pedir_parada()
                tw.esperar(10)
                break
        self.ultima_execucao = datetime.now()
        if pediu["login"]:
            app.pendencia_pauta = {"chave": "pauta_login", "titulo": TITULO_AVISO,
                                   "mensagem": MENSAGEM_LOGIN, "acao": "pauta"}
        elif tw.estado == "concluida":
            app.pendencia_pauta = None
        app.hub.publicar("estado", {})
        return True
