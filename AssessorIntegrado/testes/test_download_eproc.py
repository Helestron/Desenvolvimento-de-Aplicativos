"""eProc sem navegador: leitura do HTML (eventos, capa, partes, paginação),
ordenação dos documentos, links, tipos de conteúdo, sessão, sigilo,
seletores configuráveis e a janela pelo CDP.

O ponta a ponta, com Chromium de verdade e um eProc de mentira, está em
test_download_eproc_integracao.py.
"""

from __future__ import annotations

import io
import json
import unittest
import zipfile
from dataclasses import replace
from datetime import datetime

from app.download import eproc, modelos
from app.download.eproc import (Documento, Evento, PortalEProc, buscar, decodificar_html,
                                descrever_faltantes, diz_nao_encontrado, diz_sem_acesso,
                                html_em_utf8, indica_sigilo, ler_capa, ler_eventos, ler_html,
                                ler_partes, link_assinado_da_consulta, motivo_sessao,
                                normalizar_base, opcoes_de_paginacao, ordenar_documentos,
                                ordenar_eventos, primeiro, src_do_iframe, tipo_do_conteudo,
                                titulo_do_documento, url_ajax_consulta, url_implementacao)
from app.nucleo import tribunais

from testes import apoio_download as apoio

# Uma página de processo como o eProc a serve (recortada): números com
# &nbsp;, o ícone e o texto do mesmo documento como dois links, evento sem
# documento, descrição com complemento, usuário com aria-label.
PAGINA_1 = """
<div id="divInfraBarraSistema"><input type="text" name="txtNumProcessoPesquisaRapida"></div>
<fieldset id="fldCapa"><legend>Capa do Processo</legend>
 <span id="txtNumProcesso">5001234-56.2024.8.21.0001</span>
 <span id="txtClasse">PROCEDIMENTO COMUM CÍVEL</span>
 <span id="txtCompetencia">Cível</span>
 <span id="txtAutuacao">10/01/2024 14:22:01</span>
 <span id="txtSituacao">MOVIMENTO</span>
 <span id="txtOrgaoJulgador">Juízo da 1ª Vara Cível</span>
 <span id="txtMagistrado">FULANA DE TAL</span>
</fieldset>
<table id="tblPartesERepresentantes"><tr><th>AUTOR</th><th>RÉU</th></tr>
 <tr class="infraTrClara"><td class="autorReu"><a class="infraNomeParte">MARIA DA SILVA</a>
  <span id="spnCpfParte1">123.456.789-00</span> Advogado: <a>RS012345</a></td>
  <td class="autorReu"><a class="infraNomeParte">BANCO EXEMPLO S.A.</a>
  <a class="infraNomeParte">OUTRO RÉU LTDA</a></td></tr></table>
Página: <select id="selPaginacaoT" onchange="alterarPagina(this.value)">
 <option value="0" selected>1</option><option value="1">2</option></select>
<table id="tblEventos" class="infraTable">
 <tr><th>Evento</th><th>Data/Hora</th><th>Descrição</th><th>Usuário</th><th>Documentos</th></tr>
 <tr id="trEvento5" class="infraTrClara"><td>5&nbsp;</td><td>01/04/2024&nbsp;15:00:00</td>
  <td><label class="infraEventoDescricao">AUDIÊNCIA REALIZADA</label></td>
  <td><label class="infraEventoUsuario" aria-label="FULANO<br>Servidor">USR01</label></td>
  <td>Evento não gerou documento(s)</td></tr>
 <tr id="trEvento4" class="infraTrEscura"><td><span>4</span><script>var x = 1;</script></td>
  <td>20/03/2024 11:11:11</td>
  <td><label class="infraEventoDescricao">JUNTADA DE PETIÇÃO</label> - Refer. ao Evento 2</td>
  <td><label class="infraEventoUsuario">ADV01</label></td>
  <td><a class="infraLinkDocumento" href="controlador.php?acao=acessar_documento&amp;doc=401&amp;evento=4&amp;key=abc&amp;hash=h4"><img src="pdf.gif"></a>
      <a class="infraLinkDocumento" data-doc="401" data-mimetype="pdf" title="Petição"
         href="controlador.php?acao=acessar_documento&amp;doc=401&amp;evento=4&amp;key=abc&amp;hash=h4">PET1</a>
      <a class="infraLinkDocumento" data-doc="402" data-mimetype="html" title="Anexo"
         href="controlador.php?acao=acessar_documento&amp;doc=402&amp;evento=4&amp;key=abc&amp;hash=h4b">OUT2</a>
      <a class="infraLinkDocumento" data-doc="101" data-mimetype="pdf"
         href="controlador.php?acao=acessar_documento&amp;doc=101&amp;evento=4&amp;key=abc&amp;hash=hx">INIC1</a></td></tr>
</table>
"""

