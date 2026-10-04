"""Pauta no portal, ponta a ponta: Chromium de verdade contra portais de mentira, sem rede.

* um "e-SAJ" servido de verdade em 127.0.0.1 (http.server): login, menu em
  dois níveis ("Audiências" -> "Pauta de Audiências"), um "Designar
  audiência" e um "Sair" que não podem ser clicados, um painel de
  intimações (data + processo, que não é pauta), o formulário do período e
  a tabela paginada ("Próxima »");
* o eProc falso do download (testes/apoio_eproc.py) com o menu da pauta: o
  login de verdade do PortalEProc (senha + código do autenticador, pedido
  pelo Contexto), links assinados para a sessão, o formulário do Infra e a
  paginação por infraAcaoPaginar.

Pula sozinho se não houver Chromium que abra.
"""

from __future__ import annotations

import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from helestron.download import eproc
from helestron.download.eproc import PortalEProc
from helestron.nucleo import tribunais
from helestron.pauta import regras
from helestron.pauta.navegacao import LeitorDePauta
from helestron.pauta.servico import ErroPauta, ServicoPauta
from helestron.pauta.tabelas import Reconhecedor

from testes import apoio_download as apoio
from testes import apoio_eproc as ae
from testes import apoio_pauta as ap


class TestApoio(unittest.TestCase):
    def test_opcoes_do_seletor_de_pagina(self):
        from helestron.pauta.navegacao import _opcoes_de_pagina, parametros

        self.assertTrue(_opcoes_de_pagina(["1", "2", "3"]))
        self.assertTrue(_opcoes_de_pagina(["Página 1", "Página 2"]))
        self.assertFalse(_opcoes_de_pagina(["10", "20", "50"]))
        self.assertFalse(_opcoes_de_pagina(["Todas", "1"]))
        self.assertFalse(_opcoes_de_pagina([]))
        self.assertEqual(parametros("https://x/controlador.php?acao=audiencia_listar&hash=ab"),
                         {"acao": "audiencia_listar", "hash": "ab"})


class ComNavegador(apoio.PastaTemporaria):
    @classmethod
    def setUpClass(cls):
        if ae.navegador_de_teste() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")

    def setUp(self):
        super().setUp()
        self.amb = ap.config_temporaria(self.tmp)


