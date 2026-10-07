"""Constrói o instalador do Helestron: dist/Helestron-Setup-<versão>.exe (+ .sha256).

    python construir/construir.py (--modelo DIR | --sem-modelo) [--sem-falantes]
                                  [--saida dist] [--cache DIR] [--python-tar ARQ]
    python construir/construir.py --versao     a versão que será construída (o CI
                                               a compara com a tag da publicação)

Roda no Linux (aqui e no CI) e no Windows. Precisa de:
  * Python 3.12 (os .pyc pré-compilados são do 3.12, o Python que vai no
    instalador) com as bibliotecas "installer" e "pillow":
        pip install installer pillow
  * MinGW-w64 (x86_64-w64-mingw32-gcc, -windres, -objdump) e NSIS (makensis):
        sudo apt-get install mingw-w64 nsis
  * o modelo de transcrição faster-whisper-small JÁ EM INT8, em "--modelo
    DIR" (o publicado no Hugging Face é float16, ~484 MB, e o instalador
    passaria de 500 MiB): COMANDOS_CONVERSAO, abaixo, são os comandos do CI
    para convertê-lo. Ou "--sem-modelo" (o programa baixa no primeiro uso).
  * rede: python-build-standalone e os modelos da separação de falantes
    (GitHub) e PyPI. Tudo o que é baixado fica no --cache (padrão:
    construir/cache) e é reaproveitado nas construções seguintes.

As oito etapas (docs/ESPECIFICACAO.md, seção 10):

  1. Python para Windows: python-build-standalone 3.12.10 (SHA-256 conferido).
  2. Rodas win_amd64/cp312 de requisitos-windows.txt, travado com hash: cada
     arquivo baixado tem o SHA-256 conferido contra a lista; pacote que só
     existe em código-fonte e é puro Python (proxy_tools) vira roda aqui.
  3. Instala as rodas na pasta do Python (biblioteca "installer", esquema do
     Windows: Lib\\site-packages, e os dados do msvc-runtime na raiz) e
     copia o pacote helestron INTEIRO para Lib\\site-packages (a pasta toda,
     sem lista de módulos: um módulo novo entra sem mexer aqui).
  4. Enxuga (*.pdb, Lib\\test, idlelib, tkinter, pip, Scripts, include,
     libs) e pré-compila tudo em .pyc (UNCHECKED_HASH: o Python não confere
     a data do .py a cada abertura - e um .py alterado não muda o programa).
  5. Modelo de transcrição faster-whisper-small, em int8, em modelos\\ (de
     --modelo DIR; --sem-modelo: o programa baixa no primeiro uso) e os
     modelos da separação de falantes (GitHub, SHA-256 conferido). A falha
     destes interrompe a construção: o manual promete a separação de vozes
     sem internet. --sem-falantes: um instalador sem eles, de propósito.
  6. Lançadores: Helestron.exe (lancador/helestron.c + .rc: ícone, versão e
     manifesto), compilado com o MinGW e conferido com o objdump; e o
     helestron.cmd, a linha de comando ("python.exe -I -m helestron ..."),
     para quem chama o programa de fora (a skill do Claude, scripts) sem
     depender do PATH.
  7. manifesto.json: versão, os componentes embutidos (modelos) e o SHA-256
     e o tamanho de cada arquivo - o programa o confere ao abrir e o
     instalador, no fim da instalação.
  8. A lista do que esta versão instala (arquivos-instalados.txt, que vai
     para a pasta do programa: a próxima atualização e o desinstalador apagam
     só o que está nela), o script NSIS (instalador/helestron.nsi) e o
     makensis -> dist/Helestron-Setup-<versão>.exe, que não pode passar de
     LIMITE_SETUP (500 MiB, o limite para entrega por anexo).

As imagens da marca (ícone, bitmaps do instalador) são as versionadas em
helestron/recursos, geradas por construir/marca.py; --marca as gera de novo
antes de construir (e elas são geradas se faltarem).
"""

from __future__ import annotations

import argparse
import base64
import compileall
import email.parser
import fnmatch
import hashlib
import json
import os
import platform
import py_compile
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CONSTRUIR = RAIZ / "construir"
PACOTE = RAIZ / "helestron"
RECURSOS = PACOTE / "recursos"
REQUISITOS = CONSTRUIR / "requisitos-windows.txt"
MODELO_NSIS = CONSTRUIR / "instalador" / "helestron.nsi"
LANCADOR = CONSTRUIR / "lancador"
URL_PROJETO = "https://github.com/Helestron/Desenvolvimento-de-Aplicativos"

# python-build-standalone: Python 3.12.10 para Windows x64, "install_only"
# (a pasta do Python inteira: python.exe, python312.dll, DLLs, Lib).
URL_PYTHON = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
              "20250409/cpython-3.12.10%2B20250409-x86_64-pc-windows-msvc-install_only.tar.gz")
SHA256_PYTHON = "5ac66ae49a2104efeba985c1dc1cb40987757ee81cc6c7f218d10b801f3276ed"
VERSAO_PYTHON = (3, 12)

# O modelo da transcrição ao vivo (a pasta tem o nome do repositório: é onde
# helestron/transcricao/modelos.py o procura, em caminhos.MODELOS_EMBUTIDOS).
PASTA_MODELO = "faster-whisper-small"
PADROES_MODELO = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json",
                  "vocabulary.*")
NECESSARIOS_MODELO = ("model.bin", "config.json", "tokenizer.json")
# O programa carrega o modelo sempre em int8 (compute_type="int8"): gravado já
# em int8, o model.bin do whisper-small tem ~250 MB e dá o mesmo resultado. O
# publicado no Hugging Face (Systran/faster-whisper-small) é float16, ~484 MB,
# e com ele o instalador passa de LIMITE_SETUP. A faixa é a que o CI confere.
LIMITES_MODELO = (150_000_000, 350_000_000)
# Os comandos do CI (.github/workflows/helestron.yml, "Modelo de transcrição")
# que convertem o whisper-small oficial para int8 com o mesmo CTranslate2 que
# vai no instalador (4.8.2; o conversor dele pede transformers 4.56 ou mais novo).
COMANDOS_CONVERSAO = (
    "python3.12 -m venv conversao",
    "conversao/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.7.1",
    "conversao/bin/python -m pip install ctranslate2==4.8.2 transformers==4.57.6",
    "conversao/bin/ct2-transformers-converter --model openai/whisper-small "
    "--output_dir faster-whisper-small --copy_files tokenizer.json preprocessor_config.json "
    "--quantization int8",
)
# O Helestron-Setup vai por anexo (e-mail, sistema do tribunal): 500 MiB no máximo.
LIMITE_SETUP = 500 * 1024 * 1024