PAGINA_2 = """
<select id="selPaginacaoT"><option value="0">1</option><option value="1" selected>2</option></select>
<table id="tblEventos">
 <tr id="trEvento3" class="infraTrClara"><td>3</td><td>12/03/2024 16:40:12</td>
  <td><label class="infraEventoDescricao">DECISÃO INTERLOCUTÓRIA</label></td><td></td>
  <td><a class="infraLinkDocumento" data-doc="301" data-mimetype="html"
         href="controlador.php?acao=acessar_documento&amp;doc=301&amp;hash=h3">DESPADEC1</a></td></tr>
 <tr id="trEvento1" class="infraTrClara"><td>1</td><td>10/01/2024 14:22:01</td>
  <td><label class="infraEventoDescricao">PETIÇÃO INICIAL</label></td><td></td>
  <td><a class="infraLinkDocumento" data-doc="101" data-mimetype="pdf"
         href="controlador.php?acao=acessar_documento&amp;doc=101&amp;hash=h1">INIC1</a>
      <a class="infraLinkDocumento" data-doc="102" data-mimetype="jpg"
         href="controlador.php?acao=acessar_documento&amp;doc=102&amp;hash=h1b">FOTO2</a></td></tr>
 <tr id="trEvento2" class="infraTrEscura"><td>2</td><td>11/01/2024 09:00:00</td>
  <td><label class="infraEventoDescricao">JUNTADA</label></td><td></td>
  <td><a data-doc="201" href="controlador.php?acao=acessar_documento&amp;doc=201&amp;hash=h2">PROC1</a></td></tr>
</table>
"""


class TestLeituraDeHtml(unittest.TestCase):
    def test_texto_sem_script_e_com_fronteiras(self):
        raiz = ler_html("<div>Certi<b>fico</b><script>lixo()</script>"
                        "<a>INIC1</a><a>PROC2</a>&nbsp;fim<style>x{}</style></div>")
        self.assertEqual(raiz.texto(), "Certifico INIC1 PROC2 fim")

    def test_fechamentos_implicitos_de_tabela(self):
        raiz = ler_html("<table><tr><td>a<td>b<tr><td>c</table><p>depois")
        linhas = [n for n in raiz.elementos() if n.tag == "tr"]
        self.assertEqual(len(linhas), 2)
        self.assertEqual([len([c for c in tr.filhos if c.tag == "td"]) for tr in linhas], [2, 1])
        self.assertEqual(primeiro(raiz, "p").texto(), "depois")

    def test_seletores_css_simples(self):
        raiz = ler_html(
            "<div id='a' class='x y'><table id='t'><tr id='trEvento1'><td>"
            "<a class='infraLinkDocumento' href='c.php?acao=acessar_documento&amp;doc=1'>A</a>"
            "<a href='c.php?ACAO=Outra' data-mimetype='PDF'>B</a></td></tr></table></div>"
            "<span class='x'>fora</span>")
        def textos(sel):
            return [n.texto() for n in buscar(raiz, sel)]
        self.assertEqual(textos("tr[id^='trEvento'] a.infraLinkDocumento"), ["A"])
        self.assertEqual(textos("a[href*='acao=acessar_documento']"), ["A"])
        self.assertEqual(textos("a[data-mimetype='pdf' i]"), ["B"])
        self.assertEqual(textos("a[href$='Outra']"), ["B"])
        self.assertEqual(textos("div.x.y > table td > a"), ["A", "B"])
        self.assertEqual(textos("div.x.y > td a"), [])                  # td não é filho de div
        self.assertEqual(textos("#t td > a"), ["A", "B"])
        self.assertEqual(textos(".x"), ["A B", "fora"])
        self.assertEqual(textos("#nada, span.x"), ["fora"])
        # alternativa fora do CSS simples é ignorada aqui (vale no navegador)
        self.assertEqual(textos(["button:has-text('Entrar')", "span"]), ["fora"])
        self.assertEqual(primeiro(raiz, ["#nada", "a", "span"]).texto(), "A")


