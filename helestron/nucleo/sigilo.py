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

PAUTA_DO_PROGRAMA = object()   # o banco da pauta do programa (caminhos.ARQUIVO_PAUTA)
VALIDADE_PAUTA_S = 30.0        # releitura forçada, mesmo sem mudança aparente no banco

_trava = threading.Lock()
# arquivo do banco -> (assinatura do banco, chaves, quando foi lido)
_lidas: dict[str, tuple[tuple, frozenset[str], float]] = {}


# ===================================================================== apoio
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
def chaves_na_pasta(sigilosos, raiz=None) -> set[str]:
    """Os processos (Numero.nome_arquivo) com autos, transcrição, gravação ou
    diário na pasta dos sigilosos.

    'raiz': o acervo. Se ele estiver (por engano de configuração) dentro da
    pasta dos sigilosos, o que é do acervo não vira sigiloso por isso.
    """
    if not sigilosos:
        return set()
    sigilosos = Path(sigilosos)
    dentro_dela = _partes_relativas(raiz, sigilosos) if raiz is not None else None
    try:
        candidatos = _candidatos(sigilosos)
    except OSError:
        return set()
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
    return achados


def na_pasta(sigilosos, numero) -> bool:
    """O processo tem autos, transcrição, gravação ou diário na pasta dos
    sigilosos? (A consulta de um número só: procura só o que tem o nome dele.)"""
    nome = _nome(numero)
    if not nome or not sigilosos:
        return False
    try:
        candidatos = _candidatos(Path(sigilosos), f"{glob.escape(nome)}*")
    except (OSError, ValueError, TypeError):
        return False
    for p in candidatos:
        try:
            if cnj.ler_nome_arquivo(p.stem).nome_arquivo == nome:
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


def chaves_da_pauta(pauta=PAUTA_DO_PROGRAMA) -> set[str]:
    """Os processos (Numero.nome_arquivo) que a pauta marca sigilosos.

    'pauta': o banco (padrão: o do programa); None não consulta a pauta.
    Nunca levanta e nunca cria o banco.
    """
    arquivo = _arquivo_da_pauta(pauta)
    if arquivo is None:
        return set()
    try:
        if not arquivo.is_file():
            return set()
    except OSError:
        return set()
    chave = str(arquivo)
    assinatura = _assinatura(arquivo)
    with _trava:
        guardado = _lidas.get(chave)
    if guardado is not None and guardado[0] == assinatura \
            and time.monotonic() - guardado[2] < VALIDADE_PAUTA_S:
        return set(guardado[1])
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
        return set(guardado[1]) if guardado else set()
    nomes = frozenset(n for n in (_nome_da_chave(c) for c in marcadas) if n)
    with _trava:
        # A assinatura de ANTES da leitura: se o banco mudou no meio, a
        # próxima consulta o lê de novo.
        _lidas[chave] = (assinatura, nomes, time.monotonic())
    return set(nomes)


def na_pauta(numero, pauta=PAUTA_DO_PROGRAMA) -> bool:
    """A pauta marca este processo sigiloso? Nunca levanta."""
    nome = _nome(numero)
    return bool(nome) and nome in chaves_da_pauta(pauta)


def esquecer_pauta() -> None:
    """Descarta o que se leu da pauta (testes; troca do banco)."""
    with _trava:
        _lidas.clear()


# ===================================================================== regra
def chaves_sigilosas(sigilosos, raiz=None, pauta=PAUTA_DO_PROGRAMA) -> set[str]:
    """TODOS os processos sigilosos que o programa conhece (Numero.nome_arquivo):
    os da pasta dos sigilosos (autos, transcrição, gravação, diário) e os
    que a pauta marca. 'raiz': o acervo (ver chaves_na_pasta)."""
    return chaves_na_pasta(sigilosos, raiz) | chaves_da_pauta(pauta)


def motivo(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """Por que o programa já sabe que o processo é sigiloso ("" = não sabe):
    MOTIVO_PASTA ou MOTIVO_PAUTA. Nunca levanta."""
    try:
        sigilosos = cfg.pasta_sigilosos
    except Exception:
        sigilosos = None
    if na_pasta(sigilosos, numero):
        return MOTIVO_PASTA
    if na_pauta(numero, pauta):
        return MOTIVO_PAUTA
    return ""


def processo_sigiloso(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> bool:
    """O processo é sigiloso pela regra única (pasta dos sigilosos ou pauta)?"""
    return bool(motivo(cfg, numero, pauta))
