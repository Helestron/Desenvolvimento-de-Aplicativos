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
  gravação na pasta de sigilosos, ou a pauta de audiências) - e o incidente
  ("/01") de um processo sigiloso, que herda o sigilo do principal -, mesmo
  que a página do processo não mostre o selo; a tela dele não vai para
  Logs\\diagnostico, que se envia ao suporte, e o que ainda houver dele no
  acervo (a minuta em Produtos/, a linha no relatório de outro lote) sai;
* falha passageira é repetida; sessão que cai é refeita; login recusado
  encerra só o grupo daquele tribunal, com o motivo em cada linha;
* tribunal em transição (TJAL, TJSP, TJAC: e-SAJ e eProc): o que não for
  achado no sistema principal é procurado no alternativo, com outro
  navegador e outro login; o relatório diz em que sistema cada um foi achado;
* cada processo vai ao grau que a regra única lhe dá (cnj.grau_do_processo:
  o número - órgão 0000 ou 9xxx, recurso interno /50000 -, senão o grau do
  lote), num grupo por tribunal e grau, sem troca automática de grau (a
  troca de sistema e-SAJ -> eProc é dentro do mesmo grau). Os autos do 2º
  grau chamam-se "<número> (2G).pdf", e a capa, o registro, a pasta
  provisória e a linha do relatório seguem esse nome (a chave dos autos):
  o mesmo número no 1º e no 2º grau, na mesma pasta, são dois autos. O
  sigilo continua por processo e vale para os dois graus;
* portal no modo "senha" sem senha guardada: o navegador abre na tela de
  entrada e o usuário entra à mão (é o que a tela promete ao avisar que
  falta a senha), em vez de o grupo inteiro falhar;
* "Parar" não perde o processo interrompido: ele fica pendente e entra na
  próxima rodada (na base, o processo cancelado no meio saía da retomada);
* o relatório (_controle/relatorio.csv) é regravado depois de cada item:
  se a luz cair, ele diz até onde se chegou; cada linha diz, além da
  situação, a CAUSA (coluna "causa", legível por máquina) do que não deu OK;
* o que já estava na pasta conserva o registro do download que o trouxe
  (sistema, documentos, folhas ausentes, detalhe): o manifesto de paginação
  gravado no PDF, o _controle/<chave dos autos>_meta.json ao lado dele e, por
  fim, a linha anterior do relatório - rodar a mesma relação de novo não
  apaga nada;
* a pasta do lote não é usada por dois downloads ao mesmo tempo
  (_controle/.executando);
