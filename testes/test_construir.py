"""Testes da construção do instalador (construir/), da marca e do CI.

O que é verificado sem rede e sem Windows:
  * manifesto.json: o formato que construir.py grava é o que o programa lê
    (aplicativo/integridade.py) e acusa o arquivo alterado;
  * rodas: a escolha da roda certa para Windows/cp312 entre as publicadas, o
    hash travado, a roda gerada de código-fonte puro Python e o esquema de
    instalação (Lib/site-packages; os dados do msvc-runtime na raiz);
  * os requisitos travados com hash (Windows e testes);
  * o script NSIS renderizado: nenhum marcador sobrando, páginas, registro de
    desinstalação, atalhos, --encerrar, a conferência final e o
    desinstalador que nunca apaga Documentos\\Helestron (com o makensis, se
    houver, ele é compilado de verdade);
  * com o makensis, o MinGW-w64 e o Wine de 64 bits: o instalador de verdade
    (alvo amd64), com um programa falso, roda no Wine - audiência em
    andamento (código 7), servidor MCP prendendo os arquivos (renomeados,
    código 0), pasta sem permissão (código 8), sem janela (código 9) e a
    desinstalação que tira os dois conectores;
  * o lançador: a fonte chama "-I -m helestron" pelo Py_Main do
    python312.dll carregado à mão; o manifesto e o .rc (com o MinGW, se
    houver, compila e confere o executável);
  * a marca: o .ico com todos os tamanhos em RGBA e cantos transparentes,
    os PNG, os BMP do instalador e o SVG;
  * o workflow do GitHub Actions: YAML válido, os quatro trabalhos e os
    scripts só com ASCII.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

REPOSITORIO = Path(__file__).resolve().parents[1]
CONSTRUIR = REPOSITORIO / "construir"
RECURSOS = REPOSITORIO / "helestron" / "recursos"
WEB_MARCA = REPOSITORIO / "helestron" / "web" / "img" / "marca"
WORKFLOW = REPOSITORIO / ".github" / "workflows" / "helestron.yml"


def _carregar(nome: str, arquivo: Path):
    """Carrega um script de construir/ como módulo (a pasta não é pacote)."""
    if nome in sys.modules:
        return sys.modules[nome]
    spec = importlib.util.spec_from_file_location(nome, arquivo)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo          # as dataclasses procuram o módulo aqui
    spec.loader.exec_module(modulo)
    return modulo


construcao = _carregar("helestron_construir", CONSTRUIR / "construir.py")

TEM_PIL = importlib.util.find_spec("PIL") is not None

try:
    import yaml
except ImportError:
    yaml = None

TEM_INSTALLER = importlib.util.find_spec("installer") is not None

MINGW = all(shutil.which(f"x86_64-w64-mingw32-{f}") for f in ("gcc", "windres", "objdump"))
MAKENSIS = shutil.which("makensis")
PWSH = os.environ.get("HELESTRON_PWSH") or shutil.which("pwsh")
WINE64 = shutil.which("wine64") or next(
    (c for c in ("/usr/lib/wine/wine64", "/usr/lib/x86_64-linux-gnu/wine/wine64")
     if Path(c).is_file()), None)


def _arvore_exemplo(pasta: Path) -> Path:
    """Uma 'pasta do programa' mínima, com a cara da real."""
    arvore = pasta / "Helestron"
    for rel, dados in {
        "python.exe": b"MZ python",
        "python312.dll": b"MZ dll",
        "Helestron.exe": b"MZ lancador",
        "Lib/os.py": b"# os\n",
        "Lib/site-packages/helestron/__init__.py": b'__version__ = "1.0.0"\n',
        "Lib/site-packages/helestron/__main__.py": b"print('oi')\n",
        "Lib/site-packages/helestron/web/index.html": "<p>Ação</p>".encode("utf-8"),
        "DLLs/_ssl.pyd": b"MZ pyd",
        "modelos/falantes/modelo.onnx": b"\x00" * 64,
    }.items():
        alvo = arvore / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(dados)
    return arvore


# =================================================================== versão
class TestVersao(unittest.TestCase):
    def test_versao_do_pacote_igual_a_do_programa(self):
        import helestron

        self.assertEqual(construcao.versao_do_pacote(), helestron.__version__)

    def test_versao_windows_tem_quatro_partes(self):
        self.assertEqual(construcao.versao_windows("1.0.0"), "1.0.0.0")
        self.assertEqual(construcao.versao_windows("2.3"), "2.3.0.0")
        self.assertEqual(construcao.versao_windows("1.2.3.4"), "1.2.3.4")


# =================================================================== manifesto
class TestManifesto(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.arvore = _arvore_exemplo(self.tmp)

    def test_formato(self):
        manifesto = construcao.gerar_manifesto(self.arvore, "1.0.0")
        gravado = json.loads((self.arvore / "manifesto.json").read_text(encoding="utf-8"))
        self.assertEqual(gravado, manifesto)
        self.assertEqual(gravado["versao"], "1.0.0")
        self.assertEqual(gravado["nome"], "Helestron")
        arquivos = gravado["arquivos"]
        self.assertNotIn("manifesto.json", arquivos)
        self.assertIn("Lib/site-packages/helestron/__main__.py", arquivos)
        self.assertTrue(all("\\" not in c for c in arquivos))
        entrada = arquivos["Lib/site-packages/helestron/web/index.html"]
        dados = "<p>Ação</p>".encode("utf-8")
        self.assertEqual(entrada["tamanho"], len(dados))
        self.assertEqual(entrada["sha256"], hashlib.sha256(dados).hexdigest())
        total = sum(1 for p in self.arvore.rglob("*") if p.is_file()) - 1
        self.assertEqual(len(arquivos), total)

    def test_o_programa_le_e_confere_o_manifesto(self):
        from helestron.aplicativo import integridade

        construcao.gerar_manifesto(self.arvore, "1.0.0")
        versao, entradas = integridade.ler_manifesto(self.arvore)
        self.assertEqual(versao, "1.0.0")
        self.assertEqual(len(entradas), 9)
        self.assertEqual(integridade.conferir_completo(self.arvore), [])
        self.assertEqual(integridade.conferir_rapido(self.arvore), [])
        # o antivírus "leva" um arquivo e altera outro (mesmo tamanho)
        (self.arvore / "Lib/site-packages/helestron/__main__.py").unlink()
        (self.arvore / "python.exe").write_bytes(b"MZ PYTHON")
        problemas = {p.arquivo: p.motivo for p in integridade.conferir_completo(self.arvore)}
        self.assertEqual(problemas, {"Lib/site-packages/helestron/__main__.py": integridade.AUSENTE,
                                     "python.exe": integridade.CONTEUDO})


class TestRegistroDaInstalacao(unittest.TestCase):
    """arquivos-instalados.txt: a lista do que a instalação põe na pasta do
    programa - a atualização e o desinstalador apagam só o que está nela."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.arvore = _arvore_exemplo(self.tmp)
        (self.arvore / "Lib" / "site-packages" / "helestron" / "__pycache__").mkdir()
        (self.arvore / "Lib" / "site-packages" / "helestron" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"pyc")
        (self.arvore / "Lib" / "site-packages" / "helestron" / "ação.py").write_text("# ç\n", encoding="utf-8")
        construcao.gerar_manifesto(self.arvore, "1.0.0")

    def test_formato(self):
        arquivo = construcao.gerar_registro(self.arvore, "1.0.0", self.tmp / "obra" / "arquivos-instalados.txt")
        dados = arquivo.read_bytes()
        self.assertEqual(dados[:2], b"\xff\xfe")                   # UTF-16 LE com BOM
        texto = dados[2:].decode("utf-16-le")
        self.assertTrue(texto.endswith("\r\n"))
        linhas = texto[:-2].split("\r\n")
        self.assertTrue(linhas[0].startswith("Helestron 1.0.0 - "), linhas[0])
        corpo = linhas[1:]
        arquivos = [l[2:] for l in corpo if l.startswith("A ")]
        pastas = [l[2:] for l in corpo if l.startswith("P ")]
        self.assertEqual(len(arquivos) + len(pastas), len(corpo))
        # arquivos primeiro, depois as pastas
        self.assertEqual(corpo, [f"A {a}" for a in arquivos] + [f"P {p}" for p in pastas])
        todos = sorted(p.relative_to(self.arvore).as_posix().replace("/", "\\")
                       for p in self.arvore.rglob("*") if p.is_file())
        self.assertEqual(sorted(set(arquivos) - {"Desinstalar.exe", "arquivos-instalados.txt"}), todos)
        self.assertIn("Lib\\site-packages\\helestron\\ação.py", arquivos)
        # o manifesto e a própria lista por último: até o fim da remoção, a
        # pasta continua sendo reconhecida como do Helestron
        self.assertEqual(arquivos[-3:], ["Desinstalar.exe", "manifesto.json", "arquivos-instalados.txt"])
        # as pastas, das mais fundas para as de cima, sem a raiz
        esperadas = {p.relative_to(self.arvore).as_posix().replace("/", "\\")
                     for p in self.arvore.rglob("*") if p.is_dir()}
        self.assertEqual(set(pastas), esperadas)
        profundidades = [p.count("\\") for p in pastas]
        self.assertEqual(profundidades, sorted(profundidades, reverse=True))
        self.assertLess(pastas.index("Lib\\site-packages\\helestron\\__pycache__"), pastas.index("Lib"))
        self.assertNotIn("", pastas)
        self.assertTrue(all("/" not in l and ".." not in l for l in corpo))

    def test_script_usa_a_lista_gravada(self):
        registro = construcao.gerar_registro(self.arvore, "1.0.0", self.tmp / "lista.txt")
        script = construcao.script_nsis(self.arvore, "1.0.0", self.tmp / "Setup.exe", RECURSOS, registro)
        self.assertIn(f'"{registro.resolve().as_posix()}"', script)
        self.assertNotIn("@REGISTRO@", script)
        # sem a lista, a construção a grava ao lado da árvore
        script = construcao.script_nsis(self.arvore, "1.0.0", self.tmp / "Setup.exe", RECURSOS)
        self.assertTrue((self.tmp / "arquivos-instalados.txt").is_file())


# =================================================================== rodas
def _arquivo_pypi(nome: str, conteudo: bytes = b"") -> dict:
    dados = conteudo or nome.encode()
    return {"filename": nome, "url": f"https://files.example/{nome}",
            "digests": {"sha256": hashlib.sha256(dados).hexdigest()}}


