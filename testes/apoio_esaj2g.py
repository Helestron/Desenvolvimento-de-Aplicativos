"""O e-SAJ de mentira dos testes, nos dois graus: CAS, cpopg, cposg5 e Pasta Digital.

Um servidor HTTP local (127.0.0.1, porta livre) imita o fluxo do e-SAJ - o
mesmo que o test_download_integracao usava, agora com a consulta de 2º grau.
Serve aos testes do e-SAJ (test_download_integracao) e aos de integração do
2º grau (test_integracao_2g), com esta API estável:

    with servidor_esaj() as s:
        portal = PortalESAJ(nav, s.tribunal().no_grau("2g"), opcoes, ctx,
                            (USUARIO, SENHA))
        portal.entrar()
        r = portal.baixar(NUMEROS["E"], pasta / "X-50000 (2G).pdf")

1º grau (cpopg), como sempre: login no CAS com código por e-mail (o botão
Entrar nasce desabilitado), o modal de senha escondido em toda página, o
"Não existem informações disponíveis", a busca que devolve LISTA, o foro que
tem de vir do número (show.do recusa outro), o servidor que não monta o PDF
único, folhas ocultas pela Pasta Digital.

2º grau (cposg5), pela estrutura da página real do TJAL (pesquisa dos
portais, out/2026):

* /cposg5/open.do?gateway=true - a porta de entrada: sem login, manda ao CAS;
  com login, abre a consulta e só então a consulta reconhece o login (o
  cookie SG5: o "SSO por webapp" - sem ele, a Pasta Digital recusa);
* /cposg5/search.do aceita SÓ os parâmetros do CPOSG (tipoNuProcesso,
  dePesquisaNuUnificado...; os do cpopg -> "Não existem informações
  disponíveis") e responde das três formas: a página do processo direto
  (input cdProcesso; H e S), o modal "Selecione o processo" (#modalIncidentes,
  rádios processoSelecionado, o recurso interno "50000 - Embargos..."; A e P)
  e a lista #listagemDeProcessos (PL);
* /cposg5/show.do só com processo.codigo (recusa o processo.foro da origem);
  o recurso interno tem o número com o sufixo (".../50000");
* segredo de justiça do 2º grau: #popupSenhaProcesso, #senhaProcesso,
  #botaoEnviarSenha, validarSenhaAcessoProcesso.do (S);
* /cposg5/verificarAcessoPastaDigital.do devolve, em texto, o endereço da
  Pasta Digital em /pastadigital/sg/... (erro HTTP sem acesso ou sem senha), e
  a Pasta Digital do 2º grau só responde nesse caminho;
* a árvore de A no 2º grau é OUTRA que a do 1º grau (cada grau grava a sua);
  com pasta_2g_duplicada=True, a de A numera duas peças nas mesmas folhas.

Os códigos internos do 2º grau seguem o padrão do TJAL: o do recurso interno
é o do principal com os quatro últimos caracteres trocados por 50000 em base
36 (P00006BXP0000 -> P00006BXP12KW).
"""

from __future__ import annotations

import html
import http.cookies
import json
import threading
import urllib.parse
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helestron.nucleo import cnj, tribunais

from testes import apoio_download as apoio

# Credenciais que o CAS falso aceita (o código por e-mail é CODIGO).
USUARIO, SENHA, CODIGO = "12345678900", "s3nh@ %;fácil", "123456"
# A senha do processo S no 2º grau (lá ele é sigiloso; no 1º, público).
SENHA_S_2G = "s2g-123"

# Os números do 2º grau (Anexo B do desenho; S escolhido aqui, com o dígito certo).
NUMEROS: dict[str, cnj.Numero] = {
    "A": cnj.ler("0700001-93.2024.8.02.0058"),       # apelação: o mesmo número nos dois graus
    "H": cnj.ler("0803061-28.2025.8.02.0000"),       # HC originário (órgão 0000)
    "E": cnj.ler("0706265-50.2017.8.02.0001/50000"),  # embargos de declaração do 2º grau
    "P": cnj.ler("0706265-50.2017.8.02.0001"),       # o principal dos embargos
    "PL": cnj.ler("0800103-29.2025.8.02.9002"),      # plantão do 2º grau (órgão 9002)
    "S": cnj.ler("0700010-32.2024.8.02.0001"),       # público no 1º grau, sigiloso no 2º
}
# O que o servidor sobe por padrão. A tem árvores DIFERENTES no cpopg e no cposg5.
CASOS = ("A", "E", "H", "S", "PL")

# Os casos do 1º grau de sempre (a regressão do cpopg).
P1 = apoio.numero("0700001", tr="02", origem="0001")
P1_INC = apoio.numero("0700001", tr="02", origem="0001", dependente="01")
P2 = apoio.numero("0700002", tr="02", origem="0001")     # sigiloso, servidor falha
P3 = apoio.numero("0700003", tr="02", origem="0001")     # inexistente
P5 = apoio.numero("0700005", tr="02", origem="0001")     # busca devolve lista
P6 = apoio.numero("0700006", tr="02", origem="0001")     # fls. 3-4 ocultas pela Pasta Digital
OUTRO = apoio.numero("0700099", tr="02", origem="0001")
# o outro processo da lista do 2º grau (a do PL)
OUTRO_PL = cnj.ler("0800104-14.2025.8.02.9002")

# Os códigos internos (o do 2º grau começa por P, como no TJAL).
COD_A_1G, COD_S_1G, COD_P_1G = "1K0700AAA0000", "1K0710SSS0000", "1K0626PPP0000"
COD_A_2G, COD_A_2G_50000 = "P0000AAAA0000", "P0000AAAA12KW"
COD_P_2G, COD_E_2G = "P00006BXP0000", "P00006BXP12KW"
COD_H_2G, COD_PL_2G, COD_OUTRO_PL = "P0000HHHH0000", "P0000PLPL0000", "P0000OUTR0000"
COD_S_2G = "P0000SSSS0000"


def par(numero, cd, ini, fim):
    """Os parâmetros de um bloco da Pasta Digital (como os da árvore real)."""
    return (f"nuSeqRecurso=00000&nuProcesso={numero.principal}&cdDocumento={cd}"
            f"&numInicial={ini}&numFinal={fim}&idDocumento=D{cd}-{ini}")


