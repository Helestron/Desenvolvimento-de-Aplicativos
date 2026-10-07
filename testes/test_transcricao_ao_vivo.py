"""Sessão ao vivo de ponta a ponta: arquivo WAV no lugar do microfone e modelo
dublê no lugar do Whisper. Confere falante por fala, pausa, nome do DOCX
(número do processo, "(2)" se já existir), FLAC, diário, recuperação depois
de uma queda (processo de verdade morto no meio) e a revisão ao encerrar."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from helestron.nucleo import caminhos
from helestron.transcricao import ao_vivo, documento, microfone, modelos
from helestron.transcricao.ao_vivo import SessaoAoVivo, recuperar, recuperaveis
from helestron.transcricao.segmentador import TrechoDeAudio
from testes.apoio_transcricao import (NUMERO, TAXA, ModeloDuble, PastaTemporaria, ficha,
                                     gravar_wav, ler_docx, montar, roteiro_audiencia)

ESPERADO = [("Juiz(a)", "Bom dia a todos."), ("Promotor(a)", "Sem perguntas, Excelência."),
            ("Testemunha", "Eu vi o acidente."), ("Testemunha", "Nada mais.")]
ACOES_PADRAO = {4.0: ("definir_falante", "Promotor(a)"), 7.5: ("definir_falante", "Testemunha"),
                11.8: ("pausar",), 13.8: ("retomar",)}


class Eventos:
    def __init__(self):
        self.lista: list[tuple[str, object]] = []
        self._trava = threading.Lock()

    def __call__(self, tipo, dado):
        with self._trava:
            self.lista.append((tipo, dado))

    def de(self, tipo):
        with self._trava:
            return [d for t, d in self.lista if t == tipo]


class BaseSessao(unittest.TestCase):
    ajustes: dict = {}

    def setUp(self):
        self.tmp = PastaTemporaria(**self.ajustes)
        self.cfg = self.tmp.config()
        self.wav = gravar_wav(self.tmp.raiz / "audiencia.wav", roteiro_audiencia())
        self.modelo = ModeloDuble()

    def tearDown(self):
        self.tmp.apagar()

    def sessao(self, acoes=None, motor=None, wav=None, **kw):
        eventos = Eventos()
        pendentes = dict(ACOES_PADRAO if acoes is None else acoes)
        caixa = {}

        def avancar(t):
            for instante in sorted(pendentes):
                if t >= instante - 1e-9:
                    nome, *args = pendentes.pop(instante)
                    getattr(caixa["s"], nome)(*args)

        def fabrica(ao_bloco, ao_nivel, ao_aviso):
            return microfone.CapturaDeArquivo(wav or self.wav, ao_bloco, ao_nivel, tempo_real=False,
                                              ao_aviso=ao_aviso, ao_avancar=avancar)

        kw.setdefault("falante", "Juiz(a)")
        s = SessaoAoVivo(NUMERO, self.cfg, eventos, captura_fabrica=fabrica,
                         motor_fabrica=motor or (lambda: self.modelo), **kw)
        caixa["s"] = s
        return s, eventos

    def rodar(self, refinar=False, **kw):
        s, eventos = self.sessao(**kw)
        s.iniciar()
        self.assertTrue(s.captura.esperar(30))
        final = s.encerrar(refinar=refinar)
        return s, eventos, final


class TestSessaoAoVivo(BaseSessao):
    def test_ponta_a_ponta(self):
        s, eventos, final = self.rodar(tipo="Instrução", participantes={"Testemunha": "Beltrano"})
        pasta = self.cfg.pasta_transcricoes
        # DOCX com o número do processo, na pasta dedicada
        self.assertEqual(final, pasta / f"{NUMERO}.docx")
        self.assertEqual(s.caminho_docx, final)
        # falas com o falante certo; a fala da pausa não entrou; marca da pausa
        falas = [(f.falante, f.texto) for f in s.falas if f.falante]
        self.assertEqual(falas, ESPERADO)
        marcas = [f for f in s.falas if not f.falante]
        self.assertEqual(len(marcas), 1)
        self.assertIn("Gravação pausada às", marcas[0].texto)
        self.assertEqual([(f.falante, f.texto) for f in eventos.de("fala") if f.falante], ESPERADO)
        # tempos da gravação, sem contar a pausa de 2 s
        self.assertAlmostEqual(s.falas[0].inicio, 0.5, delta=0.1)
        self.assertAlmostEqual(s.falas[-1].inicio, 13.0, delta=0.25)
        self.assertAlmostEqual(s.tempo, 16.0, delta=0.01)
        # parâmetros do Whisper ao vivo
        kw = self.modelo.chamadas[0]
        self.assertEqual((kw["language"], kw["beam_size"], kw["vad_filter"],
                          kw["condition_on_previous_text"]), ("pt", 2, True, False))
        self.assertEqual(kw["temperature"], [0.0, 0.2, 0.4])
        self.assertTrue(kw["initial_prompt"].startswith("Transcrição de audiência"))
        # FLAC 16 kHz mono com o tempo gravado (sem a pausa)
        import soundfile as sf

        info = sf.info(str(s.caminho_audio))
        self.assertEqual((info.samplerate, info.channels, info.format), (16000, 1, "FLAC"))
        self.assertAlmostEqual(info.duration, 16.0, delta=0.01)
        self.assertEqual(s.caminho_audio.parent, pasta / "_audio")
        self.assertTrue(s.caminho_audio.name.startswith(f"{NUMERO} "))
        # diário: cabeçalho, uma linha por fala, fim
        linhas = [json.loads(x) for x in s.caminho_diario.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(linhas[0]["tipo"], "inicio")
        self.assertEqual(linhas[0]["meta"]["numero"], NUMERO)
        self.assertEqual(linhas[0]["docx"], final.name)
        self.assertEqual(len([x for x in linhas if "texto" in x]), len(s.falas))
        self.assertEqual(linhas[-1]["tipo"], "fim")
        self.assertIs(linhas[-1]["fim"], True)
        # o documento
        paragrafos, tabelas, rodape = ler_docx(final)
        corpo = paragrafos[paragrafos.index("TRANSCRIÇÃO") + 1:]
        self.assertEqual(corpo[0], "Juiz(a) [00:00:00] — Bom dia a todos.")
        self.assertEqual(corpo[1], "Promotor(a) [00:00:04] — Sem perguntas, Excelência.")
        self.assertTrue(corpo[3].startswith("[00:00:11] — (Gravação pausada às"))
        self.assertEqual(corpo[4], "Testemunha [00:00:13] — Nada mais.")
        self.assertNotIn("IDENTIFICAÇÃO DOS FALANTES", paragrafos)
        f = ficha(tabelas)
        self.assertEqual(f["Processo nº"], NUMERO)
        self.assertEqual(f["Tipo de audiência"], "Instrução")
        # quem falou, na ordem, com o nome informado para o papel
        self.assertEqual(f["Participantes"], "Juiz(a)\nPromotor(a)\nTestemunha: Beltrano")
        self.assertEqual(f["Duração da gravação"], "00:00:16")
        self.assertEqual(f["Magistrado(a)"], "Fulana de Tal (Juíza de Direito)")
        self.assertEqual(f["Forma da transcrição"], "Simultânea (ao vivo, pelo microfone)")
        self.assertNotIn("Observação", f)
        # eventos
        self.assertEqual(eventos.de("fim"), [final])
        self.assertIn(final, eventos.de("salvo"))
        self.assertIn("Pausado", eventos.de("estado"))
        self.assertTrue(eventos.de("nivel"))
        self.assertTrue(all(a >= 0 for a in eventos.de("atraso")))
        self.assertEqual(eventos.de("erro"), [])
        # nada de sobra na pasta: só o DOCX e a pasta _audio
        self.assertEqual(sorted(p.name for p in pasta.iterdir()), sorted(["_audio", final.name]))
        self.assertEqual(recuperaveis(self.cfg), [])
        # encerrar de novo devolve o mesmo resultado
        self.assertEqual(s.encerrar(), final)

    def test_nome_livre_quando_ja_existe(self):
        pasta = self.cfg.pasta_transcricoes
        pasta.mkdir(parents=True)
        existente = pasta / f"{NUMERO}.docx"
        existente.write_bytes(b"transcricao ja revisada")
        _, _, final = self.rodar()
        self.assertEqual(final.name, f"{NUMERO} (2).docx")
        self.assertEqual(existente.read_bytes(), b"transcricao ja revisada")

    def test_documento_reservado_logo_no_inicio(self):
        s, eventos = self.sessao(acoes={})
        s.iniciar()
        try:
            self.assertTrue(s.caminho_docx.exists())
            paragrafos, tabelas, _ = ler_docx(s.caminho_docx)
            self.assertIn("em andamento", ficha(tabelas)["Observação"])
            # sessão aberta não aparece como "interrompida"
            self.assertEqual(recuperaveis(self.cfg), [])
        finally:
            s.captura.esperar(30)
            s.encerrar()

    def test_salvamento_automatico(self):
        antigo = ao_vivo.INTERVALO_SALVAR_S
        ao_vivo.INTERVALO_SALVAR_S = 0.0
        try:
            s, eventos, final = self.rodar()
        finally:
            ao_vivo.INTERVALO_SALVAR_S = antigo
        salvos = eventos.de("salvo")
        self.assertGreaterEqual(len(salvos), 3)
        self.assertTrue(all(p == final for p in salvos))

    def test_troca_de_falante_no_meio_da_fala(self):
        # a troca corta o trecho no instante: o que veio antes fica com o anterior
        audio = montar([("silencio", 0.5), ("fala", 2.0, 200), ("fala", 2.0, 300),
                        ("silencio", 1.0)])
        wav = gravar_wav(self.tmp.raiz / "emendado.wav", audio)
        s, _, _ = self.rodar(wav=wav, acoes={2.5: ("definir_falante", "Advogado(a) do autor")})
        self.assertEqual([(f.falante, f.texto) for f in s.falas],
                         [("Juiz(a)", "Bom dia a todos."),
                          ("Advogado(a) do autor", "Sem perguntas, Excelência.")])

    def test_modelo_indisponivel_mantem_a_gravacao(self):
        def sem_modelo():
            raise modelos.ModeloAusente("Sem acesso a huggingface.co (simulado).")

        with self.assertLogs("transcricao.ao_vivo", "ERROR"):
            s, eventos, final = self.rodar(motor=sem_modelo)
        self.assertEqual(s.falas[0].falante, "")              # só a marca da pausa
        self.assertEqual(len(eventos.de("erro")), 1)
        self.assertIn("Transcrever uma gravação", eventos.de("erro")[0])
        f = ficha(ler_docx(final)[1])
        self.assertIn("4 trechos de fala não foram transcritos", f["Observação"])
        self.assertIn("consta da gravação", f["Observação"])
        # o DOCX vai para os autos: informa o fato, sem mandar clicar em nada
        self.assertNotIn("Transcrever uma gravação", f["Observação"])
        self.assertNotIn("(s)", f["Observação"])
        import soundfile as sf

        self.assertAlmostEqual(sf.info(str(s.caminho_audio)).duration, 16.0, delta=0.01)

    def test_falha_num_trecho_nao_para_a_audiencia(self):
        self.modelo.falhar_em = 1
        with self.assertLogs("transcricao.ao_vivo", "ERROR"):
            s, eventos, final = self.rodar()
        textos = [f.texto for f in s.falas if f.falante]
        self.assertEqual(textos, ["Bom dia a todos.", "Eu vi o acidente.", "Nada mais."])
        self.assertEqual(len(eventos.de("aviso")), 1)
        obs = ficha(ler_docx(final)[1])["Observação"]
        self.assertIn("1 trecho de fala não foi transcrito", obs)
        self.assertNotIn("Transcrever uma gravação", obs)

    def test_microfone_indisponivel_nao_deixa_lixo(self):
        class SemMicrofone:
            tempo_real = True

            def iniciar(self):
                raise microfone.MicrofoneIndisponivel("Nenhum microfone foi encontrado.")

            def parar(self):
                pass

        s = SessaoAoVivo(NUMERO, self.cfg, Eventos(), captura_fabrica=lambda *a: SemMicrofone(),
                         motor_fabrica=lambda: self.modelo)
        with self.assertRaises(microfone.MicrofoneIndisponivel):
            s.iniciar()
        pasta = self.cfg.pasta_transcricoes
        self.assertEqual([p.name for p in pasta.iterdir()], ["_audio"])
        self.assertEqual(list((pasta / "_audio").iterdir()), [])
        self.assertEqual(recuperaveis(self.cfg), [])
        with self.assertRaises(RuntimeError):
            s.encerrar()

    def test_aviso_de_atraso_sugere_modelo_base(self):
        s, eventos = self.sessao()
        s.captura = types.SimpleNamespace(tempo_real=True)
        s._seg._amostras = 60 * TAXA
        s._medir_atraso(TrechoDeAudio(0.0, 10.0, np.zeros(10, dtype=np.float32)))
        s._medir_atraso(TrechoDeAudio(0.0, 12.0, np.zeros(10, dtype=np.float32)))
        self.assertEqual(eventos.de("atraso"), [50.0, 48.0])
        avisos = eventos.de("aviso")
        self.assertEqual(len(avisos), 1)       # não repete o aviso a cada trecho
        self.assertIn("\"base\"", avisos[0])

    def test_rotulo_vazio_e_definir_o_mesmo_falante(self):
        s, _ = self.sessao(falante="")
        s.definir_falante("")
        self.assertEqual(s.falante, "")
        s.definir_falante("  Perito(a) ")
        self.assertEqual(s.falante, "Perito(a)")

    def test_rotulo_digitado_nao_vai_para_o_registro(self):
        """O rótulo do falante é texto livre (até 40 caracteres), e é comum
        digitar o nome de quem depõe: o registro (Logs, em INFO) só leva a
        posição F1-F8 - nunca o nome, ainda mais em audiência sigilosa."""
        s, _ = self.sessao(falante="", sigiloso=True,
                           participantes={"F1": "Juiz(a)", "F3": "Testemunha"})
        with self.assertLogs("transcricao", "DEBUG") as registro:
            s.definir_falante("Testemunha Maria da Silva")
            s.definir_falante("Testemunha")
            s.definir_falante("")
        texto = "\n".join(registro.output)
        self.assertNotIn("Maria", texto)
        self.assertIn("falante: rótulo digitado", texto)
        self.assertIn("falante: F3", texto)
        self.assertIn("falante: (sem rótulo)", texto)


    def test_mesma_frase_dita_por_outra_parte_nao_some(self):
        """Achado 31: "Sem perguntas, Excelência." do Ministério Público e,
        depois, da defesa. O filtro de alucinação tratava a segunda como
        repetição do modelo e a apagava do termo, sem aviso."""
        audio = montar([("silencio", 0.5), ("fala", 2.0, 300), ("silencio", 2.0),
                        ("fala", 2.0, 300), ("silencio", 1.5), ("fala", 1.0, 250),
                        ("silencio", 1.0)])
        wav = gravar_wav(self.tmp.raiz / "sem_perguntas.wav", audio)
        s, _, final = self.rodar(wav=wav, falante="Promotor(a)",
                                 acoes={3.5: ("definir_falante", "Defensor(a)")})
        self.assertEqual([(f.falante, f.texto) for f in s.falas],
                         [("Promotor(a)", "Sem perguntas, Excelência."),
                          ("Defensor(a)", "Sem perguntas, Excelência."),
                          ("Defensor(a)", "Nada mais.")])
        paragrafos, _, _ = ler_docx(final)
        self.assertIn("Defensor(a) [00:00:04] — Sem perguntas, Excelência. Nada mais.", paragrafos)

    def test_mapa_das_teclas_nao_vai_para_a_ficha(self):
        """Achado 37: a tela manda {"F1": "Juiz(a)", ...}; a ficha listava
        "F1: Juiz(a)" ... "F8: Outro", os oito papéis, compareçam ou não.
        Agora lista quem falou."""
        mapa = {f"F{i + 1}": papel for i, papel in enumerate(
            ["Juiz(a)", "Promotor(a)", "Defensor(a)", "Advogado(a) do autor",
             "Advogado(a) do réu", "Testemunha", "Parte", "Outro"])}
        s, _, final = self.rodar(participantes=mapa)
        self.assertEqual(s.botoes, mapa)
        self.assertEqual(s.meta.participantes, {})
        f = ficha(ler_docx(final)[1])
        self.assertEqual(f["Participantes"], "Juiz(a)\nPromotor(a)\nTestemunha")
        self.assertNotIn("F1", f["Participantes"])

    def test_numero_do_incidente_com_hifen(self):
        """Achado 33: "...0001-01" (o nome do DOCX do incidente) virava o
        principal."""
        s, _ = self.sessao(acoes={})
        self.assertEqual(s.numero.principal, NUMERO)
        s = SessaoAoVivo(f"{NUMERO}-01", self.cfg, Eventos())
        self.assertEqual((s.numero.principal, s.numero.dependente), (NUMERO, "01"))
        self.assertEqual(s.meta.numero, f"{NUMERO}/01")
        self.assertEqual(SessaoAoVivo(f"{NUMERO}/02", self.cfg, Eventos()).numero.dependente, "02")


class TestRevisaoAoEncerrar(BaseSessao):
    def test_refinar_substitui_e_guarda_a_versao_ao_vivo(self):
        revisao = ModeloDuble()
        s, eventos, final = self.rodar(refinar=True, motor_revisao_fabrica=lambda: revisao)
        self.assertEqual(final, self.cfg.pasta_transcricoes / f"{NUMERO}.docx")
        self.assertEqual(revisao.chamadas[0]["beam_size"], 5)
        paragrafos, tabelas, _ = ler_docx(final)
        self.assertEqual(ficha(tabelas)["Forma da transcrição"],
                         "Revisão da gravação, depois da audiência")
        self.assertEqual(ficha(tabelas)["Modelo de transcrição"], "Whisper medium (português)")
        # rótulos marcados ao vivo foram levados para a revisão
        self.assertIn("Juiz(a) [00:00:00] — Bom dia a todos.", paragrafos)
        self.assertIn("Promotor(a) [00:00:04] — Sem perguntas, Excelência.", paragrafos)
        corpo = paragrafos[paragrafos.index("TRANSCRIÇÃO") + 1:]
        # a marca da pausa continua separando as falas da testemunha
        self.assertTrue(corpo[3].startswith("[00:00:11] — (Gravação pausada às"))
        self.assertTrue(corpo[4].startswith("Testemunha [00:00:1"))
        self.assertTrue(corpo[4].endswith("— Nada mais."))
        guardadas = list((self.cfg.pasta_transcricoes / "_audio").glob("* - ao vivo.docx"))
        self.assertEqual(len(guardadas), 1)
        self.assertEqual(ficha(ler_docx(guardadas[0])[1])["Forma da transcrição"],
                         "Simultânea (ao vivo, pelo microfone)")
        self.assertEqual(sorted(p.name for p in self.cfg.pasta_transcricoes.glob("*.docx")),
                         [final.name])

    def test_revisao_que_falha_mantem_a_versao_ao_vivo(self):
        def quebra():
            raise modelos.ModeloAusente("modelo medium ausente (simulado)")

        with self.assertLogs("transcricao.ao_vivo", "ERROR"):
            s, eventos, final = self.rodar(refinar=True, motor_revisao_fabrica=quebra)
        self.assertEqual(ficha(ler_docx(final)[1])["Forma da transcrição"],
                         "Simultânea (ao vivo, pelo microfone)")
        self.assertTrue(any("Ficou a versão ao vivo" in a for a in eventos.de("aviso")))


    # Achado 35: a troca da versão ao vivo pela revisada, sem proteção
    def _rodar_revisao(self):
        revisao = ModeloDuble()
        with mock.patch.object(documento, "ESPERAS_TRAVA_S", (0.0,)):
            return self.rodar(refinar=True, motor_revisao_fabrica=lambda: revisao)

    def _forma(self, caminho):
        return ficha(ler_docx(caminho)[1])["Forma da transcrição"]

    def test_revisada_recem_gravada_presa_pelo_antivirus(self):
        """os.replace(revisada, final) falhava com PermissionError (o
        antivírus segura o arquivo recém-gravado) DEPOIS do registro de fim:
        a audiência ficava sem documento em Transcricoes, sem recuperação."""
        original = os.replace

        def replace(origem, destino):
            if str(origem).endswith(" - revisão.docx"):
                raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
            return original(origem, destino)

        with mock.patch("os.replace", side_effect=replace):
            s, eventos, final = self._rodar_revisao()
        self.assertEqual(final, self.cfg.pasta_transcricoes / f"{NUMERO}.docx")
        self.assertEqual(self._forma(final), "Revisão da gravação, depois da audiência")
        self.assertEqual((s.estado, s._resultado), ("encerrada", final))
        audio = self.cfg.pasta_transcricoes / "_audio"
        self.assertEqual(len(list(audio.glob("* - ao vivo.docx"))), 1)
        self.assertEqual(list(audio.glob("* - revisão.docx")), [])
        self.assertEqual(eventos.de("fim"), [final])
        self.assertEqual(recuperaveis(self.cfg), [])

    def test_revisada_que_nao_entra_no_lugar_devolve_a_ao_vivo(self):
        with mock.patch.object(ao_vivo, "_copiar_com_espera",
                               side_effect=PermissionError(13, "Acesso negado")), \
                self.assertLogs("transcricao.ao_vivo", "WARNING"):
            s, eventos, final = self._rodar_revisao()
        self.assertEqual(final, self.cfg.pasta_transcricoes / f"{NUMERO}.docx")
        self.assertEqual(self._forma(final), "Simultânea (ao vivo, pelo microfone)")
        self.assertEqual(s.estado, "encerrada")
        (revisada,) = (self.cfg.pasta_transcricoes / "_audio").glob("* - revisão.docx")
        self.assertEqual(self._forma(revisada), "Revisão da gravação, depois da audiência")
        aviso = eventos.de("aviso")[-1]
        self.assertIn("ficou a versão ao vivo", aviso)
        self.assertIn(str(revisada), aviso)
        self.assertEqual(list((self.cfg.pasta_transcricoes / "_audio").glob("* - ao vivo.docx")),
                         [])

    def test_sem_conseguir_devolver_a_ao_vivo_aponta_para_ela(self):
        original = os.replace

        def replace(origem, destino):
            if str(origem).endswith(" - ao vivo.docx"):
                raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
            return original(origem, destino)

        with mock.patch.object(ao_vivo, "_copiar_com_espera",
                               side_effect=OSError(28, "Não há espaço no disco")), \
                mock.patch("os.replace", side_effect=replace), \
                self.assertLogs("transcricao.ao_vivo", "WARNING"):
            s, eventos, final = self._rodar_revisao()
        self.assertTrue(final.exists())
        self.assertTrue(final.name.endswith(" - ao vivo.docx"))
        self.assertEqual((s.estado, s._resultado), ("encerrada", final))
        self.assertIn(str(final), eventos.de("aviso")[-1])

    def test_versao_ao_vivo_aberta_no_word_grava_a_revisada_ao_lado(self):
        final_esperado = self.cfg.pasta_transcricoes / f"{NUMERO}.docx"
        original = os.replace

        def replace(origem, destino):
            if Path(origem) == final_esperado:
                raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
            return original(origem, destino)

        with mock.patch("os.replace", side_effect=replace):
            s, eventos, final = self._rodar_revisao()
        self.assertEqual(final.name, f"{NUMERO} (revisada).docx")
        self.assertEqual(self._forma(final), "Revisão da gravação, depois da audiência")
        self.assertEqual(self._forma(final_esperado), "Simultânea (ao vivo, pelo microfone)")
        self.assertIn("aberto em outro programa", eventos.de("aviso")[-1])
        self.assertEqual(list((self.cfg.pasta_transcricoes / "_audio").glob("* - revisão.docx")),
                         [])

    def test_erro_inesperado_na_revisao_nao_impede_o_encerramento(self):
        with mock.patch.object(SessaoAoVivo, "_trocar_pela_revisada",
                               side_effect=RuntimeError("inesperado")), \
                self.assertLogs("transcricao.ao_vivo", "ERROR"):
            s, eventos, final = self._rodar_revisao()
        self.assertTrue(final.exists())
        self.assertEqual((s.estado, s._resultado), ("encerrada", final))
        self.assertTrue(any("Ficou a versão ao vivo" in a for a in eventos.de("aviso")))
        self.assertEqual(eventos.de("fim"), [final])

    def test_ficha_da_revisao_sem_o_mapa_das_teclas(self):
        mapa = {"F1": "Juiz(a)", "F2": "Promotor(a)", "F6": "Testemunha", "F8": "Outro"}
        _, _, final = self._rodar_revisao_com(participantes=mapa)
        f = ficha(ler_docx(final)[1])
        self.assertEqual(f["Forma da transcrição"], "Revisão da gravação, depois da audiência")
        self.assertEqual(f["Participantes"], "Juiz(a)\nPromotor(a)\nTestemunha")

    def _rodar_revisao_com(self, **kw):
        revisao = ModeloDuble()
        return self.rodar(refinar=True, motor_revisao_fabrica=lambda: revisao, **kw)


class TestSemGuardarAudio(BaseSessao):
    ajustes = {"salvar_audio": "false"}

    def test_flac_apagado_no_fim(self):
        s, eventos, final = self.rodar()
        self.assertFalse(s.caminho_audio.exists())
        self.assertIn("não guardada", ficha(ler_docx(final)[1])["Gravação"])
        # tudo transcrito: a opção vale, sem aviso de gravação mantida
        self.assertFalse(any("Guardar a gravação" in a for a in eventos.de("aviso")))

    def test_trecho_perdido_mantem_a_gravacao_mesmo_desligada(self):
        """Achado 32: o aviso diz que o trecho que falhou "estará no áudio",
        mas o encerramento apagava o FLAC com a opção desligada - e a fala
        se perdia de vez. Fala não transcrita mantém a gravação."""
        self.modelo.falhar_em = 1
        with self.assertLogs("transcricao.ao_vivo", "ERROR"):
            s, eventos, final = self.rodar()
        self.assertTrue(s.caminho_audio.exists())
        f = ficha(ler_docx(final)[1])
        self.assertIn("1 trecho de fala não foi transcrito", f["Observação"])
        self.assertIn("consta da gravação", f["Observação"])
        self.assertEqual(f["Gravação"], f"_audio\\{s.caminho_audio.name}")
        aviso = eventos.de("aviso")[-1]
        self.assertIn("“Guardar a gravação da audiência”", aviso)
        self.assertIn("“Transcrever uma gravação”", aviso)
        self.assertIn(str(s.caminho_audio), aviso)

    def test_modelo_que_nao_carrega_mantem_a_gravacao(self):
        """O erro manda transcrever a gravação depois da audiência: ela não
        pode ser apagada no encerramento."""
        def sem_modelo():
            raise modelos.ErroDoModelo("faster-whisper quebrado (simulado)")

        with self.assertLogs("transcricao.ao_vivo", "ERROR"):
            s, eventos, final = self.rodar(motor=sem_modelo)
        self.assertIn("Transcrever uma gravação", eventos.de("erro")[0])
        self.assertTrue(s.caminho_audio.exists())
        import soundfile as sf

        self.assertAlmostEqual(sf.info(str(s.caminho_audio)).duration, 16.0, delta=0.01)
        f = ficha(ler_docx(final)[1])
        self.assertNotIn("não guardada", f["Gravação"])
        self.assertIn("4 trechos de fala não foram transcritos", f["Observação"])
        self.assertIn("consta da gravação", f["Observação"])
        self.assertTrue(any("4 trechos de fala não foram transcritos e só estão no áudio" in a
                            for a in eventos.de("aviso")))


class TestRecuperacao(BaseSessao):
    def escrever_diario(self, falas, fim=False) -> Path:
        pasta = self.cfg.pasta_transcricoes / "_audio"
        pasta.mkdir(parents=True, exist_ok=True)
        diario = pasta / f"{NUMERO} 2026-09-16 14h00.jsonl"
        linhas = [{"tipo": "inicio", "versao": 1, "docx": f"{NUMERO}.docx",
                   "audio": diario.with_suffix(".flac").name, "marcar_tempo": True,
                   "meta": {"numero": NUMERO, "tipo": "Conciliação",
                            "inicio": "2026-09-16T14:00:00", "data": "2026-09-16T14:00:00",
                            "modelo": "small", "origem": "ao vivo"}}]
        linhas += [{"inicio": a, "fim": b, "falante": c, "texto": d} for a, b, c, d in falas]
        texto = "\n".join(json.dumps(x, ensure_ascii=False) for x in linhas) + "\n"
        if fim:
            texto += json.dumps({"tipo": "fim", "fim": True}) + "\n"
        else:
            texto += '{"inicio": 9.0, "fim": 9.5, "falan'      # linha cortada pela queda
        diario.write_text(texto, encoding="utf-8")
        return diario

    def test_recuperar_diario_sem_fim(self):
        diario = self.escrever_diario([(1.0, 2.0, "Juiz(a)", "Aberta a audiência."),
                                       (3.0, 4.0, "Parte", "Aceito o acordo.")])
        self.escrever_diario_fechado_de_outra()
        self.assertEqual(recuperaveis(self.cfg), [diario])
        caminho = recuperar(diario)
        self.assertEqual(caminho, self.cfg.pasta_transcricoes / f"{NUMERO}.docx")
        paragrafos, tabelas, _ = ler_docx(caminho)
        self.assertIn("Juiz(a) [00:00:01] — Aberta a audiência.", paragrafos)
        self.assertIn("Parte [00:00:03] — Aceito o acordo.", paragrafos)
        f = ficha(tabelas)
        self.assertIn("recuperado depois de uma interrupção", f["Observação"])
        self.assertEqual(f["Tipo de audiência"], "Conciliação")
        self.assertEqual(recuperaveis(self.cfg), [])

    def escrever_diario_fechado_de_outra(self):
        pasta = self.cfg.pasta_transcricoes / "_audio"
        (pasta / "outra.jsonl").write_text(
            json.dumps({"tipo": "inicio", "meta": {"numero": NUMERO}}) + "\n"
            + json.dumps({"tipo": "fim", "fim": True}) + "\n", encoding="utf-8")
        (pasta / "estranho.jsonl").write_text("não é json\n", encoding="utf-8")

    def test_recuperar_nao_sobrescreve_documento_editado_depois(self):
        diario = self.escrever_diario([(1.0, 2.0, "Juiz(a)", "Texto.")])
        editado = self.cfg.pasta_transcricoes / f"{NUMERO}.docx"
        editado.write_bytes(b"editado pelo usuario")
        futuro = time.time() + 60
        os.utime(editado, (futuro, futuro))
        caminho = recuperar(diario)
        self.assertEqual(caminho.name, f"{NUMERO} (recuperada).docx")
        self.assertEqual(editado.read_bytes(), b"editado pelo usuario")

    def test_recuperar_rejeita_arquivo_estranho(self):
        estranho = self.tmp.raiz / "x.jsonl"
        estranho.write_text('{"a": 1}\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            recuperar(estranho)

    def test_queda_de_energia_de_verdade(self):
        """Um processo grava a audiência e morre sem encerrar (os._exit)."""
        script = textwrap.dedent(f"""
            import os, sys, time
            sys.path.insert(0, {str(caminhos.PACOTE.parent)!r})
            from pathlib import Path
            from helestron.nucleo.config import Config
            from helestron.transcricao import ao_vivo, microfone
            from testes import apoio_transcricao as A
            cfg = Config(Path({str(self.tmp.ini)!r}))
            modelo = A.ModeloDuble()
            fab = lambda b, n, a: microfone.CapturaDeArquivo(Path({str(self.wav)!r}), b, n,
                                                             tempo_real=False, ao_aviso=a)
            s = ao_vivo.SessaoAoVivo(A.NUMERO, cfg, lambda t, d: None, captura_fabrica=fab,
                                     motor_fabrica=lambda: modelo, falante="Juiz(a)")
            s.iniciar()
            s.captura.esperar(60)
            limite = time.time() + 60
            while len(s.falas) < 5 and time.time() < limite:
                time.sleep(0.05)
            print(len(s.falas), flush=True)
            os._exit(0)
        """)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                           timeout=120, cwd=str(caminhos.PACOTE.parent))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "5")
        (diario,) = recuperaveis(self.cfg)
        audio = diario.with_suffix(".flac")
        import soundfile as sf

        self.assertTrue(audio.exists())          # (com o cabeçalho incompleto da queda)
        caminho = recuperar(diario)
        self.assertEqual(caminho.name, f"{NUMERO}.docx")
        paragrafos, _, _ = ler_docx(caminho)
        corpo = paragrafos[paragrafos.index("TRANSCRIÇÃO") + 1:]
        # um falante só, sem pausas longas: as 5 falas viram um parágrafo
        self.assertEqual(len(corpo), 1)
        self.assertTrue(corpo[0].startswith("Juiz(a) [00:00:00] — Bom dia a todos."))
        self.assertTrue(corpo[0].endswith("Nada mais."))
        info = sf.info(str(audio))                # o FLAC foi consertado
        self.assertGreater(info.duration, 10.0)
        self.assertLessEqual(info.duration, 18.0)
        self.assertEqual(recuperaveis(self.cfg), [])

    def test_documento_final_que_nao_grava_cita_o_botao_da_tela(self):
        """O erro mandava procurar “Recuperar transcrição interrompida”, que não
        existe: o botão é “Recuperar”, na faixa “Uma transcrição foi
        interrompida” da tela Audiências. E a audiência fica entre as
        recuperáveis, que é o que faz essa faixa aparecer."""
        from unittest import mock

        s, eventos = self.sessao()
        s.iniciar()
        self.assertTrue(s.captura.esperar(30))
        with mock.patch.object(ao_vivo, "gerar_docx", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                s.encerrar()
        erro = eventos.de("erro")[-1]
        self.assertIn("disco cheio", erro)
        self.assertIn("“Recuperar”, na faixa “Uma transcrição foi interrompida” da tela "
                      "Audiências", erro)
        self.assertNotIn("Recuperar transcrição interrompida", erro)
        tela = (Path(ao_vivo.__file__).resolve().parents[1] / "web" / "js"
                / "secao-audiencias.js").read_text(encoding="utf-8")
        self.assertIn(f'rotulo: "{ao_vivo.BOTAO_RECUPERAR}"', tela)
        self.assertIn(f'"{ao_vivo.FAIXA_INTERROMPIDA}"', tela)
        self.assertIn(s.caminho_diario, recuperaveis(self.cfg))


if __name__ == "__main__":
    unittest.main()
