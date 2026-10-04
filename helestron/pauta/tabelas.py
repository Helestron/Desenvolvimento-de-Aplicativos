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
  nada que lembre audiência NA PRÓPRIA TABELA (hora, "audiência" no
  cabeçalho ou na legenda) NÃO é pauta - o título da página não basta: a
  tela da pauta do portal costuma ter, ao lado, o painel de intimações. A
  exceção é a tabela com a cara da pauta (data com hora, processo, tipo e
  situação, com tipos de audiência na coluna Tipo) e uma coluna
  "Documento", "Intimação das partes", "Mandados"... ao lado: na página da
  pauta, e sem legenda própria de intimações ou prazos, ela é a pauta. No
  portal, a tabela só com data e processo (sem hora, tipo ou situação)
  também precisa de "audiência" ou "pauta" por perto: a fila de processos
  não é pauta. Ler a lista de intimações como pauta encheria a tela de
  audiências que não existem;
* o cabeçalho é procurado nas primeiras linhas, passando por cima do
  preâmbulo do relatório ("Data: 03/10/2026 | Hora: 10:15" da emissão,
  título, vara, período) e juntando o cabeçalho em duas linhas
  ("Audiência" mesclada sobre "Data | Hora");
* células mescladas na vertical (rowspan) valem para todas as linhas que
  cobrem, marcadas como herdadas: a linha cuja data, hora e processo são só
  os herdados (a audiência em duas linhas, com as partes embaixo) completa a
  de cima e não vira outra - a menos que traga o tipo ou a situação dela
  (outra audiência do mesmo processo no mesmo horário); data e hora na mesma
  célula são separadas;
  linhas de grupo ("Segunda-feira, 05/10/2026", com ou sem a contagem ao
  lado) dão a data às linhas de baixo, e a célula de data vazia repete a da
  linha de cima (relatório com a data só na primeira audiência do dia) se a
  linha tem hora própria ou, sem coluna de hora, o número na coluna
  Processo; linha sem data é ignorada (e contada), com aviso se trazia um
  processo.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser

from ..nucleo import cnj
from . import modelos
from .modelos import Audiencia, limpar, normalizar_texto

log = logging.getLogger("pauta.tabelas")

MAX_AVISOS = 20
MAX_LINHAS_CABECALHO = 15      # o cabeçalho é procurado nas primeiras linhas (após o preâmbulo)
MAX_CELULA_CABECALHO = 60      # célula mais longa que isto não é rótulo de coluna
MAX_ROWSPAN = 500
_RE_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_NADA = re.compile(r"nenhum(a)?\s+(registro|audiencia|resultado|item)|"
                   r"nao (ha|foram encontrad|existem)|sem (registros|audiencias|resultados)", re.I)
_VERDADE = {"sim", "s", "x", "true", "verdadeiro", "1", "segredo de justica", "sigiloso",
            "sigilosa"}
# O nível puro ("Nível 1", "2") é sigilo SÓ na coluna Sigilo: em outra célula,
# "Nível 1" é o andar do fórum ("Fórum Des. Fulano, Nível 1, Sala 3").
_NIVEL_DE_SIGILO = re.compile(r"\bnivel\s*[1-9]\b|^\(?\s*[1-9]\s*\)?$")
# As dicas de uma célula (o 'title' e o 'alt' de cada ícone) são guardadas juntas,
# separadas por isto: cada uma é julgada por si ("Visualizar" | "Sigiloso").
SEPARADOR_DICAS = " | "
# Coluna de contagem: a tabela é um resumo ("Tipo | Quantidade"), não a pauta.
COLUNAS_DE_CONTAGEM = {"quantidade", "qtd", "qtde", "total", "audiencias", "n de audiencias",
                       "numero de audiencias", "soma", "contagem"}
# Célula que é só a situação ("Cancelada"), para tabelas sem a coluna Situação.
ROTULOS_SITUACAO = {normalizar_texto(x) for x in (
    *modelos.SITUACOES, "cancelado", "realizado", "redesignado", "designado", "nao realizado",
    "suspenso", "adiada", "adiado", "remarcada", "remarcado")}
