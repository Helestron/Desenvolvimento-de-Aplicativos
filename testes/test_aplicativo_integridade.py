"""Integridade da instalação, --verificar-instalacao e a tela de erro própria."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import time
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


def instalador_falso(arquivo: Path, helestron: bool = True, nsis: bool = True) -> Path:
    """Um Helestron-Setup "de verdade" para o Reparar: executável do Windows,
    cabeçalho NSIS num limite de 512 bytes e a descrição do instalador."""
    corpo = bytearray(b"MZ" + b"\0" * 4000)
    if helestron:
        corpo += "Instalador do Helestron".encode("utf-16-le")
    corpo += b"\0" * (-len(corpo) % 512)
    if nsis:
        corpo += b"\0\0\0\0" + integridade.ASSINATURA_NSIS
    corpo += b"\x5d" * 2048
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_bytes(bytes(corpo))
    return arquivo


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

    def test_sem_como_abrir_a_janela_codigo_9(self):
        """Sem WebView2, sem Edge e com o Internet Explorer de navegador
        padrão, o instalador não pode dizer "tudo certo": código próprio (9)."""
        from helestron.aplicativo import janela

        with mock.patch.object(verificacao, "conferir_janela", conferir_janela_real), \
                mock.patch.object(verificacao, "NO_WINDOWS", True), \
                mock.patch.object(janela, "versao_webview2", return_value=None), \
                mock.patch.object(janela, "achar_edge", return_value=None), \
                mock.patch.object(janela, "navegador_padrao_serve", return_value=False):
            codigo, saida = self.rodar()
        self.assertEqual(codigo, verificacao.CODIGO_SEM_JANELA, saida)
        self.assertIn("Internet Explorer", saida)
        self.assertIn("WebView2 Runtime", saida)
        # com outra falha junto, o código é o de sempre
        verificacao.conferir_modulos.return_value = verificacao.Resultado(
            "Módulos do programa", verificacao.FALHA, "1 módulo não carrega.")
        with mock.patch.object(verificacao, "conferir_janela", conferir_janela_real), \
                mock.patch.object(verificacao, "NO_WINDOWS", True), \
                mock.patch.object(janela, "versao_webview2", return_value=None), \
                mock.patch.object(janela, "achar_edge", return_value=None), \
                mock.patch.object(janela, "navegador_padrao_serve", return_value=False):
            self.assertEqual(self.rodar()[0], 1)

    def test_conferir_janela(self):
        from helestron.aplicativo import janela

        casos = [
            ("120.0.2210.91", None, True, verificacao.OK, "120.0.2210.91"),
            ("95.0.1020.53", "/edge", True, verificacao.AVISO, "antigo"),
            (None, "/edge", True, verificacao.AVISO, "Microsoft Edge, em modo aplicativo"),
            (None, None, True, verificacao.AVISO, "navegador padrão"),
            (None, None, False, verificacao.FALHA, "Internet Explorer"),
        ]
        for versao, edge, serve, situacao, trecho in casos:
            with self.subTest(versao=versao, edge=edge, serve=serve), \
                    mock.patch.object(verificacao, "NO_WINDOWS", True), \
                    mock.patch.object(janela, "versao_webview2", return_value=versao), \
                    mock.patch.object(janela, "achar_edge", return_value=edge), \
                    mock.patch.object(janela, "navegador_padrao_serve", return_value=serve):
                r = conferir_janela_real()
                self.assertEqual(r.situacao, situacao, r)
                self.assertIn(trecho, r.detalhe)


conferir_janela_real = verificacao.conferir_janela


class TestVerificacaoRobusta(unittest.TestCase):
    """O instalador sempre tem relatório: as checagens do motor rodam num
    processo à parte, e o relatório é regravado a cada item."""

    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)

    def test_relatorio_gravado_a_cada_passo(self):
        relatorio = self.amb.raiz / "relatorio.txt"
        vistos = []

        def primeiro():
            return verificacao.Resultado("Arquivos do programa", verificacao.OK, "certo")

        def segundo():
            # Se o processo caísse aqui, o instalador já acharia isto:
            vistos.append(relatorio.read_text(encoding="utf-8"))
            return verificacao.Resultado("Módulos do programa", verificacao.OK, "certo")

        codigo = verificacao.executar(relatorio, saida=lambda _t: None, passos=[primeiro, segundo])
        self.assertEqual(codigo, 0)
        self.assertIn("Arquivos do programa", vistos[0])
        self.assertIn(verificacao.EM_ANDAMENTO, vistos[0])
        final = relatorio.read_text(encoding="utf-8")
        self.assertNotIn(verificacao.EM_ANDAMENTO, final)
        self.assertIn("Resultado: tudo certo", final)

    def test_motor_de_verdade_num_processo_a_parte(self):
        with mock.patch.object(verificacao, "LIMITE_MOTOR_S", 300.0):
            resultados = verificacao.conferir_motor()
        nomes = [r.nome for r in resultados]
        self.assertEqual(nomes, verificacao.nomes_do_motor())
        for esperado in ("Windows 64 bits", "Bibliotecas", "Componentes nativos (DLLs)",
                         "Modelo de transcrição", "Teste de transcrição",
                         "Navegador dos portais", "Pastas de trabalho", "Cofre de senhas",
                         "Conector do acervo (MCP)"):
            self.assertIn(esperado, nomes)
        # o WebView2 sai uma vez só, pela conferência da janela
        self.assertNotIn("WebView2 (janela do programa)", nomes)
        self.assertEqual(verificacao.conferir_janela().nome, "WebView2 (janela do programa)")

    def test_queda_nativa_no_filho_vira_falha_e_o_resto_segue(self):
        """Uma checagem derruba o processo (DLL quebrada): ela sai como falha,
        com a explicação, e as demais rodam num processo novo."""
        sonda = r"""
