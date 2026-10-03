"""Modelos Whisper (sem rede: download e carga simulados) e o filtro de
alucinações."""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from app.transcricao import modelos
from app.transcricao.modelos import FiltroDeAlucinacao, ModeloAusente, normalizar
from testes.apoio_transcricao import PastaTemporaria, SegmentoDuble


def instalar_falso(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "model.bin").write_bytes(b"\0" * 1_100_000)
    (pasta / "config.json").write_text("{}", encoding="utf-8")
    (pasta / "tokenizer.json").write_text("{}", encoding="utf-8")


class TestCatalogo(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.patch = mock.patch.object(modelos, "PASTA", self.tmp.raiz / "modelos")
        self.patch.start()
        modelos.descarregar()

    def tearDown(self):
        modelos.descarregar()
        self.patch.stop()
        self.tmp.apagar()

    def test_nomes_e_apelidos(self):
        self.assertEqual(modelos.nome_canonico("Small"), "small")
        self.assertEqual(modelos.nome_canonico("turbo"), "large-v3-turbo")
        with self.assertRaises(ValueError) as ctx:
            modelos.nome_canonico("gigante")
        self.assertIn("small", str(ctx.exception))
        self.assertEqual(modelos.tamanho_mb("small"), 484)
        self.assertEqual(modelos.CATALOGO["large-v3-turbo"][0],
                         "mobiuslabsgmbh/faster-whisper-large-v3-turbo")

    def test_pasta_e_instalado(self):
        pasta = modelos.pasta_do_modelo("small")
        self.assertEqual(pasta.name, "whisper-small")
        self.assertFalse(modelos.instalado("small"))
        instalar_falso(pasta)
        self.assertTrue(modelos.instalado("small"))
        (pasta / "model.bin").write_bytes(b"\0" * 10)        # cópia interrompida
        self.assertFalse(modelos.instalado("small"))
        self.assertFalse(modelos.instalado("inexistente"))
        instalar_falso(pasta)
        self.assertEqual(modelos.instalados(), ["small"])
        linhas = {linha["nome"]: linha for linha in modelos.listar()}
        self.assertTrue(linhas["small"]["instalado"])
        self.assertFalse(linhas["medium"]["instalado"])

    def test_threads(self):
        self.assertEqual(modelos.threads_padrao(3), 3)
        self.assertEqual(modelos.threads_padrao(0), max(1, (os.cpu_count() or 2) // 2))

    def test_carregar_sem_modelo_e_sem_baixar_explica(self):
        with self.assertRaises(ModeloAusente) as ctx:
            modelos.carregar("small", baixar_se_faltar=False)
        self.assertIn("Configurações", str(ctx.exception))

    def test_carregar_usa_a_pasta_local_e_guarda_no_maximo_dois(self):
        criados = []

        class WhisperFalso:
            def __init__(self, caminho, **kw):
                criados.append((caminho, kw))

        falso = types.ModuleType("faster_whisper")
        falso.WhisperModel = WhisperFalso
        for nome in ("base", "small", "medium"):
            instalar_falso(modelos.pasta_do_modelo(nome))
        with mock.patch.dict(sys.modules, {"faster_whisper": falso}):
            a = modelos.carregar("small", threads=2)
            self.assertIs(modelos.carregar("small", threads=2), a)        # cache
            modelos.carregar("base", threads=2)
            modelos.carregar("medium", threads=2)                         # tira o small
            self.assertIsNot(modelos.carregar("small", threads=2), a)
        caminho, kw = criados[0]
        self.assertEqual(caminho, str(modelos.pasta_do_modelo("small")))
        self.assertEqual(kw, {"device": "cpu", "compute_type": "int8", "cpu_threads": 2})
        self.assertEqual(len(criados), 4)

    def test_modelo_corrompido_explica_o_que_fazer(self):
        class WhisperQuebrado:
            def __init__(self, caminho, **kw):
                raise RuntimeError("Unable to open file 'model.bin'")

        falso = types.ModuleType("faster_whisper")
        falso.WhisperModel = WhisperQuebrado
        instalar_falso(modelos.pasta_do_modelo("small"))
        with mock.patch.dict(sys.modules, {"faster_whisper": falso}):
            with self.assertRaises(modelos.ErroDoModelo) as ctx:
                modelos.carregar("small")
        self.assertIn("apague", str(ctx.exception))

    def test_baixar_chama_snapshot_download_na_pasta_local(self):
        chamadas = []

        def snapshot_download(repo, **kw):
            chamadas.append((repo, kw))
            instalar_falso(Path(kw["local_dir"]))
            return kw["local_dir"]

        falso = types.ModuleType("huggingface_hub")
        falso.snapshot_download = snapshot_download
        progresso = []
        with mock.patch.dict(sys.modules, {"huggingface_hub": falso}), \
                mock.patch.dict(os.environ, {}, clear=False):
            pasta = modelos.baixar("small", lambda f, t: progresso.append((f, t)))
            self.assertEqual(os.environ.get("HF_HUB_DISABLE_XET"), "1")
            self.assertEqual(os.environ.get("HF_HUB_DISABLE_SYMLINKS_WARNING"), "1")
        self.assertEqual(pasta, modelos.pasta_do_modelo("small"))
        repo, kw = chamadas[0]
        self.assertEqual(repo, "Systran/faster-whisper-small")
        self.assertEqual(kw["local_dir"], str(pasta))
        self.assertIn("model.bin", kw["allow_patterns"])
        self.assertEqual(progresso[-1][0], 1.0)
        # já instalado: não baixa de novo
        with mock.patch.dict(sys.modules, {"huggingface_hub": falso}):
            modelos.baixar("small")
        self.assertEqual(len(chamadas), 1)

    def test_falha_de_rede_vira_mensagem_para_o_usuario(self):
        def snapshot_download(repo, **kw):
            raise ConnectionError("Failed to establish a new connection: timed out")

        falso = types.ModuleType("huggingface_hub")
        falso.snapshot_download = snapshot_download
        with mock.patch.dict(sys.modules, {"huggingface_hub": falso}), \
                mock.patch.object(modelos.time, "sleep"), \
                self.assertLogs("transcricao.modelos", "WARNING"):
            with self.assertRaises(ModeloAusente) as ctx:
                modelos.baixar("base", tentativas=2)
        texto = str(ctx.exception)
        self.assertIn("huggingface.co", texto)
        self.assertIn("continua de onde parou", texto)


class TestFiltroDeAlucinacao(unittest.TestCase):
    def test_normalizar(self):
        self.assertEqual(normalizar("  Excelência, SIM!  "), "excelencia sim")
        self.assertEqual(normalizar("Amara.org"), "amara org")

    def test_aceita_fala_normal(self):
        f = FiltroDeAlucinacao()
        self.assertEqual(f.aceitar(SegmentoDuble(0, 1, "  Bom dia,   Excelência. ")),
                         "Bom dia, Excelência.")

    def test_frases_fantasma(self):
        f = FiltroDeAlucinacao()
        for texto in ("Legendas pela comunidade Amara.org", "Obrigado por assistir!",
                      "Inscreva-se no canal.", "Tchau, tchau.", "  ", "..."):
            with self.subTest(texto=texto):
                self.assertIsNone(f.aceitar(SegmentoDuble(0, 1, texto)))
        self.assertEqual(f.descartados, 6)
        # "Obrigado" sozinho é fala legítima numa audiência
        self.assertEqual(f.aceitar(SegmentoDuble(0, 1, "Obrigado, Excelência.")),
                         "Obrigado, Excelência.")

    def test_silencio_laco_e_confianca_baixa(self):
        f = FiltroDeAlucinacao()
        self.assertIsNone(f.aceitar(SegmentoDuble(0, 1, "Texto.", no_speech_prob=0.9,
                                                  avg_logprob=-1.2)))
        self.assertEqual(f.aceitar(SegmentoDuble(0, 1, "Texto.", no_speech_prob=0.9,
                                                 avg_logprob=-0.3)), "Texto.")
        self.assertIsNone(f.aceitar(SegmentoDuble(0, 1, "a a a a a a a", compression_ratio=3.1)))
        self.assertIsNone(f.aceitar(SegmentoDuble(0, 1, "Outro.", avg_logprob=-2.5)))

    def test_repeticao_consecutiva(self):
        f = FiltroDeAlucinacao()
        longa = "O depoente confirma o que foi dito."
        self.assertEqual(f.aceitar(SegmentoDuble(0, 1, longa)), longa)
        self.assertIsNone(f.aceitar(SegmentoDuble(1, 2, longa)))
        # resposta curta repetida em outro trecho é legítima ("Sim." / "Sim.")
        self.assertEqual(f.aceitar(SegmentoDuble(2, 3, "Sim.")), "Sim.")
        self.assertEqual(f.aceitar(SegmentoDuble(3, 4, "Sim.")), "Sim.")
        # ...mas não dentro do mesmo trecho
        self.assertIsNone(f.aceitar(SegmentoDuble(4, 5, "Sim."), mesmo_trecho=True))

    def test_eco_do_contexto(self):
        contexto = ("Transcrição de audiência judicial. Participam o Juiz de Direito, o "
                    "Ministério Público, advogados, partes e testemunhas.")
        f = FiltroDeAlucinacao(contexto)
        self.assertIsNone(f.aceitar(SegmentoDuble(0, 1, "Transcrição de audiência judicial.")))
        self.assertEqual(f.aceitar(SegmentoDuble(0, 1, "A audiência judicial começou.")),
                         "A audiência judicial começou.")


if __name__ == "__main__":
    unittest.main()
