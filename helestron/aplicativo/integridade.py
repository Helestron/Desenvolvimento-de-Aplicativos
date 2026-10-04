"""Integridade da instalação: os arquivos do programa estão todos lá?

A causa do "No module named 'app.interface.pagina_config'" da versão
anterior foi um arquivo do programa que sumiu depois da instalação
(antivírus que põe em quarentena um arquivo que lida com senhas, extração
interrompida). Aqui o instalador grava o manifesto.json - a versão e, de
cada arquivo, o tamanho e o SHA-256 - e o programa o confere:

  * ao abrir (conferir_rapido): só existência e tamanho do pacote
    helestron e do núcleo do Python (python312.dll, DLLs, biblioteca
    padrão). É uma chamada de stat por arquivo: leva uma fração de segundo,
    e o que falta vira a tela de erro própria, com o arquivo que falta e o
    botão Reparar - em vez de um erro de importação no meio do uso;
  * na verificação (conferir_completo, python -m helestron
    --verificar-instalacao, que o instalador roda ao final): o hash de
    todos os arquivos.

Fora da instalação (rodando do repositório) não há manifesto, e nada é
conferido. Só biblioteca padrão aqui: este módulo tem de funcionar com a
instalação quebrada.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("aplicativo.integridade")

NOME_MANIFESTO = "manifesto.json"
AUSENTE, TAMANHO, CONTEUDO, MANIFESTO = "ausente", "tamanho", "conteudo", "manifesto"
MOTIVOS = {
    AUSENTE: "não está na pasta do programa",
    TAMANHO: "está com o tamanho errado (incompleto ou alterado)",
    CONTEUDO: "está com o conteúdo diferente do instalado",
    MANIFESTO: "não pôde ser lido",
}


@dataclass
class Problema:
    arquivo: str          # relativo à pasta do programa, com barras "/"
    motivo: str           # ausente | tamanho | conteudo | manifesto
    detalhe: str = ""

    @property
    def frase(self) -> str:
        texto = f"{self.arquivo.replace('/', chr(92))} {MOTIVOS.get(self.motivo, self.motivo)}"
        return texto + (f" ({self.detalhe})" if self.detalhe else "")

    def como_dict(self) -> dict:
        return {"arquivo": self.arquivo, "motivo": self.motivo, "detalhe": self.detalhe,
                "frase": self.frase}


@dataclass
class Entrada:
    caminho: str          # relativo, com "/"
    tamanho: int | None
    sha256: str


def pasta_instalada() -> Path | None:
    """A pasta do programa instalado, ou None fora da instalação."""
    try:
        from ..nucleo import caminhos

        if hasattr(caminhos, "INSTALADO"):
            return Path(caminhos.INSTALACAO) if caminhos.INSTALADO else None
    except Exception:                          # caminhos quebrado: decide pelo prefixo
        pass
    prefixo = Path(sys.prefix)
    return prefixo if (prefixo / NOME_MANIFESTO).is_file() else None


def ler_manifesto(pasta: Path) -> tuple[str, list[Entrada]]:
    """(versão, entradas) do manifesto.json da pasta.

    Aceita os formatos que o construtor pode gravar: {"arquivos": {caminho:
    {"tamanho", "sha256"}}} ou {"arquivos": [{"caminho", "tamanho",
    "sha256"}]} (também "bytes"/"size" e "hash"). Levanta ValueError se o
    arquivo estiver ilegível.
    """
    arquivo = Path(pasta) / NOME_MANIFESTO
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as erro:
        raise ValueError(f"{NOME_MANIFESTO} ilegível: {erro}") from erro
    if not isinstance(dados, dict):
        raise ValueError(f"{NOME_MANIFESTO} não é um objeto JSON")
    versao = str(dados.get("versao") or dados.get("version") or "")
    bruto = dados.get("arquivos", dados.get("files"))
    if isinstance(bruto, dict):
        itens = [(k, v) for k, v in bruto.items()]
    elif isinstance(bruto, list):
        itens = [(x.get("caminho") or x.get("arquivo") or x.get("path") or "", x)
                 for x in bruto if isinstance(x, dict)]
    else:
        raise ValueError(f"{NOME_MANIFESTO} sem a lista de arquivos")
    entradas = []
    for caminho, info in itens:
        caminho = str(caminho or "").replace("\\", "/").lstrip("/")
        if not caminho or caminho == NOME_MANIFESTO or ".." in caminho.split("/"):
            continue
        if isinstance(info, dict):
            tamanho = info.get("tamanho", info.get("bytes", info.get("size")))
            sha = info.get("sha256", info.get("hash", ""))
        else:                                   # só o hash
            tamanho, sha = None, info
        try:
            tamanho = int(tamanho) if tamanho is not None else None
        except (TypeError, ValueError):
            tamanho = None
        entradas.append(Entrada(caminho, tamanho, str(sha or "").lower()))
    return versao, entradas


def essencial(caminho: str) -> bool:
    """Arquivo conferido na abertura: o pacote helestron e o núcleo do Python.

    Núcleo = o que fica na raiz da pasta (python312.dll, python.exe, o
    lançador, as DLLs do Visual C++), a pasta DLLs e a biblioteca padrão
    (Lib, sem site-packages). Das bibliotecas de terceiros, só o pacote do
    programa: elas são conferidas inteiras na verificação.
    """
    c = caminho.lower()
    if c.startswith("lib/site-packages/"):
        return c.startswith("lib/site-packages/helestron/")
    if "/" not in c:
        return True
    return c.startswith(("dlls/", "lib/"))


def conferir_rapido(pasta: Path | None = None) -> list[Problema]:
    """Existência e tamanho dos arquivos essenciais. [] = tudo certo."""
    pasta = pasta if pasta is not None else pasta_instalada()
    if pasta is None:
        return []
    try:
        _, entradas = ler_manifesto(pasta)
    except ValueError as erro:
        return [Problema(NOME_MANIFESTO, MANIFESTO, str(erro))]
    problemas = []
    for e in entradas:
        if not essencial(e.caminho):
            continue
        p = _conferir_tamanho(Path(pasta), e)
        if p is not None:
            problemas.append(p)
    if problemas:
        log.error("instalação incompleta: %s", "; ".join(p.frase for p in problemas[:10]))
    return problemas


def _conferir_tamanho(pasta: Path, e: Entrada) -> Problema | None:
    alvo = pasta / Path(*e.caminho.split("/"))
    try:
        tamanho = alvo.stat().st_size
    except OSError:
        return Problema(e.caminho, AUSENTE)
    if not alvo.is_file():
        return Problema(e.caminho, AUSENTE)
    if e.tamanho is not None and tamanho != e.tamanho:
        return Problema(e.caminho, TAMANHO, f"{tamanho} bytes; o esperado é {e.tamanho}")
    return None


def sha256_de(arquivo: Path) -> str:
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def conferir_completo(pasta: Path | None = None,
                      progresso: Callable[[int, int, str], None] | None = None) -> list[Problema]:
    """Existência, tamanho e SHA-256 de TODOS os arquivos do manifesto."""
    pasta = pasta if pasta is not None else pasta_instalada()
    if pasta is None:
        return []
    try:
        _, entradas = ler_manifesto(pasta)
    except ValueError as erro:
        return [Problema(NOME_MANIFESTO, MANIFESTO, str(erro))]
    problemas = []
    total = len(entradas)
    for i, e in enumerate(entradas, 1):
        if progresso is not None and (i == total or i % 200 == 0):
            progresso(i, total, e.caminho)
        p = _conferir_tamanho(Path(pasta), e)
        if p is None and e.sha256:
            try:
                atual = sha256_de(Path(pasta) / Path(*e.caminho.split("/")))
            except OSError as erro:
                p = Problema(e.caminho, AUSENTE, str(erro))
            else:
                if atual != e.sha256:
                    p = Problema(e.caminho, CONTEUDO)
        if p is not None:
            problemas.append(p)
    return problemas


def descrever(problemas: list[Problema], limite: int = 10) -> str:
    """As linhas do relatório e da tela de erro."""
    linhas = [f"•  {p.frase}" for p in problemas[:limite]]
    if len(problemas) > limite:
        resto = len(problemas) - limite
        linhas.append(f"•  … e mais {resto} arquivo{'s' if resto != 1 else ''}")
    return "\n".join(linhas)


def procurar_instalador() -> Path | None:
    """O Helestron-Setup guardado no computador, para o botão Reparar.

    Procura em LOCAL (onde o instalador deixa uma cópia de si, se deixar),
    na pasta do programa e em Downloads - o mais novo primeiro.
    """
    candidatos: list[Path] = []
    pastas: list[Path] = []
    try:
        from ..nucleo import caminhos

        pastas += [Path(caminhos.LOCAL), Path(caminhos.LOCAL) / "instalador"]
    except Exception:
        pass
    instalada = pasta_instalada()
    if instalada is not None:
        pastas.append(instalada)
    pastas.append(Path.home() / "Downloads")
    for pasta in pastas:
        try:
            candidatos += [p for p in pasta.glob("Helestron-Setup*.exe") if p.is_file()]
        except OSError:
            continue
    if not candidatos:
        return None
    candidatos.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return candidatos[0]
