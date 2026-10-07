"""Lê a relação de processos de quase qualquer arquivo: Excel, Word, PDF, texto.

Herdado do Assessor SAJ (app/esaj/planilha.py), que já tinha apanhado de
arquivo de verdade. O que se aprendeu lá continua valendo:

1. A EXTENSÃO MENTE. O ".xls" que os sistemas do Judiciário exportam é,
   quase sempre, uma tabela HTML. O arquivo é reconhecido pelos primeiros
   bytes, não pelo fim do nome.
2. O EXCEL COME O ZERO DA FRENTE. CNJ guardado como número fica com 19
   dígitos; a célula numérica de 19 dígitos recebe o zero de volta.
3. NÚMERO GRANDE VIRA NOTAÇÃO CIENTÍFICA, e str(7.0e18) não contém número
   de processo nenhum. A célula numérica vira inteiro antes de ser lida.
4. O EXCEL CORROMPE O CNJ GUARDADO COMO NÚMERO: o double de 64 bits não
   comporta 20 dígitos, e os últimos saem trocados - e o número corrompido
   ainda parece um número de processo. Por isso a célula numérica que já
   não guarda o inteiro exato (de 2**53 em diante - todo CNJ como número)
   nunca entra no lote, mesmo que o dígito verificador confira: ele é
   módulo 97, e cerca de 1 em 97 números corrompidos passaria por ele. O
   inteiro exato (raro: XML montado à mão) só entra se o dígito conferir.
   Sem isso, o programa baixaria processo alheio sem ninguém perceber.
5. PLANILHA COM FÓRMULA que o Excel nunca abriu não tem valor gravado:
   tenta-se de novo pelo texto das fórmulas.

E o que foi corrigido em relação à base (todos com teste):
  * o sufixo de dependente só é aceito com barra ("/01"): "... - 2ª Vara"
    deixava de ser lido como o incidente 02; e, mesmo com a barra, não
    quando o que vem depois é texto ("... / 1ª Vara", ".../2ª Vara",
    "... / 3 réus" continuam sendo os autos principais - cnj._PADRAO);
  * o Word é lido na ordem do documento (parágrafos e tabelas
    intercalados), e não todos os parágrafos antes de todas as tabelas;
  * várias colunas de número: se uma delas se chama "processo" (e não
    "processo de origem", "principal"...), só ela é lida - mesmo que só
    traga números corrompidos (item 4); vazia, a linha inteira é lida, menos
    as colunas de outro processo;
  * abas ocultas da planilha são ignoradas (no .ods também, e na leitura
    direta do XML do .xlsx); os bytes crus da planilha, que as trazem, não
    são lidos como texto;
  * o .xlsx que o openpyxl não lê inteiro (célula fora do padrão, variante
    do formato) é lido direto do XML, com as mesmas regras;
  * arquivo em UTF-16 (BOM) é lido;
  * senha de processo sigiloso na lista ("número ; senha" ou coluna
    "senha") fica associada ao número, com a mesma grafia usada no
    download;
  * nada de estado global: tudo volta no objeto Leitura.
"""

from __future__ import annotations

import csv
import html
import logging
import posixpath
import re
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from . import cnj, sistema

log = logging.getLogger("listas")

EXTENSOES = (".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".txt", ".htm",
             ".html", ".pdf", ".docx")
TIPOS_ARQUIVO = [
    ("Relação de processos", " ".join("*" + e for e in EXTENSOES)),
    ("Planilhas", "*.xlsx *.xlsm *.xls *.ods *.csv"),
    ("Documentos", "*.docx *.pdf *.txt"),
    ("Todos os arquivos", "*.*"),
]
CODIFICACOES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
LNLN = "\n\n"

# Cabeçalho da coluna que traz o número do processo...
_COLUNA_NUMERO = re.compile(r"processo|n[uú]mero|autos|\bn[º°o]\b|cnj", re.I)
# ...e o que, mesmo com "processo" no nome, é OUTRO processo.
_COLUNA_OUTRO = re.compile(
    r"origem|principal|apens|refer[eê]ncia|vinculad|relacionad|anterior|"
    r"originári|piloto|paradigma", re.I)
_COLUNA_SENHA = re.compile(r"senha", re.I)

# "número ; senha" - a linha inteira tem de ser só isso, para a segunda
# coluna de uma tabela ("João da Silva", "Audiência") não virar senha.
_SENHA_DEPOIS = re.compile(
    r"^\s*[;|\t:]\s*(?:senhas?\s*[:=]\s*)?([^\s;|\t]{3,40})\s*$", re.I)
_ANTES_DO_NUMERO = re.compile(r"^\s*(?:[-•*]|\d{1,4}[.)º°]?)?\s*$")


class ListaInvalida(RuntimeError):
    """O arquivo não pode ser lido, ou não tem número de processo dentro."""


@dataclass
class Leitura:
    """O resultado de uma leitura: o que entra, e o que a tela deve avisar."""
    processos: list[cnj.Numero] = field(default_factory=list)
    senhas: dict[str, str] = field(default_factory=dict)   # Numero.formatado -> senha
    corrompidos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    formato: str = ""
    origem: str = ""

    @property
    def digito_errado(self) -> list[cnj.Numero]:
        return [n for n in self.processos if not n.digito_confere]

    def juntar(self, outra: "Leitura") -> "Leitura":
        """Acrescenta outra leitura, sem repetir processo."""
        vistos = {cnj.chave(n) for n in self.processos}
        for n in outra.processos:
            if cnj.chave(n) not in vistos:
                vistos.add(cnj.chave(n))
                self.processos.append(n)
        self.senhas.update(outra.senhas)
        self.corrompidos += outra.corrompidos
        self.avisos += outra.avisos
        return self