class TestPortalWeb(ComNavegador):
    def setUp(self):
        super().setUp()
        self.web = ap.PortalWebFalso().iniciar()
        self.addCleanup(self.web.parar)

    def servico(self, **extra) -> ServicoPauta:
        s = ServicoPauta(self.amb.cfg, self.tmp / "local" / "pauta.sqlite3",
                         fabrica_navegador=lambda t, o: ap.navegador_web(self.tmp),
                         fabrica_portal=lambda nav, t, o, ctx, cred: ap.PortalDeTeste(
                             nav, self.web, ctx, cred),
                         cofre=apoio.CofreFalso({"esaj:TJAL": (ap.USUARIO, ap.SENHA)}), **extra)
        s.espera_pagina_s = 8
        self.addCleanup(s.fechar)
        return s

    def test_descobre_pelo_menu_preenche_o_periodo_e_pagina(self):
        s = self.servico()
        s.salvar_fonte("TJAL", "esaj", "")
        ctx = apoio.ContextoGravador()
        r = s.sincronizar(ctx, None, ap.INICIO, ap.FIM)
        self.assertEqual((r["novas"], r["total"]), (8, 8))
        parcial = r["fontes"][0]
        self.assertEqual((parcial["paginas"], parcial["periodo_aplicado"]), (3, True))
        self.assertEqual(self.web.proibidas, [], "nem 'Designar audiência' nem 'Sair'")
        self.assertEqual(self.web.periodos, [("05/10/2026", "16/10/2026")] * 3)
        self.assertEqual(self.web.paginas, [1, 2, 3])
        self.assertEqual(self.web.logins, 1)
        caminhos = [c.split("?")[0] for _, c in self.web.pedidos]
        self.assertLess(caminhos.index("/audiencias"), caminhos.index("/pauta/consultar"),
                        "achou a pauta um nível abaixo do menu")
        fonte = s.fontes()[0]
        self.assertEqual(fonte["url"], self.web.base + "/pauta/consultar")
        self.assertEqual(fonte["menu"], "Pauta de Audiências")
        self.assertTrue(fonte["monitorada"])
        lista = s.listar(ap.INICIO, ap.FIM)["audiencias"]
        esperadas = ap.no_periodo(ap.audiencias_padrao(), ap.INICIO, ap.FIM)
        self.assertEqual([a["processo"] for a in lista], [f.processo for f in esperadas])
        por_processo = {a["processo"]: a for a in lista}
        self.assertTrue(por_processo[esperadas[4].processo]["sigiloso"])
        self.assertEqual(por_processo[esperadas[5].processo]["link"], esperadas[5].link)
        self.assertEqual(por_processo[esperadas[1].processo]["tipo"], "Una")
        self.assertEqual({a["origem"].split("?")[0] for a in lista},
                         {self.web.base + "/pauta/consultar"})
        self.assertIn("Lendo a pauta do e-SAJ do TJAL (página 3)…", ctx.status_)

        # segunda vez: a rota lembrada vai direto à pauta; o que saiu vira "removida";
        # e a sessão que cai no meio é refeita
        removida = self.web.audiencias.pop(2)
        self.web.pedidos.clear()
        self.web.expirar_na_pauta(1)
        r = s.sincronizar(ctx, None, ap.INICIO, ap.FIM)
        self.assertEqual((r["novas"], r["removidas"], r["total"]), (0, 1, 7))
        caminhos = [c.split("?")[0] for _, c in self.web.pedidos]
        self.assertNotIn("/audiencias", caminhos, "não precisou do menu")
        self.assertEqual(self.web.logins, 2, "a sessão caiu e o login foi refeito")
        alteracoes = s.alteracoes()
        self.assertEqual([(a["tipo"], a["audiencia"]["processo"]) for a in alteracoes],
                         [("removida", removida.processo)])

    def test_rota_conhecida_do_pauta_json(self):
        s = self.servico(regras=regras.de_dicionario({"rotas": {"tribunais": {
            "TJAL": {"esaj": ["/pauta/consultar"]}}}}))
        s.salvar_fonte("TJAL", "esaj", "")
        s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        caminhos = [c.split("?")[0] for _, c in self.web.pedidos]
        self.assertNotIn("/audiencias", caminhos)
        self.assertEqual(len(s.listar(ap.INICIO, ap.FIM)["audiencias"]), 8)

    def test_portal_sem_pauta(self):
        s = self.servico(regras=regras.de_dicionario({"menu": {"procurar": [["consulta", 50]]}}))
        s.salvar_fonte("TJAL", "esaj", "")
        with self.assertRaises(ErroPauta) as erro:
            s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.assertIn("Capturar no portal", str(erro.exception))
        self.assertIn("Capturar no portal", s.fontes()[0]["ultimo_erro"])
        self.assertEqual(s.listar(ap.INICIO, ap.FIM)["audiencias"], [],
                         "as intimações do painel não viraram audiência")

    def test_limite_de_paginas_e_legenda_que_nao_bate(self):
        nav = ap.navegador_web(self.tmp)
        with nav:
            portal = ap.PortalDeTeste(nav, self.web)
            portal.entrar()
            nav.pagina.goto(self.web.base + "/pauta/consultar?dataInicio=05/10/2026&"
                            "dataFim=16/10/2026", wait_until="domcontentloaded")
            r = regras.de_dicionario({"paginacao": {"limite_paginas": 2}})
            leitor = LeitorDePauta(nav.pagina, r, Reconhecedor(r, "esaj", "TJAL"), espera_s=8,
                                   nome="e-SAJ do TJAL")
            leitura = leitor.ler(ap.INICIO, ap.FIM, preencher=False)
        self.assertEqual((leitura.paginas, len(leitura.audiencias), leitura.total_informado),
                         (2, 6, 8))
        self.assertTrue(any("mais de 2 páginas" in a for a in leitura.avisos))
        self.assertTrue(any("informou 8 audiências e foram lidas 6" in a for a in leitura.avisos))
        # leitura incompleta: nada se conclui sobre o que não foi lido (nem entre as
        # datas que vieram - a página 3 podia ter mais audiências do dia 9)
        self.assertIn("mais de 2 páginas", leitura.incompleta)
        self.assertTrue(any("nenhuma audiência foi dada como fora da pauta" in a
                            for a in leitura.avisos))
        self.assertIsNone(leitura.cobertura(ap.INICIO, ap.INICIO.replace(day=4)))
        self.assertIsNone(leitura.cobertura(ap.INICIO, ap.FIM))


