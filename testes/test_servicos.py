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

    def test_conflito_da_nuvem(self):
        acervo = self.base / "Acervo"
        for nuvem in (acervo, acervo / "OneDrive", self.base, self.amb.raiz):
            with self.subTest(nuvem=nuvem):
                self.assertTrue(servicos.conflito_da_nuvem(nuvem, acervo))
        self.assertIsNone(servicos.conflito_da_nuvem(self.amb.raiz / "OneDrive", acervo))
        self.assertIsNone(servicos.conflito_da_nuvem("", acervo))
        # a mesma subpasta do espelho de compartilhar.nuvem
        from helestron.compartilhar import nuvem as mod_nuvem

        self.assertEqual(servicos.SUBPASTA_NUVEM, mod_nuvem.SUBPASTA)

    def test_gravacao_guardada_na_pasta_dos_sigilosos(self):
        pasta = self.base / "Sigilosos" / "Gravacoes"
        pasta.mkdir(parents=True)
        (pasta / "sala [2].wav").write_bytes(b"12345")
        self.assertTrue(servicos.copia_na_pasta_dos_sigilosos(self.amb.cfg, "sala [2].wav", 5))
        self.assertTrue(servicos.copia_na_pasta_dos_sigilosos(self.amb.cfg, "sala [2].wav", None))
        self.assertFalse(servicos.copia_na_pasta_dos_sigilosos(self.amb.cfg, "sala [2].wav", 6))
        self.assertFalse(servicos.copia_na_pasta_dos_sigilosos(self.amb.cfg, "outra.wav", 5))
        self.assertFalse(servicos.copia_na_pasta_dos_sigilosos(self.amb.cfg, "", 5))

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
            # "Padrão do Windows" escolhido na tela vai explícito
            servicos.nova_sessao(cnj.ler(NUMERO), object(), lambda t, d: None, dispositivo="")
            self.assertEqual(Sessao.call_args.kwargs["dispositivo"], "")

    def test_padrao_do_windows_nao_cai_no_microfone_da_configuracao(self):
        """Achado: a tela mostrava "Padrão do Windows" e mandava "", mas a
        sessão gravava pelo microfone (índice velho) do config.ini."""
        amb = AmbienteTemporario().iniciar()
        self.addCleanup(amb.parar)
        amb.cfg.definir("transcricao", "dispositivo", "3")
        sessao = servicos.nova_sessao(cnj.ler(NUMERO), amb.cfg, lambda t, d: None, dispositivo="")
        self.assertEqual(sessao.dispositivo, "")
        sessao = servicos.nova_sessao(cnj.ler(NUMERO), amb.cfg, lambda t, d: None)
        self.assertEqual(sessao.dispositivo, "3")

    def test_gravacao_enviada_leva_nome_e_data_para_a_ficha(self):
        from datetime import datetime

        quando = datetime(2026, 9, 15, 10, 30)
        with mock.patch("helestron.transcricao.arquivo.transcrever_arquivo") as transcrever:
            servicos.transcrever_gravacao(Path("/tmp/envio-abc.wav"), cnj.ler(NUMERO), object(),
                                          None, None, gravacao="sala 2.wav", data=quando)
            meta = transcrever.call_args.kwargs["meta"]
            self.assertEqual((meta.gravacao, meta.data, meta.tipo), ("sala 2.wav", quando, ""))
            servicos.transcrever_gravacao(Path("/tmp/a.wav"), cnj.ler(NUMERO), object(), None,
                                          None, participantes={"F1": "Juiz(a)"})
            self.assertEqual(transcrever.call_args.kwargs["meta"].participantes,
                             {"F1": "Juiz(a)"})
            servicos.transcrever_gravacao(Path("/tmp/a.wav"), cnj.ler(NUMERO), object(), None,
                                          None)
            self.assertNotIn("meta", transcrever.call_args.kwargs)

    def test_revisar_leva_a_ficha_da_audiencia(self):
        """Achado 38: o "Revisar" da tela criava a ficha só com o tipo e os
        participantes - sem início, término nem a data da audiência."""
        from datetime import datetime

        from helestron.transcricao.documento import MetaAudiencia

        sessao = MetaAudiencia(numero=NUMERO, tipo="Instrução", origem="ao vivo",
                               data=datetime(2026, 9, 15, 23, 30),
                               inicio=datetime(2026, 9, 15, 23, 30),
                               fim=datetime(2026, 9, 16, 0, 40),
                               participantes={"Testemunha": "Beltrano"},
                               gravacao="_audio\\x.flac", observacao="1 trecho não transcrito.")
        with mock.patch("helestron.transcricao.arquivo.transcrever_arquivo") as transcrever:
            servicos.transcrever_gravacao(Path("/tmp/x.flac"), cnj.ler(NUMERO), object(), None,
                                          None, meta=sessao)
            meta = transcrever.call_args.kwargs["meta"]
            self.assertIsNot(meta, sessao)
            self.assertIsNot(meta.participantes, sessao.participantes)
            self.assertEqual((meta.data, meta.inicio, meta.fim, meta.gravacao),
                             (sessao.data, sessao.inicio, sessao.fim, "_audio\\x.flac"))
            self.assertEqual((meta.origem, meta.observacao, meta.tipo), ("revisão", "", "Instrução"))
            self.assertEqual(sessao.origem, "ao vivo")       # a da sessão não muda
            # o que a tela escolheu agora prevalece
            servicos.transcrever_gravacao(Path("/tmp/x.flac"), cnj.ler(NUMERO), object(), None,
                                          None, meta=sessao, tipo="Una",
                                          participantes={"F1": "Juiz(a)"})
            meta = transcrever.call_args.kwargs["meta"]
            self.assertEqual(meta.tipo, "Una")
            self.assertEqual(meta.participantes, {"Testemunha": "Beltrano", "F1": "Juiz(a)"})
            self.assertEqual(sessao.participantes, {"Testemunha": "Beltrano"})
            # uma ficha que não é a de sessão ao vivo segue como veio
            gravada = MetaAudiencia(numero=NUMERO, origem="gravação", observacao="Obs.")
            servicos.transcrever_gravacao(Path("/tmp/x.flac"), cnj.ler(NUMERO), object(), None,
                                          None, meta=gravada)
            meta = transcrever.call_args.kwargs["meta"]
            self.assertEqual((meta.origem, meta.observacao), ("gravação", "Obs."))

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
