"""A janela do Helestron: WebView2 (pywebview), com duas reservas.

    1. pywebview com o motor "edgechromium" (WebView2, presente no Windows 10
       atualizado e no 11): janela nativa, título "Helestron", ícone do H,
       diálogos nativos de arquivo e pasta;
    2. reserva 1 - o Edge em modo aplicativo (msedge --app=URL, perfil
       próprio em LOCAL\\edge-app): janela sem barra de endereço, quase
       igual; sem diálogos nativos (a página usa o envio de arquivo);
    3. reserva 2 - o navegador padrão, numa aba.

Por que conferir o WebView2 antes: sem ele, a pywebview cai sozinha no
motor do Internet Explorer (MSHTML), que não desenha a interface (vidro,
ES2020). Melhor o Edge em modo aplicativo.

Nas reservas o programa não sabe quando a janela fecha pelo próprio
navegador: encerra quando o processo do Edge sai e a página para de dar
sinal (conexão de eventos ou /api/ping) por SEM_SINAL_S segundos.

HELESTRON_JANELA=webview|edge|navegador|nenhuma força o modo (diagnóstico
e testes; "nenhuma" só espera o encerramento pela API).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .. import NOME
from ..nucleo import caminhos
from ..tarefas import Pergunta

log = logging.getLogger("aplicativo.janela")

LARGURA, ALTURA = 1280, 820
MINIMO = (1100, 720)
COR_FUNDO = "#F2F4F7"
SEM_SINAL_S = 60.0
PRIMEIRO_SINAL_S = 120.0
NO_WINDOWS = sys.platform == "win32"
CHAVE_WEBVIEW2 = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
MODOS = ("webview", "edge", "navegador", "nenhuma")


# ============================================================ o que há aqui
def webview2_disponivel() -> bool:
    """O WebView2 Runtime está instalado? (Mesmas chaves que a pywebview lê.)"""
    if not NO_WINDOWS:
        return False
    try:
        import winreg
    except ImportError:                                     # pragma: no cover
        return False
    caminhos_chave = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{CHAVE_WEBVIEW2}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{CHAVE_WEBVIEW2}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{CHAVE_WEBVIEW2}"),
    ]
    for raiz, chave in caminhos_chave:
        try:
            with winreg.OpenKey(raiz, chave) as k:
                versao, _ = winreg.QueryValueEx(k, "pv")
        except OSError:
            continue
        if versao and str(versao) not in ("0.0.0.0", "0"):
            return True
    return False


def achar_edge() -> Path | None:
    """O msedge.exe, onde quer que esteja."""
    candidatos = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            candidatos.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    if NO_WINDOWS:
        try:
            import winreg

            for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(raiz, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
                                              r"\msedge.exe") as k:
                        valor, _ = winreg.QueryValueEx(k, "")
                        candidatos.append(Path(str(valor).strip('"')))
                except OSError:
                    continue
        except ImportError:                                 # pragma: no cover
            pass
    for c in candidatos:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    achado = shutil.which("msedge") or shutil.which("microsoft-edge")
    return Path(achado) if achado else None


def _escolher_modo() -> list[str]:
    forcado = (os.environ.get("HELESTRON_JANELA") or "").strip().lower()
    if forcado in MODOS:
        return [forcado]
    ordem = []
    if NO_WINDOWS and webview2_disponivel():
        ordem.append("webview")
    ordem += ["edge", "navegador"]
    return ordem


# ===================================================================== base
class Janela:
    """O que o servidor espera de uma janela (app.janela)."""

    modo = "nenhuma"
    tem_dialogos = False

    def __init__(self, app):
        self.app = app

    def abrir(self, url: str) -> bool:
        """Abre e BLOQUEIA até a janela fechar. False: não conseguiu abrir."""
        raise NotImplementedError

    def mostrar(self) -> bool:
        return False

    def fechar(self) -> None:
        pass

    def retangulo(self) -> tuple[int, int, int, int] | None:
        """(x, y, largura, altura) na tela, para a captura do autoteste."""
        return None

    # A espera das reservas: até o Edge fechar e a página parar de dar sinal.
    def _esperar_pagina(self, processo: subprocess.Popen | None = None) -> None:
        inicio = time.monotonic()
        hub = self.app.hub
        while not self.app.encerrado.wait(1.0):
            agora = time.monotonic()
            conectado = hub.conectados > 0
            recente = agora - hub.ultimo_contato < SEM_SINAL_S
            if processo is not None and processo.poll() is not None and not conectado:
                if agora - hub.ultimo_contato > 5:
                    log.info("o Edge fechou: encerrando")
                    return
            if conectado or recente:
                continue
            if agora - inicio < PRIMEIRO_SINAL_S and hub.ultimo_contato <= self.app.iniciado_em:
                continue
            log.info("a página parou de dar sinal há %d s: encerrando", int(SEM_SINAL_S))
            return


class JanelaNenhuma(Janela):
    """Sem janela: espera o encerramento pela API (testes, --servidor)."""

    def abrir(self, url: str) -> bool:
        self.app.encerrado.wait()
        return True


# ================================================================ pywebview
class JanelaWebview(Janela):
    modo = "janela"
    tem_dialogos = True

    def __init__(self, app):
        super().__init__(app)
        self.webview = None
        self.janela = None
        self._pode_fechar = False
        self._perguntando_desde: float | None = None

    def abrir(self, url: str) -> bool:
        try:
            import webview
        except Exception as erro:
            log.warning("pywebview indisponível (%s): uso a reserva", erro)
            return False
        self.webview = webview
        try:
            self.janela = webview.create_window(
                NOME, url, width=LARGURA, height=ALTURA, min_size=MINIMO,
                background_color=COR_FUNDO, text_select=True)
            self.janela.events.closing += self._ao_fechar
            self.janela.events.shown += self._ao_mostrar
            pasta = Path(caminhos.LOCAL) / "webview"
            pasta.mkdir(parents=True, exist_ok=True)
            self.app.ao_encerrar.append(self.fechar)
            webview.start(gui="edgechromium", private_mode=False, storage_path=str(pasta),
                          debug=bool(os.environ.get("HELESTRON_DEPURAR")))
        except Exception as erro:
            log.warning("a janela WebView2 não abriu (%s): uso a reserva", erro)
            if self.fechar in self.app.ao_encerrar:
                self.app.ao_encerrar.remove(self.fechar)
            return False
        if not self.janela.events.shown.is_set() and not self.app.fechando:
            # O WebView2 falhou ao iniciar (runtime corrompido, política da
            # empresa): a janela nunca apareceu.
            log.warning("a janela WebView2 não chegou a aparecer: uso a reserva")
            if self.fechar in self.app.ao_encerrar:
                self.app.ao_encerrar.remove(self.fechar)
            return False
        return True

    # ----------------------------------------------------------- eventos
    def _ao_mostrar(self) -> None:
        """O ícone do H na barra de título e na barra de tarefas."""
        from ..servidor.aplicacao import Aplicacao

        icone = Aplicacao.arquivo_icone()
        if icone is None:
            return
        try:
            import clr                                     # pythonnet

            clr.AddReference("System.Drawing")
            clr.AddReference("System.Windows.Forms")
            from System import Action                      # type: ignore
            from System.Drawing import Icon                # type: ignore

            forma = self.janela.native
            novo = Icon(str(icone))

            def aplicar():
                forma.Icon = novo

            if getattr(forma, "InvokeRequired", False):
                forma.Invoke(Action(aplicar))
            else:
                aplicar()
        except Exception as erro:
            log.debug("ícone da janela não aplicado: %s", erro)

    def _ao_fechar(self):
        """O X da janela. Com trabalho em andamento, pergunta antes (pela página).

        Devolver False cancela o fechamento (a pywebview chama isto na
        thread da janela: nada de esperar aqui). O segundo clique, depois de
        5 s sem resposta, fecha mesmo assim: a página pode estar travada.
        """
        if self._pode_fechar or self.app.fechando:
            return True
        pendentes = self.app.trabalho_em_andamento()
        if not pendentes:
            self._pode_fechar = True
            return True
        if self._perguntando_desde is not None:
            if time.monotonic() - self._perguntando_desde > 5:
                log.warning("fechamento forçado com trabalho em andamento")
                self._pode_fechar = True
                threading.Thread(target=self.app.encerrar, name="encerrar", daemon=True).start()
            return False
        self._perguntando_desde = time.monotonic()
        threading.Thread(target=self._confirmar, args=(pendentes,), name="confirmar-fechar",
                         daemon=True).start()
        return False

    def _confirmar(self, pendentes: list[str]) -> None:
        pergunta = Pergunta(
            f"Fechar o {NOME}?",
            "Há trabalho em andamento:\n" + "\n".join(f"•  {p}" for p in pendentes)
            + "\n\nFechar mesmo assim? O que estiver em andamento é interrompido com segurança "
              "— a transcrição da audiência é salva antes.", 120, tipo="confirmar",
            opcoes={"sim": "Fechar mesmo assim", "nao": "Continuar"})
        self.app.perguntas.abrir(pergunta)
        resposta = pergunta.esperar()
        self._perguntando_desde = None
        if resposta:
            self.app.encerrar()            # ao_encerrar fecha a janela no fim

    # ------------------------------------------------------------ ações
    def mostrar(self) -> bool:
        j = self.janela
        if j is None:
            return False
        try:
            j.restore()
            j.show()
        except Exception as erro:
            log.debug("restaurar a janela: %s", erro)
        hwnd = self._hwnd()
        if hwnd and NO_WINDOWS:
            try:
                import ctypes

                ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception as erro:
                log.debug("trazer a janela à frente: %s", erro)
        return True

    def fechar(self) -> None:
        self._pode_fechar = True
        j = self.janela
        if j is not None:
            try:
                j.destroy()
            except Exception as erro:
                log.debug("fechar a janela: %s", erro)

    def _hwnd(self) -> int | None:
        try:
            return int(self.janela.native.Handle.ToInt64())
        except Exception:
            return None

    def retangulo(self) -> tuple[int, int, int, int] | None:
        hwnd = self._hwnd()
        if hwnd and NO_WINDOWS:
            try:
                import ctypes
                from ctypes import wintypes

                r = wintypes.RECT()
                if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    return r.left, r.top, r.right - r.left, r.bottom - r.top
            except Exception:
                pass
        try:
            j = self.janela
            return int(j.x), int(j.y), int(j.width), int(j.height)
        except Exception:
            return None

    # --------------------------------------------------------- diálogos
    def _tipo(self, nome: str, numero: int):
        enum = getattr(self.webview, "FileDialog", None)
        return getattr(enum, nome) if enum is not None else numero

    def dialogo_arquivo(self, titulo: str, tipos: list[str], inicial: str = "") -> str | None:
        if self.janela is None:
            return None
        resultado = self.janela.create_file_dialog(
            self._tipo("OPEN", 10), directory=inicial or "", allow_multiple=False,
            file_types=tuple(tipos) if tipos else ())
        if not resultado:
            return None
        return str(resultado[0] if isinstance(resultado, (list, tuple)) else resultado)

    def dialogo_pasta(self, titulo: str, inicial: str = "") -> str | None:
        if self.janela is None:
            return None
        resultado = self.janela.create_file_dialog(self._tipo("FOLDER", 20),
                                                   directory=inicial or "")
        if not resultado:
            return None
        return str(resultado[0] if isinstance(resultado, (list, tuple)) else resultado)


# ===================================================================== Edge
class JanelaEdge(Janela):
    modo = "edge"

    def __init__(self, app, executavel: Path | None = None):
        super().__init__(app)
        self.executavel = executavel
        self.processo: subprocess.Popen | None = None
        self.url = ""

    def abrir(self, url: str) -> bool:
        exe = self.executavel or achar_edge()
        if exe is None:
            return False
        self.url = url
        perfil = Path(caminhos.LOCAL) / "edge-app"
        perfil.mkdir(parents=True, exist_ok=True)
        argumentos = [str(exe), f"--app={url}", f"--user-data-dir={perfil}",
                      f"--window-size={LARGURA},{ALTURA}", "--no-first-run",
                      "--no-default-browser-check", "--disable-features=Translate"]
        try:
            self.processo = subprocess.Popen(argumentos, close_fds=True)
        except OSError as erro:
            log.warning("o Edge não abriu (%s)", erro)
            return False
        self.app.ao_encerrar.append(self.fechar)
        self._esperar_pagina(self.processo)
        return True

    def mostrar(self) -> bool:
        if NO_WINDOWS and _trazer_a_frente(NOME):
            return True
        if self.processo is not None and self.processo.poll() is None:
            return False
        # O Edge foi fechado, mas a página continuou viva (outra janela):
        # abre de novo.
        exe = self.executavel or achar_edge()
        if exe is None:
            return False
        perfil = Path(caminhos.LOCAL) / "edge-app"
        try:
            self.processo = subprocess.Popen([str(exe), f"--app={self.url}",
                                              f"--user-data-dir={perfil}"], close_fds=True)
        except OSError:
            return False
        return True

    def fechar(self) -> None:
        p = self.processo
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass

    def retangulo(self) -> tuple[int, int, int, int] | None:
        return _retangulo_por_titulo(NOME) if NO_WINDOWS else None


# ================================================================ navegador
class JanelaNavegador(Janela):
    modo = "navegador"

    def __init__(self, app):
        super().__init__(app)
        self.url = ""

    def abrir(self, url: str) -> bool:
        self.url = url
        try:
            if not webbrowser.open(url, new=1):
                return False
        except Exception as erro:
            log.warning("o navegador padrão não abriu (%s)", erro)
            return False
        self._esperar_pagina()
        return True

    def mostrar(self) -> bool:
        if NO_WINDOWS and _trazer_a_frente(NOME):
            return True
        try:
            return bool(webbrowser.open(self.url, new=2))
        except Exception:
            return False


# ============================================================ apoio Windows
def _achar_janela(titulo: str) -> int | None:
    """A janela de primeiro nível cujo título começa por 'titulo'."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        achadas: list[int] = []
        prototipo = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def ver(hwnd, _l):
            if not user32.IsWindowVisible(hwnd):
                return True
            tamanho = user32.GetWindowTextLengthW(hwnd)
            if tamanho:
                buf = ctypes.create_unicode_buffer(tamanho + 1)
                user32.GetWindowTextW(hwnd, buf, tamanho + 1)
                if buf.value.startswith(titulo):
                    achadas.append(hwnd)
                    return False
            return True

        user32.EnumWindows(prototipo(ver), 0)
        return achadas[0] if achadas else None
    except Exception:
        return None