class TestEProc(ComNavegador):
    def setUp(self):
        super().setUp()
        self.falso = ap.EProcComPauta()
        self.tribunal = replace(tribunais.por_sigla("TJRS"), urls={"1g": [ae.BASE]})

    def servico(self, **extra) -> ServicoPauta:
        s = ServicoPauta(
            self.amb.cfg, self.tmp / "local" / "pauta.sqlite3",
            fabrica_navegador=lambda t, o: ae.navegador(self.falso, self.tmp),
            fabrica_portal=lambda nav, t, o, ctx, cred: PortalEProc(
                nav, self.tribunal, o, ctx, cred, seletores=eproc.SELETORES_PADRAO),
            cofre=apoio.CofreFalso({"eproc:TJRS": (ae.USUARIO, ae.SENHA)}), **extra)
        s.espera_pagina_s = 8
        self.addCleanup(s.fechar)
        return s

    def test_login_com_codigo_menu_assinado_e_paginacao_do_infra(self):
        s = self.servico(regras=regras.de_dicionario({"rotas": {"eproc": []}}))
        s.salvar_fonte("TJRS", "eproc", "")
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        r = s.sincronizar(ctx, None, ap.INICIO, ap.FIM)
        self.assertEqual((r["novas"], r["fontes"][0]["paginas"]), (8, 2))
        self.assertEqual(len(ctx.pedidos_codigo), 1, "o código foi pedido pelo Contexto")
        self.assertEqual(ctx.reenviaveis, [False])
        self.assertEqual(self.falso.sem_assinatura, [], "só links assinados para a sessão")
        self.assertEqual(self.falso.designar_visitas, 0)
        self.assertEqual(self.falso.pauta_pedidos, [("05/10/2026", "16/10/2026", 0),
                                                    ("05/10/2026", "16/10/2026", 1)])
        self.assertIn("Conferindo “Pauta de Audiências” no eProc do TJRS…", ctx.status_)
        lista = s.listar(ap.INICIO, ap.FIM)["audiencias"]
        self.assertEqual({(a["sistema"], a["tribunal"]) for a in lista}, {("eproc", "TJRS")})
        esperadas = ap.no_periodo(ap.audiencias_padrao("21"), ap.INICIO, ap.FIM)
        por_processo = {a["processo"]: a for a in lista}
        self.assertEqual(set(por_processo), {f.processo for f in esperadas})
        sig = por_processo[esperadas[4].processo]
        self.assertTrue(sig["sigiloso"])
        self.assertEqual(sig["partes"], "")
        self.assertEqual(por_processo[esperadas[2].processo]["situacao"], "Redesignada")
        self.assertEqual(por_processo[esperadas[3].processo]["tipo"], "Custódia")
        url = s.fontes()[0]["url"]
        self.assertIn("acao=audiencia_listar", url)

        # segunda vez, outra sessão: a rota lembrada vale pela 'acao' (o hash velho
        # não é usado - daria "Link sem assinatura")
        self.falso.sessoes.clear()
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        r = s.sincronizar(ctx, None, ap.INICIO, ap.FIM)
        self.assertEqual((r["novas"], r["atualizadas"], r["removidas"]), (0, 0, 0))
        self.assertEqual(self.falso.sem_assinatura, [])
        self.assertNotIn("Conferindo “Pauta de Audiências” no eProc do TJRS…", ctx.status_)

    def test_paginacao_so_pelo_seletor_de_pagina(self):
        self.falso = ap.EProcComPauta(so_seletor=True)
        s = self.servico()
        s.salvar_fonte("TJRS", "eproc", "")
        r = s.sincronizar(apoio.ContextoGravador(codigos=[ae.CODIGO]), None, ap.INICIO, ap.FIM)
        self.assertEqual((r["novas"], r["fontes"][0]["paginas"]), (8, 2))
        self.assertEqual([p for *_, p in self.falso.pauta_pedidos], [0, 1],
                         "o 'registros por página' (10, 20, 50) não foi tomado por paginação")

    def test_rota_conhecida_pela_acao(self):
        s = self.servico()
        s.salvar_fonte("TJRS", "eproc", "")
        s.sincronizar(apoio.ContextoGravador(codigos=[ae.CODIGO]), None, ap.INICIO, ap.FIM)
        self.assertEqual(self.falso.sem_assinatura, [])
        self.assertEqual(len(s.listar(ap.INICIO, ap.FIM)["audiencias"]), 8)


