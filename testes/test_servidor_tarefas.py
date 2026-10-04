"""Tarefas pela API: download com o motor simulado, eventos SSE e perguntas."""

from __future__ import annotations

import logging
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from helestron.download.modelos import (Cancelado, OK, ResultadoProcesso, ResumoLote)
from helestron.servidor import trabalhos
from helestron.tarefas import ContextoTela, PedidoCodigo, Pergunta, Recursos

from testes.test_servidor_base import ServidorDeTeste

A = "0700123-83.2024.8.02.0001"
B = "0700124-68.2024.8.02.0001"


class MotorFalso:
    """Faz as vezes de servicos.baixar_lote: publica itens, pede código, baixa."""

    def __init__(self, pedir_codigo: int | None = None, segurar: threading.Event | None = None,
                 prazo_s: int = 60):
        self.pedir_codigo = pedir_codigo
        self.segurar = segurar
        self.prazo_s = prazo_s
        self.codigos: list = []
        self.chamadas: list = []

    def __call__(self, numeros, destino, opcoes, ctx, senhas, cofre, cfg):
        self.chamadas.append({"numeros": [n.formatado for n in numeros], "destino": destino,
                              "opcoes": opcoes, "senhas": dict(senhas or {}), "cofre": cofre})
        itens = [ResultadoProcesso(i + 1, n.formatado, "TJAL", "esaj") for i, n in enumerate(numeros)]
        for r in itens:
            ctx.item(r)
        ctx.status("Entrando no e-SAJ…")
        logging.getLogger("download.motor").info("Lote %s: começando", Path(destino).name)
        if self.pedir_codigo is not None:
            self.codigos.append(ctx.pedir_codigo("Código de verificação do e-SAJ",
                                                 "O e-SAJ enviou um código para o seu e-mail.",
                                                 self.prazo_s, True))
        for i, r in enumerate(itens):
            if self.segurar is not None:
                while not self.segurar.wait(0.05):
                    if ctx.cancelado():
                        raise Cancelado()
            if ctx.cancelado():
                break
            ctx.progresso(i, len(itens), r.numero)
            r.situacao = OK
            r.paginas = 10 + i
            r.arquivo = str(Path(destino) / f"{r.numero}.pdf")
            r.carimbar()
            ctx.item(r)
        ctx.progresso(len(itens), len(itens), "")
        return ResumoLote(itens, Path(destino), Path(destino) / "_controle" / "relatorio.csv")


