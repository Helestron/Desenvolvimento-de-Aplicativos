"""PortalESAJ: a lógica pura e os fluxos, com dublês de página.

Não há acesso aos portais daqui. O que se testa é o que o programa faz com
o que o portal responde: os endereços montados (com o foro do próprio
número - na base ele vinha fixo em 56), a árvore da Pasta Digital, os
buracos na numeração, o segredo de justiça, o código por e-mail, a senha
recusada, o PDF que o servidor não monta (e vira peça a peça).
"""

from __future__ import annotations

import json
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

import pymupdf

from helestron.download import esaj, modelos
from helestron.download.esaj import PortalESAJ
from helestron.nucleo.tribunais import Tribunal

from testes import apoio_download as apoio

TRIBUNAL = Tribunal(chave="8.02", sigla="TJAL", nome="Tribunal de Justiça - Alagoas",
                    sistema="esaj", urls={"base": "https://portal.teste"})
N = apoio.numero("0700001", tr="02", origem="0056")
N_INC = apoio.numero("0700001", tr="02", origem="0056", dependente="01")


def par(cd, ini, fim, extra=""):
    return (f"nuSeqRecurso=00000&nuProcesso={N.principal}&cdDocumento={cd}"
            f"&numInicial={ini}&numFinal={fim}&idDocumento=X{cd}{ini}{extra}")


ARVORE = [
    {"data": {"title": "Petição Inicial", "cdDocumento": 101, "dtInclusao": "01/02/2024",
              "flPeticaoInicial": True},
     "children": [{"data": {"parametros": par(101, 1, 2), "nuPaginas": 2, "flAssinado": True}}]},
    {"data": {"title": "Contestação", "cdDocumento": 102, "dtInclusao": "10/03/2024"},
     "children": [{"data": {"parametros": par(102, 3, 4), "nuPaginas": 2}},
                  {"data": {"parametros": par(102, 5, 5), "nuPaginas": 1}}]},
    {"data": {"title": "Termo de Audiência", "cdDocumento": 104, "dtInclusao": "20/04/2024"},
     "children": [{"data": {"parametros": par(104, 8, 8), "nuPaginas": 1}},
                  {"data": {"urlMidiaDigital": "https://portal.teste/pastadigital/getMidia.do?"
                            "gravacaoAudiencia=C%3A%5Cmidias%5Caudiencia%201.mp3&x=1"}}]},
]

INFO = {"capa": {"Classe": "Procedimento Comum Cível", "Juiz": "Fulano de Tal"},
        "partes": ["Autor: Maria da Silva", "Réu: Banco Exemplo S.A."],
        "movs": [{"data": "20/04/2024", "texto": "Audiência realizada"}],
        "texto": "Processo 0700001 Classe Procedimento Comum Cível"}


# ============================================================ funções puras
class TestEnderecos(unittest.TestCase):
    def test_busca_usa_o_foro_do_numero(self):
        url = esaj.url_busca("https://b", N)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)
        self.assertTrue(url.startswith("https://b/cpopg/search.do?"))
        self.assertEqual(q["foroNumeroUnificado"], ["0056"])
        self.assertEqual(q["numeroDigitoAnoUnificado"], [N.unificado])
        self.assertEqual(q["dadosConsulta.valorConsultaNuUnificado"], [N.principal, "UNIFICADO"])
        self.assertEqual(q["cbPesquisa"], ["NUMPROC"])

    def test_busca_de_outro_foro(self):
        outro = apoio.numero("0700001", tr="26", origem="0100")
        self.assertIn("foroNumeroUnificado=0100", esaj.url_busca("https://b", outro))

    def test_pagina_do_processo_com_foro_sem_zeros(self):
        url = esaj.url_processo("https://b", "1K0001AAA0000", N)
        self.assertEqual(url, f"https://b/cpopg/show.do?processo.codigo=1K0001AAA0000"
                              f"&processo.foro=56&processo.numero={N.principal}")

    def test_incidente_nao_herda_o_foro_56_fixo(self):
        outro = apoio.numero("0700001", tr="02", origem="0001", dependente="01")
        url = esaj.url_processo("https://b", "1K0001AAA0001", outro)
        self.assertIn("processo.foro=1", url)
        self.assertNotIn("processo.foro=56", url)
        self.assertNotIn("processo.numero", url, "o número do principal não serve ao incidente")

    def test_codigo_do_incidente(self):
        self.assertEqual(esaj.codigo_incidente("1K0000RXW0000", 1), "1K0000RXW0001")
        self.assertEqual(esaj.codigo_incidente("1K0000RXW0000", 12), "1K0000RXW0012")
        with self.assertRaises(ValueError):
            esaj.codigo_incidente("123", 1)

    def test_marca_do_incidente(self):
        m = esaj.marca_do_incidente(1)
        for sim in ("0700001-70.2024.8.02.0001/01 Cumprimento", "Execução (00001)", "x (01)",
                    "x/0001", "0700001-70.2024.8.02.0001/1 fim"):
            self.assertTrue(m.search(sim), sim)
        for nao in ("x/0100", "x/10", "item 1) a", "0700001-70.2024.8.02.0001", "000010"):
            self.assertFalse(m.search(nao), nao)

    def test_data_na_linha_nao_passa_por_marca_do_incidente(self):
        """A linha de OUTRO incidente traz a data de recebimento: "/01" de
        janeiro não pode ser tomado pelo incidente 01 (autos trocados)."""
        for ordem, linha in ((1, "Cumprimento de sentença  Recebido em 15/01/2024"),
                             (1, "Recebido em 2024/01/15"),
                             (10, "Embargos à execução 05/10/2024"),
                             (1, "Volume (1)")):
            self.assertFalse(esaj.marca_do_incidente(ordem).search(linha), (ordem, linha))
        self.assertTrue(esaj.marca_do_incidente(10).search(
            "0700001-70.2024.8.02.0001/10 - 05/10/2024"))

    def test_codigo_na_url_ou_no_html(self):
        self.assertEqual(esaj.codigo_na("show.do?processo.codigo=1K0001AAA0000&x"), "1K0001AAA0000")
        self.assertIsNone(esaj.codigo_na("<html>nada</html>"))


