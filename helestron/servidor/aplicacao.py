"""O estado do programa aberto, visto pelo servidor.

Uma Aplicacao por execução: a configuração, o hub de eventos, as perguntas
abertas, as tarefas, a sessão de transcrição, a pauta e as credenciais
digitadas "só por agora" (que nunca vão para o disco). A janela, o monitor
da pauta e o autoteste são do pacote helestron.aplicativo e se penduram
aqui depois (atributos 'janela', 'monitor', 'autoteste'): o servidor
funciona sem eles (python -m helestron --servidor, testes).
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import NOME, __version__, servicos
from ..nucleo import caminhos, config
from ..tarefas import Recursos
from . import multipart, rotas
from .audiencia import GerenteAudiencia
from .eventos import HubEventos
from .perguntas import GerentePerguntas, PerguntaFechada, PerguntaInexistente
from .rede import ErroApi, ServidorLocal
from .trabalhos import GerenteTarefas, Recusa

log = logging.getLogger("servidor.aplicacao")

PACOTE = Path(__file__).resolve().parents[1]          # .../helestron

ESPERA_TAREFAS_S = 120
# A audiência ao vivo transcreve, ao encerrar, a fila que ainda estiver
# atrasada (computador lento: minutos) antes de gravar o DOCX final. Matar o
# processo no meio deixava só o documento parcial; espera-se mais por ela.
ESPERA_AUDIENCIA_S = 15 * 60
MODOS = ("janela", "edge", "navegador", "servidor")


class PonteDeLog(logging.Handler):
    """Cada linha do registro vira um evento 'log' (o painel de detalhes).

    A linha de uma thread de trabalho leva o id da tarefa: a página mostra
    os detalhes do download ao lado do download.
    """

    IGNORAR = ("servidor.http", "servidor.eventos")

    def __init__(self, app: "Aplicacao", nivel: int = logging.INFO):
        super().__init__(nivel)
        self.app = app
        self._local = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._local, "dentro", False) or record.name.startswith(self.IGNORAR):
            return
        self._local.dentro = True
        try:
            nivel = ("erro" if record.levelno >= logging.ERROR else
                     "aviso" if record.levelno >= logging.WARNING else "info")
            texto = record.getMessage()
            self.app.hub.publicar("log", {
                "tarefa": self.app.tarefas.tarefa_da_thread(record.thread),
                "nivel": nivel, "texto": texto[:600],
                "hora": datetime.fromtimestamp(record.created).strftime("%H:%M:%S")})
        except Exception:                       # pragma: no cover - log nunca derruba
            pass
        finally:
            self._local.dentro = False


class Aplicacao:
    """O programa aberto (servidor + estado)."""

    def __init__(self, cfg=None, *, modo: str = "janela", token: str | None = None,
                 porta: int = 0, pasta_web: Path | None = None):
        self.cfg = cfg if cfg is not None else config.carregar()
        self.modo = modo if modo in MODOS else "janela"
        self.token = token or secrets.token_urlsafe(32)
        self.hub = HubEventos()
        self.perguntas = GerentePerguntas(self.hub.publicar)
        self.recursos = Recursos()
        self.tarefas = GerenteTarefas(self.hub.publicar, self.perguntas, self.recursos)
        self.audiencia = GerenteAudiencia(self)
        # Senhas que o usuário não quis guardar ("Lembrar" desmarcado): valem
        # enquanto o programa estiver aberto e nunca vão para o disco.
        self.credenciais_sessao: dict[str, tuple[str, str]] = {}
        # Senhas de processos sigilosos que vieram na relação (coluna "senha").
        self.senhas_relacao: dict[str, str] = {}
        # PDFs sigilosos que não puderam sair do acervo (abertos em outro
        # programa): enquanto existirem, nada de espelho na nuvem.
        self.sigilosos_presos: list[Path] = []
        self.janela = None          # helestron.aplicativo.janela (mostrar, diálogos...)
        self.monitor = None         # helestron.aplicativo.monitor.MonitorPauta
        self.autoteste = None       # helestron.aplicativo.autoteste.Autoteste
        self.pendencia_pauta: dict | None = None    # monitor pediu login
        self.ao_encerrar: list[Callable[[], None]] = []
        self.fechando = False
        self.encerrado = threading.Event()
        self._trava_fim = threading.Lock()
        self._trava_pauta = threading.Lock()
        self._pauta = None
        self._ponte: PonteDeLog | None = None
        self.iniciado_em = time.monotonic()
        web = pasta_web if pasta_web is not None else self.pasta_web()
        self.servidor = ServidorLocal(self, rotas.montar(), self.token, porta, web,
                                      icone=self.arquivo_icone())

    # ------------------------------------------------------------ caminhos
    @staticmethod
    def pasta_web() -> Path:
        """helestron/web (caminhos.WEB, ou a pasta ao lado deste pacote)."""
        return Path(getattr(caminhos, "WEB", None) or PACOTE / "web")

    @staticmethod
    def arquivo_icone() -> Path | None:
        for pasta in (getattr(caminhos, "RECURSOS", None), PACOTE / "recursos"):
            if pasta is not None and (Path(pasta) / "helestron.ico").is_file():
                return Path(pasta) / "helestron.ico"
        return None

    @staticmethod
    def pasta_temp() -> Path:
        return Path(caminhos.TEMP)

    @staticmethod
    def pasta_envios() -> Path:
        return Path(caminhos.TEMP) / "envios"

    @staticmethod
    def arquivo_pauta() -> Path:
        arquivo = getattr(caminhos, "ARQUIVO_PAUTA", None)
        return Path(arquivo) if arquivo is not None else Path(caminhos.LOCAL) / "pauta.sqlite3"

    @property
    def url(self) -> str:
        return self.servidor.url_com_token()

    @property
    def porta(self) -> int:
        return self.servidor.porta

    # ------------------------------------------------------------- início
    def iniciar(self) -> "Aplicacao":
        self._ponte = PonteDeLog(self)
        logging.getLogger().addHandler(self._ponte)
        multipart.apagar_antigos(self.pasta_envios())
        self.servidor.iniciar()
        log.info("%s %s: servidor em 127.0.0.1:%d (modo %s)", NOME, __version__, self.porta,
                 self.modo)
        return self

    def tocar(self) -> None:
        self.hub.tocar()

    # ------------------------------------------------------------- pauta
    def pauta(self):
        """O ServicoPauta (seção 8.10), criado no primeiro uso.

        Importado aqui dentro: se o pacote da pauta faltar na instalação, só
        a pauta fica indisponível (503), e o resto do programa funciona.
        """
        with self._trava_pauta:
            if self._pauta is None:
                try:
                    from ..pauta.servico import ServicoPauta
                except ImportError as erro:
                    raise ErroApi(503, "pauta_indisponivel",
                                  "A pauta de audiências não está disponível nesta instalação. "
                                  + servicos.DICA_INSTALAR, str(erro)) from erro
                self._pauta = ServicoPauta(self.cfg, arquivo_banco=self.arquivo_pauta(),
                                           eventos=self._evento_pauta)
            return self._pauta

    def pauta_ou_none(self):
        try:
            return self.pauta()
        except ErroApi:
            return None
        except Exception as erro:
            log.warning("a pauta não pôde ser aberta: %s", erro)
            return None

    def _evento_pauta(self, tipo: str, dados=None) -> None:
        self.hub.publicar(tipo, dados if dados is not None else {})
        if tipo == "pauta":
            self.hub.publicar("estado", {})

    # ------------------------------------------------------------- erros
    def traduzir_erro(self, erro: Exception) -> ErroApi | None:
        """A exceção do motor com a frase certa e o código HTTP certo."""
        nome = type(erro).__name__
        texto = str(erro).strip()
        frase = texto[:1].upper() + texto[1:] if texto else ""
        if isinstance(erro, Recusa):
            return ErroApi(409, "ocupado", frase)
        if isinstance(erro, PerguntaInexistente):
            return ErroApi(404, "pergunta_inexistente", "Esta pergunta não existe mais.")
        if isinstance(erro, PerguntaFechada):
            return ErroApi(409, "pergunta_fechada",
                           "Esta pergunta já foi encerrada (o prazo acabou ou o trabalho foi "
                           "interrompido).")
        if isinstance(erro, servicos.ComponenteAusente):
            return ErroApi(500, "componente_ausente", frase)
        if nome == "ListaInvalida":
            return ErroApi(400, "relacao_invalida", frase)
        if isinstance(erro, PermissionError):
            return ErroApi(409, "arquivo_preso", frase or "O arquivo está em uso por outro "
                                                           "programa.", nome)
        if isinstance(erro, FileNotFoundError):
            return ErroApi(404, "arquivo_inexistente", frase or "Arquivo não encontrado.", nome)
        if isinstance(erro, LookupError) and not isinstance(erro, (KeyError, IndexError)):
            return ErroApi(409, "vazio", frase)
        if isinstance(erro, ValueError) and nome in ("ValueError", "NumeroInvalido"):
            return ErroApi(400, "valor_invalido", frase)
        return None

    # ----------------------------------------------------------- encerrar
    def trabalho_em_andamento(self) -> list[str]:
        """O que seria interrompido ao fechar (para a confirmação)."""
        itens = [t.titulo for t in self.tarefas.listar(so_ativas=True)]
        if self.audiencia.ativa:
            itens.insert(0, "Audiência sendo transcrita (o documento é salvo antes de fechar)")
        return itens

    def encerrar(self, espera_tarefas_s: float = ESPERA_TAREFAS_S,
                 espera_audiencia_s: float = ESPERA_AUDIENCIA_S) -> None:
        """Fecha com segurança: salva a audiência, para as tarefas, fecha a
        janela e o servidor. Pode ser chamado de qualquer thread, mais de
        uma vez (só a primeira faz efeito)."""
        with self._trava_fim:
            if self.fechando:
                return
            self.fechando = True
        log.info("encerrando o %s", NOME)
        if self.trabalho_em_andamento():
            self.hub.publicar("aviso", {"titulo": "Encerrando com segurança",
                                        "mensagem": "Salvando o que estava em andamento. Isto "
                                                    "leva poucos segundos.",
                                        "nivel": "info"})
        monitor = self.monitor
        if monitor is not None:
            try:
                monitor.parar()
            except Exception:                      # pragma: no cover
                log.exception("falha ao parar o monitor da pauta")
        self.tarefas.parar_todas()
        try:
            self.audiencia.encerrar_para_fechar(espera_audiencia_s)
        except Exception:
            log.exception("falha ao encerrar a audiência ao fechar")
        if not self.tarefas.esperar_todas(espera_tarefas_s):
            log.warning("havia trabalho em andamento ao fechar; o programa fechou sem esperar o "
                        "fim dele")
        self.perguntas.cancelar_todas()
        for funcao in list(self.ao_encerrar):
            try:
                funcao()
            except Exception:                      # pragma: no cover
                log.exception("falha ao encerrar")
        self.hub.fechar()
        self.servidor.parar()
        self.tarefas.fechar()
        if self._ponte is not None:
            logging.getLogger().removeHandler(self._ponte)
            self._ponte = None
        self.encerrado.set()

    def encerrar_em_segundo_plano(self, **kw) -> None:
        threading.Thread(target=self.encerrar, kwargs=kw, name="encerrar", daemon=True).start()

    def esperar(self, segundos: float | None = None) -> bool:
        return self.encerrado.wait(segundos)