def doc(titulo, cd, data, blocos, midia=None):
    """Um documento da árvore (requestScope), com um filho por bloco."""
    filhos = [{"data": {"parametros": p, "nuPaginas": 1}} for p in blocos]
    if midia:
        filhos.append({"data": {"urlMidiaDigital": midia}})
    return {"data": {"title": titulo, "cdDocumento": cd, "dtInclusao": data}, "children": filhos}


def _foro_sem_zeros(numero) -> str:
    return numero.origem.lstrip("0") or "0"


class ServidorESAJ:
    """O e-SAJ falso no ar: um ThreadingHTTPServer em 127.0.0.1:<porta livre>.

    base: "http://127.0.0.1:<porta>" (CAS, /cpopg, /pastadigital);
    app_2g: base + "/cposg5"; pedidos: (método, caminho com query), na ordem.
    """

    def __init__(self, casos=CASOS, *, pasta_2g_duplicada: bool = False):
        self.casos = tuple(casos)
        self.pasta_2g_duplicada = bool(pasta_2g_duplicada)
        self.pedidos: list[tuple[str, str]] = []
        self.localizadores: dict[str, dict] = {}
        self.codigos_enviados: list[str] = []
        self.processos: dict[str, dict] = {}       # 1º grau (cpopg): código -> dados
        self.processos_2g: dict[str, dict] = {}    # 2º grau (cposg5): código -> dados
        self.por_numero: dict[str, str] = {}       # 1º grau: principal -> código | "lista"
        self.respostas_2g: dict[str, tuple] = {}   # 2º grau: principal -> resposta da busca
        self.sessoes_2g: set[str] = set()          # os cookies SG5 que a consulta reconhece
        self._trava = threading.Lock()
        atendente = type("AtendenteESAJ", (Atendente,), {"servidor": self})
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), atendente)
        self._http.daemon_threads = True
        self.porta = self._http.server_address[1]
        self.base = f"http://127.0.0.1:{self.porta}"
        self.app_2g = self.base + "/cposg5"
        self._montar()
        self._fio = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._fio.start()

    # ------------------------------------------------------------ API
    def tribunal(self) -> tribunais.Tribunal:
        """O TJAL do catálogo apontado para este servidor, sem alternativo, no
        1º grau (.no_grau("2g") para o 2º)."""
        return replace(tribunais.por_sigla("TJAL"),
                       urls={"base": self.base, "2g": self.app_2g}, alternativo=None)

    def enderecos_locais(self) -> dict:
        """Para o motor achar o servidor pelo catálogo (o enderecos-locais.json)."""
        return {"esaj:TJAL": {"base": self.base, "2g": self.app_2g}}

    def expirar_sessao_2g(self) -> None:
        """A consulta de 2º grau esquece o login (o login do portal fica): só
        uma nova passada pela porta de entrada dela o faz valer de novo."""
        with self._trava:
            self.sessoes_2g.clear()

    def parar(self) -> None:
        self._http.shutdown()
        self._http.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.parar()
        return False

    def pedidos_de(self, caminho: str) -> list[str]:
        """Os caminhos (com query) dos pedidos a uma rota."""
        return [c for _, c in self.pedidos if urllib.parse.urlsplit(c).path == caminho]

    # ----------------------------------------------------------- dados
    def _montar(self):
        base = self.base
        midia = f"{base}/pastadigital/getMidia.do?gravacaoAudiencia=C%3A%5Cgrav%5Caudiencia1.mp3"
        self.processos = {
            "1K0001AAA0000": dict(numero=P1, arvore=[
                doc("Petição Inicial", 101, "01/02/2024", [par(P1, 101, 1, 2)]),
                doc("Contestação", 102, "10/03/2024", [par(P1, 102, 3, 4), par(P1, 102, 5, 5)]),
                doc("Termo de Audiência", 103, "20/04/2024", [par(P1, 103, 6, 6)], midia),
            ], incidente="1K0001AAA0001"),
            "1K0001AAA0001": dict(numero=P1_INC, principal=P1, arvore=[
                doc("Petição de cumprimento", 111, "05/05/2024", [par(P1, 111, 1, 2)]),
            ]),
            "1K0002BBB0000": dict(numero=P2, senha="abc123", servidor_falha=True,
                                  pecas_ausentes={"202"}, arvore=[
                doc("Petição Inicial", 201, "02/02/2024", [par(P2, 201, 1, 2)]),
                doc("Laudo psicossocial", 202, "03/03/2024", [par(P2, 202, 3, 3)], midia),
            ]),
            "1K0005EEE0000": dict(numero=P5, arvore=[
                doc("Petição Inicial", 501, "05/01/2024", [par(P5, 501, 1, 1)]),
            ]),
            "1K0006FFF0000": dict(numero=P6, arvore=[
                doc("Petição Inicial", 601, "06/01/2024", [par(P6, 601, 1, 2)]),
                doc("Sentença", 605, "06/06/2024", [par(P6, 605, 5, 5)]),
            ]),
            "1K0099ZZZ0000": dict(numero=OUTRO, arvore=[]),
        }
        self.por_numero = {P1.principal: "1K0001AAA0000", P2.principal: "1K0002BBB0000",
                           P5.principal: "lista", P6.principal: "1K0006FFF0000"}
        a, h, e, p, pl, s = (NUMEROS[k] for k in ("A", "H", "E", "P", "PL", "S"))
        if "A" in self.casos:
            # a árvore do 1º grau de A: denúncia e sentença (4 folhas)
            self.processos[COD_A_1G] = dict(numero=a, arvore=[
                doc("Denúncia", 151, "10/01/2024", [par(a, 151, 1, 2)]),
                doc("Sentença", 152, "10/06/2024", [par(a, 152, 3, 4)]),
            ])
            self.por_numero[a.principal] = COD_A_1G
            arvore = [
                doc("Apelação Criminal", 701, "01/08/2024", [par(a, 701, 1, 3)]),
                doc("Contrarrazões", 702, "15/08/2024", [par(a, 702, 4, 5)]),
                doc("Parecer da Procuradoria", 703, "01/09/2024", [par(a, 703, 6, 6)]),
                doc("Acórdão", 704, "10/10/2024", [par(a, 704, 7, 8)]),
            ]
            if self.pasta_2g_duplicada:
                # duas numerações na mesma pasta: a peça da origem nas fls. 3-4
                arvore.insert(1, doc("Termo de remessa (numeração da origem)", 705,
                                     "20/07/2024", [par(a, 705, 3, 4)]))
            self.processos_2g[COD_A_2G] = dict(
                numero=a, classe="Apelação Criminal", assunto="Roubo Majorado",
                orgao="Câmara Criminal", relator="DES. JOÃO EXEMPLO", area="Criminal",
                situacao="Julgado", origem="Comarca de Arapiraca / Foro de Arapiraca / "
                                           "1ª Vara Criminal de Arapiraca",
                numeros_1a=[(a.formatado, "Foro de Arapiraca", "1ª Vara Criminal de Arapiraca",
                             "Juiz Fulano de Tal", "-", True)],
                partes=[("Apelante", "João da Silva"), ("Apelado", "Ministério Público")],
                movs=[("10/10/2024", "Acórdão publicado"), ("01/09/2024", "Conclusos ao relator")],
                composicao=[("Relator", "Des. João Exemplo"), ("Revisor", "Des. Pedro Revisor"),
                            ("3º Julgador", "Desa. Maria Vogal")],
                julgamentos=[("09/10/2024", "Julgado",
                              "à unanimidade, negou provimento ao recurso")],
                dependentes=[COD_A_2G_50000], arvore=arvore)
            self.processos_2g[COD_A_2G_50000] = dict(
                numero=cnj.ler(a.principal + "/50000"), classe="Embargos de Declaração Criminal",
                assunto="Roubo Majorado", orgao="Câmara Criminal", relator="DES. JOÃO EXEMPLO",
                area="Criminal", situacao="Em andamento", principal=COD_A_2G,
                arvore=[doc("Embargos de Declaração", 711, "20/10/2024", [par(a, 711, 1, 2)])])
            self.respostas_2g[a.principal] = ("modal", [COD_A_2G])
        if "E" in self.casos or "P" in self.casos:
            self.processos[COD_P_1G] = dict(numero=p, arvore=[
                doc("Petição Inicial", 171, "05/05/2017", [par(p, 171, 1, 3)]),
            ])
            self.por_numero[p.principal] = COD_P_1G
            self.processos_2g[COD_P_2G] = dict(
                numero=p, classe="Apelação Cível", assunto="Obrigações", orgao="1ª Câmara Cível",
                relator="DES. CARLOS RELATOR", area="Cível", situacao="Julgado",
                origem="Comarca de Maceió / Foro de Maceió / 4ª Vara Cível da Capital",
                numeros_1a=[(p.formatado, "Foro de Maceió", "4ª Vara Cível da Capital",
                             "Juíza Beltrana", "-", True)],
                partes=[("Apelante", "Construtora Exemplo Ltda."), ("Apelado", "Fulano Exemplo")],
                movs=[("01/03/2019", "Acórdão publicado")],
                composicao=[("Relator", "Des. Carlos Relator")],
                julgamentos=[("20/02/2019", "Julgado", "negaram provimento")],
                dependentes=[COD_E_2G],
                arvore=[doc("Apelação", 801, "01/06/2018", [par(p, 801, 1, 4)]),
                        doc("Acórdão", 802, "01/03/2019", [par(p, 802, 5, 6)])])
            self.processos_2g[COD_E_2G] = dict(
                numero=e, classe="Embargos de Declaração Cível", assunto="Obrigações",
                orgao="1ª Câmara Cível", relator="DES. CARLOS RELATOR", area="Cível",
                situacao="Arquivado", principal=COD_P_2G,
                movs=[("10/04/2019", "Embargos rejeitados")],
                arvore=[doc("Petição de embargos", 811, "10/03/2019", [par(p, 811, 1, 2)]),
                        doc("Acórdão dos embargos", 812, "10/04/2019", [par(p, 812, 3, 3)])])
            self.respostas_2g[p.principal] = ("modal", [COD_P_2G])
        if "H" in self.casos:
            self.processos_2g[COD_H_2G] = dict(
                numero=h, classe="Habeas Corpus Criminal", assunto="Prisão Preventiva",
                orgao="Câmara Criminal", relator="DES. JOÃO EXEMPLO", area="Criminal",
                situacao="Em andamento",
                origem="Comarca de Arapiraca / Foro de Arapiraca / 1ª Vara Criminal de Arapiraca",
                numeros_1a=[(a.formatado, "Foro de Arapiraca", "1ª Vara Criminal de Arapiraca",
                             "Juiz Fulano de Tal", "-", True)],
                partes=[("Impetrante", "Advogada Exemplo"), ("Paciente", "João da Silva")],
                movs=[("05/09/2025", "Liminar indeferida"), ("02/09/2025", "Distribuído")],
                composicao=[("Relator", "Des. João Exemplo")],
                arvore=[doc("Petição Inicial", 901, "01/09/2025", [par(h, 901, 1, 3)]),
                        doc("Informações", 902, "10/09/2025", [par(h, 902, 4, 4)]),
                        doc("Parecer", 903, "20/09/2025", [par(h, 903, 5, 5)])])
            self.respostas_2g[h.principal] = ("pagina", COD_H_2G)
        if "PL" in self.casos:
            self.processos_2g[COD_PL_2G] = dict(
                numero=pl, classe="Habeas Corpus Criminal", assunto="Prisão em Flagrante",
                orgao="Plantão - TJ", relator="DES. PLANTONISTA", area="Criminal",
                situacao="Arquivado",
                arvore=[doc("Petição Inicial", 921, "06/06/2025", [par(pl, 921, 1, 2)])])
            self.processos_2g[COD_OUTRO_PL] = dict(
                numero=OUTRO_PL, classe="Habeas Corpus Criminal", assunto="Prisão em Flagrante",
                orgao="Plantão - TJ", situacao="Arquivado",
                arvore=[doc("Petição Inicial", 941, "07/06/2025", [par(OUTRO_PL, 941, 1, 1)])])
            self.respostas_2g[pl.principal] = ("lista", [COD_OUTRO_PL, COD_PL_2G])
        if "S" in self.casos:
            self.processos[COD_S_1G] = dict(numero=s, arvore=[
                doc("Petição Inicial", 161, "02/02/2024", [par(s, 161, 1, 2)]),
            ])
            self.por_numero[s.principal] = COD_S_1G
            self.processos_2g[COD_S_2G] = dict(
                numero=s, classe="Apelação Criminal", assunto="Estupro de Vulnerável",
                orgao="Câmara Criminal", relator="DES. JOÃO EXEMPLO", area="Criminal",
                situacao="Em andamento", senha=SENHA_S_2G, segredo=True,
                numeros_1a=[(s.formatado, "Foro de Maceió", "1ª Vara Criminal da Capital",
                             "Juiz Fulano de Tal", "-", True)],
                partes=[("Apelante", "R. S."), ("Apelado", "Ministério Público")],
                movs=[("01/09/2025", "Conclusos ao relator")],
                arvore=[doc("Apelação Criminal", 931, "01/08/2025", [par(s, 931, 1, 2)]),
                        doc("Parecer", 932, "20/08/2025", [par(s, 932, 3, 3)])])
            self.respostas_2g[s.principal] = ("pagina", COD_S_2G)

    def sessao_2g_nova(self) -> str:
        token = uuid.uuid4().hex
        with self._trava:
            self.sessoes_2g.add(token)
        return token

    def sessao_2g_vale(self, token: str) -> bool:
        with self._trava:
            return bool(token) and token in self.sessoes_2g


