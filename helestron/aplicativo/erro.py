"""A tela de erro própria: o programa abriu, mas falta arquivo dele.

Em vez do "No module named ..." cru da versão anterior, a janela mostra o
que falta, a hipótese mais provável (o antivírus pôs o arquivo em
quarentena, ou a instalação foi interrompida), que os dados do usuário não
foram afetados, e o botão Reparar: procura o instalador (Helestron-Setup) na
pasta Downloads e o abre; se não o encontrar, explica como baixá-lo e
reinstalar. O instalador não deixa cópia de si no computador.

Roda no mesmo servidor local (modo de erro: poucas rotas) e na mesma
janela; se nem isso for possível, quem chama mostra a caixa de mensagem
nativa do Windows (helestron.__main__).
"""

from __future__ import annotations

import html
import logging
import os
import secrets
import sys
import threading
import time

from .. import NOME, __version__
from ..nucleo import caminhos, sistema
from ..servidor.eventos import HubEventos
from ..servidor.perguntas import GerentePerguntas
from ..servidor.rede import ErroApi, Pedido, Roteador, ServidorLocal
from . import integridade

log = logging.getLogger("aplicativo.erro")

HIPOTESE = ("Isso costuma acontecer quando o antivírus põe um arquivo em quarentena logo "
            "depois da instalação, ou quando a instalação foi interrompida no meio.")
DADOS_INTACTOS = ("Os seus dados — acervo, transcrições, pauta, configurações e senhas — não "
                  "foram afetados e continuam no computador.")


def instrucoes_reinstalar(pasta) -> str:
    return ("Não encontrei o instalador na pasta Downloads. Baixe de novo o instalador do "
            "Helestron (Helestron-Setup) e execute-o: ele conserta a instalação sem apagar os "
            "seus dados. Se o antivírus bloqueou um arquivo, peça ao suporte de informática que "
            f"libere a pasta {pasta} e reinstale.")


