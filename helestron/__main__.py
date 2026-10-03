"""Ponto de entrada: `python -m helestron` abre a janela; com subcomando, a linha de comando.

    python -m helestron                         a janela do programa
    python -m helestron --teste-interface       abre, percorre as telas, salva captura e fecha
    python -m helestron baixar --lista X.xlsx   baixa os processos da relação
    python -m helestron transcrever ARQUIVO     transcreve uma gravação
    python -m helestron modelos baixar small    baixa um modelo de transcrição
    python -m helestron falantes instalar       instala a separação automática de falantes
    python -m helestron microfones              lista os microfones
    python -m helestron verificar [--completo]  confere a instalação
    python -m helestron mcp --pasta ACERVO      servidor MCP do acervo (para o Claude/ChatGPT)
    python -m helestron preparar                prepara o acervo para a IA (textos e índice)
    python -m helestron preparar-pastas         cria o config.ini e as pastas de trabalho
"""

from __future__ import annotations

import os
import sys


def _ambiente() -> None:
    from .nucleo import caminhos

    # O Chromium de reserva do Playwright mora dentro do programa.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(caminhos.NAVEGADORES))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def main(argv: list[str] | None = None) -> int:
    from .nucleo import registro

    registro.preparar_saidas()
    _ambiente()
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("--teste-interface", "--janela"):
        from .interface import janela

        return janela.executar(teste=bool(args) and args[0] == "--teste-interface") or 0

    comando, resto = args[0], args[1:]
    if comando in ("-h", "--help", "ajuda"):
        print(__doc__)
        return 0
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
