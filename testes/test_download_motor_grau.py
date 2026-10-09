"""O 2º grau no motor, no eProc, no navegador e na linha de comando (1.1.0).

O grau de cada processo sai da regra única (cnj.grau_do_processo: o número;
senão o grau do lote) e viaja dentro do Tribunal até as fábricas, o cofre e
o perfil do navegador. Os autos do 2º grau chamam-se "<número> (2G).pdf", e
tudo o que é por arquivo (capa, registro, pasta provisória, linha do
relatório, --retomar, JA_BAIXADO) segue esse nome - a chave dos autos. O
sigilo continua por processo e vale para os dois graus.

Números do Anexo B do desenho (dígito verificador conferido): A, apelação
que existe nos dois graus; H, HC originário (órgão 0000); PL, plantão do 2º
grau (órgão 9002); P e E, o principal e os embargos de declaração (/50000);
I, incidente do 1º grau (/01); S, processo público no 1º grau e sigiloso no
2º. Com portal e navegador de mentira (testes/apoio_download.py); o eProc de
mentira (testes/apoio_eproc.py) só na última classe, que pula sem Chromium.
"""

from __future__ import annotations

import csv
import io
import json
import os
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from helestron.download import cli, eproc, modelos, motor, navegador
from helestron.download.acompanhamento import Acompanhamento, processo_json
from helestron.nucleo import caminhos, cnj, paginacao, sigilo, tribunais

from testes import apoio_download as apoio
from testes.test_download_cli import BaseCli
from testes.test_download_motor import BaseMotor

A = cnj.ler("0700001-93.2024.8.02.0058")
A2 = cnj.ler("0700002-78.2024.8.02.0058")
H = cnj.ler("0803061-28.2025.8.02.0000")
PL = cnj.ler("0800103-29.2025.8.02.9002")
P = cnj.ler("0706265-50.2017.8.02.0001")
E = cnj.ler("0706265-50.2017.8.02.0001/50000")
I = cnj.ler("0700001-93.2024.8.02.0058/01")
S = cnj.ler("0700003-40.2024.8.02.0001")
SP = apoio.numero("0700001", tr="26", origem="0100")          # TJSP: sem o 2º grau no catálogo


def autos(n: cnj.Numero, grau: str) -> str:
    return cnj.nome_dos_autos(n, grau)


def pdf_com_manifesto(caminho: Path, manifesto: dict, paginas: int = 2) -> Path:
    import pymupdf
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(stream=apoio.pdf_bytes(paginas), filetype="pdf")
    paginacao.gravar_no_doc(doc, manifesto)
    doc.save(str(caminho))
    doc.close()
    return caminho


class ContextoComEventos(apoio.ContextoGravador):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.eventos = []

    def evento(self, tipo, **dados):
        self.eventos.append((tipo, dados))


class PortalDoSegredo(apoio.PortalFalso):
    """Como o e-SAJ do 2º grau com o recurso interno de processo em segredo
    (esaj.achar_codigo_2g): a busca cai na página do principal sem o número,
    o pedido sai NAO_SUPORTADO e sigiloso, e o principal também entra nos
    sigilosos apurados. O principal pedido e o incidente do 1º grau (/01)
    saem como no PortalFalso."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sigilosos_apurados: set[str] = set()

    def baixar(self, numero, destino_pdf, senha=None):
        if not numero.e_dependente or self.grau != "2g":
            return super().baixar(numero, destino_pdf, senha)
        self.chamadas.append((numero.formatado, senha))
        self.sigilosos_apurados.update((numero.nome_arquivo, numero.principal))
        r = modelos.ResultadoProcesso(
            ordem=0, numero=numero.formatado, tribunal=self.tribunal.sigla,
            sistema=self.sistema, situacao=modelos.NAO_SUPORTADO,
            detalhe="a consulta de 2º grau abriu a página do processo principal em segredo de "
                    "justiça, sem o número")
        r.sigiloso = True
        return r


class PortalErroApurado(apoio.PortalFalso):
    """O download do recurso interno E falha depois de a página dele se
    mostrar em segredo de justiça: E entra nos sigilosos apurados."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sigilosos_apurados: set[str] = set()

    def baixar(self, numero, destino_pdf, senha=None):
        if numero.formatado != E.formatado:
            return super().baixar(numero, destino_pdf, senha)
        self.chamadas.append((numero.formatado, senha))
        self.sigilosos_apurados.add(numero.nome_arquivo)
        raise RuntimeError("o portal demorou demais")


class BaseGrau(BaseMotor):
    def setUp(self):
        super().setUp()
        self.ctx = ContextoComEventos()

    def lote(self, numeros, grau="1g", roteiro=None, capas=None, cofre=None, destino=None,
             falha_entrar=None, portal=None, **opcoes):
        fp, fn = apoio.fabricas(roteiro, falha_entrar, capas=capas)
        if portal is not None:             # outro dublê do portal (PortalDoSegredo)
            rot = {k: list(v) for k, v in (roteiro or {}).items()}

            def com_portal(nav, tribunal, opcoes_, ctx, credenciais):
                return portal(nav, tribunal, opcoes_, ctx, credenciais, rot, capas=capas)
            fp = com_portal
        self.opcoes = apoio.opcoes_de_teste(self.tmp, grau=grau, **opcoes)
        return motor.executar(numeros, destino or self.destino, self.opcoes, self.ctx,
                              cofre=cofre, fabrica_portal=fp, fabrica_navegador=fn)

    def relatorio(self, arquivo=None) -> list[dict]:
        texto = Path(arquivo or self.destino / "_controle" / "relatorio.csv") \
            .read_bytes().decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


# ====================================================================== grupos
class TestGrupos(BaseGrau):
    def test_lote_do_2o_grau_vai_ao_esaj_do_2o_grau_pelo_tribunal(self):
        # o exemplo do desenho (§4.3)
        resumo = self.lote([A], grau="2g")
        self.assertEqual([(p.portal, p.grau) for p in apoio.PortalFalso.todos],
                         [("esaj:TJAL", "2g")])
        self.assertEqual(apoio.PortalFalso.todos[0].destinos[0].name, f"{autos(A, '2g')}.pdf")
        r = resumo.itens[0]
        self.assertEqual((r.situacao, r.grau), (modelos.OK, "2g"))
        self.assertTrue((self.destino / f"{A.nome_arquivo} (2G).pdf").is_file())
        self.assertFalse((self.destino / f"{A.nome_arquivo}.pdf").exists())

    def test_grupos_por_tribunal_e_grau_com_o_numero_que_so_existe_no_2o(self):
        # num lote do 1º grau, o HC (órgão 0000), o plantão (9002) e os embargos
        # (/50000) vão ao 2º grau: dois grupos do TJAL, na ordem da 1ª aparição
        resumo = self.lote([A, H, P, E, PL, I], grau="1g")
        self.assertEqual([(r.numero, r.grau) for r in resumo.itens],
                         [(A.formatado, "1g"), (H.formatado, "2g"), (P.formatado, "1g"),
                          (E.formatado, "2g"), (PL.formatado, "2g"), (I.formatado, "1g")])
        portais = apoio.PortalFalso.todos
        self.assertEqual([(p.portal, p.grau) for p in portais],
                         [("esaj:TJAL", "1g"), ("esaj:TJAL", "2g")])
        self.assertEqual([c[0] for c in portais[0].chamadas],
                         [A.formatado, P.formatado, I.formatado])
        self.assertEqual([c[0] for c in portais[1].chamadas],
                         [H.formatado, E.formatado, PL.formatado])
        # E e P são dois processos (o /50000 não é o principal), com autos próprios
        nomes = sorted(p.name for p in self.destino.glob("*.pdf"))
        self.assertEqual(nomes, sorted([f"{A.nome_arquivo}.pdf", f"{H.nome_arquivo} (2G).pdf",
                                        f"{P.nome_arquivo}.pdf",
                                        "0706265-50.2017.8.02.0001-50000 (2G).pdf",
                                        f"{PL.nome_arquivo} (2G).pdf", f"{I.nome_arquivo}.pdf"]))
        # o 1º grau continua com os nomes de sempre
        self.assertEqual(I.nome_arquivo, "0700001-93.2024.8.02.0058-01")

    def test_incidente_do_1o_grau_num_lote_do_2o_e_procurado_no_2o(self):
        resumo = self.lote([I], grau="2g")
        self.assertEqual(resumo.itens[0].grau, "2g")
        self.assertEqual([(p.portal, p.grau) for p in apoio.PortalFalso.todos],
                         [("esaj:TJAL", "2g")])

    def test_tribunal_sem_o_2o_grau_no_catalogo_nao_e_suportado(self):
        resumo = self.lote([SP, A], grau="2g")
        sp, a = resumo.itens
        self.assertEqual(sp.situacao, modelos.NAO_SUPORTADO)
        self.assertEqual(sp.causa, "")
        self.assertFalse(sp.refazer)
        self.assertEqual(sp.detalhe, "o 2º grau do e-SAJ do TJSP ainda não é baixado pelo "
                                     "Helestron; baixe-o pelo portal do tribunal")
        self.assertEqual(a.situacao, modelos.OK)
        self.assertEqual([p.tribunal.sigla for p in apoio.PortalFalso.todos], ["TJAL"])
        # o mesmo TJSP no 1º grau, como sempre
        resumo = self.lote([SP], grau="1g", destino=self.tmp / "Acervo" / "Processos" / "SP")
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)

    def test_nome_do_grupo_e_eventos_com_o_grau_so_no_2o(self):
        self.lote([A, H], grau="1g")
        inicios = [d for t, d in self.ctx.eventos if t == "grupo_inicio"]
        self.assertEqual(len(inicios), 2)
        self.assertNotIn("grau", inicios[0], "no 1º grau, o evento de sempre")
        self.assertEqual(inicios[1]["grau"], "2g")
        self.assertIn("Entrando no e-SAJ do TJAL...", self.ctx.status_)
        self.assertIn("Entrando no e-SAJ do TJAL (2º grau)...", self.ctx.status_)

    def test_login_recusado_e_sessao_que_cai_levam_o_grau(self):
        fp, fn = apoio.fabricas({H.formatado: ["sessao", "ok"]})
        self.opcoes = apoio.opcoes_de_teste(self.tmp)
        motor.executar([A, H], self.destino, self.opcoes, self.ctx, fabrica_portal=fp,
                       fabrica_navegador=fn)
        caiu = [d for t, d in self.ctx.eventos if t == "sessao_caiu"]
        self.assertEqual([d.get("grau") for d in caiu], ["2g"])
        # o login recusado nos dois grupos: o evento do 1º grau como era
        fp, fn = apoio.fabricas(falha_entrar={"TJAL": [modelos.LoginFalhou("recusou")]})
        self.ctx = ContextoComEventos()
        motor.executar([A, H], self.tmp / "Acervo" / "Processos" / "Outro", self.opcoes,
                       self.ctx, fabrica_portal=fp, fabrica_navegador=fn)
        falhou = [d for t, d in self.ctx.eventos if t == "login_falhou"]
        self.assertEqual([d.get("grau") for d in falhou], [None, "2g"])
        self.assertEqual([t for t, _ in self.ctx.avisos],
                         ["Não foi possível entrar no e-SAJ do TJAL",
                          "Não foi possível entrar no e-SAJ do TJAL (2º grau)"])


# ======================================================== nomes dos autos
class TestNomesDosAutos(BaseGrau):
    def test_a_nos_dois_graus_na_mesma_pasta_sem_colisao(self):
        r1 = self.lote([A], grau="1g").itens[0]
        r2 = self.lote([A], grau="2g").itens[0]
        self.assertEqual((r1.situacao, r2.situacao), (modelos.OK, modelos.OK),
                         "o PDF do 1º grau não é JA_BAIXADO de um pedido do 2º")
        controle = self.destino / "_controle"
        for nome in (A.nome_arquivo, f"{A.nome_arquivo} (2G)"):
            self.assertTrue((self.destino / f"{nome}.pdf").is_file(), nome)
            self.assertTrue((controle / f"{nome}_capa.txt").is_file(), nome)
            self.assertTrue((controle / f"{nome}_meta.json").is_file(), nome)
        meta1 = json.loads((controle / f"{A.nome_arquivo}_meta.json").read_text("utf-8"))
        meta2 = json.loads((controle / f"{A.nome_arquivo} (2G)_meta.json").read_text("utf-8"))
        self.assertNotIn("grau", meta1, "o registro do 1º grau fica como era")
        self.assertEqual(meta2["grau"], "2g")
        self.assertNotIn("grau", meta1["consultas"][0])
        self.assertEqual(meta2["consultas"], [{"sistema": "esaj", "situacao": "OK",
                                               "grau": "2g"}])
        # a pasta provisória é por chave dos autos, e é apagada
        self.assertEqual(list((self.tmp / "provisorio").iterdir()), [])
        # o relatório tem as duas linhas, cada uma com o grau
        linhas = self.relatorio()
        self.assertEqual([(l["processo"], l["grau"], l["arquivo"]) for l in linhas],
                         [(A.formatado, "1g", f"{A.nome_arquivo}.pdf"),
                          (A.formatado, "2g", f"{A.nome_arquivo} (2G).pdf")])
        # rodando de novo, cada grau acha o seu
        r1 = self.lote([A], grau="1g").itens[0]
        r2 = self.lote([A], grau="2g").itens[0]
        self.assertEqual((r1.situacao, r2.situacao), (modelos.JA_BAIXADO, modelos.JA_BAIXADO))
        self.assertEqual((Path(r1.arquivo).name, Path(r2.arquivo).name),
                         (f"{A.nome_arquivo}.pdf", f"{A.nome_arquivo} (2G).pdf"))
        self.assertEqual(len(self.relatorio()), 2)

    def test_manifesto_do_outro_grau_baixa_de_novo(self):
        # um PDF com o nome dos autos do 2º grau cujo manifesto não diz grau (1º)
        pdf_com_manifesto(self.destino / f"{A.nome_arquivo} (2G).pdf",
                          paginacao.manifesto_esaj(A.formatado, 2, tribunal="TJAL"))
        r = self.lote([A], grau="2g").itens[0]
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("baixado de novo: o PDF na pasta é do outro grau", r.detalhe)
        # e o inverso: o do 1º grau com o manifesto do 2º
        pdf_com_manifesto(self.destino / f"{A2.nome_arquivo}.pdf",
                          paginacao.manifesto_esaj(A2.formatado, 2, tribunal="TJAL", grau="2g"))
        r = self.lote([A2], grau="1g").itens[0]
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("o PDF na pasta é do outro grau", r.detalhe)
        # manifesto do mesmo grau: já estava
        pdf_com_manifesto(self.destino / f"{H.nome_arquivo} (2G).pdf",
                          paginacao.manifesto_esaj(H.formatado, 2, tribunal="TJAL", grau="2g"))
        r = self.lote([H], grau="1g").itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO, r.detalhe)
        self.assertEqual(r.paginacao.get("grau"), "2g")

    def test_json_do_processo_com_o_grau_e_o_nome_dos_autos(self):
        resumo = self.lote([A, H], grau="1g", roteiro={H.formatado: ["nao_encontrado"]})
        a, h = resumo.itens
        pa, ph = processo_json(a), processo_json(h)
        self.assertEqual((pa["grau"], pa["nome_arquivo"]), ("1g", A.nome_arquivo))
        # sem PDF, o nome que os autos teriam
        self.assertEqual((ph["grau"], ph["nome_arquivo"]), ("2g", f"{H.nome_arquivo} (2G)"))
        self.assertNotIn("grau", pa["consultas"][0])
        self.assertEqual(ph["consultas"][-1].get("grau"), "2g")


