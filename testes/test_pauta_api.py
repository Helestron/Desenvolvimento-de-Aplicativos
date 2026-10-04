"""Pauta pela API com o ServicoPauta DE VERDADE (o banco, a planilha, a senha da sessão).

O resto da API da pauta é testado com um serviço simulado em
test_servidor_pauta.py; aqui ficam os casos em que só o serviço real mostra o
defeito: a escolha "sem as partes dos sigilosos" feita na janela de
exportação, a senha digitada com "Lembrar neste computador" desligado e o
sigilo que a pauta revela, que tira o processo do acervo na hora.
"""

from __future__ import annotations

import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from helestron.pauta import modelos, navegacao
from helestron.pauta.navegacao import Leitura
from helestron.pauta.tabelas import Reconhecimento

from testes import apoio_download as apoio
from testes import apoio_pauta as ap
from testes.test_servidor_base import ServidorDeTeste

DIA = date(2026, 10, 6)
PARTES = "Maria A. S. x João R. S."


class TestExportarPelaApi(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        self.servico = self.app.pauta()
        self.servico.armazem.gravar([modelos.nova(
            sistema="esaj", tribunal="TJAL", data_=DIA, processo=ap.numero("0700105"),
            hora="09:30", tipo_original="Conciliação", partes=PARTES, sigiloso=True)],
            "esaj-tjal", None, registrar_novas=False)

    def partes_na_planilha(self, corpo: dict) -> str:
        from openpyxl import load_workbook

        dados = self.cliente.dados("POST", "/api/pauta/exportar",
                                   {"de": DIA.isoformat(), "ate": DIA.isoformat(), **corpo})
        return load_workbook(Path(dados["arquivo"]))["Pauta"].cell(5, 6).value

    def test_a_escolha_da_janela_vale_mesmo_com_o_ajuste_ligado(self):
        self.cfg.definir("pauta", "incluir_partes_sigilosos", True)
        self.assertEqual(self.partes_na_planilha({"incluir_partes_sigilosos": False}),
                         modelos.MASCARA_SIGILO, "desligado na janela: mascarado")
        self.assertEqual(self.partes_na_planilha({"incluir_partes_sigilosos": True}), PARTES)
        self.assertEqual(self.partes_na_planilha({}), PARTES, "sem o campo, vale o Ajuste")
        self.cfg.definir("pauta", "incluir_partes_sigilosos", False)
        self.assertEqual(self.partes_na_planilha({}), modelos.MASCARA_SIGILO)
        self.assertEqual(self.partes_na_planilha({"incluir_partes_sigilosos": "false"}),
                         modelos.MASCARA_SIGILO)


class _Portal:
    instancias: list = []

    def __init__(self, nav, tribunal, opcoes, ctx, credenciais):
        self.opcoes, self.credenciais = opcoes, credenciais
        self.sistema, self.base = tribunal.sistema, "https://portal.invalid"
        self.nome = f"{tribunal.nome_sistema} do {tribunal.sigla}"
        _Portal.instancias.append(self)

    def entrar(self):
        pass


class _Extrator:
    def __init__(self, *a, **k):
        pass

    def extrair(self, de, ate):
        return Leitura(reconhecimento=Reconhecimento(tabelas=1), paginas=1,
                       periodo_aplicado=True, url="https://portal.invalid/pauta")


class TestSenhaDaSessao(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        _Portal.instancias = []
        self.servico = self.app.pauta()
        self.servico.fabrica_navegador = apoio.NavegadorFalso
        self.servico.fabrica_portal = _Portal
        p = mock.patch.object(navegacao, "ExtratorAutomatico", _Extrator)
        p.start()
        self.addCleanup(p.stop)

    def test_senha_so_por_agora_vale_para_sincronizar(self):
        acesso = self.cliente.dados("POST", "/api/acessos", {
            "portal": "esaj:TJAL", "usuario": "12345678900", "senha": "segredo",
            "lembrar": False})
        self.assertTrue(acesso.get("so_agora"))
        self.cliente.dados("POST", "/api/pauta/fontes", {"tribunal": "TJAL", "sistema": "esaj"})
        tarefa = self.cliente.dados("POST", "/api/pauta/sincronizar", {})["tarefa"]
        fim = self.esperar_tarefa(tarefa)
        self.assertNotEqual(fim["estado"], "falhou", fim)
        portal = _Portal.instancias[-1]
        self.assertEqual(portal.credenciais, ("12345678900", "segredo"))
        self.assertEqual(portal.opcoes.modo_login("esaj"), "senha",
                         "a tela de entrada do portal não abre: a senha foi informada")


def _ate(condicao, espera: float = 15.0) -> bool:
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.05)
    return bool(condicao())


class TestSigiloReveladoPelaPauta(ServidorDeTeste):
    """A pauta (importação, sincronização, monitor) revela que um processo com
    autos no acervo corre em segredo de justiça: ele sai do acervo, do índice e
    da nuvem na hora - não só no próximo compartilhamento -, e o usuário é avisado."""

    def setUp(self):
        super().setUp()
        from helestron import servicos

        self.n1, self.n2, self.n3 = (ap.numero("0700141"), ap.numero("0700142"),
                                     ap.numero("0700143"))
        self.acervo, self.sig = Path(self.cfg.pasta_acervo), Path(self.cfg.pasta_sigilosos)
        self.lote = self.acervo / "Processos" / "Lote 1"
        self.lote.mkdir(parents=True)
        for n in (self.n1, self.n2):
            (self.lote / f"{n}.pdf").write_bytes(apoio.pdf_bytes(1, "autos"))
        servicos.atualizar_indice(self.cfg)
        self.assertIn(self.n1, self.indice())
        self.avisos: list[dict] = []
        publicar = self.app.hub.publicar

        def espiar(tipo, dados=None):
            if tipo == "aviso":
                self.avisos.append(dict(dados or {}))
            return publicar(tipo, dados)

        p = mock.patch.object(self.app.hub, "publicar", espiar)
        p.start()
        self.addCleanup(p.stop)

    def indice(self) -> str:
        try:
            return (self.acervo / "INDICE.md").read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def relatorio(self, *linhas: tuple[str, str]) -> Path:
        arquivo = self.amb.raiz / "rel.csv"
        arquivo.write_text("Data;Hora;Processo;Tipo;Observações;Partes\n" + "".join(
            f"20/10/2026;09:00;{n};Instrução;{obs};{partes}\n" for n, obs, partes in linhas),
            encoding="utf-8")
        return arquivo

    def sigiloso_saiu(self, n) -> bool:
        return (self.sig / "Lote 1" / f"{n}.pdf").exists() and \
            not (self.lote / f"{n}.pdf").exists() and n not in self.indice()

    def test_importar_tira_do_acervo_e_avisa(self):
        arquivo = self.relatorio((self.n1, "", "(Segredo de Justiça)"),
                                 (self.n2, "Segredo de justiça: não", "Fulano x Banco"))
        r = self.cliente.dados("POST", "/api/pauta/importar", {"caminho": str(arquivo)})
        self.assertEqual(r["sigilosos_novos"], [self.n1])
        self.assertTrue(_ate(lambda: self.sigiloso_saiu(self.n1)),
                        "os autos do processo sigiloso continuaram no acervo (ou no índice)")
        self.assertTrue((self.lote / f"{self.n2}.pdf").exists(), "o público fica")
        self.assertIn(self.n2, self.indice())
        self.assertEqual(len(self.avisos), 1, self.avisos)
        aviso = self.avisos[0]
        self.assertEqual(aviso["titulo"], "Processo em segredo de justiça")
        self.assertEqual(aviso["mensagem"],
                         f"A pauta indica que o processo {self.n1} corre em segredo de justiça. "
                         "O Helestron está levando os autos e as transcrições dele para a pasta "
                         "dos sigilosos, e ele sai do índice e do texto lidos pela IA.")

    def test_nada_no_acervo_nada_a_avisar(self):
        arquivo = self.relatorio((self.n3, "", "(Segredo de Justiça)"))
        r = self.cliente.dados("POST", "/api/pauta/importar", {"caminho": str(arquivo)})
        self.assertEqual(r["sigilosos_novos"], [self.n3])
        self.assertEqual(self.avisos, [])
        self.assertTrue((self.lote / f"{self.n1}.pdf").exists())

    def test_o_que_o_monitor_revelou_antes_vale_quando_a_janela_abre(self):
        """O monitor usa o mesmo serviço, direto: o revelado antes de qualquer
        pedido à API da pauta é tratado no primeiro pedido (a janela abrindo o Início)."""
        servico = self.app.pauta()
        servico.importar(self.relatorio((self.n1, "", "(Segredo de Justiça)")))
        self.assertTrue((self.lote / f"{self.n1}.pdf").exists())
        self.cliente.dados("GET", "/api/pauta")
        self.assertTrue(_ate(lambda: self.sigiloso_saiu(self.n1)))
        self.assertEqual(len(self.avisos), 1)
        # e, ligado, a sincronização seguinte do monitor já vale na hora
        (self.lote / f"{self.n3}.pdf").write_bytes(apoio.pdf_bytes(1, "autos"))
        servico.importar(self.relatorio((self.n3, "Processo em segredo de justiça", "A x B")))
        self.assertTrue(_ate(lambda: self.sigiloso_saiu(self.n3)))

    def test_espelho_automatico_tira_a_copia_da_nuvem(self):
        from helestron.compartilhar import nuvem

        destino = self.amb.raiz / "OneDrive"
        destino.mkdir()
        nuvem.espelhar(self.acervo, destino)
        copia = destino / nuvem.SUBPASTA / "Processos" / "Lote 1" / f"{self.n1}.pdf"
        self.assertTrue(copia.exists())
        self.cfg.definir("compartilhar", "pasta_nuvem", str(destino))
        self.cfg.definir("compartilhar", "espelhar_automaticamente", True)
        arquivo = self.relatorio((self.n1, "", "(Segredo de Justiça)"))
        self.cliente.dados("POST", "/api/pauta/importar", {"caminho": str(arquivo)})
        self.assertTrue(_ate(lambda: not copia.exists()),
                        "a cópia do processo sigiloso continuou na nuvem")
        self.assertTrue(_ate(lambda: self.sigiloso_saiu(self.n1)))
        self.assertTrue(self.avisos[0]["mensagem"].endswith(
            "sai do índice e do texto lidos pela IA e do espelho na nuvem."), self.avisos)

    def test_separacao_desligada_e_nuvem_manual(self):
        self.cfg.definir("download", "separar_sigilosos", False)
        destino = self.amb.raiz / "OneDrive"
        destino.mkdir()
        self.cfg.definir("compartilhar", "pasta_nuvem", str(destino))
        arquivo = self.relatorio((self.n1, "", "(Segredo de Justiça)"))
        self.cliente.dados("POST", "/api/pauta/importar", {"caminho": str(arquivo)})
        self.assertTrue(_ate(lambda: self.n1 not in self.indice()))
        self.assertTrue((self.lote / f"{self.n1}.pdf").exists(), "com a separação desligada, fica")
        self.assertEqual(self.avisos[0]["mensagem"],
                         f"A pauta indica que o processo {self.n1} corre em segredo de justiça. "
                         "Com a separação dos sigilosos desligada, os arquivos dele continuam no "
                         "acervo, mas ele sai do índice e do texto lidos pela IA. A cópia dele "
                         "na nuvem sai no próximo espelho (Compartilhar › Espelhar agora).")


if __name__ == "__main__":
    unittest.main()
