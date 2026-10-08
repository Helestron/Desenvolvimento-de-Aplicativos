"""Portal eProc: login do próprio usuário e os autos de cada processo num PDF único.

O eProc (TRF4, TRF2, TRF6, TJRS, TJSC, TJMG, TJTO, TJSP, TJAL...) é o mesmo
sistema em todo lugar, com variações de layout e de login. Mesmo contrato do
PortalESAJ (ver modelos.py): entrar() e baixar(numero, destino, senha).

O que este módulo faz, e a armadilha que cada passo contorna:

* login na janela do navegador. Senha (tela legada do InfraPHP ou
  Keycloak/SSO) com o segundo fator do aplicativo autenticador - o código é
  pedido ao usuário pela tela do programa (ctx.pedir_codigo) e digitado
  aqui; captcha/Turnstile e escolha de perfil ficam com o usuário, na
  própria janela; no modo manual o programa só espera. Depois do login a
  janela é minimizada (CDP) se o usuário não pediu para vê-la, e volta se
  for preciso de novo;
* o endereço do eProc de alguns tribunais ainda não está confirmado (TJAL):
  o catálogo traz candidatos, e vale o primeiro que mostrar a tela de
  entrada (o log diz qual);
* todo link interno do eProc leva um "hash" assinado para a sessão: uma URL
  montada à mão (controlador.php?acao=processo_selecionar&num_processo=...)
  é recusada com "Link sem assinatura". Por isso o processo é aberto pela
  pesquisa rápida, ou pela consulta processual (que devolve o
  linkProcessoAssinado), e todo link usado é colhido da própria página;
* o eProc não entrega o processo num PDF na hora (o "Download Completo" é
  agendado e leva de minutos a horas): o PDF é montado aqui, documento a
  documento, do evento mais antigo ao mais novo, SEM capa e sem página
  nenhuma inserida antes ou entre os documentos - o eProc não numera folhas,
  e cada documento conserva a paginação própria (cita-se "evento N, RÓTULO,
  p. Y"). O documento que não veio, ou a gravação, tem UMA página de aviso no
  lugar, marcada como não citável. Cada documento tem um marcador "Evento N —
  descrição — rótulo (data)" e rótulos de página ("Ev. 1 INIC1 p. 2"); o PDF
  leva metadados e o manifesto de paginação (nucleo.paginacao). Os dados da
  capa (classe, partes, como citar, o mapa dos documentos) vão para
  _controle/<nome do PDF>_capa.txt e _capa.json e para o manifesto. O Download
  Completo nativo é opcional ([eproc] modo = completo): o arquivo do eProc
  entra intacto (a página M do PDF é a página M dele) e, se falhar ou demorar,
  cai no modo por documentos;
* cada documento vem pelo contexto autenticado
  (acessar_documento_implementacao); se não vier, pela moldura
  (iframe#conteudoIframe). PDF, HTML (ISO-8859-1, do editor do eProc),
  imagem e mídia têm cada um o seu tratamento; o que não vier de jeito
  nenhum vira página de aviso e é anotado em "incompleto";
* a sessão do eProc cai sem aviso: vira SessaoPerdida, e o motor entra de
  novo e recomeça o processo - os links colhidos na sessão anterior
  perderam a validade;
* o 2º grau é outra instalação do eProc (no TJAL, eproc2g), com login,
  senha guardada, perfil do navegador e sessão próprios (a chave
  'eproc2g:TJAL'): o grau vem SÓ do Tribunal que o motor passa
  (Tribunal.no_grau("2g")), de onde saem também a credencial e o perfil - um
  grau= diferente dele é recusado, para a senha de um grau nunca ir ao
  portal do outro. Sem o endereço do grau no catálogo, o portal nem abre
  (urls_para é estrito no 2º grau). O manifesto, a capa JSON e os eventos
  do 2º grau levam "grau": "2g"; os autos e a capa são gravados pelo nome
  do destino ("<número> (2G).pdf"). Os eventos "de outro grau" (os do
  processo de origem) ficam de fora nesta versão: o PDF traz os eventos do
  próprio processo do 2º grau.

Seletores: listas de alternativas por chave (SELETORES_PADRAO), com correção
sem mexer no código em seletores-eproc.json, na pasta de dados do Helestron
(%LOCALAPPDATA%\\Helestron, que a atualização não apaga), no formato
{"pesquisa_rapida": ["#campoNovo"], ...} (ou {"eproc": {...}}, também aceito
no seletores.json da mesma pasta). Os do usuário vêm na frente; os padrões
ficam de reserva. As chaves usadas na leitura do HTML (eventos, capa, partes) aceitam
CSS simples: tag, #id, .classe, [atributo], [a=v], [a^=v], [a*=v], [a$=v],
descendente e ">".
"""

from __future__ import annotations

import base64
import codecs
import configparser
import functools
import html as _html
import io
import json
import logging
import re
import time
import urllib.parse
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

from ..nucleo import caminhos, paginacao, sistema
from ..nucleo.cnj import Numero, normalizar_grau
from . import pdf
from .contexto import Contexto
from .modelos import (AJUSTES_ACESSOS, CAMPO_PRAZO_LOGIN, ENTRAR_MANUALMENTE,
                      MOSTRAR_NAVEGADOR, NAO_ENCONTRADO, OK, ONDE_CADASTRAR_ACESSO,
                      ONDE_CORRIGIR_ENDERECO, PERFIL_EPROC, SEM_ACESSO, SIGILOSO_SEM_SENHA,
                      TENTAR_DE_NOVO, Cancelado, LoginFalhou, PortalIndisponivel, ProcessoNaoEncontrado,
                      ResultadoProcesso, SemAcesso, SessaoPerdida, SigilosoSemSenha, dica_de_grau)
from .navegador import (DICA_DIAGNOSTICO, DICA_SEM_DIAGNOSTICO, diagnosticar_processo,
                        explicar_erro, primeiro_visivel, recusou_credenciais, sem_acento)

log = logging.getLogger("download.eproc")

PAUSA_DOCUMENTOS_S = 0.5      # entre um documento e outro: rajada parece abuso
ESPERA_COMPLETO_MIN = 8       # Download Completo: depois disso, monta por documentos
INTERVALO_COMPLETO_S = 3.0    # consulta da página de "gerando o arquivo"
MAX_CODIGOS = 5               # códigos do autenticador por login
MAX_ENVIOS_SENHA = 2          # envios da senha sem resposta clara (o eProc bloqueia o
                              # usuário depois de poucas tentativas erradas)
MODOS_PDF = ("documentos", "completo")
TITULO_COMPLETO = "Autos completos (arquivo gerado pelo eProc)"

# data-mimetype do link do documento (o eProc escreve a extensão)
MIMETYPES_MIDIA = frozenset({
    "mp3", "mp4", "wav", "ogg", "oga", "ogv", "webm", "wma", "wmv", "avi", "mov", "m4a",
    "m4v", "mpeg", "mpg", "mp2", "3gp", "flac", "aac", "mkv", "asf", "audio", "video"})
