"""Montagem do PDF único com o PyMuPDF de verdade.

Um documento ruim não pode derrubar os autos: ele vira uma página de aviso
no lugar exato em que estaria. E nenhuma gravação pode deixar um PDF pela
metade no lugar do bom.
"""

from __future__ import annotations

import unittest
from unittest import mock

import pymupdf

from helestron.download import pdf
from helestron.nucleo import paginacao

from testes import apoio_download as apoio


def abrir(caminho):
    return pymupdf.open(str(caminho))


def pdf_com_sumario(paginas, sumario, texto="página"):
    doc = pymupdf.open(stream=apoio.pdf_bytes(paginas, texto))
    doc.set_toc(sumario)
    dados = doc.tobytes()
    doc.close()
    return dados


def pdf_carimbado(folhas, texto="servidor"):
    """PDF com o carimbo do e-SAJ ("fls. N", numa linha só) em cada página."""
    doc = pymupdf.open()
    for i, f in enumerate(folhas, 1):
        pagina = doc.new_page()
        pagina.insert_text((500, 30), f"fls. {f}")
        pagina.insert_text((72, 120), f"{texto} {i}")
    dados = doc.tobytes()
    doc.close()
    return dados


def pdf_carimbado_com_copias(folhas, copias, texto="servidor"):
    """Como ``pdf_carimbado``, mas a folha que está em ``copias`` (folha ->
    carimbo antigo) reproduz uma folha de outro processo do e-SAJ - a
    sentença do principal anexada ao cumprimento de sentença: a página
    copiada traz o carimbo antigo, e o deste processo vem por cima, no fim
    do conteúdo, como o e-SAJ o desenha."""
    doc = pymupdf.open()
    for i, f in enumerate(folhas, 1):
        pagina = doc.new_page()
        if f in copias:
            outro = pymupdf.open()
            antiga = outro.new_page()
            antiga.insert_text((500, 30), f"fls. {copias[f]}")
            antiga.insert_text((72, 120), f"{texto} {i}")
            with pymupdf.open(stream=outro.tobytes()) as copia:
                pagina.show_pdf_page(pagina.rect, copia, 0)
            outro.close()
        else:
            pagina.insert_text((72, 120), f"{texto} {i}")
        pagina.insert_text((500, 45), f"fls. {f}")
    dados = doc.tobytes()
    doc.close()
    return dados


def textos_das_paginas(caminho):
    with pymupdf.open(caminho) as doc:
        return [" ".join(doc[i].get_text().split()) for i in range(len(doc))]


