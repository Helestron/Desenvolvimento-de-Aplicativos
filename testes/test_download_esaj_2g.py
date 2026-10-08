"""PortalESAJ no 2º grau (CPOSG): a lógica pura e os fluxos, com dublês de página.

O que se testa: a busca com os parâmetros do CPOSG (foro do próprio número,
sempre pelo principal), a escolha da opção pelo número EXATO entre as três
respostas da consulta (nunca "a primeira": apelação e embargos têm o mesmo
número-base), a conferência da página aberta, o grau que só vem do
Tribunal, a capa do 2º grau (e a do 1º grau byte a byte a de antes), o
manifesto com o grau, a Pasta Digital pelo verificarAcessoPastaDigital.do
(com o caminho tirado da URL e o "SSO por webapp"), a guarda da numeração em
duplicidade e as frases de "não encontrado" com a dica do grau.

O mesmo fluxo num navegador de verdade, contra o e-SAJ falso, está em
test_download_integracao.py (TestSegundoGrau).
"""

from __future__ import annotations

import json
import unittest
import urllib.parse
from datetime import datetime
from unittest import mock

import pymupdf

from helestron.download import esaj, modelos
from helestron.download.esaj import PortalESAJ
from helestron.nucleo import cnj, paginacao, tribunais
from helestron.nucleo.tribunais import Tribunal

from testes import apoio_download as apoio
from testes import test_download_esaj as tde

A = cnj.ler("0700001-93.2024.8.02.0058")         # apelação: o mesmo número nos dois graus
H = cnj.ler("0803061-28.2025.8.02.0000")         # HC originário
E = cnj.ler("0706265-50.2017.8.02.0001/50000")   # embargos de declaração do 2º grau
E2 = cnj.ler("0706265-50.2017.8.02.0001/50001")  # agravo interno
P = cnj.ler("0706265-50.2017.8.02.0001")         # o principal dos embargos
PL = cnj.ler("0800103-29.2025.8.02.9002")        # plantão do 2º grau
I = cnj.ler("0700001-93.2024.8.02.0058/01")      # incidente do 1º grau  # noqa: E741

TRIBUNAL_1G = Tribunal(chave="8.02", sigla="TJAL", nome="Tribunal de Justiça - Alagoas",
                       sistema="esaj",
                       urls={"base": "https://portal.teste", "2g": "https://portal.teste/cposg5"})
TRIBUNAL_2G = TRIBUNAL_1G.no_grau("2g")
APP = "https://portal.teste/cposg5"


def opcoes(**k):
    return tde.opcoes(**k)


def portal(tribunal=TRIBUNAL_2G, ctx=None, **op):
    return PortalESAJ(tde.NavegadorDeMentira(), tribunal, opcoes(**op),
                      ctx or apoio.ContextoGravador(), ("u", "s"))


def query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)


# ============================================================ funções puras
class TestEnderecos2g(unittest.TestCase):
    def test_busca_com_os_parametros_do_cposg(self):
        url = esaj.url_busca_2g(APP, A)
        self.assertTrue(url.startswith(f"{APP}/search.do?"))
        self.assertEqual(query(url), {
            "conversationId": [""], "paginaConsulta": ["1"], "cbPesquisa": ["NUMPROC"],
            "tipoNuProcesso": ["UNIFICADO"], "numeroDigitoAnoUnificado": ["0700001-93.2024"],
            "foroNumeroUnificado": ["0058"],
            "dePesquisaNuUnificado": ["0700001-93.2024.8.02.0058"],
            "dePesquisa": [""], "uuidCaptcha": [""]})
        self.assertNotIn("dadosConsulta", url, "os nomes do cpopg não servem no cposg")

    def test_foro_do_proprio_numero_e_sempre_o_principal(self):
        self.assertEqual(query(esaj.url_busca_2g(APP, H))["foroNumeroUnificado"], ["0000"])
        self.assertEqual(query(esaj.url_busca_2g(APP, PL))["foroNumeroUnificado"], ["9002"])
        q = query(esaj.url_busca_2g(APP, E))
        self.assertEqual(q["dePesquisaNuUnificado"], [P.principal],
                         "o /50000 é escolhido depois, entre as opções da consulta")
        self.assertEqual(q["foroNumeroUnificado"], ["0001"])
        self.assertEqual(esaj.url_busca_2g(APP + "/", A), esaj.url_busca_2g(APP, A))

    def test_pagina_do_processo_so_com_o_codigo(self):
        self.assertEqual(esaj.url_processo_2g(APP, "P00006BXP12KW"),
                         f"{APP}/show.do?processo.codigo=P00006BXP12KW")

    def test_tabela_de_rotas(self):
        r1 = esaj.RotasESAJ("1g", "https://b", "https://b/cpopg")
        self.assertEqual(r1.busca(A), esaj.url_busca("https://b", A), "o 1º grau como sempre")
        self.assertEqual(r1.processo("1K0001AAA0000", A),
                         esaj.url_processo("https://b", "1K0001AAA0000", A))
        self.assertEqual(r1.abertura, "https://b/cpopg/open.do")
        self.assertEqual(r1.gateway, "https://b/cpopg/open.do?servico=190101&gateway=true")
        self.assertEqual(r1.pasta("CD", 7), "/cpopg/abrirPastaDigital.do?processo.codigo=CD&_=7")
        self.assertEqual(r1.diagnostico, "esaj")
        r2 = esaj.RotasESAJ("2g", "https://b", "https://b/cposg5")
        self.assertEqual(r2.busca(A), esaj.url_busca_2g("https://b/cposg5", A))
        self.assertEqual(r2.processo("P1", A), "https://b/cposg5/show.do?processo.codigo=P1")
        self.assertEqual(r2.gateway, "https://b/cposg5/open.do?gateway=true")
        self.assertEqual(r2.pasta("CD", 7), "/cposg5/verificarAcessoPastaDigital.do?cdProcesso=CD&_=7")
        self.assertEqual((r2.caminho, r2.diagnostico), ("/cposg5", "esaj2g"))

    def test_prefixo_da_pasta_vem_da_url(self):
        self.assertEqual(esaj.prefixo_da_pasta(
            "https://www2.tjal.jus.br/pastadigital/sg/abrirPastaProcessoDigital.do?x=1"),
            "/pastadigital/sg")
        self.assertEqual(esaj.prefixo_da_pasta(
            "https://www2.tjal.jus.br/pastadigital/abrirPastaProcessoDigital.do?x=1"),
            "/pastadigital")
        self.assertEqual(esaj.prefixo_da_pasta("https://h/abrir.do"), "/pastadigital")
        self.assertEqual(esaj.prefixo_da_pasta(""), "/pastadigital")


def modal(numero, codigo, *dependentes, classe="Apelação Criminal"):
    """As opções do modal "Selecione o processo", como _JS_RESPOSTA_2G as lê."""
    saida = [{"origem": "modal", "codigo": codigo, "numero": numero.principal,
              "titulo": classe, "dependente": ""}]
    for dep, cd in dependentes:
        saida.append({"origem": "modal", "codigo": cd, "numero": numero.principal,
                      "titulo": f"{dep} - Embargos de Declaração Criminal (Arquivado)",
                      "dependente": dep})
    return saida