class TestDownload(ServidorDeTeste):
    def test_lote_completo_com_eventos(self):
        # No programa, registro.configurar() põe o registro em INFO.
        registro = logging.getLogger("download.motor")
        self.addCleanup(registro.setLevel, registro.level)
        registro.setLevel(logging.INFO)
        motor = MotorFalso()
        leitor = self.eventos()
        self.app.senhas_relacao[A] = "senha-da-relacao"
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            dados = self.cliente.dados("POST", "/api/download/iniciar", {
                "processos": [A, B, A], "nome_lote": "Lote: março/2026",
                "senhas": {B: "senha-b"},
                "opcoes": {"separar_sigilosos": True, "rebaixar": True, "navegador_visivel": True}})
            id_tarefa = dados["tarefa"]
            tarefa = self.esperar_tarefa(id_tarefa)
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(tarefa["tipo"], "download")
        self.assertEqual(tarefa["resultado"]["baixados"], 2)
        self.assertEqual(tarefa["resultado"]["falhas"], 0)
        self.assertEqual(tarefa["progresso"]["percentual"], 100.0)
        chamada = motor.chamadas[0]
        self.assertEqual(chamada["numeros"], [A, B])                 # sem repetir
        self.assertEqual(chamada["destino"], self.amb.dados / "Acervo" / "Processos"
                         / "Lote_ março_2026")
        self.assertFalse(chamada["opcoes"].pular_baixados)           # rebaixar
        self.assertTrue(chamada["opcoes"].mostrar_navegador)
        self.assertEqual(chamada["senhas"], {A: "senha-da-relacao", B: "senha-b"})
        # eventos: tarefa (rodando e concluída), item por processo, log com a tarefa
        leitor.esperar("tarefa", lambda d: d["id"] == id_tarefa and d["estado"] == "rodando")
        leitor.esperar("tarefa", lambda d: d["id"] == id_tarefa and d["estado"] == "concluida")
        item = leitor.esperar("item", lambda d: d["numero"] == B and d["situacao"] == "OK")
        self.assertEqual(item["tarefa"], id_tarefa)
        self.assertEqual(item["rotulo"], "baixado")
        self.assertTrue(item["arquivo"].endswith(f"{B}.pdf"))
        self.assertEqual(set(item) >= {"tarefa", "numero", "situacao", "mensagem", "arquivo",
                                       "sigiloso"}, True)
        leitor.esperar("item", lambda d: d["numero"] == A and d["situacao"] == "")
        log = leitor.esperar("log", lambda d: "começando" in d["texto"])
        self.assertEqual(log["tarefa"], id_tarefa)
        self.assertEqual(log["nivel"], "info")
        leitor.esperar("estado")
        detalhe = self.cliente.dados("GET", f"/api/tarefas/{id_tarefa}")
        self.assertEqual(len(detalhe["itens"]), 2)
        lista = self.cliente.dados("GET", "/api/tarefas")
        self.assertEqual(lista[0]["id"], id_tarefa)

    def test_processo_invalido_400(self):
        status, env = self.cliente.post("/api/download/iniciar", {"processos": ["123"]})
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "numero_invalido")
        status, _ = self.cliente.post("/api/download/iniciar", {"processos": []})
        self.assertEqual(status, 400)

    def test_pergunta_respondida(self):
        motor = MotorFalso(pedir_codigo=0)
        leitor = self.eventos()
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            id_tarefa = self.cliente.dados("POST", "/api/download/iniciar",
                                           {"processos": [A]})["tarefa"]
            pergunta = leitor.esperar("pergunta")
            self.assertEqual(pergunta["tipo"], "codigo")
            self.assertEqual(pergunta["tarefa"], id_tarefa)
            self.assertTrue(pergunta["reenviavel"])
            self.assertGreater(pergunta["prazo_s"], 50)
            # quem conecta depois recebe a pergunta aberta
            outro = self.eventos()
            outro.esperar("pergunta", lambda d: d["id"] == pergunta["id"])
            self.cliente.dados("POST", f"/api/perguntas/{pergunta['id']}/responder",
                               {"valor": " 123 456 "})
            fechada = leitor.esperar("pergunta_fechada")
            self.assertEqual(fechada, {"id": pergunta["id"], "motivo": "respondida"})
            tarefa = self.esperar_tarefa(id_tarefa)
        self.assertEqual(motor.codigos, ["123456"])
        self.assertEqual(tarefa["estado"], "concluida")
        status, env = self.cliente.post(f"/api/perguntas/{pergunta['id']}/responder",
                                        {"valor": "1"})
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "pergunta_fechada")

    def test_pergunta_cancelada(self):
        motor = MotorFalso(pedir_codigo=0)
        leitor = self.eventos()
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            id_tarefa = self.cliente.dados("POST", "/api/download/iniciar",
                                           {"processos": [A]})["tarefa"]
            pergunta = leitor.esperar("pergunta")
            self.cliente.dados("POST", f"/api/perguntas/{pergunta['id']}/cancelar")
            self.assertEqual(leitor.esperar("pergunta_fechada")["motivo"], "cancelada")
            self.esperar_tarefa(id_tarefa)
        self.assertEqual(motor.codigos, [None])

    def test_pergunta_com_prazo_esgotado(self):
        motor = MotorFalso(pedir_codigo=0, prazo_s=1)
        leitor = self.eventos()
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            id_tarefa = self.cliente.dados("POST", "/api/download/iniciar",
                                           {"processos": [A]})["tarefa"]
            pergunta = leitor.esperar("pergunta")
            fechada = leitor.esperar("pergunta_fechada", espera=10)
            self.assertEqual(fechada, {"id": pergunta["id"], "motivo": "prazo"})
            self.esperar_tarefa(id_tarefa)
        self.assertEqual(motor.codigos, [None])

    def test_parar_fecha_a_pergunta_e_a_tarefa(self):
        segurar = threading.Event()
        motor = MotorFalso(pedir_codigo=0, segurar=segurar)
        leitor = self.eventos()
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            id_tarefa = self.cliente.dados("POST", "/api/download/iniciar",
                                           {"processos": [A, B]})["tarefa"]
            leitor.esperar("pergunta")
            parada = self.cliente.dados("POST", f"/api/tarefas/{id_tarefa}/parar")
            self.assertIn("Parando", parada["status"])
            self.assertEqual(leitor.esperar("pergunta_fechada")["motivo"], "tarefa_parada")
            tarefa = self.esperar_tarefa(id_tarefa)
        self.assertEqual(tarefa["estado"], "parada")
        self.assertIsNone(tarefa["erro"])

    def test_navegador_ocupado_e_tarefa_repetida(self):
        segurar = threading.Event()
        motor = MotorFalso(segurar=segurar)
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            id_tarefa = self.cliente.dados("POST", "/api/download/iniciar",
                                           {"processos": [A]})["tarefa"]
            status, env = self.cliente.post("/api/download/iniciar", {"processos": [B]})
            self.assertEqual(status, 409)
            self.assertIn("já está em andamento", env["erro"]["mensagem"])
            with mock.patch("helestron.servicos.testar_login"):
                status, env = self.cliente.post("/api/acessos/testar", {"tribunal": "TJAL"})
            self.assertEqual(status, 409)
            self.assertEqual(env["erro"]["codigo"], "ocupado")
            self.assertIn("O navegador dos portais está em uso por outro trabalho: Baixar 1 processo",
                          env["erro"]["mensagem"])
            segurar.set()
            self.esperar_tarefa(id_tarefa)
            # solto o recurso, o teste de login começa
            with mock.patch("helestron.servicos.testar_login"):
                id_teste = self.cliente.dados("POST", "/api/acessos/testar",
                                              {"tribunal": "TJAL"})["tarefa"]
                self.assertEqual(self.esperar_tarefa(id_teste)["estado"], "concluida")

    def test_motor_que_falha(self):
        from helestron.download.modelos import PortalIndisponivel

        with mock.patch("helestron.servicos.baixar_lote",
                        side_effect=PortalIndisponivel("o e-SAJ está fora do ar")):
            id_tarefa = self.cliente.dados("POST", "/api/download/iniciar",
                                           {"processos": [A]})["tarefa"]
            tarefa = self.esperar_tarefa(id_tarefa)
        self.assertEqual(tarefa["estado"], "falhou")
        self.assertEqual(tarefa["erro"], "O e-SAJ está fora do ar")

    def test_sigiloso_preso_no_acervo_vira_pendencia(self):
        preso = self.amb.dados / "Acervo" / "Processos" / "Lote" / f"{A}.pdf"
        preso.parent.mkdir(parents=True)
        preso.write_bytes(b"%PDF")

        def motor(numeros, destino, opcoes, ctx, senhas, cofre, cfg):
            r = ResultadoProcesso(1, A, "TJAL", "esaj", situacao=OK, sigiloso=True,
                                  arquivo=str(preso))
            ctx.item(r)
            return ResumoLote([r], Path(destino), Path(destino) / "r.csv",
                              sigilosos_no_acervo=[str(preso)])

        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/download/iniciar", {"processos": [A], "nome_lote": "Lote"})["tarefa"])
        self.assertEqual(tarefa["resultado"]["sigilosos_no_acervo"], [str(preso)])
        estado = self.cliente.dados("GET", "/api/estado")
        self.assertEqual(estado["pendencias"][0]["chave"], "sigilo")
        # nada vai para a IA enquanto ele estiver lá
        status, env = self.cliente.post("/api/compartilhar/preparar")
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "sigiloso_no_acervo")
        preso.unlink()
        estado = self.cliente.dados("GET", "/api/estado")
        self.assertNotIn("sigilo", [p["chave"] for p in estado["pendencias"]])

    def test_lotes(self):
        relatorio = self.amb.dados / "Acervo" / "Processos" / "Lote 1" / "_controle" / "relatorio.csv"
        relatorio.parent.mkdir(parents=True)
        relatorio.write_text("numero;situacao\nx;OK\ny;ERRO\n", encoding="utf-8")
        lotes = self.cliente.dados("GET", "/api/download/lotes")
        self.assertEqual(lotes[0]["nome"], "Lote 1")
        self.assertEqual((lotes[0]["total"], lotes[0]["baixados"], lotes[0]["falhas"]), (2, 1, 1))
        estado = self.cliente.dados("GET", "/api/estado")
        self.assertEqual(estado["resumo"]["ultimos_lotes"][0]["nome"], "Lote 1")


