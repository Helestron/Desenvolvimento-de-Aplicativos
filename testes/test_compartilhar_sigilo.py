"""Processo sigiloso no acervo: o que sai, o que trava o compartilhamento e o
que só é avisado; o incidente do sigiloso; os restos (a minuta em Produtos/
e o relatório do lote); o "buscar" do conector num acervo grande; e a
limpeza dos conectores da versão anterior.

Regressões (quarta rodada da revisão):

* uma cópia fora de Processos/<lote>/ (Processos/Lote 1/Concluídos/X.pdf) ou
  a minuta do usuário (Minutas/X - despacho.docx) nunca saía do acervo e
  travava TODO o compartilhamento, com a frase "Feche o PDF" para um DOCX e
  "2 processos" para um só;
* o incidente ("...0001-01") do processo sigiloso continuava no índice, no
  conector e na nuvem;
* levados os autos do sigiloso, ficavam no acervo a minuta em Produtos/ e a
  linha dele no relatório do lote, com o número;
* o "buscar" do conector relistava o acervo e reaplicava a regra do sigilo
  para cada processo (O(N²): cerca de 25 minutos com 3.000 PDFs);
* o conector "assessor-integrado" ficava no Claude Desktop mesmo depois de
  desinstalar o Helestron.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from helestron.compartilhar import chatgpt, claude, mcp_servidor, nuvem, preparo
from helestron.nucleo import caminhos, cnj, config, sigilo
from testes.test_compartilhar import _docx, _pdf
from testes.test_nucleo import pauta_com_sigiloso


def _num(seq: int) -> str:
    corpo = f"{seq:07d}202480200001"
    dv = 98 - int(corpo + "00") % 97
    return f"{seq:07d}-{dv:02d}.2024.8.02.0001"


X = _num(778)          # o sigiloso (pela pauta)
Y = _num(779)          # o público


class BaseSigilo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.base = base
        self.acervo = base / "Acervo"
        self.sig = base / "Sigilosos"
        self.lote = self.acervo / "Processos" / "Lote 1"
        self.pauta = base / "local" / "pauta.sqlite3"
        p = mock.patch.object(caminhos, "ARQUIVO_PAUTA", self.pauta)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(sigilo.esquecer_pauta)
        sigilo.esquecer_pauta()
        self.cfg = config.Config(base / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.acervo))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.sig))
        _pdf(self.lote / f"{Y}.pdf", ["Petição inicial do público"])

    def marcar_na_pauta(self, *numeros: str) -> None:
        self.pauta.parent.mkdir(parents=True, exist_ok=True)
        pauta_com_sigiloso(self.pauta, *(cnj.ler(n) for n in numeros or (X,)))
        sigilo.esquecer_pauta()

    def preparar(self):
        return preparo.atualizar_contexto(self.cfg, extrair_texto=False)

    def nada_de_x_no_acervo(self):
        restos = [p.relative_to(self.acervo).as_posix() for p in self.acervo.rglob("*")
                  if p.is_file() and X in p.name]
        self.assertEqual(restos, [], "ficou no acervo arquivo do processo sigiloso")


class TestBloqueioSoDosAutos(BaseSigilo):
    """Só os autos (PDF) presos travam o compartilhamento; o resto do processo
    sigiloso sai junto (com aviso) e, se não puder sair, só é avisado - com o
    arquivo, o motivo e o que fazer."""

    def setUp(self):
        super().setUp()
        self.concluido = _pdf(self.lote / "Concluídos" / f"{X}.pdf", ["SEGREDO"])
        self.minuta = _docx(self.acervo / "Minutas" / f"{X} - despacho.docx", ["minuta"])
        self.produto = _docx(self.acervo / "Produtos" / f"{X} - sentença.docx", ["produto"])
        self.marcar_na_pauta()

    def test_tudo_do_sigiloso_sai_com_aviso_e_nada_trava(self):
        from helestron.servidor import api_compartilhar as api

        rel = self.preparar()
        self.assertEqual(rel.sigilosos_no_acervo, [])
        self.assertEqual(rel.sigilosos_avisos, [])
        self.nada_de_x_no_acervo()
        # o mesmo caminho dentro da pasta dos sigilosos (os lotes na raiz dela)
        self.assertTrue((self.sig / "Lote 1" / "Concluídos" / f"{X}.pdf").exists())
        self.assertTrue((self.sig / "Minutas" / f"{X} - despacho.docx").exists())
        self.assertTrue((self.sig / "Produtos" / f"{X} - sentença.docx").exists())
        avisos = " ".join(rel.avisos)
        for rel_origem in (Path("Processos", "Lote 1", "Concluídos", f"{X}.pdf"),
                           Path("Minutas", f"{X} - despacho.docx"),
                           Path("Produtos", f"{X} - sentença.docx")):
            self.assertIn(str(rel_origem), avisos)
        self.assertIn("foi levado para a pasta dos sigilosos", avisos)
        self.assertIn("1 processo sigiloso levado para a pasta dos sigilosos", rel.resumo)
        app = mock.Mock(cfg=self.cfg, sigilosos_presos=[], sigilosos_avisos=[],
                        sigilosos_motivos={})
        api.registrar_presos(app, rel.sigilosos_no_acervo)
        api.exigir_sem_sigiloso(app)          # não recusa

    def test_minuta_aberta_no_word_nao_trava_mas_e_avisada(self):
        from helestron.download import motor

        original = motor._mover

        def preso(origem, destino, *a, **k):
            if Path(origem) == self.minuta:
                raise PermissionError(13, "O arquivo está aberto em outro programa")
            return original(origem, destino, *a, **k)

        with mock.patch.object(motor, "_mover", preso):
            rel = self.preparar()
        self.assertEqual(rel.sigilosos_no_acervo, [], "a minuta do usuário travou tudo")
        self.assertEqual(rel.sigilosos_avisos, [self.minuta])
        frase = " ".join(rel.avisos)
        self.assertIn(str(Path("Minutas", f"{X} - despacho.docx")), frase)
        self.assertIn(f"Um arquivo do processo {X}, que corre em segredo de justiça, ficou no "
                      "acervo", frase)
        self.assertIn("está aberto em outro programa?", frase)
        self.assertIn(f"mova-o você mesmo para a pasta dos sigilosos ({self.sig / 'Minutas'})",
                      frase)
        self.assertNotIn("Feche o PDF", frase)
        self.assertIn("1 arquivo de processo sigiloso ficou no acervo", rel.resumo)
        # o conector e o índice já deixam o processo de fora
        self.assertNotIn(X, (self.acervo / "INDICE.md").read_text(encoding="utf-8"))

    def test_autos_presos_travam_com_o_arquivo_o_motivo_e_o_destino(self):
        from helestron.download import motor
        from helestron.servidor import api_compartilhar as api
        from helestron.servidor.rede import ErroApi

        autos = _pdf(self.lote / f"{X}.pdf", ["SEGREDO"])
        original = motor._mover

        def preso(origem, destino, *a, **k):
            if Path(origem) in (autos, self.concluido):
                raise PermissionError(13, "O arquivo está aberto em outro programa")
            return original(origem, destino, *a, **k)

        with mock.patch.object(motor, "_mover", preso), self.assertLogs("compartilhar", "ERROR"):
            rel = self.preparar()
            self.assertEqual(sorted(rel.sigilosos_no_acervo), sorted([autos, self.concluido]))
            # o resumo (o que a linha de comando imprime) diz a trava à parte
            self.assertTrue(rel.resumo.endswith(
                "2 autos de processo sigiloso presos no acervo; não compartilhe"), rel.resumo)
            app = mock.Mock(cfg=self.cfg, sigilosos_presos=[], sigilosos_avisos=[],
                            sigilosos_motivos={})
            api.registrar_presos(app, rel.sigilosos_no_acervo, rel.motivos)
            with self.assertRaises(ErroApi) as caso:
                api.exigir_sem_sigiloso(app)
        frase = caso.exception.mensagem if hasattr(caso.exception, "mensagem") \
            else str(caso.exception)
        self.assertEqual(caso.exception.status, 409)
        # um processo, dois arquivos - e nunca "2 processos"
        self.assertIn(f"2 arquivos dos autos do processo {X}, que corre em segredo de justiça",
                      frase)
        self.assertNotIn("2 processos", frase)
        self.assertIn(str(Path("Processos", "Lote 1", f"{X}.pdf")), frase)
        self.assertIn(str(Path("Processos", "Lote 1", "Concluídos", f"{X}.pdf")), frase)
        self.assertIn("(está aberto em outro programa?)", frase)
        self.assertIn("ou mova-os para a pasta dos sigilosos", frase)
        self.assertIn("nada do acervo é compartilhado", frase)
        # a minuta e o produto saíram mesmo assim
        self.assertFalse(self.minuta.exists())
        self.assertFalse(self.produto.exists())
        # fechados os PDFs, a nova tentativa os leva e libera o compartilhamento
        api.exigir_sem_sigiloso(app)
        self.nada_de_x_no_acervo()

    def test_inicio_mostra_o_arquivo_o_que_fazer_e_o_que_fica_suspenso(self):
        from helestron.servidor import api_geral

        autos = _pdf(self.lote / f"{X}.pdf", ["SEGREDO"])
        app = mock.Mock(cfg=self.cfg, sigilosos_presos=[autos], sigilosos_avisos=[self.minuta],
                        sigilosos_motivos={autos: "está aberto em outro programa?"},
                        credenciais_sessao={}, pendencia_pauta=None)
        with mock.patch.object(api_geral.servicos, "pendencias", return_value=[]), \
                mock.patch.object(api_geral.servicos, "cofre", side_effect=OSError):
            pendencias = {p["chave"]: p for p in api_geral._pendencias(app)}
        trava = pendencias["sigilo"]
        self.assertEqual(trava["titulo"], "Processo sigiloso no acervo")
        self.assertEqual(trava["acao"], "compartilhar")
        self.assertIn(str(Path("Processos", "Lote 1", f"{X}.pdf")), trava["mensagem"])
        self.assertIn("o pacote e o espelho na nuvem ficam suspensos", trava["mensagem"])
        self.assertNotIn("provavelmente", trava["mensagem"])
        aviso = pendencias["sigilo-arquivos"]
        self.assertEqual(aviso["titulo"], "Arquivo de processo sigiloso no acervo")
        self.assertIn(str(Path("Minutas", f"{X} - despacho.docx")), aviso["mensagem"])
        self.assertIn("O compartilhamento continua", aviso["mensagem"])
        self.assertEqual(aviso["arquivos"], [str(self.minuta)])

    def test_pasta_dos_sigilosos_inacessivel_diz_o_motivo_certo(self):
        from helestron.download import motor

        def sem_pasta(origem, destino, *a, **k):
            raise OSError(5, "Erro de E/S")

        autos = _pdf(self.lote / f"{X}.pdf", ["SEGREDO"])
        with mock.patch.object(motor, "_mover", sem_pasta), self.assertLogs("compartilhar"):
            rel = self.preparar()
        self.assertIn(autos, rel.sigilosos_no_acervo)
        self.assertIn("presos no acervo; não compartilhe", rel.resumo)
        frase = preparo.frase_sigilosos_no_acervo([autos], self.cfg, rel.motivos)
        self.assertIn("a pasta dos sigilosos não está acessível", frase)
        self.assertNotIn("aberto em outro programa", frase)


class TestResumoDoPreparo(unittest.TestCase):
    def test_autos_presos_tem_parte_propria_no_resumo(self):
        rel = preparo.RelatorioPreparo(processos=3, transcricoes=1)
        self.assertEqual(rel.resumo, "3 processos, 1 transcrição")
        self.assertNotIn("não compartilhe", rel.resumo)
        rel.sigilosos_no_acervo = [Path("Processos", "Lote 1", f"{X}.pdf")]
        rel.erros = ["frase dos autos presos"]
        self.assertEqual(rel.resumo, "3 processos, 1 transcrição, 1 arquivo com problema, "
                                     "autos de 1 processo sigiloso presos no acervo; não "
                                     "compartilhe")
        rel.sigilosos_no_acervo.append(Path("Processos", "Lote 2", f"{X}.pdf"))
        self.assertTrue(rel.resumo.endswith(
            ", 2 autos de processo sigiloso presos no acervo; não compartilhe"), rel.resumo)
        # o resto que ficou (a minuta aberta) continua só avisado, sem a trava
        so_aviso = preparo.RelatorioPreparo(sigilosos_avisos=[Path("Minutas", "x.docx")])
        self.assertIn("1 arquivo de processo sigiloso ficou no acervo", so_aviso.resumo)
        self.assertNotIn("não compartilhe", so_aviso.resumo)


class TestIncidenteDoSigiloso(BaseSigilo):
    """O incidente ("...0001-01") herda o sigilo do principal; o principal não
    fica sigiloso por causa de um incidente."""

    def test_regra(self):
        inc = cnj.ler_nome_arquivo(f"{X}-01")
        cfg = mock.Mock(pasta_sigilosos=self.sig)
        self.assertFalse(sigilo.processo_sigiloso(cfg, inc))
        _pdf(self.sig / "Lote 1" / f"{X}.pdf", ["SEGREDO"])
        self.assertTrue(sigilo.na_pasta(self.sig, inc))
        self.assertTrue(sigilo.na_pasta(self.sig, f"{X}/01"))
        self.assertEqual(sigilo.motivo(cfg, inc), sigilo.MOTIVO_PASTA_PRINCIPAL)
        self.assertEqual(sigilo.motivo(cfg, X), sigilo.MOTIVO_PASTA)
        chaves = sigilo.chaves_sigilosas(self.sig, pauta=None)
        self.assertIn(f"{X}-01", chaves)
        self.assertIn(f"{X}-12", chaves)
        self.assertNotIn(Y, chaves)
        # o contrário não: o incidente sigiloso não torna sigiloso o principal
        (self.sig / "Lote 1" / f"{X}.pdf").unlink()
        _pdf(self.sig / "Lote 1" / f"{Y}-01.pdf", ["SEGREDO"])
        self.assertFalse(sigilo.na_pasta(self.sig, Y))
        self.assertTrue(sigilo.na_pasta(self.sig, f"{Y}-01"))
        # pela pauta
        self.marcar_na_pauta(X)
        self.assertTrue(sigilo.na_pauta(f"{X}-01"))
        self.assertEqual(sigilo.motivo(cfg, f"{X}-01"), sigilo.MOTIVO_PAUTA_PRINCIPAL)

    def test_tela_da_audiencia_diz_que_o_sigilo_vem_do_principal(self):
        from helestron.servidor import audiencia

        app = mock.Mock(cfg=self.cfg)
        app.pauta_ou_none.return_value = None
        inc = cnj.ler(f"{X}/01")
        self.assertEqual(audiencia.sigilo_conhecido(app, inc), "")
        self.marcar_na_pauta(X)
        self.assertEqual(audiencia.sigilo_conhecido(app, inc), audiencia.MOTIVO_PAUTA_PRINCIPAL)
        _pdf(self.sig / "Lote 1" / f"{X}.pdf", ["SEGREDO"])
        self.assertEqual(audiencia.sigilo_conhecido(app, inc), audiencia.MOTIVO_AUTOS_PRINCIPAL)
        self.assertEqual(audiencia.sigilo_conhecido(app, cnj.ler(X)), audiencia.MOTIVO_AUTOS)
        # e a transcrição do incidente vai para a pasta dos sigilosos
        from helestron.transcricao import documento

        self.assertEqual(documento.pasta_das_transcricoes(self.cfg, inc),
                         self.sig / "Transcricoes")

    def test_incidente_sai_do_acervo_do_indice_do_conector_e_da_nuvem(self):
        _pdf(self.lote / f"{X}.pdf", ["SEGREDO do principal"])
        _pdf(self.lote / f"{X}-01.pdf", ["Cumprimento de sentença - alimentos"])
        _docx(self.acervo / "Transcricoes" / f"{X}-01.docx", ["AUDIÊNCIA DO INCIDENTE"])
        nuvem_dir = self.base / "Nuvem"
        _pdf(nuvem_dir / nuvem.SUBPASTA / "Processos" / "Lote 1" / f"{X}-01.pdf", ["antigo"])
        self.marcar_na_pauta(X)
        ac = mcp_servidor.Acervo(self.acervo, sigilosos=self.sig)
        self.assertEqual(set(ac.pdfs()), {Y}, "o conector serve o incidente do sigiloso")
        self.assertEqual(set(ac.transcricoes()), set())
        with self.assertRaises(LookupError):
            ac.ler_processo(f"{X}/01")
        self.preparar()
        self.assertNotIn(X, (self.acervo / "INDICE.md").read_text(encoding="utf-8"))
        self.nada_de_x_no_acervo()
        self.assertTrue((self.sig / "Lote 1" / f"{X}-01.pdf").exists())
        self.assertTrue((self.sig / "Transcricoes" / f"{X}-01.docx").exists())
        nuvem.espelhar(self.acervo, nuvem_dir, sigilosos=self.sig)
        self.assertEqual(list(nuvem_dir.rglob(f"{X}*")), [])
        self.assertTrue(list(nuvem_dir.rglob(f"{Y}.pdf")))


class TestRestosDoSigiloso(BaseSigilo):
    """Levados os autos do sigiloso, a minuta em Produtos/ vai junto e o número
    dele sai do relatório do lote no acervo (a linha completa fica no
    relatório do lote na pasta dos sigilosos), como no download."""

    def test_minuta_em_produtos_e_relatorio_do_lote(self):
        from helestron.download import motor
        from testes import apoio_download as apoio

        x, y = cnj.ler(X), cnj.ler(Y)
        (self.lote / f"{Y}.pdf").unlink()
        fp, fn = apoio.fabricas()
        opcoes = apoio.opcoes_de_teste(self.base, pasta_sigilosos=self.sig)
        resumo = motor.executar([x, y], self.lote, opcoes, apoio.ContextoGravador(),
                                fabrica_portal=fp, fabrica_navegador=fn, cfg=self.cfg)
        self.assertEqual([r.situacao for r in resumo.itens], ["OK", "OK"])
        relatorio = self.lote / "_controle" / "relatorio.csv"
        self.assertIn(X, relatorio.read_text(encoding="utf-8-sig"))
        produto = self.acervo / "Produtos" / f"{X} - relatório.md"
        produto.parent.mkdir(parents=True, exist_ok=True)
        produto.write_text("Relatório: Fulano x Beltrana, guarda do menor", encoding="utf-8")

        self.marcar_na_pauta(X)
        rel = self.preparar()
        self.assertEqual(rel.sigilosos_levados, 1)
        self.assertFalse(produto.exists(), "a minuta do sigiloso continua em Produtos/")
        self.assertTrue((self.sig / "Produtos" / f"{X} - relatório.md").exists())
        self.nada_de_x_no_acervo()
        # o relatório do lote no acervo não traz mais o número
        texto = relatorio.read_text(encoding="utf-8-sig")
        self.assertNotIn(X, texto)
        linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
        self.assertEqual([l["processo"] for l in linhas], [motor.MASCARA_SIGILOSO, Y])
        self.assertEqual(linhas[0]["sigiloso"], "sim")
        self.assertEqual(linhas[0]["arquivo"], "")
        # a linha completa, na pasta dos sigilosos
        completo = self.sig / "Lote 1" / "_controle" / "relatorio.csv"
        cheias = list(csv.DictReader(io.StringIO(completo.read_text(encoding="utf-8-sig")),
                                     delimiter=";"))
        self.assertEqual([l["processo"] for l in cheias], [X, Y])
        self.assertEqual(cheias[0]["sigiloso"], "sim")
        self.assertIn("(na pasta de sigilosos)", cheias[0]["arquivo"])
        self.assertTrue(any("relatório do lote “Lote 1”" in a for a in rel.avisos), rel.avisos)
        # "Tentar de novo" no mesmo lote: o motor reconhece a linha mascarada
        lote = motor._Lote([y], self.lote, opcoes, apoio.ContextoGravador(), {}, None,
                           fp, fn, self.cfg)
        self.assertIn(X, {c for c, _ in lote._linhas_anteriores})
        self.assertIn(X, lote._sigilosos_sabidos)
        # e um segundo preparo não muda nada
        antes = relatorio.read_bytes()
        rel = self.preparar()
        self.assertEqual((rel.sigilosos_levados, rel.avisos), (0, []))
        self.assertEqual(relatorio.read_bytes(), antes)

    def test_relatorio_aberto_no_excel_so_avisa(self):
        from helestron.download import motor

        controle = self.lote / "_controle"
        controle.mkdir(parents=True)
        (controle / "relatorio.csv").write_text(
            "\ufeff" + ";".join(motor.COLUNAS) + "\r\n"
            f"1;{X};TJAL;esaj;OK;2;1;{X}.pdf;não;;;2026-10-01 10:00\r\n", encoding="utf-8")
        original = motor._gravar_relatorio

        def excel(arquivo, linhas):
            if Path(arquivo).parent == controle:
                raise PermissionError(13, "aberto no Excel")
            return original(arquivo, linhas)

        self.marcar_na_pauta(X)
        with mock.patch.object(motor, "_gravar_relatorio", excel), \
                self.assertLogs("compartilhar", "WARNING"):
            rel = self.preparar()
        self.assertEqual(rel.sigilosos_no_acervo, [])
        self.assertEqual(rel.sigilosos_avisos, [controle / "relatorio.csv"])
        frase = " ".join(rel.avisos)
        self.assertIn("que ainda traz o número dele (está aberto no Excel?)", frase)

    def test_completo_aberto_no_excel_avisa_o_relatorio_do_acervo(self):
        """Achado X10: com o relatório COMPLETO do lote (o da pasta dos
        sigilosos) aberto no Excel, o número não sai do relatório do lote no
        acervo. O aviso nomeia esse, que está no acervo e traz o número - não
        o completo, que fica fora dele e não é pendência do acervo (nem no
        preparo, nem no "Tentar de novo" da tela Compartilhar)."""
        from helestron.download import motor

        controle = self.lote / "_controle"
        controle.mkdir(parents=True)
        do_acervo = controle / "relatorio.csv"
        do_acervo.write_text(
            "﻿" + ";".join(motor.COLUNAS) + "\r\n"
            f"1;{X};TJAL;esaj;OK;2;1;{X}.pdf;não;;;2026-10-01 10:00\r\n", encoding="utf-8")
        completo = self.sig / "Lote 1" / "_controle" / "relatorio.csv"
        completo.parent.mkdir(parents=True)
        completo.write_text("﻿" + ";".join(motor.COLUNAS) + "\r\n", encoding="utf-8")
        original = motor._gravar_relatorio

        def excel(arquivo, linhas):
            if Path(arquivo) == completo:
                raise PermissionError(13, "aberto no Excel", str(arquivo))
            return original(arquivo, linhas)

        self.marcar_na_pauta(X)
        with mock.patch.object(motor, "_gravar_relatorio", excel), \
                self.assertLogs("compartilhar", "WARNING"):
            rel = self.preparar()
            ret = motor.retirar_do_acervo(self.cfg, X)
        self.assertIn(X, do_acervo.read_text(encoding="utf-8-sig"), "o número ficou no acervo")
        self.assertEqual(rel.sigilosos_avisos, [do_acervo])
        frase = " ".join(rel.avisos)
        self.assertIn(f"{Path('Processos', 'Lote 1', '_controle', 'relatorio.csv')}, que ainda "
                      "traz o número dele (o relatório completo do lote, na pasta dos sigilosos, "
                      "não pôde ser atualizado: está aberto em outro programa?)", frase)
        self.assertNotIn(str(self.sig), frase)
        # o "Tentar de novo" (api_compartilhar) registra o que a retirada
        # avisa: o relatório do lote no acervo, com o porquê - não o completo
        # (achado Y1)
        self.assertEqual(ret.avisam, [do_acervo])
        self.assertEqual(ret.motivos[do_acervo], "o relatório completo do lote, na pasta dos "
                         "sigilosos, não pôde ser atualizado: está aberto em outro programa?")
        self.assertEqual(ret.completos_presos, {completo: [do_acervo]})

    def test_tentar_de_novo_avisa_o_relatorio_do_lote_com_o_completo_preso(self):
        """Achado Y1: o "Tentar de novo" da tela Compartilhar (antes do Claude
        Desktop, do pacote e do espelho) leva os autos de X, que estavam
        presos no acervo, mas o relatório completo do lote está aberto no
        Excel: o relatório do lote, no acervo, continua com o número de X e
        passa a ser pendência (o Início), com o porquê - como na 1.0.2."""
        from types import SimpleNamespace

        from helestron.download import motor
        from helestron.servidor import api_compartilhar

        controle = self.lote / "_controle"
        controle.mkdir(parents=True)
        do_acervo = controle / "relatorio.csv"
        do_acervo.write_text(
            "﻿" + ";".join(motor.COLUNAS) + "\r\n"
            f"1;{X};TJAL;esaj;OK;2;1;{X}.pdf;não;;;2026-10-01 10:00\r\n", encoding="utf-8")
        pdf = _pdf(self.lote / f"{X}.pdf", ["Petição inicial do sigiloso"])
        completo = self.sig / "Lote 1" / "_controle" / "relatorio.csv"
        original = motor._gravar_relatorio

        def excel(arquivo, linhas):
            if Path(arquivo) == completo:
                raise PermissionError(13, "aberto no Excel", str(arquivo))
            return original(arquivo, linhas)

        self.marcar_na_pauta(X)
        app = SimpleNamespace(cfg=self.cfg, sigilosos_presos=[pdf], sigilosos_avisos=[],
                              sigilosos_motivos={pdf: "está aberto em outro programa?"})
        with mock.patch.object(motor, "_gravar_relatorio", excel):
            api_compartilhar.exigir_sem_sigiloso(app)      # os autos saíram agora
        self.assertFalse(pdf.exists())
        self.assertEqual(app.sigilosos_presos, [])
        self.assertIn(X, do_acervo.read_text(encoding="utf-8-sig"), "o número ficou no acervo")
        self.assertEqual(app.sigilosos_avisos, [do_acervo])
        self.assertEqual(app.sigilosos_motivos[do_acervo], "o relatório completo do lote, na "
                         "pasta dos sigilosos, não pôde ser atualizado: está aberto em outro "
                         "programa?")


class TestSeparacaoDesligada(BaseSigilo):
    """Achado R19: com a separação dos sigilosos desligada, o processo que o
    portal mostrou em segredo de justiça fica no acervo - e ia para o índice,
    o _ia/texto, o conector e a nuvem, porque a regra única não sabia dele."""

    def test_sigiloso_do_portal_fica_fora_do_indice_do_texto_do_conector_e_da_nuvem(self):
        from helestron.download import motor
        from testes import apoio_download as apoio

        x, y = cnj.ler(X), cnj.ler(Y)
        (self.lote / f"{Y}.pdf").unlink()
        self.cfg.definir("download", "separar_sigilosos", False)
        fp, fn = apoio.fabricas({X: ["ok_sigiloso"]})
        opcoes = apoio.opcoes_de_teste(self.base, pasta_sigilosos=self.sig,
                                       separar_sigilosos=False)
        resumo = motor.executar([x, y], self.lote, opcoes, apoio.ContextoGravador(),
                                fabrica_portal=fp, fabrica_navegador=fn, cfg=self.cfg)
        self.assertEqual([(r.situacao, r.sigiloso) for r in resumo.itens],
                         [("OK", True), ("OK", False)])
        self.assertTrue((self.lote / f"{X}.pdf").exists(), "desligada, a separação não move")
        # a regra única sabe, e diz por quê
        self.assertTrue(sigilo.processo_sigiloso(self.cfg, x))
        self.assertEqual(sigilo.motivo(self.cfg, x), sigilo.MOTIVO_DOWNLOAD)
        self.assertEqual(sigilo.motivo(self.cfg, f"{X}-01"), sigilo.MOTIVO_DOWNLOAD_PRINCIPAL)
        self.assertFalse(sigilo.processo_sigiloso(self.cfg, y))
        # a audiência dele é sigilosa, e a tela diz por quê
        from helestron.servidor import audiencia
        from helestron.transcricao import documento

        app = mock.Mock(cfg=self.cfg)
        app.pauta_ou_none.return_value = None
        self.assertEqual(audiencia.sigilo_conhecido(app, x), audiencia.MOTIVO_DOWNLOAD)
        self.assertEqual(audiencia.sigilo_conhecido(app, cnj.ler(f"{X}/01")),
                         audiencia.MOTIVO_DOWNLOAD_PRINCIPAL)
        self.assertEqual(audiencia.sigilo_conhecido(app, y), "")
        self.assertEqual(documento.pasta_das_transcricoes(self.cfg, x), self.sig / "Transcricoes")
        # o preparo, o conector e a nuvem o deixam de fora
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertEqual(rel.processos, 1)
        self.assertFalse((self.acervo / "_ia" / "texto" / f"{X}.txt").exists())
        self.assertTrue((self.acervo / "_ia" / "texto" / f"{Y}.txt").exists())
        self.assertNotIn(X, (self.acervo / "INDICE.md").read_text(encoding="utf-8"))
        ac = mcp_servidor.Acervo(self.acervo, sigilosos=self.sig)
        self.assertEqual(set(ac.pdfs()), {Y})
        nuvem_dir = self.base / "Nuvem"
        nuvem_dir.mkdir()
        nuvem.espelhar(self.acervo, nuvem_dir, sigilosos=self.sig)
        self.assertEqual(list(nuvem_dir.rglob(f"{X}*")), [])
        self.assertTrue(list(nuvem_dir.rglob(f"{Y}.pdf")))

    def test_lote_de_antes_do_registro_fica_fora_de_tudo(self):
        """Achado V2: o lote baixado com a separação desligada ANTES do
        registro do download (a versão anterior), ou com ele perdido (a pasta
        LOCAL apagada pela desinstalação, o acervo levado para outro
        computador): o relatório do lote diz sigiloso=sim, mas o índice, o
        texto para a IA, o conector, o pacote e a nuvem o tratavam como
        público."""
        from helestron.download import motor
        from testes import apoio_download as apoio

        x, y = cnj.ler(X), cnj.ler(Y)
        (self.lote / f"{Y}.pdf").unlink()
        self.cfg.definir("download", "separar_sigilosos", False)
        fp, fn = apoio.fabricas({X: ["ok_sigiloso"]})
        opcoes = apoio.opcoes_de_teste(self.base, pasta_sigilosos=self.sig,
                                       separar_sigilosos=False)
        motor.executar([x, y], self.lote, opcoes, apoio.ContextoGravador(),
                       fabrica_portal=fp, fabrica_navegador=fn, cfg=self.cfg)
        self.assertTrue((self.lote / f"{X}.pdf").exists())
        sigilo.arquivo_do_download().unlink()        # a versão anterior não o gravava
        sigilo.esquecer_pauta()
        self.assertFalse(sigilo.processo_sigiloso(self.cfg, x))
        # o preparo, o índice, o conector, a nuvem e o pacote o deixam de fora
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertEqual(rel.processos, 1)
        self.assertFalse((self.acervo / "_ia" / "texto" / f"{X}.txt").exists())
        self.assertTrue((self.acervo / "_ia" / "texto" / f"{Y}.txt").exists())
        self.assertNotIn(X, (self.acervo / "INDICE.md").read_text(encoding="utf-8"))
        ac = mcp_servidor.Acervo(self.acervo, sigilosos=self.sig)
        self.assertEqual(set(ac.pdfs()), {Y})
        self.assertNotIn(X, ac.listar_acervo())
        nuvem_dir = self.base / "Nuvem"
        nuvem_dir.mkdir()
        nuvem.espelhar(self.acervo, nuvem_dir, sigilosos=self.sig)
        self.assertEqual(list(nuvem_dir.rglob(f"{X}*")), [])
        self.assertTrue(list(nuvem_dir.rglob(f"{Y}.pdf")))
        import zipfile
        pacote = chatgpt.gerar_pacote(self.acervo, self.base / "Pacotes", cfg=self.cfg)
        with zipfile.ZipFile(pacote.arquivo_zip) as z:
            self.assertEqual([n for n in z.namelist() if X in n], [])
            self.assertTrue([n for n in z.namelist() if Y in n])
        # e o sigilo voltou ao registro do download, para o resto do programa
        self.assertEqual(sigilo.apuradas_no_download(), {X})
        self.assertEqual(sigilo.motivo(self.cfg, x), sigilo.MOTIVO_DOWNLOAD)
        from helestron.transcricao import documento
        self.assertEqual(documento.pasta_das_transcricoes(self.cfg, x), self.sig / "Transcricoes")


class TestBuscarNumAcervoGrande(unittest.TestCase):
    """'buscar' sem número: a listagem do acervo e a regra do sigilo uma vez
    por pedido, e não uma vez por processo (O(N²))."""

    def test_uma_listagem_e_uma_regra_por_pedido(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp) / "Acervo"
            modelo = _pdf(Path(tmp) / "modelo.pdf", ["usucapião extraordinária"])
            for i in range(30):
                destino = raiz / "Processos" / "Lote 1" / f"{_num(2000 + i)}.pdf"
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(modelo.read_bytes())
            servidor = mcp_servidor.Servidor(mcp_servidor.Acervo(raiz, sigilosos=None))
            regra = mock.Mock(wraps=mcp_servidor.chaves_sigilosas)
            listar = mock.Mock(wraps=mcp_servidor.Acervo._listar)
            with mock.patch.object(mcp_servidor, "chaves_sigilosas", regra), \
                    mock.patch.object(mcp_servidor.Acervo, "_listar",
                                      lambda self, sufixo: listar(self, sufixo)):
                resposta = servidor.tratar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                            "params": {"name": "buscar",
                                                       "arguments": {"termo": "usucapião"}}})
            texto = resposta["result"]["content"][0]["text"]
            self.assertEqual(texto.count("usucapião"), 30)
            self.assertEqual(regra.call_count, 1, "a regra do sigilo foi reaplicada por processo")
            self.assertEqual(sorted(c.args[1] for c in listar.call_args_list), [".docx", ".pdf"])
            # fora de um pedido, nada fica guardado: o próximo vê o acervo de agora
            (raiz / "Processos" / "Lote 1" / f"{_num(2000)}.pdf").unlink()
            resposta = servidor.tratar({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": "buscar",
                                                   "arguments": {"termo": "usucapião"}}})
            self.assertEqual(resposta["result"]["content"][0]["text"].count("usucapião"), 29)


class TestRestosDaVersaoAnterior(unittest.TestCase):
    """O conector da versão anterior (Assessor Integrado) sai na desinstalação
    e na limpeza que o instalador chama, com cópia dos arquivos."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.json = self.base / "Claude" / "claude_desktop_config.json"
        self.json.parent.mkdir()
        velho = {"command": "C:/AssessorIntegrado/runtime/python/python.exe", "args": []}
        self.json.write_text(json.dumps({"mcpServers": {
            "assessor-integrado": velho, "assessor_integrado": velho,
            "helestron": {"command": "python.exe", "args": []}, "outro": {"command": "x"}}}),
            encoding="utf-8")
        self.toml = self.base / ".codex" / "config.toml"
        self.toml.parent.mkdir()
        self.toml.write_text('model = "x"\n\n[mcp_servers.assessor_integrado]\ncommand = "v"\n'
                             '[mcp_servers.assessor_integrado.env]\nA = "1"\n\n'
                             '[mcp_servers.assessor-integrado]\ncommand = "v"\n\n'
                             '[mcp_servers.helestron]\ncommand = "h"\n\n'
                             '[mcp_servers.outro]\ncommand = "y"\n', encoding="utf-8")

    def servidores_json(self) -> set[str]:
        return set(json.loads(self.json.read_text(encoding="utf-8"))["mcpServers"])

    def servidores_toml(self) -> set[str]:
        return set(tomllib.loads(self.toml.read_text(encoding="utf-8"))["mcp_servers"])

    def test_desinstalar_tira_o_helestron_e_os_antigos(self):
        self.assertEqual(claude.remover_mcp([self.json]), [self.json])
        self.assertEqual(self.servidores_json(), {"outro"})
        self.assertTrue(list(self.json.parent.glob("*antes-do-helestron*")))
        self.assertTrue(chatgpt.remover_mcp_codex(self.toml))
        self.assertEqual(self.servidores_toml(), {"outro"})
        copias = list(self.toml.parent.glob("config.antes-do-helestron-*.toml"))
        self.assertEqual(len(copias), 1, "o config.toml foi alterado sem cópia")
        self.assertIn("assessor_integrado", copias[0].read_text(encoding="utf-8"))

    def test_limpar_restos_antigos_so_tira_os_antigos(self):
        from helestron import compartilhar
        from helestron.compartilhar import migracao

        with mock.patch.object(claude, "arquivos_config_desktop", return_value=[self.json]), \
                mock.patch.object(chatgpt, "arquivo_config_codex", return_value=self.toml):
            feito = compartilhar.limpar_restos_antigos()
            self.assertEqual(len(feito), 2, feito)
            self.assertEqual(self.servidores_json(), {"helestron", "outro"})
            self.assertEqual(self.servidores_toml(), {"helestron", "outro"})
            self.assertEqual(tomllib.loads(self.toml.read_text(encoding="utf-8"))["model"], "x")
            self.assertEqual(len(list(self.json.parent.glob("*antes-do-helestron*"))), 1)
            self.assertEqual(len(list(self.toml.parent.glob("config.antes-do-helestron-*"))), 1)
            # de novo: nada a fazer, nenhuma cópia nova
            self.assertEqual(compartilhar.limpar_restos_antigos(), [])
            self.assertEqual(len(list(self.json.parent.glob("*antes-do-helestron*"))), 1)
            # a linha de comando do instalador sai sempre com 0
            saida = io.StringIO()
            with mock.patch("sys.stdout", saida):
                self.assertEqual(migracao.main([]), 0)
            self.assertIn("Nada da versão anterior a limpar.", saida.getvalue())

    def test_reapontar_conectores_da_instalacao_que_mudou_de_pasta(self):
        from helestron.compartilhar import migracao

        acervo = str(self.base / "Acervo")
        antigo = {"command": "C:/Velha/Helestron/python.exe",
                  "args": ["-I", "-m", "helestron", "mcp", "--pasta", acervo]}
        self.json.write_text(json.dumps({"mcpServers": {"helestron": antigo, "outro": {"command": "x"}},
                                         "preferencias": {"y": 2}}), encoding="utf-8")
        self.toml.write_text('model = "x"\n\n[mcp_servers.helestron]\n'
                             "command = 'C:/Velha/Helestron/python.exe'\n"
                             f"args = ['-I', '-m', 'helestron', 'mcp', '--pasta', '{acervo}']\n\n"
                             '[mcp_servers.outro]\ncommand = "y"\n', encoding="utf-8")
        with mock.patch.object(claude, "arquivos_config_desktop", return_value=[self.json]), \
                mock.patch.object(chatgpt, "arquivo_config_codex", return_value=self.toml):
            # fora da instalação, nada muda
            self.assertEqual(migracao.reapontar_conectores(), [])
            feito = migracao.reapontar_conectores(forcar=True)
            self.assertEqual(len(feito), 2, feito)
            esperada = claude.entrada_mcp(Path(acervo))
            dados = json.loads(self.json.read_text(encoding="utf-8"))
            self.assertEqual(dados["mcpServers"]["helestron"], esperada)
            self.assertEqual(dados["mcpServers"]["outro"], {"command": "x"})
            self.assertEqual(dados["preferencias"], {"y": 2})
            codex = tomllib.loads(self.toml.read_text(encoding="utf-8"))
            self.assertEqual(codex["mcp_servers"]["helestron"]["command"], esperada["command"])
            self.assertIn(str(Path(acervo).resolve()), codex["mcp_servers"]["helestron"]["args"])
            self.assertEqual(codex["model"], "x")
            self.assertIn("outro", codex["mcp_servers"])
            # de novo: já aponta para esta instalação, nada a fazer
            self.assertEqual(migracao.reapontar_conectores(forcar=True), [])

    def test_reapontar_mantem_o_conector_desligado_e_as_outras_chaves(self):
        """O bloco do Codex era reescrito inteiro, com 'enabled = true': o
        conector que o usuário desligou (para o ChatGPT não ler o acervo)
        voltava ligado depois da instalação, sem aviso."""
        from helestron.compartilhar import migracao

        acervo = str(self.base / "Acervo")
        self.json.write_text("{}", encoding="utf-8")
        self.toml.write_text('model = "x"\n\n[mcp_servers.helestron]\n'
                             "command = 'C:/Velha/Helestron/python.exe'\n"
                             f"args = ['-I', '-m', 'helestron', 'mcp', '--pasta', '{acervo}']\n"
                             "enabled = false\n"
                             "startup_timeout_sec = 30\n"
                             "tool_timeout_sec = 120.5\n"
                             "disabled_tools = ['buscar', \"ler 'pagina'\"]\n"
                             '"chave com espaço" = 1\n\n'
                             "[mcp_servers.helestron.env]\nHTTPS_PROXY = 'http://proxy:8080'\n\n"
                             "[mcp_servers.helestron.tools.ler_pagina]\napproval = 'approve'\n\n"
                             '[mcp_servers.outro]\ncommand = "y"\n', encoding="utf-8")
        with mock.patch.object(claude, "arquivos_config_desktop", return_value=[self.json]), \
                mock.patch.object(chatgpt, "arquivo_config_codex", return_value=self.toml), \
                mock.patch.object(caminhos, "INSTALADO", True):
            feito = migracao.reapontar_conectores()
            self.assertEqual(len(feito), 1, feito)
            esperada = claude.entrada_mcp(Path(acervo))
            codex = tomllib.loads(self.toml.read_text(encoding="utf-8"))
            bloco = codex["mcp_servers"]["helestron"]
            self.assertEqual(bloco.pop("command"), esperada["command"])
            self.assertEqual(bloco.pop("args"), esperada["args"])
            self.assertEqual(bloco, {"enabled": False, "startup_timeout_sec": 30,
                                     "tool_timeout_sec": 120.5,
                                     "disabled_tools": ["buscar", "ler 'pagina'"],
                                     "chave com espaço": 1,
                                     "env": {"HTTPS_PROXY": "http://proxy:8080"},
                                     "tools": {"ler_pagina": {"approval": "approve"}}})
            self.assertEqual(codex["mcp_servers"]["outro"], {"command": "y"})
            self.assertEqual(codex["model"], "x")
            self.assertEqual(migracao.reapontar_conectores(), [])
            # o "Conectar" da tela é o usuário pedindo: liga
            chatgpt.registrar_mcp_codex(Path(acervo), self.toml)
            codex = tomllib.loads(self.toml.read_text(encoding="utf-8"))
            self.assertIs(codex["mcp_servers"]["helestron"]["enabled"], True)

    def test_arquivo_invalido_nao_e_tocado(self):
        self.json.write_text("{ isto não é json", encoding="utf-8")
        self.toml.write_text("[mcp_servers.assessor_integrado\ncommand = ", encoding="utf-8")
        with mock.patch.object(claude, "arquivos_config_desktop", return_value=[self.json]), \
                mock.patch.object(chatgpt, "arquivo_config_codex", return_value=self.toml):
            from helestron.compartilhar import migracao

            with self.assertLogs("compartilhar", "WARNING"):
                self.assertEqual(migracao.limpar_restos_antigos(), [])
        self.assertEqual(self.json.read_text(encoding="utf-8"), "{ isto não é json")
        self.assertIn("assessor_integrado", self.toml.read_text(encoding="utf-8"))