def primeiras_linhas(caminho):
    with pymupdf.open(caminho) as doc:
        return [(doc[i].get_text().splitlines() or [""])[0] for i in range(len(doc))]


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

    def test_anexar_saiu(self):
        """Acrescentar documentos ao fim de um PDF do e-SAJ criaria páginas
        depois da última folha, que pareceriam folhas que não existem."""
        self.assertFalse(hasattr(pdf, "anexar"))

    def test_gravar_sem_marcadores_mantem_o_sumario_do_arquivo(self):
        """O arquivo inteiro do eProc entra intacto: sumário próprio,
        páginas e bytes; metadados e manifesto vão por salvamento incremental."""
        original = pdf_com_sumario(4, [[1, "Evento 1 - INIC1", 1], [1, "Evento 2 - SENT1", 3]])
        destino = self.tmp / "completo.pdf"
        manifesto = paginacao.manifesto_eproc("5001234-56.2024.8.21.0001", [], modo="completo",
                                              tribunal="TJRS")
        n = pdf.gravar(destino, original, metadados={"title": "Processo 5001234",
                                                     "subject": "Autos do eProc"},
                       manifesto=manifesto)
        self.assertEqual(n, 4)
        self.assertTrue(destino.read_bytes().startswith(original))
        with abrir(destino) as doc:
            self.assertEqual(doc.get_toc(), [[1, "Evento 1 - INIC1", 1],
                                             [1, "Evento 2 - SENT1", 3]])
            self.assertEqual(doc.metadata["title"], "Processo 5001234")
            self.assertEqual(doc.metadata["subject"], "Autos do eProc")
            self.assertIn("modo=completo", doc.metadata["keywords"])
            m = paginacao.ler_do_doc(doc)
        self.assertEqual(m["partes"], [{"inicio": 1, "paginas": 4}])
        self.assertEqual(m["documentos"], [])

    def test_gravar_preservando_o_sumario_que_ja_existe(self):
        destino = self.tmp / "p.pdf"
        com = pdf_com_sumario(2, [[1, "Próprio", 1]])
        pdf.gravar(destino, com, [("Autos completos", 1)], preservar_sumario=True)
        with abrir(destino) as doc:
            self.assertEqual(doc.get_toc(), [[1, "Próprio", 1]])
        pdf.gravar(destino, apoio.pdf_bytes(2), [("Autos completos", 1)], preservar_sumario=True)
        with abrir(destino) as doc:
            self.assertEqual(doc.get_toc(), [[1, "Autos completos", 1]])

    def test_arquivo_preso_por_um_instante_nao_derruba_a_gravacao(self):
        """OneDrive, indexador e antivírus seguram o arquivo recém-gravado por
        um instante; o motor tomaria o PermissionError por "PDF aberto"."""
        real = pdf.os.replace
        falhas = [PermissionError(13, "Acesso negado")] * 2

        def replace(origem, destino):
            if falhas:
                raise falhas.pop()
            return real(origem, destino)
        destino = self.tmp / "p.pdf"
        with mock.patch.object(pdf, "ESPERA_TROCA_S", 0), \
                mock.patch.object(pdf.os, "replace", replace):
            self.assertEqual(pdf.gravar(destino, apoio.pdf_bytes(2)), 2)
        self.assertEqual(pdf.contar_paginas(destino), 2)
        self.assertFalse((self.tmp / "p.pdf.parcial").exists())

    def test_troca_espera_cada_vez_mais_antes_de_desistir(self):
        """O antivírus segura um PDF grande por segundos: a troca insiste com
        esperas crescentes (0,25, 0,5, 1, 2, 3 s...), por quase 10 s."""
        esperas = []
        with mock.patch.object(pdf.time, "sleep", esperas.append), \
                mock.patch.object(pdf.os, "replace",
                                  side_effect=PermissionError(13, "Acesso negado")) as troca:
            with self.assertRaises(PermissionError):
                pdf._trocar(self.tmp / "a.parcial", self.tmp / "a.pdf")
        self.assertEqual(troca.call_count, pdf.TENTATIVAS_TROCA)
        self.assertEqual(esperas, [0.25, 0.5, 1.0, 2.0, 3.0, 3.0])
        self.assertTrue(8 <= sum(esperas) <= 10, sum(esperas))
        # a trava curta passa logo, sem esperar o resto
        esperas.clear()
        falhas = [PermissionError(13, "Acesso negado")] * 2
        real = pdf.os.replace

        def replace(origem, destino):
            if falhas:
                raise falhas.pop()
            return real(origem, destino)
        (self.tmp / "b.parcial").write_bytes(b"x")
        with mock.patch.object(pdf.time, "sleep", esperas.append), \
                mock.patch.object(pdf.os, "replace", replace):
            pdf._trocar(self.tmp / "b.parcial", self.tmp / "b.pdf")
        self.assertEqual(esperas, [0.25, 0.5])
        self.assertEqual((self.tmp / "b.pdf").read_bytes(), b"x")

    def test_gravar_insiste_na_troca_do_parcial2(self):
        """Sem salvamento incremental, o PDF com o manifesto vai para o
        .parcial2 e troca de lugar com o .parcial: essa troca também insiste."""
        real = pdf.os.replace
        falhas = [PermissionError(13, "Acesso negado")] * 2

        def replace(origem, destino):
            if str(origem).endswith(".parcial2") and falhas:
                raise falhas.pop()
            return real(origem, destino)
        destino = self.tmp / "p.pdf"
        m = paginacao.manifesto_eproc("5001234-56.2024.8.21.0001", [], modo="completo")
        with mock.patch.object(pdf, "ESPERA_TROCA_S", 0), \
                mock.patch.object(pdf.os, "replace", replace), \
                mock.patch.object(pymupdf.Document, "can_save_incrementally", return_value=False):
            self.assertEqual(pdf.gravar(destino, apoio.pdf_bytes(2), manifesto=m), 2)
        self.assertEqual(falhas, [])
        self.assertEqual(paginacao.ler_do_pdf(destino)["modo"], "completo")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["p.pdf"])

    def test_gravar_sem_trocar_o_parcial2_vai_como_veio_e_nao_deixa_sobra(self):
        real = pdf.os.replace

        def replace(origem, destino):
            if str(origem).endswith(".parcial2"):
                raise PermissionError(13, "Acesso negado")
            return real(origem, destino)
        destino = self.tmp / "p.pdf"
        m = paginacao.manifesto_eproc("5001234-56.2024.8.21.0001", [], modo="completo")
        with mock.patch.object(pdf, "ESPERA_TROCA_S", 0), \
                mock.patch.object(pdf.os, "replace", replace), \
                mock.patch.object(pymupdf.Document, "can_save_incrementally", return_value=False), \
                self.assertLogs("download.pdf", "WARNING"):
            self.assertEqual(pdf.gravar(destino, apoio.pdf_bytes(2), manifesto=m), 2)
        self.assertEqual(pdf.contar_paginas(destino), 2)       # o PDF como veio
        self.assertIsNone(paginacao.ler_do_pdf(destino))
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["p.pdf"],
                         "nenhum .parcial nem .parcial2 sobra")

    def test_pdf_aberto_no_leitor_ainda_avisa(self):
        destino = self.tmp / "p.pdf"
        tentativas = []

        def replace(origem, destino):
            tentativas.append(1)
            raise PermissionError(13, "Acesso negado")
        with mock.patch.object(pdf, "ESPERA_TROCA_S", 0), \
                mock.patch.object(pdf.os, "replace", replace):
            with self.assertRaises(PermissionError):
                pdf.juntar([pdf.Parte("Inicial", apoio.pdf_bytes(1))], destino)
        self.assertEqual(len(tentativas), pdf.TENTATIVAS_TROCA)

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


