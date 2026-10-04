"""A regra única do processo sigiloso (segredo de justiça).

O programa sabe que um processo corre em segredo de justiça por três fontes,
e qualquer uma basta:

1. os AUTOS estão na pasta dos sigilosos (<sigilosos>/<número>.pdf ou
   <sigilosos>/<lote>/<número>.pdf, como o download grava);
2. há TRANSCRIÇÃO, gravação ou diário de audiência dele em
   <sigilosos>/Transcricoes (ou em Transcricoes/_audio): a audiência que já
   foi sigilosa uma vez continua sigilosa;
3. a PAUTA de audiências o marca sigiloso, em qualquer registro (o do
   portal, o do relatório importado, o que já saiu da pauta): o sigilo é do
   processo, não da linha (Armazem.sigilosas, contrato C4).

O INCIDENTE (o dependente "...0001-01", o cumprimento de sentença, por
exemplo) herda o sigilo do principal: as partes e o conteúdo são os mesmos.
O contrário não vale - o principal não fica sigiloso só por causa de um
incidente (Sigilosas, contem).

É esta regra que o compartilhamento (INDICE.md, CLAUDE.md/AGENTS.md, MCP,
_ia/texto, pacote, espelho na nuvem), o download e a transcrição consultam:
processo assim nunca vai para a IA nem para a nuvem, o download o grava na
pasta dos sigilosos e a transcrição dele vai para <sigilosos>/Transcricoes.

A pauta é lida do banco do programa (LOCAL/pauta.sqlite3) só se ele já
existir - a consulta nunca o cria -, pela API pública da pauta, e o
resultado fica guardado enquanto o banco não muda (o servidor MCP consulta
a regra a cada pedido da IA). Banco ilegível ou ocupado não derruba quem
pergunta: vale o que se leu da última vez (o sigilo, uma vez apurado,
fica), e o registro diz que a pauta não pôde ser lida.
"""

from __future__ import annotations

import glob
import logging
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

from . import caminhos, cnj

log = logging.getLogger("nucleo.sigilo")

SUBPASTA_TRANSCRICOES = "Transcricoes"   # dentro da pasta dos sigilosos
SUBPASTA_AUDIO = "_audio"                # gravações e diários, dentro de Transcricoes

# Por que o processo é sigiloso, para a tela, a linha de comando e o relatório
MOTIVO_PASTA = ("os autos, uma transcrição ou uma gravação dele estão na pasta dos "
                "sigilosos")
MOTIVO_PAUTA = "a pauta de audiências indica que ele corre em segredo de justiça"
# O incidente de um processo sigiloso (o sigilo vem do principal)
MOTIVO_PASTA_PRINCIPAL = ("é incidente de um processo sigiloso: os autos, uma transcrição ou "
                          "uma gravação do principal estão na pasta dos sigilosos")
MOTIVO_PAUTA_PRINCIPAL = ("é incidente de um processo sigiloso: a pauta de audiências indica "
                          "que o principal corre em segredo de justiça")

PAUTA_DO_PROGRAMA = object()   # o banco da pauta do programa (caminhos.ARQUIVO_PAUTA)
VALIDADE_PAUTA_S = 30.0        # releitura forçada, mesmo sem mudança aparente no banco

_trava = threading.Lock()
# arquivo do banco -> (assinatura do banco, chaves, quando foi lido)
_lidas: dict[str, tuple[tuple, frozenset[str], float]] = {}


# ===================================================================== apoio
_TAMANHO_PRINCIPAL = len("0000000-00.0000.0.00.0000")


def principal(nome) -> str | None:
    """O principal (Numero.nome_arquivo) de um incidente ("...0001-01" ->
    "...0001"); None se 'nome' não for incidente nem número."""
    texto = getattr(nome, "nome_arquivo", None) or str(nome or "")
    # O caminho rápido (a regra é consultada para cada arquivo do acervo):
    # o nome_arquivo do principal ("NNNNNNN-DD.AAAA.J.TR.OOOO") e o do incidente.
    if len(texto) >= _TAMANHO_PRINCIPAL and texto[7] == "-" and texto[10] == ".":
        if len(texto) == _TAMANHO_PRINCIPAL:
            return None
        if texto[_TAMANHO_PRINCIPAL] == "-" and texto[_TAMANHO_PRINCIPAL + 1:].isdigit():
            return texto[:_TAMANHO_PRINCIPAL]
    try:
        n = cnj.ler_nome_arquivo(texto)
    except cnj.NumeroInvalido:
        return None
    return n.principal if n.dependente else None


def contem(chaves, nome) -> bool:
    """O processo 'nome' (Numero.nome_arquivo) está entre os sigilosos
    'chaves' - ele mesmo ou, se for incidente, o principal dele?"""
    if not chaves or not nome:
        return False
    if frozenset.__contains__(chaves, nome) if isinstance(chaves, frozenset) else nome in chaves:
        return True
    p = principal(nome)
    if p is None:
        return False
    return frozenset.__contains__(chaves, p) if isinstance(chaves, frozenset) else p in chaves