# A linha de comando do programa para quem o chama de fora (a skill do Claude,
# scripts da TI): o Python desta pasta em modo isolado, sem depender do PATH
# (que o instalador não altera). Só ASCII: o cmd lê o arquivo na página de
# código do console. %~dp0 é a pasta do próprio .cmd, com a barra no fim, e o
# código de saída é o do Python (o último comando do arquivo).
NOME_COMANDO = "helestron.cmd"
CONTEUDO_COMANDO = (
    "@echo off\r\n"
    "rem Helestron - linha de comando: helestron.cmd baixar --lista X.xlsx ...\r\n"
    "rem Roda o Python desta pasta em modo isolado (-I), sem depender do PATH.\r\n"
    "rem Ajuda: helestron.cmd --ajuda\r\n"
    '"%~dp0python.exe" -I -m helestron %*\r\n'
)

# Tags de roda aceitas no Windows 64 bits com CPython 3.12, da mais
# específica para a mais genérica (a ordem do pip): a primeira que houver é
# a escolhida - o sounddevice, por exemplo, tem uma roda "any" sem a
# PortAudio e outra win_amd64 com ela.
PLATAFORMA = "win_amd64"


def tags_compativeis() -> list[tuple[str, str, str]]:
    tags = [("cp312", "cp312", PLATAFORMA)]
    tags += [(f"cp3{m}", "abi3", PLATAFORMA) for m in range(12, 1, -1)]
    tags.append(("cp312", "none", PLATAFORMA))
    genericos = ["py312", "py3"] + [f"py3{m}" for m in range(11, -1, -1)]
    tags += [(py, "none", PLATAFORMA) for py in genericos]
    tags.append(("cp312", "none", "any"))
    tags += [(py, "none", "any") for py in genericos]
    return tags


TAGS = tags_compativeis()
PRIORIDADE = {t: i for i, t in enumerate(TAGS)}

# O que sai da pasta do Python (etapa 4): nada disso é usado pelo programa.
REMOVER_PASTAS = ("Scripts", "include", "Include", "libs", "tcl", "share", "Lib/test", "Lib/idlelib",
                  "Lib/turtledemo", "Lib/ensurepip", "Lib/tkinter", "Lib/lib2to3/tests",
                  "Lib/site-packages/pip")
REMOVER_ARQUIVOS = ("DLLs/_tkinter.pyd", "DLLs/tcl86t.dll", "DLLs/tk86t.dll", "DLLs/_test*.pyd",
                    "DLLs/_ctypes_test.pyd", "Lib/turtle.py")     # aceitam curinga
REMOVER_PADROES = ("*.pdb",)


class ErroConstrucao(RuntimeError):
    """Falha que interrompe a construção (com a frase para quem roda)."""


def etapa(numero: int, titulo: str) -> None:
    print(f"\n[{numero}/8] {titulo}", flush=True)


def info(texto: str) -> None:
    print(f"      {texto}", flush=True)


# ============================================================= utilidades
def sha256_de(arquivo: Path) -> str:
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def baixar(url: str, destino: Path, sha256: str | None = None, tentativas: int = 4) -> Path:
    """Baixa url em destino (reaproveita o arquivo do cache se o hash bater).

    Grava em .parcial e renomeia só no fim: uma construção interrompida não
    deixa arquivo pela metade no cache.
    """
    destino = Path(destino)
    if destino.is_file() and (sha256 is None or sha256_de(destino) == sha256):
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            pedido = urllib.request.Request(url, headers={"User-Agent": "helestron-construir"})
            with urllib.request.urlopen(pedido, timeout=120) as resposta, open(parcial, "wb") as f:
                shutil.copyfileobj(resposta, f, 1 << 20)
            if sha256 is not None:
                obtido = sha256_de(parcial)
                if obtido != sha256:
                    parcial.unlink(missing_ok=True)
                    raise ErroConstrucao(f"SHA-256 diferente do esperado em {url}: {obtido}")
            os.replace(parcial, destino)
            return destino
        except ErroConstrucao:
            raise
        except (OSError, urllib.error.URLError) as erro:
            ultimo_erro = erro
            parcial.unlink(missing_ok=True)
            if tentativa < tentativas:
                time.sleep(2 * tentativa)
    raise ErroConstrucao(f"não foi possível baixar {url}: {ultimo_erro}")


def ler_json_url(url: str, cache: Path | None = None) -> dict:
    if cache is not None and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    ultimo_erro: Exception | None = None
    for tentativa in range(1, 5):
        try:
            pedido = urllib.request.Request(url, headers={"User-Agent": "helestron-construir",
                                                         "Accept": "application/json"})
            with urllib.request.urlopen(pedido, timeout=60) as resposta:
                dados = json.loads(resposta.read().decode("utf-8"))
            if cache is not None:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(dados), encoding="utf-8")
            return dados
        except (OSError, ValueError, urllib.error.URLError) as erro:
            ultimo_erro = erro
            time.sleep(2 * tentativa)
    raise ErroConstrucao(f"não foi possível ler {url}: {ultimo_erro}")


def versao_do_pacote() -> str:
    """A versão de helestron/__init__.py (lida do texto: importar o pacote
    aqui puxaria as bibliotecas do motor, que a construção não tem)."""
    texto = (PACOTE / "__init__.py").read_text(encoding="utf-8")
    achado = re.search(r'^__version__\s*=\s*["\']([0-9]+(?:\.[0-9]+){1,3})["\']', texto, re.M)
    if not achado:
        raise ErroConstrucao("helestron/__init__.py sem __version__ no formato 1.2.3")
    return achado.group(1)


def versao_windows(versao: str) -> str:
    """'1.0' -> '1.0.0.0' (as quatro partes que o Windows exige)."""
    partes = [int(p) for p in versao.split(".")]
    return ".".join(str(p) for p in (partes + [0, 0, 0, 0])[:4])


def remover(caminho: Path) -> None:
    if caminho.is_dir() and not caminho.is_symlink():
        shutil.rmtree(caminho)
    elif caminho.exists() or caminho.is_symlink():
        caminho.unlink()


# ============================================================= etapa 1
def extrair_python(tar: Path, destino: Path) -> None:
    """Extrai a pasta "python/" do tar em destino (sem o prefixo)."""
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    with tarfile.open(tar) as arquivo:
        membros = []
        for m in arquivo.getmembers():
            nome = m.name.lstrip("./")
            if not nome.startswith("python/") or nome == "python/":
                continue
            m.name = nome[len("python/"):]
            if m.islnk() and m.linkname.lstrip("./").startswith("python/"):
                m.linkname = m.linkname.lstrip("./")[len("python/"):]
            membros.append(m)
        if not any(m.name == "python.exe" for m in membros):
            raise ErroConstrucao(f"{tar.name} não tem python/python.exe: não é o Python esperado")
        arquivo.extractall(destino, members=membros, filter="data")