def _pdf(paginas, rotulo):
    return apoio.pdf_bytes(paginas, rotulo)


class Atendente(BaseHTTPRequestHandler):
    servidor: ServidorESAJ = None   # definido pela classe derivada (ServidorESAJ)

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

    def _logado_2g(self):
        """O login vale na consulta de 2º grau? (o do portal E a passada pela
        porta de entrada da consulta)"""
        return self._logado() and self.servidor.sessao_2g_vale(self._cookies().get("SG5", ""))

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

    # ---------------------------------------------------------- telas (CAS)
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

    # ------------------------------------------------- telas (1º grau, cpopg)
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
            # a seção é achada pelo título; a linha começa por data, como no
            # portal ("Recebido em")
            incidente = ("<h2 class='subtitle tituloDoBloco'>Incidentes, ações incidentais, "
                         "recursos e execuções de sentenças</h2>"
                         "<table><thead><tr><th>Recebido em</th><th>Processo</th><th>Classe</th>"
                         "</tr></thead><tr><td>15/05/2024</td><td><a href='/cpopg/show.do?"
                         f"processo.codigo={info['incidente']}&processo.foro=1'>{n.principal}/01"
                         "</a></td><td>Cumprimento de sentença (00001)</td></tr></table>")
        principal = (f"<p>Processo principal: {info['principal'].principal}</p>"
                     if info.get("principal") else "")
        corpo = (
            f"<div id='containerDadosPrincipaisProcesso'><span id='numeroProcesso'>"
            f"{n.formatado}</span><span id='classeProcesso'>Procedimento Comum Cível</span>"
            "<span id='assuntoProcesso'>Estatuto do Idoso</span>"
            "<span id='juizProcesso'>Dra. Fulana de Tal</span>"
            "<span class='unj-tag'>Tramitação prioritária</span>"
            "<span class='unj-label'>Outros números</span><div>0001234-56.2023.8.02.0001</div>"
            "</div>"
            f"{principal}"
            "<table id='tablePartesPrincipais'><tr><td>Autor:</td><td>Maria da Silva</td></tr>"
            "<tr><td>Réu:</td><td>Banco Exemplo S.A.</td></tr></table>"
            "<table id='tableTodasPartes'><tr><td>Autor:</td><td>Maria da Silva</td></tr>"
            "<tr><td>Réu:</td><td>Banco Exemplo S.A.</td></tr>"
            "<tr><td>Terceiro:</td><td>João Terceiro</td></tr></table>"
            f"{incidente}"
            "<h2 class='subtitle tituloDoBloco'>Movimentações</h2>"
            "<table id='tabelaUltimasMovimentacoes'>"
            "<tr><td>20/04/2024</td><td>Retirado o segredo de justiça</td></tr></table>"
            "<table id='tabelaTodasMovimentacoes'>"
            "<tr><td>20/04/2024</td><td>Retirado o segredo de justiça</td></tr>"
            "<tr><td>01/02/2024</td><td>Distribuído por sorteio</td></tr>"
            "<tr><td>01/02/2024</td><td>Distribuído por sorteio</td></tr></table>"
            # tabelas com linhas que começam por data e NÃO são movimentações
            "<h2 class='subtitle tituloDoBloco'>Petições diversas</h2>"
            "<table><tr><th>Data</th><th>Tipo</th></tr>"
            "<tr><td>05/03/2024</td><td>Pedido de vista dos autos</td></tr></table>"
            "<h2 class='subtitle tituloDoBloco'>Audiências</h2>"
            "<table><tr><th>Data</th><th>Audiência</th><th>Situação</th><th>Qt. Pessoas</th></tr>"
            "<tr><td>19/04/2024</td><td>Conciliação</td><td>Realizada</td><td>2</td></tr></table>"
            "<h2 class='subtitle tituloDoBloco'>Histórico de classes</h2>"
            "<table><tr><td>01/02/2024</td><td>Evolução de classe</td>"
            "<td>Procedimento Comum Cível</td><td>Cível</td></tr></table>"
            # o modal de senha existe ESCONDIDO em toda página
            "<div id='popupSenha' style='display:none'><p>Segredo de justiça: informe a "
            "senha</p><input id='senhaProcesso'><button id='btEnviarSenha'>Enviar</button></div>")
        return self._pagina(corpo)

    # ------------------------------------------------- telas (2º grau, cposg5)
    def _tela_consulta_2g(self, aviso=""):
        mensagem = (f"<div id='spwTabelaMensagem'><table><tr><td id='mensagemRetorno'>{aviso}"
                    "</td></tr></table></div>" if aviso else "")
        return self._pagina(
            "<div class='div-conteudo container'><h1>Consulta de Processos de 2º Grau</h1>"
            "<form id='formularioConsulta' name='consultarProcessoForm' method='GET' "
            "action='/cposg5/search.do'><input type='hidden' name='conversationId'>"
            "<select name='cbPesquisa'><option value='NUMPROC'>Número do Processo</option>"
            "</select><input type='text' name='dePesquisaNuUnificado'></form>"
            f"{mensagem}</div>")

    def _popup_senha_2g(self, visivel: bool) -> str:
        estilo = "display:block;width:420px;height:220px" if visivel else "display:none"
        return (f"<div id='popupSenhaProcesso' style='{estilo}'>"
                "<p class='orientacao121'>É necessário informar uma senha para acessar processo "
                "em segredo de justiça, bem como para acessar autos dos demais processos.</p>"
                "<input type='password' id='senhaProcesso' name='senhaProcesso'>"
                "<span id='msgErroSenha' style='display:none'></span>"
                "<input type='button' id='botaoEnviarSenha' name='btEnviarSenha' value='Continuar'>"
                "<input type='button' id='botaoFecharPopupSenha' value='Fechar'></div>")

    def _tela_senha_2g(self, cd):
        # como no portal: a página vem SEM os dados, com o popup da senha; o
        # envio é por AJAX e, aceita a senha, a página volta pelo show.do
        script = (
            "<script>document.getElementById('botaoEnviarSenha').addEventListener('click',"
            " async () => {const corpo = new URLSearchParams({senhaDoProcessoDigitada:"
            " document.getElementById('senhaProcesso').value, cdProcesso:"
            " document.querySelector('input[name=\"cdProcesso\"]').value});"
            " const r = await fetch('/cposg5/validarSenhaAcessoProcesso.do', {method: 'POST',"
            " body: corpo, credentials: 'include'}); const cd = (await r.text()).trim();"
            " if (r.ok) { location = '/cposg5/show.do?processo.codigo=' + cd; } else {"
            " const m = document.getElementById('msgErroSenha'); m.textContent ="
            " 'Senha inválida'; m.style.display = 'block'; }});</script>")
        return self._pagina(f"<input type='hidden' name='cdProcesso' value='{cd}'/>"
                            "<div class='div-conteudo container'>"
                            f"{self._popup_senha_2g(True)}</div>{script}")

    @staticmethod
    def _campo(rotulo, ident, valor):
        if not valor:
            return ""
        v = html.escape(valor)
        attr = f" id='{ident}'" if ident else ""
        return (f"<div class='col-md-3'><span class='unj-label'>{rotulo}</span>"
                f"<div class='lh-1-1 line-clamp__2'{attr}><span title='{v}'>{v}</span></div></div>")

    @staticmethod
    def _secao(titulo, cabecalho, linhas, classe_linha=""):
        """Uma seção do 2º grau como no portal: o título, uma tabela só com o
        cabeçalho (tr.label) e outra com as linhas."""
        cab = "".join(f"<td>{html.escape(c)}</td>" for c in cabecalho)
        vazio = "".join("<td></td>" for _ in cabecalho)
        corpo = "".join(
            f"<tr class='fundoClaro {classe_linha}'>"
            + "".join(f"<td>{c}</td>" for c in linha) + "</tr>" for linha in linhas)
        return (f"<div style='padding-top: 10px;'><h2 class='subtitle'>{titulo}</h2></div>"
                f"<table><tr class='label'>{cab}</tr><tr class='fundoEscuro' height='2'>{vazio}"
                f"</tr></table><table>{corpo}</table>")

    def _tela_processo_2g(self, cd, info):
        srv = self.servidor
        if info.get("senha") and self._cookies().get(f"LIB2_{cd}") != "1":
            return self._tela_senha_2g(cd)
        n = info["numero"]
        segredo = ("<span class='unj-tag' id='labelSegredoDeJusticaProcesso'>Segredo de Justiça"
                   "</span>" if info.get("segredo") else "")
        principal = ""
        if info.get("principal"):
            principal = (f"<a class='processoPrinc' href='/cposg5/show.do?processo.codigo="
                         f"{info['principal']}'>Processo principal</a>")
        resumo = (
            "<div class='unj-entity-header__summary'><div class='container'><div class='row'>"
            f"<span class='unj-larger-1' id='numeroProcesso'>{n.formatado}</span>"
            f"<span class='unj-tag' id='situacaoProcesso'>{info.get('situacao', '')}</span>"
            f"{segredo}{principal}</div><div class='row'>"
            + self._campo("Classe", "classeProcesso", info.get("classe"))
            + self._campo("Assunto", "assuntoProcesso", info.get("assunto"))
            + self._campo("Seção", "secaoProcesso", "Tribunal de Justiça")
            + self._campo("Órgão Julgador", "orgaoJulgadorProcesso", info.get("orgao"))
            + self._campo("Área", "areaProcesso", info.get("area"))
            + "</div></div></div>")
        detalhes = (
            "<div class='unj-entity-header__details'><div id='maisDetalhes' class='collapse' "
            "style='display:none'><div class='row'>"
            + self._campo("Relator", "relatorProcesso", info.get("relator"))
            + self._campo("Valor da ação", "valorAcaoProcesso", "50.000,00")
            + self._campo("Origem", "", info.get("origem"))
            + "</div></div></div>")
        cabecalho = (
            f"<input type='hidden' name='cdProcesso' value='{cd}'/>"
            "<div class='unj-entity-header'><div class='unj-entity-header__actions'>"
            "<a class='linkPasta btn btn-secondary' id='pbVisualizarAutos' title='Pasta Digital'"
            f" href='#'>Visualizar autos</a></div>{resumo}{detalhes}</div>")
        secoes = []
        if info.get("numeros_1a"):
            linhas = []
            for numero, foro, vara, juiz, obs, eh_principal in info["numeros_1a"]:
                cod = srv.por_numero.get(cnj.ler(numero).principal, "")
                linhas.append([f"<a href='{srv.base}/cpopg/show.do?processo.codigo={cod}' "
                               f"target='_blank'>{numero}</a>"
                               + (" (Principal)" if eh_principal else ""),
                               foro, vara, juiz, obs])
            secoes.append(self._secao("Números de 1ª Instância",
                                      ["Nº de 1ª instância", "Foro", "Vara", "Juiz", "Obs."],
                                      linhas))
        partes = "".join(
            f"<tr class='fundoClaro poloAtivo'><td class='label'><span class='mensagemExibindo "
            f"tipoDeParticipacao'>{tipo}:&nbsp;</span></td><td class='nomeParteEAdvogado'>"
            f"{html.escape(nome)}</td></tr>" for tipo, nome in info.get("partes") or [])
        secoes.append("<div style='padding-top: 10px;'><h2 class='subtitle'>Partes do Processo"
                      f"</h2></div><table id='tablePartesPrincipais'>{partes}</table>")
        movs = info.get("movs") or []
        linhas_movs = "".join(
            f"<tr class='fundoClaro movimentacaoProcesso'><td class='dataMovimentacaoProcesso'>"
            f"{data}</td><td></td><td class='descricaoMovimentacaoProcesso'>{html.escape(texto)}"
            "</td></tr>" for data, texto in movs)
        secoes.append(
            "<div style='padding-top: 10px;'><h2 class='subtitle'>Movimentações</h2></div>"
            "<table><thead><tr><th class='label'>Data</th><th></th><th class='label'>Movimento"
            f"</th></tr></thead><tbody id='tabelaUltimasMovimentacoes'>{linhas_movs}</tbody>"
            f"<tbody style='display: none;' id='tabelaTodasMovimentacoes'>{linhas_movs}</tbody>"
            "</table>")
        if info.get("dependentes"):
            linhas = "".join(
                "<tr class='fundoClaro'><td>21/10/2024</td><td><a href='/cposg5/show.do?"
                f"processo.codigo={dcd}&uuidCaptcha=&processo.foro=900' target='_top'>"
                f"{srv.processos_2g[dcd]['classe']} - {srv.processos_2g[dcd]['numero'].dependente}"
                "</a></td></tr>" for dcd in info["dependentes"])
            secoes.append(
                "<div style='padding-top: 10px;'><h2 class='subtitle'>Incidentes, ações "
                "incidentais, recursos e execuções de sentenças</h2></div><table>"
                "<tr class='label'><th>Recebido em</th><th>Classe</th></tr>"
                f"<tr class='fundoEscuro' height='2'><td></td><td></td></tr>{linhas}</table>")
        if info.get("composicao"):
            secoes.append(self._secao("Composição do Julgamento", ["Participação", "Magistrado"],
                                      [[papel, nome] for papel, nome in info["composicao"]],
                                      "itemComposicaoJulgamento"))
        if info.get("julgamentos"):
            secoes.append(self._secao("Julgamentos", ["Data", "Situação do julgamento",
                                                      "Decisão"],
                                      [list(j) for j in info["julgamentos"]]))
        # o popup de senha do 2º grau, escondido (diz "segredo de justiça")
        return self._pagina(f"{cabecalho}<div class='div-conteudo container'>{''.join(secoes)}"
                            f"{self._popup_senha_2g(False)}</div>")

    def _tela_modal_2g(self, codigos):
        srv = self.servidor
        secoes = []
        for cd in codigos:
            info = srv.processos_2g[cd]
            deps = "".join(
                "<div style='padding-left: 20px' class='list__hierarquia-dependentes__item mt-0'>"
                "<label class='list__dependentes_row'><input class='custom-radio' type='radio' "
                f"name='processoSelecionado' id='processoSelecionado' value='{dcd}' />"
                "<div class='list__hierarquia-dependentes__item__label__info'>"
                "<em class='list__hierarquia-dependentes__item__label__info__title'>"
                f"{srv.processos_2g[dcd]['numero'].dependente} - {srv.processos_2g[dcd]['classe']}"
                f" ({srv.processos_2g[dcd]['situacao']})</em>"
                "<em class='list__hierarquia-dependentes__item__label__info__data'>21/10/2024</em>"
                "</div></label></div>" for dcd in info.get("dependentes") or [])
            corpo = ""
            if deps:
                corpo = ("<div class='modal__lista-processos__item__body'><button "
                         "class='modal__lista-processos__item__body__expand' id='btnExpand'>"
                         "<span class='text'>Incidentes, ações acidentais, recursos e execuções "
                         f"de sentenças({len(info['dependentes'])})</span></button>"
                         "<div class='list__hierarquia-dependentes' id='exibindoDependentes' "
                         f"hidden='true'>{deps}</div></div>")
            secoes.append(
                "<section class='modal__lista-processos__item'>"
                "<div class='modal__lista-processos__item__header'>"
                "<div class='modal__lista-processos__item__header modal__process-choice'>"
                "<input class='custom-radio' type='radio' name='processoSelecionado' "
                f"id='processoSelecionado' value='{cd}'><div>"
                "<em class='modal__lista-processos__item__header modal__process-choice__number'>"
                f"{info['numero'].formatado}</em>"
                "<em class='modal__process-choice__instancia d-ib'>2º Grau</em>"
                f"<em class='modal__process-choice__instancia d-ib ml-10'>{info['situacao']}</em>"
                "</div></div><div class='modal__lista-processos__item__header__process-info'>"
                "<div class='modal__lista-processos__item__header__process-info__content'>"
                "<div class='modal__lista-processos__item__header__process-info__content__item'>"
                f"{info['classe']}</div><div class='modal__lista-processos__item__header__"
                "process-info__content__item data'>22/02/2024</div></div></div></div>"
                f"{corpo}</section>")
        modal = ("<div id='modalIncidentes' class='modal-main'><div class='modal-body p-0'>"
                 "<div class='modal-header'><h5>Selecione o processo</h5></div>"
                 f"<article class='modal__lista-processos'>{''.join(secoes)}</article>"
                 "<div class='modal-footer'><input type='button' name='btFechar' value='Cancelar' "
                 "id='botaoFecharPopupIncidentes'><input type='button' name='btEnviarIncidente' "
                 "value='Selecionar' id='botaoEnviarIncidente'></div></div></div>")
        return self._pagina("<div class='div-conteudo container'><h1>Consulta de Processos de "
                            f"2º Grau</h1></div>{modal}")

    def _tela_lista_2g(self, codigos):
        srv = self.servidor
        itens = "".join(
            "<li><div class='row unj-ai-c home__lista-de-processos'>"
            f"<a class='linkProcesso' href='/cposg5/show.do?processo.codigo={cd}"
            f"&processo.foro=900'>{srv.processos_2g[cd]['numero'].formatado}</a>"
            f"<div class='classeProcesso'>{srv.processos_2g[cd]['classe']}</div></div></li>"
            for cd in codigos)
        return self._pagina("<div class='div-conteudo container'><div id='listagemDeProcessos'>"
                            f"<ul class='unj-list-row'>{itens}</ul></div></div>")

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        srv = self.servidor
        srv.pedidos.append(("GET", self.path))
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
        if rota.startswith("/cposg5/"):
            return self._get_2g(rota, q)
        if rota.startswith("/pastadigital/sg/"):
            return self._get_pasta(rota, q, srv.processos_2g, "2g")
        if not self._logado():
            if rota.startswith("/cpopg/abrirPastaDigital"):
                return self._enviar(200, "Não foi possível validar o seu acesso.", "text/plain")
            return self._ir("/sajcas/login")

        if rota == "/cpopg/search.do":
            numero = q.get("dadosConsulta.valorConsultaNuUnificado", [""])[0]
            foro = q.get("foroNumeroUnificado", [""])[0]
            if not numero or numero[-4:] != foro:
                return self._enviar(200, self._pagina("Foro inválido para o número"))
            cd = srv.por_numero.get(numero)
            if cd == "lista":
                linhas = "".join(
                    f"<tr><td><a href='/cpopg/show.do?processo.codigo={c}&processo.foro=1'>"
                    f"{srv.processos[c]['numero'].principal}</a></td><td>Cível</td></tr>"
                    for c in ("1K0099ZZZ0000", "1K0005EEE0000"))
                return self._enviar(200, self._pagina(f"<table>{linhas}</table>"))
            if cd is None:
                return self._enviar(200, self._pagina(
                    "<p>Não existem informações disponíveis para os parâmetros informados.</p>"))
            foro_cd = _foro_sem_zeros(srv.processos[cd]["numero"])
            return self._ir(f"/cpopg/show.do?processo.codigo={cd}&processo.foro={foro_cd}"
                            f"&processo.numero={numero}")
        if rota == "/cpopg/show.do":
            cd = q.get("processo.codigo", [""])[0]
            info = srv.processos.get(cd)
            foro = q.get("processo.foro", ["1"])[0]
            if info is None or foro != _foro_sem_zeros(info["numero"]):
                # foro errado (o 56 fixo da base) não abre o processo
                return self._enviar(200, self._pagina("Não foi possível validar o seu acesso."))
            return self._enviar(200, self._tela_processo(cd, info))
        if rota == "/cpopg/senha.do":
            cd = q.get("cd", [""])[0]
            info = srv.processos.get(cd, {})
            cab = []
            if q.get("senha", [""])[0] == info.get("senha"):
                cab.append(("Set-Cookie", f"LIB_{cd}=1; Path=/"))
            foro_cd = _foro_sem_zeros(info["numero"]) if info else "1"
            return self._ir(f"/cpopg/show.do?processo.codigo={cd}&processo.foro={foro_cd}", cab)
        if rota == "/cpopg/abrirPastaDigital.do":
            cd = q.get("processo.codigo", [""])[0]
            info = srv.processos.get(cd)
            if info is None or (info.get("senha") and self._cookies().get(f"LIB_{cd}") != "1"):
                return self._enviar(200, "Não foi possível validar o seu acesso.", "text/plain")
            return self._enviar(200, f"{srv.base}/pastadigital/abrirPastaProcessoDigital.do"
                                     f"?cd={cd}", "text/plain")
        if rota.startswith("/pastadigital/"):
            return self._get_pasta(rota, q, srv.processos, "1g")
        return self._enviar(404, "não encontrado")

    def _get_2g(self, rota, q):
        """As rotas da consulta de 2º grau (/cposg5)."""
        srv = self.servidor
        if rota == "/cposg5/open.do":
            if "gateway" in q:
                if not self._logado():
                    return self._ir("/sajcas/login?service=cposg5")
                # a consulta passa a reconhecer o login (o "SSO por webapp")
                token = srv.sessao_2g_nova()
                return self._enviar(200, self._tela_consulta_2g(),
                                    cabecalhos=[("Set-Cookie", f"SG5={token}; Path=/")])
            return self._enviar(200, self._tela_consulta_2g())
        if rota == "/cposg5/search.do":
            # só os parâmetros do CPOSG; os do cpopg não são entendidos
            nada = self._tela_consulta_2g(
                "Não existem informações disponíveis para os parâmetros informados.")
            principal = q.get("dePesquisaNuUnificado", [""])[0]
            if (q.get("cbPesquisa") != ["NUMPROC"] or q.get("tipoNuProcesso") != ["UNIFICADO"]
                    or not principal
                    or q.get("numeroDigitoAnoUnificado", [""])[0] != principal[:15]
                    or q.get("foroNumeroUnificado", [""])[0] != principal[-4:]):
                return self._enviar(200, nada)
            resposta = srv.respostas_2g.get(principal)
            if resposta is None:
                return self._enviar(200, nada)
            forma, alvo = resposta
            if forma == "pagina":
                return self._enviar(200, self._tela_processo_2g(alvo, srv.processos_2g[alvo]))
            if forma == "modal":
                return self._enviar(200, self._tela_modal_2g(alvo))
            return self._enviar(200, self._tela_lista_2g(alvo))
        if rota == "/cposg5/show.do":
            cd = q.get("processo.codigo", [""])[0]
            info = srv.processos_2g.get(cd)
            foro = q.get("processo.foro", ["900"])[0]
            if info is None or foro != "900":
                # o foro do número (a origem) não é o do 2º grau
                return self._enviar(200, self._tela_consulta_2g(
                    "Não existem informações disponíveis para os parâmetros informados."))
            return self._enviar(200, self._tela_processo_2g(cd, info))
        if rota == "/cposg5/verificarAcessoPastaDigital.do":
            cd = q.get("cdProcesso", [""])[0]
            info = srv.processos_2g.get(cd)
            if not self._logado_2g():
                # sem login no portal, ou a consulta ainda não o reconheceu
                return self._enviar(401, "Não foi possível validar o seu acesso.", "text/plain")
            if info is None:
                return self._enviar(404, "Não foi possível validar o seu acesso.", "text/plain")
            if info.get("senha") and self._cookies().get(f"LIB2_{cd}") != "1":
                return self._enviar(403, self._popup_senha_2g(True))
            return self._enviar(200, f"{srv.base}/pastadigital/sg/abrirPastaProcessoDigital.do"
                                     f"?cdProcesso={cd}&cdForo=900&tpOrigem=2&flOrigem=S"
                                     f"&nmAlias=SG5TJ&ticket={uuid.uuid4().hex}", "text/plain")
        return self._enviar(404, "não encontrado")

    def _get_pasta(self, rota, q, processos, grau):
        """A Pasta Digital: /pastadigital/... (1º grau) e /pastadigital/sg/...
        (2º grau). Cada caminho só serve os processos do seu grau."""
        srv = self.servidor
        if not self._logado():
            return self._ir("/sajcas/login")
        prefixo = "/pastadigital/sg/" if grau == "2g" else "/pastadigital/"
        nome = rota[len(prefixo):]
        rotulo = "servidor 2g" if grau == "2g" else "servidor"
        if nome == "abrirPastaProcessoDigital.do":
            info = processos.get((q.get("cdProcesso") or q.get("cd") or [""])[0])
            if info is None:
                return self._enviar(404, "não encontrado")
            arvore = json.dumps(info["arvore"])
            return self._enviar(200, f"<html><body><div>Pasta Digital</div>"
                                     f"<script>var requestScope = {arvore};</script></body></html>")
        if nome == "documentoFinal.do":
            loc = srv.localizadores.get(q.get("loc", [""])[0])
            if loc is None or loc["grau"] != grau:
                return self._enviar(404, "não encontrado")
            return self._enviar(200, _pdf(loc["paginas"], rotulo), "application/pdf")
        if nome == "getPDF.do":
            cd = q.get("cdDocumento", [""])[0]
            dono = next((i for i in processos.values()
                         if any(cd == str(d["data"]["cdDocumento"]) for d in i["arvore"])), None)
            if dono is None or cd in dono.get("pecas_ausentes", set()):
                return self._enviar(404, "não encontrado")
            paginas = int(q["numFinal"][0]) - int(q["numInicial"][0]) + 1
            texto = f"peça 2g {cd}" if grau == "2g" else f"peça {cd}"
            return self._enviar(200, _pdf(paginas, texto), "application/pdf")
        if nome == "getArquivo.do":
            return self._enviar(404, "não encontrado")
        if nome == "getMidia.do" and grau == "1g":
            return self._enviar(200, b"ID3" + b"\x00" * 2000, "audio/mpeg")
        return self._enviar(404, "não encontrado")

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        srv = self.servidor
        srv.pedidos.append(("POST", self.path))
        bruto, form = self._form()
        if url.path == "/sajcas/login":
            if form.get("username", [""])[0] == USUARIO and form.get("password", [""])[0] == SENHA:
                return self._enviar(200, self._tela_codigo())
            return self._enviar(200, self._tela_login("Usuário ou senha inválidos."))
        if url.path == "/sajcas/token":
            codigo = form.get("tokenInformado", [""])[0]
            srv.codigos_enviados.append(codigo)
            if codigo == CODIGO:
                return self._ir("/esaj/portal.do", [("Set-Cookie", "SESSAO=ok; Path=/")])
            return self._enviar(200, self._tela_codigo("Código inválido."))
        if url.path == "/cposg5/validarSenhaAcessoProcesso.do":
            cd = form.get("cdProcesso", [""])[0]
            info = srv.processos_2g.get(cd) or {}
            if info.get("senha") and form.get("senhaDoProcessoDigitada", [""])[0] == info["senha"]:
                return self._enviar(200, cd, "text/plain",
                                    [("Set-Cookie", f"LIB2_{cd}=1; Path=/")])
            return self._enviar(400, "senhaInvalida", "text/plain")
        if not self._logado():
            return self._enviar(401, "sessão expirada")
        if url.path.startswith("/pastadigital/sg/"):
            return self._post_pasta(url.path[len("/pastadigital/sg/"):], bruto, form,
                                    srv.processos_2g, "2g")
        if url.path.startswith("/pastadigital/"):
            return self._post_pasta(url.path[len("/pastadigital/"):], bruto, form,
                                    srv.processos, "1g")
        return self._enviar(404, "não encontrado")

    def _post_pasta(self, nome, bruto, form, processos, grau):
        srv = self.servidor
        prefixo = "/pastadigital/sg" if grau == "2g" else "/pastadigital"
        if nome == "salvarDocumentoPreparado.do":
            cd = form.get("cdProcesso", [""])[0]
            if cd not in processos:
                return self._enviar(404, "não encontrado")
            if processos[cd].get("servidor_falha"):
                return self._enviar(500, "<html>Erro interno do servidor</html>")
            paginas = 0
            for item in form.get("itensPdfSelecionados", []):
                qi = urllib.parse.parse_qs(item)
                paginas += int(qi["numFinal"][0]) - int(qi["numInicial"][0]) + 1
            loc = str(uuid.uuid4())
            srv.localizadores[loc] = {"cd": cd, "paginas": paginas, "consultas": 0,
                                      "corpo": bruto, "grau": grau}
            return self._enviar(200, loc, "text/plain")
        if nome == "buscarDocumentoFinalizado.do":
            loc = srv.localizadores.get(form.get("localizador", [""])[0])
            if loc is None or loc["grau"] != grau:
                return self._enviar(404, "não encontrado")
            loc["consultas"] += 1
            if loc["consultas"] < 2:                # ainda montando
                return self._enviar(200, "", "text/plain")
            return self._enviar(200, f"{srv.base}{prefixo}/documentoFinal.do"
                                     f"?loc={form['localizador'][0]}", "text/plain")
        return self._enviar(404, "não encontrado")


def servidor_esaj(casos=CASOS, *, pasta_2g_duplicada: bool = False) -> ServidorESAJ:
    """Sobe o e-SAJ falso (já ouvindo) com os casos pedidos.

    ``pasta_2g_duplicada=True``: a Pasta Digital do 2º grau de A numera duas
    peças nas mesmas folhas (a guarda da numeração do 2º grau)."""
    return ServidorESAJ(casos, pasta_2g_duplicada=pasta_2g_duplicada)
