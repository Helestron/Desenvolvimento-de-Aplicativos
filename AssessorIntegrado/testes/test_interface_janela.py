"""A janela de verdade: páginas, cartões, eventos, código de verificação,
audiência ao vivo (com sessão simulada) e o fechar que salva a audiência.

Precisa de tela: sem display (CI do Linux sem Xvfb), os testes se pulam
sozinhos. No Windows e com `xvfb-run`, rodam inteiros.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from app.download.modelos import ResultadoProcesso, ResumoLote
from app.nucleo import config, listas


def tem_display() -> bool:
    if sys.platform != "win32" and not os.environ.get("DISPLAY"):
        return False
    try:
        raiz = tk.Tk()
        raiz.destroy()
        return True
    except tk.TclError:
        return False


TELA = tem_display()


def _cnj(seq: int, ano=2024, seg=8, tr=2, orig=1) -> str:
    corpo = f"{seq:07d}{ano}{seg}{tr:02d}{orig:04d}"
    dv = 98 - (int(corpo + "00") % 97)
    return f"{seq:07d}-{dv:02d}.{ano}.{seg}.{tr:02d}.{orig:04d}"


class CofreFalso:
    def __init__(self):
        self.dados = {}

    def obter(self, portal):
        return self.dados.get(portal, ("", ""))

    def guardar(self, portal, usuario, senha):
        self.dados[portal] = (usuario, senha)

    def apagar(self, portal):
        self.dados.pop(portal, None)


class SessaoFalsa:
    """Faz as vezes de transcricao.ao_vivo.SessaoAoVivo (sem microfone nem modelo)."""

    def __init__(self, numero, cfg, eventos, *, tipo="", participantes=None, falante="",
                 pasta=None):
        self.numero, self.cfg, self.eventos = numero, cfg, eventos
        self.falante = falante
        self.tipo = tipo
        self.modelo = "small"
        self.tempo = 0.0
        self.falas = []
        self.caminho_docx = Path(pasta) / f"{numero.nome_arquivo}.docx"
        self.caminho_audio = None
        self.encerrada = threading.Event()
        self.pausada = False

    def iniciar(self):
        self.eventos("estado", "Gravando")

    def definir_falante(self, rotulo):
        self.falante = rotulo

    def pausar(self):
        self.pausada = True

    def retomar(self):
        self.pausada = False

    def encerrar(self, refinar=False):
        self.caminho_docx.write_bytes(b"PK")
        self.encerrada.set()
        self.eventos("fim", self.caminho_docx)
        return self.caminho_docx


@unittest.skipUnless(TELA, "sem tela (rode com xvfb-run no Linux)")
class TesteJanela(unittest.TestCase):
    def setUp(self):
        from app.interface import estilo, janela

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        arquivo = self.dir / "config.ini"
        arquivo.write_text(
            f"[geral]\npasta_acervo = {self.dir / 'Acervo'}\npasta_sigilosos = "
            f"{self.dir / 'Sigilosos'}\nnome_usuario = Dra. Teste\n"
            "[interface]\nassistente_concluido = true\n", encoding="utf-8")
        self.cfg = config.Config(arquivo)
        # Nenhuma caixa de mensagem nativa pode abrir num teste: ela esperaria
        # um clique para sempre. Respostas padrão: "sim".
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
        self.bombear(0.2)

    def tearDown(self):
        try:
            self.j.destruir()
        except Exception:
            pass
        self.mensagens_baixar.stop()
        self.caixas.stop()
        # recolhe os widgets desta janela aqui, na thread principal (ver
        # dialogos.Dialogo.fechar)
        import gc
        gc.collect()
        self.tmp.cleanup()

    # --------------------------------------------------------------- apoio
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

    def textos(self, widget) -> list[str]:
        saida = []
        for filho in widget.winfo_children():
            try:
                texto = filho.cget("text")
                if texto:
                    saida.append(str(texto))
            except tk.TclError:
                pass
            saida += self.textos(filho)
        return saida

    # --------------------------------------------------------------- testes
    def test_todas_as_paginas_abrem(self):
        from app.interface.janela import PaginaComErro

        self.assertEqual(list(self.j.paginas), ["inicio", "baixar", "transcrever", "compartilhar",
                                                "config", "ajuda"])
        for nome, pagina in self.j.paginas.items():
            self.assertNotIsInstance(pagina, PaginaComErro, nome)
            self.j.mostrar(nome)
            self.bombear(0.05)
            self.assertEqual(self.j.atual, nome)

    def test_inicio_mostra_as_tres_funcoes(self):
        textos = self.textos(self.j.paginas["inicio"])
        for titulo in ("Baixar processos", "Transcrever audiência", "Compartilhar com IA"):
            self.assertIn(titulo, textos)
        for botao in ("Iniciar transcrição", "Compartilhar acervo"):
            self.assertIn(botao, textos)
        self.assertTrue(any(t.endswith("Dra. Teste") for t in textos), "saudação com o nome")
        # o botão de cada cartão leva à página da função
        inicio = self.j.paginas["inicio"]
        inicio.botoes["transcrever"].invoke()
        self.assertEqual(self.j.atual, "transcrever")

    def test_atalhos_de_pagina(self):
        self.j.mostrar("baixar")
        self.raiz.event_generate("<Control-Key-3>")
        self.bombear(0.05)
        self.assertEqual(self.j.atual, "transcrever")

    def test_relacao_e_eventos_do_lote(self):
        pagina = self.j.paginas["baixar"]
        numeros = [_cnj(700100 + i) for i in range(5)]
        leitura = listas.ler_texto("\n".join(numeros))
        pagina._usar_leitura(leitura, "Pauta teste")
        self.assertEqual(len(pagina.arvore.get_children()), 5)
        self.assertIn("Baixar 5 processos", self.textos(pagina))
        self.assertTrue(str(pagina._destino()).endswith("Pauta teste"))
        r = ResultadoProcesso(1, numeros[0], "TJAL", "esaj", situacao="OK", paginas=42)
        pagina.tratar_evento("item", r)
        valores = pagina.arvore.item(numeros[0], "values")
        self.assertEqual((valores[3], str(valores[4])), ("baixado", "42"))

    def test_lote_completo_com_motor_simulado(self):
        pagina = self.j.paginas["baixar"]
        numeros = [_cnj(700200 + i) for i in range(3)]
        pagina._usar_leitura(listas.ler_texto("\n".join(numeros)), "Lote simulado")

        def motor(nums, destino, opcoes, ctx, senhas, cofre, cfg):
            itens = []
            for i, n in enumerate(nums, 1):
                ctx.progresso(i - 1, len(nums), n.formatado)
                r = ResultadoProcesso(i, n.formatado, "TJAL", "esaj",
                                      situacao="OK" if i < 3 else "NAO_ENCONTRADO", paginas=10)
                ctx.item(r)
                itens.append(r)
            return ResumoLote(itens, destino, destino / "_controle" / "relatorio.csv", 0.1)

        with mock.patch("app.interface.servicos.baixar_lote", side_effect=motor), \
                mock.patch("app.interface.dialogos.confirmar", return_value=True):
            pagina.iniciar()
            self.assertTrue(self.bombear(ate=lambda: pagina.estado == "fim"))
        self.assertEqual(pagina.resumo.texto(), "2 baixados, 1 com problema.")
        textos = self.textos(pagina.acoes_rodape)
        self.assertIn("Abrir a pasta", textos)
        self.assertIn("Tentar de novo (1)", textos)

    def test_codigo_de_verificacao_pela_janela(self):
        from app.interface import dialogos
        from app.interface.tarefas import ContextoTela

        pagina = self.j.paginas["baixar"]
        ctx = ContextoTela(pagina.postar, threading.Event(), intervalo=0.02)
        resposta = {}
        t = threading.Thread(target=lambda: resposta.setdefault(
            "codigo", ctx.pedir_codigo("Código do e-SAJ", "Digite o código do e-mail.", 60)))
        t.start()

        def dialogo():
            return next((w for w in self.raiz.winfo_children()
                         if isinstance(w, dialogos.DialogoCodigo)), None)
        self.assertTrue(self.bombear(ate=lambda: dialogo() is not None))
        d = dialogo()
        self.assertTrue(d.ok.instate(["disabled"]), "sem código, Confirmar fica apagado")
        d.codigo.set(" 123 456 ")
        self.bombear(0.05)
        d.confirmar()
        t.join(5)
        self.assertEqual(resposta["codigo"], "123456")

    def test_codigo_fecha_quando_o_trabalho_desiste(self):
        from app.interface import dialogos
        from app.interface.tarefas import ContextoTela

        pagina = self.j.paginas["baixar"]
        parar = threading.Event()
        ctx = ContextoTela(pagina.postar, parar, intervalo=0.02)
        t = threading.Thread(target=lambda: ctx.pedir_codigo("Código", "Digite", 60))
        t.start()

        def abertos():
            return [w for w in self.raiz.winfo_children() if isinstance(w, dialogos.DialogoCodigo)]
        self.assertTrue(self.bombear(ate=lambda: bool(abertos())))
        parar.set()
        t.join(5)
        self.assertTrue(self.bombear(ate=lambda: not abertos()))

    def _sessao_falsa(self):
        criadas = []

        def fabrica(numero, cfg, eventos, **kw):
            s = SessaoFalsa(numero, cfg, eventos, pasta=self.dir, **kw)
            criadas.append(s)
            return s
        return criadas, fabrica

    def test_audiencia_ao_vivo_com_sessao_simulada(self):
        from app.transcricao.documento import Fala

        pagina = self.j.paginas["transcrever"]
        self.j.mostrar("transcrever")
        criadas, fabrica = self._sessao_falsa()
        pagina.var_numero.set("0700123-83.2024.8.02.0001")
        with mock.patch("app.interface.servicos.nova_sessao", side_effect=fabrica):
            pagina.iniciar()
            self.assertTrue(self.bombear(ate=lambda: pagina.situacao == "gravando"))
            sessao = criadas[0]
            # F2 escolhe o segundo falante e avisa a sessão
            evento = mock.Mock(keysym="F2")
            self.assertTrue(pagina.atalho(evento))
            self.assertEqual(sessao.falante, pagina.grade.nomes[1])
            sessao.eventos("fala", Fala(1.0, 4.0, "Promotor(a)", "Sem mais perguntas, Excelência."))
            self.assertTrue(self.bombear(ate=lambda: "Excelência" in pagina.texto.get("1.0", "end")))
            self.assertIn("PROMOTOR(A)", pagina.texto.get("1.0", "end"))
            self.assertEqual(self.j.paginas["transcrever"].indicador()[1], "#c5221f")
            pagina._clique_redondo()               # pausar
            self.assertTrue(sessao.pausada)
            pagina._clique_redondo()               # retomar
            self.assertFalse(sessao.pausada)
            pagina.encerrar()
            self.assertTrue(self.bombear(ate=lambda: pagina.situacao == "fim"))
        self.assertTrue(sessao.encerrada.is_set())
        self.assertIn("Transcrição salva", self.textos(pagina.faixa))

    def test_numero_obrigatorio_e_validado(self):
        pagina = self.j.paginas["transcrever"]
        pagina.var_numero.set("12345")
        self.assertIsNone(pagina.numero)
        pagina.var_numero.set("Processo 0700123-83.2024.8.02.0001, audiência de instrução")
        self.assertEqual(pagina.numero.formatado, "0700123-83.2024.8.02.0001")
        pagina.var_numero.set("")
        pagina.iniciar()
        self.messagebox.showwarning.assert_called_once()
        self.assertEqual(pagina.situacao, "pronta")

    def test_fechar_salva_a_audiencia_antes(self):
        pagina = self.j.paginas["transcrever"]
        criadas, fabrica = self._sessao_falsa()
        pagina.var_numero.set("0700123-83.2024.8.02.0001")
        with mock.patch("app.interface.servicos.nova_sessao", side_effect=fabrica):
            pagina.iniciar()
            self.assertTrue(self.bombear(ate=lambda: pagina.situacao == "gravando"))
            with mock.patch("app.interface.dialogos.confirmar", return_value=True) as perguntou:
                self.j.fechar()
                self.assertTrue(self.bombear(ate=lambda: not self.j._viva(), limite=10))
            perguntou.assert_called_once()
        self.assertTrue(criadas[0].encerrada.is_set(), "o DOCX é gravado antes de fechar")

    def test_percorrer_para_o_ci(self):
        fim = threading.Event()
        self.j.percorrer(self.dir / "capturas", ao_fim=fim.set)
        self.assertTrue(self.bombear(ate=fim.is_set, limite=60))
        self.assertEqual(self.j.falhas_teste, [])
        self.assertEqual(self.j.codigo_saida, 0)

    def test_assistente_de_primeiro_uso_salva_e_conclui(self):
        from app.interface import dialogos

        a = dialogos.Assistente(self.j)
        self.bombear(0.2)
        a.proximo()
        a.proximo()
        self.bombear(0.1)
        campos = [w for w in a.area.winfo_children()]
        self.assertTrue(campos)
        a.proximo()                                  # concluir
        self.bombear(0.1)
        self.assertTrue(self.cfg.flag("interface", "assistente_concluido"))
        self.assertTrue(self.cfg.texto("interface", "tribunal"))

    # ------------------------------------------------ ações de cada página
    def test_baixar_abrir_arquivo_le_em_segundo_plano(self):
        pagina = self.j.paginas["baixar"]
        relacao = self.dir / "Pauta da vara.txt"
        relacao.write_text("\n".join(_cnj(700300 + i) for i in range(4)), encoding="utf-8")
        with mock.patch("app.interface.pagina_baixar.filedialog.askopenfilename",
                        return_value=str(relacao)):
            pagina.abrir_arquivo()
            self.assertTrue(self.bombear(ate=lambda: len(pagina.arvore.get_children()) == 4))
        self.assertEqual(pagina.nome_lote, "Pauta da vara")
        self.assertEqual(self.cfg.texto("interface", "pasta_relacoes"), str(self.dir))
        # relação ruim: mensagem clara, nada quebra
        vazia = self.dir / "vazia.txt"
        vazia.write_text("nenhum número aqui", encoding="utf-8")
        with mock.patch("app.interface.pagina_baixar.filedialog.askopenfilename",
                        return_value=str(vazia)):
            pagina.abrir_arquivo()
            self.assertTrue(self.bombear(ate=lambda: self.messagebox.showerror.called))
        self.assertIn("nenhum número", self.messagebox.showerror.call_args[0][1])
        self.assertEqual(len(pagina.arvore.get_children()), 4, "a lista anterior fica")

    def test_baixar_link_compartilhado(self):
        pagina = self.j.paginas["baixar"]
        arquivo = self.dir / "relacao do drive.csv"
        arquivo.write_text("processo\n" + _cnj(700400), encoding="utf-8")
        with mock.patch("app.nucleo.listas.baixar_link", return_value=arquivo):
            pagina._ler(lambda: listas.ler_arquivo(arquivo), None)
            self.assertTrue(self.bombear(ate=lambda: len(pagina.arvore.get_children()) == 1))
        self.assertEqual(pagina.nome_lote, "relacao do drive")

    def test_compartilhar_acoes(self):
        from app.compartilhar import claude

        pagina = self.j.paginas["compartilhar"]
        self.j.mostrar("compartilhar")
        self.assertTrue(self.bombear(ate=lambda: bool(pagina.estado), limite=15))
        # preparar: roda o preparo de verdade num acervo vazio
        pagina.preparar()
        self.assertTrue(self.bombear(ate=lambda: (self.cfg.pasta_acervo / "CLAUDE.md").exists()
                                     and not pagina.tarefa.ativa, limite=20))
        # Cowork: o pedido inicial vai para a área de transferência
        with mock.patch("app.interface.servicos.abrir_no_cowork", return_value="cowork"):
            pagina.abrir_cowork()
            self.assertTrue(self.bombear(ate=lambda: "Abrindo o Cowork" in self.textos(pagina.faixa)))
        self.assertIn(str(self.cfg.pasta_acervo), self.raiz.clipboard_get())
        # ChatGPT Work sem o app: avisa e oferece instalar
        with mock.patch("app.interface.servicos.abrir_chatgpt_work", return_value="web"):
            pagina.abrir_work()
            self.assertTrue(self.bombear(ate=lambda: "Instalar o app do ChatGPT"
                                         in self.textos(pagina.faixa)))
        self.assertEqual(self.raiz.clipboard_get(), str(self.cfg.pasta_acervo))
        # conector do Claude Desktop
        with mock.patch.object(claude, "registrar_mcp", return_value=[self.dir / "x.json"]):
            pagina.conectar_claude()
            self.assertTrue(self.bombear(ate=lambda: "Acervo conectado ao Claude Desktop"
                                         in self.textos(pagina.faixa)))
        # pacote com o acervo vazio: recado, não erro
        pagina.pacote()
        self.assertTrue(self.bombear(ate=lambda: self.messagebox.showinfo.called, limite=15))
        # espelho na nuvem para uma pasta qualquer
        nuvem = self.dir / "OneDrive"
        nuvem.mkdir()
        pagina.var_nuvem.set(str(nuvem))
        pagina.espelhar()
        self.assertTrue(self.bombear(ate=lambda: not pagina.tarefa_nuvem.ativa
                                     and "copiado" in pagina.estado_nuvem.texto.cget("text"),
                                     limite=15))
        self.assertEqual(self.cfg.texto("compartilhar", "pasta_nuvem"), str(nuvem))
        self.assertTrue((nuvem / "Assessor Integrado - Acervo" / "CLAUDE.md").exists())

    def test_config_acoes(self):
        pagina = self.j.paginas["config"]
        self.j.mostrar("config")
        # salvar ao sair do campo
        var = pagina._vars[("unidade", "comarca")]
        var.set("Arapiraca")
        entradas = [w for w in self._descendentes(pagina) if isinstance(w, tk.ttk.Entry)
                    and str(w.cget("textvariable")) == str(var)]
        entradas[0].event_generate("<FocusOut>")
        self.bombear(0.05)
        self.assertEqual(self.cfg.texto("unidade", "comarca"), "Arapiraca")
        # baixar modelo (simulado), com progresso
        def baixar(nome, progresso):
            progresso(0.5, "metade")
            return self.dir
        with mock.patch("app.interface.servicos.baixar_modelo", side_effect=baixar), \
                mock.patch("app.interface.servicos.modelo_instalado", return_value=True):
            pagina.baixar_modelo_ao_vivo()
            self.assertTrue(self.bombear(ate=lambda: "instalado" in str(
                pagina.texto_modelo.cget("text"))))
        # testar login (simulado)
        with mock.patch("app.interface.servicos.testar_login", return_value=None):
            t = pagina._tribunal()
            estado = mock.Mock()
            editor = mock.Mock()
            editor.modo.get.return_value = "manual"
            pagina._testar_login(t, editor, estado)
            self.assertTrue(self.bombear(ate=lambda: any(
                "Login confirmado" in str(c) for c in estado.definir.call_args_list)))
        # verificação da instalação (simulada)
        from app.interface.servicos import ItemVerificacao
        with mock.patch("app.interface.servicos.verificar_instalacao",
                        return_value=[ItemVerificacao("Python", "ok", "3.12"),
                                      ItemVerificacao("Modelo", "aviso", "não baixado")]):
            pagina.verificar()
            self.assertTrue(self.bombear(ate=lambda: len(pagina.arvore_verif.get_children()) == 2))
        self.assertIn("pedem atenção", pagina.estado_verificar.texto.cget("text"))

    def test_transcrever_gravacao_e_recuperar(self):
        pagina = self.j.paginas["transcrever"]
        gravacao = self.dir / "audiencia 0700123-83.2024.8.02.0001.mp3"
        gravacao.write_bytes(b"ID3")
        saida = self.dir / "0700123-83.2024.8.02.0001.docx"

        def transcrever(origem, numero, cfg, progresso, cancelado, **kw):
            progresso(0.5, "Transcrevendo")
            saida.write_bytes(b"PK")
            return saida
        with mock.patch("app.interface.pagina_transcrever.filedialog.askopenfilename",
                        return_value=str(gravacao)), \
                mock.patch("app.interface.servicos.transcrever_gravacao",
                           side_effect=transcrever) as chamada:
            pagina.transcrever_arquivo()
            self.assertTrue(self.bombear(ate=lambda: "Transcrição pronta"
                                         in self.textos(pagina.faixa)))
        self.assertEqual(chamada.call_args[0][1].formatado, "0700123-83.2024.8.02.0001",
                         "o número vem do nome do arquivo")
        diario = self.dir / "x.jsonl"
        pagina._mostrar_recuperaveis([diario])
        with mock.patch("app.interface.servicos.recuperar", return_value=saida):
            pagina.recuperar()
            self.assertTrue(self.bombear(ate=lambda: "Transcrição recuperada"
                                         in self.textos(pagina.faixa)))

    def _descendentes(self, w):
        for filho in w.winfo_children():
            yield filho
            yield from self._descendentes(filho)

    def test_registro_tem_limite(self):
        from app.interface.componentes import MAX_LINHAS_REGISTRO, Detalhes

        d = Detalhes(self.j.paginas["ajuda"])
        d.escrever([f"linha {i}" for i in range(MAX_LINHAS_REGISTRO + 150)])
        linhas = int(d.caixa.index("end-1c").split(".")[0])
        self.assertLessEqual(linhas, MAX_LINHAS_REGISTRO + 1)
        self.assertIn(f"linha {MAX_LINHAS_REGISTRO + 149}", d.caixa.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