class TestEscolherProcesso(unittest.TestCase):
    OPCOES = modal(A, "P0000AAAA0000", ("50000", "P0000AAAA12KW"))

    def test_principal_e_recurso_interno(self):
        self.assertEqual(esaj.escolher_processo_2g(self.OPCOES, A), "P0000AAAA0000")
        self.assertEqual(esaj.escolher_processo_2g(self.OPCOES, cnj.ler(A.principal + "/50000")),
                         "P0000AAAA12KW")

    def test_sem_a_opcao_exata_nada(self):
        self.assertIsNone(esaj.escolher_processo_2g(self.OPCOES, cnj.ler(A.principal + "/50001")))
        self.assertIsNone(esaj.escolher_processo_2g(self.OPCOES, I), "o /01 do 1º grau")
        self.assertIsNone(esaj.escolher_processo_2g(self.OPCOES, H), "outro número")
        self.assertIsNone(esaj.escolher_processo_2g([], A))
        self.assertIsNone(esaj.escolher_processo_2g(None, A))

    def test_dois_principais_do_mesmo_numero_recusa(self):
        dois = self.OPCOES + modal(A, "P0000BBBB0000")
        with self.assertRaises(RuntimeError) as caso:
            esaj.escolher_processo_2g(dois, A)
        self.assertIn("mais de um processo com este número (0700001-93.2024.8.02.0058)",
                      str(caso.exception))
        self.assertIn("autos trocados", str(caso.exception))
        # mas o /50000, que é um só, ainda se escolhe
        self.assertEqual(esaj.escolher_processo_2g(dois, cnj.ler(A.principal + "/50000")),
                         "P0000AAAA12KW")

    def test_o_mesmo_codigo_em_duas_formas_nao_e_ambiguo(self):
        pagina = {"origem": "pagina", "codigo": "P0000AAAA0000", "numero": A.formatado,
                  "titulo": "Apelação Criminal", "dependente": ""}
        self.assertEqual(esaj.escolher_processo_2g(self.OPCOES + [pagina], A), "P0000AAAA0000")

    def test_dependente_ilegivel_nunca_vira_o_principal(self):
        opcoes = [{"origem": "modal", "codigo": "P0000AAAA12KW", "numero": A.principal,
                   "titulo": "Embargos de Declaração (Arquivado)", "dependente": "?"}]
        self.assertIsNone(esaj.escolher_processo_2g(opcoes, A))

    def test_pagina_direta_e_tabela_de_incidentes(self):
        opcoes = [{"origem": "pagina", "codigo": "P00006BXP0000", "numero": P.formatado,
                   "titulo": "Apelação Cível", "dependente": ""},
                  {"origem": "incidente", "codigo": "P00006BXP12KW", "numero": P.formatado,
                   "titulo": "Embargos de Declaração Cível - 50000", "dependente": "50000"}]
        self.assertEqual(esaj.escolher_processo_2g(opcoes, P), "P00006BXP0000")
        self.assertEqual(esaj.escolher_processo_2g(opcoes, E), "P00006BXP12KW")
        self.assertIsNone(esaj.escolher_processo_2g(opcoes, E2))

    def test_lista(self):
        opcoes = [{"origem": "lista", "codigo": "X1", "numero": "0800104-14.2025.8.02.9002",
                   "titulo": "Habeas Corpus", "dependente": ""},
                  {"origem": "lista", "codigo": "X2", "numero": PL.formatado,
                   "titulo": f"{PL.formatado} Habeas Corpus Criminal", "dependente": ""},
                  {"origem": "lista", "codigo": "X3", "numero": PL.formatado,
                   "titulo": f"{PL.formatado} Agravo Interno - 50000", "dependente": ""}]
        self.assertEqual(esaj.escolher_processo_2g(opcoes, PL), "X2")
        self.assertEqual(esaj.escolher_processo_2g(opcoes, cnj.ler(PL.principal + "/50000")),
                         "X3", "o título da linha diz o recurso interno")


class TestConferirPagina(unittest.TestCase):
    def dados(self, numero, cabecalho="", cd="P00006BXP0000", texto=""):
        return {"numero": numero, "cabecalho": cabecalho or f"{numero} Julgado Classe Apelação",
                "cd": cd, "texto": texto}

    def test_principal(self):
        esaj.conferir_pagina_2g(self.dados(P.formatado), P, "P00006BXP0000")
        with self.assertRaises(RuntimeError) as caso:
            esaj.conferir_pagina_2g(self.dados(E.formatado, cd="P00006BXP0000"), P,
                                    "P00006BXP0000")
        self.assertIn("recurso interno do 2º grau (/50000)", str(caso.exception))

    def test_recurso_interno(self):
        esaj.conferir_pagina_2g(self.dados(E.formatado, cd="P00006BXP12KW"), E, "P00006BXP12KW")
        # pelo título do cabeçalho
        esaj.conferir_pagina_2g(self.dados(
            P.formatado, cabecalho=f"{P.formatado} Embargos de Declaração Cível - 50000",
            cd="P00006BXP12KW"), E, "P00006BXP12KW")
        # pelo código do 2º grau (12KW = 50000 em base 36), sem o sufixo na página
        esaj.conferir_pagina_2g(self.dados(P.formatado, cd="P00006BXP12KW"), E, "P00006BXP12KW")
        with self.assertRaises(RuntimeError) as caso:
            esaj.conferir_pagina_2g(self.dados(P.formatado, cd="P00006BXP0000"), E,
                                    "P00006BXP0000")
        self.assertIn("recurso /50000 não se declara", str(caso.exception))
        with self.assertRaises(RuntimeError):
            esaj.conferir_pagina_2g(self.dados(E.formatado, cd="P00006BXP12KX"), E2,
                                    "P00006BXP12KX")

    def test_outro_numero_ou_outro_codigo(self):
        with self.assertRaises(RuntimeError) as caso:
            esaj.conferir_pagina_2g(self.dados(H.formatado), P, "P00006BXP0000")
        self.assertIn("não traz este número", str(caso.exception))
        with self.assertRaises(RuntimeError) as caso:
            esaj.conferir_pagina_2g(self.dados(P.formatado, cd="P99999ZZZ0000"), P,
                                    "P00006BXP0000")
        self.assertIn("não é a do processo escolhido", str(caso.exception))

    def test_valor_ou_data_no_cabecalho_nao_e_dependente(self):
        for cabecalho in (f"{P.formatado} Valor da ação 50.000,00 - 50000,00",
                          f"{P.formatado} 22/02/2021 Baixado",
                          f"{P.formatado} (Principal)"):
            esaj.conferir_pagina_2g(self.dados(P.formatado, cabecalho=cabecalho), P,
                                    "P00006BXP0000")

    def test_dependentes_da_pagina(self):
        self.assertEqual(esaj.dependentes_da_pagina(E.formatado), {"50000"})
        self.assertEqual(esaj.dependentes_da_pagina("0706265-50.2017.8.02.0001 / 50001"),
                         {"50001"})
        self.assertEqual(esaj.dependentes_da_pagina(P.formatado), set())
        self.assertEqual(esaj.dependentes_da_pagina("", "50000 - Embargos de Declaração"),
                         {"50000"})
        self.assertEqual(esaj.dependentes_da_pagina("", f"{P.formatado}/50000 Embargos"),
                         {"50000"})


