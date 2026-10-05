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
* diagnóstico (captura da tela + HTML) em Logs\\diagnostico - menos o da tela
  de processo em segredo de justiça, que traz as partes;
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
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from ..nucleo import caminhos, cofre_senhas, sistema
from ..nucleo.registro import censurar
from .modelos import AJUSTES_ACESSOS, ENTRAR_MANUALMENTE, NavegadorOcupado, PortalIndisponivel

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

# O que vem do perfil do Chrome do usuário para o modo certificado: SÓ o que
# é do Web Signer (lista de permissão). Até a 1.0.1 copiava-se o perfil
# inteiro, menos os caches: vinham as senhas salvas (Login Data), os cookies
# de todos os sites (Cookies, Network\Cookies), o autopreenchimento e os
# tokens da conta Google (Web Data), o histórico, as outras extensões (que
# passavam a ver as telas dos processos sigilosos) e o Local State, com a
# chave que decifra tudo isso nesta conta do Windows.
PASTAS_DA_EXTENSAO = ("Extensions", "Local Extension Settings",
                      "Sync Extension Settings", "Managed Extension Settings")
# Nas preferências, só estes ramos (com o MAC que o Chrome confere):
RAMOS_DA_EXTENSAO = (("extensions", "settings", EXT_WEB_SIGNER),
                     ("extensions", "install_signature"))
ARQUIVOS_DE_PREFERENCIAS = ("Preferences", "Secure Preferences")
VERSAO_PERFIL_CERT = 2
MARCA_PERFIL_CERT = "helestron-perfil.json"
SUFIXO_LIXO = ".apagar-"
_TRAVA_PERFIS = threading.Lock()

# Cookies que a sessão guardada pode levar: os dos portais (todos em .jus.br)
# e os dos endereços do tribunal (o catálogo, ou a correção do usuário).
SUFIXOS_DOS_PORTAIS = ("jus.br",)
FINALIDADE_SESSAO = "sessao/v1"
# perfil_base (texto) -> instante em que o portal foi "esquecido" (Apagar
# acesso, troca de usuário): um navegador aberto ANTES disso não regrava a
# sessão ao fechar, e apaga o próprio perfil.
_ESQUECIDOS: dict[str, float] = {}
VERSAO_SESSAO = 2

SESSAO_VALIDA_S = 12 * 3600
ARGS_PADRAO = ["--disable-blink-features=AutomationControlled",
               "--no-first-run", "--no-default-browser-check",
               "--hide-crash-restore-bubble", "--disable-session-crashed-bubble"]
FORA_DA_TELA = "--window-position=-32000,-32000"
MANTER_DIAGNOSTICOS = 300     # arquivos; os mais antigos saem
AVISO_SEM_DIAGNOSTICO = (
    "A tela deste processo NÃO foi guardada em Logs\\diagnostico: o processo está em segredo "
    "de justiça, e a página traz os dados das partes (o diagnóstico é o que se envia ao "
    "suporte). Para o suporte, use o diagnóstico de um processo público com o mesmo problema.")
# Para as mensagens de erro: onde ver a tela do problema
DICA_DIAGNOSTICO = "veja Logs\\diagnostico"
DICA_SEM_DIAGNOSTICO = ("a tela, de processo em segredo de justiça, não foi guardada nos "
                        "registros")


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
    # a mensagem vai para a tela e para o relatorio.csv do acervo: sem o
    # jsessionid nem o hash de sessão do eProc que a URL do erro carrega
    return censurar(primeira)[:200] or "erro desconhecido"


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


def _ler_json(arquivo: Path) -> dict:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _ramo(dados, chaves):
    for c in chaves:
        dados = dados.get(c) if isinstance(dados, dict) else None
    return dados


def _pendurar(dados: dict, chaves, valor) -> None:
    for c in chaves[:-1]:
        dados = dados.setdefault(c, {})
    dados[chaves[-1]] = valor


