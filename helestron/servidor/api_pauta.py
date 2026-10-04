"""API da Pauta de audiências: a fachada helestron.pauta.servico.ServicoPauta.

O ServicoPauta (seção 8.10 da especificação) é criado no primeiro uso pela
Aplicacao; se o pacote da pauta faltar na instalação, todas estas rotas
respondem 503 {codigo: "pauta_indisponivel"} e o resto do programa segue.

Sincronizar e capturar usam o navegador dos portais (o mesmo perfil e a
mesma sessão do download): rodam como tarefa, com o recurso 'navegador' -
não andam junto com um download. E a mesma senha: a guardada no cofre e a
digitada com "Lembrar neste computador" desligado (app.credenciais_sessao,
como em api_processos), que vale até fechar o Helestron.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import servicos
from ..nucleo import cnj, tribunais
from ..tarefas import NAVEGADOR
from .api_geral import iso
from .rede import ErroApi, Pedido, Roteador, erro_400

log = logging.getLogger("servidor.pauta")

SISTEMAS = ("esaj", "eproc")


def registrar(r: Roteador) -> None:
    r.adicionar("GET", "/api/pauta", listar)
    r.adicionar("GET", "/api/pauta/fontes", fontes)
    r.adicionar("POST", "/api/pauta/fontes", salvar_fonte)
    r.adicionar("DELETE", "/api/pauta/fontes/{id}", remover_fonte)
    r.adicionar("POST", "/api/pauta/sincronizar", sincronizar)
    r.adicionar("POST", "/api/pauta/capturar", capturar)
    r.adicionar("POST", "/api/pauta/importar", importar)
    r.adicionar("POST", "/api/pauta/exportar", exportar)
    r.adicionar("GET", "/api/pauta/alteracoes", alteracoes)
    r.adicionar("POST", "/api/pauta/alteracoes/vistas", alteracoes_vistas)
    r.adicionar("POST", "/api/pauta/monitoramento", monitoramento)
    r.adicionar("POST", "/api/pauta/baixar-autos", baixar_autos)


# ===================================================================== apoio
def data(texto, campo: str) -> date | None:
    if texto in (None, ""):
        return None
    if isinstance(texto, date):
        return texto
    try:
        return date.fromisoformat(str(texto).strip()[:10])
    except ValueError as erro:
        raise erro_400(f"Data inválida em “{campo}” (use AAAA-MM-DD).", "data_invalida") from erro


def momento(texto, campo: str) -> datetime | None:
    if texto in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(texto).strip())
    except ValueError as erro:
        raise erro_400(f"Data e hora inválidas em “{campo}”.", "data_invalida") from erro


def _inteiro(cfg, chave: str, padrao: int) -> int:
    try:
        valor = cfg.texto("pauta", chave)
        return int(valor) if str(valor).strip() else padrao
    except (ValueError, TypeError):
        return padrao


def periodo_padrao(cfg) -> tuple[date, date]:
    """O período da sincronização: [pauta] dias_atras a dias_a_frente."""
    hoje = date.today()
    return (hoje - timedelta(days=max(0, _inteiro(cfg, "dias_atras", 7))),
            hoje + timedelta(days=max(1, _inteiro(cfg, "dias_a_frente", 60))))


def _periodo(de, ate, padrao: tuple[date, date]) -> tuple[date, date]:
    de = de or padrao[0]
    ate = ate or padrao[1]
    if ate < de:
        raise erro_400("A data final vem antes da inicial.", "periodo_invalido")
    if (ate - de).days > 3 * 366:
        raise erro_400("Escolha um período de até três anos.", "periodo_invalido")
    return de, ate


def _com_senha_da_sessao(app, servico) -> None:
    """A senha "só por agora" vale também para a pauta (o mesmo dicionário do
    download: o que mudar nos Acessos vale na hora)."""
    sessao = getattr(app, "credenciais_sessao", None)
    if sessao is not None:
        try:
            servico.credenciais_sessao = sessao
        except Exception as erro:          # serviço sem o atributo: segue com o cofre
            log.debug("credenciais da sessão: %s", erro)


def monitoramento_dict(app, servico) -> dict:
    try:
        dados = dict(servico.monitoramento() or {})
    except Exception as erro:
        log.debug("monitoramento: %s", erro)
        dados = {}
    monitor = app.monitor
    proxima = getattr(monitor, "proxima", None) if monitor is not None else None
    dados.setdefault("ativo", app.cfg.flag("pauta", "monitorar"))
    dados.setdefault("intervalo_horas", _inteiro(app.cfg, "intervalo_horas", 6))
    dados["proxima"] = iso(proxima) if proxima is not None else dados.get("proxima")
    return dados


def _tribunal(sigla: str, sistema_: str) -> str:
    sigla = (sigla or "").strip().upper()
    if sistema_ not in SISTEMAS:
        raise erro_400("Escolha o sistema: e-SAJ ou eProc.", "sistema_invalido")
    if not sigla:
        raise erro_400("Informe o tribunal (ex.: TJAL).", "tribunal_invalido")
    t = tribunais.por_sigla(sigla)
    if t is None:
        raise erro_400(f"Tribunal desconhecido: {sigla}.", "tribunal_invalido")
    if sistema_ not in {x.sistema for x in (t, t.alternativo) if x is not None}:
        raise erro_400(f"O {t.sigla} não usa o {tribunais.NOMES_SISTEMA.get(sistema_, sistema_)}.",
                       "tribunal_invalido")
    return t.sigla


# ==================================================================== consulta
def listar(p: Pedido) -> dict:
    app = p.app
    servico = app.pauta()
    hoje = date.today()
    de = data(p.arg("de"), "de") or hoje
    ate = data(p.arg("ate"), "ate") or hoje + timedelta(days=max(1, _inteiro(app.cfg,
                                                                            "dias_a_frente", 60)))
    de, ate = _periodo(de, ate, (de, ate))
    sistema_ = p.arg("sistema").strip().lower()
    if sistema_ in ("todos", "*"):
        sistema_ = ""
    dados = dict(servico.listar(de, ate, sistema=sistema_, situacao=p.arg("situacao").strip(),
                                busca=p.arg("busca").strip()))
    dados.setdefault("audiencias", [])
    dados.setdefault("resumo", {})
    dados["ultima_sincronizacao"] = iso(servico.ultima_sincronizacao())
    dados["monitoramento"] = monitoramento_dict(app, servico)
    dados["periodo"] = {"de": de.isoformat(), "ate": ate.isoformat()}
    return dados


def fontes(p: Pedido) -> list[dict]:
    return list(p.app.pauta().fontes())


def salvar_fonte(p: Pedido) -> dict:
    servico = p.app.pauta()
    sistema_ = p.campo("sistema", obrigatorio=True, tipo=str).strip().lower()
    sigla = _tribunal(p.campo("tribunal", obrigatorio=True, tipo=str), sistema_)
    rotulo = p.campo("rotulo", padrao="", tipo=str).strip() or \
        f"{sigla} · {tribunais.NOMES_SISTEMA.get(sistema_, sistema_)}"
    url = p.campo("url", padrao="", tipo=str).strip()
    if url and not url.lower().startswith(("https://", "http://")):
        raise erro_400("O endereço da pauta deve começar por https://.", "valor_invalido")
    fonte = servico.salvar_fonte(sigla, sistema_, rotulo[:120], url)
    p.app.hub.publicar("estado", {})
    return fonte


def remover_fonte(p: Pedido) -> dict:
    p.app.pauta().remover_fonte(p.params["id"])
    p.app.hub.publicar("estado", {})
    return {"id": p.params["id"]}


def alteracoes(p: Pedido) -> list[dict]:
    return list(p.app.pauta().alteracoes(momento(p.arg("desde"), "desde")))


def alteracoes_vistas(p: Pedido) -> dict:
    p.app.pauta().marcar_vistas()
    p.app.hub.publicar("estado", {})
    return {}


# ==================================================================== tarefas
def sincronizar(p: Pedido) -> dict:
    app = p.app
    servico = app.pauta()
    lista = p.campo("fontes", padrao=None)
    if lista is not None and not isinstance(lista, list):
        raise erro_400("“fontes” deve ser uma lista de ids.", "campo_invalido")
    de, ate = _periodo(data(p.campo("de"), "de"), data(p.campo("ate"), "ate"),
                       periodo_padrao(app.cfg))
    _com_senha_da_sessao(app, servico)

    def alvo(tw):
        tw.definir_status("Entrando nos portais…")
        resultado = servico.sincronizar(tw.contexto(), [str(x) for x in lista] if lista else None,
                                        de, ate)
        app.pendencia_pauta = None
        # O status final já é a frase do serviço ("8 audiências conferidas ·
        # 1 nova…"): não é trocado por outra mais pobre.
        if not tw.status or tw.status.startswith("Entrando"):
            tw.definir_status("Pauta atualizada.")
        return resultado

    tw = app.tarefas.iniciar("pauta_sincronizar", "Sincronizar a pauta", alvo, (NAVEGADOR,),
                             chave="pauta_sincronizar")
    return {"tarefa": tw.id}


def capturar(p: Pedido) -> dict:
    app = p.app
    servico = app.pauta()
    sistema_ = p.campo("sistema", obrigatorio=True, tipo=str).strip().lower()
    sigla = _tribunal(p.campo("tribunal", obrigatorio=True, tipo=str), sistema_)
    _com_senha_da_sessao(app, servico)

    def alvo(tw):
        tw.definir_status("Abrindo o portal: vá até a pauta de audiências e clique em "
                          "“Capturar esta tela”.")
        return servico.capturar(tw.contexto(), sigla, sistema_)

    tw = app.tarefas.iniciar("pauta_capturar",
                             f"Capturar a pauta no {tribunais.NOMES_SISTEMA.get(sistema_, sistema_)}"
                             f" do {sigla}", alvo, (NAVEGADOR,), chave="pauta_capturar")
    return {"tarefa": tw.id}


def importar(p: Pedido) -> dict:
    app = p.app
    servico = app.pauta()
    if p.tipo_corpo == "multipart/form-data":
        with p.envio(app.pasta_envios()) as envio:
            arquivo = envio.arquivo("arquivo")
            if arquivo is None:
                raise erro_400("Envie o relatório no campo “arquivo”.", "campo_ausente")
            resultado = servico.importar(arquivo.caminho)
            if isinstance(resultado, dict) and arquivo.nome:
                # o nome que o usuário reconhece, e não o aleatório do envio
                resultado["arquivo"] = Path(arquivo.nome.replace("\\", "/")).name
    else:
        caminho = Path(p.campo("caminho", obrigatorio=True, tipo=str).strip().strip('"'))
        if not caminho.is_absolute():
            raise erro_400("Informe o caminho completo do arquivo.", "valor_invalido")
        if not caminho.is_file():
            raise ErroApi(404, "arquivo_inexistente", f"Não encontrei o arquivo {caminho.name}.")
        resultado = servico.importar(caminho)
    app.hub.publicar("estado", {})
    return resultado


def exportar(p: Pedido) -> dict:
    app = p.app
    servico = app.pauta()
    de, ate = _periodo(data(p.campo("de"), "de"), data(p.campo("ate"), "ate"),
                       (date.today(), date.today() + timedelta(days=30)))
    filtros = {}
    for chave in ("sistema", "situacao", "busca"):
        valor = str(p.campo(chave, padrao="") or "").strip()
        if chave == "sistema" and valor.lower() in ("todos", "*"):
            valor = ""
        if valor:
            filtros[chave] = valor
    # a escolha feita na janela vale - inclusive o "não" com o Ajuste ligado; sem o
    # campo, o serviço usa o Ajuste ([pauta] incluir_partes_sigilosos)
    incluir = p.campo("incluir_partes_sigilosos", padrao=None, tipo=bool)
    if incluir is not None:
        filtros["incluir_partes_sigilosos"] = bool(incluir)
    destino = servicos.pasta_pauta(app.cfg)
    problema = servicos.problema_nas_pastas(app.cfg.pasta_acervo, app.cfg.pasta_sigilosos, destino)
    if problema:
        raise ErroApi(409, "pastas_em_conflito", problema)
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = servico.exportar(de, ate, destino, **filtros)
    return {"arquivo": str(arquivo), "pasta": str(destino)}


def monitoramento(p: Pedido) -> dict:
    app = p.app
    servico = app.pauta()
    ativo = p.campo("ativo", obrigatorio=True, tipo=bool)
    intervalo = p.campo("intervalo_horas", padrao=None, tipo=int)
    if intervalo is None:
        intervalo = _inteiro(app.cfg, "intervalo_horas", 6)
    if not 1 <= intervalo <= 72:
        raise erro_400("O intervalo deve ficar entre 1 e 72 horas.", "valor_invalido")
    servico.configurar_monitoramento(ativo, intervalo)
    if not ativo:
        app.pendencia_pauta = None
    if app.monitor is not None:
        app.monitor.acordar()
    app.hub.publicar("estado", {})
    return monitoramento_dict(app, servico)


def baixar_autos(p: Pedido) -> dict:
    from .api_processos import iniciar_lote

    app = p.app
    servico = app.pauta()
    ids = p.campo("ids", padrao=None)
    if ids is not None and not isinstance(ids, list):
        raise erro_400("“ids” deve ser uma lista.", "campo_invalido")
    hoje = date.today()
    de, ate = _periodo(data(p.campo("de"), "de"), data(p.campo("ate"), "ate"),
                       (hoje, hoje + timedelta(days=7)))
    audiencias = servico.listar(de, ate).get("audiencias", [])
    if ids:
        escolhidos = {str(x) for x in ids}
        audiencias = [a for a in audiencias if str(a.get("id")) in escolhidos]
    numeros, vistos = [], set()
    for a in audiencias:
        try:
            n = cnj.ler(str(a.get("processo") or ""))
        except cnj.NumeroInvalido:
            continue
        if cnj.chave(n) not in vistos:
            vistos.add(cnj.chave(n))
            numeros.append(n)
    if not numeros:
        raise ErroApi(409, "vazio", "Nenhuma audiência do período tem número de processo para "
                                    "baixar.")
    nome = f"Pauta {de.isoformat()} a {ate.isoformat()}" if de != ate else f"Pauta {de.isoformat()}"
    tw = iniciar_lote(app, numeros, nome,
                      titulo=f"Baixar os autos da pauta ({len(numeros)} "
                             f"processo{'s' if len(numeros) != 1 else ''})")
    return {"tarefa": tw.id, "processos": len(numeros)}
