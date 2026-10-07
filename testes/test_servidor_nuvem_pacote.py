"""Servidor local: o lote recusado com as pastas em conflito, a linha do
processo com a causa e o "refazer", o espelho na nuvem que diz o que NÃO
copiou, o pacote para o ChatGPT que mostra os avisos (e o .zip grande demais)
e os pacotes já gerados que perdem o processo que virou sigiloso - pela
transcrição sigilosa e pela pauta."""

from __future__ import annotations

import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from helestron.download.modelos import (ERRO, NAO_ENCONTRADO, OK, ResultadoProcesso,
                                        ResumoLote)

from testes.test_servidor_base import ServidorDeTeste

A = "0700123-83.2024.8.02.0001"


def _esperar(condicao, espera: float = 15.0) -> bool:
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.05)
    return condicao()


def _segundo_plano_terminou() -> bool:
    """As threads do índice e dos pacotes (api_compartilhar) acabaram? O
    teste espera por elas, e não lê o .zip enquanto elas o trocam: no
    Windows, o .zip aberto pelo teste impediria a troca."""
    return not any(t.is_alive() and t.name in ("indice-acervo", "pacotes-sigilo")
                   for t in threading.enumerate())


# ======================================================= lote x pastas
class TestLoteComPastasEmConflito(ServidorDeTeste):
    """Com a pasta dos sigilosos (ou a da pauta) dentro do acervo - config.ini
    editado à mão ou de versão anterior -, o lote não começa: o sigiloso
    baixado iria para a pasta dos sigilosos DENTRO do acervo, lido pela IA."""

    def recusa(self, corpo=None, rota="/api/download/iniciar") -> str:
        with mock.patch("helestron.servicos.baixar_lote") as baixar:
            status, env = self.cliente.post(rota, corpo or {"processos": [A]})
        self.assertEqual(status, 409, env)
        self.assertEqual(env["erro"]["codigo"], "pastas_em_conflito")
        baixar.assert_not_called()
        self.assertFalse([t for t in self.app.tarefas.listar() if t.tipo == "download"])
        return env["erro"]["mensagem"]

    def test_sigilosos_dentro_do_acervo(self):
        self.cfg.definir("geral", "pasta_sigilosos",
                         str(self.amb.dados / "Acervo" / "Sigilosos"))
        frase = self.recusa()
        self.assertIn("sigilosos", frase)
        self.assertTrue(frase.endswith("Corrija em Ajustes › Pastas antes de baixar os "
                                       "processos."), frase)

    def test_pauta_dentro_do_acervo(self):
        self.cfg.definir("pauta", "pasta", str(self.amb.dados / "Acervo" / "Pauta"))
        self.assertIn("pauta", self.recusa())

    def test_baixar_os_autos_da_pauta_tambem_espera(self):
        from helestron.nucleo import cnj, sigilo
        from testes.test_nucleo import pauta_com_sigiloso

        self.addCleanup(sigilo.esquecer_pauta)
        pauta_com_sigiloso(self.amb.local / "pauta.sqlite3", cnj.ler(A), sigiloso=False)
        self.cfg.definir("geral", "pasta_sigilosos",
                         str(self.amb.dados / "Acervo" / "Sigilosos"))
        self.recusa({"de": "2026-10-08", "ate": "2026-10-08"}, "/api/pauta/baixar-autos")

    def test_com_as_pastas_separadas_o_lote_comeca(self):
        def motor(numeros, destino, opcoes, ctx, senhas, cofre, cfg):
            return ResumoLote([], Path(destino), Path(destino) / "r.csv")

        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/download/iniciar", {"processos": [A]})["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)


# ===================================================== causa e refazer
class TestCausaERefazerNaLinha(unittest.TestCase):
    """A linha do processo na API traz a causa e o "refazer" do motor - os
    mesmos do relatorio.csv e do JSON da linha de comando."""

    def linha(self, **campos) -> dict:
        from helestron.servidor import api_processos

        r = ResultadoProcesso(1, A, "TJAL", "esaj", **campos)
        return api_processos.item_json(SimpleNamespace(id="t1"), r, Path("Lote"))

    def test_campos(self):
        self.assertEqual({k: v for k, v in self.linha(situacao=ERRO, causa="portal").items()
                          if k in ("causa", "refazer")}, {"causa": "portal", "refazer": True})
        self.assertEqual(self.linha(situacao=OK)["causa"], "")
        self.assertIs(self.linha(situacao=OK)["refazer"], False)
        # o "não encontrado" só pede nova rodada quando um sistema nem pôde ser consultado
        self.assertIs(self.linha(situacao=NAO_ENCONTRADO)["refazer"], False)
        self.assertIs(self.linha(situacao=NAO_ENCONTRADO, causa="login")["refazer"], True)
        self.assertIs(self.linha()["refazer"], True)            # pendente


