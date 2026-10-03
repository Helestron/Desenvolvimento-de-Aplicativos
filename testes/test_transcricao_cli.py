"""Linha de comando: os comandos que o instalador e o CI do Windows chamam."""

from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

from helestron.transcricao import cli, falantes, modelos
from testes.apoio_transcricao import (NUMERO, NUMERO_CI, ModeloDuble, PastaTemporaria, ficha,
                                     gravar_wav, ler_docx, roteiro_audiencia)


def rodar(argv: list[str]) -> tuple[int, str]:
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(io.StringIO()):
        codigo = cli.main(argv)
    return codigo, saida.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.cfg = self.tmp.config()
        self.wav = gravar_wav(self.tmp.raiz / "fala.wav", roteiro_audiencia())
        self.modelo = ModeloDuble()
        self.patches = [
            mock.patch.object(modelos, "carregar", side_effect=lambda *a, **k: self.modelo),
            mock.patch.object(modelos, "PASTA", self.tmp.raiz / "modelos"),
            mock.patch.object(falantes, "PASTA", self.tmp.raiz / "falantes"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.apagar()

    def test_ao_vivo_com_wav_como_no_ci(self):
        codigo, saida = rodar(["transcrever", "--ao-vivo", "--processo", NUMERO_CI,
                               "--wav", str(self.wav), "--config", str(self.tmp.ini),
                               "--falante", "Juiz(a)",
                               "--trocas", "4=Promotor(a); 7,5=Testemunha"])
        self.assertEqual(codigo, 0, saida)
        docx = self.cfg.pasta_transcricoes / f"{NUMERO_CI}.docx"
        self.assertTrue(docx.exists())
        self.assertIn("dígito verificador", saida)            # avisa, mas continua
        self.assertIn("Promotor(a): Sem perguntas, Excelência.", saida)
        paragrafos, tabelas, _ = ler_docx(docx)
        self.assertIn("Juiz(a) [00:00:00] — Bom dia a todos.", paragrafos)
        self.assertIn("Testemunha [00:00:08] — Eu vi o acidente. Esta fala aconteceu durante a "
                      "pausa. Nada mais.", paragrafos)
        self.assertEqual(ficha(tabelas)["Processo nº"], NUMERO_CI)

    def test_transcrever_arquivo(self):
        codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                               "--config", str(self.tmp.ini), "--sem-falantes"])
        self.assertEqual(codigo, 0, saida)
        self.assertIn("100%", saida)
        self.assertTrue((self.cfg.pasta_transcricoes / f"{NUMERO}.docx").exists())

    def test_transcrever_arquivo_sem_numero(self):
        codigo, saida = rodar(["transcrever", str(self.wav), "--config", str(self.tmp.ini)])
        self.assertEqual(codigo, 2)
        self.assertIn("--processo", saida)

    def test_erros_de_uso(self):
        self.assertEqual(rodar([])[0], 2)
        self.assertEqual(rodar(["--help"])[0], 0)
        self.assertEqual(rodar(["inventado"])[0], 2)
        self.assertEqual(rodar(["transcrever", "--config", str(self.tmp.ini)])[0], 2)
        self.assertEqual(rodar(["transcrever", "--ao-vivo", "--config", str(self.tmp.ini)])[0], 2)
        self.assertEqual(rodar(["transcrever", "--ao-vivo", "--processo", "123"])[0], 2)
        self.assertEqual(rodar(["transcrever", "--opcao-que-nao-existe"])[0], 2)
        self.assertEqual(rodar(["transcrever", "--help"])[0], 0)
        self.assertEqual(rodar(["transcrever", "nao-existe.wav", "--processo", NUMERO,
                                "--config", str(self.tmp.ini)])[0], 1)
        codigo, saida = rodar(["transcrever", "--ao-vivo", "--processo", NUMERO,
                               "--wav", str(self.wav), "--trocas", "x=Juiz",
                               "--config", str(self.tmp.ini)])
        self.assertEqual(codigo, 2)
        self.assertIn("troca inválida", saida)

    def test_modelos(self):
        codigo, saida = rodar(["modelos", "listar"])
        self.assertEqual(codigo, 0)
        for nome in ("base", "small", "medium", "large-v3-turbo"):
            self.assertIn(nome, saida)
        self.assertIn("não instalado", saida)
        self.assertEqual(rodar(["modelos"])[0], 0)
        self.assertEqual(rodar(["modelos", "baixar", "gigante"])[0], 2)
        self.assertEqual(rodar(["modelos", "baixar"])[0], 2)
        with mock.patch.object(modelos, "baixar", side_effect=modelos.ModeloAusente("sem rede")):
            codigo, saida = rodar(["modelos", "baixar", "small"])
        self.assertEqual(codigo, 1)
        self.assertIn("sem rede", saida)

        def baixar(nome, progresso):
            progresso(0.5, "Baixando o modelo small: 242 de ~484 MB")
            progresso(1.0, "Modelo small instalado.")
            return modelos.pasta_do_modelo(nome)

        with mock.patch.object(modelos, "baixar", side_effect=baixar):
            codigo, saida = rodar(["modelos", "baixar", "small"])
        self.assertEqual(codigo, 0)
        self.assertIn("50%", saida)
        self.assertIn("pronto", saida)

    def test_falantes(self):
        codigo, saida = rodar(["falantes", "estado"])
        self.assertEqual(codigo, 1)
        self.assertIn("Separação de falantes", saida)
        chamadas = []
        with mock.patch.object(falantes, "instalar", side_effect=lambda p, pip: chamadas.append(pip)), \
                mock.patch.object(falantes, "disponivel", return_value=True):
            self.assertEqual(rodar(["falantes", "instalar", "--sem-pip"])[0], 0)
            self.assertEqual(rodar(["falantes", "instalar"])[0], 0)
        self.assertEqual(chamadas, [False, True])
        with mock.patch.object(falantes, "instalar",
                               side_effect=falantes.ComponenteAusente("sem internet")):
            codigo, saida = rodar(["falantes", "instalar"])
        self.assertEqual(codigo, 1)
        self.assertIn("sem internet", saida)

    def test_microfones_sem_aparelho(self):
        with mock.patch("helestron.transcricao.microfone.listar_entradas", return_value=[]):
            codigo, saida = rodar(["microfones"])
        self.assertEqual(codigo, 1)
        self.assertIn("Nenhum microfone", saida)

    def test_subcomandos_expostos(self):
        self.assertEqual(set(cli.SUBCOMANDOS), {"transcrever", "modelos", "falantes", "microfones"})


if __name__ == "__main__":
    unittest.main()
