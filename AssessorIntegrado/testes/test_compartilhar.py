"""Testes do compartilhamento com IA: servidor MCP, preparo, Claude, ChatGPT, nuvem."""

from __future__ import annotations

import io
import json
import os
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app.compartilhar import chatgpt, claude, mcp_servidor, nuvem, preparo, textos
from app.nucleo import config

NUM = "0800072-12.2024.8.02.0056"
INCIDENTE = f"{NUM}-01"          # o mesmo número com /01, como o programa o grava
SIGILOSO = "0700999-61.2024.8.02.0001"


def _pdf(destino: Path, paginas: list[str], marcadores=None) -> Path:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for texto in paginas:
        doc.new_page().insert_text((72, 72), texto)
    if marcadores:
        doc.set_toc(marcadores)
    doc.save(str(destino))
    return destino


def _sem_config(*args, **kwargs):
    """Acervo e espelho sem a pasta de sigilosos do config.ini da máquina."""
    return None


def _docx(destino: Path, linhas: list[str]) -> Path:
    from docx import Document

    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    for l in linhas:
        doc.add_paragraph(l)
    doc.save(str(destino))
    return destino


class BaseAcervo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.raiz = Path(self.dir.name) / "Acervo"
        _pdf(self.raiz / "Processos" / "Lote 1" / f"{NUM}.pdf",
             ["Petição inicial do autor", "Contestação: alega prescrição", "Sentença"])
        _docx(self.raiz / "Transcricoes" / f"{NUM}.docx",
              ["TRANSCRIÇÃO DE AUDIÊNCIA", "TESTEMUNHA [00:01:02] — vi o acidente"])
        # O que NÃO é autos: produto da IA, cache e arquivo-trava do Word
        _pdf(self.raiz / "Produtos" / f"{NUM}.pdf", ["minuta"])
        (self.raiz / "Transcricoes" / f"~${NUM}.docx").write_bytes(b"trava")

    def tearDown(self):
        self.dir.cleanup()


