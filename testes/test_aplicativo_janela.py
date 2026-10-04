"""A janela: escolha do modo, pywebview simulada (fechar com trabalho, diálogos), reservas,
a vigia do WebView2 que não carrega, o tamanho pela área útil e o chamar atenção."""

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
        self.events = types.SimpleNamespace(closing=EventoFalso(), shown=EventoFalso(),
                                            loaded=EventoFalso())
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


def webview_falso(roteiro, carrega=True):
    """Um módulo 'webview': start() mostra a janela (e carrega a página, como
    o WebView2 que funciona) e roda o roteiro do teste."""
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
        if carrega:
            j.events.loaded.set()
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
                mock.patch.object(janela, "webview2_disponivel", return_value=True), \
                mock.patch.object(janela, "_navegador_padrao", return_value=("ChromeHTML", None)):
            self.assertEqual(janela._escolher_modo(), ["webview", "edge", "navegador"])

    def test_webview2_antigo_conta_como_ausente(self):
        """A pywebview 6 precisa do runtime 101 (ICoreWebView2Environment10):
        com o 86 a 100, a janela abriria vazia."""
        for versao, serve in (("101.0.1210.39", True), ("120.0.2210.91", True),
                              ("100.0.1185.50", False), ("90.0.818.66", False),
                              ("0.0.0.0", False), ("", False), (None, False), ("lixo", False)):
            with self.subTest(versao=versao):
                self.assertEqual(janela.versao_suficiente(versao), serve)
        with mock.patch.dict(os.environ, {"HELESTRON_JANELA": ""}), \
                mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(janela, "versao_webview2", return_value="90.0.818.66"), \
                mock.patch.object(janela, "_navegador_padrao", return_value=("MSEdgeHTM", None)):
            self.assertFalse(janela.webview2_disponivel())
            self.assertEqual(janela._escolher_modo(), ["edge", "navegador"])

    def test_internet_explorer_nunca_e_a_reserva(self):
        casos = [(("IE.HTTP", None), False), (("IE.HTTPS", None), False),
                 (("AppXq0fevzme2pys62n3e0fbqa7peapykr8v", None), False),
                 ((None, '"C:\\Program Files\\Internet Explorer\\iexplore.exe" %1'), False),
                 (("ChromeHTML", None), True), (("MSEdgeHTM", None), True),
                 (("FirefoxURL-308046B0AF4A39CB", None), True), ((None, None), True)]
        for (progid, comando), serve in casos:
            with self.subTest(progid=progid, comando=comando):
                self.assertEqual(not janela.navegador_inadequado(progid, comando), serve)
        with mock.patch.dict(os.environ, {"HELESTRON_JANELA": ""}), \
                mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(janela, "webview2_disponivel", return_value=False), \
                mock.patch.object(janela, "_navegador_padrao", return_value=("IE.HTTP", None)), \
                self.assertLogs("aplicativo.janela", "WARNING"):
            self.assertEqual(janela._escolher_modo(), ["edge"])

    def test_motivo_sem_janela_explica_o_webview2(self):
        with mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(janela, "versao_webview2", return_value=None), \
                mock.patch.object(janela, "achar_edge", return_value=None):
            texto = janela.motivo_sem_janela()
        self.assertIn("WebView2 Runtime", texto)
        self.assertIn("Internet Explorer não é compatível", texto)
        self.assertIn(janela.URL_WEBVIEW2, texto)
        with mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(janela, "versao_webview2", return_value="95.0.1020.53"), \
                mock.patch.object(janela, "achar_edge", return_value=None):
            self.assertIn("antigo (versão 95.0.1020.53", janela.motivo_sem_janela())


