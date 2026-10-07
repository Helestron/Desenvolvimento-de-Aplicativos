"""Montagem do PDF único de cada processo (PyMuPDF).

O caminho normal do e-SAJ é o PDF que o próprio servidor monta. Quando ele
falha (tempo esgotado, localizador inválido, erro 5xx) ou não confere com o
índice da Pasta Digital, o processo é montado aqui, peça a peça - coisa que
a base não fazia: o processo simplesmente ficava sem autos. O eProc, cujos
documentos chegam um a um e em formatos variados (PDF, HTML, imagem,
texto), também é montado aqui.

Regras que valem para tudo neste módulo:

* gravação atômica (".parcial" + os.replace): uma queda de energia no meio
  deixa o arquivo anterior intacto, nunca um PDF pela metade;
* a numeração do tribunal é a do arquivo (o manifesto de
  ``nucleo.paginacao`` vai dentro do PDF e diz isso):
  - e-SAJ (``gravar_alinhado`` e ``juntar_folhas``): a página N do PDF é
    SEMPRE a folha N. A folha que não veio - não oferecida pela Pasta
    Digital, peça que não baixou, arquivo inválido ou com páginas a menos -
    tem uma página de aviso no lugar ("Folha N — não disponibilizada pelo
    e-SAJ"), uma por folha; nada se desloca;
  - eProc (``juntar``): cada documento conserva a própria paginação (o
    rótulo de página diz "Ev. 1 INIC1 p. 2"); o documento ruim vira UMA
    página de aviso, marcada como não citável, sem mexer na paginação de
    documento nenhum;
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
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..nucleo import paginacao
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
    """Um documento a entrar no PDF final (``juntar``).

    ``rotulo_pagina`` é o prefixo do rótulo das páginas dele no leitor de PDF
    ("Ev. 1 INIC1 p. "); vazio, a página leva o número dela no arquivo.
    ``numerar``: o rótulo leva o número da página dentro do documento (1,
    2...); sem ele, todas as páginas mostram o mesmo rótulo (documento sem
    paginação própria, como o despacho em HTML do eProc). ``info`` é a
    entrada deste documento no manifesto, que ``juntar`` completa.
    ``manter_sumario``: o sumário do próprio documento entra, como nível 2,
    sob o marcador dele.

    ``inicio`` (página do PDF em que o documento começa), ``paginas`` e
    ``falhou`` (não pôde ser incluído: uma página de aviso ficou no lugar)
    são preenchidos por ``juntar``.
    """
    titulo: str
    dados: bytes
    tipo: str = "pdf"        # pdf | html | imagem | texto | aviso
    rotulo_pagina: str = ""
    numerar: bool = True
    info: dict | None = None
    manter_sumario: bool = False
    inicio: int = 0
    paginas: int = 0
    falhou: bool = False


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


TENTATIVAS_TROCA = 7
# A 1ª espera entre as tentativas; cada uma dobra a anterior, até o máximo:
# 0,25 + 0,5 + 1 + 2 + 3 + 3 = 9,75 s no total.
ESPERA_TROCA_S = 0.25
ESPERA_MAXIMA_TROCA_S = 3.0


def _trocar(origem: Path, destino: Path) -> None:
    """os.replace com paciência para o Windows.

    O OneDrive (que sincroniza o acervo), o indexador e o antivírus abrem o
    arquivo recém-gravado por um instante - num PDF de centenas de páginas,
    o antivírus leva segundos -, e a troca falha com "acesso negado"
    (PermissionError), que o motor entenderia como "PDF aberto no leitor" e
    não tentaria de novo. Insiste-se com esperas crescentes (0,25, 0,5, 1, 2
    e 3 s), por quase 10 s no total: a trava curta passa logo, sem demora; se
    for mesmo o leitor de PDF, o erro sobe igual.
    """
    for tentativa in range(TENTATIVAS_TROCA):
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if tentativa == TENTATIVAS_TROCA - 1:
                raise
            time.sleep(min(ESPERA_TROCA_S * 2 ** tentativa, ESPERA_MAXIMA_TROCA_S))


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


def _apagar(*caminhos: Path) -> None:
    for caminho in caminhos:
        try:
            Path(caminho).unlink()
        except OSError:
            pass


def _abrir_fonte(dados: bytes):
    """Abre um PDF em bytes para inserir; ValueError se ele não servir."""
    fitz = _pymupdf()
    try:
        fonte = fitz.open(stream=dados, filetype="pdf")
    except Exception as erro:
        raise ValueError(f"o arquivo não abre como PDF ({str(erro)[:120]})") from erro
    if fonte.needs_pass:
        fonte.close()
        raise ValueError("o PDF está protegido por senha")
    if len(fonte) == 0:
        fonte.close()
        raise ValueError("o PDF não tem nenhuma página")
    return fonte


def contar_paginas_de(dados: bytes | None) -> int | None:
    """Quantas páginas tem o PDF em bytes; None se ele não servir."""
    if not dados:
        return None
    try:
        with _abrir_fonte(dados) as fonte:
            return len(fonte)
    except Exception:
        return None


def _inserir(doc, dados: bytes, titulo: str, sumario: bool = False) -> tuple[int, bool, list]:
    """Insere um PDF (em bytes) no fim do doc.

    Devolve (páginas que entraram, se entrou o próprio documento, o sumário
    dele já com as páginas do doc - só com ``sumario``). PDF que não abre,
    ou sem página nenhuma, vira página de aviso (e o segundo valor é False).
    """
    fitz = _pymupdf()
    antes = len(doc)
    try:
        with _abrir_fonte(dados) as fonte:
            proprio = []
            if sumario:
                try:
                    proprio = fonte.get_toc(simple=True) or []
                except Exception:
                    proprio = []
            n = len(fonte)
            doc.insert_pdf(fonte)
        deslocado = [[int(nivel), str(t)[:200], antes + int(p)] for nivel, t, p in proprio
                     if 1 <= int(p) <= n]
        return len(doc) - antes, True, deslocado
    except Exception as erro:
        # um insert_pdf que falhou no meio pode ter deixado páginas pela metade
        while len(doc) > antes:
            doc.delete_page(len(doc) - 1)
        log.warning("  documento '%s' não pôde ser incluído: %s", titulo, str(erro)[:160])
        with fitz.open(stream=_aviso_de_falha(titulo, str(erro)[:300]), filetype="pdf") as aviso:
            doc.insert_pdf(aviso)
        return len(doc) - antes, False, []


# ----------------------------------------------------- acabamentos do arquivo
_ROTULO_RECUSADO = re.compile(r"[^A-Za-z0-9 .,:;/_\-\[\]]")


def rotulo_seguro(texto: str) -> str:
    """O rótulo de página em ASCII simples, até 60 letras.

    O PyMuPDF 1.28 grava errado o prefixo com acento ou parênteses ("ÁUDIO1"
    volta "\\303\\201UDIO1"; "(ausente)", "\\ausente\\"): o acento sai, e o
    que não for letra, número ou pontuação simples vira espaço.
    """
    sem = unicodedata.normalize("NFKD", str(texto or ""))
    sem = "".join(c for c in sem if not unicodedata.combining(c))
    sem = re.sub(r" {2,}", " ", _ROTULO_RECUSADO.sub(" ", sem))
    return sem.lstrip()[:60]


def _sem_numero(prefixo: str) -> str:
    """'Ev. 1 INIC1 p. ' -> 'Ev. 1 INIC1': o rótulo do documento que não entrou."""
    return re.sub(r"\s*\bp\.?\s*$", "", (prefixo or "").strip()).strip()


def _rotulos(doc, partes: list[Parte]) -> None:
    """Rótulos de página (/PageLabels): o leitor de PDF mostra a numeração
    do tribunal ("Ev. 1 INIC1 p. 2") na caixa da página."""
    com = [p for p in partes if p.paginas]
    if not any(p.rotulo_pagina for p in com):
        return
    regras = []
    for p in com:
        inicio = p.inicio - 1
        if not p.rotulo_pagina:
            # sem rótulo próprio: o número da página no arquivo, como sem regra
            regras.append({"startpage": inicio, "style": "D", "firstpagenum": p.inicio})
        elif p.falhou:
            # página de aviso no lugar: não tem número para citar
            regras.append({"startpage": inicio,
                           "prefix": rotulo_seguro(f"{_sem_numero(p.rotulo_pagina)} nao incluido")})
        elif p.numerar:
            regras.append({"startpage": inicio, "prefix": rotulo_seguro(p.rotulo_pagina),
                           "style": "D", "firstpagenum": 1})
        else:
            regras.append({"startpage": inicio,
                           "prefix": rotulo_seguro(p.rotulo_pagina).rstrip()})
    doc.set_page_labels(regras)


def _hierarquia(entradas) -> list[list]:
    """Sumário no formato do set_toc: [nível, título, página], o primeiro no
    nível 1 e nenhum subindo mais de um nível de uma vez."""
    saida, anterior = [], 0
    for entrada in entradas or []:
        if len(entrada) == 2:              # (título, página)
            nivel, (titulo, pagina) = 1, entrada
        else:
            nivel, titulo, pagina = entrada[:3]
        nivel = max(1, min(int(nivel), anterior + 1))
        saida.append([nivel, str(titulo or "Documento")[:200], int(pagina)])
        anterior = nivel
    return saida


def _gravar_sumario(doc, *opcoes) -> None:
    """Tenta cada sumário, do mais completo ao mais simples: o sumário
    próprio de um documento pode vir com hierarquia que o set_toc recusa, e
    perder todos os marcadores por causa dele seria pior."""
    for sumario in opcoes:
        try:
            doc.set_toc(_hierarquia(sumario))
            return
        except Exception as erro:       # marcador é conveniência, não dever
            log.debug("sumário não gravado: %s", erro)


_CHAVES_META = ("title", "author", "subject", "keywords", "creator", "producer",
                "creationDate", "modDate", "trapped")


def _aplicar_metadados(doc, metadados: dict | None) -> None:
    if not metadados:
        return
    atual = {k: v for k, v in (doc.metadata or {}).items() if k in _CHAVES_META and v}
    atual.update({k: str(v) for k, v in metadados.items() if k in _CHAVES_META and v is not None})
    doc.set_metadata(atual)


def _completar_manifesto(manifesto: dict, partes: list[Parte]) -> dict:
    """Completa o manifesto (eProc) com o que só a montagem sabe: em que
    página cada documento começou, quantas tem e se entrou mesmo."""
    comuns = [p for p in partes if isinstance(p.info, dict)]
    for p in comuns:
        p.info["inicio"] = p.inicio
        p.info["paginas"] = p.paginas
        if p.falhou:
            p.info["situacao"] = "ausente"
        else:
            p.info.setdefault("situacao", "ok")
    if manifesto.get("modo") == "completo":
        # o arquivo inteiro do tribunal: as partes dele, sem documentos
        manifesto["documentos"] = list(manifesto.get("documentos") or [])
        manifesto["partes"] = [{"inicio": p.inicio, "paginas": p.paginas}
                               for p in partes if p.paginas]
        return manifesto
    docs = manifesto.get("documentos")
    if not docs:
        manifesto["documentos"] = [p.info for p in comuns]
        return manifesto
    # Entradas que não são o próprio info de uma parte (cópias): acha-se a
    # parte pelo evento e rótulo.
    proprios = {id(p.info) for p in comuns}
    por_chave = {(p.info.get("evento"), p.info.get("rotulo")): p.info for p in comuns}
    for d in docs:
        if not isinstance(d, dict) or id(d) in proprios:
            continue
        info = por_chave.get((d.get("evento"), d.get("rotulo")))
        if info is not None:
            d.update({k: info[k] for k in ("inicio", "paginas", "situacao")})
    return manifesto


def _gravar_manifesto(doc, manifesto: dict | None) -> None:
    if manifesto is None:
        return
    try:
        paginacao.gravar_no_doc(doc, manifesto)
    except Exception as erro:
        # sem o manifesto o PDF ainda está certo; só parece de versão anterior
        log.warning("manifesto de paginação não gravado no PDF: %s", str(erro)[:160])


# ------------------------------------------------------------------ juntar
def juntar(partes: list[Parte], destino: Path, metadados: dict | None = None,
           manifesto: dict | None = None) -> int:
    """Junta as partes num PDF só, com um marcador por documento. Devolve
    o número de páginas. Grava de forma atômica.

    Preenche ``inicio``, ``paginas`` e ``falhou`` de cada parte e põe os
    rótulos de página (``Parte.rotulo_pagina``), o sumário próprio dos
    documentos (``Parte.manter_sumario``, nível 2), os ``metadados`` e o
    ``manifesto`` (``nucleo.paginacao``), completado com o início, as páginas
    e a situação de cada documento. Esses acabamentos são conveniência: o
    que falhar fica de fora, e o arquivo é gravado assim mesmo.
    """
    if not partes:
        raise ValueError("nenhum documento para montar o PDF")
    fitz = _pymupdf()
    doc = fitz.open()
    simples, completo = [], []
    try:
        for parte in partes:
            titulo = (parte.titulo or "Documento").strip()[:200]
            parte.inicio = len(doc) + 1
            parte.paginas, parte.falhou = 0, False
            try:
                dados = _como_pdf(parte)
                convertido = True
            except Exception as erro:
                log.warning("  documento '%s' não pôde ser convertido: %s", titulo, str(erro)[:160])
                dados = _aviso_de_falha(titulo, str(erro)[:300])
                convertido = False
            n, entrou, proprio = _inserir(doc, dados, titulo,
                                          sumario=parte.manter_sumario and convertido)
            parte.paginas = n
            parte.falhou = not (convertido and entrou)
            if n:
                simples.append([1, titulo, parte.inicio])
                completo.append([1, titulo, parte.inicio])
                completo += [[nivel + 1, t, p] for nivel, t, p in proprio]
        _gravar_sumario(doc, *([completo, simples] if completo != simples else [simples]))
        try:
            _rotulos(doc, partes)
        except Exception as erro:
            log.debug("rótulos de página não gravados: %s", erro)
        try:
            _aplicar_metadados(doc, metadados)
        except Exception as erro:
            log.debug("metadados não gravados: %s", erro)
        if manifesto is not None:
            _gravar_manifesto(doc, _completar_manifesto(manifesto, partes))
        _salvar_atomico(doc, destino)
        return len(doc)
    finally:
        doc.close()


def gravar(destino: Path, dados: bytes, marcadores: list[tuple[str, int]] | None = None,
           exigir_paginas: int | None = None, metadados: dict | None = None,
           manifesto: dict | None = None, preservar_sumario: bool = False) -> int:
    """Grava um PDF recebido pronto - o arquivo inteiro gerado pelo tribunal.

    Devolve o número de páginas. O arquivo entra como veio: o que se
    acrescenta (marcadores, metadados, manifesto) vai por salvamento
    incremental, no fim dele, sem reescrever centenas de megabytes de autos
    nem mexer na paginação.

    * ``marcadores=None``: o sumário que o arquivo já traz fica como está.
      Os marcadores informados só entram se o PDF tiver exatamente
      ``exigir_paginas`` páginas (quando informado) - com contagem
      diferente, cairiam em páginas erradas, e marcador errado é pior que
      nenhum - e, com ``preservar_sumario``, só se o arquivo não tiver
      sumário próprio.
    * ``manifesto`` (``nucleo.paginacao``) vai anexo ao PDF; o do modo
      "completo" do eProc sem ``partes`` ganha a do arquivo inteiro.

    Se os acréscimos não puderem ser gravados, o PDF é gravado como veio.
    PDF que não abre não substitui nada.
    """
    if not e_pdf(dados):
        raise ValueError("o arquivo recebido não é um PDF")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = _parcial(destino)
    tmp2 = destino.with_name(destino.name + ".parcial2")
    tmp.write_bytes(dados)
    paginas = 0
    try:
        fitz = _pymupdf()
        trocar = False
        doc = fitz.open(str(tmp))
        try:
            paginas = len(doc)
            mudou = False
            if marcadores is not None:
                confere = not exigir_paginas or exigir_paginas == paginas
                toc = [[1, t[:200], int(p)] for t, p in marcadores
                       if confere and 1 <= int(p) <= paginas]
                if toc and preservar_sumario and doc.get_toc(simple=True):
                    toc = []
                if toc:
                    doc.set_toc(toc)
                    mudou = True
            if metadados:
                _aplicar_metadados(doc, metadados)
                mudou = True
            if manifesto is not None and paginas:
                if manifesto.get("modo") == "completo" and not manifesto.get("partes"):
                    manifesto["partes"] = [{"inicio": 1, "paginas": paginas}]
                paginacao.gravar_no_doc(doc, manifesto)
                mudou = True
            if mudou:
                # Salvamento incremental: só acrescenta ao fim do arquivo.
                if doc.can_save_incrementally():
                    doc.saveIncr()
                else:
                    doc.save(str(tmp2), garbage=1, deflate=True)
                    trocar = True
        finally:
            doc.close()
        if trocar:
            # o .parcial recém-fechado também é aberto pelo antivírus e pelo
            # indexador por um instante: a troca insiste, como a final
            _trocar(tmp2, tmp)
    except Exception as erro:
        log.warning("marcadores ou manifesto não aplicados (%s); o PDF vai como veio",
                    str(erro)[:160])
        _apagar(tmp2)           # o .parcial2 que sobrou não fica na pasta do lote
        tmp.write_bytes(dados)
        paginas = contar_paginas(tmp) or paginas
    if not paginas:
        # PDF truncado ou corrompido não substitui nada: no lugar dele ficaria
        # um arquivo que parece baixado e não abre.
        _apagar(tmp)
        raise ValueError("o PDF recebido está corrompido (não abre)")
    _trocar(tmp, destino)
    return paginas


# ============================================== e-SAJ: página N = folha N
# A folha que o e-SAJ carimba em cada página ("fls. 12", numa linha só - o
# "conforme fls. 12" do texto não conta). Só decide quando quase todas as
# páginas trazem o carimbo; sem ele, não há veredito.
RE_CARIMBO = re.compile(r"^\s*fls?\.\s*(\d{1,6})\s*$", re.M | re.I)
MINIMO_CARIMBADAS = 0.9
TITULO_AUSENTE = "Folha {n} — não disponibilizada pelo e-SAJ"


class Desalinhado(ValueError):
    """O PDF do servidor não confere com o índice da Pasta Digital: gravado,
    a página N não seria a folha N. Quem chama monta o processo peça a peça."""


@dataclass
class Montagem:
    """O que saiu de uma montagem página = folha."""
    paginas: int                                   # = a última folha
    ausentes: dict[int, str]                       # folha -> código (paginacao.MOTIVOS)
    notas: list[str] = field(default_factory=list)


@dataclass
class PecaDeFolhas:
    """Um bloco de folhas da Pasta Digital, baixado à parte (getPDF.do)."""
    proprias: list[int]                 # as folhas que este bloco fornece
    ini: int
    fim: int
    titulo: str = ""
    dados: bytes | None = None          # None: a peça não pôde ser baixada
    total_documento: int = 0            # folhas do documento inteiro (todos os blocos dele)
    deslocamento: int = 0               # onde este bloco começa dentro do documento inteiro


# acabamento(ausentes, notas) -> (sumário, manifesto). Só depois de montar se
# sabe que folhas ficaram com aviso, e o sumário e o manifesto dependem disso.
Acabamento = Callable[[dict, list], tuple]


def _fls(folhas) -> str:
    """{8} -> 'fl. 8'; {6, 7, 40} -> 'fls. 6-7, 40'."""
    lista = sorted(set(folhas))
    return (f"fl. {lista[0]}" if len(lista) == 1
            else f"fls. {paginacao.descrever_folhas(lista)}")


def paginas_de_aviso(itens: list[tuple[int, str, str]]) -> bytes:
    """Um PDF com uma página de aviso por folha: [(folha, código, título da peça)].

    A primeira linha de cada página é exatamente "Folha N — não
    disponibilizada pelo e-SAJ" (é por ela que a IA e a skill reconhecem a
    página); depois vêm o motivo (``paginacao.MOTIVOS``), a peça, quando
    houver, e o porquê da página. Um documento só, com as fontes escolhidas
    uma vez: um buraco de centenas de folhas não pode custar centenas de PDFs.
    """
    fitz = _pymupdf()
    normal, negrito = _fontes()
    largura = A4[0] - 2 * MARGEM
    quebradas: dict[str, list[str]] = {}     # medir o texto é o que custa: uma vez por frase

    def linhas(texto: str) -> list[str]:
        if texto not in quebradas:
            quebradas[texto] = _quebrar(texto, largura, 11, normal)
        return quebradas[texto]

    doc = fitz.open()
    try:
        for folha, codigo, titulo in itens:
            pagina = doc.new_page(width=A4[0], height=A4[1])
            pagina.draw_rect(fitz.Rect(MARGEM - 10, MARGEM - 10, A4[0] - MARGEM + 10,
                                       A4[1] - MARGEM + 10), color=(0.77, 0.13, 0.12), width=1.2)
            escritor = fitz.TextWriter(pagina.rect)
            y = MARGEM + 16
            escritor.append((MARGEM, y), TITULO_AUSENTE.format(n=folha), font=negrito, fontsize=16)
            y += 16 * 1.4 + 8
            textos = [f"Motivo: {paginacao.MOTIVOS.get(codigo, paginacao.MOTIVOS['N'])}."]
            if titulo:
                textos.append(f"Peça: {str(titulo).strip()[:300]}.")
            textos += ["", "Esta página ocupa o lugar da folha que não veio, para que a página N "
                           "deste arquivo seja sempre a folha N dos autos. Consulte a folha no "
                           "portal do tribunal."]
            for texto in textos:
                for linha in linhas(texto):
                    if linha:
                        escritor.append((MARGEM, y), linha, font=normal, fontsize=11)
                    y += 11 * 1.4
            escritor.write_text(pagina)
        try:
            doc.subset_fonts()
        except Exception:
            pass
        return doc.tobytes(deflate=True, garbage=3)
    finally:
        doc.close()


def carimbo(pagina) -> int | None:
    """A folha carimbada pelo e-SAJ na página; None se não houver."""
    try:
        m = RE_CARIMBO.search(pagina.get_text("text") or "")
    except Exception:
        return None
    return int(m.group(1)) if m else None


def _conferir_carimbos(doc, mapa: dict[int, int]) -> None:
    """Levanta Desalinhado se as páginas carimbadas trazem outra folha."""
    if not mapa:
        return
    lidos = {f: carimbo(doc[k]) for f, k in mapa.items()}
    com = [f for f, c in lidos.items() if c is not None]
    if len(com) < MINIMO_CARIMBADAS * len(mapa):
        return
    errados = sorted(f for f in com if lidos[f] != f)
    if errados:
        f = errados[0]
        raise Desalinhado(f"a folha carimbada não confere com o índice da Pasta Digital "
                          f"(no lugar da fl. {f} veio a página carimbada fls. {lidos[f]})")


def _acabar(doc, sumario, manifesto) -> None:
    if sumario:
        _gravar_sumario(doc, sumario)
    _gravar_manifesto(doc, manifesto)


def gravar_alinhado(destino: Path, dados: bytes, faixas: list[tuple[int, int, list[int]]],
                    ultima: int, avisos: dict[int, tuple[str, str]] | None = None,
                    acabamento: Acabamento | None = None) -> Montagem:
    """Grava o PDF único do servidor do e-SAJ com a página N = folha N.

    ``faixas``: um (ini, fim, folhas próprias) por bloco, na ordem em que
    foram pedidos ao servidor; ``ultima``: a última folha; ``avisos``: folha
    -> (código, título) das folhas que a Pasta Digital não ofereceu (as que
    nenhum bloco fornece; sem entrada, "N").

    Levanta ``Desalinhado`` quando o PDF não tem uma página por folha pedida
    ou quando a folha carimbada nas páginas não confere: gravado assim, a
    numeração não seria a do e-SAJ. Nesse caso, e em qualquer erro, o
    arquivo anterior fica intacto e não sobra arquivo parcial. Com o PDF do
    servidor na mesma ordem das folhas, as páginas de aviso e o resto vão
    por salvamento incremental: os bytes do servidor ficam como vieram.
    """
    if not e_pdf(dados):
        raise ValueError("o arquivo recebido não é um PDF")
    fitz = _pymupdf()
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = _parcial(destino)
    tmp2 = destino.with_name(destino.name + ".parcial2")
    avisos = dict(avisos or {})
    try:
        tmp.write_bytes(dados)
        try:
            doc = fitz.open(str(tmp))
        except Exception as erro:
            raise ValueError("o PDF recebido está corrompido (não abre)") from erro
        trocar = False
        try:
            if doc.needs_pass:
                raise ValueError("o PDF do servidor está protegido por senha")
            esperado = sum(fim - ini + 1 for ini, fim, _ in faixas)
            if not len(doc):
                raise ValueError("o PDF recebido está corrompido (não abre)")
            if len(doc) != esperado:
                raise Desalinhado(f"o PDF do servidor tem {len(doc)} página"
                                  f"{'s' if len(doc) != 1 else ''} para {esperado} folha"
                                  f"{'s' if esperado != 1 else ''}")
            # página do servidor -> folha, na ordem em que os blocos foram pedidos;
            # a cópia de uma folha que já tem dono (faixas sobrepostas) sai
            mapa: dict[int, int] = {}
            k = 0
            for ini, fim, proprias in faixas:
                donas = set(proprias)
                for f in range(ini, fim + 1):
                    if f in donas and f not in mapa:
                        mapa[f] = k
                    k += 1
            if not mapa or max(mapa) > ultima:
                raise ValueError("o índice das folhas não confere com a última folha")
            _conferir_carimbos(doc, mapa)
            folhas = sorted(mapa)
            identidade = all(mapa[f] == j for j, f in enumerate(folhas))
            if not identidade:
                doc.select([mapa[f] for f in folhas])
            faltam = [f for f in range(1, ultima + 1) if f not in mapa]
            itens = [(f, *avisos.get(f, ("N", ""))) for f in faltam]
            if itens:
                # em ordem crescente: cada inserção já encontra as folhas
                # anteriores no lugar
                with fitz.open("pdf", paginas_de_aviso(itens)) as avisos_pdf:
                    for j, f in enumerate(faltam):
                        doc.insert_pdf(avisos_pdf, from_page=j, to_page=j, start_at=f - 1)
            if len(doc) != ultima:
                raise Desalinhado(f"a montagem saiu com {len(doc)} páginas para {ultima} folhas")
            ausentes = {f: c for f, c, _ in itens}
            sumario, manifesto = acabamento(ausentes, []) if acabamento else ([], None)
            _acabar(doc, sumario, manifesto)
            if identidade and doc.can_save_incrementally():
                doc.saveIncr()
            else:
                doc.save(str(tmp2), garbage=3, deflate=True)
                trocar = True
        finally:
            # fechado ANTES da troca: no Windows, arquivo aberto pelo MuPDF
            # não pode ser substituído
            doc.close()
        if trocar:
            os.replace(tmp2, tmp)
        # PDF aberto no leitor (PermissionError): o anterior fica, e o parcial sai
        _trocar(tmp, destino)
    except BaseException:
        _apagar(tmp, tmp2)
        raise
    return Montagem(ultima, ausentes, [])


def _escolher_paginas(fonte, item: PecaDeFolhas, notas: list[str]) -> dict[int, int]:
    """Folha -> página do arquivo de uma peça, quando ele não tem uma
    página por folha. Faltando páginas, as folhas do fim ficam sem (e
    ganham aviso); sobrando, nenhuma página sem folha entra no PDF - ela
    deslocaria todas as folhas seguintes."""
    n = item.fim - item.ini + 1
    k = len(fonte)
    folhas = range(item.ini, item.fim + 1)
    if k <= n:
        return {f: f - item.ini for f in folhas if f - item.ini < k}
    if item.total_documento > n and k == item.total_documento and item.deslocamento + n <= k:
        # o getPDF.do devolveu o documento inteiro, não só este bloco: a fatia dele
        log.info("    %s: veio o documento inteiro (%d páginas); uso as do bloco",
                 _fls(folhas), k)
        return {f: item.deslocamento + f - item.ini for f in folhas}
    lidos = [carimbo(fonte[i]) for i in range(k)]
    if sum(c is not None for c in lidos) >= MINIMO_CARIMBADAS * k:
        escolha: dict[int, int] = {}
        for i, c in enumerate(lidos):
            if c is not None and item.ini <= c <= item.fim and c not in escolha:
                escolha[c] = i
        notas.append(f"{_fls(folhas)}: o arquivo da peça tinha {k} páginas; mantidas "
                     f"só as carimbadas com essas folhas ({len(escolha)})")
        return escolha
    notas.append(f"{_fls(folhas)}: o arquivo da peça tinha {k} páginas; "
                 + ("mantida a primeira" if n == 1 else f"mantidas as {n} primeiras"))
    return {f: f - item.ini for f in folhas}


def juntar_folhas(itens: list[PecaDeFolhas], ultima: int, destino: Path,
                  avisos: dict[int, tuple[str, str]] | None = None,
                  acabamento: Acabamento | None = None) -> Montagem:
    """Monta, peça a peça, o PDF do e-SAJ com a página N = folha N.

    Cada folha de 1 a ``ultima`` vira exatamente uma página: a do arquivo
    da peça que a fornece, ou uma página de aviso - a peça não veio ("B"),
    o arquivo dela não abre ("I") ou tem páginas a menos ("C"), ou nenhuma
    peça fornece a folha (``avisos``; sem entrada, "N"). Arquivo de peça
    com páginas a mais é aparado (e anotado em ``notas``). Grava de forma
    atômica.
    """
    fitz = _pymupdf()
    avisos = dict(avisos or {})
    abertos: dict[int, object] = {}        # id(dados) -> documento aberto
    # folha -> ("pdf", fonte, página, título) | ("aviso", código, título)
    origem: dict[int, tuple] = {}
    notas: list[str] = []
    doc = avisos_pdf = None
    try:
        for item in itens:
            proprias = [f for f in item.proprias if 1 <= f <= ultima and f not in origem]
            if not proprias:
                continue
            if item.dados is None:
                origem.update({f: ("aviso", "B", item.titulo) for f in proprias})
                continue
            fonte = abertos.get(id(item.dados))
            if fonte is None:
                try:
                    fonte = _abrir_fonte(item.dados)
                except Exception as erro:
                    log.warning("  peça '%s' veio inválida: %s", item.titulo, str(erro)[:160])
                    origem.update({f: ("aviso", "I", item.titulo) for f in proprias})
                    continue
                abertos[id(item.dados)] = fonte
            paginas = _escolher_paginas(fonte, item, notas)
            for f in proprias:
                origem[f] = (("pdf", fonte, paginas[f], item.titulo) if f in paginas
                             else ("aviso", "C", item.titulo))
        for f in range(1, ultima + 1):
            if f not in origem:
                codigo, titulo = avisos.get(f, ("N", ""))
                origem[f] = ("aviso", codigo, titulo)
        lista = [(f, o[1], o[2]) for f, o in sorted(origem.items()) if o[0] == "aviso"]
        posicao = {f: j for j, (f, _, _) in enumerate(lista)}
        if lista:
            avisos_pdf = fitz.open("pdf", paginas_de_aviso(lista))
        ausentes = {f: c for f, c, _ in lista}

        def fonte_de(f):
            o = origem[f]
            return (avisos_pdf, posicao[f]) if o[0] == "aviso" else (o[1], o[2])

        doc = fitz.open()
        f = 1
        while f <= ultima:
            # uma inserção por trecho seguido da mesma fonte, não por página
            fonte, pagina = fonte_de(f)
            g = f
            while g < ultima:
                prox, pg = fonte_de(g + 1)
                if prox is not fonte or pg != pagina + (g + 1 - f):
                    break
                g += 1
            antes = len(doc)
            try:
                doc.insert_pdf(fonte, from_page=pagina, to_page=pagina + (g - f))
            except Exception as erro:
                if fonte is avisos_pdf:
                    raise
                while len(doc) > antes:
                    doc.delete_page(len(doc) - 1)
                log.warning("  %s não puderam ser incluídas: %s", _fls(range(f, g + 1)),
                            str(erro)[:160])
                falhas = [(x, "I", origem[x][3]) for x in range(f, g + 1)]
                with fitz.open("pdf", paginas_de_aviso(falhas)) as extra:
                    doc.insert_pdf(extra)
                ausentes.update({x: "I" for x in range(f, g + 1)})
            f = g + 1
        if len(doc) != ultima:
            raise RuntimeError(f"a montagem saiu com {len(doc)} páginas para {ultima} folhas")
        ausentes = dict(sorted(ausentes.items()))
        sumario, manifesto = acabamento(ausentes, notas) if acabamento else ([], None)
        _acabar(doc, sumario, manifesto)
        _salvar_atomico(doc, destino)
        return Montagem(ultima, ausentes, notas)
    finally:
        for aberto in (doc, avisos_pdf, *abertos.values()):
            if aberto is not None:
                try:
                    aberto.close()
                except Exception:
                    pass


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
