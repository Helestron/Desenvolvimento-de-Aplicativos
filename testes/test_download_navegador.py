"""O navegador automatizado, sem abrir navegador nenhum.

Inclui, portados da base (testes/test_navegador.py), os testes de
"o que a tela do e-SAJ diz": o portal escreve com acento, e comparar com
o texto cru fazia o programa perder a mensagem mais importante que ele
recebe - a de senha recusada.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
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
    def test_auto_prefere_chrome_depois_edge_e_o_chromium_so_se_ja_existir(self):
        self.assertEqual(navegador.escolher_canais("auto", chrome="c", edge="e", chromium=""),
                         ["chrome", "msedge"])
        self.assertEqual(navegador.escolher_canais("auto", chrome="", edge="e", chromium=""),
                         ["msedge"])
        # o Chromium do Playwright só entra, por último, se já estiver aqui
        self.assertEqual(navegador.escolher_canais("auto", chrome="c", edge="e", chromium="/pw"),
                         ["chrome", "msedge", None])
        self.assertEqual(navegador.escolher_canais("auto", chrome="", edge="", chromium="/pw"),
                         [None])

    def test_sem_chrome_nem_edge_explica(self):
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            navegador.escolher_canais("auto", chrome="", edge="", chromium="")
        texto = str(caso.exception)
        self.assertIn("nem o Google Chrome nem o Microsoft Edge", texto)
        self.assertIn("O Edge vem com o Windows 10 e 11", texto)

    def test_preferencias_explicitas(self):
        self.assertEqual(navegador.escolher_canais("msedge", chrome="c", edge="e", chromium=""),
                         ["msedge", "chrome"])
        self.assertEqual(navegador.escolher_canais("chromium", chrome="c", edge="e",
                                                   chromium="/pw"), [None, "chrome", "msedge"])
        # pediu o Chromium, mas não há: segue com o Chrome e o Edge
        with self.assertLogs("download.navegador", "WARNING"):
            self.assertEqual(navegador.escolher_canais("chromium", chrome="c", edge="e",
                                                       chromium=""), ["chrome", "msedge"])
        # pediu Chrome, não tem: segue com o que houver, sem derrubar
        with self.assertLogs("download.navegador", "WARNING"):
            self.assertEqual(navegador.escolher_canais("chrome", chrome="", edge="e",
                                                       chromium=""), ["msedge"])
        # valor estranho no config.ini vale como "auto"
        self.assertEqual(navegador.escolher_canais("firefox", chrome="c", edge="", chromium=""),
                         ["chrome"])

    def test_chromium_de_reserva_so_o_que_ja_existe(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": tmp}), \
                    mock.patch("pathlib.Path.home", return_value=Path(tmp) / "casa"), \
                    mock.patch.dict(os.environ, {"LOCALAPPDATA": str(Path(tmp) / "local")}):
                self.assertEqual(navegador.chromium_reserva(), "")
                (Path(tmp) / "chromium-1194").mkdir()
                self.assertEqual(navegador.chromium_reserva(), str(Path(tmp) / "chromium-1194"))

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
    OUTRA = "nngceckbapebfimnlniiiahkandclblb"      # outra extensão qualquer
    CREDENCIAIS = ("Login Data", "Login Data For Account", "Web Data", "Account Web Data",
                   "Cookies", "History", "Bookmarks", "Top Sites", "Shortcuts", "Favicons",
                   "Visited Links", "Extension Cookies", "Affiliation Database")

    def _prefs(self, nome):
        ext = navegador.EXT_WEB_SIGNER
        return {"account_info": [{"email": "juiz@exemplo.com"}],
                "profile": {"name": nome, "content_settings": {"exceptions": {
                    "site_engagement": {"https://banco.com.br:443,*": {}}}}},
                "download": {"default_directory": "C:\\Users\\juiz\\Downloads"},
                "extensions": {"settings": {ext: {"location": 1, "from_webstore": True},
                                            self.OUTRA: {"location": 1}},
                               "install_signature": {"ids": [ext, self.OUTRA]}},
                "protection": {"macs": {"extensions": {"settings": {ext: "MAC-WS",
                                                                    self.OUTRA: "MAC-OUTRA"}},
                                        "homepage": "MAC-HOME"},
                               "super_mac": "SUPER"},
                "homepage": "https://webmail.exemplo.com"}

    def _chrome(self, com_extensao=("Profile 2",), ultimo="Profile 2"):
        user = self.tmp / "User Data"
        ext = navegador.EXT_WEB_SIGNER
        for nome in ("Default", "Profile 2"):
            pasta = user / nome
            (pasta / "Cache").mkdir(parents=True)
            (pasta / "Cache" / "lixo").write_text("x")
            (pasta / "Sessions").mkdir()
            for arq in self.CREDENCIAIS:
                (pasta / arq).write_text("SEGREDO")
            (pasta / "Network").mkdir()
            (pasta / "Network" / "Cookies").write_text("SEGREDO")
            (pasta / "Local Storage" / "leveldb").mkdir(parents=True)
            (pasta / "Extensions" / self.OUTRA / "9.9").mkdir(parents=True)
            (pasta / "Local Extension Settings" / self.OUTRA).mkdir(parents=True)
            (pasta / "Local Extension Settings" / self.OUTRA / "000003.log").write_text("cofre")
            prefs = self._prefs(nome)
            if nome in com_extensao:
                (pasta / "Extensions" / ext / "1.0").mkdir(parents=True)
                (pasta / "Extensions" / ext / "1.0" / "manifest.json").write_text("{}")
                (pasta / "Local Extension Settings" / ext).mkdir(parents=True)
                (pasta / "Local Extension Settings" / ext / "000003.log").write_text("dominios")
                (pasta / "Local Extension Settings" / ext / "LOCK").write_text("")
            else:
                del prefs["extensions"]["settings"][ext]
            (pasta / "Secure Preferences").write_text(json.dumps(prefs))
            (pasta / "Preferences").write_text(json.dumps({"profile": {"name": nome},
                                                           "account_info": prefs["account_info"]}))
        (user / "Local State").write_text(json.dumps({"profile": {"last_used": ultimo},
                                                      "os_crypt": {"encrypted_key": "DPAPI"}}))
        return user

    def _arquivos(self, destino):
        return sorted(str(p.relative_to(destino)).replace(os.sep, "/")
                      for p in destino.rglob("*") if p.is_file())

    def test_copia_so_o_web_signer(self):
        user = self._chrome()
        destino = self.tmp / "perfis" / "esaj-TJAL-certificado"
        navegador.preparar_perfil_certificado(destino, user)
        ext = navegador.EXT_WEB_SIGNER
        self.assertTrue(navegador.tem_web_signer(destino))
        self.assertEqual(self._arquivos(destino), sorted([
            f"Default/Extensions/{ext}/1.0/manifest.json",
            f"Default/Local Extension Settings/{ext}/000003.log",
            "Default/Secure Preferences",
            navegador.MARCA_PERFIL_CERT]))
        self.assertFalse((destino / "Local State").exists(), "a chave do Chrome não vem")

    def test_preferencias_reduzidas_ao_registro_da_extensao(self):
        user = self._chrome()
        destino = self.tmp / "cert"
        navegador.preparar_perfil_certificado(destino, user)
        ext = navegador.EXT_WEB_SIGNER
        prefs = json.loads((destino / "Default" / "Secure Preferences").read_text())
        self.assertEqual(prefs, {
            "extensions": {"settings": {ext: {"location": 1, "from_webstore": True}},
                           "install_signature": {"ids": [ext, self.OUTRA]}},
            "protection": {"macs": {"extensions": {"settings": {ext: "MAC-WS"}}}}})
        texto = (destino / "Default" / "Secure Preferences").read_text()
        for vazamento in ("juiz@exemplo.com", "banco.com.br", "webmail", "Downloads",
                          "MAC-OUTRA", "SUPER"):
            self.assertNotIn(vazamento, texto)

    def test_copia_uma_vez_so(self):
        user = self._chrome()
        destino = self.tmp / "cert"
        navegador.preparar_perfil_certificado(destino, user)
        (destino / "Default" / "Secure Preferences").write_text("mexido pelo Chrome")
        navegador.preparar_perfil_certificado(destino, user)
        self.assertEqual((destino / "Default" / "Secure Preferences").read_text(),
                         "mexido pelo Chrome")

    def test_web_signer_atualizado_no_chrome_atualiza_a_copia(self):
        """O navegador do programa não atualiza extensões sozinho
        (--disable-background-networking do Playwright)."""
        user = self._chrome()
        destino = self.tmp / "cert"
        navegador.preparar_perfil_certificado(destino, user)
        ext = user / "Profile 2" / "Extensions" / navegador.EXT_WEB_SIGNER
        (ext / "1.0").rename(ext / "1.10.2_0")
        navegador.preparar_perfil_certificado(destino, user)
        self.assertEqual(navegador.versao_do_web_signer(destino / "Default"), (1, 10, 2, 0))
        self.assertEqual(len(list((destino / "Default" / "Extensions" /
                                   navegador.EXT_WEB_SIGNER).iterdir())), 1)

    def test_sem_web_signer_no_chrome_o_perfil_abre_limpo(self):
        user = self._chrome(com_extensao=(), ultimo="Profile 2")
        destino = self.tmp / "cert"
        navegador.preparar_perfil_certificado(destino, user)
        self.assertFalse(navegador.tem_web_signer(destino))
        self.assertEqual(self._arquivos(destino), [navegador.MARCA_PERFIL_CERT])

    def test_copia_antiga_do_perfil_inteiro_e_apagada(self):
        """Até a 1.0.1 vinha o perfil inteiro, com senhas, cookies e Local State."""
        user = self._chrome()
        destino = self.tmp / "perfis" / "esaj-TJAL-certificado"
        (destino / "Default" / "Extensions" / navegador.EXT_WEB_SIGNER / "0.9").mkdir(parents=True)
        for arq in self.CREDENCIAIS:
            (destino / "Default" / arq).write_text("SEGREDO")
        (destino / "Local State").write_text("{}")
        self.assertTrue(navegador.copia_antiga(destino))
        navegador.preparar_perfil_certificado(destino, user)
        self.assertFalse(navegador.copia_antiga(destino))
        self.assertNotIn("Default/Login Data", self._arquivos(destino))
        self.assertFalse((destino / "Local State").exists())
        self.assertTrue(navegador.tem_web_signer(destino))
        self.assertEqual([p.name for p in destino.parent.iterdir()], [destino.name],
                         "nada de pasta de lixo sobrando")

    def test_copia_antiga_aberta_fica_para_depois(self):
        destino = self.tmp / "perfis" / "esaj-TJAL-certificado"
        (destino / "Default").mkdir(parents=True)
        (destino / "Default" / "Login Data").write_text("SEGREDO")
        with mock.patch.object(navegador, "perfil_aberto", return_value=True):
            self.assertFalse(navegador.limpar_copia_antiga(destino))
        self.assertTrue((destino / "Default" / "Login Data").exists())
        self.assertTrue(navegador.limpar_copia_antiga(destino))
        self.assertFalse(destino.exists())

    def test_copia_antiga_que_nao_sai_nao_e_aberta(self):
        """Sem Chrome nenhum aberto, o Windows recusa renomear a pasta com um
        arquivo preso (antivírus, backup, Explorador): o navegador do programa
        abria em cima da cópia antiga, com as senhas, os cookies e o Local
        State do Chrome do usuário."""
        destino = self.tmp / "perfis" / "esaj-TJAL-certificado"
        (destino / "Default").mkdir(parents=True)
        (destino / "Default" / "Login Data").write_text("SEGREDO")
        (destino / "Local State").write_text("{}")
        lancados = []
        chromium = mock.Mock()
        chromium.launch_persistent_context.side_effect = (
            lambda **k: lancados.append(k.get("user_data_dir")))
        pw = mock.Mock(chromium=chromium)
        pw.start.return_value = pw
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = lambda: pw
        recusa = PermissionError(13, "o arquivo está sendo usado por outro processo")
        nav = Navegador(self.tmp / "perfis" / "esaj-TJAL", certificado=True,
                        pasta_downloads=self.tmp / "dl")
        with mock.patch.dict(sys.modules, {"playwright.sync_api": sync_api}), \
                mock.patch.object(navegador, "escolher_canais", return_value=["chrome"]), \
                mock.patch.object(navegador, "perfil_aberto", return_value=False), \
                mock.patch.object(navegador, "USER_DATA_CHROME", self.tmp / "sem-chrome"), \
                mock.patch.object(Path, "rename", side_effect=recusa), \
                self.assertLogs("download.navegador", "WARNING") as registro:
            with self.assertRaises(modelos.NavegadorOcupado) as caso:
                nav.abrir()
        self.assertEqual(lancados, [], "o Chrome do programa não abre sobre a cópia antiga")
        self.assertIn("não pôde ser apagada", str(caso.exception))
        self.assertTrue((destino / "Default" / "Login Data").exists(), "nada mudou")
        self.assertNotIn("quando o navegador do programa fechar", "".join(registro.output))
        # solto o arquivo, a cópia antiga sai e o perfil abre só com o Web Signer
        navegador.preparar_perfil_certificado(destino, self.tmp / "sem-chrome")
        self.assertFalse(navegador.copia_antiga(destino))
        self.assertEqual(self._arquivos(destino), [navegador.MARCA_PERFIL_CERT])

    def test_limpeza_na_abertura(self):
        perfis = self.tmp / "perfis"
        antiga = perfis / "eproc-TJSC-certificado" / "Default"
        antiga.mkdir(parents=True)
        (antiga / "Login Data").write_text("SEGREDO")
        (perfis / "esaj-TJAL-certificado.apagar-1-2").mkdir()
        sessao = perfis / "esaj-TJAL" / "sessao.json"
        sessao.parent.mkdir()
        sessao.write_text(json.dumps({"cookies": [
            {"name": "SID", "value": "g", "domain": ".google.com", "path": "/"},
            {"name": "JSESSIONID", "value": "j", "domain": "www2.tjal.jus.br", "path": "/"}],
            "origins": [{"origin": "https://www2.tjal.jus.br", "localStorage": []}]}))
        hora = time.time() - 3600
        os.utime(sessao, (hora, hora))
        self.assertEqual(navegador.limpar_perfis_antigos(perfis), 3)
        self.assertEqual(sorted(p.name for p in perfis.iterdir()), ["esaj-TJAL"])
        dados = json.loads(sessao.read_text())
        self.assertEqual(dados["versao"], navegador.VERSAO_SESSAO)
        self.assertAlmostEqual(dados["gravado_em"], hora, delta=2, msg="a validade não renova")
        self.assertNotIn("google", sessao.read_text())
        self.assertNotIn("JSESSIONID", sessao.read_text(), "cifrada (b64 fora do Windows)")
        self.assertEqual([c["name"] for c in navegador.ler_sessao(sessao)], ["JSESSIONID"])
        self.assertEqual(navegador.limpar_perfis_antigos(perfis), 0, "uma vez só")

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
        self.limpos = []
        self.estado = {"cookies": [{"name": "JSESSIONID", "value": "abc",
                                    "domain": "esaj.tjal.jus.br", "path": "/"},
                                   {"name": "SID", "value": "conta-google",
                                    "domain": ".google.com", "path": "/"}],
                       "origins": [{"origin": "https://esaj.tjal.jus.br",
                                    "localStorage": [{"name": "k", "value": "v"}]}]}

    def clear_cookies(self, domain=None):
        self.limpos.append(domain)

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

    def test_sessao_so_dos_portais_cifrada_e_so_do_dono(self):
        n = self.nav()
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._guardar_sessao()
        texto = n.arquivo_sessao.read_text()
        for vazamento in ("conta-google", "google.com", "JSESSIONID", "localStorage"):
            self.assertNotIn(vazamento, texto)
        self.assertEqual([c["name"] for c in navegador.ler_sessao(n.arquivo_sessao)],
                         ["JSESSIONID"])
        if os.name == "posix":
            self.assertEqual(os.stat(n.arquivo_sessao).st_mode & 0o777, 0o600)

    def test_cookie_do_portal(self):
        self.assertTrue(navegador.cookie_do_portal({"domain": ".tjal.jus.br"}))
        self.assertTrue(navegador.cookie_do_portal({"domain": "eproc1g.tjsc.jus.br"}))
        self.assertFalse(navegador.cookie_do_portal({"domain": ".google.com"}))
        self.assertFalse(navegador.cookie_do_portal({"domain": "jus.br.golpe.com"}))
        self.assertFalse(navegador.cookie_do_portal({"domain": ""}))
        # endereço corrigido pelo usuário, fora de .jus.br
        self.assertTrue(navegador.cookie_do_portal({"domain": "esaj.exemplo.org"},
                                                   ("esaj.exemplo.org",)))
        self.assertTrue(navegador.cookie_do_portal({"domain": ".exemplo.org"},
                                                   ("esaj.exemplo.org",)))

    def test_cookies_alheios_saem_do_navegador_ao_abrir(self):
        n = self.nav()
        n._contexto = ContextoFalso([])
        n._contexto.cookies = lambda: n._contexto.estado["cookies"]
        n._higienizar_cookies()
        self.assertEqual(n._contexto.limpos, [".google.com"])

    def test_esquecer_portal_apaga_sessao_e_perfis(self):
        perfis = self.tmp / "perfis"
        n = self.nav()
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._guardar_sessao()
        (perfis / "esaj-TJAL" / "chrome" / "Default").mkdir(parents=True)
        (perfis / "esaj-TJAL-certificado" / "Default").mkdir(parents=True)
        self.assertTrue(navegador.esquecer_portal("esaj:tjal", perfis))
        # fica só a marca do instante, para o navegador de outro processo
        self.assertEqual([p.name for p in perfis.iterdir()], ["esaj-TJAL.esquecido"])
        float((perfis / "esaj-TJAL.esquecido").read_text())
        with self.assertRaises(ValueError):
            navegador.esquecer_portal("esaj:../../x", perfis)

    def test_navegador_aberto_antes_do_esquecer_nao_regrava(self):
        """'Apagar acesso' com um download em andamento: o fechar() desse
        navegador regravava a sessão (da pessoa cujo acesso foi apagado)."""
        perfis = self.tmp / "perfis"
        n = self.nav()
        n._aberto_em = time.time() - 5
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._contexto.close = lambda: None
        navegador.esquecer_portal("esaj:TJAL", perfis)
        n.fechar()
        self.assertFalse(n.arquivo_sessao.exists())

    def test_esquecer_vale_para_o_navegador_de_outro_processo(self):
        """'Apagar acesso' na janela com o 'baixar' da linha de comando (outro
        processo) usando o navegador do portal: a marca ficava só na memória
        da janela, e o fechar() do outro processo regravava a sessão do
        usuário anterior e deixava o perfil."""
        perfis = self.tmp / "perfis"
        n = self.nav()
        n._aberto_em = time.time() - 5
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._contexto.close = lambda: None
        n._guardar_sessao()
        (n.perfil / "chrome" / "Default").mkdir(parents=True)
        with mock.patch.object(navegador, "perfil_aberto", return_value=True):
            self.assertFalse(navegador.esquecer_portal("esaj:TJAL", perfis))
        self.assertFalse(n.arquivo_sessao.exists())
        nunca_abriu = self.nav()
        nunca_abriu.fechar()
        self.assertTrue(n.perfil.exists(), "um navegador que nem abriu não apaga nada")
        # o outro processo não tem a marca na memória: só a do disco
        with mock.patch.dict(navegador._ESQUECIDOS, {}, clear=True):
            n.fechar()
        self.assertFalse(n.arquivo_sessao.exists(), "a sessão do usuário anterior não volta")
        self.assertFalse(n.perfil_base.exists(), "o perfil do portal sai ao fechar")
        # o navegador aberto depois do 'Apagar acesso' guarda a sessão normalmente
        novo = self.nav()
        novo._aberto_em = time.time() + 1
        novo._contexto = ContextoFalso([PaginaFalsa()])
        novo._contexto.close = lambda: None
        with mock.patch.dict(navegador._ESQUECIDOS, {}, clear=True):
            novo.fechar()
        self.assertEqual([c["name"] for c in navegador.ler_sessao(novo.arquivo_sessao)],
                         ["JSESSIONID"])

    def test_marca_do_esquecer_vencida_sai_na_abertura(self):
        perfis = self.tmp / "perfis"
        perfis.mkdir()
        navegador.esquecer_portal("eproc:TJSC", perfis)
        recente = perfis / "eproc-TJSC.esquecido"
        self.assertTrue(recente.is_file())
        velha = perfis / "esaj-TJAL.esquecido"
        velha.write_text(repr(time.time() - navegador.MARCA_ESQUECIDO_VALIDA_S - 60))
        navegador.limpar_perfis_antigos(perfis)
        self.assertEqual(sorted(p.name for p in perfis.iterdir()), ["eproc-TJSC.esquecido"])

    def test_sessao_velha_nao_volta(self):
        n = self.nav()
        n._contexto = ContextoFalso([PaginaFalsa()])
        n._guardar_sessao()
        dados = json.loads(n.arquivo_sessao.read_text())
        dados["gravado_em"] = time.time() - 13 * 3600
        n.arquivo_sessao.write_text(json.dumps(dados))
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

    def test_tela_de_processo_sigiloso_nao_vai_para_os_registros(self):
        """Logs\\diagnostico é o que o manual manda enviar ao suporte: a tela de
        processo em segredo de justiça (com os nomes das partes) não é guardada,
        e o registro diz por quê."""
        n = self.nav()
        pagina = PaginaFalsa(html="<html>AUTOR: MARIA DA SILVA - Segredo de Justiça</html>")
        n._pagina = pagina                     # a aba aberta no portal
        n.sigiloso_em_curso = True
        with self.assertLogs("download.navegador", "WARNING") as registro:
            self.assertIsNone(n.diagnosticar("eproc-falha-x", pagina))
            self.assertIsNone(navegador.diagnosticar_processo(n, "eproc-falha-x", False))
        self.assertFalse((self.tmp / "diag").exists() and list((self.tmp / "diag").iterdir()))
        self.assertEqual(pagina.capturas, [])
        self.assertIn("segredo de justiça", registro.output[0])
        self.assertNotIn("MARIA", "".join(registro.output))
        n.sigiloso_em_curso = False
        with self.assertLogs("download.navegador", "WARNING"):
            self.assertIsNone(navegador.diagnosticar_processo(n, "eproc-falha-x", True))
        self.assertEqual(pagina.capturas, [])
        self.assertIsNotNone(navegador.diagnosticar_processo(n, "eproc-falha-y", False))
        self.assertEqual(len(pagina.capturas), 1)

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
        self.assertIn("Instale o Helestron de novo com o Helestron-Setup", str(caso.exception))


if __name__ == "__main__":
    unittest.main()
