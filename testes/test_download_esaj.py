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
from datetime import datetime
from pathlib import Path
from unittest import mock

import pymupdf

from helestron.download import esaj, modelos
from helestron.download.esaj import PortalESAJ
from helestron.nucleo import paginacao
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

    def test_descrever_buracos(self):
        self.assertEqual(esaj.descrever_buracos([(6, 7), (10, 10)]), "6-7, 10")
        self.assertEqual(paginacao.descrever_folhas({6, 7, 8, 40}), "6-8, 40")

    def test_contar_documentos(self):
        self.assertEqual(esaj.contar_documentos(esaj.extrair_pecas(ARVORE)), 3)


def documento(titulo, cd, blocos, data="01/01/2024"):
    """Um documento da árvore, com um filho por bloco (ini, fim) numerado."""
    return {"data": {"title": titulo, "cdDocumento": cd, "dtInclusao": data},
            "children": [{"data": {"parametros": par(cd, a, b), "nuPaginas": b - a + 1}}
                         for a, b in blocos]}


def sem_numero(titulo, cd, paginas):
    """Documento listado sem numInicial/numFinal (só nuPaginas)."""
    return {"data": {"title": titulo, "cdDocumento": cd},
            "children": [{"data": {"parametros": f"cdDocumento={cd}&idDocumento=S{cd}",
                                   "nuPaginas": paginas}}]}