import json, os, sys
for nome in [a for a in sys.argv[1:] if not a.startswith("--")]:
    print(json.dumps({"inicio": nome}), flush=True)
    if nome == "Microfone":
        os.abort()
    print(json.dumps({"item": nome, "dados": {"nome": nome, "situacao": "ok", "detalhe": "certo",
                                              "obrigatorio": True, "acao": ""}}), flush=True)
"""
        recebidos = []
        with mock.patch.object(verificacao, "_SONDA_MOTOR", sonda):
            resultados = verificacao.conferir_motor(ao_resultado=recebidos.append)
        por_nome = {r.nome: r for r in resultados}
        self.assertEqual(list(por_nome), verificacao.nomes_do_motor())
        self.assertEqual(por_nome["Microfone"].situacao, verificacao.FALHA)
        self.assertIn("caiu", por_nome["Microfone"].detalhe)
        self.assertIn("Helestron-Setup", por_nome["Microfone"].acao)
        outros = [r for r in resultados if r.nome != "Microfone"]
        self.assertTrue(all(r.situacao == verificacao.OK for r in outros))
        self.assertEqual(len(recebidos), len(resultados))

    def test_checagem_que_trava_de_verdade(self):
        """Uma checagem que trava (caixa de erro invisível de uma DLL) não prende
        a verificação até o limite total: o processo calado é encerrado."""
        sonda = r"""
import json, sys, time
for nome in [a for a in sys.argv[1:] if not a.startswith("--")]:
    print(json.dumps({"inicio": nome}), flush=True)
    if nome == "Microfone":
        time.sleep(600)
    print(json.dumps({"item": nome, "dados": {"nome": nome, "situacao": "ok", "detalhe": "certo",
                                              "obrigatorio": True, "acao": ""}}), flush=True)