# ============================================================ credenciais
class TestCredenciaisEPerfil(BaseGrau):
    def test_alternativo_do_2o_grau_pede_o_eproc2g_e_nunca_o_eproc_do_1o(self):
        cofre = apoio.CofreFalso({"esaj:TJAL": ("u", "s"), "eproc:TJAL": ("u1", "s1"),
                                  "eproc2g:TJAL": ("u2", "s2")})
        resumo = self.lote([A], grau="2g", roteiro={A.formatado: ["nao_encontrado"]},
                           cofre=cofre)
        self.assertEqual(cofre.pedidos, ["esaj:TJAL", "eproc2g:TJAL"])
        esaj, eproc_ = apoio.PortalFalso.todos
        self.assertEqual((eproc_.portal, eproc_.grau, eproc_.credenciais),
                         ("eproc2g:TJAL", "2g", ("u2", "s2")))
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(resumo.itens[0].sistema, "eproc")

    def test_sem_a_senha_do_eproc2g_so_esse_grupo_abre_a_janela(self):
        cofre = apoio.CofreFalso({"esaj:TJAL": ("u", "s"), "eproc:TJAL": ("u1", "s1")})
        self.lote([A], grau="2g", roteiro={A.formatado: ["nao_encontrado"]}, cofre=cofre)
        self.assertNotIn("eproc:TJAL", cofre.pedidos, "a senha do 1º grau nunca vai ao 2º")
        esaj, eproc_ = apoio.PortalFalso.todos
        self.assertEqual(esaj.opcoes.modo_login("esaj"), "senha")
        self.assertIsNone(eproc_.credenciais)
        self.assertEqual(eproc_.opcoes.modo_login("eproc"), "manual")

    def test_nao_encontrado_nos_dois_sistemas_do_2o_grau(self):
        for n in (A, H, PL, E):
            with self.subTest(n.formatado):
                self.ctx = ContextoComEventos()
                resumo = self.lote([n], grau="2g",
                                   roteiro={n.formatado: ["nao_encontrado", "nao_encontrado"]},
                                   destino=self.tmp / "Acervo" / "Processos" / n.nome_arquivo)
                r = resumo.itens[0]
                self.assertEqual(r.situacao, modelos.NAO_ENCONTRADO)
                self.assertTrue(r.detalhe.startswith(
                    "não encontrado no e-SAJ nem no eProc do TJAL (2º grau); confira o número; "),
                    r.detalhe)
                self.assertIn(modelos.dica_de_grau(n, "2g"), r.detalhe)
                self.assertEqual([c.get("grau") for c in r.consultas], ["2g", "2g"])
        # no 1º grau, a frase de sempre
        self.ctx = ContextoComEventos()
        r = self.lote([A2], grau="1g", roteiro={A2.formatado: ["nao_encontrado"] * 2},
                      destino=self.tmp / "Acervo" / "Processos" / "1g").itens[0]
        self.assertEqual(r.detalhe, "não encontrado no e-SAJ nem no eProc do TJAL; confira o "
                                    "número")

    def test_perfil_do_navegador_por_portal(self):
        abertos = []
        t = tribunais.por_sigla("TJAL")
        with mock.patch.object(navegador, "Navegador",
                               lambda perfil, **k: abertos.append(Path(perfil)) or perfil):
            opcoes = apoio.opcoes_de_teste(self.tmp)
            for alvo in (t, t.alternativo, t.no_grau("2g"), t.no_grau("2g").alternativo):
                motor.fabrica_navegador_padrao(alvo, opcoes)
            # dublê de Tribunal sem 'perfil': o nome de sempre
            motor.fabrica_navegador_padrao(
                types.SimpleNamespace(sistema="esaj", sigla="TJXX", urls={}), opcoes)
        self.assertEqual([p.name for p in abertos],
                         ["esaj-TJAL", "eproc-TJAL", "esaj-TJAL", "eproc2g-TJAL", "esaj-TJXX"])
        self.assertTrue(all(p.parent == caminhos.PERFIS for p in abertos))

    def test_pastas_e_esquecer_o_eproc_do_2o_grau(self):
        perfis = self.tmp / "perfis"
        self.assertEqual([p.name for p in navegador.pastas_do_portal("eproc2g:TJAL", perfis)],
                         ["eproc2g-TJAL", "eproc2g-TJAL-certificado"])
        self.assertEqual([p.name for p in navegador.pastas_do_portal("eproc:tjal", perfis)],
                         ["eproc-TJAL", "eproc-TJAL-certificado"])
        for nome in ("eproc-TJAL", "eproc-TJAL-certificado", "eproc2g-TJAL",
                     "eproc2g-TJAL-certificado", "esaj-TJAL"):
            (perfis / nome).mkdir(parents=True)
            (perfis / nome / "sessao.json").write_text("{}", encoding="utf-8")
        self.assertTrue(navegador.esquecer_portal("eproc2g:TJAL", perfis))
        self.assertEqual(sorted(p.name for p in perfis.iterdir() if p.is_dir()),
                         ["eproc-TJAL", "eproc-TJAL-certificado", "esaj-TJAL"])
        for invalido in ("eproc3g:TJAL", "eproc2g:../../x", "eproc2g:"):
            with self.assertRaises(ValueError):
                navegador.pastas_do_portal(invalido, perfis)