class TestPlanoDeFolhas(unittest.TestCase):
    """A página N do PDF é a folha N: o plano diz que bloco fornece cada folha."""

    def plano(self, arvore):
        return esaj.planejar_folhas(esaj.extrair_pecas(arvore))

    def test_arvore_com_folhas_nao_oferecidas(self):
        pl = self.plano(ARVORE)
        self.assertEqual([(b.ini, b.fim) for b in pl.blocos], [(1, 2), (3, 4), (5, 5), (8, 8)])
        self.assertEqual(pl.ultima, 8)
        self.assertEqual(pl.nao_oferecidas, {6: ("N", ""), 7: ("N", "")})
        self.assertEqual(pl.anomalias, [])
        self.assertEqual(pl.faixas(), [(1, 2, [1, 2]), (3, 4, [3, 4]), (5, 5, [5]), (8, 8, [8])])

    def test_indice_que_comeca_depois_da_folha_1(self):
        pl = self.plano([documento("Contestação", 1, [(3, 5)]), documento("Termo", 2, [(6, 6)])])
        self.assertEqual(pl.ultima, 6)
        self.assertEqual(sorted(pl.nao_oferecidas), [1, 2], "as folhas iniciais também têm aviso")

    def test_arvore_fora_de_ordem(self):
        pl = self.plano([documento("Sentença", 9, [(9, 9)]), documento("Inicial", 3, [(3, 4)]),
                         documento("Laudo", 5, [(5, 7)])])
        self.assertEqual([(b.ini, b.fim) for b in pl.blocos], [(3, 4), (5, 7), (9, 9)])
        envio = pl.pecas_envio()
        self.assertEqual([p["pagina_inicial"] for p in envio], ["3", "5", "9"],
                         "o servidor monta na ordem pedida: a das folhas")
        self.assertEqual(envio.cd_documento, "5", "o pedido leva a última peça da árvore")
        self.assertEqual(sorted(pl.nao_oferecidas), [1, 2, 8])

    def test_bloco_repetido_e_faixas_sobrepostas(self):
        pl = self.plano([documento("Inicial", 3, [(3, 4)]), documento("Inicial", 3, [(3, 4)]),
                         documento("Laudo", 5, [(5, 7)]), documento("Outra", 6, [(7, 8)])])
        self.assertEqual([(b.ini, b.fim, b.proprias) for b in pl.blocos],
                         [(3, 4, [3, 4]), (5, 7, [5, 6, 7]), (7, 8, [8])],
                         "uma cópia só; a fl. 7 fica com a primeira peça que a traz")
        self.assertEqual(pl.ultima, 8)
        self.assertTrue(any("listadas duas vezes" in a for a in pl.anomalias), pl.anomalias)
        self.assertTrue(any(a.startswith("fl. 7 também na faixa") for a in pl.anomalias),
                        pl.anomalias)
        self.assertFalse(any("(s)" in a for a in pl.anomalias))

    def test_bloco_sem_numeracao_posicionado_pelo_vao(self):
        arvore = [documento("Inicial", 1, [(1, 2)]), sem_numero("Procuração", 2, 2),
                  documento("Contestação", 3, [(5, 5)])]
        pl = self.plano(arvore)
        self.assertEqual([(b.ini, b.fim) for b in pl.blocos], [(1, 2), (3, 4), (5, 5)])
        self.assertEqual(pl.blocos[1].peca["tipo"], "Procuração")
        self.assertEqual(pl.nao_oferecidas, {})

    def test_bloco_sem_numeracao_que_nao_cabe_no_vao(self):
        arvore = [documento("Inicial", 1, [(1, 2)]), sem_numero("Procuração", 2, 5),
                  documento("Contestação", 3, [(5, 5)]),
                  {"data": {"title": "Invertida", "cdDocumento": 4},
                   "children": [{"data": {"parametros": par(4, 9, 7), "nuPaginas": 1}}]}]
        pl = self.plano(arvore)
        self.assertEqual([(b.ini, b.fim) for b in pl.blocos], [(1, 2), (5, 5)])
        self.assertEqual(pl.nao_oferecidas[3][0], "S", "o vão é o da peça sem numeração")
        self.assertIn("Procuração", pl.nao_oferecidas[4][1])
        self.assertEqual(len(pl.sem_numeracao), 2)
        self.assertIn("1 peça com numeração de folhas inválida", pl.anomalias)
        self.assertIn("2 peças listadas sem numeração de folhas ficaram fora do PDF", pl.anomalias)

    def test_paginas_declaradas_diferentes_da_faixa(self):
        arvore = [{"data": {"title": "Inicial", "cdDocumento": 1},
                   "children": [{"data": {"parametros": par(1, 1, 2), "nuPaginas": 3}}]}]
        pl = self.plano(arvore)
        self.assertEqual(pl.anomalias, ["fls. 1-2: a Pasta Digital diz 3 páginas"])
        self.assertEqual(pl.ultima, 2, "vale a faixa")

    def test_sem_numeracao_nenhuma(self):
        pl = esaj.planejar_folhas([{"parametros": "x", "cdDocumento": "1"}])
        self.assertEqual(pl.blocos, [])
        self.assertEqual(pl.ultima, 0)
        self.assertEqual(esaj.planejar_folhas([]).blocos, [])

    def test_marcadores_em_folhas(self):
        pl = self.plano(ARVORE)
        marcas = esaj.marcadores_de(pl, {6: "N", 7: "N"})
        self.assertEqual([(t, p) for _, t, p in marcas],
                         [("Petição Inicial (fls. 1-2) - 01/02/2024", 1),
                          ("Contestação (fls. 3-5) - 10/03/2024", 3),
                          ("Fls. 6-7 — não disponibilizadas pelo e-SAJ", 6),
                          ("Termo de Audiência (fl. 8) - 20/04/2024", 8)])

    def test_marcador_proprio_para_cada_sequencia_de_avisos(self):
        pl = self.plano(ARVORE)
        marcas = esaj.marcadores_de(pl, {4: "C", 5: "B", 6: "N", 7: "N", 8: "B"})
        self.assertEqual([p for _, _, p in marcas], [1, 3, 4, 5, 6, 8])
        titulos = [t for _, t, _ in marcas]
        self.assertEqual(titulos[1], "Contestação (fl. 3) - 10/03/2024")
        self.assertEqual(titulos[2],
                         "Fl. 4 — não disponibilizada pelo e-SAJ (Contestação - 10/03/2024)")
        self.assertEqual(titulos[4], "Fls. 6-7 — não disponibilizadas pelo e-SAJ")
        self.assertEqual(titulos[5], "Fl. 8 — não disponibilizada pelo e-SAJ "
                                     "(Termo de Audiência - 20/04/2024)")

    def test_frases_por_motivo(self):
        pl = self.plano(ARVORE)
        frases = esaj.frases_das_ausencias(pl, {6: "N", 7: "N", 8: "B", 4: "C", 1: "I", 2: "I"})
        self.assertEqual(frases, [
            "fls. 6-7 não oferecidas pela Pasta Digital (página de aviso no lugar)",
            "fl. 8: 1 peça não veio e tem página de aviso no lugar",
            "fls. 1-2: o arquivo de 1 peça veio inválido (página de aviso no lugar)",
            "fl. 4: o arquivo de 1 peça veio com páginas a menos (página de aviso no lugar)"])

    def test_documento_de_varios_blocos(self):
        pl = self.plano(ARVORE)
        self.assertEqual(pl.no_documento(0), (2, 0))
        self.assertEqual(pl.no_documento(1), (3, 0), "contestação: fls. 3-5, bloco 3-4")
        self.assertEqual(pl.no_documento(2), (3, 2), "o bloco da fl. 5 é a 3ª página dela")


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

    # ------------------------------------------------------------ capa v2
    INFO_V2 = dict(
        INFO,
        movs=[{"data": f"{(i % 28) + 1:02d}/03/2024", "texto": f"Movimentação {i}"}
              for i in range(75)] + [{"data": "01/02/2024", "texto": "Juntada de petição"},
                                     {"data": "01/02/2024", "texto": "Juntada de petição"}],
        marcas=["Prioridade Idoso"],
        cabecalho="Classe Assunto Foro Justiça Gratuita",
        extras={"outros_numeros": "0001234-56.2023.8.02.0001",
                "processo_principal": "0700001-11.2024.8.02.0001"},
        secoes={
            "incidentes": [
                {"celulas": ["15/05/2024", "0700001-11.2024.8.02.0001/01 Cumprimento de sentença"],
                 "codigo": "1K0001AAA0001"}],
            "audiencias": [{"celulas": ["20/04/2024", "Conciliação", "Realizada", "2"]}],
            "historico_classes": [{"celulas": ["01/02/2024", "Evolução", "Procedimento Comum Cível",
                                               "Cível", ""]}],
            "peticoes_diversas": [{"celulas": ["05/03/2024", "Contestação"]}],
            "apensos": [{"celulas": ["Não há processos apensados, entranhados e unificados a "
                                     "este processo."]}],
        },
        codigo="1K0001AAA0000",
        url="https://portal.teste/cpopg/show.do?processo.codigo=1K0001AAA0000&processo.foro=1")

    def test_capa_v2_todas_as_movimentacoes_e_as_secoes(self):
        manifesto = paginacao.manifesto_esaj(N.formatado, 8, {6: "N", 7: "N"}, origem="servidor",
                                             tribunal="TJAL")
        texto = esaj.formatar_capa(self.INFO_V2, N, "TJAL", manifesto=manifesto)
        # os títulos da 1.0.1 continuam
        for titulo in ("== Capa ==", "== Partes ==", "== Movimentações (77) =="):
            self.assertIn(titulo, texto)
        # sem o limite de 60, e as duas movimentações iguais do mesmo dia ficam
        self.assertNotIn("e mais", texto)
        self.assertIn("Movimentação 74", texto)
        self.assertEqual(texto.count("01/02/2024  Juntada de petição"), 2)
        self.assertIn("== Marcas ==\nPrioridade Idoso\nJustiça gratuita\n", texto)
        self.assertIn("Outros números: 0001234-56.2023.8.02.0001", texto)
        self.assertIn("Processo principal: 0700001-11.2024.8.02.0001", texto)
        self.assertIn("Folhas 1 a 8 (última oferecida pela Pasta Digital)", texto)
        self.assertIn(f"Paginação: {paginacao.resumo(manifesto)}", texto)
        self.assertIn("folhas com página de aviso: 6-7", texto)
        self.assertIn("== Incidentes, ações incidentais, recursos e execuções de sentenças (1) ==\n"
                      "15/05/2024  0700001-11.2024.8.02.0001/01 Cumprimento de sentença", texto)
        self.assertIn("== Audiências (1) ==\n20/04/2024  Conciliação - Realizada - 2", texto)
        self.assertIn("== Histórico de classes (1) ==", texto)
        self.assertIn("== Petições diversas (1) ==\n05/03/2024  Contestação", texto)
        self.assertNotIn("Apensos", texto, "'Não há...' não é apenso")
        # as seções vêm depois das movimentações: a ordem da 1.0.1 fica
        self.assertLess(texto.index("== Movimentações"), texto.index("== Audiências"))

    def test_capa_json(self):
        manifesto = paginacao.manifesto_esaj(N.formatado, 8, {6: "N"}, tribunal="TJAL")
        d = esaj.dados_da_capa(self.INFO_V2, N, "TJAL", sigiloso=False, manifesto=manifesto)
        self.assertEqual((d["formato"], d["sistema"], d["processo"], d["tribunal"]),
                         ("helestron.capa/2", "esaj", N.formatado, "TJAL"))
        # chaves de máquina no JSON (no capa.txt ficam os rótulos da página)
        self.assertEqual(d["capa"], {"classe": "Procedimento Comum Cível", "juiz": "Fulano de Tal"})
        self.assertEqual(esaj._chave_da_capa("Outro Campo Ção"), "outro_campo_cao")
        self.assertEqual((d["prioridade"], d["justica_gratuita"], d["segredo"], d["idoso"]),
                         (True, True, False, True))
        self.assertEqual(len(d["movimentacoes"]), 77)
        self.assertEqual(d["incidentes"], [{
            "data": "15/05/2024", "texto": "0700001-11.2024.8.02.0001/01 Cumprimento de sentença",
            "celulas": ["15/05/2024", "0700001-11.2024.8.02.0001/01 Cumprimento de sentença"],
            "numero": "0700001-11.2024.8.02.0001/01", "codigo": "1K0001AAA0001",
            "recebido_em": "15/05/2024", "classe": "Cumprimento de sentença"}])
        self.assertEqual(d["apensos"], [])
        self.assertEqual(d["audiencias"][0]["data"], "20/04/2024")
        self.assertEqual(d["historico_classes"][0]["texto"],
                         "Evolução - Procedimento Comum Cível - Cível")
        self.assertEqual(d["peticoes_diversas"][0]["texto"], "Contestação")
        self.assertEqual(d["processo_principal"], "0700001-11.2024.8.02.0001")
        self.assertEqual(d["codigo_processo"], "1K0001AAA0000")
        self.assertEqual(d["paginacao"]["ultima"], 8)
        self.assertEqual(d["paginacao"]["folhas_ausentes"], "6")
        json.dumps(d)                               # tudo serializável
        # sigiloso: segredo vale mesmo sem a etiqueta
        d2 = esaj.dados_da_capa(INFO, N, "TJAL", sigiloso=True)
        self.assertTrue(d2["segredo"])
        self.assertIn("Segredo de justiça", d2["marcas"])
        self.assertNotIn("paginacao", d2, "sem o manifesto, nada de folhas inventadas")
        self.assertEqual(d2["incidentes"], [])

    def test_marcas(self):
        marcas, sinais = esaj.marcas_da_capa({"marcas": ["Tramitação prioritária"],
                                              "cabecalho": "Assistência Judiciária"})
        self.assertEqual(marcas, ["Tramitação prioritária", "Justiça gratuita"])
        self.assertEqual(sinais, {"prioridade": True, "justica_gratuita": True, "segredo": False,
                                  "idoso": False})
        # sem etiqueta e com o cabeçalho limpo (o JS tira os valores da capa)
        self.assertEqual(esaj.marcas_da_capa({}), ([], dict.fromkeys(
            ("prioridade", "justica_gratuita", "segredo", "idoso"), False)))


