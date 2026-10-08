"""Texto dos autos e das transcrições, no formato que a IA lê melhor.

Um PDF de 800 folhas é pesado para qualquer assistente: lê-lo como imagem
custa caro e lento. O texto extraído, com a marca de citação em cada página,
deixa o Claude e o ChatGPT citarem "fl. 123" (e-SAJ) ou "evento 4, PET1, p. 2"
(eProc) sem abrir o PDF, e cabe numa busca. O arquivo de texto é um cache:
refeito sozinho quando o PDF muda (ou quando é de um formato anterior).

Formato 2 do texto (o único que este módulo grava):

* 1ª linha, legível por máquina::

    # helestron-texto 2 | sistema=<esaj|eproc|desconhecido> | paginacao=<folhas|documento|nao_garantida> | paginas=<n> | ausentes=<faixas>

  ``paginas`` é o total de páginas do PDF; ``ausentes``, as páginas do PDF
  que são página de aviso no lugar do que não veio (no e-SAJ, são as
  próprias folhas, porque a página N é a folha N), em faixas ("6-7, 40").
  Nos autos do 2º grau (o manifesto diz "grau": "2g"; sem manifesto, o
  " (2G)" no nome do PDF), a linha termina em ``| grau=2g``; nos do 1º grau,
  ela é a de sempre (ausente = 1º grau).
* depois, linhas entre colchetes: como citar e, no eProc, a capa e os eventos
  sem documento (tirados do manifesto de paginação gravado no PDF);
* cada página começa por uma marca, e o que vai entre os colchetes é o que se
  cita:

  - e-SAJ: ``=== [fl. N] ===``; a folha que não veio tem, logo abaixo, a linha
    ``[folha não disponível no e-SAJ: <motivo>]`` e nada do texto da página
    de aviso;
  - eProc: ``=== [evento N, RÓTULO, p. Y] (pág. M do PDF) ===``; documento
    HTML do eProc, sem página: ``=== [evento N, RÓTULO] (pág. M do PDF) ===``;
    documento que não veio: ``=== [evento N, RÓTULO — NÃO INCLUÍDO] (...) ===``;
    gravação: ``=== [evento N, RÓTULO — gravação fora do PDF] (...) ===``;
    arquivo completo gerado pelo eProc: ``=== [arquivo completo do eProc, pág. M] ===``;
  - PDF sem manifesto e sem como conferir a paginação: ``=== [pág. M do PDF] ===``
    (``paginacao=nao_garantida``). "(pág. M do PDF)" é só a posição no
    arquivo, para navegar: nunca se cita.

  Abaixo da marca vem ``[documento: ...]`` (o marcador do PDF a que a página
  pertence). Página dos autos sem texto que se extraia (imagem digitalizada
  sem OCR; no e-SAJ, só com o carimbo da Pasta Digital e o número da folha)
  tem, antes do conteúdo, uma linha que começa por
  ``[página sem texto extraível``: é preciso ver a página no PDF. Linha do
  conteúdo da página que imite uma marca ou uma dessas linhas recebe um "· "
  na frente: um documento das partes não consegue forjar uma folha.

``analisar`` devolve o texto e o que dele se sabe (sistema, paginação,
páginas de aviso e as páginas sem texto, citadas como os autos as citam),
para quem automatiza: a linha de comando o põe no JSON ("paginas_sem_texto").

PDF sem manifesto é de versão anterior (1.0.1 ou antes): do e-SAJ, vale
"fl. N" só se TODOS os marcadores "(fls. A-B)" começarem na página A e o PDF
terminar na última folha deles; do eProc antigo (1º marcador "Capa — dados do
processo" na página 1), a capa é marcada como não sendo dos autos e as demais
páginas são citadas pelos marcadores dos eventos.

Autos do 2º grau: as marcas são as mesmas (a folha N é a da Pasta Digital do
2º grau; no eProc, os eventos do processo no 2º grau), mas a abertura e o
"como citar" dizem que os autos de origem (1º grau), de mesmo número, são
outro arquivo, com numeração própria - e que o carimbo "fls." de outros
autos na página não é folha destes (COMO_CITAR_ESAJ_2G).
"""

from __future__ import annotations

import bisect
import functools
import logging
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..nucleo import cnj, paginacao

log = logging.getLogger(__name__)

VERSAO_TEXTO = 2
CABECA = f"# helestron-texto {VERSAO_TEXTO}"
GRAU_1, GRAU_2 = "1g", paginacao.SEGUNDO_GRAU

ESAJ, EPROC, DESCONHECIDO = "esaj", "eproc", "desconhecido"
FOLHAS, DOCUMENTO, NAO_GARANTIDA = "folhas", "documento", "nao_garantida"

# Marcas de página. MARCA_PAGINA (e-SAJ) é a do formato 1, mantida.
MARCA_PAGINA = "=== [fl. {n}] ==="
MARCA = "=== [{citacao}] ==="
MARCA_COM_PAGINA = "=== [{citacao}] (pág. {m} do PDF) ==="
# Logo abaixo da marca, o documento (marcador do PDF) a que a página pertence.
MARCA_DOCUMENTO = "[documento: {titulo}]"
MARCA_AUSENTE = "[folha não disponível no e-SAJ: {motivo}]"
SEM_TEXTO = "[página sem texto extraível — pode ser imagem digitalizada; confira no PDF]"
SEM_TEXTO_CARIMBO = ("[página sem texto extraível além do carimbo do e-SAJ — pode ser imagem "
                     "digitalizada; confira no PDF]")
SEM_TEXTO_ILEGIVEL = "[página sem texto extraível — a página não pôde ser lida; confira no PDF]"
# O começo comum das três linhas acima: é por ele que analisar() as acha
PREFIXO_SEM_TEXTO = "[página sem texto extraível"
ILEGIVEL = "[página ilegível]"         # o que a leitura devolve da página corrompida
CITACAO_CAPA = "capa gerada pelo Helestron — não é página dos autos"
NAO_INCLUIDO = "NÃO INCLUÍDO"
GRAVACAO = "gravação fora do PDF"

# Títulos dos marcadores dos PDFs do eProc da versão 1.0.1 (download/eproc.py),
# copiados aqui para não importar o download.
TITULO_CAPA_ANTIGA = "Capa — dados do processo"
TITULO_COMPLETO_ANTIGO = "Autos completos (arquivo gerado pelo eProc)"
# Marcador da peça que não veio, no PDF peça a peça do e-SAJ da 1.0.1
TITULO_AVISO_ANTIGO = "Documento não incluído"
# Frases das páginas de aviso da 1.0.1 (eproc._aviso_falha, eproc._aviso_midia e
# pdf._aviso_de_falha), com o rótulo e o evento: um documento de verdade que
# fale em "não pôde ser baixado" não vira aviso.
_AVISO_FALHA_ANTIGO = "O documento {rotulo} do evento {evento} não pôde ser baixado do"
_AVISO_INCLUSAO_ANTIGO = "não pôde ser incluído neste arquivo"
_AVISO_MIDIA_ANTIGO = "Arquivo de áudio ou vídeo: {rotulo} (evento {evento}"

_RE_MARCA = re.compile(r"^=== \[(?P<cit>[^\]\n]+)\](?: \(pág\. (?P<pag>\d+) do PDF\))? ===$",
                       re.M)
_RE_NUMERO_NA_CITACAO = re.compile(r"\b(?:fls?|pág)\. (\d+)")
_RE_EVENTO_NA_CITACAO = re.compile(r"^evento (?P<ev>\d+), (?P<rot>[^,—]+?)(?:, p\. \d+| — .*)?$")
# Linha do conteúdo de uma página que imita a estrutura do texto
_RE_RESERVADA = re.compile(
    r"^\s*(?:=+\s*\[|\[\s*(?:documento|folha não disponível|página|gravação|capa|aviso|fl\.)"
    r"|#\s*helestron-texto)", re.I)
