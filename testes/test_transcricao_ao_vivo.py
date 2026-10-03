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

import numpy as np

from helestron.nucleo import caminhos
from helestron.transcricao import ao_vivo, microfone, modelos
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
        self.assertEqual(f["Participantes"], "Testemunha: Beltrano")
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


class TestSemGuardarAudio(BaseSessao):
    ajustes = {"salvar_audio": "false"}

    def test_flac_apagado_no_fim(self):
        s, _, final = self.rodar()
        self.assertFalse(s.caminho_audio.exists())
        self.assertIn("não guardada", ficha(ler_docx(final)[1])["Gravação"])

    def test_trecho_perdido_sem_gravacao_nao_remete_a_ela(self):
        # Sem o áudio guardado, o documento não pode dizer que o trecho
        # "consta da gravação".
        self.modelo.falhar_em = 1
        with self.assertLogs("transcricao.ao_vivo", "ERROR"):
            _, _, final = self.rodar()
        obs = ficha(ler_docx(final)[1])["Observação"]
        self.assertIn("1 trecho de fala não foi transcrito", obs)
        self.assertNotIn("gravação", obs)


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
            sys.path.insert(0, {str(caminhos.RAIZ)!r})
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
                           timeout=120, cwd=str(caminhos.RAIZ))
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


if __name__ == "__main__":
    unittest.main()
