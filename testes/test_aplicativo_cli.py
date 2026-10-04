"""Linha de comando (python -m helestron): --servidor, --encerrar, pauta e o resto."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import types
import unittest
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from helestron import __main__ as principal

from testes.test_servidor_base import AmbienteTemporario

RAIZ = Path(__file__).resolve().parents[1]

# O processo-filho põe os caminhos do programa na pasta temporária antes de
# tudo (vale com e sem HELESTRON_LOCAL implementado em helestron.nucleo.caminhos).
INICIO_ISOLADO = r"""
import os, sys
from pathlib import Path
from helestron.nucleo import caminhos
local, dados = Path(os.environ["HELESTRON_LOCAL"]), Path(os.environ["HELESTRON_DADOS"])
valores = {"LOCAL": local, "LOGS": local / "Logs", "TEMP": local / "temp",
           "PERFIS": local / "perfis", "ARQUIVO_CONFIG": local / "config.ini",
           "ARQUIVO_SENHAS": local / "credenciais.json", "ARQUIVO_PAUTA": local / "pauta.sqlite3",
           "ARQUIVO_INSTANCIA": local / "instancia.json", "BASE_USUARIO": dados}
for nome, valor in valores.items():
    setattr(caminhos, nome, valor)
from helestron.__main__ import main
sys.exit(main(sys.argv[1:]))
"""


class TestServidorPelaLinhaDeComando(unittest.TestCase):
    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)

    def test_servidor_imprime_url_e_encerra_pela_api(self):
        env = dict(os.environ)
        env.update({"HELESTRON_LOCAL": str(self.amb.local), "HELESTRON_DADOS": str(self.amb.dados),
                    "HOME": str(self.amb.raiz), "USERPROFILE": str(self.amb.raiz),
                    "PYTHONPATH": str(RAIZ), "PYTHONIOENCODING": "utf-8"})
        env.pop("LOCALAPPDATA", None)
        processo = subprocess.Popen(
            [sys.executable, "-c", INICIO_ISOLADO, "--servidor", "--sem-janela",
             "--token", "token-de-teste"],
            # fora do repositório: nada que o programa grave pode cair na raiz dele
            cwd=str(self.amb.raiz), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        self.addCleanup(lambda: processo.poll() is None and processo.kill())
        linha = processo.stdout.readline().strip()
        self.assertTrue(linha.startswith("URL=http://127.0.0.1:"), linha)
        url = linha[4:]
        self.assertTrue(url.endswith("/?t=token-de-teste"))
        base = url.split("?")[0]
        abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        pedido = urllib.request.Request(base + "api/ping",
                                        headers={"X-Helestron-Token": "token-de-teste"})
        with abridor.open(pedido, timeout=10) as resposta:
            ping = json.loads(resposta.read())
        self.assertEqual(ping["dados"]["modo"], "servidor")
        pedido = urllib.request.Request(base + "api/encerrar", data=b"{}", method="POST",
                                        headers={"X-Helestron-Token": "token-de-teste",
                                                 "Content-Type": "application/json"})
        with abridor.open(pedido, timeout=10) as resposta:
            self.assertEqual(resposta.status, 200)
        self.assertEqual(processo.wait(30), 0, processo.stderr.read())
        processo.stdout.close()
        processo.stderr.close()
        # nada fora da pasta temporária
        self.assertTrue((self.amb.local / "config.ini").exists())


class TestProgramaEntreProcessos(unittest.TestCase):
    """O programa aberto (sem janela), a segunda abertura e o --encerrar do instalador."""

    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.env = dict(os.environ)
        self.env.update({"HELESTRON_LOCAL": str(self.amb.local),
                         "HELESTRON_DADOS": str(self.amb.dados), "HOME": str(self.amb.raiz),
                         "USERPROFILE": str(self.amb.raiz), "PYTHONPATH": str(RAIZ),
                         "PYTHONIOENCODING": "utf-8", "HELESTRON_JANELA": "nenhuma"})
        self.env.pop("LOCALAPPDATA", None)

    def rodar(self, *args, esperar: bool = True):
        processo = subprocess.Popen([sys.executable, "-c", INICIO_ISOLADO, *args],
                                    cwd=str(self.amb.raiz),
                                    env=self.env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: processo.poll() is None and processo.kill())
        if esperar:
            processo.wait(60)
        return processo

    def test_abrir_segunda_abertura_e_encerrar(self):
        import time

        aberto = self.rodar(esperar=False)
        registro = self.amb.local / "instancia.json"
        limite = time.monotonic() + 30
        while not registro.exists() and time.monotonic() < limite:
            time.sleep(0.1)
        self.assertTrue(registro.exists(), aberto.stderr.read() if aberto.poll() is not None else "")
        dados = json.loads(registro.read_text(encoding="utf-8"))
        self.assertEqual(dados["pid"], aberto.pid)
        segunda = self.rodar()
        self.assertEqual(segunda.returncode, 0)          # pediu à primeira que aparecesse e saiu
        self.assertIsNone(aberto.poll())                 # a primeira continua aberta
        encerrar = self.rodar("--encerrar")
        self.assertEqual(encerrar.returncode, 0, encerrar.stderr.read())
        self.assertEqual(aberto.wait(30), 0)
        self.assertFalse(registro.exists())               # o registro sai junto
        for p in (aberto, segunda, encerrar):
            p.stderr.close()


class TestComandos(unittest.TestCase):
    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)

    def rodar(self, *args) -> tuple[int, str]:
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = principal.main(list(args))
        return codigo, saida.getvalue()

    def test_ajuda_e_desconhecido(self):
        codigo, saida = self.rodar("--ajuda")
        self.assertEqual(codigo, 0)
        self.assertIn("--verificar-instalacao", saida)
        self.assertIn("--servidor", saida)
        self.assertEqual(self.rodar("nada")[0], 2)
        self.assertEqual(self.rodar("--autoteste")[0], 2)

    def test_encerrar_sem_programa_aberto(self):
        self.assertEqual(self.rodar("--encerrar")[0], 0)

    def test_pauta_vai_para_o_cli_da_pauta(self):
        cli = types.ModuleType("helestron.pauta.cli")
        cli.main = mock.Mock(return_value=0)
        pacote = types.ModuleType("helestron.pauta")
        pacote.__path__ = []
        pacote.cli = cli
        with mock.patch.dict(sys.modules, {"helestron.pauta": pacote, "helestron.pauta.cli": cli}):
            self.assertEqual(self.rodar("pauta", "exportar", "--de", "2026-10-01")[0], 0)
        cli.main.assert_called_once_with(["exportar", "--de", "2026-10-01"])

    def test_sem_argumentos_abre_o_programa(self):
        with mock.patch.object(principal, "abrir_programa", return_value=0) as abrir:
            self.assertEqual(principal.main([]), 0)
        abrir.assert_called_once_with()
        with mock.patch.object(principal, "abrir_programa", return_value=1) as abrir:
            self.assertEqual(principal.main(["--autoteste", str(self.amb.raiz / "cap")]), 1)
        abrir.assert_called_once_with(self.amb.raiz / "cap")

    def test_opcao(self):
        self.assertEqual(principal._opcao(["--porta", "8080"], "--porta"), "8080")
        self.assertEqual(principal._opcao(["--porta=81"], "--porta"), "81")
        self.assertIsNone(principal._opcao([], "--porta"))
        with self.assertRaises(SystemExit):
            principal._opcao(["--porta"], "--porta")

    def test_sem_interface_tkinter(self):
        fonte = (RAIZ / "helestron" / "__main__.py").read_text(encoding="utf-8")
        self.assertNotIn("interface", fonte.replace("interface (", "").split('"""', 2)[2])
        self.assertNotIn("importlib", fonte)


if __name__ == "__main__":
    unittest.main()