# "(fls. 6-8)" ou "(fl. 6)" no marcador de peça do e-SAJ (esaj.titulo_da_peca)
_RE_FOLHAS_NO_TITULO = re.compile(r"\(fls?\. (\d+)(?:-(\d+))?\)")
_RE_TITULO_EVENTO = re.compile(r"^Evento (\d+)(?: — (.*))?$")
_RE_DATA_FINAL = re.compile(r"\s*\(\d{2}/\d{2}/\d{4}\)$")
_RE_PARTE_COMPLETO = re.compile(r"— parte (\d+)\s*$")
# O carimbo que o e-SAJ põe em toda folha da Pasta Digital ("Este documento é
# cópia do original, assinado digitalmente por ... Para conferir o original,
# acesse o site ..., informe o processo ... e código ...") e o número da folha
# numa linha só ("fls. 12"): são texto até na folha digitalizada sem OCR, que
# por isso parecia ter texto - e a IA não sabia que precisava ver a imagem.
_RE_CARIMBO_ESAJ = re.compile(
    r"(?:Este documento [ée] c[óo]pia do original|Para conferir o original)"
    r".{0,700}?c[óo]digo\s+[\w-]+\.?", re.I | re.S)
_RE_FOLHA_SOZINHA = re.compile(r"^\s*fls?\.\s*\d{1,7}\s*$", re.I)
# Menos que isto de letras e algarismos além do carimbo: a página não tem texto
MIN_CARACTERES_TEXTO = 12
_RE_SEM_TEXTO = re.compile(r"^" + re.escape(PREFIXO_SEM_TEXTO), re.M)
# "evento 4, PET1, p. 2", "arquivo completo do eProc, pág. 3", "pág. 5 do PDF"
_RE_CITACAO_NUMERADA = re.compile(r"^(?P<base>.*?)(?P<p>\bp\.|\bpág\.) (?P<n>\d+)"
                                  r"(?P<fim> do PDF)?$")

MAX_LINHAS_LISTA = 40          # partes, eventos sem documento... no cabeçalho


