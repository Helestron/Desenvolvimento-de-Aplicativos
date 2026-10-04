"""A linha de comando em português (nucleo/argumentos.py) e o seu uso no
download, na transcrição e no servidor MCP.

Regressão: a pauta traduzia "argument" depois das outras trocas e escrevia
"faltam os argumentoos"; o `baixar` e o `transcrever` respondiam em inglês
("usage:", "error: unrecognized arguments")."""

from __future__ import annotations

import argparse
import contextlib
import io
import unittest

from helestron.nucleo import argumentos
from helestron.nucleo.argumentos import ArgumentParser, traduzir


def _erro(parser, argv) -> tuple[int, str]:
    saida = io.StringIO()
    with contextlib.redirect_stderr(saida), contextlib.redirect_stdout(io.StringIO()):
        try:
            parser.parse_args(argv)
        except SystemExit as fim:
            return int(fim.code or 0), saida.getvalue()
    return 0, saida.getvalue()


def _exemplo() -> ArgumentParser:
    p = ArgumentParser(prog="python -m helestron exemplo", description="Exemplo.")
    p.add_argument("arquivos", nargs="+", help="os arquivos")
    p.add_argument("--sistema", choices=("esaj", "eproc"), help="o sistema")
    p.add_argument("--quantos", type=int, help="quantos")
    p.add_argument("--sim", action="store_true", help="um interruptor")
    return p


class TestTraducao(unittest.TestCase):
    def test_mensagens_do_argparse(self):
        casos = {
            "the following arguments are required: arquivos":
                "falta o argumento obrigatório: arquivos",
            "the following arguments are required: arquivos, --de":
                "faltam os argumentos obrigatórios: arquivos, --de",
            "unrecognized arguments: --xyz": "argumento não reconhecido: --xyz",
            "unrecognized arguments: --xyz --abc": "argumentos não reconhecidos: --xyz --abc",
            "argument --sistema: invalid choice: 'foo' (choose from esaj, eproc)":
                "argumento --sistema: escolha inválida: 'foo' (opções: esaj, eproc)",
            "argument --quantos: invalid int value: 'x'":
                "argumento --quantos: valor inválido: 'x' (era esperado um número inteiro)",
            "argument --quantos: expected one argument": "argumento --quantos: falta o valor",
            "argument --sim: ignored explicit argument '3'":
                "argumento --sim: esta opção não aceita valor (recebeu '3')",
            "one of the arguments --a --b is required": "informe um destes argumentos: --a --b",
            "argument --a: not allowed with argument --b":
                "argumento --a: não pode ser usado junto com o argumento --b",
        }
        for ingles, portugues in casos.items():
            with self.subTest(ingles):
                self.assertEqual(traduzir(ingles), portugues)

    def test_nunca_argumentoos_e_texto_do_programa_passa_inteiro(self):
        for texto in ("faltam os argumentos: arquivos", "data inválida: 31/02 (use AAAA-MM-DD)",
                      "argumentos não reconhecidos: --x"):
            self.assertEqual(traduzir(texto), texto)
        self.assertNotIn("argumentoo", traduzir("the following arguments are required: a, b"))
        # o erro do próprio programa (ArgumentTypeError) dentro do "argument X:"
        self.assertEqual(traduzir("argument --de: data inválida: ontem"),
                         "argumento --de: data inválida: ontem")