class Sigilosas(frozenset):
    """Os processos sigilosos (Numero.nome_arquivo). 'chave in sigilosas' é
    verdadeiro também para o incidente de um processo sigiloso: o incidente
    ("...0001-01") herda o sigilo do principal ("...0001"). O principal não
    fica sigiloso só por causa de um incidente."""

    def __contains__(self, chave) -> bool:
        return contem(self, chave)


def _nome(numero) -> str | None:
    """O Numero.nome_arquivo de um Numero ou de um texto (None se não houver)."""
    nome = getattr(numero, "nome_arquivo", None)
    if nome:
        return nome
    try:
        return cnj.ler_nome_arquivo(str(numero or "")).nome_arquivo
    except cnj.NumeroInvalido:
        return None


def _partes_relativas(pasta, raiz) -> tuple[str, ...] | None:
    """As partes de 'pasta' relativas a 'raiz' (minúsculas), se estiver dentro."""
    try:
        rel = Path(pasta).resolve().relative_to(Path(raiz).resolve())
    except (ValueError, OSError, RuntimeError, TypeError):
        return None
    return tuple(q.lower() for q in rel.parts)


def _candidatos(sigilosos: Path, prefixo: str = "*") -> list[Path]:
    """Os arquivos que contam na pasta dos sigilosos: os autos (dois níveis,
    como o programa grava - a pasta pode ter sido apontada para algo grande,
    como os Documentos) e as transcrições, gravações e diários."""
    transcricoes = sigilosos / SUBPASTA_TRANSCRICOES
    return [*sigilosos.glob(f"{prefixo}.pdf"), *sigilosos.glob(f"*/{prefixo}.pdf"),
            *transcricoes.glob(f"{prefixo}.docx"),
            *(transcricoes / SUBPASTA_AUDIO).glob(prefixo)]


# ========================================================== pasta dos sigilosos
def chaves_na_pasta(sigilosos, raiz=None) -> Sigilosas:
    """Os processos (Numero.nome_arquivo) com autos, transcrição, gravação ou
    diário na pasta dos sigilosos.

    'raiz': o acervo. Se ele estiver (por engano de configuração) dentro da
    pasta dos sigilosos, o que é do acervo não vira sigiloso por isso.
    """
    if not sigilosos:
        return Sigilosas()
    sigilosos = Path(sigilosos)
    dentro_dela = _partes_relativas(raiz, sigilosos) if raiz is not None else None
    try:
        candidatos = _candidatos(sigilosos)
    except OSError:
        return Sigilosas()
    achados: set[str] = set()
    for p in candidatos:
        if dentro_dela is not None:
            partes = tuple(q.lower() for q in p.relative_to(sigilosos).parts)
            if partes[:len(dentro_dela)] == dentro_dela:
                continue
        try:
            # "...0001-01.pdf" é o incidente, não o principal "...0001"
            achados.add(cnj.ler_nome_arquivo(p.stem).nome_arquivo)
        except cnj.NumeroInvalido:
            continue
    return Sigilosas(achados)


def na_pasta(sigilosos, numero, herdar: bool = True) -> bool:
    """O processo tem autos, transcrição, gravação ou diário na pasta dos
    sigilosos? O incidente também, se o principal tiver ('herdar'). (A
    consulta de um número só: procura só o que tem o nome dele.)"""
    nome = _nome(numero)
    if not nome or not sigilosos:
        return False
    do_principal = principal(nome) if herdar else None
    alvos = {nome, do_principal} - {None}
    prefixo = do_principal or nome      # o nome do incidente começa pelo do principal
    try:
        candidatos = _candidatos(Path(sigilosos), f"{glob.escape(prefixo)}*")
    except (OSError, ValueError, TypeError):
        return False
    for p in candidatos:
        try:
            if cnj.ler_nome_arquivo(p.stem).nome_arquivo in alvos:
                return True
        except cnj.NumeroInvalido:
            continue
    return False


# ===================================================================== pauta
def _arquivo_da_pauta(pauta) -> Path | None:
    if pauta is None or pauta is False:
        return None
    if pauta is PAUTA_DO_PROGRAMA or pauta is True:
        arquivo = getattr(caminhos, "ARQUIVO_PAUTA", None)
        return Path(arquivo) if arquivo else Path(caminhos.LOCAL) / "pauta.sqlite3"
    return Path(pauta)


def _assinatura(arquivo: Path) -> tuple:
    """O que muda quando o banco muda: o arquivo e o diário WAL (onde as
    gravações vão parar antes do ponto de verificação)."""
    partes = []
    for sufixo in ("", "-wal"):
        try:
            st = os.stat(f"{arquivo}{sufixo}")
            partes.append((st.st_mtime_ns, st.st_size))
        except OSError:
            partes.append(None)
    return tuple(partes)


