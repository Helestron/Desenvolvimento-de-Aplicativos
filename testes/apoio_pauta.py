"""Dublês para os testes da pauta: portais de mentira, HTML realista e configuração isolada.

* audiencias_padrao(): uma pauta de duas semanas, com sigiloso, cancelada,
  redesignada, virtual (com link) e uma fora do período;
* html_eproc() / html_esaj(): a tabela como cada portal a desenha
  (table.infraTable com a legenda "Lista de Audiências (N registros - a a
  b):" e a paginação do Infra; table.resultTable com "Data/Hora" juntas);
* PortalWebFalso: um portal em http.server (127.0.0.1) com login, menu em
  dois níveis ("Audiências" -> "Pauta de Audiências"), um "Designar
  audiência" que NÃO pode ser clicado, um "Sair" idem, painel de
  intimações (tabela com data e processo que NÃO é pauta), formulário de
  período e tabela paginada; e o robô que faz as vezes do usuário na
  captura assistida (clica na barra do Helestron);
* PortalDeTeste: o "portal" do download para esse site (entrar() faz o login);
* EProcComPauta: o eProc falso do download (testes/apoio_eproc.py) com o
  menu "Audiência > Pauta de Audiências" (link assinado para a sessão), o
  formulário do Infra e a paginação por infraAcaoPaginar;
* config_temporaria(): um config.ini com acervo, sigilosos e pauta numa
  pasta temporária.
"""

from __future__ import annotations

import http.cookies
import http.server
import json
import logging
import secrets
import threading
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from pathlib import Path

from helestron.nucleo import config

from testes import apoio_download as apoio
from testes import apoio_eproc as ae

# Os avisos que a pauta dá (fonte que falhou, regra estragada) são esperados
# nos testes; sem isto, o logging os despejaria no terminal.
logging.getLogger("pauta").addHandler(logging.NullHandler())

USUARIO, SENHA = "juiz.teste", "s3nh@ da pauta"
INICIO, FIM = date(2026, 10, 5), date(2026, 10, 16)


def numero(seq: str, tr: str = "02", origem: str = "0001") -> str:
    return apoio.numero_valido(seq=seq, tr=tr, origem=origem)


@dataclass
class AudFalsa:
    data: date
    hora: str
    processo: str
    tipo: str
    situacao: str = "Designada"
    local: str = "Sala de audiências da 2ª Vara Cível"
    classe: str = "Procedimento Comum Cível"
    partes: str = ""
    magistrado: str = "Dra. Camila Albuquerque"
    sigiloso: bool = False
    link: str = ""


def audiencias_padrao(tr: str = "02") -> list[AudFalsa]:
    n = lambda s: numero(s, tr)  # noqa: E731
    return [
        AudFalsa(date(2026, 10, 5), "09:00", n("0700101"), "Audiência de Conciliação",
                 partes="Maria José dos Santos x Banco do Brasil S.A."),
        AudFalsa(date(2026, 10, 5), "14:30", n("0700102"),
                 "Audiência de Conciliação, Instrução e Julgamento",
                 partes="José Carlos Lima x Equatorial Alagoas S.A.",
                 classe="Procedimento do Juizado Especial Cível"),
        AudFalsa(date(2026, 10, 6), "10:00", n("0700103"), "Audiência de Instrução e Julgamento",
                 situacao="Redesignada", partes="Ana Paula Rocha x Município de Maceió"),
        AudFalsa(date(2026, 10, 7), "08:30", n("0700104"), "Audiência de Custódia",
                 local="Central de Custódia", partes="Justiça Pública x Erivaldo Gomes",
                 classe="Auto de Prisão em Flagrante"),
        AudFalsa(date(2026, 10, 8), "09:30", n("0700105"), "Audiência de Conciliação",
                 sigiloso=True, partes="M. A. S. x J. R. S.", classe="Alimentos"),
        AudFalsa(date(2026, 10, 9), "15:00", n("0700106"), "Audiência de Mediação",
                 local="Virtual (videoconferência)",
                 link="https://teams.microsoft.com/l/meetup-join/sala-2vcivel",
                 partes="Condomínio Jatiúca Park x Ricardo Brandão"),
        AudFalsa(date(2026, 10, 13), "11:00", n("0700107"), "Audiência de Justificação",
                 situacao="Cancelada", partes="Pedro Wanderley x Ebazar.com.br Ltda."),
        AudFalsa(date(2026, 10, 15), "13:30", n("0700108"), "Audiência Una",
                 partes="Rosângela Pimentel x Azul Linhas Aéreas S.A."),
        AudFalsa(date(2026, 10, 30), "09:00", n("0700109"), "Audiência de Conciliação",
                 partes="Fora do período x Ninguém"),
    ]


