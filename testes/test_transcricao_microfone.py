"""Microfone: reamostragem, nível, lista de aparelhos (com PortAudio simulado),
microfone mudo e a captura de arquivo usada pelos testes e pelo CI."""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from helestron.transcricao import microfone
from helestron.transcricao.microfone import (AVISO_PRIVACIDADE, CapturaDeArquivo, Captura,
                                       MicrofoneIndisponivel, Reamostrador, nivel)
from testes.apoio_transcricao import TAXA, PastaTemporaria, gravar_wav, montar


def tom(freq: float, taxa: int, dur: float = 1.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(taxa * dur)) / taxa
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def freq_dominante(x: np.ndarray, taxa: int) -> float:
    espectro = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    return float(np.fft.rfftfreq(x.size, 1 / taxa)[int(np.argmax(espectro))])


class TestReamostrador(unittest.TestCase):
    def test_taxas_comuns(self):
        for origem in (48000, 44100, 32000, 22050, 8000):
            with self.subTest(origem=origem):
                x = tom(1000, origem, 2.0)
                y = Reamostrador(origem, TAXA).tudo(x)
                self.assertEqual(y.size, round(x.size * TAXA / origem))
                self.assertAlmostEqual(freq_dominante(y[1000:-1000], TAXA), 1000, delta=3)
                self.assertAlmostEqual(float(np.max(np.abs(y[2000:-2000]))), 0.5, delta=0.02)

    def test_em_blocos_igual_a_de_uma_vez(self):
        x = tom(440, 44100, 1.5) + tom(3000, 44100, 1.5, 0.1)
        inteiro = Reamostrador(44100).tudo(x)
        r = Reamostrador(44100)
        partes = [r.processar(x[i:i + 1003]) for i in range(0, x.size, 1003)] + [r.finalizar()]
        em_blocos = np.concatenate(partes)[:inteiro.size]
        np.testing.assert_allclose(em_blocos, inteiro, atol=1e-6)

    def test_corta_o_que_nao_cabe_em_16_khz(self):
        # 12 kHz a 48 kHz "dobraria" para 4 kHz sem o filtro passa-baixas
        y = Reamostrador(48000).tudo(tom(12000, 48000, 1.0))
        self.assertLess(float(np.sqrt(np.mean(y[500:-500] ** 2))), 0.01)

    def test_mesma_taxa_nao_mexe(self):
        x = tom(500, TAXA, 0.5)
        r = Reamostrador(TAXA)
        self.assertTrue(r.identidade)
        np.testing.assert_array_equal(r.processar(x), x)
        self.assertEqual(r.finalizar().size, 0)


class TestNivel(unittest.TestCase):
    def test_escala(self):
        self.assertEqual(nivel(np.zeros(1600, dtype=np.float32)), 0.0)
        self.assertEqual(nivel(np.zeros(0, dtype=np.float32)), 0.0)
        self.assertAlmostEqual(nivel(np.ones(1600, dtype=np.float32)), 1.0)
        meio = nivel(np.full(1600, 10 ** (-30 / 20), dtype=np.float32))  # -30 dBFS
        self.assertAlmostEqual(meio, 0.5, delta=0.01)


