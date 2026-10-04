"""python -m helestron --verificar-instalacao [--relatorio ARQ]: a conferência do instalador.

Sem janela. O instalador roda isto ao final e, se o código de saída não for
0, mostra o resumo e onde está o relatório. Confere, nesta ordem:

  1. o manifesto: existência, tamanho e SHA-256 de TODOS os arquivos
     instalados (o arquivo que o antivírus levou aparece aqui, pelo nome);
  2. os módulos: importa TODOS os módulos do pacote helestron (listados
     sem importar nada, pelo sistema de arquivos), num processo à parte - um
     módulo que falte ou não carregue aparece aqui, e não no meio do uso,
     como o "No module named 'app.interface.pagina_config'" da versão
     anterior;
  3. o restante, por helestron.verificar, TAMBÉM num processo à parte:
     Windows, bibliotecas, componentes nativos, modelo de transcrição
     (carregado de verdade), navegador dos portais, microfone, pastas,
     cofre de senhas, catálogo de tribunais, separação de falantes e o
     conector do acervo (MCP);
  4. a janela: WebView2 (101 ou mais recente) ou, na falta dele, o Edge, ou
     um navegador padrão que rode a interface (não o Internet Explorer).

Por que processos à parte: uma biblioteca nativa quebrada (DLL faltando,
processador sem AVX, o numpy no Wine) derruba o processo sem exceção
nenhuma. Se isso acontecesse aqui, o instalador ficaria sem relatório. No
processo-filho, a queda vira um item de falha com o nome da checagem, e a
verificação segue com as demais num processo novo.

O relatório é regravado a cada passo: mesmo que este processo caia, o
instalador encontra o que já foi conferido e a marca de que a verificação
não terminou.

Relatório em texto UTF-8 (padrão: LOCAL\\Logs\\verificacao-instalacao.txt).
Código de saída: 0 = pronto (talvez com avisos); 1 = falha; 9 = os arquivos
estão certos, mas o computador não tem como abrir a janela (sem WebView2,
sem Edge e com o Internet Explorer de navegador padrão) - o instalador
explica como instalar o WebView2, em vez de dizer "tudo certo".
"""

from __future__ import annotations

import json
import logging
import os
import pkgutil
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import NOME, __version__
from ..nucleo import caminhos
from . import integridade

log = logging.getLogger("aplicativo.verificacao")

OK, AVISO, FALHA = "ok", "aviso", "falha"
NOME_JANELA = "WebView2 (janela do programa)"
CODIGO_SEM_JANELA = 9
NO_WINDOWS = sys.platform == "win32"
ROTULOS = {OK: "OK", AVISO: "AVISO", FALHA: "FALHA"}
REINSTALAR = ("Instale o Helestron de novo com o Helestron-Setup: ele conserta a instalação sem "
              "apagar os seus dados. Se um arquivo sumiu logo depois da instalação, o antivírus "
              "pode tê-lo posto em quarentena: peça ao suporte que libere a pasta do programa.")


@dataclass
class Resultado:
    nome: str
    situacao: str
    detalhe: str = ""
    acao: str = ""
    linhas: tuple[str, ...] = ()
    codigo: str = ""          # "sem_janela": o item que muda o código de saída para 9


def arquivo_padrao() -> Path:
    return Path(caminhos.LOGS) / "verificacao-instalacao.txt"


# ================================================================ os passos
def conferir_manifesto(progresso: Callable[[int, int, str], None] | None = None) -> Resultado:
    pasta = integridade.pasta_instalada()
    if pasta is None:
        return Resultado("Arquivos do programa", AVISO,
                         "Execução a partir do código-fonte: não há manifesto para conferir.")
    try:
        versao, entradas = integridade.ler_manifesto(pasta)
    except ValueError as erro:
        return Resultado("Arquivos do programa", FALHA, str(erro), REINSTALAR)
    problemas = integridade.conferir_completo(pasta, progresso)
    if not problemas:
        return Resultado("Arquivos do programa", OK,
                         f"{len(entradas)} arquivos conferidos (tamanho e SHA-256), versão "
                         f"{versao or __version__}.")
    um = len(problemas) == 1
    return Resultado("Arquivos do programa", FALHA,
                     f"{len(problemas)} arquivo{'' if um else 's'} ausente{'' if um else 's'} ou "
                     f"alterado{'' if um else 's'}, de {len(entradas)}.", REINSTALAR,
                     tuple(p.frase for p in problemas))


