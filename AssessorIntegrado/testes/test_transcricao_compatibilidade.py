"""As chamadas que fazemos às bibliotecas de verdade batem com as versões
instaladas? (O modelo Whisper não é baixado nos testes; aqui se confere a
"forma" das chamadas, para uma atualização de versão não quebrar calada.)"""

from __future__ import annotations

import dataclasses
import importlib.util
import inspect
import unittest

import numpy as np

from app.transcricao import modelos
from app.transcricao.ao_vivo import PARAMETROS_AO_VIVO
from app.transcricao.arquivo import transcrever_arquivo
from testes.apoio_transcricao import (NUMERO, ModeloDuble, PastaTemporaria, gravar_wav,
                                     roteiro_audiencia)


def presente(nome: str) -> bool:
    try:
        return importlib.util.find_spec(nome) is not None
    except (ImportError, ValueError):
        return False


@unittest.skipUnless(presente("faster_whisper"), "faster-whisper não instalado")
class TestFasterWhisper(unittest.TestCase):
    def test_chamada_ao_vivo_e_aceita(self):
        from faster_whisper import WhisperModel

        assinatura = inspect.signature(WhisperModel.transcribe)
        assinatura.bind(object(), np.zeros(16000, dtype=np.float32), initial_prompt="contexto",
                        **PARAMETROS_AO_VIVO)

    def test_chamada_da_revisao_e_aceita(self):
        from faster_whisper import WhisperModel

        tmp = PastaTemporaria(separar_falantes="true")
        try:
            wav = gravar_wav(tmp.raiz / f"{NUMERO}.wav", roteiro_audiencia())
            duble = ModeloDuble()
            transcrever_arquivo(wav, None, tmp.config(), motor_fabrica=lambda: duble,
                                diarizador=lambda a, n, progresso=None, cancelado=None: [])
            kw = duble.chamadas[0]
        finally:
            tmp.apagar()
        self.assertTrue(kw["word_timestamps"])
        inspect.signature(WhisperModel.transcribe).bind(
            object(), np.zeros(16000, dtype=np.float32), **kw)

    def test_criacao_do_modelo_e_aceita(self):
        from faster_whisper import WhisperModel

        inspect.signature(WhisperModel.__init__).bind(
            object(), "C:/AssessorIntegrado/runtime/modelos/whisper-small", device="cpu",
            compute_type="int8", cpu_threads=2)

    def test_campos_dos_segmentos(self):
        from faster_whisper.transcribe import Segment, Word

        campos = {f.name for f in dataclasses.fields(Segment)}
        self.assertTrue({"start", "end", "text", "no_speech_prob", "avg_logprob",
                         "compression_ratio", "words"} <= campos)
        self.assertTrue({"start", "end", "word"} <= {f.name for f in dataclasses.fields(Word)})

    def test_vad_embutido_roda_neste_computador(self):
        # o vad_filter=True usa o Silero (onnxruntime) que vem dentro do pacote
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        trechos = get_speech_timestamps(roteiro_audiencia()[:16000 * 3],
                                        VadOptions(min_silence_duration_ms=700, speech_pad_ms=200))
        self.assertIsInstance(trechos, list)


@unittest.skipUnless(presente("huggingface_hub"), "huggingface_hub não instalado")
class TestHuggingFace(unittest.TestCase):
    def test_snapshot_download_aceita_pasta_local(self):
        from huggingface_hub import snapshot_download

        inspect.signature(snapshot_download).bind(
            "Systran/faster-whisper-small", local_dir="x", allow_patterns=modelos.PADROES_DOWNLOAD)


@unittest.skipUnless(presente("sounddevice"), "sounddevice não instalado")
class TestSoundDevice(unittest.TestCase):
    def test_fluxo_de_entrada_e_wasapi(self):
        try:
            import sounddevice as sd
        except OSError as erro:  # PortAudio ausente nesta máquina
            self.skipTest(str(erro))
        inspect.signature(sd.InputStream.__init__).bind(
            object(), device=None, channels=1, samplerate=48000, dtype="float32",
            blocksize=4800, callback=lambda *a: None, extra_settings=None)
        sd.WasapiSettings(auto_convert=True)
        self.assertTrue(callable(sd._terminate) and callable(sd._initialize))


if __name__ == "__main__":
    unittest.main()
