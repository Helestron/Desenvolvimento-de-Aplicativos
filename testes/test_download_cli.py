"""Linha de comando do download e o acompanhamento pelo terminal."""

from __future__ import annotations

import io
import json
import logging
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from helestron.download import cli, modelos, motor
from helestron.download.contexto import Contexto, ContextoTerminal
from helestron.nucleo import caminhos, config

from testes import apoio_download as apoio

A = apoio.numero("0700001", tr="02")
B = apoio.numero("0700002", tr="02")
C = apoio.numero("0700003", tr="02")
D = apoio.numero("0700004", tr="02")
E = apoio.numero("0700005", tr="02")


class TestContextoTerminal(unittest.TestCase):
    def test_codigo_digitado(self):
        saida = io.StringIO()
        ctx = ContextoTerminal(saida=saida, entrada=lambda prompt: " 123456 ")
        self.assertEqual(ctx.pedir_codigo("Código", "Veja o e-mail."), "123456")
        self.assertIn("Veja o e-mail.", saida.getvalue())

    def test_enter_em_branco_pede_outro_e_sair_cancela(self):
        ctx = ContextoTerminal(saida=io.StringIO(), entrada=lambda p: "")
        self.assertEqual(ctx.pedir_codigo("t", "m"), "")
        ctx = ContextoTerminal(saida=io.StringIO(), entrada=lambda p: "sair")
        self.assertIsNone(ctx.pedir_codigo("t", "m"))

    def test_codigo_do_autenticador_nao_oferece_pedir_outro(self):
        # O aplicativo autenticador (eProc) muda sozinho: "Enter em branco
        # pede outro" seria oferecer o que não existe.
        convites = []
        ctx = ContextoTerminal(saida=io.StringIO(),
                               entrada=lambda p: convites.append(p) or "654321")
        self.assertEqual(ctx.pedir_codigo("Código do autenticador", "Digite.", 60,
                                          reenviavel=False), "654321")
        self.assertNotIn("pede outro", convites[0])
        self.assertIn("'sair' cancela", convites[0])
        # o do e-mail (e-SAJ), padrão, continua oferecendo
        ctx = ContextoTerminal(saida=io.StringIO(),
                               entrada=lambda p: convites.append(p) or "111")
        ctx.pedir_codigo("Código do e-SAJ", "Veja o e-mail.")
        self.assertIn("Enter em branco pede outro", convites[1])

    def test_assinatura_compativel_com_a_tela(self):
        # Os portais passam 'reenviavel' por nome; todo Contexto precisa aceitá-lo.
        import inspect
        from helestron.tarefas import ContextoTela
        for classe in (Contexto, ContextoTerminal, ContextoTela, apoio.ContextoGravador):
            with self.subTest(classe=classe.__name__):
                self.assertIn("reenviavel", inspect.signature(classe.pedir_codigo).parameters)
        self.assertIsNone(Contexto().pedir_codigo("t", "m", 60, reenviavel=False))

    def test_sem_teclado_nao_trava(self):
        def sem_teclado(prompt):
            raise EOFError
        ctx = ContextoTerminal(saida=io.StringIO(), entrada=sem_teclado)
        self.assertIsNone(ctx.pedir_codigo("t", "m"))

    def test_ctrl_c_no_codigo_para_o_lote(self):
        def ctrl_c(prompt):
            raise KeyboardInterrupt
        ctx = ContextoTerminal(saida=io.StringIO(), entrada=ctrl_c)
        self.assertIsNone(ctx.pedir_codigo("t", "m"))
        self.assertTrue(ctx.cancelado(), "Ctrl+C é 'parar', não 'não tenho o código'")

    def test_sem_terminal_nao_espera_input(self):
        ctx = ContextoTerminal(saida=io.StringIO())
        with mock.patch("sys.stdin", io.StringIO("")):
            self.assertIsNone(ctx.pedir_codigo("t", "m"))

    def test_item_e_parar(self):
        saida = io.StringIO()
        ctx = ContextoTerminal(saida=saida)
        r = modelos.ResultadoProcesso(1, A.formatado, "TJAL", "esaj", modelos.OK, paginas=12,
                                      sigiloso=True)
        ctx.item(r)
        self.assertIn("baixado (12 páginas; sigiloso)", saida.getvalue())
        self.assertFalse(ctx.cancelado())
        ctx.parar()
        self.assertTrue(ctx.cancelado())

    def test_faltantes_no_eproc_sao_documentos_e_no_esaj_folhas(self):
        saida = io.StringIO()
        ctx = ContextoTerminal(saida=saida)
        ctx.item(modelos.ResultadoProcesso(1, A.formatado, "TJRS", "eproc", modelos.OK,
                                           incompleto="ev. 4 PET1"))
        ctx.item(modelos.ResultadoProcesso(2, B.formatado, "TJAL", "esaj", modelos.OK,
                                           incompleto="6-7"))
        linhas = saida.getvalue().splitlines()
        self.assertIn("documentos ausentes: ev. 4 PET1", linhas[0])
        self.assertNotIn("folhas", linhas[0])
        self.assertIn("folhas ausentes: 6-7", linhas[1])

    def test_contexto_base_nao_faz_nada_e_nao_cancela(self):
        ctx = Contexto()
        ctx.status("x")
        ctx.progresso(1, 2, "y")
        self.assertIsNone(ctx.evento("grupo_inicio", sistema="esaj"))
        self.assertFalse(ctx.cancelado())
        self.assertIsNone(ctx.pedir_codigo("t", "m"))

    def test_eventos_so_com_a_opcao_e_em_json_numa_linha(self):
        saida = io.StringIO()
        ContextoTerminal(saida=saida).evento("grupo_inicio", sistema="esaj")
        self.assertEqual(saida.getvalue(), "", "sem --eventos, a saída é a de sempre")
        ctx = ContextoTerminal(saida=saida, eventos=True)
        ctx.evento("login_aguardando", sistema="esaj", tribunal="TJAL", motivo="certificado",
                   ate="2026-10-04T10:10:00", prazo_min=10)
        linha = saida.getvalue().strip()
        self.assertTrue(linha.startswith("HELESTRON-EVENTO "))
        self.assertEqual(len(saida.getvalue().splitlines()), 1)
        dados = json.loads(linha[len("HELESTRON-EVENTO "):])
        self.assertEqual(dados["tipo"], "login_aguardando")
        self.assertEqual(dados["tribunal"], "TJAL")
        self.assertIn("momento", dados)

    def test_repassa_ao_acompanhamento_sem_nunca_quebrar(self):
        recebidos = []

        class Acomp:
            def item(self, r):
                recebidos.append(("item", r.numero))

            def evento(self, tipo, **dados):
                recebidos.append(("evento", tipo))

            def aviso(self, titulo, mensagem):
                raise RuntimeError("disco cheio")
        ctx = ContextoTerminal(saida=io.StringIO(), acompanhamento=Acomp())
        ctx.item(modelos.ResultadoProcesso(1, A.formatado, "TJAL", "esaj"))
        ctx.evento("fim", total=1)
        ctx.avisar("t", "m")             # o acompanhamento falha; o lote segue
        self.assertEqual(recebidos, [("item", A.formatado), ("evento", "fim")])