"""
        inicio = time.monotonic()
        with mock.patch.object(verificacao, "_SONDA_MOTOR", sonda), \
                mock.patch.object(verificacao, "SEM_NOVIDADE_MOTOR_S", 2.0):
            resultados = verificacao.conferir_motor()
        self.assertLess(time.monotonic() - inicio, 60)
        por_nome = {r.nome: r for r in resultados}
        self.assertEqual(list(por_nome), verificacao.nomes_do_motor())
        self.assertEqual(por_nome["Microfone"].situacao, verificacao.FALHA)
        self.assertIn("travou", por_nome["Microfone"].detalhe)
        self.assertTrue(all(r.situacao == verificacao.OK for r in resultados if r.nome != "Microfone"))

    def test_python_que_nao_abre(self):
        with mock.patch("helestron.verificar.rodar", return_value=(1, "", "Fatal Python error", False)):
            resultados = verificacao.conferir_motor()
        self.assertTrue(resultados)
        self.assertTrue(all(r.situacao == verificacao.FALHA for r in resultados))
        self.assertIn("não iniciou", resultados[0].detalhe)

    def test_checagem_que_trava(self):
        nomes = verificacao.nomes_do_motor()
        saidas = [
            # paralelo: as duas primeiras começam e a segunda trava
            (None, json.dumps({"inicio": nomes[0]}) + "\n" + json.dumps({"inicio": nomes[1]})
             + "\n" + json.dumps({"item": nomes[0], "dados": {"nome": nomes[0], "situacao": "ok"}}),
             "", True),
            (0, "\n".join(json.dumps({"item": n, "dados": {"nome": n, "situacao": "ok"}})
                           for n in nomes[2:]) + "\n" + "\n".join(
                json.dumps({"inicio": n}) for n in nomes[2:]), "", False),
        ]
        with mock.patch("helestron.verificar.rodar", side_effect=saidas):
            resultados = verificacao.conferir_motor()
        por_nome = {r.nome: r for r in resultados}
        self.assertEqual(por_nome[nomes[1]].situacao, verificacao.FALHA)
        self.assertIn("travou", por_nome[nomes[1]].detalhe)
        self.assertEqual(len(resultados), len(nomes))


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
        def sondar(nomes, limite, extra, **_):
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
        # grava o instancia.json (o --encerrar do instalador fala com a tela)
        mostrar.assert_called_once_with(self.problemas, registrar=True)
        with mock.patch.object(integridade, "conferir_rapido", return_value=self.problemas), \
                mock.patch.object(erro, "mostrar", return_value=1) as mostrar:
            inicio._abrir(Path(self.amb.raiz / "autoteste"))
        mostrar.assert_called_once_with(self.problemas, registrar=False)

    def test_sem_nem_a_tela_de_erro_mensagem_nativa(self):
        with mock.patch.object(integridade, "conferir_rapido", return_value=self.problemas), \
                mock.patch.object(erro, "mostrar", side_effect=RuntimeError("sem janela")), \
                mock.patch.object(inicio, "mensagem_nativa") as mensagem, \
                self.assertLogs("aplicativo.inicio", "ERROR"):
            self.assertEqual(inicio._abrir(None), 1)
        self.assertIn("rede.py", mensagem.call_args[0][1])

    def test_procurar_instalador(self):
        """O instalador não deixa cópia de si: o Reparar o acha em Downloads."""
        casa = self.amb.raiz / "casa"
        (casa / "Downloads").mkdir(parents=True)
        with mock.patch.object(caminhos, "INSTALADO", False, create=True), \
                mock.patch("pathlib.Path.home", return_value=casa), \
                mock.patch.object(integridade, "NO_WINDOWS", False):
            self.assertIsNone(integridade.procurar_instalador())
            instalador_falso(casa / "Downloads" / "Helestron-Setup-1.0.0.exe")
            achado = integridade.procurar_instalador()
        self.assertEqual(achado, casa / "Downloads" / "Helestron-Setup-1.0.0.exe")

    def test_downloads_redirecionada(self):
        """Com a pasta Downloads redirecionada (GPO do tribunal) ou movida, o
        Reparar procura onde o Windows diz que ela está (SHGetKnownFolderPath)."""
        casa = self.amb.raiz / "casa"
        casa.mkdir()
        redirecionada = self.amb.raiz / "rede" / "Downloads"
        instalador_falso(redirecionada / "Helestron-Setup-1.0.0.exe")
        with mock.patch.object(caminhos, "INSTALADO", False, create=True), \
                mock.patch("pathlib.Path.home", return_value=casa), \
                mock.patch.object(integridade, "NO_WINDOWS", True), \
                mock.patch.object(integridade, "_downloads_windows", return_value=redirecionada):
            self.assertEqual(integridade.pastas_downloads(), [redirecionada, casa / "Downloads"])
            achado = integridade.procurar_instalador()
        self.assertEqual(achado, redirecionada / "Helestron-Setup-1.0.0.exe")

    def test_so_um_instalador_do_helestron_de_verdade(self):
        """Um executável qualquer com nome parecido, mais novo, não passa na frente."""
        casa = self.amb.raiz / "casa"
        baixados = casa / "Downloads"
        bom = instalador_falso(baixados / "Helestron-Setup-1.0.0.exe")
        antigo = time.time() - 3600
        os.utime(bom, (antigo, antigo))
        (baixados / "Helestron-Setup (atualização).exe").write_bytes(b"MZ" + b"\0" * 100)
        instalador_falso(baixados / "Helestron-Setup-1.0.1.exe", nsis=False)      # não é NSIS
        instalador_falso(baixados / "Helestron-Setup-1.0.2.exe", helestron=False)  # outro programa
        corrompido = instalador_falso(baixados / "Helestron-Setup-1.0.3.exe")
        (baixados / "Helestron-Setup-1.0.3.exe.sha256").write_text(
            "0" * 64 + "  Helestron-Setup-1.0.3.exe\n", encoding="utf-8")
        with mock.patch.object(caminhos, "INSTALADO", False, create=True), \
                mock.patch("pathlib.Path.home", return_value=casa), \
                mock.patch.object(integridade, "NO_WINDOWS", False), \
                self.assertLogs("aplicativo.integridade", "WARNING") as registro:
            self.assertEqual(integridade.procurar_instalador(), bom)
        texto = "\n".join(registro.output)
        self.assertIn("cabeçalho do instalador", texto)
        self.assertIn("não é o instalador do Helestron", texto)
        self.assertIn("código de conferência", texto)
        self.assertNotIn("atualização", texto)               # nem chega a ser candidato
        self.assertIsNone(integridade.conferir_instalador(bom))
        (baixados / "Helestron-Setup-1.0.3.exe.sha256").write_text(
            integridade.sha256_de(corrompido) + "  Helestron-Setup-1.0.3.exe\n", encoding="utf-8")
        self.assertIsNone(integridade.conferir_instalador(corrompido))
        # o nome que o navegador dá ao baixar de novo também vale
        self.assertEqual(integridade.versao_do_instalador(Path("Helestron-Setup-1.2.3 (1).exe")),
                         (1, 2, 3))
        self.assertIsNone(integridade.versao_do_instalador(Path("Helestron-Setup (1).exe")))

    def test_nunca_uma_versao_mais_velha_que_a_instalada(self):
        pasta = self.amb.raiz / "programa"
        instalacao_falsa(pasta, {"Lib/os.py": b"# os"})
        manifesto = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
        manifesto["versao"] = "1.2.0"
        (pasta / "manifesto.json").write_text(json.dumps(manifesto), encoding="utf-8")
        casa = self.amb.raiz / "casa"
        instalador_falso(casa / "Downloads" / "Helestron-Setup-1.1.9.exe")
        with mock.patch.object(integridade, "pasta_instalada", return_value=pasta), \
                mock.patch("pathlib.Path.home", return_value=casa), \
                mock.patch.object(integridade, "NO_WINDOWS", False):
            self.assertIsNone(integridade.procurar_instalador())
            novo = instalador_falso(casa / "Downloads" / "Helestron-Setup-1.2.0.exe")
            self.assertEqual(integridade.procurar_instalador(), novo)

    def test_reparar_pede_confirmacao_antes_de_abrir(self):
        instalador = instalador_falso(self.amb.raiz / "Downloads" / "Helestron-Setup-1.0.0.exe")
        with mock.patch.object(erro, "NO_WINDOWS", True), \
                mock.patch.object(integridade, "procurar_instalador", return_value=instalador), \
                mock.patch.object(erro, "_executar") as executar:
            primeiro = self.cliente.dados("POST", "/api/integridade/reparar")
            executar.assert_not_called()
            self.assertTrue(primeiro["confirmar"])
            self.assertFalse(primeiro["abriu"])
            self.assertIn("Helestron-Setup-1.0.0.exe", primeiro["mensagem"])
            self.assertIn("Abrir o instalador", primeiro["mensagem"])
            outro = self.cliente.dados("POST", "/api/integridade/reparar",
                                       {"arquivo": str(self.amb.raiz / "outro.exe")})
            executar.assert_not_called()
            self.assertFalse(outro["abriu"])
            with mock.patch("threading.Timer"):
                segundo = self.cliente.dados("POST", "/api/integridade/reparar",
                                             {"arquivo": primeiro["arquivo"]})
            executar.assert_called_once_with(instalador)
            self.assertTrue(segundo["abriu"])
        html = self.cliente.get("/", token=False)[1].decode("utf-8")
        self.assertIn('id="abrir-instalador"', html)


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
