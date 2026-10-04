"""O monitor da pauta (seção 8.7): quando sincroniza, e que não bloqueia em perguntas."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