# ============================================================== relatório
class TestRelatorioPorGrau(BaseGrau):
    def gravar_csv(self, pasta: Path, linhas: list[list], colunas=None):
        colunas = colunas or motor.COLUNAS
        arquivo = pasta / "_controle" / "relatorio.csv"
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        corpo = "\r\n".join(";".join(str(c) for c in l) for l in [colunas] + linhas)
        arquivo.write_bytes(("﻿" + corpo + "\r\n").encode("utf-8"))
        return arquivo

    def test_relatorio_da_1_0_2_com_o_hc_nao_encontrado_vira_uma_linha_so(self):
        antigas = motor.COLUNAS[:-1]            # 1.0.2: sem a coluna "grau"
        self.gravar_csv(self.destino, [
            [1, A.formatado, "TJAL", "esaj", "OK", 2, 1, f"{A.nome_arquivo}.pdf", "não", "", "",
             "2026-01-01 10:00:00", ""],
            [2, H.formatado, "TJAL", "esaj", "NAO_ENCONTRADO", "", "", "", "não", "",
             "não encontrado no e-SAJ nem no eProc do TJAL; confira o número",
             "2026-01-01 10:01:00", ""]], antigas)
        (self.destino / f"{A.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(2))
        lidas = motor.ler_relatorio_do_lote(self.destino, self.tmp / "Sigilosos")
        # a linha antiga do HC, sem grau, vale como do 2º grau (o número só existe nele)
        self.assertEqual([c for c, _ in lidas], [A.nome_arquivo, f"{H.nome_arquivo} (2G)"])
        # o --retomar a retoma (sem --grau: o HC vai ao 2º grau assim mesmo)
        opcoes = apoio.opcoes_de_teste(self.tmp)
        numeros, ignorados = cli._retomar([], self.destino, opcoes, None, motor, modelos, cnj)
        self.assertEqual([n.formatado for n in numeros], [H.formatado])
        self.assertEqual(ignorados, [])
        # a rodada da 1.1.0 troca a linha antiga pela nova: uma linha só do HC
        resumo = self.lote([H], grau="1g")
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        linhas = self.relatorio()
        self.assertEqual([(l["processo"], l["situacao"], l["grau"]) for l in linhas],
                         [(A.formatado, "OK", "1g"), (H.formatado, "OK", "2g")])

    def test_retomar_por_grau(self):
        self.gravar_csv(self.destino, [
            [1, A.formatado, "TJAL", "esaj", "ERRO", "", "", "", "não", "", "x", "", "falha",
             "1g"],
            [2, A.formatado, "TJAL", "esaj", "ERRO", "", "", "", "não", "", "x", "", "falha",
             "2g"],
            [3, A2.formatado, "TJAL", "esaj", "ERRO", "", "", "", "não", "", "x", "", "falha",
             "1g"]])
        opcoes = apoio.opcoes_de_teste(self.tmp, grau="2g")
        numeros, ignorados = cli._retomar([], self.destino, opcoes, None, motor, modelos, cnj)
        self.assertEqual([n.formatado for n in numeros], [A.formatado])
        self.assertEqual([(i["numero"], i["motivo"]) for i in ignorados],
                         [(A.formatado, "do 1º grau: para retomá-la, use --grau 1g"),
                          (A2.formatado, "do 1º grau: para retomá-la, use --grau 1g")])
        opcoes = apoio.opcoes_de_teste(self.tmp, grau="1g")
        numeros, ignorados = cli._retomar([], self.destino, opcoes, None, motor, modelos, cnj)
        self.assertEqual([n.formatado for n in numeros], [A.formatado, A2.formatado])
        self.assertEqual([i["motivo"] for i in ignorados],
                         ["do 2º grau: para retomá-la, use --grau 2g"])
        # a relação pede A no grau do lote: a linha dele é a desse grau
        numeros, _ = cli._retomar([A], self.destino, opcoes, None, motor, modelos, cnj)
        self.assertEqual([n.formatado for n in numeros], [A.formatado, A2.formatado])

    def test_retomar_baixado_do_2o_grau_cujo_pdf_saiu(self):
        self.lote([A], grau="2g")
        (self.destino / f"{A.nome_arquivo} (2G).pdf").unlink()
        opcoes = apoio.opcoes_de_teste(self.tmp, grau="2g")
        numeros, _ = cli._retomar([], self.destino, opcoes, None, motor, modelos, cnj)
        self.assertEqual([n.formatado for n in numeros], [A.formatado])
        # o do 1º grau na pasta não conta para os autos do 2º
        (self.destino / f"{A.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(2))
        numeros, _ = cli._retomar([A], self.destino, opcoes, None, motor, modelos, cnj)
        self.assertEqual([n.formatado for n in numeros], [A.formatado])

    def test_linha_mascarada_leva_o_grau(self):
        resumo = self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]})
        self.assertTrue(resumo.itens[0].sigiloso)
        linha = self.relatorio()[0]
        self.assertEqual((linha["processo"], linha["grau"]), (motor.MASCARA_SIGILOSO, "2g"))
        completo = self.relatorio(self.tmp / "Sigilosos" / self.destino.name / "_controle" /
                                  "relatorio.csv")
        self.assertEqual((completo[0]["processo"], completo[0]["grau"]), (A.formatado, "2g"))

    def test_mascarar_mantem_a_linha_do_2o_grau_que_so_o_completo_tem(self):
        raiz = self.tmp / "Sigilosos"
        lote = self.tmp / "Acervo" / "Processos" / "Lote X"
        self.gravar_csv(lote, [
            [1, A.formatado, "TJAL", "esaj", "OK", 2, 1, f"{A.nome_arquivo}.pdf", "não", "",
             "", "", "", "1g"]])
        self.gravar_csv(raiz / "Lote X", [
            [5, A.formatado, "TJAL", "esaj", "OK", 2, 1, f"{A.nome_arquivo} (2G).pdf", "sim", "",
             "", "", "", "2g"]])
        ret = motor.Retirada()
        motor._mascarar_relatorios(ret, [lote], raiz, {A.nome_arquivo})
        completo = self.relatorio(raiz / "Lote X" / "_controle" / "relatorio.csv")
        self.assertEqual([(l["processo"], l["grau"], l["sigiloso"]) for l in completo],
                         [(A.formatado, "1g", "sim"), (A.formatado, "2g", "sim")])
        do_lote = self.relatorio(lote / "_controle" / "relatorio.csv")
        self.assertEqual([(l["processo"], l["grau"]) for l in do_lote],
                         [(motor.MASCARA_SIGILOSO, "1g")])

    def test_a_dos_dois_graus_sigiloso_no_mesmo_lote(self):
        self.lote([A], grau="1g", roteiro={A.formatado: ["ok_sigiloso"]})
        self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]})
        completo = self.relatorio(self.tmp / "Sigilosos" / self.destino.name / "_controle" /
                                  "relatorio.csv")
        self.assertEqual([(l["processo"], l["grau"]) for l in completo],
                         [(A.formatado, "1g"), (A.formatado, "2g")])
        self.assertEqual([(l["processo"], l["grau"]) for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, "1g"), (motor.MASCARA_SIGILOSO, "2g")])
        sig = self.tmp / "Sigilosos" / self.destino.name
        self.assertTrue((sig / f"{A.nome_arquivo}.pdf").is_file())
        self.assertTrue((sig / f"{A.nome_arquivo} (2G).pdf").is_file())

    def test_a_publico_no_1o_grau_e_sigiloso_no_2o_no_mesmo_lote(self):
        """Achado C1: A baixado público no 1º grau numa rodada anterior do
        MESMO lote; a rodada seguinte, no 2º grau, apura o segredo. A
        retirada leva os autos dos dois graus e mascara o relatório no disco,
        e o salvar_relatorio que vem logo depois (regravado a partir das
        linhas lidas no início da rodada) não pode devolver o número de A
        pela linha antiga do 1º grau, que ainda diz "não"."""
        r = self.lote([A], grau="1g").itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.OK, False))
        r = self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]}).itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.OK, True))
        sig = self.tmp / "Sigilosos" / self.destino.name
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertTrue((sig / f"{A.nome_arquivo}.pdf").is_file())
        self.assertTrue((sig / f"{A.nome_arquivo} (2G).pdf").is_file())
        # as duas linhas mascaradas no relatório do acervo...
        self.assertEqual([(l["processo"], l["sigiloso"], l["arquivo"], l["grau"])
                          for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, "sim", "", "1g"),
                          (motor.MASCARA_SIGILOSO, "sim", "", "2g")])
        self.assertNotIn(A.nome_arquivo, (self.destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))
        # ... e completas, com sigiloso "sim", na pasta de sigilosos
        completo = sig / "_controle" / "relatorio.csv"
        self.assertEqual([(l["processo"], l["sigiloso"], l["arquivo"], l["grau"])
                          for l in self.relatorio(completo)],
                         [(A.formatado, "sim", f"{A.nome_arquivo}.pdf (na pasta de sigilosos)",
                           "1g"),
                          (A.formatado, "sim",
                           f"{A.nome_arquivo} (2G).pdf (na pasta de sigilosos)", "2g")])
        # a rodada seguinte no lote, com outro processo, mantém as duas mascaradas
        self.lote([A2], grau="1g")
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, "sim"), (motor.MASCARA_SIGILOSO, "sim"),
                          (A2.formatado, "não")])
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio(completo)],
                         [(A.formatado, "sim"), (A.formatado, "sim"), (A2.formatado, "não")])

    def test_incidente_baixado_antes_do_principal_sigiloso_na_mesma_rodada(self):
        """O incidente I vem antes de A na relação e é baixado público; A
        então se apura sigiloso, e a retirada leva I junto (herda o sigilo).
        A linha de I sai mascarada, e o item dele (o JSON do lote) diz que é
        sigiloso e onde o PDF está."""
        i, a = self.lote([I, A], grau="1g", roteiro={A.formatado: ["ok_sigiloso"]}).itens
        self.assertEqual((a.situacao, a.sigiloso), (modelos.OK, True))
        sig = self.tmp / "Sigilosos" / self.destino.name
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertTrue((sig / f"{I.nome_arquivo}.pdf").is_file())
        self.assertEqual((i.situacao, i.sigiloso, i.arquivo),
                         (modelos.OK, True, str(sig / f"{I.nome_arquivo}.pdf")))
        self.assertIn("levado agora para a pasta de sigilosos", i.detalhe)
        self.assertEqual((processo_json(i)["sigiloso"], processo_json(i)["pdf"]),
                         (True, str(sig / f"{I.nome_arquivo}.pdf")))
        self.assertEqual([(l["processo"], l["sigiloso"], l["arquivo"], l["grau"])
                          for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, "sim", "", "1g"),
                          (motor.MASCARA_SIGILOSO, "sim", "", "1g")])
        self.assertEqual([(l["processo"], l["sigiloso"], l["arquivo"])
                          for l in self.relatorio(sig / "_controle" / "relatorio.csv")],
                         [(I.formatado, "sim", f"{I.nome_arquivo}.pdf (na pasta de sigilosos)"),
                          (A.formatado, "sim", f"{A.nome_arquivo}.pdf (na pasta de sigilosos)")])

    def test_incidente_preso_no_acervo_quando_o_principal_vira_sigiloso(self):
        """Achado V4: I, baixado público numa rodada anterior, está aberto no
        leitor (preso) quando A se apura sigiloso. A retirada não o leva; o
        relatório do acervo o mascara, e o item (o JSON do lote) tem de dizer
        que é sigiloso, com o PDF onde ficou - não "público, no lote"."""
        self.lote([I], grau="1g")
        preso = self.destino / f"{I.nome_arquivo}.pdf"
        original = motor._mover

        def falha(origem, destino, *a):
            if Path(origem) == preso:
                raise PermissionError(13, "Acesso negado", str(origem))
            return original(origem, destino, *a)
        with mock.patch.object(motor, "_mover", falha):
            resumo = self.lote([I, A], grau="1g", roteiro={A.formatado: ["ok_sigiloso"]})
        i, a = resumo.itens
        self.assertEqual((a.situacao, a.causa), (modelos.ERRO, motor.CAUSA_SIGILO_NO_ACERVO))
        self.assertEqual(resumo.sigilosos_no_acervo, [str(preso)])
        self.assertTrue(preso.is_file())
        self.assertEqual((i.situacao, i.sigiloso, i.arquivo),
                         (modelos.JA_BAIXADO, True, str(preso)))
        self.assertIn("a cópia dos autos ficou presa no acervo", i.detalhe)
        self.assertEqual((processo_json(i)["sigiloso"], processo_json(i)["pdf"]),
                         (True, str(preso)))
        self.assertEqual(self.ctx.itens.count((I.formatado, modelos.JA_BAIXADO)), 2,
                         "o item de I é publicado de novo, já sigiloso")
        self.assertNotIn(I.nome_arquivo, (self.destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))
        self.assertEqual([(l["processo"], l["situacao"], l["sigiloso"]) for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, modelos.JA_BAIXADO, "sim"),
                          (motor.MASCARA_SIGILOSO, modelos.ERRO, "sim")])
        completo = self.relatorio(self.tmp / "Sigilosos" / self.destino.name / "_controle" /
                                  "relatorio.csv")
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in completo],
                         [(I.formatado, "sim"), (A.formatado, "sim")])
        self.assertEqual(completo[0]["arquivo"], f"{I.nome_arquivo}.pdf", "ficou no lote")

    def test_completo_preso_na_rodada_do_sigilo_nao_devolve_o_numero(self):
        """Achado V3: o relatório COMPLETO (o da pasta de sigilosos) estava
        aberto no Excel na rodada em que A, público no 1º grau, se apurou
        sigiloso no 2º: ficou com a linha antiga de A dizendo "não". Na
        rodada seguinte, a linha mascarada do lote é trocada pela dele e tem
        de sair sigilosa - senão o número de A voltava ao relatório do
        acervo, sem aviso. E o aviso da rodada do sigilo nomeia o arquivo
        que de fato ficou preso: o completo, não o relatório do lote."""
        self.lote([S], grau="1g", roteiro={S.formatado: ["ok_sigiloso"]})   # o completo já existe
        self.lote([A], grau="1g")
        sig = self.tmp / "Sigilosos" / self.destino.name
        completo = sig / "_controle" / "relatorio.csv"
        original = os.replace

        def preso(origem, destino, *a, **k):
            if Path(destino) == completo:
                raise PermissionError(13, "O arquivo está sendo usado por outro processo",
                                      str(destino))
            return original(origem, destino, *a, **k)
        with mock.patch.object(motor.os, "replace", preso):
            resumo = self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]})
        self.assertTrue(resumo.itens[0].sigiloso)
        # o aviso, no detalhe do item; fora do acervo, não entra nos avisos do lote
        self.assertIn("o relatório completo da pasta de sigilosos não pôde ser atualizado: "
                      f"{Path(self.destino.name) / '_controle' / 'relatorio.csv'}",
                      resumo.itens[0].detalhe)
        self.assertEqual(resumo.sigilosos_avisos, [])
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio(completo)],
                         [(S.formatado, "sim"), (A.formatado, "não")],
                         "o completo ficou como estava, desatualizado")
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, "sim")] * 3)
        # a rodada seguinte, com o Excel fechado, relê esse completo
        self.lote([A2], grau="1g")
        self.assertNotIn(A.nome_arquivo, (self.destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))
        self.assertEqual([(l["processo"], l["sigiloso"], l["grau"]) for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, "sim", "1g"),
                          (motor.MASCARA_SIGILOSO, "sim", "1g"),
                          (motor.MASCARA_SIGILOSO, "sim", "2g"), (A2.formatado, "não", "1g")])
        self.assertEqual([(l["processo"], l["sigiloso"], l["grau"])
                          for l in self.relatorio(completo)][:2],
                         [(S.formatado, "sim", "1g"), (A.formatado, "sim", "1g")],
                         "o completo regravado passa a dizer que A é sigiloso")

    def test_aviso_do_completo_preso_nao_manda_mover_nada(self):
        """Achados W7 e X2: o relatório completo preso fica na pasta de
        sigilosos, fora do acervo. O aviso não diz que algo "ficou no acervo"
        nem manda movê-lo para a pasta de sigilosos, onde ele já está: diz
        qual é e que basta fechá-lo. E ele não entra nos avisos do lote
        (sigilosos_avisos), de onde o fim do lote, o Início e a tela
        Compartilhar diriam "Arquivo de processo sigiloso no acervo"."""
        self.lote([S], grau="1g", roteiro={S.formatado: ["ok_sigiloso"]})   # o completo já existe
        self.lote([A], grau="1g")
        completo = self.tmp / "Sigilosos" / self.destino.name / "_controle" / "relatorio.csv"
        original = os.replace

        def preso(origem, destino, *a, **k):
            if Path(destino) == completo:
                raise PermissionError(13, "O arquivo está sendo usado por outro processo",
                                      str(destino))
            return original(origem, destino, *a, **k)
        with mock.patch.object(motor.os, "replace", preso):
            resumo = self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]})
        r = resumo.itens[0]
        self.assertEqual(resumo.sigilosos_avisos, [])
        self.assertEqual(self.ctx.avisos, [])
        self.assertNotIn("ficou no acervo", r.detalhe)
        self.assertNotIn("mova-o", r.detalhe)
        self.assertIn("atenção: o relatório completo da pasta de sigilosos não pôde ser "
                      f"atualizado: {Path(self.destino.name) / '_controle' / 'relatorio.csv'} "
                      "(está aberto em outro programa?). Feche-o: o próximo download do lote o "
                      "regrava", r.detalhe)

    def test_completo_preso_de_outro_lote_avisa_o_relatorio_do_lote(self):
        """Achado Y1: A, pública no Lote X (que já tem um sigiloso e, por isso,
        o relatório completo na pasta de sigilosos), se mostra sigilosa no
        Lote Y com o completo do Lote X aberto no Excel. O relatório do Lote
        X, no acervo, fica com o número de A até o acervo ser preparado de
        novo: é aviso do lote também sem o preparo do fim (--sem-ia, "Parar"),
        com o porquê, como na 1.0.2 - uma vez só, mesmo com dois processos
        da rodada nele -, e o detalhe não manda movê-lo, nem promete que o
        próximo download do lote tira o número. Só o 1º grau."""
        lote_x = self.tmp / "Acervo" / "Processos" / "Lote X"
        self.lote([S], roteiro={S.formatado: ["ok_sigiloso"]}, destino=lote_x)
        self.lote([A, A2], destino=lote_x)
        completo = self.tmp / "Sigilosos" / "Lote X" / "_controle" / "relatorio.csv"
        do_acervo = lote_x / "_controle" / "relatorio.csv"
        original = os.replace

        def preso(origem, destino, *a, **k):
            if Path(destino) == completo:
                raise PermissionError(13, "O arquivo está sendo usado por outro processo",
                                      str(destino))
            return original(origem, destino, *a, **k)
        self.ctx = ContextoComEventos()
        with mock.patch.object(motor.os, "replace", preso):
            resumo = self.lote([A, A2], roteiro={A.formatado: ["ok_sigiloso"],
                                                 A2.formatado: ["ok_sigiloso"]},
                               destino=self.tmp / "Acervo" / "Processos" / "Lote Y")
        a = resumo.itens[0]
        self.assertEqual([(r.grau, r.sigiloso) for r in resumo.itens], [("1g", True)] * 2)
        texto = do_acervo.read_bytes().decode("utf-8-sig")
        self.assertTrue(A.formatado in texto and A2.formatado in texto, "os números ficaram")
        porque = ("o relatório completo do lote, na pasta dos sigilosos, não pôde ser "
                  "atualizado: está aberto em outro programa?")
        self.assertEqual(resumo.sigilosos_avisos, [str(do_acervo)])
        self.assertEqual(resumo.sigilosos_motivos[str(do_acervo)], porque)
        self.assertEqual(resumo.sigilosos_no_acervo, [])
        [(titulo, frase)] = self.ctx.avisos
        self.assertEqual(titulo, "Arquivo de processo sigiloso no acervo")
        self.assertTrue(frase.startswith("Um arquivo de um processo em segredo de justiça ficou "
                                         "no acervo: relatorio.csv, que ainda traz o número "
                                         f"dele ({porque})"), frase)
        self.assertIn("atenção: o relatório completo da pasta de sigilosos não pôde ser "
                      f"atualizado: {Path('Lote X') / '_controle' / 'relatorio.csv'} "
                      "(está aberto em outro programa?). Feche-o e prepare o acervo para a IA "
                      "de novo: até lá, o relatório do lote no acervo continua com o número "
                      "dele", a.detalhe)
        self.assertNotIn("próximo download", a.detalhe)
        self.assertNotIn("mova-o", a.detalhe)

    def completo_preso_no_lote_em_curso(self, relatorio_aberto: bool) -> tuple:
        """Achado Z1: A, pública no Lote X (que já tem o relatório completo),
        se mostra sigilosa no 2º grau no próprio Lote X, com o completo
        aberto no Excel. 'relatorio_aberto': o relatorio.csv do lote também
        está aberto (salvar_relatorio grava o "(atualizado)"); sem isso, há
        um "(atualizado)" antigo, de uma rodada em que o relatorio.csv estava
        aberto. Devolve o resumo e o relatório do lote que fica com o número
        de A (o outro, salvar_relatorio o regrava mascarado)."""
        lote_x = self.tmp / "Acervo" / "Processos" / "Lote X"
        do_lote = lote_x / "_controle" / "relatorio.csv"
        atualizado = lote_x / "_controle" / "relatorio (atualizado).csv"
        completo = self.tmp / "Sigilosos" / "Lote X" / "_controle" / "relatorio.csv"
        presos: set[Path] = set()
        original = os.replace

        def preso(origem, destino, *a, **k):
            if Path(destino) in presos:
                raise PermissionError(13, "O arquivo está sendo usado por outro processo",
                                      str(destino))
            return original(origem, destino, *a, **k)
        self.lote([S], roteiro={S.formatado: ["ok_sigiloso"]}, destino=lote_x)
        with mock.patch.object(motor.os, "replace", preso):
            if relatorio_aberto:
                self.lote([A], destino=lote_x)           # A pública, no relatorio.csv
                presos = {completo, do_lote}
            else:
                presos = {do_lote}
                self.lote([A], destino=lote_x)           # A pública, no "(atualizado)"
                presos = {completo}
            self.ctx = ContextoComEventos()
            resumo = self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]},
                               destino=lote_x)
        self.assertEqual([(r.grau, r.sigiloso) for r in resumo.itens], [("2g", True)])
        fica, regravado = (do_lote, atualizado) if relatorio_aberto else (atualizado, do_lote)
        self.assertIn(A.formatado, fica.read_bytes().decode("utf-8-sig"), "o número ficou")
        self.assertNotIn(A.formatado, regravado.read_bytes().decode("utf-8-sig"))
        return resumo, fica

    def avisa_o_relatorio_que_ficou(self, relatorio_aberto: bool) -> None:
        """Achado Z1: o relatório do lote em curso que salvar_relatorio não
        regrava fica com o número no acervo; é aviso do lote (como na 1.0.2),
        e o detalhe manda preparar o acervo de novo."""
        resumo, fica = self.completo_preso_no_lote_em_curso(relatorio_aberto)
        a = resumo.itens[0]
        self.assertIn(str(fica), resumo.sigilosos_avisos)
        self.assertEqual(resumo.sigilosos_avisos, [str(fica)], "o regravado não é aviso")
        self.assertEqual(resumo.sigilosos_motivos[str(fica)],
                         "o relatório completo do lote, na pasta dos sigilosos, não pôde ser "
                         "atualizado: está aberto em outro programa?")
        [(titulo, _frase)] = self.ctx.avisos
        self.assertEqual(titulo, "Arquivo de processo sigiloso no acervo")
        self.assertIn("Feche-o e prepare o acervo para a IA de novo: até lá, o relatório do "
                      "lote no acervo continua com o número dele", a.detalhe)
        self.assertNotIn("próximo download", a.detalhe)

    def test_completo_preso_com_o_relatorio_do_lote_aberto_avisa(self):
        # o relatorio.csv aberto no Excel: o lote grava o "(atualizado)", e o
        # relatorio.csv fica com o número
        self.avisa_o_relatorio_que_ficou(relatorio_aberto=True)

    def test_completo_preso_com_o_atualizado_antigo_avisa(self):
        # o "(atualizado)" antigo: salvar_relatorio regrava só o relatorio.csv
        self.avisa_o_relatorio_que_ficou(relatorio_aberto=False)

    def test_completo_preso_com_o_relatorio_aberto_depois_do_inicio_avisa(self):
        """Achados Q3 e Q5 da sétima verificação: o completo preso desde o
        início e o relatorio.csv do lote aberto no Excel DEPOIS do início do
        lote (a primeira gravação dele passa; as seguintes, não).
        _retirar_do_acervo o tirava dos avisos por ser o relatório que o lote
        está gravando, e salvar_relatorio, que passa ao "(atualizado)", não o
        regravava mais: ele ficava no acervo com o número de A, sem aviso (a
        1.0.2 avisava). Agora salvar_relatorio o põe nos avisos."""
        lote_x = self.tmp / "Acervo" / "Processos" / "Lote X"
        do_lote = lote_x / "_controle" / "relatorio.csv"
        atualizado = lote_x / "_controle" / "relatorio (atualizado).csv"
        completo = self.tmp / "Sigilosos" / "Lote X" / "_controle" / "relatorio.csv"
        self.lote([S], roteiro={S.formatado: ["ok_sigiloso"]}, destino=lote_x)
        self.lote([A], destino=lote_x)                   # A pública, no relatorio.csv
        gravacoes = []
        original = os.replace

        def preso(origem, destino, *a, **k):
            gravacoes.append(Path(destino))
            if Path(destino) == completo or (Path(destino) == do_lote
                                             and gravacoes.count(do_lote) > 1):
                raise PermissionError(13, "O arquivo está sendo usado por outro processo",
                                      str(destino))
            return original(origem, destino, *a, **k)
        self.ctx = ContextoComEventos()
        with mock.patch.object(motor.os, "replace", preso):
            resumo = self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]},
                               destino=lote_x)
        self.assertEqual([(r.grau, r.sigiloso) for r in resumo.itens], [("2g", True)])
        self.assertGreater(gravacoes.count(do_lote), 1, "aberto depois da 1ª gravação")
        self.assertIn(A.formatado, do_lote.read_bytes().decode("utf-8-sig"), "o número ficou")
        self.assertNotIn(A.formatado, atualizado.read_bytes().decode("utf-8-sig"))
        self.assertIn(str(do_lote), resumo.sigilosos_avisos)
        self.assertEqual(resumo.sigilosos_avisos, [str(do_lote)])
        self.assertEqual(resumo.sigilosos_motivos[str(do_lote)],
                         "o relatório completo do lote, na pasta dos sigilosos, não pôde ser "
                         "atualizado: está aberto em outro programa?; ele mesmo também está "
                         "aberto no Excel?")
        [(titulo, _frase)] = self.ctx.avisos
        self.assertEqual(titulo, "Arquivo de processo sigiloso no acervo")

    def test_completo_preso_com_o_relatorio_aberto_depois_de_mascarado_nao_avisa(self):
        """Achado R2 da oitava verificação: o completo preso desde o início e
        o relatorio.csv do lote aberto no Excel só DEPOIS de o fim do item de
        A o regravar mascarado (o número de A já saiu dele). A gravação do
        item de B passa ao "(atualizado)", e salvar_relatorio, que ainda o
        tinha entre os que o completo preso deixou com o número, o punha nos
        avisos ("ainda traz o número dele"), sem ser verdade. O relatório
        regravado mascarado sai dessa conta."""
        lote_x = self.tmp / "Acervo" / "Processos" / "Lote X"
        do_lote = lote_x / "_controle" / "relatorio.csv"
        atualizado = lote_x / "_controle" / "relatorio (atualizado).csv"
        completo = self.tmp / "Sigilosos" / "Lote X" / "_controle" / "relatorio.csv"
        self.lote([S], roteiro={S.formatado: ["ok_sigiloso"]}, destino=lote_x)
        self.lote([A], destino=lote_x)                   # A pública, no relatorio.csv
        aberto = []
        original = os.replace

        def preso(origem, destino, *a, **k):
            if Path(destino) == completo or (Path(destino) == do_lote and aberto):
                raise PermissionError(13, "O arquivo está sendo usado por outro processo",
                                      str(destino))
            mascarado = Path(destino) == do_lote \
                and A.formatado not in Path(origem).read_bytes().decode("utf-8-sig")
            original(origem, destino, *a, **k)
            if mascarado:
                aberto.append(True)      # aberto no Excel logo depois de regravado
        self.ctx = ContextoComEventos()
        with mock.patch.object(motor.os, "replace", preso):
            resumo = self.lote([A, A2], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]},
                               destino=lote_x)
        self.assertEqual([(r.grau, r.sigiloso) for r in resumo.itens],
                         [("2g", True), ("2g", False)])
        self.assertTrue(aberto, "o relatorio.csv regravado mascarado no fim do item de A")
        self.assertTrue(atualizado.is_file(), "a gravação do item de B foi ao \"(atualizado)\"")
        for arquivo in (do_lote, atualizado):
            self.assertNotIn(A.formatado, arquivo.read_bytes().decode("utf-8-sig"), arquivo)
        self.assertEqual(resumo.sigilosos_avisos, [])
        self.assertEqual(self.ctx.avisos, [])

    def test_marcado_por_engano_e_desfeito_pelo_manual_continua_publico(self):
        """Achados W8 e W10: desde a correção V3, a linha "(processo sigiloso)"
        do relatório do acervo vale "sim" mesmo que o completo diga "não". O
        manual ("Se um processo foi marcado como sigiloso por engano") mandava
        trocar o "sim" só no completo: a rodada seguinte do lote marcava A de
        novo e a outra levava os autos de volta à pasta dos sigilosos. O passo
        5 manda agora trocar também a linha mascarada do acervo pela de A,
        copiada do completo; seguido à letra, A continua pública."""
        import re

        manual = (Path(__file__).resolve().parents[1] / "docs" / "MANUAL.md") \
            .read_text(encoding="utf-8")
        secao = manual.split("### Se um processo foi marcado como sigiloso por engano", 1)[1]
        passo5 = re.sub(r"\s+", " ", secao.split("\n5. ", 1)[1].split("\n6. ", 1)[0])
        self.assertIn("`Acervo\\Processos\\<nome do lote>\\_controle\\relatorio.csv`", passo5)
        self.assertIn("“(processo sigiloso)”", passo5)
        self.assertIn("copiada do relatório completo", passo5)

        r = self.lote([A], roteiro={A.formatado: ["ok_sigiloso"]}).itens[0]
        self.assertTrue(r.sigiloso)
        sig = self.tmp / "Sigilosos" / self.destino.name
        completo = sig / "_controle" / "relatorio.csv"
        do_acervo = self.destino / "_controle" / "relatorio.csv"

        def gravar(arquivo, linhas):                # como o Excel, no mesmo formato
            with open(arquivo, "w", encoding="utf-8-sig", newline="") as f:
                escritor = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";",
                                          lineterminator="\r\n")
                escritor.writeheader()
                escritor.writerows(linhas)

        # o manual, à letra: 4. o download.sigilo.json fora
        sigilo.arquivo_do_download().unlink()
        # 5. "não" na linha de A do completo; no relatório do acervo, a linha
        # mascarada de mesma ordem trocada pela de A copiada do completo
        linhas = self.relatorio(completo)
        dela = next(l for l in linhas if l["processo"] == A.formatado)
        dela["sigiloso"] = "não"
        gravar(completo, linhas)
        gravar(do_acervo, [dela if (l["processo"], l["ordem"]) ==
                           (motor.MASCARA_SIGILOSO, dela["ordem"]) else l
                           for l in self.relatorio(do_acervo)])
        # 6. os autos (e o que mais tiver o número dele) de volta ao lote
        for pasta in (sig, sig / "_controle"):
            for p in list(pasta.glob(f"{A.nome_arquivo}*")):
                p.replace(self.destino / p.relative_to(sig))

        # a rodada seguinte do lote, com outro processo, não o marca de novo...
        self.lote([A2])
        for arquivo in (do_acervo, completo):
            self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio(arquivo)],
                             [(A.formatado, "não"), (A2.formatado, "não")], arquivo)
        # ... e a que o tem na relação não o leva de volta aos sigilosos
        r = self.lote([A]).itens[0]
        self.assertEqual((r.situacao, r.sigiloso, r.arquivo),
                         (modelos.JA_BAIXADO, False, str(self.destino / f"{A.nome_arquivo}.pdf")))
        self.assertTrue((self.destino / f"{A.nome_arquivo}.pdf").is_file())
        self.assertFalse((sig / f"{A.nome_arquivo}.pdf").exists())
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio()],
                         [(A.formatado, "não"), (A2.formatado, "não")])
        self.assertNotIn(A.nome_arquivo, sigilo.apuradas_no_download())
        self.assertNotIn(A.nome_arquivo, sigilo.chaves_sigilosas(self.tmp / "Sigilosos",
                                                                 self.tmp / "Acervo"))


