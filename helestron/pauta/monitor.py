"""Quando sincronizar a pauta sozinho (seção 8.7) - a decisão, sem a thread.

Quem cria a thread é o aplicativo (helestron/aplicativo/monitor.py): ele
acorda, pergunta "e agora?" e dorme o tempo devolvido. A decisão mora aqui,
pura e com o relógio injetável, para ser testada sem esperar seis horas:

* monitoramento desligado: não sincroniza (reavalia em uma hora, ou quando
  o usuário religar);
* nenhuma fonte com rota (URL que já funcionou): não há o que conferir
  sozinho - espera o intervalo;
* a última sincronização passou do intervalo (ou nunca houve): sincroniza
  AGORA - é o "ao abrir o programa, se a última passou do intervalo";
* senão: espera até última + intervalo.

O período conferido é de 'dias_atras' antes de hoje a 'dias_a_frente'
depois. A configuração vem de [pauta] no config.ini, com padrões firmes
para chave ausente ou valor estragado (monitorar=true, 6 h, 7 e 60 dias).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

PADRAO_ATIVO = True
PADRAO_INTERVALO_H = 6
PADRAO_DIAS_ATRAS = 7
PADRAO_DIAS_A_FRENTE = 60
INTERVALO_MIN_H, INTERVALO_MAX_H = 1, 72
SEM_MONITORAMENTO_S = 3600.0       # desligado: reavalia de hora em hora
ADIAR_S = 15 * 60                  # navegador ocupado (um download): tenta de novo em 15 min

_VERDADE = ("1", "true", "sim", "s", "yes", "on", "verdadeiro")
_MENTIRA = ("0", "false", "nao", "não", "n", "no", "off", "falso")


def _texto(cfg, chave: str) -> str:
    try:
        return str(cfg.texto("pauta", chave) or "").strip()
    except Exception:
        return ""


def ler_flag(cfg, chave: str, padrao: bool) -> bool:
    valor = _texto(cfg, chave).lower()
    if valor in _VERDADE:
        return True
    if valor in _MENTIRA:
        return False
    return padrao


def ler_inteiro(cfg, chave: str, padrao: int, minimo: int, maximo: int) -> int:
    try:
        valor = int(float(_texto(cfg, chave).replace(",", ".")))
    except ValueError:
        return padrao
    return max(minimo, min(maximo, valor))


@dataclass
class ConfigMonitoramento:
    ativo: bool = PADRAO_ATIVO
    intervalo_horas: int = PADRAO_INTERVALO_H
    dias_atras: int = PADRAO_DIAS_ATRAS
    dias_a_frente: int = PADRAO_DIAS_A_FRENTE

    @classmethod
    def de_config(cls, cfg) -> "ConfigMonitoramento":
        return cls(
            ativo=ler_flag(cfg, "monitorar", PADRAO_ATIVO),
            intervalo_horas=ler_inteiro(cfg, "intervalo_horas", PADRAO_INTERVALO_H,
                                        INTERVALO_MIN_H, INTERVALO_MAX_H),
            dias_atras=ler_inteiro(cfg, "dias_atras", PADRAO_DIAS_ATRAS, 0, 366),
            dias_a_frente=ler_inteiro(cfg, "dias_a_frente", PADRAO_DIAS_A_FRENTE, 1, 3 * 366),
        )

    @property
    def intervalo(self) -> timedelta:
        return timedelta(hours=max(INTERVALO_MIN_H, int(self.intervalo_horas)))

    def periodo(self, hoje: date) -> tuple[date, date]:
        return (hoje - timedelta(days=max(0, self.dias_atras)),
                hoje + timedelta(days=max(1, self.dias_a_frente)))


@dataclass
class Decisao:
    sincronizar: bool
    esperar_s: float               # quanto dormir até reavaliar (depois de sincronizar, se for)
    proxima: datetime | None       # quando será a próxima sincronização (para a tela)
    motivo: str


class Agenda:
    """A regra do monitoramento, com o relógio injetável."""

    def __init__(self, relogio: Callable[[], datetime] | None = None):
        self.relogio = relogio or datetime.now

    def proxima(self, conf: ConfigMonitoramento, ultima: datetime | None,
                tem_fontes: bool) -> datetime | None:
        """Quando o monitor vai sincronizar (None se desligado ou sem fonte)."""
        if not conf.ativo or not tem_fontes:
            return None
        agora = self.relogio()
        if ultima is None:
            return agora
        return max(agora, ultima + conf.intervalo)

    def avaliar(self, conf: ConfigMonitoramento, ultima: datetime | None, tem_fontes: bool,
                agora: datetime | None = None) -> Decisao:
        agora = agora or self.relogio()
        if not conf.ativo:
            return Decisao(False, SEM_MONITORAMENTO_S, None, "desligado")
        if not tem_fontes:
            return Decisao(False, conf.intervalo.total_seconds(), None, "sem_fontes")
        if ultima is not None and agora - ultima < conf.intervalo:
            proxima = ultima + conf.intervalo
            return Decisao(False, max(1.0, (proxima - agora).total_seconds()), proxima,
                           "em_dia")
        return Decisao(True, conf.intervalo.total_seconds(), agora + conf.intervalo,
                       "vencida" if ultima is not None else "primeira")


class Monitor:
    """O ciclo do monitoramento sobre um ServicoPauta, sem thread.

    'sincronizar(fontes, de, ate) -> bool' faz o trabalho (o aplicativo a
    roda como tarefa, com o Contexto que não bloqueia em pergunta); False
    quer dizer "não deu agora" (navegador ocupado) e o monitor tenta de novo
    em ADIAR_S.
    """

    def __init__(self, servico, sincronizar: Callable[[list[str], date, date], bool],
                 relogio: Callable[[], datetime] | None = None, adiar_s: float = ADIAR_S):
        self.servico = servico
        self.sincronizar = sincronizar
        self.agenda = Agenda(relogio)
        self.adiar_s = adiar_s
        self.proxima: datetime | None = None
        self.ultima_decisao: Decisao | None = None

    def fontes_com_rota(self) -> list[str]:
        return [str(f.get("id")) for f in (self.servico.fontes() or [])
                if f.get("id") and f.get("url")]

    def ciclo(self) -> float:
        """Uma avaliação; devolve quantos segundos esperar até a próxima."""
        conf = ConfigMonitoramento.de_config(self.servico.cfg)
        fontes = self.fontes_com_rota()
        agora = self.agenda.relogio()
        decisao = self.agenda.avaliar(conf, self.servico.ultima_sincronizacao(), bool(fontes),
                                      agora)
        self.ultima_decisao = decisao
        self.proxima = decisao.proxima
        if not decisao.sincronizar:
            return decisao.esperar_s
        de, ate = conf.periodo(agora.date())
        if not self.sincronizar(fontes, de, ate):
            self.proxima = agora + timedelta(seconds=self.adiar_s)
            return self.adiar_s
        self.proxima = self.agenda.relogio() + conf.intervalo
        return conf.intervalo.total_seconds()
