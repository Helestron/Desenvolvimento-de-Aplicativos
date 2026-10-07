"""eProc sem navegador: a paginação do PDF igual à do eProc.

O PDF documento a documento não tem capa nem página nenhuma antes ou entre
os documentos (o eProc não numera folhas: cada documento conserva a própria
paginação, citada "evento N, RÓTULO, p. Y"); o documento que não veio e a
gravação têm UMA página de aviso, marcada como não citável no rótulo de
página, no marcador e no manifesto. No modo completo, o arquivo do eProc
entra intacto. A capa vai para _controle/<número>_capa.txt e _capa.json.
Também os eventos de login (login_aguardando, acao_na_janela,
login_concluido) para quem acompanha pela linha de comando.

O ponta a ponta, com Chromium de verdade, está em
test_download_eproc_integracao.py.
"""

from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from datetime import datetime
from unittest import mock

import pymupdf

from helestron.compartilhar import textos
from helestron.download import eproc, esaj, modelos
from helestron.download.eproc import Documento, Evento, PortalEProc
from helestron.nucleo import paginacao, tribunais

from testes import apoio_download as apoio


def _ev(numero, data, hora, descricao, documentos=()):
    return Evento(numero, data, hora, descricao, documentos=list(documentos))


def _doc(evento, rotulo, mimetype="pdf", descricao="", data="10/01/2024"):
    return Documento(evento, data, "10:00", descricao, rotulo, f"controlador.php?doc={rotulo}",
                     mimetype=mimetype, id=rotulo)


def _pdf_com_sumario(paginas, texto, sumario):
    doc = pymupdf.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"{texto} {i + 1}")
    doc.set_toc(sumario)
    dados = doc.tobytes()
    doc.close()
    return dados


class ContextoComEventos(apoio.ContextoGravador):
    """O Contexto com ``evento`` (frente da linha de comando), gravando tudo."""

    def __init__(self, *a, falhar=False, **k):
        super().__init__(*a, **k)
        self.eventos = []
        self.falhar = falhar

    def evento(self, tipo, **dados):
        self.eventos.append((tipo, dados))
        if self.falhar:
            raise RuntimeError("quem acompanha caiu")


class _Pagina:
    url = "https://e/eproc/controlador.php?acao=principal"

    def content(self):
        return ""

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, *a, **k):
        return None


class _Nav:
    """O bastante do Navegador para o portal sem navegador de verdade."""

    def __init__(self, visivel=True):
        self.visivel = visivel
        self.pagina = _Pagina()
        self.diagnosticos = []

    def diagnosticar(self, rotulo, pagina=None):
        self.diagnosticos.append(rotulo)

    def abas(self):
        return []


