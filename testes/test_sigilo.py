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
  tinha no acervo (Lote 1/Concluídos/X.pdf, Transcricoes/2025/X.docx);
* a consulta de um número só (download e transcrição) via o arquivo cujo
  nome começa pelo número, e o compartilhamento o via em qualquer posição
  do nome: a regra dava duas respostas para o mesmo processo.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from helestron.nucleo import caminhos, cnj, cofre_senhas, sigilo
from testes.test_nucleo import _numero, pauta_com_sigiloso


def _lembrar_em_outro_processo(pauta: str, numero: str, barreira) -> None:
    """Num processo à parte (a janela, o "baixar" da linha de comando, o
    conector): espera os outros e acrescenta 'numero' ao registro do download."""
    barreira.wait(60)
    sigilo.lembrar_do_download([numero], Path(pauta))


def _relatorio(controle: Path, linhas, nome: str = "relatorio.csv",
               codificacao: str = "utf-8-sig") -> Path:
    """Um relatório de lote como o motor grava (';', UTF-8 com BOM), ou como o
    Excel o salva (codificacao="cp1252")."""
    controle.mkdir(parents=True, exist_ok=True)
    cabecalho = ("ordem;processo;tribunal;sistema;situacao;paginas;documentos;arquivo;"
                 "sigiloso;incompleto;detalhe;data_hora;causa")
    corpo = [cabecalho] + [f"{i};{processo};TJAL;esaj;OK;2;1;x.pdf;{sim};;;2026-10-01 10:00:00;"
                           for i, (processo, sim) in enumerate(linhas, 1)]
    arquivo = controle / nome
    arquivo.write_bytes("\r\n".join(corpo).encode(codificacao) + b"\r\n")
    return arquivo


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
        self.assertEqual(sorted(p.name for p in self.pauta.parent.iterdir()),
                         ["pauta.sigilo.json"], "sobrou temporário ou trava")
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


class TestRegistroDoDownload(Base):
    """Achado R19: o sigilo que o portal mostrou num download vale na regra
    única (a quarta fonte), mesmo com os autos no acervo."""

    def test_registro_ao_lado_do_da_pauta(self):
        x, inc, y = _numero("0700881"), _numero("0700881", dependente="01"), _numero("0700882")
        self.assertIsNone(sigilo.arquivo_do_download(None))
        self.assertEqual(sigilo.arquivo_do_download(),
                         self.pauta.with_name("download.sigilo.json"))
        self.assertFalse(sigilo.processo_sigiloso(self.cfg, x))
        self.assertTrue(sigilo.lembrar_do_download([x]))
        dados = json.loads(sigilo.arquivo_do_download().read_text(encoding="utf-8"))
        self.assertEqual(dados["processos"], [x.nome_arquivo])
        self.assertIn("download", dados["sobre"])
        self.assertFalse(self.pauta.exists(), "o registro não cria o banco da pauta")
        self.assertEqual(sigilo.apuradas_no_download(), {x.nome_arquivo})
        # a regra única: o processo e o incidente dele; a pauta não muda
        self.assertTrue(sigilo.processo_sigiloso(self.cfg, x))
        self.assertEqual(sigilo.motivo(self.cfg, x), sigilo.MOTIVO_DOWNLOAD)
        self.assertEqual(sigilo.motivo(self.cfg, inc), sigilo.MOTIVO_DOWNLOAD_PRINCIPAL)
        self.assertEqual(sigilo.motivo(self.cfg, y), "")
        chaves = sigilo.chaves_sigilosas(self.sigilosos)
        self.assertIn(x.nome_arquivo, chaves)
        self.assertIn(inc.nome_arquivo, chaves)
        self.assertNotIn(y.nome_arquivo, chaves)
        self.assertEqual(sigilo.chaves_da_pauta(), set())
        self.assertEqual(sigilo.motivo_da_pauta(x), "")
        # pauta=None não consulta nem a pauta nem o registro ao lado dela
        self.assertEqual(sigilo.chaves_sigilosas(self.sigilosos, pauta=None), set())
        # os autos na pasta dos sigilosos continuam dizendo o motivo deles
        self.arquivo(f"Lote 1/{x.nome_arquivo}.pdf")
        self.assertEqual(sigilo.motivo(self.cfg, x), sigilo.MOTIVO_PASTA)

    def test_so_acrescenta_e_nao_sobrescreve_o_ilegivel(self):
        a, b = _numero("0700883"), _numero("0700884")
        self.assertTrue(sigilo.lembrar_do_download([a]))
        self.assertTrue(sigilo.lembrar_do_download([b.formatado, "não é número"]))
        self.assertTrue(sigilo.lembrar_do_download([a]))
        self.assertEqual(sigilo.apuradas_no_download(), {a.nome_arquivo, b.nome_arquivo})
        self.assertEqual(sigilo.apuradas_da_pauta(), set(), "o da pauta é outro registro")
        registro = sigilo.arquivo_do_download()
        registro.write_text("{estragado", encoding="utf-8")
        with self.assertLogs("nucleo.sigilo", "WARNING"):
            self.assertFalse(sigilo.lembrar_do_download([_numero("0700885")]))
        self.assertEqual(registro.read_text(encoding="utf-8"), "{estragado")

    def test_pasta_local_ainda_inexistente_e_criada(self):
        pauta = self.tmp / "nova" / "local" / "pauta.sqlite3"
        x = _numero("0700886")
        self.assertTrue(sigilo.lembrar_do_download([x], pauta))
        self.assertEqual(sigilo.apuradas_no_download(pauta), {x.nome_arquivo})
        self.assertFalse(pauta.exists())


