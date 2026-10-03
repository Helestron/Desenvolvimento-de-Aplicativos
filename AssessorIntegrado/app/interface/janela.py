"""A janela do Assessor Integrado.

    ┌──────────────┬──────────────────────────────────────────────┐
    │ Assessor     │                                              │
    │ Integrado    │   Início: três cartões grandes               │
    │              │   (Baixar · Transcrever · Compartilhar)      │
    │ ▣ Início     │                                              │
    │ ▣ Baixar  ●  │   ou a página da função escolhida            │
    │ ▣ Transcr.   │                                              │
    │ ▣ Compart.   │                                              │
    │ ──────────   │                                              │
    │ ▣ Config.    │                                              │
    │ ▣ Ajuda      │                                              │
    └──────────────┴──────────────────────────────────────────────┘

Cada página roda o próprio trabalho numa thread (tarefas.Tarefa) e recebe
os eventos dele pela fila desta janela, consumida a cada 100 ms com
after() - as threads nunca tocam no Tk. O ponto na barra lateral mostra o
que está em andamento, mesmo com outra página aberta.

Correções em relação à base: janela 1180x760 centrada (a base abria
maximizada à força, ruim em notebook de 1366x768), escala pelo DPI real (a
base fixava 1.2), ícone próprio na barra de tarefas (AppUserModelID),
registro com limite de linhas, e o fechar que salva a audiência em
andamento ANTES de destruir a janela (a base esperava 2 s e o .docx podia
ficar truncado).
"""

from __future__ import annotations

import collections
import logging
import queue
import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .. import NOME, __version__
from ..nucleo import caminhos, config, registro, sistema
from . import componentes, dialogos, estilo
from .estilo import px
from .tarefas import Recursos

log = logging.getLogger("interface.janela")

LARGURA, ALTURA = 1180, 760
MINIMO = (980, 660)
LARGURA_TRILHO = 1060      # abaixo disto, a barra lateral mostra só ícones
TICK_MS = 100
FATIA_S = 0.04            # tempo máximo de um tique esvaziando a fila
ESPERA_FECHAR_S = 120     # o DOCX da audiência pode levar um pouco para fechar

# (nome, módulo, classe); None = separador na barra lateral
PAGINAS = (
    ("inicio", "pagina_inicio", "PaginaInicio"),
    ("baixar", "pagina_baixar", "PaginaBaixar"),
    ("transcrever", "pagina_transcrever", "PaginaTranscrever"),
    ("compartilhar", "pagina_compartilhar", "PaginaCompartilhar"),
    None,
    ("config", "pagina_config", "PaginaConfig"),
    ("ajuda", "pagina_ajuda", "PaginaAjuda"),
)
ROTULOS = {"inicio": ("Início", "inicio"), "baixar": ("Baixar processos", "baixar"),
           "transcrever": ("Transcrever audiência", "transcrever"),
           "compartilhar": ("Compartilhar com IA", "compartilhar"),
           "config": ("Configurações", "config"), "ajuda": ("Ajuda", "ajuda")}


class PaginaComErro(componentes.Pagina):
    """Lugar de uma página que não conseguiu abrir: o resto do programa
    funciona, e o usuário sabe o que fazer."""

    def __init__(self, pai, janela, nome, titulo, icone, erro):
        self.nome, self.titulo, self.icone, self._erro = nome, titulo, icone, erro
        super().__init__(pai, janela)

    def montar(self) -> None:
        corpo, _, _ = componentes.estrutura(self, self.titulo, rolavel=False)
        faixa = componentes.Faixa(corpo, "Erro", titulo="Esta parte do programa não abriu.",
                                  texto=f"{self._erro}\n\nRode o INSTALAR.bat de novo. Se "
                                        "continuar, envie a pasta Logs ao suporte.")
        faixa.grid(row=0, column=0, sticky="ew")
        corpo.columnconfigure(0, weight=1)


