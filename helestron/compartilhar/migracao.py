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
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("compartilhar.migracao")


def limpar_restos_antigos() -> list[str]:
    """Tira os conectores da versão anterior do Claude Desktop e do
    Codex/ChatGPT Work. Nunca levanta. Devolve o que foi feito, em frases
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
