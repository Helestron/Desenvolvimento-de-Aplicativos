"""O ÚNICO ponto em que a interface chama o download, a transcrição, a
verificação e as funções de compartilhamento que podem não existir ainda.

Por que um módulo só: as telas não importam helestron.download.motor,
helestron.transcricao.* nem helestron.verificar diretamente. Se uma assinatura mudar,
ou se um pacote faltar na instalação, o ajuste é aqui - e a tela recebe uma
exceção ComponenteAusente com a frase pronta para o usuário ("rode o
INSTALAR.bat de novo"), em vez de um ImportError cru.

Tudo é importado DENTRO das funções: a janela abre em menos de 2 s mesmo
sem faster-whisper, Playwright ou PyMuPDF. Quase tudo aqui é lento (disco,
áudio, rede) e deve ser chamado de uma thread de trabalho - nunca da
thread do Tk.
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

from ..nucleo import caminhos, cnj, sistema

log = logging.getLogger("interface.servicos")

DICA_INSTALAR = "Rode o INSTALAR.bat de novo (ele completa a instalação sem apagar nada)."


class ComponenteAusente(RuntimeError):
    """Parte do programa não está instalada; a mensagem diz o que fazer."""


def _ausente(erro: ImportError, funcao: str) -> ComponenteAusente:
    nome = getattr(erro, "name", "") or str(erro)
    return ComponenteAusente(
        f"O componente de {funcao} não está instalado ({nome}). {DICA_INSTALAR}")


# =================================================================== download
def opcoes_download(cfg):
    from ..download.modelos import OpcoesDownload

    return OpcoesDownload.de_config(cfg)


def baixar_lote(numeros, destino: Path, opcoes, ctx, senhas: dict | None, cofre, cfg):
    """Roda o lote inteiro (bloqueia). Devolve o ResumoLote do motor."""
    try:
        from ..download import motor
    except ImportError as erro:
        raise _ausente(erro, "download de processos") from erro
    return motor.executar(numeros, Path(destino), opcoes, ctx, senhas=senhas, cofre=cofre, cfg=cfg)


def testar_login(tribunal, opcoes, ctx, credenciais: tuple[str, str] | None) -> None:
    """Abre o navegador do portal e faz só o login (bloqueia).

    Usa as mesmas fábricas do motor: o teste passa exatamente pelo caminho
    que o download vai usar.
    """
    try:
        from ..download import motor
    except ImportError as erro:
        raise _ausente(erro, "download de processos") from erro
    nav = motor.fabrica_navegador_padrao(tribunal, opcoes)
    with nav:
        portal = motor.fabrica_portal_padrao(nav, tribunal, opcoes, ctx, credenciais)
        portal.entrar()


def cofre():
    from ..nucleo.cofre_senhas import CofreSenhas

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
                sigiloso: bool = False):
    """Cria (sem iniciar) a sessão ao vivo. iniciar() e encerrar() bloqueiam:
    chame-os de uma thread de trabalho. 'sigiloso': documento, gravação e
    diário vão para a pasta dos sigilosos, fora do acervo."""
    try:
        from ..transcricao.ao_vivo import SessaoAoVivo
    except ImportError as erro:
        raise _ausente(erro, "transcrição") from erro
    return SessaoAoVivo(numero, cfg, eventos, tipo=tipo, participantes=participantes,
                        falante=falante, sigiloso=sigiloso)


def processo_sigiloso(cfg, numero) -> bool:
    """Os autos do processo estão na pasta de sigilosos? Pré-marca a caixa
    "Processo em segredo de justiça" das transcrições. Nunca levanta."""
    if numero is None:
        return False
    try:
        from ..transcricao.documento import processo_sigiloso as _sigiloso

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


def recuperaveis(cfg) -> list[Path]:
    try:
        from ..transcricao import ao_vivo
    except ImportError:
        return []
    try:
        return list(ao_vivo.recuperaveis(cfg))
    except Exception as erro:
        log.warning("não consegui procurar transcrições interrompidas: %s", erro)
        return []


def recuperar(jsonl: Path) -> Path:
    try:
        from ..transcricao import ao_vivo
    except ImportError as erro:
        raise _ausente(erro, "transcrição") from erro
    return ao_vivo.recuperar(jsonl)


def listar_microfones() -> list:
    """Entradas de áudio (Entrada: indice, nome, padrao, taxa). Lenta: PortAudio."""
    try:
        from ..transcricao import microfone
    except ImportError as erro:
        raise _ausente(erro, "microfone") from erro
    return list(microfone.listar_entradas())


def abrir_teste_microfone(dispositivo, ao_nivel: Callable[[float], None],
                          ao_aviso: Callable[[str], None] | None = None):
    """Liga o microfone só para medir o nível (botão Testar). Devolve o objeto
    de captura, que a tela desliga com parar()."""
    try:
        from ..transcricao import microfone
    except ImportError as erro:
        raise _ausente(erro, "microfone") from erro
    captura = microfone.Captura(dispositivo if dispositivo not in ("", None) else None,
                                lambda _bloco: None, ao_nivel, ao_aviso)
    captura.iniciar()
    return captura


def modelos_disponiveis() -> list[dict]:
    """[{'nome', 'mb', 'instalado', 'descricao'...}] do catálogo Whisper."""
    try:
        from ..transcricao import modelos
    except ImportError:
        return []
    try:
        return modelos.listar()
    except Exception as erro:
        log.debug("catálogo de modelos indisponível: %s", erro)
        return []


def modelo_instalado(nome: str) -> bool:
    try:
        from ..transcricao import modelos

        return bool(modelos.instalado(nome))
    except Exception:
        return False


def baixar_modelo(nome: str, progresso: Callable[[float, str], None] | None = None) -> Path:
    try:
        from ..transcricao import modelos
    except ImportError as erro:
        raise _ausente(erro, "transcrição") from erro
    return modelos.baixar(nome, progresso)


def transcrever_gravacao(origem: Path, numero, cfg, progresso, cancelado, *,
                         rotulos_manuais=None, destino: Path | None = None, tipo: str = "",
                         participantes: dict | None = None, sigiloso: bool = False) -> Path:
    try:
        from ..transcricao import arquivo
    except ImportError as erro:
        raise _ausente(erro, "transcrição de gravações") from erro
    meta = None
    if tipo:
        try:
            from ..transcricao.documento import MetaAudiencia

            meta = MetaAudiencia(numero=numero.formatado if numero else "", tipo=tipo,
                                 participantes=dict(participantes or {}))
        except Exception:
            meta = None
    extra = {"meta": meta} if meta is not None else {}
    return arquivo.transcrever_arquivo(origem, numero, cfg, progresso, cancelado,
                                       rotulos_manuais=rotulos_manuais, destino=destino,
                                       sigiloso=sigiloso, **extra)


def excecao_cancelado(erro: BaseException) -> bool:
    """O erro é o "Cancelado" de algum módulo (o usuário pediu para parar)?"""
    return type(erro).__name__ == "Cancelado"


def falantes_situacao() -> tuple[bool, str]:
    """(disponível, frase) da separação automática de falantes."""
    try:
        from ..transcricao import falantes
    except ImportError:
        return False, "não instalada"
    try:
        return bool(falantes.disponivel()), falantes.situacao()
    except Exception as erro:
        return False, f"indisponível ({erro})"


def instalar_falantes(progresso: Callable[[float, str], None] | None = None,
                      cancelado: Callable[[], bool] | None = None) -> None:
    try:
        from ..transcricao import falantes
    except ImportError as erro:
        raise _ausente(erro, "separação de falantes") from erro
    falantes.instalar(progresso, cancelado=cancelado)


def numero_no_nome(caminho: Path):
    """O número CNJ do arquivo: no nome (inclusive o dependente "-NN") ou na
    pasta (as mídias baixadas ficam em _controle/midias/<número>/)."""
    try:
        from ..transcricao import arquivo

        return arquivo.numero_do_caminho(Path(caminho))
    except (ImportError, AttributeError):
        pass
    try:
        return cnj.ler(Path(caminho).stem)
    except cnj.NumeroInvalido:
        return None


def transcricoes_recentes(cfg, limite: int = 5) -> list[Path]:
    pasta = cfg.pasta_transcricoes
    try:
        docs = [p for p in pasta.glob("*.docx")
                if not p.name.startswith("~$") and not p.name.endswith((".parcial", ".tmp"))]
    except OSError:
        return []
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
        from .. import verificar
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
    ("PIL", "ícones e botões da janela", False),
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
    """Algo da instalação que falta, para o aviso amarelo da tela inicial."""
    chave: str             # "pacotes" | "modelo"
    texto: str
    acao: str = ""         # rótulo do botão


def pendencias(cfg) -> list[Pendencia]:
    """O que falta para as três funções. Rápido (só procura arquivos), mas
    chame fora da thread do Tk."""
    faltam = [funcao for nome, funcao, obrigatorio in PACOTES
              if obrigatorio and not _pacote_presente(nome)]
    saida = []
    problema = problema_nas_pastas(cfg.pasta_acervo, cfg.pasta_sigilosos)
    if problema:
        saida.append(Pendencia("pastas", problema, "Abrir as Configurações"))
    if faltam:
        inicio = ("Falta o componente do programa: " if len(faltam) == 1
                  else "Faltam os componentes do programa: ")
        saida.append(Pendencia("pacotes", inicio + ", ".join(faltam) + ". " + DICA_INSTALAR,
                               "Abrir a pasta do programa"))
    modelo = cfg.texto("transcricao", "modelo_ao_vivo") or "small"
    if _pacote_presente("faster_whisper") and not modelo_instalado(modelo):
        # A sessão ao vivo baixa o modelo que faltar ao começar (o áudio é
        # gravado e a fila espera): o recado diz isso, e não que "não começa".
        saida.append(Pendencia("modelo", f"O modelo de transcrição “{modelo}” ainda não foi "
                                         "baixado. Baixe agora: senão, a primeira audiência "
                                         "começa baixando o modelo, e o texto demora a aparecer.",
                               "Baixar agora"))
    return saida


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


def problema_nas_pastas(acervo, sigilosos) -> str | None:
    """Por que este par de pastas vazaria o que não pode sair, ou None.

    O acervo inteiro é lido pela IA (conector, CLAUDE.md, pacote) e copiado
    para a nuvem. Por isso a pasta dos sigilosos não pode ficar dentro dele,
    e ele não pode conter a pasta do programa (registros com imagens das
    telas dos portais, config.ini e, no padrão, a própria pasta Sigilosos)
    nem a pasta das senhas e dos perfis do navegador.
    """
    # A regra acervo x sigilosos é do núcleo, quando ele a tiver: uma frase só
    # para a tela, o assistente e a verificação.
    from ..nucleo import config as _config

    conferir = getattr(_config, "conflito_de_pastas", None)
    if conferir is not None:
        try:
            frase = conferir(Path(acervo), Path(sigilosos))
        except Exception:
            frase = ""
        if frase:
            return frase
    if dentro_ou_igual(sigilosos, acervo):
        return ("A pasta dos processos em segredo de justiça não pode ficar dentro do acervo: "
                "tudo o que está no acervo é lido pela IA e copiado para a nuvem. Escolha uma "
                "pasta fora dele.")
    if dentro_ou_igual(caminhos.RAIZ, acervo):
        return ("O acervo não pode ser a pasta do programa nem uma pasta que a contenha: ela "
                "guarda os registros, a configuração e, no padrão, os processos sigilosos. "
                "Escolha uma pasta só para o acervo.")
    if dentro_ou_igual(caminhos.LOCAL, acervo):
        return ("O acervo não pode conter a pasta em que o programa guarda as senhas e os "
                f"perfis do navegador ({caminhos.LOCAL}). Escolha uma pasta só para o acervo.")
    return None


def atualizar_indice(cfg) -> None:
    """INDICE.md (e CLAUDE.md/AGENTS.md, se faltarem) em dia, sem extrair o
    texto dos PDFs - é rápido. Chamado depois de cada transcrição: o índice
    é o que a IA lê primeiro, e sem isto a audiência recém-transcrita não
    aparecia nele (nem no espelho da nuvem). Nunca levanta."""
    try:
        from ..compartilhar import preparo

        preparo.atualizar_contexto(cfg, extrair_texto=False)
    except Exception as erro:
        log.warning("não consegui atualizar o INDICE.md do acervo: %s", str(erro)[:200])


# ============================================================ compartilhar
PROMPT_PADRAO = (
    "Você vai trabalhar no acervo judicial desta pasta. Leia primeiro o CLAUDE.md "
    "(ou o AGENTS.md) e o INDICE.md. Depois, aguarde a minha tarefa.")

LOJA_CHATGPT = "ms-windows-store://pdp/?productid=9PLM9XGG6VKS"   # reserva
SITE_CHATGPT_APP = "https://openai.com/chatgpt/download/"


def prompt_inicial() -> str:
    try:
        from ..compartilhar import claude

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
    from ..compartilhar import claude

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
    from ..compartilhar import claude

    fn = getattr(claude, "gerar_plugin_cowork", None)
    return fn(Path(destino)) if fn else None


def chatgpt_desktop_instalado() -> bool | None:
    """True/False; None quando esta versão não sabe detectar."""
    from ..compartilhar import chatgpt

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
    from ..compartilhar import chatgpt

    fn = getattr(chatgpt, "abrir_chatgpt_work", None)
    if fn is None:
        chatgpt.abrir_chatgpt()
        return "web"
    resultado = fn(Path(pasta))
    if isinstance(resultado, str):
        return resultado
    return "app" if resultado else "web"


def instalar_chatgpt_desktop() -> None:
    from ..compartilhar import chatgpt

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
    from ..compartilhar import chatgpt

    fn = getattr(chatgpt, "registrar_mcp_codex", None)
    return fn(Path(pasta)) if fn else None


def estado_ia(cfg) -> dict:
    """Tudo o que a página Compartilhar mostra (procura arquivos: fora do Tk).

    Cada ferramenta numa chave própria ('claude', 'chatgpt'): os dois
    módulos usam o mesmo nome 'mcp' para coisas diferentes.
    """
    from ..compartilhar import chatgpt, claude, nuvem

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
    from ..compartilhar.mcp_servidor import Acervo

    raiz = cfg.pasta_acervo
    try:
        ac = Acervo(raiz)
        pdfs = ac.pdfs()
        trans = ac.transcricoes()
    except Exception:
        pdfs, trans = {}, {}
    indice = raiz / "INDICE.md"
    preparado = datetime.fromtimestamp(_mtime(indice)) if indice.exists() else None
    return {"processos": len(pdfs), "transcricoes": sum(len(v) for v in trans.values()),
            "preparado": preparado}

