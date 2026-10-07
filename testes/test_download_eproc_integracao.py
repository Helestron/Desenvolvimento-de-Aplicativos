"""Ponta a ponta: Chromium de verdade contra um eProc de mentira, sem rede.

O eProc falso (testes/apoio_eproc.py) é servido pelo próprio navegador
(context.route): login legado com segundo fator (código errado e depois o
certo), Keycloak, captcha, escolha de perfil, pesquisa rápida, consulta
processual por ajax, processo com duas páginas de eventos e documentos em
PDF, HTML ISO-8859-1, JPEG e vídeo, um documento que só vem pela moldura,
um que não vem de jeito nenhum, um processo sigiloso sem acesso, um
inexistente, a sessão que cai no meio do download e o Download Completo.

Pula sozinho se não houver Chromium que abra (no CI do Windows, o Chrome
ou o Edge instalados; aqui, o Chromium de /opt/pw-browsers).
"""

from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from unittest import mock

from helestron.download import eproc, modelos, motor
from helestron.download.eproc import PortalEProc
from helestron.nucleo import paginacao, tribunais

from testes import apoio_download as apoio
from testes import apoio_eproc as ae


class TestEProcDeMentira(apoio.PastaTemporaria):

    @classmethod
    def setUpClass(cls):
        if ae.navegador_de_teste() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")

    def setUp(self):
        super().setUp()
        for alvo, nome, valor in ((eproc, "PAUSA_DOCUMENTOS_S", 0),
                                  (eproc, "INTERVALO_COMPLETO_S", 0.3),
                                  (motor, "ESPERA_ENTRE_TENTATIVAS_S", 0.0)):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)
        self.tribunal = replace(tribunais.por_sigla("TJRS"), urls={"1g": [ae.BASE]})

    # ------------------------------------------------------------ apoio
    def opcoes(self, **mudar):
        base = dict(espera_s=20, espera_login_min=1)
        base.update(mudar)
        return apoio.opcoes_de_teste(self.tmp, **base)

    def portal(self, nav, ctx, credenciais=(ae.USUARIO, ae.SENHA), tribunal=None, opcoes=None,
               **extra):
        return PortalEProc(nav, tribunal or self.tribunal, opcoes or self.opcoes(), ctx,
                           credenciais, seletores=eproc.SELETORES_PADRAO, **extra)

    def fabricas(self, falso, nome="eproc-TJRS"):
        def fabrica_navegador(tribunal, opcoes):
            return ae.navegador(falso, self.tmp, nome)

        def fabrica_portal(nav, tribunal, opcoes, ctx, credenciais):
            self.assertEqual(tribunal.sistema, "eproc")
            return PortalEProc(nav, self.tribunal, opcoes, ctx, credenciais,
                               seletores=eproc.SELETORES_PADRAO)
        return fabrica_portal, fabrica_navegador

    @staticmethod
    def paginas(caminho):
        import pymupdf
        with pymupdf.open(str(caminho)) as doc:
            return doc.get_toc(), [p.get_text() for p in doc], [len(p.get_images()) for p in doc]

    @staticmethod
    def acabamento(caminho):
        """Os rótulos de página, os metadados e o manifesto de paginação do PDF."""
        import pymupdf
        with pymupdf.open(str(caminho)) as doc:
            return [p.get_label() for p in doc], dict(doc.metadata), paginacao.ler_do_doc(doc)

    @staticmethod
    def capa(pasta, numero):
        controle = pasta / "_controle"
        return ((controle / f"{numero.nome_arquivo}_capa.txt").read_text("utf-8"),
                json.loads((controle / f"{numero.nome_arquivo}_capa.json").read_text("utf-8")))

    # ------------------------------------------------- o lote pelo motor
    def test_lote_pelo_motor_e_segunda_rodada(self):
        falso = ae.EProcFalso()
        destino = self.tmp / "Acervo" / "Processos" / "Pauta"
        opcoes = self.opcoes(tentativas=2, baixar_midias=True)
        ctx = apoio.ContextoGravador(codigos=["000000", ae.CODIGO, ae.CODIGO])
        cofre = apoio.CofreFalso({"eproc:TJRS": (ae.USUARIO, ae.SENHA)})
        fp, fn = self.fabricas(falso)
        lista = [ae.P1, ae.P_SIG, ae.P_NAO, ae.P_CONS, ae.P_SIGOK, ae.P_EXP]
        resumo = motor.executar(lista, destino, opcoes, ctx, cofre=cofre,
                                fabrica_portal=fp, fabrica_navegador=fn)
        r = {x.numero: x for x in resumo.itens}

        # login: o primeiro código foi recusado, o segundo aceito; a sessão que
        # caiu no P_EXP pediu um terceiro
        self.assertEqual(falso.codigos_recebidos, ["000000", ae.CODIGO, ae.CODIGO])
        self.assertEqual(len(ctx.pedidos_codigo), 3)
        self.assertEqual(ctx.pedidos_codigo[0][0], "Código do autenticador")
        self.assertIn("aplicativo autenticador", ctx.pedidos_codigo[0][1])
        self.assertIn("não aceitou", ctx.pedidos_codigo[1][1])
        self.assertEqual(ctx.reenviaveis, [False] * 3,
                         "não existe 'pedir novo código' para o autenticador")
        self.assertEqual(falso.logins, 2)
        # nenhum link montado à mão: todo endereço interno veio da sessão
        self.assertEqual(falso.sem_assinatura, [])

        # P1: duas páginas de eventos, do mais antigo ao mais novo
        r1 = r[ae.P1.formatado]
        self.assertEqual(r1.situacao, modelos.OK, r1.detalhe)
        self.assertEqual(r1.sistema, "eproc")
        self.assertEqual(r1.documentos, 7)
        self.assertEqual(r1.paginas, 8, "só as páginas dos documentos: nenhuma capa")
        self.assertEqual(r1.incompleto, "ev. 4 PET1")
        self.assertIn("1 documento não veio e tem página de aviso no lugar", r1.detalhe)
        self.assertIn("1 gravação salva", r1.detalhe)
        self.assertFalse(r1.sigiloso, "'Sem Sigilo (Nível 0)' não é sigilo")
        self.assertIn(f"{ae.P1.digitos}:1", falso.paginas_pedidas)
        pdf1 = destino / f"{ae.P1.nome_arquivo}.pdf"
        toc, textos, imagens = self.paginas(pdf1)
        self.assertEqual(toc, [
            [1, "Evento 1 — PETIÇÃO INICIAL — INIC1 (10/01/2024)", 1],
            [1, "Evento 1 — PETIÇÃO INICIAL — PROC2 (10/01/2024)", 3],
            [1, "Evento 2 — JUNTADA DE DOCUMENTO — FOTO1 (11/01/2024)", 4],
            [1, "Evento 3 — DECISÃO INTERLOCUTÓRIA — DESPADEC1 (12/03/2024)", 5],
            [1, "Evento 4 — JUNTADA DE PETIÇÃO — PET1 (20/03/2024) [NÃO INCLUÍDO]", 6],
            [1, "Evento 6 — SENTENÇA — SENT1 (10/05/2024)", 7],
            [1, "Evento 7 — GRAVAÇÃO DE AUDIÊNCIA — VIDEO1 (15/05/2024) "
                "[GRAVAÇÃO — fora do PDF]", 8]])
        self.assertIn("INIC1 1", textos[0], "a página 1 é a p. 1 da petição inicial")
        self.assertIn("INIC1 2", textos[1])
        self.assertIn("PROC2 1", textos[2])           # só pela moldura (iframe)
        self.assertGreater(imagens[3], 0)              # a foto (JPEG) virou página
        self.assertIn("DECISÃO", textos[4])            # HTML em ISO-8859-1, acentos certos
        self.assertIn("Citação e intimação", textos[4])
        self.assertIn("não pôde ser baixado", textos[5])
        self.assertIn("não é página dos autos", " ".join(textos[5].split()))
        self.assertIn("SENTENÇA", textos[6])
        self.assertIn("condenação em custas — publique-se", textos[6])
        self.assertIn("salvo em", textos[7])
        rotulos, meta, m1 = self.acabamento(pdf1)
        self.assertEqual(rotulos, ["Ev. 1 INIC1 p. 1", "Ev. 1 INIC1 p. 2", "Ev. 1 PROC2 p. 1",
                                   "Ev. 2 FOTO1 p. 1", "Ev. 3 DESPADEC1", "Ev. 4 PET1 nao incluido",
                                   "Ev. 6 SENT1", "Ev. 7 VIDEO1 gravacao"])
        self.assertIn("sistema=eproc", meta["keywords"])
        self.assertIn("modo=documentos", meta["keywords"])
        self.assertEqual(meta["title"], f"Processo {ae.P1.formatado}")
        self.assertEqual((m1["sistema"], m1["paginacao"], m1["modo"]),
                         ("eproc", "documento", "documentos"))
        self.assertEqual([(d["rotulo"], d["inicio"], d["paginas"], d["situacao"])
                          for d in m1["documentos"]],
                         [("INIC1", 1, 2, "ok"), ("PROC2", 3, 1, "ok"), ("FOTO1", 4, 1, "ok"),
                          ("DESPADEC1", 5, 1, "ok"), ("PET1", 6, 1, "ausente"),
                          ("SENT1", 7, 1, "ok"), ("VIDEO1", 8, 1, "midia")])
        self.assertEqual([d["origem"] for d in m1["documentos"]],
                         ["pdf", "pdf", "imagem", "html", "pdf", "html", "midia"])
        self.assertIn("HTTP", m1["documentos"][4]["motivo"])
        self.assertEqual(m1["documentos"][6]["arquivo"],
                         f"_controle/midias/{ae.P1.nome_arquivo}/Evento 7 - VIDEO1.mp4")
        self.assertEqual(m1["capa"]["classe"], "PROCEDIMENTO COMUM CÍVEL")
        self.assertEqual(m1["capa"]["partes"], ["AUTOR: MARIA DA SILVA", "RÉU: BANCO EXEMPLO S.A."])
        self.assertEqual(m1["eventos_sem_documento"],
                         [{"evento": 5, "descricao": "AUDIÊNCIA REALIZADA", "data": "01/04/2024"}])
        self.assertEqual(r1.paginacao.get("ultima"), 8)
        midia = destino / "_controle" / "midias" / ae.P1.nome_arquivo / "Evento 7 - VIDEO1.mp4"
        self.assertTrue(midia.exists())
        self.assertEqual(r1.midias, [str(midia)])
        # a capa que estava no PDF foi para o capa.txt (e o capa.json)
        capa_txt, capa_json = self.capa(destino, ae.P1)
        for trecho in (f"Processo {ae.P1.formatado} - eProc do TJRS",
                       "Classe: PROCEDIMENTO COMUM CÍVEL",
                       "Órgão julgador: Juízo da 1ª Vara Cível de Porto Alegre",
                       "AUTOR: MARIA DA SILVA", "RÉU: BANCO EXEMPLO S.A.",
                       "Eventos: 7; documentos: 7; páginas do PDF: 8.",
                       "Documentos não incluídos (1): ev. 4 PET1", "== Como citar ==",
                       "== Mapa de documentos (7) ==",
                       "Evento 1 — PETIÇÃO INICIAL — INIC1 (10/01/2024) — págs. 1–2 do PDF "
                       "(2 págs.; p. 1–2 no eProc)",
                       "Evento 7 — GRAVAÇÃO DE AUDIÊNCIA — VIDEO1 (15/05/2024) — pág. 8 do PDF",
                       "Evento 7 - GRAVAÇÃO DE AUDIÊNCIA [VIDEO1]"):
            self.assertIn(trecho, capa_txt)
        self.assertEqual((capa_json["sistema"], len(capa_json["documentos"]),
                          len(capa_json["eventos"])), ("eproc", 7, 7))

        # sigiloso sem acesso, inexistente, achado só pela consulta processual
        r_sig = r[ae.P_SIG.formatado]
        self.assertEqual(r_sig.situacao, modelos.SEM_ACESSO, r_sig.detalhe)
        self.assertTrue(r_sig.sigiloso)
        self.assertIn("segredo de justiça", r_sig.detalhe)
        r_nao = r[ae.P_NAO.formatado]
        self.assertEqual(r_nao.situacao, modelos.NAO_ENCONTRADO)
        self.assertIn("não encontrado no 1º grau do eProc do TJRS", r_nao.detalhe)
        r_cons = r[ae.P_CONS.formatado]
        self.assertEqual(r_cons.situacao, modelos.OK, r_cons.detalhe)
        self.assertEqual(r_cons.paginas, 1)
        self.assertTrue(any("controlador_ajax.php" in u for _, u in falso.pedidos))

        # sigiloso com acesso: baixado e levado para fora do acervo
        r_sigok = r[ae.P_SIGOK.formatado]
        self.assertEqual(r_sigok.situacao, modelos.OK, r_sigok.detalhe)
        self.assertTrue(r_sigok.sigiloso)
        sig = self.tmp / "Sigilosos" / "Pauta"
        self.assertTrue((sig / f"{ae.P_SIGOK.nome_arquivo}.pdf").exists())
        self.assertFalse((destino / f"{ae.P_SIGOK.nome_arquivo}.pdf").exists())
        self.assertTrue((sig / "_controle" / f"{ae.P_SIGOK.nome_arquivo}_capa.txt").exists())
        capa_sig, json_sig = self.capa(sig, ae.P_SIGOK)
        self.assertIn("SEGREDO DE JUSTIÇA", capa_sig[:2000])
        self.assertTrue(json_sig["sigiloso"])
        self.assertFalse((destino / "_controle" / f"{ae.P_SIGOK.nome_arquivo}_capa.json").exists())
        self.assertTrue(paginacao.ler_do_pdf(sig / f"{ae.P_SIGOK.nome_arquivo}.pdf")["sigiloso"],
                        "o manifesto vai com o PDF para a pasta de sigilosos")

        # a sessão caiu no 2º documento do P_EXP: novo login e o processo inteiro de novo
        r_exp = r[ae.P_EXP.formatado]
        self.assertEqual(r_exp.situacao, modelos.OK, r_exp.detalhe)
        self.assertEqual(r_exp.paginas, 3)
        toc, textos, _ = self.paginas(destino / f"{ae.P_EXP.nome_arquivo}.pdf")
        self.assertEqual([t[1].split(" — ")[-1] for t in toc],
                         ["INIC1 (07/02/2024)", "CONT1 (08/02/2024)", "REPLICA1 (09/02/2024)"])

        self.assertTrue((destino / "_controle" / "relatorio.csv").exists())
        self.assertEqual(sorted(p.name for p in destino.iterdir() if p.is_file()),
                         sorted(f"{n.nome_arquivo}.pdf" for n in (ae.P1, ae.P_CONS, ae.P_EXP)))

        # segunda rodada: a sessão guardada dispensa o login, e o que já tem é pulado
        ctx2 = apoio.ContextoGravador(codigos=[])
        fp, fn = self.fabricas(falso)
        resumo2 = motor.executar(lista, destino, opcoes, ctx2, cofre=cofre,
                                 fabrica_portal=fp, fabrica_navegador=fn)
        self.assertEqual(ctx2.pedidos_codigo, [], "a sessão guardada dispensa o código")
        sit = {x.numero: x.situacao for x in resumo2.itens}
        self.assertEqual(sit[ae.P1.formatado], modelos.JA_BAIXADO)
        self.assertEqual(sit[ae.P_SIGOK.formatado], modelos.JA_BAIXADO)
        self.assertEqual(sit[ae.P_SIG.formatado], modelos.SEM_ACESSO)
        self.assertEqual(sit[ae.P_NAO.formatado], modelos.NAO_ENCONTRADO)
        self.assertEqual(falso.logins, 2)

    # ------------------------------------------------------- sessão
    def test_sessao_que_cai_no_meio_vira_sessao_perdida(self):
        falso = ae.EProcFalso()
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO, ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P_EXP.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx)
            portal.entrar()
            with self.assertRaises(modelos.SessaoPerdida):
                portal.baixar(ae.P_EXP, alvo)
            self.assertFalse(alvo.exists())
            self.assertFalse(alvo.with_name(alvo.name + ".parcial").exists())
            portal.entrar()                 # o que o motor faz
            r = portal.baixar(ae.P_EXP, alvo)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual(len(ctx.pedidos_codigo), 2)

    def test_cancelar_entre_documentos(self):
        falso = ae.EProcFalso()

        class Parar(apoio.ContextoGravador):
            def status(self, texto):
                super().status(texto)
                if "documento 2 de" in texto:
                    self.cancelar()

        ctx = Parar(codigos=[ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P1.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx)
            portal.entrar()
            with self.assertRaises(modelos.Cancelado):
                portal.baixar(ae.P1, alvo)
        self.assertFalse(alvo.exists())
        self.assertFalse(list((self.tmp / "out").glob("*.parcial")) if (self.tmp / "out").exists()
                         else [])
        pedidos_de_documento = [u for _, u in falso.pedidos if "acessar_documento" in u]
        self.assertLessEqual(len(pedidos_de_documento), 3, "parou logo depois do 2º documento")

    # ------------------------------------------------------------ login
    def test_senha_errada_e_avisada_sem_pedir_codigo(self):
        falso = ae.EProcFalso()
        ctx = apoio.ContextoGravador()
        with ae.navegador(falso, self.tmp, "eproc-senha-errada") as nav:
            portal = self.portal(nav, ctx, (ae.USUARIO, "errada"))
            inicio = time.monotonic()
            with self.assertRaises(modelos.LoginFalhou) as caso:
                portal.entrar()
            demora = time.monotonic() - inicio
        self.assertIn("recusou o usuário ou a senha", str(caso.exception))
        self.assertLess(demora, 20)
        self.assertEqual(ctx.pedidos_codigo, [])
        self.assertTrue(list((self.tmp / "diagnostico").glob("*eproc-login-recusado*.html")))

    def test_codigo_nao_informado(self):
        falso = ae.EProcFalso()
        ctx = apoio.ContextoGravador(codigos=[])
        with ae.navegador(falso, self.tmp) as nav:
            with self.assertRaises(modelos.LoginFalhou) as caso:
                self.portal(nav, ctx).entrar()
        self.assertIn("código do aplicativo autenticador não foi informado", str(caso.exception))
        self.assertEqual(len(ctx.pedidos_codigo), 1)

    def test_codigo_digitado_na_janela_sem_terminal(self):
        """Sem terminal (a skill: pedir_codigo devolve None na hora) e com a
        janela à vista, o código digitado no campo do próprio eProc conclui o
        login; antes, o login desistia em 0 s."""
        falso = ae.EProcFalso()
        portal = None

        class NaJanela(apoio.ContextoGravador):
            def avisar(self, titulo, mensagem):
                super().avisar(titulo, mensagem)
                if titulo.startswith("Digite o código na janela"):
                    # o que o usuário faz na janela do navegador
                    campo = portal._visivel("otp_campo", espera_ms=3000)
                    campo.fill(ae.CODIGO)
                    campo.press("Enter")

        ctx = NaJanela(codigos=[])
        with ae.navegador(falso, self.tmp, "eproc-codigo-na-janela") as nav:
            nav.visivel = True              # o eProc abre sempre com a janela (motor)
            portal = self.portal(nav, ctx)
            portal.entrar()
            self.assertTrue(portal._logado)
        self.assertEqual(falso.codigos_recebidos, [ae.CODIGO])
        self.assertEqual(len(ctx.pedidos_codigo), 1)
        self.assertEqual([t for t, _ in ctx.avisos],
                         ["Digite o código na janela do eProc do TJRS"])

    def test_keycloak_com_codigo(self):
        falso = ae.EProcFalso(estilo="keycloak")
        ctx = apoio.ContextoGravador(codigos=["999999", ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P_CONS.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp, "eproc-keycloak") as nav:
            portal = self.portal(nav, ctx)
            portal.entrar()
            r = portal.baixar(ae.P_CONS, alvo)
        self.assertEqual(falso.codigos_recebidos, ["999999", ae.CODIGO])
        self.assertTrue(any(ae.HOST_SSO in u for _, u in falso.pedidos))
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual(r.paginas, 1)

    def test_keycloak_senha_errada(self):
        falso = ae.EProcFalso(estilo="keycloak")
        ctx = apoio.ContextoGravador()
        with ae.navegador(falso, self.tmp, "eproc-keycloak-errada") as nav:
            with self.assertRaises(modelos.LoginFalhou) as caso:
                self.portal(nav, ctx, (ae.USUARIO, "errada")).entrar()
        self.assertIn("recusou o usuário ou a senha", str(caso.exception))
        self.assertEqual(ctx.pedidos_codigo, [])

    def test_captcha_com_a_janela_oculta(self):
        falso = ae.EProcFalso(captcha=True)
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        with ae.navegador(falso, self.tmp) as nav:
            with self.assertRaises(modelos.LoginFalhou) as caso:
                self.portal(nav, ctx).entrar()
        self.assertIn("captcha", str(caso.exception))
        self.assertIn("Mostrar o navegador enquanto baixa", str(caso.exception))

    def test_perfil_unico_e_escolhido_sozinho(self):
        falso = ae.EProcFalso(perfis=["JUIZ"])
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx)
            portal.entrar()
            r = portal.baixar(ae.P_CONS, self.tmp / "out" / "x.pdf")
        self.assertEqual(falso.perfil_escolhido, ["10"])
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)

    def test_varios_perfis(self):
        # sem janela e sem perfil configurado: explica; com perfil configurado: escolhe
        falso = ae.EProcFalso(perfis=["JUIZ", "DIRETOR DE SECRETARIA"])
        with ae.navegador(falso, self.tmp, "eproc-perfis") as nav:
            with self.assertRaises(modelos.LoginFalhou) as caso:
                self.portal(nav, apoio.ContextoGravador(codigos=[ae.CODIGO])).entrar()
        self.assertIn("mais de um perfil", str(caso.exception))
        self.assertIn("DIRETOR DE SECRETARIA", str(caso.exception))
        opcoes = self.opcoes()
        opcoes.perfil_eproc = "diretor de secretaria"
        with ae.navegador(falso, self.tmp, "eproc-perfis-2") as nav:
            self.portal(nav, apoio.ContextoGravador(codigos=[ae.CODIGO]), opcoes=opcoes).entrar()
        self.assertEqual(falso.perfil_escolhido, ["11"])

    def test_enderecos_candidatos(self):
        falso = ae.EProcFalso()
        fora = f"https://{ae.HOST_FORA}/eproc/"
        tribunal = replace(self.tribunal, urls={"1g": [fora, ae.BASE]})
        with ae.navegador(falso, self.tmp) as nav:
            with self.assertLogs("download.eproc", "INFO") as logs:
                portal = self.portal(nav, apoio.ContextoGravador(codigos=[ae.CODIGO]),
                                     tribunal=tribunal)
                portal.entrar()
        texto = "\n".join(logs.output)
        self.assertIn(f"{fora} não respondeu", texto)
        self.assertIn(f"usando o endereço {ae.BASE}", texto)
        self.assertEqual(portal.base, ae.BASE)

        so_fora = replace(self.tribunal, urls={"1g": [fora]})
        with ae.navegador(falso, self.tmp, "eproc-fora") as nav:
            with self.assertRaises(modelos.PortalIndisponivel) as caso:
                self.portal(nav, apoio.ContextoGravador(), tribunal=so_fora).entrar()
        self.assertIn(fora, str(caso.exception))
        self.assertIn("enderecos-locais.json", str(caso.exception))

    # ------------------------------------------------- Download Completo
    def test_download_completo(self):
        falso = ae.EProcFalso()
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P1.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx, modo="completo")
            portal.entrar()
            r = portal.baixar(ae.P1, alvo)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertIn("PDF completo gerado pelo próprio eProc", r.detalhe)
        # o relacionado foi desmarcado: com dois marcados, o eProc dá erro
        self.assertEqual(falso.completo_marcados, [[f"RS|{ae.P1.digitos}|111"]])
        toc, textos, _ = self.paginas(alvo)
        # o arquivo do eProc entra como veio: a página M é a página M dele
        self.assertEqual([t[1] for t in toc], ["Autos completos (arquivo gerado pelo eProc)"])
        self.assertEqual(r.paginas, 5)
        self.assertEqual([t.strip() for t in textos], [f"COMPLETO {i}" for i in range(1, 6)])
        _, meta, m = self.acabamento(alvo)
        self.assertIn("modo=completo", meta["keywords"])
        self.assertEqual((m["modo"], m["partes"], m["documentos"]),
                         ("completo", [{"inicio": 1, "paginas": 5}], []))
        # a lista inteira de eventos foi lida antes (as duas páginas), para a capa
        self.assertEqual(r.documentos, 7)
        self.assertEqual([e["evento"] for e in m["eventos_sem_documento"]], [5])
        capa_txt, capa_json = self.capa(alvo.parent, ae.P1)
        self.assertIn("Download Completo", capa_txt)
        self.assertIn("a página M do PDF é a página M desse arquivo", capa_txt)
        self.assertIn("== Eventos (7) ==", capa_txt)
        self.assertIn("== Mapa de documentos (7) ==", capa_txt)
        self.assertEqual((capa_json["modo"], capa_json["paginas_pdf"]), ("completo", 5))

    def test_download_completo_que_falha_cai_para_documentos(self):
        falso = ae.EProcFalso()
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P_CONS.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx, modo="completo")
            portal.entrar()
            r = portal.baixar(ae.P_CONS, alvo)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertIn("o Download Completo do eProc falhou", r.detalhe)
        self.assertIn("montado documento a documento", r.detalhe)
        self.assertEqual(r.paginas, 1)
        self.assertEqual(r.documentos, 1)


    # ------------------------------------------------------ regressões
    # Defeitos achados na revisão; cada teste falhava antes da correção.
    def test_sigiloso_nivel_2_com_capa_em_blocos(self):
        # "Nível de Sigilo do Processo:" e "Sigiloso (Nível 2)" em elementos
        # separados: passava por público, e o PDF ficava no acervo da IA
        falso = ae.EProcFalso()
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx)
            portal.entrar()
            r = portal.baixar(ae.P_SIG2, self.tmp / "out" / f"{ae.P_SIG2.nome_arquivo}.pdf")
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertTrue(r.sigiloso)

    def test_painel_de_magistrado_nao_e_recusa_de_login(self):
        falso = ae.EProcFalso(painel_extra=(
            "<p><a href='#'>Alterar senha</a></p><table class='infraTable'><tr><td>"
            "5000500-11.2024.8.21.0001</td><td>Bloqueio SISBAJUD - conta bloqueada</td></tr>"
            "<tr><td>5000600-22.2024.8.21.0001</td><td>Procuração inválida</td></tr></table>"))
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx)
            portal.entrar()
            r = portal.baixar(ae.P_CONS, self.tmp / "out" / f"{ae.P_CONS.nome_arquivo}.pdf")
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual(falso.logins, 1)

    def test_tela_que_nao_responde_nao_vira_nao_encontrado(self):
        # Pesquisa rápida que não responde, com o "Nenhum registro encontrado"
        # de uma tabela vazia do painel na tela, e consulta processual que não
        # conclui: era NAO_ENCONTRADO (definitivo, sem nova tentativa) para um
        # processo que existe.
        falso = ae.EProcFalso(rapida_inerte=True, consulta_quebrada=True)
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P1.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp, espera_s=5) as nav:
            portal = self.portal(nav, ctx, opcoes=self.opcoes(espera_s=5))
            portal.entrar()
            with self.assertRaises(RuntimeError) as caso:
                portal.baixar(ae.P1, alvo)
        self.assertNotIsInstance(caso.exception, modelos.ProcessoNaoEncontrado)
        self.assertIn("consulta processual", str(caso.exception))

    def test_download_completo_ignora_arquivo_de_outro_processo(self):
        falso = ae.EProcFalso(completo_outros=True)
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P1.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx, modo="completo")
            portal.entrar()
            r = portal.baixar(ae.P1, alvo)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertIn("PDF completo gerado pelo próprio eProc", r.detalhe)
        _, textos, _ = self.paginas(alvo)
        self.assertEqual(r.paginas, 5)
        self.assertFalse(any("OUTRO PROCESSO" in t for t in textos), "autos trocados no PDF")

    def test_cancelar_depois_de_salvar_gravacao_nao_deixa_midia_solta(self):
        falso = ae.EProcFalso()

        class Parar(apoio.ContextoGravador):
            def status(self, texto):
                super().status(texto)
                if "documento 2 de" in texto:
                    self.cancelar()

        ctx = Parar(codigos=[ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P_MID.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx, opcoes=self.opcoes(baixar_midias=True))
            portal.entrar()
            with self.assertRaises(modelos.Cancelado):
                portal.baixar(ae.P_MID, alvo)
        self.assertFalse(alvo.exists())
        pasta = self.tmp / "out" / "_controle" / "midias" / ae.P_MID.nome_arquivo
        self.assertFalse(pasta.exists() and any(pasta.iterdir()),
                         "gravação de processo não baixado ficou no acervo")

    def test_paginacao_nao_lida_fica_no_incompleto(self):
        # Paginação que o programa não reconhece: só a página 1 (eventos 7 a
        # 4) era lida, e os autos saíam sem a inicial como se estivessem
        # completos.
        falso = ae.EProcFalso()
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        sel = dict(eproc.SELETORES_PADRAO, eventos_paginacao=["#paginacaoQueNaoExiste"])
        alvo = self.tmp / "out" / f"{ae.P1.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = PortalEProc(nav, self.tribunal, self.opcoes(), ctx, (ae.USUARIO, ae.SENHA),
                                 seletores=sel)
            portal.entrar()
            r = portal.baixar(ae.P1, alvo)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual(r.incompleto, "eventos 1 a 3 (não listados); ev. 4 PET1")
        self.assertIn("os eventos 1 a 3 não apareceram", r.detalhe)
        # sem capa no PDF: o aviso está no capa.txt e no manifesto
        capa_txt, _ = self.capa(alvo.parent, ae.P1)
        self.assertIn("os eventos 1 a 3 não apareceram", capa_txt)
        _, _, m = self.acabamento(alvo)
        self.assertEqual(m["eventos_nao_listados"], "1 a 3")

    def test_paginacao_sem_onchange_usa_a_funcao_do_eproc(self):
        falso = ae.EProcFalso(paginacao_sem_onchange=True)
        ctx = apoio.ContextoGravador(codigos=[ae.CODIGO])
        alvo = self.tmp / "out" / f"{ae.P1.nome_arquivo}.pdf"
        with ae.navegador(falso, self.tmp) as nav:
            portal = self.portal(nav, ctx)
            portal.entrar()
            r = portal.baixar(ae.P1, alvo)
        self.assertEqual(r.situacao, modelos.OK, r.detalhe)
        self.assertEqual(r.documentos, 7)
        self.assertEqual(r.incompleto, "ev. 4 PET1")
        self.assertIn(f"{ae.P1.digitos}:1", falso.paginas_pedidas)


if __name__ == "__main__":
    unittest.main()