class TestTextosDoPortal(unittest.TestCase):
    def test_nao_encontrado_com_a_frase_real(self):
        self.assertTrue(esaj.diz_nao_encontrado(
            "Não existem informações disponíveis para os parâmetros informados."))
        self.assertTrue(esaj.diz_nao_encontrado("Processo não encontrado"))
        self.assertFalse(esaj.diz_nao_encontrado("Dados do processo"))

    def test_sem_acesso(self):
        self.assertTrue(esaj.diz_sem_acesso("Não foi possível validar o seu acesso."))
        self.assertFalse(esaj.diz_sem_acesso("Pasta digital"))

    def test_sigilo(self):
        self.assertTrue(esaj.texto_indica_sigilo("Classe: Divórcio  Segredo de Justiça"))
        self.assertTrue(esaj.texto_indica_sigilo("SEGREDO DE JUSTIÇA"))
        self.assertFalse(esaj.texto_indica_sigilo("Quebra de sigilo bancário deferida"))

    def test_classificacao_de_erros(self):
        self.assertTrue(esaj.erro_transitorio("Target page, context or browser has been closed"))
        self.assertTrue(esaj.erro_transitorio("Execution context was destroyed"))
        self.assertFalse(esaj.erro_transitorio("HTTP 500"))
        self.assertTrue(esaj.cheira_a_sessao("não consegui abrir a Pasta Digital"))
        self.assertTrue(esaj.cheira_a_sessao("a lista de peças da Pasta Digital não carregou"))
        self.assertTrue(esaj.cheira_a_sessao("Sessão expirada"))
        self.assertFalse(esaj.cheira_a_sessao("o servidor demorou demais"))
        self.assertTrue(esaj.falha_de_rede("connect ECONNREFUSED 10.0.0.1:443"))
        self.assertTrue(esaj.falha_de_rede("Timeout 300000ms exceeded"))
        self.assertTrue(esaj.falha_de_rede("net::ERR_CONNECTION_RESET"))
        self.assertFalse(esaj.falha_de_rede("HTTP 404"))
        # rede do fórum: o canal direto não resolve o nome nem aceita o
        # certificado da inspeção de TLS - é caminho, não recusa do portal
        for msg in ("getaddrinfo ENOTFOUND www2.tjal.jus.br",
                    "self-signed certificate in certificate chain",
                    "unable to get local issuer certificate"):
            self.assertTrue(esaj.falha_de_rede(msg), msg)
            self.assertTrue(esaj.falha_de_caminho(msg), msg)
        self.assertFalse(esaj.falha_de_caminho("connect ECONNRESET 1.2.3.4:443"))

    def test_mascara_do_usuario(self):
        self.assertEqual(esaj.mascarar("12345678900"), "123***")
        self.assertNotIn("45678900", esaj.mascarar("12345678900"))

    def test_proxy_do_sistema(self):
        with mock.patch.object(esaj.urllib.request, "getproxies",
                               return_value={"https": "proxy.tj:3128"}):
            self.assertEqual(esaj.proxy_do_sistema(), "http://proxy.tj:3128")
        with mock.patch.object(esaj.urllib.request, "getproxies", return_value={}):
            self.assertIsNone(esaj.proxy_do_sistema())


class TestArvoreDaPasta(unittest.TestCase):
    def test_extrair_pecas(self):
        pecas = esaj.extrair_pecas(ARVORE)
        self.assertEqual(len(pecas), 4, "a mídia não é peça do PDF")
        self.assertEqual([p["pagina_inicial"] for p in pecas], ["1", "3", "5", "8"])
        self.assertEqual(pecas[1]["tipo"], "Contestação")
        self.assertEqual(pecas[1]["cdDocumento"], "102")
        self.assertEqual(pecas[0]["data"], "01/02/2024")

    def test_titulo_pela_consulta_quando_falta(self):
        arvore = [{"data": {}, "children": [{"data": {
            "parametros": "cdDocumento=9&numInicial=1&numFinal=1&deTipoDocConsulta=Of%C3%ADcio+Expedido"}}]}]
        self.assertEqual(esaj.extrair_pecas(arvore)[0]["tipo"], "Ofício Expedido")

    def test_marca_de_peca_sigilosa(self):
        def com(valor):
            filho = {"data": {"parametros": par(101, 1, 1), "documentoSigiloso": valor}}
            return esaj.extrair_pecas([{"data": {"cdDocumento": 101}, "children": [filho]}])[0]
        for valor in (True, "S", "true", 1):
            self.assertTrue(com(valor)["sigiloso"], valor)
        for valor in (False, "N", "false", 0, None, ""):
            self.assertFalse(com(valor)["sigiloso"], valor)
        self.assertFalse(esaj.extrair_pecas(ARVORE)[0]["sigiloso"])

    def test_arvore_estranha_nao_quebra(self):
        self.assertEqual(esaj.extrair_pecas(None), [])
        self.assertEqual(esaj.extrair_pecas({"x": 1}), [])
        self.assertEqual(esaj.extrair_pecas([None, {"children": [None]}]), [])

    def test_midias(self):
        midias = esaj.extrair_midias(ARVORE)
        self.assertEqual(len(midias), 1)
        self.assertEqual(midias[0]["arquivo"], "audiencia 1.mp3")
        self.assertEqual(midias[0]["folha"], "8")
        self.assertEqual(midias[0]["peca"], "Termo de Audiência")

    def test_conferir_numeracao(self):
        buracos, soma = esaj.conferir_numeracao(esaj.extrair_pecas(ARVORE))
        self.assertEqual(buracos, [(6, 7)])
        self.assertEqual(soma, 6)
        self.assertEqual(esaj.descrever_buracos([(6, 7), (10, 10)]), "6-7, 10")
        self.assertEqual(esaj.conferir_numeracao([]), ([], 0))
        sobrepostas = [{"pagina_inicial": "1", "pagina_final": "5"},
                       {"pagina_inicial": "3", "pagina_final": "6"}]
        self.assertEqual(esaj.conferir_numeracao(sobrepostas)[0], [])

    def test_marcadores_contam_a_pagina_do_arquivo_e_nao_a_folha(self):
        marcas, total = esaj.marcadores_das_pecas(esaj.extrair_pecas(ARVORE))
        self.assertEqual(total, 6)
        self.assertEqual([m[1] for m in marcas], [1, 3, 6],
                         "o Termo começa na página 6 do PDF (fls. 6-7 não vieram)")
        self.assertEqual(marcas[1][0], "Contestação (fls. 3-5) - 10/03/2024")
        self.assertEqual(marcas[2][0], "Termo de Audiência (fl. 8) - 20/04/2024")

    def test_marcadores_sem_numeracao(self):
        self.assertEqual(esaj.marcadores_das_pecas([{"parametros": "x"}]), ([], 0))

    def test_contar_documentos(self):
        self.assertEqual(esaj.contar_documentos(esaj.extrair_pecas(ARVORE)), 3)


class TestSeletores(apoio.PastaTemporaria):
    def test_padrao(self):
        sel = esaj.carregar_seletores(self.tmp / "nao-existe.json")
        self.assertEqual(sel["login_usuario"][0], "#usernameForm")

    def test_os_do_usuario_vem_na_frente(self):
        arq = self.tmp / "seletores.json"
        arq.write_text(json.dumps({"esaj": {"login_usuario": ["#novoCampo", "#usernameForm"],
                                            "login_token": "#outroToken"}}), encoding="utf-8")
        sel = esaj.carregar_seletores(arq)
        self.assertEqual(sel["login_usuario"][:2], ["#novoCampo", "#usernameForm"])
        self.assertEqual(sel["login_usuario"].count("#usernameForm"), 1)
        self.assertEqual(sel["login_token"][0], "#outroToken")

    def test_arquivo_estragado_usa_o_padrao(self):
        arq = self.tmp / "seletores.json"
        arq.write_text("{quebrado", encoding="utf-8")
        self.assertEqual(esaj.carregar_seletores(arq)["login_senha"][0], "#passwordForm")

    def test_correcao_fica_na_pasta_de_dados_que_a_atualizacao_nao_apaga(self):
        """A pasta do programa (Lib\\site-packages\\helestron\\dados) é apagada a
        cada atualização: a correção do usuário mora na pasta de dados (LOCAL);
        a de dentro do programa ainda vale, de reserva, atrás dela."""
        from helestron.nucleo import caminhos

        local, programa = self.tmp / "local", self.tmp / "programa"
        local.mkdir()
        programa.mkdir()
        with mock.patch.object(caminhos, "LOCAL", local), \
                mock.patch.object(caminhos, "DADOS", programa):
            self.assertEqual(esaj.carregar_seletores()["login_usuario"][0], "#usernameForm")
            (local / "seletores.json").write_text(json.dumps(
                {"esaj": {"login_usuario": ["#novoCampoUsuario"]}}), encoding="utf-8")
            self.assertEqual(esaj.carregar_seletores()["login_usuario"][:2],
                             ["#novoCampoUsuario", "#usernameForm"])
            (programa / "seletores.json").write_text(json.dumps(
                {"esaj": {"login_usuario": ["#campoDaVersao"], "login_senha": ["#senhaNova"]}}),
                encoding="utf-8")
            sel = esaj.carregar_seletores()
            self.assertEqual(sel["login_usuario"][:3],
                             ["#novoCampoUsuario", "#campoDaVersao", "#usernameForm"])
            self.assertEqual(sel["login_senha"][0], "#senhaNova")
            # a mensagem do portal mudado aponta o arquivo certo
            self.assertEqual(esaj.arquivos_de_seletores()[-1], local / "seletores.json")