# ================================================================== sigilo
class TestSigiloNosDoisGraus(BaseGrau):
    def test_s_sigiloso_no_2o_grau_tira_os_autos_e_os_textos_dos_dois_graus(self):
        acervo = self.tmp / "Acervo"
        outro = acervo / "Processos" / "Lote antigo"
        (outro / "_controle").mkdir(parents=True)
        (outro / f"{S.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(2))
        (outro / "_controle" / f"{S.nome_arquivo}_capa.txt").write_text("capa", "utf-8")
        # o PDF do incidente fora do 1º nível dos lotes (numa subpasta)
        sub = outro / "subpasta"
        sub.mkdir()
        (sub / f"{S.nome_arquivo}-01.pdf").write_bytes(apoio.pdf_bytes(1))
        textos = acervo / "_ia" / "texto"
        textos.mkdir(parents=True)
        for nome in (S.nome_arquivo, f"{S.nome_arquivo} (2G)", f"{S.nome_arquivo}-01",
                     f"{S.nome_arquivo}-50000 (2G)", A.nome_arquivo):
            (textos / f"{nome}.txt").write_text("texto", encoding="utf-8")

        r = self.lote([S], grau="2g", roteiro={S.formatado: ["ok_sigiloso"]}).itens[0]
        self.assertTrue(r.sigiloso)
        sig = self.tmp / "Sigilosos"
        self.assertTrue((sig / self.destino.name / f"{S.nome_arquivo} (2G).pdf").is_file())
        self.assertFalse((self.destino / f"{S.nome_arquivo} (2G).pdf").exists())
        # o PDF do 1º grau, de outro lote do acervo, sai também, com a capa
        self.assertFalse((outro / f"{S.nome_arquivo}.pdf").exists())
        self.assertTrue((sig / "Lote antigo" / f"{S.nome_arquivo}.pdf").is_file())
        self.assertTrue((sig / "Lote antigo" / "_controle" / f"{S.nome_arquivo}_capa.txt")
                        .is_file())
        self.assertFalse((sub / f"{S.nome_arquivo}-01.pdf").exists())
        # os textos dos dois graus e dos incidentes saem; o de outro processo fica
        self.assertEqual(sorted(p.name for p in textos.iterdir()), [f"{A.nome_arquivo}.txt"])
        # e o próximo download de S, no 1º grau, já nasce sigiloso
        r = self.lote([S], grau="1g", destino=acervo / "Processos" / "Novo").itens[0]
        self.assertTrue(r.sigiloso)
        self.assertTrue((sig / "Novo" / f"{S.nome_arquivo}.pdf").is_file())

    def test_retirar_do_acervo_leva_os_dois_graus_e_o_recurso_interno(self):
        acervo = self.tmp / "Acervo"
        lote = acervo / "Processos" / "Lote E"
        controle = lote / "_controle"
        controle.mkdir(parents=True)
        nomes = (P.nome_arquivo, f"{P.nome_arquivo} (2G)", f"{P.nome_arquivo}-50000 (2G)")
        for nome in nomes:
            (lote / f"{nome}.pdf").write_bytes(apoio.pdf_bytes(1))
            (controle / f"{nome}_capa.json").write_text("{}", encoding="utf-8")
        (lote / f"{A.nome_arquivo} (2G).pdf").write_bytes(apoio.pdf_bytes(1))
        self.assertEqual(motor._incidentes_no_acervo(P.nome_arquivo, [lote], None),
                         [E.nome_arquivo])
        ret = motor.retirar_do_acervo(None, P, raiz_sigilosos=self.tmp / "Sigilosos",
                                      lotes=[lote], acervo=acervo)
        self.assertEqual(sorted(p.name for p in ret.autos),
                         sorted(f"{nome}.pdf" for nome in nomes))
        destino = self.tmp / "Sigilosos" / "Lote E"
        for nome in nomes:
            self.assertTrue((destino / f"{nome}.pdf").is_file(), nome)
            self.assertTrue((destino / "_controle" / f"{nome}_capa.json").is_file(), nome)
        self.assertEqual([p.name for p in lote.glob("*.pdf")], [f"{A.nome_arquivo} (2G).pdf"])
        # pelo embargo (o incidente), o principal fica
        ret = motor.retirar_do_acervo(None, E, raiz_sigilosos=self.tmp / "Sigilosos",
                                      lotes=[lote], acervo=acervo)
        self.assertEqual(ret.autos, {})

    def test_apagar_texto_da_ia_sem_lote_nenhum(self):
        acervo = self.tmp / "Acervo"
        textos = acervo / "_ia" / "texto"
        textos.mkdir(parents=True)
        for nome in (f"{P.nome_arquivo}-50000 (2G)", f"{P.nome_arquivo}-01", P.nome_arquivo,
                     A.nome_arquivo):
            (textos / f"{nome}.txt").write_text("t", encoding="utf-8")
        motor._apagar_texto_da_ia(acervo, P.nome_arquivo)
        self.assertEqual(sorted(p.name for p in textos.iterdir()), [f"{A.nome_arquivo}.txt"])
        # o do incidente só leva o dele
        (textos / f"{P.nome_arquivo}.txt").write_text("t", encoding="utf-8")
        (textos / f"{P.nome_arquivo}-01.txt").write_text("t", encoding="utf-8")
        motor._apagar_texto_da_ia(acervo, f"{P.nome_arquivo}-01")
        self.assertEqual(sorted(p.name for p in textos.iterdir()),
                         sorted([f"{A.nome_arquivo}.txt", f"{P.nome_arquivo}.txt"]))

    def test_capa_do_2o_grau_com_segredo_vale_para_o_1o(self):
        controle = self.destino / "_controle"
        controle.mkdir(parents=True)
        (controle / f"{A.nome_arquivo} (2G)_capa.txt").write_text(
            "Processo ... SEGREDO DE JUSTIÇA", encoding="utf-8")
        r = self.lote([A], grau="1g").itens[0]
        self.assertTrue(r.sigiloso)

    def test_originario_herda_o_sigilo_da_origem(self):
        capa = {"formato": "helestron.capa/2", "grau": "2g", "capa": {"classe": "Habeas Corpus"},
                "numeros_1a_instancia": [{"numero": A.formatado, "foro": "x"}]}
        # A é sigiloso pela pasta dos sigilosos (de outro lote)
        sig = self.tmp / "Sigilosos" / "Outro lote"
        sig.mkdir(parents=True)
        (sig / f"{A.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(1))
        r = self.lote([H], grau="1g", capas={H.formatado: capa}).itens[0]
        self.assertEqual((r.situacao, r.grau), (modelos.OK, "2g"))
        self.assertTrue(r.sigiloso)
        self.assertIn(f"tratado como sigiloso: o processo de origem {A.formatado} é sigiloso",
                      r.detalhe)
        self.assertTrue((self.tmp / "Sigilosos" / self.destino.name /
                         f"{H.nome_arquivo} (2G).pdf").is_file())
        self.assertFalse((self.destino / f"{H.nome_arquivo} (2G).pdf").exists())
        self.assertTrue(sigilo.motivo_do_download(H), "vai para a regra única")

    def test_origem_publica_deixa_o_originario_publico(self):
        capa = {"numeros_1a_instancia": [{"numero": A.formatado}, {"numero": ""}]}
        r = self.lote([H], grau="2g", capas={H.formatado: capa}).itens[0]
        self.assertFalse(r.sigiloso)
        self.assertTrue((self.destino / f"{H.nome_arquivo} (2G).pdf").is_file())
        self.assertFalse(sigilo.motivo_do_download(H))

    def test_originario_baixado_antes_de_a_origem_se_apurar_sigilosa(self):
        """Achado V7: o HC vem antes da ação de origem A na relação do 2º
        grau e é baixado público (A ainda não se sabia sigilosa); A então se
        apura sigilosa pelo portal. O HC herda o sigilo na hora, pela capa
        guardada: o item diz que é sigiloso e onde o PDF está, o relatório o
        mascara e o registro do download o guarda - não fica para o preparo
        do fim do lote, que levaria o PDF e deixaria o JSON dizendo público."""
        capa = {"formato": "helestron.capa/2", "grau": "2g", "capa": {"classe": "Habeas Corpus"},
                "numeros_1a_instancia": [{"numero": A.formatado, "foro": "x"}]}
        resumo = self.lote([H, A], grau="2g", capas={H.formatado: capa},
                           roteiro={A.formatado: ["ok_sigiloso"]})
        h, a = resumo.itens
        self.assertEqual((a.situacao, a.sigiloso), (modelos.OK, True))
        sig = self.tmp / "Sigilosos" / self.destino.name
        pdf = sig / f"{H.nome_arquivo} (2G).pdf"
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertTrue(pdf.is_file())
        self.assertTrue((sig / "_controle" / f"{H.nome_arquivo} (2G)_capa.json").is_file())
        self.assertEqual((h.situacao, h.sigiloso, h.arquivo), (modelos.OK, True, str(pdf)))
        self.assertIn(f"tratado como sigiloso: o processo de origem {A.formatado} é sigiloso",
                      h.detalhe)
        self.assertIn("levado agora para a pasta de sigilosos", h.detalhe)
        self.assertEqual((processo_json(h)["sigiloso"], processo_json(h)["pdf"]),
                         (True, str(pdf)))
        self.assertEqual(len(resumo.sigilosos), 2)
        self.assertEqual(resumo.sigilosos_no_acervo, [])
        self.assertTrue(sigilo.motivo_do_download(H), "vai para a regra única")
        self.assertEqual(self.ctx.itens.count((H.formatado, modelos.OK)), 2,
                         "o item do HC é publicado de novo, já sigiloso")
        self.assertNotIn(H.nome_arquivo, (self.destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))
        self.assertEqual([(l["processo"], l["sigiloso"], l["grau"]) for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, "sim", "2g"),
                          (motor.MASCARA_SIGILOSO, "sim", "2g")])
        self.assertEqual([(l["processo"], l["sigiloso"], l["arquivo"])
                          for l in self.relatorio(sig / "_controle" / "relatorio.csv")],
                         [(H.formatado, "sim",
                           f"{H.nome_arquivo} (2G).pdf (na pasta de sigilosos)"),
                          (A.formatado, "sim",
                           f"{A.nome_arquivo} (2G).pdf (na pasta de sigilosos)")])

    CAPA_DO_HC = {"formato": "helestron.capa/2", "grau": "2g",
                  "capa": {"classe": "Habeas Corpus"},
                  "numeros_1a_instancia": [{"numero": A.formatado, "foro": "x"}]}

    def originario_ja_baixado_herda(self, destino: Path) -> None:
        """Achado W5: o HC baixado público numa rodada; a ação de origem A se
        apura sigilosa noutra (sem o HC na relação); o HC pedido de novo já
        está na pasta (JA_BAIXADO) e herda o sigilo pela capa guardada, como
        herdaria baixado de novo."""
        self.lote([H], grau="2g", capas={H.formatado: self.CAPA_DO_HC}, destino=destino)
        self.lote([A], grau="2g", roteiro={A.formatado: ["ok_sigiloso"]}, destino=destino)
        self.assertTrue((destino / f"{H.nome_arquivo} (2G).pdf").is_file())
        h = self.lote([H], grau="2g", capas={H.formatado: self.CAPA_DO_HC},
                      destino=destino).itens[0]
        sig = motor.pasta_sigilosos_do_lote(self.tmp / "Sigilosos", destino,
                                            self.cfg.pasta_processos)
        pdf = sig / f"{H.nome_arquivo} (2G).pdf"
        self.assertEqual((h.situacao, h.sigiloso, h.arquivo), (modelos.JA_BAIXADO, True, str(pdf)))
        self.assertTrue(pdf.is_file())
        self.assertEqual(list(destino.glob("*.pdf")), [])
        self.assertIn(f"tratado como sigiloso: o processo de origem {A.formatado} é sigiloso",
                      h.detalhe)
        self.assertEqual(processo_json(h)["sigiloso"], True)
        self.assertTrue(sigilo.motivo_do_download(H), "vai para a regra única")
        self.assertNotIn(H.nome_arquivo, (destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))

    def test_originario_ja_baixado_herda_a_origem_que_se_apurou_depois(self):
        self.originario_ja_baixado_herda(self.destino)

    def test_originario_ja_baixado_herda_tambem_no_lote_fora_do_acervo(self):
        # o fluxo da skill: o preparo do fim do lote não alcança esta pasta
        self.originario_ja_baixado_herda(self.tmp / "Trabalho" / "Lotes" / "Semana 42")

    def originario_herda_com_a_separacao_desligada(self, acao: str) -> None:
        """Achados W6 e W11: com a separação dos sigilosos desligada, o HC
        baixado antes da ação de origem A na relação herda o sigilo quando A
        se apura sigilosa, como na ordem [A, H]: o item diz que é sigiloso, a
        linha dele diz "sim" e o registro do download o guarda; os autos
        ficam no lote (a separação está desligada)."""
        resumo = self.lote([H, A], grau="2g", capas={H.formatado: self.CAPA_DO_HC},
                           roteiro={A.formatado: [acao]}, separar_sigilosos=False)
        h, a = resumo.itens
        self.assertTrue(a.sigiloso)
        pdf = self.destino / f"{H.nome_arquivo} (2G).pdf"
        self.assertEqual((h.situacao, h.sigiloso, h.arquivo), (modelos.OK, True, str(pdf)))
        self.assertTrue(pdf.is_file(), "a separação está desligada: fica no lote")
        self.assertEqual(h.detalhe, f"tratado como sigiloso: o processo de origem {A.formatado} "
                                    "é sigiloso")
        self.assertEqual(processo_json(h)["sigiloso"], True)
        self.assertEqual(len(resumo.sigilosos), 2)
        self.assertEqual(self.ctx.itens.count((H.formatado, modelos.OK)), 2,
                         "o item do HC é publicado de novo, já sigiloso")
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio()],
                         [(H.formatado, "sim"), (A.formatado, "sim")])
        self.assertTrue(sigilo.motivo_do_download(H), "vai para a regra única")
        self.assertFalse((self.tmp / "Sigilosos").exists())

    def test_originario_herda_com_a_separacao_desligada(self):
        self.originario_herda_com_a_separacao_desligada("ok_sigiloso")

    def test_originario_herda_da_origem_sem_senha_com_a_separacao_desligada(self):
        # A sem a senha (SIGILOSO_SEM_SENHA): sigilosa, sem PDF novo
        self.originario_herda_com_a_separacao_desligada("sigiloso_sem_senha")

    def test_separacao_desligada_e_o_registro_do_originario_que_falha(self):
        """W6, o lado seguro: com a separação desligada, o HC que herda o
        sigilo e não pode ir para o registro do download vai para a pasta de
        sigilosos (como o próprio processo, _lembrar_sigilo), com o porquê."""
        original = sigilo.lembrar_do_download

        def lembrar(processos, *a, **k):
            if any(cnj.chave(p) == cnj.chave(H) for p in processos):
                return False
            return original(processos, *a, **k)
        with mock.patch.object(sigilo, "lembrar_do_download", lembrar):
            h, a = self.lote([H, A], grau="2g", capas={H.formatado: self.CAPA_DO_HC},
                             roteiro={A.formatado: ["ok_sigiloso"]},
                             separar_sigilosos=False).itens
        pdf = self.tmp / "Sigilosos" / self.destino.name / f"{H.nome_arquivo} (2G).pdf"
        self.assertEqual((h.sigiloso, h.arquivo), (True, str(pdf)))
        self.assertTrue(pdf.is_file())
        self.assertIn(motor.SEM_REGISTRO_DO_SIGILO, h.detalhe)
        self.assertTrue((self.destino / f"{A.nome_arquivo} (2G).pdf").is_file(),
                        "A foi para o registro: fica no lote")

    def test_recurso_interno_em_segredo_apura_o_principal_desta_rodada(self):
        """Achado W4: P baixado público numa rodada; depois a relação [P, E]
        (E = P/50000): P sai JA_BAIXADO e a consulta de E abre a página de P
        em segredo de justiça. O sigilo é de P: o item dele passa a dizê-lo,
        os autos vão para a pasta de sigilosos, a linha dele é mascarada e o
        registro do download o guarda."""
        self.lote([P], grau="2g")
        resumo = self.lote([P, E], grau="2g", portal=PortalDoSegredo)
        p, e = resumo.itens
        self.assertEqual((e.situacao, e.sigiloso), (modelos.NAO_SUPORTADO, True))
        sig = self.tmp / "Sigilosos" / self.destino.name
        pdf = sig / f"{P.nome_arquivo} (2G).pdf"
        self.assertEqual((p.situacao, p.sigiloso, p.arquivo), (modelos.JA_BAIXADO, True, str(pdf)))
        self.assertTrue(pdf.is_file())
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertIn(f"tratado como sigiloso: a consulta do recurso interno {E.formatado} abriu "
                      "a página dele em segredo de justiça", p.detalhe)
        self.assertIn("levado agora para a pasta de sigilosos", p.detalhe)
        self.assertEqual((processo_json(p)["sigiloso"], processo_json(p)["pdf"]), (True, str(pdf)))
        self.assertEqual(self.ctx.itens.count((P.formatado, modelos.JA_BAIXADO)), 2,
                         "o item de P é publicado de novo, já sigiloso")
        self.assertTrue(sigilo.motivo_do_download(P), "vai para a regra única")
        self.assertNotIn(P.nome_arquivo, (self.destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))
        self.assertEqual([(l["processo"], l["sigiloso"])
                          for l in self.relatorio(sig / "_controle" / "relatorio.csv")],
                         [(P.formatado, "sim"), (E.formatado, "sim")])

    def test_recurso_interno_em_segredo_tira_o_principal_de_todo_o_acervo(self):
        """Achado W1: P baixado público no 1º grau neste lote e no 2º grau
        noutro; depois só E (= P/50000), cuja consulta abre a página de P em
        segredo de justiça. Os autos de P, nos dois graus e nos dois lotes,
        saem do acervo; a linha de P é mascarada; o registro do download
        guarda P e E; o detalhe de E diz o que saiu; e P, pedido depois,
        nasce sigiloso."""
        outro = self.tmp / "Acervo" / "Processos" / "Outro"
        self.lote([P], grau="1g")
        self.lote([P], grau="2g", destino=outro)
        e = self.lote([E], grau="2g", portal=PortalDoSegredo).itens[0]
        self.assertEqual((e.situacao, e.sigiloso), (modelos.NAO_SUPORTADO, True))
        sig = self.tmp / "Sigilosos"
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertEqual(list(outro.glob("*.pdf")), [])
        self.assertTrue((sig / self.destino.name / f"{P.nome_arquivo}.pdf").is_file())
        self.assertTrue((sig / "Outro" / f"{P.nome_arquivo} (2G).pdf").is_file())
        self.assertIn(f"o processo principal {P.formatado} passa a ser tratado como sigiloso: "
                      "2 cópias dos autos dele levadas para a pasta de sigilosos", e.detalhe)
        self.assertTrue(sigilo.motivo_do_download(P) and sigilo.motivo_do_download(E))
        self.assertTrue(sigilo.motivo(self.cfg, P))
        self.assertEqual([(l["processo"], l["situacao"], l["sigiloso"], l["grau"])
                          for l in self.relatorio()],
                         [(motor.MASCARA_SIGILOSO, modelos.OK, "sim", "1g"),
                          (motor.MASCARA_SIGILOSO, modelos.NAO_SUPORTADO, "sim", "2g")])
        self.assertEqual([(l["processo"], l["sigiloso"])
                          for l in self.relatorio(outro / "_controle" / "relatorio.csv")],
                         [(motor.MASCARA_SIGILOSO, "sim")])
        self.assertEqual([(l["processo"], l["sigiloso"], l["arquivo"])
                          for l in self.relatorio(sig / self.destino.name / "_controle" /
                                                  "relatorio.csv")],
                         [(P.formatado, "sim", f"{P.nome_arquivo}.pdf (na pasta de sigilosos)"),
                          (E.formatado, "sim", "")])
        # P pedido depois, neste lote, já nasce sigiloso
        r = self.lote([P], grau="2g").itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.OK, True))
        self.assertTrue((sig / self.destino.name / f"{P.nome_arquivo} (2G).pdf").is_file())

    PORQUE_DE_P = (f"tratado como sigiloso: a consulta do recurso interno {E.formatado} abriu "
                   "a página dele em segredo de justiça")

    def test_principal_pedido_depois_do_recurso_interno_diz_o_porque(self):
        """Achado X1: num lote do 1º grau [E, P], E vai ao 2º grau e a
        consulta dele abre a página de P em segredo; P, público no 1º grau,
        é baixado depois na mesma rodada. Ele sai sigiloso com o porquê de
        verdade - não "assim constava de download anterior", que não houve."""
        e, p = self.lote([E, P], grau="1g", portal=PortalDoSegredo).itens
        self.assertEqual((e.grau, e.situacao, e.sigiloso), ("2g", modelos.NAO_SUPORTADO, True))
        self.assertEqual((p.grau, p.situacao, p.sigiloso), ("1g", modelos.OK, True))
        self.assertIn(self.PORQUE_DE_P, p.detalhe)
        self.assertNotIn(motor.SIGILO_ANTERIOR, p.detalhe)
        pdf = self.tmp / "Sigilosos" / self.destino.name / f"{P.nome_arquivo}.pdf"
        self.assertEqual(p.arquivo, str(pdf))
        self.assertTrue(pdf.is_file())
        self.assertNotIn(P.nome_arquivo, (self.destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))

    def test_incidente_do_principal_pedido_depois_do_recurso_interno_diz_o_porque(self):
        """Achados Y2 e Y7: num lote do 1º grau [E, P/01], a consulta de E
        abre a página de P em segredo; P/01, público no 1º grau e pedido
        depois na mesma rodada, herda o sigilo de P com o porquê de verdade -
        não "assim constava de download anterior", que não houve. O registro
        do download fica como antes (P, P/01 e E)."""
        P01 = cnj.ler(f"{P.formatado}/01")
        e, p01 = self.lote([E, P01], grau="1g", portal=PortalDoSegredo).itens
        self.assertEqual((e.grau, e.situacao, e.sigiloso), ("2g", modelos.NAO_SUPORTADO, True))
        self.assertEqual((p01.grau, p01.situacao, p01.sigiloso), ("1g", modelos.OK, True))
        self.assertIn(f"tratado como sigiloso: a consulta do recurso interno {E.formatado} abriu "
                      f"a página do processo principal {P.formatado} em segredo de justiça",
                      p01.detalhe)
        self.assertNotIn(motor.SIGILO_ANTERIOR, p01.detalhe)
        pdf = self.tmp / "Sigilosos" / self.destino.name / f"{P01.nome_arquivo}.pdf"
        self.assertEqual(p01.arquivo, str(pdf))
        self.assertTrue(pdf.is_file())
        self.assertEqual(set(sigilo.apuradas_no_download()),
                         {P.nome_arquivo, P01.nome_arquivo, E.nome_arquivo})

    def principal_apurado_sem_o_registro(self, separar: bool) -> None:
        """Achado Y4: P apurado só pela consulta de E (P/50000), sem linha nem
        autos dele - a linha "sim" é a de E. Sem o registro do download (o
        passo 4 do manual, para desfazer a marcação de OUTRO processo), P
        continua sigiloso: o recurso interno do 2º grau sigiloso torna
        sigiloso o principal. Na regra única, pela linha de E no relatório do
        lote - o do acervo, com a separação desligada; o completo, na pasta
        de sigilosos, com ela ligada (a do acervo sai mascarada) -, que o
        devolve ao registro; no motor, na rodada seguinte do lote, pelo
        relatório do lote ou pelo completo."""
        e = self.lote([E], grau="2g", portal=PortalDoSegredo,
                      separar_sigilosos=separar).itens[0]
        self.assertTrue(e.sigiloso)
        relatorios = [self.relatorio()]
        if separar:
            relatorios.append(self.relatorio(self.tmp / "Sigilosos" / self.destino.name /
                                             "_controle" / "relatorio.csv"))
            self.assertNotIn(E.formatado, [l["processo"] for l in relatorios[0]], "mascarada")
        for linhas in relatorios:
            self.assertNotIn(P.formatado, [l["processo"] for l in linhas], "P não tem linha")
        sigilo.arquivo_do_download().unlink()
        chaves = sigilo.chaves_sigilosas(self.tmp / "Sigilosos", raiz=self.tmp / "Acervo")
        self.assertIn(P.nome_arquivo, chaves)
        self.assertIn(P.nome_arquivo, set(sigilo.apuradas_no_download()),
                      "a linha de E devolve P ao registro")
        sigilo.arquivo_do_download().unlink()            # o motor, sem ele
        p = self.lote([P], grau="1g", separar_sigilosos=separar).itens[0]
        self.assertEqual((p.situacao, p.sigiloso), (modelos.OK, True))
        self.assertIn(f"tratado como sigiloso: {motor.SIGILO_ANTERIOR}", p.detalhe)
        pasta = self.tmp / "Sigilosos" / self.destino.name if separar else self.destino
        self.assertEqual(p.arquivo, str(pasta / f"{P.nome_arquivo}.pdf"))
        self.assertTrue(sigilo.motivo_do_download(P), "volta ao registro")

    def test_principal_apurado_pelo_recurso_continua_sigiloso_sem_o_registro(self):
        self.principal_apurado_sem_o_registro(separar=False)

    def test_principal_apurado_continua_sigiloso_sem_o_registro_e_com_a_separacao(self):
        self.principal_apurado_sem_o_registro(separar=True)

    def test_incidente_comum_sigiloso_nao_torna_o_principal_sigiloso(self):
        """Achado Y4, o controle: o incidente comum do 1º grau (P/01, o
        cumprimento de sentença) sigiloso continua sem tornar sigiloso o
        principal - na regra única e no motor (o 1º grau, como na 1.0.2)."""
        P01 = cnj.ler(f"{P.formatado}/01")
        r = self.lote([P01], grau="1g", roteiro={P01.formatado: ["ok_sigiloso"]},
                      separar_sigilosos=False).itens[0]
        self.assertTrue(r.sigiloso)
        sigilo.arquivo_do_download().unlink()
        chaves = sigilo.chaves_sigilosas(self.tmp / "Sigilosos", raiz=self.tmp / "Acervo")
        self.assertIn(P01.nome_arquivo, chaves)
        self.assertNotIn(P.nome_arquivo, chaves)
        sigilo.arquivo_do_download().unlink()
        p = self.lote([P], grau="1g", separar_sigilosos=False).itens[0]
        self.assertEqual((p.situacao, p.sigiloso), (modelos.OK, False))

    def test_recurso_interno_sigiloso_pela_propria_pagina_registra_o_principal(self):
        """Achado Z2 da sexta verificação: E (= P/50000) sigiloso pela PRÓPRIA
        página (a opção exata existe na consulta e a página dela pede a
        senha: o e-SAJ põe em sigilosos_apurados só E, não P). A regra única
        dá P como sigiloso, e o registro do download também: senão, as
        consultas de um número só (o download noutro lote, a transcrição) o
        davam como público."""
        lote1, lote2 = (self.tmp / "Acervo" / "Processos" / f"Lote {i}" for i in (1, 2))
        e = self.lote([E], grau="2g", destino=lote1,
                      roteiro={E.formatado: ["sigiloso_sem_senha"]}).itens[0]
        self.assertEqual((e.situacao, e.sigiloso), (modelos.SIGILOSO_SEM_SENHA, True))
        self.assertFalse(getattr(apoio.PortalFalso.todos[-1], "sigilosos_apurados", None))
        self.assertLessEqual({E.nome_arquivo, P.nome_arquivo}, set(sigilo.apuradas_no_download()))
        self.assertEqual(sigilo.motivo(self.cfg, P), sigilo.MOTIVO_DOWNLOAD)
        self.assertNotIn("processo principal", e.detalhe, "nada dele havia no acervo")
        # P noutro lote, com a página do 1º grau sem o selo
        p = self.lote([P], grau="1g", destino=lote2).itens[0]
        pdf = self.tmp / "Sigilosos" / lote2.name / f"{P.nome_arquivo}.pdf"
        self.assertEqual((p.situacao, p.sigiloso, p.arquivo), (modelos.OK, True, str(pdf)))
        self.assertTrue(pdf.is_file())
        self.assertIn(f"tratado como sigiloso: {sigilo.MOTIVO_DOWNLOAD}", p.detalhe)
        self.assertEqual(list(lote2.glob("*.pdf")), [])
        self.assertEqual(processo_json(p)["sigiloso"], True)

    def principal_sem_o_registro_fora_do_acervo(self, acao: str) -> None:
        """Achado Q4 da sétima verificação: E (= P/50000) sigiloso pela
        própria página no Lote Z ('acao': com a senha, os autos na pasta dos
        sigilosos; sem ela, só a linha do relatório completo), e o registro
        do download perdido (as configurações apagadas na desinstalação, o
        acervo levado a outro computador). A regra única dava P como
        sigiloso, mas o download fora do acervo (a pasta de trabalho da
        skill), a transcrição e a tela da audiência o davam como público:
        as consultas de um número só não derivavam o principal do recurso
        interno. Agora fazem a mesma conta (sigilo._como_contem)."""
        from helestron.servidor import audiencia
        from helestron.transcricao import documento

        lote_z = self.tmp / "Acervo" / "Processos" / "Lote Z"
        e = self.lote([E], grau="2g", destino=lote_z, roteiro={E.formatado: [acao]}).itens[0]
        self.assertTrue(e.sigiloso)
        sigilo.arquivo_do_download().unlink()
        self.assertEqual(sigilo.motivo(self.cfg, P), sigilo.MOTIVO_RECURSO)
        sigilosos = self.tmp / "Sigilosos"
        self.assertEqual(documento.pasta_das_transcricoes(self.cfg, P),
                         sigilosos / "Transcricoes")
        app = mock.Mock(cfg=self.cfg)
        app.pauta_ou_none.return_value = None
        self.assertEqual(audiencia.sigilo_conhecido(app, P), audiencia.MOTIVO_RECURSO)
        self.assertEqual(audiencia.sigilo_conhecido(app, cnj.ler(f"{P.formatado}/01")),
                         audiencia.MOTIVO_RECURSO_PRINCIPAL)
        trabalho = self.tmp / "Trabalho" / "Lotes" / "Semana 41"
        p = self.lote([P], grau="1g", destino=trabalho).itens[0]   # a página sem o selo
        self.assertEqual((p.situacao, p.sigiloso), (modelos.OK, True))
        self.assertIn(f"tratado como sigiloso: {sigilo.MOTIVO_RECURSO}", p.detalhe)
        self.assertTrue(motor._dentro(p.arquivo, sigilosos) and Path(p.arquivo).is_file())
        self.assertEqual(list(trabalho.glob("*.pdf")), [])
        self.assertEqual((processo_json(p)["sigiloso"], processo_json(p)["pdf"]),
                         (True, p.arquivo))

    def test_principal_do_recurso_com_a_senha_sem_o_registro_fora_do_acervo(self):
        self.principal_sem_o_registro_fora_do_acervo("ok_sigiloso")

    def test_principal_do_recurso_sem_a_senha_sem_o_registro_fora_do_acervo(self):
        self.principal_sem_o_registro_fora_do_acervo("sigiloso_sem_senha")

    def recurso_de_novo_sem_pdf_novo(self, situacao: str, portal=None, **opcoes) -> None:
        """Achado Q1 da sétima verificação: E (= P/50000) baixado público e,
        de novo no mesmo lote, sigiloso sem PDF novo (a página dele pede a
        senha, ou o download falhou com E apurado). A retirada do principal,
        que leva junto os autos dos incidentes dele, levava a cópia antiga do
        PRÓPRIO E, contada como "dos incidentes dele"; o item de E ficava sem
        arquivo (o JSON com o pdf vazio, o completo sem a coluna arquivo),
        embora o PDF estivesse na pasta dos sigilosos. Agora, como na 678f6fe,
        o item aponta o PDF dele onde ele foi parar."""
        self.lote([E], grau="2g")
        e = self.lote([E], grau="2g", portal=portal, **opcoes).itens[0]
        pdf = self.tmp / "Sigilosos" / self.destino.name / f"{autos(E, '2g')}.pdf"
        self.assertEqual((e.situacao, e.sigiloso, e.arquivo), (situacao, True, str(pdf)))
        self.assertTrue(pdf.is_file())
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertIn("levado agora para a pasta de sigilosos", e.detalhe)
        self.assertNotIn("incidentes dele", e.detalhe)
        self.assertNotIn("processo principal", e.detalhe, "nada de P havia no acervo")
        self.assertEqual((processo_json(e)["sigiloso"], processo_json(e)["pdf"]),
                         (True, str(pdf)))
        completo = self.tmp / "Sigilosos" / self.destino.name / "_controle" / "relatorio.csv"
        self.assertEqual([(l["processo"], l["arquivo"]) for l in self.relatorio(completo)],
                         [(E.formatado, pdf.name)])
        self.assertLessEqual({P.nome_arquivo, E.nome_arquivo}, set(sigilo.apuradas_no_download()))

    def test_recurso_de_novo_sem_a_senha_aponta_o_pdf_levado(self):
        self.recurso_de_novo_sem_pdf_novo(
            modelos.SIGILOSO_SEM_SENHA, roteiro={E.formatado: ["sigiloso_sem_senha"]},
            pular_baixados=False)

    def test_recurso_rebaixado_sem_a_senha_aponta_o_pdf_levado(self):
        self.recurso_de_novo_sem_pdf_novo(
            modelos.SIGILOSO_SEM_SENHA, roteiro={E.formatado: ["sigiloso_sem_senha"]},
            rebaixar_incompletos=True)

    def test_recurso_rebaixado_com_erro_apurado_aponta_o_pdf_levado(self):
        self.recurso_de_novo_sem_pdf_novo(modelos.ERRO, portal=PortalErroApurado,
                                          rebaixar_incompletos=True, tentativas=1)

    def test_recurso_de_novo_conta_so_os_incidentes_do_principal(self):
        """Achado Q1: com P e P/01 públicos noutro lote, a retirada do principal
        pelo recurso interno conta os autos dele e os do incidente comum - não
        a cópia antiga do próprio recurso interno, que é do item dele."""
        P01 = cnj.ler(f"{P.formatado}/01")
        self.lote([P, P01], destino=self.tmp / "Acervo" / "Processos" / "Lote 1")
        self.lote([E], grau="2g")
        e = self.lote([E], grau="2g", roteiro={E.formatado: ["sigiloso_sem_senha"]},
                      pular_baixados=False).itens[0]
        self.assertIn(f"o processo principal {P.formatado} passa a ser tratado como sigiloso: "
                      "1 cópia dos autos dele e 1 dos incidentes dele levadas para a pasta de "
                      "sigilosos", e.detalhe)
        self.assertEqual(e.arquivo, str(self.tmp / "Sigilosos" / self.destino.name /
                                        f"{autos(E, '2g')}.pdf"))

    def recurso_de_novo_com_o_principal_no_lote(self, situacao: str, portal=None,
                                                **opcoes) -> None:
        """Achado R3 da oitava verificação: o Q1 com o principal P na mesma
        relação de E (P e E baixados públicos e, de novo no mesmo lote, E
        sigiloso). A retirada de P pelo item dele levava junto a cópia antiga
        de E sem dá-la ao item de E, que ficava sem arquivo (o JSON com o pdf
        vazio, o completo sem a coluna arquivo), embora o PDF estivesse na
        pasta dos sigilosos. Agora o item de E aponta o PDF dele onde ele foi
        parar, como sem P na relação."""
        self.lote([P, E])
        p, e = self.lote([P, E], portal=portal, **opcoes).itens
        sig = self.tmp / "Sigilosos" / self.destino.name
        pdf = sig / f"{autos(E, '2g')}.pdf"
        self.assertEqual((p.sigiloso, p.arquivo), (True, str(sig / f"{P.nome_arquivo}.pdf")))
        self.assertEqual((e.situacao, e.sigiloso, e.arquivo), (situacao, True, str(pdf)))
        self.assertTrue(pdf.is_file())
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertIn("levado agora para a pasta de sigilosos", e.detalhe)
        self.assertNotIn("incidentes dele", e.detalhe)
        self.assertEqual((processo_json(e)["sigiloso"], processo_json(e)["pdf"]),
                         (True, str(pdf)))
        completo = sig / "_controle" / "relatorio.csv"
        na_pasta = " (na pasta de sigilosos)" if situacao == modelos.OK else ""
        self.assertEqual([(l["processo"], l["arquivo"]) for l in self.relatorio(completo)],
                         [(P.formatado, f"{P.nome_arquivo}.pdf (na pasta de sigilosos)"),
                          (E.formatado, pdf.name + na_pasta)])

    def test_recurso_de_novo_sem_a_senha_com_o_principal_no_lote_aponta_o_pdf(self):
        self.recurso_de_novo_com_o_principal_no_lote(
            modelos.SIGILOSO_SEM_SENHA, roteiro={E.formatado: ["sigiloso_sem_senha"]},
            pular_baixados=False)

    def test_recurso_rebaixado_com_erro_e_o_principal_no_lote_aponta_o_pdf(self):
        self.recurso_de_novo_com_o_principal_no_lote(
            modelos.ERRO, portal=PortalErroApurado, rebaixar_incompletos=True, tentativas=1)

    def test_recurso_de_novo_sigiloso_com_o_principal_no_lote_aponta_o_pdf(self):
        self.recurso_de_novo_com_o_principal_no_lote(
            modelos.OK, roteiro={E.formatado: ["ok_sigiloso"]}, pular_baixados=False)

    PORQUE_DO_RECURSO = f"tratado como sigiloso: o recurso interno {E.formatado} é sigiloso"

    def test_principal_antes_do_recurso_interno_sigiloso_sai_do_acervo(self):
        """Achado Z2, no mesmo lote [P, E]: P, baixado público, sai do acervo
        quando E se mostra sigiloso pela própria página, com o porquê de
        verdade - não "a consulta do recurso interno abriu a página dele",
        que não houve."""
        p, e = self.lote([P, E], grau="2g", roteiro={E.formatado: ["sigiloso_sem_senha"]}).itens
        pdf = self.tmp / "Sigilosos" / self.destino.name / f"{P.nome_arquivo} (2G).pdf"
        self.assertEqual((p.situacao, p.sigiloso, p.arquivo), (modelos.OK, True, str(pdf)))
        self.assertTrue(pdf.is_file())
        self.assertIn(self.PORQUE_DO_RECURSO, p.detalhe)
        self.assertIn("levado agora para a pasta de sigilosos", p.detalhe)
        self.assertNotIn("abriu a página", p.detalhe)
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertEqual(processo_json(p)["sigiloso"], True)
        self.assertNotIn(P.nome_arquivo, (self.destino / "_controle" / "relatorio.csv")
                         .read_bytes().decode("utf-8-sig"))

    def test_principal_depois_do_recurso_interno_sigiloso_diz_o_porque(self):
        """Achado Z2, no mesmo lote [E, P, P/01]: P e o incidente dele, pedidos
        depois de E (sigiloso pela própria página), nascem sigilosos com o
        porquê de verdade."""
        P01 = cnj.ler(f"{P.formatado}/01")
        e, p, p01 = self.lote([E, P, P01], grau="1g",
                              roteiro={E.formatado: ["sigiloso_sem_senha"]}).itens
        self.assertEqual((e.grau, p.grau, p01.grau), ("2g", "1g", "1g"))
        self.assertEqual((p.situacao, p.sigiloso), (modelos.OK, True))
        self.assertIn(self.PORQUE_DO_RECURSO, p.detalhe)
        self.assertNotIn(motor.SIGILO_ANTERIOR, p.detalhe)
        self.assertEqual((p01.situacao, p01.sigiloso), (modelos.OK, True))
        self.assertIn(f"tratado como sigiloso: o recurso interno {E.formatado}, do processo "
                      f"principal {P.formatado}, é sigiloso", p01.detalhe)
        self.assertEqual(list(self.destino.glob("*.pdf")), [])

    def test_recurso_interno_que_herdou_do_principal_nao_acrescenta_nada(self):
        """Achado Z2: E baixado com P já sigiloso (pela pauta) herda o sigilo
        dele - e, mesmo com a página dele em segredo, não apura P de novo:
        sem detalhe novo, e P, que só a pauta marca, fora do registro do
        download (desfazer a marcação da pauta continua bastando)."""
        sigilo.lembrar_da_pauta([P])
        sigilo.esquecer_pauta()
        e = self.lote([E], grau="2g").itens[0]
        self.assertTrue(e.sigiloso)
        self.assertIn(f"tratado como sigiloso: {sigilo.MOTIVO_PAUTA_PRINCIPAL}", e.detalhe)
        self.assertNotIn("recurso interno", e.detalhe)
        e = self.lote([E], grau="2g", roteiro={E.formatado: ["sigiloso_sem_senha"]},
                      destino=self.tmp / "Acervo" / "Processos" / "Outro").itens[0]
        self.assertTrue(e.sigiloso)
        self.assertNotIn("processo principal", e.detalhe)
        self.assertNotIn("recurso interno", e.detalhe)
        self.assertEqual(set(sigilo.apuradas_no_download()), {E.nome_arquivo})

    def test_principal_dos_autos_do_recurso_interno_volta_ao_registro(self):
        """Achado Z2, a variante do registro afastado: E baixado com a senha
        (OK sigiloso, os autos na pasta dos sigilosos), o download.sigilo.json
        afastado (o passo 4 do manual, para desfazer a marcação de OUTRO
        processo) e a regra única aplicada (o passo 8, Preparar): P, que só os
        autos de E dão como sigiloso, volta ao registro."""
        e = self.lote([E], grau="2g", roteiro={E.formatado: ["ok_sigiloso"]}).itens[0]
        self.assertTrue(e.sigiloso)
        self.assertTrue((self.tmp / "Sigilosos" / self.destino.name /
                         f"{autos(E, '2g')}.pdf").is_file())
        sigilo.arquivo_do_download().unlink()
        chaves = sigilo.chaves_sigilosas(self.tmp / "Sigilosos", raiz=self.tmp / "Acervo")
        self.assertIn(P.nome_arquivo, chaves)
        self.assertIn(P.nome_arquivo, set(sigilo.apuradas_no_download()))
        self.assertEqual(sigilo.motivo(self.cfg, P), sigilo.MOTIVO_DOWNLOAD)
        # sem o relatório do lote também: só os autos de E na pasta
        sigilo.arquivo_do_download().unlink()
        for nome in motor.RELATORIOS:
            for pasta in (self.destino, self.tmp / "Sigilosos" / self.destino.name):
                (pasta / "_controle" / nome).unlink(missing_ok=True)
        sigilo.chaves_sigilosas(self.tmp / "Sigilosos", raiz=self.tmp / "Acervo")
        self.assertEqual(set(sigilo.apuradas_no_download()), {P.nome_arquivo})

    def test_incidente_comum_sigiloso_nao_poe_o_principal_no_registro(self):
        """Achado Z2, o controle: o incidente comum (P/01) sigiloso, pela
        página ou com os autos na pasta, não põe o principal no registro do
        download - nem no motor, nem na regra única."""
        P01 = cnj.ler(f"{P.formatado}/01")
        r = self.lote([P01], grau="1g", roteiro={P01.formatado: ["ok_sigiloso"]}).itens[0]
        self.assertTrue(r.sigiloso)
        self.assertTrue((self.tmp / "Sigilosos" / self.destino.name /
                         f"{P01.nome_arquivo}.pdf").is_file())
        self.assertEqual(set(sigilo.apuradas_no_download()), {P01.nome_arquivo})
        sigilo.arquivo_do_download().unlink()
        chaves = sigilo.chaves_sigilosas(self.tmp / "Sigilosos", raiz=self.tmp / "Acervo")
        self.assertNotIn(P.nome_arquivo, chaves)
        self.assertNotIn(P.nome_arquivo, set(sigilo.apuradas_no_download()))
        self.assertEqual(sigilo.motivo(self.cfg, P), "")

    def test_principal_ja_baixado_depois_do_recurso_interno_diz_o_porque(self):
        """Achado X3 (a): P baixado público numa rodada; depois [E, P]. A
        consulta de E apura P e leva os autos dele; P, já na pasta de
        sigilosos (JA_BAIXADO), diz por que é sigiloso."""
        self.lote([P], grau="2g")
        e, p = self.lote([E, P], grau="2g", portal=PortalDoSegredo).itens
        pdf = self.tmp / "Sigilosos" / self.destino.name / f"{P.nome_arquivo} (2G).pdf"
        self.assertEqual((p.situacao, p.sigiloso, p.arquivo), (modelos.JA_BAIXADO, True, str(pdf)))
        self.assertIn(self.PORQUE_DE_P, p.detalhe)
        self.assertEqual(p.detalhe.count(self.PORQUE_DE_P), 1)
        self.assertIn(f"o processo principal {P.formatado} passa a ser tratado como sigiloso: "
                      "1 cópia dos autos dele levada para a pasta de sigilosos", e.detalhe)
        self.assertEqual(processo_json(p)["sigiloso"], True)

    def principal_que_falhou(self, acao: list, situacao: str) -> None:
        """Achados X3 (b) e X11: [P, E] com P que falha (ERRO ou SEM_ACESSO)
        antes de a consulta de E abrir a página dele em segredo. O registro
        do download e o relatório já o dão como sigiloso: o item (o JSON do
        lote) também, com o porquê, e a cópia de uma rodada anterior sai do
        acervo."""
        self.lote([P], grau="2g")
        self.ctx = ContextoComEventos()
        p, e = self.lote([P, E], grau="2g", portal=PortalDoSegredo,
                         roteiro={P.formatado: acao}, rebaixar_incompletos=True).itens
        self.assertEqual((p.situacao, p.sigiloso), (situacao, True))
        self.assertIn(self.PORQUE_DE_P, p.detalhe)
        self.assertEqual(processo_json(p)["sigiloso"], True)
        self.assertEqual(self.ctx.itens.count((P.formatado, situacao)), 2,
                         "o item de P é publicado de novo, já sigiloso")
        self.assertEqual(list(self.destino.glob("*.pdf")), [])
        self.assertIn("1 cópia dos autos dele levada para a pasta de sigilosos", e.detalhe)
        self.assertTrue(sigilo.motivo_do_download(P))

    def test_principal_que_falhou_antes_do_recurso_interno_passa_a_sigiloso(self):
        self.principal_que_falhou(["erro", "erro"], modelos.ERRO)

    def test_principal_sem_acesso_antes_do_recurso_interno_passa_a_sigiloso(self):
        self.principal_que_falhou(["sem_acesso"], modelos.SEM_ACESSO)

    def test_detalhe_do_recurso_interno_nao_inventa_copias_do_principal(self):
        """Achado X4: a retirada pelo principal leva também os autos dos
        incidentes dele. Com só o incidente P/01 no acervo, o detalhe de E
        não diz que levou "cópia dos autos dele"."""
        P01 = cnj.ler(f"{P.formatado}/01")
        self.lote([P01], grau="1g")
        e = self.lote([E], grau="2g", portal=PortalDoSegredo).itens[0]
        self.assertIn(f"o processo principal {P.formatado} passa a ser tratado como sigiloso: "
                      "1 cópia dos autos dos incidentes dele levada para a pasta de sigilosos",
                      e.detalhe)
        self.assertNotIn("cópia dos autos dele", e.detalhe)
        self.assertTrue((self.tmp / "Sigilosos" / self.destino.name /
                         f"{P01.nome_arquivo}.pdf").is_file())

    def test_detalhe_do_recurso_interno_conta_a_parte_os_autos_dos_incidentes(self):
        # Achado X4: com os autos dele e os do incidente, cada um na sua conta
        P01 = cnj.ler(f"{P.formatado}/01")
        self.lote([P, P01], grau="1g")
        e = self.lote([E], grau="2g", portal=PortalDoSegredo).itens[0]
        self.assertIn(f"o processo principal {P.formatado} passa a ser tratado como sigiloso: "
                      "1 cópia dos autos dele e 1 dos incidentes dele levadas para a pasta de "
                      "sigilosos", e.detalhe)

    def principal_sem_registro(self, relacao: list) -> None:
        """Achado X5: com a separação dos sigilosos desligada e o registro do
        download sem poder ser gravado, os autos do principal apurado pelo
        recurso interno vão para a pasta de sigilosos (o lado seguro), e o
        detalhe diz por quê - no item dele e, sem item, no do recurso."""
        self.lote([P], grau="2g", separar_sigilosos=False)
        with mock.patch.object(sigilo, "lembrar_do_download", lambda *a, **k: False):
            quem = self.lote(relacao, grau="2g", portal=PortalDoSegredo,
                             separar_sigilosos=False).itens[0]       # P, ou E sem o de P
        self.assertIn(motor.SEM_REGISTRO_DO_SIGILO, quem.detalhe)
        self.assertTrue((self.tmp / "Sigilosos" / self.destino.name /
                         f"{P.nome_arquivo} (2G).pdf").is_file())
        self.assertEqual(list(self.destino.glob(f"{P.nome_arquivo}*.pdf")), [])

    def test_separacao_desligada_e_o_registro_do_principal_que_falha(self):
        self.principal_sem_registro([P, E])

    def test_separacao_desligada_e_o_registro_do_principal_sem_item_que_falha(self):
        self.principal_sem_registro([E])

    def originario_vai_para_logs(self, rodadas: list) -> None:
        """Achado X6: nos três caminhos do download em que o originário herda
        o sigilo da origem (baixado depois dela, baixado antes dela na mesma
        rodada, já na pasta), o registro do programa (Logs) diz qual foi, com
        a frase do preparo (sigilo.chaves_sigilosas) - o passo 6 do manual o
        procura lá."""
        frase = (f"originário {H.formatado} tratado como sigiloso: o processo de origem "
                 f"{A.formatado} é sigiloso")
        h = None
        with self.assertLogs("download.motor", "WARNING") as logs:
            for relacao, roteiro in rodadas:
                itens = self.lote(relacao, grau="2g", capas={H.formatado: self.CAPA_DO_HC},
                                  roteiro=roteiro).itens
                h = next((r for r in itens if r.numero == H.formatado), h)
        self.assertTrue(h.sigiloso)
        self.assertEqual(sum(frase in linha for linha in logs.output), 1, logs.output)

    def test_originario_baixado_depois_da_origem_vai_para_logs(self):
        self.originario_vai_para_logs([([A], {A.formatado: ["ok_sigiloso"]}), ([H], None)])

    def test_originario_baixado_antes_da_origem_vai_para_logs(self):
        self.originario_vai_para_logs([([H, A], {A.formatado: ["ok_sigiloso"]})])

    def test_originario_ja_baixado_vai_para_logs(self):
        self.originario_vai_para_logs([([H], None), ([A], {A.formatado: ["ok_sigiloso"]}),
                                       ([H], None)])