class TestServidorMCP(BaseAcervo):
    def conversar(self, mensagens: list[dict]) -> list[dict]:
        entrada = io.BytesIO("".join(json.dumps(m) + "\n" for m in mensagens).encode())
        saida = io.BytesIO()
        mcp_servidor.servir(self.raiz, entrada=entrada, saida=saida)
        return [json.loads(l) for l in saida.getvalue().decode().splitlines() if l.strip()]

    def test_protocolo_completo(self):
        r = self.conversar([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "listar_acervo", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "buscar", "arguments": {"termo": "PRESCRICAO"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "ler_processo", "arguments": {"numero": NUM.replace("-", "").replace(".", ""),
                                                             "folha_inicial": 2, "folha_final": 2}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
             "params": {"name": "ler_transcricao", "arguments": {"numero": NUM}}},
            {"jsonrpc": "2.0", "id": 7, "method": "metodo/inexistente"},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
             "params": {"name": "ler_processo", "arguments": {"numero": "0000001-00.2024.8.02.0001"}}},
        ])
        self.assertEqual(len(r), 8)            # a notificação não tem resposta
        self.assertEqual(r[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual({f["name"] for f in r[1]["result"]["tools"]},
                         {"listar_acervo", "ler_processo", "buscar", "ler_transcricao"})
        lista = r[2]["result"]["content"][0]["text"]
        self.assertIn(f"{NUM} — 3 pág.", lista)
        self.assertNotIn("Produtos", lista)
        self.assertIn("fl. 2", r[3]["result"]["content"][0]["text"])
        texto = r[4]["result"]["content"][0]["text"]
        self.assertIn("=== [fl. 2] ===", texto)
        self.assertNotIn("[fl. 1]", texto)
        self.assertIn("vi o acidente", r[5]["result"]["content"][0]["text"])
        self.assertEqual(r[6]["error"]["code"], -32601)
        self.assertTrue(r[7]["result"]["isError"])

    def test_versao_desconhecida_responde_a_mais_nova(self):
        r = self.conversar([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2099-01-01"}}])
        self.assertEqual(r[0]["result"]["protocolVersion"], mcp_servidor.VERSOES[0])

    def test_json_invalido(self):
        saida = io.BytesIO()
        mcp_servidor.servir(self.raiz, entrada=io.BytesIO(b"{quebrado\n"), saida=saida)
        self.assertEqual(json.loads(saida.getvalue())["error"]["code"], -32700)


class TestTextos(unittest.TestCase):
    def test_busca_sem_acento_e_recorte(self):
        texto = "=== [fl. 1] ===\nInício\n=== [fl. 2] ===\nA contestação alega prescrição\n"
        achados = textos.buscar(texto, "CONTESTACAO")
        self.assertEqual(achados[0][0], 2)
        self.assertEqual(textos.recortar_paginas(texto, 2, 2).count("[fl."), 1)


class TestPreparo(BaseAcervo):
    def test_cria_contexto_indice_textos_e_skill(self):
        rel = preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=True)
        self.assertEqual((rel.processos, rel.transcricoes, rel.textos_novos), (1, 1, 1))
        for nome in ("CLAUDE.md", "AGENTS.md", "INDICE.md",
                     ".claude/skills/acervo-judicial/SKILL.md", f"_ia/texto/{NUM}.txt"):
            self.assertTrue((self.raiz / nome).exists(), nome)
        self.assertIn(NUM, (self.raiz / "INDICE.md").read_text(encoding="utf-8"))
        skill = (self.raiz / ".claude/skills/acervo-judicial/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: acervo-judicial\ndescription: "))
        # O AGENTS.md cabe no limite do Codex (32 KiB)
        self.assertLess((self.raiz / "AGENTS.md").stat().st_size, 24 * 1024)

    def test_idempotente_e_respeita_edicao_do_usuario(self):
        preparo.atualizar_contexto(raiz=self.raiz)
        (self.raiz / "CLAUDE.md").write_text("minhas regras", encoding="utf-8")
        rel = preparo.atualizar_contexto(raiz=self.raiz)
        self.assertEqual(rel.arquivos, [])
        self.assertEqual(rel.textos_novos, 0)
        self.assertEqual((self.raiz / "CLAUDE.md").read_text(encoding="utf-8"), "minhas regras")

    def test_pdf_corrompido_nao_derruba(self):
        (self.raiz / "Processos" / "Lote 1" / "0700123-45.2024.8.02.0001.pdf").write_bytes(b"lixo")
        rel = preparo.atualizar_contexto(raiz=self.raiz)
        self.assertEqual(len(rel.erros), 1)


class TestDependente(BaseAcervo):
    """Regressão: o "-01" do nome do arquivo era ignorado e o incidente tomava
    a chave do principal - a IA lia os autos de outro processo."""

    def setUp(self):
        super().setUp()
        _pdf(self.raiz / "Processos" / "Lote 1" / f"{INCIDENTE}.pdf",
             ["Cumprimento de sentença do incidente"])
        _docx(self.raiz / "Transcricoes" / f"{INCIDENTE}.docx", ["AUDIÊNCIA DO INCIDENTE"])

    def test_principal_e_incidente_separados_em_tudo(self):
        ac = mcp_servidor.Acervo(self.raiz, sigilosos=None)
        self.assertEqual(set(ac.pdfs()), {NUM, INCIDENTE})
        self.assertEqual(set(ac.transcricoes()), {NUM, INCIDENTE})
        self.assertIn("Petição inicial", ac.ler_processo(NUM))
        self.assertNotIn("incidente", ac.ler_processo(NUM))
        # Como nos autos ("/01") e como na listagem ("-01")
        for pedido in (f"{NUM}/01", INCIDENTE):
            self.assertIn("Cumprimento de sentença do incidente", ac.ler_processo(pedido))
            self.assertIn("AUDIÊNCIA DO INCIDENTE", ac.ler_transcricao(pedido))
        self.assertIn(f"Processo {NUM}/01", ac.ler_processo(INCIDENTE))
        rel = preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=True)
        self.assertEqual(rel.processos, 2)
        self.assertIn("incidente", (self.raiz / "_ia" / "texto" / f"{INCIDENTE}.txt")
                      .read_text(encoding="utf-8"))
        self.assertNotIn("incidente", (self.raiz / "_ia" / "texto" / f"{NUM}.txt")
                         .read_text(encoding="utf-8"))
        indice = (self.raiz / "INDICE.md").read_text(encoding="utf-8")
        self.assertIn(f"| {INCIDENTE} |", indice)
        self.assertIn(f"| {NUM} |", indice)

    def test_texto_de_outro_pdf_nao_passa_por_atual(self):
        # O texto antigo do principal tinha sido tirado do incidente (mais
        # novo): pela regra "texto mais novo que o PDF" ele ficaria para sempre.
        principal = self.raiz / "Processos" / "Lote 1" / f"{NUM}.pdf"
        uma_hora_antes = principal.stat().st_mtime - 3600
        os.utime(principal, (uma_hora_antes, uma_hora_antes))
        destino = self.raiz / "_ia" / "texto" / f"{NUM}.txt"
        destino.parent.mkdir(parents=True)
        destino.write_text("=== [fl. 1] ===\nCumprimento de sentença do incidente\n",
                           encoding="utf-8")
        textos.garantir_texto(principal, destino)
        self.assertIn("Petição inicial", destino.read_text(encoding="utf-8"))
        # Em dia, não é extraído de novo
        destino.write_text("=== [fl. 1] ===\nmarca\n", encoding="utf-8")
        os.utime(destino, (uma_hora_antes, uma_hora_antes))
        textos.garantir_texto(principal, destino)
        self.assertIn("marca", destino.read_text(encoding="utf-8"))


class TestSigilo(BaseAcervo):
    def setUp(self):
        super().setUp()
        self.sigilosos = Path(self.dir.name) / "Sigilosos"

    def test_pasta_de_sigilosos_dentro_do_acervo_fica_de_fora(self):
        # Configuração errada (acervo D:\\Gabinete, sigilosos D:\\Gabinete\\Sigilosos):
        # os autos em segredo não podem ir para a IA nem para a nuvem.
        dentro = self.raiz / "Sigilosos"
        _pdf(dentro / "Lote 1" / f"{SIGILOSO}.pdf", ["DEPOIMENTO DA VÍTIMA - SEGREDO"])
        cfg = config.Config(Path(self.dir.name) / "config.ini")
        cfg.definir("geral", "pasta_acervo", str(self.raiz))
        cfg.definir("geral", "pasta_sigilosos", str(dentro))
        self.assertTrue(cfg.conflito_de_pastas())
        self.assertNotIn(SIGILOSO, mcp_servidor.Acervo(self.raiz, sigilosos=dentro).pdfs())
        preparo.atualizar_contexto(cfg, extrair_texto=True)
        self.assertNotIn(SIGILOSO, (self.raiz / "INDICE.md").read_text(encoding="utf-8"))
        self.assertFalse((self.raiz / "_ia" / "texto" / f"{SIGILOSO}.txt").exists())
        nuvem.espelhar(self.raiz, Path(self.dir.name) / "Nuvem", sigilosos=dentro)
        self.assertFalse(list((Path(self.dir.name) / "Nuvem").rglob(f"{SIGILOSO}*")))

    def test_sigiloso_retirado_a_mao_some_do_texto_e_da_nuvem(self):
        # A separação falhou, o lote terminou (texto extraído, espelho feito) e o
        # usuário levou o PDF à mão para a pasta de sigilosos.
        pdf = _pdf(self.raiz / "Processos" / "Lote 1" / f"{SIGILOSO}.pdf",
                   ["DEPOIMENTO DA VÍTIMA - SEGREDO"])
        nuvem_dir = Path(self.dir.name) / "Nuvem"
        preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=True)
        texto = self.raiz / "_ia" / "texto" / f"{SIGILOSO}.txt"
        self.assertTrue(texto.exists())
        nuvem.espelhar(self.raiz, nuvem_dir, sigilosos=self.sigilosos)
        self.assertTrue(list(nuvem_dir.rglob(f"{SIGILOSO}*")))

        (self.sigilosos / "Lote 1").mkdir(parents=True)
        pdf.replace(self.sigilosos / "Lote 1" / pdf.name)
        cfg = config.Config(Path(self.dir.name) / "config.ini")
        cfg.definir("geral", "pasta_acervo", str(self.raiz))
        cfg.definir("geral", "pasta_sigilosos", str(self.sigilosos))
        preparo.atualizar_contexto(cfg, extrair_texto=False)    # o preparo rápido
        self.assertFalse(texto.exists())
        nuvem.espelhar(self.raiz, nuvem_dir, sigilosos=self.sigilosos)
        self.assertEqual(list(nuvem_dir.rglob(f"{SIGILOSO}*")), [])
        self.assertTrue(list(nuvem_dir.rglob(f"{NUM}.pdf")))    # o resto continua lá

    def test_copia_esquecida_no_acervo_nao_e_servida(self):
        # Copiou para a pasta de sigilosos, mas não conseguiu apagar do acervo.
        _pdf(self.raiz / "Processos" / "Lote 1" / f"{SIGILOSO}.pdf", ["SEGREDO"])
        _pdf(self.sigilosos / "Lote 1" / f"{SIGILOSO}.pdf", ["SEGREDO"])
        _docx(self.raiz / "Transcricoes" / f"{SIGILOSO}.docx", ["AUDIÊNCIA EM SEGREDO"])
        ac = mcp_servidor.Acervo(self.raiz, sigilosos=self.sigilosos)
        self.assertEqual(set(ac.pdfs()), {NUM})
        self.assertEqual(set(ac.transcricoes()), {NUM})
        with self.assertRaises(LookupError):
            ac.ler_processo(SIGILOSO)


