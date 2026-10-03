"""Ponta a ponta: Chromium de verdade contra um e-SAJ de mentira, sem rede.

Um servidor HTTP local imita o fluxo do e-SAJ - CAS com código por e-mail,
cpopg (open.do, search.do, show.do), segredo de justiça com senha,
incidente, Pasta Digital (requestScope), salvarDocumentoPreparado /
buscarDocumentoFinalizado e getPDF.do - com as armadilhas que a base
conheceu: o botão Entrar que nasce desabilitado, o modal de senha que
existe escondido em toda página, o "Não existem informações disponíveis",
a busca que devolve LISTA, o foro que tem de vir do número (o servidor
recusa processo.foro errado, como o 56 fixo da base) e o servidor que não
monta o PDF único.

Pula sozinho se não houver Chromium que abra (o CI do Windows usa o Chrome
ou o Edge instalados; aqui, o Chromium de /opt/pw-browsers).
"""

from __future__ import annotations

import glob
import http.cookies
import json
import os
import threading
import unittest
import urllib.parse
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from app.download import esaj, modelos, motor
from app.download.esaj import PortalESAJ
from app.download.navegador import Navegador
from app.nucleo import tribunais

from testes import apoio_download as apoio

USUARIO, SENHA, CODIGO = "12345678900", "s3nh@ %;fácil", "123456"
P1 = apoio.numero("0700001", tr="02", origem="0001")
P1_INC = apoio.numero("0700001", tr="02", origem="0001", dependente="01")
P2 = apoio.numero("0700002", tr="02", origem="0001")     # sigiloso, servidor falha
P3 = apoio.numero("0700003", tr="02", origem="0001")     # inexistente
P5 = apoio.numero("0700005", tr="02", origem="0001")     # busca devolve lista
OUTRO = apoio.numero("0700099", tr="02", origem="0001")


def _par(numero, cd, ini, fim):
    return (f"nuSeqRecurso=00000&nuProcesso={numero.principal}&cdDocumento={cd}"
            f"&numInicial={ini}&numFinal={fim}&idDocumento=D{cd}-{ini}")


def _doc(titulo, cd, data, blocos, midia=None):
    filhos = [{"data": {"parametros": p, "nuPaginas": 1}} for p in blocos]
    if midia:
        filhos.append({"data": {"urlMidiaDigital": midia}})
    return {"data": {"title": titulo, "cdDocumento": cd, "dtInclusao": data}, "children": filhos}


class PortalDeMentira:
    """O estado do e-SAJ falso: processos, sessões, pedidos recebidos."""

    def __init__(self):
        self.porta = 0
        self.pedidos: list[tuple[str, str]] = []
        self.localizadores: dict[str, dict] = {}
        self.codigos_enviados: list[str] = []
        self.processos: dict[str, dict] = {}

    def montar(self):
        base = f"http://127.0.0.1:{self.porta}"
        midia = f"{base}/pastadigital/getMidia.do?gravacaoAudiencia=C%3A%5Cgrav%5Caudiencia1.mp3"
        self.processos = {
            "1K0001AAA0000": dict(numero=P1, arvore=[
                _doc("Petição Inicial", 101, "01/02/2024", [_par(P1, 101, 1, 2)]),
                _doc("Contestação", 102, "10/03/2024", [_par(P1, 102, 3, 4), _par(P1, 102, 5, 5)]),
                _doc("Termo de Audiência", 103, "20/04/2024", [_par(P1, 103, 6, 6)], midia),
            ], incidente="1K0001AAA0001"),
            "1K0001AAA0001": dict(numero=P1_INC, principal=P1, arvore=[
                _doc("Petição de cumprimento", 111, "05/05/2024", [_par(P1, 111, 1, 2)]),
            ]),
            "1K0002BBB0000": dict(numero=P2, senha="abc123", servidor_falha=True,
                                  pecas_ausentes={"202"}, arvore=[
                _doc("Petição Inicial", 201, "02/02/2024", [_par(P2, 201, 1, 2)]),
                _doc("Laudo psicossocial", 202, "03/03/2024", [_par(P2, 202, 3, 3)], midia),
            ]),
            "1K0005EEE0000": dict(numero=P5, arvore=[
                _doc("Petição Inicial", 501, "05/01/2024", [_par(P5, 501, 1, 1)]),
            ]),
            "1K0099ZZZ0000": dict(numero=OUTRO, arvore=[]),
        }
        self.por_numero = {"0700001": "1K0001AAA0000", "0700002": "1K0002BBB0000",
                           "0700005": "lista"}


