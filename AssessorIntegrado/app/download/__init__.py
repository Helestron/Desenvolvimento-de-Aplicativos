"""Baixar processos: um PDF por processo, a partir do login do próprio usuário.

Módulos:
  modelos    exceções, situações, opções e resultados (leve: a janela importa)
  contexto   ponte motor <-> tela/terminal (status, progresso, código por e-mail)
  navegador  Playwright: Chrome/Edge/Chromium, perfil, sessão, diagnóstico
  pdf        montagem do PDF único (PyMuPDF), gravação atômica
  esaj       PortalESAJ (login e download no e-SAJ)
  eproc      PortalEProc (mesma interface)
  motor      executar(): percorre a relação, agrupa por tribunal, relatório
  cli        python -m app baixar --lista pauta.xlsx

Nada pesado é importado aqui: Playwright e PyMuPDF só quando usados.
"""

from .modelos import (LoginFalhou, OpcoesDownload, PortalIndisponivel, ResultadoProcesso,
                      ResumoLote, SessaoPerdida, SITUACOES)

__all__ = ["LoginFalhou", "OpcoesDownload", "PortalIndisponivel", "ResultadoProcesso",
           "ResumoLote", "SessaoPerdida", "SITUACOES"]