def no_periodo(lista: list[AudFalsa], de: date, ate: date) -> list[AudFalsa]:
    return [a for a in lista if de <= a.data <= ate]


# ================================================================== HTML
def html_eproc(lista: list[AudFalsa], total: int | None = None, inicio: int = 1,
               sigilo_por_icone: bool = True) -> str:
    """A tabela como o eProc a desenha (framework Infra)."""
    total = len(lista) if total is None else total
    fim = inicio + len(lista) - 1
    linhas = []
    for i, a in enumerate(lista):
        icone = ("<img src='data:,' title='Segredo de Justiça (Nível 1)' alt='Sigiloso'>"
                 if a.sigiloso and sigilo_por_icone else "")
        partes = "(Segredo de Justiça)" if a.sigiloso else escape(a.partes)
        local = (f"<a href='{escape(a.link)}' target='_blank'>{escape(a.local)}</a>"
                 if a.link else escape(a.local))
        linhas.append(
            f"<tr class='{'infraTrClara' if i % 2 else 'infraTrEscura'}'>"
            f"<td><a href='controlador.php?acao=processo_selecionar&num_processo="
            f"{a.processo.replace('-', '').replace('.', '')}'>{a.processo}</a> {icone}</td>"
            f"<td>{a.data:%d/%m/%Y}</td><td>{a.hora}</td><td>{escape(a.tipo)}</td>"
            f"<td>{escape(a.situacao)}</td><td>{local}</td><td>{escape(a.magistrado)}</td>"
            f"<td>{partes}</td></tr>")
    vazio = "<tr><td colspan='8'>Nenhum registro encontrado.</td></tr>" if not lista else ""
    return ("<table class='infraTable' summary='Tabela de Audiências'>"
            f"<caption class='infraCaption'>Lista de Audiências ({total} registros - {inicio} a "
            f"{fim}):</caption>"
            "<tr><th class='infraTh'>Nº Processo</th><th class='infraTh'>Data</th>"
            "<th class='infraTh'>Hora</th><th class='infraTh'>Tipo de Audiência</th>"
            "<th class='infraTh'>Situação</th><th class='infraTh'>Local</th>"
            "<th class='infraTh'>Magistrado</th><th class='infraTh'>Partes</th></tr>"
            + "".join(linhas) + vazio + "</table>")


def html_esaj(lista: list[AudFalsa], legenda: str = "") -> str:
    """A tabela como o e-SAJ a desenha: data e hora numa coluna só."""
    linhas = []
    for a in lista:
        sig = (" <img class='segredoJustica' src='data:,' title='Processo em segredo de justiça'"
               " alt='Sigiloso'>" if a.sigiloso else "")
        link = f" <a href='{escape(a.link)}'>Entrar na sala</a>" if a.link else ""
        linhas.append(
            f"<tr><td>{a.data:%d/%m/%Y} {a.hora}</td><td>{a.processo}{sig}</td>"
            f"<td>{escape(a.classe)}</td><td>{escape(a.tipo)}</td><td>{escape(a.situacao)}</td>"
            f"<td>{escape(a.local)}{link}</td><td>{escape(a.partes)}</td></tr>")
    cap = f"<caption>{escape(legenda)}</caption>" if legenda else ""
    return ("<table class='resultTable'>" + cap +
            "<thead><tr><th>Data/Hora</th><th>Processo</th><th>Classe</th>"
            "<th>Tipo de Audiência</th><th>Situação</th><th>Local</th><th>Partes</th></tr></thead>"
            "<tbody>" + "".join(linhas) + "</tbody></table>")


