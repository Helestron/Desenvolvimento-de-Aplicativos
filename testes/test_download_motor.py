"""O motor do download, com portal e navegador de mentira.

Cobre o que o magistrado sente: a ordem da relação, os grupos por
tribunal, o que já estava baixado, o sigiloso fora do acervo, o relatório
que o Excel abre, a insistência no que falhou por instabilidade, o "Parar"
que não perde nada e o login recusado que não derruba o resto.
"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from helestron.download import modelos, motor
from helestron.nucleo import caminhos, config, sigilo

from testes import apoio_download as apoio

TJAL1 = apoio.numero("0700001", tr="02")
TJAL2 = apoio.numero("0700002", tr="02")
TJAL3 = apoio.numero("0700003", tr="02")
TJRS1 = apoio.numero("5000001", tr="21")      # eProc
TJBA1 = apoio.numero("8000001", tr="05")      # sistema 'outro'
TRT1 = apoio.numero("0100001", j="5", tr="01")  # fora do catálogo


@contextlib.contextmanager
def pymupdf_aberto(caminho):
    import pymupdf
    doc = pymupdf.open(caminho)
    try:
        yield doc
    finally:
        doc.close()


def ler_relatorio(caminho):
    bruto = caminho.read_bytes()
    assert bruto.startswith(b"\xef\xbb\xbf"), "relatório sem BOM: o Excel estraga os acentos"
    texto = bruto.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(texto), delimiter=";"))


class BaseMotor(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.destino = self.tmp / "Acervo" / "Processos" / "Lote de teste"
        self.ctx = apoio.ContextoGravador()
        p = mock.patch.object(motor, "ESPERA_ENTRE_TENTATIVAS_S", 0.0)
        p.start()
        self.addCleanup(p.stop)
        # Sem cfg, o motor lê o config.ini; nos testes, o do temporário - nunca
        # o acervo de verdade de quem roda os testes.
        self.cfg = config.Config(self.tmp / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.tmp / "Acervo"))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.tmp / "Sigilosos"))
        p = mock.patch.object(config, "carregar", lambda *a, **k: self.cfg)
        p.start()
        self.addCleanup(p.stop)

    def rodar(self, numeros, roteiro=None, falha_entrar=None, senhas=None, cofre=None,
              **opcoes):
        fp, fn = apoio.fabricas(roteiro, falha_entrar)
        self.opcoes = apoio.opcoes_de_teste(self.tmp, **opcoes)
        return motor.executar(numeros, self.destino, self.opcoes, self.ctx, senhas=senhas,
                              cofre=cofre, fabrica_portal=fp, fabrica_navegador=fn)

    def item(self, resumo, numero):
        return next(r for r in resumo.itens if r.numero == numero.formatado)


class TestOrdemEGrupos(BaseMotor):
    def test_ordem_preservada_e_grupos_por_tribunal(self):
        lista = [TJAL1, TJRS1, TJAL2, TJBA1, TJAL3]
        resumo = self.rodar(lista)
        self.assertEqual([r.numero for r in resumo.itens], [n.formatado for n in lista])
        self.assertEqual([r.ordem for r in resumo.itens], [1, 2, 3, 4, 5])
        # um portal (e um navegador) por tribunal, na ordem da 1ª aparição
        portais = apoio.PortalFalso.todos
        self.assertEqual([p.tribunal.sigla for p in portais], ["TJAL", "TJRS"])
        self.assertEqual([c[0] for c in portais[0].chamadas],
                         [TJAL1.formatado, TJAL2.formatado, TJAL3.formatado])
        self.assertEqual(portais[1].chamadas[0][0], TJRS1.formatado)
        self.assertTrue(all(n.fechado for n in apoio.NavegadorFalso.instancias))
        self.assertEqual(len(resumo.baixados), 4)
        for n in (TJAL1, TJAL2, TJAL3, TJRS1):
            self.assertTrue((self.destino / f"{n.nome_arquivo}.pdf").exists())
        # nada além dos PDFs na raiz do lote (o resto vai para _controle)
        soltos = {p.name for p in self.destino.iterdir() if p.is_file()}
        self.assertEqual(soltos, {f"{n.nome_arquivo}.pdf" for n in (TJAL1, TJAL2, TJAL3, TJRS1)})

    def test_tribunal_nao_suportado_e_desconhecido(self):
        resumo = self.rodar([TJBA1, TRT1, TJAL1])
        ba, trt, al = resumo.itens
        self.assertEqual(ba.situacao, modelos.NAO_SUPORTADO)
        self.assertIn("TJBA", ba.detalhe)
        self.assertIn("portal do tribunal", ba.detalhe)
        self.assertEqual(trt.situacao, modelos.NAO_SUPORTADO)
        self.assertIn("catálogo", trt.detalhe)
        self.assertEqual(al.situacao, modelos.OK)
        self.assertEqual([p.tribunal.sigla for p in apoio.PortalFalso.todos], ["TJAL"])
        # não suportado não entra no "tentar de novo": repetir não muda nada
        self.assertNotIn(TJBA1.formatado, resumo.a_refazer())

    def test_so_nao_suportados_nao_abre_navegador(self):
        resumo = self.rodar([TJBA1])
        self.assertEqual(apoio.NavegadorFalso.instancias, [])
        self.assertEqual(resumo.itens[0].situacao, modelos.NAO_SUPORTADO)

    def test_repetido_na_relacao_baixa_uma_vez(self):
        resumo = self.rodar([TJAL1, TJAL2, TJAL1])
        self.assertEqual(len(resumo.itens), 2)
        self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 2)

    def test_progresso_e_itens_chegam_ao_contexto(self):
        self.rodar([TJAL1, TJAL2])
        atuais = [p[2] for p in self.ctx.progressos]
        self.assertIn(TJAL1.formatado, atuais)
        self.assertIn(TJAL2.formatado, atuais)
        self.assertEqual(self.ctx.progressos[-1][:2], (2, 2))
        self.assertIn((TJAL2.formatado, modelos.OK), self.ctx.itens)


class TestJaBaixados(BaseMotor):
    def test_pula_o_que_ja_esta_na_pasta(self):
        self.destino.mkdir(parents=True)
        (self.destino / f"{TJAL1.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(3))
        resumo = self.rodar([TJAL1, TJAL2])
        r1 = self.item(resumo, TJAL1)
        self.assertEqual(r1.situacao, modelos.JA_BAIXADO)
        self.assertEqual(r1.paginas, 3)
        self.assertFalse(r1.sigiloso)
        self.assertEqual([c[0] for c in apoio.PortalFalso.todos[0].chamadas], [TJAL2.formatado])

    def test_pula_o_que_esta_na_pasta_de_sigilosos(self):
        sig = self.tmp / "Sigilosos" / self.destino.name
        sig.mkdir(parents=True)
        (sig / f"{TJAL1.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(1))
        resumo = self.rodar([TJAL1])
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO)
        self.assertTrue(r.sigiloso)
        self.assertEqual(apoio.PortalFalso.todos[0].chamadas, [])

    def test_arquivo_vazio_ou_quebrado_nao_conta_como_baixado(self):
        self.destino.mkdir(parents=True)
        (self.destino / f"{TJAL1.nome_arquivo}.pdf").write_bytes(b"")
        resumo = self.rodar([TJAL1])
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)

    def test_rebaixar_quando_pedido(self):
        self.destino.mkdir(parents=True)
        (self.destino / f"{TJAL1.nome_arquivo}.pdf").write_bytes(apoio.pdf_bytes(3))
        resumo = self.rodar([TJAL1], pular_baixados=False)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(resumo.itens[0].paginas, 2)


class TestSigilosos(BaseMotor):
    def test_sigiloso_sai_do_acervo_com_capa_e_gravacoes(self):
        resumo = self.rodar([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        r = self.item(resumo, TJAL1)
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        nome = TJAL1.nome_arquivo
        sig = self.tmp / "Sigilosos" / self.destino.name
        self.assertTrue((sig / f"{nome}.pdf").exists())
        self.assertTrue((sig / "_controle" / f"{nome}_capa.txt").exists())
        self.assertTrue((sig / "_controle" / "midias" / nome / "audiencia.mp3").exists())
        # nada do sigiloso fica no acervo compartilhado com a IA
        self.assertFalse((self.destino / f"{nome}.pdf").exists())
        self.assertFalse((self.destino / "_controle" / f"{nome}_capa.txt").exists())
        self.assertFalse((self.destino / "_controle" / "midias" / nome).exists())
        self.assertEqual(r.arquivo, str(sig / f"{nome}.pdf"))
        self.assertTrue(r.midias[0].startswith(str(sig)))
        self.assertIn("sigilosos", r.detalhe)
        self.assertEqual(len(resumo.sigilosos), 1)
        # o público continua no acervo
        self.assertTrue((self.destino / f"{TJAL2.nome_arquivo}.pdf").exists())

    def test_sem_separar_o_sigiloso_fica(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]},
                            separar_sigilosos=False)
        self.assertTrue((self.destino / f"{TJAL1.nome_arquivo}.pdf").exists())
        self.assertTrue(resumo.itens[0].sigiloso)

    def test_sigiloso_sem_senha_nao_e_repetido(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["sigiloso_sem_senha"]})
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.SIGILOSO_SEM_SENHA)
        self.assertTrue(r.sigiloso)
        self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 1)
        self.assertIn(TJAL1.formatado, resumo.a_refazer())

    def test_senha_da_lista_chega_ao_portal(self):
        dep = apoio.numero("0700001", tr="02", dependente="01")
        senhas = {TJAL1.formatado: "abc123", "outro": "x"}
        self.rodar([TJAL1, dep, TJAL2], senhas=senhas)
        chamadas = dict(apoio.PortalFalso.todos[0].chamadas)
        self.assertEqual(chamadas[TJAL1.formatado], "abc123")
        # o incidente herda a senha do principal (o ofício costuma valer para todos)
        self.assertEqual(chamadas[dep.formatado], "abc123")
        self.assertIsNone(chamadas[TJAL2.formatado])


class TestSigiloForaDoAcervo(BaseMotor):
    """O sigiloso nunca passa pelo acervo, nem quando algo dá errado."""

    def setUp(self):
        super().setUp()
        self.sig = self.tmp / "Sigilosos" / self.destino.name
        self.nome = TJAL1.nome_arquivo

    def _no_acervo(self):
        return sorted(p.name for p in (self.tmp / "Acervo").rglob(f"{self.nome}*")
                      if p.suffix != ".csv")

    def _mover_falha_nos_sigilosos(self):
        original = motor._mover

        def falha(origem, destino, *a):
            if Path(destino).suffix == ".pdf" and "Sigilosos" in Path(destino).parts:
                raise PermissionError(13, "Acesso negado")
            return original(origem, destino, *a)
        return mock.patch.object(motor, "_mover", falha)

    def test_portal_grava_fora_do_acervo(self):
        destinos = []
        original = apoio.PortalFalso.baixar

        def espiao(portal, numero, destino_pdf, senha=None):
            destinos.append(Path(destino_pdf))
            return original(portal, numero, destino_pdf, senha)
        with mock.patch.object(apoio.PortalFalso, "baixar", espiao):
            self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        self.assertFalse(motor._dentro(destinos[0], self.tmp / "Acervo"))
        self.assertEqual(list((self.tmp / "provisorio").rglob("*.*")), [],
                         "a área provisória é esvaziada")

    def test_separacao_que_falha_e_falha_e_nada_fica_no_acervo(self):
        with self._mover_falha_nos_sigilosos():
            resumo = self.rodar([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        r = self.item(resumo, TJAL1)
        self.assertEqual(r.situacao, modelos.ERRO)
        self.assertTrue(r.sigiloso)
        self.assertEqual(r.arquivo, "")
        self.assertIn("não foi posto no acervo", r.detalhe)
        self.assertIn(r, resumo.falhas)
        self.assertIn(TJAL1.formatado, resumo.a_refazer())
        self.assertEqual(self._no_acervo(), [])
        self.assertNotIn("segredo", resumo.texto())
        # na rodada seguinte, mesmo que o portal não repita o aviso, é sigiloso
        resumo2 = self.rodar([TJAL1])
        r2 = resumo2.itens[0]
        self.assertEqual(r2.situacao, modelos.OK)
        self.assertTrue(r2.sigiloso)
        self.assertTrue((self.sig / f"{self.nome}.pdf").exists())
        self.assertEqual(self._no_acervo(), [])

    def test_ctrl_c_depois_de_gravar_o_sigiloso_nao_o_deixa_no_acervo(self):
        original = apoio.PortalFalso.baixar

        def grava_e_interrompe(portal, numero, destino_pdf, senha=None):
            original(portal, numero, destino_pdf, senha)
            raise KeyboardInterrupt()
        with mock.patch.object(apoio.PortalFalso, "baixar", grava_e_interrompe):
            resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        self.assertEqual(resumo.itens[0].situacao, modelos.CANCELADO)
        self.assertEqual(self._no_acervo(), [])
        # e a rodada seguinte não o toma por "já baixado"
        resumo2 = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        self.assertEqual(resumo2.itens[0].situacao, modelos.OK)
        self.assertTrue((self.sig / f"{self.nome}.pdf").exists())

    def test_sigiloso_esquecido_no_acervo_sai_na_rodada_seguinte(self):
        # versão anterior: a separação falhou e o PDF ficou no lote
        controle = self.destino / "_controle"
        controle.mkdir(parents=True)
        (self.destino / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(2))
        (controle / f"{self.nome}_capa.txt").write_text(
            "Processo X\n\nSEGREDO DE JUSTIÇA - processo sigiloso. Não compartilhe.\n",
            encoding="utf-8")
        resumo = self.rodar([TJAL1])
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO)
        self.assertTrue(r.sigiloso)
        self.assertEqual(r.arquivo, str(self.sig / f"{self.nome}.pdf"))
        self.assertTrue((self.sig / "_controle" / f"{self.nome}_capa.txt").exists())
        self.assertEqual(self._no_acervo(), [])
        self.assertEqual(apoio.PortalFalso.todos[0].chamadas, [])

    def test_sigiloso_preso_no_acervo_e_falha_e_nao_prepara_a_ia(self):
        (self.destino / "_controle").mkdir(parents=True)
        (self.destino / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(2))
        (self.destino / "_controle" / f"{self.nome}_capa.txt").write_text(
            "SEGREDO DE JUSTIÇA", encoding="utf-8")
        chamadas = []
        falso = types.ModuleType("helestron.compartilhar.preparo")
        falso.atualizar_contexto = lambda cfg, *a, **k: chamadas.append(cfg)
        fp, fn = apoio.fabricas()
        opcoes = apoio.opcoes_de_teste(self.tmp, atualizar_ia=True)
        with self._mover_falha_nos_sigilosos(), \
                mock.patch.dict(sys.modules, {"helestron.compartilhar.preparo": falso}):
            import helestron.compartilhar as pacote
            with mock.patch.object(pacote, "preparo", falso, create=True):
                resumo = motor.executar([TJAL1, TJAL2], self.destino, opcoes, self.ctx,
                                        fabrica_portal=fp, fabrica_navegador=fn, cfg=object())
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.ERRO)
        self.assertIn("ATENÇÃO", r.detalhe)
        self.assertEqual(resumo.sigilosos_no_acervo, [str(self.destino / f"{self.nome}.pdf")])
        self.assertEqual(chamadas, [], "com sigiloso no acervo, nada vai para _ia/texto")
        self.assertTrue(any("sigiloso" in t.lower() for t, _ in self.ctx.avisos))

    def test_copia_de_outro_lote_sai_do_acervo_quando_vira_sigiloso(self):
        marco = self.destino.parent / "Pauta março"
        (marco / "_controle").mkdir(parents=True)
        (marco / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(3))
        (marco / "_controle" / f"{self.nome}_capa.txt").write_text("capa", encoding="utf-8")
        texto = self.tmp / "Acervo" / "_ia" / "texto" / f"{self.nome}.txt"
        texto.parent.mkdir(parents=True)
        texto.write_text("autos", encoding="utf-8")
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(self._no_acervo(), [])
        antigo = self.tmp / "Sigilosos" / "Pauta março"
        self.assertTrue((antigo / f"{self.nome}.pdf").exists())
        self.assertTrue((antigo / "_controle" / f"{self.nome}_capa.txt").exists())
        self.assertFalse(texto.exists(), "o texto integral dos autos sai de _ia/texto")
        # a cópia recém-baixada é a que fica na pasta do lote atual
        with pymupdf_aberto(self.sig / f"{self.nome}.pdf") as doc:
            self.assertEqual(len(doc), 2)

    def test_redownload_sigiloso_nao_e_trocado_pela_copia_antiga(self):
        self.destino.mkdir(parents=True)
        (self.destino / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(5))
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]},
                            pular_baixados=False)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(self._no_acervo(), [])
        with pymupdf_aberto(self.sig / f"{self.nome}.pdf") as doc:
            self.assertEqual(len(doc), 2)

    def test_numero_ja_sigiloso_em_outro_lote_continua_sigiloso(self):
        outro = self.tmp / "Sigilosos" / "Pauta março"
        outro.mkdir(parents=True)
        (outro / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(1))
        resumo = self.rodar([TJAL1])         # o portal, desta vez, não fala em sigilo
        r = resumo.itens[0]
        self.assertTrue(r.sigiloso)
        self.assertTrue((self.sig / f"{self.nome}.pdf").exists())
        self.assertEqual(self._no_acervo(), [])

    def test_sigilo_apurado_em_tentativa_que_falhou_vale_para_as_outras(self):
        def com_memoria(roteiro):
            fp, fn = apoio.fabricas(roteiro)

            def fabrica(*a):
                p = fp(*a)
                p.sigilosos_apurados = {self.nome}
                return p
            return fabrica, fn
        fp, fn = com_memoria({TJAL1.formatado: ["erro", "ok"]})
        self.opcoes = apoio.opcoes_de_teste(self.tmp)
        resumo = motor.executar([TJAL1], self.destino, self.opcoes, self.ctx,
                                fabrica_portal=fp, fabrica_navegador=fn)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertTrue(resumo.itens[0].sigiloso)
        self.assertEqual(self._no_acervo(), [])
        # e o ERRO de um sigiloso sai no relatório como sigiloso
        fp, fn = com_memoria({TJAL2.formatado: ["erro", "erro"]})
        self.nome = TJAL2.nome_arquivo
        resumo = motor.executar([TJAL2], self.destino, self.opcoes, self.ctx,
                                fabrica_portal=fp, fabrica_navegador=fn)
        self.assertEqual(resumo.itens[0].situacao, modelos.ERRO)
        self.assertTrue(resumo.itens[0].sigiloso)


class TestSigiloSabidoPeloPrograma(BaseMotor):
    """O que o programa já sabe sigiloso - pela pauta (o segredo decretado
    depois, o selo visto só na pauta) ou pela transcrição na pasta dos
    sigilosos - é baixado como sigiloso mesmo que a página do processo não
    mostre o selo. Antes, o motor só olhava os relatórios do lote, os PDFs da
    pasta de sigilosos e a capa: o "Baixar autos" da Pauta gravava no acervo
    o processo que a própria pauta marcava em segredo de justiça."""

    def setUp(self):
        super().setUp()
        self.pauta = self.tmp / "local" / "pauta.sqlite3"
        p = mock.patch.object(caminhos, "ARQUIVO_PAUTA", self.pauta)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(sigilo.esquecer_pauta)
        self.sig = self.tmp / "Sigilosos" / self.destino.name
        self.nome = TJAL1.nome_arquivo

    def marcar_na_pauta(self, *numeros):
        from testes.test_nucleo import pauta_com_sigiloso

        self.pauta.parent.mkdir(parents=True, exist_ok=True)
        pauta_com_sigiloso(self.pauta, *numeros)

    def no_acervo(self):
        return sorted(p.name for p in (self.tmp / "Acervo").rglob(f"{self.nome}*")
                      if p.suffix != ".csv")

    def conferir_sigiloso(self, resumo, motivo):
        r = self.item(resumo, TJAL1)
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        self.assertEqual(r.arquivo, str(self.sig / f"{self.nome}.pdf"))
        self.assertIn(f"tratado como sigiloso: {motivo}", r.detalhe)
        self.assertEqual(self.no_acervo(), [])
        # o relatório do acervo (que a IA lê) não identifica o sigiloso
        linhas = ler_relatorio(self.destino / "_controle" / "relatorio.csv")
        self.assertFalse([l for l in linhas if TJAL1.formatado in ";".join(l)])
        self.assertIn(motor.MASCARA_SIGILOSO, [l[1] for l in linhas])
        # o público continua no acervo
        self.assertTrue((self.destino / f"{TJAL2.nome_arquivo}.pdf").exists())
        self.assertFalse(self.item(resumo, TJAL2).sigiloso)

    def test_pauta_marca_o_sigilo_que_a_pagina_nao_mostra(self):
        self.marcar_na_pauta(TJAL1)
        resumo = self.rodar([TJAL1, TJAL2])         # o portal responde "ok", sem selo
        self.conferir_sigiloso(resumo, sigilo.MOTIVO_PAUTA)

    def test_transcricao_na_pasta_dos_sigilosos_marca_o_sigilo(self):
        trans = self.tmp / "Sigilosos" / "Transcricoes"
        trans.mkdir(parents=True)
        (trans / f"{self.nome}.docx").write_bytes(b"PK")
        resumo = self.rodar([TJAL1, TJAL2])
        self.conferir_sigiloso(resumo, sigilo.MOTIVO_PASTA)

    def test_copia_de_quando_era_publico_sai_do_acervo(self):
        # Baixado antes do segredo; agora a pauta mostra o selo.
        self.destino.mkdir(parents=True)
        (self.destino / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(2))
        self.marcar_na_pauta(TJAL1)
        resumo = self.rodar([TJAL1])
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO)
        self.assertTrue(r.sigiloso)
        self.assertEqual(r.arquivo, str(self.sig / f"{self.nome}.pdf"))
        self.assertEqual(self.no_acervo(), [])
        self.assertEqual(apoio.PortalFalso.todos[0].chamadas, [])

    def test_incidente_de_processo_sigiloso_e_sigiloso(self):
        """Regressão: a regra comparava o número exato, e o incidente ("/01")
        do principal que a pauta (ou a pasta) dava como sigiloso ia para o
        acervo quando o portal não mostrava o selo."""
        inc = apoio.numero("0700001", tr="02", dependente="01")
        self.marcar_na_pauta(TJAL1)                  # o principal
        resumo = self.rodar([inc, TJAL2])
        r = self.item(resumo, inc)
        self.assertEqual(r.situacao, modelos.OK)
        self.assertTrue(r.sigiloso)
        self.assertEqual(r.arquivo, str(self.sig / f"{inc.nome_arquivo}.pdf"))
        self.assertIn(f"tratado como sigiloso: {sigilo.MOTIVO_PAUTA_PRINCIPAL}", r.detalhe)
        self.assertEqual(self.no_acervo(), [])
        # o principal na pasta dos sigilosos também basta (sem o relatório
        # anterior do lote, que já o dava como sigiloso)
        sigilo.esquecer_pauta()
        self.pauta.unlink()
        (self.sig / f"{inc.nome_arquivo}.pdf").unlink()
        shutil.rmtree(self.destino / "_controle")
        shutil.rmtree(self.sig / "_controle")
        (self.sig / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(1))
        resumo = self.rodar([inc])
        self.assertIn(f"tratado como sigiloso: {sigilo.MOTIVO_PASTA_PRINCIPAL}",
                      resumo.itens[0].detalhe)
        self.assertTrue((self.sig / f"{inc.nome_arquivo}.pdf").exists())

    def test_tela_do_sigiloso_sabido_nao_vai_para_o_diagnostico(self):
        """O navegador fica sabendo que a tela é de processo sigiloso enquanto
        o portal o busca: o diagnóstico dela (com as partes) não é guardado."""
        self.marcar_na_pauta(TJAL1)
        vistos = {}
        original = apoio.PortalFalso.baixar

        def espiao(portal, numero, destino_pdf, senha=None):
            vistos[numero.formatado] = getattr(portal.nav, "sigiloso_em_curso", None)
            return original(portal, numero, destino_pdf, senha)

        with mock.patch.object(apoio.PortalFalso, "baixar", espiao):
            self.rodar([TJAL1, TJAL2])
        self.assertEqual(vistos, {TJAL1.formatado: True, TJAL2.formatado: False})
        self.assertFalse(apoio.NavegadorFalso.instancias[0].sigiloso_em_curso)


class TestTranscricoesDoSigiloso(BaseMotor):
    """Processo sigiloso: as transcrições de audiência já feitas também saem
    do acervo (<acervo>/Transcricoes -> <sigilosos>/Transcricoes)."""

    def setUp(self):
        super().setUp()
        self.nome = TJAL1.nome_arquivo
        self.inc = apoio.numero("0700001", tr="02", dependente="01")
        self.trans = self.tmp / "Acervo" / "Transcricoes"
        self.audio = self.trans / "_audio"
        self.sig = self.tmp / "Sigilosos" / "Transcricoes"
        self.audio.mkdir(parents=True)
        self.sessao = f"{self.nome} 2026-09-16 14h00"

    def escrever(self, pasta, nome, texto=None):
        caminho = pasta / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto if texto is not None else nome, encoding="utf-8")
        return caminho

    def conteudos(self, pasta):
        return sorted(p.read_text(encoding="utf-8") for p in pasta.iterdir() if p.is_file())

    def test_transcricoes_vao_junto_sem_sobrescrever_e_com_as_do_incidente(self):
        """O incidente herda o sigilo do principal: as transcrições dele saem
        junto (antes, ficavam no acervo, ao alcance da IA e da nuvem)."""
        n, inc, sessao = self.nome, self.inc.nome_arquivo, self.sessao
        for nome in (f"{n}.docx", f"{n} (2).docx", f"{inc}.docx", f"{inc} (2).docx",
                     f"{TJAL2.nome_arquivo}.docx"):
            self.escrever(self.trans, nome)
        for nome in (f"{sessao}.flac", f"{sessao}.jsonl", f"{sessao}.trava",
                     f"{sessao} - revisão.docx", f"{inc} 2026-09-16 15h00.flac",
                     f"{inc} 2026-09-16 15h00.jsonl"):
            self.escrever(self.audio, nome)
        # o que já está na pasta de sigilosos não pode ser sobrescrito
        self.escrever(self.sig, f"{n}.docx", "antigo")
        self.escrever(self.sig / "_audio", f"{sessao}.jsonl", "diário antigo")

        resumo = self.rodar([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        r = self.item(resumo, TJAL1)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        # no acervo, só o que é do outro processo
        self.assertEqual(sorted(p.name for p in self.trans.iterdir() if p.is_file()),
                         [f"{TJAL2.nome_arquivo}.docx"])
        self.assertEqual(sorted(p.name for p in self.audio.iterdir()), [])
        # na pasta de sigilosos: tudo (o do incidente também), sem perder o que já estava lá
        self.assertEqual(self.conteudos(self.sig),
                         sorted(["antigo", f"{n}.docx", f"{n} (2).docx", f"{inc}.docx",
                                 f"{inc} (2).docx"]))
        self.assertTrue((self.sig / "_audio" / f"{inc} 2026-09-16 15h00.flac").exists())
        self.assertEqual((self.sig / f"{n}.docx").read_text(encoding="utf-8"), "antigo")
        # a gravação, o diário e a trava continuam com o mesmo nome entre si
        audio_sig = self.sig / "_audio"
        self.assertEqual((audio_sig / f"{sessao}.jsonl").read_text(encoding="utf-8"),
                         "diário antigo")
        for final in (".flac", ".jsonl", ".trava"):
            self.assertEqual((audio_sig / f"{sessao} (2){final}").read_text(encoding="utf-8"),
                             f"{sessao}{final}")
        self.assertTrue((audio_sig / f"{sessao} - revisão.docx").exists())
        self.assertIn("10 arquivos de transcrição de audiência levados para a pasta de sigilosos",
                      r.detalhe)
        self.assertEqual(resumo.sigilosos_no_acervo, [])
        # o público não mexe nas transcrições
        self.assertTrue((self.trans / f"{TJAL2.nome_arquivo}.docx").exists())

    def test_incidente_sigiloso_nao_leva_as_do_principal(self):
        n, inc = self.nome, self.inc.nome_arquivo
        self.escrever(self.trans, f"{n}.docx")
        self.escrever(self.trans, f"{inc}.docx")
        self.escrever(self.audio, f"{n} 2026-09-16 14h00.flac")
        self.escrever(self.audio, f"{inc} 2026-09-16 15h00.flac")
        resumo = self.rodar([self.inc], roteiro={self.inc.formatado: ["ok_sigiloso"]})
        r = resumo.itens[0]
        self.assertEqual(sorted(p.name for p in self.trans.iterdir() if p.is_file()), [f"{n}.docx"])
        self.assertEqual([p.name for p in self.audio.iterdir()], [f"{n} 2026-09-16 14h00.flac"])
        self.assertTrue((self.sig / f"{inc}.docx").exists())
        self.assertTrue((self.sig / "_audio" / f"{inc} 2026-09-16 15h00.flac").exists())
        self.assertIn("2 arquivos de transcrição de audiência levados", r.detalhe)

    def test_ao_retirar_copia_antiga_do_acervo_com_cfg_da_tela(self):
        # já baixado na pasta de sigilosos: a rodada seguinte leva a transcrição
        lote_sig = self.tmp / "Sigilosos" / self.destino.name
        lote_sig.mkdir(parents=True)
        (lote_sig / f"{self.nome}.pdf").write_bytes(apoio.pdf_bytes(2))
        self.escrever(self.trans, f"{self.nome}.docx")
        fp, fn = apoio.fabricas()
        opcoes = apoio.opcoes_de_teste(self.tmp)
        with mock.patch.object(config, "carregar", side_effect=AssertionError("cfg foi dado")):
            resumo = motor.executar([TJAL1], self.destino, opcoes, self.ctx,
                                    fabrica_portal=fp, fabrica_navegador=fn, cfg=self.cfg)
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.JA_BAIXADO, r.detalhe)
        self.assertFalse((self.trans / f"{self.nome}.docx").exists())
        self.assertTrue((self.sig / f"{self.nome}.docx").exists())
        self.assertIn("1 arquivo de transcrição de audiência levado para a pasta de sigilosos",
                      r.detalhe)

    def test_audiencia_sendo_gravada_fica_e_e_avisada(self):
        from helestron.transcricao import ao_vivo
        sessao = self.sessao
        self.escrever(self.trans, f"{self.nome}.docx")
        flac = self.escrever(self.audio, f"{sessao}.flac")
        diario = self.escrever(self.audio, f"{sessao}.jsonl")
        trava = ao_vivo._travar(diario.with_suffix(ao_vivo.SUFIXO_TRAVA))   # "outra janela"
        try:
            resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        finally:
            ao_vivo._soltar(trava)
        r = resumo.itens[0]
        self.assertTrue(flac.exists() and diario.exists(), "a gravação em curso não sai do lugar")
        self.assertTrue((self.trans / f"{self.nome}.docx").exists())
        self.assertFalse(self.sig.exists())
        # Só os autos travam o compartilhamento: a gravação em curso é avisada
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertIn("audiência sendo gravada", r.detalhe)
        self.assertIn(str(flac), resumo.sigilosos_avisos)
        self.assertEqual(resumo.sigilosos_no_acervo, [])
        self.assertEqual(resumo.sigilosos_motivos[str(flac)],
                         "a audiência está sendo gravada agora")
        self.assertTrue(any("(a audiência está sendo gravada agora)" in m
                            for _, m in self.ctx.avisos), self.ctx.avisos)

    def test_transcricao_aberta_no_word_e_falha_e_avisada(self):
        self.escrever(self.trans, f"{self.nome}.docx")
        self.escrever(self.audio, f"{self.sessao}.flac")
        original = motor._mover

        def falha(origem, destino, *a):
            if Path(origem).suffix == ".docx":
                raise PermissionError(13, "Acesso negado")
            return original(origem, destino, *a)
        with mock.patch.object(motor, "_mover", falha):
            resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]})
        r = resumo.itens[0]
        # Só os autos travam o compartilhamento: a transcrição presa é avisada
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertIn("arquivo de transcrição no acervo que não pôde ser levado", r.detalhe)
        self.assertIn(f"{self.nome}.docx", r.detalhe)
        self.assertIn("1 arquivo de transcrição de audiência levado", r.detalhe)
        self.assertEqual(resumo.sigilosos_no_acervo, [])
        self.assertEqual(resumo.sigilosos_avisos, [str(self.trans / f"{self.nome}.docx")])
        self.assertTrue(any("sigiloso" in t.lower() for t, _ in self.ctx.avisos))

    def test_sem_separar_sigilosos_nada_se_move(self):
        self.escrever(self.trans, f"{self.nome}.docx")
        self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]}, separar_sigilosos=False)
        self.assertTrue((self.trans / f"{self.nome}.docx").exists())


class TestMover(apoio.PastaTemporaria):
    def test_insiste_quando_o_antivirus_segura_o_arquivo(self):
        origem = self.tmp / "a.pdf"
        origem.write_bytes(b"x")
        original = os.replace
        falhas = [PermissionError(13, "Acesso negado")] * 2

        def replace(a, b):
            if falhas:
                raise falhas.pop()
            return original(a, b)
        from helestron.download import pdf
        with mock.patch.object(pdf, "ESPERA_TROCA_S", 0), mock.patch("os.replace", replace):
            motor._mover(origem, self.tmp / "b" / "a.pdf")
        self.assertTrue((self.tmp / "b" / "a.pdf").exists())
        self.assertFalse(origem.exists())

    def test_outro_disco_nao_deixa_copia_pela_metade(self):
        origem = self.tmp / "a.pdf"
        origem.write_bytes(b"%PDF-" + b"x" * 100)
        destino = self.tmp / "b" / "a.pdf"
        with mock.patch.object(motor, "_mesmo_volume", return_value=False):
            motor._mover(origem, destino)
        self.assertEqual(destino.read_bytes()[:5], b"%PDF-")
        self.assertFalse(origem.exists())
        self.assertEqual([p.name for p in destino.parent.iterdir()], ["a.pdf"])

        origem.write_bytes(b"y")
        with mock.patch.object(motor, "_mesmo_volume", return_value=False), \
                mock.patch("shutil.copy2", side_effect=OSError(28, "Disco cheio")):
            with self.assertRaises(OSError):
                motor._mover(origem, destino)
        self.assertEqual(destino.read_bytes()[:5], b"%PDF-", "o destino não foi estragado")
        self.assertTrue(origem.exists())
        self.assertEqual([p.name for p in destino.parent.iterdir()], ["a.pdf"])


class TestSenhaDe(unittest.TestCase):
    def test_grafias_do_dependente(self):
        dep = apoio.numero("0700001", tr="02", dependente="01")
        principal = dep.principal
        self.assertEqual(motor.senha_de(dep, {f"{principal}/0001": "s1"}), "s1")
        self.assertEqual(motor.senha_de(dep, {f"{principal}/01": "s2"}), "s2")
        self.assertEqual(motor.senha_de(dep, {principal: "s3"}), "s3")
        # a senha específica do incidente vence a do principal
        self.assertEqual(motor.senha_de(dep, {principal: "geral", f"{principal}/1": "propria"}),
                         "propria")

    def test_principal_nao_herda_senha_de_incidente(self):
        self.assertIsNone(motor.senha_de(TJAL1, {f"{TJAL1.principal}/01": "s"}))
        self.assertIsNone(motor.senha_de(TJAL1, None))

    def test_grafia_sem_pontuacao(self):
        self.assertEqual(motor.senha_de(TJAL1, {TJAL1.digitos: "s"}), "s")


class TestRelatorio(BaseMotor):
    def test_csv_utf8_com_bom_e_ponto_e_virgula(self):
        resumo = self.rodar([TJAL1, TJBA1, TJAL2],
                            roteiro={TJAL2.formatado: ["ok_sigiloso"]})
        self.assertEqual(resumo.relatorio, self.destino / "_controle" / "relatorio.csv")
        linhas = ler_relatorio(resumo.relatorio)
        self.assertEqual(linhas[0], ["ordem", "processo", "tribunal", "sistema", "situacao",
                                     "paginas", "documentos", "arquivo", "sigiloso",
                                     "incompleto", "detalhe", "data_hora"])
        # o relatório do acervo (que a IA lê) não diz QUAL processo é sigiloso
        self.assertEqual([l[1] for l in linhas[1:]],
                         [TJAL1.formatado, TJBA1.formatado, "(processo sigiloso)"])
        self.assertEqual([l[4] for l in linhas[1:]], ["OK", "NAO_SUPORTADO", "OK"])
        self.assertEqual(linhas[1][7], f"{TJAL1.nome_arquivo}.pdf")
        self.assertEqual(linhas[1][8], "não")
        self.assertEqual(linhas[3][8], "sim")
        self.assertEqual(linhas[3][5:8], ["", "", ""])
        self.assertIn("pasta de sigilosos", linhas[3][10])
        self.assertNotIn(TJAL2.formatado, resumo.relatorio.read_text(encoding="utf-8-sig"))
        self.assertRegex(linhas[1][11], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        # o completo fica na pasta de sigilosos do lote
        completo = ler_relatorio(self.tmp / "Sigilosos" / self.destino.name / "_controle" /
                                 "relatorio.csv")
        self.assertEqual([l[1] for l in completo[1:]],
                         [TJAL1.formatado, TJBA1.formatado, TJAL2.formatado])
        self.assertIn("pasta de sigilosos", completo[3][7])
        # gravação atômica: nada de .tmp esquecido
        self.assertEqual([p.name for p in (self.destino / "_controle").glob("*.tmp")], [])

    def test_lote_sem_sigiloso_nao_cria_pasta_de_sigilosos(self):
        self.rodar([TJAL1, TJAL2])
        self.assertFalse((self.tmp / "Sigilosos").exists())

    def test_sem_separar_o_relatorio_do_lote_e_completo(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["ok_sigiloso"]},
                            separar_sigilosos=False)
        self.assertEqual(ler_relatorio(resumo.relatorio)[1][1], TJAL1.formatado)

    def test_relatorio_regravado_a_cada_item(self):
        visto = []
        original = motor._Lote.salvar_relatorio

        def espiao(lote):
            original(lote)
            visto.append(len([l for l in ler_relatorio(lote.relatorio)[1:] if l[4] == "OK"]))

        with mock.patch.object(motor._Lote, "salvar_relatorio", espiao):
            self.rodar([TJAL1, TJAL2, TJAL3])
        self.assertIn(1, visto)
        self.assertIn(2, visto)
        self.assertEqual(visto[-1], 3)

    def test_relatorio_aberto_no_excel_nao_derruba_o_lote(self):
        real = motor.os.replace

        def replace(origem, destino):
            if str(destino).endswith("relatorio.csv"):
                raise PermissionError("arquivo aberto em outro programa")
            return real(origem, destino)

        with mock.patch.object(motor.os, "replace", replace):
            resumo = self.rodar([TJAL1])
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(resumo.relatorio.name, "relatorio (atualizado).csv")
        self.assertEqual(ler_relatorio(resumo.relatorio)[1][4], "OK")
        self.assertEqual(list((self.destino / "_controle").glob("*.tmp")), [],
                         "o .tmp da troca recusada não fica esquecido")


class TestRefazerParteDoLote(BaseMotor):
    """"Tentar de novo" refaz só os que falharam, na mesma pasta: o relatório
    do lote mescla - as linhas refeitas substituem as antigas, as demais
    ficam. Antes ele era regravado só com os refeitos, e "Últimos lotes"
    mostrava o lote com 1 processo."""

    def test_relatorio_mescla_as_linhas_refeitas(self):
        from helestron import servicos

        primeiro = self.rodar([TJAL1, TJAL2, TJAL3],
                              roteiro={TJAL1.formatado: ["ok_sigiloso"],
                                       TJAL2.formatado: ["sem_acesso"]})
        self.assertEqual(primeiro.a_refazer(), [TJAL2.formatado])
        antes = ler_relatorio(primeiro.relatorio)
        segundo = self.rodar([TJAL2])                  # o "Tentar de novo"
        self.assertEqual(len(segundo.itens), 1)
        linhas = ler_relatorio(segundo.relatorio)
        self.assertEqual([l[0] for l in linhas[1:]], ["1", "2", "3"])
        self.assertEqual([l[1] for l in linhas[1:]],
                         ["(processo sigiloso)", TJAL2.formatado, TJAL3.formatado])
        self.assertEqual([l[4] for l in linhas[1:]], ["OK", "OK", "OK"])
        # a linha que não foi refeita continua como estava
        self.assertEqual(linhas[3], antes[3])
        self.assertNotIn(TJAL1.formatado, segundo.relatorio.read_text(encoding="utf-8-sig"))
        completo = ler_relatorio(self.tmp / "Sigilosos" / self.destino.name / "_controle" /
                                 "relatorio.csv")
        self.assertEqual([l[1] for l in completo[1:]],
                         [TJAL1.formatado, TJAL2.formatado, TJAL3.formatado])
        self.assertEqual(completo[1][8], "sim")
        info = servicos.ler_relatorio(segundo.relatorio)
        self.assertEqual((info.total, info.baixados, info.falhas), (3, 3, 0))
        # um processo novo no mesmo lote entra no fim, sem tirar os outros
        self.rodar([apoio.numero("0700004", tr="02")])
        linhas = ler_relatorio(segundo.relatorio)
        self.assertEqual(len(linhas) - 1, 4)
        self.assertEqual(linhas[4][1], apoio.numero("0700004", tr="02").formatado)
        self.assertEqual(linhas[4][0], "4")

    def test_sem_separar_os_sigilosos_tambem_mescla(self):
        self.rodar([TJAL1, TJAL2], roteiro={TJAL2.formatado: ["sem_acesso"]},
                   separar_sigilosos=False)
        resumo = self.rodar([TJAL2], separar_sigilosos=False)
        linhas = ler_relatorio(resumo.relatorio)
        self.assertEqual([(l[1], l[4]) for l in linhas[1:]],
                         [(TJAL1.formatado, "OK"), (TJAL2.formatado, "OK")])


class TestRetentativas(BaseMotor):
    def test_falha_passageira_e_repetida(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["erro", "ok"]}, tentativas=2)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 2)

    def test_esgotadas_as_tentativas_vira_erro_com_motivo(self):
        resumo = self.rodar([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["erro", "erro"]},
                            tentativas=2)
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.ERRO)
        self.assertIn("demorou demais", r.detalhe)
        self.assertEqual(resumo.itens[1].situacao, modelos.OK, "um erro não para o lote")
        self.assertEqual(resumo.falhas, [r])
        self.assertIn(TJAL1.formatado, resumo.a_refazer())

    def test_pdf_aberto_no_leitor_explica_e_nao_insiste(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["pdf_aberto", "ok"]},
                            tentativas=3)
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.ERRO)
        self.assertIn("aberto em outro programa", r.detalhe)
        self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 1)

    def test_nao_encontrado_nao_e_repetido(self):
        # TJRS: só eProc, sem sistema alternativo (o TJAL procuraria no eProc)
        resumo = self.rodar([TJRS1], roteiro={TJRS1.formatado: ["nao_encontrado"]},
                            tentativas=3)
        self.assertEqual(resumo.itens[0].situacao, modelos.NAO_ENCONTRADO)
        self.assertEqual(len(apoio.PortalFalso.todos), 1)
        self.assertEqual(len(apoio.PortalFalso.todos[0].chamadas), 1)

    def test_sem_acesso_devolvido_pelo_portal(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["sem_acesso"]})
        self.assertEqual(resumo.itens[0].situacao, modelos.SEM_ACESSO)

    def test_sessao_perdida_entra_de_novo_e_repete(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["sessao", "ok"]}, tentativas=1)
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(apoio.PortalFalso.todos[0].entradas, 2)

    def test_sessao_que_nunca_volta_tem_limite(self):
        resumo = self.rodar([TJAL1], roteiro={TJAL1.formatado: ["sessao"] * 10})
        self.assertEqual(resumo.itens[0].situacao, modelos.ERRO)
        self.assertEqual(apoio.PortalFalso.todos[0].entradas, 1 + motor.MAX_RELOGINS)

    def test_portal_fora_do_ar_desiste_do_grupo(self):
        lista = [apoio.numero(f"07000{i:02d}", tr="02") for i in range(6)]
        roteiro = {n.formatado: ["indisponivel"] * 5 for n in lista}
        resumo = self.rodar(lista + [TJRS1], roteiro=roteiro, tentativas=1)
        chamadas = apoio.PortalFalso.todos[0].chamadas
        self.assertEqual(len(chamadas), motor.MAX_INDISPONIVEL_SEGUIDOS)
        self.assertTrue(all(r.situacao == modelos.ERRO for r in resumo.itens[:6]))
        self.assertIn("parou de responder", resumo.itens[5].detalhe)
        self.assertEqual(resumo.itens[6].situacao, modelos.OK, "o outro tribunal segue")


class TestCancelamento(BaseMotor):
    def test_parar_nao_perde_o_item_interrompido(self):
        resumo = self.rodar([TJAL1, TJAL2, TJAL3],
                            roteiro={TJAL2.formatado: ["cancelar"]})
        r1, r2, r3 = resumo.itens
        self.assertEqual(r1.situacao, modelos.OK)
        self.assertEqual(r2.situacao, modelos.CANCELADO)
        self.assertIn("próxima vez", r2.detalhe)
        self.assertEqual(r3.situacao, modelos.CANCELADO)
        self.assertEqual([r.numero for r in resumo.pendentes], [TJAL2.formatado, TJAL3.formatado])
        self.assertEqual(resumo.a_refazer(), [TJAL2.formatado, TJAL3.formatado])
        self.assertEqual(resumo.numeros_a_refazer(), [TJAL2, TJAL3])
        self.assertTrue(resumo.cancelado)
        self.assertEqual([l[4] for l in ler_relatorio(resumo.relatorio)[1:]],
                         ["OK", "CANCELADO", "CANCELADO"])
        self.assertTrue(apoio.NavegadorFalso.instancias[0].fechado)
        self.assertFalse((self.destino / f"{TJAL2.nome_arquivo}.pdf").exists())

    def test_parar_logo_depois_de_um_sigiloso_ainda_o_protege(self):
        resumo = self.rodar([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["ok_sigiloso_e_parar"]})
        r1, r2 = resumo.itens
        self.assertEqual(r1.situacao, modelos.OK)
        sig = self.tmp / "Sigilosos" / self.destino.name
        self.assertTrue((sig / f"{TJAL1.nome_arquivo}.pdf").exists())
        self.assertFalse((self.destino / f"{TJAL1.nome_arquivo}.pdf").exists())
        self.assertEqual(r2.situacao, modelos.CANCELADO)

    def test_cancelado_antes_de_comecar_outro_grupo(self):
        resumo = self.rodar([TJAL1, TJRS1], roteiro={TJAL1.formatado: ["cancelar"]})
        self.assertEqual(len(apoio.PortalFalso.todos), 1, "o grupo do TJRS nem abre")
        self.assertEqual(resumo.itens[1].situacao, modelos.CANCELADO)

    def test_ctrl_c_no_terminal_para_sem_perder(self):
        resumo = self.rodar([TJAL1, TJAL2], roteiro={TJAL2.formatado: ["teclado"]})
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        self.assertEqual(resumo.itens[1].situacao, modelos.CANCELADO)
        self.assertTrue(resumo.relatorio.exists())

    def test_parcial_esquecido_e_limpo(self):
        self.destino.mkdir(parents=True)
        parcial = self.destino / f"{TJAL1.nome_arquivo}.pdf.parcial"
        parcial.write_bytes(b"%PDF-1.4 meio")
        self.rodar([TJAL1], roteiro={TJAL1.formatado: ["cancelar"]})
        self.assertFalse(parcial.exists())


class TestLogin(BaseMotor):
    def test_login_recusado_marca_o_grupo_e_segue_os_outros(self):
        falha = {"TJAL": [modelos.LoginFalhou("o e-SAJ recusou o usuário ou a senha")]}
        resumo = self.rodar([TJAL1, TJRS1, TJAL2], falha_entrar=falha)
        al1, rs, al2 = resumo.itens
        for r in (al1, al2):
            self.assertEqual(r.situacao, modelos.ERRO)
            self.assertTrue(r.detalhe.startswith("login falhou:"), r.detalhe)
            self.assertIn("recusou", r.detalhe)
        self.assertEqual(rs.situacao, modelos.OK)
        self.assertEqual(apoio.PortalFalso.todos[0].chamadas, [])
        self.assertTrue(self.ctx.avisos, "o usuário é avisado do login recusado")

    def test_login_que_cai_no_meio_do_grupo(self):
        falha = {"TJAL": [None, modelos.LoginFalhou("a senha expirou")]}
        resumo = self.rodar([TJAL1, TJAL2, TJAL3], falha_entrar=falha,
                            roteiro={TJAL2.formatado: ["sessao"]})
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        for r in resumo.itens[1:]:
            self.assertEqual(r.situacao, modelos.ERRO)
            self.assertIn("login falhou: a senha expirou", r.detalhe)

    def test_login_falhou_levantado_pelo_baixar(self):
        resumo = self.rodar([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["login"]})
        self.assertTrue(all(r.situacao == modelos.ERRO for r in resumo.itens))

    def test_portal_indisponivel_ao_entrar(self):
        falha = {"TJAL": [modelos.PortalIndisponivel("sem internet")]}
        resumo = self.rodar([TJAL1], falha_entrar=falha)
        self.assertEqual(resumo.itens[0].situacao, modelos.ERRO)
        self.assertIn("portal indisponível: sem internet", resumo.itens[0].detalhe)

    def test_credenciais_do_cofre_chegam_ao_portal(self):
        cofre = apoio.CofreFalso({"esaj:TJAL": ("12345678900", "s3nh@%;")})
        self.rodar([TJAL1, TJRS1], cofre=cofre)
        al, rs = apoio.PortalFalso.todos
        self.assertEqual(al.credenciais, ("12345678900", "s3nh@%;"))
        self.assertIsNone(rs.credenciais, "sem senha guardada para o eProc")
        self.assertIn("esaj:TJAL", cofre.pedidos)

    def test_login_manual_nao_consulta_o_cofre(self):
        cofre = apoio.CofreFalso({"esaj:TJAL": ("u", "s")})
        self.rodar([TJAL1], cofre=cofre, login={"esaj": "manual", "eproc": "senha"})
        self.assertIsNone(apoio.PortalFalso.todos[0].credenciais)
        self.assertEqual(cofre.pedidos, [])


class TestFabricas(unittest.TestCase):
    def test_portal_esaj(self):
        from helestron.download.esaj import PortalESAJ
        from helestron.nucleo import tribunais
        t = tribunais.por_sigla("TJAL")
        p = motor.fabrica_portal_padrao(apoio.NavegadorFalso(), t, modelos.OpcoesDownload(),
                                        apoio.ContextoGravador(), ("u", "s"))
        self.assertIsInstance(p, PortalESAJ)
        self.assertEqual(p.base, "https://www2.tjal.jus.br")

    def test_eproc_ausente_explica(self):
        from helestron.nucleo import tribunais
        t = tribunais.por_sigla("TJRS")
        with mock.patch.dict(sys.modules, {"helestron.download.eproc": None}):
            with self.assertRaises(modelos.PortalIndisponivel) as caso:
                motor.fabrica_portal_padrao(apoio.NavegadorFalso(), t, modelos.OpcoesDownload(),
                                            apoio.ContextoGravador(), None)
        self.assertIn("eProc", str(caso.exception))

    def test_eproc_presente_e_usado(self):
        from helestron.nucleo import tribunais
        falso = types.ModuleType("helestron.download.eproc")

        class PortalEProc:
            def __init__(self, *args):
                self.args = args
        falso.PortalEProc = PortalEProc
        t = tribunais.por_sigla("TJRS")
        with mock.patch.dict(sys.modules, {"helestron.download.eproc": falso}):
            p = motor.fabrica_portal_padrao("nav", t, "op", "ctx", ("u", "s"))
        self.assertIsInstance(p, PortalEProc)
        self.assertEqual(p.args, ("nav", t, "op", "ctx", ("u", "s")))

    def test_sistema_outro(self):
        from helestron.nucleo import tribunais
        with self.assertRaises(modelos.PortalIndisponivel):
            motor.fabrica_portal_padrao(None, tribunais.por_sigla("TJBA"),
                                        modelos.OpcoesDownload(), None, None)

    def test_navegador_padrao_segue_as_opcoes(self):
        from helestron.download.navegador import Navegador
        from helestron.nucleo import caminhos, tribunais
        t = tribunais.por_sigla("TJAL")
        op = modelos.OpcoesDownload(login={"esaj": "certificado"}, navegador="msedge", espera_s=30)
        nav = motor.fabrica_navegador_padrao(t, op)
        self.assertIsInstance(nav, Navegador)
        self.assertEqual(nav.perfil_base, caminhos.PERFIS / "esaj-TJAL")
        self.assertTrue(nav.certificado)
        self.assertTrue(nav.visivel, "certificado exige a janela visível (PIN do token)")
        self.assertEqual(nav.preferencia, "msedge")
        self.assertEqual(nav.espera_s, 30)
        op2 = modelos.OpcoesDownload()
        self.assertFalse(motor.fabrica_navegador_padrao(t, op2).visivel)


class TestSistemaAlternativo(BaseMotor):
    """TJAL, TJSP e TJAC estão em transição: o que o e-SAJ não acha pode
    estar no eProc. A tela já promete isso ao mostrar o acesso ao eProc."""

    def rodar_alt(self, numeros, roteiro=None, falha_alt=None, **opcoes):
        """Como rodar(), mas o entrar() do portal alternativo (eProc) pode falhar."""
        fp_base, fn = apoio.fabricas(roteiro)

        def fp(nav, tribunal, op, ctx, credenciais):
            portal = fp_base(nav, tribunal, op, ctx, credenciais)
            if tribunal.sistema == "eproc" and falha_alt is not None:
                portal.falha_entrar = [falha_alt]
            return portal
        self.opcoes = apoio.opcoes_de_teste(self.tmp, **opcoes)
        return motor.executar(numeros, self.destino, self.opcoes, self.ctx,
                              fabrica_portal=fp, fabrica_navegador=fn)

    def test_nao_encontrado_no_esaj_e_baixado_do_eproc(self):
        resumo = self.rodar_alt([TJAL1, TJAL2, TJAL3],
                                roteiro={TJAL2.formatado: ["nao_encontrado", "ok"]})
        r1, r2, r3 = resumo.itens
        self.assertEqual([r.situacao for r in resumo.itens], [modelos.OK] * 3)
        self.assertEqual((r1.sistema, r2.sistema, r3.sistema), ("esaj", "eproc", "esaj"),
                         "o relatório diz em que sistema cada um foi achado")
        esaj, eproc = apoio.PortalFalso.todos
        self.assertEqual((esaj.tribunal.sistema, eproc.tribunal.sistema), ("esaj", "eproc"))
        self.assertEqual([c[0] for c in eproc.chamadas], [TJAL2.formatado],
                         "só o não encontrado vai ao eProc")
        self.assertEqual(len(apoio.NavegadorFalso.instancias), 2, "outro navegador, outro login")
        self.assertTrue((self.destino / f"{TJAL2.nome_arquivo}.pdf").exists())
        linhas = ler_relatorio(resumo.relatorio)[1:]
        self.assertEqual([(l[1], l[3], l[4]) for l in linhas],
                         [(TJAL1.formatado, "esaj", "OK"), (TJAL2.formatado, "eproc", "OK"),
                          (TJAL3.formatado, "esaj", "OK")])

    def test_nao_encontrado_nos_dois(self):
        resumo = self.rodar_alt([TJAL1], roteiro={TJAL1.formatado: ["nao_encontrado"] * 2})
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.NAO_ENCONTRADO)
        self.assertEqual(r.sistema, "esaj")
        self.assertIn("nem no eProc do TJAL", r.detalhe)

    def test_alternativo_que_nao_entra_mantem_o_nao_encontrado(self):
        resumo = self.rodar_alt([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["nao_encontrado"]},
                                falha_alt=modelos.LoginFalhou("o eProc recusou a senha"))
        r1, r2 = resumo.itens
        self.assertEqual(r1.situacao, modelos.NAO_ENCONTRADO,
                         "um login recusado no eProc não pode virar ERRO de quem o e-SAJ não achou")
        self.assertIn("não encontrado no 1º grau", r1.detalhe)
        self.assertIn("login falhou: o eProc recusou a senha", r1.detalhe)
        self.assertEqual(r1.sistema, "esaj")
        self.assertEqual(r2.situacao, modelos.OK)
        self.assertEqual(apoio.PortalFalso.todos[1].chamadas, [])

    def test_modulo_do_eproc_ausente_mantem_o_nao_encontrado(self):
        fp_base, fn = apoio.fabricas({TJAL1.formatado: ["nao_encontrado"]})

        def fp(nav, tribunal, op, ctx, credenciais):
            if tribunal.sistema == "eproc":
                raise modelos.PortalIndisponivel("o módulo do eProc não está presente")
            return fp_base(nav, tribunal, op, ctx, credenciais)
        resumo = motor.executar([TJAL1], self.destino, apoio.opcoes_de_teste(self.tmp), self.ctx,
                                fabrica_portal=fp, fabrica_navegador=fn)
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.NAO_ENCONTRADO)
        self.assertIn("módulo do eProc", r.detalhe)

    def test_erro_no_alternativo_diz_onde_foi(self):
        resumo = self.rodar_alt([TJAL1], roteiro={TJAL1.formatado: ["nao_encontrado", "erro"]},
                                tentativas=1)
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.ERRO)
        self.assertEqual(r.sistema, "eproc")
        self.assertIn("não encontrado no e-SAJ; no eProc: o portal demorou demais", r.detalhe)

    def test_desfecho_definitivo_no_alternativo_leva_o_sistema_certo(self):
        resumo = self.rodar_alt([TJAL1], roteiro={TJAL1.formatado: ["nao_encontrado",
                                                                  "nao_encontrado_sem_acesso"]})
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.SEM_ACESSO)
        self.assertEqual(r.sistema, "eproc")

    def test_parar_no_principal_nao_abre_o_alternativo(self):
        resumo = self.rodar_alt([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["nao_encontrado"],
                                                       TJAL2.formatado: ["cancelar"]})
        self.assertEqual(len(apoio.PortalFalso.todos), 1)
        self.assertEqual(resumo.itens[0].situacao, modelos.NAO_ENCONTRADO)
        self.assertEqual(resumo.itens[1].situacao, modelos.CANCELADO)

    def test_progresso_nao_anda_para_tras(self):
        self.rodar_alt([TJAL1, TJAL2], roteiro={TJAL1.formatado: ["nao_encontrado", "ok"]})
        feitos = [p[0] for p in self.ctx.progressos]
        self.assertEqual(feitos, sorted(feitos), feitos)
        self.assertEqual(self.ctx.progressos[-1][:2], (2, 2))

    def test_tribunal_sem_alternativo_nao_reabre(self):
        self.rodar_alt([TJRS1], roteiro={TJRS1.formatado: ["nao_encontrado"]})
        self.assertEqual(len(apoio.PortalFalso.todos), 1)


class TestSemSenhaGuardada(BaseMotor):
    def test_modo_senha_sem_senha_entra_manualmente(self):
        """A tela avisa: 'sem a senha, o navegador abre na tela de entrada e
        você entra manualmente'. O motor tem de cumprir a promessa."""
        resumo = self.rodar([TJAL1], cofre=apoio.CofreFalso())
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)
        portal = apoio.PortalFalso.todos[0]
        nav = apoio.NavegadorFalso.instancias[0]
        self.assertEqual(portal.opcoes.modo_login("esaj"), "manual")
        self.assertTrue(nav.opcoes.navegador_visivel("esaj"), "o usuário precisa da janela")
        self.assertEqual(self.opcoes.modo_login("esaj"), "senha",
                         "a troca vale só para o grupo; as opções do lote ficam como estavam")

    def test_com_senha_guardada_continua_no_modo_senha(self):
        self.rodar([TJAL1], cofre=apoio.CofreFalso({"esaj:TJAL": ("u", "s")}))
        portal = apoio.PortalFalso.todos[0]
        self.assertEqual(portal.opcoes.modo_login("esaj"), "senha")
        self.assertFalse(apoio.NavegadorFalso.instancias[0].opcoes.navegador_visivel("esaj"))


