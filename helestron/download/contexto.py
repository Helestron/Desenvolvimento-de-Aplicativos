"""A ponte entre o motor de download e quem o acompanha (interface ou terminal).

O motor roda numa thread de trabalho e nunca toca na interface: tudo o que
ele quer dizer ou perguntar passa por um Contexto. O servidor do programa
(helestron/tarefas.py) implementa uma subclasse que publica eventos para a
interface e responde ``pedir_codigo`` com um threading.Event (a pergunta
aparece numa folha da janela); o terminal usa ContextoTerminal.

No Assessor SAJ o código de verificação do e-SAJ chegava por um arquivo
(runtime\\codigo-esaj.txt) e a janela só sabia que devia pedi-lo lendo o
TEXTO do log - qualquer mensagem de erro que mencionasse "código de
validação" acendia a caixa, e sob python.exe o programa ficava esperando o
código no console enquanto o usuário o digitava na janela. Aqui o pedido é
uma chamada explícita, que bloqueia a thread até a resposta.

A classe base é utilizável como está (não faz nada e nunca cancela): serve
para testes e para usos sem acompanhamento.

Além das frases para gente, o motor e os portais emitem EVENTOS legíveis por
máquina (``evento(tipo, **dados)``): o início de cada grupo, o login que
espera o usuário na janela, o login recusado, a sessão que caiu, o fim. A
base os ignora; o terminal, com ``eventos=True`` (``baixar --eventos``), os
imprime numa linha própria - ``HELESTRON-EVENTO {json}`` - e os repassa ao
acompanhamento em JSON (``baixar --json``, download/acompanhamento.py).
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from datetime import datetime

from .modelos import ResultadoProcesso, rotulo

log = logging.getLogger("download.contexto")


class Contexto:
    """Interface que o motor e os portais usam para falar com o usuário."""

    def status(self, texto: str) -> None:
        """Frase curta do que está acontecendo agora ("Entrando no e-SAJ...")."""

    def progresso(self, feitos: int, total: int, atual: str) -> None:
        """Quantos itens já terminaram, de quantos, e qual está em curso."""

    def item(self, r: ResultadoProcesso) -> None:
        """Uma linha da tabela mudou (situação, páginas, detalhe...)."""

    def cancelado(self) -> bool:
        """O usuário pediu para parar? Consultado com frequência pelo motor."""
        return False

    def pedir_codigo(self, titulo: str, mensagem: str, prazo_s: int = 600,
                     reenviavel: bool = True) -> str | None:
        """Pede ao usuário o código de verificação e BLOQUEIA até a resposta.

        Devolve o código digitado; ``""`` quando o usuário pede um código
        novo (o anterior vale poucos minutos); ``None`` quando ele cancela,
        fecha o diálogo ou o prazo acaba.

        ``reenviavel``: dá para pedir outro código ao portal? Sim para o
        enviado por e-mail (e-SAJ); não para o do aplicativo autenticador
        (eProc), que muda sozinho a cada 30 segundos - aí quem acompanha
        não oferece "pedir novo código".
        """
        return None

    def avisar(self, titulo: str, mensagem: str) -> None:
        """Recado que pede atenção, sem bloquear (ex.: "Conclua o login na
        janela do navegador")."""
        log.warning("%s: %s", titulo, mensagem)

    def evento(self, tipo: str, **dados) -> None:
        """Um acontecimento legível por máquina (tipos em EVENTOS). Na base,
        nada: a tela e os testes não precisam dele. Nunca deve levantar."""


# Os eventos que o motor e os portais emitem, com os dados de cada um:
#   lote_inicio       destino, relatorio, sigilosos_do_lote, total
#   grupo_inicio      sistema, tribunal, alternativo (bool), ordens (lista)
#   navegador_ocupado sistema, tribunal, ate (ISO), motivo: esperando o navegador
#                     do portal abrir (outro_download: outro download o usa;
#                     copia_antiga_presa: a cópia antiga do perfil não saiu)
#   login_aguardando  sistema, tribunal, modo, prazo_min, ate (ISO), motivo
#   acao_na_janela    sistema, tribunal, motivo (captcha, perfil...)
#   login_concluido   sistema, tribunal
#   login_falhou      sistema, tribunal, detalhe
#   sessao_caiu       sistema, tribunal, ordem
#   fim               total, baixados, ja_baixados, falhas, pendentes, sigilosos
# No 2º grau, os eventos de grupo e de login (grupo_inicio, navegador_ocupado,
# login_aguardando, acao_na_janela, login_concluido, login_falhou, sessao_caiu)
# levam também grau="2g"; no 1º grau o campo não vai (ausente = 1º grau).
EVENTOS = ("lote_inicio", "grupo_inicio", "navegador_ocupado", "login_aguardando",
           "acao_na_janela", "login_concluido", "login_falhou", "sessao_caiu", "fim")
PREFIXO_EVENTO = "HELESTRON-EVENTO "


def linha_de_evento(tipo: str, dados: dict) -> str:
    """'HELESTRON-EVENTO {"tipo": ..., "momento": ..., ...}' numa linha só."""
    corpo = {"tipo": tipo, "momento": datetime.now().isoformat(timespec="seconds")}
    corpo.update({k: v for k, v in dados.items() if k not in corpo})
    return PREFIXO_EVENTO + json.dumps(corpo, ensure_ascii=False, default=str)


class ContextoTerminal(Contexto):
    """Acompanhamento pelo console: print e input().

    Ctrl+C durante o lote é tratado pelo motor como "parar": o item em curso
    volta para a fila e o relatório é gravado.

    ``eventos``: imprime cada evento como ``HELESTRON-EVENTO {json}`` (sem
    ele, a saída é a de sempre). ``acompanhamento``: quem mais quer saber de
    cada item, evento e aviso (o JSON de ``baixar --json``); falha dele nunca
    derruba o lote.
    """

    def __init__(self, saida=None, entrada=None, eventos: bool = False, acompanhamento=None):
        self._saida = saida
        self._entrada = entrada          # para testes: função que faz as vezes de input()
        self._parar = threading.Event()
        self._ultimo_status = ""
        self.eventos = bool(eventos)
        self.acompanhamento = acompanhamento

    def _repassar(self, metodo: str, *args, **kwargs) -> None:
        alvo = getattr(self.acompanhamento, metodo, None) if self.acompanhamento else None
        if alvo is None:
            return
        try:
            alvo(*args, **kwargs)
        except Exception:        # o acompanhamento nunca derruba o lote
            log.debug("acompanhamento.%s falhou", metodo, exc_info=True)

    # --------------------------------------------------------------- saída
    def _print(self, texto: str) -> None:
        destino = self._saida or sys.stdout
        if destino is None:      # pythonw: sem console
            return
        try:
            print(texto, file=destino, flush=True)
        except (OSError, ValueError, UnicodeEncodeError):
            pass

    def status(self, texto: str) -> None:
        if texto and texto != self._ultimo_status:
            self._ultimo_status = texto
            self._repassar("status", texto)
            self._print(f"  {texto}")

    def progresso(self, feitos: int, total: int, atual: str) -> None:
        # O motor já registra "[n/total] número" no log, que no terminal
        # aparece na tela; repetir aqui só duplicaria a linha.
        self._repassar("progresso", feitos, total, atual)

    def item(self, r: ResultadoProcesso) -> None:
        self._repassar("item", r)
        if not r.situacao:
            return
        extra = []
        if r.paginas:
            extra.append(f"{r.paginas} página{'s' if r.paginas != 1 else ''}")
        if r.sigiloso:
            extra.append("sigiloso")
        if r.incompleto:
            # No eProc faltam documentos (eventos); no e-SAJ, folhas numeradas.
            extra.append(f"documentos ausentes: {r.incompleto}" if r.sistema == "eproc"
                         else f"folhas ausentes: {r.incompleto}")
        if r.detalhe:
            extra.append(r.detalhe)
        sufixo = f" ({'; '.join(extra)})" if extra else ""
        self._print(f"    -> {r.numero}: {r.rotulo}{sufixo}")

    def avisar(self, titulo: str, mensagem: str) -> None:
        self._repassar("aviso", titulo, mensagem)
        self._print("")
        self._print(f"  *** {titulo} ***")
        self._print(f"  {mensagem}")
        self._print("")

    def evento(self, tipo: str, **dados) -> None:
        if self.eventos:
            try:
                self._print(linha_de_evento(tipo, dados))
            except Exception:     # dado que não vira JSON nunca derruba o lote
                log.debug("evento %s não impresso", tipo, exc_info=True)
        self._repassar("evento", tipo, **dados)

    # -------------------------------------------------------------- parar
    def parar(self) -> None:
        self._parar.set()

    def cancelado(self) -> bool:
        return self._parar.is_set()

    # ------------------------------------------------------------- código
    def _ler(self, prompt: str) -> str:
        if self._entrada is not None:
            return self._entrada(prompt)
        return input(prompt)

    def pedir_codigo(self, titulo: str, mensagem: str, prazo_s: int = 600,
                     reenviavel: bool = True) -> str | None:
        self.avisar(titulo, mensagem)
        try:
            interativo = self._entrada is not None or bool(sys.stdin and sys.stdin.isatty())
        except (AttributeError, ValueError):
            interativo = False
        if not interativo:
            # Sem ninguém ao teclado (tarefa agendada, saída redirecionada):
            # esperar input() seria esperar para sempre.
            self._print("  Não há terminal para digitar o código: digite-o na janela do "
                        "navegador, se ela estiver aberta (sem ela, rode de novo num "
                        "Prompt de Comando ou use o programa pela janela).")
            return None
        # O código do aplicativo autenticador não se pede de novo: o próprio
        # aplicativo mostra outro a cada 30 segundos. Enter em branco, aí,
        # só faz o programa perguntar outra vez.
        convite = ("  Código recebido (Enter em branco pede outro; 'sair' cancela): "
                   if reenviavel else
                   "  Código do aplicativo ('sair' cancela): ")
        try:
            texto = self._ler(convite)
        except KeyboardInterrupt:
            # Ctrl+C aqui é "parar", como no resto do lote - e não "não tenho
            # o código", que encerraria só este tribunal e seguiria adiante.
            self.parar()
            return None
        except (EOFError, OSError):
            return None
        texto = (texto or "").strip()
        if texto.lower() in ("sair", "cancelar"):
            return None
        return texto


def descrever(r: ResultadoProcesso) -> str:
    """Linha legível de um resultado, para log e terminal."""
    return f"{r.numero} - {rotulo(r.situacao)}" + (f" ({r.detalhe})" if r.detalhe else "")
