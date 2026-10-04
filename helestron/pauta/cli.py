"""Linha de comando da pauta de audiências.

    python -m helestron pauta sincronizar [--fonte ID ...] [--de AAAA-MM-DD] [--ate AAAA-MM-DD]
    python -m helestron pauta exportar --de 2026-10-01 --ate 2026-10-31 [--pasta DIR]
    python -m helestron pauta importar relatorio.xls [outro.pdf ...]
    python -m helestron pauta listar [--de ...] [--ate ...] [--sistema esaj|eproc] [--json]
    python -m helestron pauta fontes [--adicionar TRIBUNAL SISTEMA [--url URL]] [--remover ID]

O mesmo ServicoPauta da janela, com o mesmo banco (LOCAL/pauta.sqlite3) e a
mesma configuração. Na sincronização, o código de verificação do portal é
pedido no próprio terminal. Serve ao CI do Windows (exportação da pauta) e
a quem prefere o Prompt de Comando.

Códigos de saída: 0 tudo certo; 1 falhou (a frase diz por quê); 2 uso
errado (opção inválida, data ilegível).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger("pauta.cli")


class _Formatador(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        # prefix "" é o argparse montando o nome do subcomando: fica sem prefixo
        return super().add_usage(usage, actions, groups, "uso: " if prefix is None else prefix)


class _Parser(argparse.ArgumentParser):
    """argparse em português (ajuda, títulos e erros)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", _Formatador)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "argumentos"
        self._optionals.title = "opções"
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS,
                          help="mostra esta ajuda e sai")

    def error(self, message):
        traducoes = (("the following arguments are required", "faltam os argumentos"),
                     ("unrecognized arguments", "argumentos não reconhecidos"),
                     ("invalid choice", "escolha inválida"),
                     ("expected one argument", "falta o valor"),
                     ("argument", "argumento"))
        for de, para in traducoes:
            message = message.replace(de, para)
        self.print_usage(sys.stderr)
        print(f"{self.prog}: erro: {message}", file=sys.stderr)
        raise SystemExit(2)


def _data(texto: str) -> date:
    try:
        return date.fromisoformat(texto.strip())
    except ValueError:
        from .modelos import ler_data

        d = ler_data(texto)
        if d is None:
            raise argparse.ArgumentTypeError(f"data inválida: {texto} (use AAAA-MM-DD)")
        return d


def criar_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m helestron pauta",
                description="Pauta de audiências do Helestron: sincronizar com o e-SAJ e o eProc, "
                            "importar relatórios, listar e exportar em Excel.")
    sub = p.add_subparsers(dest="comando", parser_class=_Parser, metavar="COMANDO",
                           title="comandos")

    s = sub.add_parser("sincronizar", help="lê a pauta nos portais (fontes configuradas)")
    s.add_argument("--fonte", action="append", default=[], metavar="ID",
                   help="só esta fonte (pode repetir); padrão: todas")
    s.add_argument("--de", type=_data, metavar="AAAA-MM-DD", help="início do período (padrão: hoje menos [pauta] "
                                            "dias_atras)")
    s.add_argument("--ate", type=_data, metavar="AAAA-MM-DD", help="fim do período (padrão: hoje mais [pauta] "
                                             "dias_a_frente)")

    e = sub.add_parser("exportar", help="grava a planilha Excel do período")
    e.add_argument("--de", type=_data, metavar="AAAA-MM-DD", help="início do período (padrão: hoje)")
    e.add_argument("--ate", type=_data, metavar="AAAA-MM-DD", help="fim do período (padrão: hoje mais 30 dias)")
    e.add_argument("--sistema", choices=("esaj", "eproc", "arquivo"), help="só um sistema")
    e.add_argument("--situacao", help="só uma situação (ex.: Designada)")
    e.add_argument("--busca", metavar="TEXTO", help="só o que contiver este texto (processo, partes...)")
    e.add_argument("--pasta", help="pasta de destino (padrão: [pauta] pasta, fora do acervo)")
    partes = e.add_mutually_exclusive_group()
    partes.add_argument("--incluir-partes-sigilosos", action="store_true", default=None,
                        help="mostrar as partes dos processos em segredo de justiça")
    partes.add_argument("--sem-partes-sigilosos", action="store_false",
                        dest="incluir_partes_sigilosos",
                        help="mascarar as partes dos processos em segredo de justiça, mesmo com "
                             "[pauta] incluir_partes_sigilosos ligado")

    i = sub.add_parser("importar", help="importa relatório exportado do SAJ/eProc")
    i.add_argument("arquivos", nargs="+", help="planilha, HTML, PDF ou DOCX")

    li = sub.add_parser("listar", help="mostra as audiências do período")
    li.add_argument("--de", type=_data, metavar="AAAA-MM-DD", help="início (padrão: hoje)")
    li.add_argument("--ate", type=_data, metavar="AAAA-MM-DD", help="fim (padrão: hoje mais 7 dias)")
    li.add_argument("--sistema", choices=("esaj", "eproc", "arquivo"), help="só um sistema")
    li.add_argument("--situacao", help="só uma situação (ex.: Cancelada)")
    li.add_argument("--busca", metavar="TEXTO", help="só o que contiver este texto")
    li.add_argument("--json", action="store_true", help="saída em JSON (para scripts)")

    f = sub.add_parser("fontes", help="mostra, adiciona ou remove as fontes da pauta")
    f.add_argument("--adicionar", nargs=2, metavar=("TRIBUNAL", "SISTEMA"),
                   help="ex.: --adicionar TJAL esaj")
    f.add_argument("--url", default="", help="endereço da pauta no portal (opcional)")
    f.add_argument("--rotulo", default="", help="nome da fonte (opcional)")
    f.add_argument("--remover", metavar="ID", help="id da fonte a remover")
    return p


