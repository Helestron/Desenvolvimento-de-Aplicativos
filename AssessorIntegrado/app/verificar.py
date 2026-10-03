"""Confere a instalação: o que funciona, o que falta e como corrigir.

    python -m app verificar               conferência rápida (alguns segundos)
    python -m app verificar --completo    também carrega o modelo e transcreve
                                          1 s de silêncio, e abre o navegador
                                          em modo invisível
    python -m app verificar --json ARQ    grava o resultado em JSON (é daí que
                                          o instalador tira o resumo final)

Cada item sai como "ok", "aviso" ou "falha". Falha em item obrigatório
reprova a instalação (código de saída 1). Aviso nunca reprova: é o que
funciona com limitação (sem microfone, modelo ainda não baixado) ou o que não
se aplica fora do Windows (DPAPI, privacidade do microfone).

Por que tantos testes rodam num processo separado: importar onnxruntime ou
ctranslate2 num processador sem as instruções esperadas, ou com DLL do
Visual C++ faltando, pode DERRUBAR o processo sem exceção nenhuma - e a
verificação morreria junto, calada. No processo-filho, a queda vira um
diagnóstico ("o processo caiu ao carregar onnxruntime"). Também não mexe na
janela, que pode estar aberta chamando esta mesma verificação: o PortAudio,
por exemplo, guarda a lista de microfones do momento em que foi iniciado (o
filho enxerga a lista atual), e o Tk não gosta de ser criado fora da thread
principal.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import NOME, __version__
from .nucleo import caminhos

log = logging.getLogger("verificar")

OK, AVISO, FALHA = "ok", "aviso", "falha"
SITUACOES = (OK, AVISO, FALHA)
NO_WINDOWS = sys.platform == "win32"
NAO_SE_APLICA = "Não se aplica fora do Windows"
RODE_O_INSTALADOR = "Rode o INSTALAR.bat de novo: ele completa a instalação sem apagar os seus arquivos."
LIMITE_CAMINHO = 100

# (módulo, distribuição no PyPI, para que serve)
BIBLIOTECAS: tuple[tuple[str, str, str], ...] = (
    ("faster_whisper", "faster-whisper", "transcrição"),
    ("ctranslate2", "ctranslate2", "transcrição"),
    ("onnxruntime", "onnxruntime", "detector de voz"),
    ("av", "av", "leitura de áudio"),
    ("numpy", "numpy", "processamento do áudio"),
    ("sounddevice", "sounddevice", "microfone"),
    ("soundfile", "soundfile", "gravação em FLAC"),
    ("huggingface_hub", "huggingface-hub", "download dos modelos"),
    ("docx", "python-docx", "documentos do Word"),
    ("pymupdf", "pymupdf", "PDF"),
    ("pypdf", "pypdf", "PDF"),
    ("openpyxl", "openpyxl", "planilhas do Excel"),
    ("xlrd", "xlrd", "planilhas antigas do Excel (.xls)"),
    ("playwright", "playwright", "download nos portais"),
    ("PIL", "pillow", "imagens e ícones"),
)
# Os que trazem DLL própria: importados de verdade, num processo à parte.
NATIVOS = ("numpy", "ctranslate2", "onnxruntime", "av", "sounddevice", "soundfile",
           "pymupdf", "faster_whisper", "playwright.sync_api")
NOMES_AMIGAVEIS = {"av": "PyAV", "pymupdf": "PyMuPDF", "playwright.sync_api": "Playwright",
                   "faster_whisper": "faster-whisper", "sounddevice": "PortAudio",
                   "soundfile": "libsndfile", "sherpa_onnx": "sherpa-onnx"}

# Códigos de saída de processo que caiu (Windows: NTSTATUS; POSIX: -sinal).
QUEDAS = {
    0xC000001D: "instrução ilegal: o processador não tem as instruções exigidas (AVX)",
    0xC0000135: "DLL não encontrada",
    0xC0000005: "violação de acesso (DLL incompatível ou corrompida)",
    0xC0000409: "falha interna de uma DLL",
    -4: "instrução ilegal: o processador não tem as instruções exigidas (AVX)",
    -11: "violação de acesso (biblioteca incompatível ou corrompida)",
    -6: "a biblioteca abortou o processo",
}


@dataclass
class Item:
    nome: str
    situacao: str               # "ok" | "aviso" | "falha"
    detalhe: str = ""
    obrigatorio: bool = True
    codigo: str = ""            # identificador estável (a tela usa no botão "Corrigir")
    acao: str = ""              # o que fazer, numa frase

    @property
    def ok(self) -> bool:
        return self.situacao == OK


# ===================================================== processos à parte

def _python() -> str:
    """O python.exe do programa (com console: o pythonw não devolve saída)."""
    return str(caminhos.python_exe(janela=False))


def _ambiente_filho(extra_pythonpath: list[str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    # PYTHONHOME global (deixado por outro programa) quebra o Python portátil
    # logo na partida; o pacote "do usuário" de outro Python misturaria versões.
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    caminho = [str(caminhos.RAIZ)] + list(extra_pythonpath or [])
    env["PYTHONPATH"] = os.pathsep.join(caminho)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(caminhos.NAVEGADORES))
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    env.setdefault("HF_HUB_OFFLINE", "1")   # o teste do modelo nunca vai à rede
    return env


def _texto(dados) -> str:
    if dados is None:
        return ""
    if isinstance(dados, bytes):
        return dados.decode("utf-8", errors="replace")
    return str(dados)


def rodar(argumentos: list[str], limite_s: float, extra_pythonpath: list[str] | None = None
          ) -> tuple[int | None, str, str, bool]:
    """(código de saída, stdout, stderr, estourou o tempo). Nunca levanta."""
    try:
        r = subprocess.run(
            argumentos, capture_output=True, timeout=limite_s, cwd=str(caminhos.RAIZ),
            env=_ambiente_filho(extra_pythonpath), stdin=subprocess.DEVNULL,
            creationflags=0x08000000 if NO_WINDOWS else 0)   # CREATE_NO_WINDOW
        return r.returncode, _texto(r.stdout), _texto(r.stderr), False
    except subprocess.TimeoutExpired as erro:
        return None, _texto(erro.stdout), _texto(erro.stderr), True
    except OSError as erro:
        return -1, "", str(erro), False


def explicar_queda(codigo: int | None) -> str:
    if codigo is None:
        return "travou (não respondeu no tempo esperado)"
    if codigo in QUEDAS:
        return QUEDAS[codigo]
    sem_sinal = codigo & 0xFFFFFFFF
    if sem_sinal in QUEDAS:
        return QUEDAS[sem_sinal]
    if sem_sinal >= 0xC0000000:
        return f"terminou abruptamente (código 0x{sem_sinal:08X})"
    return f"terminou abruptamente (código {codigo})"


_SONDA_IMPORTACAO = r"""
import importlib, json, sys
for nome in sys.argv[1:]:
    print(json.dumps({"inicio": nome}), flush=True)
    try:
        modulo = importlib.import_module(nome)
        versao = getattr(modulo, "__version__", "") or getattr(modulo, "VersionBind", "")
        print(json.dumps({"ok": nome, "versao": str(versao)}), flush=True)
    except BaseException as erro:
        texto = str(erro).replace("\n", " ")[:400]
        print(json.dumps({"erro": nome, "tipo": type(erro).__name__, "mensagem": texto}), flush=True)