def _pasta_do_pacote() -> Path:
    return Path(__file__).resolve().parents[1]


def modulos_do_pacote() -> tuple[list[str], list[tuple[str, str]]]:
    """(nomes de todos os módulos do pacote helestron, pastas que não
    puderam ser lidas).

    Percorre as pastas com pkgutil.iter_modules, que só lê o disco: o
    pkgutil.walk_packages importaria cada subpacote AQUI, e a importação de
    verdade fica para o processo à parte (importar_todos).
    """
    nomes = ["helestron"]
    erros: list[tuple[str, str]] = []

    def percorrer(pasta: Path, prefixo: str) -> None:
        try:
            achados = sorted(pkgutil.iter_modules([str(pasta)]), key=lambda i: i.name)
        except OSError as erro:
            erros.append((prefixo.rstrip("."), f"{type(erro).__name__}: {erro}"))
            return
        for info in achados:
            nome = prefixo + info.name
            nomes.append(nome)
            if info.ispkg:
                percorrer(pasta / info.name, nome + ".")

    percorrer(_pasta_do_pacote(), "helestron.")
    return nomes, erros


def importar_todos() -> list[tuple[str, str]]:
    """[(módulo, erro)] dos módulos que não carregaram. Num processo à parte:
    importar uma biblioteca nativa quebrada pode derrubar o processo."""
    from .. import verificar

    nomes, erros = modulos_do_pacote()
    pasta = str(_pasta_do_pacote().parent)
    resultado = verificar.sondar_importacoes(nomes, LIMITE_MODULOS_S, [pasta],
                                             total_s=LIMITE_MODULOS_S)
    for nome in nomes:
        r = resultado.get(nome)
        if r is None:
            erros.append((nome, "não foi conferido"))
        elif not r.get("ok"):
            erros.append((nome, str(r.get("erro", "erro desconhecido"))))
    return erros


def conferir_modulos() -> Resultado:
    try:
        nomes, _ = modulos_do_pacote()
        erros = importar_todos()
    except Exception as erro:                      # noqa: BLE001
        return Resultado("Módulos do programa", FALHA, f"{type(erro).__name__}: {erro}",
                         REINSTALAR)
    if not erros:
        return Resultado("Módulos do programa", OK, f"{len(nomes)} módulos carregados.")
    return Resultado("Módulos do programa", FALHA,
                     f"{len(erros)} módulo{'s' if len(erros) != 1 else ''} não "
                     f"carrega{'m' if len(erros) != 1 else ''}.", REINSTALAR,
                     tuple(f"{nome}: {erro}" for nome, erro in erros))


# As checagens de helestron.verificar que entram aqui. O WebView2 fica de
# fora: conferir_janela() o confere, e também diz o que acontece sem ele.
TESTE_TRANSCRICAO = "Teste de transcrição"
FORA_DO_MOTOR = ("WebView2 (janela do programa)",)
# Tempo total das checagens do motor, e quanto o processo delas pode ficar
# calado (sem começar nem terminar uma checagem) antes de ser dado como
# travado - o teste do modelo pode levar uns minutos num computador lento.
LIMITE_MOTOR_S = 900.0
SEM_NOVIDADE_MOTOR_S = 360.0
# A importação de todos os módulos (num processo à parte).
LIMITE_MODULOS_S = 600.0

# O processo-filho: roda as checagens pedidas e escreve uma linha JSON ao
# começar cada uma ({"inicio": nome}) e outra ao terminar ({"item": {...}}).
_SONDA_MOTOR = r"""
import sys
from helestron.aplicativo import verificacao
sys.exit(verificacao.motor_no_filho(sys.argv[1:]))
"""


def _etapas_do_motor(cfg) -> list[tuple[str, Callable]]:
    from .. import verificar

    etapas = [(nome, funcao) for nome, funcao in verificar._etapas(cfg, False)
              if nome not in FORA_DO_MOTOR]
    # O modelo embutido carrega de verdade (1 s de silêncio), logo depois do
    # item do modelo.
    posicao = next((i + 1 for i, (nome, _) in enumerate(etapas)
                    if nome == "Modelo de transcrição"), len(etapas))
    etapas.insert(posicao, (TESTE_TRANSCRICAO, lambda: verificar.checar_teste_transcricao(cfg)))
    return etapas