class TestCapa(unittest.TestCase):
    def test_capa(self):
        texto = esaj.formatar_capa(INFO, N, "TJAL")
        self.assertIn(f"Processo {N.formatado} - TJAL", texto)
        self.assertIn("Classe: Procedimento Comum Cível", texto)
        self.assertIn("Autor: Maria da Silva", texto)
        self.assertIn("20/04/2024  Audiência realizada", texto)
        self.assertNotIn("SEGREDO", texto)
        self.assertIn("SEGREDO DE JUSTIÇA", esaj.formatar_capa(INFO, N, "TJAL", sigiloso=True))


# ================================================================ dublês
class NavegadorDeMentira:
    def __init__(self):
        self.diagnosticos = []
        self.visitas = []
        self.esqueceu = False
        self.perfil = Path("/nao/existe")
        self.pagina = types.SimpleNamespace(url="https://portal.teste/esaj/portal.do")
        self.contexto = None
        self.playwright = None

    def ir(self, url, **_):
        self.visitas.append(url)
        self.pagina.url = url

    def diagnosticar(self, rotulo, pagina=None):
        self.diagnosticos.append(rotulo)

    def esquecer_sessao(self):
        self.esqueceu = True

    def abas(self):
        return []


def opcoes(**k):
    base = dict(espera_s=10, espera_login_min=1, login={"esaj": "senha"})
    base.update(k)
    return modelos.OpcoesDownload(**base)


class PortalDeLogin(PortalESAJ):
    """Só o bastante para exercitar 'entrar' (porte do teste da base)."""

    def __init__(self, campos_por_tentativa=(True,), logado_depois=False, logado_antes=False,
                 credenciais=("111", "abc"), sessao_final=True, texto_tela="", ctx=None):
        super().__init__(NavegadorDeMentira(), TRIBUNAL, opcoes(),
                         ctx or apoio.ContextoGravador(), credenciais)
        self.campos = list(campos_por_tentativa)
        self.logado_depois = logado_depois
        self.logado_antes = logado_antes
        self.sessao_final = sessao_final
        self.texto_tela = texto_tela
        self.tentativas = 0
        self.preencheu = False
        self.token = False

    def _esta_logado(self, pagina=None):
        return self.logado_antes or (self.logado_depois and self.tentativas > 0)

    def sessao_ativa(self):
        return False

    def _preencher_login(self):
        achou = self.campos[self.tentativas] if self.tentativas < len(self.campos) else False
        self.tentativas += 1
        if not achou:
            raise esaj._CamposNaoApareceram("não encontrei os campos")
        self.preencheu = True

    def _resolver_codigo(self):
        self.token = True
        return False

    def _sessao_no_contexto(self):
        return self.sessao_final

    def _sondar_sessao(self):
        return self.sessao_final

    def _texto_da_pagina(self, pagina=None):
        return self.texto_tela

    def _recusa_na_tela(self):
        return False


class TestLoginInsiste(unittest.TestCase):
    """A tela de login sem formulário não pode derrubar o lote (14/09/2026)."""

    def test_a_segunda_tentativa_salva_o_lote(self):
        p = PortalDeLogin([False, True])
        p.entrar()
        self.assertTrue(p.preencheu)
        self.assertEqual(p.tentativas, 2)
        self.assertEqual(p.nav.diagnosticos, [], "não diagnostica o que se curou")

    def test_ja_logado_encerra_sem_formulario_nenhum(self):
        p = PortalDeLogin([False], logado_depois=True)
        p.entrar()
        self.assertFalse(p.preencheu)
        self.assertEqual(p.tentativas, 1)

    def test_tres_falhas_desistem_com_diagnostico(self):
        p = PortalDeLogin([False, False, False])
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            p.entrar()
        self.assertEqual(p.tentativas, 3)
        self.assertIn("esaj-login-sem-campos", p.nav.diagnosticos)
        self.assertIn("seletores", str(caso.exception))
        from helestron.nucleo import caminhos

        self.assertIn(str(caminhos.LOCAL / "seletores.json"), str(caso.exception))

    def test_campos_no_primeiro_gole_nao_repete(self):
        p = PortalDeLogin([True])
        p.entrar()
        self.assertEqual(p.tentativas, 1)
        self.assertTrue(p.token)

    def test_sessao_valida_dispensa_ate_a_senha(self):
        p = PortalDeLogin(logado_antes=True, credenciais=None)
        p.entrar()
        self.assertEqual(p.tentativas, 0)

    def test_sem_credenciais_explica_o_que_fazer(self):
        p = PortalDeLogin(credenciais=None)
        with self.assertRaises(modelos.LoginFalhou) as caso:
            p.entrar()
        self.assertIn("“Entrar manualmente”", str(caso.exception))
        self.assertIn("Cadastre-os em Ajustes › Acessos aos portais", str(caso.exception))
        self.assertEqual(p.tentativas, 0)

    def test_senha_recusada(self):
        p = PortalDeLogin(sessao_final=False, texto_tela="Usuário ou senha inválidos.")
        with self.assertRaises(modelos.LoginFalhou) as caso:
            p.entrar()
        self.assertIn("recusou o usuário ou a senha", str(caso.exception))
        self.assertIn("Ajustes › Acessos aos portais", str(caso.exception))
        self.assertTrue(p.nav.esqueceu, "sessão velha não deve ser reaproveitada")

    def test_login_que_nao_conclui_sugere_mostrar_navegador(self):
        p = PortalDeLogin(sessao_final=False, texto_tela="Bem-vindo")
        with self.assertRaises(modelos.LoginFalhou) as caso:
            p.entrar()
        self.assertIn("Mostrar o navegador enquanto baixa", str(caso.exception))


class PortalDoCodigo(PortalESAJ):
    def __init__(self, ctx, aceito="222", na_janela=False):
        super().__init__(NavegadorDeMentira(), TRIBUNAL, opcoes(), ctx, ("u", "s"))
        self.aceito = aceito
        self.na_janela = na_janela
        self.enviados = []
        self.novos = 0

    def _tela_do_codigo(self, espera_s=45):
        return "aba", "campo"

    def _enviar_codigo(self, codigo):
        self.enviados.append(codigo)
        return codigo == self.aceito

    def _pedir_codigo_novo(self):
        self.novos += 1
        return True

    def _sessao_no_contexto(self):
        return self.na_janela

    def _sondar_sessao(self):
        return self.na_janela


