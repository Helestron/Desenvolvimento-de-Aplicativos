"""Servidor local: as pastas do sigilo conferidas com o valor que vai valer,
a nuvem longe dos sigilosos e da pauta, as ferramentas que leem o acervo
direto recusadas com as pastas em conflito, número gigante recusado com 400,
campo de arquivo repetido no envio e o token fora do registro."""

from __future__ import annotations

import http.client
import io
import json
import logging
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helestron.servidor import multipart, rede

from testes.test_servidor_base import ServidorDeTeste


def _post_config(cliente, secao: str, chave: str, valor):
    return cliente.post("/api/config", {"secao": secao, "chave": chave, "valor": valor})


# ================================================= pasta em branco (achado 40)
class TestPastaEmBrancoVoltaAoPadrao(ServidorDeTeste):
    """A pasta em branco vale como a pasta padrão: a conferência do sigilo
    usa o padrão, e não a pasta de agora."""

    def gravar(self, secao, chave, valor):
        return self.cliente.dados("POST", "/api/config",
                                  {"secao": secao, "chave": chave, "valor": valor})

    def recusa(self, secao, chave, valor) -> str:
        status, env = _post_config(self.cliente, secao, chave, valor)
        self.assertEqual(status, 400, env)
        self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
        return env["erro"]["mensagem"]

    def test_sigilosos_ou_pauta_no_onedrive_recusados_um_de_cada_vez(self):
        """Os Ajustes recusam os sigilosos ou a pauta em qualquer pasta do
        OneDrive; com as duas lá (configuração antiga), dá para corrigir uma
        de cada vez: cada chave confere só a sua pasta."""
        raiz = self.amb.raiz
        onedrive = raiz / "OneDrive - TJAL"
        with mock.patch.dict("os.environ", {"OneDrive": str(onedrive)}):
            self.assertIn("OneDrive", self.recusa("geral", "pasta_sigilosos",
                                                  str(onedrive / "Sigilosos")))
            self.assertIn("pauta exportada", self.recusa("pauta", "pasta", str(onedrive / "Pauta")))
            # as duas na nuvem, gravadas à mão: a correção de cada uma passa
            self.cfg.definir("geral", "pasta_sigilosos", str(onedrive / "Sigilosos"))
            self.cfg.definir("pauta", "pasta", str(onedrive / "Pauta"))
            self.gravar("pauta", "pasta", str(raiz / "Pauta"))
            self.gravar("geral", "pasta_sigilosos", str(raiz / "Sig"))
            self.cfg.recarregar()
            self.assertEqual(self.cfg.pasta_sigilosos, raiz / "Sig")
            # o acervo pode ser trocado mesmo com os sigilosos na nuvem
            self.cfg.definir("geral", "pasta_sigilosos", str(onedrive / "Sigilosos"))
            self.gravar("geral", "pasta_acervo", str(raiz / "OutroAcervo"))

    def test_acervo_em_branco_com_sigilosos_dentro_do_padrao(self):
        dados, raiz = self.amb.dados, self.amb.raiz
        self.gravar("geral", "pasta_acervo", str(raiz / "D_Acervo"))
        self.gravar("geral", "pasta_sigilosos", str(dados / "Acervo" / "Sig"))
        self.assertIn("sigilosos", self.recusa("geral", "pasta_acervo", ""))
        self.cfg.recarregar()
        self.assertEqual(self.cfg.pasta_acervo, raiz / "D_Acervo")

    def test_sigilosos_em_branco_dentro_do_acervo(self):
        dados, raiz = self.amb.dados, self.amb.raiz
        self.gravar("pauta", "pasta", str(raiz / "Pauta"))
        self.gravar("geral", "pasta_sigilosos", str(raiz / "Sig"))
        self.gravar("geral", "pasta_acervo", str(dados))
        self.recusa("geral", "pasta_sigilosos", "")
        self.cfg.recarregar()
        self.assertEqual(self.cfg.pasta_sigilosos, raiz / "Sig")

    def test_sigilosos_em_branco_contendo_o_acervo(self):
        dados, raiz = self.amb.dados, self.amb.raiz
        self.gravar("geral", "pasta_sigilosos", str(raiz / "Sig"))
        self.gravar("geral", "pasta_acervo", str(dados / "Sigilosos" / "Acervo"))
        self.recusa("geral", "pasta_sigilosos", "")

    def test_acervo_em_branco_com_a_pauta_dentro(self):
        dados, raiz = self.amb.dados, self.amb.raiz
        self.gravar("geral", "pasta_acervo", str(raiz / "Acervo"))
        self.gravar("pauta", "pasta", str(dados / "Acervo" / "Pauta"))
        self.assertIn("pauta", self.recusa("geral", "pasta_acervo", ""))

    def test_acervo_em_branco_com_a_nuvem_dentro(self):
        dados, raiz = self.amb.dados, self.amb.raiz
        self.gravar("geral", "pasta_acervo", str(raiz / "Acervo2"))
        self.gravar("compartilhar", "pasta_nuvem", str(dados / "Acervo" / "OneDrive"))
        self.assertIn("nuvem", self.recusa("geral", "pasta_acervo", ""))

    def test_em_branco_sem_conflito_e_aceito(self):
        ok = self.gravar("geral", "pasta_acervo", "")
        self.assertEqual(ok["valor"], str(self.amb.dados / "Acervo"))
        ok = self.gravar("geral", "pasta_sigilosos", "")
        self.assertEqual(ok["valor"], str(self.amb.dados / "Sigilosos"))
        ok = self.gravar("pauta", "pasta", "")
        self.assertEqual(ok["valor"], str(self.amb.dados / "Pauta"))


