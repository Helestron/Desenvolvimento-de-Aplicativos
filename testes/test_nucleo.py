"""Testes do núcleo: número CNJ, tribunais, configuração, senhas e listas."""

from __future__ import annotations

import configparser
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from helestron.nucleo import cnj, config, cofre_senhas, listas, sistema, tribunais


class _nada:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class TestCNJ(unittest.TestCase):
    def test_formatos_aceitos(self):
        for texto in ("0800072-12.2024.8.02.0056", "08000721220248020056",
                      "Proc. 0800072–12.2024.8.02.0056 (Word)", "0800072 12 2024 8 02 0056"):
            self.assertEqual(cnj.ler(texto).formatado, "0800072-12.2024.8.02.0056", texto)

    def test_digito_verificador(self):
        self.assertTrue(cnj.ler("0800072-12.2024.8.02.0056").digito_confere)
        self.assertFalse(cnj.ler("0800072-13.2024.8.02.0056").digito_confere)

    def test_dependente_so_com_barra(self):
        # Regressão da base: "- 2ª Vara" virava o incidente 02.
        self.assertEqual(cnj.ler("0700123-45.2024.8.02.0001 - 2ª Vara").dependente, "")
        self.assertEqual(cnj.ler("0700123-45.2024.8.02.0001-2024").dependente, "")
        n = cnj.ler("0700123-45.2024.8.02.0001/0003")
        self.assertEqual(n.dependente, "03")
        self.assertEqual(n.nome_arquivo, "0700123-45.2024.8.02.0001-03")

    def test_sem_casar_dentro_de_numero_maior(self):
        with self.assertRaises(cnj.NumeroInvalido):
            cnj.ler("9070012345202480200019")

    def test_varios_na_mesma_linha_e_sem_repetir(self):
        achados = cnj.extrair_todos("a 0700123-45.2024.8.02.0001; b 07001234520248020001 "
                                    "c 5001234-56.2023.4.04.7100")
        self.assertEqual([n.formatado for n in achados],
                         ["0700123-45.2024.8.02.0001", "5001234-56.2023.4.04.7100"])

    def test_ler_none(self):
        with self.assertRaises(cnj.NumeroInvalido):
            cnj.ler(None)  # type: ignore[arg-type]

    def test_nome_de_arquivo_com_dependente(self):
        # Regressão: o "-NN" do nome do arquivo (Numero.nome_arquivo) era
        # ignorado, e o PDF do incidente ficava com a chave do principal.
        principal = "0700123-83.2024.8.02.0001"
        for nome, esperado in ((principal, principal),
                               (f"{principal}-01", f"{principal}-01"),
                               (f"{principal}/0001", f"{principal}-01"),
                               (f"{principal} (2)", principal),
                               (f"{principal}-01 (2)", f"{principal}-01"),
                               (f"{principal} 2025-03-10 14h00 - revisão", principal),
                               (f"{principal} - 2ª Vara", principal)):
            self.assertEqual(cnj.ler_nome_arquivo(nome).nome_arquivo, esperado, nome)
        with self.assertRaises(cnj.NumeroInvalido):
            cnj.ler_nome_arquivo("INDICE")