class TestFolhasEmDuplicidade(unittest.TestCase):
    def pecas(self, arvore):
        return esaj.extrair_pecas(arvore)

    def test_pecas_diferentes_nas_mesmas_folhas(self):
        arvore = [tde.documento("Apelação", 701, [(1, 3)]),
                  tde.documento("Remessa (numeração da origem)", 705, [(3, 4)]),
                  tde.documento("Contrarrazões", 702, [(4, 5)])]
        self.assertEqual(esaj.folhas_em_duplicidade(self.pecas(arvore)), [3, 4])

    def test_a_mesma_peca_duas_vezes_nao_conta(self):
        arvore = [tde.documento("Inicial", 3, [(3, 4)]), tde.documento("Inicial", 3, [(3, 4)]),
                  tde.documento("Laudo", 5, [(5, 7)])]
        self.assertEqual(esaj.folhas_em_duplicidade(self.pecas(arvore)), [])
        self.assertEqual(esaj.folhas_em_duplicidade(self.pecas(tde.ARVORE)), [])
        self.assertEqual(esaj.folhas_em_duplicidade([]), [])


# ========================================================== grau e nome
class TestGrauDoTribunal(unittest.TestCase):
    def test_nome_por_grau(self):
        self.assertEqual(portal(TRIBUNAL_1G).nome, "e-SAJ do TJAL")
        self.assertEqual(portal(TRIBUNAL_2G).nome, "e-SAJ do TJAL (2º grau)")
        self.assertEqual((portal(TRIBUNAL_1G).grau, portal(TRIBUNAL_2G).grau), ("1g", "2g"))

    def test_grau_so_do_tribunal(self):
        nav, ctx = tde.NavegadorDeMentira(), apoio.ContextoGravador()
        self.assertEqual(PortalESAJ(nav, TRIBUNAL_2G, opcoes(), ctx, None, grau="2").grau, "2g")
        self.assertEqual(PortalESAJ(nav, TRIBUNAL_1G, opcoes(), ctx, None, grau="1g").grau, "1g")
        with self.assertRaises(ValueError) as caso:
            PortalESAJ(nav, TRIBUNAL_1G, opcoes(), ctx, None, grau="2g")
        self.assertIn("passe tribunal.no_grau('2g')", str(caso.exception))
        with self.assertRaises(ValueError):
            PortalESAJ(nav, TRIBUNAL_2G, opcoes(), ctx, None, grau="1g")
        with self.assertRaises(ValueError):
            PortalESAJ(nav, TRIBUNAL_2G, opcoes(), ctx, None, grau="3")

    def test_sem_o_endereco_do_2o_grau(self):
        sem = Tribunal(chave="8.26", sigla="TJSP", nome="x", sistema="esaj",
                       urls={"base": "https://esaj.tjsp.jus.br"})
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            portal(sem.no_grau("2g"))
        self.assertIn("não traz o endereço do 2º grau do e-SAJ do TJSP", str(caso.exception))
        self.assertIsNotNone(portal(sem), "o 1º grau do mesmo tribunal continua")

    def test_o_endereco_do_catalogo(self):
        p = portal(tribunais.por_sigla("TJAL").no_grau("2g"))
        self.assertEqual(p.rotas.app, "https://www2.tjal.jus.br/cposg5")
        self.assertEqual(p.rotas.gateway, "https://www2.tjal.jus.br/cposg5/open.do?gateway=true")
        self.assertEqual(p.base, "https://www2.tjal.jus.br", "o login é o do portal")

    def test_diagnostico_com_o_grau(self):
        self.assertEqual(portal(TRIBUNAL_2G)._diag("falha-x"), "esaj2g-falha-x")
        self.assertEqual(portal(TRIBUNAL_1G)._diag("falha-x"), "esaj-falha-x")


class TestSegredo2g(unittest.TestCase):
    def test_seletores_da_senha_do_2o_grau(self):
        self.assertEqual(esaj.SELETORES_PADRAO["processo_senha_enviar"],
                         ["#btEnviarSenha", "#botaoEnviarSenha"], "o do 1º grau primeiro")
        self.assertIn("#senhaProcesso", esaj.SELETORES_PADRAO["processo_senha"])
        self.assertIn("#popupSenhaProcesso", esaj._JS_MODAL_SENHA)

    def test_o_texto_do_popup_do_2o_grau_nao_marca_segredo(self):
        """O popup do 2º grau diz "segredo de justiça" (e pede senha também para
        autos que não são sigilosos): sai do texto em que se procura o segredo.
        (O mesmo, rodando no navegador: TestSegundoGrau.test_capa_do_2o_grau_no_navegador.)"""
        exclusao = esaj._JS_PAGINA_PROCESSO.split("document.querySelectorAll(", 1)[1]
        exclusao = exclusao.split(").forEach", 1)[0]
        self.assertIn("#popupSenhaProcesso", exclusao)
        self.assertIn("#popupSenha,", exclusao, "o do 1º grau continua")


# ================================================================ capa
INFO_2G = {
    "capa": {"Classe": "Apelação Criminal", "Assunto": "Roubo Majorado",
             "Seção": "Tribunal de Justiça", "Órgão julgador": "Câmara Criminal",
             "Relator": "DES. JOÃO EXEMPLO", "Situação": "Julgado", "Área": "Criminal",
             "Origem": "Comarca de Arapiraca / Foro de Arapiraca / 1ª Vara Criminal"},
    "partes": ["Apelante: João da Silva", "Apelado: Ministério Público"],
    "movs": [{"data": "10/10/2024", "texto": "Acórdão publicado"}],
    "marcas": ["Julgado"], "cabecalho": "",
    "secoes": {
        "numeros_1a_instancia": [
            {"celulas": ["Nº de 1ª instância", "Foro", "Vara", "Juiz", "Obs."], "codigo": ""},
            {"celulas": ["", "", "", "", ""], "codigo": ""},
            {"celulas": ["0700001-93.2024.8.02.0058 (Principal)", "Foro de Arapiraca",
                         "1ª Vara Criminal", "Juiz Fulano", "-"], "codigo": "1K0700AAA0000"},
            {"celulas": ["número antigo ilegível", "Foro de Maceió", "", "", "apensado"]}],
        "incidentes": [{"celulas": ["21/10/2024", "Embargos de Declaração Criminal - 50000"],
                        "codigo": "P0000AAAA12KW"}],
        "composicao": [{"celulas": ["Participação", "Magistrado"]},
                       {"celulas": ["Relator", "Des. João Exemplo"]},
                       {"celulas": ["Revisor:", "Des. Pedro Revisor"]},
                       {"celulas": ["3º Julgador", "Desa. Maria Vogal"]}],
        "julgamentos": [{"celulas": ["Data", "Situação do julgamento", "Decisão"]},
                        {"celulas": ["09/10/2024", "Julgado", "à unanimidade, negou provimento"]}],
    },
    "codigo": "P0000AAAA0000",
    "url": "https://www2.tjal.jus.br/cposg5/show.do?processo.codigo=P0000AAAA0000",
    "texto": "x"}
QUANDO = datetime(2026, 10, 8, 14, 30, 0)