class TestTextosParaIA(BaseAcervo):
    def test_documento_de_cada_pagina_no_eproc(self):
        pdf = _pdf(self.raiz / "Processos" / "Lote 2" / "0700777-04.2025.8.02.0001.pdf",
                   ["PROCESSO 0700777-04.2025.8.02.0001 — eProc", "Petição inicial",
                    "continua", "Despacho"],
                   [[1, "Capa — dados do processo", 1],
                    [1, "Evento 1 — PETIÇÃO INICIAL — INIC1 (03/02/2025)", 2],
                    [1, "Evento 3 — DESPACHO — DESPADEC1 (10/02/2025)", 4]])
        texto = textos.texto_pdf(pdf)
        self.assertIn("=== [fl. 3] ===\n[documento: Evento 1 — PETIÇÃO INICIAL — INIC1 "
                      "(03/02/2025)]\ncontinua", texto)
        self.assertIn("=== [fl. 4] ===\n[documento: Evento 3 — DESPACHO", texto)
        self.assertEqual(textos.recortar_paginas(texto, 3, 3).count("=== [fl."), 1)

    def test_regras_para_a_ia(self):
        preparo.atualizar_contexto(raiz=self.raiz)
        contexto = (self.raiz / "CLAUDE.md").read_text(encoding="utf-8")
        skill = (self.raiz / ".claude/skills/acervo-judicial/SKILL.md").read_text(encoding="utf-8")
        for texto in (contexto, skill, mcp_servidor.INSTRUCOES):
            self.assertIn("eProc", texto)
            self.assertIn("material das partes", texto)
        self.assertIn("evento e o rótulo", contexto)
        # O rodapé dizia que o arquivo era refeito a cada lote (não é)
        self.assertNotIn("refeito a cada lote", contexto)
        self.assertIn("O programa não o altera", contexto)


