"""Instância única: trava, instancia.json, /api/ping, mostrar e --encerrar (que não
corta uma audiência), e a tela de erro que também atende o --encerrar."""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
from unittest import mock

from helestron.aplicativo import erro, inicio, instancia, integridade

from testes.test_servidor_base import AmbienteTemporario, ServidorDeTeste


class TestTravaERegistro(unittest.TestCase):
    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)

    def test_trava_exclusiva(self):
        primeira = instancia.Trava()
        self.assertTrue(primeira.tomar())
        self.addCleanup(primeira.soltar)
        segunda = instancia.Trava()
        self.assertFalse(segunda.tomar())
        self.assertTrue(instancia.outra_aberta())
        primeira.soltar()
        self.assertFalse(instancia.outra_aberta())
        self.assertTrue(segunda.tomar())
        segunda.soltar()
        self.assertEqual(primeira.arquivo, self.amb.local / "instancia.trava")

    def test_registro(self):
        arquivo = instancia.gravar_registro(4321, "tok")
        self.assertEqual(arquivo, self.amb.local / "instancia.json")
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        self.assertEqual(dados, {"pid": os.getpid(), "porta": 4321, "token": "tok"})
        self.assertEqual(instancia.ler_registro()["porta"], 4321)
        instancia.apagar_registro(pid=os.getpid() + 1)      # de outro processo: fica
        self.assertTrue(arquivo.exists())
        instancia.apagar_registro(pid=os.getpid())
        self.assertFalse(arquivo.exists())
        arquivo.write_text("{lixo", encoding="utf-8")
        self.assertIsNone(instancia.ler_registro())

    def test_ninguem_aberto(self):
        self.assertIsNone(instancia.responde(None))
        self.assertIsNone(instancia.responde({"porta": 1, "token": "x"}))
        self.assertEqual(instancia.encerrar_aberta(espera_s=1), 0)
        self.assertEqual(instancia.chamar_a_aberta(espera_s=1), "fechou")


class TestSegundaAbertura(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        self.trava = instancia.Trava()
        self.assertTrue(self.trava.tomar())
        self.addCleanup(self.trava.soltar)
        instancia.gravar_registro(self.app.porta, self.app.token)
        self.janela = mock.Mock()
        self.janela.mostrar.return_value = True
        self.app.janela = self.janela

    def test_pede_que_a_aberta_apareca(self):
        self.assertEqual(instancia.responde(instancia.ler_registro())["nome"], "Helestron")
        self.assertEqual(instancia.chamar_a_aberta(espera_s=5), "mostrou")
        self.janela.mostrar.assert_called_once()

    def test_main_sai_com_zero_quando_ja_ha_uma_aberta(self):
        with mock.patch.object(inicio, "_abrir") as abrir, \
                mock.patch("helestron.nucleo.registro.configurar"):
            self.assertEqual(inicio.main(), 0)
        abrir.assert_not_called()
        self.janela.mostrar.assert_called()

    def test_proxy_do_sistema_nao_atrapalha(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://10.255.255.1:3128",
                                          "http_proxy": "http://10.255.255.1:3128",
                                          "NO_PROXY": "", "no_proxy": ""}):
            self.assertIsNotNone(instancia.responde(instancia.ler_registro()))

    def test_encerrar_a_aberta(self):
        self.app.ao_encerrar.append(self.trava.soltar)       # o processo "sai"
        self.assertEqual(instancia.encerrar_aberta(espera_s=20), 0)
        self.assertTrue(self.app.esperar(10))

    def test_encerrar_nao_corta_a_audiencia(self):
        """Com uma audiência sendo transcrita, o --encerrar (atualização
        silenciosa empurrada pela TI) recusa com o código 10 e não fecha nada."""
        self.app.ao_encerrar.append(self.trava.soltar)
        for estado in ("gravando", "pausada", "iniciando"):
            with self.subTest(estado=estado), mock.patch.object(self.app.audiencia, "estado", estado), \
                    self.assertLogs("aplicativo.instancia", "WARNING"):
                self.assertEqual(instancia.encerrar_aberta(espera_s=2),
                                 instancia.AUDIENCIA_EM_ANDAMENTO)
            self.assertFalse(self.app.fechando)
        # encerrada (o documento sendo finalizado): pode fechar
        with mock.patch.object(self.app.audiencia, "estado", "encerrando"):
            self.assertEqual(instancia.encerrar_aberta(espera_s=20), 0)
        self.assertTrue(self.app.esperar(10))

    def test_encerrar_espera_quem_esta_salvando(self):
        """A instância responde "fechando" (a fila da audiência sendo
        transcrita): o --encerrar continua esperando, em vez de desistir com
        ela no meio e o instalador abortar com o código 4."""
        def salvar_devagar():
            time.sleep(2.5)                   # o servidor ainda responde: fechando
            self.trava.soltar()

        self.app.ao_encerrar.append(salvar_devagar)
        inicio_ = time.monotonic()
        self.assertEqual(instancia.encerrar_aberta(espera_s=1, espera_fechando_s=30), 0)
        self.assertGreater(time.monotonic() - inicio_, 2)
        self.assertTrue(self.app.esperar(10))

    def test_fechando_nao_aparece(self):
        self.app.fechando = True
        status, env = self.cliente.post("/api/janela/mostrar")
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "encerrando")