class TestCodigoPorEmail(unittest.TestCase):
    def test_codigo_pedido_pela_tela_e_conferido(self):
        ctx = apoio.ContextoGravador(codigos=["", "1 11", "222"])
        p = PortalDoCodigo(ctx)
        self.assertTrue(p._resolver_codigo())
        self.assertEqual(p.enviados, ["111", "222"], "espaços colados junto saem")
        self.assertEqual(p.novos, 2, "um a pedido, outro depois do código recusado")
        titulos = [t for t, _, _ in ctx.pedidos_codigo]
        self.assertTrue(all("TJAL" in t for t in titulos))
        self.assertIn("Pedi um código novo", ctx.pedidos_codigo[1][1])
        self.assertIn("não aceitou", ctx.pedidos_codigo[2][1])
        self.assertIn("Pedi outro", ctx.pedidos_codigo[2][1])
        self.assertLessEqual(ctx.pedidos_codigo[0][2], 600)
        self.assertTrue(all(ctx.reenviaveis), "o código por e-mail pode ser pedido de novo")

    def test_sem_codigo_falha_com_orientacao(self):
        p = PortalDoCodigo(apoio.ContextoGravador(codigos=[]))
        with self.assertRaises(modelos.LoginFalhou) as caso:
            p._resolver_codigo()
        self.assertIn("não foi informado", str(caso.exception))

    def test_codigo_digitado_na_janela_do_navegador(self):
        p = PortalDoCodigo(apoio.ContextoGravador(codigos=[]), na_janela=True)
        self.assertTrue(p._resolver_codigo())

    def test_cancelar_no_dialogo_para_o_lote(self):
        ctx = apoio.ContextoGravador(codigos=[])
        ctx.cancelar()
        with self.assertRaises(modelos.Cancelado):
            PortalDoCodigo(ctx)._resolver_codigo()

    def test_cinco_recusas_desistem(self):
        ctx = apoio.ContextoGravador(codigos=["1", "2", "3", "4", "5", "6"])
        p = PortalDoCodigo(ctx, aceito="nunca")
        with self.assertRaises(modelos.LoginFalhou):
            p._resolver_codigo()
        self.assertEqual(len(p.enviados), 5)

    def test_tela_que_troca_no_envio_nao_derruba(self):
        ctx = apoio.ContextoGravador(codigos=["333"])
        p = PortalDoCodigo(ctx, na_janela=True)

        def quebra(codigo):
            raise RuntimeError("Execution context was destroyed")
        p._enviar_codigo = quebra
        self.assertTrue(p._resolver_codigo(), "a sessão já valia: segue")

    def test_erro_inesperado_no_login_vira_portal_indisponivel(self):
        p = PortalDeLogin()

        def quebra():
            raise RuntimeError("Target page, context or browser has been closed")
        p._entrar_com_senha = quebra
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            p.entrar()
        self.assertIn("Mostrar o navegador enquanto baixa", str(caso.exception))
        self.assertIn("esaj-login-erro", p.nav.diagnosticos)

    def test_sem_tela_do_codigo_devolve_falso(self):
        p = PortalDoCodigo(apoio.ContextoGravador())
        p._tela_do_codigo = lambda espera_s=45: (None, None)
        self.assertFalse(p._resolver_codigo())


class TestTelaDoCodigo(unittest.TestCase):
    def portal(self):
        p = PortalESAJ(NavegadorDeMentira(), TRIBUNAL, opcoes(), apoio.ContextoGravador(),
                       ("u", "s"))
        p._dormir = lambda s: None
        p._sessao_no_contexto = lambda: False
        return p

    def test_senha_expirada_avisa_na_hora(self):
        p = self.portal()
        p._senha_expirada = lambda: "Senha expirada. Cadastre nova senha."
        with self.assertRaises(modelos.LoginFalhou) as caso:
            p._tela_do_codigo(5)
        self.assertIn("expirou", str(caso.exception))
        self.assertIn("esaj-senha-expirada", p.nav.diagnosticos)

    def test_senha_recusada_nao_espera_a_tela_do_codigo(self):
        p = self.portal()
        p._senha_expirada = lambda: ""
        p._recusa_na_tela = lambda: True
        with self.assertRaises(modelos.LoginFalhou) as caso:
            p._tela_do_codigo(45)
        self.assertIn("recusou", str(caso.exception))

    def test_codigo_recusado_nao_e_senha_recusada(self):
        p = self.portal()
        aba = types.SimpleNamespace(url="https://portal.teste/sajcas/login")
        p.nav.abas = lambda: [aba]
        p._texto_da_pagina = lambda pagina=None: "Senha * Código inválido. Receber novo código"
        self.assertFalse(p._recusa_na_tela())
        p._texto_da_pagina = lambda pagina=None: "Senha * Usuário ou senha inválidos."
        self.assertTrue(p._recusa_na_tela())


class RelogioFalso:
    def __init__(self):
        self.agora = 0.0

    def monotonic(self):
        return self.agora

    def time(self):
        return 1_700_000_000 + self.agora

    def sleep(self, s):
        self.agora += s


class TestLoginNaJanela(unittest.TestCase):
    def portal(self, modo, sessoes):
        ctx = apoio.ContextoGravador()
        p = PortalESAJ(NavegadorDeMentira(), TRIBUNAL, opcoes(login={"esaj": modo}), ctx, None)
        respostas = list(sessoes)
        p.sessao_ativa = lambda: respostas.pop(0) if respostas else False
        p._esta_logado = lambda pagina=None: False
        p._sessao_no_contexto = lambda: False
        return p, ctx

    def test_manual_espera_o_usuario_entrar(self):
        p, ctx = self.portal("manual", [False, False, False, True])
        relogio = RelogioFalso()
        with mock.patch.object(esaj, "time", relogio):
            p.entrar()
        self.assertTrue(any("Conclua o login" in m for _, m in ctx.avisos))
        self.assertIn("https://portal.teste/sajcas/login", p.nav.visitas)

    def test_manual_com_prazo_esgotado(self):
        p, _ = self.portal("manual", [False] * 1000)
        with mock.patch.object(esaj, "time", RelogioFalso()):
            with self.assertRaises(modelos.LoginFalhou) as caso:
                p.entrar()
        texto = str(caso.exception)
        self.assertIn("passou-se 1 minuto sem o login", texto)
        self.assertNotIn("1 minutos", texto)
        # o campo da tela, e não a chave do config.ini
        self.assertIn("Ajustes › Acessos aos portais, campo “Esperar o login até (minutos)”", texto)
        self.assertNotIn("espera_login_minutos", texto)

    def test_certificado_sem_web_signer_avisa(self):
        p, ctx = self.portal("certificado", [False, True])
        with mock.patch.object(esaj, "time", RelogioFalso()):
            p.entrar()
        self.assertTrue(any("Web Signer" in m for _, m in ctx.avisos))

    def test_certificado_com_sessao_valida(self):
        p, ctx = self.portal("certificado", [True])
        p.entrar()
        self.assertEqual(ctx.avisos, [])