def _pymupdf():
    """O PyMuPDF pelo nome novo; 'fitz' imprime aviso de obsoleto."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - versões antigas
        import fitz as pymupdf
    return pymupdf


# ------------------------------------------------------------ montagem
@dataclass
class _Pagina:
    marca: str
    linhas: list[str] = field(default_factory=list)   # abaixo da marca
    corpo: bool = True                                # o texto da página entra?


@dataclass
class _Plano:
    sistema: str
    paginacao: str
    linhas: list[str]                 # cabeçalho entre colchetes
    paginas: list[_Pagina]
    ausentes: set[int] = field(default_factory=set)   # páginas do PDF
    grau: str = GRAU_1                                # dos autos: "1g" ou "2g"


def _limpo(texto, limite: int = 200) -> str:
    """Texto numa linha, sem colchetes (que fechariam a marca)."""
    t = " ".join(str(texto or "").split())
    t = t.replace("[", "(").replace("]", ")").replace("===", "=")
    return t[:limite].rstrip()


def _documento_por_pagina(sumario, paginas: int) -> dict[int, str]:
    """{página: título do marcador que a cobre}, a partir do sumário do PDF."""
    inicios = []
    for item in sumario or []:
        try:
            if len(item) >= 3 and int(item[2]) >= 1 and str(item[1]).strip():
                inicios.append((int(item[2]), str(item[1]).strip()))
        except (TypeError, ValueError):
            continue
    inicios.sort(key=lambda x: x[0])
    saida: dict[int, str] = {}
    for k, (inicio, titulo) in enumerate(inicios):
        fim = inicios[k + 1][0] - 1 if k + 1 < len(inicios) else paginas
        for n in range(inicio, min(paginas, max(inicio, fim)) + 1):
            saida[n] = titulo
    return saida


def _secoes(sumario, paginas: int) -> list[tuple[int, int, str]]:
    """[(início, fim, título)] dos marcadores de 1º nível, em ordem de página."""
    inicios = []
    for item in sumario or []:
        try:
            if len(item) >= 3 and int(item[0]) == 1 and 1 <= int(item[2]) <= paginas:
                inicios.append((int(item[2]), str(item[1]).strip()))
        except (TypeError, ValueError):
            continue
    inicios.sort(key=lambda x: x[0])
    saida = []
    for k, (inicio, titulo) in enumerate(inicios):
        fim = inicios[k + 1][0] - 1 if k + 1 < len(inicios) else paginas
        if fim >= inicio:
            saida.append((inicio, fim, titulo))
    return saida


def _cabeca(sistema: str, pag: str, n: int, ausentes, grau: str = GRAU_1) -> str:
    # O grau só vai no 2º grau, no fim: o texto do 1º grau é o de sempre (nada a
    # reextrair nem a reenviar à nuvem), e quem lê só o começo da linha não muda.
    return (f"{CABECA} | sistema={sistema} | paginacao={pag} | paginas={n} | "
            f"ausentes={paginacao.descrever_folhas(ausentes)}"
            + (f" | grau={GRAU_2}" if grau == GRAU_2 else ""))


def grau_dos_autos(manifesto: dict | None, nome="") -> str:
    """O grau dos autos de um PDF: "2g" ou "1g". Pelo manifesto de paginação
    (paginacao.grau: sem o campo, 1º grau) e, sem manifesto (PDF de versão
    anterior ou de outra origem), pelo nome do arquivo (cnj.grau_do_nome: o
    " (2G)" depois do número). Nome sem número: 1º grau."""
    if paginacao.valido(manifesto):
        return paginacao.grau(manifesto)
    try:
        return cnj.grau_do_nome(Path(str(nome or "")).name) if nome else GRAU_1
    except cnj.NumeroInvalido:
        return GRAU_1


def _no_grau(grau: str) -> str:
    """", 2º grau" no 2º grau (o fim de "autos do e-SAJ do TJAL"); "" no 1º."""
    return ", 2º grau" if grau == GRAU_2 else ""


def _do_tribunal(m: dict) -> str:
    t = _limpo(m.get("tribunal"), 30)
    return f" do {t}" if t else ""


def _processo(m: dict) -> str:
    p = _limpo(m.get("processo"), 40)
    return f"Processo {p} — " if p else ""


COMO_CITAR_ESAJ = (
    "[Como citar: \"fl. N\", pela marca [fl. N] que abre cada página. A folha marcada "
    "[folha não disponível no e-SAJ: …] não veio do e-SAJ (há só uma página de aviso no "
    "lugar): não a use como prova; diga que a folha não está disponível. Se a folha "
    "carimbada na própria página divergir da marca, cite a carimbada e avise o magistrado.]")
COMO_CITAR_EPROC = (
    "[Como citar: copie a marca da página — \"evento N, RÓTULO, p. Y\" (a página Y é a do "
    "próprio documento, igual à do eProc); marca sem \"p.\" é texto do próprio eProc "
    "(despacho, decisão, certidão), citado \"evento N, RÓTULO\". \"(pág. M do PDF)\" é só a "
    "posição no arquivo, para navegar: nunca a cite. Página marcada NÃO INCLUÍDO, "
    "gravação ou capa gerada pelo Helestron não é página dos autos.]")
COMO_CITAR_NAO_GARANTIDA = (
    "[Como citar: \"pág. M do PDF\" é só a posição no arquivo, para navegar: nunca a cite "
    "como folha. Cite a folha carimbada na própria página, se houver; senão, o documento "
    "(linha [documento: …]). Para a numeração exata, baixe o processo de novo pelo "
    "Helestron 1.0.2 ou mais novo.]")
# O PDF do eProc cujo manifesto não descreve o arquivo: a regra do eProc vale
# (nunca "fl."), inclusive para o carimbo "fls. N" que o documento migrado de
# outro sistema (o e-SAJ, no TJAL) traz na página.
COMO_CITAR_EPROC_NAO_GARANTIDA = (
    "[Como citar: o eProc não numera folhas: nunca cite \"fl.\", nem o carimbo \"fls. N\" que "
    "um documento vindo de outro sistema traga na página. \"pág. M do PDF\" é só a posição no "
    "arquivo, para navegar: nunca a cite. Cite o evento e o documento que a linha "
    "[documento: …] (ou a própria página) indicar, como \"evento N, RÓTULO\", sem a página, e "
    "avise o magistrado de que a página não pôde ser conferida; para a página exata, baixe o "
    "processo de novo.]")

# Os autos do 2º grau. No e-SAJ, a regra do carimbo é a OPOSTA da do 1º grau, de
# propósito: no 1º grau, o carimbo de outro processo traz outro número, e a
# folha carimbada que diverge da marca é citada; no 2º grau, a apelação e o RESE
# têm o MESMO número dos autos de origem, e a peça do 1º grau trazida à Pasta
# Digital do 2º grau com o carimbo "fls. 120" da origem, numa página marcada
# [fl. 735], não se distingue pelo número - "cite a carimbada" levaria a IA a
# citar a fl. 120 como folha do 2º grau.
COMO_CITAR_ESAJ_2G = (
    "[Como citar: \"fl. N\", pela marca [fl. N] que abre cada página: é a folha da Pasta "
    "Digital do 2º grau. Os autos de origem (1º grau), se estiverem no acervo, são outro "
    "arquivo, sem \"(2G)\" no nome e com folhas próprias: nunca presuma que a fl. N de um é a "
    "fl. N do outro e, ao citar folha deles, diga \"fl. N dos autos de origem\". A folha marcada "
    "[folha não disponível no e-SAJ: …] não veio do e-SAJ: não a use como prova. A marca [fl. N] "
    "é a folha destes autos. Carimbo \"fls.\" diferente na página é de outros autos, inclusive "
    "dos autos de origem, que têm o mesmo número: nunca o cite como folha destes autos; cite a "
    "marca e avise o magistrado do carimbo divergente (se precisar dele, \"fl. X dos autos de "
    "origem\").]")
# O eProc do 2º grau: os eventos do PDF são os do processo no 2º grau
EVENTOS_DO_2G = (
    "Os eventos são os do processo no 2º grau; evento do processo de origem (1º grau) não está "
    "neste PDF: cite-o como \"evento N, RÓTULO, do processo de origem\".")
COMO_CITAR_EPROC_2G = COMO_CITAR_EPROC[:-1] + " " + EVENTOS_DO_2G + "]"
COMO_CITAR_EPROC_NAO_GARANTIDA_2G = (COMO_CITAR_EPROC_NAO_GARANTIDA[:-1] + " " + EVENTOS_DO_2G
                                     + "]")
# Autos do 2º grau sem a paginação garantida (sem manifesto, ou alterados depois
# do download): a "folha carimbada" de COMO_CITAR_NAO_GARANTIDA pode ser a dos
# autos de origem, que têm o mesmo número - não se manda citá-la.
COMO_CITAR_NAO_GARANTIDA_2G = (
    "[Como citar: \"pág. M do PDF\" é só a posição no arquivo, para navegar: nunca a cite "
    "como folha. Nos autos do 2º grau, o carimbo \"fls.\" na página pode ser dos autos de "
    "origem (1º grau), que têm o mesmo número e são outro arquivo, sem \"(2G)\" no nome: não o "
    "cite como folha destes autos; cite o documento (linha [documento: …]) e avise o "
    "magistrado. Para a numeração exata, baixe o processo de novo.]")


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def manifesto_confere(m: dict | None, n: int) -> bool:
    """O manifesto de paginação descreve este PDF de 'n' páginas? No e-SAJ, a
    última folha tem de ser a última página; no eProc, a última página que os
    documentos (ou, no modo completo, as partes do arquivo) ocupam. Página
    incluída ou apagada depois do download (num editor que conserva os
    anexos) faz o manifesto descrever outro arquivo.

    É a conferência que decide se o texto sai com a paginação do manifesto
    ou "nao_garantida"; o índice, o conector e o JSON (preparar --pasta,
    baixar) a usam para dizer o mesmo que o texto. Sem manifesto: False."""
    if not paginacao.valido(m):
        return False
    if m.get("paginacao") == paginacao.FOLHAS:
        try:
            return int(m.get("ultima") or 0) == n
        except (TypeError, ValueError):
            return False
    fim = _fim_eproc(m)
    return not fim or fim == n


def _divergencia(m: dict, n: int) -> str:
    """'o manifesto de paginação diz 3 folhas, mas o PDF tem 4 páginas'."""
    if m.get("paginacao") == paginacao.FOLHAS:
        try:
            ultima = int(m.get("ultima") or 0)
        except (TypeError, ValueError):
            ultima = 0
        return (f"o manifesto de paginação diz {_plural(ultima, 'folha', 'folhas')}, mas o PDF "
                f"tem {_plural(n, 'página', 'páginas')}")
    return (f"o manifesto de paginação descreve {_plural(_fim_eproc(m), 'página', 'páginas')}, "
            f"mas o PDF tem {n}")


def resumo_da_paginacao(m: dict | None, n: int) -> str:
    """A frase do índice, do conector e do JSON sobre a paginação de um PDF
    de 'n' páginas - a mesma que o texto dele dá: a do manifesto
    (paginacao.resumo), se ele descreve o arquivo; a de paginação não
    garantida, se não descreve (alterado depois do download); a de PDF de
    versão anterior, sem manifesto."""
    if not paginacao.valido(m):
        return paginacao.resumo(None)
    if manifesto_confere(m, n):
        return paginacao.resumo(m)
    if m.get("paginacao") == paginacao.FOLHAS:
        efeito = "a página do PDF pode não ser a folha"
    else:
        efeito = ("o evento, o documento e a página do eProc de cada página do PDF não são "
                  "garantidos")
    return (f"NÃO garantida: {_divergencia(m, n)} (o arquivo foi alterado depois do "
            f"download?): {efeito}; baixe o processo de novo")


def _plano_esaj(m: dict, n: int, toc, grau: str = GRAU_1) -> _Plano:
    ultima = int(m.get("ultima") or 0)
    aus = paginacao.ausentes(m)
    docs = _documento_por_pagina(toc, n)
    if not manifesto_confere(m, n):
        # O manifesto não descreve este arquivo (alterado depois?): não há
        # como garantir que a página é a folha.
        log.warning("manifesto do e-SAJ diz %d folhas, mas o PDF tem %d páginas", ultima, n)
        plano = _plano_sem_garantia(toc, n, ESAJ, grau=grau)
        plano.linhas.insert(0, f"[{_processo(m)}autos do e-SAJ{_do_tribunal(m)}{_no_grau(grau)}: "
                               f"{_divergencia(m, n)} (o arquivo foi alterado depois do "
                               "download?): a página do PDF NÃO é garantidamente a folha.]")
        return plano
    if grau == GRAU_2:
        linhas = [f"[{_processo(m)}autos do e-SAJ{_do_tribunal(m)}, 2º grau (Pasta Digital do "
                  "processo no Tribunal). A página N deste PDF é sempre a folha N destes autos "
                  f"(fls. 1 a {ultima}).]", COMO_CITAR_ESAJ_2G]
    else:
        linhas = [f"[{_processo(m)}autos do e-SAJ{_do_tribunal(m)}. A página N deste PDF é "
                  f"sempre a folha N dos autos (fls. 1 a {ultima}).]", COMO_CITAR_ESAJ]
    if aus:
        por_motivo: dict[str, list[int]] = {}
        for f, c in aus.items():
            por_motivo.setdefault(c, []).append(f)
        partes = [f"{paginacao.descrever_folhas(fs)} ({paginacao.MOTIVOS.get(c, c)})"
                  for c, fs in sorted(por_motivo.items(),
                                      key=lambda x: paginacao.ORDEM_MOTIVOS.find(x[0]))]
        linhas.append("[Folhas com página de aviso no lugar: " + "; ".join(partes) + ".]")
    notas = [_limpo(x, 300) for x in (m.get("notas") or []) if str(x).strip()][:10]
    if notas:
        linhas.append("[Observações do download: " + "; ".join(notas) + ".]")
    paginas = []
    for i in range(1, n + 1):
        p = _Pagina(MARCA_PAGINA.format(n=i))
        if i in aus:
            p.linhas.append(MARCA_AUSENTE.format(
                motivo=paginacao.MOTIVOS.get(aus[i], paginacao.MOTIVOS["N"])))
            p.corpo = False
        if docs.get(i):
            p.linhas.append(MARCA_DOCUMENTO.format(titulo=_limpo(docs[i], 300)))
        paginas.append(p)
    return _Plano(ESAJ, FOLHAS, linhas, paginas, set(aus), grau)


def _citacao_evento(d: dict) -> str:
    rotulo = _limpo(d.get("rotulo") or "documento", 40).replace(",", " ")
    ev = d.get("evento")
    return f"evento {_limpo(ev, 10)}, {rotulo}" if ev not in (None, "") else rotulo


def _titulo_documento(d: dict) -> str:
    partes = [f"Evento {_limpo(d.get('evento'), 10)}" if d.get("evento") not in (None, "")
              else "Evento"]
    desc = _limpo(d.get("descricao"), 120)
    if desc:
        partes.append(desc)
    partes.append(_limpo(d.get("rotulo") or "documento", 40))
    titulo = " — ".join(partes)
    data = _limpo(d.get("data"), 20)
    return f"{titulo} ({data})" if data else titulo


def _texto_capa(m: dict) -> list[str]:
    """As linhas da capa e dos eventos sem documento, do manifesto do eProc."""
    linhas = []
    capa = m.get("capa") if isinstance(m.get("capa"), dict) else {}
    rotulos = {"classe": "Classe", "orgao": "Órgão julgador", "magistrado": "Magistrado",
               "assunto": "Assunto", "assuntos": "Assuntos", "valor": "Valor da causa",
               "autuacao": "Autuação", "situacao": "Situação", "competencia": "Competência"}
    itens = [f"{rotulos.get(str(k), str(k).replace('_', ' ').capitalize())}: {_limpo(v, 200)}"
             for k, v in capa.items()
             if str(k) != "partes" and isinstance(v, (str, int, float)) and _limpo(v)]
    # As partes do processo: na raiz do manifesto ("partes", lista de textos;
    # no modo "completo" essa chave é a das partes do arquivo, dicionários) e
    # na capa ("capa": {"partes": [...]}) - as duas, sem repetir.
    partes = list(dict.fromkeys(
        t for t in (_limpo(x, 160) for x in _textos_da_lista(m.get("partes"))
                    + _textos_da_lista(capa.get("partes"))) if t))
    if partes:
        nomes = partes[:MAX_LINHAS_LISTA]
        if len(partes) > MAX_LINHAS_LISTA:
            nomes.append(f"e mais {len(partes) - MAX_LINHAS_LISTA}")
        itens.append("Partes: " + "; ".join(nomes))
    if itens:
        linhas.append("[Capa (dados do eProc; não é página dos autos): " + "; ".join(itens) + ".]")
    sem_doc = [e for e in (m.get("eventos_sem_documento") or []) if isinstance(e, dict)]
    if sem_doc:
        descr = []
        for e in sem_doc[:MAX_LINHAS_LISTA * 2]:
            t = f"{_limpo(e.get('evento'), 10)} — {_limpo(e.get('descricao'), 120)}"
            if _limpo(e.get("data")):
                t += f" ({_limpo(e.get('data'), 20)})"
            descr.append(t)
        if len(sem_doc) > MAX_LINHAS_LISTA * 2:
            descr.append(f"e mais {len(sem_doc) - MAX_LINHAS_LISTA * 2}")
        linhas.append("[Eventos sem documento (não têm página no PDF): " + "; ".join(descr) + ".]")
    nao_listados = _limpo(m.get("eventos_nao_listados"), 80)
    if nao_listados:
        linhas.append(f"[Eventos que o portal não listou: {nao_listados} (confira no eProc).]")
    return linhas


def _textos_da_lista(valor) -> list[str]:
    """Os textos de uma lista do manifesto (um texto solto vale como lista de
    um); item que é dicionário ("polo", "nome"...) vira os valores, juntos.
    O dicionário de uma parte do arquivo completo ("inicio", "paginas") não
    é parte do processo e fica de fora."""
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, (list, tuple)):
        return []
    saida = []
    for x in valor:
        if isinstance(x, str):
            texto = x
        elif isinstance(x, dict) and not ({"inicio", "paginas"} & set(x)):
            texto = ": ".join(str(v) for v in x.values() if isinstance(v, str) and v.strip())
        else:
            continue
        if texto.strip():
            saida.append(texto)
    return saida


def _fim_eproc(m: dict) -> int:
    """A última página do PDF que o manifesto do eProc descreve (pelos
    documentos ou, no modo completo, pelas partes do arquivo); 0 se nenhum
    diz."""
    fins = []
    for chave in ("documentos", "partes"):
        itens = m.get(chave)
        for x in itens if isinstance(itens, list) else []:
            if not isinstance(x, dict):
                continue
            try:
                inicio, qtd = int(x.get("inicio") or 0), int(x.get("paginas") or 0)
            except (TypeError, ValueError):
                continue
            if qtd > 0:
                fins.append(inicio + qtd - 1)
    return max(fins, default=0)


def _plano_eproc(m: dict, n: int, toc, grau: str = GRAU_1) -> _Plano:
    segundo = grau == GRAU_2
    if not manifesto_confere(m, n):
        # Como no e-SAJ: o manifesto não descreve este arquivo (página apagada
        # ou incluída depois do download, num editor que conserva os anexos),
        # e cada marca citaria outra página, sem aviso nenhum. A instrução de
        # citação é a do eProc (nunca "fl."), e não a do e-SAJ.
        log.warning("manifesto do eProc descreve %d páginas, mas o PDF tem %d", _fim_eproc(m), n)
        plano = _plano_sem_garantia(toc, n, EPROC)
        plano.grau = grau
        plano.linhas = [f"[{_processo(m)}autos do eProc{_do_tribunal(m)}{_no_grau(grau)}: "
                        f"{_divergencia(m, n)} (o arquivo foi alterado depois do download?): o "
                        "evento, o documento e a página do eProc de cada página do PDF NÃO são "
                        "garantidos.]",
                        COMO_CITAR_EPROC_NAO_GARANTIDA_2G if segundo
                        else COMO_CITAR_EPROC_NAO_GARANTIDA] + _texto_capa(m)
        return plano
    if str(m.get("modo") or "") == "completo":
        return _plano_eproc_completo(m, n, toc, grau)
    linhas = [f"[{_processo(m)}autos do eProc{_do_tribunal(m)}{_no_grau(grau)}, documento a "
              "documento, na ordem dos eventos. O eProc não numera folhas: cada documento "
              "conserva a paginação própria, igual à do eProc, e nenhuma página foi inserida "
              "antes ou entre eles (só uma página de aviso no lugar de documento que não veio).]",
              COMO_CITAR_EPROC_2G if segundo else COMO_CITAR_EPROC]
    linhas += _texto_capa(m)
    mapa: dict[int, tuple[dict, int]] = {}
    fora, gravacoes = [], []
    for d in m.get("documentos") or []:
        if not isinstance(d, dict):
            continue
        try:
            inicio, qtd = int(d.get("inicio") or 0), int(d.get("paginas") or 0)
        except (TypeError, ValueError):
            continue
        for y in range(1, qtd + 1):
            if 1 <= inicio + y - 1 <= n:
                mapa.setdefault(inicio + y - 1, (d, y))
        situacao = str(d.get("situacao") or "ok")
        if situacao == "ausente":
            motivo = _limpo(d.get("motivo"), 160)
            fora.append(_citacao_evento(d) + (f" ({motivo})" if motivo else ""))
        elif situacao == "midia":
            gravacoes.append(_citacao_evento(d))
    if fora or gravacoes:
        t = []
        if fora:
            t.append("Documentos não incluídos no PDF: " + "; ".join(fora[:MAX_LINHAS_LISTA]))
        if gravacoes:
            t.append("Gravações fora do PDF: " + "; ".join(gravacoes[:MAX_LINHAS_LISTA]))
        linhas.append("[" + ". ".join(t) + ".]")
    paginas, ausentes = [], set()
    for i in range(1, n + 1):
        if i not in mapa:
            paginas.append(_Pagina(MARCA.format(citacao=f"pág. {i} do PDF")))
            continue
        d, y = mapa[i]
        base = _citacao_evento(d)
        situacao = str(d.get("situacao") or "ok")
        origem = str(d.get("origem") or "pdf")
        p = _Pagina("")
        if situacao == "ausente":
            cit = f"{base} — {NAO_INCLUIDO}"
            motivo = _limpo(d.get("motivo"), 200)
            p.linhas.append("[documento não incluído no PDF" + (f": {motivo}" if motivo else "")
                            + "; esta é uma página de aviso do Helestron, não é página dos autos]")
            p.corpo = False
            ausentes.add(i)
        elif situacao == "midia":
            cit = f"{base} — {GRAVACAO}"
            arquivo = _limpo(d.get("arquivo"), 200)
            p.linhas.append("[gravação de áudio ou vídeo, que não cabe no PDF"
                            + (f" (salva em {arquivo})" if arquivo else "")
                            + "; esta é uma página de aviso do Helestron, não é página dos autos]")
            p.corpo = False
            ausentes.add(i)
        elif origem in ("html", "texto"):
            cit = base
        else:
            cit = f"{base}, p. {y}"
        p.marca = MARCA_COM_PAGINA.format(citacao=cit, m=i)
        p.linhas.append(MARCA_DOCUMENTO.format(titulo=_titulo_documento(d)))
        paginas.append(p)
    return _Plano(EPROC, DOCUMENTO, linhas, paginas, ausentes, grau)


def _plano_eproc_completo(m: dict, n: int, toc, grau: str = GRAU_1) -> _Plano:
    partes = []
    for p in m.get("partes") or []:
        if isinstance(p, dict):
            try:
                partes.append((int(p.get("inicio") or 0), int(p.get("paginas") or 0)))
            except (TypeError, ValueError):
                continue
    partes = sorted(x for x in partes if x[0] >= 1 and x[1] >= 1) or [(1, n)]
    como_citar = ("[Como citar: o evento e o documento que a própria página ou a linha "
                  "[documento: …] indicarem; sem eles, a marca da página (\"arquivo completo do "
                  "eProc, pág. M\"). \"(pág. M do PDF)\" é só a posição no arquivo: nunca a cite.]")
    if grau == GRAU_2:
        como_citar = como_citar[:-1] + " " + EVENTOS_DO_2G + "]"
    linhas = [f"[{_processo(m)}arquivo completo gerado pelo próprio eProc{_do_tribunal(m)}"
              f"{_no_grau(grau)} (“Download Completo”), sem nenhuma página acrescentada"
              + (": a página M deste PDF é a página M desse arquivo.]" if len(partes) == 1
                 else f", em {len(partes)} partes (cada uma recomeça na página 1).]"),
              como_citar]
    linhas += _texto_capa(m)
    docs = _documento_por_pagina(toc, n)
    paginas = []
    for i in range(1, n + 1):
        j = next((k for k, (ini, qtd) in enumerate(partes, 1) if ini <= i < ini + qtd), None)
        if j is None:
            p = _Pagina(MARCA.format(citacao=f"pág. {i} do PDF"))
        elif len(partes) == 1 and partes[0][0] == 1:
            p = _Pagina(MARCA.format(citacao=f"arquivo completo do eProc, pág. {i}"))
        else:
            ini = partes[j - 1][0]
            cit = (f"arquivo completo do eProc, pág. {i - ini + 1}" if len(partes) == 1
                   else f"arquivo completo do eProc, parte {j}, pág. {i - ini + 1}")
            p = _Pagina(MARCA_COM_PAGINA.format(citacao=cit, m=i))
        if docs.get(i):
            p.linhas.append(MARCA_DOCUMENTO.format(titulo=_limpo(docs[i], 300)))
        paginas.append(p)
    return _Plano(EPROC, DOCUMENTO, linhas, paginas, grau=grau)


def _plano_sem_garantia(toc, n: int, sistema: str = DESCONHECIDO,
                        avisos: dict[int, str] | None = None, grau: str = GRAU_1) -> _Plano:
    docs = _documento_por_pagina(toc, n)
    avisos = avisos or {}
    paginas = []
    for i in range(1, n + 1):
        p = _Pagina(MARCA.format(citacao=f"pág. {i} do PDF"))
        if i in avisos:
            p.linhas.append(avisos[i])
            p.corpo = False
        if docs.get(i):
            p.linhas.append(MARCA_DOCUMENTO.format(titulo=_limpo(docs[i], 300)))
        paginas.append(p)
    # No 2º grau, a "folha carimbada" pode ser a dos autos de origem (o mesmo
    # número). (O eProc sem garantia troca estas linhas pelas dele: _plano_eproc.)
    linhas = [COMO_CITAR_NAO_GARANTIDA_2G if grau == GRAU_2 else COMO_CITAR_NAO_GARANTIDA]
    return _Plano(sistema, NAO_GARANTIDA, linhas, paginas, set(avisos), grau)


def _avisos_antigos_esaj(secoes) -> dict[int, str]:
    """Páginas "Documento não incluído" (uma por peça que não veio) do PDF
    peça a peça da 1.0.1."""
    return {ini: ("[página de aviso do Helestron no lugar de uma peça que não pôde ser "
                  "baixada do e-SAJ; não é página dos autos]")
            for ini, fim, titulo in secoes
            if titulo == TITULO_AVISO_ANTIGO and fim == ini}


def _plano_esaj_antigo(toc, n: int, grau: str = GRAU_1) -> _Plano:
    """PDF do e-SAJ da 1.0.1 (sem manifesto): a página é a folha só se cada
    peça começar na página da sua primeira folha e o PDF terminar na última."""
    secoes = _secoes(toc, n)
    faixas = []
    for ini, _fim, titulo in secoes:
        achado = _RE_FOLHAS_NO_TITULO.search(titulo)
        if achado:
            a = int(achado.group(1))
            faixas.append((ini, a, int(achado.group(2) or a)))
    alinhado = bool(faixas) and all(ini == a for ini, a, _b in faixas) \
        and max(b for _i, _a, b in faixas) == n
    avisos = _avisos_antigos_esaj(secoes)
    if not alinhado:
        plano = _plano_sem_garantia(toc, n, ESAJ, avisos, grau)
        plano.linhas.insert(0, "[Autos do e-SAJ baixados por versão anterior à 1.0.2, sem o "
                               "manifesto de paginação, e com as peças fora da página das suas "
                               "folhas (faltam folhas no arquivo, ou uma peça veio com outro "
                               "número de páginas): a página do PDF NÃO é a folha dos autos.]")
        return plano
    docs = _documento_por_pagina(toc, n)
    paginas = []
    for i in range(1, n + 1):
        p = _Pagina(MARCA_PAGINA.format(n=i))
        if i in avisos:
            p.linhas.append(MARCA_AUSENTE.format(motivo=paginacao.MOTIVOS["B"]))
            p.corpo = False
        if docs.get(i):
            p.linhas.append(MARCA_DOCUMENTO.format(titulo=_limpo(docs[i], 300)))
        paginas.append(p)
    linhas = ["[Autos do e-SAJ baixados por versão anterior à 1.0.2, sem o manifesto de "
              "paginação: a numeração foi conferida pelos marcadores das peças (cada peça "
              f"começa na página da sua primeira folha, e o PDF termina na fl. {n}). A página "
              "N deste PDF é a folha N dos autos.]",
              COMO_CITAR_ESAJ_2G if grau == GRAU_2 else COMO_CITAR_ESAJ]
    return _Plano(ESAJ, FOLHAS, linhas, paginas, set(avisos), grau)


def _rotulo_do_titulo(resto: str) -> str:
    """'PETIÇÃO INICIAL — INIC1 (03/02/2025)' -> 'INIC1'."""
    resto = _RE_DATA_FINAL.sub("", resto or "").strip()
    return resto.split(" — ")[-1].strip() if resto else ""


def _plano_eproc_antigo(toc, n: int, textos_paginas: list[str], grau: str = GRAU_1) -> _Plano:
    """PDF do eProc da 1.0.1: capa do programa no início, depois os
    documentos (ou o arquivo completo), um marcador por documento."""
    secoes = _secoes(toc, n)
    docs = _documento_por_pagina(toc, n)
    paginas: list[_Pagina | None] = [None] * (n + 1)
    ausentes: set[int] = set()
    completos = [s for s in secoes if s[2].startswith(TITULO_COMPLETO_ANTIGO)]
    for ini, fim, titulo in secoes:
        if titulo == TITULO_CAPA_ANTIGA:
            for i in range(ini, fim + 1):
                paginas[i] = _Pagina(MARCA_COM_PAGINA.format(citacao=CITACAO_CAPA, m=i))
            continue
        if titulo.startswith(TITULO_COMPLETO_ANTIGO):
            achado = _RE_PARTE_COMPLETO.search(titulo)
            parte = f"parte {achado.group(1)}, " if achado and len(completos) > 1 else ""
            for i in range(ini, fim + 1):
                cit = f"arquivo completo do eProc, {parte}pág. {i - ini + 1}"
                paginas[i] = _Pagina(MARCA_COM_PAGINA.format(citacao=cit, m=i))
            continue
        achado = _RE_TITULO_EVENTO.match(titulo)
        if not achado:
            continue
        evento = achado.group(1)
        rotulo = _limpo(_rotulo_do_titulo(achado.group(2) or "") or "documento", 40)
        base = f"evento {evento}, {rotulo.replace(',', ' ')}"
        texto_unico = (" ".join(textos_paginas[ini - 1].split())
                       if fim == ini and ini - 1 < len(textos_paginas) else "")
        if texto_unico and _AVISO_MIDIA_ANTIGO.format(rotulo=rotulo, evento=evento) in texto_unico:
            paginas[ini] = _Pagina(MARCA_COM_PAGINA.format(citacao=f"{base} — {GRAVACAO}", m=ini),
                                   ["[gravação de áudio ou vídeo, que não cabe no PDF; esta é "
                                    "uma página de aviso do Helestron, não é página dos autos]"],
                                   corpo=False)
            ausentes.add(ini)
            continue
        if texto_unico and (_AVISO_FALHA_ANTIGO.format(rotulo=rotulo, evento=evento) in texto_unico
                            or (TITULO_AVISO_ANTIGO in texto_unico
                                and _AVISO_INCLUSAO_ANTIGO in texto_unico)):
            paginas[ini] = _Pagina(MARCA_COM_PAGINA.format(citacao=f"{base} — {NAO_INCLUIDO}",
                                                           m=ini),
                                   ["[documento não incluído no PDF; esta é uma página de aviso "
                                    "do Helestron, não é página dos autos]"], corpo=False)
            ausentes.add(ini)
            continue
        for i in range(ini, fim + 1):
            paginas[i] = _Pagina(MARCA_COM_PAGINA.format(citacao=f"{base}, p. {i - ini + 1}",
                                                         m=i))
    saida = []
    for i in range(1, n + 1):
        p = paginas[i] or _Pagina(MARCA.format(citacao=f"pág. {i} do PDF"))
        if docs.get(i):
            p.linhas.append(MARCA_DOCUMENTO.format(titulo=_limpo(docs[i], 300)))
        saida.append(p)
    linhas = ["[Autos do eProc baixados por versão anterior à 1.0.2, sem o manifesto de "
              "paginação: a 1ª página (ou as primeiras) é uma capa gerada pelo Helestron, que "
              "não é página dos autos. Nos documentos em PDF, \"p. Y\" é a página do documento "
              "no eProc; documento de texto do próprio eProc (despacho, decisão, certidão) "
              "pode ter vindo paginado pelo Helestron: cite-o sem a página. Para a paginação "
              "exata, baixe o processo de novo.]",
              COMO_CITAR_EPROC_2G if grau == GRAU_2 else COMO_CITAR_EPROC]
    return _Plano(EPROC, DOCUMENTO, linhas, saida, ausentes, grau)


def _planejar(manifesto: dict | None, toc, n: int, textos_paginas: list[str],
              grau: str = GRAU_1) -> _Plano:
    if manifesto and manifesto.get("paginacao") == paginacao.FOLHAS:
        return _plano_esaj(manifesto, n, toc, grau)
    if manifesto and manifesto.get("paginacao") == paginacao.DOCUMENTO:
        return _plano_eproc(manifesto, n, toc, grau)
    secoes = _secoes(toc, n)
    if secoes and secoes[0][0] == 1 and secoes[0][2] == TITULO_CAPA_ANTIGA:
        return _plano_eproc_antigo(toc, n, textos_paginas, grau)
    if any(_RE_FOLHAS_NO_TITULO.search(t) for _i, _f, t in secoes):
        return _plano_esaj_antigo(toc, n, grau)
    plano = _plano_sem_garantia(toc, n, grau=grau)
    plano.linhas.insert(0, "[PDF sem o manifesto de paginação do Helestron (baixado por "
                           "versão anterior à 1.0.2, ou de outra origem): a paginação não é "
                           "garantida, e a página do PDF pode não ser a folha dos autos.]")
    return plano


def _neutralizar(texto: str) -> str:
    """Linha do conteúdo que imita uma marca (ou uma linha do programa) ganha
    um "· " na frente: o documento não consegue forjar folha nem cabeçalho."""
    if "[" not in texto and "#" not in texto:
        return texto
    return "\n".join("· " + linha if _RE_RESERVADA.match(linha) else linha
                     for linha in texto.split("\n"))


def _aviso_sem_texto(corpo: str) -> str | None:
    """A linha "[página sem texto extraível …]" que a página pede, ou None se
    ela tem texto. No e-SAJ, o carimbo da Pasta Digital e o número da folha
    não contam como texto: a folha digitalizada sem OCR só tem isso."""
    if not corpo:
        return SEM_TEXTO
    if corpo == ILEGIVEL:
        return SEM_TEXTO_ILEGIVEL
    linhas = corpo.split("\n")
    sobra = [linha for linha in linhas if not _RE_FOLHA_SOZINHA.match(linha)]
    resto, carimbos = _RE_CARIMBO_ESAJ.subn(" ", " ".join(" ".join(sobra).split()))
    if len(sobra) == len(linhas) and not carimbos:
        return None             # sem carimbo: o texto que houver é da página
    if sum(1 for c in resto if c.isalnum()) < MIN_CARACTERES_TEXTO:
        return SEM_TEXTO_CARIMBO
    return None


def _montar(plano: _Plano, textos_paginas: list[str]) -> str:
    n = len(plano.paginas)
    saida = [_cabeca(plano.sistema, plano.paginacao, n, plano.ausentes, plano.grau)]
    saida += plano.linhas
    for i, p in enumerate(plano.paginas):
        saida.append(p.marca)
        saida += p.linhas
        if p.corpo:
            corpo = (textos_paginas[i] if i < len(textos_paginas) else "").strip()
            aviso = _aviso_sem_texto(corpo)
            if aviso:
                saida.append(aviso)
            if corpo and corpo != ILEGIVEL:
                saida.append(_neutralizar(corpo))
    return "\n".join(saida) + "\n"


def _ler_com_pymupdf(caminho: Path):
    fitz = _pymupdf()
    # Sem TEXT_PRESERVE_LIGATURES: "Certiﬁco" (ligadura) vira "Certifico",
    # e a busca da IA por "certifico" acha a palavra.
    flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP
    with fitz.open(str(caminho)) as doc:
        try:
            toc = doc.get_toc(simple=True)
        except Exception:  # sumário estragado não impede o texto
            toc = []
        manifesto = paginacao.ler_do_doc(doc)
        textos_paginas = []
        for pagina in doc:
            try:
                textos_paginas.append(pagina.get_text("text", flags=flags) or "")
            except Exception:  # página corrompida não derruba o resto
                textos_paginas.append(ILEGIVEL)
        return doc.page_count, toc, manifesto, textos_paginas


def _ler_com_pypdf(caminho: Path):  # pragma: no cover - só sem o PyMuPDF
    from pypdf import PdfReader

    leitor = PdfReader(str(caminho))
    textos_paginas = []
    for pagina in leitor.pages:
        try:
            textos_paginas.append(pagina.extract_text() or "")
        except Exception:
            textos_paginas.append(ILEGIVEL)
    return len(textos_paginas), [], paginacao.ler_do_pdf(caminho), textos_paginas


def texto_pdf(caminho: Path) -> str:
    """O texto do PDF no formato 2: cabeçalho e, por página, a marca de
    citação, o documento e o conteúdo. O grau dos autos é o do manifesto e,
    sem ele, o do nome do arquivo (grau_dos_autos)."""
    try:
        n, toc, manifesto, textos_paginas = _ler_com_pymupdf(Path(caminho))
    except ImportError:  # pragma: no cover - PyMuPDF faz parte da instalação
        n, toc, manifesto, textos_paginas = _ler_com_pypdf(Path(caminho))
    grau = grau_dos_autos(manifesto, Path(caminho).name)
    return _montar(_planejar(manifesto, toc, n, textos_paginas, grau), textos_paginas)


def texto_docx(caminho: Path) -> str:
    """Parágrafos e tabelas do .docx, na ordem do documento."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(caminho))
    linhas: list[str] = []
    corpo = doc.element.body
    for filho in corpo.iterchildren():
        tag = filho.tag.rsplit("}", 1)[-1]
        if tag == "p":
            linhas.append(Paragraph(filho, doc).text)
        elif tag == "tbl":
            for linha in Table(filho, doc).rows:
                celulas = [c.text.strip() for c in linha.cells]
                linhas.append(" | ".join(celulas))
    return "\n".join(linhas).strip() + "\n"