class TestRegistroEntreProcessos(Base):
    """Achado V3: o registro só tinha trava dentro do processo e não insistia
    no arquivo preso. A janela e o "baixar" da linha de comando gravando ao
    mesmo tempo perdiam números (o último os.replace apagava o que o outro
    acrescentou), e um instante de arquivo preso (antivírus) bastava para o
    sigilo não ser guardado."""

    def _arquivos(self):
        return sorted(p.name for p in self.pauta.parent.iterdir())

    def test_gravacoes_de_varios_processos_nao_se_perdem(self):
        numeros = [_numero(f"07009{i:02d}") for i in range(8)]
        ctx = multiprocessing.get_context("spawn")
        barreira = ctx.Barrier(len(numeros))
        processos = [ctx.Process(target=_lembrar_em_outro_processo,
                                 args=(str(self.pauta), n.formatado, barreira))
                     for n in numeros]
        for p in processos:
            p.start()
        for p in processos:
            p.join(120)
        self.assertEqual([p.exitcode for p in processos], [0] * len(numeros))
        self.assertEqual(sigilo.apuradas_no_download(), {n.nome_arquivo for n in numeros})
        self.assertEqual(self._arquivos(), ["download.sigilo.json"], "sobrou trava ou temporário")

    def test_troca_presa_por_um_instante_insiste(self):
        a, b = _numero("0700911"), _numero("0700912")
        self.assertTrue(sigilo.lembrar_do_download([a]))
        original = os.replace
        falhas = [PermissionError(13, "O arquivo já está sendo usado por outro processo")] * 2

        def replace(origem, destino):
            if str(destino).endswith("download.sigilo.json") and falhas:
                raise falhas.pop()
            return original(origem, destino)

        with mock.patch.object(cofre_senhas.os, "replace", replace), \
                mock.patch.object(cofre_senhas.time, "sleep"):
            self.assertTrue(sigilo.lembrar_do_download([b]))
        self.assertEqual(falhas, [])
        self.assertEqual(sigilo.apuradas_no_download(), {a.nome_arquivo, b.nome_arquivo})
        self.assertEqual(self._arquivos(), ["download.sigilo.json"])

    def test_leitura_presa_por_um_instante_nao_perde_os_outros(self):
        a, b = _numero("0700913"), _numero("0700914")
        self.assertTrue(sigilo.lembrar_do_download([a]))
        registro = sigilo.arquivo_do_download()
        original = Path.read_text
        # a olhada sem trava e a 1ª leitura sob a trava dão com o arquivo preso
        falhas = [PermissionError(13, "Acesso negado")] * 2

        def ler(caminho, *args, **kwargs):
            if caminho == registro and falhas:
                raise falhas.pop()
            return original(caminho, *args, **kwargs)

        with mock.patch.object(Path, "read_text", ler), \
                mock.patch.object(sigilo.time, "sleep") as dormir:
            self.assertTrue(sigilo.lembrar_do_download([b]))
        self.assertEqual(falhas, [])
        self.assertEqual(dormir.call_count, 1)
        self.assertEqual(sigilo.apuradas_no_download(), {a.nome_arquivo, b.nome_arquivo})

    def test_trava_de_outro_processo(self):
        x = _numero("0700915")
        trava = sigilo.arquivo_do_download().with_name("download.sigilo.json.trava")
        trava.write_text("999999", encoding="ascii")
        with mock.patch.object(cofre_senhas, "ESPERA_TRAVA_S", 0.2), \
                self.assertLogs("nucleo.sigilo", "WARNING"):
            self.assertFalse(sigilo.lembrar_do_download([x]))
        self.assertTrue(trava.exists(), "a trava viva não é de quem esperou")
        self.assertEqual(sigilo.apuradas_no_download(), set())
        # esquecida (o processo que a tinha caiu): deixa de valer
        velho = time.time() - cofre_senhas.TRAVA_ABANDONADA_S - 5
        os.utime(trava, (velho, velho))
        self.assertTrue(sigilo.lembrar_do_download([x]))
        self.assertEqual(sigilo.apuradas_no_download(), {x.nome_arquivo})
        self.assertEqual(self._arquivos(), ["download.sigilo.json"])