class PortalComDefeitos(ap.PortalWebFalso):
    """O e-SAJ de mentira com os tropeços do de verdade: página que demora, sessão
    que cai no meio da paginação, formulário que recusa o período, período encurtado."""

    lenta_s = 0.0            # a página 2 demora isto
    recusar = False          # o formulário valida no navegador e não envia
    encurtar_dias = 0        # o portal mostra no máximo N dias (e diz nos campos)

    def _pauta(self, h, q):
        if self.lenta_s and int(q.get("pagina") or 1) > 1:
            time.sleep(self.lenta_s)
        if self.recusar:
            form = ("<form method='get' action='/pauta/consultar' onsubmit=\"alert('Período "
                    "máximo: 30 dias'); return false;\"><label for='dataInicio'>Data inicial"
                    "</label><input id='dataInicio' name='dataInicio' maxlength='10'>"
                    "<label for='dataFim'>Data final</label><input id='dataFim' name='dataFim' "
                    "maxlength='10'><input type='submit' value='Pesquisar'></form>")
            hoje = [a for a in self.audiencias if a.data == ap.INICIO]
            return self._html(h, self._menu() + "<h1>Pauta de Audiências</h1>" + form +
                              ap.html_esaj(hoje, "Audiências de hoje"), "Pauta de Audiências")
        if self.encurtar_dias and q.get("dataInicio"):
            de = datetime.strptime(q["dataInicio"], "%d/%m/%Y").date()
            ate = datetime.strptime(q["dataFim"], "%d/%m/%Y").date()
            if (ate - de).days > self.encurtar_dias:
                q = dict(q, dataFim=(de + timedelta(days=self.encurtar_dias)).strftime("%d/%m/%Y"))
        return super()._pauta(h, q)