def texto_de(caminho: Path) -> str:
    caminho = Path(caminho)
    sufixo = caminho.suffix.lower()
    if sufixo == ".pdf":
        return texto_pdf(caminho)
    if sufixo == ".docx":
        return texto_docx(caminho)
    return caminho.read_text(encoding="utf-8", errors="replace")


def analisar(caminho: Path) -> tuple[str, dict]:
    """O texto de 'caminho' e o que se sabe dele, para quem automatiza.

    'caminho' é o PDF dos autos (o texto é extraído agora, no formato 2), o
    texto já extraído (.txt, lido como está) ou um .docx. A 'info' é a de
    info_do_texto: sistema, paginação, páginas, páginas de aviso e as páginas
    sem texto extraível - no e-SAJ, em folhas ("3, 7-9"); no eProc, pela
    citação ("evento 4, PET1, p. 1-2 (págs. 5-6 do PDF)").
    """
    texto = texto_de(Path(caminho))
    return texto, info_do_texto(texto)


def info_do_texto(texto: str) -> dict:
    """O que o texto (formato 2) diz de si: {"versao", "sistema",
    "paginacao", "paginas", "ausentes", "grau", "paginas_sem_texto",
    "paginas_sem_texto_pdf", "total_sem_texto"}. "grau": "2g" nos autos do
    2º grau, "1g" nos do 1º (e no texto sem o cabeçalho do formato 2).

    "paginas_sem_texto" cita as páginas sem texto extraível (imagem
    digitalizada sem OCR, só o carimbo do e-SAJ, página ilegível) como os
    autos as citam: no e-SAJ, as folhas em faixas ("3, 7-9", que são também
    as páginas do PDF); no eProc, por documento ("evento 4, PET1, p. 1-2
    (págs. 5-6 do PDF)"); sem paginação garantida, a posição no PDF ("págs.
    3-4 do PDF"). "paginas_sem_texto_pdf" traz sempre as páginas do PDF, em
    faixas. Vazios se não houver nenhuma. Texto sem o cabeçalho do formato 2
    (um .docx, o formato 1) dá sistema e paginação vazios."""
    cab = cabecalho(texto)
    lista = marcas(texto)
    inicios = [m.inicio for m in lista]
    vazias: list[Marca] = []
    for achado in _RE_SEM_TEXTO.finditer(texto):
        i = bisect.bisect_right(inicios, achado.start()) - 1
        if i >= 0 and (not vazias or vazias[-1] is not lista[i]):
            vazias.append(lista[i])
    pdf = sorted({m.pagina for m in vazias})
    pag = cab.get("paginacao", "")
    em_folhas = pag == FOLHAS or (not cab and bool(lista)
                                  and all(m.citacao.startswith("fl. ") for m in lista))
    if not vazias:
        citacao = ""
    elif em_folhas:
        citacao = paginacao.descrever_folhas(pdf)
    elif pag == DOCUMENTO:
        citacao = _citar_paginas(vazias)
    else:
        citacao = (f"{'pág.' if len(pdf) == 1 else 'págs.'} "
                   f"{paginacao.descrever_folhas(pdf)} do PDF")
    return {"versao": cab.get("versao", 0), "sistema": cab.get("sistema", ""),
            "paginacao": pag, "paginas": cab.get("paginas") or len(lista),
            "ausentes": cab.get("ausentes", ""), "grau": cab.get("grau", GRAU_1),
            "paginas_sem_texto": citacao,
            "paginas_sem_texto_pdf": paginacao.descrever_folhas(pdf),
            "total_sem_texto": len(pdf)}