class _SoundDeviceFalso:
    """PortAudio de um Windows típico: o mesmo microfone em 3 APIs."""

    class WasapiSettings:
        def __init__(self, **kw):
            self.kw = kw

    def __init__(self, abrir_falha=False):
        self.abrir_falha = abrir_falha
        self.abertos = []
        self._apis = [
            {"name": "MME", "default_input_device": 1},
            {"name": "Windows DirectSound", "default_input_device": 4},
            {"name": "Windows WASAPI", "default_input_device": 7},
        ]
        self._aparelhos = [
            {"index": 0, "name": "Mapeador de som da Microsoft - Input", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100},
            {"index": 1, "name": "Microfone (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 2, "default_samplerate": 44100},
            {"index": 2, "name": "Microfone USB (Conferência Jab", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 44100},
            {"index": 3, "name": "Alto-falantes (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 0, "default_samplerate": 44100},
            {"index": 4, "name": "Microfone (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 44100},
            {"index": 7, "name": "Microfone (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 2, "default_samplerate": 48000},
            {"index": 8, "name": "Microfone USB (Conferência Jabra 510)", "hostapi": 2, "max_input_channels": 1, "default_samplerate": 16000},
        ]

    def query_hostapis(self, indice=None):
        return self._apis if indice is None else self._apis[indice]

    def query_devices(self, indice=None, kind=None):
        if indice is None and kind is None:
            return self._aparelhos
        if indice is None:
            indice = 7
        for d in self._aparelhos:
            if d["index"] == indice:
                return d
        raise ValueError(indice)

    def InputStream(self, **kw):
        if self.abrir_falha:
            raise RuntimeError("Error opening InputStream: Device unavailable")
        sd = self

        class Fluxo:
            def start(self_):
                sd.abertos.append(kw)

            def stop(self_):
                pass

            def close(self_):
                pass

        return Fluxo()


class TestListaDeMicrofones(unittest.TestCase):
    def test_sem_portaudio_ou_sem_aparelho_lista_vazia(self):
        # aqui (Linux de teste) não há microfone: lista vazia, sem exceção
        self.assertIsInstance(microfone.listar_entradas(), list)

    def test_sem_microfone_de_verdade_a_mensagem_e_clara(self):
        if microfone.listar_entradas():
            self.skipTest("esta máquina tem microfone")
        with self.assertRaises(MicrofoneIndisponivel) as ctx:
            Captura(None, lambda b: None).iniciar()
        texto = str(ctx.exception)
        self.assertTrue("microfone" in texto.lower() or "portaudio" in texto.lower(), texto)

    def test_prefere_wasapi_sem_duplicatas_e_padrao_primeiro(self):
        falso = _SoundDeviceFalso()
        with mock.patch.object(microfone, "_sounddevice", return_value=falso):
            entradas = microfone.listar_entradas()
            self.assertEqual([e.indice for e in entradas], [7, 8])
            self.assertTrue(entradas[0].padrao)
            self.assertEqual(entradas[0].api, "Windows WASAPI")
            self.assertEqual(entradas[0].taxa, 48000)
            self.assertEqual(microfone.achar("Microfone USB (Conferência Jabra 510)"), 8)
            self.assertEqual(microfone.achar("Microfone USB (Conferência Jab"), 8)  # nome cortado do MME
            self.assertIsNone(microfone.achar("Aparelho que não existe"))
            self.assertIsNone(microfone.achar(""))
            self.assertEqual(microfone.achar(3), 3)

    def test_conferir_o_microfone_escolhido(self):
        """O nome que não existe mais é erro com a frase para o usuário - e não
        o padrão do Windows em silêncio (achar() continua tolerante: é o que a
        Captura usa para reabrir o aparelho no meio da audiência)."""
        falso = _SoundDeviceFalso()
        with mock.patch.object(microfone, "_sounddevice", return_value=falso):
            nome = "Microfone USB (Conferência Jabra 510)"
            self.assertEqual(microfone.conferir(nome), nome)
            self.assertEqual(microfone.conferir("Microfone USB (Conferência Jab"),
                             "Microfone USB (Conferência Jab")      # nome cortado do MME
            self.assertEqual(microfone.conferir(""), "")
            self.assertEqual(microfone.conferir("  "), "")
            self.assertIsNone(microfone.conferir(None))
            self.assertEqual(microfone.conferir("3"), 3)
            self.assertEqual(microfone.conferir(8), 8)
            with self.assertRaises(microfone.MicrofoneNaoEncontrado) as ctx:
                microfone.conferir("Fone Jabra Evolve")
            self.assertEqual(str(ctx.exception),
                             "O microfone “Fone Jabra Evolve” não foi encontrado. Escolha outro "
                             "em Audiências ou Ajustes › Transcrição.")
            self.assertIsInstance(ctx.exception, MicrofoneIndisponivel)
        # sem microfone nenhum: a frase de "nenhum microfone"
        with mock.patch.object(microfone, "listar_entradas", return_value=[]), \
                mock.patch.object(microfone, "_sounddevice", return_value=falso):
            with self.assertRaises(MicrofoneIndisponivel) as ctx:
                microfone.conferir("Microfone de mesa")
            self.assertEqual(str(ctx.exception), microfone.SEM_MICROFONE)

    def test_escolhido_que_nao_abre_cai_no_padrao_com_aviso(self):
        """O microfone escolhido existe, mas não abre (ocupado): a gravação segue
        pelo padrão do Windows - e a tela é avisada, em vez de gravar por outro
        aparelho em silêncio."""
        falso = _SoundDeviceFalso()
        original = falso.InputStream

        def abre_so_o_padrao(**kw):
            if kw["device"] in (8, 2):          # o Jabra, por WASAPI e por MME
                raise RuntimeError("Error opening InputStream: Device unavailable")
            return original(**kw)

        falso.InputStream = abre_so_o_padrao
        avisos = []
        with mock.patch.object(microfone, "_sounddevice", return_value=falso), \
                self.assertLogs("transcricao.microfone", "WARNING"):
            c = Captura("Microfone USB (Conferência Jabra 510)", lambda b: None,
                        ao_aviso=avisos.append)
            c._abrir()
            self.assertEqual(falso.abertos[0]["device"], 7)
            self.assertEqual(len(avisos), 1)
            self.assertIn("“Microfone USB (Conferência Jabra 510)” não abriu", avisos[0])
            self.assertIn("“Microfone (Realtek(R) Audio)”", avisos[0])
            # o mesmo aparelho aberto por outra API (o MME corta o nome) não é troca
            self.assertTrue(microfone._mesmo_aparelho("Microfone USB (Conferência Jabra 510)",
                                                      "Microfone USB (Conferência Jab"))
            self.assertFalse(microfone._mesmo_aparelho("Microfone USB (Conferência Jabra 510)",
                                                       "Microfone (Realtek(R) Audio)"))
            # o escolhido que abre não avisa nada
            avisos.clear()
            Captura("Microfone (Realtek(R) Audio)", lambda b: None, ao_aviso=avisos.append)._abrir()
            Captura(None, lambda b: None, ao_aviso=avisos.append)._abrir()
            self.assertEqual(avisos, [])

    def test_captura_abre_na_taxa_nativa_e_reamostra(self):
        falso = _SoundDeviceFalso()
        with mock.patch.object(microfone, "_sounddevice", return_value=falso):
            c = Captura("Microfone (Realtek(R) Audio)", lambda b: None)
            c._abrir()
            self.assertEqual(falso.abertos[0]["device"], 7)
            self.assertEqual(falso.abertos[0]["samplerate"], 48000)
            self.assertEqual(falso.abertos[0]["channels"], 1)
            self.assertIsInstance(falso.abertos[0]["extra_settings"], _SoundDeviceFalso.WasapiSettings)
            self.assertEqual(c.taxa_origem, 48000)
            self.assertIsNotNone(c._reamostrador)

    def test_captura_sem_aparelho_explica(self):
        falso = _SoundDeviceFalso(abrir_falha=True)
        with mock.patch.object(microfone, "_sounddevice", return_value=falso):
            c = Captura(None, lambda b: None)
            with self.assertRaises(MicrofoneIndisponivel) as ctx, \
                    self.assertLogs("transcricao.microfone", "WARNING"):
                c.iniciar()
            self.assertIn("Não consegui abrir o microfone", str(ctx.exception))

    def test_microfone_que_some_e_reaberto(self):
        falso = _SoundDeviceFalso()
        avisos = []
        with mock.patch.object(microfone, "_sounddevice", return_value=falso), \
                mock.patch.object(microfone, "SEM_BLOCOS_S", 0.2), \
                mock.patch.object(microfone, "REABRIR_S", 0.2), \
                self.assertLogs("transcricao.microfone", "WARNING"):
            c = Captura(None, lambda b: None, ao_aviso=avisos.append)
            c.iniciar()
            try:
                limite = time.monotonic() + 5
                while len(avisos) < 2 and time.monotonic() < limite:
                    time.sleep(0.05)
            finally:
                c.parar()
        self.assertIn("parou de responder", avisos[0])
        self.assertIn("reaberto", avisos[1])
        self.assertGreaterEqual(len(falso.abertos), 2)
        self.assertFalse(c.ativa)

    def test_entrega_do_callback_ate_o_bloco_de_16khz(self):
        falso = _SoundDeviceFalso()
        recebidos = []
        niveis = []
        with mock.patch.object(microfone, "_sounddevice", return_value=falso):
            c = Captura(None, recebidos.append, niveis.append)
            c.iniciar()
            try:
                x = tom(440, 48000, 1.0, 0.3).reshape(-1, 1)
                for i in range(0, x.shape[0], 4800):  # como o PortAudio chamaria
                    c._callback(x[i:i + 4800], 4800, None, None)
            finally:
                c.parar()
        total = sum(b.size for b in recebidos)
        self.assertAlmostEqual(total, TAXA, delta=40)
        self.assertEqual(len(niveis), 10)
        self.assertTrue(all(0.5 < n < 1.0 for n in niveis))


class TestCapturaDeArquivo(unittest.TestCase):
    def setUp(self):
        self.pasta = PastaTemporaria()

    def tearDown(self):
        self.pasta.apagar()

    def test_entrega_tudo_na_ordem_e_avisa_o_avanco(self):
        audio = montar([("silencio", 0.5), ("fala", 1.0, 200), ("silencio", 0.5)])
        wav = gravar_wav(self.pasta.raiz / "a.wav", audio)
        blocos, posicoes = [], []
        c = CapturaDeArquivo(wav, blocos.append, tempo_real=False, ao_avancar=posicoes.append)
        c.iniciar()
        self.assertTrue(c.esperar(10))
        c.parar()
        recebido = np.concatenate(blocos)
        np.testing.assert_allclose(recebido, audio, atol=1 / 32768 + 1e-6)
        self.assertEqual(posicoes[0], 0.0)
        self.assertAlmostEqual(posicoes[1], 0.1)
        self.assertAlmostEqual(posicoes[-1], audio.size / TAXA)
        self.assertFalse(c.tempo_real)

    def test_reamostra_arquivo_estereo_de_44khz(self):
        t = np.arange(44100) / 44100
        estereo = np.stack([0.3 * np.sin(2 * np.pi * 300 * t)] * 2, axis=1).astype(np.float32)
        wav = gravar_wav(self.pasta.raiz / "b.wav", estereo, 44100)
        blocos = []
        c = CapturaDeArquivo(wav, blocos.append, tempo_real=False)
        c.iniciar()
        c.esperar(10)
        self.assertAlmostEqual(sum(b.size for b in blocos), TAXA, delta=2)

    def test_silencio_absoluto_avisa_da_privacidade(self):
        wav = gravar_wav(self.pasta.raiz / "mudo.wav", np.zeros(6 * TAXA, dtype=np.float32))
        avisos = []
        c = CapturaDeArquivo(wav, lambda b: None, ao_aviso=avisos.append, tempo_real=False)
        with self.assertLogs("transcricao.microfone", "WARNING"):
            c.iniciar()
            c.esperar(10)
        self.assertEqual(avisos, [AVISO_PRIVACIDADE])
        self.assertIn("Privacidade", AVISO_PRIVACIDADE)

    def test_erro_em_quem_recebe_nao_derruba_a_captura(self):
        wav = gravar_wav(self.pasta.raiz / "c.wav", montar([("fala", 1.0, 200)]))
        contagem = []

        def receber(bloco):
            contagem.append(1)
            raise ValueError("disco cheio (simulado)")

        c = CapturaDeArquivo(wav, receber, tempo_real=False)
        with self.assertLogs("transcricao.microfone", "ERROR") as registro:
            c.iniciar()
            self.assertTrue(c.esperar(10))
        self.assertEqual(len(registro.records), 2)   # 1ª e 10ª falha: não inunda o log
        self.assertEqual(len(contagem), 10)
        self.assertIsNone(c.erro)

    def test_tempo_real_respeita_o_relogio_e_para_no_meio(self):
        wav = gravar_wav(self.pasta.raiz / "d.wav", montar([("fala", 3.0, 200)]))
        blocos = []
        c = CapturaDeArquivo(wav, blocos.append, tempo_real=True)
        c.iniciar()
        threading.Event().wait(0.35)
        c.parar()
        self.assertTrue(c.terminou.is_set())
        self.assertLess(len(blocos), 15)   # longe dos 30 blocos do arquivo inteiro

    def test_arquivo_inexistente(self):
        c = CapturaDeArquivo(Path(self.pasta.raiz / "nao.wav"), lambda b: None)
        with self.assertRaises(MicrofoneIndisponivel):
            c.iniciar()


if __name__ == "__main__":
    unittest.main()
