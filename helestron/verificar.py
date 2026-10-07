"""Confere a instalação: o que funciona, o que falta e como corrigir.

    python -m helestron verificar               conferência rápida (alguns segundos)
    python -m helestron verificar --completo    também carrega o modelo e transcreve
                                          1 s de silêncio, e abre o navegador
                                          em modo invisível
    python -m helestron verificar --json ARQ    grava o resultado em JSON

Cada item sai como "ok", "aviso" ou "falha". Falha em item obrigatório
reprova a instalação (código de saída 1). Aviso nunca reprova: é o que
funciona com limitação (sem microfone, conector ainda não ligado) ou o que
não se aplica fora do Windows (DPAPI, WebView2, privacidade do microfone).

O que se confere, no modelo do Helestron (instalador próprio, Python e
bibliotecas embutidos, dados em %LOCALAPPDATA%\\Helestron, documentos em
Documentos\\Helestron): Windows 10/11 de 64 bits; as bibliotecas e os
componentes nativos; o modelo de transcrição embutido (presente e, na
conferência completa, carregado de verdade); o navegador dos portais
(Chrome ou Edge); o WebView2 da janela; o microfone e a permissão do
Windows; as pastas (graváveis e separadas como o sigilo exige); o cofre de
senhas; o catálogo de tribunais; a separação de falantes; o conector MCP do
acervo (que responde de verdade, como o Claude Desktop o chamaria).

Por que tantos testes rodam num processo separado: importar onnxruntime ou
ctranslate2 num processador sem as instruções esperadas, ou com DLL do
Visual C++ faltando, pode DERRUBAR o processo sem exceção nenhuma - e a
verificação morreria junto, calada. No processo-filho, a queda vira um
diagnóstico ("o processo caiu ao carregar onnxruntime"). Também não mexe no
programa aberto, que pode estar chamando esta mesma verificação: o PortAudio,
por exemplo, guarda a lista de microfones do momento em que foi iniciado (o
filho enxerga a lista atual).
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
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import NOME, __version__
from .nucleo import caminhos
from .nucleo.sistema import REINSTALAR

log = logging.getLogger("verificar")

OK, AVISO, FALHA = "ok", "aviso", "falha"
SITUACOES = (OK, AVISO, FALHA)
NO_WINDOWS = sys.platform == "win32"
NAO_SE_APLICA = "Não se aplica fora do Windows"
RODE_O_INSTALADOR = REINSTALAR
LIMITE_CAMINHO = 100
# Onde a tela de Ajustes mostra cada assunto (as ações citam o caminho).
AJUSTES_PASTAS = "Ajustes › Pastas"
AJUSTES_TRANSCRICAO = "Ajustes › Transcrição"
AJUSTES_COMPARTILHAR = "Ajustes › Compartilhar"
AJUSTES_ACESSOS = "Ajustes › Acessos aos portais"

# (módulo, distribuição no PyPI, para que serve, só no Windows)
BIBLIOTECAS: tuple[tuple[str, ...], ...] = (
    ("faster_whisper", "faster-whisper", "transcrição"),
    ("ctranslate2", "ctranslate2", "transcrição"),
    ("onnxruntime", "onnxruntime", "detector de voz"),
    ("av", "av", "leitura de áudio"),
    ("numpy", "numpy", "processamento do áudio"),
    ("sounddevice", "sounddevice", "microfone"),
    ("soundfile", "soundfile", "gravação em FLAC"),
    ("huggingface_hub", "huggingface-hub", "download de outros modelos"),
    ("docx", "python-docx", "documentos do Word"),
    ("pymupdf", "pymupdf", "PDF"),
    ("pypdf", "pypdf", "PDF"),
    ("openpyxl", "openpyxl", "planilhas do Excel"),
    ("xlrd", "xlrd", "planilhas antigas do Excel (.xls)"),
    ("playwright", "playwright", "acesso aos portais"),
    ("PIL", "pillow", "imagens"),
    ("webview", "pywebview", "janela do programa", "windows"),
    ("clr", "pythonnet", "janela do programa", "windows"),
    ("bottle", "bottle", "janela do programa", "windows"),
    ("proxy_tools", "proxy_tools", "janela do programa", "windows"),
)
# O sherpa-onnx (separação de falantes) fica de fora de propósito: é opcional,
# e o item "Separação de falantes" o confere sem reprovar a instalação.
# Os que trazem DLL própria: importados de verdade, num processo à parte.
NATIVOS = ("numpy", "ctranslate2", "onnxruntime", "av", "sounddevice", "soundfile",
           "pymupdf", "faster_whisper", "playwright.sync_api")
NOMES_AMIGAVEIS = {"av": "PyAV", "pymupdf": "PyMuPDF", "playwright.sync_api": "Playwright",
                   "faster_whisper": "faster-whisper", "sounddevice": "PortAudio",
                   "soundfile": "libsndfile", "sherpa_onnx": "sherpa-onnx"}

# O WebView2 Runtime (a janela do programa) se registra no EdgeUpdate com
# este identificador: em HKLM (instalação para o computador, 64 ou 32 bits)
# ou em HKCU (instalação só para o usuário).
GUID_WEBVIEW2 = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
CHAVES_WEBVIEW2 = (
    ("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{GUID_WEBVIEW2}"),
    ("HKLM", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{GUID_WEBVIEW2}"),
    ("HKCU", rf"Software\Microsoft\EdgeUpdate\Clients\{GUID_WEBVIEW2}"),
)
URL_WEBVIEW2 = "https://developer.microsoft.com/microsoft-edge/webview2/"
# A pywebview 6 usa uma interface do WebView2 (ICoreWebView2Environment10) que
# só existe a partir deste runtime; com um mais velho, a janela abriria vazia,
# e o programa abre no Edge em modo aplicativo (helestron.aplicativo.janela).
VERSAO_MINIMA_WEBVIEW2 = (101, 0, 1210, 39)

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
    codigo: str = ""            # identificador estável (a tela pode usá-lo num botão "Corrigir")
    acao: str = ""              # o que fazer, numa frase

    @property
    def ok(self) -> bool:
        return self.situacao == OK


# ===================================================== processos à parte

def _python() -> str:
    """O python.exe do programa (com console: o pythonw não devolve saída)."""
    return str(caminhos.python_exe(janela=False))


def _pasta_de_trabalho() -> str:
    pasta = Path(caminhos.INSTALACAO)
    return str(pasta if pasta.is_dir() else Path.cwd())


def _ambiente_filho(extra_pythonpath: list[str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    # PYTHONHOME global (deixado por outro programa) quebra o Python embutido
    # logo na partida; o pacote "do usuário" de outro Python misturaria versões.
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Instalado, o pacote está no Lib\site-packages do próprio Python; no
    # repositório, entra pelo PYTHONPATH.
    caminho = ([] if caminhos.INSTALADO else [str(caminhos.PACOTE.parent)])
    caminho += list(extra_pythonpath or [])
    if caminho:
        env["PYTHONPATH"] = os.pathsep.join(caminho)
    else:
        env.pop("PYTHONPATH", None)
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    env.setdefault("HF_HUB_OFFLINE", "1")   # o teste do modelo nunca vai à rede
    return env


def _texto(dados) -> str:
    if dados is None:
        return ""
    if isinstance(dados, bytes):
        return dados.decode("utf-8", errors="replace")
    return str(dados)


def rodar(argumentos: list[str], limite_s: float, extra_pythonpath: list[str] | None = None,
          sem_novidade_s: float | None = None) -> tuple[int | None, str, str, bool]:
    """(código de saída, stdout, stderr, estourou o tempo). Nunca levanta.

    'sem_novidade_s': desiste também se o processo passar esse tempo sem
    escrever uma linha na saída - uma biblioteca nativa que trava (uma caixa
    de erro do Windows que ninguém vê, por exemplo) não prende a verificação
    até o limite total.
    """
    if sem_novidade_s is not None:
        return _rodar_vigiado(argumentos, limite_s, sem_novidade_s, extra_pythonpath)
    try:
        r = subprocess.run(
            argumentos, capture_output=True, timeout=limite_s, cwd=_pasta_de_trabalho(),
            env=_ambiente_filho(extra_pythonpath), stdin=subprocess.DEVNULL,
            creationflags=0x08000000 if NO_WINDOWS else 0)   # CREATE_NO_WINDOW
        return r.returncode, _texto(r.stdout), _texto(r.stderr), False
    except subprocess.TimeoutExpired as erro:
        return None, _texto(erro.stdout), _texto(erro.stderr), True
    except OSError as erro:
        return -1, "", str(erro), False


def _rodar_vigiado(argumentos: list[str], limite_s: float, sem_novidade_s: float,
                   extra_pythonpath: list[str] | None) -> tuple[int | None, str, str, bool]:
    try:
        proc = subprocess.Popen(
            argumentos, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            cwd=_pasta_de_trabalho(), env=_ambiente_filho(extra_pythonpath),
            creationflags=0x08000000 if NO_WINDOWS else 0)
    except OSError as erro:
        return -1, "", str(erro), False
    saida: list[bytes] = []
    erros: list[bytes] = []
    ultimo = [time.monotonic()]

    def ler(cano, destino: list[bytes], marca: bool) -> None:
        for linha in iter(cano.readline, b""):
            destino.append(linha)
            if marca:
                ultimo[0] = time.monotonic()
        cano.close()

    leitores = [threading.Thread(target=ler, args=(proc.stdout, saida, True), daemon=True),
                threading.Thread(target=ler, args=(proc.stderr, erros, False), daemon=True)]
    for leitor in leitores:
        leitor.start()
    inicio = time.monotonic()
    estourou = False
    while proc.poll() is None:
        agora = time.monotonic()
        if agora - inicio > limite_s or agora - ultimo[0] > sem_novidade_s:
            estourou = True
            proc.kill()
            break
        time.sleep(0.1)
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:  # pragma: no cover - defesa
        pass
    for leitor in leitores:
        leitor.join(5)
    codigo = None if estourou else proc.returncode
    return codigo, _texto(b"".join(saida)), _texto(b"".join(erros)), estourou


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


# Quanto um único módulo pode levar para carregar (antivírus conferindo cada
# DLL, computador lento) antes de ser dado como travado.
LIMITE_POR_MODULO_S = 120.0


def sondar_importacoes(modulos: list[str] | tuple[str, ...], limite_s: float = 180.0,
                       extra_pythonpath: list[str] | None = None,
                       por_modulo_s: float | None = None,
                       total_s: float | None = None) -> dict[str, dict]:
    """Importa cada módulo num processo à parte e diz o que aconteceu.

    {"modulo": {"ok": True, "versao": "1.2"} | {"ok": False, "erro": "...", "queda": bool}}.
    Se o processo cair (ou travar) no meio, o módulo que estava sendo
    importado é o culpado; os seguintes são tentados de novo num processo
    novo. 'limite_s' vale para cada processo; um módulo que passe
    'por_modulo_s' sem terminar é dado como travado; com 'total_s', o que
    não couber nesse tempo sai como não conferido.
    """
    pendentes = list(modulos)
    resultado: dict[str, dict] = {}
    por_modulo = min(limite_s, por_modulo_s or LIMITE_POR_MODULO_S)
    prazo = time.monotonic() + total_s if total_s else None
    while pendentes:
        limite = limite_s
        if prazo is not None:
            limite = min(limite_s, prazo - time.monotonic())
            if limite <= 1:
                for m in pendentes:
                    resultado[m] = {"ok": False, "queda": True,
                                    "erro": "não foi conferido: a verificação passou do tempo"}
                break
        codigo, saida, erro, estourou = rodar(
            [_python(), "-c", _SONDA_IMPORTACAO, *pendentes], limite, extra_pythonpath,
            sem_novidade_s=min(limite, por_modulo))
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
        if estourou:
            motivo = "o carregamento travou (não terminou no tempo esperado)"
        else:
            motivo = f"o processo caiu ao carregar ({explicar_queda(codigo)})"
        resultado[em_curso] = {"ok": False, "queda": True, "erro": motivo}
        pendentes = [m for m in restantes if m != em_curso]
    return resultado


# ============================================================ os itens

def _relativo(p: Path | str) -> str:
    """Caminho dentro da pasta do programa ou da de dados, sem o começo comprido."""
    for base, rotulo in ((caminhos.INSTALACAO, "pasta do programa"), (caminhos.LOCAL, "dados")):
        try:
            resto = Path(p).resolve().relative_to(Path(base).resolve())
            return f"{resto} ({rotulo})"
        except (ValueError, OSError, RuntimeError):
            continue
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


# ------------------------------------------------------------ sistema
def avaliar_sistema(sistema: str, build: int, maquina: str, python_64: bool) -> Item:
    """Decide o item do sistema operacional a partir dos fatos (puro, testável).

    'sistema' é o platform.system(); 'build', o número de compilação do
    Windows (0 fora dele); 'maquina', o platform.machine().
    """
    nome = "Windows 64 bits"
    py = f"Python {platform.python_version()}"
    if sistema != "Windows":
        return Item(nome, AVISO, f"{NAO_SE_APLICA} ({sistema or 'outro sistema'}; {py}).",
                    obrigatorio=False, codigo="sistema")
    maquina = (maquina or "").upper()
    if maquina not in ("AMD64", "X86_64", "ARM64") or not python_64:
        return Item(nome, FALHA, "Este Windows (ou o Python do programa) é de 32 bits.",
                    codigo="sistema",
                    acao=("O Helestron precisa do Windows 10 ou 11 de 64 bits. Se o Windows é de "
                          f"64 bits, {REINSTALAR[0].lower()}{REINSTALAR[1:]}"))
    if build and build < 10240:
        return Item(nome, FALHA, f"Versão do Windows antiga demais (compilação {build}).",
                    codigo="sistema", acao="O Helestron precisa do Windows 10 ou 11 de 64 bits.")
    versao = "Windows 11" if build >= 22000 else "Windows 10"
    arq = "ARM 64 bits" if maquina == "ARM64" else "64 bits"
    return Item(nome, OK, f"{versao} (compilação {build}), {arq}; {py}.", codigo="sistema")


def checar_sistema() -> Item:
    build = 0
    if NO_WINDOWS:
        try:
            build = int(sys.getwindowsversion().build)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defesa
            build = 0
    return avaliar_sistema(platform.system(), build, platform.machine(), sys.maxsize > 2 ** 32)


def checar_bibliotecas() -> Item:
    faltam = [f"{b[1]} ({b[2]})" for b in BIBLIOTECAS
              if (len(b) < 4 or NO_WINDOWS) and not _presente(b[0])]
    if faltam:
        return Item("Bibliotecas", FALHA, "Faltam: " + ", ".join(faltam) + ".",
                    codigo="bibliotecas", acao=RODE_O_INSTALADOR)
    principais = []
    for dist in ("faster-whisper", "playwright", "pymupdf", "pywebview"):
        v = _versao(dist)
        if v:
            principais.append(f"{dist} {v}")
    conferidas = sum(1 for b in BIBLIOTECAS if len(b) < 4 or NO_WINDOWS)
    detalhe = f"As {conferidas} bibliotecas estão presentes"
    if principais:
        detalhe += " (" + ", ".join(principais) + ")"
    return Item("Bibliotecas", OK, detalhe + ".", codigo="bibliotecas")


def checar_nativos() -> Item:
    modulos = [m for m in NATIVOS if _presente(m.split(".")[0])]
    if not modulos:
        return Item("Componentes nativos (DLLs)", FALHA,
                    "Nenhuma das bibliotecas nativas está instalada.",
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


# ------------------------------------------------------------- modelo
def _modelos():
    """O módulo de modelos da transcrição (ponto único de integração)."""
    from .transcricao import modelos

    return modelos


def _modelo_instalado(nome: str) -> tuple[bool, Path, bool]:
    """(instalado, pasta, veio no instalador)."""
    try:
        m = _modelos()
        embutido = getattr(m, "embutido", lambda _n: False)
        return m.instalado(nome), m.pasta_do_modelo(nome), bool(embutido(nome))
    except (ImportError, ValueError):
        for base, veio in ((caminhos.MODELOS_EMBUTIDOS, True), (caminhos.MODELOS, False)):
            pasta = Path(base) / f"faster-whisper-{nome}"
            bin_ = pasta / "model.bin"
            if (all((pasta / a).is_file() for a in ("config.json", "tokenizer.json"))
                    and bin_.is_file() and bin_.stat().st_size > 1_000_000):
                return True, pasta, veio
        return False, Path(caminhos.MODELOS) / f"faster-whisper-{nome}", False


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


def _componentes_embutidos() -> dict:
    """O que a construção declarou ter embutido (a chave 'componentes' do
    manifesto.json: {"modelo_transcricao": "faster-whisper-small" ou "",
    "falantes": bool}). Vazio fora da instalação e no manifesto sem a chave."""
    if not caminhos.INSTALADO:
        return {}
    try:
        dados = json.loads((Path(caminhos.INSTALACAO) / "manifesto.json")
                           .read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    comp = dados.get("componentes") if isinstance(dados, dict) else None
    return comp if isinstance(comp, dict) else {}


def checar_modelo(cfg) -> Item:
    ao_vivo, revisao = _nomes_dos_modelos(cfg)
    instalado, pasta, embutido = _modelo_instalado(ao_vivo)
    declarado = _componentes_embutidos().get("modelo_transcricao")
    if not instalado and isinstance(declarado, str) and declarado == f"faster-whisper-{ao_vivo}":
        # Veio no instalador e sumiu da pasta do programa (antivírus, cópia
        # interrompida): não é "baixado no primeiro uso", é instalação com defeito.
        return Item("Modelo de transcrição", FALHA,
                    f"O modelo da transcrição ao vivo ({ao_vivo}) veio com o programa, mas não "
                    "está mais na pasta do programa (o antivírus pode tê-lo retirado).",
                    obrigatorio=False, codigo="modelo", acao=REINSTALAR)
    rev_ok, _, _ = _modelo_instalado(revisao)
    if revisao == ao_vivo:
        sobre_revisao = ""
    elif rev_ok:
        sobre_revisao = f" O da revisão final ({revisao}) também está instalado."
    else:
        sobre_revisao = (f" O da revisão final ({revisao}) será baixado no primeiro uso "
                         f"(cerca de {_tamanho_mb(revisao)} MB).")
    if instalado:
        origem = "embutido no programa" if embutido else "baixado"
        return Item("Modelo de transcrição", OK,
                    f"Ao vivo: {ao_vivo}, {origem} ({_relativo(pasta)}).{sobre_revisao}",
                    obrigatorio=False, codigo="modelo")
    return Item("Modelo de transcrição", AVISO,
                f"O modelo da transcrição ao vivo ({ao_vivo}) não está neste computador.",
                obrigatorio=False, codigo="modelo",
                acao=(f"Ele é baixado no primeiro uso (cerca de {_tamanho_mb(ao_vivo)} MB). "
                      f"Para baixar agora: {AJUSTES_TRANSCRICAO}, botão \u201cBaixar\u201d."))


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
    """Carrega o modelo da audiência de verdade e transcreve 1 s de silêncio."""
    ao_vivo, _ = _nomes_dos_modelos(cfg)
    instalado, pasta, embutido = _modelo_instalado(ao_vivo)
    nome = "Teste de transcrição"
    if not instalado:
        return Item(nome, AVISO, f"Pulado: o modelo {ao_vivo} ainda não está neste computador.",
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
    if embutido:
        acao = f"O modelo que veio com o programa não abriu. {REINSTALAR}"
    else:
        acao = (f"Apague a pasta {pasta} e baixe o modelo de novo em {AJUSTES_TRANSCRICAO}, "
                "botão \u201cBaixar\u201d.")
    if not nativo.isascii():
        # Acento no caminho e nenhum nome curto 8.3 neste disco: se a causa
        # for essa, instalar ou baixar de novo no mesmo lugar não resolve.
        acao += (" Se persistir, instale o Helestron numa pasta sem acento no caminho, como "
                 "C:\\Helestron (o instalador deixa escolher a pasta).")
    return Item(nome, FALHA, f"O modelo {ao_vivo} não funcionou: {motivo}",
                codigo="teste_transcricao", acao=acao)


# ---------------------------------------------------------- navegador
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


def _chromium_reserva() -> str:
    """O Chromium do Playwright que já estiver neste computador (o programa não
    o baixa: é só reserva), ou ''."""
    try:
        from .download import navegador

        return navegador.chromium_reserva()
    except Exception:
        return ""


def _canais(cfg) -> list[str]:
    """Ordem de tentativa, como o download faria: "chrome", "msedge", "chromium"."""
    chrome, edge = _navegadores_instalados()
    try:
        from .download import navegador

        ordem = navegador.escolher_canais(cfg.texto("download", "navegador") or "auto",
                                          chrome=chrome, edge=edge,
                                          chromium=_chromium_reserva())
        return [c or "chromium" for c in ordem]
    except Exception:
        ordem = (["chrome"] if chrome else []) + (["msedge"] if edge else [])
        return ordem + (["chromium"] if _chromium_reserva() else [])


def checar_navegador(cfg) -> Item:
    nome = "Navegador dos portais"
    chrome, edge = _navegadores_instalados()
    achados = []
    if chrome:
        achados.append("Google Chrome")
    if edge:
        achados.append("Microsoft Edge")
    if achados:
        return Item(nome, OK, "Disponível: " + ", ".join(achados) + ".", codigo="navegador")
    reserva = _chromium_reserva()
    if reserva:
        return Item(nome, AVISO,
                    "Nem o Google Chrome nem o Microsoft Edge foram encontrados; o download usará "
                    "o Chromium do Playwright que já está neste computador.",
                    obrigatorio=False, codigo="navegador",
                    acao="Instale o Microsoft Edge ou o Google Chrome: é com eles que o Helestron é testado.")
    if NO_WINDOWS:
        # Falha, mas não obrigatória: a instalação está boa e a transcrição
        # funciona; só o acesso aos portais (download e pauta) depende disto.
        return Item(nome, FALHA, "Nem o Google Chrome nem o Microsoft Edge foram encontrados.",
                    obrigatorio=False, codigo="navegador",
                    acao=("O Microsoft Edge vem com o Windows 10 e 11: se ele foi removido, "
                          "instale-o de novo (ou instale o Google Chrome). Sem um dos dois, o "
                          "download de processos e a pauta não funcionam."))
    return Item(nome, AVISO, "Nenhum navegador compatível encontrado neste ambiente.",
                obrigatorio=False, codigo="navegador",
                acao="Instale o Google Chrome ou o Microsoft Edge.")


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
_NOMES_CANAL = {"chrome": "Google Chrome", "msedge": "Microsoft Edge",
                "chromium": "Chromium (reserva do Playwright)"}


def checar_teste_navegador(cfg) -> Item:
    nome = "Teste do navegador"
    if not _presente("playwright"):
        return Item(nome, FALHA, "Pulado: a biblioteca playwright não está instalada.",
                    codigo="teste_navegador", acao=RODE_O_INSTALADOR)
    canais = _canais(cfg)
    if not canais:
        return Item(nome, AVISO, "Pulado: não há navegador para testar.", obrigatorio=False,
                    codigo="teste_navegador")
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
    # Aviso, e não falha: sem navegador, só o acesso aos portais fica de
    # fora - a transcrição e o compartilhamento funcionam, e a instalação
    # não pode sair "em vermelho" por uma regra da TI que bloqueie o modo
    # invisível.
    return Item(nome, AVISO, "Nenhum navegador abriu. " + "; ".join(erros),
                obrigatorio=False, codigo="teste_navegador",
                acao=("Feche janelas do navegador que tenham travado, reinicie o computador e "
                      "tente de novo; se persistir, fale com a informática do tribunal (alguma "
                      "regra pode estar bloqueando o navegador automático)."))


# ------------------------------------------------------------ WebView2
def _versao_numerica(texto) -> tuple[int, ...] | None:
    """'101.0.1210.39' -> (101, 0, 1210, 39); None se não for uma versão."""
    partes = str(texto or "").strip().split(".")
    if not partes or not all(p.isdigit() for p in partes):
        return None
    numeros = tuple(int(p) for p in partes[:4])
    return numeros + (0,) * (4 - len(numeros))


def avaliar_webview2(versoes: list[str | None]) -> Item:
    """Decide o item a partir das versões ("pv") lidas do registro (puro, testável).

    Vale a maior das versões instaladas (a que a pywebview usa). Abaixo da
    101.0.1210.39 a janela própria não abre: o Helestron funciona no Edge em
    modo aplicativo, e o item é aviso, com a orientação de atualizar.
    """
    nome = "WebView2 (janela do programa)"
    validas = []
    for v in versoes:
        numero = _versao_numerica(v)
        if numero is not None and any(numero):
            validas.append((numero, str(v).strip()))
    minima = ".".join(str(n) for n in VERSAO_MINIMA_WEBVIEW2)
    if validas:
        numero, texto = max(validas)
        if numero >= VERSAO_MINIMA_WEBVIEW2:
            return Item(nome, OK, f"Microsoft Edge WebView2 Runtime {texto} instalado.",
                        obrigatorio=False, codigo="webview2")
        return Item(nome, AVISO,
                    f"O Microsoft Edge WebView2 Runtime deste computador é antigo (versão "
                    f"{texto}; o Helestron precisa da {minima} ou de uma mais recente).",
                    obrigatorio=False, codigo="webview2",
                    acao=("O Helestron funciona assim mesmo: abre no Microsoft Edge, em modo "
                          "aplicativo. Para a janela própria, atualize o \u201cMicrosoft Edge "
                          "WebView2 Runtime\u201d (gratuito, da Microsoft, sem administrador): "
                          f"{URL_WEBVIEW2}. Se o computador é do tribunal, peça a atualização "
                          "à informática."))
    return Item(nome, AVISO, "O Microsoft Edge WebView2 Runtime não foi encontrado.",
                obrigatorio=False, codigo="webview2",
                acao=("O Helestron funciona assim mesmo: abre no Microsoft Edge, em modo "
                      "aplicativo. Para a janela própria, instale o \u201cMicrosoft Edge "
                      "WebView2 Runtime\u201d (gratuito, da Microsoft, sem administrador): "
                      f"{URL_WEBVIEW2}."))


def _ler_valor(raiz, chave: str, valor: str) -> str | None:
    import winreg  # só existe no Windows

    try:
        with winreg.OpenKey(raiz, chave) as k:
            return str(winreg.QueryValueEx(k, valor)[0])
    except OSError:
        return None


def versoes_webview2() -> list[str | None]:
    """As versões ("pv") do WebView2 Runtime no registro, nas três chaves."""
    if not NO_WINDOWS:
        return []
    import winreg

    raizes = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    return [_ler_valor(raizes[raiz], chave, "pv") for raiz, chave in CHAVES_WEBVIEW2]


def checar_webview2() -> Item:
    if not NO_WINDOWS:
        return Item("WebView2 (janela do programa)", AVISO, f"{NAO_SE_APLICA}.",
                    obrigatorio=False, codigo="webview2")
    return avaliar_webview2(versoes_webview2())


# ----------------------------------------------------------- microfone
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
_CAMINHO_CONFIG = ("Configurações do Windows › Privacidade e segurança › Microfone "
                   "(no Windows 10: Privacidade › Microfone)")


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
    return _ler_valor(raiz, chave, "Value")


def checar_privacidade_microfone() -> Item:
    if not NO_WINDOWS:
        return Item("Permissão do microfone", AVISO, f"{NAO_SE_APLICA}.", obrigatorio=False,
                    codigo="privacidade_microfone")
    import winreg

    return avaliar_privacidade(
        _ler_registro(winreg.HKEY_CURRENT_USER, _CHAVE_MICROFONE),
        _ler_registro(winreg.HKEY_CURRENT_USER, _CHAVE_MICROFONE + r"\NonPackaged"),
        _ler_registro(winreg.HKEY_LOCAL_MACHINE, _CHAVE_MICROFONE))


# --------------------------------------------------------------- pastas
def _contem(pai: Path, filho: Path) -> bool:
    """'filho' é 'pai' ou fica dentro dele (caminhos reais)?"""
    try:
        return Path(filho).resolve().is_relative_to(Path(pai).resolve())
    except (OSError, RuntimeError, ValueError):
        return False


_ACAO_PASTAS = ("Corrija antes de compartilhar o acervo: em " + AJUSTES_PASTAS + ", use "
                "\u201cAlterar\u2026\u201d para escolher {}.")


def _pasta_pauta(cfg) -> Path:
    propria = getattr(cfg, "pasta_pauta", None)
    if isinstance(propria, Path):
        return propria
    return caminhos.resolver(cfg.texto("pauta", "pasta"), "Pauta")


def _problema_nas_pastas(cfg) -> tuple[str, str] | None:
    """(o problema, o que fazer) se a pasta do acervo levaria à IA o que não
    pode ir; None se está tudo separado.

    Tudo o que está no acervo é lido pela IA (Claude Code, Cowork, ChatGPT
    Work) e copiado para a nuvem. A regra acervo x sigilosos x pauta é a do
    núcleo (config.conflito_de_pastas), a mesma da tela de Ajustes.
    """
    from .nucleo import config

    acervo = cfg.pasta_acervo
    frase = config.conflito_de_pastas(acervo, cfg.pasta_sigilosos, _pasta_pauta(cfg))
    if frase:
        return (frase + " Do jeito que está, o que é de segredo de justiça iria para a IA "
                "junto com o acervo.",
                _ACAO_PASTAS.format("pastas separadas para o acervo, os sigilosos e a pauta "
                                    "(nenhuma dentro da outra)"))
    # A pasta da nuvem do espelho (gravada à mão no config.ini, ou antes desta
    # regra): os sigilosos ou a pauta dentro dela iriam para o OneDrive ou o
    # Google Drive - a mesma regra da tela de Ajustes (config.conflito_com_a_nuvem).
    try:
        nuvem = str(cfg.texto("compartilhar", "pasta_nuvem") or "").strip()
    except Exception:  # noqa: BLE001 - configuração sem a seção: não há espelho
        nuvem = ""
    frase = config.conflito_com_a_nuvem(nuvem, cfg.pasta_sigilosos, _pasta_pauta(cfg))
    if frase:
        return (f"{frase} (pasta da nuvem: {nuvem})",
                "Corrija antes de espelhar o acervo: em " + AJUSTES_PASTAS + ", escolha para os "
                "sigilosos e a pauta pastas fora da nuvem, ou, em " + AJUSTES_COMPARTILHAR
                + ", outra pasta da nuvem (em branco, o acervo não é espelhado).")
    if caminhos.INSTALADO and _contem(acervo, caminhos.INSTALACAO):
        return (f"A pasta do acervo ({acervo}) contém a pasta do programa "
                f"({caminhos.INSTALACAO}), que o instalador substitui a cada atualização.",
                _ACAO_PASTAS.format("uma pasta só para o acervo, fora da pasta do programa"))
    if _contem(acervo, caminhos.LOCAL):
        return (f"A pasta do acervo ({acervo}) contém a pasta em que o programa guarda as senhas, "
                f"os registros e os perfis do navegador ({caminhos.LOCAL}), que ficariam ao "
                "alcance da IA.",
                _ACAO_PASTAS.format("uma pasta só para o acervo, que não contenha essa pasta"))
    return None


def checar_pastas(cfg) -> Item:
    pastas = [cfg.pasta_acervo, cfg.pasta_processos, cfg.pasta_transcricoes,
              cfg.pasta_sigilosos, _pasta_pauta(cfg), caminhos.LOCAL, caminhos.LOGS,
              caminhos.TEMP]
    for pasta in pastas:
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            teste = pasta / f".teste-gravacao-{os.getpid()}-{threading.get_ident()}.tmp"
            teste.write_bytes(b"ok")
            teste.unlink()
        except PermissionError:
            return Item("Pastas de trabalho", FALHA, f"Sem permissão para gravar em {pasta}.",
                        codigo="pastas",
                        acao=("Se o \u201cAcesso controlado a pastas\u201d do Windows Defender "
                              "estiver ligado, permita o Helestron (Helestron.exe e python.exe da "
                              f"pasta do programa), ou escolha outra pasta em {AJUSTES_PASTAS}."))
        except OSError as erro:
            return Item("Pastas de trabalho", FALHA, f"Não foi possível gravar em {pasta}: {erro}",
                        codigo="pastas",
                        acao=("Confira se a pasta existe, se o disco tem espaço e se não está "
                              "protegida contra gravação."))
    # Aviso, e não falha: a instalação está boa, e a troca é feita na tela
    # (nada se perde). Mas o texto diz o que está em jogo.
    problema = _problema_nas_pastas(cfg)
    if problema:
        return Item("Pastas de trabalho", AVISO, problema[0], codigo="pastas", acao=problema[1])
    return Item("Pastas de trabalho", OK,
                f"O acervo ({cfg.pasta_acervo}), os sigilosos, a pauta e os dados do programa "
                "aceitam gravação e estão separados.",
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


# Pastas do Google Drive para computador logo abaixo da letra da unidade
# virtual (G:\Meu Drive, G:\Drives compartilhados).
_RAIZES_GOOGLE_DRIVE = ("meu drive", "my drive", "drives compartilhados", "shared drives")


def _nuvens_detectadas() -> list[tuple[str, Path]]:
    """[(rótulo, pasta)] das pastas do OneDrive e do Google Drive deste
    computador (compartilhar.nuvem.detectar). Nunca levanta."""
    try:
        from .compartilhar import nuvem

        return [(str(r), Path(p)) for r, p in nuvem.detectar().items()]
    except Exception as erro:  # noqa: BLE001 - sem detecção, fica a dos nomes
        log.debug("pastas de nuvem não detectadas: %s", erro)
        return []


def nuvem_da_pasta(pasta, detectadas: list[tuple[str, Path]] | None = None) -> str:
    """"OneDrive" ou "Google Drive" se a pasta está dentro de uma pasta
    sincronizada com a nuvem; "" se não está (ou não se sabe)."""
    if caminhos.dentro_do_onedrive(Path(pasta)):
        return "OneDrive"
    for rotulo, raiz in (detectadas if detectadas is not None else _nuvens_detectadas()):
        if _contem(raiz, Path(pasta)):
            return "Google Drive" if "google" in rotulo.lower() else "OneDrive"
    try:
        partes = [p.lower() for p in Path(pasta).resolve().parts]
    except (OSError, RuntimeError, ValueError):
        partes = [p.lower() for p in Path(pasta).parts]
    if "google drive" in partes or "googledrive" in partes:
        return "Google Drive"
    if NO_WINDOWS and len(partes) > 1 and partes[1] in _RAIZES_GOOGLE_DRIVE:
        return "Google Drive"
    return ""


def checar_local(cfg) -> Item:
    """Onde ficam as pastas: fora do OneDrive, da rede e de caminho curto - e
    os sigilosos e a pauta exportada fora de toda pasta sincronizada com a
    nuvem (OneDrive, Google Drive)."""
    nome = "Local das pastas"
    problemas, acoes = [], []
    # Primeiro o mais grave: o que é de segredo de justiça saindo do computador.
    detectadas = _nuvens_detectadas()
    for rotulo, pasta, porque, alvo in (
            ("dos processos em segredo de justiça", cfg.pasta_sigilosos,
             "os autos, as transcrições e as gravações sigilosas saem do computador e ficam",
             "os sigilosos"),
            ("da pauta exportada", _pasta_pauta(cfg),
             "a planilha, com as partes dos processos sigilosos, sai do computador e fica",
             "a pauta")):
        servico = nuvem_da_pasta(pasta, detectadas)
        if servico:
            problemas.append(f"a pasta {rotulo} ({pasta}) está dentro do {servico}: {porque} "
                             "ao alcance dos conectores da IA")
            acoes.append(f"em {AJUSTES_PASTAS}, escolha para {alvo} uma pasta fora do OneDrive "
                         "e do Google Drive")
    if caminhos.dentro_do_onedrive(cfg.pasta_acervo):
        problemas.append(f"a pasta do acervo ({cfg.pasta_acervo}) está dentro do OneDrive, cuja "
                         "sincronização trava arquivos em uso")
        acoes.append(f"em {AJUSTES_PASTAS}, escolha uma pasta fora do OneDrive (para ter o "
                     "acervo na nuvem, use o espelho da tela Compartilhar)")
    if caminhos.dentro_do_onedrive(caminhos.LOCAL):
        problemas.append(f"a pasta de dados do programa ({caminhos.LOCAL}) está dentro do OneDrive")
        acoes.append("peça ao suporte que tire do OneDrive a pasta AppData\\Local do seu perfil")
    programa = str(caminhos.INSTALACAO)
    if caminhos.INSTALADO and len(programa) > LIMITE_CAMINHO and not _caminhos_longos():
        problemas.append(f"a pasta do programa tem caminho longo ({len(programa)} caracteres; "
                         f"acima de {LIMITE_CAMINHO}, algumas bibliotecas passam do limite do "
                         "Windows)")
        acoes.append("instale o Helestron numa pasta de caminho curto, como C:\\Helestron")
    for rotulo, pasta in (("do programa", programa), ("de dados", str(caminhos.LOCAL))):
        if pasta.startswith("\\\\"):
            problemas.append(f"a pasta {rotulo} fica numa pasta de rede")
            acoes.append("instale e use o Helestron no próprio computador")
    if problemas:
        return Item(nome, AVISO, "Atenção: " + "; ".join(problemas) + ".",
                    obrigatorio=False, codigo="local",
                    acao="Recomendado: " + "; ".join(acoes) + ".")
    return Item(nome, OK, f"Programa em {programa}; dados em {caminhos.LOCAL}; acervo fora do "
                "OneDrive; sigilosos e pauta fora da nuvem.", obrigatorio=False, codigo="local")


def _formatar_gb(bytes_: float) -> str:
    return f"{bytes_ / 1024 ** 3:.1f}".replace(".", ",") + " GB"


def checar_espaco(cfg) -> Item:
    alvo = next((p for p in (cfg.pasta_acervo, caminhos.LOCAL, caminhos.INSTALACAO)
                 if Path(p).exists()), Path.cwd())
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


# ----------------------------------------------------------------- cofre
def checar_cofre() -> Item:
    from .nucleo.cofre_senhas import CofreSenhas

    nome = "Cofre de senhas"
    senha = "s3nh@ de teste \u00e7\u00e3o"
    with tempfile.TemporaryDirectory(prefix="helestron-verificacao-") as tmp:
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

    nome = "Catálogo de tribunais"
    locais = Path(tribunais.ARQUIVO_LOCAL)
    try:
        lista = tribunais.carregar()
    except Exception as erro:  # noqa: BLE001 - JSON editado à mão pode estar quebrado
        # carregar() lê o catálogo E as correções de endereço do usuário: o
        # problema pode estar no enderecos-locais.json, e não no catálogo que
        # vem com o programa (a frase antiga só falava do tribunais.json).
        return Item(nome, FALHA,
                    "O catálogo de tribunais (dados\\tribunais.json) ou as correções de "
                    f"endereço ({locais}) não puderam ser lidos: {erro}",
                    codigo="tribunais",
                    acao=(f"Desfaça a última edição do {locais.name} (na pasta de dados, "
                          f"{locais.parent}) ou do tribunais.json. Se não houve edição: "
                          f"{REINSTALAR}"))
    if not lista:
        # O catálogo ilegível não levanta: carregar() devolve vazio e guarda o
        # motivo (tribunais.problema), que diz o arquivo, a linha e a coluna.
        try:
            motivo = tribunais.problema()
        except Exception:  # noqa: BLE001 - fica a frase genérica
            motivo = ""
        if motivo:
            return Item(nome, FALHA, motivo[:1].upper() + motivo[1:] + ".", codigo="tribunais",
                        acao=("Desfaça a última edição do dados\\tribunais.json. Se não houve "
                              f"edição: {REINSTALAR}"))
        return Item(nome, FALHA, "O catálogo de tribunais está vazio.",
                    codigo="tribunais", acao=RODE_O_INSTALADOR)
    suportados = sum(1 for t in lista if t.suportado)
    detalhe = f"{len(lista)} tribunais no catálogo; {suportados} com e-SAJ ou eProc."
    # As correções de endereço fora do formato não derrubam mais o catálogo
    # (ficam de fora, e vale o endereço dele) - mas o usuário precisa saber
    # que a correção que fez não está valendo.
    try:
        problema_locais = tribunais.problema_locais()
    except Exception as erro:  # noqa: BLE001
        problema_locais = (f"as correções de endereço ({locais}) não puderam ser conferidas "
                           f"({erro})")
    if problema_locais:
        return Item(nome, AVISO, f"{detalhe} Mas {problema_locais}.", codigo="tribunais",
                    acao=(f"Em {AJUSTES_ACESSOS}, refaça a correção com "
                          "“Corrigir o endereço de um portal” (ela regrava o arquivo sem o que "
                          f"está fora do formato), ou desfaça a última edição do {locais.name}."))
    return Item(nome, OK, detalhe, codigo="tribunais")


def checar_regras_pauta() -> Item:
    """As regras de leitura da pauta (dados\\pauta.json): sinônimos das colunas,
    tipos e situações de audiência, rotas dos portais."""
    nome = "Regras da pauta"
    try:
        from .pauta import regras

        lidas = regras.carregar()
    except Exception as erro:  # noqa: BLE001 - módulo ausente ou quebrado
        return Item(nome, FALHA, f"As regras da pauta não puderam ser carregadas: {erro}",
                    obrigatorio=False, codigo="pauta", acao=RODE_O_INSTALADOR)
    problema = getattr(lidas, "problema", "")
    if problema:
        return Item(nome, AVISO, f"{problema[:1].upper()}{problema[1:]}; valem as regras que vêm "
                    "embutidas no programa.", obrigatorio=False, codigo="pauta",
                    acao=("Desfaça a última edição do dados\\pauta.json. Se não houve edição: "
                          + REINSTALAR))
    return Item(nome, OK, "Colunas, tipos e situações de audiência e rotas dos portais carregados.",
                obrigatorio=False, codigo="pauta")


# -------------------------------------------------------------- falantes
def _falantes_situacao() -> tuple[bool, str]:
    """(disponível, descrição). Ponto único de integração com a transcrição."""
    try:
        from .transcricao import falantes

        return bool(falantes.disponivel()), str(falantes.situacao())
    except Exception:
        presente = _presente("sherpa_onnx")
        return False, "incompleta (faltam os modelos de voz)" if presente else "indisponível"


def _falantes_faltam() -> tuple[bool, bool]:
    """(falta a biblioteca sherpa-onnx, faltam os modelos de voz)."""
    try:
        from .transcricao import falantes

        return not falantes.biblioteca_presente(), not falantes.modelos_presentes()
    except Exception:
        return not _presente("sherpa_onnx"), True


def checar_falantes(completo: bool = False) -> Item:
    nome = "Separação de falantes (opcional)"
    disponivel, situacao = _falantes_situacao()
    if not disponivel and _componentes_embutidos().get("falantes") is True:
        # o que sumiu: a biblioteca (a DLL em quarentena), os modelos, ou os dois
        sem_biblioteca, sem_modelos = _falantes_faltam()
        if sem_biblioteca and not sem_modelos:
            o_que = ("O componente da separação de vozes (sherpa-onnx) veio com o programa, mas "
                     "não está mais na pasta do programa (o antivírus pode tê-lo retirado)")
        elif sem_biblioteca:
            o_que = ("O componente da separação de vozes (sherpa-onnx) e os modelos de voz "
                     "vieram com o programa, mas não estão mais na pasta do programa (o "
                     "antivírus pode tê-los retirado)")
        else:
            o_que = ("Os modelos de voz vieram com o programa, mas não estão mais na pasta do "
                     "programa (o antivírus pode tê-los retirado)")
        return Item(nome, FALHA, f"{o_que}: a revisão final não separa as vozes sozinha.",
                    obrigatorio=False, codigo="falantes", acao=REINSTALAR)
    if not disponivel:
        if _presente("sherpa_onnx"):
            # A biblioteca veio; faltam só os modelos de voz (construção sem eles).
            acao = (f"Baixe os modelos de voz em {AJUSTES_TRANSCRICAO}, botão \u201cBaixar os "
                    "modelos de voz\u201d (cerca de 47\u00a0MB, uma vez só).")
        else:
            acao = f"A separação de vozes vem no instalador. {REINSTALAR}"
        return Item(nome, AVISO,
                    f"{situacao[:1].upper()}{situacao[1:]}: a revisão final não separa as vozes "
                    "sozinha (os falantes marcados durante a audiência continuam valendo).",
                    obrigatorio=False, codigo="falantes", acao=acao)
    if completo:
        r = sondar_importacoes(["sherpa_onnx"], 120).get("sherpa_onnx", {})
        if not r.get("ok"):
            return Item(nome, AVISO, f"O componente está instalado, mas não carregou: {r.get('erro', '?')}",
                        obrigatorio=False, codigo="falantes", acao=RODE_O_INSTALADOR)
    return Item(nome, OK, "Instalada.", obrigatorio=False, codigo="falantes")


# ------------------------------------------------------- conector MCP
def _pedidos_mcp() -> bytes:
    pedidos = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "helestron-verificacao", "version": __version__}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    return "".join(json.dumps(p) + "\n" for p in pedidos).encode("utf-8")


def conversar_mcp(entrada: dict, limite_s: float = 90.0) -> tuple[list[str], str]:
    """Roda o conector EXATAMENTE como o Claude Desktop o rodaria (o comando,
    os argumentos e as variáveis da entrada registrada) e faz o aperto de
    mão: initialize e tools/list. Devolve (nomes das ferramentas, erro)."""
    env = dict(os.environ)
    env.update({k: str(v) for k, v in (entrada.get("env") or {}).items()})
    comando = [str(entrada["command"]), *[str(a) for a in entrada.get("args", [])]]
    try:
        r = subprocess.run(comando, input=_pedidos_mcp(), capture_output=True, timeout=limite_s,
                           env=env, cwd=_pasta_de_trabalho(),
                           creationflags=0x08000000 if NO_WINDOWS else 0)
    except subprocess.TimeoutExpired:
        return [], "o conector não respondeu no tempo esperado"
    except OSError as erro:
        return [], f"o conector não pôde ser iniciado ({erro})"
    respostas = {}
    for linha in _texto(r.stdout).splitlines():
        try:
            d = json.loads(linha)
        except ValueError:
            continue
        if isinstance(d, dict) and "id" in d:
            respostas[d["id"]] = d
    inicio = (respostas.get(1) or {}).get("result") or {}
    if (inicio.get("serverInfo") or {}).get("name") != "helestron":
        ultima = (_texto(r.stderr).strip().splitlines() or [explicar_queda(r.returncode)])[-1]
        return [], f"o conector não se apresentou ({ultima[:300]})"
    ferramentas = ((respostas.get(2) or {}).get("result") or {}).get("tools") or []
    return [str(f.get("name", "")) for f in ferramentas if isinstance(f, dict)], ""


def _registros_mcp(acervo: Path) -> tuple[list[str], list[str]]:
    """(onde o conector está registrado e certo, problemas encontrados)."""
    from .compartilhar import chatgpt, claude

    certos, problemas = [], []
    esperada = claude.entrada_mcp(acervo)
    for arq in claude.arquivos_config_desktop():
        try:
            servidores = claude._ler_json(arq).get("mcpServers") or {}
        except (OSError, ValueError):
            continue
        if not isinstance(servidores, dict):
            continue
        if any(n in servidores for n in claude.NOMES_ANTIGOS):
            problemas.append("o Claude Desktop ainda tem o conector da versão anterior "
                             "(Assessor Integrado)")
        atual = servidores.get(claude.NOME_MCP)
        if atual is None:
            continue
        if atual.get("command") != esperada["command"] or atual.get("args") != esperada["args"]:
            problemas.append("o conector do Claude Desktop aponta para outro acervo ou para "
                             "outra instalação")
        elif "Claude Desktop" not in certos:
            certos.append("Claude Desktop")
    try:
        import tomllib

        dados = tomllib.loads(chatgpt.arquivo_config_codex().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        dados = {}
    servidores = dados.get("mcp_servers") or {}
    if isinstance(servidores, dict):
        if any(n in servidores for n in chatgpt.NOMES_ANTIGOS):
            problemas.append("o ChatGPT/Codex ainda tem o conector da versão anterior "
                             "(Assessor Integrado)")
        atual = servidores.get(chatgpt.NOME_MCP)
        if isinstance(atual, dict):
            if atual.get("command") != esperada["command"] or atual.get("args") != esperada["args"]:
                problemas.append("o conector do ChatGPT/Codex aponta para outro acervo ou para "
                                 "outra instalação")
            else:
                certos.append("ChatGPT/Codex")
    return certos, list(dict.fromkeys(problemas))


def checar_conector(cfg) -> Item:
    """O conector MCP do acervo responde, e o registrado nas IAs é o certo."""
    nome = "Conector do acervo (MCP)"
    from .compartilhar import claude

    acervo = cfg.pasta_acervo
    ferramentas, erro = conversar_mcp(claude.entrada_mcp(acervo))
    if erro:
        return Item(nome, FALHA, f"O conector não funcionou: {erro}.", obrigatorio=False,
                    codigo="conector", acao=RODE_O_INSTALADOR)
    try:
        certos, problemas = _registros_mcp(acervo)
    except Exception as falha:  # noqa: BLE001 - arquivo de outro programa, ilegível
        log.debug("registros do conector: %s", falha)
        certos, problemas = [], []
    qtd = f"{len(ferramentas)} ferramenta{'s' if len(ferramentas) != 1 else ''}"
    if problemas:
        return Item(nome, AVISO, f"O conector responde ({qtd}), mas " + "; ".join(problemas) + ".",
                    obrigatorio=False, codigo="conector",
                    acao=("Na tela Compartilhar, conecte o acervo de novo (Claude Desktop: "
                          "\u201cReconectar o acervo\u201d; ChatGPT: \u201cAbrir no ChatGPT "
                          "Work\u201d)."))
    if certos:
        return Item(nome, OK, f"O conector responde ({qtd}); ligado a: {', '.join(certos)}.",
                    obrigatorio=False, codigo="conector")
    return Item(nome, OK, f"O conector responde ({qtd}); ainda não foi ligado ao Claude Desktop "
                "nem ao ChatGPT (opcional: tela Compartilhar).", obrigatorio=False,
                codigo="conector")


# ============================================================ conjunto

def _etapas(cfg, completo: bool) -> list[tuple[str, Callable[[], Item]]]:
    etapas: list[tuple[str, Callable[[], Item]]] = [
        ("Windows 64 bits", checar_sistema),
        ("Bibliotecas", checar_bibliotecas),
        ("Componentes nativos (DLLs)", checar_nativos),
        ("Modelo de transcrição", lambda: checar_modelo(cfg)),
    ]
    if completo:
        etapas.append(("Teste de transcrição", lambda: checar_teste_transcricao(cfg)))
    etapas.append(("Navegador dos portais", lambda: checar_navegador(cfg)))
    if completo:
        etapas.append(("Teste do navegador", lambda: checar_teste_navegador(cfg)))
    etapas += [
        ("WebView2 (janela do programa)", checar_webview2),
        ("Microfone", checar_microfone),
        ("Permissão do microfone", checar_privacidade_microfone),
        ("Pastas de trabalho", lambda: checar_pastas(cfg)),
        ("Local das pastas", lambda: checar_local(cfg)),
        ("Espaço em disco", lambda: checar_espaco(cfg)),
        ("Cofre de senhas", checar_cofre),
        ("Catálogo de tribunais", checar_tribunais),
        ("Regras da pauta", checar_regras_pauta),
        ("Separação de falantes (opcional)", lambda: checar_falantes(completo)),
        ("Conector do acervo (MCP)", lambda: checar_conector(cfg)),
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

    Pode ser chamada de uma thread de trabalho do servidor (não toca na
    janela). `ao_item` recebe cada item assim que fica pronto, na ordem.
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
    return (f"Resultado: {contagem}. A instalação tem problemas: veja acima o que fazer. Se for "
            "preciso, instale o Helestron de novo com o Helestron-Setup (os seus dados ficam).")


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
            f"Programa: {caminhos.INSTALACAO}\n"
            f"Dados: {caminhos.LOCAL}\n")


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
        "pasta": str(caminhos.INSTALACAO),
        "dados": str(caminhos.LOCAL),
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
Uso: python -m helestron verificar [--completo] [--json ARQUIVO]

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