class TestTelaDeErroAtendeOInstalador(unittest.TestCase):
    """A tela de "instalação incompleta" grava o instancia.json: o --encerrar
    do instalador a fecha, e a segunda abertura fala com ela (antes: 60 s de
    espera e código 1; "não respondeu... reinicie o computador")."""

    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)

    def test_encerrar_e_segunda_abertura(self):
        problemas = [integridade.Problema("Lib/site-packages/helestron/servidor/rede.py", "ausente")]
        saida = {}

        def abrir():
            saida["codigo"] = inicio.main()

        with mock.patch.object(integridade, "conferir_rapido", return_value=problemas), \
                mock.patch("helestron.nucleo.registro.configurar"), \
                mock.patch.dict(os.environ, {"HELESTRON_JANELA": "nenhuma"}), \
                self.assertLogs("aplicativo.erro", "ERROR"):
            fio = threading.Thread(target=abrir, daemon=True)
            fio.start()
            limite = time.monotonic() + 15
            while instancia.ler_registro() is None and time.monotonic() < limite:
                time.sleep(0.05)
            self.assertIsNotNone(instancia.ler_registro(), "a tela de erro não gravou o registro")
            self.assertEqual(instancia.responde(instancia.ler_registro())["modo"], "erro")
            self.assertEqual(instancia.chamar_a_aberta(espera_s=5), "mostrou")
            inicio_ = time.monotonic()
            self.assertEqual(instancia.encerrar_aberta(espera_s=20), 0)
            self.assertLess(time.monotonic() - inicio_, 15)
            fio.join(10)
        self.assertFalse(fio.is_alive())
        self.assertEqual(saida["codigo"], 1)
        self.assertIsNone(instancia.ler_registro())         # apagado na saída
        self.assertFalse(instancia.outra_aberta())

    def test_mostrar_sem_registrar(self):
        """No --autoteste não há trava: a tela não grava o registro."""
        problemas = [integridade.Problema("Lib/os.py", "ausente")]
        app = mock.Mock()
        app.porta, app.token, app.fechando = 1234, "t", False
        with mock.patch.object(erro, "AplicacaoErro") as classe, \
                mock.patch("helestron.aplicativo.janela.abrir", return_value="nenhuma"), \
                mock.patch.object(instancia, "gravar_registro") as gravar, \
                self.assertLogs("aplicativo.erro", "ERROR"):
            classe.return_value.iniciar.return_value = app
            self.assertEqual(erro.mostrar(problemas, registrar=False), 1)
            gravar.assert_not_called()
            self.assertEqual(erro.mostrar(problemas), 1)
            gravar.assert_called_once_with(1234, "t")


class TestAbertura(unittest.TestCase):
    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)

    def test_sem_appusermodelid_explicito(self):
        """O ID explícito "Helestron.App" não estava nos atalhos do instalador:
        o Helestron fixado na barra de tarefas abria como um segundo botão.
        Vale o ID implícito do Helestron.exe, o mesmo dos atalhos: nenhuma
        parte do programa define outro (e a função que o fazia saiu)."""
        from pathlib import Path

        from helestron.nucleo import sistema

        self.assertFalse(hasattr(sistema, "id_do_aplicativo"))
        pacote = Path(inicio.__file__).resolve().parents[1]
        for arquivo in sorted(pacote.rglob("*.py")):
            with self.subTest(arquivo=arquivo.name):
                self.assertNotIn("ExplicitAppUserModelID", arquivo.read_text(encoding="utf-8"))
        with mock.patch("helestron.nucleo.registro.configurar"), \
                mock.patch.object(inicio, "_abrir", return_value=0):
            self.assertEqual(inicio.main(), 0)

    def test_sem_janela_explica_e_espera_o_encerramento_inteiro(self):
        from helestron.aplicativo import janela
        from helestron.servidor import aplicacao

        with mock.patch.object(integridade, "conferir_rapido", return_value=[]), \
                mock.patch.object(janela, "abrir", return_value=""), \
                mock.patch.object(janela, "motivo_sem_janela", return_value="instale o WebView2"), \
                mock.patch.object(inicio, "mensagem_nativa") as mensagem, \
                mock.patch.object(aplicacao.Aplicacao, "esperar", return_value=True) as esperar:
            self.assertEqual(inicio._abrir(None), 1)
        mensagem.assert_called_once_with("O Helestron não pôde abrir", "instale o WebView2")
        # o processo não sai antes de a audiência terminar de ser salva
        self.assertGreaterEqual(esperar.call_args[0][0],
                                aplicacao.ESPERA_AUDIENCIA_S + aplicacao.ESPERA_TAREFAS_S)

    def test_limpar_antigos(self):
        """O que o instalador renomeou (presos pelo servidor MCP) some depois."""
        pasta = self.amb.raiz / "Helestron" / inicio.PASTA_ANTIGOS
        for rel in ("123/1-python312.dll", "123/2-_socket.pyd", "456/python312.dll"):
            (pasta / rel).parent.mkdir(parents=True, exist_ok=True)
            (pasta / rel).write_bytes(b"MZ")
        self.assertEqual(inicio.limpar_antigos(pasta), 3)
        self.assertFalse(pasta.exists())
        self.assertEqual(inicio.limpar_antigos(pasta), 0)
        with mock.patch.object(integridade, "pasta_instalada", return_value=None):
            self.assertEqual(inicio.limpar_antigos(), 0)          # fora da instalação


if __name__ == "__main__":
    unittest.main()