class TestCapaNoDownload(apoio.PastaTemporaria):
    def test_capa_txt_e_json_com_as_folhas_do_pdf(self):
        p = PortalDeDownload(info=TestCapa.INFO_V2)
        destino = self.tmp / "Lote" / f"{N.nome_arquivo}.pdf"
        r = p.baixar(N, destino)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        controle = self.tmp / "Lote" / "_controle"
        texto = (controle / f"{N.nome_arquivo}_capa.txt").read_text(encoding="utf-8")
        self.assertIn("Folhas 1 a 8 (última oferecida pela Pasta Digital)", texto)
        self.assertIn("folhas com página de aviso: 6-7", texto)
        d = json.loads((controle / f"{N.nome_arquivo}_capa.json").read_text(encoding="utf-8"))
        self.assertEqual(d["paginacao"]["ultima"], 8)
        self.assertEqual(d["paginacao"]["ausentes"], {"N": "6-7"})
        self.assertEqual(len(d["movimentacoes"]), 77)
        self.assertTrue(d["idoso"])

    def test_capa_de_sigiloso_avisa_no_topo(self):
        p = PortalDeDownload(senha_pedida=[True], info=TestCapa.INFO_V2)
        r = p.baixar(N, self.tmp / "Lote" / f"{N.nome_arquivo}.pdf", senha="abc123")
        self.assertTrue(r.sigiloso)
        texto = (self.tmp / "Lote" / "_controle" / f"{N.nome_arquivo}_capa.txt").read_text(
            encoding="utf-8")
        self.assertIn("SEGREDO DE JUSTIÇA", texto[:2000], "o motor só olha o começo")
        d = json.loads((self.tmp / "Lote" / "_controle" / f"{N.nome_arquivo}_capa.json")
                       .read_text(encoding="utf-8"))
        self.assertTrue(d["sigiloso"] and d["segredo"])


