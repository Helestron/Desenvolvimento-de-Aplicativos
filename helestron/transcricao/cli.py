"""Linha de comando da transcrição (o instalador e o CI do Windows usam).

    python -m helestron transcrever GRAVAÇÃO [--processo N] [--modelo medium]
    python -m helestron transcrever --ao-vivo --processo N [--wav fala.wav]
    python -m helestron modelos listar | baixar NOME
    python -m helestron falantes instalar | estado
    python -m helestron microfones

`main(argv)` recebe a lista SEM o "python -m helestron" (ex.: ["modelos",
"baixar", "small"]) e devolve o código de saída: 0 = certo, 1 = falhou,
2 = uso errado, 3 = nada reconhecido, 130 = interrompido.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger("transcricao.cli")

OK, FALHOU, USO, NADA, INTERROMPIDO = 0, 1, 2, 3, 130


class _Analisador(argparse.ArgumentParser):
    """argparse que não encerra o processo (devolve o código a main)."""

    def error(self, message):  # noqa: D401 - assinatura do argparse
        self.print_usage(sys.stderr)
        raise _ErroDeUso(f"{self.prog}: {message}")


class _ErroDeUso(Exception):
    pass


def _imprimir(texto: str = "") -> None:
    try:
        print(texto, flush=True)
    except UnicodeEncodeError:  # console antigo em cp1252/cp850
        print(texto.encode("ascii", "replace").decode("ascii"), flush=True)


def _config(caminho: str | None):
    from ..nucleo import config

    return config.Config(Path(caminho)) if caminho else config.carregar()


class _Progresso:
    """Imprime o progresso de 10 em 10% (o log do instalador fica legível)."""

    def __init__(self, prefixo: str = ""):
        self.prefixo = prefixo
        self._marco = -1
        self._texto = ""

    def __call__(self, fracao: float, texto: str = "") -> None:
        marco = int(fracao * 10)
        mudou_assunto = texto.split(":")[0] != self._texto.split(":")[0]
        if marco > self._marco or (mudou_assunto and texto):
            self._marco = marco
            self._texto = texto
            _imprimir(f"{self.prefixo}{fracao:4.0%}  {texto}")


# ============================================================ transcrever
def cmd_transcrever(argv: list[str]) -> int:
    p = _Analisador(prog="python -m helestron transcrever",
                    description="Transcreve uma gravação, ou uma audiência ao vivo.")
    p.add_argument("arquivo", nargs="?", help="gravação a transcrever (ASF, WMV, MP4, MP3, WAV...)")
    p.add_argument("--processo", help="número do processo (nome do DOCX)")
    p.add_argument("--ao-vivo", action="store_true", help="transcrição simultânea")
    p.add_argument("--wav", help="ao vivo: tocar este arquivo no lugar do microfone (testes/CI)")
    p.add_argument("--tempo-real", action="store_true",
                   help="ao vivo com --wav: tocar no ritmo real (padrão: acelerado)")
    p.add_argument("--modelo", help="base, small, medium ou large-v3-turbo")
    p.add_argument("--falante", default="", help="ao vivo: rótulo de quem começa falando")
    p.add_argument("--trocas", default="",
                   help='ao vivo com --wav: trocas de falante, ex.: "4.5=Promotor(a);9=Testemunha"')
    p.add_argument("--dispositivo", help="ao vivo: nome ou número do microfone")
    p.add_argument("--refinar", action="store_true",
                   help="ao vivo: ao encerrar, revisar com o modelo de revisão")
    p.add_argument("--destino", help="arquivo: DOCX de saída (padrão: Transcricoes/<processo>.docx)")
    p.add_argument("--falantes", type=int, default=0,
                   help="arquivo: quantas pessoas falam (0 = descobrir sozinho)")
    p.add_argument("--sem-falantes", action="store_true", help="arquivo: não separar as vozes")
    p.add_argument("--sigiloso", action="store_true",
                   help="processo em segredo de justiça: grava na pasta dos sigilosos, fora do "
                        "acervo (automático se os autos já estiverem lá)")
    p.add_argument("--config", help="config.ini alternativo")
    try:
        args = p.parse_args(argv)
    except _ErroDeUso as erro:
        _imprimir(str(erro))
        return USO
    except SystemExit as saida:  # --help
        return int(saida.code or 0)

    from ..nucleo import cnj

    numero = None
    if args.processo:
        try:
            numero = cnj.ler(args.processo)
        except cnj.NumeroInvalido:
            _imprimir(f"Número de processo inválido: {args.processo}")
            return USO
        if not numero.digito_confere:
            _imprimir(f"Atenção: o dígito verificador de {numero.formatado} não confere "
                      "(confira o número). Continuando assim mesmo.")
    try:
        cfg = _config(args.config)
    except Exception as erro:
        _imprimir(f"Não consegui ler a configuração: {erro}")
        return FALHOU

    if args.ao_vivo:
        if numero is None:
            _imprimir("Informe o número do processo: --processo NNNNNNN-DD.AAAA.J.TR.OOOO")
            return USO
        return _ao_vivo(args, numero, cfg)
    if not args.arquivo:
        _imprimir("Informe a gravação a transcrever (ou use --ao-vivo).")
        return USO
    return _arquivo(args, numero, cfg)


def _arquivo(args, numero, cfg) -> int:
    from . import arquivo, modelos

    origem = Path(args.arquivo)
    if not origem.exists():
        _imprimir(f"Arquivo não encontrado: {origem}")
        return FALHOU
    try:
        caminho = arquivo.transcrever_arquivo(
            origem, numero, cfg, progresso=_Progresso(), cancelado=lambda: False,
            destino=Path(args.destino) if args.destino else None,
            modelo=args.modelo, separar=False if args.sem_falantes else None,
            num_falantes=args.falantes, sigiloso=args.sigiloso)
    except arquivo.ProcessoNaoInformado as erro:
        _imprimir(f"{erro} Use --processo.")
        return USO
    except arquivo.SemFala as erro:
        _imprimir(str(erro))
        return NADA
    except (arquivo.AudioIlegivel, modelos.ModeloAusente, modelos.ErroDoModelo, ValueError) as erro:
        _imprimir(str(erro))
        return FALHOU
    except KeyboardInterrupt:
        _imprimir("Interrompido.")
        return INTERROMPIDO
    _imprimir(f"Transcrição gravada em: {caminho}")
    return OK


def _ler_trocas(texto: str) -> list[tuple[float, str]]:
    trocas: list[tuple[float, str]] = []
    for parte in (texto or "").split(";"):
        if "=" not in parte:
            continue
        instante, rotulo = parte.split("=", 1)
        try:
            trocas.append((float(instante.strip().replace(",", ".")), rotulo.strip()))
        except ValueError:
            raise _ErroDeUso(f"troca inválida: '{parte}' (use segundos=Rótulo)")
    return sorted(trocas)


def _fabrica_de_arquivo(wav: Path, tempo_real: bool, ao_avancar):
    """Fonte de áudio = arquivo (o CI do Windows não tem microfone)."""
    from . import microfone

    def fabrica(ao_bloco, ao_nivel, ao_aviso):
        return microfone.CapturaDeArquivo(wav, ao_bloco, ao_nivel, tempo_real=tempo_real,
                                          ao_aviso=ao_aviso, ao_avancar=ao_avancar)

    return fabrica


def _ao_vivo(args, numero, cfg) -> int:
    from . import microfone
    from .ao_vivo import SessaoAoVivo
    from .documento import hms

    try:
        trocas = _ler_trocas(args.trocas)
    except _ErroDeUso as erro:
        _imprimir(str(erro))
        return USO
    falas: list = []
    erros: list[str] = []

    def eventos(tipo: str, dado) -> None:
        if tipo == "fala":
            falas.append(dado)
            rotulo = f"{dado.falante}: " if dado.falante else ""
            _imprimir(f"[{hms(dado.inicio)}] {rotulo}{dado.texto}")
        elif tipo in ("estado", "aviso"):
            _imprimir(f"({dado})")
        elif tipo == "erro":
            erros.append(str(dado))
            _imprimir(f"ERRO: {dado}")
        elif tipo == "fim":
            _imprimir(f"Documento final: {dado}")

    caixa: dict = {}

    def ao_avancar(segundos: float) -> None:
        sessao = caixa.get("sessao")
        while trocas and segundos >= trocas[0][0] and sessao is not None:
            _, rotulo = trocas.pop(0)
            sessao.definir_falante(rotulo)

    fabrica = None
    if args.wav:
        wav = Path(args.wav)
        if not wav.exists():
            _imprimir(f"Arquivo não encontrado: {wav}")
            return FALHOU
        fabrica = _fabrica_de_arquivo(wav, args.tempo_real, ao_avancar)

    try:
        sessao = SessaoAoVivo(numero, cfg, eventos, captura_fabrica=fabrica, modelo=args.modelo,
                              dispositivo=args.dispositivo, falante=args.falante,
                              sigiloso=args.sigiloso)
    except ValueError as erro:
        _imprimir(str(erro))
        return USO
    caixa["sessao"] = sessao
    try:
        sessao.iniciar()
    except (microfone.MicrofoneIndisponivel, RuntimeError, OSError) as erro:
        _imprimir(f"Não foi possível começar: {erro}")
        return FALHOU

    try:
        if args.wav:
            sessao.captura.esperar()
            if not sessao.modelo_pronto.is_set():
                _imprimir("(áudio lido; esperando o modelo para transcrever a fila...)")
        else:
            _imprimir("Gravando. Digite o rótulo de quem fala e Enter para trocar; "
                      "/p pausa, /r retoma; Enter vazio encerra.")
            while True:
                linha = input().strip()
                if not linha:
                    break
                if linha == "/p":
                    sessao.pausar()
                elif linha == "/r":
                    sessao.retomar()
                else:
                    sessao.definir_falante(linha)
    except (KeyboardInterrupt, EOFError):
        _imprimir("Encerrando...")
    try:
        final = sessao.encerrar(refinar=args.refinar)
    except Exception as erro:
        _imprimir(f"Falha ao encerrar: {erro}")
        return FALHOU
    reais = [f for f in falas if (f.fim - f.inicio) >= 0.01]   # sem as marcas de pausa
    quantas = "1 fala transcrita" if len(reais) == 1 else f"{len(reais)} falas transcritas"
    _imprimir(f"{quantas}. Documento: {final}")
    if erros and not reais:
        return FALHOU
    return OK if reais else NADA


# ================================================================ modelos
def cmd_modelos(argv: list[str]) -> int:
    from . import modelos

    p = _Analisador(prog="python -m helestron modelos", description="Modelos de transcrição (Whisper).")
    sub = p.add_subparsers(dest="acao")
    sub.add_parser("listar", help="mostra os modelos e quais estão instalados")
    b = sub.add_parser("baixar", help="baixa um modelo (retomável)")
    b.add_argument("nome", help="base, small, medium ou large-v3-turbo")
    try:
        args = p.parse_args(argv)
    except _ErroDeUso as erro:
        _imprimir(str(erro))
        return USO
    except SystemExit as saida:
        return int(saida.code or 0)

    if args.acao in (None, "listar"):
        for linha in modelos.listar():
            marca = ("embutido" if linha.get("embutido") else "instalado") \
                if linha["instalado"] else "não instalado"
            _imprimir(f"{linha['nome']:<15} ~{linha['mb']:>5} MB  {marca:<14} {linha['descricao']}")
        return OK
    try:
        nome = modelos.nome_canonico(args.nome)
    except ValueError as erro:
        _imprimir(str(erro))
        return USO
    try:
        pasta = modelos.baixar(nome, _Progresso())
    except modelos.ModeloAusente as erro:
        _imprimir(str(erro))
        return FALHOU
    except KeyboardInterrupt:
        _imprimir("Interrompido (o download continua de onde parou na próxima vez).")
        return INTERROMPIDO
    _imprimir(f"Modelo {nome} pronto em {pasta}")
    return OK


# =============================================================== falantes
def cmd_falantes(argv: list[str]) -> int:
    from . import falantes

    p = _Analisador(prog="python -m helestron falantes",
                    description="Separação automática de falantes (a biblioteca vem no "
                                "instalador; os modelos de voz também, quando disponíveis).")
    sub = p.add_subparsers(dest="acao")
    i = sub.add_parser("instalar", help="baixa os modelos de voz que faltarem "
                       f"(cerca de {falantes.TAMANHO_MB} MB, do GitHub)")
    # Aceita e ignora a opção da versão anterior (nada de pip agora).
    i.add_argument("--sem-pip", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("estado", help="mostra se o componente está instalado")
    try:
        args = p.parse_args(argv)
    except _ErroDeUso as erro:
        _imprimir(str(erro))
        return USO
    except SystemExit as saida:
        return int(saida.code or 0)

    if args.acao in (None, "estado"):
        _imprimir(f"Separação de falantes: {falantes.situacao()}")
        return OK if falantes.disponivel() else FALHOU
    try:
        falantes.instalar(_Progresso())
    except falantes.ComponenteAusente as erro:
        _imprimir(str(erro))
        return FALHOU
    except KeyboardInterrupt:
        _imprimir("Interrompido.")
        return INTERROMPIDO
    _imprimir(f"Separação de falantes: {falantes.situacao()}")
    return OK if falantes.disponivel() else FALHOU


# ============================================================= microfones
def cmd_microfones(argv: list[str]) -> int:
    from . import microfone

    entradas = microfone.listar_entradas()
    if not entradas:
        _imprimir("Nenhum microfone encontrado.")
        return FALHOU
    for e in entradas:
        marca = " (padrão)" if e.padrao else ""
        _imprimir(f"{e.indice:>3}  {e.nome}{marca}  [{e.api}, {e.taxa} Hz]")
    return OK


SUBCOMANDOS = {
    "transcrever": cmd_transcrever,
    "modelos": cmd_modelos,
    "falantes": cmd_falantes,
    "microfones": cmd_microfones,
}


def main(argv: list[str] | None = None) -> int:
    """Despacha ["transcrever"|"modelos"|"falantes"|"microfones", ...]."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "ajuda"):
        _imprimir(__doc__.strip())
        return OK if argv else USO
    funcao = SUBCOMANDOS.get(argv[0])
    if funcao is None:
        _imprimir(f"Comando desconhecido: {argv[0]}. Use: {', '.join(SUBCOMANDOS)}.")
        return USO
    return funcao(argv[1:])


if __name__ == "__main__":  # pragma: no cover - uso direto: python -m helestron.transcricao.cli
    from ..nucleo import registro

    registro.preparar_saidas()
    registro.configurar(console=True)
    sys.exit(main())