def so_da_extensao(prefs: dict) -> dict:
    """De um arquivo de preferências do Chrome, só o registro do Web Signer
    e o MAC dele (protection.macs.<mesmo caminho>), que o Chrome confere -
    sem a conta Google, a página inicial, os sites visitados, a pasta de
    downloads nem as outras extensões."""
    saida: dict = {}
    for chaves in RAMOS_DA_EXTENSAO:
        valor = _ramo(prefs, chaves)
        if valor is None:
            continue
        _pendurar(saida, chaves, valor)
        mac = _ramo(prefs, ("protection", "macs") + chaves)
        if isinstance(mac, str):
            _pendurar(saida, ("protection", "macs") + chaves, mac)
    return saida


def _versao_da_copia(destino: Path) -> int:
    try:
        return int(_ler_json(Path(destino) / MARCA_PERFIL_CERT).get("versao") or 0)
    except (TypeError, ValueError):
        return 0


def copia_antiga(destino: Path) -> bool:
    """A pasta é uma cópia do perfil INTEIRO, das versões até a 1.0.1?"""
    destino = Path(destino)
    if _versao_da_copia(destino) >= VERSAO_PERFIL_CERT:
        return False
    return (destino / "Default").is_dir() or (destino / "Local State").exists()


def perfil_aberto(pasta: Path) -> bool:
    """Há um Chrome usando esta pasta agora? No Windows, o Chrome aberto
    segura o 'lockfile' (o Windows recusa apagá-lo); fora dele, há o
    SingletonLock."""
    pasta = Path(pasta)
    if sys.platform == "win32":  # pragma: no cover - exercitado no CI do Windows
        for p in (pasta, *_subpastas(pasta)):
            try:
                (p / "lockfile").unlink()
            except FileNotFoundError:
                continue
            except OSError:
                return True
        return False
    for p in (pasta, *(q for q in _subpastas(pasta))):
        trava = p / "SingletonLock"
        if trava.is_symlink() or trava.exists():
            return True
    return False


def _subpastas(pasta: Path) -> list[Path]:
    """As pastas de cada navegador (chrome, msedge, chromium) do perfil."""
    try:
        return [p for p in Path(pasta).iterdir() if p.is_dir()]
    except OSError:
        return []


def _apagar_pasta(pasta: Path) -> bool:
    """Tira a pasta do caminho (renomeando: no Windows, falha se houver
    arquivo aberto nela) e a apaga. False: em uso, nada mudou."""
    pasta = Path(pasta)
    if not pasta.exists():
        return True
    if perfil_aberto(pasta):
        return False
    lixo = pasta.with_name(f"{pasta.name}{SUFIXO_LIXO}{os.getpid()}-{time.time_ns()}")
    try:
        pasta.rename(lixo)
    except OSError:
        return False
    shutil.rmtree(lixo, ignore_errors=True)
    return True


def limpar_copia_antiga(destino: Path) -> bool:
    """Apaga a cópia do perfil inteiro do Chrome feita até a 1.0.1 (senhas,
    cookies, autopreenchimento, histórico, Local State). True: não há (mais)
    cópia antiga; False: ela está aberta agora, e fica para a próxima vez."""
    destino = Path(destino)
    if not copia_antiga(destino):
        return True
    if not _apagar_pasta(destino):
        log.warning("A cópia antiga do perfil do Chrome em %s está em uso; apago-a quando "
                    "o navegador do programa fechar.", destino.name)
        return False
    log.info("Apaguei a cópia antiga do perfil do Chrome (%s): ela levava as senhas e os "
             "cookies do Chrome, e o modo certificado só precisa do Web Signer.", destino.name)
    return True


