"""O manifesto de paginação gravado dentro do PDF (nucleo/paginacao)."""

import tempfile
import unittest
from pathlib import Path

import pymupdf

from helestron.nucleo import paginacao


def _pdf(caminho: Path, paginas: int) -> Path:
    doc = pymupdf.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"página {i + 1}")
    doc.save(str(caminho))
    doc.close()
    return caminho


class TestFaixas(unittest.TestCase):
    def test_descrever_ordena_e_une(self):
        self.assertEqual(paginacao.descrever_folhas({40, 8, 6, 7}), "6-8, 40")
        self.assertEqual(paginacao.descrever_folhas([]), "")
        self.assertEqual(paginacao.descrever_folhas([3]), "3")

    def test_ler_faixas_ida_e_volta(self):
        self.assertEqual(paginacao.ler_faixas("6-8, 40"), {6, 7, 8, 40})
        self.assertEqual(paginacao.ler_faixas(" 3 ,x, 5-4, 9 - 10"), {3, 9, 10})
        self.assertEqual(paginacao.ler_faixas(""), set())


class TestManifesto(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_esaj_ida_e_volta_no_pdf(self):
        m = paginacao.manifesto_esaj("0700001-70.2024.8.02.0058", 8,
                                     {6: "N", 7: "N", 8: "B"}, origem="servidor",
                                     tribunal="TJAL")
        self.assertEqual(m["ausentes"], {"N": "6-7", "B": "8"})
        arq = _pdf(self.tmp / "a.pdf", 8)
        with pymupdf.open(str(arq)) as doc:
            paginacao.gravar_no_doc(doc, m)
            doc.saveIncr()
        lido = paginacao.ler_do_pdf(arq)
        self.assertEqual(lido["ultima"], 8)
        self.assertEqual(paginacao.ausentes(lido), {6: "N", 7: "N", 8: "B"})
        with pymupdf.open(str(arq)) as doc:
            chaves = doc.metadata["keywords"]
            self.assertEqual(doc.page_count, 8)
        self.assertIn("sistema=esaj", chaves)
        self.assertIn("ausentes=N:6-7|B:8", chaves)
        self.assertIn("página N = folha N (fls. 1 a 8)", paginacao.resumo(lido))

    def test_regravar_atualiza_o_anexo(self):
        arq = _pdf(self.tmp / "b.pdf", 3)
        with pymupdf.open(str(arq)) as doc:
            paginacao.gravar_no_doc(doc, paginacao.manifesto_esaj("1", 3, {}))
            doc.saveIncr()
        with pymupdf.open(str(arq)) as doc:
            paginacao.gravar_no_doc(doc, paginacao.manifesto_esaj("1", 3, {2: "C"}))
            doc.saveIncr()
        self.assertEqual(paginacao.ausentes(paginacao.ler_do_pdf(arq)), {2: "C"})

    def test_eproc(self):
        docs = [{"evento": 1, "rotulo": "INIC1", "origem": "pdf", "situacao": "ok",
                 "inicio": 1, "paginas": 2}]
        m = paginacao.manifesto_eproc("5001234-56.2024.8.21.0001", docs, tribunal="TJRS")
        arq = _pdf(self.tmp / "c.pdf", 2)
        with pymupdf.open(str(arq)) as doc:
            paginacao.gravar_no_doc(doc, m)
            doc.save(str(self.tmp / "d.pdf"))
        lido = paginacao.ler_do_pdf(self.tmp / "d.pdf")
        self.assertEqual(lido["paginacao"], "documento")
        self.assertEqual(lido["documentos"][0]["rotulo"], "INIC1")
        self.assertEqual(paginacao.ausentes(lido), {})

    def test_pdf_antigo_ou_invalido(self):
        arq = _pdf(self.tmp / "velho.pdf", 2)
        self.assertIsNone(paginacao.ler_do_pdf(arq))
        (self.tmp / "lixo.pdf").write_bytes(b"nada")
        self.assertIsNone(paginacao.ler_do_pdf(self.tmp / "lixo.pdf"))
        self.assertIsNone(paginacao.ler_do_pdf(self.tmp / "nao-existe.pdf"))
        self.assertIn("anterior à 1.0.2", paginacao.resumo(None))

    def test_anexo_legivel_pelo_pypdf(self):
        from pypdf import PdfReader
        arq = _pdf(self.tmp / "e.pdf", 1)
        with pymupdf.open(str(arq)) as doc:
            paginacao.gravar_no_doc(doc, paginacao.manifesto_esaj("1", 1))
            doc.saveIncr()
        anexos = PdfReader(str(arq)).attachments
        self.assertIn(paginacao.NOME_ANEXO, anexos)


if __name__ == "__main__":
    unittest.main()