class TestClaude(BaseAcervo):
    def test_registra_mcp_mesclando_e_com_copia(self):
        arq = Path(self.dir.name) / "Claude" / "claude_desktop_config.json"
        arq.parent.mkdir()
        arq.write_text(json.dumps({"mcpServers": {"outro": {"command": "x"}},
                                   "coworkScheduledTasksEnabled": True}), encoding="utf-8")
        self.assertEqual(claude.registrar_mcp(self.raiz, [arq]), [arq])
        dados = json.loads(arq.read_text(encoding="utf-8"))
        self.assertEqual(set(dados["mcpServers"]), {"outro", claude.NOME_MCP})
        self.assertTrue(dados["coworkScheduledTasksEnabled"])
        entrada = dados["mcpServers"][claude.NOME_MCP]
        self.assertEqual(entrada["args"][:3], ["-s", "-m", "app.compartilhar.mcp_servidor"])
        self.assertTrue(list(arq.parent.glob("*antes-do-assessor*")))
        self.assertEqual(claude.registrar_mcp(self.raiz, [arq]), [])   # nada mudou

    def test_json_invalido_nao_e_sobrescrito(self):
        arq = Path(self.dir.name) / "claude_desktop_config.json"
        arq.write_text("{ isto não é json", encoding="utf-8")
        with self.assertRaises(ValueError):
            claude.registrar_mcp(self.raiz, [arq])
        self.assertEqual(arq.read_text(encoding="utf-8"), "{ isto não é json")

    def test_links_do_cowork_codificados(self):
        url = claude.url_cowork(Path("/tmp/Acervo Área"), "Leia o CLAUDE.md")
        self.assertTrue(url.startswith("claude://cowork/new?folder="))
        self.assertIn("%C3%81rea", url)
        self.assertNotIn(" ", url)

    def test_plugin_do_cowork(self):
        z = claude.gerar_plugin_cowork(Path(self.dir.name))
        with zipfile.ZipFile(z) as arq:
            self.assertEqual(set(arq.namelist()),
                             {".claude-plugin/plugin.json", "skills/acervo-judicial/SKILL.md"})
            self.assertEqual(json.loads(arq.read(".claude-plugin/plugin.json"))["name"],
                             "acervo-judicial")

    def test_conectar_sem_o_app_nao_o_faz_parecer_instalado(self):
        # Regressão: registrar_mcp cria %APPDATA%\\Claude, e a pasta servia de
        # prova de que o Claude Desktop estava instalado.
        base = Path(self.dir.name)
        ambiente = {"APPDATA": str(base / "Roaming"), "LOCALAPPDATA": str(base / "Local")}
        with mock.patch.dict(os.environ, ambiente):
            self.assertFalse(claude.claude_desktop_instalado())
            self.assertTrue(claude.registrar_mcp(self.raiz))
            self.assertFalse(claude.claude_desktop_instalado())
            (base / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
            self.assertTrue(claude.claude_desktop_instalado())

    def _terminal(self, pasta: Path, exe: str, wt: str | None):
        with mock.patch.object(claude.sistema, "NO_WINDOWS", True), \
                mock.patch("shutil.which", return_value=wt), \
                mock.patch("subprocess.Popen") as popen:
            claude._abrir_terminal(pasta, Path(exe), "Claude Code - Acervo")
        return popen.call_args

    def test_console_classico_sem_aspas_escapadas(self):
        # Regressão: em lista, o Python escapava as aspas internas com \\",
        # que o cmd.exe não entende - o Claude Code não abria sem o Windows
        # Terminal. E a pasta de rede ia para C:\\Windows (o cmd não a aceita).
        exe = r"C:\Users\Ana & Rui\.local\bin\claude.exe"
        for pasta in (r"C:\Users\Ana & Rui\Acervo", r"\\servidor\gabinete\Acervo"):
            chamada = self._terminal(Path(pasta), exe, None)
            linha = chamada.args[0]
            self.assertIsInstance(linha, str)
            self.assertNotIn('\\"', linha)
            self.assertNotIn("cwd", chamada.kwargs)
            # Regra do cmd /s /k: tira a primeira e a última aspa, mantém o resto
            comando = linha.split(" /s /k ", 1)[1]
            self.assertTrue(comando.startswith('"') and comando.endswith('"'))
            self.assertEqual(comando[1:-1],
                             f'title Claude Code - Acervo& pushd "{Path(pasta)}" && "{exe}"')

    def test_windows_terminal_entra_na_pasta_de_rede(self):
        chamada = self._terminal(Path(r"\\servidor\gabinete\Acervo"), r"C:\c\claude.exe",
                                 r"C:\wt.exe")
        args = chamada.args[0]
        self.assertNotIn("-d", args)
        self.assertEqual(args[-5:], ["/k", "pushd", str(Path(r"\\servidor\gabinete\Acervo")),
                                     "&&", r"C:\c\claude.exe"])
        args = self._terminal(Path("C:/Acervo"), r"C:\c\claude.exe", r"C:\wt.exe").args[0]
        self.assertIn("-d", args)

    def test_achar_claude_code_pelo_caminho_nativo(self):
        casa = Path(self.dir.name) / "casa"
        exe = casa / ".local" / "bin" / "claude.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        with mock.patch("shutil.which", return_value=None), \
                mock.patch("pathlib.Path.home", return_value=casa), \
                mock.patch.dict(os.environ, {"APPDATA": "", "LOCALAPPDATA": ""}):
            self.assertEqual(claude.achar_claude_code(), exe)


class TestChatGPT(BaseAcervo):
    def test_config_toml_do_codex(self):
        arq = Path(self.dir.name) / ".codex" / "config.toml"
        arq.parent.mkdir()
        arq.write_text('model = "x"\n\n[mcp_servers.outro]\ncommand = "y"\n\n'
                       f"[mcp_servers.{chatgpt.NOME_MCP}]\ncommand = \"velho\"\n"
                       f"[mcp_servers.{chatgpt.NOME_MCP}.env]\nA = \"1\"\n", encoding="utf-8")
        chatgpt.registrar_mcp_codex(Path("C:/Acervo d'Ávila"), arq)
        dados = tomllib.loads(arq.read_text(encoding="utf-8"))
        self.assertEqual(dados["model"], "x")
        self.assertIn("outro", dados["mcp_servers"])
        nosso = dados["mcp_servers"][chatgpt.NOME_MCP]
        self.assertTrue(nosso["enabled"])
        self.assertIn("--pasta", nosso["args"])
        self.assertNotIn("A", nosso["env"])
        self.assertTrue(chatgpt.mcp_codex_registrado(arq))
        self.assertTrue(chatgpt.remover_mcp_codex(arq))
        self.assertFalse(chatgpt.mcp_codex_registrado(arq))
        self.assertIn("outro", tomllib.loads(arq.read_text(encoding="utf-8"))["mcp_servers"])

    def test_conector_do_codex_confere_a_pasta(self):
        # Regressão: depois de trocar a pasta do acervo, a tela seguia dizendo
        # "acervo conectado" ao ChatGPT, com o config.toml no acervo antigo.
        arq = Path(self.dir.name) / ".codex" / "config.toml"
        chatgpt.registrar_mcp_codex(self.raiz, arq)
        self.assertTrue(chatgpt.mcp_codex_registrado(arq, pasta_acervo=self.raiz))
        self.assertFalse(chatgpt.mcp_codex_registrado(arq, pasta_acervo=Path(self.dir.name) / "Outro"))
        with mock.patch.object(chatgpt, "arquivo_config_codex", return_value=arq):
            self.assertTrue(chatgpt.estado(self.raiz)["mcp"])
            self.assertFalse(chatgpt.estado(Path(self.dir.name) / "Outro")["mcp"])

    def test_codex_ausente_aponta_botao_que_existe(self):
        with mock.patch.object(chatgpt, "achar_codex", return_value=None):
            with self.assertRaises(FileNotFoundError) as ctx:
                chatgpt.abrir_codex(self.raiz)
        self.assertIn("“Abrir no ChatGPT Work”", str(ctx.exception))

    def test_pacote_respeita_texto_desligado(self):
        cfg = config.Config(Path(self.dir.name) / "config.ini")
        cfg.definir("compartilhar", "incluir_texto", False)
        _, arq_zip = chatgpt.gerar_pacote(self.raiz, Path(self.dir.name) / "saida", cfg=cfg)
        nomes = set(zipfile.ZipFile(arq_zip).namelist())
        self.assertIn(f"autos/{NUM}.pdf", nomes)
        self.assertFalse(any(n.startswith("texto/") for n in nomes))
        self.assertFalse((self.raiz / "_ia" / "texto" / f"{NUM}.txt").exists())

    def test_toml_invalido_nao_e_tocado(self):
        arq = Path(self.dir.name) / "config.toml"
        arq.write_text("isto = [nao fecha", encoding="utf-8")
        with self.assertRaises(ValueError):
            chatgpt.registrar_mcp_codex(self.raiz, arq)

    def test_pacote(self):
        pasta, arq_zip = chatgpt.gerar_pacote(self.raiz, Path(self.dir.name) / "saida")
        nomes = set(zipfile.ZipFile(arq_zip).namelist())
        self.assertIn(f"autos/{NUM}.pdf", nomes)
        self.assertIn(f"texto/{NUM}.txt", nomes)
        self.assertIn(f"audiencias/{NUM}.docx", nomes)
        self.assertIn("LEIA-ME - instrucoes.md", nomes)
        self.assertFalse(any("Produtos" in n for n in nomes))

    def test_link_do_work(self):
        self.assertTrue(chatgpt.url_work(Path("/tmp/A B")).startswith("codex://threads/new?path="))


class TestNuvem(BaseAcervo):
    def test_espelha_so_o_que_mudou_e_nunca_apaga(self):
        destino = Path(self.dir.name) / "OneDrive"
        copiados, iguais = nuvem.espelhar(self.raiz, destino)
        self.assertGreater(copiados, 0)
        espelho = destino / nuvem.SUBPASTA
        self.assertTrue((espelho / "Processos" / "Lote 1" / f"{NUM}.pdf").exists())
        self.assertFalse((espelho / "Transcricoes" / f"~${NUM}.docx").exists())
        extra = espelho / "do usuario.txt"
        extra.write_text("fica", encoding="utf-8")
        self.assertEqual(nuvem.espelhar(self.raiz, destino), (0, copiados))
        self.assertTrue(extra.exists())

    def test_detectar_onedrive(self):
        pasta = Path(self.dir.name) / "OneDrive - Tribunal"
        pasta.mkdir()
        with mock.patch.dict(os.environ, {"OneDriveCommercial": str(pasta)}):
            self.assertIn(pasta, nuvem.detectar().values())


if __name__ == "__main__":
    unittest.main()