class TestEventosParaATela(BaseMotor):
    def test_linha_em_curso_nao_volta_a_aguardando(self):
        """A tela marca 'baixando…' ao receber o progresso; um item com
        situação vazia logo depois a fazia voltar a 'aguardando'."""
        eventos = []
        ctx = self.ctx
        progresso_original, item_original = ctx.progresso, ctx.item
        ctx.progresso = lambda f, t, a: (eventos.append(("progresso", a)),
                                         progresso_original(f, t, a))
        ctx.item = lambda r: (eventos.append(("item", r.numero, r.situacao)), item_original(r))
        self.rodar([TJAL1, TJAL2])
        for numero in (TJAL1.formatado, TJAL2.formatado):
            inicio = eventos.index(("progresso", numero))
            depois = [e for e in eventos[inicio:] if e[0] == "item" and e[1] == numero]
            self.assertEqual(depois, [("item", numero, modelos.OK)], eventos)


class TestPreparoParaIA(BaseMotor):
    def test_preparo_chamado_ao_fim_e_nunca_derruba(self):
        chamadas = []
        falso = types.ModuleType("helestron.compartilhar.preparo")

        def atualizar_contexto(cfg, *a, **k):
            chamadas.append(cfg)
            raise RuntimeError("disco cheio")
        falso.atualizar_contexto = atualizar_contexto
        fp, fn = apoio.fabricas()
        opcoes = apoio.opcoes_de_teste(self.tmp, atualizar_ia=True)
        cfg = object()
        with mock.patch.dict(sys.modules, {"helestron.compartilhar.preparo": falso}):
            import helestron.compartilhar as pacote
            with mock.patch.object(pacote, "preparo", falso, create=True):
                resumo = motor.executar([TJAL1], self.destino, opcoes, self.ctx,
                                        fabrica_portal=fp, fabrica_navegador=fn, cfg=cfg)
        self.assertEqual(chamadas, [cfg])
        self.assertEqual(resumo.itens[0].situacao, modelos.OK)

    def test_parar_nao_espera_o_preparo(self):
        chamadas = []
        falso = types.ModuleType("helestron.compartilhar.preparo")
        falso.atualizar_contexto = lambda cfg, *a, **k: chamadas.append(cfg)
        fp, fn = apoio.fabricas({TJAL2.formatado: ["cancelar"]})
        opcoes = apoio.opcoes_de_teste(self.tmp, atualizar_ia=True)
        with mock.patch.dict(sys.modules, {"helestron.compartilhar.preparo": falso}):
            import helestron.compartilhar as pacote
            with mock.patch.object(pacote, "preparo", falso, create=True):
                resumo = motor.executar([TJAL1, TJAL2], self.destino, opcoes, self.ctx,
                                        fabrica_portal=fp, fabrica_navegador=fn, cfg=object())
        self.assertEqual(len(resumo.baixados), 1)
        self.assertEqual(chamadas, [], "depois de 'Parar' o programa fica livre na hora")

    def test_preparo_enxerga_o_parar_e_mostra_o_andamento(self):
        recebido = {}
        falso = types.ModuleType("helestron.compartilhar.preparo")

        def atualizar_contexto(cfg, *a, **k):
            self.assertFalse(k["cancelado"]())
            k["progresso"](0, 412, "texto de X")
            self.ctx.cancelar()            # "Parar" (ou fechar a janela) no meio do preparo
            recebido["parou"] = k["cancelado"]()
        falso.atualizar_contexto = atualizar_contexto
        fp, fn = apoio.fabricas()
        opcoes = apoio.opcoes_de_teste(self.tmp, atualizar_ia=True)
        with mock.patch.dict(sys.modules, {"helestron.compartilhar.preparo": falso}):
            import helestron.compartilhar as pacote
            with mock.patch.object(pacote, "preparo", falso, create=True):
                motor.executar([TJAL1], self.destino, opcoes, self.ctx,
                               fabrica_portal=fp, fabrica_navegador=fn, cfg=object())
        self.assertTrue(recebido["parou"], "o preparo precisa ver o pedido de parar")
        self.assertIn("Preparando os arquivos para a IA (0 de 412)...", self.ctx.status_)

    def test_sem_baixados_nao_prepara(self):
        chamadas = []
        falso = types.ModuleType("helestron.compartilhar.preparo")
        falso.atualizar_contexto = lambda cfg, *a, **k: chamadas.append(cfg)
        fp, fn = apoio.fabricas()
        opcoes = apoio.opcoes_de_teste(self.tmp, atualizar_ia=True)
        with mock.patch.dict(sys.modules, {"helestron.compartilhar.preparo": falso}):
            motor.executar([TJBA1], self.destino, opcoes, self.ctx,
                           fabrica_portal=fp, fabrica_navegador=fn, cfg=object())
        self.assertEqual(chamadas, [])