def nomes_do_motor(cfg=None) -> list[str]:
    from ..nucleo import config

    return [nome for nome, _ in _etapas_do_motor(cfg or config.carregar(criar=False))]


def motor_no_filho(argv: list[str]) -> int:
    """No processo-filho: roda as checagens nomeadas em argv ("--paralelo"
    para várias ao mesmo tempo) e as escreve na saída, uma linha JSON cada."""
    from .. import verificar
    from ..nucleo import config

    paralelo = "--paralelo" in argv
    pedidos = [a for a in argv if not a.startswith("--")]
    cfg = config.carregar(criar=False)
    etapas = dict(_etapas_do_motor(cfg))

    def emitir(dados: dict) -> None:
        sys.stdout.write(json.dumps(dados) + "\n")
        sys.stdout.flush()

    def comecar(nome: str):
        emitir({"inicio": nome})
        funcao = etapas.get(nome)
        if funcao is None:
            return verificar.Item(nome, FALHA, "Checagem desconhecida.", obrigatorio=False)
        return verificar._protegido(nome, funcao)

    if paralelo:
        # Várias ao mesmo tempo (as que esperam processos-filhos andam juntas);
        # cada uma sai assim que fica pronta - quem chama põe na ordem do
        # relatório. Sair na hora também mostra ao vigia que o processo não
        # travou enquanto uma checagem lenta ainda corre.
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="verificar") as pool:
            futuros = {pool.submit(comecar, nome): nome for nome in pedidos}
            for futuro in as_completed(futuros):
                emitir({"item": futuros[futuro], "dados": asdict(futuro.result())})
    else:
        for nome in pedidos:
            emitir({"item": nome, "dados": asdict(comecar(nome))})
    return 0


def _resultado_do_item(dados: dict) -> Resultado:
    situacao = str(dados.get("situacao") or FALHA)
    if situacao not in (OK, AVISO, FALHA):
        situacao = FALHA
    obrigatorio = bool(dados.get("obrigatorio", True))
    if situacao == FALHA and not obrigatorio:
        situacao = AVISO        # opcional: não reprova a instalação
    acao = str(dados.get("acao") or "")
    return Resultado(str(dados.get("nome") or "Verificação"), situacao,
                     str(dados.get("detalhe") or ""), acao if situacao != OK else "")


def conferir_motor(cfg=None, ao_resultado: Callable[[Resultado], None] | None = None
                   ) -> list[Resultado]:
    """As checagens de helestron.verificar, num processo à parte.

    Se o processo cair (biblioteca nativa quebrada) ou travar, a checagem
    em curso vira FALHA com a explicação, e as que faltam rodam num processo
    novo. Com várias em curso na hora da queda, elas são repetidas uma a
    uma, para achar a culpada. 'ao_resultado' recebe cada item pronto.
    """
    from .. import verificar
    from ..nucleo import config

    cfg = cfg or config.carregar(criar=False)
    nomes = nomes_do_motor(cfg)
    pasta = str(_pasta_do_pacote().parent)
    feitos: dict[str, Resultado] = {}

    def guardar(nome: str, r: Resultado) -> None:
        feitos[nome] = r
        if ao_resultado is not None:
            try:
                ao_resultado(r)
            except Exception:                       # noqa: BLE001 - o relatório nunca derruba
                log.exception("falha ao registrar o resultado %s", nome)

    pendentes, paralelo = list(nomes), True
    prazo = time.monotonic() + LIMITE_MOTOR_S
    while pendentes:
        resta = prazo - time.monotonic()
        if resta <= 1:
            for nome in pendentes:
                guardar(nome, Resultado(nome, FALHA, "Não foi conferido: a verificação passou do "
                                                     "tempo.", REINSTALAR))
            break
        argumentos = [verificar._python(), "-c", _SONDA_MOTOR, *(["--paralelo"] if paralelo else []),
                      *pendentes]
        codigo, saida, erro, estourou = verificar.rodar(
            argumentos, resta, [pasta], sem_novidade_s=min(resta, SEM_NOVIDADE_MOTOR_S))
        iniciados: list[str] = []
        for linha in saida.splitlines():
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if "inicio" in d:
                iniciados.append(str(d["inicio"]))
            elif "item" in d and str(d["item"]) in pendentes:
                guardar(str(d["item"]), _resultado_do_item(d.get("dados") or {}))
        restantes = [n for n in pendentes if n not in feitos]
        if not restantes:
            break
        em_curso = [n for n in iniciados if n in restantes]
        if not iniciados:
            # O próprio Python do programa não abriu (ou não achou o pacote).
            ultima = (erro.strip().splitlines() or [""])[-1][:300]
            motivo = f"o Python do programa não iniciou ({verificar.explicar_queda(None if estourou else codigo)})"
            if ultima:
                motivo += f": {ultima}"
            for nome in restantes:
                guardar(nome, Resultado(nome, FALHA, f"Não foi conferido: {motivo}.", REINSTALAR))
            break
        if estourou and paralelo and len(em_curso) > 1:
            # Várias em curso quando o processo calou: de novo, uma a uma, para
            # não culpar a que só estava esperando a vez de terminar.
            paralelo = False
            pendentes = em_curso + [n for n in restantes if n not in em_curso]
        elif estourou:
            for nome in em_curso:
                guardar(nome, Resultado(nome, FALHA,
                                        "A checagem não terminou no tempo esperado (travou).",
                                        REINSTALAR))
            pendentes = [n for n in restantes if n not in em_curso]
        elif len(em_curso) == 1:
            nome = em_curso[0]
            guardar(nome, Resultado(nome, FALHA,
                                    f"O processo da verificação caiu nesta checagem "
                                    f"({verificar.explicar_queda(codigo)}).", REINSTALAR))
            pendentes = [n for n in restantes if n != nome]
        elif not em_curso:
            if codigo == 0:
                for nome in restantes:
                    guardar(nome, Resultado(nome, FALHA, "Não foi conferido.", REINSTALAR))
                break
            pendentes = restantes
        else:
            # Várias ao mesmo tempo na hora da queda: de novo, uma a uma.
            paralelo = False
            pendentes = em_curso + [n for n in restantes if n not in em_curso]
    return [feitos[n] for n in nomes if n in feitos]