# ----------------------------------------------------------------- utilidades
def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _texto_da_celula(valor) -> str:
    """O conteúdo da célula em texto que o buscador consiga ler."""
    if valor is None or isinstance(valor, bool):
        return ""
    if isinstance(valor, int):
        digitos = str(abs(valor))
    elif isinstance(valor, float):
        if valor != valor or valor in (float("inf"), float("-inf")):
            return ""
        inteiro = int(valor)
        if inteiro != valor:
            return repr(valor)
        digitos = str(abs(inteiro))
    else:
        return str(valor)
    if len(digitos) == 19:          # o Excel comeu o zero da frente
        digitos = "0" + digitos
    return digitos


# Célula numérica (float) que não guarda mais o inteiro exato: de 2**53 em
# diante, o espaçamento entre dois doubles vizinhos passa de 1. O CNJ como
# número tem de 18 a 20 dígitos (o zero da frente some) - sempre nessa faixa.
# Acima de 10**20 não há CNJ possível, e a célula segue o caminho comum.
_FLOAT_INEXATO = float(2 ** 53)
_ALEM_DO_CNJ = 1e20


class _Coletor:
    """Junta números e senhas, na ordem, sem repetir."""

    def __init__(self) -> None:
        self.leitura = Leitura()
        self._vistos: set[str] = set()

    def numero(self, n: cnj.Numero, senha: str = "") -> None:
        k = cnj.chave(n)
        if k not in self._vistos:
            self._vistos.add(k)
            self.leitura.processos.append(n)
        if senha:
            self.leitura.senhas[n.formatado] = senha

    def absorver(self, outro: "_Coletor") -> None:
        """O que outra leitura (feita à parte, para poder ser descartada) achou."""
        for n in outro.leitura.processos:
            self.numero(n, outro.leitura.senhas.get(n.formatado, ""))
        self.leitura.corrompidos += outro.leitura.corrompidos
        self.leitura.avisos += outro.leitura.avisos

    def texto(self, texto: str, senha: str = "") -> int:
        achados = cnj.extrair_todos(texto)
        for n in achados:
            self.numero(n, senha if len(achados) == 1 else "")
        return len(achados)

    def linha_livre(self, linha: str) -> None:
        """Linha de texto colado: 'numero ; senha' associa a senha."""
        achados = cnj.extrair_todos(linha)
        senha = ""
        if len(achados) == 1:
            m = cnj._PADRAO.search(linha)
            depois = _SENHA_DEPOIS.match(linha[m.end():]) if m else None
            if m and depois and _ANTES_DO_NUMERO.match(linha[:m.start()]):
                candidata = depois.group(1).strip()
                if len(_digitos(candidata)) < 15:   # não é outro número CNJ
                    senha = candidata
        for n in achados:
            self.numero(n, senha)

    def celula(self, valor) -> None:
        texto = _texto_da_celula(valor)
        if not texto:
            return
        if isinstance(valor, float) and _FLOAT_INEXATO <= abs(valor) < _ALEM_DO_CNJ:
            # Item 4 do docstring. Acima de 2**53 o double não guarda mais o
            # inteiro exato (o Excel, aliás, só guarda 15 algarismos): o CNJ
            # lido daqui já não é o da relação. O dígito verificador não basta
            # como filtro - é módulo 97, e cerca de 1 em 97 números
            # corrompidos ainda confere (com o foro, ou até o tribunal,
            # trocado). Nada desta célula entra no lote; ela é contada entre
            # os corrompidos (inclusive o número com "00" na frente, que nem
            # chega a parecer um CNJ), para o aviso "formate como Texto".
            achados = cnj.extrair_todos(texto)
            self.leitura.corrompidos.extend(
                [n.formatado for n in achados] or [texto])
            return
        # Inteiro de verdade (XML montado à mão, com todos os dígitos) é
        # exato: vale o dígito verificador, como antes.
        numerico = isinstance(valor, (int, float)) and not isinstance(valor, bool)
        for n in cnj.extrair_todos(texto):
            if numerico and not n.digito_confere:
                self.leitura.corrompidos.append(n.formatado)
                continue
            self.numero(n)


# -------------------------------------------------------------- reconhecer
def formato(caminho: Path) -> str:
    """O que o arquivo É, pelos primeiros bytes - não pelo nome."""
    try:
        with open(caminho, "rb") as f:
            cabeca = f.read(4096)
    except OSError as erro:
        raise ListaInvalida(f"não consegui abrir o arquivo: {str(erro)[:120]}") from erro

    if cabeca.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(caminho) as z:
                nomes = set(z.namelist())
        except Exception:
            return "zip-quebrado"
        if "content.xml" in nomes:
            return "ods"
        if any(n.startswith("word/") for n in nomes):
            return "docx"
        if any(n.startswith("xl/") for n in nomes):
            return "xlsx"
        return "zip-desconhecido"
    if cabeca.startswith(b"\xd0\xcf\x11\xe0"):
        # OLE: .xls de verdade - ou um .doc antigo do Word, com a mesma cara.
        return "doc" if b"W\x00o\x00r\x00d\x00D\x00o\x00c" in cabeca or \
            caminho.suffix.lower() == ".doc" else "xls"
    if cabeca.startswith(b"%PDF"):
        return "pdf"
    texto = _decodificar(cabeca)[:800].lower()
    if "<html" in texto or "<table" in texto or "<!doctype html" in texto:
        return "html"
    return "texto"


