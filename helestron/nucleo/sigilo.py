"""A regra única do processo sigiloso (segredo de justiça).

O programa sabe que um processo corre em segredo de justiça por estas
fontes, e qualquer uma basta:

1. os AUTOS estão na pasta dos sigilosos (<sigilosos>/<número>.pdf ou
   <sigilosos>/<lote>/<número>.pdf, como o download grava, ou numa subpasta
   do lote, como o preparo os leva: o mesmo caminho que tinham no acervo);
2. há TRANSCRIÇÃO, gravação ou diário de audiência dele em
   <sigilosos>/Transcricoes (numa subpasta dela, ou numa pasta _audio dela):
   a audiência que já foi sigilosa uma vez continua sigilosa;
3. a PAUTA de audiências o marca sigiloso, em qualquer registro (o do
   portal, o do relatório importado, o que já saiu da pauta): o sigilo é do
   processo, não da linha (Armazem.sigilosas, contrato C4);
4. um DOWNLOAD já o apurou em segredo de justiça (o portal mostrou o selo):
   fica no registro ao lado do da pauta (LOCAL/download.sigilo.json:
   lembrar_do_download). Com a separação dos sigilosos desligada, os autos
   ficam no acervo, e é por ele que o resto do programa sabe do sigilo;
5. o RELATÓRIO de um lote dentro do acervo o dá como sigiloso (coluna
   "sigiloso" = "sim", em <lote>/_controle/relatorio.csv:
   sigilosos_dos_relatorios). É o que cobre o lote baixado com a separação
   desligada antes de existir o registro do download (versão anterior), ou
   depois de ele se perder (a pasta LOCAL apagada, o acervo levado para
   outro computador). Do relatório completo, na pasta dos sigilosos
   (<sigilosos>/<lote>/_controle), contam só as linhas dos recursos
   internos do 2º grau, que não têm autos (recursos_dos_completos).
   chaves_sigilosas, ao dar com um processo que só o relatório conhece, o
   acrescenta ao registro do download;
6. a CAPA do 2º grau de um ORIGINÁRIO (o HC, o MS, o AI de órgão 0000, o
   originário de turma recursal, 9xxx: número próprio) guardada num lote
   dentro do acervo (<lote>/_controle/<número> (2G)_capa.json) lista, em
   "Números de 1ª Instância", uma ação de origem sigilosa por qualquer das
   fontes acima (herdadas_das_origens). A petição traz cópia da origem; o
   motor já trata o originário como sigiloso no download, se a origem já se
   sabe sigilosa, e por aqui a origem que vira sigilosa DEPOIS o alcança
   também. chaves_sigilosas o acrescenta ao registro do download e avisa,
   no registro do programa, de que origem e de que capa veio o sigilo (uma
   vez por originário: o registro do download não guarda o porquê).

A gravação dos registros (4 e o da pauta) passa uma de cada vez também
entre processos (a janela, o "baixar" da linha de comando e o conector) e
insiste quando o Windows segura o arquivo por um instante (a trava e a troca
do cofre de senhas: cofre_senhas.travado e gravar_privado).

O INCIDENTE (o dependente "...0001-01", o cumprimento de sentença, por
exemplo) herda o sigilo do principal: as partes e o conteúdo são os mesmos.
O contrário não vale - o principal não fica sigiloso só por causa de um
incidente (Sigilosas, contem) -, salvo pelo RECURSO INTERNO do 2º grau
("...0001-50000": os embargos de declaração, o agravo interno), que corre
nos mesmos autos do principal: o sigiloso torna sigiloso também o principal
(com_principais_dos_recursos, nas fontes de chaves_sigilosas e, pela mesma
conta, nas consultas de um número só: _como_contem).

É esta regra que o compartilhamento (INDICE.md, CLAUDE.md/AGENTS.md, MCP,
_ia/texto, pacote, espelho na nuvem), o download e a transcrição consultam:
processo assim nunca vai para a IA nem para a nuvem, o download o grava na
pasta dos sigilosos e a transcrição dele vai para <sigilosos>/Transcricoes.

A pauta é lida do banco do programa (LOCAL/pauta.sqlite3) só se ele já
existir e SÓ PARA CONSULTA (o SQLite em "mode=ro": a consulta nunca cria o
banco, nunca grava nele e nunca o põe de lado, nem estragado - isso é com a
pauta, ao abrir), e o resultado fica guardado enquanto o banco não muda (o
servidor MCP consulta a regra a cada pedido da IA). Banco ilegível ou
ocupado não derruba quem pergunta: vale o que se leu da última vez, e o
registro diz que a pauta não pôde ser lida.

O sigilo, uma vez apurado, fica: o que a pauta já indicou é guardado também
FORA do banco, ao lado dele (LOCAL/pauta.sigilo.json: lembrar_da_pauta,
apuradas_da_pauta), e continua valendo se o banco se perder, estragar ou
for refeito do zero. Só se acrescenta a esse registro; para desfazer uma
marcação errada, o manual manda tirar da pasta, com o Helestron fechado, o
banco e o registro.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from dataclasses import replace
from pathlib import Path

from . import caminhos, cnj, cofre_senhas

log = logging.getLogger("nucleo.sigilo")

SUBPASTA_TRANSCRICOES = "Transcricoes"   # dentro da pasta dos sigilosos
SUBPASTA_AUDIO = "_audio"                # gravações e diários, dentro de Transcricoes

# Até que profundidade a pasta dos sigilosos é procurada (pastas abaixo dela:
# <sigilosos>/<lote>/<a>/<b>/<c>/<número>.pdf). O download grava nos dois
# primeiros níveis; o preparo leva o arquivo para o mesmo caminho que ele
# tinha no acervo (Processos/Lote 1/Concluídos/X.pdf -> <sigilosos>/Lote
# 1/Concluídos/X.pdf; Transcricoes/2025/X.docx -> <sigilosos>/Transcricoes/2025/X.docx).
PROFUNDIDADE_MAX = 4
# A pasta pode ter sido apontada para algo grande, como os Documentos: abaixo
# dos dois primeiros níveis (sempre lidos inteiros), no máximo estas pastas.
MAX_PASTAS = 2000
# O registro do que a pauta já apurou, ao lado do banco: pauta.sqlite3 -> pauta.sigilo.json
SUFIXO_APURADO = ".sigilo.json"
# E o do que o download já apurou, ao lado dele: download.sigilo.json
NOME_DO_DOWNLOAD = "download"
# Os relatórios de um lote, em <lote>/_controle (download/motor.RELATORIOS):
# o "(atualizado)" é o que o motor grava quando o Excel prende o outro.
RELATORIOS_DO_LOTE = ("relatorio.csv", "relatorio (atualizado).csv")
# Até que profundidade, abaixo do acervo, se procura a pasta de um lote (a
# que tem _controle): o próprio acervo (0), <acervo>/<lote> (1),
# <acervo>/Processos/<lote> (2, onde o download grava) e um nível abaixo
# (Processos/2025/<lote>). Abaixo do 2º nível, no máximo MAX_PASTAS pastas.
PROFUNDIDADE_LOTES = 3
# Pastas do acervo em que não há lote: o cache da IA, a das gravações e a
# do Claude Code (e as _controle, onde o relatório é procurado, não descido).
_SEM_LOTE = frozenset({"_ia", "_audio", ".claude", "_controle"})

# Por que o processo é sigiloso, para a tela, a linha de comando e o relatório
MOTIVO_PASTA = ("os autos, uma transcrição ou uma gravação dele estão na pasta dos "
                "sigilosos")
MOTIVO_PAUTA = "a pauta de audiências indica que ele corre em segredo de justiça"
# O incidente de um processo sigiloso (o sigilo vem do principal)
MOTIVO_PASTA_PRINCIPAL = ("é incidente de um processo sigiloso: os autos, uma transcrição ou "
                          "uma gravação do principal estão na pasta dos sigilosos")
MOTIVO_PAUTA_PRINCIPAL = ("é incidente de um processo sigiloso: a pauta de audiências indica "
                          "que o principal corre em segredo de justiça")
MOTIVO_DOWNLOAD = "um download anterior apurou que ele corre em segredo de justiça"
MOTIVO_DOWNLOAD_PRINCIPAL = ("é incidente de um processo sigiloso: um download anterior apurou "
                             "que o principal corre em segredo de justiça")
# O recurso interno sem autos que só o relatório completo de um lote, na pasta
# dos sigilosos, ainda dá como sigiloso (recursos_dos_completos)
MOTIVO_COMPLETO = ("o relatório completo de um lote, na pasta dos sigilosos, o dá como "
                   "sigiloso")
# O principal de um recurso interno do 2º grau sigiloso, por qualquer das
# fontes (com_principais_dos_recursos), e o incidente desse principal
MOTIVO_RECURSO = "um recurso interno dele no 2º grau é sigiloso"
MOTIVO_RECURSO_PRINCIPAL = ("é incidente de um processo sigiloso: um recurso interno do "
                            "principal no 2º grau é sigiloso")

PAUTA_DO_PROGRAMA = object()   # o banco da pauta do programa (caminhos.ARQUIVO_PAUTA)
VALIDADE_PAUTA_S = 30.0        # releitura forçada, mesmo sem mudança aparente no banco

_trava = threading.Lock()
_trava_apurado = threading.Lock()
# arquivo do banco -> (assinatura do banco e do registro, chaves, quando foi lido)
_lidas: dict[str, tuple[tuple, frozenset[str], float]] = {}
# relatório de lote -> (assinatura: mtime e tamanho, processos que ele dá como sigilosos)
_relatorios_lidos: dict[str, tuple[tuple, frozenset[str]]] = {}
# capa do 2º grau de um originário -> (assinatura, os processos de origem que ela lista)
_capas_lidas: dict[str, tuple[tuple, frozenset[str]]] = {}
_avisou_pasta_grande: set[str] = set()


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


def _principal_do_recurso(nome: str) -> str | None:
    """O principal (Numero.nome_arquivo) de 'nome' se ele for um recurso
    interno do 2º grau - o dependente que, sozinho, faz cnj.grau_do_numero
    dizer 2º grau ("...0001-50000", "...0001-50001") -; None se não for."""
    p = principal(nome)
    if p is None:
        return None                      # nem é incidente: quase todo nome
    try:
        n = cnj.ler_nome_arquivo(nome)
    except cnj.NumeroInvalido:
        return None
    # Sem o órgão (o 0000 do HC também diria 2º grau), só o dependente decide.
    return p if cnj.grau_do_numero(replace(n, origem="")) == "2g" else None


def com_principais_dos_recursos(nomes) -> frozenset[str]:
    """'nomes' (Numero.nome_arquivo) com o principal de cada recurso interno
    do 2º grau entre eles (_principal_do_recurso). O recurso interno corre
    nos mesmos autos do principal, e o portal apura os dois juntos
    (esaj.achar_codigo_2g): o sigiloso torna sigiloso também o principal. Sem
    isso, o principal que só a consulta do recurso apurou (sem linha nem
    autos dele) perdia o sigilo com o registro do download. O incidente
    comum ("-01", "-02") não muda nada: o principal não herda dele."""
    nomes = frozenset(nomes)
    principais = {p for p in map(_principal_do_recurso, nomes) if p}
    return nomes | principais if principais else nomes


# A chave do processo como a regra a guarda (Numero.nome_arquivo): o principal
# ou o incidente "-NN" (até "-50000", o recurso interno do 2º grau).
_RE_CHAVE_DO_PROCESSO = re.compile(r"^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?:-\d{2,5})?$")


def contem(chaves, nome) -> bool:
    """O processo 'nome' (Numero.nome_arquivo) está entre os sigilosos
    'chaves' - ele mesmo ou, se for incidente, o principal dele?

    'nome' pode vir também como a chave dos AUTOS ("...0001 (2G)", "...0001-01
    (2G)": cnj.chave_dos_autos), como um Numero ou como um nome de arquivo: o
    sigilo é do processo, nos dois graus, e a chave é normalizada antes de
    comparar - sem isso, os autos do 2º grau de um processo sigiloso passariam."""
    if not chaves or not nome:
        return False
    if not (isinstance(nome, str) and _RE_CHAVE_DO_PROCESSO.match(nome)):
        nome = _nome(nome) or str(nome)
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


# Como um processo está entre os sigilosos de uma fonte (_como_contem)
_PROPRIO, _DO_PRINCIPAL, _DO_RECURSO, _DO_RECURSO_DO_PRINCIPAL = 1, 2, 3, 4


def _como_contem(chaves: frozenset, nome: str) -> int:
    """Como o processo 'nome' (Numero.nome_arquivo) está entre os sigilosos
    'chaves' de UMA fonte, pela conta da regra única (contem sobre
    com_principais_dos_recursos, como em chaves_sigilosas): _PROPRIO,
    _DO_PRINCIPAL (é incidente de um deles), _DO_RECURSO (um recurso interno
    dele no 2º grau está entre eles), _DO_RECURSO_DO_PRINCIPAL (é incidente
    do principal de um desses recursos) ou 0 (não está).

    É a conta das consultas de um número só (na_pasta, na_pauta, motivo, o
    download, a transcrição, a tela da audiência): sem ela, o principal que
    só um recurso interno torna sigiloso dependia do registro do download, e
    com o registro perdido o download e a transcrição o davam como público.
    Só o dependente /5xxxx deriva o principal; sem ele, a conta é a de
    sempre, sobre as chaves já lidas (nenhuma leitura a mais)."""
    if frozenset.__contains__(chaves, nome):
        return _PROPRIO
    p = principal(nome)
    if p is not None and frozenset.__contains__(chaves, p):
        return _DO_PRINCIPAL
    derivadas = com_principais_dos_recursos(chaves)
    if frozenset.__contains__(derivadas, nome):
        return _DO_RECURSO
    if p is not None and frozenset.__contains__(derivadas, p):
        return _DO_RECURSO_DO_PRINCIPAL
    return 0


def _motivo(nome: str, fontes) -> str:
    """O porquê do sigilo de 'nome' pelas 'fontes', cada uma (função que lê
    as chaves dela, motivo próprio, motivo do incidente), lidas na ordem e só
    até a resposta. O próprio processo ou o principal dele numa fonte vale
    antes do recurso interno em qualquer delas (o porquê de sempre não muda);
    só sem eles vale MOTIVO_RECURSO ou MOTIVO_RECURSO_PRINCIPAL."""
    pelo_recurso = 0
    for ler, proprio, do_principal in fontes:
        como = _como_contem(ler(), nome)
        if como == _PROPRIO:
            return proprio
        if como == _DO_PRINCIPAL:
            return do_principal
        pelo_recurso = pelo_recurso or como
    if pelo_recurso == _DO_RECURSO:
        return MOTIVO_RECURSO
    return MOTIVO_RECURSO_PRINCIPAL if pelo_recurso else ""


def _nome(numero) -> str | None:
    """O Numero.nome_arquivo de um Numero ou de um texto (None se não houver)."""
    nome = getattr(numero, "nome_arquivo", None)
    if nome:
        return nome
    try:
        return cnj.ler_nome_arquivo(str(numero or "")).nome_arquivo
    except cnj.NumeroInvalido:
        return None


def nome_do_processo(numero) -> str | None:
    """O processo (um Numero, o número como a pauta o mostra, "...0001/01",
    ou o nome de um arquivo, "...0001-01.pdf") como Numero.nome_arquivo -
    a forma em que a regra compara. None se não houver número."""
    return _nome(numero)


def _partes_relativas(pasta, raiz) -> tuple[str, ...] | None:
    """As partes de 'pasta' relativas a 'raiz' (minúsculas), se estiver dentro."""
    try:
        rel = Path(pasta).resolve().relative_to(Path(raiz).resolve())
    except (ValueError, OSError, RuntimeError, TypeError):
        return None
    return tuple(q.lower() for q in rel.parts)


def _e_ligacao(entrada: os.DirEntry) -> bool:
    """Atalho simbólico ou junção do Windows: não se desce por ele (laço, ou
    uma pasta de fora que não é dos sigilosos)."""
    try:
        if entrada.is_symlink():
            return True
        juncao = getattr(entrada, "is_junction", None)
        return bool(juncao and juncao())
    except OSError:
        return True


def _candidatos(sigilosos: Path, fora: tuple[str, ...] | None = None) -> list[Path]:
    """Os arquivos que contam na pasta dos sigilosos: os autos (PDF) e, dentro
    de Transcricoes, as transcrições (DOCX) e o que estiver numa pasta _audio
    (gravações e diários).

    Em largura, nível a nível, até PROFUNDIDADE_MAX: o preparo leva o arquivo
    para o mesmo caminho que ele tinha no acervo, e não só para os dois
    primeiros níveis, onde o download grava. A pasta pode ter sido apontada
    para algo grande, como os Documentos: os dois primeiros níveis são
    sempre lidos inteiros e, abaixo deles, no máximo MAX_PASTAS pastas (sem
    as _controle dos lotes, as escondidas e os atalhos). Todos os nomes
    contam, e não só os que começam pelo número: quem decide é o número que
    o nome traz em qualquer posição ("Audiência - <número>.docx", os 20
    dígitos, "Sentença <número>.pdf"). 'fora': as partes (minúsculas,
    relativas à pasta) de uma subpasta que não conta (o acervo, se estiver
    por engano dentro dela). Levanta OSError se a pasta não puder ser lida.
    """
    achados: list[Path] = []
    transcricoes, audio = SUBPASTA_TRANSCRICOES.lower(), SUBPASTA_AUDIO.lower()
    # (pasta, partes relativas em minúsculas)
    nivel: list[tuple[Path, tuple[str, ...]]] = [(Path(sigilosos), ())]
    lidas_abaixo = 0
    while nivel:
        proximo: list[tuple[Path, tuple[str, ...]]] = []
        for pasta, partes in nivel:
            profundidade = len(partes)
            if profundidade >= 2:
                if lidas_abaixo >= MAX_PASTAS:
                    chave = str(sigilosos)
                    if chave not in _avisou_pasta_grande:
                        _avisou_pasta_grande.add(chave)
                        log.warning("A pasta dos sigilosos (%s) tem pastas demais; só as "
                                    "primeiras %d abaixo do segundo nível foram conferidas. "
                                    "Ela deve guardar só os processos em segredo de justiça.",
                                    sigilosos, MAX_PASTAS)
                    nivel = []
                    break
                lidas_abaixo += 1
            try:
                with os.scandir(pasta) as it:
                    entradas = list(it)
            except OSError:
                if profundidade == 0:
                    raise
                continue
            em_transcricoes = bool(partes) and partes[0] == transcricoes
            em_audio = em_transcricoes and audio in partes[1:]
            for e in entradas:
                nome = e.name
                minusculo = nome.lower()
                try:
                    e_pasta = e.is_dir()
                except OSError:
                    continue
                if e_pasta:
                    sub = (*partes, minusculo)
                    if em_audio:
                        achados.append(Path(e.path))   # a pasta de uma gravação em _audio
                    if profundidade + 1 > PROFUNDIDADE_MAX or (fora and sub == fora):
                        continue
                    if profundidade >= 1 and (minusculo == "_controle"
                                              or minusculo.startswith((".", "$", "~"))
                                              or _e_ligacao(e)):
                        continue
                    proximo.append((Path(e.path), sub))
                    continue
                if minusculo.endswith(".pdf") or em_audio or (
                        em_transcricoes and minusculo.endswith(".docx")):
                    achados.append(Path(e.path))
        else:
            nivel = proximo
    return achados


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
        candidatos = _candidatos(sigilosos, fora=dentro_dela or None)
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
            achados.add(cnj.ler_nome_arquivo(p.name).nome_arquivo)
        except cnj.NumeroInvalido:
            continue
    return Sigilosas(achados)


def _chaves_da_pasta(sigilosos) -> frozenset[str]:
    """chaves_na_pasta para as consultas de um número só. Nunca levanta."""
    if not sigilosos:
        return frozenset()
    try:
        return chaves_na_pasta(sigilosos)
    except (OSError, ValueError, TypeError):
        return frozenset()


def na_pasta(sigilosos, numero, herdar: bool = True) -> bool:
    """O processo tem autos, transcrição, gravação ou diário na pasta dos
    sigilosos? Com 'herdar', também o incidente, se o principal tiver, e o
    principal (ou o incidente dele), se um recurso interno do 2º grau tiver
    (_como_contem: a conta da regra única).

    Confere os mesmos arquivos que chaves_na_pasta, com o número em qualquer
    posição do nome ("Audiência - <número>.docx", "Sentença <número>.pdf",
    os 20 dígitos), e não só os que começam por ele: o download e a
    transcrição dão a mesma resposta que o compartilhamento."""
    nome = _nome(numero)
    if not nome or not sigilosos:
        return False
    como = _como_contem(_chaves_da_pasta(sigilosos), nome)
    return como == _PROPRIO or (herdar and bool(como))


# ===================================================================== pauta
def _arquivo_da_pauta(pauta) -> Path | None:
    if pauta is None or pauta is False:
        return None
    if pauta is PAUTA_DO_PROGRAMA or pauta is True:
        arquivo = getattr(caminhos, "ARQUIVO_PAUTA", None)
        return Path(arquivo) if arquivo else Path(caminhos.LOCAL) / "pauta.sqlite3"
    return Path(pauta)


def arquivo_apurado(pauta=PAUTA_DO_PROGRAMA) -> Path | None:
    """O registro dos processos que a pauta já indicou em segredo de justiça,
    ao lado do banco (LOCAL/pauta.sqlite3 -> LOCAL/pauta.sigilo.json)."""
    arquivo = _arquivo_da_pauta(pauta)
    if arquivo is None:
        return None
    return arquivo.with_name(arquivo.stem + SUFIXO_APURADO)


def _assinatura(arquivo: Path, sufixos=("", "-wal")) -> tuple:
    """O que muda quando o banco muda: o arquivo e o diário WAL (onde as
    gravações vão parar antes do ponto de verificação)."""
    partes = []
    for sufixo in sufixos:
        try:
            st = os.stat(f"{arquivo}{sufixo}")
            partes.append((st.st_mtime_ns, st.st_size))
        except OSError:
            partes.append(None)
    return tuple(partes)


def nome_da_chave(chave: str) -> str | None:
    """A chave da pauta (os 20 dígitos e o dependente: modelos.chave_processo)
    como Numero.nome_arquivo; None se não for chave."""
    chave = str(chave or "")
    digitos, dependente = chave[:20], chave[20:]
    if len(digitos) != 20 or not digitos.isdigit():
        return None
    try:
        n = cnj.ler(digitos)
    except cnj.NumeroInvalido:
        return None
    return (replace(n, dependente=dependente) if dependente else n).nome_arquivo


_nome_da_chave = nome_da_chave        # o nome antigo (compatibilidade)


def _uri_so_leitura(arquivo: Path) -> str:
    """file:...?mode=ro do banco, com o caminho absoluto em %XX (espaço, acento,
    "#", "?"); "file:///C:/..." no Windows e "file:////servidor/..." na rede."""
    caminho = os.path.abspath(str(arquivo)).replace("\\", "/")
    if not caminho.startswith("/"):
        caminho = "/" + caminho
    return "file://" + urllib.parse.quote(caminho, safe="/:") + "?mode=ro"


def _ler_banco(arquivo: Path) -> frozenset[str]:
    """Os processos (Numero.nome_arquivo) que o banco da pauta marca sigilosos,
    em qualquer registro (o mesmo que Armazem.sigilosas). SÓ PARA CONSULTA:
    nada de esquema, de PRAGMA que grave, de pôr o banco de lado. Banco sem
    a tabela (recém-criado) não marca nenhum. Levanta sqlite3.Error ou
    OSError se não puder ler."""
    import sqlite3

    con = sqlite3.connect(_uri_so_leitura(arquivo), uri=True, timeout=5,
                          check_same_thread=False)
    try:
        con.execute("PRAGMA query_only = ON")
        try:
            linhas = con.execute("SELECT DISTINCT processo FROM audiencias "
                                 "WHERE sigiloso = 1 AND processo != ''").fetchall()
        except sqlite3.OperationalError as erro:
            if "no such table" in str(erro).lower():
                return frozenset()
            raise
    finally:
        con.close()
    nomes = set()
    for (processo,) in linhas:
        try:
            nomes.add(cnj.ler(str(processo or "")).nome_arquivo)
        except cnj.NumeroInvalido:
            continue
    return frozenset(nomes)


def _ler_apuradas(arquivo: Path | None, tentativas: int = 1,
                  avisar: bool = True) -> tuple[frozenset[str], bool]:
    """(processos do registro, se foi lido). Sem o registro: (vazio, True).
    Registro ilegível (preso pelo antivírus, estragado): (vazio, False) - e
    ninguém grava por cima dele. 'tentativas': quantas vezes insistir no
    arquivo preso (o estragado não muda com a espera); 'avisar': o
    ilegível vai para o registro do programa."""
    if arquivo is None:
        return frozenset(), True
    for tentativa in range(max(1, tentativas)):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            break
        except FileNotFoundError:
            return frozenset(), True
        except (OSError, ValueError) as erro:
            if isinstance(erro, OSError) and tentativa < tentativas - 1:
                time.sleep(cofre_senhas.ESPERA_S)
                continue
            if avisar:
                log.warning("não consegui ler o registro dos processos já apurados em segredo "
                            "de justiça (%s): %s", arquivo.name, str(erro)[:160])
            return frozenset(), False
    lista = dados.get("processos") if isinstance(dados, dict) else None
    if not isinstance(lista, list):
        if avisar:
            log.warning("o registro dos processos já apurados em segredo de justiça (%s) não "
                        "tem a lista 'processos'.", arquivo.name)
        return frozenset(), False
    return frozenset(n for n in (_nome(x) for x in lista if isinstance(x, str)) if n), True


def apuradas_da_pauta(pauta=PAUTA_DO_PROGRAMA) -> Sigilosas:
    """Os processos (Numero.nome_arquivo) que a pauta JÁ indicou em segredo de
    justiça e que ficaram no registro ao lado do banco - mesmo que o banco
    tenha se perdido ou sido refeito. Nunca levanta."""
    return Sigilosas(_ler_apuradas(arquivo_apurado(pauta))[0])


_SOBRE_A_PAUTA = ("Processos que a pauta de audiências do Helestron já indicou em segredo de "
                  "justiça. O sigilo, uma vez apurado, fica: eles continuam sigilosos mesmo que "
                  "a pauta seja apagada ou refeita.")
_SOBRE_O_DOWNLOAD = ("Processos que um download do Helestron já apurou em segredo de justiça "
                     "(o portal do tribunal mostrou o selo). O sigilo, uma vez apurado, fica: "
                     "eles continuam sigilosos mesmo que os autos fiquem no acervo, com a "
                     "separação dos sigilosos desligada.")
_DESFAZER = (" Para desfazer uma marcação errada, veja no manual do Helestron a seção sobre o "
             "processo marcado como sigiloso por engano.")


def _acrescentar(arquivo: Path | None, processos, sobre: str) -> bool:
    """Acrescenta 'processos' ao registro 'arquivo' (lembrar_da_pauta,
    lembrar_do_download). Só acrescenta, nunca tira.

    Ler, juntar e gravar acontecem sob a trava do registro, entre as threads
    e entre os processos (a janela, o "baixar" da linha de comando, o
    conector): um não apaga o que o outro acabou de acrescentar. O registro
    preso por um instante (antivírus, o outro processo lendo) é lido e
    trocado com insistência; a gravação é atômica (temporário no disco +
    troca). Nunca levanta: False se não gravou (o registro ilegível não é
    sobrescrito)."""
    nomes = {n for n in (_nome(p) for p in processos or []) if n}
    if arquivo is None or not nomes:
        return False
    # Já estão todos lá: nada a gravar, e sem trava (do registro nada sai).
    ja, legivel = _ler_apuradas(arquivo, avisar=False)
    if legivel and nomes <= ja:
        return True
    try:
        with cofre_senhas.travado(arquivo, _trava_apurado, f"do registro {arquivo.name}"):
            ja, legivel = _ler_apuradas(arquivo, cofre_senhas.TENTATIVAS)
            if not legivel:
                return False
            if nomes <= ja:
                return True
            dados = {"sobre": sobre + _DESFAZER, "processos": sorted(ja | nomes)}
            cofre_senhas.gravar_privado(
                arquivo, json.dumps(dados, ensure_ascii=False, indent=1) + "\n")
    except OSError as erro:
        log.warning("não consegui guardar o registro dos processos apurados em segredo de "
                    "justiça (%s): %s", arquivo.name, str(erro)[:160])
        return False
    return True


def lembrar_da_pauta(processos, pauta=PAUTA_DO_PROGRAMA) -> bool:
    """Acrescenta 'processos' (Numero, número como a pauta mostra ou
    nome_arquivo) ao registro do que a pauta já apurou. Só acrescenta, nunca
    tira; gravação atômica (temporário + os.replace). Nunca levanta: False se
    não gravou (o registro ilegível não é sobrescrito)."""
    return _acrescentar(arquivo_apurado(pauta), processos, _SOBRE_A_PAUTA)


def arquivo_do_download(pauta=PAUTA_DO_PROGRAMA) -> Path | None:
    """O registro dos processos que um download já apurou em segredo de
    justiça, ao lado do da pauta (LOCAL/download.sigilo.json)."""
    arquivo = _arquivo_da_pauta(pauta)
    return None if arquivo is None else arquivo.with_name(NOME_DO_DOWNLOAD + SUFIXO_APURADO)


def apuradas_no_download(pauta=PAUTA_DO_PROGRAMA) -> Sigilosas:
    """Os processos (Numero.nome_arquivo) que um download já apurou em
    segredo de justiça (lembrar_do_download). Nunca levanta."""
    return Sigilosas(_ler_apuradas(arquivo_do_download(pauta))[0])


def lembrar_do_download(processos, pauta=PAUTA_DO_PROGRAMA) -> bool:
    """Acrescenta 'processos' ao registro do que o download já apurou: o
    portal mostrou o segredo de justiça. Com a separação dos sigilosos
    desligada, os autos ficam no acervo, e só este registro diz ao resto do
    programa (o índice, o texto para a IA, o conector, o pacote, a nuvem, a
    transcrição) que o processo é sigiloso. Só acrescenta; nunca levanta."""
    return _acrescentar(arquivo_do_download(pauta), processos, _SOBRE_O_DOWNLOAD)


def lembrar_do_banco(banco, pauta=PAUTA_DO_PROGRAMA) -> int:
    """Lê (só para consulta) os processos sigilosos de 'banco' - a cópia de um
    banco da pauta posto de lado por estar estragado, por exemplo - e os
    acrescenta ao registro de 'pauta'. Quantos leu (0 se não deu). Nunca levanta."""
    try:
        nomes = _ler_banco(Path(banco))
    except Exception as erro:
        log.info("não consegui ler os processos sigilosos de %s: %s", Path(banco).name,
                 str(erro)[:160])
        return 0
    if nomes:
        lembrar_da_pauta(nomes, pauta)
    return len(nomes)


def chaves_da_pauta(pauta=PAUTA_DO_PROGRAMA) -> Sigilosas:
    """Os processos (Numero.nome_arquivo) que a pauta marca sigilosos: os do
    banco e os do registro do que ela já apurou (apuradas_da_pauta).

    'pauta': o banco (padrão: o do programa); None não consulta a pauta.
    Nunca levanta, nunca cria o banco e nunca grava nele (lê em "mode=ro").
    """
    arquivo = _arquivo_da_pauta(pauta)
    if arquivo is None:
        return Sigilosas()
    apurado = arquivo_apurado(pauta)
    chave = str(arquivo)
    assinatura = _assinatura(arquivo) + _assinatura(apurado, ("",))
    with _trava:
        guardado = _lidas.get(chave)
    if guardado is not None and guardado[0] == assinatura \
            and time.monotonic() - guardado[2] < VALIDADE_PAUTA_S:
        return Sigilosas(guardado[1])
    lembradas, _legivel = _ler_apuradas(apurado)
    try:
        existe = arquivo.is_file()
    except OSError:
        existe = False
    if not existe:
        # sem o banco (ainda não criado, ou perdido): vale o que ela já apurou
        return Sigilosas(lembradas | (guardado[1] if guardado else frozenset()))
    try:
        do_banco = _ler_banco(arquivo)
    except Exception as erro:              # banco ocupado ou ilegível: vale o já sabido
        log.warning("não consegui ler na pauta quais processos são sigilosos (%s); %s.",
                    str(erro)[:160],
                    "valem a pasta dos sigilosos e o que a pauta já tinha indicado"
                    if guardado or lembradas else "vale só a pasta dos sigilosos")
        return Sigilosas(lembradas | (guardado[1] if guardado else frozenset()))
    if not do_banco <= lembradas and lembrar_da_pauta(do_banco, pauta):
        # o registro mudou agora, por nós: a assinatura dele é a de depois
        assinatura = assinatura[:-1] + _assinatura(apurado, ("",))
    nomes = frozenset(do_banco | lembradas)
    with _trava:
        # A assinatura do banco é a de ANTES da leitura: se ele mudou no meio,
        # a próxima consulta o lê de novo.
        _lidas[chave] = (assinatura, nomes, time.monotonic())
    return Sigilosas(nomes)


def na_pauta(numero, pauta=PAUTA_DO_PROGRAMA, herdar: bool = True) -> bool:
    """A pauta marca este processo sigiloso? Com 'herdar', também se marca o
    principal do incidente ou um recurso interno do 2º grau do principal
    (_como_contem). Nunca levanta."""
    nome = _nome(numero)
    if not nome:
        return False
    como = _como_contem(chaves_da_pauta(pauta), nome)
    return como == _PROPRIO or (herdar and bool(como))


def esquecer_pauta() -> None:
    """Descarta o que se leu da pauta (testes; troca do banco). O registro do
    que ela já apurou (no disco) fica."""
    with _trava:
        _lidas.clear()


# ============================================================ relatório do lote
def _pastas_de_controle(raiz: Path) -> list[Path]:
    """As pastas _controle dos lotes dentro de 'raiz' (o acervo): em largura,
    até PROFUNDIDADE_LOTES, sem descer pelo cache da IA, pelas pastas das
    gravações, pelas escondidas e pelos atalhos. Os dois primeiros níveis
    e as pastas dos lotes de Processos são sempre lidos inteiros; abaixo
    deles, no máximo MAX_PASTAS pastas (as de Processos primeiro). Só pastas: o relatório é procurado
    pelo nome, sem listar a _controle (que tem a capa de cada processo)."""
    achadas: list[Path] = []
    nivel: list[tuple[Path, tuple[str, ...]]] = [(Path(raiz), ())]
    lidas_abaixo = 0
    while nivel:
        proximo: list[tuple[Path, tuple[str, ...]]] = []
        for pasta, partes in nivel:
            # As pastas dos lotes do download (Processos/<lote>) não contam
            # para o limite: cada uma é justamente o que se procura, e o
            # limite as cortaria pela ordem do nome (no Windows, a dos lotes
            # mais recentes, "Lote AAAA-MM-DD HHhMM", ficaria de fora).
            if len(partes) >= 2 and not (len(partes) == 2 and partes[0] == "processos"):
                if lidas_abaixo >= MAX_PASTAS:
                    chave = str(raiz)
                    if chave not in _avisou_pasta_grande:
                        _avisou_pasta_grande.add(chave)
                        log.warning("O acervo (%s) tem pastas demais; o relatório dos lotes só "
                                    "foi procurado nas primeiras %d abaixo do segundo nível.",
                                    raiz, MAX_PASTAS)
                    return achadas
                lidas_abaixo += 1
            try:
                with os.scandir(pasta) as it:
                    entradas = list(it)
            except OSError:
                continue
            for e in entradas:
                minusculo = e.name.lower()
                try:
                    if not e.is_dir():
                        continue
                except OSError:
                    continue
                if minusculo == "_controle":
                    achadas.append(Path(e.path))
                    continue
                if (len(partes) >= PROFUNDIDADE_LOTES or minusculo in _SEM_LOTE
                        or minusculo.startswith((".", "$", "~")) or _e_ligacao(e)):
                    continue
                proximo.append((Path(e.path), (*partes, minusculo)))
        # Os lotes do download (Processos/<lote>) antes do resto do acervo
        nivel = sorted(proximo, key=lambda item: item[1][0] != "processos")
    return achadas


def _sigilosos_do_csv(dados: bytes) -> frozenset[str]:
    """Os processos que um relatório de lote dá como sigilosos ("sim" na
    coluna "sigiloso"), lido como o motor o lê (UTF-8 com BOM; o salvo pelo
    Excel, em ANSI). A linha mascarada ("(processo sigiloso)") não tem número
    e não conta: o número dela está na pasta dos sigilosos."""
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = dados.decode("cp1252", errors="replace")
    nomes: set[str] = set()
    try:
        for linha in csv.DictReader(texto.splitlines(), delimiter=";"):
            valor = linha.get("sigiloso")
            if not isinstance(valor, str) or valor.strip().lower() != "sim":
                continue
            try:
                nomes.add(cnj.ler_nome_arquivo(str(linha.get("processo") or "").strip())
                          .nome_arquivo)
            except cnj.NumeroInvalido:
                continue
    except (csv.Error, ValueError, AttributeError) as erro:
        log.warning("relatório de lote ilegível em parte (%s); vale o que foi lido.",
                    str(erro)[:120])
    return frozenset(nomes)


def _do_relatorio(arquivo: Path) -> frozenset[str]:
    """_sigilosos_do_csv de um relatório, guardado enquanto ele não muda (a
    data e o tamanho). Preso por um instante: vale o que se leu da última vez."""
    try:
        st = os.stat(arquivo)
    except OSError:
        return frozenset()
    assinatura = (st.st_mtime_ns, st.st_size)
    chave = str(arquivo)
    with _trava:
        guardado = _relatorios_lidos.get(chave)
    if guardado is not None and guardado[0] == assinatura:
        return guardado[1]
    try:
        dados = arquivo.read_bytes()
    except OSError as erro:
        log.info("não consegui ler o relatório %s (%s)", arquivo, str(erro)[:120])
        return guardado[1] if guardado is not None else frozenset()
    nomes = _sigilosos_do_csv(dados)
    with _trava:
        _relatorios_lidos[chave] = (assinatura, nomes)
    return nomes


def sigilosos_dos_relatorios(raiz) -> Sigilosas:
    """Os processos (Numero.nome_arquivo) que o relatório de algum lote
    dentro de 'raiz' (o acervo) dá como sigilosos: os dois relatórios
    (RELATORIOS_DO_LOTE) de cada <lote>/_controle até PROFUNDIDADE_LOTES.
    Com a separação dos sigilosos desligada, o relatório do lote fica no
    acervo sem máscara, e é o que diz o sigilo do lote baixado antes do
    registro do download (ou depois de ele se perder). A linha de um recurso
    interno do 2º grau dá como sigiloso também o principal
    (com_principais_dos_recursos). Cada relatório é lido de novo só quando
    muda. Nunca levanta."""
    if raiz is None:
        return Sigilosas()
    nomes: set[str] = set()
    try:
        for controle in _pastas_de_controle(Path(raiz)):
            for nome in RELATORIOS_DO_LOTE:
                nomes |= _do_relatorio(controle / nome)
    except (OSError, ValueError, TypeError) as erro:
        log.warning("não consegui ler os relatórios dos lotes do acervo (%s)", str(erro)[:160])
    return Sigilosas(com_principais_dos_recursos(nomes))


def recursos_dos_completos(sigilosos) -> frozenset[str]:
    """Os recursos internos do 2º grau que o relatório completo de algum
    lote, na pasta dos sigilosos (<sigilosos>/<lote>/_controle, onde o
    download o grava), dá como sigilosos - com o principal de cada um
    (com_principais_dos_recursos).

    O recurso interno de processo em segredo não tem autos (o Helestron não
    o baixa) e, com a separação ligada, a linha dele no relatório do lote no
    acervo sai mascarada: sem o registro do download, só o completo ainda
    diz que ele - e, por ele, o principal que só a consulta dele apurou - é
    sigiloso. As outras linhas do completo continuam fora da regra, como
    sempre: os autos desses processos estão na pasta dos sigilosos, e o
    sigilo deles, no registro do download. Nunca levanta."""
    return com_principais_dos_recursos(_recursos_dos_completos(sigilosos))


def _recursos_dos_completos(sigilosos) -> frozenset[str]:
    """Os recursos internos de recursos_dos_completos, sem os principais:
    cada relatório completo é relido só quando muda (_do_relatorio)."""
    if not sigilosos:
        return frozenset()
    try:
        with os.scandir(sigilosos) as it:
            entradas = list(it)
    except (OSError, ValueError, TypeError):
        return frozenset()
    lotes = []
    for e in entradas:
        try:
            if e.is_dir() and not _e_ligacao(e):
                lotes.append(Path(e.path))
        except OSError:
            continue
    recursos: set[str] = set()
    for lote in lotes:
        for nome in RELATORIOS_DO_LOTE:
            recursos |= {n for n in _do_relatorio(lote / "_controle" / nome)
                         if _principal_do_recurso(n)}
    return frozenset(recursos)


# ================================================= capa do originário do 2º grau
# O fim do nome da capa dos autos do 2º grau: "<número> (2G)_capa.json"
_FIM_CAPA_2G = (cnj.SUFIXO_2G + "_capa.json").lower()


def _originario(n: cnj.Numero) -> bool:
    """O número só existe no 2º grau pelo ÓRGÃO (0000: HC, MS, AI, revisão
    criminal; 9xxx: plantão do 2º grau, turma recursal), e não só pelo
    dependente (/50000, o recurso interno de uma apelação): é o processo com
    número próprio, que a regra por processo não liga à ação de origem."""
    return cnj.grau_do_numero(replace(n, dependente="")) == "2g"


def _origens_da_capa(dados) -> frozenset[str]:
    """Os processos de origem (Numero.nome_arquivo) que a capa do 2º grau
    lista em "numeros_1a_instancia" (o nível de cima do arquivo, com o
    "numero" de cada item no formato CNJ - o e-SAJ; o eProc não traz a lista
    nesta versão), lidos como motor._origem_sigilosa os lê."""
    lista = dados.get("numeros_1a_instancia") if isinstance(dados, dict) else None
    if not isinstance(lista, list):
        return frozenset()
    nomes: set[str] = set()
    for item in lista:
        texto = item.get("numero") if isinstance(item, dict) else item
        try:
            nomes.add(cnj.ler(str(texto or "")).nome_arquivo)
        except cnj.NumeroInvalido:
            continue
    return frozenset(nomes)


def _da_capa(arquivo: Path) -> frozenset[str]:
    """_origens_da_capa de uma capa, guardada enquanto ela não muda (a data
    e o tamanho), como _do_relatorio. Presa por um instante ou ilegível:
    vale o que se leu da última vez."""
    try:
        st = os.stat(arquivo)
    except OSError:
        return frozenset()
    assinatura = (st.st_mtime_ns, st.st_size)
    chave = str(arquivo)
    with _trava:
        guardado = _capas_lidas.get(chave)
    if guardado is not None and guardado[0] == assinatura:
        return guardado[1]
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        log.info("não consegui ler a capa %s (%s)", arquivo, str(erro)[:120])
        return guardado[1] if guardado is not None else frozenset()
    nomes = _origens_da_capa(dados)
    with _trava:
        _capas_lidas[chave] = (assinatura, nomes)
    return nomes


def _capas_de_originarios(controle: Path):
    """(chave do processo, capa) de cada "<número> (2G)_capa.json" de um
    originário do 2º grau na _controle de um lote. Só os nomes decidem: a
    capa da apelação (e a do recurso interno dela), cuja origem é o próprio
    número, não é aberta - seria a capa de quase todo o acervo."""
    try:
        with os.scandir(controle) as it:
            entradas = list(it)
    except OSError:
        return
    for e in entradas:
        if not e.name.lower().endswith(_FIM_CAPA_2G):
            continue
        try:
            n = cnj.ler_nome_arquivo(e.name)
        except cnj.NumeroInvalido:
            continue
        if _originario(n):
            yield n.nome_arquivo, Path(e.path)


def origens_herdadas(raiz, sabidas) -> dict[str, tuple[str, Path]]:
    """Os originários do 2º grau (Numero.nome_arquivo) com capa guardada na
    _controle de algum lote dentro de 'raiz' (o acervo) cuja ação de origem
    - a lista "numeros_1a_instancia" da capa, sem o próprio processo - está
    em 'sabidas' (contem: o incidente herda do principal), cada um com a
    origem sigilosa (a primeira, em ordem) e a capa que a lista: o porquê,
    que chaves_sigilosas põe no registro do programa.

    O HC, o MS e o AI de órgão 0000 (e o originário de turma recursal, 9xxx)
    têm número próprio, mas a petição traz cópia da ação de origem: o motor
    os trata como sigilosos no download, se a origem já se sabe sigilosa
    (motor._origem_sigilosa). A origem que vira sigilosa DEPOIS (a apelação
    dela baixada meses mais tarde com o selo, os autos levados à pasta dos
    sigilosos, a pauta) alcança o originário por aqui, pela mesma capa, que
    o download deixou em _controle. As pastas são as de
    _pastas_de_controle (com o mesmo limite de acervo grande); só as capas
    "<número> (2G)_capa.json" de originários são abertas, cada uma relida
    só quando muda. Nunca levanta."""
    if raiz is None or not sabidas:
        return {}
    nomes: dict[str, tuple[str, Path]] = {}
    try:
        for controle in _pastas_de_controle(Path(raiz)):
            for nome, capa in _capas_de_originarios(controle):
                sigilosas = sorted(origem for origem in _da_capa(capa)
                                   if origem != nome and contem(sabidas, origem))
                if sigilosas:
                    nomes.setdefault(nome, (sigilosas[0], capa))
    except (OSError, ValueError, TypeError) as erro:
        log.warning("não consegui ler as capas do 2º grau dos lotes do acervo (%s)",
                    str(erro)[:160])
    return nomes


def herdadas_das_origens(raiz, sabidas) -> frozenset[str]:
    """Só os originários de origens_herdadas (Numero.nome_arquivo), sem o
    porquê."""
    return frozenset(origens_herdadas(raiz, sabidas))


# ===================================================================== regra
def chaves_sigilosas(sigilosos, raiz=None, pauta=PAUTA_DO_PROGRAMA) -> Sigilosas:
    """TODOS os processos sigilosos que o programa conhece (Numero.nome_arquivo):
    os da pasta dos sigilosos (autos, transcrição, gravação, diário), os
    que a pauta marca, os que um download já apurou e, com 'raiz', os que o
    relatório de um lote dentro dela dá como sigilosos e os originários do
    2º grau cuja ação de origem, pela capa guardada no lote, é sigilosa por
    qualquer dessas fontes. 'raiz': o acervo (ver chaves_na_pasta,
    sigilosos_dos_relatorios e herdadas_das_origens); 'pauta': o banco da
    pauta, com o registro do download ao lado (None: nem um nem outro). Num
    Sigilosas: 'chave in ...' vale também para o incidente de um deles.

    O processo que só o relatório conhece (o lote baixado antes do registro
    do download, ou com ele perdido) e o originário que só a capa liga à
    origem sigilosa passam a valer também no registro do download, para o
    resto do programa (a transcrição, a tela da audiência, o próximo
    download): uma vez apurado, fica. O que a pasta ou a pauta já dão não
    vai para ele: o relatório marca também o que o lote só TRATOU como
    sigiloso por elas, e o registro do download diria que o portal o apurou.
    O originário entra nele com um aviso no registro do programa (a origem
    e a capa, como o detalhe do item no download), uma vez: depois, o
    registro já o conhece.

    Em todas as fontes, o recurso interno do 2º grau sigiloso torna sigiloso
    também o principal (com_principais_dos_recursos): o principal que só a
    consulta do recurso apurou volta ao registro pela linha do recurso no
    relatório do lote - o do acervo ou o completo, na pasta dos sigilosos,
    onde a linha não é mascarada (recursos_dos_completos). O que só os autos
    do recurso na pasta, ou só o recurso no registro, dão como sigiloso vai
    para o registro também (uma vez apurado, fica). As consultas de um número
    só (motivo, processo_sigiloso) fazem a mesma conta (_como_contem), com o
    completo; só o relatório do lote no acervo e a capa do originário, que
    pedem 'raiz', chegam a elas pelo registro."""
    base = chaves_na_pasta(sigilosos, raiz) | chaves_da_pauta(pauta) | apuradas_no_download(pauta)
    sabidas = Sigilosas(com_principais_dos_recursos(base))
    if raiz is None:
        return sabidas
    # já com os principais dos recursos internos
    dos_relatorios = sigilosos_dos_relatorios(raiz) | recursos_dos_completos(sigilosos)
    origens = origens_herdadas(raiz, Sigilosas(sabidas | dos_relatorios))
    das_origens = com_principais_dos_recursos(origens)
    novas = sorted(n for n in dos_relatorios | das_origens if n not in sabidas)
    for nome in novas:
        if nome in origens:
            # O rastro do porquê: no registro do download, o originário não
            # se distingue do que o portal apurou.
            origem, capa = origens[nome]
            log.warning("originário %s tratado como sigiloso: o processo de origem %s é "
                        "sigiloso (capa do 2º grau em %s)", nome, origem, capa)
    # o principal que só um recurso interno dele dá (os autos do recurso na
    # pasta, ou só o recurso no registro)
    novas += sorted(sabidas - base)
    if novas:
        lembrar_do_download(novas, pauta)
    return Sigilosas(sabidas | dos_relatorios | das_origens)


# As fontes das consultas de um número só, para _motivo: (como ler as chaves,
# motivo próprio, motivo do incidente)
def _fonte_da_pasta(sigilosos):
    return (lambda: _chaves_da_pasta(sigilosos)), MOTIVO_PASTA, MOTIVO_PASTA_PRINCIPAL


def _fonte_da_pauta(pauta):
    return (lambda: chaves_da_pauta(pauta)), MOTIVO_PAUTA, MOTIVO_PAUTA_PRINCIPAL


def _fonte_do_download(pauta):
    return (lambda: apuradas_no_download(pauta)), MOTIVO_DOWNLOAD, MOTIVO_DOWNLOAD_PRINCIPAL


def motivo_da_pasta(sigilosos, numero) -> str:
    """MOTIVO_PASTA, MOTIVO_PASTA_PRINCIPAL (o incidente de um processo com
    autos, transcrição ou gravação na pasta dos sigilosos), MOTIVO_RECURSO ou
    MOTIVO_RECURSO_PRINCIPAL (os de um recurso interno do 2º grau estão lá:
    _como_contem) ou ""."""
    nome = _nome(numero)
    if not nome or not sigilosos:
        return ""
    return _motivo(nome, [_fonte_da_pasta(sigilosos)])


def motivo_da_pauta(numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """MOTIVO_PAUTA, MOTIVO_PAUTA_PRINCIPAL (o incidente de um processo que a
    pauta marca sigiloso), MOTIVO_RECURSO ou MOTIVO_RECURSO_PRINCIPAL (a pauta
    marca um recurso interno do 2º grau: _como_contem) ou ""."""
    nome = _nome(numero)
    return _motivo(nome, [_fonte_da_pauta(pauta)]) if nome else ""


def motivo_do_download(numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """MOTIVO_DOWNLOAD, MOTIVO_DOWNLOAD_PRINCIPAL (o incidente de um processo
    que um download apurou sigiloso), MOTIVO_RECURSO ou
    MOTIVO_RECURSO_PRINCIPAL (um download apurou um recurso interno do 2º
    grau: _como_contem) ou ""."""
    nome = _nome(numero)
    return _motivo(nome, [_fonte_do_download(pauta)]) if nome else ""


def motivo_sabido(sigilosos, numero, pauta=PAUTA_DO_PROGRAMA, com_os_autos: bool = True) -> str:
    """motivo, com a pasta dos sigilosos dada (a do motor). 'com_os_autos'
    falso deixa de fora os autos, as transcrições e as gravações da pasta,
    que quem pergunta já conferiu (a tela da audiência, por na_pasta); o
    relatório completo conta sempre. Nunca levanta."""
    nome = _nome(numero)
    if not nome:
        return ""
    # A linha "sim" de um recurso interno sem autos no relatório completo,
    # na pasta dos sigilosos: por último, porque é a única leitura a mais (e
    # cada completo só é relido quando muda).
    completos = ((lambda: _recursos_dos_completos(sigilosos)), MOTIVO_COMPLETO,
                 MOTIVO_COMPLETO)
    fontes = [_fonte_da_pauta(pauta), _fonte_do_download(pauta), completos]
    return _motivo(nome, [_fonte_da_pasta(sigilosos)] + fontes if com_os_autos else fontes)


def motivo(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """Por que o programa já sabe que o processo é sigiloso ("" = não sabe):
    MOTIVO_PASTA, MOTIVO_PAUTA, MOTIVO_DOWNLOAD ou MOTIVO_COMPLETO (ou, no
    incidente de um processo sigiloso, MOTIVO_PASTA_PRINCIPAL,
    MOTIVO_PAUTA_PRINCIPAL ou MOTIVO_DOWNLOAD_PRINCIPAL), nessa ordem; sem
    nenhum deles, MOTIVO_RECURSO (o principal de um recurso interno do 2º
    grau sigiloso por qualquer dessas fontes) ou MOTIVO_RECURSO_PRINCIPAL (o
    incidente desse principal). É a conta da regra única (chaves_sigilosas):
    só o relatório de lote no acervo e a capa do originário, que pedem
    'raiz', ficam de fora, e o que eles dão chega aqui pelo registro do
    download, da próxima vez que a regra rodar. Nunca levanta."""
    try:
        sigilosos = cfg.pasta_sigilosos
    except Exception:
        sigilosos = None
    return motivo_sabido(sigilosos, numero, pauta)


def processo_sigiloso(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> bool:
    """O processo é sigiloso pela regra única (pasta dos sigilosos, pauta, o
    que um download já apurou, o relatório completo de um recurso interno
    sem autos e, em todas, o recurso interno do 2º grau: motivo)?"""
    return bool(motivo(cfg, numero, pauta))