class TestTribunais(unittest.TestCase):
    def test_detecta_pelo_numero(self):
        t = tribunais.por_numero(cnj.ler("0700123-45.2024.8.02.0001"))
        self.assertEqual((t.sigla, t.sistema), ("TJAL", "esaj"))
        self.assertIsNotNone(t.alternativo)
        self.assertEqual(t.alternativo.sistema, "eproc")
        self.assertEqual(t.portal, "esaj:TJAL")

    def test_secao_judiciaria_federal(self):
        for origem, host in (("7000", "jfpr"), ("7100", "jfrs"), ("7200", "jfsc")):
            n = cnj.ler(f"5001234-56.2023.4.04.{origem}")
            self.assertIn(host, tribunais.por_numero(n).url_para(n))

    def test_nao_suportado(self):
        t = tribunais.por_numero(cnj.ler("0001234-56.2023.8.05.0001"))
        self.assertFalse(t.suportado)

    def test_catalogo_valido(self):
        dados = json.loads(tribunais.ARQUIVO.read_text(encoding="utf-8"))
        chaves = [t["chave"] for t in dados["tribunais"]]
        self.assertEqual(len(chaves), len(set(chaves)))
        for t in tribunais.carregar():
            if t.suportado:
                self.assertTrue(t.url_para(), t.sigla)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.arq = Path(self.dir.name) / "config.ini"

    def tearDown(self):
        self.dir.cleanup()

    def test_cria_com_comentarios_e_padroes(self):
        c = config.Config(self.arq)
        self.assertTrue(self.arq.exists())
        self.assertIn("; Pasta com tudo", self.arq.read_text(encoding="utf-8"))
        self.assertTrue(c.flag("download", "pular_baixados"))
        self.assertEqual(c.texto("transcricao", "modelo_ao_vivo"), "small")

    def test_definir_preserva_comentarios_e_aceita_porcento(self):
        c = config.Config(self.arq)
        antes = self.arq.read_text(encoding="utf-8").count(";")
        c.definir("geral", "nome_usuario", "Dr. Fulano 100% ; teste")
        c.definir("download", "pausa_entre_processos", 7)
        self.assertEqual(c.texto("geral", "nome_usuario"), "Dr. Fulano 100% ; teste")
        self.assertEqual(c.inteiro("download", "pausa_entre_processos"), 7)
        self.assertEqual(self.arq.read_text(encoding="utf-8").count(";"), antes + 1)

    def test_bom_e_valor_multilinha(self):
        self.arq.write_text("\ufeff[geral]\nnome_usuario = A\n  continua\n", encoding="utf-8")
        c = config.Config(self.arq)
        c.definir("geral", "nome_usuario", "B")
        self.assertEqual(c.texto("geral", "nome_usuario"), "B")
        self.assertEqual(self.arq.read_text(encoding="utf-8").count("[geral]"), 1)

    def test_recarregar_nao_expoe_configuracao_vazia(self):
        # Regressão: recarregar() trocava o parser por um VAZIO antes de ler;
        # outra thread lia, nesse intervalo, os padrões (pasta do acervo
        # errada) ou valores ainda em montagem (AttributeError).
        c = config.Config(self.arq)
        c.definir("geral", "pasta_acervo", r"D:\Gabinete\Acervo")
        vistos = []
        original = configparser.ConfigParser.read_string

        def lendo(cp, *args, **kwargs):
            vistos.append(c.texto("geral", "pasta_acervo"))
            return original(cp, *args, **kwargs)

        with mock.patch.object(configparser.ConfigParser, "read_string", lendo):
            c.recarregar()
        self.assertEqual(vistos, [r"D:\Gabinete\Acervo"])
        self.assertEqual(c.texto("geral", "pasta_acervo"), r"D:\Gabinete\Acervo")

    def test_arquivo_em_ansi_ou_utf16_nao_volta_ao_padrao(self):
        acervo = Path(self.dir.name) / "Gabinete" / "Acervo"     # absoluto também no Windows
        texto = (config.modelo_ini()
                 .replace("nome_usuario = \n", "nome_usuario = Dra. Conceição\n")
                 .replace("pasta_acervo = Acervo\n", f"pasta_acervo = {acervo}\n"))
        for codificacao in ("cp1252", "utf-16"):
            with self.subTest(codificacao=codificacao):
                self.arq.write_bytes(texto.replace("\n", "\r\n").encode(codificacao))
                with self.assertLogs("nucleo.config", "WARNING") if codificacao == "cp1252" \
                        else _nada():
                    c = config.Config(self.arq)
                self.assertEqual(c.texto("geral", "nome_usuario"), "Dra. Conceição")
                self.assertEqual(c.pasta_acervo, acervo)
                c.definir("unidade", "comarca", "Maceió")      # antes: UnicodeDecodeError
                self.assertIn("Dra. Conceição", self.arq.read_text(encoding="utf-8"))
                self.assertEqual(config.Config(self.arq).texto("unidade", "comarca"), "Maceió")

    def test_so_leitura_nao_cria_o_arquivo(self):
        c = config.Config(self.arq, criar=False)
        self.assertFalse(self.arq.exists())
        self.assertEqual(c.texto("transcricao", "modelo_ao_vivo"), "small")

    def test_pastas_uma_dentro_da_outra(self):
        base = Path(self.dir.name)
        self.assertEqual(config.conflito_de_pastas(base / "Acervo", base / "Sigilosos"), "")
        for acervo, sigilosos in ((base, base / "Sigilosos"), (base / "Acervo", base),
                                  (base / "Acervo", base / "Acervo")):
            self.assertIn("compartilhado com a IA", config.conflito_de_pastas(acervo, sigilosos))

    def test_definir_insiste_quando_o_arquivo_esta_preso(self):
        # Regressão: o antivírus ou o OneDrive seguram o config.ini por um
        # instante, e o os.replace falhava de primeira com "acesso negado".
        c = config.Config(self.arq)
        original = config.os.replace
        falhas = [PermissionError(13, "Acesso negado")] * 2

        def replace(origem, destino):
            if falhas:
                raise falhas.pop()
            return original(origem, destino)

        with mock.patch.object(config.os, "replace", replace), \
                mock.patch.object(config.time, "sleep") as dormir:
            c.definir("unidade", "comarca", "Maceió")
        self.assertEqual(dormir.call_count, 2)
        self.assertEqual(config.Config(self.arq).texto("unidade", "comarca"), "Maceió")

    def test_definir_com_arquivo_preso_de_vez_explica_e_nao_deixa_resto(self):
        c = config.Config(self.arq)
        with mock.patch.object(config.os, "replace", side_effect=PermissionError(13, "Acesso negado")), \
                mock.patch.object(config.time, "sleep") as dormir:
            with self.assertRaises(PermissionError) as ctx:
                c.definir("unidade", "comarca", "Maceió")
        self.assertEqual(dormir.call_count, config.TENTATIVAS_TROCA - 1)
        self.assertGreaterEqual(config.TENTATIVAS_TROCA * config.ESPERA_TROCA_S, 2)
        mensagem = str(ctx.exception)
        self.assertIn("Não consegui salvar a configuração", mensagem)
        self.assertIn("antivírus, OneDrive", mensagem)
        self.assertNotIn("Errno", mensagem)
        self.assertFalse(self.arq.with_name(self.arq.name + ".tmp").exists())
        self.assertEqual(c.texto("unidade", "comarca"), "")

    def test_valor_invalido_vira_padrao(self):
        self.arq.write_text("[download]\npausa_entre_processos = muito\npular_baixados = talvez\n",
                            encoding="utf-8")
        c = config.Config(self.arq)
        self.assertEqual(c.inteiro("download", "pausa_entre_processos"), 3)
        self.assertTrue(c.flag("download", "pular_baixados"))


