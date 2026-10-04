"""Todas as rotas da API, montadas num Roteador só.

Imports estáticos de propósito: cada módulo da API é conhecido aqui pelo
nome, e um arquivo que falte na instalação aparece já na verificação
(python -m helestron --verificar-instalacao importa o pacote inteiro), e
não no meio do uso, como o "No module named 'app.interface.pagina_config'"
da versão anterior.
"""

from __future__ import annotations

from . import api_audiencias, api_compartilhar, api_geral, api_pauta, api_processos
from .rede import Roteador


def montar() -> Roteador:
    r = Roteador()
    for modulo in (api_geral, api_processos, api_audiencias, api_pauta, api_compartilhar):
        modulo.registrar(r)
    return r
