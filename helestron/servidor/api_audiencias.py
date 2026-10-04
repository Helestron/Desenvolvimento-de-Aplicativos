"""API de Audiências: microfone, modelos, transcrição ao vivo e de gravação."""

from __future__ import annotations

import logging
from pathlib import Path

from .. import servicos
from ..nucleo import caminhos
from ..tarefas import MODELO_REVISAO
from .audiencia import numero_da_gravacao, quando
from .rede import ErroApi, Pedido, Roteador, erro_400

log = logging.getLogger("servidor.audiencias")

ROTULOS_MODELO = {"base": "Base", "small": "Small", "medium": "Medium",
                  "large-v3-turbo": "Large v3 Turbo"}
RECOMENDADO = {"base": ["ao_vivo"], "small": ["ao_vivo"], "medium": ["revisao"],
               "large-v3-turbo": ["revisao"]}


def registrar(r: Roteador) -> None:
    r.adicionar("GET", "/api/transcricao/microfones", microfones)
    r.adicionar("POST", "/api/transcricao/microfone/teste", testar_microfone)
    r.adicionar("POST", "/api/transcricao/microfone/parar", parar_microfone)
    r.adicionar("GET", "/api/transcricao/modelos", modelos)
    r.adicionar("POST", "/api/transcricao/modelos/baixar", baixar_modelo)
    r.adicionar("POST", "/api/transcricao/iniciar", iniciar)
    r.adicionar("POST", "/api/transcricao/pausar", pausar)
    r.adicionar("POST", "/api/transcricao/retomar", retomar)
    r.adicionar("POST", "/api/transcricao/falante", falante)
    r.adicionar("POST", "/api/transcricao/encerrar", encerrar)
    r.adicionar("GET", "/api/transcricao/estado", estado)
    r.adicionar("GET", "/api/transcricao/recuperaveis", recuperaveis)
    r.adicionar("POST", "/api/transcricao/recuperar", recuperar)
    r.adicionar("POST", "/api/transcricao/gravacao", gravacao)
    r.adicionar("GET", "/api/transcricao/recentes", recentes)


# ================================================================= microfone
def microfones(p: Pedido) -> list[dict]:
    lista = servicos.listar_microfones()
    return [{"indice": getattr(e, "indice", None), "nome": getattr(e, "nome", str(e)),
             "padrao": bool(getattr(e, "padrao", False))} for e in lista]


def testar_microfone(p: Pedido) -> dict:
    return p.app.audiencia.testar_microfone(p.campo("dispositivo", padrao=None))


def parar_microfone(p: Pedido) -> dict:
    return p.app.audiencia.parar_teste()


# ==================================================================== modelos
def _embutido(nome: str) -> bool:
    pasta = getattr(caminhos, "MODELOS_EMBUTIDOS", None)
    if pasta is None:
        return False
    alvo = Path(pasta) / f"faster-whisper-{nome}"
    return (alvo / "model.bin").is_file()


def modelos(p: Pedido) -> list[dict]:
    saida = []
    for m in servicos.modelos_disponiveis():
        nome = m.get("nome", "")
        saida.append({"nome": nome, "rotulo": ROTULOS_MODELO.get(nome, nome),
                      "tamanho_mb": m.get("mb") or m.get("tamanho_mb") or 0,
                      "instalado": bool(m.get("instalado")),
                      "embutido": bool(m["embutido"]) if "embutido" in m else _embutido(nome),
                      "recomendado_para": RECOMENDADO.get(nome, []),
                      "descricao": m.get("descricao", "")})
    return saida


def baixar_modelo(p: Pedido) -> dict:
    nome = p.campo("nome", obrigatorio=True, tipo=str).strip()
    conhecidos = {m.get("nome") for m in servicos.modelos_disponiveis()}
    if conhecidos and nome not in conhecidos:
        raise erro_400(f"Modelo desconhecido: {nome}.", "valor_invalido")

    def alvo(tw):
        tw.definir_status(f"Baixando o modelo {nome}…")
        pasta = servicos.baixar_modelo(nome, lambda f, t="": tw.definir_fracao(f, t))
        tw.definir_fracao(1.0, "Modelo pronto.")
        return {"nome": nome, "pasta": str(pasta)}

    tw = p.app.tarefas.iniciar("modelo", f"Baixar o modelo {nome}", alvo, chave=f"modelo:{nome}")
    return {"tarefa": tw.id}


# ================================================================== ao vivo
def iniciar(p: Pedido) -> dict:
    return p.app.audiencia.iniciar(p.json())


def pausar(p: Pedido) -> dict:
    return p.app.audiencia.pausar()


def retomar(p: Pedido) -> dict:
    return p.app.audiencia.retomar()


def falante(p: Pedido) -> dict:
    return p.app.audiencia.definir_falante(p.campo("falante", padrao="", tipo=str))


def encerrar(p: Pedido) -> dict:
    refinar = p.json().get("refinar")
    return p.app.audiencia.encerrar(None if refinar is None else bool(refinar))


def estado(p: Pedido) -> dict:
    return p.app.audiencia.como_dict()


def recuperaveis(p: Pedido) -> list[dict]:
    saida = []
    for diario in servicos.recuperaveis(p.app.cfg):
        numero = servicos.numero_no_nome(Path(diario))
        saida.append({"arquivo": str(diario),
                      "processo": numero.formatado if numero is not None else None,
                      "quando": quando(diario)})
    return saida