class TestPermissaoNaGravacao(apoio.PastaTemporaria):
    """Achado 9c: PermissionError só deixa de montar peça a peça quando é do
    arquivo que se estava gravando (o PDF de destino, aberto no leitor, ou o
    provisório dele, preso pelo antivírus - o motor repete); sem arquivo
    nenhum (o Windows negando um soquete), é falha da rota do servidor."""

    def baixar_com(self, erro):
        p = PortalDeDownload()
        destino = self.tmp / "Lote" / f"{N.nome_arquivo}.pdf"

        def gravar(*a, **k):
            raise erro(destino) if callable(erro) else erro

        with mock.patch.object(esaj.pdf, "gravar_alinhado", side_effect=gravar):
            r = p.baixar(N, destino)
        return p, r, destino

    def test_destino_preso_sobe_sem_peca_a_peca(self):
        for nome in ("{d}", "{d}.parcial", "{d}.parcial2"):
            with self.subTest(arquivo=nome):
                def erro(destino, nome=nome):
                    return PermissionError(13, "Acesso negado", nome.format(d=destino))
                with self.assertRaises(PermissionError):
                    self.baixar_com(erro)

    def test_permissao_negada_sem_arquivo_monta_peca_a_peca(self):
        erro = PermissionError(10013, "uma tentativa de acesso a um soquete foi negada")
        with self.assertLogs("download.esaj", "WARNING"):
            p, r, destino = self.baixar_com(erro)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertIn("peça a peça", r.detalhe)
        self.assertTrue(p.pecas_pedidas)
        with pymupdf.open(destino) as doc:
            self.assertEqual(len(doc), 8)

    def test_arquivo_de_outra_pasta_nao_e_da_gravacao(self):
        destino = self.tmp / "Lote" / "x.pdf"
        fora = PermissionError(13, "negado", str(self.tmp / "Outra" / "x.pdf"))
        self.assertFalse(PortalESAJ._na_gravacao(fora, destino))
        self.assertTrue(PortalESAJ._na_gravacao(
            PermissionError(13, "negado", str(destino) + ".parcial"), destino))
        self.assertTrue(PortalESAJ._na_gravacao(
            PermissionError(13, "negado", str(self.tmp / "Outra" / "y"), None, str(destino)),
            destino), "os.replace(origem, destino): o destino é o filename2")
        self.assertFalse(PortalESAJ._na_gravacao(PermissionError(13, "negado"), destino))


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

    def test_sem_terminal_espera_o_codigo_na_janela_visivel(self):
        """A skill do Claude roda a linha de comando sem terminal: ninguém
        digita o código ali. Com a janela do navegador à vista, o usuário o
        digita no próprio portal, dentro do prazo do login."""
        ctx = ContextoComEventos(codigos=[])
        p = PortalDoCodigo(ctx)
        p.nav.visivel = True
        respostas = [False, False, True]
        p.sessao_ativa = lambda: respostas.pop(0) if respostas else False
        with mock.patch.object(esaj, "time", RelogioFalso()):
            self.assertTrue(p._resolver_codigo())
        self.assertTrue(any("Digite o código na janela" in t for t, _ in ctx.avisos))
        self.assertEqual([t for t, _ in ctx.eventos], ["login_aguardando", "login_concluido"])
        self.assertEqual(ctx.eventos[0][1]["motivo"], "codigo")
        self.assertEqual(ctx.eventos[0][1]["modo"], "senha")
        self.assertEqual(ctx.eventos[0][1]["prazo_min"], 1)

    def test_codigo_na_janela_com_prazo_esgotado(self):
        p = PortalDoCodigo(apoio.ContextoGravador(codigos=[]))
        p.nav.visivel = True
        p.sessao_ativa = lambda: False
        with mock.patch.object(esaj, "time", RelogioFalso()):
            with self.assertRaises(modelos.LoginFalhou) as caso:
                p._resolver_codigo()
        self.assertIn("sem o login na janela", str(caso.exception))
        self.assertIn("esaj-codigo-prazo", p.nav.diagnosticos)

    def test_sem_terminal_e_sem_janela_explica_o_caminho(self):
        p = PortalDoCodigo(apoio.ContextoGravador(codigos=[]))
        with self.assertRaises(modelos.LoginFalhou) as caso:
            p._resolver_codigo()
        self.assertIn("--visivel", str(caso.exception))
        self.assertEqual(p.ctx.avisos, [], "sem janela, não manda digitar nela")

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

    def test_eventos_do_login_na_janela_para_a_skill(self):
        ctx = ContextoComEventos()
        p = PortalESAJ(NavegadorDeMentira(), TRIBUNAL,
                       opcoes(login={"esaj": "manual"}, espera_login_min=3), ctx, None)
        respostas = [False, False, True]
        p.sessao_ativa = lambda: respostas.pop(0) if respostas else False
        p._esta_logado = lambda pagina=None: False
        p._sessao_no_contexto = lambda: False
        with mock.patch.object(esaj, "time", RelogioFalso()):
            p.entrar()
        self.assertEqual([t for t, _ in ctx.eventos], ["login_aguardando", "login_concluido"])
        dados = ctx.eventos[0][1]
        self.assertEqual({k: dados[k] for k in ("sistema", "tribunal", "modo", "prazo_min",
                                                 "motivo")},
                         {"sistema": "esaj", "tribunal": "TJAL", "modo": "manual",
                          "prazo_min": 3, "motivo": "manual"})
        ate = datetime.fromisoformat(dados["ate"])
        self.assertLess(abs((ate - datetime.now()).total_seconds() - 180), 60)
        self.assertEqual(ctx.eventos[1][1]["sistema"], "esaj")
        # o evento vem ANTES de esperar (e do aviso)
        self.assertTrue(ctx.avisos)

    def test_sem_evento_no_contexto_nada_quebra(self):
        """Contexto de versão anterior, sem ``evento``: o login segue igual."""
        p, ctx = self.portal("manual", [False, True])
        p.ctx = types.SimpleNamespace(avisar=ctx.avisar, status=ctx.status,
                                      cancelado=ctx.cancelado)
        with mock.patch.object(esaj, "time", RelogioFalso()):
            p.entrar()
        self.assertTrue(ctx.avisos)

    def test_evento_que_falha_nao_derruba_o_login(self):
        ctx = ContextoComEventos(falhar=True)
        p = PortalESAJ(NavegadorDeMentira(), TRIBUNAL, opcoes(login={"esaj": "certificado"}),
                       ctx, None)
        respostas = [False, False, True]
        p.sessao_ativa = lambda: respostas.pop(0) if respostas else False
        p._esta_logado = lambda pagina=None: False
        p._sessao_no_contexto = lambda: False
        with mock.patch.object(esaj, "time", RelogioFalso()):
            p.entrar()
        self.assertEqual(ctx.eventos[0][1]["motivo"], "certificado")