def pagina(problemas: list[integridade.Problema], nonce: str) -> str:
    pasta = integridade.pasta_instalada() or caminhos.LOCAL
    itens = "\n".join(f"<li><code>{html.escape(p.arquivo.replace('/', chr(92)))}</code> — "
                      f"{html.escape(integridade.MOTIVOS.get(p.motivo, p.motivo))}</li>"
                      for p in problemas[:12])
    if len(problemas) > 12:
        itens += f"\n<li>… e mais {len(problemas) - 12} arquivos</li>"
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{NOME} — instalação incompleta</title>
<style nonce="{nonce}">
:root{{--navy-900:#0B1A33;--azul:#0A66E8;--cinza-900:#1C1C1E;--cinza-600:#6B7280;
--cinza-200:#E5E7EB;--vermelho:#D93A3A;--branco:#FFFFFF}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;font:15px/1.5 "Segoe UI Variable","Segoe UI",system-ui,sans-serif;
color:var(--cinza-900);background:radial-gradient(circle at 15% 20%,rgba(10,102,232,.14),transparent 45%),
radial-gradient(circle at 85% 80%,rgba(11,26,51,.10),transparent 50%),linear-gradient(160deg,#FFFFFF,#E8F1FF);
display:flex;align-items:center;justify-content:center;padding:32px}}
main{{max-width:720px;width:100%;background:rgba(255,255,255,.62);backdrop-filter:blur(24px) saturate(180%);
border:1px solid rgba(255,255,255,.7);box-shadow:0 8px 32px rgba(11,26,51,.08);border-radius:20px;padding:32px 36px}}
h1{{margin:0 0 4px;font-size:30px;font-weight:600;color:var(--navy-900)}}
.sub{{margin:0 0 20px;color:var(--cinza-600)}}
ul{{margin:0 0 18px;padding:14px 18px 14px 34px;background:rgba(217,58,58,.06);border-radius:14px;
border:1px solid rgba(217,58,58,.18)}}
li{{margin:4px 0}} code{{font-family:Consolas,"Cascadia Mono",monospace;font-size:13px}}
p{{margin:0 0 12px}}
.acoes{{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}}
button{{font:inherit;border:0;border-radius:12px;padding:10px 18px;cursor:pointer;
background:var(--cinza-200);color:var(--cinza-900)}}
button.principal{{background:var(--azul);color:var(--branco);font-weight:600}}
button:focus-visible{{outline:3px solid rgba(10,102,232,.45);outline-offset:2px}}
#recado{{margin-top:16px;min-height:1.5em;color:var(--navy-900)}}
.versao{{margin-top:20px;font-size:12px;color:var(--cinza-600)}}
</style></head><body><main role="main" aria-labelledby="titulo">
<h1 id="titulo">O {NOME} não pôde abrir</h1>
<p class="sub">Faltam arquivos do programa, ou eles foram alterados:</p>
<ul>{itens}</ul>
<p>{html.escape(HIPOTESE)}</p>
<p>{html.escape(DADOS_INTACTOS)}</p>
<div class="acoes">
<button class="principal" id="reparar" aria-describedby="sobre-reparar">Reparar</button>
<button id="registros">Abrir os registros</button>
<button id="fechar">Fechar</button>
</div>
<p class="sub" id="sobre-reparar">Reparar abre o instalador do {NOME} (Helestron-Setup) que estiver na
pasta Downloads; se ele não estiver lá, explica como baixá-lo de novo.</p>
<p id="recado" role="status" aria-live="polite"></p>
<p class="versao">{NOME} {__version__} · pasta do programa: <code>{html.escape(str(pasta))}</code></p>
</main>
<script nonce="{nonce}">
(function () {{
  var t = new URLSearchParams(location.search).get("t") || sessionStorage.getItem("helestron-token") || "";
  if (t) {{ sessionStorage.setItem("helestron-token", t); history.replaceState(null, "", "/"); }}
  var recado = document.getElementById("recado");
  function api(caminho, corpo) {{
    return fetch(caminho, {{method: "POST", headers: {{"X-Helestron-Token": t,
      "Content-Type": "application/json"}}, body: JSON.stringify(corpo || {{}})}})
      .then(function (r) {{ return r.json(); }});
  }}
  document.getElementById("reparar").addEventListener("click", function () {{
    recado.textContent = "Procurando o instalador na pasta Downloads…";
    api("/api/integridade/reparar").then(function (r) {{
      recado.textContent = r.ok ? r.dados.mensagem : r.erro.mensagem;
    }}).catch(function () {{ recado.textContent = "Não consegui falar com o programa."; }});
  }});
  document.getElementById("registros").addEventListener("click", function () {{
    api("/api/abrir", {{tipo: "pasta", alvo: "logs"}});
  }});
  document.getElementById("fechar").addEventListener("click", function () {{
    api("/api/encerrar").finally(function () {{ window.close(); }});
  }});
}})();
</script></body></html>
"""


class AplicacaoErro:
    """O mínimo que o servidor e a janela usam, no modo de erro."""

    def __init__(self, problemas: list[integridade.Problema], token: str | None = None):
        self.problemas = problemas
        self.token = token or secrets.token_urlsafe(32)
        self.modo = "janela"
        self.hub = HubEventos()
        self.perguntas = GerentePerguntas(self.hub.publicar)
        self.janela = None
        self.ao_encerrar: list = []
        self.fechando = False
        self.encerrado = threading.Event()
        self.iniciado_em = time.monotonic()
        self.instalador_aberto = False
        roteador = Roteador()
        roteador.adicionar("GET", "/api/ping", self._ping)
        roteador.adicionar("GET", "/api/integridade", self._integridade)
        roteador.adicionar("POST", "/api/integridade/reparar", self._reparar)
        roteador.adicionar("POST", "/api/abrir", self._abrir)
        roteador.adicionar("POST", "/api/encerrar", self._encerrar)
        roteador.adicionar("POST", "/api/janela/mostrar", self._mostrar)
        self.servidor = ServidorLocal(self, roteador, self.token, 0, None,
                                      pagina_inicial=self._pagina)

    @property
    def url(self) -> str:
        return self.servidor.url_com_token()

    @property
    def porta(self) -> int:
        return self.servidor.porta

    def _pagina(self) -> tuple[str, str]:
        nonce = secrets.token_urlsafe(16)
        csp = (f"default-src 'self'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
               "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
               "frame-ancestors 'none'; form-action 'none'")
        return pagina(self.problemas, nonce), csp

    def tocar(self) -> None:
        self.hub.tocar()

    def trabalho_em_andamento(self) -> list[str]:
        return []

    # ------------------------------------------------------------- rotas
    def _ping(self, p: Pedido) -> dict:
        return {"nome": NOME, "versao": __version__, "pid": os.getpid(), "modo": "erro",
                "porta": self.porta, "fechando": self.fechando}

    def _integridade(self, p: Pedido) -> dict:
        instalador = integridade.procurar_instalador()
        return {"problemas": [x.como_dict() for x in self.problemas],
                "instalador": str(instalador) if instalador else None,
                "pasta": str(integridade.pasta_instalada() or ""), "logs": str(caminhos.LOGS)}

    def _reparar(self, p: Pedido) -> dict:
        instalador = integridade.procurar_instalador()
        pasta = integridade.pasta_instalada() or caminhos.LOCAL
        if instalador is None or sys.platform != "win32":
            return {"abriu": False, "mensagem": instrucoes_reinstalar(pasta)}
        try:
            os.startfile(str(instalador))           # type: ignore[attr-defined]
        except OSError as erro:
            log.warning("o instalador não abriu: %s", erro)
            return {"abriu": False, "mensagem": instrucoes_reinstalar(pasta)}
        self.instalador_aberto = True
        # O instalador pede ao programa aberto que feche (--encerrar): fecha-se já.
        threading.Timer(2.0, self.encerrar).start()
        return {"abriu": True, "mensagem": f"O instalador abriu ({instalador.name}). Siga as "
                                           "etapas: ele conserta a instalação sem apagar os "
                                           "seus dados."}

    def _abrir(self, p: Pedido) -> dict:
        if p.campo("alvo", padrao="", tipo=str) != "logs":
            raise ErroApi(403, "fora_das_pastas", "Nesta tela, só os registros podem ser abertos.")
        sistema.abrir_pasta(caminhos.LOGS)
        return {"aberto": str(caminhos.LOGS)}

    def _encerrar(self, p: Pedido) -> dict:
        threading.Thread(target=self.encerrar, name="encerrar", daemon=True).start()
        return {"encerrando": True}

    def _mostrar(self, p: Pedido) -> dict:
        janela = self.janela
        return {"mostrou": bool(janela.mostrar()) if janela is not None else False}

    # ---------------------------------------------------------- execução
    def iniciar(self) -> "AplicacaoErro":
        self.servidor.iniciar()
        return self

    def encerrar(self) -> None:
        if self.fechando:
            return
        self.fechando = True
        for funcao in list(self.ao_encerrar):
            try:
                funcao()
            except Exception:                      # pragma: no cover
                log.exception("falha ao encerrar a tela de erro")
        self.hub.fechar()
        self.servidor.parar()
        self.encerrado.set()


def mostrar(problemas: list[integridade.Problema]) -> int:
    """Mostra a tela de erro e espera ela fechar. Código de saída: 1."""
    from . import janela

    log.error("a instalação está incompleta:\n%s", integridade.descrever(problemas, 50))
    app = AplicacaoErro(problemas).iniciar()
    try:
        modo = janela.abrir(app, app.url)
        if not modo:
            raise RuntimeError("nenhuma janela pôde ser aberta")
    finally:
        app.encerrar()
    return 1