class TestEventos(unittest.TestCase):
    def test_le_uma_pagina(self):
        eventos = ler_eventos(PAGINA_1)
        self.assertEqual([e.numero for e in eventos], [5, 4])
        e5, e4 = eventos
        self.assertEqual((e5.data, e5.hora), ("01/04/2024", "15:00:00"))
        self.assertEqual(e5.descricao, "AUDIÊNCIA REALIZADA")
        self.assertEqual(e5.usuario, "USR01")
        self.assertEqual(e5.documentos, [])
        self.assertEqual(e4.descricao, "JUNTADA DE PETIÇÃO")
        # o ícone e o texto do PET1 são um documento só, com rótulo e tipo
        self.assertEqual([(d.rotulo, d.id, d.mimetype) for d in e4.documentos],
                         [("PET1", "401", "pdf"), ("OUT2", "402", "html"), ("INIC1", "101", "pdf")])
        self.assertEqual(e4.documentos[0].href,
                         "controlador.php?acao=acessar_documento&doc=401&evento=4&key=abc&hash=h4")

    def test_ordena_do_mais_antigo_ao_mais_novo_entre_paginas(self):
        todos = eproc.juntar_paginas(ler_eventos(PAGINA_1), ler_eventos(PAGINA_2),
                                     ler_eventos(PAGINA_1))
        self.assertEqual([e.numero for e in ordenar_eventos(todos)], [1, 2, 3, 4, 5])
        docs = ordenar_documentos(todos)
        # INIC1 aparece também no evento 4: entra uma vez, no evento 1
        self.assertEqual([(d.evento, d.rotulo) for d in docs],
                         [(1, "INIC1"), (1, "FOTO2"), (2, "PROC1"), (3, "DESPADEC1"),
                          (4, "PET1"), (4, "OUT2")])

    def test_sem_numero_vale_a_data_e_depois_a_posicao(self):
        def ev(data, desc):
            return Evento(0, data, "", desc, documentos=[
                Documento(0, data, "", desc, desc, f"x?doc={desc}", id=desc)])
        # a lista da página vem do mais novo para o mais antigo
        eventos = [ev("02/02/2024", "C"), ev("01/02/2024", "B2"), ev("01/02/2024", "B1"),
                   ev("31/01/2024", "A")]
        self.assertEqual([d.rotulo for d in ordenar_documentos(eventos)], ["A", "B1", "B2", "C"])

    def test_paginacao(self):
        self.assertEqual(opcoes_de_paginacao(PAGINA_1), (["0", "1"], "0"))
        self.assertEqual(opcoes_de_paginacao(PAGINA_2), (["0", "1"], "1"))
        self.assertEqual(opcoes_de_paginacao("<table id='tblEventos'></table>"), ([], ""))

    def test_titulo_e_faltantes(self):
        doc = Documento(3, "12/03/2024", "16:40", "DECISÃO INTERLOCUTÓRIA", "DESPADEC1", "x")
        self.assertEqual(titulo_do_documento(doc),
                         "Evento 3 — DECISÃO INTERLOCUTÓRIA — DESPADEC1 (12/03/2024)")
        longo = replace(doc, descricao="X" * 200)
        titulo = titulo_do_documento(longo)
        self.assertIn("…", titulo)
        self.assertLess(len(titulo), 130)
        docs = [replace(doc, evento=i, rotulo=f"PET{i}") for i in range(1, 16)]
        self.assertEqual(descrever_faltantes(docs[:2]), "ev. 1 PET1, ev. 2 PET2")
        self.assertTrue(descrever_faltantes(docs).endswith("e mais 3"))

    def test_capa_e_partes(self):
        capa = ler_capa(PAGINA_1)
        self.assertEqual(capa["numero"], "5001234-56.2024.8.21.0001")
        self.assertEqual(capa["classe"], "PROCEDIMENTO COMUM CÍVEL")
        self.assertEqual(capa["orgao"], "Juízo da 1ª Vara Cível")
        self.assertEqual(capa["magistrado"], "FULANA DE TAL")
        self.assertEqual(ler_partes(PAGINA_1),
                         ["AUTOR: MARIA DA SILVA", "RÉU: BANCO EXEMPLO S.A.; OUTRO RÉU LTDA"])

    def test_seletor_configurado_vale_no_parser(self):
        html = ("<table id='listaEventos'><tr class='evento'><td>9</td><td>01/02/2024</td>"
                "<td><span class='desc'>CITAÇÃO</span></td><td></td>"
                "<td><a class='doc' href='c.php?acao=acessar_documento&amp;doc=9'>CIT1</a></td>"
                "</tr></table>")
        self.assertEqual(ler_eventos(html), [])
        sel = dict(eproc.SELETORES_PADRAO, eventos_tabela=["#listaEventos"],
                   eventos_linha=["tr.evento"], evento_descricao=["span.desc"])
        (ev,) = ler_eventos(html, sel)
        self.assertEqual((ev.numero, ev.descricao, [d.rotulo for d in ev.documentos]),
                         (9, "CITAÇÃO", ["CIT1"]))


