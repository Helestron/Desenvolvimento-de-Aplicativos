"""Instância única: trava, instancia.json, /api/ping, mostrar e --encerrar."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from helestron.aplicativo import inicio, instancia

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

    def test_fechando_nao_aparece(self):
        self.app.fechando = True
        status, env = self.cliente.post("/api/janela/mostrar")
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "encerrando")


if __name__ == "__main__":
    unittest.main()
