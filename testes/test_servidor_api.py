"""API geral e de Processos: configuração, acessos, relação, abrir, diálogos."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest import mock

from helestron.servidor import api_geral

from testes.test_servidor_base import ServidorDeTeste

TJAL = "0700123-83.2024.8.02.0001"       # dígito verificador correto
TJAL_ERRADO = "0700123-45.2024.8.02.0001"
TJPE = "0000001-02.2024.8.17.0001"        # PJe: sem suporte


class CofreFalso:
    def __init__(self):
        self.dados: dict[str, tuple[str, str]] = {}

    def obter(self, portal):
        return self.dados.get(portal, ("", ""))

    def guardar(self, portal, usuario, senha):
        if not usuario and not senha:
            self.dados.pop(portal, None)
        else:
            self.dados[portal] = (usuario, senha)

    def apagar(self, portal):
        self.dados.pop(portal, None)

    def portais(self):
        return sorted(self.dados)


class TestConfig(ServidorDeTeste):
    def test_esquema_e_valores(self):
        dados = self.cliente.dados("GET", "/api/config")
        chaves = {(c["secao"], c["chave"]) for c in dados["esquema"]}
        for esperado in (("geral", "pasta_acervo"), ("pauta", "pasta"), ("pauta", "monitorar"),
                         ("download", "tentativas"), ("transcricao", "modelo_ao_vivo")):
            self.assertIn(esperado, chaves)
        tipos = {c["tipo"] for c in dados["esquema"]}
        self.assertLessEqual(tipos, {"texto", "flag", "inteiro", "pasta", "escolha"})
        escolha = next(c for c in dados["esquema"] if c["chave"] == "navegador")
        self.assertIn({"valor": "auto", "rotulo": "Automático (Chrome, senão Edge)"},
                      escolha["opcoes"])
        self.assertIs(dados["valores"]["download"]["pular_baixados"], True)
        self.assertIsInstance(dados["valores"]["download"]["tentativas"], int)
        self.assertEqual(dados["valores"]["geral"]["pasta_acervo"], str(self.amb.dados / "Acervo"))
        self.assertNotIn("interface", {c["secao"] for c in dados["esquema"]})

    def test_grava_e_valida(self):
        ok = self.cliente.dados("POST", "/api/config",
                                {"secao": "download", "chave": "tentativas", "valor": "3"})
        self.assertEqual(ok, {"valor": 3})
        self.cfg.recarregar()
        self.assertEqual(self.cfg.inteiro("download", "tentativas"), 3)
        for valor in (99, "abc"):
            status, env = self.cliente.post("/api/config", {"secao": "download",
                                                            "chave": "tentativas", "valor": valor})
            self.assertEqual(status, 400)
            self.assertEqual(env["erro"]["codigo"], "valor_invalido")
        status, env = self.cliente.post("/api/config", {"secao": "download", "chave": "navegador",
                                                        "valor": "netscape"})
        self.assertEqual(status, 400)
        self.assertEqual(self.cliente.dados("POST", "/api/config", {
            "secao": "download", "chave": "mostrar_navegador", "valor": True}), {"valor": True})

    def test_chave_inexistente_404(self):
        status, env = self.cliente.post("/api/config", {"secao": "nada", "chave": "x", "valor": 1})
        self.assertEqual(status, 404)
        self.assertEqual(env["erro"]["codigo"], "chave_inexistente")

    def test_pastas_conflitantes_recusadas(self):
        dentro = self.amb.dados / "Acervo" / "Segredo"
        status, env = self.cliente.post("/api/config", {"secao": "geral", "chave": "pasta_sigilosos",
                                                        "valor": str(dentro)})
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
        self.assertIn("acervo", env["erro"]["mensagem"])
        self.cfg.recarregar()
        self.assertEqual(self.cfg.pasta_sigilosos, self.amb.dados / "Sigilosos")

    def test_pasta_da_pauta_nao_pode_ficar_no_acervo(self):
        status, env = self.cliente.post("/api/config", {
            "secao": "pauta", "chave": "pasta", "valor": str(self.amb.dados / "Acervo" / "Pauta")})
        self.assertEqual(status, 400)
        self.assertIn("pauta", env["erro"]["mensagem"])
        ok = self.cliente.dados("POST", "/api/config", {
            "secao": "pauta", "chave": "pasta", "valor": str(self.amb.dados / "Planilhas")})
        self.assertEqual(ok["valor"], str(self.amb.dados / "Planilhas"))

    def test_pasta_da_nuvem_nao_pode_ficar_no_acervo_nem_conte_lo(self):
        """O botão "Outra pasta…" e Ajustes gravam a pasta da nuvem por aqui: a
        regra do espelho (nem dentro do acervo, nem contendo-o) vale também."""
        acervo = self.amb.dados / "Acervo"
        for valor in (acervo, acervo / "OneDrive", self.amb.dados, self.amb.raiz):
            with self.subTest(valor=valor):
                status, env = self.cliente.post("/api/config", {
                    "secao": "compartilhar", "chave": "pasta_nuvem", "valor": str(valor)})
                self.assertEqual(status, 400)
                self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
                self.cfg.recarregar()
                self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), "")
        fora = self.amb.raiz / "OneDrive"
        ok = self.cliente.dados("POST", "/api/config", {
            "secao": "compartilhar", "chave": "pasta_nuvem", "valor": str(fora)})
        self.assertEqual(ok["valor"], str(fora))
        # trocar o acervo para dentro da nuvem já escolhida também é recusado
        status, env = self.cliente.post("/api/config", {
            "secao": "geral", "chave": "pasta_acervo", "valor": str(fora / "Acervo")})
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
        # em branco (não espelhar) é sempre aceito
        ok = self.cliente.dados("POST", "/api/config", {
            "secao": "compartilhar", "chave": "pasta_nuvem", "valor": ""})
        self.assertEqual(ok["valor"], "")

    def test_pasta_relativa_recusada(self):
        status, _ = self.cliente.post("/api/config", {"secao": "compartilhar",
                                                      "chave": "pasta_nuvem", "valor": "nuvem"})
        self.assertEqual(status, 400)

    def test_secao_interna_aceita(self):
        ok = self.cliente.dados("POST", "/api/config", {"secao": "interface",
                                                        "chave": "ultimo_processo",
                                                        "valor": TJAL})
        self.assertEqual(ok["valor"], TJAL)


class TestTribunaisEAcessos(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        self.cofre = CofreFalso()
        p = mock.patch("helestron.servicos.cofre", return_value=self.cofre)
        p.start()
        self.addCleanup(p.stop)

    def test_tribunais(self):
        lista = self.cliente.dados("GET", "/api/tribunais")
        tjal = next(t for t in lista if t["sigla"] == "TJAL")
        self.assertEqual((tjal["sistema"], tjal["alternativo"]), ("esaj", "eproc"))
        self.assertTrue({"sigla", "nome", "sistema", "alternativo"} <= set(tjal))

    def test_guardar_listar_apagar(self):
        self.cfg.definir("unidade", "tribunal", "TJAL")
        lista = self.cliente.dados("GET", "/api/acessos")
        self.assertEqual([a["portal"] for a in lista], ["esaj:TJAL", "eproc:TJAL"])
        self.assertFalse(lista[0]["tem_senha"])
        dados = self.cliente.dados("POST", "/api/acessos", {"portal": "esaj:TJAL",
                                                            "usuario": "123", "senha": "s3"})
        self.assertTrue(dados["tem_senha"])
        self.assertTrue(dados["guardada"])
        self.assertEqual(self.cofre.obter("esaj:TJAL"), ("123", "s3"))
        # senha em branco = mantém a guardada
        self.cliente.dados("POST", "/api/acessos", {"portal": "esaj:TJAL", "usuario": "456"})
        self.assertEqual(self.cofre.obter("esaj:TJAL"), ("456", "s3"))
        self.assertNotIn("s3", str(self.cliente.dados("GET", "/api/acessos")))   # nunca a senha
        self.cliente.dados("DELETE", "/api/acessos/esaj:TJAL")
        self.assertEqual(self.cofre.obter("esaj:TJAL"), ("", ""))

    def _sessao_guardada(self):
        from helestron.nucleo import caminhos
        sessao = caminhos.PERFIS / "esaj-TJAL" / "sessao.json"
        sessao.parent.mkdir(parents=True, exist_ok=True)
        sessao.write_text("{}")
        (caminhos.PERFIS / "esaj-TJAL-certificado" / "Default").mkdir(parents=True, exist_ok=True)
        return sessao

    def test_apagar_acesso_apaga_a_sessao_e_os_perfis(self):
        """Sem isto, o login apagado seguia valendo por até 12 horas."""
        sessao = self._sessao_guardada()
        self.cliente.dados("POST", "/api/acessos", {"portal": "esaj:TJAL",
                                                    "usuario": "123", "senha": "s3"})
        self.assertTrue(sessao.exists(), "a primeira gravação não é troca de usuário")
        self.cliente.dados("DELETE", "/api/acessos/esaj:TJAL")
        self.assertFalse(sessao.parent.exists())
        self.assertFalse(sessao.parent.with_name("esaj-TJAL-certificado").exists())

    def test_troca_de_usuario_apaga_a_sessao_do_anterior(self):
        self.cliente.dados("POST", "/api/acessos", {"portal": "esaj:TJAL",
                                                    "usuario": "123", "senha": "s3"})
        sessao = self._sessao_guardada()
        self.cliente.dados("POST", "/api/acessos", {"portal": "esaj:TJAL", "senha": "nova"})
        self.assertTrue(sessao.exists(), "mesmo usuário, senha nova: a sessão fica")
        self.cliente.dados("POST", "/api/acessos", {"portal": "esaj:TJAL", "usuario": "456"})
        self.assertFalse(sessao.exists())

    def test_so_por_agora_nao_vai_para_o_disco(self):
        dados = self.cliente.dados("POST", "/api/acessos", {"portal": "eproc:TJAL", "usuario": "u",
                                                            "senha": "p", "lembrar": False})
        self.assertTrue(dados["so_agora"])
        self.assertEqual(self.cofre.dados, {})
        self.assertEqual(self.app.credenciais_sessao["eproc:TJAL"], ("u", "p"))
        self.assertEqual(api_geral.credenciais_de(self.app, "eproc:TJAL"), ("u", "p"))

    def test_modo_de_entrar(self):
        self.cliente.dados("POST", "/api/acessos", {"portal": "esaj:TJAL", "modo": "certificado"})
        self.cfg.recarregar()
        self.assertEqual(self.cfg.texto("esaj", "login"), "certificado")
        status, _ = self.cliente.post("/api/acessos", {"portal": "eproc:TJAL",
                                                       "modo": "certificado"})
        self.assertEqual(status, 400)

    def test_endereco_do_portal_corrigido_e_restaurado(self):
        """Ajustes › Acessos aos portais, "Endereço do portal": a correção vale por
        cima do catálogo, para o motor também, e em branco volta ao catálogo."""
        from helestron.nucleo import tribunais

        arquivo = self.amb.local / "enderecos-locais.json"
        with mock.patch.object(tribunais, "ARQUIVO_LOCAL", arquivo):
            dados = self.cliente.dados("GET", "/api/tribunais/enderecos/esaj:TJAL")
            self.assertEqual(dados["rotulo"], "TJAL · e-SAJ")
            self.assertEqual(dados["enderecos"], [{
                "grau": "base", "rotulo": "Endereço do portal", "url": "https://www2.tjal.jus.br",
                "padrao": "https://www2.tjal.jus.br", "corrigido": False}])
            self.assertEqual(self.cliente.dados("GET", "/api/tribunais/enderecos"), [])

            novo = "https://novo.tjal.jus.br"
            dados = self.cliente.dados("POST", "/api/tribunais/enderecos",
                                       {"portal": "esaj:TJAL", "grau": "base", "url": novo})
            self.assertEqual((dados["enderecos"][0]["url"], dados["enderecos"][0]["corrigido"]),
                             (novo, True))
            self.assertEqual(tribunais.por_sigla("TJAL").urls_para(), [novo])   # o motor usa
            corrigidos = self.cliente.dados("GET", "/api/tribunais/enderecos")
            self.assertEqual(corrigidos, [{"portal": "esaj:TJAL", "grau": "base",
                                           "rotulo": "Endereço do portal", "url": novo,
                                           "rotulo_portal": "TJAL · e-SAJ"}])
            # eProc da Justiça Federal: um endereço por seção judiciária
            trf4 = self.cliente.dados("GET", "/api/tribunais/enderecos/eproc:TRF4")["enderecos"]
            self.assertIn("1º grau — Rio Grande do Sul", [e["rotulo"] for e in trf4])
            # inválidos
            for corpo in ({"portal": "esaj:TJAL", "grau": "base", "url": "novo.tjal.jus.br"},
                          {"portal": "esaj:TJAL", "grau": "3g", "url": novo},
                          {"portal": "pje:TJAL", "grau": "base", "url": novo}):
                with self.subTest(corpo=corpo):
                    self.assertEqual(self.cliente.post("/api/tribunais/enderecos", corpo)[0], 400)
            # em branco: volta ao catálogo
            self.cliente.dados("POST", "/api/tribunais/enderecos",
                               {"portal": "esaj:TJAL", "grau": "base", "url": ""})
            self.assertEqual(tribunais.por_sigla("TJAL").urls_para(), ["https://www2.tjal.jus.br"])
            self.assertEqual(self.cliente.dados("GET", "/api/tribunais/enderecos"), [])

    def test_portal_invalido(self):
        for portal in ("pje:TJAL", "esaj:TJXX", "eproc:TJPE", "esaj"):
            with self.subTest(portal=portal):
                status, _ = self.cliente.post("/api/acessos", {"portal": portal, "usuario": "u"})
                self.assertEqual(status, 400)

    def test_testar_login_vira_tarefa(self):
        self.cofre.guardar("esaj:TJAL", "u", "p")
        chamadas = []

        def falso(tribunal, opcoes, ctx, credenciais):
            chamadas.append((tribunal.portal, credenciais))
            ctx.status("Entrando no e-SAJ…")

        with mock.patch("helestron.servicos.testar_login", side_effect=falso):
            dados = self.cliente.dados("POST", "/api/acessos/testar", {"tribunal": "TJAL"})
            tarefa = self.esperar_tarefa(dados["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida")
        self.assertEqual(tarefa["tipo"], "teste_login")
        self.assertEqual(chamadas, [("esaj:TJAL", ("u", "p"))])
        self.assertIn("confirmado", tarefa["resultado"]["mensagem"])

    def test_testar_o_eproc_da_linha(self):
        """O "Testar" da linha "TJAL · eProc" manda o sistema: testa o eProc, com
        as credenciais do eProc - e não o e-SAJ, o principal do TJAL."""
        self.cofre.guardar("eproc:TJAL", "ue", "pe")
        self.cofre.guardar("esaj:TJAL", "us", "ps")
        chamadas = []

        def falso(tribunal, opcoes, ctx, credenciais):
            chamadas.append((tribunal.portal, credenciais))

        with mock.patch("helestron.servicos.testar_login", side_effect=falso):
            for corpo, portal, credenciais, rotulo in (
                    ({"tribunal": "TJAL", "sistema": "eproc"}, "eproc:TJAL", ("ue", "pe"),
                     "TJAL · eProc"),
                    ({"tribunal": "TJAL", "sistema": "esaj"}, "esaj:TJAL", ("us", "ps"),
                     "TJAL · e-SAJ"),
                    ({"tribunal": "TJAL"}, "esaj:TJAL", ("us", "ps"), "TJAL · e-SAJ")):
                with self.subTest(corpo=corpo):
                    chamadas.clear()
                    tarefa = self.esperar_tarefa(self.cliente.dados(
                        "POST", "/api/acessos/testar", corpo)["tarefa"])
                    self.assertEqual(tarefa["estado"], "concluida", tarefa)
                    self.assertEqual(chamadas, [(portal, credenciais)])
                    self.assertEqual(tarefa["titulo"], f"Testar o acesso ao {rotulo}")
            status, env = self.cliente.post("/api/acessos/testar",
                                            {"tribunal": "TJAL", "sistema": "pje"})
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "valor_invalido")

    def test_testar_login_que_falha(self):
        from helestron.download.modelos import LoginFalhou

        with mock.patch("helestron.servicos.testar_login",
                        side_effect=LoginFalhou("a senha foi recusada pelo e-SAJ")):
            dados = self.cliente.dados("POST", "/api/acessos/testar",
                                       {"tribunal": "TJAL", "sistema": "eproc"})
            tarefa = self.esperar_tarefa(dados["tarefa"])
        self.assertEqual(tarefa["estado"], "falhou")
        self.assertEqual(tarefa["erro"], "A senha foi recusada pelo e-SAJ")


class TestRelacao(ServidorDeTeste):
    def test_texto(self):
        texto = f"{TJAL}; minhasenha\n{TJAL_ERRADO}\n{TJPE}\n{TJAL}"
        leitura = self.cliente.dados("POST", "/api/relacao/texto", {"texto": texto})
        numeros = [p["numero"] for p in leitura["processos"]]
        self.assertEqual(numeros, [TJAL, TJAL_ERRADO])
        self.assertTrue(leitura["processos"][0]["tem_senha"])
        self.assertEqual(leitura["processos"][0]["tribunal"], "TJAL")
        self.assertEqual(leitura["processos"][0]["sistema"], "esaj")
        self.assertEqual([s["numero"] for s in leitura["sem_suporte"]], [TJPE])
        self.assertTrue(any("dígito verificador" in a for a in leitura["avisos"]))
        self.assertEqual(set(leitura) >= {"formato", "origem", "processos", "avisos",
                                          "corrompidos", "sem_suporte"}, True)
        # a senha fica no servidor, para o lote; a página não a recebe
        self.assertNotIn("minhasenha", str(leitura))
        self.assertEqual(self.app.senhas_relacao[TJAL], "minhasenha")

    def test_texto_sem_numero_400(self):
        status, env = self.cliente.post("/api/relacao/texto", {"texto": "nada aqui"})
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "relacao_invalida")

    def test_envio_multipart(self):
        conteudo = f"processo;senha\n{TJAL};abc\n".encode("cp1252")
        status, env = self.cliente.enviar("/api/relacao/arquivo", "Relação de março.csv", conteudo)
        self.assertEqual(status, 200, env)
        leitura = env["dados"]
        self.assertEqual([p["numero"] for p in leitura["processos"]], [TJAL])
        self.assertEqual(leitura["origem"], "Relação de março.csv")
        self.assertEqual(leitura["nome_lote"], "Relação de março")
        # o arquivo enviado não fica no disco (pode trazer senhas)
        envios = Path(self.app.pasta_envios())
        self.assertEqual(list(envios.glob("*")) if envios.exists() else [], [])

    def test_envio_ilegivel_400(self):
        status, env = self.cliente.enviar("/api/relacao/arquivo", "vazio.txt", b"sem numero")
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "relacao_invalida")
        envios = Path(self.app.pasta_envios())
        self.assertEqual(list(envios.glob("*")) if envios.exists() else [], [])

    def test_envio_sem_campo_arquivo(self):
        status, env = self.cliente.enviar("/api/relacao/arquivo", "a.txt", TJAL.encode(),
                                          campo="outro")
        self.assertEqual(status, 400)

    def test_caminho(self):
        arquivo = self.amb.raiz / "lista.txt"
        arquivo.write_text(TJAL, encoding="utf-8")
        leitura = self.cliente.dados("POST", "/api/relacao/arquivo", {"caminho": str(arquivo)})
        self.assertEqual(leitura["nome_lote"], "lista")
        status, _ = self.cliente.post("/api/relacao/arquivo",
                                      {"caminho": str(self.amb.raiz / "nao.txt")})
        self.assertEqual(status, 404)

    def test_link(self):
        def baixar(url, pasta):
            pasta.mkdir(parents=True, exist_ok=True)
            destino = pasta / "relacao do drive.txt"
            destino.write_text(TJAL, encoding="utf-8")
            return destino

        with mock.patch("helestron.nucleo.listas.baixar_link", side_effect=baixar):
            leitura = self.cliente.dados("POST", "/api/relacao/link",
                                         {"url": "https://drive.google.com/x"})
        self.assertEqual(len(leitura["processos"]), 1)
        self.assertFalse(list((self.amb.local / "temp" / "listas").glob("*")))
        status, _ = self.cliente.post("/api/relacao/link", {"url": "file:///etc/passwd"})
        self.assertEqual(status, 400)


class TestAbrirEDialogos(ServidorDeTeste):
    def test_abre_so_dentro_das_pastas_do_usuario(self):
        acervo = self.amb.dados / "Acervo"
        acervo.mkdir(parents=True)
        (acervo / "a.pdf").write_bytes(b"%PDF")
        (acervo / "b.exe").write_bytes(b"MZ")
        with mock.patch("helestron.nucleo.sistema.abrir_arquivo") as abrir_arquivo, \
                mock.patch("helestron.nucleo.sistema.abrir_pasta") as abrir_pasta, \
                mock.patch("helestron.nucleo.sistema.abrir_endereco") as abrir_endereco:
            self.cliente.dados("POST", "/api/abrir", {"tipo": "arquivo", "alvo": str(acervo / "a.pdf")})
            abrir_arquivo.assert_called_once()
            self.cliente.dados("POST", "/api/abrir", {"tipo": "pasta", "alvo": str(acervo)})
            abrir_pasta.assert_called_once()
            for corpo, esperado in (
                    ({"tipo": "pasta", "alvo": "/etc"}, 403),
                    ({"tipo": "arquivo", "alvo": str(self.amb.local / "credenciais.json")}, 403),
                    ({"tipo": "arquivo", "alvo": str(acervo / "b.exe")}, 403),
                    ({"tipo": "arquivo", "alvo": str(acervo / "sumiu.pdf")}, 404),
                    ({"tipo": "url", "alvo": "http://exemplo.com"}, 403),
                    ({"tipo": "url", "alvo": "file:///C:/Windows"}, 403),
                    ({"tipo": "programa", "alvo": "x"}, 400)):
                with self.subTest(corpo=corpo):
                    status, _ = self.cliente.post("/api/abrir", corpo)
                    self.assertEqual(status, esperado)
            self.cliente.dados("POST", "/api/abrir", {"tipo": "url", "alvo": "https://claude.ai"})
            abrir_endereco.assert_called_once_with("https://claude.ai")
            self.assertEqual(abrir_arquivo.call_count, 1)

    def test_nuvem_na_raiz_da_unidade_nao_abre_o_disco_todo(self):
        """Pasta da nuvem na raiz de uma unidade (gravada à mão): o /api/abrir
        não passa a abrir qualquer arquivo dela."""
        self.cfg.definir("compartilhar", "pasta_nuvem", "/")
        with mock.patch("helestron.nucleo.sistema.abrir_arquivo") as abrir:
            status, _ = self.cliente.post("/api/abrir", {"tipo": "arquivo",
                                                         "alvo": str(Path(__file__).resolve())})
        self.assertEqual(status, 403)
        abrir.assert_not_called()
        nuvem = self.amb.raiz / "OneDrive"
        nuvem.mkdir()
        self.cfg.definir("compartilhar", "pasta_nuvem", str(nuvem))
        with mock.patch("helestron.nucleo.sistema.abrir_pasta") as abrir_pasta:
            self.cliente.dados("POST", "/api/abrir", {"tipo": "pasta", "alvo": str(nuvem)})
        abrir_pasta.assert_called_once()

    def test_sem_janela_nao_ha_dialogo(self):
        status, env = self.cliente.post("/api/dialogo/arquivo", {"titulo": "x"})
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "sem_dialogo")

    def test_dialogo_pela_janela(self):
        janela = mock.Mock(tem_dialogos=True)
        janela.dialogo_arquivo.return_value = "C:\\relacao.xlsx"
        janela.dialogo_pasta.return_value = None
        self.app.janela = janela
        dados = self.cliente.dados("POST", "/api/dialogo/arquivo", {
            "titulo": "Relação", "tipos": ["Planilhas|*.xlsx;*.xls", "Tudo|*.*", "Ruim|exe"]})
        self.assertEqual(dados, {"caminho": "C:\\relacao.xlsx"})
        self.assertEqual(janela.dialogo_arquivo.call_args[0][1],
                         ["Planilhas (*.xlsx;*.xls)", "Tudo (*.*)"])
        self.assertEqual(self.cliente.dados("POST", "/api/dialogo/pasta", {}), {"caminho": None})

    def test_tipos_pywebview_limpa_a_descricao(self):
        self.assertEqual(api_geral.tipos_pywebview(["Relatórios do e-SAJ|*.xls;*.html"]),
                         ["Relatórios do e SAJ (*.xls;*.html)"])


class TestVerificacaoEEncerrar(ServidorDeTeste):
    def test_verificacao_rapida(self):
        from helestron.servicos import ItemVerificacao

        with mock.patch("helestron.servicos.verificar_instalacao",
                        return_value=[ItemVerificacao("Python", "ok", "3.12", True)]):
            itens = self.cliente.dados("GET", "/api/verificacao")
        self.assertEqual(itens[0]["nome"], "Python")
        self.assertEqual(set(itens[0]) >= {"nome", "situacao", "detalhe", "acao"}, True)

    def test_verificacao_completa_vira_tarefa(self):
        from helestron.servicos import ItemVerificacao

        def falsa(completo, cfg, ao_item=None):
            itens = [ItemVerificacao("Python", "ok"), ItemVerificacao("Modelo", "falha", "x", True)]
            for i in itens:
                ao_item(i)
            return itens

        with mock.patch("helestron.servicos.verificar_instalacao", side_effect=falsa):
            dados = self.cliente.dados("POST", "/api/verificacao/completa")
            tarefa = self.esperar_tarefa(dados["tarefa"])
        self.assertEqual(tarefa["resultado"]["resultado"], "falha")
        self.assertEqual(len(tarefa["resultado"]["itens"]), 2)

    def test_encerrar(self):
        self.cliente.dados("POST", "/api/encerrar")
        self.assertTrue(self.app.esperar(15))
        self.assertTrue(self.app.fechando)

    def test_tarefa_inexistente_404(self):
        status, env = self.cliente.get("/api/tarefas/nada")
        self.assertEqual(status, 404)
        status, _ = self.cliente.post("/api/tarefas/nada/parar")
        self.assertEqual(status, 404)
        status, env = self.cliente.post("/api/perguntas/nada/responder", {"valor": "1"})
        self.assertEqual(status, 404)
        self.assertEqual(env["erro"]["codigo"], "pergunta_inexistente")


class TestEstadoPendenciasEPerguntas(ServidorDeTeste):
    def test_resolver_instalacao_incompleta_leva_ao_diagnostico(self):
        """O "Resolver" de "Instalação incompleta" ia para "ajustes#diagnostico",
        grupo que não existe em Ajustes: a tela caía em "Acessos aos portais"."""
        from helestron import servicos

        presente = servicos._pacote_presente
        with mock.patch("helestron.servicos._pacote_presente",
                        side_effect=lambda nome: nome != "playwright" and presente(nome)):
            pendencias = self.cliente.dados("GET", "/api/estado")["pendencias"]
        pacotes = next(x for x in pendencias if x["chave"] == "pacotes")
        self.assertEqual(pacotes["acao"], "ajustes#sobre")
        # toda ação "ajustes#<grupo>" das pendências aponta um grupo que existe na tela
        tela = (Path(servicos.__file__).resolve().parent / "web" / "js"
                / "secao-ajustes.js").read_text(encoding="utf-8")
        import re

        grupos = set(re.findall(r'\{ id: "([a-z]+)", curto:', tela))
        self.assertIn("sobre", grupos)
        fonte = Path(servicos.__file__).read_text(encoding="utf-8") + \
            Path(api_geral.__file__).read_text(encoding="utf-8")
        for grupo in re.findall(r'"ajustes#([a-z]+)"', fonte):
            with self.subTest(grupo=grupo):
                self.assertIn(grupo, grupos)

    def test_resumo_da_pauta_traz_fontes_e_configurada(self):
        """O passo "Pauta" dos Primeiros passos só se dá por feito com
        'configurada': /api/estado repassa 'fontes' e 'configurada' (e os
        completa se a pauta não os der)."""
        class PautaAntiga:
            def resumo_inicio(self):
                return {"hoje": 0, "semana": 0, "proxima": None, "ultima_sincronizacao": None,
                        "alteracoes_nao_vistas": 0}

            def fontes(self):
                return [{"id": "f1"}]

        with mock.patch.object(self.app, "pauta_ou_none", return_value=PautaAntiga()):
            pauta = self.cliente.dados("GET", "/api/estado")["resumo"]["pauta"]
        self.assertEqual((pauta["fontes"], pauta["configurada"]), (1, True))

        class PautaNova(PautaAntiga):
            def resumo_inicio(self):
                return dict(super().resumo_inicio(), fontes=0, configurada=False)

        with mock.patch.object(self.app, "pauta_ou_none", return_value=PautaNova()):
            pauta = self.cliente.dados("GET", "/api/estado")["resumo"]["pauta"]
        self.assertEqual((pauta["fontes"], pauta["configurada"]), (0, False))
        # a pauta de verdade, sem nada cadastrado
        pauta = self.cliente.dados("GET", "/api/estado")["resumo"]["pauta"]
        self.assertIsNotNone(pauta)
        self.assertEqual((pauta["fontes"], pauta["configurada"]), (0, False))

    def test_pergunta_chama_a_atencao_da_janela(self):
        """Pedido de código (e-mail do e-SAJ, autenticador do eProc): o servidor
        chama quem se registrou (a janela vem para a frente e pisca) - antes, a
        folha abria numa janela minimizada, e o prazo acabava sem ninguém ver."""
        import threading

        from helestron.tarefas import Pergunta

        chamadas = threading.Event()
        quebrada = mock.Mock(side_effect=RuntimeError("janela fechada"))
        self.app.registrar_atencao(quebrada)          # uma que falha não impede as outras
        self.app.registrar_atencao(chamadas.set)
        self.app.registrar_atencao(chamadas.set)      # registrar de novo não duplica
        leitor = self.eventos()
        pergunta = Pergunta("Código de verificação do e-SAJ", "Digite o código", 60,
                            tipo="codigo")
        self.app.perguntas.abrir(pergunta, None)
        self.assertEqual(leitor.esperar("pergunta")["titulo"], "Código de verificação do e-SAJ")
        self.assertTrue(chamadas.wait(5))
        limite = time.monotonic() + 5
        while not quebrada.called and time.monotonic() < limite:
            time.sleep(0.02)
        quebrada.assert_called_once()
        # fechar a pergunta não chama a atenção de novo
        chamadas.clear()
        pergunta.cancelar()
        leitor.esperar("pergunta_fechada")
        self.assertFalse(chamadas.wait(0.3))


if __name__ == "__main__":
    unittest.main()
