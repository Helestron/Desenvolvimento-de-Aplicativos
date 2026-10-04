"""Pauta: importação de relatórios (xlsx, "xls" que é HTML, ods, csv, html, docx, pdf)."""

from __future__ import annotations

import unittest
import zipfile
from unittest import mock
from datetime import date, datetime, time

from helestron.pauta import importacao, regras
from helestron.pauta.importacao import RelatorioInvalido, ler_relatorio
from helestron.pauta.servico import ServicoPauta

from testes import apoio_download as apoio
from testes import apoio_pauta as ap

R = regras.carregar()
N1, N2, N3 = ap.numero("0700101"), ap.numero("0700102"), ap.numero("0700103")
# Um CNJ que sobrevive como número na planilha: os 19 dígitos dão um múltiplo
# de 1024, que o double guarda exato (os outros o Excel corrompe).
N_EXATO = ap.numero("0700102", origem="0992")


def digitos(n: str) -> str:
    return n.replace("-", "").replace(".", "")


class TestFormatos(apoio.PastaTemporaria):
    def ler(self, nome: str):
        return ler_relatorio(self.tmp / nome, R, agora=datetime(2026, 10, 3, 10, 0))

    def test_xlsx_com_celulas_tipadas_aba_oculta_e_numero_corrompido(self):
        from openpyxl import Workbook

        livro = Workbook()
        aba = livro.active
        aba.title = "Pauta"
        aba.append(["Pauta de audiências — 2ª Vara Cível"])
        aba.append([])
        aba.append(["Data", "Hora", "Processo", "Tipo de audiência", "Situação", "Partes"])
        aba.append([datetime(2026, 10, 5), time(14, 30), N1, "Conciliação", "Designada", "A x B"])
        # o CNJ guardado como número: o zero da frente some (e volta), o dígito confere
        aba.append([date(2026, 10, 6), "09h00", int(digitos(N_EXATO)), "Instrução", "Cancelada",
                    "C x D"])
        # número corrompido pelo Excel (os últimos dígitos trocados)
        aba.append([date(2026, 10, 7), "10:00", float(digitos(N3)[:-3] + "999"), "Una", "", ""])
        aba.append([None, None, None, None, None, None])
        oculta = livro.create_sheet("Rascunho")
        oculta.sheet_state = "hidden"
        oculta.append(["Data", "Processo", "Tipo"])
        oculta.append([datetime(2026, 10, 8), N3, "Una"])
        resumo = livro.create_sheet("Resumo")
        resumo.append(["Tipo", "Quantidade"])
        resumo.append(["Conciliação", 1])
        livro.save(self.tmp / "pauta.xlsx")

        r = self.ler("pauta.xlsx")
        self.assertEqual([(a.data, a.hora, a.processo, a.tipo, a.situacao) for a in r.audiencias], [
            (date(2026, 10, 5), "14:30", N1, "Conciliação", "Designada"),
            (date(2026, 10, 6), "09:00", N_EXATO, "Instrução e julgamento", "Cancelada")])
        self.assertEqual(r.ignoradas, 1)
        self.assertIn("corrompeu", r.avisos[0])
        a = r.audiencias[0]
        self.assertEqual((a.sistema, a.tribunal, a.fonte, a.origem),
                         ("arquivo", "TJAL", "arquivo", "pauta.xlsx"))

    def test_xls_de_verdade(self):
        """O .xls binário (OLE) vai pelo xlrd, com a data do Excel convertida."""
        import xlrd

        class Celula:
            def __init__(self, ctype, value):
                self.ctype, self.value = ctype, value

        class Aba:
            def __init__(self, nome, linhas, visibility=0):
                self.name, self._linhas, self.visibility = nome, linhas, visibility
                self.nrows = len(linhas)

            def row(self, i):
                return self._linhas[i]

        texto = lambda v: Celula(xlrd.XL_CELL_TEXT, v)  # noqa: E731
        data = Celula(xlrd.XL_CELL_DATE, 46300 + 14.5 / 24)       # 05/10/2026 14:30
        livro = mock.Mock(datemode=0)
        livro.sheets.return_value = [
            Aba("Oculta", [[texto("Data"), texto("Processo"), texto("Tipo")],
                           [Celula(xlrd.XL_CELL_DATE, 46301), texto(N3), texto("Una")]], 1),
            Aba("Pauta", [[texto("Data/Hora"), texto("Processo"), texto("Tipo")],
                          [data, texto(N1), texto("Conciliação")],
                          [Celula(xlrd.XL_CELL_EMPTY, ""), Celula(xlrd.XL_CELL_EMPTY, ""),
                           Celula(xlrd.XL_CELL_EMPTY, "")]])]
        (self.tmp / "antigo.xls").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 600)
        with mock.patch.object(xlrd, "open_workbook", return_value=livro) as abrir:
            r = self.ler("antigo.xls")
        abrir.assert_called_once_with(str(self.tmp / "antigo.xls"))
        self.assertEqual([(a.data, a.hora, a.processo, a.tipo) for a in r.audiencias],
                         [(date(2026, 10, 5), "14:30", N1, "Conciliação")])

    def test_xls_que_e_html_e_html(self):
        lista = ap.no_periodo(ap.audiencias_padrao(), ap.INICIO, ap.FIM)
        html = ap.pagina(ap.html_esaj(lista))
        (self.tmp / "Agenda de audiências.xls").write_text(html, encoding="cp1252",
                                                           errors="xmlcharrefreplace")
        (self.tmp / "pauta.html").write_text(ap.pagina(ap.html_eproc(lista, total=8)),
                                             encoding="utf-8")
        for nome in ("Agenda de audiências.xls", "pauta.html"):
            with self.subTest(nome=nome):
                r = self.ler(nome)
                self.assertEqual(len(r.audiencias), 8)
                self.assertEqual({a.tribunal for a in r.audiencias}, {"TJAL"})
                sig = next(a for a in r.audiencias if a.processo == lista[4].processo)
                self.assertTrue(sig.sigiloso)

    def test_csv_ponto_e_virgula_em_ansi(self):
        texto = ("Data;Hora;Processo;Tipo;Situação;Local\r\n"
                 f"05/10/2026;09:00;{N1};Conciliação;Designada;Sala 1\r\n"
                 f"06/10/2026;14h;{N2};Audiência Una;Redesignada;Sala 2\r\n")
        (self.tmp / "pauta.csv").write_bytes(texto.encode("cp1252"))
        r = self.ler("pauta.csv")
        self.assertEqual([(a.processo, a.hora, a.tipo, a.situacao, a.local) for a in r.audiencias],
                         [(N1, "09:00", "Conciliação", "Designada", "Sala 1"),
                          (N2, "14:00", "Una", "Redesignada", "Sala 2")])

    def test_ods(self):
        ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
              'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
              'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')

        def texto(t):
            return f'<table:table-cell office:value-type="string"><text:p>{t}</text:p></table:table-cell>'

        linhas = [
            "".join(texto(t) for t in ("Data", "Hora", "Processo", "Tipo")),
            ('<table:table-cell office:value-type="date" office:date-value="2026-10-05">'
             '<text:p>05/10/26</text:p></table:table-cell>'
             '<table:table-cell office:value-type="time" office:time-value="PT14H30M00S">'
             '<text:p>14:30</text:p></table:table-cell>' + texto(N1) + texto("Custódia")
             + '<table:table-cell table:number-columns-repeated="1020"/>'),
        ]
        conteudo = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns}>'
                    '<office:body><office:spreadsheet><table:table table:name="Pauta">'
                    + "".join(f"<table:table-row>{x}</table:table-row>" for x in linhas)
                    + '<table:table-row table:number-rows-repeated="1000"><table:table-cell/>'
                      '</table:table-row></table:table></office:spreadsheet></office:body>'
                      '</office:document-content>')
        with zipfile.ZipFile(self.tmp / "pauta.ods", "w") as z:
            z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
            z.writestr("content.xml", conteudo)
        r = self.ler("pauta.ods")
        self.assertEqual([(a.data, a.hora, a.processo, a.tipo) for a in r.audiencias],
                         [(date(2026, 10, 5), "14:30", N1, "Custódia")])

    def test_docx(self):
        import docx

        documento = docx.Document()
        documento.add_heading("Pauta de audiências da semana", 1)
        tabela = documento.add_table(rows=1, cols=5)
        for celula, titulo in zip(tabela.rows[0].cells,
                                  ("Data/Hora", "Processo", "Tipo", "Situação", "Partes")):
            celula.text = titulo
        for valores in (("05/10/2026 09:00", N1, "Conciliação", "Designada", "A x B"),
                        ("06/10/2026 10:30", N2, "Justificação", "Realizada", "C x D")):
            linha = tabela.add_row().cells
            for celula, valor in zip(linha, valores):
                celula.text = valor
        documento.save(self.tmp / "pauta.docx")
        r = self.ler("pauta.docx")
        self.assertEqual([(a.data, a.hora, a.tipo, a.situacao) for a in r.audiencias], [
            (date(2026, 10, 5), "09:00", "Conciliação", "Designada"),
            (date(2026, 10, 6), "10:30", "Justificação", "Realizada")])

    def test_docx_sem_tabela_por_linhas(self):
        import docx

        documento = docx.Document()
        documento.add_paragraph("Segunda-feira, 5 de outubro de 2026")
        documento.add_paragraph(f"09:00 — {N1} — Audiência de Conciliação — Maria x João")
        documento.add_paragraph(f"10:00 — {N2} — Audiência de Instrução e Julgamento")
        documento.add_paragraph("Terça-feira, 6 de outubro de 2026")
        documento.add_paragraph(f"08:30 — {N3} — Custódia — Cancelada")
        documento.save(self.tmp / "lista.docx")
        r = self.ler("lista.docx")
        self.assertEqual([(a.data, a.hora, a.processo, a.tipo, a.situacao) for a in r.audiencias],
                         [(date(2026, 10, 5), "09:00", N1, "Conciliação", "Designada"),
                          (date(2026, 10, 5), "10:00", N2, "Instrução e julgamento", "Designada"),
                          (date(2026, 10, 6), "08:30", N3, "Custódia", "Designada")])

    def _pdf_com_tabela(self, nome: str) -> None:
        import pymupdf

        documento = pymupdf.open()
        colunas = (30, 100, 150, 330, 470, 560)
        cabecalho = ("Data", "Hora", "Processo", "Tipo de audiência", "Situação", "Partes")

        def nova_pagina(titulo: str):
            pagina = documento.new_page(width=842, height=595)
            pagina.insert_text((30, 50), titulo, fontsize=13)
            for x, t in zip(colunas, cabecalho):
                pagina.insert_text((x, 90), t, fontsize=9)
            pagina.insert_text((30, 570), "Página 1 de 2", fontsize=8)
            pagina.insert_text((600, 570), "Gerado em 03/10/2026 10:00", fontsize=8)
            return pagina

        p1 = nova_pagina("Pauta de audiências - 05/10/2026 a 09/10/2026")
        linhas = [(110, ("05/10/2026", "09:00", N1, "Conciliação", "Designada", "Maria x Banco")),
                  (125, ("05/10/2026", "14:30", N2, "Instrução e julgamento", "Cancelada",
                         "José da Silva"))]
        for y, valores in linhas:
            for x, t in zip(colunas, valores):
                p1.insert_text((x, y), t, fontsize=9)
        p1.insert_text((560, 137), "x Equatorial S.A.", fontsize=9)   # partes que quebraram
        p2 = nova_pagina("Pauta de audiências (continuação)")
        for x, t in zip(colunas, ("06/10/2026", "10:00", N3, "Custódia", "Designada", "")):
            p2.insert_text((x, 110), t, fontsize=9)
        documento.save(self.tmp / nome)
        documento.close()

    def test_pdf_tabela_por_texto(self):
        self._pdf_com_tabela("pauta.pdf")
        r = self.ler("pauta.pdf")
        self.assertEqual([(a.data, a.hora, a.processo, a.tipo, a.situacao, a.partes)
                          for a in r.audiencias], [
            (date(2026, 10, 5), "09:00", N1, "Conciliação", "Designada", "Maria x Banco"),
            (date(2026, 10, 5), "14:30", N2, "Instrução e julgamento", "Cancelada",
             "José da Silva x Equatorial S.A."),
            (date(2026, 10, 6), "10:00", N3, "Custódia", "Designada", "")])

    def test_pdf_sem_cabecalho(self):
        import pymupdf

        documento = pymupdf.open()
        pagina = documento.new_page()
        pagina.insert_text((40, 60), "Audiências designadas", fontsize=12)
        pagina.insert_text((40, 90), f"05/10/2026 09:00 {N1} Audiência de Conciliação", fontsize=9)
        pagina.insert_text((40, 105), f"05/10/2026 11:00 {N2} Audiência Una Redesignada",
                           fontsize=9)
        documento.save(self.tmp / "solto.pdf")
        documento.close()
        r = self.ler("solto.pdf")
        self.assertEqual([(a.hora, a.processo, a.tipo) for a in r.audiencias],
                         [("09:00", N1, "Conciliação"), ("11:00", N2, "Una")])

    def test_erros_com_frase(self):
        (self.tmp / "vazio.xlsx").write_bytes(b"")
        (self.tmp / "texto.txt").write_text("nada de pauta aqui\n", encoding="utf-8")
        (self.tmp / "quebrado.xlsx").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        (self.tmp / "velho.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 600)
        casos = {"nao-existe.xlsx": "não encontrei", "vazio.xlsx": "está vazio",
                 "texto.txt": "não encontrei uma tabela de audiências",
                 "quebrado.xlsx": "danificado", "velho.doc": ".docx"}
        for nome, trecho in casos.items():
            with self.subTest(nome=nome):
                with self.assertRaises(RelatorioInvalido) as erro:
                    self.ler(nome)
                self.assertIn(trecho, str(erro.exception))
        self.assertIn("*.xlsx", importacao.TIPOS_ARQUIVO[0][1])


class TestImportarNoServico(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.amb = ap.config_temporaria(self.tmp)
        self.servico = ServicoPauta(self.amb.cfg, self.tmp / "pauta.sqlite3")
        self.addCleanup(self.servico.fechar)

    def test_nao_duplica_a_do_portal_e_completa(self):
        from helestron.pauta import modelos

        do_portal = modelos.nova(sistema="esaj", tribunal="TJAL", data_=date(2026, 10, 5),
                                 processo=N1, hora="09:00", tipo_original="Conciliação",
                                 fonte="esaj-tjal")
        self.servico.armazem.gravar([do_portal], "esaj-tjal", None, registrar_novas=False)
        (self.tmp / "rel.csv").write_text(
            "Data;Hora;Processo;Tipo;Local\n"
            f"05/10/2026;09:00;{N1};Conciliação;Sala 9\n"
            f"06/10/2026;10:00;{N2};Una;Sala 2\n"
            "sem data;10:00;" + N3 + ";Una;\n", encoding="utf-8")
        eventos = []
        self.servico.eventos = lambda tipo, dados: eventos.append((tipo, dados))
        r = self.servico.importar(self.tmp / "rel.csv")
        self.assertEqual((r["novas"], r["atualizadas"], r["ignoradas"], r["total"]), (1, 1, 1, 2))
        self.assertIn(N3, r["avisos"][0])
        lista = self.servico.listar(date(2026, 10, 1), date(2026, 10, 31))["audiencias"]
        self.assertEqual([(a["sistema"], a["processo"], a["local"]) for a in lista],
                         [("esaj", N1, "Sala 9"), ("arquivo", N2, "Sala 2")])
        self.assertEqual(eventos[-1][0], "pauta")
        self.assertEqual(eventos[-1][1]["tipo"], "atualizada")
        # importar de novo não duplica nada
        r = self.servico.importar(self.tmp / "rel.csv")
        self.assertEqual((r["novas"], r["atualizadas"]), (0, 0))

    def test_relatorio_invalido_vira_valueerror(self):
        (self.tmp / "x.txt").write_text("nada", encoding="utf-8")
        with self.assertRaises(ValueError) as erro:
            self.servico.importar(self.tmp / "x.txt")
        self.assertTrue(str(erro.exception)[0].isupper(), "frase com maiúscula para a tela")

    def test_ida_e_volta_pela_planilha_exportada(self):
        lista = ap.no_periodo(ap.audiencias_padrao(), ap.INICIO, ap.FIM)
        (self.tmp / "p.html").write_text(ap.pagina(ap.html_esaj(lista)), encoding="utf-8")
        self.servico.importar(self.tmp / "p.html")
        arquivo = self.servico.exportar(ap.INICIO, ap.FIM, self.amb.pauta)
        outro = ServicoPauta(self.amb.cfg, self.tmp / "outro.sqlite3")
        self.addCleanup(outro.fechar)
        r = outro.importar(arquivo)
        self.assertEqual(r["novas"], 8)
        de_volta = outro.listar(ap.INICIO, ap.FIM)["audiencias"]
        sig = next(a for a in de_volta if a["processo"] == lista[4].processo)
        self.assertTrue(sig["sigiloso"])
        self.assertEqual(sig["partes"], "", "a máscara não vira nome de parte")
        virtual = next(a for a in de_volta if a["processo"] == lista[5].processo)
        self.assertEqual(virtual["link"], lista[5].link)


if __name__ == "__main__":
    unittest.main()
