"""Ponto de entrada: `python -m helestron` abre o programa; com opção ou subcomando,
a linha de comando. O lançador Helestron.exe roda `python -I -m helestron`.

    python -m helestron                               abre o programa (servidor + janela)
    python -m helestron --verificar-instalacao [--relatorio ARQ]
                                                      confere a instalação, sem janela
    python -m helestron --autoteste PASTA             percorre a interface e salva capturas
    python -m helestron --servidor [--porta N] [--sem-janela] [--token T]
                                                      só o servidor (imprime URL=...)
    python -m helestron --encerrar                    pede ao programa aberto que feche
    python -m helestron baixar --lista X.xlsx         baixa os processos da relação
    python -m helestron transcrever ARQUIVO           transcreve uma gravação
    python -m helestron modelos baixar small          baixa um modelo de transcrição
    python -m helestron falantes instalar             baixa os modelos da separação de falantes
    python -m helestron microfones                    lista os microfones
    python -m helestron verificar [--completo]        confere a instalação (detalhado)
    python -m helestron mcp --pasta ACERVO            servidor MCP do acervo (Claude/ChatGPT)
    python -m helestron preparar [--sem-texto] [--json]
                                                      prepara o acervo para a IA (textos e índice)
    python -m helestron preparar --pasta PASTA [--texto-em _texto] [--incluir-sigilosos] [--json]
                                                      só o texto dos autos de uma pasta de lote
    python -m helestron preparar-pastas               cria o config.ini e as pastas de trabalho
    python -m helestron caminhos [--json]             onde o programa guarda cada coisa
    python -m helestron pauta sincronizar|exportar|importar ...
                                                      a pauta de audiências
    python -m helestron --version                     a versão do programa

Códigos de saída de "preparar": 0 tudo certo; 1 algum arquivo com problema;
2 uso errado (opção desconhecida, pasta que não existe); 3 autos de processo
sigiloso presos no acervo - não compartilhe o acervo até movê-los.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from .nucleo.argumentos import ArgumentParser
except ImportError:                     # instalação quebrada: o do argparse serve
    from argparse import ArgumentParser

# Os subcomandos: o resto da linha vai inteiro para a linha de comando de cada um.
SUBCOMANDOS = ("baixar", "transcrever", "modelos", "falantes", "microfones", "verificar", "mcp",
               "pauta", "preparar", "preparar-pastas", "caminhos")

COMANDOS = """comandos (cada um tem a própria ajuda: python -m helestron <comando> -h):
  baixar --lista X.xlsx       baixa os processos da relação
  transcrever ARQUIVO         transcreve uma gravação
  modelos baixar small        baixa um modelo de transcrição
  falantes instalar           baixa os modelos da separação de falantes
  microfones                  lista os microfones
  verificar [--completo]      confere a instalação (detalhado)
  mcp --pasta ACERVO          servidor MCP do acervo (Claude/ChatGPT)
  preparar                    prepara o acervo para a IA (textos e índice)
  preparar --pasta PASTA      só o texto dos autos de uma pasta de lote
  preparar-pastas             cria o config.ini e as pastas de trabalho
  caminhos [--json]           onde o programa guarda cada coisa (não cria nada)
  pauta sincronizar|exportar|importar ...
                              a pauta de audiências

Sem argumentos, abre o programa (servidor + janela)."""

# O que esta versão oferece a quem a automatiza (a skill do Claude consulta
# em "caminhos --json" e, numa versão sem o recurso, segue pelo caminho antigo).
RECURSOS = ("versao", "caminhos", "baixar.json", "baixar.eventos", "baixar.log", "baixar.texto",
            "baixar.retomar", "baixar.completar", "baixar.esperar-navegador",
            "baixar.rebaixar-incompletos", "baixar.sem-cofre", "baixar.desanexar",
            "relatorio.causa", "relatorio.meta", "paginacao.manifesto", "preparar.pasta",
            "preparar.json")

SAIDA_SIGILOSO_NO_ACERVO = 3     # "preparar": autos de sigiloso presos no acervo

REINSTALAR = ("Isso costuma acontecer quando o antivírus põe um arquivo em quarentena, ou quando "
              "a instalação foi interrompida. Instale o Helestron de novo com o Helestron-Setup: "
              "ele conserta a instalação sem apagar os seus dados.")


def _ambiente() -> None:
    # O programa não traz navegador próprio: o download e a pauta usam o
    # Google Chrome ou o Microsoft Edge do computador (download/navegador.py),
    # e por isso PLAYWRIGHT_BROWSERS_PATH não é definido aqui.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def _mensagem(titulo: str, texto: str) -> None:
    """Caixa de mensagem sem depender de nada do pacote (instalação quebrada)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, texto, titulo, 0x10 | 0x40000)
            return
        except Exception:
            pass
    try:
        print(f"{titulo}\n\n{texto}", file=sys.stderr)
    except Exception:
        pass