class TestParser(unittest.TestCase):
    def test_ajuda_em_portugues(self):
        texto = _exemplo().format_help()
        self.assertTrue(texto.startswith("uso: python -m helestron exemplo"), texto)
        self.assertIn("\nargumentos:\n", texto)
        self.assertIn("\nopções:\n", texto)
        self.assertIn("-h, --help", texto)
        self.assertIn("mostra esta ajuda e sai", texto)
        for ingles in ("usage:", "positional arguments", "options:", "show this help"):
            self.assertNotIn(ingles, texto)

    def test_erros_em_portugues_com_codigo_2(self):
        p = _exemplo()
        casos = [
            ([], "erro: falta o argumento obrigatório: arquivos"),
            (["a", "--xyz"], "erro: argumento não reconhecido: --xyz"),
            (["a", "--sistema", "foo"], "erro: argumento --sistema: escolha inválida: 'foo'"),
            (["a", "--quantos", "x"], "erro: argumento --quantos: valor inválido: 'x'"),
            (["a", "--quantos"], "erro: argumento --quantos: falta o valor"),
        ]
        for argv, esperado in casos:
            with self.subTest(argv):
                codigo, saida = _erro(p, argv)
                self.assertEqual(codigo, 2)
                self.assertIn("uso: python -m helestron exemplo", saida)
                self.assertIn(f"python -m helestron exemplo: {esperado}", saida)
                for ingles in ("usage:", "error:", "argument ", "unrecognized", "invalid",
                               "expected", "required", "argumentoo"):
                    self.assertNotIn(ingles, saida)

    def test_subcomandos_falam_a_mesma_lingua(self):
        p = ArgumentParser(prog="prog")
        sub = p.add_subparsers(dest="acao", title="comandos", metavar="COMANDO")
        s = sub.add_parser("listar", help="lista")
        s.add_argument("--json", action="store_true")
        self.assertIsInstance(s, ArgumentParser)
        self.assertIn("mostra esta ajuda e sai", s.format_help())
        codigo, saida = _erro(p, ["inventado"])
        self.assertEqual(codigo, 2)
        self.assertIn("prog: erro: comando desconhecido: 'inventado' (opções: listar)", saida)
        codigo, saida = _erro(p, ["listar", "--xyz"])
        self.assertIn("erro: argumento não reconhecido: --xyz", saida)

    def test_sem_ajuda_e_padroes(self):
        p = ArgumentParser(prog="p", add_help=False,
                           formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        p.add_argument("--n", default=3, help="quantos")
        texto = p.format_help()
        self.assertNotIn("--help", texto)
        self.assertIn("(padrão: 3)", texto)
        self.assertTrue(issubclass(ArgumentParser, argparse.ArgumentParser))
        self.assertTrue(callable(argumentos.traduzir))


class TestLinhasDeComando(unittest.TestCase):
    def test_baixar_responde_em_portugues(self):
        from helestron.download import cli

        codigo, saida = _erro(cli.criar_parser(), ["--xyz"])
        self.assertEqual(codigo, 2)
        self.assertIn("uso: python -m helestron baixar", saida)
        self.assertIn("python -m helestron baixar: erro: argumento não reconhecido: --xyz", saida)
        codigo, saida = _erro(cli.criar_parser(), ["--login", "x"])
        self.assertIn("argumento --login: escolha inválida: 'x'", saida)
        self.assertIn("mostra esta ajuda e sai", cli.criar_parser().format_help())

    def test_transcrever_responde_em_portugues(self):
        from helestron.transcricao import cli

        for argv, esperado in (
                (["transcrever", "--xyz"],
                 "python -m helestron transcrever: erro: argumento não reconhecido: --xyz"),
                (["modelos", "inventado"],
                 "python -m helestron modelos: erro: comando desconhecido: 'inventado'")):
            with self.subTest(argv):
                saida, erros = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
                    codigo = cli.main(argv)
                self.assertEqual(codigo, cli.USO)
                self.assertIn(esperado, saida.getvalue())
                self.assertIn("uso: ", erros.getvalue())
                self.assertNotIn("usage:", erros.getvalue())

    def test_mcp_responde_em_portugues(self):
        from helestron.compartilhar import mcp_servidor

        erros = io.StringIO()
        with contextlib.redirect_stderr(erros), self.assertRaises(SystemExit) as fim:
            mcp_servidor.main(["--xyz"])
        self.assertEqual(fim.exception.code, 2)
        self.assertIn("python -m helestron mcp: erro: argumento não reconhecido: --xyz",
                      erros.getvalue())


if __name__ == "__main__":
    unittest.main()
