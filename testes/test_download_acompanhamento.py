"""O acompanhamento em JSON do download (baixar --json)."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest import mock

from helestron.download import acompanhamento, modelos

from testes import apoio_download as apoio

A = apoio.numero("0700001", tr="02")
B = apoio.numero("0700002", tr="02")


class TestAcompanhamento(apoio.PastaTemporaria):
    def ler(self, arq):
        return json.loads(Path(arq).read_text(encoding="utf-8"))

    def test_grava_ja_ao_comecar_e_limita_a_uma_vez_por_intervalo(self):
        arq = self.tmp / "sub" / "lote.json"
        acomp = acompanhamento.Acompanhamento(arq, intervalo=30)
        r = modelos.ResultadoProcesso(1, A.formatado, "TJAL", "esaj")
        acomp.item(r)                                 # a primeira grava na hora
        self.assertEqual(self.ler(arq)["processos"][0]["situacao"], "PENDENTE")
        r.situacao = modelos.OK
        acomp.item(r)                                 # dentro do intervalo: fica agendada
        self.assertEqual(self.ler(arq)["processos"][0]["situacao"], "PENDENTE")
        acomp.concluir(0)
        dados = self.ler(arq)
        self.assertTrue(dados["concluido"])
        self.assertEqual(dados["codigo_saida"], 0)
        self.assertEqual(dados["processos"][0]["situacao"], "OK")
        self.assertEqual(list(self.tmp.rglob("*.parcial")), [], "gravação atômica")
        acomp.item(r)                                 # depois de concluído, nada muda
        self.assertTrue(self.ler(arq)["concluido"])

    def test_agendada_grava_sozinha(self):
        arq = self.tmp / "lote.json"
        acomp = acompanhamento.Acompanhamento(arq, intervalo=0.2)
        r = modelos.ResultadoProcesso(1, A.formatado, "TJAL", "esaj")
        acomp.item(r)
        r.situacao = modelos.ERRO
        acomp.item(r)
        limite = time.monotonic() + 5
        while time.monotonic() < limite and self.ler(arq)["processos"][0]["situacao"] != "ERRO":
            time.sleep(0.05)
        self.assertEqual(self.ler(arq)["processos"][0]["situacao"], "ERRO")
        acomp.fechar()

    def test_aguardando_o_usuario(self):
        acomp = acompanhamento.Acompanhamento(None)
        acomp.evento("login_aguardando", sistema="eproc", tribunal="TJAL", motivo="captcha")
        self.assertEqual(acomp.dados()["aguardando"]["motivo"], "captcha")
        acomp.evento("login_concluido", sistema="eproc", tribunal="TJAL")
        self.assertIsNone(acomp.dados()["aguardando"])
        acomp.evento("acao_na_janela", sistema="eproc", tribunal="TJAL", motivo="perfil")
        acomp.item(modelos.ResultadoProcesso(1, A.formatado, "TJAL", "eproc", modelos.OK))
        self.assertIsNone(acomp.dados()["aguardando"], "um item que termina encerra a espera")
        acomp.evento("lote_inicio", destino="D:\\Lote", relatorio="D:\\Lote\\_controle\\r.csv",
                     sigilosos_do_lote="D:\\Sig\\Lote", total=1)
        self.assertEqual(acomp.dados()["destino"], "D:\\Lote")
        self.assertEqual(acomp.dados()["ultimo_evento"]["tipo"], "lote_inicio")
        acomp.status("Entrando no e-SAJ do TJAL...")
        acomp.progresso(1, 3, B.formatado)
        self.assertEqual(acomp.dados()["status"], "Entrando no e-SAJ do TJAL...")
        self.assertEqual(acomp.dados()["progresso"],
                         {"feitos": 1, "total": 3, "em_curso": B.formatado})

    def test_contexto_do_terminal_repassa_frase_e_andamento(self):
        import io

        from helestron.download.contexto import ContextoTerminal

        acomp = acompanhamento.Acompanhamento(None)
        ctx = ContextoTerminal(saida=io.StringIO(), acompanhamento=acomp)
        ctx.status("A sessão caiu; entrando de novo...")
        ctx.progresso(2, 5, A.formatado)
        self.assertEqual(acomp.dados()["status"], "A sessão caiu; entrando de novo...")
        self.assertEqual(acomp.dados()["progresso"]["em_curso"], A.formatado)

    def test_processo_com_paginacao_do_manifesto(self):
        r = modelos.ResultadoProcesso(
            1, A.formatado, "TJAL", "esaj", modelos.OK, arquivo=str(self.tmp / "a.pdf"),
            incompleto="6-7", paginacao={"sistema": "esaj", "paginacao": "folhas", "ultima": 8,
                                         "ausentes": {"N": "6-7"}, "folhas_ausentes": "6-7",
                                         "resumo": "página N = folha N (fls. 1 a 8)"})
        p = acompanhamento.processo_json(r)
        self.assertTrue(p["paginacao"]["garantida"])
        self.assertEqual((p["paginacao"]["ultima"], p["paginacao"]["ausentes"]), (8, {"N": "6-7"}))
        self.assertEqual(p["nome_arquivo"], "a")
        sem = acompanhamento.processo_json(modelos.ResultadoProcesso(
            2, B.formatado, "TJAL", "esaj", modelos.JA_BAIXADO, arquivo=str(self.tmp / "b.pdf")))
        self.assertFalse(sem["paginacao"]["garantida"])
        self.assertIsNone(sem["paginacao"]["ultima"])
        self.assertIn("não conferida", sem["paginacao"]["resumo"])
        nada = acompanhamento.processo_json(modelos.ResultadoProcesso(3, B.formatado, "TJAL",
                                                                       "esaj", modelos.ERRO))
        self.assertIsNone(nada["paginacao"])
        self.assertEqual(nada["nome_arquivo"], B.nome_arquivo)
        self.assertTrue(nada["refazer"])

    def test_concluir_com_o_resumo_do_lote(self):
        arq = self.tmp / "lote.json"
        acomp = acompanhamento.Acompanhamento(arq)
        itens = [modelos.ResultadoProcesso(1, A.formatado, "TJAL", "esaj", modelos.OK,
                                           sigiloso=True),
                 modelos.ResultadoProcesso(2, B.formatado, "TJAL", "esaj", modelos.CANCELADO)]
        resumo = modelos.ResumoLote(itens, self.tmp / "L", self.tmp / "L" / "r.csv",
                                    sigilosos_no_acervo=["x.pdf"],
                                    pasta_sigilosos=self.tmp / "Sig" / "L",
                                    relatorio_completo=self.tmp / "Sig" / "L" / "r.csv")
        acomp.concluir(1, resumo=resumo)
        dados = self.ler(arq)
        self.assertEqual(dados["resumo"]["pendentes"], 1)
        self.assertEqual(dados["resumo"]["sigilosos"], 1)
        self.assertEqual(dados["sigilosos_do_lote"], str(self.tmp / "Sig" / "L"))
        self.assertEqual(dados["relatorio_completo"], str(self.tmp / "Sig" / "L" / "r.csv"))
        self.assertEqual(dados["sigilosos_no_acervo"], ["x.pdf"])

    def test_arquivo_preso_por_quem_le_nao_derruba(self):
        arq = self.tmp / "lote.json"
        acomp = acompanhamento.Acompanhamento(arq)
        with mock.patch.object(acompanhamento.os, "replace",
                               side_effect=PermissionError(13, "em uso")), \
                mock.patch.object(acompanhamento.time, "sleep"):
            acomp.evento("fim", total=0)
        self.assertFalse(arq.exists())
        self.assertEqual(list(self.tmp.glob("*.parcial")), [])
        acomp.concluir(0)
        self.assertTrue(self.ler(arq)["concluido"])

    def test_formato_documentado(self):
        doc = acompanhamento.__doc__
        for campo in ("helestron.baixar/1", '"paginacao"', '"ultima"', '"ausentes"', '"causa"',
                      '"refazer"', '"capa_json"', '"texto"', '"incompleto"', '"aguardando"'):
            self.assertIn(campo, doc)


if __name__ == "__main__":
    unittest.main()