class PortalDeDownload(PortalESAJ):
    """Tudo o que toca a página é trocado por respostas prontas."""

    def __init__(self, ctx=None, senha_pedida=(False,), libera=True, info=INFO, arvore=ARVORE,
                 servidor="ok", pecas_ok=("101", "102", "104"), sessao=True, achar=None,
                 **op):
        super().__init__(NavegadorDeMentira(), TRIBUNAL, opcoes(**op),
                         ctx or apoio.ContextoGravador(), ("u", "s"))
        self.senha_pedida = list(senha_pedida)
        self.libera = libera
        self.info = info
        self.arvore = arvore
        self.servidor = servidor
        self.pecas_ok = set(pecas_ok)
        self.sessao = sessao
        self.achar = achar
        self.registro = []
        self.pasta_recusa = 0
        self.modal_tardio = False

    def achar_codigo(self, numero):
        self.registro.append(("achar", numero.formatado))
        if self.achar is not None:
            raise self.achar
        return "1K0001AAA0000"

    def achar_codigo_incidente(self, ordem, cd, senha, numero):
        self.registro.append(("incidente", ordem, cd, senha))
        return "1K0001AAA0001"

    def conferir_incidente(self, cd, ordem):
        self.registro.append(("conferir", cd, ordem))

    def precisa_senha(self):
        return self.senha_pedida.pop(0) if self.senha_pedida else False

    def liberar_segredo(self, senha):
        self.registro.append(("senha", senha))
        return self.libera

    def ler_pagina_processo(self):
        return self.info

    def abrir_pasta(self, cd):
        self.registro.append(("pasta", cd))
        if self.pasta_recusa:
            self.pasta_recusa -= 1
            raise modelos.SemAcesso("o e-SAJ não liberou a Pasta Digital")
        return self.arvore

    def modal_senha_visivel(self):
        return self.modal_tardio

    def gerar_pdf(self, pecas, cd, reabrir=None):
        if self.servidor == "falha":
            raise RuntimeError("o servidor não devolveu o localizador do PDF (HTTP 500: erro)")
        return "https://portal.teste/pastadigital/final.pdf"

    def pedir_arquivo(self, url, timeout_ms=300000):
        if "getMidia" in url:
            if self.servidor == "parar_na_midia":
                self.ctx.cancelar()
                raise modelos.Cancelado()
            return b"ID3" + b"x" * 500
        if self.servidor == "corrompido":
            return b"%PDF-1.4\n" + b"\x00lixo" * 40
        if self.servidor == "html":
            return b"<html><body>Sess\xc3\xa3o expirada</body></html>"
        return apoio.pdf_bytes(6, "servidor")

    def baixar_peca(self, parametros):
        cd = urllib.parse.parse_qs(parametros)["cdDocumento"][0]
        return apoio.pdf_bytes(1, f"peça {cd}") if cd in self.pecas_ok else None

    def sessao_ativa(self):
        return self.sessao

    def limpar_estado(self):
        self.registro.append(("limpar",))