class Janela:
    def __init__(self, raiz: tk.Tk, cfg=None, teste: bool = False):
        self.raiz = raiz
        self.cfg = cfg or config.carregar()
        self.teste = teste
        self.fila: queue.Queue = queue.Queue()
        self.recursos = Recursos()
        # Senhas digitadas sem "Lembrar": valem só enquanto o programa está aberto.
        self.credenciais_sessao: dict[str, tuple[str, str]] = {}
        self.paginas: dict[str, componentes.Pagina] = {}
        self.atual: str | None = None
        self.registro_geral: collections.deque = collections.deque(maxlen=componentes.MAX_LINHAS_REGISTRO)
        self.codigo_saida = 0
        self._fechando = False
        self._ponte: logging.Handler | None = None
        self._cofre = None

        raiz.title(NOME)
        estilo.aplicar_icone(raiz)
        self._geometria()
        self._montar()
        componentes.instalar_roda(raiz)
        self._ligar_log()
        self._atalhos()
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        self.mostrar("inicio")
        raiz.after(TICK_MS, self._consumir)
        if not teste and not self.cfg.flag("interface", "assistente_concluido"):
            raiz.after(500, self.abrir_assistente)

    # ------------------------------------------------------------ montagem
    def _geometria(self) -> None:
        r = self.raiz
        largura_tela, altura_tela = r.winfo_screenwidth(), r.winfo_screenheight()
        # Em notebook a 150% a janela "de projeto" pode passar da tela: encolhe.
        largura = min(px(LARGURA), int(largura_tela * 0.94))
        altura = min(px(ALTURA), int(altura_tela * 0.88))
        x = max(0, (largura_tela - largura) // 2)
        y = max(0, (altura_tela - altura) // 2 - px(16))
        r.geometry(f"{largura}x{altura}+{x}+{y}")
        r.minsize(min(px(MINIMO[0]), largura), min(px(MINIMO[1]), altura))

    def _montar(self) -> None:
        import importlib

        r = self.raiz
        r.configure(background=estilo.MOLDURA)
        r.columnconfigure(1, weight=1)
        r.rowconfigure(0, weight=1)
        self.barra = componentes.BarraLateral(r, self.mostrar, __version__)
        self.barra.grid(row=0, column=0, sticky="ns")
        self.painel = ttk.Frame(r, style="Painel.TFrame", padding=px(7))
        self.painel.grid(row=0, column=1, sticky="nsew", padx=(0, px(12)), pady=px(12))
        self.painel.columnconfigure(0, weight=1)
        self.painel.rowconfigure(0, weight=1)
        r.bind("<Configure>", self._largura_mudou, add="+")

        for definicao in PAGINAS:
            if definicao is None:
                self.barra.separador()
                continue
            nome, modulo, classe = definicao
            titulo, icone = ROTULOS[nome]
            try:
                mod = importlib.import_module(f"{__package__}.{modulo}")
                pagina = getattr(mod, classe)(self.painel, self)
            except Exception as erro:          # uma página quebrada não derruba a janela
                log.exception("a página %s não abriu", nome)
                pagina = PaginaComErro(self.painel, self, nome, titulo, icone, erro)
            pagina.grid(row=0, column=0, sticky="nsew")
            self.paginas[nome] = pagina
            self.barra.adicionar(nome, titulo, icone)

    def _largura_mudou(self, evento) -> None:
        """Abaixo de ~1060 px (de projeto), a barra lateral vira trilho."""
        if evento.widget is not self.raiz:
            return
        self.barra.definir_compacta(evento.width < px(LARGURA_TRILHO))

    def _ligar_log(self) -> None:
        self._ponte = registro.PonteDeLog(self.fila)
        logging.getLogger().addHandler(self._ponte)
        if logging.getLogger().level > logging.INFO or logging.getLogger().level == 0:
            logging.getLogger().setLevel(logging.INFO)

    def _atalhos(self) -> None:
        nomes = [d[0] for d in PAGINAS if d is not None]
        for i, nome in enumerate(nomes, 1):
            self.raiz.bind_all(f"<Control-Key-{i}>", lambda _e, n=nome: self.mostrar(n))
        for k in range(1, 13):
            self.raiz.bind_all(f"<Key-F{k}>", self._tecla_funcao)

    def _tecla_funcao(self, evento):
        pagina = self.paginas.get(self.atual or "")
        if pagina is not None and pagina.atalho(evento):
            return "break"
        if evento.keysym == "F1":
            self.mostrar("ajuda")
            return "break"
        return None

    # ------------------------------------------------------------- navegação
    def mostrar(self, nome: str) -> None:
        pagina = self.paginas.get(nome)
        if pagina is None or nome == self.atual:
            return
        anterior = self.paginas.get(self.atual or "")
        if anterior is not None:
            try:
                anterior.ao_esconder()
            except Exception:
                log.exception("erro ao sair da página %s", self.atual)
        pagina.tkraise()
        self.atual = nome
        self.barra.selecionar(nome)
        try:
            pagina.ao_mostrar()
        except Exception:
            log.exception("erro ao abrir a página %s", nome)

    def abrir_assistente(self) -> None:
        def concluido():
            inicio = self.paginas.get("inicio")
            if inicio is not None:
                inicio.ao_mostrar()
        try:
            dialogos.Assistente(self, ao_concluir=concluido)
        except Exception:
            log.exception("o assistente de primeiro uso não abriu")

    # --------------------------------------------------------------- apoio
    def cofre(self):
        if self._cofre is None:
            from . import servicos

            self._cofre = servicos.cofre()
        return self._cofre

    def postar(self, pagina: str, tipo: str, dado=None) -> None:
        """Seguro em qualquer thread."""
        self.fila.put(("evento", (pagina, tipo, dado)))

    def erro_inesperado(self, erro: BaseException) -> None:
        from .servicos import ComponenteAusente

        if isinstance(erro, ComponenteAusente):
            dialogos.erro(self.raiz, "Componente ausente", str(erro))
            return
        dialogos.erro(self.raiz, "Algo deu errado",
                      f"{erro}\n\nOs detalhes ficaram no registro (pasta Logs).")

    def atualizar_indicadores(self) -> None:
        em_andamento = []
        for nome, pagina in self.paginas.items():
            try:
                indicador = pagina.indicador()
            except Exception:
                indicador = None
            self.barra.indicar(nome, indicador)
            if pagina.ocupada:
                em_andamento.append(pagina.titulo)
        if em_andamento:
            self.barra.estado("Em andamento: " + ", ".join(em_andamento) + ".")
        else:
            self.barra.estado("")

    # -------------------------------------------------------------- a fila
    def _consumir(self) -> None:
        """Traz para a tela o que as threads produziram (a cada 100 ms).

        Esvazia a fila por no máximo 40 ms por vez - numa enxurrada de
        eventos a janela continua respondendo - e junta as linhas de
        registro para inserir de uma vez só.
        """
        if not self._viva():
            return
        inicio = time.monotonic()
        linhas: list = []
        try:
            while time.monotonic() - inicio < FATIA_S:
                try:
                    tipo, dado = self.fila.get_nowait()
                except queue.Empty:
                    break
                if tipo == "log":
                    linhas.append(dado)
                    continue
                if tipo == "evento":
                    nome, t, d = dado
                    pagina = self.paginas.get(nome)
                    if pagina is None:
                        continue
                    try:
                        pagina.tratar_evento(t, d)
                    except Exception:
                        log.exception("erro ao tratar o evento %s da página %s", t, nome)
            if linhas:
                self._distribuir(linhas)
            self.atualizar_indicadores()
        except Exception:
            log.exception("erro no laço da janela")
        finally:
            if self._viva():
                self.raiz.after(TICK_MS, self._consumir)

    def _distribuir(self, linhas: list) -> None:
        por_marca: dict[str, list] = {}
        for marca, texto, nivel in linhas:
            self.registro_geral.append((texto, nivel))
            por_marca.setdefault(marca, []).append((texto, nivel))
        for pagina in self.paginas.values():
            if pagina.marca_log and pagina.marca_log in por_marca:
                try:
                    pagina.receber_log(por_marca[pagina.marca_log])
                except Exception:
                    pass

    def _viva(self) -> bool:
        try:
            return bool(self.raiz.winfo_exists())
        except tk.TclError:
            return False

    # -------------------------------------------------------------- fechar
    def fechar(self) -> None:
        if self._fechando:
            return
        pendentes = []
        for pagina in self.paginas.values():
            try:
                pendentes += pagina.trabalho_em_andamento()
            except Exception:
                pass
        if pendentes:
            texto = ("Há trabalho em andamento:\n\n" + "\n".join(f"•  {p}" for p in pendentes)
                     + "\n\nFechar mesmo assim? O que estiver em andamento é interrompido "
                       "com segurança — a transcrição da audiência é salva antes.")
            if not dialogos.confirmar(self.raiz, "Fechar o Assessor Integrado", texto):
                return
        self._fechando = True
        for pagina in self.paginas.values():
            try:
                pagina.antes_de_fechar()
            except Exception:
                log.exception("erro ao encerrar a página %s", pagina.nome)
        self._aguarde = None
        if any(p.ocupada for p in self.paginas.values()):
            self._aguarde = dialogos.DialogoAguarde(
                self.raiz, "Encerrando com segurança",
                "Salvando o que estava em andamento. Isto leva poucos segundos.")
        self._esperar_e_destruir(time.monotonic() + ESPERA_FECHAR_S)

    def _esperar_e_destruir(self, limite: float) -> None:
        if any(p.ocupada for p in self.paginas.values()) and time.monotonic() < limite:
            self.raiz.after(150, lambda: self._esperar_e_destruir(limite))
            return
        self.destruir()

    def destruir(self) -> None:
        if self._ponte is not None:
            logging.getLogger().removeHandler(self._ponte)
            self._ponte = None
        # Os after() pendentes (o laço da fila, cronômetros, animações)
        # disparariam depois da destruição, contra comandos que não existem
        # mais ("invalid command name"): cancela todos antes.
        try:
            for pendente in self.raiz.tk.splitlist(self.raiz.tk.call("after", "info")):
                try:
                    self.raiz.tk.call("after", "cancel", pendente)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
        try:
            self.raiz.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------- teste de interface
    def percorrer(self, pasta: Path | None, ao_fim=None) -> None:
        """Visita todas as páginas (e os diálogos principais), salva uma
        captura de cada uma em <pasta>/captura-<nome>.png e fecha.

        Usado por `python -m app --teste-interface` e pelo CI do Windows:
        prova que cada tela abre e desenha sem erro.
        """
        passos: list = []
        for nome in self.paginas:
            passos.append(("pagina", nome))
            if nome == "config":
                aba = getattr(self.paginas[nome], "abas", None)
                if aba is not None:
                    for i in range(1, len(aba.tabs())):
                        passos.append(("aba", i))
        passos += [("codigo", None), ("assistente", None)]
        self.capturas: list[Path] = []
        self.falhas_teste: list[str] = []

        def proximo(i=0):
            if i >= len(passos):
                self.codigo_saida = 1 if self.falhas_teste else 0
                if ao_fim:
                    ao_fim()
                else:
                    self.destruir()
                return
            tipo, valor = passos[i]
            alvo = self.raiz
            nome_captura = ""
            try:
                if tipo == "pagina":
                    self.mostrar(valor)
                    nome_captura = valor
                elif tipo == "aba":
                    self.paginas["config"].abas.select(valor)
                    nome_captura = f"config-{valor + 1}"
                elif tipo == "codigo":
                    from .tarefas import PedidoCodigo
                    self.mostrar("baixar")
                    pedido = PedidoCodigo("Código de verificação do e-SAJ",
                                          "O e-SAJ enviou um código para o seu e-mail. "
                                          "Digite-o abaixo para continuar o download.", 180)
                    alvo = dialogos.DialogoCodigo(self.raiz, pedido)
                    nome_captura = "codigo"
                elif tipo == "assistente":
                    self.mostrar("inicio")
                    alvo = dialogos.Assistente(self)
                    nome_captura = "assistente"
            except Exception as erro:
                log.exception("teste de interface: %s %s falhou", tipo, valor)
                self.falhas_teste.append(f"{tipo} {valor}: {erro}")

            def capturar_e_seguir():
                try:
                    self.raiz.update()
                    if pasta is not None and nome_captura:
                        destino = Path(pasta) / f"captura-{nome_captura}.png"
                        if capturar(alvo, destino):
                            self.capturas.append(destino)
                except Exception as erro:
                    log.warning("captura de %s falhou: %s", nome_captura, erro)
                if alvo is not self.raiz:
                    try:
                        alvo.fechar()
                    except Exception:
                        pass
                proximo(i + 1)
            # tempo para as threads de estado responderem e a tela assentar
            self.raiz.after(700 if tipo == "pagina" else 400, capturar_e_seguir)

        proximo()


def capturar(janela: tk.Misc, destino: Path) -> bool:
    """Salva a imagem da janela em PNG. Devolve False (sem erro) se não houver
    como capturar neste sistema."""
    janela.update()
    x, y = janela.winfo_rootx(), janela.winfo_rooty()
    largura, altura = janela.winfo_width(), janela.winfo_height()
    if largura < 10 or altura < 10:
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import ImageGrab

        extra = {"all_screens": True} if sys.platform == "win32" else {}
        imagem = ImageGrab.grab(bbox=(x, y, x + largura, y + altura), **extra)
        imagem.save(destino)
        return True
    except Exception as erro:
        log.debug("ImageGrab indisponível (%s); tentando o ImageMagick", erro)
    if shutil.which("import"):
        try:
            subprocess.run(["import", "-window", "root", "-crop",
                            f"{largura}x{altura}+{x}+{y}", "+repage", str(destino)],
                           check=True, timeout=30, capture_output=True)
            return destino.exists()
        except Exception as erro:
            log.debug("import falhou: %s", erro)
    return False


def executar(teste: bool = False, pasta_capturas: Path | None = None, cfg=None) -> int:
    """Abre a janela (bloqueia até fechar). Devolve o código de saída.

    Com teste=True percorre as páginas, salva capturas em Logs\\ e fecha
    sozinho - é o teste de interface do CI.
    """
    registro.preparar_saidas()
    try:
        registro.configurar(console=teste)
    except Exception:
        pass
    sistema.id_do_aplicativo()          # ícone próprio na barra de tarefas (bug B9)
    estilo.consciencia_de_dpi()         # antes de criar a janela
    try:
        raiz = tk.Tk(className="AssessorIntegrado")
    except tk.TclError as erro:
        log.error("não foi possível abrir a janela: %s", erro)
        print(f"Não foi possível abrir a janela: {erro}", file=sys.stderr)
        return 1
    raiz.withdraw()
    try:
        estilo.aplicar(raiz)
        janela = Janela(raiz, cfg=cfg, teste=teste)
    except Exception:
        log.exception("a janela não pôde ser montada")
        raiz.destroy()
        raise
    raiz.deiconify()
    estilo.pintar_barra_de_titulo(raiz)
    if teste:
        destino = Path(pasta_capturas) if pasta_capturas else caminhos.LOGS

        def salvaguarda():
            # se algo travar, o CI não fica esperando para sempre
            if janela._viva():
                log.error("teste de interface: tempo esgotado")
                janela.codigo_saida = 1
                janela.destruir()
        raiz.after(120_000, salvaguarda)
        raiz.after(400, lambda: janela.percorrer(destino))
    raiz.mainloop()
    if teste:
        n = len(getattr(janela, "capturas", []))
        falhas = getattr(janela, "falhas_teste", [])
        print(f"Teste de interface: {len(janela.paginas)} página(s), {n} captura(s)"
              + (f", {len(falhas)} falha(s): {'; '.join(falhas)}" if falhas else ", sem falhas."))
    return janela.codigo_saida
