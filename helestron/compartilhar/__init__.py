"""Compartilhamento do acervo com o Claude e o ChatGPT (preparo, conector MCP,
pacote, espelho na nuvem)."""


def limpar_restos_antigos() -> list[str]:
    """Tira os conectores da versão anterior do programa do Claude Desktop e
    do Codex/ChatGPT Work, guardando cópia dos arquivos de configuração. O
    instalador chama depois de instalar. Ver migracao.py."""
    from .migracao import limpar_restos_antigos as limpar

    return limpar()
