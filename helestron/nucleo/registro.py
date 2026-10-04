"""O registro (log) do programa: arquivo mensal em Logs\\ e ponte para a tela.

Logs\\ fica na pasta de dados do programa (%LOCALAPPDATA%\\Helestron),
fora da pasta instalada e fora do acervo compartilhado com a IA.

Sob o pythonw.exe (a janela sem console), sys.stdout e sys.stderr são None,
e bibliotecas que escrevem barra de progresso (huggingface, tqdm) quebram
ao escrever em None. preparar_saidas() troca os dois por um destino real
antes de qualquer import pesado.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from . import caminhos

RUIDOSOS = ("urllib3", "asyncio", "playwright", "faster_whisper", "huggingface_hub",
            "filelock", "httpx", "httpcore", "PIL", "comtypes", "sherpa_onnx")

# Marca de cada módulo no painel de andamento, quando há mais de uma tarefa.
MARCAS = {"download": "[baixar]", "esaj": "[baixar]", "eproc": "[baixar]",
          "navegador": "[baixar]", "listas": "[baixar]",
          "transcricao": "[transcrever]", "microfone": "[transcrever]",
          "falantes": "[transcrever]", "compartilhar": "[compartilhar]",
          "mcp": "[compartilhar]"}


def preparar_saidas() -> None:
    for nome in ("stdout", "stderr"):
        fluxo = getattr(sys, nome)
        if fluxo is None:
            setattr(sys, nome, open(os.devnull, "w", encoding="utf-8"))
        else:
            try:
                fluxo.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


def configurar(console: bool = True, nivel: int = logging.INFO) -> Path:
    """Liga o log em Logs\\AAAA-MM.log (e no console, se houver)."""
    caminhos.LOGS.mkdir(parents=True, exist_ok=True)
    arquivo = caminhos.LOGS / f"{datetime.now():%Y-%m}.log"
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for h in list(raiz.handlers):
        if getattr(h, "_helestron", False):
            raiz.removeHandler(h)

    disco = logging.FileHandler(arquivo, encoding="utf-8")
    disco.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"))
    disco._helestron = True  # type: ignore[attr-defined]
    raiz.addHandler(disco)

    if console and sys.stdout is not None and getattr(sys.stdout, "isatty", lambda: False)():
        tela = logging.StreamHandler(sys.stdout)
        tela.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        tela._helestron = True  # type: ignore[attr-defined]
        raiz.addHandler(tela)

    for nome in RUIDOSOS:
        logging.getLogger(nome).setLevel(logging.WARNING)
    return arquivo


def marca(nome_logger: str) -> str:
    for parte in nome_logger.split("."):
        if parte in MARCAS:
            return MARCAS[parte]
    return ""
