"""Transcrição simultânea da audiência, pelo microfone.

Não existia na base (lá só se transcrevia arquivo já gravado). Desenho:

    microfone -> [captura] -> bloco de 100 ms -> FLAC em disco (prova e revisão)
                                              -> [segmentador] -> trecho de fala
    trecho -> fila -> [thread de transcrição: Whisper] -> fala -> tela, diário, DOCX

  * A gravação do áudio nunca espera o modelo: se o computador ficar para
    trás, a fila cresce, o atraso aparece na tela e nada se perde. Enquanto o
    modelo carrega (ou baixa), a audiência já está sendo gravada.
  * Quem fala é marcado pelo usuário (botões F1...F8): a separação
    automática de vozes em tempo real é cara e instável na CPU; a marcação
    manual é precisa e leve. A troca de falante fecha o trecho naquele
    instante, para a fala de um não sair com o nome do outro.
  * Queda de energia: cada fala vai na hora para um diário (.jsonl, gravado
    e sincronizado com o disco), e o DOCX é regravado a cada 30 s. Na volta,
    `recuperaveis()` lista as audiências interrompidas e `recuperar()` refaz
    o documento (e conserta o cabeçalho do FLAC que ficou incompleto).
  * O nome do DOCX (o número do processo) é reservado logo no início, com um
    documento "em andamento"; nunca sobrescreve uma transcrição existente:
    se já houver uma, esta sai como "<número> (2).docx".
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..nucleo import cnj, energia, sistema
from . import modelos
from .documento import (Fala, MetaAudiencia, gerar_docx, magistrado_da_config,
                        unidade_da_config)
from .segmentador import TAXA, Segmentador, TrechoDeAudio

__all__ = ["SessaoAoVivo", "Fala", "MetaAudiencia", "recuperaveis", "recuperar",
           "PARAMETROS_AO_VIVO"]

log = logging.getLogger("transcricao.ao_vivo")

# Ao vivo: rápido acima de tudo (beam 2, poucas temperaturas de reserva).
PARAMETROS_AO_VIVO = dict(
    language="pt", task="transcribe", beam_size=2, vad_filter=True,
    condition_on_previous_text=False,  # true faz o modelo repetir frases em laço
    temperature=[0.0, 0.2, 0.4], no_speech_threshold=0.6,
    compression_ratio_threshold=2.4,
)
INTERVALO_SALVAR_S = 30.0
ATRASO_AVISO_S = 20.0
INTERVALO_AVISO_ATRASO_S = 300.0
SINCRONIZAR_AUDIO_S = 5.0
VERSAO_DIARIO = 1

_ativos: set[str] = set()          # diários das sessões abertas neste processo
_trava_ativos = threading.Lock()


def _chave(p: Path) -> str:
    try:
        return str(Path(p).resolve()).lower()
    except OSError:  # pragma: no cover
        return str(p).lower()


class SessaoAoVivo:
    """Uma audiência sendo transcrita.

    `eventos(tipo, dado)` recebe, de QUALQUER thread (a janela deve só
    enfileirar): ("estado", texto), ("nivel", 0..1), ("fala", Fala),
    ("atraso", segundos), ("aviso", texto), ("erro", texto), ("salvo", Path)
    e ("fim", Path).

    `captura_fabrica(ao_bloco, ao_nivel, ao_aviso)` cria a fonte de áudio
    (padrão: o microfone da configuração); `motor_fabrica()` devolve o
    modelo (padrão: `modelos.carregar(modelo_ao_vivo)`). Ambas existem para
    os testes e para o CI (arquivo WAV no lugar do microfone).
    """

    def __init__(self, numero, cfg, eventos: Callable[[str, object], None],
                 captura_fabrica: Callable | None = None,
                 motor_fabrica: Callable[[], object] | None = None, *,
                 tipo: str = "", participantes: dict[str, str] | None = None,
                 modelo: str | None = None, dispositivo: int | str | None = None,
                 falante: str = "", motor_revisao_fabrica: Callable[[], object] | None = None,
                 diarizador: Callable | None = None):
        self.numero: cnj.Numero = numero if isinstance(numero, cnj.Numero) else cnj.ler(str(numero))
        self.cfg = cfg
        self._eventos = eventos
        self._captura_fabrica = captura_fabrica
        self._motor_fabrica = motor_fabrica
        self._motor_revisao_fabrica = motor_revisao_fabrica
        self._diarizador = diarizador
        self.modelo = modelos.nome_canonico(
            modelo or cfg.texto("transcricao", "modelo_ao_vivo") or "small")
        self.dispositivo = dispositivo if dispositivo is not None else cfg.texto("transcricao", "dispositivo")
        self.falante = falante or ""
        self.marcar_tempo = cfg.flag("transcricao", "marcar_tempo")
        self.contexto = cfg.texto("transcricao", "contexto")
        self.meta = MetaAudiencia(
            numero=self.numero.formatado, tipo=tipo, participantes=dict(participantes or {}),
            unidade=unidade_da_config(cfg), magistrado=magistrado_da_config(cfg),
            modelo=self.modelo, origem="ao vivo")

        self.falas: list[Fala] = []
        self.caminho_docx: Path | None = None
        self.caminho_audio: Path | None = None
        self.caminho_diario: Path | None = None
        self.ultimo_docx: Path | None = None
        self.captura = None
        self.estado = "parada"   # parada, gravando, pausada, encerrando, encerrada
        self.pausada = False

        self._trava = threading.RLock()
        self._trava_encerrar = threading.Lock()
        self._fila: queue.Queue = queue.Queue()
        self._seg = Segmentador()
        self._flac = None
        self._diario = None
        self._aceitando = False
        self._trabalhador: threading.Thread | None = None
        self._cancelar = threading.Event()
        self._pausa: tuple[datetime, float] | None = None
        self._pendentes = 0
        self._nao_transcritos = 0
        self._modelo_falhou = False
        self.modelo_pronto = threading.Event()
        self._ultimo_salvo = 0.0
        self._ultimo_aviso_atraso = -1e9
        self._sincronizado_em = 0.0
        self._avisou_disco = False
        self._resultado: Path | None = None

    # ============================================================ consulta
    @property
    def tempo(self) -> float:
        """Segundos gravados (sem as pausas): o cronômetro da tela."""
        return self._seg.tempo

    @property
    def pendentes(self) -> int:
        """Trechos de fala esperando o modelo."""
        return self._pendentes

    # ============================================================= eventos
    def _emitir(self, tipo: str, dado) -> None:
        try:
            self._eventos(tipo, dado)
        except Exception:  # a tela nunca derruba a gravação
            log.exception("falha ao entregar o evento %s", tipo)

    def _ao_nivel(self, valor: float) -> None:
        self._emitir("nivel", valor)

    def _ao_aviso(self, texto: str) -> None:
        self._emitir("aviso", texto)

    # ============================================================== início
    def iniciar(self) -> None:
        """Reserva o DOCX, abre o áudio e o diário, liga a captura e o modelo."""
        with self._trava:
            if self.estado != "parada":
                raise RuntimeError("Esta sessão já foi iniciada.")
            pasta = self.cfg.pasta_transcricoes
            pasta_audio = pasta / "_audio"
            try:
                pasta_audio.mkdir(parents=True, exist_ok=True)
            except OSError as erro:
                raise RuntimeError(f"Não consegui criar a pasta das transcrições ({pasta}): "
                                   f"{erro}. Confira a pasta do acervo em Configurações.") from erro
            agora = datetime.now().replace(microsecond=0)
            self.meta.inicio = agora
            self.meta.data = agora
            self.caminho_docx = sistema.destino_livre(pasta, self.numero.nome_arquivo, ".docx")
            base = f"{self.numero.nome_arquivo} {agora:%Y-%m-%d %Hh%M}"
            self.caminho_audio = sistema.destino_livre(pasta_audio, base, ".flac")
            self.caminho_diario = self.caminho_audio.with_suffix(".jsonl")
            self.meta.gravacao = f"_audio\\{self.caminho_audio.name}"
            criados: list[Path] = []
            try:
                em_andamento = replace(self.meta, observacao=(
                    "Transcrição em andamento; este documento é atualizado automaticamente."))
                self.ultimo_docx = gerar_docx(self.caminho_docx, [], em_andamento,
                                              marcar_tempo=self.marcar_tempo)
                criados.append(self.ultimo_docx)
                self._abrir_audio()
                criados.append(self.caminho_audio)
                self._abrir_diario()
                criados.append(self.caminho_diario)
                with _trava_ativos:
                    _ativos.add(_chave(self.caminho_diario))

                fabrica = self._captura_fabrica or self._captura_padrao
                self.captura = fabrica(self._ao_bloco, self._ao_nivel, self._ao_aviso)
                self._aceitando = True
                self.captura.iniciar()
            except BaseException:
                self._aceitando = False
                self._desfazer_inicio(criados)
                raise
            self.estado = "gravando"
            self._ultimo_salvo = time.monotonic()
            self._trabalhador = threading.Thread(target=self._trabalhar, name="transcricao-ao-vivo",
                                                 daemon=True)
            self._trabalhador.start()
        log.info("audiência do processo %s: gravando (%s); documento %s",
                 self.numero.formatado, self.caminho_audio.name, self.caminho_docx.name)
        self._emitir("estado", "Gravando")

    def _captura_padrao(self, ao_bloco, ao_nivel, ao_aviso):
        from .microfone import Captura

        return Captura(self.dispositivo or None, ao_bloco, ao_nivel, ao_aviso)

    def _abrir_audio(self) -> None:
        try:
            import soundfile as sf
        except ImportError as erro:
            raise RuntimeError("O componente de gravação de áudio (soundfile) não está "
                               "instalado. Rode o INSTALAR.bat de novo.") from erro
        try:
            self._flac = sf.SoundFile(str(self.caminho_audio), "w", TAXA, 1,
                                      format="FLAC", subtype="PCM_16")
        except Exception as erro:
            raise RuntimeError(f"Não consegui criar o arquivo da gravação ({erro}). Confira o "
                               "espaço em disco e a pasta do acervo em Configurações.") from erro

    def _abrir_diario(self) -> None:
        from .. import __version__

        try:
            self._diario = open(self.caminho_diario, "a", encoding="utf-8", newline="\n")
        except OSError as erro:
            raise RuntimeError(f"Não consegui criar o diário da audiência ({erro}). Confira o "
                               "espaço em disco e a pasta do acervo em Configurações.") from erro
        cabecalho = {"tipo": "inicio", "versao": VERSAO_DIARIO, "programa": __version__,
                     "meta": self.meta.como_dict(), "docx": self.caminho_docx.name,
                     "audio": self.caminho_audio.name, "marcar_tempo": self.marcar_tempo}
        self._escrever_diario(cabecalho)

    def _escrever_diario(self, registro: dict) -> None:
        if self._diario is None:
            return
        try:
            self._diario.write(json.dumps(registro, ensure_ascii=False) + "\n")
            self._diario.flush()
            os.fsync(self._diario.fileno())  # queda de energia não leva a última fala
        except (OSError, ValueError) as erro:
            if not self._avisou_disco:
                self._avisou_disco = True
                self._emitir("aviso", f"Não consegui gravar o diário da audiência ({erro}). "
                                      "A transcrição continua na tela e no documento.")

    def _desfazer_inicio(self, criados: list[Path]) -> None:
        for recurso in ("_flac", "_diario"):
            obj = getattr(self, recurso)
            setattr(self, recurso, None)
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        if self.caminho_diario is not None:
            with _trava_ativos:
                _ativos.discard(_chave(self.caminho_diario))
        for p in criados:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass

    # ============================================================ captura
    def _ao_bloco(self, bloco) -> None:
        """Roda na thread da captura: grava em disco e corta em trechos."""
        with self._trava:
            if not self._aceitando or self.pausada:
                return
            if self._flac is not None:
                try:
                    self._flac.write(bloco)
                    if self._seg.tempo - self._sincronizado_em >= SINCRONIZAR_AUDIO_S:
                        self._sincronizado_em = self._seg.tempo
                        self._flac.flush()
                except Exception as erro:
                    if not self._avisou_disco:
                        self._avisou_disco = True
                        self._emitir("aviso", f"Não consegui gravar o áudio em disco ({erro}). "
                                              "A transcrição continua, mas sem a gravação.")
            for trecho in self._seg.alimentar(bloco):
                self._enfileirar(trecho)

    def _enfileirar(self, trecho: TrechoDeAudio) -> None:
        self._pendentes += 1
        self._fila.put(("trecho", trecho, self.falante))

    # ============================================================ comandos
    def definir_falante(self, rotulo: str) -> None:
        """Fecha o trecho em curso (com o falante anterior) e passa a rotular
        os próximos com `rotulo`."""
        rotulo = (rotulo or "").strip()
        with self._trava:
            if rotulo == self.falante:
                return
            if self._aceitando and not self.pausada:
                for trecho in self._seg.cortar_agora():
                    self._enfileirar(trecho)
            self.falante = rotulo
        log.info("falante: %s", rotulo or "(sem rótulo)")

    def pausar(self) -> None:
        with self._trava:
            if self.pausada or not self._aceitando:
                return
            for trecho in self._seg.finalizar():
                self._enfileirar(trecho)
            self.pausada = True
            self.estado = "pausada"
            self._pausa = (datetime.now(), self._seg.tempo)
            if self._flac is not None:
                try:
                    self._flac.flush()
                except Exception:
                    pass
        self._emitir("estado", "Pausado")

    def retomar(self) -> None:
        with self._trava:
            if not self.pausada:
                return
            if self._pausa is not None:
                inicio, t = self._pausa
                marca = Fala(t, t, "", f"(Gravação pausada às {inicio:%H:%M:%S} e retomada "
                                       f"às {datetime.now():%H:%M:%S}.)")
                self._fila.put(("marca", marca))
            self._pausa = None
            self.pausada = False
            self.estado = "gravando"
        self._emitir("estado", "Gravando")

    def cancelar(self) -> None:
        """Interrompe a revisão final (se estiver em andamento)."""
        self._cancelar.set()

    # ======================================================== transcrição
    def _carregar_motor(self):
        self._emitir("estado", f"Carregando o modelo {self.modelo}...")
        try:
            if self._motor_fabrica is not None:
                motor = self._motor_fabrica()
            else:
                motor = modelos.carregar(
                    self.modelo, self.cfg.inteiro("transcricao", "threads"),
                    progresso=lambda f, t: self._emitir("estado", t))
        except Exception as erro:
            self._modelo_falhou = True
            log.error("modelo %s indisponível: %s", self.modelo, erro)
            self._emitir("erro", f"{erro}\n\nA gravação do áudio continua normalmente. "
                                 "Depois da audiência, transcreva a gravação pela opção "
                                 "\"Transcrever uma gravação\".")
            return None
        self.modelo_pronto.set()
        self._emitir("estado", "Pausado" if self.pausada else "Gravando")
        return motor

    def _trabalhar(self) -> None:
        with energia.manter_acordado("transcrição de audiência"):
            motor = self._carregar_motor()
            filtro = modelos.FiltroDeAlucinacao(self.contexto)
            falhas = 0
            while True:
                item = self._fila.get()
                if item is None:
                    break
                if item[0] == "marca":
                    self._registrar(item[1])
                    continue
                _, trecho, falante = item
                with self._trava:
                    self._pendentes = max(0, self._pendentes - 1)
                if motor is None:
                    self._nao_transcritos += 1
                    continue
                try:
                    fala = self._transcrever(motor, filtro, trecho, falante)
                except Exception as erro:
                    falhas += 1
                    self._nao_transcritos += 1
                    log.exception("falha ao transcrever o trecho de %.1f s", trecho.inicio)
                    if falhas in (1, 10, 100):
                        self._emitir("aviso", f"Um trecho de fala não pôde ser transcrito ({erro}). "
                                              "A gravação continua; ele estará no áudio.")
                    continue
                try:
                    if fala is not None:
                        self._registrar(fala)
                    self._medir_atraso(trecho)
                    if time.monotonic() - self._ultimo_salvo >= INTERVALO_SALVAR_S:
                        self._salvar_parcial()
                except Exception:  # pragma: no cover - última rede: a fila não pode parar
                    log.exception("falha ao registrar uma fala")

    def _transcrever(self, motor, filtro, trecho: TrechoDeAudio, falante: str) -> Fala | None:
        segmentos, _info = motor.transcribe(trecho.amostras, initial_prompt=self.contexto or None,
                                            **PARAMETROS_AO_VIVO)
        partes: list[str] = []
        primeiro = ultimo = None
        for i, seg in enumerate(segmentos):
            texto = filtro.aceitar(seg, mesmo_trecho=i > 0)
            if not texto:
                continue
            partes.append(texto)
            if primeiro is None:
                primeiro = float(getattr(seg, "start", 0.0) or 0.0)
            ultimo = float(getattr(seg, "end", 0.0) or 0.0)
        if not partes:
            return None
        inicio = trecho.inicio + max(0.0, primeiro or 0.0)
        fim = trecho.inicio + ultimo if ultimo else trecho.fim
        fim = min(max(fim, inicio), trecho.fim)
        inicio = min(inicio, fim)
        return Fala(round(inicio, 2), round(fim, 2), falante, " ".join(partes))

    def _registrar(self, fala: Fala) -> None:
        self.falas.append(fala)
        self._escrever_diario(fala.como_dict())
        self._emitir("fala", fala)

    def _medir_atraso(self, trecho: TrechoDeAudio) -> None:
        atraso = max(0.0, self._seg.tempo - trecho.fim)
        self._emitir("atraso", atraso)
        tempo_real = getattr(self.captura, "tempo_real", True)
        agora = time.monotonic()
        if (atraso > ATRASO_AVISO_S and tempo_real and not self.pausada
                and agora - self._ultimo_aviso_atraso > INTERVALO_AVISO_ATRASO_S):
            self._ultimo_aviso_atraso = agora
            if self.modelo != "base":
                dica = ("Nada se perde (o áudio está sendo gravado e a fila será transcrita), "
                        "mas, na próxima audiência, escolha o modelo \"base\" em "
                        "Configurações > Transcrição.")
            else:
                dica = ("Nada se perde (o áudio está sendo gravado e a fila será transcrita). "
                        "Feche outros programas pesados para o computador acompanhar.")
            self._emitir("aviso", f"A transcrição está {int(atraso)} s atrás da fala: o "
                                  f"computador não está dando conta do modelo \"{self.modelo}\". "
                                  + dica)

    def _meta_atual(self, final: bool) -> MetaAudiencia:
        meta = replace(self.meta, participantes=dict(self.meta.participantes))
        meta.duracao = self._seg.tempo
        if not final:
            meta.observacao = ("Transcrição em andamento; este documento é atualizado "
                               "automaticamente.")
        return meta

    def _salvar_parcial(self) -> None:
        self._ultimo_salvo = time.monotonic()
        try:
            caminho = gerar_docx(self.caminho_docx, list(self.falas), self._meta_atual(False),
                                 marcar_tempo=self.marcar_tempo)
        except Exception as erro:
            log.warning("salvamento automático falhou: %s", erro)
            self._emitir("aviso", f"O salvamento automático do documento falhou ({erro}). "
                                  "As falas continuam guardadas no diário da audiência.")
            return
        self.ultimo_docx = caminho
        self._emitir("salvo", caminho)

    # ============================================================== fim
    def encerrar(self, refinar: bool = False) -> Path:
        """Para a captura, transcreve o que estiver na fila, grava o DOCX final
        e fecha o áudio. Devolve o caminho do DOCX (bloqueia até terminar:
        chame de uma thread de trabalho, não da janela)."""
        with self._trava_encerrar:
            if self._resultado is not None:
                return self._resultado
            if self.estado == "parada":
                raise RuntimeError("A sessão não foi iniciada.")
            self.estado = "encerrando"
            if self.captura is not None:
                try:
                    self.captura.parar()
                except Exception:
                    log.exception("falha ao parar a captura")
            with self._trava:
                if not self.pausada:
                    for trecho in self._seg.finalizar():
                        self._enfileirar(trecho)
                self._aceitando = False
                self.meta.fim = datetime.now().replace(microsecond=0)
            if self._pendentes:
                aguardando = ("" if self.modelo_pronto.is_set() or self._modelo_falhou
                              else " (esperando o modelo carregar)")
                self._emitir("estado", f"Concluindo a transcrição: {self._pendentes} "
                                       f"trecho(s) na fila{aguardando}...")
            self._fila.put(None)
            if self._trabalhador is not None:
                self._trabalhador.join()
            self._fechar_audio()

            meta = self._meta_atual(True)
            observacoes = []
            if self._nao_transcritos:
                observacoes.append(
                    f"{self._nao_transcritos} trecho(s) de fala não foram transcritos "
                    "(modelo indisponível ou falha). Estão na gravação: use \"Transcrever "
                    "uma gravação\" para obtê-los.")
            if not self.cfg.flag("transcricao", "salvar_audio"):
                meta.gravacao = "não guardada (opção desligada em Configurações)"
            meta.observacao = " ".join(observacoes)
            self.meta = meta
            try:
                final = gerar_docx(self.caminho_docx, list(self.falas), meta,
                                   marcar_tempo=self.marcar_tempo)
            except Exception as erro:
                self._emitir("erro", f"Não consegui gravar o documento final ({erro}). As falas "
                                     "estão no diário da audiência e podem ser recuperadas em "
                                     "\"Recuperar transcrição interrompida\".")
                self._fechar_diario(None)
                raise
            self.ultimo_docx = final
            self._fechar_diario(final)
            self._emitir("salvo", final)

            if refinar:
                final = self._refinar(final)
            if not self.cfg.flag("transcricao", "salvar_audio") and self.caminho_audio:
                try:
                    self.caminho_audio.unlink(missing_ok=True)
                except OSError:
                    pass
            self.estado = "encerrada"
            self._resultado = final
        log.info("audiência do processo %s encerrada: %s (%d fala(s))",
                 self.numero.formatado, final, len(self.falas))
        self._emitir("estado", "Concluído")
        self._emitir("fim", final)
        return final

    def _fechar_audio(self) -> None:
        with self._trava:
            flac, self._flac = self._flac, None
        if flac is not None:
            try:
                flac.close()
            except Exception as erro:
                log.warning("falha ao fechar a gravação: %s", erro)

    def _fechar_diario(self, final: Path | None) -> None:
        if final is not None:
            self._escrever_diario({"tipo": "fim", "fim": True, "docx": final.name,
                                   "hora": datetime.now().isoformat(timespec="seconds")})
        diario, self._diario = self._diario, None
        if diario is not None:
            try:
                diario.close()
            except Exception:
                pass
        if self.caminho_diario is not None:
            # sem o registro de fim, o diário fica recuperável já nesta execução
            with _trava_ativos:
                _ativos.discard(_chave(self.caminho_diario))

    def _refinar(self, final: Path) -> Path:
        from . import arquivo

        if not self.caminho_audio or not self.caminho_audio.exists():
            self._emitir("aviso", "A revisão precisa da gravação, que não está disponível. "
                                  "Ficou a versão ao vivo.")
            return final
        pasta_audio = self.caminho_audio.parent
        base = self.caminho_audio.stem
        destino_rev = sistema.destino_livre(pasta_audio, f"{base} - revisão", ".docx")
        meta_rev = replace(self.meta, origem="revisão", participantes=dict(self.meta.participantes),
                           observacao="")
        self._emitir("estado", "Revisando a transcrição com o modelo de revisão "
                               "(pode levar alguns minutos)...")
        try:
            revisado = arquivo.transcrever_arquivo(
                self.caminho_audio, self.numero, self.cfg,
                progresso=lambda f, t: self._emitir("estado", f"Revisão: {t}"),
                cancelado=self._cancelar.is_set, rotulos_manuais=list(self.falas),
                destino=destino_rev, meta=meta_rev,
                motor_fabrica=self._motor_revisao_fabrica, diarizador=self._diarizador)
        except arquivo.Cancelado:
            self._emitir("aviso", "Revisão cancelada: ficou a versão ao vivo.")
            return final
        except Exception as erro:
            log.exception("a revisão falhou")
            self._emitir("aviso", f"A revisão não pôde ser feita ({erro}). Ficou a versão ao vivo.")
            return final
        # A revisada assume o nome do processo; a ao vivo fica guardada em _audio.
        guardado = sistema.destino_livre(pasta_audio, f"{base} - ao vivo", ".docx")
        try:
            os.replace(final, guardado)
        except OSError:
            alternativa = sistema.destino_livre(final.parent, f"{final.stem} (revisada)", ".docx")
            os.replace(revisado, alternativa)
            self._emitir("aviso", f"{final.name} está aberto em outro programa; a versão "
                                  f"revisada foi gravada como {alternativa.name}.")
            return alternativa
        os.replace(revisado, final)
        self.ultimo_docx = final
        self._emitir("salvo", final)
        return final


# ======================================================== recuperação
def _ler_diario(caminho: Path) -> list[dict]:
    registros: list[dict] = []
    with open(caminho, encoding="utf-8", errors="replace") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                registros.append(json.loads(linha))
            except json.JSONDecodeError:
                continue  # a última linha pode ter ficado pela metade na queda
    return registros


def _encerrado(registros: list[dict]) -> bool:
    return any(r.get("tipo") == "fim" or r.get("fim") is True for r in registros)


def recuperaveis(cfg) -> list[Path]:
    """Diários de audiências interrompidas (sem o registro de fim), do mais novo
    para o mais antigo. Não lista as sessões abertas agora."""
    pasta = cfg.pasta_transcricoes / "_audio"
    if not pasta.is_dir():
        return []
    with _trava_ativos:
        ativos = set(_ativos)
    achados: list[Path] = []
    for p in pasta.glob("*.jsonl"):
        if _chave(p) in ativos:
            continue
        try:
            registros = _ler_diario(p)
        except OSError:
            continue
        if registros and registros[0].get("tipo") == "inicio" and not _encerrado(registros):
            achados.append(p)
    achados.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return achados


def reparar_audio(caminho: Path) -> float:
    """Regrava o FLAC de uma gravação interrompida (cabeçalho sem a duração).

    Devolve a duração em segundos (0 se não houver áudio aproveitável).
    """
    from . import arquivo

    caminho = Path(caminho)
    if not caminho.exists():
        return 0.0
    try:
        import soundfile as sf

        with sf.SoundFile(str(caminho)) as f:
            if 0 < f.frames < 2 ** 40:
                return f.frames / f.samplerate
    except Exception:
        pass
    try:
        audio = arquivo._decodificar_av(caminho, TAXA)
    except Exception as erro:
        log.warning("a gravação %s não pôde ser lida: %s", caminho.name, erro)
        return 0.0
    try:
        import soundfile as sf

        tmp = caminho.with_name(caminho.name + ".parcial")
        sf.write(str(tmp), audio, TAXA, format="FLAC", subtype="PCM_16")
        os.replace(tmp, caminho)
    except Exception as erro:
        log.warning("não consegui regravar %s: %s", caminho.name, erro)
    return audio.size / TAXA


def recuperar(jsonl: Path) -> Path:
    """Refaz o DOCX de uma audiência interrompida a partir do diário."""
    jsonl = Path(jsonl)
    registros = _ler_diario(jsonl)
    if not registros or registros[0].get("tipo") != "inicio":
        raise ValueError(f"{jsonl.name} não é um diário de audiência do programa.")
    cabecalho = registros[0]
    falas = [Fala.de_dict(r) for r in registros[1:] if "texto" in r]
    meta = MetaAudiencia.de_dict(cabecalho.get("meta") or {})
    try:
        momento = datetime.fromtimestamp(jsonl.stat().st_mtime).replace(microsecond=0)
    except OSError:  # pragma: no cover
        momento = datetime.now().replace(microsecond=0)
    meta.fim = meta.fim or momento
    meta.observacao = ("Documento recuperado depois de uma interrupção (queda de energia ou "
                       "fechamento inesperado do programa). As falas dos últimos segundos antes "
                       "da interrupção podem faltar; confira com a gravação.")
    audio = jsonl.with_suffix(".flac")
    duracao = reparar_audio(audio) if audio.exists() else 0.0
    meta.duracao = duracao or max((f.fim for f in falas), default=0.0)

    pasta = jsonl.parent.parent
    nome = Path(str(cabecalho.get("docx") or "")).name or f"{jsonl.stem}.docx"
    destino = pasta / nome
    try:
        editado = destino.exists() and destino.stat().st_mtime > jsonl.stat().st_mtime + 5
    except OSError:  # pragma: no cover
        editado = False
    if editado:  # alguém mexeu no documento depois da queda: não sobrescreve
        destino = sistema.destino_livre(pasta, f"{Path(nome).stem} (recuperada)", ".docx")
    final = gerar_docx(destino, falas, meta, marcar_tempo=bool(cabecalho.get("marcar_tempo", True)))
    # A queda pode ter deixado a última linha pela metade, sem quebra: sem
    # esta quebra, o registro de fim grudaria nela e não seria reconhecido.
    with open(jsonl, "rb") as f:
        f.seek(0, os.SEEK_END)
        tamanho = f.tell()
        termina_em_quebra = True
        if tamanho:
            f.seek(-1, os.SEEK_END)
            termina_em_quebra = f.read(1) == b"\n"
    with open(jsonl, "a", encoding="utf-8", newline="\n") as f:
        if not termina_em_quebra:
            f.write("\n")
        f.write(json.dumps({"tipo": "fim", "fim": True, "docx": final.name, "recuperado": True,
                            "hora": datetime.now().isoformat(timespec="seconds")},
                           ensure_ascii=False) + "\n")
    log.info("transcrição recuperada: %s (%d fala(s))", final, len(falas))
    return final
