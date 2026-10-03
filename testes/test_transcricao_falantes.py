"""Separação de falantes: atribuição, suavização, votação com os rótulos
manuais, instalação dos modelos (por arquivo local, sem rede) e, se os
modelos de verdade estiverem nesta máquina, a diarização de 4 vozes."""

from __future__ import annotations

import hashlib
import shutil
import unittest
from pathlib import Path
from unittest import mock

from helestron.transcricao import falantes
from helestron.transcricao.documento import Fala
from testes.apoio_transcricao import PastaTemporaria

# Arquivos reais usados na validação do componente (opcionais nesta máquina)
VALIDACAO = Path("/tmp/claude-0/-home-user-Desenvolvimento-de-Aplicativos/"
                 "e9cfeb30-f128-57b9-a412-eae6bbb2f2b7/scratchpad/sherpa")
PACOTE = VALIDACAO / "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING = VALIDACAO / "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
QUATRO_VOZES = VALIDACAO / "four.wav"


class TestAtribuir(unittest.TestCase):
    def test_numera_pela_ordem_de_aparicao(self):
        falas = [Fala(0, 2, "", "Primeira."), Fala(3, 5, "", "Segunda."), Fala(6, 8, "", "Terceira.")]
        turnos = [(0, 2.2, 5), (2.8, 5.2, 2), (5.8, 8.5, 5)]
        saida = falantes.atribuir(falas, turnos)
        self.assertEqual([f.falante for f in saida], ["FALANTE 1", "FALANTE 2", "FALANTE 1"])
        self.assertEqual([f.texto for f in saida], ["Primeira.", "Segunda.", "Terceira."])

    def test_suaviza_aba_curto_sem_efeito_cascata(self):
        falas = [Fala(0, 3, "", "A longa."), Fala(3.2, 4.0, "", "sim"),
                 Fala(4.2, 7, "", "A de novo."), Fala(7.2, 7.9, "", "B curta"),
                 Fala(8, 11, "", "C longa.")]
        turnos = [(0, 3.1, 0), (3.1, 4.1, 1), (4.1, 7.1, 0), (7.1, 7.95, 1), (7.95, 11, 2)]
        saida = falantes.atribuir(falas, turnos)
        # o "sim" de 0,8 s entre duas falas de A vira A; "B curta" fica B
        # (os vizinhos A e C não concordam); a numeração não pula números
        self.assertEqual([f.falante for f in saida],
                         ["FALANTE 1", "FALANTE 1", "FALANTE 1", "FALANTE 2", "FALANTE 3"])

    def test_divide_a_fala_na_troca_de_voz(self):
        palavras = [(0.0, 0.4, " O"), (0.4, 0.8, " senhor"), (0.8, 1.2, " viu?"),
                    (1.5, 1.9, " Vi,"), (1.9, 2.3, " sim"), (2.3, 2.7, " senhor.")]
        falas = [Fala(0.0, 2.7, "", "O senhor viu? Vi, sim senhor.", palavras)]
        turnos = [(0.0, 1.3, 0), (1.4, 2.8, 1)]
        saida = falantes.atribuir(falas, turnos)
        self.assertEqual([(f.falante, f.texto) for f in saida],
                         [("FALANTE 1", "O senhor viu?"), ("FALANTE 2", "Vi, sim senhor.")])
        self.assertEqual((saida[1].inicio, saida[1].fim), (1.5, 2.7))

    def test_palavra_solta_nao_divide(self):
        palavras = [(0.0, 0.4, " Uma"), (0.4, 0.8, " frase"), (0.8, 1.0, " só"),
                    (1.0, 1.4, " de"), (1.4, 1.8, " alguém.")]
        falas = [Fala(0.0, 1.8, "", "Uma frase só de alguém.", palavras)]
        turnos = [(0.0, 0.8, 0), (0.8, 1.0, 1), (1.0, 1.8, 0)]
        saida = falantes.atribuir(falas, turnos)
        self.assertEqual(len(saida), 1)
        self.assertEqual(saida[0].texto, "Uma frase só de alguém.")

    def test_sem_sobreposicao_usa_o_turno_mais_proximo(self):
        saida = falantes.atribuir([Fala(10, 11, "", "Longe.")], [(0, 2, 0), (12, 14, 1)])
        self.assertEqual(saida[0].falante, "FALANTE 1")
        self.assertEqual(falantes.atribuir([], [(0, 1, 0)]), [])

    def test_votacao_com_rotulos_manuais(self):
        auto = [Fala(0, 10, "FALANTE 1", "a"), Fala(10, 30, "FALANTE 2", "b"),
                Fala(30, 35, "FALANTE 1", "c"), Fala(40, 45, "FALANTE 3", "d")]
        manuais = [Fala(0, 11, "Juiz(a)", "x"), Fala(11, 29, "Testemunha", "y"),
                   Fala(29, 36, "Juiz(a)", "z"), Fala(36, 50, "", "sem rótulo")]
        self.assertEqual(falantes.votar_rotulos(auto, manuais),
                         {"FALANTE 1": "Juiz(a)", "FALANTE 2": "Testemunha"})

    def test_rotular_por_sobreposicao(self):
        falas = [Fala(0, 2, "", "a"), Fala(2.5, 4, "", "b"), Fala(9, 10, "", "c"), Fala(-1, -0.5, "", "d")]
        manuais = [Fala(0, 2.2, "Juiz(a)", "x"), Fala(2.4, 5, "Testemunha", "y")]
        saida = falantes.rotular_por_sobreposicao(falas, manuais)
        self.assertEqual([f.falante for f in saida], ["Juiz(a)", "Testemunha", "Testemunha", ""])


