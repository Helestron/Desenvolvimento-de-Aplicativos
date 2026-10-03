"""Um eProc de mentira, servido pelo próprio Chromium (context.route), sem rede.

Modelado nos seletores reais (ver app/download/eproc.py e a pesquisa em
relatorios/pesquisa-eproc.md): login legado (#txtUsuario/#pwdSenha/#sbmEntrar)
com segundo fator (#txtAcessoCodigo/#btnValidar), Keycloak (#kc-form-login,
#username/#password/#kc-login, #otp), captcha (#divInfraCaptcha), escolha de
perfil (botões data-descricao), pesquisa rápida (txtNumProcessoPesquisaRapida),
consulta processual com o ajax processos_consulta_por_numprocesso
(linkProcessoAssinado), página do processo com capa, partes, #tblEventos
paginado (select#selPaginacaoT + alterarPagina), documentos
a.infraLinkDocumento, moldura com iframe#conteudoIframe,
acessar_documento_implementacao e o Download Completo.

As armadilhas do portal de verdade estão aqui: todo link interno leva um
hash assinado para a sessão (link montado à mão ou de outra sessão cai em
"Link sem assinatura" - e fica registrado em ``sem_assinatura``); páginas em
ISO-8859-1; a tela de login traz de saída o aviso "após 5 tentativas com
senha incorreta..."; a sessão pode ser encerrada no meio do download.

O host termina em .invalid: o canal direto do Playwright (contexto.request,
que não passa pelas rotas) falha na hora, sem nunca alcançar a internet, e o
portal precisa cair para o canal da própria janela - o mesmo caminho de uma
rede com proxy.
"""

from __future__ import annotations

import glob
import hashlib
import http.cookies
import io
import json
import os
import traceback
import urllib.parse
import uuid
from dataclasses import dataclass, field
from html import escape

from app.download.navegador import Navegador

from testes import apoio_download as apoio

HOST = "eproc1g.tjfalso.invalid"
BASE = f"https://{HOST}/eproc/"
HOST_SSO = "sso.tjfalso.invalid"
SSO = f"https://{HOST_SSO}/realms/eproc/"
HOST_FORA = "eproc-fora.tjfalso.invalid"      # endereço candidato que não existe
USUARIO, SENHA, CODIGO = "RS012345", "s3nh@ fácil%;", "123456"
POR_PAGINA = 4

P1 = apoio.numero("5000001", tr="21", origem="0001")      # completo: 7 eventos, 2 páginas
P_SIG = apoio.numero("5000002", tr="21", origem="0001")   # segredo de justiça, sem acesso
P_NAO = apoio.numero("5000003", tr="21", origem="0001")   # não existe
P_CONS = apoio.numero("5000004", tr="21", origem="0001")  # só a consulta processual acha
P_SIGOK = apoio.numero("5000005", tr="21", origem="0001")  # sigiloso, com acesso
P_EXP = apoio.numero("5000006", tr="21", origem="0001")   # a sessão cai no 2º documento
RELACIONADO = apoio.numero("5000099", tr="21", origem="0001")


def jpeg_bytes() -> bytes:
    from PIL import Image
    saida = io.BytesIO()
    Image.new("RGB", (160, 100), (200, 40, 30)).save(saida, "JPEG")
    return saida.getvalue()


@dataclass
class DocFalso:
    rotulo: str
    mimetype: str
    conteudo: bytes
    content_type: str
    falha: bool = False          # o servidor não entrega por caminho nenhum
    so_iframe: bool = False      # o link reescrito é recusado; só o src da moldura vale
    id: str = ""


@dataclass
class EventoFalso:
    numero: int
    data: str
    descricao: str
    docs: list[DocFalso] = field(default_factory=list)


@dataclass
class ProcessoFalso:
    numero: object
    eventos: list[EventoFalso]
    sigilo: str = "Sem Sigilo (Nível 0)"
    sem_acesso: bool = False
    pela_rapida: bool = True
    completo: bool = True
    expirar_no_doc: int = 0


def _pdf(paginas, rotulo):
    return apoio.pdf_bytes(paginas, rotulo)


