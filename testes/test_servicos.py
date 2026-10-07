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

    def test_sigilosos_e_pauta_fora_de_toda_pasta_da_nuvem(self):
        """Nada de segredo de justiça na nuvem: os sigilosos e a pauta não
        ficam em pasta nenhuma do OneDrive ou do Google Drive (e não só fora
        da pasta do espelho)."""
        onedrive = self.amb.raiz / "OneDrive - TJAL"
        acervo = self.base / "Acervo"
        with mock.patch.dict("os.environ", {"OneDrive": str(onedrive)}):
            frase = servicos.problema_nas_pastas(acervo, onedrive / "Sigilosos")
            self.assertIn("segredo de justiça", frase)
            self.assertIn("OneDrive", frase)
            frase = servicos.problema_nas_pastas(acervo, self.base / "Sigilosos",
                                                 onedrive / "Pauta")
            self.assertIn("pauta exportada", frase)
            # a tela de Ajustes confere a nuvem à parte, só da pasta trocada
            self.assertIsNone(servicos.problema_nas_pastas(acervo, onedrive / "Sigilosos",
                                                           nuvem=False))
            self.assertIsNone(servicos.sigilo_na_nuvem(self.base / "Sigilosos", None))
        frase = servicos.sigilo_na_nuvem(Path("/home/x/Google Drive/Meu Drive/Sigilosos"))
        self.assertIn("Google Drive", frase)
        self.assertIsNone(servicos.problema_nas_pastas(acervo, self.base / "Sigilosos",
                                                       self.base / "Pauta"))

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


class TestPendenciaDaNuvem(unittest.TestCase):
    """A pasta da nuvem em conflito (config.ini editado à mão ou de versão
    anterior): o espelho não roda, e o Início diz por quê e onde corrigir."""

    def setUp(self):
        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.cfg = self.amb.cfg
        self.nuvem = self.amb.raiz / "OneDrive"

    def pendencia(self):
        with mock.patch.object(servicos, "_pacote_presente", return_value=True), \
                mock.patch.object(servicos, "modelo_instalado", return_value=True):
            achadas = [p for p in servicos.pendencias(self.cfg) if p.chave == "nuvem"]
        self.assertLessEqual(len(achadas), 1)
        return achadas[0] if achadas else None

    def test_sem_conflito_nada(self):
        self.assertIsNone(self.pendencia())                    # sem pasta da nuvem
        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.nuvem))
        self.assertIsNone(self.pendencia())

    def test_sigilosos_ou_pauta_dentro_da_nuvem(self):
        from helestron.nucleo import config

        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.nuvem))
        for secao, chave in (("geral", "pasta_sigilosos"), ("pauta", "pasta")):
            with self.subTest(chave=chave):
                self.cfg.definir("geral", "pasta_sigilosos", str(self.amb.dados / "Sigilosos"))
                self.cfg.definir("pauta", "pasta", str(self.amb.dados / "Pauta"))
                self.cfg.definir(secao, chave, str(self.nuvem / "Gabinete"))
                p = self.pendencia()
                self.assertIsNotNone(p)
                self.assertEqual((p.titulo, p.acao), ("Pasta da nuvem em conflito",
                                                      "ajustes#pastas"))
                self.assertEqual(p.mensagem, config.conflito_com_a_nuvem(
                    self.nuvem, self.cfg.pasta_sigilosos, servicos.pasta_pauta(self.cfg)))

    def test_nuvem_dentro_dos_sigilosos(self):
        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.amb.dados / "Sigilosos" / "OD"))
        p = self.pendencia()
        self.assertEqual(p.acao, "ajustes#compartilhar")
        self.assertIn("segredo de justiça", p.mensagem)

    def test_nuvem_dentro_do_acervo(self):
        self.cfg.definir("compartilhar", "pasta_nuvem", str(self.amb.dados / "Acervo" / "OD"))
        p = self.pendencia()
        self.assertEqual(p.acao, "ajustes#compartilhar")
        self.assertIn("dentro do acervo", p.mensagem)
        self.assertTrue(p.mensagem.endswith("o acervo não é espelhado na nuvem."), p.mensagem)


class TestNumeroNoNome(unittest.TestCase):
    """Sem o módulo da transcrição, a leitura de reserva perdia o "-NN" do
    incidente: a transcrição do incidente virava a do processo principal."""

    def test_reserva_le_o_dependente(self):
        with mock.patch("helestron.transcricao.arquivo.numero_do_caminho",
                        side_effect=AttributeError):
            n = servicos.numero_no_nome(Path("Transcricoes") / f"{NUMERO}-01 2026-10-07 10h00.docx")
            self.assertEqual((n.formatado, n.dependente), (NUMERO + "/01", "01"))
            n = servicos.numero_no_nome(Path("Lote") / "_controle" / "midias" / f"{NUMERO}-02"
                                        / "video.mp4")
            self.assertEqual(n.dependente, "02")
            self.assertEqual(servicos.numero_no_nome(Path(f"{NUMERO}.docx")).dependente, "")
            self.assertIsNone(servicos.numero_no_nome(Path("Pasta") / "gravação.wav"))

    def test_igual_ao_da_transcricao(self):
        from helestron.transcricao import arquivo

        caminho = Path(f"{NUMERO}-01.docx")
        with mock.patch("helestron.transcricao.arquivo.numero_do_caminho",
                        side_effect=AttributeError):
            reserva = servicos.numero_no_nome(caminho)
        self.assertEqual(reserva, arquivo.numero_do_caminho(caminho))