def parte_que_falta(erro: ImportError) -> str:
    """O módulo que faltou, pelo texto do erro: "No module named 'x.y'" -> x.y;
    "cannot import name 'z' from 'x.y' (...)" -> x.y.z (erro.name diria só o
    pacote, x.y)."""
    texto = str(erro)
    achado = re.match(r"cannot import name '([^']+)' from '([^']+)'", texto)
    if achado:
        return f"{achado.group(2)}.{achado.group(1)}"
    achado = re.match(r"No module named '([^']+)'", texto)
    if achado:
        return achado.group(1)
    return getattr(erro, "name", "") or texto


def _anotar_erro(contexto: str) -> None:
    """O erro em andamento vai para o registro (Logs): é para lá que a mensagem
    do lançador aponta quando o programa fecha logo depois de começar."""
    try:
        import logging

        from .nucleo import registro

        if not any(getattr(h, "_helestron", False) for h in logging.getLogger().handlers):
            registro.configurar(console=False)
        logging.getLogger("helestron").exception(contexto)
    except Exception:
        pass


def abrir_programa(autoteste: Path | None = None) -> int:
    try:
        from .aplicativo import inicio
    except ImportError as erro:
        # Arquivo do programa ausente (antivírus, instalação interrompida):
        # nem a tela de erro própria pode abrir.
        _anotar_erro("falta uma parte do programa")
        _mensagem("O Helestron não pôde abrir",
                  f"Falta uma parte do programa ({parte_que_falta(erro)}).\n\n{REINSTALAR}")
        return 1
    try:
        return inicio.main(autoteste=autoteste)
    except Exception:
        _anotar_erro("o Helestron fechou por um erro inesperado")
        return 1


def _relatorio_sem_o_programa(args: list[str], erro: ImportError) -> None:
    """--verificar-instalacao sem o registro do programa: um relatório mínimo,
    para o instalador dizer o que falta (sem ele, só "não conseguiu terminar")."""
    destino = None
    for i, a in enumerate(args):
        if a == "--relatorio" and i + 1 < len(args):
            destino = Path(args[i + 1])
        elif a.startswith("--relatorio="):
            destino = Path(a.split("=", 1)[1])
    if destino is None:
        local = os.environ.get("HELESTRON_LOCAL") or (
            str(Path(os.environ["LOCALAPPDATA"]) / "Helestron") if os.environ.get("LOCALAPPDATA") else "")
        if not local:
            return
        destino = Path(local) / "Logs" / "verificacao-instalacao.txt"
    texto = (f"Helestron — verificação da instalação\nData: {datetime.now():%d/%m/%Y %H:%M:%S}\n\n"
             f"  FALHA  Falta uma parte do programa: {parte_que_falta(erro)}\n"
             f"         - {erro}\n"
             f"         O que fazer: {REINSTALAR}\n")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    except OSError:
        pass


def _sem_parte_de_partida(args: list[str], erro: ImportError) -> int:
    """Falta o registro (ou o caminhos) do pacote: nada mais do programa roda."""
    if not args or args[0].startswith("--autoteste"):
        _mensagem("O Helestron não pôde abrir",
                  f"Falta uma parte do programa ({parte_que_falta(erro)}).\n\n{REINSTALAR}")
    elif args[0] == "--verificar-instalacao":
        _relatorio_sem_o_programa(args[1:], erro)       # o instalador informa o usuário
    else:
        try:
            print(f"Falta uma parte do programa ({parte_que_falta(erro)}). {REINSTALAR}",
                  file=sys.stderr)
        except Exception:
            pass
    return 1