def _servico():
    from ..nucleo import config
    from .servico import ServicoPauta

    return ServicoPauta(config.carregar())


def _configurar_registro() -> None:
    try:
        from ..nucleo import registro

        registro.configurar()
    except Exception as erro:          # sem registro em disco, o comando segue
        print(f"(aviso: o registro em disco não foi aberto: {erro})", file=sys.stderr)


def _linha(a: dict) -> str:
    data_ = date.fromisoformat(a["data"]).strftime("%d/%m/%Y")
    sig = "  [segredo de justiça]" if a.get("sigiloso") else ""
    partes = "" if a.get("sigiloso") else (a.get("partes") or "")
    return (f"{data_} {a.get('hora') or '--:--'}  {a.get('processo') or '(sem número)':27} "
            f"{a.get('tipo', ''):22} {a.get('situacao', ''):13} {partes}{sig}").rstrip()


# ================================================================ comandos
def _sincronizar(args, servico) -> int:
    from ..download.contexto import ContextoTerminal
    from .monitor import ConfigMonitoramento

    conf = ConfigMonitoramento.de_config(servico.cfg)
    de_padrao, ate_padrao = conf.periodo(date.today())
    de, ate = args.de or de_padrao, args.ate or ate_padrao
    if ate < de:
        print("A data final vem antes da inicial.", file=sys.stderr)
        return 2
    print(f"Sincronizando a pauta de {de:%d/%m/%Y} a {ate:%d/%m/%Y}...")
    ctx = ContextoTerminal()
    try:
        r = servico.sincronizar(ctx, args.fonte or None, de, ate)
    except KeyboardInterrupt:
        print("Interrompido.")
        return 1
    except Exception as erro:
        print(f"Falhou: {erro}", file=sys.stderr)
        return 1
    print(servico._frase_resultado(r))
    for aviso in r.get("avisos") or []:
        print(f"  aviso: {aviso}")
    for e in r.get("erros") or []:
        print(f"  {e['rotulo']}: {e['mensagem']}")
    return 1 if r.get("erros") else 0


