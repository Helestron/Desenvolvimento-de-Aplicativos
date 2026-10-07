"""O servidor HTTP local: só em 127.0.0.1, porta livre, token por execução.

Biblioteca padrão pura (http.server.ThreadingHTTPServer, uma thread daemon
por conexão): nada de framework, nada de dependência a mais no instalador.

Segurança (seção 6.1 da especificação):

  * escuta só em 127.0.0.1, na porta que o sistema der (nunca uma fixa);
  * a API exige o token desta execução no cabeçalho X-Helestron-Token (no
    EventSource, que não manda cabeçalho, vale ?t=), comparado em tempo
    constante;
  * recusa (403) o pedido cujo Host não seja 127.0.0.1:PORTA ou
    localhost:PORTA - uma página da internet que aponte o próprio domínio
    para 127.0.0.1 (DNS rebinding) chega com o Host dela - e o pedido com
    Origin diferente da própria origem. Sem CORS: nenhuma outra origem lê
    nada daqui;
  * arquivos estáticos (/, /css, /js, /img, /fontes) só de dentro de
    helestron/web, sem token, com o caminho normalizado e '..' recusado;
  * corpo JSON até 2 MB; envio de arquivo até 500 MB, gravado em
    LOCAL\\temp e apagado depois.

Toda resposta da API usa o envelope da seção 6.2: {"ok": true, "dados": ...}
ou {"ok": false, "erro": {"codigo", "mensagem", "detalhe"}}.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import re
import socket
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit

from . import eventos, multipart

log = logging.getLogger("servidor.http")

LIMITE_JSON = 2 * 1024 * 1024
LIMITE_ENVIO = 500 * 1024 * 1024
CABECALHO_TOKEN = "X-Helestron-Token"
PREFIXOS_ESTATICOS = ("/css/", "/js/", "/img/", "/fontes/")
TIPOS = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff",
    ".ttf": "font/ttf", ".otf": "font/otf", ".txt": "text/plain; charset=utf-8",
    ".map": "application/json; charset=utf-8", ".webmanifest": "application/manifest+json",
}
# A interface é toda local: nada de CDN. Sem 'unsafe-inline' em script-src:
# um nome de parte vindo do portal que chegasse ao HTML sem escape não vira
# código (e não lê o token). Os <script> embutidos que a PRÓPRIA página traz
# entram pelo hash (csp_da_pagina); atributos on*="..." não rodam.
CSP_MODELO = ("default-src 'self'; script-src 'self'{hashes}; style-src 'self' 'unsafe-inline'; "
              "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
              "media-src 'self' blob:; object-src 'none'; base-uri 'none'; "
              "frame-ancestors 'none'; form-action 'none'")
CSP = CSP_MODELO.format(hashes="")
_RE_SCRIPT_EMBUTIDO = re.compile(rb"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>",
                                 re.IGNORECASE | re.DOTALL)
_RE_TOKEN = re.compile(r"([?&]t=)[^&\s\"]+")


def mascarar_token(texto: str) -> str:
    """O texto com o token da URL (?t=...) trocado por ***."""
    return _RE_TOKEN.sub(r"\1***", str(texto))


def csp_da_pagina(html: bytes) -> str:
    """A CSP com o hash de cada <script> embutido da página servida."""
    hashes = []
    for m in _RE_SCRIPT_EMBUTIDO.finditer(html):
        digesto = base64.b64encode(hashlib.sha256(m.group(1)).digest()).decode("ascii")
        hashes.append(f" 'sha256-{digesto}'")
    return CSP_MODELO.format(hashes="".join(dict.fromkeys(hashes)))

PAGINA_MINIMA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Helestron</title>
<style>
body{margin:0;font:15px "Segoe UI Variable","Segoe UI",system-ui,sans-serif;color:#1C1C1E;
background:linear-gradient(160deg,#FFFFFF,#E8F1FF);min-height:100vh;display:flex;
align-items:center;justify-content:center}
main{background:rgba(255,255,255,.62);backdrop-filter:blur(24px) saturate(180%);
border:1px solid rgba(255,255,255,.7);box-shadow:0 8px 32px rgba(11,26,51,.08);
border-radius:20px;padding:32px 40px;max-width:520px}
h1{font-size:28px;margin:0 0 8px;color:#0B1A33}p{color:#6B7280;line-height:1.5}
</style></head><body><main><h1>Helestron</h1>
<p>O servidor do Helestron está funcionando, mas a interface (pasta <code>web</code>)
não foi encontrada nesta instalação. Instale o Helestron de novo com o
Helestron-Setup: ele conserta a instalação sem apagar os seus dados.</p>
</main></body></html>
"""