# =================================================================== eProc
class TestEProcNoGrau(apoio.PastaTemporaria):
    def tribunal(self, grau="1g"):
        t = replace(tribunais.por_sigla("TJRS"),
                    urls={"1g": ["https://eproc1g.tjfalso.invalid/eproc/"],
                          "2g": ["https://eproc2g.tjfalso.invalid/eproc/"]})
        return t.no_grau(grau)

    def portal(self, tribunal, ctx=None, **extra):
        return eproc.PortalEProc(None, tribunal, apoio.opcoes_de_teste(self.tmp), ctx, None,
                                 seletores=eproc.SELETORES_PADRAO, **extra)

    def test_grau_so_do_tribunal(self):
        p1, p2 = self.portal(self.tribunal()), self.portal(self.tribunal("2g"))
        self.assertEqual((p1.grau, p1.nome), ("1g", "eProc do TJRS"))
        self.assertEqual((p2.grau, p2.nome), ("2g", "eProc do TJRS (2º grau)"))
        # grau= igual ao do Tribunal é aceito; divergente é erro
        self.assertEqual(self.portal(self.tribunal("2g"), grau="2").grau, "2g")
        with self.assertRaises(ValueError) as caso:
            self.portal(self.tribunal(), grau="2g")
        self.assertIn("passe tribunal.no_grau('2g')", str(caso.exception))
        with self.assertRaises(ValueError):
            self.portal(self.tribunal("2g"), grau="1g")

    def test_sem_endereco_do_2o_grau_nao_abre(self):
        so_1g = replace(tribunais.por_sigla("TJRS"),
                        urls={"1g": ["https://eproc1g.tjfalso.invalid/eproc/"]})
        self.portal(so_1g)                              # o 1º grau, como sempre
        with self.assertRaises(modelos.PortalIndisponivel) as caso:
            self.portal(replace(so_1g, grau="2g"))
        self.assertIn("eProc do TJRS (2º grau)", str(caso.exception))

    def test_nao_encontrado_com_a_dica_do_grau(self):
        for grau, inicio in (("1g", "não encontrado no 1º grau do eProc do TJRS. Confira o "
                                    "número; "),
                             ("2g", "não encontrado no eProc do TJRS (2º grau). Confira o "
                                    "número; ")):
            p = self.portal(self.tribunal(grau))
            p._pela_pesquisa_rapida = lambda n: "nao_encontrado"
            p._pela_consulta = lambda n: "nao_encontrado"
            for n in (A, H, PL, E):
                with self.subTest(grau=grau, numero=n.formatado):
                    with self.assertRaises(modelos.ProcessoNaoEncontrado) as caso:
                        p._abrir_processo(n)
                    texto = str(caso.exception)
                    self.assertTrue(texto.startswith(inicio), texto)
                    self.assertIn(modelos.dica_de_grau(n, grau), texto)

    def test_eventos_com_o_grau_so_no_2o(self):
        for grau in ("1g", "2g"):
            ctx = ContextoComEventos()
            p = self.portal(self.tribunal(grau), ctx)
            p._evento("login_aguardando", modo="senha", motivo="manual")
            p._evento("login_concluido")
            self.assertEqual([t for t, _ in ctx.eventos], ["login_aguardando", "login_concluido"])
            for tipo, dados in ctx.eventos:
                self.assertEqual((dados["sistema"], dados["tribunal"]), ("eproc", "TJRS"))
                with self.subTest(grau=grau, tipo=tipo):
                    if grau == "2g":
                        self.assertEqual(dados["grau"], "2g")
                    else:
                        self.assertNotIn("grau", dados)

    def test_manifesto_e_capa_json_com_o_grau_so_no_2o(self):
        n = apoio.numero("5000001", tr="21")
        m1 = eproc.manifesto_do_processo(n, "eProc do TJRS", "TJRS", {}, [], [], False)
        m2 = eproc.manifesto_do_processo(n, "eProc do TJRS (2º grau)", "TJRS", {}, [], [],
                                         False, grau="2g")
        self.assertNotIn("grau", m1)
        self.assertEqual((m2["grau"], paginacao.grau(m2), paginacao.grau(m1)), ("2g", "2g", "1g"))
        c1 = eproc.dados_da_capa(n, "eProc do TJRS", "TJRS", {}, [], [], False, m1)
        c2 = eproc.dados_da_capa(n, "eProc do TJRS (2º grau)", "TJRS", {}, [], [], False, m2,
                                 grau="2g")
        self.assertNotIn("grau", c1)
        self.assertEqual(list(c2)[:3], ["formato", "sistema", "grau"])
        self.assertEqual(c2["grau"], "2g")
        self.assertEqual({k: v for k, v in c2.items() if k not in ("grau", "portal",
                                                                    "extraido_em")},
                         {k: v for k, v in c1.items() if k not in ("portal", "extraido_em")})

    def test_essencial_da_paginacao_com_o_grau(self):
        m = paginacao.manifesto_esaj(A.formatado, 3, tribunal="TJAL", grau="2g")
        self.assertEqual(motor.essencial_da_paginacao(m)["grau"], "2g")
        m = paginacao.manifesto_esaj(A.formatado, 3, tribunal="TJAL")
        self.assertNotIn("grau", motor.essencial_da_paginacao(m))


