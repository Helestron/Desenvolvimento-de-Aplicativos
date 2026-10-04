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
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("aplicativo.integridade")

NO_WINDOWS = sys.platform == "win32"

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


# ============================================================ o instalador
# O nome que a construção publica (e o que o navegador acrescenta quando o
# arquivo é baixado de novo: "Helestron-Setup-1.0.0 (1).exe"). Outro nome
# qualquer - "Helestron-Setup (atualização).exe", vindo de um anexo ou de um
# site - nunca é aberto pelo botão Reparar.
PADRAO_INSTALADOR = re.compile(r"^Helestron-Setup-(\d+)\.(\d+)\.(\d+)(?: \(\d+\))?\.exe$",
                               re.IGNORECASE)
# O cabeçalho que todo instalador NSIS tem (firstheader: flags, 0xDEADBEEF,
# "NullsoftInst"), num limite de 512 bytes logo depois do executável inicial.
ASSINATURA_NSIS = b"\xef\xbe\xad\xdeNullsoftInst"
# A descrição que o helestron.nsi grava nas propriedades do Setup.exe.
DESCRICAO_INSTALADOR = "Instalador do Helestron".encode("utf-16-le")
LIMITE_CABECALHO = 4 * 1024 * 1024
# FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
_FOLDERID_DOWNLOADS = (0x374DE290, 0x123F, 0x4565, (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))


def _versao_tupla(texto: str) -> tuple[int, ...]:
    partes = []
    for parte in str(texto or "").split("."):
        if not parte.isdigit():
            break
        partes.append(int(parte))
    return tuple(partes)


def versao_do_instalador(arquivo: Path) -> tuple[int, int, int] | None:
    """(1, 0, 0) de "Helestron-Setup-1.0.0.exe"; None se o nome não for o publicado."""
    achado = PADRAO_INSTALADOR.match(Path(arquivo).name)
    if not achado:
        return None
    return int(achado.group(1)), int(achado.group(2)), int(achado.group(3))


def _downloads_windows() -> Path | None:  # pragma: no cover - só no Windows
    """A pasta Downloads de verdade (SHGetKnownFolderPath): com o
    redirecionamento de pastas da TI (GPO) ou a pasta movida pelo usuário,
    ela não é %USERPROFILE%\\Downloads - e é onde o navegador salva."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    d1, d2, d3, d4 = _FOLDERID_DOWNLOADS
    guid = GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))
    # Protótipo próprio (e não argtypes na função compartilhada do windll).
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


def pastas_downloads() -> list[Path]:
    """A pasta Downloads registrada no Windows e, de reserva, a de sempre
    (%USERPROFILE%\\Downloads), sem repetir."""
    pastas: list[Path] = []
    if NO_WINDOWS:
        try:
            achada = _downloads_windows()
        except Exception as erro:                    # sem a API: só a de sempre
            log.debug("pasta Downloads não lida pelo Windows: %s", erro)
            achada = None
        if achada is not None:
            pastas.append(achada)
    reserva = Path.home() / "Downloads"
    if not any(_mesma_pasta(reserva, p) for p in pastas):
        pastas.append(reserva)
    return pastas


def _mesma_pasta(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (OSError, ValueError):
        return False


def conferir_instalador(arquivo: Path) -> str | None:
    """None se o arquivo é um instalador do Helestron; senão, o motivo.

    Confere o nome publicado, o cabeçalho de instalador NSIS, a descrição
    "Instalador do Helestron" nas propriedades do arquivo e, se houver o
    .sha256 ao lado (o que a página de versões publica), o código de
    conferência. Não é uma assinatura digital (o instalador não é assinado):
    é o bastante para o botão Reparar não abrir um executável qualquer que
    tenha caído na pasta Downloads.
    """
    arquivo = Path(arquivo)
    if versao_do_instalador(arquivo) is None:
        return "o nome não é o do instalador publicado (Helestron-Setup-versão.exe)"
    try:
        with open(arquivo, "rb") as f:
            inicio = f.read(LIMITE_CABECALHO)
    except OSError as erro:
        return f"não pôde ser lido ({erro})"
    if not inicio.startswith(b"MZ"):
        return "não é um programa do Windows"
    posicao, achou = inicio.find(ASSINATURA_NSIS), False
    while posicao >= 0:
        if (posicao - 4) % 512 == 0:
            achou = True
            break
        posicao = inicio.find(ASSINATURA_NSIS, posicao + 1)
    if not achou:
        return "não é um instalador (falta o cabeçalho do instalador)"
    if DESCRICAO_INSTALADOR not in inicio:
        return "não é o instalador do Helestron"
    soma = arquivo.with_name(arquivo.name + ".sha256")
    if soma.is_file():
        try:
            esperado = (soma.read_text(encoding="utf-8", errors="replace").split() or [""])[0].lower()
            obtido = sha256_de(arquivo)
        except OSError as erro:
            return f"não pôde ser conferido ({erro})"
        if esperado and obtido != esperado:
            return ("está incompleto ou corrompido (o código de conferência do arquivo .sha256 "
                    "não bate)")
    return None


def procurar_instalador(conferir: bool = True) -> Path | None:
    """O Helestron-Setup que estiver no computador, para o botão Reparar.

    O instalador não deixa cópia de si (seriam centenas de MB a mais): quem
    o baixou costuma tê-lo em Downloads - a pasta Downloads registrada no
    Windows, que a TI pode ter redirecionado. Procura ali e, por garantia,
    em LOCAL e na pasta do programa (onde a TI pode tê-lo deixado). Só vale
    o nome publicado, e (conferir=True) um instalador do Helestron de
    verdade; nunca uma versão mais velha que a instalada. A versão mais
    nova primeiro; na mesma versão, o arquivo mais recente.
    """
    candidatos: list[Path] = []
    pastas: list[Path] = []
    try:
        from ..nucleo import caminhos

        pastas.append(Path(caminhos.LOCAL))
    except Exception:
        pass
    instalada = pasta_instalada()
    if instalada is not None:
        pastas.append(instalada)
    pastas += pastas_downloads()
    minima: tuple[int, ...] = ()
    if instalada is not None:
        try:
            minima = _versao_tupla(ler_manifesto(instalada)[0])
        except ValueError:
            minima = ()
    for pasta in pastas:
        try:
            achados = [p for p in pasta.glob("Helestron-Setup*.exe") if p.is_file()]
        except OSError:
            continue
        for p in achados:
            versao = versao_do_instalador(p)
            if versao is None or (minima and versao < minima[:3]):
                continue
            if any(_mesma_pasta(p, c) for c in candidatos):
                continue
            candidatos.append(p)

    def chave(p: Path):
        try:
            quando = p.stat().st_mtime
        except OSError:
            quando = 0
        return versao_do_instalador(p) or (0, 0, 0), quando

    candidatos.sort(key=chave, reverse=True)
    for p in candidatos:
        if not conferir:
            return p
        motivo = conferir_instalador(p)
        if motivo is None:
            return p
        log.warning("%s não serve para reparar a instalação: %s", p, motivo)
    return None