class TestRelatorioDoLote(Base):
    """Achado V2: só o motor alimentava o registro do download. O lote baixado
    com a separação desligada pela versão anterior (ou depois de a pasta
    LOCAL ser apagada, ou com o acervo levado para outro computador) tinha o
    sigiloso no acervo e o relatório dizendo sigiloso=sim, mas a regra única
    não o via: o índice, o texto para a IA, o conector, o pacote e a nuvem o
    tratavam como público."""

    def setUp(self):
        super().setUp()
        self.acervo = self.tmp / "Acervo"
        self.lote = self.acervo / "Processos" / "Lote 1"

    def test_relatorio_do_lote_marca_e_vai_para_o_registro(self):
        x, y, z = _numero("0700921"), _numero("0700922"), _numero("0700923")
        inc = _numero("0700924", dependente="01")
        _relatorio(self.lote / "_controle", [
            (x.formatado, "sim"), (y.formatado, "não"),
            ("(processo sigiloso)", "sim"),       # a linha mascarada não tem número
            (inc.formatado, "Sim")])
        # o "(atualizado)", salvo pelo Excel em ANSI, também conta
        _relatorio(self.lote / "_controle", [(z.formatado, "sim"), (y.formatado, "não")],
                   nome="relatorio (atualizado).csv", codificacao="cp1252")
        self.assertFalse(sigilo.processo_sigiloso(self.cfg, x))
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        esperado = {x.nome_arquivo, z.nome_arquivo, inc.nome_arquivo}
        self.assertEqual(set(chaves), esperado)
        self.assertNotIn(y.nome_arquivo, chaves)
        self.assertNotIn(_numero("0700924").nome_arquivo, chaves,
                         "o principal não fica sigiloso pelo incidente")
        # passou a valer no registro do download, para o resto do programa
        self.assertEqual(sigilo.apuradas_no_download(), esperado)
        self.assertEqual(sigilo.motivo(self.cfg, x), sigilo.MOTIVO_DOWNLOAD)
        # sem o acervo, só a pasta, a pauta e o registro (nada é lido)
        with mock.patch.object(sigilo, "_pastas_de_controle") as procurar:
            self.assertEqual(set(sigilo.chaves_sigilosas(self.sigilosos)), esperado)
        procurar.assert_not_called()

    def test_o_que_a_pasta_ou_a_pauta_ja_dao_nao_vai_para_o_registro(self):
        """Achado V4: o relatório marca também o que o lote só TRATOU como
        sigiloso por causa da pasta ou da pauta; o registro do download diria
        que o portal o apurou."""
        da_pauta, da_pasta = _numero("0700931"), _numero("0700932")
        inc_da_pauta = _numero("0700931", dependente="02")
        sigilo.lembrar_da_pauta([da_pauta])
        self.arquivo(f"Lote 1/{da_pasta.nome_arquivo}.pdf")
        _relatorio(self.lote / "_controle", [(da_pauta.formatado, "sim"),
                                             (inc_da_pauta.formatado, "sim"),
                                             (da_pasta.formatado, "sim")])
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        for n in (da_pauta, da_pasta, inc_da_pauta):
            self.assertIn(n.nome_arquivo, chaves)
        self.assertEqual(sigilo.apuradas_no_download(), set())
        self.assertFalse(sigilo.arquivo_do_download().exists())
        # pauta=None: nem a pauta nem o registro - o relatório vale assim mesmo
        self.assertIn(da_pauta.nome_arquivo,
                      sigilo.chaves_sigilosas(self.sigilosos, self.acervo, pauta=None))
        self.assertFalse(sigilo.arquivo_do_download().exists())

    def test_recurso_interno_sigiloso_torna_sigiloso_o_principal(self):
        """Achado Y4: o recurso interno do 2º grau (/50000, /50001) corre nos
        mesmos autos do principal. A linha "sim" dele no relatório do lote dá
        como sigiloso também o principal, que volta ao registro do download
        (o principal que só a consulta do recurso apurou não tem linha
        própria); e o mesmo vale nas outras fontes. O incidente comum (/01)
        continua sem tornar o principal sigiloso."""
        p, e = _numero("0700991"), _numero("0700991", dependente="50000")
        q, q01 = _numero("0700992"), _numero("0700992", dependente="01")
        _relatorio(self.lote / "_controle", [(e.formatado, "sim"), (q01.formatado, "sim")])
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        self.assertIn(p.nome_arquivo, chaves)
        self.assertIn(q01.nome_arquivo, chaves)
        self.assertNotIn(q.nome_arquivo, chaves, "o principal não herda do incidente comum")
        self.assertEqual(set(sigilo.apuradas_no_download()),
                         {p.nome_arquivo, e.nome_arquivo, q01.nome_arquivo})
        # o registro do download e a pasta dos sigilosos, sem o relatório
        sigilo.arquivo_do_download().unlink()
        (self.lote / "_controle" / "relatorio.csv").unlink()
        r, e2 = _numero("0700993"), _numero("0700993", dependente="50001")
        sigilo.lembrar_do_download([e2])
        hc = _originario("0803091")
        self.arquivo(f"Lote 1/{cnj.nome_dos_autos(replace(hc, dependente='50000'), '2g')}.pdf")
        self.arquivo(f"Lote 1/{q01.nome_arquivo}.pdf")
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        self.assertIn(r.nome_arquivo, chaves)
        self.assertIn(hc.nome_arquivo, chaves, "o recurso interno do HC (órgão 0000)")
        self.assertNotIn(q.nome_arquivo, chaves)
        self.assertEqual(sigilo.com_principais_dos_recursos([q01.nome_arquivo]),
                         {q01.nome_arquivo})

    def test_recurso_interno_do_relatorio_completo(self):
        """Achado Y4, com a separação ligada: a linha do recurso interno no
        relatório do lote no acervo sai mascarada, e ele não tem autos. O
        relatório completo, na pasta dos sigilosos, ainda o diz sigiloso -
        e, por ele, o principal, que volta ao registro. Do completo, só as
        linhas dos recursos internos contam (as outras, como antes, não)."""
        p, e = _numero("0700994"), _numero("0700994", dependente="50000")
        s = _numero("0700995")                       # sigiloso do 1º grau, sem autos na pasta
        completo = _relatorio(self.sigilosos / "Lote 1" / "_controle",
                              [(e.formatado, "sim"), (s.formatado, "sim")])
        _relatorio(self.lote / "_controle", [("(processo sigiloso)", "sim")] * 2)
        self.assertEqual(sigilo.recursos_dos_completos(self.sigilosos),
                         {e.nome_arquivo, p.nome_arquivo})
        self.assertEqual(sigilo.chaves_sigilosas(self.sigilosos), set(), "só com o acervo")
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        self.assertEqual(set(chaves), {e.nome_arquivo, p.nome_arquivo})
        self.assertEqual(set(sigilo.apuradas_no_download()), {e.nome_arquivo, p.nome_arquivo})
        completo.unlink()
        self.assertEqual(sigilo.recursos_dos_completos(self.sigilosos), set())
        self.assertEqual(sigilo.recursos_dos_completos(self.tmp / "não existe"), set())

    def test_onde_o_relatorio_e_procurado(self):
        na_raiz, solto, fundo, longe, cache, oculto = (_numero(f"07009{i}") for i in range(40, 46))
        _relatorio(self.acervo / "_controle", [(na_raiz.formatado, "sim")])     # o acervo é o lote
        _relatorio(self.acervo / "Lote solto" / "_controle", [(solto.formatado, "sim")])
        _relatorio(self.acervo / "Processos" / "2025" / "Lote 3" / "_controle",
                   [(fundo.formatado, "sim")])
        _relatorio(self.acervo / "a" / "b" / "c" / "d" / "_controle", [(longe.formatado, "sim")])
        _relatorio(self.acervo / "_ia" / "x" / "_controle", [(cache.formatado, "sim")])
        _relatorio(self.acervo / "Processos" / ".escondida" / "_controle",
                   [(oculto.formatado, "sim")])
        _relatorio(self.lote / "_controle" / "midias", [(longe.formatado, "sim")])
        achados = sigilo.sigilosos_dos_relatorios(self.acervo)
        self.assertEqual(set(achados), {na_raiz.nome_arquivo, solto.nome_arquivo,
                                        fundo.nome_arquivo})
        self.assertEqual(sigilo.sigilosos_dos_relatorios(self.tmp / "não existe"), set())
        self.assertEqual(sigilo.sigilosos_dos_relatorios(None), set())

    def test_acervo_grande_para_de_descer_e_avisa(self):
        perto, longe = _numero("0700951"), _numero("0700952")
        _relatorio(self.lote / "_controle", [(perto.formatado, "sim")])
        for i in range(6):
            (self.acervo / "Documentos" / f"p{i}" / "q").mkdir(parents=True)
        _relatorio(self.acervo / "Documentos" / "p9" / "Lote" / "_controle",
                   [(longe.formatado, "sim")])
        sigilo._avisou_pasta_grande.clear()
        with mock.patch.object(sigilo, "MAX_PASTAS", 3), \
                self.assertLogs("nucleo.sigilo", "WARNING") as registro:
            achados = sigilo.sigilosos_dos_relatorios(self.acervo)
        self.assertIn(perto.nome_arquivo, achados, "os lotes de Processos vêm primeiro")
        self.assertIn("pastas demais", registro.output[0])
        self.assertEqual(set(sigilo.sigilosos_dos_relatorios(self.acervo)),
                         {perto.nome_arquivo, longe.nome_arquivo})

    def test_lotes_de_processos_nao_contam_para_o_limite(self):
        """Mais lotes em Processos do que MAX_PASTAS: todos são lidos (o
        limite, pela ordem do nome, deixaria de fora os mais recentes)."""
        numeros = [_numero(f"07009{i:02d}") for i in range(6)]
        for i, n in enumerate(numeros):
            _relatorio(self.acervo / "Processos" / f"Lote 2024-10-0{i + 1} 10h00" / "_controle",
                       [(n.formatado, "sim")])
        sigilo._avisou_pasta_grande.clear()
        with mock.patch.object(sigilo, "MAX_PASTAS", 2):
            achados = sigilo.sigilosos_dos_relatorios(self.acervo)
        self.assertTrue({n.nome_arquivo for n in numeros} <= set(achados))

    def test_relatorio_relido_so_quando_muda(self):
        x, y = _numero("0700961"), _numero("0700962")
        arquivo = _relatorio(self.lote / "_controle", [(x.formatado, "sim")])
        leituras = []
        original = sigilo._sigilosos_do_csv

        def contar(dados):
            leituras.append(len(dados))
            return original(dados)

        with mock.patch.object(sigilo, "_sigilosos_do_csv", contar):
            for _ in range(3):
                self.assertEqual(set(sigilo.sigilosos_dos_relatorios(self.acervo)),
                                 {x.nome_arquivo})
            self.assertEqual(len(leituras), 1)
            _relatorio(self.lote / "_controle", [(x.formatado, "sim"), (y.formatado, "sim")])
            depois = arquivo.stat().st_mtime_ns + 10 ** 9
            os.utime(arquivo, ns=(depois, depois))
            self.assertEqual(set(sigilo.sigilosos_dos_relatorios(self.acervo)),
                             {x.nome_arquivo, y.nome_arquivo})
            self.assertEqual(len(leituras), 2)
            # preso por um instante (o Excel): vale o que se leu da última vez
            os.utime(arquivo, ns=(depois + 10 ** 9, depois + 10 ** 9))
            with mock.patch.object(Path, "read_bytes",
                                   side_effect=PermissionError(13, "Acesso negado")):
                self.assertEqual(set(sigilo.sigilosos_dos_relatorios(self.acervo)),
                                 {x.nome_arquivo, y.nome_arquivo})