class TestLinks(unittest.TestCase):
    def test_url_implementacao_so_troca_a_acao(self):
        href = ("https://e/eproc/controlador.php?acao=acessar_documento&doc=711&evento=7"
                "&key=ab%2Bcd&nome_documento=PET%201&hash=0f0f")
        self.assertEqual(url_implementacao(href),
                         "https://e/eproc/controlador.php?acao=acessar_documento_implementacao"
                         "&acao_origem=acessar_documento&doc=711&evento=7&key=ab%2Bcd"
                         "&nome_documento=PET%201&hash=0f0f")
        com_origem = "c.php?acao=acessar_documento&acao_origem=processo_selecionar&doc=1&hash=h"
        self.assertEqual(url_implementacao(com_origem),
                         "c.php?acao=acessar_documento_implementacao&acao_origem=acessar_documento"
                         "&doc=1&hash=h")
        pronto = "c.php?acao=acessar_documento_implementacao&doc=1&hash=h"
        self.assertEqual(url_implementacao(pronto), pronto)
        self.assertEqual(url_implementacao("c.php?acao=processo_selecionar&hash=h"), "")
        self.assertEqual(url_implementacao(""), "")

    def test_src_da_moldura(self):
        base = "https://e/eproc/controlador.php?acao=acessar_documento&doc=1"
        self.assertEqual(
            src_do_iframe("<iframe id='conteudoIframe' src='controlador.php?acao=acessar_documento"
                          "_implementacao&amp;doc=1&amp;hash=x'></iframe>", base),
            "https://e/eproc/controlador.php?acao=acessar_documento_implementacao&doc=1&hash=x")
        por_campos = src_do_iframe(
            "<form><input name='doc' value='1'><input name='evento' value='2'>"
            "<input name='key' value='k'><input name='nome_documento' value='PET1'>"
            "<input name='hash' value='h'></form>", base)
        self.assertTrue(por_campos.startswith("https://e/eproc/controlador.php?acao=acessar_documento"
                                              "_implementacao&acao_origem=acessar_documento&doc=1"))
        self.assertIn("&hash=h", por_campos)
        por_script = src_do_iframe(
            "<script>var u = 'controlador.php?acao=acessar_documento_implementacao&amp;doc=3"
            "&amp;hash=z';</script>", base)
        self.assertEqual(por_script, "https://e/eproc/controlador.php?acao=acessar_documento"
                                     "_implementacao&doc=3&hash=z")
        self.assertEqual(src_do_iframe("<iframe id='conteudoIframe' src='about:blank'></iframe>",
                                       base), "")

    def test_consulta_por_ajax(self):
        html = ("<script>var u='controlador_ajax.php?acao_ajax=processos_consulta_por_numprocesso"
                "&amp;hash=9f8e7d';</script>")
        self.assertEqual(url_ajax_consulta(html), "controlador_ajax.php?acao_ajax=processos_"
                                                  "consulta_por_numprocesso&hash=9f8e7d")
        achado = json.dumps({"resultados": [
            {"numProcesso": "5009999-00.2024.8.21.0001", "linkProcessoAssinado": "outro"},
            {"numProcesso": "5001234-56.2024.8.21.0001",
             "linkProcessoAssinado": "controlador.php?acao=processo_selecionar&hash=a"}]})
        self.assertEqual(link_assinado_da_consulta(achado, "50012345620248210001"),
                         "controlador.php?acao=processo_selecionar&hash=a")
        self.assertEqual(link_assinado_da_consulta('{"resultados": []}', "1"), "")
        self.assertEqual(link_assinado_da_consulta("Processo não encontrado.", "1"), "")
        self.assertIsNone(link_assinado_da_consulta("<html>erro</html>", "1"))
        self.assertIsNone(link_assinado_da_consulta('{"x": 1}', "1"))


