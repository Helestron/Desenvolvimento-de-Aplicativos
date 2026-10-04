"""Pauta pela API, com um ServicoPauta simulado (a interface da seção 8.10)."""

from __future__ import annotations

import sys
import threading
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from helestron.download.modelos import OK, ResultadoProcesso, ResumoLote

from testes.test_servidor_base import ServidorDeTeste

HOJE = date.today()


class ServicoPautaFalso:
    """Guarda as chamadas e devolve dados no formato da especificação."""

    instancias: list = []

    def __init__(self, cfg, arquivo_banco=None, eventos=None):
        self.cfg = cfg
        self.arquivo_banco = arquivo_banco
        self.eventos = eventos
        self.chamadas: list = []
        self._fontes = [{"id": "f1", "tribunal": "TJAL", "sistema": "esaj", "rotulo": "TJAL · e-SAJ",
                         "url": "https://www2.tjal.jus.br/sajcas/pauta"}]
        self._ativo, self._intervalo = False, 6
        self._ultima: datetime | None = None
        self.pedir_codigo = False
        self.segurar: threading.Event | None = None
        ServicoPautaFalso.instancias.append(self)

    def _audiencias(self):
        return [{"id": "a1", "sistema": "esaj", "tribunal": "TJAL",
                 "processo": "0700123-83.2024.8.02.0001", "data": HOJE.isoformat(), "hora": "14:30",
                 "tipo": "Conciliação", "situacao": "Designada", "partes": "A x B", "sigiloso": False},
                {"id": "a2", "sistema": "eproc", "tribunal": "TJAL",
                 "processo": "0700124-68.2024.8.02.0001", "data": HOJE.isoformat(), "hora": "15:00",
                 "tipo": "Una", "situacao": "Designada", "partes": "C x D", "sigiloso": True},
                {"id": "a3", "sistema": "arquivo", "tribunal": "", "processo": "",
                 "data": HOJE.isoformat(), "hora": "", "tipo": "Outra", "situacao": "Designada"}]

    def listar(self, de, ate, sistema="", situacao="", busca=""):
        self.chamadas.append(("listar", de, ate, sistema, situacao, busca))
        lista = [a for a in self._audiencias() if not sistema or a["sistema"] == sistema]
        return {"audiencias": lista, "resumo": {"total": len(lista), "hoje": len(lista),
                                                 "semana": len(lista), "por_situacao": {},
                                                 "por_tipo": {}}}

    def fontes(self):
        return list(self._fontes)

    def salvar_fonte(self, tribunal, sistema, rotulo, url=""):
        fonte = {"id": f"f{len(self._fontes) + 1}", "tribunal": tribunal, "sistema": sistema,
                 "rotulo": rotulo, "url": url}
        self._fontes.append(fonte)
        return fonte

    def remover_fonte(self, id_fonte):
        self.chamadas.append(("remover_fonte", id_fonte))
        self._fontes = [f for f in self._fontes if f["id"] != id_fonte]

    def sincronizar(self, ctx, fontes, de, ate):
        self.chamadas.append(("sincronizar", fontes, de, ate))
        ctx.status("Lendo a pauta do e-SAJ…")
        if self.pedir_codigo:
            codigo = ctx.pedir_codigo("Código do e-SAJ", "Veja o e-mail.", 60, True)
            self.chamadas.append(("codigo", codigo))
            if codigo is None:
                return {"novas": 0, "erro": "login"}
        if self.segurar is not None:
            while not self.segurar.wait(0.05):
                if ctx.cancelado():
                    return {}
        ctx.progresso(1, 1, "TJAL")
        self._ultima = datetime.now()
        if self.eventos:
            self.eventos("pauta", {"tipo": "atualizada", "dados": {"novas": 2}})
        return {"novas": 2, "atualizadas": 0, "removidas": 0}

    def capturar(self, ctx, tribunal, sistema):
        self.chamadas.append(("capturar", tribunal, sistema))
        return {"capturadas": 3}

    def importar(self, caminho):
        self.chamadas.append(("importar", Path(caminho).suffix, Path(caminho).exists(),
                              Path(caminho).read_bytes()))
        return {"novas": 1, "atualizadas": 0, "ignoradas": 0, "avisos": []}

    def exportar(self, de, ate, destino_pasta, **filtros):
        self.chamadas.append(("exportar", de, ate, Path(destino_pasta), filtros))
        arquivo = Path(destino_pasta) / f"Pauta de audiências {de} a {ate}.xlsx"
        arquivo.write_bytes(b"PK")
        return arquivo

    def alteracoes(self, desde=None):
        self.chamadas.append(("alteracoes", desde))
        return [{"quando": "2026-10-03T10:00:00", "tipo": "nova", "audiencia": {}, "campos": []}]

    def marcar_vistas(self):
        self.chamadas.append(("vistas",))

    def monitoramento(self):
        return {"ativo": self._ativo, "intervalo_horas": self._intervalo}

    def configurar_monitoramento(self, ativo, intervalo_horas):
        self._ativo, self._intervalo = bool(ativo), int(intervalo_horas)
        return self.monitoramento()

    def ultima_sincronizacao(self):
        return self._ultima

    def resumo_inicio(self):
        return {"hoje": 2, "semana": 2, "proxima": self._audiencias()[0],
                "ultima_sincronizacao": self._ultima, "alteracoes_nao_vistas": 1}


