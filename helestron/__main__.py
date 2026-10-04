"""Ponto de entrada: `python -m helestron` abre o programa; com opção ou subcomando,
a linha de comando. O lançador Helestron.exe roda `python -I -m helestron`.

    python -m helestron                               abre o programa (servidor + janela)
    python -m helestron --verificar-instalacao [--relatorio ARQ]
                                                      confere a instalação, sem janela
    python -m helestron --autoteste PASTA             percorre a interface e salva capturas
    python -m helestron --servidor [--porta N] [--sem-janela] [--token T]
                                                      só o servidor (imprime URL=...)
    python -m helestron --encerrar                    pede ao programa aberto que feche
    python -m helestron baixar --lista X.xlsx         baixa os processos da relação
    python -m helestron transcrever ARQUIVO           transcreve uma gravação
    python -m helestron modelos baixar small          baixa um modelo de transcrição
    python -m helestron falantes instalar             baixa os modelos da separação de falantes
    python -m helestron microfones                    lista os microfones
    python -m helestron verificar [--completo]        confere a instalação (detalhado)
    python -m helestron mcp --pasta ACERVO            servidor MCP do acervo (Claude/ChatGPT)
    python -m helestron preparar                      prepara o acervo para a IA (textos e índice)
    python -m helestron preparar-pastas               cria o config.ini e as pastas de trabalho
    python -m helestron pauta sincronizar|exportar|importar ...
                                                      a pauta de audiências
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from .nucleo.argumentos import ArgumentParser
except ImportError:                     # instalação quebrada: o do argparse serve
    from argparse import ArgumentParser

# Os subcomandos: o resto da linha vai inteiro para a linha de comando de cada um.
SUBCOMANDOS = ("baixar", "transcrever", "modelos", "falantes", "microfones", "verificar", "mcp",
               "pauta", "preparar", "preparar-pastas")

COMANDOS = """comandos (cada um tem a própria ajuda: python -m helestron <comando> -h):
  baixar --lista X.xlsx       baixa os processos da relação
  transcrever ARQUIVO         transcreve uma gravação
  modelos baixar small        baixa um modelo de transcrição
  falantes instalar           baixa os modelos da separação de falantes
  microfones                  lista os microfones
  verificar [--completo]      confere a instalação (detalhado)
  mcp --pasta ACERVO          servidor MCP do acervo (Claude/ChatGPT)
  preparar                    prepara o acervo para a IA (textos e índice)
  preparar-pastas             cria o config.ini e as pastas de trabalho
  pauta sincronizar|exportar|importar ...
                              a pauta de audiências

Sem argumentos, abre o programa (servidor + janela)."""

REINSTALAR = ("Isso costuma acontecer quando o antivírus põe um arquivo em quarentena, ou quando "
              "a instalação foi interrompida. Instale o Helestron de novo com o Helestron-Setup: "
              "ele conserta a instalação sem apagar os seus dados.")


def _ambiente() -> None:
    # O programa não traz navegador próprio: o download e a pauta usam o
    # Google Chrome ou o Microsoft Edge do computador (download/navegador.py),
    # e por isso PLAYWRIGHT_BROWSERS_PATH não é definido aqui.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def _mensagem(titulo: str, texto: str) -> None:
    """Caixa de mensagem sem depender de nada do pacote (instalação quebrada)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, texto, titulo, 0x10 | 0x40000)
            return
        except Exception:
            pass
    try:
        print(f"{titulo}\n\n{texto}", file=sys.stderr)
    except Exception:
        pass


def parte_que_falta(erro: ImportError) -> str:
    """O módulo que faltou, pelo texto do erro: "No module named 'x.y'" -> x.y;
    "cannot import name 'z' from 'x.y' (...)" -> x.y.z (erro.name diria só o
    pacote, x.y)."""
    texto = str(erro)
    achado = re.match(r"cannot import name '([^']+)' from '([^']+)'", texto)
    if achado:
        return f"{achado.group(2)}.{achado.group(1)}"
    achado = re.match(r"No module named '([^']+)'", texto)
    if achado:
        return achado.group(1)
    return getattr(erro, "name", "") or texto