def html_intimacoes(tr: str = "02") -> str:
    """Tabela com data e processo que NÃO é pauta (intimações com prazo)."""
    return ("<table class='infraTable'><caption>Intimações pendentes</caption>"
            "<tr><th>Data</th><th>Processo</th><th>Evento</th><th>Prazo</th></tr>"
            f"<tr><td>01/10/2026</td><td>{numero('0700901', tr)}</td><td>Intimação eletrônica</td>"
            "<td>15 dias</td></tr>"
            f"<tr><td>02/10/2026</td><td>{numero('0700902', tr)}</td><td>Citação</td>"
            "<td>5 dias</td></tr></table>")


def pagina(corpo: str, titulo: str = "Portal") -> str:
    return (f"<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'><title>{titulo}"
            f"</title></head><body>{corpo}</body></html>")


# ======================================================== portal em http.server
ROBO_JS = r"""(() => {
  const passo = () => parseInt(sessionStorage.getItem("robo") || "0", 10);
  const definir = (n) => sessionStorage.setItem("robo", String(n));
  const barra = () => { const h = document.getElementById("helestron-barra"); return h && h.shadowRoot; };
  const anotar = (texto) => fetch("/robo/registro", {method: "POST", body: texto});
  const quando = (cond, fazer) => { const t = setInterval(() => { if (cond()) { clearInterval(t); fazer(); } }, 120); };
  quando(() => typeof window.helestronPauta === "function" && barra() && barra().getElementById("capturar"), () => {
    const r = barra();
    const texto = () => r.getElementById("texto").textContent;
    const p = passo();
    const capturarEDepois = (depois) => {
      const antes = texto();
      r.getElementById("capturar").click();
      quando(() => texto() !== antes && !/Lendo/.test(texto()), () => { anotar(texto()).then(depois); });
    };
    if (location.pathname === "/inicio" && p === 0) {
      definir(1);
      capturarEDepois(() => { location.href = "/pauta/consultar?dataInicio=05/10/2026&dataFim=16/10/2026"; });
    } else if (location.pathname.startsWith("/pauta") && p === 1) {
      definir(2);
      capturarEDepois(() => {
        const prox = Array.from(document.querySelectorAll("a")).find((a) => /Próxima/.test(a.textContent));
        prox.click();
      });
    } else if (location.pathname.startsWith("/pauta") && p === 2) {
      definir(3);
      capturarEDepois(() => capturarEDepois(() => r.getElementById("concluir").click()));
    }
  });
})();"""