class TestGerenteSemServidor(unittest.TestCase):
    """O gerente de tarefas e o ContextoTela, sem HTTP."""

    def setUp(self):
        self.eventos: list = []
        from helestron.servidor.perguntas import GerentePerguntas

        publicar = lambda tipo, dados: self.eventos.append((tipo, dados))   # noqa: E731
        self.perguntas = GerentePerguntas(publicar)
        self.gerente = trabalhos.GerenteTarefas(publicar, self.perguntas, Recursos())
        self.addCleanup(self.gerente.fechar)

    def test_progresso_limitado_e_estado_final(self):
        def alvo(tw):
            for i in range(500):
                tw.definir_progresso(i, 500, f"arquivo {i}")
            return {"ok": True}

        tw = self.gerente.iniciar("preparo", "Preparar", alvo)
        self.assertTrue(tw.esperar(5))
        time.sleep(0.4)
        tarefas = [d for t, d in self.eventos if t == "tarefa"]
        self.assertLess(len(tarefas), 50)
        self.assertEqual(tarefas[-1]["estado"], "concluida")
        self.assertEqual(tw.resultado, {"ok": True})

    def test_contexto_de_fundo_nao_bloqueia(self):
        resposta = []

        def alvo(tw):
            ctx = trabalhos.ContextoFundo(tw, "Monitor", "Entre no portal")
            resposta.append(ctx.pedir_codigo("Código", "Veja o e-mail", 600))
            resposta.append(ctx.pediu_login)

        tw = self.gerente.iniciar("pauta_sincronizar", "Monitor", alvo)
        self.assertTrue(tw.esperar(5))
        self.assertEqual(resposta, [None, True])
        self.assertFalse(any(t == "pergunta" for t, _ in self.eventos))
        self.assertTrue(any(t == "aviso" and d["mensagem"] == "Entre no portal"
                            for t, d in self.eventos))

    def test_contexto_tela_compativel(self):
        postados = []
        ctx = ContextoTela(lambda t, d: postados.append((t, d)))

        def responder():
            while not postados:
                time.sleep(0.01)
            postados[0][1].responder("9")

        threading.Thread(target=responder, daemon=True).start()
        self.assertEqual(ctx.pedir_codigo("t", "m", 30, reenviavel=False), "9")
        tipo, pedido = postados[0]
        self.assertEqual(tipo, "pedir_codigo")
        self.assertIsInstance(pedido, PedidoCodigo)
        self.assertIs(pedido.reenviavel, False)

    def test_pergunta_generica(self):
        def alvo(tw):
            return tw.contexto().perguntar_tipo("escolha", "Perfil", "Qual?", ["A", "B"], 30)

        tw = self.gerente.iniciar("teste_login", "Escolher", alvo)
        limite = time.monotonic() + 5
        while not self.perguntas.abertas() and time.monotonic() < limite:
            time.sleep(0.01)
        aberta = self.perguntas.abertas()[0]
        self.assertEqual(aberta["opcoes"], ["A", "B"])
        with self.assertRaises(ValueError):
            self.perguntas.responder(aberta["id"], "C")
        self.perguntas.responder(aberta["id"], "B")
        self.assertTrue(tw.esperar(5))
        self.assertEqual(tw.resultado, "B")

    def test_pergunta_registrada_fecha_uma_vez(self):
        p = Pergunta("t", "m", 60)
        self.perguntas.abrir(p, "x")
        self.assertTrue(p.responder("1"))
        self.assertFalse(p.responder("2"))
        self.assertEqual(p.resposta, "1")
        self.assertEqual([t for t, _ in self.eventos].count("pergunta_fechada"), 1)


if __name__ == "__main__":
    unittest.main()
