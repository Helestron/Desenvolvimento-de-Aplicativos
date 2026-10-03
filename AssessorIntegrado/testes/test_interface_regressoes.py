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
        self.assertIn("senhas", servicos.problema_nas_pastas(caminhos.LOCAL.parent,
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


if __name__ == "__main__":
    unittest.main()