def processos_padrao() -> dict[str, ProcessoFalso]:
    decisao = ("<html><head><meta http-equiv='Content-Type' content='text/html; "
               "charset=iso-8859-1'></head><body><p class='titulo'>DECISÃO</p>"
               "<p>Defiro a tutela de urgência. Citação e intimação.</p></body></html>"
               ).encode("cp1252")
    sentenca = ("<html><body><p class='titulo'>SENTENÇA</p><p>Julgo procedente o pedido; "
                "condenação em custas — publique-se.</p><p class='dispositivo'>Intimem-se."
                "</p></body></html>").encode("cp1252")
    video = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 3000
    p1 = ProcessoFalso(P1, [
        EventoFalso(1, "10/01/2024 14:22:01", "PETIÇÃO INICIAL", [
            DocFalso("INIC1", "pdf", _pdf(2, "INIC1"), "application/pdf"),
            DocFalso("PROC2", "pdf", _pdf(1, "PROC2"), "application/pdf", so_iframe=True)]),
        EventoFalso(2, "11/01/2024 09:00:00", "JUNTADA DE DOCUMENTO", [
            DocFalso("FOTO1", "jpg", jpeg_bytes(), "image/jpeg")]),
        EventoFalso(3, "12/03/2024 16:40:12", "DECISÃO INTERLOCUTÓRIA", [
            DocFalso("DESPADEC1", "html", decisao, "text/html; charset=ISO-8859-1")]),
        EventoFalso(4, "20/03/2024 11:11:11", "JUNTADA DE PETIÇÃO", [
            DocFalso("PET1", "pdf", _pdf(1, "PET1"), "application/pdf", falha=True)]),
        EventoFalso(5, "01/04/2024 15:00:00", "AUDIÊNCIA REALIZADA", []),
        EventoFalso(6, "10/05/2024 18:30:00", "SENTENÇA", [
            DocFalso("SENT1", "html", sentenca, "text/html; charset=ISO-8859-1")]),
        EventoFalso(7, "15/05/2024 08:00:00", "GRAVAÇÃO DE AUDIÊNCIA", [
            DocFalso("VIDEO1", "mp4", video, "video/mp4")]),
    ])
    sig = ProcessoFalso(P_SIG, [], sigilo="Segredo de Justiça (Nível 1)", sem_acesso=True,
                        completo=False)
    cons = ProcessoFalso(P_CONS, [EventoFalso(1, "05/02/2024 10:00:00", "PETIÇÃO INICIAL", [
        DocFalso("INIC1", "pdf", _pdf(1, "CONS-INIC1"), "application/pdf")])],
        pela_rapida=False, completo=False)
    sigok = ProcessoFalso(P_SIGOK, [EventoFalso(1, "06/02/2024 10:00:00", "PETIÇÃO INICIAL", [
        DocFalso("INIC1", "pdf", _pdf(1, "SIG-INIC1"), "application/pdf")])],
        sigilo="Segredo de Justiça (Nível 1)", completo=False)
    exp = ProcessoFalso(P_EXP, [
        EventoFalso(1, "07/02/2024 10:00:00", "PETIÇÃO INICIAL", [
            DocFalso("INIC1", "pdf", _pdf(1, "EXP-INIC1"), "application/pdf")]),
        EventoFalso(2, "08/02/2024 10:00:00", "CONTESTAÇÃO", [
            DocFalso("CONT1", "pdf", _pdf(1, "EXP-CONT1"), "application/pdf")]),
        EventoFalso(3, "09/02/2024 10:00:00", "RÉPLICA", [
            DocFalso("REPLICA1", "pdf", _pdf(1, "EXP-REPLICA1"), "application/pdf")]),
    ], expirar_no_doc=2, completo=False)
    return {p.numero.digitos: p for p in (p1, sig, cons, sigok, exp)}


