"""Impede o computador de dormir enquanto há trabalho em andamento.

Herdado do Assessor SAJ. Um lote de downloads ou uma audiência longa levam
horas. Se o Windows suspender a máquina no meio, o
trabalho fica parado até alguém mexer no mouse - aconteceu numa fila que
dormiu das 3h25 às 8h06 e só então terminou.

Isto não mexe na configuração de energia do usuário: apenas avisa ao Windows,
enquanto o bloco durar, que há algo em andamento. Ao sair, tudo volta ao
normal - inclusive se o programa fechar de qualquer jeito.
"""

from __future__ import annotations

import ctypes
import logging
from contextlib import contextmanager

log = logging.getLogger("energia")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040


@contextmanager
def manter_acordado(motivo: str = "trabalho em andamento"):
    """Enquanto o bloco durar, o Windows não suspende a máquina.

    A tela pode apagar normalmente - só o desligamento do sistema é adiado.
    """
    ligado = False
    # O estado vale para a thread que chamou: use o bloco DENTRO da thread
    # de trabalho, não na da janela.
    try:
        estado = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        if ctypes.windll.kernel32.SetThreadExecutionState(estado) == 0:
            # sem o modo "ausente", que nem toda máquina aceita
            estado = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            ligado = ctypes.windll.kernel32.SetThreadExecutionState(estado) != 0
        else:
            ligado = True
        if ligado:
            log.info("  o computador vai ficar acordado (%s).", motivo)
    except Exception as erro:
        log.debug("não consegui impedir a suspensão: %s", erro)

    try:
        yield
    finally:
        if ligado:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:
                pass