class TestLeituraIncompletaNaoRemove(ComNavegador):
    """Página não lida não é audiência "fora da pauta"."""

    def setUp(self):
        super().setUp()
        self.web = PortalComDefeitos().iniciar()
        self.addCleanup(self.web.parar)

    def servico(self) -> ServicoPauta:
        s = ServicoPauta(self.amb.cfg, self.tmp / "local" / "pauta.sqlite3",
                         fabrica_navegador=lambda t, o: ap.navegador_web(self.tmp),
                         fabrica_portal=lambda nav, t, o, ctx, cred: ap.PortalDeTeste(
                             nav, self.web, ctx, cred),
                         cofre=apoio.CofreFalso({"esaj:TJAL": (ap.USUARIO, ap.SENHA)}))
        s.espera_pagina_s = 2
        self.addCleanup(s.fechar)
        s.salvar_fonte("TJAL", "esaj", "")
        r = s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.assertEqual((r["novas"], r["total"]), (8, 8))
        return s

    def confere_nada_removido(self, s, r):
        self.assertEqual(r["removidas"], 0, r["avisos"])
        self.assertEqual([a for a in s.alteracoes() if a["tipo"] == "removida"], [])
        self.assertEqual(len(s.listar(ap.INICIO, ap.FIM)["audiencias"]), 8)

    def test_pagina_que_nao_abre_a_tempo(self):
        s = self.servico()
        self.web.lenta_s = 4
        r = s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.confere_nada_removido(s, r)
        self.assertIn("a página 2 não abriu a tempo", r["fontes"][0]["incompleta"])
        self.assertTrue(any("nenhuma audiência foi dada como fora da pauta" in a
                            for a in r["avisos"]))

    def test_sessao_que_cai_na_pagina_2(self):
        s = self.servico()
        logins = self.web.logins
        # 1: a rota lembrada; 2: a pesquisa (página 1); 3: a página 2 - a sessão cai
        self.web.expirar_na_pauta(3)
        r = s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.confere_nada_removido(s, r)
        self.assertEqual(self.web.logins, logins + 1, "entrou de novo e releu a pauta inteira")
        self.assertEqual((r["total"], r["fontes"][0]["incompleta"]), (8, ""))

    def test_formulario_que_recusa_o_periodo(self):
        s = self.servico()
        self.web.recusar = True
        r = s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.confere_nada_removido(s, r)
        self.assertFalse(r["fontes"][0]["periodo_aplicado"])
        self.assertTrue(any("não aceitou o período" in a for a in r["avisos"]), r["avisos"])

    def test_portal_que_encurta_o_periodo(self):
        s = self.servico()
        self.web.encurtar_dias = 3          # pede 05 a 16/10; o portal mostra 05 a 08/10
        r = s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.confere_nada_removido(s, r)
        self.assertFalse(r["fontes"][0]["periodo_aplicado"])
        self.assertTrue(any("mostrou o período de 05/10/2026 a 08/10/2026" in a
                            for a in r["avisos"]), r["avisos"])
        # o que estava dentro das datas mostradas e sumiu, sai da pauta (como sempre)
        self.web.encurtar_dias = 0
        sumiu = self.web.audiencias.pop(1)            # 05/10, 14:30
        r = s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.assertEqual(r["removidas"], 1)
        self.assertEqual([a["audiencia"]["processo"] for a in s.alteracoes()
                          if a["tipo"] == "removida"], [sumiu.processo])


class TestRowspanNoNavegador(ComNavegador):
    def test_js_tabelas_leva_o_rowspan(self):
        from helestron.pauta.navegacao import JS_TABELAS
        from helestron.pauta.tabelas import Tabela

        n1, n2 = ap.numero("0700951"), ap.numero("0700952")
        html = ap.pagina("<table><tr><th>Data</th><th>Hora</th><th>Processo</th><th>Tipo</th>"
                         "</tr><tr><td rowspan='2'>05/10/2026</td><td>09:00</td>"
                         f"<td>{n1}</td><td>Una</td></tr><tr><td>10:00</td><td>{n2}</td>"
                         "<td>Conciliação</td></tr></table>")
        nav = ap.navegador_web(self.tmp)
        with nav:
            nav.pagina.set_content(html)
            dados = nav.pagina.evaluate(JS_TABELAS)
        t = Tabela.de_js(dados["tabelas"][0])
        self.assertEqual([c.texto for c in t.linhas[2]], ["05/10/2026", "10:00", n2,
                                                          "Conciliação"])


if __name__ == "__main__":
    unittest.main()
