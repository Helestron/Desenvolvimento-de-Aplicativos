"""O registro não leva segredos de URL (sessão, hash do eProc, ticket do CAS)."""

from __future__ import annotations

import logging
import unittest

from helestron.nucleo import registro


class TestCensura(unittest.TestCase):
    def test_segredos_de_url(self):
        casos = {
            "https://esaj.tjal.jus.br/cpopg/open.do;jsessionid=ABC123?x=1":
                "https://esaj.tjal.jus.br/cpopg/open.do;jsessionid=***?x=1",
            "controlador.php?acao=processo&hash=9f8e7d6c&num=1":
                "controlador.php?acao=processo&hash=***&num=1",
            "sajcas/login?service=x&ticket=ST-12-abc": "sajcas/login?service=x&ticket=***",
            "https://sso.tjsc.jus.br/cb#state=s1&session_state=s2&code=c3":
                "https://sso.tjsc.jus.br/cb#state=***&session_state=***&code=***",
            "proxy http://joao:segredo@10.0.0.1:3128": "proxy http://***:***@10.0.0.1:3128",
        }
        for entrada, esperado in casos.items():
            self.assertEqual(registro.censurar(entrada), esperado)

    def test_texto_comum_fica(self):
        for texto in ("Baixando 0700123-45.2024.8.02.0001 (3 de 10)",
                      "o portal mostrou um aviso: Sessão expirada"):
            self.assertEqual(registro.censurar(texto), texto)

    def test_filtro_no_registro(self):
        registros = []

        class Guarda(logging.Handler):
            def emit(self, record):
                registros.append(self.format(record))

        h = Guarda()
        h.addFilter(registro.FiltroSegredos())
        log = logging.getLogger("teste.censura")
        log.addHandler(h)
        log.propagate = False
        try:
            log.warning("não consegui abrir %s", "https://x.jus.br/a;jsessionid=XYZ")
            try:
                raise RuntimeError("Page.goto: net::ERR at https://x.jus.br/?hash=SEGREDO")
            except RuntimeError:
                log.exception("falhou")
        finally:
            log.removeHandler(h)
        self.assertNotIn("XYZ", "\n".join(registros))
        self.assertNotIn("SEGREDO", "\n".join(registros))


if __name__ == "__main__":
    unittest.main()


class TestCofrePrivado(unittest.TestCase):
    def test_finalidades_separadas_e_arquivo_so_do_dono(self):
        import os
        import tempfile
        from pathlib import Path

        from helestron.nucleo import cofre_senhas
        texto = cofre_senhas.cifrar(b"cookie", "sessao/v1")
        self.assertEqual(cofre_senhas.decifrar(texto, "sessao/v1"), b"cookie")
        with tempfile.TemporaryDirectory() as d:
            alvo = Path(d) / "sub" / "credenciais.json"
            cofre_senhas.CofreSenhas(alvo).guardar("esaj:TJAL", "u", "s")
            if os.name == "posix":
                self.assertEqual(os.stat(alvo).st_mode & 0o777, 0o600)
            self.assertEqual(sorted(p.name for p in alvo.parent.iterdir()), ["credenciais.json"])


class TestErroDoNavegador(unittest.TestCase):
    def test_mensagem_de_erro_sem_segredo_de_url(self):
        from helestron.download import navegador
        texto = navegador.explicar_erro(
            "Page.goto: net::ERR_ABORTED at https://eproc1g.tjrs.jus.br/eproc/"
            "controlador.php?acao=processo_selecionar&hash=a1b2c3\nCall log: ...")
        self.assertNotIn("a1b2c3", texto)
        self.assertIn("hash=***", texto)
