"""Ponta a ponta: Chromium de verdade contra um e-SAJ de mentira, sem rede.

O servidor local (testes/apoio_esaj2g.py) imita o fluxo do e-SAJ - CAS com
código por e-mail, cpopg (open.do, search.do, show.do), segredo de justiça
com senha, incidente, Pasta Digital (requestScope), salvarDocumentoPreparado
/ buscarDocumentoFinalizado e getPDF.do - com as armadilhas que a base
conheceu: o botão Entrar que nasce desabilitado, o modal de senha que existe
escondido em toda página, o "Não existem informações disponíveis", a busca
que devolve LISTA, o foro que tem de vir do número (o servidor recusa
processo.foro errado, como o 56 fixo da base) e o servidor que não monta o
PDF único. Estes são o teste de regressão do 1º grau (cpopg).

O mesmo servidor tem a consulta de 2º grau (cposg5): a porta de entrada que
faz a consulta reconhecer o login ("SSO por webapp"), a busca que só aceita
os parâmetros do CPOSG, as três respostas (a página do processo, o modal
"Selecione o processo" com o recurso interno /50000, a lista), o show.do só
com o código, o segredo de justiça do 2º grau e a Pasta Digital aberta por
verificarAcessoPastaDigital.do, em /pastadigital/sg.

Pula sozinho se não houver Chromium que abra (o CI do Windows usa o Chrome
ou o Edge instalados; aqui, o Chromium de /opt/pw-browsers). Os testes do
próprio servidor falso (TestServidorFalso) não precisam de navegador.
"""

from __future__ import annotations

import glob
import json
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from helestron.download import esaj, modelos, motor
from helestron.download.esaj import PortalESAJ
from helestron.download.navegador import Navegador
from helestron.nucleo import cnj, paginacao

from testes import apoio_download as apoio
from testes import apoio_esaj2g as falso
from testes.apoio_esaj2g import (CODIGO, NUMEROS, P1, P1_INC, P2, P3, P5, P6, SENHA,
                                 SENHA_S_2G, USUARIO)

A, H, E, P, PL, S = (NUMEROS[k] for k in ("A", "H", "E", "P", "PL", "S"))


