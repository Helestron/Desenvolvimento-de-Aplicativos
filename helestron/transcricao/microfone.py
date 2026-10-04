"""Captura de som: o microfone (sounddevice/PortAudio) e, para testes e CI,
um arquivo de áudio tocado como se fosse o microfone.

Armadilhas do Windows que este módulo trata:
  * a privacidade do Windows ("Permitir que aplicativos da área de trabalho
    acessem o microfone" desligado) NÃO dá erro: o fluxo abre e entrega
    silêncio absoluto. Medimos o nível e avisamos depois de ~5 s de zeros;
  * o mesmo microfone aparece 3 ou 4 vezes na lista do PortAudio (MME,
    DirectSound, WASAPI, WDM-KS), com o nome cortado em 31 letras no MME.
    A lista mostra cada aparelho uma vez só (prefere WASAPI, depois MME);
  * no WASAPI compartilhado, só a taxa nativa do aparelho (44,1 ou 48 kHz)
    abre. Abrimos na taxa nativa e reamostramos para 16 kHz aqui mesmo;
  * microfone USB que se solta no meio da audiência: o fluxo para de
    entregar blocos sem erro nenhum. Detectamos o silêncio de blocos, avisamos
    e tentamos reabrir sozinhos a cada poucos segundos.

O callback do PortAudio roda numa thread de tempo real: qualquer demora lá
vira estalo ou perda de áudio. Por isso ele só copia o bloco para uma fila;
uma thread nossa reamostra, mede o nível e entrega o bloco a quem gravou.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass
from math import gcd
from pathlib import Path
from typing import Callable

import numpy as np

from ..nucleo import sistema

log = logging.getLogger("transcricao.microfone")

TAXA = 16000
BLOCO_S = 0.1          # ~100 ms por bloco: latência baixa, pouca sobrecarga
MUDO_RMS = 3e-5        # ~ -90 dBFS: abaixo disso é zero digital, não sala quieta
MUDO_S = 5.0
SEM_BLOCOS_S = 3.0     # sem nenhum bloco por esse tempo = aparelho sumiu
REABRIR_S = 3.0

AVISO_PRIVACIDADE = (
    "O microfone está entregando silêncio absoluto. No Windows, a causa mais "
    "comum é a privacidade: abra as Configurações do Windows › Privacidade e segurança › "
    "Microfone e ligue \"Acesso ao microfone\" e \"Permitir que aplicativos da "
    "área de trabalho acessem o microfone\". Confira também se o microfone não "
    "está no mudo (tecla ou botão do próprio aparelho) e se é o microfone certo."
)

# Nomes de "aparelhos" que não são microfones de verdade (atalhos do Windows)
_VIRTUAIS = ("microsoft sound mapper", "mapeador de som da microsoft",
             "primary sound capture", "driver de captura de som primário",
             "driver primário de captura de som")
_ORDEM_APIS = ("Windows WASAPI", "MME", "Windows DirectSound", "Windows WDM-KS")


class MicrofoneIndisponivel(RuntimeError):
    """Não há microfone, ou nenhum pôde ser aberto."""


class MicrofoneNaoEncontrado(MicrofoneIndisponivel):
    """O microfone escolhido (pelo nome) não está mais neste computador."""


SEM_MICROFONE = ("Nenhum microfone foi encontrado. Ligue o microfone (ou o fone com "
                 "microfone) e clique em Testar de novo. Se ele estiver ligado, confira "
                 "em Configurações do Windows › Sistema › Som › Entrada.")


@dataclass(frozen=True)
class Entrada:
    indice: int
    nome: str
    padrao: bool
    taxa: int
    api: str = ""
    canais: int = 1


def _sounddevice():
    try:
        import sounddevice as sd
    except OSError as erro:  # PortAudio ausente (só fora do Windows)
        raise MicrofoneIndisponivel(
            f"A biblioteca de áudio (PortAudio) não foi encontrada: {erro}") from erro
    except ImportError as erro:
        raise MicrofoneIndisponivel(
            "O componente de captura de som (sounddevice) não está instalado. "
            f"{sistema.REINSTALAR}") from erro
    return sd


def _nome_virtual(nome: str) -> bool:
    n = nome.lower()
    return any(v in n for v in _VIRTUAIS)


def listar_entradas() -> list[Entrada]:
    """Microfones disponíveis, cada um uma vez só, o padrão do Windows primeiro."""
    try:
        sd = _sounddevice()
        apis = sd.query_hostapis()
        aparelhos = sd.query_devices()
    except MicrofoneIndisponivel:
        return []
    except Exception as erro:  # PortAudio sem aparelho nenhum, driver quebrado...
        log.warning("não consegui listar os microfones: %s", erro)
        return []

    por_api: dict[int, list[dict]] = {}
    for d in aparelhos:
        if int(d.get("max_input_channels", 0)) > 0 and not _nome_virtual(d.get("name", "")):
            por_api.setdefault(int(d["hostapi"]), []).append(d)
    if not por_api:
        return []

    nomes_apis = {i: a.get("name", "") for i, a in enumerate(apis)}
    escolhida = None
    for preferida in _ORDEM_APIS:
        for i, nome in nomes_apis.items():
            if nome == preferida and por_api.get(i):
                escolhida = i
                break
        if escolhida is not None:
            break
    if escolhida is None:  # Linux/macOS (ou API desconhecida): a primeira com entrada
        escolhida = min(por_api)

    padrao_api = apis[escolhida].get("default_input_device", -1)
    entradas: list[Entrada] = []
    vistos: set[str] = set()
    for d in por_api[escolhida]:
        nome = str(d["name"]).strip()
        if nome.lower() in vistos:
            continue
        vistos.add(nome.lower())
        entradas.append(Entrada(
            indice=int(d["index"]), nome=nome, padrao=int(d["index"]) == padrao_api,
            taxa=int(round(float(d.get("default_samplerate") or TAXA))),
            api=nomes_apis.get(escolhida, ""), canais=int(d["max_input_channels"])))
    entradas.sort(key=lambda e: (not e.padrao, e.nome.lower()))
    return entradas


def achar(dispositivo: int | str | None) -> int | None:
    """Índice do PortAudio para o microfone guardado na configuração.

    A configuração guarda o NOME, não o número: o número muda quando se liga
    ou desliga um aparelho USB. Nome vazio (ou não encontrado) = o padrão.
    """
    if dispositivo is None or dispositivo == "":
        return None
    if isinstance(dispositivo, int):
        return dispositivo
    texto = str(dispositivo).strip()
    if texto.isdigit():
        return int(texto)
    indice = _procurar(texto, listar_entradas())
    if indice is None:
        log.info("microfone '%s' não encontrado; usando o padrão do Windows.", texto)
    return indice


def _procurar(texto: str, entradas: list[Entrada]) -> int | None:
    alvo = texto.strip().lower()
    if not alvo:
        return None
    for e in entradas:
        if e.nome.lower() == alvo:
            return e.indice
    for e in entradas:  # o MME corta o nome em 31 letras
        n = e.nome.lower()
        if n.startswith(alvo[:31]) or alvo.startswith(n[:31]):
            return e.indice
    return None


def _mesmo_aparelho(a: str, b: str) -> bool:
    """Os dois nomes são do mesmo microfone? (O MME corta o nome em 31 letras.)"""
    a, b = a.strip().lower(), b.strip().lower()
    return bool(a and b) and (a == b or a.startswith(b[:31]) or b.startswith(a[:31]))


def conferir(dispositivo: int | str | None) -> int | str | None:
    """O microfone escolhido na tela, conferido AGORA, antes de gravar.

    Nome (o que a configuração guarda) que não está mais na lista é erro com
    a frase para o usuário - e não o padrão do Windows em silêncio, que
    gravaria a audiência por outro aparelho. Devolve o próprio nome (a
    Captura o procura de novo a cada abertura: o número muda quando um
    aparelho USB é religado no meio da audiência), o número, ou None/""
    para o padrão do Windows.
    """
    if dispositivo is None or isinstance(dispositivo, int):
        return dispositivo
    texto = str(dispositivo).strip()
    if not texto or texto.lstrip("-").isdigit():
        return int(texto) if texto else ""
    entradas = listar_entradas()
    if _procurar(texto, entradas) is not None:
        return texto
    if not entradas:
        _sounddevice()           # sem o componente de áudio, a frase é a dele
        raise MicrofoneIndisponivel(SEM_MICROFONE)
    raise MicrofoneNaoEncontrado(
        f"O microfone «{texto}» não foi encontrado. Escolha outro em Audiências ou "
        "Ajustes › Transcrição.")


def nivel(bloco: np.ndarray) -> float:
    """Nível do bloco de 0 a 1, em escala de decibéis (-60 dBFS a 0)."""
    if bloco.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(bloco, dtype=np.float64))))
    if rms <= 1e-9:
        return 0.0
    db = 20.0 * math.log10(rms)
    return max(0.0, min(1.0, (db + 60.0) / 60.0))


class Reamostrador:
    """Converte a taxa de amostragem em blocos, sem perder continuidade.

    Interpolação polifásica com núcleo sinc janelado (Hann): para cada
    amostra de saída, uma soma ponderada das vizinhas na entrada. O filtro
    passa-baixas embutido corta acima da metade da taxa de destino (senão a
    voz aguda de 48 kHz "dobraria" para dentro dos 16 kHz como chiado).
    Guarda a cauda de cada bloco para o bloco seguinte, então reamostrar em
    pedaços dá o mesmo resultado que reamostrar tudo de uma vez.
    """

    LOBULOS = 8
    LOTE = 16384   # amostras de saída por vez (memória limitada a poucos MB)

    def __init__(self, origem: int, destino: int = TAXA):
        self.origem = int(origem)
        self.destino = int(destino)
        g = gcd(self.origem, self.destino)
        self.p = self.destino // g      # fases (passo de saída)
        self.q = self.origem // g       # passo de entrada
        self.identidade = self.p == self.q
        if self.identidade:
            return
        corte = min(1.0, self.p / self.q) * 0.94
        self.meia = int(math.ceil(self.LOBULOS / corte))
        t = np.arange(2 * self.meia)
        fases = np.arange(self.p)[:, None] / self.p
        tau = fases + self.meia - 1 - t[None, :]          # distância à amostra de entrada
        janela = 0.5 * (1.0 + np.cos(np.pi * np.clip(tau / self.meia, -1, 1)))
        tabela = corte * np.sinc(corte * tau) * janela
        tabela /= tabela.sum(axis=1, keepdims=True)       # ganho 1 em sinal constante
        self._tabela = tabela.astype(np.float32)
        self._desloc = np.arange(2 * self.meia)
        # começa com zeros "antes do início" para a primeira amostra ter vizinhas
        self._buf = np.zeros(self.meia, dtype=np.float32)
        self._base = -self.meia
        self._n = 0

    def processar(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        if self.identidade:
            return x
        if x.size:
            self._buf = np.concatenate([self._buf, x])
        fim = self._base + self._buf.size
        limite = (fim - self.meia) * self.p
        n_fim = -(-limite // self.q) if limite > 0 else 0
        if n_fim <= self._n:
            return np.zeros(0, dtype=np.float32)
        y = np.empty(int(n_fim - self._n), dtype=np.float32)
        # Em lotes: as matrizes de índices e de pesos têm ~50 colunas por
        # amostra de saída. De uma vez só, 2 min de WAV a 44,1 kHz já pediam
        # 1,5 GB, e uma audiência inteira estourava a memória (MemoryError).
        for ini in range(self._n, int(n_fim), self.LOTE):
            fim = min(int(n_fim), ini + self.LOTE)
            pos = np.arange(ini, fim, dtype=np.int64) * self.q
            i0 = pos // self.p
            fase = pos % self.p
            idx = (i0 - self.meia + 1 - self._base)[:, None] + self._desloc[None, :]
            y[ini - self._n:fim - self._n] = np.einsum("ij,ij->i", self._buf[idx],
                                                       self._tabela[fase])
        self._n = int(n_fim)
        prox = (self._n * self.q) // self.p
        corte = max(0, prox - self.meia + 1 - self._base)
        if corte:
            self._buf = self._buf[corte:]
            self._base += corte
        return y

    def finalizar(self) -> np.ndarray:
        """Esvazia a cauda (completa com zeros depois do fim)."""
        if self.identidade:
            return np.zeros(0, dtype=np.float32)
        return self.processar(np.zeros(self.meia, dtype=np.float32))

    def tudo(self, x: np.ndarray) -> np.ndarray:
        """Reamostra um sinal inteiro (atalho para arquivos)."""
        if self.identidade:
            return np.asarray(x, dtype=np.float32).reshape(-1)
        esperado = int(round(np.asarray(x).size * self.destino / self.origem))
        y = np.concatenate([self.processar(x), self.finalizar()])
        return y[:esperado]


# ============================================================ base comum
class _CapturaBase:
    """Entrega blocos de 16 kHz a `ao_bloco`, o nível a `ao_nivel` e avisos a
    `ao_aviso`. Nenhum desses callbacks pode derrubar a captura."""

    tempo_real = True

    def __init__(self, ao_bloco: Callable[[np.ndarray], None],
                 ao_nivel: Callable[[float], None] | None = None,
                 ao_aviso: Callable[[str], None] | None = None):
        self.ao_bloco = ao_bloco
        self.ao_nivel = ao_nivel
        self.ao_aviso = ao_aviso
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._reamostrador: Reamostrador | None = None
        self._mudo_desde: float | None = None
        self._avisou_mudo = False
        self._falhas_bloco = 0
        self.taxa_origem = TAXA
        self.nome = ""
        self.ativa = False

    def _avisar(self, texto: str) -> None:
        log.warning("%s", texto)
        if self.ao_aviso:
            try:
                self.ao_aviso(texto)
            except Exception:  # pragma: no cover - aviso nunca derruba a captura
                log.exception("falha ao repassar aviso")

    def _conferir_mudo(self, bruto: np.ndarray, duracao: float) -> None:
        rms = float(np.sqrt(np.mean(np.square(bruto, dtype=np.float64)))) if bruto.size else 0.0
        if rms < MUDO_RMS:
            self._mudo_desde = (self._mudo_desde or 0.0) + duracao
            if self._mudo_desde >= MUDO_S and not self._avisou_mudo:
                self._avisou_mudo = True
                self._avisar(AVISO_PRIVACIDADE)
        else:
            if self._avisou_mudo:
                log.info("o microfone voltou a mandar som.")
            self._mudo_desde = 0.0
            self._avisou_mudo = False

    def _entregar(self, bruto: np.ndarray, taxa: int) -> None:
        """Mono, 16 kHz, nível, entrega. Roda na thread de entrega."""
        if bruto.ndim == 2:
            bruto = bruto.mean(axis=1, dtype=np.float32)
        bruto = np.ascontiguousarray(bruto, dtype=np.float32).reshape(-1)
        self._conferir_mudo(bruto, bruto.size / float(taxa))
        if self.ao_nivel:
            try:
                self.ao_nivel(nivel(bruto))
            except Exception:  # pragma: no cover
                log.exception("falha ao repassar o nível")
        bloco = self._reamostrador.processar(bruto) if self._reamostrador else bruto
        if bloco.size == 0:
            return
        try:
            self.ao_bloco(bloco)
            self._falhas_bloco = 0
        except Exception:
            # Quem recebe (gravação em disco, segmentador) já trata os próprios
            # erros; isto é a última rede, para a captura não morrer calada.
            self._falhas_bloco += 1
            if self._falhas_bloco in (1, 10, 100):
                log.exception("falha ao processar um bloco de áudio")

    def iniciar(self) -> None:  # pragma: no cover - sobrescrito
        raise NotImplementedError

    def parar(self) -> None:  # pragma: no cover - sobrescrito
        raise NotImplementedError


# ============================================================ microfone
class Captura(_CapturaBase):
    """Microfone de verdade. `dispositivo`: índice, nome ou None (padrão)."""

    def __init__(self, dispositivo: int | str | None,
                 ao_bloco: Callable[[np.ndarray], None],
                 ao_nivel: Callable[[float], None] | None = None,
                 ao_aviso: Callable[[str], None] | None = None):
        super().__init__(ao_bloco, ao_nivel, ao_aviso)
        self.dispositivo = dispositivo
        self._fila: queue.Queue = queue.Queue()
        self._fluxo = None
        self._trava_fluxo = threading.Lock()   # reabrir x parar, de threads diferentes
        self._ultimo_bloco = 0.0
        self._estouros = 0
        self._estouros_avisados = 0
        # O microfone pedido (nome), para avisar quando outro abre no lugar dele
        self._escolhido = ""
        self._avisou_troca = False

    # ------------------------------------------------------------ abertura
    def _candidatos(self, sd) -> list[tuple]:
        """(índice, canais, taxa, extra) a tentar, em ordem."""
        candidatos: list[tuple] = []
        try:
            aparelhos = sd.query_devices()
            apis = sd.query_hostapis()
        except Exception as erro:
            raise MicrofoneIndisponivel(f"O Windows não informou os aparelhos de som: {erro}") from erro

        def adicionar(indice: int | None) -> None:
            try:
                info = sd.query_devices(indice, "input") if indice is not None else sd.query_devices(kind="input")
            except Exception:
                return
            idx = int(info["index"]) if indice is None else int(indice)
            api = apis[int(info["hostapi"])].get("name", "")
            taxa_nativa = int(round(float(info.get("default_samplerate") or TAXA)))
            extra = None
            if api == "Windows WASAPI":
                try:
                    # Deixa o próprio Windows converter canais/taxa se preciso.
                    extra = sd.WasapiSettings(auto_convert=True)
                except Exception:
                    extra = None
            maximo = max(1, min(2, int(info.get("max_input_channels") or 1)))
            for taxa in dict.fromkeys((taxa_nativa, TAXA, 48000, 44100)):
                for canais in dict.fromkeys((1, maximo)):
                    candidatos.append((idx, canais, taxa, extra))

        indice = achar(self.dispositivo)
        self._escolhido = ""
        if indice is not None:
            try:
                self._escolhido = str(sd.query_devices(indice)["name"])
            except Exception:
                self._escolhido = str(self.dispositivo)
        elif isinstance(self.dispositivo, str) and self.dispositivo.strip():
            self._escolhido = self.dispositivo.strip()      # sumiu: vai o padrão, com aviso
        adicionar(indice)
        if indice is not None:
            # O mesmo microfone por outra API (o MME é o mais tolerante)
            try:
                nome = str(aparelhos[indice]["name"]).lower()[:31]
                for d in aparelhos:
                    if (int(d["index"]) != indice and int(d.get("max_input_channels", 0)) > 0
                            and str(d["name"]).lower()[:31] == nome):
                        adicionar(int(d["index"]))
            except Exception:
                pass
        adicionar(None)  # por último, o padrão do Windows
        return candidatos

    def _abrir(self) -> None:
        sd = _sounddevice()
        candidatos = self._candidatos(sd)
        if not candidatos:
            raise MicrofoneIndisponivel(SEM_MICROFONE)
        erros: list[str] = []
        for indice, canais, taxa, extra in candidatos:
            try:
                fluxo = sd.InputStream(
                    device=indice, channels=canais, samplerate=taxa, dtype="float32",
                    blocksize=max(1, int(taxa * BLOCO_S)), callback=self._callback,
                    extra_settings=extra)
                fluxo.start()
            except Exception as erro:
                erros.append(f"{indice}/{canais}ch/{taxa}Hz: {erro}")
                continue
            self._fluxo = fluxo
            self.taxa_origem = int(taxa)
            self._reamostrador = Reamostrador(int(taxa), TAXA) if int(taxa) != TAXA else None
            try:
                self.nome = str(sd.query_devices(indice)["name"])
            except Exception:
                self.nome = str(indice)
            self._ultimo_bloco = time.monotonic()
            log.info("microfone aberto: %s (%d Hz, %d canal/canais)", self.nome, taxa, canais)
            escolhido = self._escolhido
            if escolhido and not _mesmo_aparelho(escolhido, self.nome) \
                    and not self._avisou_troca:
                # Nunca o padrão em silêncio: o escolhido não abriu (ocupado,
                # desligado), e a audiência segue gravando por outro aparelho.
                self._avisou_troca = True
                self._avisar(f"O microfone «{escolhido}» não abriu (desligado, ou em uso por "
                             f"outro programa); a gravação segue pelo «{self.nome}». Confira o "
                             "microfone em Audiências.")
            return
        log.warning("nenhuma configuração de microfone abriu: %s", "; ".join(erros[:6]))
        raise MicrofoneIndisponivel(
            "Não consegui abrir o microfone. Outro programa (Teams, Zoom, gravador "
            "da sala) pode estar usando-o com exclusividade, ou ele foi desconectado. "
            "Feche o outro programa, confira o cabo e tente de novo. "
            f"Detalhe técnico: {erros[0] if erros else 'sem detalhe'}")

    def _fechar_fluxo(self) -> None:
        fluxo, self._fluxo = self._fluxo, None
        if fluxo is None:
            return
        try:
            fluxo.stop()
        except Exception:
            pass
        try:
            fluxo.close()
        except Exception:
            pass

    @staticmethod
    def _reiniciar_portaudio() -> None:
        """O PortAudio só enxerga os aparelhos que existiam quando foi iniciado:
        o microfone USB religado só aparece depois de reiniciá-lo. Só é seguro
        com o nosso fluxo já fechado (é o caso aqui)."""
        try:
            sd = _sounddevice()
            sd._terminate()
            sd._initialize()
        except Exception as erro:
            log.debug("não consegui reiniciar o PortAudio: %s", erro)

    def _callback(self, indata, frames, tempo, status) -> None:
        if status and getattr(status, "input_overflow", False):
            self._estouros += 1
        self._fila.put_nowait(indata.copy())
        self._ultimo_bloco = time.monotonic()

    # --------------------------------------------------------------- ciclo
    def iniciar(self) -> None:
        if self.ativa:
            return
        self._parar.clear()
        self._abrir()
        self.ativa = True
        self._thread = threading.Thread(target=self._laco, name="captura-microfone", daemon=True)
        self._thread.start()

    def _laco(self) -> None:
        proxima_tentativa = 0.0
        avisou_queda = False
        while not self._parar.is_set():
            try:
                bruto = self._fila.get(timeout=0.5)
            except queue.Empty:
                agora = time.monotonic()
                if (agora - self._ultimo_bloco >= SEM_BLOCOS_S and agora >= proxima_tentativa
                        and not self._parar.is_set()):
                    if not avisou_queda:
                        avisou_queda = True
                        self._avisar("O microfone parou de responder (foi desconectado?). "
                                     "Tentando reabrir...")
                    proxima_tentativa = agora + REABRIR_S
                    with self._trava_fluxo:
                        if self._parar.is_set():
                            break
                        self._fechar_fluxo()
                        self._reiniciar_portaudio()
                        try:
                            self._abrir()
                            avisou_queda = False
                            self._avisar(f"Microfone reaberto: {self.nome}. A gravação continua.")
                        except MicrofoneIndisponivel:
                            pass
                continue
            avisou_queda = False
            self._entregar(bruto, self.taxa_origem)
            n = self._estouros
            if n != self._estouros_avisados and (n in (1, 10, 100) or n % 1000 == 0):
                self._estouros_avisados = n
                log.warning("o computador não deu conta de ler o microfone a tempo "
                            "(%d vez(es)); pode haver pequenos cortes.", n)

    def _esvaziar(self) -> None:
        while True:
            try:
                bruto = self._fila.get_nowait()
            except queue.Empty:
                break
            self._entregar(bruto, self.taxa_origem)

    def parar(self) -> None:
        """Para a captura. O que já chegou do microfone ainda é entregue."""
        if not self.ativa:
            return
        self._parar.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        with self._trava_fluxo:
            self._fechar_fluxo()
        self._esvaziar()
        self.ativa = False


# ============================================================== arquivo
class CapturaDeArquivo(_CapturaBase):
    """Toca um arquivo de áudio como se fosse o microfone (testes e CI).

    `tempo_real=False` entrega os blocos o mais rápido possível (o CI do
    Windows prova a transcrição de ponta a ponta sem esperar o áudio inteiro).
    `ao_avancar(segundos)` é chamado antes de cada bloco, com a posição no
    arquivo - os testes usam para trocar o falante em instantes exatos.
    """

    def __init__(self, caminho: str | Path,
                 ao_bloco: Callable[[np.ndarray], None],
                 ao_nivel: Callable[[float], None] | None = None,
                 tempo_real: bool = True,
                 ao_aviso: Callable[[str], None] | None = None,
                 ao_avancar: Callable[[float], None] | None = None):
        super().__init__(ao_bloco, ao_nivel, ao_aviso)
        self.caminho = Path(caminho)
        self.tempo_real = bool(tempo_real)
        self.ao_avancar = ao_avancar
        self.terminou = threading.Event()
        self.duracao = 0.0
        self.erro: BaseException | None = None

    def iniciar(self) -> None:
        if self.ativa:
            return
        if not self.caminho.exists():
            raise MicrofoneIndisponivel(f"Arquivo de áudio não encontrado: {self.caminho}")
        from .arquivo import decodificar  # import tardio: arquivo não importa microfone

        try:
            audio = decodificar(self.caminho, TAXA)
        except Exception as erro:
            raise MicrofoneIndisponivel(f"Não consegui ler o áudio de {self.caminho.name}: {erro}") from erro
        self.duracao = audio.size / TAXA
        self.nome = self.caminho.name
        self._parar.clear()
        self.terminou.clear()
        self.ativa = True
        self._thread = threading.Thread(target=self._laco, args=(audio,),
                                        name="captura-arquivo", daemon=True)
        self._thread.start()

    def _laco(self, audio: np.ndarray) -> None:
        passo = int(TAXA * BLOCO_S)
        t0 = time.monotonic()
        try:
            for ini in range(0, audio.size, passo):
                if self._parar.is_set():
                    break
                if self.ao_avancar:
                    try:
                        self.ao_avancar(ini / TAXA)
                    except Exception:
                        log.exception("falha no ao_avancar")
                self._entregar(audio[ini:ini + passo], TAXA)
                if self.tempo_real:
                    espera = t0 + (ini + passo) / TAXA - time.monotonic()
                    if espera > 0:
                        self._parar.wait(espera)
            if self.ao_avancar and not self._parar.is_set():
                try:
                    self.ao_avancar(audio.size / TAXA)
                except Exception:
                    log.exception("falha no ao_avancar")
        except BaseException as erro:  # pragma: no cover - guardado para o teste ver
            self.erro = erro
            log.exception("falha ao tocar o arquivo de áudio")
        finally:
            self.terminou.set()

    def esperar(self, timeout: float | None = None) -> bool:
        """Espera o arquivo acabar de tocar."""
        return self.terminou.wait(timeout)

    def parar(self) -> None:
        if not self.ativa:
            return
        self._parar.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        self.ativa = False