# ============================================================= etapa 2
@dataclass
class Requisito:
    nome: str
    versao: str
    hashes: set[str] = field(default_factory=set)


def ler_requisitos(texto: str) -> list[Requisito]:
    """Os pacotes de um requisitos travado (nome==versão com --hash=sha256:...)."""
    requisitos: list[Requisito] = []
    juntas = re.sub(r"\\\s*\n", " ", texto)
    for linha in juntas.splitlines():
        linha = linha.split("#", 1)[0].strip()
        if not linha or linha.startswith("-"):
            continue
        achado = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;]+)", linha)
        if not achado:
            raise ErroConstrucao(f"linha sem versão travada (nome==versão): {linha}")
        hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", linha))
        if not hashes:
            raise ErroConstrucao(f"{achado.group(1)} sem --hash=sha256 (o arquivo tem de ser travado)")
        requisitos.append(Requisito(achado.group(1), achado.group(2), hashes))
    return requisitos


def tags_da_roda(nome_arquivo: str) -> set[tuple[str, str, str]] | None:
    """As tags (python, abi, plataforma) de um nome de roda; None se não for roda."""
    if not nome_arquivo.endswith(".whl"):
        return None
    partes = nome_arquivo[:-4].split("-")
    if len(partes) not in (5, 6):
        return None
    py, abi, plat = partes[-3:]
    return {(i, a, p) for i in py.split(".") for a in abi.split(".") for p in plat.split(".")}


def prioridade_da_roda(nome_arquivo: str) -> int | None:
    """Menor = mais específica para cp312/win_amd64; None = não serve."""
    tags = tags_da_roda(nome_arquivo)
    if not tags:
        return None
    notas = [PRIORIDADE[t] for t in tags if t in PRIORIDADE]
    return min(notas) if notas else None


def eh_codigo_fonte(nome_arquivo: str) -> bool:
    return nome_arquivo.endswith((".tar.gz", ".zip", ".tar.bz2"))


def escolher_arquivo(arquivos: list[dict], hashes: set[str]) -> dict:
    """Entre os arquivos de uma versão no PyPI ({filename, url, digests}),
    a roda mais específica para o Windows cujo SHA-256 está travado; sem
    roda, o código-fonte travado (que será convertido). Levanta ErroConstrucao."""
    travados = [a for a in arquivos if a.get("digests", {}).get("sha256") in hashes]
    rodas = [(prioridade_da_roda(a["filename"]), a) for a in travados]
    rodas = [(p, a) for p, a in rodas if p is not None]
    if rodas:
        return min(rodas, key=lambda par: (par[0], par[1]["filename"]))[1]
    fontes = [a for a in travados if eh_codigo_fonte(a["filename"])]
    if fontes:
        return fontes[0]
    nomes = ", ".join(sorted(a["filename"] for a in arquivos)) or "nenhum"
    raise ErroConstrucao("nenhum arquivo travado serve para Windows 64 bits / Python 3.12 "
                         f"(arquivos publicados: {nomes})")


def nome_normalizado(nome: str) -> str:
    """Nome de distribuição no formato do nome de roda (PEP 427/503)."""
    return re.sub(r"[-_.]+", "_", nome).lower()


def _hash_record(dados: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).rstrip(b"=").decode()


