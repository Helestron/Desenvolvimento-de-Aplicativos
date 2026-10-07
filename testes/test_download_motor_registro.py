"""O motor do download (1.0.2): o registro que sobrevive a uma nova rodada,
a causa legível por máquina, as consultas a cada sistema, os eventos, a
pasta de sigilosos de cada lote, a trava do lote e as esperas.

Com portal e navegador de mentira (testes/apoio_download.py)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

from helestron.download import modelos, motor
from helestron.nucleo import paginacao

from testes import apoio_download as apoio
from testes.test_download_motor import TJAL1, TJAL2, TJAL3, TJRS1, BaseMotor, ler_relatorio


class ContextoComEventos(apoio.ContextoGravador):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.eventos = []

    def evento(self, tipo, **dados):
        self.eventos.append((tipo, dados))

    def tipos(self):
        return [t for t, _ in self.eventos]


def fabricas_com(roteiro=None, ajustes=None, falha_entrar=None, baixar=None, ctx=None):
    """As fábricas do apoio, com o resultado de cada número ajustado
    ('ajustes': {número: {campo: valor}}), um 'baixar' próprio e o entrar()
    anotado nos eventos de 'ctx'."""
    fp, fn = apoio.fabricas(roteiro, falha_entrar)

    def fabrica(nav, tribunal, opcoes, ctx_, credenciais):
        portal = fp(nav, tribunal, opcoes, ctx_, credenciais)
        original = portal.baixar
        entrar = portal.entrar

        def baixar_(numero, destino_pdf, senha=None):
            if baixar is not None:
                portal.chamadas.append((numero.formatado, senha))
                return baixar(portal, numero, destino_pdf, senha)
            r = original(numero, destino_pdf, senha)
            for campo, valor in (ajustes or {}).get(numero.formatado, {}).items():
                setattr(r, campo, valor)
            return r

        def entrar_():
            if ctx is not None:
                ctx.eventos.append(("entrar", {"sistema": tribunal.sistema}))
            return entrar()
        portal.baixar = baixar_
        portal.entrar = entrar_
        return portal
    return fabrica, fn


def pdf_com_manifesto(caminho: Path, paginas: int, manifesto: dict) -> Path:
    import pymupdf
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(stream=apoio.pdf_bytes(paginas), filetype="pdf")
    paginacao.gravar_no_doc(doc, manifesto)
    doc.save(str(caminho))
    doc.close()
    return caminho


def linha_csv(**campos) -> list:
    return [campos.get(c, "") for c in motor.COLUNAS]


class BaseRegistro(BaseMotor):
    def setUp(self):
        super().setUp()
        self.ctx = ContextoComEventos()

    def executar(self, numeros, fp, fn, destino=None, cofre=None, **opcoes):
        self.opcoes = apoio.opcoes_de_teste(self.tmp, **opcoes)
        return motor.executar(numeros, destino or self.destino, self.opcoes, self.ctx,
                              cofre=cofre, fabrica_portal=fp, fabrica_navegador=fn)

    def rodar_alt(self, numeros, roteiro=None, falha_alt=None, ajustes=None, **opcoes):
        fp_base, fn = fabricas_com(roteiro, ajustes, ctx=self.ctx)

        def fp(nav, tribunal, op, ctx, credenciais):
            portal = fp_base(nav, tribunal, op, ctx, credenciais)
            if tribunal.sistema == "eproc" and falha_alt is not None:
                portal.falha_entrar = [falha_alt]
            return portal
        return self.executar(numeros, fp, fn, **opcoes)


# ===================================================================== causa
class TestCausa(BaseRegistro):
    def test_causa_de_cada_falha(self):
        casos = [
            ({"TJAL": [modelos.LoginFalhou("a senha expirou")]}, None, modelos.CAUSA_LOGIN),
            ({"TJAL": [modelos.PortalIndisponivel("fora do ar")]}, None, modelos.CAUSA_PORTAL),
            ({"TJAL": [modelos.NavegadorOcupado("já aberto")]}, None,
             modelos.CAUSA_NAVEGADOR_OCUPADO),
            ({"TJAL": [RuntimeError("quebrou")]}, None, modelos.CAUSA_INESPERADO),
            (None, {TJAL1.formatado: ["sessao"] * 10}, modelos.CAUSA_SESSAO),
            (None, {TJAL1.formatado: ["erro", "erro"]}, modelos.CAUSA_FALHA),
        ]
        for falha_entrar, roteiro, causa in casos:
            with self.subTest(causa=causa):
                fp, fn = fabricas_com(roteiro, falha_entrar=falha_entrar)
                self.destino = self.tmp / "Acervo" / "Processos" / f"Lote {causa}"
                resumo = self.executar([TJAL1], fp, fn, tentativas=2)
                r = resumo.itens[0]
                self.assertEqual(r.situacao, modelos.ERRO)
                self.assertEqual(r.causa, causa)
                self.assertTrue(r.refazer)
                self.assertIn(causa, modelos.CAUSAS)
                linhas = ler_relatorio(resumo.relatorio)
                self.assertEqual(linhas[0][-1], "causa")
                self.assertEqual(linhas[1][-1], causa)

    def test_interrompido_e_portal_parou(self):
        fp, fn = fabricas_com({TJAL2.formatado: ["cancelar"]})
        resumo = self.executar([TJAL1, TJAL2, TJAL3], fp, fn)
        self.assertEqual([r.causa for r in resumo.itens],
                         ["", modelos.CAUSA_INTERROMPIDO, modelos.CAUSA_INTERROMPIDO])
        self.assertTrue(all(r.refazer for r in resumo.itens[1:]))
        self.ctx = ContextoComEventos()             # o "Parar" valeu só para aquele lote
        self.destino = self.tmp / "Acervo" / "Processos" / "Outro lote"
        lista = [apoio.numero(f"07000{i:02d}", tr="02") for i in range(5)]
        fp, fn = fabricas_com({n.formatado: ["indisponivel"] * 5 for n in lista})
        resumo = self.executar(lista, fp, fn, tentativas=1)
        self.assertEqual([r.causa for r in resumo.itens],
                         [modelos.CAUSA_PORTAL] * 3 + [modelos.CAUSA_PORTAL_PAROU] * 2)

    def test_pdf_invalido_e_gravacao(self):
        def sem_pdf(portal, numero, destino_pdf, senha=None):
            return modelos.ResultadoProcesso(0, numero.formatado, "TJAL", "esaj", modelos.OK)
        fp, fn = fabricas_com(baixar=sem_pdf)
        r = self.executar([TJAL1], fp, fn).itens[0]
        self.assertEqual((r.situacao, r.causa), (modelos.ERRO, modelos.CAUSA_PDF_INVALIDO))

        original = motor._mover

        def disco_cheio(origem, destino, *a, **k):
            if Path(destino).suffix == ".pdf" and motor._dentro(destino, self.destino):
                raise OSError(28, "Não há espaço no disco")
            return original(origem, destino, *a, **k)
        fp, fn = fabricas_com()
        with mock.patch.object(motor, "_mover", disco_cheio):
            r = self.executar([TJAL2], fp, fn).itens[0]
        self.assertEqual((r.situacao, r.causa), (modelos.ERRO, modelos.CAUSA_GRAVACAO))

    def test_definitivos_nao_pedem_nova_tentativa(self):
        fp, fn = fabricas_com({TJRS1.formatado: ["nao_encontrado"],
                               TJAL1.formatado: ["sem_acesso"]})
        resumo = self.executar([TJRS1, TJAL1, apoio.numero("8000001", tr="05"), TJAL2], fp, fn)
        self.assertEqual([r.refazer for r in resumo.itens], [False, False, False, False])
        self.assertEqual([r.causa for r in resumo.itens], ["", "", "", ""])

    def test_linha_mascarada_tem_a_causa(self):
        fp, fn = fabricas_com({TJAL1.formatado: ["ok_sigiloso"], TJAL2.formatado: ["erro"] * 3})
        resumo = self.executar([TJAL1, TJAL2], fp, fn, tentativas=1)
        linhas = ler_relatorio(resumo.relatorio)
        self.assertTrue(all(len(l) == len(motor.COLUNAS) for l in linhas))
        self.assertEqual(linhas[1][1], motor.MASCARA_SIGILOSO)
        self.assertEqual(linhas[2][-1], modelos.CAUSA_FALHA)

    def test_relatorio_antigo_sem_causa_e_lido_e_mesclado(self):
        controle = self.destino / "_controle"
        controle.mkdir(parents=True)
        antigas = ["ordem;processo;tribunal;sistema;situacao;paginas;documentos;arquivo;sigiloso;"
                   "incompleto;detalhe;data_hora",
                   f"1;{TJAL1.formatado};TJAL;esaj;OK;3;1;{TJAL1.nome_arquivo}.pdf;não;;;"
                   "2026-01-01 10:00:00",
                   f"2;{TJAL2.formatado};TJAL;esaj;ERRO;;;;não;;o portal demorou;"
                   "2026-01-01 10:01:00"]
        (controle / "relatorio.csv").write_bytes(("﻿" + "\r\n".join(antigas) + "\r\n")
                                                 .encode("utf-8"))
        fp, fn = fabricas_com()
        resumo = self.executar([TJAL2], fp, fn)
        linhas = ler_relatorio(resumo.relatorio)
        self.assertEqual(linhas[0][-1], "causa")
        self.assertEqual([(l[1], l[4], l[-1]) for l in linhas[1:]],
                         [(TJAL1.formatado, "OK", ""), (TJAL2.formatado, "OK", "")])
        # e o lote inteiro, com as linhas antigas sem causa
        lidas = motor.ler_relatorio_do_lote(self.destino, self.tmp / "Sigilosos")
        self.assertEqual([c for c, _ in lidas], [TJAL1.nome_arquivo, TJAL2.nome_arquivo])
        self.assertTrue(modelos.pede_nova_tentativa("ERRO", ""))
        self.assertTrue(modelos.pede_nova_tentativa("PENDENTE"))
        self.assertFalse(modelos.pede_nova_tentativa("OK"))
        self.assertTrue(modelos.pede_nova_tentativa("NAO_ENCONTRADO", "login"))
        self.assertFalse(modelos.pede_nova_tentativa("NAO_ENCONTRADO", ""))


# ================================================================= consultas
class TestConsultas(BaseRegistro):
    def test_consulta_normal(self):
        fp, fn = fabricas_com()
        r = self.executar([TJAL1], fp, fn).itens[0]
        self.assertEqual(r.consultas, [{"sistema": "esaj", "situacao": "OK"}])

    def test_consultas_eproc_nao_consultado_e_falhou(self):
        resumo = self.rodar_alt([TJAL1], roteiro={TJAL1.formatado: ["nao_encontrado"]},
                                falha_alt=modelos.LoginFalhou("o eProc recusou a senha"))
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.NAO_ENCONTRADO)
        self.assertEqual(r.sistema, "esaj")
        self.assertEqual(r.consultas[0], {"sistema": "esaj", "situacao": "NAO_ENCONTRADO"})
        ultima = r.consultas[-1]
        self.assertEqual((ultima["sistema"], ultima["consultado"], ultima["causa"]),
                         ("eproc", False, modelos.CAUSA_LOGIN))
        self.assertIn("recusou a senha", ultima["detalhe"])
        self.assertEqual(r.causa, modelos.CAUSA_LOGIN)
        self.assertTrue(r.refazer, "o eProc não foi consultado: uma nova rodada pode achá-lo")

        resumo = self.rodar_alt([TJAL2], roteiro={TJAL2.formatado: ["nao_encontrado", "erro"]},
                                tentativas=1)
        r = resumo.itens[0]
        self.assertEqual(r.consultas, [{"sistema": "esaj", "situacao": "NAO_ENCONTRADO"},
                                       {"sistema": "eproc", "situacao": "ERRO",
                                        "causa": modelos.CAUSA_FALHA}])
        self.assertTrue(r.refazer)

        resumo = self.rodar_alt([TJAL3], roteiro={TJAL3.formatado: ["nao_encontrado"] * 2})
        r = resumo.itens[0]
        self.assertEqual([c["sistema"] for c in r.consultas], ["esaj", "eproc"])
        self.assertEqual(r.causa, "")
        self.assertFalse(r.refazer, "não encontrado nos dois sistemas é definitivo")


# =================================================================== eventos
class TestEventos(BaseRegistro):
    def test_grupo_do_alternativo_antes_do_login_no_eproc(self):
        self.rodar_alt([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["nao_encontrado", "ok"]})
        seq = [(t, d.get("sistema"), d.get("alternativo")) for t, d in self.ctx.eventos
               if t in ("grupo_inicio", "entrar")]
        self.assertEqual(seq, [("grupo_inicio", "esaj", False), ("entrar", "esaj", None),
                               ("grupo_inicio", "eproc", True), ("entrar", "eproc", None)])
        tipos = self.ctx.tipos()
        self.assertEqual(tipos[0], "lote_inicio")
        self.assertEqual(tipos[-1], "fim")
        inicio = dict(self.ctx.eventos[0][1])
        self.assertEqual(inicio["destino"], str(self.destino))
        self.assertEqual(inicio["total"], 2)
        fim = self.ctx.eventos[-1][1]
        self.assertEqual((fim["baixados"], fim["falhas"]), (2, 0))
        grupo = next(d for t, d in self.ctx.eventos if t == "grupo_inicio")
        self.assertEqual(grupo["ordens"], [1, 2])

    def test_login_falhou_e_sessao_caiu(self):
        fp, fn = fabricas_com({TJAL1.formatado: ["sessao", "ok"]})
        self.executar([TJAL1], fp, fn)
        caiu = [d for t, d in self.ctx.eventos if t == "sessao_caiu"]
        self.assertEqual(caiu, [{"sistema": "esaj", "tribunal": "TJAL", "ordem": 1}])
        fp, fn = fabricas_com(falha_entrar={"TJAL": [modelos.LoginFalhou("senha expirada")]})
        self.executar([TJAL2], fp, fn)
        falhou = [d for t, d in self.ctx.eventos if t == "login_falhou"]
        self.assertEqual(falhou[0]["tribunal"], "TJAL")
        self.assertIn("senha expirada", falhou[0]["detalhe"])

    def test_contexto_sem_evento_nao_quebra(self):
        class Velho:                     # quem acompanha sem conhecer eventos
            def status(self, t): pass
            def progresso(self, f, t, a): pass
            def item(self, r): pass
            def cancelado(self): return False
            def avisar(self, t, m): pass
        fp, fn = fabricas_com()
        resumo = motor.executar([TJAL1], self.destino, apoio.opcoes_de_teste(self.tmp), Velho(),
                                fabrica_portal=fp, fabrica_navegador=fn)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)


# ======================================================= já na pasta (P0-4)
class TestJaBaixadoPreservaORegistro(BaseRegistro):
    AJUSTES = {TJAL1.formatado: dict(incompleto="12-15, 40", documentos=20,
                                     detalhe="montado peça a peça (o servidor não gerou o PDF)")}

    def test_rerun_preserva_sistema_incompleto_e_detalhe(self):
        primeiro = self.rodar_alt([TJAL1, TJAL2], ajustes=self.AJUSTES,
                                  roteiro={TJAL2.formatado: ["nao_encontrado", "ok"]})
        r1, r2 = primeiro.itens
        self.assertEqual((r1.sistema, r2.sistema), ("esaj", "eproc"))
        meta = motor.ler_meta(self.destino, TJAL1.nome_arquivo)
        self.assertEqual(meta["incompleto"], "12-15, 40")
        self.assertEqual(meta["numero"], TJAL1.formatado)
        for rodada in range(2):          # e o marcador não se acumula
            with self.subTest(rodada=rodada):
                segundo = self.rodar_alt([TJAL1, TJAL2])
                s1, s2 = segundo.itens
                self.assertEqual((s1.situacao, s2.situacao),
                                 (modelos.JA_BAIXADO, modelos.JA_BAIXADO))
                self.assertEqual(s1.incompleto, "12-15, 40")
                self.assertEqual(s1.documentos, 20)
                self.assertTrue(s1.detalhe.startswith(motor.JA_ESTAVA))
                self.assertEqual(s1.detalhe.count(motor.JA_ESTAVA), 1)
                self.assertIn("montado peça a peça", s1.detalhe)
                self.assertEqual(s2.sistema, "eproc",
                                 "o processo achado no eProc não volta a constar como e-SAJ")
                linhas = ler_relatorio(segundo.relatorio)[1:]
                self.assertEqual([(l[1], l[3], l[4], l[9]) for l in linhas],
                                 [(TJAL1.formatado, "esaj", "JA_BAIXADO", "12-15, 40"),
                                  (TJAL2.formatado, "eproc", "JA_BAIXADO", "")])
                self.assertEqual(apoio.PortalFalso.todos[0].chamadas, [])

    def test_sem_meta_vale_a_linha_anterior_do_relatorio(self):
        self.rodar_alt([TJAL1], roteiro={TJAL1.formatado: ["nao_encontrado", "ok"]},
                       ajustes={TJAL1.formatado: dict(incompleto="ev. 4 PET1", documentos=20,
                                                      detalhe="1 documento sigiloso")})
        motor.arquivo_meta(self.destino, TJAL1.nome_arquivo).unlink()
        r = self.rodar_alt([TJAL1]).itens[0]
        self.assertEqual((r.situacao, r.sistema, r.incompleto, r.documentos),
                         (modelos.JA_BAIXADO, "eproc", "ev. 4 PET1", 20))
        self.assertIn("1 documento sigiloso", r.detalhe)
        self.assertNotIn(motor.SEM_REGISTRO, r.detalhe)

    def test_sem_registro_nenhum_diz_que_nao_conferiu(self):
        self.destino.mkdir(parents=True)
        (self.destino / f"{TJAL1.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(3))
        r = self.rodar([TJAL1]).itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO)
        self.assertIn(motor.SEM_REGISTRO, r.detalhe)
        self.assertEqual(r.paginacao, {})

    def test_manifesto_do_pdf_e_a_fonte_primaria(self):
        m = paginacao.manifesto_esaj(TJAL1.formatado, 8, {6: "N", 7: "N", 8: "B"},
                                     origem="servidor", tribunal="TJAL")
        pdf_com_manifesto(self.destino / f"{TJAL1.nome_arquivo}.pdf", 8, m)
        motor._gravar_relatorio(self.destino / "_controle" / "relatorio.csv", [linha_csv(
            ordem=1, processo=TJAL1.formatado, tribunal="TJAL", sistema="eproc", situacao="OK",
            incompleto="1", detalhe="antigo")])
        r = self.rodar([TJAL1]).itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO)
        self.assertEqual(r.sistema, "esaj")
        self.assertEqual(r.incompleto, "6-8")
        self.assertEqual(r.paginacao["paginacao"], "folhas")
        self.assertEqual(r.paginacao["ultima"], 8)
        self.assertEqual(r.paginacao["ausentes"], {"N": "6-7", "B": "8"})
        self.assertEqual(r.paginacao["folhas_ausentes"], "6-8")
        self.assertIn("página N = folha N", r.paginacao["resumo"])

    def test_manifesto_do_eproc(self):
        docs = [{"evento": 1, "rotulo": "INIC1", "situacao": "ok", "inicio": 1, "paginas": 3},
                {"evento": 4, "rotulo": "PET1", "situacao": "ausente", "inicio": 4, "paginas": 1}]
        m = paginacao.manifesto_eproc(TJRS1.formatado, docs, tribunal="TJRS")
        pdf_com_manifesto(self.destino / f"{TJRS1.nome_arquivo}.pdf", 4, m)
        r = self.rodar([TJRS1]).itens[0]
        self.assertEqual((r.situacao, r.sistema), (modelos.JA_BAIXADO, "eproc"))
        self.assertEqual(r.incompleto, "ev. 4 PET1")
        self.assertEqual(r.paginacao["paginacao"], "documento")
        self.assertEqual(r.paginacao["ultima"], 4)
        self.assertEqual(r.paginacao["ausentes"], [{"evento": 4, "rotulo": "PET1"}])

    def test_ok_guarda_a_paginacao_do_pdf(self):
        m = paginacao.manifesto_esaj(TJAL1.formatado, 2, {2: "N"})

        def com_manifesto(portal, numero, destino_pdf, senha=None):
            pdf_com_manifesto(Path(destino_pdf), 2, m)
            return modelos.ResultadoProcesso(0, numero.formatado, "TJAL", "esaj", modelos.OK,
                                             paginas=2, incompleto="2")
        fp, fn = fabricas_com(baixar=com_manifesto)
        r = self.executar([TJAL1], fp, fn).itens[0]
        self.assertEqual(r.situacao, modelos.OK)
        self.assertEqual(r.paginacao["folhas_ausentes"], "2")
        self.assertEqual(motor.ler_meta(self.destino, TJAL1.nome_arquivo)["paginacao"]["ultima"], 2)

    def test_meta_acompanha_o_pdf_para_a_pasta_de_sigilosos(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        sig = self.tmp / "Sigilosos" / self.destino.name
        self.assertTrue(motor.arquivo_meta(sig, TJAL1.nome_arquivo).exists())
        self.assertFalse(motor.arquivo_meta(self.destino, TJAL1.nome_arquivo).exists())
        self.assertTrue(resumo.itens[0].sigiloso)
        # e a cópia de outro lote do acervo, quando o processo vira sigiloso,
        # sai com a capa (texto e JSON) e o registro
        outro = self.tmp / "Acervo" / "Processos" / "Lote antigo"
        controle = outro / "_controle"
        controle.mkdir(parents=True)
        nome = TJAL2.nome_arquivo
        (outro / f"{nome}.pdf").write_bytes(apoio.pdf_bytes(1))
        for sufixo in motor.SUFIXOS_CONTROLE:
            (controle / f"{nome}{sufixo}").write_text("{}", encoding="utf-8")
        ret = motor.retirar_do_acervo(self.cfg, TJAL2, raiz_sigilosos=self.tmp / "Sigilosos",
                                      lotes=[outro], acervo=self.tmp / "Acervo")
        self.assertEqual(ret.presos, [])
        destino = self.tmp / "Sigilosos" / "Lote antigo"
        self.assertTrue((destino / f"{nome}.pdf").exists())
        for sufixo in motor.SUFIXOS_CONTROLE:
            self.assertTrue((destino / "_controle" / f"{nome}{sufixo}").exists(), sufixo)
            self.assertFalse((controle / f"{nome}{sufixo}").exists(), sufixo)


class TestPdfAntigoDoESAJ(BaseRegistro):
    """PDF de versão anterior (sem manifesto, sem registro) cujo download
    deixou sinal de numeração deslocada: a página pode não ser a folha."""

    def preparar(self, **linha):
        self.destino.mkdir(parents=True)
        (self.destino / f"{TJAL1.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(3))
        base = dict(ordem=1, processo=TJAL1.formatado, tribunal="TJAL", sistema="esaj",
                    situacao="OK", arquivo=f"{TJAL1.nome_arquivo}.pdf")
        base.update(linha)
        motor._gravar_relatorio(self.destino / "_controle" / "relatorio.csv", [linha_csv(**base)])

    def test_com_sinais_e_baixado_de_novo(self):
        for i, linha in enumerate((dict(incompleto="6-7"), dict(detalhe="montado peça a peça (x)"),
                                   dict(detalhe="o índice soma 10 páginas e o PDF tem 8; confira"))):
            with self.subTest(linha=linha):
                self.destino = self.tmp / "Acervo" / "Processos" / f"Lote {i}"
                self.preparar(**linha)
                r = self.rodar([TJAL1]).itens[0]
                self.assertEqual(r.situacao, modelos.OK)
                self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 1)
                self.assertIn("baixado de novo", r.detalhe)
                self.assertIn("numeração possivelmente deslocada", r.detalhe)

    def test_sem_sinais_ou_do_eproc_ou_com_registro_fica(self):
        for i, linha in enumerate((dict(), dict(sistema="eproc", incompleto="ev. 4 PET1"))):
            with self.subTest(linha=linha):
                self.destino = self.tmp / "Acervo" / "Processos" / f"Lote {i}"
                self.preparar(**linha)
                r = self.rodar([TJAL1]).itens[0]
                self.assertEqual(r.situacao, modelos.JA_BAIXADO)
                self.assertEqual(apoio.PortalFalso.todos[0].chamadas, [])
        # com o registro da 1.0.2 ao lado, não: nada de baixar de novo a cada rodada
        self.destino = self.tmp / "Acervo" / "Processos" / "Lote com registro"
        self.preparar(incompleto="6-7")
        r = modelos.ResultadoProcesso(1, TJAL1.formatado, "TJAL", "esaj", modelos.OK,
                                      arquivo=str(self.destino / f"{TJAL1.nome_arquivo}.pdf"),
                                      incompleto="6-7")
        motor.gravar_meta(r)
        r = self.rodar([TJAL1]).itens[0]
        self.assertEqual((r.situacao, r.incompleto), (modelos.JA_BAIXADO, "6-7"))

    def test_rebaixar_incompletos(self):
        # com folhas ausentes no registro: baixa de novo
        self.preparar(incompleto="6-7")
        motor.gravar_meta(modelos.ResultadoProcesso(
            1, TJAL1.formatado, "TJAL", "esaj", modelos.OK,
            arquivo=str(self.destino / f"{TJAL1.nome_arquivo}.pdf"), incompleto="6-7"))
        r = self.rodar([TJAL1], rebaixar_incompletos=True).itens[0]
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("folhas ausentes (6-7)", r.detalhe)
        # completo e com manifesto: fica
        m = paginacao.manifesto_esaj(TJAL2.formatado, 2)
        pdf_com_manifesto(self.destino / f"{TJAL2.nome_arquivo}.pdf", 2, m)
        r = self.rodar([TJAL2], rebaixar_incompletos=True).itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO)
        # sem manifesto (versão anterior): baixa de novo
        (self.destino / f"{TJAL3.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(2))
        r = self.rodar([TJAL3], rebaixar_incompletos=True).itens[0]
        self.assertEqual(r.situacao, modelos.OK)
        self.assertIn("sem o manifesto", r.detalhe)


# ============================================ pasta de sigilosos de cada lote
class TestPastaDeSigilososDoLote(BaseRegistro):
    def test_lotes_de_mesmo_nome_em_pastas_diferentes_nao_se_misturam(self):
        caso_a = self.tmp / "Caso A" / "autos"
        caso_b = self.tmp / "Caso B" / "autos"
        fp, fn = fabricas_com({TJAL2.formatado: ["ok_sigiloso"]})
        a = self.executar([TJAL1, TJAL2], fp, fn, destino=caso_a)
        fp, fn = fabricas_com()
        b = self.executar([TJAL3], fp, fn, destino=caso_b)
        self.assertNotEqual(a.pasta_sigilosos, b.pasta_sigilosos)
        self.assertEqual(a.pasta_sigilosos.parent, self.tmp / "Sigilosos")
        self.assertTrue(a.pasta_sigilosos.name.startswith("autos ("))
        self.assertEqual([l[1] for l in ler_relatorio(b.relatorio)[1:]], [TJAL3.formatado])
        completo_a = ler_relatorio(a.pasta_sigilosos / "_controle" / "relatorio.csv")
        self.assertEqual([l[1] for l in completo_a[1:]], [TJAL1.formatado, TJAL2.formatado])
        self.assertEqual(a.relatorio_completo, a.pasta_sigilosos / "_controle" / "relatorio.csv")
        origem = (a.pasta_sigilosos / "_controle" / motor.ORIGEM_DO_LOTE).read_text("utf-8")
        self.assertEqual(Path(origem.strip()), caso_a.resolve())
        # de novo o Caso A: o mesmo lugar, sem o processo do Caso B
        fp, fn = fabricas_com()
        a2 = self.executar([TJAL1], fp, fn, destino=caso_a)
        self.assertEqual(a2.pasta_sigilosos, a.pasta_sigilosos)
        self.assertEqual([l[1] for l in ler_relatorio(a2.relatorio)[1:]],
                         [TJAL1.formatado, motor.MASCARA_SIGILOSO])

    def test_lote_do_acervo_continua_com_o_nome_do_lote(self):
        self.assertEqual(motor.pasta_sigilosos_do_lote(self.tmp / "Sigilosos", self.destino),
                         self.tmp / "Sigilosos" / self.destino.name)
        fora = self.tmp / "Outro" / self.destino.name
        self.assertEqual(motor.pasta_sigilosos_do_lote(self.tmp / "Sigilosos", self.destino,
                                                       pasta_processos=self.destino.parent),
                         self.tmp / "Sigilosos" / self.destino.name)
        self.assertNotEqual(motor.pasta_sigilosos_do_lote(self.tmp / "Sigilosos", fora,
                                                          pasta_processos=self.destino.parent),
                            self.tmp / "Sigilosos" / self.destino.name)

    def test_pasta_de_versao_anterior_e_adotada_so_pelo_seu_lote(self):
        raiz = self.tmp / "Sigilosos"
        antiga = raiz / "autos"
        motor._gravar_relatorio(antiga / "_controle" / "relatorio.csv", [
            linha_csv(ordem=1, processo=TJAL1.formatado, situacao="OK", sigiloso="não"),
            linha_csv(ordem=2, processo=TJAL2.formatado, situacao="OK", sigiloso="sim")])
        caso_a = self.tmp / "Caso A" / "autos"
        motor._gravar_relatorio(caso_a / "_controle" / "relatorio.csv", [
            linha_csv(ordem=1, processo=TJAL1.formatado, situacao="OK", sigiloso="não"),
            linha_csv(ordem=2, processo=motor.MASCARA_SIGILOSO, situacao="OK", sigiloso="sim")])
        self.assertEqual(motor.pasta_sigilosos_do_lote(raiz, caso_a), antiga)
        caso_b = self.tmp / "Caso B" / "autos"
        self.assertNotEqual(motor.pasta_sigilosos_do_lote(raiz, caso_b), antiga)
        # marcada por um, a pasta nunca serve ao outro
        motor._marcar_origem(antiga, caso_a)
        self.assertEqual(motor.pasta_sigilosos_do_lote(raiz, caso_a), antiga)
        self.assertNotEqual(motor.pasta_sigilosos_do_lote(raiz, caso_b), antiga)
        # e o relatório do lote é lido com as linhas reais dos sigilosos
        lidas = motor.ler_relatorio_do_lote(caso_a, raiz)
        self.assertEqual([c for c, _ in lidas], [TJAL1.nome_arquivo, TJAL2.nome_arquivo])


# ===================================================== portal fora (achado 5)
class TestPortalForaDoAr(BaseRegistro):
    def lista(self, n=6):
        return [apoio.numero(f"07000{i:02d}", tr="02") for i in range(n)]

    def test_erro_de_rede_conta_e_encerra_o_grupo(self):
        def sem_rede(portal, numero, destino_pdf, senha=None):
            raise RuntimeError("Page.goto: net::ERR_INTERNET_DISCONNECTED at "
                               "https://www2.tjal.jus.br/cpopg/show.do;jsessionid=ABC123")
        fp, fn = fabricas_com(baixar=sem_rede)
        resumo = self.executar(self.lista() + [TJRS1], fp, fn, tentativas=2)
        # 2 + 2 + 1: o 3º não gasta a espera crescente - o grupo vai ser encerrado
        self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 5)
        itens = resumo.itens
        self.assertEqual([r.causa for r in itens[:6]],
                         [modelos.CAUSA_PORTAL] * 3 + [modelos.CAUSA_PORTAL_PAROU] * 3)
        self.assertIn("portal indisponível: o computador está sem internet", itens[0].detalhe)
        self.assertNotIn("jsessionid", itens[0].detalhe)
        self.assertIn("parou de responder", itens[5].detalhe)

    def test_tela_lenta_nao_e_portal_fora(self):
        def lenta(portal, numero, destino_pdf, senha=None):
            raise RuntimeError("locator.click: Timeout 30000ms exceeded.")
        fp, fn = fabricas_com(baixar=lenta)
        resumo = self.executar(self.lista(4), fp, fn, tentativas=1)
        self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 4)
        self.assertEqual({r.causa for r in resumo.itens}, {modelos.CAUSA_FALHA})
        self.assertFalse(any("parou de responder" in r.detalhe for r in resumo.itens))
        self.assertTrue(motor.portal_fora("net::ERR_CONNECTION_REFUSED"))
        self.assertTrue(motor.portal_fora("Page.goto: Timeout 60000ms exceeded."))
        self.assertFalse(motor.portal_fora("o portal demorou demais"))


# ================================================= esperas, cofre, preparo
class TestEsperarONavegador(BaseRegistro):
    def fabrica_ocupada(self, vezes):
        contagem = {"n": 0}

        def fn(tribunal, opcoes):
            contagem["n"] += 1
            if contagem["n"] <= vezes:
                raise modelos.NavegadorOcupado("o navegador do programa já está aberto")
            return apoio.NavegadorFalso(tribunal, opcoes)
        return fn, contagem

    def test_espera_o_outro_download_terminar(self):
        fp, _ = fabricas_com()
        fn, contagem = self.fabrica_ocupada(2)
        with mock.patch.object(motor, "ESPERA_NAVEGADOR_S", 0.01):
            resumo = self.executar([TJAL1], fp, fn, esperar_navegador_s=60)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(contagem["n"], 3)
        self.assertEqual(self.ctx.tipos().count("navegador_ocupado"), 1)

    def test_sem_esperar_ou_prazo_esgotado_falha_com_a_causa(self):
        for espera in (0, 0.05):
            with self.subTest(espera=espera):
                fp, _ = fabricas_com()
                fn, _contagem = self.fabrica_ocupada(10 ** 6)
                with mock.patch.object(motor, "ESPERA_NAVEGADOR_S", 0.01):
                    r = self.executar([TJAL1], fp, fn, esperar_navegador_s=espera).itens[0]
                self.assertEqual((r.situacao, r.causa),
                                 (modelos.ERRO, modelos.CAUSA_NAVEGADOR_OCUPADO))


class TestSemCofre(BaseRegistro):
    def test_senha_guardada_nao_e_lida(self):
        cofre = apoio.CofreFalso({"esaj:TJAL": ("u", "s")})
        fp, fn = fabricas_com()
        resumo = self.executar([TJAL1], fp, fn, cofre=cofre, usar_cofre=False)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        portal = apoio.PortalFalso.todos[0]
        self.assertIsNone(portal.credenciais)
        self.assertEqual(portal.opcoes.modo_login("esaj"), "manual")
        self.assertEqual(cofre.pedidos, [])


class TestPreparoForaDoAcervo(BaseRegistro):
    def preparo_falso(self):
        chamadas = []
        falso = types.ModuleType("helestron.compartilhar.preparo")
        falso.atualizar_contexto = lambda cfg, *a, **k: chamadas.append(cfg)
        return falso, chamadas

    def test_lote_fora_do_acervo_nao_prepara(self):
        falso, chamadas = self.preparo_falso()
        fp, fn = fabricas_com()
        with mock.patch.dict(sys.modules, {"helestron.compartilhar.preparo": falso}):
            import helestron.compartilhar as pacote
            with mock.patch.object(pacote, "preparo", falso, create=True):
                self.executar([TJAL1], fp, fn, destino=self.tmp / "Fora" / "Lote",
                              atualizar_ia=True)
                self.assertEqual(chamadas, [])
                self.executar([TJAL2], fp, fn, atualizar_ia=True)     # no acervo: prepara
                self.assertEqual(len(chamadas), 1)


# ==================================================================== trava
class TestTravaDoLote(BaseRegistro):
    def test_segundo_download_na_mesma_pasta_e_recusado(self):
        controle = self.destino / "_controle"
        controle.mkdir(parents=True)
        (controle / motor.NOME_TRAVA).write_text(
            json.dumps({"pid": os.getppid(), "inicio": "2026-10-04T10:00:00"}), encoding="utf-8")
        fp, fn = fabricas_com()
        with self.assertRaises(motor.LoteEmAndamento) as erro:
            self.executar([TJAL1], fp, fn)
        self.assertIn("outro download está usando esta pasta", str(erro.exception))
        self.assertIsInstance(erro.exception, RuntimeError)
        self.assertEqual(apoio.PortalFalso.todos, [])

    def test_trava_de_processo_morto_e_desfeita_e_a_propria_sai_no_fim(self):
        morto = subprocess.Popen([sys.executable, "-c", "pass"])
        morto.wait()
        controle = self.destino / "_controle"
        controle.mkdir(parents=True)
        (controle / motor.NOME_TRAVA).write_text(json.dumps({"pid": morto.pid}), encoding="utf-8")
        vista = {}
        original = apoio.PortalFalso.entrar

        def entrar(portal):
            vista["trava"] = json.loads((controle / motor.NOME_TRAVA).read_text("utf-8"))
            return original(portal)
        fp, fn = fabricas_com()
        with mock.patch.object(apoio.PortalFalso, "entrar", entrar):
            resumo = self.executar([TJAL1], fp, fn)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(vista["trava"]["pid"], os.getpid())
        self.assertFalse((controle / motor.NOME_TRAVA).exists())
        self.assertFalse(motor.processo_vivo(morto.pid))
        self.assertTrue(motor.processo_vivo(os.getpid()))
        self.assertFalse(motor.processo_vivo(0))
