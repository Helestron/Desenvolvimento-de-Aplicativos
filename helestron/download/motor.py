"""O motor do download: percorre a relação e entrega um PDF por processo.

Genérico: funciona com qualquer portal que siga o contrato descrito em
modelos.py (entrar/baixar). O e-SAJ e o eProc são só dois deles.

O que o motor garante, seja qual for o portal:

* a ORDEM da relação é a ordem da tabela e do relatório;
* uma relação que mistura tribunais é baixada grupo a grupo (um navegador
  e um login por tribunal), sem o usuário dizer de onde é cada processo;
* processo já baixado é pulado (inclusive se estiver na pasta de
  sigilosos);
* processo em segredo de justiça vai para a pasta de sigilosos, FORA do
  acervo compartilhado com a IA - o PDF, a capa e as gravações. O portal
  grava numa pasta provisória fora do acervo, e nada entra no acervo antes
  de se saber se é sigiloso; uma vez sigiloso, sempre sigiloso (e a cópia
  de outro lote, de quando era público, também sai do acervo, assim como
  as transcrições de audiência já feitas, que vão para
  <sigilosos>\\Transcricoes). Sigiloso é também o que o programa já sabe
  sigiloso pela regra única (nucleo/sigilo.py: autos, transcrição ou
  gravação na pasta de sigilosos, ou a pauta de audiências), mesmo que a
  página do processo não mostre o selo - e a tela dele não vai para
  Logs\\diagnostico, que se envia ao suporte;
* falha passageira é repetida; sessão que cai é refeita; login recusado
  encerra só o grupo daquele tribunal, com o motivo em cada linha;
* tribunal em transição (TJAL, TJSP, TJAC: e-SAJ e eProc): o que não for
  achado no sistema principal é procurado no alternativo, com outro
  navegador e outro login; o relatório diz em que sistema cada um foi achado;
* portal no modo "senha" sem senha guardada: o navegador abre na tela de
  entrada e o usuário entra à mão (é o que a tela promete ao avisar que
  falta a senha), em vez de o grupo inteiro falhar;
* "Parar" não perde o processo interrompido: ele fica pendente e entra na
  próxima rodada (na base, o processo cancelado no meio saía da retomada);
* o relatório (_controle/relatorio.csv) é regravado depois de cada item:
  se a luz cair, ele diz até onde se chegou;
* o computador não dorme enquanto o lote roda.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..nucleo import caminhos, cnj, sigilo, tribunais
from ..nucleo.cnj import Numero
from ..nucleo.sistema import REINSTALAR
from .contexto import Contexto
from .modelos import (CANCELADO, ERRO, JA_BAIXADO, NAO_ENCONTRADO, NAO_SUPORTADO, OK,
                      SEM_ACESSO, SIGILOSO_SEM_SENHA, TENTAR_DE_NOVO, Cancelado, LoginFalhou,
                      OpcoesDownload, PortalIndisponivel, ProcessoNaoEncontrado,
                      ResultadoProcesso, ResumoLote, SemAcesso, SessaoPerdida, SigilosoSemSenha)

log = logging.getLogger("download.motor")

COLUNAS = ["ordem", "processo", "tribunal", "sistema", "situacao", "paginas", "documentos",
           "arquivo", "sigiloso", "incompleto", "detalhe", "data_hora"]
MASCARA_SIGILOSO = "(processo sigiloso)"
SIGILO_ANTERIOR = "assim constava de download anterior"
DETALHE_MASCARA = ("processo em segredo de justiça; o número e os detalhes estão no relatório da "
                   "pasta de sigilosos")
RELATORIOS = ("relatorio.csv", "relatorio (atualizado).csv")
MAX_RELOGINS = 2                 # por processo
MAX_INDISPONIVEL_SEGUIDOS = 3    # processos seguidos com o portal fora: desiste do grupo
ESPERA_ENTRE_TENTATIVAS_S = 3.0  # cresce a cada tentativa (3 s, 6 s...), até 30 s


# ------------------------------------------------------------- fábricas
def fabrica_portal_padrao(nav, tribunal, opcoes: OpcoesDownload, ctx: Contexto,
                          credenciais: tuple[str, str] | None):
    """O portal certo para o tribunal (import tardio: só o que for usado)."""
    if tribunal.sistema == "esaj":
        from .esaj import PortalESAJ
        return PortalESAJ(nav, tribunal, opcoes, ctx, credenciais)
    if tribunal.sistema == "eproc":
        try:
            from .eproc import PortalEProc
        except ModuleNotFoundError as erro:
            if erro.name in ("helestron.download.eproc", __package__ + ".eproc"):
                raise PortalIndisponivel(
                    f"o módulo do eProc não está presente nesta instalação. {REINSTALAR}"
                ) from erro
            raise PortalIndisponivel(
                f"falta um componente para o eProc ({erro.name}). {REINSTALAR}") from erro
        except ImportError as erro:
            raise PortalIndisponivel(
                f"o módulo do eProc não pôde ser carregado ({erro}). {REINSTALAR}") from erro
        return PortalEProc(nav, tribunal, opcoes, ctx, credenciais)
    raise PortalIndisponivel(f"o {tribunal.sigla} usa um sistema que o programa ainda não "
                             "suporta.")


def fabrica_navegador_padrao(tribunal, opcoes: OpcoesDownload):
    """Um navegador com perfil próprio por portal (%LOCALAPPDATA%)."""
    from .navegador import Navegador
    sistema = tribunal.sistema
    escolha = opcoes.navegador or "auto"
    executavel = None
    if escolha.lower() not in ("auto", "chrome", "msedge", "chromium"):
        # caminho de um navegador (ex.: Chrome portátil) escrito no config.ini
        executavel, escolha = (escolha if Path(escolha).is_file() else None), "auto"
    return Navegador(
        caminhos.PERFIS / f"{sistema}-{tribunal.sigla}",
        # O eProc abre SEMPRE com janela: captcha, escolha de perfil e o
        # Keycloak só se resolvem nela. Depois do login o portal a minimiza
        # (CDP) se "mostrar o navegador" estiver desligado.
        visivel=opcoes.navegador_visivel(sistema) or sistema == "eproc",
        canal=escolha,
        executavel=executavel,
        espera_s=opcoes.espera_s,
        pasta_downloads=caminhos.TEMP / "downloads",
        pasta_diagnostico=opcoes.pasta_diagnostico,
        certificado=opcoes.modo_login(sistema) == "certificado",
        salvar_diagnostico=opcoes.salvar_diagnostico,
    )


# ---------------------------------------------------------------- senhas
def senha_de(numero: Numero, senhas: dict[str, str] | None) -> str | None:
    """A senha do processo sigiloso, seja qual for a grafia da chave.

    A relação pode escrever '…0001/0001', '…0001/01' ou só o principal (a
    senha do ofício costuma valer para os incidentes). Compara-se pela
    identidade do número, não pelo texto.
    """
    if not senhas:
        return None
    direta = senhas.get(numero.formatado)
    if direta:
        return direta
    alvo = cnj.chave(numero)
    da_principal = None
    for chave, senha in senhas.items():
        if not senha:
            continue
        try:
            n = cnj.ler(chave)
        except cnj.NumeroInvalido:
            continue
        if cnj.chave(n) == alvo:
            return senha
        if n.digitos == numero.digitos and not n.dependente:
            da_principal = senha
    return da_principal


# ---------------------------------------------------------------- arquivos
def _pdf_valido(caminho: Path) -> bool:
    """Já baixado = existe e é PDF. Arquivo de 0 byte ou truncado não conta."""
    try:
        if not caminho.is_file() or caminho.stat().st_size < 64:
            return False
        with open(caminho, "rb") as f:
            return b"%PDF-" in f.read(1024)
    except OSError:
        return False


def _paginas(caminho: Path) -> int:
    try:
        from . import pdf
        return pdf.contar_paginas(caminho) or 0
    except Exception:
        return 0


def _trocar(origem: Path, destino: Path) -> None:
    # O mesmo os.replace com paciência do pdf.py: o antivírus, o indexador
    # e o OneDrive abrem por um instante o arquivo recém-gravado.
    from .pdf import _trocar as trocar
    trocar(origem, destino)


def _apagar(caminho: Path) -> None:
    from . import pdf
    for tentativa in range(pdf.TENTATIVAS_TROCA):
        try:
            caminho.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if tentativa == pdf.TENTATIVAS_TROCA - 1:
                raise
            time.sleep(pdf.ESPERA_TROCA_S)


def _mover(origem: Path, destino: Path, manter_destino: bool = False) -> Path:
    """Move arquivo ou pasta (pastas são mescladas). Arquivo de mesmo nome
    no destino é substituído: é o mesmo processo, baixado de novo - salvo
    com 'manter_destino', em que o que já está lá vence e a origem, cópia
    antiga, é apagada."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if origem.is_dir():
        destino.mkdir(parents=True, exist_ok=True)
        for item in origem.iterdir():
            _mover(item, destino / item.name, manter_destino)
        try:
            origem.rmdir()
        except OSError:
            pass
        return destino
    if manter_destino and destino.exists():
        _apagar(origem)
        return destino
    if _mesmo_volume(origem, destino):
        _trocar(origem, destino)
    else:
        # Outro disco (pasta de sigilosos em D:, por exemplo): copia ao lado
        # do destino e só então troca - cópia pela metade nunca ganha o nome
        # do PDF - e por fim apaga a origem.
        tmp = destino.with_name(destino.name + ".parcial")
        try:
            shutil.copy2(origem, tmp)
            _trocar(tmp, destino)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        _apagar(origem)
    return destino