def recuperar(p: Pedido) -> dict:
    alvo = p.campo("arquivo", obrigatorio=True, tipo=str)
    # Só o que a própria busca achou: o caminho não vem livre da página.
    validos = {str(Path(x)) for x in servicos.recuperaveis(p.app.cfg)}
    if str(Path(alvo)) not in validos:
        raise ErroApi(404, "nao_recuperavel",
                      "Esta transcrição não está entre as interrompidas (já foi recuperada?).")
    documento = servicos.recuperar(Path(alvo))
    p.app.hub.publicar("estado", {})
    return {"documento": str(documento)}


# ================================================================== gravação
def gravacao(p: Pedido) -> dict:
    app = p.app
    cfg = app.cfg
    enviado: Path | None = None
    if p.tipo_corpo == "multipart/form-data":
        envio = p.envio(app.pasta_envios())
        arquivo = envio.arquivo("arquivo")
        dados = dict(envio.campos)
        if arquivo is None:
            envio.apagar()
            raise erro_400("Envie a gravação no campo “arquivo”.", "campo_ausente")
        origem, nome, enviado = arquivo.caminho, arquivo.nome, arquivo.caminho
    else:
        dados = p.json()
        origem = None
        nome = ""
        caminho = str(dados.get("caminho") or "").strip().strip('"')
        if caminho:
            origem = Path(caminho)
            nome = origem.name
    try:
        revisao = str(dados.get("revisao", "")).strip().lower() in ("1", "true", "sim", "on") \
            if not isinstance(dados.get("revisao"), bool) else dados["revisao"]
        rotulos = None
        sigiloso_pedido = dados.get("sigiloso")
        if isinstance(sigiloso_pedido, str):
            sigiloso_pedido = sigiloso_pedido.strip().lower() in ("1", "true", "sim", "on") \
                if sigiloso_pedido.strip() else None
        if revisao:
            ultima = app.audiencia.ultima
            if not ultima:
                raise ErroApi(409, "sem_audiencia", "Não há audiência encerrada para revisar.")
            if origem is None:
                origem = Path(ultima["audio"]) if ultima.get("audio") else None
                nome = origem.name if origem is not None else ""
            if origem is None or not origem.exists():
                raise ErroApi(409, "sem_gravacao",
                              "A gravação da última audiência não está disponível para a "
                              "revisão.")
            numero = ultima["numero"]
            rotulos = ultima.get("falas")
            # a revisão de audiência sigilosa continua fora do acervo
            sigiloso = bool(ultima.get("sigiloso")) or bool(sigiloso_pedido)
        else:
            if origem is None:
                raise erro_400("Escolha a gravação da audiência.", "campo_ausente")
            if enviado is None and not origem.is_file():
                raise ErroApi(404, "arquivo_inexistente", f"Não encontrei o arquivo {origem.name}.")
            numero = numero_da_gravacao(nome, str(dados.get("processo") or "").strip() or None)
            if sigiloso_pedido is None:
                sigiloso = servicos.processo_sigiloso(cfg, numero) or (
                    enviado is None and servicos.na_pasta_dos_sigilosos(cfg, origem))
            else:
                sigiloso = bool(sigiloso_pedido)
        tipo = str(dados.get("tipo") or "").strip()
    except BaseException:
        if enviado is not None:
            enviado.unlink(missing_ok=True)
        raise

    def alvo(tw):
        try:
            tw.definir_fracao(0.0, f"{nome} → {numero.nome_arquivo}.docx")
            documento = servicos.transcrever_gravacao(
                origem, numero, cfg, lambda f, t="": tw.definir_fracao(f, t), tw.cancelado,
                rotulos_manuais=rotulos, tipo=tipo, sigiloso=sigiloso)
        finally:
            if enviado is not None:
                try:
                    enviado.unlink(missing_ok=True)
                except OSError:
                    log.warning("não consegui apagar a gravação enviada %s", enviado.name)
        documento = Path(documento)
        fora = servicos.na_pasta_dos_sigilosos(cfg, documento)
        tw.definir_fracao(1.0, "Transcrição pronta.")
        from .api_compartilhar import depois_de_salvar

        depois_de_salvar(app, documento)
        return {"documento": str(documento), "processo": numero.formatado, "sigiloso": fora,
                "mensagem": documento.name + (" — na pasta dos sigilosos, fora do acervo "
                                              "compartilhado." if fora else "")}

    titulo = "Revisar a audiência" if revisao else "Transcrever a gravação"
    try:
        tw = app.tarefas.iniciar("transcricao_arquivo", titulo, alvo, (MODELO_REVISAO,),
                                 chave="transcricao_arquivo")
    except BaseException:
        if enviado is not None:
            enviado.unlink(missing_ok=True)
        raise
    return {"tarefa": tw.id}


def recentes(p: Pedido) -> list[dict]:
    cfg = p.app.cfg
    saida = []
    for doc in servicos.transcricoes_recentes(cfg, 20, incluir_sigilosas=True):
        numero = servicos.numero_no_nome(doc)
        saida.append({"numero": numero.formatado if numero is not None else doc.stem,
                      "arquivo": str(doc), "quando": quando(doc),
                      "sigiloso": servicos.na_pasta_dos_sigilosos(cfg, doc)})
    return saida

