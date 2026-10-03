"""Montagem do PDF único com o PyMuPDF de verdade.

Um documento ruim não pode derrubar os autos: ele vira uma página de aviso
no lugar exato em que estaria. E nenhuma gravação pode deixar um PDF pela
metade no lugar do bom.
"""

from __future__ import annotations

import unittest
from unittest import mock

import pymupdf

from app.download import pdf

from testes import apoio_download as apoio


def abrir(caminho):
    return pymupdf.open(str(caminho))


class TestConversoes(unittest.TestCase):
    def test_e_pdf(self):
        self.assertTrue(pdf.e_pdf(apoio.pdf_bytes()))
        self.assertTrue(pdf.e_pdf(b"\r\n lixo inicial %PDF-1.7 resto"))
        self.assertFalse(pdf.e_pdf(b"<html>erro</html>"))
        self.assertFalse(pdf.e_pdf(b""))
        self.assertFalse(pdf.e_pdf(None))

    def test_e_html(self):
        self.assertTrue(pdf.e_html(b"  <!DOCTYPE html><html>"))
        self.assertTrue(pdf.e_html(b"<html><body>Sess\xc3\xa3o expirada"))
        self.assertFalse(pdf.e_html(apoio.pdf_bytes()))

    def test_html_vira_pdf_com_o_texto(self):
        dados = pdf.html_para_pdf("<h1>Despacho</h1><p>Intime-se a ré. Ação &amp; ônus.</p>"
                                  "<script>alert('não')</script>")
        self.assertTrue(pdf.e_pdf(dados))
        with pymupdf.open(stream=dados) as doc:
            texto = doc[0].get_text()
        self.assertIn("Despacho", texto)
        self.assertIn("Intime-se a ré", texto)
        self.assertNotIn("alert", texto)

    def test_html_longo_quebra_em_paginas(self):
        dados = pdf.html_para_pdf("".join(f"<p>Parágrafo {i}</p>" for i in range(400)))
        with pymupdf.open(stream=dados) as doc:
            self.assertGreater(len(doc), 2)

    def test_html_que_o_layout_recusa_sai_como_texto(self):
        with mock.patch.object(pdf, "_story_para_pdf", side_effect=[RuntimeError("layout"),
                                                                     RuntimeError("layout")]):
            dados = pdf.html_para_pdf("<p>Conteúdo importante</p>")
        with pymupdf.open(stream=dados) as doc:
            self.assertIn("Conteúdo importante", doc[0].get_text())

    def test_texto_vira_pdf(self):
        dados = pdf.texto_para_pdf("Certidão\nCertifico que intimei a parte.", "Certidão")
        with pymupdf.open(stream=dados) as doc:
            self.assertIn("Certifico que intimei", doc[0].get_text())

    def test_imagem_numa_pagina_a4_sem_distorcer(self):
        dados = pdf.imagem_para_pdf(apoio.png_bytes(40, 80))      # em pé
        with pymupdf.open(stream=dados) as doc:
            self.assertEqual(len(doc), 1)
            self.assertLess(doc[0].rect.width, doc[0].rect.height)
            self.assertEqual(len(doc[0].get_images()), 1)
        dados = pdf.imagem_para_pdf(apoio.png_bytes(120, 40))     # deitada
        with pymupdf.open(stream=dados) as doc:
            self.assertGreater(doc[0].rect.width, doc[0].rect.height)

    def test_texto_com_travessao_aspas_e_sem_ligadura(self):
        dados = pdf.texto_para_pdf("Certifico que o réu — citado — disse “não” ao ofício…")
        with pymupdf.open(stream=dados) as doc:
            texto = doc[0].get_text()
        self.assertIn("Certifico que o réu — citado — disse “não” ao ofício…", texto)

    def test_tiff_de_varias_paginas_vira_varias_paginas(self):
        from PIL import Image
        import io
        quadros = [Image.new("RGB", (80, 120), cor) for cor in ("white", "gray", "black")]
        saida = io.BytesIO()
        quadros[0].save(saida, format="TIFF", save_all=True, append_images=quadros[1:])
        dados = pdf.imagem_para_pdf(saida.getvalue())
        with pymupdf.open(stream=dados) as doc:
            self.assertEqual(len(doc), 3)

    def test_codificacoes(self):
        latin1 = "<html><head><meta charset='iso-8859-1'></head><p>Ação</p></html>".encode("latin-1")
        self.assertIn("Ação", pdf.decodificar(latin1, html=True))
        self.assertEqual(pdf.decodificar("Ação".encode("cp1252")), "Ação")
        self.assertEqual(pdf.decodificar("Ação".encode("utf-8")), "Ação")
        self.assertEqual(pdf.decodificar("\ufeffAção".encode("utf-8")), "Ação")
        self.assertEqual(pdf.decodificar(b"<meta charset=x-desconhecido>ok", html=True),
                         "<meta charset=x-desconhecido>ok")

    def test_html_latin1_no_pdf(self):
        destino_html = "<html><head><meta http-equiv='Content-Type' content='text/html; " \
                       "charset=ISO-8859-1'></head><body><p>Decisão: intime-se.</p></body></html>"
        partes = [pdf.Parte("Decisão", destino_html.encode("latin-1"), "html")]
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            alvo = Path(d) / "x.pdf"
            pdf.juntar(partes, alvo)
            with pymupdf.open(alvo) as doc:
                self.assertIn("Decisão: intime-se.", doc[0].get_text())

    def test_pagina_de_aviso(self):
        dados = pdf.pagina_aviso("Documento não incluído", "O arquivo veio corrompido.")
        with pymupdf.open(stream=dados) as doc:
            texto = doc[0].get_text()
        self.assertIn("Documento não incluído", texto)
        self.assertIn("corrompido", texto)


