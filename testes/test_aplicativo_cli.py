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
from contextlib import redirect_stderr, redirect_stdout
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
        codigo, saida, _ = self.rodar_com_erros(*args)
        return codigo, saida

    def rodar_com_erros(self, *args) -> tuple[int, str, str]:
        saida, erros = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erros):
            codigo = principal.main(list(args))
        return codigo, saida.getvalue(), erros.getvalue()

    def test_ajuda_e_desconhecido(self):
        codigo, saida = self.rodar("--ajuda")
        self.assertEqual(codigo, 0)
        self.assertIn("--verificar-instalacao", saida)
        self.assertIn("--servidor", saida)
        self.assertEqual(self.rodar("nada")[0], 2)
        self.assertEqual(self.rodar("--autoteste")[0], 2)

    def test_linha_de_comando_em_portugues(self):
        """A ajuda e os erros da linha de comando vinham à mão (e o argparse, nos
        subcomandos, em inglês): agora é o ArgumentParser do programa."""
        for pedido in ("-h", "--help", "--ajuda", "ajuda"):
            codigo, saida = self.rodar(pedido)
            self.assertEqual(codigo, 0, pedido)
            self.assertIn("uso: python -m helestron", saida)
            self.assertIn("mostra esta ajuda e sai", saida)
            self.assertIn("opções:", saida)
            self.assertIn("comandos (cada um tem a própria ajuda", saida)
            self.assertNotRegex(saida, r"\b(usage|options|show this help)\b")
        casos = {("nada",): "erro: comando desconhecido: nada",
                 ("--autoteste",): "erro: argumento --autoteste: falta o valor",
                 ("--porta", "x", "--servidor"): "erro: argumento --porta: valor inválido: 'x'",
                 ("--servidor", "--encerrar"): "não pode ser usado junto com o argumento --servidor",
                 ("--relatorio", "r.txt"): "erro: --relatorio só vale com --verificar-instalacao",
                 ("--token", "t"): "erro: --porta, --sem-janela e --token só valem com --servidor",
                 ("--xyz",): "erro: argumento não reconhecido: --xyz"}
        for args, trecho in casos.items():
            with self.subTest(args=args):
                codigo, saida, erros = self.rodar_com_erros(*args)
                self.assertEqual(codigo, 2)
                self.assertIn("uso: python -m helestron", erros)
                self.assertIn(trecho, erros)

    def test_parte_que_falta(self):
        # "cannot import name": erro.name dizia só o pacote (helestron.aplicativo)
        erro = ImportError("cannot import name 'instancia' from 'helestron.aplicativo' "
                           "(C:\\Helestron\\Lib\\site-packages\\helestron\\aplicativo\\__init__.py)",
                           name="helestron.aplicativo")
        self.assertEqual(principal.parte_que_falta(erro), "helestron.aplicativo.instancia")
        erro = ImportError("No module named 'helestron.nucleo.registro'", name="helestron.nucleo.registro")
        self.assertEqual(principal.parte_que_falta(erro), "helestron.nucleo.registro")
        self.assertEqual(principal.parte_que_falta(ImportError("outra coisa")), "outra coisa")

    def test_sem_o_registro_do_programa(self):
        """Sem o nucleo/registro.py (ou o caminhos.py), o main() quebrava no
        import, antes de qualquer mensagem: o atalho não fazia nada."""
        from helestron import nucleo

        relatorio = self.amb.raiz / "relatorio.txt"
        with mock.patch.dict(sys.modules, {"helestron.nucleo.registro": None}), \
                mock.patch.dict(nucleo.__dict__), \
                mock.patch.object(principal, "_mensagem") as mensagem:
            nucleo.__dict__.pop("registro", None)
            self.assertEqual(principal.main([]), 1)
            mensagem.assert_called_once()
            titulo, texto = mensagem.call_args.args
            self.assertEqual(titulo, "O Helestron não pôde abrir")
            self.assertIn("helestron.nucleo.registro", texto)
            self.assertIn("Helestron-Setup", texto)
            mensagem.reset_mock()
            # a conferência do instalador: sem caixa, com um relatório que diz o que falta
            self.assertEqual(principal.main(["--verificar-instalacao", "--relatorio", str(relatorio)]), 1)
            mensagem.assert_not_called()
        texto = relatorio.read_text(encoding="utf-8")
        self.assertIn("FALHA  Falta uma parte do programa: helestron.nucleo.registro", texto)
        self.assertIn("Helestron-Setup", texto)

    def test_falta_uma_parte_cita_o_modulo(self):
        from helestron import aplicativo

        with mock.patch.dict(sys.modules, {"helestron.aplicativo.inicio": None}), \
                mock.patch.dict(aplicativo.__dict__), \
                mock.patch.object(principal, "_mensagem") as mensagem:
            aplicativo.__dict__.pop("inicio", None)
            self.assertEqual(principal.abrir_programa(), 1)
        self.assertIn("(helestron.aplicativo.inicio)", mensagem.call_args.args[1])

    def test_erro_inesperado_vai_para_o_registro(self):
        """O lançador aponta o registro (Logs) quando o programa fecha logo depois
        de começar: o erro tem de estar lá (sem console, ele ia para o nada)."""
        import logging

        from helestron.aplicativo import inicio

        antes = list(logging.getLogger().handlers)

        def limpar():
            for h in list(logging.getLogger().handlers):
                if h not in antes:
                    logging.getLogger().removeHandler(h)
                    h.close()

        self.addCleanup(limpar)
        with mock.patch.object(inicio, "main", side_effect=RuntimeError("falha de teste 4815")):
            self.assertEqual(principal.abrir_programa(), 1)
        for h in logging.getLogger().handlers:
            h.flush()
        registros = "".join(p.read_text(encoding="utf-8") for p in (self.amb.local / "Logs").glob("*.log"))
        self.assertIn("o Helestron fechou por um erro inesperado", registros)
        self.assertIn("RuntimeError: falha de teste 4815", registros)

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

    def test_sem_interface_tkinter(self):
        fonte = (RAIZ / "helestron" / "__main__.py").read_text(encoding="utf-8")
        self.assertNotIn("interface", fonte.replace("interface (", "").split('"""', 2)[2])
        self.assertNotIn("importlib", fonte)


