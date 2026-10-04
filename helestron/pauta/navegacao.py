"""A pauta lida no próprio portal, já logado (seção 8.3 da especificação).

O login, o perfil do navegador e as perguntas (código por e-mail, segundo
fator) são os do download - helestron.download.esaj/eproc/navegador -, sem
cópia: quem chama entrega o Navegador e o portal já com a sessão aberta.
Daqui em diante, nesta ordem:

1. a ROTA LEMBRADA da fonte (a URL que funcionou da última vez);
2. as ROTAS CONHECIDAS do pauta.json (por sistema e por tribunal);
3. a DESCOBERTA PELO MENU: links cujo texto lembra "Pauta de audiências",
   "Agenda de audiências", "Gerenciar audiências"... - nunca "Designar",
   "Cancelar", "Incluir" (o pauta.json tem a lista do que não se clica).

Aberta a página candidata: se ela fala de audiência e tem campos de data,
o PERÍODO é preenchido e a pesquisa enviada; todas as tabelas (inclusive
dentro de frames) são lidas e reconhecidas pelo cabeçalho; e a PAGINAÇÃO é
seguida até o fim - o "Próxima" comum, o infraAcaoPaginar do eProc (e o
seletor de página dele), com limite de 50 páginas e parada quando a
página não muda ou quando a legenda "(N registros)" já foi atingida.

O eProc assina cada link para a sessão (link montado à mão ou de outra
sessão cai em "Link sem assinatura"). Por isso a rota lembrada e as rotas
conhecidas do eProc valem pelo parâmetro 'acao' do link: procura-se na
página o link com a mesma ação, que já vem assinado para a sessão atual.

O JavaScript daqui só COLETA (tabelas, links, campos, controles de
página); quem decide o que clicar é o Python, com as regras do pauta.json.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date

from ..download.modelos import Cancelado, SessaoPerdida
from . import modelos
from .modelos import normalizar_texto
from .tabelas import Reconhecedor, Reconhecimento, Tabela

log = logging.getLogger("pauta.navegacao")

ESPERA_MUDANCA_S = 20.0        # quanto esperar a página mudar depois de um clique
INTERVALO_S = 0.3
_RE_SAIR = re.compile(r"logout|logoff|\bsair\b|acao=sair|sajcas/logout|encerrar.?sessao", re.I)


class PautaNaoEncontrada(RuntimeError):
    """O portal abriu, mas a tela da pauta de audiências não foi achada."""


# ================================================================ JavaScript
JS_TABELAS = r"""() => {
  const limpar = (t) => (t || "").replace(/\s+/g, " ").trim();
  const textoAntes = (t) => {
    const partes = [];
    let el = t, passos = 0;
    while (el && passos < 3) {
      let irmao = el.previousElementSibling;
      while (irmao && passos < 3) {
        if (irmao.tagName !== "SCRIPT" && irmao.tagName !== "STYLE" && irmao.tagName !== "TABLE") {
          const tx = limpar(irmao.innerText || irmao.textContent || "");
          if (tx) { partes.unshift(tx.slice(-200)); passos++; }
        }
        irmao = irmao.previousElementSibling;
      }
      el = el.parentElement;
      if (!el || el === document.body) break;
    }
    return partes.join(" ").slice(-200);
  };
  const saida = [];
  const tabelas = Array.from(document.querySelectorAll("table")).slice(0, 300);
  for (const t of tabelas) {
    const linhas = [];
    for (const tr of Array.from(t.rows).slice(0, 3000)) {
      const celulas = [];
      for (const c of Array.from(tr.cells)) {
        const links = Array.from(c.querySelectorAll("a[href]"))
          .map((a) => a.href).filter((h) => /^https?:/i.test(h)).slice(0, 5);
        const dicas = Array.from(c.querySelectorAll("[title], img[alt]"))
          .map((e) => e.getAttribute("title") || e.getAttribute("alt") || "")
          .filter(Boolean).slice(0, 6).join(" ");
        const proprio = c.getAttribute("title") || "";
        celulas.push({texto: limpar(c.innerText || c.textContent || ""), links,
                      dicas: limpar(proprio + " " + dicas), th: c.tagName === "TH",
                      colspan: c.colSpan || 1, aninhada: !!c.querySelector("table")});
      }
      linhas.push(celulas);
    }
    const legenda = limpar(t.caption ? (t.caption.innerText || t.caption.textContent) : "");
    saida.push({id: t.id || "", classes: (typeof t.className === "string" ? t.className : ""),
                legenda, antes: legenda ? "" : textoAntes(t), linhas});
  }
  return {tabelas: saida, titulo: limpar(document.title || ""),
          cabecalhos: Array.from(document.querySelectorAll("h1, h2, h3, legend, .infraBarraLocalizacao, #divInfraBarraLocalizacao"))
            .map((e) => limpar(e.innerText || e.textContent || "")).filter(Boolean).slice(0, 12).join(" | ")};
}"""

JS_ASSINATURA = r"""() => {
  const ts = Array.from(document.querySelectorAll("table"));
  let s = String(ts.length) + "|" + location.href;
  for (const t of ts.slice(0, 40)) {
    const tx = (t.innerText || "").replace(/\s+/g, " ");
    s += "|" + tx.length + ":" + tx.slice(0, 120) + tx.slice(-120);
  }
  return s;
}"""

JS_LINKS = r"""() => {
  const limpar = (t) => (t || "").replace(/\s+/g, " ").trim();
  document.querySelectorAll("[data-helestron-link]").forEach((e) => e.removeAttribute("data-helestron-link"));
  const saida = [];
  const els = Array.from(document.querySelectorAll("a, button, [onclick], [role=menuitem], li[data-url]")).slice(0, 4000);
  let n = 0;
  for (const el of els) {
    const texto = limpar(el.innerText || el.textContent || el.value || "");
    const titulo = limpar(el.getAttribute("title") || el.getAttribute("aria-label") || "");
    if (!texto && !titulo) continue;
    if (texto.length > 120) continue;
    n += 1;
    el.setAttribute("data-helestron-link", String(n));
    const href = el.tagName === "A" ? (el.href || "") : (el.getAttribute("data-url") || "");
    saida.push({n, texto, titulo, href, onclick: (el.getAttribute("onclick") || "").slice(0, 300),
                visivel: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)});
  }
  return saida;
}"""

JS_CAMPOS = r"""() => {
  const limpar = (t) => (t || "").replace(/\s+/g, " ").trim();
  const rotulo = (el) => {
    const partes = [];
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) partes.push(l.innerText || l.textContent || "");
    }
    const pai = el.closest("label");
    if (pai) partes.push(pai.innerText || pai.textContent || "");
    let ant = el.previousSibling, passos = 0;
    while (ant && passos < 3) {
      const tx = limpar(ant.textContent || "");
      if (tx) { partes.push(tx.slice(-40)); break; }
      ant = ant.previousSibling; passos++;
    }
    if (!partes.length) {
      const celula = el.closest("td, th, div");
      if (celula && celula.previousElementSibling) partes.push((celula.previousElementSibling.innerText || "").slice(-40));
    }
    return limpar(partes.join(" "));
  };
  const visivel = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  document.querySelectorAll("[data-helestron-campo]").forEach((e) => e.removeAttribute("data-helestron-campo"));
  const formularios = Array.from(document.forms);
  const campos = [], botoes = [];
  let n = 0;
  for (const el of Array.from(document.querySelectorAll("input, button, a[href], a[onclick]")).slice(0, 2000)) {
    const tipo = (el.getAttribute("type") || (el.tagName === "INPUT" ? "text" : el.tagName.toLowerCase())).toLowerCase();
    if (!visivel(el) || el.disabled) continue;
    n += 1;
    el.setAttribute("data-helestron-campo", String(n));
    const form = el.form ? formularios.indexOf(el.form) : (el.closest("form") ? formularios.indexOf(el.closest("form")) : -1);
    if (el.tagName === "INPUT" && ["text", "date", "search", "tel", ""].includes(tipo)) {
      campos.push({n, tipo, id: el.id || "", nome: el.name || "", placeholder: el.getAttribute("placeholder") || "",
                   titulo: el.getAttribute("title") || el.getAttribute("aria-label") || "",
                   rotulo: rotulo(el), maxlength: el.maxLength || 0, valor: el.value || "", form,
                   somenteLeitura: !!el.readOnly});
    } else if (["submit", "button", "image", "a"].includes(tipo) || el.tagName === "BUTTON") {
      botoes.push({n, texto: limpar(el.innerText || el.value || el.getAttribute("title") || el.getAttribute("alt") || ""),
                   id: el.id || "", nome: el.name || "", form, tipo});
    }
  }
  const senha = Array.from(document.querySelectorAll("input[type=password]")).some(visivel);
  const textoPagina = limpar([document.title, ...Array.from(document.querySelectorAll("h1, h2, h3, legend, label, caption, .infraBarraLocalizacao"))
    .map((e) => e.innerText || e.textContent || "")].join(" ")).slice(0, 3000);
  return {campos, botoes, senha, textoPagina};
}"""

JS_PAGINACAO = r"""() => {
  const limpar = (t) => (t || "").replace(/\s+/g, " ").trim();
  const saida = [], selects = [];
  document.querySelectorAll("[data-helestron-pagina]").forEach((e) => e.removeAttribute("data-helestron-pagina"));
  let n = 0;
  const visivel = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  for (const el of Array.from(document.querySelectorAll("a, button, input[type=button], input[type=submit], input[type=image], img[onclick], span[onclick], li[onclick], [role=button]")).slice(0, 3000)) {
    const imgs = Array.from(el.querySelectorAll ? el.querySelectorAll("img") : []);
    const titulo = limpar([el.getAttribute("title"), el.getAttribute("aria-label"), el.getAttribute("alt"),
                           ...imgs.map((i) => i.getAttribute("title") || i.getAttribute("alt") || "")].filter(Boolean).join(" "));
    const texto = limpar(el.innerText || el.value || "");
    const codigo = (el.getAttribute("onclick") || "") + " " + (el.getAttribute("href") || "");
    if (!texto && !titulo && !/paginar|pagina/i.test(codigo)) continue;
    n += 1;
    el.setAttribute("data-helestron-pagina", String(n));
    const classe = (typeof el.className === "string" ? el.className : "") + " " +
                   ((el.parentElement && typeof el.parentElement.className === "string") ? el.parentElement.className : "");
    saida.push({n, texto: texto.slice(0, 60), titulo: titulo.slice(0, 80), codigo: codigo.slice(0, 200),
                desabilitado: !!(el.disabled || el.getAttribute("aria-disabled") === "true" || /disabl|desabilit|inativ/i.test(classe)),
                visivel: visivel(el) || imgs.some(visivel)});
  }
  for (const s of Array.from(document.querySelectorAll("select"))) {
    const marca = (s.id || "") + " " + (s.name || "") + " " + (s.getAttribute("onchange") || "");
    if (!/paginac|pagina|page/i.test(marca)) continue;
    n += 1;
    s.setAttribute("data-helestron-pagina", String(n));
    selects.push({n, marca: marca.slice(0, 200), selecionada: s.selectedIndex, opcoes: s.options.length,
                  textos: Array.from(s.options).slice(0, 6).map((o) => limpar(o.textContent)),
                  visivel: visivel(s)});
  }
  return {controles: saida, selects};
}"""

JS_CLICAR = r"""([atributo, n]) => {
  const el = document.querySelector("[" + atributo + "=\"" + n + "\"]");
  if (!el) return false;
  if (el.tagName === "IMG" && el.parentElement && el.parentElement.tagName === "A") { el.parentElement.click(); return true; }
  el.click();
  return true;
}"""

JS_ESCOLHER_OPCAO = r"""([n, indice]) => {
  const s = document.querySelector('[data-helestron-pagina="' + n + '"]');
  if (!s || indice >= s.options.length) return false;
  s.selectedIndex = indice;
  s.dispatchEvent(new Event("input", {bubbles: true}));
  s.dispatchEvent(new Event("change", {bubbles: true}));
  return true;
}"""

JS_DEFINIR_VALOR = r"""([n, valor]) => {
  const el = document.querySelector('[data-helestron-campo="' + n + '"]');
  if (!el) return false;
  el.removeAttribute("readonly");
  el.value = valor;
  for (const tipo of ["input", "change", "blur"]) el.dispatchEvent(new Event(tipo, {bubbles: true}));
  return true;
}"""


# ================================================================== apoio
def parametros(url: str) -> dict[str, str]:
    try:
        consulta = urllib.parse.urlsplit(url or "").query
        return {k: v[0] for k, v in urllib.parse.parse_qs(consulta, keep_blank_values=True).items()}
    except ValueError:
        return {}


def _frames(pagina) -> list:
    try:
        return [f for f in pagina.frames if not f.is_detached()]
    except Exception:
        return []


def _avaliar(alvo, codigo: str, arg=None):
    """evaluate que não derruba quem chama: navegação no meio vira None."""
    try:
        return alvo.evaluate(codigo, arg) if arg is not None else alvo.evaluate(codigo)
    except Exception as erro:
        log.debug("  avaliação na página falhou: %s", str(erro)[:160])
        return None


def _opcoes_de_pagina(textos: list[str]) -> bool:
    """As opções começam em 1 e seguem de um em um ("1", "2", "3" ou "Página 1"...)."""
    numeros = []
    for t in textos:
        m = re.search(r"\d+", t or "")
        if not m:
            return False
        numeros.append(int(m.group(0)))
    return bool(numeros) and numeros == list(range(1, len(numeros) + 1))


@dataclass
class Leitura:
    """O que a leitura de uma tela de pauta trouxe (todas as páginas)."""

    reconhecimento: Reconhecimento = field(default_factory=Reconhecimento)
    paginas: int = 0
    periodo_aplicado: bool = False
    url: str = ""                      # a URL de ENTRADA da pauta (a rota a lembrar)
    menu: str = ""                     # o texto do menu que levou até ela
    total_informado: int | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def audiencias(self):
        return self.reconhecimento.audiencias

    def cobertura(self, de: date, ate: date) -> tuple[date, date] | None:
        """O intervalo que esta leitura CONFERIU (para marcar as removidas).

        Com o período preenchido no portal, é o pedido. Sem ele, o portal
        mostrou o que quis: vale só o intervalo das datas que vieram, dentro
        do pedido - e, se nada veio, nada se pode concluir.
        """
        if self.periodo_aplicado:
            return de, ate
        datas = [a.data for a in self.audiencias if de <= a.data <= ate]
        if not datas:
            return None
        return min(datas), max(datas)


# ============================================================ a leitura
class LeitorDePauta:
    """Lê a pauta da página aberta: período, tabelas, paginação."""

    def __init__(self, pagina, regras, reconhecedor: Reconhecedor, ctx=None,
                 espera_s: float = ESPERA_MUDANCA_S, nome: str = "portal"):
        self.pagina = pagina
        self.regras = regras
        self.reconhecedor = reconhecedor
        self.ctx = ctx
        self.espera_s = max(2.0, float(espera_s))
        self.nome = nome

    # ------------------------------------------------------------- apoio
    def _cancelado(self) -> None:
        if self.ctx is not None and self.ctx.cancelado():
            raise Cancelado()

    def _status(self, texto: str) -> None:
        if self.ctx is not None:
            try:
                self.ctx.status(texto)
            except Exception:
                pass

    def esperar(self, ms: int) -> None:
        try:
            self.pagina.wait_for_timeout(max(1, int(ms)))
        except Exception:
            time.sleep(max(1, int(ms)) / 1000)

    def esperar_carga(self) -> None:
        for estado, ms in (("domcontentloaded", int(self.espera_s * 1000)), ("load", 5000)):
            try:
                self.pagina.wait_for_load_state(estado, timeout=ms)
            except Exception:
                pass

    def assinatura(self) -> str:
        partes = []
        for f in _frames(self.pagina):
            partes.append(str(_avaliar(f, JS_ASSINATURA) or ""))
        return "#".join(partes)

    def esperar_mudanca(self, antes: str) -> bool:
        """Espera a página mudar (navegação ou atualização por ajax)."""
        limite = time.monotonic() + self.espera_s
        while time.monotonic() < limite:
            self._cancelado()
            self.esperar(int(INTERVALO_S * 1000))
            self.esperar_carga()
            agora = self.assinatura()
            if agora and agora != antes:
                self.esperar(250)          # deixa o ajax terminar de desenhar
                return True
        return False

    # ----------------------------------------------------------- tabelas
    def tabelas(self) -> tuple[list[tuple[object, Tabela]], str]:
        """[(frame, Tabela)] de todos os frames, e o texto de contexto da página."""
        saida, contexto = [], []
        for f in _frames(self.pagina):
            dados = _avaliar(f, JS_TABELAS)
            if not isinstance(dados, dict):
                continue
            contexto.append(f"{dados.get('titulo', '')} {dados.get('cabecalhos', '')}")
            try:
                url = f.url
            except Exception:
                url = ""
            for t in dados.get("tabelas") or []:
                saida.append((f, Tabela.de_js(t, url)))
        return saida, " ".join(contexto)

    def reconhecer(self) -> tuple[Reconhecimento, object | None]:
        """O que a tela mostra agora, e o frame em que a pauta está."""
        tabelas, contexto = self.tabelas()
        total = Reconhecimento()
        frame_alvo = None
        for frame, t in tabelas:
            r = self.reconhecedor.tabela(t, contexto)
            if r.reconhecida and frame_alvo is None:
                frame_alvo = frame
            total.juntar(r)
            if r.total_informado is not None:
                total.total_informado = r.total_informado
        return total, frame_alvo

    # ----------------------------------------------------------- período
    def campos(self) -> list[tuple[object, dict]]:
        saida = []
        for f in _frames(self.pagina):
            dados = _avaliar(f, JS_CAMPOS)
            if isinstance(dados, dict):
                saida.append((f, dados))
        return saida

    def pede_login(self) -> bool:
        return any(d.get("senha") for _, d in self.campos())

    def _descricao(self, campo: dict) -> str:
        return normalizar_texto(" ".join(str(campo.get(k) or "") for k in
                                         ("rotulo", "id", "nome", "placeholder", "titulo")))

    def classificar_periodo(self, campos: list[dict]) -> tuple[dict | None, dict | None]:
        """(campo da data inicial, campo da data final), pelas regras do pauta.json."""
        p = self.regras.periodo
        re_data = re.compile(p["data"], re.I)
        re_ini = re.compile(p["inicio"], re.I)
        re_fim = re.compile(p["fim"], re.I)
        datas = []
        for c in campos:
            desc = self._descricao(c)
            valor = str(c.get("valor") or "")
            parece = (c.get("tipo") == "date" or bool(re_data.search(desc))
                      or "dd/mm" in normalizar_texto(c.get("placeholder"))
                      or (int(c.get("maxlength") or 0) == 10
                          and modelos.ler_data(valor) is not None))
            if parece:
                datas.append((c, desc))
        inicio = next((c for c, d in datas if re_ini.search(d) and not re_fim.search(d)), None)
        fim = next((c for c, d in datas if re_fim.search(d) and c is not inicio), None)
        if inicio is None and fim is None and len(datas) == 2:
            inicio, fim = datas[0][0], datas[1][0]
        return inicio, fim

    def _formatar(self, campo: dict, d: date) -> str:
        if campo.get("tipo") == "date":
            return d.isoformat()
        return d.strftime("%d/%m/%Y")

    def _preencher(self, frame, campo: dict, d: date) -> bool:
        valor = self._formatar(campo, d)
        seletor = f'[data-helestron-campo="{campo["n"]}"]'
        try:
            frame.fill(seletor, valor, timeout=5000)
            atual = frame.eval_on_selector(seletor, "el => el.value")
            if modelos.ler_data(atual) == d or atual == valor:
                return True
        except Exception as erro:
            log.debug("  preencher %s: %s", seletor, str(erro)[:120])
        return bool(_avaliar(frame, JS_DEFINIR_VALOR, [campo["n"], valor]))

    def preencher_periodo(self, de: date, ate: date) -> bool:
        """Preenche Data inicial/final e envia a pesquisa. True se o fez.

        Só numa página que fala de audiência ou pauta: um formulário com
        campo de data em outra tela (designar, cadastrar) não é enviado.
        """
        re_botao = re.compile(self.regras.periodo["botao"], re.I)
        for frame, dados in self.campos():
            texto_da_pagina = normalizar_texto(dados.get("textoPagina"))
            if not self.regras.contexto_audiencia.search(texto_da_pagina):
                continue
            inicio, fim = self.classificar_periodo(dados.get("campos") or [])
            if inicio is None or fim is None:
                continue
            if not (self._preencher(frame, inicio, de) and self._preencher(frame, fim, ate)):
                continue
            botoes = [b for b in dados.get("botoes") or []
                      if re_botao.search(normalizar_texto(b.get("texto") or b.get("nome")
                                                          or b.get("id")))]
            mesmo_form = [b for b in botoes if b.get("form") == inicio.get("form")
                          and inicio.get("form", -1) >= 0]
            botao = (mesmo_form or botoes or [None])[0]
            antes = self.assinatura()
            self._status(f"Pedindo ao {self.nome} a pauta de {de:%d/%m/%Y} a {ate:%d/%m/%Y}…")
            if botao is not None:
                _avaliar(frame, JS_CLICAR, ["data-helestron-campo", botao["n"]])
            else:
                try:
                    frame.press(f'[data-helestron-campo="{fim["n"]}"]', "Enter", timeout=5000)
                except Exception:
                    pass
            self.esperar_mudanca(antes)
            self.esperar_carga()
            return True
        return False

    # --------------------------------------------------------- paginação
    def proxima(self, frame) -> bool:
        """Clica no "Próxima" (ou equivalente). False se não há próxima página."""
        alvos = [frame] if frame is not None else _frames(self.pagina)
        re_prox = re.compile(self.regras.proxima, re.I)
        for f in alvos:
            dados = _avaliar(f, JS_PAGINACAO)
            if not isinstance(dados, dict):
                continue
            controles = [c for c in dados.get("controles") or [] if not c.get("desabilitado")]
            # 1. eProc: infraAcaoPaginar('+', ...)
            for c in controles:
                if re.search(r"infraAcaoPaginar\(\s*['\"]\+", c.get("codigo") or ""):
                    if _avaliar(f, JS_CLICAR, ["data-helestron-pagina", c["n"]]):
                        return True
            # 2. "Próxima", "»", "Seguinte" (texto, title ou alt)
            for c in controles:
                for texto in (c.get("texto"), c.get("titulo")):
                    alvo = normalizar_texto(texto)
                    if alvo and re_prox.search(alvo) and not re.search(r"ultim", alvo):
                        if _avaliar(f, JS_CLICAR, ["data-helestron-pagina", c["n"]]):
                            return True
            # 3. seletor de página (o do eProc: selInfraPaginacao...), com as opções
            #    1, 2, 3... - o de "registros por página" (10, 20, 50) não é
            for s in dados.get("selects") or []:
                if not _opcoes_de_pagina(s.get("textos") or []):
                    continue
                indice = int(s.get("selecionada") or 0) + 1
                if 0 < indice < int(s.get("opcoes") or 0):
                    if _avaliar(f, JS_ESCOLHER_OPCAO, [s["n"], indice]):
                        return True
        return False

    # ------------------------------------------------------------ inteira
    def ler(self, de: date, ate: date, preencher: bool = True) -> Leitura:
        """A pauta da tela atual, todas as páginas. leitura.reconhecimento
        vazio (tabelas == 0) se a tela não tem pauta."""
        leitura = Leitura()
        self.esperar_carga()
        self._cancelado()
        if self.pede_login():
            raise SessaoPerdida(f"a sessão do {self.nome} caiu (o portal pediu a senha de novo)")
        if preencher:
            leitura.periodo_aplicado = self.preencher_periodo(de, ate)
        vistas: set[str] = set()
        limite = self.regras.limite_paginas
        while True:
            self._cancelado()
            rec, frame = self.reconhecer()
            if not rec.reconhecida:
                if leitura.paginas == 0 and self.pede_login():
                    raise SessaoPerdida(f"a sessão do {self.nome} caiu")
                break
            marca = "|".join(sorted(a.id for a in rec.audiencias)) or self.assinatura()
            if marca in vistas:
                break
            vistas.add(marca)
            leitura.reconhecimento.juntar(rec)
            leitura.reconhecimento.total_informado = None
            if rec.total_informado is not None:
                leitura.total_informado = max(leitura.total_informado or 0, rec.total_informado)
            leitura.paginas += 1
            if leitura.paginas > 1 or rec.total_informado:
                self._status(f"Lendo a pauta do {self.nome} (página {leitura.paginas})…")
            if leitura.total_informado is not None and \
                    len(leitura.audiencias) >= leitura.total_informado:
                break
            if leitura.paginas >= limite:
                leitura.avisos.append(f"A pauta tem mais de {limite} páginas; li as {limite} "
                                      "primeiras. Escolha um período menor.")
                break
            antes = self.assinatura()
            if not self.proxima(frame):
                break
            if not self.esperar_mudanca(antes):
                break
        if leitura.total_informado and len(leitura.audiencias) < leitura.total_informado:
            leitura.avisos.append(
                f"O {self.nome} informou {leitura.total_informado} audiências e foram lidas "
                f"{len(leitura.audiencias)}. Confira a pauta no portal.")
        leitura.reconhecimento.tabelas = 1 if leitura.paginas else 0
        return leitura


# ======================================================= extração automática
@dataclass
class _Candidato:
    peso: int
    texto: str
    href: str
    n: int
    frame: object


class ExtratorAutomatico:
    """Acha a pauta no portal já logado e a lê inteira (seção 8.3)."""

    def __init__(self, nav, portal, regras, reconhecedor: Reconhecedor, ctx=None,
                 fonte: dict | None = None, espera_s: float = ESPERA_MUDANCA_S):
        self.nav = nav
        self.portal = portal
        self.regras = regras
        self.reconhecedor = reconhecedor
        self.ctx = ctx
        self.fonte = dict(fonte or {})
        self.sistema = getattr(portal, "sistema", "") or self.fonte.get("sistema", "")
        self.espera_s = espera_s
        self.nome = getattr(portal, "nome", "") or "portal"
        self.visitadas: list[str] = []          # o que se abriu (para o diagnóstico)

    # ------------------------------------------------------------- apoio
    @property
    def pagina(self):
        return self.nav.pagina

    @property
    def base(self) -> str:
        return (getattr(self.portal, "base", "") or "").strip()

    def _cancelado(self) -> None:
        if self.ctx is not None and self.ctx.cancelado():
            raise Cancelado()

    def _status(self, texto: str) -> None:
        if self.ctx is not None:
            try:
                self.ctx.status(texto)
            except Exception:
                pass

    def leitor(self) -> LeitorDePauta:
        return LeitorDePauta(self.pagina, self.regras, self.reconhecedor, self.ctx,
                             self.espera_s, self.nome)

    def abrir(self, url: str) -> bool:
        self._cancelado()
        if not url or _RE_SAIR.search(url):
            return False
        self.visitadas.append(url)
        try:
            self.pagina.goto(url, wait_until="domcontentloaded",
                             timeout=int(max(5.0, self.espera_s) * 1000))
        except Exception as erro:
            log.info("  %s não abriu: %s", url, str(erro)[:160])
            return False
        self.leitor().esperar_carga()
        return True

    def url_atual(self) -> str:
        try:
            return self.pagina.url or ""
        except Exception:
            return ""

    def _absoluta(self, rota: str) -> str:
        if re.match(r"^https?://", rota, re.I):
            return rota
        base = self.base or self.url_atual()
        if not base:
            return ""
        if not base.endswith("/") and self.sistema == "eproc":
            base += "/"
        return urllib.parse.urljoin(base, rota)

    # ---------------------------------------------------------- os links
    def links(self) -> list[tuple[object, dict]]:
        saida = []
        for f in _frames(self.pagina):
            for item in _avaliar(f, JS_LINKS) or []:
                saida.append((f, item))
        return saida

    def candidatos_do_menu(self, ignorar: set[str] | None = None) -> list[_Candidato]:
        ignorar = ignorar or set()
        saida: list[_Candidato] = []
        vistos: set[str] = set()
        for frame, item in self.links():
            texto = normalizar_texto(f"{item.get('texto', '')} {item.get('titulo', '')}")
            href = str(item.get("href") or "")
            if not texto or self.regras.menu_excluir.search(texto) or _RE_SAIR.search(href):
                continue
            peso = 0
            for padrao, valor in self.regras.menu_procurar:
                if padrao.search(texto):
                    peso = max(peso, valor)
            if not peso:
                continue
            util = href if re.match(r"^https?://", href, re.I) else ""
            chave = util or f"{texto}|{item.get('onclick', '')}"
            if chave in vistos or (util and util in ignorar):
                continue
            vistos.add(chave)
            saida.append(_Candidato(peso, str(item.get("texto") or item.get("titulo") or ""),
                                    util, int(item["n"]), frame))
        saida.sort(key=lambda c: -c.peso)
        return saida

    def link_por_acao(self, acao: str) -> str:
        """O link desta sessão com a mesma 'acao' (eProc: já assinado)."""
        if not acao:
            return ""
        for _frame, item in self.links():
            href = str(item.get("href") or "")
            if href and parametros(href).get("acao") == acao:
                return href
        return ""

    def _paginas_de_partida(self) -> list[str]:
        """Onde procurar o menu: a página atual, a âncora do eProc, as do pauta.json."""
        saida = [self.url_atual()]
        ancora = getattr(self.portal, "_url_ancora", "") or ""
        if ancora:
            saida.append(ancora)
        for rota in self.regras.paginas_de_menu(self.sistema):
            saida.append(self._absoluta(rota))
        unicas = []
        for u in saida:
            if u and u not in unicas and not _RE_SAIR.search(u):
                unicas.append(u)
        return unicas

    # -------------------------------------------------------- a extração
    def extrair(self, de: date, ate: date) -> Leitura:
        lembrada = (self.fonte.get("url") or "").strip()
        if lembrada:
            self._status(f"Abrindo a pauta lembrada do {self.nome}…")
            leitura = self._tentar_rota(lembrada, de, ate, "rota lembrada")
            if leitura is not None:
                return leitura
        for rota in self.regras.rotas(self.sistema, self.fonte.get("tribunal", "")):
            leitura = self._tentar_rota(rota, de, ate, "rota conhecida")
            if leitura is not None:
                return leitura
        self._status(f"Procurando a pauta de audiências no menu do {self.nome}…")
        leitura = self.pelo_menu(de, ate)
        if leitura is not None:
            return leitura
        raise PautaNaoEncontrada(
            f"não encontrei a pauta de audiências no {self.nome}. Use “Capturar no portal”, na "
            "tela Pauta: você abre a pauta no navegador e o Helestron a lê; o endereço fica "
            "lembrado para o monitoramento.")

    def _tentar_rota(self, rota: str, de: date, ate: date, origem: str) -> Leitura | None:
        self._cancelado()
        if self.sistema == "eproc":
            # o eProc assina cada link para a sessão: vale a 'acao', não o endereço
            acao = parametros(rota).get("acao") if "acao=" in rota else rota.strip()
            if not acao or not re.match(r"^[\w.-]+$", acao):
                return None
            url = ""
            for partida in self._paginas_de_partida():
                if partida != self.url_atual() and not self.abrir(partida):
                    continue
                url = self.link_por_acao(acao)
                if url:
                    break
            if not url:
                return None
        else:
            url = self._absoluta(rota)
            if not url:
                return None
        if not self.abrir(url):
            return None
        leitura = self.leitor().ler(de, ate)
        if not leitura.reconhecimento.reconhecida:
            log.info("  %s (%s) abriu, mas não mostrou a pauta.", url, origem)
            return None
        leitura.url = url
        log.info("Pauta do %s achada pela %s: %s", self.nome, origem, url)
        return leitura

    def pelo_menu(self, de: date, ate: date) -> Leitura | None:
        """Busca em largura pelos links do menu, até max_paginas_visitadas."""
        limite = self.regras.max_paginas_visitadas
        abertas = 0
        tentados: set[str] = set()
        for partida in self._paginas_de_partida():
            if abertas >= limite:
                break
            if partida != self.url_atual() and not self.abrir(partida):
                continue
            fila: list[tuple[_Candidato, int, str]] = [
                (c, 1, partida) for c in self.candidatos_do_menu(tentados)[:5]]
            while fila and abertas < limite:
                self._cancelado()
                cand, nivel, origem = fila.pop(0)
                chave = cand.href or f"{origem}#{cand.texto}"
                if chave in tentados:
                    continue
                tentados.add(chave)
                if cand.href:
                    if not self.abrir(cand.href):
                        continue
                else:
                    if self.url_atual() != origem and not self.abrir(origem):
                        continue
                    # o menu foi relido na página de origem: o número do link vale de novo
                    novo = next((c for c in self.candidatos_do_menu()
                                 if normalizar_texto(c.texto) == normalizar_texto(cand.texto)),
                                None)
                    if novo is None:
                        continue
                    leitor = self.leitor()
                    antes = leitor.assinatura()
                    _avaliar(novo.frame, JS_CLICAR, ["data-helestron-link", novo.n])
                    leitor.esperar_mudanca(antes)
                abertas += 1
                entrada = self.url_atual()
                self._status(f"Conferindo “{cand.texto}” no {self.nome}…")
                leitura = self.leitor().ler(de, ate)
                if leitura.reconhecimento.reconhecida:
                    leitura.url = cand.href or entrada
                    leitura.menu = cand.texto
                    log.info("Pauta do %s achada pelo menu (“%s”): %s", self.nome, cand.texto,
                             leitura.url)
                    return leitura
                if nivel < 2:
                    # um nível abaixo: o item "Audiências" que abre a página com
                    # "Pauta de audiências"
                    subs = [c for c in self.candidatos_do_menu(tentados) if c.href]
                    fila.extend((sub, nivel + 1, entrada) for sub in subs[:3])
        return None