class TestTextosDaTela(unittest.TestCase):
    def test_sessao(self):
        self.assertEqual(motivo_sessao(
            "<textarea id='txaInfraMsg'>A sessão foi encerrada. Entre de novo.</textarea>"),
            "encerrada")
        self.assertEqual(motivo_sessao(
            "<form><input id='txtUsuario'><input id='pwdSenha' type='password'></form>"), "login")
        self.assertEqual(motivo_sessao(
            "<form id='kc-form-login'><input id='username'></form>"), "login")
        self.assertEqual(motivo_sessao("<p>x</p>", "https://e/eproc/externo_controlador.php"
                                                   "?acao=principal&msg=Link%20sem%20assinatura"),
                         "sem_assinatura")
        # aviso comum do InfraPHP, área logada com o usuário no topo: nada disso é sessão
        self.assertEqual(motivo_sessao("<textarea id='txaInfraMsg'>Prazo cadastrado.</textarea>"
                                       "<span id='txtUsuario'>RS012345</span>"), "")

    def test_sigilo(self):
        self.assertTrue(indica_sigilo("Nível de sigilo: Segredo de Justiça (Nível 1)"))
        self.assertTrue(indica_sigilo("Sigilo do processo: Nível 3"))
        self.assertTrue(indica_sigilo("PROCESSO SIGILOSO"))
        self.assertFalse(indica_sigilo("Nível de sigilo: Sem Sigilo (Nível 0)"))
        self.assertFalse(indica_sigilo("Deferida a quebra de sigilo bancário"))

    def test_nao_encontrado_e_sem_acesso(self):
        self.assertTrue(diz_nao_encontrado("Processo não encontrado."))
        self.assertTrue(diz_nao_encontrado("Nenhum registro encontrado"))
        self.assertFalse(diz_nao_encontrado("Processo encontrado"))
        self.assertTrue(diz_sem_acesso("Acesso íntegra do processo"))
        self.assertTrue(diz_sem_acesso("Usuário não possui permissão"))
        self.assertFalse(diz_sem_acesso("Painel do Advogado"))


