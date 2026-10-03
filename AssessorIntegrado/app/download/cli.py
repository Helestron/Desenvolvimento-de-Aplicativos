"""Linha de comando do download.

    python -m app baixar --lista pauta.xlsx [--destino PASTA] [--visivel]
    python -m app baixar 0700123-45.2024.8.02.0001 0700456-78.2024.8.02.0001

Usa o mesmo motor da janela; o código de verificação do e-SAJ é pedido no
próprio terminal. Ctrl+C para o lote sem perder o processo em curso.
Códigos de saída: 0 tudo certo; 1 parte falhou ou ficou pendente;
2 nada pôde ser feito (relação inválida, login recusado...).
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger("download.cli")


def criar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app baixar",
        description="Baixa os processos de uma relação (Excel, Word, PDF, CSV, TXT ou "
                    "link compartilhado): um PDF por processo, nomeado com o número.")
    p.add_argument("processos", nargs="*", help="números de processo (opcional, além da --lista)")
    p.add_argument("--lista", "-l", help="arquivo da relação, ou link compartilhado (http...)")
    p.add_argument("--destino", "-d", help="pasta onde gravar os PDFs (padrão: "
                   "Acervo\\Processos\\<nome da relação>)")
    p.add_argument("--visivel", action="store_true", help="mostrar a janela do navegador")
    p.add_argument("--login", choices=("senha", "certificado", "manual"),
                   help="forma de entrar no portal (padrão: a das Configurações)")
    p.add_argument("--rebaixar", action="store_true",
                   help="baixar de novo mesmo o que já está na pasta")
    p.add_argument("--midias", action="store_true", help="baixar também as gravações de audiência")
    p.add_argument("--sem-ia", action="store_true",
                   help="não atualizar os arquivos de contexto da IA ao fim")
    return p


class _CofreComMemoria:
    """O cofre de senhas, mais as credenciais digitadas agora (sem gravar)."""

    def __init__(self, cofre, extras: dict[str, tuple[str, str]]):
        self.cofre = cofre
        self.extras = extras

    def obter(self, portal: str) -> tuple[str, str]:
        if portal in self.extras:
            return self.extras[portal]
        try:
            return self.cofre.obter(portal)
        except Exception:
            return "", ""


def _interativo() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _ler_relacao(args, listas, caminhos):
    leitura = listas.Leitura(formato="")
    origem = ""
    if args.lista:
        alvo = args.lista.strip().strip('"')
        if alvo.lower().startswith(("http://", "https://")):
            print("Baixando a relação do link...")
            arquivo = listas.baixar_link(alvo, caminhos.TEMP / "relacoes")
        else:
            arquivo = Path(alvo).expanduser()
        leitura = listas.ler_arquivo(arquivo)
        origem = Path(arquivo).stem
    if args.processos:
        leitura.juntar(listas.ler_texto("\n".join(args.processos)))
    return leitura, origem


def _pedir_credenciais(grupos, opcoes, cofre) -> dict[str, tuple[str, str]]:
    """Pergunta usuário e senha dos portais que não têm credencial guardada."""
    extras: dict[str, tuple[str, str]] = {}
    for t in grupos:
        if opcoes.modo_login(t.sistema) != "senha":
            continue
        try:
            usuario, senha = cofre.obter(t.portal)
        except Exception:
            usuario, senha = "", ""
        if usuario and senha:
            continue
        if not _interativo():
            print(f"  (sem usuário e senha guardados para o {t.nome_sistema} do {t.sigla}: "
                  "se a sessão anterior tiver expirado, o navegador abre para você entrar)")
            continue
        print(f"\nAcesso ao {t.nome_sistema} do {t.sigla} (Enter em branco pula):")
        try:
            usuario = input("  Usuário (CPF): ").strip()
            if not usuario:
                continue
            senha = getpass.getpass("  Senha (não aparece ao digitar): ")
            lembrar = input("  Guardar neste computador (cifrado)? [s/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            continue
        extras[t.portal] = (usuario, senha)
        if lembrar in ("s", "sim", "y"):
            try:
                cofre.guardar(t.portal, usuario, senha)
                print("  Guardado.")
            except Exception as erro:
                print(f"  Não consegui guardar ({erro}); uso só desta vez.")
    return extras


def main(argv: list[str] | None = None, *, configurar_log: bool = True) -> int:
    from ..nucleo import caminhos, config, listas, registro, sistema, tribunais
    from ..nucleo.cofre_senhas import CofreSenhas
    from . import motor
    from .contexto import ContextoTerminal
    from .modelos import FALHAS, OpcoesDownload

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "baixar":
        argv = argv[1:]
    args = criar_parser().parse_args(argv)

    if configurar_log:
        registro.preparar_saidas()
        registro.configurar(console=True)

    if not args.lista and not args.processos:
        criar_parser().print_help()
        print("\nInforme a relação (--lista arquivo.xlsx) ou os números dos processos.")
        return 2

    try:
        leitura, origem = _ler_relacao(args, listas, caminhos)
    except listas.ListaInvalida as erro:
        print(f"\nNão consegui ler a relação: {erro}")
        return 2
    except OSError as erro:
        print(f"\nNão consegui abrir a relação: {erro}")
        return 2

    numeros = leitura.processos
    if not numeros:
        print("\nNenhum número de processo foi encontrado.")
        return 2
    print(f"\n{len(numeros)} processo(s) na relação" + (f" ({leitura.formato})." if leitura.formato else "."))
    for aviso in leitura.avisos:
        print(f"  aviso: {aviso}")
    if leitura.corrompidos:
        print(f"  {len(leitura.corrompidos)} número(s) corrompido(s) pelo Excel foram ignorados.")
    for n in leitura.digito_errado:
        print(f"  atenção: o dígito verificador de {n.formatado} não confere (tento assim mesmo).")

    cfg = config.carregar()
    opcoes = OpcoesDownload.de_config(cfg)
    if args.visivel:
        opcoes.mostrar_navegador = True
    if args.login:
        opcoes.login = {s: args.login for s in ("esaj", "eproc")}
    if args.rebaixar:
        opcoes.pular_baixados = False
    if args.midias:
        opcoes.baixar_midias = True
    if args.sem_ia:
        opcoes.atualizar_ia = False

    if args.destino:
        destino = Path(args.destino).expanduser()
    else:
        # nome curto: o caminho inteiro precisa caber nos 260 caracteres do Windows
        lote = sistema.nome_seguro(origem, "")[:80].strip(" .") if origem else ""
        lote = lote or f"Lista {datetime.now():%Y-%m-%d %Hh%M}"
        destino = cfg.pasta_processos / lote
    print(f"Destino: {destino}")

    vistos, grupos = set(), []
    for n in numeros:
        t = tribunais.por_numero(n)
        if t is not None and t.suportado and t.chave not in vistos:
            vistos.add(t.chave)
            grupos.append(t)
    cofre_real = CofreSenhas(caminhos.ARQUIVO_SENHAS)
    cofre = _CofreComMemoria(cofre_real, _pedir_credenciais(grupos, opcoes, cofre_real))

    ctx = ContextoTerminal()
    print("\nComeçando. Ctrl+C para parar (o que já foi baixado fica).\n")
    try:
        resumo = motor.executar(numeros, destino, opcoes, ctx, senhas=leitura.senhas,
                                cofre=cofre, cfg=cfg)
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return 1
    except (RuntimeError, OSError) as erro:
        # ex.: pasta de destino que não pode ser criada (disco cheio, sem
        # permissão, unidade de rede fora) - frase, e não rastro de pilha
        log.error("o lote não pôde ser baixado: %s", erro)
        print(f"\nNão foi possível baixar: {erro}")
        return 2

    print("\n" + "=" * 60)
    print(f"Concluído em {resumo.minutos:.1f} min: {resumo.texto()}")
    problemas = [r for r in resumo.itens if r.situacao in FALHAS or r.pendente]
    if problemas:
        print("\nPrecisam de atenção:")
        for r in problemas:
            print(f"  {r.numero}: {r.rotulo}" + (f" - {r.detalhe}" if r.detalhe else ""))
    print(f"\nPDFs em: {resumo.destino}")
    print(f"Relatório: {resumo.relatorio}")

    if not problemas:
        return 0
    if resumo.baixados or resumo.pulados:
        return 1
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