class PortalWebFalso:
    """Um portal "e-SAJ" de mentira, servido de verdade em 127.0.0.1."""

    def __init__(self, audiencias: list[AudFalsa] | None = None, por_pagina: int = 3,
                 robo: bool = False, tr: str = "02"):
        self.audiencias = audiencias if audiencias is not None else audiencias_padrao(tr)
        self.por_pagina = por_pagina
        self.robo = robo
        self.tr = tr
        self.sessoes: set[str] = set()
        self.logins = 0
        self.pedidos: list[tuple[str, str]] = []
        self.periodos: list[tuple[str, str]] = []
        self.paginas: list[int] = []
        self.proibidas: list[str] = []          # "Designar", "Sair": nunca podem ser abertas
        self.registro_robo: list[str] = []
        self._aberturas_pauta = 0
        self._expirar_em = 0                     # derruba a sessão nesta abertura da pauta
        self._servidor: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def expirar_na_pauta(self, n: int = 1) -> None:
        """A sessão cai na n-ésima abertura da pauta, contada a partir de agora."""
        self._expirar_em = self._aberturas_pauta + n

    # -------------------------------------------------------------- ciclo
    def iniciar(self) -> "PortalWebFalso":
        portal = self

        class Tratador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                portal._atender(self, "GET")

            def do_POST(self):
                portal._atender(self, "POST")

        self._servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self._servidor.daemon_threads = True
        self._thread = threading.Thread(target=self._servidor.serve_forever, daemon=True)
        self._thread.start()
        return self

    def parar(self) -> None:
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self._servidor.server_address[1]}"

    # ---------------------------------------------------------- respostas
    def _html(self, h, corpo: str, titulo: str = "e-SAJ de teste", status: int = 200,
              cabecalhos: dict | None = None) -> None:
        robo = "<script src='/robo.js'></script>" if self.robo else ""
        dados = pagina(corpo + robo, titulo).encode("utf-8")
        h.send_response(status)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(dados)))
        for k, v in (cabecalhos or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(dados)

    def _redirecionar(self, h, destino: str, cabecalhos: dict | None = None) -> None:
        h.send_response(303)
        h.send_header("Location", destino)
        h.send_header("Content-Length", "0")
        for k, v in (cabecalhos or {}).items():
            h.send_header(k, v)
        h.end_headers()

    def _sessao(self, h) -> str:
        c = http.cookies.SimpleCookie()
        try:
            c.load(h.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return ""
        valor = c["sessao"].value if "sessao" in c else ""
        return valor if valor in self.sessoes else ""

    def _menu(self) -> str:
        return ("<nav id='menu'><a href='/inicio'>Início</a> · <a href='/consulta'>Consulta "
                "processual</a> · <a href='/audiencias'>Audiências</a> · "
                "<a href='/sair'>Sair</a></nav>")

    def _atender(self, h, metodo: str) -> None:
        partes = urllib.parse.urlsplit(h.path)
        caminho = partes.path
        q = {k: v[0] for k, v in urllib.parse.parse_qs(partes.query, keep_blank_values=True).items()}
        self.pedidos.append((metodo, h.path))
        tamanho = int(h.headers.get("Content-Length") or 0)
        corpo = h.rfile.read(tamanho).decode("utf-8", "replace") if tamanho else ""
        if caminho == "/robo.js":
            dados = ROBO_JS.encode("utf-8")
            h.send_response(200)
            h.send_header("Content-Type", "text/javascript; charset=utf-8")
            h.send_header("Content-Length", str(len(dados)))
            h.end_headers()
            h.wfile.write(dados)
            return
        if caminho == "/robo/registro":
            self.registro_robo.append(corpo)
            h.send_response(204)
            h.end_headers()
            return
        if caminho == "/login":
            if metodo == "POST":
                form = {k: v[0] for k, v in urllib.parse.parse_qs(corpo).items()}
                if form.get("usuario") == USUARIO and form.get("senha") == SENHA:
                    sid = secrets.token_hex(8)
                    self.sessoes.add(sid)
                    self.logins += 1
                    return self._redirecionar(h, "/inicio",
                                              {"Set-Cookie": f"sessao={sid}; Path=/"})
                return self._html(h, "<p class='erro'>Usuário ou senha inválidos.</p>"
                                  + self._form_login())
            return self._html(h, self._form_login(), "Entrar")
        sid = self._sessao(h)
        if not sid:
            return self._redirecionar(h, "/login")
        if caminho in ("/sair", "/audiencias/designar"):
            self.proibidas.append(caminho)
            if caminho == "/sair":
                self.sessoes.discard(sid)
                return self._redirecionar(h, "/login")
            return self._html(h, self._menu() + "<h1>Designar audiência</h1><form method='post'>"
                              "<label for='d'>Data</label><input id='d' name='d'>"
                              "<button>Designar</button></form>")
        if caminho == "/inicio":
            return self._html(h, self._menu() + "<h1>Bem-vindo</h1>" + html_intimacoes(self.tr),
                              "Início")
        if caminho == "/consulta":
            return self._html(h, self._menu() + "<h1>Consulta processual</h1><form>"
                              "<label for='n'>Número do processo</label><input id='n'></form>")
        if caminho == "/audiencias":
            return self._html(h, self._menu() + "<h1>Audiências</h1><ul>"
                              "<li><a href='/audiencias/designar'>Designar audiência</a></li>"
                              "<li><a href='/pauta/consultar'>Pauta de Audiências</a></li></ul>")
        if caminho == "/pauta/consultar":
            self._aberturas_pauta += 1
            if self._expirar_em and self._aberturas_pauta == self._expirar_em:
                self.sessoes.discard(sid)
                return self._redirecionar(h, "/login")
            return self._pauta(h, q)
        return self._html(h, "<p>Não encontrado.</p>", status=404)

    def _form_login(self) -> str:
        return ("<form method='post' action='/login'><label for='usuario'>Usuário</label>"
                "<input id='usuario' name='usuario'><label for='senha'>Senha</label>"
                "<input id='senha' name='senha' type='password'>"
                "<button id='entrar' type='submit'>Entrar</button></form>")

    def _pauta(self, h, q: dict) -> None:
        formulario = ("<table class='moldura'><tr><td><form method='get' action='/pauta/consultar'>"
                      "<label for='dataInicio'>Data inicial</label>"
                      f"<input id='dataInicio' name='dataInicio' maxlength='10' "
                      f"placeholder='dd/mm/aaaa' value='{escape(q.get('dataInicio', ''))}'>"
                      "<label for='dataFim'>Data final</label>"
                      f"<input id='dataFim' name='dataFim' maxlength='10' placeholder='dd/mm/aaaa' "
                      f"value='{escape(q.get('dataFim', ''))}'>"
                      "<input type='submit' value='Pesquisar'></form></td></tr></table>")
        topo = self._menu() + "<h1>Pauta de Audiências</h1>" + formulario
        if not q.get("dataInicio"):
            return self._html(h, topo + "<p>Informe o período e clique em Pesquisar.</p>",
                              "Pauta de Audiências")
        de = datetime.strptime(q["dataInicio"], "%d/%m/%Y").date()
        ate = datetime.strptime(q["dataFim"], "%d/%m/%Y").date()
        pag = int(q.get("pagina") or 1)
        self.periodos.append((q["dataInicio"], q["dataFim"]))
        self.paginas.append(pag)
        lista = no_periodo(self.audiencias, de, ate)
        fatia = lista[(pag - 1) * self.por_pagina: pag * self.por_pagina]
        paginas = max(1, -(-len(lista) // self.por_pagina))
        nav = []
        consulta = f"dataInicio={q['dataInicio']}&dataFim={q['dataFim']}"
        if pag > 1:
            nav.append(f"<a href='/pauta/consultar?{consulta}&pagina={pag - 1}'>« Anterior</a>")
        nav.append(f"<span>Página {pag} de {paginas}</span>")
        if pag < paginas:
            nav.append(f"<a class='proxima' href='/pauta/consultar?{consulta}&pagina={pag + 1}'>"
                       "Próxima »</a>")
        tabela = html_esaj(fatia, f"Audiências encontradas: {len(lista)}")
        return self._html(h, topo + tabela + "<div class='paginacao'>" + " ".join(nav) + "</div>",
                          "Pauta de Audiências")


class PortalDeTeste:
    """O "portal" do download para o PortalWebFalso: entrar() faz o login."""

    sistema = "esaj"

    def __init__(self, nav, web: PortalWebFalso, ctx=None, credenciais=None):
        self.nav = nav
        self.web = web
        self.ctx = ctx
        self.credenciais = credenciais
        self.base = web.base
        self.nome = "e-SAJ do TJAL"
        self.entradas = 0

    def entrar(self) -> None:
        self.entradas += 1
        pg = self.nav.pagina
        pg.goto(self.base + "/inicio", wait_until="domcontentloaded")
        if "/login" in pg.url:
            usuario, senha = self.credenciais or (USUARIO, SENHA)
            pg.fill("#usuario", usuario)
            pg.fill("#senha", senha)
            with pg.expect_navigation(wait_until="domcontentloaded"):
                pg.click("#entrar")


def navegador_web(pasta: Path, nome: str = "esaj-TJAL"):
    """O Navegador de verdade do download, com o Chromium de teste."""
    from helestron.download.navegador import Navegador

    canal, exe = ae.navegador_de_teste()
    return Navegador(pasta / "perfis" / nome, visivel=False, canal=canal, executavel=exe,
                     espera_s=20, pasta_downloads=pasta / "downloads",
                     pasta_diagnostico=pasta / "diagnostico")


# ===================================================== eProc com a pauta
class EProcComPauta(ae.EProcFalso):
    """O eProc falso do download, com "Audiência > Pauta de Audiências"."""

    def __init__(self, audiencias: list[AudFalsa] | None = None, por_pagina: int = 4,
                 so_seletor: bool = False, **extra):
        extra.setdefault("painel_extra", html_intimacoes("21"))
        super().__init__(**extra)
        # sem o link "Próxima Página": só o seletor de página (e um "registros por
        # página" ao lado, que não é paginação)
        self.so_seletor = so_seletor
        self.pauta = audiencias if audiencias is not None else audiencias_padrao("21")
        self.por_pagina_pauta = por_pagina
        self.pauta_pedidos: list[tuple[str, str, int]] = []      # (de, ate, página)
        self.designar_visitas = 0

    def _topo(self, sid: str) -> str:
        menu = ("<ul id='main-menu'><li><a href='#'>Audiência</a><ul style='display:none'>"
                f"<li><a href='{escape(self.link(sid, 'audiencia_designar', 'designar'))}'>"
                "Designar Audiência</a></li>"
                f"<li><a href='{escape(self.link(sid, 'audiencia_listar', 'pauta'))}'>"
                "Pauta de Audiências</a></li></ul></li></ul>")
        return super()._topo(sid) + menu

    def _interno(self, req, caminho: str, q: dict, form: dict, sid: str) -> tuple:
        acao = q.get("acao") or ""
        if acao == "audiencia_designar":
            self.designar_visitas += 1
            return self._html(self._topo(sid) + "<h1>Designar Audiência</h1>")
        if acao == "audiencia_listar":
            if not self._confere(sid, q, "pauta", req.url):
                return self._sem_assinatura()
            return self._pagina_pauta(sid, form)
        return super()._interno(req, caminho, q, form, sid)

    def _pagina_pauta(self, sid: str, form: dict) -> tuple:
        campo = lambda nome: (form.get(nome) or [""])[0]  # noqa: E731
        acao_form = escape(self.link(sid, "audiencia_listar", "pauta"))
        de_txt, ate_txt = campo("txtDataInicio"), campo("txtDataFim")
        pagina_atual = int(campo("hdnInfraPaginaAtual") or 0)
        formulario = (
            f"<form id='frmAudienciaLista' method='post' action='{acao_form}'>"
            "<label for='txtDataInicio'>Data Inicial:</label>"
            f"<input type='text' id='txtDataInicio' name='txtDataInicio' maxlength='10' "
            f"value='{escape(de_txt)}'>"
            "<label for='txtDataFim'>Data Final:</label>"
            f"<input type='text' id='txtDataFim' name='txtDataFim' maxlength='10' "
            f"value='{escape(ate_txt)}'>"
            "<button type='submit' id='sbmPesquisar' name='sbmPesquisar' value='Pesquisar'>"
            "Pesquisar</button>"
            f"<input type='hidden' id='hdnInfraPaginaAtual' name='hdnInfraPaginaAtual' "
            f"value='{pagina_atual}'>")
        script = ("<script>function infraAcaoPaginar(acao, valor, nome) {"
                  "var h = document.getElementById('hdnInfraPaginaAtual');"
                  "var atual = parseInt(h.value || '0', 10);"
                  "if (acao === '+') h.value = atual + 1; else if (acao === '-') h.value = atual - 1;"
                  " else h.value = valor;"
                  "document.getElementById('frmAudienciaLista').submit(); }</script>")
        topo = (self._topo(sid) + "<div id='divInfraBarraLocalizacao' class='infraBarraLocalizacao'>"
                "Pauta de Audiências</div>")
        if not de_txt:
            return self._html(topo + formulario + "</form>" + script, "Pauta de Audiências")
        de = datetime.strptime(de_txt, "%d/%m/%Y").date()
        ate = datetime.strptime(ate_txt, "%d/%m/%Y").date()
        if campo("sbmPesquisar"):
            pagina_atual = 0                       # nova pesquisa volta à primeira página
        self.pauta_pedidos.append((de_txt, ate_txt, pagina_atual))
        lista = no_periodo(self.pauta, de, ate)
        n = self.por_pagina_pauta
        paginas = max(1, -(-len(lista) // n))
        fatia = lista[pagina_atual * n:(pagina_atual + 1) * n]
        opcoes = "".join(f"<option value='{i}'{' selected' if i == pagina_atual else ''}>{i + 1}"
                         "</option>" for i in range(paginas))
        proxima = ("<a id='lnkInfraProximaPaginaSuperior' href='javascript:void(0);' "
                   "onclick=\"infraAcaoPaginar('+',0,'Infra');\"><img src='data:,' "
                   "title='Próxima Página' alt='Próxima Página'></a>"
                   if pagina_atual < paginas - 1 and not self.so_seletor else "")
        if self.so_seletor:
            proxima += ("<select id='selInfraNroItensPaginacao' name='selRegistrosPorPagina' "
                        "onchange=\"infraAcaoPaginar('=',0,'Infra');\"><option>10</option>"
                        "<option>20</option><option>50</option></select>")
        anterior = ("<a id='lnkInfraPaginaAnteriorSuperior' href='javascript:void(0);' "
                    "onclick=\"infraAcaoPaginar('-',0,'Infra');\"><img src='data:,' "
                    "title='Página Anterior' alt='Página Anterior'></a>" if pagina_atual else "")
        paginacao = ("<div id='divInfraAreaPaginacaoSuperior' class='infraAreaPaginacao'>"
                     f"{anterior}<select id='selInfraPaginacaoSuperior' "
                     "onchange=\"infraAcaoPaginar('=',this.value,'Infra');\">"
                     f"{opcoes}</select>{proxima}</div>")
        tabela = html_eproc(fatia, total=len(lista), inicio=pagina_atual * n + 1)
        corpo = topo + formulario + paginacao + tabela + "</form>" + script
        return self._html(corpo, "Pauta de Audiências")


# ============================================================ configuração
@dataclass
class Ambiente:
    raiz: Path
    cfg: config.Config
    acervo: Path = field(init=False)
    sigilosos: Path = field(init=False)
    pauta: Path = field(init=False)

    def __post_init__(self):
        self.acervo = self.raiz / "Acervo"
        self.sigilosos = self.raiz / "Sigilosos"
        self.pauta = self.raiz / "Pauta"


def config_temporaria(raiz: Path, **extra) -> Ambiente:
    """Um config.ini só do teste, com as pastas do usuário na pasta temporária."""
    raiz.mkdir(parents=True, exist_ok=True)
    arquivo = raiz / "config.ini"
    linhas = ["[geral]", f"pasta_acervo = {raiz / 'Acervo'}",
              f"pasta_sigilosos = {raiz / 'Sigilosos'}", "", "[pauta]",
              f"pasta = {raiz / 'Pauta'}"]
    for chave, valor in extra.items():
        linhas.append(f"{chave} = {valor}")
    linhas += ["", "[download]", "pausa_entre_processos = 0", "salvar_diagnostico = false",
               "espera_segundos = 20"]
    arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return Ambiente(raiz, config.Config(arquivo))


class ContextoComCodigo(apoio.ContextoGravador):
    """O ContextoGravador do download (responde o código com a fila)."""


class ContextoDeFundo(apoio.ContextoGravador):
    """Como o ContextoFundo do servidor: não responde pergunta e marca 'pediu_login'."""

    def __init__(self):
        super().__init__()
        self.pediu_login = False

    def pedir_codigo(self, titulo, mensagem, prazo_s=600, reenviavel=True):
        self.pediu_login = True
        return None


def json_de(texto: str):
    return json.loads(texto)