MIMETYPES_IMAGEM = frozenset({"jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "webp"})

SELETORES_PADRAO: dict[str, list[str]] = {
    # login: tela legada (InfraPHP) e Keycloak/SSO (TJSC, TJSP, JFRS)
    "login_usuario": ["input#txtUsuario", "input#username", "input[name='txtUsuario']",
                      "input[name='username']"],
    "login_senha": ["input#pwdSenha", "input#password", "input[name='pwdSenha']",
                    "input[name='password']"],
    "login_botao": ["#sbmEntrar", "#kc-login", "button[type='submit']", "input[type='submit']"],
    "otp_campo": ["input#otp", "input#txtAcessoCodigo", "input[name='otp']",
                  "input[name='txtAcessoCodigo']", "input[autocomplete='one-time-code']"],
    "otp_botao": ["#btnValidar", "#kc-login", "button[type='submit']", "input[type='submit']"],
    "senha_nova": ["#password-new", "#kc-passwd-update-form"],
    "captcha": ["#divInfraCaptcha", "div.cf-turnstile", "#challenge-stage",
                "iframe[src*='challenges.cloudflare.com']"],
    "perfil": ["button[data-descricao]", "a[data-descricao]", "input[data-descricao]"],
    # abertura do processo
    "pesquisa_rapida": ["input[name='txtNumProcessoPesquisaRapida']",
                        "#txtNumProcessoPesquisaRapida"],
    "menu_consulta": ["a[href*='acao=processo_consultar']"],
    "consulta_tipo_numero": ["input[type='radio'][name='tipoPesquisa'][value='NU']",
                             "input[type='radio'][value='NU']"],
    "consulta_numero": ["#numNrProcesso", "input[name='numNrProcesso']"],
    "consulta_botao": ["#sbmConsultar", "#btnPesquisar", "#frmProcessoLista button[type='submit']",
                       "input[type='submit'][value*='onsultar']"],
    # página do processo (lida também em Python: só CSS simples)
    "processo_pagina": ["#txtNumProcesso", "#tblEventos", "#fldCapa"],
    "capa_numero": ["#txtNumProcesso"],
    "capa_classe": ["#txtClasse"],
    "capa_competencia": ["#txtCompetencia"],
    "capa_autuacao": ["#txtAutuacao"],
    "capa_situacao": ["#txtSituacao"],
    "capa_orgao": ["#txtOrgaoJulgador"],
    "capa_magistrado": ["#txtMagistrado"],
    "capa_assunto": ["#txtAssunto"],
    "capa_valor": ["#txtValorCausa"],
    "partes_tabela": ["#tblPartesERepresentantes"],
    "parte_nome": ["a.infraNomeParte", "span.infraNomeParte"],
    "eventos_tabela": ["#tblEventos"],
    "eventos_linha": ["tr[id^='trEvento']"],
    "evento_descricao": ["label.infraEventoDescricao"],
    "evento_usuario": ["label.infraEventoUsuario"],
    "evento_documento": ["a.infraLinkDocumento", "a[href*='acao=acessar_documento']"],
    "eventos_paginacao": ["#selPaginacaoT", "#selPaginacaoB", "select[id^='selPaginacao']"],
    # Botão "listar todos os eventos" (se a versão do eProc tiver): vazio por
    # padrão; quem o confirmar num tribunal pode pô-lo no seletores-eproc.json.
    "eventos_listar_todos": [],
    # documento e Download Completo
    "documento_iframe": ["iframe#conteudoIframe", "#conteudoIframe",
                         "iframe[name='conteudoIframe']"],
    "completo_botao": ["#btnDownloadCompletoRS", "#btnDownloadCompleto",
                       "[onclick*='agendar_arquivo_completo']",
                       "a[href*='agendar_arquivo_completo']"],
    "completo_formulario": ["#frmProcessosSelecionados"],
    "completo_marcar": ["input[name='arrChkProcessos[]']"],
    "completo_gerar": ["#btnGerar"],
}


def carregar_seletores(arquivo: Path | None = None) -> dict[str, list[str]]:
    """Seletores padrão, com os do usuário na frente.

    Lê seletores-eproc.json ({"chave": [...]} ou {"eproc": {...}}) e a
    seção "eproc" de seletores.json (o mesmo arquivo do e-SAJ), na pasta de
    dados do Helestron (e, de reserva, na pasta dados do programa: ver
    esaj.arquivos_de_seletores). Arquivo ausente é o normal; arquivo
    estragado é avisado e ignorado.
    """
    from .esaj import arquivos_de_seletores

    sel = {k: list(v) for k, v in SELETORES_PADRAO.items()}
    if arquivo is not None:
        fontes = [Path(arquivo)]
    else:
        fontes = arquivos_de_seletores("seletores.json", "seletores-eproc.json")
    for alvo in fontes:
        try:
            dados = json.loads(alvo.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as erro:
            log.warning("%s ilegível (%s); uso os seletores padrão.", alvo, erro)
            continue
        if not isinstance(dados, dict):
            continue
        if isinstance(dados.get("eproc"), dict):
            dados = dados["eproc"]
        elif alvo.name == "seletores.json":
            continue               # só a seção "eproc" desse arquivo é nossa
        for chave, lista in dados.items():
            if isinstance(lista, str):
                lista = [lista]
            if not isinstance(lista, list) or chave.startswith("_"):
                continue
            proprios = [s for s in lista if isinstance(s, str) and s.strip()]
            sel[chave] = proprios + [s for s in sel.get(chave, []) if s not in proprios]
    return sel


# ================================================== leitura de HTML (sem bs4)
# O HTML vem de page.content() - já serializado pelo Chromium, bem formado -,
# e é lido aqui em Python para que a extração de eventos, capa e links possa
# ser testada sem navegador.
_VAZIOS = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_SEPARADORES = frozenset(
    "address article aside blockquote br dd div dl dt fieldset figcaption figure footer form "
    "h1 h2 h3 h4 h5 h6 header hr legend li main nav ol p pre section table tbody td tfoot th "
    "thead tr ul a label option select textarea button".split())
_SEM_TEXTO = frozenset(("script", "style", "noscript", "template"))
_RAIZ = "#documento"


def limpar(texto: str | None) -> str:
    """Espaços normalizados (inclusive o &nbsp;, que o eProc usa muito)."""
    return re.sub(r"\s+", " ", (texto or "").replace("\xa0", " ")).strip()


class No:
    """Elemento (ou trecho de texto, quando ``tag`` é None) de uma página lida."""

    __slots__ = ("tag", "attrs", "filhos", "pai", "dado")

    def __init__(self, tag: str | None, attrs: dict | None = None, pai: "No | None" = None,
                 dado: str = ""):
        self.tag = tag
        self.attrs = attrs or {}
        self.filhos: list[No] = []
        self.pai = pai
        self.dado = dado

    def attr(self, nome: str, padrao: str = "") -> str:
        valor = self.attrs.get(nome)
        return padrao if valor is None else valor

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def elementos(self):
        """Os elementos descendentes, em ordem de documento."""
        pilha = list(reversed(self.filhos))
        while pilha:
            no = pilha.pop()
            if no.tag is None:
                continue
            yield no
            pilha.extend(reversed(no.filhos))

    def texto(self, excluir: tuple = ()) -> str:
        """O texto do elemento, sem scripts, com espaços normalizados.

        Elementos de bloco, células e links viram fronteira de palavra:
        "<a>INIC1</a><a>PROC2</a>" é "INIC1 PROC2", e não "INIC1PROC2".
        """
        partes: list[str] = []
        excluidos = {id(x) for x in excluir}
        pilha: list = list(reversed(self.filhos))
        while pilha:
            item = pilha.pop()
            if isinstance(item, str):
                partes.append(item)
                continue
            if item.tag is None:
                partes.append(item.dado)
                continue
            if item.tag in _SEM_TEXTO or id(item) in excluidos:
                continue
            separa = item.tag in _SEPARADORES
            if separa:
                partes.append(" ")
                pilha.append(" ")
            pilha.extend(reversed(item.filhos))
        return limpar("".join(partes))


class _Leitor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = No(_RAIZ)
        self.pilha = [self.raiz]

    def _topo(self) -> str:
        return self.pilha[-1].tag or ""

    def _fechar_implicitos(self, tag: str) -> None:
        if tag in ("td", "th"):
            while len(self.pilha) > 1 and self._topo() in ("td", "th"):
                self.pilha.pop()
        elif tag == "tr":
            while len(self.pilha) > 1 and self._topo() in ("td", "th", "tr"):
                self.pilha.pop()
        elif tag in ("tbody", "thead", "tfoot"):
            while len(self.pilha) > 1 and self._topo() in ("td", "th", "tr", "tbody", "thead",
                                                            "tfoot"):
                self.pilha.pop()
        elif tag in ("li", "option", "p", "dt", "dd") and self._topo() == tag:
            self.pilha.pop()

    def _abrir(self, tag: str, attrs, vazio: bool) -> None:
        tag = tag.lower()
        self._fechar_implicitos(tag)
        topo = self.pilha[-1]
        no = No(tag, {k.lower(): ("" if v is None else v) for k, v in attrs}, topo)
        topo.filhos.append(no)
        if not vazio and tag not in _VAZIOS:
            self.pilha.append(no)

    def handle_starttag(self, tag, attrs):
        self._abrir(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._abrir(tag, attrs, True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.pilha) - 1, 0, -1):
            if self.pilha[i].tag == tag:
                del self.pilha[i:]
                return

    def handle_data(self, data):
        if data:
            topo = self.pilha[-1]
            topo.filhos.append(No(None, pai=topo, dado=data))


def ler_html(html: str) -> No:
    leitor = _Leitor()
    try:
        leitor.feed(html or "")
        leitor.close()
    except Exception as erro:          # HTML muito estragado: fica o que deu para ler
        log.debug("HTML lido pela metade: %s", erro)
    return leitor.raiz


# ----------------------------------------------------------- CSS simples
@dataclass
class _Composto:
    tag: str = ""
    id: str = ""
    classes: tuple = ()
    attrs: tuple = ()           # (nome, operador | None, valor, sem_caixa)
    combinador: str = ""        # relação com o composto à esquerda: " " ou ">"


_RE_ATRIBUTO = re.compile(
    r"""^\s*([\w:-]+)\s*(?:([~^$*|]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\s"']+)))?\s*(i)?\s*$""",
    re.I)


def _dividir(texto: str, sep: str) -> list[str]:
    """Divide por ``sep`` fora de colchetes e aspas."""
    partes, atual, nivel, aspa = [], [], 0, ""
    for c in texto:
        if aspa:
            atual.append(c)
            if c == aspa:
                aspa = ""
            continue
        if c in "\"'":
            aspa = c
        elif c == "[":
            nivel += 1
        elif c == "]":
            nivel = max(0, nivel - 1)
        elif c == sep and nivel == 0:
            partes.append("".join(atual))
            atual = []
            continue
        atual.append(c)
    partes.append("".join(atual))
    return partes


def _cadeia(seletor: str) -> tuple | None:
    s = seletor.strip()
    if not s:
        return None
    compostos: list[_Composto] = []
    atual: _Composto | None = None
    combinador = " "
    espaco = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            espaco = True
            i += 1
            continue
        if c == ">":
            combinador, atual, espaco = ">", None, False
            i += 1
            continue
        if c in "+~:,()":
            return None                     # pseudo-classes e irmãos: não suportados
        if espaco and atual is not None:
            atual, combinador = None, " "
        espaco = False
        if atual is None:
            atual = _Composto(combinador=combinador if compostos else "")
            compostos.append(atual)
            combinador = " "
        if c == "#":
            m = re.match(r"#([\w-]+)", s[i:])
            if not m:
                return None
            atual.id = m.group(1)
            i += m.end()
        elif c == ".":
            m = re.match(r"\.([\w-]+)", s[i:])
            if not m:
                return None
            atual.classes += (m.group(1),)
            i += m.end()
        elif c == "[":
            j, aspa = i + 1, ""
            while j < n and (aspa or s[j] != "]"):
                if aspa and s[j] == aspa:
                    aspa = ""
                elif not aspa and s[j] in "\"'":
                    aspa = s[j]
                j += 1
            m = _RE_ATRIBUTO.match(s[i + 1:j])
            if j >= n or not m:
                return None
            valor = next((g for g in (m.group(3), m.group(4), m.group(5)) if g is not None), None)
            atual.attrs += ((m.group(1).lower(), m.group(2), valor, bool(m.group(6))),)
            i = j + 1
        elif c == "*":
            i += 1
        elif c.isalpha():
            m = re.match(r"[A-Za-z][\w-]*", s[i:])
            if atual.tag or atual.id or atual.classes or atual.attrs:
                return None
            atual.tag = m.group(0).lower()
            i += m.end()
        else:
            return None
    return tuple(compostos) or None


@functools.lru_cache(maxsize=512)
def _compilar(seletor: str) -> tuple:
    """Seletor (com vírgulas) -> cadeias suportadas. Alternativa que usa algo
    fora do CSS simples (":has-text", "+") é ignorada aqui - continua valendo
    no navegador."""
    return tuple(c for c in (_cadeia(p) for p in _dividir(seletor or "", ",")) if c)


def _casa_composto(no: No, p: _Composto) -> bool:
    if p.tag and no.tag != p.tag:
        return False
    if p.id and no.attrs.get("id") != p.id:
        return False
    if p.classes:
        classes = no.classes
        if not all(c in classes for c in p.classes):
            return False
    for nome, op, valor, sem_caixa in p.attrs:
        atual = no.attrs.get(nome)
        if atual is None:
            return False
        if op is None:
            continue
        a, v = (atual.lower(), (valor or "").lower()) if sem_caixa else (atual, valor or "")
        if op == "=" and a != v:
            return False
        if op == "^=" and not (v and a.startswith(v)):
            return False
        if op == "$=" and not (v and a.endswith(v)):
            return False
        if op == "*=" and not (v and v in a):
            return False
        if op == "~=" and v not in a.split():
            return False
        if op == "|=" and not (a == v or a.startswith(v + "-")):
            return False
    return True


def _casa(no: No, cadeia: tuple, i: int) -> bool:
    p = cadeia[i]
    if not _casa_composto(no, p):
        return False
    if i == 0:
        return True
    pai = no.pai
    if p.combinador == ">":
        return pai is not None and pai.tag not in (None, _RAIZ) and _casa(pai, cadeia, i - 1)
    while pai is not None and pai.tag not in (None, _RAIZ):
        if _casa(pai, cadeia, i - 1):
            return True
        pai = pai.pai
    return False


def _lista(seletores) -> list[str]:
    if isinstance(seletores, str):
        return [seletores]
    return [s for s in (seletores or []) if isinstance(s, str) and s.strip()]


def buscar(raiz: No, seletores) -> list[No]:
    """Os elementos que casam com QUALQUER seletor da lista, em ordem de documento."""
    cadeias = [c for s in _lista(seletores) for c in _compilar(s)]
    if not cadeias or raiz is None:
        return []
    return [no for no in raiz.elementos() if any(_casa(no, c, len(c) - 1) for c in cadeias)]


def primeiro(raiz: No, seletores) -> No | None:
    """O primeiro elemento do primeiro seletor da lista que achar algo (a ordem
    da lista é a de preferência, como em navegador.primeiro_visivel)."""
    if raiz is None:
        return None
    for s in _lista(seletores):
        cadeias = _compilar(s)
        if not cadeias:
            continue
        for no in raiz.elementos():
            if any(_casa(no, c, len(c) - 1) for c in cadeias):
                return no
    return None


# ================================================= eventos e documentos
@dataclass
class Documento:
    """Um documento de um evento (o link "INIC1", "PET1", "SENT1"...)."""
    evento: int
    data: str              # dd/mm/aaaa
    hora: str
    descricao: str         # a do evento
    rotulo: str            # INIC1
    href: str              # como está na página (relativo ou absoluto)
    mimetype: str = ""     # data-mimetype (pdf, html, jpg, mp4...)
    titulo: str = ""       # atributo title
    id: str = ""           # data-doc, ou o parâmetro doc do link
    ordem: int = 0         # posição dentro do evento


@dataclass
class Evento:
    numero: int
    data: str
    hora: str
    descricao: str
    usuario: str = ""
    documentos: list[Documento] = field(default_factory=list)

    @property
    def chave(self) -> str:
        return str(self.numero) if self.numero > 0 else f"{self.data} {self.hora} {self.descricao}"


_RE_DATA = re.compile(r"(\d{2}/\d{2}/\d{4})(?:\D{1,3}(\d{2}:\d{2}(?::\d{2})?))?")


def _primeiro_inteiro(texto: str) -> int:
    m = re.search(r"\d+", texto or "")
    return int(m.group(0)) if m else 0


def parametros(url: str) -> dict[str, str]:
    consulta = urllib.parse.urlsplit(url or "").query
    return {k: v[0] for k, v in urllib.parse.parse_qs(consulta, keep_blank_values=True).items()}


_RE_LINK_DOCUMENTO = re.compile(
    r"""((?:[\w.:/-]*/)?controlador\.php\?acao=acessar_documento[^'"\s<>)]*)""")


def _link_no_script(texto: str) -> str:
    """O endereço de documento escrito num onclick ("window.open('...')")."""
    m = _RE_LINK_DOCUMENTO.search(_html.unescape(texto or ""))
    return m.group(1) if m else ""


def ler_eventos(fonte, sel: dict | None = None) -> list[Evento]:
    """Os eventos (com seus documentos) de UMA página do processo.

    Linha: tr[id^=trEvento] com as colunas [nº | data e hora | descrição
    (label.infraEventoDescricao) | usuário | documentos (a.infraLinkDocumento,
    com data-doc, data-mimetype e title; o texto é o rótulo)]. O mesmo
    documento pode ter dois links (ícone e texto): vale um só.
    """
    sel = sel or SELETORES_PADRAO
    raiz = fonte if isinstance(fonte, No) else ler_html(fonte)
    escopo = primeiro(raiz, sel.get("eventos_tabela", [])) or raiz
    eventos: list[Evento] = []
    for tr in buscar(escopo, sel.get("eventos_linha", [])):
        celulas = [f for f in tr.filhos if f.tag in ("td", "th")]
        if not celulas:
            continue
        numero = _primeiro_inteiro(celulas[0].texto()) or _primeiro_inteiro(tr.attr("id"))
        m = _RE_DATA.search(celulas[1].texto()) if len(celulas) > 1 else None
        m = m or _RE_DATA.search(tr.texto())
        data, hora = (m.group(1), m.group(2) or "") if m else ("", "")
        no_desc = primeiro(tr, sel.get("evento_descricao", []))
        if no_desc is not None:
            descricao = no_desc.texto()
        else:
            descricao = celulas[2].texto() if len(celulas) > 2 else ""
        no_usu = primeiro(tr, sel.get("evento_usuario", []))
        usuario = no_usu.texto() if no_usu is not None else ""
        evento = Evento(numero, data, hora, descricao, usuario)
        por_chave: dict[str, Documento] = {}
        for a in buscar(tr, sel.get("evento_documento", [])):
            href = (a.attr("href") or "").strip()
            if not href or href == "#" or href.lower().startswith("javascript"):
                # link que abre o documento por script (onclick/window.open):
                # o endereço assinado está no próprio atributo
                href = _link_no_script(" ".join(
                    (a.attr("onclick"), a.attr("href"), a.attr("data-href"), a.attr("data-url"))))
                if not href:
                    continue
            # O ícone e o texto do mesmo documento são dois links, e o data-doc
            # nem sempre é igual ao parâmetro doc do endereço: vale qualquer
            # das chaves para reconhecer o repetido.
            chaves = [k for k in (a.attr("data-doc"), parametros(href).get("doc"), href) if k]
            chave = chaves[0]
            rotulo = limpar(a.texto() or a.attr("title"))[:80]
            existente = next((por_chave[k] for k in chaves if k in por_chave), None)
            if existente is not None:
                # o primeiro link era o ícone: o rótulo e o tipo vêm do outro
                existente.rotulo = existente.rotulo or rotulo
                existente.mimetype = existente.mimetype or (a.attr("data-mimetype") or "").lower()
                existente.titulo = existente.titulo or limpar(a.attr("title"))
                for k in chaves:
                    por_chave.setdefault(k, existente)
                continue
            doc = Documento(evento=numero, data=data, hora=hora, descricao=descricao,
                            rotulo=rotulo, href=href,
                            mimetype=(a.attr("data-mimetype") or "").strip().lower(),
                            titulo=limpar(a.attr("title")), id=chave,
                            ordem=len(evento.documentos))
            for k in chaves:
                por_chave.setdefault(k, doc)
            evento.documentos.append(doc)
        for doc in evento.documentos:
            doc.rotulo = doc.rotulo or doc.titulo[:80] or f"documento {doc.ordem + 1}"
        eventos.append(evento)
    return eventos


def opcoes_de_paginacao(fonte, sel: dict | None = None) -> tuple[list[str], str]:
    """(valores das páginas de eventos, valor da página atual). Sem paginação: ([], "")."""
    sel = sel or SELETORES_PADRAO
    raiz = fonte if isinstance(fonte, No) else ler_html(fonte)
    alvo = primeiro(raiz, sel.get("eventos_paginacao", []))
    if alvo is None:
        return [], ""
    valores: list[str] = []
    atual = ""
    for op in alvo.elementos():
        if op.tag != "option":
            continue
        valor = op.attrs.get("value")
        valor = op.texto() if valor is None else valor
        if valor not in valores:
            valores.append(valor)
        if "selected" in op.attrs and not atual:
            atual = valor
    return valores, atual or (valores[0] if valores else "")


def _data_ordenavel(data: str, hora: str) -> str:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", data or "")
    if not m:
        return "99999999"
    return m.group(3) + m.group(2) + m.group(1) + re.sub(r"\D", "", hora or "").ljust(6, "0")


def ordenar_eventos(eventos: list[Evento]) -> list[Evento]:
    """Do evento mais antigo ao mais novo.

    O eProc lista do mais novo para o mais antigo, em páginas; o número do
    evento é a ordem verdadeira. Sem número, vale a data - e, empatada, a
    posição (quem aparece depois na lista é mais antigo).
    """
    indexados = list(enumerate(eventos))
    indexados.sort(key=lambda par: (par[1].numero if par[1].numero > 0 else 10 ** 9,
                                    _data_ordenavel(par[1].data, par[1].hora), -par[0]))
    return [e for _, e in indexados]


def ordenar_documentos(eventos: list[Evento]) -> list[Documento]:
    """Os documentos do processo na ordem dos autos, sem repetição.

    Um mesmo documento referido por dois eventos (juntada e certidão que o
    menciona, por exemplo) entra uma vez, no evento mais antigo.
    """
    saida: list[Documento] = []
    vistos: set[str] = set()
    for evento in ordenar_eventos(eventos):
        for doc in evento.documentos:
            chave = doc.id or doc.href
            if chave in vistos:
                continue
            vistos.add(chave)
            saida.append(doc)
    return saida


def juntar_paginas(*paginas: list[Evento]) -> list[Evento]:
    """Une os eventos de várias páginas, sem repetir (a mesma linha pode vir
    em duas páginas se um evento novo entrar no meio da leitura)."""
    unidos: dict[str, Evento] = {}
    for lista in paginas:
        for e in lista:
            unidos.setdefault(e.chave, e)
    return list(unidos.values())


def eventos_ausentes(eventos: list[Evento]) -> str:
    """"1 a 3" quando a lista lida começa depois do evento 1.

    O eProc mostra os eventos do mais novo para o mais antigo e numera-os a
    partir de 1: se o menor número lido é 4, as páginas com os eventos 1 a 3
    (a petição inicial!) não foram lidas - paginação que mudou de jeito, por
    exemplo. Melhor dizer isso no relatório que entregar autos sem o começo
    como se estivessem completos.
    """
    numeros = [e.numero for e in eventos if e.numero > 0]
    if not numeros or min(numeros) <= 1:
        return ""
    menor = min(numeros)
    return "1" if menor == 2 else f"1 a {menor - 1}"


def _titulo(evento, descricao: str, rotulo: str, data: str) -> str:
    descricao = limpar(descricao)
    if len(descricao) > 90:
        descricao = descricao[:88].rstrip() + "…"
    partes = [f"Evento {evento}" if evento else "Evento"]
    if descricao:
        partes.append(descricao)
    partes.append(rotulo or "documento")
    titulo = " — ".join(partes)
    return f"{titulo} ({data})" if data else titulo


def titulo_do_documento(doc: Documento) -> str:
    """Marcador do documento: "Evento 3 — DESPACHO — DESPADEC1 (12/03/2024)"."""
    return _titulo(doc.evento, doc.descricao, doc.rotulo, doc.data)


def plural(n: int, singular: str, plural_: str) -> str:
    """"1 documento", "2 documentos"."""
    return f"{n} {singular if n == 1 else plural_}"


def descrever_faltantes(docs: list[Documento], limite: int = 12) -> str:
    """Para a coluna "incompleto": "ev. 4 PET1, ev. 9 OUT2"."""
    itens = [f"ev. {d.evento} {d.rotulo}".strip() for d in docs]
    if len(itens) > limite:
        return ", ".join(itens[:limite]) + f" e mais {len(itens) - limite}"
    return ", ".join(itens)


# ------------------------------------------------------------ capa e partes
CAMPOS_CAPA = (("numero", "capa_numero", "Número"), ("classe", "capa_classe", "Classe"),
               ("competencia", "capa_competencia", "Competência"),
               ("autuacao", "capa_autuacao", "Autuação"),
               ("situacao", "capa_situacao", "Situação"),
               ("orgao", "capa_orgao", "Órgão julgador"),
               ("magistrado", "capa_magistrado", "Magistrado(a)"),
               ("assunto", "capa_assunto", "Assunto"),
               ("valor", "capa_valor", "Valor da causa"))


def ler_capa(fonte, sel: dict | None = None) -> dict[str, str]:
    sel = sel or SELETORES_PADRAO
    raiz = fonte if isinstance(fonte, No) else ler_html(fonte)
    capa: dict[str, str] = {}
    for chave, seletor, _rotulo in CAMPOS_CAPA:
        no = primeiro(raiz, sel.get(seletor, []))
        if no is not None:
            valor = no.texto() or limpar(no.attr("value"))
            if valor:
                capa[chave] = valor[:300]
    return capa


def ler_partes(fonte, sel: dict | None = None) -> list[str]:
    """"AUTOR: MARIA DA SILVA" - uma linha por polo, com os nomes das partes."""
    sel = sel or SELETORES_PADRAO
    raiz = fonte if isinstance(fonte, No) else ler_html(fonte)
    tabela = primeiro(raiz, sel.get("partes_tabela", []))
    if tabela is None:
        return []
    cabecalhos = [th.texto() for th in tabela.elementos() if th.tag == "th"]
    saida: list[str] = []
    for tr in (e for e in tabela.elementos() if e.tag == "tr"):
        tds = [f for f in tr.filhos if f.tag == "td"]
        for i, td in enumerate(tds):
            nomes = [n.texto() for n in buscar(td, sel.get("parte_nome", []))]
            nomes = list(dict.fromkeys(n for n in nomes if n))
            if not nomes:
                texto = td.texto()
                if not texto:
                    continue
                nomes = [texto[:160]]
            papel = cabecalhos[i] if i < len(cabecalhos) and cabecalhos[i] else "Parte"
            linha = f"{papel}: {'; '.join(nomes)}"
            if linha not in saida:
                saida.append(linha)
    return saida[:60]


# --------------------------------------------------------- textos da tela
_FRASES_NAO_ENCONTRADO = ("processo nao encontrado", "nenhum processo encontrado",
                          "nao foram encontrados", "processo inexistente",
                          "nenhum registro encontrado", "processo nao localizado",
                          "nao foi encontrado nenhum processo", "nao existe processo",
                          "nenhum resultado encontrado")
# variações com "foi/foram" ("Nenhum processo foi encontrado", "Processo não
# foi localizado", "Não foram localizados processos")
_RE_NAO_ENCONTRADO = re.compile(
    r"\bnenhum\w*\s+(?:processo|registro|resultado)s?\s+(?:foi\s+|foram\s+)?(?:encontrad|localizad)"
    r"|\bprocessos?\s+nao\s+(?:foi\s+|foram\s+)?(?:encontrad|localizad)"
    r"|\bnao\s+(?:foi|foram)\s+(?:encontrad|localizad)")
_FRASES_SEM_ACESSO = ("acesso integra do processo", "vista sem procuracao",
                      "nao possui permissao", "sem permissao", "acesso negado",
                      "acesso nao autorizado", "nao tem acesso", "acesso restrito",
                      "usuario sem acesso")


def diz_nao_encontrado(texto: str) -> bool:
    t = sem_acento(texto)
    return any(f in t for f in _FRASES_NAO_ENCONTRADO) or bool(_RE_NAO_ENCONTRADO.search(t))


def diz_sem_acesso(texto: str) -> bool:
    t = sem_acento(texto)
    return any(f in t for f in _FRASES_SEM_ACESSO)


def indica_sigilo(texto: str) -> bool:
    """A página do processo (sem a lista de eventos) se declara sigilosa?

    "Segredo de justiça", "processo sigiloso" ou um nível de sigilo de 1 a 9
    ("Sigilo: Nível 2", "Nível de sigilo do processo: Sigiloso (Nível 2)",
    "Restrito Juiz (Nível 4)"). "Sem Sigilo (Nível 0)" não é sigilo; e a
    lista de eventos fica de fora, porque "Retirado o segredo de justiça" é
    andamento de processo público.

    Na capa, rótulo e valor costumam estar em elementos separados, e o
    innerText os põe em LINHAS diferentes ("Nível de Sigilo do Processo:" /
    "Sigiloso (Nível 2)"): a busca não pode parar na quebra de linha. E
    "Sigiloso" não é "sigilo" seguido de fronteira de palavra - a primeira
    versão perdia exatamente o nível 2, e o PDF ia para o acervo compartilhado.
    """
    t = sem_acento(texto)
    if "segredo de justi" in t:
        return True
    if re.search(r"\bprocesso\s+sigiloso\b", t):
        return True
    for m in re.finditer(r"\bsigil\w*", t):
        # o PRIMEIRO "nível N" depois da palavra: em "Sem Sigilo (Nível 0)" é o 0
        nivel = re.search(r"\bnivel\s*(\d)", t[m.end():m.end() + 80])
        if nivel and nivel.group(1) != "0":
            return True
    # "Nível de sigilo: Sigiloso" / "Restrito Juiz", sem o número. Exige os
    # dois-pontos do rótulo da capa: um botão "Alterar nível de sigilo" (perfil
    # de magistrado) não é declaração de sigilo.
    m = re.search(r"\bnivel\s+de\s+sigilo\b[^:\n]{0,40}:\s*([^\n:]{1,60})(?:\n|$)", t)
    if m:
        valor = m.group(1).strip()
        if valor and not re.match(r"(sem\s+sigilo|publico|nenhum|nao\b|0\b|\(?nivel\s*0)", valor):
            return True
    return False


def motivo_sessao(html: str, url: str = "", sel: dict | None = None) -> str:
    """Por que esta página diz que a sessão acabou ("" quando não diz).

    "encerrada": o aviso do InfraPHP (txaInfraMsg "A sessão foi encerrada");
    "login": a página trouxe os campos de entrada; "sem_assinatura": o eProc
    devolveu para a área externa (externo_controlador.php?...&msg=), o que
    acontece com link de outra sessão - ou com a sessão vencida.
    """
    sel = sel or SELETORES_PADRAO
    bruto = html or ""
    raiz = ler_html(bruto) if bruto else None
    if raiz is not None and "txaInfraMsg" in bruto:
        mensagem = next((n.texto() for n in raiz.elementos()
                         if n.attrs.get("id") == "txaInfraMsg"), "")
        # "sess\S{0,3}o": também a "sessão" de uma página decodificada errado
        # ("sess�o"), que de outro modo passaria por documento
        if re.search(r"sess\S{0,3}o\b.{0,40}?(encerrad|expir|finalizad|invalid|terminad)",
                     sem_acento(mensagem)):
            return "encerrada"
    if raiz is not None:
        def campo(seletores) -> bool:
            # campo oculto (type=hidden) com o mesmo id não é tela de login
            return any(n.tag != "input" or n.attr("type").strip().lower() != "hidden"
                       for n in buscar(raiz, seletores))

        fortes = ["input#txtUsuario", "input#pwdSenha", "form#kc-form-login",
                  "input[name='pwdSenha']"]
        if campo(fortes) or (campo(sel.get("login_senha", []))
                             and campo(sel.get("login_usuario", []))):
            return "login"
    u = (url or "").lower()
    if "externo_controlador.php" in u and "msg=" in u:
        return "sem_assinatura"
    return ""


def url_implementacao(href: str) -> str:
    """O endereço do conteúdo de um documento, a partir do link do evento.

    O link (acao=acessar_documento) abre uma moldura; o conteúdo é
    acao=acessar_documento_implementacao&acao_origem=acessar_documento com os
    MESMOS parâmetros assinados (doc, evento, key, hash). Troca-se só a ação,
    no texto da consulta, sem recodificar o resto - o hash não pode mudar.
    """
    if not href:
        return ""
    partes = urllib.parse.urlsplit(href)
    pedacos = [p for p in partes.query.split("&") if p]
    acoes = [p.partition("=")[2] for p in pedacos if p.partition("=")[0] == "acao"]
    if not acoes:
        return ""
    if acoes[0] == "acessar_documento_implementacao":
        return href
    if acoes[0] != "acessar_documento":
        return ""
    novos = []
    for p in pedacos:
        nome = p.split("=", 1)[0]
        if nome == "acao":
            novos += ["acao=acessar_documento_implementacao", "acao_origem=acessar_documento"]
        elif nome != "acao_origem":
            novos.append(p)
    return urllib.parse.urlunsplit((partes.scheme, partes.netloc, partes.path, "&".join(novos),
                                    partes.fragment))


def src_do_iframe(html: str, url_base: str, sel: dict | None = None,
                  so_iframe: bool = False) -> str:
    """O endereço do conteúdo dentro da moldura do documento.

    Pela ordem: o src do iframe#conteudoIframe; os campos ocultos doc,
    evento, key, nome_documento e hash da própria moldura; o endereço
    escrito no JavaScript da página.

    ``so_iframe``: só o iframe da moldura vale. É o caso de um HTML que já
    veio de acessar_documento_implementacao - é o próprio documento, e um
    despacho ou certidão que CITA o link de outro documento não pode ser
    trocado por ele.
    """
    sel = sel or SELETORES_PADRAO
    raiz = ler_html(html or "")
    no = primeiro(raiz, sel.get("documento_iframe", []))
    if no is not None:
        src = no.attr("src").strip()
        if src and not src.lower().startswith(("about:", "javascript")):
            return urllib.parse.urljoin(url_base, src)
    if so_iframe:
        return ""
    campos: dict[str, str] = {}
    for inp in raiz.elementos():
        nome = inp.attr("name")
        if inp.tag == "input" and nome in ("doc", "evento", "key", "nome_documento", "hash"):
            campos.setdefault(nome, inp.attr("value"))
    if campos.get("doc") and campos.get("hash"):
        consulta = urllib.parse.urlencode([
            ("acao", "acessar_documento_implementacao"), ("acao_origem", "acessar_documento"),
            ("doc", campos.get("doc", "")), ("evento", campos.get("evento", "")),
            ("key", campos.get("key", "")), ("mesmoGrau", "S"),
            ("nome_documento", campos.get("nome_documento", "")), ("termosPesquisados", ""),
            ("hash", campos.get("hash", ""))])
        return urllib.parse.urljoin(url_base, "controlador.php?" + consulta)
    m = re.search(r"controlador\.php\?acao=acessar_documento_implementacao[^\"'<>\s]+", html or "")
    if m:
        return urllib.parse.urljoin(url_base, _html.unescape(m.group(0)))
    return ""


_RE_REDIRECIONA = re.compile(
    r"""location(?:\.href)?\s*=\s*['"]([^'"]+)['"]|location\.(?:replace|assign)\(\s*['"]([^'"]+)['"]""")


def conteudo_embutido(html: str, url_base: str) -> str:
    """Página-casca: quase sem texto, com o documento num iframe, frame,
    embed ou object (ou só um redirecionamento). Devolve o endereço do
    documento de verdade; "" se a página é o próprio documento.

    Sem isto, a casca (uma página em branco) entrava no PDF no lugar do
    documento - e sem aviso nenhum, porque "veio".
    """
    raiz = ler_html(html or "")
    if len(raiz.texto()) > 300:
        return ""
    for no in raiz.elementos():
        alvo = ""
        if no.tag in ("iframe", "frame", "embed"):
            alvo = no.attr("src")
        elif no.tag == "object":
            alvo = no.attr("data")
        elif no.tag == "meta" and no.attr("http-equiv").strip().lower() == "refresh":
            m = re.search(r"url\s*=\s*['\"]?([^'\";]+)", no.attr("content"), re.I)
            alvo = m.group(1) if m else ""
        alvo = alvo.strip()
        if alvo and not alvo.lower().startswith(("about:", "javascript", "data:", "#")):
            return urllib.parse.urljoin(url_base, alvo)
    m = _RE_REDIRECIONA.search(html or "")
    if m:
        return urllib.parse.urljoin(url_base, _html.unescape(m.group(1) or m.group(2)))
    return ""


_RE_AJAX_CONSULTA = re.compile(
    r"controlador_ajax\.php\?acao_ajax=processos_consulta_por_numprocesso(?:&amp;|&)hash=[0-9A-Za-z]+")


def url_ajax_consulta(html: str) -> str:
    m = _RE_AJAX_CONSULTA.search(html or "")
    return _html.unescape(m.group(0)) if m else ""


def link_assinado_da_consulta(texto: str, digitos: str) -> str | None:
    """O linkProcessoAssinado da resposta da consulta por número.

    Devolve o link; "" quando a resposta diz que não há processo; None
    quando a resposta não é a esperada (layout novo, erro).
    """
    try:
        dados = json.loads(texto or "")
    except ValueError:
        return "" if diz_nao_encontrado(texto) else None
    if isinstance(dados, dict):
        if "resultados" not in dados:
            return "" if diz_nao_encontrado(json.dumps(dados, ensure_ascii=False)) else None
        resultados = dados.get("resultados") or []
    elif isinstance(dados, list):
        resultados = dados
    else:
        return None
    candidatos = [r for r in resultados if isinstance(r, dict) and r.get("linkProcessoAssinado")]
    if not resultados:
        return ""
    for r in candidatos:
        if digitos and digitos in re.sub(r"\D", "", json.dumps(r, ensure_ascii=False)):
            return str(r["linkProcessoAssinado"])
    # Um resultado só: foi o que o portal achou para o número pedido (a página
    # aberta ainda é conferida pelos 20 dígitos). Vários, e nenhum com o
    # número: não se escolhe um ao acaso.
    return str(candidatos[0]["linkProcessoAssinado"]) if len(candidatos) == 1 else None


# ------------------------------------------------------ tipos de conteúdo
def charset_de(content_type: str) -> str:
    m = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", content_type or "", re.I)
    return m.group(1).lower() if m else ""


def _codec_html(nome: str) -> str:
    """O codec Python de um charset declarado; Latin-1 e ASCII viram
    Windows-1252 (o que os navegadores fazem). "" se desconhecido."""
    try:
        codec = codecs.lookup((nome or "").strip()).name
    except (LookupError, ValueError):
        return ""
    return "cp1252" if codec in ("iso8859-1", "latin-1", "ascii") else codec


_RE_META_CHARSET = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.I)


def decodificar_html(dados: bytes | str, content_type: str = "") -> str:
    """Bytes de HTML em texto: o charset do cabeçalho manda (o eProc serve
    ISO-8859-1); sem ele, o declarado na página, UTF-8 ou Windows-1252.

    ISO-8859-1 é lido como Windows-1252, como fazem os navegadores: os
    documentos colados do Word trazem aspas curvas e travessões nos códigos
    0x80-0x9F, que o Latin-1 puro transformaria em caracteres de controle.
    Vale também quando o charset só está no <meta> da página (cabeçalho
    "text/html" sem charset): pdf.decodificar leria esse Latin-1 ao pé da
    letra.
    """
    if isinstance(dados, str):
        return dados
    dados = dados or b""
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados[3:].decode("utf-8", errors="replace")
    cs = _codec_html(charset_de(content_type)) if charset_de(content_type) else ""
    if not cs:
        m = _RE_META_CHARSET.search(dados[:4096])
        if m:
            cs = _codec_html(m.group(1).decode("ascii", errors="ignore"))
    if cs:
        try:
            return dados.decode(cs, errors="replace")
        except LookupError:
            pass
    return pdf.decodificar(dados, html=True)


def html_em_utf8(texto: str) -> bytes:
    """HTML já decodificado, pronto para o pdf.Parte: em UTF-8 e declarando
    UTF-8 (senão o charset antigo da página o faria ser lido errado de novo)."""
    corrigido = re.sub(r"charset\s*=\s*[\"']?[\w.:-]+", "charset=utf-8", texto or "", flags=re.I)
    if "charset=utf-8" not in corrigido[:4096].lower():
        corrigido = '<meta charset="utf-8">' + corrigido
    return corrigido.encode("utf-8")


def tipo_do_conteudo(dados: bytes, content_type: str = "", mimetype: str = "") -> str:
    """pdf | html | imagem | midia | texto | zip | vazio | desconhecido.

    A assinatura dos bytes vale mais que o cabeçalho (servidor PHP costuma
    mandar tudo como text/html) e que o data-mimetype do link.
    """
    if not dados:
        return "vazio"
    ct = (content_type or "").split(";")[0].strip().lower()
    mt = (mimetype or "").strip().lower()
    if pdf.e_pdf(dados):
        return "pdf"
    cab = dados[:16]
    if (cab.startswith(b"\xff\xd8\xff") or cab.startswith(b"\x89PNG\r\n\x1a\n")
            or cab[:6] in (b"GIF87a", b"GIF89a") or cab[:4] in (b"II*\x00", b"MM\x00*")
            or (cab[:4] == b"RIFF" and dados[8:12] == b"WEBP")
            or (cab[:2] == b"BM" and (ct == "image/bmp" or mt == "bmp"))):
        return "imagem"
    if (dados[4:8] == b"ftyp" or cab[:3] == b"ID3" or cab[:4] in (b"OggS", b"fLaC", b"\x1aE\xdf\xa3")
            or (cab[:4] == b"RIFF" and dados[8:12] in (b"WAVE", b"AVI "))
            or cab[:4] == b"0&\xb2u"):
        return "midia"
    if cab[:4] == b"PK\x03\x04":
        return "zip"
    if ct.startswith(("audio/", "video/")) or mt in MIMETYPES_MIDIA:
        return "midia"
    if ct.startswith("image/"):
        return "imagem"
    inicio = dados[:400].lstrip().lower()
    if (pdf.e_html(dados) or ct in ("text/html", "application/xhtml+xml")
            or inicio.startswith((b"<!--", b"<?xml", b"<meta", b"<div", b"<p", b"<table",
                                  b"<span", b"<style", b"<title"))):
        return "html"
    if ct.startswith("text/") or mt in ("txt", "text"):
        return "texto"
    return "desconhecido"


_EXTENSOES_MIDIA = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
                    "audio/x-wav": ".wav", "audio/ogg": ".ogg", "video/mp4": ".mp4",
                    "audio/mp4": ".m4a", "video/webm": ".webm", "audio/webm": ".webm",
                    "video/x-msvideo": ".avi", "video/quicktime": ".mov",
                    "video/x-ms-wmv": ".wmv", "audio/x-ms-wma": ".wma", "audio/flac": ".flac"}


def extensao_da_midia(dados: bytes, content_type: str = "", mimetype: str = "") -> str:
    mt = (mimetype or "").strip().lower()
    if mt in MIMETYPES_MIDIA and mt not in ("audio", "video"):
        return "." + mt
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXTENSOES_MIDIA:
        return _EXTENSOES_MIDIA[ct]
    cab = (dados or b"")[:16]
    if (dados or b"")[4:8] == b"ftyp":
        return ".mp4"
    if cab[:3] == b"ID3":
        return ".mp3"
    if cab[:4] == b"OggS":
        return ".ogg"
    if cab[:4] == b"fLaC":
        return ".flac"
    if cab[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    if cab[:4] == b"RIFF":
        return ".wav" if (dados or b"")[8:12] == b"WAVE" else ".avi"
    if cab[:4] == b"0&\xb2u":
        return ".wmv"
    return ".bin"


def _ordem_natural(nome: str) -> list:
    """"parte2" antes de "parte10" (a ordem alfabética pura os inverte)."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p.lower())
            for p in re.split(r"(\d+)", nome or "") if p]


def pdfs_do_zip(dados: bytes) -> list[bytes]:
    """Os PDFs de um ZIP (processo grande sai em partes), na ordem das partes:
    "parte2.pdf" vem antes de "parte10.pdf"."""
    saida = []
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        for nome in sorted(z.namelist(), key=_ordem_natural):
            if nome.lower().endswith(".pdf"):
                conteudo = z.read(nome)
                if pdf.e_pdf(conteudo):
                    saida.append(conteudo)
    return saida


_RE_CNJ_SOLTO = re.compile(r"(?<!\d)\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}(?!\d)")


def links_do_completo(links: list, digitos: str) -> list[str]:
    """Dos links "baixar arquivo" da página do Download Completo, os DESTE processo.

    ``links``: [{"href": ..., "texto": texto da linha em volta}]. A página pode
    listar também arquivos gerados antes para outros processos: link cuja
    linha (ou endereço) traz outro número CNJ, e não este, fica de fora -
    juntá-lo seria gravar autos trocados. Sem número nenhum por perto, o link
    vale (é a página de um arquivo só).
    """
    proprios: list[str] = []
    neutros: list[str] = []
    for item in links or []:
        if isinstance(item, str):
            item = {"href": item, "texto": ""}
        href = str((item or {}).get("href") or "")
        if not href or href in proprios or href in neutros:
            continue
        texto = str(item.get("texto") or "")
        numeros = {re.sub(r"\D", "", n) for n in _RE_CNJ_SOLTO.findall(texto)}
        numeros |= set(re.findall(r"(?:num_processo|numProcesso|txtNumProcesso)=(\d{20})", href))
        if not numeros:
            neutros.append(href)
        elif digitos in numeros:
            proprios.append(href)
        else:
            log.info("    Download Completo: ignorado um arquivo de outro processo (%s).",
                     ", ".join(sorted(numeros))[:80])
    return proprios or neutros


# ------------------------------------------ paginação, manifesto e capa
# O PDF do eProc não tem capa (nem página nenhuma antes ou entre os
# documentos): o eProc não numera folhas, cada documento conserva a
# paginação própria, e qualquer página inserida seria tomada por página dos
# autos. O que a capa da 1.0.1 dizia vai para _controle/<número>_capa.txt,
# _capa.json e o manifesto de paginação (nucleo.paginacao) dentro do PDF.

# Sufixos dos marcadores das páginas de aviso: o marcador diz, já no painel do
# leitor de PDF, que a página não é do documento (não se cita "PET1, p. 1").
SUFIXO_NAO_INCLUIDO = " [NÃO INCLUÍDO]"
SUFIXO_GRAVACAO = " [GRAVAÇÃO — fora do PDF]"
FORMATO_CAPA = "helestron.capa/2"
# Os campos da capa que vão para o manifesto e o capa.json (sem o número,
# que já é o "processo")
CAMPOS_MANIFESTO = ("classe", "competencia", "autuacao", "situacao", "orgao", "magistrado",
                    "assunto", "valor")


def _inteiro(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def origem_esperada(doc: Documento) -> str:
    """O tipo que o documento teria no PDF, pelo data-mimetype do link - o
    do documento que não veio: pdf | imagem | html | texto | midia."""
    mt = (doc.mimetype or "").strip().lower()
    if mt in MIMETYPES_MIDIA:
        return "midia"
    if mt in MIMETYPES_IMAGEM:
        return "imagem"
    if mt in ("html", "htm", "xhtml"):
        return "html"
    if mt in ("txt", "text"):
        return "texto"
    return "pdf"


def citacao(doc: Documento, y: int | None = None, origem: str = "pdf",
            situacao: str = "ok") -> str:
    """Como se cita a página Y do documento (a mesma marca do texto dos autos).

    "evento 1, INIC1, p. 2" (PDF ou imagem: a página Y é a do próprio
    documento, igual à do eProc); "evento 3, DESPADEC1" (HTML ou texto do
    editor do eProc, que não tem páginas); "evento 4, PET1 — NÃO INCLUÍDO" e
    "evento 7, VIDEO1 — gravação fora do PDF" (página de aviso do Helestron,
    que não é página dos autos).
    """
    base = (f"evento {doc.evento}, {doc.rotulo}" if doc.evento
            else (doc.rotulo or "documento"))
    if situacao == "ausente":
        return f"{base} — NÃO INCLUÍDO"
    if situacao == "midia":
        return f"{base} — gravação fora do PDF"
    if origem in ("html", "texto") or not y:
        return base
    return f"{base}, p. {int(y)}"


def rotulo_de_pagina(doc: Documento, origem: str = "pdf",
                     situacao: str = "ok") -> tuple[str, bool]:
    """(prefixo do rótulo de página, numerar?): o que o leitor de PDF mostra
    na caixa da página.

    "Ev. 1 INIC1 p. " numerado (vira "Ev. 1 INIC1 p. 2"); "Ev. 3 DESPADEC1"
    em todas as páginas do documento sem paginação própria (HTML, texto);
    "Ev. 4 PET1 nao incluido" e "Ev. 7 VIDEO1 gravacao" na página de aviso,
    sem número para citar. Em ASCII simples (pdf.rotulo_seguro): o PyMuPDF
    grava errado acento e parênteses no rótulo.
    """
    base = pdf.rotulo_seguro(f"Ev. {doc.evento} {doc.rotulo}" if doc.evento
                             else (doc.rotulo or "Documento")).rstrip()
    if situacao == "ausente":
        return pdf.rotulo_seguro(f"{base[:46].rstrip()} nao incluido"), False
    if situacao == "midia":
        return pdf.rotulo_seguro(f"{base[:50].rstrip()} gravacao"), False
    if origem in ("html", "texto"):
        return base, False
    return base[:56].rstrip() + " p. ", True


def info_do_documento(doc: Documento, origem: str, situacao: str = "ok", **extra) -> dict:
    """A entrada do documento no manifesto; o pdf.juntar completa o início
    (página do PDF em que ele começa) e as páginas. ``extra``: "motivo" do
    documento que não veio, "arquivo" da gravação salva."""
    info = {"evento": doc.evento, "rotulo": doc.rotulo, "descricao": limpar(doc.descricao),
            "data": doc.data, "origem": origem, "situacao": situacao}
    info.update({k: v for k, v in extra.items() if v})
    return info


def capa_do_manifesto(capa: dict, partes: list[str]) -> dict:
    """Classe, órgão julgador, magistrado, assunto... e as partes (lista de
    textos, uma linha por polo). As partes ficam DENTRO da capa: no topo do
    manifesto, "partes" é a lista das partes do ARQUIVO no modo completo
    ([{inicio, paginas}])."""
    saida = {k: capa[k] for k in CAMPOS_MANIFESTO if (capa or {}).get(k)}
    saida["partes"] = [str(p) for p in (partes or []) if str(p).strip()]
    return saida


def eventos_sem_documento(eventos: list[Evento]) -> list[dict]:
    """Os eventos sem documento (audiência realizada, conclusão...), do mais
    antigo ao mais novo: não têm página no PDF, nem marcador."""
    return [{"evento": e.numero, "descricao": limpar(e.descricao), "data": e.data}
            for e in ordenar_eventos(eventos or []) if not e.documentos]


def manifesto_do_processo(numero: Numero, portal: str, tribunal: str, capa: dict,
                          partes: list[str], eventos: list[Evento] | None, sigiloso: bool,
                          modo: str = "documentos", ausentes: str = "",
                          quando: datetime | None = None, grau: str = "1g") -> dict:
    """O manifesto de paginação do PDF (nucleo.paginacao.manifesto_eproc).

    Os documentos, com início e páginas, quem completa é o pdf.juntar (pelo
    ``info`` de cada parte); no modo completo, as partes do arquivo (pdf.gravar
    ou pdf.juntar). ``eventos=None``: a lista de eventos não foi lida inteira,
    e os eventos sem documento ficam de fora - melhor nada que meia lista.
    ``grau``: "2g" nos autos do eProc do 2º grau (o manifesto leva "grau";
    no 1º grau, nada muda).
    """
    quando = quando or datetime.now()
    extras = {"portal": portal, "extraido_em": quando.isoformat(timespec="seconds"),
              "sigiloso": bool(sigiloso), "capa": capa_do_manifesto(capa, partes)}
    if eventos is not None:
        extras["eventos_sem_documento"] = eventos_sem_documento(eventos)
        extras["eventos_nao_listados"] = ausentes or ""
    return paginacao.manifesto_eproc(numero.formatado, [], modo=modo, tribunal=tribunal,
                                     grau=grau, **extras)


def paginas_do_pdf(m: dict | None) -> int:
    """A última página do PDF segundo o manifesto (0 se ele não disser)."""
    itens = [x for x in ((m or {}).get("documentos") or []) + ((m or {}).get("partes") or [])
             if isinstance(x, dict) and _inteiro(x.get("paginas")) > 0]
    return max((_inteiro(x.get("inicio")) + _inteiro(x.get("paginas")) - 1 for x in itens),
               default=0)


def _faixa_do_pdf(inicio: int, paginas: int) -> str:
    if paginas <= 1:
        return f"pág. {inicio} do PDF"
    return f"págs. {inicio}–{inicio + paginas - 1} do PDF"


def _lista_curta(itens: list[str], limite: int = 12) -> str:
    if len(itens) > limite:
        return ", ".join(itens[:limite]) + f" e mais {len(itens) - limite}"
    return ", ".join(itens)


def _ev_rotulo(d: dict) -> str:
    return f"ev. {d.get('evento')} {d.get('rotulo') or ''}".strip()


def resumo_do_arquivo(m: dict | None, eventos: list[Evento] | None) -> list[str]:
    """As linhas de "== Arquivo ==" do capa.txt: como o PDF foi montado, o que
    ele tem e o que falta (o que a 1.0.1 escrevia na capa dentro do PDF).
    ``eventos=None``: a lista de eventos não foi lida inteira."""
    m = m or {}
    total = paginas_do_pdf(m)
    if m.get("modo") == "completo":
        partes = [p for p in m.get("partes") or [] if isinstance(p, dict)]
        if len(partes) > 1:
            faixas = "; ".join(
                f"parte {i} = {_faixa_do_pdf(_inteiro(p.get('inicio')), _inteiro(p.get('paginas')))}"
                for i, p in enumerate(partes, 1))
            linhas = ["Arquivo completo gerado pelo próprio eProc (Download Completo), entregue "
                      f"em {len(partes)} partes, juntadas na ordem sem nenhuma página "
                      f"acrescentada; cada parte recomeça na página 1 ({faixas})."]
        else:
            linhas = ["Arquivo completo gerado pelo próprio eProc (Download Completo), sem "
                      "nenhuma página acrescentada: a página M do PDF é a página M desse arquivo."]
        if total:
            linhas.append(f"Páginas do PDF: {total}.")
        if eventos is None:
            linhas.append("Lista de eventos incompleta: só a primeira página de eventos do portal "
                          "pôde ser lida (o arquivo do eProc traz os documentos de todos eles).")
        else:
            linhas.append(f"Eventos: {len(eventos)}; documentos: "
                          f"{len(ordenar_documentos(eventos))}.")
        return linhas
    docs = [d for d in m.get("documentos") or [] if isinstance(d, dict)]
    linhas = ["PDF montado pelo Helestron documento a documento, do evento mais antigo ao mais "
              "novo, sem capa e sem página nenhuma antes ou entre os documentos (só uma página "
              "de aviso no lugar do documento que não veio e da gravação).",
              f"Eventos: {len(eventos or [])}; documentos: {len(docs)}; páginas do PDF: {total}.",
              f"Paginação: {paginacao.resumo(m)}."]
    ausentes = str(m.get("eventos_nao_listados") or "")
    if ausentes:
        linhas.append(f"ATENÇÃO: {'o evento' if ausentes == '1' else 'os eventos'} {ausentes} não "
                      f"{'apareceu' if ausentes == '1' else 'apareceram'} na lista lida do "
                      "portal; os documentos deles NÃO estão neste arquivo. Confira no eProc.")
    fora = [_ev_rotulo(d) for d in docs if d.get("situacao") == "ausente"]
    if fora:
        linhas.append(f"Documentos não incluídos ({len(fora)}): {_lista_curta(fora)} — cada um "
                      "tem uma página de aviso no lugar.")
    gravacoes = [_ev_rotulo(d) for d in docs if d.get("situacao") == "midia"]
    if gravacoes:
        linhas.append(f"Gravações (áudio ou vídeo) fora do PDF ({len(gravacoes)}): "
                      f"{_lista_curta(gravacoes)} — página de aviso no lugar; as baixadas ficam "
                      "em _controle\\midias.")
    sem_doc = [e for e in m.get("eventos_sem_documento") or [] if isinstance(e, dict)]
    if sem_doc:
        linhas.append(f"Eventos sem documento ({len(sem_doc)}): não têm página no PDF (estão na "
                      "lista de eventos, abaixo).")
    return linhas


def como_citar(m: dict | None) -> list[str]:
    """As linhas de "== Como citar ==" do capa.txt."""
    m = m or {}
    if m.get("modo") == "completo":
        partes = [p for p in m.get("partes") or [] if isinstance(p, dict)]
        posicao = ("\"Download Completo do eProc, parte P, pág. M\"" if len(partes) > 1
                   else "\"Download Completo do eProc, pág. M\"")
        return ["Cite o evento e o documento que a própria página ou o marcador do arquivo do "
                f"eProc indicarem; sem eles, {posicao}. O eProc não numera folhas: não cite "
                "\"fl.\"."]
    return ["O eProc não numera folhas: cada documento conserva a paginação própria, igual à "
            "do eProc. Cite \"evento N, RÓTULO, p. Y\", com Y a página dentro do documento (o "
            "leitor de PDF mostra \"Ev. N RÓTULO p. Y\" na caixa da página, e o texto dos autos "
            "marca cada página assim).",
            "Documento escrito no editor do próprio eProc (despacho, decisão, sentença, "
            "certidão em HTML) não tem páginas: cite \"evento N, RÓTULO\".",
            "A posição no arquivo (\"pág. M do PDF\") serve só para navegar: nunca a cite. As "
            "páginas de aviso (documento NÃO INCLUÍDO, gravação fora do PDF) não são páginas dos "
            "autos."]


def mapa_de_documentos(m: dict | None, eventos: list[Evento] | None) -> list[str]:
    """"== Mapa de documentos ==": TODOS os documentos, um por linha, com
    a posição no PDF e a paginação no eProc (no modo completo, sem posição:
    o arquivo do eProc não a informa)."""
    m = m or {}
    docs = [d for d in m.get("documentos") or [] if isinstance(d, dict)]
    if m.get("modo") == "completo" or not docs:
        lista = ordenar_documentos(eventos or [])
        linhas = [f"== Mapa de documentos ({len(lista)}) =="]
        if m.get("modo") == "completo" and lista:
            linhas.append("(o arquivo do eProc não informa a página em que começa cada documento: "
                          "use os marcadores do próprio arquivo, quando houver)")
        return linhas + [titulo_do_documento(d) for d in lista]
    linhas = [f"== Mapa de documentos ({len(docs)}) =="]
    for d in docs:
        inicio, qtd = _inteiro(d.get("inicio")), _inteiro(d.get("paginas"))
        faixa = _faixa_do_pdf(inicio, qtd) if inicio else "fora do PDF"
        situacao = str(d.get("situacao") or "ok")
        if situacao == "ausente":
            motivo = limpar(str(d.get("motivo") or ""))[:200]
            onde = f"{faixa} — NÃO INCLUÍDO (página de aviso)" + (f": {motivo}" if motivo else "")
        elif situacao == "midia":
            arquivo = str(d.get("arquivo") or "")
            onde = (f"{faixa} — gravação fora do PDF (página de aviso)"
                    + (f"; salva em {arquivo}" if arquivo else "; não baixada"))
        elif str(d.get("origem") or "pdf") in ("html", "texto"):
            onde = f"{faixa} (texto do próprio eProc, sem paginação: cite sem página)"
        elif qtd == 1:
            onde = f"{faixa} (1 pág.; p. 1 no eProc)"
        else:
            onde = f"{faixa} ({qtd} págs.; p. 1–{qtd} no eProc)"
        titulo = _titulo(d.get("evento"), d.get("descricao") or "", d.get("rotulo") or "",
                         d.get("data") or "")
        linhas.append(f"{titulo} — {onde}")
    return linhas


def texto_capa_txt(numero: Numero, portal: str, capa: dict, partes: list[str],
                   eventos: list[Evento], sigiloso: bool, manifesto: dict | None = None,
                   quando: datetime | None = None, eventos_completos: bool = True) -> str:
    """_controle/<número>_capa.txt, para quem lê e para a IA: a capa do
    processo, o arquivo (como foi montado, o que falta), como citar, o mapa de
    TODOS os documentos e TODOS os eventos.

    "SEGREDO DE JUSTIÇA" vai no topo: o motor o procura nos primeiros 2000
    caracteres para manter o processo fora do acervo nas próximas rodadas.
    """
    quando = quando or datetime.now()
    linhas = [f"Processo {numero.formatado} - {portal}",
              f"Capa extraída em {quando:%d/%m/%Y %H:%M}", ""]
    if sigiloso:
        linhas += ["SEGREDO DE JUSTIÇA - processo sigiloso. Não compartilhe.", ""]
    dados = [f"{rotulo}: {capa[chave]}" for chave, _s, rotulo in CAMPOS_CAPA[1:]
             if (capa or {}).get(chave)]
    if dados:
        linhas += ["== Capa =="] + dados + [""]
    if partes:
        linhas += ["== Partes =="] + list(partes) + [""]
    linhas += (["== Arquivo =="] + resumo_do_arquivo(manifesto, eventos if eventos_completos
                                                       else None) + [""])
    linhas += ["== Como citar =="] + como_citar(manifesto) + [""]
    mapa = mapa_de_documentos(manifesto, eventos)
    if not eventos_completos:
        mapa.insert(1, "(lista incompleta: só os documentos da primeira página de eventos do "
                       "portal)")
    linhas += mapa + [""]
    recentes = list(reversed(ordenar_eventos(eventos or [])))
    linhas.append(f"== Eventos ({len(recentes)}) ==")
    if recentes and not eventos_completos:
        linhas.append("(lista incompleta: só a primeira página de eventos do portal)")
    for e in recentes:
        rotulos = ", ".join(d.rotulo for d in e.documentos)
        linhas.append(f"{e.data}  Evento {e.numero} - {e.descricao}"
                      + (f" [{rotulos}]" if rotulos else ""))
    if not recentes:
        linhas.append("(nenhum evento localizado na página - confira no portal)")
    return "\n".join(linhas) + "\n"


def dados_da_capa(numero: Numero, portal: str, tribunal: str, capa: dict, partes: list[str],
                  eventos: list[Evento], sigiloso: bool, manifesto: dict | None = None,
                  quando: datetime | None = None, eventos_completos: bool = True,
                  grau: str = "1g") -> dict:
    """_controle/<nome do PDF>_capa.json: o mesmo do capa.txt, legível por
    máquina (a skill do Claude o lê pelo "capa_json" do --json do baixar).
    No 2º grau leva "grau": "2g" (no 1º grau, o campo não vai: ausente = 1º).

    "paginacao" é um objeto, como no e-SAJ ({resumo, ultima, ...}), e só
    existe com o manifesto de paginação: era o texto do resumo (ou ""), e
    quem lia capa["paginacao"]["resumo"] pelo contrato do e-SAJ quebrava no
    primeiro processo do eProc."""
    quando = quando or datetime.now()
    m = manifesto or {}
    ordenados = ordenar_eventos(eventos or [])
    docs = [dict(d) for d in m.get("documentos") or [] if isinstance(d, dict)]
    if not docs:
        docs = [info_do_documento(d, origem_esperada(d), "") for d in ordenar_documentos(ordenados)]
        for d in docs:
            d.pop("situacao", None)
    pag = {}
    if paginacao.valido(m):
        pag = {"paginacao": {
            "resumo": paginacao.resumo(m),
            "ultima": paginas_do_pdf(m),
            # como a coluna "incompleto": os documentos com página de aviso no lugar
            "documentos_ausentes": ", ".join(_ev_rotulo(d) for d in docs
                                             if d.get("situacao") == "ausente")}}
    saida = {
        "formato": FORMATO_CAPA,
        "sistema": "eproc",
        "tribunal": tribunal,
        "portal": portal,
        "processo": numero.formatado,
        "extraido_em": quando.isoformat(timespec="seconds"),
        "sigiloso": bool(sigiloso),
        "capa": {k: capa[k] for k in CAMPOS_MANIFESTO if (capa or {}).get(k)},
        "partes": [str(p) for p in (partes or []) if str(p).strip()],
        "modo": str(m.get("modo") or "documentos"),
        **pag,
        "paginas_pdf": paginas_do_pdf(m),
        "como_citar": " ".join(como_citar(m)),
        "eventos_completos": bool(eventos_completos),
        "eventos_nao_listados": (str(m.get("eventos_nao_listados") or "")
                                 if eventos_completos else ""),
        "eventos_sem_documento": eventos_sem_documento(ordenados) if eventos_completos else [],
        "eventos": [{"evento": e.numero, "data": e.data, "hora": e.hora,
                     "descricao": limpar(e.descricao),
                     "documentos": [d.rotulo for d in e.documentos]} for e in ordenados],
        "documentos": docs,
    }
    if m.get("modo") == "completo":
        saida["partes_do_arquivo"] = [p for p in m.get("partes") or [] if isinstance(p, dict)]
    if normalizar_grau(grau) == paginacao.SEGUNDO_GRAU:
        # logo depois do sistema, para quem lê o arquivo
        saida = {"formato": saida["formato"], "sistema": saida["sistema"],
                 "grau": paginacao.SEGUNDO_GRAU, **saida}
    return saida


# ------------------------------------------------------------ configuração
def _config_eproc(chave: str) -> str:
    """[eproc] <chave> do config.ini, sem criar o arquivo (o Config criaria)."""
    arquivo = caminhos.ARQUIVO_CONFIG
    try:
        if not arquivo.is_file():
            return ""
        cp = configparser.ConfigParser(interpolation=None, comment_prefixes=(";", "#"),
                                       inline_comment_prefixes=None, strict=False)
        cp.read(arquivo, encoding="utf-8-sig")
        return cp.get("eproc", chave, fallback="").strip()
    except (configparser.Error, OSError, UnicodeDecodeError):
        return ""


def resolver_modo(explicito: str | None = None, opcoes=None) -> str:
    """documentos (padrão) ou completo: o explícito, o das opções, o do config.ini."""
    for valor in (explicito, getattr(opcoes, "modo_eproc", None),
                  getattr(opcoes, "eproc_modo", None), _config_eproc("modo")):
        v = (valor or "").strip().lower()
        if v in ("documento", "documentos", "pecas", "peças"):
            return "documentos"
        if v in ("completo", "download completo", "download_completo"):
            return "completo"
        if v:
            log.warning("modo do eProc desconhecido (%r); uso 'documentos'.", valor)
            return "documentos"
    return "documentos"


def mascarar(usuario: str) -> str:
    u = (usuario or "").strip()
    return (u[:3] + "***") if u else "(sem usuário)"


def normalizar_base(url: str) -> str:
    """"https://x/eproc" ou ".../eproc/index.php" -> "https://x/eproc/"."""
    u = (url or "").strip()
    if not u:
        return ""
    partes = urllib.parse.urlsplit(u)
    caminho = partes.path or "/"
    if not caminho.endswith("/"):
        cabeca, _, ultimo = caminho.rpartition("/")
        caminho = (cabeca + "/") if "." in ultimo else (caminho + "/")
    return urllib.parse.urlunsplit((partes.scheme, partes.netloc, caminho, "", ""))


# ações de entrada: o endereço em que o login termina não serve de âncora
_RE_ACAO_DE_ENTRADA = re.compile(r"logar|login|entrar|sso|retorno|autentica|perfil", re.I)


def _erro_transitorio(msg: str) -> bool:
    return bool(re.search(r"Execution context was destroyed|Target closed|Target page"
                          r"|Session closed|has been closed|net::ERR_ABORTED"
                          r"|Navigation failed because|frame was detached", msg or "", re.I))


# ======================================================== JS da página
_JS_BUSCAR = r"""async (a) => {
    const relogio = new AbortController();
    const prazo = setTimeout(() => relogio.abort(), a.prazo);
    try {
        const op = {method: a.metodo || 'GET', credentials: 'include', cache: 'no-store',
                    headers: a.cabecalhos || {}, signal: relogio.signal};
        if (a.corpo !== null && a.corpo !== undefined) op.body = a.corpo;
        const r = await fetch(a.url, op);
        const b = new Uint8Array(await r.arrayBuffer());
        let s = '';
        for (let i = 0; i < b.length; i += 8192)
            s += String.fromCharCode.apply(null, b.subarray(i, i + 8192));
        return {status: r.status, url: r.url, tipo: r.headers.get('content-type') || '',
                dados: btoa(s)};
    } catch (e) {
        return {erro: String((e && e.message) || e)};
    } finally {
        clearTimeout(prazo);
    }
}"""

_JS_TEXTO_SEM = r"""(seletores) => {
    let t = (document.body && document.body.innerText) || '';
    for (const s of seletores) {
        let nos = [];
        try { nos = document.querySelectorAll(s); } catch (e) { continue; }
        nos.forEach(el => { const x = el.innerText || ''; if (x) t = t.split(x).join(' '); });
    }
    return t.slice(0, 300000);
}"""

_JS_PAGINAR = r"""(a) => {
    const el = a.s ? document.querySelector(a.s) : null;
    if (!a.funcao && el && el.options) {
        const i = Array.from(el.options).findIndex(o => o.value === a.v);
        if (i >= 0) {
            el.selectedIndex = i;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            return 'seletor';
        }
    }
    if (typeof alterarPagina === 'function') { alterarPagina(a.v); return 'funcao'; }
    return '';
}"""

_JS_LINKS_COMPLETO = r"""() => {
    const vistos = [], saida = [];
    document.querySelectorAll('a[href]').forEach(a => {
        const h = a.href || '';
        const pronto = /download_completo_download_pronto_enviar|\/download72h\//;
        if (!pronto.test(h) || vistos.includes(h)) return;
        vistos.push(h);
        let linha = a.closest('tr, li, p');
        if (!linha)
            linha = (a.parentElement && a.parentElement !== document.body) ? a.parentElement : a;
        saida.push({href: h, texto: String(linha.innerText || '').slice(0, 2000)});
    });
    return saida;
}"""

_JS_DESMARCAR = r"""(a) => {
    const caixas = Array.from(document.querySelectorAll(a.seletor));
    let principal = 0;
    for (const cb of caixas) {
        const partes = (cb.value || '').split('|');
        const d = (partes[1] || '').replace(/\D/g, '');
        if (d === a.digitos) principal++;
    }
    if (!principal) return {caixas: caixas.length, principal: 0, desmarcadas: 0};
    let desmarcadas = 0;
    for (const cb of caixas) {
        const d = ((cb.value || '').split('|')[1] || '').replace(/\D/g, '');
        const marcar = d === a.digitos;
        if (cb.checked !== marcar) {
            cb.checked = marcar;
            if (!marcar) desmarcadas++;
            cb.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }
    return {caixas: caixas.length, principal, desmarcadas};
}"""


@dataclass
class Resposta:
    status: int
    url: str
    tipo: str
    dados: bytes
    canal: str = ""


class _FalhaDocumento(RuntimeError):
    """Um documento que não veio por nenhum caminho (vira página de aviso)."""


# ============================================================== o portal
class PortalEProc:
    """Login e download no eProc de um tribunal, no grau do Tribunal recebido
    (o do catálogo é o 1º; o 2º vem de tribunal.no_grau("2g"))."""

    sistema = "eproc"

    def __init__(self, nav, tribunal, opcoes, ctx: Contexto | None,
                 credenciais: tuple[str, str] | None, *, modo: str | None = None,
                 grau: str | None = None, seletores: dict | None = None):
        # O grau tem uma fonte só: o Tribunal. É dele que o motor tira a
        # credencial (cofre[tribunal.portal]) e o perfil do navegador; um
        # grau= que vencesse o do Tribunal mandaria a senha do eProc do 1º
        # grau ao do 2º (outra instalação, que bloqueia o usuário depois de
        # poucas tentativas erradas). Divergente, é erro de programação.
        proprio = normalizar_grau(getattr(tribunal, "grau", "1g")) or "1g"
        if grau not in (None, "") and normalizar_grau(grau) != proprio:
            pedido = normalizar_grau(grau) or str(grau)
            raise ValueError(f"o grau pedido ({pedido}) não é o do tribunal ({proprio}): passe "
                             f"tribunal.no_grau('{pedido}')")
        self.nav = nav
        self.tribunal = tribunal
        self.opcoes = opcoes
        self.ctx = ctx or Contexto()
        self.usuario, self.senha = (credenciais or ("", ""))
        self.modo_login = opcoes.modo_login("eproc")
        self.grau = proprio
        self.sel = seletores or carregar_seletores()
        self.modo_pdf = resolver_modo(modo, opcoes)
        try:
            minutos = float(_config_eproc("espera_completo_minutos") or ESPERA_COMPLETO_MIN)
        except ValueError:
            minutos = ESPERA_COMPLETO_MIN
        self.espera_completo_min = max(1.0, minutos)
        self.perfil_preferido = (getattr(opcoes, "perfil_eproc", "") or _config_eproc("perfil"))
        urls = dict(getattr(tribunal, "urls", {}) or {})
        self._por_secao = any(str(k).startswith(f"{self.grau}_") for k in urls)
        if not tribunal.urls_para(None, self.grau):
            # no 2º grau, urls_para é estrito: nunca cai no endereço do 1º
            raise PortalIndisponivel(
                f"o catálogo de tribunais não traz o endereço do {self.nome}. "
                f"Informe-o {ONDE_CORRIGIR_ENDERECO}.")
        self.base: str = ""
        self._candidatos_atuais: list[str] = []
        self._logado = False
        self._url_ancora = ""
        self._url_processo = ""
        self._minimizada = False
        self._canais = ["contexto", "pagina"]
        self._avisos_portal: list[str] = []
        self._abas_ouvidas: set[int] = set()
        self._notas: list[str] = []
        # processos cujo sigilo esta sessão já apurou (Numero.nome_arquivo)
        self.sigilosos_apurados: set[str] = set()
        # o processo que baixar() está buscando agora, e o resultado dele
        self._em_curso: tuple[Numero, ResultadoProcesso] | None = None
        # o manifesto de paginação do último PDF gravado (para a capa)
        self._manifesto: dict | None = None
        # _todos_os_eventos saiu da primeira página de eventos?
        self._paginou = False
        # um evento de espera (login_aguardando, acao_na_janela) foi publicado
        # e ainda não teve o login_concluido
        self._aguardando_usuario = False

    # ----------------------------------------------------------- atalhos
    @property
    def nome(self) -> str:
        sufixo = " (2º grau)" if self.grau == "2g" else ""
        return f"eProc do {self.tribunal.sigla}{sufixo}"

    @property
    def pg(self):
        return self.nav.pagina

    @property
    def espera_ms(self) -> int:
        return max(5, int(self.opcoes.espera_s)) * 1000

    def _checar_cancelado(self) -> None:
        if self.ctx.cancelado():
            raise Cancelado()

    def _esperar_ms(self, ms: int) -> None:
        try:
            self.pg.wait_for_timeout(max(1, int(ms)))
        except Exception:
            time.sleep(max(1, int(ms)) / 1000)

    def _dormir(self, segundos: float) -> None:
        """Pausa que atende o "Parar" em menos de meio segundo."""
        limite = time.monotonic() + max(0.0, segundos)
        while True:
            self._checar_cancelado()
            falta = limite - time.monotonic()
            if falta <= 0:
                return
            self._esperar_ms(int(min(0.25, falta) * 1000))

    def _texto(self, pagina=None) -> str:
        try:
            return (pagina or self.pg).inner_text("body", timeout=5000) or ""
        except Exception:
            return ""

    def _html(self, pagina=None) -> str:
        try:
            return (pagina or self.pg).content() or ""
        except Exception:
            return ""

    def _url(self, pagina=None) -> str:
        try:
            return (pagina or self.pg).url or ""
        except Exception:
            return ""

    def _esperar_carga(self, pagina=None, ms: int = 10000) -> None:
        pagina = pagina or self.pg
        try:
            pagina.wait_for_load_state("domcontentloaded", timeout=min(ms, self.espera_ms))
        except Exception:
            pass

    def _visivel(self, chave: str, pagina=None, espera_ms: int = 0):
        return primeiro_visivel(pagina or self.pg, self.sel.get(chave, []), espera_ms=espera_ms)

    def _marcar(self, pagina=None) -> str:
        """Põe uma marca na página: quando ela some, a página foi trocada."""
        marca = uuid.uuid4().hex
        try:
            (pagina or self.pg).evaluate("m => { window.__marcaHelestron = m; }", marca)
        except Exception:
            pass
        return marca

    def _trocou(self, marca: str, pagina=None) -> bool:
        try:
            atual, estado = (pagina or self.pg).evaluate(
                "() => [window.__marcaHelestron || '', document.readyState]")
        except Exception:
            return False            # navegando: o contexto da página está sendo trocado
        return atual != marca and estado in ("interactive", "complete")

    def _esperar(self, condicao, ms: int, pagina=None) -> bool:
        limite = time.monotonic() + ms / 1000
        while True:
            self._checar_cancelado()
            try:
                if condicao():
                    return True
            except (Cancelado, SessaoPerdida, LoginFalhou):
                raise
            except Exception:
                pass
            if time.monotonic() >= limite:
                return False
            try:
                (pagina or self.pg).wait_for_timeout(150)
            except Exception:
                time.sleep(0.15)

    def _ir(self, url: str, pagina=None) -> None:
        """goto que tolera a navegação anterior ainda em curso.

        Depois de um endereço que não responde, o Chromium ainda está abrindo
        a própria página de erro, e o goto seguinte é "interrompido por outra
        navegação": espera-se ela assentar e tenta-se de novo (até duas vezes:
        num computador ocupado, a página de erro demora a assentar).
        """
        self._checar_cancelado()
        pagina = pagina or self.pg
        for tentativa in (1, 2, 3):
            try:
                pagina.goto(url, wait_until="domcontentloaded", timeout=self.espera_ms)
                return
            except Exception as erro:
                if tentativa == 3 or not re.search(
                        r"interrupted by another navigation|net::ERR_ABORTED", str(erro)):
                    raise
                try:
                    pagina.wait_for_load_state("load", timeout=5000)
                except Exception:
                    pass

    def _ouvir_avisos(self, pagina) -> None:
        """Guarda as caixas de aviso do portal (alert), que o Navegador
        dispensa: "Processo não encontrado" às vezes só aparece nelas."""
        if pagina is None or id(pagina) in self._abas_ouvidas:
            return
        self._abas_ouvidas.add(id(pagina))
        try:
            pagina.on("dialog", lambda d: self._avisos_portal.append(
                str(getattr(d, "message", "") or "")))
        except Exception:
            pass

    # ============================================================ janela
    def _janela_visivel(self) -> bool:
        return bool(getattr(self.nav, "visivel", False))

    def _janela(self, estado: str) -> bool:
        """Minimiza ("minimized") ou restaura ("normal") a janela pelo CDP.

        Falha aqui nunca é erro: navegador invisível, Edge antigo ou CDP
        recusado só deixam a janela como está.
        """
        if not self._janela_visivel():
            return False
        sessao = None
        try:
            sessao = self.nav.contexto.new_cdp_session(self.pg)
            alvo = sessao.send("Browser.getWindowForTarget")
            sessao.send("Browser.setWindowBounds",
                        {"windowId": alvo["windowId"], "bounds": {"windowState": estado}})
            return True
        except Exception as erro:
            log.debug("  janela do navegador (%s): %s", estado, str(erro)[:160])
            return False
        finally:
            if sessao is not None:
                try:
                    sessao.detach()
                except Exception:
                    pass

    def _minimizar(self) -> None:
        if self.opcoes.mostrar_navegador or not self._janela_visivel():
            return
        if self._janela("minimized"):
            self._minimizada = True
            log.debug("  janela do navegador minimizada depois do login.")

    def _restaurar_janela(self) -> None:
        if self._minimizada and self._janela("normal"):
            self._minimizada = False
            try:
                self.pg.bring_to_front()
            except Exception:
                pass

    # ============================================================ login
    def _evento(self, tipo: str, **dados) -> None:
        """Evento legível por máquina para quem acompanha (a skill do Claude,
        pela linha de comando): "login_aguardando", "acao_na_janela",
        "login_concluido". Contexto sem ``evento`` (versão anterior) não
        recebe nada; e o evento é aviso: nunca derruba o login. No 2º grau,
        leva "grau": "2g" (no 1º grau, o corpo de sempre)."""
        ev = getattr(self.ctx, "evento", None)
        if not callable(ev):
            return
        if self.grau == paginacao.SEGUNDO_GRAU:
            dados = {**dados, "grau": paginacao.SEGUNDO_GRAU}
        try:
            ev(tipo, sistema=self.sistema, tribunal=self.tribunal.sigla, **dados)
        except Exception as erro:
            log.debug("evento %s não publicado: %s", tipo, erro)

    def _evento_de_espera(self, tipo: str, motivo: str, limite: float) -> None:
        """login_aguardando ou acao_na_janela, ANTES de esperar o usuário: o
        modo de login, o prazo que resta (até ``limite``, em time.monotonic) e
        o porquê ("manual", "certificado", "captcha", "perfil")."""
        resta = max(0.0, limite - time.monotonic())
        self._evento(tipo, modo=self.modo_login, prazo_min=max(1, -int(-resta // 60)),
                     ate=(datetime.now() + timedelta(seconds=resta)).isoformat(timespec="seconds"),
                     motivo=motivo)
        self._aguardando_usuario = True

    def _login_concluido(self) -> None:
        """login_concluido - só depois de um evento de espera, como no e-SAJ."""
        if self._aguardando_usuario:
            self._aguardando_usuario = False
            self._evento("login_concluido")

    def _etapa(self, pagina=None, apos_envio: bool = False) -> str:
        """Em que ponto do login a página está.

        login | otp | captcha | perfil | recusado | bloqueado |
        senha_expirada | logado | desconhecido.

        A recusa pelo TEXTO só conta depois de enviada a senha: a tela de
        login pode trazer, de saída, avisos como "após 5 tentativas com
        senha incorreta o usuário será bloqueado".
        """
        pagina = pagina or self.pg
        url = self._url(pagina)
        if self._visivel("otp_campo", pagina) is not None:
            return "otp"
        if self._visivel("captcha", pagina) is not None:
            return "captcha"
        if "acao_retorno=login_invalido" in url:
            return "recusado"
        interna = bool(re.search(r"(?<!externo_)controlador\.php", url, re.I))
        # Área logada com a barra de pesquisa: é logado - ANTES de olhar o
        # texto. O painel de um magistrado lista andamentos de centenas de
        # processos ("conta bloqueada" do SISBAJUD, "procuração inválida") e
        # o menu tem "Alterar senha": lido como tela de login, isso dava
        # "usuário bloqueado" ou "senha recusada" com o login já feito. Pelo
        # mesmo motivo, o texto só é lido fora da área logada - ou quando a
        # página mostra os campos de login (erro devolvido num endereço interno:
        # sem reconhecer a recusa, a senha errada seria reenviada, e o eProc
        # bloqueia o usuário depois de poucas tentativas).
        if interna and self._visivel("pesquisa_rapida", pagina) is not None:
            return "logado"
        campos_login = (self._visivel("login_usuario", pagina) is not None
                        or self._visivel("login_senha", pagina) is not None)
        if apos_envio and (not interna or campos_login):
            texto = self._texto(pagina)
            limpo = sem_acento(texto)
            if re.search(r"usuario (esta )?bloqueado|conta (esta )?bloqueada|account is "
                         r"(temporarily )?disabled|conta (esta )?desativada|usuario (esta )?inativo",
                         limpo):
                return "bloqueado"
            if recusou_credenciais(texto) or any(
                    f in limpo for f in ("invalid username or password", "usuario ou senha invalid",
                                         "credenciais invalidas", "login invalido")):
                return "recusado"
        if self._visivel("senha_nova", pagina) is not None:
            return "senha_expirada"
        if campos_login:
            return "login"
        # Sem a barra de pesquisa, botões de perfil (data-descricao) mandam.
        if self._visivel("perfil", pagina) is not None:
            return "perfil"
        if interna:
            return "logado"
        return "desconhecido"

    def _esperar_etapa_conhecida(self, segundos: float) -> str:
        limite = time.monotonic() + segundos
        while True:
            self._checar_cancelado()
            etapa = self._etapa()
            if etapa != "desconhecido" or time.monotonic() >= limite:
                return etapa
            self._esperar_ms(400)

    def _etapa_em_alguma_aba(self) -> str:
        """No modo manual o usuário pode entrar noutra aba: adota-se a logada."""
        etapa = self._etapa()
        if etapa == "logado":
            return etapa
        try:
            abas = self.nav.abas()
        except Exception:
            abas = []
        for aba in abas:
            if aba is self.pg:
                continue
            try:
                if self._etapa(aba) == "logado":
                    self.nav.pagina = aba
                    return "logado"
            except Exception:
                continue
        return etapa

    def entrar(self, numero: Numero | None = None) -> None:
        """Garante uma sessão autenticada. Reaproveita a anterior se valer.

        ``numero`` só importa nos tribunais com um eProc por seção
        judiciária (TRF4, TRF2): o login é feito no endereço da seção dele.
        Sem número, nesses tribunais, o login espera o primeiro processo.
        """
        self._checar_cancelado()
        if numero is not None:
            candidatos = self.tribunal.urls_para(numero, self.grau)
        elif self._candidatos_atuais:
            candidatos = self._candidatos_atuais
        elif self._por_secao:
            log.info("O %s tem um endereço por seção judiciária; o login é feito no primeiro "
                     "processo da lista.", self.nome)
            return
        else:
            candidatos = self.tribunal.urls_para(None, self.grau)
        try:
            self._entrar_em(candidatos)
        except (Cancelado, LoginFalhou, PortalIndisponivel, SessaoPerdida):
            raise
        except Exception as erro:
            # erro do navegador no meio do login (aba fechada, página que
            # trocou): o grupo para com uma explicação, não com um rastro
            if self.ctx.cancelado():
                raise Cancelado() from erro
            self.nav.diagnosticar("eproc-login-erro")
            raise PortalIndisponivel(
                f"o login no {self.nome} não pôde ser concluído "
                f"({explicar_erro(str(erro))}). Tente de novo; se persistir, ligue "
                f"“{MOSTRAR_NAVEGADOR}” para acompanhar.") from erro

    def _entrar_em(self, candidatos: list[str]) -> None:
        candidatos = [normalizar_base(c) for c in candidatos if c]
        if self._logado and self.base in candidatos and self._sessao_ativa():
            return
        self._logado = False
        base, etapa = self._abrir_entrada(candidatos)
        self.base = base
        self._candidatos_atuais = candidatos
        if etapa == "logado":
            log.info("Sessão do %s ainda válida - login dispensado.", self.nome)
        elif self.modo_login in ("manual", "certificado"):
            self._login_na_janela()
        else:
            self._login_com_senha(etapa)
        self._pos_login()

    def _abrir_entrada(self, candidatos: list[str]) -> tuple[str, str]:
        """Abre o primeiro endereço que mostrar a tela de entrada do eProc
        (ou já a área logada). Devolve (endereço, etapa)."""
        falhas: list[str] = []
        abriu_algo = False
        for url in candidatos:
            self._checar_cancelado()
            self.ctx.status(f"Abrindo o {self.nome}...")
            try:
                self._ir(url)
            except Cancelado:
                raise
            except Exception as erro:
                motivo = explicar_erro(str(erro))
                falhas.append(f"{url} ({motivo})")
                log.info("  %s não respondeu (%s).", url, motivo)
                continue
            self._ouvir_avisos(self.pg)
            etapa = self._esperar_etapa_conhecida(min(20.0, float(self.opcoes.espera_s)))
            if etapa != "desconhecido":
                # o log diz qual endereço valeu (o do TJAL ainda não é confirmado)
                log.info("%s: usando o endereço %s", self.nome, url)
                return url, etapa
            abriu_algo = True
            falhas.append(f"{url} (abriu, mas não é a tela de entrada do eProc)")
            log.info("  %s abriu, mas não mostrou a tela de entrada do eProc.", url)
            self.nav.diagnosticar("eproc-endereco")
        lista = "; ".join(falhas) or "nenhum endereço no catálogo"
        if abriu_algo:
            raise PortalIndisponivel(
                f"nenhum endereço do {self.nome} mostrou a tela de entrada ({lista}). Se o "
                f"endereço do portal mudou, corrija-o {ONDE_CORRIGIR_ENDERECO}; a captura da "
                "tela está em Logs\\diagnostico.")
        raise PortalIndisponivel(
            f"o {self.nome} não respondeu em nenhum endereço conhecido ({lista}). Confira a "
            f"internet e, se o endereço mudou, corrija-o {ONDE_CORRIGIR_ENDERECO}.")

    def _falha_de_credencial(self) -> LoginFalhou:
        self.nav.diagnosticar("eproc-login-recusado")
        self.nav.esquecer_sessao()
        return LoginFalhou(
            f"o {self.nome} recusou o usuário ou a senha. Confira-os {ONDE_CADASTRAR_ACESSO} "
            "e tente de novo.")

    def _login_com_senha(self, etapa: str) -> None:
        if not (self.usuario and self.senha):
            raise LoginFalhou(
                f"não há usuário e senha do {self.nome} guardados neste computador. Cadastre-os "
                f"{ONDE_CADASTRAR_ACESSO} - ou escolha “{ENTRAR_MANUALMENTE}” em "
                f"{AJUSTES_ACESSOS}.")
        log.info("Fazendo login no %s como %s...", self.nome, mascarar(self.usuario))
        self.ctx.status(f"Entrando no {self.nome}...")
        minutos = max(1, int(self.opcoes.espera_login_min))
        limite = time.monotonic() + minutos * 60
        envios = 0
        codigos = 0
        recado = ""
        avisou_captcha = False
        avisou_perfil = False
        conhecida_em = time.monotonic()
        tolerancia = max(30.0, float(self.opcoes.espera_s))
        self._aguardando_usuario = False
        while True:
            self._checar_cancelado()
            if etapa == "logado":
                self._login_concluido()
                return
            if time.monotonic() > limite:
                self.nav.diagnosticar("eproc-login-prazo")
                raise LoginFalhou(
                    f"o prazo de {plural(minutos, 'minuto', 'minutos')} para concluir o login no "
                    f"{self.nome} acabou. Tente de novo (o prazo se ajusta em "
                    f"{CAMPO_PRAZO_LOGIN}).")
            if etapa == "recusado":
                raise self._falha_de_credencial()
            if etapa == "bloqueado":
                self.nav.diagnosticar("eproc-usuario-bloqueado")
                raise LoginFalhou(
                    f"o {self.nome} informa que o seu usuário está bloqueado ou inativo. "
                    "Regularize-o no próprio portal (ou com o suporte do tribunal) e tente de novo.")
            if etapa == "senha_expirada":
                self.nav.diagnosticar("eproc-senha-expirada")
                raise LoginFalhou(
                    f"o {self.nome} pede a troca da senha. Troque-a no próprio portal e "
                    f"atualize-a em {AJUSTES_ACESSOS}.")
            if etapa == "login":
                if envios >= MAX_ENVIOS_SENHA:
                    self.nav.diagnosticar("eproc-login-sem-saida")
                    raise LoginFalhou(
                        f"o {self.nome} voltou à tela de login sem dizer por quê. Confira usuário "
                        f"e senha; se persistir, ligue “{MOSTRAR_NAVEGADOR}” para acompanhar, "
                        f"ou escolha “{ENTRAR_MANUALMENTE}” em {AJUSTES_ACESSOS}.")
                self._preencher_login()
                envios += 1
            elif etapa == "otp":
                codigos, recado = self._resolver_codigo(codigos, recado, limite)
            elif etapa == "captcha":
                if not self._janela_visivel():
                    self.nav.diagnosticar("eproc-captcha")
                    raise LoginFalhou(
                        f"o {self.nome} pediu uma verificação (captcha) que só se resolve na "
                        f"janela do navegador, e ela está oculta. Ligue “{MOSTRAR_NAVEGADOR}” "
                        f"(ou escolha “{ENTRAR_MANUALMENTE}” em {AJUSTES_ACESSOS}) e tente de "
                        "novo.")
                if not avisou_captcha:
                    avisou_captcha = True
                    self._restaurar_janela()
                    self._evento_de_espera("acao_na_janela", "captcha", limite)
                    self.ctx.avisar(
                        "Verificação no eProc",
                        f"O {self.nome} pediu uma verificação (captcha) na janela do navegador. "
                        "Resolva-a lá; o programa continua sozinho em seguida.")
                self._dormir(2)
            elif etapa == "perfil":
                avisou_perfil = self._escolher_perfil(avisou_perfil, limite)
            else:
                if time.monotonic() - conhecida_em > tolerancia:
                    self.nav.diagnosticar("eproc-login-incompleto")
                    raise LoginFalhou(
                        f"o login no {self.nome} não foi concluído: apareceu uma tela que o "
                        "programa não reconhece (aviso, troca de senha ou instabilidade). Ligue "
                        f"“{MOSTRAR_NAVEGADOR}” para ver a tela, ou escolha “{ENTRAR_MANUALMENTE}” "
                        f"em {AJUSTES_ACESSOS}.")
                self._dormir(1)
            etapa = self._etapa(apos_envio=envios > 0)
            if etapa != "desconhecido":
                conhecida_em = time.monotonic()

    def _preencher_login(self) -> None:
        usuario = self._visivel("login_usuario", espera_ms=3000)
        senha = self._visivel("login_senha", espera_ms=1500)
        if usuario is None and senha is None:
            return                  # a tela trocou: quem chama olha de novo
        if usuario is not None:
            usuario.fill(self.usuario)
        if senha is not None:
            senha.fill(self.senha)
        botao = self._visivel("login_botao", espera_ms=3000)
        marca = self._marcar()
        try:
            if botao is None:
                raise RuntimeError("sem botão")
            botao.click(timeout=15000)
        except Exception as erro:
            log.debug("  o botão Entrar não aceitou o clique (%s); enviando pelo teclado.",
                      type(erro).__name__)
            (senha or usuario).press("Enter")
        self._esperar(lambda: self._trocou(marca), self.espera_ms)
        self._esperar_carga()

    def _resolver_codigo(self, codigos: int, recado: str, limite: float) -> tuple[int, str]:
        """Pede ao usuário o código do aplicativo autenticador e o envia.

        Devolve (códigos já pedidos, recado para o próximo pedido). Quem
        chama olha a página de novo: se ainda for a do código, ele foi
        recusado.
        """
        if codigos >= MAX_CODIGOS:
            self.nav.diagnosticar("eproc-codigo-recusado")
            raise LoginFalhou(
                "não consegui concluir a verificação em duas etapas: o eProc recusou os códigos "
                "informados. Confira se o relógio do computador e o do celular estão certos e "
                "tente de novo.")
        restante = int(limite - time.monotonic())
        codigo = self.ctx.pedir_codigo(
            "Código do autenticador",
            recado + "Digite o código de 6 dígitos do seu aplicativo autenticador "
            f"({self.nome}).", max(30, min(restante, 120)),
            # o autenticador muda sozinho a cada 30 s: não há "pedir novo código"
            reenviavel=False)
        if codigo is None:
            if self.ctx.cancelado():
                raise Cancelado()
            if self._etapa_em_alguma_aba() == "logado":
                log.info("Código aceito na janela do navegador.")
                return codigos + 1, ""
            if self._janela_visivel() and limite > time.monotonic():
                # Sem quem digite o código aqui (a linha de comando sem
                # terminal, como a da skill do Claude, ou o diálogo fechado):
                # com a janela do navegador à vista - a do eProc abre sempre
                # visível -, o usuário o digita lá, no campo do próprio eProc,
                # dentro do prazo do login. Como no e-SAJ; antes, desistia na hora.
                return self._esperar_codigo_na_janela(codigos, limite)
            self.nav.diagnosticar("eproc-codigo-nao-informado")
            raise LoginFalhou(
                "o código do aplicativo autenticador não foi informado. Clique em "
                f"“{TENTAR_DE_NOVO}” quando estiver com o celular à mão.")
        codigo = re.sub(r"\D", "", codigo)
        if not codigo:
            # "pedir outro" não é tentativa: quem limita é o prazo do login
            return codigos, ("Espere o aplicativo mostrar um código novo (ele muda a cada "
                             "30 segundos) e digite-o. ")
        campo = self._visivel("otp_campo", espera_ms=3000)
        if campo is None:
            return codigos + 1, recado
        self.ctx.status("Conferindo o código no eProc...")
        campo.fill(codigo)
        botao = self._visivel("otp_botao", espera_ms=2000)
        marca = self._marcar()
        try:
            if botao is None:
                raise RuntimeError("sem botão")
            botao.click(timeout=15000)
        except Exception:
            campo.press("Enter")
        self._esperar(lambda: self._trocou(marca), self.espera_ms)
        self._esperar_carga()
        if self._esperar(lambda: self._etapa() != "otp", 1500):
            log.info("Código aceito.")
            return codigos + 1, ""
        log.warning("O eProc não aceitou esse código (errado ou vencido).")
        return codigos + 1, ("O eProc não aceitou o código anterior (errado ou vencido). Espere "
                             "o aplicativo mostrar um código novo e digite-o. ")

    def _esperar_codigo_na_janela(self, codigos: int, limite: float) -> tuple[int, str]:
        """Espera o usuário digitar o código do autenticador na janela do
        navegador, até ``limite`` (o fim do prazo do login, em time.monotonic).

        Volta assim que a página sai da tela do código (aceito: logado ou a
        escolha do perfil; recusado, ela volta à tela do código e quem chama
        pede de novo, até MAX_CODIGOS): quem chama olha a página de novo."""
        self._restaurar_janela()
        self._evento_de_espera("login_aguardando", "codigo", limite)
        resta = max(1, -int(-(limite - time.monotonic()) // 60))     # minutos, para cima
        self.ctx.avisar(
            f"Digite o código na janela do {self.nome}",
            "Digite o código de 6 dígitos do seu aplicativo autenticador na janela do navegador, "
            "no campo do próprio eProc, e confirme. Aguardo até "
            f"{plural(resta, 'minuto', 'minutos')} e sigo sozinho.")
        while time.monotonic() < limite:
            self._dormir(2)
            if self._etapa_em_alguma_aba() != "otp":
                log.info("Código digitado na janela do navegador.")
                return codigos + 1, ""
        minutos = max(1, int(self.opcoes.espera_login_min))
        self.nav.diagnosticar("eproc-codigo-prazo")
        raise LoginFalhou(
            f"o prazo de {plural(minutos, 'minuto', 'minutos')} para concluir o login no "
            f"{self.nome} acabou sem o código do aplicativo autenticador. Tente de novo (o prazo "
            f"se ajusta em {CAMPO_PRAZO_LOGIN}).")

    def _perfis_na_tela(self) -> list:
        achados = []
        for seletor in self.sel.get("perfil", []):
            try:
                loc = self.pg.locator(seletor)
                for i in range(min(loc.count(), 30)):
                    item = loc.nth(i)
                    if item.is_visible():
                        achados.append(item)
            except Exception:
                continue
            if achados:
                break
        return achados

    def _escolher_perfil(self, avisou: bool, limite: float | None = None) -> bool:
        """Mais de um perfil (advogado, servidor, magistrado...): escolhe o
        único, ou o configurado ([eproc] perfil); senão, o usuário escolhe.
        ``limite`` (time.monotonic): o fim do prazo do login, para o evento."""
        botoes = self._perfis_na_tela()
        descricoes = []
        for b in botoes:
            try:
                descricoes.append(limpar(b.get_attribute("data-descricao") or b.inner_text()))
            except Exception:
                descricoes.append("")
        escolhido = None
        if len(botoes) == 1:
            escolhido = 0
        elif self.perfil_preferido:
            alvo = sem_acento(self.perfil_preferido)
            escolhido = next((i for i, d in enumerate(descricoes) if alvo in sem_acento(d)), None)
        if escolhido is not None:
            log.info("Entrando com o perfil %s.", descricoes[escolhido] or "(único)")
            marca = self._marcar()
            botoes[escolhido].click(timeout=15000)
            self._esperar(lambda: self._trocou(marca), self.espera_ms)
            self._esperar_carga()
            return avisou
        if not botoes:
            self._dormir(1)
            return avisou
        lista = ", ".join(d for d in descricoes if d) or f"{len(botoes)} perfis"
        if not self._janela_visivel():
            self.nav.diagnosticar("eproc-perfil")
            raise LoginFalhou(
                f"o seu usuário tem mais de um perfil no {self.nome} ({lista}). Ligue "
                f"“{MOSTRAR_NAVEGADOR}” (ou escolha “{ENTRAR_MANUALMENTE}”) para escolher o "
                f"perfil na janela, ou indique-o em {AJUSTES_ACESSOS}, campo “{PERFIL_EPROC}”.")
        if not avisou:
            self._restaurar_janela()
            if limite is None:
                limite = time.monotonic() + max(1, int(self.opcoes.espera_login_min)) * 60
            self._evento_de_espera("acao_na_janela", "perfil", limite)
            self.ctx.avisar(
                "Escolha o perfil no eProc",
                f"O seu usuário tem mais de um perfil no {self.nome} ({lista}). Escolha, na "
                "janela do navegador, o perfil com que os processos devem ser baixados; o "
                "programa continua sozinho em seguida.")
        self._dormir(2)
        return True

    def _login_na_janela(self) -> None:
        if not self._janela_visivel():
            jeito = "com certificado digital" if self.modo_login == "certificado" else "manual"
            raise LoginFalhou(
                f"o login {jeito} no {self.nome} precisa da janela do navegador, que está "
                f"oculta. Ligue “{MOSTRAR_NAVEGADOR}” e tente de novo.")
        self._restaurar_janela()
        minutos = max(1, int(self.opcoes.espera_login_min))
        if self.modo_login == "certificado":
            mensagem = (f"Na janela do navegador que se abriu, entre no {self.nome} com o "
                        "certificado digital (escolha o certificado e digite o PIN do token).")
        else:
            mensagem = ("Conclua o login na janela do navegador que se abriu (usuário e senha, "
                        "código do autenticador ou certificado digital, como de costume).")
        limite = time.monotonic() + minutos * 60
        self._aguardando_usuario = False
        self._evento_de_espera("login_aguardando",
                               "certificado" if self.modo_login == "certificado" else "manual",
                               limite)
        self.ctx.avisar(f"Entre no {self.nome}",
                        f"{mensagem} Aguardo até {plural(minutos, 'minuto', 'minutos')} e sigo "
                        "sozinho.")
        while time.monotonic() < limite:
            self._dormir(2)
            if self._etapa_em_alguma_aba() == "logado":
                self.ctx.status("Login concluído.")
                self._login_concluido()
                return
        self.nav.diagnosticar("eproc-manual-prazo")
        raise LoginFalhou(
            f"o prazo de {plural(minutos, 'minuto', 'minutos')} para o login na janela do "
            f"navegador acabou. Tente de novo (o prazo se ajusta em {CAMPO_PRAZO_LOGIN}).")

    def _ancora(self) -> str:
        """Um link desta sessão para voltar à área logada (e testar a sessão).

        O endereço em que o login termina nem sempre se pode abrir de novo:
        a escolha de perfil (acao=pessoa_usuario_logar) é um POST, e o
        retorno do SSO leva um código de uso único - repetido, ele pede login
        ou troca o perfil. Nesses casos vale o link do painel da página.
        """
        url = self._url()
        acao = parametros(url).get("acao", "")
        interna = re.search(r"(?<!externo_)controlador\.php", url, re.I)
        if interna and acao and not _RE_ACAO_DE_ENTRADA.search(acao):
            return url
        for a in ler_html(self._html()).elementos():
            href = a.attr("href") if a.tag == "a" else ""
            acao_link = parametros(href).get("acao", "") if "controlador.php" in href else ""
            if ("hash=" in href and re.search(r"painel|principal", acao_link)
                    and "externo_controlador" not in href):
                return urllib.parse.urljoin(url, href)
        return url

    def _pos_login(self) -> None:
        # A página em que o login termina pode ser um redirecionamento; a
        # âncora (link desta sessão para voltar à área logada) é a que tem a
        # barra de pesquisa.
        self._esperar(lambda: self._visivel("pesquisa_rapida") is not None, 5000)
        self._url_ancora = self._ancora()
        self._logado = True
        self._ouvir_avisos(self.pg)
        self._minimizar()
        log.info("Login concluído no %s.", self.nome)
        self.ctx.status("Login concluído.")

    def _estado_sessao(self) -> bool | None:
        """A sessão ainda vale? Pergunta-se ao servidor por um link desta sessão
        (a página de entrada da área logada), sem mexer na tela.

        True: vale; False: o portal disse que não; None: não deu para saber
        (rede fora) - e aí não se presume sessão perdida, para um soluço da
        rede não virar um novo login com código.
        """
        alvo = self._url_ancora or self._url_processo
        if not alvo:
            return False
        try:
            resp = self._buscar(alvo, prazo_ms=20000)
        except Cancelado:
            raise
        except Exception as erro:
            log.debug("  sessão: %s", str(erro)[:160])
            return None
        if resp.status >= 500:
            return None
        if resp.status < 400 and not motivo_sessao(decodificar_html(resp.dados, resp.tipo),
                                                   resp.url, self.sel):
            return True
        if resp.canal == "contexto":
            # O canal direto pode não levar os cookies da janela (cookie
            # particionado, perfil novo): sem confirmar pela própria janela,
            # isso virava "sessão perdida" e um novo login com código a cada
            # processo.
            try:
                outra = self._buscar(alvo, prazo_ms=20000, canais=["pagina"])
            except Cancelado:
                raise
            except Exception as erro:
                log.debug("  sessão (pela janela): %s", str(erro)[:160])
                return False
            if outra.status < 400 and not motivo_sessao(
                    decodificar_html(outra.dados, outra.tipo), outra.url, self.sel):
                log.info("    (o canal direto não levou a sessão; sigo pela janela do navegador)")
                self._canais = ["pagina", "contexto"]
                return True
        return False

    def _sessao_ativa(self) -> bool:
        return self._estado_sessao() is True

    def _perdeu_sessao(self, motivo: str) -> SessaoPerdida:
        self._logado = False
        return SessaoPerdida(f"a sessão do {self.nome} caiu ({motivo})")

    def _motivo_na_pagina(self, pagina=None) -> str:
        """motivo_sessao da página aberta no navegador."""
        pagina = pagina or self.pg
        url = self._url(pagina)
        motivo = motivo_sessao(self._html(pagina), url, self.sel)
        if (motivo == "login" and re.search(r"(?<!externo_)controlador\.php", url, re.I)
                and self._visivel("login_senha", pagina) is None
                and self._visivel("login_usuario", pagina) is None):
            # Campos de login escondidos numa página da área logada (janela
            # de "entrar de novo" que só aparece quando a sessão vence) não
            # são a tela de login: na página viva, só conta o que se vê.
            return ""
        return motivo

    def _conferir_sessao_na_pagina(self, pagina=None) -> None:
        motivo = self._motivo_na_pagina(pagina)
        if not motivo:
            return
        if motivo == "sem_assinatura" and self._sessao_ativa():
            raise RuntimeError("o eProc recusou um link desta sessão (\"link sem assinatura\")")
        raise self._perdeu_sessao({"encerrada": "o eProc encerrou a sessão",
                                   "login": "o eProc voltou à tela de login",
                                   "sem_assinatura": "link sem assinatura"}.get(motivo, motivo))

    # ============================================================ rede
    def _buscar_por(self, canal: str, url: str, metodo: str, corpo, cabecalhos,
                    prazo_ms: int) -> Resposta:
        if canal == "contexto":
            req = self.nav.contexto.request
            extra = {"timeout": prazo_ms}
            if cabecalhos:
                extra["headers"] = dict(cabecalhos)
            if metodo == "POST":
                r = req.post(url, data=corpo or "", **extra)
            else:
                r = req.get(url, **extra)
            try:
                return Resposta(r.status, r.url or url,
                                (r.headers or {}).get("content-type", ""), r.body(), canal)
            finally:
                try:
                    r.dispose()      # o corpo também fica na memória do navegador
                except Exception:
                    pass
        d = self.pg.evaluate(_JS_BUSCAR, {"url": url, "metodo": metodo, "corpo": corpo,
                                          "cabecalhos": cabecalhos or {}, "prazo": prazo_ms})
        if not isinstance(d, dict) or d.get("erro"):
            raise RuntimeError((d or {}).get("erro") or "resposta vazia da janela do navegador")
        return Resposta(int(d.get("status") or 0), d.get("url") or url, d.get("tipo") or "",
                        base64.b64decode(d.get("dados") or ""), canal)

    def _buscar(self, url: str, metodo: str = "GET", corpo: str | None = None,
                cabecalhos: dict | None = None, prazo_ms: int | None = None,
                canais: list[str] | None = None) -> Resposta:
        """Uma requisição com os cookies da sessão.

        Primeiro pelo canal do contexto (rápido, sem passar o arquivo pela
        página); se ele falhar (rede com proxy, que esse canal não usa),
        pela própria janela - e esse passa a ser o primeiro dali em diante.
        Erro 5xx, 408 e 429 é repetido uma vez.
        """
        url = urllib.parse.urljoin(self._url() or self.base, url)
        prazo = int(prazo_ms or max(60000, self.espera_ms))
        ultimo: Exception | None = None
        ordem = list(canais or self._canais)
        for canal in ordem:
            for tentativa in (1, 2):
                self._checar_cancelado()
                try:
                    resp = self._buscar_por(canal, url, metodo, corpo, cabecalhos, prazo)
                except Cancelado:
                    raise
                except Exception as erro:
                    ultimo = erro
                    log.debug("  canal %s falhou: %s", canal, str(erro)[:160])
                    break
                if (resp.status >= 500 or resp.status in (408, 429)) and tentativa == 1:
                    ultimo = RuntimeError(f"HTTP {resp.status}")
                    self._dormir(1.5)
                    continue
                if canais is None and canal != self._canais[0]:
                    log.info("    (%s)", "o canal direto não respondeu; sigo pela própria janela "
                             "do navegador" if canal == "pagina" else
                             "a janela do navegador não buscou o arquivo; sigo pelo canal direto")
                    self._canais.remove(canal)
                    self._canais.insert(0, canal)
                return resp
        raise RuntimeError(f"não consegui falar com o eProc ({explicar_erro(str(ultimo))})")

    # ------------------------------------------------------- diagnóstico
    def _tela_sigilosa(self, numero: Numero | None = None,
                       r: ResultadoProcesso | None = None) -> bool:
        """A tela em curso é de processo em segredo de justiça - apurado
        agora, numa tentativa anterior, ou já sabido pelo motor (pasta de
        sigilosos, pauta)?"""
        em_curso = getattr(self, "_em_curso", None)
        if em_curso is not None:
            numero = numero or em_curso[0]
            r = r or em_curso[1]
        return bool(getattr(self.nav, "sigiloso_em_curso", False)
                    or (r is not None and r.sigiloso)
                    or (numero is not None and numero.nome_arquivo in self.sigilosos_apurados))

    def _diagnosticar_processo(self, rotulo: str, numero: Numero | None = None,
                               r: ResultadoProcesso | None = None) -> str:
        """Guarda a tela do processo em Logs\\diagnostico - menos a de processo
        sigiloso, que traz as partes (o registro diz por quê). Devolve a dica
        para a mensagem de erro: onde ver a tela, ou que ela não foi guardada."""
        sigiloso = self._tela_sigilosa(numero, r)
        diagnosticar_processo(self.nav, rotulo, sigiloso)
        return DICA_SEM_DIAGNOSTICO if sigiloso else DICA_DIAGNOSTICO

    # ======================================================== download
    def baixar(self, numero: Numero, destino_pdf: Path,
               senha: str | None = None) -> ResultadoProcesso:
        """Os autos do processo em ``destino_pdf``.

        ``senha`` existe pelo contrato comum e é ignorada: o eProc não tem
        senha de processo (o acesso ao sigiloso depende do perfil do usuário).
        """
        destino_pdf = Path(destino_pdf)
        r = ResultadoProcesso(ordem=0, numero=numero.formatado, tribunal=self.tribunal.sigla,
                              sistema=self.sistema)
        inicio = time.monotonic()
        self._notas = []
        self._em_curso = (numero, r)
        try:
            if numero.e_dependente:
                raise ProcessoNaoEncontrado(
                    "o eProc não usa número de incidente com barra (/NN): cada incidente tem "
                    "número próprio. Ponha na relação o número do incidente.")
            self._garantir_login(numero)
            self._baixar(numero, destino_pdf, r)
            r.situacao = OK
            r.arquivo = str(destino_pdf)
        except ProcessoNaoEncontrado as erro:
            r.situacao, r.detalhe = NAO_ENCONTRADO, str(erro)
        except SemAcesso as erro:
            r.situacao, r.detalhe = SEM_ACESSO, str(erro)
        except SigilosoSemSenha as erro:
            r.situacao, r.detalhe, r.sigiloso = SIGILOSO_SEM_SENHA, str(erro), True
        except (Cancelado, LoginFalhou, SessaoPerdida, PortalIndisponivel, PermissionError):
            raise
        except Exception as erro:
            if self.ctx.cancelado():
                raise Cancelado() from erro
            msg = str(erro) or type(erro).__name__
            if self._estado_sessao() is False:
                raise self._perdeu_sessao(msg[:160]) from erro
            if not _erro_transitorio(msg):
                self._diagnosticar_processo(f"eproc-falha-{numero.nome_arquivo}", numero, r)
            raise
        finally:
            r.segundos = round(time.monotonic() - inicio, 1)
            self._em_curso = None
            if numero.nome_arquivo in self.sigilosos_apurados:
                r.sigiloso = True
            elif r.sigiloso:
                self.sigilosos_apurados.add(numero.nome_arquivo)
        return r

    def _garantir_login(self, numero: Numero) -> None:
        candidatos = [normalizar_base(u) for u in self.tribunal.urls_para(numero, self.grau)]
        if self._logado and self.base in candidatos:
            return
        self.entrar(numero)

    def _baixar(self, numero: Numero, destino: Path, r: ResultadoProcesso) -> None:
        rotulo = numero.formatado
        self._checar_cancelado()
        self.ctx.status(f"{rotulo}: consultando o {self.nome}...")
        self._abrir_processo(numero)
        info = self._ler_processo()
        if indica_sigilo(info["texto"]):
            r.sigiloso = True
        if not info["eventos"]:
            self._sem_eventos(info, r)
        if r.sigiloso:
            log.info("    processo em segredo de justiça (sigiloso).")
        self._manifesto = None
        eventos: list[Evento] | None = None
        if self.modo_pdf == "completo":
            # A lista inteira de eventos ANTES do Download Completo, que tira o
            # navegador da página do processo: é ela que faz a capa e o mapa
            # (com só a primeira página, a capa contava os eventos pela metade).
            eventos = self._eventos_antes_do_completo(numero, info, rotulo)
            if self._baixar_completo(numero, destino, r, info, eventos):
                completos = eventos is not None
                if completos:
                    r.documentos = len(ordenar_documentos(eventos))
                self._gravar_capa(numero, destino, info, eventos if completos else info["eventos"],
                                  r.sigiloso, eventos_completos=completos)
                r.detalhe = "; ".join(self._notas)
                return
        if eventos is None:
            eventos = self._todos_os_eventos(info["eventos"], rotulo)
        ausentes = eventos_ausentes(eventos)
        if ausentes:
            log.warning("    a lista lida começa depois do evento 1: faltam os eventos %s "
                        "(paginação?).", ausentes)
        self._montar_documentos(numero, destino, r, info, eventos, ausentes)
        self._gravar_capa(numero, destino, info, eventos, r.sigiloso)
        r.detalhe = "; ".join(self._notas)

    def _eventos_antes_do_completo(self, numero: Numero, info: dict,
                                   rotulo: str) -> list[Evento] | None:
        """Os eventos de todas as páginas, para a capa do Download Completo.

        None quando a paginação falha: o Download Completo segue assim mesmo
        (o arquivo do eProc traz os documentos de todos os eventos), e a capa
        avisa que a lista de eventos ficou incompleta. Se a leitura saiu da
        primeira página, volta-se à do processo, onde está o botão do
        Download Completo.
        """
        self._paginou = False
        try:
            eventos = self._todos_os_eventos(info["eventos"], rotulo)
        except (Cancelado, SessaoPerdida, LoginFalhou):
            raise
        except Exception as erro:
            log.warning("    não consegui ler todas as páginas de eventos (%s); a capa do Download "
                        "Completo fica só com a primeira.", str(erro)[:160])
            eventos = None
        if self._paginou:
            self._voltar_ao_processo(numero)
        return eventos

    def _sem_eventos(self, info: dict, r: ResultadoProcesso) -> None:
        """A página do processo abriu sem eventos: sigilo, falta de acesso, ou
        layout novo (este último é o único que vale tentar de novo)."""
        texto = info["texto"]
        if r.sigiloso:
            raise SemAcesso("processo em segredo de justiça: o eProc não mostrou os eventos e "
                            "documentos ao seu usuário")
        if info["vista"]:
            raise SemAcesso("o eProc só libera a íntegra deste processo por pedido de vista "
                            "(acesso sem procuração, com verificação). Peça vista no portal")
        if diz_sem_acesso(texto):
            raise SemAcesso("o eProc não liberou os autos deste processo para o seu usuário")
        self._diagnosticar_processo("eproc-sem-eventos", r=r)
        raise RuntimeError("a página do processo abriu, mas a lista de eventos não apareceu")

    # ------------------------------------------------------ abrir processo
    def _abrir_processo(self, numero: Numero) -> None:
        self._avisos_portal.clear()
        rapida = self._pela_pesquisa_rapida(numero)
        if rapida == "processo":
            return self._chegou(numero)
        if rapida == "sem_acesso":
            raise SemAcesso("o eProc não liberou este processo para o seu usuário (acesso sem "
                            "procuração ou restrito). Peça vista no portal")
        if rapida != "indisponivel":
            log.info("    a pesquisa rápida não abriu o processo; tentando a consulta processual.")
        # O alerta "Processo não encontrado" da pesquisa rápida não pode ser
        # lido de novo como a resposta da consulta (que é quem confirma).
        self._avisos_portal.clear()
        consulta = self._pela_consulta(numero)
        if consulta == "processo":
            return self._chegou(numero)
        if consulta == "sem_acesso":
            raise SemAcesso("o eProc não liberou este processo para o seu usuário (acesso sem "
                            "procuração ou restrito). Peça vista no portal")
        # "Não encontrado" é definitivo (não se tenta de novo): vale o que a
        # consulta processual disse; a pesquisa rápida sozinha só basta quando
        # não há consulta processual nesta tela. Consulta que não concluiu é
        # falha passageira, e não processo inexistente.
        if consulta == "nao_encontrado" or (rapida == "nao_encontrado"
                                            and consulta == "indisponivel"):
            # A dica final diz onde mais procurar (modelos.dica_de_grau): o
            # outro grau - ou, para o número que só existe no 2º, que trocar
            # o grau do lote não muda nada.
            if self.grau == paginacao.SEGUNDO_GRAU:
                raise ProcessoNaoEncontrado(
                    f"não encontrado no {self.nome}. Confira o número; "
                    f"{dica_de_grau(numero, '2g')}.")
            raise ProcessoNaoEncontrado(
                f"não encontrado no 1º grau do {self.nome}. Confira o número; "
                f"{dica_de_grau(numero, '1g')}.")
        dica = self._diagnosticar_processo(f"eproc-abrir-{numero.nome_arquivo}", numero)
        if rapida == "nao_encontrado":
            raise RuntimeError("a pesquisa rápida não achou o processo, e a consulta processual "
                               f"não respondeu para confirmar ({dica})")
        raise RuntimeError("não consegui abrir o processo nem pela pesquisa rápida nem pela "
                           f"consulta processual (o portal pode ter mudado: {dica})")

    def _campo_pesquisa(self):
        campo = self._visivel("pesquisa_rapida", espera_ms=1500)
        if campo is None and self._url_ancora:
            self._ir(self._url_ancora)
            self._conferir_sessao_na_pagina()
            campo = self._visivel("pesquisa_rapida", espera_ms=5000)
        return campo

    def _pela_pesquisa_rapida(self, numero: Numero) -> str:
        campo = self._campo_pesquisa()
        if campo is None:
            return "indisponivel"
        campo.fill("")
        campo.fill(numero.digitos)
        marca = self._marcar()
        campo.press("Enter")
        mudou = self._esperar(lambda: self._trocou(marca) or bool(self._avisos_portal),
                              self.espera_ms)
        self._esperar_carga()
        # A resposta pode ser uma página que se redireciona sozinha (por
        # script) para a do processo: dá-se um instante antes de desistir.
        resultado = ["desconhecido"]

        def pronto():
            resultado[0] = self._classificar(numero)
            return resultado[0] != "desconhecido"

        self._esperar(pronto, 3000)
        if resultado[0] in ("nao_encontrado", "sem_acesso") and not mudou:
            # A página nem trocou: o "Nenhum registro encontrado" é o de uma
            # tabela vazia do painel (padrão do InfraPHP), não a resposta.
            return "desconhecido"
        return resultado[0]

    def _na_pagina_do_processo(self, raiz: No) -> bool:
        if primeiro(raiz, self.sel.get("processo_pagina", [])) is not None:
            return True
        # Só o endereço não basta: processo_selecionar também responde
        # "Processo não encontrado" (processo baixado, número de outro órgão).
        return "acao=processo_selecionar" in self._url() and not diz_nao_encontrado(raiz.texto())

    def _classificar(self, numero: Numero, seguir_link: bool = True) -> str:
        """processo | sem_acesso | nao_encontrado | desconhecido."""
        self._conferir_sessao_na_pagina()
        html = self._html()
        raiz = ler_html(html)
        if self._na_pagina_do_processo(raiz):
            return "processo"
        if seguir_link:
            link = self._link_do_processo(raiz, numero)
            if link:
                self._ir(link)
                self._esperar_carga()
                return self._classificar(numero, seguir_link=False)
        texto = self._texto() + "\n" + "\n".join(self._avisos_portal)
        if diz_nao_encontrado(texto):
            return "nao_encontrado"
        if ("processo_vista_sem_procuracao" in html or diz_sem_acesso(texto)
                or self._visivel("captcha") is not None):
            return "sem_acesso"
        return "desconhecido"

    def _link_do_processo(self, raiz: No, numero: Numero) -> str:
        """Na lista de resultados, o link (assinado) que abre ESTE processo."""
        for a in raiz.elementos():
            if a.tag != "a":
                continue
            href = a.attr("href")
            if "processo_selecionar" not in href:
                continue
            if (f"num_processo={numero.digitos}" in href
                    or numero.digitos in re.sub(r"\D", "", a.texto())):
                return urllib.parse.urljoin(self._url(), href)
        return ""

    def _href(self, chave: str) -> str:
        no = primeiro(ler_html(self._html()), self.sel.get(chave, []))
        if no is None or not no.attr("href"):
            return ""
        return urllib.parse.urljoin(self._url(), no.attr("href"))

    def _pela_consulta(self, numero: Numero) -> str:
        link = self._href("menu_consulta")
        if not link and self._url_ancora:
            self._ir(self._url_ancora)
            self._conferir_sessao_na_pagina()
            link = self._href("menu_consulta")
        if not link:
            return "indisponivel"
        self._ir(link)
        self._esperar_carga()
        self._conferir_sessao_na_pagina()
        ajax = url_ajax_consulta(self._html())
        if ajax:
            resultado = self._consulta_ajax(urllib.parse.urljoin(self._url(), ajax), numero)
            if resultado != "desconhecido":
                return resultado
        return self._consulta_formulario(numero)

    def _consulta_ajax(self, url: str, numero: Numero) -> str:
        """POST da própria consulta (o que o formulário faz por baixo):
        devolve JSON com o linkProcessoAssinado."""
        corpo = urllib.parse.urlencode([
            ("hdnInfraTipoPagina", "1"), ("acao_origem", "consultar"), ("acao_retorno", ""),
            ("acao", "processo_consultar"), ("hdnNumPaginaAtual", "1"),
            ("hdnNumSentidoNavegacao", "1"), ("tipoPesquisa", "NU"),
            ("numNrProcesso", numero.digitos), ("selIdClasseSelecionados", ""), ("strChave", "")])
        try:
            resp = self._buscar(url, "POST", corpo, {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest"})
        except Cancelado:
            raise
        except Exception as erro:
            log.debug("  consulta por ajax: %s", str(erro)[:160])
            return "desconhecido"
        texto = decodificar_html(resp.dados, resp.tipo)
        if resp.status >= 400:
            return "desconhecido"
        if motivo_sessao(texto, resp.url, self.sel) and not self._sessao_ativa():
            raise self._perdeu_sessao("a consulta processual pediu login de novo")
        link = link_assinado_da_consulta(texto, numero.digitos)
        if link is None:
            return "desconhecido"
        if link == "":
            return "nao_encontrado"
        self._ir(urllib.parse.urljoin(self._url(), _html.unescape(link)))
        self._esperar_carga()
        return self._classificar(numero)

    def _consulta_formulario(self, numero: Numero) -> str:
        radio = self._visivel("consulta_tipo_numero", espera_ms=1000)
        if radio is not None:
            try:
                radio.check(timeout=5000)
            except Exception:
                pass
        campo = self._visivel("consulta_numero", espera_ms=5000)
        if campo is None:
            return "indisponivel"
        campo.fill(numero.digitos)
        botao = self._visivel("consulta_botao", espera_ms=3000)
        marca = self._marcar()
        try:
            if botao is None:
                raise RuntimeError("sem botão")
            botao.click(timeout=15000)
        except Exception:
            campo.press("Enter")
        # Espera a resposta (página nova, ou resultados no lugar) antes de ler:
        # a tela da consulta, vazia, pode dizer "nenhum registro encontrado".
        mudou = self._esperar(lambda: self._trocou(marca) or bool(self._avisos_portal)
                              or bool(self.pg.evaluate(
                                  "() => { const r = document.querySelector("
                                  "'#divAreaResultadosAjax'); return !!(r && r.innerText.trim());"
                                  " }")), self.espera_ms)
        self._esperar_carga()
        resultado = ["desconhecido"]

        def pronto():
            resultado[0] = self._classificar(numero)
            return resultado[0] != "desconhecido"

        self._esperar(pronto, 3000)
        if resultado[0] in ("nao_encontrado", "sem_acesso") and not mudou:
            return "desconhecido"       # a tela da consulta, ainda vazia, não é resposta
        return resultado[0]

    def _chegou(self, numero: Numero) -> None:
        """A página aberta é mesmo a deste processo? (pelos 20 dígitos)."""
        self._esperar_carga()
        raiz = ler_html(self._html())
        no = primeiro(raiz, self.sel.get("capa_numero", []))
        bruto = (no.texto() or no.attr("value")) if no is not None else ""
        achados = re.sub(r"\D", "", bruto)
        trocados = "não baixei, para não gravar autos trocados"
        # O número do processo é o PRIMEIRO do campo: "5000099-... (originário:
        # <este>)" é a página de outro processo que só menciona este.
        numeros = [re.sub(r"\D", "", x) for x in _RE_CNJ_SOLTO.findall(bruto)]
        if numeros:
            if numeros[0] != numero.digitos:
                raise RuntimeError(f"a página aberta é de outro processo ({bruto[:40]}); "
                                   f"{trocados}")
        elif achados:
            if numero.digitos not in achados:
                raise RuntimeError(f"a página aberta é de outro processo "
                                   f"({(no.texto() or achados)[:40]}); {trocados}")
        else:
            # Sem o campo do número (layout novo): o número do próprio link,
            # se houver; senão, o número inteiro escrito na página. NÃO vale
            # juntar todos os dígitos da página - a lista de processos
            # relacionados, colada a outros números, "conteria" este.
            p = parametros(self._url())
            do_link = re.sub(r"\D", "", p.get("num_processo") or p.get("txtNumProcesso") or "")
            if len(do_link) == 20:
                if do_link != numero.digitos:
                    raise RuntimeError(f"a página aberta é de outro processo ({do_link}); "
                                       f"{trocados}")
            else:
                texto = raiz.texto()
                if (numero.formatado not in texto
                        and not re.search(rf"(?<!\d){numero.digitos}(?!\d)", texto)):
                    raise RuntimeError("a página aberta pelo eProc não traz este número de "
                                       f"processo; {trocados}")
        self._url_processo = self._url()

    def _voltar_ao_processo(self, numero: Numero) -> None:
        if self._url_processo:
            try:
                self._ir(self._url_processo)
                self._esperar_carga()
                self._conferir_sessao_na_pagina()
                self._chegou(numero)
                return
            except (Cancelado, SessaoPerdida):
                raise
            except Exception as erro:
                log.debug("  volta ao processo pelo link: %s", str(erro)[:120])
        self._abrir_processo(numero)

    # --------------------------------------------------- página do processo
    def _ler_processo(self) -> dict:
        """Capa, partes, eventos desta página e o texto que denuncia o sigilo."""
        self._esperar_carga()
        raiz = ler_html(self._html())
        eventos = ler_eventos(raiz, self.sel)
        if not eventos:
            # a lista pode chegar um instante depois do resto da página
            for _ in range(4):
                self._esperar_ms(500)
                raiz = ler_html(self._html())
                eventos = ler_eventos(raiz, self.sel)
                if eventos:
                    break
        try:
            texto = self.pg.evaluate(_JS_TEXTO_SEM, self.sel.get("eventos_tabela", [])) or ""
        except Exception:
            texto = raiz.texto(excluir=tuple(buscar(raiz, self.sel.get("eventos_tabela", []))))
        html = self._html()
        return {
            "capa": ler_capa(raiz, self.sel),
            "partes": ler_partes(raiz, self.sel),
            "eventos": eventos,
            "texto": texto,
            "vista": ("processo_vista_sem_procuracao" in html
                      or "acesso integra do processo" in sem_acento(texto)),
        }

    def _valor_paginacao(self) -> str:
        for seletor in self.sel.get("eventos_paginacao", []):
            try:
                valor = self.pg.evaluate(
                    "s => { const el = document.querySelector(s);"
                    " return el ? String(el.value) : null; }", seletor)
            except Exception:
                continue
            if valor is not None:
                return valor
        return ""

    def _todos_os_eventos(self, primeiros: list[Evento], rotulo: str) -> list[Evento]:
        """Os eventos de TODAS as páginas (o eProc mostra uma de cada vez)."""
        self._paginou = False
        if self._listar_todos():
            self._paginou = True
            todos = ler_eventos(ler_html(self._html()), self.sel)
            # "Listar todos" pode ser só uma página maior: a paginação, se
            # ainda houver, é percorrida do mesmo jeito (senão os eventos
            # mais antigos - a inicial - ficavam de fora sem aviso).
            primeiros = juntar_paginas(todos, primeiros)
        valores, marcado = opcoes_de_paginacao(ler_html(self._html()), self.sel)
        if len(valores) <= 1:
            return primeiros
        atual = self._valor_paginacao() or marcado
        coletados = [primeiros]
        log.info("    %d páginas de eventos.", len(valores))
        for n, valor in enumerate(valores, 1):
            if valor == atual:
                continue
            self._checar_cancelado()
            self.ctx.status(f"{rotulo}: lendo a página {n} de {len(valores)} dos eventos...")
            self._paginou = True
            mudou = self._mudar_pagina(valor)
            self._conferir_sessao_na_pagina()
            if not mudou:
                self._diagnosticar_processo("eproc-paginacao")
                raise RuntimeError(f"a página {n} dos eventos não abriu (paginação do eProc)")
            coletados.append(ler_eventos(ler_html(self._html()), self.sel))
        return juntar_paginas(*coletados)

    def _listar_todos(self) -> bool:
        """Se a versão do eProc tiver "listar todos os eventos" (seletor
        configurável), usa-o: menos páginas a percorrer (ou nenhuma)."""
        if not self.sel.get("eventos_listar_todos"):
            return False
        botao = self._visivel("eventos_listar_todos", espera_ms=0)
        if botao is None:
            return False
        marca = self._marcar()
        try:
            botao.click(timeout=10000)
        except Exception:
            return False
        self._esperar(lambda: self._trocou(marca), self.espera_ms)
        self._esperar_carga()
        self._conferir_sessao_na_pagina()
        return True

    def _mudar_pagina(self, valor: str) -> bool:
        seletor = ""
        for s in self.sel.get("eventos_paginacao", []):
            try:
                if self.pg.locator(s).count():
                    seletor = s
                    break
            except Exception:
                continue
        antes = {e.chave for e in ler_eventos(ler_html(self._html()), self.sel)}
        marca = self._marcar()
        # Pelo VALOR exato, por script. O select_option do Playwright casa a
        # string também com o RÓTULO das opções - e na paginação do eProc as
        # opções são value="0" rótulo "1", value="1" rótulo "2"...: pedir a
        # página "1" abria a primeira de novo.
        try:
            modo = self.pg.evaluate(_JS_PAGINAR, {"s": seletor, "v": valor, "funcao": False})
        except Exception:
            modo = "navegando"   # a página trocou durante a chamada: é o esperado

        def pronto():
            # Com navegação, a página nova; sem ela (paginação por ajax), o
            # seletor no valor pedido. Nos dois casos, a lista tem de mudar.
            trocou = self._trocou(marca)
            if trocou and self._motivo_na_pagina():
                return True      # a sessão caiu: quem chama confere e avisa já
            if not trocou and self._valor_paginacao() != valor:
                return False
            agora = {e.chave for e in ler_eventos(ler_html(self._html()), self.sel)}
            return bool(agora) and agora != antes

        if modo == "seletor":
            # Select sem onchange (há versões com um botão ao lado): se a lista
            # não mudar logo, chama-se a função de paginação do próprio eProc.
            ok = self._esperar(pronto, min(self.espera_ms, 5000))
            if not ok:
                log.debug("  paginação: o seletor não trocou a página; chamando alterarPagina.")
                try:
                    self.pg.evaluate(_JS_PAGINAR, {"s": seletor, "v": valor, "funcao": True})
                except Exception:
                    pass
                ok = self._esperar(pronto, self.espera_ms)
        else:
            ok = self._esperar(pronto, self.espera_ms)
        self._esperar_carga()
        return ok

    # ------------------------------------------------------ documentos
    def _metadados(self, numero: Numero, modo: str) -> dict:
        """Título, assunto e programa do PDF (o manifesto põe as palavras-chave).
        No modo completo, o criador e o produtor do arquivo do eProc ficam."""
        from .. import __version__
        titulo = f"Processo {numero.formatado}"
        if modo == "completo":
            return {"title": titulo,
                    "subject": f"Autos do {self.nome} — arquivo completo gerado pelo próprio "
                               "eProc (Download Completo), sem páginas acrescentadas"}
        return {"title": titulo,
                "subject": f"Autos do {self.nome} — documento a documento, paginação de cada "
                           "documento igual à do eProc",
                "creator": f"Helestron {__version__}", "producer": f"Helestron {__version__}",
                "creationDate": datetime.now().strftime("D:%Y%m%d%H%M%S")}

    def _manifesto_de(self, numero: Numero, info: dict, eventos: list[Evento] | None,
                      sigiloso: bool, modo: str, ausentes: str = "") -> dict:
        return manifesto_do_processo(numero, self.nome, self.tribunal.sigla,
                                     info.get("capa") or {}, info.get("partes") or [], eventos,
                                     sigiloso, modo, ausentes, grau=self.grau)

    def _montar_documentos(self, numero: Numero, destino: Path, r: ResultadoProcesso,
                           info: dict, eventos: list[Evento], ausentes: str = "") -> None:
        """O PDF documento a documento: só as páginas dos documentos, na ordem
        dos eventos, sem capa e sem página nenhuma entre eles - o eProc não
        numera folhas, e cada documento conserva a paginação própria (o
        rótulo da página diz "Ev. 1 INIC1 p. 2"). O documento que não veio e
        a gravação ficam com UMA página de aviso no lugar, marcada como não
        citável no rótulo, no marcador e no manifesto."""
        rotulo = numero.formatado
        docs = ordenar_documentos(eventos)
        if not docs:
            dica = self._diagnosticar_processo(f"eproc-sem-documentos-{numero.nome_arquivo}",
                                               numero, r)
            raise SemAcesso(f"o eProc mostrou {plural(len(eventos), 'evento', 'eventos')}, mas "
                            "nenhum documento com link (sem acesso aos documentos, ou o portal "
                            f"mudou: {dica})")
        log.info("    %s, %s.", plural(len(eventos), "evento", "eventos"),
                 plural(len(docs), "documento", "documentos"))
        r.documentos = len(docs)
        partes: list[pdf.Parte] = []          # uma por documento, na ordem de docs
        faltaram: list[Documento] = []
        midias_salvas: list[str] = []
        midias_fora = 0
        obtidos = 0
        # pelo nome do destino: no 2º grau, "<número> (2G)" (o motor as leva
        # junto com os autos pelo mesmo nome)
        pasta_midias = destino.parent / "_controle" / "midias" / Path(destino).stem

        def documento(doc: Documento, dados: bytes, tipo: str, origem: str) -> None:
            prefixo, numerar = rotulo_de_pagina(doc, origem)
            partes.append(pdf.Parte(titulo_do_documento(doc), dados, tipo, rotulo_pagina=prefixo,
                                    numerar=numerar, info=info_do_documento(doc, origem),
                                    manter_sumario=tipo == "pdf"))

        def aviso(doc: Documento, texto: str, situacao: str, origem: str, **extra) -> None:
            prefixo, numerar = rotulo_de_pagina(doc, origem, situacao)
            sufixo = SUFIXO_NAO_INCLUIDO if situacao == "ausente" else SUFIXO_GRAVACAO
            partes.append(pdf.Parte(titulo_do_documento(doc) + sufixo, texto.encode("utf-8"),
                                    "aviso", rotulo_pagina=prefixo, numerar=numerar,
                                    info=info_do_documento(doc, origem, situacao, **extra)))

        def nao_veio(doc: Documento, motivo: str, origem: str = "") -> None:
            faltaram.append(doc)
            aviso(doc, self._aviso_falha(doc, motivo), "ausente", origem or origem_esperada(doc),
                  motivo=limpar(motivo)[:300])

        try:
            for i, doc in enumerate(docs, 1):
                self._checar_cancelado()
                if i > 1 and PAUSA_DOCUMENTOS_S:
                    self._dormir(PAUSA_DOCUMENTOS_S)
                self.ctx.status(f"{rotulo}: documento {i} de {len(docs)} "
                                f"(evento {doc.evento}, {doc.rotulo})...")
                if doc.mimetype in MIMETYPES_MIDIA and not self.opcoes.baixar_midias:
                    midias_fora += 1
                    aviso(doc, self._aviso_midia(doc, None), "midia", "midia")
                    continue
                try:
                    tipo, dados, extra = self._obter_documento(doc)
                except _FalhaDocumento as erro:
                    log.warning("    %s não veio: %s", doc.rotulo, str(erro)[:200])
                    nao_veio(doc, str(erro))
                    continue
                if tipo == "midia":
                    caminho = None
                    if self.opcoes.baixar_midias:
                        caminho = self._salvar_midia(doc, dados, extra, pasta_midias)
                    if caminho:
                        midias_salvas.append(str(caminho))
                        obtidos += 1
                    else:
                        midias_fora += 1
                    texto = self._aviso_midia(doc, caminho, destino.parent,
                                              falhou=self.opcoes.baixar_midias and caminho is None)
                    arquivo = ""
                    if caminho:
                        try:
                            arquivo = Path(caminho).relative_to(destino.parent).as_posix()
                        except ValueError:
                            arquivo = Path(caminho).name
                    aviso(doc, texto, "midia", "midia", arquivo=arquivo)
                elif tipo == "html":
                    documento(doc, html_em_utf8(dados), "html", "html")
                    obtidos += 1
                elif tipo == "imagem":
                    try:
                        convertido = pdf.imagem_para_pdf(dados)
                    except Exception as erro:
                        motivo = f"a imagem não pôde ser convertida ({str(erro)[:120]})"
                        log.warning("    %s: %s", doc.rotulo, motivo)
                        nao_veio(doc, motivo, "imagem")
                        continue
                    documento(doc, convertido, "pdf", "imagem")
                    obtidos += 1
                elif tipo == "pdf" and pdf.contar_paginas_de(dados) is None:
                    # Conferido aqui, e não só no pdf.juntar: assim o documento
                    # entra no "incompleto" e o manifesto diz o motivo.
                    motivo = ("o arquivo do documento veio inválido (não abre como PDF, está "
                              "protegido por senha ou não tem páginas)")
                    log.warning("    %s: %s", doc.rotulo, motivo)
                    nao_veio(doc, motivo, "pdf")
                else:
                    documento(doc, dados, tipo, "texto" if tipo == "texto" else "pdf")
                    obtidos += 1
            if faltaram and not obtidos:
                # Só páginas de aviso (as gravações não baixadas também são
                # aviso): isso não são os autos - é falha, e o motor tenta de novo.
                raise RuntimeError("nenhum documento do processo pôde ser baixado")
            self._checar_cancelado()
            manifesto = self._manifesto_de(numero, info, eventos, r.sigiloso, "documentos",
                                           ausentes)
            self.ctx.status(f"{rotulo}: montando o PDF ({len(docs)} documentos)...")
            r.paginas = pdf.juntar(partes, destino, metadados=self._metadados(numero, "documentos"),
                                   manifesto=manifesto)
            self._manifesto = manifesto
        except BaseException:
            # Sem o PDF, as gravações já salvas ficariam soltas no acervo
            # compartilhado - e, de processo sigiloso, fora do alcance do motor,
            # que só as leva para a pasta de sigilosos junto com o PDF pronto.
            self._apagar_midias(midias_salvas, pasta_midias)
            raise
        # O documento que o próprio pdf.juntar não conseguiu incluir (conversão
        # que falhou lá) também tem página de aviso no lugar: entra na conta.
        faltaram = [d for d, p in zip(docs, partes)
                    if p.falhou or (p.info or {}).get("situacao") == "ausente"]
        log.info("    salvo: %s (%d páginas)", destino.name, r.paginas)
        incompleto = []
        if ausentes:
            incompleto.append(f"evento {ausentes} (não listado)" if ausentes == "1"
                              else f"eventos {ausentes} (não listados)")
            self._notas.append(
                ("o evento 1 não apareceu" if ausentes == "1" else
                 f"os eventos {ausentes} não apareceram")
                + " na lista do portal (confira no eProc)")
        if faltaram:
            incompleto.append(descrever_faltantes(faltaram))
            self._notas.append(
                plural(len(faltaram), "documento não veio e tem", "documentos não vieram e têm")
                + " página de aviso no lugar")
        r.incompleto = "; ".join(incompleto)
        if midias_salvas:
            r.midias = midias_salvas
            self._notas.append(plural(len(midias_salvas), "gravação salva", "gravações salvas")
                               + " em _controle\\midias")
        if midias_fora:
            self._notas.append(plural(midias_fora, "gravação", "gravações") + " nos autos, "
                               + ("não baixada" if midias_fora == 1 else "não baixadas"))

    @staticmethod
    def _apagar_midias(caminhos: list[str], pasta: Path) -> None:
        for c in caminhos:
            try:
                Path(c).unlink()
            except OSError:
                pass
        try:
            pasta.rmdir()            # só se ficou vazia
        except OSError:
            pass

    # As páginas de aviso dizem que não são páginas dos autos: estão no lugar
    # de um documento, e "p. 1" delas não existe no eProc.
    NAO_E_PAGINA = ("\n\nEsta página é um aviso do Helestron, posto no lugar do documento: não é "
                    "página dos autos e não deve ser citada.")

    def _aviso_falha(self, doc: Documento, motivo: str) -> str:
        return (f"O documento {doc.rotulo} do evento {doc.evento} não pôde ser baixado do "
                f"{self.nome}.\n\nMotivo: {motivo}\n\nConsulte-o diretamente no portal."
                + self.NAO_E_PAGINA)

    def _aviso_midia(self, doc: Documento, caminho: Path | None, raiz: Path | None = None,
                     falhou: bool = False) -> str:
        cabeca = (f"Arquivo de áudio ou vídeo: {doc.rotulo} (evento {doc.evento}"
                  + (f", {doc.data}" if doc.data else "") + ").\n\nGravações não cabem no PDF. ")
        if caminho is not None:
            try:
                relativo = Path(caminho).relative_to(raiz) if raiz else Path(caminho)
            except ValueError:
                relativo = Path(caminho)
            return cabeca + f"O arquivo foi salvo em:\n{relativo}" + self.NAO_E_PAGINA
        if falhou:
            return cabeca + ("O arquivo veio do portal, mas não pôde ser salvo no computador "
                             "(disco cheio ou sem permissão?). Consulte-o diretamente no eProc."
                             + self.NAO_E_PAGINA)
        return cabeca + ("O arquivo não foi baixado: para baixá-lo, ative a opção de baixar as "
                         "gravações de audiência e baixe o processo de novo, ou consulte-o "
                         "diretamente no eProc." + self.NAO_E_PAGINA)

    def _salvar_midia(self, doc: Documento, dados: bytes, extensao: str,
                      pasta: Path) -> Path | None:
        nome = (sistema.nome_seguro(f"Evento {doc.evento} - {doc.rotulo}", "midia")
                + (extensao or ".bin"))
        alvo = pasta / nome
        try:
            sistema.gravar_atomico(alvo, dados)
        except OSError as erro:
            log.warning("    gravação %s não pôde ser salva: %s", nome, erro)
            return None
        log.info("    gravação: %s (%.1f MB)", nome, len(dados) / 1048576)
        return alvo

    def _obter_documento(self, doc: Documento) -> tuple[str, object, str]:
        """O conteúdo de um documento: (tipo, dados, extensão).

        tipo: pdf | html (dados = texto já decodificado) | imagem | midia |
        texto. Levanta _FalhaDocumento quando nenhum caminho deu certo, e
        SessaoPerdida quando o motivo é a sessão.
        """
        href = urllib.parse.urljoin(self._url_processo or self._url() or self.base, doc.href)
        motivos: list[str] = []
        visitados: set[str] = set()
        recusas: dict[str, int] = {}

        def tentar(url: str):
            if not url or url in visitados:
                return None
            visitados.add(url)
            achado = self._interpretar(url, doc)
            if achado[0] == "falha":
                motivos.append(achado[1])
                recusas[url] = achado[2] if len(achado) > 2 else 0
                return None
            return achado

        candidatos = [url_implementacao(href)] if url_implementacao(href) != href else []
        for url in candidatos + [href]:
            achado = tentar(url)
            # moldura -> conteúdo (que ainda pode ser uma casca com o arquivo
            # num frame): no máximo três saltos, e nunca o mesmo endereço duas vezes
            saltos = 0
            while achado is not None and achado[0] == "moldura" and saltos < 3:
                achado = tentar(achado[1])
                saltos += 1
            if achado is None or achado[0] == "moldura":
                continue
            return achado
        # Último recurso: a moldura aberta numa aba, lida depois dos scripts.
        # Se a própria moldura foi recusada pelo servidor, a aba não ajuda.
        if recusas.get(href, 0) >= 400:
            raise _FalhaDocumento("; ".join(dict.fromkeys(motivos)))
        src = self._src_pela_aba(href)
        if src:
            achado = tentar(src)
            if achado is not None and achado[0] == "moldura":
                achado = tentar(achado[1])
            if achado is not None and achado[0] != "moldura":
                return achado
        raise _FalhaDocumento("; ".join(dict.fromkeys(motivos))
                              or "o portal não entregou o documento")

    def _interpretar(self, url: str, doc: Documento) -> tuple:
        try:
            resp = self._buscar(url)
        except Cancelado:
            raise
        except Exception as erro:
            return ("falha", str(erro)[:200] or type(erro).__name__)
        tipo = tipo_do_conteudo(resp.dados, resp.tipo, doc.mimetype)
        if tipo == "html" or resp.status >= 400:
            texto = decodificar_html(resp.dados, resp.tipo)
            motivo = motivo_sessao(texto, resp.url, self.sel)
            if motivo:
                if resp.canal == "contexto":
                    # O canal direto pode não levar os cookies da janela (perfil
                    # novo, cookie particionado): confirma-se pela janela.
                    try:
                        outra = self._buscar(url, canais=["pagina"])
                    except Cancelado:
                        raise
                    except Exception:
                        outra = None
                    if outra is not None and not motivo_sessao(
                            decodificar_html(outra.dados, outra.tipo), outra.url, self.sel):
                        log.info("    (o canal direto não levou a sessão; sigo pela janela do "
                                 "navegador)")
                        self._canais = ["pagina", "contexto"]
                        return self._interpretar(url, doc)
                if not self._sessao_ativa():
                    raise self._perdeu_sessao("o eProc pediu login de novo ao abrir um documento")
                return ("falha", "o eProc recusou o link do documento")
            if resp.status >= 400:
                return ("falha", f"o portal recusou o documento (HTTP {resp.status})", resp.status)
            conteudo = parametros(url).get("acao") == "acessar_documento_implementacao"
            src = src_do_iframe(texto, resp.url, self.sel, so_iframe=conteudo)
            if src:
                return ("moldura", src)
            marcas_do_sistema = ("divInfraBarraSistema", "txtNumProcessoPesquisaRapida",
                                 "txaInfraMsg", "divInfraCaptcha")
            if any(marca in texto for marca in marcas_do_sistema):
                return ("falha", "o portal devolveu uma página de aviso em vez do documento")
            embutido = conteudo_embutido(texto, resp.url)
            if embutido and embutido not in (url, resp.url):
                return ("moldura", embutido)
            return ("html", texto, ".html")
        if tipo in ("pdf", "imagem", "texto"):
            return (tipo, resp.dados, "")
        if tipo == "midia":
            return ("midia", resp.dados, extensao_da_midia(resp.dados, resp.tipo, doc.mimetype))
        if tipo == "vazio":
            return ("falha", "o portal devolveu um arquivo vazio")
        if tipo == "zip":
            return ("falha", "o documento é um arquivo compactado (ZIP), que não cabe no PDF")
        formato = (resp.tipo or "").split(";")[0] or doc.mimetype or "desconhecido"
        return ("falha", f"formato que não cabe no PDF ({formato})")

    def _src_pela_aba(self, href: str) -> str:
        """Abre a moldura numa aba e lê o endereço do iframe (quando ele é
        posto por script e não está no HTML)."""
        seletores = self.sel.get("documento_iframe", [])
        try:
            with self.nav.nova_aba() as aba:
                aba.goto(href, wait_until="domcontentloaded", timeout=self.espera_ms)
                try:      # uma espera só, por qualquer um deles
                    aba.locator(", ".join(seletores)).first.wait_for(state="attached",
                                                                     timeout=3000)
                except Exception:
                    pass
                for seletor in seletores:
                    src = aba.evaluate(
                        "s => { const f = document.querySelector(s);"
                        " return f ? (f.src || f.getAttribute('src') || '') : ''; }", seletor)
                    if src and not src.startswith(("about:", "javascript")):
                        return src
                return src_do_iframe(aba.content(), aba.url, self.sel)
        except Cancelado:
            raise
        except Exception as erro:
            log.debug("  moldura do documento: %s", str(erro)[:160])
            return ""

    # ------------------------------------------------- Download Completo
    def _baixar_completo(self, numero: Numero, destino: Path, r: ResultadoProcesso,
                         info: dict, eventos: list[Evento] | None = None) -> bool:
        """O PDF que o próprio eProc gera, sem página nenhuma acrescentada: a
        página M do PDF é a página M do arquivo do eProc, com o sumário e os
        rótulos que ele trouxer. False quando não deu (e a página volta para a
        do processo, para a montagem por documentos). ``eventos``: a lista
        inteira (None se não foi lida), para o manifesto."""
        try:
            arquivos = self._gerar_completo(numero)
            for i, dados in enumerate(arquivos, 1):
                if pdf.contar_paginas_de(dados) is None:
                    raise RuntimeError("o arquivo completo entregue pelo eProc não abre como PDF"
                                       + (f" (parte {i})" if len(arquivos) > 1 else ""))
        except (Cancelado, SessaoPerdida, LoginFalhou):
            raise
        except Exception as erro:
            motivo = str(erro) or type(erro).__name__
            log.warning("    o Download Completo do eProc não deu certo (%s); montando documento "
                        "a documento.", motivo[:200])
            self._notas.append(f"o Download Completo do eProc falhou ({motivo[:120]}); montado "
                               "documento a documento")
            self._voltar_ao_processo(numero)
            return False
        self.ctx.status(f"{numero.formatado}: gravando o arquivo completo...")
        manifesto = self._manifesto_de(numero, info, eventos, r.sigiloso, "completo",
                                       eventos_ausentes(eventos) if eventos is not None else "")
        metadados = self._metadados(numero, "completo")
        if len(arquivos) == 1:
            # O arquivo entra como veio (o que se acrescenta vai por salvamento
            # incremental); o marcador só entra se o arquivo não tiver sumário.
            r.paginas = pdf.gravar(destino, arquivos[0], marcadores=[(TITULO_COMPLETO, 1)],
                                   metadados=metadados, manifesto=manifesto,
                                   preservar_sumario=True)
        else:
            # Processo grande sai em partes (ZIP): cada uma recomeça na página 1
            partes = [pdf.Parte(f"{TITULO_COMPLETO} — parte {i}", dados, "pdf",
                                rotulo_pagina=f"Parte {i} p. ", manter_sumario=True)
                      for i, dados in enumerate(arquivos, 1)]
            r.paginas = pdf.juntar(partes, destino, metadados=metadados, manifesto=manifesto)
        if not manifesto.get("partes"):
            manifesto["partes"] = [{"inicio": 1, "paginas": r.paginas}]
        self._manifesto = manifesto
        log.info("    salvo: %s (%d páginas, Download Completo)", destino.name, r.paginas)
        self._notas.append("PDF completo gerado pelo próprio eProc")
        return True

    def _gerar_completo(self, numero: Numero) -> list[bytes]:
        rotulo = numero.formatado
        botao = self._visivel("completo_botao", espera_ms=5000)
        if botao is None:
            raise RuntimeError("a página do processo não tem o botão Download Completo")
        self.ctx.status(f"{rotulo}: pedindo o Download Completo ao eProc...")
        marca = self._marcar()
        try:
            botao.click(timeout=15000)
        except Exception:
            onclick = botao.get_attribute("onclick") or ""
            m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)", onclick)
            if not m:
                raise
            self._ir(urllib.parse.urljoin(self._url(), _html.unescape(m.group(1))))
        self._esperar(lambda: self._trocou(marca), self.espera_ms)
        self._esperar_carga()
        self._conferir_sessao_na_pagina()
        limite = time.monotonic() + self.espera_completo_min * 60
        formulario = self._visivel("completo_formulario", espera_ms=5000)
        if formulario is not None or "agendar_arquivo_completo" in self._url():
            seletor = ", ".join(self.sel.get("completo_marcar", [])) or "input[type='checkbox']"
            try:
                caixas = self.pg.evaluate(_JS_DESMARCAR, {"seletor": seletor,
                                                          "digitos": numero.digitos})
            except Exception:
                caixas = {}
            caixas = caixas if isinstance(caixas, dict) else {}
            if caixas.get("caixas", 0) > 1 and not caixas.get("principal"):
                # Vários processos marcados e nenhum é este: gerar assim daria
                # erro no eProc - ou um arquivo com os autos de outro processo.
                raise RuntimeError("não identifiquei este processo entre os marcados para o "
                                   "Download Completo")
            if caixas.get("desmarcadas"):
                n = caixas["desmarcadas"]
                log.info("    %s no Download Completo (com dois marcados, o eProc dá erro).",
                         plural(n, "processo relacionado desmarcado",
                                "processos relacionados desmarcados"))
            gerar = self._visivel("completo_gerar", espera_ms=5000)
            if gerar is None:
                raise RuntimeError("não achei o botão de gerar o arquivo completo")
            marca = self._marcar()
            gerar.click(timeout=15000)
            self._esperar(lambda: self._trocou(marca), self.espera_ms)
            self._esperar_carga()
        inicio = time.monotonic()
        links: list[str] = []
        while True:
            self._checar_cancelado()
            try:
                self._conferir_sessao_na_pagina()
                achados = self.pg.evaluate(_JS_LINKS_COMPLETO) or []
            except (SessaoPerdida, Cancelado):
                raise
            except Exception:
                achados = []      # a página se recarrega sozinha enquanto gera
            # só os arquivos DESTE processo (a página pode listar outros)
            links = links_do_completo(achados, numero.digitos)
            if links:
                break
            texto = sem_acento(self._texto())
            if re.search(r"erro ao gerar|falha na geracao|nao foi possivel gerar", texto):
                raise RuntimeError("o eProc informou erro na geração do arquivo completo")
            if time.monotonic() > limite:
                minutos = self.espera_completo_min
                texto_min = (f"{minutos:g} minuto" if minutos == 1
                             else f"{minutos:g} minutos")
                raise RuntimeError(f"o eProc não terminou de gerar o arquivo completo em "
                                   f"{texto_min}")
            self.ctx.status(f"{rotulo}: o eProc está gerando o arquivo completo "
                            f"({int(time.monotonic() - inicio)} s)...")
            self._dormir(INTERVALO_COMPLETO_S)
        arquivos: list[bytes] = []
        for link in links:
            self.ctx.status(f"{rotulo}: baixando o arquivo completo...")
            resp = self._buscar(link, prazo_ms=max(300000, self.espera_ms))
            if resp.status != 200:
                raise RuntimeError(f"o arquivo completo não veio (HTTP {resp.status})")
            if resp.dados[:4] == b"PK\x03\x04":
                arquivos += pdfs_do_zip(resp.dados)
                continue
            if len(resp.dados) < 1024 or not pdf.e_pdf(resp.dados):
                raise RuntimeError("o arquivo completo entregue pelo eProc não é um PDF válido")
            arquivos.append(resp.dados)
        if not arquivos:
            raise RuntimeError("o eProc não entregou nenhum PDF no Download Completo")
        return arquivos

    # ------------------------------------------------------------- capa
    def _gravar_capa(self, numero: Numero, destino: Path, info: dict, eventos: list[Evento],
                     sigiloso: bool, eventos_completos: bool = True) -> None:
        """_controle/<nome do PDF>_capa.txt e _capa.json (o motor os leva junto
        com o PDF, pelo mesmo nome - no 2º grau, "<número> (2G)_capa.json"): a
        capa, o arquivo, como citar, o mapa de todos os documentos e todos os
        eventos. Capa é conveniência, não dever: falha vai só para o log."""
        controle = destino.parent / "_controle"
        nome = Path(destino).stem
        quando = datetime.now()
        capa, partes = info.get("capa") or {}, info.get("partes") or []
        try:
            texto = texto_capa_txt(numero, self.nome, capa, partes, eventos, sigiloso,
                                   self._manifesto, quando, eventos_completos)
            sistema.gravar_atomico(controle / f"{nome}_capa.txt", texto.encode("utf-8"))
        except Exception as erro:
            log.debug("capa não gravada: %s", erro)
        try:
            dados = dados_da_capa(numero, self.nome, self.tribunal.sigla, capa, partes, eventos,
                                  sigiloso, self._manifesto, quando, eventos_completos,
                                  grau=self.grau)
            sistema.gravar_atomico(controle / f"{nome}_capa.json",
                                   json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8"))
        except Exception as erro:
            log.debug("capa (JSON) não gravada: %s", erro)
