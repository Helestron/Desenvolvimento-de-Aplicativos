"""API de Compartilhar com IA: preparar o acervo e entregá-lo a cada ferramenta.

A regra do sigilo vale aqui por inteiro: com processo sigiloso preso no
acervo (o motor não conseguiu tirá-lo de lá), nada de preparo, pacote ou
espelho na nuvem até o PDF sair - a IA leria o texto dele, e a nuvem
levaria a cópia.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .. import servicos
from ..nucleo import sistema
from ..tarefas import NUVEM
from .api_geral import maiuscula
from .rede import ErroApi, Pedido, Roteador, erro_400

log = logging.getLogger("servidor.compartilhar")

PASTA_PACOTES = "Pacotes para IA"


def registrar(r: Roteador) -> None:
    r.adicionar("GET", "/api/compartilhar/estado", estado)
    r.adicionar("POST", "/api/compartilhar/preparar", preparar)
    r.adicionar("POST", "/api/compartilhar/claude-desktop", claude_desktop)
    r.adicionar("POST", "/api/compartilhar/cowork", cowork)
    r.adicionar("POST", "/api/compartilhar/claude-code", claude_code)
    r.adicionar("POST", "/api/compartilhar/chatgpt-work", chatgpt_work)
    r.adicionar("POST", "/api/compartilhar/codex", codex)
    r.adicionar("POST", "/api/compartilhar/pacote", pacote)
    r.adicionar("GET", "/api/compartilhar/nuvem", nuvens)
    r.adicionar("POST", "/api/compartilhar/nuvem/espelhar", espelhar)
    r.adicionar("GET", "/api/compartilhar/prompt", prompt)


# ===================================================================== sigilo
def presos(app) -> list[Path]:
    ficam = [Path(p) for p in app.sigilosos_presos if Path(p).exists()]
    app.sigilosos_presos = ficam
    return ficam


def exigir_sem_sigiloso(app) -> None:
    lista = presos(app)
    if lista:
        um = len(lista) == 1
        raise ErroApi(409, "sigiloso_no_acervo",
                      ("Um processo em segredo de justiça ficou no acervo" if um else
                       f"{len(lista)} processos em segredo de justiça ficaram no acervo")
                      + ": " + ", ".join(p.name for p in lista[:5])
                      + ". Feche o PDF e mova-o para a pasta dos sigilosos antes de compartilhar.")


def pasta_pacotes() -> Path:
    return servicos.base_usuario() / PASTA_PACOTES


def depois_de_salvar(app, documento: Path | None = None) -> None:
    """Ao fim de cada transcrição: o INDICE.md em dia e, se ligado, o espelho.

    O índice é o que a IA lê primeiro; sem refazê-lo, a audiência
    recém-transcrita não constava dele - nem da cópia na nuvem. Transcrição
    sigilosa não está no acervo: o índice não muda, mas refazê-lo não faz mal.
    """
    if app.fechando or presos(app):
        if presos(app):
            log.warning("Índice do acervo e espelho na nuvem adiados: há processo sigiloso no "
                        "acervo.")
        return
    cfg = app.cfg
    destino = cfg.texto("compartilhar", "pasta_nuvem")
    if destino and cfg.flag("compartilhar", "espelhar_automaticamente") \
            and nuvem_sem_conflito(cfg, destino):
        from ..compartilhar import nuvem

        def alvo(tw):
            servicos.atualizar_indice(cfg)
            if tw.cancelado():
                return {"copiados": 0, "iguais": 0}
            copiados, iguais = nuvem.espelhar(cfg.pasta_acervo, Path(destino),
                                              lambda f, t, n: tw.definir_progresso(f, t, n),
                                              tw.cancelado)
            return {"copiados": copiados, "iguais": iguais}

        try:
            app.tarefas.iniciar("nuvem", "Espelhar o acervo na nuvem", alvo, (NUVEM,),
                                chave="nuvem")
            return
        except Exception as erro:
            log.info("espelho na nuvem adiado: %s", erro)
    _indice_em_segundo_plano(cfg)


def nuvem_sem_conflito(cfg, destino) -> bool:
    """O espelho automático pode ir para 'destino'? Pasta da nuvem dentro do
    acervo (ou que o contém), gravada antes desta regra ou à mão no
    config.ini: o espelho é pulado, com o aviso no registro."""
    frase = servicos.conflito_da_nuvem(destino, cfg.pasta_acervo)
    if frase:
        log.warning("Espelho na nuvem NÃO feito: %s", frase)
        return False
    return True


def _indice_em_segundo_plano(cfg) -> None:
    threading.Thread(target=servicos.atualizar_indice, args=(cfg,), name="indice-acervo",
                     daemon=True).start()


# ==================================================================== estado
def estado(p: Pedido) -> dict:
    app = p.app
    dados = servicos.estado_ia(app.cfg)
    dados["pasta_acervo"] = str(app.cfg.pasta_acervo)
    dados["pasta_nuvem"] = app.cfg.texto("compartilhar", "pasta_nuvem")
    dados["sigilosos_no_acervo"] = [str(x) for x in presos(app)]
    dados["pasta_pacotes"] = str(pasta_pacotes())
    return dados


def prompt(p: Pedido) -> dict:
    texto = servicos.prompt_inicial()
    return {"texto": f"Pasta do acervo: {p.app.cfg.pasta_acervo}\n\n{texto}"}


def _preparo_rapido(cfg) -> None:
    """CLAUDE.md, AGENTS.md e INDICE.md antes de abrir uma ferramenta (sem
    extrair o texto dos PDFs, que é o que demora)."""
    from ..compartilhar import preparo

    preparo.atualizar_contexto(cfg, extrair_texto=False)


# =================================================================== preparar
def preparar(p: Pedido) -> dict:
    app = p.app
    exigir_sem_sigiloso(app)
    cfg = app.cfg

    def alvo(tw):
        from ..compartilhar import preparo

        tw.definir_status("Preparando o acervo para a IA…")
        rel = preparo.atualizar_contexto(cfg, progresso=lambda f, t, d: tw.definir_progresso(
            f, t, d), cancelado=tw.cancelado)
        resumo = maiuscula(getattr(rel, "resumo", "") or "Acervo preparado")
        tw.definir_status(resumo + ".")
        return {"resumo": resumo, "processos": getattr(rel, "processos", 0),
                "transcricoes": getattr(rel, "transcricoes", 0),
                "erros": list(getattr(rel, "erros", []) or [])[:20]}

    tw = app.tarefas.iniciar("preparo", "Preparar o acervo para a IA", alvo, chave="preparo")
    return {"tarefa": tw.id}


# ================================================================ ferramentas
def claude_desktop(p: Pedido) -> dict:
    from ..compartilhar import claude

    app = p.app
    exigir_sem_sigiloso(app)
    alterados = claude.registrar_mcp(app.cfg.pasta_acervo)
    instalado = claude.claude_desktop_instalado()
    if not instalado:
        aberta = abrir_pagina(claude.URL_DOWNLOAD_DESKTOP)
        inicio = ("O conector do acervo foi registrado, mas o app Claude Desktop não está "
                  "instalado neste computador. ")
        meio = ("Abri no navegador a página de download: instale o app, " if aberta else
                f"Baixe o app em {claude.URL_DOWNLOAD_DESKTOP}, instale-o, ")
        return {"abriu": False, "instalado": False, "pagina_aberta": aberta,
                "mensagem": inicio + meio + "entre com a sua conta e conecte de novo.",
                "url": claude.URL_DOWNLOAD_DESKTOP}
    if alterados:
        mensagem = ("Acervo conectado ao Claude Desktop. Feche e abra o Claude Desktop para ele "
                    "carregar o conector (ferramentas que só leem os autos, sem alterar nada).")
    else:
        mensagem = ("O acervo já estava conectado. Se o conector não aparecer, feche o Claude "
                    "Desktop pela bandeja do Windows (perto do relógio) e abra de novo.")
    return {"abriu": False, "instalado": True, "mensagem": mensagem}


def cowork(p: Pedido) -> dict:
    app = p.app
    exigir_sem_sigiloso(app)
    acervo = app.cfg.pasta_acervo
    _preparo_rapido(app.cfg)
    resultado = servicos.abrir_no_cowork(acervo)
    pedido = f"Pasta do acervo: {acervo}\n\n{servicos.prompt_inicial()}"
    if resultado == "cowork":
        mensagem = ("Abrindo o Cowork. O Claude vai pedir para confirmar o acesso à pasta do "
                    "acervo; depois, cole o pedido inicial (Ctrl+V).")
    elif resultado == "baixar":
        mensagem = ("O Claude Desktop não está instalado: abri a página de download. Instale, "
                    "entre com a sua conta (o Cowork exige plano pago) e tente de novo.")
    else:
        mensagem = ("Abrindo o Claude. No Cowork, escolha a pasta do acervo (o caminho e o "
                    "pedido inicial estão no texto para copiar).")
    return {"abriu": resultado != "baixar", "resultado": resultado, "mensagem": mensagem,
            "copiar": pedido}


def abrir_pagina(url: str) -> bool:
    """Abre a página no navegador padrão; False se não abriu (nunca levanta)."""
    try:
        aberta = sistema.abrir_endereco(url) is not False
    except Exception as erro:
        log.warning("não consegui abrir %s no navegador: %s", url, erro)
        return False
    if not aberta:
        log.warning("nenhum navegador abriu %s", url)
    return aberta


def claude_code(p: Pedido) -> dict:
    from ..compartilhar import claude

    app = p.app
    exigir_sem_sigiloso(app)
    _preparo_rapido(app.cfg)
    try:
        claude.abrir_claude_code(app.cfg.pasta_acervo)
    except FileNotFoundError:
        aberta = abrir_pagina(claude.URL_DOC_CODE)
        if aberta:
            mensagem = ("O Claude Code não está instalado neste computador. Abri no navegador a "
                        "página oficial que explica como instalá-lo (sem administrador). Depois "
                        "de instalar, clique de novo em “Abrir no Claude Code”.")
        else:
            mensagem = ("O Claude Code não está instalado neste computador. A página oficial "
                        f"explica como instalá-lo (sem administrador): {claude.URL_DOC_CODE}")
        return {"abriu": False, "instalado": False, "pagina_aberta": aberta,
                "mensagem": mensagem, "url": claude.URL_DOC_CODE}
    return {"abriu": True, "mensagem": "O Claude Code abriu numa janela própria, já na pasta "
                                       "do acervo. No primeiro uso, entre com a sua conta."}


def chatgpt_work(p: Pedido) -> dict:
    app = p.app
    exigir_sem_sigiloso(app)
    acervo = app.cfg.pasta_acervo
    _preparo_rapido(app.cfg)
    resultado = servicos.abrir_chatgpt_work(acervo)
    if resultado == "web":
        return {"abriu": True, "resultado": "web", "copiar": str(acervo),
                "mensagem": "O ChatGPT abriu no navegador, que não lê pastas do computador. "
                            "Instale o app do ChatGPT para Windows para usar o modo Work com o "
                            "acervo — ou gere o pacote para o ChatGPT."}
    return {"abriu": True, "resultado": "app", "copiar": str(acervo),
            "mensagem": "No app do ChatGPT, escolha Work, tecle Ctrl+O e cole o caminho do "
                        "acervo (Ctrl+V). O ChatGPT lê o AGENTS.md da pasta."}


def codex(p: Pedido) -> dict:
    from ..compartilhar import chatgpt

    app = p.app
    exigir_sem_sigiloso(app)
    acervo = app.cfg.pasta_acervo
    _preparo_rapido(app.cfg)
    partes = []
    try:
        arquivo = servicos.registrar_mcp_codex(acervo)
        if arquivo is not None:
            partes.append(f"Conector de leitura do acervo registrado em {arquivo}.")
    except Exception as erro:
        log.warning("não consegui registrar o conector do Codex: %s", erro)
        partes.append(f"Não consegui registrar o conector do acervo ({erro}).")
    try:
        chatgpt.abrir_codex(acervo)
        abriu = True
        partes.append("O Codex abriu numa janela própria, já na pasta do acervo.")
    except FileNotFoundError as erro:
        abriu = False
        partes.append(str(erro))
    return {"abriu": abriu, "mensagem": " ".join(partes)}


def pacote(p: Pedido) -> dict:
    from ..compartilhar import chatgpt

    app = p.app
    exigir_sem_sigiloso(app)
    numeros = p.campo("numeros", padrao=None)
    if numeros is not None and not isinstance(numeros, list):
        raise erro_400("“numeros” deve ser uma lista.", "campo_invalido")
    cfg = app.cfg
    destino = pasta_pacotes()

    def alvo(tw):
        tw.definir_status("Copiando os autos e os textos…")
        pasta, arquivo = chatgpt.gerar_pacote(
            cfg.pasta_acervo, destino, numeros=[str(n) for n in numeros] if numeros else None,
            cfg=cfg, progresso=lambda f, t, d="": tw.definir_progresso(f, t, d))
        tw.definir_status("Pacote pronto.")
        return {"pasta": str(pasta), "arquivo": str(arquivo),
                "mensagem": f"{Path(arquivo).name}. Arraste o .zip para uma conversa ou um "
                            "Projeto do ChatGPT."}

    tw = app.tarefas.iniciar("pacote", "Gerar o pacote para o ChatGPT", alvo, chave="pacote")
    return {"tarefa": tw.id}


# ===================================================================== nuvem
def nuvens(p: Pedido) -> list[dict]:
    from ..compartilhar import nuvem

    try:
        achadas = nuvem.detectar()
    except Exception:
        achadas = {}
    saida = [{"rotulo": rotulo, "caminho": str(caminho)} for rotulo, caminho in achadas.items()]
    atual = p.app.cfg.texto("compartilhar", "pasta_nuvem")
    if atual and all(x["caminho"] != atual for x in saida):
        saida.insert(0, {"rotulo": "Escolhida", "caminho": atual})
    return saida


def espelhar(p: Pedido) -> dict:
    from ..compartilhar import nuvem

    app = p.app
    cfg = app.cfg
    novo = str(p.campo("destino", padrao="", tipo=str) or "").strip().strip('"')
    if novo and not Path(novo).is_absolute():
        raise erro_400("Escolha a pasta completa da nuvem.", "valor_invalido")
    destino = novo or cfg.texto("compartilhar", "pasta_nuvem")
    if not destino:
        raise erro_400("Escolha antes a pasta do OneDrive ou do Google Drive.", "sem_nuvem")
    if not Path(destino).is_dir():
        raise ErroApi(404, "pasta_inexistente", f"A pasta {destino} não existe.")
    exigir_sem_sigiloso(app)
    acervo = cfg.pasta_acervo
    frase = servicos.conflito_da_nuvem(destino, acervo)
    if frase:
        raise erro_400(frase, "pastas_em_conflito")
    # Só depois de todas as conferências: a pasta recusada não fica gravada
    # (nem em uso pelo espelho automático, nem aceita pelo /api/abrir).
    if novo and novo != cfg.texto("compartilhar", "pasta_nuvem"):
        cfg.definir("compartilhar", "pasta_nuvem", novo)

    def alvo(tw):
        tw.definir_status("Copiando o acervo para a nuvem…")
        copiados, iguais = nuvem.espelhar(acervo, Path(destino),
                                          lambda f, t, n: tw.definir_progresso(f, t, n),
                                          tw.cancelado)
        tw.definir_status(f"{copiados} copiado{'s' if copiados != 1 else ''}, {iguais} sem "
                          "mudança.")
        return {"copiados": copiados, "iguais": iguais,
                "pasta": str(Path(destino) / nuvem.SUBPASTA)}

    tw = app.tarefas.iniciar("nuvem", "Espelhar o acervo na nuvem", alvo, (NUVEM,), chave="nuvem")
    return {"tarefa": tw.id}