def _decodificar(dados: bytes) -> str:
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dados.decode("utf-16", errors="replace")
    # UTF-16 sem BOM: metade dos bytes é zero.
    if len(dados) > 20 and dados[1:200:2].count(0) > 0.4 * len(dados[1:200:2]):
        return dados.decode("utf-16-le", errors="replace")
    for codificacao in CODIFICACOES:
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


def _sem_marcacao(bruto: str) -> str:
    # Etiqueta vira espaço: dois números vizinhos não podem se colar.
    sem = re.sub(r"<[^>]+>", " ", bruto)
    return (sem.replace("&nbsp;", " ").replace("&#160;", " ")
               .replace("&amp;", "&"))


# --------------------------------------------------------------- planilhas
def _cabecalho(linhas: list[tuple]) -> tuple[int | None, int | None, frozenset[int]]:
    """Nas 10 primeiras linhas, o cabeçalho: a coluna do número, a da senha,
    se houver, e as que ele diz serem de OUTRO processo ("Processo de
    origem", "Principal"...).

    O relatório exportado costuma trazer um título antes do cabeçalho
    ("Relação de processos", numa célula só, mesclada sobre as outras), e o
    título também tem "processo" no texto: a linha com mais de uma célula
    preenchida, e sem número de processo dentro, passa na frente dele. Sem
    nenhuma linha assim, vale a primeira com o rótulo, como antes.
    """
    primeira = None
    for linha in linhas[:10]:
        num = senha = None
        outras: set[int] = set()
        preenchidas = 0
        com_numero = False
        for i, valor in enumerate(linha):
            rotulo = _texto_da_celula(valor).strip()
            if not rotulo:
                continue
            preenchidas += 1
            if cnj.extrair_todos(rotulo):
                com_numero = True
                continue
            if not isinstance(valor, str):
                continue
            if _COLUNA_OUTRO.search(rotulo):
                outras.add(i)
            if num is None and _COLUNA_NUMERO.search(rotulo) and not _COLUNA_OUTRO.search(rotulo):
                num = i
            elif senha is None and _COLUNA_SENHA.search(rotulo):
                senha = i
        if num is None:
            continue
        achado = (num, senha, frozenset(outras))
        if preenchidas > 1 and not com_numero:
            return achado
        if primeira is None:
            primeira = achado
    return primeira or (None, None, frozenset())


def _escolher_coluna(linhas: list[tuple]) -> tuple[int | None, int | None]:
    """Nas 10 primeiras linhas, a coluna do número e a da senha, se houver."""
    return _cabecalho(linhas)[:2]


def _ler_linhas(col: _Coletor, linhas: list[tuple], aviso_aba: str) -> None:
    coluna, coluna_senha, outras = _cabecalho(linhas)
    if coluna is not None:
        antes = len(col.leitura.processos)
        corrompidos = len(col.leitura.corrompidos)
        for linha in linhas:
            valor = linha[coluna] if coluna < len(linha) else None
            senha = ""
            if coluna_senha is not None and coluna_senha < len(linha):
                senha = _texto_da_celula(linha[coluna_senha]).strip()
            n_antes = len(col.leitura.processos)
            col.celula(valor)
            if senha and len(col.leitura.processos) > n_antes:
                col.leitura.senhas[col.leitura.processos[-1].formatado] = senha
        # A coluna do número trouxe número - mesmo que só os corrompidos pelo
        # Excel (item 4): as outras colunas não são lidas. Varrer a linha
        # inteira poria no lote o "Processo de origem" (outro processo) no
        # lugar dos números que a relação pede.
        if len(col.leitura.processos) > antes or len(col.leitura.corrompidos) > corrompidos:
            return
    # Sem coluna reconhecida (ou ela veio vazia): varre a linha inteira -
    # menos as colunas que o cabeçalho diz serem de outro processo.
    for linha in linhas:
        for i, valor in enumerate(linha):
            if i not in outras:
                col.celula(valor)


