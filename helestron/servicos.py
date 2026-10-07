"""O ÚNICO ponto em que a API do servidor local chama o download, a
transcrição, a verificação e as funções de compartilhamento.

Por que um módulo só: os tratadores da API (helestron.servidor) não importam
helestron.download.motor, helestron.transcricao.* nem helestron.verificar
diretamente. Se uma assinatura mudar, ou se um pacote faltar na instalação,
o ajuste é aqui - e a interface recebe uma exceção ComponenteAusente com a
frase pronta para o usuário ("reinstale o Helestron"), em vez de um
ImportError cru.

Tudo é importado DENTRO das funções: a janela abre em menos de 2 s mesmo
sem faster-whisper, Playwright ou PyMuPDF. Quase tudo aqui é lento (disco,
áudio, rede) e deve ser chamado de uma thread de trabalho (helestron.tarefas)
- nunca da thread que atende os pedidos da página, que ficaria presa.
"""

from __future__ import annotations

import csv
import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .nucleo import caminhos, cnj, sistema

log = logging.getLogger("servicos")

DICA_INSTALAR = ("Instale o Helestron de novo com o Helestron-Setup: ele conserta a instalação "
                 "sem apagar os seus dados.")


class ComponenteAusente(RuntimeError):
    """Parte do programa não está instalada; a mensagem diz o que fazer."""


def _ausente(erro: ImportError, funcao: str) -> ComponenteAusente:
    nome = getattr(erro, "name", "") or str(erro)
    return ComponenteAusente(
        f"O componente de {funcao} não está instalado ({nome}). {DICA_INSTALAR}")


# =================================================================== download
def opcoes_download(cfg):
    from .download.modelos import OpcoesDownload

    return OpcoesDownload.de_config(cfg)


def baixar_lote(numeros, destino: Path, opcoes, ctx, senhas: dict | None, cofre, cfg):
    """Roda o lote inteiro (bloqueia). Devolve o ResumoLote do motor."""
    try:
        from .download import motor
    except ImportError as erro:
        raise _ausente(erro, "download de processos") from erro
    return motor.executar(numeros, Path(destino), opcoes, ctx, senhas=senhas, cofre=cofre, cfg=cfg)


def testar_login(tribunal, opcoes, ctx, credenciais: tuple[str, str] | None) -> None:
    """Abre o navegador do portal e faz só o login (bloqueia).

    Usa as mesmas fábricas do motor: o teste passa exatamente pelo caminho
    que o download vai usar.
    """
    try:
        from .download import motor
    except ImportError as erro:
        raise _ausente(erro, "download de processos") from erro
    nav = motor.fabrica_navegador_padrao(tribunal, opcoes)
    with nav:
        portal = motor.fabrica_portal_padrao(nav, tribunal, opcoes, ctx, credenciais)
        portal.entrar()


def cofre():
    from .nucleo.cofre_senhas import CofreSenhas

    return CofreSenhas(caminhos.ARQUIVO_SENHAS)


class CofreMisto:
    """O cofre de senhas, mais as credenciais digitadas agora sem "Lembrar".

    O motor só chama obter(portal); assim a senha que o usuário não quis
    guardar vale para este lote e não vai para o disco.
    """

    def __init__(self, base, extras: dict[str, tuple[str, str]] | None = None):
        self.base = base
        self.extras = dict(extras or {})

    def obter(self, portal: str) -> tuple[str, str]:
        if portal in self.extras:
            return self.extras[portal]
        try:
            return self.base.obter(portal) if self.base is not None else ("", "")
        except Exception:
            return "", ""


@dataclass
class InfoLote:
    nome: str
    pasta: Path
    relatorio: Path
    quando: datetime
    total: int = 0
    baixados: int = 0
    falhas: int = 0
    situacoes: dict[str, int] = field(default_factory=dict)


_FALHAS = {"ERRO", "NAO_ENCONTRADO", "SEM_ACESSO", "NAO_SUPORTADO", "SIGILOSO_SEM_SENHA"}


def ler_relatorio(relatorio: Path) -> InfoLote | None:
    """Resumo de um _controle/relatorio.csv (gravado pelo motor).

    O magistrado pode abrir o relatório no Excel e salvá-lo: o Excel grava
    o "CSV (separado por vírgulas)" em ANSI (cp1252), e a leitura só em
    UTF-8 levantava UnicodeDecodeError - que derrubava a tela inicial
    inteira. Arquivo ilegível vale como ausente (None).
    """
    try:
        dados = relatorio.read_bytes()
        quando = datetime.fromtimestamp(relatorio.stat().st_mtime)
    except OSError:
        return None
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = dados.decode("cp1252", errors="replace")
    pasta = relatorio.parent.parent
    info = InfoLote(nome=pasta.name, pasta=pasta, relatorio=relatorio, quando=quando)
    try:
        for linha in csv.DictReader(texto.splitlines(), delimiter=";"):
            situacao = (linha.get("situacao") or "").strip().upper()
            info.total += 1
            info.situacoes[situacao] = info.situacoes.get(situacao, 0) + 1
            if situacao in ("OK", "JA_BAIXADO"):
                info.baixados += 1
            elif situacao in _FALHAS:
                info.falhas += 1
    except (csv.Error, ValueError, AttributeError) as erro:
        log.warning("relatório ilegível (%s): %s", relatorio, erro)
        return None
    return info


