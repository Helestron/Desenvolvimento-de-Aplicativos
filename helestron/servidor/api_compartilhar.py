"""API de Compartilhar com IA: preparar o acervo e entregá-lo a cada ferramenta.

A regra do sigilo vale aqui por inteiro: com processo sigiloso preso no
acervo (o motor ou o preparo não conseguiu tirá-lo de lá), nada de preparo,
pacote ou espelho na nuvem até o PDF sair - a IA leria o texto dele, e a
nuvem levaria a cópia. Antes de recusar, o programa tenta de novo levá-lo
para a pasta dos sigilosos (o arquivo pode ter sido fechado). E todo
compartilhamento começa pelo preparo (nucleo/sigilo.py: o processo que o
programa já sabe sigiloso - pela pasta dos sigilosos ou pela pauta - sai do
acervo e do índice antes de a ferramenta abrir ou de a nuvem receber a cópia).
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


def registrar_presos(app, arquivos) -> list[Path]:
    """Guarda os sigilosos que ficaram no acervo (o preparo não conseguiu
    levá-los): até saírem, nada se compartilha. Devolve a lista recebida."""
    lista = [Path(p) for p in arquivos] if isinstance(arquivos, (list, tuple)) else []
    for p in lista:
        if p not in app.sigilosos_presos:
            app.sigilosos_presos.append(p)
    return lista


def _tentar_de_novo(app, lista: list[Path]) -> None:
    """Leva de novo para a pasta dos sigilosos os arquivos presos de processo
    que a regra única dá como sigiloso (pasta dos sigilosos, pauta) - os que
    o preparo não conseguiu levar: o PDF que estava aberto pode ter sido
    fechado. O que sair deixa de ser preso. O sigilo que só o portal apurou
    no download continua com o caminho do download ("Tentar de novo", ou
    mover à mão)."""
    try:
        from ..download.motor import retirar_do_acervo
        from ..nucleo import cnj, sigilo

        cfg = app.cfg
        sigilosas = sigilo.chaves_sigilosas(cfg.pasta_sigilosos, cfg.pasta_acervo)
    except Exception as erro:
        log.debug("presos: a regra do sigilo não pôde ser lida (%s)", erro)
        return
    vistos: set[str] = set()
    for p in lista:
        try:
            chave = cnj.ler_nome_arquivo(p.stem).nome_arquivo
        except cnj.NumeroInvalido:
            continue
        if chave in vistos or chave not in sigilosas:
            continue
        vistos.add(chave)
        try:
            retirar_do_acervo(app.cfg, chave)
        except Exception as erro:          # continua preso; a recusa explica
            log.warning("não consegui levar %s para a pasta dos sigilosos: %s", p.name, erro)


def exigir_sem_sigiloso(app) -> None:
    lista = presos(app)
    if lista:
        _tentar_de_novo(app, lista)
        lista = presos(app)
    if lista:
        um = len(lista) == 1
        raise ErroApi(409, "sigiloso_no_acervo",
                      ("Um processo em segredo de justiça ficou no acervo" if um else
                       f"{len(lista)} processos em segredo de justiça ficaram no acervo")
                      + ": " + ", ".join(p.name for p in lista[:5])
                      + ". Feche o PDF e mova-o para a pasta dos sigilosos antes de compartilhar.")


def preparar_e_conferir(app, **opcoes):
    """O preparo do acervo (preparo.atualizar_contexto(app.cfg, **opcoes)) e,
    se um processo sigiloso não pôde sair do acervo, a recusa (SigilosoNoAcervo,
    com a frase da tela; o arquivo fica entre os presos)."""
    from ..compartilhar import preparo

    rel = preparo.atualizar_contexto(app.cfg, **opcoes)
    ficaram = registrar_presos(app, getattr(rel, "sigilosos_no_acervo", None))
    if ficaram:
        raise preparo.SigilosoNoAcervo(ficaram)
    return rel


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
            _atualizar_indice(app)
            if presos(app):
                # O índice já não lista o sigiloso preso, mas a nuvem espera.
                from ..compartilhar.preparo import SigilosoNoAcervo
                raise SigilosoNoAcervo(presos(app))
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
    _indice_em_segundo_plano(app)


def nuvem_sem_conflito(cfg, destino) -> bool:
    """O espelho automático pode ir para 'destino'? Pasta da nuvem dentro do
    acervo (ou que o contém), gravada antes desta regra ou à mão no
    config.ini: o espelho é pulado, com o aviso no registro."""
    frase = servicos.conflito_da_nuvem(destino, cfg.pasta_acervo)
    if frase:
        log.warning("Espelho na nuvem NÃO feito: %s", frase)
        return False
    return True


def _atualizar_indice(app) -> None:
    """INDICE.md em dia (servicos.atualizar_indice) e, se o preparo não
    conseguiu tirar do acervo um processo sigiloso, o arquivo entre os presos."""
    rel = servicos.atualizar_indice(app.cfg)
    registrar_presos(app, getattr(rel, "sigilosos_no_acervo", None))


def _indice_em_segundo_plano(app) -> None:
    threading.Thread(target=_atualizar_indice, args=(app,), name="indice-acervo",
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


def _preparo_rapido(app) -> None:
    """CLAUDE.md, AGENTS.md e INDICE.md antes de abrir uma ferramenta (sem
    extrair o texto dos PDFs, que é o que demora). O processo sigiloso que
    ainda estivesse no acervo sai dele aqui; se não puder sair, a ferramenta
    não abre (409)."""
    from ..compartilhar import preparo

    try:
        preparar_e_conferir(app, extrair_texto=False)
    except preparo.SigilosoNoAcervo:
        exigir_sem_sigiloso(app)    # a recusa (409), salvo se o arquivo saiu agora


# =================================================================== preparar
def preparar(p: Pedido) -> dict:
    app = p.app
    exigir_sem_sigiloso(app)

    def alvo(tw):
        tw.definir_status("Preparando o acervo para a IA…")
        rel = preparar_e_conferir(app, progresso=lambda f, t, d: tw.definir_progresso(
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
    from ..compartilhar import claude

    app = p.app
    exigir_sem_sigiloso(app)
    acervo = app.cfg.pasta_acervo
    _preparo_rapido(app)
    pedido = f"Pasta do acervo: {acervo}\n\n{servicos.prompt_inicial()}"
    if not claude.claude_desktop_instalado():
        # Como o Claude Desktop ausente (C6): a página de download abre aqui,
        # para saber se abriu - e, sem navegador, a mensagem traz o endereço
        # em vez de dizer que abriu (servicos.abrir_no_cowork não conta).
        url = claude.URL_DOWNLOAD_DESKTOP
        aberta = abrir_pagina(url)
        if aberta:
            mensagem = ("O Claude Desktop não está instalado: abri no navegador a página de "
                        "download. Instale o app, entre com a sua conta (o Cowork exige plano "
                        "pago) e tente de novo.")
        else:
            mensagem = (f"O Claude Desktop não está instalado. Baixe-o em {url}, instale-o, "
                        "entre com a sua conta (o Cowork exige plano pago) e tente de novo.")
        return {"abriu": False, "resultado": "baixar", "instalado": False,
                "pagina_aberta": aberta, "url": url, "mensagem": mensagem, "copiar": pedido}
    resultado = servicos.abrir_no_cowork(acervo)
    if resultado == "cowork":
        mensagem = ("Abrindo o Cowork. O Claude vai pedir para confirmar o acesso à pasta do "
                    "acervo; depois, cole o pedido inicial (Ctrl+V).")
    elif resultado == "baixar":
        # O app sumiu entre a conferência e a abertura: a página foi pedida.
        mensagem = ("O Claude Desktop não está instalado. Baixe-o em "
                    f"{claude.URL_DOWNLOAD_DESKTOP}, instale-o, entre com a sua conta (o "
                    "Cowork exige plano pago) e tente de novo.")
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
    _preparo_rapido(app)
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


def _app_chatgpt() -> bool:
    """O app do ChatGPT abre aqui? A mesma conferência de
    chatgpt.abrir_chatgpt_work: só no Windows, com o app instalado."""
    from ..compartilhar import chatgpt

    try:
        return bool(sistema.NO_WINDOWS and chatgpt.chatgpt_desktop_instalado())
    except Exception:
        return False


def chatgpt_work(p: Pedido) -> dict:
    from ..compartilhar import chatgpt

    app = p.app
    exigir_sem_sigiloso(app)
    acervo = app.cfg.pasta_acervo
    _preparo_rapido(app)
    if _app_chatgpt():
        resultado = servicos.abrir_chatgpt_work(acervo)
        aberta = True       # sem o app no fim das contas, a web foi pedida por lá
    else:
        # Sem o app, a web abre aqui, para saber se abriu (C6): a mensagem não
        # diz "abriu no navegador" quando nenhum navegador abriu.
        resultado = "web"
        aberta = abrir_pagina(chatgpt.URL_CHATGPT)
    if resultado == "web":
        sem_app = ("Instale o app do ChatGPT para Windows para usar o modo Work com o acervo — "
                   "ou, no cartão “Pacote para o ChatGPT”, “Gerar o pacote”.")
        if aberta:
            mensagem = "O ChatGPT abriu no navegador, que não lê pastas do computador. " + sem_app
        else:
            mensagem = (f"Não consegui abrir o ChatGPT no navegador ({chatgpt.URL_CHATGPT}). "
                        "Pelo navegador, ele não lê pastas do computador. " + sem_app)
        return {"abriu": aberta, "resultado": "web", "pagina_aberta": aberta,
                "url": chatgpt.URL_CHATGPT, "copiar": str(acervo), "mensagem": mensagem}
    return {"abriu": True, "resultado": "app", "copiar": str(acervo),
            "mensagem": "No app do ChatGPT, escolha Work, tecle Ctrl+O e cole o caminho do "
                        "acervo (Ctrl+V). O ChatGPT lê o AGENTS.md da pasta."}


def codex(p: Pedido) -> dict:
    from ..compartilhar import chatgpt

    app = p.app
    exigir_sem_sigiloso(app)
    acervo = app.cfg.pasta_acervo
    _preparo_rapido(app)
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
        from ..compartilhar.preparo import SigilosoNoAcervo

        tw.definir_status("Copiando os autos e os textos…")
        try:
            pasta, arquivo = chatgpt.gerar_pacote(
                cfg.pasta_acervo, destino, numeros=[str(n) for n in numeros] if numeros else None,
                cfg=cfg, progresso=lambda f, t, d="": tw.definir_progresso(f, t, d))
        except SigilosoNoAcervo as erro:
            registrar_presos(app, erro.arquivos)
            raise
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
        # O índice antes da cópia: sem isto, o INDICE.md da nuvem continuava
        # listando o processo que foi para a pasta dos sigilosos (ou que a
        # pauta passou a dar como sigiloso) - e o preparo tira do acervo a
        # cópia que ainda estivesse lá.
        tw.definir_status("Atualizando o índice do acervo…")
        preparar_e_conferir(app, extrair_texto=False)
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