class EProcFalso:
    """O estado do eProc falso e o atendimento de cada requisição."""

    def __init__(self, estilo: str = "legado", captcha: bool = False, perfis=None,
                 processos: dict | None = None):
        self.estilo = estilo
        self.captcha = captcha
        self.perfis = list(perfis or [])
        self.processos = processos if processos is not None else processos_padrao()
        self.docs: dict[str, tuple[ProcessoFalso, EventoFalso, DocFalso]] = {}
        for proc in self.processos.values():
            for ev in proc.eventos:
                for i, doc in enumerate(ev.docs):
                    doc.id = f"{proc.numero.digitos[:7]}{ev.numero:03d}{i}"
                    self.docs[doc.id] = (proc, ev, doc)
        self.sessoes: dict[str, str] = {}
        self.pedidos: list[tuple[str, str]] = []
        self.sem_assinatura: list[str] = []
        self.codigos_recebidos: list[str] = []
        self.logins = 0
        self.perfil_escolhido: list[str] = []
        self.paginas_pedidas: list[str] = []
        self.completo_marcados: list[list[str]] = []
        self.completo_consultas = 0
        self.expirou: set[str] = set()
        self.docs_por_sessao: dict[tuple[str, str], int] = {}
        self.sso_etapa = ""
        self.sso_codigo = ""

    # ------------------------------------------------------------ assinatura
    @staticmethod
    def assinar(sid: str, carga: str) -> str:
        return hashlib.md5(f"{sid}|{carga}".encode()).hexdigest()

    def link(self, sid: str, acao: str, carga: str, **params) -> str:
        consulta = urllib.parse.urlencode([("acao", acao), *params.items(),
                                           ("hash", self.assinar(sid, carga))])
        return f"controlador.php?{consulta}"

    # ------------------------------------------------------------ respostas
    @staticmethod
    def _html(corpo: str, titulo: str = "eProc") -> tuple:
        pagina = (f"<!DOCTYPE html><html><head><meta charset='iso-8859-1'><title>{titulo}"
                  f"</title></head><body>{corpo}</body></html>")
        return 200, pagina.encode("cp1252", errors="xmlcharrefreplace"), \
            "text/html; charset=ISO-8859-1", {}

    def _redirecionar(self, destino: str, cabecalhos=None) -> tuple:
        # Sem 302: no Chromium, redirecionamento atendido por rota não é
        # seguido de forma confiável. O eProc também redireciona por script.
        corpo = (f"<html><head><script>location.replace({json.dumps(destino)});</script>"
                 "</head><body>Redirecionando...</body></html>")
        return 200, corpo.encode("utf-8"), "text/html; charset=utf-8", dict(cabecalhos or {})

    def _topo(self, sid: str) -> str:
        return (
            "<div id='divInfraBarraSistema'><form id='frmPesquisaRapida' method='get' "
            "action='controlador.php'><input type='hidden' name='acao' "
            "value='processo_pesquisa_rapida'>"
            f"<input type='hidden' name='hash' value='{self.assinar(sid, 'pesquisa')}'>"
            "<input type='text' id='txtNumProcessoPesquisaRapida' "
            "name='txtNumProcessoPesquisaRapida' placeholder='Pesquisa rápida'></form>"
            f"<a href='{escape(self.link(sid, 'processo_consultar', 'consultar'))}'>"
            "<span class='menu-item-text'>Consulta Processual</span></a> "
            f"<a href='{escape(self.link(sid, 'painel_adv_listar', 'painel'))}'>Painel</a>"
            "<span id='lnkUsuarioSistema'>RS012345</span></div>")

    def _sessao_encerrada(self) -> tuple:
        return self._html(
            "<form id='frmLogin' method='post' action='index.php'>"
            "<input type='hidden' name='hdnAcao' value='login'>"
            "<input type='text' id='txtUsuario' name='txtUsuario'>"
            "<input type='password' id='pwdSenha' name='pwdSenha'>"
            "<input type='submit' id='sbmEntrar' value='Entrar'></form>"
            "<textarea id='txaInfraMsg'>A sessão foi encerrada. Efetue o login novamente."
            "</textarea>")

    def _tela_login(self, erro: str = "") -> tuple:
        aviso = f"<div class='infraMensagem'>{erro}</div>" if erro else ""
        return self._html(
            "<h1>eProc - Acesso ao sistema</h1>"
            "<form id='frmLogin' method='post' action='index.php'>"
            "<input type='hidden' name='hdnAcao' value='login'>"
            "<label for='txtUsuario'>Usuário</label><input type='text' id='txtUsuario' "
            "name='txtUsuario'><label for='pwdSenha'>Senha</label>"
            "<input type='password' id='pwdSenha' name='pwdSenha'>"
            "<input type='submit' id='sbmEntrar' name='sbmEntrar' value='Entrar'></form>"
            f"{aviso}<p>Atenção: após 5 tentativas com senha incorreta, o usuário será "
            "bloqueado.</p><a href='#'>Autenticação em dois fatores</a>")

    def _tela_codigo(self, erro: str = "") -> tuple:
        aviso = f"<div class='infraMensagem'>{erro}</div>" if erro else ""
        return self._html(
            "<form id='frmValidar' method='post' action='index.php'>"
            "<p>Informe o código de 6 dígitos gerado pelo aplicativo autenticador.</p>"
            f"{aviso}<input type='text' id='txtAcessoCodigo' name='txtAcessoCodigo' "
            "maxlength='6'><button type='submit' id='btnValidar'>Validar</button>"
            "<label><input type='checkbox' name='chkNaoUsar2fa'> Não usar o 2FA neste "
            "dispositivo e navegador</label></form><a href='#'>Esqueci minha senha</a>")

    def _tela_perfis(self, sid: str) -> tuple:
        botoes = "".join(
            f"<button type='button' data-descricao='{USUARIO} / {p}' onclick=\"location.href="
            f"'{self._link_perfil(sid, i)}'\">{p}</button>" for i, p in enumerate(self.perfis))
        return self._html(f"<h2>Selecione o perfil</h2>{botoes}")

    def _link_perfil(self, sid: str, i: int) -> str:
        return self.link(sid, "pessoa_usuario_logar", "perfil", acao_origem="entrar",
                         id_usuario=str(i + 10))

    def _tela_captcha(self) -> tuple:
        return self._html(
            "<form method='post' action='index.php'><div id='divInfraCaptcha'><label>"
            "<img src='data:image/png;base64,iVBORw0KGgo=' width='120' height='40'></label>"
            "<input type='text' id='txtInfraCaptcha' name='txtInfraCaptcha'></div>"
            "<button type='submit'>Enviar</button></form>")

    def _painel(self, sid: str) -> tuple:
        return self._html(f"{self._topo(sid)}<div id='divInfraAreaTela'><h1>Painel do "
                          "Usuário</h1><p>Processos com prazo em aberto: 0</p></div>")

    # ------------------------------------------------------------ processo
    def _pagina_processo(self, sid: str, proc: ProcessoFalso, pagina: int) -> tuple:
        n = proc.numero
        proprio = self.link(sid, "processo_selecionar", f"proc:{n.digitos}", num_processo=n.digitos)
        capa = (
            "<fieldset id='fldCapa'><legend>Capa do Processo</legend>"
            f"Nº do processo: <span id='txtNumProcesso'>{n.formatado}</span><br>"
            "Classe: <span id='txtClasse'>PROCEDIMENTO COMUM CÍVEL</span><br>"
            "Competência: <span id='txtCompetencia'>Cível</span><br>"
            "Data de autuação: <span id='txtAutuacao'>10/01/2024 14:22:01</span><br>"
            "Situação: <span id='txtSituacao'>MOVIMENTO</span><br>"
            "Órgão julgador: <span id='txtOrgaoJulgador'>Juízo da 1ª Vara Cível de Porto "
            "Alegre</span><br>Juiz(a): <span id='txtMagistrado'>FULANA DE TAL</span><br>"
            f"Nível de sigilo: <span id='txtNivelSigilo'>{proc.sigilo}</span></fieldset>"
            "<table id='tblPartesERepresentantes' class='infraTable'><tr><th>AUTOR</th>"
            "<th>RÉU</th></tr><tr class='infraTrClara'><td class='autorReu'>"
            "<a class='infraNomeParte' data-parte='AUTOR'>MARIA DA SILVA</a> "
            "<span id='spnCpfParte1'>123.456.789-00</span><br>Advogado: "
            "<a onmouseover=\"infraTooltipMostrar('ADVOGADO')\">RS012345</a></td>"
            "<td class='autorReu'><a class='infraNomeParte'>BANCO EXEMPLO S.A.</a></td>"
            "</tr></table>")
        if proc.sem_acesso:
            corpo = (f"{self._topo(sid)}<div id='divInfraAreaTela'>{capa}<div class='infraAviso'>"
                     "Processo em segredo de justiça: acesso restrito às partes e procuradores "
                     "habilitados.</div></div>")
            return self._html(corpo, "eProc - Processo")
        eventos = sorted(proc.eventos, key=lambda e: -e.numero)
        total = max(1, (len(eventos) + POR_PAGINA - 1) // POR_PAGINA)
        pagina = min(max(0, pagina), total - 1)
        linhas = []
        for ev in eventos[pagina * POR_PAGINA:(pagina + 1) * POR_PAGINA]:
            docs = []
            for doc in ev.docs:
                href = escape(self.link(sid, "acessar_documento", f"doc:{doc.id}", doc=doc.id,
                                        evento=f"{ev.numero:030d}", key="k" * 64))
                if doc.rotulo == "INIC1":       # o ícone também é link (o mesmo)
                    docs.append(f"<a class='infraLinkDocumento' href='{href}' target='_blank'>"
                                "<img src='imagens/pdf.gif' alt=''></a>")
                docs.append(f"<a class='infraLinkDocumento' data-doc='{doc.id}' "
                            f"data-mimetype='{doc.mimetype}' title='{doc.rotulo} - documento' "
                            f"href='{href}' target='_blank'>{doc.rotulo}</a>")
            conteudo = " ".join(docs) or "Evento não gerou documento(s)"
            classe = "infraTrClara" if ev.numero % 2 else "infraTrEscura"
            linhas.append(
                f"<tr id='trEvento{ev.numero}' class='{classe}'><td class='infraEventoNumero'>"
                f"{ev.numero}</td><td>{ev.data}</td><td><label class='infraEventoDescricao'>"
                f"{ev.descricao}</label></td><td><label class='infraEventoUsuario' "
                f"aria-label='SERVIDOR'>USR01</label></td><td>{conteudo}</td></tr>")
        opcoes = "".join(f"<option value='{i}'{' selected' if i == pagina else ''}>{i + 1}</option>"
                         for i in range(total))
        paginacao = (f"<select id='selPaginacaoT' onchange='alterarPagina(this.value)'>{opcoes}"
                     "</select>") if total > 1 else ""
        botao = ""
        if proc.completo:
            destino = self.link(sid, "selecionar_processos_agendar_arquivo_completo",
                                f"completo:{n.digitos}", num_processo=n.digitos)
            botao = (f"<button type='button' id='btnDownloadCompletoRS' onclick=\"location.href="
                     f"'{destino}'\">Download Completo</button>")
        corpo = (
            f"<script>function alterarPagina(p) {{ if (p === 'ultima') p = '{total - 1}';"
            " document.getElementById('hdnPagina').value = p;"
            " document.getElementById('frmProcessoEventos').submit(); }</script>"
            f"{self._topo(sid)}<div id='divInfraAreaTela'>{capa}{botao}"
            f"<form id='frmProcessoEventos' method='post' action='{escape(proprio)}'>"
            f"<input type='hidden' id='hdnPagina' name='pagina' value='{pagina}'></form>"
            f"Página: {paginacao}<table id='tblEventos' class='infraTable'><tr><th>Evento</th>"
            "<th>Data/Hora</th><th>Descrição</th><th>Usuário</th><th>Documentos</th></tr>"
            f"{''.join(linhas)}</table></div>")
        return self._html(corpo, "eProc - Processo")

    def _moldura(self, sid: str, doc: DocFalso, ev: EventoFalso) -> tuple:
        carga = f"iframe:{doc.id}" if doc.so_iframe else f"doc:{doc.id}"
        src = self.link(sid, "acessar_documento_implementacao", carga,
                        acao_origem="acessar_documento", doc=doc.id, evento=f"{ev.numero:030d}",
                        key="k" * 64, mesmoGrau="S", nome_documento=doc.rotulo)
        return self._html(f"<iframe id='conteudoIframe' name='conteudoIframe' "
                          f"src='{escape(src)}' width='100%' height='600'></iframe>",
                          f"{doc.rotulo}")

    # ------------------------------------------------------------ roteiro
    def atender(self, route) -> None:
        try:
            req = route.request
            self.pedidos.append((req.method, req.url))
            partes = urllib.parse.urlsplit(req.url)
            if partes.hostname == HOST_SSO:
                resposta = self._sso(req, partes)
            elif partes.hostname == HOST:
                resposta = self._eproc(req, partes)
            else:
                route.abort("namenotresolved")
                return
            status, corpo, tipo, cabecalhos = resposta
            route.fulfill(status=status, body=corpo, headers={"Content-Type": tipo, **cabecalhos})
        except Exception:
            try:
                route.fulfill(status=500, body=traceback.format_exc(),
                              headers={"Content-Type": "text/plain; charset=utf-8"})
            except Exception:
                pass

    def _cookie(self, req) -> str:
        c = http.cookies.SimpleCookie()
        try:
            c.load(req.all_headers().get("cookie", ""))
        except http.cookies.CookieError:
            pass
        return c["PHPSESSID"].value if "PHPSESSID" in c else ""

    def _nova_sessao(self, estado: str) -> tuple[str, dict]:
        sid = uuid.uuid4().hex[:16]
        self.sessoes[sid] = estado
        return sid, {"Set-Cookie": f"PHPSESSID={sid}; Path=/eproc/"}

    def _depois_da_senha(self) -> tuple:
        if self.captcha:
            sid, cab = self._nova_sessao("captcha")
            return self._redirecionar(
                BASE + "externo_controlador.php?acao=principal&acao_retorno=login", cab)
        sid, cab = self._nova_sessao("otp")
        status, corpo, tipo, _ = self._tela_codigo()
        return status, corpo, tipo, cab

    def _depois_do_codigo(self, sid: str, cab=None) -> tuple:
        self.logins += 1
        if self.perfis:
            self.sessoes[sid] = "perfil"
            status, corpo, tipo, _ = self._tela_perfis(sid)
            return status, corpo, tipo, dict(cab or {})
        self.sessoes[sid] = "ok"
        return self._redirecionar(BASE + self.link(sid, "painel_adv_listar", "painel"), cab)

    def _sso(self, req, partes) -> tuple:
        form = urllib.parse.parse_qs(req.post_data or "", keep_blank_values=True, encoding="cp1252")
        campo = lambda nome: (form.get(nome) or [""])[0]  # noqa: E731
        tela_login = (
            "<form id='kc-form-login' method='post' action='" + SSO + "login-actions/authenticate'>"
            "<label for='username'>Usuário ou e-mail</label><input id='username' name='username' "
            "type='text'><label for='password'>Senha</label><input id='password' name='password' "
            "type='password'><input id='kc-login' name='login' type='submit' value='Entrar'>"
            "</form>{erro}")
        tela_otp = (
            "<form id='kc-otp-login-form' method='post' action='" + SSO +
            "login-actions/authenticate?etapa=otp'><label for='otp'>Código de uso único</label>"
            "<input id='otp' name='otp' autocomplete='one-time-code' type='text'>"
            "<input id='kc-login' name='login' type='submit' value='Entrar'></form>{erro}")
        if req.method == "GET":
            self.sso_etapa = "login"
            return self._html(tela_login.format(erro=""), "Entrar")
        if "etapa=otp" in (partes.query or ""):
            self.codigos_recebidos.append(campo("otp"))
            if campo("otp") != CODIGO:
                return self._html(tela_otp.format(
                    erro="<span id='input-error-otp-code'>Código inválido.</span>"), "Entrar")
            self.sso_codigo = uuid.uuid4().hex
            return self._redirecionar(BASE + "controlador.php?acao=sso_retorno&code="
                                      + self.sso_codigo)
        if campo("username") == USUARIO and campo("password") == SENHA:
            self.sso_etapa = "otp"
            return self._html(tela_otp.format(erro=""), "Entrar")
        return self._html(tela_login.format(
            erro="<span id='input-error'>Usuário ou senha inválidos.</span>"), "Entrar")

    def _eproc(self, req, partes) -> tuple:
        caminho = partes.path[len("/eproc/"):] if partes.path.startswith("/eproc/") else ""
        q = {k: v[0] for k, v in urllib.parse.parse_qs(partes.query, keep_blank_values=True).items()}
        form = urllib.parse.parse_qs(req.post_data or "", keep_blank_values=True, encoding="cp1252")
        sid = self._cookie(req)
        estado = self.sessoes.get(sid, "")
        if caminho.startswith("download72h/"):
            return 200, _pdf(5, "COMPLETO"), "application/pdf", {}
        if caminho in ("", "index.php") and req.method == "GET":
            if estado == "ok":
                return self._redirecionar(BASE + self.link(sid, "painel_adv_listar", "painel"))
            if self.estilo == "keycloak":
                return self._redirecionar(SSO + "protocol/openid-connect/auth?client_id=eproc"
                                          "&redirect_uri=" + urllib.parse.quote(BASE))
            return self._tela_login()
        if caminho == "index.php":       # POST
            if "txtAcessoCodigo" in form:
                codigo = form["txtAcessoCodigo"][0]
                self.codigos_recebidos.append(codigo)
                if estado != "otp":
                    return self._tela_login()
                if codigo != CODIGO:
                    return self._tela_codigo("Código inválido.")
                return self._depois_do_codigo(sid)
            usuario = (form.get("txtUsuario") or [""])[0]
            senha = (form.get("pwdSenha") or [""])[0]
            if usuario == USUARIO and senha == SENHA:
                return self._depois_da_senha()
            return self._redirecionar(
                BASE + "externo_controlador.php?acao=principal&acao_retorno=login_invalido")
        if caminho == "externo_controlador.php":
            if q.get("acao_retorno") == "login_invalido":
                return self._tela_login("Usuário ou senha inválidos.")
            if q.get("acao_retorno") == "login" and estado == "captcha":
                return self._tela_captcha()
            if q.get("msg"):
                return self._tela_login(escape(q["msg"]))
            return self._tela_login()
        if caminho == "controlador.php" and q.get("acao") == "sso_retorno":
            if not q.get("code") or q.get("code") != self.sso_codigo:
                return self._tela_login("Falha na autenticação.")
            self.sso_codigo = ""
            novo, cab = self._nova_sessao("otp")
            return self._depois_do_codigo(novo, cab)
        if caminho == "controlador.php" and q.get("acao") == "pessoa_usuario_logar":
            if estado != "perfil" or q.get("hash") != self.assinar(sid, "perfil"):
                return self._sessao_encerrada()
            self.perfil_escolhido.append(q.get("id_usuario", ""))
            self.sessoes[sid] = "ok"
            return self._redirecionar(BASE + self.link(sid, "painel_adv_listar", "painel"))
        if caminho in ("controlador.php", "controlador_ajax.php"):
            if estado != "ok":
                return self._sessao_encerrada()
            return self._interno(req, caminho, q, form, sid)
        return 404, "<html><body>Não encontrado</body></html>".encode(), "text/html", {}

    def _confere(self, sid: str, q: dict, carga: str, url: str) -> bool:
        if q.get("hash") == self.assinar(sid, carga):
            return True
        self.sem_assinatura.append(url)
        return False

    def _sem_assinatura(self) -> tuple:
        return self._redirecionar(BASE + "externo_controlador.php?acao=principal&msg="
                                  + urllib.parse.quote("Link sem assinatura"))

    def _interno(self, req, caminho: str, q: dict, form: dict, sid: str) -> tuple:
        acao = q.get("acao") or q.get("acao_ajax") or ""
        url = req.url
        if caminho == "controlador_ajax.php":
            if acao != "processos_consulta_por_numprocesso" or not self._confere(sid, q, "ajax", url):
                return 403, b"{}", "application/json", {}
            digitos = (form.get("numNrProcesso") or [""])[0]
            proc = self.processos.get(digitos)
            if proc is None:
                dados = {"resultados": [], "mensagem": "Processo não encontrado"}
            else:
                link = self.link(sid, "processo_selecionar", f"proc:{digitos}", num_processo=digitos)
                dados = {"resultados": [{"numProcesso": proc.numero.formatado,
                                         "linkProcessoAssinado": link}]}
            return 200, json.dumps(dados, ensure_ascii=False).encode("cp1252"), \
                "application/json; charset=ISO-8859-1", {}
        if acao == "painel_adv_listar":
            if not self._confere(sid, q, "painel", url):
                return self._sem_assinatura()
            return self._painel(sid)
        if acao == "processo_pesquisa_rapida":
            if not self._confere(sid, q, "pesquisa", url):
                return self._sem_assinatura()
            digitos = "".join(c for c in q.get("txtNumProcessoPesquisaRapida", "") if c.isdigit())
            proc = self.processos.get(digitos)
            if proc is None or not proc.pela_rapida:
                return self._html(f"{self._topo(sid)}<div id='divInfraAreaTela'>"
                                  "<div class='infraMensagem'>Processo não encontrado.</div></div>")
            return self._redirecionar(BASE + self.link(sid, "processo_selecionar",
                                                       f"proc:{digitos}", num_processo=digitos))
        if acao == "processo_consultar":
            if not self._confere(sid, q, "consultar", url):
                return self._sem_assinatura()
            ajax = (f"controlador_ajax.php?acao_ajax=processos_consulta_por_numprocesso&hash="
                    f"{self.assinar(sid, 'ajax')}")
            return self._html(
                f"{self._topo(sid)}<div id='divInfraAreaTela'><form id='frmProcessoLista' "
                "method='post' action='#'><label><input type='radio' name='tipoPesquisa' "
                "value='NU' checked> Número do processo</label><input type='text' "
                "id='numNrProcesso' name='numNrProcesso'><button type='button' "
                "id='sbmConsultar'>Consultar</button></form><div id='divAreaResultadosAjax'>"
                f"</div><script>var urlConsultaPorNumero = '{ajax}';</script></div>")
        if acao == "processo_selecionar":
            digitos = q.get("num_processo", "")
            if not self._confere(sid, q, f"proc:{digitos}", url):
                return self._sem_assinatura()
            proc = self.processos.get(digitos)
            if proc is None:
                return self._html("<div class='infraMensagem'>Processo não encontrado.</div>")
            pagina = int((form.get("pagina") or ["0"])[0] or 0)
            if req.method == "POST":
                self.paginas_pedidas.append(f"{digitos}:{pagina}")
            return self._pagina_processo(sid, proc, pagina)
        if acao in ("acessar_documento", "acessar_documento_implementacao"):
            achado = self.docs.get(q.get("doc", ""))
            if achado is None:
                return 404, b"", "text/html", {}
            proc, ev, doc = achado
            if acao == "acessar_documento":
                if not self._confere(sid, q, f"doc:{doc.id}", url):
                    return self._sem_assinatura()
                if doc.falha:
                    return (404, "<html><body>Documento indisponível</body></html>".encode(),
                            "text/html", {})
                return self._moldura(sid, doc, ev)
            carga = f"iframe:{doc.id}" if doc.so_iframe else f"doc:{doc.id}"
            if q.get("hash") != self.assinar(sid, carga):
                if doc.so_iframe:
                    return 403, b"<html><body>Acesso negado</body></html>", "text/html", {}
                self.sem_assinatura.append(url)
                return self._sem_assinatura()
            chave = (sid, proc.numero.digitos)
            self.docs_por_sessao[chave] = self.docs_por_sessao.get(chave, 0) + 1
            if (proc.expirar_no_doc and proc.numero.digitos not in self.expirou
                    and self.docs_por_sessao[chave] >= proc.expirar_no_doc):
                self.expirou.add(proc.numero.digitos)
                self.sessoes[sid] = "expirada"
                return self._sessao_encerrada()
            if doc.falha:
                return 500, b"<html><body>Erro interno</body></html>", "text/html", {}
            return 200, doc.conteudo, doc.content_type, {}
        if acao == "selecionar_processos_agendar_arquivo_completo":
            digitos = q.get("num_processo", "")
            if not self._confere(sid, q, f"completo:{digitos}", url):
                return self._sem_assinatura()
            agendar = self.link(sid, "agendar_geracao_arquivo_processo_completo", "agendar")
            caixas = "".join(
                f"<label><input type='checkbox' name='arrChkProcessos[]' value='RS|{d}|{i}' "
                f"checked> {d}</label><br>"
                for i, d in ((111, digitos), (222, RELACIONADO.digitos)))
            return self._html(
                f"{self._topo(sid)}<form id='frmProcessosSelecionados' method='post' "
                f"action='{escape(agendar)}'>{caixas}<label><input type='radio' name='qualidade' "
                "value='media' checked> Média</label><button type='submit' id='btnGerar'>"
                "GERAR ARQUIVO COMPLETO</button></form>")
        if acao == "agendar_geracao_arquivo_processo_completo":
            if not self._confere(sid, q, "agendar", url):
                return self._sem_assinatura()
            if req.method == "POST":
                self.completo_marcados.append(form.get("arrChkProcessos[]", []))
                self.completo_consultas = 0
                return self._html("<meta http-equiv='refresh' content='1'>Agendado com sucesso. "
                                  "Aguardando a geração do arquivo...")
            self.completo_consultas += 1
            if self.completo_consultas < 2:
                return self._html("<meta http-equiv='refresh' content='1'>Arquivo em "
                                  "processamento...")
            return self._html(
                f"{self._topo(sid)}<p>DOCUMENTO COMPLETO GERADO COM SUCESSO</p>"
                f"<a href='{BASE}download72h/{uuid.uuid4().hex}/arquivo.pdf'>BAIXAR ARQUIVO</a>")
        return 404, b"<html><body>Acao desconhecida</body></html>", "text/html", {}


# ------------------------------------------------------------ navegador
class NavegadorComEProc(Navegador):
    """O Navegador de verdade, com o eProc falso atendendo todas as requisições."""

    def __init__(self, falso: EProcFalso, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.falso = falso

    def abrir(self):
        super().abrir()
        self.contexto.route("**/*", self.falso.atender)
        return self


def _procurar_navegador():
    """(canal, executável) de um navegador que o Playwright consiga abrir."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import tempfile
    raiz = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "/opt/pw-browsers"
    candidatos: list[tuple[str, str | None]] = [("chromium", None), ("chrome", None),
                                                 ("msedge", None)]
    for padrao in ("chromium_headless_shell-*/chrome-*/headless_shell*",
                   "chromium-*/chrome-*/chrome", "chromium-*/chrome-*/chrome.exe"):
        candidatos += [("chromium", exe) for exe in sorted(glob.glob(f"{raiz}/{padrao}"),
                                                            reverse=True)]
    with sync_playwright() as pw:
        for canal, exe in candidatos:
            extra = {"executable_path": exe} if exe else {}
            if canal != "chromium":
                extra["channel"] = canal
            try:
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                    ctx = pw.chromium.launch_persistent_context(d, headless=True, **extra)
                    ctx.close()
                return canal, exe
            except Exception:
                continue
    return None


_NAVEGADOR = None
_PROCURADO = False


def navegador_de_teste():
    global _NAVEGADOR, _PROCURADO
    if not _PROCURADO:
        _PROCURADO = True
        try:
            _NAVEGADOR = _procurar_navegador()
        except Exception:
            _NAVEGADOR = None
    return _NAVEGADOR


def navegador(falso: EProcFalso, pasta, nome: str = "eproc-TJRS", espera_s: int = 20):
    canal, exe = navegador_de_teste()
    return NavegadorComEProc(falso, pasta / "perfis" / nome, visivel=False, canal=canal,
                             executavel=exe, espera_s=espera_s,
                             pasta_downloads=pasta / "downloads",
                             pasta_diagnostico=pasta / "diagnostico")