# ==================================================================== CLI
class TestCliGrau(BaseCli):
    def ler_json(self, arq):
        return json.loads(Path(arq).read_text(encoding="utf-8"))

    def test_grau_formas_aceitas_e_erro_de_uso(self):
        parser = cli.criar_parser()
        for valor, esperado in (("1g", "1g"), ("2g", "2g"), ("1", "1g"), ("2", "2g"),
                                ("2º", "2g"), ("1º", "1g"), ("2G", "2g")):
            with self.subTest(valor):
                self.assertEqual(parser.parse_args(["--grau", valor]).grau, esperado)
        self.assertIsNone(parser.parse_args([]).grau)
        erros = io.StringIO()
        with mock.patch("sys.stderr", erros), self.assertRaises(SystemExit) as saida:
            cli.main([A.formatado, "--grau", "3"], configurar_log=False)
        self.assertEqual(saida.exception.code, 2)
        self.assertIn("'3' não é grau: use 1g (1º grau) ou 2g (2º grau)", erros.getvalue())

    def test_sem_grau_e_1g_mesmo_com_os_ajustes_em_2g(self):
        self.cfg.definir("download", "grau", "2g")
        arq = self.tmp / "lote.json"
        codigo, _ = self.rodar([A.formatado, "--json", str(arq)])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.capturado["opcoes"].grau, "1g")
        self.assertEqual(self.ler_json(arq)["grau"], "1g")
        codigo, _ = self.rodar([A.formatado, "--json", str(arq), "--grau", "2g"])
        self.assertEqual(self.capturado["opcoes"].grau, "2g")
        dados = self.ler_json(arq)
        self.assertEqual(dados["grau"], "2g")

    def test_grau_do_topo_em_todo_json(self):
        # a saída sem relação
        arq = self.tmp / "sem.json"
        codigo, _ = self.rodar(["--json", str(arq), "--grau", "2g"])
        self.assertEqual(codigo, 2)
        self.assertEqual(self.ler_json(arq)["grau"], "2g")
        codigo, _ = self.rodar(["--json", str(arq)])
        self.assertEqual(self.ler_json(arq)["grau"], "1g")
        # o primeiro JSON do --desanexar
        arq = self.tmp / "des.json"
        popen = mock.Mock(return_value=mock.Mock(pid=77))
        with mock.patch.object(cli.subprocess, "Popen", popen):
            codigo, _ = self.rodar([A.formatado, "--json", str(arq), "--desanexar",
                                    "--grau", "2g"])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.ler_json(arq)["grau"], "2g")
        self.assertIn("--grau", popen.call_args.args[0])
        # o acompanhamento sem quem o crie com o grau: 1g
        self.assertEqual(Acompanhamento(None).dados()["grau"], "1g")

    def test_completar_aceita_o_recurso_interno(self):
        codigo, _ = self.rodar(["0706265-50.2017/50000", "0706265-50.2017",
                                "--completar", "8.02.0001"])
        self.assertEqual(codigo, 0)
        self.assertEqual([n.formatado for n in self.capturado["numeros"]],
                         [E.formatado, P.formatado])

    def test_credenciais_perguntadas_pelo_portal_no_grau(self):
        self.cfg.definir("eproc", "login", "senha")
        perguntados = []

        def pedir(grupos, opcoes, cofre):
            perguntados.extend((t.portal, t.grau) for t in grupos)
            return {}
        with mock.patch.object(cli, "_pedir_credenciais", pedir):
            self.rodar([A.formatado, H.formatado, apoio.numero("5000001", tr="21").formatado,
                        "--grau", "1g"])
        self.assertEqual(perguntados, [("esaj:TJAL", "1g"), ("esaj:TJAL", "2g"),
                                       ("eproc:TJRS", "1g")])
        perguntados.clear()
        with mock.patch.object(cli, "_pedir_credenciais", pedir):
            self.rodar([apoio.numero("5000001", tr="21").formatado, SP.formatado,
                        "--grau", "2g"])
        # o TJSP sem o 2º grau fica de fora (o motor o dá como não suportado)
        self.assertEqual(perguntados, [("eproc2g:TJRS", "2g")])

    def test_pedir_credenciais_uma_vez_por_portal_com_o_nome_do_grau(self):
        t = tribunais.por_sigla("TJRS")
        cofre = apoio.CofreFalso()
        opcoes = apoio.opcoes_de_teste(self.tmp)
        saida = io.StringIO()
        with mock.patch("sys.stdout", saida), mock.patch.object(cli, "_interativo",
                                                                 lambda: False):
            cli._pedir_credenciais([t, t.no_grau("2g"), t.no_grau("2g")], opcoes, cofre)
        self.assertEqual(cofre.pedidos, ["eproc:TJRS", "eproc2g:TJRS"])
        self.assertIn("sem usuário e senha guardados para o eProc do TJRS:", saida.getvalue())
        self.assertIn("sem usuário e senha guardados para o eProc do TJRS (2º grau):",
                      saida.getvalue())


