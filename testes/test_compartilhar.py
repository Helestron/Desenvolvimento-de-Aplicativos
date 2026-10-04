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

from helestron.compartilhar import chatgpt, claude, mcp_servidor, nuvem, preparo, textos
from helestron.nucleo import caminhos, cnj, config, sigilo

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
        self.assertEqual(r[0]["result"]["serverInfo"]["name"], "helestron")
        self.assertEqual(r[0]["result"]["serverInfo"]["title"], "Helestron — acervo judicial")
        self.assertIn("Helestron", r[0]["result"]["instructions"])
        self.assertNotIn("Assessor", json.dumps(r, ensure_ascii=False))
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

    def test_sem_pasta_usa_o_acervo_da_configuracao(self):
        # "python -I -m helestron mcp" sem --pasta: o acervo dos Ajustes, lido
        # sem criar o config.ini (o servidor roda a pedido do Claude).
        lidos, servidos = [], []
        falsa = mock.Mock(pasta_acervo=self.raiz)
        with mock.patch.object(config, "carregar",
                               side_effect=lambda criar=True: lidos.append(criar) or falsa), \
                mock.patch.object(mcp_servidor, "servir",
                                  side_effect=lambda raiz, saida=None: servidos.append(raiz)), \
                mock.patch.object(mcp_servidor.os, "dup2"), \
                mock.patch.object(mcp_servidor.sys, "stdout", io.StringIO()):
            self.assertEqual(mcp_servidor.main([]), 0)
        self.assertEqual((lidos, servidos), ([False], [self.raiz]))

    def test_canal_do_protocolo_fechado_no_fim(self):
        # A cópia do descritor 1 (o canal das respostas) é fechada quando a
        # conversa acaba: nada de "unclosed file" (ResourceWarning).
        import gc
        import warnings

        canais = []
        with warnings.catch_warnings(record=True) as avisos, \
                mock.patch.object(mcp_servidor, "servir",
                                  side_effect=lambda raiz, saida=None: canais.append(saida)), \
                mock.patch.object(mcp_servidor.os, "dup2"), \
                mock.patch.object(mcp_servidor.sys, "stdout", io.StringIO()):
            warnings.simplefilter("always")
            self.assertEqual(mcp_servidor.main(["--pasta", str(self.raiz)]), 0)
            gc.collect()
        self.assertEqual(len(canais), 1)
        self.assertTrue(canais[0].closed)
        self.assertEqual([str(a.message) for a in avisos
                          if issubclass(a.category, ResourceWarning)], [])

    def test_canal_fechado_tambem_quando_a_conversa_falha(self):
        canais = []

        def servir(raiz, saida=None):
            canais.append(saida)
            raise BrokenPipeError("o outro lado fechou")

        with mock.patch.object(mcp_servidor, "servir", side_effect=servir), \
                mock.patch.object(mcp_servidor.os, "dup2"), \
                mock.patch.object(mcp_servidor.sys, "stdout", io.StringIO()):
            with self.assertRaises(BrokenPipeError):
                mcp_servidor.main(["--pasta", str(self.raiz)])
        self.assertTrue(canais[0].closed)

    def test_processo_de_verdade_responde_pelo_stdout(self):
        # Como o Claude Desktop o chama: um processo, as mensagens pelo stdin
        # e as respostas pelo stdout. O print de biblioteca vai para o stderr,
        # as respostas chegam inteiras (o fechamento do canal não as perde) e
        # nenhum ResourceWarning aparece no fim (-X dev os mostra).
        import subprocess
        import sys

        casa = Path(self.dir.name) / "casa"
        casa.mkdir()
        env = dict(os.environ, HELESTRON_LOCAL=str(casa / "local"),
                   HELESTRON_DADOS=str(casa / "dados"), HOME=str(casa),
                   APPDATA=str(casa), LOCALAPPDATA=str(casa))
        mensagens = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        r = subprocess.run(
            [sys.executable, "-X", "dev", "-m", "helestron", "mcp", "--pasta", str(self.raiz)],
            input="".join(json.dumps(m) + "\n" for m in mensagens).encode(),
            capture_output=True, cwd=str(Path(__file__).resolve().parents[1]), env=env,
            timeout=120)
        erros = r.stderr.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, erros)
        linhas = [json.loads(l) for l in r.stdout.decode("utf-8").splitlines() if l.strip()]
        self.assertEqual([x["id"] for x in linhas], [1, 2], erros)
        self.assertEqual(linhas[0]["result"]["serverInfo"]["name"], "helestron")
        self.assertNotIn("ResourceWarning", erros)

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

    def test_a_ia_le_helestron(self):
        # Tudo o que a IA lê traz o nome novo, o conector "helestron" e o
        # botão como ele se chama na tela Compartilhar.
        preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        for nome in ("CLAUDE.md", "AGENTS.md", "INDICE.md",
                     ".claude/skills/acervo-judicial/SKILL.md"):
            texto = (self.raiz / nome).read_text(encoding="utf-8")
            self.assertNotIn("Assessor", texto, nome)
        contexto = (self.raiz / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("# Acervo judicial — Helestron", contexto)
        self.assertIn('o conector "helestron" (MCP)', contexto)
        self.assertIn("“Preparar acervo para a IA”", contexto)
        z = claude.gerar_plugin_cowork(Path(self.dir.name))
        with zipfile.ZipFile(z) as arq:
            manifesto = json.loads(arq.read(".claude-plugin/plugin.json"))
        self.assertEqual(manifesto["author"], {"name": "Helestron"})
        self.assertIn("Helestron", manifesto["description"])
        self.assertEqual(nuvem.SUBPASTA, "Helestron - Acervo")

    def test_idempotente_e_respeita_edicao_do_usuario(self):
        preparo.atualizar_contexto(raiz=self.raiz)
        (self.raiz / "CLAUDE.md").write_text("minhas regras", encoding="utf-8")
        rel = preparo.atualizar_contexto(raiz=self.raiz)
        self.assertEqual(rel.arquivos, [])
        self.assertEqual(rel.textos_novos, 0)
        self.assertEqual((self.raiz / "CLAUDE.md").read_text(encoding="utf-8"), "minhas regras")

    def test_regra_do_sigilo_segue_a_configuracao(self):
        # Regressão: o CLAUDE.md/AGENTS.md dizia sempre que os sigilosos "não
        # estão nesta pasta" - falso com a separação desligada.
        def contexto(cfg):
            for nome in ("CLAUDE.md", "AGENTS.md"):
                (self.raiz / nome).unlink(missing_ok=True)
            preparo.atualizar_contexto(cfg, raiz=self.raiz, extrair_texto=False)
            textos_ = [(self.raiz / n).read_text(encoding="utf-8") for n in ("CLAUDE.md", "AGENTS.md")]
            self.assertEqual(textos_[0], textos_[1])
            return textos_[0]

        separados = "segredo de justiça não estão nesta pasta"
        self.assertIn(separados, contexto(None))        # sem configuração: o padrão, que separa
        cfg = config.Config(Path(self.dir.name) / "config.ini")
        cfg.definir("geral", "pasta_sigilosos", str(Path(self.dir.name) / "Sigilosos"))
        self.assertIn(separados, contexto(cfg))
        cfg.definir("download", "separar_sigilosos", False)
        texto = contexto(cfg)
        self.assertNotIn(separados, texto)
        self.assertIn("**Esta pasta pode conter processos em segredo de justiça**", texto)
        self.assertIn("sem autorização expressa do\n   magistrado", texto)
        self.assertRegex(texto, r"\n5\. \*\*Esta pasta[^\n]*\n(   \S[^\n]*\n)+6\. ")
        # Criado o arquivo, o programa não o reescreve (o usuário pode tê-lo editado)
        cfg.definir("download", "separar_sigilosos", True)
        preparo.atualizar_contexto(cfg, raiz=self.raiz, extrair_texto=False)
        self.assertNotIn(separados, (self.raiz / "CLAUDE.md").read_text(encoding="utf-8"))

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

    def test_espelho_antigo_do_assessor_tambem_perde_o_sigiloso(self):
        """Quem usava o espelho do Assessor Integrado na mesma nuvem: a cópia
        antiga ("Assessor Integrado - Acervo") de processo que depois foi para a
        pasta de sigilosos também sai - ela continua ao alcance dos conectores."""
        nuvem_dir = Path(self.dir.name) / "Nuvem"
        antiga = nuvem_dir / "Assessor Integrado - Acervo" / "Processos" / "Lote 1"
        _pdf(antiga / f"{SIGILOSO}.pdf", ["DEPOIMENTO DA VÍTIMA - SEGREDO"])
        (antiga / f"{SIGILOSO}.txt").write_text("SEGREDO", encoding="utf-8")
        _pdf(antiga / f"{NUM}.pdf", ["Petição inicial"])
        _pdf(self.sigilosos / "Lote 1" / f"{SIGILOSO}.pdf", ["DEPOIMENTO DA VÍTIMA - SEGREDO"])
        self.assertIn("Assessor Integrado - Acervo", nuvem.SUBPASTAS_ANTIGAS)
        nuvem.espelhar(self.raiz, nuvem_dir, sigilosos=self.sigilosos)
        self.assertEqual(list(nuvem_dir.rglob(f"{SIGILOSO}*")), [])
        self.assertTrue((antiga / f"{NUM}.pdf").exists())     # o resto não é apagado

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


class TestSigiloUnico(BaseAcervo):
    """Uma regra só de processo sigiloso para todo o compartilhamento: autos,
    transcrição ou gravação na pasta de sigilosos, OU a pauta marcando o
    segredo de justiça. Antes, só o PDF na pasta de sigilosos contava: o
    processo que a pauta dava como sigiloso (o segredo decretado depois do
    download) e o que tinha a audiência transcrita como sigilosa continuavam
    no INDICE.md, no MCP, em _ia/texto, no pacote e na nuvem."""

    def setUp(self):
        super().setUp()
        base = Path(self.dir.name)
        self.sigilosos = base / "Sigilosos"
        self.pauta = base / "local" / "pauta.sqlite3"
        p = mock.patch.object(caminhos, "ARQUIVO_PAUTA", self.pauta)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(sigilo.esquecer_pauta)
        self.cfg = config.Config(base / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.raiz))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.sigilosos))
        self.lote = self.raiz / "Processos" / "Lote 1"
        self.pdf = _pdf(self.lote / f"{SIGILOSO}.pdf", ["DEPOIMENTO DA VÍTIMA - SEGREDO"])
        (self.lote / "_controle").mkdir(exist_ok=True)
        (self.lote / "_controle" / f"{SIGILOSO}_capa.txt").write_text("capa", encoding="utf-8")
        self.trans = _docx(self.raiz / "Transcricoes" / f"{SIGILOSO}.docx", ["AUDIÊNCIA EM SEGREDO"])
        # o texto e o espelho de quando ele ainda era público
        texto = self.raiz / "_ia" / "texto" / f"{SIGILOSO}.txt"
        texto.parent.mkdir(parents=True)
        texto.write_text("=== [fl. 1] ===\nSEGREDO\n", encoding="utf-8")
        self.nuvem_dir = base / "Nuvem"
        _pdf(self.nuvem_dir / nuvem.SUBPASTA / "Processos" / "Lote 1" / f"{SIGILOSO}.pdf",
             ["SEGREDO"])

    def marcar_na_pauta(self, numero=SIGILOSO):
        from testes.test_nucleo import pauta_com_sigiloso

        self.pauta.parent.mkdir(parents=True, exist_ok=True)
        pauta_com_sigiloso(self.pauta, cnj.ler(numero))

    def assert_fora_da_ia(self):
        ac = mcp_servidor.Acervo(self.raiz, sigilosos=self.sigilosos)
        self.assertEqual(set(ac.pdfs()), {NUM}, "o MCP serve os autos do sigiloso")
        self.assertEqual(set(ac.transcricoes()), {NUM})
        with self.assertRaises(LookupError):
            ac.ler_processo(SIGILOSO)
        self.assertNotIn(SIGILOSO, ac.listar_acervo())
        self.assertEqual(ac.buscar("SEGREDO"), "Nenhuma ocorrência de 'SEGREDO'.")
        preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertNotIn(SIGILOSO, (self.raiz / "INDICE.md").read_text(encoding="utf-8"))
        self.assertFalse((self.raiz / "_ia" / "texto" / f"{SIGILOSO}.txt").exists())
        nuvem.espelhar(self.raiz, self.nuvem_dir, sigilosos=self.sigilosos)
        self.assertEqual(list(self.nuvem_dir.rglob(f"{SIGILOSO}*")), [])
        self.assertTrue(list(self.nuvem_dir.rglob(f"{NUM}.pdf")))
        _pasta, arq_zip = chatgpt.gerar_pacote(self.raiz, Path(self.dir.name) / "saida",
                                               cfg=self.cfg)
        nomes = zipfile.ZipFile(arq_zip).namelist()
        self.assertFalse([n for n in nomes if SIGILOSO in n], nomes)
        indice = zipfile.ZipFile(arq_zip).read("INDICE.md").decode("utf-8")
        self.assertNotIn(SIGILOSO, indice)

    def test_sigilo_da_pauta_tira_o_processo_da_ia_e_do_acervo(self):
        self.marcar_na_pauta()
        self.assert_fora_da_ia()
        # E, com a separação ligada (o padrão), a cópia sai do acervo, como no
        # download: o Claude Code e o Cowork abrem a pasta inteira, e o
        # CLAUDE.md lhes diz que os sigilosos "não estão nesta pasta".
        self.assertEqual(sorted(p.name for p in self.raiz.rglob(f"{SIGILOSO}*")), [])
        self.assertTrue((self.sigilosos / "Lote 1" / f"{SIGILOSO}.pdf").exists())
        self.assertTrue((self.sigilosos / "Lote 1" / "_controle" / f"{SIGILOSO}_capa.txt").exists())
        self.assertTrue((self.sigilosos / "Transcricoes" / f"{SIGILOSO}.docx").exists())
        self.assertIn("não estão nesta pasta", (self.raiz / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertTrue((self.lote / f"{NUM}.pdf").exists(), "o público continua no acervo")

    def test_preparo_diz_quantos_sigilosos_levou(self):
        self.marcar_na_pauta()
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=False)
        self.assertEqual((rel.sigilosos_levados, rel.sigilosos_no_acervo), (1, []))
        self.assertIn("1 processo sigiloso levado para a pasta dos sigilosos", rel.resumo)
        self.assertEqual(rel.processos, 1)

    def test_transcricao_sigilosa_tira_os_autos_da_ia(self):
        # A audiência foi transcrita como sigilosa (pela pauta ou pelo
        # interruptor): os autos que ficaram no acervo também são sigilosos.
        self.trans.unlink()
        _docx(self.sigilosos / "Transcricoes" / f"{SIGILOSO}.docx", ["AUDIÊNCIA EM SEGREDO"])
        self.assert_fora_da_ia()
        self.assertFalse(self.pdf.exists())

    def test_com_a_separacao_desligada_fica_no_acervo_mas_nao_vai_para_a_ia(self):
        self.cfg.definir("download", "separar_sigilosos", False)
        self.marcar_na_pauta()
        self.assert_fora_da_ia()
        self.assertTrue(self.pdf.exists())
        self.assertIn("pode conter processos em segredo de justiça",
                      (self.raiz / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_copia_presa_no_acervo_trava_o_compartilhamento(self):
        from helestron.download import motor

        self.marcar_na_pauta()
        original = motor._mover

        def preso(origem, destino, *a):
            if Path(origem) == self.pdf:
                raise PermissionError(13, "O arquivo está aberto em outro programa")
            return original(origem, destino, *a)

        with mock.patch.object(motor, "_mover", preso), self.assertLogs("compartilhar", "ERROR"):
            rel = preparo.atualizar_contexto(self.cfg, extrair_texto=False)
            self.assertEqual(rel.sigilosos_no_acervo, [self.pdf])
            self.assertTrue(any(SIGILOSO in e for e in rel.erros))
            # o índice não o lista, mas o pacote recusa: nada se compartilha
            self.assertNotIn(SIGILOSO, (self.raiz / "INDICE.md").read_text(encoding="utf-8"))
            with self.assertRaises(preparo.SigilosoNoAcervo) as caso:
                chatgpt.gerar_pacote(self.raiz, Path(self.dir.name) / "saida", cfg=self.cfg)
        self.assertIn(f"{SIGILOSO}.pdf", str(caso.exception))
        self.assertIn("mova-o para a pasta dos sigilosos", str(caso.exception))
        self.assertTrue(self.pdf.exists())
        self.assertFalse((self.raiz / "Transcricoes" / f"{SIGILOSO}.docx").exists())
        # fechado o arquivo, o próximo preparo o leva
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=False)
        self.assertEqual(rel.sigilosos_no_acervo, [])
        self.assertFalse(self.pdf.exists())

    def test_servidor_mcp_le_a_pauta_sem_alterar_nada(self):
        """O MCP roda em outro processo, a pedido do Claude Desktop: consulta a
        pauta do programa (só leitura) e nunca move nem apaga arquivo."""
        self.marcar_na_pauta()
        ac = mcp_servidor.Acervo(self.raiz, sigilosos=self.sigilosos)
        self.assertNotIn(SIGILOSO, ac.pdfs())
        self.assertTrue(self.pdf.exists())
        self.assertNotIn(SIGILOSO, mcp_servidor.Acervo(self.raiz, sigilosos=None).pdfs())
        self.assertIn(SIGILOSO, mcp_servidor.Acervo(self.raiz, sigilosos=None, pauta=None).pdfs())


class TestRecorte(BaseAcervo):
    """O que não é acervo, mesmo estando debaixo dele: as pastas do programa
    (registros, runtime, senhas) e o que só chega lá por link ou junção que
    leva para fora."""

    OUTRO = "0700555-25.2024.8.02.0001"

    def setUp(self):
        super().setUp()
        self.fora = Path(self.dir.name) / "Fora"
        _pdf(self.fora / f"{self.OUTRO}.pdf", ["AUTOS DE FORA DO ACERVO"])
        self.nuvem = Path(self.dir.name) / "Nuvem"

    def _ligar(self, link: Path, alvo: Path) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(alvo, link, target_is_directory=alvo.is_dir())
        except (OSError, NotImplementedError) as erro:   # Windows sem o modo de desenvolvedor
            self.skipTest(f"sem permissão para criar link simbólico: {erro}")

    def _espelhados(self) -> list[str]:
        nuvem.espelhar(self.raiz, self.nuvem, sigilosos=None)
        return [p.name for p in (self.nuvem / nuvem.SUBPASTA).rglob("*") if p.is_file()]

    def test_pastas_do_programa_dentro_do_acervo_ficam_de_fora(self):
        # Acervo apontado (por engano) para uma pasta acima da do programa
        logs, programa, local = self.raiz / "Logs", self.raiz / "Programs", self.raiz / "Local"
        _pdf(logs / "diagnostico" / f"{self.OUTRO}.pdf", ["TELA DO PORTAL"])
        _docx(programa / "Lib" / f"{SIGILOSO}.docx", ["RASCUNHO"])
        (local / "perfis").mkdir(parents=True)
        (local / "credenciais.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(mcp_servidor.caminhos, "LOGS", logs), \
                mock.patch.object(mcp_servidor.caminhos, "INSTALADO", True), \
                mock.patch.object(mcp_servidor.caminhos, "INSTALACAO", programa), \
                mock.patch.object(mcp_servidor.caminhos, "LOCAL", local):
            ac = mcp_servidor.Acervo(self.raiz, sigilosos=None)
            self.assertEqual(set(ac.pdfs()), {NUM})
            self.assertEqual(set(ac.transcricoes()), {NUM})
            espelhados = self._espelhados()
        self.assertIn(f"{NUM}.pdf", espelhados)
        for nome in (f"{self.OUTRO}.pdf", f"{SIGILOSO}.docx", "credenciais.json"):
            self.assertNotIn(nome, espelhados)

    def test_link_de_arquivo_para_fora_do_acervo_fica_de_fora(self):
        self._ligar(self.raiz / "Processos" / "Lote 1" / f"{self.OUTRO}.pdf",
                    self.fora / f"{self.OUTRO}.pdf")
        self.assertEqual(set(mcp_servidor.Acervo(self.raiz, sigilosos=None).pdfs()), {NUM})
        self.assertNotIn(f"{self.OUTRO}.pdf", self._espelhados())

    def test_link_de_pasta_ou_juncao_para_fora_do_acervo_fica_de_fora(self):
        # No Windows, a junção é seguida pela varredura; o Recorte confere o
        # caminho real de cada arquivo.
        self._ligar(self.raiz / "Processos" / "Lote 2", self.fora)
        recorte = mcp_servidor.Recorte(self.raiz)
        self.assertFalse(recorte.aceita(self.raiz / "Processos" / "Lote 2" / f"{self.OUTRO}.pdf"))
        self.assertTrue(recorte.aceita(self.raiz / "Processos" / "Lote 1" / f"{NUM}.pdf"))
        self.assertEqual(set(mcp_servidor.Acervo(self.raiz, sigilosos=None).pdfs()), {NUM})
        self.assertNotIn(f"{self.OUTRO}.pdf", self._espelhados())

    def test_link_dentro_do_acervo_vale_mas_nao_abre_a_pasta_de_sigilosos(self):
        dentro = self.raiz / "Sigilosos"
        _pdf(dentro / "Lote 1" / f"{SIGILOSO}.pdf", ["SEGREDO"])
        self._ligar(self.raiz / "Processos" / "Atalho", dentro / "Lote 1")
        self._ligar(self.raiz / "Processos" / "Copia" / f"{NUM}.pdf",
                    self.raiz / "Processos" / "Lote 1" / f"{NUM}.pdf")
        recorte = mcp_servidor.Recorte(self.raiz, dentro)
        self.assertFalse(recorte.aceita(self.raiz / "Processos" / "Atalho" / f"{SIGILOSO}.pdf"))
        self.assertTrue(recorte.aceita(self.raiz / "Processos" / "Copia" / f"{NUM}.pdf"))


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
        self.assertEqual(claude.NOME_MCP, "helestron")
        self.assertEqual(entrada["args"][-5:], ["-m", "helestron", "mcp", "--pasta",
                                                str(self.raiz.resolve())])
        self.assertTrue(list(arq.parent.glob("*antes-do-helestron*")))
        self.assertEqual(claude.registrar_mcp(self.raiz, [arq]), [])   # nada mudou

    def test_entrada_da_instalacao_usa_o_python_do_programa_isolado(self):
        # Instalado: o python.exe da pasta do programa com -I (PYTHONPATH,
        # PYTHONHOME e a pasta "site" do usuário não entram) e nenhuma
        # variável de ambiente - nem o PYTHONNOUSERSITE da versão anterior.
        programa = Path(self.dir.name) / "Programs" / "Helestron"
        programa.mkdir(parents=True)
        (programa / "python.exe").write_bytes(b"")
        with mock.patch.object(claude.caminhos, "INSTALADO", True), \
                mock.patch.object(claude.caminhos, "INSTALACAO", programa):
            entrada = claude.entrada_mcp(self.raiz)
            bloco = chatgpt.bloco_toml(self.raiz)
        self.assertEqual(entrada, {"command": str(programa / "python.exe"),
                                   "args": ["-I", "-m", "helestron", "mcp", "--pasta",
                                            str(self.raiz.resolve())]})
        self.assertNotIn("PYTHONNOUSERSITE", json.dumps(entrada))
        dados = tomllib.loads(bloco)["mcp_servers"][chatgpt.NOME_MCP]
        self.assertEqual(dados["args"][:4], ["-I", "-m", "helestron", "mcp"])
        self.assertNotIn("env", dados)

    def test_registrar_tira_o_conector_da_versao_anterior(self):
        arq = Path(self.dir.name) / "claude_desktop_config.json"
        velho = {"command": "C:/AssessorIntegrado/runtime/python/python.exe", "args": []}
        arq.write_text(json.dumps({"mcpServers": {"assessor-integrado": velho,
                                                  "outro": {"command": "x"}}}), encoding="utf-8")
        self.assertEqual(claude.registrar_mcp(self.raiz, [arq]), [arq])
        servidores = json.loads(arq.read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(set(servidores), {"outro", "helestron"})

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
        rede = Path(r"\\servidor\gabinete\Acervo")
        chamada = self._terminal(rede, r"C:\c\claude.exe", r"C:\wt.exe")
        args = chamada.args[0]
        self.assertNotIn("-d", args)
        self.assertEqual(args[-4:], ["cmd.exe", "/s", "/k",
                                     f'pushd "{rede}" && "C:\\c\\claude.exe"'])
        args = self._terminal(Path("C:/Acervo"), r"C:\c\claude.exe", r"C:\wt.exe").args[0]
        self.assertIn("-d", args)

    @staticmethod
    def _argv_do_windows(linha: str) -> list[str]:
        """Como o CommandLineToArgvW do Windows lê uma linha de comando."""
        args, atual, aspas, i, tem = [], [], False, 0, False
        while i < len(linha):
            c = linha[i]
            if c == "\\":
                n = 0
                while i < len(linha) and linha[i] == "\\":
                    n += 1
                    i += 1
                if i < len(linha) and linha[i] == '"':
                    atual.append("\\" * (n // 2))
                    if n % 2:
                        atual.append('"')
                        i += 1
                    tem = True
                    continue
                atual.append("\\" * n)
                tem = True
                continue
            if c == '"':
                aspas = not aspas
                tem = True
            elif c in " \t" and not aspas:
                if tem:
                    args.append("".join(atual))
                atual, tem = [], False
            else:
                atual.append(c)
                tem = True
            i += 1
        if tem:
            args.append("".join(atual))
        return args

    def test_windows_terminal_protege_e_comercial_sem_espaco(self):
        """Usuário "M&M" (o Windows aceita "&" no nome da conta) ou acervo em
        "D:\\P&D": sem espaço no caminho, o Windows Terminal não punha aspas, e o
        cmd.exe partia o comando no "&" - o Claude Code (e o Codex) não abria."""
        import subprocess

        for pasta, exe in ((r"C:\Users\M&M\Documents\Helestron\Acervo",
                            r"C:\Users\M&M\.local\bin\claude.exe"),
                           (r"D:\P&D;x\Acervo", r"C:\Users\M&M\.local\bin\claude.exe")):
            with self.subTest(pasta=pasta):
                args = self._terminal(Path(pasta), exe, r"C:\wt.exe").args[0]
                # o que o wt.exe recebe (o Python monta a linha) e lê de volta
                lidos = self._argv_do_windows(subprocess.list2cmdline(args))
                comando_wt = lidos[lidos.index("cmd.exe"):]
                # o ";" vai escapado para o wt, que o desfaz
                comando_wt = [a.replace("\\;", ";") for a in comando_wt]
                # o Windows Terminal remonta a linha do cmd: aspas só onde há espaço
                linha_cmd = " ".join(f'"{a}"' if " " in a else a for a in comando_wt)
                self.assertTrue(linha_cmd.startswith('cmd.exe /s /k "'), linha_cmd)
                # /s: o cmd tira só a primeira e a última aspa
                interno = linha_cmd.split(" /k ", 1)[1][1:-1]
                self.assertEqual(interno, f'pushd "{Path(pasta)}" && "{exe}"')
                # todo "&" de caminho fica dentro de aspas; só o "&&" fica fora
                fora = "".join(parte for i, parte in enumerate(interno.split('"')) if i % 2 == 0)
                self.assertEqual(fora.replace("&&", ""), fora.replace("&", ""))
                self.assertEqual(fora.count("&&"), 1)

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
        self.assertNotIn("A", nosso.get("env", {}))
        self.assertTrue(chatgpt.mcp_codex_registrado(arq))
        self.assertTrue(chatgpt.remover_mcp_codex(arq))
        self.assertFalse(chatgpt.mcp_codex_registrado(arq))
        self.assertIn("outro", tomllib.loads(arq.read_text(encoding="utf-8"))["mcp_servers"])

    def test_config_toml_tira_o_bloco_da_versao_anterior(self):
        arq = Path(self.dir.name) / ".codex" / "config.toml"
        arq.parent.mkdir()
        arq.write_text('[mcp_servers.assessor_integrado]\ncommand = "velho"\n'
                       '[mcp_servers.assessor_integrado.env]\nA = "1"\n\n'
                       '[mcp_servers.helestron_outro]\ncommand = "y"\n', encoding="utf-8")
        chatgpt.registrar_mcp_codex(self.raiz, arq)
        servidores = tomllib.loads(arq.read_text(encoding="utf-8"))["mcp_servers"]
        self.assertEqual(set(servidores), {"helestron", "helestron_outro"})
        self.assertEqual(list(arq.parent.glob("config.antes-do-helestron-*.toml"))[0].read_text(
            encoding="utf-8").count("assessor_integrado"), 2)

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
        # o botão do cartão "Pacote para o ChatGPT" se chama "Gerar o pacote"
        self.assertIn("“Gerar o pacote”", str(ctx.exception))
        self.assertNotIn("Gerar pacote para o ChatGPT", str(ctx.exception))
        tela = (Path(chatgpt.__file__).resolve().parents[1] / "web" / "js"
                / "secao-compartilhar.js").read_text(encoding="utf-8")
        self.assertIn('rotulo: "Gerar o pacote"', tela)
        self.assertIn('rotulo: "Abrir no ChatGPT Work"', tela)

    def test_claude_code_ausente_nao_cita_botao_que_nao_existe(self):
        with mock.patch.object(claude, "achar_claude_code", return_value=None):
            with self.assertRaises(FileNotFoundError) as ctx:
                claude.abrir_claude_code(self.raiz)
        self.assertNotIn("Instalar o Claude Code", str(ctx.exception))
        self.assertIn(claude.URL_DOC_CODE, str(ctx.exception))

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
        # as instruções falam das pastas do acervo; o pacote diz onde estão
        leia = zipfile.ZipFile(arq_zip).read("LEIA-ME - instrucoes.md").decode("utf-8")
        self.assertTrue(leia.startswith(chatgpt.NOTA_PASTAS_DO_PACOTE))
        self.assertIn("audiencias/", leia)

    def test_pacote_diz_que_leva_as_transcricoes(self):
        with self.assertLogs("compartilhar.chatgpt", "INFO") as registro:
            chatgpt.gerar_pacote(self.raiz, Path(self.dir.name) / "saida")
        final = [l for l in registro.output if "Pacote para o ChatGPT" in l]
        self.assertTrue(final, registro.output)
        self.assertIn("1 transcrição de audiência", final[-1])
        self.assertEqual(chatgpt.conteudo_do_pacote({NUM: None, SIGILOSO: None}, {NUM: [1, 2]}),
                         "2 processos (autos e texto com as páginas marcadas), 2 transcrições de "
                         "audiência, o índice e as instruções")
        self.assertEqual(chatgpt.conteudo_do_pacote({NUM: None}, {}, incluir_texto=False),
                         "1 processo (autos), o índice e as instruções")

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

    def test_espelho_dentro_do_acervo_e_recusado(self):
        """A pasta da nuvem dentro do acervo (ou o próprio acervo): cada espelho
        copiava a cópia anterior ("Helestron - Acervo/Helestron - Acervo/..."),
        e o acervo crescia sem fim."""
        for destino in (self.raiz, self.raiz / "OneDrive"):
            with self.subTest(destino=destino):
                with self.assertRaises(ValueError):
                    nuvem.espelhar(self.raiz, destino, sigilosos=None)
                self.assertFalse((self.raiz / nuvem.SUBPASTA).exists())
                self.assertFalse((self.raiz / "OneDrive" / nuvem.SUBPASTA).exists())
        # o acervo dentro da própria subpasta do espelho também não
        nuvem_dir = Path(self.dir.name) / "Nuvem"
        acervo = nuvem_dir / nuvem.SUBPASTA / "Acervo"
        _pdf(acervo / f"{NUM}.pdf", ["Petição inicial"])
        with self.assertRaises(ValueError):
            nuvem.espelhar(acervo, nuvem_dir, sigilosos=None)
        self.assertEqual(sorted(p.name for p in (nuvem_dir / nuvem.SUBPASTA).iterdir()),
                         ["Acervo"])

    def test_detectar_onedrive(self):
        pasta = Path(self.dir.name) / "OneDrive - Tribunal"
        pasta.mkdir()
        with mock.patch.dict(os.environ, {"OneDriveCommercial": str(pasta)}):
            self.assertIn(pasta, nuvem.detectar().values())


if __name__ == "__main__":
    unittest.main()