"""


def sondar_importacoes(modulos: list[str] | tuple[str, ...], limite_s: float = 180.0,
                       extra_pythonpath: list[str] | None = None) -> dict[str, dict]:
    """Importa cada módulo num processo à parte e diz o que aconteceu.

    {"modulo": {"ok": True, "versao": "1.2"} | {"ok": False, "erro": "...", "queda": bool}}.
    Se o processo cair no meio, o módulo que estava sendo importado é o
    culpado; os seguintes são tentados de novo num processo novo.
    """
    pendentes = list(modulos)
    resultado: dict[str, dict] = {}
    while pendentes:
        codigo, saida, erro, estourou = rodar(
            [_python(), "-c", _SONDA_IMPORTACAO, *pendentes], limite_s, extra_pythonpath)
        em_curso = None
        for linha in saida.splitlines():
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            if "inicio" in d:
                em_curso = d["inicio"]
            elif "ok" in d:
                resultado[d["ok"]] = {"ok": True, "versao": d.get("versao", "")}
                em_curso = None
            elif "erro" in d:
                resultado[d["erro"]] = {"ok": False, "queda": False,
                                        "erro": f"{d.get('tipo', 'Erro')}: {d.get('mensagem', '')}"}
                em_curso = None
        restantes = [m for m in pendentes if m not in resultado]
        if not restantes:
            break
        if em_curso is None:
            # Morreu antes de começar: o próprio Python não abre.
            ultima = (erro.strip().splitlines() or [""])[-1]
            motivo = f"o Python não iniciou ({explicar_queda(codigo)})"
            if ultima:
                motivo += f": {ultima}"
            for m in restantes:
                resultado[m] = {"ok": False, "queda": True, "erro": motivo}
            break
        resultado[em_curso] = {"ok": False, "queda": True,
                               "erro": "o processo " + ("travou" if estourou else "caiu")
                                       + f" ao carregar ({explicar_queda(None if estourou else codigo)})"}
        pendentes = [m for m in restantes if m != em_curso]
    return resultado


# ============================================================ os itens

def _relativo(p: Path | str) -> str:
    """Caminho dentro da pasta do programa sem o começo comprido."""
    try:
        return str(Path(p).resolve().relative_to(caminhos.RAIZ.resolve()))
    except (ValueError, OSError):
        return str(p)


def _versao(distribuicao: str) -> str:
    try:
        return importlib.metadata.version(distribuicao)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _presente(modulo: str) -> bool:
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


_SONDA_TK = r"""
import tkinter
print("tk", tkinter.Tcl().eval("info patchlevel"), flush=True)
try:
    raiz = tkinter.Tk()
    raiz.withdraw()
    raiz.update_idletasks()
    raiz.destroy()
    print("janela ok", flush=True)
except tkinter.TclError as erro:
    print("sem tela", str(erro).replace("\n", " ")[:200], flush=True)