class TestJuntar(apoio.PastaTemporaria):
    def test_junta_tudo_com_marcadores(self):
        partes = [
            pdf.Parte("Petição inicial", apoio.pdf_bytes(3), "pdf"),
            pdf.Parte("Despacho", "<p>Cite-se.</p>".encode("utf-8"), "html"),
            pdf.Parte("Foto do documento", apoio.png_bytes(), "imagem"),
            pdf.Parte("Certidão", "Certifico e dou fé.".encode("utf-8"), "texto"),
        ]
        destino = self.tmp / "0700123-45.2024.8.02.0001.pdf"
        paginas = pdf.juntar(partes, destino)
        self.assertEqual(paginas, 6)
        with abrir(destino) as doc:
            self.assertEqual(len(doc), 6)
            self.assertEqual(doc.get_toc(), [[1, "Petição inicial", 1], [1, "Despacho", 4],
                                             [1, "Foto do documento", 5], [1, "Certidão", 6]])
            self.assertIn("Cite-se", doc[3].get_text())

    def test_pdf_invalido_vira_pagina_de_aviso_no_lugar_certo(self):
        partes = [pdf.Parte("Inicial", apoio.pdf_bytes(2)),
                  pdf.Parte("Laudo pericial", b"isto nao e pdf"),
                  pdf.Parte("Laudo complementar", b"%PDF-1.4\nquebrado de verdade"),
                  pdf.Parte("Sentença", apoio.pdf_bytes(1, "sentença"))]
        destino = self.tmp / "autos.pdf"
        self.assertEqual(pdf.juntar(partes, destino), 5)
        with abrir(destino) as doc:
            self.assertIn("Laudo pericial", doc[2].get_text())
            self.assertIn("não pôde ser incluído", doc[2].get_text())
            self.assertIn("Laudo complementar", doc[3].get_text())
            self.assertIn("sentença 1", doc[4].get_text())
            self.assertEqual([t[1] for t in doc.get_toc()],
                             ["Inicial", "Laudo pericial", "Laudo complementar", "Sentença"])

    def test_tipo_aviso(self):
        destino = self.tmp / "a.pdf"
        pdf.juntar([pdf.Parte("Peça ausente", "Não veio do portal.".encode(), "aviso")], destino)
        with abrir(destino) as doc:
            self.assertIn("Não veio do portal", doc[0].get_text())

    def test_sem_partes_e_erro(self):
        with self.assertRaises(ValueError):
            pdf.juntar([], self.tmp / "x.pdf")

    def test_gravacao_atomica_preserva_o_anterior_se_falhar(self):
        destino = self.tmp / "autos.pdf"
        bom = apoio.pdf_bytes(4)
        destino.write_bytes(bom)
        with mock.patch.object(pymupdf.Document, "save", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                pdf.juntar([pdf.Parte("x", apoio.pdf_bytes(1))], destino)
        self.assertEqual(destino.read_bytes(), bom, "o PDF anterior tem de continuar intacto")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["autos.pdf"])

    def test_substitui_o_anterior_de_uma_vez(self):
        destino = self.tmp / "autos.pdf"
        destino.write_bytes(apoio.pdf_bytes(4))
        pdf.juntar([pdf.Parte("novo", apoio.pdf_bytes(2))], destino)
        self.assertEqual(pdf.contar_paginas(destino), 2)
        self.assertFalse((self.tmp / "autos.pdf.parcial").exists())


