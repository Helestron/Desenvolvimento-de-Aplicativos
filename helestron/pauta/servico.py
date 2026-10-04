"""A fachada da pauta para a API (seção 8.10 da especificação).

O servidor (helestron/servidor/api_pauta.py) só conhece esta classe; a
linha de comando (pauta/cli.py) e o monitor do aplicativo também. Ela junta
o banco (armazem), o reconhecimento (tabelas), a leitura no portal
(navegacao, captura), a importação e a exportação.

O que vale para todas as entradas:

* sincronizar e capturar usam o login, o perfil do navegador e as
  perguntas do DOWNLOAD (helestron.download.motor: as mesmas fábricas de
  navegador e de portal, o mesmo cofre de senhas). Sem senha guardada no
  modo "senha", o navegador abre na tela de entrada para o usuário entrar -
  como no download. No monitoramento (ninguém olhando) isso não acontece:
  a fonte fica pendente, com o aviso "Entre no portal para continuar o
  monitoramento", em vez de abrir uma janela do nada;
* uma fonte que falha não derruba as outras; só quando todas falham a
  tarefa termina como "falhou", com o motivo de cada uma;
* SIGILO: a audiência é sigilosa se o portal disse (segredo de justiça) ou
  se os autos do processo estão na pasta de sigilosos - a mesma regra do
  compartilhamento e da transcrição. A planilha mascara as partes dela por
  padrão e nunca é gravada dentro do acervo.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from ..nucleo import caminhos, cnj
from . import exportacao, importacao, modelos
from . import regras as regras_mod
from .armazem import Armazem
from .modelos import JA_PASSOU, SEM_AUDIENCIA, como_dict, normalizar_texto
from .monitor import (INTERVALO_MAX_H, INTERVALO_MIN_H, Agenda, ConfigMonitoramento,
                      ler_flag)
from .tabelas import Reconhecedor

log = logging.getLogger("pauta.servico")

DICA_INSTALAR = ("Instale o Helestron de novo com o Helestron-Setup: ele conserta a instalação "
                 "sem apagar os seus dados.")
MENSAGEM_LOGIN = ("Entre no portal para continuar o monitoramento: sem a senha guardada (ou no "
                  "login por certificado), o {nome} só pode ser aberto com você à frente. Na tela "
                  "Pauta, clique em Sincronizar.")
CACHE_SIGILOSOS_S = 15.0


class ErroPauta(RuntimeError):
    """Falha da pauta com a frase pronta para o usuário."""


def _agora() -> datetime:
    return datetime.now().replace(microsecond=0)


def _iso(momento: datetime | None) -> str | None:
    return momento.replace(microsecond=0).isoformat() if momento else None


def _frase(erro: BaseException) -> str:
    texto = str(erro).strip() or type(erro).__name__
    return texto[:1].upper() + texto[1:]


class ServicoPauta:
    """A pauta de audiências: consulta, sincronização, captura, importação, exportação."""

    def __init__(self, cfg, arquivo_banco: Path | None = None,
                 eventos: Callable[[str, dict], None] | None = None, *,
                 regras=None, fabrica_navegador=None, fabrica_portal=None, cofre=None,
                 relogio: Callable[[], datetime] | None = None):
        self.cfg = cfg
        padrao = getattr(caminhos, "ARQUIVO_PAUTA", None) or Path(caminhos.LOCAL) / "pauta.sqlite3"
        self.arquivo_banco = Path(arquivo_banco or padrao)
        self.eventos = eventos
        self.armazem = Armazem(self.arquivo_banco)
        # Injetáveis (testes, ou outro portal): o padrão é o do download.
        self._regras = regras
        self.fabrica_navegador = fabrica_navegador
        self.fabrica_portal = fabrica_portal
        self.cofre = cofre
        self.relogio = relogio or _agora
        self.espera_pagina_s = 20.0
        self.limite_captura_s: float | None = None
        self._sigilosos: tuple[float, str, set[str]] = (0.0, "", set())

    # ================================================================ apoio
    @property
    def regras(self):
        return self._regras or regras_mod.carregar()

    def fechar(self) -> None:
        self.armazem.fechar()

    def _evento(self, tipo: str, dados: dict) -> None:
        if self.eventos is None:
            return
        try:
            self.eventos(tipo, dados)
        except Exception as erro:          # o evento é aviso; nunca derruba o trabalho
            log.debug("evento %s não publicado: %s", tipo, erro)

    def _hoje(self) -> date:
        return self.relogio().date()

    def _numeros_sigilosos(self) -> set[str]:
        """As chaves CNJ dos processos com autos (ou transcrição) na pasta de sigilosos.

        A regra do motor (transcricao.documento.processo_sigiloso): um PDF com
        o número em <sigilosos>/ ou <sigilosos>/<lote>/. Lida uma vez a cada
        poucos segundos, e não uma vez por audiência.
        """
        try:
            pasta = Path(self.cfg.pasta_sigilosos)
        except Exception:
            return set()
        quando, onde, numeros = self._sigilosos
        if onde == str(pasta) and _time.monotonic() - quando < CACHE_SIGILOSOS_S:
            return numeros
        numeros = set()
        try:
            arquivos = [*pasta.glob("*.pdf"), *pasta.glob("*/*.pdf"), *pasta.glob("*/*.docx")]
        except OSError:
            arquivos = []
        for p in arquivos:
            try:
                numeros.add(cnj.chave(cnj.ler_nome_arquivo(p.stem)))
            except cnj.NumeroInvalido:
                continue
        self._sigilosos = (_time.monotonic(), str(pasta), numeros)
        return numeros

    def _dicts(self, audiencias) -> list[dict]:
        sigilosos = self._numeros_sigilosos()
        saida = []
        for a in audiencias:
            d = como_dict(a)
            if not d["sigiloso"] and a.processo and modelos.chave_processo(a.processo) in sigilosos:
                d["sigiloso"] = True
            saida.append(d)
        return saida

    # ============================================================= consulta
    def listar(self, de: date, ate: date, sistema="", situacao="", busca="") -> dict:
        """{audiencias: [dict], resumo: {total, hoje, semana, por_situacao, por_tipo}}."""
        audiencias = self.armazem.listar(de, ate)
        sistema = (sistema or "").strip().lower().replace("-", "")
        if sistema in ("todos", "*"):
            sistema = ""
        if sistema:
            audiencias = [a for a in audiencias if a.sistema == sistema]
        situacao = (situacao or "").strip()
        if situacao:
            alvo = modelos.situacao_reconhecida(situacao, self.regras) or situacao
            audiencias = [a for a in audiencias
                          if normalizar_texto(a.situacao) == normalizar_texto(alvo)]
        busca = normalizar_texto(busca)
        if busca:
            digitos = "".join(ch for ch in busca if ch.isdigit())
            so_numero = bool(digitos) and len(digitos) >= 4 and not any(
                ch.isalpha() for ch in busca)

            def casa(a) -> bool:
                if so_numero and digitos in "".join(ch for ch in a.processo if ch.isdigit()):
                    return True
                texto = normalizar_texto(" ".join((a.processo, a.partes, a.classe, a.tipo,
                                                   a.tipo_original, a.local, a.magistrado,
                                                   a.observacoes, a.tribunal, a.situacao)))
                return all(p in texto for p in busca.split())

            audiencias = [a for a in audiencias if casa(a)]
        dicts = self._dicts(audiencias)
        return {"audiencias": dicts, "resumo": self.resumo(dicts)}

    def resumo(self, audiencias: list[dict]) -> dict:
        hoje = self._hoje()
        semana = hoje + timedelta(days=7)
        acontecem = [a for a in audiencias if a.get("situacao") not in SEM_AUDIENCIA]
        por_situacao: dict[str, int] = {}
        por_tipo: dict[str, int] = {}
        for a in audiencias:
            por_situacao[a.get("situacao") or ""] = por_situacao.get(a.get("situacao") or "", 0) + 1
            por_tipo[a.get("tipo") or ""] = por_tipo.get(a.get("tipo") or "", 0) + 1
        return {"total": len(audiencias),
                "hoje": sum(1 for a in acontecem if a.get("data") == hoje.isoformat()),
                "semana": sum(1 for a in acontecem
                              if hoje.isoformat() <= str(a.get("data")) <= semana.isoformat()),
                "por_situacao": por_situacao, "por_tipo": por_tipo}

    def fontes(self) -> list[dict]:
        return self.armazem.fontes()

    def salvar_fonte(self, tribunal, sistema, rotulo, url="") -> dict:
        sistema = (sistema or "").strip().lower()
        if sistema not in ("esaj", "eproc"):
            raise ValueError("Escolha o sistema da fonte: e-SAJ ou eProc.")
        if not (tribunal or "").strip():
            raise ValueError("Informe o tribunal da fonte (ex.: TJAL).")
        if url and not str(url).lower().startswith(("https://", "http://")):
            raise ValueError("O endereço da pauta deve começar por https://.")
        rotulo = (rotulo or "").strip() or \
            f"{str(tribunal).strip().upper()} · {modelos.NOMES_SISTEMA.get(sistema, sistema)}"
        return self.armazem.salvar_fonte(tribunal, sistema, rotulo, (url or "").strip())

    def remover_fonte(self, id_fonte) -> None:
        self.armazem.remover_fonte(str(id_fonte))

    def alteracoes(self, desde: datetime | None = None) -> list[dict]:
        alteracoes = self.armazem.alteracoes(desde)
        sigilosos = self._numeros_sigilosos()
        for alt in alteracoes:
            a = alt.get("audiencia") or {}
            if not a.get("sigiloso") and a.get("processo") and \
                    modelos.chave_processo(a["processo"]) in sigilosos:
                a["sigiloso"] = True
        return alteracoes

    def marcar_vistas(self) -> None:
        self.armazem.marcar_vistas()

    def ultima_sincronizacao(self) -> datetime | None:
        texto = self.armazem.meta("ultima_sincronizacao")
        try:
            return datetime.fromisoformat(texto) if texto else None
        except ValueError:
            return None

    # ------------------------------------------------------- monitoramento
    def config_monitoramento(self) -> ConfigMonitoramento:
        return ConfigMonitoramento.de_config(self.cfg)

    def monitoramento(self) -> dict:
        conf = self.config_monitoramento()
        com_rota = [f for f in self.armazem.fontes() if f.get("url")]
        proxima = Agenda(self.relogio).proxima(conf, self.ultima_sincronizacao(), bool(com_rota))
        return {"ativo": conf.ativo, "intervalo_horas": conf.intervalo_horas,
                "dias_atras": conf.dias_atras, "dias_a_frente": conf.dias_a_frente,
                "proxima": _iso(proxima), "fontes_monitoradas": len(com_rota)}

    def configurar_monitoramento(self, ativo: bool, intervalo_horas: int) -> dict:
        try:
            horas = int(intervalo_horas)
        except (TypeError, ValueError) as erro:
            raise ValueError("O intervalo do monitoramento deve ser um número de horas.") from erro
        if not INTERVALO_MIN_H <= horas <= INTERVALO_MAX_H:
            raise ValueError(f"O intervalo deve ficar entre {INTERVALO_MIN_H} e "
                             f"{INTERVALO_MAX_H} horas.")
        self.cfg.definir("pauta", "monitorar", bool(ativo))
        self.cfg.definir("pauta", "intervalo_horas", horas)
        return self.monitoramento()

    def resumo_inicio(self) -> dict:
        """{hoje, semana, proxima, ultima_sincronizacao, alteracoes_nao_vistas} - a tela Início."""
        agora = self.relogio()
        hoje = agora.date()
        lista = self._dicts(self.armazem.listar(hoje, hoje + timedelta(days=7)))
        resumo = self.resumo(lista)
        agora_hm = f"{agora:%H:%M}"
        proxima = None
        for a in self._dicts(self.armazem.futuras(hoje, 200)):
            if a.get("situacao") in SEM_AUDIENCIA + JA_PASSOU:
                continue
            if a.get("data") == hoje.isoformat() and a.get("hora") and a["hora"] < agora_hm:
                continue
            proxima = a
            break
        return {"hoje": resumo["hoje"], "semana": resumo["semana"], "proxima": proxima,
                "ultima_sincronizacao": _iso(self.ultima_sincronizacao()),
                "alteracoes_nao_vistas": self.armazem.nao_vistas()}

    # ============================================================ o portal
    def _tribunal(self, sigla: str, sistema: str):
        from ..nucleo import tribunais

        t = tribunais.por_sigla(sigla)
        if t is None:
            raise ErroPauta(f"Tribunal desconhecido: {sigla}. Confira a fonte da pauta.")
        for candidato in (t, t.alternativo):
            if candidato is not None and candidato.sistema == sistema:
                return candidato
        raise ErroPauta(f"O {t.sigla} não usa o {modelos.NOMES_SISTEMA.get(sistema, sistema)}.")

    def _motor(self):
        try:
            from ..download import motor
        except ImportError as erro:
            raise ErroPauta(f"O componente de acesso aos portais não está instalado "
                            f"({getattr(erro, 'name', '') or erro}). {DICA_INSTALAR}") from erro
        return motor

    def _opcoes(self, tribunal, visivel: bool = False):
        from ..download.modelos import OpcoesDownload

        opcoes = OpcoesDownload.de_config(self.cfg)
        opcoes = replace(opcoes, atualizar_ia=False)
        if visivel:
            opcoes = replace(opcoes, mostrar_navegador=True)
        return opcoes

    def _credenciais(self, tribunal, opcoes) -> tuple[str, str] | None:
        if opcoes.modo_login(tribunal.sistema) != "senha":
            return None
        cofre = self.cofre
        if cofre is None:
            try:
                from ..nucleo.cofre_senhas import CofreSenhas

                cofre = CofreSenhas(caminhos.ARQUIVO_SENHAS)
            except Exception as erro:
                log.warning("o cofre de senhas não abriu: %s", erro)
                return None
        try:
            usuario, senha = cofre.obter(tribunal.portal)
        except Exception as erro:
            log.warning("não consegui ler a senha guardada de %s: %s", tribunal.portal, erro)
            return None
        return (usuario, senha) if usuario and senha else None

    @staticmethod
    def _em_segundo_plano(ctx) -> bool:
        """O Contexto de fundo do monitor (servidor.trabalhos.ContextoFundo)."""
        return getattr(ctx, "pediu_login", None) is not None

    def _acesso(self, tribunal, ctx, visivel: bool = False):
        """(opções, credenciais) - a regra do motor (_opcoes_do_grupo) para o login."""
        opcoes = self._opcoes(tribunal, visivel)
        credenciais = self._credenciais(tribunal, opcoes)
        sistema = tribunal.sistema
        precisa_de_alguem = (opcoes.modo_login(sistema) in ("manual", "certificado")
                             or credenciais is None)
        if precisa_de_alguem and self._em_segundo_plano(ctx):
            try:
                ctx.pediu_login = True
            except Exception:
                pass
            raise ErroPauta(MENSAGEM_LOGIN.format(
                nome=f"{tribunal.nome_sistema} do {tribunal.sigla}"))
        if opcoes.modo_login(sistema) == "senha" and credenciais is None:
            log.info("Sem usuário e senha guardados para o %s do %s: o navegador abre na tela "
                     "de entrada para você entrar.", tribunal.nome_sistema, tribunal.sigla)
            opcoes = replace(opcoes, login={**opcoes.login, sistema: "manual"})
        return opcoes, credenciais

    def _navegador(self, tribunal, opcoes):
        fabrica = self.fabrica_navegador or self._motor().fabrica_navegador_padrao
        return fabrica(tribunal, opcoes)

    def _portal(self, nav, tribunal, opcoes, ctx, credenciais):
        fabrica = self.fabrica_portal or self._motor().fabrica_portal_padrao
        return fabrica(nav, tribunal, opcoes, ctx, credenciais)

    def _reconhecedor(self, tribunal_sigla: str, sistema: str, fonte: str) -> Reconhecedor:
        return Reconhecedor(self.regras, sistema, tribunal_sigla, fonte=fonte, estrito=True,
                            agora=self.relogio())

    # ========================================================= sincronizar
    def sincronizar(self, ctx, fontes: list[str] | None, de: date, ate: date) -> dict:
        """Lê a pauta de cada fonte no portal e grava. ctx = Contexto da tarefa."""
        from ..download.modelos import Cancelado

        todas = self.armazem.fontes()
        if fontes:
            pedidas = {str(x) for x in fontes}
            escolhidas = [f for f in todas if f["id"] in pedidas]
            if not escolhidas:
                raise ErroPauta("As fontes pedidas não existem mais. Confira as fontes da pauta "
                                "em Ajustes.")
        else:
            escolhidas = todas
        if not escolhidas:
            raise ErroPauta("Nenhuma fonte da pauta configurada. Escolha o tribunal e o sistema "
                            "(e-SAJ ou eProc) primeiro.")
        resultado = {"novas": 0, "atualizadas": 0, "canceladas": 0, "removidas": 0, "total": 0,
                     "alteracoes": 0, "fontes": [], "erros": [], "avisos": [],
                     "periodo": {"de": de.isoformat(), "ate": ate.isoformat()}}
        sucesso = False
        for i, fonte in enumerate(escolhidas):
            if ctx.cancelado():
                raise Cancelado()
            rotulo = fonte.get("rotulo") or fonte["id"]
            try:
                ctx.progresso(i, len(escolhidas), rotulo)
            except Exception:
                pass
            try:
                parcial = self._sincronizar_fonte(ctx, fonte, de, ate)
            except Cancelado:
                raise
            except Exception as erro:
                if ctx.cancelado():
                    raise Cancelado() from erro
                mensagem = _frase(erro)
                log.warning("Pauta - %s: %s", rotulo, mensagem,
                            exc_info=type(erro).__name__ not in (
                                "LoginFalhou", "PortalIndisponivel", "PautaNaoEncontrada",
                                "ErroPauta", "SessaoPerdida"))
                self.armazem.atualizar_fonte(fonte["id"], ultimo_erro=mensagem[:500])
                resultado["erros"].append({"fonte": fonte["id"], "rotulo": rotulo,
                                           "mensagem": mensagem})
                try:
                    ctx.avisar(f"Pauta: {rotulo}", mensagem)
                except Exception:
                    pass
                continue
            sucesso = True
            resultado["fontes"].append(parcial)
            for chave in ("novas", "atualizadas", "canceladas", "removidas", "total",
                          "alteracoes"):
                resultado[chave] += parcial.get(chave, 0)
            resultado["avisos"] += parcial.get("avisos", [])
        try:
            ctx.progresso(len(escolhidas), len(escolhidas), "")
        except Exception:
            pass
        if sucesso:
            self.armazem.definir_meta("ultima_sincronizacao", self.relogio())
            self._publicar_mudancas(resultado)
        if not sucesso:
            raise ErroPauta("Não consegui ler a pauta: " + "; ".join(
                f"{e['rotulo']} — {e['mensagem'].rstrip('.')}" for e in resultado["erros"]) + ".")
        ctx.status(self._frase_resultado(resultado))
        return resultado

    @staticmethod
    def _frase_resultado(r: dict) -> str:
        def plural(n, um, varios):
            return f"{n} {um if n == 1 else varios}"
        partes = [plural(r.get("total", 0), "audiência conferida", "audiências conferidas")]
        mudancas = r.get("novas", 0) + r.get("atualizadas", 0) + r.get("removidas", 0)
        if mudancas:
            detalhes = []
            if r.get("novas"):
                detalhes.append(plural(r["novas"], "nova", "novas"))
            if r.get("atualizadas"):
                detalhes.append(plural(r["atualizadas"], "alterada", "alteradas"))
            if r.get("removidas"):
                detalhes.append(plural(r["removidas"], "saiu da pauta", "saíram da pauta"))
            partes.append(", ".join(detalhes))
        else:
            partes.append("nenhuma mudança")
        if r.get("erros"):
            partes.append(plural(len(r["erros"]), "fonte com problema", "fontes com problema"))
        return " · ".join(partes) + "."

    def _publicar_mudancas(self, resultado: dict) -> None:
        self._evento("pauta", {"tipo": "atualizada", "dados": {
            k: resultado.get(k, 0) for k in ("novas", "atualizadas", "canceladas", "removidas",
                                              "total")}})
        if resultado.get("alteracoes"):
            self._evento("pauta", {"tipo": "alteracoes", "dados": {
                "novas": resultado["alteracoes"], "nao_vistas": self.armazem.nao_vistas()}})

    def _sincronizar_fonte(self, ctx, fonte: dict, de: date, ate: date) -> dict:
        from ..download.modelos import SessaoPerdida
        from .navegacao import ExtratorAutomatico

        tribunal = self._tribunal(fonte["tribunal"], fonte["sistema"])
        opcoes, credenciais = self._acesso(tribunal, ctx)
        nome = f"{tribunal.nome_sistema} do {tribunal.sigla}"
        primeira = not fonte.get("ultima_sincronizacao")
        with self._navegador(tribunal, opcoes) as nav:
            portal = self._portal(nav, tribunal, opcoes, ctx, credenciais)
            ctx.status(f"Entrando no {nome}…")
            portal.entrar()
            if not (getattr(portal, "base", "") or ""):
                # eProc com um endereço por seção judiciária (TRF4, TRF2): o login
                # espera um processo para saber a seção. A rota lembrada (da captura)
                # diz qual é.
                lembrada = fonte.get("url") or ""
                if not lembrada or not hasattr(portal, "_candidatos_atuais"):
                    raise ErroPauta(f"O {nome} tem um endereço por seção judiciária. Abra a "
                                    "pauta com “Capturar no portal”: o endereço fica lembrado.")
                portal._candidatos_atuais = [lembrada.split("controlador.php")[0]]
                portal.entrar()
            extrator = ExtratorAutomatico(
                nav, portal, self.regras,
                self._reconhecedor(tribunal.sigla, tribunal.sistema, fonte["id"]), ctx, fonte,
                self.espera_pagina_s)
            for tentativa in (1, 2):
                try:
                    leitura = extrator.extrair(de, ate)
                    break
                except SessaoPerdida:
                    if tentativa == 2:
                        raise
                    ctx.status(f"A sessão do {nome} caiu; entrando de novo…")
                    portal.entrar()
        ctx.status(f"Gravando a pauta do {nome}…")
        balanco = self.armazem.gravar(leitura.audiencias, fonte["id"], leitura.cobertura(de, ate),
                                      registrar_novas=not primeira, agora=self.relogio())
        self.armazem.atualizar_fonte(fonte["id"], url=leitura.url or fonte.get("url") or "",
                                     menu=leitura.menu or fonte.get("menu") or "",
                                     ultima_sincronizacao=self.relogio(), ultimo_erro="")
        parcial = balanco.como_dict()
        parcial.update({"fonte": fonte["id"], "rotulo": fonte.get("rotulo") or "",
                        "paginas": leitura.paginas, "url": leitura.url,
                        "periodo_aplicado": leitura.periodo_aplicado,
                        "avisos": [f"{fonte.get('rotulo') or nome}: {x}" for x in leitura.avisos]})
        return parcial

    # ============================================================ capturar
    def capturar(self, ctx, tribunal: str, sistema: str) -> dict:
        """Captura assistida: abre o portal visível, com a barra do Helestron (8.4)."""
        from .captura import LIMITE_PADRAO_S, CapturaAssistida
        from .navegacao import ExtratorAutomatico, parametros

        sistema = (sistema or "").strip().lower()
        t = self._tribunal((tribunal or "").strip().upper(), sistema)
        id_fonte = Armazem.id_fonte(t.sigla, sistema)
        fonte = self.armazem.fonte(id_fonte) or self.salvar_fonte(t.sigla, sistema, "")
        opcoes, credenciais = self._acesso(t, ctx, visivel=True)
        nome = f"{t.nome_sistema} do {t.sigla}"
        primeira = not fonte.get("ultima_sincronizacao")
        with self._navegador(t, opcoes) as nav:
            portal = self._portal(nav, t, opcoes, ctx, credenciais)
            ctx.status(f"Entrando no {nome}…")
            portal.entrar()
            reconhecedor = self._reconhecedor(t.sigla, sistema, id_fonte)
            cap = CapturaAssistida(nav, self.regras, reconhecedor, ctx,
                                   self.limite_captura_s or LIMITE_PADRAO_S, nome)
            cap.instalar()
            # poupa o caminho: abre a pauta lembrada (no eProc, pelo link assinado)
            extrator = ExtratorAutomatico(nav, portal, self.regras, reconhecedor, ctx, fonte,
                                          self.espera_pagina_s)
            url = fonte.get("url") or ""
            if url and sistema == "eproc":
                url = extrator.link_por_acao(parametros(url).get("acao", ""))
            if url:
                extrator.abrir(url)
            elif not (extrator.url_atual() or "").startswith("http"):
                inicio = getattr(portal, "base", "") or next(iter(t.urls_para(None)), "")
                if inicio:
                    extrator.abrir(inicio)
            ctx.status("O portal está aberto no navegador: vá até a pauta de audiências e "
                       "clique em “Capturar esta tela” na barra do Helestron; no fim, em "
                       "“Concluir”.")
            try:
                ctx.avisar("Captura da pauta",
                           f"O {nome} abriu no navegador. Vá até a pauta de audiências e clique em "
                           "“Capturar esta tela” (em cada página, se houver mais de uma); no fim, "
                           "clique em “Concluir”.")
            except Exception:
                pass
            resultado = cap.esperar()
        audiencias = resultado.audiencias
        balanco = self.armazem.gravar(audiencias, id_fonte, None, registrar_novas=not primeira,
                                      agora=self.relogio())
        campos = {}
        if resultado.url:
            campos.update(url=resultado.url, modo="capturado")
        if audiencias:
            campos.update(ultima_sincronizacao=self.relogio(), ultimo_erro="")
            self.armazem.definir_meta("ultima_sincronizacao", self.relogio())
        if campos:
            self.armazem.atualizar_fonte(id_fonte, **campos)
        dados = balanco.como_dict()
        dados.update({"capturadas": len(audiencias), "telas": resultado.telas,
                      "url": resultado.url, "motivo": resultado.motivo, "fonte": id_fonte})
        if audiencias:
            self._publicar_mudancas(dados)
            ctx.status(f"Captura concluída: {len(audiencias)} audiência"
                       f"{'s' if len(audiencias) != 1 else ''}"
                       + (". O endereço ficou lembrado para o monitoramento." if resultado.url
                          else "."))
        else:
            ctx.status("Nenhuma audiência foi capturada.")
        return dados

    # ============================================================ importar
    def importar(self, caminho: Path) -> dict:
        """Relatório exportado do SAJ/eProc (planilha, HTML, PDF, DOCX) - seção 8.6."""
        try:
            rec = importacao.ler_relatorio(Path(caminho), self.regras, agora=self.relogio())
        except importacao.RelatorioInvalido as erro:
            raise ValueError(_frase(erro)) from erro
        audiencias = rec.audiencias
        # A mesma audiência já trazida do portal (processo, data e hora) não é
        # duplicada: o relatório só completa o que faltava nela.
        existentes: dict[tuple, modelos.Audiencia] = {}
        if audiencias:
            de = min(a.data for a in audiencias)
            ate = max(a.data for a in audiencias)
            for a in self.armazem.listar(de, ate):
                if a.sistema != "arquivo" and a.processo:
                    existentes[(modelos.chave_processo(a.processo), a.data, a.hora)] = a
        novas_lista, completar = [], []
        for a in audiencias:
            chave = (modelos.chave_processo(a.processo), a.data, a.hora) if a.processo else None
            alvo = existentes.get(chave) if chave else None
            if alvo is None:
                novas_lista.append(a)
                continue
            for campo in ("local", "link", "classe", "partes", "magistrado", "observacoes"):
                if not getattr(alvo, campo) and getattr(a, campo):
                    setattr(alvo, campo, getattr(a, campo))
            alvo.sigiloso = alvo.sigiloso or a.sigiloso
            completar.append(alvo)
        balanco = self.armazem.gravar(novas_lista, "arquivo", None, registrar_novas=False,
                                      agora=self.relogio())
        atualizadas = balanco.atualizadas
        for alvo in completar:
            b = self.armazem.gravar([alvo], alvo.fonte, None, registrar_novas=False,
                                    agora=self.relogio())
            atualizadas += b.atualizadas
        resultado = {"novas": balanco.novas, "atualizadas": atualizadas,
                     "ignoradas": rec.ignoradas, "avisos": list(rec.avisos),
                     "total": len(audiencias), "arquivo": Path(caminho).name}
        self._evento("pauta", {"tipo": "atualizada", "dados": {
            "novas": resultado["novas"], "atualizadas": atualizadas, "total": len(audiencias)}})
        return resultado

    # ============================================================ exportar
    def _dentro_do_acervo(self, destino: Path) -> bool:
        try:
            acervo = Path(self.cfg.pasta_acervo)
        except Exception:
            return False
        try:
            from .. import servicos

            return bool(servicos.dentro_ou_igual(destino, acervo))
        except Exception:
            try:
                return destino.resolve().is_relative_to(acervo.resolve())
            except Exception:
                return False

    def exportar(self, de, ate, destino_pasta: Path, **filtros) -> Path:
        """A planilha do período (seção 8.9). Filtros: sistema, situacao, busca,
        incluir_partes_sigilosos (padrão: [pauta] incluir_partes_sigilosos)."""
        destino = Path(destino_pasta)
        if self._dentro_do_acervo(destino):
            raise ValueError("A planilha da pauta não pode ser gravada dentro do acervo: ela traz "
                             "as partes dos processos em segredo de justiça, e tudo o que está no "
                             "acervo é lido pela IA. Escolha outra pasta.")
        incluir = filtros.pop("incluir_partes_sigilosos", None)
        if incluir is None:
            incluir = ler_flag(self.cfg, "incluir_partes_sigilosos", False)
        escolhidos = {k: str(filtros.get(k) or "").strip() for k in ("sistema", "situacao",
                                                                     "busca")}
        dados = self.listar(de, ate, **escolhidos)
        alteracoes = self.armazem.alteracoes(de=de, ate=ate)
        sigilosos = self._numeros_sigilosos()
        sistema = escolhidos["sistema"].lower().replace("-", "")
        saida_alt = []
        for alt in alteracoes:
            a = alt.get("audiencia") or {}
            if sistema and sistema not in ("todos", "*") and a.get("sistema") != sistema:
                continue
            if a.get("processo") and modelos.chave_processo(a["processo"]) in sigilosos:
                a["sigiloso"] = True
            saida_alt.append(alt)
        return exportacao.exportar(dados["audiencias"], saida_alt, de, ate, destino,
                                   incluir_partes_sigilosos=bool(incluir),
                                   filtros={k: v for k, v in escolhidos.items() if v},
                                   agora=self.relogio())