def _anotar_erro(contexto: str) -> None:
    """O erro em andamento vai para o registro (Logs): é para lá que a mensagem
    do lançador aponta quando o programa fecha logo depois de começar."""
    try:
        import logging

        from .nucleo import registro

        if not any(getattr(h, "_helestron", False) for h in logging.getLogger().handlers):
            registro.configurar(console=False)
        logging.getLogger("helestron").exception(contexto)
    except Exception:
        pass


def abrir_programa(autoteste: Path | None = None) -> int:
    try:
        from .aplicativo import inicio
    except ImportError as erro:
        # Arquivo do programa ausente (antivírus, instalação interrompida):
        # nem a tela de erro própria pode abrir.
        _anotar_erro("falta uma parte do programa")
        _mensagem("O Helestron não pôde abrir",
                  f"Falta uma parte do programa ({parte_que_falta(erro)}).\n\n{REINSTALAR}")
        return 1
    try:
        return inicio.main(autoteste=autoteste)
    except Exception:
        _anotar_erro("o Helestron fechou por um erro inesperado")
        return 1


def _relatorio_sem_o_programa(args: list[str], erro: ImportError) -> None:
    """--verificar-instalacao sem o registro do programa: um relatório mínimo,
    para o instalador dizer o que falta (sem ele, só "não conseguiu terminar")."""
    destino = None
    for i, a in enumerate(args):
        if a == "--relatorio" and i + 1 < len(args):
            destino = Path(args[i + 1])
        elif a.startswith("--relatorio="):
            destino = Path(a.split("=", 1)[1])
    if destino is None:
        local = os.environ.get("HELESTRON_LOCAL") or (
            str(Path(os.environ["LOCALAPPDATA"]) / "Helestron") if os.environ.get("LOCALAPPDATA") else "")
        if not local:
            return
        destino = Path(local) / "Logs" / "verificacao-instalacao.txt"
    texto = (f"Helestron — verificação da instalação\nData: {datetime.now():%d/%m/%Y %H:%M:%S}\n\n"
             f"  FALHA  Falta uma parte do programa: {parte_que_falta(erro)}\n"
             f"         - {erro}\n"
             f"         O que fazer: {REINSTALAR}\n")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    except OSError:
        pass


def _sem_parte_de_partida(args: list[str], erro: ImportError) -> int:
    """Falta o registro (ou o caminhos) do pacote: nada mais do programa roda."""
    if not args or args[0].startswith("--autoteste"):
        _mensagem("O Helestron não pôde abrir",
                  f"Falta uma parte do programa ({parte_que_falta(erro)}).\n\n{REINSTALAR}")
    elif args[0] == "--verificar-instalacao":
        _relatorio_sem_o_programa(args[1:], erro)       # o instalador informa o usuário
    else:
        try:
            print(f"Falta uma parte do programa ({parte_que_falta(erro)}). {REINSTALAR}",
                  file=sys.stderr)
        except Exception:
            pass
    return 1


def _formatador() -> type:
    """A ajuda com o "uso:" em português e a lista de comandos como foi escrita."""
    try:
        from .nucleo.argumentos import Formatador
    except ImportError:
        Formatador = argparse.HelpFormatter

    class FormatadorDosComandos(Formatador, argparse.RawDescriptionHelpFormatter):
        pass

    return FormatadorDosComandos


def analisador() -> argparse.ArgumentParser:
    p = ArgumentParser(prog="python -m helestron", formatter_class=_formatador(),
                       description="Helestron: baixa processos, transcreve audiências, monitora a\n"
                                   "pauta de audiências e prepara o acervo para a IA.",
                       epilog=COMANDOS)
    o_que = p.add_mutually_exclusive_group()
    o_que.add_argument("--verificar-instalacao", action="store_true",
                       help="confere a instalação, sem janela (o instalador usa)")
    o_que.add_argument("--autoteste", metavar="PASTA",
                       help="percorre todas as telas e salva as capturas na PASTA")
    o_que.add_argument("--servidor", action="store_true",
                       help="só o servidor local (imprime URL=...)")
    o_que.add_argument("--encerrar", action="store_true",
                       help="pede ao programa aberto que feche (o instalador usa)")
    p.add_argument("--relatorio", metavar="ARQ",
                   help="com --verificar-instalacao: onde gravar o relatório")
    p.add_argument("--porta", type=int, metavar="N",
                   help="com --servidor: a porta (padrão: uma livre)")
    p.add_argument("--sem-janela", action="store_true", help="com --servidor: sem abrir a janela")
    p.add_argument("--token", metavar="T", help="com --servidor: o token (padrão: um aleatório)")
    return p