class _Base(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.tribunal = replace(tribunais.por_sigla("TJRS"), urls={"1g": ["https://e/eproc/"]})
        self.n = apoio.numero("5001234", tr="21")
        p = mock.patch.object(eproc, "PAUSA_DOCUMENTOS_S", 0)
        p.start()
        self.addCleanup(p.stop)

    def portal(self, ctx=None, nav=None, **mudar):
        opcoes = apoio.opcoes_de_teste(self.tmp, **mudar)
        return PortalEProc(nav or _Nav(), self.tribunal, opcoes, ctx or apoio.ContextoGravador(),
                           ("u", "s"), seletores=eproc.SELETORES_PADRAO)


# ================================================================ funções puras
class TestCitacaoERotulo(unittest.TestCase):
    def test_citacao(self):
        inic = _doc(1, "INIC1")
        self.assertEqual(eproc.citacao(inic, 2), "evento 1, INIC1, p. 2")
        self.assertEqual(eproc.citacao(inic, 1, "imagem"), "evento 1, INIC1, p. 1")
        self.assertEqual(eproc.citacao(_doc(3, "DESPADEC1"), 1, "html"), "evento 3, DESPADEC1")
        self.assertEqual(eproc.citacao(_doc(3, "CERT1"), 2, "texto"), "evento 3, CERT1")
        self.assertEqual(eproc.citacao(_doc(4, "PET1"), 1, "pdf", "ausente"),
                         "evento 4, PET1 — NÃO INCLUÍDO")
        self.assertEqual(eproc.citacao(_doc(7, "VIDEO1"), 1, "midia", "midia"),
                         "evento 7, VIDEO1 — gravação fora do PDF")

    def test_rotulo_de_pagina(self):
        self.assertEqual(eproc.rotulo_de_pagina(_doc(1, "INIC1")), ("Ev. 1 INIC1 p. ", True))
        self.assertEqual(eproc.rotulo_de_pagina(_doc(2, "FOTO1"), "imagem"),
                         ("Ev. 2 FOTO1 p. ", True))
        self.assertEqual(eproc.rotulo_de_pagina(_doc(3, "DESPADEC1"), "html"),
                         ("Ev. 3 DESPADEC1", False))
        self.assertEqual(eproc.rotulo_de_pagina(_doc(4, "PET1"), "pdf", "ausente"),
                         ("Ev. 4 PET1 nao incluido", False))
        self.assertEqual(eproc.rotulo_de_pagina(_doc(7, "VIDEO1"), "midia", "midia"),
                         ("Ev. 7 VIDEO1 gravacao", False))
        # o PyMuPDF estraga acento e parênteses no rótulo: sai ASCII simples
        self.assertEqual(eproc.rotulo_de_pagina(_doc(8, "ÁUDIO1 (cópia)")),
                         ("Ev. 8 AUDIO1 copia p. ", True))
        longo = eproc.rotulo_de_pagina(_doc(9, "X" * 120))[0]
        self.assertLessEqual(len(longo), 60)
        self.assertTrue(longo.endswith(" p. "))

    def test_origem_esperada(self):
        self.assertEqual([eproc.origem_esperada(_doc(1, "A", mt))
                          for mt in ("pdf", "jpg", "html", "txt", "mp4", "")],
                         ["pdf", "imagem", "html", "texto", "midia", "pdf"])

    def test_manifesto_tem_as_partes_dentro_da_capa(self):
        n = apoio.numero("5001234", tr="21")
        eventos = [_ev(2, "02/01/2024", "", "AUDIÊNCIA", []),
                   _ev(1, "01/01/2024", "", "INICIAL", [_doc(1, "INIC1")])]
        m = eproc.manifesto_do_processo(
            n, "eProc do TJRS", "TJRS", {"numero": n.formatado, "classe": "PROC. COMUM",
                                         "orgao": "1ª Vara", "magistrado": "FULANA",
                                         "assunto": "Dano moral"},
            ["AUTOR: MARIA", "RÉU: BANCO"], eventos, False, ausentes="")
        self.assertTrue(paginacao.valido(m))
        self.assertEqual((m["sistema"], m["paginacao"], m["modo"], m["documentos"]),
                         ("eproc", "documento", "documentos", []))
        self.assertEqual(m["capa"], {"classe": "PROC. COMUM", "orgao": "1ª Vara",
                                     "magistrado": "FULANA", "assunto": "Dano moral",
                                     "partes": ["AUTOR: MARIA", "RÉU: BANCO"]})
        self.assertNotIn("partes", m, "no topo, 'partes' é das partes do arquivo completo")
        self.assertEqual(m["eventos_sem_documento"],
                         [{"evento": 2, "descricao": "AUDIÊNCIA", "data": "02/01/2024"}])
        self.assertEqual(m["eventos_nao_listados"], "")
        # sem a lista inteira de eventos, nada de meia lista
        parcial = eproc.manifesto_do_processo(n, "eProc do TJRS", "TJRS", {}, [], None, False,
                                              "completo")
        self.assertNotIn("eventos_sem_documento", parcial)
        self.assertNotIn("eventos_nao_listados", parcial)

    def test_capa_txt_sem_limite_de_eventos_e_segredo_no_topo(self):
        n = apoio.numero("5001234", tr="21")
        eventos = [_ev(i, "01/01/2024", "", f"ANDAMENTO {i}",
                          [_doc(i, f"DOC{i}")] if i % 2 else []) for i in range(1, 151)]
        partes = [f"AUTOR: PESSOA {i} " + "X" * 80 for i in range(40)]   # capa grande
        m = eproc.manifesto_do_processo(n, "eProc do TJRS", "TJRS", {"classe": "C"}, partes,
                                        eventos, True)
        texto = eproc.texto_capa_txt(n, "eProc do TJRS", {"classe": "C"}, partes, eventos, True,
                                     m)
        self.assertIn("SEGREDO DE JUSTIÇA", texto[:2000], "o motor só olha o começo")
        self.assertIn("== Eventos (150) ==", texto)
        self.assertIn("Evento 1 - ANDAMENTO 1 [DOC1]", texto)
        self.assertNotIn("e mais", texto.split("== Eventos")[1])
        self.assertIn("== Mapa de documentos (75) ==", texto)
        self.assertIn("Evento 149 — DOC149 (10/01/2024)", texto)

    def test_capa_json_tem_a_paginacao_como_objeto_nos_dois_sistemas(self):
        """helestron.capa/2: "paginacao" era objeto no e-SAJ e texto no eProc;
        quem lia capa["paginacao"]["resumo"] pelo contrato do e-SAJ (a skill,
        no TJAL em transição) quebrava com TypeError no primeiro do eProc."""
        n_esaj = apoio.numero("0700123", tr="02")
        m_esaj = paginacao.manifesto_esaj(n_esaj.formatado, 6, {3: "N"}, tribunal="TJAL")
        capa_esaj = esaj.dados_da_capa({"capa": {"Classe": "Procedimento Comum"}}, n_esaj,
                                       "TJAL", False, m_esaj)
        n = apoio.numero("5001234", tr="21")
        eventos = [_ev(1, "01/01/2024", "", "INICIAL", [_doc(1, "INIC1")]),
                   _ev(2, "02/01/2024", "", "PETIÇÃO", [_doc(2, "PET1")])]
        m = eproc.manifesto_do_processo(n, "eProc do TJRS", "TJRS", {}, [], eventos, False)
        m["documentos"] = [
            dict(eproc.info_do_documento(eventos[0].documentos[0], "pdf"), inicio=1, paginas=2),
            dict(eproc.info_do_documento(eventos[1].documentos[0], "pdf", "ausente"), inicio=3,
                 paginas=1)]
        capa_eproc = eproc.dados_da_capa(n, "eProc do TJRS", "TJRS", {}, [], eventos, False, m)
        for capa, ultima in ((capa_esaj, 6), (capa_eproc, 3)):
            with self.subTest(sistema=capa["sistema"]):
                self.assertEqual(capa["formato"], "helestron.capa/2")
                self.assertIsInstance(capa["paginacao"], dict)
                self.assertIsInstance(capa["paginacao"]["resumo"], str)
                self.assertEqual(capa["paginacao"]["ultima"], ultima)
        self.assertEqual(capa_eproc["paginacao"]["documentos_ausentes"], "ev. 2 PET1")
        self.assertEqual(capa_eproc["paginas_pdf"], 3)
        # sem manifesto, nenhum dos dois traz a chave (o eProc gravava "")
        self.assertNotIn("paginacao", esaj.dados_da_capa({}, n_esaj, "TJAL"))
        self.assertNotIn("paginacao", eproc.dados_da_capa(n, "eProc do TJRS", "TJRS", {}, [],
                                                          eventos, False))


# ======================================================= montagem por documentos
class TestMontagemPorDocumentos(_Base):
    def eventos(self):
        return [
            _ev(1, "10/01/2024", "14:22", "PETIÇÃO INICIAL",
                   [_doc(1, "INIC1", descricao="PETIÇÃO INICIAL"),
                    _doc(1, "PROC2", descricao="PETIÇÃO INICIAL")]),
            _ev(2, "11/01/2024", "", "JUNTADA", [_doc(2, "FOTO1", "jpg", "JUNTADA",
                                                         "11/01/2024")]),
            _ev(3, "12/03/2024", "", "DECISÃO", [_doc(3, "DESPADEC1", "html", "DECISÃO",
                                                         "12/03/2024")]),
            _ev(4, "20/03/2024", "", "JUNTADA DE PETIÇÃO",
                   [_doc(4, "PET1", "pdf", "JUNTADA DE PETIÇÃO", "20/03/2024"),
                    _doc(4, "CORROMPIDO1", "pdf", "JUNTADA DE PETIÇÃO", "20/03/2024")]),
            _ev(5, "01/04/2024", "", "AUDIÊNCIA REALIZADA", []),
            _ev(6, "10/05/2024", "", "SENTENÇA", [_doc(6, "SENT1", "html", "SENTENÇA",
                                                          "10/05/2024")]),
            _ev(7, "15/05/2024", "", "GRAVAÇÃO", [_doc(7, "VIDEO1", "mp4", "GRAVAÇÃO",
                                                          "15/05/2024")]),
            _ev(8, "16/05/2024", "", "JUNTADA", [_doc(8, "ÁUDIO1", "pdf", "JUNTADA",
                                                         "16/05/2024")]),
        ]

    def conteudos(self):
        return {
            "INIC1": ("pdf", _pdf_com_sumario(2, "INIC1", [[1, "Dos fatos", 1],
                                                           [1, "Dos pedidos", 2]]), ""),
            "PROC2": ("pdf", apoio.pdf_bytes(1, "PROC2"), ""),
            "FOTO1": ("imagem", apoio.png_bytes(), ""),
            "DESPADEC1": ("html", "<html><body><p>DECISÃO</p><p>Defiro.</p></body></html>", ""),
            "PET1": eproc._FalhaDocumento("o portal recusou o documento (HTTP 500)"),
            "CORROMPIDO1": ("pdf", b"%PDF-1.4\n" + b"\x00lixo" * 40, ""),
            "SENT1": ("html", "<html><body><p>SENTENÇA</p></body></html>", ""),
            "ÁUDIO1": ("pdf", apoio.pdf_bytes(1, "AUDIO1"), ""),
        }

    def montar(self):
        portal = self.portal()
        conteudos = self.conteudos()

        def obter(doc):
            achado = conteudos[doc.rotulo]
            if isinstance(achado, Exception):
                raise achado
            return achado

        portal._obter_documento = obter
        destino = self.tmp / "Lote" / f"{self.n.nome_arquivo}.pdf"
        r = modelos.ResultadoProcesso(ordem=1, numero=self.n.formatado, tribunal="TJRS",
                                      sistema="eproc")
        info = {"capa": {"classe": "PROCEDIMENTO COMUM CÍVEL", "orgao": "1ª Vara Cível",
                         "magistrado": "FULANA DE TAL"},
                "partes": ["AUTOR: MARIA DA SILVA", "RÉU: BANCO EXEMPLO S.A."], "texto": ""}
        eventos = self.eventos()
        with self.assertLogs("download", "WARNING"):
            portal._montar_documentos(self.n, destino, r, info, eventos)
        portal._gravar_capa(self.n, destino, info, eventos, r.sigiloso)
        return portal, r, destino

    def test_so_as_paginas_dos_documentos_com_a_paginacao_do_eproc(self):
        _, r, destino = self.montar()
        self.assertEqual(r.paginas, 10, "9 documentos, INIC1 com 2 páginas; nenhuma capa")
        self.assertEqual(r.documentos, 9)
        self.assertEqual(r.incompleto, "ev. 4 PET1, ev. 4 CORROMPIDO1")
        with pymupdf.open(destino) as doc:
            rotulos = [p.get_label() for p in doc]
            toc = doc.get_toc()
            texto1 = doc[0].get_text()
            meta = dict(doc.metadata)
            m = paginacao.ler_do_doc(doc)
        self.assertEqual(rotulos, [
            "Ev. 1 INIC1 p. 1", "Ev. 1 INIC1 p. 2", "Ev. 1 PROC2 p. 1", "Ev. 2 FOTO1 p. 1",
            "Ev. 3 DESPADEC1", "Ev. 4 PET1 nao incluido", "Ev. 4 CORROMPIDO1 nao incluido",
            "Ev. 6 SENT1", "Ev. 7 VIDEO1 gravacao", "Ev. 8 AUDIO1 p. 1"])
        self.assertIn("INIC1 1", texto1, "a página 1 é a do primeiro documento, não uma capa")
        self.assertEqual(toc, [
            [1, "Evento 1 — PETIÇÃO INICIAL — INIC1 (10/01/2024)", 1],
            [2, "Dos fatos", 1], [2, "Dos pedidos", 2],
            [1, "Evento 1 — PETIÇÃO INICIAL — PROC2 (10/01/2024)", 3],
            [1, "Evento 2 — JUNTADA — FOTO1 (11/01/2024)", 4],
            [1, "Evento 3 — DECISÃO — DESPADEC1 (12/03/2024)", 5],
            [1, "Evento 4 — JUNTADA DE PETIÇÃO — PET1 (20/03/2024) [NÃO INCLUÍDO]", 6],
            [1, "Evento 4 — JUNTADA DE PETIÇÃO — CORROMPIDO1 (20/03/2024) [NÃO INCLUÍDO]", 7],
            [1, "Evento 6 — SENTENÇA — SENT1 (10/05/2024)", 8],
            [1, "Evento 7 — GRAVAÇÃO — VIDEO1 (15/05/2024) [GRAVAÇÃO — fora do PDF]", 9],
            [1, "Evento 8 — JUNTADA — ÁUDIO1 (16/05/2024)", 10]])
        self.assertEqual(meta["title"], f"Processo {self.n.formatado}")
        self.assertIn("documento a documento", meta["subject"])
        self.assertTrue(meta["creator"].startswith("Helestron"))
        self.assertTrue(meta["keywords"].startswith(
            "helestron;sistema=eproc;paginacao=documento;formato=1;modo=documentos"))
        # o manifesto: o que o texto dos autos, o MCP e o preparo leem
        self.assertEqual((m["sistema"], m["paginacao"], m["modo"], m["tribunal"], m["processo"]),
                         ("eproc", "documento", "documentos", "TJRS", self.n.formatado))
        self.assertEqual(m["capa"]["partes"], ["AUTOR: MARIA DA SILVA", "RÉU: BANCO EXEMPLO S.A."])
        self.assertEqual(m["capa"]["classe"], "PROCEDIMENTO COMUM CÍVEL")
        self.assertNotIn("partes", m)
        self.assertEqual(m["eventos_sem_documento"],
                         [{"evento": 5, "descricao": "AUDIÊNCIA REALIZADA", "data": "01/04/2024"}])
        resumo = [(d["rotulo"], d["origem"], d["situacao"], d["inicio"], d["paginas"])
                  for d in m["documentos"]]
        self.assertEqual(resumo, [
            ("INIC1", "pdf", "ok", 1, 2), ("PROC2", "pdf", "ok", 3, 1),
            ("FOTO1", "imagem", "ok", 4, 1), ("DESPADEC1", "html", "ok", 5, 1),
            ("PET1", "pdf", "ausente", 6, 1), ("CORROMPIDO1", "pdf", "ausente", 7, 1),
            ("SENT1", "html", "ok", 8, 1), ("VIDEO1", "midia", "midia", 9, 1),
            ("ÁUDIO1", "pdf", "ok", 10, 1)])
        por_rotulo = {d["rotulo"]: d for d in m["documentos"]}
        self.assertIn("HTTP 500", por_rotulo["PET1"]["motivo"])
        self.assertIn("inválido", por_rotulo["CORROMPIDO1"]["motivo"])
        self.assertNotIn("arquivo", por_rotulo["VIDEO1"], "gravação não baixada")
        self.assertEqual(por_rotulo["INIC1"]["evento"], 1)

    def test_texto_dos_autos_cita_pela_paginacao_do_eproc(self):
        # O contrato com o compartilhamento: as marcas saem do manifesto
        _, _, destino = self.montar()
        texto = textos.texto_pdf(destino)
        self.assertIn("=== [evento 1, INIC1, p. 2] (pág. 2 do PDF) ===", texto)
        self.assertIn("=== [evento 3, DESPADEC1] (pág. 5 do PDF) ===", texto)
        self.assertIn("=== [evento 4, PET1 — NÃO INCLUÍDO] (pág. 6 do PDF) ===", texto)
        self.assertIn("=== [evento 7, VIDEO1 — gravação fora do PDF] (pág. 9 do PDF) ===", texto)
        self.assertIn("PROCEDIMENTO COMUM CÍVEL", textos.preambulo(texto))
        self.assertIn("5 — AUDIÊNCIA REALIZADA", textos.preambulo(texto))
        self.assertNotIn("=== [capa gerada pelo Helestron", texto)

    def test_capa_txt_e_json(self):
        _, r, destino = self.montar()
        controle = destino.parent / "_controle"
        capa = (controle / f"{self.n.nome_arquivo}_capa.txt").read_text(encoding="utf-8")
        for trecho in (
                "== Capa ==\nClasse: PROCEDIMENTO COMUM CÍVEL",
                "== Partes ==\nAUTOR: MARIA DA SILVA",
                "== Arquivo ==",
                "Eventos: 8; documentos: 9; páginas do PDF: 10.",
                "Documentos não incluídos (2): ev. 4 PET1, ev. 4 CORROMPIDO1",
                "Gravações (áudio ou vídeo) fora do PDF (1): ev. 7 VIDEO1",
                "== Como citar ==",
                "== Mapa de documentos (9) ==",
                "Evento 1 — PETIÇÃO INICIAL — INIC1 (10/01/2024) — págs. 1–2 do PDF (2 págs.; "
                "p. 1–2 no eProc)",
                "Evento 3 — DECISÃO — DESPADEC1 (12/03/2024) — pág. 5 do PDF (texto do próprio "
                "eProc, sem paginação: cite sem página)",
                "Evento 4 — JUNTADA DE PETIÇÃO — PET1 (20/03/2024) — pág. 6 do PDF — NÃO "
                "INCLUÍDO (página de aviso): o portal recusou o documento (HTTP 500)",
                "Evento 7 — GRAVAÇÃO — VIDEO1 (15/05/2024) — pág. 9 do PDF — gravação fora do "
                "PDF (página de aviso); não baixada",
                "== Eventos (8) ==", "01/04/2024  Evento 5 - AUDIÊNCIA REALIZADA"):
            self.assertIn(trecho, capa)
        self.assertNotIn("SEGREDO", capa)
        d = json.loads((controle / f"{self.n.nome_arquivo}_capa.json").read_text(encoding="utf-8"))
        self.assertEqual((d["formato"], d["sistema"], d["modo"], d["paginas_pdf"]),
                         ("helestron.capa/2", "eproc", "documentos", 10))
        self.assertEqual(d["partes"], ["AUTOR: MARIA DA SILVA", "RÉU: BANCO EXEMPLO S.A."])
        self.assertEqual(len(d["documentos"]), 9)
        self.assertEqual(len(d["eventos"]), 8)
        self.assertEqual(d["eventos"][0]["documentos"], ["INIC1", "PROC2"])
        self.assertEqual([e["evento"] for e in d["eventos_sem_documento"]], [5])
        self.assertTrue(d["eventos_completos"])
        # "paginacao" é um objeto, como no e-SAJ (era o texto do resumo)
        self.assertEqual(d["paginacao"], {
            "resumo": "paginação de cada documento igual à do eProc (9 documentos); "
                      "3 não incluídos no PDF",
            "ultima": 10, "documentos_ausentes": "ev. 4 PET1, ev. 4 CORROMPIDO1"})
        self.assertEqual(d["paginacao"]["documentos_ausentes"], r.incompleto)

    def test_gravacao_salva_vai_no_manifesto_com_o_caminho(self):
        portal = self.portal(baixar_midias=True)
        portal._obter_documento = lambda doc: (
            ("midia", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 300, ".mp4") if doc.rotulo == "VIDEO1"
            else ("pdf", apoio.pdf_bytes(1, doc.rotulo), ""))
        destino = self.tmp / "Lote" / f"{self.n.nome_arquivo}.pdf"
        r = modelos.ResultadoProcesso(ordem=1, numero=self.n.formatado, tribunal="TJRS",
                                      sistema="eproc")
        eventos = [_ev(1, "01/01/2024", "", "INICIAL", [_doc(1, "INIC1")]),
                   _ev(2, "02/01/2024", "", "GRAVAÇÃO", [_doc(2, "VIDEO1", "mp4")])]
        portal._montar_documentos(self.n, destino, r, {"capa": {}, "partes": []}, eventos)
        m = paginacao.ler_do_pdf(destino)
        video = m["documentos"][1]
        self.assertEqual((video["situacao"], video["origem"]), ("midia", "midia"))
        self.assertEqual(video["arquivo"],
                         f"_controle/midias/{self.n.nome_arquivo}/Evento 2 - VIDEO1.mp4")
        self.assertEqual(r.incompleto, "")
        self.assertEqual(len(r.midias), 1)


# ============================================================ Download Completo
class TestDownloadCompletoSemNavegador(_Base):
    def baixar(self, arquivos, eventos=None):
        portal = self.portal()
        portal._gerar_completo = lambda numero: list(arquivos)
        portal._voltar_ao_processo = mock.Mock()
        destino = self.tmp / "Lote" / f"{self.n.nome_arquivo}.pdf"
        r = modelos.ResultadoProcesso(ordem=1, numero=self.n.formatado, tribunal="TJRS",
                                      sistema="eproc")
        info = {"capa": {"classe": "PROCEDIMENTO COMUM"}, "partes": ["AUTOR: MARIA"],
                "eventos": eventos or []}
        ok = portal._baixar_completo(self.n, destino, r, info, eventos)
        return portal, r, destino, ok

    def test_arquivo_unico_entra_intacto(self):
        original = _pdf_com_sumario(5, "COMPLETO", [[1, "Evento 1 - INIC1", 1],
                                                     [1, "Evento 2 - CONT1", 4]])
        eventos = [_ev(1, "01/01/2024", "", "INICIAL", [_doc(1, "INIC1")]),
                   _ev(2, "02/01/2024", "", "CONTESTAÇÃO", [_doc(2, "CONT1")]),
                   _ev(3, "03/01/2024", "", "CONCLUSOS", [])]
        portal, r, destino, ok = self.baixar([original], eventos)
        self.assertTrue(ok)
        self.assertEqual(r.paginas, 5, "a página M do PDF é a página M do arquivo do eProc")
        self.assertTrue(destino.read_bytes().startswith(original),
                        "os bytes do eProc ficam como vieram (salvamento incremental)")
        with pymupdf.open(destino) as doc:
            self.assertEqual([p.get_text().strip() for p in doc],
                             [f"COMPLETO {i}" for i in range(1, 6)])
            self.assertEqual(doc.get_toc(), [[1, "Evento 1 - INIC1", 1], [1, "Evento 2 - CONT1", 4]],
                             "o sumário do próprio eProc fica")
            self.assertIn("modo=completo", doc.metadata["keywords"])
            m = paginacao.ler_do_doc(doc)
        self.assertEqual((m["modo"], m["documentos"], m["partes"]),
                         ("completo", [], [{"inicio": 1, "paginas": 5}]))
        self.assertEqual(m["capa"]["partes"], ["AUTOR: MARIA"])
        self.assertEqual([e["evento"] for e in m["eventos_sem_documento"]], [3])
        portal._gravar_capa(self.n, destino, {"capa": {"classe": "PROCEDIMENTO COMUM"},
                                              "partes": ["AUTOR: MARIA"]}, eventos, False)
        capa = (destino.parent / "_controle" / f"{self.n.nome_arquivo}_capa.txt").read_text(
            encoding="utf-8")
        self.assertIn("Download Completo", capa)
        self.assertIn("a página M do PDF é a página M desse arquivo", capa)
        self.assertIn("Eventos: 3; documentos: 2.", capa)
        self.assertIn("== Mapa de documentos (2) ==", capa)
        # o resumo da paginação (capa.json, JSON do baixar, INDICE.md) diz o
        # que o arquivo é; dizia "... igual à do eProc (0 documentos)"
        d = json.loads((destino.parent / "_controle" / f"{self.n.nome_arquivo}_capa.json")
                       .read_text(encoding="utf-8"))
        self.assertEqual(d["paginacao"], {
            "resumo": "arquivo completo do eProc (Download Completo), sem página acrescentada: "
                      "página M do PDF = página M do arquivo",
            "ultima": 5, "documentos_ausentes": ""})
        portal._voltar_ao_processo.assert_not_called()

    def test_arquivo_sem_sumario_ganha_um_marcador(self):
        portal, r, destino, ok = self.baixar([apoio.pdf_bytes(3, "COMPLETO")])
        self.assertTrue(ok)
        with pymupdf.open(destino) as doc:
            self.assertEqual(doc.get_toc(), [[1, eproc.TITULO_COMPLETO, 1]])
            self.assertEqual(len(doc), 3)
            m = paginacao.ler_do_doc(doc)
        self.assertNotIn("eventos_sem_documento", m, "lista de eventos não lida: nada de meia")
        # a capa avisa que a lista de eventos é só a da primeira página
        primeira = [_ev(9, "09/01/2024", "", "SENTENÇA", [_doc(9, "SENT1")])]
        portal._gravar_capa(self.n, destino, {"capa": {}, "partes": []}, primeira, False,
                            eventos_completos=False)
        capa = (destino.parent / "_controle" / f"{self.n.nome_arquivo}_capa.txt").read_text(
            encoding="utf-8")
        self.assertIn("Lista de eventos incompleta", capa)
        self.assertIn("== Mapa de documentos (1) ==\n(lista incompleta", capa)
        self.assertIn("== Eventos (1) ==\n(lista incompleta", capa)
        d = json.loads((destino.parent / "_controle" / f"{self.n.nome_arquivo}_capa.json")
                       .read_text(encoding="utf-8"))
        self.assertFalse(d["eventos_completos"])
        self.assertEqual(d["eventos_sem_documento"], [])

    def test_zip_em_partes_sem_pagina_acrescentada(self):
        _, r, destino, ok = self.baixar([apoio.pdf_bytes(2, "PARTE-A"),
                                          apoio.pdf_bytes(3, "PARTE-B")])
        self.assertTrue(ok)
        self.assertEqual(r.paginas, 5)
        with pymupdf.open(destino) as doc:
            self.assertEqual([p.get_label() for p in doc],
                             ["Parte 1 p. 1", "Parte 1 p. 2", "Parte 2 p. 1", "Parte 2 p. 2",
                              "Parte 2 p. 3"])
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 3])
            self.assertIn("PARTE-A 1", doc[0].get_text())
            m = paginacao.ler_do_doc(doc)
        self.assertEqual(m["partes"], [{"inicio": 1, "paginas": 2}, {"inicio": 3, "paginas": 3}])
        self.assertEqual(m["documentos"], [])

    def test_arquivo_que_nao_abre_cai_para_documentos(self):
        with self.assertLogs("download.eproc", "WARNING"):
            portal, r, destino, ok = self.baixar([b"%PDF-1.4\n" + b"\x00lixo" * 400])
        self.assertFalse(ok)
        self.assertFalse(destino.exists())
        portal._voltar_ao_processo.assert_called_once()
        self.assertIn("o Download Completo do eProc falhou", portal._notas[0])