class TestCapa2g(unittest.TestCase):
    def manifesto(self):
        return paginacao.manifesto_esaj(A.formatado, 8, {6: "N"}, tribunal="TJAL", grau="2g")

    def test_capa_json_do_2o_grau(self):
        d = esaj.dados_da_capa(INFO_2G, A, "TJAL", manifesto=self.manifesto(), quando=QUANDO,
                               grau="2g")
        self.assertEqual(list(d)[:3], ["formato", "sistema", "grau"])
        self.assertEqual((d["formato"], d["grau"]), ("helestron.capa/2", "2g"))
        self.assertEqual({k: d["capa"][k] for k in ("classe", "secao", "orgao_julgador",
                                                     "relator", "origem", "situacao", "area")},
                         {"classe": "Apelação Criminal", "secao": "Tribunal de Justiça",
                          "orgao_julgador": "Câmara Criminal", "relator": "DES. JOÃO EXEMPLO",
                          "origem": "Comarca de Arapiraca / Foro de Arapiraca / 1ª Vara Criminal",
                          "situacao": "Julgado", "area": "Criminal"})
        self.assertEqual(d["numeros_1a_instancia"], [
            {"numero": "0700001-93.2024.8.02.0058", "foro": "Foro de Arapiraca",
             "vara": "1ª Vara Criminal", "juiz": "Juiz Fulano", "obs": "", "principal": True},
            {"numero": "", "foro": "Foro de Maceió", "vara": "", "juiz": "", "obs": "apensado",
             "principal": False}])
        self.assertEqual(d["capa"]["numeros_1a_instancia"], d["numeros_1a_instancia"],
                         "também em capa.numeros_1a_instancia (o motor lê a origem por ali)")
        self.assertEqual(d["composicao"], [{"papel": "Relator", "nome": "Des. João Exemplo"},
                                           {"papel": "Revisor", "nome": "Des. Pedro Revisor"},
                                           {"papel": "3º Julgador", "nome": "Desa. Maria Vogal"}])
        self.assertEqual(d["julgamentos"], [{"data": "09/10/2024", "situacao": "Julgado",
                                             "decisao": "à unanimidade, negou provimento"}])
        self.assertEqual(d["subprocessos"], d["incidentes"])
        self.assertEqual(d["subprocessos"][0]["codigo"], "P0000AAAA12KW")
        self.assertEqual(d["paginacao"]["ultima"], 8)
        json.dumps(d)

    def test_numero_de_1a_instancia_no_formato_cnj(self):
        linhas = [{"celulas": ["07000019320248020058", "Foro"]},
                  {"celulas": ["0700001-93.2024.8.02.0058/01 (Principal)", "Foro"]}]
        self.assertEqual([x["numero"] for x in esaj.numeros_de_1a_instancia(linhas)],
                         ["0700001-93.2024.8.02.0058", "0700001-93.2024.8.02.0058/01"])

    def test_capa_txt_do_2o_grau(self):
        texto = esaj.formatar_capa(INFO_2G, A, "TJAL", manifesto=self.manifesto(),
                                   quando=QUANDO, grau="2g")
        self.assertTrue(texto.startswith(
            "Processo 0700001-93.2024.8.02.0058 - TJAL (e-SAJ, 2º grau)\n"))
        self.assertIn("Seção: Tribunal de Justiça\nÓrgão julgador: Câmara Criminal\n"
                      "Relator: DES. JOÃO EXEMPLO\n", texto)
        self.assertIn("Origem: Comarca de Arapiraca / Foro de Arapiraca / 1ª Vara Criminal",
                      texto)
        self.assertIn("Folhas 1 a 8 (última oferecida pela Pasta Digital do 2º grau)", texto)
        self.assertIn("Como citar: \"fl. N\" - a página N do PDF é sempre a folha N da Pasta "
                      "Digital do 2º grau", texto)
        self.assertIn("\n== Números de 1ª Instância (2) ==\n0700001-93.2024.8.02.0058 "
                      "(principal) - Foro de Arapiraca - 1ª Vara Criminal - Juiz Fulano\n", texto)
        self.assertIn("\n== Composição do Julgamento (3) ==\nRelator: Des. João Exemplo\n", texto)
        self.assertIn("\n== Julgamentos (1) ==\n09/10/2024  Julgado - à unanimidade, negou "
                      "provimento\n", texto)
        self.assertIn("== Incidentes, ações incidentais, recursos e execuções de sentenças (1) =="
                      "\n21/10/2024  Embargos de Declaração Criminal - 50000", texto)
        self.assertNotIn("(s)", texto)
        sigiloso = esaj.formatar_capa(INFO_2G, A, "TJAL", sigiloso=True, grau="2g")
        self.assertIn("SEGREDO DE JUSTIÇA", sigiloso[:2000])

    # A capa do 1º grau, gerada pelo código de ANTES do 2º grau (1.0.2), com
    # este mesmo INFO_1G e QUANDO: tem de continuar byte a byte a mesma.
    INFO_1G = {
        "capa": {"Classe": "Procedimento Comum Cível", "Juiz": "Fulano de Tal",
                 "Foro": "Foro de Arapiraca"},
        "partes": ["Autor: Maria da Silva", "Réu: Banco Exemplo S.A."],
        "movs": [{"data": "20/04/2024", "texto": "Audiência realizada"},
                 {"data": "01/02/2024", "texto": "Distribuído por sorteio"}],
        "marcas": ["Tramitação prioritária"], "cabecalho": "Justiça Gratuita",
        "extras": {"outros_numeros": "0700003-40.2024.8.02.0001"},
        "secoes": {"incidentes": [{"celulas": ["15/05/2024", "0700001-93.2024.8.02.0058/01 "
                                                             "Cumprimento de sentença"],
                                   "codigo": "1K0001AAA0001"}],
                   "audiencias": [{"celulas": ["19/04/2024", "Conciliação", "Realizada", "2"]}]},
        "codigo": "1K0001AAA0000",
        "url": "https://portal.teste/cpopg/show.do?processo.codigo=1K0001AAA0000&processo.foro=58",
        "texto": "x"}
    MANIFESTO_1G = {"formato": 1, "programa": "Helestron 1.1.0", "sistema": "esaj",
                    "paginacao": "folhas", "processo": A.formatado, "tribunal": "TJAL",
                    "ultima": 8, "ausentes": {"N": "6-7"}, "origem": "servidor", "notas": [],
                    "gerado_em": "2026-10-08T14:30:00"}
    TXT_1G = (
        "Processo 0700001-93.2024.8.02.0058 - TJAL (e-SAJ, 1º grau)\n"
        "Capa extraída da consulta em 08/10/2026 14:30\n\n"
        "== Capa ==\nClasse: Procedimento Comum Cível\nJuiz: Fulano de Tal\n"
        "Foro: Foro de Arapiraca\nOutros números: 0700003-40.2024.8.02.0001\n\n"
        "== Marcas ==\nTramitação prioritária\nJustiça gratuita\n\n"
        "== Partes ==\nAutor: Maria da Silva\nRéu: Banco Exemplo S.A.\n\n"
        "== Arquivo ==\nFolhas 1 a 8 (última oferecida pela Pasta Digital)\n"
        "Paginação: página N = folha N (fls. 1 a 8); folhas com página de aviso: 6-7\n"
        "Como citar: \"fl. N\" - a página N do PDF é sempre a folha N da Pasta Digital; a "
        "folha com página de aviso não veio do e-SAJ (não a use como prova).\n\n"
        "== Movimentações (2) ==\n20/04/2024  Audiência realizada\n"
        "01/02/2024  Distribuído por sorteio\n\n"
        "== Incidentes, ações incidentais, recursos e execuções de sentenças (1) ==\n"
        "15/05/2024  0700001-93.2024.8.02.0058/01 Cumprimento de sentença\n\n"
        "== Audiências (1) ==\n19/04/2024  Conciliação - Realizada - 2\n")
    JSON_1G = (
        '{\n "formato": "helestron.capa/2",\n "sistema": "esaj",\n "tribunal": "TJAL",\n '
        '"processo": "0700001-93.2024.8.02.0058",\n "extraido_em": "2026-10-08T14:30:00",\n '
        '"sigiloso": true,\n "capa": {\n  "classe": "Procedimento Comum Cível",\n  '
        '"juiz": "Fulano de Tal",\n  "foro": "Foro de Arapiraca"\n },\n "partes": [\n  '
        '"Autor: Maria da Silva",\n  "Réu: Banco Exemplo S.A."\n ],\n "marcas": [\n  '
        '"Tramitação prioritária",\n  "Justiça gratuita",\n  "Segredo de justiça"\n ],\n '
        '"prioridade": true,\n "justica_gratuita": true,\n "segredo": true,\n '
        '"idoso": false,\n "outros_numeros": "0700003-40.2024.8.02.0001",\n '
        '"processo_principal": "",\n "local_fisico": "",\n "outros_assuntos": "",\n '
        '"movimentacoes": [\n  {\n   "data": "20/04/2024",\n   "texto": "Audiência realizada"'
        '\n  },\n  {\n   "data": "01/02/2024",\n   "texto": "Distribuído por sorteio"\n  }\n'
        ' ],\n "codigo_processo": "1K0001AAA0000",\n "url": "https://portal.teste/cpopg/'
        'show.do?processo.codigo=1K0001AAA0000&processo.foro=58",\n "incidentes": [\n  {\n'
        '   "data": "15/05/2024",\n   "texto": "0700001-93.2024.8.02.0058/01 Cumprimento de '
        'sentença",\n   "celulas": [\n    "15/05/2024",\n    "0700001-93.2024.8.02.0058/01 '
        'Cumprimento de sentença"\n   ],\n   "numero": "0700001-93.2024.8.02.0058/01",\n   '
        '"codigo": "1K0001AAA0001",\n   "recebido_em": "15/05/2024",\n   "classe": '
        '"Cumprimento de sentença"\n  }\n ],\n "apensos": [],\n "audiencias": [\n  {\n   '
        '"data": "19/04/2024",\n   "texto": "Conciliação - Realizada - 2",\n   "celulas": [\n'
        '    "19/04/2024",\n    "Conciliação",\n    "Realizada",\n    "2"\n   ]\n  }\n ],\n '
        '"historico_classes": [],\n "peticoes_diversas": [],\n "paginacao": {\n  "resumo": '
        '"página N = folha N (fls. 1 a 8); folhas com página de aviso: 6-7",\n  "ultima": 8,'
        '\n  "ausentes": {\n   "N": "6-7"\n  },\n  "folhas_ausentes": "6-7"\n }\n}')

    def test_capa_do_1o_grau_byte_a_byte_a_de_antes(self):
        self.assertEqual(esaj.formatar_capa(self.INFO_1G, A, "TJAL", False, self.MANIFESTO_1G,
                                            QUANDO), self.TXT_1G)
        dados = esaj.dados_da_capa(self.INFO_1G, A, "TJAL", True, self.MANIFESTO_1G, QUANDO)
        self.assertEqual(json.dumps(dados, ensure_ascii=False, indent=1), self.JSON_1G)
        # grau="1g" explícito dá o mesmo
        self.assertEqual(esaj.formatar_capa(self.INFO_1G, A, "TJAL", False, self.MANIFESTO_1G,
                                            QUANDO, grau="1g"), self.TXT_1G)
        for chave in ("grau", "numeros_1a_instancia", "composicao", "julgamentos",
                      "subprocessos"):
            self.assertNotIn(chave, dados)


