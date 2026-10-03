"""A ponte entre o motor de download e quem o acompanha (janela ou terminal).

O motor roda numa thread de trabalho e nunca toca na interface: tudo o que
ele quer dizer ou perguntar passa por um Contexto. A janela implementa uma
subclasse que põe eventos numa fila (lida pelo Tk com after()) e responde
``pedir_codigo`` com um threading.Event; o terminal usa ContextoTerminal.

No Assessor SAJ o código de verificação do e-SAJ chegava por um arquivo
(runtime\\codigo-esaj.txt) e a janela só sabia que devia pedi-lo lendo o
TEXTO do log - qualquer mensagem de erro que mencionasse "código de
validação" acendia a caixa, e sob python.exe o programa ficava esperando o
código no console enquanto o usuário o digitava na janela. Aqui o pedido é
uma chamada explícita, que bloqueia a thread até a resposta.

A classe base é utilizável como está (não faz nada e nunca cancela): serve
para testes e para usos sem acompanhamento.
"""

from __future__ import annotations

import logging
import sys
import threading

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


class ContextoTerminal(Contexto):
    """Acompanhamento pelo console: print e input().

    Ctrl+C durante o lote é tratado pelo motor como "parar": o item em curso
    volta para a fila e o relatório é gravado.
    """

    def __init__(self, saida=None, entrada=None):
        self._saida = saida
        self._entrada = entrada          # para testes: função que faz as vezes de input()
        self._parar = threading.Event()
        self._ultimo_status = ""

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
            self._print(f"  {texto}")

    def progresso(self, feitos: int, total: int, atual: str) -> None:
        # O motor já registra "[n/total] número" no log, que no terminal
        # aparece na tela; repetir aqui só duplicaria a linha.
        pass

    def item(self, r: ResultadoProcesso) -> None:
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
        self._print("")
        self._print(f"  *** {titulo} ***")
        self._print(f"  {mensagem}")
        self._print("")

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
            self._print("  Não há terminal para digitar o código. Rode de novo "
                        "num Prompt de Comando, ou use o programa pela janela.")
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