def _de_xlsx(caminho: Path, col: _Coletor) -> None:
    from openpyxl import load_workbook

    abriu = False

    def tentar(valores: bool, alvo: _Coletor) -> int:
        """Lê as abas visíveis em 'alvo' e diz quantas leu."""
        nonlocal abriu
        # Em memória: o openpyxl recusa pela extensão, e aqui a extensão já
        # se mostrou mentirosa; e no modo read_only ele lê as abas depois.
        try:
            livro = load_workbook(BytesIO(caminho.read_bytes()),
                                  read_only=True, data_only=valores)
        except Exception as erro:
            raise ListaInvalida(
                f"não consegui abrir a planilha: {str(erro)[:120]}") from erro
        abriu = True
        lidas = 0
        try:
            for nome in livro.sheetnames:
                try:
                    aba = livro[nome]
                    if getattr(aba, "sheet_state", "visible") != "visible":
                        alvo.leitura.avisos.append(f"aba oculta '{nome}' ignorada")
                        continue
                    if not hasattr(aba, "iter_rows"):      # aba de gráfico: sem células
                        continue
                    # No modo read_only, o openpyxl lê só até a "dimensão" que
                    # o arquivo declara - e as planilhas exportadas por
                    # sistemas (o próprio SAJ, relatórios, Apache POI) costumam
                    # declarar "A1": lia-se a primeira linha e mais nada, e a
                    # relação inteira era recusada ("nenhum número de processo").
                    redefinir = getattr(aba, "reset_dimensions", None)
                    if callable(redefinir):
                        redefinir()
                    linhas = list(aba.iter_rows(values_only=True))
                except Exception as erro:
                    # No modo read_only, a célula só é convertida aqui: o valor
                    # com vírgula decimal ("1500,50", de exportador com o
                    # Windows em português), o texto gravado sem o tipo, a data
                    # fora do padrão ISO - em qualquer coluna - derrubavam a
                    # leitura inteira, com a frase do openpyxl em inglês.
                    raise ListaInvalida(
                        f"não consegui ler a aba '{nome}': {str(erro)[:120]}") from erro
                _ler_linhas(alvo, linhas, nome)
                lidas += 1
        finally:
            try:
                livro.close()
            except Exception:
                pass
        return lidas

    primeira = _Coletor()
    erro_openpyxl: ListaInvalida | None = None
    lidas = 0
    try:
        lidas = tentar(True, primeira)
    except ListaInvalida as erro:
        erro_openpyxl = erro
    if erro_openpyxl is None and lidas and not primeira.leitura.processos:
        # De novo, pelo texto das fórmulas. As células numéricas e as abas
        # ocultas são as mesmas da primeira leitura: os corrompidos e os
        # avisos não são contados de novo (a tela diria o dobro de linhas).
        formulas = _Coletor()
        try:
            tentar(False, formulas)
        except ListaInvalida:
            pass
        for n in formulas.leitura.processos:
            primeira.numero(n, formulas.leitura.senhas.get(n.formatado, ""))
    if erro_openpyxl is None and lidas and (primeira.leitura.processos
                                            or primeira.leitura.corrompidos):
        col.absorver(primeira)
        return
    # O openpyxl recusou o arquivo (variantes legítimas do formato, estilos
    # que ele não entende), parou numa célula fora do padrão, não achou aba
    # (o Strict Open XML abre com zero abas) ou não achou número nas abas
    # visíveis: a planilha é lida de novo, direto do XML, aba por aba e
    # coluna por coluna. O que a primeira leitura juntou até parar fica de
    # fora: nada conta duas vezes. Se o openpyxl abriu a pasta de trabalho,
    # ele sabia quais abas são ocultas: a leitura direta, sem esse mapa, não
    # as distinguiria, e não é feita.
    xml = _Coletor()
    lidas_xml = _de_xlsx_xml(caminho, xml, so_com_mapa=abriu)
    if (xml.leitura.processos or xml.leitura.corrompidos
            or erro_openpyxl is not None or not lidas):
        col.absorver(xml)
    else:
        col.absorver(primeira)
    if not col.leitura.processos and not col.leitura.corrompidos \
            and erro_openpyxl is not None and not lidas_xml:
        raise erro_openpyxl


# ------------------------------------------------- .xlsx lido direto do XML
_RE_CELULA_XML = re.compile(rb"<(?:\w+:)?(?:t|v)(?:\s[^>]*)?>([^<]*)</(?:\w+:)?(?:t|v)>")
_RE_SI_XML = re.compile(rb"<(?:\w+:)?si(?:\s[^>]*)?(?:/>|>(.*?)</(?:\w+:)?si>)", re.S)
_RE_FONETICA_XML = re.compile(rb"<(?:\w+:)?rPh\b.*?</(?:\w+:)?rPh>", re.S)
_RE_T_XML = re.compile(rb"<(?:\w+:)?t(?:\s[^>]*)?>([^<]*)</(?:\w+:)?t>")
_RE_REFERENCIA = re.compile(r"([A-Za-z]{1,3})\d+$")
_RE_INTEIRO = re.compile(r"[+-]?\d+")
_MAX_COLUNAS = 16384            # a última coluna do Excel (XFD)


def _local(tag: str) -> str:
    """O nome do elemento sem o espaço de nomes (o Strict Open XML usa outro)."""
    return tag.rsplit("}", 1)[-1]


def _texto_xml(bruto: bytes) -> str:
    return html.unescape(bruto.decode("utf-8", errors="ignore"))


def _texto_ooxml(el) -> str:
    """O texto de um <si> ou <is>: o <t> direto ou os <t> dos trechos <r>
    (a transcrição fonética, <rPh>, fica de fora)."""
    partes = []
    for filho in el:
        nome = _local(filho.tag)
        if nome == "t":
            partes.append(filho.text or "")
        elif nome == "r":
            partes += [t.text or "" for t in filho if _local(t.tag) == "t"]
    return "".join(partes)


def _relacoes(z: zipfile.ZipFile, parte: str) -> list[tuple[str, str, str]]:
    """(Id, Type, parte de destino) das relações de uma parte do pacote."""
    pasta, nome = posixpath.split(parte)
    saida = []
    for rel in ET.fromstring(z.read(posixpath.join(pasta, "_rels", nome + ".rels"))).iter():
        if _local(rel.tag) != "Relationship" or rel.get("TargetMode") == "External":
            continue
        alvo = (rel.get("Target") or "").replace("\\", "/")
        destino = alvo.lstrip("/") if alvo.startswith("/") else \
            posixpath.normpath(posixpath.join(pasta, alvo))
        saida.append((rel.get("Id") or "", rel.get("Type") or "", destino))
    return saida