"""


def checar_python() -> Item:
    versao = platform.python_version()
    no_runtime = str(Path(sys.executable).resolve()).lower().startswith(
        str(caminhos.PYTHON_DIR.resolve()).lower())
    onde = "runtime\\python" if no_runtime else sys.executable
    situacao, acao = OK, ""
    if sys.version_info[:2] != (3, 12):
        if sys.version_info >= (3, 10):
            situacao, acao = AVISO, "O programa é testado com o Python 3.12, que o INSTALAR.bat instala."
        else:
            return Item("Python e janela (Tk)", FALHA, f"Python {versao} é antigo demais.",
                        codigo="python", acao=RODE_O_INSTALADOR)
    codigo, saida, erro, _ = rodar([_python(), "-c", _SONDA_TK], 60)
    tk = ""
    for linha in saida.splitlines():
        if linha.startswith("tk "):
            tk = linha[3:].strip()
    if codigo != 0 or not tk:
        ultima = (erro.strip().splitlines() or [explicar_queda(codigo)])[-1]
        return Item("Python e janela (Tk)", FALHA,
                    f"Python {versao}, mas o Tk (a biblioteca da janela) não carregou: {ultima}",
                    codigo="python", acao=RODE_O_INSTALADOR)
    detalhe = f"Python {versao} e Tk {tk} ({onde})."
    if "janela ok" not in saida:
        if NO_WINDOWS:
            return Item("Python e janela (Tk)", FALHA,
                        f"{detalhe[:-1]}, mas a janela não abriu.", codigo="python",
                        acao=RODE_O_INSTALADOR)
        return Item("Python e janela (Tk)", AVISO,
                    f"{detalhe} Sem tela neste ambiente: a janela não foi testada.",
                    codigo="python")
    return Item("Python e janela (Tk)", situacao, detalhe, codigo="python", acao=acao)


def checar_bibliotecas() -> Item:
    faltam = [f"{dist} ({uso})" for mod, dist, uso in BIBLIOTECAS if not _presente(mod)]
    if faltam:
        return Item("Bibliotecas", FALHA, "Faltam: " + ", ".join(faltam) + ".",
                    codigo="bibliotecas", acao=RODE_O_INSTALADOR)
    principais = []
    for dist in ("faster-whisper", "playwright", "pymupdf", "python-docx"):
        v = _versao(dist)
        if v:
            principais.append(f"{dist} {v}")
    detalhe = f"As {len(BIBLIOTECAS)} bibliotecas estão presentes"
    if principais:
        detalhe += " (" + ", ".join(principais) + ")"
    return Item("Bibliotecas", OK, detalhe + ".", codigo="bibliotecas")


def checar_nativos() -> Item:
    modulos = [m for m in NATIVOS if _presente(m.split(".")[0])]
    if not modulos:
        return Item("Componentes nativos (DLLs)", FALHA, "Nenhuma das bibliotecas nativas está instalada.",
                    codigo="dlls", acao=RODE_O_INSTALADOR)
    res = sondar_importacoes(modulos)
    falhas = {m: r for m, r in res.items() if not r.get("ok")}
    if not falhas:
        nomes = [NOMES_AMIGAVEIS.get(m, m) + (f" {r['versao']}" if r.get("versao") else "")
                 for m, r in res.items() if m in ("ctranslate2", "onnxruntime", "av")]
        detalhe = "O componente carregou" if len(res) == 1 else f"Os {len(res)} componentes carregaram"
        if nomes:
            detalhe += " (" + ", ".join(nomes) + ")"
        return Item("Componentes nativos (DLLs)", OK, detalhe + ".", codigo="dlls")
    partes = [f"{NOMES_AMIGAVEIS.get(m, m)}: {r['erro']}" for m, r in falhas.items()]
    texto = " ".join(r["erro"] for r in falhas.values())
    if "AVX" in texto or "instrução ilegal" in texto:
        acao = ("Este processador é antigo demais para a transcrição. As demais funções "
                "podem funcionar; fale com o suporte.")
    elif "DLL" in texto or "dll" in texto:
        acao = ("Faltam DLLs do Visual C++. " + RODE_O_INSTALADOR + " Se persistir, instale o "
                "\u201cMicrosoft Visual C++ Redistributable\u201d (x64) ou peça ao suporte.")
    else:
        acao = RODE_O_INSTALADOR
    return Item("Componentes nativos (DLLs)", FALHA, "; ".join(partes), codigo="dlls", acao=acao)


def _modelos():
    """O módulo de modelos da transcrição (ponto único de integração)."""
    from .transcricao import modelos

    return modelos


def _modelo_instalado(nome: str) -> tuple[bool, Path]:
    try:
        m = _modelos()
        return m.instalado(nome), m.pasta_do_modelo(nome)
    except (ImportError, ValueError):
        pasta = caminhos.MODELOS / f"whisper-{nome}"
        bin_ = pasta / "model.bin"
        ok = (all((pasta / a).is_file() for a in ("config.json", "tokenizer.json"))
              and bin_.is_file() and bin_.stat().st_size > 1_000_000)
        return ok, pasta


def _caminho_nativo(pasta: Path) -> str:
    """O caminho do modelo exatamente como o programa o entrega ao CTranslate2.

    Com acento na pasta ("C:\\Users\\João\\..."), o programa usa o nome curto
    8.3 (modelos.caminho_nativo), por causa das bibliotecas em C++ que abrem
    arquivos em ANSI. A verificação tem de carregar o modelo pelo MESMO
    caminho: testando por outro, poderia aprovar o que o programa não abre,
    ou reprovar o que ele abre.
    """
    try:
        return str(_modelos().caminho_nativo(pasta))
    except Exception:  # noqa: BLE001 - sem o módulo, o caminho como está
        return str(pasta)


def _tamanho_mb(nome: str) -> int:
    try:
        return int(_modelos().tamanho_mb(nome))
    except Exception:
        return {"base": 145, "small": 484, "medium": 1530, "large-v3-turbo": 1620}.get(nome, 0)


def _nomes_dos_modelos(cfg) -> tuple[str, str]:
    ao_vivo = cfg.texto("transcricao", "modelo_ao_vivo") or "small"
    revisao = cfg.texto("transcricao", "modelo_revisao") or "medium"
    try:
        m = _modelos()
        ao_vivo, revisao = m.nome_canonico(ao_vivo), m.nome_canonico(revisao)
    except (ImportError, ValueError):
        pass
    return ao_vivo, revisao


def checar_modelo(cfg) -> Item:
    ao_vivo, revisao = _nomes_dos_modelos(cfg)
    instalado, pasta = _modelo_instalado(ao_vivo)
    rev_ok, _ = _modelo_instalado(revisao)
    if revisao == ao_vivo:
        sobre_revisao = ""
    elif rev_ok:
        sobre_revisao = f" O da revisão final ({revisao}) também está instalado."
    else:
        sobre_revisao = (f" O da revisão final ({revisao}) será baixado no primeiro uso "
                         f"(cerca de {_tamanho_mb(revisao)} MB).")
    if instalado:
        return Item("Modelo de transcrição", OK,
                    f"Ao vivo: {ao_vivo}, instalado em {_relativo(pasta)}.{sobre_revisao}",
                    obrigatorio=False, codigo="modelo")
    return Item("Modelo de transcrição", AVISO,
                f"O modelo da transcrição ao vivo ({ao_vivo}) ainda não foi baixado.",
                obrigatorio=False, codigo="modelo",
                acao=(f"Ele é baixado no primeiro uso (cerca de {_tamanho_mb(ao_vivo)} MB). "
                      "Para baixar agora: Configurações > Transcrição, ou rode o INSTALAR.bat de novo."))


_SONDA_WHISPER = r"""
import sys, time
inicio = time.time()
import numpy as np
from faster_whisper import WhisperModel
modelo = WhisperModel(sys.argv[1], device="cpu", compute_type="int8", cpu_threads=2)
carregou = time.time() - inicio
segmentos, info = modelo.transcribe(np.zeros(16000, dtype=np.float32), language="pt",
                                    beam_size=1, vad_filter=True)