# O que acompanha a data numa linha de grupo: a contagem ("2 audiências",
# "Total: 3", "(3)") ou o dia da semana.
_ANOTACAO_DE_GRUPO = re.compile(
    r"^\(?\s*(?:(?:total|quantidade|qtde?|n)\s*(?:de\s+(?:audiencias?|registros?))?\s*:?\s*)?"
    r"\d{1,4}\s*(?:audiencias?|registros?|processos?|itens?)?\s*\)?$"
    r"|^(?:segunda|terca|quarta|quinta|sexta)(?:[\s-]*feira)?$|^(?:sabado|domingo)$")
# Texto que parece "Autor x Réu" (as partes fora da coluna Partes).
_PARECE_PARTES = re.compile(r"\s[xX]\s|\bversus\b|\bvs\.?\s")
_ROTULO_PARTES = re.compile(r"^\s*partes?\s*:\s*", re.I)


def _dicas(celula: "Celula") -> list[str]:
    """As dicas da célula, uma a uma (o 'title' e o 'alt' de cada ícone)."""
    return [x for x in (celula.dicas or "").split(SEPARADOR_DICAS.strip()) if x.strip()]


def tem_valores(linha) -> bool:
    """A linha traz dados (uma data, um número de processo): não é cabeçalho de colunas.

    "Data: | 03/10/2026 | Hora: | 10:15", da emissão do relatório, tem
    rótulos de coluna, mas é preâmbulo.
    """
    return any(cnj.extrair_todos(c.texto) or modelos.ler_data(c.bruto) is not None
               for c in linha)


def _juntar_cabecalhos(cima: list["Celula"], baixo: list["Celula"]) -> list["Celula"]:
    """O cabeçalho em duas linhas: o rótulo de baixo; onde ele falta, o de cima."""
    saida = []
    for j in range(max(len(cima), len(baixo))):
        b = baixo[j] if j < len(baixo) else None
        c = cima[j] if j < len(cima) else None
        saida.append(b if b is not None and b.texto else (c or b or Celula()))
    return saida


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
    # cópia da célula mesclada na vertical que começa numa linha de cima (rowspan
    # do HTML, mescla da planilha): vale nesta linha, mas não diz que ela é outra
    # audiência - a linha só com Data, Hora e Processo herdados é a continuação
    # da de cima (as partes ou um detalhe da mesma audiência)
    herdada: bool = False

    @property
    def bruto(self):
        """O que a normalização lê: o valor tipado, se houver; senão o texto."""
        return self.valor if self.valor not in (None, "") else self.texto

    @property
    def cheia(self) -> bool:
        return bool(self.texto) or self.valor not in (None, "")


def celula_de_valor(v, herdada: bool = False) -> Celula:
    """A célula de um valor de planilha (texto, data, número...) ou já pronta."""
    if isinstance(v, Celula):
        return replace(v, herdada=True) if herdada else v
    if v is None:
        return Celula(herdada=herdada)
    if isinstance(v, str):
        return Celula(texto=limpar(v), herdada=herdada)
    return Celula(texto=_texto_de_valor(v), valor=v, herdada=herdada)


