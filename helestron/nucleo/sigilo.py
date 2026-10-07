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
   outro computador). chaves_sigilosas, ao dar com um processo que só o
   relatório conhece, o acrescenta ao registro do download.

A gravação dos registros (4 e o da pauta) passa uma de cada vez também
entre processos (a janela, o "baixar" da linha de comando e o conector) e
insiste quando o Windows segura o arquivo por um instante (a trava e a troca
do cofre de senhas: cofre_senhas.travado e gravar_privado).

O INCIDENTE (o dependente "...0001-01", o cumprimento de sentença, por
exemplo) herda o sigilo do principal: as partes e o conteúdo são os mesmos.
O contrário não vale - o principal não fica sigiloso só por causa de um
incidente (Sigilosas, contem).

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

PAUTA_DO_PROGRAMA = object()   # o banco da pauta do programa (caminhos.ARQUIVO_PAUTA)
VALIDADE_PAUTA_S = 30.0        # releitura forçada, mesmo sem mudança aparente no banco

_trava = threading.Lock()
_trava_apurado = threading.Lock()
# arquivo do banco -> (assinatura do banco e do registro, chaves, quando foi lido)
_lidas: dict[str, tuple[tuple, frozenset[str], float]] = {}
# relatório de lote -> (assinatura: mtime e tamanho, processos que ele dá como sigilosos)
_relatorios_lidos: dict[str, tuple[tuple, frozenset[str]]] = {}
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


def na_pasta(sigilosos, numero, herdar: bool = True) -> bool:
    """O processo tem autos, transcrição, gravação ou diário na pasta dos
    sigilosos? O incidente também, se o principal tiver ('herdar').

    Confere os mesmos arquivos que chaves_na_pasta, com o número em qualquer
    posição do nome ("Audiência - <número>.docx", "Sentença <número>.pdf",
    os 20 dígitos), e não só os que começam por ele: o download e a
    transcrição dão a mesma resposta que o compartilhamento."""
    nome = _nome(numero)
    if not nome or not sigilosos:
        return False
    do_principal = principal(nome) if herdar else None
    alvos = {nome, do_principal} - {None}
    try:
        candidatos = _candidatos(Path(sigilosos))
    except (OSError, ValueError, TypeError):
        return False
    for p in candidatos:
        try:
            if cnj.ler_nome_arquivo(p.name).nome_arquivo in alvos:
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
    """A pauta marca este processo sigiloso (ou, se for incidente e
    'herdar', o principal dele)? Nunca levanta."""
    nome = _nome(numero)
    if not nome:
        return False
    chaves = chaves_da_pauta(pauta)
    return contem(chaves, nome) if herdar else frozenset.__contains__(chaves, nome)


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
    registro do download (ou depois de ele se perder). Cada relatório é lido
    de novo só quando muda. Nunca levanta."""
    if raiz is None:
        return Sigilosas()
    nomes: set[str] = set()
    try:
        for controle in _pastas_de_controle(Path(raiz)):
            for nome in RELATORIOS_DO_LOTE:
                nomes |= _do_relatorio(controle / nome)
    except (OSError, ValueError, TypeError) as erro:
        log.warning("não consegui ler os relatórios dos lotes do acervo (%s)", str(erro)[:160])
    return Sigilosas(nomes)


# ===================================================================== regra
def chaves_sigilosas(sigilosos, raiz=None, pauta=PAUTA_DO_PROGRAMA) -> Sigilosas:
    """TODOS os processos sigilosos que o programa conhece (Numero.nome_arquivo):
    os da pasta dos sigilosos (autos, transcrição, gravação, diário), os
    que a pauta marca, os que um download já apurou e, com 'raiz', os que o
    relatório de um lote dentro dela dá como sigilosos. 'raiz': o acervo
    (ver chaves_na_pasta e sigilosos_dos_relatorios); 'pauta': o banco da
    pauta, com o registro do download ao lado (None: nem um nem outro). Num
    Sigilosas: 'chave in ...' vale também para o incidente de um deles.

    O processo que só o relatório conhece (o lote baixado antes do registro
    do download, ou com ele perdido) passa a valer também no registro do
    download, para o resto do programa (a transcrição, a tela da
    audiência). O que a pasta ou a pauta já dão não vai para ele: o relatório
    marca também o que o lote só TRATOU como sigiloso por elas, e o registro
    do download diria que o portal o apurou."""
    sabidas = Sigilosas(chaves_na_pasta(sigilosos, raiz) | chaves_da_pauta(pauta)
                        | apuradas_no_download(pauta))
    if raiz is None:
        return sabidas
    dos_relatorios = sigilosos_dos_relatorios(raiz)
    novas = sorted(n for n in dos_relatorios if n not in sabidas)
    if novas:
        lembrar_do_download(novas, pauta)
    return Sigilosas(sabidas | dos_relatorios)


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


def motivo_do_download(numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """MOTIVO_DOWNLOAD, MOTIVO_DOWNLOAD_PRINCIPAL (o incidente de um processo
    que um download apurou sigiloso) ou ""."""
    nome = _nome(numero)
    if not nome:
        return ""
    chaves = apuradas_no_download(pauta)
    if frozenset.__contains__(chaves, nome):
        return MOTIVO_DOWNLOAD
    return MOTIVO_DOWNLOAD_PRINCIPAL if contem(chaves, nome) else ""


def motivo(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> str:
    """Por que o programa já sabe que o processo é sigiloso ("" = não sabe):
    MOTIVO_PASTA, MOTIVO_PAUTA ou MOTIVO_DOWNLOAD (ou, no incidente de um
    processo sigiloso, MOTIVO_PASTA_PRINCIPAL, MOTIVO_PAUTA_PRINCIPAL ou
    MOTIVO_DOWNLOAD_PRINCIPAL). Nunca levanta."""
    try:
        sigilosos = cfg.pasta_sigilosos
    except Exception:
        sigilosos = None
    return (motivo_da_pasta(sigilosos, numero) or motivo_da_pauta(numero, pauta)
            or motivo_do_download(numero, pauta))


def processo_sigiloso(cfg, numero, pauta=PAUTA_DO_PROGRAMA) -> bool:
    """O processo é sigiloso pela regra única (pasta dos sigilosos, pauta ou
    o que um download já apurou)?"""
    return bool(motivo(cfg, numero, pauta))