texto = " ".join(s.text for s in segmentos).strip()
print("ok %.1f %.1f" % (carregou, time.time() - inicio), flush=True)
"""


def checar_teste_transcricao(cfg) -> Item:
    ao_vivo, _ = _nomes_dos_modelos(cfg)
    instalado, pasta = _modelo_instalado(ao_vivo)
    nome = "Teste de transcrição"
    if not instalado:
        return Item(nome, AVISO, f"Pulado: o modelo {ao_vivo} ainda não foi baixado.",
                    obrigatorio=False, codigo="teste_transcricao")
    nativo = _caminho_nativo(pasta)
    codigo, saida, erro, estourou = rodar([_python(), "-c", _SONDA_WHISPER, nativo], 300)
    for linha in saida.splitlines():
        if linha.startswith("ok "):
            _, carregou, total = linha.split()
            return Item(nome, OK,
                        f"O modelo {ao_vivo} carregou em {carregou.replace('.', ',')} s e transcreveu "
                        f"1 s de silêncio (total: {total.replace('.', ',')} s).",
                        codigo="teste_transcricao")
    ultima = (erro.strip().splitlines() or [""])[-1]
    motivo = explicar_queda(None if estourou else codigo) if not ultima else ultima
    acao = ("Apague a pasta " + _relativo(pasta) + " e rode o INSTALAR.bat de novo "
            "(o modelo será baixado outra vez).")
    if not nativo.isascii():
        # Acento no caminho e nenhum nome curto 8.3 neste disco: se a causa
        # for essa, baixar de novo não resolve.
        acao += (" Se persistir, instale o programa numa pasta sem acento no caminho, "
                 "como C:\\AssessorIntegrado.")
    return Item(nome, FALHA, f"O modelo {ao_vivo} não funcionou: {motivo}",
                codigo="teste_transcricao", acao=acao)


def _navegadores_instalados() -> tuple[str, str]:
    """(Chrome, Edge) - caminhos ou ''. Ponto único de integração com o download."""
    try:
        from .download import navegador

        return navegador.chrome_instalado(), navegador.edge_instalado()
    except Exception:
        candidatos = {
            "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                       r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                       os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")],
            "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
        }
        achar = (lambda lista: next((c for c in lista if os.path.exists(c)), "")) if NO_WINDOWS \
            else (lambda lista: "")
        chrome = achar(candidatos["chrome"]) or shutil.which("google-chrome") or ""
        edge = achar(candidatos["edge"]) or shutil.which("microsoft-edge") or ""
        return chrome, edge


def _chromium_proprio() -> str:
    """A pasta do Chromium do Playwright (o do programa ou o configurado), ou ''."""
    pastas = [caminhos.NAVEGADORES]
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        pastas.insert(0, Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    for pasta in pastas:
        try:
            achados = sorted(p for p in Path(pasta).glob("chromium-*") if p.is_dir())
        except OSError:
            achados = []
        if achados:
            return str(achados[-1])
    return ""


def _canais(cfg) -> list[str]:
    """Ordem de tentativa, como o download faria: "chrome", "msedge", "chromium"."""
    chrome, edge = _navegadores_instalados()
    try:
        from .download import navegador

        ordem = navegador.escolher_canais(cfg.texto("download", "navegador") or "auto",
                                          chrome=chrome, edge=edge)
        return [c or "chromium" for c in ordem]
    except Exception:
        ordem = (["chrome"] if chrome else []) + (["msedge"] if edge else [])
        return ordem + ["chromium"]


def checar_navegador(cfg) -> Item:
    chrome, edge = _navegadores_instalados()
    proprio = _chromium_proprio()
    achados = []
    if chrome:
        achados.append("Google Chrome")
    if edge:
        achados.append("Microsoft Edge")
    if proprio:
        achados.append("Chromium do programa")
    if achados:
        return Item("Navegador", OK, "Disponível: " + ", ".join(achados) + ".", codigo="navegador")
    if NO_WINDOWS:
        return Item("Navegador", FALHA, "Nem o Google Chrome nem o Microsoft Edge foram encontrados.",
                    codigo="navegador",
                    acao=("Instale o Google Chrome ou o Microsoft Edge e rode o INSTALAR.bat de "
                          "novo (sem eles, o instalador baixa um navegador próprio)."))
    return Item("Navegador", AVISO, "Nenhum navegador compatível encontrado neste ambiente.",
                obrigatorio=False, codigo="navegador",
                acao="Instale o Chromium do Playwright: python -m playwright install chromium.")


_SONDA_NAVEGADOR = r"""
import sys, time
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    for canal in sys.argv[1:]:
        inicio = time.time()
        try:
            opcoes = {"headless": True, "timeout": 60000}
            if canal != "chromium":
                opcoes["channel"] = canal
            navegador = p.chromium.launch(**opcoes)
            pagina = navegador.new_page()
            pagina.goto("about:blank")
            navegador.close()
            print("ok", canal, "%.1f" % (time.time() - inicio), flush=True)
            sys.exit(0)
        except Exception as erro:
            texto = (str(erro).strip().splitlines() or ["?"])[0][:300]
            print("erro", canal, texto, flush=True)
