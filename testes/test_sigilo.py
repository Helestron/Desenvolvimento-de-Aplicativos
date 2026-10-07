"""A regra única do sigilo (nucleo/sigilo.py): a leitura da pauta só para
consulta, o registro do que a pauta já apurou e a pasta dos sigilosos como o
próprio preparo a deixa.

Regressões (1.0.2):

* a consulta "só de consulta" abria o banco da pauta pelo Armazem, que, com
  o banco estragado, o punha de lado e criava um vazio: o servidor MCP (com
  o Helestron fechado) esquecia os processos sigilosos que só a pauta
  indicava, e eles voltavam ao índice, ao conector e à nuvem;
* o sigilo apurado pela pauta só existia dentro do banco: perdido ou
  refeito o banco, o processo voltava a ser público;
* a regra só procurava os autos nos dois primeiros níveis da pasta dos
  sigilosos, mas o preparo leva o arquivo para o mesmo caminho que ele
  tinha no acervo (Lote 1/Concluídos/X.pdf, Transcricoes/2025/X.docx).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helestron.nucleo import caminhos, cnj, sigilo
from testes.test_nucleo import _numero, pauta_com_sigiloso


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.sigilosos = self.tmp / "Sigilosos"
        self.pauta = self.tmp / "local" / "pauta.sqlite3"
        self.pauta.parent.mkdir(parents=True)
        p = mock.patch.object(caminhos, "ARQUIVO_PAUTA", self.pauta)
        p.start()
        self.addCleanup(p.stop)
        sigilo.esquecer_pauta()
        self.addCleanup(sigilo.esquecer_pauta)
        self.cfg = mock.Mock(pasta_sigilosos=self.sigilosos)

    def arquivo(self, rel: str) -> Path:
        caminho = self.sigilosos / rel
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b"x")
        return caminho


class TestLeituraSoDeConsulta(Base):
    """Achado 11 (e 27): a consulta nunca grava no banco nem o põe de lado."""

    def test_banco_estragado_nao_e_posto_de_lado_pela_consulta(self):
        x = _numero("0700777")
        pauta_com_sigiloso(self.pauta, x)
        self.assertEqual(sigilo.chaves_da_pauta(), {x.nome_arquivo})
        # cabeçalho danificado (gravação interrompida, antivírus, disco de rede)
        dados = bytearray(self.pauta.read_bytes())
        dados[:100] = bytes(100)
        self.pauta.write_bytes(bytes(dados))
        with self.assertLogs("nucleo.sigilo", "WARNING") as registro:
            self.assertEqual(sigilo.chaves_da_pauta(), {x.nome_arquivo})
        self.assertIn("não consegui ler na pauta", "\n".join(registro.output))
        self.assertEqual(list(self.pauta.parent.glob("*corrompido*")), [],
                         "a consulta pôs o banco de lado")
        self.assertEqual(self.pauta.read_bytes(), bytes(dados), "a consulta mexeu no banco")
        # outro processo (o MCP reiniciado): o registro ao lado do banco lembra
        sigilo.esquecer_pauta()
        with self.assertLogs("nucleo.sigilo", "WARNING"):
            self.assertTrue(sigilo.na_pauta(x))
            self.assertTrue(sigilo.processo_sigiloso(self.cfg, x))

    def test_consulta_nao_grava_no_banco(self):
        x = _numero("0700777")
        pauta_com_sigiloso(self.pauta, x)
        antes = (self.pauta.stat().st_mtime_ns, self.pauta.read_bytes())
        with mock.patch("helestron.pauta.armazem.Armazem",
                        side_effect=AssertionError("a consulta abriu o Armazem")):
            self.assertIn(x.nome_arquivo, sigilo.chaves_da_pauta())
        self.assertEqual((self.pauta.stat().st_mtime_ns, self.pauta.read_bytes()), antes)
        # o SQLite pode criar o -wal e o -shm de leitura (vazios), mas nada é gravado
        wal = Path(f"{self.pauta}-wal")
        self.assertFalse(wal.exists() and wal.stat().st_size, "a consulta gravou no diário")
        # e a pauta abre normalmente depois
        pauta_com_sigiloso(self.pauta, _numero("0700778"))
        sigilo.esquecer_pauta()
        self.assertEqual(len(sigilo.chaves_da_pauta()), 2)

    def test_erro_passageiro_vale_o_que_ja_se_sabia(self):
        import sqlite3

        x = _numero("0700777")
        pauta_com_sigiloso(self.pauta, x)
        self.assertTrue(sigilo.na_pauta(x))
        pauta_com_sigiloso(self.pauta, _numero("0700778"))       # o banco mudou
        with mock.patch.object(sigilo, "_ler_banco",
                               side_effect=sqlite3.OperationalError("disk I/O error")), \
                self.assertLogs("nucleo.sigilo", "WARNING"):
            self.assertTrue(sigilo.na_pauta(x))
        self.assertTrue(self.pauta.is_file())
        self.assertEqual(list(self.pauta.parent.glob("*corrompido*")), [])

    def test_caminho_com_espaco_acento_e_simbolos(self):
        pasta = self.tmp / "Usuário Fulano" / "Dados #1 ?% local"
        pasta.mkdir(parents=True)
        banco = pasta / "pauta.sqlite3"
        x = _numero("0700777")
        pauta_com_sigiloso(banco, x)
        self.assertEqual(sigilo.chaves_da_pauta(banco), {x.nome_arquivo})

    def test_banco_sem_a_tabela_nao_marca_nada(self):
        self.pauta.write_bytes(b"")
        self.assertEqual(sigilo.chaves_da_pauta(), set())


class TestRegistroDoApurado(Base):
    """O sigilo, uma vez apurado pela pauta, fica - também fora do banco."""

    def test_registro_ao_lado_do_banco(self):
        x, inc = _numero("0700777"), _numero("0700777", dependente="01")
        self.assertIsNone(sigilo.arquivo_apurado(None))
        self.assertEqual(sigilo.arquivo_apurado(), self.pauta.with_name("pauta.sigilo.json"))
        pauta_com_sigiloso(self.pauta, x)          # o Armazem já guarda ao gravar
        dados = json.loads(sigilo.arquivo_apurado().read_text(encoding="utf-8"))
        self.assertEqual(dados["processos"], [x.nome_arquivo])
        self.assertIn("segredo de justiça", dados["sobre"])
        # o banco se perdeu (ou foi refeito): o processo continua sigiloso, e o
        # incidente dele também
        self.pauta.unlink()
        sigilo.esquecer_pauta()
        self.assertEqual(sigilo.chaves_da_pauta(), {x.nome_arquivo})
        self.assertTrue(sigilo.na_pauta(inc))
        self.assertEqual(sigilo.motivo(self.cfg, x), sigilo.MOTIVO_PAUTA)
        self.assertEqual(sigilo.apuradas_da_pauta(), {x.nome_arquivo})

    def test_banco_de_versao_anterior_sem_registro(self):
        x = _numero("0700777")
        pauta_com_sigiloso(self.pauta, x)
        sigilo.arquivo_apurado().unlink()          # como a 1.0.1 deixava
        sigilo.esquecer_pauta()
        self.assertEqual(sigilo.chaves_da_pauta(), {x.nome_arquivo})
        self.assertEqual(sigilo.apuradas_da_pauta(), {x.nome_arquivo}, "a leitura o guardou")

    def test_so_acrescenta_e_nao_sobrescreve_o_ilegivel(self):
        a, b = _numero("0700777"), _numero("0700778", dependente="02")
        self.assertTrue(sigilo.lembrar_da_pauta([a.formatado]))
        self.assertTrue(sigilo.lembrar_da_pauta([b.formatado, "não é número"]))
        self.assertEqual(sigilo.apuradas_da_pauta(), {a.nome_arquivo, b.nome_arquivo})
        self.assertEqual(list(self.pauta.parent.glob(".*.tmp")), [])
        registro = sigilo.arquivo_apurado()
        registro.write_text("{estragado", encoding="utf-8")
        with self.assertLogs("nucleo.sigilo", "WARNING"):
            self.assertFalse(sigilo.lembrar_da_pauta([_numero("0700779")]))
        self.assertEqual(registro.read_text(encoding="utf-8"), "{estragado")

    def test_lembrar_do_banco_posto_de_lado(self):
        copia = self.tmp / "copia.sqlite3"
        x = _numero("0700777")
        pauta_com_sigiloso(copia, x)
        sigilo.lembrar_do_banco(copia, self.pauta)
        self.assertEqual(sigilo.apuradas_da_pauta(), {x.nome_arquivo})
        lixo = self.tmp / "lixo.sqlite3"
        lixo.write_bytes(b"isto nao e um banco" * 50)
        with self.assertLogs("nucleo.sigilo", "INFO"):
            self.assertEqual(sigilo.lembrar_do_banco(lixo, self.pauta), 0)


class TestPastaFunda(Base):
    """Achado 16: o que o preparo leva para a pasta dos sigilosos conta."""

    def test_subpastas_do_lote_e_das_transcricoes(self):
        autos, docx, audio, diario = (_numero(s) for s in ("0700201", "0700202", "0700203",
                                                             "0700204"))
        inc = _numero("0700205", dependente="01")
        self.arquivo(f"Lote 1/Concluídos/{autos.nome_arquivo}.pdf")
        self.arquivo(f"Transcricoes/2025/{docx.nome_arquivo}.docx")
        self.arquivo(f"Transcricoes/2025/_audio/{audio.nome_arquivo} 2026-09-16 14h00.flac")
        self.arquivo(f"Transcricoes/_audio/{diario.nome_arquivo} 2026-09-16 15h00/parte1.wav")
        self.arquivo(f"Minhas coisas/2024/março/{inc.nome_arquivo}.pdf")
        esperado = {n.nome_arquivo for n in (autos, docx, audio, diario, inc)}
        self.assertEqual(sigilo.chaves_na_pasta(self.sigilosos), esperado)
        for n in (autos, docx, audio, diario, inc):
            self.assertTrue(sigilo.na_pasta(self.sigilosos, n), n)
            self.assertEqual(sigilo.motivo_da_pasta(self.sigilosos, n), sigilo.MOTIVO_PASTA)
        # o principal no fundo também faz o incidente sigiloso
        self.assertEqual(sigilo.motivo_da_pasta(self.sigilosos, _numero("0700201",
                                                                         dependente="03")),
                         sigilo.MOTIVO_PASTA_PRINCIPAL)

    def test_o_que_nao_conta(self):
        fundo, controle, oculta, docx_fora = (_numero(s) for s in ("0700301", "0700302",
                                                                   "0700303", "0700304"))
        self.arquivo(f"a/b/c/d/e/{fundo.nome_arquivo}.pdf")       # fundo demais
        self.arquivo(f"Lote 1/_controle/x/{controle.nome_arquivo}.pdf")
        self.arquivo(f"Lote 1/.cache/{oculta.nome_arquivo}.pdf")
        self.arquivo(f"Lote 1/{docx_fora.nome_arquivo}.docx")    # DOCX fora de Transcricoes
        self.assertEqual(sigilo.chaves_na_pasta(self.sigilosos), set())
        self.assertFalse(sigilo.na_pasta(self.sigilosos, fundo))

    def test_acervo_dentro_da_pasta_nao_conta(self):
        n = _numero("0700401")
        self.arquivo(f"Acervo/Processos/Lote 1/{n.nome_arquivo}.pdf")
        self.assertEqual(sigilo.chaves_na_pasta(self.sigilosos, self.sigilosos / "Acervo"),
                         set())
        self.assertEqual(sigilo.chaves_na_pasta(self.sigilosos), {n.nome_arquivo})

    def test_pasta_grande_para_de_descer_e_avisa(self):
        perto, longe = _numero("0700501"), _numero("0700502")
        self.arquivo(f"Lote/{perto.nome_arquivo}.pdf")
        for i in range(6):
            self.arquivo(f"Documentos/p{i}/q/leia.txt")
        self.arquivo(f"Documentos/p9/q/{longe.nome_arquivo}.pdf")
        sigilo._avisou_pasta_grande.clear()
        with mock.patch.object(sigilo, "MAX_PASTAS", 3), \
                self.assertLogs("nucleo.sigilo", "WARNING") as registro:
            achados = sigilo.chaves_na_pasta(self.sigilosos)
        self.assertIn(perto.nome_arquivo, achados, "os dois primeiros níveis sempre contam")
        self.assertIn("pastas demais", registro.output[0])
        self.assertEqual(sigilo.chaves_na_pasta(self.sigilosos),
                         {perto.nome_arquivo, longe.nome_arquivo})

    def test_pasta_inexistente(self):
        self.assertEqual(sigilo.chaves_na_pasta(self.tmp / "nao existe"), set())
        self.assertFalse(sigilo.na_pasta(self.tmp / "nao existe", _numero("0700601")))


class TestPreparoESigiloDuravel(unittest.TestCase):
    """Ponta a ponta (achados 11 e 16): o processo que só a pauta dava como
    sigiloso, levado pelo preparo para uma subpasta da pasta dos sigilosos,
    continua sigiloso depois que o banco da pauta é tirado - e uma cópia nova
    dele no acervo sai de novo, sem ir para o índice."""

    def test_continua_sigiloso_sem_a_pauta(self):
        from testes.test_compartilhar import _pdf
        from testes.test_compartilhar_sigilo import X, BaseSigilo

        caso = BaseSigilo("setUp")
        caso.setUp()
        self.addCleanup(caso.doCleanups)
        _pdf(caso.lote / "Concluídos" / f"{X}.pdf", ["SEGREDO"])
        caso.marcar_na_pauta()
        rel = caso.preparar()
        self.assertEqual(rel.sigilosos_levados, 1)
        self.assertTrue((caso.sig / "Lote 1" / "Concluídos" / f"{X}.pdf").exists())
        self.assertIn(X, sigilo.chaves_na_pasta(caso.sig, caso.acervo))
        # o banco da pauta saiu (e o registro do apurado também): vale a pasta
        caso.pauta.unlink()
        sigilo.arquivo_apurado(caso.pauta).unlink()
        sigilo.esquecer_pauta()
        self.assertTrue(sigilo.processo_sigiloso(caso.cfg, cnj.ler(X)))
        _pdf(caso.lote / f"{X}.pdf", ["SEGREDO de novo"])
        caso.preparar()
        caso.nada_de_x_no_acervo()
        indice = (caso.acervo / "INDICE.md").read_text(encoding="utf-8")
        self.assertNotIn(X, indice)


if __name__ == "__main__":
    unittest.main()
