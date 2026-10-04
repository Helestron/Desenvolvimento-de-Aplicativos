"""argparse em português do Brasil, para todas as linhas de comando do programa.

    from ..nucleo.argumentos import ArgumentParser

    p = ArgumentParser(prog="python -m helestron baixar", description="...")

A classe é a do argparse, com o que o usuário lê traduzido: o "uso:" da
primeira linha, os títulos "argumentos" e "opções", o "-h, --help" ("mostra
esta ajuda e sai") e as mensagens de erro (argumento obrigatório que falta,
argumento não reconhecido, escolha inválida, valor inválido...), no formato

    uso: python -m helestron baixar [-h] ...
    python -m helestron baixar: erro: argumento não reconhecido: --xyz

e com o código de saída 2 do argparse. Os subcomandos (add_subparsers) usam
a mesma classe. As mensagens do argparse são traduzidas por modelo, frase
inteira (nunca palavra solta dentro de um texto já traduzido); o que não
for do argparse (a mensagem de um ArgumentTypeError do próprio programa,
já em português) passa como está.

traduzir(mensagem) serve a quem trata o erro por conta própria (a linha de
comando da transcrição devolve o código em vez de encerrar o processo).
"""

from __future__ import annotations

import argparse
import re
import sys

# Nomes dos tipos do argparse ("invalid int value: 'x'")
_TIPOS = {
    "int": "um número inteiro",
    "float": "um número",
    "complex": "um número",
    "Path": "um caminho",
    "PosixPath": "um caminho",
    "WindowsPath": "um caminho",
    "date": "uma data",
}


def _quantos(lista: str, separador: str) -> int:
    return len([p for p in lista.split(separador) if p.strip()])


def _faltam(m: re.Match) -> str:
    nomes = m.group(1)
    if _quantos(nomes, ",") <= 1:
        return f"falta o argumento obrigatório: {nomes}"
    return f"faltam os argumentos obrigatórios: {nomes}"


def _nao_reconhecidos(m: re.Match) -> str:
    resto = m.group(1)
    if _quantos(resto, " ") <= 1:
        return f"argumento não reconhecido: {resto}"
    return f"argumentos não reconhecidos: {resto}"


def _valor_invalido(m: re.Match) -> str:
    tipo, valor = m.group(1), m.group(2)
    esperado = _TIPOS.get(tipo)
    return f"valor inválido: {valor}" + (f" (era esperado {esperado})" if esperado else "")


def _esperados(m: re.Match) -> str:
    n = m.group(1)
    return f"falta o valor (são esperados {n} valores)" if n != "1" else "falta o valor"


# (modelo do argparse, tradução). Frases inteiras, aplicadas a cada parte da
# mensagem; a ordem importa só entre modelos que começam igual.
_MODELOS: list[tuple[re.Pattern, object]] = [
    (re.compile(r"^the following arguments are required: (.+)$", re.S), _faltam),
    (re.compile(r"^unrecognized arguments?: (.+)$", re.S), _nao_reconhecidos),
    (re.compile(r"^invalid choice: (.+?) \(choose from (.+)\)$", re.S),
     r"escolha inválida: \1 (opções: \2)"),
    (re.compile(r"^invalid (\S+) value: (.+)$", re.S), _valor_invalido),
    (re.compile(r"^expected one argument$"), "falta o valor"),
    (re.compile(r"^expected at most one argument$"), "aceita no máximo um valor"),
    (re.compile(r"^expected at least one argument$"), "falta o valor (pelo menos um)"),
    (re.compile(r"^expected (\d+) arguments?$"), _esperados),
    (re.compile(r"^one of the arguments (.+) is required$", re.S),
     r"informe um destes argumentos: \1"),
    (re.compile(r"^not allowed with argument (.+)$", re.S),
     r"não pode ser usado junto com o argumento \1"),
    (re.compile(r"^ambiguous option: (.+?) could match (.+)$", re.S),
     r"opção ambígua: \1 pode ser \2"),
    (re.compile(r"^ignored explicit argument (.+)$", re.S),
     r"esta opção não aceita valor (recebeu \1)"),
    (re.compile(r"^unknown parser (.+?) \(choices: (.+)\)$", re.S),
     r"comando desconhecido: \1 (opções: \2)"),
    (re.compile(r"^unexpected option string: (.+)$", re.S), r"opção inesperada: \1"),
]