def _citar_paginas(lista: list[Marca]) -> str:
    """As citações de páginas do eProc, com as seguidas do mesmo documento
    juntas: "evento 4, PET1, p. 1-3 (págs. 5-7 do PDF); evento 3, DESPADEC1
    (pág. 4 do PDF)"."""
    grupos: list[dict] = []
    for m in lista:
        achado = _RE_CITACAO_NUMERADA.match(m.citacao)
        if achado:
            chave = (achado.group("base"), achado.group("p"), achado.group("fim") or "")
            n = int(achado.group("n"))
        else:
            chave, n = (m.citacao, None, ""), None
        g = grupos[-1] if grupos else None
        if g and g["chave"] == chave and g["pdf_fim"] + 1 == m.pagina \
                and (n is None or g["n_fim"] + 1 == n):
            g["n_fim"], g["pdf_fim"] = n, m.pagina
            continue
        grupos.append({"chave": chave, "citacao": m.citacao, "explicita": m.explicita,
                       "n_ini": n, "n_fim": n, "pdf_ini": m.pagina, "pdf_fim": m.pagina})
    saida = []
    for g in grupos:
        base, p, fim = g["chave"]
        if p is None or g["n_ini"] == g["n_fim"]:
            t = g["citacao"]
        else:
            t = f"{base}{'págs.' if p == 'pág.' else p} {g['n_ini']}-{g['n_fim']}{fim}"
        if g["explicita"] and not t.startswith("pág"):
            t += (f" (pág. {g['pdf_ini']} do PDF)" if g["pdf_ini"] == g["pdf_fim"]
                  else f" (págs. {g['pdf_ini']}-{g['pdf_fim']} do PDF)")
        saida.append(t)
    return "; ".join(saida)


