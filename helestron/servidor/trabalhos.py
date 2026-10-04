"""As tarefas vistas pela API: id, estado, progresso e eventos.

Cada trabalho longo (download, teste de login, preparo do acervo,
sincronização da pauta...) roda numa helestron.tarefas.Tarefa - a mesma
regra de recursos da versão anterior: só se recusa o que disputa a MESMA
coisa. Aqui ela ganha um id, o formato 'Tarefa' da seção 6.3 da
especificação e um Contexto (ContextoWeb) que transforma o que o motor diz
em eventos para a página:

    status / progresso      evento 'tarefa' (no máximo ~4 por segundo)
    item (download)         evento 'item'
    avisar                  evento 'aviso'
    pedir_codigo            evento 'pergunta' (e a thread espera a resposta)

A tarefa terminada continua na lista (as últimas LIMITE_HISTORICO), para a
página que reconecta saber como o lote acabou.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import traceback
from datetime import datetime
from typing import Callable

from .. import tarefas
from ..tarefas import ContextoTela, Pergunta, Recursos

log = logging.getLogger("servidor.trabalhos")

RODANDO, CONCLUIDA, FALHOU, PARADA = "rodando", "concluida", "falhou", "parada"
TIPOS = ("download", "teste_login", "transcricao_arquivo", "modelo", "preparo", "pacote",
         "nuvem", "pauta_sincronizar", "pauta_capturar", "verificacao")
INTERVALO_EVENTO_S = 0.25
LIMITE_HISTORICO = 50


class Recusa(RuntimeError):
    """A tarefa não pode começar agora (já em andamento, recurso ocupado)."""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mensagem_de_erro(erro: BaseException) -> str:
    """A frase do erro para o usuário: o texto da exceção, com maiúscula.

    As exceções do motor já são escritas para o usuário ("não consegui
    entrar no e-SAJ: a senha foi recusada"); as que não são (KeyError,
    erro de programação) ganham o nome do tipo, para o suporte entender.
    """
    texto = str(erro).strip()
    if not texto or isinstance(erro, (KeyError, AttributeError, TypeError, IndexError)):
        texto = f"{type(erro).__name__}: {texto}" if texto else type(erro).__name__
    return texto[:1].upper() + texto[1:]


class TarefaWeb:
    """Uma tarefa da API (o 'Tarefa' da seção 6.3)."""

    def __init__(self, gerente: "GerenteTarefas", tipo: str, titulo: str,
                 recursos: tuple[str, ...] = (), chave: str | None = None):
        self.gerente = gerente
        self.id = secrets.token_hex(6)
        self.tipo = tipo
        self.titulo = titulo
        self.chave = chave or tipo
        self.estado = RODANDO
        self.inicio = _agora()
        self.fim: str | None = None
        self.feitos = 0
        self.total = 0
        self.atual = ""
        self.fracao: float | None = None       # progresso por fração (0..1), se houver
        self.status = ""
        self.resultado = None
        self.erro: str | None = None
        self.erro_detalhe = ""
        self.avisos: list[dict] = []
        self.itens: dict[str, dict] = {}        # download: número -> último 'item'
        self.dados: dict = {}                    # o que o tratador quiser guardar
        self.interna = tarefas.Tarefa(titulo, recursos, gerente=gerente.recursos,
                                      ao_terminar=lambda _t: gerente._terminou(self))
        self.ao_item: Callable[[object], None] | None = None
        self.ao_progresso: Callable[[int, int, str], None] | None = None
        self._sujo = False
        self._ultimo_envio = 0.0

    # ------------------------------------------------------------ estado
    @property
    def parar(self) -> threading.Event:
        return self.interna.parar

    @property
    def ativa(self) -> bool:
        return self.estado == RODANDO

    def cancelado(self) -> bool:
        return self.parar.is_set()

    @property
    def percentual(self) -> float | None:
        if self.fracao is not None:
            return round(max(0.0, min(1.0, self.fracao)) * 100, 1)
        if self.total:
            return round(100.0 * min(self.feitos, self.total) / self.total, 1)
        return None

    def como_dict(self, com_itens: bool = False) -> dict:
        dados = {
            "id": self.id, "tipo": self.tipo, "titulo": self.titulo, "estado": self.estado,
            "inicio": self.inicio, "fim": self.fim,
            "progresso": {"feitos": self.feitos, "total": self.total, "atual": self.atual,
                          "percentual": self.percentual},
            "status": self.status, "resultado": self.resultado, "erro": self.erro,
        }
        if com_itens:
            dados["itens"] = list(self.itens.values())
            dados["avisos"] = list(self.avisos)
        return dados

    # ------------------------------------------------------- atualização
    def definir_status(self, texto: str) -> None:
        self.status = str(texto or "")
        self.mudou()

    def definir_progresso(self, feitos: int, total: int, atual: str = "") -> None:
        self.feitos, self.total, self.atual = int(feitos or 0), int(total or 0), str(atual or "")
        self.mudou()

    def definir_fracao(self, fracao: float, texto: str = "") -> None:
        """Progresso contínuo (modelo baixando, gravação transcrevendo)."""
        try:
            self.fracao = max(0.0, min(1.0, float(fracao)))
        except (TypeError, ValueError):
            self.fracao = None
        if texto:
            self.status = str(texto)
        self.mudou()

    def mudou(self, ja: bool = False) -> None:
        """Marca para o próximo evento 'tarefa'. 'ja': publica agora."""
        if ja:
            self._sujo = False
            self._ultimo_envio = time.monotonic()
            self.gerente.publicar("tarefa", self.como_dict())
        else:
            self._sujo = True

    def avisar(self, titulo: str, mensagem: str, nivel: str = "aviso") -> None:
        aviso = {"titulo": str(titulo), "mensagem": str(mensagem), "nivel": nivel,
                 "tarefa": self.id}
        self.avisos.append(aviso)
        del self.avisos[:-20]
        self.gerente.publicar("aviso", aviso)

    def pedir_parada(self) -> None:
        if self.estado != RODANDO:
            return
        self.interna.pedir_parada()
        if not self.status.startswith("Parando"):
            self.status = "Parando com segurança…"
        self.gerente.perguntas_da_tarefa_canceladas(self.id)
        self.mudou(ja=True)

    def esperar(self, segundos: float) -> bool:
        return self.interna.esperar(segundos)

    def contexto(self) -> "ContextoWeb":
        return ContextoWeb(self)


class ContextoWeb(ContextoTela):
    """O Contexto do motor para uma tarefa da API.

    Herda de ContextoTela a espera da pergunta (fatias curtas, Parar e
    prazo); o 'postar' é que muda: em vez da fila do Tk, a tarefa e o hub.
    """

    def __init__(self, tarefa: TarefaWeb, intervalo: float = 0.2):
        self.tarefa = tarefa
        super().__init__(self._receber, tarefa.parar, intervalo)

    def _receber(self, tipo: str, dado) -> None:
        t = self.tarefa
        if tipo == "status":
            t.definir_status(dado)
        elif tipo == "progresso":
            feitos, total, atual = dado
            t.definir_progresso(feitos, total, atual)
            if t.ao_progresso is not None:
                t.ao_progresso(feitos, total, atual)
        elif tipo == "item":
            if t.ao_item is not None:
                t.ao_item(dado)
        elif tipo == "avisar":
            titulo, mensagem = dado
            t.avisar(titulo, mensagem)
        elif tipo in ("pedir_codigo", "perguntar"):
            t.gerente.perguntas.abrir(dado, t.id)

    def perguntar_tipo(self, tipo: str, titulo: str, mensagem: str,
                       opcoes: list[str] | dict | None = None, prazo_s: int = 600):
        """Pergunta genérica (confirmar, texto, escolha), bloqueando."""
        return self.perguntar(Pergunta(titulo, mensagem, max(1, int(prazo_s)), tipo=tipo,
                                       opcoes=(dict(opcoes) if isinstance(opcoes, dict) else
                                               list(opcoes) if opcoes is not None else None)))


class ContextoFundo(ContextoWeb):
    """O Contexto de um trabalho sem ninguém olhando (monitor da pauta).

    Não bloqueia em pergunta: se o portal pedir código, devolve None (o
    portal desiste do login) e deixa o aviso - "Entre no portal para
    continuar o monitoramento". Quem chama confere 'pediu_login' depois.
    """

    def __init__(self, tarefa: TarefaWeb, aviso_titulo: str, aviso_mensagem: str):
        super().__init__(tarefa)
        self.aviso_titulo = aviso_titulo
        self.aviso_mensagem = aviso_mensagem
        self.pediu_login = False

    def perguntar(self, pergunta: Pergunta):
        self.pediu_login = True
        log.info("pergunta recusada em trabalho de fundo: %s", pergunta.titulo)
        self.tarefa.avisar(self.aviso_titulo, self.aviso_mensagem)
        return None


class GerenteTarefas:
    """Cria, roda e lembra as tarefas da API."""

    def __init__(self, publicar, perguntas, recursos: Recursos | None = None):
        self.publicar = publicar
        self.perguntas = perguntas
        self.recursos = recursos or Recursos()
        self._trava = threading.Lock()
        self._tarefas: dict[str, TarefaWeb] = {}
        self._threads: dict[int, str] = {}          # ident da thread -> id da tarefa
        self._fim = threading.Event()
        self._despachante = threading.Thread(target=self._despachar, name="tarefas-eventos",
                                             daemon=True)
        self._despachante.start()
        self.ao_terminar: list[Callable[[TarefaWeb], None]] = []

    # ------------------------------------------------------------ iniciar
    def iniciar(self, tipo: str, titulo: str, alvo: Callable[[TarefaWeb], object],
                recursos: tuple[str, ...] = (), chave: str | None = None,
                preparar: Callable[[TarefaWeb], None] | None = None) -> TarefaWeb:
        """Começa a tarefa; levanta Recusa com a frase para o usuário.

        'alvo(tarefa)' roda na thread de trabalho e devolve o 'resultado'
        (algo que vire JSON). 'preparar(tarefa)' roda antes de a thread
        começar - para ligar ao_item e afins sem corrida.
        """
        tw = TarefaWeb(self, tipo, titulo, tuple(recursos), chave)
        with self._trava:
            for outra in self._tarefas.values():
                if outra.ativa and outra.chave == tw.chave:
                    raise Recusa(f"Este trabalho já está em andamento: {outra.titulo}.")
            self._tarefas[tw.id] = tw
        if preparar is not None:
            preparar(tw)
        # A thread começa presa até o evento 'tarefa' (rodando) sair: a
        # página fica sabendo da tarefa antes do primeiro 'item' dela.
        liberar = threading.Event()
        recusa = tw.interna.iniciar(self._rodar, tw, alvo, liberar)
        if recusa:
            with self._trava:
                self._tarefas.pop(tw.id, None)
            raise Recusa(recusa)
        self._podar()
        tw.mudou(ja=True)
        liberar.set()
        return tw

    def _rodar(self, tw: TarefaWeb, alvo, liberar: threading.Event) -> None:
        with self._trava:
            self._threads[threading.get_ident()] = tw.id
        try:
            liberar.wait(10)
            tw.resultado = alvo(tw)
            tw.estado = PARADA if tw.parar.is_set() else CONCLUIDA
        except BaseException as erro:          # noqa: BLE001 - vira estado da tarefa
            # Pedida a parada, o erro que vier é o da interrupção (navegador
            # fechado no meio de uma página, cópia cortada): não é falha.
            if type(erro).__name__ == "Cancelado" or tw.parar.is_set():
                tw.estado = PARADA
            else:
                tw.estado = FALHOU
                tw.erro = mensagem_de_erro(erro)
                tw.erro_detalhe = "".join(traceback.format_exception_only(type(erro), erro))[-800:]
                log.error("tarefa %s (%s) falhou: %s", tw.titulo, tw.id, tw.erro,
                          exc_info=not _erro_esperado(erro))
        finally:
            tw.fim = _agora()
            if tw.estado == PARADA and not tw.status.startswith("Interromp"):
                tw.status = "Interrompida a pedido."
            with self._trava:
                self._threads.pop(threading.get_ident(), None)

    def _terminou(self, tw: TarefaWeb) -> None:
        """Chamado depois de soltos os recursos: a página que reage ao fim
        (e começa outro trabalho na hora) não esbarra num recurso ainda preso."""
        if tw.estado == RODANDO:           # alvo nem começou (erro antes do _rodar)
            tw.estado = FALHOU
            tw.fim = _agora()
            erro = tw.interna.erro
            tw.erro = mensagem_de_erro(erro) if erro else "A tarefa terminou sem resultado."
        self.perguntas.cancelar_da_tarefa(tw.id)
        tw.mudou(ja=True)
        for f in list(self.ao_terminar):
            try:
                f(tw)
            except Exception:              # pragma: no cover
                log.exception("falha no aviso de fim da tarefa %s", tw.id)
        self.publicar("estado", {})

    def perguntas_da_tarefa_canceladas(self, id_tarefa: str) -> None:
        self.perguntas.cancelar_da_tarefa(id_tarefa)

    # ------------------------------------------------------------ consulta
    def obter(self, id_tarefa: str) -> TarefaWeb | None:
        with self._trava:
            return self._tarefas.get(id_tarefa)

    def listar(self, so_ativas: bool = False) -> list[TarefaWeb]:
        with self._trava:
            todas = list(self._tarefas.values())
        if so_ativas:
            todas = [t for t in todas if t.ativa]
        return todas

    def ativa(self, chave: str) -> TarefaWeb | None:
        for t in self.listar(so_ativas=True):
            if t.chave == chave:
                return t
        return None

    def tarefa_da_thread(self, ident: int | None = None) -> str | None:
        with self._trava:
            return self._threads.get(threading.get_ident() if ident is None else ident)

    def _podar(self) -> None:
        with self._trava:
            terminadas = [t for t in self._tarefas.values() if not t.ativa]
            excesso = len(self._tarefas) - LIMITE_HISTORICO
            for t in terminadas[:max(0, excesso)]:
                self._tarefas.pop(t.id, None)

    # ------------------------------------------------------------- eventos
    def _despachar(self) -> None:
        """Publica as tarefas que mudaram, no máximo a cada INTERVALO_EVENTO_S.

        O preparo do acervo chama progresso() a cada arquivo, o download a
        cada folha: sem o limite, a página receberia centenas de eventos por
        segundo e o último estado poderia se perder no meio deles.
        """
        while not self._fim.wait(INTERVALO_EVENTO_S):
            for t in self.listar():
                if t._sujo and time.monotonic() - t._ultimo_envio >= INTERVALO_EVENTO_S:
                    t.mudou(ja=True)

    # ------------------------------------------------------------- encerrar
    def parar_todas(self) -> None:
        for t in self.listar(so_ativas=True):
            t.pedir_parada()

    def esperar_todas(self, segundos: float, filtro: Callable[[TarefaWeb], bool] | None = None
                      ) -> bool:
        limite = time.monotonic() + max(0.0, segundos)
        for t in self.listar(so_ativas=True):
            if filtro is not None and not filtro(t):
                continue
            if not t.esperar(max(0.0, limite - time.monotonic())):
                return False
        return True

    def fechar(self) -> None:
        self._fim.set()


def _erro_esperado(erro: BaseException) -> bool:
    """Erros do motor com frase pronta não precisam do rastro no registro."""
    nome = type(erro).__name__
    return nome in ("LoginFalhou", "PortalIndisponivel", "ListaInvalida", "ComponenteAusente",
                    "ModeloAusente", "ErroDoModelo", "LookupError", "FileNotFoundError")