def conferir_janela() -> Resultado:
    from . import janela

    nome = NOME_JANELA
    if not NO_WINDOWS:
        return Resultado(nome, AVISO, "Não se aplica fora do Windows.")
    versao = janela.versao_webview2()
    if janela.versao_suficiente(versao):
        return Resultado(nome, OK, f"Microsoft Edge WebView2 Runtime {versao} instalado.")
    instalar = (f"Instale{' (ou atualize)' if versao else ''} o “Microsoft Edge WebView2 Runtime” "
                f"(gratuito, da Microsoft, sem administrador): {janela.URL_WEBVIEW2}")
    if versao:
        falta = (f"O WebView2 Runtime instalado é antigo (versão {versao}; o {NOME} precisa da 101 "
                 "ou de uma mais recente)")
    else:
        falta = "WebView2 ausente"
    if janela.achar_edge() is not None:
        return Resultado(nome, AVISO,
                         f"{falta}: o {NOME} abre no Microsoft Edge, em modo aplicativo.",
                         f"Para a janela própria do programa: {instalar[0].lower()}{instalar[1:]}.")
    if janela.navegador_padrao_serve():
        return Resultado(nome, AVISO,
                         f"{falta}, e o Microsoft Edge não foi encontrado: o {NOME} abre no "
                         "navegador padrão.", instalar + ".")
    return Resultado(nome, FALHA,
                     f"{falta}, o Microsoft Edge não foi encontrado e o navegador padrão é o "
                     f"Internet Explorer (ou o Edge antigo), que não roda o {NOME}: o programa "
                     "não tem como abrir a janela.",
                     instalar + ". Outra saída: instalar o Google Chrome e defini-lo como "
                                "navegador padrão.", codigo="sem_janela")


# ================================================================ relatório
def formatar(r: Resultado) -> list[str]:
    linhas = [f"  {ROTULOS.get(r.situacao, r.situacao.upper()):<7}{r.nome:<34}{r.detalhe}"]
    linhas += [f"         - {x}" for x in r.linhas]
    if r.acao and r.situacao != OK:
        linhas.append(f"         O que fazer: {r.acao}")
    return linhas


EM_ANDAMENTO = ("Verificação em andamento. Se o relatório terminar aqui, ela foi interrompida "
                "antes do fim (o processo caiu): instale o Helestron de novo com o "
                "Helestron-Setup e, se o problema continuar, envie este relatório ao suporte.")