def _copiar_extensao(origem: Path, default: Path, so_codigo: bool = False) -> int:
    """As pastas do Web Signer e as preferências reduzidas a ele. Devolve
    quantos arquivos não puderam ser copiados (Chrome aberto). 'so_codigo'
    (atualização da extensão): os dados dela (LevelDB) já são os do perfil
    do programa e não se misturam com os do Chrome."""
    falhas = 0
    for pasta in PASTAS_DA_EXTENSAO[:1] if so_codigo else PASTAS_DA_EXTENSAO:
        de = origem / pasta / EXT_WEB_SIGNER
        if not de.is_dir():
            continue
        try:
            # LOCK é a trava do LevelDB, presa pelo Chrome aberto; recria-se
            shutil.copytree(de, default / pasta / EXT_WEB_SIGNER, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("LOCK"))
        except shutil.Error as erro:
            lista = erro.args[0] if erro.args else []
            falhas += len(lista) if isinstance(lista, list) else 1
    for nome in ARQUIVOS_DE_PREFERENCIAS:
        reduzidas = so_da_extensao(_ler_json(origem / nome))
        if reduzidas:
            alvo = default / nome
            tmp = alvo.with_name(alvo.name + ".tmp")
            tmp.write_text(json.dumps(reduzidas, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, alvo)
    return falhas


def versao_do_web_signer(default: Path) -> tuple[int, ...]:
    """A versão mais nova do Web Signer numa pasta de perfil ('1.2.3_0' ->
    (1, 2, 3, 0)); () se não houver."""
    try:
        nomes = [p.name for p in (Path(default) / "Extensions" / EXT_WEB_SIGNER).iterdir()
                 if p.is_dir()]
    except OSError:
        return ()
    versoes = [tuple(int(n) for n in re.findall(r"\d+", nome)) for nome in nomes]
    return max((v for v in versoes if v), default=())


def preparar_perfil_certificado(destino: Path, user_data: Path | None = None) -> Path:
    """Prepara o perfil do modo certificado: o Web Signer do Chrome do
    usuário, e mais nada.

    O Chrome recusa o modo automatizado na pasta de perfil padrão; por isso
    trabalha-se noutra pasta, com uma cópia SÓ da extensão (os arquivos dela
    e o registro dela nas preferências). Sem o Web Signer no Chrome, o
    perfil abre limpo, e a tela de login ensina a instalá-lo pela Chrome Web
    Store (fica neste perfil). A cópia antiga, do perfil inteiro, é apagada
    antes.
    """
    destino = Path(destino)
    user_data = Path(user_data or USER_DATA_CHROME)
    with _TRAVA_PERFIS:
        if not limpar_copia_antiga(destino):
            return destino          # aberta: o lançamento acusa "perfil em uso"
        perfis = _perfis_do_chrome(user_data)
        origem = next((p for p in perfis if (p / "Extensions" / EXT_WEB_SIGNER).is_dir()), None)
        if tem_web_signer(destino):
            # O navegador do programa não atualiza extensões (o Playwright
            # liga --disable-background-networking): a atualização vem do
            # Chrome do usuário, quando ele tiver uma versão mais nova.
            if origem is None or (versao_do_web_signer(origem)
                                  <= versao_do_web_signer(destino / "Default")):
                return destino
            log.info("O Web Signer do Chrome foi atualizado; atualizo a cópia do programa.")
            shutil.rmtree(destino / "Default" / "Extensions" / EXT_WEB_SIGNER, ignore_errors=True)
            _copiar_extensao(origem, destino / "Default", so_codigo=True)
            return destino
        (destino / "Default").mkdir(parents=True, exist_ok=True)
        if origem is not None:
            log.info("Copiando o Web Signer do perfil '%s' do Chrome (só a extensão)...",
                     origem.name)
            falhas = _copiar_extensao(origem, destino / "Default")
            if falhas:
                log.warning("  %d arquivo(s) do Web Signer não puderam ser copiados (o Chrome "
                            "estava aberto?). Se o login por certificado não funcionar, feche "
                            "o Chrome e tente de novo.", falhas)
        marca = {"versao": VERSAO_PERFIL_CERT, "origem": origem.name if origem else "",
                 "copiado_em": datetime.now().isoformat(timespec="seconds")}
        (destino / MARCA_PERFIL_CERT).write_text(json.dumps(marca), encoding="utf-8")
    return destino


def limpar_perfis_antigos(pasta: Path | None = None) -> int:
    """Na abertura do programa: as cópias antigas do perfil do Chrome (de
    todos os portais), as sessões guardadas no formato antigo (texto puro,
    com cookies de qualquer site) e os restos de limpezas interrompidas.
    Devolve quantas coisas foram limpas."""
    pasta = Path(pasta or caminhos.PERFIS)
    try:
        itens = list(pasta.iterdir())
    except OSError:
        return 0
    limpos = 0
    with _TRAVA_PERFIS:
        for item in itens:
            if SUFIXO_LIXO in item.name:
                shutil.rmtree(item, ignore_errors=True)
                limpos += 0 if item.exists() else 1
            elif item.name.endswith("-certificado") and copia_antiga(item):
                limpos += 1 if limpar_copia_antiga(item) else 0
            elif (item / "sessao.json").is_file():
                limpos += 1 if migrar_sessao(item / "sessao.json") else 0
    return limpos


# ------------------------------------------------------------ sessão no disco
def cookie_do_portal(cookie: dict, hosts=()) -> bool:
    """O cookie é de um portal (.jus.br, ou um endereço do tribunal)?"""
    dominio = str((cookie or {}).get("domain") or "").lstrip(".").lower()
    if not dominio:
        return False
    if any(dominio == s or dominio.endswith("." + s) for s in SUFIXOS_DOS_PORTAIS):
        return True
    return any(h == dominio or h.endswith("." + dominio) for h in hosts or ())


def gravar_sessao(arquivo: Path, cookies: list[dict], gravado_em: float | None = None,
                  hosts=()) -> None:
    """Cifrada para esta conta do Windows (DPAPI) e só para o dono. 'hosts':
    os do login fora de .jus.br (Keycloak, gov.br), que valem na volta."""
    corpo = json.dumps({"cookies": cookies, "hosts": sorted(set(hosts or ()))},
                       ensure_ascii=False).encode("utf-8")
    envelope = {"versao": VERSAO_SESSAO,
                "gravado_em": time.time() if gravado_em is None else gravado_em,
                "dados": cofre_senhas.cifrar(corpo, FINALIDADE_SESSAO)}
    cofre_senhas.gravar_privado(Path(arquivo), json.dumps(envelope))


def abrir_sessao(arquivo: Path, hosts=(), agora: float | None = None
                 ) -> tuple[list[dict], tuple[str, ...]]:
    """(cookies dos portais, hosts do login) guardados há menos de
    SESSAO_VALIDA_S - ([], ()) se não houver, se venceu ou se não decifra.
    Lê também o formato antigo (texto puro, validade pelo mtime)."""
    arquivo = Path(arquivo)
    agora = time.time() if agora is None else agora
    if not arquivo.is_file():
        return [], ()
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        return [], ()
    salvos: tuple[str, ...] = ()
    if dados.get("versao") == VERSAO_SESSAO:
        gravado = float(dados.get("gravado_em") or 0)
        if not 0 <= agora - gravado <= SESSAO_VALIDA_S:
            return [], ()
        corpo = json.loads(cofre_senhas.decifrar(str(dados.get("dados") or ""),
                                                 FINALIDADE_SESSAO).decode("utf-8"))
        corpo = corpo if isinstance(corpo, dict) else {}
        cookies = corpo.get("cookies")
        salvos = tuple(str(h).lower() for h in corpo.get("hosts") or () if h)
    else:
        if agora - arquivo.stat().st_mtime > SESSAO_VALIDA_S:
            return [], ()
        cookies = dados.get("cookies")
    todos = tuple(hosts or ()) + salvos
    return ([c for c in (cookies or []) if isinstance(c, dict) and cookie_do_portal(c, todos)],
            salvos)


def ler_sessao(arquivo: Path, hosts=(), agora: float | None = None) -> list[dict]:
    return abrir_sessao(arquivo, hosts, agora)[0]


def migrar_sessao(arquivo: Path) -> bool:
    """Regrava no formato novo (cifrado, só .jus.br) a sessão guardada pela
    1.0.1, mantendo a hora em que foi gravada. True se mudou algo."""
    arquivo = Path(arquivo)
    dados = _ler_json(arquivo)
    if dados.get("versao") == VERSAO_SESSAO:
        return False
    try:
        gravado = arquivo.stat().st_mtime
        cookies = ler_sessao(arquivo)
        if cookies:
            gravar_sessao(arquivo, cookies, gravado_em=gravado)
        else:
            arquivo.unlink()
    except (OSError, ValueError):
        try:
            arquivo.unlink()
        except OSError:
            return False
    return True


def pastas_do_portal(portal: str, perfis: Path | None = None) -> list[Path]:
    """As pastas do navegador de um portal ('esaj:TJAL'): a do login por
    senha (com a sessão guardada) e a do certificado."""
    m = re.fullmatch(r"(esaj|eproc):([A-Za-z0-9]{2,12})", (portal or "").strip())
    if not m:
        raise ValueError(f"portal inválido: {portal!r}")
    base = Path(perfis or caminhos.PERFIS)
    nome = f"{m.group(1)}-{m.group(2).upper()}"
    return [base / nome, base / f"{nome}-certificado"]


def esquecer_portal(portal: str, perfis: Path | None = None) -> bool:
    """'Apagar acesso' e troca de usuário: a sessão guardada e os perfis do
    navegador do portal saem - sem isso, a sessão anterior (de outra pessoa,
    talvez) seguia valendo por até 12 horas. False: algum perfil está aberto
    agora (a sessão guardada sai assim mesmo)."""
    tudo = True
    pastas = pastas_do_portal(portal, perfis)
    _ESQUECIDOS[os.path.normcase(str(pastas[0]))] = time.time()
    with _TRAVA_PERFIS:
        for pasta in pastas:
            try:
                (pasta / "sessao.json").unlink()
            except FileNotFoundError:
                pass
            except OSError:
                tudo = False
            if not _apagar_pasta(pasta):
                tudo = False
    return tudo


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
                 salvar_diagnostico: bool = True, executavel: str | Path | None = None,
                 dominios=()):
        self.perfil_base = Path(perfil)
        # Os endereços do tribunal: além de .jus.br, os únicos cujos cookies
        # a sessão guardada leva (e que ficam no navegador do programa).
        self.dominios = tuple(sorted({str(d).lower() for d in dominios or () if d}))
        # e os hosts por onde as abas passaram (CAS, Keycloak, gov.br do login)
        self._hosts_visitados: set[str] = set()
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
        # A tela em curso é de processo em segredo de justiça (o motor e o
        # portal avisam): o diagnóstico dela não é guardado.
        self.sigiloso_em_curso = False
        # Caminho de um navegador Chromium qualquer (Chrome portátil, por
        # exemplo): usado no lugar do Chrome e do Edge.
        self.executavel = Path(executavel) if executavel else None
        self.canal: str | None = None
        self._pw = None
        self._contexto = None
        self._pagina = None
        self._esquecer = False
        self._aberto_em = 0.0

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

        self._aberto_em = time.time()
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
            self._contexto.on("page", self._vigiar_hosts)
            for aba in list(self._contexto.pages):
                self._preparar_aba(aba)
                self._vigiar_hosts(aba)
            self._restaurar_sessao()
            self._higienizar_cookies()
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
                    raise NavegadorOcupado(
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

    def _foi_esquecido(self) -> bool:
        quando = _ESQUECIDOS.get(os.path.normcase(str(self.perfil_base)), 0.0)
        return bool(quando) and quando >= self._aberto_em

    def fechar(self) -> None:
        esquecido = self._foi_esquecido()
        if esquecido:
            self._esquecer = True
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
        if esquecido:
            with _TRAVA_PERFIS:
                for pasta in (self.perfil_base, self.perfil):
                    _apagar_pasta(pasta)

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

    @property
    def hosts_da_sessao(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.dominios) | self._hosts_visitados))

    def _vigiar_hosts(self, aba) -> None:
        """Anota os hosts por onde a PÁGINA passa (não os dos anúncios e
        contadores que ela carrega): o CAS, o Keycloak e o gov.br do login,
        que podem estar fora de .jus.br e do catálogo."""
        def anotar(quadro):
            try:
                if quadro.parent_frame is None:
                    partes = urlsplit(quadro.url or "")
                    if partes.scheme in ("http", "https") and partes.hostname:
                        self._hosts_visitados.add(partes.hostname.lower())
            except Exception:
                pass
        try:
            aba.on("framenavigated", anotar)
        except Exception:
            pass

    # ------------------------------------------------- sessão entre execuções
    def _higienizar_cookies(self) -> None:
        """Tira do navegador do programa os cookies que não são dos portais.

        Até a 1.0.1, a sessão do modo certificado levava os cookies de TODOS
        os sites do Chrome do usuário (Google, e-mail, banco), e o login por
        senha os devolvia ao seu próprio perfil, onde ficavam.
        """
        try:
            hosts = self.hosts_da_sessao
            alheios = sorted({str(c.get("domain") or "") for c in self._contexto.cookies()
                              if not cookie_do_portal(c, hosts)})
            for dominio in alheios:
                self._contexto.clear_cookies(domain=dominio)
            if alheios:
                log.info("  tirei do navegador do programa os cookies de %d site(s) que não "
                         "são dos portais.", len(alheios))
        except Exception as erro:
            log.debug("  higienização dos cookies: %s", type(erro).__name__)

    def _restaurar_sessao(self) -> None:
        try:
            cookies, salvos = abrir_sessao(self.arquivo_sessao, self.dominios)
            self._hosts_visitados.update(salvos)
            if cookies:
                self._contexto.add_cookies(cookies)
                log.debug("  %d cookie(s) da sessão anterior restaurados.", len(cookies))
        except Exception as erro:
            # sem o texto do erro: ele pode trazer o conteúdo do arquivo
            log.debug("  não restaurei a sessão anterior (%s)", type(erro).__name__)

    def _guardar_sessao(self) -> None:
        """Só os cookies dos portais (nada de localStorage, nada de outros
        sites), cifrados pela DPAPI."""
        if self._contexto is None or self._esquecer:
            return
        try:
            estado = self._contexto.storage_state()
            hosts = self.hosts_da_sessao
            cookies = [c for c in (estado.get("cookies") or [])
                       if isinstance(c, dict) and cookie_do_portal(c, hosts)]
            if cookies:
                gravar_sessao(self.arquivo_sessao, cookies,
                              hosts=[h for h in hosts if not cookie_do_portal({"domain": h})])
            else:
                self.arquivo_sessao.unlink(missing_ok=True)
        except Exception as erro:
            log.debug("  não guardei a sessão (%s)", type(erro).__name__)

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

    def web_signer_ativo(self) -> bool:
        """O Web Signer está instalado E ativo neste navegador? Pergunta ao
        próprio Chrome (a página da extensão só abre se ela estiver
        carregada) - a pasta da extensão no perfil não prova nada: sem o
        registro nas preferências, o Chrome a ignora (e apaga)."""
        if self._contexto is None:
            return False
        alvo = f"chrome-extension://{EXT_WEB_SIGNER}/"
        try:
            if any((w.url or "").startswith(alvo) for w in self._contexto.service_workers):
                return True
        except Exception:
            pass
        try:
            with self.nova_aba() as aba:
                resposta = aba.goto(alvo + "manifest.json", wait_until="commit", timeout=5000)
                return bool(resposta is not None and resposta.ok)
        except Exception:
            return False

    # ------------------------------------------------------------ navegação
    def ir(self, url: str, pagina=None, espera: str = "domcontentloaded",
           timeout_ms: int | None = None):
        pagina = pagina or self.pagina
        try:
            return pagina.goto(url, wait_until=espera, timeout=timeout_ms or self.espera_ms)
        except Exception as erro:
            raise PortalIndisponivel(
                f"não consegui abrir {censurar(url)}: {explicar_erro(str(erro))}") from erro

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

        Fica em Logs\\diagnostico, FORA do Acervo. A tela de processo em
        segredo de justiça (sigiloso_em_curso) não é guardada: a página traz
        os nomes das partes, e o diagnóstico é o que o manual manda enviar ao
        suporte. O registro diz por quê.
        """
        if not self.salvar_diagnostico or self.pasta_diagnostico is None:
            return None
        if getattr(self, "sigiloso_em_curso", False):
            log.warning(AVISO_SEM_DIAGNOSTICO)
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


def diagnosticar_processo(nav, rotulo: str, sigiloso: bool) -> Path | None:
    """O diagnóstico da tela de um processo: o de processo em segredo de
    justiça não é guardado (a página traz as partes), e o registro diz por
    quê. Devolve onde ficou a captura (None: não guardada)."""
    if sigiloso or getattr(nav, "sigiloso_em_curso", False):
        if getattr(nav, "salvar_diagnostico", True):
            log.warning(AVISO_SEM_DIAGNOSTICO)
        return None
    return nav.diagnosticar(rotulo)


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
