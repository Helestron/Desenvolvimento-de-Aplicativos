"""Pauta: quando o monitor sincroniza sozinho (seção 8.7), com relógio falso."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from helestron.pauta.monitor import (ADIAR_S, SEM_MONITORAMENTO_S, Agenda, ConfigMonitoramento,
                                     Monitor)
from helestron.pauta.servico import ServicoPauta

from testes import apoio_download as apoio
from testes import apoio_pauta as ap


class Relogio:
    def __init__(self, inicio: datetime):
        self.agora = inicio

    def __call__(self) -> datetime:
        return self.agora

    def andar(self, **delta) -> None:
        self.agora += timedelta(**delta)


T0 = datetime(2026, 10, 5, 8, 0)


class TestAgenda(unittest.TestCase):
    def setUp(self):
        self.relogio = Relogio(T0)
        self.agenda = Agenda(self.relogio)
        self.conf = ConfigMonitoramento()

    def test_desligado_e_sem_fontes(self):
        d = self.agenda.avaliar(ConfigMonitoramento(ativo=False), None, True)
        self.assertEqual((d.sincronizar, d.esperar_s, d.proxima, d.motivo),
                         (False, SEM_MONITORAMENTO_S, None, "desligado"))
        d = self.agenda.avaliar(self.conf, None, False)
        self.assertEqual((d.sincronizar, d.esperar_s, d.motivo), (False, 6 * 3600, "sem_fontes"))
        self.assertIsNone(self.agenda.proxima(self.conf, None, False))

    def test_ao_abrir_e_a_cada_intervalo(self):
        d = self.agenda.avaliar(self.conf, None, True)
        self.assertEqual((d.sincronizar, d.motivo, d.proxima), (True, "primeira",
                                                                T0 + timedelta(hours=6)))
        # sincronizou há 2 h: espera as 4 que faltam
        ultima = T0 - timedelta(hours=2)
        d = self.agenda.avaliar(self.conf, ultima, True)
        self.assertEqual((d.sincronizar, d.motivo, d.esperar_s, d.proxima),
                         (False, "em_dia", 4 * 3600, T0 + timedelta(hours=4)))
        self.assertEqual(self.agenda.proxima(self.conf, ultima, True), T0 + timedelta(hours=4))
        # o programa ficou fechado de um dia para o outro: sincroniza ao abrir
        d = self.agenda.avaliar(self.conf, T0 - timedelta(days=1), True)
        self.assertEqual((d.sincronizar, d.motivo), (True, "vencida"))
        self.assertEqual(self.agenda.proxima(self.conf, T0 - timedelta(days=1), True), T0)
        # intervalo de 1 h, exatamente vencido
        d = self.agenda.avaliar(ConfigMonitoramento(intervalo_horas=1), T0 - timedelta(hours=1),
                                True)
        self.assertTrue(d.sincronizar)

    def test_periodo(self):
        self.assertEqual(self.conf.periodo(date(2026, 10, 5)),
                         (date(2026, 9, 28), date(2026, 12, 4)))
        self.assertEqual(ConfigMonitoramento(dias_atras=0, dias_a_frente=0).periodo(
            date(2026, 10, 5)), (date(2026, 10, 5), date(2026, 10, 6)))


class TestMonitor(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.amb = ap.config_temporaria(self.tmp, intervalo_horas=4, dias_atras=2,
                                        dias_a_frente=10)
        self.relogio = Relogio(T0)
        self.servico = ServicoPauta(self.amb.cfg, self.tmp / "p.sqlite3", relogio=self.relogio)
        self.addCleanup(self.servico.fechar)
        self.chamadas = []
        self.ocupado = False

        def sincronizar(fontes, de, ate):
            self.chamadas.append((self.relogio(), fontes, de, ate))
            if self.ocupado:
                return False
            self.servico.armazem.definir_meta("ultima_sincronizacao", self.relogio())
            return True

        self.monitor = Monitor(self.servico, sincronizar, relogio=self.relogio)

    def test_um_dia_de_monitoramento(self):
        # sem fonte com rota: nada a fazer
        self.assertEqual(self.monitor.ciclo(), 4 * 3600)
        self.assertEqual(self.chamadas, [])
        self.servico.salvar_fonte("TJAL", "esaj", "")          # sem rota: ainda não
        self.assertEqual(self.monitor.ciclo(), 4 * 3600)
        self.servico.salvar_fonte("TJAL", "eproc", "", "https://eproc/pauta")
        # ao abrir: sincroniza já, só a fonte com rota, no período do config.ini
        espera = self.monitor.ciclo()
        self.assertEqual(espera, 4 * 3600)
        self.assertEqual(self.chamadas, [(T0, ["eproc-tjal"], date(2026, 10, 3),
                                          date(2026, 10, 15))])
        self.assertEqual(self.monitor.proxima, T0 + timedelta(hours=4))
        # 1 h depois: ainda em dia
        self.relogio.andar(hours=1)
        self.assertEqual(self.monitor.ciclo(), 3 * 3600)
        self.assertEqual(len(self.chamadas), 1)
        # 4 h depois: de novo; o navegador estava ocupado (um download): adia
        self.relogio.andar(hours=3)
        self.ocupado = True
        self.assertEqual(self.monitor.ciclo(), ADIAR_S)
        self.assertEqual(self.monitor.proxima, self.relogio() + timedelta(seconds=ADIAR_S))
        self.relogio.andar(seconds=ADIAR_S)
        self.ocupado = False
        self.assertEqual(self.monitor.ciclo(), 4 * 3600)
        self.assertEqual(len(self.chamadas), 3)
        # desligado pela tela
        self.servico.configurar_monitoramento(False, 4)
        self.relogio.andar(hours=10)
        self.assertEqual(self.monitor.ciclo(), SEM_MONITORAMENTO_S)
        self.assertIsNone(self.monitor.proxima)
        self.assertEqual(len(self.chamadas), 3)
        self.assertEqual(self.monitor.ultima_decisao.motivo, "desligado")


if __name__ == "__main__":
    unittest.main()