def ultimos_lotes(cfg, limite: int = 5) -> list[InfoLote]:
    pasta = cfg.pasta_processos
    try:
        relatorios = list(pasta.glob("*/_controle/relatorio.csv"))
    except OSError:
        return []
    relatorios.sort(key=lambda p: _mtime(p), reverse=True)
    saida = []
    for r in relatorios[:limite]:
        info = ler_relatorio(r)
        if info is not None:
            saida.append(info)
    return saida


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


# ================================================================ transcrição
def nova_sessao(numero, cfg, eventos: Callable[[str, object], None], *, tipo: str = "",
                participantes: dict[str, str] | None = None, falante: str = "",
                sigiloso: bool = False, dispositivo: int | str | None = None):
    """Cria (sem iniciar) a sessão ao vivo. iniciar() e encerrar() bloqueiam:
    chame-os de uma thread de trabalho. 'sigiloso': documento, gravação e
    diário vão para a pasta dos sigilosos, fora do acervo. 'dispositivo':
    o microfone escolhido na tela (None = o da configuração)."""
    try:
        from .transcricao.ao_vivo import SessaoAoVivo
    except ImportError as erro:
        raise _ausente(erro, "transcrição") from erro
    # "" é escolha da tela ("Padrão do Windows") e vai explícito: sem isso, a
    # sessão caía no microfone do config.ini, que a tela não mostrava.
    extra = {} if dispositivo is None else {"dispositivo": dispositivo}
    return SessaoAoVivo(numero, cfg, eventos, tipo=tipo, participantes=participantes,
                        falante=falante, sigiloso=sigiloso, **extra)


def conferir_microfone(dispositivo):
    """O microfone escolhido (nome, número ou "" = padrão do Windows), conferido
    agora: nome que não existe mais levanta MicrofoneNaoEncontrado com a frase
    para o usuário, em vez de gravar em silêncio por outro aparelho."""
    try:
        from .transcricao import microfone
    except ImportError as erro:
        raise _ausente(erro, "microfone") from erro
    return microfone.conferir(dispositivo)


def processo_sigiloso(cfg, numero) -> bool:
    """O processo já se sabe sigiloso pelos arquivos: os autos estão na pasta de
    sigilosos, ou uma transcrição (ou gravação) dele já foi para lá. Pré-marca a
    caixa "Processo em segredo de justiça" das transcrições. Nunca levanta."""
    if numero is None:
        return False
    try:
        from .transcricao.documento import processo_sigiloso as _sigiloso

        return bool(_sigiloso(cfg, numero))
    except Exception as erro:
        log.debug("não consegui conferir se %s é sigiloso: %s", numero, erro)
        return False


def na_pasta_dos_sigilosos(cfg, caminho) -> bool:
    """O arquivo está dentro da pasta de sigilosos (fora do acervo)?"""
    try:
        pasta = Path(cfg.pasta_sigilosos).resolve()
        return Path(caminho).resolve().is_relative_to(pasta)
    except Exception:
        return False


def copia_na_pasta_dos_sigilosos(cfg, nome: str, tamanho: int | None) -> bool:
    """Há na pasta de sigilosos um arquivo com este nome (e este tamanho)?

    É como se reconhece, no envio pela página (modos Edge e navegador, sem o
    caminho real), a gravação guardada na pasta dos sigilosos: o servidor só
    recebe uma cópia temporária. Nunca levanta."""
    nome = Path(str(nome or "")).name
    if not nome:
        return False
    try:
        import glob as _glob

        for p in Path(cfg.pasta_sigilosos).rglob(_glob.escape(nome)):
            try:
                if p.is_file() and (tamanho is None or p.stat().st_size == tamanho):
                    return True
            except OSError:
                continue
    except Exception as erro:
        log.debug("não consegui procurar %s na pasta de sigilosos: %s", nome, erro)
    return False


def recuperaveis(cfg) -> list[Path]:
    try:
        from .transcricao import ao_vivo
    except ImportError:
        return []
    try:
        return list(ao_vivo.recuperaveis(cfg))
    except Exception as erro:
        log.warning("não consegui procurar transcrições interrompidas: %s", erro)
        return []


def recuperar(jsonl: Path) -> Path:
    try:
        from .transcricao import ao_vivo
    except ImportError as erro:
        raise _ausente(erro, "transcrição") from erro
    return ao_vivo.recuperar(jsonl)