def _formatador() -> type:
    """A ajuda com o "uso:" em português e a lista de comandos como foi escrita."""
    try:
        from .nucleo.argumentos import Formatador
    except ImportError:
        Formatador = argparse.HelpFormatter

    class FormatadorDosComandos(Formatador, argparse.RawDescriptionHelpFormatter):
        pass

    return FormatadorDosComandos


def _versao() -> str:
    try:
        from . import __version__
    except ImportError:                 # pragma: no cover - o pacote sempre tem versão
        __version__ = "?"
    return __version__


def analisador() -> argparse.ArgumentParser:
    p = ArgumentParser(prog="python -m helestron", formatter_class=_formatador(),
                       description="Helestron: baixa processos, transcreve audiências, monitora a\n"
                                   "pauta de audiências e prepara o acervo para a IA.",
                       epilog=COMANDOS)
    p.add_argument("--version", "--versao", action="version", version=f"Helestron {_versao()}",
                   help="mostra a versão do programa e sai")
    o_que = p.add_mutually_exclusive_group()
    o_que.add_argument("--verificar-instalacao", action="store_true",
                       help="confere a instalação, sem janela (o instalador usa)")
    o_que.add_argument("--autoteste", metavar="PASTA",
                       help="percorre todas as telas e salva as capturas na PASTA")
    o_que.add_argument("--servidor", action="store_true",
                       help="só o servidor local (imprime URL=...)")
    o_que.add_argument("--encerrar", action="store_true",
                       help="pede ao programa aberto que feche (o instalador usa)")
    p.add_argument("--relatorio", metavar="ARQ",
                   help="com --verificar-instalacao: onde gravar o relatório")
    p.add_argument("--porta", type=int, metavar="N",
                   help="com --servidor: a porta (padrão: uma livre)")
    p.add_argument("--sem-janela", action="store_true", help="com --servidor: sem abrir a janela")
    p.add_argument("--token", metavar="T", help="com --servidor: o token (padrão: um aleatório)")
    return p


def servidor(porta: int | None = None, token: str | None = None, sem_janela: bool = False) -> int:
    """--servidor: só o servidor local (testes e desenvolvimento)."""
    from .nucleo import registro
    from .servidor.aplicacao import Aplicacao

    try:
        registro.configurar(console=False)
    except Exception:
        pass
    app = Aplicacao(modo="servidor", token=token or None, porta=porta or 0).iniciar()
    print(f"URL={app.url}", flush=True)
    try:
        if sem_janela:
            while not app.esperar(0.5):
                pass
        else:
            from .aplicativo import janela
            from .aplicativo.monitor import MonitorPauta

            app.monitor = MonitorPauta(app).iniciar()
            janela.abrir(app, app.url)
    except KeyboardInterrupt:
        pass
    finally:
        app.encerrar()
    return 0


def _subcomando(comando: str, resto: list[str]) -> int:
    if comando == "baixar":
        from .download import cli

        return cli.main(resto)
    if comando in ("transcrever", "modelos", "falantes", "microfones"):
        from .transcricao import cli

        return cli.main([comando] + resto)
    if comando == "verificar":
        from . import verificar

        return verificar.main(resto)
    if comando == "mcp":
        from .compartilhar import mcp_servidor

        return mcp_servidor.main(resto)
    if comando == "pauta":
        from .pauta import cli

        return cli.main(resto)
    # Os demais têm a linha de comando aqui: -h mostra a ajuda e opção
    # desconhecida sai com 2 ANTES de qualquer efeito (antes, "preparar -h"
    # preparava o acervo inteiro e "preparar-pastas --xyz" criava as pastas).
    try:
        opcoes = _analisador_do_subcomando(comando).parse_args(resto)
    except SystemExit as saida:             # -h (0) ou erro na linha de comando (2)
        return saida.code if isinstance(saida.code, int) else 2
    if comando == "caminhos":
        return _caminhos(opcoes)
    if comando == "preparar":
        return _preparar(opcoes)
    # preparar-pastas
    from .nucleo import config

    cfg = config.carregar()
    cfg.criar_pastas()
    print(f"Configuração: {cfg.arquivo}")
    print(f"Acervo: {cfg.pasta_acervo}")
    return 0