class TestCausaPelaApi(ServidorDeTeste):
    def test_itens_da_tarefa(self):
        def motor(numeros, destino, opcoes, ctx, senhas, cofre, cfg):
            r = ResultadoProcesso(1, A, "TJAL", "esaj", situacao=ERRO, causa="pdf_aberto",
                                  detalhe="o PDF está aberto em outro programa")
            ctx.item(r)
            return ResumoLote([r], Path(destino), Path(destino) / "r.csv")

        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/download/iniciar", {"processos": [A]})["tarefa"])
        item = tarefa["itens"][0]
        self.assertEqual((item["causa"], item["refazer"]), ("pdf_aberto", True))
        self.assertEqual(tarefa["resultado"]["a_refazer"], [A])


# ========================================================= espelho
class TestEspelhoDizOQueNaoCopiou(ServidorDeTeste):
    """Antes, a tarefa do espelho terminava em "N copiados" como se a cópia
    estivesse completa: o arquivo que não foi para a nuvem (aberto, caminho
    longo demais) só aparecia no registro."""

    def setUp(self):
        super().setUp()
        from testes.apoio_download import pdf_bytes

        self.acervo = self.amb.dados / "Acervo"
        self.pdf = self.acervo / "Processos" / "Lote 1" / f"{A}.pdf"
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(pdf_bytes(2))
        self.nuvem = self.amb.raiz / "Nuvem"
        self.nuvem.mkdir()

    def espelho(self, motivo: str):
        from helestron.compartilhar import nuvem

        return nuvem.Espelho(2, 5, [(self.pdf, motivo)])

    def conferir(self, tarefa: dict, motivo: str, dica: str) -> None:
        from helestron.compartilhar import nuvem

        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(tarefa["status"],
                         f"2 copiados, 5 sem mudança, 1 NÃO copiado ({self.pdf.name}: {motivo}).")
        r = tarefa["resultado"]
        self.assertEqual((r["copiados"], r["iguais"]), (2, 5))
        self.assertEqual(r["nao_copiados"], [{"arquivo": str(self.pdf), "motivo": motivo}])
        self.assertEqual(r["pasta"], str(self.nuvem / nuvem.SUBPASTA))
        self.assertEqual(len(tarefa["avisos"]), 1, tarefa["avisos"])
        aviso = tarefa["avisos"][0]
        self.assertEqual((aviso["titulo"], aviso["nivel"]),
                         ("Um arquivo não foi copiado para a nuvem", "aviso"))
        self.assertIn(str(Path("Processos") / "Lote 1" / self.pdf.name), aviso["mensagem"])
        self.assertIn(dica, aviso["mensagem"])
        self.assertIn("“Espelhar agora”", aviso["mensagem"])

    def tarefa_nova_de_nuvem(self, antes: set) -> dict:
        novas = [t for t in self.app.tarefas.listar() if t.tipo == "nuvem" and t.id not in antes]
        self.assertEqual(len(novas), 1)
        return self.esperar_tarefa(novas[0].id)

    def test_espelhar_agora(self):
        with mock.patch("helestron.compartilhar.nuvem.espelhar",
                        return_value=self.espelho("caminho longo demais")):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/compartilhar/nuvem/espelhar", {"destino": str(self.nuvem)})["tarefa"])
        self.conferir(tarefa, "caminho longo demais", "encurte o nome da pasta do lote")

    def test_espelho_ao_fim_do_lote(self):
        from helestron.servidor import api_processos

        self.cfg.definir("compartilhar", "espelhar_automaticamente", True)
        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.nuvem))
        antes = {t.id for t in self.app.tarefas.listar()}
        with mock.patch("helestron.compartilhar.nuvem.espelhar",
                        return_value=self.espelho("arquivo aberto ou sem permissão")):
            api_processos._espelhar_ao_fim(self.app)
            tarefa = self.tarefa_nova_de_nuvem(antes)
        self.conferir(tarefa, "arquivo aberto ou sem permissão", "feche o arquivo")

    def test_espelho_ao_fim_da_transcricao(self):
        from helestron.servidor import api_compartilhar

        self.cfg.definir("compartilhar", "espelhar_automaticamente", True)
        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.nuvem))
        antes = {t.id for t in self.app.tarefas.listar()}
        with mock.patch("helestron.compartilhar.nuvem.espelhar",
                        return_value=self.espelho("arquivo aberto ou sem permissão")):
            api_compartilhar.depois_de_salvar(self.app)
            tarefa = self.tarefa_nova_de_nuvem(antes)
        self.conferir(tarefa, "arquivo aberto ou sem permissão", "feche o arquivo")

    def test_tudo_copiado_nao_avisa(self):
        from helestron.compartilhar import nuvem

        with mock.patch("helestron.compartilhar.nuvem.espelhar",
                        return_value=nuvem.Espelho(1, 0)):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/compartilhar/nuvem/espelhar", {"destino": str(self.nuvem)})["tarefa"])
        self.assertEqual((tarefa["status"], tarefa["avisos"]), ("1 copiado, 0 sem mudança.", []))
        self.assertEqual(tarefa["resultado"]["nao_copiados"], [])

    def test_frase_com_mais_de_cinco(self):
        from helestron.servidor import api_compartilhar

        nao = [(self.acervo / f"{i}.pdf", "caminho longo demais") for i in range(7)]
        titulo, mensagem = api_compartilhar.frase_nao_copiados(nao, self.acervo)
        self.assertEqual(titulo, "7 arquivos não foram copiados para a nuvem")
        self.assertIn("; e mais 2.", mensagem)


