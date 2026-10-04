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

Quem entra por certificado digital, pela entrada manual ou sem a senha
guardada nunca entra sozinho: o portal só abre com a pessoa à frente, e
nenhum código chega a ser pedido. Essas fontes ficam de fora da
sincronização automática (nada de tarefa que falha e de aviso "não deu
certo" a cada ciclo); a pendência diz o que de fato acontece e o que fazer
(MENSAGEM_PRESENCA), uma vez por execução do programa.

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
MENSAGEM_PRESENCA = ("O monitoramento automático não entra sozinho em {fontes}: com o certificado "
                     "digital, com a entrada manual ou sem a senha guardada, o portal só abre com "
                     "você à frente. Na tela Pauta, clique em Sincronizar quando quiser atualizar. "
                     "Para a pauta ser conferida sozinha, guarde o usuário e a senha em Ajustes › "
                     "Acessos aos portais; ou desligue “Conferir sozinho”, na tela Pauta.")


class ContextoMonitor(ContextoFundo):
    """O Contexto de fundo que lembra POR QUE o login não aconteceu.

    'pediu_login' fica verdadeiro nos dois casos, e 'motivo' diz qual foi:
    "codigo" quando o portal pediu o código (perguntar, aqui) e "presenca"
    quando a pauta viu que o login exige a pessoa (ServicoPauta._acesso).
    """

    def __init__(self, tarefa, aviso_titulo: str, aviso_mensagem: str):
        super().__init__(tarefa, aviso_titulo, aviso_mensagem)
        self.motivo = getattr(self, "motivo", None) or None

    def perguntar(self, pergunta):
        self.motivo = "codigo"
        return super().perguntar(pergunta)


NOMES_SISTEMA = {"esaj": "e-SAJ", "eproc": "eProc"}


def rotulo_fonte(fonte: dict) -> str:
    rotulo = str(fonte.get("rotulo") or "").strip()
    if rotulo:
        return rotulo
    sistema = str(fonte.get("sistema") or "").strip().lower()
    partes = (str(fonte.get("tribunal") or "").strip().upper(), NOMES_SISTEMA.get(sistema, sistema))
    return " · ".join(x for x in partes if x) or "uma fonte da pauta"


def mensagem_presenca(fontes: list[dict]) -> str:
    rotulos = [rotulo_fonte(f) for f in fontes]
    if len(rotulos) > 1:
        lista = ", ".join(rotulos[:-1]) + " e " + rotulos[-1]
    else:
        lista = rotulos[0] if rotulos else "uma fonte da pauta"
    return MENSAGEM_PRESENCA.format(fontes=lista)


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
        # as fontes que exigem a pessoa e já viraram pendência nesta execução
        self._avisadas_presenca: set[str] = set()
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
        automaticas, presenciais = [], []
        for f in fontes:
            (presenciais if self.exige_presenca(servico, f) else automaticas).append(f)
        if not automaticas:
            # Nada entra sozinho: sem tarefa (que só falharia), só a pendência.
            self._avisar_presenca(presenciais)
            self.proxima = agora + intervalo
            return intervalo.total_seconds()
        if not self.sincronizar(servico, [str(f.get("id")) for f in automaticas if f.get("id")],
                                presenciais):
            self.proxima = agora + timedelta(seconds=ADIAR_S)
            return ADIAR_S
        self.proxima = datetime.now(agora.tzinfo) + intervalo
        return intervalo.total_seconds()

    @staticmethod
    def exige_presenca(servico, fonte: dict) -> bool:
        """O login desta fonte só entra com a pessoa à frente? (Certificado,
        entrada manual ou senha não guardada: a regra de ServicoPauta._acesso.)
        Na dúvida, False - a sincronização decide."""
        publica = getattr(servico, "exige_presenca", None)
        try:
            if callable(publica):
                return bool(publica(fonte))
            tribunal = servico._tribunal(str(fonte.get("tribunal") or ""),
                                         str(fonte.get("sistema") or ""))
            opcoes = servico._opcoes(tribunal)
            if opcoes.modo_login(tribunal.sistema) in ("manual", "certificado"):
                return True
            try:
                # sem ninguém à frente, só vale a senha GUARDADA (não a da sessão)
                credenciais = servico._credenciais(tribunal, opcoes, sessao=False)
            except TypeError:
                credenciais = servico._credenciais(tribunal, opcoes)
            return credenciais is None
        except Exception as erro:
            log.debug("não sei se a fonte %s entra sozinha: %s", fonte.get("id"), erro)
            return False

    def _avisar_presenca(self, presenciais: list[dict]) -> None:
        """A pendência das fontes que exigem a pessoa - uma vez por execução
        (a sincronização feita à mão a limpa, e ela não volta a cada ciclo)."""
        chaves = {str(f.get("id") or rotulo_fonte(f)) for f in presenciais}
        if not chaves or chaves <= self._avisadas_presenca:
            return
        self._avisadas_presenca |= chaves
        self.app.pendencia_pauta = {"chave": "pauta_login", "titulo": TITULO_AVISO,
                                    "mensagem": mensagem_presenca(presenciais), "acao": "pauta"}
        self.app.hub.publicar("estado", {})

    def sincronizar(self, servico, fontes: list[str], presenciais: list[dict] | None = None) -> bool:
        """Roda a sincronização como tarefa (aparece na barra lateral) e
        espera ela acabar. False: o navegador estava ocupado."""
        app = self.app
        hoje = date.today()
        de = hoje - timedelta(days=max(0, _inteiro(app.cfg, "dias_atras", 7)))
        ate = hoje + timedelta(days=max(1, _inteiro(app.cfg, "dias_a_frente", 60)))
        pediu = {"login": False, "motivo": None}

        def alvo(tw):
            ctx = ContextoMonitor(tw, TITULO_AVISO, MENSAGEM_LOGIN)
            try:
                return servico.sincronizar(ctx, fontes or None, de, ate)
            finally:
                pediu["login"] = ctx.pediu_login
                pediu["motivo"] = getattr(ctx, "motivo", None)

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
        presenciais = list(presenciais or [])
        if pediu["login"] and pediu["motivo"] == "codigo":
            app.pendencia_pauta = {"chave": "pauta_login", "titulo": TITULO_AVISO,
                                   "mensagem": MENSAGEM_LOGIN, "acao": "pauta"}
        else:
            if pediu["login"]:
                # O login exigia a pessoa e a regra não pôde ser vista antes:
                # as fontes que falharam (ou todas, se a tarefa inteira falhou).
                resultado = getattr(tw, "resultado", None)
                erros = resultado.get("erros", []) if isinstance(resultado, dict) else []
                ids = {str(e.get("fonte")) for e in erros if isinstance(e, dict)} or set(fontes)
                presenciais += [f for f in (servico.fontes() or []) if str(f.get("id")) in ids]
            atual = app.pendencia_pauta or {}
            if tw.estado == "concluida" and atual.get("mensagem") == MENSAGEM_LOGIN:
                app.pendencia_pauta = None          # o código já não falta
            if presenciais:
                self._avisar_presenca(presenciais)
            elif tw.estado == "concluida":
                app.pendencia_pauta = None
        app.hub.publicar("estado", {})
        return True