def _exportar(args, servico) -> int:
    from .. import servicos

    de = args.de or date.today()
    ate = args.ate or de + timedelta(days=30)
    if ate < de:
        print("A data final vem antes da inicial.", file=sys.stderr)
        return 2
    pasta = Path(args.pasta).expanduser() if args.pasta else servicos.pasta_pauta(servico.cfg)
    filtros = {k: getattr(args, k) for k in ("sistema", "situacao", "busca") if getattr(args, k)}
    if args.incluir_partes_sigilosos is not None:      # sem a opção: vale o Ajuste
        filtros["incluir_partes_sigilosos"] = bool(args.incluir_partes_sigilosos)
    try:
        arquivo = servico.exportar(de, ate, pasta, **filtros)
    except Exception as erro:
        print(f"Não consegui exportar: {erro}", file=sys.stderr)
        return 1
    print(f"Planilha gravada: {arquivo}")
    return 0


def _importar(args, servico) -> int:
    codigo = 0
    for nome in args.arquivos:
        caminho = Path(nome.strip().strip('"')).expanduser()
        try:
            r = servico.importar(caminho)
        except Exception as erro:
            print(f"{caminho.name}: {erro}", file=sys.stderr)
            codigo = 1
            continue
        total = r.get("total", r["novas"] + r["atualizadas"])
        print(f"{caminho.name}: {_plural(total, 'audiência lida', 'audiências lidas')} · "
              f"{_plural(r['novas'], 'nova', 'novas')} · "
              f"{_plural(r['atualizadas'], 'atualizada', 'atualizadas')} · "
              f"{_plural(r['ignoradas'], 'linha ignorada', 'linhas ignoradas')}.")
        for aviso in r.get("avisos") or []:
            print(f"  aviso: {aviso}")
    return codigo


def _listar(args, servico) -> int:
    de = args.de or date.today()
    ate = args.ate or de + timedelta(days=7)
    dados = servico.listar(de, ate, sistema=args.sistema or "", situacao=args.situacao or "",
                           busca=args.busca or "")
    if args.json:
        print(json.dumps(dados, ensure_ascii=False, indent=1))
        return 0
    lista = dados["audiencias"]
    if not lista:
        print(f"Nenhuma audiência de {de:%d/%m/%Y} a {ate:%d/%m/%Y}.")
        return 0
    for a in lista:
        print(_linha(a))
    r = dados["resumo"]
    print(f"\n{_plural(r['total'], 'audiência', 'audiências')} no período; {r['hoje']} hoje.")
    return 0


def _fontes(args, servico) -> int:
    if args.remover:
        servico.remover_fonte(args.remover)
        print(f"Fonte {args.remover} removida (as audiências já trazidas continuam na pauta).")
        return 0
    if args.adicionar:
        tribunal, sistema = args.adicionar
        try:
            f = servico.salvar_fonte(tribunal.upper(), sistema.lower(), args.rotulo, args.url)
        except ValueError as erro:
            print(str(erro), file=sys.stderr)
            return 2
        print(f"Fonte {f['id']} salva: {f['rotulo']}.")
        return 0
    fontes = servico.fontes()
    if not fontes:
        print("Nenhuma fonte configurada. Ex.: python -m helestron pauta fontes "
              "--adicionar TJAL esaj")
        return 0
    for f in fontes:
        estado = f"erro: {f['ultimo_erro']}" if f.get("ultimo_erro") else (
            f"sincronizada em {f['ultima_sincronizacao']}" if f.get("ultima_sincronizacao")
            else "ainda não sincronizada")
        print(f"{f['id']:16} {f['rotulo']}  ({estado})" + (f"\n{'':16} {f['url']}" if f.get("url")
                                                            else ""))
        if f.get("motivo_presenca"):
            print(f"{'':16} fora do monitoramento automático: {f['motivo_presenca']}")
    return 0


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


COMANDOS = {"sincronizar": _sincronizar, "exportar": _exportar, "importar": _importar,
            "listar": _listar, "fontes": _fontes}


def main(argv: list[str] | None = None) -> int:
    parser = criar_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as saida:
        return int(saida.code or 0)
    if not args.comando:
        parser.print_help()
        return 2
    _configurar_registro()
    try:
        servico = _servico()
    except Exception as erro:
        print(f"A pauta não pôde ser aberta: {erro}", file=sys.stderr)
        return 1
    try:
        return COMANDOS[args.comando](args, servico)
    finally:
        servico.fechar()


if __name__ == "__main__":
    sys.exit(main())
