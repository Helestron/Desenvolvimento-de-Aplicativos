"""A janela do Helestron: WebView2 (pywebview), com duas reservas.

    1. pywebview com o motor "edgechromium" (WebView2, presente no Windows 10
       atualizado e no 11): janela nativa, título "Helestron", ícone do H,
       diálogos nativos de arquivo e pasta;
    2. reserva 1 — o Edge em modo aplicativo (msedge --app=URL, perfil
       próprio em LOCAL\\edge-app): janela sem barra de endereço, quase
       igual; sem diálogos nativos (a página usa o envio de arquivo);
    3. reserva 2 — o navegador padrão, numa aba. Nunca o Internet Explorer
       nem o Edge antigo (EdgeHTML): eles não rodam a interface (ES2020), e
       a página ficaria em branco. Sem nenhuma das três, o programa explica
       numa caixa de mensagem como instalar o WebView2 (motivo_sem_janela).

Por que conferir o WebView2 antes: sem ele, a pywebview cai sozinha no
motor do Internet Explorer (MSHTML), que não desenha a interface (vidro,
ES2020). Melhor o Edge em modo aplicativo. E a versão: a pywebview 6 usa
uma interface do WebView2 que só existe a partir do runtime 101
(ICoreWebView2Environment10); com um runtime mais velho (Windows 10 cuja
TI bloqueia as atualizações do Edge) a janela abriria vazia.

Mesmo com o WebView2 aprovado, a inicialização dele pode falhar (runtime
danificado, política da empresa): a pywebview só registra o erro e deixa a
janela cinza e vazia. Por isso uma vigia espera a página dar sinal (o
evento 'loaded' da pywebview ou a página conectada ao canal de eventos) e,
se ela não der em PRAZO_CARREGAR_S, fecha a janela vazia e passa para o Edge.

O sinal da página é só dela: o canal de eventos (/api/eventos), que só a
página abre (o EventSource de web/js/api.js e o da tela de erro). Um pedido
qualquer à API não conta — a segunda abertura do programa (o duplo clique de
novo no atalho diante da janela cinza: /api/ping e /api/janela/mostrar) e o
instalador também falam com o servidor, e a janela vazia passaria por
carregada.

Nas reservas o programa não sabe quando a janela fecha pelo próprio
navegador: encerra quando o processo do Edge sai e a página para de dar
sinal (o canal de eventos, com o ping dele a cada INTERVALO_PING_S) por
SEM_SINAL_S segundos.

O tamanho inicial cabe na área útil do monitor (sem a barra de tarefas):
num notebook Full HD a 150 % (1280×672 DIP úteis), a janela padrão de
1280×820 passaria da tela e esconderia o rodapé atrás da barra de tarefas —
lá ela abre maximizada.

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
# Folga (DIP) entre a janela e as bordas da área útil do monitor.
MARGEM_TELA = 16
COR_FUNDO = "#F2F4F7"
SEM_SINAL_S = 60.0
PRIMEIRO_SINAL_S = 120.0
# A janela WebView2 apareceu: a página tem este prazo para dar sinal. A
# primeira partida do WebView2 num computador lento leva alguns segundos.
PRAZO_CARREGAR_S = 30.0
# ... e a própria janela, para aparecer (o .NET carregando a frio).
PRAZO_APARECER_S = 120.0
NO_WINDOWS = sys.platform == "win32"
CHAVE_WEBVIEW2 = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
# O primeiro runtime com ICoreWebView2Environment10, que a pywebview 6
# sempre usa (CreateCoreWebView2ControllerOptions).
VERSAO_MINIMA_WEBVIEW2 = (101, 0, 1210, 39)
URL_WEBVIEW2 = "https://developer.microsoft.com/microsoft-edge/webview2/"
# Navegadores padrão que não rodam a interface: o Internet Explorer e o Edge
# antigo (EdgeHTML, do Windows 10 de 2015 a 2020).
PROGIDS_EDGE_ANTIGO = ("AppXq0fevzme2pys62n3e0fbqa7peapykr8v",
                       "AppX90nv6nhay5n6a98fnetv7tpk64pp35es")
MODOS = ("webview", "edge", "navegador", "nenhuma")


# ============================================================ o que há aqui
def _versao(texto) -> tuple[int, ...] | None:
    """'101.0.1210.39' -> (101, 0, 1210, 39); None se não for uma versão."""
    partes = str(texto or "").strip().split(".")
    if not partes or not all(p.isdigit() for p in partes):
        return None
    numeros = tuple(int(p) for p in partes[:4])
    return numeros + (0,) * (4 - len(numeros))


def versao_suficiente(texto) -> bool:
    """A versão do WebView2 Runtime serve para a pywebview 6 (101 ou mais recente)?"""
    v = _versao(texto)
    return v is not None and any(v) and v >= VERSAO_MINIMA_WEBVIEW2


def versao_webview2() -> str | None:
    """A versão ("pv") do WebView2 Runtime instalada — a maior das chaves que
    a pywebview lê -, ou None se ele não estiver instalado."""
    if not NO_WINDOWS:
        return None
    try:
        import winreg
    except ImportError:                                     # pragma: no cover
        return None
    caminhos_chave = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{CHAVE_WEBVIEW2}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{CHAVE_WEBVIEW2}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{CHAVE_WEBVIEW2}"),
    ]
    achadas = []
    for raiz, chave in caminhos_chave:
        try:
            with winreg.OpenKey(raiz, chave) as k:
                versao, _ = winreg.QueryValueEx(k, "pv")
        except OSError:
            continue
        v = _versao(versao)
        if v is not None and any(v):
            achadas.append((v, str(versao).strip()))
    return max(achadas)[1] if achadas else None


def webview2_disponivel() -> bool:
    """O WebView2 Runtime está instalado, numa versão que a pywebview usa?

    Um runtime antigo (86 a 100) conta como ausente: a janela abriria vazia,
    e o Edge em modo aplicativo funciona.
    """
    if not NO_WINDOWS:
        return False
    return versao_suficiente(versao_webview2())


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


def navegador_inadequado(progid: str | None, comando: str | None = None) -> bool:
    """O navegador padrão é o Internet Explorer ou o Edge antigo?

    'progid' vem da escolha do usuário (UserChoice); sem ela, vale o
    comando que o Windows associa ao http (o do sistema).
    """
    p = (progid or "").strip()
    if p:
        return p.upper().startswith("IE.") or p in PROGIDS_EDGE_ANTIGO
    return "iexplore.exe" in (comando or "").lower()


def _navegador_padrao() -> tuple[str | None, str | None]:  # pragma: no cover — só no Windows
    """(ProgId escolhido pelo usuário, comando do http no sistema)."""
    import winreg

    progid = None
    for protocolo in ("https", "http"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations"
                                rf"\{protocolo}\UserChoice") as k:
                progid = str(winreg.QueryValueEx(k, "ProgId")[0] or "") or None
        except OSError:
            continue
        if progid:
            break
    comando = None
    if not progid:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"http\shell\open\command") as k:
                comando = str(winreg.QueryValueEx(k, "")[0] or "")
        except OSError:
            pass
    return progid, comando


def navegador_padrao_serve() -> bool:
    """O navegador padrão roda a interface? (Fora do Windows, sempre.)"""
    if not NO_WINDOWS:
        return True
    try:
        progid, comando = _navegador_padrao()
    except Exception as erro:                              # sem o registro: tenta
        log.debug("navegador padrão não identificado: %s", erro)
        return True
    if navegador_inadequado(progid, comando):
        log.warning("o navegador padrão (%s) não roda a interface do %s", progid or comando, NOME)
        return False
    return True


def motivo_sem_janela() -> str:
    """O texto da caixa de mensagem quando nenhuma janela abriu."""
    if NO_WINDOWS:
        try:
            versao = versao_webview2()
            sem_edge = achar_edge() is None
        except Exception:                                   # pragma: no cover
            versao, sem_edge = None, True
        if sem_edge and not versao_suficiente(versao):
            if versao:
                inicio = (f"O Microsoft Edge WebView2 Runtime deste computador é antigo (versão "
                          f"{versao}; o {NOME} precisa da 101 ou de uma mais recente), e o "
                          "Microsoft Edge não foi encontrado.")
            else:
                inicio = (f"O {NOME} abre numa janela do Microsoft Edge WebView2 Runtime, que não "
                          "está instalado neste computador (nem o Microsoft Edge). O Internet "
                          "Explorer não é compatível.")
            return (inicio + "\n\nPeça ao suporte de informática que instale o “Microsoft Edge "
                    "WebView2 Runtime” (gratuito, da Microsoft; não precisa de administrador) e "
                    f"abra o {NOME} de novo: {URL_WEBVIEW2}\n\nOutra saída: instalar o Google "
                    f"Chrome e defini-lo como navegador padrão — o {NOME} também abre nele.")
    return (f"Não consegui abrir a janela do {NOME}: nem o WebView2, nem o Microsoft Edge, nem o "
            "navegador padrão responderam.")


def _escolher_modo() -> list[str]:
    forcado = (os.environ.get("HELESTRON_JANELA") or "").strip().lower()
    if forcado in MODOS:
        return [forcado]
    ordem = []
    if NO_WINDOWS and webview2_disponivel():
        ordem.append("webview")
    ordem.append("edge")
    if navegador_padrao_serve():
        ordem.append("navegador")
    return ordem


# ============================================================== o tamanho
def area_util_dip() -> tuple[float, float] | None:
    """(largura, altura) da área útil do monitor onde a janela abre — o do
    ponteiro do mouse, como faz o WinForms -, em pixels lógicos (DIP).
    None fora do Windows ou se a API falhar."""
    if not NO_WINDOWS:
        return None
    try:
        return _area_util_windows()
    except Exception as erro:
        log.debug("área útil do monitor não lida: %s", erro)
        return None


def _area_util_windows() -> tuple[float, float] | None:  # pragma: no cover — só no Windows
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    # Protótipos próprios (e não argtypes nas funções compartilhadas do windll).
    user32, shcore = ctypes.WinDLL("user32"), ctypes.WinDLL("shcore")
    cursor = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.POINTER(wintypes.POINT))(
        ("GetCursorPos", user32))
    monitor_do_ponto = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.POINT, wintypes.DWORD)(
        ("MonitorFromPoint", user32))
    info_do_monitor = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.POINTER(MONITORINFO))(
        ("GetMonitorInfoW", user32))
    dpi_do_monitor = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
                                        ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint))(
        ("GetDpiForMonitor", shcore))
    ponto = wintypes.POINT(0, 0)
    cursor(ctypes.byref(ponto))
    monitor = monitor_do_ponto(ponto, 2)                    # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not monitor or not info_do_monitor(monitor, ctypes.byref(info)):
        return None
    dpi_x, dpi_y = ctypes.c_uint(96), ctypes.c_uint(96)
    if dpi_do_monitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) != 0:   # MDT_EFFECTIVE_DPI
        dpi_x.value = 96
    escala = (dpi_x.value or 96) / 96.0
    r = info.rcWork
    return (r.right - r.left) / escala, (r.bottom - r.top) / escala


def tamanho_inicial(area: tuple[float, float] | None) -> dict:
    """width, height, min_size e maximized da janela, para a área útil dada (DIP).

    Cabe 1280×820 (com folga): abre assim. Não cabe (Full HD a 150 %,
    1366×768): abre MAXIMIZADA, com o tamanho "restaurado" e o mínimo
    cortados para caber — o rodapé nunca fica atrás da barra de tarefas.
    """
    if not area:
        return {"width": LARGURA, "height": ALTURA, "min_size": MINIMO, "maximized": False}
    larg_area, alt_area = max(0.0, float(area[0])), max(0.0, float(area[1]))
    cabe = larg_area >= LARGURA + MARGEM_TELA and alt_area >= ALTURA + MARGEM_TELA
    largura = int(max(400, min(LARGURA, larg_area - MARGEM_TELA)))
    altura = int(max(300, min(ALTURA, alt_area - MARGEM_TELA)))
    minimo = (min(MINIMO[0], largura), min(MINIMO[1], altura))
    return {"width": largura, "height": altura, "min_size": minimo, "maximized": not cabe}


# ===================================================================== base
class Janela:
    """O que o servidor espera de uma janela (app.janela)."""

    modo = "nenhuma"
    tem_dialogos = False

    def __init__(self, app):
        self.app = app
        # A página desta janela já se conectou ao canal de eventos (deu sinal).
        self.pagina_conectou = False

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

    def _pagina_conectada(self) -> bool:
        """Há uma página conectada ao canal de eventos agora? E guarda, em
        'pagina_conectou', que ela se conectou — o sinal de que carregou.

        Só a página abre /api/eventos. Os pedidos à API não servem de sinal:
        a segunda abertura do programa (instancia.chamar_a_aberta) pede
        /api/ping e /api/janela/mostrar justamente quando a janela está cinza
        — quem não vê nada clica de novo no atalho —, e o instalador consulta
        o programa aberto."""
        hub = getattr(self.app, "hub", None)
        try:
            conectada = hub is not None and hub.conectados > 0
        except Exception:                                   # pragma: no cover
            conectada = False
        if conectada:
            self.pagina_conectou = True
        return conectada

    # A espera das reservas: até o Edge fechar e a página parar de dar sinal.
    def _esperar_pagina(self, processo: subprocess.Popen | None = None) -> bool:
        """Devolve True se a página chegou a dar sinal (ou o programa foi
        encerrado pela API); False se ela nunca carregou — um navegador que
        não roda a interface: quem chama tenta a próxima reserva ou explica."""
        inicio = time.monotonic()
        hub = self.app.hub
        while not self.app.encerrado.wait(1.0):
            agora = time.monotonic()
            conectado = self._pagina_conectada()
            deu_sinal = self.pagina_conectou
            if processo is not None and processo.poll() is not None and not conectado:
                if agora - hub.ultimo_contato > 5:
                    log.info("o Edge fechou: encerrando")
                    return deu_sinal
            if conectado or agora - hub.ultimo_contato < SEM_SINAL_S:
                continue
            if not deu_sinal:
                if agora - inicio < PRIMEIRO_SINAL_S:
                    continue
                log.warning("a página não deu nenhum sinal em %d s: a janela não carregou",
                            int(PRIMEIRO_SINAL_S))
                return False
            log.info("a página parou de dar sinal há %d s: encerrando", int(SEM_SINAL_S))
            return True
        return True


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
        self._falhou = False
        self._fim_start = threading.Event()

    def abrir(self, url: str) -> bool:
        try:
            import webview
        except Exception as erro:
            log.warning("pywebview indisponível (%s): uso a reserva", erro)
            return False
        self.webview = webview
        tamanho = tamanho_inicial(area_util_dip())
        try:
            self.janela = webview.create_window(
                NOME, url, width=tamanho["width"], height=tamanho["height"],
                min_size=tamanho["min_size"], maximized=tamanho["maximized"],
                background_color=COR_FUNDO, text_select=True)
            self.janela.events.closing += self._ao_fechar
            self.janela.events.shown += self._ao_mostrar
            pasta = Path(caminhos.LOCAL) / "webview"
            pasta.mkdir(parents=True, exist_ok=True)
            self.app.ao_encerrar.append(self.fechar)
            self._registrar_atencao()
            threading.Thread(target=self._vigiar_carregamento, name="vigia-webview2",
                             daemon=True).start()
            webview.start(gui="edgechromium", private_mode=False, storage_path=str(pasta),
                          debug=bool(os.environ.get("HELESTRON_DEPURAR")))
        except Exception as erro:
            log.warning("a janela WebView2 não abriu (%s): uso a reserva", erro)
            self._desistir()
            return False
        finally:
            self._fim_start.set()
        if self.app.fechando:
            return True
        if not self._deu_sinal():
            if self._falhou:
                log.warning("o WebView2 não carregou a página em %d s (runtime danificado ou "
                            "bloqueado): uso a reserva", int(PRAZO_CARREGAR_S))
            else:
                log.warning("a janela WebView2 fechou sem carregar a página: uso a reserva")
            self._desistir()
            return False
        return True

    def _desistir(self) -> None:
        self._falhou = True
        if self.fechar in self.app.ao_encerrar:
            self.app.ao_encerrar.remove(self.fechar)

    def _deu_sinal(self) -> bool:
        """A página carregou? (O 'loaded' da pywebview, ou a página conectada
        ao canal de eventos — nunca um pedido qualquer à API: _pagina_conectada.)"""
        eventos = getattr(self.janela, "events", None)
        carregou = getattr(eventos, "loaded", None)
        try:
            if carregou is not None and carregou.is_set():
                return True
        except Exception:                                   # pragma: no cover
            pass
        self._pagina_conectada()
        return self.pagina_conectou

    def _apareceu(self) -> bool:
        try:
            return bool(self.janela.events.shown.is_set())
        except Exception:                                   # pragma: no cover
            return False

    def _vigiar_carregamento(self) -> None:
        """A vigia: a janela apareceu, mas a página não dá sinal (o WebView2
        falhou ao iniciar e a pywebview deixou a janela vazia) — fecha a
        janela vazia, e abrir() passa para o Edge."""
        limite = time.monotonic() + PRAZO_APARECER_S
        while not self._apareceu():
            if self._fim_start.wait(0.25) or self.app.fechando or self._deu_sinal():
                return
            if time.monotonic() > limite:
                break
        limite = time.monotonic() + PRAZO_CARREGAR_S
        while time.monotonic() < limite:
            if self._fim_start.wait(0.25) or self.app.fechando or self._deu_sinal():
                return
        if self._deu_sinal() or self.app.fechando:
            return
        log.warning("a janela WebView2 está vazia há %d s: fecho e uso a reserva",
                    int(PRAZO_CARREGAR_S))
        self._falhou = True
        self._pode_fechar = True
        try:
            self.janela.destroy()
        except Exception as erro:
            log.debug("fechar a janela vazia: %s", erro)

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
    def _registrar_atencao(self) -> None:
        """Pede ao servidor que chame chamar_atencao() quando publicar uma
        pergunta (contrato C3: Aplicacao.registrar_atencao). Sem ele, nada."""
        registrar = getattr(self.app, "registrar_atencao", None)
        if not callable(registrar):
            return
        try:
            registrar(self.chamar_atencao)
        except Exception as erro:
            log.debug("chamar atenção nas perguntas: %s", erro)

    def chamar_atencao(self, *_dados, **_mais) -> None:
        """Chegou uma pergunta (o código do e-SAJ, o do autenticador do
        eProc): a janela volta da barra de tarefas, vem para a frente e
        pisca. O magistrado pode estar em outro programa — sem resposta no
        prazo, o lote inteiro termina em "login falhou". (Aceita e ignora o
        que o servidor mandar junto, como a própria pergunta.)"""
        if self._falhou or self.janela is None or getattr(self.app, "janela", None) is not self \
                or self.app.fechando:
            return
        hwnd = self._hwnd() if NO_WINDOWS else None
        if hwnd:
            chamar_atencao_hwnd(hwnd)
            return
        try:
            self.janela.restore()
            self.janela.show()
        except Exception as erro:
            log.debug("chamar atenção: %s", erro)

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
        tamanho = tamanho_inicial(area_util_dip())
        argumentos = [str(exe), f"--app={url}", f"--user-data-dir={perfil}",
                      f"--window-size={tamanho['width']},{tamanho['height']}", "--no-first-run",
                      "--no-default-browser-check", "--disable-features=Translate"]
        if tamanho["maximized"]:
            argumentos.append("--start-maximized")
        try:
            self.processo = subprocess.Popen(argumentos, close_fds=True)
        except OSError as erro:
            log.warning("o Edge não abriu (%s)", erro)
            return False
        self.app.ao_encerrar.append(self.fechar)
        if self._esperar_pagina(self.processo):
            return True
        # O Edge abriu e fechou sem a página carregar: tenta a próxima reserva.
        self.fechar()
        if self.fechar in self.app.ao_encerrar:
            self.app.ao_encerrar.remove(self.fechar)
        return False

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
        return self._esperar_pagina()

    def mostrar(self) -> bool:
        if NO_WINDOWS and _trazer_a_frente(NOME):
            return True
        try:
            return bool(webbrowser.open(self.url, new=2))
        except Exception:
            return False


# ============================================================ apoio Windows
SW_RESTORE = 9
FLASHW_ALL = 0x3                # a barra de título e o botão na barra de tarefas
FLASHW_TIMERNOFG = 0xC          # até a janela vir para a frente


def chamar_atencao_hwnd(hwnd: int, user32=None) -> None:
    """Restaura a janela minimizada, tenta trazê-la à frente e a faz piscar
    na barra de tarefas (FlashWindowEx). O Windows pode recusar o primeiro
    plano a um programa de fundo; o piscar é o que garante o aviso."""
    import ctypes
    from ctypes import wintypes

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

    if user32 is None:
        user32 = ctypes.windll.user32
    try:
        if user32.IsIconic(hwnd):
            # assíncrono: a thread da janela pode estar ocupada, e esta não espera
            user32.ShowWindowAsync(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    except Exception as erro:
        log.debug("trazer a janela à frente: %s", erro)
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
    try:
        user32.FlashWindowEx(ctypes.byref(info))
    except Exception as erro:
        log.debug("piscar na barra de tarefas: %s", erro)


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
    à frente — o Windows não deixa um processo de fundo roubar o foco."""
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
    se nada abriu (quem chama mostra motivo_sem_janela()).
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
        if getattr(app, "fechando", False):
            break
    return ""