class TestCofreSenhas(unittest.TestCase):
    def test_guarda_obtem_apaga(self):
        with tempfile.TemporaryDirectory() as d:
            cofre = cofre_senhas.CofreSenhas(Path(d) / "c.json")
            cofre.guardar("esaj:TJAL", "12345678900", "s3nh@;%")
            self.assertEqual(cofre.obter("esaj:TJAL"), ("12345678900", "s3nh@;%"))
            self.assertNotIn("s3nh@", (Path(d) / "c.json").read_text(encoding="utf-8"))
            cofre.apagar("esaj:TJAL")
            self.assertEqual(cofre.obter("esaj:TJAL"), ("", ""))

    def test_arquivo_estragado_nao_derruba(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "c.json"
            arq.write_text("{isto não é json", encoding="utf-8")
            self.assertEqual(cofre_senhas.CofreSenhas(arq).obter("x"), ("", ""))


class TestListas(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_texto_colado_com_senha(self):
        lei = listas.ler_texto("0800072-12.2024.8.02.0056 ; SENHA1\n"
                               "0700123-45.2024.8.02.0001; 0700001-11.2023.8.02.0001\n"
                               "# comentário 0700999-99.2024.8.02.0001\n")
        self.assertEqual(len(lei.processos), 3)
        self.assertEqual(lei.senhas, {"0800072-12.2024.8.02.0056": "SENHA1"})

    def test_segunda_coluna_nao_vira_senha(self):
        lei = listas.ler_texto("Por fim 0800072-12.2024.8.02.0056 ; Audiência\n")
        self.assertEqual(lei.senhas, {})
        # tabela colada do Excel, sem o cabeçalho "Senha"
        lei = listas.ler_texto("0800072-12.2024.8.02.0056\tCível\n"
                               "0700123-45.2024.8.02.0001\tFamília\n")
        self.assertEqual(len(lei.processos), 2)
        self.assertEqual(lei.senhas, {})

    def test_numero_e_senha_em_todas_as_linhas_sem_cabecalho(self):
        # Só linhas "número ; senha": o leitor de CSV pegava o atalho e perdia
        # as senhas.
        lei = listas.ler_texto("0800072-12.2024.8.02.0056 ; SENHA1\n"
                               "0700123-45.2024.8.02.0001 ; SENHA2\n")
        self.assertEqual(lei.senhas, {"0800072-12.2024.8.02.0056": "SENHA1",
                                      "0700123-45.2024.8.02.0001": "SENHA2"})
        (self.d / "s.csv").write_text("0800072-12.2024.8.02.0056;XY99\n"
                                      "0700123-45.2024.8.02.0001;ZW77\n", encoding="utf-8")
        lei = listas.ler_arquivo(self.d / "s.csv")
        self.assertEqual(lei.senhas, {"0800072-12.2024.8.02.0056": "XY99",
                                      "0700123-45.2024.8.02.0001": "ZW77"})

    def test_docx_na_ordem_do_documento(self):
        from docx import Document

        doc = Document()
        doc.add_paragraph("Primeiro: 0700123-45.2024.8.02.0001")
        t = doc.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "Processo", "Senha"
        t.cell(1, 0).text, t.cell(1, 1).text = "0800072-12.2024.8.02.0056", "ABC123"
        doc.add_paragraph("Último: 5001234-56.2023.4.04.7100")
        doc.save(self.d / "l.docx")
        lei = listas.ler_arquivo(self.d / "l.docx")
        self.assertEqual([n.formatado for n in lei.processos],
                         ["0700123-45.2024.8.02.0001", "0800072-12.2024.8.02.0056",
                          "5001234-56.2023.4.04.7100"])
        self.assertEqual(lei.senhas, {"0800072-12.2024.8.02.0056": "ABC123"})

    def test_xlsx_coluna_preferida_corrompido_e_aba_oculta(self):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["Nº do processo", "Processo de origem"])
        ws.append(["0800072-12.2024.8.02.0056", "0700001-11.2023.8.02.0001"])
        ws.append([8000721220248020056, None])     # número: o Excel corrompe
        oculta = wb.create_sheet("oculta")
        oculta.sheet_state = "hidden"
        oculta.append(["0700999-99.2024.8.02.0001"])
        wb.save(self.d / "l.xlsx")
        lei = listas.ler_arquivo(self.d / "l.xlsx")
        self.assertEqual([n.formatado for n in lei.processos], ["0800072-12.2024.8.02.0056"])
        self.assertTrue(lei.corrompidos)
        self.assertTrue(any("oculta" in a for a in lei.avisos))

    def test_xls_que_e_html_em_utf16(self):
        html = ("<html><table><tr><td>0800072-12.2024.8.02.0056</td></tr>"
                "<tr><td>07001234520248020001</td></tr></table></html>")
        (self.d / "x.xls").write_bytes(html.encode("utf-16"))
        lei = listas.ler_arquivo(self.d / "x.xls")
        self.assertEqual(len(lei.processos), 2)

    def test_csv_ponto_e_virgula(self):
        (self.d / "l.csv").write_text("processo;senha\n0800072-12.2024.8.02.0056;XY99\n",
                                      encoding="cp1252")
        lei = listas.ler_arquivo(self.d / "l.csv")
        self.assertEqual(lei.senhas, {"0800072-12.2024.8.02.0056": "XY99"})

    def test_ods(self):
        conteudo = (
            '<?xml version="1.0"?><office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body>'
            '<office:spreadsheet><table:table table:name="A"><table:table-row>'
            '<table:table-cell office:value-type="string"><text:p>0800072-12.2024.8.02.0056'
            '</text:p></table:table-cell></table:table-row></table:table>'
            '</office:spreadsheet></office:body></office:document-content>')
        with zipfile.ZipFile(self.d / "l.ods", "w") as z:
            z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
            z.writestr("content.xml", conteudo)
        lei = listas.ler_arquivo(self.d / "l.ods")
        self.assertEqual([n.formatado for n in lei.processos], ["0800072-12.2024.8.02.0056"])

    def test_pdf_com_quebra_no_meio_do_numero(self):
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "Processo 0800072-12.2024.8.02.\n0056 pauta")
        doc.save(str(self.d / "l.pdf"))
        lei = listas.ler_arquivo(self.d / "l.pdf")
        self.assertEqual([n.formatado for n in lei.processos], ["0800072-12.2024.8.02.0056"])

    def test_arquivo_sem_numero(self):
        (self.d / "v.txt").write_text("nada aqui", encoding="utf-8")
        with self.assertRaises(listas.ListaInvalida):
            listas.ler_arquivo(self.d / "v.txt")

    def test_links_compartilhados(self):
        self.assertEqual(
            listas.url_de_download("https://docs.google.com/spreadsheets/d/AbC-1_x/edit#gid=0"),
            "https://docs.google.com/spreadsheets/d/AbC-1_x/export?format=xlsx")
        self.assertIn("download=1", listas.url_de_download(
            "https://tjal-my.sharepoint.com/:x:/g/personal/x/EaBc?e=xyz"))


class TestSistema(unittest.TestCase):
    def test_nome_seguro_e_destino_livre(self):
        self.assertEqual(sistema.nome_seguro('a/b:c*?"<>|'), "a_b_c_")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "x.docx").write_text("1")
            self.assertEqual(sistema.destino_livre(p, "x", ".docx").name, "x (2).docx")

    def test_ambiente_sem_chaves(self):
        import os

        os.environ["ANTHROPIC_API_KEY"] = "sk-teste"
        try:
            self.assertNotIn("ANTHROPIC_API_KEY", sistema.ambiente_sem_chaves())
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


if __name__ == "__main__":
    unittest.main()