class ContextoComEventos(apoio.ContextoGravador):
    """O Contexto com ``evento`` (frente da linha de comando), gravando tudo."""

    def __init__(self, *a, falhar=False, **k):
        super().__init__(*a, **k)
        self.eventos = []
        self.falhar = falhar

    def evento(self, tipo, **dados):
        self.eventos.append((tipo, dados))
        if self.falhar:
            raise RuntimeError("quem acompanha caiu")


class TestCertificadoNaRedeDoForum(unittest.TestCase):
    """--login certificado na rede com proxy: o canal direto não alcança o
    portal, e a aba ainda em about:blank também não. A sessão válida não
    pode virar um pedido de login falso a cada chamada da skill."""

    def portal(self, logado=True):
        nav = NavegadorDeMentira()
        nav.pagina.url = "about:blank"

        class Canal:
            def get(self, url, timeout=0, headers=None):
                raise RuntimeError("getaddrinfo ENOTFOUND portal.teste")
        nav.contexto = types.SimpleNamespace(request=Canal())
        ctx = ContextoComEventos()
        p = PortalESAJ(nav, TRIBUNAL, opcoes(login={"esaj": "certificado"}), ctx, None)
        p._esta_logado = lambda pagina=None: False
        resposta = '{"usuarioLogado": true}' if logado else '{"usuarioLogado": false}'
        p._buscar_texto = lambda url, metodo="GET", corpo=None, cabecalhos=None: (200, resposta)
        p._sessao_no_contexto = lambda: logado
        return p, ctx

    def test_sessao_valida_pela_aba_dispensa_o_login(self):
        p, ctx = self.portal(logado=True)
        p.entrar()
        self.assertEqual(p.nav.visitas, ["https://portal.teste/cpopg/open.do?servico=190101"
                                         "&gateway=true"])
        self.assertEqual(ctx.avisos, [])
        self.assertEqual(ctx.eventos, [])

    def test_sem_sessao_vai_ao_cas_e_espera(self):
        p, ctx = self.portal(logado=False)
        with mock.patch.object(esaj, "time", RelogioFalso()):
            with self.assertRaises(modelos.LoginFalhou):
                p.entrar()
        self.assertEqual(p.nav.visitas[-1], "https://portal.teste/sajcas/login")
        self.assertTrue(any("certificado" in t.lower() for t, _ in ctx.avisos))
        self.assertEqual(ctx.eventos[0][0], "login_aguardando")


