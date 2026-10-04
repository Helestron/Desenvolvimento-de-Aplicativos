"""--autoteste: o percurso da interface, as capturas e o autoteste.json."""

from __future__ import annotations

import json
import logging
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from helestron.aplicativo import autoteste as modulo
from helestron.aplicativo import inicio, janela
from helestron.aplicativo.autoteste import Autoteste
from helestron.nucleo import caminhos

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

    def test_sem_retangulo_da_janela_nao_captura_a_tela_inteira(self):
        # A interface numa aba do navegador padrão: a janela não sabe onde
        # está. A captura da tela inteira levaria o que estivesse aberto em
        # outros programas; o passo fica registrado, sem imagem, e o
        # autoteste (que no Windows promete as capturas) não passa.
        grab = mock.Mock()
        pil = mock.Mock(ImageGrab=mock.Mock(grab=grab))
        self.app.janela = mock.Mock()
        self.app.janela.retangulo.return_value = None
        self.app.autoteste = Autoteste(self.app, self.pasta, capturar=True)
        with mock.patch.dict("sys.modules", {"PIL": pil, "PIL.ImageGrab": pil.ImageGrab}), \
                self.assertLogs("aplicativo.autoteste", "WARNING"):
            dados = self.cliente.dados("POST", "/api/autoteste/passo", {"secao": "pauta"})
            self.app.janela.retangulo.return_value = (0, 0, 4, 3)        # minimizada
            self.cliente.dados("POST", "/api/autoteste/passo", {"secao": "inicio"})
        self.assertEqual(dados, {"captura": None})
        grab.assert_not_called()
        self.assertEqual(list(self.pasta.glob("*.png")), [])
        registro = json.loads((self.pasta / "autoteste.json").read_text(encoding="utf-8"))
        self.assertEqual([p["erro_captura"] for p in registro["passos"]], [modulo.SEM_RETANGULO] * 2)
        self.assertEqual(self.cliente.dados("POST", "/api/autoteste/fim", {"ok": True})["resultado"], "falha")

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
            # As pastas que o programa usa durante o percurso (as capturas
            # saem do computador: nada dos dados de verdade pode aparecer).
            visto["caminhos"] = {nome: Path(getattr(caminhos, nome)) for nome in (
                "LOCAL", "LOGS", "TEMP", "PERFIS", "ARQUIVO_CONFIG", "ARQUIVO_SENHAS",
                "ARQUIVO_PAUTA", "ARQUIVO_INSTANCIA", "BASE_USUARIO")}
            visto["ambiente"] = {v: os.environ.get(v) for v in ("HELESTRON_LOCAL", "HELESTRON_DADOS")}
            visto["config"] = Path(app.cfg.arquivo)
            visto["acervo"] = Path(app.cfg.pasta_acervo)
            visto["pastas"] = cliente.dados("GET", "/api/estado")["pastas"]
            visto["monitor"] = app.monitor

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
        # Pastas de dados novas e vazias, numa pasta temporária só da rodada,
        # que não sobra; a configuração, a pauta e o acervo de verdade (os do
        # ambiente do teste) ficam de fora.
        temporaria = visto["caminhos"]["LOCAL"].parent
        self.assertTrue(temporaria.name.startswith("helestron-autoteste-"), temporaria)
        for nome, caminho in visto["caminhos"].items():
            with self.subTest(constante=nome):
                self.assertTrue(caminho.is_relative_to(temporaria), caminho)
        self.assertEqual(visto["ambiente"], {"HELESTRON_LOCAL": str(temporaria / "local"),
                                             "HELESTRON_DADOS": str(temporaria / "documentos")})
        self.assertTrue(visto["config"].is_relative_to(temporaria))
        self.assertTrue(visto["acervo"].is_relative_to(temporaria))
        self.assertNotEqual(visto["acervo"], self.amb.dados / "Acervo")
        for nome, pasta in visto["pastas"].items():
            if pasta:
                with self.subTest(pasta=nome):
                    self.assertFalse(Path(pasta).is_relative_to(self.amb.raiz), pasta)
        # Sem o monitor da pauta: nada de entrar nos portais durante o percurso.
        self.assertIsNone(visto["monitor"])
        self.assertFalse(temporaria.exists())
        # No fim, tudo volta a ser como antes.
        self.assertEqual(caminhos.LOCAL, self.amb.local)
        self.assertEqual(caminhos.BASE_USUARIO, self.amb.dados)
        self.assertEqual(os.environ["HELESTRON_LOCAL"], str(self.amb.local))
        self.assertEqual(os.environ["HELESTRON_DADOS"], str(self.amb.dados))

    def test_registro_da_rodada_vai_com_as_capturas(self):
        # O registro da rodada (das pastas vazias) acompanha as capturas, para
        # o diagnóstico do CI; o arquivo é solto antes de apagar a pasta.
        raiz = logging.getLogger()
        nivel, manipuladores = raiz.level, list(raiz.handlers)
        self.addCleanup(raiz.setLevel, nivel)

        def abrir(app, url):
            app.modo = "janela"
            logging.getLogger("aplicativo.teste").info("percurso do autoteste")
            app.autoteste.fim({})
            app.encerrar_em_segundo_plano()
            app.encerrado.wait(30)
            return "janela"

        with mock.patch.object(janela, "abrir", side_effect=abrir), \
                mock.patch.object(modulo, "NO_WINDOWS", False):
            codigo = inicio.main(autoteste=self.pasta)
        self.assertEqual(codigo, 1)                       # nenhum passo: não passa
        registros = list((self.pasta / "Logs").glob("*.log"))
        self.assertEqual(len(registros), 1)
        self.assertIn("percurso do autoteste", registros[0].read_text(encoding="utf-8"))
        self.assertEqual([h for h in raiz.handlers if h not in manipuladores], [])


if __name__ == "__main__":
    unittest.main()
