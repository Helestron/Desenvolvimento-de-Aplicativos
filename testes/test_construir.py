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
        self.assertLess(secao.index("Call LiberarArquivos"), secao.index("!insertmacro RemoverPrograma"))
        self.assertLess(secao.index("!insertmacro RemoverPrograma"), secao.index("Call AfastarPresos"))
        self.assertLess(secao.index("Call AfastarPresos"), secao.index("File /r"))
        self.assertIn("--encerrar", self.script)
        conferir = self.script[self.script.index('Section "-Conferir a instalação"'):]
        self.assertIn('--verificar-instalacao --relatorio "${RELATORIO}"', conferir)
        self.assertIn("SetErrorLevel 2", conferir)
        self.assertIn("/SD IDNO", conferir)               # o modo silencioso não para em pergunta

    def test_remover_programa_lista_o_que_foi_instalado(self):
        inicio = self.script.index("!macro RemoverPrograma")
        macro = self.script[inicio:self.script.index("!macroend", inicio)]
        for linha in ('RMDir /r "$INSTDIR\\Lib"', 'RMDir /r "$INSTDIR\\DLLs"', 'RMDir /r "$INSTDIR\\modelos"',
                      'Delete "$INSTDIR\\python312.dll"', 'Delete "$INSTDIR\\Helestron.exe"',
                      'Delete "$INSTDIR\\manifesto.json"', 'RMDir /r "$INSTDIR\\Scripts"'):
            self.assertIn(linha, macro)
        # nunca a pasta inteira (ela pode ter coisas do usuário)
        self.assertNotRegex(self.script, r'RMDir /r "\$INSTDIR"')
        self.assertNotRegex(self.script, r'RMDir /r "\$INSTDIR\\\*')

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
        lista = self.script[self.script.index("!macro AfastarLista"):]
        lista = lista[:lista.index("!macroend")]
        for linha in ('!insertmacro AfastarPasta "${UN}" "Lib"', '!insertmacro AfastarPasta "${UN}" "DLLs"',
                      '!insertmacro AfastarArquivo "${UN}" "python312.dll"',
                      '!insertmacro AfastarArquivo "${UN}" "python.exe"'):
            self.assertIn(linha, lista)
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
                                            ("segurar.c", _SEGURAR_C, ["-municode"], "segurar.exe")):
            (fontes / nome).write_text(codigo, encoding="utf-8")
            subprocess.run([gcc, *opcoes, "-O2", "-s", "-o", str(fontes / saida), str(fontes / nome)],
                           check=True, capture_output=True)
        cls.segurar = fontes / "segurar.exe"
        arvore = cls.tmp / "obra" / "Helestron"
        (arvore / "Lib" / "site-packages" / "helestron").mkdir(parents=True)
        (arvore / "DLLs").mkdir()
        shutil.copy(fontes / "stub.exe", arvore / "Helestron.exe")
        shutil.copy(fontes / "stub.exe", arvore / "python.exe")
        shutil.copy(fontes / "falso.dll", arvore / "python312.dll")
        shutil.copy(fontes / "falso.dll", arvore / "DLLs" / "_socket.pyd")
        (arvore / "Lib" / "os.py").write_text("# os\n", encoding="utf-8")
        (arvore / "Lib" / "site-packages" / "helestron" / "__init__.py").write_text("# h\n")
        construcao.gerar_manifesto(arvore, "1.0.0")
        cls.setup = cls.tmp / "obra" / "Helestron-Setup-1.0.0.exe"
        script = construcao.script_nsis(arvore, "1.0.0", cls.setup, RECURSOS)
        script = script.replace("Unicode true", "Target amd64-unicode")
        script = script.replace("SetCompressor /SOLID /FINAL lzma", "SetCompressor /FINAL zlib")
        script = script.replace("SetCompressorDictSize 64\n", "")
        (cls.tmp / "obra" / "h.nsi").write_text(script, encoding="utf-8")
        r = subprocess.run([MAKENSIS, "-V2", "-INPUTCHARSET", "UTF8", str(cls.tmp / "obra" / "h.nsi")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        subprocess.run([WINE64, "wineboot", "-i"], env=cls.env, capture_output=True, timeout=300)
        cls.alvo = cls.tmp / "prefixo" / "drive_c" / "TesteArea" / "Helestron"

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

    def instalar(self, destino: str | None = None) -> int:
        return self.wine(self.setup, "/S", f"/D={destino or self.ALVO_WIN}")

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
        self.assertIn("instale o Helestron de novo com o Helestron-Setup", self.fonte)
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

    def test_opcoes_incompativeis(self):
        saida = io.StringIO()
        with mock.patch.object(construcao, "garantir_marca") as marca, \
                contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
            self.assertEqual(construcao.main(["--modelo", "x", "--sem-modelo"]), 1)
        marca.assert_not_called()
        self.assertIn("use --modelo DIR ou --sem-modelo", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
