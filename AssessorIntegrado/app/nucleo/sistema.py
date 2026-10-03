"""Pequenas pontes com o Windows: abrir pasta, abrir arquivo, nome livre.

Tudo aqui tolera rodar fora do Windows (testes), sem efeito colateral.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

NO_WINDOWS = sys.platform == "win32"
SEM_JANELA = 0x08000000 if NO_WINDOWS else 0          # CREATE_NO_WINDOW
NOVO_CONSOLE = 0x00000010 if NO_WINDOWS else 0        # CREATE_NEW_CONSOLE

_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def nome_seguro(texto: str, padrao: str = "arquivo") -> str:
    """Nome de arquivo aceito pelo Windows (sem / \\ : * ? " < > |)."""
    limpo = _PROIBIDOS.sub("_", texto or "").strip(" .")
    return limpo[:150] or padrao


def destino_livre(pasta: Path, nome: str, extensao: str) -> Path:
    """'nome.ext', ou 'nome (2).ext' se já existir: nunca sobrescreve."""
    extensao = extensao if extensao.startswith(".") else "." + extensao
    alvo = pasta / f"{nome}{extensao}"
    n = 2
    while alvo.exists():
        alvo = pasta / f"{nome} ({n}){extensao}"
        n += 1
    return alvo


def abrir_pasta(pasta: Path, selecionar: Path | None = None) -> None:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    if NO_WINDOWS:
        if selecionar is not None and Path(selecionar).exists():
            subprocess.Popen(["explorer", "/select,", str(selecionar)])
        else:
            subprocess.Popen(["explorer", str(pasta)])
    elif sys.platform == "darwin":  # pragma: no cover
        subprocess.Popen(["open", str(pasta)])
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", str(pasta)])


def abrir_arquivo(caminho: Path) -> None:
    if NO_WINDOWS:
        os.startfile(str(caminho))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":  # pragma: no cover
        subprocess.Popen(["open", str(caminho)])
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", str(caminho)])


def abrir_endereco(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def gravar_atomico(destino: Path, dados: bytes) -> None:
    """Grava em .tmp e troca de uma vez: queda no meio não corrompe o anterior."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".parcial")
    tmp.write_bytes(dados)
    os.replace(tmp, destino)


def ambiente_sem_chaves() -> dict[str, str]:
    """Cópia do ambiente sem chave de API.

    Com ANTHROPIC_API_KEY no ambiente, o Claude Code usa a chave em vez da
    conta já logada, e o usuário passa a pagar por uso sem perceber (lição
    do Assessor SAJ). O mesmo vale para a OpenAI no Codex.
    """
    env = dict(os.environ)
    for chave in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        env.pop(chave, None)
    return env


def id_do_aplicativo(nome: str = "AssessorIntegrado.App") -> None:
    """Ícone próprio na barra de tarefas (sem isso, aparece o do Python)."""
    if not NO_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(nome)
    except Exception:
        pass