class PortalDeDownload(PortalESAJ):
    """Tudo o que toca a página é trocado por respostas prontas."""

    def __init__(self, ctx=None, senha_pedida=(False,), libera=True, info=INFO, arvore=ARVORE,
                 servidor="ok", pecas_ok=("101", "102", "104"), sessao=True, achar=None,
                 paginas_servidor=6, paginas_pecas=None, pecas_ruins=(), **op):
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
        self.paginas_servidor = paginas_servidor     # int, ou bytes prontos do PDF único
        self.paginas_pecas = dict(paginas_pecas or {})   # cd -> páginas do arquivo da peça
        self.pecas_ruins = set(pecas_ruins)          # cd -> arquivo que não abre
        self.pedidos_ao_servidor = []                # as peças de cada gerar_pdf
        self.pecas_pedidas = []                      # cd de cada getPDF.do
        self.entregue = b""                          # o PDF único entregue

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
        self.pedidos_ao_servidor.append(list(pecas))
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
        if isinstance(self.paginas_servidor, bytes):
            self.entregue = self.paginas_servidor
        else:
            self.entregue = apoio.pdf_bytes(self.paginas_servidor, "servidor")
        return self.entregue

    def baixar_peca(self, parametros):
        """O arquivo de cada bloco tem uma página por folha (numInicial a
        numFinal), como o getPDF.do do portal - salvo o que o teste mandar."""
        q = urllib.parse.parse_qs(parametros)
        cd = q["cdDocumento"][0]
        self.pecas_pedidas.append(cd)
        if cd not in self.pecas_ok:
            return None
        if cd in self.pecas_ruins:
            return b"%PDF-1.4\n" + b"\x00quebrado" * 40
        n = (int(q["numFinal"][0]) - int(q["numInicial"][0]) + 1) if "numFinal" in q else 1
        return apoio.pdf_bytes(self.paginas_pecas.get(cd, n), f"peça {cd}")

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
        self.assertEqual(r.paginas, 8, "página N = folha N: fls. 1 a 8")
        self.assertEqual(r.documentos, 3)
        self.assertEqual(r.incompleto, "6-7", "as folhas que a Pasta Digital não ofereceu")
        self.assertIn("fls. 6-7 não oferecidas pela Pasta Digital", r.detalhe)
        self.assertNotIn("peça a peça", r.detalhe)
        self.assertFalse(r.sigiloso)
        self.assertEqual(r.arquivo, str(self.destino()))
        self.assertTrue(self.destino().read_bytes().startswith(p.entregue),
                        "os bytes do servidor ficam como vieram (salvamento incremental)")
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual(len(doc), 8)
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 3, 6, 8])
            self.assertEqual(doc.get_toc()[2][1], "Fls. 6-7 — não disponibilizadas pelo e-SAJ")
            for i, folha in ((5, 6), (6, 7)):
                self.assertEqual(doc[i].get_text().splitlines()[0],
                                 f"Folha {folha} — não disponibilizada pelo e-SAJ")
                self.assertIn(paginacao.MOTIVOS["N"][:40], " ".join(doc[i].get_text().split()))
            self.assertIn("servidor 5", doc[4].get_text())
            self.assertIn("servidor 6", doc[7].get_text(), "a fl. 8 é a página 8")
            m = paginacao.ler_do_doc(doc)
        self.assertEqual((m["sistema"], m["paginacao"], m["ultima"], m["origem"]),
                         ("esaj", "folhas", 8, "servidor"))
        self.assertEqual(m["ausentes"], {"N": "6-7"})
        self.assertEqual(m["processo"], N.formatado)
        self.assertEqual(m["tribunal"], "TJAL")
        self.assertEqual([[x["parametros"] for x in pedido] for pedido in p.pedidos_ao_servidor],
                         [[x["parametros"] for x in esaj.extrair_pecas(ARVORE)]])
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
        self.assertIn("fl. 8: 1 peça não veio e tem página de aviso no lugar", r.detalhe)
        self.assertIn("montado peça a peça (o PDF único do servidor falhou)", r.detalhe)
        self.assertNotIn("(s)", r.detalhe)
        self.assertEqual(r.incompleto, "6-8", "não oferecidas e não baixadas, numa faixa só")
        self.assertEqual(r.paginas, 8)
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual(len(doc), 8)
            texto = doc[7].get_text()
            self.assertTrue(texto.startswith("Folha 8 — não disponibilizada pelo e-SAJ"), texto)
            self.assertIn("não pôde ser baixada", texto)
            self.assertIn("Termo de Audiência", texto)
            self.assertIn("peça 102 2", doc[3].get_text(), "fl. 4 = 2ª página do bloco 3-4")
            self.assertIn("peça 102 1", doc[4].get_text(), "fl. 5 = o bloco dela, à parte")
            self.assertEqual([t[2] for t in doc.get_toc()], [1, 3, 6, 8])
            m = paginacao.ler_do_doc(doc)
        self.assertEqual(m["origem"], "peca_a_peca")
        self.assertEqual(m["ausentes"], {"N": "6-7", "B": "8"})

    def test_servidor_entrega_html_e_monta_peca_a_peca(self):
        r = PortalDeDownload(servidor="html").baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("peça a peça", r.detalhe)

    def test_pdf_do_servidor_corrompido_vira_peca_a_peca(self):
        r = PortalDeDownload(servidor="corrompido").baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("peça a peça", r.detalhe)
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual(doc.page_count, 8, "uma página por folha, de 1 a 8")
        self.assertEqual(sorted(p.name for p in self.destino().parent.iterdir() if p.is_file()),
                         [self.destino().name], "nenhum .parcial sobra")

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
        self.assertEqual(r.incompleto, "2-10")

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


def pdf_carimbado(folhas, texto="servidor"):
    """PDF com o carimbo do e-SAJ ("fls. N", numa linha só) em cada página."""
    doc = pymupdf.open()
    for i, f in enumerate(folhas, 1):
        pagina = doc.new_page()
        pagina.insert_text((500, 30), f"fls. {f}")
        pagina.insert_text((72, 120), f"{texto} {i}")
    dados = doc.tobytes()
    doc.close()
    return dados


