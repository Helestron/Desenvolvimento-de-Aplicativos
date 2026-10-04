"""Compartilhar com IA pela API (as ferramentas externas simuladas)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from testes.test_servidor_base import ServidorDeTeste


class TestCompartilhar(ServidorDeTeste):
    def test_estado_e_prompt(self):
        with mock.patch("helestron.servicos.estado_ia",
                        return_value={"claude": {"desktop": True}, "nuvens": {"OneDrive": Path("/x")},
                                      "acervo": {"processos": 2}}):
            dados = self.cliente.dados("GET", "/api/compartilhar/estado")
        self.assertEqual(dados["nuvens"], {"OneDrive": "/x"})
        self.assertEqual(dados["sigilosos_no_acervo"], [])
        self.assertEqual(dados["pasta_acervo"], str(self.amb.dados / "Acervo"))
        texto = self.cliente.dados("GET", "/api/compartilhar/prompt")["texto"]
        self.assertIn("CLAUDE.md", texto)
        self.assertIn(str(self.amb.dados / "Acervo"), texto)

    def test_preparar(self):
        rel = mock.Mock(resumo="2 processos e 1 transcrição prontos", processos=2,
                        transcricoes=1, erros=[])

        def atualizar(cfg, progresso=None, cancelado=None, **kw):
            progresso(1, 2, "texto de x")
            return rel

        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto",
                        side_effect=atualizar):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/compartilhar/preparar")["tarefa"])
        self.assertEqual(tarefa["tipo"], "preparo")
        self.assertEqual(tarefa["resultado"]["processos"], 2)
        self.assertEqual(tarefa["resultado"]["resumo"], "2 processos e 1 transcrição prontos")

    def test_ferramentas(self):
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.servicos.abrir_no_cowork", return_value="cowork"):
            dados = self.cliente.dados("POST", "/api/compartilhar/cowork")
        self.assertTrue(dados["abriu"])
        self.assertIn("Pasta do acervo", dados["copiar"])
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.compartilhar.claude.abrir_claude_code",
                           side_effect=FileNotFoundError("sem")):
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-code")
        self.assertFalse(dados["abriu"])
        self.assertTrue(dados["url"].startswith("https://"))
        with mock.patch("helestron.compartilhar.claude.registrar_mcp", return_value=[Path("a")]), \
                mock.patch("helestron.compartilhar.claude.claude_desktop_instalado",
                           return_value=True):
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-desktop")
        self.assertIn("conectado", dados["mensagem"])
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.servicos.abrir_chatgpt_work", return_value="web"):
            dados = self.cliente.dados("POST", "/api/compartilhar/chatgpt-work")
        self.assertEqual(dados["resultado"], "web")
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.servicos.registrar_mcp_codex", return_value=Path("c.toml")), \
                mock.patch("helestron.compartilhar.chatgpt.abrir_codex"):
            dados = self.cliente.dados("POST", "/api/compartilhar/codex")
        self.assertTrue(dados["abriu"])
        self.assertIn("c.toml", dados["mensagem"])

    def test_pacote(self):
        def gerar(acervo, destino, numeros=None, cfg=None, progresso=None, **kw):
            destino.mkdir(parents=True, exist_ok=True)
            return destino / "pacote", destino / "pacote.zip"

        with mock.patch("helestron.compartilhar.chatgpt.gerar_pacote", side_effect=gerar) as g:
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/compartilhar/pacote", {"numeros": ["x"]})["tarefa"])
        self.assertEqual(tarefa["resultado"]["arquivo"],
                         str(self.amb.dados / "Pacotes para IA" / "pacote.zip"))
        self.assertEqual(g.call_args.kwargs["numeros"], ["x"])

    def test_nuvem(self):
        nuvem = self.amb.raiz / "OneDrive"
        nuvem.mkdir()
        with mock.patch("helestron.compartilhar.nuvem.detectar", return_value={"OneDrive": nuvem}):
            self.assertEqual(self.cliente.dados("GET", "/api/compartilhar/nuvem"),
                             [{"rotulo": "OneDrive", "caminho": str(nuvem)}])
        status, env = self.cliente.post("/api/compartilhar/nuvem/espelhar", {})
        self.assertEqual(status, 400)
        status, env = self.cliente.post("/api/compartilhar/nuvem/espelhar",
                                        {"destino": str(self.amb.dados / "Acervo" / "x")})
        self.assertIn(status, (400, 404))
        with mock.patch("helestron.compartilhar.nuvem.espelhar", return_value=(3, 4)):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/compartilhar/nuvem/espelhar", {"destino": str(nuvem)})["tarefa"])
        self.assertEqual((tarefa["resultado"]["copiados"], tarefa["resultado"]["iguais"]), (3, 4))
        self.cfg.recarregar()
        self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), str(nuvem))


if __name__ == "__main__":
    unittest.main()
