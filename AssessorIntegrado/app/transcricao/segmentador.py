"""Corta o som contínuo do microfone em trechos de fala.

O Whisper não transcreve um fluxo: transcreve pedaços (até 30 s). Mandar
janelas fixas de N segundos corta palavras ao meio e manda silêncio para o
modelo (que, no silêncio, "ouve" frases que ninguém disse). Aqui o corte é
feito nas pausas naturais da fala, e cada trecho sai com a hora exata em
que começou e terminou, contada desde o início da gravação.

Detector de voz por energia, em numpy puro (rápido, sem modelo, 100%
testável):
  * o "piso" de ruído é o percentil 10 da energia dos últimos ~5 s - acompanha
    o ar-condicionado que liga e desliga sem precisar de calibração;
  * histerese: para COMEÇAR uma fala a energia precisa passar o piso por
    9 dB; para CONTINUAR, basta passar por 5 dB. Sem isso, as sílabas
    fracas no fim das frases picotariam o trecho;
  * a fala termina depois de `silencio_ms` abaixo do limiar (700 ms, o mesmo
    valor do VAD da base, afinado em audiências reais);
  * fala contínua longa demais (um depoimento sem respiro) é cortada em
    `maximo_s`, no ponto mais silencioso dos últimos 3 s - nunca no meio de
    uma palavra se houver uma pausa curta por perto;
  * `preroll_ms` de som anterior entra no começo do trecho: o detector só
    percebe a fala depois que ela começou, e a primeira consoante se perderia.

Os tempos não contam as pausas da gravação: quem chama simplesmente não
alimenta o segmentador enquanto a gravação está pausada. Assim o tempo de
cada fala coincide com a posição dela no arquivo de áudio gravado.
"""

from __future__ import annotations

import math
from collections import deque
from typing import NamedTuple

import numpy as np

TAXA = 16000
QUADRO_MS = 30


class TrechoDeAudio(NamedTuple):
    """Um trecho de fala: tempos em segundos desde o início da gravação."""

    inicio: float
    fim: float
    amostras: np.ndarray

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio


def energia_db(quadro: np.ndarray) -> float:
    """Energia média do quadro em dBFS (0 dB = escala cheia)."""
    if quadro.size == 0:
        return -120.0
    potencia = float(np.mean(np.square(quadro, dtype=np.float64)))
    return 10.0 * math.log10(potencia + 1e-12)