class TestTamanho(unittest.TestCase):
    def test_cabe_na_area_util(self):
        # Full HD a 100 % (barra de tarefas de 40 px): o tamanho padrão
        self.assertEqual(janela.tamanho_inicial((1920, 1040)),
                         {"width": 1280, "height": 820, "min_size": (1100, 720), "maximized": False})
        self.assertEqual(janela.tamanho_inicial(None)["height"], 820)
        # Full HD a 150 % (1280×672 DIP úteis) e 1366×768 a 125 %: maximizada,
        # e nada maior que a área útil
        for area in ((1280, 672), (1366 / 1.25, 728 / 1.25), (1366, 728)):
            with self.subTest(area=area):
                t = janela.tamanho_inicial(area)
                self.assertTrue(t["maximized"])
                self.assertLessEqual(t["width"], area[0])
                self.assertLessEqual(t["height"], area[1] - janela.MARGEM_TELA)
                self.assertLessEqual(t["min_size"][0], t["width"])
                self.assertLessEqual(t["min_size"][1], t["height"])


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

    def test_webview2_que_nao_carrega_cai_no_edge(self):
        """O WebView2 falhou ao iniciar: a janela aparece (Form.Shown), mas
        fica cinza e vazia - a vigia a fecha e o programa abre no Edge."""
        def roteiro(j):
            resultados["destruida"] = j.destruida.wait(15)

        resultados = {}
        modulo = webview_falso(roteiro, carrega=False)
        self.app.hub.ultimo_contato = self.app.iniciado_em - 1        # a página nunca falou
        with mock.patch.dict(sys.modules, {"webview": modulo}), \
                mock.patch.dict(os.environ, {"HELESTRON_JANELA": ""}), \
                mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(janela, "webview2_disponivel", return_value=True), \
                mock.patch.object(janela, "_navegador_padrao", return_value=("ChromeHTML", None)), \
                mock.patch.object(janela, "area_util_dip", return_value=None), \
                mock.patch.object(janela, "PRAZO_CARREGAR_S", 0.5), \
                mock.patch.object(janela.JanelaEdge, "abrir", return_value=True) as edge:
            self.assertEqual(janela.abrir(self.app, self.app.url), "edge")
        self.assertTrue(resultados["destruida"])
        edge.assert_called_once()
        self.assertIsInstance(self.app.janela, janela.JanelaEdge)

    def test_janela_vazia_fechada_pelo_usuario_tambem_cai_no_edge(self):
        modulo = webview_falso(lambda j: j.events.closing.set(), carrega=False)
        self.app.hub.ultimo_contato = self.app.iniciado_em - 1
        with mock.patch.dict(sys.modules, {"webview": modulo}):
            self.assertFalse(janela.JanelaWebview(self.app).abrir(self.app.url))
        self.assertNotIn(janela.JanelaWebview.fechar, self.app.ao_encerrar)

    def test_tamanho_pela_area_util_do_monitor(self):
        modulo = webview_falso(lambda j: None)
        with mock.patch.dict(sys.modules, {"webview": modulo}), \
                mock.patch.object(janela, "area_util_dip", return_value=(1280, 672)):
            self.assertTrue(janela.JanelaWebview(self.app).abrir(self.app.url))
        kw = modulo.janelas[0].kw
        self.assertTrue(kw["maximized"])
        self.assertLessEqual(kw["height"], 672 - janela.MARGEM_TELA)
        self.assertLessEqual(kw["min_size"][1], kw["height"])
        processo = mock.Mock()
        processo.poll.return_value = 0
        self.app.iniciado_em = time.monotonic() - 20       # a página já deu sinal
        self.app.hub.ultimo_contato = time.monotonic() - 10
        with mock.patch.object(janela.subprocess, "Popen", return_value=processo) as popen, \
                mock.patch.object(janela, "area_util_dip", return_value=(1280, 672)):
            janela.JanelaEdge(self.app, executavel=janela.Path("/opt/msedge")).abrir(self.app.url)
        self.assertIn("--start-maximized", popen.call_args[0][0])

    def test_pergunta_chama_atencao_da_janela(self):
        """C3: a janela registra no servidor quem chamar quando chega uma
        pergunta (código do portal), e isso restaura, traz à frente e pisca."""
        registradas = []

        def roteiro(j):
            for funcao in registradas:
                funcao()

        modulo = webview_falso(roteiro)
        jw = janela.JanelaWebview(self.app)
        self.app.janela = jw
        with mock.patch.dict(sys.modules, {"webview": modulo}), \
                mock.patch.object(self.app, "registrar_atencao", registradas.append, create=True), \
                mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(jw, "_hwnd", return_value=4321), \
                mock.patch.object(janela, "chamar_atencao_hwnd") as atencao:
            self.assertTrue(jw.abrir(self.app.url))
        self.assertEqual(registradas, [jw.chamar_atencao])
        atencao.assert_called_once_with(4321)
        # depois que a janela saiu de cena (reserva), não faz nada
        jw._falhou = True
        with mock.patch.object(janela, "chamar_atencao_hwnd") as atencao:
            jw.chamar_atencao()
        atencao.assert_not_called()

    def test_chamar_atencao_hwnd_restaura_e_pisca(self):
        user32 = mock.Mock()
        user32.IsIconic.return_value = 1
        janela.chamar_atencao_hwnd(77, user32=user32)
        user32.ShowWindowAsync.assert_called_once_with(77, janela.SW_RESTORE)
        user32.SetForegroundWindow.assert_called_once_with(77)
        info = user32.FlashWindowEx.call_args[0][0]._obj
        self.assertEqual(info.hwnd, 77)
        self.assertEqual(info.dwFlags, janela.FLASHW_ALL | janela.FLASHW_TIMERNOFG)
        user32 = mock.Mock()
        user32.IsIconic.return_value = 0                 # não minimizada: só pisca
        janela.chamar_atencao_hwnd(77, user32=user32)
        user32.ShowWindowAsync.assert_not_called()
        user32.FlashWindowEx.assert_called_once()

    @unittest.skipUnless(hasattr(__import__("helestron.servidor.aplicacao", fromlist=["Aplicacao"])
                                 .Aplicacao, "registrar_atencao"),
                         "o servidor ainda não tem registrar_atencao (contrato C3)")
    def test_pergunta_de_verdade_chama_a_janela(self):
        from helestron.tarefas import Pergunta

        chamado = threading.Event()

        def roteiro(j):
            self.app.perguntas.abrir(Pergunta("Código de verificação do e-SAJ", "Veja o e-mail.",
                                              60, tipo="codigo"))
            resultados["chamou"] = chamado.wait(10)

        resultados = {}
        modulo = webview_falso(roteiro)
        jw = janela.JanelaWebview(self.app)
        self.app.janela = jw
        with mock.patch.dict(sys.modules, {"webview": modulo}), \
                mock.patch.object(janela, "NO_WINDOWS", True), \
                mock.patch.object(jw, "_hwnd", return_value=99), \
                mock.patch.object(janela, "chamar_atencao_hwnd",
                                  side_effect=lambda h: chamado.set()):
            jw.abrir(self.app.url)
        self.assertTrue(resultados["chamou"])

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
            self.app.iniciado_em = time.monotonic() - 20       # a página deu sinal
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

    def test_edge_que_fecha_sem_carregar_tenta_a_proxima(self):
        processo = mock.Mock()
        processo.poll.return_value = 0
        with mock.patch.object(janela.subprocess, "Popen", return_value=processo):
            self.app.hub.ultimo_contato = self.app.iniciado_em - 10   # nunca falou
            ok = janela.JanelaEdge(self.app, executavel=janela.Path("/opt/msedge")).abrir(
                self.app.url)
        self.assertFalse(ok)

    def test_navegador_que_nao_carrega_explica_em_vez_de_sumir(self):
        """O navegador padrão abriu, mas não roda a interface (o Internet
        Explorer): antes, o programa saía calado com código 0 em 2 min."""
        with mock.patch.object(janela.webbrowser, "open", return_value=True), \
                mock.patch.object(janela, "SEM_SINAL_S", 0.1), \
                mock.patch.object(janela, "PRIMEIRO_SINAL_S", 0.5), \
                self.assertLogs("aplicativo.janela", "WARNING") as registro:
            self.app.hub.ultimo_contato = self.app.iniciado_em - 1
            self.assertFalse(janela.JanelaNavegador(self.app).abrir(self.app.url))
        self.assertIn("não deu nenhum sinal", "\n".join(registro.output))

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
