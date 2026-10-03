"""Regressões da revisão transversal da interface: defeitos que só apareciam
cruzando páginas (uma grava, a outra mostrava o valor velho e o regravava),
textos que afirmavam o que não era verdade e erros que sumiam sob o pythonw.

A parte com tela se pula sozinha sem display (rode com xvfb-run no Linux);
a parte sem tela roda em qualquer CI.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from app.download.modelos import ResultadoProcesso, ResumoLote
from app.interface import servicos
from app.interface.tarefas import MODELO_REVISAO, PedidoCodigo, Recursos, Tarefa
from app.nucleo import caminhos, config, listas
from testes.test_interface_janela import TELA, CofreFalso, _cnj


# ======================================================================= sem tela
class TesteSemTela(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recusa_por_recurso_ocupado_em_portugues(self):
        gerente = Recursos()
        dono = Tarefa("Transcrição de gravação", (MODELO_REVISAO,), gerente)
        outra = Tarefa("Instalar a separação de falantes", (MODELO_REVISAO,), gerente)
        liberar = mock.Mock()
        evento = threading.Event()
        self.assertIsNone(dono.iniciar(evento.wait, 5))
        try:
            recusa = outra.iniciar(liberar)
            self.assertEqual(recusa, "O modelo preciso de transcrição está em uso por outro "
                                     "trabalho: Transcrição de gravação. Espere esse trabalho "
                                     "terminar ou interrompa-o.")
            self.assertEqual(outra.motivo_recusa(), recusa)
            self.assertEqual(dono.iniciar(liberar),
                             "Este trabalho já está em andamento: Transcrição de gravação.")
        finally:
            evento.set()
            dono.esperar(5)

    def test_relatorio_salvo_pelo_excel_em_ansi(self):
        # O Excel grava o CSV em cp1252: a leitura só em UTF-8 derrubava a
        # tela inicial inteira (UnicodeDecodeError).
        controle = self.dir / "Acervo" / "Processos" / "Lote" / "_controle"
        controle.mkdir(parents=True)
        (controle / "relatorio.csv").write_bytes(
            "ordem;numero;situacao;sigiloso\r\n1;x;OK;não\r\n2;y;ERRO;não\r\n".encode("cp1252"))
        cfg = mock.Mock(pasta_processos=self.dir / "Acervo" / "Processos")
        lotes = servicos.ultimos_lotes(cfg)
        self.assertEqual(len(lotes), 1)
        self.assertEqual((lotes[0].total, lotes[0].baixados, lotes[0].falhas), (2, 1, 1))

    def test_falta_um_componente_no_singular(self):
        arquivo = self.dir / "config.ini"
        arquivo.write_text(f"[geral]\npasta_acervo = {self.dir / 'Acervo'}\npasta_sigilosos = "
                           f"{self.dir / 'Sigilosos'}\n", encoding="utf-8")
        cfg = config.Config(arquivo)
        with mock.patch.object(servicos, "_pacote_presente", side_effect=lambda n: n != "sounddevice"), \
                mock.patch.object(servicos, "modelo_instalado", return_value=True):
            pendencias = servicos.pendencias(cfg)
        self.assertEqual([p.chave for p in pendencias], ["pacotes"])
        self.assertTrue(pendencias[0].texto.startswith("Falta o componente do programa: microfone."))

    def test_pastas_que_vazariam_os_sigilosos(self):
        acervo = self.dir / "Acervo"
        self.assertIsNone(servicos.problema_nas_pastas(acervo, self.dir / "Sigilosos"))
        self.assertRegex(servicos.problema_nas_pastas(acervo, acervo / "Sigilosos") or "",
                         r"não pode ficar dentro d[ao] (pasta do )?acervo")
        self.assertIn("acervo", servicos.problema_nas_pastas(acervo, acervo) or "")
        # o acervo na pasta do programa levaria Logs, config.ini e runtime
        self.assertIn("pasta do programa",
                      servicos.problema_nas_pastas(caminhos.RAIZ, self.dir / "Sigilosos"))
        # (LOCAL temporário: o real fica, conforme a máquina, junto da pasta do
        # programa ou da dos sigilosos, e outra regra responderia primeiro)
        local = self.dir / "Perfil" / "AppData" / "Local" / "AssessorIntegrado"
        with mock.patch.object(caminhos, "LOCAL", local):
            self.assertIn("senhas", servicos.problema_nas_pastas(local.parent,
                                                                 self.dir / "Sigilosos"))
        # prefixo do nome não é "dentro"
        self.assertIsNone(servicos.problema_nas_pastas(self.dir / "Acervo",
                                                       self.dir / "Acervo antigo"))
        # e a tela inicial avisa da configuração já gravada assim
        arquivo = self.dir / "config.ini"
        arquivo.write_text(f"[geral]\npasta_acervo = {acervo}\npasta_sigilosos = "
                           f"{acervo / 'Sigilosos'}\n", encoding="utf-8")
        with mock.patch.object(servicos, "_pacote_presente", return_value=True), \
                mock.patch.object(servicos, "modelo_instalado", return_value=True):
            pendencias = servicos.pendencias(config.Config(arquivo))
        self.assertEqual([p.chave for p in pendencias], ["pastas"])

    def test_relacoes_baixadas_que_sobraram_sao_apagadas(self):
        from app.interface import janela

        temp = self.dir / "temp"
        (temp / "listas").mkdir(parents=True)
        (temp / "relacoes").mkdir()
        velha = temp / "listas" / "pauta com senhas.xlsx"
        velha.write_bytes(b"x")
        recente = temp / "relacoes" / "agora.csv"
        recente.write_bytes(b"x")
        antes = time.time() - 2 * janela.IDADE_TEMP_S
        os.utime(velha, (antes, antes))
        with mock.patch.object(caminhos, "TEMP", temp):
            self.assertEqual(janela.limpar_relacoes_baixadas(), 1)
        self.assertFalse(velha.exists())
        self.assertTrue(recente.exists(), "o que acabou de ser baixado fica")

    def test_falantes_mantem_a_posicao(self):
        from app.interface.pagina_transcrever import nomes_falantes

        cfg = mock.Mock()
        cfg.texto.return_value = "Juiz(a);;Defensor(a)"
        self.assertEqual(nomes_falantes(cfg), ["Juiz(a)", "", "Defensor(a)", "", "", "", "", ""])

    def test_codigo_do_autenticador_nao_se_pede_de_novo(self):
        from app.interface.dialogos import _reenviavel

        self.assertTrue(_reenviavel(PedidoCodigo("Código de verificação do e-SAJ",
                                                 "O e-SAJ enviou um código para o seu e-mail.")))
        self.assertFalse(_reenviavel(PedidoCodigo(
            "Código do autenticador", "Digite o código de 6 dígitos do seu aplicativo "
            "autenticador (eProc do TJAL).", 120)))
        # o que o portal disser vale mais que o texto
        self.assertFalse(_reenviavel(PedidoCodigo("Código", "Digite.", 60, reenviavel=False)))

    # ------------------------------------------- pendências transversais
    def test_instancia_unica_traz_a_janela_aberta_a_frente(self):
        from app.interface import janela

        class Kernel:
            def __init__(self, erro):
                self.erro, self.nomes, self.fechados = erro, [], []

            def CreateMutexW(self, seguranca, dono, nome):
                self.nomes.append(nome)
                return 77

            def CloseHandle(self, handle):
                self.fechados.append(handle)

        class User:
            def __init__(self, por_classe, sem_classe, minimizada):
                self.janelas = {janela.CLASSE_JANELA_TK: por_classe, None: sem_classe}
                self.minimizada = minimizada
                self.procurados, self.mostradas, self.frente = [], [], []

            def FindWindowW(self, classe, titulo):
                self.procurados.append((classe, titulo))
                return self.janelas.get(classe, 0) if titulo == "Assessor Integrado" else 0

            def IsIconic(self, hwnd):
                return self.minimizada

            def ShowWindow(self, hwnd, modo):
                self.mostradas.append((hwnd, modo))

            def SetForegroundWindow(self, hwnd):
                self.frente.append(hwnd)

        with mock.patch.object(janela, "_mutex", None):
            # a primeira janela: guarda o mutex e abre
            k, u = Kernel(0), User(5, 0, False)
            self.assertTrue(janela.instancia_unica(api=(k, u, lambda: k.erro)))
            self.assertEqual(k.nomes, ["Local\\AssessorIntegrado.Janela"])
            self.assertEqual(janela._mutex, 77)
            self.assertEqual(u.procurados, [])
            # a segunda, com a primeira minimizada: restaura, traz à frente, não abre
            k, u = Kernel(janela.ERRO_JA_EXISTE), User(5, 0, True)
            self.assertFalse(janela.instancia_unica(api=(k, u, lambda: k.erro)))
            self.assertEqual(k.fechados, [77])
            self.assertEqual(u.procurados[0], ("TkTopLevel", "Assessor Integrado"))
            self.assertEqual(u.mostradas, [(5, 9)])
            self.assertEqual(u.frente, [5])
            # maximizada continua maximizada; sem a classe, procura só pelo título
            k, u = Kernel(183), User(0, 6, False)
            self.assertFalse(janela.instancia_unica(api=(k, u, lambda: k.erro)))
            self.assertEqual(u.mostradas, [])
            self.assertEqual(u.frente, [6])
            # o mutex não pôde ser criado: abre assim mesmo
            k = Kernel(5)
            k.CreateMutexW = lambda *a: 0
            with self.assertLogs("interface.janela", level="WARNING"):
                self.assertTrue(janela.instancia_unica(api=(k, User(0, 0, False), lambda: 5)))
        # fora do Windows, nada a fazer (e o ctypes nem é tocado)
        with mock.patch.object(janela.sistema, "NO_WINDOWS", False), \
                mock.patch.object(janela, "_api_windows", side_effect=AssertionError):
            self.assertTrue(janela.instancia_unica())
        # com outra janela aberta, executar() sai sem criar a segunda
        with mock.patch.object(janela, "instancia_unica", return_value=False) as conferiu, \
                mock.patch.object(janela.registro, "preparar_saidas"), \
                mock.patch.object(janela.registro, "configurar"), \
                mock.patch.object(janela.tk, "Tk", side_effect=AssertionError("abriu outra")):
            self.assertEqual(janela.executar(teste=False), 0)
            conferiu.assert_called_once()

    def test_servicos_repassam_o_sigilo_da_tela(self):
        import inspect

        from app.compartilhar import chatgpt, claude
        from app.nucleo import cnj
        from app.transcricao import ao_vivo, arquivo

        self.assertIn("sigiloso", inspect.signature(ao_vivo.SessaoAoVivo).parameters)
        self.assertIn("sigiloso", inspect.signature(arquivo.transcrever_arquivo).parameters)
        n = cnj.ler("0700123-83.2024.8.02.0001")
        cfg = mock.Mock(pasta_sigilosos=self.dir / "Sigilosos",
                        pasta_acervo=self.dir / "Acervo")
        with mock.patch.object(ao_vivo, "SessaoAoVivo") as sessao:
            servicos.nova_sessao(n, cfg, lambda *a: None, tipo="Una", sigiloso=True)
        self.assertIs(sessao.call_args.kwargs["sigiloso"], True)
        with mock.patch.object(arquivo, "transcrever_arquivo") as transcrever:
            servicos.transcrever_gravacao(self.dir / "a.wav", n, cfg, None, None, sigiloso=True)
            self.assertIs(transcrever.call_args.kwargs["sigiloso"], True)
            servicos.transcrever_gravacao(self.dir / "a.wav", n, cfg, None, None)
            self.assertIs(transcrever.call_args.kwargs["sigiloso"], False)
        # os autos na pasta de sigilosos (solto ou num lote) pré-marcam a caixa
        self.assertFalse(servicos.processo_sigiloso(cfg, n))
        lote = self.dir / "Sigilosos" / "Lote"
        lote.mkdir(parents=True)
        (lote / f"{n.nome_arquivo}.pdf").write_bytes(b"%PDF")
        self.assertTrue(servicos.processo_sigiloso(cfg, n))
        self.assertFalse(servicos.processo_sigiloso(cfg, cnj.ler(_cnj(700124))))
        self.assertFalse(servicos.processo_sigiloso(cfg, None))
        self.assertTrue(servicos.na_pasta_dos_sigilosos(cfg, lote / "x.docx"))
        self.assertFalse(servicos.na_pasta_dos_sigilosos(cfg, self.dir / "Acervo" / "x.docx"))
        # o conector do ChatGPT conta só se aponta para ESTE acervo
        with mock.patch.object(chatgpt, "estado", return_value={}) as estado_gpt, \
                mock.patch.object(claude, "estado", return_value={}), \
                mock.patch.object(claude, "mcp_registrado", return_value=False):
            servicos.estado_ia(cfg)
        self.assertEqual(estado_gpt.call_args.args, (cfg.pasta_acervo,))

    def test_textos_com_os_nomes_reais_da_tela(self):
        from app.download import modelos
        from app.interface import pagina_ajuda, pagina_baixar, pagina_config
        from app.transcricao import falantes

        # o eProc não tem folhas: a coluna conta as páginas do PDF
        self.assertIn(("paginas", "Páginas"), [c[:2] for c in pagina_baixar.COLUNAS])
        self.assertNotIn("Folhas", [c[1] for c in pagina_baixar.COLUNAS])
        # as mensagens dos portais citam a opção pelo nome que ela tem na tela
        self.assertEqual(dict(pagina_baixar.OPCOES)["mostrar_navegador"],
                         modelos.MOSTRAR_NAVEGADOR)
        # a Ajuda cita o botão que existe ("Baixar 37 processos", azul, no rodapé)
        passos = " ".join(pagina_ajuda.GUIAS[0][2])
        self.assertIn("Clique em “Baixar N processos”, o botão azul no rodapé", passos)
        self.assertNotIn("Clique em “Baixar”.", passos)
        self.assertEqual(pagina_config.tamanho_falantes_mb(), falantes.TAMANHO_MB)
        with mock.patch.dict("sys.modules", {"app.transcricao.falantes": None}):
            self.assertEqual(pagina_config.tamanho_falantes_mb(), 60)


# ======================================================================= com tela
@unittest.skipUnless(TELA, "sem tela (rode com xvfb-run no Linux)")
class TesteComTela(unittest.TestCase):
    def setUp(self):
        from app.interface import estilo, janela

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        arquivo = self.dir / "config.ini"
        arquivo.write_text(
            f"[geral]\npasta_acervo = {self.dir / 'Acervo'}\npasta_sigilosos = "
            f"{self.dir / 'Sigilosos'}\nnome_usuario = \n"
            "[interface]\nassistente_concluido = true\n", encoding="utf-8")
        self.cfg = config.Config(arquivo)
        self.caixas = mock.patch("app.interface.dialogos.messagebox")
        self.messagebox = self.caixas.start()
        self.messagebox.askyesno.return_value = True
        self.messagebox.askyesnocancel.return_value = True
        self.mensagens_baixar = mock.patch("app.interface.pagina_baixar.messagebox",
                                           self.messagebox)
        self.mensagens_baixar.start()
        self.raiz = tk.Tk()
        self.raiz.withdraw()
        estilo.aplicar(self.raiz)
        self.j = janela.Janela(self.raiz, cfg=self.cfg, teste=True)
        self.j._cofre = CofreFalso()
        self.raiz.deiconify()
        self.bombear(ate=lambda: len(self.j.paginas) == len(janela.NOMES))

    def tearDown(self):
        try:
            self.j.destruir()
        except Exception:
            pass
        self.mensagens_baixar.stop()
        self.caixas.stop()
        import gc
        gc.collect()
        self.tmp.cleanup()

    def bombear(self, segundos=0.0, ate=None, limite=8.0):
        fim = time.monotonic() + (limite if ate else segundos)
        while time.monotonic() < fim:
            try:
                self.raiz.update()
            except tk.TclError:
                return True
            if ate is not None and ate():
                return True
            time.sleep(0.01)
        return ate() if ate else True

    def _descendentes(self, w):
        for filho in w.winfo_children():
            yield filho
            yield from self._descendentes(filho)

    def textos(self, widget) -> list[str]:
        saida = []
        for filho in self._descendentes(widget):
            try:
                texto = filho.cget("text")
                if texto:
                    saida.append(str(texto))
            except tk.TclError:
                pass
        return saida

    def _entrada(self, pagina, var):
        return next(w for w in self._descendentes(pagina) if isinstance(w, tk.ttk.Entry)
                    and str(w.cget("textvariable")) == str(var))

    # ---------------------------------------------------------- integração
    def test_configuracoes_nao_regravam_o_valor_velho(self):
        pagina = self.j.paginas["config"]
        # o assistente (ou outra página) grava depois da montagem
        self.cfg.definir("geral", "nome_usuario", "Dra. Helena")
        self.cfg.definir("unidade", "comarca", "Maceió")
        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.dir / "OneDrive"))
        self.cfg.definir("geral", "pasta_acervo", str(self.dir / "Outro acervo"))
        # um clique no campo e outro fora, antes de reabrir a página, não apaga nada
        comarca = pagina._vars[("unidade", "comarca")]
        self._entrada(pagina, comarca).event_generate("<FocusOut>")
        self.assertEqual(self.cfg.texto("unidade", "comarca"), "Maceió")
        self.j.mostrar("config")
        self.bombear(0.05)
        self.assertEqual(comarca.get(), "Maceió")
        self.assertEqual(pagina._vars[("geral", "nome_usuario")].get(), "Dra. Helena")
        self.assertEqual(pagina._vars[("compartilhar", "pasta_nuvem")].get(),
                         str(self.dir / "OneDrive"))
        self.assertIn(str(self.dir / "Outro acervo"), self.textos(pagina))
        for var in (comarca, pagina._vars[("compartilhar", "pasta_nuvem")]):
            self._entrada(pagina, var).event_generate("<FocusOut>")
        self.assertEqual(self.cfg.texto("unidade", "comarca"), "Maceió")
        self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), str(self.dir / "OneDrive"))
        # a edição ainda não gravada sobrevive à troca de página
        comarca.set("Arapiraca")
        self.j.mostrar("inicio")
        self.j.mostrar("config")
        self.assertEqual(comarca.get(), "Arapiraca")
        self._entrada(pagina, comarca).event_generate("<FocusOut>")
        self.assertEqual(self.cfg.texto("unidade", "comarca"), "Arapiraca")

    def test_compartilhar_nao_apaga_a_nuvem_das_configuracoes(self):
        pagina = self.j.paginas["compartilhar"]
        nuvem = self.dir / "OneDrive"
        nuvem.mkdir()
        self.cfg.definir("compartilhar", "pasta_nuvem", str(nuvem))
        self.cfg.definir("compartilhar", "espelhar_automaticamente", True)
        # sem reabrir a página: o FocusOut do campo velho não apaga a escolha
        pagina._salvar_nuvem()
        self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), str(nuvem))
        self.j.mostrar("compartilhar")
        self.assertEqual(pagina.var_nuvem.get(), str(nuvem))
        self.assertTrue(pagina._vars["auto"].get())
        with mock.patch("app.compartilhar.nuvem.espelhar", return_value=(0, 0)) as espelhar:
            pagina.espelhar()
            self.assertTrue(self.bombear(ate=lambda: espelhar.called
                                         and not pagina.tarefa_nuvem.ativa))
        self.assertEqual(espelhar.call_args[0][1], nuvem)
        self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), str(nuvem))

    def test_revisar_ao_encerrar_segue_as_configuracoes(self):
        pagina = self.j.paginas["transcrever"]
        self.assertFalse(pagina.var_refinar.get())
        self.cfg.definir("transcricao", "refinar_ao_encerrar", True)
        self.j.mostrar("transcrever")
        self.assertTrue(pagina.var_refinar.get())

    def test_transcricao_entra_no_indice_do_acervo(self):
        pagina = self.j.paginas["transcrever"]
        pasta = self.cfg.pasta_transcricoes
        pasta.mkdir(parents=True)
        (pasta / "0700123-83.2024.8.02.0001.docx").write_bytes(b"PK")
        pagina._depois_de_salvar()                     # sem espelho: só o índice
        indice = self.cfg.pasta_acervo / "INDICE.md"
        self.assertTrue(self.bombear(ate=lambda: indice.exists()
                                     and not pagina.tarefa_indice.ativa, limite=15))
        self.assertIn("0700123-83.2024.8.02.0001.docx", indice.read_text(encoding="utf-8"))

    def test_renomear_falante_para_vazio_nao_desloca_os_outros(self):
        pagina = self.j.paginas["transcrever"]
        nomes = list(pagina.grade.nomes)
        nomes[1] = ""
        pagina._falantes_renomeados(nomes)
        from app.interface.pagina_transcrever import nomes_falantes

        self.assertEqual(nomes_falantes(self.cfg), nomes)
        self.assertEqual(nomes_falantes(self.cfg)[2], "Defensor(a)")

    # --------------------------------------------------------------- baixar
    def test_cancelar_a_troca_da_relacao_destrava_o_rodape(self):
        pagina = self.j.paginas["baixar"]
        pagina._usar_leitura(listas.ler_texto(_cnj(700500)), "Primeira")
        self.messagebox.askyesnocancel.return_value = None          # Cancelar
        pagina._ler(lambda: listas.ler_texto(_cnj(700501)), "Segunda")
        self.assertTrue(self.bombear(ate=lambda: not pagina.tarefa_ler.ativa
                                     and pagina.estado == "pronto"))
        self.bombear(0.1)
        self.assertNotIn("Lendo", pagina.texto_rodape.cget("text"))
        self.assertIsNone(pagina._modo_barra)
        self.assertIn("Baixar 1 processo", self.textos(pagina.acoes_rodape))
        self.assertEqual(pagina.nome_lote, "Primeira")

    def test_login_recusado_continua_a_vista_depois_do_lote(self):
        pagina = self.j.paginas["baixar"]
        numeros = [_cnj(700600 + i) for i in range(2)]
        pagina._usar_leitura(listas.ler_texto("\n".join(numeros)), "Lote")

        def motor(nums, destino, opcoes, ctx, senhas, cofre, cfg):
            itens = [ResultadoProcesso(i, n.formatado, "TJAL", "esaj", situacao="ERRO",
                                       detalhe="login falhou: senha recusada")
                     for i, n in enumerate(nums, 1)]
            for r in itens:
                ctx.item(r)
            ctx.avisar("Não foi possível entrar no e-SAJ do TJAL", "Senha recusada pelo portal.")
            return ResumoLote(itens, destino, destino / "_controle" / "relatorio.csv", 0.1)

        with mock.patch("app.interface.servicos.baixar_lote", side_effect=motor), \
                mock.patch("app.interface.dialogos.confirmar", return_value=True):
            pagina.iniciar()
            self.assertTrue(self.bombear(ate=lambda: pagina.estado == "fim"))
        self.bombear(0.05)
        self.assertTrue(pagina.faixa_portal.winfo_ismapped())
        self.assertIn("Senha recusada pelo portal.", self.textos(pagina.faixa_portal))
        # o recado passageiro ("Entre no…") ainda sai de cena no próximo lote
        pagina._falhas_login = []
        pagina.tratar_evento("avisar", ("Entre no eProc do TJAL", "Conclua o login."))
        pagina.tratar_evento("item", ResultadoProcesso(1, numeros[0], "TJAL", "eproc",
                                                       situacao="OK"))
        self.bombear(0.05)
        self.assertFalse(pagina.faixa_portal.winfo_ismapped())

    def test_tabela_diz_onde_o_sigiloso_esta(self):
        pagina = self.j.paginas["baixar"]
        n = _cnj(700700)
        pagina._usar_leitura(listas.ler_texto(n), "Lote")
        lote = pagina._destino()
        pagina._destino_lote = lote

        def obs(**kw):
            r = ResultadoProcesso(1, n, "TJAL", kw.pop("sistema", "esaj"), situacao="OK", **kw)
            pagina._atualizar_linha(r)
            return pagina.arvore.item(n, "values")[5]

        # separação desmarcada (ou movimentação falhou): o PDF ficou no lote
        ficou = obs(sigiloso=True, arquivo=str(lote / f"{n}.pdf"))
        self.assertIn("SIGILOSO: ficou na pasta do lote", ficou)
        self.assertNotIn("fora do acervo", ficou)
        movido = obs(sigiloso=True, arquivo=str(self.cfg.pasta_sigilosos / "Lote" / f"{n}.pdf"))
        self.assertEqual(movido, "sigiloso (na pasta de sigilosos)")
        self.assertEqual(obs(sigiloso=True), "sigiloso")
        # eProc: o que falta são documentos de eventos, não folhas
        self.assertEqual(obs(sistema="eproc", incompleto="ev. 4 PET1"),
                         "faltam documentos: ev. 4 PET1")
        self.assertEqual(obs(incompleto="12-15"), "faltam as folhas 12-15")

    def test_desmarcar_separar_sigilosos_pede_confirmacao(self):
        pagina = self.j.paginas["baixar"]
        var = pagina._vars["separar_sigilosos"]
        self.messagebox.askyesno.return_value = False
        var.set(False)
        pagina._opcao("separar_sigilosos")
        self.assertTrue(var.get())
        self.assertTrue(self.cfg.flag("download", "separar_sigilosos"))
        self.messagebox.askyesno.return_value = True
        var.set(False)
        pagina._opcao("separar_sigilosos")
        self.assertFalse(self.cfg.flag("download", "separar_sigilosos"))
        # a nota da página Compartilhar passa a dizer a verdade
        self.j.mostrar("compartilhar")
        textos = " ".join(self.textos(self.j.paginas["compartilhar"].nota_sigilo))
        self.assertIn("SÃO compartilhados", textos)
        self.assertNotIn("não são compartilhados", textos)

    def test_concordancia_com_uma_linha_corrompida(self):
        pagina = self.j.paginas["baixar"]
        leitura = listas.ler_texto(_cnj(700800))
        leitura.corrompidos = ["7,00801E+19"]
        pagina._usar_leitura(leitura, "Planilha")
        texto = " ".join(self.textos(pagina.faixa_lista))
        self.assertIn("1 linha da planilha guarda o número como NÚMERO", texto)
        self.assertIn("ficou de fora de propósito", texto)

    def test_relacao_por_link_nao_fica_no_disco(self):
        pagina = self.j.paginas["baixar"]
        baixado = self.dir / "temp" / "pauta com senhas.csv"

        def baixar_link(url, pasta):
            baixado.parent.mkdir(parents=True, exist_ok=True)
            baixado.write_text(f"processo;senha\n{_cnj(700900)};segredo\n", encoding="utf-8")
            return baixado

        with mock.patch("app.nucleo.listas.baixar_link", side_effect=baixar_link), \
                mock.patch("app.interface.pagina_baixar.dialogos.DialogoLink",
                           side_effect=lambda raiz, usar: usar("https://exemplo/x")):
            pagina.link()
            self.assertTrue(self.bombear(ate=lambda: len(pagina.arvore.get_children()) == 1))
        self.assertFalse(baixado.exists())
        self.assertEqual(pagina.nome_lote, "pauta com senhas")

    # ---------------------------------------------------- textos e Windows
    def test_dialogo_do_codigo_do_autenticador(self):
        from app.interface import dialogos

        d = dialogos.DialogoCodigo(self.raiz, PedidoCodigo(
            "Código do autenticador", "Digite o código de 6 dígitos do seu aplicativo "
            "autenticador (eProc do TJAL).", 120))
        try:
            self.bombear(0.1)
            self.assertRegex(d.tempo.cget("text"), r"^Tempo para digitar: [12]:\d\d\. ")
            self.assertIn("muda a cada 30 segundos", d.tempo.cget("text"))
            self.assertNotIn("Pedir novo código", self.textos(d))
        finally:
            d.cancelar()
        d = dialogos.DialogoCodigo(self.raiz, PedidoCodigo(
            "Código de verificação do e-SAJ", "O e-SAJ enviou um código para o seu e-mail. "
            "O código vale cerca de 3 minutos.", 600))
        try:
            self.bombear(0.1)
            self.assertNotIn("vale por mais", d.tempo.cget("text"))
            self.assertIn("Pedir novo código", self.textos(d))
        finally:
            d.cancelar()

    def test_preparado_para_ia_com_preposicao(self):
        pagina = self.j.paginas["compartilhar"]
        antigo = datetime.now() - timedelta(days=12)
        pagina._aplicar_estado({"acervo": {"processos": 1, "transcricoes": 0,
                                           "preparado": antigo}})
        self.assertIn("preparado para IA em ", pagina.estado_acervo.texto.cget("text"))
        pagina._aplicar_estado({"acervo": {"processos": 1, "transcricoes": 0,
                                           "preparado": datetime.now()}})
        self.assertIn("preparado para IA hoje, ", pagina.estado_acervo.texto.cget("text"))

    def test_pasta_dos_sigilosos_dentro_do_acervo_e_recusada(self):
        pagina = self.j.paginas["config"]
        dentro = self.cfg.pasta_acervo / "Sigilosos"
        antes = self.cfg.texto("geral", "pasta_sigilosos")
        with mock.patch("app.interface.dialogos.escolher_pasta", return_value=dentro):
            botao = next(w for w in self._descendentes(pagina)
                         if isinstance(w, tk.ttk.Button) and w.cget("text") == "Alterar…"
                         and "segredo de justiça" in " ".join(self.textos(w.master)))
            botao.invoke()
        self.assertEqual(self.cfg.texto("geral", "pasta_sigilosos"), antes)
        self.assertTrue(self.messagebox.showwarning.called)
        self.assertRegex(self.messagebox.showwarning.call_args[0][1],
                         r"não pode ficar dentro d[ao] (pasta do )?acervo")

    def test_erro_num_botao_vai_para_o_registro_e_para_a_tela(self):
        self.j.teste = False                      # fora do teste, o usuário vê
        try:
            with self.assertLogs("interface.janela", level="ERROR"):
                self.raiz.report_callback_exception(PermissionError,
                                                    PermissionError("config.ini bloqueado"), None)
            self.assertEqual(self.messagebox.showerror.call_count, 1)
            self.assertIn("config.ini bloqueado", self.messagebox.showerror.call_args[0][1])
            # o mesmo erro em rajada não abre uma caixa atrás da outra
            with self.assertLogs("interface.janela", level="ERROR"):
                self.raiz.report_callback_exception(PermissionError,
                                                    PermissionError("de novo"), None)
            self.assertEqual(self.messagebox.showerror.call_count, 1)
        finally:
            self.j.teste = True

    def test_assistente_fecha_mesmo_sem_poder_gravar(self):
        from app.interface import dialogos

        assistente = dialogos.Assistente(self.j)
        self.bombear(0.1)
        with mock.patch.object(self.cfg, "definir", side_effect=PermissionError("somente leitura")):
            assistente.pular()
        self.bombear(0.05)
        self.assertFalse(assistente.winfo_exists())

    def test_audiencia_comeca_mesmo_sem_poder_lembrar_o_processo(self):
        from testes.test_interface_janela import SessaoFalsa

        pagina = self.j.paginas["transcrever"]
        criadas = []

        def fabrica(numero, cfg, eventos, **kw):
            s = SessaoFalsa(numero, cfg, eventos, pasta=self.dir, **kw)
            criadas.append(s)
            return s
        pagina.var_numero.set("0700123-83.2024.8.02.0001")
        with mock.patch("app.interface.servicos.nova_sessao", side_effect=fabrica), \
                mock.patch.object(self.cfg, "definir", side_effect=PermissionError("bloqueado")):
            pagina.iniciar()
        self.assertEqual(len(criadas), 1)
        self.assertTrue(self.bombear(ate=lambda: pagina.situacao == "gravando"))
        pagina.encerrar()
        self.assertTrue(self.bombear(ate=lambda: pagina.situacao == "fim"))

    def test_manual_sem_programa_para_markdown(self):
        from app.nucleo import sistema

        pagina = self.j.paginas["ajuda"]
        abertos = []

        def abrir(alvo):
            if Path(alvo).suffix == ".md":
                raise OSError("[WinError 1155] Nenhum aplicativo está associado ao arquivo")
            abertos.append(Path(alvo).name)
        with mock.patch.object(sistema, "abrir_arquivo", side_effect=abrir), \
                mock.patch.object(sistema, "NO_WINDOWS", False):
            pagina._manual()
        self.assertEqual(abertos, ["LEIA-ME.txt"])
        self.assertFalse(self.messagebox.showerror.called)

    # ------------------------------------------- pendências transversais
    def _botao(self, pai, texto):
        return next(w for w in self._descendentes(pai)
                    if isinstance(w, tk.ttk.Button) and w.cget("text") == texto)

    def test_sigiloso_preso_no_acervo_nao_vai_para_a_nuvem_e_fica_a_vista(self):
        pagina = self.j.paginas["baixar"]
        n = _cnj(701000)
        pagina._usar_leitura(listas.ler_texto(n), "Lote")
        nuvem_dir = self.dir / "Nuvem"
        nuvem_dir.mkdir()
        self.cfg.definir("compartilhar", "pasta_nuvem", str(nuvem_dir))
        self.cfg.definir("compartilhar", "espelhar_automaticamente", True)
        preso = pagina._destino() / f"{n}.pdf"

        def motor(nums, destino, opcoes, ctx, senhas, cofre, cfg):
            destino.mkdir(parents=True, exist_ok=True)
            preso.write_bytes(b"%PDF")
            r = ResultadoProcesso(1, n, "TJAL", "esaj", situacao="ERRO", sigiloso=True,
                                  arquivo=str(preso), detalhe="ATENÇÃO: processo sigiloso")
            ctx.item(r)
            ctx.avisar("Processo sigiloso ficou no acervo", "Não consegui levar o arquivo.")
            return ResumoLote([r], destino, destino / "_controle" / "relatorio.csv", 0.1,
                              sigilosos_no_acervo=[str(preso)])

        with mock.patch("app.interface.servicos.baixar_lote", side_effect=motor), \
                mock.patch("app.interface.dialogos.confirmar", return_value=True), \
                mock.patch("app.compartilhar.nuvem.espelhar", return_value=(0, 0)) as espelhar:
            pagina.iniciar()
            self.assertTrue(self.bombear(ate=lambda: pagina.estado == "fim"))
            self.bombear(0.2)
        espelhar.assert_not_called()
        self.assertTrue(pagina.faixa_sigilo.winfo_ismapped())
        texto = " ".join(self.textos(pagina.faixa_sigilo))
        self.assertIn("Processo sigiloso ficou no acervo", texto)
        self.assertIn(f"{n} (pasta “Lote”)", texto)
        self.assertIn("o espelho na nuvem não é feito", texto)
        self.assertIn(f"mova-o para “{self.cfg.pasta_sigilosos / 'Lote'}”", texto)
        self.assertIn("limpa o resto sozinho no próximo preparo", texto)
        # o recado passageiro sai de cena; o alerta, não (nem com a lista limpa)
        pagina._recolher_recado_portal()
        pagina.limpar()
        self.bombear(0.05)
        self.assertFalse(pagina.faixa_portal.winfo_ismapped())
        self.assertTrue(pagina.faixa_sigilo.winfo_ismapped())
        with mock.patch("app.nucleo.sistema.abrir_pasta") as abrir:
            self._botao(pagina.faixa_sigilo, "Mostrar o PDF").invoke()
            self._botao(pagina.faixa_sigilo, "Abrir a pasta de sigilosos").invoke()
        self.assertEqual(abrir.call_args_list[0], mock.call(preso.parent, selecionar=preso))
        self.assertEqual(abrir.call_args_list[1], mock.call(self.cfg.pasta_sigilosos / "Lote"))
        # nem o espelho das outras páginas leva a cópia presa
        self.assertEqual(self.j.sigilosos_no_acervo(), [preso])
        transcrever, compartilhar = self.j.paginas["transcrever"], self.j.paginas["compartilhar"]
        with mock.patch("app.compartilhar.nuvem.espelhar", return_value=(0, 0)) as espelhar, \
                mock.patch("app.interface.servicos.atualizar_indice") as indice:
            with self.assertLogs("interface.transcricao", level="WARNING"):
                transcrever._depois_de_salvar()
            compartilhar.var_nuvem.set(str(nuvem_dir))
            compartilhar.espelhar()
            self.bombear(0.2)
        espelhar.assert_not_called()
        indice.assert_not_called()
        self.assertIn(preso.name, self.messagebox.showwarning.call_args[0][1])
        # movido à mão: o alerta sai quando a página volta à vista
        destino = self.cfg.pasta_sigilosos / "Lote"
        destino.mkdir(parents=True)
        preso.rename(destino / preso.name)
        self.j.mostrar("inicio")
        self.j.mostrar("baixar")
        self.bombear(0.05)
        self.assertFalse(pagina.faixa_sigilo.winfo_ismapped())
        self.assertEqual(self.j.sigilosos_no_acervo(), [])

    def test_audiencia_sigilosa_fica_fora_do_acervo(self):
        from app.interface import componentes
        from testes.test_interface_janela import SessaoFalsa

        pagina = self.j.paginas["transcrever"]
        self.j.mostrar("transcrever")
        caixa = pagina.caixa_sigilo
        self.assertFalse(caixa.marcada)
        self.assertFalse(caixa.nota.winfo_ismapped())
        # os autos estão na pasta de sigilosos: pré-marcada e travada
        n = "0700123-83.2024.8.02.0001"
        lote = self.cfg.pasta_sigilosos / "Lote"
        lote.mkdir(parents=True)
        (lote / f"{n}.pdf").write_bytes(b"%PDF")
        pagina.var_numero.set(n)
        self.bombear(0.05)
        self.assertTrue(caixa.marcada)
        self.assertTrue(caixa.caixa.instate(["disabled"]))
        self.assertEqual(caixa.nota.cget("text"), componentes.NOTA_SIGILO_AUTOS)
        # outro processo: a marcação automática sai...
        pagina.var_numero.set(_cnj(701100))
        self.assertFalse(caixa.marcada)
        self.assertFalse(caixa.caixa.instate(["disabled"]))
        # ...e a do usuário fica, com a frase de onde os arquivos vão
        caixa.caixa.invoke()
        pagina.var_numero.set(_cnj(701101))
        self.assertTrue(caixa.marcada)
        self.assertEqual(caixa.nota.cget("text"), "A transcrição e a gravação ficam na pasta "
                                                  "dos sigilosos, fora do acervo compartilhado.")
        caixa.caixa.invoke()
        pagina.var_numero.set(n)

        pasta = self.cfg.pasta_sigilosos / "Transcricoes"
        (pasta / "_audio").mkdir(parents=True)
        criadas = []

        class SessaoSigilosa(SessaoFalsa):
            def __init__(s, *a, **kw):
                super().__init__(*a, pasta=pasta, **kw)
                s.caminho_audio = pasta / "_audio" / f"{n}.flac"
                s.caminho_audio.write_bytes(b"fLaC")

        def fabrica(numero, cfg, eventos, **kw):
            criadas.append(SessaoSigilosa(numero, cfg, eventos, **kw))
            return criadas[-1]

        with mock.patch("app.interface.servicos.nova_sessao", side_effect=fabrica):
            pagina.iniciar()
            self.assertTrue(self.bombear(ate=lambda: pagina.situacao == "gravando"))
        self.assertIs(criadas[0].sigiloso, True)
        self.assertIn("segredo de justiça", pagina.resumo_sessao.cget("text"))
        self.assertTrue(caixa.caixa.instate(["disabled"]))
        pagina.encerrar()
        self.assertTrue(self.bombear(ate=lambda: pagina.situacao == "fim"))
        self.assertIn("Na pasta dos sigilosos, fora do acervo compartilhado.",
                      " ".join(self.textos(pagina.faixa)))
        docx = pasta / f"{n}.docx"
        with mock.patch("app.nucleo.sistema.abrir_pasta") as abrir, \
                mock.patch("app.nucleo.sistema.abrir_arquivo") as abrir_doc:
            self._botao(pagina.faixa, "Abrir a pasta").invoke()
            self._botao(pagina.faixa, "Abrir o documento").invoke()
        abrir.assert_called_once_with(pasta, docx)
        abrir_doc.assert_called_once_with(docx)
        # "Revisar agora" de audiência sigilosa continua fora do acervo
        with mock.patch("app.interface.servicos.transcrever_gravacao",
                        return_value=pasta / f"{n} (2).docx") as revisar:
            self._botao(pagina.faixa, "Revisar agora").invoke()
            self.assertTrue(self.bombear(ate=lambda: revisar.called
                                         and not pagina.tarefa_arquivo.ativa))
        self.assertIs(revisar.call_args.kwargs["sigiloso"], True)

    def test_gravacao_com_a_caixa_de_segredo_de_justica(self):
        from app.interface import dialogos

        pagina = self.j.paginas["transcrever"]
        n = _cnj(701200)

        def caixa_aberta():
            return next(w for w in self.raiz.winfo_children()
                        if isinstance(w, dialogos.DialogoNumero))

        def transcrever(gravacao):
            with mock.patch("app.interface.pagina_transcrever.filedialog.askopenfilename",
                            return_value=str(gravacao)):
                pagina.transcrever_arquivo()
            self.bombear(0.05)
            return caixa_aberta()

        gravacao = self.dir / f"{n}.mp3"
        gravacao.write_bytes(b"ID3")
        with mock.patch("app.interface.servicos.transcrever_gravacao",
                        return_value=self.dir / f"{n}.docx") as chamada:
            d = transcrever(gravacao)
            self.assertFalse(d.caixa_sigilo.marcada, "o processo não está nos sigilosos")
            d.caixa_sigilo.caixa.invoke()                    # marcada à mão
            d.confirmar()
            self.assertTrue(self.bombear(ate=lambda: chamada.called
                                         and not pagina.tarefa_arquivo.ativa))
            self.assertIs(chamada.call_args.kwargs["sigiloso"], True)
            # os autos foram para os sigilosos: pré-marcada
            (self.cfg.pasta_sigilosos / "Lote").mkdir(parents=True)
            (self.cfg.pasta_sigilosos / "Lote" / f"{n}.pdf").write_bytes(b"%PDF")
            d = transcrever(gravacao)
            self.assertTrue(d.caixa_sigilo.marcada)
            self.assertTrue(d.caixa_sigilo.caixa.instate(["disabled"]))
            d.cancelar()
            # a gravação guardada na pasta dos sigilosos: marcada e travada
            dentro = self.cfg.pasta_sigilosos / "Transcricoes" / "_audio" / "sessao.flac"
            dentro.parent.mkdir(parents=True)
            dentro.write_bytes(b"fLaC")
            pagina.var_numero.set(_cnj(701201))
            d = transcrever(dentro)
            self.assertTrue(d.caixa_sigilo.marcada)
            self.assertIn("A gravação está na pasta dos sigilosos",
                          d.caixa_sigilo.nota.cget("text"))
            d.cancelar()

    def test_conectar_ao_claude_sem_o_claude_desktop(self):
        from app.compartilhar import chatgpt, claude

        pagina = self.j.paginas["compartilhar"]
        # o espelho cita a exceção dos sigilosos
        self.assertTrue(any("as cópias de processos que estão na pasta de sigilosos são "
                            "retiradas do espelho" in t for t in self.textos(pagina)))
        with mock.patch.object(claude, "registrar_mcp", return_value=[self.dir / "x.json"]), \
                mock.patch.object(claude, "claude_desktop_instalado", return_value=False), \
                mock.patch("app.interface.servicos.estado_ia", return_value={}):
            pagina.conectar_claude()
            self.assertTrue(self.bombear(ate=lambda: "Falta instalar o Claude Desktop"
                                         in self.textos(pagina.faixa)))
        self.assertIn("foi registrado", " ".join(self.textos(pagina.faixa)))
        with mock.patch.object(claude, "instalar_claude_desktop") as instalar:
            self._botao(pagina.faixa, "Instalar o Claude Desktop").invoke()
        instalar.assert_called_once()
        # registrado sem o app: o bloco não diz "Instalado"
        pagina._aplicar_estado({"claude": {"desktop": False}, "mcp_acervo": True})
        cowork = pagina.blocos[1]
        self.assertEqual(cowork.estado.texto.cget("text"),
                         "Acervo registrado, mas o Claude Desktop não está instalado")
        pagina._aplicar_estado({"claude": {"desktop": True}, "mcp_acervo": True})
        self.assertEqual(cowork.estado.texto.cget("text"), "Instalado · acervo conectado")
        # o pacote do ChatGPT recebe a configuração (pasta de sigilosos desta instalação)
        with mock.patch.object(chatgpt, "gerar_pacote", side_effect=LookupError) as pacote:
            pagina.pacote()
            self.assertTrue(self.bombear(ate=lambda: self.messagebox.showinfo.called))
        self.assertIs(pacote.call_args.kwargs["cfg"], self.cfg)

    def test_tamanho_do_componente_de_falantes(self):
        from app.transcricao import falantes

        textos = " ".join(self.textos(self.j.paginas["config"]))
        self.assertIn(f"Componente opcional (cerca de {falantes.TAMANHO_MB} MB).", textos)
        self.assertNotIn("cerca de 50 MB", textos)
        self.assertIn("Instalar o componente", self.textos(self.j.paginas["config"]))


if __name__ == "__main__":
    unittest.main()