def modulo_falso():
    pacote = types.ModuleType("helestron.pauta")
    pacote.__path__ = []
    servico = types.ModuleType("helestron.pauta.servico")
    servico.ServicoPauta = ServicoPautaFalso
    pacote.servico = servico
    return {"helestron.pauta": pacote, "helestron.pauta.servico": servico}


class TestPauta(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        ServicoPautaFalso.instancias = []
        p = mock.patch.dict(sys.modules, modulo_falso())
        p.start()
        self.addCleanup(p.stop)

    @property
    def servico(self) -> ServicoPautaFalso:
        return ServicoPautaFalso.instancias[0]

    def test_listar(self):
        dados = self.cliente.dados("GET", f"/api/pauta?de={HOJE}&ate={HOJE}&sistema=esaj&busca=A")
        self.assertEqual([a["id"] for a in dados["audiencias"]], ["a1"])
        self.assertEqual(dados["resumo"]["total"], 1)
        self.assertIsNone(dados["ultima_sincronizacao"])
        self.assertEqual(dados["monitoramento"]["ativo"], False)
        self.assertIn("proxima", dados["monitoramento"])
        self.assertEqual(self.servico.chamadas[0], ("listar", HOJE, HOJE, "esaj", "", "A"))
        self.assertEqual(self.servico.arquivo_banco, self.amb.local / "pauta.sqlite3")
        status, env = self.cliente.get("/api/pauta?de=03/10/2026")
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "data_invalida")
        status, _ = self.cliente.get(f"/api/pauta?de={HOJE}&ate={HOJE - timedelta(days=1)}")
        self.assertEqual(status, 400)

    def test_resumo_no_estado(self):
        dados = self.cliente.dados("GET", "/api/estado")
        self.assertEqual(dados["resumo"]["pauta"]["hoje"], 2)
        self.assertEqual(dados["resumo"]["pauta"]["alteracoes_nao_vistas"], 1)

    def test_fontes(self):
        self.assertEqual(len(self.cliente.dados("GET", "/api/pauta/fontes")), 1)
        nova = self.cliente.dados("POST", "/api/pauta/fontes",
                                  {"tribunal": "tjal", "sistema": "eproc", "rotulo": ""})
        self.assertEqual((nova["tribunal"], nova["sistema"], nova["rotulo"]),
                         ("TJAL", "eproc", "TJAL · eProc"))
        for corpo in ({"tribunal": "TJAL", "sistema": "pje"},
                      {"tribunal": "TJPE", "sistema": "esaj"},
                      {"tribunal": "TJAL", "sistema": "esaj", "url": "javascript:alert(1)"}):
            with self.subTest(corpo=corpo):
                status, _ = self.cliente.post("/api/pauta/fontes", corpo)
                self.assertEqual(status, 400)
        self.cliente.dados("DELETE", f"/api/pauta/fontes/{nova['id']}")
        self.assertIn(("remover_fonte", nova["id"]), self.servico.chamadas)

    def test_sincronizar_com_codigo_e_evento(self):
        self.cliente.dados("GET", "/api/pauta/fontes")
        self.servico.pedir_codigo = True
        leitor = self.eventos()
        id_tarefa = self.cliente.dados("POST", "/api/pauta/sincronizar", {"fontes": ["f1"]})["tarefa"]
        pergunta = leitor.esperar("pergunta")
        self.assertEqual(pergunta["tarefa"], id_tarefa)
        self.cliente.dados("POST", f"/api/perguntas/{pergunta['id']}/responder", {"valor": "777"})
        tarefa = self.esperar_tarefa(id_tarefa)
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(tarefa["tipo"], "pauta_sincronizar")
        self.assertEqual(tarefa["resultado"]["novas"], 2)
        self.assertIn(("codigo", "777"), self.servico.chamadas)
        evento = leitor.esperar("pauta")
        self.assertEqual(evento["tipo"], "atualizada")
        _, fontes, de, ate = next(c for c in self.servico.chamadas if c[0] == "sincronizar")
        self.assertEqual(fontes, ["f1"])
        self.assertEqual((de, ate), (HOJE - timedelta(days=7), HOJE + timedelta(days=60)))

    def test_sincronizar_disputa_o_navegador(self):
        self.cliente.dados("GET", "/api/pauta/fontes")
        self.servico.segurar = threading.Event()
        id_tarefa = self.cliente.dados("POST", "/api/pauta/sincronizar", {})["tarefa"]
        with mock.patch("helestron.servicos.baixar_lote"):
            status, env = self.cliente.post("/api/download/iniciar",
                                            {"processos": ["0700123-83.2024.8.02.0001"]})
        self.assertEqual(status, 409)
        self.assertIn("navegador dos portais", env["erro"]["mensagem"])
        self.servico.segurar.set()
        self.esperar_tarefa(id_tarefa)

    def test_capturar(self):
        tarefa = self.esperar_tarefa(self.cliente.dados(
            "POST", "/api/pauta/capturar", {"tribunal": "TJAL", "sistema": "eproc"})["tarefa"])
        self.assertEqual(tarefa["tipo"], "pauta_capturar")
        self.assertEqual(tarefa["resultado"], {"capturadas": 3})
        self.assertIn(("capturar", "TJAL", "eproc"), self.servico.chamadas)

    def test_importar_envio_e_caminho(self):
        status, env = self.cliente.enviar("/api/pauta/importar", "pauta do SAJ.xls", b"<html>")
        self.assertEqual(status, 200, env)
        self.assertEqual(env["dados"]["novas"], 1)
        chamada = next(c for c in self.servico.chamadas if c[0] == "importar")
        self.assertEqual(chamada[1:], (".xls", True, b"<html>"))
        envios = self.app.pasta_envios()
        self.assertEqual(list(envios.glob("*")), [])
        arquivo = self.amb.raiz / "pauta.csv"
        arquivo.write_text("x", encoding="utf-8")
        self.cliente.dados("POST", "/api/pauta/importar", {"caminho": str(arquivo)})
        status, _ = self.cliente.post("/api/pauta/importar", {"caminho": "relativo.csv"})
        self.assertEqual(status, 400)

    def test_exportar_fora_do_acervo(self):
        dados = self.cliente.dados("POST", "/api/pauta/exportar", {
            "de": "2026-10-01", "ate": "2026-10-31", "sistema": "todos", "busca": "x",
            "incluir_partes_sigilosos": True})
        pasta = self.amb.dados / "Pauta"
        self.assertEqual(dados["pasta"], str(pasta))
        self.assertTrue(Path(dados["arquivo"]).exists())
        _, de, ate, destino, filtros = next(c for c in self.servico.chamadas if c[0] == "exportar")
        self.assertEqual((de, ate, destino), (date(2026, 10, 1), date(2026, 10, 31), pasta))
        self.assertEqual(filtros, {"busca": "x", "incluir_partes_sigilosos": True})
        # a pasta da pauta posta dentro do acervo (no ini, à mão): recusa
        self.cfg.definir("pauta", "pasta", str(self.amb.dados / "Acervo" / "Pauta"))
        status, env = self.cliente.post("/api/pauta/exportar", {"de": "2026-10-01",
                                                               "ate": "2026-10-02"})
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")

    def test_alteracoes_e_vistas(self):
        lista = self.cliente.dados("GET", "/api/pauta/alteracoes?desde=2026-10-01T00:00:00")
        self.assertEqual(lista[0]["tipo"], "nova")
        self.assertIn(("alteracoes", datetime(2026, 10, 1)), self.servico.chamadas)
        self.cliente.dados("POST", "/api/pauta/alteracoes/vistas")
        self.assertIn(("vistas",), self.servico.chamadas)

    def test_monitoramento(self):
        monitor = mock.Mock(proxima=datetime(2026, 10, 3, 18, 0))
        self.app.monitor = monitor
        dados = self.cliente.dados("POST", "/api/pauta/monitoramento",
                                   {"ativo": True, "intervalo_horas": 4})
        self.assertEqual((dados["ativo"], dados["intervalo_horas"]), (True, 4))
        self.assertEqual(dados["proxima"], "2026-10-03T18:00:00")
        monitor.acordar.assert_called_once()
        status, _ = self.cliente.post("/api/pauta/monitoramento", {"ativo": True,
                                                                  "intervalo_horas": 0})
        self.assertEqual(status, 400)

    def test_baixar_autos_da_pauta(self):
        recebidos = []

        def motor(numeros, destino, opcoes, ctx, senhas, cofre, cfg):
            recebidos.append(([n.formatado for n in numeros], Path(destino).name))
            itens = [ResultadoProcesso(1, numeros[0].formatado, "TJAL", "esaj", situacao=OK)]
            return ResumoLote(itens, Path(destino), Path(destino) / "r.csv")

        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            dados = self.cliente.dados("POST", "/api/pauta/baixar-autos",
                                       {"ids": ["a2", "a3"], "de": HOJE.isoformat(),
                                        "ate": HOJE.isoformat()})
            self.assertEqual(dados["processos"], 1)
            tarefa = self.esperar_tarefa(dados["tarefa"])
        self.assertEqual(tarefa["tipo"], "download")
        self.assertEqual(recebidos, [(["0700124-68.2024.8.02.0001"], f"Pauta {HOJE.isoformat()}")])
        status, env = self.cliente.post("/api/pauta/baixar-autos", {"ids": ["a3"]})
        self.assertEqual(status, 409)


class TestPautaIndisponivel(ServidorDeTeste):
    def test_503_sem_o_pacote(self):
        with mock.patch.dict(sys.modules, {"helestron.pauta": None, "helestron.pauta.servico": None}):
            for metodo, caminho in (("GET", "/api/pauta"), ("GET", "/api/pauta/fontes"),
                                    ("POST", "/api/pauta/sincronizar")):
                with self.subTest(caminho=caminho):
                    status, env = self.cliente.pedir(metodo, caminho, {} if metodo == "POST"
                                                     else None)
                    self.assertEqual(status, 503)
                    self.assertEqual(env["erro"]["codigo"], "pauta_indisponivel")
            # o resto do programa continua
            dados = self.cliente.dados("GET", "/api/estado")
            self.assertIsNone(dados["resumo"]["pauta"])


if __name__ == "__main__":
    unittest.main()