def _nome_da_chave(chave: str) -> str | None:
    """A chave da pauta (os 20 dígitos e o dependente) como Numero.nome_arquivo."""
    digitos, dependente = chave[:20], chave[20:]
    if len(digitos) != 20 or not digitos.isdigit():
        return None
    try:
        n = cnj.ler(digitos)
    except cnj.NumeroInvalido:
        return None
    return (replace(n, dependente=dependente) if dependente else n).nome_arquivo


def chaves_da_pauta(pauta=PAUTA_DO_PROGRAMA) -> Sigilosas:
    """Os processos (Numero.nome_arquivo) que a pauta marca sigilosos.

    'pauta': o banco (padrão: o do programa); None não consulta a pauta.
    Nunca levanta e nunca cria o banco.
    """
    arquivo = _arquivo_da_pauta(pauta)
    if arquivo is None:
        return Sigilosas()
    try:
        if not arquivo.is_file():
            return Sigilosas()
    except OSError:
        return Sigilosas()
    chave = str(arquivo)
    assinatura = _assinatura(arquivo)
    with _trava:
        guardado = _lidas.get(chave)
    if guardado is not None and guardado[0] == assinatura \
            and time.monotonic() - guardado[2] < VALIDADE_PAUTA_S:
        return Sigilosas(guardado[1])
    try:
        from ..pauta.armazem import Armazem

        armazem = Armazem(arquivo)
        try:
            marcadas, _ids = armazem.sigilosas()
        finally:
            armazem.fechar()
    except Exception as erro:              # banco ocupado ou ilegível: vale o já sabido
        log.warning("não consegui ler na pauta quais processos são sigilosos (%s); %s.",
                    str(erro)[:160],
                    "valem a pasta dos sigilosos e o que a pauta já tinha indicado" if guardado
                    else "vale só a pasta dos sigilosos")
        return Sigilosas(guardado[1]) if guardado else Sigilosas()
    nomes = Sigilosas(n for n in (_nome_da_chave(c) for c in marcadas) if n)
    with _trava:
        # A assinatura de ANTES da leitura: se o banco mudou no meio, a
        # próxima consulta o lê de novo.
        _lidas[chave] = (assinatura, nomes, time.monotonic())
    return nomes


def na_pauta(numero, pauta=PAUTA_DO_PROGRAMA, herdar: bool = True) -> bool:
    """A pauta marca este processo sigiloso (ou, se for incidente e
    'herdar', o principal dele)? Nunca levanta."""
    nome = _nome(numero)
    if not nome:
        return False
    chaves = chaves_da_pauta(pauta)
    return contem(chaves, nome) if herdar else frozenset.__contains__(chaves, nome)


def esquecer_pauta() -> None:
    """Descarta o que se leu da pauta (testes; troca do banco)."""
    with _trava:
        _lidas.clear()


# ===================================================================== regra
def chaves_sigilosas(sigilosos, raiz=None, pauta=PAUTA_DO_PROGRAMA) -> Sigilosas:
    """TODOS os processos sigilosos que o programa conhece (Numero.nome_arquivo):
    os da pasta dos sigilosos (autos, transcrição, gravação, diário) e os
    que a pauta marca. 'raiz': o acervo (ver chaves_na_pasta). Num
    Sigilosas: 'chave in ...' vale também para o incidente de um deles."""
    return Sigilosas(chaves_na_pasta(sigilosos, raiz) | chaves_da_pauta(pauta))


def motivo_da_pasta(sigilosos, numero) -> str:
    """MOTIVO_PASTA, MOTIVO_PASTA_PRINCIPAL (o incidente de um processo com
    autos, transcrição ou gravação na pasta dos sigilosos) ou ""."""
    if na_pasta(sigilosos, numero, herdar=False):
        return MOTIVO_PASTA
    if principal(_nome(numero)) and na_pasta(sigilosos, numero):
        return MOTIVO_PASTA_PRINCIPAL
    return ""


def motivo_da_pauta(numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """MOTIVO_PAUTA, MOTIVO_PAUTA_PRINCIPAL (o incidente de um processo que a
    pauta marca sigiloso) ou ""."""
    if na_pauta(numero, pauta, herdar=False):
        return MOTIVO_PAUTA
    if principal(_nome(numero)) and na_pauta(numero, pauta):
        return MOTIVO_PAUTA_PRINCIPAL
    return ""


def motivo(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """Por que o programa já sabe que o processo é sigiloso ("" = não sabe):
    MOTIVO_PASTA ou MOTIVO_PAUTA (ou, no incidente de um processo sigiloso,
    MOTIVO_PASTA_PRINCIPAL ou MOTIVO_PAUTA_PRINCIPAL). Nunca levanta."""
    try:
        sigilosos = cfg.pasta_sigilosos
    except Exception:
        sigilosos = None
    return motivo_da_pasta(sigilosos, numero) or motivo_da_pauta(numero, pauta)


def processo_sigiloso(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> bool:
    """O processo é sigiloso pela regra única (pasta dos sigilosos ou pauta)?"""
    return bool(motivo(cfg, numero, pauta))
