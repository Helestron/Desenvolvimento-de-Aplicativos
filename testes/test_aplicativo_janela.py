"""A janela: escolha do modo, pywebview simulada (fechar com trabalho, diálogos), reservas."""

from __future__ import annotations

import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

from helestron.aplicativo import janela
from helestron.download.modelos import Cancelado

from testes.test_servidor_base import ServidorDeTeste


class EventoFalso:
    def __init__(self):
        self.funcoes = []
        self._evento = threading.Event()

    def __iadd__(self, funcao):
        self.funcoes.append(funcao)
        return self

    def set(self):
        valores = [f() for f in self.funcoes]
        self._evento.set()
        return any(v is False for v in valores)

    def is_set(self):
        return self._evento.is_set()


class JanelaPywebviewFalsa:
    def __init__(self, titulo, url, **kw):
        self.titulo, self.url, self.kw = titulo, url, kw
        self.events = types.SimpleNamespace(closing=EventoFalso(), shown=EventoFalso())
        self.destruida = threading.Event()
        self.dialogos = []
        self.resposta_dialogo = ("/tmp/a.xlsx",)
        self.native = None

    def destroy(self):
        self.destruida.set()

    def restore(self):
        pass

    def show(self):
        pass

    def create_file_dialog(self, tipo, directory="", allow_multiple=False, file_types=()):
        self.dialogos.append((tipo, directory, tuple(file_types)))
        return self.resposta_dialogo


def webview_falso(roteiro):
    """Um módulo 'webview': start() mostra a janela e roda o roteiro do teste."""
    modulo = types.ModuleType("webview")
    modulo.janelas = []
    modulo.FileDialog = types.SimpleNamespace(OPEN=10, FOLDER=20, SAVE=30)

    def create_window(titulo, url, **kw):
        j = JanelaPywebviewFalsa(titulo, url, **kw)
        modulo.janelas.append(j)
        return j

    def start(**kw):
        modulo.start_kw = kw
        j = modulo.janelas[-1]
        j.events.shown.set()
        roteiro(j)

    modulo.create_window = create_window
    modulo.start = start
    return modulo


class TestEscolhaDoModo(unittest.TestCase):
    def test_forcado_pelo_ambiente(self):
        with mock.patch.dict(os.environ, {"HELESTRON_JANELA": "edge"}):
            self.assertEqual(janela._escolher_modo(), ["edge"])

    def test_fora_do_windows_nao_tenta_webview(self):
        with mock.patch.dict(os.environ, {"HELESTRON_JANELA": ""}), \
                mock.patch.object(janela, "NO_WINDOWS", False):
            self.assertEqual(janela._escolher_modo(), ["edge", "navegador"])

    def test_com_webview2(self):
        with mock.patch.dict(os.environ, {"HELESTRON_JANELA": ""}), \
                mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(janela, "webview2_disponivel", return_value=True):
            self.assertEqual(janela._escolher_modo(), ["webview", "edge", "navegador"])


