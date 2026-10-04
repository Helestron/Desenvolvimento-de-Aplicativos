"""Pauta: normalização de datas, horas, tipos e situações; id estável; regras do pauta.json."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from helestron.pauta import modelos, regras
from helestron.pauta.modelos import (como_dict, de_dict, gerar_id, ler_data, ler_data_hora, ler_hora,
                                     ler_processo, normalizar_situacao, normalizar_texto,
                                     normalizar_tipo)

from testes import apoio_pauta as ap


class TestDatas(unittest.TestCase):
    def test_formatos_de_data(self):
        casos = {
            "05/10/2026": date(2026, 10, 5),
            "5/10/2026": date(2026, 10, 5),
            "05/10/26": date(2026, 10, 5),
            "05.10.2026": date(2026, 10, 5),
            "05-10-2026": date(2026, 10, 5),
            "2026-10-05": date(2026, 10, 5),
            "2026-10-05T14:30:00": date(2026, 10, 5),
            "Segunda-feira, 5 de outubro de 2026": date(2026, 10, 5),
            "05/out/2026": date(2026, 10, 5),
            "Data: 31/12/2026 às 9h": date(2026, 12, 31),
            "01/01/99": date(1999, 1, 1),
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(ler_data(texto), esperado)

    def test_datas_invalidas(self):
        for texto in ("", None, "32/10/2026", "29/02/2026", "processo 0700123", "14:30",
                      "05/10/1850", True):
            with self.subTest(texto=texto):
                self.assertIsNone(ler_data(texto))

    def test_valores_de_planilha(self):
        self.assertEqual(ler_data(datetime(2026, 10, 5, 14, 30)), date(2026, 10, 5))
        self.assertEqual(ler_data(date(2026, 10, 5)), date(2026, 10, 5))
        # número de série do Excel (célula de data sem formatação)
        self.assertEqual(ler_data(46300), date(2026, 10, 5))
        self.assertIsNone(ler_data(12.5))

    def test_horas(self):
        casos = {"14:30": "14:30", "9:05": "09:05", "14:30:00": "14:30", "14h30": "14:30",
                 "14 h 30": "14:30", "14hs30": "14:30", "9h": "09:00", "14H30": "14:30",
                 "05/10/2026 14:30": "14:30", "05.10.2026": "", "": "", "sala 2": "",
                 "25:00": "", "Audiência às 08:00 (virtual)": "08:00"}
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(ler_hora(texto), esperado)
        self.assertEqual(ler_hora(time(9, 5)), "09:05")
        self.assertEqual(ler_hora(0.5), "12:00")          # fração de dia do Excel
        self.assertEqual(ler_hora(datetime(2026, 10, 5, 8, 15)), "08:15")
        self.assertEqual(ler_hora(datetime(2026, 10, 5)), "")

    def test_data_e_hora_juntas(self):
        self.assertEqual(ler_data_hora("05/10/2026 14:30"), (date(2026, 10, 5), "14:30"))
        self.assertEqual(ler_data_hora("2026-10-05T09:00:00"), (date(2026, 10, 5), "09:00"))
        self.assertEqual(ler_data_hora("05/10/26 - 15h00"), (date(2026, 10, 5), "15:00"))
        self.assertEqual(ler_data_hora(datetime(2026, 10, 5, 16, 45)), (date(2026, 10, 5), "16:45"))
        self.assertEqual(ler_data_hora("05/10/2026"), (date(2026, 10, 5), ""))

    def test_dia_por_extenso(self):
        self.assertEqual(modelos.data_por_extenso(date(2026, 10, 5)), "Segunda-feira, 5 de outubro")
        self.assertEqual(modelos.dia_da_semana(date(2026, 10, 10)), "Sábado")


class TestTiposESituacoes(unittest.TestCase):
    def test_tipos(self):
        casos = {
            "Audiência de Conciliação": "Conciliação",
            "CONCILIAÇÃO": "Conciliação",
            "Audiência de Conciliação, Instrução e Julgamento": "Una",
            "Conciliação e Instrução": "Una",
            "AUDIÊNCIA UNA": "Una",
            "Audiência de Instrução e Julgamento": "Instrução e julgamento",
            "Instrução": "Instrução e julgamento",
            "Audiência de Custódia": "Custódia",
            "Audiência de Justificação": "Justificação",
            "Sessão de Mediação": "Mediação",
            "CEJUSC - sessão": "Mediação",
            "Audiência Preliminar": "Outra",
            "": "Outra",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(normalizar_tipo(texto), esperado)
        self.assertEqual(set(modelos.TIPOS), {r for r, _ in regras.carregar().tipos} | {"Outra"})

    def test_situacoes(self):
        casos = {
            "Designada": "Designada", "AGENDADA": "Designada", "Pendente": "Designada",
            "Realizada": "Realizada", "Concluída": "Realizada",
            "Não realizada": "Não realizada", "NAO REALIZADA": "Não realizada",
            "Não-realizada (ausência das partes)": "Não realizada",
            "Cancelada": "Cancelada", "Retirada de pauta": "Cancelada",
            "Redesignada": "Redesignada", "Redesignada a pedido": "Redesignada",
            "Adiada": "Redesignada", "Remarcada": "Redesignada",
            "Suspensa": "Suspensa", "": "Designada", "qualquer coisa": "Designada",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(normalizar_situacao(texto), esperado)
        self.assertEqual(modelos.situacao_reconhecida("qualquer coisa"), "")

    def test_normalizar_texto(self):
        self.assertEqual(normalizar_texto("  Nº do Processo: "), "n do processo")
        self.assertEqual(normalizar_texto("N. do processo"), "n do processo")
        self.assertEqual(normalizar_texto("SITUAÇÃO\xa0da   Audiência"), "situacao da audiencia")


class TestAudiencia(unittest.TestCase):
    def test_processo(self):
        n = ap.numero("0700123")
        self.assertEqual(ler_processo(f"Autos {n} (sigiloso)"), (n, True))
        self.assertEqual(ler_processo("sem número"), ("", True))
        # célula numérica com o zero da frente comido e dígito conferindo
        self.assertEqual(ler_processo(int(n.replace("-", "").replace(".", ""))), (n, True))
        # célula numérica que o Excel corrompeu: não vale (seria o processo de outra pessoa)
        corrompido = float(n.replace("-", "").replace(".", "")[:-2] + "99")
        self.assertEqual(ler_processo(corrompido), ("", False))
        self.assertEqual(modelos.tribunal_do_processo(n), "TJAL")
        self.assertEqual(modelos.tribunal_do_processo(ap.numero("5000001", tr="21")), "TJRS")
        self.assertEqual(modelos.tribunal_do_processo(""), "")

    def test_id_estavel_e_normalizado(self):
        n = ap.numero("0700123")
        a = modelos.nova(sistema="esaj", tribunal="tjal", data_=date(2026, 10, 5), processo=n,
                         hora="14h30", tipo_original="AUDIÊNCIA DE CONCILIAÇÃO",
                         situacao_original="Agendada", partes="  A   x  B ")
        b = modelos.nova(sistema="esaj", tribunal="TJAL", data_=date(2026, 10, 5), processo=n,
                         hora="14:30", tipo_original="Conciliação", situacao_original="Cancelada")
        self.assertEqual(a.id, b.id, "a grafia do tipo e a situação não mudam a identidade")
        self.assertEqual(a.id, gerar_id("esaj", "TJAL", n, date(2026, 10, 5), "14:30",
                                        "Conciliação"))
        self.assertEqual(len(a.id), 16)
        self.assertEqual((a.tribunal, a.hora, a.tipo, a.situacao, a.partes),
                         ("TJAL", "14:30", "Conciliação", "Designada", "A x B"))
        self.assertEqual(a.tipo_original, "AUDIÊNCIA DE CONCILIAÇÃO")
        outra = modelos.nova(sistema="esaj", tribunal="TJAL", data_=date(2026, 10, 5), processo=n,
                             hora="15:30", tipo_original="Conciliação")
        self.assertNotEqual(a.id, outra.id)

    def test_dict_ida_e_volta(self):
        a = modelos.nova(sistema="eproc", tribunal="TJRS", data_=date(2026, 10, 5),
                         processo=ap.numero("5000001", tr="21"), hora="09:00",
                         tipo_original="Una", sigiloso=True, link="https://teams.microsoft.com/x",
                         capturada_em=datetime(2026, 10, 3, 10, 0, 0, 999))
        d = como_dict(a)
        self.assertEqual(d["data"], "2026-10-05")
        self.assertEqual(d["hora"], "09:00")
        self.assertEqual(d["capturada_em"], "2026-10-03T10:00:00")
        self.assertTrue(d["sigiloso"])
        json.dumps(d)                                    # vai para a API sem conversão
        self.assertEqual(de_dict(d), a)


class TestRegras(unittest.TestCase):
    def test_arquivo_igual_ao_embutido(self):
        """O pauta.json e as regras embutidas (reserva) andam juntos."""
        dados = json.loads(regras.ARQUIVO.read_text(encoding="utf-8"))

        def sem_comentarios(d):
            if isinstance(d, dict):
                return {k: sem_comentarios(v) for k, v in d.items() if not k.startswith("_")}
            return d

        self.assertEqual(sem_comentarios(dados), regras.PADROES)
        self.assertEqual(regras.carregar().problema, "")

    def test_arquivo_estragado_usa_o_embutido(self):
        with tempfile.TemporaryDirectory() as d:
            arquivo = Path(d) / "pauta.json"
            arquivo.write_text('{"cabecalhos": {"data": ["quando"]', encoding="utf-8")
            with self.assertLogs("pauta.regras", "WARNING") as registro:
                r = regras.carregar(arquivo)
            self.assertIn("linha 1", r.problema)
            self.assertIn("regras embutidas", registro.output[0])
            self.assertIn("data da audiencia", r.cabecalhos["data"])

    def test_arquivo_ajustado_vale_chave_a_chave(self):
        with tempfile.TemporaryDirectory() as d:
            arquivo = Path(d) / "pauta.json"
            arquivo.write_text(json.dumps({"rotas": {"esaj": ["/pauta"], "tribunais": {
                "TJAL": {"esaj": ["/tjal/pauta"]}}}, "tipos": [["Custódia", "custodia"],
                                                                ["Outra", "["]]}),
                               encoding="utf-8-sig")
            with self.assertLogs("pauta.regras", "WARNING"):
                r = regras.carregar(arquivo)
            self.assertEqual(r.rotas("esaj", "TJAL"), ["/tjal/pauta", "/pauta"])
            self.assertEqual(r.rotas("esaj", "TJSP"), ["/pauta"])
            self.assertEqual(r.rotas("eproc"), regras.PADROES["rotas"]["eproc"])
            self.assertEqual(normalizar_tipo("custódia", r), "Custódia")
            self.assertEqual(normalizar_tipo("conciliação", r), "Outra")   # regex estragado: ignorado
            self.assertIn("processo", r.cabecalhos)         # o resto continua o embutido


if __name__ == "__main__":
    unittest.main()