class TestPacotesPerdemOSigiloso(unittest.TestCase):
    """servicos.retirar_sigilosos_dos_pacotes e servicos.atualizar_indice (o
    caminho da transcrição e da pauta): os pacotes já gerados perdem o
    processo que virou sigiloso, sem esperar o próximo "Gerar o pacote"."""

    def setUp(self):
        import zipfile

        self.amb = AmbienteTemporario().iniciar()
        self.addCleanup(self.amb.parar)
        self.cfg = self.amb.cfg
        self.x = cnj.ler(NUMERO)
        self.y = cnj.ler("0700124-68.2024.8.02.0001")
        self.pasta = servicos.pasta_pacotes() / "Pacote para o ChatGPT 2026-10-01 09h00"
        (self.pasta / "autos").mkdir(parents=True)
        for n in (self.x, self.y):
            (self.pasta / "autos" / f"{n.nome_arquivo}.pdf").write_bytes(b"%PDF")
        (self.pasta / "INDICE.md").write_text(f"- {self.x.formatado}\n- {self.y.formatado}\n",
                                              encoding="utf-8")
        with zipfile.ZipFile(self.pasta.with_suffix(".zip"), "w") as z:
            z.writestr(f"autos/{self.x.nome_arquivo}.pdf", b"%PDF")
            z.writestr(f"autos/{self.y.nome_arquivo}.pdf", b"%PDF")

    def tornar_sigiloso(self) -> None:
        pasta = self.amb.dados / "Sigilosos" / "Transcricoes"
        pasta.mkdir(parents=True)
        (pasta / f"{self.x.nome_arquivo} 2026-10-07 10h00.docx").write_bytes(b"docx")

    def conferir(self) -> None:
        import zipfile

        self.assertFalse((self.pasta / "autos" / f"{self.x.nome_arquivo}.pdf").exists())
        self.assertTrue((self.pasta / "autos" / f"{self.y.nome_arquivo}.pdf").exists())
        self.assertNotIn(self.x.formatado, (self.pasta / "INDICE.md").read_text(encoding="utf-8"))
        with zipfile.ZipFile(self.pasta.with_suffix(".zip")) as z:
            self.assertEqual(z.namelist(), [f"autos/{self.y.nome_arquivo}.pdf"])

    def test_pasta_dos_pacotes(self):
        self.assertEqual(servicos.pasta_pacotes(), self.amb.dados / "Pacotes para IA")
        from helestron.servidor import api_compartilhar

        self.assertEqual(api_compartilhar.pasta_pacotes(), servicos.pasta_pacotes())

    def test_retirar(self):
        self.assertEqual(servicos.retirar_sigilosos_dos_pacotes(self.cfg), [])
        self.assertTrue((self.pasta / "autos" / f"{self.x.nome_arquivo}.pdf").exists())
        self.tornar_sigiloso()
        with self.assertLogs("compartilhar.chatgpt", "WARNING"):
            self.assertEqual(servicos.retirar_sigilosos_dos_pacotes(self.cfg), [])
        self.conferir()

    def test_atualizar_indice_tambem_limpa_os_pacotes(self):
        self.tornar_sigiloso()
        with self.assertLogs("compartilhar.chatgpt", "WARNING"):
            rel = servicos.atualizar_indice(self.cfg)
        self.assertIsNotNone(rel)
        self.assertEqual(rel.avisos_pacotes, [])
        self.conferir()

    def test_aviso_do_pacote_que_nao_saiu(self):
        frase = "Não consegui tirar do pacote antigo o que é de processo em segredo de justiça."
        with mock.patch("helestron.compartilhar.chatgpt.retirar_sigilosos_dos_pacotes",
                        return_value=[frase]):
            self.tornar_sigiloso()
            rel = servicos.atualizar_indice(self.cfg)
        self.assertEqual(rel.avisos_pacotes, [frase])
        self.assertIn(frase, rel.avisos)

    def test_nunca_levanta(self):
        with mock.patch("helestron.compartilhar.chatgpt.retirar_sigilosos_dos_pacotes",
                        side_effect=OSError("disco")), \
                self.assertLogs("servicos", "WARNING"):
            self.tornar_sigiloso()
            self.assertEqual(servicos.retirar_sigilosos_dos_pacotes(self.cfg), [])
        with mock.patch.object(servicos, "pasta_pacotes", return_value=self.amb.raiz / "nada"):
            self.assertEqual(servicos.retirar_sigilosos_dos_pacotes(object()), [])


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