# ============================================= sigilosos na nuvem (achado 41)
class TestSigilososEPautaForaDaNuvem(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        # Uma pasta de nuvem que o programa não reconhece pelo caminho (a de
        # um outro serviço, escolhida em Ajustes): aqui vale a regra da pasta
        # do espelho. Os sigilosos em qualquer pasta do OneDrive têm teste
        # próprio (TestPastaEmBrancoVoltaAoPadrao).
        self.nuvem = self.amb.raiz / "Nuvem"
        self.nuvem.mkdir()

    def recusa(self, secao, chave, valor):
        status, env = _post_config(self.cliente, secao, chave, valor)
        self.assertEqual(status, 400, env)
        self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
        return env["erro"]["mensagem"]

    def test_sigilosos_e_pauta_nao_entram_na_nuvem(self):
        self.cliente.dados("POST", "/api/config", {"secao": "compartilhar",
                                                   "chave": "pasta_nuvem",
                                                   "valor": str(self.nuvem)})
        for valor in (self.nuvem, self.nuvem / "Gabinete" / "Sigilosos",
                      self.nuvem / "Helestron - Acervo" / "Sig"):
            with self.subTest(sigilosos=valor):
                self.assertIn("nuvem", self.recusa("geral", "pasta_sigilosos", str(valor)))
        self.assertIn("pauta", self.recusa("pauta", "pasta", str(self.nuvem / "Pauta")))
        self.cfg.recarregar()
        self.assertEqual(self.cfg.pasta_sigilosos, self.amb.dados / "Sigilosos")
        self.assertEqual(self.cfg.pasta_pauta, self.amb.dados / "Pauta")

    def test_nuvem_nao_pode_conter_os_sigilosos_nem_ficar_neles(self):
        sig = self.nuvem / "Sigilosos"
        self.cliente.dados("POST", "/api/config", {"secao": "geral", "chave": "pasta_sigilosos",
                                                   "valor": str(sig)})
        self.recusa("compartilhar", "pasta_nuvem", str(self.nuvem))
        self.recusa("compartilhar", "pasta_nuvem", str(sig / "OD"))
        self.cfg.recarregar()
        self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), "")

    def test_espelhar_recusa_a_nuvem_com_os_sigilosos_dentro(self):
        # config.ini editado à mão: os sigilosos dentro da pasta da nuvem
        self.cfg.definir("geral", "pasta_sigilosos", str(self.nuvem / "Sigilosos"))
        with mock.patch("helestron.compartilhar.nuvem.espelhar") as espelhar:
            status, env = self.cliente.post("/api/compartilhar/nuvem/espelhar",
                                            {"destino": str(self.nuvem)})
        self.assertEqual((status, env["erro"]["codigo"]), (400, "pastas_em_conflito"))
        espelhar.assert_not_called()
        self.cfg.recarregar()
        self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), "")

    def test_espelho_automatico_pula(self):
        from helestron.servidor import api_compartilhar

        self.cfg.definir("geral", "pasta_sigilosos", str(self.nuvem / "Sigilosos"))
        with self.assertLogs("servidor", level="WARNING") as registro:
            self.assertFalse(api_compartilhar.nuvem_sem_conflito(self.cfg, str(self.nuvem)))
        self.assertTrue(any("NÃO feito" in linha for linha in registro.output))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.amb.dados / "Sigilosos"))
        self.assertTrue(api_compartilhar.nuvem_sem_conflito(self.cfg, str(self.nuvem)))