def _mapa_xlsx(z: zipfile.ZipFile,
               nomes: list[str]) -> tuple[list[tuple[str, bool, str]], str, bool]:
    """As abas de células, (nome, oculta, parte do ZIP) na ordem da pasta de
    trabalho, a parte dos textos compartilhados e se o mapa foi lido - sem
    ele, vão todas as abas, sem saber quais são ocultas."""
    existentes = set(nomes)
    compartilhadas = next((n for n in nomes if n.lower() == "xl/sharedstrings.xml"), "")
    try:
        livro_parte = next((destino for _, tipo, destino in _relacoes(z, "")
                            if tipo.endswith("/officeDocument")), "xl/workbook.xml")
    except Exception:
        livro_parte = "xl/workbook.xml"
    try:
        alvos: dict[str, str] = {}
        for rid, tipo, destino in _relacoes(z, livro_parte):
            if tipo.endswith("/worksheet"):         # a aba de gráfico não tem células
                alvos[rid] = destino
            elif tipo.endswith("/sharedStrings") and destino in existentes:
                compartilhadas = destino
        abas = []
        for aba in ET.fromstring(z.read(livro_parte)).iter():
            if _local(aba.tag) != "sheet":
                continue
            rid = next((v for k, v in aba.attrib.items() if _local(k) == "id"), "")
            parte = alvos.get(rid, "")
            if parte in existentes:
                abas.append((aba.get("name") or Path(parte).stem,
                             (aba.get("state") or "visible") != "visible", parte))
        if abas:
            return abas, compartilhadas, True
    except Exception as erro:
        log.debug("mapa das abas da planilha ilegível: %s", type(erro).__name__)
    # Sem o mapa (workbook.xml ilegível ou sem as relações): todas as abas,
    # na ordem do nome.
    def ordem(nome: str):
        return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", nome)]
    planilhas = sorted((n for n in nomes if n.lower().startswith("xl/worksheets/")
                        and n.lower().endswith(".xml")), key=ordem)
    return [(Path(p).stem, False, p) for p in planilhas], compartilhadas, False


def _textos_compartilhados(dados: bytes) -> list[str]:
    try:
        return [_texto_ooxml(si) for si in ET.fromstring(dados) if _local(si.tag) == "si"]
    except ET.ParseError:
        # XML malformado: pelo texto, sem perder a posição de cada <si>.
        return ["".join(_texto_xml(t) for t in _RE_T_XML.findall(
                    _RE_FONETICA_XML.sub(b"", m.group(1) or b"")))
                for m in _RE_SI_XML.finditer(dados)]


def _valor_xml(celula, compartilhadas: list[str]):
    """O valor de uma célula <c>, como o openpyxl o daria - mas sem recusar
    o que foge do padrão: o que não é número segue como texto."""
    tipo = celula.get("t") or "n"
    valor = formula = em_linha = None
    for filho in celula:
        nome = _local(filho.tag)
        if nome == "v":
            valor = filho.text or ""
        elif nome == "is":
            em_linha = _texto_ooxml(filho)
        elif nome == "f":
            formula = filho.text or ""
    if tipo == "inlineStr" or (em_linha is not None and valor is None):
        return em_linha or ""
    if valor is None:
        return formula          # fórmula que o Excel nunca calculou (item 5)
    if tipo == "s":
        try:
            return compartilhadas[int(valor)]
        except (ValueError, IndexError):
            return None
    if tipo in ("str", "d"):
        return valor
    if tipo in ("b", "e"):
        return None
    bruto = valor.strip()
    try:
        return int(bruto) if _RE_INTEIRO.fullmatch(bruto) else float(bruto)
    except ValueError:
        return bruto            # "1500,50", o número de processo sem o tipo


def _linhas_xml(dados: bytes, compartilhadas: list[str]) -> list[tuple]:
    linhas = []
    for linha in ET.fromstring(dados).iter():
        if _local(linha.tag) != "row":
            continue
        celulas: dict[int, object] = {}
        proxima = 0
        for celula in linha:
            if _local(celula.tag) != "c":
                continue
            m = _RE_REFERENCIA.match(celula.get("r") or "")
            indice = proxima
            if m:
                indice = 0
                for letra in m.group(1).upper():
                    indice = indice * 26 + ord(letra) - 64
                indice -= 1
            if not 0 <= indice < _MAX_COLUNAS:
                indice = proxima
            proxima = indice + 1
            celulas[indice] = _valor_xml(celula, compartilhadas)
        linhas.append(tuple(celulas.get(i) for i in range(max(celulas) + 1))
                      if celulas else ())
    return linhas


def _de_xlsx_xml(caminho: Path, col: _Coletor, so_com_mapa: bool = False) -> int:
    """A planilha lida direto do XML, sem o openpyxl, e do mesmo jeito que a
    leitura normal: só as abas visíveis, e a coluna do número escolhida pelo
    cabeçalho. Devolve quantas abas leu."""
    lidas = 0
    try:
        with zipfile.ZipFile(caminho) as z:
            nomes = z.namelist()
            if "xl/workbook.bin" in nomes:
                raise ListaInvalida(
                    "esta é uma pasta de trabalho binária do Excel (.xlsb), que o "
                    "programa não lê. No Excel, use Salvar como > Pasta de Trabalho "
                    "do Excel (.xlsx), ou CSV, e escolha de novo.")
            abas, parte_compartilhadas, mapeadas = _mapa_xlsx(z, nomes)
            if so_com_mapa and not mapeadas:
                log.debug("leitura direta do XML dispensada: abas sem o mapa da pasta de trabalho")
                return 0
            compartilhadas: list[str] = []
            if parte_compartilhadas:
                try:
                    compartilhadas = _textos_compartilhados(z.read(parte_compartilhadas))
                except Exception as erro:
                    log.debug("textos compartilhados ilegíveis: %s", type(erro).__name__)
            for nome, oculta, parte in abas:
                if oculta:
                    col.leitura.avisos.append(f"aba oculta '{nome}' ignorada")
                    continue
                try:
                    dados = z.read(parte)
                except Exception as erro:
                    log.debug("aba ilegível na planilha: %s", type(erro).__name__)
                    continue
                lidas += 1
                try:
                    _ler_linhas(col, _linhas_xml(dados, compartilhadas), nome)
                except ET.ParseError:
                    # XML malformado: só o texto das células desta aba. O número
                    # gravado como número não tem os 20 dígitos do CNJ de forma
                    # confiável e fica de fora.
                    for m in _RE_CELULA_XML.finditer(dados):
                        texto = _texto_xml(m.group(1))
                        if re.search(r"\D", texto.strip()):
                            col.texto(texto)
    except ListaInvalida:
        raise
    except Exception as erro:
        log.debug("leitura direta do XML da planilha falhou: %s", type(erro).__name__)
    return lidas


