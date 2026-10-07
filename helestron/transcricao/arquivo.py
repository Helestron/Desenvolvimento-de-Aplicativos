"""Transcrição de uma gravação inteira: a revisão final da audiência ao vivo
e as gravações que já existem (ASF/WMV/MP4 do sistema de gravação, MP3...).

Reuso quase literal do `pipeline.processar` do Assessor SAJ - os parâmetros
do Whisper e o VAD 700/200 foram afinados em audiências reais -, com três
mudanças:
  * sem ffmpeg.exe: o áudio é decodificado pelo PyAV, que já vem com o
    faster-whisper (a base baixava 40 MB do gyan.dev no instalador, um
    download frágil). O passa-alta de 80 Hz e a normalização de volume, que
    lá eram filtros do ffmpeg, aqui são numpy;
  * o arquivo sai com o NÚMERO DO PROCESSO como nome, na pasta de
    transcrições, e o número vem do usuário ou do nome do arquivo;
  * a separação de falantes divide a fala na troca de voz (tempo por
    palavra), e, na revisão de uma audiência ao vivo, os rótulos marcados na
    hora (Juiz(a), Testemunha...) substituem os FALANTE n por votação.

Atenção: `faster_whisper.decode_audio` (1.2.1) quebra com o PyAV 17+ (o
argumento `metadata_errors` sumiu do `av.open`). Por isso a decodificação
é nossa (`decodificar`), e o modelo recebe sempre o áudio já em memória.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from ..nucleo import cnj, energia, sistema
from . import falantes as mod_falantes
from . import modelos
from .documento import (Fala, MetaAudiencia, gerar_docx, magistrado_da_config,
                        pasta_das_transcricoes, unidade_da_config)

log = logging.getLogger("transcricao.arquivo")

TAXA = 16000
# Os formatos de áudio e de vídeo que o Windows reproduz (Windows Media
# Player, Filmes e TV, Mídia), numa lista ÚNICA: a do filtro do diálogo do
# Windows, a do 'accept' do navegador (web/js/secao-audiencias.js,
# EXTENSOES_MIDIA, que o teste test_transcricao_formatos confere item a item)
# e a da linha de comando. A lista só orienta a escolha: o servidor não recusa
# arquivo pela extensão - quem decide é o PyAV abrir o arquivo e achar uma
# trilha de áudio (decodificar), com a frase certa quando não há trilha, o
# arquivo está cortado ou é protegido por DRM.
EXTENSOES = (
    # áudio
    ".mp3", ".wav", ".wma", ".aac", ".adt", ".adts", ".m4a", ".m4b", ".flac", ".ogg", ".oga",
    ".opus", ".aif", ".aiff", ".aifc", ".amr", ".awb", ".ac3", ".ec3", ".mka", ".weba",
    ".caf", ".au", ".snd", ".mp2", ".mpa", ".3ga",
    # vídeo
    ".mp4", ".m4v", ".mov", ".qt", ".avi", ".wmv", ".wm", ".asf", ".mkv", ".webm", ".mpg",
    ".mpeg", ".mpe", ".m1v", ".m2v", ".ts", ".m2t", ".m2ts", ".mts", ".3gp", ".3g2", ".flv",
    ".f4v", ".vob", ".ogv", ".dvr-ms", ".wtv", ".divx", ".mxf",
)
FILTRO_ARQUIVOS = [("Gravações de áudio e vídeo", " ".join(f"*{e}" for e in EXTENSOES)),
                   ("Todos os arquivos", "*.*")]
TEMPERATURAS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


class ProcessoNaoInformado(ValueError):
    """Sem número do processo: nem informado, nem no nome do arquivo."""


class AudioIlegivel(RuntimeError):
    """O arquivo não tem áudio que se possa ler."""


class SemTrilhaDeAudio(AudioIlegivel):
    """O arquivo abre, mas não tem trilha de áudio (o vídeo sem som)."""


class ArquivoDanificado(AudioIlegivel):
    """O arquivo não abre como mídia, ou a trilha de áudio não decodifica:
    cortado (cópia ou download pela metade), corrompido ou não é mídia."""


class ProtegidoPorDrm(AudioIlegivel):
    """O áudio é cifrado (DRM): só o programa que tem a licença o toca."""


class SemFala(RuntimeError):
    """Nenhuma fala foi reconhecida."""


class Cancelado(Exception):
    """O usuário mandou parar."""


# ----------------------------------------------------------- decodificar
# Formatos que o libsndfile lê de forma exata; o resto (MP3, ASF, MP4...) vai
# para o PyAV, que é mais tolerante com arquivo cortado ou cabeçalho estranho.
_EXTENSOES_SOUNDFILE = (".wav", ".flac", ".ogg", ".oga", ".aif", ".aiff", ".w64", ".rf64")


def _decodificar_soundfile(caminho: Path, taxa: int) -> np.ndarray | None:
    if caminho.suffix.lower() not in _EXTENSOES_SOUNDFILE:
        return None
    try:
        import soundfile as sf
    except ImportError:
        return None
    from .microfone import Reamostrador

    try:
        with sf.SoundFile(str(caminho)) as f:
            # FLAC de gravação interrompida (queda de energia) fica sem a
            # duração no cabeçalho, e o libsndfile se perde: o PyAV lê.
            if not (0 < f.frames < 2 ** 40):
                return None
            origem = int(f.samplerate)
            esperado = int(round(f.frames * taxa / origem))
            reamostrador = Reamostrador(origem, taxa) if origem != taxa else None
            # Em blocos: ler de uma vez uma audiência de 3 h em WAV de 48 kHz
            # estéreo são 4 GB de float32 na memória (MemoryError no notebook
            # do gabinete); em 16 kHz mono ficam ~700 MB.
            partes: list[np.ndarray] = []
            for bloco in f.blocks(blocksize=origem * 60, dtype="float32", always_2d=True):
                mono = (bloco.mean(axis=1, dtype=np.float32) if bloco.shape[1] > 1
                        else bloco[:, 0].copy())
                partes.append(reamostrador.processar(mono) if reamostrador else mono)
            if reamostrador:
                partes.append(reamostrador.finalizar())
    except Exception:
        return None
    if not partes:
        return None
    audio = np.concatenate(partes)[:esperado] if len(partes) > 1 else partes[0][:esperado]
    return np.ascontiguousarray(audio, dtype=np.float32)


# ----------------------------------------------------------------- DRM
# O áudio cifrado (DRM) abre no PyAV, mas não decodifica - ou decodifica em
# ruído, e a transcrição sairia vazia com "Nenhuma fala foi reconhecida". A
# proteção se reconhece pela estrutura do arquivo, sem a licença:
#   * ASF/WMA/WMV (Windows Media DRM, PlayReady): os objetos de cifra do
#     cabeçalho ASF, pelo GUID (16 bytes; não aparecem por acaso);
#   * MP4/M4A/M4B/MOV/3GP (FairPlay do iTunes, CENC/PlayReady): a descrição
#     da trilha de áudio (stsd) com o tipo trocado por 'drms' ou 'enca'.
_GUID_ASF_CABECALHO = uuid.UUID("75B22630-668E-11CF-A6D9-00AA0062CE6C").bytes_le
_GUIDS_ASF_DRM = (
    uuid.UUID("2211B3FB-BD23-11D2-B4B7-00A0C955FC6E").bytes_le,   # Content Encryption
    uuid.UUID("298AE614-2622-4C17-B935-DAE07EE9289C").bytes_le,   # Extended Content Encryption
    uuid.UUID("43058533-6981-49E6-9B74-AD12CB86D58C").bytes_le,   # Advanced Content Encryption
    uuid.UUID("9A04F079-9840-4286-AB92-E65BE0885F95").bytes_le,   # Protection System Identifier
)
_CAIXAS_INICIAIS_MP4 = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot", b"styp"}
_CAIXAS_ATE_STSD = (b"trak", b"mdia", b"minf", b"stbl")
_AUDIO_CIFRADO_MP4 = {b"drms", b"enca"}
_LIMITE_CABECALHO = 64 * 1024 * 1024


def _caixas_mp4(dados: bytes, inicio: int, fim: int):
    """(tipo, início do conteúdo, fim) de cada caixa ISO-BMFF entre inicio e fim."""
    pos = inicio
    while pos + 8 <= fim:
        tamanho = int.from_bytes(dados[pos:pos + 4], "big")
        tipo = dados[pos + 4:pos + 8]
        cabeca = 8
        if tamanho == 1:
            if pos + 16 > fim:
                return
            tamanho = int.from_bytes(dados[pos + 8:pos + 16], "big")
            cabeca = 16
        elif tamanho == 0:
            tamanho = fim - pos
        if tamanho < cabeca or pos + tamanho > fim:
            return
        yield tipo, pos + cabeca, pos + tamanho
        pos += tamanho


def _audio_cifrado_no_moov(moov: bytes) -> bool:
    for tipo, ini, fim in _caixas_mp4(moov, 0, len(moov)):
        if tipo != b"trak":
            continue
        nivel = [(ini, fim)]
        for procurado in _CAIXAS_ATE_STSD[1:] + (b"stsd",):
            proximo = []
            for a, b in nivel:
                proximo += [(i, f) for t, i, f in _caixas_mp4(moov, a, b) if t == procurado]
            nivel = proximo
        for a, b in nivel:
            # stsd: versão e sinais (4), quantidade (4) e as descrições (caixas)
            for entrada, _i, _f in _caixas_mp4(moov, a + 8, b):
                if entrada in _AUDIO_CIFRADO_MP4:
                    return True
    return False


def _moov_do_arquivo(f, tamanho_arquivo: int) -> bytes | None:
    """O conteúdo da caixa 'moov' (no começo ou no fim do arquivo), ou None."""
    pos = 0
    for _ in range(10000):
        if pos + 8 > tamanho_arquivo:
            return None
        f.seek(pos)
        cabeca = f.read(16)
        if len(cabeca) < 8:
            return None
        tamanho = int.from_bytes(cabeca[:4], "big")
        tipo = cabeca[4:8]
        inicio = 8
        if tamanho == 1 and len(cabeca) == 16:
            tamanho, inicio = int.from_bytes(cabeca[8:16], "big"), 16
        elif tamanho == 0:
            tamanho = tamanho_arquivo - pos
        if tamanho < inicio:
            return None
        if pos == 0 and tipo not in _CAIXAS_INICIAIS_MP4:
            return None
        if tipo == b"moov":
            if tamanho > _LIMITE_CABECALHO:
                return None
            f.seek(pos + inicio)
            return f.read(tamanho - inicio)
        pos += tamanho
    return None


def protecao_drm(caminho: Path | str) -> str:
    """O nome da proteção, se o áudio do arquivo é cifrado (DRM); senão "".

    Nunca levanta: na dúvida (arquivo curto, estrutura que não se reconhece),
    "" - quem decide se o arquivo serve é a decodificação.
    """
    try:
        with open(caminho, "rb") as f:
            f.seek(0, 2)
            tamanho = f.tell()
            f.seek(0)
            inicio = f.read(30)
            if inicio[:16] == _GUID_ASF_CABECALHO and len(inicio) >= 24:
                cabecalho = int.from_bytes(inicio[16:24], "little")
                f.seek(0)
                dados = f.read(min(max(cabecalho, 30), _LIMITE_CABECALHO))
                if any(guid in dados for guid in _GUIDS_ASF_DRM):
                    return "Windows Media DRM"
                return ""
            if inicio[4:8] in _CAIXAS_INICIAIS_MP4:
                moov = _moov_do_arquivo(f, tamanho)
                if moov and _audio_cifrado_no_moov(moov):
                    return "FairPlay/CENC"
    except (OSError, ValueError):
        return ""
    return ""


def _frase_protegido(nome: str) -> str:
    return (f"'{nome}' é protegido contra cópia (DRM): o áudio é cifrado e só o programa que "
            "tem a licença consegue tocá-lo. Peça ao setor ou ao sistema de gravação a "
            "gravação original, sem proteção (por exemplo, exportada em MP3, WAV ou MP4).")


def _frase_danificado(nome: str) -> str:
    return (f"Não consegui ler '{nome}' como áudio ou vídeo: o arquivo parece cortado "
            "(copiado ou baixado pela metade), corrompido ou não é de áudio nem de vídeo. "
            "Confira se ele toca no reprodutor de mídia do Windows; se tocar só até um "
            "ponto, copie ou baixe a gravação de novo.")


def _frase_sem_trilha(nome: str, tem_video: bool) -> str:
    if tem_video:
        return (f"'{nome}' é um vídeo sem trilha de áudio: não há som para transcrever. "
                "Confira se a gravação foi feita com o som ligado ou se o sistema de "
                "gravação guardou o áudio num arquivo à parte.")
    return (f"'{nome}' não tem trilha de áudio: não há som para transcrever. Confira se é "
            "mesmo a gravação da audiência e se o arquivo foi copiado por inteiro.")


def _abrir_av(av, caminho: Path):
    try:
        try:
            return av.open(str(caminho), metadata_errors="ignore")
        except TypeError:  # PyAV 17+ não tem mais esse argumento
            return av.open(str(caminho))
    except FileNotFoundError:
        raise
    except PermissionError as erro:
        raise AudioIlegivel(f"Não consegui abrir '{caminho.name}': o arquivo está em uso por "
                            "outro programa ou sem permissão de leitura.") from erro
    except Exception as erro:
        # O texto do FFmpeg traz o caminho inteiro (que pode dizer o processo
        # e as partes): fica só no registro de depuração, e a frase diz o que
        # fazer.
        log.debug("o PyAV não abriu %s: %s", caminho.name, type(erro).__name__)
        if protecao_drm(caminho):
            raise ProtegidoPorDrm(_frase_protegido(caminho.name)) from erro
        raise ArquivoDanificado(_frase_danificado(caminho.name)) from erro


def _decodificar_av(caminho: Path, taxa: int) -> np.ndarray:
    try:
        import av
    except ImportError as erro:
        raise AudioIlegivel("O decodificador de áudio (PyAV) não está instalado. "
                            f"{sistema.REINSTALAR}") from erro
    if protecao_drm(caminho):
        raise ProtegidoPorDrm(_frase_protegido(caminho.name))
    recipiente = _abrir_av(av, caminho)
    partes: list[np.ndarray] = []
    with recipiente:
        if not recipiente.streams.audio:
            raise SemTrilhaDeAudio(_frase_sem_trilha(caminho.name,
                                                     bool(recipiente.streams.video)))
        # Com mais de uma trilha (dublagem, comentário), a principal - a que
        # o próprio FFmpeg escolheria para tocar.
        try:
            fluxo = recipiente.streams.best("audio") or recipiente.streams.audio[0]
        except Exception:
            fluxo = recipiente.streams.audio[0]
        reamostrador = av.AudioResampler(format="s16", layout="mono", rate=taxa)
        falhas = 0
        try:
            pacotes = recipiente.demux(fluxo)
            for pacote in pacotes:
                try:
                    quadros = pacote.decode()
                except Exception:
                    # pedaço corrompido (gravação cortada, rede): pula e segue
                    falhas += 1
                    continue
                for quadro in quadros:
                    try:
                        for saida in reamostrador.resample(quadro):
                            partes.append(saida.to_ndarray().reshape(-1).copy())
                    except Exception:
                        falhas += 1
        except (av.error.InvalidDataError, av.error.EOFError, OSError) as erro:
            # O arquivo acaba no meio de um pacote (cópia pela metade): fica o
            # que veio antes; sem nada, a frase do arquivo danificado.
            log.warning("%s: a leitura parou antes do fim (%s).", caminho.name,
                        type(erro).__name__)
            falhas += 1
        try:
            for saida in reamostrador.resample(None):
                partes.append(saida.to_ndarray().reshape(-1).copy())
        except Exception:
            pass
        if falhas:
            log.warning("%s: %d pedaço(s) de áudio ilegível(is) foram pulados.", caminho.name, falhas)
    if not partes:
        if falhas:
            raise ArquivoDanificado(_frase_danificado(caminho.name))
        raise SemTrilhaDeAudio(f"'{caminho.name}' tem trilha de áudio, mas ela está vazia: "
                               "não há som para transcrever.")
    audio = np.concatenate(partes).astype(np.float32)
    del partes
    audio *= np.float32(1.0 / 32768.0)   # no lugar: 3 h são ~700 MB a menos no pico
    return audio


def decodificar(caminho: Path | str, taxa: int = TAXA) -> np.ndarray:
    """O áudio do arquivo, mono, `taxa` Hz, float32 entre -1 e 1."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
    audio = _decodificar_soundfile(caminho, taxa)
    if audio is not None:
        return audio
    return _decodificar_av(caminho, taxa)