class Segmentador:
    """Recebe blocos de áudio (16 kHz, mono, float32) e devolve trechos de fala.

    Uso: `alimentar(bloco)` a cada bloco que chega; `cortar_agora()` quando o
    usuário troca o falante (o trecho em curso fecha naquele instante, para
    a fala de um não sair com o nome do outro); `finalizar()` no fim.
    Todos devolvem uma lista (possivelmente vazia) de `TrechoDeAudio`.
    """

    LIMIAR_INICIO_DB = 9.0      # acima do piso, para começar uma fala
    LIMIAR_FIM_DB = 5.0         # acima do piso, para continuar falando
    QUADROS_PARA_INICIAR = 2    # 60 ms seguidos: um estalo isolado não abre trecho
    VOZ_MINIMA_MS = 150         # trecho com menos voz que isso é ruído (tosse, porta)
    CAUDA_MS = 300              # silêncio mantido depois da última sílaba
    JANELA_CORTE_S = 3.0        # onde procurar a pausa no corte forçado
    HISTORICO_S = 5.0           # janela do piso de ruído
    PISO_INICIAL_DB = -50.0     # piso enquanto não há 1 s de histórico
    MINIMO_ABSOLUTO_DB = -65.0  # abaixo disso nada é fala (silêncio digital)

    def __init__(self, taxa: int = TAXA, silencio_ms: int = 700, minimo_ms: int = 600,
                 maximo_s: float = 20, preroll_ms: int = 300):
        self.taxa = int(taxa)
        self.tam_quadro = max(1, self.taxa * QUADRO_MS // 1000)
        self._q_silencio = max(1, math.ceil(silencio_ms / QUADRO_MS))
        self._q_minimo = max(1, math.ceil(minimo_ms / QUADRO_MS))
        self._q_maximo = max(10, int(maximo_s * 1000 / QUADRO_MS))
        self._q_preroll = max(0, round(preroll_ms / QUADRO_MS))
        self._q_cauda = max(0, round(self.CAUDA_MS / QUADRO_MS))
        self._q_voz_minima = max(1, math.ceil(self.VOZ_MINIMA_MS / QUADRO_MS))
        self._q_janela_corte = max(3, round(self.JANELA_CORTE_S * 1000 / QUADRO_MS))
        self._q_um_segundo = 1000 // QUADRO_MS

        self._historico: deque[float] = deque(
            maxlen=int(self.HISTORICO_S * 1000 / QUADRO_MS))
        # quadros recentes fora de fala: viram o "preroll" quando a fala começa
        self._pre: deque[tuple] = deque(maxlen=self._q_preroll + self.QUADROS_PARA_INICIAR)
        self._resto = np.zeros(0, dtype=np.float32)
        self._pos = 0                # amostra em que começa o próximo quadro
        self._amostras = 0           # total de amostras recebidas

        self._falando = False
        self._consecutivos = 0
        self._seg: list[tuple] = []  # (amostra_inicial, quadro, energia, tem_voz)
        self._voz = 0
        self._ultimo_voz = -1
        self._silencio = 0

    # ------------------------------------------------------------ consulta
    @property
    def tempo(self) -> float:
        """Segundos de áudio recebidos até agora (sem as pausas)."""
        return self._amostras / self.taxa

    @property
    def falando(self) -> bool:
        return self._falando

    # ------------------------------------------------------------- entrada
    def alimentar(self, bloco) -> list[TrechoDeAudio]:
        x = np.asarray(bloco, dtype=np.float32)
        if x.ndim == 2:  # (amostras, canais), como o sounddevice entrega
            x = x.mean(axis=1, dtype=np.float32)
        x = x.reshape(-1)
        if x.size == 0:
            return []
        self._amostras += x.size
        buf = np.concatenate([self._resto, x]) if self._resto.size else x
        n = buf.size // self.tam_quadro
        saida: list[TrechoDeAudio] = []
        for i in range(n):
            quadro = buf[i * self.tam_quadro:(i + 1) * self.tam_quadro]
            saida.extend(self._processar_quadro(quadro))
        self._resto = buf[n * self.tam_quadro:].copy()
        return saida

    def cortar_agora(self) -> list[TrechoDeAudio]:
        """Fecha o trecho em curso neste instante (troca de falante).

        Um pedaço curto demais para ser uma fala inteira não é emitido: quase
        sempre é o começo da fala de quem acabou de ganhar a palavra (o botão
        é apertado quando a pessoa já começou), e fica para o próximo trecho.
        """
        if not self._falando:
            self._consecutivos = 0
            return []
        if len(self._seg) < self._q_minimo or self._voz < self._q_voz_minima:
            return []
        trecho = self._montar(self._seg, self._voz)
        # Continua "em fala" com um trecho novo e vazio: se a próxima pessoa
        # já está falando, nada se perde esperando o detector reabrir.
        self._seg = []
        self._voz = 0
        self._ultimo_voz = -1
        self._silencio = 0
        return [trecho] if trecho is not None else []

    def finalizar(self) -> list[TrechoDeAudio]:
        """Fim da gravação: devolve o que estiver pendente."""
        saida: list[TrechoDeAudio] = []
        if self._resto.size:
            saida.extend(self._processar_quadro(self._resto.copy()))
            self._resto = np.zeros(0, dtype=np.float32)
        if self._falando and self._seg:
            corte = min(self._ultimo_voz + 1 + self._q_cauda, len(self._seg))
            trecho = self._montar(self._seg[:corte], self._voz)
            if trecho is not None:
                saida.append(trecho)
        self._falando = False
        self._seg = []
        self._voz = 0
        self._ultimo_voz = -1
        self._silencio = 0
        self._consecutivos = 0
        self._pre.clear()
        return saida

    # ------------------------------------------------------------- interno
    def _piso(self) -> float:
        if not self._historico:
            return self.PISO_INICIAL_DB
        p = float(np.percentile(np.fromiter(self._historico, dtype=np.float64), 10))
        if len(self._historico) < self._q_um_segundo:
            # Com pouco histórico, o percentil ainda não sabe o que é ruído:
            # se a fala começou logo no início, ele mediria a própria voz.
            return min(p, self.PISO_INICIAL_DB)
        return p

    def _processar_quadro(self, quadro: np.ndarray) -> list[TrechoDeAudio]:
        e = energia_db(quadro)
        piso = self._piso()
        inicio_amostra = self._pos
        self._pos += quadro.size
        saida: list[TrechoDeAudio] = []

        if not self._falando:
            forte = e > piso + self.LIMIAR_INICIO_DB and e > self.MINIMO_ABSOLUTO_DB
            self._pre.append((inicio_amostra, quadro, e, forte))
            self._consecutivos = self._consecutivos + 1 if forte else 0
            if self._consecutivos >= self.QUADROS_PARA_INICIAR:
                self._seg = list(self._pre)
                self._pre.clear()
                self._falando = True
                self._voz = sum(1 for item in self._seg if item[3])
                self._ultimo_voz = len(self._seg) - 1
                self._silencio = 0
                self._consecutivos = 0
        else:
            voz = e > piso + self.LIMIAR_FIM_DB and e > self.MINIMO_ABSOLUTO_DB
            self._seg.append((inicio_amostra, quadro, e, voz))
            if voz:
                self._silencio = 0
                self._voz += 1
                self._ultimo_voz = len(self._seg) - 1
            else:
                self._silencio += 1
            if self._silencio >= self._q_silencio:
                saida.extend(self._fechar_por_silencio())
            elif len(self._seg) >= self._q_maximo:
                saida.extend(self._corte_forcado())

        self._historico.append(e)
        return saida

    def _fechar_por_silencio(self) -> list[TrechoDeAudio]:
        corte = min(self._ultimo_voz + 1 + self._q_cauda, len(self._seg))
        trecho = self._montar(self._seg[:corte], self._voz)
        sobra = self._seg[corte:]
        self._falando = False
        self._seg = []
        self._voz = 0
        self._ultimo_voz = -1
        self._silencio = 0
        self._consecutivos = 0
        for item in sobra:  # silêncio que sobrou serve de preroll da próxima fala
            self._pre.append(item[:3] + (False,))
        return [trecho] if trecho is not None else []

    def _corte_forcado(self) -> list[TrechoDeAudio]:
        n = len(self._seg)
        janela = min(self._q_janela_corte, n - 1)
        ini = n - janela
        energias = np.array([item[2] for item in self._seg[ini:]], dtype=np.float64)
        # Média de 3 quadros: procura uma pausa de verdade (~90 ms), não um
        # quadro isolado mais fraco no meio de uma sílaba.
        suave = np.convolve(energias, np.ones(3) / 3.0, mode="same") if energias.size >= 3 else energias
        k = ini + int(np.argmin(suave[:-1])) if suave.size > 1 else n - 2
        k = max(0, min(k, n - 2))
        primeira = self._seg[:k + 1]
        resto = self._seg[k + 1:]
        voz_primeira = sum(1 for item in primeira if item[3])
        trecho = self._montar(primeira, max(voz_primeira, self._q_voz_minima))

        self._seg = resto
        self._voz = sum(1 for item in resto if item[3])
        ultimos = [i for i, item in enumerate(resto) if item[3]]
        self._ultimo_voz = ultimos[-1] if ultimos else -1
        self._silencio = len(resto) - (self._ultimo_voz + 1)
        return [trecho] if trecho is not None else []

    def _montar(self, itens: list[tuple], voz: int) -> TrechoDeAudio | None:
        if not itens or len(itens) < self._q_minimo or voz < self._q_voz_minima:
            return None
        amostras = np.concatenate([item[1] for item in itens]).astype(np.float32, copy=False)
        inicio = itens[0][0] / self.taxa
        fim = (itens[-1][0] + itens[-1][1].size) / self.taxa
        return TrechoDeAudio(inicio, fim, amostras)
