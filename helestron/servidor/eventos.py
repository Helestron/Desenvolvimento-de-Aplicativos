"""O hub de eventos: o que o motor diz chega a todas as páginas abertas.

Server-Sent Events (seção 6.4 da especificação): cada página conectada em
GET /api/eventos ganha uma fila própria, e publicar() põe o evento em todas
as filas. Por que uma fila por cliente, e não uma lista global com cursor:
uma página lenta (aba em segundo plano, janela minimizada) não segura as
outras, e a página que reconecta recomeça limpa - o que perdeu ela relê
por GET /api/estado, que é para isso que o evento 'estado' existe.

A fila tem limite: se uma página parar de ler (travou, foi suspensa), o
evento mais velho é descartado no lugar do novo - um medidor de nível do
microfone de dez minutos atrás não serve para nada, e a memória não cresce
sem fim.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import PurePath

log = logging.getLogger("servidor.eventos")

INTERVALO_PING_S = 15.0
LIMITE_FILA = 2000
_FIM = object()          # sentinela: o hub fechou, a conexão deve terminar


def para_json(valor):
    """O 'default' do json.dumps: datas em ISO 8601, caminhos como texto.

    Tudo o que o motor devolve (Path, datetime, dataclass, set) sai em JSON
    sem que cada tratador precise converter à mão.
    """
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, PurePath):
        return str(valor)
    if is_dataclass(valor) and not isinstance(valor, type):
        return asdict(valor)
    if isinstance(valor, (set, frozenset, tuple)):
        return list(valor)
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace")
    como_dict = getattr(valor, "como_dict", None)
    if callable(como_dict):
        return como_dict()
    return str(valor)


def json_texto(dados) -> str:
    return json.dumps(dados, ensure_ascii=False, default=para_json, separators=(",", ":"))


def formatar_sse(tipo: str, dados) -> bytes:
    """Um evento no formato do EventSource: 'event:' + 'data:' + linha em branco.

    O JSON sai numa linha só (separators compactos e sem quebra), então não
    há 'data:' de várias linhas para o navegador remontar.
    """
    texto = json_texto(dados if dados is not None else {})
    texto = texto.replace("\r", "\\r").replace("\n", "\\n")
    return f"event: {tipo}\ndata: {texto}\n\n".encode("utf-8")


class Assinatura:
    """A fila de uma página conectada."""

    def __init__(self, hub: "HubEventos", limite: int = LIMITE_FILA):
        self.hub = hub
        self.fila: queue.Queue = queue.Queue(maxsize=limite)
        self.criada = time.monotonic()
        self.descartados = 0

    def entregar(self, item) -> None:
        while True:
            try:
                self.fila.put_nowait(item)
                return
            except queue.Full:
                try:
                    self.fila.get_nowait()
                    self.descartados += 1
                except queue.Empty:
                    pass

    def proximo(self, espera_s: float = INTERVALO_PING_S):
        """O próximo (tipo, dados); None se nada chegou no prazo (hora do
        ping); o sentinela _FIM se o hub fechou."""
        try:
            return self.fila.get(timeout=espera_s)
        except queue.Empty:
            return None

    def cancelar(self) -> None:
        self.hub.cancelar(self)


class HubEventos:
    """Difusão de eventos para todas as páginas conectadas."""

    def __init__(self):
        self._trava = threading.Lock()
        self._assinaturas: list[Assinatura] = []
        self._fechado = False
        self.ultimo_contato = time.monotonic()
        self.publicados = 0

    # ------------------------------------------------------------ assinar
    def assinar(self) -> Assinatura:
        a = Assinatura(self)
        with self._trava:
            if self._fechado:
                a.entregar(_FIM)
            else:
                self._assinaturas.append(a)
        self.tocar()
        return a

    def cancelar(self, assinatura: Assinatura) -> None:
        with self._trava:
            if assinatura in self._assinaturas:
                self._assinaturas.remove(assinatura)

    @property
    def conectados(self) -> int:
        with self._trava:
            return len(self._assinaturas)

    def tocar(self) -> None:
        """Registra sinal de vida da página (conexão, ping, evento entregue)."""
        self.ultimo_contato = time.monotonic()

    # ---------------------------------------------------------- publicar
    def publicar(self, tipo: str, dados=None) -> None:
        """Entrega o evento a todas as páginas. Nunca levanta: quem publica é
        a thread de trabalho, que não pode cair por causa da interface."""
        try:
            with self._trava:
                if self._fechado:
                    return
                alvos = list(self._assinaturas)
                self.publicados += 1
            item = (str(tipo), dados if dados is not None else {})
            for a in alvos:
                a.entregar(item)
        except Exception:                      # pragma: no cover - defesa
            log.exception("falha ao publicar o evento %s", tipo)

    def __call__(self, tipo: str, dados=None) -> None:
        self.publicar(tipo, dados)

    # ------------------------------------------------------------ fechar
    def fechar(self) -> None:
        """Encerra todas as conexões abertas (o programa está fechando)."""
        with self._trava:
            self._fechado = True
            alvos, self._assinaturas = self._assinaturas, []
        for a in alvos:
            a.entregar(_FIM)

    @property
    def fechado(self) -> bool:
        return self._fechado


FIM = _FIM
