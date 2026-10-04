"""Montagem do PDF único de cada processo (PyMuPDF).

O caminho normal do e-SAJ é o PDF que o próprio servidor monta. Quando ele
falha (tempo esgotado, localizador inválido, erro 5xx), o processo é
montado aqui, peça a peça - coisa que a base não fazia: o processo
simplesmente ficava sem autos. O mesmo serve ao eProc, cujos documentos
chegam um a um e em formatos variados (PDF, HTML, imagem, texto).

Regras que valem para tudo neste módulo:

* gravação atômica (".parcial" + os.replace): uma queda de energia no meio
  deixa o arquivo anterior intacto, nunca um PDF pela metade;
* um documento ruim não derruba o processo: vira uma página de aviso
  ("documento X não pôde ser incluído") no lugar exato em que estaria, e a
  numeração das demais páginas não se desloca sem explicação;
* cada documento vira um marcador (sumário lateral do leitor de PDF), o que
  ajuda o magistrado a navegar e a IA a citar.
"""

from __future__ import annotations

import html as _html
import io
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from ..nucleo.sistema import REINSTALAR

log = logging.getLogger("download.pdf")

A4 = (595.0, 842.0)          # pontos (1/72 pol.)
MARGEM = 56.0                # ~2 cm
TIPOS = ("pdf", "html", "imagem", "texto", "aviso")


