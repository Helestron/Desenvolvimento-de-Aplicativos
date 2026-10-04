"""helestron.servicos: a ponte entre a API e o motor (pastas, pendências, sessões)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from helestron import servicos, tarefas
from helestron.nucleo import caminhos, cnj

from testes.test_servidor_base import AmbienteTemporario

NUMERO = "0700123-83.2024.8.02.0001"


class TestPastas(unittest.TestCase):
    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.base = self.amb.dados

    def test_sigilosos_dentro_do_acervo(self):
        frase = servicos.problema_nas_pastas(self.base / "Acervo", self.base / "Acervo" / "Sig")
        self.assertIn("acervo", frase.lower())

    def test_pauta_dentro_do_acervo(self):
        frase = servicos.problema_nas_pastas(self.base / "Acervo", self.base / "Sigilosos",
                                             self.base / "Acervo" / "Pauta")
        self.assertIn("pauta exportada", frase)
        self.assertIn("segredo de justiça", frase)
        self.assertIsNone(servicos.problema_nas_pastas(self.base / "Acervo", self.base / "Sigilosos",
                                                       self.base / "Pauta"))
        # a pauta dentro dos sigilosos é permitida (nunca vai para a IA)
        self.assertIsNone(servicos.problema_nas_pastas(self.base / "Acervo", self.base / "Sigilosos",
                                                       self.base / "Sigilosos" / "Pauta"))

    def test_acervo_nao_contem_a_pasta_local_nem_o_programa(self):
        self.assertIn("senhas", servicos.problema_nas_pastas(self.amb.raiz, Path("/fora/sig")))
        with mock.patch.object(caminhos, "INSTALACAO", self.base / "Programa", create=True):
            frase = servicos.problema_nas_pastas(self.base, Path("/fora/sig"))
        self.assertIn("pasta do programa", frase)

    def test_pasta_da_pauta(self):
        cfg = self.amb.cfg
        self.assertEqual(servicos.pasta_pauta(cfg), self.base / "Pauta")
        cfg.definir("pauta", "pasta", str(self.base / "Planilhas"))
        self.assertEqual(servicos.pasta_pauta(cfg), self.base / "Planilhas")
        cfg.definir("pauta", "pasta", "Pauta exportada")
        self.assertEqual(servicos.pasta_pauta(cfg), self.base / "Pauta exportada")

    def test_pendencias_no_formato_da_tela_inicio(self):
        self.amb.cfg.definir("geral", "pasta_sigilosos", str(self.base / "Acervo" / "Sig"))
        with mock.patch.object(servicos, "_pacote_presente", return_value=True), \
                mock.patch.object(servicos, "modelo_instalado", return_value=False):
            lista = servicos.pendencias(self.amb.cfg)
        chaves = [p.chave for p in lista]
        self.assertEqual(chaves, ["pastas", "modelo"])
        self.assertEqual(lista[0].acao, "ajustes#pastas")
        self.assertEqual(set(lista[1].como_dict()), {"chave", "titulo", "mensagem", "acao"})
        self.assertEqual(lista[1].texto, lista[1].mensagem)

    def test_transcricoes_recentes(self):
        acervo = self.base / "Acervo" / "Transcricoes"
        sig = self.base / "Sigilosos" / "Transcricoes"
        for pasta in (acervo, sig):
            pasta.mkdir(parents=True)
        (acervo / "a.docx").write_bytes(b"x")
        (acervo / "~$a.docx").write_bytes(b"x")
        (sig / "b.docx").write_bytes(b"x")
        self.assertEqual([p.name for p in servicos.transcricoes_recentes(self.amb.cfg)], ["a.docx"])
        self.assertEqual(sorted(p.name for p in servicos.transcricoes_recentes(
            self.amb.cfg, incluir_sigilosas=True)), ["a.docx", "b.docx"])


class TestPontesDoMotor(unittest.TestCase):
    def test_nova_sessao_repassa_o_microfone(self):
        with mock.patch("helestron.transcricao.ao_vivo.SessaoAoVivo") as Sessao:
            servicos.nova_sessao(cnj.ler(NUMERO), object(), lambda t, d: None, dispositivo=2)
            self.assertEqual(Sessao.call_args.kwargs["dispositivo"], 2)
            servicos.nova_sessao(cnj.ler(NUMERO), object(), lambda t, d: None)
            self.assertNotIn("dispositivo", Sessao.call_args.kwargs)

    def test_componente_ausente_tem_frase(self):
        erro = servicos._ausente(ImportError("x", name="faster_whisper"), "transcrição")
        self.assertIn("faster_whisper", str(erro))
        self.assertIn("Helestron-Setup", str(erro))
        self.assertNotIn("INSTALAR.bat", servicos.DICA_INSTALAR)

    def test_sem_tk(self):
        fonte = Path(servicos.__file__).read_text(encoding="utf-8")
        self.assertNotIn("tkinter", fonte)
        fonte = Path(tarefas.__file__).read_text(encoding="utf-8")
        self.assertNotIn("tkinter", fonte)
        self.assertNotIn("import tk", fonte)


class TestRecursosETarefa(unittest.TestCase):
    def test_tudo_ou_nada(self):
        r = tarefas.Recursos()
        self.assertIsNone(r.tomar("A", ("navegador",)))
        self.assertEqual(r.tomar("B", ("microfone", "navegador")), "A")
        self.assertIsNone(r.quem_tem("microfone"))            # nada pela metade
        r.soltar("A")
        self.assertIsNone(r.tomar("B", ("microfone", "navegador")))

    def test_frase_de_recusa(self):
        self.assertEqual(tarefas.frase_ocupado("Baixar processos", ["o navegador dos portais"]),
                         "O navegador dos portais está em uso por outro trabalho: Baixar "
                         "processos. Espere esse trabalho terminar ou interrompa-o.")
        self.assertIn("estão em uso", tarefas.frase_ocupado("X", ["o microfone", "a nuvem"]))

    def test_tarefa_recusa_repetida_e_solta_no_fim(self):
        import threading

        gerente = tarefas.Recursos()
        segurar = threading.Event()
        t = tarefas.Tarefa("Baixar", (tarefas.NAVEGADOR,), gerente)
        self.assertIsNone(t.iniciar(segurar.wait, 5))
        self.assertIn("já está em andamento", t.iniciar(lambda: None))
        outra = tarefas.Tarefa("Testar", (tarefas.NAVEGADOR,), gerente)
        self.assertIn("Baixar", outra.motivo_recusa())
        segurar.set()
        self.assertTrue(t.esperar(5))
        self.assertIsNone(gerente.quem_tem(tarefas.NAVEGADOR))

    def test_pergunta_espera_e_prazo(self):
        p = tarefas.Pergunta("t", "m", prazo_s=0)
        self.assertIsNone(p.esperar(intervalo=0.01, margem_s=0.05))
        self.assertEqual(p.motivo, tarefas.PRAZO)
        p = tarefas.Pergunta("t", "m", 60, tipo="confirmar")
        self.assertNotIn("reenviavel", p.como_dict())
        self.assertTrue(p.cancelar())
        self.assertEqual(p.motivo, tarefas.CANCELADA)


if __name__ == "__main__":
    unittest.main()