@dataclass
class Tabela:
    linhas: list[list[Celula]]
    legenda: str = ""                # <caption> ou o texto logo antes da tabela
    origem: str = ""                 # URL do frame, arquivo e aba
    identificador: str = ""          # id/classe no portal, nome da aba

    @classmethod
    def de_textos(cls, linhas, **extra) -> "Tabela":
        """Tabela de linhas de valores (planilha, CSV, Word)."""
        saida = [[celula_de_valor(v) for v in linha] for linha in linhas]
        return cls(linhas=saida, **extra)

    @classmethod
    def de_js(cls, dados: dict, origem: str = "") -> "Tabela":
        """A tabela lida no navegador (navegacao.JS_TABELAS) ou no HTML.

        colspan: a célula ocupa as colunas seguintes (vazias). rowspan: ela
        vale também nas linhas de baixo, na mesma coluna - a data (ou a
        hora) escrita uma vez para as audiências do dia não some nelas, e as
        células seguintes não escorregam para a coluna errada. A cópia vai
        marcada como herdada (Celula.herdada).
        """
        linhas = []
        # coluna -> [célula que desce, quantas linhas ainda ocupa]
        descendo: dict[int, list] = {}
        for linha in dados.get("linhas") or []:
            celulas: list[Celula] = []
            de_cima = dict(descendo)
            novas: dict[int, list] = {}

            def cobrir() -> None:
                while len(celulas) in de_cima:
                    celulas.append(replace(de_cima[len(celulas)][0], herdada=True))

            for c in linha:
                cobrir()
                celula = Celula(texto=limpar(c.get("texto")), links=tuple(c.get("links") or ()),
                                dicas=limpar(c.get("dicas")), th=bool(c.get("th")),
                                aninhada=bool(c.get("aninhada")))
                inicio = len(celulas)
                largura = max(1, min(_inteiro(c.get("colspan"), 1), 30))
                celulas.append(celula)
                for _ in range(largura - 1):
                    celulas.append(Celula(th=celula.th))
                altura = max(1, min(_inteiro(c.get("rowspan"), 1), MAX_ROWSPAN))
                if altura > 1:
                    # a moldura de layout (tabela dentro) não se repete: vira célula vazia
                    copia = Celula(th=celula.th) if celula.aninhada else celula
                    novas[inicio] = [copia, altura - 1]
                    for k in range(1, largura):
                        novas[inicio + k] = [Celula(th=celula.th), altura - 1]
            if de_cima:
                while len(celulas) <= max(de_cima):
                    if len(celulas) in de_cima:
                        celulas.append(replace(de_cima[len(celulas)][0], herdada=True))
                    else:
                        celulas.append(Celula())
            descendo = {col: [cel, n - 1] for col, (cel, n) in de_cima.items() if n > 1}
            descendo.update(novas)
            linhas.append(celulas)
        legenda = limpar(dados.get("legenda") or "") or limpar(dados.get("antes") or "")
        ident = " ".join(x for x in (dados.get("id") or "", dados.get("classes") or "") if x)
        return cls(linhas=linhas, legenda=legenda, origem=origem or dados.get("origem") or "",
                   identificador=ident)


def _propria(c: Celula | None) -> bool:
    """A célula é desta linha (não é a cópia da mescla de cima) e tem conteúdo."""
    return c is not None and not c.herdada and c.cheia


def _tem_hora(c: Celula) -> bool:
    return bool(modelos.ler_hora(c.bruto) or modelos.ler_hora(c.texto))


def _inteiro(valor, padrao: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return padrao
    return n if n > 0 else padrao        # rowspan="0" (até o fim do grupo): fica em 1


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
            t["celula"] = {"texto": [], "links": [], "dicas": [], "th": tag == "th",
                           "colspan": _inteiro(a.get("colspan"), 1),
                           "rowspan": _inteiro(a.get("rowspan"), 1), "aninhada": False}
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
                              "dicas": SEPARADOR_DICAS.join(c["dicas"]), "th": c["th"],
                              "colspan": c["colspan"], "rowspan": c["rowspan"],
                              "aninhada": c["aninhada"]}
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


_RE_ROTULO_COM_HORA = re.compile(r"\bhora|\bhorario")


def _data_com_hora(mapa: dict[str, int], linha: list[Celula],
                   dados: list[list[Celula]] | None) -> bool:
    """A coluna de data traz também a hora? Pelo rótulo ("Data/Hora") ou porque
    ao menos metade das datas das linhas de baixo vem com o horário."""
    i = mapa.get("data")
    if i is None:
        return False
    if i < len(linha) and _RE_ROTULO_COM_HORA.search(normalizar_texto(linha[i].texto)):
        return True
    com_data = com_hora = 0
    for d in (dados or [])[:60]:
        if i >= len(d) or not d[i].cheia:
            continue
        data_, hora = modelos.ler_data_hora(d[i].bruto)
        if data_ is None and d[i].texto:
            data_, hora = modelos.ler_data_hora(d[i].texto)
        if data_ is not None:
            com_data += 1
            com_hora += bool(hora)
    return com_data > 0 and com_hora * 2 >= com_data