# ============================== ferramentas com pastas em conflito (achado 39)
class TestFerramentasComPastasEmConflito(ServidorDeTeste):
    """Os sigilosos dentro do acervo (config.ini editado à mão): o Claude Code,
    o Cowork, o ChatGPT Work e o Codex leem a pasta inteira - não abrem."""

    def setUp(self):
        super().setUp()
        self.acervo = self.amb.dados / "Acervo"
        self.sig = self.acervo / "Sigilosos"
        (self.sig / "Lote 1").mkdir(parents=True)
        (self.sig / "Lote 1" / "0700123-83.2024.8.02.0001.pdf").write_bytes(b"%PDF-1.4 sigiloso")
        self.cfg.definir("geral", "pasta_sigilosos", str(self.sig))

    def test_nenhuma_ferramenta_que_le_a_pasta_abre(self):
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto") as preparo, \
                mock.patch("helestron.compartilhar.claude.claude_desktop_instalado",
                           return_value=True), \
                mock.patch("helestron.servicos.abrir_no_cowork") as cowork, \
                mock.patch("helestron.compartilhar.claude.abrir_claude_code") as claude_code, \
                mock.patch("helestron.servidor.api_compartilhar._app_chatgpt",
                           return_value=True), \
                mock.patch("helestron.servicos.abrir_chatgpt_work") as chatgpt, \
                mock.patch("helestron.servicos.registrar_mcp_codex") as mcp_codex, \
                mock.patch("helestron.compartilhar.chatgpt.abrir_codex") as codex, \
                mock.patch("helestron.nucleo.sistema.abrir_endereco") as navegador:
            for rota in ("cowork", "claude-code", "chatgpt-work", "codex", "preparar"):
                with self.subTest(rota=rota):
                    status, env = self.cliente.post(f"/api/compartilhar/{rota}")
                    self.assertEqual(status, 409, env)
                    self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
                    self.assertIn("sigilosos", env["erro"]["mensagem"])
        for abrir in (preparo, cowork, claude_code, chatgpt, mcp_codex, codex, navegador):
            abrir.assert_not_called()
        self.assertFalse([t for t in self.app.tarefas.listar() if t.tipo == "preparo"])

    def test_espelhar_tambem_espera(self):
        nuvem = self.amb.raiz / "OneDrive"
        nuvem.mkdir()
        with mock.patch("helestron.compartilhar.nuvem.espelhar") as espelhar:
            status, env = self.cliente.post("/api/compartilhar/nuvem/espelhar",
                                            {"destino": str(nuvem)})
        self.assertEqual((status, env["erro"]["codigo"]), (409, "pastas_em_conflito"))
        espelhar.assert_not_called()

    def test_com_as_pastas_separadas_volta_a_abrir(self):
        self.cfg.definir("geral", "pasta_sigilosos", str(self.amb.dados / "Sigilosos"))
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.compartilhar.claude.abrir_claude_code") as claude_code:
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-code")
        self.assertTrue(dados["abriu"])
        claude_code.assert_called_once_with(self.acervo)


# ======================================================= 1e999 (achado 48)
class TestNumeroGigante(ServidorDeTeste):
    def test_texto_e_json_infinitos_sao_400(self):
        for valor in ("1e999", "-1e999", "inf", "NaN"):
            with self.subTest(valor=valor):
                status, env = _post_config(self.cliente, "download", "tentativas", valor)
                self.assertEqual(status, 400, env)
                self.assertEqual(env["erro"]["codigo"], "valor_invalido")
        for bruto in (b'{"secao": "download", "chave": "tentativas", "valor": 1e999}',
                      b'{"secao": "download", "chave": "tentativas", "valor": Infinity}',
                      b'{"secao": "download", "chave": "tentativas", "valor": -Infinity}'):
            with self.subTest(bruto=bruto):
                status, env = self.cliente.pedir("POST", "/api/config", bruto=bruto)
                self.assertEqual(status, 400, env)
                self.assertEqual(env["erro"]["codigo"], "valor_invalido")

    def test_ajustes_abrem_com_infinito_no_ini(self):
        self.cfg.definir("download", "espera_segundos", "1e999")
        self.cfg.definir("download", "tentativas", "inf")
        dados = self.cliente.dados("GET", "/api/config")
        from helestron.nucleo import config

        self.assertEqual(dados["valores"]["download"]["espera_segundos"],
                         int(config.PADROES[("download", "espera_segundos")]))
        self.assertEqual(dados["valores"]["download"]["tentativas"],
                         int(config.PADROES[("download", "tentativas")]))

    def test_campo_inteiro_infinito(self):
        pedido = rede.Pedido.__new__(rede.Pedido)
        pedido._lido, pedido._json = True, {"n": float("inf"), "m": float("nan")}
        for nome in ("n", "m"):
            with self.subTest(nome=nome):
                with self.assertRaises(rede.ErroApi) as ctx:
                    pedido.campo(nome, tipo=int)
                self.assertEqual(ctx.exception.status, 400)


