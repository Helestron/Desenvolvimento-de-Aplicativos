"""Restos da versão anterior (Assessor Integrado) na máquina de quem migra.

A versão anterior registrou o conector "assessor-integrado" no Claude
Desktop (claude_desktop_config.json) e "assessor_integrado" no Codex/ChatGPT
Work (%USERPROFILE%\\.codex\\config.toml). Depois de instalar o Helestron,
eles continuavam lá, apontando para um Python que não existe mais: o Claude
Desktop listava o servidor antigo (com erro) e o Diagnóstico acusava "o
Claude Desktop ainda tem o conector da versão anterior".

limpar_restos_antigos() tira só esses conectores antigos - o do Helestron e
os outros servidores do usuário ficam -, guardando antes uma cópia de cada
arquivo de configuração ("...antes-do-helestron-<data>"). Arquivo com JSON ou
TOML inválido não é tocado. O instalador chama depois de instalar:

    python -I -m helestron.compartilhar.migracao

(código de saída 0 sempre: a limpeza nunca impede a instalação).

reapontar_conectores() cuida da instalação que mudou de pasta: o conector do
Helestron no Claude Desktop e no Codex continuava apontando para o
python.exe da pasta anterior (que o instalador remove) e parava de
funcionar. Ele passa a apontar para o desta instalação, com a mesma pasta
do acervo. limpar_restos_antigos() o chama, de modo que a chamada do
instalador cobre os dois casos.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("compartilhar.migracao")

# O programa anterior e o nome do conector dele. O preparo do acervo os usa
# para reconhecer o CLAUDE.md/AGENTS.md que ele gravou e o usuário não editou
# (e trocá-lo pelo do Helestron, com as regras de citação de agora).
NOME_ANTERIOR = "Assessor Integrado"
CONECTOR_ANTERIOR = "assessor-integrado"


def _pasta_do_acervo(args) -> Path | None:
    """A pasta passada ao conector ('--pasta PASTA'), ou None."""
    if not isinstance(args, list):
        return None
    try:
        pasta = args[args.index("--pasta") + 1]
    except (ValueError, IndexError):
        return None
    return Path(pasta) if isinstance(pasta, str) and pasta.strip() else None


def _mesmo_comando(a, b) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def reapontar_conectores(forcar: bool = False) -> list[str]:
    """O conector do Helestron registrado com o python.exe de outra pasta
    (a instalação anterior, antes de mudar de lugar) passa a usar o desta
    instalação, mantendo a pasta do acervo. Só no programa instalado (ou
    com 'forcar', nos testes). Arquivo inválido não é tocado; nunca levanta.
    Devolve o que foi feito, em frases."""
    from ..nucleo import caminhos

    if not (caminhos.INSTALADO or forcar):
        return []
    feito: list[str] = []
    try:
        from . import claude

        for arq in claude.arquivos_config_desktop():
            try:
                dados = claude._ler_json(arq)
            except (OSError, ValueError):
                continue
            servidores = dados.get("mcpServers")
            atual = servidores.get(claude.NOME_MCP) if isinstance(servidores, dict) else None
            if not isinstance(atual, dict):
                continue
            pasta = _pasta_do_acervo(atual.get("args"))
            if pasta is None:
                continue
            nova = claude.entrada_mcp(pasta)
            if _mesmo_comando(atual.get("command"), nova["command"]):
                continue
            servidores[claude.NOME_MCP] = nova
            try:
                claude._gravar_json(arq, dados)
            except OSError as erro:
                log.warning("não consegui reapontar o conector em %s (%s)", arq, erro)
                continue
            feito.append(f"Conector do Claude Desktop reapontado para esta instalação ({arq}); "
                         "o arquivo anterior foi guardado ao lado.")
    except Exception as erro:  # noqa: BLE001 - arquivo de outro programa
        log.warning("não consegui reapontar o conector do Claude Desktop: %s", erro)
    try:
        import tomllib

        from . import chatgpt

        arquivo = chatgpt.arquivo_config_codex()
        try:
            dados = tomllib.loads(arquivo.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            dados = {}
        servidores = dados.get("mcp_servers")
        atual = servidores.get(chatgpt.NOME_MCP) if isinstance(servidores, dict) else None
        if isinstance(atual, dict):
            pasta = _pasta_do_acervo(atual.get("args"))
            if pasta is not None and not _mesmo_comando(
                    atual.get("command"), chatgpt.entrada_mcp(pasta)["command"]):
                # só o comando muda: o conector desligado (enabled = false)
                # continua desligado, e as outras chaves do bloco ficam
                chatgpt.registrar_mcp_codex(pasta, arquivo, manter=atual)
                feito.append("Conector do ChatGPT/Codex reapontado para esta instalação "
                             f"({arquivo}); o arquivo anterior foi guardado ao lado.")
    except Exception as erro:  # noqa: BLE001
        log.warning("não consegui reapontar o conector do ChatGPT/Codex: %s", erro)
    return feito


def limpar_restos_antigos() -> list[str]:
    """Tira os conectores da versão anterior do Claude Desktop e do
    Codex/ChatGPT Work e reaponta o do Helestron que ficou com o python.exe
    de outra pasta. Nunca levanta. Devolve o que foi feito, em frases
    (vazia: nada a limpar)."""
    feito: list[str] = []
    try:
        from . import claude

        for arquivo in claude.remover_conectores_antigos():
            feito.append(f"Conector da versão anterior retirado do Claude Desktop ({arquivo}); "
                         "o arquivo anterior foi guardado ao lado.")
    except Exception as erro:  # noqa: BLE001 - arquivo de outro programa
        log.warning("não consegui limpar o conector antigo do Claude Desktop: %s", erro)
    try:
        from . import chatgpt

        if chatgpt.remover_conectores_antigos_codex():
            feito.append("Conector da versão anterior retirado do ChatGPT/Codex "
                         f"({chatgpt.arquivo_config_codex()}); o arquivo anterior foi guardado "
                         "ao lado.")
    except Exception as erro:  # noqa: BLE001
        log.warning("não consegui limpar o conector antigo do ChatGPT/Codex: %s", erro)
    feito += reapontar_conectores()
    for frase in feito:
        log.info(frase)
    return feito


def main(argv: list[str] | None = None) -> int:
    """Linha de comando do instalador: imprime o que foi feito; sai com 0."""
    try:
        feito = limpar_restos_antigos()
    except Exception as erro:  # noqa: BLE001 - nunca impedir a instalação
        print(f"Limpeza da versão anterior não concluída: {erro}")
        return 0
    try:
        print("\n".join(feito) if feito else "Nada da versão anterior a limpar.")
    except (UnicodeEncodeError, OSError):
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover - chamado pelo instalador
    sys.exit(main())