class TestOpcoes(apoio.PastaTemporaria):
    def test_de_config(self):
        from helestron.nucleo import config
        cfg = config.Config(self.tmp / "config.ini")
        op = modelos.OpcoesDownload.de_config(cfg)
        self.assertTrue(op.pular_baixados)
        self.assertTrue(op.separar_sigilosos)
        self.assertEqual(op.navegador, "auto")
        self.assertEqual(op.tentativas, 2)
        self.assertEqual(op.login, {"esaj": "senha", "eproc": "senha"})
        self.assertTrue(op.pasta_sigilosos.is_absolute())
        cfg.definir("esaj", "login", "Certificado")
        cfg.definir("eproc", "login", "qualquer coisa")
        cfg.definir("download", "tentativas", "0")
        cfg.definir("download", "pausa_entre_processos", "1,5")
        cfg.definir("download", "navegador", "MSEdge")
        op = modelos.OpcoesDownload.de_config(cfg)
        self.assertEqual(op.modo_login("esaj"), "certificado")
        self.assertEqual(op.modo_login("eproc"), "senha")
        self.assertEqual(op.tentativas, 1)
        self.assertEqual(op.pausa, 1.5)
        self.assertEqual(op.navegador, "msedge")
        self.assertTrue(op.navegador_visivel("esaj"))
        self.assertFalse(op.navegador_visivel("eproc"))

    def test_caminho_de_navegador(self):
        from helestron.nucleo import config
        exe = self.tmp / "chrome.exe"
        exe.write_bytes(b"MZ")
        cfg = config.Config(self.tmp / "config.ini")
        cfg.definir("download", "navegador", str(exe))
        op = modelos.OpcoesDownload.de_config(cfg)
        self.assertEqual(op.navegador, str(exe))
        from helestron.nucleo import tribunais
        nav = motor.fabrica_navegador_padrao(tribunais.por_sigla("TJAL"), op)
        self.assertEqual(nav.executavel, exe)
        cfg.definir("download", "navegador", str(self.tmp / "nao-existe.exe"))
        self.assertEqual(modelos.OpcoesDownload.de_config(cfg).navegador, "auto")


