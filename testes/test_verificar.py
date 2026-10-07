"""Testes da verificação da instalação (helestron/verificar.py).

Rodam em qualquer sistema: o que só existe no Windows (DPAPI, WebView2,
privacidade do microfone, a versão do Windows) tem de sair como aviso "não
se aplica" fora dele, e nunca quebrar. As sondas em processo à parte são
exercitadas com módulos de mentira que falham, derrubam o processo ou
travam - os três jeitos de uma DLL dar errado. As pastas do programa (dados
e documentos do usuário) apontam para uma pasta temporária: nada toca no
perfil de verdade.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest import mock

from helestron import verificar
from helestron.compartilhar import chatgpt, claude
from helestron.nucleo import caminhos, config
from helestron.verificar import AVISO, FALHA, OK, Item

_ISOLAMENTO: list = []


def setUpModule():
    """Dados do programa e documentos do usuário numa pasta temporária."""
    tmp = tempfile.TemporaryDirectory(prefix="helestron-verificar-")
    base = Path(tmp.name)
    _ISOLAMENTO.append(tmp)
    for nome, valor in (("LOCAL", base / "Local"), ("LOGS", base / "Local" / "Logs"),
                        ("TEMP", base / "Local" / "temp"), ("MODELOS", base / "Local" / "modelos"),
                        ("BASE_USUARIO", base / "Documentos" / "Helestron")):
        patch = mock.patch.object(caminhos, nome, valor)
        patch.start()
        _ISOLAMENTO.append(patch)


def tearDownModule():
    for item in reversed(_ISOLAMENTO):
        if hasattr(item, "stop"):
            item.stop()
        else:
            item.cleanup()
    _ISOLAMENTO.clear()


def cfg_temporaria(pasta: Path) -> config.Config:
    """Config num arquivo temporário, com o acervo, os sigilosos e a pauta dentro de `pasta`."""
    cfg = config.Config(pasta / "config.ini")
    cfg.definir("geral", "pasta_acervo", str(pasta / "Acervo"))
    cfg.definir("geral", "pasta_sigilosos", str(pasta / "Sigilosos"))
    cfg.definir("pauta", "pasta", str(pasta / "Pauta"))
    return cfg


class TestResumo(unittest.TestCase):
    def test_resultado(self):
        ok = Item("A", OK)
        aviso = Item("B", AVISO, obrigatorio=False)
        falha_opcional = Item("C", FALHA, obrigatorio=False)
        falha = Item("D", FALHA)
        self.assertEqual(verificar.resumir([ok])["resultado"], OK)
        self.assertEqual(verificar.resumir([ok, aviso])["resultado"], AVISO)
        self.assertEqual(verificar.resumir([ok, falha_opcional])["resultado"], AVISO)
        r = verificar.resumir([ok, aviso, falha_opcional, falha])
        self.assertEqual((r["resultado"], r[OK], r[AVISO], r[FALHA]), (FALHA, 1, 1, 2))
        self.assertEqual(verificar.resumir([])["resultado"], FALHA)

    def test_frase_final_em_bom_portugues(self):
        f = verificar.frase_final(verificar.resumir([Item("A", OK)]))
        self.assertIn("1 OK, nenhum aviso e nenhuma falha", f)
        self.assertIn("Tudo certo", f)
        f = verificar.frase_final(verificar.resumir([Item("A", AVISO), Item("B", AVISO), Item("C", FALHA)]))
        self.assertIn("0 OK, 2 avisos e 1 falha", f)
        self.assertIn("Helestron-Setup", f)
        self.assertNotIn("INSTALAR", f)

    def test_formatar_item(self):
        texto = verificar.formatar_item(Item("Microfone", AVISO, "Nenhum.", False,
                                             acao="Conecte um microfone de cerca de 60 MB " * 4))
        self.assertIn("AVISO", texto)
        self.assertIn("O que fazer:", texto)
        self.assertNotIn("60\n", texto.replace("\u00a0", " ").replace("60 MB", ""))
        self.assertNotIn("O que fazer", verificar.formatar_item(Item("A", OK, "certo", acao="x")))
        self.assertIn("FALHA*", verificar.formatar_item(Item("A", FALHA, obrigatorio=False)))

    def test_json(self):
        dados = verificar.para_json([Item("A", OK, "d", codigo="a"), Item("B", AVISO, obrigatorio=False)], True)
        self.assertEqual(dados["resultado"], AVISO)
        self.assertTrue(dados["completo"])
        self.assertEqual(dados["resumo"], {OK: 1, AVISO: 1, FALHA: 0})
        self.assertEqual(set(dados["itens"][0]), {"nome", "situacao", "detalhe", "obrigatorio", "codigo", "acao"})
        self.assertEqual(dados["programa"], "Helestron")
        self.assertEqual(dados["dados"], str(caminhos.LOCAL))

    def test_cabecalho_mostra_programa_e_dados(self):
        texto = verificar.cabecalho(False)
        self.assertTrue(texto.startswith("Helestron "))
        self.assertIn(f"Programa: {caminhos.INSTALACAO}", texto)
        self.assertIn(f"Dados: {caminhos.LOCAL}", texto)


class TestSistemaEJanela(unittest.TestCase):
    """Windows de 64 bits e WebView2: decididos por funções puras."""

    def test_windows_64_bits(self):
        item = verificar.avaliar_sistema("Windows", 22631, "AMD64", True)
        self.assertEqual(item.situacao, OK)
        self.assertIn("Windows 11", item.detalhe)
        self.assertIn("64 bits", item.detalhe)
        self.assertIn("Windows 10", verificar.avaliar_sistema("Windows", 19045, "AMD64", True).detalhe)

    def test_32_bits_ou_antigo_reprova(self):
        for args in (("Windows", 19045, "x86", False), ("Windows", 19045, "AMD64", False),
                     ("Windows", 9600, "AMD64", True)):
            with self.subTest(args=args):
                item = verificar.avaliar_sistema(*args)
                self.assertEqual((item.situacao, item.obrigatorio), (FALHA, True))
                self.assertIn("Windows 10 ou 11 de 64 bits", item.acao)

    def test_fora_do_windows_nao_se_aplica(self):
        item = verificar.avaliar_sistema("Linux", 0, "x86_64", True)
        self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
        self.assertIn("Não se aplica", item.detalhe)
        if sys.platform != "win32":
            self.assertEqual(verificar.checar_sistema().situacao, AVISO)

    def test_webview2_pelo_registro(self):
        self.assertIn("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", verificar.CHAVES_WEBVIEW2[0][1])
        self.assertEqual({r for r, _ in verificar.CHAVES_WEBVIEW2}, {"HKLM", "HKCU"})
        item = verificar.avaliar_webview2([None, "", "128.0.2739.42"])
        self.assertEqual(item.situacao, OK)
        self.assertIn("128.0.2739.42", item.detalhe)
        # "0.0.0.0" é o que fica no registro depois de desinstalar
        for versoes in ([], [None, None, None], ["0.0.0.0"]):
            with self.subTest(versoes=versoes):
                item = verificar.avaliar_webview2(versoes)
                self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
                self.assertIn("modo aplicativo", item.acao)
                self.assertIn("WebView2 Runtime", item.acao)

    def test_webview2_antigo_e_aviso_com_orientacao(self):
        """A pywebview 6 precisa do runtime 101.0.1210.39 ou mais recente: com
        um mais velho a janela própria não abre (o programa vai para o Edge em
        modo aplicativo) - a verificação avisa e diz como atualizar."""
        self.assertEqual(verificar.VERSAO_MINIMA_WEBVIEW2, (101, 0, 1210, 39))
        for versoes in (["100.0.1185.36"], ["86.0.622.38", None], ["101.0.1210.38"]):
            with self.subTest(versoes=versoes):
                item = verificar.avaliar_webview2(versoes)
                self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
                self.assertIn("antigo", item.detalhe)
                self.assertIn("101.0.1210.39", item.detalhe)
                self.assertIn("modo aplicativo", item.acao)
                self.assertIn("atualize", item.acao)
                self.assertIn(verificar.URL_WEBVIEW2, item.acao)
        # vale a maior instalada (a que a janela usa), e a mínima já serve
        for versoes in (["86.0.622.38", "101.0.1210.39"], ["129.0.2792.65", "100.0.1185.36"]):
            with self.subTest(versoes=versoes):
                self.assertEqual(verificar.avaliar_webview2(versoes).situacao, OK)
        # a mesma régua da janela (helestron.aplicativo.janela), se ela a tiver
        try:
            from helestron.aplicativo import janela
        except Exception:                          # pragma: no cover - janela ausente
            return
        minima = getattr(janela, "VERSAO_MINIMA_WEBVIEW2", None)
        if minima is not None:
            self.assertEqual(tuple(minima), verificar.VERSAO_MINIMA_WEBVIEW2)

    def test_webview2_fora_do_windows(self):
        if sys.platform == "win32":
            self.skipTest("só fora do Windows")
        item = verificar.checar_webview2()
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("Não se aplica", item.detalhe)


class TestPrivacidadeDoMicrofone(unittest.TestCase):
    def test_permitido(self):
        self.assertEqual(verificar.avaliar_privacidade(None, None, None).situacao, OK)
        self.assertEqual(verificar.avaliar_privacidade("Allow", "Allow", "Allow").situacao, OK)

    def test_negado_para_programas_da_area_de_trabalho(self):
        item = verificar.avaliar_privacidade("Allow", "Deny", None)
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("muda", item.detalhe)
        self.assertIn("Permitir que aplicativos da área de trabalho", item.acao)
        self.assertFalse(item.obrigatorio)

    def test_negado_em_geral_e_no_computador(self):
        self.assertIn("configurações de privacidade", verificar.avaliar_privacidade("Deny", None, None).detalhe)
        self.assertIn("todo o computador", verificar.avaliar_privacidade(None, None, "Deny").detalhe)

    def test_fora_do_windows_nao_se_aplica(self):
        if sys.platform == "win32":
            self.skipTest("só fora do Windows")
        item = verificar.checar_privacidade_microfone()
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("Não se aplica", item.detalhe)


class TestSonda(unittest.TestCase):
    """O processo à parte: erro de import, queda e trava."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        pasta = Path(self.tmp.name)
        (pasta / "queda_helestron_teste.py").write_text("import os\nos._exit(3)\n", encoding="utf-8")
        (pasta / "trava_helestron_teste.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        self.extra = [str(pasta)]

    def tearDown(self):
        self.tmp.cleanup()

    def test_ok_e_erro(self):
        r = verificar.sondar_importacoes(["json", "modulo_que_nao_existe_helestron"])
        self.assertTrue(r["json"]["ok"])
        self.assertFalse(r["modulo_que_nao_existe_helestron"]["ok"])
        self.assertIn("ModuleNotFoundError", r["modulo_que_nao_existe_helestron"]["erro"])

    def test_queda_aponta_o_culpado_e_segue(self):
        r = verificar.sondar_importacoes(["json", "queda_helestron_teste", "csv"], extra_pythonpath=self.extra)
        self.assertTrue(r["json"]["ok"])
        self.assertFalse(r["queda_helestron_teste"]["ok"])
        self.assertTrue(r["queda_helestron_teste"]["queda"])
        self.assertIn("caiu", r["queda_helestron_teste"]["erro"])
        self.assertTrue(r["csv"]["ok"], "o módulo depois da queda tem de ser tentado de novo")

    def test_trava_vira_diagnostico(self):
        r = verificar.sondar_importacoes(["trava_helestron_teste", "json"], limite_s=3,
                                         extra_pythonpath=self.extra)
        self.assertFalse(r["trava_helestron_teste"]["ok"])
        self.assertIn("travou", r["trava_helestron_teste"]["erro"])
        self.assertTrue(r["json"]["ok"])

    def test_trava_sem_novidade_nao_espera_o_limite_inteiro(self):
        """Um módulo que trava (uma caixa de erro que ninguém vê) é dado como
        travado depois de por_modulo_s, e o resto segue: a verificação do
        instalador nunca fica presa até o limite total."""
        inicio = time.monotonic()
        r = verificar.sondar_importacoes(["json", "trava_helestron_teste", "csv"], limite_s=120,
                                         extra_pythonpath=self.extra, por_modulo_s=2)
        self.assertLess(time.monotonic() - inicio, 30)
        self.assertTrue(r["json"]["ok"])
        self.assertIn("travou", r["trava_helestron_teste"]["erro"])
        self.assertTrue(r["csv"]["ok"])

    def test_prazo_total(self):
        r = verificar.sondar_importacoes(["trava_helestron_teste", "json"], limite_s=120,
                                         extra_pythonpath=self.extra, por_modulo_s=2, total_s=2.5)
        self.assertIn("travou", r["trava_helestron_teste"]["erro"])
        self.assertIn("não foi conferido", r["json"]["erro"])

    def test_rodar_vigiado(self):
        codigo, saida, _, estourou = verificar.rodar(
            [sys.executable, "-c", "import time; print('um', flush=True); time.sleep(60)"],
            60, sem_novidade_s=1.5)
        self.assertTrue(estourou)
        self.assertIsNone(codigo)
        self.assertIn("um", saida)
        codigo, saida, _, estourou = verificar.rodar(
            [sys.executable, "-c", "print('ok')"], 60, sem_novidade_s=5)
        self.assertEqual((codigo, saida.strip(), estourou), (0, "ok", False))

    def test_explicar_queda(self):
        self.assertIn("AVX", verificar.explicar_queda(0xC000001D))
        self.assertIn("DLL não encontrada", verificar.explicar_queda(-1073741515))  # 0xC0000135 com sinal
        self.assertIn("violação", verificar.explicar_queda(-11))
        self.assertIn("travou", verificar.explicar_queda(None))
        self.assertIn("0xC0001234", verificar.explicar_queda(0xC0001234))
        self.assertIn("código 5", verificar.explicar_queda(5))


class TestChecagens(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.cfg = cfg_temporaria(self.pasta)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pastas_gravaveis(self):
        item = verificar.checar_pastas(self.cfg)
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertTrue((self.pasta / "Acervo" / "Processos").is_dir())
        self.assertTrue((self.pasta / "Acervo" / "Transcricoes").is_dir())
        self.assertTrue((self.pasta / "Sigilosos").is_dir())
        self.assertEqual(list((self.pasta / "Acervo").glob(".teste-*")), [], "o arquivo de teste ficou para trás")

    @unittest.skipIf(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "permissão de pasta só se testa assim como usuário comum no POSIX")
    def test_pasta_sem_permissao(self):
        bloqueada = self.pasta / "bloqueada"
        bloqueada.mkdir()
        os.chmod(bloqueada, 0o500)
        try:
            self.cfg.definir("geral", "pasta_acervo", str(bloqueada / "Acervo"))
            item = verificar.checar_pastas(self.cfg)
        finally:
            os.chmod(bloqueada, 0o700)
        self.assertEqual(item.situacao, FALHA)
        self.assertTrue(item.obrigatorio)
        self.assertIn("Acesso controlado a pastas", item.acao)

    def test_pastas_uma_dentro_da_outra(self):
        # Acervo e sigilosos aninhados: aviso que diz o que está em jogo
        for acervo, sigilosos in ((self.pasta / "Acervo", self.pasta / "Acervo" / "Sigilosos"),
                                  (self.pasta / "Sigilosos" / "Acervo", self.pasta / "Sigilosos"),
                                  (self.pasta / "Acervo", self.pasta / "Acervo")):
            with self.subTest(acervo=acervo, sigilosos=sigilosos):
                self.cfg.definir("geral", "pasta_acervo", str(acervo))
                self.cfg.definir("geral", "pasta_sigilosos", str(sigilosos))
                item = verificar.checar_pastas(self.cfg)
                self.assertEqual((item.situacao, item.codigo), (AVISO, "pastas"))
                self.assertIn(config.conflito_de_pastas(acervo, sigilosos), item.detalhe)
                self.assertIn("o que é de segredo de justiça iria para a IA", item.detalhe)
                self.assertIn("Ajustes › Pastas", item.acao)
                self.assertIn("\u201cAlterar\u2026\u201d", item.acao)

    def test_pauta_dentro_do_acervo(self):
        # A planilha da pauta traz as partes dos processos sigilosos.
        self.cfg.definir("pauta", "pasta", str(self.pasta / "Acervo" / "Pauta"))
        item = verificar.checar_pastas(self.cfg)
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("pauta exportada", item.detalhe)

    def test_acervo_nao_pode_conter_o_programa_nem_as_senhas(self):
        acervo = self.pasta / "Acervo"
        with mock.patch.object(verificar.caminhos, "INSTALADO", True), \
                mock.patch.object(verificar.caminhos, "INSTALACAO", acervo / "Programs" / "Helestron"):
            item = verificar.checar_pastas(self.cfg)
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("contém a pasta do programa", item.detalhe)
        self.assertIn("fora da pasta do programa", item.acao)
        with mock.patch.object(verificar.caminhos, "LOCAL", acervo / "AppData" / "Helestron"):
            item = verificar.checar_pastas(self.cfg)
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("as senhas, os registros e os perfis do navegador", item.detalhe)
        with mock.patch.object(verificar.caminhos, "LOCAL", acervo):
            self.assertEqual(verificar.checar_pastas(self.cfg).situacao, AVISO)
        # Fora da instalação (repositório), a pasta "do programa" não conta
        with mock.patch.object(verificar.caminhos, "INSTALADO", False), \
                mock.patch.object(verificar.caminhos, "INSTALACAO", self.pasta):
            self.assertEqual(verificar.checar_pastas(self.cfg).situacao, OK)

    def test_acervo_no_onedrive_e_aviso(self):
        with mock.patch.dict(os.environ, {"OneDrive": str(self.pasta)}):
            item = verificar.checar_local(self.cfg)
        self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
        self.assertIn("OneDrive", item.detalhe)
        self.assertIn("Ajustes › Pastas", item.acao)
        with mock.patch.dict(os.environ, {"OneDrive": "", "OneDriveCommercial": "",
                                          "OneDriveConsumer": ""}):
            self.assertEqual(verificar.checar_local(self.cfg).situacao, OK)

    def test_modelo_presente_ou_ausente(self):
        try:
            from helestron.transcricao import modelos
        except ImportError:
            self.skipTest("módulo de modelos indisponível")

        def instalar(pasta):
            pasta.mkdir(parents=True)
            (pasta / "model.bin").write_bytes(b"\0" * 1_100_000)
            (pasta / "config.json").write_text("{}", encoding="utf-8")
            (pasta / "tokenizer.json").write_text("{}", encoding="utf-8")

        with mock.patch.object(modelos, "PASTA", self.pasta / "modelos"), \
                mock.patch.object(modelos, "PASTA_EMBUTIDA", self.pasta / "programa" / "modelos"):
            item = verificar.checar_modelo(self.cfg)
            self.assertEqual(item.situacao, AVISO)
            self.assertFalse(item.obrigatorio)
            self.assertIn("small", item.detalhe)
            self.assertIn("484 MB", item.acao)
            self.assertIn("Ajustes › Transcrição", item.acao)
            teste = verificar.checar_teste_transcricao(self.cfg)
            self.assertEqual(teste.situacao, AVISO)
            self.assertIn("Pulado", teste.detalhe)

            instalar(modelos.PASTA / "faster-whisper-small")
            item = verificar.checar_modelo(self.cfg)
            self.assertEqual(item.situacao, OK, item.detalhe)
            self.assertIn("baixado", item.detalhe)
            self.assertIn("medium", item.detalhe)   # o da revisão, ainda por baixar

            # o que vem no instalador vale primeiro, e o item diz que é ele
            instalar(modelos.PASTA_EMBUTIDA / "faster-whisper-small")
            item = verificar.checar_modelo(self.cfg)
            self.assertEqual(item.situacao, OK, item.detalhe)
            self.assertIn("embutido no programa", item.detalhe)

    def test_teste_de_transcricao_usa_o_caminho_nativo(self):
        # Regressão: a sonda carregava o modelo pelo caminho longo, com acento
        # ("C:\\Teste Área\\...", o do CI), enquanto o programa o carrega pelo
        # nome curto 8.3 (modelos.caminho_nativo): a verificação testava um
        # caminho que o programa não usa.
        longo = Path("C:/Teste \u00c1rea/runtime/modelos/whisper-small")

        class Modelos:
            instalado = staticmethod(lambda nome: True)
            pasta_do_modelo = staticmethod(lambda nome: longo)
            nome_canonico = staticmethod(lambda nome: nome)
            tamanho_mb = staticmethod(lambda nome: 484)
            caminho_nativo = staticmethod(lambda p: "C:/TESTEA~1/runtime/modelos/whisper-small")

        chamadas = []

        def rodar(args, limite_s, extra=None):
            chamadas.append(list(args))
            return 0, "ok 1.5 2.0\n", "", False

        with mock.patch.object(verificar, "_modelos", lambda: Modelos), \
                mock.patch.object(verificar, "rodar", rodar):
            item = verificar.checar_teste_transcricao(self.cfg)
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertEqual(chamadas[0][-1], "C:/TESTEA~1/runtime/modelos/whisper-small")

        # Sem nome curto (disco com 8.3 desligado), a falha sugere também uma pasta sem acento.
        Modelos.caminho_nativo = staticmethod(lambda p: str(longo))
        quebra = (1, "", "RuntimeError: Unable to open file 'model.bin'", False)
        with mock.patch.object(verificar, "_modelos", lambda: Modelos), \
                mock.patch.object(verificar, "rodar", lambda *a, **k: quebra):
            item = verificar.checar_teste_transcricao(self.cfg)
        self.assertEqual(item.situacao, FALHA)
        self.assertIn("baixe o modelo de novo em Ajustes › Transcrição", item.acao)
        self.assertIn("sem acento", item.acao)
        self.assertIn("C:\\Helestron", item.acao)
        # O modelo que veio no instalador não se apaga: reinstala-se.
        Modelos.embutido = staticmethod(lambda nome: True)
        with mock.patch.object(verificar, "_modelos", lambda: Modelos), \
                mock.patch.object(verificar, "rodar", lambda *a, **k: quebra):
            item = verificar.checar_teste_transcricao(self.cfg)
        self.assertIn("Helestron-Setup", item.acao)
        self.assertNotIn("Apague", item.acao)

    def test_cofre(self):
        item = verificar.checar_cofre()
        if sys.platform == "win32":
            self.assertEqual(item.situacao, OK, item.detalhe)
            self.assertIn("DPAPI", item.detalhe)
        else:
            self.assertEqual(item.situacao, AVISO)
            self.assertIn("Não se aplica", item.detalhe)
        self.assertFalse(item.obrigatorio)

    def test_tribunais(self):
        item = verificar.checar_tribunais()
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertRegex(item.detalhe, r"^\d+ tribunais no catálogo; \d+ com e-SAJ ou eProc\.$")

    def test_bibliotecas_faltando(self):
        falsas = verificar.BIBLIOTECAS + (("modulo_inexistente_helestron", "pacote-inexistente", "teste"),)
        with mock.patch.object(verificar, "BIBLIOTECAS", falsas):
            item = verificar.checar_bibliotecas()
        self.assertEqual(item.situacao, FALHA)
        self.assertIn("pacote-inexistente (teste)", item.detalhe)
        self.assertIn("Helestron-Setup", item.acao)

    def test_bibliotecas_so_do_windows_nao_contam_fora_dele(self):
        so_windows = (("modulo_inexistente_helestron", "pacote-do-windows", "janela", "windows"),)
        with mock.patch.object(verificar, "BIBLIOTECAS", verificar.BIBLIOTECAS[:1] + so_windows):
            item = verificar.checar_bibliotecas()
        if sys.platform == "win32":
            self.assertEqual(item.situacao, FALHA)
        else:
            self.assertEqual(item.situacao, OK, item.detalhe)

    def test_nativos_com_modulo_simples(self):
        with mock.patch.object(verificar, "NATIVOS", ("json",)):
            item = verificar.checar_nativos()
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertEqual(item.detalhe, "O componente carregou.")

    def test_sem_navegador(self):
        with mock.patch.object(verificar, "_navegadores_instalados", return_value=("", "")), \
                mock.patch.object(verificar, "_chromium_reserva", return_value=""):
            item = verificar.checar_navegador(self.cfg)
        self.assertEqual(item.nome, "Navegador dos portais")
        self.assertFalse(item.obrigatorio)     # a transcrição funciona sem ele
        if sys.platform == "win32":
            self.assertEqual(item.situacao, FALHA)
            self.assertIn("Microsoft Edge vem com o Windows", item.acao)
        else:
            self.assertEqual(item.situacao, AVISO)

    def test_navegador_encontrado(self):
        with mock.patch.object(verificar, "_navegadores_instalados", return_value=("", "C:/edge/msedge.exe")), \
                mock.patch.object(verificar, "_chromium_reserva", return_value="/pw/chromium-1"):
            item = verificar.checar_navegador(self.cfg)
        self.assertEqual(item.situacao, OK)
        self.assertEqual(item.detalhe, "Disponível: Microsoft Edge.")

    def test_so_o_chromium_de_reserva(self):
        with mock.patch.object(verificar, "_navegadores_instalados", return_value=("", "")), \
                mock.patch.object(verificar, "_chromium_reserva", return_value="/pw/chromium-1"):
            item = verificar.checar_navegador(self.cfg)
            canais = verificar._canais(self.cfg)
        self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
        self.assertIn("Chromium do Playwright", item.detalhe)
        self.assertEqual(canais, ["chromium"])

    def test_falantes(self):
        with mock.patch.object(verificar, "_falantes_situacao",
                               return_value=(False, "incompleta (faltam os modelos de voz)")):
            item = verificar.checar_falantes()
        self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
        self.assertTrue(item.detalhe.startswith("Incompleta (faltam os modelos de voz):"), item.detalhe)
        # Com a biblioteca (que vem no instalador) e sem os modelos de voz
        # (construção --sem-falantes): a tela de Ajustes tem o botão.
        with mock.patch.object(verificar, "_falantes_situacao",
                               return_value=(False, "incompleta (faltam os modelos de voz)")), \
                mock.patch.object(verificar, "_presente", return_value=True):
            item = verificar.checar_falantes()
        self.assertIn("Ajustes › Transcrição", item.acao)
        self.assertIn("“Baixar os modelos de voz”", item.acao)
        # Sem a biblioteca: só reinstalando.
        with mock.patch.object(verificar, "_falantes_situacao",
                               return_value=(False, "indisponível")), \
                mock.patch.object(verificar, "_presente", return_value=False):
            item = verificar.checar_falantes()
        self.assertIn("vem no instalador", item.acao)
        self.assertIn("Helestron-Setup", item.acao)
        with mock.patch.object(verificar, "_falantes_situacao", return_value=(True, "instalada")):
            self.assertEqual(verificar.checar_falantes().situacao, OK)

    def test_componente_embutido_que_sumiu_e_falha(self):
        """O manifesto.json diz o que a construção embutiu: o modelo ou os
        modelos de voz que vieram e sumiram da pasta do programa são defeito
        da instalação (reinstalar), não 'baixar no primeiro uso'."""
        programa = self.pasta / "programa"
        programa.mkdir()
        (programa / "manifesto.json").write_text(json.dumps({"componentes": {
            "modelo_transcricao": "faster-whisper-small", "falantes": True}}), encoding="utf-8")
        with mock.patch.object(verificar.caminhos, "INSTALADO", True), \
                mock.patch.object(verificar.caminhos, "INSTALACAO", programa), \
                mock.patch.object(verificar, "_modelo_instalado",
                                  return_value=(False, self.pasta / "x", False)), \
                mock.patch.object(verificar, "_falantes_situacao",
                                  return_value=(False, "incompleta (faltam os modelos de voz)")):
            modelo = verificar.checar_modelo(self.cfg)
            falantes = verificar.checar_falantes()
        self.assertEqual((modelo.situacao, modelo.codigo), (FALHA, "modelo"))
        self.assertIn("veio com o programa", modelo.detalhe)
        self.assertIn("Helestron-Setup", modelo.acao)
        self.assertEqual((falantes.situacao, falantes.codigo), (FALHA, "falantes"))
        self.assertIn("Helestron-Setup", falantes.acao)
        # construção sem eles (componentes vazios): continua aviso
        (programa / "manifesto.json").write_text(json.dumps({"componentes": {
            "modelo_transcricao": "", "falantes": False}}), encoding="utf-8")
        with mock.patch.object(verificar.caminhos, "INSTALADO", True), \
                mock.patch.object(verificar.caminhos, "INSTALACAO", programa), \
                mock.patch.object(verificar, "_modelo_instalado",
                                  return_value=(False, self.pasta / "x", False)), \
                mock.patch.object(verificar, "_falantes_situacao",
                                  return_value=(False, "incompleta (faltam os modelos de voz)")):
            self.assertEqual(verificar.checar_modelo(self.cfg).situacao, AVISO)
            self.assertEqual(verificar.checar_falantes().situacao, AVISO)

    def test_regras_da_pauta(self):
        self.assertEqual(verificar.checar_regras_pauta().situacao, OK)
        from helestron.pauta import regras

        estragadas = regras.Regras({}, "o arquivo pauta.json tem erro de formatação na linha 3, coluna 1")
        with mock.patch.object(regras, "carregar", return_value=estragadas):
            item = verificar.checar_regras_pauta()
        self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
        self.assertTrue(item.detalhe.startswith("O arquivo pauta.json tem erro"), item.detalhe)
        self.assertIn("pauta.json", item.acao)

    def test_checagem_que_quebra_vira_item(self):
        def quebra():
            raise RuntimeError("inesperado")

        with self.assertLogs("verificar", level="ERROR"):
            item = verificar._protegido("Teste", quebra)
        self.assertEqual((item.nome, item.situacao, item.obrigatorio), ("Teste", FALHA, False))
        self.assertIn("RuntimeError: inesperado", item.detalhe)


_SEM_ONEDRIVE = {"OneDrive": "", "OneDriveCommercial": "", "OneDriveConsumer": ""}


class TestSigilososForaDaNuvem(unittest.TestCase):
    """A pasta dos sigilosos e a da pauta exportada fora da nuvem: dentro do
    OneDrive ou do Google Drive, o que é de segredo de justiça sai do
    computador; com a pasta da nuvem do espelho contendo-as, idem."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        self.cfg = cfg_temporaria(self.pasta)
        detectar = mock.patch("helestron.compartilhar.nuvem.detectar", return_value={})
        self.detectar = detectar.start()
        self.addCleanup(detectar.stop)

    def local(self, ambiente: dict | None = None) -> Item:
        with mock.patch.dict(os.environ, dict(_SEM_ONEDRIVE, **(ambiente or {}))):
            return verificar.checar_local(self.cfg)

    def test_tudo_fora_da_nuvem(self):
        item = self.local()
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertIn("sigilosos e pauta fora da nuvem", item.detalhe)

    def test_sigilosos_no_onedrive(self):
        od = self.pasta / "OD"
        self.cfg.definir("geral", "pasta_sigilosos", str(od / "Sigilosos"))
        item = self.local({"OneDrive": str(od)})
        self.assertEqual((item.situacao, item.obrigatorio, item.codigo), (AVISO, False, "local"))
        self.assertIn("a pasta dos processos em segredo de justiça", item.detalhe)
        self.assertIn("está dentro do OneDrive", item.detalhe)
        self.assertNotIn("pauta exportada", item.detalhe)      # a pauta ficou fora
        self.assertIn("escolha para os sigilosos uma pasta fora do OneDrive e do Google Drive",
                      item.acao)
        self.assertIn("Ajustes › Pastas", item.acao)
        # o mais grave primeiro: o segredo de justiça saindo do computador
        self.assertTrue(item.detalhe.startswith("Atenção: a pasta dos processos em segredo"))

    def test_pauta_no_google_drive_detectado(self):
        gd = self.pasta / "GD"
        self.detectar.return_value = {"Google Drive": gd}
        self.cfg.definir("pauta", "pasta", str(gd / "Pauta"))
        item = self.local()
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("a pasta da pauta exportada", item.detalhe)
        self.assertIn("está dentro do Google Drive", item.detalhe)
        self.assertIn("sai do computador e fica ao alcance", item.detalhe)
        self.assertIn("para a pauta", item.acao)

    def test_google_drive_pelo_nome_da_pasta(self):
        self.cfg.definir("geral", "pasta_sigilosos", str(self.pasta / "Google Drive" / "Sig"))
        self.assertEqual(verificar.nuvem_da_pasta(self.cfg.pasta_sigilosos, []), "Google Drive")
        self.assertIn("Google Drive", self.local().detalhe)
        self.assertEqual(verificar.nuvem_da_pasta(self.pasta / "Sigilosos", []), "")

    def test_onedrive_detectado_sem_a_variavel(self):
        od = self.pasta / "Empresa"
        self.detectar.return_value = {"OneDrive (instituição)": od}
        self.assertEqual(verificar.nuvem_da_pasta(od / "Sig", None), "OneDrive")

    def test_deteccao_que_falha_nao_derruba(self):
        self.detectar.side_effect = OSError("sem acesso")
        self.assertEqual(self.local().situacao, OK)

    def test_pasta_da_nuvem_com_os_sigilosos_dentro(self):
        nuvem = self.pasta / "Nuvem"
        self.cfg.definir("compartilhar", "pasta_nuvem", str(nuvem))
        self.assertEqual(verificar.checar_pastas(self.cfg).situacao, OK)
        for secao, chave in (("geral", "pasta_sigilosos"), ("pauta", "pasta")):
            with self.subTest(chave=chave):
                self.cfg.definir("geral", "pasta_sigilosos", str(self.pasta / "Sigilosos"))
                self.cfg.definir("pauta", "pasta", str(self.pasta / "Pauta"))
                self.cfg.definir(secao, chave, str(nuvem / "Dentro"))
                item = verificar.checar_pastas(self.cfg)
                self.assertEqual((item.situacao, item.codigo), (AVISO, "pastas"))
                frase = config.conflito_com_a_nuvem(nuvem, self.cfg.pasta_sigilosos,
                                                    self.cfg.pasta_pauta)
                self.assertTrue(frase)
                self.assertIn(frase, item.detalhe)
                self.assertIn(str(nuvem), item.detalhe)
                self.assertIn("Ajustes › Pastas", item.acao)
                self.assertIn("Ajustes › Compartilhar", item.acao)

    def test_nuvem_dentro_dos_sigilosos(self):
        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.pasta / "Sigilosos" / "OD"))
        item = verificar.checar_pastas(self.cfg)
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("A pasta da nuvem não pode ficar dentro da pasta dos processos",
                      item.detalhe)


class TestCatalogoETribunaisLocais(unittest.TestCase):
    """O catálogo de tribunais e as correções de endereço do usuário
    (enderecos-locais.json): a correção fora do formato fica de fora - e a
    Verificação diz isso; a frase de erro não culpa só o tribunais.json."""

    def test_correcoes_fora_do_formato_sao_aviso(self):
        from helestron.nucleo import tribunais

        frase = (f"parte das correções de endereço ({tribunais.ARQUIVO_LOCAL}) está fora do "
                 "formato e foi ignorada: eproc:TJAL; vale o endereço do catálogo")
        with mock.patch.object(tribunais, "problema_locais", return_value=frase):
            item = verificar.checar_tribunais()
        self.assertEqual((item.situacao, item.codigo), (AVISO, "tribunais"))
        self.assertRegex(item.detalhe, r"^\d+ tribunais no catálogo; \d+ com e-SAJ ou eProc\. Mas ")
        self.assertTrue(item.detalhe.endswith(frase + "."))
        self.assertIn("Ajustes › Acessos aos portais", item.acao)
        self.assertIn("“Corrigir o endereço de um portal”", item.acao)
        self.assertIn(Path(tribunais.ARQUIVO_LOCAL).name, item.acao)

    def test_correcoes_ilegiveis_de_verdade(self):
        from helestron.nucleo import tribunais

        arquivo = Path(tempfile.mkdtemp()) / "enderecos-locais.json"
        self.addCleanup(lambda: arquivo.unlink(missing_ok=True))
        arquivo.write_text("{ quebrado", encoding="utf-8")
        with mock.patch.object(tribunais, "ARQUIVO_LOCAL", arquivo):
            item = verificar.checar_tribunais()
        self.assertEqual(item.situacao, AVISO, item.detalhe)
        self.assertIn("não puderam ser lidas e foram ignoradas", item.detalhe)
        with mock.patch.object(tribunais, "ARQUIVO_LOCAL", arquivo.with_name("nao-existe.json")):
            self.assertEqual(verificar.checar_tribunais().situacao, OK)

    def test_erro_ao_carregar_cita_as_correcoes(self):
        from helestron.nucleo import tribunais

        with mock.patch.object(tribunais, "carregar", side_effect=TypeError("x")):
            item = verificar.checar_tribunais()
        self.assertEqual(item.situacao, FALHA)
        self.assertIn("tribunais.json", item.detalhe)
        self.assertIn("correções de endereço", item.detalhe)
        self.assertIn(str(tribunais.ARQUIVO_LOCAL), item.detalhe)
        self.assertTrue(item.acao.startswith("Desfaça a última edição do enderecos-locais.json"))

    def test_catalogo_ilegivel_diz_o_motivo(self):
        from helestron.nucleo import tribunais

        motivo = ("o catálogo de tribunais (dados\\tribunais.json) não pôde ser lido: erro de "
                  "formatação na linha 3, coluna 5. Corrija o arquivo ou instale o programa de novo")
        with mock.patch.object(tribunais, "carregar", return_value=()), \
                mock.patch.object(tribunais, "problema", return_value=motivo):
            item = verificar.checar_tribunais()
        self.assertEqual(item.situacao, FALHA)
        self.assertEqual(item.detalhe, "O" + motivo[1:] + ".")
        with mock.patch.object(tribunais, "carregar", return_value=()), \
                mock.patch.object(tribunais, "problema", return_value=""):
            self.assertEqual(verificar.checar_tribunais().detalhe,
                             "O catálogo de tribunais está vazio.")


class TestConector(unittest.TestCase):
    """O conector MCP: roda de verdade (como o Claude Desktop o rodaria) e o
    que está registrado nas IAs aponta para este acervo e esta instalação."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.cfg = cfg_temporaria(self.pasta)
        self.desktop = self.pasta / "Claude" / "claude_desktop_config.json"
        self.codex = self.pasta / ".codex" / "config.toml"
        self.patches = [mock.patch.object(claude, "arquivos_config_desktop",
                                          return_value=[self.desktop]),
                        mock.patch.object(chatgpt, "arquivo_config_codex", return_value=self.codex)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_conector_de_verdade_responde(self):
        ferramentas, erro = verificar.conversar_mcp(claude.entrada_mcp(self.cfg.pasta_acervo))
        self.assertEqual(erro, "")
        self.assertEqual(set(ferramentas), {"listar_acervo", "ler_processo", "buscar",
                                            "ler_transcricao"})
        item = verificar.checar_conector(self.cfg)
        self.assertEqual((item.nome, item.situacao), ("Conector do acervo (MCP)", OK))
        self.assertIn("4 ferramentas", item.detalhe)
        self.assertIn("ainda não foi ligado", item.detalhe)

    def test_ligado_as_duas_ias(self):
        claude.registrar_mcp(self.cfg.pasta_acervo, [self.desktop])
        chatgpt.registrar_mcp_codex(self.cfg.pasta_acervo, self.codex)
        with mock.patch.object(verificar, "conversar_mcp", return_value=(["a", "b"], "")):
            item = verificar.checar_conector(self.cfg)
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertIn("ligado a: Claude Desktop, ChatGPT/Codex", item.detalhe)

    def test_registro_velho_ou_de_outro_acervo(self):
        outro = self.pasta / "Outro acervo"
        claude.registrar_mcp(outro, [self.desktop])
        dados = json.loads(self.desktop.read_text(encoding="utf-8"))
        dados["mcpServers"]["assessor-integrado"] = {"command": "C:/x/python.exe", "args": []}
        self.desktop.write_text(json.dumps(dados), encoding="utf-8")
        with mock.patch.object(verificar, "conversar_mcp", return_value=(["a"], "")):
            item = verificar.checar_conector(self.cfg)
        self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
        self.assertIn("versão anterior", item.detalhe)
        self.assertIn("aponta para outro acervo", item.detalhe)
        self.assertIn("\u201cReconectar o acervo\u201d", item.acao)

    def test_conector_que_nao_responde(self):
        quebrado = {"command": sys.executable, "args": ["-c", "import sys; sys.exit(3)"]}
        ferramentas, erro = verificar.conversar_mcp(quebrado, limite_s=60)
        self.assertEqual(ferramentas, [])
        self.assertIn("não se apresentou", erro)
        with mock.patch.object(claude, "entrada_mcp", return_value=quebrado):
            item = verificar.checar_conector(self.cfg)
        self.assertEqual((item.situacao, item.obrigatorio), (FALHA, False))
        self.assertIn("Helestron-Setup", item.acao)


class TestVerificacaoInteira(unittest.TestCase):
    """A verificação de verdade, neste computador: nunca quebra, nunca trava."""

    def test_roda_e_devolve_itens_validos(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_temporaria(Path(tmp))
            recebidos: list[Item] = []
            itens = verificar.verificar(cfg=cfg, ao_item=recebidos.append)
        self.assertEqual(itens, recebidos, "ao_item recebe tudo, na ordem")
        nomes = [i.nome for i in itens]
        self.assertEqual(len(nomes), len(set(nomes)))
        for esperado in ("Windows 64 bits", "Bibliotecas", "Componentes nativos (DLLs)",
                         "Modelo de transcrição", "Navegador dos portais",
                         "WebView2 (janela do programa)", "Microfone", "Permissão do microfone",
                         "Pastas de trabalho", "Local das pastas", "Espaço em disco",
                         "Cofre de senhas", "Catálogo de tribunais", "Regras da pauta",
                         "Separação de falantes (opcional)", "Conector do acervo (MCP)"):
            self.assertIn(esperado, nomes)
        # nada do programa antigo: a janela Tk e o INSTALAR.bat não existem mais
        self.assertNotIn("Python e janela (Tk)", nomes)
        self.assertFalse(any("INSTALAR" in i.acao or "INSTALAR" in i.detalhe for i in itens))
        for i in itens:
            self.assertIn(i.situacao, verificar.SITUACOES, i)
            self.assertTrue(i.detalhe, i)
            if i.situacao != OK and i.acao:
                self.assertTrue(i.acao.rstrip().endswith((".", ")")), i.acao)
        if sys.platform != "win32":
            # Fora do Windows nada que é só do Windows pode reprovar.
            for i in itens:
                if i.nome in ("Cofre de senhas", "Permissão do microfone", "Windows 64 bits",
                              "WebView2 (janela do programa)"):
                    self.assertEqual(i.situacao, AVISO)

    def test_pode_rodar_fora_da_thread_principal(self):
        # A janela chama a verificação de uma thread de trabalho.
        resultado: list = []
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_temporaria(Path(tmp))
            with mock.patch.object(verificar, "_etapas",
                                   return_value=[("Pastas de trabalho", lambda: verificar.checar_pastas(cfg)),
                                                 ("Windows 64 bits", verificar.checar_sistema)]):
                t = threading.Thread(target=lambda: resultado.extend(verificar.verificar(cfg=cfg)))
                t.start()
                t.join(120)
        self.assertEqual([i.nome for i in resultado], ["Pastas de trabalho", "Windows 64 bits"])


class TestLinhaDeComando(unittest.TestCase):
    def _main(self, argv, itens=None):
        saida = io.StringIO()
        patches = [mock.patch("helestron.nucleo.registro.configurar")]
        if itens is not None:
            def falso(completo=False, cfg=None, ao_item=None):
                for i in itens:
                    if ao_item:
                        ao_item(i)
                return list(itens)
            patches.append(mock.patch.object(verificar, "verificar", side_effect=falso))
        with contextlib.ExitStack() as pilha:
            for p in patches:
                pilha.enter_context(p)
            pilha.enter_context(contextlib.redirect_stdout(saida))
            codigo = verificar.main(argv)
        return codigo, saida.getvalue()

    def test_opcoes_invalidas(self):
        self.assertEqual(self._main(["--nao-existe"])[0], 2)
        codigo, texto = self._main(["--json"])
        self.assertEqual(codigo, 2)
        self.assertIn("Faltou o nome do arquivo", texto)

    def test_ajuda_em_portugues(self):
        codigo, texto = self._main(["--ajuda"])
        self.assertEqual(codigo, 0)
        self.assertIn("Uso: python -m helestron verificar", texto)
        self.assertIn("Código de saída", texto)

    def test_json_e_codigo_de_saida(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "sub" / "verificacao.json"
            codigo, texto = self._main(["--completo", "--json", str(destino)],
                                       [Item("A", OK, "certo"), Item("B", AVISO, "atenção", False, acao="Faça x.")])
            self.assertEqual(codigo, 0)
            dados = json.loads(destino.read_text(encoding="utf-8"))
            self.assertEqual(dados["resultado"], AVISO)
            self.assertTrue(dados["completo"])
            self.assertEqual([i["nome"] for i in dados["itens"]], ["A", "B"])
            self.assertEqual(dados["itens"][1]["detalhe"], "atenção")
        self.assertIn("verificação completa", texto)
        self.assertIn("O que fazer: Faça x.", texto)
        self.assertIn("A instalação está pronta, com avisos", texto)

    def test_falha_obrigatoria_reprova(self):
        codigo, texto = self._main([], [Item("A", FALHA, "quebrado", acao="Conserte.")])
        self.assertEqual(codigo, 1)
        self.assertIn("A instalação tem problemas", texto)
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "v.json"
            codigo, _ = self._main([f"--json={destino}"], [Item("A", FALHA, "opcional", obrigatorio=False)])
            self.assertEqual(json.loads(destino.read_text(encoding="utf-8"))["resultado"], AVISO)
        self.assertEqual(codigo, 0)


if __name__ == "__main__":
    unittest.main()