class TestJanelas(ServidorDeTeste):
    def test_reservas_em_ordem(self):
        with mock.patch.dict(os.environ, {"HELESTRON_JANELA": ""}), \
                mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(janela, "webview2_disponivel", return_value=True), \
                mock.patch.object(janela.JanelaWebview, "abrir", return_value=False), \
                mock.patch.object(janela.JanelaEdge, "abrir", return_value=False), \
                mock.patch.object(janela.JanelaNavegador, "abrir", return_value=True):
            self.assertEqual(janela.abrir(self.app, self.app.url), "navegador")
        self.assertEqual(self.app.modo, "navegador")
        self.assertIsInstance(self.app.janela, janela.JanelaNavegador)

    def test_nada_abre(self):
        with mock.patch.dict(os.environ, {"HELESTRON_JANELA": "edge"}), \
                mock.patch.object(janela, "achar_edge", return_value=None):
            self.assertEqual(janela.abrir(self.app, self.app.url), "")
        self.assertIsNone(self.app.janela)

    def test_pywebview_abre_e_fecha_sem_trabalho(self):
        def roteiro(j):
            self.assertTrue(j.events.closing.set() is False)       # não cancela
        modulo = webview_falso(roteiro)
        with mock.patch.dict(sys.modules, {"webview": modulo}), \
                mock.patch.dict(os.environ, {"HELESTRON_JANELA": "webview"}):
            self.assertEqual(janela.abrir(self.app, self.app.url), "janela")
        j = modulo.janelas[0]
        self.assertEqual(j.titulo, "Helestron")
        self.assertEqual((j.kw["width"], j.kw["height"], j.kw["min_size"]), (1280, 820, (1100, 720)))
        self.assertEqual(modulo.start_kw["gui"], "edgechromium")
        self.assertFalse(modulo.start_kw["private_mode"])
        self.assertTrue(modulo.start_kw["storage_path"].endswith("webview"))
        self.assertEqual(self.app.modo, "janela")

    def test_pywebview_que_nunca_aparece_vai_para_a_reserva(self):
        modulo = webview_falso(lambda j: None)
        modulo.start = lambda **kw: None                               # não mostra nada
        with mock.patch.dict(sys.modules, {"webview": modulo}):
            self.assertFalse(janela.JanelaWebview(self.app).abrir(self.app.url))

    def test_fechar_com_trabalho_pergunta_pela_pagina(self):
        resultados = {}

        def roteiro(j):
            leitor = self.eventos()
            resultados["primeiro"] = j.events.closing.set()          # True = cancelado
            pergunta = leitor.esperar("pergunta")
            resultados["pergunta"] = pergunta
            self.cliente.dados("POST", f"/api/perguntas/{pergunta['id']}/responder",
                               {"valor": True})
            resultados["destruida"] = j.destruida.wait(15)

        def baixar(numeros, destino, opcoes, ctx, *a):
            while not ctx.cancelado():          # o encerramento pede a parada
                time.sleep(0.05)
            raise Cancelado()

        modulo = webview_falso(roteiro)
        with mock.patch("helestron.servicos.baixar_lote", side_effect=baixar):
            self.cliente.dados("POST", "/api/download/iniciar",
                               {"processos": ["0700123-83.2024.8.02.0001"]})
            with mock.patch.dict(sys.modules, {"webview": modulo}):
                janela.JanelaWebview(self.app).abrir(self.app.url)
        self.assertTrue(resultados["primeiro"])
        self.assertEqual(resultados["pergunta"]["tipo"], "confirmar")
        self.assertIn("Baixar 1 processo", resultados["pergunta"]["mensagem"])
        self.assertTrue(resultados["destruida"])
        self.assertTrue(self.app.fechando)

    def test_dialogos_e_mostrar(self):
        def roteiro(j):
            self.app.janela.tem_dialogos = True
            dados = self.cliente.dados("POST", "/api/dialogo/arquivo",
                                       {"titulo": "Relação", "tipos": ["Planilhas|*.xlsx"],
                                        "inicial": "/tmp"})
            resultados["arquivo"] = dados
            j.resposta_dialogo = None
            resultados["pasta"] = self.cliente.dados("POST", "/api/dialogo/pasta", {})
            resultados["mostrar"] = self.cliente.dados("POST", "/api/janela/mostrar")
            resultados["dialogos"] = list(j.dialogos)

        resultados = {}
        modulo = webview_falso(roteiro)
        with mock.patch.dict(sys.modules, {"webview": modulo}), \
                mock.patch.dict(os.environ, {"HELESTRON_JANELA": "webview"}):
            janela.abrir(self.app, self.app.url)
        self.assertEqual(resultados["arquivo"], {"caminho": "/tmp/a.xlsx"})
        self.assertEqual(resultados["pasta"], {"caminho": None})
        self.assertEqual(resultados["mostrar"], {"mostrou": True})
        self.assertEqual(resultados["dialogos"][0], (10, "/tmp", ("Planilhas (*.xlsx)",)))
        self.assertEqual(resultados["dialogos"][1][0], 20)

    def test_edge_em_modo_aplicativo(self):
        processo = mock.Mock()
        processo.poll.return_value = 0                  # o Edge "fechou"
        with mock.patch.object(janela.subprocess, "Popen", return_value=processo) as popen, \
                mock.patch.object(janela, "SEM_SINAL_S", 0.1), \
                mock.patch.object(janela, "PRIMEIRO_SINAL_S", 0.1):
            self.app.hub.ultimo_contato = time.monotonic() - 10
            ok = janela.JanelaEdge(self.app, executavel=janela.Path("/opt/msedge")).abrir(
                self.app.url)
        self.assertTrue(ok)
        argumentos = popen.call_args[0][0]
        self.assertEqual(argumentos[0], str(janela.Path("/opt/msedge")))
        self.assertIn(f"--app={self.app.url}", argumentos)
        self.assertIn("--window-size=1280,820", argumentos)
        self.assertTrue(any(a.startswith("--user-data-dir=") and a.endswith("edge-app")
                            for a in argumentos))

    def test_pagina_viva_segura_o_programa(self):
        janela_ = janela.JanelaNavegador(self.app)
        fim = threading.Event()

        def esperar():
            janela_._esperar_pagina()
            fim.set()

        # ping curto: o servidor percebe logo a conexão fechada
        with mock.patch("helestron.servidor.api_geral.INTERVALO_PING_S", 0.1), \
                mock.patch.object(janela, "SEM_SINAL_S", 0.3), \
                mock.patch.object(janela, "PRIMEIRO_SINAL_S", 0.3):
            leitor = self.eventos()                     # uma página conectada
            threading.Thread(target=esperar, daemon=True).start()
            self.assertFalse(fim.wait(1.5))             # conectada: continua
            leitor.fechar()
            self.assertTrue(fim.wait(6))                # sem sinal: encerra
        self.assertEqual(self.app.hub.conectados, 0)


if __name__ == "__main__":
    unittest.main()
