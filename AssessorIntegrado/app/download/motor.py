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
  acervo compartilhado com a IA - o PDF, a capa e as gravações;
* falha passageira é repetida; sessão que cai é refeita; login recusado
  encerra só o grupo daquele tribunal, com o motivo em cada linha;
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
from pathlib import Path

from ..nucleo import caminhos, cnj, tribunais
from ..nucleo.cnj import Numero
from .contexto import Contexto
from .modelos import (CANCELADO, ERRO, JA_BAIXADO, NAO_ENCONTRADO, NAO_SUPORTADO, OK,
                      SEM_ACESSO, SIGILOSO_SEM_SENHA, Cancelado, LoginFalhou, OpcoesDownload,
                      PortalIndisponivel, ProcessoNaoEncontrado, ResultadoProcesso, ResumoLote,
                      SemAcesso, SessaoPerdida, SigilosoSemSenha)

log = logging.getLogger("download.motor")

COLUNAS = ["ordem", "processo", "tribunal", "sistema", "situacao", "paginas", "documentos",
           "arquivo", "sigiloso", "incompleto", "detalhe", "data_hora"]
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
            if erro.name in ("app.download.eproc", __package__ + ".eproc"):
                raise PortalIndisponivel(
                    "o módulo do eProc não está presente nesta instalação. Atualize o "
                    "programa (ou rode o INSTALAR.bat de novo).") from erro
            raise PortalIndisponivel(
                f"falta um componente para o eProc ({erro.name}). Rode o INSTALAR.bat de novo."
            ) from erro
        except ImportError as erro:
            raise PortalIndisponivel(
                f"o módulo do eProc não pôde ser carregado ({erro}). Rode o INSTALAR.bat "
                "de novo.") from erro
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
        # caminho de um navegador (ex.: Chrome portátil) informado nas Configurações
        executavel, escolha = (escolha if Path(escolha).is_file() else None), "auto"
    return Navegador(
        caminhos.PERFIS / f"{sistema}-{tribunal.sigla}",
        visivel=opcoes.navegador_visivel(sistema),
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


def _mover(origem: Path, destino: Path) -> Path:
    """Move arquivo ou pasta (pastas são mescladas). Arquivo de mesmo nome
    no destino é substituído: é o mesmo processo, baixado de novo."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if origem.is_dir():
        destino.mkdir(parents=True, exist_ok=True)
        for item in origem.iterdir():
            _mover(item, destino / item.name)
        try:
            origem.rmdir()
        except OSError:
            pass
        return destino
    if _mesmo_volume(origem, destino):
        os.replace(origem, destino)
    else:
        # outro disco (pasta de sigilosos em D:, por exemplo): copia e apaga
        shutil.move(str(origem), str(destino))
    return destino


def _mesmo_volume(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b.parent).st_dev
    except OSError:
        return False


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
        self.pasta_sigilosos = Path(opcoes.pasta_sigilosos) / self.destino.name
        self.inicio = time.monotonic()
        self._avisou_relatorio = False

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

    # ------------------------------------------------------------ apoio
    @property
    def total(self) -> int:
        return len(self.itens)

    def feitos(self) -> int:
        return sum(1 for r in self.itens if r.concluido)

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
    def _linhas_csv(self) -> str:
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";", lineterminator="\r\n")
        w.writerow(COLUNAS)
        for r in self.itens:
            arquivo = Path(r.arquivo).name if r.arquivo else ""
            if r.arquivo and r.sigiloso and r.situacao in (OK, JA_BAIXADO) \
                    and not str(r.arquivo).startswith(str(self.destino)):
                arquivo += " (na pasta de sigilosos)"
            w.writerow([r.ordem, r.numero, r.tribunal, r.sistema, r.situacao or "PENDENTE",
                        r.paginas or "", r.documentos or "", arquivo,
                        "sim" if r.sigiloso else "não", r.incompleto, r.detalhe, r.data_hora])
        return saida.getvalue()

    def salvar_relatorio(self) -> None:
        """UTF-8 com BOM e ';' - o Excel brasileiro abre com acento e colunas
        certas num duplo clique. Gravação atômica."""
        dados = ("\ufeff" + self._linhas_csv()).encode("utf-8")
        try:
            self.controle.mkdir(parents=True, exist_ok=True)
            tmp = self.relatorio.with_name(self.relatorio.name + ".tmp")
            tmp.write_bytes(dados)
            os.replace(tmp, self.relatorio)
            return
        except PermissionError:
            # relatório aberto no Excel: o Windows não deixa trocar o arquivo
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
                log.warning("não consegui gravar o relatório: %s", erro)
        except OSError as erro:
            log.warning("não consegui gravar o relatório: %s", erro)

    # ------------------------------------------------------- sigilosos
    def _ja_baixado(self, n: Numero) -> Path | None:
        nome = f"{n.nome_arquivo}.pdf"
        for pasta in (self.destino, self.pasta_sigilosos):
            if _pdf_valido(pasta / nome):
                return pasta / nome
        return None

    def _mover_sigiloso(self, r: ResultadoProcesso, n: Numero) -> None:
        """Leva para a pasta de sigilosos TUDO o que é do processo: o PDF, a
        capa e as gravações. Arquivo esquecido no acervo iria para a IA."""
        alvo_dir = self.pasta_sigilosos
        movidos = []
        problemas = []
        candidatos = [
            (self.destino / f"{n.nome_arquivo}.pdf", alvo_dir / f"{n.nome_arquivo}.pdf"),
            (self.controle / f"{n.nome_arquivo}_capa.txt",
             alvo_dir / "_controle" / f"{n.nome_arquivo}_capa.txt"),
            (self.controle / "midias" / n.nome_arquivo,
             alvo_dir / "_controle" / "midias" / n.nome_arquivo),
        ]
        for origem, destino in candidatos:
            if not origem.exists():
                continue
            try:
                novo = _mover(origem, destino)
                movidos.append(novo)
                if origem.suffix == ".pdf":
                    r.arquivo = str(novo)
            except OSError as erro:
                problemas.append(f"{origem.name}: {erro}")
        if r.midias:
            velho = str(self.controle / "midias" / n.nome_arquivo)
            novo = str(alvo_dir / "_controle" / "midias" / n.nome_arquivo)
            r.midias = [m.replace(velho, novo, 1) for m in r.midias]
        if problemas:
            log.error("ATENÇÃO: %s é sigiloso e NÃO pôde ser tirado do acervo: %s",
                      n.formatado, "; ".join(problemas))
            r.detalhe = "; ".join(x for x in (
                r.detalhe, "ATENÇÃO: sigiloso não pôde ser movido para a pasta de sigilosos "
                "(arquivo aberto?). Mova-o à mão antes de compartilhar o acervo") if x)
        elif movidos:
            log.info("    sigiloso: guardado em %s (fora do acervo compartilhado).", alvo_dir)
            r.detalhe = "; ".join(x for x in (r.detalhe, "guardado na pasta de sigilosos") if x)

    def _limpar_parcial(self, n: Numero) -> None:
        for sufixo in (".pdf.parcial", ".pdf.parcial2"):
            try:
                (self.destino / f"{n.nome_arquivo}{sufixo}").unlink()
            except OSError:
                pass

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
                r.detalhe = (f"tribunal {n.chave_tribunal} não consta do catálogo "
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

    def executar(self) -> ResumoLote:
        from ..nucleo.energia import manter_acordado

        try:
            self.destino.mkdir(parents=True, exist_ok=True)
        except OSError as erro:
            raise RuntimeError(f"não consegui criar a pasta de destino {self.destino} "
                               f"({erro.strerror or erro}). Escolha outra pasta.") from erro
        grupos = self.grupos()
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
        except KeyboardInterrupt:
            # Ctrl+C no terminal: para como o botão "Parar", sem perder nada
            log.warning("Interrompido pelo teclado.")
        finally:
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
                            minutos=round((time.monotonic() - self.inicio) / 60, 1))
        log.info("Fim do lote: %s Relatório: %s", resumo.texto(), self.relatorio)
        if self.opcoes.atualizar_ia and resumo.baixados:
            self._preparar_ia()
        return resumo

    def _preparar_ia(self) -> None:
        """Atualiza INDICE.md, CLAUDE.md e os textos do acervo. Nunca falha o lote."""
        try:
            from ..compartilhar import preparo
        except ImportError:
            log.debug("preparo da IA indisponível nesta versão")
            return
        try:
            self.ctx.status("Preparando os arquivos para a IA...")
            cfg = self.cfg
            if cfg is None:
                from ..nucleo import config
                cfg = config.carregar()
            preparo.atualizar_contexto(cfg)
        except Exception as erro:
            log.warning("não consegui preparar os arquivos para a IA (%s); use o botão "
                        "'Preparar arquivos para IA' na tela Compartilhar.", str(erro)[:160])

    # -------------------------------------------------------------- grupo
    def _grupo(self, tribunal, indices: list[int]) -> None:
        nome = f"{tribunal.nome_sistema} do {tribunal.sigla}"
        try:
            with self.fabrica_navegador(tribunal, self.opcoes) as nav:
                portal = self.fabrica_portal(nav, tribunal, self.opcoes, self.ctx,
                                             self._credenciais(tribunal))
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

        if self.opcoes.pular_baixados:
            existente = self._ja_baixado(n)
            if existente is not None:
                r.situacao = JA_BAIXADO
                r.arquivo = str(existente)
                r.paginas = _paginas(existente)
                r.sigiloso = existente.parent == self.pasta_sigilosos
                r.detalhe = "já estava na pasta (não baixei de novo)"
                self._concluir(r)
                return False, False

        alvo = self.destino / f"{n.nome_arquivo}.pdf"
        senha = senha_de(n, self.senhas)
        inicio = time.monotonic()
        tentativas = max(1, int(self.opcoes.tentativas))
        tentativa = 0
        relogins = 0
        ultimo: Exception | None = None
        res: ResultadoProcesso | None = None
        self._publicar(r)
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
                self._limpar_parcial(n)
                if tentativa >= tentativas:
                    break
                log.warning("    falhou (%s); tentando de novo (%d/%d)...",
                            str(erro)[:160] or type(erro).__name__, tentativa + 1, tentativas)
                self.ctx.status(f"{n.formatado}: falhou; tentando de novo "
                                f"({tentativa + 1}/{tentativas})...")
                self._dormir(min(30.0, ESPERA_ENTRE_TENTATIVAS_S * tentativa))

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
            if r.situacao == OK:
                r.arquivo = str(alvo)
            if r.situacao not in (OK, JA_BAIXADO, NAO_ENCONTRADO, SEM_ACESSO,
                                  SIGILOSO_SEM_SENHA, NAO_SUPORTADO, ERRO, CANCELADO):
                r.situacao, r.detalhe = ERRO, f"situação desconhecida: {res.situacao!r}"
        if r.situacao == OK and r.sigiloso and self.opcoes.separar_sigilosos:
            self._mover_sigiloso(r, n)
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