def _analisador_do_subcomando(comando: str) -> argparse.ArgumentParser:
    if comando == "caminhos":
        p = ArgumentParser(prog="python -m helestron caminhos",
                           description="Mostra onde o programa guarda cada coisa (acervo, "
                                       "sigilosos, pauta, configuração, registros) e o que esta "
                                       "versão oferece. Não cria nada. Senhas, perfis do "
                                       "navegador e sessões não aparecem.")
        p.add_argument("--json", action="store_true", help="saída em JSON, para programas")
        return p
    if comando == "preparar":
        p = ArgumentParser(
            prog="python -m helestron preparar",
            description="Prepara o acervo para a IA: tira dele o que é de processo sigiloso, "
                        "extrai o texto dos autos (com a marca da folha) e atualiza o índice e "
                        "os arquivos de contexto (CLAUDE.md, AGENTS.md). Com --pasta, só "
                        "extrai o texto dos autos de uma pasta de lote, sem mexer no resto. "
                        "Saída: 0 tudo certo; 1 algum arquivo com problema; 2 uso errado; "
                        "3 autos de processo sigiloso presos no acervo (não compartilhe).")
        p.add_argument("--pasta", metavar="PASTA",
                       help="só o texto dos autos (PDFs) desta pasta de lote; não grava "
                            "CLAUDE.md, AGENTS.md, INDICE.md nem Produtos")
        p.add_argument("--texto-em", metavar="SUBPASTA", default="_texto",
                       help="com --pasta: onde gravar os textos (padrão: _texto, dentro da "
                            "pasta)")
        p.add_argument("--incluir-sigilosos", action="store_true",
                       help="com --pasta: também o texto dos autos sigilosos do lote, na pasta "
                            "de sigilosos dele (fora do acervo)")
        p.add_argument("--sem-texto", action="store_true",
                       help="sem --pasta: não extrair o texto dos autos (só índice e contexto)")
        p.add_argument("--json", action="store_true", help="saída em JSON, para programas")
        return p
    p = ArgumentParser(prog="python -m helestron preparar-pastas",
                       description="Cria o config.ini (se faltar) e as pastas de trabalho: "
                                   "Acervo\\Processos, Acervo\\Transcricoes, Sigilosos e Pauta.")
    return p


def _imprimir_json(dados: dict) -> None:
    print(json.dumps(dados, ensure_ascii=False, indent=1, default=str))


def _caminhos(opcoes) -> int:
    """Os caminhos do programa, sem criar nada (nem o config.ini) e sem os
    perfis do navegador, o arquivo de senhas e a sessão guardada - que nenhum
    programa de fora deve ler."""
    from .nucleo import caminhos, config

    cfg = config.carregar(criar=False)
    # como o download lê (modelos._modo_login): o que não for um dos três é "senha"
    login = {}
    for sistema in ("esaj", "eproc"):
        modo = (cfg.texto(sistema, "login") or "").strip().lower()
        login[sistema] = modo if modo in ("senha", "certificado", "manual") else "senha"
    dados = {
        "versao": _versao(),
        "recursos": list(RECURSOS),
        "python": str(caminhos.python_exe()),
        "instalacao": str(caminhos.INSTALACAO),
        "instalado": bool(caminhos.INSTALADO),
        "config": str(cfg.arquivo),
        "config_existe": cfg.arquivo.is_file(),
        "logs": str(caminhos.LOGS),
        "acervo": str(cfg.pasta_acervo),
        "processos": str(cfg.pasta_processos),
        "transcricoes": str(cfg.pasta_transcricoes),
        "sigilosos": str(cfg.pasta_sigilosos),
        "pauta": str(cfg.pasta_pauta),
        "separar_sigilosos": cfg.flag("download", "separar_sigilosos"),
        "login": login,
        "espera_login_min": cfg.inteiro("download", "espera_login_minutos"),
        "conflito_de_pastas": cfg.conflito_de_pastas(),
    }
    if opcoes.json:
        _imprimir_json(dados)
        return 0
    for chave, valor in dados.items():
        if isinstance(valor, (list, tuple)):
            valor = ", ".join(str(v) for v in valor)
        elif isinstance(valor, dict):
            valor = ", ".join(f"{k}={v}" for k, v in valor.items())
        elif isinstance(valor, bool):
            valor = "sim" if valor else "não"
        print(f"{chave}: {valor}")
    return 0