# ======================================================= download (dublês)
class PortalDeDownload2G(tde.PortalDeDownload):
    """O PortalDeDownload do test_download_esaj no 2º grau: a consulta e a
    conferência da página trocadas por respostas prontas."""

    def __init__(self, **k):
        with mock.patch.object(tde, "TRIBUNAL", TRIBUNAL_2G):
            super().__init__(**k)

    def achar_codigo_2g(self, numero):
        self.registro.append(("achar2g", numero.formatado))
        if self.achar is not None:
            raise self.achar
        return "P0000AAAA0000"

    def _conferir_pagina_2g(self, numero, cd):
        self.registro.append(("conferir2g", numero.formatado, cd))


class TestBaixar2g(apoio.PastaTemporaria):
    def destino(self, numero=A):
        return self.tmp / "Lote" / f"{cnj.nome_dos_autos(numero, '2g')}.pdf"

    def test_download_do_2o_grau(self):
        p = PortalDeDownload2G(info=INFO_2G)
        r = p.baixar(A, self.destino())
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual((r.grau, r.sistema, r.paginas), ("2g", "esaj", 8))
        self.assertEqual(self.destino().name, "0700001-93.2024.8.02.0058 (2G).pdf")
        self.assertIn(("achar2g", A.formatado), p.registro)
        self.assertFalse([x for x in p.registro if x[0] in ("achar", "incidente")],
                         "nada da consulta nem da aritmética do 1º grau")
        with pymupdf.open(self.destino()) as doc:
            m = paginacao.ler_do_doc(doc)
            chaves = doc.metadata.get("keywords") or ""
        self.assertEqual((m["grau"], m["ultima"], m["processo"]), ("2g", 8, A.formatado))
        self.assertTrue(chaves.endswith(";grau=2g"), chaves)
        controle = self.tmp / "Lote" / "_controle"
        self.assertEqual(sorted(x.name for x in controle.iterdir() if x.is_file()),
                         ["0700001-93.2024.8.02.0058 (2G)_capa.json",
                          "0700001-93.2024.8.02.0058 (2G)_capa.txt"],
                         "capa pelo nome dos autos (destino.stem)")
        d = json.loads((controle / "0700001-93.2024.8.02.0058 (2G)_capa.json")
                       .read_text(encoding="utf-8"))
        self.assertEqual((d["grau"], d["paginacao"]["ultima"]), ("2g", 8))
        self.assertEqual(d["numeros_1a_instancia"][0]["numero"], A.formatado)

    def test_manifesto_do_1o_grau_sem_grau(self):
        destino = self.tmp / "Lote" / f"{A.nome_arquivo}.pdf"
        r = tde.PortalDeDownload().baixar(A, destino)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual(r.grau, "1g")
        with pymupdf.open(destino) as doc:
            m = paginacao.ler_do_doc(doc)
            self.assertNotIn("grau", doc.metadata.get("keywords") or "")
        self.assertNotIn("grau", m)
        d = json.loads((self.tmp / "Lote" / "_controle" / f"{A.nome_arquivo}_capa.json")
                       .read_text(encoding="utf-8"))
        self.assertNotIn("grau", d)

    def test_midias_pelo_nome_dos_autos(self):
        p = PortalDeDownload2G(baixar_midias=True)
        r = p.baixar(A, self.destino())
        alvo = (self.tmp / "Lote" / "_controle" / "midias" / "0700001-93.2024.8.02.0058 (2G)"
                / "audiencia 1.mp3")
        self.assertTrue(alvo.exists())
        self.assertEqual(r.midias, [str(alvo)])

    def test_folhas_em_duplicidade_nao_gravam_no_2o_grau(self):
        arvore = [tde.documento("Apelação", 701, [(1, 3)]),
                  tde.documento("Remessa (numeração da origem)", 705, [(3, 4)]),
                  tde.documento("Contrarrazões", 702, [(4, 5)])]
        p = PortalDeDownload2G(arvore=arvore, pecas_ok=("701", "702", "705"))
        r = p.baixar(A, self.destino())
        self.assertEqual(r.situacao, modelos.NAO_SUPORTADO)
        self.assertEqual(r.causa, "")
        self.assertFalse(r.refazer, "repetir daria o mesmo")
        self.assertEqual(r.detalhe, "a Pasta Digital do 2º grau numera folhas em duplicidade "
                                    "(fls. 3-4 em mais de uma peça); não gravei os autos, para "
                                    "não perder peças: baixe-os pelo portal do tribunal")
        self.assertEqual((p.pedidos_ao_servidor, p.pecas_pedidas), ([], []),
                         "decidido sobre o plano, antes de baixar qualquer peça")
        self.assertFalse(self.destino().exists())
        self.assertFalse((self.tmp / "Lote" / "_controle").exists())
        # no 1º grau, a mesma árvore continua só com a anomalia anotada
        r1 = tde.PortalDeDownload(arvore=arvore, pecas_ok=("701", "702", "705"),
                                  paginas_servidor=5).baixar(
            A, self.tmp / "Lote" / f"{A.nome_arquivo}.pdf")
        self.assertEqual(r1.situacao, modelos.OK, r1.detalhe)
        self.assertIn("fl. 3 também na faixa de outra peça (entrou a primeira)", r1.detalhe)

    def test_a_mesma_peca_listada_duas_vezes_continua_no_2o_grau(self):
        arvore = [tde.documento("Apelação", 701, [(1, 2)]),
                  tde.documento("Apelação", 701, [(1, 2)]),
                  tde.documento("Acórdão", 704, [(3, 3)])]
        r = PortalDeDownload2G(arvore=arvore, paginas_servidor=3).baixar(A, self.destino())
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertIn("listadas duas vezes na Pasta Digital (entrou uma)", r.detalhe)

    def test_pasta_reaberta_com_duplicidade_tambem_para(self):
        dupla = [tde.documento("Apelação", 701, [(1, 3)]),
                 tde.documento("Outra numeração", 705, [(2, 3)])]

        class QueReabre(PortalDeDownload2G):
            def gerar_pdf(self, pecas, cd, reabrir=None):
                self.arvore = dupla
                reabrir()
                return "https://portal.teste/pastadigital/sg/final.pdf"

        p = QueReabre(arvore=[tde.documento("Apelação", 701, [(1, 3)])])
        r = p.baixar(A, self.destino())
        self.assertEqual(r.situacao, modelos.NAO_SUPORTADO)
        self.assertFalse(self.destino().exists())
        self.assertEqual(p.pecas_pedidas, [], "não vira peça a peça")

    def test_senha_no_2o_grau_e_conferida_depois(self):
        p = PortalDeDownload2G(senha_pedida=[True])
        r = p.baixar(A, self.destino(), senha="s1")
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertTrue(r.sigiloso)
        self.assertIn(("conferir2g", A.formatado, "P0000AAAA0000"), p.registro)
        self.assertIn(A.nome_arquivo, p.sigilosos_apurados, "pela chave do processo")

    def test_nao_encontrado_no_2o_grau(self):
        erro = modelos.ProcessoNaoEncontrado("não encontrado no e-SAJ do TJAL (2º grau)")
        r = PortalDeDownload2G(achar=erro).baixar(A, self.destino())
        self.assertEqual((r.situacao, r.grau), (modelos.NAO_ENCONTRADO, "2g"))


