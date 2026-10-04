"""O monitor da pauta (seção 8.7): quando sincroniza, e que não bloqueia em perguntas."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from helestron.aplicativo import monitor as modulo_monitor
from helestron.aplicativo.monitor import ADIAR_S, SEM_PAUTA_S, MonitorPauta

from testes.test_servidor_base import ServidorDeTeste
from testes.test_servidor_pauta import ServicoPautaFalso, modulo_falso


class TestMonitor(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        ServicoPautaFalso.instancias = []
        p = mock.patch.dict(sys.modules, modulo_falso())
        p.start()
        self.addCleanup(p.stop)
        self.servico = self.app.pauta()
        self.monitor = MonitorPauta(self.app)
        self.app.monitor = self.monitor

    def sincronizacoes(self) -> list:
        return [c for c in self.servico.chamadas if c[0] == "sincronizar"]

    def test_desligado_nao_sincroniza(self):
        self.assertEqual(self.monitor.ciclo(), SEM_PAUTA_S)
        self.assertEqual(self.sincronizacoes(), [])
        self.assertIsNone(self.monitor.proxima)

    def test_ainda_no_intervalo(self):
        self.servico.configurar_monitoramento(True, 6)
        self.servico._ultima = datetime.now() - timedelta(hours=2)
        espera = self.monitor.ciclo()
        self.assertAlmostEqual(espera, 4 * 3600, delta=5)
        self.assertEqual(self.sincronizacoes(), [])
        self.assertEqual(self.monitor.proxima, self.servico._ultima + timedelta(hours=6))

    def test_passou_do_intervalo_sincroniza_as_fontes_com_rota(self):
        self.servico.configurar_monitoramento(True, 3)
        self.servico._fontes.append({"id": "sem-rota", "tribunal": "TJAL", "sistema": "eproc",
                                     "rotulo": "x", "url": ""})
        self.cfg.definir("pauta", "dias_atras", "2")
        self.cfg.definir("pauta", "dias_a_frente", "10")
        leitor = self.eventos()
        espera = self.monitor.ciclo()
        self.assertEqual(espera, 3 * 3600)
        _, fontes, de, ate = self.sincronizacoes()[0]
        self.assertEqual(fontes, ["f1"])
        self.assertEqual((de, ate), (date.today() - timedelta(days=2),
                                     date.today() + timedelta(days=10)))
        tarefa = leitor.esperar("tarefa", lambda d: d["tipo"] == "pauta_sincronizar"
                                and d["estado"] == "concluida")
        self.assertEqual(tarefa["titulo"], "Monitoramento da pauta")
        self.assertIsNotNone(self.monitor.proxima)

    def test_mensagem_com_varias_fontes(self):
        texto = modulo_monitor.mensagem_presenca([{"rotulo": "TJAL · e-SAJ"},
                                                   {"tribunal": "trf4", "sistema": "eproc"}])
        self.assertIn("TJAL · e-SAJ e TRF4 · eProc", texto)

    def test_codigo_pedido_nao_bloqueia_e_vira_pendencia(self):
        self.servico.configurar_monitoramento(True, 6)
        self.servico.pedir_codigo = True
        leitor = self.eventos()
        inicio = time.monotonic()
        self.monitor.ciclo()
        self.assertLess(time.monotonic() - inicio, 10)
        self.assertIn(("codigo", None), self.servico.chamadas)
        aviso = leitor.esperar("aviso", lambda d: d["titulo"] == "Monitoramento da pauta")
        self.assertIn("Entre no portal", aviso["mensagem"])
        self.assertFalse(any(t == "pergunta" for t, _ in leitor.recebidos))
        pendencias = self.cliente.dados("GET", "/api/estado")["pendencias"]
        self.assertIn("pauta_login", [p["chave"] for p in pendencias])
        # a sincronização feita pelo usuário (que responde ao código) limpa a pendência
        self.servico.pedir_codigo = False
        tarefa = self.esperar_tarefa(self.cliente.dados("POST", "/api/pauta/sincronizar")["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida")
        pendencias = self.cliente.dados("GET", "/api/estado")["pendencias"]
        self.assertNotIn("pauta_login", [p["chave"] for p in pendencias])

    def test_certificado_ou_sem_senha_nao_diz_que_pediu_codigo(self):
        """Quem entra por certificado, pela entrada manual ou sem a senha
        guardada: nada de tarefa que falha a cada ciclo nem de "o portal pediu
        o código" - a pendência diz o que acontece e o que fazer, uma vez."""
        self.servico.configurar_monitoramento(True, 6)
        self.servico.exige_presenca = lambda fonte: True
        leitor = self.eventos()
        espera = self.monitor.ciclo()
        self.assertEqual(espera, 6 * 3600)
        self.assertEqual(self.sincronizacoes(), [])          # nenhuma tentativa de login
        pendencia = [p for p in self.cliente.dados("GET", "/api/estado")["pendencias"]
                     if p["chave"] == "pauta_login"][0]
        self.assertIn("não entra sozinho em TJAL · e-SAJ", pendencia["mensagem"])
        self.assertIn("certificado", pendencia["mensagem"])
        self.assertIn("Conferir sozinho", pendencia["mensagem"])
        self.assertNotIn("pediu o código", pendencia["mensagem"])
        self.assertFalse(any(t == "tarefa" for t, _ in leitor.recebidos))
        # a sincronização à mão limpa a pendência, e o ciclo seguinte não a repõe
        self.app.pendencia_pauta = None
        self.monitor.ciclo()
        pendencias = self.cliente.dados("GET", "/api/estado")["pendencias"]
        self.assertNotIn("pauta_login", [p["chave"] for p in pendencias])

    def proxima_na_tela(self):
        """A “Próxima: …” que a tela Pauta mostra (GET /api/pauta)."""
        return self.cliente.dados("GET", "/api/pauta")["monitoramento"].get("proxima")

    def test_so_fontes_que_exigem_a_pessoa_nao_anunciam_proxima(self):
        """Ninguém entra sozinho (certificado, entrada manual, senha não
        guardada): a tela Pauta não pode dizer “Próxima: hoje, 15:00” logo
        acima do aviso de que o monitoramento não entra no portal."""
        self.servico.configurar_monitoramento(True, 6)
        self.servico.exige_presenca = lambda fonte: True
        self.assertEqual(self.monitor.ciclo(), 6 * 3600)        # o monitor reavalia
        self.assertIsNone(self.monitor.proxima)
        self.assertIsNone(self.proxima_na_tela())
        self.assertIsNotNone(self.app.pendencia_pauta)          # a pendência diz o que fazer

    def test_sincronizou_a_mao_sem_fonte_automatica_nao_anuncia_proxima(self):
        """Quem entra por certificado e sincronizou à mão há 2 h: nada de
        “Próxima” daqui a 4 h — ela não vai acontecer sozinha."""
        self.servico.configurar_monitoramento(True, 6)
        self.servico.exige_presenca = lambda fonte: True
        self.servico._ultima = datetime.now() - timedelta(hours=2)
        self.assertAlmostEqual(self.monitor.ciclo(), 4 * 3600, delta=5)
        self.assertIsNone(self.monitor.proxima)
        self.assertIsNone(self.proxima_na_tela())
        self.assertEqual(self.sincronizacoes(), [])

    def test_sem_fonte_com_rota_nao_anuncia_proxima(self):
        self.servico.configurar_monitoramento(True, 6)
        self.servico._fontes[0]["url"] = ""
        self.assertEqual(self.monitor.ciclo(), 6 * 3600)
        self.assertIsNone(self.monitor.proxima)
        self.assertIsNone(self.proxima_na_tela())
        self.assertEqual(self.sincronizacoes(), [])

    def test_com_fonte_automatica_anuncia_proxima(self):
        self.servico.configurar_monitoramento(True, 6)
        self.servico._ultima = datetime.now() - timedelta(hours=2)
        self.monitor.ciclo()
        self.assertEqual(self.monitor.proxima, self.servico._ultima + timedelta(hours=6))
        self.assertEqual(self.proxima_na_tela()[:16],
                         (self.servico._ultima + timedelta(hours=6)).isoformat()[:16])

    def test_presenca_descoberta_na_sincronizacao(self):
        """A regra não pôde ser vista antes (ServicoPauta._acesso marca
        pediu_login sem pergunta nenhuma): também não é "pediu o código"."""
        self.servico.configurar_monitoramento(True, 6)

        def sincronizar(ctx, fontes, de, ate):
            self.servico.chamadas.append(("sincronizar", fontes, de, ate))
            ctx.pediu_login = True
            raise RuntimeError("Entre no portal para continuar o monitoramento: sem a senha "
                               "guardada (ou no login por certificado)...")

        self.servico.sincronizar = sincronizar
        self.monitor.ciclo()
        pendencia = self.app.pendencia_pauta
        self.assertIsNotNone(pendencia)
        self.assertIn("não entra sozinho", pendencia["mensagem"])
        self.assertNotIn("pediu o código", pendencia["mensagem"])

    def test_regra_da_presenca_so_pela_api_publica(self):
        """O monitor não entra nos internos da pauta (_tribunal, _opcoes,
        _credenciais): vale o 'exige_presenca' de ServicoPauta.fontes() ou,
        sem ele, ServicoPauta.exige_presenca(fonte)."""
        class SoInternos:
            def _tribunal(self, *a):
                raise AssertionError("o monitor usou um interno da pauta")

            _opcoes = _credenciais = _tribunal

        class Publica:
            def __init__(self, resposta):
                self.resposta = resposta

            def exige_presenca(self, fonte):
                if isinstance(self.resposta, Exception):
                    raise self.resposta
                return self.resposta

        fonte = {"id": "f1", "tribunal": "TJAL", "sistema": "esaj"}
        exige = MonitorPauta.exige_presenca
        # o que fontes() já disse vale, sem perguntar de novo
        self.assertTrue(exige(Publica(False), dict(fonte, exige_presenca=True)))
        self.assertFalse(exige(Publica(True), dict(fonte, exige_presenca=False)))
        # sem a marca, a função pública
        self.assertTrue(exige(Publica(True), fonte))
        self.assertFalse(exige(Publica(False), fonte))
        # na dúvida, tenta: a sincronização decide
        self.assertFalse(exige(Publica(RuntimeError("cofre")), fonte))
        self.assertFalse(exige(SoInternos(), fonte))
        self.assertFalse(exige(object(), fonte))

    def test_navegador_ocupado_adia(self):
        self.servico.configurar_monitoramento(True, 6)
        segurar = threading.Event()
        self.addCleanup(segurar.set)

        def baixar(*a, **kw):
            segurar.wait(10)
            raise RuntimeError("fim")

        with mock.patch("helestron.servicos.baixar_lote", side_effect=baixar):
            self.cliente.dados("POST", "/api/download/iniciar",
                               {"processos": ["0700123-83.2024.8.02.0001"]})
            self.assertEqual(self.monitor.ciclo(), ADIAR_S)
            segurar.set()
        self.assertEqual(self.sincronizacoes(), [])

    def test_sem_pauta_instalada(self):
        with mock.patch.dict(sys.modules, {"helestron.pauta": None,
                                           "helestron.pauta.servico": None}):
            self.app._pauta = None
            self.assertEqual(MonitorPauta(self.app).ciclo(), SEM_PAUTA_S)

    def test_thread_acorda_e_para(self):
        self.servico.configurar_monitoramento(True, 6)
        monitor = MonitorPauta(self.app, atraso_inicial_s=3600).iniciar()
        self.assertTrue(monitor.ativo)
        monitor.acordar()
        limite = time.monotonic() + 10
        while not self.sincronizacoes() and time.monotonic() < limite:
            time.sleep(0.05)
        self.assertEqual(len(self.sincronizacoes()), 1)
        monitor.parar()
        monitor._thread.join(5)
        self.assertFalse(monitor.ativo)

    def test_configurar_pela_api_acorda(self):
        with mock.patch.object(self.monitor, "acordar") as acordar:
            self.cliente.dados("POST", "/api/config", {"secao": "pauta", "chave": "monitorar",
                                                       "valor": True})
        acordar.assert_called_once()