sys.exit(1)
"""
_NOMES_CANAL = {"chrome": "Google Chrome", "msedge": "Microsoft Edge", "chromium": "Chromium do programa"}


def checar_teste_navegador(cfg) -> Item:
    nome = "Teste do navegador"
    if not _presente("playwright"):
        return Item(nome, FALHA, "Pulado: a biblioteca playwright não está instalada.",
                    codigo="teste_navegador", acao=RODE_O_INSTALADOR)
    canais = _canais(cfg)
    codigo, saida, erro, estourou = rodar([_python(), "-c", _SONDA_NAVEGADOR, *canais], 240)
    erros = []
    for linha in saida.splitlines():
        partes = linha.split(" ", 2)
        if partes[0] == "ok" and len(partes) >= 3:
            canal, segundos = partes[1], partes[2].replace(".", ",")
            return Item(nome, OK, f"{_NOMES_CANAL.get(canal, canal)} abriu em modo invisível em {segundos} s.",
                        codigo="teste_navegador")
        if partes[0] == "erro" and len(partes) >= 3:
            erros.append(f"{_NOMES_CANAL.get(partes[1], partes[1])}: {partes[2]}")
    if not erros:
        ultima = (erro.strip().splitlines() or [explicar_queda(None if estourou else codigo)])[-1]
        erros.append(ultima)
    situacao = FALHA if NO_WINDOWS else AVISO
    return Item(nome, situacao, "Nenhum navegador abriu. " + "; ".join(erros),
                obrigatorio=NO_WINDOWS, codigo="teste_navegador",
                acao=("Feche janelas do navegador que tenham travado, reinicie o computador e "
                      "tente de novo; se persistir, rode o INSTALAR.bat de novo."))


_SONDA_MICROFONE = r"""
import json
import sounddevice as sd
entradas = sorted({d["name"].strip() for d in sd.query_devices() if d.get("max_input_channels", 0) > 0})
try:
    padrao = sd.query_devices(kind="input")["name"]
except Exception:
    padrao = ""
