"""Pauta no portal: o robô só LÊ (achado 23). Chromium de verdade contra um
portal de mentira com AÇÕES sobre a pauta no menu ("Bloquear pauta", "Fechar
pauta do dia", "Marcar audiência") e telas com "Data inicial", "Data final" e
um botão que grava ("Aplicar", "Bloquear"): nenhuma é aberta pelo menu,
nenhum formulário delas é enviado - nem pelo Enter.

Pula sozinho se não houver Chromium que abra.
"""

from __future__ import annotations

import unittest
import urllib.parse
from datetime import date
from html import escape

from helestron.pauta import regras
from helestron.pauta.navegacao import _RE_ACAO, LeitorDePauta
from helestron.pauta.modelos import normalizar_texto
from helestron.pauta.servico import ServicoPauta
from helestron.pauta.tabelas import Reconhecedor

from testes import apoio_download as apoio
from testes import apoio_eproc as ae
from testes import apoio_pauta as ap

# caminho -> (título da tela, texto do botão)
TELAS_DE_ACAO = {
    "/bloqueio": ("Bloqueio de pauta de audiências", "Aplicar"),
    "/fechar": ("Fechamento da pauta de audiências do dia", "OK"),
    "/marcar": ("Marcar audiência", "Gerar"),
    # tela que se diz pauta, mas cujo único botão grava
    "/pauta-so-bloquear": ("Pauta de audiências", "Bloquear"),
}


class PortalComAcoes(ap.PortalWebFalso):
    """O e-SAJ de mentira com ações sobre a pauta no menu."""

    def __init__(self):
        super().__init__()
        self.escritas: list[tuple[str, str]] = []

    def _menu(self) -> str:
        return super()._menu().replace(
            "</nav>", " · <a href='/bloqueio'>Bloquear pauta</a> · <a href='/fechar'>Fechar "
                      "pauta do dia</a> · <a href='/marcar'>Marcar audiência</a></nav>")

    def _atender(self, h, metodo: str) -> None:
        caminho = urllib.parse.urlsplit(h.path).path
        if caminho not in TELAS_DE_ACAO:
            return super()._atender(h, metodo)
        self.pedidos.append((metodo, h.path))
        tamanho = int(h.headers.get("Content-Length") or 0)
        corpo = h.rfile.read(tamanho).decode("utf-8", "replace") if tamanho else ""
        titulo, botao = TELAS_DE_ACAO[caminho]
        if metodo == "POST":
            self.escritas.append((caminho, corpo))
            return self._html(h, self._menu() + f"<h1>{escape(titulo)}</h1>"
                              "<p>PAUTA ALTERADA NO TRIBUNAL</p>", titulo)
        return self._html(h, self._menu() + f"<h1>{escape(titulo)}</h1>"
                          f"<form method='post' action='{caminho}'>"
                          "<label for='di'>Data inicial</label><input id='di' name='di'>"
                          "<label for='df'>Data final</label><input id='df' name='df'>"
                          f"<button type='submit'>{escape(botao)}</button></form>", titulo)


class TestRegraFixa(unittest.TestCase):
    def test_acoes_e_o_que_nao_e_acao(self):
        for texto in ("Bloquear pauta", "Desbloquear pauta", "Fechar pauta do dia",
                      "Publicar pauta", "Gerar pauta", "Liberar pauta", "Reservar pauta",
                      "Marcar audiência", "Encerrar audiência", "Confirmar", "Salvar",
                      "Bloqueio de pauta de audiências", "Designar audiência"):
            with self.subTest(texto=texto):
                self.assertTrue(_RE_ACAO.search(normalizar_texto(texto)))
        for texto in ("Pauta de Audiências", "Agenda de audiências", "Consultar audiências",
                      "Audiências marcadas", "Audiências encerradas", "Pesquisar",
                      "Relatório de audiências", "Gerenciar audiências"):
            with self.subTest(texto=texto):
                self.assertFalse(_RE_ACAO.search(normalizar_texto(texto)))


class ComNavegador(apoio.PastaTemporaria):
    @classmethod
    def setUpClass(cls):
        if ae.navegador_de_teste() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")

    def setUp(self):
        super().setUp()
        self.amb = ap.config_temporaria(self.tmp)
        self.web = PortalComAcoes().iniciar()
        self.addCleanup(self.web.parar)


class TestRoboSoLe(ComNavegador):
    def test_menu_com_acoes_nao_grava_nada(self):
        s = ServicoPauta(self.amb.cfg, self.tmp / "local" / "pauta.sqlite3",
                         fabrica_navegador=lambda t, o: ap.navegador_web(self.tmp),
                         fabrica_portal=lambda nav, t, o, ctx, cred: ap.PortalDeTeste(
                             nav, self.web, ctx, cred),
                         cofre=apoio.CofreFalso({"esaj:TJAL": (ap.USUARIO, ap.SENHA)}))
        s.espera_pagina_s = 8
        self.addCleanup(s.fechar)
        s.salvar_fonte("TJAL", "esaj", "")
        r = s.sincronizar(apoio.ContextoGravador(), None, ap.INICIO, ap.FIM)
        self.assertEqual(r["total"], 8, "achou a pauta de verdade pelo menu")
        self.assertEqual(self.web.escritas, [], "o robô gravou no portal")
        abertos = {urllib.parse.urlsplit(c).path for _, c in self.web.pedidos}
        self.assertFalse(abertos & set(TELAS_DE_ACAO), abertos)

    def test_tela_de_acao_e_botao_que_grava(self):
        nav = ap.navegador_web(self.tmp)
        r = regras.carregar()
        with nav:
            portal = ap.PortalDeTeste(nav, self.web)
            portal.entrar()
            for caminho in TELAS_DE_ACAO:
                with self.subTest(caminho=caminho):
                    nav.pagina.goto(self.web.base + caminho, wait_until="domcontentloaded")
                    leitor = LeitorDePauta(nav.pagina, r, Reconhecedor(r, "esaj", "TJAL"),
                                           espera_s=3, nome="e-SAJ do TJAL")
                    self.assertFalse(leitor.preencher_periodo(date(2026, 10, 1),
                                                              date(2026, 11, 30)))
                    self.assertEqual(self.web.escritas, [], caminho)
                    self.assertNotIn("PAUTA ALTERADA", nav.pagina.content())
        # a tela que se diz pauta e só tem "Bloquear": o motivo fica no aviso
        self.assertIn("não mostrou um botão de pesquisa", leitor.aviso_periodo)


if __name__ == "__main__":
    unittest.main()