# ------------------------------------------------------- pré-tratamento
def _filtrar_bloco(trecho: np.ndarray, taxa: int, corte_hz: float) -> np.ndarray:
    """Passa-alta Butterworth de 2ª ordem aplicado na frequência (fase zero).

    É a mesma curva do `highpass=f=80` do ffmpeg que a base usava (-12 dB por
    oitava abaixo do corte), sem precisar de scipy nem de laço por amostra.
    """
    n = trecho.size
    nfft = 1 << max(1, (n - 1).bit_length())
    espectro = np.fft.rfft(trecho, nfft)
    freqs = np.fft.rfftfreq(nfft, 1.0 / taxa)
    with np.errstate(divide="ignore"):
        ganho = 1.0 / np.sqrt(1.0 + (corte_hz / np.maximum(freqs, 1e-6)) ** 4)
    ganho[0] = 0.0
    return np.fft.irfft(espectro * ganho, nfft)[:n].astype(np.float32)


def passa_alta(audio: np.ndarray, taxa: int = TAXA, corte_hz: float = 80.0,
               bloco_s: float = 120.0, copiar: bool = True) -> np.ndarray:
    """Tira o ronco de ar-condicionado/rede elétrica e o nível contínuo.

    Em blocos com margem (a margem absorve a borda de cada bloco), para não
    estourar a memória; com `copiar=False` reaproveita o próprio vetor
    (3 h de áudio são ~700 MB).
    """
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        return audio.copy() if copiar else audio
    saida = np.empty_like(audio) if copiar else audio
    margem = int(0.5 * taxa)
    passo = max(margem, int(bloco_s * taxa))
    anterior: np.ndarray | None = None   # fim ORIGINAL do bloco anterior
    for ini in range(0, audio.size, passo):
        fim = min(audio.size, ini + passo)
        atual = audio[ini:min(audio.size, fim + margem)].copy()
        trecho = np.concatenate([anterior, atual]) if anterior is not None else atual
        deslocamento = anterior.size if anterior is not None else 0
        filtrado = _filtrar_bloco(trecho, taxa, corte_hz)
        anterior = atual[max(0, (fim - ini) - margem):fim - ini].copy()
        saida[ini:fim] = filtrado[deslocamento:deslocamento + (fim - ini)]
    return saida


