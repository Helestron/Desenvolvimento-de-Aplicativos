"""Integridade da instalação, --verificar-instalacao e a tela de erro própria."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from helestron import __main__ as principal
from helestron.aplicativo import erro, inicio, integridade, verificacao
from helestron.nucleo import caminhos

from testes.test_servidor_base import AmbienteTemporario, Cliente


def instalacao_falsa(pasta: Path, arquivos: dict[str, bytes], formato: str = "dict") -> None:
    """Uma 'pasta do programa' com manifesto.json, como a do instalador."""
    entradas = {}
    for rel, dados in arquivos.items():
        alvo = pasta / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(dados)
        entradas[rel] = {"tamanho": len(dados), "sha256": hashlib.sha256(dados).hexdigest()}
    if formato == "lista":
        corpo = {"versao": "1.0.0", "arquivos": [dict(caminho=k, **v) for k, v in entradas.items()]}
    else:
        corpo = {"versao": "1.0.0", "arquivos": entradas}
    (pasta / "manifesto.json").write_text(json.dumps(corpo), encoding="utf-8")


ARQUIVOS = {
    "python312.dll": b"MZ" + b"\0" * 100,
    "Helestron.exe": b"MZ" + b"\1" * 50,
    "DLLs/_ssl.pyd": b"pyd",
    "Lib/os.py": b"# os",
    "Lib/site-packages/helestron/__init__.py": b"# helestron",
    "Lib/site-packages/helestron/servidor/rede.py": b"# rede",
    "Lib/site-packages/numpy/__init__.py": b"# numpy",
    "modelos/faster-whisper-small/model.bin": b"\0" * 64,
}


class TestManifesto(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp(prefix="helestron-inst-"))
        self.addCleanup(shutil.rmtree, self.pasta, True)

    def test_formatos(self):
        for formato in ("dict", "lista"):
            with self.subTest(formato=formato):
                instalacao_falsa(self.pasta, ARQUIVOS, formato)
                versao, entradas = integridade.ler_manifesto(self.pasta)
                self.assertEqual(versao, "1.0.0")
                self.assertEqual(len(entradas), len(ARQUIVOS))
                self.assertEqual(integridade.conferir_rapido(self.pasta), [])
                self.assertEqual(integridade.conferir_completo(self.pasta), [])

    def test_manifesto_ilegivel(self):
        (self.pasta / "manifesto.json").write_text("{", encoding="utf-8")
        problemas = integridade.conferir_rapido(self.pasta)
        self.assertEqual(problemas[0].motivo, integridade.MANIFESTO)

    def test_rapido_so_confere_o_essencial(self):
        instalacao_falsa(self.pasta, ARQUIVOS)
        (self.pasta / "Lib/site-packages/numpy/__init__.py").unlink()
        (self.pasta / "modelos/faster-whisper-small/model.bin").unlink()
        self.assertEqual(integridade.conferir_rapido(self.pasta), [])
        (self.pasta / "Lib/site-packages/helestron/servidor/rede.py").unlink()
        (self.pasta / "python312.dll").write_bytes(b"MZ")
        with self.assertLogs("aplicativo.integridade", "ERROR"):
            problemas = {p.arquivo: p.motivo for p in integridade.conferir_rapido(self.pasta)}
        self.assertEqual(problemas, {"Lib/site-packages/helestron/servidor/rede.py": "ausente",
                                     "python312.dll": "tamanho"})
        completo = {p.arquivo for p in integridade.conferir_completo(self.pasta)}
        self.assertIn("Lib/site-packages/numpy/__init__.py", completo)
        self.assertIn("modelos/faster-whisper-small/model.bin", completo)

    def test_completo_confere_o_hash(self):
        instalacao_falsa(self.pasta, ARQUIVOS)
        (self.pasta / "Lib/os.py").write_bytes(b"# OS")         # mesmo tamanho
        self.assertEqual(integridade.conferir_rapido(self.pasta), [])
        problemas = integridade.conferir_completo(self.pasta)
        self.assertEqual([(p.arquivo, p.motivo) for p in problemas], [("Lib/os.py", "conteudo")])
        self.assertIn("Lib\\os.py", problemas[0].frase)

    def test_caminho_malicioso_no_manifesto_e_ignorado(self):
        (self.pasta / "manifesto.json").write_text(json.dumps(
            {"arquivos": {"../fora.txt": {"tamanho": 1, "sha256": ""}}}), encoding="utf-8")
        self.assertEqual(integridade.ler_manifesto(self.pasta)[1], [])

    def test_fora_da_instalacao_nada_e_conferido(self):
        with mock.patch.object(caminhos, "INSTALADO", False, create=True):
            self.assertIsNone(integridade.pasta_instalada())
            self.assertEqual(integridade.conferir_rapido(), [])

    def test_descrever(self):
        problemas = [integridade.Problema(f"a{i}.py", "ausente") for i in range(12)]
        texto = integridade.descrever(problemas, 10)
        self.assertIn("e mais 2 arquivos", texto)


class TestVerificarInstalacao(unittest.TestCase):
    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.pasta = self.amb.raiz / "Programs" / "Helestron"
        instalacao_falsa(self.pasta, ARQUIVOS)
        for nome, valor in (("INSTALADO", True), ("INSTALACAO", self.pasta)):
            p = mock.patch.object(caminhos, nome, valor, create=True)
            p.start()
            self.addCleanup(p.stop)
        # As checagens demoradas (subprocessos, modelo, WebView2) ficam de fora.
        for nome in ("conferir_modulos", "conferir_motor", "conferir_janela"):
            p = mock.patch.object(verificacao, nome,
                                  return_value=verificacao.Resultado(nome, verificacao.OK, "ok"))
            p.start()
            self.addCleanup(p.stop)

    def rodar(self, *args) -> tuple[int, str]:
        saida = io.StringIO()
        with redirect_stdout(saida), mock.patch("helestron.nucleo.registro.configurar"):
            codigo = principal.main(["--verificar-instalacao", *args])
        return codigo, saida.getvalue()

    def test_arquivo_faltando_codigo_1_e_relatorio(self):
        (self.pasta / "Lib/site-packages/helestron/servidor/rede.py").unlink()
        relatorio = self.amb.raiz / "relatorio.txt"
        codigo, saida = self.rodar("--relatorio", str(relatorio))
        self.assertEqual(codigo, 1)
        texto = relatorio.read_text(encoding="utf-8")
        self.assertIn("Lib\\site-packages\\helestron\\servidor\\rede.py", texto)
        self.assertIn("FALHA", texto)
        self.assertIn("Helestron-Setup", texto)
        self.assertIn("rede.py", saida)

    def test_tudo_certo_codigo_0_e_relatorio_padrao(self):
        codigo, saida = self.rodar()
        self.assertEqual(codigo, 0, saida)
        padrao = self.amb.local / "Logs" / "verificacao-instalacao.txt"
        self.assertTrue(padrao.exists())
        self.assertIn("tudo certo", padrao.read_text(encoding="utf-8"))

    def test_falha_de_modulo_reprova(self):
        verificacao.conferir_modulos.return_value = verificacao.Resultado(
            "Módulos do programa", verificacao.FALHA, "1 módulo não carrega.",
            linhas=("helestron.servidor.rede: ModuleNotFoundError",))
        codigo, saida = self.rodar()
        self.assertEqual(codigo, 1)
        self.assertIn("helestron.servidor.rede", saida)


class TestModulos(unittest.TestCase):
    def test_percorre_o_pacote_inteiro(self):
        nomes, erros = verificacao.modulos_do_pacote()
        for esperado in ("helestron", "helestron.__main__", "helestron.servidor.rede",
                         "helestron.servidor.api_pauta", "helestron.aplicativo.inicio",
                         "helestron.aplicativo.janela", "helestron.download.motor",
                         "helestron.servicos", "helestron.tarefas"):
            self.assertIn(esperado, nomes)
        self.assertNotIn("helestron.interface", " ".join(nomes))

    def test_importar_todos_aponta_o_que_falha(self):
        def sondar(nomes, limite, extra):
            return {n: ({"ok": False, "erro": "ModuleNotFoundError: x"}
                        if n == "helestron.servidor.rede" else {"ok": True}) for n in nomes}

        with mock.patch("helestron.verificar.sondar_importacoes", side_effect=sondar):
            erros = verificacao.importar_todos()
            resultado = verificacao.conferir_modulos()
        self.assertEqual([n for n, _ in erros], ["helestron.servidor.rede"])
        self.assertEqual(resultado.situacao, verificacao.FALHA)

    def test_servidor_e_aplicativo_importam_de_verdade(self):
        """Os módulos desta área carregam sem tela (sem pywebview, sem Tk)."""
        import importlib

        for nome in ("helestron.servidor.rotas", "helestron.servidor.aplicacao",
                     "helestron.aplicativo.inicio", "helestron.aplicativo.janela",
                     "helestron.aplicativo.erro", "helestron.aplicativo.monitor",
                     "helestron.aplicativo.autoteste", "helestron.aplicativo.verificacao"):
            importlib.import_module(nome)


class TestTelaDeErro(unittest.TestCase):
    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.problemas = [integridade.Problema("Lib/site-packages/helestron/servidor/rede.py",
                                               "ausente")]
        self.app = erro.AplicacaoErro(self.problemas).iniciar()
        self.addCleanup(self.app.encerrar)
        self.cliente = Cliente(self.app)

    def test_pagina_com_o_arquivo_e_a_hipotese(self):
        status, corpo = self.cliente.get("/", token=False)
        self.assertEqual(status, 200)
        html = corpo.decode("utf-8")
        self.assertIn("helestron\\servidor\\rede.py", html)
        self.assertIn("antivírus", html)
        self.assertIn("Reparar", html)
        csp = self.cliente.ultimos_cabecalhos["Content-Security-Policy"]
        self.assertIn("'nonce-", csp)
        self.assertNotIn("unsafe-inline", csp)

    def test_reparar_sem_instalador_explica(self):
        with mock.patch.object(integridade, "procurar_instalador", return_value=None):
            dados = self.cliente.dados("POST", "/api/integridade/reparar")
        self.assertFalse(dados["abriu"])
        self.assertIn("Helestron-Setup", dados["mensagem"])
        estado = self.cliente.dados("GET", "/api/integridade")
        self.assertEqual(estado["problemas"][0]["motivo"], "ausente")

    def test_so_abre_os_registros(self):
        status, _ = self.cliente.post("/api/abrir", {"tipo": "pasta", "alvo": "/etc"})
        self.assertEqual(status, 403)
        with mock.patch("helestron.nucleo.sistema.abrir_pasta") as abrir:
            self.cliente.dados("POST", "/api/abrir", {"tipo": "pasta", "alvo": "logs"})
        abrir.assert_called_once()

    def test_sem_token_403(self):
        status, _ = self.cliente.post("/api/encerrar", token=False)
        self.assertEqual(status, 403)
        self.cliente.dados("POST", "/api/encerrar")
        self.assertTrue(self.app.encerrado.wait(5))

    def test_inicio_mostra_a_tela_de_erro(self):
        with mock.patch.object(integridade, "conferir_rapido", return_value=self.problemas), \
                mock.patch.object(erro, "mostrar", return_value=1) as mostrar:
            self.assertEqual(inicio._abrir(None), 1)
        mostrar.assert_called_once_with(self.problemas)

    def test_sem_nem_a_tela_de_erro_mensagem_nativa(self):
        with mock.patch.object(integridade, "conferir_rapido", return_value=self.problemas), \
                mock.patch.object(erro, "mostrar", side_effect=RuntimeError("sem janela")), \
                mock.patch.object(inicio, "mensagem_nativa") as mensagem, \
                self.assertLogs("aplicativo.inicio", "ERROR"):
            self.assertEqual(inicio._abrir(None), 1)
        self.assertIn("rede.py", mensagem.call_args[0][1])

    def test_procurar_instalador(self):
        pasta = self.amb.local / "instalador"
        pasta.mkdir(parents=True)
        (pasta / "Helestron-Setup-1.0.0.exe").write_bytes(b"MZ")
        with mock.patch.object(caminhos, "INSTALADO", False, create=True):
            achado = integridade.procurar_instalador()
        self.assertEqual(achado.name, "Helestron-Setup-1.0.0.exe")


class TestAberturaSemPacote(unittest.TestCase):
    def test_import_quebrado_vira_mensagem(self):
        import builtins

        original = builtins.__import__

        def falso(nome, *args, **kw):
            if nome.endswith("aplicativo") or "aplicativo.inicio" in nome:
                raise ImportError("No module named 'helestron.aplicativo.inicio'",
                                  name="helestron.aplicativo.inicio")
            return original(nome, *args, **kw)

        with mock.patch("builtins.__import__", side_effect=falso), \
                mock.patch.object(principal, "_mensagem") as mensagem:
            self.assertEqual(principal.abrir_programa(), 1)
        self.assertIn("helestron.aplicativo.inicio", mensagem.call_args[0][1])
        self.assertIn("antivírus", mensagem.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