def _dentro(caminho, pasta) -> bool:
    try:
        Path(caminho).resolve().relative_to(Path(pasta).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _preparar(opcoes) -> int:
    from .nucleo import config, registro

    if opcoes.pasta is None and (opcoes.incluir_sigilosos or opcoes.texto_em != "_texto"):
        print("--texto-em e --incluir-sigilosos só valem com --pasta.", file=sys.stderr)
        return 2
    if opcoes.pasta is not None and opcoes.sem_texto:
        print("--sem-texto não vale com --pasta (que só extrai o texto).", file=sys.stderr)
        return 2
    try:
        registro.configurar(console=not opcoes.json)
    except Exception:
        pass
    cfg = config.carregar()
    if opcoes.pasta is not None:
        return _preparar_pasta(opcoes, cfg)

    from .compartilhar import preparo

    rel = preparo.atualizar_contexto(cfg, extrair_texto=False if opcoes.sem_texto else None)
    codigo = SAIDA_SIGILOSO_NO_ACERVO if rel.sigilosos_no_acervo else (1 if rel.erros else 0)
    if opcoes.json:
        _imprimir_json({
            "acervo": str(cfg.pasta_acervo), "resumo": rel.resumo, "processos": rel.processos,
            "transcricoes": rel.transcricoes, "textos_novos": rel.textos_novos,
            "sigilosos_levados": rel.sigilosos_levados,
            "sigilosos_no_acervo": [str(p) for p in rel.sigilosos_no_acervo],
            "sigilosos_avisos": [str(p) for p in rel.sigilosos_avisos],
            "motivos": {str(k): str(v) for k, v in (rel.motivos or {}).items()},
            "erros": list(rel.erros), "avisos": list(rel.avisos),
            "pode_compartilhar": not rel.sigilosos_no_acervo, "codigo_saida": codigo})
        return codigo
    print(rel.resumo)
    # O que deu errado e o que se fez, com o arquivo e o porquê - inclusive a
    # frase dos autos de sigiloso presos no acervo (quem chama sem terminal,
    # como uma skill, não vê o log da tela)
    for erro in rel.erros:
        print(f"  {erro}", file=sys.stderr)
    for aviso in rel.avisos:
        print(f"  aviso: {aviso}")
    if rel.sigilosos_no_acervo:
        print("ATENÇÃO: autos de processo sigiloso continuam no acervo: não o compartilhe "
              "até movê-los para a pasta dos sigilosos.", file=sys.stderr)
    return codigo


def _preparar_pasta(opcoes, cfg) -> int:
    """preparar --pasta: o texto dos autos de uma pasta de lote, e nada mais."""
    from .compartilhar import textos
    from .download import motor
    from .nucleo import paginacao, sigilo

    pasta = Path(opcoes.pasta).expanduser()
    if not pasta.is_dir():
        print(f"A pasta {pasta} não existe.", file=sys.stderr)
        return 2
    texto_em = Path(opcoes.texto_em).expanduser()
    acervo = Path(cfg.pasta_acervo)
    no_acervo = _dentro(pasta, acervo)
    # Dentro do acervo, o que é sigiloso pela regra única não vira texto ali
    sigilosas = sigilo.chaves_sigilosas(cfg.pasta_sigilosos, raiz=acervo) if no_acervo else None
    pastas = [(pasta, texto_em if texto_em.is_absolute() else pasta / texto_em, False)]
    if opcoes.incluir_sigilosos:
        sig = motor.pasta_sigilosos_do_lote(cfg.pasta_sigilosos, pasta,
                                            getattr(cfg, "pasta_processos", None))
        # O texto do sigiloso fica com ele, na pasta de sigilosos - nunca na
        # pasta pedida em --texto-em (que pode ser o acervo)
        alvo = sig / (texto_em if not texto_em.is_absolute() else Path("_texto"))
        if sig.is_dir():
            pastas.append((sig, alvo, True))
    itens: list[dict] = []
    for origem, destino, da_pasta_de_sigilosos in pastas:
        for pdf in sorted(p for p in origem.glob("*.pdf") if p.is_file()):
            chave = motor.chave_do_nome(pdf.name)
            item = {"pdf": str(pdf), "texto": "", "situacao": "", "erro": "",
                    "sigiloso": da_pasta_de_sigilosos, "paginas": 0, "paginacao": None}
            if sigilosas is not None and not da_pasta_de_sigilosos and chave \
                    and sigilo.contem(sigilosas, chave):
                item.update(situacao="sigiloso_ignorado", sigiloso=True,
                            erro="processo sigiloso: o texto não é gerado dentro do acervo")
                itens.append(item)
                continue
            alvo = destino / f"{pdf.stem}.txt"
            try:
                antes = alvo.stat().st_mtime if alvo.exists() else None
                textos.garantir_texto(pdf, alvo)
                novo = antes is None or alvo.stat().st_mtime != antes
                item.update(texto=str(alvo), situacao="novo" if novo else "em_dia",
                            paginas=textos.contar_paginas(pdf))
                m = paginacao.ler_do_pdf(pdf)
                item["paginacao"] = motor.essencial_da_paginacao(m) or {
                    "garantida": False, "resumo": paginacao.resumo(None)}
            except Exception as erro:   # PDF corrompido não para o resto
                item.update(situacao="falhou", erro=str(erro)[:300])
            itens.append(item)
    falhas = [i for i in itens if i["situacao"] == "falhou"]
    codigo = 1 if falhas else 0
    if opcoes.json:
        _imprimir_json({"pasta": str(pasta), "itens": itens, "codigo_saida": codigo})
        return codigo
    prontos = sum(1 for i in itens if i["situacao"] in ("novo", "em_dia"))
    novos = sum(1 for i in itens if i["situacao"] == "novo")
    ignorados = sum(1 for i in itens if i["situacao"] == "sigiloso_ignorado")
    texto = f"{prontos} texto{'s' if prontos != 1 else ''} pronto{'s' if prontos != 1 else ''}"
    if novos:
        texto += f" ({novos} extraído{'s' if novos != 1 else ''} agora)"
    if ignorados:
        texto += f", {ignorados} de processo sigiloso sem texto (dentro do acervo)"
    if falhas:
        texto += f", {len(falhas)} com problema"
    print(texto + ".")
    for i in falhas:
        print(f"  {Path(i['pdf']).name}: {i['erro']}", file=sys.stderr)
    return codigo


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        from .nucleo import registro

        registro.preparar_saidas()
    except ImportError as erro:
        return _sem_parte_de_partida(args, erro)
    _ambiente()

    if not args:
        return abrir_programa()
    comando, resto = args[0], args[1:]
    if comando in SUBCOMANDOS:
        return _subcomando(comando, resto)
    p = analisador()
    if comando in ("--ajuda", "ajuda"):
        p.print_help()
        return 0
    try:
        if not comando.startswith("-"):
            p.error(f"comando desconhecido: {comando} (comandos: {', '.join(SUBCOMANDOS)})")
        opcoes = p.parse_args(args)
        if opcoes.relatorio is not None and not opcoes.verificar_instalacao:
            p.error("--relatorio só vale com --verificar-instalacao")
        if (opcoes.porta is not None or opcoes.sem_janela or opcoes.token is not None) \
                and not opcoes.servidor:
            p.error("--porta, --sem-janela e --token só valem com --servidor")
        if not (opcoes.verificar_instalacao or opcoes.autoteste or opcoes.servidor
                or opcoes.encerrar):
            p.error("diga o que fazer: --verificar-instalacao, --autoteste, --servidor, "
                    "--encerrar ou um comando")
    except SystemExit as saida:             # -h (0) ou erro na linha de comando (2)
        return saida.code if isinstance(saida.code, int) else 2

    if opcoes.verificar_instalacao:
        from .aplicativo import verificacao

        try:
            registro.configurar(console=False)
        except Exception:
            pass
        return verificacao.executar(Path(opcoes.relatorio) if opcoes.relatorio else None)
    if opcoes.autoteste:
        return abrir_programa(Path(opcoes.autoteste))
    if opcoes.servidor:
        return servidor(opcoes.porta, opcoes.token, opcoes.sem_janela)
    from .aplicativo import instancia

    return instancia.encerrar_aberta()


if __name__ == "__main__":
    sys.exit(main())