class TestProximaComOServicoReal(ServidorDeTeste):
    """A “Próxima: …” da tela Pauta com o ServicoPauta e o MonitorPauta de
    verdade, como no programa aberto: a fonte do e-SAJ com a rota, mas sem a
    senha guardada (ou com o certificado)."""

    def setUp(self):
        super().setUp()
        self.monitor = MonitorPauta(self.app)
        self.app.monitor = self.monitor
        self.cliente.dados("POST", "/api/pauta/fontes", {
            "tribunal": "TJAL", "sistema": "esaj",
            "url": "https://www2.tjal.jus.br/sajcas/agendaAudiencias"})
        self.cliente.dados("POST", "/api/pauta/monitoramento", {"ativo": True, "intervalo_horas": 6})

    def test_sem_fonte_monitorada_nao_ha_proxima(self):
        for modo in ("senha", "certificado"):
            with self.subTest(modo=modo):
                self.cfg.definir("esaj", "login", modo)
                fonte = self.cliente.dados("GET", "/api/pauta/fontes")[0]
                self.assertTrue(fonte["exige_presenca"])
                self.assertFalse(fonte["monitorada"])
                self.monitor.ciclo()
                self.assertIsNone(self.monitor.proxima)
                estado = self.cliente.dados("GET", "/api/pauta")["monitoramento"]
                self.assertEqual(estado["fontes_monitoradas"], 0)
                self.assertIsNone(estado["proxima"])
        self.assertEqual([t for t in self.cliente.dados("GET", "/api/tarefas")
                          if t.get("tipo") == "pauta_sincronizar"], [])


class TestPresencaComOServicoReal(unittest.TestCase):
    """A regra do monitor bate com a do ServicoPauta de verdade (_acesso)."""

    def setUp(self):
        from testes.test_servidor_base import AmbienteTemporario

        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)

    def test_regra(self):
        from helestron.pauta.servico import ServicoPauta

        class Cofre:
            guardado = ("", "")

            def obter(self, portal):
                return self.guardado

        cofre = Cofre()
        servico = ServicoPauta(self.amb.cfg, arquivo_banco=self.amb.local / "pauta.sqlite3",
                               cofre=cofre)
        fonte = {"id": "f1", "tribunal": "TJAL", "sistema": "esaj"}
        for modo, guardado, exige in (("certificado", ("u", "s"), True), ("manual", ("u", "s"), True),
                                      ("senha", ("", ""), True), ("senha", ("u", "s"), False)):
            with self.subTest(modo=modo, guardado=guardado):
                self.amb.cfg.definir("esaj", "login", modo)
                cofre.guardado = guardado
                self.assertEqual(MonitorPauta.exige_presenca(servico, fonte), exige)


if __name__ == "__main__":
    unittest.main()