class BaseCli(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.cfg = config.Config(self.tmp / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.tmp / "Acervo"))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.tmp / "Sigilosos"))
        self.capturado = {}
        self.situacoes = [modelos.OK]
        self.construir = None        # (numeros, destino) -> itens do lote falso
        self.durante = None          # (ctx, itens) -> o que o lote falso faz no meio
        patches = [
            mock.patch.object(config, "carregar", lambda *a, **k: self.cfg),
            mock.patch.object(caminhos, "ARQUIVO_SENHAS", self.tmp / "credenciais.json"),
            mock.patch.object(caminhos, "LOGS", self.tmp / "Logs"),
            mock.patch.object(motor, "executar", self.executar_falso),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def executar_falso(self, numeros, destino, opcoes, ctx, senhas=None, cofre=None, cfg=None,
                       **_):
        self.capturado = dict(numeros=numeros, destino=destino, opcoes=opcoes, senhas=senhas,
                              cofre=cofre, ctx=ctx)
        if self.construir is not None:
            itens = self.construir(numeros, Path(destino))
        else:
            itens = [modelos.ResultadoProcesso(i + 1, n.formatado, "TJAL", "esaj",
                                               self.situacoes[i % len(self.situacoes)])
                     for i, n in enumerate(numeros)]
        if self.durante is not None:
            self.durante(ctx, itens)
        for r in itens:
            ctx.item(r)
        return modelos.ResumoLote(itens, Path(destino), Path(destino) / "_controle" / "relatorio.csv")

    def rodar(self, argv):
        codigo, saida, _ = self.rodar_com_erros(argv)
        return codigo, saida

    def rodar_com_erros(self, argv):
        saida, erros = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erros), \
                mock.patch("sys.stdin", io.StringIO("")):
            codigo = cli.main(argv, configurar_log=False)
        return codigo, saida.getvalue(), erros.getvalue()


