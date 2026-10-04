"""O aplicativo Helestron: abertura, janela, instância única, integridade e autoteste.

    inicio.py        main(): instância única → integridade → servidor → janela → monitor
    instancia.py     um Helestron aberto por usuário (trava + instancia.json + /api/ping)
    integridade.py   o manifesto.json da instalação (rápido ao abrir; hash na verificação)
    erro.py          a tela de erro própria (arquivo que falta, antivírus, Reparar)
    janela.py        WebView2 (pywebview) → Edge em modo aplicativo → navegador padrão
    monitor.py       o monitor da pauta (seção 8.7 da especificação)
    autoteste.py     --autoteste: percurso da interface e capturas da janela
    verificacao.py   --verificar-instalacao: a conferência que o instalador roda

Só biblioteca padrão neste arquivo: mensagem_nativa() precisa funcionar com
a instalação quebrada.
"""

from __future__ import annotations

import sys


def mensagem_nativa(titulo: str, texto: str, erro: bool = True) -> None:
    """Caixa de mensagem do Windows (ou stderr fora dele). Último recurso,
    quando nem a tela de erro própria pode abrir."""
    if sys.platform == "win32":
        try:
            import ctypes

            icone = 0x10 if erro else 0x40                 # MB_ICONERROR | MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(None, texto, titulo, icone | 0x40000)  # TOPMOST
            return
        except Exception:
            pass
    try:
        print(f"{titulo}\n\n{texto}", file=sys.stderr, flush=True)
    except Exception:
        pass
