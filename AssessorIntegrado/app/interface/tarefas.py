"""Trabalho em segundo plano: quem pode rodar junto com quem, e a ponte com a tela.

Nada aqui importa o Tk: as threads de trabalho nunca tocam na janela. Elas
falam com ela por eventos postos numa fila (queue.Queue) que a janela
esvazia com after() - o padrão da base, que funcionou.

RECURSOS. No Assessor SAJ, um trabalho em qualquer aba impedia todos os
outros ("Um de cada vez"), e dois diálogos ainda testavam essa regra velha
mesmo depois da troca (bug B6). Aqui só se recusa o que disputa a MESMA
coisa:

    navegador        o navegador dos portais, a sessão e o código de verificação
    microfone        a captura de áudio (audiência ao vivo, teste do microfone)
    modelo_revisao   o modelo preciso de transcrição, que toma todos os núcleos
    nuvem            a pasta do espelho na nuvem (duas cópias ao mesmo tempo
                     escreveriam no mesmo arquivo .parcial)

Baixar processos e transcrever uma audiência ao vivo, por exemplo, andam
juntos.

O CÓDIGO DE VERIFICAÇÃO. Na base ele chegava por um arquivo e a caixa da
tela acendia ao ler o TEXTO do log - mensagens de erro que mencionavam
"código de validação" acendiam a caixa (bug B2), e sob python.exe o código
era esperado no console (bug B3). Aqui o motor chama
ContextoTela.pedir_codigo(), que posta um PedidoCodigo na fila e BLOQUEIA a
thread de trabalho num threading.Event até a tela responder, o usuário
cancelar, o prazo acabar ou o trabalho ser interrompido.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..download.contexto import Contexto

log = logging.getLogger("interface.tarefas")

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
    """Guarda quem está com cada recurso. Uma instância por janela."""

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


class Tarefa:
    """Um trabalho em segundo plano com nome, recursos e pedido de parada.

    A thread é daemon (o programa pode fechar), mas a janela, ao fechar,
    pede a parada e espera um pouco por ela (esperar()) - sem essa espera,
    um arquivo em gravação ficava truncado (lição da base).
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
        # False: consulta sem efeito em disco; o fechar não pergunta nem espera
        self.essencial = True

    @property
    def ativa(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def motivo_recusa(self) -> str | None:
        """Por que não dá para começar agora (ou None, se dá)."""
        if self.ativa:
            return f"{self.nome} já está em andamento."
        ocupados = self.gerente.ocupados()
        for nome in self.recursos:
            dono = ocupados.get(nome)
            if dono is not None and dono != self.nome:
                return (f"{dono} está usando {NOMES.get(nome, nome)}. Espere terminar "
                        "ou interrompa aquele trabalho.")
        return None

    def iniciar(self, alvo: Callable, *args, **kwargs) -> str | None:
        """Começa o trabalho. Devolve None, ou a frase que explica a recusa."""
        if self.ativa:
            return f"{self.nome} já está em andamento."
        dono = self.gerente.tomar(self.nome, self.recursos)
        if dono is not None:
            quais = [NOMES.get(n, n) for n in self.recursos if self.gerente.quem_tem(n) == dono]
            return (f"{dono} está usando {', '.join(quais) or 'um recurso'}. Espere terminar "
                    "ou interrompa aquele trabalho.")
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


# ----------------------------------------------------------- código pedido
@dataclass
class PedidoCodigo:
    """Um pedido de código de verificação, à espera da tela.

    'resposta': o código digitado; "" = o usuário pediu um código novo;
    None = cancelou, fechou, o prazo acabou ou o trabalho foi interrompido.
    """
    titulo: str
    mensagem: str
    prazo_s: int = 600
    criado: float = field(default_factory=time.monotonic)
    resposta: str | None = None
    respondido: threading.Event = field(default_factory=threading.Event)
    encerrado_pelo_trabalho: bool = False

    def responder(self, valor: str | None) -> None:
        if not self.respondido.is_set():
            self.resposta = valor
            self.respondido.set()

    def cancelar_pelo_trabalho(self) -> None:
        """O trabalho desistiu de esperar (parada, prazo): a tela fecha o diálogo."""
        self.encerrado_pelo_trabalho = True
        self.responder(None)

    @property
    def restante(self) -> float:
        return max(0.0, self.prazo_s - (time.monotonic() - self.criado))

    @property
    def aberto(self) -> bool:
        return not self.respondido.is_set()


class ContextoTela(Contexto):
    """O Contexto do motor de download quando quem acompanha é a janela.

    Cada chamada vira um evento ('status', 'progresso', 'item', 'avisar',
    'pedir_codigo') entregue a 'postar(tipo, dado)', que a janela põe na
    fila; nada aqui toca no Tk.
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
        # Cópia: o motor continua mexendo no objeto enquanto a tela o lê.
        self._postar("item", copy.copy(r))

    def cancelado(self) -> bool:
        return self._parar.is_set()

    def avisar(self, titulo: str, mensagem: str) -> None:
        log.info("%s: %s", titulo, mensagem)
        self._postar("avisar", (titulo, mensagem))

    def pedir_codigo(self, titulo: str, mensagem: str, prazo_s: int = 600) -> str | None:
        pedido = PedidoCodigo(titulo, mensagem, max(1, int(prazo_s)))
        self._postar("pedir_codigo", pedido)
        # Espera em fatias curtas para enxergar o Parar e o prazo; a margem
        # de 2 s cobre o diálogo, que conta o mesmo prazo do lado da tela.
        limite = time.monotonic() + pedido.prazo_s + 2
        while not pedido.respondido.wait(self._intervalo):
            if self._parar.is_set() or time.monotonic() > limite:
                pedido.cancelar_pelo_trabalho()
                return None
        return pedido.resposta