def listar_microfones() -> list:
    """Entradas de áudio (Entrada: indice, nome, padrao, taxa). Lenta: PortAudio."""
    try:
        from .transcricao import microfone
    except ImportError as erro:
        raise _ausente(erro, "microfone") from erro
    return list(microfone.listar_entradas())


def abrir_teste_microfone(dispositivo, ao_nivel: Callable[[float], None],
                          ao_aviso: Callable[[str], None] | None = None):
    """Liga o microfone só para medir o nível (botão Testar). Devolve o objeto
    de captura, que a tela desliga com parar()."""
    try:
        from .transcricao import microfone
    except ImportError as erro:
        raise _ausente(erro, "microfone") from erro
    captura = microfone.Captura(dispositivo if dispositivo not in ("", None) else None,
                                lambda _bloco: None, ao_nivel, ao_aviso)
    captura.iniciar()
    return captura


def modelos_disponiveis() -> list[dict]:
    """[{'nome', 'mb', 'instalado', 'descricao'...}] do catálogo Whisper."""
    try:
        from .transcricao import modelos
    except ImportError:
        return []
    try:
        return modelos.listar()
    except Exception as erro:
        log.debug("catálogo de modelos indisponível: %s", erro)
        return []


def modelo_instalado(nome: str) -> bool:
    try:
        from .transcricao import modelos

        return bool(modelos.instalado(nome))
    except Exception:
        return False


def baixar_modelo(nome: str, progresso: Callable[[float, str], None] | None = None) -> Path:
    try:
        from .transcricao import modelos
    except ImportError as erro:
        raise _ausente(erro, "transcrição") from erro
    return modelos.baixar(nome, progresso)


def transcrever_gravacao(origem: Path, numero, cfg, progresso, cancelado, *,
                         rotulos_manuais=None, destino: Path | None = None, tipo: str = "",
                         participantes: dict | None = None, sigiloso: bool = False,
                         gravacao: str = "", data: datetime | None = None,
                         meta=None) -> Path:
    """Transcreve a gravação (bloqueia). 'gravacao' e 'data': o nome e a data
    do arquivo do usuário, quando 'origem' é só a cópia temporária do envio
    pela página - senão a ficha diria "envio-3d29….wav" e a data de hoje.

    'meta': a ficha da audiência (a MetaAudiencia da sessão ao vivo, na
    revisão pelo "Revisar"). Sem ela, a revisão perdia o início e o término
    e punha na Data a da modificação do FLAC (o dia seguinte, numa audiência
    que passa da meia-noite), ao contrário da revisão automática ao
    encerrar. Vai uma cópia (o motor completa a ficha no lugar); a ficha de
    uma sessão ao vivo vira a da revisão, sem a observação da versão ao vivo;
    'tipo', 'gravacao' e 'data' informados prevalecem, e 'participantes' se
    somam aos da ficha.
    """
    try:
        from .transcricao import arquivo
    except ImportError as erro:
        raise _ausente(erro, "transcrição de gravações") from erro
    if meta is not None:
        meta = _ficha_da_revisao(meta, tipo=tipo, participantes=participantes,
                                 gravacao=gravacao, data=data)
    elif tipo or participantes or gravacao or data is not None:
        try:
            from .transcricao.documento import MetaAudiencia

            meta = MetaAudiencia(numero=numero.formatado if numero else "", tipo=tipo,
                                 participantes=dict(participantes or {}), data=data,
                                 gravacao=gravacao)
        except Exception:
            meta = None
    extra = {"meta": meta} if meta is not None else {}
    return arquivo.transcrever_arquivo(origem, numero, cfg, progresso, cancelado,
                                       rotulos_manuais=rotulos_manuais, destino=destino,
                                       sigiloso=sigiloso, **extra)


def _ficha_da_revisao(meta, *, tipo: str = "", participantes: dict | None = None,
                      gravacao: str = "", data: datetime | None = None):
    """Cópia da ficha recebida, pronta para a transcrição da gravação: a da
    sessão ao vivo vira a da revisão, como em SessaoAoVivo._refinar."""
    from dataclasses import replace

    ao_vivo = getattr(meta, "origem", "") == "ao vivo"
    copia = replace(meta, participantes=dict(getattr(meta, "participantes", None) or {}),
                    origem="revisão" if ao_vivo else meta.origem,
                    observacao="" if ao_vivo else meta.observacao)
    if tipo:
        copia.tipo = tipo
    if participantes:   # somados aos da ficha (o mesmo papel: vale o informado agora)
        copia.participantes.update(participantes)
    if gravacao:
        copia.gravacao = gravacao
    if data is not None:
        copia.data = data
    return copia


def excecao_cancelado(erro: BaseException) -> bool:
    """O erro é o "Cancelado" de algum módulo (o usuário pediu para parar)?"""
    return type(erro).__name__ == "Cancelado"