# ===================================================================== erros
class ErroApi(Exception):
    """Erro com frase pronta para o usuário (vira o envelope de erro)."""

    def __init__(self, status: int, codigo: str, mensagem: str, detalhe: str = ""):
        super().__init__(mensagem)
        self.status = int(status)
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhe = detalhe

    def como_dict(self) -> dict:
        erro = {"codigo": self.codigo, "mensagem": self.mensagem}
        if self.detalhe:
            erro["detalhe"] = self.detalhe
        return {"ok": False, "erro": erro}


def erro_400(mensagem: str, codigo: str = "pedido_invalido", detalhe: str = "") -> ErroApi:
    return ErroApi(400, codigo, mensagem, detalhe)


# ===================================================================== rotas
@dataclass
class Rota:
    metodo: str
    padrao: re.Pattern
    modelo: str
    funcao: Callable


class Roteador:
    """Rotas com parâmetros no caminho: '/api/tarefas/{id}/parar'."""

    def __init__(self):
        self.rotas: list[Rota] = []

    def adicionar(self, metodo: str, modelo: str, funcao: Callable) -> None:
        regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", re.escape(modelo).replace(r"\{", "{")
                       .replace(r"\}", "}"))
        self.rotas.append(Rota(metodo.upper(), re.compile(f"^{regex}$"), modelo, funcao))

    def get(self, modelo: str):
        return lambda f: (self.adicionar("GET", modelo, f), f)[1]

    def post(self, modelo: str):
        return lambda f: (self.adicionar("POST", modelo, f), f)[1]

    def delete(self, modelo: str):
        return lambda f: (self.adicionar("DELETE", modelo, f), f)[1]

    def achar(self, metodo: str, caminho: str) -> tuple[Rota | None, dict, bool]:
        """(rota, parâmetros, caminho_existe_com_outro_metodo)."""
        outro = False
        for r in self.rotas:
            m = r.padrao.match(caminho)
            if m:
                if r.metodo == metodo:
                    # o caminho já chega decodificado (_atender): sem unquote de novo
                    return r, dict(m.groupdict()), False
                outro = True
        return None, {}, outro


# ==================================================================== pedido
class Pedido:
    """O que o tratador de uma rota recebe."""

    def __init__(self, tratador: "Tratador", metodo: str, caminho: str, consulta: dict,
                 params: dict):
        self.tratador = tratador
        self.servidor: ServidorLocal = tratador.server       # type: ignore[assignment]
        self.app = self.servidor.app
        self.metodo = metodo
        self.caminho = caminho
        self.consulta = consulta
        self.params = params
        self._json = None
        self._lido = False

    @property
    def tipo_corpo(self) -> str:
        return (self.tratador.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    @property
    def tamanho(self) -> int:
        return self.tratador.tamanho_corpo()

    def arg(self, nome: str, padrao: str = "") -> str:
        valores = self.consulta.get(nome)
        return valores[0] if valores else padrao

    def json(self) -> dict:
        """O corpo JSON (objeto), ou {} se não houver corpo."""
        if self._lido:
            return self._json if isinstance(self._json, dict) else {}
        self._lido = True
        if self.tipo_corpo == "multipart/form-data":
            raise erro_400("Este pedido espera JSON, e não um envio de arquivo.")
        bruto = self.tratador.ler_corpo(LIMITE_JSON)
        if not bruto.strip():
            self._json = {}
            return self._json
        try:
            dados = json.loads(bruto.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erro:
            raise erro_400("O pedido chegou com um JSON ilegível.", "json_invalido",
                           str(erro)) from erro
        if not isinstance(dados, dict):
            raise erro_400("O pedido deve ser um objeto JSON.", "json_invalido")
        self._json = dados
        return dados

    def envio(self, pasta: Path) -> multipart.Envio:
        """O envio de arquivo (multipart). Apague com Envio.apagar() / with."""
        if self._lido:
            raise erro_400("O corpo do pedido já foi lido.")
        self._lido = True
        tamanho = self.tamanho
        if tamanho > LIMITE_ENVIO:
            raise ErroApi(413, "envio_grande_demais",
                          "O arquivo passa de 500 MB, o limite do envio pela página. Na janela "
                          "do Helestron, escolha-o pelo botão “Escolher arquivo”, que não tem "
                          "esse limite.")
        try:
            envio = multipart.ler(self.tratador.rfile, tamanho,
                                  self.tratador.headers.get("Content-Type", ""), pasta,
                                  LIMITE_ENVIO)
        except multipart.EnvioGrandeDemais as erro:
            self.tratador.close_connection = True
            raise ErroApi(413, "envio_grande_demais", "O envio passou do limite de tamanho.",
                          str(erro)) from erro
        except multipart.EnvioInvalido as erro:
            self.tratador.close_connection = True
            raise erro_400("O arquivo não chegou inteiro. Tente enviá-lo de novo.",
                           "envio_invalido", str(erro)) from erro
        finally:
            self.tratador.corpo_consumido = True
        return envio

    # ----------------------------------------------------------- campos
    def campo(self, nome: str, obrigatorio: bool = False, padrao=None, tipo=None):
        dados = self.json()
        if nome not in dados or dados[nome] is None:
            if obrigatorio:
                raise erro_400(f"Falta o campo “{nome}” no pedido.", "campo_ausente")
            return padrao
        valor = dados[nome]
        if tipo is bool:
            if isinstance(valor, str):
                return valor.strip().lower() in ("1", "true", "sim", "s", "on", "yes")
            return bool(valor)
        if tipo is int:
            # OverflowError: o JSON 1e999 (ou Infinity) chega como float
            # infinito, e int() dele não é ValueError - seria um 500.
            try:
                return int(valor)
            except (TypeError, ValueError, OverflowError) as erro:
                raise erro_400(f"O campo “{nome}” deve ser um número inteiro.",
                               "campo_invalido") from erro
        if tipo is str:
            return str(valor)
        if tipo is list:
            if not isinstance(valor, list):
                raise erro_400(f"O campo “{nome}” deve ser uma lista.", "campo_invalido")
            return valor
        if tipo is dict:
            if not isinstance(valor, dict):
                raise erro_400(f"O campo “{nome}” deve ser um objeto.", "campo_invalido")
            return valor
        return valor


class Fluxo:
    """Resposta que não é JSON: o tratador escreve sozinho (eventos SSE)."""

    def __init__(self, escrever: Callable[["Tratador"], None]):
        self.escrever = escrever


# ================================================================== tratador
class Tratador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Helestron"
    sys_version = ""
    # Conexão parada (keep-alive ocioso, cliente travado) não segura a
    # thread para sempre.
    timeout = 120

    server: "ServidorLocal"

    # --------------------------------------------------------- registro
    # O token da URL (?t=, o do /api/eventos e o da página inicial) nunca vai
    # para o registro: a pasta Logs é a que o usuário manda ao suporte.
    def caminho_seguro(self) -> str:
        """O caminho pedido (com a consulta), sem o token."""
        return mascarar_token(getattr(self, "path", "") or "")

    def log_message(self, formato, *args) -> None:                # noqa: N802
        log.debug("%s %s", self.address_string(), mascarar_token(formato % args))

    def log_error(self, formato, *args) -> None:                  # noqa: N802
        # O send_error repete a linha do pedido (com a consulta) na mensagem.
        log.debug("erro HTTP: %s", mascarar_token(formato % args))

    # ---------------------------------------------------------- métodos
    def do_GET(self):                                              # noqa: N802
        self._atender("GET")

    def do_HEAD(self):                                             # noqa: N802
        self._atender("HEAD")

    def do_POST(self):                                             # noqa: N802
        self._atender("POST")

    def do_DELETE(self):                                           # noqa: N802
        self._atender("DELETE")

    def do_PUT(self):                                              # noqa: N802
        self._atender("PUT")

    def do_PATCH(self):                                            # noqa: N802
        self._atender("PATCH")

    def do_OPTIONS(self):                                          # noqa: N802
        # Sem CORS: o "preflight" de outra origem não recebe permissão.
        self._atender("OPTIONS")

    # ------------------------------------------------------------ corpo
    def tamanho_corpo(self) -> int:
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return 0

    def ler_corpo(self, limite: int) -> bytes:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self.close_connection = True
            raise ErroApi(411, "tamanho_ausente", "O pedido precisa informar o tamanho do corpo.")
        tamanho = self.tamanho_corpo()
        if tamanho > limite:
            self.close_connection = True
            raise ErroApi(413, "corpo_grande_demais", "O pedido é grande demais.")
        dados = self.rfile.read(tamanho) if tamanho else b""
        self.corpo_consumido = True
        return dados

    # ---------------------------------------------------------- atender
    def _atender(self, metodo: str) -> None:
        self.corpo_consumido = False
        try:
            partes = urlsplit(self.path)
            caminho = unquote(partes.path or "/")
            consulta = parse_qs(partes.query, keep_blank_values=True)
            if "\x00" in caminho or "\\" in caminho:
                self._json_erro(ErroApi(404, "nao_encontrado", "Página não encontrada."))
                return
            recusa = self.server.conferir_origem(self.headers)
            if recusa is not None:
                self._json_erro(recusa)
                return
            if caminho == "/api" or caminho.startswith("/api/"):
                self._api(metodo, caminho, consulta)
            else:
                self._estatico(metodo, caminho)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception as erro:                       # pragma: no cover - defesa
            log.exception("falha ao atender %s %s", metodo, self.caminho_seguro())
            try:
                self._json_erro(ErroApi(500, "erro_interno", "Algo deu errado no Helestron.",
                                        f"{type(erro).__name__}: {erro}"))
            except Exception:
                self.close_connection = True
        finally:
            if not self.corpo_consumido and self.tamanho_corpo():
                # Corpo não lido (erro antes): a conexão não serve para o
                # próximo pedido.
                self.close_connection = True

    def _api(self, metodo: str, caminho: str, consulta: dict) -> None:
        if not self.server.token_valido(self.headers.get(CABECALHO_TOKEN), caminho, consulta):
            self._json_erro(ErroApi(403, "token_invalido",
                                    "Acesso recusado: esta página não é do Helestron aberto agora. "
                                    "Feche-a e abra o Helestron pelo atalho."))
            return
        rota, params, outro = self.server.roteador.achar(metodo if metodo != "HEAD" else "GET",
                                                         caminho)
        if rota is None:
            if outro:
                self._json_erro(ErroApi(405, "metodo_invalido", "Operação não permitida aqui."))
            else:
                self._json_erro(ErroApi(404, "rota_inexistente", "Operação desconhecida.",
                                        caminho))
            return
        pedido = Pedido(self, metodo, caminho, consulta, params)
        try:
            dados = rota.funcao(pedido)
        except ErroApi as erro:
            if erro.status >= 500:
                log.error("%s %s: %s (%s)", metodo, caminho, erro.mensagem, erro.detalhe)
            self._json_erro(erro)
            return
        except Exception as erro:
            self._json_erro(self.server.traduzir_erro(erro, metodo, caminho))
            return
        if isinstance(dados, Fluxo):
            self.close_connection = True
            dados.escrever(self)
            return
        self.server.app_tocar()
        self._json(200, {"ok": True, "dados": dados}, cabeca=(metodo == "HEAD"))

    # ------------------------------------------------------- respostas
    def _cabecalhos_comuns(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")

    def _json(self, status: int, corpo: dict, cabeca: bool = False) -> None:
        dados = eventos.json_texto(corpo).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self._cabecalhos_comuns()
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if not cabeca:
            self.wfile.write(dados)

    def _json_erro(self, erro: ErroApi) -> None:
        if not self.corpo_consumido and self.tamanho_corpo():
            self.close_connection = True
        self._json(erro.status, erro.como_dict())

    def iniciar_fluxo(self, tipo: str = "text/event-stream") -> None:
        self.send_response(200)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self._cabecalhos_comuns()
        self.end_headers()
        self.close_connection = True

    # ------------------------------------------------------- estáticos
    def _estatico(self, metodo: str, caminho: str) -> None:
        if metodo not in ("GET", "HEAD"):
            self._json_erro(ErroApi(405, "metodo_invalido", "Operação não permitida aqui."))
            return
        pagina = self.server.pagina_inicial
        if caminho in ("/", "/index.html") and pagina is not None:
            corpo, csp = pagina()
            self._enviar(corpo.encode("utf-8"), TIPOS[".html"], metodo == "HEAD", csp)
            return
        arquivo = self.server.arquivo_estatico(caminho)
        if arquivo is None:
            if caminho in ("/", "/index.html"):
                self._enviar(PAGINA_MINIMA.encode("utf-8"), TIPOS[".html"], metodo == "HEAD")
                return
            self._enviar(b"Arquivo n\xc3\xa3o encontrado.", TIPOS[".txt"], metodo == "HEAD",
                         status=404)
            return
        try:
            dados = arquivo.read_bytes()
        except OSError:
            self._enviar(b"Arquivo n\xc3\xa3o encontrado.", TIPOS[".txt"], metodo == "HEAD",
                         status=404)
            return
        tipo = TIPOS.get(arquivo.suffix.lower()) or mimetypes.guess_type(arquivo.name)[0] \
            or "application/octet-stream"
        csp = csp_da_pagina(dados) if tipo.startswith("text/html") else None
        self._enviar(dados, tipo, metodo == "HEAD", csp)

    def _enviar(self, dados: bytes, tipo: str, cabeca: bool, csp: str | None = None,
                status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        # Sem cache: a interface muda com a atualização do programa, e o
        # WebView2 guardaria a versão velha.
        self.send_header("Cache-Control", "no-cache")
        self._cabecalhos_comuns()
        if tipo.startswith("text/html"):
            self.send_header("Content-Security-Policy", csp or CSP)
        self.end_headers()
        if not cabeca:
            self.wfile.write(dados)


# ================================================================== servidor
class ServidorLocal(ThreadingHTTPServer):
    """O servidor do Helestron. 'app' é a Aplicacao (ou o modo de erro)."""

    daemon_threads = True
    allow_reuse_address = False         # no Windows, reuse permite "roubar" a porta
    request_queue_size = 64

    def __init__(self, app, roteador: Roteador, token: str, porta: int = 0,
                 pasta_web: Path | None = None, pagina_inicial=None, icone: Path | None = None):
        self.app = app
        self.roteador = roteador
        self.token = token
        self.pasta_web = Path(pasta_web) if pasta_web is not None else None
        # pagina_inicial() -> (html, csp): substitui o index.html (tela de erro)
        self.pagina_inicial = pagina_inicial
        self.icone = Path(icone) if icone is not None else None
        self._thread: threading.Thread | None = None
        super().__init__(("127.0.0.1", int(porta or 0)), Tratador)
        self.porta = self.server_address[1]
        self.hosts = {f"127.0.0.1:{self.porta}", f"localhost:{self.porta}"}
        self.origens = {f"http://127.0.0.1:{self.porta}", f"http://localhost:{self.porta}"}

    def server_bind(self) -> None:
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Outro programa não consegue abrir a mesma porta "por cima".
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.porta}/"

    def url_com_token(self, extra: str = "") -> str:
        return f"{self.url}?t={self.token}{extra}"

    # -------------------------------------------------------- segurança
    def conferir_origem(self, cabecalhos) -> ErroApi | None:
        host = (cabecalhos.get("Host") or "").strip().lower()
        if host not in self.hosts:
            return ErroApi(403, "host_invalido", "Acesso recusado (endereço inesperado).", host)
        origem = cabecalhos.get("Origin")
        if origem is not None and origem.strip().lower() not in self.origens:
            return ErroApi(403, "origem_invalida", "Acesso recusado (origem inesperada).", origem)
        site = (cabecalhos.get("Sec-Fetch-Site") or "").strip().lower()
        if site == "cross-site":
            return ErroApi(403, "origem_invalida", "Acesso recusado (origem inesperada).", site)
        return None

    def token_valido(self, cabecalho: str | None, caminho: str, consulta: dict) -> bool:
        recebido = cabecalho
        if recebido is None and caminho == "/api/eventos":
            valores = consulta.get("t") or []
            recebido = valores[0] if valores else None
        if not recebido:
            return False
        return hmac.compare_digest(recebido.strip().encode("utf-8"), self.token.encode("utf-8"))

    def arquivo_estatico(self, caminho: str) -> Path | None:
        """O arquivo de helestron/web para o caminho, ou None (404).

        Só os prefixos da interface; cada pedaço do caminho é conferido
        ('..', '.', vazio, ':' de unidade do Windows) e o resultado tem de
        continuar dentro da pasta web depois de resolvido (links incluídos).
        """
        if caminho == "/favicon.ico":
            # O ícone do programa, quando a interface não trouxer o seu.
            proprio = self._dentro_da_web("img/favicon.ico")
            if proprio is None and self.icone is not None and self.icone.is_file():
                return self.icone
            return proprio
        if caminho in ("/", "/index.html"):
            return self._dentro_da_web("index.html")
        if caminho.startswith(PREFIXOS_ESTATICOS):
            return self._dentro_da_web(caminho.lstrip("/"))
        return None

    def _dentro_da_web(self, relativo: str) -> Path | None:
        if self.pasta_web is None:
            return None
        pedacos = relativo.split("/")
        if any(p in ("", ".", "..") or ":" in p or p.startswith("~") for p in pedacos):
            return None
        try:
            raiz = self.pasta_web.resolve()
            alvo = (raiz / Path(*pedacos)).resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        if not alvo.is_relative_to(raiz) or not alvo.is_file():
            return None
        return alvo

    # ---------------------------------------------------------- erros
    def traduzir_erro(self, erro: Exception, metodo: str, caminho: str) -> ErroApi:
        traduzir = getattr(self.app, "traduzir_erro", None)
        if traduzir is not None:
            try:
                resultado = traduzir(erro)
                if resultado is not None:
                    return resultado
            except Exception:                         # pragma: no cover
                pass
        log.error("%s %s falhou:\n%s", metodo, caminho, traceback.format_exc())
        return ErroApi(500, "erro_interno",
                       "Algo deu errado no Helestron. Os detalhes ficaram no registro (pasta "
                       "Logs).", f"{type(erro).__name__}: {erro}")

    def app_tocar(self) -> None:
        tocar = getattr(self.app, "tocar", None)
        if tocar is not None:
            tocar()

    # -------------------------------------------------------- execução
    def iniciar(self) -> "ServidorLocal":
        self._thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.25},
                                        name="servidor-http", daemon=True)
        self._thread.start()
        return self

    def parar(self, espera_s: float = 5.0) -> None:
        try:
            self.shutdown()
        except Exception:                             # pragma: no cover
            pass
        try:
            self.server_close()
        except Exception:                             # pragma: no cover
            pass
        if self._thread is not None:
            self._thread.join(timeout=espera_s)


def esperar_porta(porta: int, espera_s: float = 5.0) -> bool:
    """Para os testes e o --servidor: a porta já aceita conexões?"""
    limite = time.monotonic() + espera_s
    while time.monotonic() < limite:
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.05)
    return False