def _de_xls(caminho: Path, col: _Coletor) -> None:
    import xlrd

    try:
        cabeca = caminho.read_bytes()[:1_000_000]
    except OSError:
        cabeca = b""
    if "EncryptedPackage".encode("utf-16-le") in cabeca:
        # .xlsx com senha de abertura: o Excel o guarda dentro de um arquivo
        # OLE, com a mesma cara de um .xls antigo.
        raise ListaInvalida(
            "esta planilha está protegida por senha de abertura, e o programa não a "
            "abre. No Excel, abra-a, tire a senha (Arquivo > Informações > Proteger "
            "pasta de trabalho > Criptografar com senha, e apague a senha), salve e "
            "escolha de novo.")
    try:
        livro = xlrd.open_workbook(str(caminho))
    except Exception as erro:
        raise ListaInvalida(
            f"não consegui abrir a planilha antiga: {str(erro)[:120]}") from erro
    for aba in livro.sheets():
        if getattr(aba, "visibility", 0):
            col.leitura.avisos.append(f"aba oculta '{aba.name}' ignorada")
            continue
        linhas = [tuple(aba.row_values(i)) for i in range(aba.nrows)]
        _ler_linhas(col, linhas, aba.name)


_NS_ODS = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
}
_MAX_COLUNAS_ODS = 1024         # a última coluna das versões antigas do LibreOffice (AMJ)


def _valor_ods(celula):
    o = _NS_ODS["office"]
    if celula.get(f"{{{o}}}value-type") == "float" and celula.get(f"{{{o}}}value"):
        try:
            return float(celula.get(f"{{{o}}}value"))
        except ValueError:
            pass
    return " ".join("".join(p.itertext()) for p in celula)


def _de_ods(caminho: Path, col: _Coletor) -> None:
    try:
        with zipfile.ZipFile(caminho) as z:
            raiz = ET.fromstring(z.read("content.xml"))
    except Exception as erro:
        raise ListaInvalida(f"não consegui abrir o arquivo .ods: {str(erro)[:120]}") from erro
    t, s = _NS_ODS["table"], _NS_ODS["style"]
    celulas = (f"{{{t}}}table-cell", f"{{{t}}}covered-table-cell")
    # Aba oculta: o estilo dela diz table:display="false".
    ocultos = {estilo.get(f"{{{s}}}name") for estilo in raiz.iter(f"{{{s}}}style")
               if estilo.get(f"{{{s}}}name") and any(
                   p.get(f"{{{t}}}display") == "false"
                   for p in estilo.iter(f"{{{s}}}table-properties"))}
    for tabela in raiz.iter(f"{{{t}}}table"):
        nome = tabela.get(f"{{{t}}}name", "")
        if tabela.get(f"{{{t}}}style-name") in ocultos:
            col.leitura.avisos.append(f"aba oculta '{nome}' ignorada")
            continue
        linhas = []
        for linha in tabela.iter(f"{{{t}}}table-row"):
            # O LibreOffice grava as células vizinhas iguais (as vazias,
            # sobretudo) como uma só, com number-columns-repeated, e a célula
            # coberta por uma mescla com outro nome: contadas uma vez, elas
            # deslocavam as colunas seguintes, e a "Senha" lia a vizinha.
            valores: list = []
            vazias = 0
            for celula in linha:
                if celula.tag not in celulas:
                    continue
                try:
                    repete = int(celula.get(f"{{{t}}}number-columns-repeated") or 1)
                except ValueError:
                    repete = 1
                repete = max(1, min(repete, _MAX_COLUNAS_ODS))
                valor = _valor_ods(celula)
                if valor in ("", None):
                    # só ocupam lugar se vier algo depois
                    vazias = min(vazias + repete, _MAX_COLUNAS_ODS)
                    continue
                valores += [""] * vazias + [valor] * repete
                vazias = 0
                if len(valores) >= _MAX_COLUNAS_ODS:
                    break
            linhas.append(tuple(valores[:_MAX_COLUNAS_ODS]))
        _ler_linhas(col, linhas, nome)


# --------------------------------------------------------------- documentos
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _texto_do_elemento(el) -> str:
    partes = []
    for x in el.iter():
        if x.tag == f"{_W}t" and x.text:
            partes.append(x.text)
        elif x.tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
            partes.append(" ")
    return "".join(partes)


def _blocos_word(el):
    """Parágrafos e tabelas do Word NA ORDEM DO DOCUMENTO.

    Devolve ('p', texto) ou ('tabela', [linhas]). Controles de conteúdo
    (w:sdt) e outros invólucros são abertos; a tabela vem por linha, para a
    coluna do número (e a da senha) ser reconhecida como numa planilha.
    """
    for filho in el:
        tag = filho.tag
        if tag == f"{_W}p":
            yield "p", _texto_do_elemento(filho)
        elif tag == f"{_W}tbl":
            linhas = []
            for tr in filho.iter(f"{_W}tr"):
                celulas = [_texto_do_elemento(tc).strip()
                           for tc in tr if tc.tag == f"{_W}tc"]
                linhas.append(tuple(celulas))
            yield "tabela", linhas
        else:
            yield from _blocos_word(filho)


