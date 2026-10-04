"""--autoteste: o percurso da interface, as capturas e o autoteste.json."""

from __future__ import annotations

import json
import threading
import unittest
from unittest import mock

from helestron.aplicativo import autoteste as modulo
from helestron.aplicativo import inicio, janela
from helestron.aplicativo.autoteste import Autoteste

from testes.test_servidor_base import AmbienteTemporario, Cliente, ServidorDeTeste

SECOES = ("inicio", "processos", "audiencias", "pauta", "compartilhar", "ajustes", "ajuda")


class TestAutotestePelaApi(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        self.pasta = self.amb.raiz / "capturas"
        modulo_assentar = mock.patch.object(modulo, "ASSENTAR_S", 0)
        modulo_assentar.start()
        self.addCleanup(modulo_assentar.stop)

    def test_percurso_sem_capturas_fora_do_windows(self):
        self.app.autoteste = Autoteste(self.app, self.pasta, capturar=False)
        for secao in SECOES:
            self.assertEqual(self.cliente.dados("POST", "/api/autoteste/passo", {"secao": secao}),
                             {"captura": None})
        resultado = self.cliente.dados("POST", "/api/autoteste/fim", {"ok": True})
        self.assertEqual(resultado, {"resultado": "ok", "passos": 7})
        dados = json.loads((self.pasta / "autoteste.json").read_text(encoding="utf-8"))
        self.assertEqual([p["secao"] for p in dados["passos"]], list(SECOES))
        self.assertEqual(dados["resultado"], "ok")
        self.assertEqual(self.app.autoteste.codigo, 0)
        self.assertTrue(self.app.esperar(10))             # o programa fecha sozinho

    def test_capturas_pelo_retangulo_da_janela(self):
        imagem = mock.Mock()
        grab = mock.Mock(return_value=imagem)
        pil = mock.Mock(ImageGrab=mock.Mock(grab=grab))
        self.app.janela = mock.Mock()
        self.app.janela.retangulo.return_value = (10, 20, 1280, 820)
        self.app.autoteste = Autoteste(self.app, self.pasta, capturar=True)
        with mock.patch.dict("sys.modules", {"PIL": pil, "PIL.ImageGrab": pil.ImageGrab}):
            dados = self.cliente.dados("POST", "/api/autoteste/passo", {"secao": "pauta"})
        self.assertEqual(dados, {"captura": "captura-pauta.png"})
        self.assertEqual(grab.call_args.kwargs["bbox"], (10, 20, 1290, 840))
        imagem.save.assert_called_once_with(self.pasta / "captura-pauta.png")

    def test_erro_da_pagina_reprova(self):
        self.app.autoteste = Autoteste(self.app, self.pasta, capturar=False)
        self.cliente.dados("POST", "/api/autoteste/passo", {"secao": "inicio"})
        resultado = self.cliente.dados("POST", "/api/autoteste/fim",
                                       {"erros": ["pauta: TypeError: x is undefined"]})
        self.assertEqual(resultado["resultado"], "falha")
        self.assertEqual(self.app.autoteste.codigo, 1)

    def test_secao_invalida_e_sem_autoteste(self):
        status, _ = self.cliente.post("/api/autoteste/passo", {"secao": "inicio"})
        self.assertEqual(status, 404)
        self.app.autoteste = Autoteste(self.app, self.pasta, capturar=False)
        status, _ = self.cliente.post("/api/autoteste/passo", {"secao": "../x"})
        self.assertEqual(status, 400)

    def test_tempo_esgotado(self):
        teste = Autoteste(self.app, self.pasta, prazo_s=0.2, capturar=False)
        self.app.autoteste = teste
        with self.assertLogs("aplicativo.autoteste", "ERROR"):
            teste.vigiar()
            self.assertTrue(teste.terminou.wait(5))
        self.assertEqual(teste.codigo, 1)
        dados = json.loads((self.pasta / "autoteste.json").read_text(encoding="utf-8"))
        self.assertIn("tempo esgotado", dados["erros"][0])
        self.assertTrue(self.app.esperar(10))


class TestAutotesteDePontaAPonta(unittest.TestCase):
    """inicio.main(autoteste=...) inteiro, com uma 'janela' que faz o papel da página."""

    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.pasta = self.amb.raiz / "autoteste"

    def test_main_devolve_o_codigo_do_autoteste(self):
        visto = {}

        def abrir(app, url):
            visto["url"] = url
            app.modo = "janela"
            cliente = Cliente(app)

            def pagina():
                for secao in SECOES:
                    cliente.dados("POST", "/api/autoteste/passo", {"secao": secao})
                cliente.dados("POST", "/api/autoteste/fim", {})

            threading.Thread(target=pagina, daemon=True).start()
            app.encerrado.wait(30)
            return "janela"

        with mock.patch.object(janela, "abrir", side_effect=abrir), \
                mock.patch.object(modulo, "ASSENTAR_S", 0), \
                mock.patch.object(modulo, "NO_WINDOWS", False), \
                mock.patch("helestron.nucleo.registro.configurar"), \
                mock.patch("helestron.aplicativo.monitor.ATRASO_INICIAL_S", 3600):
            codigo = inicio.main(autoteste=self.pasta)
        self.assertEqual(codigo, 0)
        self.assertTrue(visto["url"].endswith("&autoteste=1"))
        self.assertIn("?t=", visto["url"])
        dados = json.loads((self.pasta / "autoteste.json").read_text(encoding="utf-8"))
        self.assertEqual(len(dados["passos"]), len(SECOES))
        # o autoteste não registra instância (não atrapalha um programa aberto)
        self.assertFalse((self.amb.local / "instancia.json").exists())


if __name__ == "__main__":
    unittest.main()