class TestBaixar(apoio.PastaTemporaria):
    def destino(self, numero=N):
        return self.tmp / "Lote" / f"{numero.nome_arquivo}.pdf"

    def test_download_normal(self):
        p = PortalDeDownload()
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertEqual(r.paginas, 6)
        self.assertEqual(r.documentos, 3)
        self.assertEqual(r.incompleto, "6-7", "as folhas que a Pasta Digital não ofereceu")
        self.assertFalse(r.sigiloso)
        self.assertEqual(r.arquivo, str(self.destino()))
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 3, 6])
        capa = self.tmp / "Lote" / "_controle" / f"{N.nome_arquivo}_capa.txt"
        self.assertIn("Procedimento Comum Cível", capa.read_text(encoding="utf-8"))
        self.assertIn("gravação de audiência nos autos, não baixada", r.detalhe)
        self.assertNotIn("(ões)", r.detalhe)
        self.assertEqual([p.name for p in (self.tmp / "Lote").iterdir() if p.is_file()],
                         [f"{N.nome_arquivo}.pdf"], "na raiz do lote, só o PDF")

    def test_midias_quando_pedidas(self):
        p = PortalDeDownload(baixar_midias=True)
        r = p.baixar(N, self.destino())
        alvo = self.tmp / "Lote" / "_controle" / "midias" / N.nome_arquivo / "audiencia 1.mp3"
        self.assertTrue(alvo.exists())
        self.assertEqual(r.midias, [str(alvo)])

    def test_sigiloso_sem_senha(self):
        p = PortalDeDownload(senha_pedida=[True])
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.SIGILOSO_SEM_SENHA)
        self.assertTrue(r.sigiloso)
        self.assertIn("número ; senha", r.detalhe)
        self.assertFalse(self.destino().exists())
        self.assertIn(("limpar",), p.registro)

    def test_sigiloso_com_senha(self):
        p = PortalDeDownload(senha_pedida=[True])
        r = p.baixar(N, self.destino(), senha="abc123")
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        self.assertIn(("senha", "abc123"), p.registro)
        capa = self.tmp / "Lote" / "_controle" / f"{N.nome_arquivo}_capa.txt"
        self.assertIn("SEGREDO DE JUSTIÇA", capa.read_text(encoding="utf-8"))

    def test_senha_que_nao_libera(self):
        p = PortalDeDownload(senha_pedida=[True], libera=False)
        r = p.baixar(N, self.destino(), senha="errada")
        self.assertEqual(r.situacao, modelos.SIGILOSO_SEM_SENHA)
        self.assertIn("não liberou", r.detalhe)

    def test_modal_de_senha_que_aparece_tarde(self):
        p = PortalDeDownload(info=dict(INFO, movs=[]))
        p.modal_tardio = True
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.SIGILOSO_SEM_SENHA)
        p = PortalDeDownload(info=dict(INFO, movs=[]))
        p.modal_tardio = True
        r = p.baixar(N, self.destino(), senha="s")
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        self.assertIn(("senha", "s"), p.registro)

    def test_pasta_recusada_com_modal_na_tela_e_segredo(self):
        p = PortalDeDownload()
        p.pasta_recusa = 1
        p.modal_tardio = True       # só olhado depois da recusa (há movimentações)
        r = p.baixar(N, self.destino(), senha="s")
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        self.assertEqual([x for x in p.registro if x[0] == "pasta"], [("pasta", "1K0001AAA0000")] * 2)

    def test_pasta_recusada_sem_modal_e_sem_acesso(self):
        p = PortalDeDownload()
        p.pasta_recusa = 1
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.SEM_ACESSO)

    def test_peca_sigilosa_torna_o_processo_sigiloso(self):
        arvore = [dict(ARVORE[0], children=[{"data": dict(ARVORE[0]["children"][0]["data"],
                                                          documentoSigiloso=True)}]),
                  *ARVORE[1:]]
        r = PortalDeDownload(arvore=arvore).baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso, "a peça sigilosa não pode ir para o acervo da IA")
        self.assertIn("contém 1 peça sigilosa", r.detalhe)

    def test_sigilo_apurado_vale_para_a_tentativa_seguinte(self):
        # 1ª tentativa: a senha libera o processo, mas o PDF falha
        p = PortalDeDownload(senha_pedida=[True], servidor="falha", pecas_ok=())
        with self.assertRaises(Exception):
            p.baixar(N, self.destino(), senha="s")
        self.assertIn(N.nome_arquivo, p.sigilosos_apurados)
        # 2ª, na mesma sessão: o modal não volta e a página não fala em sigilo
        p.servidor, p.pecas_ok = "ok", {"101", "102", "104"}
        r = p.baixar(N, self.destino(), senha="s")
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)

    def test_sigilo_declarado_na_pagina(self):
        info = dict(INFO, texto="Classe: Divórcio Litigioso  Segredo de Justiça")
        r = PortalDeDownload(info=info).baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)

    def test_incidente_com_senha_e_conferido_depois_de_liberar(self):
        p = PortalDeDownload(senha_pedida=[True])
        r = p.baixar(N_INC, self.destino(N_INC), senha="s1")
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn(("incidente", 1, "1K0001AAA0000", "s1"), p.registro)
        self.assertIn(("pasta", "1K0001AAA0001"), p.registro)
        self.assertIn(("conferir", "1K0001AAA0000", 1), p.registro)
        self.assertTrue(self.destino(N_INC).name.endswith("-01.pdf"))

    def test_servidor_falha_e_monta_peca_a_peca(self):
        p = PortalDeDownload(servidor="falha", pecas_ok=("101", "102"))
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("peça a peça", r.detalhe)
        self.assertIn("1 peça não veio e tem página de aviso no lugar", r.detalhe)
        self.assertNotIn("(s)", r.detalhe)
        self.assertEqual(r.incompleto, "6-7, 8")
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual(len(doc), 4)
            self.assertIn("não pôde ser baixada", doc[3].get_text())
            self.assertIn("Termo de Audiência", doc[3].get_text())

    def test_servidor_entrega_html_e_monta_peca_a_peca(self):
        r = PortalDeDownload(servidor="html").baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("peça a peça", r.detalhe)

    def test_pdf_do_servidor_corrompido_vira_peca_a_peca(self):
        r = PortalDeDownload(servidor="corrompido").baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("peça a peça", r.detalhe)
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual(doc.page_count, 4, "uma página por bloco da árvore (dublê)")

    def test_parar_durante_as_gravacoes_nao_desfaz_o_processo(self):
        """O PDF já está gravado: o item termina (e o sigiloso ainda sai do
        acervo, pelo motor); só as gravações ficam para depois."""
        p = PortalDeDownload(servidor="parar_na_midia", baixar_midias=True,
                             senha_pedida=[True])
        r = p.baixar(N, self.destino(), senha="s")
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        self.assertEqual(r.midias, [])
        self.assertTrue(self.destino().exists())

    def test_midia_que_nao_grava_no_disco_nao_derruba_o_processo(self):
        """Com o erro subindo, o processo virava ERRO com o PDF já na pasta -
        e um sigiloso ficaria no acervo compartilhado com a IA."""
        real = esaj.sistema.gravar_atomico

        def gravar(destino, dados):
            if "midias" in str(destino):
                raise OSError(28, "Não há espaço suficiente no disco")
            return real(destino, dados)
        p = PortalDeDownload(baixar_midias=True, senha_pedida=[True])
        with mock.patch.object(esaj.sistema, "gravar_atomico", gravar):
            r = p.baixar(N, self.destino(), senha="s")
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        self.assertEqual(r.midias, [])
        self.assertTrue(self.destino().exists())

    def test_peca_a_peca_com_servidor_fora_desiste_cedo(self):
        arvore = [{"data": {"title": f"Doc {i}", "cdDocumento": 200 + i},
                   "children": [{"data": {"parametros": par(200 + i, i, i), "nuPaginas": 1}}]}
                  for i in range(1, 61)]
        p = PortalDeDownload(servidor="falha", arvore=arvore, pecas_ok=())
        pedidas = []
        original = p.baixar_peca
        p.baixar_peca = lambda par_: pedidas.append(par_) or original(par_)
        with self.assertRaises(RuntimeError) as caso:
            p.baixar(N, self.destino())
        self.assertIn("servidor do tribunal parece fora do ar", str(caso.exception))
        self.assertEqual(len(pedidas), esaj.MAX_PECAS_SEGUIDAS_FALHANDO,
                         "60 peças x ~40 s seria quase uma hora para nada")
        self.assertFalse(self.destino().exists())

    def test_peca_a_peca_que_comecou_bem_vai_ate_o_fim(self):
        arvore = [{"data": {"title": f"Doc {i}", "cdDocumento": 200 + i},
                   "children": [{"data": {"parametros": par(200 + i, i, i), "nuPaginas": 1}}]}
                  for i in range(1, 11)]
        p = PortalDeDownload(servidor="falha", arvore=arvore, pecas_ok=("201",))
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertEqual(r.paginas, 10, "uma peça e nove páginas de aviso")
        self.assertIn("9 peças não vieram e têm página de aviso no lugar", r.detalhe)

    def test_sem_pdf_nem_pecas_e_erro_para_repetir(self):
        p = PortalDeDownload(servidor="falha", pecas_ok=())
        with self.assertRaises(RuntimeError) as caso:
            p.baixar(N, self.destino())
        self.assertIn("nem o PDF único nem as peças", str(caso.exception))
        self.assertFalse(self.destino().exists())
        self.assertIn(("limpar",), p.registro)
        self.assertTrue(p.nav.diagnosticos)

    def test_nao_encontrado(self):
        p = PortalDeDownload(achar=modelos.ProcessoNaoEncontrado("não encontrado no 1º grau"))
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.NAO_ENCONTRADO)
        self.assertIn("1º grau", r.detalhe)

    def test_cara_de_sessao_perdida(self):
        erro = RuntimeError("não consegui identificar o processo na consulta (sem acesso, "
                            "ou sessão expirada?)")
        with self.assertRaises(modelos.SessaoPerdida):
            PortalDeDownload(achar=erro, sessao=False).baixar(N, self.destino())
        # com a sessão de pé, é erro comum (o motor repete)
        with self.assertRaises(RuntimeError) as caso:
            PortalDeDownload(achar=erro, sessao=True).baixar(N, self.destino())
        self.assertNotIsInstance(caso.exception, modelos.SessaoPerdida)

    def test_falha_de_processo_sigiloso_nao_vai_para_o_diagnostico(self):
        """A tela do processo em segredo de justiça (apurado numa tentativa
        anterior, ou já sabido pelo motor: pauta, pasta de sigilosos) traz as
        partes: não vai para Logs\\diagnostico, que se envia ao suporte."""
        p = PortalDeDownload(servidor="falha", pecas_ok=())
        p.sigilosos_apurados.add(N.nome_arquivo)
        with self.assertRaises(RuntimeError), self.assertLogs("download", "WARNING") as reg:
            p.baixar(N, self.destino())
        self.assertEqual(p.nav.diagnosticos, [])
        self.assertTrue(any("segredo de justiça" in linha for linha in reg.output))
        p = PortalDeDownload(servidor="falha", pecas_ok=())
        p.nav.sigiloso_em_curso = True               # o motor avisou o navegador
        with self.assertRaises(RuntimeError), self.assertLogs("download", "WARNING"):
            p.baixar(N, self.destino())
        self.assertEqual(p.nav.diagnosticos, [])

    def test_erro_transitorio_nao_gera_diagnostico(self):
        p = PortalDeDownload(achar=RuntimeError("Target page, context or browser has been closed"))
        with self.assertRaises(RuntimeError):
            p.baixar(N, self.destino())
        self.assertEqual(p.nav.diagnosticos, [])

    def test_cancelado_antes_de_comecar(self):
        ctx = apoio.ContextoGravador()
        ctx.cancelar()
        with self.assertRaises(modelos.Cancelado):
            PortalDeDownload(ctx=ctx).baixar(N, self.destino())


class PortalDeConsulta(PortalESAJ):
    """achar_codigo com a página trocada por respostas prontas."""

    def __init__(self, redireciona=None, html="", na_lista=None, texto="", paginas_digitos=""):
        nav = NavegadorDeMentira()
        nav.pagina.goto = lambda url, **k: None
        super().__init__(nav, TRIBUNAL, opcoes(), apoio.ContextoGravador(), None)
        self.redireciona = redireciona
        self.html_ = html
        self.na_lista = na_lista
        self.texto_ = texto
        self.paginas_digitos = paginas_digitos
        self.visitas = []
        self._dormir = lambda s: None

    def ir_para(self, url, timeout=60000, tentativas=3):
        self.visitas.append(url)
        self.nav.pagina.url = (self.redireciona if (self.redireciona and "search.do" in url)
                               else url)

    def _html(self, pagina=None):
        if "show.do" in (self.nav.pagina.url or ""):
            return self.paginas_digitos
        return self.html_

    def _texto_da_pagina(self, pagina=None):
        return self.texto_

    def _codigo_na_lista(self, numero):
        return self.na_lista

    def _esperar_carga(self, pagina=None, ms=10000):
        pass

    def modal_senha_visivel(self):
        return False