def falantes_situacao() -> tuple[bool, str]:
    """(disponível, frase) da separação automática de falantes."""
    try:
        from .transcricao import falantes
    except ImportError:
        return False, "não instalada"
    try:
        return bool(falantes.disponivel()), falantes.situacao()
    except Exception as erro:
        return False, f"indisponível ({erro})"


def falantes_estado() -> dict:
    """A separação de falantes para a tela de Ajustes › Transcrição.

    {disponivel, situacao, biblioteca, modelos, embutidos, tamanho_mb}: a
    biblioteca (sherpa-onnx) vem no instalador; os modelos de voz também,
    salvo numa construção sem eles - aí a tela oferece baixá-los (uma vez,
    do GitHub, para a pasta de dados).
    """
    estado = {"disponivel": False, "situacao": "não instalada", "biblioteca": False,
              "modelos": False, "embutidos": False, "tamanho_mb": 47}
    try:
        from .transcricao import falantes
    except ImportError:
        return estado
    try:
        biblioteca = bool(falantes.biblioteca_presente())
        modelos = bool(falantes.modelos_presentes())
        embutidos = modelos and Path(falantes.modelo_embedding()).is_relative_to(
            Path(falantes.PASTA_EMBUTIDA))
        estado.update(disponivel=biblioteca and modelos, situacao=falantes.situacao(),
                      biblioteca=biblioteca, modelos=modelos, embutidos=bool(embutidos),
                      tamanho_mb=int(getattr(falantes, "TAMANHO_MB", 47)))
    except Exception as erro:
        estado["situacao"] = f"indisponível ({erro})"
    return estado


def instalar_falantes(progresso: Callable[[float, str], None] | None = None,
                      cancelado: Callable[[], bool] | None = None) -> None:
    """Baixa os modelos de voz que faltarem (a biblioteca vem no instalador)."""
    try:
        from .transcricao import falantes
    except ImportError as erro:
        raise _ausente(erro, "separação de falantes") from erro
    falantes.instalar(progresso, cancelado=cancelado)


def numero_no_nome(caminho: Path):
    """O número CNJ do arquivo: no nome (inclusive o dependente "-NN") ou na
    pasta (as mídias baixadas ficam em _controle/midias/<número>/)."""
    try:
        from .transcricao import arquivo

        return arquivo.numero_do_caminho(Path(caminho))
    except (ImportError, AttributeError):
        pass
    # Sem o módulo da transcrição, a mesma leitura daqui: cnj.ler perderia o
    # "-NN" do incidente ("...0001-01.docx" viraria o principal), e a
    # transcrição do incidente seria tratada como a do processo principal.
    caminho = Path(caminho)
    for nome in (caminho.name, caminho.parent.name):
        try:
            return cnj.ler_nome_arquivo(nome)
        except cnj.NumeroInvalido:
            continue
    return None


def _docx_da_pasta(pasta: Path) -> list[Path]:
    try:
        return [p for p in Path(pasta).glob("*.docx")
                if not p.name.startswith("~$") and not p.name.endswith((".parcial", ".tmp"))]
    except OSError:
        return []


def transcricoes_recentes(cfg, limite: int = 5, incluir_sigilosas: bool = False) -> list[Path]:
    """As transcrições mais recentes, da mais nova para a mais antiga.

    'incluir_sigilosas': também as da pasta dos sigilosos (fora do acervo) -
    a lista da tela Audiências mostra as duas, com o selo do sigilo; o
    resumo do acervo, só as do acervo.
    """
    docs = _docx_da_pasta(cfg.pasta_transcricoes)
    if incluir_sigilosas:
        try:
            from .transcricao.documento import pastas_das_transcricoes

            pastas = pastas_das_transcricoes(cfg)[1:]
        except Exception:
            pastas = [Path(cfg.pasta_sigilosos) / "Transcricoes"]
        for pasta in pastas:
            docs += _docx_da_pasta(pasta)
    docs.sort(key=_mtime, reverse=True)
    return docs[:limite]


# ================================================================ verificação
@dataclass
class ItemVerificacao:
    nome: str
    situacao: str          # ok | aviso | falha
    detalhe: str = ""
    obrigatorio: bool = False


def verificar_instalacao(completo: bool = False, cfg=None, ao_item=None) -> list:
    """Itens de helestron.verificar (nome, situacao, detalhe, obrigatorio, acao).

    Se o módulo não puder ser importado (instalação quebrada), faz a
    conferência mínima daqui mesmo: os pacotes de cada função.
    """
    try:
        from . import verificar
    except ImportError:
        return _verificacao_minima()
    return list(verificar.verificar(completo=completo, cfg=cfg, ao_item=ao_item))