def _pymupdf():
    """O PyMuPDF pelo nome novo; 'fitz' é o nome antigo do mesmo pacote."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError as erro:
            raise RuntimeError(
                f"o componente de PDF (PyMuPDF) não está instalado. {REINSTALAR}") from erro
    return pymupdf


@dataclass
class Parte:
    """Um documento a entrar no PDF final."""
    titulo: str
    dados: bytes
    tipo: str = "pdf"        # pdf | html | imagem | texto | aviso


# ---------------------------------------------------------------- conversões
def e_pdf(dados: bytes | None) -> bool:
    """Os bytes começam como PDF? (o cabeçalho pode vir até o byte 1024)."""
    if not dados or len(dados) < 8:
        return False
    return b"%PDF-" in dados[:1024]


def e_html(dados: bytes | None) -> bool:
    inicio = (dados or b"")[:600].lstrip().lower()
    return inicio.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def _story_para_pdf(story) -> bytes:
    fitz = _pymupdf()
    saida = io.BytesIO()
    escritor = fitz.DocumentWriter(saida)
    pagina = fitz.Rect(0, 0, *A4)
    area = pagina + (MARGEM, MARGEM, -MARGEM, -MARGEM)
    mais = True
    paginas = 0
    while mais:
        dispositivo = escritor.begin_page(pagina)
        mais, _ = story.place(area)
        story.draw(dispositivo)
        escritor.end_page()
        paginas += 1
        if paginas > 5000:       # salvaguarda contra laço sem fim
            break
    escritor.close()
    return saida.getvalue()


_CSS = ("body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.35; } "
        "h1 { font-size: 13pt; } pre { font-family: monospace; font-size: 9pt; "
        "white-space: pre-wrap; } table { border-collapse: collapse; } "
        "td, th { border: 0.5pt solid #999; padding: 2pt; }")

_SCRIPTS = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


def _texto_de_html(html: str) -> str:
    sem = _SCRIPTS.sub(" ", html or "")
    sem = re.sub(r"<br\s*/?>|</p\s*>|</div\s*>|</tr\s*>|</h\d\s*>", "\n", sem, flags=re.I)
    return _html.unescape(_TAGS.sub(" ", sem))


def html_para_pdf(html: str) -> bytes:
    """HTML (despacho do eProc, certidão...) em PDF A4.

    Se o HTML for exótico demais para o motor de layout, sai ao menos o
    texto: melhor um documento sem formatação que um documento perdido.
    """
    fitz = _pymupdf()
    limpo = _SCRIPTS.sub(" ", html or "")
    # O texto já chega decodificado; o motor de HTML o recebe em UTF-8, e um
    # <meta charset=iso-8859-1> esquecido no documento o faria decodificar
    # de novo ("DecisÃ£o").
    limpo = re.sub(r"charset\s*=\s*[\"']?[\w.:-]+", "charset=utf-8", limpo, flags=re.I)
    try:
        story = fitz.Story(html=limpo, user_css=_CSS)
        dados = _story_para_pdf(story)
        if e_pdf(dados):
            return dados
    except Exception as erro:
        log.debug("HTML não coube no layout (%s); vai como texto", str(erro)[:120])
    return texto_para_pdf(_texto_de_html(html))


def _fontes():
    """Helvetica (Nimbus Sans) como fonte Unicode: a fonte "base 14" comum
    só conhece o Latin-1 e troca travessão e aspas curvas por "·"."""
    fitz = _pymupdf()
    return fitz.Font("helv"), fitz.Font("hebo")


def _quebrar(linha: str, largura: float, tamanho: float, fonte) -> list[str]:
    """Quebra uma linha em pedaços que cabem na largura (por palavra)."""
    medir = lambda t: fonte.text_length(t, fontsize=tamanho)  # noqa: E731
    if not linha.strip():
        return [""]
    saida, atual = [], ""
    for palavra in linha.split(" "):
        candidata = f"{atual} {palavra}" if atual else palavra
        if medir(candidata) <= largura:
            atual = candidata
            continue
        if atual:
            saida.append(atual)
        # palavra maior que a linha (endereço, código): corta por letra
        while medir(palavra) > largura and len(palavra) > 1:
            corte = len(palavra)
            while corte > 1 and medir(palavra[:corte]) > largura:
                corte -= 1
            saida.append(palavra[:corte])
            palavra = palavra[corte:]
        atual = palavra
    saida.append(atual)
    return saida


def _escrever(blocos: list[tuple[str, float, bool]], moldura: bool = False) -> bytes:
    """Escreve blocos (texto, tamanho, negrito) em páginas A4, linha a linha.

    Linha a linha, e não pelo motor de HTML: aquele junta "fi" e "fl" numa
    letra só (ligadura), e o texto extraído depois sai "Certiﬁco" - que
    nenhuma busca acha.
    """
    fitz = _pymupdf()
    normal, negrito = _fontes()
    largura = A4[0] - 2 * MARGEM
    linhas: list[tuple[str, float, object]] = []
    for texto, tamanho, forte in blocos:
        fonte = negrito if forte else normal
        for bruta in (texto or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            bruta = bruta.replace("\t", "    ")
            linhas += [(t, tamanho, fonte) for t in _quebrar(bruta, largura, tamanho, fonte)]
    doc = fitz.open()
    try:
        pagina, escritor, y = None, None, A4[1]
        for linha, tamanho, fonte in linhas or [("(vazio)", 10.0, normal)]:
            altura = tamanho * 1.4
            if pagina is None or y + altura > A4[1] - MARGEM:
                if escritor is not None:
                    escritor.write_text(pagina)
                pagina = doc.new_page(width=A4[0], height=A4[1])
                if moldura:
                    pagina.draw_rect(fitz.Rect(MARGEM - 10, MARGEM - 10, A4[0] - MARGEM + 10,
                                               A4[1] - MARGEM + 10),
                                     color=(0.77, 0.13, 0.12), width=1.2)
                escritor = fitz.TextWriter(pagina.rect)
                y = MARGEM
            if linha:
                escritor.append((MARGEM, y + tamanho), linha, font=fonte, fontsize=tamanho)
            y += altura
        if escritor is not None:
            escritor.write_text(pagina)
        try:
            doc.subset_fonts()        # só as letras usadas: KB em vez de 300 KB
        except Exception:
            pass
        return doc.tobytes(deflate=True, garbage=3)
    finally:
        doc.close()


def texto_para_pdf(texto: str, titulo: str = "") -> bytes:
    """Texto puro em PDF A4, com quebra de linha e de página."""
    blocos = [(titulo, 12.0, True), ("", 10.0, False)] if titulo else []
    return _escrever(blocos + [(texto or "", 10.0, False)])


def imagem_para_pdf(dados: bytes) -> bytes:
    """Imagem (foto, digitalização) em páginas A4, sem distorcer.

    TIFF de várias páginas - formato comum de digitalização - vira várias
    páginas; abrir só a primeira perderia o resto do documento em silêncio.
    """
    fitz = _pymupdf()
    with fitz.open(stream=dados) as img:
        if img.page_count < 1:
            raise ValueError("a imagem não tem conteúdo")
        convertido = img.convert_to_pdf()
    doc = fitz.open()
    try:
        with fitz.open("pdf", convertido) as fonte:
            for i, original in enumerate(fonte):
                deitada = original.rect.width > original.rect.height
                tamanho = (A4[1], A4[0]) if deitada else A4
                pagina = doc.new_page(width=tamanho[0], height=tamanho[1])
                area = pagina.rect + (MARGEM / 2, MARGEM / 2, -MARGEM / 2, -MARGEM / 2)
                pagina.show_pdf_page(area, fonte, i, keep_proportion=True)
        return doc.tobytes(deflate=True, garbage=3)
    finally:
        doc.close()


def pagina_aviso(titulo: str, texto: str) -> bytes:
    """Página que ocupa o lugar de um documento que não pôde ser incluído."""
    return _escrever([(titulo or "Aviso", 14.0, True), ("", 10.0, False),
                      ((texto or "")[:6000], 11.0, False)], moldura=True)


_CHARSET = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.I)


def decodificar(dados: bytes | str, html: bool = False) -> str:
    """Bytes de documento em texto, na codificação certa.

    Portal em PHP (o eProc, por exemplo) costuma servir ISO-8859-1: lido
    como UTF-8, "ação" vira "a��o". Vale o charset declarado; sem ele,
    UTF-8 se for válido, senão Windows-1252 (que cobre o Latin-1).
    """
    if isinstance(dados, str):
        return dados
    dados = dados or b""
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados[3:].decode("utf-8", errors="replace")
    if html:
        m = _CHARSET.search(dados[:4096])
        if m:
            try:
                return dados.decode(m.group(1).decode("ascii"), errors="replace")
            except LookupError:
                pass
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


def _como_pdf(parte: Parte) -> bytes:
    tipo = (parte.tipo or "pdf").lower()
    if tipo == "pdf":
        if not e_pdf(parte.dados):
            raise ValueError("o conteúdo recebido não é um PDF")
        return parte.dados
    if tipo == "html":
        return html_para_pdf(decodificar(parte.dados, html=True))
    if tipo == "imagem":
        return imagem_para_pdf(parte.dados)
    if tipo == "texto":
        return texto_para_pdf(decodificar(parte.dados))
    if tipo == "aviso":
        return pagina_aviso(parte.titulo, decodificar(parte.dados))
    raise ValueError(f"tipo de documento desconhecido: {parte.tipo}")


def _aviso_de_falha(titulo: str, motivo: str) -> bytes:
    return pagina_aviso(
        "Documento não incluído",
        f"O documento \"{titulo}\" não pôde ser incluído neste arquivo.\n\n"
        f"Motivo: {motivo}\n\n"
        "Consulte-o diretamente no portal do tribunal.")


# --------------------------------------------------------------- gravação
def _parcial(destino: Path) -> Path:
    return destino.with_name(destino.name + ".parcial")


TENTATIVAS_TROCA = 6
ESPERA_TROCA_S = 0.4


def _trocar(origem: Path, destino: Path) -> None:
    """os.replace com paciência para o Windows.

    O OneDrive (que sincroniza o acervo), o indexador e o antivírus abrem o
    arquivo recém-gravado por um instante, e a troca falha com "acesso
    negado" (PermissionError) - que o motor entenderia como "PDF aberto no
    leitor" e não tentaria de novo. Insiste-se por ~2 s; se for mesmo o
    leitor de PDF, o erro sobe igual.
    """
    for tentativa in range(TENTATIVAS_TROCA):
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if tentativa == TENTATIVAS_TROCA - 1:
                raise
            time.sleep(ESPERA_TROCA_S)


def _salvar_atomico(doc, destino: Path) -> None:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = _parcial(destino)
    try:
        doc.save(str(tmp), garbage=3, deflate=True)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    _trocar(tmp, destino)


def _inserir(doc, dados: bytes, titulo: str) -> int:
    """Insere um PDF (em bytes) no fim do doc; devolve quantas páginas entraram.

    PDF que não abre, ou sem página nenhuma, vira página de aviso.
    """
    fitz = _pymupdf()
    antes = len(doc)
    try:
        with fitz.open(stream=dados, filetype="pdf") as fonte:
            if fonte.needs_pass:
                raise ValueError("o PDF está protegido por senha")
            if len(fonte) == 0:
                raise ValueError("o PDF não tem nenhuma página")
            doc.insert_pdf(fonte)
    except Exception as erro:
        # um insert_pdf que falhou no meio pode ter deixado páginas pela metade
        while len(doc) > antes:
            doc.delete_page(len(doc) - 1)
        log.warning("  documento '%s' não pôde ser incluído: %s", titulo, str(erro)[:160])
        with fitz.open(stream=_aviso_de_falha(titulo, str(erro)[:300]), filetype="pdf") as aviso:
            doc.insert_pdf(aviso)
    return len(doc) - antes


def juntar(partes: list[Parte], destino: Path) -> int:
    """Junta as partes num PDF só, com um marcador por documento. Devolve
    o número de páginas. Grava de forma atômica."""
    if not partes:
        raise ValueError("nenhum documento para montar o PDF")
    fitz = _pymupdf()
    doc = fitz.open()
    sumario = []
    try:
        for parte in partes:
            titulo = (parte.titulo or "Documento").strip()[:200]
            inicio = len(doc) + 1
            try:
                dados = _como_pdf(parte)
            except Exception as erro:
                log.warning("  documento '%s' não pôde ser convertido: %s", titulo, str(erro)[:160])
                dados = _aviso_de_falha(titulo, str(erro)[:300])
            if _inserir(doc, dados, titulo):
                sumario.append([1, titulo, inicio])
        try:
            doc.set_toc(sumario)
        except Exception as erro:       # marcador é conveniência, não dever
            log.debug("sumário não gravado: %s", erro)
        _salvar_atomico(doc, destino)
        return len(doc)
    finally:
        doc.close()


def anexar(alvo: Path, novas: list[bytes], titulos: list[str] | None = None) -> int:
    """Acrescenta documentos ao fim de um PDF existente. Devolve o total de
    páginas. O original só é trocado quando o novo está gravado por inteiro."""
    fitz = _pymupdf()
    alvo = Path(alvo)
    # Aberto da MEMÓRIA, e não do arquivo: no Windows, um arquivo aberto
    # pelo MuPDF não pode ser substituído (os.replace dá "acesso negado"),
    # e é justamente ele que a gravação atômica troca no fim. Achado no CI
    # do Windows; no Linux a troca passa mesmo com o arquivo aberto.
    doc = fitz.open(stream=alvo.read_bytes(), filetype="pdf")
    try:
        sumario = doc.get_toc(simple=True) or []
        for i, dados in enumerate(novas or []):
            titulo = (titulos[i] if titulos and i < len(titulos) else f"Documento anexado {i + 1}")
            inicio = len(doc) + 1
            if _inserir(doc, dados, titulo):
                sumario.append([1, titulo, inicio])
        try:
            doc.set_toc(sumario)
        except Exception as erro:
            log.debug("sumário não atualizado: %s", erro)
        _salvar_atomico(doc, alvo)
        return len(doc)
    finally:
        doc.close()


def gravar(destino: Path, dados: bytes, marcadores: list[tuple[str, int]] | None = None,
           exigir_paginas: int | None = None) -> int:
    """Grava um PDF recebido pronto (o do servidor), com marcadores opcionais.

    Devolve o número de páginas. Os marcadores só entram se o PDF tiver
    exatamente ``exigir_paginas`` páginas (quando informado): com contagem
    diferente, cairiam em páginas erradas - e marcador errado é pior que
    nenhum. Se não puderem ser postos, o PDF é gravado assim mesmo.
    """
    if not e_pdf(dados):
        raise ValueError("o arquivo recebido não é um PDF")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = _parcial(destino)
    tmp.write_bytes(dados)
    paginas = 0
    try:
        fitz = _pymupdf()
        trocar = None
        doc = fitz.open(str(tmp))
        try:
            paginas = len(doc)
            confere = not exigir_paginas or exigir_paginas == paginas
            toc = [[1, t[:200], int(p)] for t, p in (marcadores or [])
                   if confere and 1 <= int(p) <= paginas]
            if toc:
                doc.set_toc(toc)
                # Salvamento incremental: só acrescenta o sumário ao fim do
                # arquivo, sem reescrever centenas de megabytes de autos.
                if doc.can_save_incrementally():
                    doc.saveIncr()
                else:
                    trocar = destino.with_name(destino.name + ".parcial2")
                    doc.save(str(trocar), garbage=1, deflate=True)
        finally:
            doc.close()
        if trocar is not None:
            os.replace(trocar, tmp)
    except Exception as erro:
        log.debug("marcadores não aplicados (%s); o PDF vai como veio", str(erro)[:160])
        tmp.write_bytes(dados)
        paginas = contar_paginas(tmp) or paginas
    if not paginas:
        # PDF truncado ou corrompido não substitui nada: no lugar dele ficaria
        # um arquivo que parece baixado e não abre.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise ValueError("o PDF recebido está corrompido (não abre)")
    _trocar(tmp, destino)
    return paginas


def contar_paginas(caminho: Path) -> int | None:
    """Quantas páginas o PDF tem; None se não abrir."""
    try:
        fitz = _pymupdf()
        with fitz.open(str(caminho)) as doc:
            return len(doc)
    except Exception:
        return None


def valido(caminho: Path) -> bool:
    """O arquivo existe, abre e tem ao menos uma página?"""
    try:
        if not Path(caminho).is_file() or Path(caminho).stat().st_size < 8:
            return False
    except OSError:
        return False
    n = contar_paginas(caminho)
    return bool(n)