class TestCli(BaseCli):
    def test_sem_nada_mostra_ajuda(self):
        codigo, texto = self.rodar([])
        self.assertEqual(codigo, 2)
        self.assertIn("--lista", texto)

    def test_lista_em_arquivo_com_senha(self):
        lista = self.tmp / "Pauta da semana.txt"
        lista.write_text(f"{A.formatado}\n{B.formatado} ; segredo1\n", encoding="utf-8")
        codigo, texto = self.rodar(["baixar", "--lista", str(lista), "--visivel", "--sem-ia",
                                    "--login", "manual"])
        self.assertEqual(codigo, 0)
        c = self.capturado
        self.assertEqual([n.formatado for n in c["numeros"]], [A.formatado, B.formatado])
        self.assertEqual(c["senhas"], {B.formatado: "segredo1"})
        self.assertEqual(c["destino"], self.tmp / "Acervo" / "Processos" / "Pauta da semana")
        self.assertTrue(c["opcoes"].mostrar_navegador)
        self.assertFalse(c["opcoes"].atualizar_ia)
        self.assertEqual(c["opcoes"].modo_login("esaj"), "manual")
        self.assertIsInstance(c["ctx"], ContextoTerminal)
        self.assertIn("2 processos na relação", texto)

    def test_relacao_baixada_por_link_e_apagada_depois_de_lida(self):
        # A relação pode trazer as senhas dos sigilosos: lida, sai do disco.
        from helestron.nucleo import listas
        baixadas = []

        def baixar_falso(url, pasta):
            pasta.mkdir(parents=True, exist_ok=True)
            arquivo = pasta / "Pauta do link.txt"
            arquivo.write_text(f"{A.formatado}\n{B.formatado} ; segredo1\n", encoding="utf-8")
            baixadas.append(arquivo)
            return arquivo

        with mock.patch.object(caminhos, "TEMP", self.tmp / "temp"), \
                mock.patch.object(listas, "baixar_link", baixar_falso):
            codigo, texto = self.rodar(["--lista", "https://exemplo.invalid/pauta", "--sem-ia"])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.capturado["senhas"], {B.formatado: "segredo1"})
        self.assertIn("2 processos na relação", texto)
        self.assertFalse(baixadas[0].exists(), "a relação baixada ficou no disco")
        self.assertEqual(self.capturado["destino"].name, "Pauta do link")

    def test_relacao_do_link_ilegivel_tambem_e_apagada(self):
        from helestron.nucleo import listas
        baixadas = []

        def baixar_falso(url, pasta):
            pasta.mkdir(parents=True, exist_ok=True)
            arquivo = pasta / "ilegivel.txt"
            arquivo.write_text("nada aqui ; segredo", encoding="utf-8")
            baixadas.append(arquivo)
            return arquivo

        with mock.patch.object(caminhos, "TEMP", self.tmp / "temp"), \
                mock.patch.object(listas, "baixar_link", baixar_falso):
            codigo, texto = self.rodar(["--lista", "https://exemplo.invalid/x"])
        self.assertEqual(codigo, 2)
        self.assertIn("Não consegui ler a relação", texto)
        self.assertFalse(baixadas[0].exists())

    def test_numeros_avulsos_e_destino_escolhido(self):
        destino = self.tmp / "Outra pasta"
        codigo, texto = self.rodar([A.formatado, "--destino", str(destino), "--rebaixar",
                                    "--midias"])
        self.assertEqual(codigo, 0)
        self.assertIn("1 processo na relação", texto)
        self.assertEqual(self.capturado["destino"], destino)
        self.assertFalse(self.capturado["opcoes"].pular_baixados)
        self.assertTrue(self.capturado["opcoes"].baixar_midias)

    def test_lote_de_lista_colada_ganha_nome_com_data(self):
        self.rodar([A.formatado])
        self.assertTrue(self.capturado["destino"].name.startswith("Lista "))

    def test_relacao_invalida(self):
        vazia = self.tmp / "vazia.txt"
        vazia.write_text("nada aqui", encoding="utf-8")
        codigo, texto = self.rodar(["--lista", str(vazia)])
        self.assertEqual(codigo, 2)
        self.assertIn("Não consegui ler a relação", texto)

    def test_codigos_de_saida(self):
        lista = self.tmp / "l.txt"
        lista.write_text(f"{A.formatado}\n{B.formatado}\n", encoding="utf-8")
        self.situacoes = [modelos.OK, modelos.ERRO]
        self.assertEqual(self.rodar(["--lista", str(lista)])[0], 1)
        self.situacoes = [modelos.ERRO]
        codigo, texto = self.rodar(["--lista", str(lista)])
        self.assertEqual(codigo, 2)
        self.assertIn("Precisam de atenção", texto)
        self.situacoes = [modelos.JA_BAIXADO]
        self.assertEqual(self.rodar(["--lista", str(lista)])[0], 0)

    def test_destino_que_nao_pode_ser_criado_explica_sem_rastro(self):
        def falha(*a, **k):
            raise RuntimeError("não consegui criar a pasta de destino X (Acesso negado). "
                               "Escolha outra pasta.")
        with mock.patch.object(motor, "executar", falha):
            codigo, texto = self.rodar([A.formatado])
        self.assertEqual(codigo, 2)
        self.assertIn("Não foi possível baixar: não consegui criar a pasta", texto)

    def test_cofre_com_memoria(self):
        cofre = cli._CofreComMemoria(apoio.CofreFalso({"esaj:TJAL": ("a", "b")}),
                                     {"eproc:TJRS": ("c", "d")})
        self.assertEqual(cofre.obter("eproc:TJRS"), ("c", "d"))
        self.assertEqual(cofre.obter("esaj:TJAL"), ("a", "b"))
        self.assertEqual(cofre.obter("esaj:TJSP"), ("", ""))
        self.assertEqual(cli._CofreComMemoria(None, {}).obter("esaj:TJAL"), ("", ""))


