"""Regressões achadas na revisão do módulo de transcrição.

Cada teste prende um defeito concreto que existia: fala sem rótulo em
itálico, ficha incompleta quando a tela passa só o tipo, número do processo
dependente e da pasta das mídias, memória do reamostrador, trava geral
durante o download de outro modelo, diário compartilhado entre sessões,
recuperação que criava "(recuperada)" à toa, download de falantes preso no
HTTP 416 e o Windows trancando o arquivo por um instante.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import types
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock

import numpy as np

from app.nucleo import sistema
from app.transcricao import ao_vivo, arquivo, documento, falantes, modelos
from app.transcricao.ao_vivo import SessaoAoVivo, recuperar, recuperaveis
from app.transcricao.arquivo import decodificar, numero_do_caminho, transcrever_arquivo
from app.transcricao.documento import Fala, MetaAudiencia, gerar_docx
from app.transcricao.microfone import Reamostrador
from testes.apoio_transcricao import (NUMERO, ModeloDuble, PastaTemporaria, ficha,
                                     gravar_wav, ler_docx, montar)


def _italicos(caminho: Path) -> dict[str, bool]:
    """Texto de cada parágrafo do corpo -> o trecho falado está em itálico?"""
    from docx import Document

    doc = Document(str(caminho))
    saida = {}
    for p in doc.paragraphs:
        if p.runs and " — " in p.text:
            saida[p.text] = bool(p.runs[-1].italic)
    return saida


# ================================================================ documento
class TestDocumento(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.destino = self.tmp.raiz / f"{NUMERO}.docx"

    def tearDown(self):
        self.tmp.apagar()

    def test_fala_sem_rotulo_nao_sai_em_italico_so_a_marca(self):
        falas = [Fala(1.0, 3.0, "", "Fala sem separação de vozes."),
                 Fala(5.0, 5.0, "", "(Gravação pausada às 10:00:00 e retomada às 10:05:00.)")]
        italico = _italicos(gerar_docx(self.destino, falas, MetaAudiencia(numero=NUMERO)))
        self.assertFalse(italico["[00:00:01] — Fala sem separação de vozes."])
        self.assertTrue(italico["[00:00:05] — (Gravação pausada às 10:00:00 e retomada às 10:05:00.)"])
        self.assertTrue(documento.e_marca(falas[1]))
        self.assertFalse(documento.e_marca(falas[0]))

    def test_trava_passageira_do_windows_nao_vira_copia(self):
        original = sistema.gravar_atomico
        falhas = []

        def trava_uma_vez(destino, dados):
            if not falhas:
                falhas.append(destino)
                Path(str(destino) + ".parcial").write_bytes(b"x")
                raise PermissionError(32, "O arquivo já está sendo usado por outro processo")
            return original(destino, dados)

        with mock.patch.object(documento.sistema, "gravar_atomico", side_effect=trava_uma_vez), \
                mock.patch.object(documento, "ESPERAS_TRAVA_S", (0.0, 0.0)):
            caminho = gerar_docx(self.destino, [Fala(0, 1, "Juiz(a)", "Oi.")],
                                 MetaAudiencia(numero=NUMERO))
        self.assertEqual(caminho, self.destino)
        self.assertEqual(len(falhas), 1)
        self.assertFalse(list(self.tmp.raiz.glob("*cópia*")))
        self.assertFalse(list(self.tmp.raiz.glob("*.parcial")))


# ================================================================== arquivo
class TestArquivo(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.cfg = self.tmp.config()
        self.audio = montar([("silencio", 0.5), ("fala", 2.0, 200), ("silencio", 1.0)])
        self.modelo = ModeloDuble()

    def tearDown(self):
        self.tmp.apagar()

    def test_numero_do_dependente_e_da_pasta_das_midias(self):
        n = numero_do_caminho(Path(f"{NUMERO}-01 2026-09-16 14h00.flac"))
        self.assertEqual((n.principal, n.dependente), (NUMERO, "01"))
        n = numero_do_caminho(Path(f"{NUMERO}-inc0003.mp4"))
        self.assertEqual(n.dependente, "03")
        # data emendada com hífen não é dependente
        self.assertEqual(numero_do_caminho(Path(f"{NUMERO}-2026-09-16.wav")).dependente, "")
        self.assertEqual(numero_do_caminho(Path(f"{NUMERO} 2026-09-16 14h00.flac")).dependente, "")
        self.assertIsNone(numero_do_caminho(Path("Lote 1") / "gravacao.wav"))
        # a gravação baixada dos autos: o número está na pasta, não no arquivo
        pasta = self.tmp.raiz / "Lote" / "_controle" / "midias" / f"{NUMERO}-02"
        pasta.mkdir(parents=True)
        wav = gravar_wav(pasta / "Midia da audiencia.wav", self.audio)
        self.assertEqual(numero_do_caminho(wav).formatado, f"{NUMERO}/02")
        caminho = transcrever_arquivo(wav, None, self.cfg, motor_fabrica=lambda: self.modelo)
        self.assertEqual(caminho.name, f"{NUMERO}-02.docx")
        self.assertEqual(ficha(ler_docx(caminho)[1])["Processo nº"], f"{NUMERO}/02")

    def test_ficha_so_com_o_tipo_e_completada(self):
        # é o que a tela passa (servicos.transcrever_gravacao): numero e tipo
        wav = gravar_wav(self.tmp.raiz / f"{NUMERO}.wav", self.audio)
        meta = MetaAudiencia(numero=NUMERO, tipo="Instrução")
        f = ficha(ler_docx(transcrever_arquivo(wav, None, self.cfg, meta=meta,
                                               motor_fabrica=lambda: self.modelo))[1])
        self.assertEqual(f["Tipo de audiência"], "Instrução")
        self.assertEqual(f["Forma da transcrição"], "A partir de arquivo de gravação")
        self.assertEqual(f["Unidade"], "1ª Vara Cível, Maceió, TJAL")
        self.assertEqual(f["Magistrado(a)"], "Fulana de Tal (Juíza de Direito)")
        self.assertNotEqual(f["Data"], "—")
        # com os rótulos da audiência ao vivo, é revisão
        meta = MetaAudiencia(numero=NUMERO, tipo="Instrução")
        manuais = [Fala(0.5, 2.5, "Juiz(a)", "x")]
        f = ficha(ler_docx(transcrever_arquivo(wav, None, self.cfg, meta=meta,
                                               rotulos_manuais=manuais,
                                               motor_fabrica=lambda: self.modelo))[1])
        self.assertEqual(f["Forma da transcrição"], "Revisão da gravação, depois da audiência")

    def test_gravacao_sem_separacao_nao_sai_em_italico(self):
        wav = gravar_wav(self.tmp.raiz / f"{NUMERO}.wav", self.audio)
        caminho = transcrever_arquivo(wav, None, self.cfg, separar=False,
                                      motor_fabrica=lambda: self.modelo)
        self.assertEqual(_italicos(caminho), {"[00:00:00] — Bom dia a todos.": False})

    def test_progresso_nao_volta_quando_o_modelo_precisa_baixar(self):
        wav = gravar_wav(self.tmp.raiz / f"{NUMERO}.wav", self.audio)
        visto = []

        def carregar(nome, threads=0, progresso=None, **kw):
            for f in (0.0, 0.5, 1.0):
                progresso(f, "Baixando o modelo")
            return self.modelo

        with mock.patch.object(arquivo.modelos, "carregar", side_effect=carregar):
            transcrever_arquivo(wav, None, self.cfg, progresso=lambda f, t: visto.append(f))
        self.assertEqual(visto, sorted(visto))

    def test_wav_longo_em_44khz_estereo_e_lido_em_blocos(self):
        t = np.arange(44100 * 70) / 44100        # 70 s: mais de um bloco de leitura
        tom = 0.3 * np.sin(2 * np.pi * 440 * t)
        estereo = np.stack([tom, tom], axis=1).astype(np.float32)
        wav = gravar_wav(self.tmp.raiz / "longo.wav", estereo, 44100)
        audio = decodificar(wav)
        self.assertEqual(audio.size, 16000 * 70)
        ref = 0.3 * np.sin(2 * np.pi * 440 * np.arange(audio.size) / 16000)
        self.assertLess(float(np.max(np.abs(audio[1000:-1000] - ref[1000:-1000]))), 1e-3)


class TestReamostradorEmLotes(unittest.TestCase):
    def test_lotes_pequenos_dao_o_mesmo_resultado(self):
        x = np.random.default_rng(1).normal(0, 0.1, 44100 * 2).astype(np.float32)
        inteiro = Reamostrador(44100).tudo(x)
        with mock.patch.object(Reamostrador, "LOTE", 1000):
            em_lotes = Reamostrador(44100).tudo(x)
        np.testing.assert_allclose(em_lotes, inteiro, atol=1e-7)

    def test_matriz_de_indices_limitada(self):
        # Antes: uma matriz (amostras de saída x ~50) de uma vez - 2 min de
        # WAV a 44,1 kHz pediam 1,5 GB. Agora, no máximo LOTE linhas.
        tamanhos = []
        original = np.einsum

        def medir(expr, a, b):
            tamanhos.append(a.shape[0])
            return original(expr, a, b)

        with mock.patch.object(np, "einsum", side_effect=medir):
            Reamostrador(48000).processar(np.zeros(48000 * 10, dtype=np.float32))
        self.assertTrue(tamanhos)
        self.assertLessEqual(max(tamanhos), Reamostrador.LOTE)


# ================================================================== modelos
def _instalar_falso(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "model.bin").write_bytes(b"\0" * 1_100_000)
    (pasta / "config.json").write_text("{}", encoding="utf-8")
    (pasta / "tokenizer.json").write_text("{}", encoding="utf-8")


class TestModelosConcorrencia(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.patch = mock.patch.object(modelos, "PASTA", self.tmp.raiz / "modelos")
        self.patch.start()
        modelos.descarregar()
        self.liberar = threading.Event()
        self.chamadas = []

        def snapshot_download(repo, **kw):
            self.chamadas.append(repo)
            self.liberar.wait(20)
            _instalar_falso(Path(kw["local_dir"]))
            return kw["local_dir"]

        class WhisperFalso:
            def __init__(self, caminho, **kw):
                self.caminho = caminho

        hub = types.ModuleType("huggingface_hub")
        hub.snapshot_download = snapshot_download
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = WhisperFalso
        self.modulos = mock.patch.dict(sys.modules, {"huggingface_hub": hub, "faster_whisper": fw})
        self.modulos.start()
        self.ambiente = mock.patch.dict(os.environ)   # preparar_rede() mexe no ambiente
        self.ambiente.start()

    def tearDown(self):
        self.liberar.set()
        self.ambiente.stop()
        self.modulos.stop()
        modelos.descarregar()
        self.patch.stop()
        self.tmp.apagar()

    def test_modelo_instalado_nao_espera_o_download_de_outro(self):
        _instalar_falso(modelos.pasta_do_modelo("small"))
        fundo = threading.Thread(target=modelos.carregar, args=("medium",), daemon=True)
        fundo.start()
        limite = time.time() + 5
        while not self.chamadas and time.time() < limite:
            time.sleep(0.01)
        self.assertEqual(self.chamadas, ["Systran/faster-whisper-medium"])
        inicio = time.monotonic()
        pronto = modelos.carregar("small")             # o ao vivo, durante o download
        self.assertLess(time.monotonic() - inicio, 2.0)
        self.assertTrue(pronto.caminho.endswith("whisper-small"))
        self.liberar.set()
        fundo.join(10)
        self.assertFalse(fundo.is_alive())

    def test_mesmo_modelo_pedido_duas_vezes_baixa_uma(self):
        avisos = []
        a = threading.Thread(target=modelos.baixar, args=("base",), daemon=True)
        a.start()
        limite = time.time() + 5
        while not self.chamadas and time.time() < limite:
            time.sleep(0.01)
        b = threading.Thread(target=modelos.baixar,
                             args=("base", lambda f, t: avisos.append(t)), daemon=True)
        b.start()
        time.sleep(0.2)
        self.liberar.set()
        a.join(10)
        b.join(10)
        self.assertEqual(self.chamadas, ["Systran/faster-whisper-base"])
        self.assertTrue(any("já em andamento" in t for t in avisos))
        self.assertTrue(modelos.instalado("base"))


class TestCaminhoNativo(unittest.TestCase):
    """Pasta com acento no Windows: CTranslate2 e sherpa-onnx abrem o arquivo
    com o caminho em bytes ANSI e não acham o modelo."""

    def test_fora_do_windows_ou_ascii_nao_muda(self):
        self.assertEqual(modelos.caminho_nativo(Path("/opt/modelos/whisper-small")),
                         str(Path("/opt/modelos/whisper-small")))
        with mock.patch.object(modelos, "NO_WINDOWS", True), \
                mock.patch.object(modelos, "_nome_curto_windows") as curto:
            self.assertEqual(modelos.caminho_nativo(r"C:\AssessorIntegrado\runtime"),
                             r"C:\AssessorIntegrado\runtime")
        curto.assert_not_called()

    def test_pasta_com_acento_usa_o_nome_curto(self):
        longo = r"C:\Users\joão\Downloads\AssessorIntegrado\runtime\modelos\whisper-small"
        with mock.patch.object(modelos, "NO_WINDOWS", True), \
                mock.patch.object(modelos, "_nome_curto_windows",
                                  return_value=r"C:\Users\JOO~1\DOWNLO~1\ASSESS~1\runtime\modelos\WHISPE~1"):
            self.assertEqual(modelos.caminho_nativo(longo),
                             r"C:\Users\JOO~1\DOWNLO~1\ASSESS~1\runtime\modelos\WHISPE~1")
        # sem nome curto (8.3 desligado no disco): avisa e tenta o original
        with mock.patch.object(modelos, "NO_WINDOWS", True), \
                mock.patch.object(modelos, "_nome_curto_windows", return_value=None), \
                self.assertLogs("transcricao.modelos", "WARNING"):
            self.assertEqual(modelos.caminho_nativo(longo), longo)

    def test_carregar_entrega_o_nome_curto_ao_ctranslate2(self):
        tmp = PastaTemporaria()
        criados = []

        class WhisperFalso:
            def __init__(self, caminho, **kw):
                criados.append(caminho)

        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = WhisperFalso
        try:
            with mock.patch.object(modelos, "PASTA", tmp.raiz / "modelos"), \
                    mock.patch.dict(sys.modules, {"faster_whisper": fw}), \
                    mock.patch.dict(os.environ), \
                    mock.patch.object(modelos, "NO_WINDOWS", True), \
                    mock.patch.object(modelos, "_nome_curto_windows", return_value="C:\\CURTO~1"):
                modelos.descarregar()
                pasta = modelos.pasta_do_modelo("small")
                _instalar_falso(pasta)
                with mock.patch.object(modelos, "pasta_do_modelo",
                                       return_value=Path(str(pasta) + "-joão")):
                    _instalar_falso(Path(str(pasta) + "-joão"))
                    modelos.carregar("small")
        finally:
            modelos.descarregar()
            tmp.apagar()
        self.assertEqual(criados, ["C:\\CURTO~1"])


# ================================================================== ao vivo
class _CapturaParada:
    """Fonte de áudio que não entrega nada (os testes chamam os métodos)."""

    tempo_real = True

    def __init__(self, *a):
        pass

    def iniciar(self):
        pass

    def parar(self):
        pass


class TestAoVivo(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria(salvar_audio="false")
        self.cfg = self.tmp.config()

    def tearDown(self):
        self.tmp.apagar()

    def sessao(self):
        return SessaoAoVivo(NUMERO, self.cfg, lambda t, d: None,
                            captura_fabrica=lambda *a: _CapturaParada(),
                            motor_fabrica=lambda: ModeloDuble(), falante="Juiz(a)")

    def test_nome_livre_tambem_para_o_diario(self):
        pasta = self.tmp.raiz / "_audio"
        pasta.mkdir()
        base = f"{NUMERO} 2026-09-16 14h00"
        (pasta / f"{base}.jsonl").write_text("{}\n", encoding="utf-8")   # FLAC já apagado
        self.assertEqual(ao_vivo._audio_livre(pasta, base).name, f"{base} (2).flac")
        (pasta / f"{base} (2).flac").write_bytes(b"")
        self.assertEqual(ao_vivo._audio_livre(pasta, base).name, f"{base} (3).flac")

    def test_duas_sessoes_seguidas_sem_guardar_audio_tem_diarios_proprios(self):
        fixo = datetime(2026, 9, 16, 14, 0, 5)

        class Relogio(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixo

        diarios = []
        with mock.patch.object(ao_vivo, "datetime", Relogio):
            for _ in range(2):
                s = self.sessao()
                s.iniciar()
                s.encerrar()
                diarios.append(s.caminho_diario)
                self.assertFalse(s.caminho_audio.exists())   # salvar_audio = false
        self.assertNotEqual(diarios[0], diarios[1])
        for diario in diarios:
            linhas = [json.loads(x) for x in diario.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([x.get("tipo") for x in linhas].count("inicio"), 1)

    def test_salvamento_depois_de_ruido_nao_gera_recuperada(self):
        s = self.sessao()
        s.iniciar()
        try:
            s._flac.write(np.full(16000, 1e-3, dtype=np.float32))   # 1 s gravado
            s._registrar(Fala(1.0, 2.0, "Juiz(a)", "Aberta a audiência."))
            antigo = time.time() - 60          # a última fala foi há um minuto...
            os.utime(s.caminho_diario, (antigo, antigo))
            s._salvar_parcial()                # ...e o salvamento automático, agora
            # "queda de energia": o diário fica sem o registro de fim
            s._diario.close()
            s._diario = None
            with ao_vivo._trava_ativos:
                ao_vivo._ativos.discard(ao_vivo._chave(s.caminho_diario))
            # o processo morto solta a trava (o arquivo dela fica)
            ao_vivo._soltar(s._trava_processo)
            s._trava_processo = None
        finally:
            s._fila.put(None)
            s._trabalhador.join(10)
            s._fechar_audio()
        self.assertEqual(recuperaveis(self.cfg), [s.caminho_diario])
        registros = [json.loads(x) for x in s.caminho_diario.read_text(encoding="utf-8").splitlines()]
        self.assertIn("salvo", [r.get("tipo") for r in registros])
        caminho = recuperar(s.caminho_diario)
        self.assertEqual(caminho, s.caminho_docx)       # não "(recuperada)"
        paragrafos, _, _ = ler_docx(caminho)
        self.assertIn("Juiz(a) [00:00:01] — Aberta a audiência.", paragrafos)
        self.assertEqual(len([p for p in paragrafos if " — " in p]), 1)

    def test_retomar_depois_de_encerrar_nao_volta_a_gravar(self):
        s = self.sessao()
        s.iniciar()
        s.pausar()
        s.encerrar()
        s.retomar()
        self.assertEqual(s.estado, "encerrada")


# ================================================================= falantes
class _Resposta(io.BytesIO):
    status = 200

    def __init__(self, dados: bytes):
        super().__init__(dados)
        self.headers = {"Content-Length": str(len(dados))}


class TestFalantesDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()

    def tearDown(self):
        self.tmp.apagar()

    def test_part_completo_com_416_e_aproveitado(self):
        import hashlib

        dados = b"modelo" * 1000
        destino = self.tmp.raiz / "modelo.onnx"
        destino.with_name("modelo.onnx.part").write_bytes(dados)   # caiu antes de renomear
        pedidos = []

        def abrir(url, inicio):
            pedidos.append(inicio)
            if inicio:
                raise urllib.error.HTTPError(url, 416, "Range Not Satisfiable", {}, None)
            return _Resposta(dados)

        with mock.patch.object(falantes, "_abrir_url", side_effect=abrir), \
                mock.patch.object(falantes.time, "sleep"):
            falantes._baixar("https://exemplo/modelo.onnx", destino,
                             hashlib.sha256(dados).hexdigest(), tentativas=2)
        self.assertEqual(destino.read_bytes(), dados)
        self.assertEqual(pedidos, [len(dados)])
        self.assertFalse(destino.with_name("modelo.onnx.part").exists())

    def test_part_estragado_com_416_recomeca_do_zero(self):
        import hashlib

        dados = b"modelo" * 1000
        destino = self.tmp.raiz / "modelo.onnx"
        destino.with_name("modelo.onnx.part").write_bytes(b"lixo" * 2000)
        pedidos = []

        def abrir(url, inicio):
            pedidos.append(inicio)
            if inicio:
                raise urllib.error.HTTPError(url, 416, "Range Not Satisfiable", {}, None)
            return _Resposta(dados)

        with mock.patch.object(falantes, "_abrir_url", side_effect=abrir), \
                mock.patch.object(falantes.time, "sleep"):
            falantes._baixar("https://exemplo/modelo.onnx", destino,
                             hashlib.sha256(dados).hexdigest(), tentativas=2)
        self.assertEqual(destino.read_bytes(), dados)
        self.assertEqual(pedidos, [8000, 0])


if __name__ == "__main__":
    unittest.main()
