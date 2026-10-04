"""API geral: estado, configuração, acessos, diálogos, tarefas, perguntas e eventos.

Cada função recebe o Pedido (helestron.servidor.rede) e devolve os 'dados'
do envelope; erro com frase para o usuário sobe como ErroApi.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from .. import NOME, __version__, servicos
from ..nucleo import caminhos, sistema, tribunais
from ..tarefas import NAVEGADOR
from . import esquema
from .eventos import FIM, INTERVALO_PING_S, formatar_sse
from .rede import ErroApi, Fluxo, Pedido, Roteador, erro_400

log = logging.getLogger("servidor.api")

RE_PORTAL = re.compile(r"^(esaj|eproc):([A-Za-z0-9]{2,12})$")
# Extensões que /api/abrir nunca abre (rodariam um programa).
EXECUTAVEIS = {".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
               ".wsf", ".wsh", ".msi", ".msp", ".scr", ".hta", ".lnk", ".pif", ".cpl", ".reg",
               ".jar", ".dll", ".sys", ".url", ".appref-ms", ".application", ".msix", ".appx"}


def registrar(r: Roteador) -> None:
    r.adicionar("GET", "/api/ping", ping)
    r.adicionar("GET", "/api/estado", estado)
    r.adicionar("GET", "/api/config", ler_config)
    r.adicionar("POST", "/api/config", gravar_config)
    r.adicionar("GET", "/api/tribunais", listar_tribunais)
    r.adicionar("GET", "/api/acessos", listar_acessos)
    r.adicionar("POST", "/api/acessos", gravar_acesso)
    r.adicionar("POST", "/api/acessos/testar", testar_acesso)
    r.adicionar("DELETE", "/api/acessos/{portal}", apagar_acesso)
    r.adicionar("GET", "/api/tribunais/enderecos", listar_enderecos)
    r.adicionar("GET", "/api/tribunais/enderecos/{portal}", enderecos_do_portal)
    r.adicionar("POST", "/api/tribunais/enderecos", corrigir_endereco)
    r.adicionar("POST", "/api/dialogo/arquivo", dialogo_arquivo)
    r.adicionar("POST", "/api/dialogo/pasta", dialogo_pasta)
    r.adicionar("POST", "/api/abrir", abrir)
    r.adicionar("GET", "/api/verificacao", verificacao)
    r.adicionar("POST", "/api/verificacao/completa", verificacao_completa)
    r.adicionar("POST", "/api/encerrar", encerrar)
    r.adicionar("GET", "/api/tarefas", listar_tarefas)
    r.adicionar("GET", "/api/tarefas/{id}", obter_tarefa)
    r.adicionar("POST", "/api/tarefas/{id}/parar", parar_tarefa)
    r.adicionar("POST", "/api/perguntas/{id}/responder", responder_pergunta)
    r.adicionar("POST", "/api/perguntas/{id}/cancelar", cancelar_pergunta)
    r.adicionar("GET", "/api/eventos", eventos)
    r.adicionar("POST", "/api/janela/mostrar", mostrar_janela)
    r.adicionar("POST", "/api/autoteste/passo", autoteste_passo)
    r.adicionar("POST", "/api/autoteste/fim", autoteste_fim)


# ===================================================================== apoio
def iso(momento) -> str | None:
    if momento is None:
        return None
    if isinstance(momento, datetime):
        return momento.isoformat(timespec="seconds")
    return str(momento)


def maiuscula(texto: str) -> str:
    texto = (texto or "").strip()
    return texto[:1].upper() + texto[1:]


def pastas(cfg) -> dict:
    acervo = Path(cfg.pasta_acervo)
    return {"acervo": str(acervo), "processos": str(cfg.pasta_processos),
            "transcricoes": str(cfg.pasta_transcricoes), "sigilosos": str(cfg.pasta_sigilosos),
            "pauta": str(servicos.pasta_pauta(cfg)), "logs": str(caminhos.LOGS)}


# ===================================================================== geral
def ping(p: Pedido) -> dict:
    app = p.app
    return {"nome": NOME, "versao": __version__, "pid": os.getpid(), "modo": app.modo,
            "porta": app.porta, "fechando": app.fechando}


def _chave_do_arquivo(caminho) -> str | None:
    """O processo que dá nome ao arquivo (Numero.nome_arquivo), ou None."""
    from ..nucleo import cnj

    try:
        return cnj.ler_nome_arquivo(Path(caminho).name).nome_arquivo
    except cnj.NumeroInvalido:
        return None


def _pendencias(app) -> list[dict]:
    cfg = app.cfg
    saida = []
    try:
        saida = [x.como_dict() for x in servicos.pendencias(cfg)]
    except Exception as erro:
        log.warning("não consegui conferir as pendências: %s", erro)
    try:
        cofre = servicos.cofre()
        tem_acesso = bool(cofre.portais()) or bool(app.credenciais_sessao)
    except Exception:
        tem_acesso = bool(app.credenciais_sessao)
    # Quem entra com certificado ou à mão não precisa guardar senha.
    modos = {(cfg.texto(s, "login") or "senha").lower() for s in ("esaj", "eproc")}
    tem_acesso = tem_acesso or bool(modos & {"certificado", "manual"})
    if not tem_acesso:
        saida.insert(0, {"chave": "acessos", "titulo": "Acesso aos portais",
                         "mensagem": "Informe o seu usuário e a sua senha do e-SAJ ou do eProc: "
                                     "o Helestron entra por você para baixar processos e ler a "
                                     "pauta.", "acao": "ajustes#acessos"})
    from ..compartilhar.preparo import frase_sigilosos_no_acervo

    motivos = getattr(app, "sigilosos_motivos", None)
    motivos = motivos if isinstance(motivos, dict) else {}
    presos = [Path(p) for p in app.sigilosos_presos if Path(p).exists()]
    app.sigilosos_presos = presos
    avisos = [Path(p) for p in getattr(app, "sigilosos_avisos", None) or []
              if Path(p).exists() and Path(p) not in presos]
    app.sigilosos_avisos = avisos
    if avisos:
        # Não trava nada, mas o arquivo (e o que fazer) fica à vista
        saida.insert(0, {"chave": "sigilo-arquivos",
                         "titulo": "Arquivo de processo sigiloso no acervo" if len(avisos) == 1
                         else "Arquivos de processos sigilosos no acervo",
                         "mensagem": frase_sigilosos_no_acervo(avisos, cfg, motivos, trava=False),
                         "acao": "compartilhar", "arquivos": [str(x) for x in avisos]})
    if presos:
        processos = {_chave_do_arquivo(p) for p in presos} - {None}
        saida.insert(0, {"chave": "sigilo",
                         "titulo": "Processo sigiloso no acervo" if len(processos) <= 1
                         else "Processos sigilosos no acervo",
                         "mensagem": frase_sigilosos_no_acervo(presos, cfg, motivos),
                         "acao": "compartilhar", "arquivos": [str(x) for x in presos]})
    if app.pendencia_pauta:
        saida.append(dict(app.pendencia_pauta))
    return saida


def _resumo_pauta(app) -> dict | None:
    """O resumo da pauta para o Início, com 'fontes' (quantas cadastradas) e
    'configurada' (há fonte, ou já houve sincronização ou importação): o
    passo "Pauta" dos Primeiros passos só se dá por feito com configurada."""
    pauta = app.pauta_ou_none()
    if pauta is None:
        return None
    try:
        resumo = dict(pauta.resumo_inicio() or {})
    except Exception as erro:
        log.warning("resumo da pauta indisponível: %s", erro)
        return None
    if "fontes" not in resumo:
        try:
            resumo["fontes"] = len(pauta.fontes())
        except Exception:
            resumo["fontes"] = 0
    if "configurada" not in resumo:
        resumo["configurada"] = bool(resumo.get("fontes") or resumo.get("ultima_sincronizacao"))
    resumo["fontes"] = int(resumo.get("fontes") or 0)
    resumo["configurada"] = bool(resumo.get("configurada"))
    return resumo


def estado(p: Pedido) -> dict:
    app = p.app
    cfg = app.cfg
    cfg.recarregar()
    try:
        acervo = servicos.resumo_acervo(cfg)
    except Exception:
        acervo = {"processos": 0, "transcricoes": 0}
    lotes = []
    try:
        for info in servicos.ultimos_lotes(cfg, 5):
            lotes.append(_lote(info))
    except Exception as erro:
        log.debug("últimos lotes: %s", erro)
    recentes = []
    for doc in servicos.transcricoes_recentes(cfg, 5):
        numero = servicos.numero_no_nome(doc)
        recentes.append({"numero": numero.formatado if numero is not None else doc.stem,
                         "arquivo": str(doc), "quando": _quando(doc)})
    return {
        "nome": NOME, "versao": __version__, "modo": app.modo,
        "usuario": cfg.texto("geral", "nome_usuario"),
        "pastas": pastas(cfg),
        "pendencias": _pendencias(app),
        "resumo": {"processos": acervo.get("processos", 0),
                   "transcricoes": acervo.get("transcricoes", 0),
                   "ultimos_lotes": lotes, "transcricoes_recentes": recentes,
                   "pauta": _resumo_pauta(app)},
        "tarefas": [t.como_dict() for t in app.tarefas.listar(so_ativas=True)],
        "audiencia": {"ativa": app.audiencia.ativa, "estado": app.audiencia.estado,
                      "processo": app.audiencia.numero.formatado
                      if app.audiencia.numero is not None and app.audiencia.ativa else None},
    }


def _quando(caminho: Path) -> str | None:
    try:
        return datetime.fromtimestamp(Path(caminho).stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None


def _lote(info) -> dict:
    return {"nome": info.nome, "quando": iso(info.quando), "total": info.total,
            "baixados": info.baixados, "falhas": info.falhas, "pasta": str(info.pasta),
            "relatorio": str(info.relatorio)}


# ============================================================== configuração
def ler_config(p: Pedido) -> dict:
    cfg = p.app.cfg
    cfg.recarregar()
    return {"valores": esquema.valores(cfg), "esquema": [c.como_dict() for c in esquema.campos()],
            "arquivo": str(cfg.arquivo)}


def gravar_config(p: Pedido) -> dict:
    secao = p.campo("secao", obrigatorio=True, tipo=str)
    chave = p.campo("chave", obrigatorio=True, tipo=str)
    dados = p.json()
    if "valor" not in dados:
        raise erro_400("Falta o campo “valor” no pedido.", "campo_ausente")
    valor = esquema.gravar(p.app.cfg, secao, chave, dados["valor"])
    if secao == "pauta" and chave in ("monitorar", "intervalo_horas"):
        monitor = p.app.monitor
        if monitor is not None:
            monitor.acordar()
    p.app.hub.publicar("estado", {})
    return {"valor": valor}


def listar_tribunais(p: Pedido) -> list[dict]:
    saida = []
    for t in tribunais.carregar():
        alt = t.alternativo
        saida.append({"sigla": t.sigla, "nome": t.nome, "sistema": t.sistema,
                      "nome_sistema": t.nome_sistema, "suportado": t.suportado,
                      "alternativo": alt.sistema if alt is not None else None,
                      "chave": t.chave})
    return saida


# =================================================================== acessos
def _tribunal_do_portal(portal: str):
    m = RE_PORTAL.match((portal or "").strip())
    if not m:
        raise erro_400("Portal inválido (use o formato esaj:TJAL ou eproc:TJAL).",
                       "portal_invalido")
    sistema_, sigla = m.group(1), m.group(2).upper()
    t = tribunais.por_sigla(sigla)
    if t is None:
        raise erro_400(f"Tribunal desconhecido: {sigla}.", "portal_invalido")
    for alvo in (t, t.alternativo):
        if alvo is not None and alvo.sistema == sistema_:
            return alvo
    raise erro_400(f"O {sigla} não usa o {tribunais.NOMES_SISTEMA.get(sistema_, sistema_)}.",
                   "portal_invalido")


def _acesso(app, cofre, portal: str) -> dict:
    sistema_, _, sigla = portal.partition(":")
    usuario, senha = "", ""
    try:
        usuario, senha = cofre.obter(portal)
    except Exception:
        pass
    sessao = app.credenciais_sessao.get(portal)
    guardada = bool(senha)
    if sessao and not usuario:
        usuario = sessao[0]
    return {"portal": portal, "tribunal": sigla, "sistema": sistema_,
            "rotulo": f"{sigla} · {tribunais.NOMES_SISTEMA.get(sistema_, sistema_)}",
            "usuario": usuario, "tem_senha": guardada or bool(sessao and sessao[1]),
            "guardada": guardada, "so_agora": bool(sessao) and not guardada,
            "modo": (app.cfg.texto(sistema_, "login") or "senha").lower()}


def _portais(app, cofre) -> list[str]:
    portais: list[str] = []

    def incluir(portal: str) -> None:
        if portal and portal not in portais:
            portais.append(portal)

    t = tribunais.por_sigla(app.cfg.texto("unidade", "tribunal"))
    if t is not None:
        for alvo in (t, t.alternativo):
            if alvo is not None and alvo.suportado:
                incluir(alvo.portal)
    try:
        for portal in cofre.portais():
            if RE_PORTAL.match(portal):
                incluir(portal)
    except Exception:
        pass
    for portal in app.credenciais_sessao:
        incluir(portal)
    return portais


def listar_acessos(p: Pedido) -> list[dict]:
    cofre = servicos.cofre()
    return [_acesso(p.app, cofre, portal) for portal in _portais(p.app, cofre)]


def gravar_acesso(p: Pedido) -> dict:
    app = p.app
    t = _tribunal_do_portal(p.campo("portal", obrigatorio=True, tipo=str))
    portal = t.portal
    dados = p.json()
    modo = dados.get("modo")
    if modo is not None:
        modos = ("senha", "manual") if t.sistema == "eproc" else ("senha", "certificado", "manual")
        if modo not in modos:
            raise erro_400("Forma de entrar inválida para este portal.", "valor_invalido")
        app.cfg.definir(t.sistema, "login", modo)
    cofre = servicos.cofre()
    if "usuario" in dados or "senha" in dados:
        usuario = str(dados.get("usuario") or "").strip()
        senha = str(dados.get("senha") or "")
        lembrar = p.campo("lembrar", padrao=True, tipo=bool)
        try:
            guardado_u, guardada_s = cofre.obter(portal)
        except Exception:
            guardado_u, guardada_s = "", ""
        sessao = app.credenciais_sessao.get(portal, ("", ""))
        # Senha em branco no pedido = manter a que já existe (o campo da tela
        # não mostra a senha guardada).
        senha = senha or guardada_s or sessao[1]
        usuario = usuario or guardado_u or sessao[0]
        if lembrar:
            if usuario or senha:
                cofre.guardar(portal, usuario, senha)
            app.credenciais_sessao.pop(portal, None)
        else:
            if guardada_s or guardado_u:
                cofre.apagar(portal)
            if usuario or senha:
                app.credenciais_sessao[portal] = (usuario, senha)
    app.hub.publicar("estado", {})
    return _acesso(app, cofre, portal)


# ================================================== endereços dos portais
def listar_enderecos(p: Pedido) -> list[dict]:
    """As correções feitas pelo usuário (enderecos-locais.json)."""
    saida = []
    for e in tribunais.enderecos_corrigidos():
        sistema_, _, sigla = e["portal"].partition(":")
        saida.append(dict(e, rotulo_portal=f"{sigla} · {tribunais.NOMES_SISTEMA.get(sistema_, sistema_)}"))
    return saida


def _enderecos(portal: str) -> dict:
    t = _tribunal_do_portal(portal)
    return {"portal": t.portal, "rotulo": f"{t.sigla} · {t.nome_sistema}",
            "enderecos": tribunais.enderecos(t.portal)}


def enderecos_do_portal(p: Pedido) -> dict:
    return _enderecos(p.params["portal"])


def corrigir_endereco(p: Pedido) -> dict:
    """Corrige (ou, em branco, devolve ao catálogo) o endereço de um portal."""
    t = _tribunal_do_portal(p.campo("portal", obrigatorio=True, tipo=str))
    grau = p.campo("grau", padrao="base" if t.sistema == "esaj" else "1g", tipo=str).strip()
    if not re.fullmatch(r"base|[12]g(_\d{2})?", grau):
        raise erro_400("Grau inválido (use base, 1g, 2g ou 1g_71).", "valor_invalido")
    url = p.campo("url", padrao="", tipo=str).strip()
    if url and not re.match(r"^https?://[^\s/]+", url, re.I):
        raise erro_400("Informe o endereço completo do portal, começando com https://.",
                       "valor_invalido")
    if len(url) > 500:
        raise erro_400("O endereço é longo demais.", "valor_invalido")
    tribunais.definir_endereco(t.portal, grau, url)
    log.info("Endereço do %s (%s) %s.", t.portal, grau, f"corrigido para {url}" if url
             else "devolvido ao catálogo")
    return _enderecos(t.portal)


def apagar_acesso(p: Pedido) -> dict:
    app = p.app
    portal = p.params["portal"]
    if not RE_PORTAL.match(portal):
        raise erro_400("Portal inválido.", "portal_invalido")
    servicos.cofre().apagar(portal)
    app.credenciais_sessao.pop(portal, None)
    app.hub.publicar("estado", {})
    return {"portal": portal}


def tribunal_pedido(texto: str, sistema_: str = ""):
    """'TJAL', 'esaj:TJAL' ou ('TJAL', 'eproc') -> Tribunal suportado."""
    texto = (texto or "").strip()
    if ":" in texto:
        return _tribunal_do_portal(texto)
    t = tribunais.por_sigla(texto)
    if t is None:
        raise erro_400(f"Tribunal desconhecido: {texto or '(vazio)'}.", "tribunal_invalido")
    if sistema_ and t.sistema != sistema_:
        if t.alternativo is not None and t.alternativo.sistema == sistema_:
            t = t.alternativo
        else:
            raise erro_400(f"O {t.sigla} não usa o "
                           f"{tribunais.NOMES_SISTEMA.get(sistema_, sistema_)}.",
                           "tribunal_invalido")
    if not t.suportado:
        raise erro_400(f"O {t.sigla} usa um sistema que o Helestron ainda não acessa "
                       "(só e-SAJ e eProc).", "tribunal_invalido")
    return t


def credenciais_de(app, portal: str) -> tuple[str, str] | None:
    usuario, senha = servicos.CofreMisto(servicos.cofre(), app.credenciais_sessao).obter(portal)
    return (usuario, senha) if usuario and senha else None


def testar_acesso(p: Pedido) -> dict:
    """Testa exatamente o portal da linha: {tribunal, sistema} ("esaj" ou
    "eproc"). Sem o sistema, o principal do tribunal (o e-SAJ no TJAL) - por
    isso a tela manda o sistema: senão o "Testar" do eProc testava o e-SAJ."""
    app = p.app
    sistema_ = (p.campo("sistema", padrao="", tipo=str) or "").strip().lower()
    if sistema_ and sistema_ not in tribunais.SUPORTADOS:
        raise erro_400("Sistema inválido (use esaj ou eproc).", "valor_invalido")
    t = tribunal_pedido(p.campo("tribunal", obrigatorio=True, tipo=str), sistema_)
    opcoes = servicos.opcoes_download(app.cfg)
    credenciais = credenciais_de(app, t.portal)

    def alvo(tw):
        tw.definir_status(f"Abrindo o {t.nome_sistema} do {t.sigla}…")
        servicos.testar_login(t, opcoes, tw.contexto(), credenciais)
        tw.definir_status("Acesso confirmado.")
        return {"portal": t.portal,
                "mensagem": f"Acesso ao {t.sigla} · {t.nome_sistema} confirmado."}

    tw = app.tarefas.iniciar("teste_login", f"Testar o acesso ao {t.sigla} · {t.nome_sistema}",
                             alvo, (NAVEGADOR,), chave="teste_login")
    return {"tarefa": tw.id}


# =================================================================== diálogos
def _janela_com(app, metodo: str):
    janela = app.janela
    funcao = getattr(janela, metodo, None) if janela is not None else None
    if funcao is None or not getattr(janela, "tem_dialogos", False):
        raise ErroApi(409, "sem_dialogo",
                      "A escolha pela janela não está disponível neste modo; use o envio de "
                      "arquivo da página.")
    return funcao


def tipos_pywebview(tipos) -> list[str]:
    """["Planilhas|*.xlsx;*.xls"] -> ["Planilhas (*.xlsx;*.xls)"] (formato da pywebview).

    A pywebview só aceita letras, números e espaço na descrição, e padrões
    '*.ext' separados por ';' - o resto é limpo aqui, para um filtro mal
    escrito não derrubar o diálogo.
    """
    saida = []
    for item in tipos or []:
        descricao, _, padroes = str(item).partition("|")
        descricao = re.sub(r"[^\w ]+", " ", descricao).strip() or "Arquivos"
        validos = [x.strip() for x in padroes.split(";")
                   if re.fullmatch(r"\*\.(\w+|\*)", x.strip())]
        if validos:
            saida.append(f"{descricao} ({';'.join(validos)})")
    return saida


def dialogo_arquivo(p: Pedido) -> dict:
    funcao = _janela_com(p.app, "dialogo_arquivo")
    titulo = p.campo("titulo", padrao="Escolher arquivo", tipo=str)
    inicial = p.campo("inicial", padrao="", tipo=str)
    caminho = funcao(titulo, tipos_pywebview(p.campo("tipos", padrao=[], tipo=list)), inicial)
    return {"caminho": str(caminho) if caminho else None}


def dialogo_pasta(p: Pedido) -> dict:
    funcao = _janela_com(p.app, "dialogo_pasta")
    titulo = p.campo("titulo", padrao="Escolher pasta", tipo=str)
    inicial = p.campo("inicial", padrao="", tipo=str)
    caminho = funcao(titulo, inicial)
    return {"caminho": str(caminho) if caminho else None}


# ===================================================================== abrir
def pastas_permitidas(app) -> list[Path]:
    """Onde /api/abrir pode abrir: as pastas do usuário, e só elas."""
    cfg = app.cfg
    lista = [cfg.pasta_acervo, cfg.pasta_sigilosos, servicos.pasta_pauta(cfg), caminhos.LOGS,
             servicos.base_usuario()]
    nuvem = cfg.texto("compartilhar", "pasta_nuvem")
    # A raiz de uma unidade (D:\ ou /) nunca: abriria qualquer arquivo dela.
    if nuvem and len(Path(nuvem).parts) > 1:
        lista.append(Path(nuvem))
    return [Path(x) for x in lista]


def dentro_das_permitidas(app, alvo: Path) -> bool:
    return any(servicos.dentro_ou_igual(alvo, raiz) for raiz in pastas_permitidas(app))


def abrir(p: Pedido) -> dict:
    tipo = p.campo("tipo", obrigatorio=True, tipo=str)
    alvo = p.campo("alvo", obrigatorio=True, tipo=str).strip()
    if tipo == "url":
        if not alvo.lower().startswith("https://") or any(c in alvo for c in "\r\n\x00 "):
            raise ErroApi(403, "endereco_recusado", "Só abro endereços https://.")
        # O "Abrir a página" da folha só aparece quando o navegador já falhou
        # uma vez: repetir a falha calado deixava a folha igual, sem resposta.
        try:
            aberto = sistema.abrir_endereco(alvo) is not False
        except Exception as erro:
            log.warning("não consegui abrir %s no navegador: %s", alvo, erro)
            aberto = False
        if not aberto:
            raise ErroApi(409, "navegador_nao_abriu",
                          "Não consegui abrir o navegador. Copie o endereço e cole-o no "
                          f"navegador: {alvo}")
        return {"aberto": alvo}
    if tipo not in ("pasta", "arquivo"):
        raise erro_400("Tipo inválido (use pasta, arquivo ou url).", "valor_invalido")
    caminho = Path(os.path.expandvars(alvo)).expanduser()
    if not caminho.is_absolute() or not dentro_das_permitidas(p.app, caminho):
        raise ErroApi(403, "fora_das_pastas",
                      "Só abro pastas e arquivos do acervo, dos sigilosos, da pauta e dos "
                      "registros do Helestron.", alvo)
    if tipo == "arquivo":
        if caminho.suffix.lower() in EXECUTAVEIS:
            raise ErroApi(403, "arquivo_recusado", "Este tipo de arquivo não é aberto pelo "
                                                    "Helestron.")
        if not caminho.is_file():
            raise ErroApi(404, "arquivo_inexistente",
                          f"O arquivo {caminho.name} não existe mais (foi movido ou apagado).")
        sistema.abrir_arquivo(caminho)
        return {"aberto": str(caminho)}
    if caminho.is_file():
        sistema.abrir_pasta(caminho.parent, selecionar=caminho)
    else:
        sistema.abrir_pasta(caminho)
    return {"aberto": str(caminho)}


# ================================================================ verificação
def _item(i) -> dict:
    return {"nome": getattr(i, "nome", ""), "situacao": getattr(i, "situacao", ""),
            "detalhe": getattr(i, "detalhe", ""), "acao": getattr(i, "acao", ""),
            "obrigatorio": bool(getattr(i, "obrigatorio", False)),
            "codigo": getattr(i, "codigo", "")}


def verificacao(p: Pedido) -> list[dict]:
    return [_item(i) for i in servicos.verificar_instalacao(False, p.app.cfg)]


def verificacao_completa(p: Pedido) -> dict:
    app = p.app

    def alvo(tw):
        itens = []

        def ao_item(i):
            itens.append(_item(i))
            tw.definir_progresso(len(itens), 0, getattr(i, "nome", ""))

        tw.definir_status("Conferindo a instalação (cerca de um minuto)…")
        servicos.verificar_instalacao(True, app.cfg, ao_item=ao_item)
        falhas = [i for i in itens if i["situacao"] == "falha" and i["obrigatorio"]]
        avisos = [i for i in itens if i["situacao"] != "ok"]
        tw.definir_status("Verificação concluída.")
        return {"itens": itens, "resultado": "falha" if falhas else "aviso" if avisos else "ok"}

    tw = app.tarefas.iniciar("verificacao", "Verificar a instalação", alvo, chave="verificacao")
    return {"tarefa": tw.id}


def encerrar(p: Pedido) -> dict:
    p.app.encerrar_em_segundo_plano()
    return {"encerrando": True}


# ==================================================================== tarefas
def _tarefa(p: Pedido):
    tw = p.app.tarefas.obter(p.params["id"])
    if tw is None:
        raise ErroApi(404, "tarefa_inexistente", "Esta tarefa não existe mais.")
    return tw


def listar_tarefas(p: Pedido) -> list[dict]:
    lista = p.app.tarefas.listar()
    lista.sort(key=lambda t: t.inicio, reverse=True)
    return [t.como_dict() for t in lista]


def obter_tarefa(p: Pedido) -> dict:
    return _tarefa(p).como_dict(com_itens=True)


def parar_tarefa(p: Pedido) -> dict:
    tw = _tarefa(p)
    tw.pedir_parada()
    return tw.como_dict()


def responder_pergunta(p: Pedido) -> dict:
    dados = p.json()
    if "valor" not in dados:
        raise erro_400("Falta o campo “valor” no pedido.", "campo_ausente")
    try:
        pergunta = p.app.perguntas.responder(p.params["id"], dados["valor"])
    except ValueError as erro:
        if type(erro).__name__ != "ValueError":
            raise
        raise erro_400(maiuscula(str(erro)) + ".", "valor_invalido") from erro
    return {"id": pergunta.id}


def cancelar_pergunta(p: Pedido) -> dict:
    pergunta = p.app.perguntas.cancelar(p.params["id"])
    return {"id": pergunta.id}


# ==================================================================== eventos
def eventos(p: Pedido) -> Fluxo:
    app = p.app

    def escrever(tratador) -> None:
        assinatura = app.hub.assinar()
        try:
            tratador.iniciar_fluxo()
            tratador.wfile.write(b"retry: 2000\n\n")
            # Quem reconecta no meio de uma pergunta precisa vê-la de novo.
            for pergunta in app.perguntas.abertas():
                tratador.wfile.write(formatar_sse("pergunta", pergunta))
            tratador.wfile.write(formatar_sse("estado", {}))
            tratador.wfile.flush()
            while True:
                item = assinatura.proximo(INTERVALO_PING_S)
                if item is FIM:
                    break
                if item is None:
                    tratador.wfile.write(formatar_sse("ping", {}))
                else:
                    tipo, dados = item
                    tratador.wfile.write(formatar_sse(tipo, dados))
                tratador.wfile.flush()
                app.hub.tocar()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError,
                ValueError):
            pass
        finally:
            assinatura.cancelar()
            app.hub.tocar()

    return Fluxo(escrever)


# ============================================================ janela e teste
def mostrar_janela(p: Pedido) -> dict:
    app = p.app
    if app.fechando:
        raise ErroApi(409, "encerrando", "O Helestron está fechando.")
    janela = app.janela
    if janela is None:
        return {"mostrou": False}
    mostrou = janela.mostrar()
    return {"mostrou": bool(mostrou) if mostrou is not None else True}


def _autoteste(app):
    if app.autoteste is None:
        raise ErroApi(404, "sem_autoteste", "O autoteste não está ligado nesta execução.")
    return app.autoteste


def autoteste_passo(p: Pedido) -> dict:
    secao = p.campo("secao", obrigatorio=True, tipo=str)
    if not re.fullmatch(r"[\w-]{1,40}", secao):
        raise erro_400("Seção inválida.", "valor_invalido")
    return _autoteste(p.app).passo(secao, p.json())


def autoteste_fim(p: Pedido) -> dict:
    resultado = _autoteste(p.app).fim(p.json())
    threading.Timer(0.3, p.app.encerrar_em_segundo_plano).start()
    return resultado
