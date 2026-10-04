"""python -m helestron --verificar-instalacao [--relatorio ARQ]: a conferência do instalador.

Sem janela. O instalador roda isto ao final e, se o código de saída for 1,
mostra o resumo e onde está o relatório. Confere, nesta ordem:

  1. o manifesto: existência, tamanho e SHA-256 de TODOS os arquivos
     instalados (o arquivo que o antivírus levou aparece aqui, pelo nome);
  2. os módulos: importa TODOS os módulos do pacote helestron (percorrido
     com pkgutil.walk_packages), num processo à parte - um módulo que falte
     ou não carregue aparece aqui, e não no meio do uso, como o "No module
     named 'app.interface.pagina_config'" da versão anterior;
  3. o restante, por helestron.verificar: bibliotecas, componentes nativos,
     modelo de transcrição (carregado de verdade, se estiver embutido),
     navegador, pastas, cofre de senhas;
  4. a janela: WebView2 ou, na falta dele, o Edge.

Relatório em texto UTF-8 (padrão: LOCAL\\Logs\\verificacao-instalacao.txt).
Código de saída: 0 = pronto (talvez com avisos); 1 = falha.
"""

from __future__ import annotations

import logging
import pkgutil
import platform
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import NOME, __version__
from ..nucleo import caminhos
from . import integridade

log = logging.getLogger("aplicativo.verificacao")

OK, AVISO, FALHA = "ok", "aviso", "falha"
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


def modulos_do_pacote() -> tuple[list[str], list[tuple[str, str]]]:
    """(nomes de todos os módulos do pacote helestron, pacotes que falharam
    ao ser percorridos)."""
    import helestron

    nomes = ["helestron"]
    erros: list[tuple[str, str]] = []

    def ao_erro(nome: str) -> None:
        tipo, valor, _ = sys.exc_info()
        erros.append((nome, f"{tipo.__name__ if tipo else 'Erro'}: {valor}"))

    for info in pkgutil.walk_packages(helestron.__path__, "helestron.", onerror=ao_erro):
        nomes.append(info.name)
    return nomes, erros


def importar_todos() -> list[tuple[str, str]]:
    """[(módulo, erro)] dos módulos que não carregaram. Num processo à parte:
    importar uma biblioteca nativa quebrada pode derrubar o processo."""
    from .. import verificar

    nomes, erros = modulos_do_pacote()
    pasta = str(Path(__file__).resolve().parents[2])
    resultado = verificar.sondar_importacoes(nomes, 600.0, [pasta])
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


def conferir_motor(cfg=None) -> list[Resultado]:
    """As checagens de helestron.verificar (bibliotecas, modelo, navegador...)."""
    from .. import verificar

    saida = []
    for i in verificar.verificar(completo=False, cfg=cfg):
        situacao = i.situacao
        if situacao == FALHA and not i.obrigatorio:
            situacao = AVISO
        saida.append(Resultado(i.nome, situacao, i.detalhe, i.acao if situacao != OK else ""))
    # O modelo embutido carrega de verdade (1 s de silêncio).
    try:
        from ..nucleo import config

        item = verificar.checar_teste_transcricao(cfg or config.carregar(criar=False))
        situacao = item.situacao if item.obrigatorio or item.situacao != FALHA else AVISO
        saida.append(Resultado(item.nome, situacao, item.detalhe, item.acao))
    except Exception as erro:                       # noqa: BLE001
        saida.append(Resultado("Teste de transcrição", AVISO, f"{type(erro).__name__}: {erro}"))
    return saida


def conferir_janela() -> Resultado:
    from . import janela

    if sys.platform != "win32":
        return Resultado("Janela (WebView2)", AVISO, "Não se aplica fora do Windows.")
    if janela.webview2_disponivel():
        return Resultado("Janela (WebView2)", OK, "WebView2 Runtime instalado.")
    edge = janela.achar_edge()
    if edge is not None:
        return Resultado("Janela (WebView2)", AVISO,
                         "WebView2 ausente: o Helestron abre no Microsoft Edge, em modo "
                         "aplicativo.", "Instale o WebView2 Runtime da Microsoft para a janela "
                                        "própria do programa.")
    return Resultado("Janela (WebView2)", AVISO,
                     "Nem WebView2 nem Edge encontrados: o Helestron abre no navegador padrão.",
                     "Instale o WebView2 Runtime da Microsoft.")


# ================================================================ relatório
def formatar(r: Resultado) -> list[str]:
    linhas = [f"  {ROTULOS.get(r.situacao, r.situacao.upper()):<7}{r.nome:<34}{r.detalhe}"]
    linhas += [f"         - {x}" for x in r.linhas]
    if r.acao and r.situacao != OK:
        linhas.append(f"         O que fazer: {r.acao}")
    return linhas


def executar(relatorio: Path | None = None, saida: Callable[[str], None] | None = None,
             passos: list[Callable[[], Resultado | list[Resultado]]] | None = None) -> int:
    """Roda a verificação, grava o relatório e devolve o código de saída."""
    escrever = saida or (lambda texto: print(texto, flush=True))
    destino = Path(relatorio) if relatorio else arquivo_padrao()
    pasta = integridade.pasta_instalada()
    cabecalho = [f"{NOME} {__version__} — verificação da instalação",
                 f"Data: {datetime.now():%d/%m/%Y %H:%M:%S}",
                 f"Pasta do programa: {pasta or Path(__file__).resolve().parents[2]}",
                 f"Sistema: {platform.platform()} · Python {platform.python_version()}", ""]
    for linha in cabecalho:
        escrever(linha)
    if passos is None:
        passos = [conferir_manifesto, conferir_modulos, conferir_motor, conferir_janela]
    resultados: list[Resultado] = []
    for passo in passos:
        try:
            r = passo()
        except Exception as erro:                   # noqa: BLE001 - vira falha no relatório
            log.exception("falha inesperada na verificação")
            r = Resultado(getattr(passo, "__name__", "Verificação"), FALHA,
                          f"Erro inesperado: {type(erro).__name__}: {erro}")
        for item in (r if isinstance(r, list) else [r]):
            resultados.append(item)
            for linha in formatar(item):
                escrever(linha)
    falhas = [r for r in resultados if r.situacao == FALHA]
    avisos = [r for r in resultados if r.situacao == AVISO]
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
    texto = "\n".join(cabecalho + [linha for r in resultados for linha in formatar(r)]
                      + ["", final]) + "\n"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        escrever(f"Relatório: {destino}")
    except OSError as erro:
        escrever(f"Não foi possível gravar o relatório em {destino}: {erro}")
    return 1 if falhas else 0