class TestConteudo(unittest.TestCase):
    def test_tipos(self):
        pdf = apoio.pdf_bytes(1)
        self.assertEqual(tipo_do_conteudo(pdf, "text/html"), "pdf")      # vale a assinatura
        self.assertEqual(tipo_do_conteudo(b"\xff\xd8\xff\xe0" + b"0" * 40), "imagem")
        self.assertEqual(tipo_do_conteudo(apoio.png_bytes()), "imagem")
        self.assertEqual(tipo_do_conteudo(b"<html><body>x</body></html>"), "html")
        self.assertEqual(tipo_do_conteudo(b"<p class='titulo'>DECIS\xc3O</p>"), "html")
        self.assertEqual(tipo_do_conteudo(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20), "midia")
        self.assertEqual(tipo_do_conteudo(b"ID3\x03" + b"\x00" * 20), "midia")
        self.assertEqual(tipo_do_conteudo(b"\x00\x01\x02", "audio/mpeg"), "midia")
        self.assertEqual(tipo_do_conteudo(b"\x00\x01\x02", "", "mp3"), "midia")
        self.assertEqual(tipo_do_conteudo(b"PK\x03\x04resto"), "zip")
        self.assertEqual(tipo_do_conteudo(b"certidao", "text/plain"), "texto")
        self.assertEqual(tipo_do_conteudo(b""), "vazio")
        self.assertEqual(tipo_do_conteudo(b"\x01\x02\x03\x04", "application/octet-stream"),
                         "desconhecido")
        self.assertEqual(eproc.extensao_da_midia(b"\x00\x00\x00\x18ftypmp42"), ".mp4")
        self.assertEqual(eproc.extensao_da_midia(b"x", "", "mp3"), ".mp3")
        self.assertEqual(eproc.extensao_da_midia(b"x", "audio/x-wav"), ".wav")

    def test_html_em_iso_8859_1(self):
        bruto = "<p>Decisão “assinada” — ação</p>".encode("cp1252")
        self.assertEqual(decodificar_html(bruto, "text/html; charset=ISO-8859-1"),
                         "<p>Decisão “assinada” — ação</p>")
        com_meta = ("<meta charset='iso-8859-1'><p>Citação</p>").encode("latin-1")
        self.assertIn("Citação", decodificar_html(com_meta, "text/html"))
        self.assertEqual(decodificar_html("<p>Já é texto</p>".encode("utf-8"), ""),
                         "<p>Já é texto</p>")
        convertido = html_em_utf8("<meta charset=iso-8859-1><p>Citação</p>")
        self.assertIn("charset=utf-8".encode(), convertido)
        self.assertNotIn(b"iso-8859-1", convertido)
        self.assertIn("Citação".encode("utf-8"), convertido)

    def test_pdfs_do_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("parte2.pdf", apoio.pdf_bytes(2, "B"))
            z.writestr("leia.txt", b"x")
            z.writestr("parte1.pdf", apoio.pdf_bytes(1, "A"))
        partes = eproc.pdfs_do_zip(buf.getvalue())
        self.assertEqual(len(partes), 2)
        self.assertTrue(all(p.startswith(b"%PDF") for p in partes))

    def test_capa(self):
        n = apoio.numero("5001234", tr="21")
        doc = Documento(4, "20/03/2024", "", "JUNTADA", "PET1", "x")
        texto = eproc.texto_capa(n, "eProc do TJRS", {"classe": "PROCEDIMENTO COMUM"},
                                 ["AUTOR: MARIA"], 7, [doc, doc], True, [doc], 1,
                                 quando=datetime(2026, 10, 3, 9, 5))
        self.assertTrue(texto.startswith(f"PROCESSO {n.formatado}\neProc do TJRS — autos "
                                         "extraídos em 03/10/2026 às 09:05"))
        self.assertIn("SEGREDO DE JUSTIÇA", texto)
        self.assertIn("Classe: PROCEDIMENTO COMUM", texto)
        self.assertIn("  AUTOR: MARIA", texto)
        self.assertIn("Documentos: 2", texto)
        self.assertIn("Documentos não incluídos (1): ev. 4 PET1", texto)
        self.assertIn("evento 1, INIC1", texto)


class TestConfiguracao(apoio.PastaTemporaria):
    def test_normalizar_base(self):
        self.assertEqual(normalizar_base("https://x.jus.br/eproc"), "https://x.jus.br/eproc/")
        self.assertEqual(normalizar_base("https://x.jus.br/eproc/index.php?a=1"),
                         "https://x.jus.br/eproc/")
        self.assertEqual(normalizar_base(" https://x.jus.br/eprocV2/ "), "https://x.jus.br/eprocV2/")
        self.assertEqual(normalizar_base(""), "")

    def test_seletores_do_usuario_vem_na_frente(self):
        arquivo = self.tmp / "seletores-eproc.json"
        arquivo.write_text(json.dumps({"pesquisa_rapida": "#campoNovo",
                                       "eventos_linha": ["tr.evento", "tr[id^='trEvento']"],
                                       "_comentario": "ignorado"}), encoding="utf-8")
        sel = eproc.carregar_seletores(arquivo)
        self.assertEqual(sel["pesquisa_rapida"][0], "#campoNovo")
        self.assertIn("#txtNumProcessoPesquisaRapida", sel["pesquisa_rapida"])
        self.assertEqual(sel["eventos_linha"], ["tr.evento", "tr[id^='trEvento']"])
        self.assertNotIn("_comentario", sel)
        arquivo.write_text(json.dumps({"eproc": {"capa_classe": ["#classe"]}}), encoding="utf-8")
        self.assertEqual(eproc.carregar_seletores(arquivo)["capa_classe"][0], "#classe")
        arquivo.write_text("{ estragado", encoding="utf-8")
        with self.assertLogs("download.eproc", "WARNING"):
            self.assertEqual(eproc.carregar_seletores(arquivo), eproc.SELETORES_PADRAO)

    def test_modo_do_pdf(self):
        self.assertEqual(eproc.resolver_modo("completo"), "completo")
        self.assertEqual(eproc.resolver_modo(" Documentos "), "documentos")
        opcoes = apoio.opcoes_de_teste(self.tmp)
        opcoes.modo_eproc = "completo"
        self.assertEqual(eproc.resolver_modo(None, opcoes), "completo")
        with self.assertLogs("download.eproc", "WARNING"):
            self.assertEqual(eproc.resolver_modo("tudo"), "documentos")


