"""Texto dos autos e das transcrições, no formato que a IA lê melhor.

Um PDF de 800 folhas é pesado para qualquer assistente: lê-lo como imagem
custa caro e lento. O texto extraído, com a marca da folha em cada página,
deixa o Claude e o ChatGPT citarem "fl. 123" sem abrir o PDF, e cabe numa
busca. O arquivo de texto é um cache: refeito sozinho quando o PDF muda.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path

log = logging.getLogger(__name__)

MARCA_PAGINA = "=== [fl. {n}] ==="
# Logo abaixo da marca, o documento (marcador do PDF) a que a página pertence.
# No eProc, que não numera folhas, é o que a IA cita: "Evento 1 — ... — INIC1".
MARCA_DOCUMENTO = "[documento: {titulo}]"


def _pymupdf():
    """O PyMuPDF pelo nome novo; 'fitz' imprime aviso de obsoleto."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - versões antigas
        import fitz as pymupdf
    return pymupdf
_RE_MARCA = re.compile(r"^=== \[fl\. (\d+)\] ===$", re.M)


def _documento_por_pagina(sumario, paginas: int) -> dict[int, str]:
    """{página: título do marcador que a cobre}, a partir do sumário do PDF."""
    inicios = sorted(((int(item[2]), str(item[1]).strip()) for item in sumario or []
                      if len(item) >= 3 and int(item[2]) >= 1 and str(item[1]).strip()),
                     key=lambda x: x[0])
    saida: dict[int, str] = {}
    for k, (inicio, titulo) in enumerate(inicios):
        fim = inicios[k + 1][0] - 1 if k + 1 < len(inicios) else paginas
        for n in range(inicio, max(inicio, fim) + 1):
            saida[n] = titulo
    return saida


def texto_pdf(caminho: Path) -> str:
    """O texto do PDF, página por página, com a marca da página e o documento."""
    partes: list[str] = []
    try:
        fitz = _pymupdf()
        # Sem TEXT_PRESERVE_LIGATURES: "Certiﬁco" (ligadura) vira "Certifico",
        # e a busca da IA por "certifico" acha a palavra.
        flags = fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP
        with fitz.open(str(caminho)) as doc:
            try:
                documentos = _documento_por_pagina(doc.get_toc(simple=True), doc.page_count)
            except Exception:  # sumário estragado não impede o texto
                documentos = {}
            for i, pagina in enumerate(doc, 1):
                partes.append(MARCA_PAGINA.format(n=i))
                if documentos.get(i):
                    partes.append(MARCA_DOCUMENTO.format(titulo=documentos[i]))
                partes.append(pagina.get_text("text", flags=flags).strip())
        return "\n".join(partes) + "\n"
    except ImportError:  # pragma: no cover - PyMuPDF faz parte da instalação
        pass
    from pypdf import PdfReader

    leitor = PdfReader(str(caminho))
    for i, pagina in enumerate(leitor.pages, 1):
        partes.append(MARCA_PAGINA.format(n=i))
        try:
            partes.append((pagina.extract_text() or "").strip())
        except Exception:  # página corrompida não derruba o resto
            partes.append("[página ilegível]")
    return "\n".join(partes) + "\n"


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
    sufixo = caminho.suffix.lower()
    if sufixo == ".pdf":
        return texto_pdf(caminho)
    if sufixo == ".docx":
        return texto_docx(caminho)
    return caminho.read_text(encoding="utf-8", errors="replace")


def garantir_texto(origem: Path, destino: Path) -> Path:
    """Extrai o texto de 'origem' para 'destino', se ainda não estiver em dia.

    O texto leva a data de modificação do próprio PDF, e só vale enquanto as
    duas coincidem. "Texto mais novo que o PDF" não basta: um texto tirado de
    OUTRO PDF (o mesmo processo noutro lote, que foi apagado) passaria por
    atual, e a IA leria autos que não são os do arquivo.
    """
    try:
        if destino.exists() and abs(destino.stat().st_mtime - origem.stat().st_mtime) <= 2:
            return destino      # folga de 2 s: FAT/exFAT arredondam a data
    except OSError:
        pass
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = texto_de(origem)
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    try:
        quando = origem.stat().st_mtime
        os.utime(tmp, (quando, quando))
    except OSError:
        pass
    os.replace(tmp, destino)
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


def sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if not unicodedata.combining(c)).casefold()


def recortar_paginas(texto: str, inicio: int, fim: int) -> str:
    """Só as folhas [inicio, fim] de um texto com marcas de folha."""
    marcas = list(_RE_MARCA.finditer(texto))
    if not marcas:
        return texto
    pedacos = []
    for i, m in enumerate(marcas):
        n = int(m.group(1))
        if inicio <= n <= fim:
            ate = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
            pedacos.append(texto[m.start():ate])
    return "".join(pedacos)


def folha_na_posicao(texto: str, posicao: int) -> int:
    """Número da folha em que cai a posição 'posicao' do texto."""
    folha = 0
    for m in _RE_MARCA.finditer(texto):
        if m.start() > posicao:
            break
        folha = int(m.group(1))
    return folha


def buscar(texto: str, termo: str, contexto: int = 160, limite: int = 20):
    """Ocorrências de 'termo' (sem diferenciar acento e caixa).

    Devolve [(folha, trecho)]. A busca ignora acento comparando as versões
    sem acento, que têm o mesmo comprimento do original quando o texto vem
    em NFC - o caso do PyMuPDF e do python-docx.
    """
    alvo = sem_acento(termo.strip())
    if not alvo:
        return []
    plano = sem_acento(texto)
    if len(plano) != len(texto):
        texto = plano  # perde o acento no trecho, mas a posição bate
    achados = []
    inicio = 0
    while len(achados) < limite:
        pos = plano.find(alvo, inicio)
        if pos < 0:
            break
        a, b = max(0, pos - contexto), min(len(texto), pos + len(alvo) + contexto)
        trecho = " ".join(texto[a:b].split())
        achados.append((folha_na_posicao(texto, pos), trecho))
        inicio = pos + len(alvo)
    return achados
