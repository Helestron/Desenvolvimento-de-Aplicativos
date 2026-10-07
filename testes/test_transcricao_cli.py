"""Linha de comando: os comandos que o instalador e o CI do Windows chamam."""

from __future__ import annotations

import contextlib
import errno
import io
import os
import unittest
from pathlib import Path
from unittest import mock

from helestron.nucleo import caminhos, cnj, sigilo
from helestron.transcricao import cli, documento, falantes, modelos
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
            mock.patch.object(modelos, "PASTA_EMBUTIDA", self.tmp.raiz / "embutidos"),
            mock.patch.object(falantes, "PASTA", self.tmp.raiz / "falantes"),
            mock.patch.object(falantes, "PASTA_EMBUTIDA", self.tmp.raiz / "embutidos" / "falantes"),
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

    def test_segue_a_regra_de_sigilo_da_tela(self):
        """O processo que a pauta marca em segredo de justiça é transcrito como
        sigiloso também pela linha de comando, sem o --sigiloso (antes, só a
        tela consultava a pauta, e a CLI gravava no acervo); a saída diz o
        motivo."""
        from testes.test_nucleo import pauta_com_sigiloso

        pauta = self.tmp.raiz / "local" / "pauta.sqlite3"
        pauta.parent.mkdir(parents=True)
        pauta_com_sigiloso(pauta, cnj.ler(NUMERO))
        with mock.patch.object(caminhos, "ARQUIVO_PAUTA", pauta):
            self.addCleanup(sigilo.esquecer_pauta)
            codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                                   "--config", str(self.tmp.ini), "--sem-falantes"])
            self.assertEqual(codigo, 0, saida)
            self.assertIn(f"Processo em segredo de justiça ({sigilo.MOTIVO_PAUTA})", saida)
            self.assertFalse((self.cfg.pasta_transcricoes / f"{NUMERO}.docx").exists())
            self.assertTrue((self.cfg.pasta_sigilosos / "Transcricoes" / f"{NUMERO}.docx").exists())
            # ao vivo também (agora já há transcrição dele na pasta dos sigilosos)
            codigo, saida = rodar(["transcrever", "--ao-vivo", "--processo", NUMERO,
                                   "--wav", str(self.wav), "--config", str(self.tmp.ini)])
            self.assertEqual(codigo, 0, saida)
            self.assertIn(f"Processo em segredo de justiça ({sigilo.MOTIVO_PASTA})", saida)
            self.assertFalse(list(self.cfg.pasta_transcricoes.rglob(f"{NUMERO}*")))
            # e o --destino não leva a transcrição do sigiloso para o acervo
            codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                                   "--config", str(self.tmp.ini), "--sem-falantes", "--destino",
                                   str(self.cfg.pasta_acervo / "x.docx")])
            self.assertEqual(codigo, 2, saida)
            self.assertIn("não pode ser gravada no acervo", saida)
            self.assertFalse((self.cfg.pasta_acervo / "x.docx").exists())

    def test_gravacao_na_pasta_dos_sigilosos_e_sigilosa(self):
        guardada = self.cfg.pasta_sigilosos / "Lote 1" / "audiencia.wav"
        guardada.parent.mkdir(parents=True)
        guardada.write_bytes(self.wav.read_bytes())
        codigo, saida = rodar(["transcrever", str(guardada), "--processo", NUMERO,
                               "--config", str(self.tmp.ini), "--sem-falantes"])
        self.assertEqual(codigo, 0, saida)
        self.assertIn(cli.MOTIVO_GRAVACAO, saida)
        self.assertTrue((self.cfg.pasta_sigilosos / "Transcricoes" / f"{NUMERO}.docx").exists())

    def test_incidente_com_hifen_segue_o_sigilo_do_incidente(self):
        """Achado 33: --processo "...0001-01" (o nome do DOCX do incidente)
        virava o principal: a transcrição do incidente sigiloso ia para o
        acervo, com o nome do principal."""
        self.cfg.pasta_sigilosos.mkdir(parents=True)
        (self.cfg.pasta_sigilosos / f"{NUMERO}-01.pdf").write_bytes(b"%PDF")
        codigo, saida = rodar(["transcrever", str(self.wav), "--processo", f"{NUMERO}-01",
                               "--config", str(self.tmp.ini), "--sem-falantes"])
        self.assertEqual(codigo, 0, saida)
        self.assertIn(f"Processo em segredo de justiça ({sigilo.MOTIVO_PASTA})", saida)
        docx = self.cfg.pasta_sigilosos / "Transcricoes" / f"{NUMERO}-01.docx"
        self.assertTrue(docx.exists())
        self.assertIn(f"Transcrição gravada em: {docx}", saida)
        self.assertEqual(ficha(ler_docx(docx)[1])["Processo nº"], f"{NUMERO}/01")
        self.assertFalse(list(self.cfg.pasta_transcricoes.rglob("*.docx")))

    def test_destino_que_e_pasta(self):
        """Achado 36: uma pasta no --destino derrubava a CLI no fim, depois
        de transcrever tudo (IsADirectoryError no Linux; no Windows, uma
        "cópia" sem extensão ao lado da pasta)."""
        pasta = self.tmp.raiz / "Saida"
        pasta.mkdir()
        codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                               "--config", str(self.tmp.ini), "--sem-falantes",
                               "--destino", str(pasta)])
        self.assertEqual(codigo, 0, saida)
        self.assertTrue((pasta / f"{NUMERO}.docx").exists())
        # de novo: não sobrescreve a anterior
        codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                               "--config", str(self.tmp.ini), "--sem-falantes",
                               "--destino", str(pasta) + os.sep])
        self.assertEqual(codigo, 0, saida)
        self.assertTrue((pasta / f"{NUMERO} (2).docx").exists())

    def test_destino_sem_extensao_ganha_docx(self):
        codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                               "--config", str(self.tmp.ini), "--sem-falantes",
                               "--destino", str(self.tmp.raiz / "Ata.2024")])
        self.assertEqual(codigo, 0, saida)
        self.assertTrue((self.tmp.raiz / "Ata.2024.docx").exists())
        self.assertFalse((self.tmp.raiz / "Ata.2024").exists())

    def test_destino_impossivel_recusado_antes_de_transcrever(self):
        arquivo = self.tmp.raiz / "relatorio.txt"
        arquivo.write_text("x", encoding="utf-8")
        codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                               "--config", str(self.tmp.ini), "--sem-falantes",
                               "--destino", str(arquivo / "ata.docx")])
        self.assertEqual(codigo, 2, saida)
        self.assertIn("é um arquivo, não uma pasta", saida)
        # pasta sem o número para dar nome ao documento
        codigo, saida = rodar(["transcrever", str(self.wav), "--config", str(self.tmp.ini),
                               "--sem-falantes", "--destino", str(self.tmp.raiz)])
        self.assertEqual(codigo, 2, saida)
        self.assertIn("--processo", saida)
        self.assertEqual(self.modelo.chamadas, [])     # nada foi transcrito à toa

    def test_falha_ao_gravar_no_destino_nao_perde_a_transcricao(self):
        destino = self.tmp.raiz / "Externo" / "ata.docx"
        original = documento.sistema.gravar_atomico

        def disco(alvo, dados):
            if Path(alvo) == destino:
                raise OSError(errno.ENOSPC, "Não há espaço no disco", str(alvo))
            return original(alvo, dados)

        with mock.patch.object(documento.sistema, "gravar_atomico", side_effect=disco), \
                self.assertLogs("transcricao.arquivo", "WARNING"):
            codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                                   "--config", str(self.tmp.ini), "--sem-falantes",
                                   "--destino", str(destino)])
        self.assertEqual(codigo, 0, saida)
        salvo = self.cfg.pasta_transcricoes / f"{NUMERO}.docx"
        self.assertTrue(salvo.exists())
        self.assertIn(f"não consegui gravar em {destino}", saida)
        self.assertIn(f"Transcrição gravada em: {salvo}", saida)

    def test_erro_de_disco_vira_mensagem_e_codigo_1(self):
        def disco(alvo, dados):
            raise OSError(errno.ENOSPC, "Não há espaço no disco", str(alvo))

        with mock.patch.object(documento.sistema, "gravar_atomico", side_effect=disco):
            codigo, saida = rodar(["transcrever", str(self.wav), "--processo", NUMERO,
                                   "--config", str(self.tmp.ini), "--sem-falantes"])
        self.assertEqual(codigo, 1, saida)
        self.assertIn("Não consegui concluir a transcrição: Não há espaço no disco", saida)

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
        with mock.patch.object(falantes, "instalar", side_effect=lambda p: chamadas.append(p)), \
                mock.patch.object(falantes, "disponivel", return_value=True):
            # --sem-pip, da versão anterior, é aceito e não muda nada: não há pip
            self.assertEqual(rodar(["falantes", "instalar", "--sem-pip"])[0], 0)
            self.assertEqual(rodar(["falantes", "instalar"])[0], 0)
        self.assertEqual(len(chamadas), 2)
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
