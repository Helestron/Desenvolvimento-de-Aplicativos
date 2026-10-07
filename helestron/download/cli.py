"""Linha de comando do download.

    python -m helestron baixar --lista pauta.xlsx [--destino PASTA] [--visivel]
    python -m helestron baixar 0700123-45.2024.8.02.0001 0700456-78.2024.8.02.0001
    python -m helestron baixar 0700123-45.2024 0700456-78.2024 --completar 8.02.0058 \\
        --destino PASTA --login certificado --sem-cofre --texto --eventos \\
        --json PASTA\\_helestron.json --log PASTA\\_helestron.log

Usa o mesmo motor da janela; o código de verificação do e-SAJ é pedido no
próprio terminal. Sem terminal (quem chama não tem teclado: a skill do
Claude, um script), a janela do navegador fica visível e o código é digitado
nela, no campo do próprio portal; senha e código nunca são lidos de arquivo.
Ctrl+C para o lote sem perder o processo em curso.

Para quem automatiza (a skill do Claude, um script): ``--json`` grava o
andamento e o resultado num JSON (formato em download/acompanhamento.py),
``--eventos`` imprime cada evento numa linha ``HELESTRON-EVENTO {json}``,
``--log`` guarda tudo o que sai na tela e o registro detalhado num arquivo
UTF-8, ``--texto`` extrai o texto dos autos com a marca da folha,
``--retomar`` refaz só o que pede nova tentativa e ``--desanexar`` deixa o
lote rodando sozinho (imprime ``HELESTRON-EXECUCAO {"pid", "json", "log"}``
e sai). O JSON e o log trazem os números reais dos processos sigilosos:
não podem ficar dentro do acervo compartilhado com a IA.

Códigos de saída: 0 tudo certo; 1 parte falhou ou ficou pendente;
2 nada pôde ser feito (relação inválida, login recusado, uso errado...).
"""

from __future__ import annotations

import argparse
import getpass
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    from ..nucleo.argumentos import ArgumentParser   # argparse em português
except ImportError:  # pragma: no cover - instalação sem o módulo
    from argparse import ArgumentParser

log = logging.getLogger("download.cli")

PREFIXO_EXECUCAO = "HELESTRON-EXECUCAO "
# Flags do CreateProcess (Windows) para o lote desanexado: sem console, fora do
# grupo do console de quem chamou (o Ctrl+C dele não chega) e, se o "job" de
# quem chamou deixar, fora dele (o lote sobrevive ao fim de quem o chamou).
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

_RE_SUFIXO = re.compile(r"^\d\.\d{2}\.\d{4}$")
# NNNNNNN-DD.AAAA (o "número curto" do e-SAJ, sem J.TR.OOOO), com ou sem /NN
_RE_CURTO = re.compile(r"^\s*(\d{7})-?(\d{2})\.?(\d{4})(\s*/\s*\d{1,4})?\s*$")


def _sufixo(valor: str) -> str:
    texto = (valor or "").strip().strip(".")
    if not _RE_SUFIXO.match(texto):
        raise argparse.ArgumentTypeError(
            f"'{valor}' não é J.TR.OOOO (segmento, tribunal e foro: por exemplo 8.02.0058)")
    return texto


