"""Onde cada coisa mora.

O programa é portátil: tudo o que ele instala fica dentro da própria pasta
(runtime\\), e o Windows não é alterado. A exceção, de propósito, são os
dados que não podem viajar junto com a pasta nem ser sincronizados pelo
OneDrive - os perfis do navegador (milhares de arquivos reescritos o tempo
todo) e as senhas cifradas -, que ficam em %LOCALAPPDATA%\\AssessorIntegrado.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RUNTIME = RAIZ / "runtime"
PYTHON_DIR = RUNTIME / "python"
MODELOS = RUNTIME / "modelos"
NAVEGADORES = RUNTIME / "navegador"          # PLAYWRIGHT_BROWSERS_PATH (reserva)
DADOS = Path(__file__).resolve().parents[1] / "dados"
LOGS = RAIZ / "Logs"
ARQUIVO_CONFIG = RAIZ / "config.ini"
RECURSOS = RAIZ / "app" / "interface" / "recursos"


def _pasta_local() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AssessorIntegrado"
    return Path.home() / ".assessor-integrado"


LOCAL = _pasta_local()
PERFIS = LOCAL / "perfis"                    # um perfil de navegador por portal
ARQUIVO_SENHAS = LOCAL / "credenciais.json"  # cifrado pela DPAPI
TEMP = LOCAL / "temp"


def resolver(valor: str | os.PathLike | None, padrao: str) -> Path:
    """Caminho do ini: relativo à pasta do programa, ou absoluto."""
    texto = os.path.expandvars(str(valor or "").strip()) or padrao
    p = Path(texto).expanduser()
    return p if p.is_absolute() else (RAIZ / p)


def python_exe(janela: bool = False) -> Path:
    """O Python do runtime (pythonw = sem console); o atual fora dele."""
    nome = "pythonw.exe" if janela else "python.exe"
    candidato = PYTHON_DIR / nome
    if candidato.exists():
        return candidato
    return Path(sys.executable)


def dentro_do_onedrive(p: Path) -> bool:
    """A pasta está sob o OneDrive? A sincronização corrompe arquivo em uso."""
    texto = str(p.resolve()).lower()
    for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        raiz = os.environ.get(var)
        if raiz and texto.startswith(str(Path(raiz).resolve()).lower()):
            return True
    return "\\onedrive" in texto or "/onedrive" in texto