PACOTES = (
    ("playwright", "download de processos", True),
    ("pymupdf", "montagem dos PDFs", True),
    ("openpyxl", "leitura de planilhas do Excel", True),
    ("docx", "documentos do Word", True),
    ("faster_whisper", "transcrição de audiências", True),
    ("sounddevice", "microfone", True),
    ("soundfile", "gravação do áudio", True),
    ("PIL", "imagens e capturas de tela", False),
)


def _pacote_presente(nome: str) -> bool:
    try:
        if nome == "pymupdf":
            return bool(importlib.util.find_spec("pymupdf") or importlib.util.find_spec("fitz"))
        return importlib.util.find_spec(nome) is not None
    except (ImportError, ValueError):
        return False


def _verificacao_minima() -> list[ItemVerificacao]:
    itens = [ItemVerificacao("Python", "ok", sys.version.split()[0], True)]
    for nome, funcao, obrigatorio in PACOTES:
        ok = _pacote_presente(nome)
        itens.append(ItemVerificacao(f"Componente: {funcao}", "ok" if ok else
                                     ("falha" if obrigatorio else "aviso"),
                                     nome if ok else f"{nome} ausente. {DICA_INSTALAR}",
                                     obrigatorio))
    return itens


@dataclass
class Pendencia:
    """Algo que falta, para os "Primeiros passos" da tela Início.

    'acao' é a rota da interface que resolve ("ajustes#pastas",
    "ajustes#transcricao"...): a tela vira o item da lista num atalho.
    """
    chave: str             # "pastas" | "pacotes" | "modelo" | ...
    titulo: str
    mensagem: str
    acao: str = ""

    @property
    def texto(self) -> str:          # nome antigo do campo
        return self.mensagem

    def como_dict(self) -> dict:
        return {"chave": self.chave, "titulo": self.titulo, "mensagem": self.mensagem,
                "acao": self.acao}


def pendencias(cfg) -> list[Pendencia]:
    """O que falta para as funções. Rápido (só procura arquivos), mas chame
    de uma thread que possa esperar um instante (disco de rede)."""
    faltam = [funcao for nome, funcao, obrigatorio in PACOTES
              if obrigatorio and not _pacote_presente(nome)]
    saida = []
    problema = problema_nas_pastas(cfg.pasta_acervo, cfg.pasta_sigilosos, pasta_pauta(cfg))
    if problema:
        saida.append(Pendencia("pastas", "Pastas em conflito", problema, "ajustes#pastas"))
    nuvem = _pendencia_da_nuvem(cfg)
    if nuvem is not None:
        saida.append(nuvem)
    if faltam:
        inicio = ("Falta o componente do programa: " if len(faltam) == 1
                  else "Faltam os componentes do programa: ")
        saida.append(Pendencia("pacotes", "Instalação incompleta",
                               inicio + ", ".join(faltam) + ". " + DICA_INSTALAR,
                               "ajustes#sobre"))
    modelo = cfg.texto("transcricao", "modelo_ao_vivo") or "small"
    if _pacote_presente("faster_whisper") and not modelo_instalado(modelo):
        # A sessão ao vivo baixa o modelo que faltar ao começar (o áudio é
        # gravado e a fila espera): o recado diz isso, e não que "não começa".
        saida.append(Pendencia("modelo", "Modelo de transcrição",
                               f"O modelo de transcrição “{modelo}” ainda não foi baixado. "
                               "Baixe agora: senão, a primeira audiência começa baixando o "
                               "modelo, e o texto demora a aparecer.", "ajustes#transcricao"))
    return saida


def _pendencia_da_nuvem(cfg) -> Pendencia | None:
    """A pasta da nuvem em conflito (config.ini editado à mão ou de versão
    anterior, que a tela de Ajustes recusaria): os sigilosos ou a pauta
    dentro da nuvem (ou a nuvem dentro deles) - o que é de segredo de justiça
    seria sincronizado com o OneDrive ou o Google Drive -, ou a nuvem dentro
    do acervo (ou contendo-o). O espelho não roda assim, e só o registro
    dizia por quê; agora o Início mostra o motivo e onde corrigir."""
    try:
        destino = str(cfg.texto("compartilhar", "pasta_nuvem") or "").strip()
    except Exception:
        destino = ""
    if not destino:
        return None
    from .nucleo import config as _config

    pauta = pasta_pauta(cfg)
    frase = _config.conflito_com_a_nuvem(destino, cfg.pasta_sigilosos, pauta)
    if frase:
        # Os sigilosos (ou a pauta) dentro da nuvem: muda-se a pasta deles;
        # a nuvem dentro deles: muda-se a pasta da nuvem.
        dentro_da_nuvem = (dentro_ou_igual(cfg.pasta_sigilosos, destino)
                           or dentro_ou_igual(pauta, destino))
        return Pendencia("nuvem", "Pasta da nuvem em conflito", frase,
                         "ajustes#pastas" if dentro_da_nuvem else "ajustes#compartilhar")
    frase = conflito_da_nuvem(destino, cfg.pasta_acervo)
    if frase:
        return Pendencia("nuvem", "Pasta da nuvem em conflito",
                         frase + " Enquanto isso, o acervo não é espelhado na nuvem.",
                         "ajustes#compartilhar")
    return None