print(json.dumps({"entradas": entradas, "padrao": padrao}, ensure_ascii=False), flush=True)
"""


def checar_microfone() -> Item:
    nome = "Microfone"
    if not _presente("sounddevice"):
        return Item(nome, AVISO, "A biblioteca do microfone (sounddevice) não está instalada.",
                    obrigatorio=False, codigo="microfone", acao=RODE_O_INSTALADOR)
    codigo, saida, erro, estourou = rodar([_python(), "-c", _SONDA_MICROFONE], 60)
    dados = None
    for linha in saida.splitlines():
        try:
            dados = json.loads(linha)
        except ValueError:
            continue
    if dados is None:
        ultima = (erro.strip().splitlines() or [explicar_queda(None if estourou else codigo)])[-1]
        return Item(nome, AVISO, f"Não foi possível listar os microfones: {ultima}",
                    obrigatorio=False, codigo="microfone",
                    acao="Confira se o serviço de áudio do Windows está funcionando e reinicie o computador.")
    entradas = dados.get("entradas") or []
    if not entradas:
        return Item(nome, AVISO, "Nenhum microfone encontrado.", obrigatorio=False, codigo="microfone",
                    acao=("Conecte um microfone (ou um fone com microfone). Sem ele, a transcrição "
                          "ao vivo não funciona; as demais funções, sim."))
    qtd = "1 entrada de áudio" if len(entradas) == 1 else f"{len(entradas)} entradas de áudio"
    padrao = dados.get("padrao") or entradas[0]
    return Item(nome, OK, f"{qtd}; padrão: {padrao}.", obrigatorio=False, codigo="microfone")


_CHAVE_MICROFONE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
_CAMINHO_CONFIG = ("Configurações do Windows > Privacidade e segurança > Microfone "
                   "(no Windows 10: Privacidade > Microfone)")


def avaliar_privacidade(geral: str | None, desktop: str | None, maquina: str | None) -> Item:
    """Decide o item a partir dos valores "Allow"/"Deny" do registro (puro, testável)."""
    nome = "Permissão do microfone"
    negado = [v for v in (geral, desktop, maquina) if (v or "").strip().lower() == "deny"]
    if not negado:
        return Item(nome, OK, "O Windows permite que programas da área de trabalho usem o microfone.",
                    obrigatorio=False, codigo="privacidade_microfone")
    if (maquina or "").strip().lower() == "deny":
        return Item(nome, AVISO, "O acesso ao microfone está desligado para todo o computador.",
                    obrigatorio=False, codigo="privacidade_microfone",
                    acao=f"Em {_CAMINHO_CONFIG}, ligue \u201cAcesso ao microfone\u201d (pode exigir o administrador).")
    if (geral or "").strip().lower() == "deny":
        return Item(nome, AVISO, "O acesso ao microfone está desligado nas configurações de privacidade.",
                    obrigatorio=False, codigo="privacidade_microfone",
                    acao=(f"Em {_CAMINHO_CONFIG}, ligue \u201cAcesso ao microfone\u201d e "
                          "\u201cPermitir que aplicativos da área de trabalho acessem o microfone\u201d."))
    return Item(nome, AVISO,
                "O Windows impede programas da área de trabalho de usar o microfone: a gravação sairia muda.",
                obrigatorio=False, codigo="privacidade_microfone",
                acao=(f"Em {_CAMINHO_CONFIG}, ligue \u201cPermitir que aplicativos da área de "
                      "trabalho acessem o microfone\u201d."))


def _ler_registro(raiz, chave: str) -> str | None:
    import winreg  # só existe no Windows

    try:
        with winreg.OpenKey(raiz, chave) as k:
            return str(winreg.QueryValueEx(k, "Value")[0])
    except OSError:
        return None


def checar_privacidade_microfone() -> Item:
    if not NO_WINDOWS:
        return Item("Permissão do microfone", AVISO, f"{NAO_SE_APLICA}.", obrigatorio=False,
                    codigo="privacidade_microfone")
    import winreg

    return avaliar_privacidade(
        _ler_registro(winreg.HKEY_CURRENT_USER, _CHAVE_MICROFONE),
        _ler_registro(winreg.HKEY_CURRENT_USER, _CHAVE_MICROFONE + r"\NonPackaged"),
        _ler_registro(winreg.HKEY_LOCAL_MACHINE, _CHAVE_MICROFONE))


def checar_pastas(cfg) -> Item:
    pastas = [cfg.pasta_acervo, cfg.pasta_processos, cfg.pasta_transcricoes,
              cfg.pasta_sigilosos, caminhos.LOGS]
    for pasta in pastas:
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            teste = pasta / f".teste-gravacao-{os.getpid()}-{threading.get_ident()}.tmp"
            teste.write_bytes(b"ok")
            teste.unlink()
        except PermissionError:
            return Item("Pastas de trabalho", FALHA, f"Sem permissão para gravar em {pasta}.",
                        codigo="pastas",
                        acao=("Se o \u201cAcesso controlado a pastas\u201d do Windows Defender estiver "
                              "ligado, permita o Python do programa (runtime\\python\\python.exe), ou "
                              "escolha outra pasta para o acervo em Configurações."))
        except OSError as erro:
            return Item("Pastas de trabalho", FALHA, f"Não foi possível gravar em {pasta}: {erro}",
                        codigo="pastas", acao="Confira se a pasta existe, se o disco tem espaço e se não está protegido contra gravação.")
    return Item("Pastas de trabalho", OK,
                f"As pastas do acervo ({_relativo(cfg.pasta_acervo)}), dos processos sigilosos e dos "
                "registros aceitam gravação.",
                codigo="pastas")


def _caminhos_longos() -> bool:
    if not NO_WINDOWS:
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
            return int(winreg.QueryValueEx(k, "LongPathsEnabled")[0]) == 1
    except (OSError, ValueError):
        return False


def checar_local(cfg) -> Item:
    nome = "Local da pasta"
    problemas, acoes = [], []
    raiz = str(caminhos.RAIZ)
    if caminhos.dentro_do_onedrive(caminhos.RAIZ) or caminhos.dentro_do_onedrive(cfg.pasta_acervo):
        problemas.append("está dentro do OneDrive, cuja sincronização trava arquivos em uso")
        acoes.append("instale em C:\\AssessorIntegrado (o INSTALAR.bat oferece a mudança)")
    if len(raiz) > LIMITE_CAMINHO and not _caminhos_longos():
        problemas.append(f"tem caminho longo ({len(raiz)} caracteres; acima de {LIMITE_CAMINHO}, "
                         "algumas bibliotecas passam do limite do Windows)")
        if not acoes:
            acoes.append("instale numa pasta de caminho curto, como C:\\AssessorIntegrado")
    if raiz.startswith("\\\\"):
        problemas.append("fica numa pasta de rede")
        if not acoes:
            acoes.append("instale no próprio computador, como em C:\\AssessorIntegrado")
    if problemas:
        return Item(nome, AVISO, f"A pasta {raiz} " + " e ".join(problemas) + ".",
                    obrigatorio=False, codigo="local", acao="Recomendado: " + "; ".join(acoes) + ".")
    return Item(nome, OK, f"{raiz} (fora do OneDrive, caminho curto).", obrigatorio=False, codigo="local")


def _formatar_gb(bytes_: float) -> str:
    return f"{bytes_ / 1024 ** 3:.1f}".replace(".", ",") + " GB"


def checar_espaco(cfg) -> Item:
    alvo = cfg.pasta_acervo if cfg.pasta_acervo.exists() else caminhos.RAIZ
    try:
        livre = shutil.disk_usage(alvo).free
    except OSError as erro:
        return Item("Espaço em disco", AVISO, f"Não foi possível medir: {erro}", obrigatorio=False,
                    codigo="espaco")
    if livre < 1024 ** 3:
        return Item("Espaço em disco", AVISO, f"Pouco espaço livre: {_formatar_gb(livre)}.",
                    obrigatorio=False, codigo="espaco",
                    acao=("Libere espaço: cada processo baixado ocupa de 1 a 50 MB, e cada hora de "
                          "gravação de audiência, cerca de 60 MB."))
    return Item("Espaço em disco", OK, f"{_formatar_gb(livre)} livres.", obrigatorio=False, codigo="espaco")


def checar_cofre() -> Item:
    from .nucleo.cofre_senhas import CofreSenhas

    nome = "Cofre de senhas"
    senha = "s3nh@ de teste \u00e7\u00e3o"
    with tempfile.TemporaryDirectory(prefix="assessor-verificacao-") as tmp:
        arquivo = Path(tmp) / "credenciais-teste.json"
        try:
            cofre = CofreSenhas(arquivo)
            cofre.guardar("teste:VERIFICACAO", "usuario.teste", senha)
            bruto = arquivo.read_text(encoding="utf-8")
            lido = cofre.obter("teste:VERIFICACAO")
        except Exception as erro:  # noqa: BLE001 - qualquer recusa da DPAPI vira aviso
            return Item(nome, FALHA, f"O Windows recusou cifrar a senha: {erro}", obrigatorio=False,
                        codigo="cofre",
                        acao="O programa funciona, mas pedirá a senha dos portais a cada uso.")
    if lido != ("usuario.teste", senha):
        return Item(nome, FALHA, "A senha guardada não pôde ser lida de volta.", obrigatorio=False,
                    codigo="cofre", acao="O programa funciona, mas pedirá a senha dos portais a cada uso.")
    if not NO_WINDOWS:
        return Item(nome, AVISO, f"{NAO_SE_APLICA}: aqui a senha seria apenas codificada, não cifrada.",
                    obrigatorio=False, codigo="cofre")
    if "dpapi:" not in bruto or senha in bruto:
        return Item(nome, FALHA, "A senha não foi cifrada pela proteção de dados do Windows.",
                    obrigatorio=False, codigo="cofre",
                    acao="O programa funciona, mas não marque \u201cLembrar neste computador\u201d.")
    return Item(nome, OK, "As senhas ficam cifradas pela proteção de dados do Windows (DPAPI).",
                obrigatorio=False, codigo="cofre")


def checar_tribunais() -> Item:
    from .nucleo import tribunais

    try:
        lista = tribunais.carregar()
    except Exception as erro:  # noqa: BLE001 - JSON editado à mão pode estar quebrado
        return Item("Catálogo de tribunais", FALHA,
                    f"O arquivo dados\\tribunais.json não pôde ser lido: {erro}", codigo="tribunais",
                    acao=("Desfaça a última edição do tribunais.json, ou extraia de novo o ZIP do "
                          "programa por cima desta pasta."))
    if not lista:
        return Item("Catálogo de tribunais", FALHA, "O catálogo de tribunais está vazio.", codigo="tribunais",
                    acao="Extraia de novo o ZIP do programa por cima desta pasta.")
    suportados = sum(1 for t in lista if t.suportado)
    return Item("Catálogo de tribunais", OK,
                f"{len(lista)} tribunais no catálogo; {suportados} com e-SAJ ou eProc.", codigo="tribunais")


def _falantes_situacao() -> tuple[bool, str]:
    """(disponível, descrição). Ponto único de integração com a transcrição."""
    try:
        from .transcricao import falantes

        return bool(falantes.disponivel()), str(falantes.situacao())
    except Exception:
        presente = _presente("sherpa_onnx")
        return False, "instalada só em parte" if presente else "não instalada"


def checar_falantes(completo: bool = False) -> Item:
    nome = "Separação de falantes (opcional)"
    disponivel, situacao = _falantes_situacao()
    acao = "Para instalar: Configurações > Transcrição > Instalar componente (cerca de 60 MB)."
    if not disponivel:
        return Item(nome, AVISO, f"{situacao[:1].upper()}{situacao[1:]}: a revisão final não separa as vozes sozinha.",
                    obrigatorio=False, codigo="falantes", acao=acao)
    if completo:
        r = sondar_importacoes(["sherpa_onnx"], 120).get("sherpa_onnx", {})
        if not r.get("ok"):
            return Item(nome, AVISO, f"O componente está instalado, mas não carregou: {r.get('erro', '?')}",
                        obrigatorio=False, codigo="falantes", acao=acao)
    return Item(nome, OK, "Instalada.", obrigatorio=False, codigo="falantes")


# ============================================================ conjunto

def _etapas(cfg, completo: bool) -> list[tuple[str, Callable[[], Item]]]:
    etapas: list[tuple[str, Callable[[], Item]]] = [
        ("Python e janela (Tk)", checar_python),
        ("Bibliotecas", checar_bibliotecas),
        ("Componentes nativos (DLLs)", checar_nativos),
        ("Modelo de transcrição", lambda: checar_modelo(cfg)),
    ]
    if completo:
        etapas.append(("Teste de transcrição", lambda: checar_teste_transcricao(cfg)))
    etapas.append(("Navegador", lambda: checar_navegador(cfg)))
    if completo:
        etapas.append(("Teste do navegador", lambda: checar_teste_navegador(cfg)))
    etapas += [
        ("Microfone", checar_microfone),
        ("Permissão do microfone", checar_privacidade_microfone),
        ("Pastas de trabalho", lambda: checar_pastas(cfg)),
        ("Local da pasta", lambda: checar_local(cfg)),
        ("Espaço em disco", lambda: checar_espaco(cfg)),
        ("Cofre de senhas", checar_cofre),
        ("Catálogo de tribunais", checar_tribunais),
        ("Separação de falantes (opcional)", lambda: checar_falantes(completo)),
    ]
    return etapas


def _protegido(nome: str, funcao: Callable[[], Item]) -> Item:
    """Uma checagem que quebra vira item de falha; a verificação segue."""
    try:
        item = funcao()
        if item.situacao not in SITUACOES:  # pragma: no cover - defesa
            item.situacao = FALHA
        return item
    except Exception as erro:  # noqa: BLE001
        log.exception("falha inesperada ao verificar %s", nome)
        return Item(nome, FALHA, f"Erro inesperado na verificação: {type(erro).__name__}: {erro}",
                    obrigatorio=False)


def verificar(completo: bool = False, cfg=None,
              ao_item: Callable[[Item], None] | None = None) -> list[Item]:
    """Roda todas as checagens; devolve os itens na ordem de exibição.

    Pode ser chamada de uma thread de trabalho da janela (não toca no Tk do
    processo). `ao_item` recebe cada item assim que fica pronto, na ordem.
    As checagens que rodam em processo à parte andam em paralelo.
    """
    if cfg is None:
        from .nucleo import config

        cfg = config.carregar()
    etapas = _etapas(cfg, completo)
    itens: list[Item] = []
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="verificar") as pool:
        futuros = [(nome, pool.submit(_protegido, nome, funcao)) for nome, funcao in etapas]
        for nome, futuro in futuros:
            item = futuro.result()
            itens.append(item)
            log.info("verificação: %s - %s - %s", item.situacao, item.nome, item.detalhe)
            if ao_item is not None:
                try:
                    ao_item(item)
                except Exception:  # pragma: no cover - a tela nunca derruba a verificação
                    log.exception("falha ao mostrar item da verificação")
    return itens


def resumir(itens: list[Item]) -> dict:
    """{"resultado": ok|aviso|falha, "ok": n, "aviso": n, "falha": n}."""
    contagem = {OK: 0, AVISO: 0, FALHA: 0}
    for i in itens:
        contagem[i.situacao] = contagem.get(i.situacao, 0) + 1
    if not itens or any(i.situacao == FALHA and i.obrigatorio for i in itens):
        resultado = FALHA
    elif any(i.situacao != OK for i in itens):
        resultado = AVISO
    else:
        resultado = OK
    return {"resultado": resultado, **contagem}


def _contar(n: int, singular: str, plural: str, nenhum: str) -> str:
    if n == 0:
        return nenhum
    return f"1 {singular}" if n == 1 else f"{n} {plural}"


def frase_final(resumo: dict) -> str:
    contagem = (f"{resumo[OK]} OK, {_contar(resumo[AVISO], 'aviso', 'avisos', 'nenhum aviso')} e "
                f"{_contar(resumo[FALHA], 'falha', 'falhas', 'nenhuma falha')}")
    if resumo["resultado"] == OK:
        return f"Resultado: {contagem}. Tudo certo: a instalação está pronta."
    if resumo["resultado"] == AVISO:
        return f"Resultado: {contagem}. A instalação está pronta, com avisos (veja acima o que fazer)."
    return (f"Resultado: {contagem}. A instalação tem problemas: veja acima o que fazer e rode o "
            "INSTALAR.bat de novo.")


ROTULOS = {OK: "OK", AVISO: "AVISO", FALHA: "FALHA"}


def formatar_item(item: Item, largura: int = 100) -> str:
    rotulo = ROTULOS.get(item.situacao, item.situacao.upper())
    if item.situacao == FALHA and not item.obrigatorio:
        rotulo = "FALHA*"
    linhas = [f"  {rotulo:<7}{item.nome:<34}{item.detalhe}"]
    if item.acao and item.situacao != OK:
        # Espaço fixo entre o número e a unidade: a quebra de linha não deixa
        # "60" numa linha e "MB" na outra.
        acao = re.sub(r"(\d) (MB|GB|KB|s)\b", "\\1\u00a0\\2", item.acao)
        linhas += textwrap.wrap("O que fazer: " + acao, width=largura,
                                initial_indent=" " * 9, subsequent_indent=" " * 9)
    return "\n".join(linhas)


def cabecalho(completo: bool) -> str:
    tipo = "completa" if completo else "rápida"
    return (f"{NOME} {__version__} \u2014 verificação {tipo} da instalação\n"
            f"Pasta: {caminhos.RAIZ}\n")


def relatorio_texto(itens: list[Item], completo: bool = False) -> str:
    """O mesmo texto do console (para copiar e mandar ao suporte)."""
    partes = [cabecalho(completo)] + [formatar_item(i) for i in itens]
    if any(i.situacao == FALHA and not i.obrigatorio for i in itens):
        partes.append("  * falha em item opcional: não impede o uso do programa.")
    partes.append("\n" + frase_final(resumir(itens)))
    return "\n".join(partes)


def para_json(itens: list[Item], completo: bool) -> dict:
    resumo = resumir(itens)
    return {
        "programa": NOME,
        "versao": __version__,
        "data": datetime.now().isoformat(timespec="seconds"),
        "completo": completo,
        "plataforma": platform.platform(),
        "python": platform.python_version(),
        "pasta": str(caminhos.RAIZ),
        "resultado": resumo["resultado"],
        "resumo": {OK: resumo[OK], AVISO: resumo[AVISO], FALHA: resumo[FALHA]},
        "itens": [asdict(i) for i in itens],
    }


def gravar_json(destino: Path, itens: list[Item], completo: bool) -> None:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(json.dumps(para_json(itens, completo), ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, destino)


USO = """\
Uso: python -m app verificar [--completo] [--json ARQUIVO]

  --completo      também carrega o modelo de transcrição (1 s de silêncio) e
                  abre o navegador em modo invisível (leva cerca de 1 minuto)
  --json ARQUIVO  grava o resultado em JSON
  --ajuda         mostra esta ajuda