def _gravar(destino: Path, texto: str) -> OSError | None:
    """Grava o relatório (troca atômica, para nunca ficar pela metade)."""
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.name + ".tmp")
        tmp.write_text(texto, encoding="utf-8")
        try:
            os.replace(tmp, destino)
        except OSError:
            # arquivo preso por um instante (antivírus, indexador): grava direto
            destino.write_text(texto, encoding="utf-8")
            tmp.unlink(missing_ok=True)
        return None
    except OSError as erro:
        return erro


def executar(relatorio: Path | None = None, saida: Callable[[str], None] | None = None,
             passos: list[Callable[[], Resultado | list[Resultado]]] | None = None) -> int:
    """Roda a verificação e devolve o código de saída.

    O relatório é regravado a cada item: se este processo cair no meio, o
    instalador ainda encontra o que já foi conferido e o aviso de que a
    verificação não terminou.
    """
    escrever = saida or (lambda texto: print(texto, flush=True))
    destino = Path(relatorio) if relatorio else arquivo_padrao()
    pasta = integridade.pasta_instalada()
    cabecalho = [f"{NOME} {__version__} — verificação da instalação",
                 f"Data: {datetime.now():%d/%m/%Y %H:%M:%S}",
                 f"Pasta do programa: {pasta or _pasta_do_pacote().parent}",
                 f"Sistema: {platform.platform()} · Python {platform.python_version()}", ""]
    for linha in cabecalho:
        escrever(linha)
    resultados: list[Resultado] = []        # na ordem em que ficaram prontos
    em_ordem: list[Resultado] = []          # na ordem do relatório final
    vistos: set[int] = set()
    problema: list[OSError] = []

    def gravar(fim: list[str], lista: list[Resultado] | None = None) -> None:
        erro = _gravar(destino, "\n".join(
            cabecalho + [linha for r in (resultados if lista is None else lista)
                         for linha in formatar(r)] + fim) + "\n")
        if erro is not None and not problema:
            problema.append(erro)

    def registrar(item: Resultado) -> None:
        if id(item) in vistos:
            return
        vistos.add(id(item))
        resultados.append(item)
        for linha in formatar(item):
            escrever(linha)
        gravar(["", EM_ANDAMENTO])

    gravar(["", EM_ANDAMENTO])          # o relatório existe desde o primeiro instante
    if passos is None:
        def conferir_o_resto() -> list[Resultado]:
            return conferir_motor(ao_resultado=registrar)

        passos = [conferir_manifesto, conferir_modulos, conferir_o_resto, conferir_janela]
    for passo in passos:
        try:
            r = passo()
        except Exception as erro:                   # noqa: BLE001 - vira falha no relatório
            log.exception("falha inesperada na verificação")
            r = Resultado(NOMES_DOS_PASSOS.get(getattr(passo, "__name__", ""), "Verificação"),
                          FALHA, f"Erro inesperado: {type(erro).__name__}: {erro}", REINSTALAR)
        for item in (r if isinstance(r, list) else [r]):
            registrar(item)
            em_ordem.append(item)
    falhas = [r for r in em_ordem if r.situacao == FALHA]
    avisos = [r for r in em_ordem if r.situacao == AVISO]
    if falhas:
        final = (f"Resultado: {len(falhas)} falha{'s' if len(falhas) != 1 else ''}. A instalação "
                 "tem problemas: veja acima o que fazer.")
    elif avisos:
        final = (f"Resultado: pronta, com {len(avisos)} aviso{'s' if len(avisos) != 1 else ''} "
                 "(veja acima).")
    else:
        final = "Resultado: tudo certo. A instalação está pronta."
    escrever("")
    escrever(final)
    gravar(["", final], em_ordem)
    if problema:
        escrever(f"Não foi possível gravar o relatório em {destino}: {problema[0]}")
    else:
        escrever(f"Relatório: {destino}")
    if falhas and all(r.codigo == "sem_janela" for r in falhas):
        return CODIGO_SEM_JANELA
    return 1 if falhas else 0


NOMES_DOS_PASSOS = {"conferir_manifesto": "Arquivos do programa",
                    "conferir_modulos": "Módulos do programa",
                    "conferir_o_resto": "Componentes do programa",
                    "conferir_motor": "Componentes do programa",
                    "conferir_janela": NOME_JANELA}
