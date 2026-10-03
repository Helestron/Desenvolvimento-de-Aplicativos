"""Segmentador: cortes nas pausas, corte forçado, troca de falante, tempos."""

from __future__ import annotations

import unittest

import numpy as np

from app.transcricao.segmentador import Segmentador, TrechoDeAudio, energia_db
from testes.apoio_transcricao import TAXA, montar


def alimentar_tudo(seg: Segmentador, audio: np.ndarray, bloco: int = 1600) -> list[TrechoDeAudio]:
    trechos: list[TrechoDeAudio] = []
    for i in range(0, audio.size, bloco):
        trechos += seg.alimentar(audio[i:i + bloco])
    return trechos


class TestSegmentador(unittest.TestCase):
    def conferir_amostras(self, t: TrechoDeAudio) -> None:
        self.assertEqual(t.amostras.dtype, np.float32)
        self.assertEqual(t.amostras.size, round((t.fim - t.inicio) * TAXA))

    def test_corta_nas_pausas_com_tempos_certos(self):
        audio = montar([("silencio", 1.0), ("fala", 2.0, 200), ("silencio", 1.5),
                        ("fala", 3.0, 300), ("silencio", 2.0)])
        seg = Segmentador()
        trechos = alimentar_tudo(seg, audio) + seg.finalizar()
        self.assertEqual(len(trechos), 2)
        a, b = trechos
        # começo com ~300 ms de preroll; fim com ~300 ms de cauda
        self.assertAlmostEqual(a.inicio, 0.7, delta=0.1)
        self.assertAlmostEqual(a.fim, 3.3, delta=0.15)
        self.assertAlmostEqual(b.inicio, 4.2, delta=0.1)
        self.assertAlmostEqual(b.fim, 7.8, delta=0.15)
        for t in trechos:
            self.conferir_amostras(t)
        self.assertAlmostEqual(seg.tempo, audio.size / TAXA, places=6)

    def test_trecho_carrega_o_audio_da_posicao_certa(self):
        audio = montar([("silencio", 1.0), ("fala", 2.0, 200), ("silencio", 1.5)])
        seg = Segmentador()
        (t,) = alimentar_tudo(seg, audio, bloco=777) + seg.finalizar()
        ini = round(t.inicio * TAXA)
        np.testing.assert_array_equal(t.amostras, audio[ini:ini + t.amostras.size])

    def test_tamanho_do_bloco_nao_muda_o_resultado(self):
        audio = montar([("silencio", 0.8), ("fala", 1.5, 250), ("silencio", 1.0),
                        ("fala", 1.0, 350), ("silencio", 1.0)])
        resultados = []
        for bloco in (160, 1600, 4096, audio.size):
            seg = Segmentador()
            trechos = alimentar_tudo(seg, audio, bloco) + seg.finalizar()
            resultados.append([(round(t.inicio, 3), round(t.fim, 3)) for t in trechos])
        for r in resultados[1:]:
            self.assertEqual(r, resultados[0])

    def test_corte_forcado_no_ponto_mais_silencioso(self):
        # 30 s de fala contínua com uma respiração (250 ms) em 18,4 s
        audio = montar([("silencio", 1.0), ("fala", 17.4, 200), ("pausa_curta", 0.25),
                        ("fala", 12.35, 200), ("silencio", 1.5)])
        seg = Segmentador(maximo_s=20)
        trechos = alimentar_tudo(seg, audio) + seg.finalizar()
        self.assertEqual(len(trechos), 2, [(t.inicio, t.fim) for t in trechos])
        a, b = trechos
        self.assertGreaterEqual(a.fim, 18.4)
        self.assertLessEqual(a.fim, 18.7)
        self.assertLessEqual(a.duracao, 20.0 + 1e-6)
        self.assertAlmostEqual(b.inicio, a.fim, places=6)   # contínuo, nada se perde
        self.assertAlmostEqual(b.fim, 31.3, delta=0.15)
        for t in trechos:
            self.conferir_amostras(t)

    def test_corte_forcado_sem_pausa_ainda_respeita_o_maximo(self):
        audio = montar([("silencio", 1.0), ("fala", 45.0, 300), ("silencio", 1.0)])
        seg = Segmentador(maximo_s=15)
        trechos = alimentar_tudo(seg, audio) + seg.finalizar()
        self.assertGreaterEqual(len(trechos), 3)
        for anterior, proximo in zip(trechos, trechos[1:]):
            self.assertAlmostEqual(proximo.inicio, anterior.fim, places=6)
        for t in trechos:
            self.assertLessEqual(t.duracao, 15.0 + 1e-6)

    def test_cortar_agora_fecha_no_instante_da_troca(self):
        audio = montar([("silencio", 1.0), ("fala", 4.0, 200), ("silencio", 1.5)])
        seg = Segmentador()
        meio = 3 * TAXA
        trechos = alimentar_tudo(seg, audio[:meio])
        self.assertEqual(trechos, [])
        cortados = seg.cortar_agora()
        self.assertEqual(len(cortados), 1)
        self.assertAlmostEqual(cortados[0].inicio, 0.7, delta=0.1)
        self.assertAlmostEqual(cortados[0].fim, 3.0, delta=0.03)
        resto = alimentar_tudo(seg, audio[meio:]) + seg.finalizar()
        self.assertEqual(len(resto), 1)
        self.assertAlmostEqual(resto[0].inicio, cortados[0].fim, delta=0.031)
        self.assertAlmostEqual(resto[0].fim, 5.3, delta=0.15)

    def test_cortar_agora_logo_no_comeco_guarda_para_o_proximo(self):
        audio = montar([("silencio", 1.0), ("fala", 2.0, 200), ("silencio", 1.5)])
        seg = Segmentador()
        corte = int(1.15 * TAXA)
        alimentar_tudo(seg, audio[:corte])
        self.assertEqual(seg.cortar_agora(), [])  # pedaço curto: fica com o próximo falante
        resto = alimentar_tudo(seg, audio[corte:]) + seg.finalizar()
        self.assertEqual(len(resto), 1)
        self.assertAlmostEqual(resto[0].inicio, 0.7, delta=0.1)

    def test_cortar_agora_no_silencio_nao_devolve_nada(self):
        seg = Segmentador()
        alimentar_tudo(seg, montar([("silencio", 2.0)]))
        self.assertEqual(seg.cortar_agora(), [])

    def test_finalizar_devolve_a_fala_em_curso(self):
        audio = montar([("silencio", 1.0), ("fala", 2.0, 200)])
        seg = Segmentador()
        self.assertEqual(alimentar_tudo(seg, audio), [])
        (t,) = seg.finalizar()
        self.assertAlmostEqual(t.fim, 3.0, delta=0.031)
        self.conferir_amostras(t)

    def test_ruido_e_estalo_nao_viram_trecho(self):
        audio = montar([("silencio", 3.0)])
        estalo = np.zeros(int(0.06 * TAXA), dtype=np.float32)
        estalo[::7] = 0.5
        audio[TAXA:TAXA + estalo.size] += estalo
        seg = Segmentador()
        self.assertEqual(alimentar_tudo(seg, audio) + seg.finalizar(), [])

    def test_continua_depois_de_finalizar_sem_perder_o_tempo(self):
        # é o que a pausa da gravação faz: finaliza, e depois volta a alimentar
        parte1 = montar([("silencio", 1.0), ("fala", 1.5, 200), ("silencio", 0.2)])
        parte2 = montar([("silencio", 1.0), ("fala", 1.5, 300), ("silencio", 1.0)], semente=3)
        seg = Segmentador()
        a = alimentar_tudo(seg, parte1, bloco=1000) + seg.finalizar()
        b = alimentar_tudo(seg, parte2) + seg.finalizar()
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        deslocamento = parte1.size / TAXA
        self.assertAlmostEqual(b[0].inicio, deslocamento + 0.7, delta=0.1)
        self.conferir_amostras(b[0])

    def test_entrada_estereo_vira_mono(self):
        mono = montar([("silencio", 1.0), ("fala", 1.5, 200), ("silencio", 1.0)])
        estereo = np.stack([mono, mono], axis=1)
        seg = Segmentador()
        trechos = alimentar_tudo(seg, estereo) + seg.finalizar()
        self.assertEqual(len(trechos), 1)

    def test_energia_db(self):
        self.assertLess(energia_db(np.zeros(480, dtype=np.float32)), -100)
        self.assertAlmostEqual(energia_db(np.ones(480, dtype=np.float32)), 0.0, places=3)
        self.assertEqual(energia_db(np.zeros(0, dtype=np.float32)), -120.0)


if __name__ == "__main__":
    unittest.main()