def servidor(porta: int | None = None, token: str | None = None, sem_janela: bool = False) -> int:
    """--servidor: só o servidor local (testes e desenvolvimento)."""
    from .nucleo import registro
    from .servidor.aplicacao import Aplicacao

    try:
        registro.configurar(console=False)
    except Exception:
        pass
    app = Aplicacao(modo="servidor", token=token or None, porta=porta or 0).iniciar()
    print(f"URL={app.url}", flush=True)
    try:
        if sem_janela:
            while not app.esperar(0.5):
                pass
        else:
            from .aplicativo import janela
            from .aplicativo.monitor import MonitorPauta

            app.monitor = MonitorPauta(app).iniciar()
            janela.abrir(app, app.url)
    except KeyboardInterrupt:
        pass
    finally:
        app.encerrar()
    return 0


def _subcomando(comando: str, resto: list[str]) -> int:
    from .nucleo import registro

    if comando == "baixar":
        from .download import cli

        return cli.main(resto)
    if comando in ("transcrever", "modelos", "falantes", "microfones"):
        from .transcricao import cli

        return cli.main([comando] + resto)
    if comando == "verificar":
        from . import verificar

        return verificar.main(resto)
    if comando == "mcp":
        from .compartilhar import mcp_servidor

        return mcp_servidor.main(resto)
    if comando == "pauta":
        from .pauta import cli

        return cli.main(resto)
    if comando == "preparar":
        registro.configurar()
        from .compartilhar import preparo
        from .nucleo import config

        rel = preparo.atualizar_contexto(config.carregar())
        print(rel.resumo)
        return 1 if rel.erros else 0
    # preparar-pastas
    from .nucleo import config

    cfg = config.carregar()
    cfg.criar_pastas()
    print(f"Configuração: {cfg.arquivo}")
    print(f"Acervo: {cfg.pasta_acervo}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        from .nucleo import registro

        registro.preparar_saidas()
    except ImportError as erro:
        return _sem_parte_de_partida(args, erro)
    _ambiente()

    if not args:
        return abrir_programa()
    comando, resto = args[0], args[1:]
    if comando in SUBCOMANDOS:
        return _subcomando(comando, resto)
    p = analisador()
    if comando in ("--ajuda", "ajuda"):
        p.print_help()
        return 0
    try:
        if not comando.startswith("-"):
            p.error(f"comando desconhecido: {comando} (comandos: {', '.join(SUBCOMANDOS)})")
        opcoes = p.parse_args(args)
        if opcoes.relatorio is not None and not opcoes.verificar_instalacao:
            p.error("--relatorio só vale com --verificar-instalacao")
        if (opcoes.porta is not None or opcoes.sem_janela or opcoes.token is not None) \
                and not opcoes.servidor:
            p.error("--porta, --sem-janela e --token só valem com --servidor")
        if not (opcoes.verificar_instalacao or opcoes.autoteste or opcoes.servidor
                or opcoes.encerrar):
            p.error("diga o que fazer: --verificar-instalacao, --autoteste, --servidor, "
                    "--encerrar ou um comando")
    except SystemExit as saida:             # -h (0) ou erro na linha de comando (2)
        return saida.code if isinstance(saida.code, int) else 2

    if opcoes.verificar_instalacao:
        from .aplicativo import verificacao

        try:
            registro.configurar(console=False)
        except Exception:
            pass
        return verificacao.executar(Path(opcoes.relatorio) if opcoes.relatorio else None)
    if opcoes.autoteste:
        return abrir_programa(Path(opcoes.autoteste))
    if opcoes.servidor:
        return servidor(opcoes.porta, opcoes.token, opcoes.sem_janela)
    from .aplicativo import instancia

    return instancia.encerrar_aberta()


if __name__ == "__main__":
    sys.exit(main())