class TestEventosAntesDoCompleto(_Base):
    def test_paginacao_que_falha_nao_impede_o_completo(self):
        portal = self.portal()
        portal._voltar_ao_processo = mock.Mock()

        def todos(primeiros, rotulo):
            portal._paginou = True
            raise RuntimeError("a página 2 dos eventos não abriu (paginação do eProc)")

        portal._todos_os_eventos = todos
        with self.assertLogs("download.eproc", "WARNING"):
            eventos = portal._eventos_antes_do_completo(self.n, {"eventos": []}, "x")
        self.assertIsNone(eventos)
        portal._voltar_ao_processo.assert_called_once()

    def test_sem_paginacao_nao_sai_da_pagina(self):
        portal = self.portal()
        portal._voltar_ao_processo = mock.Mock()
        lidos = [_ev(1, "01/01/2024", "", "INICIAL", [_doc(1, "INIC1")])]
        portal._todos_os_eventos = lambda primeiros, rotulo: primeiros
        self.assertEqual(portal._eventos_antes_do_completo(self.n, {"eventos": lidos}, "x"),
                         lidos)
        portal._voltar_ao_processo.assert_not_called()


# ============================================================== eventos de login
class TestEventosDeLogin(_Base):
    def test_login_na_janela(self):
        for modo, motivo in (("manual", "manual"), ("certificado", "certificado")):
            with self.subTest(modo=modo):
                ctx = ContextoComEventos()
                portal = self.portal(ctx, login={"eproc": modo}, espera_login_min=3)
                portal._dormir = lambda s: None
                portal._restaurar_janela = lambda: None
                etapas = iter(["login", "login", "logado"])
                portal._etapa_em_alguma_aba = lambda: next(etapas)
                antes = datetime.now()
                portal._login_na_janela()
                self.assertEqual([t for t, _ in ctx.eventos],
                                 ["login_aguardando", "login_concluido"])
                dados = ctx.eventos[0][1]
                self.assertEqual({k: dados[k] for k in ("sistema", "tribunal", "modo",
                                                         "prazo_min", "motivo")},
                                 {"sistema": "eproc", "tribunal": "TJRS", "modo": modo,
                                  "prazo_min": 3, "motivo": motivo})
                ate = datetime.fromisoformat(dados["ate"])
                self.assertGreater((ate - antes).total_seconds(), 170)
                self.assertEqual(ctx.eventos[1][1], {"sistema": "eproc", "tribunal": "TJRS"})
                # o evento sai ANTES do aviso de esperar
                self.assertEqual(len(ctx.avisos), 1)

    def test_captcha_e_perfil_sao_acao_na_janela(self):
        for etapa, motivo in (("captcha", "captcha"), ("perfil", "perfil")):
            with self.subTest(etapa=etapa):
                ctx = ContextoComEventos()
                portal = self.portal(ctx, espera_login_min=2)
                portal._dormir = lambda s: None
                portal._restaurar_janela = lambda: None
                botao = mock.Mock()
                botao.get_attribute.side_effect = ["JUIZ", "DIRETOR"]
                portal._perfis_na_tela = lambda: [botao, mock.Mock(
                    get_attribute=mock.Mock(return_value="DIRETOR"))]
                portal._etapa = lambda pagina=None, apos_envio=False: "logado"
                portal._login_com_senha(etapa)
                self.assertEqual([t for t, _ in ctx.eventos],
                                 ["acao_na_janela", "login_concluido"])
                dados = ctx.eventos[0][1]
                self.assertEqual((dados["motivo"], dados["sistema"], dados["modo"]),
                                 (motivo, "eproc", "senha"))
                self.assertLessEqual(dados["prazo_min"], 2)
                self.assertTrue(dados["ate"])

    def test_codigo_sem_terminal_espera_na_janela(self):
        """A linha de comando sem terminal (a skill roda 'baixar --desanexar',
        stdin = DEVNULL): pedir_codigo devolve None na hora. Com a janela à
        vista, o eProc espera o código digitado nela, no prazo do login, como o
        e-SAJ; antes, desistia em 0 s, sem evento nenhum."""
        ctx = ContextoComEventos(codigos=[])            # ninguém para digitar aqui
        portal = self.portal(ctx, espera_login_min=3)
        portal._dormir = lambda s: None
        portal._restaurar_janela = lambda: None
        etapas = iter(["otp", "otp", "otp", "logado"])  # o usuário digita na janela
        portal._etapa_em_alguma_aba = lambda: next(etapas)
        portal._etapa = lambda pagina=None, apos_envio=False: "logado"
        antes = datetime.now()
        portal._login_com_senha("otp")
        self.assertEqual(len(ctx.pedidos_codigo), 1)
        self.assertEqual([t for t, _ in ctx.eventos], ["login_aguardando", "login_concluido"])
        dados = ctx.eventos[0][1]
        self.assertEqual((dados["motivo"], dados["modo"], dados["sistema"], dados["prazo_min"]),
                         ("codigo", "senha", "eproc", 3))
        self.assertGreater((datetime.fromisoformat(dados["ate"]) - antes).total_seconds(), 170)
        titulo, mensagem = ctx.avisos[-1]
        self.assertEqual(titulo, "Digite o código na janela do eProc do TJRS")
        self.assertIn("aplicativo autenticador na janela do navegador", mensagem)
        self.assertIn("Aguardo até 3 minutos", mensagem)
        self.assertEqual(portal.nav.diagnosticos, [])

    def test_codigo_na_janela_tem_o_prazo_do_login(self):
        ctx = ContextoComEventos(codigos=[])
        portal = self.portal(ctx, espera_login_min=2)
        portal._dormir = lambda s: time.sleep(0.01)
        portal._restaurar_janela = lambda: None
        portal._etapa_em_alguma_aba = lambda: "otp"     # o código nunca é digitado
        with self.assertRaises(modelos.LoginFalhou) as caso:
            portal._resolver_codigo(0, "", time.monotonic() + 0.1)
        self.assertIn("o prazo de 2 minutos para concluir o login no eProc do TJRS acabou sem o "
                      "código do aplicativo autenticador", str(caso.exception))
        self.assertEqual([t for t, _ in ctx.eventos], ["login_aguardando"])
        self.assertEqual(portal.nav.diagnosticos, ["eproc-codigo-prazo"])
        # com a janela oculta, ninguém pode digitar: desiste na hora, sem evento
        ctx = ContextoComEventos(codigos=[])
        portal = self.portal(ctx, nav=_Nav(visivel=False))
        portal._etapa_em_alguma_aba = lambda: "otp"
        with self.assertRaises(modelos.LoginFalhou) as caso:
            portal._resolver_codigo(0, "", time.monotonic() + 300)
        self.assertIn("código do aplicativo autenticador não foi informado", str(caso.exception))
        self.assertEqual(ctx.eventos, [])
        self.assertEqual(portal.nav.diagnosticos, ["eproc-codigo-nao-informado"])

    def test_login_sem_espera_nao_publica_nada(self):
        ctx = ContextoComEventos()
        portal = self.portal(ctx)
        portal._login_com_senha("logado")
        self.assertEqual(ctx.eventos, [])

    def test_contexto_sem_evento_ou_que_falha_nao_derruba_o_login(self):
        for ctx in (apoio.ContextoGravador(), ContextoComEventos(falhar=True)):
            with self.subTest(ctx=type(ctx).__name__):
                portal = self.portal(ctx, login={"eproc": "manual"})
                portal._dormir = lambda s: None
                portal._restaurar_janela = lambda: None
                portal._etapa_em_alguma_aba = lambda: "logado"
                portal._login_na_janela()


if __name__ == "__main__":
    unittest.main()