class TestListaDaBusca(unittest.TestCase):
    def test_principal_antes_do_incidente_de_mesmo_numero(self):
        """Principal e incidente aparecem com o mesmo número na lista; o
        primeiro da lista podia ser o incidente, gravado com o nome do principal."""
        nav = NavegadorDeMentira()
        pares = [{"h": "show.do?processo.codigo=1K0001AAA0001",
                  "t": f"{N.principal} Cumprimento de sentença"},
                 {"h": "show.do?processo.codigo=1K0001AAA0000",
                  "t": f"{N.principal} Procedimento Comum Cível"},
                 {"h": "show.do?processo.codigo=1K0009ZZZ0000", "t": "outro processo"}]
        nav.pagina.evaluate = lambda js, *a: pares
        p = PortalESAJ(nav, TRIBUNAL, opcoes(), apoio.ContextoGravador(), None)
        self.assertEqual(p._codigo_na_lista(N), "1K0001AAA0000")
        nav.pagina.evaluate = lambda js, *a: pares[:1]
        self.assertEqual(p._codigo_na_lista(N), "1K0001AAA0001", "sem o principal, o que houver")
        nav.pagina.evaluate = lambda js, *a: pares[2:]
        self.assertIsNone(p._codigo_na_lista(N))


class TestConsulta(unittest.TestCase):
    def test_busca_que_abre_o_processo_direto(self):
        p = PortalDeConsulta(redireciona="https://portal.teste/cpopg/show.do?processo.codigo=1K9")
        self.assertEqual(p.achar_codigo(N), "1K9")
        self.assertEqual(len(p.visitas), 1)
        self.assertIn("foroNumeroUnificado=0056", p.visitas[0])

    def test_lista_usa_o_link_deste_numero(self):
        html = ("<a href='show.do?processo.codigo=1KOUTRO0000'>outro</a>"
                "<a href='show.do?processo.codigo=1KCERTO0000'>certo</a>")
        p = PortalDeConsulta(html=html, na_lista="1KCERTO0000", paginas_digitos=N.formatado)
        self.assertEqual(p.achar_codigo(N), "1KCERTO0000")
        self.assertIn("processo.codigo=1KCERTO0000&processo.foro=56", p.visitas[-1])

    def test_lista_de_um_processo_so(self):
        html = ("<a href='show.do?processo.codigo=1KUNICO0000'>x</a>"
                "<a href='show.do?processo.codigo=1KUNICO0000&y'>y</a>")
        p = PortalDeConsulta(html=html, paginas_digitos=f"Processo {N.formatado}")
        self.assertEqual(p.achar_codigo(N), "1KUNICO0000")

    def test_lista_ambigua_nao_chuta(self):
        html = ("<a href='show.do?processo.codigo=1KA0000'>a</a>"
                "<a href='show.do?processo.codigo=1KB0000'>b</a>")
        with self.assertRaises(RuntimeError) as caso:
            PortalDeConsulta(html=html).achar_codigo(N)
        self.assertIn("autos trocados", str(caso.exception))

    def test_pagina_aberta_de_outro_processo(self):
        html = "<a href='show.do?processo.codigo=1KUNICO0000'>x</a>"
        outro = apoio.numero("0700999", tr="02")
        p = PortalDeConsulta(html=html, paginas_digitos=f"Processo {outro.formatado}")
        with self.assertRaises(RuntimeError) as caso:
            p.achar_codigo(N)
        self.assertIn("não traz este número", str(caso.exception))

    def test_nao_encontrado(self):
        p = PortalDeConsulta(html="<p>Não existem informações disponíveis para os "
                                  "parâmetros informados.</p>",
                             texto="Não existem informações disponíveis para os parâmetros "
                                   "informados.")
        with self.assertRaises(modelos.ProcessoNaoEncontrado):
            p.achar_codigo(N)

    def test_multiplas_consultas_insiste_tres_vezes(self):
        p = PortalDeConsulta(html="Não é permitido realizar múltiplas consultas simultâneas")
        with self.assertRaises(RuntimeError):
            p.achar_codigo(N)
        self.assertEqual(len([v for v in p.visitas if "search.do" in v]), 3)
        self.assertTrue(p.nav.diagnosticos)


# ------------------------------------------------------------ rede e pasta
class Resposta:
    def __init__(self, status, corpo=b""):
        self.status = status
        self._corpo = corpo

    def body(self):
        return self._corpo


class CanalFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def get(self, url, timeout=0, headers=None):
        self.pedidos.append(url)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TestPedirArquivo(unittest.TestCase):
    def portal(self, respostas):
        nav = NavegadorDeMentira()
        nav.contexto = types.SimpleNamespace(request=CanalFalso(respostas))
        p = PortalESAJ(nav, TRIBUNAL, opcoes(), apoio.ContextoGravador(), None)
        p._dormir = lambda s: None
        p.canal_pelo_proxy = lambda: False
        p.pela_janela = []
        p.baixar_pelo_navegador = lambda url: p.pela_janela.append(url) or b"%PDF-janela"
        return p

    def test_5xx_e_repetido(self):
        p = self.portal([Resposta(503), Resposta(502), Resposta(200, b"%PDF-ok")])
        self.assertEqual(p.pedir_arquivo("/pastadigital/x.pdf"), b"%PDF-ok")
        self.assertEqual(p.nav.contexto.request.pedidos[0], "https://portal.teste/pastadigital/x.pdf")
        self.assertEqual(len(p.nav.contexto.request.pedidos), 3)

    def test_5xx_que_nao_passa_vira_erro_sem_ir_a_janela(self):
        p = self.portal([Resposta(500)] * 3)
        with self.assertRaises(RuntimeError) as caso:
            p.pedir_arquivo("https://portal.teste/a")
        self.assertIn("HTTP 500", str(caso.exception))
        self.assertEqual(p.pela_janela, [])

    def test_4xx_nao_insiste(self):
        p = self.portal([Resposta(404), Resposta(200, b"%PDF")])
        with self.assertRaises(RuntimeError) as caso:
            p.pedir_arquivo("https://portal.teste/a")
        self.assertIn("recusou", str(caso.exception))
        self.assertEqual(len(p.nav.contexto.request.pedidos), 1)

    def test_rede_que_cai_tenta_pela_janela(self):
        erro = RuntimeError("connect ECONNRESET 1.2.3.4:443")
        p = self.portal([erro, erro, erro])
        self.assertEqual(p.pedir_arquivo("https://portal.teste/a"), b"%PDF-janela")
        self.assertEqual(p.pela_janela, ["https://portal.teste/a"])

    def test_tempo_esgotado_e_repetido(self):
        p = self.portal([RuntimeError("Timeout 300000ms exceeded"), Resposta(200, b"%PDF-1")])
        self.assertEqual(p.pedir_arquivo("https://portal.teste/a"), b"%PDF-1")

    def test_cancelado_no_meio(self):
        p = self.portal([Resposta(503)] * 3)
        p.ctx.cancelar()
        with self.assertRaises(modelos.Cancelado):
            p.pedir_arquivo("https://portal.teste/a")

    def test_nome_que_nao_resolve_passa_ao_proxy_sem_insistir(self):
        p = self.portal([RuntimeError("getaddrinfo ENOTFOUND www2.tjal.jus.br")] * 3)
        proxy = CanalFalso([Resposta(200, b"%PDF-proxy")])
        p.canal_pelo_proxy = lambda: proxy
        self.assertEqual(p.pedir_arquivo("https://portal.teste/a"), b"%PDF-proxy")
        self.assertEqual(len(p.nav.contexto.request.pedidos), 1, "não repete o que não muda")
        self.assertEqual(p.pela_janela, [])

    def test_certificado_da_rede_cai_na_janela(self):
        p = self.portal([RuntimeError("self-signed certificate in certificate chain")] * 3)
        self.assertEqual(p.pedir_arquivo("https://portal.teste/a"), b"%PDF-janela")
        self.assertEqual(len(p.nav.contexto.request.pedidos), 1)
        self.assertEqual(p.pela_janela, ["https://portal.teste/a"])