# "argument --sistema/-s: <mensagem>" (o ArgumentError com o nome do argumento)
_COM_ARGUMENTO = re.compile(r"^argument ([^:]+): (.*)$", re.S)


def _traduzir_frase(frase: str) -> str:
    for modelo, traducao in _MODELOS:
        m = modelo.match(frase)
        if m:
            return traducao(m) if callable(traducao) else m.expand(traducao)
    return frase


def traduzir(mensagem: str) -> str:
    """A mensagem de erro do argparse em português (o que não for dele passa
    como está)."""
    mensagem = str(mensagem or "")
    m = _COM_ARGUMENTO.match(mensagem)
    if m:
        return f"argumento {m.group(1)}: {_traduzir_frase(m.group(2))}"
    return _traduzir_frase(mensagem)


class Formatador(argparse.HelpFormatter):
    """A ajuda com "uso:" e "(padrão: ...)"."""

    def add_usage(self, usage, actions, groups, prefix=None):
        # prefix "" é o argparse montando o nome do subcomando: fica sem prefixo
        return super().add_usage(usage, actions, groups, "uso: " if prefix is None else prefix)

    def _get_help_string(self, action):
        texto = super()._get_help_string(action) or ""
        return texto.replace("(default: %(default)s)", "(padrão: %(default)s)")


class FormatadorComPadroes(Formatador, argparse.ArgumentDefaultsHelpFormatter):
    """Como o ArgumentDefaultsHelpFormatter (mostra o padrão de cada opção)."""


class ArgumentParser(argparse.ArgumentParser):
    """argparse.ArgumentParser em português do Brasil (ajuda, títulos e erros)."""

    def __init__(self, *args, **kwargs):
        if kwargs.get("formatter_class") in (None, argparse.HelpFormatter):
            kwargs["formatter_class"] = Formatador
        elif kwargs.get("formatter_class") is argparse.ArgumentDefaultsHelpFormatter:
            kwargs["formatter_class"] = FormatadorComPadroes
        ajuda = kwargs.pop("add_help", True)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "argumentos"
        self._optionals.title = "opções"
        self.add_help = ajuda
        if ajuda:
            prefixo = "-" if "-" in self.prefix_chars else self.prefix_chars[0]
            self.add_argument(prefixo + "h", prefixo * 2 + "help", action="help",
                              default=argparse.SUPPRESS, help="mostra esta ajuda e sai")

    def add_argument(self, *args, **kwargs):
        if kwargs.get("action") == "version" and "help" not in kwargs:
            kwargs["help"] = "mostra a versão do programa e sai"
        return super().add_argument(*args, **kwargs)

    def add_subparsers(self, **kwargs):
        # Os subcomandos falam a mesma língua; o título padrão do grupo
        # ("subcommands") vira "comandos".
        kwargs.setdefault("parser_class", type(self))
        if "description" in kwargs and "title" not in kwargs:
            kwargs["title"] = "comandos"
        return super().add_subparsers(**kwargs)

    def _check_value(self, action, value):
        # O subcomando desconhecido diz "comando", e não "argumento <dest>"
        # (o nome interno do destino, como "acao", sem acento).
        if isinstance(action, argparse._SubParsersAction) and action.choices is not None \
                and value not in action.choices:
            opcoes = ", ".join(map(str, action.choices))
            raise argparse.ArgumentError(
                None, f"comando desconhecido: {value!r} (opções: {opcoes})")
        return super()._check_value(action, value)

    def mensagem_de_erro(self, mensagem: str) -> str:
        """'<prog>: erro: <mensagem traduzida>' (sem o "uso:")."""
        return f"{self.prog}: erro: {traduzir(mensagem)}"

    def error(self, message):  # noqa: D401 - assinatura do argparse
        self.print_usage(sys.stderr)
        self.exit(2, self.mensagem_de_erro(message) + "\n")