class TestEscolhaDeRodas(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(construcao.tags_da_roda("numpy-2.5.3-cp312-cp312-win_amd64.whl"),
                         {("cp312", "cp312", "win_amd64")})
        self.assertEqual(construcao.tags_da_roda("bottle-0.13.4-py2.py3-none-any.whl"),
                         {("py2", "none", "any"), ("py3", "none", "any")})
        self.assertIsNone(construcao.tags_da_roda("proxy_tools-0.1.0.tar.gz"))

    def test_prioridades(self):
        p = construcao.prioridade_da_roda
        self.assertIsNone(p("numpy-2.5.3-cp312-cp312-manylinux_2_28_x86_64.whl"))
        self.assertIsNone(p("numpy-2.5.3-cp313-cp313-win_amd64.whl"))
        self.assertIsNone(p("numpy-2.5.3-cp312-cp312-win32.whl"))
        self.assertIsNone(p("msvc_runtime-14.44.35112-cp312-cp312-win_arm64.whl"))
        self.assertIsNone(p("av-18.1.0-cp314-cp314t-win_amd64.whl"))
        self.assertIsNotNone(p("av-18.1.0-cp311-abi3-win_amd64.whl"))
        self.assertIsNotNone(p("pythonnet-3.2.0-cp311.cp312.cp313.cp314.cp315-none-any.whl"))
        self.assertIsNotNone(p("playwright-1.63.0-py3-none-win_amd64.whl"))
        self.assertLess(p("numpy-2.5.3-cp312-cp312-win_amd64.whl"),
                        p("av-18.1.0-cp311-abi3-win_amd64.whl"))
        # a roda do Windows (com a PortAudio dentro) antes da genérica
        self.assertLess(p("sounddevice-0.5.6-py3-none-win_amd64.whl"),
                        p("sounddevice-0.5.6-py3-none-any.whl"))

    def test_escolhe_a_roda_do_windows_com_hash_travado(self):
        arquivos = [_arquivo_pypi(n) for n in (
            "sounddevice-0.5.6-py3-none-any.whl", "sounddevice-0.5.6-py3-none-win_amd64.whl",
            "sounddevice-0.5.6-py3-none-macosx_10_6_x86_64.whl", "sounddevice-0.5.6.tar.gz")]
        hashes = {a["digests"]["sha256"] for a in arquivos}
        escolhido = construcao.escolher_arquivo(arquivos, hashes)
        self.assertEqual(escolhido["filename"], "sounddevice-0.5.6-py3-none-win_amd64.whl")

    def test_hash_fora_da_lista_nao_serve(self):
        boa = _arquivo_pypi("numpy-2.5.3-cp312-cp312-win_amd64.whl")
        generica = _arquivo_pypi("numpy-2.5.3.tar.gz")
        # só o código-fonte está travado: a roda (outro hash) não pode ser usada
        escolhido = construcao.escolher_arquivo([boa, generica], {generica["digests"]["sha256"]})
        self.assertEqual(escolhido["filename"], "numpy-2.5.3.tar.gz")
        with self.assertRaises(construcao.ErroConstrucao):
            construcao.escolher_arquivo([boa], {"0" * 64})

    def test_sem_arquivo_para_windows(self):
        linux = _arquivo_pypi("x-1.0-cp312-cp312-manylinux_2_28_x86_64.whl")
        with self.assertRaises(construcao.ErroConstrucao) as ctx:
            construcao.escolher_arquivo([linux], {linux["digests"]["sha256"]})
        self.assertIn("Windows 64 bits", str(ctx.exception))

    def test_codigo_fonte_quando_nao_ha_roda(self):
        sdist = _arquivo_pypi("proxy_tools-0.1.0.tar.gz")
        self.assertEqual(construcao.escolher_arquivo([sdist], {sdist["digests"]["sha256"]}), sdist)


def _sdist(pasta: Path, nativo: bool = False) -> Path:
    base = pasta / "fonte" / "pacote_puro-0.1.0"
    (base / "pacote_puro").mkdir(parents=True)
    (base / "pacote_puro" / "__init__.py").write_text("VALOR = 42\n", encoding="utf-8")
    (base / "pacote_puro" / "sub.py").write_text("X = 1\n", encoding="utf-8")
    (base / "pacote_puro.egg-info").mkdir()
    (base / "pacote_puro.egg-info" / "top_level.txt").write_text("pacote_puro\n", encoding="utf-8")
    (base / "PKG-INFO").write_text("Metadata-Version: 1.1\nName: pacote_puro\nVersion: 0.1.0\n"
                                   "Summary: teste\n", encoding="utf-8")
    (base / "setup.py").write_text("from setuptools import setup\nsetup()\n", encoding="utf-8")
    if nativo:
        (base / "pacote_puro" / "rapido.c").write_text("int x;\n", encoding="utf-8")
    arquivo = pasta / "pacote_puro-0.1.0.tar.gz"
    with tarfile.open(arquivo, "w:gz") as t:
        t.add(base, arcname="pacote_puro-0.1.0")
    return arquivo


class TestRodaDeCodigoFonte(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_gera_roda_valida(self):
        roda = construcao.roda_de_codigo_fonte(_sdist(self.tmp), self.tmp / "rodas")
        self.assertEqual(roda.name, "pacote_puro-0.1.0-py3-none-any.whl")
        with zipfile.ZipFile(roda) as z:
            nomes = set(z.namelist())
            self.assertIn("pacote_puro/__init__.py", nomes)
            self.assertIn("pacote_puro/sub.py", nomes)
            info = "pacote_puro-0.1.0.dist-info"
            self.assertIn("Tag: py3-none-any", z.read(f"{info}/WHEEL").decode())
            self.assertIn("Name: pacote_puro", z.read(f"{info}/METADATA").decode())
            # cada linha do RECORD com o hash e o tamanho certos
            for linha in z.read(f"{info}/RECORD").decode().strip().splitlines():
                caminho, hash_, tamanho = linha.rsplit(",", 2)
                if caminho.endswith("RECORD"):
                    continue
                dados = z.read(caminho)
                esperado = base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).rstrip(b"=")
                self.assertEqual(hash_, "sha256=" + esperado.decode())
                self.assertEqual(int(tamanho), len(dados))

    def test_recusa_codigo_nativo(self):
        with self.assertRaises(construcao.ErroConstrucao) as ctx:
            construcao.roda_de_codigo_fonte(_sdist(self.tmp, nativo=True), self.tmp / "rodas")
        self.assertIn("não é puro Python", str(ctx.exception))

    def test_nome_normalizado(self):
        self.assertEqual(construcao.nome_normalizado("proxy-tools"), "proxy_tools")
        self.assertEqual(construcao.nome_normalizado("Typing.Extensions"), "typing_extensions")


def _roda(pasta: Path) -> Path:
    """Roda de exemplo com código (purelib) e um DLL em .data/data (como o
    msvc-runtime)."""
    conteudo = {
        "exemplo/__init__.py": b"OK = True\n",
        "exemplo-1.0.data/data/vcexemplo140.dll": b"MZ dll do runtime",
        "exemplo-1.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: exemplo\nVersion: 1.0\n",
        "exemplo-1.0.dist-info/WHEEL": (b"Wheel-Version: 1.0\nGenerator: teste\n"
                                        b"Root-Is-Purelib: false\nTag: cp312-cp312-win_amd64\n"),
        "exemplo-1.0.dist-info/entry_points.txt": b"[console_scripts]\nexemplo = exemplo:main\n",
    }
    linhas = []
    for caminho, dados in conteudo.items():
        h = base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).rstrip(b"=").decode()
        linhas.append(f"{caminho},sha256={h},{len(dados)}")
    linhas.append("exemplo-1.0.dist-info/RECORD,,")
    conteudo["exemplo-1.0.dist-info/RECORD"] = ("\n".join(linhas) + "\n").encode()
    roda = pasta / "exemplo-1.0-cp312-cp312-win_amd64.whl"
    with zipfile.ZipFile(roda, "w") as z:
        for caminho, dados in conteudo.items():
            z.writestr(caminho, dados)
    return roda


class TestEsquemaDeInstalacao(unittest.TestCase):
    def test_esquema_do_windows(self):
        arvore = Path("/x/Helestron")
        esquema = construcao.esquema_windows(arvore)
        self.assertEqual(Path(esquema["purelib"]), arvore / "Lib" / "site-packages")
        self.assertEqual(Path(esquema["platlib"]), arvore / "Lib" / "site-packages")
        self.assertEqual(Path(esquema["data"]), arvore)
        self.assertEqual(Path(esquema["scripts"]), arvore / "Scripts")
        self.assertTrue(set(esquema) >= {"purelib", "platlib", "headers", "scripts", "data"})

    @unittest.skipUnless(TEM_INSTALLER, "biblioteca 'installer' ausente (só a construção a usa)")
    def test_instala_roda_na_arvore_do_windows(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        arvore = tmp / "Helestron"
        arvore.mkdir()
        construcao.instalar_rodas([_roda(tmp)], arvore)
        self.assertTrue((arvore / "Lib/site-packages/exemplo/__init__.py").is_file())
        # o DLL do runtime na raiz, ao lado do python312.dll
        self.assertEqual((arvore / "vcexemplo140.dll").read_bytes(), b"MZ dll do runtime")
        info = arvore / "Lib/site-packages/exemplo-1.0.dist-info"
        self.assertEqual((info / "INSTALLER").read_text(), "helestron-construir\n")
        # lançador .exe de console_scripts (sai na etapa de enxugar)
        self.assertTrue((arvore / "Scripts" / "exemplo.exe").is_file())


# =================================================================== requisitos
class TestRequisitos(unittest.TestCase):
    def test_ler_requisitos(self):
        texto = ("# cabeçalho\nanyio==4.15.1 \\\n    --hash=sha256:" + "a" * 64 + " \\\n"
                 "    --hash=sha256:" + "b" * 64 + "\n    # via httpx\n"
                 "proxy-tools==0.1.0 \\\n    --hash=sha256:" + "c" * 64 + "\n")
        reqs = construcao.ler_requisitos(texto)
        self.assertEqual([(r.nome, r.versao) for r in reqs], [("anyio", "4.15.1"), ("proxy-tools", "0.1.0")])
        self.assertEqual(reqs[0].hashes, {"a" * 64, "b" * 64})

    def test_recusa_sem_versao_ou_sem_hash(self):
        with self.assertRaises(construcao.ErroConstrucao):
            construcao.ler_requisitos("numpy>=2\n")
        with self.assertRaises(construcao.ErroConstrucao):
            construcao.ler_requisitos("numpy==2.5.3\n")

    def _travado(self, arquivo: str) -> dict[str, str]:
        reqs = construcao.ler_requisitos((CONSTRUIR / arquivo).read_text(encoding="utf-8"))
        self.assertTrue(all(len(h) == 64 for r in reqs for h in r.hashes))
        return {construcao.nome_normalizado(r.nome): r.versao for r in reqs}

    def test_requisitos_windows(self):
        versoes = self._travado("requisitos-windows.txt")
        for nome in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "numpy", "sounddevice",
                     "soundfile", "python_docx", "pymupdf", "pypdf", "openpyxl", "xlrd",
                     "playwright", "pillow", "requests", "truststore", "huggingface_hub",
                     "msvc_runtime", "sherpa_onnx", "pywebview", "pythonnet", "clr_loader",
                     "bottle", "proxy_tools", "typing_extensions"):
            self.assertIn(nome, versoes)
        self.assertTrue(versoes["pywebview"].startswith("6."), versoes["pywebview"])
        self.assertLess(int(versoes["av"].split(".")[0]), 19)       # PyAV 19 quebra o faster-whisper
        self.assertIn("python-platform x86_64-pc-windows-msvc",
                      (CONSTRUIR / "requisitos-windows.txt").read_text(encoding="utf-8"))

    def test_requisitos_teste(self):
        versoes = self._travado("requisitos-teste.txt")
        self.assertNotIn("msvc_runtime", versoes)       # só existe para o Windows
        self.assertNotIn("pywebview", versoes)
        for nome in ("faster_whisper", "playwright", "pymupdf", "openpyxl", "pillow", "pyyaml",
                     "installer", "sherpa_onnx"):
            self.assertIn(nome, versoes)

    def test_entradas_dos_requisitos(self):
        windows = (CONSTRUIR / "requisitos-windows.in").read_text(encoding="utf-8")
        self.assertIn("-r requisitos-base.in", windows)
        self.assertIn("-r requisitos-falantes-base.in", windows)
        base = (CONSTRUIR / "requisitos-base.in").read_text(encoding="utf-8")
        self.assertIn("av<19", base)
        self.assertRegex(base, r'msvc-runtime;\s*sys_platform == "win32"')