class TestComandosParaAutomacao(unittest.TestCase):
    """--version, caminhos, preparar e preparar-pastas com linha de comando de
    verdade (1.0.2): o que a skill do Claude chama."""

    def setUp(self):
        import logging

        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        antes = list(logging.getLogger().handlers)

        def limpar():
            for h in list(logging.getLogger().handlers):
                if h not in antes:
                    logging.getLogger().removeHandler(h)
                    h.close()
        self.addCleanup(limpar)
        self.acervo = self.amb.dados / "Acervo"
        self.sigilosos = self.amb.dados / "Sigilosos"

    def rodar(self, *args) -> tuple[int, str, str]:
        saida, erros = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erros):
            codigo = principal.main(list(args))
        return codigo, saida.getvalue(), erros.getvalue()

    def pdf(self, caminho: Path, texto: str = "autos") -> Path:
        import pymupdf

        caminho.parent.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), texto)
        doc.save(str(caminho))
        doc.close()
        return caminho

    def test_version(self):
        from helestron import __version__

        for opcao in ("--version", "--versao"):
            codigo, saida, _ = self.rodar(opcao)
            self.assertEqual(codigo, 0, opcao)
            self.assertEqual(saida.strip(), f"Helestron {__version__}")

    def test_caminhos_json_sem_criar_config_e_sem_perfis(self):
        from helestron.nucleo import caminhos

        (self.amb.local / "config.ini").unlink()
        codigo, saida, _ = self.rodar("caminhos", "--json")
        self.assertEqual(codigo, 0)
        self.assertFalse((self.amb.local / "config.ini").exists(), "caminhos não cria nada")
        self.assertFalse(caminhos.LOGS.exists())
        dados = json.loads(saida)
        for chave in ("versao", "recursos", "python", "config", "logs", "acervo", "processos",
                      "transcricoes", "sigilosos", "pauta", "separar_sigilosos", "login",
                      "espera_login_min", "conflito_de_pastas"):
            self.assertIn(chave, dados)
        self.assertIn("baixar.json", dados["recursos"])
        self.assertIn("preparar.pasta", dados["recursos"])
        self.assertEqual(dados["acervo"], str(self.acervo))
        self.assertEqual(dados["login"], {"esaj": "senha", "eproc": "senha"})
        # nada que leve às senhas, aos perfis do navegador ou à sessão guardada
        self.assertNotIn(str(caminhos.PERFIS), saida)
        self.assertNotIn("credenciais", saida)
        self.assertNotIn("perfis", saida.lower())
        codigo, saida, _ = self.rodar("caminhos")
        self.assertEqual(codigo, 0)
        self.assertIn(f"acervo: {self.acervo}", saida)

    def test_preparar_rejeita_argumento_e_mostra_ajuda(self):
        codigo, saida, _ = self.rodar("preparar", "-h")
        self.assertEqual(codigo, 0)
        self.assertIn("uso: python -m helestron preparar", saida)
        self.assertIn("--pasta", saida)
        self.assertFalse((self.acervo / "CLAUDE.md").exists(), "-h não prepara o acervo")
        for args in (("preparar", "--xyz"), ("preparar", "--sem-texto", "xyz"),
                     ("preparar-pastas", "--xyz"), ("caminhos", "--xyz"),
                     ("preparar", "--incluir-sigilosos")):
            with self.subTest(args=args):
                codigo, _, erros = self.rodar(*args)
                self.assertEqual(codigo, 2)
                self.assertTrue(erros.strip())
        self.assertFalse(self.acervo.exists(), "nada foi criado")
        codigo, saida, _ = self.rodar("preparar-pastas", "-h")
        self.assertEqual(codigo, 0)
        self.assertIn("uso: python -m helestron preparar-pastas", saida)
        self.assertFalse((self.acervo / "Processos").exists())

    def test_preparar_pasta_nao_escreve_claude_md(self):
        lote = self.amb.raiz / "Lotes da skill" / "Lote 1"
        num = "0700001-27.2024.8.02.0001"
        self.pdf(lote / f"{num}.pdf", "Petição inicial")
        codigo, saida, _ = self.rodar("preparar", "--pasta", str(lote), "--json")
        self.assertEqual(codigo, 0)
        dados = json.loads(saida)
        self.assertEqual(dados["pasta"], str(lote))
        item = dados["itens"][0]
        self.assertEqual(item["situacao"], "novo")
        self.assertEqual(item["texto"], str(lote / "_texto" / f"{num}.txt"))
        self.assertIn("Petição inicial", Path(item["texto"]).read_text(encoding="utf-8"))
        self.assertEqual(item["paginas"], 1)
        self.assertFalse(item["paginacao"]["garantida"])
        for nome in ("CLAUDE.md", "AGENTS.md", "INDICE.md", "Produtos"):
            self.assertFalse((self.acervo / nome).exists(), nome)
            self.assertFalse((lote / nome).exists(), nome)
        codigo, saida, _ = self.rodar("preparar", "--pasta", str(lote), "--json")
        self.assertEqual(json.loads(saida)["itens"][0]["situacao"], "em_dia")
        codigo, saida, _ = self.rodar("preparar", "--pasta", str(lote), "--texto-em",
                                      str(self.amb.raiz / "textos"))
        self.assertEqual(codigo, 0)
        self.assertIn("1 texto pronto", saida)
        self.assertTrue((self.amb.raiz / "textos" / f"{num}.txt").exists())
        codigo, _, erros = self.rodar("preparar", "--pasta", str(self.amb.raiz / "não existe"))
        self.assertEqual(codigo, 2)
        self.assertIn("não existe", erros)

    def test_preparar_pasta_diz_as_paginas_sem_texto(self):
        import pymupdf

        from helestron.nucleo import paginacao

        lote = self.amb.raiz / "Lotes da skill" / "Lote 2"
        num, outro = "0700001-27.2024.8.02.0001", "0700002-02.2024.8.02.0001"
        lote.mkdir(parents=True)
        doc = pymupdf.open()
        for texto in ("Petição inicial", "", "", "Contestação", "fls. 5"):
            doc.new_page().insert_text((72, 72), texto)
        paginacao.gravar_no_doc(doc, paginacao.manifesto_esaj(num, 5, {}, tribunal="TJAL"))
        doc.save(str(lote / f"{num}.pdf"))
        doc.close()
        self.pdf(lote / f"{outro}.pdf", "Petição inicial")
        codigo, saida, _ = self.rodar("preparar", "--pasta", str(lote), "--json")
        self.assertEqual(codigo, 0)
        itens = {Path(i["pdf"]).stem: i for i in json.loads(saida)["itens"]}
        self.assertEqual((itens[num]["paginas_sem_texto"], itens[num]["paginas_sem_texto_pdf"]),
                         ("2-3, 5", "2-3, 5"))
        self.assertTrue(itens[num]["paginacao"]["garantida"])
        self.assertEqual(itens[outro]["paginas_sem_texto"], "")
        # sem --json, a frase diz o arquivo e as folhas; em dia, a informação continua
        codigo, saida, _ = self.rodar("preparar", "--pasta", str(lote))
        self.assertEqual(codigo, 0)
        self.assertIn(f"{num}.pdf: páginas sem texto extraível (imagem? confira no PDF): 2-3, 5",
                      saida)
        self.assertNotIn(f"{outro}.pdf:", saida)

    def test_recursos_novos_e_versao_do_pacote(self):
        import helestron

        codigo, saida, _ = self.rodar("caminhos", "--json")
        self.assertEqual(codigo, 0)
        dados = json.loads(saida)
        self.assertEqual(dados["versao"], helestron.__version__)
        for recurso in ("folhas.fieis", "texto.v2", "capa.v2", "texto.paginas-sem-texto",
                        "baixar.codigo-na-janela", "baixar.json", "preparar.pasta"):
            self.assertIn(recurso, dados["recursos"])
        self.assertEqual(len(dados["recursos"]), len(set(dados["recursos"])))
        with mock.patch.object(helestron, "__version__", "9.9.9"):
            self.assertEqual(json.loads(self.rodar("caminhos", "--json")[1])["versao"], "9.9.9")

    def test_preparar_pasta_no_acervo_pula_sigiloso_e_inclui_os_do_lote(self):
        lote = self.acervo / "Processos" / "Lote 1"
        publico, sigiloso = "0700001-27.2024.8.02.0001", "0700002-02.2024.8.02.0001"
        self.pdf(lote / f"{publico}.pdf")
        self.pdf(lote / f"{sigiloso}.pdf")           # preso no acervo
        self.pdf(self.sigilosos / "Lote 1" / f"{sigiloso}.pdf", "autos em segredo")
        self.pdf(lote / "ruim.pdf").write_bytes(b"%PDF-1.4 quebrado")
        codigo, saida, _ = self.rodar("preparar", "--pasta", str(lote), "--incluir-sigilosos",
                                      "--json")
        self.assertEqual(codigo, 1, "um PDF ilegível")
        itens = {(Path(i["pdf"]).parent.name, Path(i["pdf"]).stem): i
                 for i in json.loads(saida)["itens"]}
        self.assertEqual(itens[("Lote 1", publico)]["situacao"], "novo")
        no_acervo = [i for i in json.loads(saida)["itens"]
                     if i["pdf"] == str(lote / f"{sigiloso}.pdf")][0]
        self.assertEqual(no_acervo["situacao"], "sigiloso_ignorado")
        self.assertFalse((lote / "_texto" / f"{sigiloso}.txt").exists())
        do_sigiloso = [i for i in json.loads(saida)["itens"]
                       if i["pdf"] == str(self.sigilosos / "Lote 1" / f"{sigiloso}.pdf")][0]
        self.assertEqual(do_sigiloso["situacao"], "novo")
        self.assertTrue(do_sigiloso["sigiloso"])
        self.assertEqual(Path(do_sigiloso["texto"]),
                         self.sigilosos / "Lote 1" / "_texto" / f"{sigiloso}.txt")
        self.assertEqual(itens[("Lote 1", "ruim")]["situacao"], "falhou")

    def _relatorio(self, **campos):
        from helestron.compartilhar import preparo

        return preparo.RelatorioPreparo(**campos)

    def test_preparar_mostra_erros_e_avisos_e_sai_3_com_sigiloso_preso(self):
        from helestron.compartilhar import preparo

        preso = self.acervo / "Processos" / "L" / "0700002-02.2024.8.02.0001.pdf"
        rel = self._relatorio(processos=1, erros=["ATENÇÃO: autos de processo sigiloso no "
                                                  "acervo: mova-os"],
                              avisos=["arquivo levado para a pasta dos sigilosos"],
                              sigilosos_no_acervo=[preso], motivos={preso: "aberto?"})
        with mock.patch.object(preparo, "atualizar_contexto", return_value=rel) as chamada:
            codigo, saida, erros = self.rodar("preparar")
            self.assertEqual(codigo, 3)
            self.assertIn("ATENÇÃO: autos de processo sigiloso no acervo: mova-os", erros)
            self.assertIn("aviso: arquivo levado para a pasta dos sigilosos", saida)
            self.assertIn("1 processo", saida)
            self.assertIsNone(chamada.call_args.kwargs["extrair_texto"])
            codigo, saida, _ = self.rodar("preparar", "--json", "--sem-texto")
            self.assertEqual(codigo, 3)
            dados = json.loads(saida)
            self.assertFalse(dados["pode_compartilhar"])
            self.assertEqual(dados["sigilosos_no_acervo"], [str(preso)])
            self.assertEqual(dados["motivos"], {str(preso): "aberto?"})
            self.assertFalse(chamada.call_args.kwargs["extrair_texto"])
        rel = self._relatorio(processos=1, erros=["x.pdf: não abre"])
        with mock.patch.object(preparo, "atualizar_contexto", return_value=rel):
            codigo, _, erros = self.rodar("preparar")
        self.assertEqual(codigo, 1)
        self.assertIn("x.pdf: não abre", erros)
        with mock.patch.object(preparo, "atualizar_contexto",
                               return_value=self._relatorio(processos=2)):
            self.assertEqual(self.rodar("preparar")[0], 0)


if __name__ == "__main__":
    unittest.main()