class TestInstalar(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.patch = mock.patch.object(falantes, "PASTA", self.tmp.raiz / "falantes")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.apagar()

    def test_sem_modelos_nao_esta_disponivel(self):
        self.assertFalse(falantes.modelos_presentes())
        self.assertFalse(falantes.disponivel())
        if falantes.biblioteca_presente():
            self.assertIn("faltam os modelos", falantes.situacao())
        else:
            self.assertIn("não instalada", falantes.situacao())

    @unittest.skipUnless(PACOTE.exists() and EMBEDDING.exists(), "modelos de validação ausentes")
    def test_instalar_baixa_confere_e_extrai(self):
        progresso = []
        with mock.patch.object(falantes, "URL_SEGMENTACAO", PACOTE.as_uri()), \
                mock.patch.object(falantes, "URL_EMBEDDING", EMBEDDING.as_uri()):
            falantes.instalar(lambda f, t: progresso.append((f, t)), pip=False)
            self.assertTrue(falantes.modelos_presentes())
            self.assertEqual(progresso[-1][0], 1.0)
            pasta = falantes.PASTA
            # só o necessário do pacote; nada de pasta temporária esquecida
            self.assertEqual(sorted(p.name for p in (pasta / falantes.SUBPASTA_SEGMENTACAO).iterdir()),
                             ["LICENSE", "README.md", "model.int8.onnx"])
            self.assertFalse(list(pasta.glob("_extraindo*")))
            self.assertFalse(list(pasta.glob("*.part")))
            self.assertFalse((pasta / PACOTE.name).exists())
            # idempotente: de novo, nada é baixado
            with mock.patch.object(falantes, "_baixar") as baixar:
                falantes.instalar(pip=False)
            baixar.assert_not_called()

    def test_download_que_nao_confere_e_descartado(self):
        origem = self.tmp.raiz / "falso.onnx"
        origem.write_bytes(b"conteudo errado")
        destino = self.tmp.raiz / "saida" / "modelo.onnx"
        with self.assertRaises(falantes.ComponenteAusente) as ctx, \
                self.assertLogs("transcricao.falantes", "WARNING"):
            falantes._baixar(origem.as_uri(), destino, "0" * 64, tentativas=1)
        self.assertIn("tente de novo", str(ctx.exception))
        self.assertFalse(destino.exists())
        self.assertFalse(destino.with_name("modelo.onnx.part").exists())

    def test_download_continua_de_onde_parou(self):
        origem = self.tmp.raiz / "origem.bin"
        dados = bytes(range(256)) * 400
        origem.write_bytes(dados)
        destino = self.tmp.raiz / "saida" / "copia.bin"
        destino.parent.mkdir(parents=True)
        # um .part velho: o servidor (file://) não aceita pedaço -> recomeça do zero
        destino.with_name("copia.bin.part").write_bytes(dados[:1000])
        visto = []
        falantes._baixar(origem.as_uri(), destino, hashlib.sha256(dados).hexdigest(),
                         lambda f, t: visto.append((f, t)))
        self.assertEqual(destino.read_bytes(), dados)
        self.assertEqual(visto[-1], (len(dados), len(dados)))

    def test_diarizar_sem_modelos_explica(self):
        import numpy as np

        with self.assertRaises(falantes.ComponenteAusente) as ctx:
            falantes.diarizar(np.zeros(16000, dtype=np.float32))
        self.assertIn("Instalar o componente", str(ctx.exception))


@unittest.skipUnless(PACOTE.exists() and EMBEDDING.exists() and QUATRO_VOZES.exists()
                     and falantes.biblioteca_presente(), "sherpa-onnx ou arquivos de validação ausentes")
class TestDiarizacaoReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = PastaTemporaria()
        cls.patch = mock.patch.object(falantes, "PASTA", cls.tmp.raiz / "falantes")
        cls.patch.start()
        falantes.PASTA.mkdir(parents=True)
        falantes._extrair_segmentacao(PACOTE, falantes.PASTA)
        shutil.copy(EMBEDDING, falantes.modelo_embedding())

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.tmp.apagar()

    def test_quatro_vozes(self):
        from helestron.transcricao.arquivo import decodificar

        audio = decodificar(QUATRO_VOZES)
        progresso = []
        turnos = falantes.diarizar(audio, 0, progresso=progresso.append)
        self.assertEqual(len({voz for _, _, voz in turnos}), 4)
        self.assertTrue(all(fim > ini for ini, fim, _ in turnos))
        self.assertEqual(turnos, sorted(turnos))
        self.assertAlmostEqual(progresso[-1], 1.0)
        # e a cadeia completa: falas -> FALANTE 1..4 na ordem de aparição
        falas = [Fala(ini, fim, "", f"trecho {i}") for i, (ini, fim, _) in enumerate(turnos)]
        rotulos = [f.falante for f in falantes.atribuir(falas, turnos)]
        self.assertEqual(rotulos[0], "FALANTE 1")
        self.assertEqual(sorted(set(rotulos)), ["FALANTE 1", "FALANTE 2", "FALANTE 3", "FALANTE 4"])

    def test_cancelar_interrompe(self):
        from helestron.transcricao.arquivo import decodificar

        audio = decodificar(QUATRO_VOZES)[:8 * 16000]
        with self.assertRaises(falantes.Cancelado):
            falantes.diarizar(audio, 2, cancelado=lambda: True)


if __name__ == "__main__":
    unittest.main()