# ============================================================== consulta
class PortalDeConsulta2G(PortalESAJ):
    """achar_codigo_2g com a resposta da consulta trocada por respostas prontas."""

    def __init__(self, *respostas, modal_senha=False, aberta=True):
        super().__init__(tde.NavegadorDeMentira(), TRIBUNAL_2G, opcoes(),
                         apoio.ContextoGravador(), None)
        self.respostas = list(respostas)
        self.modal_senha = modal_senha
        self.visitas = []
        self.conferidas = []
        self._dormir = lambda s: None
        self._consulta_2g_aberta = aberta

    def ir_para(self, url, timeout=60000, tentativas=3):
        self.visitas.append(url)
        self.nav.pagina.url = url

    def _esperar_carga(self, pagina=None, ms=10000):
        pass

    def _resposta_da_busca_2g(self):
        return self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]

    def _conferir_pagina_2g(self, numero, cd):
        self.conferidas.append((numero.formatado, cd))

    def modal_senha_visivel(self):
        return self.modal_senha

    def _abrir_consulta_2g(self):
        self.visitas.append("porta de entrada")
        self._consulta_2g_aberta = True

    def _texto_da_pagina(self, pagina=None):
        return ""


NADA = {"candidatos": [], "mensagem": "Não existem informações disponíveis para os parâmetros "
                                      "informados.",
        "texto": "Não existem informações disponíveis para os parâmetros informados."}


