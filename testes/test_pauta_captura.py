"""Pauta: captura assistida - a barra do Helestron no navegador, clicada por um "usuário".

O usuário de mentira é um script da própria página de teste (ROBO_JS, em
testes/apoio_pauta.py): espera a barra aparecer, clica em "Capturar esta
tela" numa página sem pauta, vai à pauta, captura a primeira página, passa
à seguinte, captura duas vezes e clica em "Concluir". Cada recado que a
barra mostra é anotado no servidor de teste.
"""

from __future__ import annotations

import unittest

from helestron.pauta import regras
from helestron.pauta.captura import BARRA_JS, CapturaAssistida
from helestron.pauta.servico import ServicoPauta
from helestron.pauta.tabelas import Reconhecedor

from testes import apoio_download as apoio
from testes import apoio_eproc as ae
from testes import apoio_pauta as ap


class TestLigacao(unittest.TestCase):
    def test_a_funcao_exposta_so_enfileira(self):
        """Chamar o Playwright de dentro da função exposta trava a API síncrona:
        ela só guarda o pedido; quem lê a página é o laço de espera."""

        class PaginaQueNaoPodeSerTocada:
            def __getattr__(self, nome):
                raise AssertionError(f"a função exposta tocou na página ({nome})")

        pagina = PaginaQueNaoPodeSerTocada()
        cap = CapturaAssistida(nav=None, regras=regras.carregar(),
                               reconhecedor=Reconhecedor(regras.carregar(), "esaj"))
        self.assertEqual(cap._ligacao({"page": pagina}, {"acao": "capturar"}), {"recebido": True})
        self.assertEqual(cap._ligacao({"page": pagina}, "concluir"), {"recebido": True})
        self.assertEqual([acao for _, acao in cap.fila], ["capturar", "concluir"])
        self.assertIs(cap.fila[0][0], pagina)

    def test_barra_em_portugues_e_isolada(self):
        for trecho in ("Capturar esta tela", "Concluir", "attachShadow", "window.top !== window",
                       "Helestron — vá até a pauta de audiências", "aria-live"):
            self.assertIn(trecho, BARRA_JS)


class TestCapturaNoNavegador(apoio.PastaTemporaria):
    @classmethod
    def setUpClass(cls):
        if ae.navegador_de_teste() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")

    def setUp(self):
        super().setUp()
        self.amb = ap.config_temporaria(self.tmp)

    def servico(self, web) -> ServicoPauta:
        s = ServicoPauta(self.amb.cfg, self.tmp / "local" / "pauta.sqlite3",
                         fabrica_navegador=lambda t, o: ap.navegador_web(self.tmp),
                         fabrica_portal=lambda nav, t, o, ctx, cred: ap.PortalDeTeste(
                             nav, web, ctx, cred),
                         cofre=apoio.CofreFalso({"esaj:TJAL": (ap.USUARIO, ap.SENHA)}))
        s.limite_captura_s = 60
        self.addCleanup(s.fechar)
        return s

    def test_usuario_captura_duas_paginas_e_conclui(self):
        web = ap.PortalWebFalso(robo=True).iniciar()
        self.addCleanup(web.parar)
        s = self.servico(web)
        eventos = []
        s.eventos = lambda tipo, dados: eventos.append((tipo, dados))
        ctx = apoio.ContextoGravador()
        r = s.capturar(ctx, "tjal", "esaj")
        self.assertEqual((r["capturadas"], r["novas"], r["telas"], r["motivo"], r["fonte"]),
                         (6, 6, 3, "concluida", "esaj-tjal"))
        self.assertEqual(web.registro_robo, [
            "Não encontrei a tabela de audiências nesta tela. Abra a pauta de audiências, com a "
            "lista na tela, e clique de novo.",
            "3 audiências reconhecidas nesta tela. Total: 3. Vá à próxima página e capture de "
            "novo, ou clique em Concluir.",
            "3 audiências reconhecidas nesta tela. Total: 6. Vá à próxima página e capture de "
            "novo, ou clique em Concluir.",
            "3 audiências reconhecidas nesta tela (3 já capturadas). Total: 6. Vá à próxima "
            "página e capture de novo, ou clique em Concluir."])
        fonte = s.fontes()[0]
        self.assertEqual(fonte["modo"], "capturado")
        self.assertEqual(fonte["url"], web.base + "/pauta/consultar?dataInicio=05/10/2026&"
                                                  "dataFim=16/10/2026")
        self.assertTrue(fonte["monitorada"], "a URL lembrada serve ao monitoramento")
        lista = s.listar(ap.INICIO, ap.FIM)["audiencias"]
        esperadas = ap.no_periodo(ap.audiencias_padrao(), ap.INICIO, ap.FIM)[:6]
        self.assertEqual([a["processo"] for a in lista], [f.processo for f in esperadas])
        self.assertEqual({a["fonte"] for a in lista}, {"esaj-tjal"})
        # o sigilo que a captura revelou é informado (o servidor tira o processo do acervo)
        self.assertEqual(r.get("sigilosos_novos"),
                         sorted(f.processo for f in esperadas if f.sigiloso))
        self.assertTrue(r["sigilosos_novos"])
        self.assertEqual(web.proibidas, [])
        self.assertEqual(ctx.avisos[0][0], "Captura da pauta")
        self.assertEqual(ctx.status_[-1], "Captura concluída: 6 audiências. O endereço ficou "
                                          "lembrado para o monitoramento.")
        self.assertEqual(eventos[0], ("pauta", {"tipo": "atualizada", "dados": {
            "novas": 6, "atualizadas": 0, "canceladas": 0, "removidas": 0, "total": 6}}))
        self.assertIsNotNone(s.ultima_sincronizacao())

    def test_prazo_sem_concluir(self):
        web = ap.PortalWebFalso(robo=False).iniciar()
        self.addCleanup(web.parar)
        s = self.servico(web)
        s.limite_captura_s = 1.5
        ctx = apoio.ContextoGravador()
        r = s.capturar(ctx, "TJAL", "esaj")
        self.assertEqual((r["capturadas"], r["motivo"], r["url"]), (0, "prazo", ""))
        self.assertEqual(ctx.status_[-1], "Nenhuma audiência foi capturada.")
        fonte = s.fontes()[0]
        self.assertEqual((fonte["modo"], fonte["url"], fonte["ultima_sincronizacao"]),
                         ("automatico", "", None))

    def test_parar_durante_a_captura(self):
        from helestron.download.modelos import Cancelado

        web = ap.PortalWebFalso(robo=False).iniciar()
        self.addCleanup(web.parar)
        s = self.servico(web)

        class ParaLogoDepois(apoio.ContextoGravador):
            def cancelado(self):
                return any("Capturar esta tela" in x for x in self.status_)

        with self.assertRaises(Cancelado):
            s.capturar(ParaLogoDepois(), "TJAL", "esaj")
        self.assertEqual(s.listar(ap.INICIO, ap.FIM)["audiencias"], [])


if __name__ == "__main__":
    unittest.main()
