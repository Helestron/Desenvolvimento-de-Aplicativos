"""Separação automática de falantes (opcional), sem torch.

A base usava speechbrain + torch (~250 MB, a maior fonte de falha de
instalação no Windows: "DLL load failed"/fbgemm.dll sem o Visual C++). Aqui
é o sherpa-onnx, que roda no mesmo onnxruntime do resto do programa:
  * segmentação pyannote 3.0 (model.int8.onnx): ACHA as trocas de voz dentro
    do áudio, inclusive no meio de uma frase - a base só rotulava trechos
    inteiros do Whisper e errava quando alguém interrompia;
  * "impressão digital" de voz 3D-Speaker ERes2Net;
  * agrupamento rápido com limiar 0,85 (validado: separou 4 vozes num teste).

Os rótulos saem como FALANTE 1, FALANTE 2..., na ordem em que cada voz
aparece. Na revisão de uma audiência gravada ao vivo, quem chama troca
esses rótulos pelos marcados durante a audiência (votação por sobreposição).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import numpy as np

from ..nucleo import caminhos, sistema
from .documento import Fala

log = logging.getLogger("transcricao.falantes")

TAXA = 16000
URL_SEGMENTACAO = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                   "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
URL_EMBEDDING = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                 "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
SHA256 = {
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2":
        "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
    "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx":
        "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
}
SUBPASTA_SEGMENTACAO = "sherpa-onnx-pyannote-segmentation-3-0"
ARQUIVO_SEGMENTACAO = "model.int8.onnx"
ARQUIVO_EMBEDDING = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

PASTA: Path = caminhos.MODELOS / "falantes"   # trocável nos testes
# Download do componente inteiro (a biblioteca sherpa-onnx e os dois modelos),
# arredondado: um número só para a tela, a verificação, o instalador e a CLI.
TAMANHO_MB = 60
LIMIAR = 0.85
SUAVIZAR_S = 1.5


class ComponenteAusente(RuntimeError):
    """A separação de falantes não está instalada."""


class Cancelado(Exception):
    """O usuário mandou parar."""


# ------------------------------------------------------------ consultas
def modelo_segmentacao() -> Path:
    return Path(PASTA) / SUBPASTA_SEGMENTACAO / ARQUIVO_SEGMENTACAO


def modelo_embedding() -> Path:
    return Path(PASTA) / ARQUIVO_EMBEDDING


def biblioteca_presente() -> bool:
    try:
        return importlib.util.find_spec("sherpa_onnx") is not None
    except (ImportError, ValueError):
        return False


def modelos_presentes() -> bool:
    return modelo_segmentacao().is_file() and modelo_embedding().is_file()


def disponivel() -> bool:
    """Biblioteca e modelos no lugar (não importa nada pesado)."""
    return biblioteca_presente() and modelos_presentes()


def situacao() -> str:
    if disponivel():
        return "instalada"
    if not biblioteca_presente():
        return "não instalada (falta o componente sherpa-onnx)"
    return "incompleta (faltam os modelos de voz)"


# -------------------------------------------------------------- instalar
def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _abrir_url(url: str, inicio: int):
    pedido = urllib.request.Request(url, headers={"User-Agent": "AssessorIntegrado"})
    if inicio and url.lower().startswith("http"):
        pedido.add_header("Range", f"bytes={inicio}-")
    return urllib.request.urlopen(pedido, timeout=60)


def _baixar(url: str, destino: Path, sha256: str | None,
            progresso: Callable[[int, int], None] | None = None,
            cancelado: Callable[[], bool] | None = None, tentativas: int = 4) -> Path:
    """Baixa com retomada (.part), confere o SHA-256 e só então renomeia."""
    if destino.exists() and (not sha256 or _sha256(destino) == sha256):
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")
    ultimo: BaseException | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            inicio = parcial.stat().st_size if parcial.exists() else 0
            with _abrir_url(url, inicio) as resp:
                status = getattr(resp, "status", 200) or 200
                if inicio and status != 206:
                    inicio = 0  # o servidor ignorou o pedaço: recomeça
                tamanho = resp.headers.get("Content-Length")
                total = inicio + int(tamanho) if tamanho and tamanho.isdigit() else 0
                feito = inicio
                with open(parcial, "ab" if inicio else "wb") as saida:
                    while True:
                        if cancelado and cancelado():
                            raise Cancelado()
                        bloco = resp.read(1 << 16)
                        if not bloco:
                            break
                        saida.write(bloco)
                        feito += len(bloco)
                        if progresso:
                            progresso(feito, total)
            if sha256 and _sha256(parcial) != sha256:
                parcial.unlink(missing_ok=True)
                raise RuntimeError(f"o arquivo baixado de {url} não confere (SHA-256); "
                                   "foi descartado")
            os.replace(parcial, destino)
            return destino
        except Cancelado:
            raise
        except urllib.error.HTTPError as erro:
            ultimo = erro
            if erro.code == 416 and parcial.exists():
                # "Range" além do fim: o .part já veio inteiro (o programa caiu
                # antes de conferir e renomear). Sem tratar, TODA tentativa
                # repetia o mesmo pedido e a instalação nunca mais terminava.
                if sha256 and _sha256(parcial) == sha256:
                    os.replace(parcial, destino)
                    return destino
                parcial.unlink(missing_ok=True)
                continue   # recomeça do zero, sem esperar
            log.warning("download de %s falhou (tentativa %d): %s", destino.name, tentativa, erro)
            if tentativa < tentativas:
                time.sleep(min(20, 3 * tentativa))
        except Exception as erro:
            ultimo = erro
            log.warning("download de %s falhou (tentativa %d): %s", destino.name, tentativa, erro)
            if tentativa < tentativas:
                time.sleep(min(20, 3 * tentativa))
    raise ComponenteAusente(
        f"Não consegui baixar {destino.name} do GitHub ({ultimo}). Confira a internet "
        "(a rede do tribunal precisa liberar github.com e objects.githubusercontent.com) "
        "e tente de novo; o download continua de onde parou.")


def _ambiente_do_pip() -> dict[str, str]:
    """O ambiente do pip, limpo como o instalador o deixa (Preparar-Ambiente).

    O -E do atalho vale só para o processo da janela: os.environ continua
    com o PYTHONHOME global (deixado pelo ArcGIS, por exemplo), e o Python
    filho morria na partida ("No module named encodings"). Um pip.ini do
    usuário com "user = true" mandava o pacote para %APPDATA%\\Python, que o
    programa (rodando com -s) não enxerga: reabrir não resolvia.
    """
    env = dict(os.environ)
    for variavel in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PIP_USER", "PIP_TARGET",
                     "PIP_PREFIX", "PIP_REQUIRE_VIRTUALENV", "VIRTUAL_ENV", "PIP_INDEX_URL"):
        env.pop(variavel, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_CONFIG_FILE"] = os.devnull      # "nul" no Windows: nenhum pip.ini é lido
    env["PIP_NO_INPUT"] = "1"
    env.setdefault("PIP_CACHE_DIR", str(caminhos.RUNTIME / "pip-cache"))
    # Saída do pip em UTF-8: no Windows, por cano, ela sai em cp1252 e a
    # mensagem de erro mostrada ao usuário vinha com os acentos trocados.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _instalar_biblioteca(progresso: Callable[[float, str], None]) -> None:
    requisitos = caminhos.RAIZ / "instalador" / "requisitos-falantes.txt"
    if not requisitos.exists():
        raise ComponenteAusente(f"Arquivo de requisitos não encontrado: {requisitos}")
    progresso(0.02, "Instalando o componente sherpa-onnx (alguns minutos)...")
    env = _ambiente_do_pip()
    # -s: o pacote "do usuário" de outro Python 3.12 não entra (o programa
    # roda com -s e não o enxergaria).
    cmd = [str(caminhos.python_exe(False)), "-s", "-m", "pip", "install", "--require-hashes",
           "--only-binary=:all:", "--prefer-binary", "--no-warn-script-location",
           "--disable-pip-version-check", "--retries", "10", "--timeout", "60",
           "-r", str(requisitos)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, creationflags=sistema.SEM_JANELA)
    if r.returncode != 0:
        ultimas = "\n".join((r.stdout + r.stderr).strip().splitlines()[-8:])
        raise ComponenteAusente("A instalação do componente sherpa-onnx falhou. Confira a "
                                f"internet e tente de novo.\n{ultimas}")
    importlib.invalidate_caches()


def _extrair_segmentacao(pacote: Path, pasta: Path) -> None:
    """Extrai só o necessário do .tar.bz2, numa pasta temporária, e troca."""
    alvo = pasta / SUBPASTA_SEGMENTACAO
    with tempfile.TemporaryDirectory(dir=pasta, prefix="_extraindo") as tmp:
        with tarfile.open(pacote, "r:bz2") as tar:
            membros = [m for m in tar.getmembers()
                       if m.isfile() and Path(m.name).name in (ARQUIVO_SEGMENTACAO, "LICENSE",
                                                               "README.md")]
            if not any(Path(m.name).name == ARQUIVO_SEGMENTACAO for m in membros):
                raise ComponenteAusente(f"{pacote.name} não contém {ARQUIVO_SEGMENTACAO}")
            for m in membros:
                m.name = Path(m.name).name  # achata: nada de caminho vindo do pacote
                try:
                    tar.extract(m, tmp, filter="data")
                except TypeError:  # Python sem o filtro (anterior a 3.12)
                    tar.extract(m, tmp)
        alvo.mkdir(parents=True, exist_ok=True)
        for arq in Path(tmp).iterdir():
            os.replace(arq, alvo / arq.name)


def instalar(progresso: Callable[[float, str], None] | None = None, *, pip: bool = True,
             cancelado: Callable[[], bool] | None = None) -> None:
    """Instala o componente: a biblioteca (pip, se faltar) e os 2 modelos (~47 MB).

    Idempotente: o que já está no lugar e confere não é baixado de novo.
    `progresso(fração 0..1, texto)`.
    """
    def avisar(fracao: float, texto: str) -> None:
        if progresso:
            try:
                progresso(max(0.0, min(1.0, fracao)), texto)
            except Exception:  # pragma: no cover
                pass

    from .modelos import preparar_rede

    preparar_rede()  # certificados e proxy do Windows também para o GitHub
    if pip and not biblioteca_presente():
        _instalar_biblioteca(avisar)
        if not biblioteca_presente():
            raise ComponenteAusente("O componente sherpa-onnx foi instalado, mas não pôde "
                                    "ser carregado. Feche e abra o programa de novo.")
    pasta = Path(PASTA)
    pasta.mkdir(parents=True, exist_ok=True)

    if not modelo_segmentacao().is_file():
        pacote = pasta / Path(URL_SEGMENTACAO).name
        avisar(0.1, "Baixando o modelo de segmentação de voz (7 MB)...")
        _baixar(URL_SEGMENTACAO, pacote, SHA256.get(pacote.name),
                lambda f, t: avisar(0.1 + 0.15 * (f / t if t else 0),
                                    f"Baixando o modelo de segmentação: {f // 1_000_000} MB"),
                cancelado)
        _extrair_segmentacao(pacote, pasta)
        pacote.unlink(missing_ok=True)

    if not modelo_embedding().is_file():
        avisar(0.3, "Baixando o modelo de impressão de voz (40 MB)...")
        _baixar(URL_EMBEDDING, modelo_embedding(), SHA256.get(ARQUIVO_EMBEDDING),
                lambda f, t: avisar(0.3 + 0.65 * (f / t if t else 0),
                                    f"Baixando o modelo de voz: {f // 1_000_000} de 40 MB"),
                cancelado)
    avisar(1.0, "Separação de falantes instalada.")
    log.info("separação de falantes instalada em %s", pasta)


# -------------------------------------------------------------- diarizar
def diarizar(audio16k: np.ndarray, num_falantes: int = 0, *, limiar: float = LIMIAR,
             progresso: Callable[[float], None] | None = None,
             cancelado: Callable[[], bool] | None = None,
             threads: int = 0) -> list[tuple[float, float, int]]:
    """Turnos de fala [(início, fim, índice da voz)], em ordem de início.

    `num_falantes` > 0 fixa a quantidade (informar o número certo melhora
    MUITO o resultado); 0 = descobre sozinho pelo limiar.
    """
    if not modelos_presentes():
        raise ComponenteAusente("Os modelos da separação de falantes não estão instalados "
                                "(Configurações > Transcrição > Instalar o componente).")
    try:
        import sherpa_onnx
    except ImportError as erro:
        raise ComponenteAusente("O componente sherpa-onnx não está instalado "
                                "(Configurações > Transcrição > Instalar o componente).") from erro

    audio = np.ascontiguousarray(audio16k, dtype=np.float32).reshape(-1)
    duracao = audio.size / TAXA
    if duracao < 1.0:
        return [(0.0, duracao, 0)] if duracao > 0 else []
    from .modelos import caminho_nativo   # pasta com acento no Windows (ver lá)

    n_threads = threads or max(1, (os.cpu_count() or 2) // 2)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=caminho_nativo(modelo_segmentacao())),
            num_threads=n_threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=caminho_nativo(modelo_embedding()), num_threads=n_threads),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=int(num_falantes) if num_falantes and num_falantes > 0 else -1,
            threshold=float(limiar)),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise ComponenteAusente("A configuração da separação de falantes não é válida "
                                "(modelos corrompidos?). Reinstale o componente.")
    motor = sherpa_onnx.OfflineSpeakerDiarization(config)

    def callback(feitos: int, total: int) -> int:
        if progresso and total:
            try:
                progresso(feitos / total)
            except Exception:  # pragma: no cover
                pass
        return 1 if (cancelado and cancelado()) else 0

    resultado = motor.process(audio, callback=callback).sort_by_start_time()
    if cancelado and cancelado():
        raise Cancelado()
    return [(float(r.start), float(r.end), int(r.speaker)) for r in resultado]


# -------------------------------------------------------------- atribuir
def _sobreposicao(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _voz_de(inicio: float, fim: float, turnos: list[tuple[float, float, int]]) -> int | None:
    """A voz que mais ocupa o intervalo; sem sobreposição, a do turno mais perto."""
    if not turnos:
        return None
    if fim - inicio < 0.1:  # palavra curtíssima: mede ao redor do centro
        centro = (inicio + fim) / 2
        inicio, fim = centro - 0.05, centro + 0.05
    somas: dict[int, float] = {}
    for t0, t1, voz in turnos:
        s = _sobreposicao(inicio, fim, t0, t1)
        if s > 0:
            somas[voz] = somas.get(voz, 0.0) + s
    if somas:
        return max(somas.items(), key=lambda kv: kv[1])[0]
    centro = (inicio + fim) / 2
    return min(turnos, key=lambda t: min(abs(centro - t[0]), abs(centro - t[1])))[2]


def _pedacos(fala: Fala, turnos) -> list[tuple[float, float, str, int | None]]:
    """Divide a fala nas trocas de voz, quando há tempo por palavra."""
    palavras = [p for p in (fala.palavras or []) if str(p[2]).strip()]
    if len(palavras) < 2:
        return [(fala.inicio, fala.fim, fala.texto, _voz_de(fala.inicio, fala.fim, turnos))]
    vozes = [_voz_de(float(p[0]), float(p[1]), turnos) for p in palavras]
    # uma palavra solta entre duas da mesma voz é erro de fronteira, não troca
    for i in range(1, len(vozes) - 1):
        if vozes[i - 1] == vozes[i + 1] != vozes[i]:
            vozes[i] = vozes[i - 1]
    pedacos: list[tuple[float, float, str, int | None]] = []
    ini = 0
    for i in range(1, len(palavras) + 1):
        if i == len(palavras) or vozes[i] != vozes[ini]:
            grupo = palavras[ini:i]
            texto = "".join(str(p[2]) for p in grupo).strip()
            pedacos.append((float(grupo[0][0]), float(grupo[-1][1]), texto, vozes[ini]))
            ini = i
    return pedacos


def atribuir(falas: list[Fala], turnos: list[tuple[float, float, int]]) -> list[Fala]:
    """Rotula as falas com FALANTE n conforme os turnos da diarização.

    Divide a fala na troca de voz (se houver tempo por palavra), corrige o
    padrão A-B-A em que B dura menos de 1,5 s (o "sim" mal classificado) e
    numera as vozes pela ordem em que aparecem na audiência.
    """
    pedacos: list[tuple[float, float, str, int | None]] = []
    for f in falas:
        pedacos.extend(_pedacos(f, turnos))
    if not pedacos:
        return []
    vozes = [p[3] for p in pedacos]
    # suavização sem efeito cascata: decide olhando os rótulos ORIGINAIS
    novas = list(vozes)
    for i in range(1, len(pedacos) - 1):
        ini, fim = pedacos[i][0], pedacos[i][1]
        if vozes[i - 1] == vozes[i + 1] != vozes[i] and (fim - ini) < SUAVIZAR_S:
            novas[i] = vozes[i - 1]
    ordem: dict[int, int] = {}
    saida: list[Fala] = []
    for (ini, fim, texto, _), voz in zip(pedacos, novas):
        if voz is None:
            rotulo = saida[-1].falante if saida else "FALANTE 1"
        else:
            if voz not in ordem:
                ordem[voz] = len(ordem) + 1
            rotulo = f"FALANTE {ordem[voz]}"
        saida.append(Fala(ini, fim, rotulo, texto))
    return saida


def votar_rotulos(falas: list[Fala], manuais: list[Fala]) -> dict[str, str]:
    """Para cada rótulo automático, o rótulo manual com mais tempo em comum.

    Ex.: FALANTE 2 coincide 80 s com "Testemunha" e 3 s com "Juiz(a)" ->
    vira "Testemunha". Rótulo sem nenhuma sobreposição continua automático.
    """
    marcados = [m for m in manuais if (m.falante or "").strip()]
    votos: dict[str, dict[str, float]] = {}
    for f in falas:
        for m in marcados:
            s = _sobreposicao(f.inicio, f.fim, m.inicio, m.fim)
            if s > 0:
                caixa = votos.setdefault(f.falante, {})
                caixa[m.falante] = caixa.get(m.falante, 0.0) + s
    return {auto: max(caixa.items(), key=lambda kv: kv[1])[0]
            for auto, caixa in votos.items() if caixa}


def rotular_por_sobreposicao(falas: list[Fala], manuais: list[Fala]) -> list[Fala]:
    """Sem separação automática: cada fala recebe o rótulo manual que mais a
    cobre no tempo (ou o último marcado antes dela)."""
    marcados = sorted((m for m in manuais if (m.falante or "").strip()), key=lambda m: m.inicio)
    saida: list[Fala] = []
    for f in falas:
        somas: dict[str, float] = {}
        for m in marcados:
            s = _sobreposicao(f.inicio, f.fim, m.inicio, m.fim)
            if s > 0:
                somas[m.falante] = somas.get(m.falante, 0.0) + s
        if somas:
            rotulo = max(somas.items(), key=lambda kv: kv[1])[0]
        else:
            anteriores = [m for m in marcados if m.inicio <= f.inicio]
            rotulo = anteriores[-1].falante if anteriores else (f.falante or "")
        saida.append(Fala(f.inicio, f.fim, rotulo, f.texto, f.palavras))
    return saida


def remover_instalacao() -> None:
    """Apaga os modelos (a tela de Configurações oferece)."""
    shutil.rmtree(Path(PASTA), ignore_errors=True)