def _originario(seq: str, origem: str = "0000") -> cnj.Numero:
    """Um número que só existe no 2º grau: órgão 0000 (HC, MS, AI) ou 9xxx
    (plantão do 2º grau, turma recursal), com o dígito verificador certo."""
    corpo = f"{seq}2025802{origem}"
    dv = 98 - int(corpo + "00") % 97
    return cnj.ler(f"{seq}-{dv:02d}.2025.8.02.{origem}")


def _capa_2g(controle: Path, n: cnj.Numero, *origens: cnj.Numero) -> Path:
    """A capa do 2º grau como o e-SAJ a grava ("<número> (2G)_capa.json", com
    a lista "numeros_1a_instancia" no nível de cima)."""
    controle.mkdir(parents=True, exist_ok=True)
    arquivo = controle / f"{cnj.nome_dos_autos(n, '2g')}_capa.json"
    arquivo.write_text(json.dumps({
        "processo": n.formatado, "grau": "2g", "capa": {"classe": "Habeas Corpus"},
        "numeros_1a_instancia": [{"numero": o.formatado, "foro": "Maceió"} for o in origens]}),
        encoding="utf-8")
    return arquivo


class TestOrigemDoOriginario(Base):
    """Achado C3 da revisão do 2º grau: o originário do 2º grau (o HC, o MS, o
    AI de órgão 0000) só herdava o sigilo da ação de origem no download
    (motor._origem_sigilosa). Se a origem virava sigilosa DEPOIS, o HC, que
    traz cópia dela, seguia no índice, no texto para a IA, no conector, no
    pacote e na nuvem: a regra única não lia a capa guardada em _controle."""

    def setUp(self):
        super().setUp()
        self.acervo = self.tmp / "Acervo"
        self.controle = self.acervo / "Processos" / "Lote 1" / "_controle"
        self.a, self.b = _numero("0700971"), _numero("0700972")     # as ações de origem
        self.hc = _originario("0803001")                            # origem A
        self.hc_publico = _originario("0803002")                    # origem B, pública

    def test_a_origem_que_vira_sigilosa_depois_alcanca_o_hc(self):
        _capa_2g(self.controle, self.hc, self.a)
        _capa_2g(self.controle, self.hc_publico, self.b)
        _capa_2g(self.controle, self.a, self.a)       # a apelação: a origem é ela mesma
        # ninguém sigiloso: a capa não faz o HC sigiloso por si
        self.assertEqual(set(sigilo.chaves_sigilosas(self.sigilosos, self.acervo)), set())
        self.assertFalse(sigilo.arquivo_do_download().exists())
        # A passa a ser sigilosa pela pasta, depois do download do HC
        self.arquivo(f"Lote 9/{self.a.nome_arquivo}.pdf")
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        self.assertEqual(set(chaves), {self.a.nome_arquivo, self.hc.nome_arquivo})
        self.assertIn(cnj.nome_dos_autos(self.hc, "2g"), chaves)   # a chave dos autos também
        self.assertNotIn(self.hc_publico.nome_arquivo, chaves)
        # uma vez apurado, fica: o HC vai para o registro do download (A, que
        # a pasta dá, não), e vale sem o acervo
        self.assertEqual(sigilo.apuradas_no_download(), {self.hc.nome_arquivo})
        self.assertEqual(sigilo.motivo(self.cfg, self.hc), sigilo.MOTIVO_DOWNLOAD)
        self.assertEqual(set(sigilo.chaves_sigilosas(self.sigilosos)),
                         {self.a.nome_arquivo, self.hc.nome_arquivo})

    def test_origem_sigilosa_pela_pauta_pelo_registro_ou_pelo_relatorio(self):
        da_pauta, do_registro, do_relatorio = (_numero(f"0700{i}") for i in (981, 982, 983))
        incidente = _numero("0700971", dependente="01")          # de A, que será sigilosa
        hcs = {o: _originario(f"08030{i}") for i, o in enumerate(
            (da_pauta, do_registro, do_relatorio, incidente), 11)}
        for origem, hc in hcs.items():
            _capa_2g(self.controle, hc, origem)
        sigilo.lembrar_da_pauta([da_pauta])
        sigilo.lembrar_do_download([do_registro])
        _relatorio(self.controle, [(do_relatorio.formatado, "sim")])
        self.arquivo(f"Lote 9/{self.a.nome_arquivo}.pdf")
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        for origem, hc in hcs.items():
            self.assertIn(hc.nome_arquivo, chaves, origem.formatado)
        # pauta=None: sem a pauta e sem o registro, valem a pasta e o relatório
        chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo, pauta=None)
        self.assertIn(hcs[do_relatorio].nome_arquivo, chaves)
        self.assertIn(hcs[incidente].nome_arquivo, chaves)
        self.assertNotIn(hcs[da_pauta].nome_arquivo, chaves)

    def test_so_a_capa_do_originario_e_aberta(self):
        """A capa da apelação (e a do recurso interno dela), cuja origem é o
        próprio número, não é aberta: seria a capa de quase todo o acervo."""
        plantao = _originario("0800103", origem="9002")
        embargos = _numero("0700971", dependente="50000")
        _capa_2g(self.controle, self.hc, self.a)
        _capa_2g(self.controle, plantao, self.a)
        _capa_2g(self.controle, self.a, self.a)
        _capa_2g(self.controle, embargos, self.a)
        (self.controle / f"{self.a.nome_arquivo}_capa.json").write_text("{", encoding="utf-8")
        self.arquivo(f"Lote 9/{self.a.nome_arquivo}.pdf")
        lidas = []
        original = sigilo._origens_da_capa

        def contar(dados):
            lidas.append(dados["processo"])
            return original(dados)

        with mock.patch.object(sigilo, "_origens_da_capa", contar):
            chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        self.assertEqual(sorted(lidas), sorted([self.hc.formatado, plantao.formatado]))
        self.assertEqual(set(chaves), {self.a.nome_arquivo, self.hc.nome_arquivo,
                                       plantao.nome_arquivo})
        self.assertIn(embargos.nome_arquivo, chaves, "o recurso interno herda de A")

    def test_capa_relida_so_quando_muda(self):
        arquivo = _capa_2g(self.controle, self.hc, self.b)
        self.arquivo(f"Lote 9/{self.a.nome_arquivo}.pdf")
        leituras = []
        original = sigilo._origens_da_capa

        def contar(dados):
            leituras.append(dados)
            return original(dados)

        sabidas = sigilo.Sigilosas({self.a.nome_arquivo})
        with mock.patch.object(sigilo, "_origens_da_capa", contar):
            for _ in range(3):
                self.assertEqual(sigilo.herdadas_das_origens(self.acervo, sabidas), set())
            self.assertEqual(len(leituras), 1)
            _capa_2g(self.controle, self.hc, self.b, self.a)     # a capa refeita lista A
            depois = arquivo.stat().st_mtime_ns + 10 ** 9
            os.utime(arquivo, ns=(depois, depois))
            self.assertEqual(sigilo.herdadas_das_origens(self.acervo, sabidas),
                             {self.hc.nome_arquivo})
            self.assertEqual(len(leituras), 2)
            # presa por um instante: vale o que se leu da última vez
            os.utime(arquivo, ns=(depois + 10 ** 9, depois + 10 ** 9))
            with mock.patch.object(Path, "read_text",
                                   side_effect=PermissionError(13, "Acesso negado")):
                self.assertEqual(sigilo.herdadas_das_origens(self.acervo, sabidas),
                                 {self.hc.nome_arquivo})
        self.assertEqual(sigilo.herdadas_das_origens(None, sabidas), set())
        self.assertEqual(sigilo.herdadas_das_origens(self.acervo, set()), set())

    def test_o_registro_diz_a_origem_e_a_capa_uma_vez(self):
        """Achado V6 da verificação: o originário levado pela origem DEPOIS do
        download entrava no registro do download em silêncio - o motivo
        passava a ser "um download anterior apurou", e nada dizia que o HC
        saiu por causa de A. O aviso diz a origem e a capa, uma vez por
        originário novo: depois, o registro já o conhece."""
        capa = _capa_2g(self.controle, self.hc, self.a)
        _capa_2g(self.controle, self.hc_publico, self.b)
        self.arquivo(f"Lote 9/{self.a.nome_arquivo}.pdf")
        sabidas = sigilo.Sigilosas({self.a.nome_arquivo})
        self.assertEqual(sigilo.origens_herdadas(self.acervo, sabidas),
                         {self.hc.nome_arquivo: (self.a.nome_arquivo, capa)})
        self.assertEqual(sigilo.herdadas_das_origens(self.acervo, sabidas),
                         {self.hc.nome_arquivo})
        with self.assertLogs("nucleo.sigilo", "WARNING") as registro:
            chaves = sigilo.chaves_sigilosas(self.sigilosos, self.acervo)
        self.assertIn(self.hc.nome_arquivo, chaves)
        self.assertEqual(len(registro.output), 1, registro.output)
        self.assertIn(f"originário {self.hc.nome_arquivo} tratado como sigiloso: o processo "
                      f"de origem {self.a.nome_arquivo} é sigiloso (capa do 2º grau em {capa})",
                      registro.output[0])
        self.assertEqual(sigilo.apuradas_no_download(), {self.hc.nome_arquivo})
        # o registro já o conhece: a consulta seguinte não avisa de novo
        with self.assertNoLogs("nucleo.sigilo", "WARNING"):
            self.assertIn(self.hc.nome_arquivo,
                          sigilo.chaves_sigilosas(self.sigilosos, self.acervo))


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