# ===================================================================== pastas
def _normalizar(p) -> str:
    try:
        p = Path(p).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        p = Path(os.path.abspath(p))
    return os.path.normcase(str(p))


def dentro_ou_igual(filho, pai) -> bool:
    """'filho' é 'pai' ou fica dentro dele? (No Windows, sem distinguir
    maiúsculas e com as barras normalizadas.)"""
    f, p = _normalizar(filho), _normalizar(pai)
    return f == p or f.startswith(p.rstrip(os.sep) + os.sep)


def pasta_do_programa() -> Path:
    """A pasta instalada do programa (ou o repositório, fora da instalação)."""
    return Path(caminhos.INSTALACAO)


def base_usuario() -> Path:
    """Documentos\\Helestron (ou o que caminhos.BASE_USUARIO disser)."""
    return Path(caminhos.BASE_USUARIO)


def pasta_pauta(cfg) -> Path:
    """Onde vão as planilhas da pauta exportada ([pauta] pasta).

    Em branco = Documentos\\Helestron\\Pauta. Fica FORA do acervo: a planilha
    traz as partes dos processos em segredo de justiça.
    """
    propria = getattr(cfg, "pasta_pauta", None)
    if propria is not None and not callable(propria):
        return Path(propria)
    # Configuração simulada (testes) sem a propriedade: a mesma regra do núcleo.
    try:
        valor = cfg.texto("pauta", "pasta")
    except Exception:
        valor = ""
    return caminhos.resolver(valor, "Pauta", base_usuario())


def problema_nas_pastas(acervo, sigilosos, pauta=None) -> str | None:
    """Por que estas pastas vazariam o que não pode sair, ou None.

    O acervo inteiro é lido pela IA (conector, CLAUDE.md, pacote) e copiado
    para a nuvem. Por isso a pasta dos sigilosos não pode ficar dentro dele,
    nem a da pauta exportada (a planilha traz as partes dos processos em
    segredo de justiça), e ele não pode conter a pasta do programa nem a
    pasta das senhas e dos perfis do navegador.
    """
    # A regra acervo x sigilosos x pauta é do núcleo: uma frase só para a
    # tela, o assistente e a verificação.
    from .nucleo import config as _config

    pauta = Path(pauta) if pauta is not None and str(pauta).strip() else None
    frase = _config.conflito_de_pastas(Path(acervo), Path(sigilosos), pauta)
    if frase:
        return frase
    # Defesa: o núcleo compara caminhos resolvidos; aqui, também sem
    # distinguir maiúsculas no Windows.
    if dentro_ou_igual(sigilosos, acervo):
        return ("A pasta dos processos em segredo de justiça não pode ficar dentro do acervo: "
                "tudo o que está no acervo é lido pela IA e copiado para a nuvem. Escolha uma "
                "pasta fora dele.")
    if pauta is not None and dentro_ou_igual(pauta, acervo):
        return ("A pasta da pauta exportada não pode ficar dentro do acervo: a planilha traz "
                "as partes dos processos em segredo de justiça, e tudo o que está no acervo é "
                "lido pela IA e copiado para a nuvem. Escolha uma pasta fora dele.")
    if dentro_ou_igual(pasta_do_programa(), acervo):
        return ("O acervo não pode ser a pasta do programa nem uma pasta que a contenha: ela "
                "guarda os arquivos do Helestron. Escolha uma pasta só para o acervo.")
    if dentro_ou_igual(caminhos.LOCAL, acervo):
        return ("O acervo não pode conter a pasta em que o programa guarda as senhas e os "
                f"perfis do navegador ({caminhos.LOCAL}). Escolha uma pasta só para o acervo.")
    return None


SUBPASTA_NUVEM = "Helestron - Acervo"      # a de compartilhar.nuvem (sem importá-lo aqui)


def conflito_da_nuvem(nuvem, acervo) -> str | None:
    """Por que esta pasta da nuvem não pode receber o espelho do acervo, ou None.

    O espelho copia o acervo para '<nuvem>/Helestron - Acervo'. Com a nuvem
    dentro do acervo (ou igual a ele), cada espelho copiaria a cópia
    anterior: o acervo cresceria sem fim, e a IA veria os autos em dobro. Com
    a nuvem contendo o acervo, ele já está na nuvem - o espelho só o
    duplicaria lá (e, se o acervo for a própria subpasta, copiaria o acervo
    sobre ele mesmo).
    """
    texto = str(nuvem or "").strip()
    if not texto:
        return None
    if dentro_ou_igual(texto, acervo):
        return ("A pasta da nuvem não pode ficar dentro do acervo (nem ser o próprio acervo): "
                "cada espelho copiaria a cópia anterior, e o acervo cresceria sem fim. Escolha "
                "a pasta do OneDrive ou do Google Drive, fora do acervo.")
    if dentro_ou_igual(acervo, texto):
        return ("O acervo já está dentro desta pasta da nuvem: o espelho só o duplicaria lá. "
                "Escolha outra pasta da nuvem, ou deixe em branco para não espelhar.")
    return None