def _de_docx(caminho: Path, col: _Coletor) -> None:
    try:
        with zipfile.ZipFile(caminho) as z:
            nomes = z.namelist()
            corpo = ET.fromstring(z.read("word/document.xml"))
            extras = [ET.fromstring(z.read(n)) for n in sorted(nomes)
                      if re.match(r"word/(header|footer)\d*\.xml$", n)]
    except Exception as erro:
        raise ListaInvalida(f"não consegui abrir o documento: {str(erro)[:120]}") from erro
    for tipo, conteudo in _blocos_word(corpo):
        if tipo == "p":
            col.linha_livre(conteudo)
        else:
            _ler_linhas(col, conteudo, "tabela")
    for raiz in extras:
        col.texto(_texto_do_elemento(raiz))


def _de_pdf(caminho: Path, col: _Coletor) -> None:
    try:
        try:
            import pymupdf
        except ImportError:  # pragma: no cover
            import fitz as pymupdf
        with pymupdf.open(str(caminho)) as doc:
            texto = "\n".join(p.get_text("text") for p in doc)
    except Exception as erro:
        raise ListaInvalida(f"não consegui abrir o PDF: {str(erro)[:120]}") from erro
    # Número quebrado no fim da linha do PDF: "8.02.\n0001" volta a ser um só.
    texto = re.sub(r"([.\-])\s*\n\s*(?=\d)", r"\1", texto)
    for linha in texto.splitlines():
        col.linha_livre(linha)


def _de_html(caminho: Path, col: _Coletor) -> None:
    bruto = _decodificar(caminho.read_bytes())
    linhas = re.split(r"(?i)</tr>|<br\s*/?>|</p>", bruto)
    for linha in linhas:
        col.texto(_sem_marcacao(linha))


def _de_texto(caminho: Path, col: _Coletor) -> None:
    bruto = _decodificar(caminho.read_bytes())
    # Como no texto colado (ler_texto): com tabulação, é tabela - o "Salvar
    # como > Texto Unicode" do Excel é um .txt assim -, e a segunda coluna só
    # é a senha se o cabeçalho disser "Senha". Lida linha a linha, a coluna
    # vizinha ("Ativo", a classe, a vara) virava a senha do processo sigiloso.
    ler_texto_em(col, bruto, csv_provavel=caminho.suffix.lower() in (".csv", ".tsv")
                 or "\t" in bruto)


def ler_texto_em(col: _Coletor, bruto: str, csv_provavel: bool = False) -> None:
    if csv_provavel or (";" in bruto[:2000] and "\n" in bruto):
        try:
            dialeto = csv.Sniffer().sniff(bruto[:4000], delimiters=";,\t|")
            linhas = [tuple(l) for l in csv.reader(bruto.splitlines(), dialeto)]
            # Sem cabeçalho, "número ; senha" digitado linha a linha vai para a
            # leitura por linha, a que sabe associar a senha ao número. Tabela
            # colada do Excel (tabulação) não: sem o cabeçalho "Senha", a
            # segunda coluna é outra coisa (classe, vara, parte).
            if linhas and max(len(l) for l in linhas) > 1 and (
                    dialeto.delimiter == "\t" or _escolher_coluna(linhas)[0] is not None):
                _ler_linhas(col, linhas, "csv")
                return
        except csv.Error:
            pass
    for linha in bruto.splitlines():
        limpa = linha.strip()
        if limpa and limpa[0] in "#;":
            continue
        col.linha_livre(limpa)


_LEITORES = {"xlsx": _de_xlsx, "xls": _de_xls, "ods": _de_ods, "html": _de_html,
             "pdf": _de_pdf, "docx": _de_docx, "texto": _de_texto}
_NOMES = {"xlsx": "planilha do Excel", "xls": "planilha antiga do Excel",
          "ods": "planilha do LibreOffice", "html": "tabela em HTML",
          "pdf": "PDF", "docx": "documento do Word", "texto": "texto",
          "doc": "documento antigo do Word (.doc)"}