def roda_de_codigo_fonte(sdist: Path, destino: Path) -> Path:
    """Converte o código-fonte de um pacote PURO Python numa roda py3-none-any.

    Sem pip nem setuptools (e sem rodar o setup.py de ninguém): copia os
    pacotes de topo (top_level.txt do egg-info, ou as pastas com
    __init__.py) e escreve METADATA/WHEEL/RECORD. Recusa código-fonte com
    extensão em C (.c, .pyx, ...): esse não é puro Python.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if sdist.name.endswith(".zip"):
            with zipfile.ZipFile(sdist) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(sdist) as arquivo_tar:
                arquivo_tar.extractall(tmp, filter="data")
        pastas = [p for p in tmp.iterdir() if p.is_dir()]
        if len(pastas) != 1:
            raise ErroConstrucao(f"{sdist.name}: esperava uma pasta só dentro do código-fonte")
        base = pastas[0]
        nativos = [p for p in base.rglob("*")
                   if p.suffix.lower() in (".c", ".cc", ".cpp", ".pyx", ".pxd", ".f", ".rs")]
        if nativos:
            raise ErroConstrucao(f"{sdist.name} não é puro Python ({nativos[0].name}); "
                                 "precisa de uma roda pronta para Windows")
        pkg_info = base / "PKG-INFO"
        if not pkg_info.is_file():
            raise ErroConstrucao(f"{sdist.name} sem PKG-INFO")
        meta_texto = pkg_info.read_text(encoding="utf-8")
        meta = email.parser.Parser().parsestr(meta_texto)
        nome, versao = meta["Name"], meta["Version"]
        if not nome or not versao:
            raise ErroConstrucao(f"{sdist.name}: PKG-INFO sem Name/Version")
        topo: list[str] = []
        for egg in base.glob("*.egg-info"):
            arq = egg / "top_level.txt"
            if arq.is_file():
                topo += [x.strip() for x in arq.read_text(encoding="utf-8").splitlines() if x.strip()]
        if not topo:
            topo = sorted(p.name for p in base.iterdir() if (p / "__init__.py").is_file())
        if not topo:
            raise ErroConstrucao(f"{sdist.name}: não achei os pacotes de topo")
        dist = nome_normalizado(nome)
        info_dir = f"{dist}-{versao}.dist-info"
        conteudo: list[tuple[str, bytes]] = []
        for nome_topo in sorted(set(topo)):
            pasta, modulo = base / nome_topo, base / f"{nome_topo}.py"
            if pasta.is_dir():
                for arq in sorted(pasta.rglob("*")):
                    if arq.is_file() and "__pycache__" not in arq.parts and arq.suffix != ".pyc":
                        conteudo.append((arq.relative_to(base).as_posix(), arq.read_bytes()))
            elif modulo.is_file():
                conteudo.append((modulo.name, modulo.read_bytes()))
            else:
                raise ErroConstrucao(f"{sdist.name}: pacote de topo {nome_topo} não encontrado")
        conteudo.append((f"{info_dir}/METADATA", meta_texto.encode("utf-8")))
        conteudo.append((f"{info_dir}/WHEEL", (
            "Wheel-Version: 1.0\nGenerator: helestron-construir\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n").encode()))
        conteudo.append((f"{info_dir}/top_level.txt", ("\n".join(sorted(set(topo))) + "\n").encode()))
        linhas = [f"{caminho},{_hash_record(dados)},{len(dados)}" for caminho, dados in conteudo]
        linhas.append(f"{info_dir}/RECORD,,")
        conteudo.append((f"{info_dir}/RECORD", ("\n".join(linhas) + "\n").encode()))
        destino.mkdir(parents=True, exist_ok=True)
        roda = destino / f"{dist}-{versao}-py3-none-any.whl"
        with zipfile.ZipFile(roda, "w", zipfile.ZIP_DEFLATED) as z:
            for caminho, dados in conteudo:
                item = zipfile.ZipInfo(caminho, date_time=(1980, 1, 1, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = 0o644 << 16
                z.writestr(item, dados)
    return roda


def obter_rodas(requisitos: list[Requisito], cache: Path) -> list[Path]:
    """Baixa (ou acha no cache) a roda de cada requisito, com o hash conferido."""
    rodas = []
    for r in requisitos:
        dados = ler_json_url(f"https://pypi.org/pypi/{r.nome}/{r.versao}/json",
                             cache / "pypi" / f"{nome_normalizado(r.nome)}-{r.versao}.json")
        try:
            escolhido = escolher_arquivo(dados.get("urls", []), r.hashes)
        except ErroConstrucao as erro:
            raise ErroConstrucao(f"{r.nome}=={r.versao}: {erro}") from None
        arquivo = baixar(escolhido["url"], cache / "rodas" / escolhido["filename"],
                         escolhido["digests"]["sha256"])
        if eh_codigo_fonte(arquivo.name):
            roda = roda_de_codigo_fonte(arquivo, cache / "rodas-locais")
            info(f"{r.nome} {r.versao}: roda gerada do código-fonte ({roda.name})")
        else:
            roda = arquivo
        rodas.append(roda)
    return rodas


# ============================================================= etapa 3
def esquema_windows(arvore: Path) -> dict[str, str]:
    """O esquema de instalação do Python do Windows (sysconfig "nt"), com a
    pasta do programa como prefixo. Os dados ("data") vão para a raiz - é o
    que põe as DLLs do msvc-runtime ao lado do python312.dll."""
    return {
        "purelib": str(arvore / "Lib" / "site-packages"),
        "platlib": str(arvore / "Lib" / "site-packages"),
        "headers": str(arvore / "include" / "site"),     # sai na etapa 4
        "scripts": str(arvore / "Scripts"),
        "data": str(arvore),
    }


def instalar_rodas(rodas: list[Path], arvore: Path) -> None:
    try:
        from installer import install
        from installer.destinations import SchemeDictionaryDestination
        from installer.sources import WheelFile
    except ImportError:
        raise ErroConstrucao("falta a biblioteca 'installer' no Python da construção: "
                             "pip install installer") from None
    destino = SchemeDictionaryDestination(
        esquema_windows(arvore), interpreter=str(arvore / "python.exe"),
        script_kind="win-amd64", hash_algorithm="sha256", overwrite_existing=True)
    for roda in rodas:
        with WheelFile.open(roda) as fonte:
            # confere o RECORD da roda (cada arquivo com o hash declarado)
            fonte.validate_record()
            install(source=fonte, destination=destino,
                    additional_metadata={"INSTALLER": b"helestron-construir\n"})


IGNORAR_NO_PACOTE = ("__pycache__", "*.pyc", "*.pyo", "*.parcial", "*.tmp", ".DS_Store")


def modulos_de(pasta: Path) -> set[str]:
    """Os .py de uma pasta (relativos, com "/"), sem os de __pycache__."""
    return {p.relative_to(pasta).as_posix() for p in pasta.rglob("*.py")
            if "__pycache__" not in p.parts}


def copiar_pacote(arvore: Path, origem: Path | None = None) -> Path:
    """helestron/ -> Lib/site-packages/helestron: a pasta INTEIRA (módulos,
    web, recursos, dados), sem __pycache__ nem .pyc. Não há lista de módulos
    a manter - o módulo novo (nucleo/paginacao.py, download/acompanhamento.py)
    entra sozinho -, e a cópia é conferida: módulo que não chegou interrompe
    a construção (a verificação da instalação acusaria só no Windows)."""
    origem = Path(origem or PACOTE)
    destino = arvore / "Lib" / "site-packages" / "helestron"
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(origem, destino, ignore=shutil.ignore_patterns(*IGNORAR_NO_PACOTE))
    if not (destino / "__main__.py").is_file():
        raise ErroConstrucao("o pacote copiado não tem helestron/__main__.py")
    faltam = sorted(modulos_de(origem) - modulos_de(destino))
    if faltam:
        raise ErroConstrucao("módulos do pacote que não foram copiados: " + ", ".join(faltam))
    return destino


# ============================================================= etapa 4
def enxugar(arvore: Path) -> int:
    """Remove o que o programa não usa. Devolve quantos bytes saíram."""
    antes = tamanho_da_arvore(arvore)
    for rel in REMOVER_PASTAS:
        remover(arvore / rel)
    for padrao in REMOVER_ARQUIVOS:
        for arq in list(arvore.glob(padrao)):
            remover(arq)
    for dist_info in (arvore / "Lib" / "site-packages").glob("pip-*.dist-info"):
        remover(dist_info)
    for padrao in REMOVER_PADROES:
        for arq in list(arvore.rglob(padrao)):
            remover(arq)
    # .pyc que vieram prontos (de outra versão, outro modo de validação):
    # serão todos refeitos abaixo, iguais.
    for pasta in sorted(arvore.rglob("__pycache__"), reverse=True):
        remover(pasta)
    return antes - tamanho_da_arvore(arvore)


def precompilar(arvore: Path) -> list[str]:
    """Compila Lib/ inteira em .pyc (UNCHECKED_HASH). Devolve os .py que não
    compilaram (código de exemplo ou modelo dentro de bibliotecas, que nunca
    é importado), relativos à pasta do programa.

    Os caminhos gravados nos .pyc ficam relativos (Lib/...): o Python os troca
    pelo caminho real ao importar, e o da máquina da construção não vaza.
    """
    if sys.version_info[:2] != VERSAO_PYTHON:
        raise ErroConstrucao(f"rode a construção com Python {VERSAO_PYTHON[0]}.{VERSAO_PYTHON[1]}: "
                             "os .pyc têm de ser da versão que vai no instalador "
                             f"(este é {platform.python_version()})")
    import importlib.util

    lib = arvore / "Lib"
    compileall.compile_dir(str(lib), quiet=2, workers=os.cpu_count() or 1,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
                           stripdir=str(arvore), prependdir="")
    # Os erros saem nos processos auxiliares; quem não compilou é quem ficou
    # sem o .pyc ao lado.
    return sorted(py.relative_to(arvore).as_posix() for py in lib.rglob("*.py")
                  if not Path(importlib.util.cache_from_source(str(py))).is_file())


def tamanho_da_arvore(pasta: Path) -> int:
    return sum(p.stat().st_size for p in pasta.rglob("*") if p.is_file())


# ============================================================= etapa 5
def arquivos_do_modelo(pasta: Path) -> list[Path]:
    return sorted(p for p in pasta.iterdir()
                  if p.is_file() and any(fnmatch.fnmatch(p.name, pad) for pad in PADROES_MODELO))


def comandos_conversao() -> str:
    """Os comandos de COMANDOS_CONVERSAO, um por linha, para as mensagens."""
    return "\n".join(f"        {c}" for c in COMANDOS_CONVERSAO)


def conferir_modelo(pasta: Path) -> None:
    """O faster-whisper-small em int8, completo, na pasta. O tamanho do
    model.bin distingue o int8 (~250 MB) do float16 publicado no Hugging Face
    (~484 MB), que estouraria o LIMITE_SETUP, e da cópia interrompida."""
    if not pasta.is_dir():
        raise ErroConstrucao(f"a pasta do modelo {pasta} não existe")
    faltam = [n for n in NECESSARIOS_MODELO if not (pasta / n).is_file()]
    if not any(fnmatch.fnmatch(p.name, "vocabulary.*") for p in pasta.iterdir() if p.is_file()):
        faltam.append("vocabulary.*")
    if faltam:
        raise ErroConstrucao(f"o modelo em {pasta} está incompleto (faltam: {', '.join(faltam)})")
    tamanho = (pasta / "model.bin").stat().st_size
    minimo, maximo = LIMITES_MODELO
    if tamanho > maximo:
        raise ErroConstrucao(
            f"{pasta / 'model.bin'} tem {tamanho / 1e6:.0f} MB: parece o modelo em float16 (o "
            "publicado no Hugging Face, ~484 MB), e o instalador passaria de 500 MiB. Construa "
            f"com --sem-modelo ou converta-o para int8, como o CI:\n{comandos_conversao()}")
    if tamanho < minimo:
        raise ErroConstrucao(
            f"{pasta / 'model.bin'} tem {tamanho / 1e6:.0f} MB, pouco para o faster-whisper-small "
            "em int8 (~250 MB): cópia interrompida, ou outro modelo?")


def copiar_modelo(origem: Path, arvore: Path) -> Path:
    conferir_modelo(origem)
    destino = arvore / "modelos" / PASTA_MODELO
    destino.mkdir(parents=True, exist_ok=True)
    for arq in arquivos_do_modelo(origem):
        shutil.copy2(arq, destino / arq.name)
    return destino


def constantes_falantes() -> dict:
    """URLs, hashes e nomes dos modelos de falantes, lidos do código do
    programa (helestron/transcricao/falantes.py) sem importá-lo."""
    import ast

    arvore_ast = ast.parse((PACOTE / "transcricao" / "falantes.py").read_text(encoding="utf-8"))
    nomes = {"URL_SEGMENTACAO", "URL_EMBEDDING", "SHA256", "SUBPASTA_SEGMENTACAO",
             "ARQUIVO_SEGMENTACAO", "ARQUIVO_EMBEDDING"}
    valores = {}
    for no in arvore_ast.body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
            if no.targets[0].id in nomes:
                valores[no.targets[0].id] = ast.literal_eval(no.value)
    faltam = nomes - set(valores)
    if faltam:
        raise ErroConstrucao(f"falantes.py sem {', '.join(sorted(faltam))}")
    return valores


def obter_falantes(cache: Path, arvore: Path) -> list[Path]:
    """Os dois modelos de voz (segmentação pyannote e "impressão digital"
    3D-Speaker) em modelos/falantes, com o SHA-256 conferido."""
    c = constantes_falantes()
    nome_tar = c["URL_SEGMENTACAO"].rsplit("/", 1)[1]
    for nome in (nome_tar, c["ARQUIVO_EMBEDDING"]):
        if not re.fullmatch(r"[0-9a-f]{64}", str(c["SHA256"].get(nome, ""))):
            raise ErroConstrucao(f"falantes.py sem o SHA-256 de {nome}")
    tar = baixar(c["URL_SEGMENTACAO"], cache / "falantes" / nome_tar, c["SHA256"][nome_tar])
    onnx = baixar(c["URL_EMBEDDING"], cache / "falantes" / c["ARQUIVO_EMBEDDING"],
                  c["SHA256"][c["ARQUIVO_EMBEDDING"]])
    destino = arvore / "modelos" / "falantes"
    seg = destino / c["SUBPASTA_SEGMENTACAO"] / c["ARQUIVO_SEGMENTACAO"]
    seg.parent.mkdir(parents=True, exist_ok=True)
    procurado = f"{c['SUBPASTA_SEGMENTACAO']}/{c['ARQUIVO_SEGMENTACAO']}"
    with tarfile.open(tar) as t:
        membro = next((m for m in t.getmembers() if m.name.lstrip("./") == procurado), None)
        if membro is None or not membro.isfile():
            raise ErroConstrucao(f"{nome_tar} sem {procurado}")
        with t.extractfile(membro) as f, open(seg, "wb") as saida:
            shutil.copyfileobj(f, saida)
    alvo = destino / c["ARQUIVO_EMBEDDING"]
    shutil.copy2(onnx, alvo)
    return [seg, alvo]


# ============================================================= etapa 6
def ferramenta(nome: str) -> str:
    """Um programa do MinGW (x86_64-w64-mingw32-<nome>), ou o sem prefixo no
    Windows (MSYS2)."""
    for candidato in (f"x86_64-w64-mingw32-{nome}", nome if os.name == "nt" else ""):
        if candidato and shutil.which(candidato):
            return shutil.which(candidato)
    raise ErroConstrucao(f"falta o {nome} do MinGW-w64 (no Ubuntu: sudo apt-get install mingw-w64)")


def renderizar(modelo: str, valores: dict[str, str]) -> str:
    """Troca @CHAVE@ pelos valores; marcador sem valor é erro."""
    def troca(achado: re.Match) -> str:
        chave = achado.group(1)
        if chave not in valores:
            raise ErroConstrucao(f"marcador @{chave}@ sem valor")
        return str(valores[chave])

    texto = re.sub(r"@([A-Z][A-Z0-9_]*)@", troca, modelo)
    return texto


def sem_comentarios_xml(texto: str) -> str:
    """O manifesto embutido vai sem os comentários (o leitor de manifestos do
    Windows é estrito: um erro nele impede o programa de abrir)."""
    return re.sub(r"<!--.*?-->\s*", "", texto, flags=re.S)


def compilar_lancador(versao: str, obra: Path, icone: Path) -> Path:
    pasta = obra / "lancador"
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    valores = {"VERSAO": versao, "VERSAO_WIN": versao_windows(versao),
               "VERSAO_VIRGULAS": versao_windows(versao).replace(".", ","),
               "ANO": str(datetime.now().year)}
    (pasta / "helestron.rc").write_text(
        renderizar((LANCADOR / "helestron.rc").read_text(encoding="utf-8"), valores), encoding="utf-8")
    (pasta / "helestron.manifest").write_text(
        sem_comentarios_xml(renderizar((LANCADOR / "helestron.manifest").read_text(encoding="utf-8"),
                                       valores)), encoding="utf-8")
    shutil.copy2(LANCADOR / "helestron.c", pasta / "helestron.c")
    shutil.copy2(icone, pasta / "helestron.ico")
    subprocess.run([ferramenta("windres"), "helestron.rc", "-O", "coff", "-o", "recursos.o"],
                   cwd=pasta, check=True)
    subprocess.run([ferramenta("gcc"), "-municode", "-mwindows", "-O2", "-s", "-Wall",
                    "-o", "Helestron.exe", "helestron.c", "recursos.o"], cwd=pasta, check=True)
    exe = pasta / "Helestron.exe"
    conferir_lancador(subprocess.run([ferramenta("objdump"), "-p", str(exe)], check=True,
                                     capture_output=True, text=True).stdout, exe.read_bytes())
    return exe


def conferir_lancador(objdump: str, binario: bytes) -> None:
    """O executável é de 64 bits, de janela (sem console), não depende do
    python312.dll na carga (é carregado à mão) e tem ícone e manifesto."""
    problemas = []
    if not re.search(r"^Magic\s+020b", objdump, re.M):
        problemas.append("não é PE32+ (64 bits)")
    if not re.search(r"^Subsystem\s+0+2\b", objdump, re.M):
        problemas.append("não é do subsistema de janela (abriria um console)")
    dlls = {d.lower() for d in re.findall(r"DLL Name:\s*(\S+)", objdump)}
    if any(d.startswith("python") for d in dlls):
        problemas.append("importa o DLL do Python na carga (a mensagem própria não apareceria)")
    for funcao in ("LoadLibraryExW", "GetProcAddress"):
        if not re.search(rf"\b{funcao}\b", objdump):
            problemas.append(f"não usa {funcao}")
    if b"Py_Main" not in binario:
        problemas.append("sem a chamada de Py_Main")
    if "-I".encode("utf-16-le") not in binario or "helestron".encode("utf-16-le") not in binario:
        problemas.append("sem os argumentos -I -m helestron")
    if b"PerMonitorV2" not in binario or b"longPathAware" not in binario:
        problemas.append("sem o manifesto (DPI PerMonitorV2, longPathAware)")
    if "ProductVersion".encode("utf-16-le") not in binario:
        problemas.append("sem as informações de versão")
    if problemas:
        raise ErroConstrucao("Helestron.exe com problema: " + "; ".join(problemas))


def gravar_comando(arvore: Path) -> Path:
    """O helestron.cmd na raiz da pasta do programa, ao lado do python.exe
    (CONTEUDO_COMANDO). Entra no manifesto e na lista do que a instalação
    põe na pasta como qualquer arquivo: a verificação o confere e a
    desinstalação o apaga."""
    destino = arvore / NOME_COMANDO
    destino.write_bytes(CONTEUDO_COMANDO.encode("ascii"))
    return destino


# ============================================================= etapa 7
NOME_MANIFESTO = "manifesto.json"


def componentes_da_arvore(arvore: Path) -> dict:
    """O que a construção embutiu, lido da própria árvore (e não das opções):
    {"modelo_transcricao": "faster-whisper-small" ou "", "falantes": bool}.
    Com isto no manifesto, a verificação da instalação sabe se a falta de um
    modelo é defeito ou uma construção sem ele (--sem-modelo, --sem-falantes)."""
    modelo = arvore / "modelos" / PASTA_MODELO / "model.bin"
    falantes = arvore / "modelos" / "falantes"
    return {"modelo_transcricao": PASTA_MODELO if modelo.is_file() else "",
            "falantes": falantes.is_dir() and any(falantes.rglob("*.onnx"))}


def gerar_manifesto(arvore: Path, versao: str) -> dict:
    """{nome, versao, gerado_em, componentes, arquivos: {caminho: {tamanho,
    sha256}}} de todos os arquivos da pasta do programa (caminhos com "/"), no
    formato que helestron/aplicativo/integridade.py lê (as chaves que ele não
    conhece, como "componentes", ele ignora)."""
    arquivos = {}
    for arq in sorted(arvore.rglob("*")):
        if not arq.is_file():
            continue
        rel = arq.relative_to(arvore).as_posix()
        if rel == NOME_MANIFESTO:
            continue
        arquivos[rel] = {"tamanho": arq.stat().st_size, "sha256": sha256_de(arq)}
    manifesto = {"nome": "Helestron", "versao": versao,
                 "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "componentes": componentes_da_arvore(arvore),
                 "arquivos": arquivos}
    (arvore / NOME_MANIFESTO).write_text(json.dumps(manifesto, indent=1, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    return manifesto


# ============================================================= etapa 8
NOME_REGISTRO = "arquivos-instalados.txt"
NOME_DESINSTALADOR = "Desinstalar.exe"


def linhas_do_registro(arvore: Path) -> list[str]:
    """As linhas da lista do que a instalação põe na pasta do programa:
    "A <arquivo>" para cada arquivo (e o Desinstalar.exe, que o instalador
    grava) e, depois, "P <pasta>" para cada pasta, das mais fundas para as
    de cima - o instalador apaga os arquivos um a um e as pastas só se
    ficarem vazias. Caminhos relativos, com "\\". O manifesto.json e a própria
    lista vêm por último: até o fim da remoção, a pasta continua sendo
    reconhecida como do Helestron."""
    finais = (NOME_DESINSTALADOR, NOME_MANIFESTO, NOME_REGISTRO)
    arquivos = sorted((p.relative_to(arvore).as_posix() for p in arvore.rglob("*")
                       if p.is_file() and p.relative_to(arvore).as_posix() not in finais),
                      key=str.lower)
    pastas = sorted((p.relative_to(arvore).as_posix() for p in arvore.rglob("*") if p.is_dir()),
                    key=lambda rel: (-rel.count("/"), rel.lower()))
    return ([f"A {rel}" for rel in (*arquivos, *finais)]
            + [f"P {rel}" for rel in pastas])


def gerar_registro(arvore: Path, versao: str, destino: Path) -> Path:
    """Grava a lista (linhas_do_registro) em destino, em UTF-16 com BOM e
    CRLF - o que o FileReadUTF16LE do NSIS lê, com qualquer caractere -,
    depois do cabeçalho "Helestron <versão> ...", pelo qual o instalador
    reconhece uma pasta que já tem o Helestron."""
    cabecalho = (f"Helestron {versao} - arquivos instalados nesta pasta. A atualização e o "
                 "desinstalador apagam só o que está nesta lista.")
    linhas = [cabecalho] + [linha.replace("/", "\\") for linha in linhas_do_registro(arvore)]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes("\ufeff".encode("utf-16-le") + ("\r\n".join(linhas) + "\r\n").encode("utf-16-le"))
    return destino


def script_nsis(arvore: Path, versao: str, saida_exe: Path, recursos: Path,
                registro: Path | None = None) -> str:
    """O helestron.nsi com os valores desta construção. Sem registro, a lista
    do que a versão instala é gravada ao lado da árvore (gerar_registro)."""
    if registro is None:
        registro = gerar_registro(arvore, versao, arvore.parent / NOME_REGISTRO)
    valores = {
        "VERSAO": versao,
        "VERSAO_WIN": versao_windows(versao),
        "ANO": str(datetime.now().year),
        "ARVORE": arvore.resolve().as_posix(),
        "SAIDA": saida_exe.resolve().as_posix(),
        "ICONE": (recursos / "helestron.ico").resolve().as_posix(),
        "BOAS_VINDAS": (recursos / "instalador-boas-vindas.bmp").resolve().as_posix(),
        "CABECALHO": (recursos / "instalador-cabecalho.bmp").resolve().as_posix(),
        "TAMANHO_KB": str(max(1, tamanho_da_arvore(arvore) // 1024)),
        "REGISTRO": registro.resolve().as_posix(),
        "URL_PROJETO": URL_PROJETO,
    }
    if os.name == "nt":     # o makensis do Windows quer barras invertidas
        for chave in ("ARVORE", "SAIDA", "ICONE", "BOAS_VINDAS", "CABECALHO", "REGISTRO"):
            valores[chave] = valores[chave].replace("/", "\\")
    return renderizar(MODELO_NSIS.read_text(encoding="utf-8"), valores)


def achar_makensis() -> str:
    candidatos = ["makensis"]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            if base:
                candidatos.append(str(Path(base) / "NSIS" / "makensis.exe"))
    for c in candidatos:
        achado = shutil.which(c) or (c if Path(c).is_file() else None)
        if achado:
            return achado
    raise ErroConstrucao("falta o NSIS (makensis); no Ubuntu: sudo apt-get install nsis")


def conferir_tamanho_do_setup(exe: Path, limite: int = LIMITE_SETUP) -> None:
    """O instalador cabe no limite para entrega por anexo? Senão, ele sai de
    dist (não fica um Setup que o CI reprovaria à espera de ser enviado)."""
    tamanho = exe.stat().st_size
    if tamanho > limite:
        exe.unlink(missing_ok=True)
        raise ErroConstrucao(
            f"o instalador ficou com {tamanho / 1024 / 1024:.0f} MiB, acima do limite de "
            f"{limite / 1024 / 1024:.0f} MiB para entrega por anexo (o modelo de transcrição está "
            "em int8?)")


def rodar_makensis(script: Path) -> None:
    opcao = "/" if os.name == "nt" else "-"
    subprocess.run([achar_makensis(), f"{opcao}V2", f"{opcao}INPUTCHARSET", "UTF8", str(script)],
                   check=True)


# ============================================================= principal
def garantir_marca(regerar: bool) -> None:
    necessarios = ("helestron.ico", "helestron.png", "helestron-64.png",
                   "instalador-boas-vindas.bmp", "instalador-cabecalho.bmp")
    if regerar or not all((RECURSOS / n).is_file() for n in necessarios):
        sys.path.insert(0, str(CONSTRUIR))
        try:
            import marca
        except ImportError as erro:
            raise ErroConstrucao(f"para gerar a marca falta o Pillow ({erro}): pip install pillow") from None
        for arq in marca.gerar():
            info(f"marca: {arq.relative_to(RAIZ)}")


def construir(args: argparse.Namespace) -> Path:
    inicio = time.monotonic()
    versao = versao_do_pacote()
    cache = Path(args.cache).resolve()
    obra = Path(args.obra).resolve()
    saida = Path(args.saida).resolve()
    arvore = obra / "Helestron"
    print(f"Helestron {versao} - construção do instalador")
    print(f"  obra: {obra}\n  cache: {cache}\n  saída: {saida}")
    if args.modelo and args.sem_modelo:
        raise ErroConstrucao("use --modelo DIR ou --sem-modelo, não os dois")
    if not args.modelo and not args.sem_modelo:
        # Antes, sem --modelo, baixava-se o do Hugging Face, em float16: um
        # instalador acima de 500 MiB e diferente do publicado pelo CI.
        raise ErroConstrucao(
            "diga de onde vem o modelo de transcrição: --modelo DIR, com o faster-whisper-small "
            "já em int8, ou --sem-modelo (o programa o baixa no primeiro uso). O CI converte o "
            f"modelo assim:\n{comandos_conversao()}")
    if args.modelo:
        conferir_modelo(Path(args.modelo))      # antes do trabalho pesado
    if sys.version_info[:2] != VERSAO_PYTHON:
        raise ErroConstrucao(f"rode com Python {VERSAO_PYTHON[0]}.{VERSAO_PYTHON[1]} "
                             f"(este é {platform.python_version()})")
    garantir_marca(args.marca)
    # confere as ferramentas antes do trabalho pesado
    for nome in ("gcc", "windres", "objdump"):
        ferramenta(nome)
    achar_makensis()

    etapa(1, "Python para Windows (python-build-standalone 3.12.10)")
    if args.python_tar:
        tar = Path(args.python_tar)
        if sha256_de(tar) != SHA256_PYTHON:
            raise ErroConstrucao(f"{tar} não tem o SHA-256 esperado ({SHA256_PYTHON})")
    else:
        tar = baixar(URL_PYTHON, cache / "python" / URL_PYTHON.rsplit("/", 1)[1].replace("%2B", "+"),
                     SHA256_PYTHON)
    extrair_python(tar, arvore)
    info(f"extraído em {arvore}")

    etapa(2, "Rodas para Windows (requisitos-windows.txt, hashes conferidos)")
    requisitos = ler_requisitos(REQUISITOS.read_text(encoding="utf-8"))
    rodas = obter_rodas(requisitos, cache)
    info(f"{len(rodas)} pacotes")

    etapa(3, "Instalação das rodas e do pacote helestron")
    instalar_rodas(rodas, arvore)
    copiar_pacote(arvore)
    info("Lib/site-packages pronto")

    etapa(4, "Enxugar e pré-compilar (.pyc UNCHECKED_HASH)")
    economia = enxugar(arvore)
    info(f"{economia / 1e6:.0f} MB removidos")
    falhas = precompilar(arvore)
    for f in falhas:
        info(f"não compilou (fica só o .py): {f}")
    if any("helestron" in f.replace("\\", "/").split("/") for f in falhas):
        raise ErroConstrucao("arquivo do pacote helestron não compila: " + ", ".join(falhas))

    etapa(5, "Modelos (transcrição e separação de falantes)")
    if args.sem_modelo:
        info("--sem-modelo: o modelo de transcrição será baixado no primeiro uso")
    else:
        info(f"faster-whisper-small: {copiar_modelo(Path(args.modelo), arvore)}")
    if args.sem_falantes:
        info("--sem-falantes: os modelos de voz serão baixados quando o usuário pedir")
    else:
        # A falha aqui interrompe a construção (antes, virava um AVISO e um
        # instalador "verde" sem os modelos): o manual promete a separação de
        # vozes sem internet. Um instalador sem eles só com --sem-falantes.
        try:
            for arq in obter_falantes(cache, arvore):
                info(f"falantes: {arq.relative_to(arvore)}")
        except ErroConstrucao as erro:
            raise ErroConstrucao(f"modelos da separação de falantes: {erro} (para construir sem "
                                 "eles, de propósito: --sem-falantes)") from None

    etapa(6, "Lançadores (Helestron.exe e helestron.cmd)")
    exe = compilar_lancador(versao, obra, RECURSOS / "helestron.ico")
    shutil.copy2(exe, arvore / "Helestron.exe")
    shutil.copy2(RECURSOS / "helestron.ico", arvore / "helestron.ico")
    info(f"Helestron.exe: {exe.stat().st_size // 1024} KB, conferido com o objdump")
    info(f"{gravar_comando(arvore).name}: a linha de comando (python.exe -I -m helestron)")

    etapa(7, "Manifesto de integridade (manifesto.json)")
    manifesto = gerar_manifesto(arvore, versao)
    total = tamanho_da_arvore(arvore)
    info(f"{len(manifesto['arquivos'])} arquivos, {total / 1e6:.0f} MB; embutidos: "
         f"{json.dumps(manifesto['componentes'], ensure_ascii=False)}")

    etapa(8, "Instalador (NSIS)")
    saida.mkdir(parents=True, exist_ok=True)
    exe_final = saida / f"Helestron-Setup-{versao}.exe"
    registro = gerar_registro(arvore, versao, obra / NOME_REGISTRO)
    info(f"{registro.name}: a lista do que esta versão instala (a atualização e o "
         "desinstalador apagam só o que está nela)")
    script = obra / "helestron.nsi"
    script.write_text(script_nsis(arvore, versao, exe_final, RECURSOS, registro), encoding="utf-8")
    exe_final.unlink(missing_ok=True)
    rodar_makensis(script)
    if not exe_final.is_file():
        raise ErroConstrucao("o makensis terminou sem gerar o instalador")
    conferir_tamanho_do_setup(exe_final)
    soma = sha256_de(exe_final)
    (saida / f"{exe_final.name}.sha256").write_text(f"{soma}  {exe_final.name}\n", encoding="utf-8")
    minutos = (time.monotonic() - inicio) / 60
    print(f"\nPronto em {minutos:.1f} min: {exe_final} ({exe_final.stat().st_size / 1e6:.0f} MB)")
    print(f"SHA-256: {soma}")
    return exe_final


def classe_do_analisador() -> type:
    """O ArgumentParser em português do programa (helestron/nucleo/argumentos.py,
    só biblioteca padrão), carregado pelo arquivo: importar o pacote helestron
    aqui não é preciso. Sem ele, o do argparse."""
    import importlib.util

    arquivo = PACOTE / "nucleo" / "argumentos.py"
    try:
        spec = importlib.util.spec_from_file_location("helestron_argumentos", arquivo)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.ArgumentParser
    except (OSError, ImportError, AttributeError, SyntaxError):
        return argparse.ArgumentParser


def main(argv: list[str] | None = None) -> int:
    p = classe_do_analisador()(prog="python construir/construir.py",
                               description="Constrói o Helestron-Setup-<versão>.exe.")
    p.add_argument("--saida", metavar="PASTA", default=str(RAIZ / "dist"), help="pasta do instalador (padrão: dist)")
    p.add_argument("--cache", metavar="PASTA", default=str(CONSTRUIR / "cache"),
                   help="downloads reaproveitáveis (padrão: construir/cache)")
    p.add_argument("--obra", metavar="PASTA", default=str(CONSTRUIR / "obra"),
                   help="pasta de trabalho (padrão: construir/obra)")
    p.add_argument("--python-tar", metavar="ARQ", help="o .tar.gz do python-build-standalone já baixado")
    p.add_argument("--modelo", metavar="PASTA",
                   help="pasta com o faster-whisper-small já em int8 (como o CI o converte)")
    p.add_argument("--sem-modelo", action="store_true",
                   help="instalador sem o modelo de transcrição (baixado no primeiro uso)")
    p.add_argument("--sem-falantes", action="store_true",
                   help="instalador sem os modelos da separação de falantes (sem esta opção, "
                        "a falha ao obtê-los interrompe a construção)")
    p.add_argument("--marca", action="store_true", help="gera de novo o ícone e as imagens")
    p.add_argument("--versao", action="store_true",
                   help="só mostra a versão que será construída (a de helestron/__init__.py) "
                        "e sai")
    args = p.parse_args(argv)
    if args.versao:
        # Só a versão, numa linha: o CI a compara com a tag da publicação.
        try:
            print(versao_do_pacote())
        except ErroConstrucao as erro:
            print(f"ERRO: {erro}", file=sys.stderr)
            return 1
        return 0
    try:
        construir(args)
    except ErroConstrucao as erro:
        print(f"\nERRO: {erro}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as erro:
        print(f"\nERRO: o comando {erro.cmd} terminou com o código {erro.returncode}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
