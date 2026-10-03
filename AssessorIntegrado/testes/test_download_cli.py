"""Linha de comando do download e o acompanhamento pelo terminal."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from app.download import cli, modelos, motor
from app.download.contexto import Contexto, ContextoTerminal
from app.nucleo import caminhos, config

from testes import apoio_download as apoio

A = apoio.numero("0700001", tr="02")
B = apoio.numero("0700002", tr="02")


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
        from app.interface.tarefas import ContextoTela
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
        self.assertFalse(ctx.cancelado())
        self.assertIsNone(ctx.pedir_codigo("t", "m"))


class TestCli(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.cfg = config.Config(self.tmp / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.tmp / "Acervo"))
        self.capturado = {}
        self.situacoes = [modelos.OK]
        patches = [
            mock.patch.object(config, "carregar", lambda: self.cfg),
            mock.patch.object(caminhos, "ARQUIVO_SENHAS", self.tmp / "credenciais.json"),
            mock.patch.object(motor, "executar", self.executar_falso),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def executar_falso(self, numeros, destino, opcoes, ctx, senhas=None, cofre=None, cfg=None,
                       **_):
        self.capturado = dict(numeros=numeros, destino=destino, opcoes=opcoes, senhas=senhas,
                              cofre=cofre, ctx=ctx)
        itens = [modelos.ResultadoProcesso(i + 1, n.formatado, "TJAL", "esaj",
                                           self.situacoes[i % len(self.situacoes)])
                 for i, n in enumerate(numeros)]
        return modelos.ResumoLote(itens, Path(destino), Path(destino) / "_controle" / "relatorio.csv")

    def rodar(self, argv):
        saida = io.StringIO()
        with redirect_stdout(saida), mock.patch("sys.stdin", io.StringIO("")):
            codigo = cli.main(argv, configurar_log=False)
        return codigo, saida.getvalue()

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
        from app.nucleo import listas
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
        from app.nucleo import listas
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


if __name__ == "__main__":
    unittest.main()
