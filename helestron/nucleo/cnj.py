"""Leitura e validação de números de processo no padrão CNJ.

Formato: NNNNNNN-DD.AAAA.J.TR.OOOO
         |       |  |    | |  |
         |       |  |    | |  +-- órgão de origem (foro), 4 dígitos
         |       |  |    | +----- tribunal, 2 dígitos (02 = Alagoas)
         |       |  |    +------- segmento (8 = Justiça Estadual, 4 = Federal)
         |       |  +------------ ano do ajuizamento
         |       +--------------- dígito verificador
         +----------------------- número sequencial na origem

Herdado do Assessor SAJ (app/esaj/numero.py), com duas novidades: o número
sabe dizer de que tribunal é (``chave_tribunal``), o que deixa o programa
escolher sozinho entre e-SAJ e eProc, e a extração de uma lista preserva a
ordem em que os números aparecem no documento.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# Aceita o número com ou sem pontuação, e também os 20 dígitos corridos.
# O separador aceita hífen, ponto, espaço e os travessões que o Word põe
# sozinho no lugar do hífen ("0700003–40.2024...").
_SEP = r"[-.\s\u2010-\u2015]?"
# O dependente (/01, /0003 - o e-SAJ usa 4 dígitos no 1º grau; /50000,
# /50001 - o recurso interno do e-SAJ 2º grau, 5 dígitos) só é aceito quando
# é mesmo um sufixo do número, e não o começo do texto que vem depois dele:
#   * colado à barra ("/1", "/01", "/0003", "/50000"), de 1 a 5 dígitos;
#   * com espaço em volta da barra (" / 01"), só com 2 ou mais dígitos -
#     "... / 3 réus" é texto, não o incidente 03;
#   * nunca seguido de letra, ordinal ou grau ("/ 1ª Vara", "/2ª Vara",
#     "/1º"): o \w do Python já cobre letras, dígitos, 'ª' e 'º'.
# Sem isso, a relação com "0700003-40.2024.8.02.0001 / 1ª Vara" baixava o
# incidente 01 no lugar dos autos principais.
_PADRAO = re.compile(
    rf"(?<!\d)(\d{{7}}){_SEP}(\d{{2}}){_SEP}(\d{{4}}){_SEP}(\d){_SEP}(\d{{2}}){_SEP}(\d{{4}})"
    r"(?:(?:/|\s*/\s*(?=\d\d))(\d{1,5})(?![\w°]))?"
    r"(?!\d)"
)


class NumeroInvalido(ValueError):
    """O texto informado não contém um número de processo reconhecível."""


@dataclass(frozen=True)
class Numero:
    sequencial: str   # NNNNNNN
    digito: str       # DD
    ano: str          # AAAA
    segmento: str     # J
    tribunal: str     # TR
    origem: str       # OOOO  (o foro, usado na consulta do e-SAJ)
    dependente: str = ""   # 01, 02... quando o número traz /NN; 50000... no recurso interno do 2º grau

    @property
    def principal(self) -> str:
        """0700003-40.2024.8.02.0001 — o número sem o sufixo."""
        return (f"{self.sequencial}-{self.digito}.{self.ano}"
                f".{self.segmento}.{self.tribunal}.{self.origem}")

    @property
    def formatado(self) -> str:
        """Como aparece nos autos, com o sufixo do dependente se houver."""
        if self.dependente:
            return f"{self.principal}/{self.dependente}"
        return self.principal

    @property
    def e_dependente(self) -> bool:
        return bool(self.dependente)

    @property
    def digitos(self) -> str:
        """Os 20 dígitos sem pontuação."""
        return (self.sequencial + self.digito + self.ano
                + self.segmento + self.tribunal + self.origem)

    @property
    def unificado(self) -> str:
        """0700003-40.2024 — o campo 'numeroDigitoAnoUnificado' do e-SAJ."""
        return f"{self.sequencial}-{self.digito}.{self.ano}"

    @property
    def foro(self) -> str:
        """0001 — o campo 'foroNumeroUnificado' do e-SAJ."""
        return self.origem

    @property
    def chave_tribunal(self) -> str:
        """'8.02' — segmento e tribunal, a chave do catálogo de tribunais."""
        return f"{self.segmento}.{self.tribunal}"

    @property
    def nome_arquivo(self) -> str:
        """Nome do arquivo de saída, sem extensão.

        O Windows não aceita '/' em nome de arquivo: o dependente vira
        '-NN'. Assim o PDF do incidente não sobrescreve o do principal.
        """
        if self.dependente:
            return f"{self.principal}-{self.dependente}"
        return self.principal

    @property
    def digito_confere(self) -> bool:
        """Confere o dígito verificador pela regra da Resolução CNJ 65/2008."""
        corpo = (self.sequencial + self.ano + self.segmento
                 + self.tribunal + self.origem)
        esperado = 98 - (int(corpo + "00") % 97)
        return esperado == int(self.digito)

    def __str__(self) -> str:  # pragma: no cover - conveniência de log
        return self.formatado


def _montar(m: re.Match) -> Numero:
    partes = list(m.groups())
    # '/0003' e '/3' são o mesmo dependente: guarda-se com 2 dígitos, no
    # mínimo ('/50000', o recurso interno do 2º grau, fica com os 5)
    sufixo = ""
    if partes[6] is not None:
        sufixo = (partes[6].strip().lstrip("0") or "0").zfill(2)
    return Numero(*partes[:6], dependente=sufixo)


def ler(texto: str) -> Numero:
    """Extrai o primeiro número CNJ de um texto qualquer."""
    m = _PADRAO.search(texto or "")
    if not m:
        raise NumeroInvalido(
            f"número de processo não reconhecido em '{(texto or '').strip()}'")
    return _montar(m)


# No NOME DE ARQUIVO o dependente vem como "-NN" (Numero.nome_arquivo), porque
# o Windows não aceita "/". Sem ler o sufixo, o PDF do incidente
# ("...0001-01.pdf") e o do principal ("...0001.pdf") teriam a mesma chave.
_DEPENDENTE_NO_NOME = re.compile(r"-(?:inc)?0*(\d{1,5})(?=$|[\s._()\[\]])", re.I)


def ler_nome_arquivo(texto: str) -> Numero:
    """O número CNJ de um nome de arquivo ou pasta, com o dependente "-NN".

    Aceita também a barra ("/01") e o que vier depois do número, como
    " (2)" ou " 2025-03-10 14h00 - revisão".
    """
    m = _PADRAO.search(texto or "")
    if not m:
        raise NumeroInvalido(
            f"número de processo não reconhecido em '{(texto or '').strip()}'")
    numero = _montar(m)
    if not numero.dependente:
        d = _DEPENDENTE_NO_NOME.match(texto[m.end():])
        if d:
            numero = replace(numero, dependente=(d.group(1).lstrip("0") or "0").zfill(2))
    return numero


def chave(n: Numero) -> str:
    """Identidade do processo para deduplicar: dígitos + dependente."""
    return n.digitos + (n.dependente or "")


def extrair_todos(texto: str) -> list[Numero]:
    """Todos os números CNJ do texto, na ordem em que aparecem, sem repetir.

    Usado na leitura de planilhas e documentos: a relação pode trazer o
    número no meio de uma frase, numa célula com outras informações, com ou
    sem pontuação.
    """
    vistos: set[str] = set()
    saida: list[Numero] = []
    for m in _PADRAO.finditer(texto or ""):
        n = _montar(m)
        k = chave(n)
        if k not in vistos:
            vistos.add(k)
            saida.append(n)
    return saida


def ler_lista(texto: str) -> list[Numero]:
    """Lê vários números de um texto livre, ignorando linhas em branco e
    comentários iniciados por '#' ou ';'. Repetidos são descartados."""
    numeros: list[Numero] = []
    vistos: set[str] = set()
    for linha in (texto or "").splitlines():
        limpa = linha.strip()
        if not limpa or limpa[0] in "#;":
            continue
        for n in extrair_todos(limpa):
            k = chave(n)
            if k not in vistos:
                vistos.add(k)
                numeros.append(n)
    return numeros


# ===================================================================== grau
# O grau dos autos: "1g" (1º grau: as varas) ou "2g" (2º grau: os recursos e
# as ações originárias do tribunal). O número sozinho quase nunca diz o grau
# (a apelação e o RESE sobem com o número da origem): ver grau_do_processo.
GRAUS = ("1g", "2g")
# O nome dos autos do 2º grau: "<número> (2G).pdf", e o mesmo na capa, no
# registro e no texto ("<número> (2G)_capa.json", "<número> (2G).txt"). O
# sufixo vem DEPOIS do número e do "-NN" do dependente, separado por espaço
# (nunca colado com hífen: "-2G" apagaria o incidente do nome), em ASCII. O
# 1º grau continua com o nome de sempre (Numero.nome_arquivo).
SUFIXO_2G = " (2G)"
_RE_GRAU = re.compile(r"^\s*([12])\s*(?:g|[º°o])?\s*(?:grau)?\s*$", re.I)
# O sufixo do 2º grau logo depois do número (e do "-NN"): " (2G)" - o que o
# programa grava - e, na leitura, também " (2g)", " (2º grau)" e " - 2g". Não
# casa a cópia do Windows " (2)" nem " - 2ª Vara".
_GRAU_NO_NOME = re.compile(
    r"^(?:-(?:inc)?\d{1,5})?(?:\s*\(\s*2\s*(?:g|[º°o]\s*grau)\s*\)"
    r"|\s+-\s+2\s*(?:g|[º°o]\s*grau))(?=$|[\s._()\[\]])", re.I)


def normalizar_grau(valor) -> str:
    """'1', '1g', '1G', '1º', '1° grau', '1o' -> '1g'; o mesmo com 2 -> '2g';
    qualquer outra coisa (vazio, '3', 'ambos') -> ''. Quem chama decide o que
    fazer com o '' (a linha de comando recusa; o config.ini vale 1g)."""
    m = _RE_GRAU.match(str(valor or ""))
    return f"{m.group(1)}g" if m else ""


def grau_do_numero(n: Numero) -> str:
    """'2g' quando o número só existe no 2º grau; '' quando não diz o grau.

    Só no 2º grau: o órgão OOOO = 0000 (competência originária do tribunal:
    HC, MS, agravo de instrumento, revisão criminal - Res. CNJ 65/2008), o
    OOOO começando por 9 (plantão do 2º grau, turma recursal) e o dependente de
    5 dígitos começando por 5 (/50000, /50001: o recurso interno do e-SAJ 2º
    grau - embargos de declaração, agravo interno)."""
    if n.origem == "0000" or n.origem.startswith("9"):
        return "2g"
    if len(n.dependente) == 5 and n.dependente.startswith("5"):
        return "2g"
    return ""


def grau_do_processo(n: Numero, grau_do_lote: str = "") -> str:
    """A regra única do grau de um processo do lote, nesta ordem: o número
    (grau_do_numero), o grau do lote (OpcoesDownload.grau: a opção "Grau" do
    lote ou --grau; sem ela, o [download] grau dos Ajustes) e, por fim, 1g.
    Não há troca automática de grau: a apelação existe nos dois."""
    return grau_do_numero(n) or normalizar_grau(grau_do_lote) or "1g"


def nome_dos_autos(n: Numero, grau: str = "1g") -> str:
    """O nome (sem extensão) do PDF dos autos - e da capa, do registro e do
    texto: o do 1º grau é Numero.nome_arquivo, como sempre; o do 2º grau leva
    SUFIXO_2G ('0700001-93.2024.8.02.0058 (2G)', '...0001-50000 (2G)')."""
    return n.nome_arquivo + (SUFIXO_2G if normalizar_grau(grau) == "2g" else "")


def grau_do_nome(texto) -> str:
    """'2g' se o nome (de arquivo ou pasta, ou a chave dos autos) traz o
    sufixo do 2º grau logo depois do número (e do "-NN"); '1g' se não traz.
    Levanta NumeroInvalido se o texto não tiver número."""
    texto = str(texto or "")
    m = _PADRAO.search(texto)
    if not m:
        raise NumeroInvalido(f"número de processo não reconhecido em '{texto.strip()}'")
    return "2g" if _GRAU_NO_NOME.match(texto[m.end():]) else "1g"


def chave_dos_autos(texto) -> str:
    """A identidade do ARQUIVO de autos (processo + grau), de um nome de
    arquivo ou pasta, de uma chave dos autos ou de um número: 'X', 'X-01',
    'X (2G)', 'X-50000 (2G)'. No 1º grau é a chave do processo
    (Numero.nome_arquivo): acervos e textos de antes não mudam. A chave do
    PROCESSO (sigilo, motor) continua ler_nome_arquivo(texto).nome_arquivo,
    que ignora o sufixo do grau. Levanta NumeroInvalido se não houver número.

    Um nome (texto) vale pelo que diz: sem o sufixo, 1º grau. Um Numero não
    traz nome: o grau é o que o próprio número diz (grau_do_numero) - o HC de
    órgão 0000 e o /50000 só têm autos no 2º grau -, e 1º grau no resto."""
    if isinstance(texto, Numero):
        return nome_dos_autos(texto, grau_do_numero(texto) or "1g")
    return nome_dos_autos(ler_nome_arquivo(str(texto or "")), grau_do_nome(texto))
