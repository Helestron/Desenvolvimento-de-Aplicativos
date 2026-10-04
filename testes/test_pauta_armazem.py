"""Pauta: o banco SQLite - upsert, histórico, removidas, remarcadas, fontes e recuperação."""

from __future__ import annotations

import sqlite3
import threading
import unittest
from datetime import date, datetime, timezone

from helestron.pauta import modelos
from helestron.pauta.armazem import Armazem

from testes import apoio_download as apoio
from testes import apoio_pauta as ap

D1, D2, D3 = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)
PERIODO = (date(2026, 10, 1), date(2026, 10, 31))
T0, T1, T2 = datetime(2026, 10, 3, 9, 0), datetime(2026, 10, 3, 15, 0), datetime(2026, 10, 4, 9, 0)


def aud(seq: str, data_=D1, hora="09:00", tipo="Conciliação", situacao="Designada", **extra):
    return modelos.nova(sistema="esaj", tribunal="TJAL", data_=data_, processo=ap.numero(seq),
                        hora=hora, tipo_original=tipo, situacao_original=situacao, **extra)


class TestArmazem(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.banco = Armazem(self.tmp / "local" / "pauta.sqlite3")
        self.addCleanup(self.banco.fechar)

    def test_wal_e_esquema(self):
        con = sqlite3.connect(str(self.banco.arquivo))
        self.addCleanup(con.close)
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        tabelas = {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"audiencias", "alteracoes", "fontes", "meta"}, tabelas)
        self.assertEqual(self.banco.meta("versao"), "1")

    def test_primeira_gravacao_sem_historico_e_upsert(self):
        b = self.banco.gravar([aud("0700101"), aud("0700102", hora="10:00")], "esaj-tjal",
                              PERIODO, registrar_novas=False, agora=T0)
        self.assertEqual((b.novas, b.atualizadas, b.removidas, b.alteracoes), (2, 0, 0, 0))
        self.assertEqual(self.banco.alteracoes(), [], "a primeira sincronização é a base")
        # a mesma pauta de novo: nada muda
        b = self.banco.gravar([aud("0700101"), aud("0700102", hora="10:00")], "esaj-tjal",
                              PERIODO, agora=T1)
        self.assertEqual((b.novas, b.atualizadas, b.inalteradas, b.alteracoes), (0, 0, 2, 0))
        self.assertEqual(len(self.banco.listar(*PERIODO)), 2)

    def test_nova_alterada_cancelada(self):
        self.banco.gravar([aud("0700101"), aud("0700102", hora="10:00")], "esaj-tjal", PERIODO,
                          registrar_novas=False, agora=T0)
        b = self.banco.gravar([
            aud("0700101", local="Sala 2"),
            aud("0700102", hora="10:00", situacao="Cancelada"),
            aud("0700103", data_=D2)], "esaj-tjal", PERIODO, agora=T1)
        self.assertEqual((b.novas, b.atualizadas, b.canceladas, b.alteracoes), (1, 2, 1, 3))
        alts = {a["audiencia"]["processo"]: a for a in self.banco.alteracoes()}
        self.assertEqual(alts[ap.numero("0700103")]["tipo"], "nova")
        self.assertEqual(alts[ap.numero("0700101")]["tipo"], "alterada")
        self.assertEqual(alts[ap.numero("0700101")]["campos"],
                         [{"campo": "local", "antes": "", "depois": "Sala 2"}])
        cancelada = alts[ap.numero("0700102")]
        self.assertEqual(cancelada["tipo"], "cancelada")
        self.assertEqual(cancelada["campos"], [{"campo": "situacao", "antes": "Designada",
                                                "depois": "Cancelada"}])
        self.assertEqual(cancelada["quando"], T1.isoformat())
        self.assertEqual(self.banco.nao_vistas(), 3)
        self.assertEqual(self.banco.marcar_vistas(), 3)
        self.assertEqual(self.banco.nao_vistas(), 0)
        self.assertTrue(all(a["vista"] for a in self.banco.alteracoes()))

    def test_removida_no_periodo_conferido_e_volta(self):
        self.banco.gravar([aud("0700101"), aud("0700102", data_=D3)], "esaj-tjal", PERIODO,
                          registrar_novas=False, agora=T0)
        # a 0700102 não veio mais (e o 0700101 é de outra fonte: não conta)
        b = self.banco.gravar([aud("0700101")], "esaj-tjal", PERIODO, agora=T1)
        self.assertEqual(b.removidas, 1)
        self.assertEqual([a.processo for a in self.banco.listar(*PERIODO)], [ap.numero("0700101")])
        removida = aud("0700102", data_=D3)
        self.assertTrue(self.banco.removida(removida.id), "marcada, não apagada")
        self.assertEqual(len(self.banco.listar(*PERIODO, incluir_removidas=True)), 2)
        self.assertEqual(self.banco.alteracoes()[0]["tipo"], "removida")
        # fora do período conferido nada se remove
        b = self.banco.gravar([], "esaj-tjal", (date(2026, 11, 1), date(2026, 11, 30)), agora=T1)
        self.assertEqual(b.removidas, 0)
        # sem período (captura, importação) nada se remove
        self.assertEqual(self.banco.gravar([], "esaj-tjal", None).removidas, 0)
        # ela voltou à pauta
        b = self.banco.gravar([aud("0700101"), aud("0700102", data_=D3)], "esaj-tjal", PERIODO,
                              agora=T2)
        self.assertEqual(b.novas, 1)
        self.assertFalse(self.banco.removida(removida.id))
        self.assertEqual(self.banco.alteracoes()[0]["tipo"], "nova")

    def test_outra_fonte_nao_remove(self):
        self.banco.gravar([aud("0700101")], "esaj-tjal", PERIODO, registrar_novas=False)
        self.banco.gravar([aud("0700201")], "eproc-tjal", PERIODO, registrar_novas=False)
        b = self.banco.gravar([], "eproc-tjal", PERIODO)
        self.assertEqual(b.removidas, 1)
        self.assertEqual([a.processo for a in self.banco.listar(*PERIODO)], [ap.numero("0700101")])

    def test_remarcada_vira_alteracao_e_nao_nova_mais_removida(self):
        self.banco.gravar([aud("0700101", hora="09:00"), aud("0700102")], "esaj-tjal", PERIODO,
                          registrar_novas=False, agora=T0)
        b = self.banco.gravar([aud("0700101", data_=D2, hora="14:00"), aud("0700102")],
                              "esaj-tjal", PERIODO, agora=T1)
        self.assertEqual((b.novas, b.atualizadas, b.removidas), (0, 1, 0))
        alts = self.banco.alteracoes()
        self.assertEqual(len(alts), 1)
        self.assertEqual(alts[0]["tipo"], "alterada")
        self.assertEqual(alts[0]["campos"], [
            {"campo": "data", "antes": "2026-10-05", "depois": "2026-10-06"},
            {"campo": "hora", "antes": "09:00", "depois": "14:00"}])
        lista = self.banco.listar(*PERIODO, incluir_removidas=True)
        self.assertEqual(len(lista), 2, "o registro antigo foi substituído, não duplicado")
        self.assertEqual(alts[0]["audiencia"]["hora"], "14:00")

    def test_duas_do_mesmo_processo_nao_se_pareiam(self):
        self.banco.gravar([aud("0700101", hora="09:00"), aud("0700101", hora="10:00")],
                          "esaj-tjal", PERIODO, registrar_novas=False)
        b = self.banco.gravar([aud("0700101", hora="11:00")], "esaj-tjal", PERIODO)
        self.assertEqual((b.novas, b.removidas), (1, 2), "na dúvida, não se adivinha")

    def test_vazio_nao_apaga_e_sigilo_fica(self):
        self.banco.gravar([aud("0700101", local="Sala 1", partes="A x B", sigiloso=True)],
                          "esaj-tjal", PERIODO, registrar_novas=False)
        b = self.banco.gravar([aud("0700101")], "esaj-tjal", PERIODO)
        self.assertEqual(b.atualizadas, 0)
        a = self.banco.listar(*PERIODO)[0]
        self.assertEqual((a.local, a.partes, a.sigiloso), ("Sala 1", "A x B", True))

    def test_transacao_desfeita_em_erro(self):
        boa = aud("0700101")
        ruim = aud("0700102")
        ruim.data = "não é data"          # quebra no meio da gravação
        with self.assertRaises(Exception):
            self.banco.gravar([boa, ruim], "esaj-tjal", PERIODO)
        self.assertEqual(self.banco.listar(*PERIODO), [], "nem meia pauta fica gravada")

    def test_fontes(self):
        f = self.banco.salvar_fonte("tjal", "ESAJ", "TJAL · e-SAJ")
        self.assertEqual((f["id"], f["tribunal"], f["sistema"], f["modo"], f["url"],
                          f["ultima_sincronizacao"], f["monitorada"]),
                         ("esaj-tjal", "TJAL", "esaj", "automatico", "", None, False))
        self.banco.atualizar_fonte("esaj-tjal", url="https://portal/pauta", ultima_sincronizacao=T1)
        # salvar de novo sem endereço não esquece a rota lembrada
        f = self.banco.salvar_fonte("TJAL", "esaj", "")
        self.assertEqual((f["url"], f["rotulo"], f["ultima_sincronizacao"], f["monitorada"]),
                         ("https://portal/pauta", "TJAL · e-SAJ", T1.isoformat(), True))
        f = self.banco.salvar_fonte("TJAL", "eproc", "eProc", "https://eproc/pauta")
        self.assertEqual(f["modo"], "capturado")
        self.assertEqual([x["id"] for x in self.banco.fontes()], ["eproc-tjal", "esaj-tjal"])
        self.banco.gravar([aud("0700101")], "eproc-tjal", None)
        self.assertTrue(self.banco.remover_fonte("eproc-tjal"))
        self.assertFalse(self.banco.remover_fonte("eproc-tjal"))
        self.assertEqual(len(self.banco.listar(*PERIODO)), 1, "as audiências ficam na pauta")

    def test_banco_corrompido_e_posto_de_lado(self):
        self.banco.fechar()
        arquivo = self.tmp / "estragado.sqlite3"
        arquivo.write_bytes(b"isto nao e um banco sqlite" * 100)
        with self.assertLogs("pauta.armazem", "ERROR") as registro:
            outro = Armazem(arquivo)
        self.addCleanup(outro.fechar)
        self.assertIn("ilegível", registro.output[0])
        self.assertEqual(outro.contar(), 0)
        self.assertTrue(list(self.tmp.glob("estragado.corrompido-*.sqlite3")))
        outro.gravar([aud("0700101")], "x", None)
        self.assertEqual(outro.contar(), 1)

    def test_threads_simultaneas(self):
        erros = []

        def gravar(seq):
            try:
                for i in range(15):
                    self.banco.gravar([aud(f"07{seq}{i:03d}")], f"f{seq}", PERIODO)
                    self.banco.listar(*PERIODO)
            except Exception as erro:          # pragma: no cover - é o que o teste procura
                erros.append(erro)

        threads = [threading.Thread(target=gravar, args=(f"{s:02d}",)) for s in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(erros, [])
        self.assertEqual(self.banco.contar(), 4)    # cada fonte ficou só com a última

    def test_alteracoes_por_periodo_e_desde(self):
        self.banco.gravar([aud("0700101", data_=D1), aud("0700102", data_=date(2026, 12, 1))],
                          "esaj-tjal", None, agora=T0)
        self.assertEqual(len(self.banco.alteracoes()), 2)
        self.assertEqual(len(self.banco.alteracoes(de=PERIODO[0], ate=PERIODO[1])), 1)
        self.assertEqual(self.banco.alteracoes(desde=T1), [])
        self.assertEqual(len(self.banco.alteracoes(desde=T0)), 2)
        # o 'desde' com fuso (a página manda em UTC) vale pela hora local
        com_fuso = T1.astimezone().astimezone(timezone.utc)
        self.assertEqual(self.banco.alteracoes(desde=com_fuso), [])
        self.assertEqual(len(self.banco.alteracoes(desde=T0.astimezone())), 2)


class TestRelatorioImportadoEPortal(apoio.PastaTemporaria):
    """A audiência do relatório importado que o portal traz depois é absorvida
    pelo registro do portal - no mesmo processo, data e hora."""

    def setUp(self):
        super().setUp()
        self.banco = Armazem(self.tmp / "local" / "pauta.sqlite3")
        self.addCleanup(self.banco.fechar)

    def importada(self, seq, **extra):
        a = modelos.nova(sistema="arquivo", tribunal="TJAL", data_=extra.pop("data_", D1),
                         processo=ap.numero(seq), hora=extra.pop("hora", "09:00"),
                         tipo_original=extra.pop("tipo", ""), fonte="arquivo", **extra)
        self.banco.gravar([a], "arquivo", None, registrar_novas=False, agora=T0)
        return a

    def test_absorve_completa_e_nao_e_nova(self):
        self.importada("0700101", local="Sala 9", partes="A x B", sigiloso=True)
        self.importada("0700102", hora="10:00")          # outra hora: outra audiência
        b = self.banco.gravar([aud("0700101", local="")], "esaj-tjal", PERIODO, agora=T1)
        self.assertEqual((b.novas, b.inalteradas, b.alteracoes), (0, 1, 0))
        lista = self.banco.listar(*PERIODO, incluir_removidas=True)
        self.assertEqual(sorted((a.sistema, a.processo[:7]) for a in lista),
                         [("arquivo", "0700102"), ("esaj", "0700101")])
        portal = next(a for a in lista if a.sistema == "esaj")
        self.assertEqual((portal.local, portal.partes, portal.sigiloso), ("Sala 9", "A x B", True))
        self.assertEqual(self.banco.sigilosas()[0], {modelos.chave_processo(ap.numero("0700101"))})

    def test_remarcada_no_portal_com_a_importada_no_meio(self):
        self.banco.gravar([aud("0700101", hora="09:00")], "esaj-tjal", PERIODO,
                          registrar_novas=False, agora=T0)
        self.importada("0700101", hora="10:00")
        b = self.banco.gravar([aud("0700101", hora="10:00")], "esaj-tjal", PERIODO, agora=T1)
        self.assertEqual((b.novas, b.atualizadas, b.removidas, b.inalteradas), (0, 1, 0, 0))
        self.assertEqual([(a.sistema, a.hora) for a in
                          self.banco.listar(*PERIODO, incluir_removidas=True)], [("esaj", "10:00")])
        self.assertEqual([x["tipo"] for x in self.banco.alteracoes()], ["alterada"])

    def test_duas_no_mesmo_horario_cada_uma_absorve_a_sua(self):
        """Uma Conciliação cancelada e uma Instrução designada do mesmo processo, no
        mesmo horário, no relatório e depois no portal: o par é pelo tipo - nada de
        "nova" nem de "cancelada" falsa, e cada uma fica com a sua sala."""
        for ordem in (0, 1):
            with self.subTest(ordem=ordem):
                banco = Armazem(self.tmp / f"ordem{ordem}" / "pauta.sqlite3")
                self.addCleanup(banco.fechar)
                do_relatorio = [
                    modelos.nova(sistema="arquivo", tribunal="TJAL", data_=D1,
                                 processo=ap.numero("0700101"), hora="09:00",
                                 tipo_original="Conciliação", situacao_original="Cancelada",
                                 local="Sala 1", fonte="arquivo"),
                    modelos.nova(sistema="arquivo", tribunal="TJAL", data_=D1,
                                 processo=ap.numero("0700101"), hora="09:00",
                                 tipo_original="Instrução", situacao_original="Designada",
                                 local="Sala 2 (relatório)", partes="Fulano x Beltrano",
                                 fonte="arquivo")]
                if ordem:
                    do_relatorio.reverse()
                banco.gravar(do_relatorio, "arquivo", None, registrar_novas=False, agora=T0)
                b = banco.gravar([aud("0700101", tipo="Conciliação", situacao="Cancelada"),
                                  aud("0700101", tipo="Instrução", situacao="Designada")],
                                 "esaj-tjal", PERIODO, agora=T1)
                self.assertEqual((b.novas, b.atualizadas, b.canceladas, b.inalteradas,
                                  b.alteracoes), (0, 0, 0, 2, 0))
                self.assertEqual(banco.alteracoes(), [])
                self.assertEqual(sorted(
                    (a.sistema, a.tipo, a.situacao, a.local, a.partes)
                    for a in banco.listar(*PERIODO, incluir_removidas=True)), [
                    ("esaj", "Conciliação", "Cancelada", "Sala 1", ""),
                    ("esaj", "Instrução e julgamento", "Designada", "Sala 2 (relatório)",
                     "Fulano x Beltrano")])

    def test_a_do_relatorio_sem_par_fica(self):
        self.importada("0700101", tipo="Conciliação", local="Sala 1")
        self.importada("0700101", tipo="Instrução", local="Sala 2")
        b = self.banco.gravar([aud("0700101", tipo="Conciliação")], "esaj-tjal", PERIODO,
                              agora=T1)
        self.assertEqual((b.novas, b.inalteradas), (0, 1))
        self.assertEqual(sorted((a.sistema, a.tipo, a.local) for a in
                                self.banco.listar(*PERIODO, incluir_removidas=True)), [
            ("arquivo", "Instrução e julgamento", "Sala 2"), ("esaj", "Conciliação", "Sala 1")])

    def test_um_de_cada_lado_com_tipos_diferentes_ainda_e_a_mesma(self):
        self.importada("0700101", tipo="Audiência", local="Sala 9")
        b = self.banco.gravar([aud("0700101", tipo="Una")], "esaj-tjal", PERIODO, agora=T1)
        self.assertEqual((b.novas, b.inalteradas), (0, 1))
        self.assertEqual([(a.sistema, a.tipo, a.local) for a in
                          self.banco.listar(*PERIODO, incluir_removidas=True)],
                         [("esaj", "Una", "Sala 9")])

    def test_contar_com_as_removidas(self):
        self.banco.gravar([aud("0700101")], "esaj-tjal", PERIODO, registrar_novas=False)
        self.banco.gravar([], "esaj-tjal", PERIODO)
        self.assertEqual((self.banco.contar(), self.banco.contar(incluir_removidas=True)), (0, 1))


if __name__ == "__main__":
    unittest.main()