class _NavJanela:
    """Faz as vezes do Navegador para o CDP da janela."""

    def __init__(self, visivel=True, falhar=False):
        self.visivel = visivel
        self.falhar = falhar
        self.enviados = []
        self.pagina = object()
        self.contexto = self
        self.diagnosticos = []

    def new_cdp_session(self, pagina):
        if self.falhar:
            raise RuntimeError("CDP recusado")
        return self

    def send(self, metodo, params=None):
        self.enviados.append((metodo, params))
        return {"windowId": 7} if metodo == "Browser.getWindowForTarget" else {}

    def detach(self):
        pass

    def diagnosticar(self, rotulo, pagina=None):
        self.diagnosticos.append(rotulo)


class TestPortalSemNavegador(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.tribunal = replace(tribunais.por_sigla("TJRS"), urls={"1g": ["https://e/eproc/"]})

    def portal(self, nav, **mudar):
        opcoes = apoio.opcoes_de_teste(self.tmp, **mudar)
        return PortalEProc(nav, self.tribunal, opcoes, apoio.ContextoGravador(), ("u", "s"),
                           seletores=eproc.SELETORES_PADRAO)

    def test_minimiza_e_restaura_pelo_cdp(self):
        nav = _NavJanela()
        portal = self.portal(nav, mostrar_navegador=False)
        portal._minimizar()
        self.assertTrue(portal._minimizada)
        self.assertEqual(nav.enviados[-1], ("Browser.setWindowBounds",
                                            {"windowId": 7, "bounds": {"windowState": "minimized"}}))
        portal._restaurar_janela()
        self.assertFalse(portal._minimizada)
        self.assertEqual(nav.enviados[-1][1]["bounds"], {"windowState": "normal"})

    def test_cdp_recusado_ou_janela_oculta_nao_e_erro(self):
        nav = _NavJanela(falhar=True)
        portal = self.portal(nav, mostrar_navegador=False)
        portal._minimizar()
        self.assertFalse(portal._minimizada)
        oculta = _NavJanela(visivel=False)
        self.portal(oculta)._minimizar()
        self.assertEqual(oculta.enviados, [])
        # quem pediu para ver o navegador não tem a janela minimizada
        visivel = _NavJanela()
        self.portal(visivel, mostrar_navegador=True)._minimizar()
        self.assertEqual(visivel.enviados, [])

    def test_incidente_com_barra_nao_existe_no_eproc(self):
        portal = self.portal(_NavJanela())
        r = portal.baixar(apoio.numero("5001234", tr="21", dependente="01"), self.tmp / "x.pdf")
        self.assertEqual(r.situacao, modelos.NAO_ENCONTRADO)
        self.assertIn("número próprio", r.detalhe)

    def test_sem_endereco_no_catalogo(self):
        sem = replace(self.tribunal, urls={})
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            PortalEProc(_NavJanela(), sem, apoio.opcoes_de_teste(self.tmp), None, None)
        self.assertIn("Configurações > Acessos", str(caso.exception))

    def test_tribunal_com_endereco_por_secao_espera_o_primeiro_processo(self):
        trf4 = tribunais.por_sigla("TRF4")
        portal = PortalEProc(object(), trf4, apoio.opcoes_de_teste(self.tmp), None, None)
        with self.assertLogs("download.eproc", "INFO") as logs:
            portal.entrar()          # não toca no navegador (object() nem tem página)
        self.assertIn("seção judiciária", "\n".join(logs.output))
        self.assertEqual(trf4.urls_para(apoio.numero("5001234", j="4", tr="04", origem="7100")),
                         ["https://eproc.jfrs.jus.br/eprocV2/"])


if __name__ == "__main__":
    unittest.main()