# ------------------------------------------------------------------- entrada
def ler_arquivo(caminho: Path | str) -> Leitura:
    """Os processos do arquivo, na ordem em que aparecem, sem repetir."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise ListaInvalida(f"não encontrei o arquivo {caminho.name}")
    if caminho.stat().st_size == 0:
        raise ListaInvalida(f"o arquivo {caminho.name} está vazio.")

    tipo = formato(caminho)
    log.info("Relação %s: reconhecida como %s.", caminho.name, _NOMES.get(tipo, tipo))
    if tipo in ("zip-quebrado", "zip-desconhecido"):
        raise ListaInvalida(
            f"o arquivo {caminho.name} parece danificado. Abra-o no Excel ou "
            "no Word e salve de novo (.xlsx ou .docx).")

    col = _Coletor()
    col.leitura.formato = _NOMES.get(tipo, tipo)
    col.leitura.origem = str(caminho)
    erro_leitor: Exception | None = None
    if tipo == "doc":
        # .doc do Word 97: o texto fica em UTF-16 dentro do arquivo OLE.
        dados = caminho.read_bytes()
        col.texto(dados.decode("utf-16-le", errors="ignore"))
        col.texto(dados.decode("latin-1", errors="ignore"))
    else:
        # Num coletor à parte: o leitor que para no meio não deixa um lote pela
        # metade.
        lido = _Coletor()
        try:
            _LEITORES.get(tipo, _de_texto)(caminho, lido)
        except ListaInvalida as erro:
            erro_leitor = erro
        except ImportError as erro:  # pragma: no cover - instalação incompleta
            erro_leitor = ListaInvalida(
                f"falta uma biblioteca para ler {_NOMES.get(tipo, tipo)} "
                f"({erro.name}). {sistema.REINSTALAR}")
        except OSError:
            raise           # arquivo preso ou sumido: a frase disso é de quem chamou
        except Exception as erro:
            # O erro da biblioteca (em inglês, e 'erro inesperado' na linha de
            # comando) não chega ao usuário: a frase diz o que fazer.
            log.warning("Relação %s: a leitura falhou (%s).", caminho.name, type(erro).__name__)
            erro_leitor = ListaInvalida(
                f"não consegui ler o arquivo {caminho.name} ({_NOMES.get(tipo, tipo)}): "
                "ele tem algo fora do padrão." + LNLN
                + "Abra-o no programa em que foi feito (o Excel, o Word), salve de "
                  "novo e escolha outra vez; ou copie os números e cole a lista na "
                  "tela de Processos.")
        else:
            col.absorver(lido)

    # Última tentativa: texto com outra cara. Custa pouco e salva o arquivo
    # com extensão trocada. Não vale para a planilha que o leitor dela abriu:
    # nos bytes crus estão também as abas ocultas e as colunas de outro
    # processo, que a leitura deixou de fora de propósito (o .xlsx, o .ods e
    # o .docx, ainda por cima, são ZIP - o texto deles não aparece nos bytes).
    if not col.leitura.processos and tipo not in ("texto", "xlsx", "ods", "docx") \
            and (tipo != "xls" or erro_leitor is not None):
        try:
            _de_texto(caminho, col)
        except Exception:
            pass

    if not col.leitura.processos:
        if col.leitura.corrompidos:
            quantas = len(col.leitura.corrompidos)
            linhas = "1 linha" if quantas == 1 else f"{quantas} linhas"
            raise ListaInvalida(
                "esta planilha guarda os números de processo como NÚMERO, e "
                "não como texto." + LNLN
                + "O Excel não comporta os 20 dígitos do CNJ num campo "
                  "numérico: ele arredonda os últimos, e o número deixa de ser "
                  f"o do processo. Foi o que aconteceu com {linhas} deste arquivo."
                + LNLN
                + "Para resolver: no Excel, formate a coluna dos números como "
                  "Texto e digite-os de novo, ou cole-os de um lugar onde estejam "
                  "como texto (o e-mail, o SAJ). Os algarismos que o Excel já "
                  "perdeu não voltam: salvar a relação como .csv não adianta."
                + LNLN
                + "Deixei de importá-los de propósito: importados assim, o "
                  "programa baixaria processo alheio.")
        if erro_leitor is not None:
            raise erro_leitor
        raise ListaInvalida(
            f"li o arquivo {caminho.name} ({_NOMES.get(tipo, tipo)}), mas não "
            "achei nenhum número de processo dentro." + LNLN
            + "Confira se os números estão no padrão CNJ "
              "(0000000-00.0000.0.00.0000). Número dentro de imagem colada "
              "não pode ser lido.")
    return col.leitura


def ler_texto(texto: str) -> Leitura:
    """Lista colada na tela (ou copiada do Excel, que chega em colunas)."""
    col = _Coletor()
    col.leitura.formato = "texto colado"
    ler_texto_em(col, texto or "", csv_provavel="\t" in (texto or ""))
    return col.leitura


# --------------------------------------------------------- link compartilhado
def url_de_download(url: str) -> str:
    """Converte o link de compartilhamento no link que entrega o arquivo."""
    url = url.strip()
    m = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", url)
    if m:
        return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=xlsx"
    m = re.search(r"docs\.google\.com/document/d/([\w-]+)", url)
    if m:
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=docx"
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=)([\w-]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    partes = urllib.parse.urlsplit(url)
    host = partes.netloc.lower()
    if "sharepoint.com" in host or "onedrive.live.com" in host or "1drv.ms" in host:
        consulta = urllib.parse.parse_qs(partes.query)
        consulta["download"] = ["1"]
        return urllib.parse.urlunsplit(partes._replace(
            query=urllib.parse.urlencode(consulta, doseq=True)))
    return url


def baixar_link(url: str, pasta: Path) -> Path:
    """Baixa a relação de um link público e devolve o arquivo salvo."""
    destino_url = url_de_download(url)
    pedido = urllib.request.Request(destino_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Helestron"})
    try:
        with urllib.request.urlopen(pedido, timeout=60) as resp:
            dados = resp.read(50 * 1024 * 1024)
            final = resp.geturl()
            nome = ""
            disp = resp.headers.get("Content-Disposition", "")
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp)
            if m:
                nome = urllib.parse.unquote(m.group(1))
    except Exception as erro:
        raise ListaInvalida(
            f"não consegui baixar o link: {str(erro)[:160]}" + LNLN
            + "Confira se ele está compartilhado como 'qualquer pessoa com o "
              "link'. Se for da rede do tribunal, baixe o arquivo e abra-o "
              "pelo botão 'Abrir arquivo'.") from erro
    amostra = dados[:2000].lower()
    if (b"<html" in amostra and any(s in final for s in (
            "accounts.google.com", "login.microsoftonline.com", "login.live.com"))):
        raise ListaInvalida(
            "o link pede login: ele não é público. Compartilhe como 'qualquer "
            "pessoa com o link' ou baixe o arquivo e abra-o pelo botão 'Abrir "
            "arquivo'.")
    pasta.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r'[<>:"/\\|?*]+', "_", nome).strip() or \
        f"relacao {datetime.now():%Y-%m-%d %Hh%M}"
    destino = pasta / nome
    destino.write_bytes(dados)
    return destino
