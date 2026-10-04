"""Captura assistida: o usuário mostra a pauta, o Helestron lê (seção 8.4).

Para quando a descoberta automática não acha a pauta, ou o tribunal tem
tela própria. O portal abre no navegador VISÍVEL, com o perfil e a sessão
do download (já logado), e uma barra discreta aparece no topo de cada
página:

    Helestron — vá até a pauta de audiências e clique em "Capturar esta tela"
    [Capturar esta tela]  [Concluir]

Cada clique lê as tabelas da página atual (e dos frames), diz na própria
barra quantas audiências reconheceu e acumula; o usuário pode ir à página
seguinte e capturar de novo. "Concluir" grava tudo, e a URL da pauta fica
lembrada como rota da fonte - o monitoramento automático passa a usá-la.

Como a barra fala com o Python: add_init_script (a barra renasce a cada
página, em todas as abas) + expose_binding. A função exposta só ENFILEIRA o
pedido e responde na hora; quem lê a página é o laço de espera, na thread
da tarefa. Chamar o Playwright de dentro da função exposta trava a API
síncrona (a chamada aninhada espera o despachante que está ocupado com
ela) - o teste disso está em testes/test_pauta_captura.py. A resposta volta
à barra por window.__helestronResposta.

A barra vive num shadow DOM: o CSS do portal não a deforma, e o dela não
mexe no portal.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..download.modelos import Cancelado
from .navegacao import LeitorDePauta, _avaliar
from .tabelas import Reconhecedor, Reconhecimento

log = logging.getLogger("pauta.captura")

NOME_LIGACAO = "helestronPauta"
LIMITE_PADRAO_S = 30 * 60          # meia hora sem "Concluir": grava o que tiver
INTERVALO_MS = 250

BARRA_JS = r"""(() => {
  if (window.top !== window) return;
  if (window.__helestronBarraInstalada) return;
  window.__helestronBarraInstalada = true;
  const CHAVE = "helestron-captura";
  const montar = () => {
    if (document.getElementById("helestron-barra")) return;
    const host = document.createElement("div");
    host.id = "helestron-barra";
    host.setAttribute("style", "all: initial; position: fixed; top: 10px; left: 50%; transform: translateX(-50%); z-index: 2147483647;");
    const raiz = host.attachShadow({mode: "open"});
    raiz.innerHTML = `
      <style>
        :host { all: initial; }
        .barra { font: 14px/1.35 Inter, "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
                 color: #0B1A33; display: flex; align-items: center; gap: 10px; padding: 8px 10px 8px 12px;
                 background: rgba(255,255,255,.86); backdrop-filter: blur(20px) saturate(180%);
                 -webkit-backdrop-filter: blur(20px) saturate(180%); border: 1px solid rgba(255,255,255,.75);
                 border-radius: 16px; box-shadow: 0 8px 32px rgba(11,26,51,.18), 0 1px 0 rgba(11,26,51,.06);
                 max-width: min(920px, calc(100vw - 24px)); }
        .marca { flex: none; width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center;
                 font-weight: 700; color: #fff; background: linear-gradient(160deg, #1B3560, #0B1A33); }
        .texto { flex: 1 1 auto; min-width: 0; }
        .texto.ocupado { color: #6B7280; }
        .texto.sucesso { color: #1F7A45; }
        .texto.erro { color: #B32F2F; }
        button { font: inherit; font-weight: 600; border-radius: 10px; border: 0; padding: 7px 12px; cursor: pointer;
                 background: #E8F1FF; color: #0A4FB8; white-space: nowrap; }
        button.principal { background: #0A66E8; color: #fff; }
        button:disabled { opacity: .55; cursor: default; }
        button:focus-visible { outline: 3px solid rgba(10,102,232,.45); outline-offset: 2px; }
        button.discreto { background: transparent; color: #6B7280; padding: 6px 8px; }
        .recolhida .texto, .recolhida #capturar, .recolhida #concluir { display: none; }
      </style>
      <div class="barra" id="barra" role="region" aria-label="Helestron: captura da pauta de audiências">
        <span class="marca" aria-hidden="true">H</span>
        <span class="texto" id="texto" role="status" aria-live="polite">Helestron — vá até a pauta de audiências e clique em <b>Capturar esta tela</b>.</span>
        <button id="capturar" class="principal" type="button">Capturar esta tela</button>
        <button id="concluir" type="button">Concluir</button>
        <button id="recolher" class="discreto" type="button" title="Recolher a barra" aria-label="Recolher a barra">–</button>
      </div>`;
    (document.body || document.documentElement).appendChild(host);
    const $ = (id) => raiz.getElementById(id);
    const mostrar = (mensagem, tipo) => {
      const t = $("texto");
      t.textContent = mensagem;
      t.className = "texto " + (tipo || "");
    };
    try {
      const salvo = JSON.parse(sessionStorage.getItem(CHAVE) || "null");
      if (salvo && salvo.total) {
        mostrar("Helestron — " + salvo.total + (salvo.total === 1 ? " audiência capturada" : " audiências capturadas") +
                " até agora. Capture outra tela ou clique em Concluir.", "");
      }
    } catch (_e) {}
    window.__helestronResposta = (r) => {
      $("capturar").disabled = false;
      $("concluir").disabled = !!r.fim;
      mostrar(r.mensagem || "", r.tipo || "");
      try { sessionStorage.setItem(CHAVE, JSON.stringify({total: r.total || 0})); } catch (_e) {}
    };
    const pedir = async (acao) => {
      try {
        await window.helestronPauta({acao});
      } catch (_e) {
        $("capturar").disabled = false;
        $("concluir").disabled = false;
        mostrar("Não consegui falar com o Helestron. Confira se ele está aberto e tente de novo.", "erro");
      }
    };
    $("capturar").addEventListener("click", () => {
      $("capturar").disabled = true;
      mostrar("Lendo esta tela…", "ocupado");
      pedir("capturar");
    });
    $("concluir").addEventListener("click", () => {
      $("capturar").disabled = true;
      $("concluir").disabled = true;
      mostrar("Gravando a pauta no Helestron…", "ocupado");
      pedir("concluir");
    });
    $("recolher").addEventListener("click", () => {
      const barra = $("barra");
      barra.classList.toggle("recolhida");
      const recolhida = barra.classList.contains("recolhida");
      $("recolher").textContent = recolhida ? "H+" : "–";
      $("recolher").setAttribute("aria-label", recolhida ? "Mostrar a barra" : "Recolher a barra");
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", montar);
  else montar();
})();"""

JS_RESPONDER = "(r) => { if (window.__helestronResposta) window.__helestronResposta(r); }"


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


@dataclass
class ResultadoCaptura:
    reconhecimento: Reconhecimento = field(default_factory=Reconhecimento)
    telas: int = 0                 # cliques em "Capturar" que acharam a pauta
    url: str = ""                  # onde a pauta foi reconhecida (a rota a lembrar)
    motivo: str = ""               # "concluida" | "fechada" | "prazo"

    @property
    def audiencias(self):
        return self.reconhecimento.audiencias


class CapturaAssistida:
    """A barra no navegador e o laço que atende os cliques."""

    def __init__(self, nav, regras, reconhecedor: Reconhecedor, ctx=None,
                 limite_s: float = LIMITE_PADRAO_S, nome: str = "portal"):
        self.nav = nav
        self.regras = regras
        self.reconhecedor = reconhecedor
        self.ctx = ctx
        self.limite_s = float(limite_s)
        self.nome = nome
        self.fila: list[tuple[object, str]] = []
        self.resultado = ResultadoCaptura()

    # ---------------------------------------------------------- instalação
    def instalar(self) -> None:
        contexto = self.nav.contexto
        contexto.expose_binding(NOME_LIGACAO, self._ligacao)
        contexto.add_init_script(script=BARRA_JS)
        for pagina in self._paginas():
            _avaliar(pagina, BARRA_JS)        # a página já aberta (o init só vale nas próximas)

    def _ligacao(self, origem, pedido=None):
        """Chamada pela barra. NÃO chama o Playwright (travaria): só enfileira."""
        acao = pedido.get("acao") if isinstance(pedido, dict) else str(pedido or "")
        pagina = origem.get("page") if isinstance(origem, dict) else None
        self.fila.append((pagina, str(acao or "")))
        return {"recebido": True}

    # ---------------------------------------------------------------- laço
    def _paginas(self) -> list:
        try:
            return [p for p in self.nav.contexto.pages if not p.is_closed()]
        except Exception:
            return []

    def _status(self, texto: str) -> None:
        if self.ctx is not None:
            try:
                self.ctx.status(texto)
            except Exception:
                pass

    def esperar(self) -> ResultadoCaptura:
        """Atende a barra até "Concluir", o navegador fechar, o prazo ou o Parar."""
        limite = time.monotonic() + self.limite_s
        while True:
            if self.ctx is not None and self.ctx.cancelado():
                raise Cancelado()
            if time.monotonic() > limite:
                self.resultado.motivo = "prazo"
                log.info("Captura: o prazo de %d minutos acabou; gravo o que foi capturado.",
                         int(self.limite_s // 60))
                break
            paginas = self._paginas()
            if not paginas:
                self.resultado.motivo = "fechada"
                break
            try:
                paginas[-1].wait_for_timeout(INTERVALO_MS)    # deixa os eventos chegarem
            except Exception:
                time.sleep(INTERVALO_MS / 1000)
            while self.fila:
                pagina, acao = self.fila.pop(0)
                if acao == "capturar":
                    self.capturar(pagina)
                elif acao == "concluir":
                    self.resultado.motivo = "concluida"
            if self.resultado.motivo == "concluida":
                total = len(self.resultado.audiencias)
                gravadas = _plural(total, "audiência gravada", "audiências gravadas")
                self._responder(None, {
                    "mensagem": (f"Pronto: {gravadas} no Helestron. Pode fechar esta janela."
                                 if total else "Nada foi capturado. Pode fechar esta janela."),
                    "tipo": "sucesso" if total else "", "total": total, "fim": True})
                break
        return self.resultado

    def _responder(self, pagina, resposta: dict) -> None:
        alvos = [pagina] if pagina is not None else self._paginas()
        for p in alvos:
            _avaliar(p, JS_RESPONDER, resposta)

    def capturar(self, pagina) -> dict:
        """Lê a tela atual e acumula. Devolve a resposta mostrada na barra."""
        if pagina is None or (hasattr(pagina, "is_closed") and pagina.is_closed()):
            return {}
        leitor = LeitorDePauta(pagina, self.regras, self.reconhecedor, self.ctx, 5.0, self.nome)
        rec, _frame = leitor.reconhecer()
        acumulado = self.resultado.reconhecimento
        antes = {a.id for a in acumulado.audiencias}
        if rec.reconhecida:
            acumulado.juntar(rec)
            acumulado.total_informado = None
            self.resultado.telas += 1
            if not self.resultado.url:
                try:
                    self.resultado.url = pagina.url or ""
                except Exception:
                    pass
        total = len(acumulado.audiencias)
        novas = len({a.id for a in rec.audiencias} - antes)
        reconhecidas = lambda n: _plural(n, "audiência reconhecida",  # noqa: E731
                                         "audiências reconhecidas")
        if not rec.reconhecida:
            mensagem = ("Não encontrei a tabela de audiências nesta tela. Abra a pauta de "
                        "audiências, com a lista na tela, e clique de novo.")
            resposta = {"mensagem": mensagem, "tipo": "erro", "total": total}
        elif not rec.audiencias:
            mensagem = ("A tabela da pauta está vazia nesta tela. Mude o período ou a página e "
                        "capture de novo.")
            resposta = {"mensagem": mensagem, "tipo": "", "total": total}
        else:
            lidas = len(rec.audiencias)
            repetidas = lidas - novas
            extra = f" ({_plural(repetidas, 'já capturada', 'já capturadas')})" if repetidas else ""
            mensagem = (f"{reconhecidas(lidas)} nesta tela{extra}. Total: {total}. Vá à próxima "
                        "página e capture de novo, ou clique em Concluir.")
            resposta = {"mensagem": mensagem, "tipo": "sucesso", "total": total}
        telas = _plural(self.resultado.telas, "tela", "telas")
        self._status(f"Captura: {reconhecidas(total)} em {telas}. Clique em “Concluir” na barra "
                     "do Helestron quando terminar.")
        self._responder(pagina, resposta)
        return resposta