def _procurar_navegador() -> tuple[str, str | None] | None:
    """(canal, executável) de um navegador que o Playwright consiga abrir.

    No Windows (CI), o Chrome ou o Edge instalados; no Linux, o Chromium do
    Playwright - ou, se a versão dele não bater com a do pacote, um dos que
    estiverem em PLAYWRIGHT_BROWSERS_PATH.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import tempfile
    raiz = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "/opt/pw-browsers"
    candidatos: list[tuple[str, str | None]] = [("chromium", None), ("chrome", None),
                                                 ("msedge", None)]
    for padrao in ("chromium_headless_shell-*/chrome-*/headless_shell*",
                   "chromium-*/chrome-*/chrome", "chromium-*/chrome-*/chrome.exe"):
        candidatos += [("chromium", exe) for exe in sorted(glob.glob(f"{raiz}/{padrao}"),
                                                            reverse=True)]
    with sync_playwright() as pw:
        for canal, exe in candidatos:
            extra = {"executable_path": exe} if exe else {}
            if canal != "chromium":
                extra["channel"] = canal
            try:
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                    ctx = pw.chromium.launch_persistent_context(d, headless=True, **extra)
                    ctx.close()
                return canal, exe
            except Exception:
                continue
    return None


_NAVEGADOR: tuple[str, str | None] | None = None
_PROCURADO = False


def navegador_de_teste():
    global _NAVEGADOR, _PROCURADO
    if not _PROCURADO:
        _PROCURADO = True
        try:
            _NAVEGADOR = _procurar_navegador()
        except Exception:
            _NAVEGADOR = None
    return _NAVEGADOR


class _ComServidor(apoio.PastaTemporaria):
    """Base: o e-SAJ falso no ar (um por classe) e o navegador de verdade."""

    @classmethod
    def setUpClass(cls):
        if navegador_de_teste() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")
        cls.servidor = falso.servidor_esaj()
        cls.base = cls.servidor.base

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()

    def setUp(self):
        super().setUp()
        patches = [mock.patch.object(esaj, "INTERVALO_POLL_S", 0.2),
                   mock.patch.object(esaj, "ESPERA_CONFIRMA_CODIGO_S", 2),
                   mock.patch.object(motor, "ESPERA_ENTRE_TENTATIVAS_S", 0.0)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.tribunal = self.servidor.tribunal()

    def navegador(self, nome="esaj-TJAL"):
        canal, exe = navegador_de_teste()
        return Navegador(self.tmp / "perfis" / nome, visivel=False, canal=canal,
                         executavel=exe, espera_s=20,
                         dominios=motor.hosts_do_tribunal(self.tribunal),
                         pasta_downloads=self.tmp / "downloads",
                         pasta_diagnostico=self.tmp / "diagnostico")


class TestPortaADentro(_ComServidor):
    """O e-SAJ inteiro, do login ao PDF, num navegador de verdade (1º grau)."""

    def fabricas(self, nome="esaj-TJAL"):
        def fabrica_navegador(tribunal, opcoes):
            return self.navegador(nome)

        def fabrica_portal(nav, tribunal, opcoes, ctx, credenciais):
            return PortalESAJ(nav, self.tribunal, opcoes, ctx, credenciais)
        return fabrica_portal, fabrica_navegador

    def test_lote_completo_e_segunda_rodada(self):
        destino = self.tmp / "Acervo" / "Processos" / "Pauta"
        opcoes = apoio.opcoes_de_teste(self.tmp, tentativas=1, baixar_midias=True, espera_s=20,
                                       espera_tela_codigo_s=15)
        ctx = apoio.ContextoGravador(codigos=["000000", CODIGO])
        cofre = apoio.CofreFalso({"esaj:TJAL": (USUARIO, SENHA)})
        fp, fn = self.fabricas()
        lista = [P1, P2, P3, P1_INC, P5, P6]
        resumo = motor.executar(lista, destino, opcoes, ctx, senhas={P2.formatado: "abc123"},
                                cofre=cofre, fabrica_portal=fp, fabrica_navegador=fn)
        r = {x.numero: x for x in resumo.itens}

        # login: o primeiro código foi recusado, o segundo aceito
        self.assertEqual(self.servidor.codigos_enviados[:2], ["000000", CODIGO])
        self.assertEqual(len(ctx.pedidos_codigo), 2)
        self.assertIn("não aceitou", ctx.pedidos_codigo[1][1])

        # P1: PDF do servidor, com marcadores, capa e gravação; não é sigiloso
        r1 = r[P1.formatado]
        self.assertEqual(r1.situacao, modelos.OK, r1.detalhe)
        self.assertEqual(r1.paginas, 6)
        self.assertEqual(r1.documentos, 3)
        self.assertFalse(r1.sigiloso, "'retirado o segredo' nas movimentações não é sigilo")
        import pymupdf
        from helestron.nucleo import paginacao
        with pymupdf.open(destino / f"{P1.nome_arquivo}.pdf") as doc:
            self.assertEqual(len(doc), 6)
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 3, 6])
            m1 = paginacao.ler_do_doc(doc)
        self.assertEqual((m1["ultima"], m1["ausentes"], m1["origem"]), (6, {}, "servidor"))
        capa = (destino / "_controle" / f"{P1.nome_arquivo}_capa.txt").read_text(encoding="utf-8")
        self.assertIn("Classe: Procedimento Comum Cível", capa)
        self.assertIn("Maria da Silva", capa)
        self.assertIn("Distribuído por sorteio", capa)
        # capa v2: só a tabela de movimentações (as duas iguais do mesmo dia
        # ficam), as partes de uma tabela só, as seções pelo título, marcas e
        # a paginação do PDF
        movs = capa[capa.index("== Movimentações"):].split("\n\n")[0]
        self.assertIn("== Movimentações (3) ==", movs)
        self.assertEqual(movs.count("01/02/2024  Distribuído por sorteio"), 2)
        for intrusa in ("Conciliação", "Pedido de vista", "Evolução de classe", "Cumprimento"):
            self.assertNotIn(intrusa, movs)
        self.assertEqual(capa.count("Réu: Banco Exemplo S.A."), 1)
        self.assertIn("Terceiro: João Terceiro", capa)
        self.assertIn("== Marcas ==\nTramitação prioritária\n\n", capa,
                      "o assunto 'Estatuto do Idoso' não é marca de idoso")
        self.assertIn("Outros números: 0001234-56.2023.8.02.0001", capa)
        self.assertIn("== Audiências (1) ==\n19/04/2024  Conciliação - Realizada - 2", capa)
        self.assertIn("== Petições diversas (1) ==\n05/03/2024  Pedido de vista dos autos", capa)
        self.assertIn("== Histórico de classes (1) ==", capa)
        self.assertIn("== Incidentes, ações incidentais, recursos e execuções de sentenças (1) ==",
                      capa)
        self.assertIn("Folhas 1 a 6 (última oferecida pela Pasta Digital)", capa)
        self.assertIn("Paginação: página N = folha N (fls. 1 a 6)", capa)
        capa_json = json.loads((destino / "_controle" / f"{P1.nome_arquivo}_capa.json")
                               .read_text(encoding="utf-8"))
        self.assertEqual(capa_json["formato"], "helestron.capa/2")
        self.assertEqual((capa_json["prioridade"], capa_json["idoso"], capa_json["segredo"]),
                         (True, False, False))
        self.assertEqual(capa_json["codigo_processo"], "1K0001AAA0000")
        self.assertNotIn("senha", capa_json["url"])
        self.assertEqual(capa_json["incidentes"][0]["codigo"], "1K0001AAA0001")
        self.assertEqual(capa_json["incidentes"][0]["recebido_em"], "15/05/2024")
        self.assertEqual(capa_json["paginacao"]["ultima"], 6)
        self.assertEqual(len(capa_json["movimentacoes"]), 3)
        self.assertTrue((destino / "_controle" / "midias" / P1.nome_arquivo /
                         "audiencia1.mp3").exists())
        loc = next(l for l in self.servidor.localizadores.values() if l["cd"] == "1K0001AAA0000")
        self.assertTrue(loc["corpo"].startswith("itensPdfSelecionados=nuSeqRecurso%3D00000"))
        self.assertIn("&cdProcesso=1K0001AAA0000&cdDocumento=103&separarDocumentos=false",
                      loc["corpo"])

        # P2: sigiloso liberado pela senha; servidor falhou -> peça a peça; fora do acervo
        r2 = r[P2.formatado]
        self.assertEqual(r2.situacao, modelos.OK, r2.detalhe)
        self.assertTrue(r2.sigiloso)
        self.assertIn("peça a peça", r2.detalhe)
        self.assertEqual(r2.incompleto, "3")
        sig = self.tmp / "Sigilosos" / "Pauta"
        self.assertFalse((destino / f"{P2.nome_arquivo}.pdf").exists())
        with pymupdf.open(sig / f"{P2.nome_arquivo}.pdf") as doc:
            self.assertEqual(len(doc), 3)
            self.assertTrue(doc[2].get_text().startswith(
                "Folha 3 — não disponibilizada pelo e-SAJ"))
            self.assertIn("não pôde ser baixada", doc[2].get_text())
            self.assertEqual(paginacao.ausentes(paginacao.ler_do_doc(doc)), {3: "B"},
                             "o manifesto vai com o PDF para a pasta de sigilosos")
        self.assertTrue((sig / "_controle" / "midias" / P2.nome_arquivo / "audiencia1.mp3").exists())
        self.assertFalse((destino / "_controle" / f"{P2.nome_arquivo}_capa.txt").exists())
        self.assertFalse((destino / "_controle" / f"{P2.nome_arquivo}_capa.json").exists())
        capa2 = json.loads((sig / "_controle" / f"{P2.nome_arquivo}_capa.json")
                           .read_text(encoding="utf-8"))
        self.assertTrue(capa2["sigiloso"] and capa2["segredo"])
        self.assertEqual(capa2["paginacao"]["folhas_ausentes"], "3")

        # P3: inexistente; incidente; busca que devolve lista
        self.assertEqual(r[P3.formatado].situacao, modelos.NAO_ENCONTRADO)
        r_inc = r[P1_INC.formatado]
        self.assertEqual(r_inc.situacao, modelos.OK, r_inc.detalhe)
        self.assertEqual(r_inc.paginas, 2)
        self.assertTrue((destino / f"{P1.principal}-01.pdf").exists())
        r5 = r[P5.formatado]
        self.assertEqual(r5.situacao, modelos.OK, r5.detalhe)
        self.assertTrue(any("1K0005EEE0000" in c for _, c in self.servidor.pedidos
                            if "show.do" in c))
        self.assertFalse(any("processo.foro=56" in c for _, c in self.servidor.pedidos))

        # P6: a Pasta Digital oculta as fls. 3-4 - a página 5 continua a fl. 5
        r6 = r[P6.formatado]
        self.assertEqual(r6.situacao, modelos.OK, r6.detalhe)
        self.assertEqual((r6.paginas, r6.incompleto), (5, "3-4"))
        self.assertNotIn("peça a peça", r6.detalhe)
        with pymupdf.open(destino / f"{P6.nome_arquivo}.pdf") as doc:
            self.assertEqual(len(doc), 5)
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 3, 5])
            self.assertTrue(doc[2].get_text().startswith("Folha 3 — não disponibilizada pelo e-SAJ"))
            self.assertIn("servidor 3", doc[4].get_text(), "a sentença (fl. 5) na página 5")
            self.assertEqual(paginacao.ausentes(paginacao.ler_do_doc(doc)), {3: "N", 4: "N"})

        # sessão guardada para a próxima vez (fora do acervo)
        self.assertTrue((self.tmp / "perfis" / "esaj-TJAL" / "sessao.json").exists())
        self.assertEqual(sorted(p.name for p in destino.iterdir() if p.is_file()),
                         sorted([f"{P1.nome_arquivo}.pdf", f"{P1.principal}-01.pdf",
                                 f"{P5.nome_arquivo}.pdf", f"{P6.nome_arquivo}.pdf"]))

        # segunda rodada: pula o que já tem e NÃO pede código de novo
        ctx2 = apoio.ContextoGravador(codigos=[])
        fp, fn = self.fabricas()
        resumo2 = motor.executar(lista, destino, opcoes, ctx2, senhas={P2.formatado: "abc123"},
                                 cofre=cofre, fabrica_portal=fp, fabrica_navegador=fn)
        self.assertEqual(ctx2.pedidos_codigo, [], "a sessão guardada dispensa o login")
        sit = {x.numero: x.situacao for x in resumo2.itens}
        self.assertEqual(sit[P1.formatado], modelos.JA_BAIXADO)
        self.assertEqual(sit[P2.formatado], modelos.JA_BAIXADO)
        self.assertEqual(sit[P3.formatado], modelos.NAO_ENCONTRADO)
        self.assertEqual(sit[P6.formatado], modelos.JA_BAIXADO)

    def test_senha_errada_e_avisada_sem_esperar(self):
        import time
        opcoes = apoio.opcoes_de_teste(self.tmp, espera_s=20, espera_tela_codigo_s=45)
        ctx = apoio.ContextoGravador()
        with self.navegador("esaj-senha-errada") as nav:
            portal = PortalESAJ(nav, self.tribunal, opcoes, ctx, (USUARIO, "errada"))
            inicio = time.monotonic()
            with self.assertRaises(modelos.LoginFalhou) as caso:
                portal.entrar()
            demora = time.monotonic() - inicio
        self.assertIn("recusou o usuário ou a senha", str(caso.exception))
        self.assertLess(demora, 30, "não pode esperar os 45 s da tela do código")
        self.assertEqual(ctx.pedidos_codigo, [])
        self.assertTrue(list((self.tmp / "diagnostico").glob("*esaj-login-recusado*.html")))

    def test_capa_v2_em_layouts_diferentes(self):
        """A leitura da página do processo (capa v2) no navegador de verdade, em
        layouts que o portal falso do lote não tem."""
        with self.navegador("esaj-capa") as nav:
            # layout sem as tabelas de movimentações conhecidas: vale a regra
            # antiga (linha que começa por data, sem repetir), mas fora das seções
            nav.pagina.set_content(
                "<table id='outra'><tr><td>02/02/2024</td><td>Conclusos</td></tr>"
                "<tr><td>02/02/2024</td><td>Conclusos</td></tr>"
                "<tr><td>01/02/2024</td><td>Distribuído</td></tr></table>"
                "<div><h2 class='subtitle'>Incidentes, ações incidentais, recursos e execuções "
                "de sentenças</h2></div><p>Não há incidentes vinculados a este processo.</p>"
                "<div><h2 class='subtitle'>Audiências</h2></div>"
                "<div class='x'><table><tr><th>Data</th><th>Audiência</th></tr>"
                "<tr><td>03/03/2024</td><td>Instrução</td></tr></table></div>"
                "<div><span class='unj-label'>Processo principal</span><div><a href="
                "'/cpopg/show.do?processo.codigo=1K0001AAA0000'>0700001-11.2024.8.02.0001</a>"
                "</div></div>"
                "<span class='unj-label'>Local físico</span><div>Cartório</div>"
                "<p>Segredo de justiça</p>")
            info = nav.pagina.evaluate(esaj._JS_PAGINA_PROCESSO)
        self.assertEqual(info["movs"], [{"data": "02/02/2024", "texto": "Conclusos"},
                                        {"data": "01/02/2024", "texto": "Distribuído"}])
        self.assertEqual(info["secoes"]["incidentes"], [],
                         "título sem tabela: não pega a tabela da seção seguinte")
        self.assertEqual(info["secoes"]["audiencias"],
                         [{"celulas": ["03/03/2024", "Instrução"], "codigo": ""}])
        self.assertEqual(info["extras"], {"processo_principal": "0700001-11.2024.8.02.0001",
                                          "local_fisico": "Cartório"})
        self.assertIn("Segredo de justiça", info["texto"], "o texto do segredo continua lido")
        self.assertEqual((info["url"], info["codigo"]), ("", ""), "página fora do portal")

    def test_primeiro_visivel_no_navegador_de_verdade(self):
        from helestron.download.navegador import primeiro_visivel
        with self.navegador("esaj-seletores") as nav:
            nav.pagina.set_content(
                "<div id='a' style='display:none'><input id='x'></div>"
                "<input id='b'><button id='c'>Entrar</button>")
            achado = primeiro_visivel(nav.pagina, ["#a input", "#b", "button:has-text('Entrar')"], 2000)
            self.assertEqual(achado.get_attribute("id"), "b")
            self.assertIsNone(primeiro_visivel(nav.pagina, ["#a", "#x"], 300))
            botao = primeiro_visivel(nav.pagina, ["#nada", "button:has-text('Entrar')"], 1000)
            self.assertEqual(botao.get_attribute("id"), "c")


# ======================================================== o servidor falso
def _pedir(url, cookies="", metodo="GET", corpo=None):
    """(status, texto, cabeçalhos) de um pedido ao servidor falso, sem seguir
    redirecionamento."""
    class SemSeguir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    abridor = urllib.request.build_opener(SemSeguir)
    pedido = urllib.request.Request(url, data=corpo, method=metodo,
                                    headers={"Cookie": cookies} if cookies else {})
    try:
        with abridor.open(pedido, timeout=10) as r:
            return r.status, r.read().decode("utf-8"), dict(r.headers)
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read().decode("utf-8"), dict(erro.headers)


class TestServidorFalso(unittest.TestCase):
    """As rotas do cposg5 falso se comportam como as do portal (sem navegador):
    se o servidor aceitasse o que o portal recusa, os testes do 2º grau
    passariam com um programa errado."""

    @classmethod
    def setUpClass(cls):
        cls.s = falso.servidor_esaj()

    @classmethod
    def tearDownClass(cls):
        cls.s.parar()

    def logado_2g(self):
        status, _, cab = _pedir(f"{self.s.app_2g}/open.do?gateway=true", "SESSAO=ok")
        self.assertEqual(status, 200)
        return "SESSAO=ok; " + cab["Set-Cookie"].split(";")[0]

    def test_porta_de_entrada_do_2o_grau(self):
        status, _, cab = _pedir(f"{self.s.app_2g}/open.do?gateway=true")
        self.assertEqual((status, cab.get("Location")), (302, "/sajcas/login?service=cposg5"))
        self.assertTrue(self.logado_2g().startswith("SESSAO=ok; SG5="))

    def test_busca_so_com_os_parametros_do_cposg(self):
        status, texto, _ = _pedir(esaj.url_busca_2g(self.s.app_2g, H))
        self.assertEqual(status, 200)
        self.assertIn("name='cdProcesso' value='P0000HHHH0000'", texto)
        # os parâmetros do cpopg no cposg5: nada
        cpopg = esaj.url_busca(self.s.base, H).replace("/cpopg/", "/cposg5/")
        self.assertIn("Não existem informações disponíveis", _pedir(cpopg)[1])
        # o foro tem de ser o do próprio número
        errado = esaj.url_busca_2g(self.s.app_2g, H).replace("foroNumeroUnificado=0000",
                                                              "foroNumeroUnificado=0001")
        self.assertIn("Não existem informações disponíveis", _pedir(errado)[1])

    def test_as_tres_respostas(self):
        modal = _pedir(esaj.url_busca_2g(self.s.app_2g, E))[1]
        self.assertIn("id='modalIncidentes'", modal)
        self.assertIn("value='P00006BXP12KW'", modal)
        self.assertIn("50000 - Embargos de Declaração Cível", modal)
        lista = _pedir(esaj.url_busca_2g(self.s.app_2g, PL))[1]
        self.assertIn("id='listagemDeProcessos'", lista)
        self.assertIn("class='linkProcesso'", lista)

    def test_show_do_so_com_o_codigo(self):
        ok = _pedir(esaj.url_processo_2g(self.s.app_2g, falso.COD_A_2G))[1]
        self.assertIn(f"id='numeroProcesso'>{A.formatado}<", ok)
        com_foro = _pedir(f"{self.s.app_2g}/show.do?processo.codigo={falso.COD_A_2G}"
                          "&processo.foro=58")[1]
        self.assertNotIn("numeroProcesso", com_foro, "o foro da origem não abre o processo")
        dependente = _pedir(esaj.url_processo_2g(self.s.app_2g, falso.COD_E_2G))[1]
        self.assertIn(f">{E.formatado}<", dependente)

    def test_pasta_do_2o_grau(self):
        url = (f"{self.s.app_2g}/verificarAcessoPastaDigital.do?cdProcesso={falso.COD_H_2G}"
               "&_=1")
        self.assertEqual(_pedir(url)[0], 401, "sem login")
        self.assertEqual(_pedir(url, "SESSAO=ok")[0], 401,
                         "com o login do portal, mas sem a porta de entrada do 2º grau")
        status, texto, _ = _pedir(url, self.logado_2g())
        self.assertEqual(status, 200)
        self.assertTrue(texto.startswith(f"{self.s.base}/pastadigital/sg/"), texto)
        # a Pasta Digital do 2º grau não responde no caminho do 1º grau
        corpo = urllib.parse.urlencode({"cdProcesso": falso.COD_H_2G,
                                        "itensPdfSelecionados": "numInicial=1&numFinal=1"})
        self.assertEqual(_pedir(f"{self.s.base}/pastadigital/salvarDocumentoPreparado.do",
                                "SESSAO=ok", "POST", corpo.encode())[0], 404)
        self.assertEqual(_pedir(f"{self.s.base}/pastadigital/sg/salvarDocumentoPreparado.do",
                                "SESSAO=ok", "POST", corpo.encode())[0], 200)

    def test_pasta_com_senha(self):
        url = (f"{self.s.app_2g}/verificarAcessoPastaDigital.do?cdProcesso={falso.COD_S_2G}"
               "&_=1")
        cookies = self.logado_2g()
        status, texto, _ = _pedir(url, cookies)
        self.assertEqual(status, 403)
        self.assertIn("popupSenhaProcesso", texto)
        corpo = urllib.parse.urlencode({"cdProcesso": falso.COD_S_2G,
                                        "senhaDoProcessoDigitada": "errada"}).encode()
        self.assertEqual(_pedir(f"{self.s.app_2g}/validarSenhaAcessoProcesso.do", "", "POST",
                                corpo)[0], 400)
        corpo = urllib.parse.urlencode({"cdProcesso": falso.COD_S_2G,
                                        "senhaDoProcessoDigitada": SENHA_S_2G}).encode()
        status, _, cab = _pedir(f"{self.s.app_2g}/validarSenhaAcessoProcesso.do", "", "POST",
                                corpo)
        self.assertEqual(status, 200)
        liberado = cookies + "; " + cab["Set-Cookie"].split(";")[0]
        self.assertEqual(_pedir(url, liberado)[0], 200)

    def test_tribunal_e_enderecos(self):
        t = self.s.tribunal()
        self.assertEqual((t.sigla, t.grau, t.alternativo), ("TJAL", "1g", None))
        self.assertEqual(t.no_grau("2g").urls_para(), [self.s.app_2g])
        self.assertEqual(self.s.enderecos_locais(),
                         {"esaj:TJAL": {"base": self.s.base, "2g": self.s.app_2g}})


# =========================================================== o 2º grau
class TestSegundoGrau(_ComServidor):
    """O e-SAJ do 2º grau (cposg5), do login ao PDF, num navegador de verdade.
    O motor do 2º grau é de outra frente: aqui, o portal direto."""

    def opcoes(self, **k):
        return apoio.opcoes_de_teste(self.tmp, espera_s=20, espera_tela_codigo_s=15, **k)

    def portais(self, nav, ctx, servidor=None):
        t = (servidor or self.servidor).tribunal()
        return (PortalESAJ(nav, t, self.opcoes(), ctx, (USUARIO, SENHA)),
                PortalESAJ(nav, t.no_grau("2g"), self.opcoes(), ctx, (USUARIO, SENHA)))

    def capa_json(self, pasta, nome):
        return json.loads((pasta / "_controle" / f"{nome}_capa.json").read_text(encoding="utf-8"))

    def test_o_mesmo_numero_nos_dois_graus(self):
        """A apelação tem o mesmo número nos dois graus: cada grau grava os
        seus autos, com a sua árvore, e nada colide."""
        import pymupdf
        s = self.servidor
        pasta = self.tmp / "Lote"
        ctx = apoio.ContextoGravador(codigos=[CODIGO])
        antes = len(s.pedidos)
        with self.navegador() as nav:
            p1, p2 = self.portais(nav, ctx)
            p2.entrar()
            # o login do portal, e depois a porta de entrada da consulta de 2º grau
            novos = [c for _, c in s.pedidos[antes:]]
            self.assertIn("/cposg5/open.do?gateway=true", novos)
            self.assertLess(max(i for i, c in enumerate(novos) if c.startswith("/sajcas/")),
                            novos.index("/cposg5/open.do?gateway=true"))
            p1.entrar()
            self.assertEqual(len(ctx.pedidos_codigo), 1, "um login só para os dois graus")
            r1 = p1.baixar(A, pasta / f"{A.nome_arquivo}.pdf")
            autos_2g = cnj.nome_dos_autos(A, "2g")
            r2 = p2.baixar(A, pasta / f"{autos_2g}.pdf")
        self.assertEqual(r1.situacao, modelos.OK, r1.detalhe)
        self.assertEqual(r2.situacao, modelos.OK, r2.detalhe)
        self.assertEqual((r1.paginas, r2.paginas), (4, 8), "cada grau com a sua árvore")
        self.assertEqual((r1.grau, r2.grau), ("1g", "2g"))
        with pymupdf.open(pasta / f"{A.nome_arquivo}.pdf") as doc:
            self.assertIn("servidor 1", doc[0].get_text())
            m1 = paginacao.ler_do_doc(doc)
        with pymupdf.open(pasta / f"{autos_2g}.pdf") as doc:
            self.assertIn("servidor 2g 1", doc[0].get_text())
            m2 = paginacao.ler_do_doc(doc)
            self.assertIn(";grau=2g", doc.metadata.get("keywords") or "")
        self.assertNotIn("grau", m1, "o manifesto do 1º grau é o de sempre")
        self.assertEqual((m2["grau"], m2["ultima"], paginacao.grau(m2)), ("2g", 8, "2g"))
        # capas separadas, pelo nome dos autos
        c1 = self.capa_json(pasta, A.nome_arquivo)
        c2 = self.capa_json(pasta, autos_2g)
        self.assertNotIn("grau", c1)
        self.assertEqual(c2["grau"], "2g")
        self.assertEqual({k: c2["capa"][k] for k in ("classe", "secao", "orgao_julgador",
                                                      "relator", "origem")},
                         {"classe": "Apelação Criminal", "secao": "Tribunal de Justiça",
                          "orgao_julgador": "Câmara Criminal", "relator": "DES. JOÃO EXEMPLO",
                          "origem": "Comarca de Arapiraca / Foro de Arapiraca / 1ª Vara "
                                    "Criminal de Arapiraca"})
        self.assertEqual(c2["numeros_1a_instancia"], [{
            "numero": A.formatado, "foro": "Foro de Arapiraca",
            "vara": "1ª Vara Criminal de Arapiraca", "juiz": "Juiz Fulano de Tal", "obs": "",
            "principal": True}])
        self.assertNotIn("numeros_1a_instancia", c2["capa"], "a lista fica num lugar só")
        self.assertEqual([x["papel"] for x in c2["composicao"]],
                         ["Relator", "Revisor", "3º Julgador"])
        self.assertEqual(c2["julgamentos"], [{"data": "09/10/2024", "situacao": "Julgado",
                                              "decisao": "à unanimidade, negou provimento ao "
                                                         "recurso"}])
        self.assertEqual([x.get("codigo") for x in c2["subprocessos"]], [falso.COD_A_2G_50000])
        self.assertEqual(c2["codigo_processo"], falso.COD_A_2G)
        self.assertEqual(len(c2["movimentacoes"]), 2)
        self.assertEqual(c2["partes"], ["Apelante: João da Silva", "Apelado: Ministério Público"])
        self.assertFalse(c2["segredo"], "o popup de senha escondido não é segredo")
        texto = (pasta / "_controle" / f"{autos_2g}_capa.txt").read_text(encoding="utf-8")
        self.assertTrue(texto.startswith(f"Processo {A.formatado} - TJAL (e-SAJ, 2º grau)\n"))
        self.assertIn("folha N da Pasta Digital do 2º grau", texto)
        self.assertIn("== Números de 1ª Instância (1) ==", texto)
        # as rotas do 2º grau: só os parâmetros do CPOSG, show.do só com o
        # código, a Pasta Digital por verificarAcessoPastaDigital.do em /pastadigital/sg
        meus = [c for _, c in s.pedidos[antes:]]

        def de(rota):
            return [c for c in meus if urllib.parse.urlsplit(c).path == rota]
        buscas = de("/cposg5/search.do")
        self.assertEqual(len(buscas), 1)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(buscas[0]).query, keep_blank_values=True)
        self.assertEqual(q["dePesquisaNuUnificado"], [A.principal])
        self.assertEqual(q["foroNumeroUnificado"], ["0058"])
        self.assertFalse([k for k in q if k.startswith("dadosConsulta")])
        self.assertEqual(de("/cposg5/show.do"),
                         [f"/cposg5/show.do?processo.codigo={falso.COD_A_2G}"])
        self.assertEqual(len(de("/cposg5/verificarAcessoPastaDigital.do")), 1)
        self.assertTrue(de("/pastadigital/sg/abrirPastaProcessoDigital.do"))
        self.assertTrue(de("/pastadigital/sg/salvarDocumentoPreparado.do"))
        loc = next(l for l in s.localizadores.values() if l["cd"] == falso.COD_A_2G)
        self.assertEqual(loc["grau"], "2g", "o PDF do 2º grau pedido em /pastadigital/sg")
        self.assertFalse([c for c in de("/cpopg/show.do") if falso.COD_A_2G in c])

    def test_tres_respostas_e_o_numero_exato(self):
        s = self.servidor
        pasta = self.tmp / "Lote"
        ctx = apoio.ContextoGravador(codigos=[CODIGO])
        with self.navegador() as nav:
            _, p2 = self.portais(nav, ctx)
            p2.entrar()
            r = {nome: p2.baixar(n, pasta / f"{cnj.nome_dos_autos(n, '2g')}.pdf")
                 for nome, n in (("E", E), ("P", P), ("H", H), ("PL", PL))}
            i = cnj.ler(A.principal + "/01")
            e2 = cnj.ler(P.principal + "/50001")
            x = cnj.ler(falso.P3.formatado)
            fora = {nome: p2.baixar(n, pasta / f"{cnj.nome_dos_autos(n, '2g')}.pdf")
                    for nome, n in (("I", i), ("E2", e2), ("X", x))}
        for nome, res in r.items():
            self.assertEqual(res.situacao, modelos.OK, f"{nome}: {res.detalhe}")
        # E pelo modal: os embargos (3 folhas), nunca a apelação (6)
        self.assertEqual((r["E"].paginas, r["P"].paginas, r["H"].paginas, r["PL"].paginas),
                         (3, 6, 5, 2))
        pedidos_pdf = {l["cd"] for l in s.localizadores.values() if l["grau"] == "2g"}
        self.assertTrue({falso.COD_E_2G, falso.COD_P_2G, falso.COD_H_2G,
                         falso.COD_PL_2G} <= pedidos_pdf)
        self.assertNotIn(falso.COD_OUTRO_PL, pedidos_pdf, "da lista, só o do número exato")
        self.assertTrue((pasta / "0706265-50.2017.8.02.0001-50000 (2G).pdf").exists())
        ce = self.capa_json(pasta, "0706265-50.2017.8.02.0001-50000 (2G)")
        self.assertEqual((ce["processo"], ce["codigo_processo"]), (E.formatado, falso.COD_E_2G))
        ch = self.capa_json(pasta, f"{H.nome_arquivo} (2G)")
        self.assertEqual([x["numero"] for x in ch["numeros_1a_instancia"]], [A.formatado],
                         "o HC diz a ação de origem (o motor herda o sigilo dela)")
        # não encontrados, com a dica do grau
        for nome, n in (("I", i), ("E2", e2), ("X", x)):
            self.assertEqual(fora[nome].situacao, modelos.NAO_ENCONTRADO, fora[nome].detalhe)
            self.assertTrue(fora[nome].detalhe.startswith(
                "não encontrado no e-SAJ do TJAL (2º grau). Confira o número; "))
            self.assertIn(modelos.dica_de_grau(n, "2g"), fora[nome].detalhe)
        self.assertIn("os autos estão no 1º grau", fora["I"].detalhe)
        self.assertIn("(/50001) só existe no 2º grau", fora["E2"].detalhe)

    def test_sigiloso_so_no_2o_grau(self):
        """S é público no 1º grau e sigiloso no 2º: a página do 2º grau vem sem
        os dados, com o pedido de senha (#popupSenhaProcesso)."""
        pasta = self.tmp / "Lote"
        ctx = apoio.ContextoGravador(codigos=[CODIGO])
        autos = f"{S.nome_arquivo} (2G)"
        with self.navegador() as nav:
            p1, p2 = self.portais(nav, ctx)
            p2.entrar()
            sem = p2.baixar(S, pasta / f"{autos}.pdf")
            com = p2.baixar(S, pasta / f"{autos}.pdf", senha=SENHA_S_2G)
            publico = p1.baixar(S, pasta / f"{S.nome_arquivo}.pdf")
        self.assertEqual(sem.situacao, modelos.SIGILOSO_SEM_SENHA)
        self.assertTrue(sem.sigiloso)
        self.assertEqual(com.situacao, modelos.OK, com.detalhe)
        self.assertTrue(com.sigiloso)
        self.assertEqual(com.paginas, 3)
        self.assertIn(S.nome_arquivo, p2.sigilosos_apurados, "pela chave do processo")
        capa = (pasta / "_controle" / f"{autos}_capa.txt").read_text(encoding="utf-8")
        self.assertIn("SEGREDO DE JUSTIÇA", capa[:2000])
        self.assertTrue(self.capa_json(pasta, autos)["segredo"])
        # no 1º grau o mesmo número é público (o portal do 1º grau não sabe do 2º)
        self.assertEqual(publico.situacao, modelos.OK, publico.detalhe)
        self.assertFalse(publico.sigiloso)

    def test_sso_por_webapp(self):
        """A consulta de 2º grau esquece o login (o do portal continua de pé):
        a Pasta Digital recusa, e o portal passa de novo pela porta de entrada
        em vez de dar "sem acesso" (definitivo)."""
        s = self.servidor
        ctx = apoio.ContextoGravador(codigos=[CODIGO])
        with self.navegador() as nav:
            _, p2 = self.portais(nav, ctx)
            p2.entrar()
            primeiro = p2.baixar(H, self.tmp / "um" / f"{H.nome_arquivo} (2G).pdf")
            s.expirar_sessao_2g()
            antes = len(s.pedidos)
            segundo = p2.baixar(H, self.tmp / "dois" / f"{H.nome_arquivo} (2G).pdf")
        self.assertEqual(primeiro.situacao, modelos.OK, primeiro.detalhe)
        self.assertEqual(segundo.situacao, modelos.OK, segundo.detalhe)
        depois = [c for _, c in s.pedidos[antes:]]
        verificar = [i for i, c in enumerate(depois)
                     if c.startswith("/cposg5/verificarAcessoPastaDigital.do")]
        self.assertEqual(len(verificar), 2, "recusada uma vez, aceita depois da porta de entrada")
        self.assertIn("/cposg5/open.do?gateway=true", depois[verificar[0]:verificar[1]])

    def test_pasta_do_2o_grau_com_folhas_em_duplicidade(self):
        """Duas numerações na mesma Pasta Digital do 2º grau: os autos não são
        gravados (NAO_SUPORTADO); o 1º grau do mesmo número segue normal."""
        ctx = apoio.ContextoGravador(codigos=[CODIGO])
        pasta = self.tmp / "Lote"
        with falso.servidor_esaj(("A",), pasta_2g_duplicada=True) as s:
            self.tribunal = s.tribunal()
            with self.navegador("esaj-duplicada") as nav:
                p1, p2 = self.portais(nav, ctx, s)
                p2.entrar()
                r2 = p2.baixar(A, pasta / f"{A.nome_arquivo} (2G).pdf")
                r1 = p1.baixar(A, pasta / f"{A.nome_arquivo}.pdf")
            self.assertFalse([l for l in s.localizadores.values() if l["grau"] == "2g"],
                             "nada pedido ao servidor")
            self.assertFalse([c for c in s.pedidos_de("/pastadigital/sg/getPDF.do")])
        self.assertEqual(r2.situacao, modelos.NAO_SUPORTADO)
        self.assertEqual(r2.causa, "")
        self.assertFalse(modelos.pede_nova_tentativa(r2.situacao, r2.causa))
        self.assertIn("numera folhas em duplicidade (fls. 3-4 em mais de uma peça)", r2.detalhe)
        self.assertFalse((pasta / f"{A.nome_arquivo} (2G).pdf").exists())
        self.assertFalse((pasta / "_controle" / f"{A.nome_arquivo} (2G)_capa.json").exists())
        self.assertEqual(r1.situacao, modelos.OK, r1.detalhe)

    def test_capa_do_2o_grau_no_navegador(self):
        """A leitura da página do 2º grau no navegador de verdade, no desenho
        real (rótulos sem id, tabela de cabeçalho à parte, popup de senha
        VISÍVEL que fala em segredo de justiça)."""
        with self.navegador("esaj-capa-2g") as nav:
            nav.pagina.set_content(
                "<div class='unj-entity-header__summary'><span id='numeroProcesso'>"
                f"{A.formatado}</span><span class='unj-tag' id='situacaoProcesso'>Baixado</span>"
                "<span class='unj-label'>Classe</span><div id='classeProcesso'><span>Apelação "
                "Criminal</span></div><span class='unj-label'>Seção</span><div "
                "id='secaoProcesso'><span>Tribunal de Justiça</span></div><span "
                "class='unj-label'>Órgão Julgador</span><div id='orgaoJulgadorProcesso'><span>"
                "Câmara Criminal</span></div></div><div id='maisDetalhes' class='collapse' "
                "style='display:none'><span class='unj-label'>Relator</span><div "
                "id='relatorProcesso'><span>DES. JOÃO</span></div><span class='unj-label'>"
                "Origem</span><div><span>Comarca de Arapiraca / 1ª Vara</span></div></div>"
                "<div><h2 class='subtitle'>Números de 1ª Instância</h2></div>"
                "<table><tr class='label'><td>Nº de 1ª instância</td><td>Foro</td></tr>"
                "<tr class='fundoEscuro'><td></td><td></td></tr></table>"
                f"<table><tr class='fundoClaro'><td><a href='/cpopg/show.do?processo.codigo=X1'>"
                f"{A.formatado}</a> (Principal)</td><td>Foro de Arapiraca</td></tr></table>"
                "<div><h2 class='subtitle'>Composição do Julgamento</h2></div>"
                "<table><tr class='label'><td>Participação</td><td>Magistrado</td></tr></table>"
                "<table><tr class='fundoClaro itemComposicaoJulgamento'><td class='label'>Relator"
                "</td><td>Des. João&nbsp;</td></tr></table>"
                "<div><h2 class='subtitle'>Julgamentos</h2></div>"
                "<table><tr class='label'><td>Data</td><td>Situação do julgamento</td>"
                "<td>Decisão</td></tr></table><table><tr class='fundoClaro'><td>07/10/2021</td>"
                "<td>Julgado</td><td>à unanimidade</td></tr></table>"
                "<div id='popupSenhaProcesso' style='display:block'>É necessário informar uma "
                "senha para acessar processo em segredo de justiça.<input id='senhaProcesso'>"
                "</div>")
            info = nav.pagina.evaluate(esaj._JS_PAGINA_PROCESSO, {"grau": "2g"})
            primeiro = nav.pagina.evaluate(esaj._JS_PAGINA_PROCESSO)
            modal = nav.pagina.evaluate(esaj._JS_MODAL_SENHA)
        self.assertEqual(info["capa"], {"Classe": "Apelação Criminal",
                                        "Seção": "Tribunal de Justiça",
                                        "Órgão julgador": "Câmara Criminal",
                                        "Relator": "DES. JOÃO", "Situação": "Baixado",
                                        "Origem": "Comarca de Arapiraca / 1ª Vara"})
        self.assertEqual(info["secoes"]["numeros_1a_instancia"],
                         [{"celulas": ["", ""], "codigo": ""},
                          {"celulas": [f"{A.formatado} (Principal)", "Foro de Arapiraca"],
                           "codigo": "X1"}])
        self.assertEqual(info["secoes"]["composicao"][-1]["celulas"], ["Relator", "Des. João"])
        self.assertEqual(info["secoes"]["julgamentos"][-1]["celulas"],
                         ["07/10/2021", "Julgado", "à unanimidade"])
        self.assertNotIn("segredo de justi", info["texto"].lower(),
                         "o popup do 2º grau não faz o processo sigiloso")
        self.assertFalse(esaj.texto_indica_sigilo(info["texto"]))
        self.assertTrue(modal, "o popup do 2º grau visível é o pedido de senha")
        # o 1º grau lê a mesma página como sempre (sem os campos do 2º grau)
        self.assertNotIn("Seção", primeiro["capa"])
        self.assertNotIn("numeros_1a_instancia", primeiro["secoes"])
        dados = esaj.dados_da_capa(info, A, "TJAL", grau="2g")
        self.assertEqual(dados["numeros_1a_instancia"][0]["numero"], A.formatado)
        self.assertEqual(dados["composicao"], [{"papel": "Relator", "nome": "Des. João"}])


if __name__ == "__main__":
    unittest.main()