# ======================================================== eProc de mentira
class TestEProcDoSegundoGrauDeMentira(apoio.PastaTemporaria):
    """O PortalEProc do 2º grau contra o eProc de mentira no host do 2º grau
    (apoio_eproc.EProcFalso(grau="2g")): o endereço, o nome, o manifesto, a
    capa e as gravações pelo nome dos autos do 2º grau."""

    @classmethod
    def setUpClass(cls):
        from testes import apoio_eproc as ae
        if ae.navegador_de_teste() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")

    def setUp(self):
        super().setUp()
        p = mock.patch.object(eproc, "PAUSA_DOCUMENTOS_S", 0)
        p.start()
        self.addCleanup(p.stop)

    def test_baixa_no_eproc2g_com_o_grau(self):
        from testes import apoio_eproc as ae
        falso = ae.EProcFalso(grau="2g")
        t = replace(tribunais.por_sigla("TJRS"), urls={"1g": [ae.BASE], "2g": [ae.BASE_2G]})
        t2 = t.no_grau("2g")
        ctx = ContextoComEventos(codigos=[ae.CODIGO])
        opcoes = apoio.opcoes_de_teste(self.tmp, espera_s=20, espera_login_min=1,
                                       baixar_midias=True)
        destino = self.tmp / "provisorio" / f"{ae.P1.nome_arquivo} (2G).pdf"
        with ae.navegador(falso, self.tmp, "eproc2g-TJRS") as nav:
            portal = eproc.PortalEProc(nav, t2, opcoes, ctx, (ae.USUARIO, ae.SENHA),
                                       seletores=eproc.SELETORES_PADRAO)
            portal.entrar()
            r = portal.baixar(ae.P1, destino)
            nao = portal.baixar(ae.P_NAO, self.tmp / "provisorio" / "nao (2G).pdf")
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual(portal.base, ae.BASE_2G)
        self.assertTrue(falso.pedidos)
        self.assertTrue(all(ae.HOST not in u for _, u in falso.pedidos),
                        "nada vai ao eProc do 1º grau")
        m = paginacao.ler_do_pdf(destino)
        self.assertEqual((m["grau"], m["portal"]), ("2g", "eProc do TJRS (2º grau)"))
        self.assertIn(";grau=2g", paginacao.palavras_chave(m))
        controle = destino.parent / "_controle"
        capa = json.loads((controle / f"{ae.P1.nome_arquivo} (2G)_capa.json")
                          .read_text("utf-8"))
        self.assertEqual(capa["grau"], "2g")
        self.assertTrue((controle / f"{ae.P1.nome_arquivo} (2G)_capa.txt").is_file())
        self.assertFalse((controle / f"{ae.P1.nome_arquivo}_capa.json").exists())
        self.assertTrue((controle / "midias" / f"{ae.P1.nome_arquivo} (2G)").is_dir())
        self.assertEqual(nao.situacao, modelos.NAO_ENCONTRADO)
        self.assertTrue(nao.detalhe.startswith("não encontrado no eProc do TJRS (2º grau). "
                                               "Confira o número; "), nao.detalhe)
        self.assertIn(modelos.dica_de_grau(ae.P_NAO, "2g"), nao.detalhe)

    def test_o_eproc_do_1o_grau_nao_responde_no_host_do_2o(self):
        from testes import apoio_eproc as ae
        falso = ae.EProcFalso()
        self.assertEqual((falso.host, falso.base), (ae.HOST, ae.BASE))
        self.assertEqual(ae.EProcFalso(grau="2g").base, ae.BASE_2G)


if __name__ == "__main__":
    unittest.main()