class TestConsulta2g(unittest.TestCase):
    def test_modal_pelo_numero_exato(self):
        opcoes_ = {"candidatos": modal(A, "P0000AAAA0000", ("50000", "P0000AAAA12KW"))}
        p = PortalDeConsulta2G(opcoes_)
        self.assertEqual(p.achar_codigo_2g(A), "P0000AAAA0000")
        self.assertEqual(p.visitas, [esaj.url_busca_2g(APP, A),
                                     f"{APP}/show.do?processo.codigo=P0000AAAA0000"])
        self.assertEqual(p.conferidas, [(A.formatado, "P0000AAAA0000")])
        p = PortalDeConsulta2G(opcoes_)
        embargos = cnj.ler(A.principal + "/50000")
        self.assertEqual(p.achar_codigo_2g(embargos), "P0000AAAA12KW")
        self.assertEqual(p.visitas[-1], f"{APP}/show.do?processo.codigo=P0000AAAA12KW")

    def test_porta_de_entrada_antes_da_primeira_busca(self):
        opcoes_ = {"candidatos": modal(A, "P0000AAAA0000")}
        p = PortalDeConsulta2G(opcoes_, aberta=False)
        p.achar_codigo_2g(A)
        self.assertEqual(p.visitas[0], "porta de entrada")
        p.achar_codigo_2g(A)
        self.assertEqual(p.visitas.count("porta de entrada"), 1, "uma vez por sessão")

    def test_nao_encontrado_com_a_dica_do_grau(self):
        for n in (A, H, PL, E):
            with self.subTest(numero=n.formatado):
                with self.assertRaises(modelos.ProcessoNaoEncontrado) as caso:
                    PortalDeConsulta2G(NADA).achar_codigo_2g(n)
                msg = str(caso.exception)
                self.assertTrue(msg.startswith("não encontrado no e-SAJ do TJAL (2º grau). "
                                               "Confira o número; "), msg)
                self.assertIn(modelos.dica_de_grau(n, "2g"), msg)
                self.assertTrue(msg.endswith("."))
                if n is A:
                    self.assertIn(modelos.DICA_GRAU_1G, msg)
                else:
                    self.assertNotIn(modelos.DICA_GRAU_1G, msg,
                                     "o número só existe no 2º grau: trocar o grau não muda")

    def test_o_numero_existe_mas_nao_o_dependente(self):
        opcoes_ = {"candidatos": modal(A, "P0000AAAA0000", ("50000", "P0000AAAA12KW")),
                   "texto": "Selecione o processo"}
        for n in (I, cnj.ler(A.principal + "/50001")):
            with self.assertRaises(modelos.ProcessoNaoEncontrado) as caso:
                PortalDeConsulta2G(opcoes_).achar_codigo_2g(n)
            self.assertIn(modelos.dica_de_grau(n, "2g"), str(caso.exception))
        self.assertIn("os autos estão no 1º grau", modelos.dica_de_grau(I, "2g"))

    def test_so_outros_numeros_nao_chuta(self):
        outro = {"candidatos": modal(H, "P0000HHHH0000")}
        with self.assertRaises(RuntimeError) as caso:
            PortalDeConsulta2G(outro).achar_codigo_2g(A)
        self.assertIn("nenhum traz exatamente este número", str(caso.exception))

    def test_dois_principais_nao_chuta(self):
        dois = {"candidatos": modal(A, "P0000AAAA0000") + modal(A, "P0000BBBB0000")}
        with self.assertRaises(RuntimeError) as caso:
            PortalDeConsulta2G(dois).achar_codigo_2g(A)
        self.assertIn("mais de um processo", str(caso.exception))

    def test_resposta_que_nao_se_entende(self):
        p = PortalDeConsulta2G({"candidatos": [], "texto": "Página inesperada"})
        with self.assertRaises(RuntimeError) as caso:
            p.achar_codigo_2g(A)
        self.assertIn("não consegui identificar o processo na consulta de 2º grau",
                      str(caso.exception))
        self.assertTrue(esaj.cheira_a_sessao(str(caso.exception)))
        self.assertTrue(any(d.startswith("esaj2g-consulta-") for d in p.nav.diagnosticos))

    def test_multiplas_consultas_insiste(self):
        p = PortalDeConsulta2G({"candidatos": [], "texto": "Não é permitido realizar múltiplas "
                                                          "consultas simultâneas"})
        with self.assertRaises(RuntimeError):
            p.achar_codigo_2g(A)
        self.assertEqual(len([v for v in p.visitas if "search.do" in v]), 3)

    def test_pagina_em_segredo_sem_o_numero(self):
        """O processo em segredo de justiça vem SEM os dados (nem o número), só
        com o código e o pedido de senha: é o da busca, conferido depois da senha."""
        so_codigo = {"candidatos": [{"origem": "pagina", "codigo": "P0000SSSS0000",
                                     "numero": "", "titulo": "", "dependente": ""}]}
        p = PortalDeConsulta2G(so_codigo, modal_senha=True)
        self.assertEqual(p.achar_codigo_2g(A), "P0000SSSS0000")
        self.assertEqual(p.visitas[-1], f"{APP}/show.do?processo.codigo=P0000SSSS0000")
        # sem o pedido de senha, ou pedindo um recurso interno: não se escolhe
        with self.assertRaises(RuntimeError):
            PortalDeConsulta2G(so_codigo).achar_codigo_2g(A)
        with self.assertRaises(RuntimeError):
            PortalDeConsulta2G(so_codigo, modal_senha=True).achar_codigo_2g(E)

    def test_nao_encontrado_do_1o_grau_com_a_dica(self):
        p = tde.PortalDeConsulta(html="<p>Não existem informações disponíveis para os "
                                      "parâmetros informados.</p>",
                                 texto="Não existem informações disponíveis para os parâmetros "
                                       "informados.")
        with self.assertRaises(modelos.ProcessoNaoEncontrado) as caso:
            p.achar_codigo(tde.N)
        msg = str(caso.exception)
        self.assertTrue(msg.startswith("não encontrado no 1º grau do e-SAJ do TJAL. Confira o "
                                       "número;"), msg)
        self.assertIn(modelos.dica_de_grau(tde.N, "1g"), msg)
        self.assertIn(modelos.DICA_GRAU_2G, msg)
        self.assertNotIn("baixe-o pelo portal", msg)


# =================================================== login e porta de entrada
class TestEntrar2g(unittest.TestCase):
    def test_o_login_termina_na_porta_de_entrada_do_2o_grau(self):
        for tribunal, esperado in ((TRIBUNAL_2G, ["login", "porta"]), (TRIBUNAL_1G, ["login"])):
            p = portal(tribunal)
            feito = []
            p._entrar_com_senha = lambda: feito.append("login")
            p._abrir_consulta_2g = lambda: feito.append("porta")
            p._consulta_2g_aberta = True
            p.entrar()
            self.assertEqual(feito, esperado)
            if tribunal is TRIBUNAL_2G:
                self.assertFalse(p._consulta_2g_aberta, "um login novo pede a porta de novo")

    def portal_na(self, url_final, sessao=True):
        p = portal(TRIBUNAL_2G)
        p.idas = []

        def ir_para(url, timeout=60000, tentativas=3):
            p.idas.append(url)
            p.nav.pagina.url = url_final
        p.ir_para = ir_para
        p.sessao_ativa = lambda: sessao
        return p

    def test_consulta_aberta(self):
        p = self.portal_na(f"{APP}/open.do?gateway=true")
        p._abrir_consulta_2g()
        self.assertTrue(p._consulta_2g_aberta)
        self.assertEqual(p.idas, [f"{APP}/open.do?gateway=true"])
        self.assertIn("Abrindo a consulta de 2º grau do e-SAJ do TJAL...", p.ctx.status_)

    def test_porta_que_manda_ao_login(self):
        with self.assertRaises(modelos.SessaoPerdida):
            self.portal_na("https://portal.teste/sajcas/login?service=x",
                           sessao=False)._abrir_consulta_2g()
        p = self.portal_na("https://portal.teste/sajcas/login?service=x", sessao=True)
        with self.assertRaises(modelos.PortalIndisponivel):
            p._abrir_consulta_2g()
        self.assertFalse(p._consulta_2g_aberta)

    def test_porta_que_vai_a_outro_lugar(self):
        p = self.portal_na("https://portal.teste/esaj/portal.do")
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            p._abrir_consulta_2g()
        self.assertIn("a consulta de 2º grau do e-SAJ do TJAL não abriu", str(caso.exception))
        self.assertIn("esaj2g-consulta-nao-abriu", p.nav.diagnosticos)

    def test_endereco_da_consulta(self):
        p = portal(TRIBUNAL_2G)
        self.assertTrue(p._na_consulta_2g(f"{APP}/search.do?x=1"))
        self.assertTrue(p._na_consulta_2g(f"{APP}/open.do"))
        self.assertFalse(p._na_consulta_2g("https://portal.teste/cposg5x/open.do"))
        self.assertFalse(p._na_consulta_2g("https://outro.teste/cposg5/open.do"))
        self.assertFalse(p._na_consulta_2g("https://portal.teste/cpopg/open.do"))
        self.assertFalse(p._na_consulta_2g("https://portal.teste/sajcas/login?service="
                                           "https://portal.teste/cposg5/open.do"))