# Os campos que a skill do Claude lê de cada processo do JSON (--json)
CAMPOS_DO_PROCESSO = {"numero", "situacao", "sistema", "sigiloso", "pdf", "capa", "capa_json",
                      "texto", "paginas", "incompleto", "paginacao", "causa", "refazer",
                      "detalhe", "consultas", "ordem", "tribunal", "documentos"}


class TestCliParaAutomacao(BaseCli):
    """O que a skill do Claude usa: JSON, eventos, log, texto, retomar,
    completar, sem cofre e desanexar."""

    def ler_json(self, arq):
        return json.loads(Path(arq).read_text(encoding="utf-8"))

    def construir_com_pdfs(self, numeros, destino):
        """A no lote (fora do acervo), B sigiloso na pasta de sigilosos."""
        itens = []
        for i, n in enumerate(numeros):
            sigiloso = i == 1
            pasta = self.tmp / "Sigilosos" / destino.name if sigiloso else destino
            pdf = pasta / f"{n.nome_arquivo}.pdf"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(apoio.pdf_bytes(2, texto=f"autos de {n.formatado}"))
            (pasta / "_controle").mkdir(exist_ok=True)
            (pasta / "_controle" / f"{n.nome_arquivo}_capa.txt").write_text("capa", "utf-8")
            itens.append(modelos.ResultadoProcesso(
                i + 1, n.formatado, "TJAL", "esaj",
                modelos.OK if i == 0 else modelos.JA_BAIXADO, arquivo=str(pdf), paginas=2,
                sigiloso=sigiloso, consultas=[{"sistema": "esaj", "situacao": "OK"}]))
        return itens

    # ----------------------------------------------------------------- JSON
    def test_json_completo_e_codigo_saida(self):
        destino = self.tmp / "Lote fora"
        arq = self.tmp / "saida" / "lote.json"

        def construir(numeros, destino):
            return [modelos.ResultadoProcesso(1, numeros[0].formatado, "TJAL", "esaj",
                                              modelos.OK),
                    modelos.ResultadoProcesso(2, numeros[1].formatado, "TJAL", "esaj",
                                              modelos.ERRO, causa=modelos.CAUSA_SESSAO,
                                              detalhe="a sessão caiu")]
        self.construir = construir
        codigo, _ = self.rodar([A.formatado, B.formatado, "--destino", str(destino),
                                "--json", str(arq)])
        self.assertEqual(codigo, 1)
        dados = self.ler_json(arq)
        self.assertEqual(dados["formato"], "helestron.baixar/1")
        self.assertTrue(dados["concluido"])
        self.assertEqual(dados["codigo_saida"], 1)
        self.assertEqual(dados["destino"], str(destino))
        self.assertEqual(dados["relatorio"], str(destino / "_controle" / "relatorio.csv"))
        self.assertTrue(dados["sigilosos_do_lote"].startswith(str(self.tmp / "Sigilosos")))
        self.assertEqual(dados["resumo"], {"total": 2, "baixados": 1, "ja_baixados": 0,
                                           "falhas": 1, "pendentes": 0, "sigilosos": 0,
                                           "a_refazer": 1})
        for p in dados["processos"]:
            self.assertLessEqual(CAMPOS_DO_PROCESSO, set(p))
        segundo = dados["processos"][1]
        self.assertEqual((segundo["numero"], segundo["situacao"], segundo["causa"],
                          segundo["refazer"]), (B.formatado, "ERRO", "sessao", True))
        self.assertIsNone(segundo["paginacao"])
        # com --json, o log da execução vai para Logs\execucoes (fora do acervo)
        self.assertTrue(dados["log"].startswith(str(self.tmp / "Logs" / "execucoes")))
        self.assertTrue(Path(dados["log"]).exists())

    def test_json_e_log_recusados_dentro_do_acervo(self):
        for opcao in ("--json", "--log"):
            with self.subTest(opcao=opcao):
                arq = self.tmp / "Acervo" / "Processos" / "x.json"
                codigo, _, erros = self.rodar_com_erros([A.formatado, opcao, str(arq)])
                self.assertEqual(codigo, 2)
                self.assertIn("não pode ficar dentro do acervo", erros)
                self.assertFalse(arq.exists())
                self.assertEqual(self.capturado, {})

    def test_json_gravado_com_relacao_invalida(self):
        vazia = self.tmp / "vazia.txt"
        vazia.write_text("nada aqui", encoding="utf-8")
        arq = self.tmp / "lote.json"
        codigo, _ = self.rodar(["--lista", str(vazia), "--json", str(arq)])
        self.assertEqual(codigo, 2)
        dados = self.ler_json(arq)
        self.assertTrue(dados["concluido"])
        self.assertEqual(dados["codigo_saida"], 2)
        self.assertEqual(dados["causa_erro"], "relacao_invalida")
        self.assertIn("não consegui ler a relação", dados["erro"])

    def test_json_tambem_no_erro_de_uso(self):
        arq = self.tmp / "lote.json"
        codigo, texto = self.rodar(["--json", str(arq)])
        self.assertEqual(codigo, 2)
        self.assertIn("--lista", texto)
        dados = self.ler_json(arq)
        self.assertTrue(dados["concluido"])
        self.assertEqual((dados["codigo_saida"], dados["causa_erro"]), (2, "uso"))

    def test_json_atualizado_durante_o_lote(self):
        arq = self.tmp / "lote.json"
        vistos = []

        def durante(ctx, itens):
            ctx.evento("login_aguardando", sistema="esaj", tribunal="TJAL", modo="certificado",
                       prazo_min=10, ate="2026-10-04T10:10:00", motivo="certificado")
            vistos.append(self.ler_json(arq))
            ctx.evento("login_concluido", sistema="esaj", tribunal="TJAL")
            vistos.append(self.ler_json(arq))
        self.durante = durante
        self.rodar([A.formatado, "--destino", str(self.tmp / "L"), "--json", str(arq)])
        self.assertFalse(vistos[0]["concluido"])
        self.assertEqual(vistos[0]["aguardando"]["tipo"], "login_aguardando")
        self.assertEqual(vistos[0]["aguardando"]["motivo"], "certificado")
        self.assertIsNone(vistos[1]["aguardando"])
        final = self.ler_json(arq)
        self.assertTrue(final["concluido"])
        self.assertEqual(final["ultimo_evento"]["tipo"], "login_concluido")

    def test_json_traz_numero_real_e_pdf_na_pasta_de_sigilosos(self):
        destino = self.tmp / "Lote"
        arq = self.tmp / "lote.json"
        self.construir = self.construir_com_pdfs
        codigo, texto = self.rodar([A.formatado, B.formatado, "--destino", str(destino),
                                    "--json", str(arq)])
        self.assertEqual(codigo, 0)
        sig = self.ler_json(arq)["processos"][1]
        self.assertEqual(sig["numero"], B.formatado)
        self.assertTrue(sig["sigiloso"])
        pdf = self.tmp / "Sigilosos" / "Lote" / f"{B.nome_arquivo}.pdf"
        self.assertEqual(sig["pdf"], str(pdf))
        self.assertEqual(sig["capa"], str(pdf.parent / "_controle" / f"{B.nome_arquivo}_capa.txt"))
        self.assertEqual(sig["capa_json"], "")
        self.assertFalse(sig["paginacao"]["garantida"])
        self.assertEqual(sig["texto_situacao"], "nao_pedido")

    # -------------------------------------------------------- eventos e log
    def test_eventos_na_saida_so_com_a_opcao(self):
        def durante(ctx, itens):
            ctx.evento("grupo_inicio", sistema="esaj", tribunal="TJAL", alternativo=False,
                       ordens=[1])
        self.durante = durante
        _, texto = self.rodar([A.formatado, "--eventos"])
        linhas = [l for l in texto.splitlines() if l.startswith("HELESTRON-EVENTO ")]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(json.loads(linhas[0][len("HELESTRON-EVENTO "):])["alternativo"], False)
        _, texto = self.rodar([A.formatado])
        self.assertNotIn("HELESTRON-EVENTO", texto)

    def test_log_utf8_com_linhas_da_tela_e_do_registro(self):
        arq = self.tmp / "execução.log"
        handlers = list(logging.getLogger().handlers)

        def durante(ctx, itens):
            print("ação na tela ✓")
            logging.getLogger("download.motor").info("[1/1] %s (registro)", A.formatado)
            logging.getLogger("download.motor").debug("detalhe que não vai")
        self.durante = durante
        codigo, texto = self.rodar([A.formatado, "--log", str(arq)])
        self.assertEqual(codigo, 0)
        self.assertIn("ação na tela ✓", texto, "a tela continua mostrando tudo")
        conteudo = arq.read_text(encoding="utf-8")
        self.assertIn("ação na tela ✓", conteudo)
        self.assertIn(f"[1/1] {A.formatado} (registro)", conteudo)
        self.assertIn("Concluído em", conteudo)
        self.assertNotIn("detalhe que não vai", conteudo)
        self.assertEqual(logging.getLogger().handlers, handlers, "o handler do --log sai no fim")

    # -------------------------------------------------------------- texto
    def test_texto_ao_fim_para_lote_e_sigilosos(self):
        destino = self.tmp / "Lote"
        arq = self.tmp / "lote.json"

        def construir(numeros, destino):
            itens = self.construir_com_pdfs(numeros[:2], destino)
            # um público e um sigiloso (preso) dentro do acervo
            for ordem, n, sigiloso in ((3, C, False), (4, D, True)):
                pdf = self.tmp / "Acervo" / "Processos" / "Outro" / f"{n.nome_arquivo}.pdf"
                pdf.parent.mkdir(parents=True, exist_ok=True)
                pdf.write_bytes(apoio.pdf_bytes(1))
                itens.append(modelos.ResultadoProcesso(ordem, n.formatado, "TJAL", "esaj",
                                                       modelos.JA_BAIXADO, arquivo=str(pdf),
                                                       sigiloso=sigiloso))
            return itens
        self.construir = construir
        codigo, texto = self.rodar([A.formatado, B.formatado, C.formatado, D.formatado,
                                    "--destino", str(destino), "--texto", "--json", str(arq)])
        self.assertIn("Texto dos autos:", texto)
        procs = self.ler_json(arq)["processos"]
        esperados = [destino / "_texto" / f"{A.nome_arquivo}.txt",
                     self.tmp / "Sigilosos" / "Lote" / "_texto" / f"{B.nome_arquivo}.txt",
                     self.tmp / "Acervo" / "_ia" / "texto" / f"{C.nome_arquivo}.txt"]
        for p, txt in zip(procs, esperados):
            self.assertEqual(p["texto"], str(txt))
            self.assertEqual(p["texto_situacao"], "novo")
            conteudo = txt.read_text(encoding="utf-8")
            # texto no formato 2; o PDF falso do teste não tem o manifesto de
            # paginação, e então a marca é a posição no PDF, nunca "fl."
            self.assertTrue(conteudo.startswith("# helestron-texto 2 |"), conteudo[:80])
            self.assertIn("=== [pág. 1 do PDF] ===", conteudo)
        self.assertIn(f"autos de {A.formatado}", esperados[0].read_text(encoding="utf-8"))
        self.assertEqual(procs[3]["texto_situacao"], "sigiloso_ignorado")
        self.assertEqual(procs[3]["texto"], "")
        self.assertFalse((self.tmp / "Acervo" / "_ia" / "texto" / f"{D.nome_arquivo}.txt").exists())
        # de novo: em dia, sem refazer
        self.rodar([A.formatado, B.formatado, C.formatado, D.formatado,
                    "--destino", str(destino), "--texto", "--json", str(arq)])
        self.assertEqual(self.ler_json(arq)["processos"][0]["texto_situacao"], "em_dia")

    def test_texto_diz_as_paginas_sem_texto_no_json(self):
        """--texto: as folhas sem texto extraível (digitalizadas sem OCR) vão
        para "paginas_sem_texto", para a skill vê-las no PDF."""
        import pymupdf

        from helestron.nucleo import paginacao

        destino = self.tmp / "Lote"
        arq = self.tmp / "lote.json"

        def construir(numeros, destino):
            pdf = destino / f"{numeros[0].nome_arquivo}.pdf"
            pdf.parent.mkdir(parents=True, exist_ok=True)
            doc = pymupdf.open()
            for texto in ("Petição inicial", "", "fls. 3", "Contestação"):
                doc.new_page().insert_text((72, 72), texto)
            paginacao.gravar_no_doc(doc, paginacao.manifesto_esaj(numeros[0].formatado, 4, {},
                                                                  tribunal="TJAL"))
            doc.save(str(pdf))
            doc.close()
            outro = destino / f"{numeros[1].nome_arquivo}.pdf"
            outro.write_bytes(apoio.pdf_bytes(2, texto="autos"))
            return [modelos.ResultadoProcesso(1, numeros[0].formatado, "TJAL", "esaj",
                                              modelos.OK, arquivo=str(pdf), paginas=4),
                    modelos.ResultadoProcesso(2, numeros[1].formatado, "TJAL", "esaj",
                                              modelos.OK, arquivo=str(outro), paginas=2)]
        self.construir = construir
        codigo, texto = self.rodar([A.formatado, B.formatado, "--destino", str(destino),
                                    "--texto", "--json", str(arq)])
        self.assertEqual(codigo, 0)
        com, sem = self.ler_json(arq)["processos"]
        self.assertEqual((com["paginas_sem_texto"], com["paginas_sem_texto_pdf"]), ("2-3", "2-3"))
        self.assertEqual((sem["paginas_sem_texto"], sem["paginas_sem_texto_pdf"]), ("", ""))
        self.assertIn(f"{A.nome_arquivo}.pdf: páginas sem texto extraível (imagem? confira no "
                      "PDF): 2-3", texto)
        self.assertIn("1 com página sem texto extraível", texto)
        # em dia (sem extrair de novo), a informação continua
        self.rodar([A.formatado, B.formatado, "--destino", str(destino), "--texto",
                    "--json", str(arq)])
        com = self.ler_json(arq)["processos"][0]
        self.assertEqual((com["texto_situacao"], com["paginas_sem_texto"]), ("em_dia", "2-3"))
        # sem --texto, os campos existem e ficam vazios
        self.rodar([A.formatado, B.formatado, "--destino", str(destino), "--json", str(arq)])
        com = self.ler_json(arq)["processos"][0]
        self.assertEqual((com["texto_situacao"], com["paginas_sem_texto"]), ("nao_pedido", ""))

    # ------------------------------------------- código do e-SAJ sem terminal
    def test_sem_terminal_e_esaj_por_senha_a_janela_fica_visivel(self):
        """A skill do Claude chama sem terminal: o código que o e-SAJ manda por
        e-mail é digitado na janela do navegador, que precisa estar à vista."""
        arq = self.tmp / "lote.json"
        codigo, texto = self.rodar([A.formatado, "--login", "senha", "--json", str(arq)])
        self.assertEqual(codigo, 0)
        self.assertTrue(self.capturado["opcoes"].mostrar_navegador)
        self.assertIn("Código do e-SAJ na janela do navegador", texto)
        self.assertIn("digite-o nessa janela", texto)
        dados = self.ler_json(arq)
        self.assertTrue(dados["navegador_visivel"])
        self.assertIn("Código do e-SAJ na janela do navegador",
                      [a["titulo"] for a in dados["avisos"]])
        # nenhuma opção de ler senha ou código de arquivo
        ajuda = cli.criar_parser().format_help().lower()
        for palavra in ("--senha", "--codigo", "--código", "arquivo de senha"):
            self.assertNotIn(palavra, ajuda)

    def test_janela_escondida_quando_ha_terminal_ou_nao_ha_codigo_por_email(self):
        tjrs = apoio.numero("0700006", tr="21")            # eProc: o código não é por e-mail
        casos = (("com terminal", [A.formatado, "--login", "senha"], True),
                 ("certificado", [A.formatado, "--login", "certificado"], False),
                 ("só eProc", [tjrs.formatado, "--login", "senha"], False))
        for nome, argv, interativo in casos:
            with self.subTest(caso=nome), \
                    mock.patch.object(cli, "_interativo", return_value=interativo):
                codigo, texto = self.rodar(argv)
                self.assertEqual(codigo, 0)
                self.assertFalse(self.capturado["opcoes"].mostrar_navegador)
                self.assertNotIn("Código do e-SAJ na janela", texto)

    # --------------------------------------------------- completar e retomar
    def test_completar_e_ignorados(self):
        curto = A.formatado[:15]                      # NNNNNNN-DD.AAAA
        arq = self.tmp / "lote.json"
        codigo, texto = self.rodar([curto, "lixo", "--completar", "8.02.0001",
                                    "--json", str(arq)])
        self.assertEqual(codigo, 0)
        self.assertEqual([n.formatado for n in self.capturado["numeros"]], [A.formatado])
        self.assertIn("ignorado: lixo", texto)
        self.assertEqual([i["argumento"] for i in self.ler_json(arq)["ignorados"]], ["lixo"])
        # sem --completar, o número curto não some em silêncio
        self.capturado = {}
        codigo, texto = self.rodar([curto, "--json", str(arq)])
        self.assertEqual(codigo, 2)
        self.assertIn("--completar", texto)
        self.assertEqual(self.capturado, {})
        dados = self.ler_json(arq)
        self.assertEqual(dados["ignorados"][0]["argumento"], curto)
        self.assertEqual(dados["causa_erro"], "sem_processos")

    def test_completar_invalido_e_erro_de_uso(self):
        with redirect_stderr(io.StringIO()) as erros, self.assertRaises(SystemExit) as saida:
            cli.main([A.formatado, "--completar", "802"], configurar_log=False)
        self.assertEqual(saida.exception.code, 2)
        self.assertIn("8.02.0058", erros.getvalue())

    def test_retomar_so_os_que_pedem_nova_tentativa(self):
        destino = self.tmp / "Lote"
        motor._gravar_relatorio(destino / "_controle" / "relatorio.csv", [
            [1, A.formatado, "TJAL", "esaj", "OK", 2, 1, "a.pdf", "não", "", "", "", ""],
            [2, B.formatado, "TJAL", "esaj", "ERRO", "", "", "", "não", "", "x", "", "falha"],
            [3, C.formatado, "TJAL", "esaj", "NAO_ENCONTRADO", "", "", "", "não", "", "", "", ""],
            [4, D.formatado, "TJAL", "esaj", "CANCELADO", "", "", "", "não", "", "", "",
             "interrompido"]])
        arq = self.tmp / "lote.json"
        codigo, texto = self.rodar([A.formatado, E.formatado, "--destino", str(destino),
                                    "--retomar", "--json", str(arq)])
        self.assertEqual(codigo, 0)
        self.assertEqual([n.formatado for n in self.capturado["numeros"]],
                         [E.formatado, B.formatado, D.formatado])
        ignorados = self.ler_json(arq)["ignorados_por_retomar"]
        self.assertEqual([(i["numero"], i["situacao"]) for i in ignorados], [(A.formatado, "OK")])
        self.assertIn("não retomado", texto)
        # só com a pasta do lote, sem a relação
        codigo, _ = self.rodar(["--destino", str(destino), "--retomar"])
        self.assertEqual([n.formatado for n in self.capturado["numeros"]],
                         [B.formatado, D.formatado])

    def test_retomar_sigiloso_quando_a_senha_vem(self):
        destino = self.tmp / "Lote"
        motor._gravar_relatorio(destino / "_controle" / "relatorio.csv", [
            [1, C.formatado, "TJAL", "esaj", "SIGILOSO_SEM_SENHA", "", "", "", "sim", "", "",
             "", ""]])
        lista = self.tmp / "l.txt"
        lista.write_text(f"{C.formatado}\n", encoding="utf-8")
        codigo, _ = self.rodar(["--lista", str(lista), "--destino", str(destino), "--retomar"])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.capturado, {}, "sem a senha, repetir não muda nada")
        lista.write_text(f"{C.formatado} ; segredo1\n", encoding="utf-8")
        self.rodar(["--lista", str(lista), "--destino", str(destino), "--retomar"])
        self.assertEqual([n.formatado for n in self.capturado["numeros"]], [C.formatado])
        self.assertEqual(self.capturado["senhas"], {C.formatado: "segredo1"})

    def test_retomar_sem_nada_a_fazer(self):
        destino = self.tmp / "Lote"
        motor._gravar_relatorio(destino / "_controle" / "relatorio.csv", [
            [1, A.formatado, "TJAL", "esaj", "OK", 2, 1, "a.pdf", "não", "", "", "", ""]])
        codigo, texto = self.rodar(["--destino", str(destino), "--retomar"])
        self.assertEqual(codigo, 0)
        self.assertIn("Nada a retomar", texto)
        self.assertEqual(self.capturado, {})

    # ---------------------------------------------- opções, cofre, trava
    def test_sem_cofre_e_opcoes_novas_chegam_ao_motor(self):
        (self.tmp / "credenciais.json").write_text("{}", encoding="utf-8")
        codigo, _ = self.rodar([A.formatado, "--sem-cofre", "--esperar-navegador", "15",
                                "--rebaixar-incompletos", "--login", "senha"])
        self.assertEqual(codigo, 0)
        opcoes = self.capturado["opcoes"]
        self.assertFalse(opcoes.usar_cofre)
        self.assertEqual(opcoes.esperar_navegador_s, 900.0)
        self.assertTrue(opcoes.rebaixar_incompletos)
        self.assertTrue(opcoes.pular_baixados)
        self.assertIsNone(self.capturado["cofre"].cofre, "a senha guardada nem é aberta")

    def test_lote_em_andamento_sai_2(self):
        def ocupado(*a, **k):
            raise motor.LoteEmAndamento("outro download está usando esta pasta de lote agora")
        arq = self.tmp / "lote.json"
        with mock.patch.object(motor, "executar", ocupado):
            codigo, texto = self.rodar([A.formatado, "--json", str(arq)])
        self.assertEqual(codigo, 2)
        self.assertIn("outro download", texto)
        self.assertEqual(self.ler_json(arq)["causa_erro"], "lote_em_andamento")

    # ---------------------------------------------------------- desanexar
    def test_desanexar_no_windows(self):
        arq = self.tmp / "lote.json"
        popen = mock.Mock(side_effect=[OSError(5, "Acesso negado"), mock.Mock(pid=4242)])
        with mock.patch.object(cli.subprocess, "Popen", popen), \
                mock.patch.object(cli.sys, "platform", "win32"):
            codigo, texto = self.rodar([A.formatado, "--json", str(arq), "--desanexar"])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.capturado, {}, "quem baixa é o processo desanexado")
        primeira, segunda = popen.call_args_list
        base = cli.DETACHED_PROCESS | cli.CREATE_NEW_PROCESS_GROUP
        self.assertEqual(primeira.kwargs["creationflags"], base | cli.CREATE_BREAKAWAY_FROM_JOB)
        self.assertEqual(segunda.kwargs["creationflags"], base)
        comando = segunda.args[0]
        self.assertEqual(comando[comando.index("-m"):comando.index("-m") + 3],
                         ["-m", "helestron", "baixar"])
        self.assertIn(A.formatado, comando)
        self.assertNotIn("--desanexar", comando)
        self.assertIn("--log", comando)
        self.assertIs(segunda.kwargs["stdin"], cli.subprocess.DEVNULL)
        linha = next(l for l in texto.splitlines() if l.startswith("HELESTRON-EXECUCAO "))
        dados = json.loads(linha[len("HELESTRON-EXECUCAO "):])
        self.assertEqual(dados["pid"], 4242)
        self.assertEqual(Path(dados["json"]), arq.resolve())
        self.assertEqual(dados["log"], comando[comando.index("--log") + 1])
        inicial = self.ler_json(arq)
        self.assertEqual((inicial["pid"], inicial["concluido"]), (4242, False))

    def test_desanexar_fora_do_windows_e_sem_json(self):
        popen = mock.Mock(return_value=mock.Mock(pid=7))
        with mock.patch.object(cli.subprocess, "Popen", popen), \
                mock.patch.object(cli.sys, "platform", "linux"):
            codigo, _ = self.rodar([A.formatado, "--json", str(self.tmp / "j.json"),
                                    "--desanexar"])
        self.assertEqual(codigo, 0)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertNotIn("creationflags", popen.call_args.kwargs)
        codigo, _, erros = self.rodar_com_erros([A.formatado, "--desanexar"])
        self.assertEqual(codigo, 2)
        self.assertIn("--json", erros)


if __name__ == "__main__":
    unittest.main()