class TestUmaSoResposta(Base):
    """Achado R20: a consulta de um número (na_pasta, que o download e a
    transcrição usam) só via os arquivos cujo nome COMEÇA pelo número, e o
    compartilhamento (chaves_na_pasta) aceita o número em qualquer posição.
    O processo era sigiloso para a nuvem e público para a transcrição nova,
    que ia para o acervo."""

    def test_numero_em_qualquer_posicao_do_nome(self):
        from helestron.transcricao import documento

        renomeada, digitos, minuta, gravacao = (_numero(s) for s in (
            "0700701", "0700702", "0700703", "0700704"))
        self.arquivo(f"Transcricoes/Audiência de instrução - {renomeada.nome_arquivo}.docx")
        self.arquivo(f"Lote 1/{digitos.digitos}.pdf")
        self.arquivo(f"Produtos/Sentença {minuta.nome_arquivo}.pdf")
        self.arquivo(f"Transcricoes/_audio/Audiência {gravacao.nome_arquivo} 2026-09-16/p1.wav")
        cfg = mock.Mock(pasta_sigilosos=self.sigilosos,
                        pasta_transcricoes=self.tmp / "Acervo" / "Transcricoes")
        todos = (renomeada, digitos, minuta, gravacao)
        self.assertEqual(sigilo.chaves_na_pasta(self.sigilosos),
                         {n.nome_arquivo for n in todos})
        for n in todos:
            self.assertTrue(sigilo.na_pasta(self.sigilosos, n), n)
            self.assertEqual(sigilo.motivo_da_pasta(self.sigilosos, n), sigilo.MOTIVO_PASTA)
            self.assertTrue(sigilo.processo_sigiloso(cfg, n), n)
            self.assertEqual(documento.pasta_das_transcricoes(cfg, n),
                             self.sigilosos / "Transcricoes", n)
        # o incidente herda do principal também assim
        incidente = _numero("0700703", dependente="01")
        self.assertEqual(sigilo.motivo_da_pasta(self.sigilosos, incidente),
                         sigilo.MOTIVO_PASTA_PRINCIPAL)
        # e o que não tem o número continua de fora
        outro = _numero("0700799")
        self.assertFalse(sigilo.na_pasta(self.sigilosos, outro))
        self.assertEqual(documento.pasta_das_transcricoes(cfg, outro), cfg.pasta_transcricoes)