def normalizar_volume(audio: np.ndarray, taxa: int = TAXA, alvo_db: float = -20.0,
                      copiar: bool = True) -> np.ndarray:
    """Equaliza o volume entre quem fala perto e longe do microfone.

    Ganho por janela de 0,5 s, medido só onde há fala (o silêncio não é
    amplificado), limitado a ±10 dB em torno do ganho geral e suavizado em
    ~3 s para não "bombear". Picos são contidos por um limitador suave.
    """
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        return audio
    jan = int(0.5 * taxa)
    n_jan = max(1, audio.size // jan)
    corpo = audio[:n_jan * jan].reshape(n_jan, jan) if audio.size >= jan else audio.reshape(1, -1)
    rms = np.sqrt(np.mean(np.square(corpo, dtype=np.float64), axis=1)) + 1e-9
    db = 20 * np.log10(rms)
    piso = np.percentile(db, 10)
    fala = db > piso + 10
    if not fala.any():  # só ruído: ganho fixo moderado, sem perseguir o nível
        pico = float(np.max(np.abs(audio))) or 1.0
        saida = audio.copy() if copiar else audio
        saida *= np.float32(min(4.0, 0.5 / pico))
        return saida
    geral = alvo_db - float(np.median(db[fala]))
    geral = float(np.clip(geral, -10.0, 30.0))
    ganho = np.full(n_jan, geral)
    ganho[fala] = np.clip(alvo_db - db[fala], geral - 10.0, geral + 10.0)
    k = min(7, n_jan)
    ganho = np.convolve(np.pad(ganho, (k // 2, k - 1 - k // 2), mode="edge"),
                        np.ones(k) / k, mode="valid")
    centros = (np.arange(n_jan) + 0.5) * jan
    saida = np.empty_like(audio) if copiar else audio
    passo = 60 * taxa
    for ini in range(0, audio.size, passo):
        pos = np.arange(ini, min(audio.size, ini + passo))
        g = np.power(10.0, np.interp(pos, centros, ganho) / 20.0).astype(np.float32)
        y = audio[ini:ini + pos.size] * g
        # limitador suave: acima de 0,9 comprime em vez de cortar
        excesso = np.abs(y) > 0.9
        if excesso.any():
            y[excesso] = np.sign(y[excesso]) * (0.9 + 0.1 * np.tanh((np.abs(y[excesso]) - 0.9) / 0.1))
        saida[ini:ini + pos.size] = y
    return saida


def preparar_audio(audio: np.ndarray, taxa: int = TAXA, copiar: bool = True) -> np.ndarray:
    filtrado = passa_alta(audio, taxa, copiar=copiar)
    return normalizar_volume(filtrado, taxa, copiar=False)


# ------------------------------------------------------------ transcrever
def numero_do_nome(texto: str) -> cnj.Numero | None:
    """O número CNJ escrito num nome de arquivo ou pasta (com o dependente).

    O próprio programa grava o processo dependente com "-NN" no nome (o
    Windows não aceita "/"): "0700123-45.2024.8.02.0001-01 2026-09-16
    14h00.flac", a pasta "_controle/midias/0700123-45.2024.8.02.0001-01". O
    "-inc0001" é da base. Sem isto, a gravação do incidente virava a
    transcrição do principal. A leitura é a do núcleo (cnj.ler_nome_arquivo),
    a mesma do download e do compartilhamento, para as leituras não divergirem.
    """
    try:
        return cnj.ler_nome_arquivo(texto or "")
    except cnj.NumeroInvalido:
        return None


def numero_do_caminho(caminho: Path | str) -> cnj.Numero | None:
    """O número do processo pelo nome do arquivo ou, senão, pela pasta.

    As gravações baixadas dos autos ficam em
    `_controle/midias/<número>/<nome dado pelo portal>`: o número está na
    pasta, não no arquivo.
    """
    caminho = Path(caminho)
    for nome in (caminho.name, caminho.parent.name):
        numero = numero_do_nome(nome)
        if numero is not None:
            return numero
    return None


def _numero_do_arquivo(origem: Path, numero) -> cnj.Numero:
    if isinstance(numero, cnj.Numero):
        return numero
    if numero:
        # o número digitado pode vir como o do nome do DOCX ("...0001-01")
        return cnj.ler_nome_arquivo(str(numero))
    achado = numero_do_caminho(origem)
    if achado is not None:
        return achado
    raise ProcessoNaoInformado(
        f"Não encontrei o número do processo no nome '{origem.name}'. Informe o número.")


def _destino_padrao(cfg, numero: cnj.Numero, sigiloso: bool) -> Path:
    """<pasta das transcrições>/<número>.docx, com nome livre ("(2)")."""
    pasta = pasta_das_transcricoes(cfg, numero, sigiloso)
    pasta.mkdir(parents=True, exist_ok=True)
    return sistema.destino_livre(pasta, numero.nome_arquivo, ".docx")


def _dentro_de(caminho: Path, pasta) -> bool:
    if not pasta:
        return False
    try:
        Path(caminho).resolve().relative_to(Path(pasta).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def transcrever_arquivo(origem: Path, numero, cfg,
                        progresso: Callable[[float, str], None] | None = None,
                        cancelado: Callable[[], bool] | None = None,
                        rotulos_manuais: list[Fala] | None = None,
                        destino: Path | None = None, *,
                        meta: MetaAudiencia | None = None,
                        modelo: str | None = None,
                        separar: bool | None = None,
                        num_falantes: int = 0,
                        motor_fabrica: Callable[[], object] | None = None,
                        diarizador: Callable[..., list] | None = None,
                        audio: np.ndarray | None = None,
                        sigiloso: bool = False) -> Path:
    """Transcreve a gravação e grava o DOCX (nome = número do processo).

    `progresso(fração 0..1, texto)`; `cancelado()` -> True interrompe
    (levanta `Cancelado`, nada é gravado). `rotulos_manuais`: as falas da
    audiência ao vivo, cujos rótulos dão nome às vozes separadas. Devolve o
    caminho do DOCX. Sem `destino`, o DOCX vai para a pasta de transcrições
    do acervo - ou para a dos sigilosos, se `sigiloso` ou se os autos do
    processo estiverem lá. `motor_fabrica`, `diarizador` e `audio` existem para os
    testes (modelo dublê, separação simulada, áudio já em memória).
    """
    origem = Path(origem)
    numero = _numero_do_arquivo(origem, numero)
    # Horas de processamento: o Windows não pode suspender no meio (o estado
    # vale para a thread que chama, que é a de trabalho).
    with energia.manter_acordado("transcrição de gravação"):
        return _transcrever(origem, numero, cfg, progresso, cancelado, rotulos_manuais, destino,
                            meta, modelo, separar, num_falantes, motor_fabrica, diarizador, audio,
                            sigiloso)


def _transcrever(origem, numero, cfg, progresso, cancelado, rotulos_manuais, destino, meta,
                 modelo, separar, num_falantes, motor_fabrica, diarizador, audio,
                 sigiloso=False) -> Path:
    def avisar(fracao: float, texto: str) -> None:
        if progresso:
            try:
                progresso(max(0.0, min(1.0, fracao)), texto)
            except Exception:  # pragma: no cover
                pass

    def conferir() -> None:
        if cancelado and cancelado():
            raise Cancelado()

    nome_modelo = modelos.nome_canonico(modelo or cfg.texto("transcricao", "modelo_revisao")
                                        or "medium")
    avisar(0.0, f"Lendo o áudio de {origem.name}...")
    proprio = audio is None
    if audio is None:
        audio = decodificar(origem, TAXA)
    duracao = audio.size / TAXA
    if duracao < 0.5:
        raise SemFala(f"'{origem.name}' tem menos de meio segundo de áudio.")
    conferir()
    avisar(0.03, "Tratando o áudio (ruído e volume)...")
    # o vetor decodificado aqui é nosso: tratá-lo no lugar poupa memória
    tratado = preparar_audio(audio, copiar=not proprio)
    del audio
    conferir()

    if separar is None:
        separar = cfg.flag("transcricao", "separar_falantes")
    usar_falantes = bool(separar) and (diarizador is not None or mod_falantes.disponivel())

    avisar(0.05, f"Carregando o modelo {nome_modelo}...")
    if motor_fabrica is not None:
        motor = motor_fabrica()
    else:
        motor = modelos.carregar(
            nome_modelo, cfg.inteiro("transcricao", "threads"),
            # 0,05 a 0,08: o download (se faltar o modelo) não faz a barra voltar
            progresso=lambda f, t: avisar(0.05 + 0.03 * f, t))
    conferir()

    contexto = cfg.texto("transcricao", "contexto")
    filtro = modelos.FiltroDeAlucinacao(contexto)
    t0 = time.monotonic()
    segmentos, _info = motor.transcribe(
        tratado, language="pt", task="transcribe", beam_size=5,
        initial_prompt=contexto or None, condition_on_previous_text=False,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 700, "speech_pad_ms": 200},
        no_speech_threshold=0.6, compression_ratio_threshold=2.4,
        temperature=TEMPERATURAS, word_timestamps=usar_falantes)

    fim_transcricao = 0.85 if usar_falantes else 0.95
    falas: list[Fala] = []
    for seg in segmentos:  # o trabalho acontece aqui (gerador preguiçoso)
        conferir()
        texto = filtro.aceitar(seg)
        fim_seg = float(getattr(seg, "end", 0.0) or 0.0)
        if texto:
            palavras = None
            if getattr(seg, "words", None):
                palavras = [(float(w.start), float(w.end), str(w.word)) for w in seg.words]
            falas.append(Fala(float(seg.start), fim_seg, "", texto, palavras))
        fracao = min(1.0, fim_seg / duracao) if duracao else 1.0
        decorrido = time.monotonic() - t0
        restante = decorrido / fracao * (1 - fracao) if fracao > 0.02 else 0
        avisar(0.08 + (fim_transcricao - 0.08) * fracao,
               f"Transcrevendo: {fracao:.0%}" + (f" (faltam ~{int(restante // 60) + 1} min)"
                                                 if restante else ""))
    log.info("%s: %d trecho(s) reconhecido(s), %d descartado(s) pelo filtro "
             "(%d por repetição emendada).",
             origem.name, len(falas), filtro.descartados, filtro.repeticoes)
    if not falas:
        raise SemFala("Nenhuma fala foi reconhecida. O áudio pode estar mudo, com volume "
                      "muito baixo ou conter apenas ruído.")
    conferir()

    manuais = [m for m in (rotulos_manuais or []) if (m.falante or "").strip()]
    automaticos = False
    if usar_falantes:
        avisar(fim_transcricao, "Separando as vozes...")
        funcao = diarizador or mod_falantes.diarizar
        try:
            turnos = funcao(tratado, num_falantes,
                            progresso=lambda f: avisar(fim_transcricao + 0.12 * f,
                                                       f"Separando as vozes: {f:.0%}"),
                            cancelado=cancelado)
        except mod_falantes.Cancelado:
            raise Cancelado()
        except Cancelado:
            raise
        except Exception as erro:  # a separação é um extra: falhou, segue sem ela
            log.warning("a separação de falantes falhou: %s", erro)
            turnos = []
        conferir()
        if turnos:
            falas = mod_falantes.atribuir(falas, turnos)
            automaticos = True
            if manuais:
                mapa = mod_falantes.votar_rotulos(falas, manuais)
                falas = [Fala(f.inicio, f.fim, mapa.get(f.falante, f.falante), f.texto)
                         for f in falas]
    if not automaticos and manuais:
        falas = mod_falantes.rotular_por_sobreposicao(falas, manuais)
    # As marcações da audiência ao vivo (pausa da gravação: sem falante e sem
    # duração) continuam na revisão; fala de verdade sem rótulo, não.
    marcas = [Fala(m.inicio, m.fim, "", m.texto) for m in (rotulos_manuais or [])
              if not (m.falante or "").strip() and (m.texto or "").strip()
              and (m.fim - m.inicio) < 0.01]
    if marcas:
        falas = sorted(falas + marcas, key=lambda f: f.inicio)

    avisar(0.97, "Gravando o documento...")
    if meta is None:
        meta = MetaAudiencia(numero=numero.formatado)
    # A tela passa uma ficha só com o tipo da audiência: o resto (unidade,
    # magistrado, data) vem da configuração e do arquivo, como sem ficha. E
    # o padrão do MetaAudiencia é "ao vivo", que aqui seria falso.
    if meta.origem not in ("revisão", "gravação"):
        meta.origem = "revisão" if rotulos_manuais else "gravação"
    if meta.data is None:
        try:
            meta.data = datetime.fromtimestamp(origem.stat().st_mtime)
        except OSError:
            meta.data = datetime.now()
    meta.unidade = meta.unidade or unidade_da_config(cfg)
    meta.magistrado = meta.magistrado or magistrado_da_config(cfg)
    meta.numero = meta.numero or numero.formatado
    meta.modelo = nome_modelo
    meta.duracao = duracao
    meta.gravacao = meta.gravacao or origem.name
    # A gravação guardada na pasta de sigilosos (a de uma audiência
    # sigilosa, no "Revisar agora", ou a mídia baixada com os autos) é
    # sigilosa, mesmo sem os autos lá.
    sigiloso = sigiloso or _dentro_de(origem, getattr(cfg, "pasta_sigilosos", None))
    marcar_tempo = cfg.flag("transcricao", "marcar_tempo")
    if destino is None:
        caminho = gerar_docx(_destino_padrao(cfg, numero, sigiloso), falas, meta,
                             marcar_tempo=marcar_tempo, legenda_automatica=False)
    else:
        try:
            caminho = gerar_docx(Path(destino), falas, meta, marcar_tempo=marcar_tempo,
                                 legenda_automatica=False)
        except OSError as erro:
            # Horas de trabalho não se perdem por causa do destino (pasta no
            # lugar do arquivo, pasta sem permissão, disco removido): o
            # documento vai para a pasta das transcrições - a dos sigilosos,
            # se for o caso, nunca o acervo para um processo sigiloso.
            caminho = gerar_docx(_destino_padrao(cfg, numero, sigiloso), falas, meta,
                                 marcar_tempo=marcar_tempo, legenda_automatica=False)
            log.warning("não consegui gravar a transcrição em %s (%s); gravada em %s.",
                        destino, erro, caminho)
    avisar(1.0, f"Transcrição pronta: {caminho.name}")
    log.info("transcrição gravada em %s", caminho)
    return caminho
