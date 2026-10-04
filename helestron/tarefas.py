"""Trabalho em segundo plano: quem pode rodar junto com quem, e as perguntas
que o motor faz ao usuário.

Nada aqui conhece a interface. As threads de trabalho falam com quem as
acompanha (o servidor local, que repassa tudo à página pelos eventos da
seção 6.4 da especificação) por uma função 'postar(tipo, dado)' - o mesmo
padrão da versão Tkinter, que funcionou; só a fila do Tk deu lugar ao hub
de eventos do servidor.

RECURSOS. No Assessor SAJ, um trabalho em qualquer aba impedia todos os
outros ("Um de cada vez"), e dois diálogos ainda testavam essa regra velha
mesmo depois da troca (bug B6). Aqui só se recusa o que disputa a MESMA
coisa:

    navegador        o navegador dos portais, a sessão e o código de verificação
                     (download, teste de login, sincronização e captura da pauta)
    microfone        a captura de áudio (audiência ao vivo, teste do microfone)
    modelo_revisao   o modelo preciso de transcrição, que toma todos os núcleos
    nuvem            a pasta do espelho na nuvem (duas cópias ao mesmo tempo
                     escreveriam no mesmo arquivo .parcial)

Baixar processos e transcrever uma audiência ao vivo, por exemplo, andam
juntos.

AS PERGUNTAS. Na base o código de verificação chegava por um arquivo e a
caixa da tela acendia ao ler o TEXTO do log - mensagens de erro que
mencionavam "código de validação" acendiam a caixa (bug B2), e sob
python.exe o código era esperado no console (bug B3). Aqui o motor chama
ContextoTela.pedir_codigo(), que posta uma Pergunta e BLOQUEIA a thread de
trabalho num threading.Event até a resposta chegar, o usuário cancelar, o
prazo acabar ou o trabalho ser interrompido.
"""

from __future__ import annotations

import copy
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .download.contexto import Contexto

log = logging.getLogger("tarefas")

NAVEGADOR = "navegador"
MICROFONE = "microfone"
MODELO_REVISAO = "modelo_revisao"
NUVEM = "nuvem"

NOMES = {
    NAVEGADOR: "o navegador dos portais",
    MICROFONE: "o microfone",
    MODELO_REVISAO: "o modelo preciso de transcrição",
    NUVEM: "a pasta da nuvem",
}


class Recursos:
    """Guarda quem está com cada recurso. Uma instância por programa aberto."""

    def __init__(self):
        self._trava = threading.Lock()
        self._donos: dict[str, str] = {}

    def tomar(self, quem: str, nomes: tuple[str, ...] | list[str]) -> str | None:
        """Toma todos os recursos pedidos, ou nenhum.

        Devolve None quando conseguiu, ou o nome de quem já detém o primeiro
        recurso ocupado - para a mensagem dizer com quem está, em vez do
        antigo "Um de cada vez". Tudo-ou-nada sob uma trava só: não há ordem
        de aquisição a respeitar, e dois pedidos simultâneos nunca ficam
        cada um com metade, esperando a outra.
        """
        with self._trava:
            for nome in nomes:
                dono = self._donos.get(nome)
                if dono is not None and dono != quem:
                    return dono
            for nome in nomes:
                self._donos[nome] = quem
            return None

    def soltar(self, quem: str) -> None:
        with self._trava:
            for nome in [n for n, d in self._donos.items() if d == quem]:
                self._donos.pop(nome, None)

    def quem_tem(self, nome: str) -> str | None:
        with self._trava:
            return self._donos.get(nome)

    def ocupados(self) -> dict[str, str]:
        with self._trava:
            return dict(self._donos)


def _ja_em_andamento(nome: str) -> str:
    return f"Este trabalho já está em andamento: {nome}."


def frase_ocupado(dono: str, recursos: list[str]) -> str:
    """Frase da recusa. O nome da tarefa entra como rótulo, depois de dois-
    pontos, e não como sujeito: os nomes misturam substantivo e infinitivo
    ("Transcrição de gravação", "Baixar o modelo small"), e "Baixar o
    modelo small está usando…" não é português."""
    if not recursos:
        sujeito, verbo = "Um recurso necessário", "está"
    elif len(recursos) == 1:
        sujeito, verbo = recursos[0], "está"
    else:
        sujeito, verbo = ", ".join(recursos[:-1]) + " e " + recursos[-1], "estão"
    return (f"{sujeito[:1].upper()}{sujeito[1:]} {verbo} em uso por outro trabalho: {dono}. "
            "Espere esse trabalho terminar ou interrompa-o.")


# Nome antigo, mantido para quem ainda o importa.
_ocupado = frase_ocupado


