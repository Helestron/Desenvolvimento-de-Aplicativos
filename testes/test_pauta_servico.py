"""Pauta: a fachada ServicoPauta (seção 8.10) - consulta, fontes, monitoramento e
sincronização (com o navegador e a leitura do portal substituídos por dublês)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from helestron.download import modelos as mdl
from helestron.pauta import modelos, navegacao
from helestron.pauta.navegacao import Leitura, PautaNaoEncontrada
from helestron.pauta.servico import ErroPauta, ServicoPauta
from helestron.pauta.tabelas import Reconhecimento

from testes import apoio_download as apoio
from testes import apoio_pauta as ap

AGORA = datetime(2026, 10, 5, 11, 0)


def aud(seq, data_, hora, tipo="Conciliação", situacao="Designada", sistema="esaj",
        tribunal="TJAL", **extra):
    tr = "21" if tribunal == "TJRS" else "02"
    return modelos.nova(sistema=sistema, tribunal=tribunal, data_=data_,
                        processo=ap.numero(seq, tr), hora=hora, tipo_original=tipo,
                        situacao_original=situacao, **extra)


class PortalFalso:
    instancias: list = []

    def __init__(self, nav, tribunal, opcoes, ctx, credenciais, falhas=None):
        self.nav, self.tribunal, self.opcoes = nav, tribunal, opcoes
        self.ctx, self.credenciais = ctx, credenciais
        self.sistema = tribunal.sistema
        self.base = "https://portal.invalid"
        self.nome = f"{tribunal.nome_sistema} do {tribunal.sigla}"
        self.entradas = 0
        self.falhas = list(falhas or [])
        PortalFalso.instancias.append(self)

    def entrar(self):
        self.entradas += 1
        if self.falhas:
            erro = self.falhas.pop(0)
            if erro is not None:
                raise erro


class ExtratorFalso:
    """Faz as vezes do ExtratorAutomatico: segue um roteiro por fonte."""

    roteiro: dict[str, list] = {}
    chamadas: list = []

    def __init__(self, nav, portal, regras, reconhecedor, ctx=None, fonte=None, espera_s=0):
        self.fonte = dict(fonte or {})
        self.reconhecedor = reconhecedor

    def extrair(self, de, ate):
        ExtratorFalso.chamadas.append((self.fonte["id"], de, ate, self.fonte.get("url")))
        passo = ExtratorFalso.roteiro[self.fonte["id"]].pop(0)
        if isinstance(passo, BaseException):
            raise passo
        audiencias, aplicado, url = passo
        leitura = Leitura(reconhecimento=Reconhecimento(audiencias=list(audiencias), tabelas=1),
                          paginas=1, periodo_aplicado=aplicado, url=url, menu="Pauta de Audiências")
        return leitura


class Base(apoio.PastaTemporaria):
    def setUp(self):
        super().setUp()
        self.amb = ap.config_temporaria(self.tmp)
        self.eventos = []
        self.cofre = apoio.CofreFalso({"esaj:TJAL": ("u", "s"), "eproc:TJRS": ("u", "s")})
        self.falhas_portal: dict[str, list] = {}
        PortalFalso.instancias = []
        apoio.NavegadorFalso.instancias = []
        ExtratorFalso.roteiro, ExtratorFalso.chamadas = {}, []

        def fabrica_portal(nav, tribunal, opcoes, ctx, credenciais):
            return PortalFalso(nav, tribunal, opcoes, ctx, credenciais,
                               self.falhas_portal.get(tribunal.sigla))

        self.agora = AGORA
        self.servico = ServicoPauta(self.amb.cfg, self.tmp / "local" / "pauta.sqlite3",
                                    eventos=lambda t, d: self.eventos.append((t, d)),
                                    fabrica_navegador=apoio.NavegadorFalso,
                                    fabrica_portal=fabrica_portal, cofre=self.cofre,
                                    relogio=lambda: self.agora)
        self.addCleanup(self.servico.fechar)
        p = mock.patch.object(navegacao, "ExtratorAutomatico", ExtratorFalso)
        p.start()
        self.addCleanup(p.stop)


class TestConsulta(Base):
    def setUp(self):
        super().setUp()
        d = AGORA.date()
        self.servico.armazem.gravar([
            aud("0700101", d, "09:00", partes="Maria José x Banco Bradesco"),     # já passou
            aud("0700102", d, "14:00", tipo="Una", partes="João x Município"),    # a próxima
            aud("0700103", d, "15:00", situacao="Cancelada"),
            aud("0700104", d + timedelta(days=2), "10:00", sistema="eproc", tribunal="TJRS",
                tipo="Custódia", local="Central de Custódia"),
            aud("0700105", d + timedelta(days=20), "10:00", situacao="Redesignada"),
        ], "x", None, registrar_novas=False)

    def test_listar_e_resumo(self):
        d = AGORA.date()
        dados = self.servico.listar(d, d + timedelta(days=30))
        self.assertEqual(len(dados["audiencias"]), 5)
        self.assertEqual(dados["resumo"], {
            "total": 5, "hoje": 2, "semana": 3,
            "por_situacao": {"Designada": 3, "Cancelada": 1, "Redesignada": 1},
            "por_tipo": {"Conciliação": 3, "Una": 1, "Custódia": 1}})
        filtrar = lambda **f: [a["processo"][:7] for a in  # noqa: E731
                               self.servico.listar(d, d + timedelta(days=30), **f)["audiencias"]]
        self.assertEqual(filtrar(sistema="eproc"), ["0700104"])
        self.assertEqual(filtrar(sistema="Todos"), filtrar())
        self.assertEqual(filtrar(situacao="cancelada"), ["0700103"])
        self.assertEqual(filtrar(situacao="Redesignada"), ["0700105"])
        self.assertEqual(filtrar(busca="maria jose"), ["0700101"])
        self.assertEqual(filtrar(busca="BRADESCO"), ["0700101"])
        self.assertEqual(filtrar(busca="0700104"), ["0700104"])
        self.assertEqual(filtrar(busca="custodia central"), ["0700104"])
        self.assertEqual(filtrar(busca="nada disso"), [])

    def test_resumo_inicio(self):
        r = self.servico.resumo_inicio()
        self.assertEqual((r["hoje"], r["semana"]), (2, 3))
        self.assertEqual(r["proxima"]["processo"][:7], "0700102", "a das 9h já passou; a das 15h "
                                                                  "foi cancelada")
        self.assertIsNone(r["ultima_sincronizacao"])
        self.assertEqual(r["alteracoes_nao_vistas"], 0)
        self.agora = AGORA.replace(hour=23)
        self.assertEqual(self.servico.resumo_inicio()["proxima"]["processo"][:7], "0700104")

    def test_sigilo_pela_pasta(self):
        self.amb.sigilosos.mkdir(parents=True)
        (self.amb.sigilosos / f"{ap.numero('0700102')}.pdf").write_bytes(apoio.pdf_bytes(1))
        d = AGORA.date()
        sig = {a["processo"][:7]: a["sigiloso"] for a in self.servico.listar(d, d)["audiencias"]}
        self.assertEqual(sig, {"0700101": False, "0700102": True, "0700103": False})
        self.assertTrue(self.servico.resumo_inicio()["proxima"]["sigiloso"])


class TestFontesEMonitoramento(Base):
    def test_fontes(self):
        f = self.servico.salvar_fonte("tjal", "esaj", "")
        self.assertEqual((f["id"], f["rotulo"], f["modo"]), ("esaj-tjal", "TJAL · e-SAJ",
                                                              "automatico"))
        for args, trecho in ((("TJAL", "pje", ""), "e-SAJ ou eProc"), (("", "esaj", ""), "tribunal"),
                             (("TJAL", "esaj", "", "javascript:alert(1)"), "https://")):
            with self.subTest(args=args):
                with self.assertRaises(ValueError) as erro:
                    self.servico.salvar_fonte(*args)
                self.assertIn(trecho, str(erro.exception))
        self.servico.remover_fonte("esaj-tjal")
        self.assertEqual(self.servico.fontes(), [])

    def test_monitoramento_com_padroes_e_gravacao(self):
        m = self.servico.monitoramento()
        self.assertEqual((m["ativo"], m["intervalo_horas"], m["dias_atras"], m["dias_a_frente"],
                          m["proxima"], m["fontes_monitoradas"]), (True, 6, 7, 60, None, 0))
        self.servico.salvar_fonte("TJAL", "esaj", "", "https://portal/pauta")
        self.assertEqual(self.servico.monitoramento()["proxima"], AGORA.isoformat(),
                         "nunca sincronizou: a próxima é já")
        self.servico.armazem.definir_meta("ultima_sincronizacao", AGORA - timedelta(hours=2))
        self.assertEqual(self.servico.monitoramento()["proxima"],
                         (AGORA + timedelta(hours=4)).isoformat())
        m = self.servico.configurar_monitoramento(False, 12)
        self.assertEqual((m["ativo"], m["intervalo_horas"], m["proxima"]), (False, 12, None))
        texto = self.amb.cfg.arquivo.read_text(encoding="utf-8")
        self.assertIn("monitorar = false", texto)
        self.assertIn("intervalo_horas = 12", texto)
        for valor in (0, 73, "x"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    self.servico.configurar_monitoramento(True, valor)

    def test_configuracao_ausente_ou_estragada(self):
        class CfgVelho:
            """Um config de antes da pauta: sem a seção, ou com lixo."""
            pasta_sigilosos = pasta_acervo = self.tmp

            def __init__(self, valores):
                self.valores = valores

            def texto(self, secao, chave):
                return self.valores.get(chave, "")

        for valores, esperado in (({}, (True, 6, 7, 60)),
                                  ({"monitorar": "talvez", "intervalo_horas": "seis",
                                    "dias_atras": "-3", "dias_a_frente": "9999"},
                                   (True, 6, 0, 3 * 366)),
                                  ({"monitorar": "não", "intervalo_horas": "200"},
                                   (False, 72, 7, 60))):
            with self.subTest(valores=valores):
                s = ServicoPauta(CfgVelho(valores), self.tmp / "outro.sqlite3")
                self.addCleanup(s.fechar)
                m = s.monitoramento()
                self.assertEqual((m["ativo"], m["intervalo_horas"], m["dias_atras"],
                                  m["dias_a_frente"]), esperado)


class TestSincronizar(Base):
    PERIODO = (date(2026, 10, 1), date(2026, 10, 31))

    def test_grava_lembra_a_rota_e_avisa_as_mudancas(self):
        self.servico.salvar_fonte("TJAL", "esaj", "")
        d = date(2026, 10, 6)
        url = "https://portal.invalid/pauta"
        ExtratorFalso.roteiro["esaj-tjal"] = [
            ([aud("0700101", d, "09:00"), aud("0700102", d, "10:00"), aud("0700103", d, "11:00")],
             True, url),
            ([aud("0700101", d, "14:00"), aud("0700102", d, "10:00", situacao="Cancelada"),
              aud("0700104", d, "16:00")], True, url),
        ]
        ctx = apoio.ContextoGravador()
        r = self.servico.sincronizar(ctx, None, *self.PERIODO)
        self.assertEqual((r["novas"], r["atualizadas"], r["removidas"], r["alteracoes"]),
                         (3, 0, 0, 0), "a primeira é a base: nada de 'alterações'")
        self.assertEqual(ctx.status_[-1], "3 audiências conferidas · 3 novas.")
        fonte = self.servico.fontes()[0]
        self.assertEqual((fonte["url"], fonte["menu"], fonte["ultima_sincronizacao"]),
                         (url, "Pauta de Audiências", AGORA.isoformat()))
        self.assertEqual(self.servico.ultima_sincronizacao(), AGORA)
        self.assertEqual([t for t, _ in self.eventos], ["pauta"])
        self.assertEqual(self.eventos[0][1]["tipo"], "atualizada")

        self.agora = AGORA + timedelta(hours=6)
        self.eventos.clear()
        r = self.servico.sincronizar(ctx, ["esaj-tjal"], *self.PERIODO)
        # 0700101 remarcada (alterada), 0700102 cancelada, 0700103 saiu, 0700104 nova
        self.assertEqual((r["novas"], r["atualizadas"], r["canceladas"], r["removidas"]),
                         (1, 2, 1, 1))
        self.assertEqual(ExtratorFalso.chamadas[-1][3], url, "a rota lembrada vai ao extrator")
        tipos = sorted(a["tipo"] for a in self.servico.alteracoes())
        self.assertEqual(tipos, ["alterada", "cancelada", "nova", "removida"])
        self.assertEqual([e[1]["tipo"] for e in self.eventos], ["atualizada", "alteracoes"])
        self.assertEqual(self.eventos[1][1]["dados"]["nao_vistas"], 4)
        self.assertEqual(self.servico.resumo_inicio()["alteracoes_nao_vistas"], 4)
        self.servico.marcar_vistas()
        self.assertEqual(self.servico.resumo_inicio()["alteracoes_nao_vistas"], 0)
        self.assertEqual(ctx.status_[-1], "3 audiências conferidas · 1 nova, 2 alteradas, "
                                          "1 saiu da pauta.")

    def test_periodo_nao_aplicado_so_remove_entre_as_datas_que_vieram(self):
        self.servico.salvar_fonte("TJAL", "esaj", "")
        ExtratorFalso.roteiro["esaj-tjal"] = [
            ([aud("0700101", date(2026, 10, 5), "09:00"), aud("0700102", date(2026, 10, 20), "09:00"),
              aud("0700103", date(2026, 10, 25), "09:00")], True, ""),
            # o portal mostrou só os dias 5 a 10 (sem campo de período)
            ([aud("0700101", date(2026, 10, 5), "09:00"), aud("0700105", date(2026, 10, 10), "09:00")],
             False, "")]
        ctx = apoio.ContextoGravador()
        self.servico.sincronizar(ctx, None, *self.PERIODO)
        r = self.servico.sincronizar(ctx, None, *self.PERIODO)
        self.assertEqual(r["removidas"], 0, "o dia 20 e o dia 25 não foram conferidos")
        self.assertEqual(len(self.servico.listar(*self.PERIODO)["audiencias"]), 4)

    def test_uma_fonte_falha_e_a_outra_segue(self):
        self.servico.salvar_fonte("TJAL", "esaj", "")
        self.servico.salvar_fonte("TJRS", "eproc", "")
        self.falhas_portal["TJAL"] = [mdl.LoginFalhou("o e-SAJ do TJAL recusou a senha")]
        ExtratorFalso.roteiro["eproc-tjrs"] = [
            ([aud("5000001", date(2026, 10, 7), "08:30", sistema="eproc", tribunal="TJRS")],
             True, "https://eproc.invalid/x")]
        ctx = apoio.ContextoGravador()
        r = self.servico.sincronizar(ctx, None, *self.PERIODO)
        self.assertEqual(r["novas"], 1)
        self.assertEqual(r["erros"], [{"fonte": "esaj-tjal", "rotulo": "TJAL · e-SAJ",
                                       "mensagem": "O e-SAJ do TJAL recusou a senha"}])
        self.assertEqual(ctx.avisos, [("Pauta: TJAL · e-SAJ", "O e-SAJ do TJAL recusou a senha")])
        fontes = {f["id"]: f for f in self.servico.fontes()}
        self.assertEqual(fontes["esaj-tjal"]["ultimo_erro"], "O e-SAJ do TJAL recusou a senha")
        self.assertEqual(fontes["eproc-tjrs"]["ultimo_erro"], "")
        self.assertIn("1 fonte com problema", ctx.status_[-1])
        self.assertTrue(all(n.fechado for n in apoio.NavegadorFalso.instancias),
                        "o navegador fecha mesmo quando o login falha")

    def test_todas_falham(self):
        self.servico.salvar_fonte("TJAL", "esaj", "")
        ExtratorFalso.roteiro["esaj-tjal"] = [PautaNaoEncontrada(
            "não encontrei a pauta de audiências no e-SAJ do TJAL")]
        with self.assertRaises(ErroPauta) as erro:
            self.servico.sincronizar(apoio.ContextoGravador(), None, *self.PERIODO)
        self.assertEqual(str(erro.exception), "Não consegui ler a pauta: TJAL · e-SAJ — Não "
                                              "encontrei a pauta de audiências no e-SAJ do TJAL.")
        self.assertIsNone(self.servico.ultima_sincronizacao())
        self.assertEqual(self.eventos, [])

    def test_sem_fontes_ou_fontes_inexistentes(self):
        with self.assertRaises(ErroPauta) as erro:
            self.servico.sincronizar(apoio.ContextoGravador(), None, *self.PERIODO)
        self.assertIn("Nenhuma fonte", str(erro.exception))
        self.servico.salvar_fonte("TJAL", "esaj", "")
        with self.assertRaises(ErroPauta) as erro:
            self.servico.sincronizar(apoio.ContextoGravador(), ["nao-existe"], *self.PERIODO)
        self.assertIn("não existem mais", str(erro.exception))

    def test_tribunal_que_nao_usa_o_sistema(self):
        self.servico.armazem.salvar_fonte("TJRS", "esaj", "TJRS · e-SAJ")
        with self.assertRaises(ErroPauta) as erro:
            self.servico.sincronizar(apoio.ContextoGravador(), None, *self.PERIODO)
        self.assertIn("O TJRS não usa o e-SAJ", str(erro.exception))

    def test_monitor_sem_senha_nao_abre_navegador(self):
        self.servico.salvar_fonte("TJAL", "esaj", "", "https://portal.invalid/pauta")
        self.cofre.dados.clear()
        ctx = ap.ContextoDeFundo()
        with self.assertRaises(ErroPauta) as erro:
            self.servico.sincronizar(ctx, None, *self.PERIODO)
        self.assertIn("Entre no portal para continuar o monitoramento", str(erro.exception))
        self.assertTrue(ctx.pediu_login)
        self.assertEqual(apoio.NavegadorFalso.instancias, [], "nenhuma janela aparece do nada")

    def test_usuario_sem_senha_entra_a_mao(self):
        self.servico.salvar_fonte("TJAL", "esaj", "")
        self.cofre.dados.clear()
        ExtratorFalso.roteiro["esaj-tjal"] = [([], True, "")]
        self.servico.sincronizar(apoio.ContextoGravador(), None, *self.PERIODO)
        portal = PortalFalso.instancias[0]
        self.assertIsNone(portal.credenciais)
        self.assertEqual(portal.opcoes.modo_login("esaj"), "manual",
                         "como no download: o navegador abre na tela de entrada")
        self.assertFalse(portal.opcoes.atualizar_ia)

    def test_sessao_caiu_entra_de_novo(self):
        self.servico.salvar_fonte("TJAL", "esaj", "")
        ExtratorFalso.roteiro["esaj-tjal"] = [mdl.SessaoPerdida("a sessão caiu"),
                                              ([aud("0700101", date(2026, 10, 6), "09:00")], True,
                                               "")]
        ctx = apoio.ContextoGravador()
        r = self.servico.sincronizar(ctx, None, *self.PERIODO)
        self.assertEqual(r["novas"], 1)
        self.assertEqual(PortalFalso.instancias[0].entradas, 2)
        self.assertIn("A sessão do e-SAJ do TJAL caiu; entrando de novo…", ctx.status_)

    def test_eproc_com_endereco_por_secao(self):
        """TRF4: o login espera um processo para saber a seção; a rota lembrada diz qual é."""

        class PortalPorSecao(PortalFalso):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.base = ""
                self._candidatos_atuais = []

            def entrar(self):
                super().entrar()
                if self._candidatos_atuais:
                    self.base = self._candidatos_atuais[0]

        self.servico.fabrica_portal = PortalPorSecao
        self.cofre.dados["eproc:TRF4"] = ("u", "s")
        self.servico.salvar_fonte("TRF4", "eproc", "")
        with self.assertRaises(ErroPauta) as erro:
            self.servico.sincronizar(apoio.ContextoGravador(), None, *self.PERIODO)
        self.assertIn("seção judiciária", str(erro.exception))
        self.servico.salvar_fonte("TRF4", "eproc", "", "https://eproc.jfrs.jus.br/eprocV2/"
                                                       "controlador.php?acao=audiencia_listar&hash=x")
        ExtratorFalso.roteiro["eproc-trf4"] = [([], True, "")]
        self.servico.sincronizar(apoio.ContextoGravador(), None, *self.PERIODO)
        portal = PortalFalso.instancias[-1]
        self.assertEqual(portal.base, "https://eproc.jfrs.jus.br/eprocV2/")
        self.assertEqual(portal.entradas, 2)

    def test_parar(self):
        self.servico.salvar_fonte("TJAL", "esaj", "")
        ctx = apoio.ContextoGravador()
        ctx.cancelar()
        with self.assertRaises(mdl.Cancelado):
            self.servico.sincronizar(ctx, None, *self.PERIODO)
        self.servico.salvar_fonte("TJRS", "eproc", "")
        ctx = apoio.ContextoGravador()
        ExtratorFalso.roteiro["eproc-tjrs"] = [mdl.Cancelado()]
        ExtratorFalso.roteiro["esaj-tjal"] = [([], True, "")]
        with self.assertRaises(mdl.Cancelado):
            self.servico.sincronizar(ctx, ["eproc-tjrs", "esaj-tjal"], *self.PERIODO)


if __name__ == "__main__":
    unittest.main()
