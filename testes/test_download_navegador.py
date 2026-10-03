"""O navegador automatizado, sem abrir navegador nenhum.

Inclui, portados da base (testes/test_navegador.py), os testes de
"o que a tela do e-SAJ diz": o portal escreve com acento, e comparar com
o texto cru fazia o programa perder a mensagem mais importante que ele
recebe - a de senha recusada.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock

from helestron.download import modelos, navegador
from helestron.download.navegador import Navegador

from testes import apoio_download as apoio


class TestRecusouCredenciais(unittest.TestCase):
    def test_a_mensagem_real_do_portal(self):
        self.assertTrue(navegador.recusou_credenciais("Usuário ou senha inválidos."))

    def test_a_mensagem_dentro_da_pagina_inteira(self):
        pagina = ("Portal de Serviços | E-SAJ Erro Entrar com identificação "
                  "CPF/CNPJ Certificado digital Senha Usuário ou senha "
                  "inválidos. Esqueci minha senha")
        self.assertTrue(navegador.recusou_credenciais(pagina))

    def test_variantes_que_o_portal_ja_usou(self):
        for texto in ("Usuário ou senha inválidos.", "usuario ou senha invalidos",
                      "Senha incorreta", "A senha não confere", "SENHA INVÁLIDA"):
            self.assertTrue(navegador.recusou_credenciais(texto), texto)

    def test_tela_normal_nao_e_recusa(self):
        for texto in ("Entrar com identificação CPF/CNPJ Senha Entrar",
                      "Insira o código de validação enviado para seu e-mail",
                      "Esqueci minha senha", "", None):
            self.assertFalse(navegador.recusou_credenciais(texto), repr(texto))

    def test_senha_expirada_nao_e_senha_invalida(self):
        self.assertFalse(navegador.recusou_credenciais(
            "Senha expirada. Verifique sua caixa de e-mail para cadastrar nova senha."))

    def test_a_pagina_de_login_de_verdade(self):
        """A tela de login carrega SEMPRE, oculto, o aviso de senha expirada.
        Uma guarda por 'expirad' mataria a detecção."""
        pagina = ("Portal de Serviços | E-SAJ Erro   Entrar com identificação "
                  "CPF/CNPJ Certificado digital CPF/CNPJ * : Senha * : "
                  "Usuário ou senha inválidos. Esqueci minha senha "
                  "Certificado * : Carregando certificados Usuário ou senha "
                  "inválidos. Não possui identificação? Inicie seu cadastro "
                  "Senha expirada Verifique sua caixa de e-mail para cadastrar "
                  "nova senha. Caso não tenha recebido verifique a caixa de spam")
        self.assertTrue(navegador.recusou_credenciais(pagina))

    def test_tela_de_login_limpa_com_o_bloco_escondido(self):
        pagina = ("Portal de Serviços | E-SAJ Entrar com identificação "
                  "CPF/CNPJ Certificado digital CPF/CNPJ * : Senha * : "
                  "Esqueci minha senha Certificado * : Carregando certificados "
                  "Não possui identificação? Inicie seu cadastro "
                  "Senha expirada Verifique sua caixa de e-mail para cadastrar nova senha.")
        self.assertFalse(navegador.recusou_credenciais(pagina))


class TestSemAcento(unittest.TestCase):
    def test_tira_acento_e_baixa_a_caixa(self):
        self.assertEqual(navegador.sem_acento("Usuário INVÁLIDO ç"), "usuario invalido c")

    def test_texto_vazio_ou_nulo(self):
        self.assertEqual(navegador.sem_acento(""), "")
        self.assertEqual(navegador.sem_acento(None), "")


class TestEscolhaDoNavegador(unittest.TestCase):
    def test_auto_prefere_chrome_depois_edge_depois_o_do_programa(self):
        self.assertEqual(navegador.escolher_canais("auto", chrome="c", edge="e"),
                         ["chrome", "msedge", None])
        self.assertEqual(navegador.escolher_canais("auto", chrome="", edge="e"),
                         ["msedge", None])
        self.assertEqual(navegador.escolher_canais("auto", chrome="", edge=""), [None])

    def test_preferencias_explicitas(self):
        self.assertEqual(navegador.escolher_canais("msedge", chrome="c", edge="e"),
                         ["msedge", "chrome", None])
        self.assertEqual(navegador.escolher_canais("chromium", chrome="c", edge="e"), [None])
        # pediu Chrome, não tem: segue com o que houver, sem derrubar
        self.assertEqual(navegador.escolher_canais("chrome", chrome="", edge="e"),
                         ["msedge", None])

    def test_certificado_exige_chrome(self):
        self.assertEqual(navegador.escolher_canais("auto", certificado=True, chrome="c", edge=""),
                         ["chrome"])
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            navegador.escolher_canais("auto", certificado=True, chrome="", edge="e")
        self.assertIn("Web Signer", str(caso.exception))
        self.assertIn("Entrar manualmente", str(caso.exception))

    def test_nomes(self):
        self.assertEqual(navegador.nome_do_canal("msedge"), "Microsoft Edge")
        self.assertIn("Chromium", navegador.nome_do_canal(None))


class TestMensagens(unittest.TestCase):
    def test_erros_de_rede_viram_frases(self):
        self.assertIn("sem internet", navegador.explicar_erro(
            "page.goto: net::ERR_NAME_NOT_RESOLVED at https://www2.tjal.jus.br"))
        self.assertIn("proxy", navegador.explicar_erro("net::ERR_PROXY_CONNECTION_FAILED"))
        self.assertIn("certificado de segurança", navegador.explicar_erro(
            "net::ERR_CERT_AUTHORITY_INVALID"))
        self.assertIn("demorou", navegador.explicar_erro("Timeout 60000ms exceeded."))
        self.assertEqual(navegador.explicar_erro("algo novo\nlinha 2"), "algo novo")
        self.assertEqual(navegador.explicar_erro(""), "erro desconhecido")

    def test_perfil_em_uso(self):
        self.assertTrue(navegador.perfil_em_uso(
            "Failed to create a ProcessSingleton for your profile directory"))
        self.assertFalse(navegador.perfil_em_uso("Executable doesn't exist at /x"))


class TestPerfilDoCertificado(apoio.PastaTemporaria):
    def _chrome(self, com_extensao=("Profile 2",), ultimo="Profile 2"):
        user = self.tmp / "User Data"
        for nome in ("Default", "Profile 2"):
            (user / nome / "Cache").mkdir(parents=True)
            (user / nome / "Cache" / "lixo").write_text("x")
            (user / nome / "Preferences").write_text(nome)
            (user / nome / "Sessions").mkdir()
            if nome in com_extensao:
                (user / nome / "Extensions" / navegador.EXT_WEB_SIGNER / "1.0").mkdir(parents=True)
        (user / "Local State").write_text(json.dumps({"profile": {"last_used": ultimo}}))
        return user

    def test_copia_o_perfil_que_tem_o_web_signer(self):
        user = self._chrome()
        destino = self.tmp / "perfis" / "esaj-TJAL-certificado"
        navegador.preparar_perfil_certificado(destino, user)
        self.assertTrue(navegador.tem_web_signer(destino))
        self.assertEqual((destino / "Default" / "Preferences").read_text(), "Profile 2")
        self.assertFalse((destino / "Default" / "Cache").exists(), "cache não se copia")
        self.assertFalse((destino / "Default" / "Sessions").exists(), "abas abertas não se copiam")
        self.assertTrue((destino / "Local State").exists())

    def test_copia_uma_vez_so(self):
        user = self._chrome()
        destino = self.tmp / "cert"
        navegador.preparar_perfil_certificado(destino, user)
        (destino / "Default" / "Preferences").write_text("mexido pelo programa")
        navegador.preparar_perfil_certificado(destino, user)
        self.assertEqual((destino / "Default" / "Preferences").read_text(), "mexido pelo programa")

    def test_sem_web_signer_usa_o_ultimo_perfil_usado(self):
        user = self._chrome(com_extensao=(), ultimo="Profile 2")
        destino = self.tmp / "cert"
        navegador.preparar_perfil_certificado(destino, user)
        self.assertFalse(navegador.tem_web_signer(destino))
        self.assertEqual((destino / "Default" / "Preferences").read_text(), "Profile 2")

    def test_sem_chrome_nenhum(self):
        destino = self.tmp / "cert"
        navegador.preparar_perfil_certificado(destino, self.tmp / "nao-existe")
        self.assertTrue(destino.is_dir())


class PaginaFalsa:
    def __init__(self, fechada=False, visiveis=(), html="<html>tela</html>"):
        self._fechada = fechada
        self.visiveis = set(visiveis)
        self.html = html
        self.eventos = {}
        self.capturas = []
        self.esperas = []

    def is_closed(self):
        return self._fechada

    def on(self, evento, funcao):
        self.eventos[evento] = funcao

    def content(self):
        return self.html

    def screenshot(self, path, full_page=True, timeout=0):
        self.capturas.append(path)
        with open(path, "wb") as f:
            f.write(b"png")

    def locator(self, seletor):
        return LocalizadorFalso(self, seletor)


class LocalizadorFalso:
    def __init__(self, pagina, seletor):
        self.pagina = pagina
        self.seletor = seletor

    @property
    def first(self):
        return self

    def _partes(self):
        return [s.strip().replace(":visible", "") for s in self.seletor.split(",")]

    def is_visible(self):
        return any(p in self.pagina.visiveis for p in self._partes())

    def wait_for(self, state="visible", timeout=0):
        self.pagina.esperas.append((self.seletor, timeout))
        if not self.is_visible():
            raise TimeoutError(f"Timeout {timeout}ms exceeded.")


class ContextoFalso:
    def __init__(self, paginas):
        self.pages = list(paginas)
        self.cookies = []
        self.estado = {"cookies": [{"name": "JSESSIONID", "value": "abc", "domain": "x",
                                    "path": "/"}], "origins": []}

    def new_page(self):
        p = PaginaFalsa()
        self.pages.append(p)
        return p

    def add_cookies(self, cookies):
        self.cookies += cookies

    def storage_state(self):
        return self.estado


class TestPrimeiroVisivel(unittest.TestCase):
    def test_escolhe_pela_ordem_de_preferencia(self):
        pagina = PaginaFalsa(visiveis={"#b", "#c"})
        achado = navegador.primeiro_visivel(pagina, ["#a", "#b", "#c"], espera_ms=100)
        self.assertEqual(achado.seletor, "#b:visible")

    def test_espera_uma_vez_so_e_desiste(self):
        pagina = PaginaFalsa()
        self.assertIsNone(navegador.primeiro_visivel(pagina, ["#a", "#b", "#c", "#d"], 500))
        # uma espera única pela união, e não 4 x 500 ms como na base
        self.assertEqual(len(pagina.esperas), 1)
        self.assertIn("#a:visible, #b:visible", pagina.esperas[0][0])

    def test_sem_espera(self):
        pagina = PaginaFalsa()
        self.assertIsNone(navegador.primeiro_visivel(pagina, ["#a"], espera_ms=0))
        self.assertEqual(pagina.esperas, [])

    def test_entradas_vazias(self):
        self.assertIsNone(navegador.primeiro_visivel(None, ["#a"]))
        self.assertIsNone(navegador.primeiro_visivel(PaginaFalsa(), []))


class TestNavegadorSemAbrir(apoio.PastaTemporaria):
    def nav(self, **k):
        n = Navegador(self.tmp / "perfis" / "esaj-TJAL", pasta_diagnostico=self.tmp / "diag", **k)
        return n

    def test_perfil_do_certificado_fica_ao_lado(self):
        n = self.nav(certificado=True)
        self.assertEqual(n.perfil.name, "esaj-TJAL-certificado")
        self.assertTrue(n.visivel, "PIN do token é caixa nativa: janela sempre visível")
        self.assertEqual(self.nav().perfil.name, "esaj-TJAL")

    def test_sessao_guardada_e_restaurada(self):
        n = self.nav()
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._guardar_sessao()
        arquivo = self.tmp / "perfis" / "esaj-TJAL" / "sessao.json"
        self.assertTrue(arquivo.exists())
        self.assertFalse(arquivo.with_name("sessao.json.tmp").exists())
        outro = self.nav()
        outro._contexto = ContextoFalso([])
        outro._restaurar_sessao()
        self.assertEqual(outro._contexto.cookies[0]["name"], "JSESSIONID")

    def test_sessao_velha_nao_volta(self):
        n = self.nav()
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._guardar_sessao()
        velho = time.time() - 13 * 3600
        os.utime(n.arquivo_sessao, (velho, velho))
        outro = self.nav()
        outro._contexto = ContextoFalso([])
        outro._restaurar_sessao()
        self.assertEqual(outro._contexto.cookies, [])

    def test_sessao_esquecida_nao_e_regravada_ao_fechar(self):
        """Depois de um login recusado, fechar() regravava os mesmos cookies
        e o esquecer_sessao() não valia nada."""
        n = self.nav()
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._guardar_sessao()
        self.assertTrue(n.arquivo_sessao.exists())
        n.esquecer_sessao()
        n._contexto.close = lambda: None
        n.fechar()
        self.assertFalse(n.arquivo_sessao.exists())

    def test_sessao_corrompida_nao_quebra(self):
        n = self.nav()
        n.arquivo_sessao.parent.mkdir(parents=True)
        n.arquivo_sessao.write_text("{quebrado")
        n._contexto = ContextoFalso([])
        n._restaurar_sessao()
        self.assertEqual(n._contexto.cookies, [])

    def test_abas_com_a_de_trabalho_na_frente(self):
        a, b, c = PaginaFalsa(), PaginaFalsa(), PaginaFalsa(fechada=True)
        n = self.nav()
        n._contexto = ContextoFalso([a, b, c])
        n._pagina = b
        self.assertEqual(n.abas(), [b, a])

    def test_aba_fechada_e_reaberta(self):
        n = self.nav()
        fechada = PaginaFalsa(fechada=True)
        n._contexto = ContextoFalso([fechada])
        n._pagina = fechada
        nova = n.pagina
        self.assertIsNot(nova, fechada)
        self.assertFalse(nova.is_closed())

    def test_dialogos_dispensados_em_toda_aba(self):
        pagina = PaginaFalsa()
        Navegador._preparar_aba(pagina)
        dialogo = mock.Mock(type="alert", message="Sessão expirada")
        pagina.eventos["dialog"](dialogo)
        dialogo.dismiss.assert_called_once()
        saida = mock.Mock(type="beforeunload", message="")
        pagina.eventos["dialog"](saida)
        saida.accept.assert_called_once()

    def test_diagnostico_fora_do_acervo(self):
        n = self.nav()
        pagina = PaginaFalsa(html="<html>Usuário ou senha inválidos</html>")
        caminho = n.diagnosticar("esaj login/recusado", pagina)
        self.assertEqual(caminho.parent, self.tmp / "diag")
        htmls = list((self.tmp / "diag").glob("*.html"))
        self.assertEqual(len(htmls), 1)
        self.assertIn("esaj_login_recusado", htmls[0].name)
        self.assertIn("inválidos", htmls[0].read_text(encoding="utf-8"))

    def test_diagnostico_desligado(self):
        n = self.nav(salvar_diagnostico=False)
        self.assertIsNone(n.diagnosticar("x", PaginaFalsa()))

    def test_pasta_de_diagnostico_nao_cresce_sem_fim(self):
        pasta = self.tmp / "diag"
        pasta.mkdir()
        for i in range(12):
            arq = pasta / f"{i:02d}.html"
            arq.write_text("x")
            os.utime(arq, (1000 + i, 1000 + i))
        navegador._podar(pasta, manter=5)
        self.assertEqual(sorted(p.name for p in pasta.iterdir()),
                         ["07.html", "08.html", "09.html", "10.html", "11.html"])

    def test_sem_playwright_mensagem_clara(self):
        n = self.nav(canal="chromium")
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaises(modelos.PortalIndisponivel) as caso:
                n.abrir()
        self.assertIn("INSTALAR.bat", str(caso.exception))


if __name__ == "__main__":
    unittest.main()