# ============================================ campo repetido (achado 49)
class TestCampoDeArquivoRepetido(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.pasta, True)

    @staticmethod
    def _parte(nome: str, arquivo: str, dados: bytes) -> bytes:
        return (f'--XyZ\r\nContent-Disposition: form-data; name="{nome}"; filename="{arquivo}"'
                f"\r\nContent-Type: text/csv\r\n\r\n").encode("utf-8") + dados + b"\r\n"

    def ler(self, dados: bytes):
        return multipart.ler(io.BytesIO(dados), len(dados), "multipart/form-data; boundary=XyZ",
                             self.pasta)

    def test_segunda_parte_com_o_mesmo_nome_e_recusada_sem_deixar_resto(self):
        dados = (self._parte("arquivo", "a.csv", b"0700123-45.2024.8.02.0001;senha123")
                 + self._parte("arquivo", "b.csv", b"x") + b"--XyZ--\r\n")
        with self.assertRaises(multipart.EnvioInvalido) as ctx:
            self.ler(dados)
        self.assertIn("repetido", str(ctx.exception))
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_segunda_parte_cortada_tambem_nao_deixa_resto(self):
        dados = (self._parte("arquivo", "a.csv", b"0700123-45.2024.8.02.0001;senha123")
                 + self._parte("outro", "b.csv", b"x")[:-10])
        with self.assertRaises(multipart.EnvioInvalido):
            self.ler(dados)
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_campos_de_arquivo_diferentes_continuam_aceitos(self):
        dados = (self._parte("arquivo", "a.csv", b"um") + self._parte("anexo", "b.csv", b"dois")
                 + b"--XyZ--\r\n")
        with self.ler(dados) as envio:
            self.assertEqual(envio.arquivo("arquivo").caminho.read_bytes(), b"um")
            self.assertEqual(envio.arquivo("anexo").caminho.read_bytes(), b"dois")
        self.assertEqual(list(self.pasta.iterdir()), [])


# ======================================================= token (achado 58)
class TestTokenForaDoRegistro(unittest.TestCase):
    TOKEN = "SEGREDO-abc123XYZ"

    def setUp(self):
        roteador = rede.Roteador()

        def quebra(_tratador):
            raise RuntimeError("falha no meio do fluxo")

        roteador.adicionar("GET", "/api/eventos", lambda p: rede.Fluxo(quebra))

        def pagina():
            raise RuntimeError("falha ao montar a página")

        self.servidor = rede.ServidorLocal(object(), roteador, self.TOKEN,
                                           pagina_inicial=pagina).iniciar()
        self.addCleanup(self.servidor.parar)

    def pedir(self, caminho: str) -> None:
        conexao = http.client.HTTPConnection("127.0.0.1", self.servidor.porta, timeout=10)
        try:
            conexao.request("GET", caminho)
            try:
                conexao.getresponse().read()
            except (http.client.HTTPException, OSError):
                pass
        finally:
            conexao.close()

    def test_falha_inesperada_nao_registra_o_token(self):
        for caminho in (f"/api/eventos?t={self.TOKEN}", f"/?t={self.TOKEN}&x=1"):
            with self.subTest(caminho=caminho):
                with self.assertLogs("servidor.http", level="DEBUG") as registro:
                    self.pedir(caminho)
                    time.sleep(0.1)
                texto = "\n".join(registro.output)
                self.assertIn("falha ao atender", texto)
                self.assertIn("t=***", texto)
                self.assertNotIn(self.TOKEN, texto)

    def test_log_error_e_log_message_mascaram(self):
        registros: list[str] = []

        class Coletor(logging.Handler):
            def emit(self, record):
                registros.append(record.getMessage())

        alvo = logging.getLogger("servidor.http")
        coletor = Coletor(logging.DEBUG)
        nivel = alvo.level
        alvo.addHandler(coletor)
        alvo.setLevel(logging.DEBUG)
        try:
            falso = mock.Mock(address_string=lambda: "127.0.0.1")
            rede.Tratador.log_error(falso, "code %d, message %s", 400,
                                    f"Bad request version ('GET /?t={self.TOKEN} HTTP')")
            rede.Tratador.log_message(falso, '"%s" %s %s', f"GET /?t={self.TOKEN} HTTP/1.1",
                                      "200", "-")
        finally:
            alvo.removeHandler(coletor)
            alvo.setLevel(nivel)
        self.assertEqual(len(registros), 2)
        self.assertFalse(any(self.TOKEN in r for r in registros), registros)
        self.assertTrue(all("t=***" in r for r in registros), registros)

    def test_mascarar_token(self):
        self.assertEqual(rede.mascarar_token(f"/api/eventos?t={self.TOKEN}&a=1"),
                         "/api/eventos?t=***&a=1")
        self.assertEqual(rede.mascarar_token("/x?a=1&t=abc"), "/x?a=1&t=***")
        self.assertEqual(rede.mascarar_token("/sem/token"), "/sem/token")


if __name__ == "__main__":
    unittest.main()