class TestSessaoAtiva(unittest.TestCase):
    def portal(self, resposta, pela_aba=(200, '{"usuarioLogado": true}')):
        nav = NavegadorDeMentira()

        class Canal:
            def get(self, url, timeout=0, headers=None):
                if isinstance(resposta, Exception):
                    raise resposta
                return resposta
        nav.contexto = types.SimpleNamespace(request=Canal())
        p = PortalESAJ(nav, TRIBUNAL, opcoes(), apoio.ContextoGravador(), None)
        p.pela_aba = []

        def buscar(url, metodo="GET", corpo=None, cabecalhos=None):
            p.pela_aba.append(url)
            return pela_aba
        p._buscar_texto = buscar
        return p

    def test_rede_do_forum_pergunta_pela_aba(self):
        """O canal direto não alcança o portal atrás do proxy; sem a aba, a
        sessão pareceria sempre caída (Pasta recusada -> novo login)."""
        p = self.portal(RuntimeError("getaddrinfo ENOTFOUND portal.teste"))
        self.assertTrue(p.sessao_ativa())
        self.assertTrue(p.pela_aba[0].startswith("/esaj/api/auth/session?_="))
        p = self.portal(RuntimeError("connect ETIMEDOUT"), pela_aba=(200, '{"usuarioLogado": false}'))
        self.assertFalse(p.sessao_ativa())

    def test_resposta_do_canal_direto_vale(self):
        resp = types.SimpleNamespace(status=200, json=lambda: {"usuarioLogado": True})
        p = self.portal(resp)
        self.assertTrue(p.sessao_ativa())
        self.assertEqual(p.pela_aba, [])
        p = self.portal(types.SimpleNamespace(status=401, json=lambda: {}))
        self.assertFalse(p.sessao_ativa())
        self.assertEqual(p.pela_aba, [])

    def test_aba_fora_do_portal_nao_e_consultada(self):
        p = self.portal(RuntimeError("getaddrinfo ENOTFOUND portal.teste"))
        p.nav.pagina.url = "about:blank"
        self.assertFalse(p.sessao_ativa())
        self.assertEqual(p.pela_aba, [])

    def test_novo_login_descarta_o_canal_pelo_proxy(self):
        """O canal pelo proxy leva cópia dos cookies de quando nasceu."""
        p = self.portal(RuntimeError("x"))
        descartes = []
        p._canal_proxy = types.SimpleNamespace(dispose=lambda: descartes.append(1))
        p._entrar_com_senha = lambda: None
        p.entrar()
        self.assertIsNone(p._canal_proxy)
        self.assertEqual(descartes, [1])


class TestPastaDigital(unittest.TestCase):
    def portal(self, respostas, sessao=True):
        p = PortalESAJ(NavegadorDeMentira(), TRIBUNAL, opcoes(), apoio.ContextoGravador(), None)
        p.chamadas = []
        fila = list(respostas)

        def buscar(url, metodo="GET", corpo=None, cabecalhos=None):
            p.chamadas.append((url, metodo, corpo, cabecalhos))
            return fila.pop(0)
        p._buscar_texto = buscar
        p._dormir = lambda s: None
        p.sessao_ativa = lambda: sessao
        return p

    def test_corpo_do_pedido_igual_ao_da_pagina(self):
        pecas = [{"parametros": "cdDocumento=1&numInicial=1&deTipoDocConsulta=Petição Inicial",
                  "cdDocumento": "1"},
                 {"parametros": "cdDocumento=2&numInicial=3", "cdDocumento": "2"}]
        p = self.portal([(200, "0123abcd-0123-4567-89ab-0123456789ab"), (200, ""),
                         (200, "https://portal.teste/pastadigital/doc.pdf")])
        url = p.gerar_pdf(pecas, "1K0001AAA0000")
        self.assertEqual(url, "https://portal.teste/pastadigital/doc.pdf")
        url0, metodo, corpo, cab = p.chamadas[0]
        self.assertEqual(url0, "/pastadigital/salvarDocumentoPreparado.do")
        self.assertEqual(metodo, "POST")
        # o mesmo que encodeURIComponent(p).replace(/%20/g, '+') da página
        self.assertEqual(corpo,
                         "itensPdfSelecionados=cdDocumento%3D1%26numInicial%3D1%26deTipoDocConsulta"
                         "%3DPeti%C3%A7%C3%A3o+Inicial&itensPdfSelecionados=cdDocumento%3D2%26"
                         "numInicial%3D3&cdProcesso=1K0001AAA0000&cdDocumento=2"
                         "&separarDocumentos=false&acessoPeloPetsg=")
        self.assertEqual(cab["X-Requested-With"], "XMLHttpRequest")
        self.assertIn("localizador=0123abcd", p.chamadas[1][2])

    def test_localizador_invalido(self):
        p = self.portal([(200, "<html>erro</html>")])
        with self.assertRaises(RuntimeError) as caso:
            p.gerar_pdf([{"parametros": "a=1", "cdDocumento": "1"}], "cd")
        self.assertIn("localizador", str(caso.exception))

    def test_localizador_expirado_reabre_uma_vez(self):
        p = self.portal([(200, "A sessão expirou"), (200, "0123abcd-0123-4567-89ab-0123456789ab"),
                         (200, "https://x/doc.pdf")])
        reaberturas = []

        def reabrir():
            reaberturas.append(1)
            return [{"parametros": "a=2", "cdDocumento": "2"}]
        self.assertEqual(p.gerar_pdf([{"parametros": "a=1", "cdDocumento": "1"}], "cd", reabrir),
                         "https://x/doc.pdf")
        self.assertEqual(reaberturas, [1])

    def test_5xx_seguidos_na_montagem(self):
        p = self.portal([(200, "0123abcd-0123-4567-89ab-0123456789ab"), (500, "erro"),
                         (502, "erro"), (503, "erro")])
        with self.assertRaises(RuntimeError) as caso:
            p.gerar_pdf([{"parametros": "a=1", "cdDocumento": "1"}], "cd")
        self.assertIn("HTTP 503", str(caso.exception))

    def test_pasta_sem_acesso(self):
        p = self.portal([(200, "Não foi possível validar o seu acesso.")], sessao=True)
        with self.assertRaises(modelos.SemAcesso):
            p.abrir_pasta("cd")

    def test_pasta_sem_acesso_por_sessao_caida(self):
        p = self.portal([(200, "Não foi possível validar o seu acesso.")], sessao=False)
        with self.assertRaises(modelos.SessaoPerdida):
            p.abrir_pasta("cd")

    def test_pasta_com_resposta_estranha(self):
        p = self.portal([(500, "<html>Erro interno</html>")])
        with self.assertRaises(RuntimeError) as caso:
            p.abrir_pasta("cd")
        self.assertIn("Pasta Digital", str(caso.exception))


class TestPortalSemEndereco(unittest.TestCase):
    def test_catalogo_sem_base(self):
        t = Tribunal(chave="8.99", sigla="TJXX", nome="x", sistema="esaj", urls={})
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            PortalESAJ(NavegadorDeMentira(), t, opcoes(), None, None)
        self.assertIn("tribunais.json", str(caso.exception))


if __name__ == "__main__":
    unittest.main()