# =================================================================== Python do Windows
class TestPythonDoWindows(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _tar(self, nomes: list[str]) -> Path:
        tar = self.tmp / "python.tar.gz"
        with tarfile.open(tar, "w:gz") as t:
            for nome in nomes:
                dados = nome.encode()
                info = tarfile.TarInfo(nome)
                info.size = len(dados)
                t.addfile(info, io.BytesIO(dados))
        return tar

    def test_extrai_sem_o_prefixo(self):
        tar = self._tar(["python/python.exe", "python/Lib/os.py", "python/DLLs/_ssl.pyd"])
        destino = self.tmp / "arvore"
        construcao.extrair_python(tar, destino)
        self.assertEqual((destino / "python.exe").read_bytes(), b"python/python.exe")
        self.assertTrue((destino / "Lib" / "os.py").is_file())
        self.assertFalse((destino / "python").exists())

    def test_recusa_tar_sem_python(self):
        with self.assertRaises(construcao.ErroConstrucao):
            construcao.extrair_python(self._tar(["outra/coisa.txt"]), self.tmp / "arvore")

    def test_sha256_do_python_travado(self):
        self.assertRegex(construcao.SHA256_PYTHON, r"^[0-9a-f]{64}$")
        self.assertIn("3.12.10", construcao.URL_PYTHON)
        self.assertIn("x86_64-pc-windows-msvc-install_only", construcao.URL_PYTHON)


# =================================================================== enxugar e .pyc
class TestEnxugarEPrecompilar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.arvore = _arvore_exemplo(self.tmp)

    def test_enxugar(self):
        for rel in ("Lib/test/test_os.py", "Lib/idlelib/idle.py", "Lib/tkinter/__init__.py",
                    "Scripts/pip.exe", "include/Python.h", "libs/python312.lib", "python.pdb",
                    "Lib/site-packages/pip/__init__.py", "Lib/site-packages/pip-25.0.dist-info/RECORD",
                    "Lib/__pycache__/os.cpython-312.opt-1.pyc"):
            alvo = self.arvore / rel
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(b"x" * 10)
        construcao.enxugar(self.arvore)
        for rel in ("Lib/test", "Lib/idlelib", "Lib/tkinter", "Scripts", "include", "libs",
                    "python.pdb", "Lib/site-packages/pip", "Lib/site-packages/pip-25.0.dist-info",
                    "Lib/__pycache__"):
            self.assertFalse((self.arvore / rel).exists(), rel)
        self.assertTrue((self.arvore / "Lib/site-packages/helestron/__main__.py").is_file())
        self.assertTrue((self.arvore / "python.exe").is_file())

    @unittest.skipUnless(sys.version_info[:2] == (3, 12), "os .pyc da construção são do Python 3.12")
    def test_precompila_unchecked_hash(self):
        quebrado = self.arvore / "Lib/site-packages/modelo_de_codigo.py"
        quebrado.write_text("def (:\n", encoding="utf-8")
        falhas = construcao.precompilar(self.arvore)
        self.assertEqual(falhas, ["Lib/site-packages/modelo_de_codigo.py"])
        pyc = self.arvore / "Lib/site-packages/helestron/__pycache__/__main__.cpython-312.pyc"
        self.assertTrue(pyc.is_file())
        cabecalho = pyc.read_bytes()[:16]
        flags = struct.unpack("<I", cabecalho[4:8])[0]
        self.assertEqual(flags, 0b01)       # baseado em hash, sem conferir o .py (UNCHECKED_HASH)

    def test_recusa_outro_python(self):
        with mock.patch.object(construcao.sys, "version_info", (3, 11, 0)):
            with self.assertRaises(construcao.ErroConstrucao):
                construcao.precompilar(self.arvore)


# =================================================================== modelos
class TestModelos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_copia_o_modelo_para_a_pasta_que_o_programa_procura(self):
        from helestron.transcricao import modelos

        origem = self.tmp / "baixado"
        origem.mkdir()
        for nome, tamanho in (("model.bin", 2_000_000), ("config.json", 10), ("tokenizer.json", 10),
                              ("vocabulary.txt", 10), ("README.md", 10)):
            (origem / nome).write_bytes(b"x" * tamanho)
        arvore = self.tmp / "Helestron"
        destino = construcao.copiar_modelo(origem, arvore)
        self.assertEqual(destino, arvore / "modelos" / "faster-whisper-small")
        self.assertEqual(sorted(p.name for p in destino.iterdir()),
                         ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"])
        # é onde helestron/transcricao/modelos.py procura o embutido
        with mock.patch.object(modelos, "PASTA_EMBUTIDA", arvore / "modelos"), \
                mock.patch.object(modelos, "PASTA", self.tmp / "dados"):
            self.assertTrue(modelos.instalado("small"))
            self.assertEqual(modelos.pasta_do_modelo("small"), destino)

    def test_modelo_incompleto(self):
        origem = self.tmp / "baixado"
        origem.mkdir()
        (origem / "model.bin").write_bytes(b"x" * 10)
        with self.assertRaises(construcao.ErroConstrucao):
            construcao.copiar_modelo(origem, self.tmp / "Helestron")

    def test_constantes_dos_falantes_vem_do_programa(self):
        try:
            from helestron.transcricao import falantes
        except ImportError as erro:                 # Python só da construção, sem numpy
            self.skipTest(f"motor de transcrição indisponível: {erro}")

        c = construcao.constantes_falantes()
        self.assertEqual(c["URL_SEGMENTACAO"], falantes.URL_SEGMENTACAO)
        self.assertEqual(c["URL_EMBEDDING"], falantes.URL_EMBEDDING)
        self.assertEqual(c["SHA256"], falantes.SHA256)
        self.assertEqual(c["SUBPASTA_SEGMENTACAO"], falantes.SUBPASTA_SEGMENTACAO)


# =================================================================== NSIS
class TestScriptNsis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.arvore = _arvore_exemplo(cls.tmp)
        construcao.gerar_manifesto(cls.arvore, "1.0.0")
        cls.saida = cls.tmp / "dist" / "Helestron-Setup-1.0.0.exe"
        cls.script = construcao.script_nsis(cls.arvore, "1.0.0", cls.saida, RECURSOS)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_sem_marcadores_sobrando(self):
        self.assertIsNone(re.search(r"@[A-Z][A-Z0-9_]*@", self.script))
        self.assertIn('!define VERSAO "1.0.0"', self.script)
        self.assertIn('VIProductVersion "1.0.0.0"', self.script)
        self.assertIn(self.saida.resolve().as_posix(), self.script)
        self.assertIn(f'File /r "{self.arvore.resolve().as_posix()}/*"', self.script)

    def test_configuracao_geral(self):
        for trecho in ("Unicode true", "RequestExecutionLevel user", "SetCompressor /SOLID /FINAL lzma",
                       'InstallDir "$LOCALAPPDATA\\Programs\\Helestron"', '!include "MUI2.nsh"',
                       '!insertmacro MUI_LANGUAGE "PortugueseBR"', "ManifestDPIAware true"):
            self.assertIn(trecho, self.script)
        for chave in ("ICONE", "BOAS_VINDAS", "CABECALHO"):
            self.assertNotIn(f"@{chave}@", self.script)
        self.assertIn((RECURSOS / "helestron.ico").resolve().as_posix(), self.script)
        self.assertIn((RECURSOS / "instalador-boas-vindas.bmp").resolve().as_posix(), self.script)

    def test_paginas(self):
        posicoes = [self.script.index(f"!insertmacro MUI_PAGE_{p}\n")
                    for p in ("WELCOME", "DIRECTORY", "COMPONENTS", "INSTFILES", "FINISH")]
        self.assertEqual(posicoes, sorted(posicoes))
        self.assertIn('!define MUI_FINISHPAGE_RUN_TEXT "Abrir o Helestron"', self.script)
        self.assertIn("!insertmacro MUI_UNPAGE_CONFIRM", self.script)
        self.assertIn("!insertmacro MUI_UNPAGE_INSTFILES", self.script)
        self.assertIn('MUI_WELCOMEFINISHPAGE_BITMAP', self.script)
        self.assertIn('MUI_HEADERIMAGE_BITMAP', self.script)

    def test_secoes_e_atalhos(self):
        self.assertRegex(self.script, r'Section "Helestron \(programa\)" SecPrograma\n\s+SectionIn RO')
        self.assertIn('Section "Atalho na Área de Trabalho" SecAtalho', self.script)
        self.assertNotIn('Section /o "Atalho', self.script)        # marcada por padrão
        self.assertRegex(self.script, r'CreateShortcut "\$SMPROGRAMS\\Helestron\.lnk" "\$INSTDIR\\\$\{EXE\}" "" '
                                      r'"\$INSTDIR\\\$\{EXE\}" 0')
        self.assertRegex(self.script, r'CreateShortcut "\$DESKTOP\\Helestron\.lnk" "\$INSTDIR\\\$\{EXE\}" "" '
                                      r'"\$INSTDIR\\\$\{EXE\}" 0')

    def test_registro_de_desinstalacao(self):
        self.assertIn('!define CHAVE_DESINSTALAR "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Helestron"',
                      self.script)
        for valor in ("DisplayName", "DisplayVersion", "DisplayIcon", "Publisher", "InstallLocation",
                      "UninstallString", "QuietUninstallString"):
            self.assertIn(f'WriteRegStr HKCU "${{CHAVE_DESINSTALAR}}" "{valor}"', self.script)
        tamanho = re.search(r'"EstimatedSize" (\d+)', self.script)
        self.assertIsNotNone(tamanho)
        self.assertGreater(int(tamanho.group(1)), 0)
        self.assertNotIn("HKLM", self.script)
        self.assertIn('DeleteRegKey HKCU "${CHAVE_DESINSTALAR}"', self.script)
        self.assertIn('WriteUninstaller "$INSTDIR\\${DESINSTALADOR}"', self.script)

    def test_fecha_o_programa_antes_de_copiar_e_confere_no_fim(self):
        secao = self.script[self.script.index('Section "Helestron (programa)"'):]
        self.assertLess(secao.index("Call FecharHelestron"), secao.index("File /r"))
        self.assertLess(secao.index("Call EsperarArquivosLivres"), secao.index("File /r"))
        self.assertLess(secao.index("Call LiberarArquivos"), secao.index("Call RemoverPrograma"))
        self.assertLess(secao.index("Call RemoverPrograma"), secao.index("File /r"))
        # a lista do que vai ser copiado chega antes da cópia: uma cópia
        # interrompida ainda é reconhecida (e removida) pela próxima instalação
        self.assertLess(secao.index('!insertmacro ExtrairRegistro "$INSTDIR\\${REGISTRO}"'),
                        secao.index("File /r"))
        self.assertIn("--encerrar", self.script)
        conferir = self.script[self.script.index('Section "-Conferir a instalação"'):]
        self.assertIn('--verificar-instalacao --relatorio "${RELATORIO}"', conferir)
        self.assertIn("SetErrorLevel 2", conferir)
        self.assertIn("/SD IDNO", conferir)               # o modo silencioso não para em pergunta

    def test_remover_programa_so_pela_lista_da_instalacao(self):
        """A atualização e a desinstalação apagavam com RMDir /r as pastas da
        raiz do programa e mais Scripts, share, tcl, include e libs: numa pasta
        que não era só do Helestron, levavam as do usuário (e o que ele
        tivesse posto em Lib ou em modelos)."""
        self.assertIn('!define REGISTRO "arquivos-instalados.txt"', self.script)
        funcao = self.script[self.script.index("Function ${UN}RemoverPrograma"):]
        funcao = funcao[:funcao.index("FunctionEnd")]
        self.assertIn('FileReadUTF16LE $0 $1', funcao)
        self.assertIn('Call ${UN}RemoverArquivo', funcao)
        self.assertIn('RMDir "$INSTDIR\\$1"', funcao)                 # a pasta só sai vazia
        # sem a lista (instalação de antes dela), a desta versão
        self.assertIn('!insertmacro ExtrairRegistro "$PLUGINSDIR\\${REGISTRO}"', funcao)
        self.assertIn(f'File "/oname=${{DESTINO}}" "{(self.tmp / "arquivos-instalados.txt").resolve().as_posix()}"',
                      self.script)
        # nenhuma pasta por nome: os únicos RMDir /r são a .antigos, as
        # __pycache__ da lista, a pasta de dados do Helestron (com o sim do
        # usuário) e nunca $INSTDIR inteira
        recursivos = sorted(set(re.findall(r'RMDir /r "([^"]+)"', self.script)))
        self.assertEqual(recursivos, ["$INSTDIR\\$1", "$LOCALAPPDATA\\Helestron", "${PASTA_ANTIGOS}"])
        self.assertIn('${If} $2 == "\\__pycache__"\n          RMDir /r "$INSTDIR\\$1"', funcao)
        for nome in ("Scripts", "share", "tcl", "include", "libs", "Lib", "DLLs", "modelos"):
            self.assertNotIn(f'"$INSTDIR\\{nome}"', self.script)
        self.assertFalse(hasattr(construcao, "LEGADO_RAIZ"))
        # a remoção só acontece numa pasta que já era do Helestron
        secao = self.script[self.script.index('Section "Helestron (programa)"'):]
        self.assertRegex(secao, r'\$\{If\} \$EraDoHelestron == 1\n\s+RMDir /r "\$\{PASTA_ANTIGOS\}"'
                                r'\n\s+Call LiberarArquivos\n(?:.*\n){2}\s+Call RemoverPrograma')

    def test_pasta_com_outras_coisas_recebe_o_helestron_numa_subpasta(self):
        self.assertIn("!define PASTA_OCUPADA 3", self.script)
        destino = self.script[self.script.index("Function ConferirDestino"):]
        destino = destino[:destino.index("FunctionEnd")]
        for trecho in ("Call EhDoHelestron", "Call PastaVazia", 'StrCpy $R0 "$R0\\Helestron"',
                       "StrCpy $INSTDIR $R0", '"recusada"', '"ajustada"', '"atualizacao"', '"nova"'):
            self.assertIn(trecho, destino)
        # o manifesto de outro programa não conta: só o do Helestron
        eh = self.script[self.script.index("Function EhDoHelestron"):]
        eh = eh[:eh.index("FunctionEnd")]
        self.assertIn("""${If} $R2 S== '"nome": "Helestron"'""", eh)
        self.assertIn('${If} $R2 S== "Helestron "', eh)
        # na página (com a pergunta) e na seção (o /S com /D=), antes de gravar
        pagina = self.script[self.script.index("Function ConferirPasta"):]
        pagina = pagina[:pagina.index("FunctionEnd")]
        self.assertLess(pagina.index("Call ConferirDestino"), pagina.index("Call PodeGravarNaPasta"))
        self.assertIn("MB_OKCANCEL", pagina)
        # o NSIS relê a pasta do campo depois da função: sem isto, a pasta própria se perdia
        self.assertIn('SendMessage $1 ${WM_SETTEXT} 0 "STR:$INSTDIR"', pagina)
        secao = self.script[self.script.index('Section "Helestron (programa)"'):]
        self.assertLess(secao.index("Call ConferirDestino"), secao.index("Call PodeGravarNaPasta"))
        self.assertLess(secao.index("SetErrorLevel ${PASTA_OCUPADA}"), secao.index("File /r"))
        self.assertIn("3 = a pasta escolhida", self.script)

    def test_restos_do_assessor_integrado(self):
        """O atalho "Assessor Integrado" da versão anterior ficava na Área de
        Trabalho e no Menu Iniciar, e os conectores dela no Claude Desktop."""
        secao = self.script[self.script.index('Section "Helestron (programa)"'):]
        secao = secao[:secao.index("SectionEnd")]
        self.assertIn('Push "$DESKTOP\\Assessor Integrado.lnk"\n  Call ApagarAtalhoAntigo', secao)
        self.assertIn('Push "$SMPROGRAMS\\Assessor Integrado.lnk"\n  Call ApagarAtalhoAntigo', secao)
        atalho = self.script[self.script.index("Function ApagarAtalhoAntigo"):]
        atalho = atalho[:atalho.index("FunctionEnd")]
        # só o atalho que é mesmo da versão anterior
        self.assertIn('${If} $R1 == "\\runtime\\python\\pythonw.exe"', atalho)
        self.assertIn('${AndIf} $R2 == "\\iniciar.pyw"', atalho)
        self.assertLess(atalho.index("$R2 == \"\\iniciar.pyw\""), atalho.index('Delete "$R0"'))
        # a limpeza dos conectores: num processo à parte, sem console e sem esperar
        chamada = re.search(r"Exec '\"\$INSTDIR\\pythonw\.exe\" -I -c \"from helestron\.compartilhar "
                            r"import (\w+); (\w+)\.(\w+)\(\)\"'", secao)
        self.assertIsNotNone(chamada)
        self.assertNotIn("ExecWait '\"$INSTDIR\\pythonw.exe", secao)
        modulo, mesmo, funcao = chamada.groups()
        self.assertEqual(modulo, mesmo)
        # o nome confere com o do programa
        import importlib

        programa = importlib.import_module(f"helestron.compartilhar.{modulo}")
        self.assertTrue(callable(getattr(programa, funcao)), funcao)
        self.assertEqual(funcao, "limpar_restos_antigos")

    def test_pagina_concluir_sem_cortar_o_texto(self):
        """Com a caixa "Abrir o Helestron", o MUI2 dava ao texto 40 unidades
        (5 linhas) e cortava o terceiro parágrafo; as unidades acompanham a
        fonte, e a conta de linhas vale em 100 % e em 125 %."""
        texto = re.search(r'!define MUI_FINISHPAGE_TEXT "([^"]*)"', self.script).group(1)
        altura = 60 if "!define MUI_FINISHPAGE_TEXT_LARGE" in self.script else 40
        linhas_que_cabem = altura // 8                  # 8 unidades por linha da fonte
        # 195 unidades de largura: ~48 caracteres médios; 44 por linha deixa folga
        paragrafos = texto.split("$\\r$\\n")
        linhas = sum(max(1, -(-len(p) // 44)) for p in paragrafos)
        self.assertLessEqual(linhas, linhas_que_cabem - 1, paragrafos)
        self.assertIn("Ajustes", texto)

    def test_desinstalador_pergunta_e_preserva_documentos(self):
        desinstalar = self.script[self.script.index('Section "Uninstall"'):]
        self.assertIn("MB_DEFBUTTON2", desinstalar)        # o padrão é NÃO apagar
        self.assertIn("/SD IDNO", desinstalar)
        self.assertIn('RMDir /r "$LOCALAPPDATA\\Helestron"', desinstalar)
        self.assertLess(desinstalar.index("MessageBox"), desinstalar.index('RMDir /r "$LOCALAPPDATA\\Helestron"'))
        self.assertNotIn("$DOCUMENTS", self.script)
        self.assertNotRegex(self.script, r"(?i)RMDir[^\n]*Documentos")
        self.assertIn('Delete "$SMPROGRAMS\\Helestron.lnk"', desinstalar)
        self.assertIn('Delete "$DESKTOP\\Helestron.lnk"', desinstalar)
        self.assertIn("claude.remover_mcp()", desinstalar)
        # o conector do Codex/ChatGPT Work também (config.toml), num processo à parte
        self.assertIn("chatgpt.remover_mcp_codex()", desinstalar)
        self.assertNotIn("claude, chatgpt", desinstalar)
        self.assertIn('RMDir "$INSTDIR"', desinstalar)       # só se ficou vazia

    def test_audiencia_em_andamento_nao_e_cortada(self):
        funcao = self.script[self.script.index("Function ${UN}FecharHelestron"):]
        funcao = funcao[:funcao.index("FunctionEnd")]
        self.assertIn('!define AUDIENCIA_EM_ANDAMENTO 10', self.script)
        self.assertIn("$0 == ${AUDIENCIA_EM_ANDAMENTO}", funcao)
        self.assertIn("/SD IDCANCEL IDRETRY tentar", funcao)     # no silencioso, desiste
        self.assertIn("SetErrorLevel 7", funcao)
        self.assertLess(funcao.index("SetErrorLevel 7"), funcao.index("Abort"))
        self.assertIn("Call un.FecharHelestron", self.script)

    def test_arquivos_presos_sao_renomeados_e_nenhum_processo_e_morto(self):
        remover = self.script[self.script.index("Function ${UN}RemoverArquivo"):]
        remover = remover[:remover.index("FunctionEnd")]
        self.assertIn('Delete "$R9"', remover)
        self.assertIn("$Afastar == 1", remover)
        self.assertIn('Rename "$R9" "$PastaAfastados\\$NumAfastados-$R7"', remover)
        self.assertIn('Rename "$INSTDIR\\python312.dll" "$PastaAfastados\\python312.dll"', self.script)
        self.assertIn("advpack.dll,DelNodeRunDLL32", self.script)
        self.assertIn("HKCU \"${CHAVE_RUNONCE}\"", self.script)
        for proibido in ("taskkill", "TerminateProcess", "KillProcess", "wmic"):
            self.assertNotIn(proibido, self.script)

    def test_pasta_sem_permissao(self):
        paginas = self.script[:self.script.index("!insertmacro MUI_PAGE_DIRECTORY")]
        self.assertTrue(paginas.rstrip().endswith("!define MUI_PAGE_CUSTOMFUNCTION_LEAVE ConferirPasta"))
        secao = self.script[self.script.index('Section "Helestron (programa)"'):]
        self.assertLess(secao.index("Call PodeGravarNaPasta"), secao.index("Call FecharHelestron"))
        self.assertIn("SetErrorLevel 8", secao)
        erro_arquivo = re.search(r'LangString \^FileError \$\{LANG_PORTUGUESEBR\} "([^"]+)"', self.script)
        self.assertIn("administrador", erro_arquivo.group(1))

    def test_sem_janela_tem_codigo_e_mensagem_proprios(self):
        conferir = self.script[self.script.index('Section "-Conferir a instalação"'):]
        self.assertIn("!define SEM_JANELA 9", self.script)
        self.assertIn("$0 == ${SEM_JANELA}", conferir)
        self.assertIn("SetErrorLevel 9", conferir)
        self.assertIn("WebView2 Runtime", conferir)

    def test_textos_em_portugues_correto(self):
        # o arquivo de idioma do NSIS usa "pra"; todos os textos visíveis são nossos
        visivel = "\n".join(linha for linha in self.script.splitlines()
                             if not linha.lstrip().startswith(";"))
        self.assertIsNone(re.search(r"\bpra\b", visivel))
        for chave in ("^ClickNext", "^ClickInstall", "^Completed", "^FileError"):
            self.assertIn(f"LangString {chave} ${{LANG_PORTUGUESEBR}}", self.script)

    # Os botões das caixas de mensagem vêm do Windows, no idioma dele. Em
    # português do Brasil (user32), IDABORT é “Anular” — o Wine, o ReactOS e o
    # PortugueseBR.nlf do NSIS dizem “Abortar”, e o teste no Wine não pegaria.
    BOTOES_PT_BR = {
        "MB_OK": {"OK"}, "MB_OKCANCEL": {"OK", "Cancelar"},
        "MB_ABORTRETRYIGNORE": {"Anular", "Repetir", "Ignorar"},
        "MB_YESNOCANCEL": {"Sim", "Não", "Cancelar"}, "MB_YESNO": {"Sim", "Não"},
        "MB_RETRYCANCEL": {"Repetir", "Cancelar"},
    }

    def test_botoes_citados_com_os_nomes_do_windows_em_portugues(self):
        visivel = "\n".join(linha for linha in self.script.splitlines()
                             if not linha.lstrip().startswith(";"))
        self.assertEqual(re.findall(r".{0,40}Abortar.{0,30}", visivel), [])
        caixas = []
        for m in re.finditer(r'^\s*MessageBox (\S+) "([^"]*)"', visivel, re.M):
            tipo = next(f for f in m.group(1).split("|") if f in self.BOTOES_PT_BR)
            caixas.append((tipo, m.group(2)))
        # as falhas de gravação do NSIS: ^FileError numa caixa de Anular, Repetir
        # e Ignorar; ^FileError_NoIgnore, numa de Repetir e Cancelar
        for chave, tipo in (("^FileError", "MB_ABORTRETRYIGNORE"),
                            ("^FileError_NoIgnore", "MB_RETRYCANCEL")):
            m = re.search(rf'^LangString {re.escape(chave)} \S+ "(.*)"$', visivel, re.M)
            caixas.append((tipo, m.group(1)))
        self.assertGreaterEqual(len(caixas), 10)
        citado = r"(?:[Cc]lique em|[Rr]esponda|botão) (Abortar|Anular|Repetir|Ignorar|Cancelar|Sim|Não|OK)\b"
        no_inicio = r"(?:^|[.:!?] |\$\\n)(Abortar|Anular|Repetir|Ignorar|Cancelar) (?=[a-zà-ú])"
        for tipo, texto in caixas:
            citados = set(re.findall(citado, texto)) | set(re.findall(no_inicio, texto))
            with self.subTest(tipo=tipo, texto=texto[:70]):
                self.assertLessEqual(citados, self.BOTOES_PT_BR[tipo])
        textos = dict((t, x) for t, x in caixas[-2:])
        for botao in ("Anular", "Repetir", "Ignorar"):
            self.assertIn(botao, textos["MB_ABORTRETRYIGNORE"])
        for botao in ("Repetir", "Cancelar"):
            self.assertIn(botao, textos["MB_RETRYCANCEL"])

    @unittest.skipUnless(MAKENSIS, "makensis ausente")
    def test_compila_com_o_makensis(self):
        script = self.tmp / "helestron.nsi"
        # compressão rápida: o que se testa é o script, não o LZMA
        rapido = self.script.replace("SetCompressor /SOLID /FINAL lzma", "SetCompressor /FINAL zlib")
        script.write_text(rapido.replace("SetCompressorDictSize 64\n", ""), encoding="utf-8")
        self.saida.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([MAKENSIS, "-V2", "-INPUTCHARSET", "UTF8", str(script)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("warning", (r.stdout + r.stderr).lower())
        self.assertTrue(self.saida.is_file())
        self.assertEqual(self.saida.read_bytes()[:2], b"MZ")


# ============================================================ instalador no Wine
_STUB_C = r"""
/* Helestron.exe e python.exe falsos: registram a chamada em chamadas.txt e
   saem com o código de encerrar-codigo.txt / verificar-codigo.txt. */
#include <windows.h>
#include <stdio.h>
#include <wchar.h>
static int codigo_de(const wchar_t *pasta, const wchar_t *nome) {
    wchar_t caminho[1024]; swprintf(caminho, 1024, L"%ls%ls", pasta, nome);
    FILE *f = _wfopen(caminho, L"r"); int c = 0;
    if (!f) return 0;
    if (fscanf(f, "%d", &c) != 1) c = 0;
    fclose(f); return c;
}
int wmain(int argc, wchar_t **argv) {
    wchar_t pasta[1024], exe[1024], registro[1024];
    GetModuleFileNameW(NULL, exe, 1024); wcscpy(pasta, exe);
    wchar_t *barra = wcsrchr(pasta, L'\\'); if (barra) barra[1] = 0;
    swprintf(registro, 1024, L"%lschamadas.txt", pasta);
    FILE *r = _wfopen(registro, L"a");
    if (r) {
        fwprintf(r, L"%ls", wcsrchr(exe, L'\\') + 1);
        for (int i = 1; i < argc; i++) fwprintf(r, L" %ls", argv[i]);
        fwprintf(r, L"\n"); fclose(r);
    }
    for (int i = 1; i < argc; i++) {
        if (wcscmp(argv[i], L"--encerrar") == 0) return codigo_de(pasta, L"encerrar-codigo.txt");
        if (wcscmp(argv[i], L"--verificar-instalacao") == 0) return codigo_de(pasta, L"verificar-codigo.txt");
    }
    return 0;
}
"""
_DLL_C = r"""
#include <windows.h>
BOOL WINAPI DllMain(HINSTANCE h, DWORD m, LPVOID r) { (void)h; (void)m; (void)r; return TRUE; }
"""
_SEGURAR_C = r"""
/* O "servidor MCP do Claude Desktop": carrega os DLLs (como o python.exe
   carrega o python312.dll e os .pyd) e fica vivo enquanto o arquivo-sinal existir. */
#include <windows.h>
#include <stdio.h>
int wmain(int argc, wchar_t **argv) {
    for (int i = 2; i < argc; i++) if (!LoadLibraryW(argv[i])) return 2;
    FILE *f = _wfopen(argv[1], L"w"); if (f) { fputs("vivo", f); fclose(f); }
    for (int i = 0; i < 1200; i++) {
        Sleep(100);
        if (GetFileAttributesW(argv[1]) == INVALID_FILE_ATTRIBUTES) return 0;
    }
    return 0;
}
"""

_RODAR_C = r"""
/* rodar.exe: roda, crua, a linha de comando de RODAR_LINHA e devolve o código
   dela. O /D= do NSIS tem de ser o último argumento e SEM aspas, mesmo com
   espaço no caminho - e o Wine põe aspas no argumento com espaço. */
#include <windows.h>
int wmain(void) {
    static wchar_t linha[8192];
    if (!GetEnvironmentVariableW(L"RODAR_LINHA", linha, 8192)) return 99;
    STARTUPINFOW si = { sizeof(si) }; PROCESS_INFORMATION pi;
    if (!CreateProcessW(NULL, linha, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) return 98;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD c = 0; GetExitCodeProcess(pi.hProcess, &c); return (int)c;
}
"""
_ATALHOS_NSI = r"""
Target amd64-unicode
RequestExecutionLevel user
SilentInstall silent
OutFile "atalhos.exe"
Section
  SetShellVarContext current
  CreateDirectory "$SMPROGRAMS"
  CreateShortcut "$DESKTOP\Assessor Integrado.lnk" "C:\Assessor Antigo\runtime\python\pythonw.exe" '-E -s "C:\Assessor Antigo\iniciar.pyw"'
  CreateShortcut "$SMPROGRAMS\Assessor Integrado.lnk" "C:\Outro\runtime\python\pythonw.exe" '-E -s "C:\Outro\outro.pyw"'
SectionEnd
"""


@unittest.skipUnless(MAKENSIS and MINGW and WINE64,
                     "precisa do makensis, do MinGW-w64 e do Wine de 64 bits")
class TestInstaladorNoWine(unittest.TestCase):
    """O helestron.nsi de verdade (alvo amd64, compressão rápida), com um
    programa falso, instalado e desinstalado em silêncio (/S) no Wine."""

    ALVO_WIN = r"C:\TesteArea\Helestron"

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="helestron-wine-"))
        casa = cls.tmp / "casa"
        casa.mkdir()
        # HOME próprio (o Wine grava em ~/.cache e ~/.local); sem menus do Linux
        cls.env = dict(os.environ, WINEPREFIX=str(cls.tmp / "prefixo"), WINEDEBUG="-all",
                       HOME=str(casa), XDG_DATA_HOME=str(casa / "dados"),
                       XDG_CONFIG_HOME=str(casa / "config"), XDG_CACHE_HOME=str(casa / "cache"),
                       WINEDLLOVERRIDES="mscoree,mshtml=;winemenubuilder.exe=d;winedbg.exe=d")
        fontes = cls.tmp / "fontes"
        fontes.mkdir()
        gcc = shutil.which("x86_64-w64-mingw32-gcc")
        for nome, codigo, opcoes, saida in (("stub.c", _STUB_C, ["-municode"], "stub.exe"),
                                            ("dll.c", _DLL_C, ["-shared"], "falso.dll"),
                                            ("segurar.c", _SEGURAR_C, ["-municode"], "segurar.exe"),
                                            ("rodar.c", _RODAR_C, ["-municode"], "rodar.exe")):
            (fontes / nome).write_text(codigo, encoding="utf-8")
            subprocess.run([gcc, *opcoes, "-O2", "-s", "-o", str(fontes / saida), str(fontes / nome)],
                           check=True, capture_output=True)
        cls.segurar = fontes / "segurar.exe"
        cls.rodar = fontes / "rodar.exe"
        arvore = cls.tmp / "obra" / "Helestron"
        (arvore / "Lib" / "site-packages" / "helestron").mkdir(parents=True)
        (arvore / "DLLs").mkdir()
        shutil.copy(fontes / "stub.exe", arvore / "Helestron.exe")
        shutil.copy(fontes / "stub.exe", arvore / "python.exe")
        shutil.copy(fontes / "falso.dll", arvore / "python312.dll")
        shutil.copy(fontes / "falso.dll", arvore / "DLLs" / "_socket.pyd")
        shutil.copy(fontes / "stub.exe", arvore / "pythonw.exe")
        (arvore / "Lib" / "os.py").write_text("# os\n", encoding="utf-8")
        (arvore / "Lib" / "velho.py").write_text("# só nesta versão\n", encoding="utf-8")
        (arvore / "Lib" / "site-packages" / "helestron" / "__init__.py").write_text("# h\n")
        (arvore / "Lib" / "site-packages" / "helestron" / "__pycache__").mkdir()
        (arvore / "Lib" / "site-packages" / "helestron" / "__pycache__" / "__init__.cpython-312.pyc").write_bytes(b"pyc")
        (arvore / "modelos" / "faster-whisper-small").mkdir(parents=True)
        (arvore / "modelos" / "faster-whisper-small" / "model.bin").write_bytes(b"\0" * 32)
        construcao.gerar_manifesto(arvore, "1.0.0")
        cls.setup = cls._compilar(arvore, "1.0.0")
        # a versão seguinte: sem o Lib\velho.py, com o Lib\novo.py
        arvore2 = cls.tmp / "obra2" / "Helestron"
        shutil.copytree(arvore, arvore2)
        (arvore2 / "Lib" / "velho.py").unlink()
        (arvore2 / "Lib" / "novo.py").write_text("# novo\n", encoding="utf-8")
        construcao.gerar_manifesto(arvore2, "1.0.1")
        cls.setup2 = cls._compilar(arvore2, "1.0.1")
        # os atalhos "Assessor Integrado": o da versão anterior (o pythonw do
        # runtime dela, com o iniciar.pyw) e um de mesmo nome que não é dela
        (fontes / "atalhos.nsi").write_text(_ATALHOS_NSI, encoding="utf-8")
        r = subprocess.run([MAKENSIS, "-V2", "-INPUTCHARSET", "UTF8", str(fontes / "atalhos.nsi")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        cls.atalhos = fontes / "atalhos.exe"
        subprocess.run([WINE64, "wineboot", "-i"], env=cls.env, capture_output=True, timeout=300)
        cls.c = cls.tmp / "prefixo" / "drive_c"
        cls.alvo = cls.c / "TesteArea" / "Helestron"

    @classmethod
    def _compilar(cls, arvore: Path, versao: str) -> Path:
        setup = arvore.parent / f"Helestron-Setup-{versao}.exe"
        script = construcao.script_nsis(arvore, versao, setup, RECURSOS)
        script = script.replace("Unicode true", "Target amd64-unicode")
        script = script.replace("SetCompressor /SOLID /FINAL lzma", "SetCompressor /FINAL zlib")
        script = script.replace("SetCompressorDictSize 64\n", "")
        (arvore.parent / "h.nsi").write_text(script, encoding="utf-8")
        r = subprocess.run([MAKENSIS, "-V2", "-INPUTCHARSET", "UTF8", str(arvore.parent / "h.nsi")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        return setup

    @classmethod
    def tearDownClass(cls):
        subprocess.run([str(Path(WINE64).with_name("wineserver")), "-k"], env=cls.env,
                       capture_output=True, timeout=60)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def wine(self, *args, espera=240) -> int:
        # sem pipe: um processo do Wine que o herde seguraria o fim da leitura
        return subprocess.run([WINE64, *map(str, args)], env=self.env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=espera).returncode

    def instalar(self, destino: str | None = None, setup: Path | None = None) -> int:
        setup_win = "Z:" + str(setup or self.setup).replace("/", "\\")
        linha = f'"{setup_win}" /S /D={destino or self.ALVO_WIN}'
        return subprocess.run([WINE64, str(self.rodar)], env=dict(self.env, RODAR_LINHA=linha),
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=240).returncode

    def desinstalar(self, pasta: Path) -> None:
        """Desinstalar.exe /S: ele se copia para a pasta temporária e segue de lá."""
        self.wine(pasta / "Desinstalar.exe", "/S")
        limite = time.monotonic() + 60
        while ((pasta / "Desinstalar.exe").exists() or (pasta / "arquivos-instalados.txt").exists()) \
                and time.monotonic() < limite:
            time.sleep(0.2)
        time.sleep(1)

    def local_instalado(self) -> str:
        saida = subprocess.run([WINE64, "reg", "query",
                                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Helestron",
                                "/v", "InstallLocation"], env=self.env, capture_output=True,
                               text=True, timeout=60).stdout
        achado = re.search(r"InstallLocation\s+REG_SZ\s+(.+?)\s*$", saida, re.M)
        return achado.group(1) if achado else ""

    @staticmethod
    def conteudo(pasta: Path) -> dict[str, bytes]:
        return {p.relative_to(pasta).as_posix(): p.read_bytes() for p in pasta.rglob("*") if p.is_file()}

    @staticmethod
    def registro(pasta: Path) -> list[str]:
        return (pasta / "arquivos-instalados.txt").read_bytes()[2:].decode("utf-16-le").splitlines()

    def runonce(self) -> str:
        return subprocess.run([WINE64, "reg", "query",
                               r"HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce"],
                              env=self.env, capture_output=True, text=True, timeout=60).stdout

    def setUp(self):
        shutil.rmtree(self.alvo.parent, ignore_errors=True)
        subprocess.run([WINE64, "reg", "delete",
                        r"HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce",
                        "/v", "HelestronLimpeza", "/f"], env=self.env, capture_output=True, timeout=60)
        self.assertEqual(self.instalar(), 0)
        self.assertTrue((self.alvo / "python312.dll").is_file())

    def test_audiencia_em_andamento_adia_a_atualizacao(self):
        (self.alvo / "encerrar-codigo.txt").write_text("10")
        self.assertEqual(self.instalar(), 7)
        for nome in ("Helestron.exe", "python312.dll", "manifesto.json", "Lib/os.py"):
            self.assertTrue((self.alvo / nome).exists(), nome)        # nada foi mexido

    def test_servidor_mcp_aberto_nao_trava_atualizacao_nem_desinstalacao(self):
        sinal = self.alvo / "mcp-vivo.txt"
        mcp = subprocess.Popen([WINE64, str(self.segurar), self.ALVO_WIN + r"\mcp-vivo.txt",
                                self.ALVO_WIN + r"\python312.dll", self.ALVO_WIN + r"\DLLs\_socket.pyd"],
                               env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: mcp.poll() is None and mcp.kill())
        limite = time.monotonic() + 60
        while not sinal.exists() and time.monotonic() < limite:
            time.sleep(0.2)
        self.assertTrue(sinal.exists(), "o processo que segura os DLLs não subiu")
        # atualização silenciosa: antes, código 4 depois de 20 s
        self.assertEqual(self.instalar(), 0)
        self.assertIsNone(mcp.poll(), "o instalador encerrou o processo do servidor MCP")
        afastados = [p.name for p in (self.alvo / ".antigos").rglob("*") if p.is_file()]
        self.assertIn("python312.dll", afastados)
        self.assertTrue(any(n.endswith("_socket.pyd") for n in afastados), afastados)
        self.assertTrue((self.alvo / "python312.dll").is_file())
        self.assertTrue((self.alvo / "DLLs" / "_socket.pyd").is_file())
        self.assertIn("DelNodeRunDLL32", self.runonce())
        # desinstalação silenciosa, com o servidor ainda aberto
        (self.alvo / "chamadas.txt").unlink(missing_ok=True)
        self.wine(self.alvo / "Desinstalar.exe", "/S")
        limite = time.monotonic() + 60
        while (self.alvo / "manifesto.json").exists() and time.monotonic() < limite:
            time.sleep(0.2)
        time.sleep(1)
        chamadas = (self.alvo / "chamadas.txt").read_text(encoding="utf-8", errors="replace")
        self.assertIn("claude.remover_mcp()", chamadas)
        self.assertIn("chatgpt.remover_mcp_codex()", chamadas)
        self.assertFalse((self.alvo / "python312.dll").exists())
        self.assertFalse((self.alvo / "Lib").exists())
        self.assertIsNone(mcp.poll())
        sinal.unlink()
        mcp.wait(30)

    def test_pasta_sem_permissao(self):
        self.assertEqual(self.instalar(r"Z:\proc\Helestron"), 8)

    # Os três cenários da pasta: nova (o setUp), com arquivos do usuário e a
    # atualização. Antes, a atualização e a desinstalação apagavam com RMDir /r
    # as pastas Lib, DLLs e modelos e mais Scripts, share, tcl, include e
    # libs - numa pasta que não era só do Helestron, com o que o usuário
    # tivesse dentro delas.
    def test_pasta_nova_a_desinstalacao_apaga_so_o_que_a_instalacao_pos(self):
        linhas = self.registro(self.alvo)
        self.assertTrue(linhas[0].startswith("Helestron 1.0.0 - "))
        self.assertIn("A Lib\\velho.py", linhas)
        self.assertIn("P Lib\\site-packages\\helestron\\__pycache__", linhas)
        # o usuário (ou outro programa) põe coisas dentro da pasta do programa
        do_usuario = {"Lib/minhas-notas.txt": b"notas", "modelos/contrato-modelo.docx": b"docx",
                      "Scripts/backup.bat": b"@echo off", "share/orcamento.txt": b"R$ 10"}
        for rel, dados in do_usuario.items():
            (self.alvo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.alvo / rel).write_bytes(dados)
        # um .pyc que o Python gravou depois (não está na lista): sai com a __pycache__
        (self.alvo / "Lib/site-packages/helestron/__pycache__/novo.cpython-312.pyc").write_bytes(b"pyc")
        self.desinstalar(self.alvo)
        for rel in ("Helestron.exe", "python.exe", "pythonw.exe", "python312.dll", "manifesto.json",
                    "arquivos-instalados.txt", "Desinstalar.exe", "DLLs", "Lib/os.py",
                    "Lib/site-packages", "modelos/faster-whisper-small"):
            self.assertFalse((self.alvo / rel).exists(), rel)
        sobrou = {rel: dados for rel, dados in self.conteudo(self.alvo).items() if rel != "chamadas.txt"}
        self.assertEqual(sobrou, do_usuario)

    def test_pasta_com_arquivos_do_usuario_recebe_o_helestron_numa_subpasta(self):
        pasta = self.c / "Meus Programas"
        do_usuario = {"share/orcamento.txt": b"R$ 10", "Scripts/backup.bat": b"@echo off",
                      "tcl/notas.txt": b"tcl", "include/meu.h": b"#pragma once", "libs/meu.lib": b"lib",
                      "Lib/minha-lib.txt": b"lib", "DLLs/minha.dll": b"MZ", "modelos/contrato.docx": b"docx",
                      "OutroPrograma/dados.txt": b"dados", "leia-me.txt": b"leia",
                      # o manifesto.json de outro programa não faz da pasta uma do Helestron
                      "manifesto.json": b'{\n "nome": "Outro",\n "arquivos": {}\n}\n'}
        shutil.rmtree(pasta, ignore_errors=True)
        self.addCleanup(shutil.rmtree, pasta, True)
        for rel, dados in do_usuario.items():
            (pasta / rel).parent.mkdir(parents=True, exist_ok=True)
            (pasta / rel).write_bytes(dados)
        subpasta = pasta / "Helestron"
        self.assertEqual(self.instalar(r"C:\Meus Programas"), 0)
        self.assertTrue((subpasta / "python312.dll").is_file())
        self.assertTrue((subpasta / "Lib" / "os.py").is_file())
        self.assertFalse((pasta / "python312.dll").exists())
        self.assertFalse((pasta / "Lib" / "os.py").exists())
        self.assertEqual(self.local_instalado(), r"C:\Meus Programas\Helestron")
        fora = {rel: d for rel, d in self.conteudo(pasta).items() if not rel.startswith("Helestron/")}
        self.assertEqual(fora, do_usuario)
        # a atualização (a pasta vem do registro) e a desinstalação: nada do usuário sai
        self.assertEqual(self.wine(self.setup2, "/S"), 0)
        self.assertTrue((subpasta / "Lib" / "novo.py").is_file())
        self.assertFalse((subpasta / "Lib" / "velho.py").exists())
        fora = {rel: d for rel, d in self.conteudo(pasta).items() if not rel.startswith("Helestron/")}
        self.assertEqual(fora, do_usuario)
        self.desinstalar(subpasta)
        self.assertFalse((subpasta / "python312.dll").exists())
        self.assertFalse((subpasta / "Lib").exists())
        restos = {rel for rel in self.conteudo(pasta) if rel.startswith("Helestron/")}
        self.assertLessEqual(restos, {"Helestron/chamadas.txt"})          # o registro do programa falso
        self.assertEqual({rel: d for rel, d in self.conteudo(pasta).items() if not rel.startswith("Helestron/")},
                         do_usuario)

    def test_pasta_e_subpasta_com_outras_coisas_recusa_sem_copiar(self):
        pasta = self.c / "Pasta Cheia"
        shutil.rmtree(pasta, ignore_errors=True)
        self.addCleanup(shutil.rmtree, pasta, True)
        (pasta / "Helestron").mkdir(parents=True)
        (pasta / "planilha.xlsx").write_bytes(b"xlsx")
        (pasta / "Helestron" / "outro.txt").write_bytes(b"outro")
        self.assertEqual(self.instalar(r"C:\Pasta Cheia"), 3)
        self.assertEqual(self.conteudo(pasta), {"planilha.xlsx": b"xlsx", "Helestron/outro.txt": b"outro"})

    def test_atualizacao_apaga_so_o_que_a_versao_anterior_instalou(self):
        do_usuario = {"Lib/minhas-notas.txt": b"notas", "Scripts/backup.bat": b"@echo off"}
        for rel, dados in do_usuario.items():
            (self.alvo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.alvo / rel).write_bytes(dados)
        self.assertEqual(self.instalar(setup=self.setup2), 0)
        self.assertFalse((self.alvo / "Lib" / "velho.py").exists())       # só a 1.0.0 tinha
        self.assertTrue((self.alvo / "Lib" / "novo.py").is_file())
        self.assertTrue(self.registro(self.alvo)[0].startswith("Helestron 1.0.1 - "))
        self.assertIn("A Lib\\novo.py", self.registro(self.alvo))
        for rel, dados in do_usuario.items():
            self.assertEqual((self.alvo / rel).read_bytes(), dados, rel)
        # uma instalação de antes da lista (só com o manifesto do Helestron):
        # vale a lista da versão que chega, arquivo por arquivo
        (self.alvo / "arquivos-instalados.txt").unlink()
        self.assertEqual(self.instalar(), 0)
        self.assertTrue(self.registro(self.alvo)[0].startswith("Helestron 1.0.0 - "))
        self.assertTrue((self.alvo / "Lib" / "velho.py").is_file())
        for rel, dados in do_usuario.items():
            self.assertEqual((self.alvo / rel).read_bytes(), dados, rel)

    def test_restos_do_assessor_integrado(self):
        self.assertEqual(self.wine(self.atalhos), 0)
        antigo = next(self.c.glob("users/*/Desktop/Assessor Integrado.lnk"))
        outro = next(self.c.glob("users/*/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/"
                                 "Assessor Integrado.lnk"))
        (self.alvo / "chamadas.txt").unlink(missing_ok=True)
        self.assertEqual(self.instalar(), 0)
        self.assertFalse(antigo.exists(), "o atalho da versão anterior ficou")
        self.assertTrue(outro.exists(), "apagou um atalho que não é da versão anterior")
        # a limpeza dos conectores antigos, num processo à parte (sem esperar por ele)
        limite = time.monotonic() + 30
        chamadas = ""
        while "limpar_restos_antigos" not in chamadas and time.monotonic() < limite:
            time.sleep(0.3)
            chamadas = (self.alvo / "chamadas.txt").read_text(encoding="utf-8", errors="replace") \
                if (self.alvo / "chamadas.txt").exists() else ""
        self.assertIn("pythonw.exe -I -c from helestron.compartilhar import migracao; "
                      "migracao.limpar_restos_antigos()", chamadas)

    def test_sem_como_abrir_a_janela(self):
        (self.alvo / "verificar-codigo.txt").write_text("9")
        self.assertEqual(self.instalar(), 9)
        (self.alvo / "verificar-codigo.txt").write_text("1")
        self.assertEqual(self.instalar(), 2)


# =================================================================== lançador
class TestLancador(unittest.TestCase):
    def setUp(self):
        self.fonte = (CONSTRUIR / "lancador" / "helestron.c").read_text(encoding="utf-8")

    def test_fonte_chama_o_python_isolado(self):
        self.assertRegex(self.fonte, r'L"-I";\s*\n\s*novo\[n\+\+\] = L"-m";\s*\n\s*novo\[n\+\+\] = L"helestron";')
        self.assertIn('#define NOME_DLL L"python312.dll"', self.fonte)
        self.assertIn("LoadLibraryExW", self.fonte)
        self.assertIn('GetProcAddress(python, "Py_Main")', self.fonte)
        self.assertIn("MessageBoxW", self.fonte)
        self.assertIn("int WINAPI wWinMain", self.fonte)
        # a mensagem própria, em português, quando falta o DLL
        self.assertIn("Falta o arquivo %ls na pasta do programa", self.fonte)
        self.assertIn("reinstale o Helestron com o Helestron-Setup", self.fonte)
        self.assertIn("antivírus", self.fonte)
        # o instalador nunca fica preso numa caixa de mensagem
        self.assertIn('L"--encerrar"', self.fonte)
        self.assertIn('L"--verificar-instalacao"', self.fonte)

    def test_rc_e_manifesto(self):
        rc = (CONSTRUIR / "lancador" / "helestron.rc").read_text(encoding="utf-8")
        self.assertIn('1 ICON "helestron.ico"', rc)
        self.assertIn("VS_VERSION_INFO VERSIONINFO", rc)
        self.assertIn('"helestron.manifest"', rc)
        self.assertIn("RT_MANIFEST_HELESTRON 24", rc)
        valores = {"VERSAO": "1.0.0", "VERSAO_WIN": "1.0.0.0", "VERSAO_VIRGULAS": "1,0,0,0", "ANO": "2026"}
        renderizado = construcao.renderizar(rc, valores)
        self.assertIn("FILEVERSION     1,0,0,0", renderizado)
        self.assertNotRegex(renderizado, r"@[A-Z_]+@")
        manifesto = construcao.sem_comentarios_xml(construcao.renderizar(
            (CONSTRUIR / "lancador" / "helestron.manifest").read_text(encoding="utf-8"), valores))
        self.assertNotIn("<!--", manifesto)
        raiz = ET.fromstring(manifesto.encode("utf-8"))
        texto = ET.tostring(raiz, encoding="unicode")
        self.assertIn("PerMonitorV2", texto)
        self.assertIn("longPathAware", texto)
        self.assertIn("asInvoker", texto)
        self.assertIn("{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}", texto)     # Windows 10/11
        self.assertIn('version="1.0.0.0"', manifesto)

    def test_renderizar_recusa_marcador_sem_valor(self):
        with self.assertRaises(construcao.ErroConstrucao):
            construcao.renderizar("@VERSAO@ @OUTRO@", {"VERSAO": "1"})

    def _objdump(self, dlls=("KERNEL32.dll", "USER32.dll", "msvcrt.dll"), subsistema="00000002",
                 magic="020b") -> str:
        linhas = [f"Magic\t\t\t{magic}\t(PE32+)", f"Subsystem\t\t{subsistema}\t(Windows GUI)"]
        for dll in dlls:
            linhas.append(f"\tDLL Name: {dll}")
        linhas += ["\t8448	  742  GetProcAddress", "\t848e	  988  LoadLibraryExW"]
        return "\n".join(linhas)

    def _binario(self) -> bytes:
        return (b"Py_Main\0" + "-I\0helestron".encode("utf-16-le") + b"PerMonitorV2 longPathAware"
                + "ProductVersion".encode("utf-16-le"))

    def test_conferir_lancador(self):
        construcao.conferir_lancador(self._objdump(), self._binario())
        casos = [
            (self._objdump(subsistema="00000003"), "console"),
            (self._objdump(dlls=("KERNEL32.dll", "python312.dll")), "DLL do Python"),
            (self._objdump(magic="010b"), "64 bits"),
        ]
        for objdump, trecho in casos:
            with self.assertRaises(construcao.ErroConstrucao) as ctx:
                construcao.conferir_lancador(objdump, self._binario())
            self.assertIn(trecho, str(ctx.exception))
        with self.assertRaises(construcao.ErroConstrucao):
            construcao.conferir_lancador(self._objdump(), b"sem nada")

    @unittest.skipUnless(MINGW, "MinGW-w64 ausente")
    def test_compila_com_o_mingw(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        exe = construcao.compilar_lancador("1.0.0", tmp, RECURSOS / "helestron.ico")   # já confere
        dados = exe.read_bytes()
        self.assertEqual(dados[:2], b"MZ")
        self.assertIn("1.0.0".encode("utf-16-le"), dados)
        # o ícone inteiro (a maior imagem, PNG de 256 px) foi para dentro do executável
        self.assertIn(b"\x89PNG", dados)


_PYTHON_FALSO_C = r"""
/* python312.dll falso: o Py_Main anota os argumentos em py_main.txt e faz o
   que FALSO_MODO pede - sair com aquele código, ou mostrar uma janela por meio
   segundo e sair com 1. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
__declspec(dllexport) int Py_Main(int argc, wchar_t **argv) {
    wchar_t modo[64] = L"0", caminho[1024];
    GetEnvironmentVariableW(L"FALSO_MODO", modo, 64);
    GetModuleFileNameW(NULL, caminho, 1024);
    wchar_t *barra = wcsrchr(caminho, L'\\'); if (barra) barra[1] = 0;
    wcscat(caminho, L"py_main.txt");
    FILE *f = _wfopen(caminho, L"a");
    if (f) { for (int i = 1; i < argc; i++) fwprintf(f, L"%ls ", argv[i]); fwprintf(f, L"\n"); fclose(f); }
    if (wcscmp(modo, L"janela") == 0) {
        HWND j = CreateWindowExW(0, L"STATIC", L"Janela do programa", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                 10, 10, 300, 200, NULL, NULL, NULL, NULL);
        DWORD fim = GetTickCount() + 500; MSG m;
        while (GetTickCount() < fim) {
            while (PeekMessageW(&m, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&m);
            Sleep(20);
        }
        DestroyWindow(j);
        return 1;
    }
    return _wtoi(modo);
}
"""


def _texto_do_trace(linha: str) -> str:
    """O texto de 'trace:msgbox:MSGBOX_OnInit L"..."' (o debugstr_w do Wine)."""
    bruto = linha.split('L"', 1)[1].rsplit('"', 1)[0]
    saida, i = [], 0
    while i < len(bruto):
        c = bruto[i]
        if c == "\\" and i + 1 < len(bruto):
            seguinte = bruto[i + 1]
            if seguinte in "0123456789abcdef" and re.fullmatch(r"[0-9a-f]{4}", bruto[i + 1:i + 5] or ""):
                saida.append(chr(int(bruto[i + 1:i + 5], 16)))
                i += 5
                continue
            saida.append({"n": "\n", "r": "\r", "t": "\t"}.get(seguinte, seguinte))
            i += 2
            continue
        saida.append(c)
        i += 1
    return "".join(saida)


@unittest.skipUnless(MINGW and WINE64 and os.environ.get("DISPLAY"),
                     "precisa do MinGW-w64, do Wine de 64 bits e de uma tela (xvfb-run)")
class TestLancadorNoWine(unittest.TestCase):
    """O Helestron.exe de verdade, com um python312.dll falso, no Wine. Antes,
    sem o __main__.py, o registro.py, o caminhos.py ou o Lib\\encodings, o
    atalho não fazia nada: o Python fechava com 1, sem janela e sem mensagem."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="helestron-lancador-"))
        casa = cls.tmp / "casa"
        casa.mkdir()
        cls.env = dict(os.environ, WINEPREFIX=str(cls.tmp / "prefixo"), WINEDEBUG="-all,trace+msgbox",
                       HOME=str(casa), XDG_DATA_HOME=str(casa / "dados"),
                       XDG_CONFIG_HOME=str(casa / "config"), XDG_CACHE_HOME=str(casa / "cache"),
                       WINEDLLOVERRIDES="mscoree,mshtml=;winemenubuilder.exe=d;winedbg.exe=d")
        cls.env.pop("HELESTRON_LOCAL", None)
        cls.exe = construcao.compilar_lancador("1.0.0", cls.tmp / "obra", RECURSOS / "helestron.ico")
        fonte = cls.tmp / "falso.c"
        fonte.write_text(_PYTHON_FALSO_C, encoding="utf-8")
        cls.dll = cls.tmp / "python312.dll"
        subprocess.run([shutil.which("x86_64-w64-mingw32-gcc"), "-shared", "-municode", "-O2", "-s",
                        "-o", str(cls.dll), str(fonte)], check=True, capture_output=True)
        subprocess.run([WINE64, "wineboot", "-i"], env=cls.env, capture_output=True, timeout=300)
        cls.pasta = cls.tmp / "prefixo" / "drive_c" / "Programa Helestron"

    @classmethod
    def tearDownClass(cls):
        subprocess.run([str(Path(WINE64).with_name("wineserver")), "-k"], env=cls.env,
                       capture_output=True, timeout=60)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(self.pasta, ignore_errors=True)
        self.pasta.mkdir(parents=True)
        shutil.copy(self.exe, self.pasta / "Helestron.exe")
        shutil.copy(self.dll, self.pasta / "python312.dll")
        pacote = Path("Lib") / "site-packages" / "helestron"
        for rel in (Path("Lib") / "encodings" / "__init__.py", pacote / "__init__.py", pacote / "__main__.py",
                    pacote / "nucleo" / "__init__.py", pacote / "nucleo" / "caminhos.py",
                    pacote / "nucleo" / "registro.py", pacote / "aplicativo" / "__init__.py",
                    pacote / "aplicativo" / "inicio.py", pacote / "aplicativo" / "integridade.py",
                    pacote / "aplicativo" / "erro.py"):
            (self.pasta / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pasta / rel).write_text("# m\n", encoding="utf-8")

    def abrir(self, *args, modo: str = "0") -> tuple[int | None, str | None, str]:
        """(código de saída, texto da caixa de mensagem, argumentos que o Py_Main recebeu)."""
        saida = self.tmp / "wine.log"
        with open(saida, "w") as registro:
            processo = subprocess.Popen([WINE64, str(self.pasta / "Helestron.exe"), *args],
                                        env=dict(self.env, FALSO_MODO=modo), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=registro)
        limite = time.monotonic() + 40
        caixa = None
        while time.monotonic() < limite:
            linhas = [l for l in saida.read_text(errors="replace").splitlines() if "MSGBOX_OnInit" in l]
            if linhas:
                caixa = _texto_do_trace(linhas[0])
                break
            if processo.poll() is not None:
                break
            time.sleep(0.2)
        if caixa is not None:
            subprocess.run([str(Path(WINE64).with_name("wineserver")), "-k"], env=self.env,
                           capture_output=True, timeout=60)
            processo.wait(30)
            codigo = None
        else:
            codigo = processo.wait(30)
            time.sleep(0.5)
            linhas = [l for l in saida.read_text(errors="replace").splitlines() if "MSGBOX_OnInit" in l]
            caixa = _texto_do_trace(linhas[0]) if linhas else None
        anotado = self.pasta / "py_main.txt"
        chamado = anotado.read_text(encoding="utf-8", errors="replace") if anotado.exists() else ""
        anotado.unlink(missing_ok=True)
        return codigo, caixa, chamado

    def test_tudo_no_lugar_abre_sem_mensagem(self):
        codigo, caixa, chamado = self.abrir()
        self.assertEqual(codigo, 0)
        self.assertIsNone(caixa)
        self.assertIn("-I -m helestron", chamado)

    def test_falta_um_modulo_de_partida(self):
        for rel in ("Lib/site-packages/helestron/aplicativo/erro.py", "Lib/encodings/__init__.py",
                    "Lib/site-packages/helestron/nucleo/registro.py", "Lib/site-packages/helestron/__main__.py"):
            with self.subTest(rel=rel):
                self.setUp()
                (self.pasta / rel).unlink()
                codigo, caixa, chamado = self.abrir()
                self.assertIsNotNone(caixa, "nenhuma mensagem")
                self.assertTrue(caixa.startswith("Falta um arquivo do programa:"), caixa)
                self.assertIn(rel.replace("/", "\\"), caixa)
                self.assertEqual(chamado, "", "o Python rodou mesmo assim")

    def test_pyc_ao_lado_vale_pelo_py(self):
        modulo = self.pasta / "Lib/site-packages/helestron/aplicativo/erro.py"
        modulo.unlink()
        modulo.with_suffix(".pyc").write_bytes(b"pyc")
        codigo, caixa, chamado = self.abrir()
        self.assertEqual((codigo, caixa), (0, None))
        self.assertNotEqual(chamado, "")

    def test_fechou_logo_sem_janela_aponta_o_registro(self):
        codigo, caixa, chamado = self.abrir(modo="1")
        self.assertIsNotNone(caixa, "o atalho fechou sem dizer nada")
        self.assertIn("sem abrir a janela (código 1)", caixa)
        self.assertIn("\\Helestron\\Logs", caixa)
        self.assertNotEqual(chamado, "")

    def test_fechou_com_janela_ou_por_outra_chamada_sem_mensagem_a_mais(self):
        # o programa mostrou a janela dele (ou a caixa dele): nada a acrescentar
        self.assertEqual(self.abrir(modo="janela")[:2], (1, None))
        # com argumentos (o autoteste do CI, uma linha de comando), nunca
        self.assertEqual(self.abrir("--autoteste", "C:\\x", modo="1")[:2], (1, None))
        # o instalador (--encerrar, --verificar-instalacao) nunca recebe caixa,
        # nem com um arquivo de partida faltando: quem informa é ele
        (self.pasta / "Lib/site-packages/helestron/nucleo/registro.py").unlink()
        self.assertEqual(self.abrir("--encerrar", modo="1")[:2], (1, None))
        self.assertEqual(self.abrir("--verificar-instalacao", modo="2")[:2], (2, None))


# =================================================================== marca
def _entradas_ico(dados: bytes) -> list[dict]:
    reservado, tipo, quantos = struct.unpack("<HHH", dados[:6])
    assert (reservado, tipo) == (0, 1)
    entradas = []
    for i in range(quantos):
        w, h, cores, _, planos, bits, tamanho, inicio = struct.unpack(
            "<BBBBHHII", dados[6 + 16 * i:22 + 16 * i])
        entradas.append({"lado": w or 256, "altura": h or 256, "bits": bits, "tamanho": tamanho,
                         "inicio": inicio, "png": dados[inicio:inicio + 4] == b"\x89PNG"})
    return entradas


class TestMarca(unittest.TestCase):
    def test_arquivos_versionados(self):
        for arq in (RECURSOS / "helestron.ico", RECURSOS / "helestron.png", RECURSOS / "helestron-64.png",
                    RECURSOS / "instalador-boas-vindas.bmp", RECURSOS / "instalador-cabecalho.bmp",
                    WEB_MARCA / "helestron.svg", WEB_MARCA / "helestron-64.png"):
            self.assertTrue(arq.is_file(), arq)

    def test_ico_com_todos_os_tamanhos(self):
        dados = (RECURSOS / "helestron.ico").read_bytes()
        entradas = _entradas_ico(dados)
        self.assertEqual(sorted(e["lado"] for e in entradas), [16, 20, 24, 32, 40, 48, 64, 128, 256])
        for e in entradas:
            self.assertEqual(e["lado"], e["altura"])
            self.assertEqual(e["bits"], 32)                 # RGBA
            self.assertLessEqual(e["inicio"] + e["tamanho"], len(dados))
            # BMP de 32 bits até 128 px; PNG só no de 256 (o formato do Visual Studio)
            self.assertEqual(e["png"], e["lado"] == 256)

    def test_bmp_do_instalador_em_24_bits(self):
        for nome, tamanho in (("instalador-boas-vindas.bmp", (164, 314)),
                              ("instalador-cabecalho.bmp", (150, 57))):
            dados = (RECURSOS / nome).read_bytes()
            self.assertEqual(dados[:2], b"BM")
            largura, altura = struct.unpack("<ii", dados[18:26])
            bits = struct.unpack("<H", dados[28:30])[0]
            compressao = struct.unpack("<I", dados[30:34])[0]
            self.assertEqual((largura, abs(altura)), tamanho, nome)
            self.assertEqual(bits, 24, nome)
            self.assertEqual(compressao, 0, nome)

    def test_svg(self):
        texto = (WEB_MARCA / "helestron.svg").read_text(encoding="utf-8")
        raiz = ET.fromstring(texto)
        self.assertTrue(raiz.tag.endswith("svg"))
        self.assertEqual(raiz.get("viewBox"), "0 0 1024 1024")
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertEqual(raiz.find("s:title", ns).text, "Helestron")
        self.assertGreaterEqual(len(raiz.findall(".//s:linearGradient", ns)), 3)
        self.assertIsNotNone(raiz.find(".//s:clipPath", ns))
        self.assertIn("#1B3560", texto)      # navy do gradiente
        self.assertIn("#0B1A33", texto)
        self.assertIn("#C5CDD8", texto)      # cinza-claro do H
        self.assertNotIn("http://", texto.replace("http://www.w3.org/2000/svg", ""))   # nada externo

    @unittest.skipUnless(TEM_PIL, "Pillow ausente")
    def test_ico_rgba_com_cantos_transparentes(self):
        from PIL import Image

        imagens = {}
        with Image.open(RECURSOS / "helestron.ico") as ico:
            for lado in (16, 20, 24, 32, 40, 48, 64, 128, 256):
                ico.size = (lado, lado)
                imagens[lado] = ico.copy().convert("RGBA")
        for lado, imagem in imagens.items():
            self.assertEqual(imagem.size, (lado, lado))
            self.assertLessEqual(imagem.getpixel((0, 0))[3], 8, lado)                # canto transparente
            centro = imagem.getpixel((lado // 2, lado // 2))
            self.assertEqual(centro[3], 255, lado)                                    # miolo opaco
            # o H branco no meio do navy: há pixels claros, e a lateral é navy
            pixels = imagem.load()
            claros = sum(1 for x in range(lado) for y in range(lado)
                         if pixels[x, y][3] == 255 and min(pixels[x, y][:3]) > 200)
            self.assertGreater(claros, lado * lado * 0.08, lado)
            r, g, b, a = pixels[round(lado * 0.10), lado // 2]
            self.assertGreaterEqual(a, 250, lado)
            self.assertLess(max(r, g, b), 130, lado)
            self.assertGreater(b, r, lado)                                            # azul-marinho

    @unittest.skipUnless(TEM_PIL, "Pillow ausente")
    def test_pngs(self):
        from PIL import Image

        for arq, lado in ((RECURSOS / "helestron.png", 512), (RECURSOS / "helestron-64.png", 64),
                          (WEB_MARCA / "helestron-64.png", 64)):
            with Image.open(arq) as imagem:
                self.assertEqual(imagem.size, (lado, lado))
                self.assertEqual(imagem.mode, "RGBA")
                self.assertEqual(imagem.getpixel((0, 0))[3], 0)

    @unittest.skipUnless(TEM_PIL, "Pillow ausente")
    def test_gerar_de_novo(self):
        marca = _carregar("helestron_marca", CONSTRUIR / "marca.py")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        gravados = marca.gerar(tmp / "recursos", tmp / "web")
        self.assertEqual(sorted(p.name for p in gravados),
                         sorted(["helestron.ico", "helestron.png", "helestron-64.png", "helestron-64.png",
                                 "instalador-boas-vindas.bmp", "instalador-cabecalho.bmp",
                                 "helestron.svg"]))
        entradas = _entradas_ico((tmp / "recursos" / "helestron.ico").read_bytes())
        self.assertEqual(len(entradas), 9)
        # pequeno = simplificado: sem reflexo nem placa, H mais grosso
        pequeno, grande = marca.Desenho(16), marca.Desenho(256)
        self.assertTrue(pequeno.simples)
        self.assertFalse(grande.simples)
        self.assertGreater(pequeno.h_haste, grande.h_haste)
        # nos tamanhos até 64 px o H cai em pixels inteiros (nitidez)
        for lado in (16, 20, 24, 32, 48, 64):
            for peca in marca.Desenho(lado).retangulos_h():
                for v in peca:
                    self.assertAlmostEqual(v * lado, round(v * lado), places=6)


# =================================================================== CI
class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.texto = WORKFLOW.read_text(encoding="utf-8")

    @unittest.skipUnless(yaml, "PyYAML ausente")
    def test_yaml_valido_com_os_trabalhos(self):
        dados = yaml.safe_load(self.texto)
        # o YAML 1.1 lê a chave "on" como True
        gatilhos = dados.get("on", dados.get(True))
        self.assertIn("push", gatilhos)
        self.assertIn("pull_request", gatilhos)
        self.assertFalse(dados["concurrency"]["cancel-in-progress"])
        jobs = dados["jobs"]
        self.assertEqual(set(jobs), {"testes", "construir", "windows", "publicar"})
        self.assertEqual(jobs["testes"]["runs-on"], "ubuntu-latest")
        self.assertEqual(jobs["construir"]["runs-on"], "ubuntu-latest")
        self.assertEqual(jobs["windows"]["runs-on"], "windows-latest")
        self.assertEqual(jobs["windows"]["needs"], "construir")
        self.assertIn("refs/tags/v", jobs["publicar"]["if"])
        self.assertEqual(set(jobs["publicar"]["needs"]), {"testes", "windows"})
        self.assertEqual(jobs["publicar"]["permissions"]["contents"], "write")

        def scripts(job):
            return "\n".join(p.get("run", "") for p in jobs[job]["steps"])

        self.assertIn("playwright install --with-deps chromium", scripts("testes"))
        self.assertIn("unittest discover -s testes -t .", scripts("testes"))
        self.assertIn("--require-hashes -r construir/requisitos-teste.txt", scripts("testes"))
        construir = scripts("construir")
        self.assertIn("nsis mingw-w64", construir)
        self.assertIn("huggingface_hub", construir)
        self.assertIn("construir/construir.py --modelo", construir)
        windows = scripts("windows")
        for trecho in ("'/S /D=' + $env:PASTA", "--verificar-instalacao", "--autoteste",
                       "System.Speech", "-I -m helestron transcrever --ao-vivo", "notifications/initialized",
                       "pauta exportar", "pauta importar", "CofreSenhas", "Desinstalar.exe",
                       "GetFolderPath('Desktop')", "CurrentVersion\\Uninstall\\Helestron",
                       "$p.ExitCode -ne 0"):
            self.assertIn(trecho, windows)
        self.assertIn("gh release create", scripts("publicar"))
        nomes_artefatos = [p["with"]["name"] for p in jobs["construir"]["steps"]
                           if p.get("uses", "").startswith("actions/upload-artifact")]
        self.assertEqual(nomes_artefatos, ["Helestron-Setup"])

    @unittest.skipUnless(yaml, "PyYAML ausente")
    def test_scripts_so_com_ascii(self):
        dados = yaml.safe_load(self.texto)
        for nome, job in dados["jobs"].items():
            for passo in job["steps"]:
                script = passo.get("run", "")
                fora = sorted({c for c in script if ord(c) > 127})
                self.assertEqual(fora, [], f"{nome} / {passo.get('name')}: {fora}")

    def passo_reinstalar(self) -> str:
        dados = yaml.safe_load(self.texto)
        return next(p["run"] for p in dados["jobs"]["windows"]["steps"]
                    if p.get("name", "").startswith("Instalar de novo por cima"))

    @unittest.skipUnless(yaml, "PyYAML ausente")
    def test_conector_aberto_responde_antes_e_depois_da_atualizacao(self):
        """O ping ao MCP aberto ia com BOM (StandardInput do PowerShell 5.1 com
        o console em UTF-8) e voltava -32700, sem que o passo reparasse; e nada
        conferia que o conector antigo seguia respondendo depois da atualização."""
        script = self.passo_reinstalar()
        self.assertNotIn("StandardInput.WriteLine", script)
        # a entrada do console fica sem preâmbulo ANTES do Start (o BOM sai no Start)
        self.assertLess(script.index("[Console]::InputEncoding = $semBom"),
                        script.index("[System.Diagnostics.Process]::Start($psi)"))
        self.assertIn("""-notmatch '"result"'""", script)
        instalador = script.index("$p.WaitForExit()")
        fechar = script.index("$mcp.StandardInput.Close()")
        depois = script[instalador:fechar]
        self.assertIn('"method": "tools/list"', depois)
        self.assertIn('"name": "ler_transcricao"', depois)
        self.assertIn("""-notmatch '"isError": false'""", depois)

    @unittest.skipUnless(yaml and PWSH, "PyYAML ou o PowerShell (pwsh) ausente")
    def test_pedidos_ao_mcp_com_o_powershell_de_verdade(self):
        """Os pedidos do passo, com o PowerShell e o servidor MCP de verdade:
        sem BOM, e também com o BOM já na entrada (o console que não mudou)."""
        from docx import Document

        script = self.passo_reinstalar()
        inicio = script.index("$semBom = New-Object")
        ping = script.index("\n", script.index("""$null = Pedir-Mcp '{"jsonrpc": "2.0", "id": 1""")) + 1
        apos = script.index("""$null = Pedir-Mcp '{"jsonrpc": "2.0", "id": 2""")
        fim = script.index("\n", script.index("if ($leitura -notmatch")) + 1
        antes, depois = script[inicio:ping], script[apos:fim]
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        numero = "0700123-83.2024.8.02.0001"
        (tmp / "acervo" / "Transcricoes").mkdir(parents=True)
        documento = Document()
        documento.add_paragraph("Audiência de instrução e julgamento.")
        documento.save(tmp / "acervo" / "Transcricoes" / f"{numero}.docx")
        detectar = "$bomNaEntrada = $mcp.StandardInput.Encoding.GetPreamble().Length -gt 0"
        self.assertIn(detectar, antes)
        bom = "$mcp.StandardInput.BaseStream.Write([byte[]](0xEF,0xBB,0xBF), 0, 3)\n"
        cenarios = {"sem BOM": (antes, 0),
                    "com o BOM na entrada": (antes.replace(detectar, bom + "$bomNaEntrada = $true"), 0),
                    "BOM sem tolerar": (antes.replace(detectar, bom + "$bomNaEntrada = $false"), 1)}
        for nome, (corpo, esperado) in cenarios.items():
            with self.subTest(cenario=nome):
                ps1 = tmp / "passo.ps1"
                ps1.write_text(f"""$ErrorActionPreference = 'Stop'
$env:PROCESSO = '{numero}'
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = '{sys.executable}'
$psi.Arguments = '-m helestron mcp --pasta "{tmp / "acervo"}"'
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.WorkingDirectory = '{REPOSITORIO}'
{corpo}
{depois}
$mcp.StandardInput.Close()
if (-not $mcp.WaitForExit(30000)) {{ $mcp.Kill(); throw 'o MCP nao saiu' }}
""", encoding="utf-8")
                r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(ps1)],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=180)
                saida = r.stdout + r.stderr
                self.assertEqual(r.returncode, esperado, saida)
                if esperado == 0:
                    self.assertIn('"id": 3, "result"', saida)
                    self.assertIn("Audiência de instrução", saida)
                else:
                    self.assertIn("-32700", saida)

    @unittest.skipUnless(yaml, "PyYAML ausente")
    def test_pasta_do_usuario_e_restos_da_versao_anterior_no_windows(self):
        dados = yaml.safe_load(self.texto)
        passos = {p.get("name", ""): p.get("run", "") for p in dados["jobs"]["windows"]["steps"]}
        nomes = list(passos)
        restos = next(n for n in nomes if n.startswith("Restos da versao anterior"))
        instalar = next(n for n in nomes if n.startswith("Instalar em silencio"))
        self.assertLess(nomes.index(restos), nomes.index(instalar))
        self.assertIn("Assessor Integrado.lnk", passos[restos])
        self.assertIn("iniciar.pyw", passos[restos])
        conferir = passos["Conferir arquivos, atalhos e registro"]
        self.assertIn("'arquivos-instalados.txt'", conferir)
        self.assertIn("assessor-integrado", conferir)
        usuario = next(n for n in nomes if n.startswith("Pasta com arquivos do usuario"))
        self.assertGreater(nomes.index(usuario), nomes.index("Desinstalar em silencio (documentos do usuario ficam)"))
        for trecho in ("'/S /D=' + $pasta", "Join-Path $pasta 'Helestron'", "'share\\orcamento.txt'",
                       "'Scripts\\backup.bat'", "'Lib\\minha-lib.txt'", "Desinstalar.exe"):
            self.assertIn(trecho, passos[usuario])

    def test_texto_com_acento_entra_por_env(self):
        self.assertIn("PASTA: 'C:\\Teste Área\\Helestron'", self.texto)
        self.assertIn("audiência de instrução e julgamento", self.texto)


# =================================================================== repositório
class TestRepositorio(unittest.TestCase):
    def test_gitignore(self):
        texto = (REPOSITORIO / ".gitignore").read_text(encoding="utf-8")
        for linha in ("/dist/", "/construir/obra/", "/construir/cache/", "__pycache__/"):
            self.assertIn(linha, texto.splitlines())

    def test_gitattributes_binarios(self):
        texto = (REPOSITORIO / ".gitattributes").read_text(encoding="utf-8")
        for padrao in ("*.ico", "*.bmp", "*.png", "*.woff2", "*.exe"):
            self.assertRegex(texto, rf"(?m)^{re.escape(padrao)}\s+binary$")

    def test_construir_ajuda_sem_rede(self):
        r = subprocess.run([sys.executable, str(CONSTRUIR / "construir.py"), "--help"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for opcao in ("--sem-modelo", "--modelo", "--cache", "--python-tar", "--saida", "--sem-falantes"):
            self.assertIn(opcao, r.stdout)
        # em português, como as outras linhas de comando do programa
        self.assertIn("uso: python construir/construir.py", r.stdout)
        self.assertIn("mostra esta ajuda e sai", r.stdout)
        self.assertNotIn("usage:", r.stdout)
        r = subprocess.run([sys.executable, str(CONSTRUIR / "construir.py"), "--xyz"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("erro: argumento não reconhecido: --xyz", r.stderr)

    def test_opcoes_incompativeis(self):
        saida = io.StringIO()
        with mock.patch.object(construcao, "garantir_marca") as marca, \
                contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
            self.assertEqual(construcao.main(["--modelo", "x", "--sem-modelo"]), 1)
        marca.assert_not_called()
        self.assertIn("use --modelo DIR ou --sem-modelo", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