def _trazer_a_frente(titulo: str) -> bool:
    hwnd = _achar_janela(titulo)
    if not hwnd:
        return False
    try:
        import ctypes

        if ctypes.windll.user32.IsIconic(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def _retangulo_por_titulo(titulo: str) -> tuple[int, int, int, int] | None:
    hwnd = _achar_janela(titulo)
    if not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        r = wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:
        pass
    return None


def permitir_primeiro_plano(pid: int) -> None:
    """A segunda abertura (que está em primeiro plano) deixa a primeira vir
    à frente - o Windows não deixa um processo de fundo roubar o foco."""
    if not NO_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
    except Exception:
        pass


# ===================================================================== abrir
def abrir(app, url: str) -> str:
    """Abre a janela no melhor modo disponível e BLOQUEIA até ela fechar.

    Devolve o modo usado ("janela", "edge", "navegador", "nenhuma") ou ""
    se nada abriu.
    """
    for modo in _escolher_modo():
        if modo == "webview":
            janela: Janela = JanelaWebview(app)
        elif modo == "edge":
            janela = JanelaEdge(app)
        elif modo == "navegador":
            janela = JanelaNavegador(app)
        else:
            janela = JanelaNenhuma(app)
        app.janela = janela
        app.modo = janela.modo if janela.modo in ("janela", "edge", "navegador") else "servidor"
        log.info("abrindo a janela (modo %s)", modo)
        if janela.abrir(url):
            return janela.modo
        app.janela = None
    return ""
