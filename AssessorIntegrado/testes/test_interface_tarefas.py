"""Interface sem tela: recursos, tarefas, o Contexto da janela e os serviços.

Nada aqui cria janela: roda no CI do Linux e do Windows, com ou sem display.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from app.download.modelos import ResultadoProcesso
from app.interface import servicos
from app.interface.tarefas import (MICROFONE, NAVEGADOR, ContextoTela, PedidoCodigo, Recursos,
                                   Tarefa)
from app.nucleo import cnj, config


def _esperar(condicao, limite=5.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return condicao()


class TesteRecursos(unittest.TestCase):
    def test_tudo_ou_nada(self):
        r = Recursos()
        self.assertIsNone(r.tomar("Baixar", (NAVEGADOR,)))
        # quem pede navegador E microfone não fica com metade
        self.assertEqual(r.tomar("Teste", (MICROFONE, NAVEGADOR)), "Baixar")
        self.assertIsNone(r.quem_tem(MICROFONE))
        self.assertIsNone(r.tomar("Audiência", (MICROFONE,)))
        r.soltar("Baixar")
        self.assertEqual(r.ocupados(), {MICROFONE: "Audiência"})

    def test_mesmo_dono_pode_pedir_de_novo(self):
        r = Recursos()
        self.assertIsNone(r.tomar("Baixar", (NAVEGADOR,)))
        self.assertIsNone(r.tomar("Baixar", (NAVEGADOR,)))


class TesteTarefa(unittest.TestCase):
    def test_roda_solta_e_avisa(self):
        gerente = Recursos()
        fins = []
        t = Tarefa("Baixar processos", (NAVEGADOR,), gerente, ao_terminar=fins.append)
        liberar = threading.Event()
        self.assertIsNone(t.iniciar(liberar.wait, 5))
        self.assertTrue(t.ativa)
        self.assertEqual(gerente.quem_tem(NAVEGADOR), "Baixar processos")
        # outra tarefa que disputa o navegador é recusada com a frase certa
        outra = Tarefa("Testar o login", (NAVEGADOR,), gerente)
        recusa = outra.iniciar(lambda: None)
        self.assertIn("Baixar processos está usando o navegador", recusa)
        # a mesma tarefa não começa duas vezes
        self.assertIn("já está em andamento", t.iniciar(lambda: None))
        liberar.set()
        self.assertTrue(t.esperar(5))
        self.assertIsNone(gerente.quem_tem(NAVEGADOR))
        self.assertTrue(_esperar(lambda: fins == [t]))

    def test_tarefas_de_recursos_diferentes_andam_juntas(self):
        gerente = Recursos()
        a = Tarefa("Baixar", (NAVEGADOR,), gerente)
        b = Tarefa("Audiência", (MICROFONE,), gerente)
        parar = threading.Event()
        self.assertIsNone(a.iniciar(parar.wait, 5))
        self.assertIsNone(b.iniciar(parar.wait, 5))
        parar.set()
        self.assertTrue(a.esperar(5) and b.esperar(5))

    def test_erro_fica_registrado_e_recurso_volta(self):
        gerente = Recursos()
        t = Tarefa("Falha", (MICROFONE,), gerente)

        def explode():
            raise RuntimeError("microfone sumiu")
        with self.assertLogs("interface.tarefas", level="ERROR"):
            t.iniciar(explode)
            t.esperar(5)
        self.assertIsInstance(t.erro, RuntimeError)
        self.assertIsNone(gerente.quem_tem(MICROFONE))


class TesteContextoTela(unittest.TestCase):
    def setUp(self):
        self.eventos = []
        self.parar = threading.Event()
        self.ctx = ContextoTela(lambda t, d: self.eventos.append((t, d)), self.parar, intervalo=0.02)

    def test_eventos_simples(self):
        self.ctx.status("Entrando no e-SAJ…")
        self.ctx.progresso(2, 10, "0700123-45.2024.8.02.0001")
        r = ResultadoProcesso(1, "0700123-45.2024.8.02.0001", "TJAL", "esaj", situacao="OK")
        self.ctx.item(r)
        r.situacao = "ERRO"           # o motor continua mexendo no objeto
        with self.assertLogs("interface.tarefas", level="INFO"):
            self.ctx.avisar("Login", "Conclua o login na janela do navegador.")
        tipos = [t for t, _ in self.eventos]
        self.assertEqual(tipos, ["status", "progresso", "item", "avisar"])
        self.assertEqual(self.eventos[2][1].situacao, "OK", "a tela recebe uma cópia")
        self.assertFalse(self.ctx.cancelado())
        self.parar.set()
        self.assertTrue(self.ctx.cancelado())

    def _responder(self, valor, atraso=0.05):
        def responder():
            self.assertTrue(_esperar(lambda: any(t == "pedir_codigo" for t, _ in self.eventos)))
            pedido = next(d for t, d in self.eventos if t == "pedir_codigo")
            time.sleep(atraso)
            pedido.responder(valor)
        threading.Thread(target=responder, daemon=True).start()

    def test_pedir_codigo_bloqueia_ate_a_resposta(self):
        self._responder("123456")
        inicio = time.monotonic()
        self.assertEqual(self.ctx.pedir_codigo("Código", "Digite o código", 30), "123456")
        self.assertGreaterEqual(time.monotonic() - inicio, 0.04)

    def test_pedir_codigo_novo(self):
        self._responder("")
        self.assertEqual(self.ctx.pedir_codigo("Código", "Digite", 30), "")

    def test_pedir_codigo_cancelado_pelo_parar(self):
        threading.Timer(0.1, self.parar.set).start()
        self.assertIsNone(self.ctx.pedir_codigo("Código", "Digite", 30))
        pedido = self.eventos[-1][1]
        self.assertTrue(pedido.encerrado_pelo_trabalho, "o diálogo da tela deve se fechar")
        self.assertFalse(pedido.aberto)

    def test_pedir_codigo_prazo_esgotado(self):
        inicio = time.monotonic()
        self.assertIsNone(self.ctx.pedir_codigo("Código", "Digite", 1))
        self.assertLess(time.monotonic() - inicio, 6)

    def test_pedido_responde_uma_vez_so(self):
        p = PedidoCodigo("t", "m", 60)
        p.responder("1")
        p.responder("2")
        self.assertEqual(p.resposta, "1")
        self.assertGreater(p.restante, 50)


class TesteServicos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        arquivo = self.dir / "config.ini"
        arquivo.write_text(f"[geral]\npasta_acervo = {self.dir / 'Acervo'}\n", encoding="utf-8")
        self.cfg = config.Config(arquivo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cofre_misto_prefere_a_senha_digitada_agora(self):
        base = mock.Mock()
        base.obter.return_value = ("guardado", "senha-guardada")
        cofre = servicos.CofreMisto(base, {"esaj:TJAL": ("agora", "senha-agora")})
        self.assertEqual(cofre.obter("esaj:TJAL"), ("agora", "senha-agora"))
        self.assertEqual(cofre.obter("eproc:TJAL"), ("guardado", "senha-guardada"))
        base.obter.side_effect = OSError("cofre ilegível")
        self.assertEqual(cofre.obter("eproc:TJRS"), ("", ""))

    def _relatorio(self, lote: str, linhas: list[str]) -> Path:
        pasta = self.cfg.pasta_processos / lote / "_controle"
        pasta.mkdir(parents=True)
        arq = pasta / "relatorio.csv"
        cab = "ordem;processo;tribunal;sistema;situacao;paginas;documentos;arquivo;sigiloso;" \
              "incompleto;detalhe;data_hora\n"
        arq.write_text(cab + "".join(linhas), encoding="utf-8-sig")
        return arq

    def test_ultimos_lotes_le_o_relatorio_do_motor(self):
        antigo = self._relatorio("Pauta antiga", ["1;x;TJAL;esaj;OK;1;1;a.pdf;nao;;;\n"])
        import os
        os.utime(antigo, (time.time() - 3600, time.time() - 3600))
        self._relatorio("Pauta 12-09", ["1;x;TJAL;esaj;OK;1;1;a.pdf;nao;;;\n",
                                        "2;y;TJAL;esaj;JA_BAIXADO;1;1;b.pdf;nao;;;\n",
                                        "3;z;TJAL;esaj;ERRO;0;0;;nao;;falhou;\n",
                                        "4;w;TJAL;esaj;CANCELADO;0;0;;nao;;;\n"])
        lotes = servicos.ultimos_lotes(self.cfg)
        self.assertEqual([lote.nome for lote in lotes], ["Pauta 12-09", "Pauta antiga"])
        self.assertEqual((lotes[0].total, lotes[0].baixados, lotes[0].falhas), (4, 2, 1))

    def test_transcricoes_recentes_ignora_temporarios(self):
        pasta = self.cfg.pasta_transcricoes
        pasta.mkdir(parents=True)
        for nome in ("0700123-45.2024.8.02.0001.docx", "~$0700123-45.2024.8.02.0001.docx",
                     "x.docx.parcial"):
            (pasta / nome).write_bytes(b"PK")
        self.assertEqual([p.name for p in servicos.transcricoes_recentes(self.cfg)],
                         ["0700123-45.2024.8.02.0001.docx"])

    def test_pendencias_nao_quebra(self):
        for p in servicos.pendencias(self.cfg):
            self.assertIn(p.chave, ("pacotes", "modelo"))
            self.assertTrue(p.texto.endswith((".", ")")))

    def test_numero_no_nome(self):
        n = servicos.numero_no_nome(Path("Audiência 0700123-45.2024.8.02.0001 manhã.mp3"))
        self.assertEqual(n.formatado, "0700123-45.2024.8.02.0001")
        self.assertIsNone(servicos.numero_no_nome(Path("gravacao.mp3")))

    def test_excecao_cancelado(self):
        class Cancelado(Exception):
            pass
        self.assertTrue(servicos.excecao_cancelado(Cancelado()))
        self.assertFalse(servicos.excecao_cancelado(ValueError()))

    def test_abrir_no_cowork_usa_o_link_e_tem_plano_b(self):
        from app.compartilhar import claude

        with mock.patch.object(claude, "claude_desktop_instalado", return_value=True), \
                mock.patch.object(servicos, "abrir_endereco") as abrir, \
                mock.patch.object(claude, "abrir_claude_desktop") as desktop:
            self.assertEqual(servicos.abrir_no_cowork(self.dir), "cowork")
            self.assertTrue(abrir.call_args[0][0].startswith("claude://cowork/new?folder="))
            # versão do módulo sem url_cowork: abre o app, sem erro
            with mock.patch.object(claude, "url_cowork", side_effect=AttributeError("x")):
                self.assertEqual(servicos.abrir_no_cowork(self.dir), "desktop")
            desktop.assert_called_once()
        with mock.patch.object(claude, "claude_desktop_instalado", return_value=False), \
                mock.patch.object(claude, "abrir_claude_desktop") as desktop:
            self.assertEqual(servicos.abrir_no_cowork(self.dir), "baixar")
            desktop.assert_called_once()

    def test_abrir_chatgpt_work_traduz_o_retorno(self):
        from app.compartilhar import chatgpt

        with mock.patch.object(chatgpt, "abrir_chatgpt_work", return_value=True):
            self.assertEqual(servicos.abrir_chatgpt_work(self.dir), "app")
        with mock.patch.object(chatgpt, "abrir_chatgpt_work", return_value=False):
            self.assertEqual(servicos.abrir_chatgpt_work(self.dir), "web")

    def test_estado_ia_separa_claude_e_chatgpt(self):
        from app.compartilhar import chatgpt, claude

        with mock.patch.object(claude, "estado", return_value={"mcp": True, "desktop": True}), \
                mock.patch.object(chatgpt, "estado", return_value={"mcp": False, "codex": ""}):
            estado = servicos.estado_ia(self.cfg)
        self.assertTrue(estado["claude"]["mcp"])
        self.assertFalse(estado["chatgpt"]["mcp"])
        self.assertIn("acervo", estado)
        self.assertEqual(estado["acervo"]["processos"], 0)

    def test_componente_ausente_tem_frase_para_o_usuario(self):
        erro = servicos._ausente(ImportError("x", name="faster_whisper"), "transcrição")
        self.assertIn("INSTALAR.bat", str(erro))
        self.assertIn("faster_whisper", str(erro))

    def test_verificacao_minima(self):
        itens = servicos._verificacao_minima()
        self.assertTrue(all(i.situacao in ("ok", "aviso", "falha") for i in itens))


class TesteAcessos(unittest.TestCase):
    def test_portais_da_lista_inclui_o_sistema_alternativo(self):
        from app.interface.acessos import portais_da_lista

        numeros = [cnj.ler("0700123-45.2024.8.02.0001"), cnj.ler("0700999-45.2024.8.02.0058")]
        portais = [t.portal for t in portais_da_lista(numeros)]
        self.assertEqual(portais[:2], ["esaj:TJAL", "eproc:TJAL"])
        self.assertEqual(len(portais), len(set(portais)))

    def test_modos_do_eproc_sem_certificado(self):
        from app.interface.acessos import modos_do_sistema

        self.assertNotIn("certificado", [m for m, _ in modos_do_sistema("eproc")])
        self.assertIn("certificado", [m for m, _ in modos_do_sistema("esaj")])


class TesteRegressoesDaRevisao(unittest.TestCase):
    """Defeitos achados na revisão da interface (sem tela)."""

    def test_registro_das_paginas_chega_aos_detalhes(self):
        # 'interface.baixar' e 'interface.transcrever' não casavam com nenhuma
        # marca: as linhas da própria página sumiam dos Detalhes dela.
        from app.interface import pagina_baixar, pagina_compartilhar, pagina_transcrever
        from app.nucleo import registro

        for modulo, pagina in ((pagina_baixar, pagina_baixar.PaginaBaixar),
                               (pagina_transcrever, pagina_transcrever.PaginaTranscrever),
                               (pagina_compartilhar, pagina_compartilhar.PaginaCompartilhar)):
            self.assertEqual(registro.marca(modulo.log.name), pagina.marca_log, modulo.__name__)

    def test_dois_espelhos_na_nuvem_nao_rodam_juntos(self):
        # As cópias automáticas (fim do lote, fim da audiência) e a manual
        # escreviam no MESMO .parcial do destino ao mesmo tempo.
        from app.interface.tarefas import NUVEM

        gerente = Recursos()
        liberar = threading.Event()
        lote = Tarefa("Espelho na nuvem (download)", (NUVEM,), gerente)
        manual = Tarefa("Espelhar o acervo na nuvem", (NUVEM,), gerente)
        self.assertIsNone(lote.iniciar(liberar.wait, 5))
        recusa = manual.iniciar(lambda: None)
        self.assertIn("a pasta da nuvem", recusa or "")
        liberar.set()
        self.assertTrue(lote.esperar(5))
        self.assertIsNone(manual.iniciar(lambda: None))
        self.assertTrue(manual.esperar(5))

    def test_recado_do_modelo_ausente_diz_a_verdade(self):
        # A sessão ao vivo baixa o modelo que faltar: "não começa" era falso.
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "config.ini"
            arquivo.write_text(f"[geral]\npasta_acervo = {Path(tmp) / 'Acervo'}\n",
                               encoding="utf-8")
            cfg = config.Config(arquivo)
            with mock.patch.object(servicos, "_pacote_presente", return_value=True), \
                    mock.patch.object(servicos, "modelo_instalado", return_value=False):
                pendencias = servicos.pendencias(cfg)
        modelo = [p for p in pendencias if p.chave == "modelo"]
        self.assertEqual(len(modelo), 1)
        self.assertNotIn("não começa", modelo[0].texto)
        self.assertIn("primeira audiência", modelo[0].texto)


class TesteIcones(unittest.TestCase):
    def test_recursos_versionados_existem(self):
        from app.interface import estilo

        for nome in ("assessor.ico", "assessor.png", "cartao-baixar.png", "cartao-transcrever.png",
                     "cartao-compartilhar.png", "nav-inicio.png", "nav-config-ativo.png",
                     "bloco-terminal.png", "sinal-aviso.png"):
            self.assertTrue((estilo.RECURSOS / nome).exists(), nome)

    def test_ico_tem_todos_os_tamanhos(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("sem Pillow")
        from app.interface import estilo

        with Image.open(estilo.RECURSOS / "assessor.ico") as ico:
            tamanhos = {t[0] for t in ico.info.get("sizes", set())}
        self.assertTrue({16, 24, 32, 48, 256} <= tamanhos, tamanhos)


if __name__ == "__main__":
    unittest.main()