* o computador não dorme enquanto o lote roda.
"""

from __future__ import annotations

import csv
import glob
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from ..nucleo import caminhos, cnj, paginacao, sigilo, tribunais
from ..nucleo.cnj import Numero
from ..nucleo.sistema import REINSTALAR
from .contexto import Contexto
from .modelos import (CANCELADO, CAUSA_FALHA, CAUSA_GRAVACAO, CAUSA_INESPERADO,
                      CAUSA_INTERROMPIDO, CAUSA_LOGIN, CAUSA_NAVEGADOR_OCUPADO,
                      CAUSA_PDF_ABERTO, CAUSA_PDF_INVALIDO, CAUSA_PORTAL, CAUSA_PORTAL_PAROU,
                      CAUSA_SESSAO, CAUSA_SIGILO_NO_ACERVO, ERRO, JA_BAIXADO, NAO_ENCONTRADO,
                      NAO_SUPORTADO, OK, SEM_ACESSO, SIGILOSO_SEM_SENHA, TENTAR_DE_NOVO,
                      Cancelado, CopiaAntigaPresa, LoginFalhou, NavegadorOcupado, OpcoesDownload,
                      PortalIndisponivel, ProcessoNaoEncontrado, ResultadoProcesso, ResumoLote,
                      SemAcesso, SessaoPerdida, SigilosoSemSenha, dica_de_grau)

log = logging.getLogger("download.motor")

# "causa" vai no FIM: quem lê o relatório pelo nome da coluna (o programa, o
# Excel, a skill do Claude) continua lendo os relatórios antigos e os novos.
# "grau" (1.1.0) veio depois dela, pelo mesmo motivo: "1g" ou "2g"; vazia no
# relatório de versão anterior, vale o que o número diz (cnj.grau_do_numero)
# ou, se ele não diz, 1º grau (_grau_da_linha).
COLUNAS = ["ordem", "processo", "tribunal", "sistema", "situacao", "paginas", "documentos",
           "arquivo", "sigiloso", "incompleto", "detalhe", "data_hora", "causa", "grau"]
MASCARA_SIGILOSO = "(processo sigiloso)"
SIGILO_ANTERIOR = "assim constava de download anterior"
DETALHE_MASCARA = ("processo em segredo de justiça; o número e os detalhes estão no relatório da "
                   "pasta de sigilosos")
RELATORIOS = ("relatorio.csv", "relatorio (atualizado).csv")
MAX_RELOGINS = 2                 # por processo
MAX_INDISPONIVEL_SEGUIDOS = 3    # processos seguidos com o portal fora: desiste do grupo
ESPERA_ENTRE_TENTATIVAS_S = 3.0  # cresce a cada tentativa (3 s, 6 s...), até 30 s
ESPERA_NAVEGADOR_S = 30.0        # navegador ocupado por outro download: tenta de novo a cada 30 s
# O "motivo" do evento navegador_ocupado: por que o navegador do portal não abre
MOTIVO_OUTRO_DOWNLOAD = "outro_download"       # outro download usa o perfil
MOTIVO_COPIA_ANTIGA = "copia_antiga_presa"     # a cópia antiga do perfil não pôde ser apagada

# Os arquivos de _controle que andam com o PDF do processo (para a pasta de
# sigilosos, de volta ao lote...): a capa em texto e em JSON e o registro do
# download (meta). As gravações (_controle/midias/<número>) vão à parte.
SUFIXOS_CONTROLE = ("_capa.txt", "_capa.json", "_meta.json")
FORMATO_META = "helestron.meta/1"
ORIGEM_DO_LOTE = "origem.txt"    # na pasta de sigilosos do lote: de que pasta de lote ela é
NOME_TRAVA = ".executando"       # em _controle: o lote está sendo baixado agora

JA_ESTAVA = "já estava na pasta (não baixei de novo)"
SEM_REGISTRO = "sem registro do download anterior: paginação não conferida"
# Na linha da rodada que não trocou o PDF que já estava na pasta (falha,
# item interrompido, grupo sem login): depois disto vem o que se sabia dele.
PDF_ANTERIOR = "o PDF anterior continua na pasta"
# O sigilo não pôde ir para o registro do download (_lembrar_sigilo): com a
# separação desligada, os autos vão para a pasta de sigilosos assim mesmo.
SEM_REGISTRO_DO_SIGILO = ("por segurança, mesmo com a separação dos sigilosos desligada: o "
                          "registro do sigilo não pôde ser gravado agora")
# Pedaços do detalhe que valem só para a rodada em que foram escritos: não
# são copiados quando o processo, já na pasta, é visto de novo.
_SO_DA_RODADA = (JA_ESTAVA, SEM_REGISTRO, "levado agora para a pasta de sigilosos",
                 "baixado de novo", PDF_ANTERIOR, "atenção:", "ATENÇÃO:",
                 SEM_REGISTRO_DO_SIGILO)

# Erro de conexão (o portal ou a rede fora), e não página lenta: só estes
# contam para MAX_INDISPONIVEL_SEGUIDOS. "Timeout" solto não entra - o
# 'locator.click: Timeout 30000ms exceeded' de uma tela que mudou não é
# portal fora do ar.
_RE_PORTAL_FORA = re.compile(
    r"net::ERR_(?:INTERNET_DISCONNECTED|NAME_NOT_RESOLVED|ADDRESS_UNREACHABLE|"
    r"CONNECTION_(?:REFUSED|TIMED_OUT|RESET|CLOSED|FAILED)|TIMED_OUT|NETWORK_CHANGED|"
    r"PROXY_CONNECTION_FAILED|TUNNEL_CONNECTION_FAILED)"
    r"|\b(?:Page|Frame)\.goto: Timeout"
    r"|\bAPIRequestContext\.\w+: Timeout"
    r"|\b(?:ETIMEDOUT|ECONNREFUSED|ECONNRESET|ENOTFOUND|EAI_AGAIN)\b")


def portal_fora(mensagem: str) -> bool:
    """O erro é de conexão com o portal (rede fora, portal fora do ar)?"""
    return bool(_RE_PORTAL_FORA.search(str(mensagem or "")))


def _explicar_erro(mensagem: str) -> str:
    """A frase do navegador para o erro técnico (sem o jsessionid da URL)."""
    try:
        from .navegador import explicar_erro
        return explicar_erro(mensagem)
    except Exception:              # instalação sem o navegador: a 1ª linha basta
        texto = str(mensagem or "").strip()
        return (texto.splitlines()[0] if texto else "erro desconhecido")[:200]


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
    """Um navegador com perfil próprio por portal (%LOCALAPPDATA%): o do
    e-SAJ serve aos dois graus (o mesmo login); o eProc do 2º grau, outra
    instalação, tem o seu (perfis/eproc2g-TJAL, Tribunal.perfil)."""
    from .navegador import Navegador
    sistema = tribunal.sistema
    escolha = opcoes.navegador or "auto"
    executavel = None
    if escolha.lower() not in ("auto", "chrome", "msedge", "chromium"):
        # caminho de um navegador (ex.: Chrome portátil) escrito no config.ini
        executavel, escolha = (escolha if Path(escolha).is_file() else None), "auto"
    # O getattr protege os dublês de Tribunal (sem 'perfil'): o nome de sempre.
    perfil = getattr(tribunal, "perfil", "") or f"{sistema}-{tribunal.sigla}"
    return Navegador(
        caminhos.PERFIS / perfil,
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
        dominios=hosts_do_tribunal(tribunal),
    )


def hosts_do_tribunal(tribunal) -> tuple[str, ...]:
    """Os hosts dos endereços do tribunal (catálogo e correções do usuário,
    dos dois sistemas): os cookies que a sessão guardada pode levar."""
    from urllib.parse import urlsplit
    hosts = set()
    for t in (tribunal, getattr(tribunal, "alternativo", None)):
        for valor in (getattr(t, "urls", None) or {}).values():
            for url in ([valor] if isinstance(valor, str) else (valor or [])):
                try:
                    host = urlsplit(str(url)).hostname
                except ValueError:
                    host = None
                if host:
                    hosts.add(host.lower())
    return tuple(sorted(hosts))


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


def relativo(caminho, raiz) -> str:
    """O caminho relativo à raiz (o acervo), como o sistema o escreve; fora
    dela (ou sem ela), a pasta e o nome."""
    p = Path(caminho)
    try:
        partes = p.relative_to(Path(raiz)).parts if raiz is not None else (p.parent.name, p.name)
    except (ValueError, TypeError):
        partes = (p.parent.name, p.name)
    partes = [q for q in partes if q]
    return str(Path(*partes)) if partes else p.name


_relativo = relativo


def _juntar(*partes: str) -> str:
    return "; ".join(p for p in partes if p)


def _do_grau(grau) -> dict:
    """{"grau": "2g"} no 2º grau; {} no 1º - os eventos, as consultas e o
    registro do 1º grau ficam como eram (ausente = 1º grau)."""
    return {"grau": "2g"} if grau == "2g" else {}


def nome_do_portal(tribunal) -> str:
    """'e-SAJ do TJAL'; no 2º grau, 'e-SAJ do TJAL (2º grau)': o nome do
    portal nas frases ("Entrando no ...", "Login no ... falhou")."""
    sufixo = " (2º grau)" if getattr(tribunal, "grau", "1g") == "2g" else ""
    return f"{tribunal.nome_sistema} do {tribunal.sigla}{sufixo}"


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
    """Leva o PDF, a capa (texto e JSON), o registro do download (meta) e as
    gravações dos autos 'nome' (a chave dos autos: cnj.nome_dos_autos - no
    1º grau, Numero.nome_arquivo; no 2º, com " (2G)") de uma pasta de lote
    (ou da área provisória) para outra. O PDF vai por ÚLTIMO: onde ele está,
    o resto já chegou. 'manter_destino': o que já está no destino (a cópia
    recém-baixada) não é trocado pela cópia antiga.

    Devolve (onde o PDF ficou, problemas com a capa e as gravações, erro do
    PDF). Sem PDF na origem, o primeiro item é None e o erro também.
    """
    problemas: list[str] = []
    pares = [(origem_dir / "_controle" / f"{nome}{sufixo}", alvo_dir / "_controle" / f"{nome}{sufixo}")
             for sufixo in SUFIXOS_CONTROLE]
    pares.append((origem_dir / "_controle" / "midias" / nome,
                  alvo_dir / "_controle" / "midias" / nome))
    for origem, destino in pares:
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
    """O texto integral dos autos do processo 'nome' (Numero.nome_arquivo) em
    <acervo>/_ia/texto não fica para trás: o dos dois graus ("<nome>.txt",
    "<nome> (2G).txt") e o dos incidentes dele ("<nome>-01.txt",
    "<nome>-50000 (2G).txt"), que herdam o sigilo - estejam onde estiverem os
    PDFs (numa subpasta do lote, num lote que já saiu do acervo): a varredura
    do acervo não olha _ia, e o texto ficaria lá até o próximo preparo."""
    if acervo is None:
        return
    pasta = Path(acervo) / "_ia" / "texto"
    chaves = frozenset({nome})
    try:
        textos = [p for p in pasta.glob("*.txt")
                  if sigilo.contem(chaves, chave_do_nome(p.name))]
    except OSError as erro:
        log.warning("não consegui ler %s (%s)", pasta, erro)
        return
    for texto in textos:
        try:
            _apagar(texto)
        except OSError as erro:
            log.warning("não consegui apagar %s (%s)", texto, erro)


# Pastas que a varredura por nome de arquivo não percorre: o cache da IA (o
# texto é apagado à parte) e a habilidade do Claude. As pastas _controle dos
# lotes só contam pela capa e pelas gravações, que andam com os autos.
_FORA_DA_VARREDURA = {"_ia", ".claude"}
PASTA_PRODUTOS = "Produtos"


def chave_do_nome(nome: str) -> str | None:
    """O processo (Numero.nome_arquivo) que dá nome ao arquivo ou à pasta:
    "<número>.pdf", "<número>-01.pdf" (o incidente), "<número> - minuta.docx",
    "Minuta <número>.docx". None se o nome não trouxer número."""
    try:
        return cnj.ler_nome_arquivo(str(nome)).nome_arquivo
    except cnj.NumeroInvalido:
        return None


def _normal(caminho) -> str:
    return os.path.normcase(os.path.abspath(caminho))


def _dentro_de(caminho: str, pasta: str) -> bool:
    """'caminho' é 'pasta' ou está dentro dela (os dois já _normal)."""
    return caminho == pasta or caminho.startswith(pasta.rstrip(os.sep) + os.sep)


def _recorte(acervo: Path, raiz_sigilosos: Path):
    """O recorte do compartilhamento (pastas do programa e dos sigilosos
    dentro do acervo, links para fora dele); None se indisponível."""
    try:
        from ..compartilhar.mcp_servidor import Recorte
        return Recorte(Path(acervo), Path(raiz_sigilosos))
    except Exception:              # instalação sem o compartilhamento
        return None


def _varrer(acervo: Path, raiz_sigilosos: Path, com_controle: bool = False):
    """(caminho, é pasta) de cada arquivo do acervo - e, com 'com_controle',
    também das pastas _controle dos lotes (a capa) e das pastas das gravações
    em _controle/midias -, fora o cache da IA, a pasta dos sigilosos e as do
    programa (se estiverem dentro do acervo) e o que só está lá por um link."""
    acervo = Path(acervo)
    if not acervo.is_dir():
        return
    sigilosos = _normal(raiz_sigilosos)
    recorte = _recorte(acervo, raiz_sigilosos)
    for pasta, subpastas, arquivos in os.walk(acervo):
        manter = []
        for d in subpastas:
            caminho = Path(pasta) / d
            if d.lower() in _FORA_DA_VARREDURA or _dentro_de(_normal(caminho), sigilosos):
                continue
            if recorte is not None and recorte.pasta_excluida(caminho):
                continue                    # pasta do programa dentro do acervo
            if d.lower() == "_controle" and not com_controle:
                continue
            manter.append(d)
        subpastas[:] = manter
        if com_controle and Path(pasta).name.lower() == "midias" \
                and Path(pasta).parent.name.lower() == "_controle":
            for d in subpastas:
                yield Path(pasta) / d, True
            subpastas[:] = []               # o conteúdo anda com a pasta
            continue
        for nome in arquivos:
            if nome.startswith("~$") or nome.endswith((".parcial", ".tmp")):
                continue
            caminho = Path(pasta) / nome
            if recorte is not None and not recorte.aceita(caminho):
                continue
            yield caminho, False


def _ler_relatorio(arquivo: Path) -> list[dict] | None:
    """As linhas de um relatorio.csv de lote (None: não existe ou ilegível)."""
    try:
        dados = arquivo.read_bytes()
    except OSError:
        return None
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:       # salvo pelo Excel, em ANSI
        texto = dados.decode("cp1252", errors="replace")
    try:
        return [{c: (linha.get(c) or "") for c in COLUNAS}
                for linha in csv.DictReader(texto.splitlines(), delimiter=";")
                if any((v or "").strip() for v in linha.values() if isinstance(v, str))]
    except (csv.Error, ValueError, AttributeError):
        return None


def _gravar_relatorio(arquivo: Path, linhas: list[list]) -> None:
    """Grava o relatório como o motor grava (UTF-8 com BOM, ';'), de uma vez."""
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    w.writerow(COLUNAS)
    w.writerows(linhas)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    try:
        tmp.write_bytes(("﻿" + saida.getvalue()).encode("utf-8"))
        os.replace(tmp, arquivo)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def processos_no_acervo(acervo, raiz_sigilosos,
                        lotes: list[Path] | None = None) -> dict[str, list[Path]]:
    """Os processos (Numero.nome_arquivo) que têm alguma coisa no acervo, com
    os arquivos deles: um arquivo com o número no nome (os autos, a capa, a
    transcrição, a minuta em Produtos/ ou noutra pasta), a pasta das
    gravações ou uma linha no relatório de um lote (sem arquivo). É o que o
    preparo confere contra a regra do sigilo, numa varredura só."""
    achados: dict[str, list[Path]] = {}
    for caminho, _pasta in _varrer(Path(acervo), Path(raiz_sigilosos), com_controle=True):
        chave = chave_do_nome(caminho.name)
        if chave:
            achados.setdefault(chave, []).append(caminho)
    for lote in lotes or []:
        for nome in RELATORIOS:
            for linha in _ler_relatorio(lote / "_controle" / nome) or []:
                chave = _chave_relatorio(linha.get("processo"))
                if chave:
                    achados.setdefault(chave, [])
    return achados


def destino_na_pasta_dos_sigilosos(acervo, raiz_sigilosos, arquivo) -> Path:
    """Para onde vai, na pasta dos sigilosos, um arquivo do acervo: o mesmo
    caminho relativo, sem o "Processos" do começo (os lotes ficam na raiz
    dela, como o download grava): Processos/<lote>/<x> -> <sigilosos>/<lote>/<x>,
    Transcricoes/<x> -> <sigilosos>/Transcricoes/<x>, Produtos/<x> ->
    <sigilosos>/Produtos/<x>."""
    try:
        partes = Path(arquivo).relative_to(Path(acervo)).parts
    except ValueError:
        partes = (Path(arquivo).name,)
    if len(partes) > 1 and partes[0].lower() == "processos":
        partes = partes[1:]
    return Path(raiz_sigilosos).joinpath(*partes)


def _motivo_do_erro(erro: BaseException | None) -> str:
    """Por que o arquivo não pôde sair, numa frase curta."""
    if isinstance(erro, PermissionError):
        return "está aberto em outro programa?"
    if isinstance(erro, FileNotFoundError):
        return "a pasta dos sigilosos não está acessível"
    if isinstance(erro, OSError):
        return f"a pasta dos sigilosos não está acessível: {erro.strerror or erro}"
    if erro is None:
        return "está aberto em outro programa?"
    return str(erro)[:160]


def bloqueia(arquivo) -> bool:
    """O arquivo de processo sigiloso preso no acervo trava o compartilhamento?
    Só os autos (PDF, fora de Produtos/): a minuta do usuário, o produto da
    IA, a transcrição e o resto não travam - o índice, o conector, o pacote e
    a nuvem já os deixam de fora, e o aviso diz qual arquivo mover."""
    p = Path(arquivo)
    if p.suffix.lower() != ".pdf":
        return False
    return PASTA_PRODUTOS.lower() not in {q.lower() for q in p.parts[:-1]}


@dataclass
class Retirada:
    """O que retirar_do_acervo fez com as cópias de um processo sigiloso."""

    autos: dict[Path, Path] = field(default_factory=dict)   # PDF no lote -> PDF levado
    transcricoes: int = 0                                     # arquivos de transcrição levados
    autos_presos: list[Path] = field(default_factory=list)   # PDFs que não puderam sair
    transcricoes_presas: list[Path] = field(default_factory=list)
    gravando: bool = False         # a audiência dele está sendo gravada: a transcrição ficou
    # O resto do processo no acervo (a minuta em Produtos/, a do usuário noutra
    # pasta, os autos numa subpasta do lote): origem -> destino
    outros: dict[Path, Path] = field(default_factory=dict)
    outros_presos: list[Path] = field(default_factory=list)
    # Relatórios de lote do acervo que tinham o número e foram mascarados
    relatorios: list[Path] = field(default_factory=list)
    # O relatório completo (na pasta dos sigilosos, fora do acervo) que não
    # pôde ser regravado -> os relatórios do lote no acervo que, por isso,
    # continuam com o número. Não entra em 'presos': não ficou no acervo.
    completos_presos: dict[Path, list[Path]] = field(default_factory=dict)
    motivos: dict[Path, str] = field(default_factory=dict)  # arquivo preso -> por quê

    @property
    def presos(self) -> list[Path]:
        """Tudo o que ficou no acervo."""
        return list(dict.fromkeys(self.autos_presos + self.transcricoes_presas
                                  + self.outros_presos))

    @property
    def bloqueiam(self) -> list[Path]:
        """O que ficou e trava o compartilhamento: os autos (bloqueia())."""
        return [p for p in self.presos if bloqueia(p)]

    @property
    def avisam(self) -> list[Path]:
        """O que ficou sem travar o compartilhamento (avisado ao usuário)."""
        return [p for p in self.presos if not bloqueia(p)]

    @property
    def levou(self) -> bool:
        return bool(self.autos or self.transcricoes or self.outros)

    def _preso(self, lista: list[Path], arquivo: Path, erro: BaseException | None) -> None:
        if arquivo not in lista:
            lista.append(arquivo)
        self.motivos[arquivo] = _motivo_do_erro(erro)


def _incidentes_no_acervo(nome: str, lotes: list[Path], cfg) -> list[str]:
    """Os incidentes ("<nome>-NN") do processo 'nome' que têm autos num lote
    ou transcrição no acervo: herdam o sigilo do principal e saem com ele."""
    if sigilo.principal(nome) is not None:          # 'nome' já é um incidente
        return []
    pastas = list(lotes)
    try:
        if cfg is not None:
            pastas += [Path(cfg.pasta_transcricoes), Path(cfg.pasta_transcricoes) / "_audio"]
    except Exception:
        pass
    achados: set[str] = set()
    padrao = f"{glob.escape(nome)}-*"
    for pasta in pastas:
        try:
            candidatos = list(Path(pasta).glob(padrao))
        except OSError:
            continue
        for p in candidatos:
            chave = chave_do_nome(p.name)
            if chave and chave != nome and sigilo.principal(chave) == nome:
                achados.add(chave)
    return sorted(achados)


def _nome_livre(alvo: Path) -> Path:
    """'alvo', ou '<nome> (2).<ext>' se já existir: nada na pasta dos
    sigilosos é sobrescrito (e o nome continua com o número do processo)."""
    if not alvo.exists():
        return alvo
    chave = chave_do_nome(alvo.name)
    n = 2
    while True:
        candidato = alvo.with_name(f"{alvo.stem} ({n}){alvo.suffix}")
        if chave_do_nome(candidato.name) != chave:      # "<número>" sem extensão
            candidato = alvo.with_name(f"{alvo.name} ({n})")
        if not candidato.exists():
            return candidato
        n += 1


def _levar_outros(ret: Retirada, acervo: Path, raiz_sigilosos: Path, nomes: set[str],
                  arquivos: list[Path] | None = None, com_transcricoes: bool = True) -> None:
    """Leva para a pasta dos sigilosos (o mesmo caminho relativo, com nome
    livre) o que ainda estiver no acervo com o número de um dos processos
    'nomes' - ou de um incidente deles: a minuta em Produtos/, a do usuário
    noutra pasta, os autos numa subpasta do lote, a capa e as gravações sem
    os autos. 'arquivos': os já achados (sem eles, o acervo é varrido).
    Sem 'com_transcricoes', a pasta das transcrições fica (sem a
    configuração, não há como saber se a audiência está sendo gravada)."""
    ja = set(ret.presos)
    chaves = frozenset(nomes)
    if arquivos is None:
        arquivos = [c for c, _ in _varrer(acervo, raiz_sigilosos, com_controle=True)]
    for caminho in arquivos:
        chave = chave_do_nome(caminho.name)
        if not sigilo.contem(chaves, chave) or caminho in ja or not caminho.exists():
            continue
        if not com_transcricoes:
            try:
                partes = {q.lower() for q in caminho.relative_to(acervo).parts[:-1]}
            except ValueError:
                partes = set()
            if partes & {"_audio", "transcricoes"}:
                continue
        alvo = destino_na_pasta_dos_sigilosos(acervo, raiz_sigilosos, caminho)
        if not caminho.is_dir():
            alvo = _nome_livre(alvo)
        try:
            _mover(caminho, alvo, manter_destino=True)
        except Exception as erro:
            log.warning("    não consegui levar %s para a pasta de sigilosos (%s)", caminho, erro)
            ret._preso(ret.autos_presos if bloqueia(caminho) else ret.outros_presos,
                       caminho, erro)
            continue
        ret.outros[caminho] = alvo
        log.info("    arquivo do sigiloso levado para a pasta de sigilosos: %s -> %s",
                 caminho, alvo)


def _sigilosos_do_lote(lote: Path, raiz_sigilosos: Path, alvos: dict | None = None) -> Path:
    """A pasta de sigilosos de um lote: a que o motor em curso escolheu para o
    lote dele ('alvos'), ou <sigilosos>/<nome do lote> (os lotes do acervo)."""
    for origem, alvo in (alvos or {}).items():
        if _mesma_pasta(origem, lote):
            return Path(alvo)
    return Path(raiz_sigilosos) / Path(lote).name


def _mascarar_relatorios(ret: Retirada, lotes: list[Path], raiz_sigilosos: Path,
                         nomes: set[str], alvos: dict | None = None) -> None:
    """Tira o número dos processos 'nomes' dos relatórios dos lotes do acervo
    (a linha fica como a do download de um sigiloso: "(processo sigiloso)")
    e guarda a linha completa no relatório do lote na pasta dos sigilosos.
    Relatório aberto no Excel fica como está, entre os avisos."""
    chaves = frozenset(nomes)
    for lote in lotes:
        for nome_rel in RELATORIOS:
            arquivo = lote / "_controle" / nome_rel
            linhas = _ler_relatorio(arquivo)
            if not linhas:
                continue
            dele = [l for l in linhas if sigilo.contem(chaves, _chave_relatorio(l.get("processo")))]
            if not dele:
                continue
            completo_arq = _sigilosos_do_lote(lote, raiz_sigilosos, alvos) / "_controle" / \
                "relatorio.csv"
            completo = _ler_relatorio(completo_arq) or []
            por_ordem = {l.get("ordem"): l for l in completo
                         if _chave_relatorio(l.get("processo")) is not None}
            # As linhas se casam pela chave dos AUTOS (processo e grau): com A
            # no 1º e no 2º grau no mesmo lote, a linha do 2º grau que só o
            # relatório completo tem não some por já se ter visto a do 1º.
            novo_completo, vistos = [], set()
            for l in linhas:
                chave = _chave_relatorio(l.get("processo"))
                if chave is None and (l.get("sigiloso") or "").strip().lower() == "sim":
                    real = por_ordem.get(l.get("ordem"))
                    if real is not None:
                        # A linha mascarada diz "sim", e isso vence o completo
                        # desatualizado (preso no Excel na rodada que apurou
                        # o sigilo, ainda com a linha de quando era público).
                        l, chave = dict(real, sigiloso="sim"), \
                            _chave_relatorio(real.get("processo"))
                if chave is not None and sigilo.contem(chaves, chave):
                    l = dict(l, sigiloso="sim")
                    if l.get("arquivo") and "(na pasta de sigilosos)" not in l["arquivo"]:
                        l["arquivo"] = f"{l['arquivo']} (na pasta de sigilosos)"
                if chave is not None:
                    vistos.add(_chave_da_linha(l))
                novo_completo.append(l)
            for l in completo:              # o que só o completo tinha
                chave = _chave_da_linha(l)
                if chave is not None and chave not in vistos:
                    vistos.add(chave)
                    novo_completo.append(l)
            try:
                _gravar_relatorio(completo_arq, [_valores_da_linha(l) for l in novo_completo])
            except OSError as erro:
                # Sem a linha completa guardada, o número não sai do relatório
                log.warning("não consegui gravar o relatório da pasta de sigilosos (%s)", erro)
                ret.completos_presos.setdefault(completo_arq, []).append(arquivo)
                ret.motivos[completo_arq] = _motivo_do_erro(erro)
                continue
            mascaradas = []
            for l in linhas:
                if sigilo.contem(chaves, _chave_relatorio(l.get("processo"))):
                    mascaradas.append(_Lote._linha_antiga(dict(l, sigiloso="sim"),
                                                          l.get("ordem", ""), True))
                else:
                    mascaradas.append(_valores_da_linha(l))
            try:
                _gravar_relatorio(arquivo, mascaradas)
            except OSError as erro:
                log.warning("não consegui tirar o número do sigiloso de %s (%s)", arquivo, erro)
                motivo = ("está aberto no Excel?" if isinstance(erro, PermissionError)
                          else _motivo_do_erro(erro))
                if arquivo not in ret.outros_presos:
                    ret.outros_presos.append(arquivo)
                ret.motivos[arquivo] = motivo
                continue
            ret.relatorios.append(arquivo)
            log.info("    número do sigiloso tirado do relatório do lote %s.", lote.name)


def _retirar_autos_do_lote(ret: Retirada, lote: Path, autos: str, raiz_sigilosos: Path,
                           alvos: dict | None) -> None:
    """Leva os autos 'autos' (a chave dos autos) de um lote do acervo, com a
    capa, o registro do download e as gravações, para a pasta de sigilosos
    do lote; o que não puder sair fica na Retirada, com o motivo."""
    controle = lote / "_controle"
    tem_pdf = (lote / f"{autos}.pdf").exists()
    # a capa (texto e JSON) traz as partes e o registro do download, o
    # número: andam com os autos e, se ficarem, também são aviso
    restos = [controle / f"{autos}{sufixo}" for sufixo in SUFIXOS_CONTROLE]
    restos.append(controle / "midias" / autos)
    if not (tem_pdf or any(p.exists() for p in restos)):
        return
    novo, _problemas, erro = _levar_arquivos(
        lote, _sigilosos_do_lote(lote, raiz_sigilosos, alvos), autos, manter_destino=True)
    for resto in restos:
        if resto.exists():
            ret._preso(ret.outros_presos, resto, None)
    if not tem_pdf:
        return
    if erro is not None or novo is None:
        ret._preso(ret.autos_presos, lote / f"{autos}.pdf", erro)
        return
    ret.autos[lote / f"{autos}.pdf"] = novo
    log.info("    cópia do sigiloso em %s levada para a pasta de sigilosos.", lote.name)


def retirar_do_acervo(cfg, numero, *, raiz_sigilosos=None, lotes: list[Path] | None = None,
                      acervo=None, arquivos: list[Path] | None = None,
                      alvos: dict | None = None) -> Retirada:
    """Tira do acervo toda cópia de um processo sigiloso - e dos incidentes
    dele, que herdam o sigilo: os autos de cada lote (Processos/<lote>/, os
    dos dois graus, com capa e gravações) vão para <sigilosos>/<lote>/ - o
    que já estiver lá vence -, as transcrições (com a gravação e o diário) para
    <sigilosos>/Transcricoes, o resto com o número dele no nome (a minuta em
    Produtos/, a do usuário noutra pasta, os autos numa subpasta do lote)
    para o mesmo caminho dentro da pasta dos sigilosos, o número dele sai dos
    relatórios dos lotes (a linha completa vai para o relatório da pasta dos
    sigilosos) e o texto dele em _ia/texto é apagado. O que não puder sair
    (arquivo aberto, audiência sendo gravada) fica na Retirada, com o motivo:
    os autos (bloqueia()) travam o compartilhamento até sair; o resto vira
    aviso.

    'lotes' e 'acervo' (padrão: os da configuração) servem ao motor, que
    também conhece o lote em curso; 'arquivos', ao preparo, que já varreu o
    acervo (processos_no_acervo). 'alvos' (lote -> pasta de sigilosos dele):
    o lote em curso fora do acervo tem pasta de sigilosos de nome próprio
    (pasta_sigilosos_do_lote); os demais vão para <sigilosos>/<nome do lote>.
    """
    nome = numero.nome_arquivo if hasattr(numero, "nome_arquivo") else \
        cnj.ler_nome_arquivo(str(numero)).nome_arquivo
    raiz_sigilosos = Path(raiz_sigilosos if raiz_sigilosos is not None else cfg.pasta_sigilosos)
    if lotes is None:
        lotes = _lotes_do_acervo(getattr(cfg, "pasta_processos", None), raiz_sigilosos)
    if acervo is None:
        acervo = getattr(cfg, "pasta_acervo", None)
    ret = Retirada()
    nomes = [nome] + _incidentes_no_acervo(nome, lotes, cfg)
    for um in nomes:
        # O sigilo é do processo, nos dois graus: saem os autos do 1º grau
        # ("<um>.pdf") e os do 2º ("<um> (2G).pdf"), cada um com a capa, o
        # registro do download e as gravações dele.
        for autos in (um, um + cnj.SUFIXO_2G):
            for lote in lotes:
                _retirar_autos_do_lote(ret, lote, autos, raiz_sigilosos, alvos)
        if cfg is not None:
            levados, presas, gravando = _levar_transcricoes_do_acervo(cfg, um)
            ret.transcricoes += levados
            ret.gravando = ret.gravando or gravando
            for p in presas:
                ret._preso(ret.transcricoes_presas, p, None)
                if gravando:
                    ret.motivos[p] = "a audiência está sendo gravada agora"
        _apagar_texto_da_ia(acervo, um)
    if acervo is not None and Path(acervo).is_dir():
        _levar_outros(ret, Path(acervo), raiz_sigilosos, set(nomes), arquivos,
                      com_transcricoes=cfg is not None)
        _mascarar_relatorios(ret, list(lotes), raiz_sigilosos, set(nomes), alvos)
    return ret


def _chave_relatorio(texto) -> str | None:
    """O processo de uma linha do relatório ("0700001-..."; o dependente
    "-01" conta), ou None (linha mascarada, editada à mão)."""
    try:
        return cnj.ler_nome_arquivo(str(texto or "").strip()).nome_arquivo
    except Exception:
        return None


def _numero_da_linha(linha: dict) -> Numero | None:
    try:
        return cnj.ler_nome_arquivo(str(linha.get("processo") or "").strip())
    except Exception:
        return None


def _grau_da_linha(linha: dict) -> str:
    """O grau dos autos de uma linha do relatório: o da coluna "grau" ou, se
    ela está vazia (relatório de versão anterior à 1.1.0, que nem a tinha), o
    que o número diz - o HC de órgão 0000 e o /50000 só têm autos no 2º grau
    (a 1.0.2 os procurava no 1º e gravava a linha sem grau) - e, se ele não
    diz, 1º grau. "" só na linha sem número legível (a mascarada) e sem grau."""
    grau = cnj.normalizar_grau(linha.get("grau"))
    if grau:
        return grau
    n = _numero_da_linha(linha)
    return "" if n is None else (cnj.grau_do_numero(n) or "1g")


def _chave_da_linha(linha: dict) -> str | None:
    """A chave dos AUTOS de uma linha do relatório (o processo da linha e o
    grau dela: cnj.nome_dos_autos), ou None (linha mascarada, editada à mão).
    É por ela que as linhas se casam: A no 1º grau e A no 2º são duas linhas."""
    n = _numero_da_linha(linha)
    return None if n is None else cnj.nome_dos_autos(n, _grau_da_linha(linha))


def _valores_da_linha(linha: dict) -> list[str]:
    """Os valores da linha na ordem de COLUNAS, com o grau escrito (a linha
    de relatório anterior à coluna "grau" a ganha, pelo que o número diz)."""
    return [linha.get(c, "") or "" for c in COLUNAS[:-1]] + [_grau_da_linha(linha)]


def _sim(valor) -> bool:
    return (valor or "").strip().lower() == "sim"


def _inteiro(valor, padrao: int = 0) -> int:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return padrao


# ------------------------------------------------------- relatório do lote
def ler_csv_do_controle(controle: Path) -> list[dict]:
    """As linhas do relatório de uma pasta _controle (o mais recente dos dois:
    o "(atualizado)" é o gravado quando o Excel prendia o outro). Relatório de
    versão anterior, sem as colunas novas, vem com elas vazias."""
    candidatos = []
    for nome in RELATORIOS:
        try:
            candidatos.append(((Path(controle) / nome).stat().st_mtime, Path(controle) / nome))
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


def _mesclar_relatorios(do_lote: list[dict], completo: list[dict]) -> list[tuple[str | None, dict]]:
    """[(chave dos autos ou None, linha)] do relatório do lote, na ordem
    dele. A linha mascarada ("(processo sigiloso)") é trocada pela do
    relatório completo da pasta de sigilosos, de mesma ordem; sem ele, fica
    como está. O que só o completo tem vem no fim. A chave é a dos AUTOS
    (_chave_da_linha: o processo e o grau da linha): o mesmo número no 1º e
    no 2º grau são duas linhas."""
    por_ordem = {linha.get("ordem"): linha for linha in completo
                 if _chave_relatorio(linha.get("processo")) is not None}
    saida: list[tuple[str | None, dict]] = []
    vistos: set[str] = set()
    for linha in do_lote or completo:
        chave = _chave_da_linha(linha)
        if chave is None and _sim(linha.get("sigiloso")):
            real = por_ordem.get(linha.get("ordem"))
            if real is not None:
                # A linha mascarada diz "sim", e isso vence o completo
                # desatualizado (preso no Excel na rodada que apurou o
                # sigilo, ainda com a linha de quando era público): o número
                # não volta ao relatório do acervo por ele.
                linha, chave = dict(real, sigiloso="sim"), _chave_da_linha(real)
        if chave is not None:
            if chave in vistos:
                continue
            vistos.add(chave)
        saida.append((chave, linha))
    for linha in completo:              # o que só o completo ainda tem
        chave = _chave_da_linha(linha)
        if chave is not None and chave not in vistos:
            vistos.add(chave)
            saida.append((chave, linha))
    return saida


def ler_relatorio_do_lote(destino, raiz_sigilosos, pasta_processos=None) -> list[tuple[str | None, dict]]:
    """O relatório inteiro de uma pasta de lote: as linhas do relatório do
    lote, com as dos sigilosos tiradas do relatório completo da pasta de
    sigilosos dele. [(chave dos autos ou None, linha)], na ordem do lote - a
    chave dos autos (cnj.nome_dos_autos) é, no 1º grau, a do processo; no 2º,
    com " (2G)"; a linha sem grau (versão anterior) vale pelo que o número
    diz (_grau_da_linha). É o que o motor mescla a cada rodada e o que
    "baixar --retomar" consulta."""
    pasta = pasta_sigilosos_do_lote(raiz_sigilosos, destino, pasta_processos)
    return _mesclar_relatorios(ler_csv_do_controle(Path(destino) / "_controle"),
                               ler_csv_do_controle(pasta / "_controle"))


# ------------------------------------------------ pasta de sigilosos do lote
def _chave_do_caminho(p) -> str:
    try:
        return os.path.normcase(str(Path(p).resolve()))
    except (OSError, RuntimeError):
        return os.path.normcase(os.path.abspath(str(p)))


def _origem_marcada(pasta: Path) -> str | None:
    """A pasta de lote de que esta pasta de sigilosos é (o origem.txt); None
    se ela não diz (não existe, ou é de versão anterior)."""
    try:
        texto = (Path(pasta) / "_controle" / ORIGEM_DO_LOTE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    return linhas[0] if linhas else None


def _nome_unico(destino: Path) -> str:
    """'<nome> (<8 hex do caminho>)': a pasta de sigilosos de um lote FORA da
    pasta Processos do acervo, onde dois lotes podem ter o mesmo nome."""
    marca = hashlib.sha1(_chave_do_caminho(destino).encode("utf-8")).hexdigest()[:8]
    return f"{Path(destino).name or 'Lote'} ({marca})"


def _no_lugar_dos_lotes(destino: Path, pasta_processos) -> bool:
    if pasta_processos is not None:
        return _mesma_pasta(Path(destino).parent, pasta_processos)
    return Path(destino).parent.name.lower() == "processos"


def _legado_do_lote(pasta: Path, destino: Path) -> bool:
    """A pasta de sigilosos <nome> sem origem.txt (versão anterior) é deste
    lote? Só se o relatório do lote tem linha mascarada e todo processo dele
    está no relatório completo dela - o lote que só tem o nome igual (outro
    caso, noutra pasta) não herda os sigilosos de ninguém."""
    do_lote = ler_csv_do_controle(Path(destino) / "_controle")
    completo = ler_csv_do_controle(Path(pasta) / "_controle")
    if not do_lote or not completo:
        return False
    if not any(_chave_relatorio(l.get("processo")) is None and _sim(l.get("sigiloso"))
               for l in do_lote):
        return False
    chaves = {_chave_relatorio(l.get("processo")) for l in do_lote} - {None}
    do_completo = {_chave_relatorio(l.get("processo")) for l in completo} - {None}
    return chaves <= do_completo


def pasta_sigilosos_do_lote(raiz_sigilosos, destino, pasta_processos=None) -> Path:
    """A pasta de sigilosos de um lote, FORA do acervo.

    O lote de Processos/<nome> (a janela e o padrão da linha de comando, de
    nomes únicos) usa <sigilosos>/<nome>, como sempre - é o que o manual e o
    resto do programa esperam. O lote noutra pasta (``--destino``) usa
    <sigilosos>/<nome> (<marca do caminho>): dois lotes "autos" em pastas
    diferentes não dividem sigilosos nem relatório completo. A pasta guarda
    em _controle/origem.txt o lote de que é; uma <sigilosos>/<nome> de outro
    lote nunca é usada.
    """
    raiz = Path(raiz_sigilosos)
    destino = Path(destino)
    simples = raiz / (destino.name or "Lote")
    origem = _origem_marcada(simples)
    if origem is not None:
        if _chave_do_caminho(origem) == _chave_do_caminho(destino):
            return simples
        return raiz / _nome_unico(destino)
    if _no_lugar_dos_lotes(destino, pasta_processos):
        return simples
    if simples.is_dir() and _legado_do_lote(simples, destino):
        return simples
    return raiz / _nome_unico(destino)


def _marcar_origem(pasta: Path, destino: Path) -> None:
    """Grava em <pasta>/_controle/origem.txt de que lote é a pasta de sigilosos."""
    arquivo = Path(pasta) / "_controle" / ORIGEM_DO_LOTE
    if arquivo.exists():
        return
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        try:
            alvo = str(Path(destino).resolve())
        except (OSError, RuntimeError):
            alvo = os.path.abspath(str(destino))
        arquivo.write_text(alvo + "\n", encoding="utf-8")
    except OSError as erro:
        log.debug("origem da pasta de sigilosos não gravada (%s)", erro)


# --------------------------------------------- paginação e registro (meta)
def essencial_da_paginacao(m: dict | None) -> dict:
    """O essencial do manifesto de paginação (nucleo/paginacao.py) para o
    relatório e o JSON: o tipo de paginação, a última página/folha, as
    ausentes e a frase de resumo. {} se não houver manifesto."""
    if not paginacao.valido(m):
        return {}
    e: dict = {"sistema": m.get("sistema", ""), "paginacao": m.get("paginacao", ""),
               "formato": m.get("formato", paginacao.FORMATO), "resumo": paginacao.resumo(m)}
    if paginacao.grau(m) == paginacao.SEGUNDO_GRAU:
        # só no 2º grau (sem o campo, 1º grau: o JSON do 1º grau fica como era)
        e["grau"] = paginacao.SEGUNDO_GRAU
    if m.get("paginacao") == paginacao.FOLHAS:
        e.update(ultima=_inteiro(m.get("ultima")),
                 ausentes={str(k): str(v) for k, v in (m.get("ausentes") or {}).items()},
                 folhas_ausentes=paginacao.descrever_folhas(paginacao.ausentes(m)),
                 origem=m.get("origem", ""))
        return e
    docs = [d for d in (m.get("documentos") or []) if isinstance(d, dict)]
    partes = [p for p in (m.get("partes") or []) if isinstance(p, dict)]
    fins = [_inteiro(x.get("inicio")) + _inteiro(x.get("paginas")) - 1
            for x in docs + partes if _inteiro(x.get("paginas")) > 0]
    e.update(modo=m.get("modo", ""), ultima=max(fins) if fins else 0,
             ausentes=[{"evento": d.get("evento"), "rotulo": d.get("rotulo", "")}
                       for d in docs if d.get("situacao") == "ausente"],
             documentos=[{k: d.get(k) for k in ("evento", "rotulo", "descricao", "data", "origem",
                                                 "situacao", "inicio", "paginas") if k in d}
                         for d in docs])
    if partes:
        e["partes"] = [{"inicio": _inteiro(p.get("inicio")), "paginas": _inteiro(p.get("paginas"))}
                       for p in partes]
    return e


def _incompleto_do_manifesto(e: dict) -> str:
    """A coluna "incompleto" a partir do manifesto: as folhas com página de
    aviso (e-SAJ) ou os documentos que não vieram (eProc)."""
    if e.get("paginacao") == paginacao.FOLHAS:
        return e.get("folhas_ausentes", "")
    return ", ".join(f"ev. {a.get('evento')} {a.get('rotulo') or ''}".strip()
                     for a in e.get("ausentes") or [])


def arquivo_meta(pasta_do_pdf: Path, nome: str) -> Path:
    return Path(pasta_do_pdf) / "_controle" / f"{nome}_meta.json"


def ler_meta(pasta_do_pdf: Path, nome: str) -> dict | None:
    """O registro do download (_controle/<nome>_meta.json) ao lado do PDF."""
    try:
        dados = json.loads(arquivo_meta(pasta_do_pdf, nome).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) and dados.get("formato") == FORMATO_META else None


def gravar_meta(r: ResultadoProcesso) -> Path | None:
    """Grava ao lado do PDF de 'r' o registro do download - o que o relatório
    diria dele -, para a próxima rodada que o encontrar na pasta (JA_BAIXADO)
    não perder o sistema, as folhas ausentes e o detalhe. Nunca levanta."""
    if not r.arquivo:
        return None
    pdf = Path(r.arquivo)
    try:
        from .. import __version__
    except Exception:  # pragma: no cover - o pacote sempre tem versão
        __version__ = "?"
    dados = {"formato": FORMATO_META, "versao": __version__, "numero": r.numero,
             "sistema": r.sistema, "tribunal": r.tribunal, "paginas": r.paginas,
             "documentos": r.documentos, "incompleto": r.incompleto, "detalhe": r.detalhe,
             "paginacao": dict(r.paginacao or {}), "sigiloso": bool(r.sigiloso),
             "consultas": list(r.consultas or []),
             "baixado_em": datetime.now().isoformat(timespec="seconds")}
    if getattr(r, "grau", "1g") == "2g":
        dados["grau"] = "2g"        # só no 2º grau: o registro do 1º grau fica como era
    destino = arquivo_meta(pdf.parent, pdf.stem)
    try:
        from ..nucleo.sistema import gravar_atomico
        gravar_atomico(destino, json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8"))
        return destino
    except OSError as erro:
        log.warning("não consegui gravar o registro do download de %s (%s)", pdf.name, erro)
        return None


def _detalhe_de_antes(texto) -> str:
    """O detalhe de uma rodada anterior, sem o que só valia para ela."""
    partes = [p.strip() for p in str(texto or "").split("; ")]
    return "; ".join(p for p in partes if p and not p.startswith(_SO_DA_RODADA))


def _detalhe_do_pdf(linha: dict) -> str | None:
    """O detalhe do PDF que a linha do relatório registra: o da linha de um
    download que deu certo (OK, JA_BAIXADO) ou, na de uma rodada que não o
    trocou, o que vem depois de PDF_ANTERIOR. None se a linha não registra
    PDF nenhum (falha sem PDF de antes)."""
    detalhe = str(linha.get("detalhe") or "")
    if (linha.get("situacao") or "").strip().upper() in (OK, JA_BAIXADO):
        return detalhe
    if PDF_ANTERIOR in detalhe:
        return detalhe.split(PDF_ANTERIOR, 1)[1].lstrip("; ").strip()
    return None


# ------------------------------------------------------- trava do lote
class LoteEmAndamento(RuntimeError):
    """Outro download está usando esta pasta de lote agora."""


_TRAVAS_DESTE_PROCESSO: set[str] = set()
_TRAVA_DAS_TRAVAS = threading.Lock()
VALIDADE_TRAVA_S = 48 * 3600     # trava mais velha que isso é de um lote que morreu
TOLERANCIA_CRIACAO_S = 2.0       # relógios e arredondamentos ao comparar o início do processo


def processo_vivo(pid: int) -> bool:
    """O processo 'pid' ainda está rodando? (no Windows, sem os.kill, que lá
    ENCERRA o processo)"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":  # pragma: no cover - só no Windows
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)    # cópia própria: argtypes locais
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        alca = k32.OpenProcess(0x1000, False, pid)       # PROCESS_QUERY_LIMITED_INFORMATION
        if not alca:
            return ctypes.get_last_error() == 5          # acesso negado: existe (outro usuário)
        try:
            codigo = wintypes.DWORD()
            if not k32.GetExitCodeProcess(alca, ctypes.byref(codigo)):
                return True
            return codigo.value == 259                   # STILL_ACTIVE
        finally:
            k32.CloseHandle(alca)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def momento_de_criacao(pid: int) -> float | None:
    """Quando o processo 'pid' começou (segundos desde 1970), ou None se não
    der para saber. Distingue o download que gravou a trava de outro
    programa que recebeu o mesmo número depois (o Windows os reaproveita)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform == "win32":  # pragma: no cover - só no Windows
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)    # cópia própria: argtypes locais
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        alca = k32.OpenProcess(0x1000, False, pid)       # PROCESS_QUERY_LIMITED_INFORMATION
        if not alca:
            return None
        try:
            tempos = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(alca, *(ctypes.byref(t) for t in tempos)):
                return None
            criacao = (tempos[0].dwHighDateTime << 32) | tempos[0].dwLowDateTime
            return (criacao - 116444736000000000) / 1e7   # 100 ns desde 1601 -> desde 1970
        finally:
            k32.CloseHandle(alca)
    try:                         # Linux: /proc/<pid>/stat (início, em tiques desde o boot)
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
            campos = f.read().rsplit(")", 1)[1].split()
        with open("/proc/stat", encoding="ascii", errors="replace") as f:
            boot = next(int(l.split()[1]) for l in f if l.startswith("btime "))
        return boot + int(campos[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None


class TravaDoLote:
    """_controle/.executando: {pid, inicio} do download que usa a pasta do
    lote. Um segundo download na mesma pasta (a mesma relação rodada de novo
    enquanto a primeira ainda corre, depois de um "timeout" de quem a chamou)
    estragaria o relatório e brigaria pelos mesmos PDFs. Trava de processo
    que já morreu (luz, Ctrl+C forte) é desfeita sozinha."""

    def __init__(self, controle: Path):
        self.arquivo = Path(controle) / NOME_TRAVA
        self.chave = _chave_do_caminho(self.arquivo)
        self._minha = False

    def ler(self) -> dict | None:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return dados if isinstance(dados, dict) else None

    def ocupada_por(self) -> dict | None:
        """Os dados do download vivo que a segura; None se está livre."""
        with _TRAVA_DAS_TRAVAS:
            if self.chave in _TRAVAS_DESTE_PROCESSO and not self._minha:
                return {"pid": os.getpid(), "inicio": ""}
        dados = self.ler()
        if not dados:
            return None
        pid = _inteiro(dados.get("pid"))
        if pid == os.getpid() or not processo_vivo(pid):
            return None
        try:
            gravada = self.arquivo.stat().st_mtime
        except OSError:
            gravada = time.time()
        if time.time() - gravada > VALIDADE_TRAVA_S:
            return None
        # O número de um download que morreu (fechado à força, queda de
        # energia) pode ter ido para outro programa: este não segura a trava.
        criado = momento_de_criacao(pid)
        if criado is not None:
            registrado = dados.get("criado")
            if isinstance(registrado, (int, float)) and not isinstance(registrado, bool):
                if abs(criado - registrado) > TOLERANCIA_CRIACAO_S:
                    return None
            else:
                # Trava sem o momento em que o dono começou: ele começou
                # antes de gravá-la ("inicio" e a data do arquivo).
                antes = gravada
                try:
                    antes = min(antes, datetime.fromisoformat(str(dados.get("inicio"))).timestamp())
                except (TypeError, ValueError, OverflowError, OSError):
                    pass
                if criado > antes + TOLERANCIA_CRIACAO_S:
                    return None
        return dados

    def adquirir(self) -> None:
        dono = self.ocupada_por()
        if dono is not None:
            desde = str(dono.get("inicio") or "")
            quando = desde.replace("T", " ")[:16] if desde else ""
            raise LoteEmAndamento(
                f"outro download está usando esta pasta de lote agora (processo "
                f"{dono.get('pid')}" + (f", desde {quando}" if quando else "") + "). Espere-o "
                "terminar, ou feche-o, e tente de novo.")
        with _TRAVA_DAS_TRAVAS:
            _TRAVAS_DESTE_PROCESSO.add(self.chave)
        self._minha = True
        dados = {"pid": os.getpid(), "inicio": datetime.now().isoformat(timespec="seconds")}
        criado = momento_de_criacao(os.getpid())
        if criado is not None:
            dados["criado"] = round(criado, 2)
        try:
            from ..nucleo.sistema import gravar_atomico
            gravar_atomico(self.arquivo, json.dumps(dados).encode("utf-8"))
        except OSError as erro:     # a trava protege; sem ela, o lote roda assim mesmo
            log.debug("trava do lote não gravada (%s)", erro)

    def soltar(self) -> None:
        if not self._minha:
            return
        self._minha = False
        with _TRAVA_DAS_TRAVAS:
            _TRAVAS_DESTE_PROCESSO.discard(self.chave)
        dados = self.ler()
        if dados and _inteiro(dados.get("pid")) == os.getpid():
            try:
                self.arquivo.unlink()
            except OSError:
                pass


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
        # Processos/<lote>: <sigilosos>/<lote>; noutra pasta, um nome que dois
        # lotes de mesmo nome não dividem (pasta_sigilosos_do_lote).
        self.pasta_sigilosos = pasta_sigilosos_do_lote(
            self.raiz_sigilosos, self.destino, getattr(cfg, "pasta_processos", None))
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
        # Cópias de sigilosos que não puderam sair do acervo (arquivo preso):
        # os autos travam o compartilhamento; o resto (transcrição, minuta,
        # capa) fica nos avisos.
        self._sigilo_no_acervo: list[str] = []
        self._sigilo_avisos: list[str] = []
        self._sigilo_motivos: dict[str, str] = {}       # arquivo -> por que ficou
        # Sigilosos cujo sigilo não pôde ir para o registro do download
        # (_lembrar_sigilo): por segurança, vão para a pasta de sigilosos
        # mesmo com a separação desligada - lá, a regra única os vê pela pasta.
        self._sem_registro: set[str] = set()
        self._cfg_lida = None            # config.ini, quando quem chama não deu cfg
        self._nav = None                 # o navegador do grupo em curso
        # Uma vez sigiloso, sempre sigiloso: o que relatórios anteriores
        # deste lote já apuraram (a página nem sempre repete o aviso).
        self._sigilosos_sabidos = self._ler_sigilos_anteriores()
        # Principal -> o recurso interno cuja consulta, nesta rodada, abriu a
        # página dele em segredo de justiça (_principal_apurado): o porquê
        # que o item dele diz, se vier depois na relação.
        self._apurados_pelo_recurso: dict[str, str] = {}
        # Itens reabertos para o sistema alternativo: já contavam como feitos
        # e continuam contando, para a barra de progresso não andar para trás.
        self._reabertos: set[int] = set()
        # Grupo do sistema alternativo em curso: índice -> (situação,
        # detalhe, sistema) do sistema principal, para devolver o
        # "não encontrado" se o alternativo nem puder ser consultado.
        self._anteriores: dict[int, tuple[str, str, str]] = {}
        self._seguidos_fora = 0          # processos seguidos com o portal fora, no grupo
        self._itens_comecaram = False    # o grupo em curso já começou a baixar?
        self._trava = TravaDoLote(self.controle)

        self.itens: list[ResultadoProcesso] = []
        self.numeros: list[Numero] = []
        # O grau dos autos de cada item (a regra única, cnj.grau_do_processo:
        # o número; senão o grau do lote) e a chave dos autos dele
        # (cnj.nome_dos_autos: o nome do PDF, da capa, do registro e da linha
        # do relatório), na ordem dos itens.
        self.graus: list[str] = []
        self.autos: list[str] = []
        grau_do_lote = getattr(opcoes, "grau", "1g")
        vistos: set[str] = set()
        for n in numeros:
            # num lote, o grau é função do número: a deduplicação continua
            # pelo número (e o /50000 não é o principal)
            k = cnj.chave(n)
            if k in vistos:
                log.info("%s aparece mais de uma vez na relação; baixo uma vez só.", n.formatado)
                continue
            vistos.add(k)
            t = tribunais.por_numero(n)
            grau = cnj.grau_do_processo(n, grau_do_lote)
            self.numeros.append(n)
            self.graus.append(grau)
            self.autos.append(cnj.nome_dos_autos(n, grau))
            self.itens.append(ResultadoProcesso(
                ordem=len(self.itens) + 1, numero=n.formatado,
                tribunal=t.sigla if t else n.chave_tribunal,
                sistema=t.sistema if t else "?", grau=grau))
        self.tribunal_de = {cnj.chave(n): tribunais.por_numero(n) for n in self.numeros}
        self._autos_de = {cnj.chave(n): a for n, a in zip(self.numeros, self.autos)}
        # O relatório que esta pasta de lote já tinha (o "Tentar de novo" refaz
        # só os que falharam, na mesma pasta): as linhas refeitas agora
        # substituem as antigas, e as demais continuam - senão o relatório do
        # lote, e os "Últimos lotes", ficavam só com os refeitos.
        self._linhas_anteriores = self._ler_relatorio_anterior()
        # chave -> (incompleto, documentos, detalhe) do PDF que o processo já
        # tinha na pasta, ou None (_pdf_que_fica)
        self._pdfs_que_ficam: dict[str | None, tuple[str, str, str] | None] = {}

    # ------------------------------------------------------------ apoio
    @property
    def total(self) -> int:
        return len(self.itens)

    def feitos(self) -> int:
        return sum(1 for i, r in enumerate(self.itens) if r.concluido or i in self._reabertos)

    def _nome_dos_autos(self, n: Numero) -> str:
        """A chave dos autos do item 'n' (cnj.nome_dos_autos com o grau dele):
        o nome do PDF, da capa, do registro e da pasta provisória."""
        autos = self._autos_de.get(cnj.chave(n))
        if autos is None:
            autos = cnj.nome_dos_autos(n, cnj.grau_do_processo(n, getattr(self.opcoes, "grau",
                                                                          "1g")))
        return autos

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
        As linhas se casam pela chave dos AUTOS (processo e grau): o mesmo
        número no 1º e no 2º grau são duas linhas.

        O sigilo é do processo, e vale pela regra, não só pelo que a linha
        diz: a linha do processo baixado quando ainda era público (A no 1º
        grau antes de o 2º apurar o segredo, no mesmo lote; o incidente antes
        do principal, na mesma rodada) sai mascarada também - a retirada já
        levou os autos dele, e o número não pode voltar por ela.
        """
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";", lineterminator="\r\n")
        w.writerow(COLUNAS)
        # Os processos que o lote já sabe sigilosos: os dos relatórios
        # anteriores e os desta rodada (o incidente herda do principal).
        sigilosos = set(self._sigilosos_sabidos)
        sigilosos.update(n.nome_arquivo for n, r in zip(self.numeros, self.itens) if r.sigiloso)
        atuais = {}
        for autos, r in zip(self.autos, self.itens):
            atuais.setdefault(autos, r)
        linhas: list = []
        usados: set = set()
        for chave, antiga in self._linhas_anteriores:
            if chave is not None and chave in atuais:
                if chave not in usados:
                    usados.add(chave)
                    linhas.append((chave, atuais[chave]))
                continue
            linhas.append((chave, antiga))
        for autos, r in zip(self.autos, self.itens):
            if autos not in usados:
                usados.add(autos)
                linhas.append((autos, r))
        for ordem, (chave, item) in enumerate(linhas, 1):
            if isinstance(item, dict):
                if sigilo.contem(sigilosos, _chave_relatorio(item.get("processo"))):
                    # a linha completa diz que é sigiloso e, se a retirada
                    # já levou os autos, onde eles estão (como _mascarar_relatorios)
                    item = dict(item, sigiloso="sim")
                    arquivo = item.get("arquivo") or ""
                    if arquivo and "(na pasta de sigilosos)" not in arquivo \
                            and (self.pasta_sigilosos / f"{chave}.pdf").exists() \
                            and not (self.destino / f"{chave}.pdf").exists():
                        item["arquivo"] = arquivo + " (na pasta de sigilosos)"
                w.writerow(self._linha_antiga(item, ordem, mascarar))
                continue
            r = item
            sigiloso = r.sigiloso or sigilo.contem(sigilosos, chave)
            if mascarar and sigiloso:
                w.writerow([ordem, MASCARA_SIGILOSO, r.tribunal, r.sistema,
                            r.situacao or "PENDENTE", "", "", "", "sim", "", DETALHE_MASCARA,
                            r.data_hora, r.causa, r.grau])
                continue
            arquivo = Path(r.arquivo).name if r.arquivo else ""
            if r.arquivo and sigiloso and r.situacao in (OK, JA_BAIXADO) \
                    and not str(r.arquivo).startswith(str(self.destino)):
                arquivo += " (na pasta de sigilosos)"
            documentos, incompleto, detalhe = r.documentos or "", r.incompleto, r.detalhe
            fica = None if r.situacao in (OK, JA_BAIXADO) else self._pdf_que_fica(chave)
            if fica is not None:
                # A rodada não trocou o PDF que já estava na pasta (falhou,
                # foi interrompida ou ainda não chegou nele): a linha leva o
                # que se sabia dele, para a próxima rodada não o perder.
                incompleto = incompleto or fica[0]
                documentos = documentos or fica[1]
                if PDF_ANTERIOR not in detalhe:
                    detalhe = _juntar(detalhe, PDF_ANTERIOR)
                detalhe = _juntar(detalhe, fica[2])
            w.writerow([ordem, r.numero, r.tribunal, r.sistema, r.situacao or "PENDENTE",
                        r.paginas or "", documentos, arquivo,
                        "sim" if sigiloso else "não", incompleto, detalhe, r.data_hora,
                        r.causa, r.grau])
        return saida.getvalue()

    def _pdf_que_fica(self, chave: str | None) -> tuple[str, str, str] | None:
        """(incompleto, documentos, detalhe) do PDF que os autos 'chave' (a
        chave dos autos) já tinham na pasta do lote (ou na de sigilosos dele),
        pela linha anterior do relatório - a de um download que deu certo ou
        a de uma rodada que não o trocou. None se não há esse PDF ou registro
        dele. Visto uma vez por lote: o que esta rodada não troca continua
        como estava."""
        if chave not in self._pdfs_que_ficam:
            saida = None
            linha = self._linha_anterior(chave) if chave else None
            detalhe = _detalhe_do_pdf(linha) if linha is not None else None
            if detalhe is not None and any(_pdf_valido(pasta / f"{chave}.pdf")
                                           for pasta in (self.destino, self.pasta_sigilosos)):
                saida = ((linha.get("incompleto") or "").strip(),
                         (linha.get("documentos") or "").strip(), _detalhe_de_antes(detalhe))
            self._pdfs_que_ficam[chave] = saida
        return self._pdfs_que_ficam[chave]

    @staticmethod
    def _linha_antiga(linha: dict, ordem: int, mascarar: bool) -> list:
        """A linha de um processo de rodada anterior, como estava (mascarada no
        relatório do acervo, se for sigiloso)."""
        if mascarar and _sim(linha.get("sigiloso")):
            # o grau fica na linha mascarada: não identifica ninguém
            return [ordem, MASCARA_SIGILOSO, linha.get("tribunal", ""), linha.get("sistema", ""),
                    linha.get("situacao") or "PENDENTE", "", "", "", "sim", "", DETALHE_MASCARA,
                    linha.get("data_hora", ""), linha.get("causa", "") or "",
                    _grau_da_linha(linha)]
        return [ordem] + _valores_da_linha(linha)[1:]

    _ler_csv = staticmethod(ler_csv_do_controle)

    def _ler_relatorio_anterior(self) -> list[tuple[str | None, dict]]:
        """[(chave dos autos ou None, linha)] do relatório que a pasta do lote
        já tinha, na ordem dele. A linha mascarada do acervo ("(processo
        sigiloso)") é trocada pela do relatório completo da pasta de
        sigilosos, de mesma ordem; sem ele, fica como está."""
        return _mesclar_relatorios(ler_csv_do_controle(self.controle),
                                   ler_csv_do_controle(self.pasta_sigilosos / "_controle"))

    def _linha_anterior(self, nome: str) -> dict | None:
        """A linha dos autos 'nome' (a chave dos autos) no relatório anterior
        do lote (ou None)."""
        for chave, linha in self._linhas_anteriores:
            if chave == nome:
                return linha
        return None

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
            _marcar_origem(self.pasta_sigilosos, self.destino)
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
        """O PDF dos autos de 'n' que já está na pasta do lote (ou na de
        sigilosos dele), pelo nome dos autos: o do 1º grau não é o do 2º, e
        vice-versa."""
        nome = f"{self._nome_dos_autos(n)}.pdf"
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
        # Apurado agora, pela consulta de um recurso interno dele: não houve
        # download anterior que o dissesse.
        pelo_recurso = self._pelo_recurso_interno(n)
        if pelo_recurso:
            return pelo_recurso
        # O incidente herda o sigilo do principal (a regra única).
        if sigilo.contem(self._sigilosos_sabidos, nome):
            return SIGILO_ANTERIOR
        # A capa guardada de qualquer dos dois graus: o sigilo é do processo.
        for grau in cnj.GRAUS:
            try:
                with open(self.controle / f"{cnj.nome_dos_autos(n, grau)}_capa.txt",
                          encoding="utf-8", errors="replace") as f:
                    if "SEGREDO DE JUSTIÇA" in f.read(2000):
                        return SIGILO_ANTERIOR
            except OSError:
                pass
        return (sigilo.motivo_da_pasta(self.raiz_sigilosos, n) or sigilo.motivo_da_pauta(n)
                or sigilo.motivo_do_download(n))

    def _pelo_recurso_interno(self, n: Numero) -> str:
        """O porquê do sigilo do principal 'n' que a consulta de um recurso
        interno dele abriu em segredo de justiça nesta rodada
        (_principal_apurado), ou ""."""
        recurso = self._apurados_pelo_recurso.get(n.nome_arquivo)
        if not recurso:
            return ""
        return f"a consulta do recurso interno {recurso} abriu a página dele em segredo de justiça"

    def _sigilo_so_do_relatorio(self, n: Numero, motivo: str) -> bool:
        """O sigilo vem só de um relatório anterior deste lote (ou da capa)?
        É o do lote de versão anterior, com o sigiloso no acervo e sem o
        registro do download. O relatório marca também o que o lote só
        TRATOU como sigiloso porque a pasta dos sigilosos ou a pauta o
        indicava: esse não vai para o registro do download, que diria, sem
        ser verdade, que o portal o apurou (e desfazer a marcação errada da
        pauta deixaria de bastar)."""
        return motivo == SIGILO_ANTERIOR and not (
            sigilo.motivo_da_pasta(self.raiz_sigilosos, n) or sigilo.motivo_da_pauta(n))

    def _lembrar_sigilo(self, n: Numero) -> bool:
        """O sigilo que o portal mostrou passa a valer na regra única
        (sigilo.lembrar_do_download): o índice, o texto para a IA, o conector,
        o pacote, a nuvem e a transcrição deixam o processo de fora mesmo com
        os autos no acervo (separação dos sigilosos desligada, ou presos).

        Se o registro não pôde ser gravado, falha para o lado seguro: os autos
        vão para a pasta de sigilosos mesmo com a separação desligada
        (_separar), onde a regra os vê pela pasta. False nesse caso."""
        if sigilo.lembrar_do_download([n]):
            return True
        self._sem_registro.add(n.nome_arquivo)
        log.warning("    não consegui guardar no registro do sigilo que %s corre em segredo de "
                    "justiça; o lote o trata como sigiloso assim mesmo%s.", n.formatado,
                    "" if self.opcoes.separar_sigilosos else
                    " e o guarda na pasta de sigilosos, mesmo com a separação desligada")
        return False

    def _separar(self, n: Numero) -> bool:
        """O sigiloso 'n' vai para a pasta de sigilosos? Com a separação
        ligada, sempre; desligada, só se o sigilo dele não pôde ir para o
        registro do download (_lembrar_sigilo)."""
        return bool(self.opcoes.separar_sigilosos) or n.nome_arquivo in self._sem_registro

    def _levar(self, origem_dir: Path, alvo_dir: Path, n: Numero,
               r: ResultadoProcesso | None,
               manter_destino: bool = False) -> tuple[Path | None, list[str], Exception | None]:
        """_levar_arquivos dos autos de 'n' (pela chave dos autos), e as
        gravações do resultado 'r' passam a apontar para o novo lugar."""
        nome = self._nome_dos_autos(n)
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
        nome = f"{self._nome_dos_autos(n)}.pdf"
        sigilo = r.sigiloso and self._separar(n)
        alvo_dir = self.pasta_sigilosos if sigilo else self.destino
        if sigilo:
            _marcar_origem(self.pasta_sigilosos, self.destino)
        novo, problemas, erro = self._levar(provisorio, alvo_dir, n, r)
        if novo is None:
            r.situacao, r.arquivo, r.midias = ERRO, "", []
            r.causa = CAUSA_GRAVACAO
            motivo = (getattr(erro, "strerror", None) or str(erro)) if erro else "o PDF sumiu"
            if sigilo:
                log.error("    %s é sigiloso e não pôde ser guardado na pasta de sigilosos "
                          "(%s): não foi posto no acervo.", n.formatado, erro)
                r.detalhe = _juntar(
                    r.detalhe, f"processo em segredo de justiça: não consegui guardá-lo na pasta "
                    f"de sigilosos ({motivo}). Por segurança, ele não foi posto no acervo. "
                    "Confira a pasta dos sigilosos em Ajustes › Pastas e baixe de novo")
            elif isinstance(erro, PermissionError):
                # Aqui sim é o PDF do lote: aberto no leitor (o Windows o trava)
                r.causa = CAUSA_PDF_ABERTO
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
                if not self.opcoes.separar_sigilosos:
                    r.detalhe = _juntar(r.detalhe, SEM_REGISTRO_DO_SIGILO)
        if sigilo:
            # Cópias baixadas quando o processo ainda era público (neste
            # lote ou noutro) também saem do acervo.
            self._retirar_do_acervo(r, n)
        elif r.sigiloso:
            # Separação desligada: nada sai do acervo, mas o originário desta
            # rodada herda o sigilo como herdaria com ela ligada.
            self._herdar_originarios(r, n, levar=False)

    def _lotes_do_acervo(self) -> list[Path]:
        """As pastas de lote do acervo (Processos/*), fora a de sigilosos."""
        raiz = getattr(self.cfg, "pasta_processos", None)
        if raiz is None and self.destino.parent.name.lower() == "processos":
            raiz = self.destino.parent           # sem configuração (testes)
        return _lotes_do_acervo(raiz, self.raiz_sigilosos, [self.destino])

    def _retirar_do_acervo(self, r: ResultadoProcesso, n: Numero) -> Retirada:
        """Tira do acervo toda cópia de um processo sigiloso: a deste lote e
        as de outros lotes (Processos/<lote>/), com capa e gravações, para
        Sigilosos/<lote>/; as transcrições; e apaga o texto dele em _ia/texto.
        Devolve a Retirada (o que saiu e o que ficou)."""
        acervo = getattr(self.cfg, "pasta_acervo", None)
        if acervo is None and self.destino.parent.name.lower() == "processos":
            acervo = self.destino.parent.parent
        try:
            cfg = self._config()
        except Exception as erro:          # config.ini ilegível: os autos saem assim mesmo
            log.debug("transcrições do sigiloso: configuração indisponível (%s)", erro)
            cfg = None
        ret = retirar_do_acervo(cfg, n, raiz_sigilosos=self.raiz_sigilosos,
                                lotes=self._lotes_do_acervo(), acervo=acervo,
                                alvos={self.destino: self.pasta_sigilosos})
        self._sigilo_motivos.update({str(k): v for k, v in ret.motivos.items()})
        if ret.autos or ret.outros:
            self._retirou_do_acervo = True
        novo = ret.autos.get(self.destino / f"{self._nome_dos_autos(n)}.pdf")
        if novo is not None:
            r.arquivo = str(novo)
            r.detalhe = _juntar(r.detalhe, "levado agora para a pasta de sigilosos")
        # O incidente dele baixado nesta rodada, quando o sigilo ainda não se
        # sabia, saiu junto (herda o sigilo): o item passa a dizê-lo, com o
        # PDF e as gravações onde estão agora - o relatório e o JSON do lote
        # não podem contradizer a pasta. O que ficou preso (aberto no
        # leitor) também é sigiloso: o item o diz, com o PDF onde está, e o
        # aviso no fim desta função pede para fechá-lo e movê-lo.
        for outro in self.itens:
            levado = ret.autos.get(Path(outro.arquivo)) if outro.arquivo else None
            preso = bool(outro.arquivo) and Path(outro.arquivo) in ret.autos_presos
            if outro is r or (levado is None and not preso):
                continue
            outro.sigiloso = True
            if preso:
                outro.detalhe = _juntar(outro.detalhe, "processo sigiloso: a cópia dos autos "
                                        "ficou presa no acervo (feche-a e mova-a para a pasta "
                                        "de sigilosos)")
                self._publicar(outro)
                continue
            outro.arquivo = str(levado)
            outro.detalhe = _juntar(outro.detalhe, "levado agora para a pasta de sigilosos")
            if outro.midias:
                velho_midias = self.destino / "_controle" / "midias" / levado.stem
                novo_midias = levado.parent / "_controle" / "midias" / levado.stem
                outro.midias = [m.replace(str(velho_midias), str(novo_midias), 1)
                                for m in outro.midias]
            self._publicar(outro)
        self._herdar_originarios(r, n, levar=True)
        if ret.outros:
            um = len(ret.outros) == 1
            r.detalhe = _juntar(r.detalhe, (
                "1 arquivo com o número dele levado de outra pasta do acervo" if um
                else f"{len(ret.outros)} arquivos com o número dele levados de outras pastas "
                     "do acervo") + " para a pasta de sigilosos: " + ", ".join(
                _relativo(p, acervo) for p in list(ret.outros)[:5]))
        self._contar_transcricoes(r, n, ret)
        presos = [p for p in ret.bloqueiam if p not in ret.transcricoes_presas]
        if presos:
            self._sigilo_no_acervo += [str(p) for p in presos]
            log.error("ATENÇÃO: %s é sigiloso e NÃO pôde ser tirado do acervo: %s",
                      n.formatado, ", ".join(str(p) for p in presos))
            if r.situacao in (OK, JA_BAIXADO):
                r.situacao = ERRO
                r.causa = CAUSA_SIGILO_NO_ACERVO
            uma = len(presos) == 1
            r.detalhe = _juntar(
                r.detalhe, "ATENÇÃO: processo sigiloso com "
                + ("cópia dos autos no acervo que não pôde ser levada" if uma
                   else "cópias dos autos no acervo que não puderam ser levadas")
                + " para a pasta de sigilosos: "
                + ", ".join(f"{_relativo(p, acervo)} ({ret.motivos.get(p, 'aberto?')})"
                            for p in presos)
                + (". Feche-a e mova-a" if uma else ". Feche-as e mova-as")
                + " à mão antes de compartilhar o acervo")
        avisos = [p for p in ret.avisam if p not in ret.transcricoes_presas]
        self._sigilo_avisos += [str(p) for p in avisos]
        # O relatório completo da pasta de sigilosos que não pôde ser regravado
        # (_mascarar_relatorios) não está no acervo: não há o que mover, só o
        # que fechar - o download seguinte do lote o regrava. Fica no detalhe
        # e no registro, fora dos avisos do lote (o fim do lote, o Início e a
        # tela Compartilhar diriam que ele "ficou no acervo").
        completos = list(ret.completos_presos)
        if completos:
            log.warning("o relatório completo da pasta de sigilosos não pôde ser atualizado: %s",
                        ", ".join(str(p) for p in completos))
            um = len(completos) == 1
            r.detalhe = _juntar(
                r.detalhe, "atenção: "
                + ("o relatório completo da pasta de sigilosos não pôde ser atualizado" if um
                   else f"{len(completos)} relatórios completos da pasta de sigilosos não "
                        "puderam ser atualizados")
                + ": " + ", ".join(f"{_relativo(p, self.raiz_sigilosos)} "
                                   f"({ret.motivos.get(p, 'aberto?')})" for p in completos[:5])
                + (". Feche-o: o próximo download do lote o regrava" if um
                   else ". Feche-os: o próximo download de cada lote os regrava"))
        if avisos:
            log.warning("%s é sigiloso; estes arquivos dele ficaram no acervo: %s",
                        n.formatado, ", ".join(str(p) for p in avisos))
            um = len(avisos) == 1
            r.detalhe = _juntar(
                r.detalhe, "atenção: "
                + ("1 arquivo do processo sigiloso ficou no acervo" if um
                   else f"{len(avisos)} arquivos do processo sigiloso ficaram no acervo")
                + ": " + ", ".join(f"{_relativo(p, acervo)} ({ret.motivos.get(p, 'aberto?')})"
                                   for p in avisos[:5])
                + (". Feche-o e mova-o" if um else ". Feche-os e mova-os")
                + " para a pasta de sigilosos")
        return ret

    def _herdar_originarios(self, r: ResultadoProcesso, n: Numero, levar: bool) -> None:
        """O originário do 2º grau (HC, MS, AI) baixado nesta rodada antes de
        a ação de origem 'n' se apurar sigilosa herda o sigilo agora, pela capa
        que o download guardou em _controle (a mesma regra do preparo,
        sigilo.herdadas_das_origens, com o lote como raiz): o item o diz, e o
        sigilo vai para o registro do download. Deixado ao preparo do fim do
        lote, o JSON ficaria dizendo "público" - e, com a separação ligada,
        com o caminho de um PDF que o preparo levaria. 'levar': os autos dele
        vão para a pasta de sigilosos, como os da origem; com a separação
        desligada, ficam onde estão, salvo se o sigilo dele não pôde ir para
        o registro (_separar). O já sigiloso não é refeito (e a retirada
        abaixo não volta a este item)."""
        if "2g" not in self.graus:
            return                       # o originário é do 2º grau: lote só do 1º não tem
        herdados = sigilo.herdadas_das_origens(self.destino, sigilo.Sigilosas({n.nome_arquivo}))
        for outro, numero in zip(self.itens, self.numeros):
            if outro is r or outro.sigiloso or numero.nome_arquivo not in herdados \
                    or outro.situacao not in (OK, JA_BAIXADO) or not outro.arquivo \
                    or not _dentro(outro.arquivo, self.destino):
                continue
            outro.sigiloso = True
            outro.detalhe = _juntar(outro.detalhe, f"tratado como sigiloso: o processo de origem "
                                                   f"{n.formatado} é sigiloso")
            # o rastro do porquê em Logs, com a frase da regra do preparo
            # (sigilo.chaves_sigilosas): o manual manda procurá-lo lá
            log.warning("originário %s tratado como sigiloso: o processo de origem %s é "
                        "sigiloso", numero.formatado, n.formatado)
            self._lembrar_sigilo(numero)
            if levar or self._separar(numero):
                self._retirar_do_acervo(outro, numero)
                if not levar:
                    outro.detalhe = _juntar(outro.detalhe, SEM_REGISTRO_DO_SIGILO)
            self._publicar(outro)

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
        levadas e as que não puderam sair. Estas não travam o compartilhamento
        (só os autos travam: o índice, o conector, o pacote e a nuvem já as
        deixam de fora), mas o aviso diz qual arquivo é e o que fazer."""
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
        self._sigilo_avisos += [str(p) for p in presos]
        log.warning("ATENÇÃO: %s é sigiloso e a transcrição dele NÃO pôde ser tirada do "
                    "acervo%s: %s", n.formatado,
                    " (a audiência está sendo gravada)" if gravando else "",
                    ", ".join(str(p) for p in presos))
        um = len(presos) == 1
        if gravando:
            r.detalhe = _juntar(
                r.detalhe, "atenção: processo sigiloso com audiência sendo gravada agora; a "
                "transcrição fica no acervo até a gravação terminar. Depois, clique em "
                f"“{TENTAR_DE_NOVO}” (ou prepare o acervo para a IA) para levá-la à pasta de "
                "sigilosos")
        else:
            r.detalhe = _juntar(
                r.detalhe, "atenção: processo sigiloso com "
                + ("arquivo de transcrição no acervo que não pôde ser levado" if um
                   else "arquivos de transcrição no acervo que não puderam ser levados")
                + " para a pasta de sigilosos (está aberto em outro programa?): "
                + ", ".join(p.name for p in presos)
                + (". Feche-o e mova-o" if um else ". Feche-os e mova-os")
                + " para a pasta de sigilosos")

    def _area_provisoria(self, n: Numero) -> Path:
        """A pasta provisória destes autos (provisorio/<chave dos autos>), vazia."""
        pasta = self.provisorio / self._nome_dos_autos(n)
        shutil.rmtree(pasta, ignore_errors=True)
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    def _limpar_parcial(self, n: Numero) -> None:
        autos = self._nome_dos_autos(n)
        shutil.rmtree(self.provisorio / autos, ignore_errors=True)
        # parciais de versões anteriores, que gravavam direto no lote
        for sufixo in (".pdf.parcial", ".pdf.parcial2"):
            try:
                (self.destino / f"{autos}{sufixo}").unlink()
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
        """(tribunal no grau, índices dos itens) por tribunal e grau, na ordem
        da primeira aparição na relação: um navegador e um login por grupo, e
        o Tribunal do grupo já no grau dele (Tribunal.no_grau), que leva o
        grau às fábricas, aos portais, ao cofre e ao perfil do navegador.
        Quem não tem portal suportado (no grau dele) já sai marcado."""
        saida: OrderedDict[str, tuple] = OrderedDict()
        for i, n in enumerate(self.numeros):
            t = self.tribunal_de[cnj.chave(n)]
            r = self.itens[i]
            grau = self.graus[i]
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
            if grau != "1g" and not t.tem_grau(grau):
                # O sistema principal do tribunal não tem o grau no catálogo (o
                # e-SAJ do TJSP não tem a consulta de 2º grau): repetir não muda.
                r.situacao = NAO_SUPORTADO
                r.detalhe = (f"o {tribunais.rotulo_do_grau(grau)} do {t.nome_sistema} do "
                             f"{t.sigla} ainda não é baixado pelo Helestron; baixe-o pelo portal "
                             "do tribunal")
                r.carimbar()
                continue
            saida.setdefault(f"{t.chave}|{grau}", (t.no_grau(grau), []))[1].append(i)
        return saida

    def _encerrar_grupo(self, indices: list[int], situacao: str, detalhe: str,
                        causa: str = "") -> None:
        for i in indices:
            r = self.itens[i]
            if r.situacao == "":
                # o sistema do grupo nem chegou a ser consultado para este item
                r.consultas.append({"sistema": r.sistema, "consultado": False, "causa": causa,
                                    "detalhe": detalhe, **_do_grau(r.grau)})
                if i in self._anteriores:
                    # O sistema alternativo nem pôde ser consultado: vale o
                    # "não encontrado" do principal, com o porquê - e a causa,
                    # que diz que uma nova rodada ainda pode achá-lo.
                    situacao_antes, detalhe_antes, sistema_antes = self._anteriores.pop(i)
                    r.situacao, r.sistema = situacao_antes, sistema_antes
                    r.detalhe = "; ".join(x for x in (detalhe_antes, detalhe) if x)
                else:
                    r.situacao = situacao
                    r.detalhe = detalhe
                r.causa = causa
                self._concluir(r)

    def _evento(self, tipo: str, **dados) -> None:
        """Repassa um evento legível por máquina a quem acompanha (nunca falha)."""
        metodo = getattr(self.ctx, "evento", None)
        if metodo is None:
            return
        try:
            metodo(tipo, **dados)
        except Exception:
            log.debug("ctx.evento(%s) falhou", tipo, exc_info=True)

    def _credenciais(self, tribunal) -> tuple[str, str] | None:
        if self.opcoes.modo_login(tribunal.sistema) != "senha" or self.cofre is None:
            return None
        if not getattr(self.opcoes, "usar_cofre", True):
            # --sem-cofre: a senha guardada não é lida; o portal abre na tela
            # de entrada (_opcoes_do_grupo) para o usuário entrar à mão
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
        log.info("Sem usuário e senha guardados para o %s: o navegador abre na tela "
                 "de entrada para você entrar.", nome_do_portal(tribunal))
        return replace(self.opcoes, login={**self.opcoes.login, sistema: "manual"})

    def executar(self) -> ResumoLote:
        try:
            self.destino.mkdir(parents=True, exist_ok=True)
        except OSError as erro:
            raise RuntimeError(f"não consegui criar a pasta de destino {self.destino} "
                               f"({erro.strerror or erro}). Escolha outra pasta.") from erro
        # Um download por pasta de lote: o segundo, ao mesmo tempo, estragaria
        # o relatório do primeiro (LoteEmAndamento, um RuntimeError).
        self._trava.adquirir()
        try:
            resumo = self._executar()
        finally:
            self._trava.soltar()
        self._evento("fim", total=self.total, baixados=len(resumo.baixados),
                     ja_baixados=len(resumo.pulados), falhas=len(resumo.falhas),
                     pendentes=len(resumo.pendentes),
                     sigilosos=len([r for r in resumo.sigilosos if r.situacao in (OK, JA_BAIXADO)]),
                     sigilosos_no_acervo=len(resumo.sigilosos_no_acervo))
        return resumo

    def _destino_no_acervo(self) -> bool:
        """O lote está dentro do acervo? Sem saber onde fica o acervo (dublê
        de configuração), sim - o preparo roda como sempre rodou."""
        acervo = getattr(self.cfg, "pasta_acervo", None)
        if acervo is None and self.cfg is None:
            try:
                acervo = self._config().pasta_acervo
            except Exception:
                acervo = None
        return True if acervo is None else _dentro(self.destino, acervo)

    def _executar(self) -> ResumoLote:
        from ..nucleo.energia import manter_acordado

        grupos = self.grupos()
        self._limpar_provisorios_antigos()
        for r in self.itens:
            self._publicar(r)
        self.salvar_relatorio()
        log.info("Lote %s: %d processo(s) em %d tribunal(is) suportado(s).",
                 self.destino.name, self.total, len(grupos))
        self._evento("lote_inicio", destino=str(self.destino), relatorio=str(self.relatorio),
                     sigilosos_do_lote=str(self.pasta_sigilosos), total=self.total)
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
                    r.causa = CAUSA_INTERROMPIDO
                    r.detalhe = r.detalhe or "não chegou a ser baixado (lote interrompido)"
                    self._publicar(r)
            self.salvar_relatorio()
            try:
                self.ctx.progresso(self.feitos(), self.total, "")
            except Exception:
                pass
        resumo = ResumoLote(itens=self.itens, destino=self.destino, relatorio=self.relatorio,
                            minutos=round((time.monotonic() - self.inicio) / 60, 1),
                            sigilosos_no_acervo=list(self._sigilo_no_acervo),
                            sigilosos_avisos=list(self._sigilo_avisos),
                            sigilosos_motivos=dict(self._sigilo_motivos),
                            pasta_sigilosos=self.pasta_sigilosos,
                            relatorio_completo=(self.relatorio_sigilosos
                                                if self.relatorio_sigilosos.exists() else None))
        log.info("Fim do lote: %s Relatório: %s", resumo.texto(), self.relatorio)
        if self._sigilo_avisos:
            self._avisar_sigilo(self._sigilo_avisos, trava=False)
        if self._sigilo_no_acervo:
            # Não se prepara nada para a IA com os autos de um sigiloso no
            # acervo: o texto dele iria para _ia/texto e para o índice.
            self._avisar_sigilo(self._sigilo_no_acervo, trava=True)
            return resumo
        # Depois de "Parar" (ou Ctrl+C), o usuário quer o programa livre já:
        # o preparo pode ler dezenas de PDFs. Fica para o botão "Preparar
        # arquivos para IA" ou para o próximo lote.
        parou = self._interrompido or self._cancelado()
        # Lote fora do acervo (--destino noutra pasta) não muda o acervo: não
        # há o que preparar - salvo se um sigiloso saiu de lá agora.
        no_acervo = self._retirou_do_acervo or self._destino_no_acervo()
        if self.opcoes.atualizar_ia and (resumo.baixados or self._retirou_do_acervo) \
                and not parou and no_acervo:
            presos, avisos = self._preparar_ia()
            resumo.sigilosos_motivos.update(self._sigilo_motivos)
            novos = [p for p in avisos if str(p) not in resumo.sigilosos_avisos]
            if novos:
                resumo.sigilosos_avisos += [str(p) for p in novos]
                self._avisar_sigilo(novos, trava=False)
            if presos:
                # O preparo tira do acervo o que o programa já sabe sigiloso
                # (pasta, pauta); os autos que ficaram presos travam o
                # compartilhamento.
                resumo.sigilosos_no_acervo += [str(p) for p in presos]
                self._avisar_sigilo(presos, trava=True)
        return resumo

    def _avisar_sigilo(self, arquivos, trava: bool) -> None:
        """O aviso do fim do lote: o arquivo de processo sigiloso que ficou no
        acervo, por quê e o que fazer (a mesma frase da tela Compartilhar)."""
        try:
            from ..compartilhar.preparo import frase_sigilosos_no_acervo
            cfg = self.cfg if self.cfg is not None and hasattr(self.cfg, "pasta_acervo") \
                else None
            frase = frase_sigilosos_no_acervo(
                [Path(p) for p in arquivos], cfg,
                {Path(k): v for k, v in self._sigilo_motivos.items()}, trava=trava)
        except Exception:
            um = len(arquivos) == 1
            frase = (("Não consegui levar para a pasta de sigilosos o arquivo " if um
                      else "Não consegui levar para a pasta de sigilosos os arquivos ")
                     + "; ".join(str(p) for p in arquivos)
                     + (". Feche o programa que o mantém aberto e mova-o" if um
                        else ". Feche o programa que os mantém abertos e mova-os")
                     + f" à mão (ou clique em “{TENTAR_DE_NOVO}”).")
        try:
            self.ctx.avisar("Processo sigiloso ficou no acervo" if trava
                            else "Arquivo de processo sigiloso no acervo", frase)
        except Exception:
            pass

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
            r.situacao, r.detalhe, r.sistema, r.causa = "", "", alt.sistema, ""
        try:
            self._grupo(alt, reabrir, alternativo=True)
        finally:
            for i in reabrir:
                r = self.itens[i]
                antes = self._anteriores.pop(i, None)
                self._reabertos.discard(i)
                if antes is None:
                    continue           # devolvido ao "não encontrado" do principal
                segundo = getattr(tribunal, "grau", "1g") == "2g"
                if r.situacao == NAO_ENCONTRADO:
                    r.sistema = antes[2]
                    if segundo:
                        # a dica de grau: trocar o grau do lote (a apelação que
                        # não subiu está no 1º grau) - ou, se o número só existe
                        # no 2º grau, que trocar não muda nada
                        r.detalhe = (f"não encontrado no {tribunal.nome_sistema} nem no "
                                     f"{alt.nome_sistema} do {tribunal.sigla} (2º grau); "
                                     "confira o número; "
                                     + dica_de_grau(self.numeros[i], "2g"))
                    else:
                        r.detalhe = (f"não encontrado no {tribunal.nome_sistema} nem no "
                                     f"{alt.nome_sistema} do {tribunal.sigla}; confira o número")
                    self._concluir(r)
                elif r.situacao == ERRO:
                    r.detalhe = (f"não encontrado no {tribunal.nome_sistema}"
                                 + (" (2º grau)" if segundo else "")
                                 + f"; no {alt.nome_sistema}: {r.detalhe}")
                    self._concluir(r)
                elif r.situacao in ("", CANCELADO):
                    r.sistema = antes[2]     # interrompido: nada se apurou no alternativo

    def _preparar_ia(self) -> tuple[list[Path], list[Path]]:
        """Atualiza INDICE.md, CLAUDE.md e os textos do acervo. Nunca falha o lote.
        Devolve o que o preparo não conseguiu tirar do acervo de processo
        sigiloso: (os autos, que travam o compartilhamento; o resto)."""
        try:
            from ..compartilhar import preparo
        except ImportError:
            log.debug("preparo da IA indisponível nesta versão")
            return [], []
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
            return [], []
        presos = getattr(rel, "sigilosos_no_acervo", None)
        avisos = getattr(rel, "sigilosos_avisos", None)
        motivos = getattr(rel, "motivos", None)
        if isinstance(motivos, dict):
            self._sigilo_motivos.update({str(k): str(v) for k, v in motivos.items()})
        return ([Path(p) for p in presos] if isinstance(presos, list) else [],
                [Path(p) for p in avisos] if isinstance(avisos, list) else [])

    def _progresso_preparo(self, feitos: int, total: int, _descricao: str = "") -> None:
        # No máximo um recado a cada 2 s: no terminal, cada um vira uma linha.
        agora = time.monotonic()
        if total and agora - self._ultimo_preparo >= 2.0:
            self._ultimo_preparo = agora
            self.ctx.status(f"Preparando os arquivos para a IA ({feitos} de {total})...")

    # -------------------------------------------------------------- grupo
    def _grupo(self, tribunal, indices: list[int], alternativo: bool = False) -> None:
        nome = nome_do_portal(tribunal)
        # "grau": "2g" nos eventos do grupo do 2º grau (no 1º, como eram)
        do_grau = _do_grau(getattr(tribunal, "grau", "1g"))
        credenciais = self._credenciais(tribunal)
        opcoes = self._opcoes_do_grupo(tribunal, credenciais)
        self._evento("grupo_inicio", sistema=tribunal.sistema, tribunal=tribunal.sigla,
                     alternativo=bool(alternativo), ordens=[self.itens[i].ordem for i in indices],
                     **do_grau)
        # Navegador ocupado por outro download (o mesmo perfil não abre duas
        # vezes), ou que não abre porque a cópia antiga do perfil ficou presa
        # (CopiaAntigaPresa): com "esperar o navegador", tenta de novo a cada
        # 30 s até o prazo - mas só antes de o grupo começar a baixar.
        espera = max(0.0, float(getattr(self.opcoes, "esperar_navegador_s", 0) or 0))
        limite = time.monotonic() + espera
        avisou = False
        while True:
            self._itens_comecaram = False
            try:
                self._percorrer_grupo(tribunal, indices, nome, opcoes, credenciais)
            except NavegadorOcupado as erro:
                restante = limite - time.monotonic()
                if not self._itens_comecaram and restante > 0 and not self._cancelado():
                    if not avisou:
                        avisou = True
                        ate = datetime.fromtimestamp(time.time() + restante)
                        if isinstance(erro, CopiaAntigaPresa):
                            motivo = MOTIVO_COPIA_ANTIGA
                            frase = (f"O navegador do {nome} não abre agora: a cópia antiga do "
                                     "perfil do Chrome (das versões anteriores) ainda não pôde "
                                     "ser apagada. Feche as janelas do navegador do programa (e "
                                     "o Explorador, se estiver aberto na pasta perfis do "
                                     "Helestron); tento de novo até "
                                     f"{ate:%H:%M}...")
                        else:
                            motivo = MOTIVO_OUTRO_DOWNLOAD
                            frase = (f"O navegador do {nome} está ocupado por outro download; "
                                     f"esperando até {ate:%H:%M}...")
                        log.warning("%s", frase)
                        self.ctx.status(frase)
                        self._evento("navegador_ocupado", sistema=tribunal.sistema,
                                     tribunal=tribunal.sigla,
                                     ate=ate.isoformat(timespec="seconds"), motivo=motivo,
                                     **do_grau)
                    try:
                        self._dormir(min(ESPERA_NAVEGADOR_S, restante))
                    except Cancelado:
                        self._interromper_grupo(indices)
                        return
                    continue
                log.error("%s indisponível: %s", nome, erro)
                self._encerrar_grupo(indices, ERRO, f"portal indisponível: {erro}",
                                     CAUSA_NAVEGADOR_OCUPADO)
            except Cancelado:
                self._interromper_grupo(indices)
            except LoginFalhou as erro:
                log.error("Login no %s falhou: %s", nome, erro)
                self._evento("login_falhou", sistema=tribunal.sistema, tribunal=tribunal.sigla,
                             detalhe=str(erro), **do_grau)
                self._encerrar_grupo(indices, ERRO, f"login falhou: {erro}", CAUSA_LOGIN)
                try:
                    texto = str(erro)
                    self.ctx.avisar(f"Não foi possível entrar no {nome}",
                                    texto[:1].upper() + texto[1:])
                except Exception:
                    pass
            except PortalIndisponivel as erro:
                log.error("%s indisponível: %s", nome, erro)
                self._encerrar_grupo(indices, ERRO, f"portal indisponível: {erro}", CAUSA_PORTAL)
            except Exception as erro:          # nada de lote morto sem explicação
                log.exception("Erro inesperado no grupo do %s", nome)
                self._encerrar_grupo(indices, ERRO, f"erro inesperado: {str(erro)[:200]}",
                                     CAUSA_INESPERADO)
            return

    def _interromper_grupo(self, indices: list[int]) -> None:
        # Só o item que estava em curso recebe este recado; os que nem
        # começaram são marcados no fim do lote. Todos voltam na próxima.
        for i in indices:
            r = self.itens[i]
            if r.situacao == "":
                r.situacao = CANCELADO
                r.causa = CAUSA_INTERROMPIDO
                r.detalhe = "interrompido pelo usuário; será baixado na próxima vez"
                self._concluir(r)
                break
        log.info("Download interrompido pelo usuário.")

    def _percorrer_grupo(self, tribunal, indices: list[int], nome: str, opcoes,
                         credenciais) -> None:
        with self.fabrica_navegador(tribunal, opcoes) as nav:
            self._nav = nav
            portal = self.fabrica_portal(nav, tribunal, opcoes, self.ctx, credenciais)
            self.ctx.status(f"Entrando no {nome}...")
            portal.entrar()
            self._seguidos_fora = 0
            for posicao, i in enumerate(indices):
                if self.ctx.cancelado():
                    raise Cancelado()
                self._itens_comecaram = True
                usou_portal, fora = self._item(portal, i)
                self._seguidos_fora = self._seguidos_fora + 1 if fora else 0
                if self._seguidos_fora >= MAX_INDISPONIVEL_SEGUIDOS:
                    resto = [j for j in indices if self.itens[j].situacao == ""]
                    self._encerrar_grupo(
                        resto, ERRO, f"o {nome} parou de responder; tente mais tarde",
                        CAUSA_PORTAL_PAROU)
                    log.error("O %s parou de responder: desisti dos %d processo(s) "
                              "restantes do grupo.", nome, len(resto))
                    return
                if usou_portal and posicao < len(indices) - 1 and self.opcoes.pausa:
                    self._dormir(self.opcoes.pausa)

    def _tela_sigilosa(self, sigiloso: bool) -> None:
        """Avisa o navegador de que a tela em curso é de processo sigiloso:
        ele não a guarda em Logs\\diagnostico."""
        if self._nav is None:
            return
        try:
            self._nav.sigiloso_em_curso = sigiloso
        except Exception:                  # navegador sem o atributo (dublê): nada a fazer
            pass

    # ------------------------------------------------------- já na pasta
    def _registro_anterior(self, n: Numero, existente: Path) -> dict:
        """O que se sabe do download que trouxe o PDF que já está na pasta.

        Em ordem de confiança (o mais confiável vence): a linha anterior do
        relatório, o registro do download (_controle/<número>_meta.json, ao
        lado do PDF) e o manifesto de paginação gravado DENTRO do PDF - que
        anda com ele para onde ele for e diz o sistema e as folhas ausentes.
        A linha vale se é de um download que deu certo ou de uma rodada que
        não trocou o PDF (a que falhou ao baixá-lo de novo, por exemplo):
        esta leva adiante, depois de PDF_ANTERIOR, o que se sabia dele.

        Tudo pela chave dos AUTOS - o nome do PDF achado ('existente' é
        "<chave dos autos>.pdf"): o registro do 1º grau não é o do 2º.
        """
        nome = existente.stem
        try:
            grau = cnj.grau_do_nome(existente.name)
        except cnj.NumeroInvalido:
            grau = "1g"
        reg: dict = {"sistema": "", "tribunal": "", "documentos": 0, "incompleto": "",
                     "detalhe": "", "paginacao": {}, "linha": None, "meta": False,
                     "manifesto": False,
                     # o grau dos autos pedidos (pelo nome) e o que o manifesto do
                     # PDF diz ("" sem manifesto): _baixar_de_novo os compara
                     "grau": grau, "grau_do_pdf": ""}
        linha = self._linha_anterior(nome)
        do_pdf = _detalhe_do_pdf(linha) if linha is not None else None
        if do_pdf is not None:
            reg.update(linha=dict(linha, detalhe=do_pdf),
                       sistema=(linha.get("sistema") or "").strip(),
                       tribunal=(linha.get("tribunal") or "").strip(),
                       documentos=_inteiro(linha.get("documentos")),
                       incompleto=(linha.get("incompleto") or "").strip(),
                       detalhe=_detalhe_de_antes(do_pdf))
        meta = ler_meta(existente.parent, nome)
        if meta:
            reg["meta"] = True
            for chave in ("sistema", "tribunal", "incompleto"):
                if isinstance(meta.get(chave), str):
                    reg[chave] = meta[chave].strip()
            reg["documentos"] = _inteiro(meta.get("documentos"), reg["documentos"])
            reg["detalhe"] = _detalhe_de_antes(meta.get("detalhe"))
            if isinstance(meta.get("paginacao"), dict):
                reg["paginacao"] = dict(meta["paginacao"])
        try:
            manifesto = paginacao.ler_do_pdf(existente)
        except Exception:                  # PDF ilegível: fica o que se tinha
            manifesto = None
        essencial = essencial_da_paginacao(manifesto)
        if essencial:
            reg["manifesto"] = True
            reg["grau_do_pdf"] = paginacao.grau(manifesto)
            reg["paginacao"] = essencial
            reg["sistema"] = essencial.get("sistema") or reg["sistema"]
            if manifesto.get("tribunal"):
                reg["tribunal"] = str(manifesto["tribunal"])
            # No e-SAJ, as folhas com página de aviso SÃO o "incompleto"; no
            # eProc, o registro do download diz melhor (evento não listado).
            if essencial.get("paginacao") == paginacao.FOLHAS or not reg["incompleto"]:
                reg["incompleto"] = _incompleto_do_manifesto(essencial)
            # O manifesto que não descreve o PDF (página incluída ou apagada
            # depois do download) não garante a paginação: a mesma conferência
            # do texto, que sai "nao_garantida".
            from ..compartilhar import textos
            paginas = _paginas(existente)
            if not textos.manifesto_confere(manifesto, paginas):
                reg["paginacao"] = {"garantida": False,
                                    "resumo": textos.resumo_da_paginacao(manifesto, paginas)}
        return reg

    def _baixar_de_novo(self, reg: dict, portal) -> str:
        """Por que o PDF que já está na pasta deve ser baixado de novo ("" =
        não deve)."""
        sistema = reg["sistema"] or getattr(portal, "sistema", "") or ""
        # O manifesto diz que o PDF com o nome destes autos é do outro grau
        # (renomeado à mão, copiado de outra pasta): não são estes autos.
        grau_do_pdf = reg.get("grau_do_pdf") or ""
        if grau_do_pdf and grau_do_pdf != (reg.get("grau") or "1g"):
            return (f"o PDF na pasta é do outro grau (o manifesto de paginação dele diz "
                    f"{tribunais.rotulo_do_grau(grau_do_pdf)})")
        if getattr(self.opcoes, "rebaixar_incompletos", False):
            if reg["incompleto"]:
                o_que = "documentos" if sistema == "eproc" else "folhas"
                return f"já estava na pasta, mas com {o_que} ausentes ({reg['incompleto']})"
            if not reg["paginacao"]:
                return ("já estava na pasta, mas sem o manifesto de paginação (PDF de versão "
                        "anterior)")
            if reg["paginacao"].get("garantida") is False:
                return ("já estava na pasta, mas com a paginação não garantida (o PDF foi "
                        "alterado depois do download?)")
        # PDF do e-SAJ de versão anterior à 1.0.2, cujo download deixou sinal
        # de numeração deslocada (folhas ausentes, montagem peça a peça, índice
        # que não fechava): a página do PDF pode não ser a folha. O registro
        # (meta) só existe a partir da 1.0.2, que já grava página = folha.
        linha = reg["linha"]
        if reg["manifesto"] or reg["meta"] or linha is None or sistema != "esaj":
            return ""
        detalhe = (linha.get("detalhe") or "").lower()
        if (linha.get("incompleto") or "").strip() or "peça a peça" in detalhe \
                or "confira" in detalhe:
            return "PDF de versão anterior com numeração possivelmente deslocada"
        return ""

    def _ja_estava(self, r: ResultadoProcesso, n: Numero, existente: Path, reg: dict,
                   motivo: str) -> None:
        """O processo já está na pasta: JA_BAIXADO, com o registro de antes."""
        r.situacao = JA_BAIXADO
        r.causa = ""
        r.arquivo = str(existente)
        r.paginas = _paginas(existente)
        r.sigiloso = _mesma_pasta(existente.parent, self.pasta_sigilosos) or bool(motivo)
        if self._sigilo_so_do_relatorio(n, motivo):
            self._lembrar_sigilo(n)      # lote de antes desta regra, com o sigiloso no acervo
        if reg["sistema"]:
            r.sistema = reg["sistema"]
        r.documentos = reg["documentos"] or r.documentos
        r.incompleto = reg["incompleto"]
        r.paginacao = dict(reg["paginacao"])
        sem_registro = not (reg["manifesto"] or reg["meta"] or reg["linha"] is not None)
        # r.detalhe: o que _item já disse do sigilo (o originário que herda da origem)
        r.detalhe = _juntar(JA_ESTAVA, reg["detalhe"], SEM_REGISTRO if sem_registro else "",
                            r.detalhe)
        if motivo and motivo == self._pelo_recurso_interno(n) \
                and f"tratado como sigiloso: {motivo}" not in r.detalhe:
            # o principal apurado nesta rodada pelo recurso interno dele
            r.detalhe = _juntar(r.detalhe, f"tratado como sigiloso: {motivo}")
        if r.sigiloso and self._separar(n):
            # sigiloso que ficou no acervo (separação que falhou numa
            # versão anterior, ou cópia de quando era público; com a
            # separação desligada, o sigilo que não foi para o registro)
            self._retirar_do_acervo(r, n)
            if not self.opcoes.separar_sigilosos \
                    and _mesma_pasta(Path(r.arquivo).parent, self.pasta_sigilosos):
                r.detalhe = _juntar(r.detalhe, SEM_REGISTRO_DO_SIGILO)
        self._concluir(r)

    def _registrar_download(self, r: ResultadoProcesso) -> None:
        """Depois de guardado: a paginação (o manifesto que o portal gravou
        no PDF) e o registro do download ao lado do PDF. Nunca falha o item."""
        try:
            if not r.paginacao:
                r.paginacao = essencial_da_paginacao(paginacao.ler_do_pdf(Path(r.arquivo)))
            gravar_meta(r)
        except Exception:
            log.debug("registro do download não gravado", exc_info=True)

    def _no_provisorio(self, erro: OSError) -> bool:
        """O arquivo do erro está na área provisória? (sem nome: considera-se que sim)"""
        nomes = [x for x in (getattr(erro, "filename", None), getattr(erro, "filename2", None))
                 if x]
        if not nomes:
            return True
        return any(_dentro(Path(str(x)), self.provisorio) for x in nomes)

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
        de_novo = ""
        if self.opcoes.pular_baixados:
            existente = self._ja_baixado(n)
            if existente is not None:
                reg = self._registro_anterior(n, existente)
                de_novo = self._baixar_de_novo(reg, portal)
                if not de_novo:
                    if not motivo and r.grau == "2g" and _dentro(existente, self.destino):
                        # O originário do 2º grau que já estava na pasta herda
                        # o sigilo da ação de origem já sabida sigilosa, como o
                        # baixado agora (abaixo): a capa dele está ao lado do PDF.
                        origem = self._origem_sigilosa(n, existente)
                        if origem:
                            motivo = f"o processo de origem {origem} é sigiloso"
                            r.detalhe = _juntar(r.detalhe, f"tratado como sigiloso: {motivo}")
                            log.warning("originário %s tratado como sigiloso: o processo de "
                                        "origem %s é sigiloso", n.formatado, origem)
                            self._lembrar_sigilo(n)
                    self._ja_estava(r, n, existente, reg, motivo)
                    return False, False
                log.info("    %s; baixando de novo.", de_novo)

        provisorio = self._area_provisoria(n)
        # O portal grava os autos, a capa e as gravações pelo nome do destino
        # (destino.stem): no 2º grau, "<número> (2G).pdf".
        alvo = provisorio / f"{self._nome_dos_autos(n)}.pdf"
        senha = senha_de(n, self.senhas)
        inicio = time.monotonic()
        tentativas = max(1, int(self.opcoes.tentativas))
        tentativa = 0
        relogins = 0
        ultimo: Exception | None = None
        causa_ultimo = ""
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
                ultimo, causa_ultimo = erro, CAUSA_SESSAO
                if relogins >= MAX_RELOGINS:
                    break
                relogins += 1
                tentativa -= 1           # relogin não gasta tentativa
                log.info("    a sessão caiu (%s); entrando de novo...", str(erro)[:120])
                self._evento("sessao_caiu", sistema=r.sistema, tribunal=r.tribunal,
                             ordem=r.ordem, **_do_grau(r.grau))
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
                self._area_provisoria(n)       # a próxima tentativa começa do zero
                if not self._no_provisorio(erro):
                    # Arquivo fora da área provisória, que o usuário pode ter
                    # aberto: repetir não adianta enquanto ele não o fechar.
                    ultimo = PermissionError(
                        f"não consegui gravar {alvo.name}: o arquivo está aberto em outro "
                        "programa (leitor de PDF?). Feche-o e baixe de novo.")
                    ultimo.__cause__ = erro
                    causa_ultimo = CAUSA_PDF_ABERTO
                    self._limpar_parcial(n)
                    break
                # Na área provisória (fora do acervo, que ninguém abre), quem
                # segura o PDF recém-gravado é o antivírus ou o indexador, por
                # alguns segundos: é passageiro - tenta de novo, com espera.
                # Sem nome de arquivo (um soquete negado pelo firewall, por
                # exemplo, WinError 10013), a frase não pode culpar o PDF.
                tem_arquivo = bool(getattr(erro, "filename", None)
                                   or getattr(erro, "filename2", None))
                ultimo = PermissionError(
                    "o PDF recém-baixado ficou preso por outro programa (antivírus ou "
                    "indexador do Windows) na pasta provisória" if tem_arquivo else
                    "o Windows negou o acesso (firewall ou antivírus?)")
                ultimo.__cause__ = erro
                causa_ultimo = CAUSA_FALHA
                if tentativa >= tentativas:
                    break
                log.warning("    o PDF ficou preso por outro programa (%s); tentando de novo "
                            "(%d/%d)...", str(erro)[:120], tentativa + 1, tentativas)
                self.ctx.status(f"{n.formatado}: o PDF ficou preso por outro programa; tentando "
                                f"de novo ({tentativa + 1}/{tentativas})...")
                self._dormir(min(30.0, ESPERA_ENTRE_TENTATIVAS_S * tentativa))
            except Exception as erro:
                ultimo, causa_ultimo = erro, ""
                self._area_provisoria(n)       # a próxima tentativa começa do zero
                if tentativa >= tentativas:
                    break
                fora_agora = isinstance(erro, PortalIndisponivel) or portal_fora(str(erro))
                if fora_agora and self._seguidos_fora >= MAX_INDISPONIVEL_SEGUIDOS - 1:
                    # o grupo vai ser encerrado com este: insistir só gastaria
                    # a espera crescente com o portal fora
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
            texto = str(ultimo) if ultimo else "falhou sem explicação"
            fora = isinstance(ultimo, PortalIndisponivel) or (
                ultimo is not None and not causa_ultimo and portal_fora(texto))
            if causa_ultimo:
                r.causa = causa_ultimo
            elif isinstance(ultimo, NavegadorOcupado):
                r.causa = CAUSA_NAVEGADOR_OCUPADO
            elif fora:
                r.causa = CAUSA_PORTAL
                if not isinstance(ultimo, PortalIndisponivel):
                    # 'Page.goto: net::ERR_INTERNET_DISCONNECTED at https://...'
                    # vira a frase que o usuário entende (e sem a URL da sessão)
                    texto = f"portal indisponível: {_explicar_erro(texto)}"
            else:
                r.causa = CAUSA_FALHA
            r.detalhe = texto
            log.error("    %s: %s", n.formatado, r.detalhe)
        else:
            r.absorver(res)
            r.causa = getattr(res, "causa", "") or ""
            if r.situacao == OK and not _pdf_valido(alvo):
                r.situacao = ERRO
                r.causa = CAUSA_PDF_INVALIDO
                r.detalhe = "o portal informou sucesso, mas o PDF não foi gravado"
            if r.situacao not in (OK, JA_BAIXADO, NAO_ENCONTRADO, SEM_ACESSO,
                                  SIGILOSO_SEM_SENHA, NAO_SUPORTADO, ERRO, CANCELADO):
                r.situacao, r.detalhe = ERRO, f"situação desconhecida: {res.situacao!r}"
                r.causa = CAUSA_INESPERADO
            elif r.situacao == ERRO and not r.causa:
                r.causa = CAUSA_FALHA
        # Uma vez sigiloso, sempre sigiloso: o que o portal apurou numa
        # tentativa que falhou, ou um download anterior, vale para esta.
        apurados = getattr(portal, "sigilosos_apurados", None) or ()
        if n.nome_arquivo in apurados:
            r.sigiloso = True
        if n.e_dependente and n.principal in apurados:
            # a consulta do recurso interno abriu a página do principal em segredo
            self._principal_apurado(r, n)
        if r.situacao == OK and r.grau == "2g" and not r.sigiloso and not motivo:
            # O originário do 2º grau (HC, MS, AI de órgão 0000) tem número
            # próprio, mas traz cópia da ação de origem: se ela já se sabe
            # sigilosa, ele também o é (o lado seguro, como o incidente, que
            # herda do principal). Antes de os autos irem para o lote.
            origem = self._origem_sigilosa(n, alvo)
            if origem:
                r.sigiloso = True
                r.detalhe = _juntar(r.detalhe, f"tratado como sigiloso: o processo de origem "
                                               f"{origem} é sigiloso")
                log.warning("originário %s tratado como sigiloso: o processo de origem %s é "
                            "sigiloso", n.formatado, origem)
        if r.sigiloso or self._sigilo_so_do_relatorio(n, motivo):
            # O sigilo que o portal mostrou (agora ou numa rodada anterior
            # deste lote) passa a valer na regra única ANTES de o PDF ir para
            # o lote: com a separação desligada, ele fica no acervo. O que
            # veio só da pasta ou da pauta não vai para o registro do
            # download: elas mesmas já o dizem.
            self._lembrar_sigilo(n)
        if not r.sigiloso and motivo:
            r.sigiloso = True
            if r.situacao == OK:
                r.detalhe = _juntar(r.detalhe, f"tratado como sigiloso: {motivo}")
        guardado = False
        try:
            if r.situacao == OK:
                self._guardar(r, n, provisorio)
                guardado = bool(r.arquivo) and not _dentro(r.arquivo, self.provisorio) \
                    and Path(r.arquivo).is_file()
            elif r.sigiloso and self._separar(n):
                self._retirar_do_acervo(r, n)
            elif r.sigiloso:                   # separação desligada, como em _guardar
                self._herdar_originarios(r, n, levar=False)
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
        if de_novo:
            # Sem OK, o relatório leva adiante o que se sabia do PDF anterior
            # (_pdf_que_fica): a próxima rodada tenta de novo.
            r.detalhe = _juntar(r.detalhe, f"baixado de novo: {de_novo}" if r.situacao == OK
                                else PDF_ANTERIOR)
        consulta = {"sistema": r.sistema, "situacao": r.situacao}
        if r.causa:
            consulta["causa"] = r.causa
        consulta.update(_do_grau(r.grau))
        r.consultas.append(consulta)
        if guardado:
            # a paginação do PDF e o registro do download, ao lado dele
            self._registrar_download(r)
        r.segundos = round(time.monotonic() - inicio, 1)
        self._concluir(r)
        return True, fora

    def _origem_sigilosa(self, n: Numero, pdf: Path) -> str:
        """O processo de origem dos autos do 2º grau recém-baixados que o
        programa já sabe sigiloso (o número formatado), ou "" se nenhum.

        A origem sai da capa do 2º grau que o portal gravou ao lado do PDF
        (_controle/<chave dos autos>_capa.json, "Números de 1ª Instância": a
        lista "numeros_1a_instancia" do nível de cima do arquivo, com o
        "numero" de cada um no formato CNJ - o e-SAJ; o eProc não traz essa
        lista nesta versão), e o sigilo, da mesma regra que vale para o
        próprio processo (_motivo_sigilo: relatório e capa deste lote, pasta
        dos sigilosos, pauta, registro do download)."""
        arquivo = Path(pdf).parent / "_controle" / f"{Path(pdf).stem}_capa.json"
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        lista = dados.get("numeros_1a_instancia") if isinstance(dados, dict) else None
        if not isinstance(lista, list):
            return ""
        for item in lista:
            texto = item.get("numero") if isinstance(item, dict) else item
            try:
                origem = cnj.ler(str(texto or ""))
            except cnj.NumeroInvalido:
                continue
            if origem.nome_arquivo == n.nome_arquivo:
                continue                 # a apelação: o próprio processo, já conferido
            try:
                if self._motivo_sigilo(origem):
                    return origem.formatado
            except Exception:            # a regra nunca derruba o item
                log.debug("sigilo da origem %s não conferido", origem.formatado, exc_info=True)
        return ""

    def _principal_apurado(self, r: ResultadoProcesso, n: Numero) -> None:
        """A consulta do recurso interno 'n' (/50000) abriu a página do
        processo principal em segredo de justiça, e o portal o pôs também nos
        sigilosos_apurados: o sigilo é dele, e os autos dele baixados quando
        era público (nos dois graus, deste lote ou de outro) saem do acervo
        como os de qualquer sigiloso - pelo recurso interno, a retirada não os
        alcança (o principal não herda do incidente). O sigilo vai para o
        registro do download e para o que o lote já sabe (a linha dele sai
        mascarada; pedido depois, ele nasce sigiloso, com esse porquê). O
        item dele nesta rodada passa a dizê-lo; sem item, o detalhe de 'r'
        diz o que saiu e o que ficou."""
        p = cnj.ler(n.principal)
        dele = next((o for o, m in zip(self.itens, self.numeros)
                     if cnj.chave(m) == cnj.chave(p)), None)
        if dele is not None and dele.sigiloso:
            return                       # o item dele já se apurou sigiloso
        self._lembrar_sigilo(p)
        self._sigilosos_sabidos.add(p.nome_arquivo)
        self._apurados_pelo_recurso.setdefault(p.nome_arquivo, n.formatado)
        porque = f"tratado como sigiloso: {self._pelo_recurso_interno(p)}"
        if dele is not None and dele.situacao in (OK, JA_BAIXADO) and dele.arquivo \
                and _dentro(dele.arquivo, self.destino):
            dele.sigiloso = True
            dele.detalhe = _juntar(dele.detalhe, porque)
            if self._separar(p):
                self._retirar_do_acervo(dele, p)
                if not self.opcoes.separar_sigilosos:
                    dele.detalhe = _juntar(dele.detalhe, SEM_REGISTRO_DO_SIGILO)
            else:
                self._herdar_originarios(dele, p, levar=False)
            self._publicar(dele)
            return
        if dele is not None and dele.situacao:
            # O item dele já terminou sem PDF no lote (falha, sem acesso):
            # passa a sigiloso também - o JSON do lote não pode dizer
            # público o que o registro e o relatório já dão como sigiloso.
            # As cópias de rodadas anteriores saem abaixo.
            dele.sigiloso = True
            dele.detalhe = _juntar(dele.detalhe, porque)
            self._publicar(dele)
        if not self._separar(p):
            self._herdar_originarios(r, p, levar=False)
            return
        provisorio = ResultadoProcesso(ordem=0, numero=p.formatado, tribunal=r.tribunal,
                                       sistema=r.sistema, grau=r.grau)
        ret = self._retirar_do_acervo(provisorio, p)
        # O que a retirada disse (outros arquivos, transcrições, o que ficou
        # preso); o "levado agora" dos autos deste lote entra na conta abaixo.
        resto = [x for x in provisorio.detalhe.split("; ")
                 if x and x != "levado agora para a pasta de sigilosos"]
        if not (ret.autos or resto):
            return                       # nada dele havia no acervo
        texto = f"o processo principal {p.formatado} passa a ser tratado como sigiloso"
        if ret.autos:
            # Os autos dele (nos dois graus) e, à parte, os dos incidentes
            # dele, que a retirada leva junto
            proprios = sum(chave_do_nome(k.name) == p.nome_arquivo for k in ret.autos)
            incidentes = len(ret.autos) - proprios
            if proprios:
                texto += (": 1 cópia" if proprios == 1 else f": {proprios} cópias") + \
                    " dos autos dele" + (f" e {incidentes} dos incidentes dele" if incidentes
                                         else "")
            else:
                texto += (": 1 cópia" if incidentes == 1 else f": {incidentes} cópias") + \
                    " dos autos dos incidentes dele"
            texto += (" levada" if len(ret.autos) == 1 else " levadas") + \
                " para a pasta de sigilosos"
        if not self.opcoes.separar_sigilosos:
            texto = _juntar(texto, SEM_REGISTRO_DO_SIGILO)
        r.detalhe = _juntar(r.detalhe, texto, *resto)

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
    ``opcoes.grau`` é o grau do lote: cada processo vai ao grau que
    cnj.grau_do_processo lhe dá (o número, senão o do lote), e o Tribunal que
    as fábricas recebem já está nesse grau (Tribunal.no_grau); cada
    ResultadoProcesso sai com o ``grau`` dele.
    """
    lote = _Lote(numeros, destino, opcoes, ctx, senhas, cofre,
                 fabrica_portal, fabrica_navegador, cfg)
    return lote.executar()