def atualizar_indice(cfg):
    """INDICE.md (e CLAUDE.md/AGENTS.md, se faltarem) em dia, sem extrair o
    texto dos PDFs - é rápido. Chamado depois de cada transcrição: o índice
    é o que a IA lê primeiro, e sem isto a audiência recém-transcrita não
    aparecia nele (nem no espelho da nuvem). O preparo também tira do acervo
    o processo que o programa já sabe sigiloso (a transcrição sigilosa
    recém-gravada, a pauta) - e os pacotes para o ChatGPT já gerados perdem o
    que for dele (retirar_sigilosos_dos_pacotes). Devolve o RelatorioPreparo
    (None se falhou: nunca levanta), com 'avisos_pacotes': o pacote antigo
    que não pôde perder o sigiloso (também em 'avisos')."""
    rel = None
    try:
        from .compartilhar import preparo

        rel = preparo.atualizar_contexto(cfg, extrair_texto=False)
    except Exception as erro:
        log.warning("não consegui atualizar o INDICE.md do acervo: %s", str(erro)[:200])
    # Mesmo se o preparo falhou: o pacote antigo não espera o índice.
    avisos = retirar_sigilosos_dos_pacotes(cfg)
    if rel is not None:
        try:
            rel.avisos_pacotes = list(avisos)
            if avisos and isinstance(getattr(rel, "avisos", None), list):
                rel.avisos += avisos
        except AttributeError:         # relatório sem atributos livres
            pass
    return rel


PASTA_PACOTES = "Pacotes para IA"


def pasta_pacotes() -> Path:
    """Onde ficam os pacotes para o ChatGPT (Documentos\\Helestron\\Pacotes
    para IA): fora do acervo, mas ao alcance de quem os arrasta para a IA."""
    return base_usuario() / PASTA_PACOTES


def retirar_sigilosos_dos_pacotes(cfg, sigilosas=None) -> list[str]:
    """Tira dos pacotes para o ChatGPT já gerados o que é de processo que o
    programa hoje sabe sigiloso (a regra única: pasta dos sigilosos e pauta;
    'sigilosas' já calculadas, se houver).

    Antes, só o "Gerar o pacote" seguinte fazia isso: o processo que virou
    sigiloso depois - a pauta revelou o segredo de justiça, a transcrição foi
    salva como sigilosa - continuava nos pacotes antigos, prontos para serem
    arrastados de novo para o ChatGPT. Devolve os avisos do que não pôde ser
    tirado (arquivo aberto). Nunca levanta."""
    try:
        pasta = pasta_pacotes()
        if not pasta.is_dir():
            return []
        from .compartilhar import chatgpt

        if sigilosas is None:
            from .nucleo import sigilo

            sigilosas = sigilo.chaves_sigilosas(cfg.pasta_sigilosos, cfg.pasta_acervo)
        if not sigilosas:
            return []
        return [str(a) for a in chatgpt.retirar_sigilosos_dos_pacotes(pasta, sigilosas) or []]
    except Exception as erro:
        log.warning("não consegui conferir os pacotes para o ChatGPT: %s", str(erro)[:200])
        return []


# ============================================================ compartilhar
PROMPT_PADRAO = (
    "Você vai trabalhar no acervo judicial desta pasta. Leia primeiro o CLAUDE.md "
    "(ou o AGENTS.md) e o INDICE.md. Depois, aguarde a minha tarefa.")

LOJA_CHATGPT = "ms-windows-store://pdp/?productid=9PLM9XGG6VKS"   # reserva
SITE_CHATGPT_APP = "https://openai.com/chatgpt/download/"


def prompt_inicial() -> str:
    try:
        from .compartilhar import claude

        return getattr(claude, "PROMPT_INICIAL", "") or PROMPT_PADRAO
    except ImportError:
        return PROMPT_PADRAO


def abrir_endereco(url: str) -> None:
    """Abre link comum ou protocolo de aplicativo (claude://, codex://)."""
    if sistema.NO_WINDOWS and not url.startswith(("http://", "https://")):
        os.startfile(url)  # type: ignore[attr-defined]
        return
    sistema.abrir_endereco(url)


