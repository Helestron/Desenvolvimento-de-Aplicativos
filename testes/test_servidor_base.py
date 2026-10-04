"""Servidor local: segurança (token, Host, Origin, estáticos) e o envelope da API.

Este arquivo também traz o apoio dos outros testes do servidor e do
aplicativo: AmbienteTemporario (HELESTRON_LOCAL, HELESTRON_DADOS e as
constantes de helestron.nucleo.caminhos numa pasta temporária - nada toca
em ~ nem em %LOCALAPPDATA%), ServidorDeTeste (um servidor de verdade, em
porta aleatória) e LeitorEventos (o EventSource dos testes).
"""

from __future__ import annotations

import http.client
import json
import os
import queue
import shutil
import socket
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from helestron.nucleo import caminhos, config


# ============================================================ apoio comum
class AmbienteTemporario:
    """Todos os caminhos do programa numa pasta temporária."""

    def __init__(self):
        self.raiz = Path(tempfile.mkdtemp(prefix="helestron-teste-"))
        self.local = self.raiz / "local"
        self.dados = self.raiz / "dados"
        self._patches: list = []
        self.cfg = None

    def iniciar(self) -> "AmbienteTemporario":
        self.local.mkdir(parents=True)
        self.dados.mkdir(parents=True)
        valores = {
            "LOCAL": self.local, "LOGS": self.local / "Logs", "TEMP": self.local / "temp",
            "PERFIS": self.local / "perfis", "MODELOS": self.local / "modelos",
            "ARQUIVO_CONFIG": self.local / "config.ini",
            "ARQUIVO_SENHAS": self.local / "credenciais.json",
            "ARQUIVO_PAUTA": self.local / "pauta.sqlite3",
            "ARQUIVO_INSTANCIA": self.local / "instancia.json",
            "BASE_USUARIO": self.dados,
        }
        self._patches.append(mock.patch.dict(os.environ, {
            "HELESTRON_LOCAL": str(self.local), "HELESTRON_DADOS": str(self.dados)}))
        for nome, valor in valores.items():
            self._patches.append(mock.patch.object(caminhos, nome, valor, create=True))
        for p in self._patches:
            p.start()
        self.cfg = config.Config(self.local / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.dados / "Acervo"))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.dados / "Sigilosos"))
        return self

    def parar(self) -> None:
        for p in reversed(self._patches):
            try:
                p.stop()
            except RuntimeError:
                pass
        self._patches.clear()
        shutil.rmtree(self.raiz, ignore_errors=True)