class TestEventos2g(unittest.TestCase):
    def test_eventos_do_portal_com_o_grau(self):
        for tribunal, grau in ((TRIBUNAL_2G, {"grau": "2g"}), (TRIBUNAL_1G, {})):
            ctx = tde.ContextoComEventos()
            p = PortalESAJ(tde.NavegadorDeMentira(), tribunal,
                           opcoes(login={"esaj": "manual"}, espera_login_min=3), ctx, None)
            respostas = [False, False, True]
            p.sessao_ativa = lambda: respostas.pop(0) if respostas else False
            p._esta_logado = lambda pagina=None: False
            p._sessao_no_contexto = lambda: False
            p._abrir_consulta_2g = lambda: None
            with mock.patch.object(esaj, "time", tde.RelogioFalso()):
                p.entrar()
            self.assertEqual([t for t, _ in ctx.eventos], ["login_aguardando", "login_concluido"])
            aguardando, concluido = (d for _, d in ctx.eventos)
            self.assertEqual({k: aguardando[k] for k in ("sistema", "tribunal", "motivo")},
                             {"sistema": "esaj", "tribunal": "TJAL", "motivo": "manual"})
            self.assertEqual({k: v for k, v in aguardando.items() if k == "grau"}, grau)
            self.assertEqual(concluido, {"sistema": "esaj", "tribunal": "TJAL", **grau})

    def test_evento_direto(self):
        ctx = tde.ContextoComEventos()
        portal(TRIBUNAL_2G, ctx)._evento("x", a=1)
        portal(TRIBUNAL_1G, ctx)._evento("x", a=1)
        self.assertEqual(ctx.eventos, [("x", {"a": 1, "grau": "2g"}), ("x", {"a": 1})])


# ============================================================ Pasta Digital
class TestPastaDigital2g(unittest.TestCase):
    def portal(self, respostas, sessao=True, modal_senha=False):
        p = portal(TRIBUNAL_2G)
        p.chamadas, p.portas, p.idas = [], [], []
        fila = list(respostas)

        def buscar(url, metodo="GET", corpo=None, cabecalhos=None):
            p.chamadas.append((url, metodo))
            return fila.pop(0)
        p._buscar_texto = buscar
        p.sessao_ativa = lambda: sessao
        p.modal_senha_visivel = lambda: modal_senha
        p._abrir_consulta_2g = lambda: p.portas.append(1)
        p.ir_para = lambda url, timeout=60000, tentativas=3: p.idas.append(url)
        p._esperar_carga = lambda pagina=None, ms=10000: None
        p._dormir = lambda s: None
        return p

    URL_SG = "https://portal.teste/pastadigital/sg/abrirPastaProcessoDigital.do?cdProcesso=CD&t=1"

    def test_verificar_acesso_e_o_caminho_da_pasta(self):
        p = self.portal([(200, self.URL_SG)])
        self.assertEqual(p._endereco_da_pasta_2g("CD"), self.URL_SG)
        self.assertTrue(p.chamadas[0][0].startswith(
            "/cposg5/verificarAcessoPastaDigital.do?cdProcesso=CD&_="))
        self.assertEqual((p._prefixo_pasta, p._raiz_pasta),
                         ("/pastadigital/sg", "https://portal.teste/pastadigital/sg"))
        self.assertEqual(p.portas, [])

    def test_pdf_e_pecas_no_caminho_da_pasta_do_2o_grau(self):
        p = self.portal([(200, self.URL_SG), (200, "0123abcd-0123-4567-89ab-0123456789ab"),
                         (200, "https://portal.teste/pastadigital/sg/doc.pdf")])
        p._endereco_da_pasta_2g("CD")
        self.assertEqual(p.gerar_pdf([{"parametros": "a=1", "cdDocumento": "1"}], "CD"),
                         "https://portal.teste/pastadigital/sg/doc.pdf")
        self.assertEqual([u for u, _ in p.chamadas[1:]],
                         ["/pastadigital/sg/salvarDocumentoPreparado.do",
                          "/pastadigital/sg/buscarDocumentoFinalizado.do"])
        pedidos = []

        def pedir(url, timeout_ms=300000):
            pedidos.append(url)
            raise RuntimeError("HTTP 404")
        p.pedir_arquivo = pedir
        self.assertIsNone(p.baixar_peca("cdDocumento=1&numInicial=1"))
        self.assertEqual(pedidos, [
            "https://portal.teste/pastadigital/sg/getPDF.do?cdDocumento=1&numInicial=1",
            "https://portal.teste/pastadigital/sg/getArquivo.do?cdDocumento=1&numInicial=1"])

    def test_no_1o_grau_o_caminho_de_sempre(self):
        p = portal(TRIBUNAL_1G)
        self.assertEqual((p._prefixo_pasta, p._raiz_pasta),
                         ("/pastadigital", "https://portal.teste/pastadigital"))

    def test_sso_por_webapp_passa_de_novo_pela_porta(self):
        p = self.portal([(401, "Não foi possível validar o seu acesso."), (200, self.URL_SG)])
        self.assertEqual(p._endereco_da_pasta_2g("CD"), self.URL_SG)
        self.assertEqual(p.portas, [1])
        self.assertEqual(p.idas, [f"{APP}/show.do?processo.codigo=CD"],
                         "volta à página do processo antes de tentar de novo")

    def test_recusada_duas_vezes_e_sem_acesso(self):
        p = self.portal([(401, "Não foi possível validar o seu acesso."),
                         (403, "<div id='popupSenhaProcesso'>...</div>")])
        with self.assertRaises(modelos.SemAcesso) as caso:
            p._endereco_da_pasta_2g("CD")
        self.assertIn("e-SAJ do TJAL (2º grau) não liberou a Pasta Digital", str(caso.exception))
        self.assertEqual(p.portas, [1])

    def test_sessao_caida(self):
        p = self.portal([(401, "Não foi possível validar o seu acesso.")], sessao=False)
        p._consulta_2g_aberta = True
        with self.assertRaises(modelos.SessaoPerdida):
            p._endereco_da_pasta_2g("CD")
        self.assertEqual(p.portas, [])
        self.assertFalse(p._consulta_2g_aberta)

    def test_com_o_modal_de_senha_segue_pela_senha(self):
        p = self.portal([(403, "<div id='popupSenhaProcesso'>senha</div>")], modal_senha=True)
        with self.assertRaises(modelos.SemAcesso) as caso:
            p._endereco_da_pasta_2g("CD")
        self.assertIn("pediu a senha do processo", str(caso.exception))
        self.assertEqual(p.portas, [], "a senha resolve; a porta de entrada não")

    def test_resposta_estranha(self):
        p = self.portal([(200, "<html>Erro</html>")])
        with self.assertRaises(RuntimeError) as caso:
            p._endereco_da_pasta_2g("CD")
        self.assertIn("não consegui abrir a Pasta Digital (HTTP 200", str(caso.exception))
        self.assertTrue(esaj.cheira_a_sessao(str(caso.exception)))


class TestLerPaginaNoGrau(unittest.TestCase):
    def test_o_js_recebe_o_grau_so_no_2o_grau(self):
        for tribunal, argumentos in ((TRIBUNAL_2G, ({"grau": "2g"},)), (TRIBUNAL_1G, ())):
            p = portal(tribunal)
            chamadas = []
            p.nav.pagina.evaluate = lambda js, *a: chamadas.append(a) or {"movs": [1]}
            p.ler_pagina_processo()
            self.assertEqual(chamadas, [argumentos])


if __name__ == "__main__":
    unittest.main()