class Tarefa:
    """Um trabalho em segundo plano com nome, recursos e pedido de parada.

    A thread é daemon (o programa pode fechar), mas quem encerra o
    programa pede a parada e espera um pouco por ela (esperar()) - sem essa
    espera, um arquivo em gravação ficava truncado (lição da base).
    """

    def __init__(self, nome: str, recursos: tuple[str, ...] = (), gerente: Recursos | None = None,
                 ao_terminar: Callable[["Tarefa"], None] | None = None):
        self.nome = nome
        self.recursos = tuple(recursos)
        self.gerente = gerente or Recursos()
        self.ao_terminar = ao_terminar
        self.parar = threading.Event()
        self.thread: threading.Thread | None = None
        self.erro: BaseException | None = None
        self.inicio = 0.0
        # False: consulta sem efeito em disco; o encerramento não espera por ela
        self.essencial = True

    @property
    def ativa(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def motivo_recusa(self) -> str | None:
        """Por que não dá para começar agora (ou None, se dá)."""
        if self.ativa:
            return _ja_em_andamento(self.nome)
        ocupados = self.gerente.ocupados()
        for nome in self.recursos:
            dono = ocupados.get(nome)
            if dono is not None and dono != self.nome:
                return frase_ocupado(dono, [NOMES.get(nome, nome)])
        return None

    def iniciar(self, alvo: Callable, *args, **kwargs) -> str | None:
        """Começa o trabalho. Devolve None, ou a frase que explica a recusa."""
        if self.ativa:
            return _ja_em_andamento(self.nome)
        dono = self.gerente.tomar(self.nome, self.recursos)
        if dono is not None:
            quais = [NOMES.get(n, n) for n in self.recursos if self.gerente.quem_tem(n) == dono]
            return frase_ocupado(dono, quais)
        self.parar.clear()
        self.erro = None
        self.inicio = time.monotonic()
        self.thread = threading.Thread(target=self._rodar, args=(alvo, args, kwargs),
                                       name=f"tarefa-{self.nome}", daemon=True)
        self.thread.start()
        return None

    def _rodar(self, alvo, args, kwargs) -> None:
        try:
            alvo(*args, **kwargs)
        except BaseException as erro:          # noqa: BLE001 - registra e segue
            self.erro = erro
            log.exception("erro em %s", self.nome)
        finally:
            self.gerente.soltar(self.nome)
            if self.ao_terminar is not None:
                try:
                    self.ao_terminar(self)
                except Exception:              # pragma: no cover
                    log.exception("erro ao avisar o fim de %s", self.nome)

    def pedir_parada(self) -> None:
        self.parar.set()

    def esperar(self, segundos: float) -> bool:
        """Espera a thread acabar. Devolve True se acabou."""
        if self.thread is None:
            return True
        self.thread.join(timeout=max(0.0, segundos))
        return not self.thread.is_alive()

    @property
    def segundos(self) -> float:
        return time.monotonic() - self.inicio if self.inicio else 0.0


# ------------------------------------------------------------- perguntas
TIPOS_PERGUNTA = ("codigo", "confirmar", "texto", "escolha")

# Por que uma pergunta foi fechada (evento 'pergunta_fechada').
RESPONDIDA = "respondida"
CANCELADA = "cancelada"
PRAZO = "prazo"
PARADA = "tarefa_parada"


@dataclass
class Pergunta:
    """Um pedido de dado ao usuário, à espera da resposta da interface.

    'resposta': o valor respondido (o código digitado; "" = o usuário pediu
    um código novo; True/False numa confirmação); None = cancelou, fechou, o
    prazo acabou ou o trabalho foi interrompido. 'ao_fechar(pergunta)' é
    chamado uma vez, quando a pergunta se fecha por qualquer motivo - é por
    ele que o servidor avisa a página ('pergunta_fechada').
    """
    titulo: str
    mensagem: str
    prazo_s: int = 600
    # Dá para pedir outro código ao portal? True: e-mail do e-SAJ; False:
    # aplicativo autenticador do eProc (muda sozinho a cada 30 s); None: o
    # portal não disse, e a interface deduz pelo texto do pedido.
    reenviavel: bool | None = None
    tipo: str = "codigo"
    # escolha: a lista das opções; confirmar: {"sim": rótulo, "nao": rótulo}
    # dos botões (opcional)
    opcoes: list[str] | dict | None = None
    id: str = field(default_factory=lambda: secrets.token_hex(6))
    criado: float = field(default_factory=time.monotonic)
    resposta: object = None
    respondido: threading.Event = field(default_factory=threading.Event)
    encerrado_pelo_trabalho: bool = False
    motivo: str = ""
    ao_fechar: Callable[["Pergunta"], None] | None = field(default=None, repr=False)

    def responder(self, valor, motivo: str = RESPONDIDA) -> bool:
        """Entrega a resposta (uma vez só). Devolve False se já estava fechada."""
        if self.respondido.is_set():
            return False
        self.resposta = valor
        self.motivo = motivo if valor is not None or motivo != RESPONDIDA else CANCELADA
        self.respondido.set()
        if self.ao_fechar is not None:
            try:
                self.ao_fechar(self)
            except Exception:                  # pragma: no cover - aviso nunca derruba
                log.exception("falha ao avisar o fechamento da pergunta %s", self.id)
        return True

    def cancelar(self) -> bool:
        """O usuário desistiu (fechou a folha, clicou em Cancelar)."""
        return self.responder(None, CANCELADA)

    def cancelar_pelo_trabalho(self, motivo: str = PARADA) -> None:
        """O trabalho desistiu de esperar (parada, prazo): a interface fecha a folha."""
        self.encerrado_pelo_trabalho = True
        self.responder(None, motivo)

    def esperar(self, parar: threading.Event | None = None, intervalo: float = 0.2,
                margem_s: float = 2.0):
        """Bloqueia até a resposta, o Parar ou o prazo. Devolve a resposta.

        Espera em fatias curtas para enxergar o Parar e o prazo; a margem
        cobre a folha da interface, que conta o mesmo prazo do lado dela.
        """
        limite = time.monotonic() + self.prazo_s + margem_s
        while not self.respondido.wait(intervalo):
            if parar is not None and parar.is_set():
                self.cancelar_pelo_trabalho(PARADA)
                return None
            if time.monotonic() > limite:
                self.cancelar_pelo_trabalho(PRAZO)
                return None
        return self.resposta

    @property
    def restante(self) -> float:
        return max(0.0, self.prazo_s - (time.monotonic() - self.criado))

    @property
    def aberto(self) -> bool:
        return not self.respondido.is_set()

    def como_dict(self) -> dict:
        """O evento 'pergunta' (seção 6.4): o prazo é o que ainda resta."""
        dados = {"id": self.id, "tipo": self.tipo, "titulo": self.titulo,
                 "mensagem": self.mensagem, "prazo_s": int(round(self.restante))}
        if self.opcoes is not None:
            dados["opcoes"] = dict(self.opcoes) if isinstance(self.opcoes, dict) \
                else list(self.opcoes)
        if self.tipo == "codigo":
            dados["reenviavel"] = self.reenviavel
        return dados


class PedidoCodigo(Pergunta):
    """O pedido de código de verificação (e-mail do e-SAJ, autenticador do
    eProc): uma Pergunta do tipo "codigo". Mantido com o nome antigo porque
    é assim que o motor e os testes o conhecem."""


class ContextoTela(Contexto):
    """O Contexto do motor quando quem acompanha é a interface.

    Cada chamada vira um evento ('status', 'progresso', 'item', 'avisar',
    'pedir_codigo') entregue a 'postar(tipo, dado)'; no programa, quem
    posta é o servidor local, que repassa à página. Nada aqui conhece a
    interface.
    """

    def __init__(self, postar: Callable[[str, object], None], parar: threading.Event | None = None,
                 intervalo: float = 0.2):
        self._postar = postar
        self._parar = parar or threading.Event()
        self._intervalo = intervalo

    def status(self, texto: str) -> None:
        self._postar("status", texto)

    def progresso(self, feitos: int, total: int, atual: str) -> None:
        self._postar("progresso", (feitos, total, atual))

    def item(self, r) -> None:
        # Cópia: o motor continua mexendo no objeto enquanto a interface o lê.
        self._postar("item", copy.copy(r))

    def cancelado(self) -> bool:
        return self._parar.is_set()

    def avisar(self, titulo: str, mensagem: str) -> None:
        log.info("%s: %s", titulo, mensagem)
        self._postar("avisar", (titulo, mensagem))

    def perguntar(self, pergunta: Pergunta):
        """Posta a pergunta e BLOQUEIA até a resposta (ou o Parar, ou o prazo)."""
        self._postar("pedir_codigo" if pergunta.tipo == "codigo" else "perguntar", pergunta)
        return pergunta.esperar(self._parar, self._intervalo)

    def pedir_codigo(self, titulo: str, mensagem: str, prazo_s: int = 600,
                     reenviavel: bool | None = None) -> str | None:
        pedido = PedidoCodigo(titulo, mensagem, max(1, int(prazo_s)), reenviavel)
        resposta = self.perguntar(pedido)
        return None if resposta is None else str(resposta)