def pdf_carimbado_com_copias(folhas, copias, texto="servidor"):
    """Como ``pdf_carimbado``, mas a folha que está em ``copias`` (folha ->
    carimbo antigo) reproduz uma folha de outro processo do e-SAJ: o
    carimbo antigo vem dentro da página copiada, e o deste processo, por
    cima, no fim do conteúdo."""
    doc = pymupdf.open()
    for i, f in enumerate(folhas, 1):
        pagina = doc.new_page()
        if f in copias:
            outro = pymupdf.open()
            antiga = outro.new_page()
            antiga.insert_text((500, 30), f"fls. {copias[f]}")
            antiga.insert_text((72, 120), f"{texto} {i}")
            with pymupdf.open(stream=outro.tobytes()) as copia:
                pagina.show_pdf_page(pagina.rect, copia, 0)
            outro.close()
        else:
            pagina.insert_text((72, 120), f"{texto} {i}")
        pagina.insert_text((500, 45), f"fls. {f}")
    dados = doc.tobytes()
    doc.close()
    return dados


def primeiras_linhas(caminho):
    with pymupdf.open(caminho) as doc:
        return [(doc[i].get_text().splitlines() or [""])[0] for i in range(len(doc))]


def textos_das_paginas(caminho):
    with pymupdf.open(caminho) as doc:
        return [" ".join(doc[i].get_text().split()) for i in range(len(doc))]