class Cliente:
    """Pedidos HTTP ao servidor de teste, com o token certo por padrão."""

    def __init__(self, app):
        self.app = app

    @property
    def porta(self) -> int:
        return self.app.porta

    def pedir(self, metodo: str, caminho: str, corpo=None, token: bool | str = True,
              cabecalhos: dict | None = None, bruto: bytes | None = None,
              tipo: str = "application/json", espera: float = 30.0):
        conexao = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=espera)
        h = dict(cabecalhos or {})
        if token is True:
            h["X-Helestron-Token"] = self.app.token
        elif isinstance(token, str):
            h["X-Helestron-Token"] = token
        dados = bruto
        if dados is None and corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
        if dados is not None:
            h.setdefault("Content-Type", tipo)
        try:
            conexao.request(metodo, caminho, body=dados, headers=h)
            resposta = conexao.getresponse()
            conteudo = resposta.read()
            cabeca = dict(resposta.getheaders())
        finally:
            conexao.close()
        try:
            envelope = json.loads(conteudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            envelope = conteudo
        self.ultimos_cabecalhos = cabeca
        return resposta.status, envelope

    def get(self, caminho, **kw):
        return self.pedir("GET", caminho, **kw)

    def post(self, caminho, corpo=None, **kw):
        return self.pedir("POST", caminho, corpo if corpo is not None else {}, **kw)

    def delete(self, caminho, **kw):
        return self.pedir("DELETE", caminho, **kw)

    def dados(self, metodo: str, caminho: str, corpo=None, esperado: int = 200):
        status, envelope = self.pedir(metodo, caminho, corpo)
        if status != esperado:
            raise AssertionError(f"{metodo} {caminho}: {status} {envelope}")
        return envelope["dados"] if esperado == 200 else envelope

    def enviar(self, caminho: str, nome: str, conteudo: bytes, campos: dict | None = None,
               campo: str = "arquivo"):
        fronteira = "----helestron" + uuid.uuid4().hex
        partes = []
        for chave, valor in (campos or {}).items():
            partes.append(f"--{fronteira}\r\nContent-Disposition: form-data; name=\"{chave}\""
                          f"\r\n\r\n{valor}\r\n".encode("utf-8"))
        partes.append(f"--{fronteira}\r\nContent-Disposition: form-data; name=\"{campo}\"; "
                      f"filename=\"{nome}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                      .encode("utf-8") + conteudo + b"\r\n")
        partes.append(f"--{fronteira}--\r\n".encode("utf-8"))
        return self.pedir("POST", caminho, bruto=b"".join(partes),
                          tipo=f"multipart/form-data; boundary={fronteira}")

    def eventos(self) -> "LeitorEventos":
        return LeitorEventos(self.porta, self.app.token)


class LeitorEventos:
    """Lê o fluxo SSE numa thread e guarda os eventos para o teste esperar."""

    def __init__(self, porta: int, token: str):
        self.conexao = http.client.HTTPConnection("127.0.0.1", porta, timeout=60)
        self.conexao.request("GET", f"/api/eventos?t={token}")
        # O http.client larga o socket depois do getresponse() (Connection:
        # close), mas o arquivo da resposta continua com ele: guardado aqui
        # para fechar() conseguir desligá-lo.
        self._socket = self.conexao.sock
        self.resposta = self.conexao.getresponse()
        self.status = self.resposta.status
        self.fila: queue.Queue = queue.Queue()
        self.recebidos: list[tuple[str, dict]] = []
        self._thread = threading.Thread(target=self._ler, daemon=True)
        self._thread.start()

    def _ler(self) -> None:
        tipo, dados = None, []
        try:
            while True:
                linha = self.resposta.readline()
                if not linha:
                    break
                linha = linha.decode("utf-8").rstrip("\n")
                if linha.startswith("event: "):
                    tipo = linha[7:]
                elif linha.startswith("data: "):
                    dados.append(linha[6:])
                elif linha == "" and tipo:
                    evento = (tipo, json.loads("\n".join(dados) or "{}"))
                    self.recebidos.append(evento)
                    self.fila.put(evento)
                    tipo, dados = None, []
        except Exception:                 # conexão fechada pelo teste, no meio da leitura
            pass
        self.fila.put(None)

    def esperar(self, tipo: str, condicao=None, espera: float = 15.0) -> dict:
        """O primeiro evento 'tipo' (já recebido ou que chegar) que satisfaz a condição."""
        for t, d in list(self.recebidos):
            if t == tipo and (condicao is None or condicao(d)):
                return d
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            try:
                evento = self.fila.get(timeout=max(0.05, limite - time.monotonic()))
            except queue.Empty:
                break
            if evento is None:
                break
            t, d = evento
            if t == tipo and (condicao is None or condicao(d)):
                return d
        raise AssertionError(f"evento {tipo!r} não chegou; recebidos: "
                             f"{[t for t, _ in self.recebidos][-30:]}")

    def fechar(self) -> None:
        """Fecha de verdade (como a aba fechada): o arquivo da resposta
        segura o socket aberto, então ele é desligado antes."""
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        for fechar in (self.resposta.close, self.conexao.close):
            try:
                fechar()
            except OSError:
                pass


class ServidorDeTeste(unittest.TestCase):
    """Um servidor de verdade, em porta aleatória, com caminhos temporários."""

    pasta_web: Path | None = None

    def setUp(self):
        from helestron.servidor.aplicacao import Aplicacao

        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.cfg = self.amb.cfg
        web = self.pasta_web if self.pasta_web is not None else self.amb.raiz / "sem-web"
        self.app = Aplicacao(self.cfg, modo="servidor", pasta_web=web).iniciar()
        self.addCleanup(self.app.encerrar, espera_tarefas_s=10, espera_audiencia_s=10)
        self.cliente = Cliente(self.app)
        self._leitores: list[LeitorEventos] = []

    def eventos(self) -> LeitorEventos:
        leitor = self.cliente.eventos()
        self._leitores.append(leitor)
        self.addCleanup(leitor.fechar)
        leitor.esperar("estado")            # conectado
        return leitor

    def esperar_tarefa(self, id_tarefa: str, espera: float = 20.0) -> dict:
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            dados = self.cliente.dados("GET", f"/api/tarefas/{id_tarefa}")
            if dados["estado"] != "rodando":
                return dados
            time.sleep(0.05)
        raise AssertionError(f"a tarefa {id_tarefa} não terminou")


# ================================================================== testes
class TestSeguranca(ServidorDeTeste):
    def test_sem_token_403(self):
        status, env = self.cliente.get("/api/estado", token=False)
        self.assertEqual(status, 403)
        self.assertEqual(env["erro"]["codigo"], "token_invalido")
        self.assertFalse(env["ok"])

    def test_token_errado_403(self):
        status, env = self.cliente.get("/api/ping", token="x" * 43)
        self.assertEqual(status, 403)

    def test_token_na_consulta_so_vale_para_eventos(self):
        status, _ = self.cliente.get(f"/api/ping?t={self.app.token}", token=False)
        self.assertEqual(status, 403)
        leitor = self.eventos()
        self.assertEqual(leitor.status, 200)

    def test_host_estranho_403(self):
        conexao = http.client.HTTPConnection("127.0.0.1", self.app.porta, timeout=10)
        conexao.putrequest("GET", "/api/ping", skip_host=True)
        conexao.putheader("Host", f"atacante.example:{self.app.porta}")
        conexao.putheader("X-Helestron-Token", self.app.token)
        conexao.endheaders()
        resposta = conexao.getresponse()
        corpo = json.loads(resposta.read())
        conexao.close()
        self.assertEqual(resposta.status, 403)
        self.assertEqual(corpo["erro"]["codigo"], "host_invalido")

    def test_host_estranho_tambem_nos_estaticos(self):
        conexao = http.client.HTTPConnection("127.0.0.1", self.app.porta, timeout=10)
        conexao.putrequest("GET", "/", skip_host=True)
        conexao.putheader("Host", "127.0.0.1.nip.io")
        conexao.endheaders()
        resposta = conexao.getresponse()
        resposta.read()
        conexao.close()
        self.assertEqual(resposta.status, 403)

    def test_localhost_aceito(self):
        status, _ = self.cliente.get("/api/ping", cabecalhos={"Host": f"localhost:{self.app.porta}"})
        self.assertEqual(status, 200)

    def test_origin_estranha_403(self):
        status, env = self.cliente.post("/api/config", {"secao": "geral", "chave": "nome_usuario",
                                                        "valor": "x"},
                                        cabecalhos={"Origin": "https://atacante.example"})
        self.assertEqual(status, 403)
        self.assertEqual(env["erro"]["codigo"], "origem_invalida")
        self.assertEqual(self.cfg.texto("geral", "nome_usuario"), "")

    def test_origin_propria_aceita(self):
        status, _ = self.cliente.get("/api/ping",
                                     cabecalhos={"Origin": f"http://127.0.0.1:{self.app.porta}"})
        self.assertEqual(status, 200)

    def test_sem_cors(self):
        status, _ = self.cliente.pedir("OPTIONS", "/api/estado", token=False,
                                       cabecalhos={"Origin": "https://atacante.example"})
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", self.cliente.ultimos_cabecalhos)

    def test_comparacao_em_tempo_constante(self):
        with mock.patch("helestron.servidor.rede.hmac.compare_digest",
                        wraps=__import__("hmac").compare_digest) as comparar:
            self.cliente.get("/api/ping")
        comparar.assert_called()


class TestEstaticos(ServidorDeTeste):
    def setUp(self):
        self.web = Path(tempfile.mkdtemp(prefix="helestron-web-"))
        self.addCleanup(shutil.rmtree, self.web, True)
        (self.web / "css").mkdir()
        (self.web / "js").mkdir()
        (self.web / "index.html").write_text("<!doctype html><title>Helestron</title>",
                                             encoding="utf-8")
        (self.web / "css" / "helestron.css").write_text("body{}", encoding="utf-8")
        (self.web / "js" / "app.js").write_text("console.log(1)", encoding="utf-8")
        (self.web.parent / "segredo.txt").write_text("SEGREDO-123", encoding="utf-8")
        self.pasta_web = self.web
        super().setUp()

    def test_index_e_arquivos_sem_token(self):
        status, corpo = self.cliente.get("/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"Helestron", corpo)
        self.assertIn("default-src 'self'",
                      self.cliente.ultimos_cabecalhos.get("Content-Security-Policy", ""))
        status, corpo = self.cliente.get("/css/helestron.css", token=False)
        self.assertEqual((status, corpo), (200, b"body{}"))
        self.assertTrue(self.cliente.ultimos_cabecalhos["Content-Type"].startswith("text/css"))
        status, _ = self.cliente.get("/js/app.js", token=False)
        self.assertEqual(status, 200)

    def test_ponto_ponto_404(self):
        for caminho in ("/css/../../segredo.txt", "/css/%2e%2e/%2e%2e/segredo.txt",
                        "/js/..%2f..%2fsegredo.txt", "/css/..\\..\\segredo.txt",
                        "/../segredo.txt", "/fontes/./x"):
            with self.subTest(caminho=caminho):
                status, corpo = self.cliente.get(caminho, token=False)
                self.assertEqual(status, 404)
                self.assertNotIn(b"SEGREDO-123", corpo if isinstance(corpo, bytes) else b"")

    def test_script_embutido_da_propria_pagina_entra_pelo_hash(self):
        import base64
        import hashlib

        (self.web / "index.html").write_text(
            "<!doctype html><script>window.x=1</script><script src='/js/app.js'></script>",
            encoding="utf-8")
        status, _ = self.cliente.get("/", token=False)
        csp = self.cliente.ultimos_cabecalhos["Content-Security-Policy"]
        digesto = base64.b64encode(hashlib.sha256(b"window.x=1").digest()).decode()
        self.assertIn(f"'sha256-{digesto}'", csp)
        self.assertNotIn("unsafe-inline' ;", csp.split("style-src")[0])
        self.assertNotIn("'unsafe-inline'", csp.split("style-src")[0])

    def test_fora_dos_prefixos_404(self):
        status, _ = self.cliente.get("/segredo.txt", token=False)
        self.assertEqual(status, 404)

    def test_link_para_fora_recusado(self):
        alvo = self.web / "js" / "fuga.js"
        try:
            alvo.symlink_to(self.web.parent / "segredo.txt")
        except (OSError, NotImplementedError):
            self.skipTest("sem links simbólicos aqui")
        status, _ = self.cliente.get("/js/fuga.js", token=False)
        self.assertEqual(status, 404)


class TestSemInterface(ServidorDeTeste):
    def test_pagina_minima_quando_falta_o_index(self):
        status, corpo = self.cliente.get("/", token=False)
        self.assertEqual(status, 200)
        self.assertIn("Helestron".encode(), corpo)
        self.assertIn("interface".encode(), corpo)


class TestEnvelope(ServidorDeTeste):
    def test_sucesso(self):
        status, env = self.cliente.get("/api/ping")
        self.assertEqual(status, 200)
        self.assertEqual(env["ok"], True)
        self.assertEqual(env["dados"]["nome"], "Helestron")
        self.assertEqual(self.cliente.ultimos_cabecalhos["Cache-Control"], "no-store")

    def test_rota_inexistente_404(self):
        status, env = self.cliente.get("/api/nada")
        self.assertEqual(status, 404)
        self.assertEqual(set(env["erro"]), {"codigo", "mensagem", "detalhe"})

    def test_metodo_errado_405(self):
        status, env = self.cliente.delete("/api/estado")
        self.assertEqual(status, 405)
        self.assertFalse(env["ok"])

    def test_json_ilegivel_400(self):
        status, env = self.cliente.pedir("POST", "/api/config", bruto=b"{nada")
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "json_invalido")

    def test_corpo_grande_demais_413(self):
        # Só o cabeçalho anuncia 3 MB: o servidor recusa sem ler o corpo (e
        # fecha a conexão), então o teste nem chega a mandá-lo.
        conexao = http.client.HTTPConnection("127.0.0.1", self.app.porta, timeout=10)
        conexao.putrequest("POST", "/api/relacao/texto")
        conexao.putheader("X-Helestron-Token", self.app.token)
        conexao.putheader("Content-Type", "application/json")
        conexao.putheader("Content-Length", str(3 * 1024 * 1024))
        conexao.endheaders()
        resposta = conexao.getresponse()
        corpo = json.loads(resposta.read())
        conexao.close()
        self.assertEqual(resposta.status, 413)
        self.assertEqual(corpo["erro"]["codigo"], "corpo_grande_demais")
        self.assertEqual(resposta.getheader("Connection"), "close")

    def test_envio_grande_demais_413(self):
        conexao = http.client.HTTPConnection("127.0.0.1", self.app.porta, timeout=10)
        conexao.putrequest("POST", "/api/relacao/arquivo")
        conexao.putheader("X-Helestron-Token", self.app.token)
        conexao.putheader("Content-Type", "multipart/form-data; boundary=x")
        conexao.putheader("Content-Length", str(501 * 1024 * 1024))
        conexao.endheaders()
        resposta = conexao.getresponse()
        corpo = json.loads(resposta.read())
        conexao.close()
        self.assertEqual(resposta.status, 413)
        self.assertEqual(corpo["erro"]["codigo"], "envio_grande_demais")

    def test_erro_interno_vira_500_com_mensagem(self):
        with mock.patch("helestron.servidor.api_geral.listar_tribunais",
                        side_effect=RuntimeError("quebrou")):
            from helestron.servidor import rotas

            self.app.servidor.roteador = rotas.montar()
            status, env = self.cliente.get("/api/tribunais")
        self.assertEqual(status, 500)
        self.assertEqual(env["erro"]["codigo"], "erro_interno")
        self.assertIn("RuntimeError", env["erro"]["detalhe"])
        self.assertIn("Logs", env["erro"]["mensagem"])

    def test_estado_no_formato_da_especificacao(self):
        dados = self.cliente.dados("GET", "/api/estado")
        for chave in ("nome", "versao", "modo", "pastas", "pendencias", "resumo", "tarefas"):
            self.assertIn(chave, dados)
        self.assertEqual(set(dados["pastas"]),
                         {"acervo", "processos", "transcricoes", "sigilosos", "pauta", "logs"})
        for chave in ("processos", "transcricoes", "ultimos_lotes", "transcricoes_recentes",
                      "pauta"):
            self.assertIn(chave, dados["resumo"])
        for p in dados["pendencias"]:
            self.assertEqual(set(p) & {"chave", "titulo", "mensagem", "acao"},
                             {"chave", "titulo", "mensagem", "acao"})
        self.assertTrue(any(p["chave"] == "acessos" for p in dados["pendencias"]))
        self.assertEqual(dados["pastas"]["pauta"], str(self.amb.dados / "Pauta"))


class TestEventosBasicos(ServidorDeTeste):
    def test_conecta_recebe_e_reconecta(self):
        leitor = self.eventos()
        self.app.hub.publicar("aviso", {"titulo": "Oi", "mensagem": "mundo", "nivel": "info"})
        self.assertEqual(leitor.esperar("aviso")["titulo"], "Oi")
        leitor.fechar()
        segundo = self.eventos()                 # reconexão: fila nova, recomeça limpa
        self.app.hub.publicar("estado", {"x": 1})
        segundo.esperar("estado", lambda d: d.get("x") == 1)

    def test_ping_periodico(self):
        with mock.patch("helestron.servidor.api_geral.INTERVALO_PING_S", 0.2):
            leitor = self.eventos()
            leitor.esperar("ping", espera=5)

    def test_encerrar_fecha_o_fluxo(self):
        leitor = self.eventos()
        self.app.hub.fechar()
        leitor._thread.join(5)
        self.assertFalse(leitor._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