def abrir_no_cowork(pasta: Path) -> str:
    """Abre o Cowork já na pasta. Devolve o que foi feito:

    'cowork'   o link claude://cowork/new foi aberto;
    'desktop'  esta versão do programa não sabe montar o link: abriu o app;
    'baixar'   o Claude Desktop não está instalado: abriu a página de download.
    """
    from .compartilhar import claude

    if not claude.claude_desktop_instalado():
        claude.abrir_claude_desktop()          # sem o app, cai na página de download
        return "baixar"
    try:
        # Com 'folder' no link, o texto de 'q' se perde (falha conhecida do
        # app): o pedido vai pela área de transferência, e o link leva só a pasta.
        url = claude.url_cowork(Path(pasta), "")
    except AttributeError:
        claude.abrir_claude_desktop()
        return "desktop"
    try:
        abrir_endereco(url)
    except OSError as erro:
        log.info("o link do Cowork não abriu (%s); abrindo o app", erro)
        claude.abrir_claude_desktop()
        return "desktop"
    return "cowork"


def gerar_plugin_cowork(destino: Path) -> Path | None:
    from .compartilhar import claude

    fn = getattr(claude, "gerar_plugin_cowork", None)
    return fn(Path(destino)) if fn else None


def chatgpt_desktop_instalado() -> bool | None:
    """True/False; None quando esta versão não sabe detectar."""
    from .compartilhar import chatgpt

    fn = getattr(chatgpt, "chatgpt_desktop_instalado", None)
    if fn is None:
        return None
    try:
        return bool(fn())
    except Exception:
        return None


def abrir_chatgpt_work(pasta: Path) -> str:
    """Abre o ChatGPT para o modo Work. Devolve 'app' ou 'web'.

    Não há como entregar a pasta ao Work de modo garantido (o link codex://
    falha em algumas versões do app no Windows): a tela sempre mostra o
    plano B - Ctrl+O e colar o caminho, que já vai copiado.
    """
    from .compartilhar import chatgpt

    fn = getattr(chatgpt, "abrir_chatgpt_work", None)
    if fn is None:
        chatgpt.abrir_chatgpt()
        return "web"
    resultado = fn(Path(pasta))
    if isinstance(resultado, str):
        return resultado
    return "app" if resultado else "web"


def instalar_chatgpt_desktop() -> None:
    from .compartilhar import chatgpt

    fn = getattr(chatgpt, "instalar_chatgpt_desktop", None)
    if fn is not None:
        fn()
        return
    try:
        abrir_endereco(LOJA_CHATGPT)
    except OSError:
        sistema.abrir_endereco(SITE_CHATGPT_APP)


def registrar_mcp_codex(pasta: Path):
    """Conecta o acervo ao ChatGPT (Work/Codex) pelo config.toml do Codex.
    Devolve o arquivo alterado, ou None se esta versão não souber fazê-lo."""
    from .compartilhar import chatgpt

    fn = getattr(chatgpt, "registrar_mcp_codex", None)
    return fn(Path(pasta)) if fn else None


def estado_ia(cfg) -> dict:
    """Tudo o que a tela Compartilhar mostra (procura arquivos: chame de uma thread
    que possa esperar).

    Cada ferramenta numa chave própria ('claude', 'chatgpt'): os dois
    módulos usam o mesmo nome 'mcp' para coisas diferentes.
    """
    from .compartilhar import chatgpt, claude, nuvem

    estado: dict = {"claude": {}, "chatgpt": {}}
    try:
        estado["claude"] = dict(claude.estado())
    except Exception as erro:
        log.debug("estado do Claude: %s", erro)
    try:
        # O conector do ChatGPT só conta como ligado se aponta para ESTE acervo.
        estado["chatgpt"] = dict(chatgpt.estado(cfg.pasta_acervo))
    except Exception as erro:
        log.debug("estado do ChatGPT: %s", erro)
    estado["chatgpt_desktop"] = chatgpt_desktop_instalado()
    estado["tem_registrar_codex"] = hasattr(chatgpt, "registrar_mcp_codex")
    try:
        estado["nuvens"] = nuvem.detectar()
    except Exception:
        estado["nuvens"] = {}
    try:
        estado["mcp_acervo"] = claude.mcp_registrado(cfg.pasta_acervo)
    except Exception:
        estado["mcp_acervo"] = False
    estado["acervo"] = resumo_acervo(cfg)
    return estado


def resumo_acervo(cfg) -> dict:
    """Quantos processos e transcrições há, e quando o acervo foi preparado."""
    from .compartilhar.mcp_servidor import Acervo

    raiz = cfg.pasta_acervo
    try:
        # Sem os sigilosos (a regra única), como o índice e o MCP os contam
        ac = Acervo(raiz, sigilosos=cfg.pasta_sigilosos)
        pdfs = ac.pdfs()
        trans = ac.transcricoes()
    except Exception:
        pdfs, trans = {}, {}
    indice = raiz / "INDICE.md"
    preparado = datetime.fromtimestamp(_mtime(indice)) if indice.exists() else None
    return {"processos": len(pdfs), "transcricoes": sum(len(v) for v in trans.values()),
            "preparado": preparado}