# ========================================================== pacote
class TestPacoteMostraOsAvisos(ServidorDeTeste):
    """Os avisos do pacote (número que faltou, .zip acima do limite do
    ChatGPT) iam só para o registro; com o .zip grande demais, a tela ainda
    mandava arrastar o .zip."""

    def gerar(self, avisos=(), faltaram=(), tamanho=1024) -> dict:
        from helestron.compartilhar import chatgpt

        pasta = self.amb.dados / "Pacotes para IA" / "Pacote para o ChatGPT 2026-10-07 10h00"
        pacote = chatgpt.Pacote(pasta, pasta.with_suffix(".zip"), list(faltaram), list(avisos),
                                tamanho)
        with mock.patch("helestron.compartilhar.chatgpt.gerar_pacote", return_value=pacote):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/compartilhar/pacote")["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        return tarefa

    def test_zip_grande_demais(self):
        from helestron.compartilhar import chatgpt

        frase = ("O .zip tem 600 MB, acima do que o ChatGPT aceita (cerca de 500 MB): em vez "
                 "dele, arraste os arquivos da pasta do pacote.")
        tarefa = self.gerar([frase], tamanho=(chatgpt.LIMITE_ARQUIVO_MB + 100) * 1024 * 1024)
        r = tarefa["resultado"]
        self.assertIs(r["grande_demais"], True)
        self.assertIn("Arraste os arquivos da pasta do pacote", r["mensagem"])
        self.assertNotIn("Arraste o .zip", r["mensagem"])
        self.assertIn(frase, r["mensagem"])
        self.assertEqual(r["avisos"], [frase])
        self.assertEqual(r["tamanho_mb"], float(chatgpt.LIMITE_ARQUIVO_MB + 100))
        self.assertIn("arraste os arquivos da pasta do pacote", tarefa["status"])
        self.assertEqual([(a["titulo"], a["mensagem"]) for a in tarefa["avisos"]],
                         [("Pacote para o ChatGPT", frase)])

    def test_processo_que_faltou(self):
        frase = "O processo 0700999-61.2024.8.02.0001 não está no acervo e não foi para o pacote."
        tarefa = self.gerar([frase], faltaram=["0700999-61.2024.8.02.0001"])
        r = tarefa["resultado"]
        self.assertIs(r["grande_demais"], False)
        self.assertTrue(r["mensagem"].startswith(
            "Pacote para o ChatGPT 2026-10-07 10h00.zip. Arraste o .zip"))
        self.assertIn("Atenção: " + frase, r["mensagem"])
        self.assertEqual(r["faltaram"], ["0700999-61.2024.8.02.0001"])
        self.assertEqual(tarefa["status"], "Pacote pronto, com 1 aviso.")
        self.assertEqual([a["mensagem"] for a in tarefa["avisos"]], [frase])

    def test_sem_avisos(self):
        tarefa = self.gerar()
        self.assertEqual((tarefa["status"], tarefa["avisos"], tarefa["resultado"]["avisos"]),
                         ("Pacote pronto.", [], []))
        self.assertNotIn("Atenção", tarefa["resultado"]["mensagem"])