Código de saída: 0 = instalação pronta (talvez com avisos); 1 = falha em item
obrigatório; 2 = opção desconhecida."""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    completo = False
    destino: Path | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--completo", "-c"):
            completo = True
        elif a == "--json":
            if i + 1 >= len(args):
                print("Faltou o nome do arquivo depois de --json.\n\n" + USO)
                return 2
            destino = Path(args[i + 1])
            i += 1
        elif a.startswith("--json="):
            destino = Path(a.split("=", 1)[1])
        elif a in ("-h", "--help", "--ajuda", "ajuda"):
            print(USO)
            return 0
        else:
            print(f"Opção desconhecida: {a}\n\n{USO}")
            return 2
        i += 1

    try:
        from .nucleo import registro

        registro.configurar(console=False)
    except Exception:  # pragma: no cover - sem log, a verificação segue
        pass
    print(cabecalho(completo), flush=True)
    itens = verificar(completo, ao_item=lambda item: print(formatar_item(item), flush=True))
    if any(i.situacao == FALHA and not i.obrigatorio for i in itens):
        print("  * falha em item opcional: não impede o uso do programa.")
    resumo = resumir(itens)
    print("\n" + frase_final(resumo), flush=True)
    if destino is not None:
        try:
            gravar_json(destino, itens, completo)
        except OSError as erro:
            print(f"Não foi possível gravar {destino}: {erro}")
    return 1 if resumo["resultado"] == FALHA else 0


if __name__ == "__main__":
    sys.exit(main())