class TestJuntarComPaginacaoPropria(apoio.PastaTemporaria):
    """O que a montagem do eProc usa: rótulos de página com a paginação de
    cada documento, sumário próprio, metadados e manifesto."""

    def partes(self):
        return [
            pdf.Parte("Evento 1 — PETIÇÃO INICIAL — INIC1 (10/01/2024)",
                      pdf_com_sumario(2, [[1, "Dos fatos", 1], [2, "Do pedido", 2]], "inicial"),
                      rotulo_pagina="Ev. 1 INIC1 p. ", manter_sumario=True,
                      info={"evento": 1, "rotulo": "INIC1", "origem": "pdf"}),
            pdf.Parte("Evento 3 — DESPACHO — DESPADEC1", b"<p>Cite-se.</p>", "html",
                      rotulo_pagina="Ev. 3 DESPADEC1", numerar=False,
                      info={"evento": 3, "rotulo": "DESPADEC1", "origem": "html"}),
            pdf.Parte("Evento 4 — PETIÇÃO — PET1", b"nao e pdf", rotulo_pagina="Ev. 4 PET1 p. ",
                      info={"evento": 4, "rotulo": "PET1", "origem": "pdf"}),
            pdf.Parte("Evento 7 — ÁUDIO1", apoio.pdf_bytes(2, "audio"),
                      rotulo_pagina="Ev. 7 ÁUDIO1 (x) p. ",
                      info={"evento": 7, "rotulo": "ÁUDIO1", "origem": "pdf"}),
        ]

    def test_rotulos_inicio_e_falha(self):
        partes = self.partes()
        destino = self.tmp / "eproc.pdf"
        manifesto = paginacao.manifesto_eproc("5001234-56.2024.8.21.0001", [], tribunal="TJRS")
        n = pdf.juntar(partes, destino, metadados={"title": "Processo 5001234-56",
                                                   "creator": "Helestron"},
                       manifesto=manifesto)
        self.assertEqual(n, 6)
        self.assertEqual([(p.inicio, p.paginas, p.falhou) for p in partes],
                         [(1, 2, False), (3, 1, False), (4, 1, True), (5, 2, False)])
        with abrir(destino) as doc:
            self.assertEqual([pg.get_label() for pg in doc],
                             ["Ev. 1 INIC1 p. 1", "Ev. 1 INIC1 p. 2", "Ev. 3 DESPADEC1",
                              "Ev. 4 PET1 nao incluido", "Ev. 7 AUDIO1 x p. 1",
                              "Ev. 7 AUDIO1 x p. 2"])
            self.assertEqual(doc.metadata["title"], "Processo 5001234-56")
            self.assertEqual(doc.metadata["creator"], "Helestron")
            self.assertIn("sistema=eproc", doc.metadata["keywords"])
            m = paginacao.ler_do_doc(doc)
        docs = [(d["evento"], d["inicio"], d["paginas"], d["situacao"]) for d in m["documentos"]]
        self.assertEqual(docs, [(1, 1, 2, "ok"), (3, 3, 1, "ok"), (4, 4, 1, "ausente"),
                                (7, 5, 2, "ok")])

    def test_sumario_proprio_vira_nivel_2(self):
        destino = self.tmp / "eproc.pdf"
        pdf.juntar(self.partes(), destino)
        with abrir(destino) as doc:
            toc = doc.get_toc()
        self.assertEqual(toc[:3], [[1, "Evento 1 — PETIÇÃO INICIAL — INIC1 (10/01/2024)", 1],
                                   [2, "Dos fatos", 1], [3, "Do pedido", 2]])
        self.assertEqual([t[2] for t in toc if t[0] == 1], [1, 3, 4, 5])

    def test_sumario_proprio_recusado_cai_no_simples(self):
        real = pymupdf.Document.set_toc
        chamadas = []

        def set_toc(doc, toc, *a, **k):
            chamadas.append(len(toc))
            if any(t[0] > 1 for t in toc):
                raise ValueError("bad hierarchy level")
            return real(doc, toc, *a, **k)
        destino = self.tmp / "eproc.pdf"
        partes = self.partes()
        with mock.patch.object(pymupdf.Document, "set_toc", set_toc):
            pdf.juntar(partes, destino)
        with abrir(destino) as doc:
            self.assertEqual([t[0] for t in doc.get_toc()], [1, 1, 1, 1])
        self.assertEqual(chamadas, [6, 4])

    def test_manifesto_com_documentos_ja_listados(self):
        """O manifesto pode trazer as entradas (cópias, não o info das
        partes): são completadas pelo evento e rótulo."""
        partes = self.partes()[:2]
        copias = [dict(p.info) for p in partes] + [{"evento": 5, "rotulo": "x",
                                                    "situacao": "midia"}]
        m = paginacao.manifesto_eproc("1", copias)
        pdf.juntar(partes, self.tmp / "a.pdf", manifesto=m)
        self.assertEqual([(d.get("inicio"), d.get("paginas")) for d in m["documentos"]],
                         [(1, 2), (3, 1), (None, None)])

    def test_completo_em_varias_partes(self):
        partes = [pdf.Parte("Autos completos - parte 1", apoio.pdf_bytes(3), rotulo_pagina="Parte 1 p. "),
                  pdf.Parte("Autos completos - parte 2", apoio.pdf_bytes(2), rotulo_pagina="Parte 2 p. ")]
        m = paginacao.manifesto_eproc("1", [], modo="completo")
        pdf.juntar(partes, self.tmp / "c.pdf", manifesto=m)
        with abrir(self.tmp / "c.pdf") as doc:
            self.assertEqual(doc[3].get_label(), "Parte 2 p. 1")
            m2 = paginacao.ler_do_doc(doc)
        self.assertEqual(m2["partes"], [{"inicio": 1, "paginas": 3}, {"inicio": 4, "paginas": 2}])
        self.assertEqual(m2["documentos"], [])

    def test_sem_rotulo_nenhum_nao_grava_regras(self):
        destino = self.tmp / "x.pdf"
        pdf.juntar([pdf.Parte("A", apoio.pdf_bytes(2)), pdf.Parte("B", apoio.pdf_bytes(1))], destino)
        with abrir(destino) as doc:
            self.assertEqual(doc.get_page_labels(), [])
            self.assertEqual(doc[2].get_label(), "")

    def test_rotulo_seguro(self):
        self.assertEqual(pdf.rotulo_seguro("Ev. 7 ÁUDIO1 (x) p. "), "Ev. 7 AUDIO1 x p. ")
        self.assertEqual(pdf.rotulo_seguro("Ev. 2 CERTIDÃO — ofício nº 3"),
                         "Ev. 2 CERTIDAO oficio no 3")
        self.assertEqual(len(pdf.rotulo_seguro("x" * 200)), 60)
        self.assertTrue(pdf.rotulo_seguro("ação").isascii())


