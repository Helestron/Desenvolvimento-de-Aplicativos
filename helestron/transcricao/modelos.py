"""Modelos Whisper (faster-whisper / CTranslate2): baixar, carregar e filtrar.

Diferenças em relação ao Assessor SAJ, todas por problemas reais:
  * o modelo fica numa pasta simples (runtime\\modelos\\whisper-small), não no
    cache do Hugging Face. Na base, CADA abertura tentava a rede primeiro e só
    depois usava o arquivo local - em rede de tribunal com proxy, ou offline,
    era espera de timeout toda vez. Aqui, instalado = carregado do disco, sem
    rede nenhuma;
  * no máximo 2 modelos na memória (o ao vivo e o da revisão); a base nunca
    descarregava, e trocar o modelo deixava dois na RAM;
  * metade dos núcleos por padrão: com todos, a captura do microfone e o
    navegador do download disputam CPU e o áudio picota;
  * download com progresso, retomável (o arquivo parcial fica e continua de
    onde parou), pela pilha de certificados do Windows (truststore: redes com
    inspeção TLS) e pelo proxy configurado no Windows.

Também mora aqui o filtro de "alucinações": frases que o Whisper inventa no
silêncio ("Legendas pela comunidade Amara.org"), repetições em laço e o eco
do texto de contexto.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
import unicodedata
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from ..nucleo import caminhos

log = logging.getLogger("transcricao.modelos")

# nome -> (repositório no Hugging Face, tamanho aproximado em MB)
CATALOGO: dict[str, tuple[str, int]] = {
    "base": ("Systran/faster-whisper-base", 145),
    "small": ("Systran/faster-whisper-small", 484),
    "medium": ("Systran/faster-whisper-medium", 1530),
    "large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1620),
}
APELIDOS = {"turbo": "large-v3-turbo", "large-turbo": "large-v3-turbo",
            "large-v3turbo": "large-v3-turbo", "pequeno": "small", "medio": "medium",
            "médio": "medium", "basico": "base", "básico": "base"}
DESCRICAO = {
    "base": "rápido, para computador modesto (qualidade razoável)",
    "small": "recomendado para a audiência ao vivo",
    "medium": "mais preciso; bom para a revisão final",
    "large-v3-turbo": "o mais preciso; revisão em computador forte",
}

NECESSARIOS = ("model.bin", "config.json", "tokenizer.json")
PADROES_DOWNLOAD = ["config.json", "preprocessor_config.json", "model.bin",
                    "tokenizer.json", "vocabulary.*"]

PASTA: Path = caminhos.MODELOS     # trocável nos testes
MAXIMO_NA_MEMORIA = 2

_cache: "OrderedDict[tuple, object]" = OrderedDict()
_trava = threading.RLock()
_travas_download: dict[str, threading.Lock] = {}


class ModeloAusente(RuntimeError):
    """O modelo não está instalado e não pôde ser baixado."""


class ErroDoModelo(RuntimeError):
    """O modelo existe, mas não abriu (arquivo corrompido, DLL ausente)."""


# ------------------------------------------------------------ consultas
def nome_canonico(nome: str) -> str:
    n = (nome or "").strip().lower()
    n = APELIDOS.get(n, n)
    if n not in CATALOGO:
        opcoes = ", ".join(CATALOGO)
        raise ValueError(f"modelo '{nome}' desconhecido; escolha um destes: {opcoes}")
    return n


def pasta_do_modelo(nome: str) -> Path:
    return Path(PASTA) / f"whisper-{nome_canonico(nome)}"


def instalado(nome: str) -> bool:
    try:
        pasta = pasta_do_modelo(nome)
    except ValueError:
        return False
    try:
        if not all((pasta / arq).is_file() for arq in NECESSARIOS):
            return False
        # model.bin minúsculo = cópia interrompida, não um modelo
        return (pasta / "model.bin").stat().st_size > 1_000_000
    except OSError:
        return False


def instalados() -> list[str]:
    return [n for n in CATALOGO if instalado(n)]


def tamanho_mb(nome: str) -> int:
    return CATALOGO[nome_canonico(nome)][1]


def listar() -> list[dict]:
    """Uma linha por modelo do catálogo (para a tela e para a CLI)."""
    linhas = []
    for nome, (repo, mb) in CATALOGO.items():
        linhas.append({"nome": nome, "repositorio": repo, "mb": mb,
                       "instalado": instalado(nome), "pasta": pasta_do_modelo(nome),
                       "descricao": DESCRICAO.get(nome, "")})
    return linhas


NO_WINDOWS = sys.platform == "win32"


def _nome_curto_windows(texto: str) -> str | None:  # pragma: no cover - só no Windows
    import ctypes
    from ctypes import wintypes

    funcao = ctypes.windll.kernel32.GetShortPathNameW
    funcao.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    funcao.restype = wintypes.DWORD
    tamanho = funcao(texto, None, 0)
    if not tamanho:
        return None
    buf = ctypes.create_unicode_buffer(tamanho)
    return buf.value if funcao(texto, buf, tamanho) else None


def caminho_nativo(caminho: Path | str) -> str:
    """O caminho a entregar às bibliotecas em C++ (CTranslate2, sherpa-onnx).

    Elas abrem o arquivo com o caminho em bytes, que o Windows lê na página
    de código ANSI (cp1252): numa pasta com acento - "C:\\Users\\joão\\..." -
    o "ã" em UTF-8 vira "Ã£" e o modelo "não existe". O nome curto 8.3 do
    Windows (C:\\Users\\JOO~1\\...) é só ASCII e aponta para o mesmo lugar.
    Fora do Windows, ou com caminho já ASCII, nada muda.
    """
    texto = str(caminho)
    if not NO_WINDOWS or texto.isascii():
        return texto
    try:
        curto = _nome_curto_windows(texto)
    except Exception as erro:  # pragma: no cover
        log.debug("GetShortPathNameW falhou: %s", erro)
        curto = None
    if curto and curto.isascii():
        return curto
    log.warning("o caminho %s tem acento e o Windows não deu um nome curto sem acento; "
                "se o modelo não abrir, instale o programa em C:\\AssessorIntegrado.", texto)
    return texto


def threads_padrao(threads: int = 0) -> int:
    """Núcleos para o modelo: o configurado, ou metade dos disponíveis."""
    if threads and threads > 0:
        return int(threads)
    return max(1, (os.cpu_count() or 2) // 2)


# ------------------------------------------------------------------ rede
def preparar_rede() -> None:
    """Ajusta o ambiente ANTES de importar huggingface_hub/faster_whisper.

    As variáveis do Hugging Face são lidas na importação; definidas depois,
    não valem. O transporte "xet" (cliente próprio, em Rust) não usa o proxy
    nem os certificados do Windows, e trava em rede de tribunal: forçamos o
    HTTPS comum, que passa pelo proxy e pelo truststore.
    """
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # pragma: no cover - opcional
        pass
    # O httpx (usado pelo huggingface_hub) só enxerga proxy em variável de
    # ambiente; o proxy configurado no Windows fica no registro.
    if not any(os.environ.get(v) for v in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")):
        try:
            import urllib.request

            proxies = urllib.request.getproxies()
            proxy = proxies.get("https") or proxies.get("http")
            if proxy:
                os.environ["HTTPS_PROXY"] = proxy
                log.info("usando o proxy do sistema para baixar modelos: %s", proxy)
        except Exception:  # pragma: no cover
            pass
    try:  # se já importado por outro caminho, ajusta a constante em memória
        import sys

        constantes = sys.modules.get("huggingface_hub.constants")
        if constantes is not None and os.environ.get("HF_HUB_DISABLE_XET") == "1":
            constantes.HF_HUB_DISABLE_XET = True
    except Exception:  # pragma: no cover
        pass


def _mensagem_de_falha(erro: BaseException, nome: str) -> str:
    texto = f"{type(erro).__name__}: {erro}"
    baixo = texto.lower()
    pasta = pasta_do_modelo(nome)
    if isinstance(erro, OSError) and getattr(erro, "errno", None) == 28 or "no space" in baixo:
        return (f"Disco cheio ao baixar o modelo '{nome}' (~{tamanho_mb(nome)} MB). "
                "Libere espaço e tente de novo; o download continua de onde parou.")
    if "certificate" in baixo or "ssl" in baixo:
        return ("A conexão segura com huggingface.co foi recusada (a rede do tribunal "
                "pode inspecionar o tráfego HTTPS). Peça à TI a liberação de "
                "huggingface.co e *.hf.co, ou copie a pasta "
                f"{pasta.name} de outro computador para {pasta.parent}. Detalhe: {texto[:200]}")
    if any(p in baixo for p in ("connect", "timeout", "timed out", "proxy", "network",
                                "resolve", "getaddrinfo", "unreachable", "offline")):
        return (f"Sem acesso a huggingface.co para baixar o modelo '{nome}'. Confira a "
                "internet; se a rede do tribunal bloquear o site, peça à TI a liberação "
                "de huggingface.co e *.hf.co, ou copie a pasta "
                f"{pasta.name} de outro computador para {pasta.parent}. "
                f"O download continua de onde parou. Detalhe: {texto[:200]}")
    return f"Não consegui baixar o modelo '{nome}': {texto[:300]}"


def _bytes_na_pasta(pasta: Path) -> int:
    total = 0
    try:
        for p in pasta.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def baixar(nome: str, progresso: Callable[[float, str], None] | None = None,
           tentativas: int = 3) -> Path:
    """Baixa o modelo para runtime\\modelos\\whisper-<nome> e devolve a pasta.

    `progresso(fração 0..1, texto)`. Retomável: o que já veio fica em disco.
    Levanta ModeloAusente com mensagem para o usuário se não conseguir.
    """
    nome = nome_canonico(nome)

    def avisar(fracao: float, texto: str) -> None:
        if progresso:
            try:
                progresso(max(0.0, min(1.0, fracao)), texto)
            except Exception:  # pragma: no cover
                pass

    # Um download por modelo de cada vez: a tela de Configurações e a
    # transcrição podem pedir o mesmo modelo juntas; quem chega depois
    # espera e encontra o modelo pronto.
    with _trava:
        trava_modelo = _travas_download.setdefault(nome, threading.Lock())
    if not trava_modelo.acquire(blocking=False):
        avisar(0.0, f"Aguardando o download do modelo {nome}, já em andamento...")
        trava_modelo.acquire()
    try:
        return _baixar(nome, avisar, tentativas)
    finally:
        trava_modelo.release()


def _baixar(nome: str, avisar: Callable[[float, str], None], tentativas: int) -> Path:
    repo, mb = CATALOGO[nome]
    pasta = pasta_do_modelo(nome)
    if instalado(nome):
        avisar(1.0, f"Modelo {nome} já instalado.")
        return pasta

    preparar_rede()
    try:
        from huggingface_hub import snapshot_download
    except ImportError as erro:
        raise ModeloAusente("O componente de download de modelos (huggingface_hub) não "
                            "está instalado. Rode o INSTALAR.bat de novo.") from erro
    try:
        pasta.mkdir(parents=True, exist_ok=True)
    except OSError as erro:
        raise ModeloAusente(f"Não consegui criar a pasta {pasta}: {erro}") from erro

    total = mb * 1_000_000
    parar = threading.Event()

    def vigiar() -> None:
        while not parar.wait(1.0):
            feito = _bytes_na_pasta(pasta)
            avisar(min(0.99, feito / total),
                   f"Baixando o modelo {nome}: {feito // 1_000_000} de ~{mb} MB")

    vigia = threading.Thread(target=vigiar, name=f"vigia-download-{nome}", daemon=True)
    avisar(0.0, f"Baixando o modelo {nome} (~{mb} MB)...")
    vigia.start()
    ultimo_erro: BaseException | None = None
    try:
        for tentativa in range(1, max(1, tentativas) + 1):
            try:
                snapshot_download(repo, local_dir=str(pasta), allow_patterns=PADROES_DOWNLOAD)
                ultimo_erro = None
                break
            except Exception as erro:
                ultimo_erro = erro
                log.warning("download do modelo %s falhou (tentativa %d): %s",
                            nome, tentativa, erro)
                if tentativa < tentativas:
                    time.sleep(min(30, 5 * tentativa))
    finally:
        parar.set()
        vigia.join(timeout=3)

    if ultimo_erro is not None:
        raise ModeloAusente(_mensagem_de_falha(ultimo_erro, nome)) from ultimo_erro
    if not instalado(nome):
        raise ModeloAusente(f"O download do modelo '{nome}' terminou incompleto. "
                            "Tente de novo: ele continua de onde parou.")
    avisar(1.0, f"Modelo {nome} instalado.")
    log.info("modelo %s instalado em %s", nome, pasta)
    return pasta


# ----------------------------------------------------------------- carga
def carregar(nome: str, threads: int = 0,
             progresso: Callable[[float, str], None] | None = None,
             baixar_se_faltar: bool = True):
    """O WhisperModel pronto para uso (em cache; no máximo 2 na memória).

    Sempre do diretório local: depois de instalado, nunca toca na rede.
    """
    nome = nome_canonico(nome)
    n_threads = threads_padrao(threads)
    chave = (nome, n_threads)
    with _trava:
        if chave in _cache:
            _cache.move_to_end(chave)
            return _cache[chave]
    if not instalado(nome):
        if not baixar_se_faltar:
            raise ModeloAusente(
                f"O modelo '{nome}' não está instalado. Baixe-o em Configurações > "
                "Transcrição (ou rode: python -m helestron modelos baixar " + nome + ").")
        # FORA da trava geral: baixar o medium leva minutos, e com a trava a
        # audiência ao vivo que começasse nesse meio-tempo ficava sem
        # transcrição (o "small", já instalado, esperava o download do outro).
        baixar(nome, progresso)
    with _trava:
        if chave in _cache:   # outra thread carregou enquanto baixávamos
            _cache.move_to_end(chave)
            return _cache[chave]
        preparar_rede()
        try:
            from faster_whisper import WhisperModel
        except ImportError as erro:
            raise ErroDoModelo(
                "O motor de transcrição (faster-whisper) não pôde ser carregado: "
                f"{erro}. Rode o INSTALAR.bat de novo.") from erro
        pasta = pasta_do_modelo(nome)
        if progresso:
            try:
                progresso(1.0, f"Abrindo o modelo {nome}...")
            except Exception:  # pragma: no cover
                pass
        log.info("carregando o modelo Whisper '%s' (%d núcleos)...", nome, n_threads)
        try:
            modelo = WhisperModel(caminho_nativo(pasta), device="cpu", compute_type="int8",
                                  cpu_threads=n_threads)
        except Exception as erro:
            raise ErroDoModelo(
                f"Não consegui abrir o modelo '{nome}' ({erro}). A pasta pode estar "
                f"corrompida: apague {pasta} e baixe o modelo de novo em "
                "Configurações > Transcrição.") from erro
        _cache[chave] = modelo
        while len(_cache) > MAXIMO_NA_MEMORIA:
            antigo, _ = _cache.popitem(last=False)
            log.info("modelo %s descarregado da memória.", antigo[0])
        return modelo


def descarregar(nome: str | None = None) -> None:
    """Tira da memória um modelo (ou todos)."""
    with _trava:
        for chave in list(_cache):
            if nome is None or chave[0] == nome_canonico(nome):
                del _cache[chave]


# ===================================================== saída do modelo
# Frases que o Whisper "ouve" no silêncio: vêm das legendas de vídeos com
# que ele foi treinado. Comparadas sem acento, sem pontuação, em minúsculas.
FANTASMAS_CONTIDOS = (
    "amara org", "legendas pela comunidade", "legendado por", "legendas por",
    "legenda adriana zanotto", "inscreva se", "se inscreva", "obrigado por assistir",
    "obrigada por assistir", "obrigado por assistirem", "ative o sininho",
    "deixe seu like", "sous titres", "subtitles by",
)
FANTASMAS_EXATOS = ("tchau tchau", "tchau tchau tchau", "e ai", "musica", "aplausos")


def normalizar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                         if unicodedata.category(c) != "Mn")
    limpo = re.sub(r"[^0-9a-z]+", " ", sem_acento.lower())
    return re.sub(r"\s+", " ", limpo).strip()


class FiltroDeAlucinacao:
    """Decide se um segmento devolvido pelo Whisper é fala de verdade.

    Descarta: (a) "silêncio" que o modelo transcreveu (probabilidade alta de
    não haver fala com confiança baixa - o critério do próprio Whisper);
    (b) texto em laço (taxa de compressão alta); (c) confiança baixíssima;
    (d) frases-fantasma conhecidas; (e) eco do texto de contexto; (f) a
    mesma frase repetida em seguida.
    """

    def __init__(self, contexto: str = "", sem_fala: float = 0.6, logprob: float = -1.0,
                 compressao: float = 2.4, logprob_minimo: float = -2.0):
        self.sem_fala = sem_fala
        self.logprob = logprob
        self.compressao = compressao
        self.logprob_minimo = logprob_minimo
        self._contexto = normalizar(contexto)
        self._anterior = ""
        self.descartados = 0

    def aceitar(self, seg, mesmo_trecho: bool = False) -> str | None:
        """Texto limpo do segmento, ou None se for alucinação."""
        texto = re.sub(r"\s+", " ", str(getattr(seg, "text", "") or "")).strip()
        motivo = self._motivo(seg, texto, mesmo_trecho)
        if motivo:
            self.descartados += 1
            log.debug("descartado (%s): %r", motivo, texto[:80])
            return None
        self._anterior = normalizar(texto)
        return texto

    def _motivo(self, seg, texto: str, mesmo_trecho: bool) -> str:
        if not texto:
            return "vazio"
        n = normalizar(texto)
        if not n:
            return "só pontuação"
        sem_fala = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
        logprob = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
        compressao = float(getattr(seg, "compression_ratio", 1.0) or 1.0)
        if sem_fala > self.sem_fala and logprob < self.logprob:
            return "silêncio"
        if compressao > self.compressao:
            return "laço"
        if logprob < self.logprob_minimo:
            return "confiança baixa"
        if n in FANTASMAS_EXATOS or any(f in n for f in FANTASMAS_CONTIDOS):
            return "frase-fantasma"
        if self._contexto and len(n) >= 20 and (n in self._contexto
                                                 or self._contexto.startswith(n[:40])):
            return "eco do contexto"
        if n == self._anterior and (len(n) >= 15 or mesmo_trecho):
            return "repetição"
        return ""