def _tipos_de_audiencia(mapa: dict[str, int], dados: list[list[Celula]] | None,
                       regras) -> bool:
    """Ao menos metade da coluna Tipo traz um tipo de audiência das regras
    ("Conciliação", "Audiência de Instrução"), e não "Intimação eletrônica",
    "Citação" ou "Intimação para a audiência": é o Tipo da pauta, não o do
    painel de intimações."""
    i = mapa.get("tipo")
    if i is None:
        return False
    cheias = tipos = 0
    for d in (dados or [])[:60]:
        if i >= len(d) or not d[i].texto:
            continue
        alvo = normalizar_texto(d[i].texto)
        cheias += 1
        if any(n in alvo for n in regras.negativos):
            continue
        tipos += alvo.startswith("audiencia") or any(p.search(alvo) for _, p in regras.tipos)
    return cheias > 0 and tipos * 2 >= cheias


def _eh_pauta(mapa: dict[str, int], linha: list[Celula], contexto: str, regras,
              contexto_pagina: str = "", estrito: bool = False,
              dados: list[list[Celula]] | None = None) -> bool:
    """O cabeçalho é de pauta? 'contexto': a legenda e o nome da PRÓPRIA tabela.

    O título da página ('contexto_pagina') não desfaz um cabeçalho de
    intimações ou prazos: a página da pauta tem, muitas vezes, o painel de
    intimações ao lado. A única exceção é a tabela que já tem a cara da
    pauta - data com hora, processo, tipo e situação, com tipos de audiência
    na coluna Tipo - e, ao lado, uma coluna "Documento" (a ata), "Intimação
    das partes", "Mandados"...: na página da pauta, ela é a pauta, a menos
    que a legenda ou o nome da própria tabela fale de intimações, prazos...
    (o painel "Intimações" com Tipo e Situação). 'dados': as linhas de baixo,
    para ver se as datas vêm com hora e o que a coluna Tipo traz. No portal
    ('estrito'), a tabela só com data e processo (sem hora, tipo nem
    situação) precisa de "audiência" ou "pauta" na própria tabela ou na
    página - uma fila de processos tem data e número também.
    """
    if "data" not in mapa or not ({"processo", "tipo"} & set(mapa)):
        return False
    if "processo" not in mapa and any(normalizar_texto(c.texto) in COLUNAS_DE_CONTAGEM
                                      for c in linha):
        return False             # resumo (quantas por dia, por tipo): contagem, não audiência
    rotulos = " ".join(normalizar_texto(c.texto) for c in linha)
    if ("hora" in mapa or regras.contexto_audiencia.search(rotulos)
            or regras.contexto_audiencia.search(contexto)):
        return True
    if any(n in rotulos for n in regras.negativos):
        # o painel de intimações ("Data | Processo | Evento | Prazo") e o de
        # expedientes (sem hora) não passam por aqui
        return ({"processo", "tipo", "situacao"} <= set(mapa)
                and bool(regras.contexto_audiencia.search(contexto_pagina))
                and not any(n in contexto for n in regras.negativos)
                and _data_com_hora(mapa, linha, dados)
                and _tipos_de_audiencia(mapa, dados, regras))
    if {"tipo", "situacao"} & set(mapa) or not estrito:
        return True
    return bool(regras.contexto_audiencia.search(contexto_pagina))


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
        ctx_tabela = normalizar_texto(" ".join(x for x in (t.legenda, t.identificador) if x))
        ctx_pagina = normalizar_texto(contexto)
        ctx = normalizar_texto(" ".join(x for x in (t.legenda, contexto, t.identificador) if x))
        outra_coisa = False
        anterior: list[Celula] | None = None
        for i, linha in enumerate(linhas[:MAX_LINHAS_CABECALHO]):
            if tem_valores(linha):
                anterior = None      # dado, ou preâmbulo "Data: | 03/10/2026": não é cabeçalho
                continue
            mapa = mapear_cabecalho(linha, self.regras)
            candidatos = [(mapa, linha)]
            if mapa and anterior is not None:
                junta = _juntar_cabecalhos(anterior, linha)
                candidatos.append((mapear_cabecalho(junta, self.regras), junta))
            for m, rotulos in candidatos:
                if m and _eh_pauta(m, rotulos, ctx_tabela, self.regras, ctx_pagina, self.estrito,
                                   linhas[i + 1:]):
                    r.tabelas = 1
                    r.total_informado = total_da_legenda(t.legenda, self.regras)
                    self._rotulos = {j: c.texto for j, c in enumerate(rotulos)}
                    self._com_cabecalho(linhas[i + 1:], m, t, r)
                    return r
            if mapa and len(mapa) >= 2 and "data" in mapa:
                # cabeçalho de outra coisa (intimações, prazos): se nenhum de pauta
                # vier abaixo, não é pauta - e a regra sem cabeçalho não vale para ela
                outra_coisa = True
            anterior = linha if mapa else None
        if outra_coisa:
            return r
        self._sem_cabecalho(linhas, t, ctx, r, ctx_tabela)
        return r

    # ------------------------------------------------------- com cabeçalho
    @staticmethod
    def _data_do_grupo(cheias: list[Celula], juntas: str) -> date | None:
        """A data de uma linha de grupo, ou None se a linha não é de grupo.

        "Segunda-feira, 05/10/2026" sozinha na linha (célula mesclada), ou
        acompanhada só da contagem ou do dia da semana ("05/10/2026" |
        "2 audiências"). Linha com número de processo nunca é de grupo.
        """
        if cnj.extrair_todos(juntas):
            return None
        com_data = [(c, modelos.ler_data(c.bruto)) for c in cheias]
        com_data = [(c, d) for c, d in com_data if d is not None]
        if len(com_data) != 1:
            return None
        celula, d = com_data[0]
        resto = [c for c in cheias if c is not celula]
        if all(_ANOTACAO_DE_GRUPO.match(normalizar_texto(c.texto)) for c in resto):
            return d
        return None

    def _com_cabecalho(self, linhas, mapa: dict[str, int], t: Tabela, r: Reconhecimento) -> None:
        data_grupo: date | None = None       # a da última linha de grupo
        data_corrente: date | None = None    # a última data vista (grupo ou audiência)
        ultima: Audiencia | None = None      # a audiência da linha de cima
        # "Data/Hora" numa coluna só: a célula vazia não tem nem o dia nem a hora
        data_tem_hora = bool(_RE_ROTULO_COM_HORA.search(normalizar_texto(
            self._rotulos.get(mapa.get("data"), ""))))
        for numero, linha in enumerate(linhas, start=1):
            if any(c.aninhada for c in linha):
                continue
            textos = [c.texto for c in linha]
            cheias = [c for c in linha if c.cheia]
            if not cheias:
                continue
            juntas = " ".join(textos)
            if self._parece_cabecalho(linha, juntas):
                ultima = None
                continue                         # cabeçalho repetido (nova página do PDF)
            d = self._data_do_grupo(cheias, juntas)
            if d is not None:
                data_grupo = data_corrente = d   # linha de grupo: "Segunda-feira, 05/10/2026"
                ultima = None
                continue
            if len(cheias) == 1 and _NADA.search(normalizar_texto(juntas)):
                continue                         # "Nenhum registro encontrado"
            c_data = self._celula(linha, mapa, "data")
            c_hora = self._celula(linha, mapa, "hora")
            c_proc = self._celula(linha, mapa, "processo")
            data_propria = _propria(c_data) and (modelos.ler_data(c_data.bruto) is not None
                                                 or modelos.ler_data(c_data.texto) is not None)
            hora_propria = _propria(c_hora) and _tem_hora(c_hora)
            # a hora sozinha na coluna de data ("10:00" embaixo de "Data/Hora")
            hora_na_data = _propria(c_data) and not data_propria and _tem_hora(c_data)
            if "processo" in mapa:
                processo_proprio = _propria(c_proc) and (
                    bool(cnj.extrair_todos(c_proc.texto))
                    or modelos.ler_processo(c_proc.bruto) != ("", True))
            else:                                # o número numa coluna sem rótulo próprio
                processo_proprio = bool(cnj.extrair_todos(
                    " ".join(c.texto for c in linha if not c.herdada)))
            herdou = any(c is not None and c.herdada and c.cheia for c in (c_data, c_hora, c_proc))
            if herdou and not (data_propria or hora_propria or hora_na_data or processo_proprio
                               or self._tipo_ou_situacao_proprios(linha, mapa)):
                # Data, Hora e Processo mesclados na vertical sobre a linha de baixo (as
                # partes, um detalhe): é a MESMA audiência, que ela completa - não outra.
                # Com tipo ou situação dela (a Conciliação cancelada e, embaixo, a
                # Instrução designada do mesmo processo no mesmo horário), é outra.
                if ultima is not None:
                    self._continuar(ultima, linha, mapa)
                continue
            # a célula de data VAZIA repete a de cima (a data escrita só na primeira
            # audiência do dia) - se a linha é mesmo outra audiência, com hora própria
            # (ou a hora mesclada de cima) ou, sem coluna de hora, com o número na
            # própria coluna Processo. O número em outra célula ("Apensado ao
            # processo...") ou a linha sem hora numa tabela que tem a coluna Hora
            # ("Aguardando designação") não herdam o dia de ninguém. Com outro texto
            # ("a designar"), só a data da linha de grupo vale.
            vazia = c_data is None or not c_data.cheia or hora_na_data
            hora_herdada = c_hora is not None and c_hora.herdada and _tem_hora(c_hora)
            outra = (hora_propria or hora_na_data or (processo_proprio and hora_herdada)
                     or (processo_proprio and "processo" in mapa and "hora" not in mapa
                         and not data_tem_hora))
            try:
                a = self._linha(linha, mapa, data_corrente if vazia and outra else data_grupo, t)
            except _LinhaRecusada as recusa:
                r.ignoradas += 1
                r.avisar(f"Linha {numero}: {recusa}; a linha foi ignorada.")
                ultima = None
                continue
            if a is None:
                ultima = None
                if _NADA.search(normalizar_texto(juntas)):
                    continue
                r.ignoradas += 1
                processo = cnj.extrair_todos(juntas)
                if processo:
                    r.avisar(f"Linha {numero}: sem data reconhecível (processo "
                             f"{processo[0].formatado}); a linha foi ignorada.")
                continue
            data_corrente = a.data
            ultima = a
            r.audiencias.append(a)

    def _parece_detalhe(self, texto: str) -> bool:
        """O texto é o detalhe de uma audiência (as partes, o selo de sigilo, o
        processo apensado, uma observação longa), não um tipo nem uma situação."""
        alvo = normalizar_texto(texto)
        return (not alvo or len(alvo) > 80 or bool(_PARECE_PARTES.search(texto))
                or bool(_ROTULO_PARTES.match(texto)) or bool(cnj.extrair_todos(texto))
                or self._diz_sigilo(alvo))

    def _eh_tipo(self, texto: str) -> bool:
        """Um tipo de audiência das regras ("Instrução", "Audiência de ..."), não "Outra"."""
        if self._parece_detalhe(texto):
            return False
        alvo = normalizar_texto(texto)
        return alvo.startswith("audiencia") or any(p.search(alvo) for _, p in self.regras.tipos)

    def _eh_situacao(self, texto: str) -> bool:
        """Uma situação das regras ("Designada", "Cancelada"), curta como um rótulo."""
        return (not self._parece_detalhe(texto) and len(normalizar_texto(texto)) <= 30
                and bool(modelos.situacao_reconhecida(texto, self.regras)))

    def _tipo_ou_situacao_proprios(self, linha, mapa) -> bool:
        """A linha cuja Data, Hora e Processo são os herdados da mescla de cima traz o
        tipo ou a situação DELA: é outra audiência do mesmo processo no mesmo horário
        (a Conciliação cancelada e a Instrução designada), não o detalhe da de cima.

        As partes numa célula larga sobre o Tipo e a Situação ("Partes: Fulano x
        Banco"), o selo de sigilo ou o processo apensado continuam detalhe.
        """
        c_tipo = self._celula(linha, mapa, "tipo")
        c_sit = self._celula(linha, mapa, "situacao")
        tipo = limpar(c_tipo.texto) if _propria(c_tipo) else ""
        situacao = limpar(c_sit.texto) if _propria(c_sit) else ""
        if (tipo and self._eh_tipo(tipo)) or (situacao and self._eh_situacao(situacao)):
            return True
        # tipo e situação em colunas separadas, cada um na sua célula: não é a
        # célula larga do detalhe, mesmo com um tipo ou uma situação fora das regras
        return bool(tipo and situacao and c_tipo is not c_sit
                    and not self._parece_detalhe(tipo) and not self._parece_detalhe(situacao))

    def _continuar(self, a: Audiencia, linha, mapa) -> None:
        """A linha de baixo da MESMA audiência (Data, Hora e Processo mesclados na
        vertical sobre ela) completa a de cima: as partes, o local, o selo de
        sigilo, uma observação. Ela não vira outra audiência - com o texto do
        detalhe no lugar do tipo, ela seria uma "Outra" a mais na pauta."""
        propria = [Celula() if c.herdada else c for c in linha]
        if self._sigiloso(propria, mapa):
            a.sigiloso = True
        usadas: set[int] = set()
        for campo in ("local", "classe", "magistrado"):
            i = mapa.get(campo)
            if i is not None and i < len(propria) and propria[i].texto:
                usadas.add(i)
                if not getattr(a, campo):
                    setattr(a, campo, limpar(propria[i].texto))
        if not a.link:
            a.link = self._link(propria, mapa)
        usadas |= {mapa[c] for c in ("link", "partes", "autor", "reu") if c in mapa}
        partes = self._partes(propria, mapa)
        da_coluna = bool(partes)
        if not partes:
            # "Autor: Fulano x Réu: Banco" numa célula larga, sob o Tipo e a Situação
            for i, c in enumerate(propria):
                if i not in usadas and c.texto and _PARECE_PARTES.search(c.texto):
                    partes = c.texto
                    usadas.add(i)
                    break
        partes, mascara = self._tirar_mascara(limpar(_ROTULO_PARTES.sub("", partes)))
        if mascara:
            a.sigiloso = True
        notas = []
        if partes:
            if not a.partes:
                a.partes = partes
            elif da_coluna:
                a.partes = f"{a.partes} {partes}"      # o nome que não coube na linha de cima
            else:
                notas.append(partes)
        for i, c in enumerate(propria):
            texto = limpar(c.texto)
            if i in usadas or not texto or texto in notas or texto in a.observacoes \
                    or (a.link and a.link in texto):
                continue
            if len(texto) <= 40 and self._diz_sigilo(normalizar_texto(texto)):
                continue                         # o selo "Segredo de Justiça": já valeu acima
            notas.append(texto)
        if notas:
            a.observacoes = "; ".join(x for x in (a.observacoes, *notas) if x)

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
        """"(Segredo de Justiça)" no lugar das partes: é sigilo, não nome.
        "Segredo de justiça: não" (ou "Sem segredo de justiça") não é máscara."""
        alvo = normalizar_texto(partes)
        if partes and len(alvo.strip("() ")) <= 40 and self._diz_sigilo(alvo):
            return "", True
        return partes, False

    def _sigiloso(self, linha, mapa) -> bool:
        c = self._celula(linha, mapa, "sigilo")
        if c is not None:
            # A coluna Sigilo: "Sim", "X", "Segredo de Justiça", e também o nível
            # puro ("Nível 1") - mas não "Não", "Nível 0", "Público", "Sem sigilo".
            for valor in ([c.texto] if c.texto.strip() else _dicas(c)):
                valor = normalizar_texto(valor)
                if not valor or self.regras.sem_sigilo.search(valor):
                    continue
                if valor in _VERDADE or _NIVEL_DE_SIGILO.search(valor) or \
                        self.regras.sigilo.search(valor):
                    return True
        return any(self._celula_sigilosa(celula, 80) for celula in linha)

    def _celula_sigilosa(self, celula: Celula, limite: int | None = None) -> bool:
        """O selo de sigilo numa célula: no 'title'/'alt' de um ícone ou no texto.

        Cada um é julgado por si, e nunca a linha inteira junta: "Ministério
        Público x Fulano" ao lado do ícone "Segredo de Justiça" não desfaz o
        sigilo (o rótulo "Público" do nível de sigilo só vale sozinho), e a
        negação de uma célula ("Segredo de justiça: não") não vale para outra.
        O número do processo sai do texto antes ("0700101-... (Sigiloso)").
        'limite': texto mais longo que isto (observações) não é selo.
        """
        texto = celula.texto if limite is None or len(celula.texto) < limite else ""
        if texto and self._diz_sigilo(normalizar_texto(cnj._PADRAO.sub(" ", texto))):
            return True
        return any(self._diz_sigilo(normalizar_texto(x)) for x in _dicas(celula))

    def _diz_sigilo(self, texto: str) -> bool:
        """"Segredo de Justiça (Nível 1)" sim; "Sem Sigilo (Nível 0)", "Segredo de
        justiça: não" e o "Nível 1" do andar do fórum não (dados/pauta.json)."""
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
    def _sem_cabecalho(self, linhas, t: Tabela, ctx: str, r: Reconhecimento,
                       ctx_tabela: str | None = None) -> None:
        """A regra dos 50 %: linhas com data e UM número CNJ.

        As linhas antes do primeiro dado (título, vara, período, "emitido
        por") não contam. Moldura de layout (célula com tabela dentro, ou
        com vários números) não conta: a tabela de dentro é lida por si. A
        linha cuja data e cujo número são só os herdados da mescla de cima,
        sem tipo nem situação próprios, é a continuação da audiência de cima
        (Reconhecedor._continuar).
        """
        ctx_tabela = ctx if ctx_tabela is None else ctx_tabela
        cheias = [linha for linha in linhas
                  if any(c.texto for c in linha) and not any(c.aninhada for c in linha)]
        if not cheias:
            return

        def continua(linha) -> bool:
            if not any(c.herdada and (cnj.extrair_todos(c.texto) or modelos.ler_data(c.bruto))
                       for c in linha):
                return False
            proprias = [c for c in linha if not c.herdada and c.cheia]
            # o tipo ou a situação DELA ("Audiência de Instrução", "Designada") embaixo
            # da data e do processo mesclados: é outra audiência no mesmo horário
            return not (cnj.extrair_todos(" ".join(c.texto for c in proprias))
                        or any(modelos.ler_data(c.bruto) or _tem_hora(c) for c in proprias)
                        or any(self._eh_tipo(c.texto) or self._eh_situacao(c.texto)
                               for c in proprias))

        def boa(linha) -> bool:
            juntas = " ".join(c.texto for c in linha)
            numeros = cnj.extrair_todos(juntas)
            d = next((modelos.ler_data(c.bruto) for c in linha if modelos.ler_data(c.bruto)), None)
            return (len(numeros) == 1 and d is not None and len(juntas) <= 600
                    and not continua(linha))

        primeira = next((i for i, linha in enumerate(cheias) if boa(linha)), None)
        if primeira is None:
            return
        cheias = cheias[primeira:]
        contadas = [linha for linha in cheias if not continua(linha)]
        boas = [linha for linha in contadas if boa(linha)]
        if len(boas) * 2 < len(contadas):
            return
        if self.estrito:
            com_hora = sum(1 for linha in boas
                           if modelos.ler_hora(" ".join(c.texto for c in linha)))
            if com_hora * 2 < len(boas) and not self.regras.contexto_audiencia.search(ctx):
                return
            # a legenda da PRÓPRIA tabela ("Intimações pendentes"): o título da
            # página ("Pauta de Audiências") não a desfaz
            if any(n in ctx_tabela for n in self.regras.negativos) and \
                    not self.regras.contexto_audiencia.search(ctx_tabela):
                return
        r.tabelas = 1
        r.total_informado = total_da_legenda(t.legenda, self.regras)
        ultima: Audiencia | None = None
        for linha in cheias:
            if continua(linha):
                if ultima is not None:
                    self._continuar(ultima, linha, {})
                continue
            a = self.linha_livre(linha, t)
            ultima = a
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
        partes = next((x for x in textos if _PARECE_PARTES.search(x)), "")
        partes, sigilo_partes = self._tirar_mascara(partes)
        # célula a célula: o "Ministério Público" das partes não desfaz o selo da outra
        sigiloso = sigilo_partes or any(self._celula_sigilosa(c) for c in linha)
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