ARVORE_FAIXAS = [(1, 2, [1, 2]), (3, 4, [3, 4]), (5, 5, [5]), (8, 8, [8])]


def acabamento_de_teste(ausentes, notas):
    sumario = [[1, "Peça", 1]] + [[1, f"Fl. {f} — não disponibilizada pelo e-SAJ", f]
                                   for f in sorted(ausentes)]
    return sumario, paginacao.manifesto_esaj("0700001-00.2024.8.02.0001", 8, ausentes,
                                             origem="servidor", notas=notas)


class TestAlinhamento(apoio.PastaTemporaria):
    """e-SAJ: a página N do PDF é sempre a folha N."""

    def test_paginas_de_aviso(self):
        dados = pdf.paginas_de_aviso([(6, "N", ""), (7, "B", "Laudo pericial (fl. 7) - 01/02/2024")])
        with pymupdf.open(stream=dados) as doc:
            self.assertEqual(len(doc), 2)
            t6 = doc[0].get_text()
            t7 = " ".join(doc[1].get_text().split())
        self.assertEqual(t6.splitlines()[0], "Folha 6 — não disponibilizada pelo e-SAJ")
        self.assertIn("Pasta Digital não ofereceu esta folha", " ".join(t6.split()))
        self.assertTrue(t7.startswith("Folha 7 — não disponibilizada pelo e-SAJ"))
        self.assertIn("não pôde ser baixada", t7)
        self.assertIn("Peça: Laudo pericial (fl. 7) - 01/02/2024.", t7)
        self.assertIn("a página N deste arquivo seja sempre a folha N", t7)

    def test_muitas_paginas_de_aviso_num_documento_so(self):
        dados = pdf.paginas_de_aviso([(f, "N", "") for f in range(1, 301)])
        with pymupdf.open(stream=dados) as doc:
            self.assertEqual(len(doc), 300)
            self.assertEqual(doc[299].get_text().splitlines()[0],
                             "Folha 300 — não disponibilizada pelo e-SAJ")
        self.assertLess(len(dados), 400_000)

    def test_servidor_com_folhas_nao_oferecidas(self):
        destino = self.tmp / "p.pdf"
        original = apoio.pdf_bytes(6, "servidor")
        m = pdf.gravar_alinhado(destino, original, ARVORE_FAIXAS, 8, {}, acabamento_de_teste)
        self.assertEqual((m.paginas, m.ausentes, m.notas), (8, {6: "N", 7: "N"}, []))
        self.assertTrue(destino.read_bytes().startswith(original), "salvamento incremental")
        linhas = primeiras_linhas(destino)
        self.assertEqual(linhas, ["servidor 1", "servidor 2", "servidor 3", "servidor 4",
                                  "servidor 5", "Folha 6 — não disponibilizada pelo e-SAJ",
                                  "Folha 7 — não disponibilizada pelo e-SAJ", "servidor 6"])
        with abrir(destino) as doc:
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 6, 7])
        self.assertEqual(paginacao.ausentes(paginacao.ler_do_pdf(destino)), {6: "N", 7: "N"})
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["p.pdf"])

    def test_aviso_com_motivo_e_titulo_informados(self):
        destino = self.tmp / "p.pdf"
        pdf.gravar_alinhado(destino, apoio.pdf_bytes(6), ARVORE_FAIXAS, 8,
                            {6: ("S", "Procuração"), 7: ("S", "Procuração")})
        with abrir(destino) as doc:
            texto = " ".join(doc[5].get_text().split())
        self.assertIn("listou uma peça sem numeração", texto)
        self.assertIn("Peça: Procuração.", texto)

    def test_contagem_que_nao_bate_nao_grava(self):
        destino = self.tmp / "p.pdf"
        bom = apoio.pdf_bytes(2, "anterior")
        destino.write_bytes(bom)
        with self.assertRaises(pdf.Desalinhado) as caso:
            pdf.gravar_alinhado(destino, apoio.pdf_bytes(5), ARVORE_FAIXAS, 8)
        self.assertIn("5 páginas para 6 folhas", str(caso.exception))
        self.assertEqual(destino.read_bytes(), bom)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["p.pdf"])

    def test_carimbos(self):
        destino = self.tmp / "p.pdf"
        with self.assertRaises(pdf.Desalinhado) as caso:
            pdf.gravar_alinhado(destino, pdf_carimbado([1, 2, 3, 5, 4, 8]), ARVORE_FAIXAS, 8)
        self.assertIn("folha carimbada não confere", str(caso.exception))
        self.assertFalse(destino.exists())
        m = pdf.gravar_alinhado(destino, pdf_carimbado([1, 2, 3, 4, 5, 8]), ARVORE_FAIXAS, 8)
        self.assertEqual(m.paginas, 8)
        with abrir(destino) as doc:
            self.assertIn("fls. 8", doc[7].get_text())

    def test_carimbo_antigo_da_copia_de_outro_processo_nao_desalinha(self):
        """A folha que reproduz uma folha de outro processo do e-SAJ traz o
        carimbo antigo ("fls. 45") antes do deste processo ("fls. 3"): o PDF
        certo do servidor fica, e não vira peça a peça."""
        dados = pdf_carimbado_com_copias([1, 2, 3, 4, 5, 8], {3: 45, 4: 46})
        with pymupdf.open(stream=dados) as doc:
            self.assertEqual(pdf.carimbos(doc[2]), [45, 3])
            self.assertEqual(pdf.carimbo(doc[2]), 3, "o carimbo deste processo é o último")
            self.assertIsNone(pdf.carimbo(doc.new_page()))
        destino = self.tmp / "p.pdf"
        m = pdf.gravar_alinhado(destino, dados, ARVORE_FAIXAS, 8)
        self.assertEqual(m.ausentes, {6: "N", 7: "N"})
        self.assertTrue(destino.read_bytes().startswith(dados), "o PDF do servidor ficou")
        textos = textos_das_paginas(destino)
        self.assertIn("servidor 3", textos[2])
        self.assertIn("servidor 4", textos[3])

    def test_copia_de_outro_processo_fora_do_lugar_ainda_desalinha(self):
        """O carimbo antigo não esconde a página trocada, e o aviso cita o
        carimbo deste processo."""
        dados = pdf_carimbado_com_copias([1, 2, 3, 5, 4, 8], {5: 45, 4: 46})
        with self.assertRaises(pdf.Desalinhado) as caso:
            pdf.gravar_alinhado(self.tmp / "p.pdf", dados, ARVORE_FAIXAS, 8)
        self.assertIn("no lugar da fl. 4 veio a página carimbada fls. 5", str(caso.exception))
        self.assertFalse((self.tmp / "p.pdf").exists())

    def test_poucos_carimbos_nao_decidem(self):
        """Só com quase todas as páginas carimbadas o carimbo dá veredito:
        "conforme fls. 4" no meio do texto não é carimbo."""
        doc = pymupdf.open()
        for i in range(6):
            pg = doc.new_page()
            pg.insert_text((72, 72), f"página {i + 1}")
            if i == 0:
                pg.insert_text((500, 30), "fls. 99")
            pg.insert_text((72, 100), "conforme fls. 4 dos autos")
        dados = doc.tobytes()
        doc.close()
        self.assertEqual(pdf.gravar_alinhado(self.tmp / "p.pdf", dados, ARVORE_FAIXAS, 8).paginas, 8)

    def test_faixas_sobrepostas(self):
        """[1-3] e [3-4]: o servidor manda a fl. 3 duas vezes; fica a primeira."""
        destino = self.tmp / "p.pdf"
        m = pdf.gravar_alinhado(destino, apoio.pdf_bytes(5, "servidor"),
                                [(1, 3, [1, 2, 3]), (3, 4, [4])], 4)
        self.assertEqual(m.paginas, 4)
        self.assertEqual(primeiras_linhas(destino),
                         ["servidor 1", "servidor 2", "servidor 3", "servidor 5"])

    def test_o_que_nao_e_pdf_nao_substitui_nada(self):
        destino = self.tmp / "p.pdf"
        bom = apoio.pdf_bytes(2)
        destino.write_bytes(bom)
        with self.assertRaises(ValueError):
            pdf.gravar_alinhado(destino, b"<html>sessao expirada</html>", ARVORE_FAIXAS, 8)
        with self.assertRaises(ValueError) as caso:
            pdf.gravar_alinhado(destino, b"%PDF-1.4\n" + b"\x00lixo" * 40, ARVORE_FAIXAS, 8)
        self.assertNotIsInstance(caso.exception, pdf.Desalinhado)
        self.assertEqual(destino.read_bytes(), bom)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["p.pdf"])

    def test_pdf_aberto_no_leitor(self):
        destino = self.tmp / "p.pdf"
        bom = apoio.pdf_bytes(2)
        destino.write_bytes(bom)

        def replace(origem, alvo):
            raise PermissionError(13, "Acesso negado")
        with mock.patch.object(pdf, "ESPERA_TROCA_S", 0), \
                mock.patch.object(pdf.os, "replace", replace):
            with self.assertRaises(PermissionError):
                pdf.gravar_alinhado(destino, apoio.pdf_bytes(6), ARVORE_FAIXAS, 8)
        self.assertEqual(destino.read_bytes(), bom)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["p.pdf"])

    def peca(self, proprias, ini, fim, dados, titulo="Peça", **k):
        return pdf.PecaDeFolhas(proprias=proprias, ini=ini, fim=fim, titulo=titulo,
                                dados=dados, **k)

    def test_juntar_folhas_com_todo_tipo_de_falta(self):
        documento = apoio.pdf_bytes(4, "laudo")           # o documento inteiro (fls. 9-12)
        itens = [
            self.peca([3, 4, 5], 3, 5, apoio.pdf_bytes(1, "curta"), "Curta (fls. 3-5)"),
            self.peca([6, 7], 6, 7, apoio.pdf_bytes(5, "longa"), "Longa (fls. 6-7)"),
            self.peca([8], 8, 8, b"%PDF-1.4 quebrado" + b"x" * 300, "Quebrada (fl. 8)"),
            self.peca([9, 10], 9, 10, documento, "Laudo (fls. 9-10)", total_documento=4,
                      deslocamento=0),
            self.peca([11, 12], 11, 12, documento, "Laudo (fls. 11-12)", total_documento=4,
                      deslocamento=2),
            self.peca([13], 13, 13, None, "Sumida (fl. 13)"),
            self.peca([14, 15], 14, 15, apoio.pdf_bytes(2, "fim")),
        ]
        destino = self.tmp / "p.pdf"
        m = pdf.juntar_folhas(itens, 15, destino, {1: ("N", ""), 2: ("N", "")},
                              acabamento_de_teste)
        self.assertEqual(m.paginas, 15)
        self.assertEqual(m.ausentes, {1: "N", 2: "N", 4: "C", 5: "C", 8: "I", 13: "B"})
        self.assertEqual(m.notas, ["fls. 6-7: o arquivo da peça tinha 5 páginas; mantidas as 2 "
                                   "primeiras"])
        linhas = primeiras_linhas(destino)
        self.assertEqual(len(linhas), 15)
        for f in (1, 2, 4, 5, 8, 13):
            self.assertEqual(linhas[f - 1], f"Folha {f} — não disponibilizada pelo e-SAJ")
        self.assertEqual([linhas[i] for i in (2, 5, 6, 8, 9, 10, 11, 13, 14)],
                         ["curta 1", "longa 1", "longa 2", "laudo 1", "laudo 2", "laudo 3",
                          "laudo 4", "fim 1", "fim 2"])
        with abrir(destino) as doc:
            self.assertIn("Quebrada (fl. 8)", doc[7].get_text())
            self.assertIn("veio inválido", " ".join(doc[7].get_text().split()))
            m2 = paginacao.ler_do_doc(doc)
        self.assertEqual(m2["ausentes"], {"N": "1-2", "B": "13", "I": "8", "C": "4-5"})
        self.assertEqual(m2["notas"], m.notas)

    def test_juntar_folhas_aparando_pelo_carimbo(self):
        """Arquivo com páginas a mais e carimbadas: ficam as das folhas do bloco."""
        itens = [self.peca([1, 2], 1, 2, pdf_carimbado([7, 1, 2, 9], "peça"))]
        m = pdf.juntar_folhas(itens, 2, self.tmp / "p.pdf")
        self.assertEqual(primeiras_linhas(self.tmp / "p.pdf"), ["fls. 1", "fls. 2"])
        self.assertIn("carimbadas", m.notas[0])

    def test_juntar_folhas_aparando_com_copia_de_outro_processo(self):
        """Com páginas a mais, vale o carimbo deste processo, não o antigo da
        folha copiada de outro processo: as fls. 3-4 ficam, sem aviso."""
        itens = [self.peca([1, 2], 1, 2, pdf_carimbado([1, 2], "inicial")),
                 self.peca([3, 4], 3, 4, pdf_carimbado_com_copias([3, 4, 5], {3: 45, 4: 46},
                                                                  "sentença"))]
        destino = self.tmp / "p.pdf"
        m = pdf.juntar_folhas(itens, 4, destino)
        self.assertEqual(m.ausentes, {})
        self.assertEqual(m.notas, ["fls. 3-4: o arquivo da peça tinha 3 páginas; mantidas só "
                                   "as carimbadas com essas folhas (2)"])
        textos = textos_das_paginas(destino)
        self.assertIn("sentença 1", textos[2])
        self.assertIn("sentença 2", textos[3])

    def test_juntar_folhas_com_paginas_a_menos_segue_o_carimbo(self):
        """Faltando a página do começo ou do meio do bloco, as que vieram
        ficam na folha do carimbo delas, e o aviso vai para a folha que
        faltou - não para a última, com as outras uma folha antes."""
        casos = [([4, 5], {3: "C"}, "fls. 4-5"), ([3, 5], {4: "C"}, "fls. 3, 5"),
                 ([5], {3: "C", 4: "C"}, "fl. 5")]
        for carimbadas, ausentes, descricao in casos:
            with self.subTest(carimbadas=carimbadas):
                itens = [self.peca([1, 2], 1, 2, pdf_carimbado([1, 2], "inicial")),
                         self.peca([3, 4, 5], 3, 5, pdf_carimbado(carimbadas, "laudo"),
                                   total_documento=3),
                         self.peca([6], 6, 6, pdf_carimbado([6], "sentença"))]
                destino = self.tmp / "p.pdf"
                m = pdf.juntar_folhas(itens, 6, destino)
                self.assertEqual(m.ausentes, ausentes)
                paginas = "1 página" if len(carimbadas) == 1 else f"{len(carimbadas)} páginas"
                self.assertEqual(m.notas, [f"fls. 3-5: o arquivo da peça tinha {paginas}; a "
                                           "página de cada folha é a que traz o carimbo dela "
                                           f"({descricao})"])
                linhas = primeiras_linhas(destino)
                self.assertEqual(len(linhas), 6)
                for f in range(1, 7):
                    esperado = (f"Folha {f} — não disponibilizada pelo e-SAJ" if f in ausentes
                                else f"fls. {f}")
                    self.assertEqual(linhas[f - 1], esperado, f"página {f}")

    def test_juntar_folhas_sem_carimbo_e_com_paginas_a_menos(self):
        """Sem carimbo não há como saber qual faltou: ficam as primeiras folhas."""
        itens = [self.peca([1, 2, 3], 1, 3, apoio.pdf_bytes(2, "curta"))]
        m = pdf.juntar_folhas(itens, 3, self.tmp / "p.pdf")
        self.assertEqual((m.ausentes, m.notas), ({3: "C"}, []))
        self.assertEqual(primeiras_linhas(self.tmp / "p.pdf")[:2], ["curta 1", "curta 2"])

    def test_juntar_folhas_gravacao_atomica(self):
        destino = self.tmp / "p.pdf"
        bom = apoio.pdf_bytes(1)
        destino.write_bytes(bom)
        with mock.patch.object(pymupdf.Document, "save", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                pdf.juntar_folhas([self.peca([1], 1, 1, apoio.pdf_bytes(1))], 1, destino)
        self.assertEqual(destino.read_bytes(), bom)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["p.pdf"])

    def test_pdf_sem_manifesto_e_de_versao_anterior(self):
        antigo = self.tmp / "antigo.pdf"
        antigo.write_bytes(apoio.pdf_bytes(3))
        self.assertIsNone(paginacao.ler_do_pdf(antigo))
        self.assertIn("versão anterior", paginacao.resumo(paginacao.ler_do_pdf(antigo)))


if __name__ == "__main__":
    unittest.main()
