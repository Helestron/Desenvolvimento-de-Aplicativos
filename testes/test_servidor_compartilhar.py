"""Compartilhar com IA pela API (as ferramentas externas simuladas)."""

from __future__ import annotations

import time
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
                mock.patch("helestron.compartilhar.claude.claude_desktop_instalado",
                           return_value=True), \
                mock.patch("helestron.servicos.abrir_no_cowork", return_value="cowork"):
            dados = self.cliente.dados("POST", "/api/compartilhar/cowork")
        self.assertTrue(dados["abriu"])
        self.assertIn("Pasta do acervo", dados["copiar"])
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.compartilhar.claude.abrir_claude_code",
                           side_effect=FileNotFoundError("sem")), \
                mock.patch("helestron.nucleo.sistema.abrir_endereco", return_value=True):
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-code")
        self.assertFalse(dados["abriu"])
        self.assertTrue(dados["url"].startswith("https://"))
        with mock.patch("helestron.compartilhar.claude.registrar_mcp", return_value=[Path("a")]), \
                mock.patch("helestron.compartilhar.claude.claude_desktop_instalado",
                           return_value=True):
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-desktop")
        self.assertIn("conectado", dados["mensagem"])
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.servidor.api_compartilhar._app_chatgpt", return_value=True), \
                mock.patch("helestron.servicos.abrir_chatgpt_work", return_value="web"):
            dados = self.cliente.dados("POST", "/api/compartilhar/chatgpt-work")
        self.assertEqual(dados["resultado"], "web")
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.servidor.api_compartilhar._app_chatgpt", return_value=True), \
                mock.patch("helestron.servicos.abrir_chatgpt_work", return_value="app"):
            dados = self.cliente.dados("POST", "/api/compartilhar/chatgpt-work")
        self.assertEqual((dados["resultado"], dados["abriu"]), ("app", True))
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

    def test_claude_code_ausente_abre_a_pagina_oficial(self):
        """O manual promete: sem o Claude Code, o botão abre a página oficial que
        explica como instalá-lo. Antes, a resposta só trazia o endereço."""
        from helestron.compartilhar import claude

        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.compartilhar.claude.achar_claude_code", return_value=None), \
                mock.patch("helestron.nucleo.sistema.abrir_endereco",
                           return_value=True) as abrir:
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-code")
        abrir.assert_called_once_with(claude.URL_DOC_CODE)
        self.assertEqual((dados["abriu"], dados["pagina_aberta"]), (False, True))
        self.assertIn("Abri no navegador a página oficial", dados["mensagem"])
        self.assertNotIn("Instalar o Claude Code", dados["mensagem"])
        # sem navegador que abra: a mensagem traz o endereço para copiar
        with mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                mock.patch("helestron.compartilhar.claude.achar_claude_code", return_value=None), \
                mock.patch("helestron.nucleo.sistema.abrir_endereco", return_value=False):
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-code")
        self.assertFalse(dados["pagina_aberta"])
        self.assertIn(claude.URL_DOC_CODE, dados["mensagem"])

    def test_claude_desktop_ausente_abre_a_pagina_de_download(self):
        from helestron.compartilhar import claude

        with mock.patch("helestron.compartilhar.claude.registrar_mcp", return_value=[Path("a")]), \
                mock.patch("helestron.compartilhar.claude.claude_desktop_instalado",
                           return_value=False), \
                mock.patch("helestron.nucleo.sistema.abrir_endereco",
                           return_value=True) as abrir:
            dados = self.cliente.dados("POST", "/api/compartilhar/claude-desktop")
        abrir.assert_called_once_with(claude.URL_DOWNLOAD_DESKTOP)
        self.assertEqual((dados["abriu"], dados["instalado"], dados["pagina_aberta"]),
                         (False, False, True))
        self.assertIn("página de download", dados["mensagem"])

    def test_cowork_sem_claude_desktop_diz_se_a_pagina_abriu(self):
        """Antes, sem o Claude Desktop, o Cowork dizia "abri a página de
        download" mesmo com o navegador falhando, e a resposta não trazia o
        endereço (nem pagina_aberta, para a folha oferecer o botão)."""
        from helestron.compartilhar import claude

        for abriu in (True, False):
            with self.subTest(navegador_abriu=abriu), \
                    mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                    mock.patch("helestron.compartilhar.claude.claude_desktop_instalado",
                               return_value=False), \
                    mock.patch("helestron.servicos.abrir_no_cowork") as servico, \
                    mock.patch("helestron.nucleo.sistema.abrir_endereco",
                               return_value=abriu) as abrir:
                dados = self.cliente.dados("POST", "/api/compartilhar/cowork")
                abrir.assert_called_once_with(claude.URL_DOWNLOAD_DESKTOP)
                servico.assert_not_called()
                self.assertEqual((dados["abriu"], dados["instalado"], dados["pagina_aberta"],
                                  dados["url"], dados["resultado"]),
                                 (False, False, abriu, claude.URL_DOWNLOAD_DESKTOP, "baixar"))
                self.assertIn("Pasta do acervo", dados["copiar"])
                if abriu:
                    self.assertIn("abri no navegador a página de download", dados["mensagem"])
                else:
                    self.assertNotIn("abri", dados["mensagem"])
                    self.assertIn(claude.URL_DOWNLOAD_DESKTOP, dados["mensagem"])

    def test_chatgpt_work_sem_app_diz_se_o_navegador_abriu(self):
        """Sem o app, "O ChatGPT abriu no navegador" (e abriu=True) saía mesmo
        quando nenhum navegador abria."""
        from helestron.compartilhar import chatgpt

        for abriu in (True, False):
            with self.subTest(navegador_abriu=abriu), \
                    mock.patch("helestron.compartilhar.preparo.atualizar_contexto"), \
                    mock.patch("helestron.servidor.api_compartilhar._app_chatgpt",
                               return_value=False), \
                    mock.patch("helestron.servicos.abrir_chatgpt_work") as servico, \
                    mock.patch("helestron.nucleo.sistema.abrir_endereco",
                               return_value=abriu) as abrir:
                dados = self.cliente.dados("POST", "/api/compartilhar/chatgpt-work")
                abrir.assert_called_once_with(chatgpt.URL_CHATGPT)
                servico.assert_not_called()
                self.assertEqual((dados["abriu"], dados["pagina_aberta"], dados["url"],
                                  dados["resultado"]), (abriu, abriu, chatgpt.URL_CHATGPT, "web"))
                self.assertEqual(dados["copiar"], str(self.amb.dados / "Acervo"))
                # só cita botões que existem na tela (C6)
                self.assertIn("“Gerar o pacote”", dados["mensagem"])
                if abriu:
                    self.assertIn("O ChatGPT abriu no navegador", dados["mensagem"])
                else:
                    self.assertNotIn("abriu no navegador", dados["mensagem"])
                    self.assertIn(chatgpt.URL_CHATGPT, dados["mensagem"])

    def test_abrir_a_pagina_que_o_navegador_nao_abre_e_erro_com_o_endereco(self):
        """O "Abrir a página" da folha (C6) chamava /api/abrir, que ignorava o
        False do navegador e respondia 200: a folha ficava igual, calada."""
        url = "https://docs.claude.com/pt-BR/docs/claude-code/overview"
        with mock.patch("helestron.nucleo.sistema.abrir_endereco", return_value=False):
            status, env = self.cliente.post("/api/abrir", {"tipo": "url", "alvo": url})
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "navegador_nao_abriu")
        self.assertIn(url, env["erro"]["mensagem"])
        self.assertIn("Copie o endereço", env["erro"]["mensagem"])
        with mock.patch("helestron.nucleo.sistema.abrir_endereco",
                        side_effect=OSError("sem navegador")):
            status, env = self.cliente.post("/api/abrir", {"tipo": "url", "alvo": url})
        self.assertEqual((status, env["erro"]["codigo"]), (409, "navegador_nao_abriu"))
        with mock.patch("helestron.nucleo.sistema.abrir_endereco", return_value=True) as abrir:
            self.assertEqual(self.cliente.dados("POST", "/api/abrir", {"tipo": "url", "alvo": url}),
                             {"aberto": url})
        abrir.assert_called_once_with(url)

    def test_pasta_da_nuvem_recusada_nao_fica_gravada(self):
        """Antes, espelhar gravava a pasta ANTES de conferi-la: o pedido voltava
        400, mas a pasta recusada ficava no config.ini, em uso pelo espelho
        automático e aceita pelo /api/abrir (com "/", o disco inteiro)."""
        acervo = self.amb.dados / "Acervo"
        (acervo / "Nuvem").mkdir(parents=True)
        for destino in (str(acervo / "Nuvem"), str(acervo), "/"):
            with self.subTest(destino=destino):
                status, env = self.cliente.post("/api/compartilhar/nuvem/espelhar",
                                                {"destino": destino})
                self.assertEqual(status, 400)
                self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
                self.cfg.recarregar()
                self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), "")
        with mock.patch("helestron.nucleo.sistema.abrir_arquivo") as abrir:
            status, _ = self.cliente.post("/api/abrir", {"tipo": "arquivo",
                                                         "alvo": str(Path(__file__).resolve())})
        self.assertEqual(status, 403)
        abrir.assert_not_called()

    def test_espelho_automatico_pula_a_nuvem_em_conflito(self):
        """pasta_nuvem dentro do acervo (gravada à mão ou por versão anterior):
        o espelho automático não roda - antes, cada lote ou audiência copiava a
        cópia anterior para dentro do acervo."""
        from helestron.servidor import api_compartilhar, api_processos

        acervo = self.amb.dados / "Acervo"
        acervo.mkdir(parents=True, exist_ok=True)
        self.cfg.definir("compartilhar", "espelhar_automaticamente", True)
        for nuvem_dir in (acervo, acervo / "OneDrive"):
            with self.subTest(nuvem=nuvem_dir):
                self.cfg.definir("compartilhar", "pasta_nuvem", str(nuvem_dir))
                with mock.patch("helestron.compartilhar.nuvem.espelhar") as espelhar, \
                        mock.patch("helestron.servicos.atualizar_indice"), \
                        self.assertLogs("servidor", level="WARNING") as registro:
                    api_compartilhar.depois_de_salvar(self.app)
                    api_processos._espelhar_ao_fim(self.app)
                    time.sleep(0.2)
                espelhar.assert_not_called()
                self.assertFalse([t for t in self.app.tarefas.listar() if t.tipo == "nuvem"])
                self.assertTrue(any("Espelho na nuvem NÃO feito" in linha
                                    for linha in registro.output))

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
