"""Onde cada coisa mora.

Três lugares, cada um com uma regra:

* a pasta do PROGRAMA (INSTALACAO): no Windows, %LOCALAPPDATA%\\Programs\\
  Helestron, a própria pasta do Python embutido (sys.prefix), com o pacote
  em Lib\\site-packages\\helestron e o modelo de transcrição em modelos\\.
  O instalador a substitui inteira a cada atualização: nada do usuário pode
  morar ali (a versão anterior guardava config.ini, Logs e runtime dentro
  dela, e uma reinstalação levava tudo junto);
* os dados LOCAIS do programa (LOCAL): %LOCALAPPDATA%\\Helestron - a
  configuração, os registros, os perfis do navegador (milhares de arquivos
  reescritos o tempo todo), as senhas cifradas, a pauta, os modelos baixados
  depois. Fica fora do OneDrive e fora do acervo compartilhado com a IA;
* os documentos do USUÁRIO (BASE_USUARIO): Documentos\\Helestron, com o
  Acervo (que vai para a IA), os Sigilosos e a Pauta exportada (que não vão).
  Se a pasta Documentos estiver dentro do OneDrive (redirecionamento de
  pastas conhecidas), a base passa a ser %USERPROFILE%\\Helestron: a
  sincronização trava arquivo em uso (lição do Assessor SAJ).

Os testes isolam tudo com as variáveis HELESTRON_LOCAL e HELESTRON_DADOS
(lidas na importação) ou com mock.patch nestas constantes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACOTE = Path(__file__).resolve().parents[1]                 # .../helestron
# A instalação tem um manifesto.json (versão e SHA-256 de cada arquivo) na
# pasta do Python; no repositório, não.
INSTALADO = (Path(sys.prefix) / "manifesto.json").exists()
INSTALACAO = Path(sys.prefix) if INSTALADO else PACOTE.parent  # pasta do programa (ou o repositório)
DADOS = PACOTE / "dados"
RECURSOS = PACOTE / "recursos"
WEB = PACOTE / "web"
MODELOS_EMBUTIDOS = INSTALACAO / "modelos"                     # vêm no instalador (só leitura)


def _pasta_local() -> Path:
    proprio = os.environ.get("HELESTRON_LOCAL", "").strip()
    if proprio:
        return Path(os.path.expandvars(proprio)).expanduser()
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if base:
        return Path(base) / "Helestron"
    return Path.home() / ".helestron"        # fora do Windows


LOCAL = _pasta_local()
ARQUIVO_CONFIG = LOCAL / "config.ini"
LOGS = LOCAL / "Logs"
PERFIS = LOCAL / "perfis"                    # um perfil de navegador por portal
ARQUIVO_SENHAS = LOCAL / "credenciais.json"  # cifrado pela DPAPI
TEMP = LOCAL / "temp"
MODELOS = LOCAL / "modelos"                  # modelos baixados depois da instalação
ARQUIVO_PAUTA = LOCAL / "pauta.sqlite3"
ARQUIVO_INSTANCIA = LOCAL / "instancia.json"


def dentro_do_onedrive(p: Path) -> bool:
    """A pasta está sob o OneDrive? A sincronização corrompe arquivo em uso."""
    try:
        texto = str(Path(p).resolve()).lower()
    except (OSError, RuntimeError):
        texto = str(p).lower()
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        raiz = os.environ.get(var)
        if raiz:
            try:
                prefixo = str(Path(raiz).resolve()).lower()
            except (OSError, RuntimeError):
                prefixo = raiz.lower()
            if texto == prefixo or texto.startswith(prefixo.rstrip("\\/") + os.sep):
                return True
    return "\\onedrive" in texto or "/onedrive" in texto


def _documentos_windows() -> Path | None:  # pragma: no cover - só no Windows
    """A pasta Documentos de verdade (SHGetKnownFolderPath): com o
    redirecionamento do OneDrive ou da TI, ela não é %USERPROFILE%\\Documents."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
    guid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
    # Protótipo próprio (e não argtypes na função compartilhada do windll):
    # outra biblioteca que declare a mesma função de outro jeito não quebra.
    prototipo = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.POINTER(GUID), wintypes.DWORD,
                                   wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p))
    pedir = prototipo(("SHGetKnownFolderPath", ctypes.windll.shell32))
    saida = ctypes.c_void_p()
    resultado = pedir(ctypes.byref(guid), 0, None, ctypes.byref(saida))
    try:
        if resultado != 0 or not saida.value:
            return None
        texto = ctypes.wstring_at(saida.value)
        return Path(texto) if texto else None
    finally:
        # A memória é liberada mesmo quando a chamada falha (documentação da API).
        ctypes.windll.ole32.CoTaskMemFree(saida)


def pasta_documentos() -> Path:
    if sys.platform == "win32":
        try:
            achada = _documentos_windows()
        except Exception:  # pragma: no cover - sem a API, o caminho de sempre
            achada = None
        if achada is not None:
            return achada
        perfil = os.environ.get("USERPROFILE")
        if perfil:
            return Path(perfil) / "Documents"
    return Path.home() / "Documents"


def _base_usuario() -> Path:
    propria = os.environ.get("HELESTRON_DADOS", "").strip()
    if propria:
        return Path(os.path.expandvars(propria)).expanduser()
    documentos = pasta_documentos()
    if dentro_do_onedrive(documentos):
        perfil = os.environ.get("USERPROFILE")
        return (Path(perfil) if perfil else Path.home()) / "Helestron"
    return documentos / "Helestron"


BASE_USUARIO = _base_usuario()


def resolver(valor: str | os.PathLike | None, padrao: str, base: Path | None = None) -> Path:
    """Caminho do config.ini: absoluto, ou relativo à base do usuário
    (Documentos\\Helestron). Aceita %VARIAVEIS% do Windows e ~."""
    texto = os.path.expandvars(str(valor or "").strip().strip('"')) or padrao
    p = Path(texto).expanduser()
    return p if p.is_absolute() else (Path(base if base is not None else BASE_USUARIO) / p)


def python_exe(janela: bool = False) -> Path:
    """O Python do programa: python.exe (com console) ou pythonw.exe (sem).

    Na instalação, os da pasta do programa; fora dela (desenvolvimento), o
    par do Python que está rodando, ou ele mesmo.
    """
    nome = "pythonw.exe" if janela else "python.exe"
    pastas = ([INSTALACAO] if INSTALADO else []) + [Path(sys.executable).parent]
    for pasta in pastas:
        candidato = pasta / nome
        if candidato.is_file():
            return candidato
    return Path(sys.executable)