class TestPaginaIgualAFolha(apoio.PastaTemporaria):
    """O PDF gravado como OK tem a página N = folha N, sempre."""

    def destino(self):
        return self.tmp / "Lote" / f"{N.nome_arquivo}.pdf"

    def test_folha_copiada_de_outro_processo_fica_com_o_servidor(self):
        """Cumprimento de sentença com a sentença do principal anexada: as
        fls. 3-4 trazem o carimbo antigo antes do deste processo. O PDF do
        servidor está certo e fica: nada é refeito peça a peça, e nenhuma
        folha que o servidor entregou vira página de aviso."""
        servidor = pdf_carimbado_com_copias([1, 2, 3, 4, 5, 8], {3: 45, 4: 46})
        p = PortalDeDownload(paginas_servidor=servidor, pecas_ok=("101", "104"))
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertNotIn("peça a peça", r.detalhe)
        self.assertNotIn("carimbada não confere", r.detalhe)
        self.assertEqual(p.pecas_pedidas, [])
        self.assertEqual(r.incompleto, "6-7")
        textos = textos_das_paginas(self.destino())
        self.assertIn("servidor 3", textos[2])
        self.assertIn("servidor 4", textos[3])

    def test_peca_com_paginas_a_menos_segue_o_carimbo(self):
        """Peça a peça, o laudo (fls. 3-5) vem sem a página da fl. 3: as que
        vieram ficam nas fls. 4 e 5, e o aviso fica na fl. 3."""
        class PortalDoLaudo(PortalDeDownload):
            def baixar_peca(self, parametros):
                if urllib.parse.parse_qs(parametros)["cdDocumento"][0] == "102":
                    self.pecas_pedidas.append("102")
                    return pdf_carimbado([4, 5], "laudo")
                return super().baixar_peca(parametros)

        arvore = [documento("Inicial", 101, [(1, 2)]), documento("Laudo", 102, [(3, 5)]),
                  documento("Sentença", 103, [(6, 6)])]
        p = PortalDoLaudo(arvore=arvore, servidor="falha", pecas_ok=("101", "102", "103"))
        r = p.baixar(N, self.destino())
        self.assertEqual(r.paginas, 6)
        self.assertEqual(r.incompleto, "3")
        self.assertIn("a página de cada folha é a que traz o carimbo dela (fls. 4-5)", r.detalhe)
        linhas = primeiras_linhas(self.destino())
        self.assertEqual(linhas[2:], ["Folha 3 — não disponibilizada pelo e-SAJ", "fls. 4",
                                      "fls. 5", "peça 103 1"])

    def test_pdf_do_servidor_com_paginas_a_menos_vira_peca_a_peca(self):
        r = PortalDeDownload(paginas_servidor=5).baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("montado peça a peça (o PDF do servidor tem 5 páginas para 6 folhas)",
                      r.detalhe)
        self.assertEqual(r.paginas, 8)
        self.assertEqual(r.incompleto, "6-7")
        linhas = primeiras_linhas(self.destino())
        self.assertEqual(linhas[0], "peça 101 1")
        self.assertEqual(linhas[3], "peça 102 2")
        self.assertEqual(linhas[5], "Folha 6 — não disponibilizada pelo e-SAJ")
        self.assertEqual(linhas[7], "peça 104 1")

    def test_carimbo_que_nao_confere_vira_peca_a_peca(self):
        r = PortalDeDownload(paginas_servidor=pdf_carimbado([1, 2, 3, 5, 4, 8])).baixar(
            N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("folha carimbada não confere", r.detalhe)
        self.assertEqual(primeiras_linhas(self.destino())[3], "peça 102 2")

    def test_carimbo_que_confere_fica_com_o_servidor(self):
        p = PortalDeDownload(paginas_servidor=pdf_carimbado([1, 2, 3, 4, 5, 8]))
        r = p.baixar(N, self.destino())
        self.assertNotIn("peça a peça", r.detalhe)
        self.assertEqual(p.pecas_pedidas, [])
        with pymupdf.open(self.destino()) as doc:
            self.assertIn("fls. 8", doc[7].get_text())

    def test_arvore_fora_de_ordem(self):
        arvore = [documento("Sentença", 109, [(5, 5)], "09/09/2024"),
                  documento("Inicial", 101, [(1, 2)]),
                  documento("Contestação", 103, [(3, 4)])]
        p = PortalDeDownload(arvore=arvore, servidor="falha", pecas_ok=("101", "103", "109"))
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertEqual(r.incompleto, "")
        self.assertEqual([[x["cdDocumento"] for x in pedido] for pedido in p.pedidos_ao_servidor],
                         [["101", "103", "109"]], "o servidor recebe as peças em ordem de folha")
        self.assertEqual(primeiras_linhas(self.destino()),
                         ["peça 101 1", "peça 101 2", "peça 103 1", "peça 103 2", "peça 109 1"])
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual([(t[1][:9], t[2]) for t in doc.get_toc()],
                             [("Inicial (", 1), ("Contestaç", 3), ("Sentença ", 5)])

    def test_peca_com_paginas_a_menos(self):
        arvore = [documento("Inicial", 101, [(1, 2)]), documento("Laudo", 102, [(3, 5)]),
                  documento("Sentença", 103, [(6, 6)])]
        p = PortalDeDownload(arvore=arvore, servidor="falha", pecas_ok=("101", "102", "103"),
                             paginas_pecas={"102": 1})
        r = p.baixar(N, self.destino())
        self.assertEqual(r.paginas, 6)
        self.assertEqual(r.incompleto, "4-5")
        self.assertIn("fls. 4-5: o arquivo de 1 peça veio com páginas a menos", r.detalhe)
        linhas = primeiras_linhas(self.destino())
        self.assertEqual(linhas[2:], ["peça 102 1", "Folha 4 — não disponibilizada pelo e-SAJ",
                                      "Folha 5 — não disponibilizada pelo e-SAJ", "peça 103 1"])

    def test_peca_com_paginas_a_mais(self):
        arvore = [documento("Inicial", 101, [(1, 2)]), documento("Laudo", 102, [(3, 4)]),
                  documento("Sentença", 103, [(5, 5)])]
        p = PortalDeDownload(arvore=arvore, servidor="falha", pecas_ok=("101", "102", "103"),
                             paginas_pecas={"102": 5})
        r = p.baixar(N, self.destino())
        self.assertEqual(r.paginas, 5)
        self.assertEqual(r.incompleto, "")
        self.assertIn("fls. 3-4: o arquivo da peça tinha 5 páginas; mantidas as 2 primeiras",
                      r.detalhe)
        self.assertEqual(primeiras_linhas(self.destino())[4], "peça 103 1",
                         "a sobra não desloca a folha seguinte")

    def test_documento_inteiro_no_lugar_do_bloco(self):
        """O getPDF.do pode devolver o documento todo (fls. 3-5) para cada
        bloco dele: cada bloco fica com a sua fatia, e o arquivo vem uma vez só."""
        p = PortalDeDownload(servidor="falha", paginas_pecas={"102": 3})
        r = p.baixar(N, self.destino())
        self.assertEqual(r.paginas, 8)
        self.assertEqual(r.incompleto, "6-7")
        self.assertEqual(p.pecas_pedidas.count("102"), 1)
        self.assertNotIn("tinha 3 páginas", r.detalhe, "nada se perdeu")
        self.assertEqual(primeiras_linhas(self.destino())[2:5],
                         ["peça 102 1", "peça 102 2", "peça 102 3"])

    def test_peca_que_veio_invalida_tem_aviso_por_folha(self):
        p = PortalDeDownload(servidor="falha", pecas_ruins={"102"})
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertEqual(r.incompleto, "3-7", "o arquivo inválido também é folha ausente")
        self.assertIn("fls. 3-5: o arquivo de 1 peça veio inválido", r.detalhe)
        linhas = primeiras_linhas(self.destino())
        self.assertEqual(len(linhas), 8)
        self.assertEqual(linhas[2], "Folha 3 — não disponibilizada pelo e-SAJ")
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual(paginacao.ausentes(paginacao.ler_do_doc(doc)),
                             {3: "I", 4: "I", 5: "I", 6: "N", 7: "N"})

    def test_pasta_reaberta_com_peca_nova(self):
        """A sessão da pasta expira e o índice reaberto tem uma peça a mais:
        o PDF do servidor é conferido com o índice NOVO."""
        nova = documento("Sentença", 105, [(9, 9)], "01/05/2024")

        class PortalQueReabre(PortalDeDownload):
            def gerar_pdf(self, pecas, cd, reabrir=None):
                self.pedidos_ao_servidor.append(list(pecas))
                self.arvore = [*ARVORE, nova]
                self.pedidos_ao_servidor.append(list(reabrir()))
                return "https://portal.teste/pastadigital/final.pdf"

        p = PortalQueReabre(paginas_servidor=7)
        r = p.baixar(N, self.destino())
        self.assertEqual(r.situacao, modelos.OK)
        self.assertNotIn("peça a peça", r.detalhe)
        self.assertEqual(r.paginas, 9)
        self.assertEqual(r.documentos, 4)
        self.assertEqual(len(p.pedidos_ao_servidor[1]), 5)
        with pymupdf.open(self.destino()) as doc:
            self.assertEqual(doc.get_toc()[-1][1:], ["Sentença (fl. 9) - 01/05/2024", 9])

    def test_indice_sem_numeracao_nao_grava(self):
        arvore = [{"data": {"title": "Inicial", "cdDocumento": 1},
                   "children": [{"data": {"parametros": "cdDocumento=1&idDocumento=X",
                                          "nuPaginas": 2}}]}]
        p = PortalDeDownload(arvore=arvore)
        with self.assertRaises(RuntimeError) as caso:
            p.baixar(N, self.destino())
        self.assertIn("não informou a numeração", str(caso.exception))
        self.assertFalse(self.destino().exists())


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