class TestResumo(unittest.TestCase):
    def test_texto_e_listas(self):
        R = modelos.ResultadoProcesso
        itens = [R(1, "a", "TJAL", "esaj", modelos.OK),
                 R(2, "b", "TJAL", "esaj", modelos.OK, sigiloso=True),
                 R(3, "c", "TJAL", "esaj", modelos.JA_BAIXADO),
                 R(4, "d", "TJAL", "esaj", modelos.ERRO),
                 R(5, "e", "TJAL", "esaj", modelos.CANCELADO)]
        resumo = modelos.ResumoLote(itens, destino=None, relatorio=None)
        self.assertEqual(len(resumo.baixados), 2)
        self.assertEqual(len(resumo.pulados), 1)
        self.assertEqual(len(resumo.falhas), 1)
        self.assertEqual(len(resumo.sigilosos), 1)
        self.assertEqual([r.numero for r in resumo.pendentes], ["e"])
        self.assertEqual(resumo.a_refazer(), ["d", "e"])
        texto = resumo.texto()
        self.assertIn("2 baixados", texto)
        self.assertIn("1 já estava na pasta", texto)
        self.assertIn("1 com problema", texto)
        self.assertIn("1 em segredo de justiça", texto)


if __name__ == "__main__":
    unittest.main()