class TestRegistroDoConector(unittest.TestCase):
    """Achado W9 da terceira verificação do 2º grau: o conector MCP só mandava
    o registro para o stderr, que o Claude Desktop guarda à parte. Quando era
    ele o primeiro a aplicar a regra do sigilo depois de a origem de um HC
    virar sigilosa, o aviso "originário … tratado como sigiloso", dado uma vez
    só, nunca chegava a %LOCALAPPDATA%\\Helestron\\Logs, onde o manual manda
    procurá-lo para desfazer uma marcação por engano. Agora vai também para
    Logs, e o stdout, o canal do protocolo, continua só com o JSON-RPC.

    Achados X9 e X12 da quarta verificação: o arquivo de Logs ficava aberto
    enquanto o Claude Desktop mantinha o conector vivo, e o desinstalador que
    apaga as configurações não conseguia apagá-lo no Windows. Agora o
    conector o abre e fecha a cada registro.

    Achado Y3 da quinta verificação: com o disco cheio, o erro do fechamento
    saía do log.warning, e a regra do sigilo dava a pasta dos sigilosos por
    vazia."""

    def cenario(self):
        """O HC no acervo, com a origem sigilosa pela pasta: o conector o tira
        do acervo e avisa uma vez (env, acervo, Logs, aviso, mensagens)."""
        import os

        from testes.test_sigilo import _capa_2g, _originario

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        casa = Path(tmp.name)
        local, dados = casa / "local", casa / "dados"
        acervo, lote = dados / "Acervo", dados / "Acervo" / "Processos" / "Gabinete"
        origem, self.hc = cnj.ler(X), _originario("0803001")
        _pdf(lote / f"{cnj.nome_dos_autos(self.hc, '2g')}.pdf", ["Habeas corpus"])
        _capa_2g(lote / "_controle", self.hc, origem)
        _pdf(dados / "Sigilosos" / "Outro lote" / f"{origem.nome_arquivo}.pdf", ["Em segredo"])
        env = dict(os.environ, HELESTRON_LOCAL=str(local), HELESTRON_DADOS=str(dados),
                   HOME=str(casa), APPDATA=str(casa), LOCALAPPDATA=str(casa))
        mensagens = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "listar_acervo", "arguments": {}}},
        ]
        aviso = (f"originário {self.hc.nome_arquivo} tratado como sigiloso: o processo de "
                 f"origem {origem.nome_arquivo} é sigiloso")
        return env, acervo, local / "Logs", aviso, mensagens

    def test_aviso_do_originario_vai_para_logs_e_o_stdout_so_tem_o_protocolo(self):
        import subprocess
        import sys

        env, acervo, logs, aviso, mensagens = self.cenario()
        hc = self.hc
        r = subprocess.run(
            [sys.executable, "-m", "helestron", "mcp", "--pasta", str(acervo)],
            input="".join(json.dumps(m) + "\n" for m in mensagens).encode(),
            capture_output=True, cwd=str(Path(__file__).resolve().parents[1]), env=env,
            timeout=120)
        erros = r.stderr.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, erros)
        # o stdout: só as respostas, uma por linha, todas JSON-RPC
        saida = r.stdout.decode("utf-8")
        respostas = [json.loads(linha) for linha in saida.splitlines()]
        self.assertEqual([(x["jsonrpc"], x["id"]) for x in respostas], [("2.0", 1), ("2.0", 2)])
        self.assertIn("result", respostas[1], erros)
        self.assertNotIn(hc.nome_arquivo, saida, "o HC saiu do acervo do conector")
        self.assertIn(aviso, erros)
        # e o aviso também no registro do programa, em Logs
        registros = sorted(logs.glob("*.log"))
        self.assertEqual(len(registros), 1, erros)
        self.assertIn(aviso, registros[0].read_text(encoding="utf-8"))

    def test_logs_nao_fica_aberto_enquanto_o_conector_espera(self):
        # O conector de verdade, vivo como o Claude Desktop o deixa: depois do
        # aviso, à espera da próxima mensagem, não segura nenhum arquivo de
        # Logs (no Linux, os abertos estão em /proc/<pid>/fd).
        import os
        import subprocess
        import sys
        import threading

        if not Path(f"/proc/{os.getpid()}/fd").is_dir():
            self.skipTest("sem /proc para ver os arquivos abertos pelo conector")
        env, acervo, logs, aviso, mensagens = self.cenario()
        erros = logs.parent.parent / "stderr.txt"
        with open(erros, "wb") as stderr:
            conector = subprocess.Popen(
                [sys.executable, "-m", "helestron", "mcp", "--pasta", str(acervo)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                cwd=str(Path(__file__).resolve().parents[1]), env=env)
        relogio = threading.Timer(120, conector.kill)
        relogio.start()
        try:
            conector.stdin.write("".join(json.dumps(m) + "\n" for m in mensagens).encode())
            conector.stdin.flush()
            respostas = [json.loads(conector.stdout.readline()) for _ in range(2)]
            abertos = []
            for fd in Path(f"/proc/{conector.pid}/fd").iterdir():
                try:
                    abertos.append(os.readlink(fd))
                except OSError:
                    pass
        finally:
            relogio.cancel()
            conector.stdin.close()
            conector.stdout.close()
            conector.wait(timeout=60)
        texto = erros.read_text(encoding="utf-8", errors="replace")
        self.assertEqual([x["id"] for x in respostas], [1, 2], texto)
        self.assertEqual(conector.returncode, 0, texto)
        registros = sorted(logs.glob("*.log"))
        self.assertEqual(len(registros), 1, texto)
        self.assertIn(aviso, registros[0].read_text(encoding="utf-8"))
        pasta = os.path.realpath(logs)
        self.assertEqual([a for a in abertos if a.startswith(pasta)], [],
                         "o conector segura o registro do programa")

    def test_registro_do_conector_fecha_o_arquivo_e_censura(self):
        # O mesmo no processo do teste (vale também no Windows): depois de cada
        # registro, nenhum arquivo aberto; o formato e o filtro dos segredos de
        # registro.py; e o mês de cada registro, não o da partida.
        import logging
        from datetime import datetime

        raiz = logging.getLogger()
        antes, nivel = list(raiz.handlers), raiz.level

        def restaurar():
            for h in raiz.handlers:
                if h not in antes:
                    h.close()
            raiz.handlers[:] = antes
            raiz.setLevel(nivel)
        self.addCleanup(restaurar)
        raiz.handlers[:] = []          # o conector liga o registro só se não houver
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        logs = Path(tmp.name) / "Logs"
        abertos = []

        def servir(pasta, saida=None):
            for mes in (1, 2):
                agora = mock.Mock(now=lambda mes=mes: datetime(2001, mes, 28, 23, 59))
                with mock.patch.object(mcp_servidor, "datetime", agora, create=True):
                    logging.getLogger("mcp").warning(
                        "aviso %d: https://portal/abrir?ticket=ST-SEGREDO", mes)
                abertos.append([h.stream for h in raiz.handlers
                                if getattr(h, "_helestron", False)])

        with mock.patch.object(caminhos, "LOGS", logs), \
                mock.patch.object(mcp_servidor, "servir", side_effect=servir), \
                mock.patch.object(mcp_servidor.os, "dup2"), \
                mock.patch.object(mcp_servidor.sys, "stdout", io.StringIO()), \
                mock.patch.object(mcp_servidor.sys, "stderr", io.StringIO()):
            self.assertEqual(mcp_servidor.main(["--pasta", tmp.name]), 0)
        self.assertEqual(abertos, [[None], [None]])
        for mes in (1, 2):
            texto = (logs / f"2001-{mes:02d}.log").read_text(encoding="utf-8")
            self.assertRegex(texto, rf"^\S+ \S+  WARNING  mcp  aviso {mes}: "
                                    r"https://portal/abrir\?ticket=\*\*\*\n$")

    def test_disco_cheio_nao_faz_o_aviso_levantar_nem_esvaziar_os_sigilosos(self):
        # O disco cheio: o flush do registro falha, e o close() o refaz. A
        # pasta dos sigilosos grande dá o aviso "pastas demais" e a origem do
        # HC, o do originário; os dois avisos não levantam, e o sigiloso só
        # pela pasta (a cópia no acervo, o HC que herda dele) continua sigiloso.
        import errno
        import logging

        from testes.test_sigilo import _capa_2g, _originario

        class Cheio(io.StringIO):
            def flush(self):
                raise OSError(errno.ENOSPC, "No space left on device")

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        sig, lote = base / "Sigilosos", base / "Acervo" / "Processos" / "Lote 2"
        hc = _originario("0803001")
        _pdf(sig / "Lote X" / f"{X}.pdf", ["Em segredo"])
        _pdf(lote / f"{X}.pdf", ["A cópia que a separação deixou"])
        _pdf(lote / f"{cnj.nome_dos_autos(hc, '2g')}.pdf", ["Habeas corpus"])
        _capa_2g(lote / "_controle", hc, cnj.ler(X))
        for i in range(sigilo.MAX_PASTAS + 1):
            (sig / "Arquivo antigo" / f"{i // 50:02d}" / f"{i % 50:02d}").mkdir(parents=True)
        registro = mcp_servidor._RegistroAvulso(base / "Logs")
        raiz = logging.getLogger()
        self.addCleanup(raiz.setLevel, raiz.level)
        raiz.setLevel(logging.WARNING)            # o nível do conector
        raiz.addHandler(registro)
        self.addCleanup(raiz.removeHandler, registro)
        with mock.patch.object(registro, "_open", side_effect=Cheio), \
                mock.patch.object(sigilo, "_avisou_pasta_grande", set()), \
                mock.patch("sys.stderr", io.StringIO()) as erros:
            chaves = mcp_servidor.chaves_sigilosas(sig, base / "Acervo", pauta=None)
        self.assertIn(X, chaves)
        self.assertIn(hc.nome_arquivo, chaves)
        self.assertIn("pastas demais", erros.getvalue())
        self.assertIn("originário", erros.getvalue())
        self.assertIsNone(registro.stream)      # o próximo registro reabre o arquivo


if __name__ == "__main__":
    unittest.main()