def _minutos(valor: str) -> float:
    try:
        n = float(str(valor).replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{valor}' não é um número de minutos") from None
    if n < 0:
        raise argparse.ArgumentTypeError("o número de minutos não pode ser negativo")
    return n


def criar_parser() -> ArgumentParser:
    p = ArgumentParser(
        prog="python -m helestron baixar",
        description="Baixa os processos de uma relação (Excel, Word, PDF, CSV, TXT ou "
                    "link compartilhado): um PDF por processo, nomeado com o número.")
    p.add_argument("processos", nargs="*", help="números de processo (opcional, além da --lista)")
    p.add_argument("--lista", "-l", help="arquivo da relação, ou link compartilhado (http...)")
    p.add_argument("--destino", "-d", help="pasta onde gravar os PDFs (padrão: "
                   "Documentos\\Helestron\\Acervo\\Processos\\<nome da relação>)")
    p.add_argument("--visivel", action="store_true", help="mostrar a janela do navegador")
    p.add_argument("--login", choices=("senha", "certificado", "manual"),
                   help="forma de entrar no portal (padrão: a dos Ajustes)")
    p.add_argument("--rebaixar", action="store_true",
                   help="baixar de novo mesmo o que já está na pasta")
    p.add_argument("--rebaixar-incompletos", action="store_true",
                   help="baixar de novo o que já está na pasta só se tiver folhas (ou "
                        "documentos) ausentes ou for de versão anterior, sem o manifesto de "
                        "paginação")
    p.add_argument("--midias", action="store_true", help="baixar também as gravações de audiência")
    p.add_argument("--sem-ia", action="store_true",
                   help="não atualizar os arquivos de contexto da IA ao fim (lote fora do "
                        "acervo nunca os atualiza)")
    p.add_argument("--completar", metavar="J.TR.OOOO", type=_sufixo,
                   help="completa os números curtos (NNNNNNN-DD.AAAA) digitados na linha de "
                        "comando com segmento, tribunal e foro (ex.: 8.02.0058)")
    p.add_argument("--retomar", action="store_true",
                   help="baixa só o que o relatório da pasta do lote diz que pede nova tentativa "
                        "(falhou, ficou pendente ou interrompido) e os números que ainda não "
                        "estão nele")
    p.add_argument("--texto", action="store_true",
                   help="ao fim, extrai o texto de cada PDF com a marca da folha (em _texto, ao "
                        "lado dos PDFs; dentro do acervo, em _ia\\texto)")
    p.add_argument("--json", metavar="ARQ",
                   help="grava o andamento e o resultado neste arquivo JSON (fora do acervo)")
    p.add_argument("--eventos", action="store_true",
                   help="imprime cada evento (grupo, login esperando, fim) numa linha "
                        "HELESTRON-EVENTO {json}")
    p.add_argument("--log", metavar="ARQ",
                   help="grava tudo o que sai na tela e o registro detalhado neste arquivo "
                        "(UTF-8, fora do acervo); com --json, há um padrão em Logs\\execucoes")
    p.add_argument("--esperar-navegador", metavar="MIN", type=_minutos, default=0.0,
                   help="com o navegador do portal ocupado por outro download, esperar até MIN "
                        "minutos (tentando a cada 30 s) em vez de desistir")
    p.add_argument("--sem-cofre", action="store_true",
                   help="não usar as senhas guardadas no computador: no modo senha, o navegador "
                        "abre na tela de entrada para você entrar")
    p.add_argument("--desanexar", action="store_true",
                   help="deixa o lote rodando sozinho, sem console, e sai na hora (exige "
                        "--json); imprime HELESTRON-EXECUCAO {\"pid\", \"json\", \"log\"}")
    return p


class _CofreComMemoria:
    """O cofre de senhas, mais as credenciais digitadas agora (sem gravar)."""

    def __init__(self, cofre, extras: dict[str, tuple[str, str]]):
        self.cofre = cofre
        self.extras = extras

    def obter(self, portal: str) -> tuple[str, str]:
        if portal in self.extras:
            return self.extras[portal]
        if self.cofre is None:
            return "", ""
        try:
            return self.cofre.obter(portal)
        except Exception:
            return "", ""


def _interativo() -> bool:
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _esaj_por_senha(grupos, opcoes) -> bool:
    """Algum tribunal do lote entra no e-SAJ por usuário e senha (o modo que
    pede o código de verificação por e-mail)? Conta também o e-SAJ que é o
    sistema alternativo de um tribunal em transição (TJAL, TJSP)."""
    if opcoes.modo_login("esaj") != "senha":
        return False
    for t in grupos:
        alternativo = getattr(t, "alternativo", None)
        if t.sistema == "esaj" or getattr(alternativo, "sistema", "") == "esaj":
            return True
    return False


def _ler_argumentos(processos: list[str], sufixo: str | None, listas, leitura) -> list[dict]:
    """Junta à 'leitura' os números digitados na linha de comando. Devolve os
    argumentos que não deram número nenhum, com o porquê (antes, sumiam em
    silêncio - e o processo simplesmente não era baixado)."""
    ignorados: list[dict] = []
    for arg in processos:
        texto = arg
        curto = _RE_CURTO.match(arg or "")
        if curto:
            if not sufixo:
                ignorados.append({"argumento": arg, "motivo": (
                    "número incompleto (falta o segmento, o tribunal e o foro): use --completar, "
                    "por exemplo --completar 8.02.0001")})
                continue
            texto = f"{curto.group(1)}-{curto.group(2)}.{curto.group(3)}.{sufixo}" \
                    f"{(curto.group(4) or '').replace(' ', '')}"
        lida = listas.ler_texto(texto)
        if not lida.processos:
            ignorados.append({"argumento": arg,
                              "motivo": "não traz número de processo no padrão CNJ"})
            continue
        leitura.juntar(lida)
    return ignorados


def _ler_relacao(args, listas, caminhos):
    leitura = listas.Leitura(formato="")
    origem = ""
    if args.lista:
        alvo = args.lista.strip().strip('"')
        if alvo.lower().startswith(("http://", "https://")):
            print("Baixando a relação do link...")
            arquivo = listas.baixar_link(alvo, caminhos.TEMP / "relacoes")
            try:
                leitura = listas.ler_arquivo(arquivo)
            finally:
                # A relação pode trazer as senhas dos sigilosos: lida, não fica
                # no disco (só o nome do arquivo segue, para nomear o lote).
                try:
                    Path(arquivo).unlink()
                except OSError:
                    log.warning("não consegui apagar a relação baixada %s", Path(arquivo).name)
        else:
            arquivo = Path(alvo).expanduser()
            leitura = listas.ler_arquivo(arquivo)
        origem = Path(arquivo).stem
    ignorados = _ler_argumentos(args.processos or [], args.completar, listas, leitura)
    return leitura, origem, ignorados


def _pedir_credenciais(grupos, opcoes, cofre) -> dict[str, tuple[str, str]]:
    """Pergunta usuário e senha dos portais que não têm credencial guardada.

    Sem cofre (--sem-cofre), não pergunta nada: o navegador abre na tela de
    entrada para o usuário entrar."""
    extras: dict[str, tuple[str, str]] = {}
    if cofre is None:
        return extras
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


# --------------------------------------------------------------- caminhos
def _dentro(caminho, pasta) -> bool:
    try:
        Path(caminho).expanduser().resolve().relative_to(Path(pasta).expanduser().resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def log_padrao(caminhos) -> Path:
    """O log de uma execução com --json sem --log: Logs\\execucoes, fora do acervo."""
    return caminhos.LOGS / "execucoes" / f"baixar-{datetime.now():%Y-%m-%d-%Hh%Mm%S}-{os.getpid()}.log"


def _recusar_no_acervo(rotulo: str, caminho: str | None, cfg) -> str:
    """A frase da recusa ("" se o arquivo pode ficar onde foi pedido)."""
    if not caminho:
        return ""
    try:
        acervo = cfg.pasta_acervo
    except Exception:
        return ""
    if _dentro(caminho, acervo):
        return (f"O arquivo de {rotulo} ({caminho}) não pode ficar dentro do acervo "
                f"compartilhado com a IA ({acervo}): ele traz os números dos processos "
                "sigilosos. Escolha outra pasta (a do lote fora do acervo, por exemplo).")
    return ""


# --------------------------------------------------------------- log (tee)
class _Duplicador(io.TextIOBase):
    """Escreve no fluxo de antes (a tela) e no arquivo do --log."""

    def __init__(self, original, arquivo, trava: threading.Lock):
        self._original = original
        self._arquivo = arquivo
        self._trava = trava

    @property
    def encoding(self):  # noqa: D401 - propriedade do TextIOBase
        return "utf-8"

    def writable(self) -> bool:
        return True

    def write(self, texto) -> int:
        texto = str(texto)
        if self._original is not None:
            try:
                self._original.write(texto)
            except (OSError, ValueError, UnicodeEncodeError):
                pass
        with self._trava:
            try:
                self._arquivo.write(texto)
                self._arquivo.flush()
            except (OSError, ValueError):
                pass
        return len(texto)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except (OSError, ValueError):
                pass

    def isatty(self) -> bool:
        try:
            return bool(self._original is not None and self._original.isatty())
        except (AttributeError, ValueError):
            return False

    def fileno(self) -> int:
        if self._original is None:
            raise io.UnsupportedOperation("fileno")
        return self._original.fileno()


class _ParaOLog(io.TextIOBase):
    """O destino do registro (logging) dentro do arquivo do --log."""

    def __init__(self, arquivo, trava: threading.Lock):
        self._arquivo = arquivo
        self._trava = trava

    def writable(self) -> bool:
        return True

    def write(self, texto) -> int:
        with self._trava:
            try:
                self._arquivo.write(str(texto))
                self._arquivo.flush()
            except (OSError, ValueError):
                pass
        return len(str(texto))


class _RegistroDaExecucao:
    """O --log: a tela (stdout e stderr) e o registro INFO num arquivo só."""

    def __init__(self, caminho: Path):
        from ..nucleo.registro import FiltroSegredos

        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._arquivo = open(self.caminho, "a", encoding="utf-8", errors="replace")
        self._trava = threading.Lock()
        self._stdout, self._stderr = sys.stdout, sys.stderr
        sys.stdout = _Duplicador(self._stdout, self._arquivo, self._trava)
        sys.stderr = _Duplicador(self._stderr, self._arquivo, self._trava)
        self._handler = logging.StreamHandler(_ParaOLog(self._arquivo, self._trava))
        self._handler.setLevel(logging.INFO)
        self._handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"))
        self._handler.addFilter(FiltroSegredos())
        raiz = logging.getLogger()
        self._nivel = raiz.level
        if raiz.level == logging.NOTSET or raiz.level > logging.INFO:
            raiz.setLevel(logging.INFO)
        raiz.addHandler(self._handler)

    def fechar(self) -> None:
        raiz = logging.getLogger()
        raiz.removeHandler(self._handler)
        raiz.setLevel(self._nivel)
        sys.stdout, sys.stderr = self._stdout, self._stderr
        with self._trava:
            try:
                self._arquivo.close()
            except OSError:
                pass


# ------------------------------------------------------------- desanexar
def _desanexar(argv: list[str], args, caminhos) -> int:
    """Começa o lote num processo separado, sem console, e sai na hora."""
    json_arq = Path(args.json).expanduser().resolve()
    log_arq = Path(args.log).expanduser().resolve() if args.log else log_padrao(caminhos)
    filho = [a for a in argv if a != "--desanexar"]
    if not args.log:
        filho += ["--log", str(log_arq)]
    comando = [sys.executable] + (["-I"] if caminhos.INSTALADO else []) + \
        ["-m", "helestron", "baixar"] + filho
    ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
    comum = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, close_fds=True, cwd=os.getcwd(), env=ambiente)
    if sys.platform == "win32":
        base = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            processo = subprocess.Popen(comando, creationflags=base | CREATE_BREAKAWAY_FROM_JOB,
                                        **comum)
        except OSError:
            # o "job" de quem chamou não deixa sair dele (acesso negado)
            processo = subprocess.Popen(comando, creationflags=base, **comum)
    else:
        processo = subprocess.Popen(comando, start_new_session=True, **comum)
    # Um primeiro JSON, já com o pid de quem vai baixar: quem chamou pode lê-lo
    # na hora; o lote o regrava assim que começar.
    from .acompanhamento import Acompanhamento
    inicial = Acompanhamento(json_arq, log=str(log_arq))
    inicial.definir(pid=processo.pid)
    inicial.gravar(forcar=True)
    inicial.fechar()
    print(PREFIXO_EXECUCAO + json.dumps({"pid": processo.pid, "json": str(json_arq),
                                         "log": str(log_arq)}, ensure_ascii=False), flush=True)
    return 0


# ------------------------------------------------------------- retomar
def _retomar(numeros, destino: Path, opcoes, cfg, motor, modelos, cnj, senhas=None):
    """O que '--retomar' baixa: os da relação que o relatório da pasta do lote
    não tem ou diz que pedem nova tentativa (e o sigiloso que faltava a senha,
    se a relação agora a traz), e os do relatório que pedem nova tentativa.
    Devolve (números, ignorados com o porquê)."""
    linhas = motor.ler_relatorio_do_lote(destino, opcoes.pasta_sigilosos,
                                         getattr(cfg, "pasta_processos", None))
    por_chave = {chave: linha for chave, linha in linhas if chave}
    escolhidos, ignorados, vistos = [], [], set()
    for n in numeros:
        linha = por_chave.get(n.nome_arquivo)
        vistos.add(n.nome_arquivo)
        if linha is None or modelos.pede_nova_tentativa(linha.get("situacao"), linha.get("causa")):
            escolhidos.append(n)
            continue
        if (linha.get("situacao") or "").strip() == modelos.SIGILOSO_SEM_SENHA \
                and motor.senha_de(n, senhas):
            escolhidos.append(n)             # a senha que faltava veio agora
            continue
        situacao = (linha.get("situacao") or "").strip()
        ignorados.append({"numero": n.formatado, "situacao": situacao,
                          "motivo": f"{modelos.rotulo(situacao)}: uma nova tentativa não muda "
                                    "o desfecho"})
    for chave, linha in linhas:
        if not modelos.pede_nova_tentativa(linha.get("situacao"), linha.get("causa")):
            continue
        if chave is None:
            ignorados.append({"numero": linha.get("processo", ""),
                              "situacao": linha.get("situacao", ""),
                              "motivo": "linha sem o número (sigiloso) e sem o relatório completo "
                                        "da pasta de sigilosos"})
            continue
        if chave in vistos:
            continue
        vistos.add(chave)
        try:
            escolhidos.append(cnj.ler(linha.get("processo") or ""))
        except cnj.NumeroInvalido:
            continue
    return escolhidos, ignorados


# ------------------------------------------------------------- texto
def _extrair_textos(resumo, cfg, acomp) -> None:
    """--texto: o texto de cada PDF baixado ou já na pasta, com a marca da
    folha. Fora do acervo, em <pasta do PDF>/_texto (o sigiloso, na pasta de
    sigilosos); dentro, em <acervo>/_ia/texto, que a limpeza do sigilo cobre.
    Autos de sigiloso dentro do acervo (presos) não viram texto."""
    from ..compartilhar import textos
    from .modelos import JA_BAIXADO, OK

    try:
        acervo = Path(cfg.pasta_acervo)
    except Exception:
        acervo = None
    contagem = {"novo": 0, "em_dia": 0, "falhou": 0, "sigiloso_ignorado": 0}
    com_imagem = 0          # PDFs com página sem texto extraível
    for r in resumo.itens:
        if r.situacao not in (OK, JA_BAIXADO) or not r.arquivo:
            continue
        pdf = Path(r.arquivo)
        if not pdf.is_file():
            continue
        no_acervo = acervo is not None and _dentro(pdf, acervo)
        if no_acervo and r.sigiloso:
            contagem["sigiloso_ignorado"] += 1
            if acomp is not None:
                acomp.texto(r, "", "sigiloso_ignorado",
                            "autos de processo sigiloso dentro do acervo: o texto não é gerado")
            continue
        destino = (acervo / "_ia" / "texto" if no_acervo else pdf.parent / "_texto") \
            / f"{pdf.stem}.txt"
        try:
            antes = destino.stat().st_mtime if destino.exists() else None
            textos.garantir_texto(pdf, destino)
            situacao = "novo" if antes is None or destino.stat().st_mtime != antes else "em_dia"
            erro = ""
        except Exception as e:      # PDF corrompido não para o resto
            situacao, erro = "falhou", str(e)[:300]
            print(f"  texto de {pdf.name}: não consegui extrair ({erro})")
        info = {}
        if situacao != "falhou":
            # As páginas sem texto extraível (imagem digitalizada sem OCR): quem
            # lê o texto precisa vê-las no PDF. No e-SAJ, em folhas.
            try:
                _texto, info = textos.analisar(destino)
            except Exception as e:  # o texto está pronto; só a análise falhou
                log.debug("análise do texto de %s: %s", pdf.name, e)
            if info.get("paginas_sem_texto"):
                com_imagem += 1
                print(f"  {pdf.name}: páginas sem texto extraível (imagem? confira no PDF): "
                      f"{info['paginas_sem_texto']}")
        contagem[situacao] += 1
        if acomp is not None:
            acomp.texto(r, destino if situacao != "falhou" else "", situacao, erro, info=info)
    feitos = contagem["novo"] + contagem["em_dia"]
    partes = [f"{feitos} pronto{'s' if feitos != 1 else ''}"]
    if com_imagem:
        partes.append(f"{com_imagem} com página sem texto extraível")
    if contagem["falhou"]:
        partes.append(f"{contagem['falhou']} com problema")
    if contagem["sigiloso_ignorado"]:
        partes.append(f"{contagem['sigiloso_ignorado']} sigiloso(s) no acervo sem texto")
    print(f"Texto dos autos: {', '.join(partes)}.")


# ------------------------------------------------------------------ main
def main(argv: list[str] | None = None, *, configurar_log: bool = True) -> int:
    from ..nucleo import caminhos, config, registro

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "baixar":
        argv = argv[1:]
    args = criar_parser().parse_args(argv)

    sem_relacao = not args.lista and not args.processos and not (args.retomar and args.destino)
    if sem_relacao and not args.json:
        criar_parser().print_help()
        print("\nInforme a relação (--lista arquivo.xlsx) ou os números dos processos.")
        return 2

    cfg = None
    if args.json or args.log or args.desanexar:
        # O JSON e o log trazem os números reais dos sigilosos: nunca no acervo
        cfg = config.carregar()
        for rotulo, caminho in (("acompanhamento (--json)", args.json),
                                ("registro (--log)", args.log)):
            recusa = _recusar_no_acervo(rotulo, caminho, cfg)
            if recusa:
                print(recusa, file=sys.stderr)
                return 2
    if sem_relacao:
        # com --json, quem chamou sempre recebe o JSON - também no erro de uso
        criar_parser().print_help()
        print("\nInforme a relação (--lista arquivo.xlsx) ou os números dos processos.")
        from .acompanhamento import Acompanhamento
        Acompanhamento(Path(os.path.abspath(Path(args.json).expanduser()))).concluir(
            2, erro="informe a relação (--lista) ou os números dos processos", causa_erro="uso")
        return 2
    if args.desanexar:
        if not args.json:
            print("--desanexar precisa de --json ARQ: é por ele que se acompanha o lote.",
                  file=sys.stderr)
            return 2
        return _desanexar(argv, args, caminhos)

    if configurar_log:
        registro.preparar_saidas()
        registro.configurar(console=True)

    caminho_log = None
    if args.log:
        caminho_log = Path(os.path.abspath(Path(args.log).expanduser()))
    elif args.json:
        caminho_log = log_padrao(caminhos)
    execucao = None
    if caminho_log is not None:
        try:
            execucao = _RegistroDaExecucao(caminho_log)
        except OSError as erro:
            print(f"Não consegui abrir o arquivo de registro {caminho_log} ({erro}).",
                  file=sys.stderr)
            return 2

    acomp = None
    if args.json:
        from .acompanhamento import Acompanhamento
        acomp = Acompanhamento(Path(os.path.abspath(Path(args.json).expanduser())),
                               log=str(caminho_log) if caminho_log else "")
        acomp.gravar(forcar=True)

    saida = {"codigo": 2, "resumo": None, "erro": "", "causa": "inesperado"}
    try:
        saida = _baixar(args, cfg, acomp)
    except KeyboardInterrupt:
        print("\nInterrompido.")
        saida = {"codigo": 1, "resumo": None, "erro": "interrompido", "causa": "interrompido"}
    except Exception as erro:
        # o rastro vai para quem chamou (e para o log); o JSON diz que acabou
        saida = {"codigo": 2, "resumo": None, "erro": f"erro inesperado: {str(erro)[:300]}",
                 "causa": "inesperado"}
        raise
    finally:
        if acomp is not None:
            acomp.concluir(saida["codigo"], resumo=saida.get("resumo"), erro=saida.get("erro", ""),
                           causa_erro=saida.get("causa", "") if saida.get("erro") else "")
        if execucao is not None:
            execucao.fechar()
    return saida["codigo"]


def _baixar(args, cfg, acomp) -> dict:
    """O download em si. Devolve {"codigo", "resumo", "erro", "causa"}."""
    from ..nucleo import caminhos, cnj, config, listas, sistema, tribunais
    from ..nucleo.cofre_senhas import CofreSenhas
    from . import modelos, motor
    from .contexto import ContextoTerminal
    from .modelos import FALHAS, OpcoesDownload

    def falhou(mensagem: str, causa: str, codigo: int = 2) -> dict:
        return {"codigo": codigo, "resumo": None, "erro": mensagem, "causa": causa}

    leitura = listas.Leitura(formato="")
    origem, ignorados = "", []
    if args.lista or args.processos:
        try:
            leitura, origem, ignorados = _ler_relacao(args, listas, caminhos)
        except listas.ListaInvalida as erro:
            print(f"\nNão consegui ler a relação: {erro}")
            return falhou(f"não consegui ler a relação: {erro}", "relacao_invalida")
        except OSError as erro:
            print(f"\nNão consegui abrir a relação: {erro}")
            return falhou(f"não consegui abrir a relação: {erro}", "relacao_invalida")
    for item in ignorados:
        print(f"  ignorado: {item['argumento']} ({item['motivo']})")
    if acomp is not None:
        acomp.definir(ignorados=ignorados)

    numeros = leitura.processos
    if not numeros and not args.retomar:
        print("\nNenhum número de processo foi encontrado.")
        return falhou("nenhum número de processo foi encontrado", "sem_processos")
    if numeros:
        quantos = "1 processo" if len(numeros) == 1 else f"{len(numeros)} processos"
        print(f"\n{quantos} na relação" + (f" ({leitura.formato})." if leitura.formato else "."))
    for aviso in leitura.avisos:
        print(f"  aviso: {aviso}")
    if leitura.corrompidos:
        print("  1 número corrompido pelo Excel foi ignorado." if len(leitura.corrompidos) == 1
              else f"  {len(leitura.corrompidos)} números corrompidos pelo Excel foram ignorados.")
    for n in leitura.digito_errado:
        print(f"  atenção: o dígito verificador de {n.formatado} não confere (tento assim mesmo).")

    if cfg is None:
        cfg = config.carregar()
    opcoes = OpcoesDownload.de_config(cfg)
    if args.visivel:
        opcoes.mostrar_navegador = True
    if args.login:
        opcoes.login = {s: args.login for s in ("esaj", "eproc")}
    if args.rebaixar:
        opcoes.pular_baixados = False
    if args.rebaixar_incompletos:
        opcoes.rebaixar_incompletos = True
    if args.midias:
        opcoes.baixar_midias = True
    if args.sem_ia:
        opcoes.atualizar_ia = False
    if args.esperar_navegador:
        opcoes.esperar_navegador_s = float(args.esperar_navegador) * 60.0
    if args.sem_cofre:
        opcoes.usar_cofre = False

    if args.destino:
        # absoluto: é o que vai para o JSON e para a pasta de sigilosos do lote
        destino = Path(os.path.abspath(Path(args.destino).expanduser()))
    else:
        # nome curto: o caminho inteiro precisa caber nos 260 caracteres do Windows
        lote = sistema.nome_seguro(origem, "")[:80].strip(" .") if origem else ""
        lote = lote or f"Lista {datetime.now():%Y-%m-%d %Hh%M}"
        destino = cfg.pasta_processos / lote
    print(f"Destino: {destino}")
    if acomp is not None:
        try:
            pasta_sig = motor.pasta_sigilosos_do_lote(opcoes.pasta_sigilosos, destino,
                                                      getattr(cfg, "pasta_processos", None))
        except Exception:
            pasta_sig = ""
        acomp.definir(destino=str(destino), relatorio=str(destino / "_controle" / "relatorio.csv"),
                      sigilosos_do_lote=str(pasta_sig))

    if args.retomar:
        numeros, deixados = _retomar(numeros, destino, opcoes, cfg, motor, modelos, cnj,
                                     leitura.senhas)
        for item in deixados:
            print(f"  não retomado: {item['numero']} ({item['motivo']})")
        if acomp is not None:
            acomp.definir(ignorados_por_retomar=deixados)
        if not numeros:
            print("\nNada a retomar: o relatório do lote não tem processo que peça nova "
                  "tentativa.")
            return {"codigo": 0, "resumo": None, "erro": "", "causa": ""}
        print(f"Retomando {len(numeros)} processo(s).")

    vistos, grupos = set(), []
    for n in numeros:
        t = tribunais.por_numero(n)
        if t is not None and t.suportado and t.chave not in vistos:
            vistos.add(t.chave)
            grupos.append(t)
    if args.sem_cofre:
        cofre = _CofreComMemoria(None, {})
    else:
        cofre_real = CofreSenhas(caminhos.ARQUIVO_SENHAS)
        cofre = _CofreComMemoria(cofre_real, _pedir_credenciais(grupos, opcoes, cofre_real))

    ctx = ContextoTerminal(eventos=args.eventos, acompanhamento=acomp)
    if not opcoes.mostrar_navegador and not _interativo() and _esaj_por_senha(grupos, opcoes):
        # Sem terminal (a skill do Claude, um script, a tarefa agendada), o
        # código que o e-SAJ manda por e-mail não tem onde ser digitado aqui -
        # e o programa nunca lê senha nem código de arquivo. Com a janela do
        # navegador à vista, o usuário o digita no campo do próprio portal, e o
        # e-SAJ espera por ele (até espera_login_minutos); escondida, o login
        # falharia sem que ninguém pudesse fazer nada.
        opcoes.mostrar_navegador = True
        ctx.avisar("Código do e-SAJ na janela do navegador",
                   "Não há terminal para digitar o código de verificação do e-SAJ: a janela do "
                   "navegador vai ficar visível. Se o e-SAJ pedir o código enviado por e-mail, "
                   "digite-o nessa janela, no campo do código, e clique em Enviar (prazo de "
                   f"{opcoes.espera_login_min} min).")
    if acomp is not None:
        acomp.definir(navegador_visivel=bool(opcoes.mostrar_navegador))
    print("\nComeçando. Ctrl+C para parar (o que já foi baixado fica).\n")
    try:
        resumo = motor.executar(numeros, destino, opcoes, ctx, senhas=leitura.senhas,
                                cofre=cofre, cfg=cfg)
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return falhou("interrompido", "interrompido", codigo=1)
    except (RuntimeError, OSError) as erro:
        # ex.: pasta de destino que não pode ser criada (disco cheio, sem
        # permissão, unidade de rede fora), ou outro download usando a pasta
        # do lote - frase, e não rastro de pilha
        log.error("o lote não pôde ser baixado: %s", erro)
        print(f"\nNão foi possível baixar: {erro}")
        causa = "lote_em_andamento" if isinstance(erro, motor.LoteEmAndamento) else "destino"
        return falhou(str(erro), causa)

    if args.texto:
        _extrair_textos(resumo, cfg, acomp)

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
        codigo = 0
    elif resumo.baixados or resumo.pulados:
        codigo = 1
    else:
        codigo = 2
    return {"codigo": codigo, "resumo": resumo, "erro": "", "causa": ""}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