class TestCatalogoDeTribunais(apoio.PastaTemporaria):
    """dados\\tribunais.json é editado à mão no Bloco de Notas."""

    def setUp(self):
        super().setUp()
        from helestron.nucleo import tribunais
        self.tribunais = tribunais
        self.original = tribunais.ARQUIVO.read_text(encoding="utf-8")

    def test_utf8_com_bom_e_ansi(self):
        com_bom = self.tmp / "bom.json"
        com_bom.write_bytes(b"\xef\xbb\xbf" + self.original.encode("utf-8"))
        ansi = self.tmp / "ansi.json"
        ansi.write_bytes(self.original.encode("cp1252", errors="replace"))
        total = len(self.tribunais.carregar())
        self.assertGreater(total, 0)
        for arquivo in (com_bom, ansi):
            self.assertEqual(len(self.tribunais.carregar(arquivo)), total, arquivo.name)
            self.assertEqual(self.tribunais.problema(arquivo), "")

    def test_catalogo_estragado_e_explicado_na_tela(self):
        ruim = self.tmp / "tribunais.json"
        ruim.write_text(self.original.replace('"tribunais"', '"tribunais",', 1), encoding="utf-8")
        with mock.patch.object(self.tribunais, "ARQUIVO", ruim), \
                self.assertLogs("helestron.nucleo.tribunais", "ERROR"):
            self.assertEqual(self.tribunais.carregar(), ())
            fp, fn = apoio.fabricas()
            resumo = motor.executar([TJAL1], self.tmp / "Processos" / "Lote",
                                    apoio.opcoes_de_teste(self.tmp), apoio.ContextoGravador(),
                                    fabrica_portal=fp, fabrica_navegador=fn)
        r = resumo.itens[0]
        self.assertEqual(r.situacao, modelos.NAO_SUPORTADO)
        self.assertIn("catálogo de tribunais", r.detalhe)
        self.assertIn("não pôde ser lido: erro de formatação na linha", r.detalhe)


