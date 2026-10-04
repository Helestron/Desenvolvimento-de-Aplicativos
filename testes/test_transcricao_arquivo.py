"""Transcrição de gravação inteira (revisão final): decodificação sem ffmpeg,
pré-tratamento, modelo dublê, filtro de alucinações, nome pelo processo e
rótulos das vozes (separação simulada + votação com os rótulos manuais)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest

import numpy as np

from helestron.transcricao import arquivo
from helestron.transcricao.arquivo import (AudioIlegivel, Cancelado, ProcessoNaoInformado, SemFala,
                                     decodificar, normalizar_volume, passa_alta,
                                     transcrever_arquivo)
from helestron.transcricao.documento import Fala
from testes.apoio_transcricao import (NUMERO, TAXA, ModeloDuble, PastaTemporaria, ficha,
                                     gravar_wav, ler_docx, montar)


def rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-12)


def roteiro() -> np.ndarray:
    return montar([("silencio", 0.5), ("fala", 2.0, 200),    # 0.5-2.5  "Bom dia a todos."
                   ("silencio", 1.7), ("fala", 2.0, 400),    # 4.2-6.2  "Eu vi o acidente."
                   ("silencio", 1.3), ("fala", 1.5, 700),    # 7.5-9.0  frase-fantasma
                   ("silencio", 1.5), ("fala", 1.5, 300),    # 10.5-12  "Sem perguntas..."
                   ("silencio", 1.0)])


class TestDecodificar(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()

    def tearDown(self):
        self.tmp.apagar()

    def test_wav_16k_e_wav_44k_estereo(self):
        audio = montar([("fala", 1.0, 200)])
        a = decodificar(gravar_wav(self.tmp.raiz / "a.wav", audio))
        np.testing.assert_allclose(a, audio, atol=1 / 32768 + 1e-6)
        t = np.arange(44100) / 44100
        estereo = np.stack([0.3 * np.sin(2 * np.pi * 300 * t)] * 2, axis=1).astype(np.float32)
        b = decodificar(gravar_wav(self.tmp.raiz / "b.wav", estereo, 44100))
        self.assertEqual(b.dtype, np.float32)
        self.assertAlmostEqual(b.size, TAXA, delta=2)

    def test_flac_interrompido_e_lido_pelo_pyav(self):
        destino = self.tmp.raiz / "queda.flac"
        script = textwrap.dedent(f"""
            import os, numpy as np, soundfile as sf
            f = sf.SoundFile(r"{destino}", "w", 16000, 1, format="FLAC", subtype="PCM_16")
            t = np.arange(16000) / 16000
            for i in range(5):
                f.write((0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32"))
                f.flush()
            os._exit(0)   # "queda de energia": o arquivo não é fechado
        """)
        subprocess.run([sys.executable, "-c", script], check=True, timeout=60)
        audio = decodificar(destino)
        self.assertGreater(audio.size, 4 * TAXA)   # quase tudo aproveitado
        self.assertAlmostEqual(float(np.max(np.abs(audio))), 0.2, delta=0.02)

    def test_arquivo_que_nao_e_audio(self):
        falso = self.tmp.raiz / "audiencia.mp3"
        falso.write_text("isto não é áudio", encoding="utf-8")
        with self.assertRaises(AudioIlegivel):
            decodificar(falso)
        with self.assertRaises(FileNotFoundError):
            decodificar(self.tmp.raiz / "nao-existe.wav")


class TestPreTratamento(unittest.TestCase):
    def test_passa_alta_tira_ronco_e_nivel_continuo(self):
        t = np.arange(4 * TAXA) / TAXA
        voz = 0.1 * np.sin(2 * np.pi * 1000 * t)
        sujo = (voz + 0.3 + 0.2 * np.sin(2 * np.pi * 20 * t)).astype(np.float32)
        limpo = passa_alta(sujo)
        self.assertLess(abs(float(np.mean(limpo))), 0.005)
        freqs = np.fft.rfftfreq(2 * TAXA, 1 / TAXA)
        antes = np.abs(np.fft.rfft(sujo[TAXA:3 * TAXA]))
        depois = np.abs(np.fft.rfft(limpo[TAXA:3 * TAXA]))
        i20, i1000 = np.argmin(abs(freqs - 20)), np.argmin(abs(freqs - 1000))
        self.assertLess(depois[i20], antes[i20] / 10)               # ronco: -20 dB ou mais
        self.assertAlmostEqual(depois[i1000] / antes[i1000], 1.0, delta=0.01)   # voz intacta
        self.assertAlmostEqual(rms_db(limpo[TAXA:-TAXA]), rms_db(voz[TAXA:-TAXA]), delta=0.5)

    def test_passa_alta_em_blocos_e_no_lugar(self):
        x = montar([("fala", 5.0, 150), ("silencio", 1.0)]) + 0.05
        inteiro = passa_alta(x, bloco_s=1000)
        em_blocos = passa_alta(x, bloco_s=1.3)
        np.testing.assert_allclose(em_blocos, inteiro, atol=1e-5)
        copia = x.copy()
        no_lugar = passa_alta(copia, bloco_s=1.3, copiar=False)
        self.assertIs(no_lugar, copia)
        np.testing.assert_allclose(no_lugar, inteiro, atol=1e-5)

    def test_normalizar_levanta_fala_baixa_sem_estourar(self):
        baixo = montar([("silencio", 1.0), ("fala", 3.0, 200), ("silencio", 1.0)]) * 0.05
        alto = normalizar_volume(baixo)
        fala_baixa = baixo[TAXA:4 * TAXA]
        fala_alta = alto[TAXA:4 * TAXA]
        self.assertGreater(rms_db(fala_alta) - rms_db(fala_baixa), 15)
        self.assertLessEqual(float(np.max(np.abs(alto))), 1.0)
        estrondo = normalizar_volume(montar([("fala", 2.0, 200)]) * 9.0)
        self.assertLessEqual(float(np.max(np.abs(estrondo))), 1.0)
        self.assertEqual(normalizar_volume(np.zeros(0, dtype=np.float32)).size, 0)


class TestTranscreverArquivo(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.cfg = self.tmp.config()
        self.wav = gravar_wav(self.tmp.raiz / f"{NUMERO} - audiência.wav", roteiro())
        self.modelo = ModeloDuble()

    def tearDown(self):
        self.tmp.apagar()

    def transcrever(self, **kw):
        kw.setdefault("motor_fabrica", lambda: self.modelo)
        return transcrever_arquivo(kw.pop("origem", self.wav), kw.pop("numero", None), self.cfg,
                                   **kw)

    def test_numero_do_nome_do_arquivo_filtro_e_parametros(self):
        progresso = []
        caminho = self.transcrever(progresso=lambda f, t: progresso.append((f, t)))
        self.assertEqual(caminho, self.cfg.pasta_transcricoes / f"{NUMERO}.docx")
        paragrafos, tabelas, _ = ler_docx(caminho)
        corpo = paragrafos[paragrafos.index("TRANSCRIÇÃO") + 1:]
        self.assertEqual(corpo, ["[00:00:00] — Bom dia a todos.", "[00:00:04] — Eu vi o acidente.",
                                 "[00:00:10] — Sem perguntas, Excelência."])
        self.assertFalse(any("Amara" in p for p in paragrafos))     # frase-fantasma descartada
        f = ficha(tabelas)
        self.assertEqual(f["Processo nº"], NUMERO)
        self.assertEqual(f["Forma da transcrição"], "A partir de arquivo de gravação")
        self.assertEqual(f["Modelo de transcrição"], "Whisper medium (português)")
        self.assertEqual(f["Gravação"], self.wav.name)
        kw = self.modelo.chamadas[0]
        self.assertEqual(kw["beam_size"], 5)
        self.assertEqual(kw["language"], "pt")
        self.assertTrue(kw["vad_filter"])
        self.assertEqual(kw["vad_parameters"], {"min_silence_duration_ms": 700, "speech_pad_ms": 200})
        self.assertFalse(kw["condition_on_previous_text"])
        self.assertEqual(kw["temperature"], [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
        self.assertFalse(kw["word_timestamps"])
        self.assertTrue(kw["initial_prompt"].startswith("Transcrição de audiência judicial"))
        self.assertEqual(progresso[-1][0], 1.0)
        self.assertEqual([p[0] for p in progresso], sorted(p[0] for p in progresso))
        # de novo: não sobrescreve, sai "(2)"
        self.assertEqual(self.transcrever().name, f"{NUMERO} (2).docx")

    def test_numero_informado_vale_mais_que_o_nome(self):
        outro = "0001234-56.2023.8.02.0001"
        caminho = self.transcrever(numero=outro)
        self.assertEqual(caminho.name, f"{outro}.docx")

    def test_sem_numero_pede_ao_usuario(self):
        sem_numero = gravar_wav(self.tmp.raiz / "gravacao.wav", roteiro())
        with self.assertRaises(ProcessoNaoInformado):
            self.transcrever(origem=sem_numero)

    def test_separacao_simulada_com_rotulos_manuais(self):
        turnos = [(0.3, 2.7, 0), (3.8, 6.2, 1), (10.3, 12.2, 0)]
        chamadas = []

        def diarizador(audio, num, progresso=None, cancelado=None):
            chamadas.append(num)
            progresso(1.0)
            return turnos

        manuais = [Fala(0.5, 2.5, "Juiz(a)", "Bom dia a todos."),
                   Fala(4.1, 6.0, "Testemunha", "Eu vi o acidente."),
                   Fala(10.4, 12.0, "", "sem rótulo")]
        caminho = self.transcrever(separar=True, diarizador=diarizador, rotulos_manuais=manuais,
                                   num_falantes=2)
        self.assertEqual(chamadas, [2])
        self.assertTrue(self.modelo.chamadas[0]["word_timestamps"])
        paragrafos, tabelas, _ = ler_docx(caminho)
        corpo = paragrafos[paragrafos.index("TRANSCRIÇÃO") + 1:]
        # a terceira fala não foi marcada à mão, mas é a mesma voz da primeira
        self.assertEqual(corpo, ["Juiz(a) [00:00:00] — Bom dia a todos.",
                                 "Testemunha [00:00:04] — Eu vi o acidente.",
                                 "Juiz(a) [00:00:10] — Sem perguntas, Excelência."])
        self.assertNotIn("IDENTIFICAÇÃO DOS FALANTES", paragrafos)
        self.assertEqual(ficha(tabelas)["Forma da transcrição"],
                         "Revisão da gravação, depois da audiência")

    def test_separacao_simulada_sem_rotulos_gera_legenda(self):
        turnos = [(0.3, 2.7, 3), (3.8, 6.2, 1), (10.3, 12.2, 3)]
        caminho = self.transcrever(separar=True,
                                   diarizador=lambda a, n, progresso=None, cancelado=None: turnos)
        paragrafos, tabelas, _ = ler_docx(caminho)
        self.assertIn("FALANTE 1 [00:00:00] — Bom dia a todos.", paragrafos)
        self.assertIn("FALANTE 2 [00:00:04] — Eu vi o acidente.", paragrafos)
        self.assertIn("IDENTIFICAÇÃO DOS FALANTES", paragrafos)
        self.assertEqual([linha[0] for linha in tabelas[1][1:]], ["FALANTE 1", "FALANTE 2"])

    def test_sem_separacao_usa_os_rotulos_manuais_por_sobreposicao(self):
        manuais = [Fala(0.5, 2.5, "Juiz(a)", "x"), Fala(3.9, 12.0, "Testemunha", "y")]
        paragrafos, _, _ = ler_docx(self.transcrever(rotulos_manuais=manuais, separar=False))
        self.assertIn("Juiz(a) [00:00:00] — Bom dia a todos.", paragrafos)
        self.assertIn("Testemunha [00:00:10] — Sem perguntas, Excelência.", paragrafos)

    def test_falha_na_separacao_nao_impede_o_documento(self):
        def quebra(*a, **k):
            raise RuntimeError("onnxruntime: DLL load failed")

        with self.assertLogs("transcricao.arquivo", "WARNING"):
            caminho = self.transcrever(separar=True, diarizador=quebra)
        self.assertTrue(caminho.exists())

    def test_audio_sem_fala(self):
        mudo = gravar_wav(self.tmp.raiz / f"{NUMERO} mudo.wav", montar([("silencio", 3.0)]))
        with self.assertRaises(SemFala):
            self.transcrever(origem=mudo)
        self.assertFalse((self.cfg.pasta_transcricoes / f"{NUMERO}.docx").exists())

    def test_cancelar_nao_grava_nada(self):
        with self.assertRaises(Cancelado):
            self.transcrever(cancelado=lambda: True)
        self.assertFalse(self.cfg.pasta_transcricoes.exists()
                         and any(self.cfg.pasta_transcricoes.iterdir()))

    def test_modelo_escolhido_e_destino_explicito(self):
        destino = self.tmp.raiz / "saida.docx"
        caminho = self.transcrever(modelo="turbo", destino=destino)
        self.assertEqual(caminho, destino)
        self.assertEqual(ficha(ler_docx(caminho)[1])["Modelo de transcrição"],
                         "Whisper large-v3-turbo (português)")

    def test_filtro_de_arquivos_do_dialogo(self):
        self.assertIn("*.asf", arquivo.FILTRO_ARQUIVOS[0][1])
        self.assertIn("*.wav", arquivo.FILTRO_ARQUIVOS[0][1])


if __name__ == "__main__":
    unittest.main()