# ------------------------------------------------------------- gravação
def gravar_atomico(destino: Path, conteudo: str, quando: float | None = None) -> None:
    """Grava 'conteudo' em 'destino' por um temporário de nome ÚNICO e troca.

    Nome fixo ("destino.tmp") fazia dois preparos ao mesmo tempo (o fim do
    lote e o fim de uma transcrição, ou o servidor MCP noutro processo)
    trocarem o temporário um do outro: FileNotFoundError, ou, no Windows,
    PermissionError. O temporário termina em ".tmp": o espelho na nuvem e o
    acervo o ignoram. No Windows, a troca é tentada de novo por alguns
    instantes se o destino estiver aberto por outro programa.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, nome = tempfile.mkstemp(dir=str(destino.parent), prefix=destino.name + ".",
                                suffix=".tmp")
    tmp = Path(nome)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as arq:
            arq.write(conteudo)
        if quando is not None:
            try:
                os.utime(tmp, (quando, quando))
            except OSError:
                pass
        for tentativa in range(6):
            try:
                os.replace(tmp, destino)
                break
            except PermissionError:
                if tentativa == 5:
                    raise
                time.sleep(0.2 * (tentativa + 1))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def versao_do_texto(destino: Path) -> int:
    """A versão do formato de um texto já gravado (0: formato 1 ou ilegível)."""
    try:
        with open(destino, encoding="utf-8", errors="replace") as arq:
            linha = arq.readline(400)
    except OSError:
        return 0
    return VERSAO_TEXTO if linha.split(" |")[0].strip() == CABECA else 0


def garantir_texto(origem: Path, destino: Path) -> Path:
    """Extrai o texto de 'origem' para 'destino', se ainda não estiver em dia.

    O texto leva a data de modificação do próprio PDF, e só vale enquanto as
    duas coincidem. "Texto mais novo que o PDF" não basta: um texto tirado de
    OUTRO PDF (o mesmo processo noutro lote, que foi apagado) passaria por
    atual, e a IA leria autos que não são os do arquivo. Texto de PDF em
    formato anterior (1ª linha diferente de "# helestron-texto 2") é refeito:
    as marcas dele não dizem a paginação.
    """
    origem, destino = Path(origem), Path(destino)
    try:
        if destino.exists() and abs(destino.stat().st_mtime - origem.stat().st_mtime) <= 2 \
                and (origem.suffix.lower() != ".pdf" or versao_do_texto(destino) == VERSAO_TEXTO):
            return destino      # folga de 2 s: FAT/exFAT arredondam a data
    except OSError:
        pass
    texto = texto_de(origem)
    try:
        quando = origem.stat().st_mtime
    except OSError:
        quando = None
    gravar_atomico(destino, texto, quando)
    return destino


def contar_paginas(caminho: Path) -> int:
    try:
        fitz = _pymupdf()
        with fitz.open(str(caminho)) as doc:
            return doc.page_count
    except Exception:
        try:
            from pypdf import PdfReader

            return len(PdfReader(str(caminho)).pages)
        except Exception:
            return 0


def info_pdf(caminho: Path) -> tuple[int, dict | None]:
    """(páginas, manifesto de paginação ou None), abrindo o PDF uma vez só."""
    try:
        fitz = _pymupdf()
        with fitz.open(str(caminho)) as doc:
            return doc.page_count, paginacao.ler_do_doc(doc)
    except Exception:
        return contar_paginas(caminho), paginacao.ler_do_pdf(caminho)


# --------------------------------------------------------------- leitura
def sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if not unicodedata.combining(c)).casefold()


def cabecalho(texto: str) -> dict:
    """A 1ª linha do texto, lida: {'versao', 'sistema', 'paginacao',
    'paginas', 'ausentes', 'grau'} - 'grau' é "2g" nos autos do 2º grau e
    "1g" nos do 1º (a linha sem o campo). Vazio se o texto não for do
    formato 2."""
    primeira = texto.split("\n", 1)[0]
    pedacos = [p.strip() for p in primeira.split(" | ")]
    if not pedacos or pedacos[0] != CABECA:
        return {}
    saida: dict = {"versao": VERSAO_TEXTO}
    for p in pedacos[1:]:
        chave, _, valor = p.partition("=")
        saida[chave.strip()] = valor.strip()
    try:
        saida["paginas"] = int(saida.get("paginas") or 0)
    except ValueError:
        saida["paginas"] = 0
    saida.setdefault("ausentes", "")
    saida["grau"] = cnj.normalizar_grau(saida.get("grau")) or GRAU_1
    return saida


@dataclass
class Marca:
    inicio: int          # posição da marca no texto
    pagina: int          # página do PDF
    citacao: str         # o que vai entre os colchetes
    explicita: bool      # a marca traz "(pág. M do PDF)"

    @property
    def completa(self) -> str:
        """A citação com a posição no PDF, para quem lê a busca."""
        if self.explicita and not self.citacao.startswith("pág. "):
            return f"{self.citacao} (pág. {self.pagina} do PDF)"
        return self.citacao


def marcas(texto: str) -> list[Marca]:
    """As marcas de página do texto, em ordem (formato 1 ou 2)."""
    saida = []
    for k, m in enumerate(_RE_MARCA.finditer(texto), 1):
        cit = m.group("cit")
        if m.group("pag"):
            pagina = int(m.group("pag"))
        else:
            numeros = _RE_NUMERO_NA_CITACAO.findall(cit)
            pagina = int(numeros[-1]) if numeros else k
        saida.append(Marca(m.start(), pagina, cit, bool(m.group("pag"))))
    return saida


def preambulo(texto: str) -> str:
    """Tudo antes da primeira marca de página (o cabeçalho do formato 2)."""
    m = _RE_MARCA.search(texto)
    return texto[:m.start()] if m else ""


def recortar_paginas(texto: str, inicio: int, fim: int) -> str:
    """Só as páginas do PDF [inicio, fim] de um texto com marcas de página."""
    lista = marcas(texto)
    if not lista:
        return texto
    pedacos = []
    for i, m in enumerate(lista):
        if inicio <= m.pagina <= fim:
            ate = lista[i + 1].inicio if i + 1 < len(lista) else len(texto)
            pedacos.append(texto[m.inicio:ate])
    return "".join(pedacos)


def _marca_na_posicao(texto: str, posicao: int) -> Marca | None:
    achada = None
    for m in marcas(texto):
        if m.inicio > posicao:
            break
        achada = m
    return achada


def folha_na_posicao(texto: str, posicao: int) -> int:
    """Página do PDF (no e-SAJ, a folha) em que cai a posição do texto."""
    m = _marca_na_posicao(texto, posicao)
    return m.pagina if m else 0


def citacao_na_posicao(texto: str, posicao: int) -> str:
    """A citação da página em que cai a posição ("fl. 5", "evento 4, PET1,
    p. 1 (pág. 6 do PDF)"); vazio antes da primeira página."""
    m = _marca_na_posicao(texto, posicao)
    return m.completa if m else ""


def faixa_do_documento(texto: str, evento, rotulo: str | None = None) -> tuple[int, int] | None:
    """(primeira, última) página do PDF do documento 'rotulo' do evento (ou
    de todos os documentos do evento, sem 'rotulo'); None se não houver."""
    try:
        alvo = int(str(evento).strip())
    except (TypeError, ValueError):
        return None
    rot = (rotulo or "").strip().casefold()
    paginas = []
    for m in marcas(texto):
        achado = _RE_EVENTO_NA_CITACAO.match(m.citacao)
        if achado and int(achado.group("ev")) == alvo \
                and (not rot or achado.group("rot").strip().casefold() == rot):
            paginas.append(m.pagina)
    return (min(paginas), max(paginas)) if paginas else None


def eventos_do_rotulo(texto: str, rotulo: str) -> list[int]:
    """Os eventos que têm um documento com este rótulo ("PET1")."""
    rot = (rotulo or "").strip().casefold()
    vistos: list[int] = []
    for m in marcas(texto):
        achado = _RE_EVENTO_NA_CITACAO.match(m.citacao)
        if achado and achado.group("rot").strip().casefold() == rot:
            ev = int(achado.group("ev"))
            if ev not in vistos:
                vistos.append(ev)
    return vistos


def _sem_estrutura(texto: str) -> str:
    """O texto com o cabeçalho, as marcas e as linhas do programa apagadas
    (trocadas por espaços, para as posições continuarem as mesmas): a busca
    acha o que está nos autos, não as marcas."""
    lista = marcas(texto)
    if not lista:
        return texto
    partes = [" " * lista[0].inicio]
    pos = lista[0].inicio
    for linha in texto[pos:].split("\n"):
        if _RE_MARCA.match(linha) or (linha.startswith("[") and linha.endswith("]")
                                      and linha.startswith(("[documento", "[folha não disponível",
                                                            "[página", "[gravação"))):
            partes.append(" " * len(linha))
        else:
            partes.append(linha)
        partes.append("\n")
    saida = "".join(partes)[:len(texto)]
    return saida if len(saida) == len(texto) else texto


@functools.lru_cache(maxsize=8192)
def _base(c: str) -> str:
    """O caractere sem acento e em minúscula, SEMPRE com um caractere só (a
    posição no texto comparado tem de ser a mesma do original)."""
    base = "".join(x for x in unicodedata.normalize("NFKD", c)
                   if not unicodedata.combining(x)).casefold()
    if len(base) == 1:
        return base
    menor = c.lower()
    return menor if len(menor) == 1 else c


def _comparavel(texto: str) -> str:
    """Sem acento e em minúscula, com o mesmo comprimento do original."""
    return texto.translate({ord(c): _base(c) for c in set(texto)})


def _achados(texto: str, termo: str, contexto: int, limite: int):
    alvo = _comparavel(" ".join(termo.split()))
    if not alvo:
        return []
    plano = _comparavel(_sem_estrutura(texto))
    primeira = _RE_MARCA.search(texto)
    piso = primeira.start() if primeira else 0     # o trecho não mostra o cabeçalho
    achados = []
    inicio = 0
    while len(achados) < limite:
        pos = plano.find(alvo, inicio)
        if pos < 0:
            break
        a, b = max(piso, pos - contexto), min(len(texto), pos + len(alvo) + contexto)
        achados.append((pos, " ".join(texto[a:b].split())))
        inicio = pos + len(alvo)
    return achados


def buscar(texto: str, termo: str, contexto: int = 160, limite: int = 20):
    """Ocorrências de 'termo' (sem diferenciar acento e caixa).

    Devolve [(página do PDF, trecho)] - no e-SAJ, a página é a folha. A busca
    ignora acento comparando as versões sem acento, que têm o mesmo
    comprimento do original quando o texto vem em NFC (o caso do PyMuPDF e do
    python-docx). O cabeçalho e as marcas não entram na busca.
    """
    na_pagina = _localizador(texto)
    return [(m.pagina if m else 0, trecho)
            for pos, trecho in _achados(texto, termo, contexto, limite)
            for m in (na_pagina(pos),)]


def buscar_citando(texto: str, termo: str, contexto: int = 160, limite: int = 20):
    """Como buscar, mas devolve [(citação, trecho)]: "fl. 5", "evento 4, PET1,
    p. 1 (pág. 6 do PDF)", "pág. 3 do PDF"."""
    na_pagina = _localizador(texto)
    return [(m.completa if m else "sem página", trecho)
            for pos, trecho in _achados(texto, termo, contexto, limite)
            for m in (na_pagina(pos),)]


def _localizador(texto: str):
    """posição -> Marca da página em que ela cai (as marcas lidas uma vez)."""
    lista = marcas(texto)
    inicios = [m.inicio for m in lista]

    def na_pagina(posicao: int) -> Marca | None:
        i = bisect.bisect_right(inicios, posicao) - 1
        return lista[i] if i >= 0 else None

    return na_pagina