class TestRotulosCitados(unittest.TestCase):
    """As mensagens do motor citam rótulos que existem na interface: na tela
    (helestron/web) ou nos campos de Ajustes que o servidor descreve
    (helestron/servidor/esquema.py). Um rótulo que mude lá e não aqui faz o
    usuário procurar uma opção que não existe."""

    def _textos_da_interface(self) -> str:
        pacote = Path(motor.__file__).resolve().parents[1]
        web = pacote / "web"
        arquivos = (sorted(web.rglob("*.js")) + sorted(web.rglob("*.html"))) if web.is_dir() else []
        if not arquivos:
            self.skipTest("a interface (helestron/web) ainda não existe")
        textos = [a.read_text(encoding="utf-8") for a in arquivos]
        esquema = pacote / "servidor" / "esquema.py"
        if esquema.is_file():
            textos.append(esquema.read_text(encoding="utf-8"))
        return "\n".join(textos)

    def test_rotulos(self):
        texto = self._textos_da_interface()
        for rotulo in modelos.ROTULOS_CITADOS:
            with self.subTest(rotulo=rotulo):
                self.assertIn(rotulo, texto)

    def test_rotulos_da_transcricao(self):
        """As mensagens da transcrição e da verificação citam o botão que
        baixa os modelos de voz e o grupo Transcrição de Ajustes."""
        from helestron.transcricao import falantes

        texto = self._textos_da_interface()
        for rotulo in (falantes.BOTAO_BAIXAR, "Transcrição", "Baixar"):
            with self.subTest(rotulo=rotulo):
                self.assertIn(rotulo, texto)
        self.assertIn(falantes.BOTAO_BAIXAR, falantes.ONDE_BAIXAR)

    def test_mensagens_montadas_com_os_rotulos(self):
        self.assertIn(f"“{modelos.PRAZO_LOGIN}”", modelos.CAMPO_PRAZO_LOGIN)
        self.assertTrue(modelos.CAMPO_PRAZO_LOGIN.startswith(modelos.AJUSTES_ACESSOS))
        self.assertIn(modelos.AJUSTES_ACESSOS, modelos.ONDE_CADASTRAR_ACESSO)
        self.assertEqual(modelos.AJUSTES_ACESSOS, "Ajustes › Acessos aos portais")
        self.assertIn("enderecos-locais.json", modelos.ONDE_CORRIGIR_ENDERECO)

    def test_nenhuma_mensagem_cita_a_tela_ou_o_instalador_antigos(self):
        # A versão anterior tinha a tela "Configurações" (Tk), a aba "Acesso"
        # da tela "Baixar processos" e o INSTALAR.bat: nada disso existe mais.
        pacote = Path(motor.__file__).resolve().parents[1]
        antigos = ("Configurações >", "INSTALAR.bat", "'Baixar processos'", "C:\\AssessorIntegrado",
                   "Preparar arquivos para IA", "Instalar o componente")
        for pasta in ("download", "transcricao", "compartilhar", "nucleo"):
            for arquivo in sorted((pacote / pasta).glob("*.py")):
                texto = arquivo.read_text(encoding="utf-8")
                for antigo in antigos:
                    with self.subTest(arquivo=arquivo.name, antigo=antigo):
                        self.assertFalse(antigo in texto, f"{pasta}/{arquivo.name} cita “{antigo}”")
        texto = (pacote / "verificar.py").read_text(encoding="utf-8")
        for antigo in antigos:
            self.assertFalse(antigo in texto, f"verificar.py cita “{antigo}”")

    def test_nada_do_programa_cita_o_assessor_integrado(self):
        """O pacote inteiro (código, interface, dados): nenhuma tela ou
        mensagem manda o usuário ao INSTALAR.bat, à tela "Configurações" do
        programa antigo ou ao componente que se instalava à parte. (O
        "Assessor Integrado" só aparece onde se removem os registros da
        versão anterior.)"""
        pacote = Path(motor.__file__).resolve().parents[1]
        antigos = ("INSTALAR.bat", "Configurações >", "AssessorIntegrado", "Instalar o componente",
                   "instalar o componente", "Configurações do Helestron", "tela de Configurações")
        permitidos = {"compartilhar/claude.py", "compartilhar/chatgpt.py", "compartilhar/nuvem.py",
                      "compartilhar/migracao.py", "verificar.py"}
        for arquivo in sorted(pacote.rglob("*")):
            if arquivo.suffix not in (".py", ".js", ".html", ".json", ".css") or \
                    "__pycache__" in arquivo.parts:
                continue
            relativo = arquivo.relative_to(pacote).as_posix()
            texto = arquivo.read_text(encoding="utf-8")
            for antigo in antigos:
                with self.subTest(arquivo=relativo, antigo=antigo):
                    self.assertNotIn(antigo, texto)
            if relativo not in permitidos:
                with self.subTest(arquivo=relativo, antigo="Assessor Integrado"):
                    self.assertNotIn("Assessor Integrado", texto)
