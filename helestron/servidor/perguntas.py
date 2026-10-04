"""As perguntas abertas: o motor pede um dado e a página responde.

O padrão é o de helestron.tarefas (seção 6.5 da especificação): a thread de
trabalho cria uma Pergunta e BLOQUEIA em pergunta.esperar(); este gerente
publica o evento 'pergunta', guarda a pergunta até ela se fechar e entrega
a resposta que chega por POST /api/perguntas/{id}/responder. Prazo esgotado,
tarefa parada ou cancelamento fecham a pergunta, e o evento
'pergunta_fechada' tira a folha da tela.

A página que recarrega (ou reconecta) no meio de uma pergunta recebe de
novo as que estão abertas, com o prazo que ainda resta: sem isso, o
download ficaria esperando um código que ninguém mais vê.
"""

from __future__ import annotations

import logging
import threading

from ..tarefas import RESPONDIDA, TIPOS_PERGUNTA, Pergunta

log = logging.getLogger("servidor.perguntas")

LIMITE_RESPOSTA = 2000


class PerguntaInexistente(LookupError):
    """Não há (nem houve, neste programa aberto) pergunta com esse id."""


class PerguntaFechada(RuntimeError):
    """A pergunta existiu, mas já foi respondida, cancelada ou expirou."""


class GerentePerguntas:
    def __init__(self, publicar):
        self._publicar = publicar
        self._trava = threading.Lock()
        self._abertas: dict[str, tuple[Pergunta, str | None]] = {}
        self._fechadas: dict[str, str] = {}       # id -> motivo (as últimas)

    # ------------------------------------------------------------- abrir
    def abrir(self, pergunta: Pergunta, tarefa: str | None = None) -> Pergunta:
        """Registra a pergunta e avisa as páginas. Não bloqueia: quem espera
        a resposta é a thread de trabalho (pergunta.esperar())."""
        if pergunta.tipo not in TIPOS_PERGUNTA:
            raise ValueError(f"tipo de pergunta desconhecido: {pergunta.tipo}")
        anterior = pergunta.ao_fechar

        def ao_fechar(p: Pergunta) -> None:
            self._fechou(p)
            if anterior is not None:
                anterior(p)

        pergunta.ao_fechar = ao_fechar
        with self._trava:
            self._abertas[pergunta.id] = (pergunta, tarefa)
        if not pergunta.aberto:            # fechada antes de registrar (corrida)
            self._fechou(pergunta)
            return pergunta
        log.info("pergunta %s (%s): %s", pergunta.id, pergunta.tipo, pergunta.titulo)
        self._publicar("pergunta", self._evento(pergunta, tarefa))
        return pergunta

    @staticmethod
    def _evento(pergunta: Pergunta, tarefa: str | None) -> dict:
        dados = pergunta.como_dict()
        dados["tarefa"] = tarefa
        return dados

    def _fechou(self, pergunta: Pergunta) -> None:
        with self._trava:
            existia = self._abertas.pop(pergunta.id, None) is not None
            self._fechadas[pergunta.id] = pergunta.motivo or RESPONDIDA
            if len(self._fechadas) > 200:
                for chave in list(self._fechadas)[:100]:
                    self._fechadas.pop(chave, None)
        if existia:
            self._publicar("pergunta_fechada", {"id": pergunta.id,
                                                "motivo": pergunta.motivo or RESPONDIDA})

    # ---------------------------------------------------------- responder
    def _pegar(self, id_pergunta: str) -> Pergunta:
        with self._trava:
            par = self._abertas.get(id_pergunta)
            fechada = id_pergunta in self._fechadas
        if par is None:
            if fechada:
                raise PerguntaFechada(id_pergunta)
            raise PerguntaInexistente(id_pergunta)
        return par[0]

    def responder(self, id_pergunta: str, valor) -> Pergunta:
        pergunta = self._pegar(id_pergunta)
        valor = normalizar_resposta(pergunta, valor)
        if not pergunta.responder(valor):
            raise PerguntaFechada(id_pergunta)
        return pergunta

    def cancelar(self, id_pergunta: str) -> Pergunta:
        pergunta = self._pegar(id_pergunta)
        if not pergunta.cancelar():
            raise PerguntaFechada(id_pergunta)
        return pergunta

    def cancelar_da_tarefa(self, tarefa: str) -> None:
        """A tarefa foi parada: as perguntas dela se fecham já (a thread de
        trabalho também veria o Parar, mas só na próxima fatia de espera)."""
        with self._trava:
            alvos = [p for p, t in self._abertas.values() if t == tarefa]
        for p in alvos:
            p.cancelar_pelo_trabalho()

    def cancelar_todas(self) -> None:
        with self._trava:
            alvos = [p for p, _ in self._abertas.values()]
        for p in alvos:
            p.cancelar_pelo_trabalho()

    # ------------------------------------------------------------ consulta
    def abertas(self) -> list[dict]:
        """As perguntas abertas, para a página que acabou de conectar."""
        with self._trava:
            pares = list(self._abertas.values())
        return [self._evento(p, t) for p, t in pares if p.aberto]


def normalizar_resposta(pergunta: Pergunta, valor):
    """A resposta no tipo que o motor espera.

    Código e texto: sempre texto, sem espaços nas pontas ("" = pedir um
    código novo). Confirmação: booleano. Escolha: uma das opções oferecidas.
    """
    if pergunta.tipo == "confirmar":
        if isinstance(valor, str):
            return valor.strip().lower() in ("1", "true", "sim", "s", "ok", "yes")
        return bool(valor)
    if valor is None:
        valor = ""
    texto = str(valor).strip()[:LIMITE_RESPOSTA]
    if pergunta.tipo == "codigo":
        # O e-mail do e-SAJ traz o código com espaço no meio às vezes
        # ("123 456"); o portal quer os dígitos juntos.
        return "".join(texto.split())
    if pergunta.tipo == "escolha":
        opcoes = [str(o) for o in (pergunta.opcoes or []) if not isinstance(pergunta.opcoes, dict)]
        if opcoes and texto not in opcoes:
            raise ValueError("escolha uma das opções oferecidas")
    return texto