# ============================================ pacotes antigos x sigilo
class TestPacotesAntigosPerdemOSigiloso(ServidorDeTeste):
    """Só o "Gerar o pacote" seguinte tirava dos pacotes antigos o processo
    que virou sigiloso: a transcrição salva como sigilosa e o sigilo que a
    pauta revelou deixavam o pacote pronto para ir de novo ao ChatGPT."""

    def setUp(self):
        super().setUp()
        from helestron.nucleo import sigilo
        from testes.apoio_download import numero

        self.addCleanup(sigilo.esquecer_pauta)
        self.x = numero("0700777", tr="02")
        self.y = numero("0700778", tr="02")
        nome = "Pacote para o ChatGPT 2026-10-01 09h00"
        self.pasta = self.amb.dados / "Pacotes para IA" / nome
        (self.pasta / "autos").mkdir(parents=True)
        indice = (f"# Índice\n- {self.x.formatado}: autos/{self.x.nome_arquivo}.pdf\n"
                  f"- {self.y.formatado}: autos/{self.y.nome_arquivo}.pdf\n")
        for n in (self.x, self.y):
            (self.pasta / "autos" / f"{n.nome_arquivo}.pdf").write_bytes(b"%PDF-1.4 autos")
        (self.pasta / "INDICE.md").write_text(indice, encoding="utf-8")
        self.zip = self.pasta.with_suffix(".zip")
        with zipfile.ZipFile(self.zip, "w") as z:
            for f in sorted(self.pasta.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(self.pasta).as_posix())

    def x_saiu(self) -> bool:
        if (self.pasta / "autos" / f"{self.x.nome_arquivo}.pdf").exists():
            return False
        with zipfile.ZipFile(self.zip) as z:
            return not any(self.x.nome_arquivo in n for n in z.namelist())

    def conferir_y_ficou(self) -> None:
        self.assertTrue((self.pasta / "autos" / f"{self.y.nome_arquivo}.pdf").exists())
        indice = (self.pasta / "INDICE.md").read_text(encoding="utf-8")
        self.assertNotIn(self.x.formatado, indice)
        self.assertIn(self.y.formatado, indice)
        with zipfile.ZipFile(self.zip) as z:
            self.assertIn(f"autos/{self.y.nome_arquivo}.pdf", z.namelist())
            self.assertNotIn(self.x.formatado, z.read("INDICE.md").decode("utf-8"))

    def transcricao_sigilosa(self) -> None:
        pasta = self.amb.dados / "Sigilosos" / "Transcricoes"
        pasta.mkdir(parents=True)
        (pasta / f"{self.x.nome_arquivo} 2026-10-07 10h00.docx").write_bytes(b"docx")

    def test_transcricao_sigilosa(self):
        from helestron.servidor import api_compartilhar

        self.transcricao_sigilosa()
        api_compartilhar.depois_de_salvar(self.app)
        self.assertTrue(_esperar(_segundo_plano_terminou))
        self.assertTrue(self.x_saiu(), "o pacote antigo continuou com o sigiloso")
        self.conferir_y_ficou()

    def test_com_autos_presos_os_pacotes_nao_esperam(self):
        from helestron.servidor import api_compartilhar

        preso = self.amb.dados / "Acervo" / "Processos" / "Lote" / f"{self.y.nome_arquivo}.pdf"
        preso.parent.mkdir(parents=True)
        preso.write_bytes(b"%PDF")
        api_compartilhar.registrar_presos(self.app, [preso])
        self.transcricao_sigilosa()
        with mock.patch("helestron.servicos.atualizar_indice") as indice:
            api_compartilhar.depois_de_salvar(self.app)
            self.assertTrue(_esperar(_segundo_plano_terminou))
        self.assertTrue(self.x_saiu(), "o pacote antigo esperou os autos presos")
        indice.assert_not_called()          # o índice e o espelho, esses esperam

    def test_pauta_revela_o_sigilo_sem_nada_no_acervo(self):
        from helestron.servidor import api_pauta
        from testes.test_nucleo import pauta_com_sigiloso

        pauta_com_sigiloso(self.amb.local / "pauta.sqlite3", self.x)
        api_pauta.sigilo_revelado(self.app, [self.x.formatado])
        self.assertTrue(_esperar(_segundo_plano_terminou))
        self.assertTrue(self.x_saiu(), "o pacote antigo continuou com o sigiloso")
        self.conferir_y_ficou()

    def test_pacote_que_nao_pode_ser_limpo_vira_aviso(self):
        from helestron.servidor import api_compartilhar

        frase = ("Não consegui tirar do pacote antigo “x.zip” o que é de processo em segredo de "
                 "justiça (arquivo aberto): apague-o à mão.")
        leitor = self.eventos()
        with mock.patch("helestron.servicos.retirar_sigilosos_dos_pacotes",
                        return_value=[frase]):
            api_compartilhar._atualizar_indice(self.app)
        aviso = leitor.esperar("aviso", lambda d: d.get("mensagem") == frase)
        self.assertEqual((aviso["titulo"], aviso["nivel"]),
                         ("Pacote antigo com processo sigiloso", "aviso"))


if __name__ == "__main__":
    unittest.main()