class TestCoerenciaDaRegra(Base):
    """Achado Q4 da sétima verificação do 2º grau: a regra única
    (chaves_sigilosas) dava como sigiloso o principal de um recurso interno
    do 2º grau (/50000) sigiloso por qualquer fonte, mas as consultas de um
    número só (processo_sigiloso, motivo: o download fora do lote, a
    transcrição, a tela da audiência) só viam o principal pelo registro do
    download. Perdido o registro (as configurações apagadas na
    desinstalação, o acervo levado a outro computador), o "baixar" da skill
    devolvia o principal público, e a transcrição dele ia para o acervo.

    O invariante: para cada fonte e cada tipo de número marcado, a consulta
    de um número só e a regra concordam, número a número. As exceções
    legítimas são as fontes que só a regra com 'raiz' (o acervo) lê - o
    relatório do lote no acervo e a capa do originário -: nelas, a consulta
    de um número só nunca diz sigiloso o que a regra diz público, e passa a
    concordar com ela depois que a regra roda uma vez (ela leva ao registro
    do download o que só essas fontes dão)."""

    P = cnj.ler("0706265-50.2017.8.02.0001")
    P01 = cnj.ler("0706265-50.2017.8.02.0001/01")             # incidente comum
    E = cnj.ler("0706265-50.2017.8.02.0001/50000")            # recurso interno
    E2 = cnj.ler("0706265-50.2017.8.02.0001/50001")           # outro recurso interno
    H = _originario("0803061")                                 # HC, órgão 0000
    HE = cnj.ler(f"{_originario('0803061').formatado}/50000")  # recurso interno do HC
    A = _numero("0700991")                                     # a origem do HC na capa
    NUMEROS = (P, P01, E, E2, H, HE)
    FONTES = ("pasta", "pauta", "registro", "relatório do acervo", "completo",
              "capa do originário")
    SO_COM_RAIZ = {"relatório do acervo", "capa do originário"}

    def esperado(self, fonte: str, marcado: cnj.Numero) -> set[str]:
        """O que a regra deve dar: o marcado, os incidentes dele (o recurso
        interno é incidente do principal) e, se for recurso interno, o
        principal. Do completo, só a linha de recurso interno conta; da capa,
        só a do originário."""
        P, P01, E, E2, H, HE = self.NUMEROS
        if fonte == "completo" and marcado not in (E, E2, HE):
            return set()
        if fonte == "capa do originário" and marcado not in (H, HE):
            return set()
        familia = {P: {P, P01, E, E2}, P01: {P01}, E: {P, P01, E, E2}, E2: {P, P01, E, E2},
                   H: {H, HE}, HE: {H, HE}}[marcado]
        return {n.nome_arquivo for n in familia}

    def marcar(self, fonte: str, n: cnj.Numero, base: Path, pauta: Path) -> None:
        sig, lote = base / "Sigilosos", base / "Acervo" / "Processos" / "Lote Z"
        if fonte == "pasta":
            arquivo = sig / "Lote Z" / f"{cnj.nome_dos_autos(n, cnj.grau_do_numero(n))}.pdf"
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_bytes(b"x")
        elif fonte == "pauta":
            pauta_com_sigiloso(pauta, n)
        elif fonte == "registro":
            self.assertTrue(sigilo.lembrar_do_download([n], pauta))
        elif fonte == "relatório do acervo":
            _relatorio(lote / "_controle", [(n.formatado, "sim")])
        elif fonte == "completo":
            _relatorio(sig / "Lote Z" / "_controle", [(n.formatado, "sim")])
        else:       # a capa lista a origem A, cujos autos estão na pasta dos sigilosos
            _capa_2g(lote / "_controle", n, self.A)
            (sig / "Lote A").mkdir(parents=True)
            (sig / "Lote A" / f"{self.A.nome_arquivo}.pdf").write_bytes(b"x")

    def test_a_consulta_de_um_numero_so_concorda_com_a_regra(self):
        casos = [(fonte, n) for fonte in self.FONTES for n in self.NUMEROS]
        for i, (fonte, marcado) in enumerate(casos):
            with self.subTest(fonte=fonte, marcado=marcado.formatado):
                base = self.tmp / f"caso {i}"
                pauta = base / "local" / "pauta.sqlite3"
                pauta.parent.mkdir(parents=True)
                self.marcar(fonte, marcado, base, pauta)
                cfg = mock.Mock(pasta_sigilosos=base / "Sigilosos")

                def um_so():
                    return {n.nome_arquivo for n in self.NUMEROS
                            if sigilo.processo_sigiloso(cfg, n, pauta)}

                antes = um_so()                   # antes de a regra rodar
                chaves = sigilo.chaves_sigilosas(base / "Sigilosos", raiz=base / "Acervo",
                                                 pauta=pauta)
                regra = {n.nome_arquivo for n in self.NUMEROS
                         if sigilo.contem(chaves, n.nome_arquivo)}
                self.assertEqual(regra, self.esperado(fonte, marcado))
                if fonte in self.SO_COM_RAIZ:
                    self.assertLessEqual(antes, regra, "mais sigiloso que a regra")
                else:
                    self.assertEqual(antes, regra)
                self.assertEqual(um_so(), regra, "depois de a regra rodar")

    def test_o_motivo_diz_que_veio_do_recurso_interno(self):
        """O porquê do principal que só um recurso interno torna sigiloso, em
        cada fonte que as consultas de um número só leem; o do próprio
        processo, se houver, vem antes (o porquê de sempre não muda)."""
        P, P01, E = self.P, self.P01, self.E
        for fonte in ("pasta", "pauta", "registro", "completo"):
            with self.subTest(fonte=fonte):
                base = self.tmp / fonte
                pauta = base / "local" / "pauta.sqlite3"
                pauta.parent.mkdir(parents=True)
                self.marcar(fonte, E, base, pauta)
                cfg = mock.Mock(pasta_sigilosos=base / "Sigilosos")
                self.assertEqual(sigilo.motivo(cfg, P, pauta), sigilo.MOTIVO_RECURSO)
                self.assertEqual(sigilo.motivo(cfg, P01, pauta), sigilo.MOTIVO_RECURSO_PRINCIPAL)
                self.assertTrue(sigilo.motivo(cfg, E, pauta))
                if fonte == "completo":
                    self.assertEqual(sigilo.motivo(cfg, E, pauta), sigilo.MOTIVO_COMPLETO)
                # o principal no registro do download (o fluxo normal): vale o dele
                sigilo.lembrar_do_download([P], pauta)
                self.assertEqual(sigilo.motivo(cfg, P, pauta), sigilo.MOTIVO_DOWNLOAD)
        # as consultas de uma fonte só fazem a mesma conta
        base = self.tmp / "pasta"
        self.assertTrue(sigilo.na_pasta(base / "Sigilosos", P))
        self.assertFalse(sigilo.na_pasta(base / "Sigilosos", P, herdar=False))
        self.assertEqual(sigilo.motivo_da_pasta(base / "Sigilosos", P), sigilo.MOTIVO_RECURSO)
        self.assertTrue(sigilo.na_pauta(P, self.tmp / "pauta" / "local" / "pauta.sqlite3"))
        self.assertEqual(sigilo.motivo_do_download(P01, self.tmp / "registro" / "local" /
                                                   "pauta.sqlite3"),
                         sigilo.MOTIVO_DOWNLOAD_PRINCIPAL)

    def test_o_incidente_comum_e_o_primeiro_grau_nao_mudam(self):
        """Só o dependente /5xxxx deriva o principal: o incidente comum
        sigiloso (P/01), em qualquer fonte, deixa o principal público."""
        for fonte in ("pasta", "pauta", "registro", "completo"):
            with self.subTest(fonte=fonte):
                base = self.tmp / fonte
                pauta = base / "local" / "pauta.sqlite3"
                pauta.parent.mkdir(parents=True)
                self.marcar(fonte, self.P01, base, pauta)
                cfg = mock.Mock(pasta_sigilosos=base / "Sigilosos")
                self.assertEqual(sigilo.motivo(cfg, self.P, pauta), "")
                self.assertEqual(sigilo.motivo(cfg, self.E, pauta), "")

    def test_o_completo_so_e_relido_quando_muda(self):
        """O relatório completo é a única leitura a mais das consultas de um
        número só: cada um é relido só quando muda (como o do acervo)."""
        completo = _relatorio(self.sigilosos / "Lote Z" / "_controle", [(self.E.formatado, "sim")])
        with mock.patch.object(sigilo, "_sigilosos_do_csv",
                               wraps=sigilo._sigilosos_do_csv) as lido:
            for _ in range(3):
                self.assertEqual(sigilo.motivo(self.cfg, self.P), sigilo.MOTIVO_RECURSO)
            self.assertEqual(lido.call_count, 1)
            _relatorio(completo.parent, [(self.E.formatado, "não"), (self.P01.formatado, "sim")])
            self.assertEqual(sigilo.motivo(self.cfg, self.P), "")
            self.assertEqual(lido.call_count, 2)


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