def _dentro(caminho: Path, pasta: Path) -> bool:
    try:
        Path(caminho).resolve().relative_to(Path(pasta).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _juntar(*partes: str) -> str:
    return "; ".join(p for p in partes if p)


def _mesmo_volume(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b.parent).st_dev
    except OSError:
        return False


def _mesma_pasta(a: Path, b: Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, RuntimeError):
        return Path(a) == Path(b)


def _do_processo(nome_do_arquivo: str, nome: str) -> bool:
    """O arquivo da pasta de transcrições é deste processo?

    "<nome>.docx", "<nome> (2).docx", "<nome> 2026-09-16 14h00.flac": sim. O
    do incidente ("<nome>-01.docx") não é do principal, nem o do principal é
    do incidente - o nome é conferido também como número CNJ.
    """
    depois = nome_do_arquivo[len(nome):len(nome) + 1]
    if not nome_do_arquivo.startswith(nome) or depois not in ("", " ", "."):
        return False
    try:
        return cnj.ler_nome_arquivo(nome_do_arquivo).nome_arquivo == nome
    except cnj.NumeroInvalido:
        return False


def _transcricoes_do_processo(pasta: Path, nome: str) -> list[list[Path]]:
    """Os arquivos do processo na pasta (sem subpastas), agrupados pelo nome
    sem a extensão: a gravação, o diário e a trava de uma audiência
    ("<nome> 2026-09-16 14h00.flac/.jsonl/.trava") andam juntos."""
    grupos: OrderedDict[str, list[Path]] = OrderedDict()
    try:
        arquivos = sorted(p for p in Path(pasta).iterdir()
                          if p.is_file() and _do_processo(p.name, nome))
    except OSError:
        return []
    for arquivo in arquivos:
        grupos.setdefault(arquivo.stem, []).append(arquivo)
    return list(grupos.values())


def _nome_livre_do_grupo(pasta: Path, grupo: list[Path]) -> str:
    """Nome (sem a extensão) que não existe na pasta para NENHUM arquivo do
    grupo: a gravação e o diário continuam com o mesmo nome, e nada no
    destino é sobrescrito."""
    base = grupo[0].stem
    finais = [a.name[len(base):] for a in grupo]
    candidato, n = base, 2
    while any((pasta / f"{candidato}{final}").exists() for final in finais):
        candidato = f"{base} ({n})"
        n += 1
    return candidato


def _levar_arquivos(origem_dir: Path, alvo_dir: Path, nome: str,
                    manter_destino: bool = False) -> tuple[Path | None, list[str], Exception | None]:
    """Leva o PDF, a capa e as gravações do processo 'nome' (Numero.nome_arquivo)
    de uma pasta de lote (ou da área provisória) para outra. O PDF vai por
    ÚLTIMO: onde ele está, o resto já chegou. 'manter_destino': o que já está
    no destino (a cópia recém-baixada) não é trocado pela cópia antiga.

    Devolve (onde o PDF ficou, problemas com a capa e as gravações, erro do
    PDF). Sem PDF na origem, o primeiro item é None e o erro também.
    """
    problemas: list[str] = []
    for origem, destino in (
            (origem_dir / "_controle" / f"{nome}_capa.txt",
             alvo_dir / "_controle" / f"{nome}_capa.txt"),
            (origem_dir / "_controle" / "midias" / nome,
             alvo_dir / "_controle" / "midias" / nome)):
        if not origem.exists():
            continue
        try:
            _mover(origem, destino, manter_destino)
        except Exception as erro:
            problemas.append(f"{origem.name}: {erro}")
    origem_pdf = origem_dir / f"{nome}.pdf"
    if not origem_pdf.exists():
        return None, problemas, None
    try:
        return _mover(origem_pdf, alvo_dir / f"{nome}.pdf", manter_destino), problemas, None
    except Exception as erro:
        return None, problemas, erro


def _lotes_do_acervo(pasta_processos, raiz_sigilosos: Path,
                     primeiros: list[Path] | None = None) -> list[Path]:
    """As pastas de lote do acervo (Processos/*), fora a de sigilosos;
    'primeiros' vêm antes (o lote em curso)."""
    lotes = list(primeiros or [])
    if pasta_processos is None:
        return lotes
    try:
        for p in sorted(Path(pasta_processos).iterdir()):
            if p.is_dir() and p not in lotes and not _dentro(p, raiz_sigilosos):
                lotes.append(p)
    except OSError:
        pass
    return lotes


def _levar_transcricoes_do_acervo(cfg, nome: str) -> tuple[int, list[Path], bool]:
    """Leva para <sigilosos>/Transcricoes as transcrições de audiência do
    processo 'nome' que estão no acervo (<acervo>/Transcricoes): os DOCX e,
    em _audio, a gravação, o diário e a trava. Nada no destino é
    sobrescrito (nome livre).

    Devolve (arquivos levados, arquivos que não puderam sair, a audiência
    dele está sendo gravada agora). Gravando, nada sai: tirar os arquivos do
    lugar estragaria a gravação; ficam todos como presos.
    """
    try:
        from ..transcricao import documento
        origem = Path(cfg.pasta_transcricoes)
        alvo = Path(documento.pasta_das_transcricoes(cfg, sigiloso=True))
    except Exception as erro:          # configuração sem as pastas (dublê, ini ilegível)
        log.debug("transcrições do sigiloso: pastas indisponíveis (%s)", erro)
        return 0, [], False
    if _mesma_pasta(origem, alvo) or not origem.is_dir():
        return 0, [], False
    pares = [(grupo, alvo) for grupo in _transcricoes_do_processo(origem, nome)]
    pares += [(grupo, alvo / "_audio")
              for grupo in _transcricoes_do_processo(origem / "_audio", nome)]
    if not pares:
        return 0, [], False
    try:
        from ..transcricao.ao_vivo import sessao_aberta
    except ImportError:                # sem o módulo de transcrição, não há gravação aberta
        def sessao_aberta(_diario):
            return False
    gravando = any(sessao_aberta(a) for grupo, _ in pares for a in grupo
                   if a.suffix.lower() == ".jsonl")
    if gravando:
        return 0, [a for grupo, _ in pares for a in grupo], True
    levados = 0
    presos: list[Path] = []
    for grupo, pasta in pares:
        livre = _nome_livre_do_grupo(pasta, grupo)
        base = grupo[0].stem
        for arquivo in grupo:
            destino = pasta / f"{livre}{arquivo.name[len(base):]}"
            try:
                _mover(arquivo, destino)
            except Exception as erro:
                log.warning("    não consegui levar %s para a pasta de sigilosos (%s)",
                            arquivo.name, erro)
                presos.append(arquivo)
                continue
            levados += 1
            log.info("    transcrição do sigiloso levada para a pasta de sigilosos: %s -> %s",
                     arquivo.name, destino)
    return levados, presos, False


def _apagar_texto_da_ia(acervo, nome: str) -> None:
    """O texto integral dos autos em <acervo>/_ia/texto não fica para trás."""
    if acervo is None:
        return
    texto = Path(acervo) / "_ia" / "texto" / f"{nome}.txt"
    try:
        _apagar(texto)
    except OSError as erro:
        log.warning("não consegui apagar %s (%s)", texto, erro)


@dataclass
class Retirada:
    """O que retirar_do_acervo fez com as cópias de um processo sigiloso."""

    autos: dict[Path, Path] = field(default_factory=dict)   # lote do acervo -> PDF levado
    transcricoes: int = 0                                     # arquivos de transcrição levados
    autos_presos: list[Path] = field(default_factory=list)   # PDFs que não puderam sair
    transcricoes_presas: list[Path] = field(default_factory=list)
    gravando: bool = False         # a audiência dele está sendo gravada: a transcrição ficou

    @property
    def presos(self) -> list[Path]:
        return self.autos_presos + self.transcricoes_presas

    @property
    def levou(self) -> bool:
        return bool(self.autos or self.transcricoes)


def retirar_do_acervo(cfg, numero, *, raiz_sigilosos=None, lotes: list[Path] | None = None,
                      acervo=None) -> Retirada:
    """Tira do acervo toda cópia de um processo sigiloso: os autos de cada
    lote (Processos/<lote>/, com capa e gravações) vão para
    <sigilosos>/<lote>/ - o que já estiver lá vence -, as transcrições (com a
    gravação e o diário) para <sigilosos>/Transcricoes, e o texto dele em
    _ia/texto é apagado. O que não puder sair (arquivo aberto, audiência
    sendo gravada) fica na Retirada, para quem chamou não compartilhar o
    acervo enquanto isso.

    'lotes' e 'acervo' (padrão: os da configuração) servem ao motor, que
    também conhece o lote em curso.
    """
    nome = numero.nome_arquivo if hasattr(numero, "nome_arquivo") else \
        cnj.ler_nome_arquivo(str(numero)).nome_arquivo
    raiz_sigilosos = Path(raiz_sigilosos if raiz_sigilosos is not None else cfg.pasta_sigilosos)
    if lotes is None:
        lotes = _lotes_do_acervo(getattr(cfg, "pasta_processos", None), raiz_sigilosos)
    if acervo is None:
        acervo = getattr(cfg, "pasta_acervo", None)
    ret = Retirada()
    for lote in lotes:
        if not (lote / f"{nome}.pdf").exists():
            continue
        novo, _problemas, erro = _levar_arquivos(lote, raiz_sigilosos / lote.name, nome,
                                                 manter_destino=True)
        if erro is not None or novo is None:
            ret.autos_presos.append(lote / f"{nome}.pdf")
            continue
        ret.autos[lote] = novo
        log.info("    cópia do sigiloso em %s levada para a pasta de sigilosos.", lote.name)
    if cfg is not None:
        levados, presas, ret.gravando = _levar_transcricoes_do_acervo(cfg, nome)
        ret.transcricoes = levados
        ret.transcricoes_presas = presas
    _apagar_texto_da_ia(acervo, nome)
    return ret


def _chave_relatorio(texto) -> str | None:
    """O processo de uma linha do relatório ("0700001-..."; o dependente
    "-01" conta), ou None (linha mascarada, editada à mão)."""
    try:
        return cnj.ler_nome_arquivo(str(texto or "").strip()).nome_arquivo
    except Exception:
        return None


# ------------------------------------------------------------------ motor
class _Lote:
    def __init__(self, numeros, destino, opcoes, ctx, senhas, cofre,
                 fabrica_portal, fabrica_navegador, cfg):
        self.destino = Path(destino)
        self.opcoes = opcoes
        self.ctx = ctx or Contexto()
        self.senhas = dict(senhas or {})
        self.cofre = cofre
        self.fabrica_portal = fabrica_portal or fabrica_portal_padrao
        self.fabrica_navegador = fabrica_navegador or fabrica_navegador_padrao
        self.cfg = cfg
        self.controle = self.destino / "_controle"
        self.relatorio = self.controle / "relatorio.csv"
        self.raiz_sigilosos = Path(opcoes.pasta_sigilosos)
        self.pasta_sigilosos = self.raiz_sigilosos / self.destino.name
        self.relatorio_sigilosos = self.pasta_sigilosos / "_controle" / "relatorio.csv"
        # O portal grava aqui, FORA do acervo; só depois de saber se o
        # processo é sigiloso o motor o leva para o lote ou para a pasta de
        # sigilosos. Assim, nem uma separação que falha, nem o Ctrl+C, nem a
        # queda de energia deixam um sigiloso no acervo (ou no OneDrive).
        self.provisorio = Path(getattr(opcoes, "pasta_provisoria", None)
                               or caminhos.TEMP / "baixando")
        self.inicio = time.monotonic()
        self._avisou_relatorio = False
        self._avisou_relatorio_sigilosos = False
        self._interrompido = False
        self._retirou_do_acervo = False
        self._ultimo_preparo = 0.0
        # Cópias de sigilosos que não puderam sair do acervo (arquivo preso).
        self._sigilo_no_acervo: list[str] = []
        self._cfg_lida = None            # config.ini, quando quem chama não deu cfg
        self._nav = None                 # o navegador do grupo em curso
        # Uma vez sigiloso, sempre sigiloso: o que relatórios anteriores
        # deste lote já apuraram (a página nem sempre repete o aviso).
        self._sigilosos_sabidos = self._ler_sigilos_anteriores()
        # Itens reabertos para o sistema alternativo: já contavam como feitos
        # e continuam contando, para a barra de progresso não andar para trás.
        self._reabertos: set[int] = set()
        # Grupo do sistema alternativo em curso: índice -> (situação,
        # detalhe, sistema) do sistema principal, para devolver o
        # "não encontrado" se o alternativo nem puder ser consultado.
        self._anteriores: dict[int, tuple[str, str, str]] = {}

        self.itens: list[ResultadoProcesso] = []
        self.numeros: list[Numero] = []
        vistos: set[str] = set()
        for n in numeros:
            k = cnj.chave(n)
            if k in vistos:
                log.info("%s aparece mais de uma vez na relação; baixo uma vez só.", n.formatado)
                continue
            vistos.add(k)
            t = tribunais.por_numero(n)
            self.numeros.append(n)
            self.itens.append(ResultadoProcesso(
                ordem=len(self.itens) + 1, numero=n.formatado,
                tribunal=t.sigla if t else n.chave_tribunal,
                sistema=t.sistema if t else "?"))
        self.tribunal_de = {cnj.chave(n): tribunais.por_numero(n) for n in self.numeros}
        # O relatório que esta pasta de lote já tinha (o "Tentar de novo" refaz
        # só os que falharam, na mesma pasta): as linhas refeitas agora
        # substituem as antigas, e as demais continuam - senão o relatório do
        # lote, e os "Últimos lotes", ficavam só com os refeitos.
        self._linhas_anteriores = self._ler_relatorio_anterior()

    # ------------------------------------------------------------ apoio
    @property
    def total(self) -> int:
        return len(self.itens)

    def feitos(self) -> int:
        return sum(1 for i, r in enumerate(self.itens) if r.concluido or i in self._reabertos)

    def _publicar(self, r: ResultadoProcesso) -> None:
        try:
            self.ctx.item(r)
        except Exception:      # a tela nunca derruba o lote
            log.debug("ctx.item falhou", exc_info=True)

    def _concluir(self, r: ResultadoProcesso) -> None:
        r.carimbar()
        self._publicar(r)
        self.salvar_relatorio()

    def _dormir(self, segundos: float) -> None:
        limite = time.monotonic() + max(0.0, segundos)
        while time.monotonic() < limite:
            if self.ctx.cancelado():
                raise Cancelado()
            time.sleep(min(0.2, max(0.0, limite - time.monotonic())))

    # ------------------------------------------------------- relatório
    def _linhas_csv(self, mascarar: bool = False) -> str:
        """O relatório. 'mascarar': o do acervo, que a IA lê, não diz qual
        processo é sigiloso; o completo fica na pasta de sigilosos.

        Mescla com o relatório anterior da mesma pasta (_linhas_anteriores):
        cada processo desta rodada fica no lugar da linha antiga dele, os
        que não foram refeitos continuam como estavam, e os novos vêm no fim.
        """
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";", lineterminator="\r\n")
        w.writerow(COLUNAS)
        atuais = {}
        for r in self.itens:
            atuais.setdefault(_chave_relatorio(r.numero), r)
        linhas: list = []
        usados: set = set()
        for chave, antiga in self._linhas_anteriores:
            if chave is not None and chave in atuais:
                if chave not in usados:
                    usados.add(chave)
                    linhas.append(atuais[chave])
                continue
            linhas.append(antiga)
        for r in self.itens:
            chave = _chave_relatorio(r.numero)
            if chave not in usados:
                usados.add(chave)
                linhas.append(r)
        for ordem, item in enumerate(linhas, 1):
            if isinstance(item, dict):
                w.writerow(self._linha_antiga(item, ordem, mascarar))
                continue
            r = item
            if mascarar and r.sigiloso:
                w.writerow([ordem, MASCARA_SIGILOSO, r.tribunal, r.sistema,
                            r.situacao or "PENDENTE", "", "", "", "sim", "", DETALHE_MASCARA,
                            r.data_hora])
                continue
            arquivo = Path(r.arquivo).name if r.arquivo else ""
            if r.arquivo and r.sigiloso and r.situacao in (OK, JA_BAIXADO) \
                    and not str(r.arquivo).startswith(str(self.destino)):
                arquivo += " (na pasta de sigilosos)"
            w.writerow([ordem, r.numero, r.tribunal, r.sistema, r.situacao or "PENDENTE",
                        r.paginas or "", r.documentos or "", arquivo,
                        "sim" if r.sigiloso else "não", r.incompleto, r.detalhe, r.data_hora])
        return saida.getvalue()

    @staticmethod
    def _linha_antiga(linha: dict, ordem: int, mascarar: bool) -> list:
        """A linha de um processo de rodada anterior, como estava (mascarada no
        relatório do acervo, se for sigiloso)."""
        sigiloso = (linha.get("sigiloso") or "").strip().lower() == "sim"
        if mascarar and sigiloso:
            return [ordem, MASCARA_SIGILOSO, linha.get("tribunal", ""), linha.get("sistema", ""),
                    linha.get("situacao") or "PENDENTE", "", "", "", "sim", "", DETALHE_MASCARA,
                    linha.get("data_hora", "")]
        return [ordem] + [linha.get(c, "") or "" for c in COLUNAS[1:]]

    @staticmethod
    def _ler_csv(controle: Path) -> list[dict]:
        """As linhas do relatório da pasta _controle (o mais recente dos dois:
        o "(atualizado)" é o gravado quando o Excel prendia o outro)."""
        candidatos = []
        for nome in RELATORIOS:
            try:
                candidatos.append(((controle / nome).stat().st_mtime, controle / nome))
            except OSError:
                continue
        if not candidatos:
            return []
        try:
            dados = max(candidatos)[1].read_bytes()
        except OSError:
            return []
        try:
            texto = dados.decode("utf-8-sig")
        except UnicodeDecodeError:       # salvo pelo Excel, em ANSI
            texto = dados.decode("cp1252", errors="replace")
        try:
            return [{c: (linha.get(c) or "") for c in COLUNAS}
                    for linha in csv.DictReader(texto.splitlines(), delimiter=";")
                    if any((v or "").strip() for v in linha.values() if isinstance(v, str))]
        except (csv.Error, ValueError, AttributeError) as erro:
            log.warning("o relatório anterior do lote está ilegível (%s); começo um novo.", erro)
            return []

    def _ler_relatorio_anterior(self) -> list[tuple[str | None, dict]]:
        """[(chave do processo ou None, linha)] do relatório que a pasta do lote
        já tinha, na ordem dele. A linha mascarada do acervo ("(processo
        sigiloso)") é trocada pela do relatório completo da pasta de
        sigilosos, de mesma ordem; sem ele, fica como está."""
        acervo = self._ler_csv(self.controle)
        completo = self._ler_csv(self.pasta_sigilosos / "_controle")
        por_ordem = {linha.get("ordem"): linha for linha in completo
                     if _chave_relatorio(linha.get("processo")) is not None}
        saida: list[tuple[str | None, dict]] = []
        vistos: set[str] = set()
        for linha in acervo or completo:
            chave = _chave_relatorio(linha.get("processo"))
            if chave is None and (linha.get("sigiloso") or "").strip().lower() == "sim":
                real = por_ordem.get(linha.get("ordem"))
                if real is not None:
                    linha, chave = real, _chave_relatorio(real.get("processo"))
            if chave is not None:
                if chave in vistos:
                    continue
                vistos.add(chave)
            saida.append((chave, linha))
        for linha in completo:              # o que só o completo ainda tem
            chave = _chave_relatorio(linha.get("processo"))
            if chave is not None and chave not in vistos:
                vistos.add(chave)
                saida.append((chave, linha))
        return saida

    def salvar_relatorio(self) -> None:
        """UTF-8 com BOM e ';' - o Excel brasileiro abre com acento e colunas
        certas num duplo clique. Gravação atômica."""
        mascarar = bool(self.opcoes.separar_sigilosos)
        if mascarar:
            self._salvar_relatorio_sigilosos()
        dados = ("\ufeff" + self._linhas_csv(mascarar)).encode("utf-8")
        tmp = self.relatorio.with_name(self.relatorio.name + ".tmp")
        try:
            self.controle.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(dados)
            os.replace(tmp, self.relatorio)
            return
        except PermissionError:
            # relatório aberto no Excel: o Windows não deixa trocar o arquivo.
            # O .tmp já gravado ficaria esquecido em _controle.
            try:
                tmp.unlink()
            except OSError:
                pass
            alternativo = self.controle / "relatorio (atualizado).csv"
            try:
                tmp = alternativo.with_name(alternativo.name + ".tmp")
                tmp.write_bytes(dados)
                os.replace(tmp, alternativo)
                if not self._avisou_relatorio:
                    self._avisou_relatorio = True
                    log.warning("O relatório está aberto no Excel; gravei a versão "
                                "atualizada em %s.", alternativo.name)
                self.relatorio = alternativo
            except OSError as erro:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                log.warning("não consegui gravar o relatório: %s", erro)
        except OSError as erro:
            log.warning("não consegui gravar o relatório: %s", erro)

    # ------------------------------------------------------- sigilosos
    def _salvar_relatorio_sigilosos(self) -> None:
        """O relatório completo, com os números dos sigilosos, na pasta de
        sigilosos do lote (fora do acervo). Só quando o lote tem sigiloso
        (ou a pasta já existe): lote sem sigiloso não cria pasta nenhuma."""
        if not (any(r.sigiloso for r in self.itens) or self.pasta_sigilosos.is_dir()
                or any((l.get("sigiloso") or "").strip().lower() == "sim"
                       for _, l in self._linhas_anteriores)):
            return
        destino = self.relatorio_sigilosos
        tmp = destino.with_name(destino.name + ".tmp")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(("\ufeff" + self._linhas_csv()).encode("utf-8"))
            os.replace(tmp, destino)
        except OSError as erro:
            try:
                tmp.unlink()
            except OSError:
                pass
            if not self._avisou_relatorio_sigilosos:
                self._avisou_relatorio_sigilosos = True
                log.warning("não consegui gravar o relatório da pasta de sigilosos: %s", erro)

    def _ler_sigilos_anteriores(self) -> set[str]:
        """Os processos que relatórios anteriores deste lote deram como
        sigilosos - inclusive os que falharam (ERRO com sigilo apurado)."""
        sabidos: set[str] = set()
        for controle in (self.controle, self.pasta_sigilosos / "_controle"):
            for nome in ("relatorio.csv", "relatorio (atualizado).csv"):
                try:
                    dados = (controle / nome).read_bytes()
                except OSError:
                    continue
                try:
                    texto = dados.decode("utf-8-sig")
                except UnicodeDecodeError:       # salvo pelo Excel, em ANSI
                    texto = dados.decode("cp1252", errors="replace")
                try:
                    for linha in csv.DictReader(texto.splitlines(), delimiter=";"):
                        if (linha.get("sigiloso") or "").strip().lower() != "sim":
                            continue
                        try:
                            sabidos.add(cnj.ler(linha.get("processo") or "").nome_arquivo)
                        except Exception:        # linha mascarada ou editada à mão
                            continue
                except (csv.Error, ValueError, AttributeError):
                    continue
        return sabidos

    def _ja_baixado(self, n: Numero) -> Path | None:
        nome = f"{n.nome_arquivo}.pdf"
        for pasta in (self.destino, self.pasta_sigilosos):
            if _pdf_valido(pasta / nome):
                return pasta / nome
        return None

    def _motivo_sigilo(self, n: Numero) -> str:
        """Por que o processo já se sabe sigiloso ("" = não se sabe): um
        relatório anterior deste lote ou a capa guardada o deu como sigiloso,
        ou a regra única do sigilo (nucleo/sigilo.py) - autos, transcrição ou
        gravação dele na pasta de sigilosos (de qualquer lote), ou a pauta de
        audiências marcando o segredo de justiça. A página do processo nem
        sempre mostra o selo (segredo decretado depois, layout que a leitura
        não pega): o que o programa já sabe vale do mesmo jeito."""
        nome = n.nome_arquivo
        if nome in self._sigilosos_sabidos:
            return SIGILO_ANTERIOR
        try:
            with open(self.controle / f"{nome}_capa.txt", encoding="utf-8",
                      errors="replace") as f:
                if "SEGREDO DE JUSTIÇA" in f.read(2000):
                    return SIGILO_ANTERIOR
        except OSError:
            pass
        if sigilo.na_pasta(self.raiz_sigilosos, n):
            return sigilo.MOTIVO_PASTA
        if sigilo.na_pauta(n):
            return sigilo.MOTIVO_PAUTA
        return ""

    def _levar(self, origem_dir: Path, alvo_dir: Path, n: Numero,
               r: ResultadoProcesso | None,
               manter_destino: bool = False) -> tuple[Path | None, list[str], Exception | None]:
        """_levar_arquivos, e as gravações do resultado 'r' passam a apontar
        para o novo lugar."""
        nome = n.nome_arquivo
        novo, problemas, erro = _levar_arquivos(origem_dir, alvo_dir, nome, manter_destino)
        if r is not None and r.midias:
            velho_midias = origem_dir / "_controle" / "midias" / nome
            novo_midias = alvo_dir / "_controle" / "midias" / nome
            r.midias = [m.replace(str(velho_midias), str(novo_midias), 1) for m in r.midias]
        return novo, problemas, erro

    def _guardar(self, r: ResultadoProcesso, n: Numero, provisorio: Path) -> None:
        """Leva o processo recém-baixado da área provisória para o lote - ou,
        se sigiloso, para a pasta de sigilosos. Se não der, o processo fica
        como ERRO e NADA dele entra no acervo."""
        nome = f"{n.nome_arquivo}.pdf"
        sigilo = r.sigiloso and self.opcoes.separar_sigilosos
        alvo_dir = self.pasta_sigilosos if sigilo else self.destino
        novo, problemas, erro = self._levar(provisorio, alvo_dir, n, r)
        if novo is None:
            r.situacao, r.arquivo, r.midias = ERRO, "", []
            motivo = (getattr(erro, "strerror", None) or str(erro)) if erro else "o PDF sumiu"
            if sigilo:
                log.error("    %s é sigiloso e não pôde ser guardado na pasta de sigilosos "
                          "(%s): não foi posto no acervo.", n.formatado, erro)
                r.detalhe = _juntar(
                    r.detalhe, f"processo em segredo de justiça: não consegui guardá-lo na pasta "
                    f"de sigilosos ({motivo}). Por segurança, ele não foi posto no acervo. "
                    "Confira a pasta dos sigilosos em Ajustes › Pastas e baixe de novo")
            elif isinstance(erro, PermissionError):
                r.detalhe = (f"não consegui gravar {nome}: o arquivo está aberto em outro "
                             "programa (leitor de PDF?). Feche-o e baixe de novo.")
            else:
                r.detalhe = f"não consegui gravar {nome} na pasta do lote ({motivo})"
            log.error("    %s: %s", n.formatado, r.detalhe)
        else:
            r.arquivo = str(novo)
            if problemas:
                log.warning("    %s: a capa ou as gravações não puderam ser guardadas: %s",
                            n.formatado, "; ".join(problemas))
                r.detalhe = _juntar(r.detalhe, "a capa ou as gravações não puderam ser "
                                    "guardadas; baixe de novo para tê-las")
            if sigilo:
                log.info("    sigiloso: guardado em %s (fora do acervo compartilhado).",
                         alvo_dir)
                r.detalhe = _juntar(r.detalhe, "guardado na pasta de sigilosos")
        if sigilo:
            # Cópias baixadas quando o processo ainda era público (neste
            # lote ou noutro) também saem do acervo.
            self._retirar_do_acervo(r, n)

    def _lotes_do_acervo(self) -> list[Path]:
        """As pastas de lote do acervo (Processos/*), fora a de sigilosos."""
        raiz = getattr(self.cfg, "pasta_processos", None)
        if raiz is None and self.destino.parent.name.lower() == "processos":
            raiz = self.destino.parent           # sem configuração (testes)
        return _lotes_do_acervo(raiz, self.raiz_sigilosos, [self.destino])

    def _retirar_do_acervo(self, r: ResultadoProcesso, n: Numero) -> None:
        """Tira do acervo toda cópia de um processo sigiloso: a deste lote e
        as de outros lotes (Processos/<lote>/), com capa e gravações, para
        Sigilosos/<lote>/; as transcrições; e apaga o texto dele em _ia/texto."""
        acervo = getattr(self.cfg, "pasta_acervo", None)
        if acervo is None and self.destino.parent.name.lower() == "processos":
            acervo = self.destino.parent.parent
        try:
            cfg = self._config()
        except Exception as erro:          # config.ini ilegível: os autos saem assim mesmo
            log.debug("transcrições do sigiloso: configuração indisponível (%s)", erro)
            cfg = None
        ret = retirar_do_acervo(cfg, n, raiz_sigilosos=self.raiz_sigilosos,
                                lotes=self._lotes_do_acervo(), acervo=acervo)
        if ret.autos:
            self._retirou_do_acervo = True
        novo = ret.autos.get(self.destino)
        if novo is not None:
            r.arquivo = str(novo)
            r.detalhe = _juntar(r.detalhe, "levado agora para a pasta de sigilosos")
        self._contar_transcricoes(r, n, ret)
        presos = ret.autos_presos
        if presos:
            self._sigilo_no_acervo += [str(p) for p in presos]
            log.error("ATENÇÃO: %s é sigiloso e NÃO pôde ser tirado do acervo: %s",
                      n.formatado, ", ".join(str(p) for p in presos))
            if r.situacao in (OK, JA_BAIXADO):
                r.situacao = ERRO
            uma = len(presos) == 1
            r.detalhe = _juntar(
                r.detalhe, "ATENÇÃO: processo sigiloso com "
                + ("cópia no acervo que não pôde ser levada" if uma
                   else "cópias no acervo que não puderam ser levadas")
                + " para a pasta de sigilosos (arquivo aberto?): "
                + ", ".join(f"{p.parent.name}\\{p.name}" for p in presos)
                + (". Mova-a" if uma else ". Mova-as") + " à mão antes de compartilhar o acervo")

    def _config(self):
        """A configuração do programa: a recebida ou, sem ela, a do config.ini."""
        if self.cfg is not None:
            return self.cfg
        if self._cfg_lida is None:
            from ..nucleo import config
            self._cfg_lida = config.carregar(criar=False)
        return self._cfg_lida

    def _contar_transcricoes(self, r: ResultadoProcesso, n: Numero, ret: Retirada) -> None:
        """O que aconteceu com as transcrições do sigiloso, no resultado: as
        levadas e as que não puderam sair (contam como sigiloso no acervo,
        como o PDF preso)."""
        if ret.transcricoes:
            self._retirou_do_acervo = True
            r.detalhe = _juntar(r.detalhe, (
                "1 arquivo de transcrição de audiência levado" if ret.transcricoes == 1
                else f"{ret.transcricoes} arquivos de transcrição de audiência levados")
                + " para a pasta de sigilosos")
        presos = ret.transcricoes_presas
        if not presos:
            return
        gravando = ret.gravando
        self._sigilo_no_acervo += [str(p) for p in presos]
        log.error("ATENÇÃO: %s é sigiloso e a transcrição dele NÃO pôde ser tirada do "
                  "acervo%s: %s", n.formatado,
                  " (a audiência está sendo gravada)" if gravando else "",
                  ", ".join(str(p) for p in presos))
        if r.situacao in (OK, JA_BAIXADO):
            r.situacao = ERRO
        um = len(presos) == 1
        if gravando:
            r.detalhe = _juntar(
                r.detalhe, "ATENÇÃO: processo sigiloso com audiência sendo gravada agora; a "
                "transcrição fica no acervo até a gravação terminar. Depois, clique em "
                f"“{TENTAR_DE_NOVO}” para levá-la à pasta de sigilosos antes de compartilhar o "
                "acervo")
        else:
            r.detalhe = _juntar(
                r.detalhe, "ATENÇÃO: processo sigiloso com "
                + ("arquivo de transcrição no acervo que não pôde ser levado" if um
                   else "arquivos de transcrição no acervo que não puderam ser levados")
                + " para a pasta de sigilosos (arquivo aberto?): "
                + ", ".join(p.name for p in presos)
                + (". Mova-o" if um else ". Mova-os") + " à mão antes de compartilhar o acervo")

    def _area_provisoria(self, n: Numero) -> Path:
        """A pasta provisória deste processo, vazia."""
        pasta = self.provisorio / n.nome_arquivo
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    def _limpar_parcial(self, n: Numero) -> None:
        shutil.rmtree(self.provisorio / n.nome_arquivo, ignore_errors=True)
        # parciais de versões anteriores, que gravavam direto no lote
        for sufixo in (".pdf.parcial", ".pdf.parcial2"):
            try:
                (self.destino / f"{n.nome_arquivo}{sufixo}").unlink()
            except OSError:
                pass

    def _limpar_provisorios_antigos(self) -> None:
        """O que um lote interrompido à força (luz, Ctrl+C) deixou na área
        provisória - fora do acervo, mas sem serventia."""
        limite = time.time() - 12 * 3600
        try:
            antigos = [p for p in self.provisorio.iterdir() if p.stat().st_mtime < limite]
        except OSError:
            return
        for p in antigos:
            shutil.rmtree(p, ignore_errors=True)

    # ------------------------------------------------------------ grupos
    def grupos(self) -> "OrderedDict[str, tuple]":
        """(tribunal, índices dos itens) por tribunal, na ordem da primeira
        aparição na relação. Quem não tem portal suportado já sai marcado."""
        saida: OrderedDict[str, tuple] = OrderedDict()
        for i, n in enumerate(self.numeros):
            t = self.tribunal_de[cnj.chave(n)]
            r = self.itens[i]
            if t is None:
                r.situacao = NAO_SUPORTADO
                r.detalhe = tribunais.problema() or (
                    f"tribunal {n.chave_tribunal} não consta do catálogo "
                    "(dados\\tribunais.json); confira o número")
                r.carimbar()
                continue
            if not t.suportado:
                r.situacao = NAO_SUPORTADO
                r.detalhe = (f"{t.sigla}: {t.observacao.strip().rstrip('.')}" if t.observacao
                             else f"o {t.sigla} usa sistema que o programa ainda não baixa")
                r.detalhe += "; baixe pelo portal do tribunal"
                r.carimbar()
                continue
            saida.setdefault(t.chave, (t, []))[1].append(i)
        return saida

    def _encerrar_grupo(self, indices: list[int], situacao: str, detalhe: str) -> None:
        for i in indices:
            r = self.itens[i]
            if r.situacao == "":
                if i in self._anteriores:
                    # O sistema alternativo nem pôde ser consultado: vale o
                    # "não encontrado" do principal, com o porquê.
                    situacao_antes, detalhe_antes, sistema_antes = self._anteriores.pop(i)
                    r.situacao, r.sistema = situacao_antes, sistema_antes
                    r.detalhe = "; ".join(x for x in (detalhe_antes, detalhe) if x)
                else:
                    r.situacao = situacao
                    r.detalhe = detalhe
                self._concluir(r)

    def _credenciais(self, tribunal) -> tuple[str, str] | None:
        if self.opcoes.modo_login(tribunal.sistema) != "senha" or self.cofre is None:
            return None
        try:
            usuario, senha = self.cofre.obter(tribunal.portal)
        except Exception as erro:
            log.warning("não consegui ler a senha guardada de %s: %s", tribunal.portal, erro)
            return None
        return (usuario, senha) if usuario and senha else None

    def _opcoes_do_grupo(self, tribunal, credenciais) -> OpcoesDownload:
        """As opções com que o grupo entra no portal.

        Modo "senha" sem senha guardada vira "manual" só para este grupo: o
        navegador abre VISÍVEL na tela de entrada e o usuário entra como de
        costume (a tela de download promete exatamente isso quando avisa que
        falta a senha). Com a sessão anterior ainda válida, o portal nem
        chega a pedir nada.
        """
        sistema = tribunal.sistema
        if self.opcoes.modo_login(sistema) != "senha" or credenciais is not None:
            return self.opcoes
        log.info("Sem usuário e senha guardados para o %s do %s: o navegador abre na tela "
                 "de entrada para você entrar.", tribunal.nome_sistema, tribunal.sigla)
        return replace(self.opcoes, login={**self.opcoes.login, sistema: "manual"})

    def executar(self) -> ResumoLote:
        from ..nucleo.energia import manter_acordado

        try:
            self.destino.mkdir(parents=True, exist_ok=True)
        except OSError as erro:
            raise RuntimeError(f"não consegui criar a pasta de destino {self.destino} "
                               f"({erro.strerror or erro}). Escolha outra pasta.") from erro
        grupos = self.grupos()
        self._limpar_provisorios_antigos()
        for r in self.itens:
            self._publicar(r)
        self.salvar_relatorio()
        log.info("Lote %s: %d processo(s) em %d tribunal(is) suportado(s).",
                 self.destino.name, self.total, len(grupos))
        try:
            with manter_acordado("download de processos"):
                for tribunal, indices in grupos.values():
                    if self.ctx.cancelado():
                        break
                    self._grupo(tribunal, indices)
                    self._no_alternativo(tribunal, indices)
        except KeyboardInterrupt:
            # Ctrl+C no terminal: para como o botão "Parar", sem perder nada
            self._interrompido = True
            log.warning("Interrompido pelo teclado.")
        finally:
            self._reabertos.clear()
            self._anteriores.clear()
            for r in self.itens:
                if r.situacao == "":
                    r.situacao = CANCELADO
                    r.detalhe = r.detalhe or "não chegou a ser baixado (lote interrompido)"
                    self._publicar(r)
            self.salvar_relatorio()
            try:
                self.ctx.progresso(self.feitos(), self.total, "")
            except Exception:
                pass
        resumo = ResumoLote(itens=self.itens, destino=self.destino, relatorio=self.relatorio,
                            minutos=round((time.monotonic() - self.inicio) / 60, 1),
                            sigilosos_no_acervo=list(self._sigilo_no_acervo))
        log.info("Fim do lote: %s Relatório: %s", resumo.texto(), self.relatorio)
        if self._sigilo_no_acervo:
            # Não se prepara nada para a IA com um sigiloso no acervo: o
            # texto dele iria para _ia/texto e para o índice.
            um = len(self._sigilo_no_acervo) == 1
            try:
                self.ctx.avisar(
                    "Processo sigiloso ficou no acervo",
                    ("Não consegui levar para a pasta de sigilosos o arquivo " if um
                     else "Não consegui levar para a pasta de sigilosos os arquivos ")
                    + "; ".join(self._sigilo_no_acervo)
                    + (". Feche o programa que o mantém aberto e mova-o" if um
                       else ". Feche o programa que os mantém abertos e mova-os")
                    + f" à mão (ou clique em “{TENTAR_DE_NOVO}”) antes de compartilhar o acervo.")
            except Exception:
                pass
            return resumo
        # Depois de "Parar" (ou Ctrl+C), o usuário quer o programa livre já:
        # o preparo pode ler dezenas de PDFs. Fica para o botão "Preparar
        # arquivos para IA" ou para o próximo lote.
        parou = self._interrompido or self._cancelado()
        if self.opcoes.atualizar_ia and (resumo.baixados or self._retirou_do_acervo) \
                and not parou:
            presos = self._preparar_ia()
            if presos:
                # O preparo tira do acervo o que o programa já sabe sigiloso
                # (pasta, pauta); o que ficou preso trava o compartilhamento.
                resumo.sigilosos_no_acervo += [str(p) for p in presos]
                try:
                    from ..compartilhar.preparo import frase_sigilosos_no_acervo
                    self.ctx.avisar("Processo sigiloso ficou no acervo",
                                    frase_sigilosos_no_acervo(presos))
                except Exception:
                    pass
        return resumo

    def _cancelado(self) -> bool:
        try:
            return bool(self.ctx.cancelado())
        except Exception:
            return False

    def _no_alternativo(self, tribunal, indices: list[int]) -> None:
        """Procura no sistema alternativo o que o principal não achou.

        Tribunais em transição (TJAL, TJSP, TJAC) têm processos no e-SAJ e
        no eProc, e o número não diz em qual. O que voltou NAO_ENCONTRADO do
        principal é reaberto e passa pelo grupo do alternativo (outro
        navegador, outro login). Se o alternativo nem puder ser consultado
        (login recusado, módulo ausente, portal fora), o item volta a
        "não encontrado", com o motivo - e não vira um erro novo.
        """
        alt = getattr(tribunal, "alternativo", None)
        if alt is None or not getattr(alt, "suportado", False) or self._cancelado():
            return
        reabrir = [i for i in indices if self.itens[i].situacao == NAO_ENCONTRADO]
        if not reabrir:
            return
        log.info("%d processo(s) não achado(s) no %s do %s; procurando no %s.", len(reabrir),
                 tribunal.nome_sistema, tribunal.sigla, alt.nome_sistema)
        for i in reabrir:
            r = self.itens[i]
            self._anteriores[i] = (r.situacao, r.detalhe, r.sistema)
            self._reabertos.add(i)
            # sistema já trocado: o desfecho que o portal levantar como
            # exceção (sem acesso, sigiloso) sai com o sistema certo
            r.situacao, r.detalhe, r.sistema = "", "", alt.sistema
        try:
            self._grupo(alt, reabrir)
        finally:
            for i in reabrir:
                r = self.itens[i]
                antes = self._anteriores.pop(i, None)
                self._reabertos.discard(i)
                if antes is None:
                    continue           # devolvido ao "não encontrado" do principal
                if r.situacao == NAO_ENCONTRADO:
                    r.sistema = antes[2]
                    r.detalhe = (f"não encontrado no {tribunal.nome_sistema} nem no "
                                 f"{alt.nome_sistema} do {tribunal.sigla}; confira o número")
                    self._concluir(r)
                elif r.situacao == ERRO:
                    r.detalhe = (f"não encontrado no {tribunal.nome_sistema}; no "
                                 f"{alt.nome_sistema}: {r.detalhe}")
                    self._concluir(r)
                elif r.situacao in ("", CANCELADO):
                    r.sistema = antes[2]     # interrompido: nada se apurou no alternativo

    def _preparar_ia(self) -> list[Path]:
        """Atualiza INDICE.md, CLAUDE.md e os textos do acervo. Nunca falha o lote.
        Devolve as cópias de processo sigiloso que o preparo não conseguiu
        tirar do acervo."""
        try:
            from ..compartilhar import preparo
        except ImportError:
            log.debug("preparo da IA indisponível nesta versão")
            return []
        try:
            self.ctx.status("Preparando os arquivos para a IA...")
            cfg = self.cfg
            if cfg is None:
                from ..nucleo import config
                cfg = config.carregar(criar=False)
            rel = preparo.atualizar_contexto(cfg, progresso=self._progresso_preparo,
                                             cancelado=self._cancelado)
        except Exception as erro:
            log.warning("não consegui preparar os arquivos para a IA (%s); use o botão "
                        "“Preparar acervo para a IA” na tela Compartilhar.", str(erro)[:160])
            return []
        presos = getattr(rel, "sigilosos_no_acervo", None)
        return [Path(p) for p in presos] if isinstance(presos, list) else []

    def _progresso_preparo(self, feitos: int, total: int, _descricao: str = "") -> None:
        # No máximo um recado a cada 2 s: no terminal, cada um vira uma linha.
        agora = time.monotonic()
        if total and agora - self._ultimo_preparo >= 2.0:
            self._ultimo_preparo = agora
            self.ctx.status(f"Preparando os arquivos para a IA ({feitos} de {total})...")

    # -------------------------------------------------------------- grupo
    def _grupo(self, tribunal, indices: list[int]) -> None:
        nome = f"{tribunal.nome_sistema} do {tribunal.sigla}"
        credenciais = self._credenciais(tribunal)
        opcoes = self._opcoes_do_grupo(tribunal, credenciais)
        try:
            with self.fabrica_navegador(tribunal, opcoes) as nav:
                self._nav = nav
                portal = self.fabrica_portal(nav, tribunal, opcoes, self.ctx, credenciais)
                self.ctx.status(f"Entrando no {nome}...")
                portal.entrar()
                seguidos_fora = 0
                for posicao, i in enumerate(indices):
                    if self.ctx.cancelado():
                        raise Cancelado()
                    usou_portal, fora = self._item(portal, i)
                    seguidos_fora = seguidos_fora + 1 if fora else 0
                    if seguidos_fora >= MAX_INDISPONIVEL_SEGUIDOS:
                        resto = [j for j in indices if self.itens[j].situacao == ""]
                        self._encerrar_grupo(
                            resto, ERRO, f"o {nome} parou de responder; tente mais tarde")
                        log.error("O %s parou de responder: desisti dos %d processo(s) "
                                  "restantes do grupo.", nome, len(resto))
                        return
                    if usou_portal and posicao < len(indices) - 1 and self.opcoes.pausa:
                        self._dormir(self.opcoes.pausa)
        except Cancelado:
            # Só o item que estava em curso recebe este recado; os que nem
            # começaram são marcados no fim do lote. Todos voltam na próxima.
            for i in indices:
                r = self.itens[i]
                if r.situacao == "":
                    r.situacao = CANCELADO
                    r.detalhe = "interrompido pelo usuário; será baixado na próxima vez"
                    self._concluir(r)
                    break
            log.info("Download interrompido pelo usuário.")
        except LoginFalhou as erro:
            log.error("Login no %s falhou: %s", nome, erro)
            self._encerrar_grupo(indices, ERRO, f"login falhou: {erro}")
            try:
                texto = str(erro)
                self.ctx.avisar(f"Não foi possível entrar no {nome}", texto[:1].upper() + texto[1:])
            except Exception:
                pass
        except PortalIndisponivel as erro:
            log.error("%s indisponível: %s", nome, erro)
            self._encerrar_grupo(indices, ERRO, f"portal indisponível: {erro}")
        except Exception as erro:          # nada de lote morto sem explicação
            log.exception("Erro inesperado no grupo do %s", nome)
            self._encerrar_grupo(indices, ERRO, f"erro inesperado: {str(erro)[:200]}")

    def _tela_sigilosa(self, sigiloso: bool) -> None:
        """Avisa o navegador de que a tela em curso é de processo sigiloso:
        ele não a guarda em Logs\\diagnostico."""
        if self._nav is None:
            return
        try:
            self._nav.sigiloso_em_curso = sigiloso
        except Exception:                  # navegador sem o atributo (dublê): nada a fazer
            pass

    # --------------------------------------------------------------- item
    def _item(self, portal, i: int) -> tuple[bool, bool]:
        """Baixa um processo. Devolve (usou o portal?, terminou com o portal fora?)."""
        r = self.itens[i]
        n = self.numeros[i]
        try:
            self.ctx.progresso(self.feitos(), self.total, n.formatado)
        except Exception:
            pass
        log.info("[%d/%d] %s", r.ordem, self.total, n.formatado)

        # O que o programa já sabe do sigilo deste processo (relatório
        # anterior, pasta de sigilosos, pauta): vale mesmo que a página do
        # portal não mostre o selo.
        motivo = self._motivo_sigilo(n)
        if self.opcoes.pular_baixados:
            existente = self._ja_baixado(n)
            if existente is not None:
                r.situacao = JA_BAIXADO
                r.arquivo = str(existente)
                r.paginas = _paginas(existente)
                r.sigiloso = existente.parent == self.pasta_sigilosos or bool(motivo)
                r.detalhe = "já estava na pasta (não baixei de novo)"
                if r.sigiloso and self.opcoes.separar_sigilosos:
                    # sigiloso que ficou no acervo (separação que falhou numa
                    # versão anterior, ou cópia de quando era público)
                    self._retirar_do_acervo(r, n)
                self._concluir(r)
                return False, False

        provisorio = self._area_provisoria(n)
        alvo = provisorio / f"{n.nome_arquivo}.pdf"
        senha = senha_de(n, self.senhas)
        inicio = time.monotonic()
        tentativas = max(1, int(self.opcoes.tentativas))
        tentativa = 0
        relogins = 0
        ultimo: Exception | None = None
        res: ResultadoProcesso | None = None
        # Sem ctx.item(r) aqui: o item ainda não mudou, e a tela, que acabou de
        # marcar a linha "baixando…" pelo progresso, a voltaria a "aguardando".
        # A tela de processo já sabido sigiloso não vai para Logs\\diagnostico
        # (a página traz as partes, e o diagnóstico é o que se envia ao suporte).
        self._tela_sigilosa(bool(motivo))
        while True:
            if self.ctx.cancelado():
                raise Cancelado()
            tentativa += 1
            try:
                res = portal.baixar(n, alvo, senha)
                break
            except (Cancelado, LoginFalhou):
                self._limpar_parcial(n)
                raise
            except SessaoPerdida as erro:
                ultimo = erro
                if relogins >= MAX_RELOGINS:
                    break
                relogins += 1
                tentativa -= 1           # relogin não gasta tentativa
                log.info("    a sessão caiu (%s); entrando de novo...", str(erro)[:120])
                self.ctx.status("A sessão caiu; entrando de novo...")
                portal.entrar()
                continue
            except ProcessoNaoEncontrado as erro:
                res = self._definitivo(r, NAO_ENCONTRADO, erro)
                break
            except SemAcesso as erro:
                res = self._definitivo(r, SEM_ACESSO, erro)
                break
            except SigilosoSemSenha as erro:
                res = self._definitivo(r, SIGILOSO_SEM_SENHA, erro)
                res.sigiloso = True
                break
            except PermissionError as erro:
                # O PDF está aberto no leitor (o Windows trava o arquivo):
                # repetir não adianta enquanto o usuário não o fechar.
                ultimo = PermissionError(
                    f"não consegui gravar {alvo.name}: o arquivo está aberto em outro programa "
                    "(leitor de PDF?). Feche-o e baixe de novo.")
                ultimo.__cause__ = erro
                self._limpar_parcial(n)
                break
            except Exception as erro:
                ultimo = erro
                self._area_provisoria(n)       # a próxima tentativa começa do zero
                if tentativa >= tentativas:
                    break
                log.warning("    falhou (%s); tentando de novo (%d/%d)...",
                            str(erro)[:160] or type(erro).__name__, tentativa + 1, tentativas)
                self.ctx.status(f"{n.formatado}: falhou; tentando de novo "
                                f"({tentativa + 1}/{tentativas})...")
                self._dormir(min(30.0, ESPERA_ENTRE_TENTATIVAS_S * tentativa))

        self._tela_sigilosa(False)
        fora = False
        if res is None:
            r.situacao = ERRO
            r.detalhe = str(ultimo) if ultimo else "falhou sem explicação"
            fora = isinstance(ultimo, PortalIndisponivel)
            log.error("    %s: %s", n.formatado, r.detalhe)
        else:
            r.absorver(res)
            if r.situacao == OK and not _pdf_valido(alvo):
                r.situacao = ERRO
                r.detalhe = "o portal informou sucesso, mas o PDF não foi gravado"
            if r.situacao not in (OK, JA_BAIXADO, NAO_ENCONTRADO, SEM_ACESSO,
                                  SIGILOSO_SEM_SENHA, NAO_SUPORTADO, ERRO, CANCELADO):
                r.situacao, r.detalhe = ERRO, f"situação desconhecida: {res.situacao!r}"
        # Uma vez sigiloso, sempre sigiloso: o que o portal apurou numa
        # tentativa que falhou, ou um download anterior, vale para esta.
        if n.nome_arquivo in (getattr(portal, "sigilosos_apurados", None) or ()):
            r.sigiloso = True
        elif not r.sigiloso and motivo:
            r.sigiloso = True
            if r.situacao == OK:
                r.detalhe = _juntar(r.detalhe, f"tratado como sigiloso: {motivo}")
        try:
            if r.situacao == OK:
                self._guardar(r, n, provisorio)
            elif r.sigiloso and self.opcoes.separar_sigilosos:
                self._retirar_do_acervo(r, n)
        except BaseException:
            # Ctrl+C no meio da guarda: o que não chegou ao destino volta
            # para a fila (o fim do lote o marca como interrompido)
            if r.situacao == OK and r.arquivo and _dentro(r.arquivo, self.provisorio):
                r.situacao = ""
            raise
        finally:
            if r.arquivo and _dentro(r.arquivo, self.provisorio):
                r.arquivo, r.midias = "", []       # a área provisória é apagada
            self._limpar_parcial(n)
        r.segundos = round(time.monotonic() - inicio, 1)
        self._concluir(r)
        return True, fora

    @staticmethod
    def _definitivo(r: ResultadoProcesso, situacao: str, erro: Exception) -> ResultadoProcesso:
        return ResultadoProcesso(ordem=r.ordem, numero=r.numero, tribunal=r.tribunal,
                                 sistema=r.sistema, situacao=situacao, detalhe=str(erro))


def executar(numeros: list[Numero], destino: Path, opcoes: OpcoesDownload, ctx: Contexto,
             senhas: dict[str, str] | None = None, cofre=None,
             fabrica_portal=None, fabrica_navegador=None, cfg=None) -> ResumoLote:
    """Baixa a relação para ``destino`` (um PDF por processo) e devolve o resumo.

    ``fabrica_portal(nav, tribunal, opcoes, ctx, credenciais)`` e
    ``fabrica_navegador(tribunal, opcoes)`` existem para os testes
    injetarem dublês; ``cfg`` só é usado no preparo final para a IA.
    """
    lote = _Lote(numeros, destino, opcoes, ctx, senhas, cofre,
                 fabrica_portal, fabrica_navegador, cfg)
    return lote.executar()