class TestGravarEAnexar(apoio.PastaTemporaria):
    def test_gravar_com_marcadores(self):
        destino = self.tmp / "p.pdf"
        n = pdf.gravar(destino, apoio.pdf_bytes(5), [("Inicial", 1), ("Contestação", 3),
                                                     ("Fora do arquivo", 9)], exigir_paginas=5)
        self.assertEqual(n, 5)
        with abrir(destino) as doc:
            self.assertEqual(doc.get_toc(), [[1, "Inicial", 1], [1, "Contestação", 3]])
        self.assertFalse((self.tmp / "p.pdf.parcial").exists())

    def test_marcadores_nao_entram_se_a_contagem_nao_bate(self):
        destino = self.tmp / "p.pdf"
        n = pdf.gravar(destino, apoio.pdf_bytes(4), [("Inicial", 1), ("Contestação", 3)],
                       exigir_paginas=6)
        self.assertEqual(n, 4)
        with abrir(destino) as doc:
            self.assertEqual(doc.get_toc(), [])

    def test_pdf_corrompido_nao_substitui_o_anterior(self):
        destino = self.tmp / "p.pdf"
        bom = apoio.pdf_bytes(2)
        destino.write_bytes(bom)
        with self.assertRaises(ValueError) as caso:
            pdf.gravar(destino, b"%PDF-1.4\n" + b"\x00lixo" * 40)
        self.assertIn("corrompido", str(caso.exception))
        self.assertEqual(destino.read_bytes(), bom)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["p.pdf"])

    def test_gravar_recusa_o_que_nao_e_pdf(self):
        with self.assertRaises(ValueError):
            pdf.gravar(self.tmp / "x.pdf", b"<html>sessao expirada</html>")
        self.assertFalse((self.tmp / "x.pdf").exists())

    def test_anexar_ao_fim(self):
        alvo = self.tmp / "autos.pdf"
        pdf.juntar([pdf.Parte("Inicial", apoio.pdf_bytes(2))], alvo)
        total = pdf.anexar(alvo, [apoio.pdf_bytes(1, "nova"), b"lixo"], ["Decisão", "Ofício"])
        self.assertEqual(total, 4)
        with abrir(alvo) as doc:
            self.assertIn("nova 1", doc[2].get_text())
            self.assertIn("não pôde ser incluído", doc[3].get_text())
            self.assertEqual([t[1] for t in doc.get_toc()], ["Inicial", "Decisão", "Ofício"])
        self.assertFalse((self.tmp / "autos.pdf.parcial").exists())

    def test_contar_e_valido(self):
        bom = self.tmp / "bom.pdf"
        bom.write_bytes(apoio.pdf_bytes(3))
        ruim = self.tmp / "ruim.pdf"
        ruim.write_bytes(b"%PDF-1.4 truncado")
        self.assertEqual(pdf.contar_paginas(bom), 3)
        self.assertIsNone(pdf.contar_paginas(self.tmp / "nao-existe.pdf"))
        self.assertTrue(pdf.valido(bom))
        self.assertFalse(pdf.valido(ruim))
        self.assertFalse(pdf.valido(self.tmp / "nao-existe.pdf"))


if __name__ == "__main__":
    unittest.main()