def _pdf(paginas, rotulo):
    return apoio.pdf_bytes(paginas, rotulo)


class Atendente(BaseHTTPRequestHandler):
    portal: PortalDeMentira = None   # definido por classe derivada

    # ---------------------------------------------------------- utilidades
    def log_message(self, *args):     # silêncio
        pass

    def _cookies(self):
        c = http.cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            pass
        return {k: v.value for k, v in c.items()}

    def _logado(self):
        return self._cookies().get("SESSAO") == "ok"

    def _enviar(self, status=200, corpo=b"", tipo="text/html; charset=utf-8", cabecalhos=()):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        for k, v in cabecalhos:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _ir(self, local, cabecalhos=()):
        self._enviar(302, b"", cabecalhos=[("Location", local), *cabecalhos])

    def _pagina(self, corpo, logado=None):
        logado = self._logado() if logado is None else logado
        flag = "true" if logado else "false"
        return (f"<html><head><meta charset='utf-8'><title>e-SAJ</title><script>"
                f"window.sajcas={{usuarioLogadoNoCasServer:{flag}}};</script></head>"
                f"<body>{corpo}</body></html>")

    def _form(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        bruto = self.rfile.read(tamanho).decode("utf-8")
        return bruto, urllib.parse.parse_qs(bruto, keep_blank_values=True)

    # -------------------------------------------------------------- telas
    def _tela_login(self, erro=""):
        aviso = f"<div class='erro'>{erro}</div>" if erro else ""
        return ("<html><head><meta charset='utf-8'></head><body><h1>Portal de Serviços</h1>"
                "<form method='post' action='/sajcas/login'>"
                "<label>CPF/CNPJ</label><input id='usernameForm' name='username' type='text'>"
                "<label>Senha</label><input id='passwordForm' name='password' type='password'>"
                "<input id='pbEntrar' type='submit' value='Entrar' disabled></form>"
                f"{aviso}<div id='modalSenhaExpirada' style='display:none'>Senha expirada "
                "Verifique sua caixa de e-mail para cadastrar nova senha.</div>"
                # o Entrar nasce desabilitado e só acende com os dois campos
                "<script>const u=document.getElementById('usernameForm'),"
                "s=document.getElementById('passwordForm'),b=document.getElementById('pbEntrar');"
                "function f(){b.disabled=!(u.value&&s.value);}"
                "u.addEventListener('input',f);s.addEventListener('input',f);</script>"
                "</body></html>")

    def _tela_codigo(self, erro=""):
        aviso = f"<div class='erro'>{erro}</div>" if erro else ""
        return ("<html><head><meta charset='utf-8'></head><body><div id='modalTokenDuploFator'>"
                "<p>Insira o código de validação enviado para seu e-mail</p>"
                f"{aviso}<form method='post' action='/sajcas/token'>"
                "<input type='text' id='tokenInformado' name='tokenInformado'>"
                "<button id='btnEnviarToken' type='submit'>Enviar</button></form>"
                "<button id='btnReceberToken' type='button'>Receber novo código</button>"
                "</div></body></html>")

    def _tela_processo(self, cd, info):
        n = info["numero"]
        cookies = self._cookies()
        if info.get("senha") and cookies.get(f"LIB_{cd}") != "1":
            modal = ("<div id='popupSenha' style='display:block;width:400px;height:200px'>"
                     "<p>Processo em segredo de justiça. Informe a senha.</p>"
                     "<form method='get' action='/cpopg/senha.do'>"
                     f"<input type='hidden' name='cd' value='{cd}'>"
                     "<input id='senhaProcesso' name='senha' type='password'>"
                     "<button id='btEnviarSenha' type='submit'>Enviar</button></form></div>")
            return self._pagina(f"<h2>Consulta de processo</h2>{modal}")
        incidente = ""
        if info.get("incidente"):
            incidente = (f"<table><tr><td><a href='/cpopg/show.do?processo.codigo="
                         f"{info['incidente']}&processo.foro=1'>{n.principal}/01</a></td>"
                         "<td>Cumprimento de sentença (00001)</td></tr></table>")
        principal = (f"<p>Processo principal: {info['principal'].principal}</p>"
                     if info.get("principal") else "")
        corpo = (
            f"<div id='containerDadosPrincipaisProcesso'><span id='numeroProcesso'>"
            f"{n.formatado}</span><span id='classeProcesso'>Procedimento Comum Cível</span>"
            "<span id='assuntoProcesso'>Indenização por Dano Moral</span>"
            "<span id='juizProcesso'>Dra. Fulana de Tal</span></div>"
            f"{principal}"
            "<table id='tablePartesPrincipais'><tr><td>Autor:</td><td>Maria da Silva</td></tr>"
            "<tr><td>Réu:</td><td>Banco Exemplo S.A.</td></tr></table>"
            f"{incidente}"
            "<table id='tabelaTodasMovimentacoes'>"
            "<tr><td>20/04/2024</td><td>Retirado o segredo de justiça</td></tr>"
            "<tr><td>01/02/2024</td><td>Distribuído por sorteio</td></tr></table>"
            # o modal de senha existe ESCONDIDO em toda página
            "<div id='popupSenha' style='display:none'><p>Segredo de justiça: informe a "
            "senha</p><input id='senhaProcesso'><button id='btEnviarSenha'>Enviar</button></div>")
        return self._pagina(corpo)

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        p = self.portal
        p.pedidos.append(("GET", self.path))
        rota = url.path
        if rota == "/esaj/api/auth/session":
            return self._enviar(200, json.dumps({"usuarioLogado": self._logado(),
                                                 "nome": "anônimo"}), "application/json")
        if rota in ("/esaj/", "/esaj/portal.do"):
            return self._enviar(200, self._pagina("<h1>Portal de Serviços e-SAJ</h1>"))
        if rota == "/sajcas/login":
            return self._enviar(200, self._tela_login())
        if rota == "/cpopg/open.do":
            if "gateway" in q and not self._logado():
                return self._ir("/sajcas/login?service=cpopg")
            return self._enviar(200, self._pagina("<form>Consulta</form>"))
        if not self._logado():
            if rota.startswith("/cpopg/abrirPastaDigital"):
                return self._enviar(200, "Não foi possível validar o seu acesso.", "text/plain")
            return self._ir("/sajcas/login")

        if rota == "/cpopg/search.do":
            numero = q.get("dadosConsulta.valorConsultaNuUnificado", [""])[0]
            foro = q.get("foroNumeroUnificado", [""])[0]
            if not numero or numero[-4:] != foro:
                return self._enviar(200, self._pagina("Foro inválido para o número"))
            cd = p.por_numero.get(numero[:7])
            if cd == "lista":
                linhas = "".join(
                    f"<tr><td><a href='/cpopg/show.do?processo.codigo={c}&processo.foro=1'>"
                    f"{p.processos[c]['numero'].principal}</a></td><td>Cível</td></tr>"
                    for c in ("1K0099ZZZ0000", "1K0005EEE0000"))
                return self._enviar(200, self._pagina(f"<table>{linhas}</table>"))
            if cd is None:
                return self._enviar(200, self._pagina(
                    "<p>Não existem informações disponíveis para os parâmetros informados.</p>"))
            return self._ir(f"/cpopg/show.do?processo.codigo={cd}&processo.foro=1"
                            f"&processo.numero={numero}")
        if rota == "/cpopg/show.do":
            cd = q.get("processo.codigo", [""])[0]
            info = p.processos.get(cd)
            foro = q.get("processo.foro", ["1"])[0]
            if info is None or foro != "1":
                # foro errado (o 56 fixo da base) não abre o processo
                return self._enviar(200, self._pagina("Não foi possível validar o seu acesso."))
            return self._enviar(200, self._tela_processo(cd, info))
        if rota == "/cpopg/senha.do":
            cd = q.get("cd", [""])[0]
            info = p.processos.get(cd, {})
            cab = []
            if q.get("senha", [""])[0] == info.get("senha"):
                cab.append(("Set-Cookie", f"LIB_{cd}=1; Path=/"))
            return self._ir(f"/cpopg/show.do?processo.codigo={cd}&processo.foro=1", cab)
        if rota == "/cpopg/abrirPastaDigital.do":
            cd = q.get("processo.codigo", [""])[0]
            info = p.processos.get(cd)
            if info is None or (info.get("senha") and self._cookies().get(f"LIB_{cd}") != "1"):
                return self._enviar(200, "Não foi possível validar o seu acesso.", "text/plain")
            return self._enviar(200, f"http://127.0.0.1:{p.porta}/pastadigital/"
                                     f"abrirPastaProcessoDigital.do?cd={cd}", "text/plain")
        if rota == "/pastadigital/abrirPastaProcessoDigital.do":
            info = p.processos[q["cd"][0]]
            arvore = json.dumps(info["arvore"])
            return self._enviar(200, f"<html><body><div>Pasta Digital</div>"
                                     f"<script>var requestScope = {arvore};</script></body></html>")
        if rota == "/pastadigital/documentoFinal.do":
            loc = p.localizadores[q["loc"][0]]
            return self._enviar(200, _pdf(loc["paginas"], "servidor"), "application/pdf")
        if rota == "/pastadigital/getPDF.do":
            cd = q.get("cdDocumento", [""])[0]
            dono = next(i for i in p.processos.values()
                        if any(cd == str(d["data"]["cdDocumento"]) for d in i["arvore"]))
            if cd in dono.get("pecas_ausentes", set()):
                return self._enviar(404, "não encontrado")
            paginas = int(q["numFinal"][0]) - int(q["numInicial"][0]) + 1
            return self._enviar(200, _pdf(paginas, f"peça {cd}"), "application/pdf")
        if rota == "/pastadigital/getArquivo.do":
            return self._enviar(404, "não encontrado")
        if rota == "/pastadigital/getMidia.do":
            return self._enviar(200, b"ID3" + b"\x00" * 2000, "audio/mpeg")
        return self._enviar(404, "não encontrado")

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        p = self.portal
        p.pedidos.append(("POST", self.path))
        bruto, form = self._form()
        if url.path == "/sajcas/login":
            if form.get("username", [""])[0] == USUARIO and form.get("password", [""])[0] == SENHA:
                return self._enviar(200, self._tela_codigo())
            return self._enviar(200, self._tela_login("Usuário ou senha inválidos."))
        if url.path == "/sajcas/token":
            codigo = form.get("tokenInformado", [""])[0]
            p.codigos_enviados.append(codigo)
            if codigo == CODIGO:
                return self._ir("/esaj/portal.do", [("Set-Cookie", "SESSAO=ok; Path=/")])
            return self._enviar(200, self._tela_codigo("Código inválido."))
        if not self._logado():
            return self._enviar(401, "sessão expirada")
        if url.path == "/pastadigital/salvarDocumentoPreparado.do":
            cd = form["cdProcesso"][0]
            if p.processos[cd].get("servidor_falha"):
                return self._enviar(500, "<html>Erro interno do servidor</html>")
            itens = form.get("itensPdfSelecionados", [])
            paginas = 0
            for item in itens:
                qi = urllib.parse.parse_qs(item)
                paginas += int(qi["numFinal"][0]) - int(qi["numInicial"][0]) + 1
            loc = str(uuid.uuid4())
            p.localizadores[loc] = {"cd": cd, "paginas": paginas, "consultas": 0,
                                    "corpo": bruto}
            return self._enviar(200, loc, "text/plain")
        if url.path == "/pastadigital/buscarDocumentoFinalizado.do":
            loc = p.localizadores[form["localizador"][0]]
            loc["consultas"] += 1
            if loc["consultas"] < 2:                # ainda montando
                return self._enviar(200, "", "text/plain")
            return self._enviar(200, f"http://127.0.0.1:{p.porta}/pastadigital/"
                                     f"documentoFinal.do?loc={form['localizador'][0]}",
                                "text/plain")
        return self._enviar(404, "não encontrado")


def _procurar_navegador() -> tuple[str, str | None] | None:
    """(canal, executável) de um navegador que o Playwright consiga abrir.

    No Windows (CI), o Chrome ou o Edge instalados; no Linux, o Chromium do
    Playwright - ou, se a versão dele não bater com a do pacote, um dos que
    estiverem em PLAYWRIGHT_BROWSERS_PATH.
    """
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


_NAVEGADOR: tuple[str, str | None] | None = None
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


class TestPortaADentro(apoio.PastaTemporaria):
    """O e-SAJ inteiro, do login ao PDF, num navegador de verdade."""

    @classmethod
    def setUpClass(cls):
        if navegador_de_teste() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")
        cls.portal = PortalDeMentira()
        atendente = type("AtendenteDoTeste", (Atendente,), {"portal": cls.portal})
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), atendente)
        cls.servidor.daemon_threads = True
        cls.portal.porta = cls.servidor.server_address[1]
        cls.portal.montar()
        cls.fio = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.fio.start()
        cls.base = f"http://127.0.0.1:{cls.portal.porta}"

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self):
        super().setUp()
        patches = [mock.patch.object(esaj, "INTERVALO_POLL_S", 0.2),
                   mock.patch.object(esaj, "ESPERA_CONFIRMA_CODIGO_S", 2),
                   mock.patch.object(motor, "ESPERA_ENTRE_TENTATIVAS_S", 0.0)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.tribunal = replace(tribunais.por_sigla("TJAL"), urls={"base": self.base})

    def navegador(self, nome="esaj-TJAL"):
        canal, exe = navegador_de_teste()
        return Navegador(self.tmp / "perfis" / nome, visivel=False, canal=canal,
                         executavel=exe, espera_s=20,
                         pasta_downloads=self.tmp / "downloads",
                         pasta_diagnostico=self.tmp / "diagnostico")

    def fabricas(self, nome="esaj-TJAL"):
        def fabrica_navegador(tribunal, opcoes):
            return self.navegador(nome)

        def fabrica_portal(nav, tribunal, opcoes, ctx, credenciais):
            return PortalESAJ(nav, self.tribunal, opcoes, ctx, credenciais)
        return fabrica_portal, fabrica_navegador

    def test_lote_completo_e_segunda_rodada(self):
        destino = self.tmp / "Acervo" / "Processos" / "Pauta"
        opcoes = apoio.opcoes_de_teste(self.tmp, tentativas=1, baixar_midias=True, espera_s=20,
                                       espera_tela_codigo_s=15)
        ctx = apoio.ContextoGravador(codigos=["000000", CODIGO])
        cofre = apoio.CofreFalso({"esaj:TJAL": (USUARIO, SENHA)})
        fp, fn = self.fabricas()
        lista = [P1, P2, P3, P1_INC, P5]
        resumo = motor.executar(lista, destino, opcoes, ctx, senhas={P2.formatado: "abc123"},
                                cofre=cofre, fabrica_portal=fp, fabrica_navegador=fn)
        r = {x.numero: x for x in resumo.itens}

        # login: o primeiro código foi recusado, o segundo aceito
        self.assertEqual(self.portal.codigos_enviados[:2], ["000000", CODIGO])
        self.assertEqual(len(ctx.pedidos_codigo), 2)
        self.assertIn("não aceitou", ctx.pedidos_codigo[1][1])

        # P1: PDF do servidor, com marcadores, capa e gravação; não é sigiloso
        r1 = r[P1.formatado]
        self.assertEqual(r1.situacao, modelos.OK, r1.detalhe)
        self.assertEqual(r1.paginas, 6)
        self.assertEqual(r1.documentos, 3)
        self.assertFalse(r1.sigiloso, "'retirado o segredo' nas movimentações não é sigilo")
        import pymupdf
        with pymupdf.open(destino / f"{P1.nome_arquivo}.pdf") as doc:
            self.assertEqual(len(doc), 6)
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 3, 6])
        capa = (destino / "_controle" / f"{P1.nome_arquivo}_capa.txt").read_text(encoding="utf-8")
        self.assertIn("Classe: Procedimento Comum Cível", capa)
        self.assertIn("Maria da Silva", capa)
        self.assertIn("Distribuído por sorteio", capa)
        self.assertTrue((destino / "_controle" / "midias" / P1.nome_arquivo /
                         "audiencia1.mp3").exists())
        loc = next(l for l in self.portal.localizadores.values() if l["cd"] == "1K0001AAA0000")
        self.assertTrue(loc["corpo"].startswith("itensPdfSelecionados=nuSeqRecurso%3D00000"))
        self.assertIn("&cdProcesso=1K0001AAA0000&cdDocumento=103&separarDocumentos=false",
                      loc["corpo"])

        # P2: sigiloso liberado pela senha; servidor falhou -> peça a peça; fora do acervo
        r2 = r[P2.formatado]
        self.assertEqual(r2.situacao, modelos.OK, r2.detalhe)
        self.assertTrue(r2.sigiloso)
        self.assertIn("peça a peça", r2.detalhe)
        self.assertEqual(r2.incompleto, "3")
        sig = self.tmp / "Sigilosos" / "Pauta"
        self.assertFalse((destino / f"{P2.nome_arquivo}.pdf").exists())
        with pymupdf.open(sig / f"{P2.nome_arquivo}.pdf") as doc:
            self.assertEqual(len(doc), 3)
            self.assertIn("não pôde ser baixada", doc[2].get_text())
        self.assertTrue((sig / "_controle" / "midias" / P2.nome_arquivo / "audiencia1.mp3").exists())
        self.assertFalse((destino / "_controle" / f"{P2.nome_arquivo}_capa.txt").exists())

        # P3: inexistente; incidente; busca que devolve lista
        self.assertEqual(r[P3.formatado].situacao, modelos.NAO_ENCONTRADO)
        r_inc = r[P1_INC.formatado]
        self.assertEqual(r_inc.situacao, modelos.OK, r_inc.detalhe)
        self.assertEqual(r_inc.paginas, 2)
        self.assertTrue((destino / f"{P1.principal}-01.pdf").exists())
        r5 = r[P5.formatado]
        self.assertEqual(r5.situacao, modelos.OK, r5.detalhe)
        self.assertTrue(any("1K0005EEE0000" in c for _, c in self.portal.pedidos
                            if "show.do" in c))
        self.assertFalse(any("processo.foro=56" in c for _, c in self.portal.pedidos))

        # sessão guardada para a próxima vez (fora do acervo)
        self.assertTrue((self.tmp / "perfis" / "esaj-TJAL" / "sessao.json").exists())
        self.assertEqual(sorted(p.name for p in destino.iterdir() if p.is_file()),
                         sorted([f"{P1.nome_arquivo}.pdf", f"{P1.principal}-01.pdf",
                                 f"{P5.nome_arquivo}.pdf"]))

        # segunda rodada: pula o que já tem e NÃO pede código de novo
        ctx2 = apoio.ContextoGravador(codigos=[])
        fp, fn = self.fabricas()
        resumo2 = motor.executar(lista, destino, opcoes, ctx2, senhas={P2.formatado: "abc123"},
                                 cofre=cofre, fabrica_portal=fp, fabrica_navegador=fn)
        self.assertEqual(ctx2.pedidos_codigo, [], "a sessão guardada dispensa o login")
        sit = {x.numero: x.situacao for x in resumo2.itens}
        self.assertEqual(sit[P1.formatado], modelos.JA_BAIXADO)
        self.assertEqual(sit[P2.formatado], modelos.JA_BAIXADO)
        self.assertEqual(sit[P3.formatado], modelos.NAO_ENCONTRADO)

    def test_senha_errada_e_avisada_sem_esperar(self):
        import time
        opcoes = apoio.opcoes_de_teste(self.tmp, espera_s=20, espera_tela_codigo_s=45)
        ctx = apoio.ContextoGravador()
        with self.navegador("esaj-senha-errada") as nav:
            portal = PortalESAJ(nav, self.tribunal, opcoes, ctx, (USUARIO, "errada"))
            inicio = time.monotonic()
            with self.assertRaises(modelos.LoginFalhou) as caso:
                portal.entrar()
            demora = time.monotonic() - inicio
        self.assertIn("recusou o usuário ou a senha", str(caso.exception))
        self.assertLess(demora, 30, "não pode esperar os 45 s da tela do código")
        self.assertEqual(ctx.pedidos_codigo, [])
        self.assertTrue(list((self.tmp / "diagnostico").glob("*esaj-login-recusado*.html")))

    def test_primeiro_visivel_no_navegador_de_verdade(self):
        from app.download.navegador import primeiro_visivel
        with self.navegador("esaj-seletores") as nav:
            nav.pagina.set_content(
                "<div id='a' style='display:none'><input id='x'></div>"
                "<input id='b'><button id='c'>Entrar</button>")
            achado = primeiro_visivel(nav.pagina, ["#a input", "#b", "button:has-text('Entrar')"], 2000)
            self.assertEqual(achado.get_attribute("id"), "b")
            self.assertIsNone(primeiro_visivel(nav.pagina, ["#a", "#x"], 300))
            botao = primeiro_visivel(nav.pagina, ["#nada", "button:has-text('Entrar')"], 1000)
            self.assertEqual(botao.get_attribute("id"), "c")


if __name__ == "__main__":
    unittest.main()
