"""Pauta pela API de verdade: o servidor local com o ServicoPauta real (não o simulado).

Confere o contrato da seção 8.10 do lado de quem chama - os nomes dos
campos, os eventos, a pasta da planilha (fora do acervo) -, sem navegador:
a pauta entra por importação de relatório.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from testes import apoio_pauta as ap
from testes.test_servidor_base import ServidorDeTeste

HOJE = date.today()
N1, N2 = ap.numero("0700101"), ap.numero("0700102")


class TestPautaPelaAPI(ServidorDeTeste):
    def relatorio(self) -> bytes:
        amanha = HOJE + timedelta(days=1)
        return ("Data;Hora;Processo;Tipo;Situação;Partes;Local\n"
                f"{HOJE:%d/%m/%Y};23:59;{N1};Audiência de Conciliação;Designada;"
                "Maria x Banco;Sala 1\n"
                f"{amanha:%d/%m/%Y};09:00;{N2};Audiência Una;Cancelada;João x Município;\n"
                ).encode("utf-8")

    def test_importar_listar_exportar_e_estado(self):
        leitor = self.eventos()
        status, env = self.cliente.enviar("/api/pauta/importar", "pauta.csv", self.relatorio())
        self.assertEqual(status, 200, env)
        r = env["dados"]
        self.assertEqual((r["novas"], r["atualizadas"], r["ignoradas"], r["avisos"]),
                         (2, 0, 0, []))
        evento = leitor.esperar("pauta")
        self.assertEqual(evento["tipo"], "atualizada")

        dados = self.cliente.dados("GET", f"/api/pauta?de={HOJE}&ate={HOJE + timedelta(days=7)}")
        self.assertEqual([a["processo"] for a in dados["audiencias"]], [N1, N2])
        a = dados["audiencias"][0]
        for campo in ("id", "sistema", "tribunal", "processo", "data", "hora", "tipo", "situacao",
                      "local", "link", "classe", "partes", "magistrado", "sigiloso",
                      "observacoes", "origem", "capturada_em", "tipo_original",
                      "situacao_original"):
            self.assertIn(campo, a)
        self.assertEqual((a["data"], a["hora"], a["tipo"], a["sistema"], a["tribunal"]),
                         (HOJE.isoformat(), "23:59", "Conciliação", "arquivo", "TJAL"))
        self.assertEqual(dados["resumo"]["total"], 2)
        self.assertEqual(dados["resumo"]["hoje"], 1)
        self.assertEqual(dados["resumo"]["por_situacao"], {"Designada": 1, "Cancelada": 1})
        self.assertIn("monitoramento", dados)
        filtrada = self.cliente.dados("GET", f"/api/pauta?de={HOJE}&ate={HOJE + timedelta(days=7)}"
                                             "&situacao=Cancelada&busca=municipio")
        self.assertEqual([x["processo"] for x in filtrada["audiencias"]], [N2])

        estado = self.cliente.dados("GET", "/api/estado")
        pauta = estado["resumo"]["pauta"]
        self.assertEqual((pauta["hoje"], pauta["semana"], pauta["alteracoes_nao_vistas"]),
                         (1, 1, 0))
        if datetime.now().strftime("%H:%M") < "23:59":     # a das 23h59 ainda não passou
            self.assertEqual(pauta["proxima"]["processo"], N1)

        r = self.cliente.dados("POST", "/api/pauta/exportar",
                               {"de": HOJE.isoformat(), "ate": (HOJE + timedelta(days=7)).isoformat()})
        arquivo = Path(r["arquivo"])
        self.assertTrue(arquivo.is_file())
        self.assertTrue(arquivo.name.startswith("Pauta de audiências"))
        self.assertFalse(arquivo.resolve().is_relative_to(Path(self.cfg.pasta_acervo).resolve()),
                         "a planilha nunca fica no acervo")

    def test_fontes_monitoramento_e_alteracoes(self):
        fonte = self.cliente.dados("POST", "/api/pauta/fontes",
                                   {"tribunal": "TJAL", "sistema": "esaj", "rotulo": ""})
        self.assertEqual((fonte["id"], fonte["rotulo"], fonte["modo"]),
                         ("esaj-tjal", "TJAL · e-SAJ", "automatico"))
        self.assertEqual([f["id"] for f in self.cliente.dados("GET", "/api/pauta/fontes")],
                         ["esaj-tjal"])
        m = self.cliente.dados("POST", "/api/pauta/monitoramento",
                               {"ativo": False, "intervalo_horas": 3})
        self.assertEqual((m["ativo"], m["intervalo_horas"]), (False, 3))
        self.cfg.recarregar()
        self.assertEqual(self.cfg.texto("pauta", "intervalo_horas"), "3")
        self.assertEqual(self.cliente.dados("GET", "/api/pauta/alteracoes"), [])
        self.cliente.dados("POST", "/api/pauta/alteracoes/vistas")
        self.cliente.dados("DELETE", "/api/pauta/fontes/esaj-tjal")
        self.assertEqual(self.cliente.dados("GET", "/api/pauta/fontes"), [])

    def test_relatorio_invalido(self):
        status, env = self.cliente.enviar("/api/pauta/importar", "nada.txt", b"sem pauta nenhuma")
        self.assertEqual(status, 400, env)
        self.assertIn("não encontrei uma tabela de audiências", env["erro"]["mensagem"])


if __name__ == "__main__":
    unittest.main()
