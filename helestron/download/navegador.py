"""Navegador automatizado (Playwright), comum a todos os portais.

Porte do navegador do Assessor SAJ (app/esaj/navegador.py), sem nada que
seja do e-SAJ: o login de cada portal mora no módulo do portal. O que fica
aqui é o que vale para qualquer tribunal:

* abrir o navegador certo. "auto" usa o Chrome instalado; sem ele, o Edge,
  presente em todo Windows 10/11. O programa NÃO baixa navegador nenhum (a
  versão anterior baixava ~150 MB de Chromium na instalação, e a rede do
  tribunal costumava barrar); o Chromium do Playwright só entra como
  reserva, se já estiver neste computador (PLAYWRIGHT_BROWSERS_PATH ou a
  pasta padrão ms-playwright);
* abrir invisível e, se o modo invisível falhar, com a janela fora da tela
  (mesmo efeito para quem usa) - técnica herdada que resolveu máquinas em
  que o headless não sobe;
* um perfil próprio por portal (em %LOCALAPPDATA%, fora do OneDrive e fora
  do Acervo compartilhado com a IA), e a sessão (cookies) guardada ao
  fechar e devolvida ao abrir, por até 12 horas: o cookie do e-SAJ é de
  sessão e o navegador o descarta ao fechar - sem isso, cada execução
  pedia login e código por e-mail de novo;
* caixas nativas (alert/confirm) dispensadas em TODAS as abas - na base só
  a primeira aba tinha esse cuidado, e um alert numa aba nova travava o lote;
* diagnóstico (captura da tela + HTML) em Logs\\diagnostico;
* o modo certificado (Web Signer): cópia do perfil do Chrome do usuário,
  onde mora a extensão que fala com o token, e janela sempre visível (o PIN
  é uma caixa nativa).

O Playwright só é importado ao abrir: a janela do programa carrega este
módulo sem custo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..nucleo import caminhos, sistema
from .modelos import AJUSTES_ACESSOS, ENTRAR_MANUALMENTE, PortalIndisponivel

log = logging.getLogger("download.navegador")

# Onde o Chrome e o Edge costumam estar. O Playwright acha sozinho pelo
# canal, mas conferir antes troca um erro obscuro por uma escolha sensata.
CANDIDATOS_CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)
CANDIDATOS_EDGE = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
)

# Perfil do Chrome do usuário, de onde o login por certificado copia a
# extensão Web Signer (Softplan), que conversa com o token.
USER_DATA_CHROME = Path(os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"))
EXT_WEB_SIGNER = "bbafmabaelnnkondpfpjmdklbmfnbmol"

# Pastas do perfil que não vale a pena copiar (cache) ou que NÃO podem vir
# (abas abertas e downloads pendentes, que o Chrome retomaria sozinho).
_NAO_COPIAR = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache",
    "DawnWebGPUCache", "GrShaderCache", "ShaderCache", "Service Worker",
    "Media Cache", "Application Cache", "File System", "IndexedDB",
    "Crashpad", "BrowserMetrics", "component_crx_cache",
    "extensions_crx_cache", "optimization_guide_model_store",
    "Safe Browsing", "segmentation_platform", "AutofillStates",
    "Sessions", "Session Storage", "Download Service", "DownloadMetadata",
    "Current Session", "Current Tabs", "Last Session", "Last Tabs",
}

SESSAO_VALIDA_S = 12 * 3600
ARGS_PADRAO = ["--disable-blink-features=AutomationControlled",
               "--no-first-run", "--no-default-browser-check",
               "--hide-crash-restore-bubble", "--disable-session-crashed-bubble"]
FORA_DA_TELA = "--window-position=-32000,-32000"
MANTER_DIAGNOSTICOS = 300     # arquivos; os mais antigos saem


# ------------------------------------------------------------------ texto
def sem_acento(texto: str | None) -> str:
    """Minúsculas e sem acento, para comparar com o que a tela escreve."""
    bruto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in bruto if unicodedata.category(c) != "Mn")


def recusou_credenciais(texto: str | None) -> bool:
    """Se a tela está dizendo que usuário ou senha não servem.

    O portal escreve 'Usuário ou senha inválidos' COM ACENTO, e procurar
    'inval' no texto cru nunca casava: o 'á' separa 'inv' de 'lidos'. O
    programa então culpava a demora da tela por uma senha errada.

    Senha EXPIRADA não entra aqui - pede troca, não conferência -, e não
    precisa de guarda: o aviso de expirada não traz 'inválido' nem
    'incorreta'. Guarda por 'expirad' seria pior que inútil, porque a tela
    de login do e-SAJ carrega ESSE bloco escondido em toda visita.
    """
    limpo = sem_acento(texto)
    return "senha" in limpo and ("inval" in limpo or "incorret" in limpo
                                 or "nao confere" in limpo)


_ERROS_DE_REDE = (
    ("ERR_NAME_NOT_RESOLVED", "o endereço do portal não foi encontrado: sem internet, "
     "ou o endereço em dados\\tribunais.json está errado"),
    ("ERR_INTERNET_DISCONNECTED", "o computador está sem internet"),
    ("ERR_CONNECTION_REFUSED", "o portal recusou a conexão (fora do ar ou em manutenção)"),
    ("ERR_CONNECTION_TIMED_OUT", "o portal não respondeu (fora do ar, ou bloqueado pela rede)"),
    ("ERR_TIMED_OUT", "o portal não respondeu a tempo"),
    ("ERR_CONNECTION_RESET", "a conexão com o portal caiu no meio"),
    ("ERR_CONNECTION_CLOSED", "a conexão com o portal caiu no meio"),
    ("ERR_PROXY", "o proxy da rede recusou a conexão (fale com a informática do tribunal)"),
    ("ERR_TUNNEL_CONNECTION_FAILED", "o proxy da rede recusou a conexão (fale com a informática do tribunal)"),
    ("ERR_CERT", "o certificado de segurança do site não foi aceito (relógio do "
     "computador errado, ou inspeção de rede)"),
    ("ERR_SSL", "falha na conexão segura com o portal"),
    ("Timeout", "o portal demorou demais para responder"),
)


def explicar_erro(mensagem: str) -> str:
    """Traduz o erro técnico do navegador numa frase que orienta o usuário."""
    for marca, frase in _ERROS_DE_REDE:
        if marca.lower() in (mensagem or "").lower():
            return frase
    primeira = (mensagem or "").strip().splitlines()[0] if (mensagem or "").strip() else ""
    return primeira[:200] or "erro desconhecido"


def perfil_em_uso(mensagem: str) -> bool:
    """O Chrome recusa abrir um perfil que outra instância já está usando."""
    m = (mensagem or "").lower()
    return any(s in m for s in ("processsingleton", "singletonlock",
                                "user data directory is already in use",
                                "profile appears to be in use",
                                "existing browser session"))


# --------------------------------------------------------------- localizar
def _primeiro_existente(candidatos) -> str:
    for c in candidatos:
        if c and os.path.exists(c):
            return c
    return ""


def chrome_instalado() -> str:
    if sys.platform == "win32":
        return _primeiro_existente(CANDIDATOS_CHROME) or shutil.which("chrome") or ""
    return (shutil.which("google-chrome") or shutil.which("google-chrome-stable")
            or "")


def edge_instalado() -> str:
    if sys.platform == "win32":
        return _primeiro_existente(CANDIDATOS_EDGE) or shutil.which("msedge") or ""
    return shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable") or ""


def _pastas_do_playwright() -> list[Path]:
    """Onde o Playwright procura os navegadores dele, nesta ordem."""
    pastas = []
    proprio = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if proprio and proprio != "0":
        pastas.append(Path(proprio))
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            pastas.append(Path(local) / "ms-playwright")
    elif sys.platform == "darwin":  # pragma: no cover
        pastas.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    else:
        pastas.append(Path.home() / ".cache" / "ms-playwright")
    return pastas


def chromium_reserva() -> str:
    """A pasta do Chromium do Playwright, se já houver um neste computador
    (o programa não o baixa); '' se não houver."""
    for pasta in _pastas_do_playwright():
        try:
            achados = sorted(p for p in pasta.glob("chromium-*") if p.is_dir())
        except OSError:
            achados = []
        if achados:
            return str(achados[-1])
    return ""


SEM_NAVEGADOR = ("nem o Google Chrome nem o Microsoft Edge foram encontrados neste "
                 "computador. O Edge vem com o Windows 10 e 11: se ele foi removido, "
                 "instale-o de novo (ou instale o Chrome) e tente outra vez.")


def escolher_canais(preferencia: str = "auto", certificado: bool = False,
                    chrome: str | None = None, edge: str | None = None,
                    chromium: str | None = None) -> list[str | None]:
    """A ordem em que os navegadores serão tentados. None = o Chromium do
    Playwright, que só entra (por último) se já estiver neste computador.

    Uma preferência que não está instalada não derruba nada: o programa
    segue para o próximo da fila e registra o porquê. Sem navegador nenhum,
    PortalIndisponivel com o que fazer.
    """
    tem_chrome = bool(chrome if chrome is not None else chrome_instalado())
    tem_edge = bool(edge if edge is not None else edge_instalado())
    tem_chromium = bool(chromium if chromium is not None else chromium_reserva())
    if certificado:
        # O Web Signer mora no perfil do Chrome do usuário: é de lá que se copia.
        if not tem_chrome:
            raise PortalIndisponivel(
                "o login por certificado digital precisa do Google Chrome com a "
                "extensão Web Signer, e o Chrome não foi encontrado neste "
                "computador. Instale o Chrome (e o Web Signer), ou escolha "
                f"“{ENTRAR_MANUALMENTE}” em {AJUSTES_ACESSOS}.")
        return ["chrome"]
    pref = (preferencia or "auto").lower()
    if pref not in ("auto", "chrome", "msedge", "chromium"):
        pref = "auto"
    ordem: list[str | None] = []
    if pref == "chromium" and tem_chromium:
        ordem.append(None)
    if pref == "msedge" and tem_edge:
        ordem.append("msedge")
    if tem_chrome:
        ordem.append("chrome")
    if tem_edge and "msedge" not in ordem:
        ordem.append("msedge")
    if pref != "auto" and (None if pref == "chromium" else pref) not in ordem:
        log.warning("o navegador escolhido (%s) não foi encontrado; uso o próximo disponível.", pref)
    if tem_chromium and None not in ordem:
        ordem.append(None)
    if not ordem:
        raise PortalIndisponivel(SEM_NAVEGADOR)
    return ordem


def nome_do_canal(canal: str | None) -> str:
    """Nome do navegador para mensagens ao usuário."""
    return {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}.get(
        canal or "", "Chromium (reserva do Playwright)")


# ------------------------------------------------------------- certificado
def tem_web_signer(perfil: Path) -> bool:
    return (Path(perfil) / "Default" / "Extensions" / EXT_WEB_SIGNER).exists()


def _perfis_do_chrome(user_data: Path) -> list[Path]:
    """Os perfis do Chrome do usuário, do mais provável ao menos provável."""
    if not user_data.is_dir():
        return []
    ultimo = ""
    try:
        estado = json.loads((user_data / "Local State").read_text(encoding="utf-8"))
        ultimo = (estado.get("profile") or {}).get("last_used") or ""
    except (OSError, ValueError, AttributeError):
        pass
    nomes = []
    for nome in (ultimo, "Default", "Profile 1"):
        if nome and nome not in nomes:
            nomes.append(nome)
    try:
        extras = sorted(p.name for p in user_data.iterdir()
                        if p.is_dir() and p.name.startswith("Profile "))
    except OSError:
        extras = []
    nomes += [n for n in extras if n not in nomes]
    return [user_data / n for n in nomes if (user_data / n).is_dir()]


def preparar_perfil_certificado(destino: Path, user_data: Path | None = None) -> Path:
    """Copia o perfil do Chrome do usuário para o perfil do programa, uma vez.

    O Chrome recusa o modo automatizado na pasta de perfil padrão; por isso
    trabalha-se numa cópia. Prefere-se o perfil que tem o Web Signer (o
    último usado, se for ele). Arquivo travado (Chrome aberto) não aborta a
    cópia: o essencial - a extensão - quase sempre vem, e o resto o Chrome
    refaz.
    """
    destino = Path(destino)
    user_data = Path(user_data or USER_DATA_CHROME)
    if tem_web_signer(destino):
        return destino
    perfis = _perfis_do_chrome(user_data)
    origem = next((p for p in perfis if (p / "Extensions" / EXT_WEB_SIGNER).exists()), None)
    if origem is None and perfis:
        origem = perfis[0]
    destino.mkdir(parents=True, exist_ok=True)
    if origem is None:
        return destino

    log.info("Copiando o perfil '%s' do Chrome para o programa (só desta vez)...", origem.name)
    try:
        shutil.copytree(origem, destino / "Default", dirs_exist_ok=True,
                        ignore=lambda _d, nomes: [n for n in nomes if n in _NAO_COPIAR])
    except shutil.Error as erro:
        falhas = erro.args[0] if erro.args else []
        log.warning("  %d arquivo(s) do perfil não puderam ser copiados (o Chrome "
                    "estava aberto?). Se o login por certificado não funcionar, "
                    "feche o Chrome e tente de novo.", len(falhas) if isinstance(falhas, list) else 1)
    estado = user_data / "Local State"
    if estado.exists():
        try:
            shutil.copy2(estado, destino / "Local State")
        except OSError:
            pass
    return destino


# ------------------------------------------------------------- localizar
_SO_CSS = re.compile(r"^(text=|xpath=|//|id=|role=|internal:)|>>")


def primeiro_visivel(pagina, seletores: list[str], espera_ms: int = 3000):
    """O primeiro seletor da lista (em ordem de preferência) que estiver
    VISÍVEL na tela, ou None.

    Na base, cada seletor era esperado por inteiro, um depois do outro: com
    cinco seletores de 8 s, a tela errada custava 40 s. Aqui espera-se UMA
    vez por qualquer um deles e só depois se escolhe pela ordem.
    """
    seletores = [s for s in (seletores or []) if s and s.strip()]
    if pagina is None or not seletores:
        return None

    def visivel_agora():
        for s in seletores:
            try:
                alvo = pagina.locator(f"{s}:visible" if not _SO_CSS.search(s) else s).first
                if alvo.is_visible():
                    return alvo
            except Exception:
                continue
        return None

    achado = visivel_agora()
    if achado is not None or espera_ms <= 0:
        return achado

    if not any(_SO_CSS.search(s) for s in seletores):
        try:
            unido = ", ".join(f"{s}:visible" for s in seletores)
            pagina.locator(unido).first.wait_for(state="visible", timeout=espera_ms)
        except Exception as erro:
            if "timeout" in type(erro).__name__.lower() or "timeout" in str(erro).lower():
                return None
            # seletor que o motor de CSS não entendeu: cai no modo antigo
        else:
            return visivel_agora()

    for s in seletores:          # modo antigo: um a um
        try:
            alvo = pagina.locator(s).first
            alvo.wait_for(state="visible", timeout=espera_ms)
            return alvo
        except Exception:
            continue
    return None


# --------------------------------------------------------------- navegador
class Navegador:
    """Navegador com sessão persistente. Use como gerenciador de contexto:

        with Navegador(PERFIS / "esaj-TJAL", visivel=False) as nav:
            nav.ir("https://...")
    """

    def __init__(self, perfil: Path, *, visivel: bool = False, canal: str = "auto",
                 espera_s: int = 60, pasta_downloads: Path | None = None,
                 pasta_diagnostico: Path | None = None, certificado: bool = False,
                 salvar_diagnostico: bool = True, executavel: str | Path | None = None):
        self.perfil_base = Path(perfil)
        # O perfil do certificado é uma cópia do Chrome do usuário: fica ao
        # lado, para nunca misturar com o perfil do login por senha.
        self.perfil = (self.perfil_base.with_name(self.perfil_base.name + "-certificado")
                       if certificado else self.perfil_base)
        self.visivel = bool(visivel or certificado)
        self.preferencia = canal or "auto"
        self.espera_s = max(5, int(espera_s or 60))
        self.pasta_downloads = Path(pasta_downloads or (caminhos.TEMP / "downloads"))
        self.pasta_diagnostico = Path(pasta_diagnostico) if pasta_diagnostico else None
        self.certificado = certificado
        self.salvar_diagnostico = salvar_diagnostico
        # Caminho de um navegador Chromium qualquer (Chrome portátil, por
        # exemplo): usado no lugar do Chrome e do Edge.
        self.executavel = Path(executavel) if executavel else None
        self.canal: str | None = None
        self._pw = None
        self._contexto = None
        self._pagina = None
        self._esquecer = False

    # ----------------------------------------------------------- atributos
    @property
    def espera_ms(self) -> int:
        return self.espera_s * 1000

    @property
    def playwright(self):
        """O objeto Playwright, para quem precisar de um canal de rede extra."""
        return self._pw

    @property
    def contexto(self):
        return self._contexto

    @property
    def pagina(self):
        """A aba de trabalho. Se o usuário a fechou, abre outra no lugar."""
        if self._pagina is not None:
            try:
                fechada = self._pagina.is_closed()
            except Exception:
                fechada = True
            if not fechada:
                return self._pagina
        if self._contexto is None:
            return None
        try:
            self._pagina = self._contexto.new_page()
        except Exception as erro:
            raise PortalIndisponivel(
                "a janela do navegador foi fechada durante o trabalho. "
                "Comece o download de novo (os processos já baixados são pulados).") from erro
        return self._pagina

    @pagina.setter
    def pagina(self, valor) -> None:
        self._pagina = valor

    @property
    def nome_navegador(self) -> str:
        return nome_do_canal(self.canal)

    @property
    def arquivo_sessao(self) -> Path:
        return self.perfil_base / "sessao.json"

    # ---------------------------------------------------------------- ciclo
    def abrir(self) -> "Navegador":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as erro:
            raise PortalIndisponivel(
                "o componente de navegação automática (Playwright) não está "
                f"instalado. {sistema.REINSTALAR}") from erro
        if self.executavel is not None and not self.certificado:
            canais: list[str | None] = [None]
        else:
            canais = escolher_canais(self.preferencia, self.certificado)

        try:
            user_data = preparar_perfil_certificado(self.perfil) if self.certificado else None
            self.perfil.mkdir(parents=True, exist_ok=True)
        except OSError as erro:
            raise PortalIndisponivel(
                f"não consegui preparar a pasta do navegador em {self.perfil} "
                f"({erro.strerror or erro}). Confira o espaço em disco e as permissões.") from erro
        try:
            self.pasta_downloads.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        try:
            self._pw = sync_playwright().start()
        except Exception as erro:
            raise PortalIndisponivel(
                f"não consegui iniciar o navegador automático ({explicar_erro(str(erro))}). "
                f"{sistema.REINSTALAR}") from erro

        falhas: list[str] = []
        for canal in canais:
            if self._lancar(canal, user_data, falhas):
                self.canal = canal
                break
        else:
            self.fechar()
            detalhe = "; ".join(falhas[-3:])
            raise PortalIndisponivel(
                "não consegui abrir nenhum navegador (nem o Chrome nem o Edge). Feche as "
                "janelas do navegador que tenham travado e tente de novo; se persistir, "
                f"reinicie o computador. Detalhe técnico: {detalhe}")

        if len(canais) > 1 and self.canal != canais[0]:
            log.info("  usando o %s.", self.nome_navegador)
        try:
            self._contexto.set_default_timeout(self.espera_ms)
            self._contexto.set_default_navigation_timeout(self.espera_ms)
            # caixas nativas (alert/confirm) travariam o lote esperando um
            # clique, e podem nascer em qualquer aba - inclusive nas que o
            # portal abre sozinho
            self._contexto.on("page", self._preparar_aba)
            for aba in list(self._contexto.pages):
                self._preparar_aba(aba)
            self._restaurar_sessao()
            self._pagina = (self._contexto.pages[0] if self._contexto.pages
                            else self._contexto.new_page())
        except Exception as erro:
            self.fechar()
            raise PortalIndisponivel(
                f"o navegador abriu, mas não respondeu ({explicar_erro(str(erro))}). "
                "Tente de novo; se persistir, reinicie o computador.") from erro
        return self

    def _lancar(self, canal: str | None, user_data: Path | None, falhas: list[str]) -> bool:
        """Tenta um navegador: invisível e, se não der, com a janela fora da tela."""
        # Cada navegador com a sua pasta: um perfil criado pelo Chrome e
        # aberto pelo Edge (ou vice-versa) pode ser recusado por "versão
        # mais nova". O certificado usa a cópia do Chrome, inteira.
        pasta = user_data or (self.perfil / (canal or "chromium"))
        pasta.mkdir(parents=True, exist_ok=True)
        ignorar = ["--enable-automation"]
        if self.certificado:
            # o Playwright desliga as extensões por padrão, e o Web Signer
            # (que conversa com o token) é uma extensão
            ignorar.append("--disable-extensions")
        modos = ["normal"] if self.visivel else ["normal", "fora-da-tela"]
        for modo in modos:
            args = list(ARGS_PADRAO)
            headless = not self.visivel
            if modo == "fora-da-tela":
                headless = False
                args.append(FORA_DA_TELA)
            extra = {}
            if canal is None and self.executavel is not None:
                extra["executable_path"] = str(self.executavel)
            try:
                self._contexto = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(pasta),
                    channel=canal,
                    headless=headless,
                    accept_downloads=True,
                    downloads_path=str(self.pasta_downloads),
                    args=args,
                    ignore_default_args=ignorar,
                    viewport={"width": 1366, "height": 900},
                    **extra,
                )
                return True
            except Exception as erro:
                msg = str(erro)
                if perfil_em_uso(msg):
                    self.fechar()
                    raise PortalIndisponivel(
                        "o navegador do programa já está aberto em outra janela "
                        "(outro download em andamento?). Feche-a, ou espere o outro "
                        "download terminar, e tente de novo.") from erro
                resumo = msg.strip().splitlines()[0][:160] if msg.strip() else type(erro).__name__
                falhas.append(f"{nome_do_canal(canal)} ({modo}): {resumo}")
                if canal is None and "executable doesn't exist" in msg.lower():
                    # A reserva de outra versão do Playwright: não serve.
                    falhas[-1] = f"{nome_do_canal(canal)}: versão incompatível"
                    return False
                log.warning("  o %s não abriu (%s): %s", nome_do_canal(canal), modo, resumo)
        return False

    def fechar(self) -> None:
        if self._contexto is not None:
            self._guardar_sessao()
            try:
                self._contexto.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._contexto = None
        self._pw = None
        self._pagina = None

    def __enter__(self) -> "Navegador":
        return self.abrir()

    def __exit__(self, *_exc) -> bool:
        self.fechar()
        return False

    @staticmethod
    def _preparar_aba(aba) -> None:
        def dispensar(dialogo):
            try:
                # 'beforeunload' dispensado cancelaria a navegação
                if getattr(dialogo, "type", "") == "beforeunload":
                    dialogo.accept()
                else:
                    log.info("  o portal mostrou um aviso: %s",
                             (getattr(dialogo, "message", "") or "")[:200])
                    dialogo.dismiss()
            except Exception:
                pass
        try:
            aba.on("dialog", dispensar)
        except Exception:
            pass

    # ------------------------------------------------- sessão entre execuções
    def _restaurar_sessao(self) -> None:
        alvo = self.arquivo_sessao
        try:
            if not alvo.exists():
                return
            if time.time() - alvo.stat().st_mtime > SESSAO_VALIDA_S:
                return
            dados = json.loads(alvo.read_text(encoding="utf-8"))
            cookies = dados.get("cookies") or []
            if cookies:
                self._contexto.add_cookies(cookies)
                log.debug("  %d cookie(s) da sessão anterior restaurados.", len(cookies))
        except Exception as erro:
            log.debug("  não restaurei a sessão anterior: %s", str(erro)[:120])

    def _guardar_sessao(self) -> None:
        if self._contexto is None or self._esquecer:
            return
        try:
            estado = self._contexto.storage_state()
            self.arquivo_sessao.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.arquivo_sessao.with_name(self.arquivo_sessao.name + ".tmp")
            tmp.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.arquivo_sessao)
        except Exception as erro:
            log.debug("  não guardei a sessão: %s", str(erro)[:120])

    def esquecer_sessao(self) -> None:
        """Apaga a sessão guardada (ex.: depois de um login recusado).

        E não a grava de novo ao fechar: sem isso, o fechar() logo em
        seguida regravava os mesmos cookies, e o apagar não valia nada.
        """
        self._esquecer = True
        try:
            self.arquivo_sessao.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------ navegação
    def ir(self, url: str, pagina=None, espera: str = "domcontentloaded",
           timeout_ms: int | None = None):
        pagina = pagina or self.pagina
        try:
            return pagina.goto(url, wait_until=espera, timeout=timeout_ms or self.espera_ms)
        except Exception as erro:
            raise PortalIndisponivel(
                f"não consegui abrir {url}: {explicar_erro(str(erro))}") from erro

    def abas(self) -> list:
        """As abas abertas, com a de trabalho na frente."""
        try:
            abas = [a for a in self._contexto.pages if not a.is_closed()]
        except Exception:
            abas = []
        atual = self._pagina
        if atual is not None:
            if atual in abas:
                abas.remove(atual)
            try:
                if not atual.is_closed():
                    abas.insert(0, atual)
            except Exception:
                pass
        return abas or ([atual] if atual is not None else [])

    @contextmanager
    def nova_aba(self):
        """Abre uma aba extra e garante o fechamento no fim."""
        aba = self._contexto.new_page()
        try:
            yield aba
        finally:
            try:
                aba.close()
            except Exception:
                pass

    def esperar(self, ms: int) -> None:
        try:
            self.pagina.wait_for_timeout(ms)
        except Exception:
            time.sleep(ms / 1000)

    # ---------------------------------------------------------- diagnóstico
    def diagnosticar(self, rotulo: str, pagina=None) -> Path | None:
        """Salva captura e HTML da tela, para descobrir o que mudou no portal.

        Fica em Logs\\diagnostico, FORA do Acervo: o HTML pode conter dados
        de processo sigiloso e não deve ir para a pasta compartilhada.
        """
        if not self.salvar_diagnostico or self.pasta_diagnostico is None:
            return None
        try:
            pagina = pagina or self._pagina
        except Exception:
            pagina = None
        if pagina is None:
            return None
        destino = self.pasta_diagnostico
        try:
            destino.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        rotulo = re.sub(r"[^\w.-]+", "_", rotulo or "tela")[:80]
        marca = f"{datetime.now():%Y-%m-%d_%H%M%S}-{rotulo}"
        try:
            pagina.screenshot(path=str(destino / f"{marca}.png"), full_page=True, timeout=15000)
        except Exception:
            pass
        try:
            html = pagina.content()
            tmp = destino / f"{marca}.html.tmp"
            tmp.write_text(html, encoding="utf-8", errors="replace")
            os.replace(tmp, destino / f"{marca}.html")
        except Exception:
            pass
        _podar(destino)
        log.warning("Diagnóstico salvo em %s", destino / f"{marca}.png")
        return destino / f"{marca}.png"


def _podar(pasta: Path, manter: int = MANTER_DIAGNOSTICOS) -> None:
    """Não deixa a pasta de diagnóstico crescer sem fim."""
    try:
        arquivos = sorted((p for p in pasta.iterdir() if p.is_file()),
                          key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for velho in arquivos[:-manter] if len(arquivos) > manter else []:
        try:
            velho.unlink()
        except OSError:
            pass
