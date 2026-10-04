"""A paginação dos autos baixados: o manifesto que vai dentro do PDF.

O PDF que o Helestron monta reproduz a numeração do próprio sistema do
tribunal, e diz isso dentro dele, num manifesto que acompanha o arquivo para
onde ele for (pasta do lote, pasta dos sigilosos, acervo):

* **e-SAJ** (``paginacao = "folhas"``): a página N do PDF é SEMPRE a folha N
  da Pasta Digital. A folha que não veio - a Pasta Digital não a ofereceu
  (peça sigilosa, de acesso restrito ou cancelada), a peça não pôde ser
  baixada, o arquivo veio inválido ou com páginas a menos - tem no lugar uma
  página de aviso ("Folha N — não disponibilizada pelo e-SAJ"), e o
  manifesto lista essas folhas com o motivo. ``ultima`` é a última folha
  oferecida: folhas depois dela, ocultas pela Pasta Digital, não aparecem em
  índice nenhum e não podem ser detectadas.
* **eProc** (``paginacao = "documento"``): o eProc não numera folhas; cada
  documento tem a paginação própria (cita-se "evento N, RÓTULO, p. Y"). O PDF
  traz os documentos na ordem dos eventos, sem páginas inseridas entre eles,
  e o manifesto diz onde cada um começa (``inicio``) e quantas páginas tem.

O manifesto vai como arquivo anexo do PDF (``helestron-paginacao.json``) e,
resumido, nas palavras-chave (/Keywords) - que qualquer leitor de PDF mostra.
PDF sem manifesto é de versão anterior à 1.0.2: a paginação dele não é
garantida (no e-SAJ, a página pode não ser a folha).

Este módulo não depende do download nem do compartilhamento: os dois o usam
(quem grava o PDF, quem extrai o texto, o servidor MCP, o motor que confere o
que já foi baixado).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

log = logging.getLogger("nucleo.paginacao")

NOME_ANEXO = "helestron-paginacao.json"
FORMATO = 1
PREFIXO_CHAVES = "helestron"

ESAJ, EPROC = "esaj", "eproc"
FOLHAS, DOCUMENTO = "folhas", "documento"

# Motivo de cada folha com página de aviso no lugar (e-SAJ). O código vai
# para o manifesto; o texto, para a página de aviso e para o texto dos autos.
MOTIVOS = {
    "N": "a Pasta Digital não ofereceu esta folha ao seu usuário "
         "(peça sigilosa, de acesso restrito ou cancelada)",
    "S": "a Pasta Digital listou uma peça sem numeração de folhas",
    "B": "a peça não pôde ser baixada do e-SAJ",
    "I": "o arquivo da peça veio inválido (não abre, protegido ou sem páginas)",
    "C": "o arquivo da peça veio com menos páginas do que as folhas que ela ocupa",
}
ORDEM_MOTIVOS = "NSBIC"

_RE_FAIXA = re.compile(r"^\s*(\d{1,7})\s*(?:-\s*(\d{1,7}))?\s*$")


# ------------------------------------------------------------- faixas
def faixas(folhas: Iterable[int]) -> list[tuple[int, int]]:
    """{6, 7, 8, 40} -> [(6, 8), (40, 40)]: ordenadas e unidas."""
    saida: list[list[int]] = []
    for f in sorted({int(x) for x in folhas if int(x) >= 1}):
        if saida and f == saida[-1][1] + 1:
            saida[-1][1] = f
        else:
            saida.append([f, f])
    return [(a, b) for a, b in saida]


def descrever_folhas(folhas: Iterable[int]) -> str:
    """{6, 7, 8, 40} -> "6-8, 40" (vazio se não houver)."""
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in faixas(folhas))


def ler_faixas(texto: str) -> set[int]:
    """"6-8, 40" -> {6, 7, 8, 40}. Pedaço que não é faixa é ignorado."""
    folhas: set[int] = set()
    for pedaco in str(texto or "").split(","):
        m = _RE_FAIXA.match(pedaco)
        if not m:
            continue
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a >= 1 and b >= a and b - a <= 200_000:
            folhas.update(range(a, b + 1))
    return folhas


# ----------------------------------------------------------- manifesto
def _programa() -> str:
    try:
        from .. import __version__
    except Exception:  # pragma: no cover - pacote sempre tem versão
        __version__ = "?"
    return f"Helestron {__version__}"


def manifesto_esaj(processo: str, ultima: int, ausentes: dict[int, str] | None = None,
                   origem: str = "", tribunal: str = "", notas: Iterable[str] = ()) -> dict:
    """Manifesto do PDF do e-SAJ: página N = folha N, de 1 a ``ultima``.

    ``ausentes``: folha -> código do motivo (MOTIVOS) das folhas que têm
    página de aviso no lugar. ``origem``: "servidor" (o PDF único da Pasta
    Digital) ou "peca_a_peca".
    """
    por_motivo: dict[str, list[int]] = {}
    for folha, codigo in sorted((ausentes or {}).items()):
        por_motivo.setdefault(codigo if codigo in MOTIVOS else "N", []).append(int(folha))
    return {
        "formato": FORMATO,
        "programa": _programa(),
        "sistema": ESAJ,
        "paginacao": FOLHAS,
        "tribunal": tribunal,
        "processo": processo,
        "ultima": int(ultima),
        "ausentes": {c: descrever_folhas(por_motivo[c]) for c in ORDEM_MOTIVOS if c in por_motivo},
        "origem": origem,
        "notas": [str(n) for n in notas if str(n).strip()],
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
    }


def manifesto_eproc(processo: str, documentos: list[dict], modo: str = "documentos",
                    tribunal: str = "", **extras) -> dict:
    """Manifesto do PDF do eProc: a paginação é a de cada documento.

    Cada item de ``documentos``: evento, rotulo, descricao, data, origem
    ("pdf", "imagem", "html", "texto", "midia"), situacao ("ok", "ausente",
    "midia"), inicio (página do PDF em que começa) e paginas. ``extras``
    leva o que mais couber (capa, partes, eventos sem documento...).
    """
    base = {
        "formato": FORMATO,
        "programa": _programa(),
        "sistema": EPROC,
        "paginacao": DOCUMENTO,
        "tribunal": tribunal,
        "processo": processo,
        "modo": modo,
        "documentos": list(documentos or []),
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
    }
    base.update({k: v for k, v in extras.items() if k not in base})
    return base


def palavras_chave(m: dict) -> str:
    """O resumo que vai em /Keywords: 'helestron;sistema=esaj;paginacao=folhas;...'."""
    partes = [PREFIXO_CHAVES, f"sistema={m.get('sistema', '')}",
              f"paginacao={m.get('paginacao', '')}", f"formato={m.get('formato', FORMATO)}"]
    if m.get("sistema") == ESAJ:
        partes.append(f"ultima={m.get('ultima', 0)}")
        aus = m.get("ausentes") or {}
        if aus:
            partes.append("ausentes=" + "|".join(f"{c}:{v.replace(' ', '')}"
                                                 for c, v in aus.items()))
    elif m.get("modo"):
        partes.append(f"modo={m['modo']}")
    return ";".join(partes)


def ausentes(m: dict | None) -> dict[int, str]:
    """Do manifesto do e-SAJ: folha -> código do motivo das páginas de aviso."""
    saida: dict[int, str] = {}
    if not m or m.get("paginacao") != FOLHAS:
        return saida
    for codigo, texto in (m.get("ausentes") or {}).items():
        for f in ler_faixas(texto):
            saida.setdefault(f, codigo if codigo in MOTIVOS else "N")
    return saida


def valido(m) -> bool:
    return (isinstance(m, dict) and m.get("paginacao") in (FOLHAS, DOCUMENTO)
            and m.get("sistema") in (ESAJ, EPROC))


# ------------------------------------------------- dentro do PDF (PyMuPDF)
def gravar_no_doc(doc, m: dict) -> None:
    """Grava o manifesto num documento PyMuPDF aberto (anexo + /Keywords).

    Os demais metadados ficam como estão. Quem chama salva o documento.
    """
    dados = json.dumps(m, ensure_ascii=False, indent=1).encode("utf-8")
    # embfile_upd do PyMuPDF 1.28 falha com bytes; apagar e anexar de novo
    # dá o mesmo resultado
    if NOME_ANEXO in set(doc.embfile_names() or []):
        doc.embfile_del(NOME_ANEXO)
    doc.embfile_add(NOME_ANEXO, dados, filename=NOME_ANEXO,
                    desc="Paginação dos autos (Helestron)")
    meta = dict(doc.metadata or {})
    meta["keywords"] = palavras_chave(m)
    meta["producer"] = meta.get("producer") or _programa()
    if m.get("processo") and not meta.get("title"):
        meta["title"] = f"Processo {m['processo']}"
    try:
        doc.set_metadata({k: v for k, v in meta.items()
                          if k in ("format", "title", "author", "subject", "keywords",
                                   "creator", "producer", "creationDate", "modDate",
                                   "trapped") and k != "format"})
    except Exception as erro:  # metadado é conveniência; o anexo é o que vale
        log.debug("metadados não gravados: %s", erro)


def ler_do_doc(doc) -> dict | None:
    """O manifesto de um documento PyMuPDF aberto; None se não houver."""
    try:
        if NOME_ANEXO not in set(doc.embfile_names() or []):
            return None
        m = json.loads(doc.embfile_get(NOME_ANEXO).decode("utf-8"))
    except Exception:
        return None
    return m if valido(m) else None


def ler_do_pdf(caminho: Path) -> dict | None:
    """O manifesto do PDF no disco; None se não houver ou não abrir.

    Lê pelo PyMuPDF e, sem ele, pelo pypdf (anexos do PDF).
    """
    caminho = Path(caminho)
    try:
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover - versões antigas
            import fitz  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover - PyMuPDF faz parte da instalação
        fitz = None
    if fitz is not None:
        try:
            with fitz.open(str(caminho)) as doc:
                return ler_do_doc(doc)
        except Exception:
            return None
    try:  # pragma: no cover - só sem o PyMuPDF
        from pypdf import PdfReader
        anexos = PdfReader(str(caminho)).attachments or {}
        conteudo = anexos.get(NOME_ANEXO)
        if not conteudo:
            return None
        m = json.loads((conteudo[0] if isinstance(conteudo, list) else conteudo).decode("utf-8"))
        return m if valido(m) else None
    except Exception:
        return None


def resumo(m: dict | None) -> str:
    """Uma linha para relatório, capa e índice: o que a paginação garante."""
    if not valido(m):
        return "paginação não conferida (PDF de versão anterior à 1.0.2)"
    if m.get("paginacao") == FOLHAS:
        texto = f"página N = folha N (fls. 1 a {m.get('ultima', 0)})"
        aus = ausentes(m)
        if aus:
            texto += f"; folhas com página de aviso: {descrever_folhas(aus)}"
        return texto
    docs = m.get("documentos") or []
    fora = [d for d in docs if d.get("situacao") != "ok"]
    texto = f"paginação de cada documento igual à do eProc ({len(docs)} documentos)"
    if fora:
        texto += f"; {len(fora)} não incluído(s) no PDF"
    return texto
