"""Reconhecer a tabela de audiências - venha ela do portal, de uma planilha ou de um PDF.

Toda origem vira a mesma coisa: uma lista de Tabela (linhas de Celula,
com o texto, o valor tipado quando a planilha o tem, os links e as dicas -
o 'title' e o 'alt' das imagens, onde o portal costuma pôr "Segredo de
Justiça"). Daí em diante a regra é uma só (seção 8.5 da especificação):

* o cabeçalho é reconhecido por sinônimos (sem acento, em minúsculas, em
  dados/pauta.json): "Data/Hora", "Nº do Processo", "Tipo de Audiência"...;
* uma tabela é de audiências se o cabeçalho tiver DATA e (PROCESSO ou
  TIPO) - ou, sem cabeçalho, se ao menos metade das linhas tiver data e
  número CNJ;
* uma tabela de intimações, prazos ou movimentações tem data e processo
  também: o cabeçalho que fala de "prazo", "evento", "intimação"... sem
  nada que lembre audiência (hora, "audiência" na legenda) NÃO é pauta.
  Ler a lista de intimações como pauta encheria a tela de audiências que
  não existem;
* data e hora na mesma célula são separadas; linhas de grupo ("Segunda-
  feira, 05/10/2026") dão a data às linhas de baixo; linha sem data é
  ignorada (e contada), com aviso se trazia um processo.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser

from ..nucleo import cnj
from . import modelos
from .modelos import Audiencia, limpar, normalizar_texto

log = logging.getLogger("pauta.tabelas")

MAX_AVISOS = 20
MAX_LINHAS_CABECALHO = 6       # o cabeçalho é procurado nas primeiras linhas
MAX_CELULA_CABECALHO = 60      # célula mais longa que isto não é rótulo de coluna
_RE_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_NADA = re.compile(r"nenhum(a)?\s+(registro|audiencia|resultado|item)|"
                   r"nao (ha|foram encontrad|existem)|sem (registros|audiencias|resultados)", re.I)
_VERDADE = {"sim", "s", "x", "true", "verdadeiro", "1", "segredo de justica", "sigiloso",
            "sigilosa"}
# Coluna de contagem: a tabela é um resumo ("Tipo | Quantidade"), não a pauta.
COLUNAS_DE_CONTAGEM = {"quantidade", "qtd", "qtde", "total", "audiencias", "n de audiencias",
                       "numero de audiencias", "soma", "contagem"}
# Célula que é só a situação ("Cancelada"), para tabelas sem a coluna Situação.
ROTULOS_SITUACAO = {normalizar_texto(x) for x in (
    *modelos.SITUACOES, "cancelado", "realizado", "redesignado", "designado", "nao realizado",
    "suspenso", "adiada", "adiado", "remarcada", "remarcado")}


class _LinhaRecusada(ValueError):
    """A linha tem um defeito que o usuário precisa saber (vira aviso)."""


# =================================================================== estrutura
@dataclass
class Celula:
    texto: str = ""
    valor: object = None             # o valor tipado da planilha (date, time, float...)
    links: tuple[str, ...] = ()
    dicas: str = ""                  # title/alt dentro da célula
    th: bool = False
    aninhada: bool = False           # a célula tem outra tabela dentro (moldura de layout)

    @property
    def bruto(self):
        """O que a normalização lê: o valor tipado, se houver; senão o texto."""
        return self.valor if self.valor not in (None, "") else self.texto


@dataclass
class Tabela:
    linhas: list[list[Celula]]
    legenda: str = ""                # <caption> ou o texto logo antes da tabela
    origem: str = ""                 # URL do frame, arquivo e aba
    identificador: str = ""          # id/classe no portal, nome da aba

    @classmethod
    def de_textos(cls, linhas, **extra) -> "Tabela":
        """Tabela de linhas de valores (planilha, CSV, Word)."""
        saida = []
        for linha in linhas:
            celulas = []
            for v in linha:
                if isinstance(v, Celula):
                    celulas.append(v)
                elif v is None:
                    celulas.append(Celula())
                elif isinstance(v, str):
                    celulas.append(Celula(texto=limpar(v)))
                else:
                    celulas.append(Celula(texto=_texto_de_valor(v), valor=v))
            saida.append(celulas)
        return cls(linhas=saida, **extra)

    @classmethod
    def de_js(cls, dados: dict, origem: str = "") -> "Tabela":
        """A tabela lida no navegador (navegacao.JS_TABELAS)."""
        linhas = []
        for linha in dados.get("linhas") or []:
            celulas = []
            for c in linha:
                celula = Celula(texto=limpar(c.get("texto")), links=tuple(c.get("links") or ()),
                                dicas=limpar(c.get("dicas")), th=bool(c.get("th")),
                                aninhada=bool(c.get("aninhada")))
                celulas.append(celula)
                for _ in range(max(0, min(int(c.get("colspan") or 1), 30) - 1)):
                    celulas.append(Celula(th=celula.th))
            linhas.append(celulas)
        legenda = limpar(dados.get("legenda") or "") or limpar(dados.get("antes") or "")
        ident = " ".join(x for x in (dados.get("id") or "", dados.get("classes") or "") if x)
        return cls(linhas=linhas, legenda=legenda, origem=origem or dados.get("origem") or "",
                   identificador=ident)


def _texto_de_valor(v) -> str:
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M") if (v.hour or v.minute) else v.strftime("%d/%m/%Y")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return limpar(v)


# ========================================================== tabelas do HTML
class _LeitorTabelas(HTMLParser):
    """Todas as <table> do HTML (inclusive aninhadas), com links e dicas.

    O relatório "Excel" que o SAJ e o eProc exportam costuma ser HTML com
    extensão .xls; a página salva do portal também. O mesmo formato da
    leitura feita no navegador (navegacao.JS_TABELAS).
    """

    _VAZIOS = {"br", "img", "input", "meta", "link", "hr", "col", "wbr", "area", "base", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tabelas: list[dict] = []
        self._pilha: list[dict] = []          # tabelas abertas
        self._ignorar = 0                     # dentro de script/style
        self._texto_solto: list[str] = []     # texto fora de tabela (para a "legenda")
        self._em_caption = False

    # ---------------------------------------------------------------- apoio
    def _celula(self):
        if not self._pilha:
            return None
        t = self._pilha[-1]
        return t["celula"]

    def _escrever(self, texto: str) -> None:
        celula = self._celula()
        if self._pilha and self._em_caption:
            self._pilha[-1]["legenda"].append(texto)
        elif celula is not None:
            celula["texto"].append(texto)
        elif not self._pilha:
            self._texto_solto.append(texto)
            if len(self._texto_solto) > 60:
                del self._texto_solto[:-60]

    def _fechar_celula(self, t: dict) -> None:
        c = t["celula"]
        if c is not None:
            if t["linha"] is None:
                t["linha"] = []
                t["linhas"].append(t["linha"])
            t["linha"].append(c)
            t["celula"] = None

    def _fechar_linha(self, t: dict) -> None:
        self._fechar_celula(t)
        t["linha"] = None

    # ------------------------------------------------------------- eventos
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "template"):
            self._ignorar += 1
            return
        if self._ignorar:
            return
        if tag == "table":
            if self._pilha and self._pilha[-1]["celula"] is not None:
                self._pilha[-1]["celula"]["aninhada"] = True
            antes = limpar(" ".join(self._texto_solto))[-200:]
            self._pilha.append({"linhas": [], "linha": None, "celula": None, "legenda": [],
                                "id": a.get("id") or "", "classes": a.get("class") or "",
                                "antes": antes})
            self._texto_solto = []
            return
        if not self._pilha:
            if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "br"):
                self._texto_solto.append(" ")
            return
        t = self._pilha[-1]
        if tag == "caption":
            self._em_caption = True
        elif tag == "tr":
            self._fechar_linha(t)
            t["linha"] = []
            t["linhas"].append(t["linha"])
        elif tag in ("td", "th"):
            self._fechar_celula(t)
            try:
                colspan = int(a.get("colspan") or 1)
            except ValueError:
                colspan = 1
            t["celula"] = {"texto": [], "links": [], "dicas": [], "th": tag == "th",
                           "colspan": colspan, "aninhada": False}
        elif tag == "a" and t["celula"] is not None and a.get("href"):
            t["celula"]["links"].append(a["href"])
        elif tag in ("br", "p", "div", "li"):
            self._escrever(" ")
        if t["celula"] is not None:
            for chave in ("title", "alt"):
                if a.get(chave):
                    t["celula"]["dicas"].append(a[chave])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self._ignorar = max(0, self._ignorar - 1)
            return
        if self._ignorar or not self._pilha:
            return
        t = self._pilha[-1]
        if tag == "caption":
            self._em_caption = False
        elif tag in ("td", "th"):
            self._fechar_celula(t)
        elif tag == "tr":
            self._fechar_linha(t)
        elif tag == "table":
            self._fechar_linha(t)
            self._pilha.pop()
            self.tabelas.append(t)

    def handle_data(self, data):
        if not self._ignorar:
            self._escrever(data)

    def close(self):
        super().close()
        while self._pilha:                       # HTML cortado: fecha o que ficou aberto
            t = self._pilha.pop()
            self._fechar_linha(t)
            self.tabelas.append(t)


def tabelas_do_html(html: str, origem: str = "") -> list[Tabela]:
    leitor = _LeitorTabelas()
    try:
        leitor.feed(html or "")
        leitor.close()
    except Exception as erro:              # HTML muito estragado: o que deu para ler
        log.debug("HTML ilegível em parte (%s): %s", origem, erro)
    saida = []
    for t in leitor.tabelas:
        dados = {"linhas": [[{"texto": unescape("".join(c["texto"])), "links": c["links"],
                              "dicas": " ".join(c["dicas"]), "th": c["th"],
                              "colspan": c["colspan"], "aninhada": c["aninhada"]}
                             for c in linha] for linha in t["linhas"]],
                 "legenda": unescape(" ".join(t["legenda"])), "antes": t["antes"],
                 "id": t["id"], "classes": t["classes"]}
        saida.append(Tabela.de_js(dados, origem))
    return saida


# ============================================================ reconhecimento
@dataclass
class Reconhecimento:
    audiencias: list[Audiencia] = field(default_factory=list)
    tabelas: int = 0                 # tabelas reconhecidas como pauta (mesmo vazias)
    ignoradas: int = 0               # linhas com conteúdo que não viraram audiência
    avisos: list[str] = field(default_factory=list)
    total_informado: int | None = None   # "(12 registros)" da legenda, quando houver

    @property
    def reconhecida(self) -> bool:
        return self.tabelas > 0

    def avisar(self, texto: str) -> None:
        if len(self.avisos) < MAX_AVISOS:
            self.avisos.append(texto)
        elif len(self.avisos) == MAX_AVISOS:
            self.avisos.append("Há mais avisos; os primeiros estão acima.")

    def juntar(self, outro: "Reconhecimento") -> "Reconhecimento":
        vistos = {a.id: i for i, a in enumerate(self.audiencias)}
        for a in outro.audiencias:
            if a.id in vistos:
                self.audiencias[vistos[a.id]] = a
            else:
                vistos[a.id] = len(self.audiencias)
                self.audiencias.append(a)
        self.tabelas += outro.tabelas
        self.ignoradas += outro.ignoradas
        for aviso in outro.avisos:
            self.avisar(aviso)
        if outro.total_informado is not None:
            self.total_informado = (self.total_informado or 0) + outro.total_informado
        return self


def campo_do_cabecalho(texto: str, regras) -> str | None:
    """Que campo esta célula de cabeçalho nomeia (ou None).

    Primeiro a igualdade com um sinônimo; depois o começo ("Data da
    audiência designada" começa por "data da audiencia"), o sinônimo mais
    longo vencendo. "Dia da semana" e afins estão na lista de ignorar.
    """
    h = normalizar_texto(texto)
    if not h or len(h) > MAX_CELULA_CABECALHO or h in regras.ignorar:
        return None
    if any(h.startswith(x + " ") for x in regras.ignorar if len(x) > 3):
        return None
    for campo, sinonimos in regras.cabecalhos.items():
        if h in sinonimos:
            return campo
    melhor, tamanho = None, 0
    for campo, sinonimos in regras.cabecalhos.items():
        for s in sinonimos:
            if len(s) > tamanho and re.match(rf"{re.escape(s)}(?=[\s/(\-:]|$)", h) \
                    and len(h) - len(s) <= 30:
                melhor, tamanho = campo, len(s)
    return melhor


def mapear_cabecalho(linha: list[Celula], regras) -> dict[str, int]:
    """{campo: coluna}. Se dois rótulos nomeiam o mesmo campo, vale o primeiro."""
    mapa: dict[str, int] = {}
    for i, c in enumerate(linha):
        if c.aninhada:
            return {}
        if cnj.extrair_todos(c.texto) or modelos.ler_data(c.texto):
            continue                     # dado, não rótulo
        campo = campo_do_cabecalho(c.texto, regras)
        if campo and campo not in mapa:
            mapa[campo] = i
    return mapa


def _eh_pauta(mapa: dict[str, int], linha: list[Celula], contexto: str, regras) -> bool:
    if "data" not in mapa or not ({"processo", "tipo"} & set(mapa)):
        return False
    if "processo" not in mapa and any(normalizar_texto(c.texto) in COLUNAS_DE_CONTAGEM
                                      for c in linha):
        return False             # resumo (quantas por dia, por tipo): contagem, não audiência
    rotulos = " ".join(normalizar_texto(c.texto) for c in linha)
    audiencia = ("hora" in mapa or bool(regras.contexto_audiencia.search(rotulos))
                 or bool(regras.contexto_audiencia.search(contexto)))
    negativo = any(n in rotulos for n in regras.negativos)
    return audiencia or not negativo


def total_da_legenda(texto: str, regras) -> int | None:
    alvo = normalizar_texto(texto)
    for padrao in regras.legenda_total:
        m = padrao.search(alvo)
        if m:
            try:
                return int(m.group(1))
            except (IndexError, ValueError):
                continue
    return None


class Reconhecedor:
    """Transforma tabelas em audiências, com as regras do pauta.json."""

    def __init__(self, regras, sistema: str, tribunal: str = "", origem: str = "",
                 fonte: str = "", estrito: bool = True, agora: datetime | None = None):
        self.regras = regras
        self.sistema = sistema
        self.tribunal = (tribunal or "").upper()
        self.origem = origem
        self.fonte = fonte
        # estrito (páginas do portal): a tabela sem cabeçalho só vale com hora ou
        # com "audiência" por perto. Relatório importado pelo usuário: basta a
        # regra dos 50 %.
        self.estrito = estrito
        self.agora = (agora or datetime.now()).replace(microsecond=0)
        self._rotulos: dict[int, str] = {}       # o cabeçalho da tabela em curso

    # ------------------------------------------------------------ entrada
    def reconhecer(self, tabelas: list[Tabela], contexto: str = "") -> Reconhecimento:
        saida = Reconhecimento()
        for t in tabelas:
            saida.juntar(self.tabela(t, contexto))
        return saida

    def tabela(self, t: Tabela, contexto: str = "") -> Reconhecimento:
        r = Reconhecimento()
        linhas = [linha for linha in t.linhas if linha]
        if not linhas:
            return r
        ctx = normalizar_texto(" ".join(x for x in (t.legenda, contexto, t.identificador) if x))
        for i, linha in enumerate(linhas[:MAX_LINHAS_CABECALHO]):
            mapa = mapear_cabecalho(linha, self.regras)
            if mapa and _eh_pauta(mapa, linha, ctx, self.regras):
                r.tabelas = 1
                r.total_informado = total_da_legenda(t.legenda, self.regras)
                self._rotulos = {j: c.texto for j, c in enumerate(linha)}
                self._com_cabecalho(linhas[i + 1:], mapa, t, r)
                return r
            if mapa and len(mapa) >= 2 and "data" in mapa:
                # cabeçalho de outra coisa (intimações, prazos): não é pauta, e a
                # regra sem cabeçalho também não vale para ela
                return r
        self._sem_cabecalho(linhas, t, ctx, r)
        return r

    # ------------------------------------------------------- com cabeçalho
    def _com_cabecalho(self, linhas, mapa: dict[str, int], t: Tabela, r: Reconhecimento) -> None:
        data_corrente: date | None = None
        for numero, linha in enumerate(linhas, start=1):
            if any(c.aninhada for c in linha):
                continue
            textos = [c.texto for c in linha]
            cheias = [c for c in linha if c.texto or c.valor not in (None, "")]
            if not cheias:
                continue
            juntas = " ".join(textos)
            if self._parece_cabecalho(linha, juntas):
                continue                         # cabeçalho repetido (nova página do PDF)
            if len(cheias) == 1 and not cnj.extrair_todos(juntas):
                d = modelos.ler_data(cheias[0].bruto)
                if d is not None:
                    data_corrente = d            # linha de grupo: "Segunda-feira, 05/10/2026"
                    continue
                if _NADA.search(normalizar_texto(juntas)):
                    continue                     # "Nenhum registro encontrado"
            try:
                a = self._linha(linha, mapa, data_corrente, t)
            except _LinhaRecusada as recusa:
                r.ignoradas += 1
                r.avisar(f"Linha {numero}: {recusa}; a linha foi ignorada.")
                continue
            if a is None:
                if _NADA.search(normalizar_texto(juntas)):
                    continue
                r.ignoradas += 1
                processo = cnj.extrair_todos(juntas)
                if processo:
                    r.avisar(f"Linha {numero}: sem data reconhecível (processo "
                             f"{processo[0].formatado}); a linha foi ignorada.")
                continue
            r.audiencias.append(a)

    def _parece_cabecalho(self, linha, juntas: str) -> bool:
        if cnj.extrair_todos(juntas) or any(modelos.ler_data(c.bruto) for c in linha):
            return False
        mapa = mapear_cabecalho(linha, self.regras)
        return "data" in mapa and len(mapa) >= 2

    def _celula(self, linha, mapa, campo) -> Celula | None:
        i = mapa.get(campo)
        if i is None or i >= len(linha):
            return None
        return linha[i]

    def _texto(self, linha, mapa, campo) -> str:
        c = self._celula(linha, mapa, campo)
        return limpar(c.texto) if c is not None else ""

    def _linha(self, linha, mapa, data_corrente, t: Tabela) -> Audiencia | None:
        c_data = self._celula(linha, mapa, "data")
        c_hora = self._celula(linha, mapa, "hora")
        data_, hora = (modelos.ler_data_hora(c_data.bruto) if c_data is not None else (None, ""))
        if c_data is not None and data_ is None and c_data.texto:
            data_, hora = modelos.ler_data_hora(c_data.texto)
        if c_hora is not None:
            h = modelos.ler_hora(c_hora.bruto) or modelos.ler_hora(c_hora.texto)
            hora = h or hora
        if data_ is None:
            data_ = data_corrente
        if data_ is None:
            return None

        c_proc = self._celula(linha, mapa, "processo")
        processo, confiavel = (modelos.ler_processo(c_proc.bruto) if c_proc is not None
                               else ("", True))
        if not confiavel:
            raise _LinhaRecusada(
                "o número do processo foi guardado como NÚMERO na planilha, e o Excel corrompeu "
                "os últimos dígitos (o dígito verificador não confere). Formate a coluna como "
                "Texto e exporte de novo")
        if not processo and confiavel:
            processo, _ = modelos.ler_processo(c_proc.texto if c_proc is not None else "")
        if not processo and confiavel:
            # o número às vezes vem em outra coluna ("Processo/Partes"): a linha inteira
            processo, _ = modelos.ler_processo(" ".join(c.texto for c in linha))
        tipo_original = self._texto(linha, mapa, "tipo")
        partes = self._partes(linha, mapa)
        if not (processo or tipo_original or partes):
            return None                          # só data e hora não fazem uma audiência

        classe = self._texto(linha, mapa, "classe")
        if not classe and c_proc is not None and "classe" in normalizar_texto(
                self._rotulo_processo(mapa)):
            classe = limpar(cnj._PADRAO.sub(" ", c_proc.texto)).strip(" -–—/|")
        situacao_original = self._texto(linha, mapa, "situacao")
        if not situacao_original and "situacao" not in mapa:
            # sem a coluna, só um rótulo inteiro de situação numa célula conta
            # ("Cancelada"): uma palavra solta nas partes não muda nada
            for c in linha:
                if normalizar_texto(c.texto) in ROTULOS_SITUACAO:
                    situacao_original = c.texto
                    break
        if not tipo_original and "tipo" not in mapa:
            for c in linha:
                if c is c_proc or c is c_data:
                    continue
                if c.texto and len(c.texto) <= 80 and normalizar_texto(c.texto).startswith(
                        "audiencia"):
                    tipo_original = c.texto
                    break
        partes_limpas, sigilo_partes = self._tirar_mascara(partes)
        sigiloso = sigilo_partes or self._sigiloso(linha, mapa)
        tribunal = self.tribunal or self._texto(linha, mapa, "tribunal").upper() \
            or modelos.tribunal_do_processo(processo)
        return modelos.nova(
            sistema=self.sistema, tribunal=tribunal, data_=data_, processo=processo, hora=hora,
            tipo_original=tipo_original, situacao_original=situacao_original, regras=self.regras,
            local=self._texto(linha, mapa, "local"), link=self._link(linha, mapa),
            classe=classe, partes=partes_limpas,
            magistrado=self._texto(linha, mapa, "magistrado"),
            observacoes=self._texto(linha, mapa, "observacoes"), sigiloso=sigiloso,
            origem=self.origem or t.origem, fonte=self.fonte, capturada_em=self.agora)

    def _rotulo_processo(self, mapa) -> str:
        return self._rotulos.get(mapa.get("processo"), "")

    def _partes(self, linha, mapa) -> str:
        partes = self._texto(linha, mapa, "partes")
        if partes:
            return partes
        autor, reu = self._texto(linha, mapa, "autor"), self._texto(linha, mapa, "reu")
        if autor and reu:
            return f"{autor} x {reu}"
        return autor or reu

    def _tirar_mascara(self, partes: str) -> tuple[str, bool]:
        """"(Segredo de Justiça)" no lugar das partes: é sigilo, não nome."""
        if partes and self.regras.sigilo.search(normalizar_texto(partes)) and \
                len(normalizar_texto(partes).strip("() ")) <= 40:
            return "", True
        return partes, False

    def _sigiloso(self, linha, mapa) -> bool:
        c = self._celula(linha, mapa, "sigilo")
        if c is not None:
            valor = normalizar_texto(c.texto or c.dicas)
            if valor in _VERDADE:
                return True
            if valor and self._diz_sigilo(valor):
                return True
        for celula in linha:
            curto = celula.texto if len(celula.texto) < 80 else ""
            alvo = normalizar_texto(f"{celula.dicas} {curto}")
            if alvo and self._diz_sigilo(alvo):
                return True
        return False

    def _diz_sigilo(self, texto: str) -> bool:
        """"Segredo de Justiça (Nível 1)" sim; "Sem Sigilo (Nível 0)" não."""
        return bool(self.regras.sigilo.search(texto)) and not self.regras.sem_sigilo.search(texto)

    def _link(self, linha, mapa) -> str:
        c = self._celula(linha, mapa, "link")
        if c is not None:
            for href in c.links:
                if href.lower().startswith(("http://", "https://")):
                    return href
            m = _RE_URL.search(c.texto)
            if m:
                return m.group(0)
        for celula in linha:
            for href in celula.links:
                if href.lower().startswith(("http://", "https://")) and \
                        self.regras.link_virtual.search(href):
                    return href
            m = _RE_URL.search(celula.texto)
            if m and self.regras.link_virtual.search(m.group(0)):
                return m.group(0)
        return ""

    # ------------------------------------------------------ sem cabeçalho
    def _sem_cabecalho(self, linhas, t: Tabela, ctx: str, r: Reconhecimento) -> None:
        """A regra dos 50 %: linhas com data e UM número CNJ.

        Moldura de layout (célula com tabela dentro, ou com vários números)
        não conta: a tabela de dentro é lida por si.
        """
        cheias = [linha for linha in linhas
                  if any(c.texto for c in linha) and not any(c.aninhada for c in linha)]
        if not cheias:
            return
        boas = []
        for linha in cheias:
            juntas = " ".join(c.texto for c in linha)
            numeros = cnj.extrair_todos(juntas)
            d = next((modelos.ler_data(c.bruto) for c in linha if modelos.ler_data(c.bruto)), None)
            if len(numeros) == 1 and d is not None and len(juntas) <= 600:
                boas.append(linha)
        if not boas or len(boas) * 2 < len(cheias):
            return
        if self.estrito:
            com_hora = sum(1 for linha in boas
                           if modelos.ler_hora(" ".join(c.texto for c in linha)))
            if com_hora * 2 < len(boas) and not self.regras.contexto_audiencia.search(ctx):
                return
            if any(n in ctx for n in self.regras.negativos) and \
                    not self.regras.contexto_audiencia.search(ctx):
                return
        r.tabelas = 1
        r.total_informado = total_da_legenda(t.legenda, self.regras)
        for linha in cheias:
            a = self.linha_livre(linha, t)
            if a is None:
                r.ignoradas += 1
                continue
            r.audiencias.append(a)

    def linha_livre(self, linha, t: Tabela | None = None, data_padrao: date | None = None
                    ) -> Audiencia | None:
        """Uma linha sem cabeçalho: data, hora, processo e o que se reconhecer."""
        textos = [c.texto for c in linha if c.texto]
        juntas = " ".join(textos)
        data_ = None
        hora = ""
        for c in linha:
            d, h = modelos.ler_data_hora(c.bruto)
            if d is not None:
                data_, hora = d, h or hora
                break
        data_ = data_ or data_padrao
        if data_ is None:
            return None
        hora = hora or modelos.ler_hora(juntas)
        processo, _ = modelos.ler_processo(juntas)
        if not processo:
            return None
        tipo_original = ""
        situacao_original = ""
        for texto in textos:
            alvo = normalizar_texto(texto)
            if not tipo_original and (alvo.startswith("audiencia") or any(
                    p.search(alvo) for _, p in self.regras.tipos)) and len(alvo) <= 80 \
                    and not cnj.extrair_todos(texto):
                tipo_original = texto
            elif not situacao_original and len(alvo) <= 30 and \
                    modelos.situacao_reconhecida(texto, self.regras):
                situacao_original = texto
        if not tipo_original:
            for _, padrao in self.regras.tipos:
                m = padrao.search(normalizar_texto(juntas))
                if m:
                    tipo_original = juntas[m.start():m.end()]
                    break
        partes = next((x for x in textos if re.search(r"\s[xX]\s|\bversus\b|\bvs\.?\s", x)), "")
        partes, sigilo_partes = self._tirar_mascara(partes)
        alvo_sigilo = normalizar_texto(" ".join(c.dicas for c in linha) + " " + juntas)
        sigiloso = sigilo_partes or (bool(self.regras.sigilo.search(alvo_sigilo))
                                     and not self.regras.sem_sigilo.search(alvo_sigilo))
        tribunal = self.tribunal or modelos.tribunal_do_processo(processo)
        link = ""
        for celula in linha:
            for href in list(celula.links) + _RE_URL.findall(celula.texto):
                if self.regras.link_virtual.search(href):
                    link = href
                    break
            if link:
                break
        return modelos.nova(
            sistema=self.sistema, tribunal=tribunal, data_=data_, processo=processo, hora=hora,
            tipo_original=tipo_original, situacao_original=situacao_original, regras=self.regras,
            partes=partes, sigiloso=sigiloso, link=link,
            origem=self.origem or (t.origem if t else ""), fonte=self.fonte,
            capturada_em=self.agora)


def reconhecer(tabelas: list[Tabela], regras, sistema: str, tribunal: str = "", origem: str = "",
               fonte: str = "", estrito: bool = True, contexto: str = "",
               agora: datetime | None = None) -> Reconhecimento:
    """Atalho: as audiências de uma lista de tabelas."""
    return Reconhecedor(regras, sistema, tribunal, origem, fonte, estrito, agora).reconhecer(
        tabelas, contexto)
