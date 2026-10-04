"""A interface de verdade (helestron/web) contra o servidor de verdade, no Chromium.

É o --autoteste sem a janela nativa: a página abre com o token e
?autoteste=1, percorre as seções e conversa só com a API real (token no
cabeçalho, eventos SSE, CSP do servidor). Pulado sem o Playwright ou sem a
interface na árvore.
"""

from __future__ import annotations

import glob
import json
import os
import re
import time
import unittest
from pathlib import Path
from unittest import mock

from helestron.aplicativo import autoteste as modulo_autoteste
from helestron.aplicativo.autoteste import Autoteste

from testes.test_servidor_base import ServidorDeTeste

WEB = Path(__file__).resolve().parents[1] / "helestron" / "web"


def _chromium(pw):
    try:
        return pw.chromium.launch()
    except Exception as erro:
        if "Executable doesn't exist" not in str(erro):
            raise
    bases = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "", "/opt/pw-browsers",
             str(Path.home() / ".cache" / "ms-playwright")]
    for base in bases:
        achados = sorted(glob.glob(os.path.join(base, "chromium-*", "chrome-linux", "chrome")))
        if base and achados:
            return pw.chromium.launch(executable_path=achados[-1])
    raise unittest.SkipTest("Chromium do Playwright não instalado")


@unittest.skipUnless((WEB / "index.html").is_file(), "interface (helestron/web) ausente")
class TestInterfaceRealNoServidor(ServidorDeTeste):
    pasta_web = WEB

    def setUp(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright não instalado")
        super().setUp()
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.navegador = _chromium(self.pw)
        self.addCleanup(self.navegador.close)

    def test_autoteste_percorre_todas_as_secoes(self):
        pasta = self.amb.raiz / "autoteste"
        self.app.autoteste = Autoteste(self.app, pasta, capturar=False)
        console, erros_js, respostas = [], [], []
        pagina = self.navegador.new_page(viewport={"width": 1280, "height": 820})
        pagina.on("console", lambda m: console.append(m.text))
        pagina.on("pageerror", lambda e: erros_js.append(str(e)))
        pagina.on("response", lambda r: respostas.append((r.status, r.url)))
        with mock.patch.object(modulo_autoteste, "ASSENTAR_S", 0):
            pagina.goto(self.app.url + "&autoteste=1")
            limite = time.monotonic() + 120
            while not self.app.autoteste.terminou.is_set() and time.monotonic() < limite:
                pagina.wait_for_timeout(200)
        url_final = pagina.url
        pagina.close()
        self.assertTrue(self.app.autoteste.terminou.is_set(), "a interface não terminou o percurso")
        dados = json.loads((pasta / "autoteste.json").read_text(encoding="utf-8"))
        self.assertEqual(dados["resultado"], "ok", dados)
        self.assertGreaterEqual(len(dados["passos"]), 7)
        self.assertEqual(erros_js, [])
        self.assertFalse([t for t in console if "Content Security Policy" in t], console)
        # o token saiu da barra de endereço; nenhum pedido à API foi recusado
        self.assertNotIn(self.app.token, url_final)
        self.assertFalse([u for s, u in respostas if s == 403])
        self.assertFalse([u for s, u in respostas if s >= 500 and "/api/pauta" not in u])


class TestContratoDasRotas(unittest.TestCase):
    """Toda rota da especificação (6.3) e do cliente da interface existe no servidor."""

    @staticmethod
    def rotas_do_servidor() -> set[tuple[str, str]]:
        from helestron.servidor import rotas

        return {(r.metodo, r.modelo) for r in rotas.montar().rotas}

    @staticmethod
    def _normalizar(modelo: str) -> str:
        return re.sub(r"\{\w+\}", "{}", modelo.split("?")[0])

    def test_especificacao(self):
        texto = (WEB.parents[1] / "docs" / "ESPECIFICACAO.md").read_text(encoding="utf-8")
        trecho = texto.split("### 6.3", 1)[1].split("### 6.5", 1)[0]
        esperadas = set()
        for linha in trecho.splitlines():
            for metodo, caminho in re.findall(r"`(GET|POST|DELETE) (/api/[^`\s]*)", linha):
                esperadas.add((metodo, caminho))
                # "/api/transcricao/pausar` · `/retomar`": as irmãs herdam o prefixo
                base = caminho.rsplit("/", 1)[0]
                for irma in re.findall(r"· `(/[\w-]+)`", linha):
                    esperadas.add((metodo, base + irma))
        servidor = {(m, self._normalizar(c)) for m, c in self.rotas_do_servidor()}
        faltam = sorted((m, c) for m, c in esperadas if (m, self._normalizar(c)) not in servidor)
        self.assertGreater(len(esperadas), 60)
        self.assertEqual(faltam, [])

    @unittest.skipUnless((WEB / "js" / "api.js").is_file(), "interface ausente")
    def test_cliente_da_interface(self):
        texto = (WEB / "js" / "api.js").read_text(encoding="utf-8")
        usadas = set(re.findall(r'"(GET|POST|DELETE) (/api/[^"]+)"', texto))
        servidor = {(m, self._normalizar(c)) for m, c in self.rotas_do_servidor()}
        faltam = sorted((m, c) for m, c in usadas if (m, self._normalizar(c)) not in servidor)
        self.assertTrue(usadas)
        self.assertEqual(faltam, [])


if __name__ == "__main__":
    unittest.main()
