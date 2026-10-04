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

import os
import sys
from pathlib import Path


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
    print(f"{titulo}\n\n{texto}", file=sys.stderr)


def _opcao(args: list[str], nome: str) -> str | None:
    """O valor de '--nome VALOR' ou '--nome=VALOR' (None se ausente)."""
    for i, a in enumerate(args):
        if a == nome:
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise SystemExit(f"Faltou o valor depois de {nome}.")
            return args[i + 1]
        if a.startswith(nome + "="):
            return a.split("=", 1)[1]
    return None


def abrir_programa(autoteste: Path | None = None) -> int:
    try:
        from .aplicativo import inicio
    except ImportError as erro:
        # Arquivo do programa ausente (antivírus, instalação interrompida):
        # nem a tela de erro própria pode abrir.
        _mensagem("O Helestron não pôde abrir",
                  f"Falta uma parte do programa ({getattr(erro, 'name', '') or erro}).\n\n"
                  "Isso costuma acontecer quando o antivírus põe um arquivo em quarentena, ou "
                  "quando a instalação foi interrompida. Instale o Helestron de novo com o "
                  "Helestron-Setup: ele conserta a instalação sem apagar os seus dados.")
        return 1
    return inicio.main(autoteste=autoteste)


def servidor(args: list[str]) -> int:
    """--servidor: só o servidor local (testes e desenvolvimento)."""
    from .nucleo import registro
    from .servidor.aplicacao import Aplicacao

    porta = _opcao(args, "--porta")
    token = _opcao(args, "--token")
    sem_janela = "--sem-janela" in args
    try:
        registro.configurar(console=False)
    except Exception:
        pass
    app = Aplicacao(modo="servidor", token=token or None,
                    porta=int(porta) if porta else 0).iniciar()
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


def main(argv: list[str] | None = None) -> int:
    from .nucleo import registro

    registro.preparar_saidas()
    _ambiente()
    args = list(sys.argv[1:] if argv is None else argv)

    if not args:
        return abrir_programa()
    comando, resto = args[0], args[1:]
    if comando in ("-h", "--help", "--ajuda", "ajuda"):
        print(__doc__)
        return 0
    if comando == "--verificar-instalacao":
        from .aplicativo import verificacao

        try:
            registro.configurar(console=False)
        except Exception:
            pass
        destino = _opcao(resto, "--relatorio")
        return verificacao.executar(Path(destino) if destino else None)
    if comando == "--autoteste":
        if not resto or resto[0].startswith("--"):
            print("Uso: python -m helestron --autoteste PASTA")
            return 2
        return abrir_programa(Path(resto[0]))
    if comando == "--servidor":
        return servidor(resto)
    if comando == "--encerrar":
        from .aplicativo import instancia

        return instancia.encerrar_aberta()
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
    if comando == "preparar-pastas":
        from .nucleo import config

        cfg = config.carregar()
        cfg.criar_pastas()
        print(f"Configuração: {cfg.arquivo}")
        print(f"Acervo: {cfg.pasta_acervo}")
        return 0
    print(f"Comando desconhecido: {comando}\n")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
