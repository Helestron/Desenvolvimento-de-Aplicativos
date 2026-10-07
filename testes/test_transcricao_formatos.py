"""Os formatos de áudio e vídeo da transcrição de gravações.

* A lista ÚNICA dos formatos que o Windows reproduz: a de
  transcricao/arquivo.py (EXTENSOES, a do filtro do diálogo) é a mesma da
  página (secao-audiencias.js, EXTENSOES_MIDIA, a do 'accept' do navegador),
  item a item, e o limite do envio da página é o da rota no servidor.
* A decodificação de ponta a ponta, com arquivos de vídeo e de áudio gerados
  aqui mesmo pelo PyAV (MP4 com AAC, MKV com Opus, WebM com Vorbis, MOV,
  AVI, MPEG-TS, WMV/WMA, M4A, MP3, OGG, FLAC, AC3, WAV): o áudio volta mono,
  16 kHz, com a duração e o tom certos.
* As frases quando não dá: vídeo sem trilha de áudio, arquivo cortado ou que
  não é mídia, áudio protegido contra cópia (DRM) - e nenhuma recusa pela
  extensão.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

import numpy as np

from helestron.transcricao import arquivo
from helestron.transcricao.arquivo import (ArquivoDanificado, AudioIlegivel, ProtegidoPorDrm,
                                           SemTrilhaDeAudio, decodificar)

RAIZ = Path(__file__).resolve().parents[1]
JS = RAIZ / "helestron" / "web" / "js" / "secao-audiencias.js"
TAXA = 16000
TOM_HZ = 440
SEGUNDOS = 2.0

# O mínimo que o usuário pediu (áudio e vídeo que o Windows reproduz).
MINIMO = (".mp3 .wav .wma .aac .m4a .m4b .flac .ogg .oga .opus .aif .aiff .aifc .amr .awb "
          ".ac3 .ec3 .mka .weba .caf .au .snd .mp2 .mpa .3ga .mp4 .m4v .mov .qt .avi .wmv "
          ".asf .mkv .webm .mpg .mpeg .mpe .m2v .ts .m2ts .mts .3gp .3g2 .flv .f4v .vob "
          ".ogv .dvr-ms .wtv .divx .mxf").split()


def _lista_do_js() -> list[str]:
    texto = JS.read_text(encoding="utf-8")
    bloco = re.search(r"const EXTENSOES_MIDIA = \[(.*?)\];", texto, re.S).group(1)
    bloco = re.sub(r"//[^\n]*", "", bloco)
    return re.findall(r'"(\.[\w-]+)"', bloco)


class TestListaUnica(unittest.TestCase):
    def test_a_lista_da_pagina_e_a_do_programa(self):
        self.assertEqual(_lista_do_js(), list(arquivo.EXTENSOES))

    def test_tem_o_minimo_pedido_sem_repetir(self):
        self.assertEqual(sorted(set(MINIMO) - set(arquivo.EXTENSOES)), [])
        self.assertEqual(len(arquivo.EXTENSOES), len(set(arquivo.EXTENSOES)))
        for ext in arquivo.EXTENSOES:
            with self.subTest(ext=ext):
                self.assertRegex(ext, r"^\.[a-z0-9-]+$")

    def test_filtro_do_dialogo_e_accept_do_navegador(self):
        texto = JS.read_text(encoding="utf-8")
        # 'accept': audio/* e video/* e a lista inteira
        self.assertIn('const ACEITAR_GRAVACAO = ["audio/*", "video/*"].concat(EXTENSOES_MIDIA).join(",");',
                      texto)
        self.assertIn('"Áudio e vídeo|" + EXTENSOES_MIDIA.map((e) => "*" + e).join(";")', texto)
        filtro = arquivo.FILTRO_ARQUIVOS[0][1].split()
        self.assertEqual(filtro, [f"*{e}" for e in arquivo.EXTENSOES])
        self.assertEqual(arquivo.FILTRO_ARQUIVOS[-1], ("Todos os arquivos", "*.*"))

    def test_filtro_passa_pela_pywebview(self):
        """A pywebview só aceita '*.ext' com letras e números: o que ela não
        aceita (o ".dvr-ms") sai do filtro sem derrubar o diálogo - e entra
        por "Todos os arquivos"."""
        from helestron.servidor.api_geral import tipos_pywebview

        tipos = ["Áudio e vídeo|" + ";".join(f"*{e}" for e in arquivo.EXTENSOES),
                 "Todos os arquivos|*.*"]
        saida = tipos_pywebview(tipos)
        self.assertEqual(len(saida), 2)
        self.assertTrue(saida[0].startswith("Áudio e vídeo (*.mp3;*.wav;"))
        self.assertIn("*.wmv", saida[0])
        self.assertNotIn("dvr-ms", saida[0])
        self.assertTrue(re.fullmatch(r"[\w ]+ \((\*\.\w+)(;\*\.\w+)*\)", saida[0]))

    def test_limite_do_envio_da_pagina_e_o_da_rota(self):
        from helestron.servidor.api_audiencias import LIMITE_ENVIO_GRAVACAO

        texto = JS.read_text(encoding="utf-8")
        expressao = re.search(r"const LIMITE_ENVIO_GRAVACAO = ([\d\s*]+);", texto).group(1)
        produto = 1
        for fator in expressao.split("*"):
            produto *= int(fator)
        self.assertEqual(produto, LIMITE_ENVIO_GRAVACAO)


# ------------------------------------------------------------ geração
def _encoder(nome: str) -> bool:
    import av

    try:
        av.codec.Codec(nome, "w")
        return True
    except Exception:
        return False


def gerar(caminho: Path, formato: str, codec_audio: str | None, video: str | None = None,
          taxa: int = 48000, layout: str = "stereo", segundos: float = SEGUNDOS) -> Path:
    """Um arquivo de verdade: o tom de 440 Hz na trilha de áudio e, se pedido,
    um vídeo pequeno (64x48, 25 qps) na de vídeo."""
    import av

    saida = av.open(str(caminho), "w", format=formato)
    fluxo_audio = None
    if codec_audio:
        fluxo_audio = saida.add_stream(codec_audio, rate=taxa, layout=layout)
        if codec_audio in ("wmav1", "wmav2"):
            fluxo_audio.bit_rate = 128000
        if codec_audio in ("vorbis", "opus"):        # os codificadores nativos ditos experimentais
            fluxo_audio.codec_context.options = {"strict": "-2"}
    fluxo_video = None
    if video:
        fluxo_video = saida.add_stream(video, rate=25)
        fluxo_video.width, fluxo_video.height = 64, 48
        fluxo_video.pix_fmt = "yuv420p"
    if fluxo_audio is not None:
        cc = fluxo_audio.codec_context
        formato_amostra = cc.format.name if cc.format else "fltp"
        canais = 2 if layout == "stereo" else 1
        n = int(segundos * taxa)
        sinal = (0.3 * np.sin(2 * np.pi * TOM_HZ * np.arange(n) / taxa)).astype(np.float32)
        passo = 1024
        for ini in range(0, n, passo):
            bloco = sinal[ini:ini + passo]
            if formato_amostra.endswith("p"):
                dados = np.tile(bloco, (canais, 1))
            else:
                dados = np.repeat(bloco[None, :], canais, axis=0).T.reshape(1, -1)
            if formato_amostra.startswith("s16"):
                dados = (dados * 32767).astype(np.int16)
            elif formato_amostra.startswith("s32"):
                dados = (dados * (2 ** 31 - 1)).astype(np.int32)
            else:
                dados = dados.astype(np.float32)
            quadro = av.AudioFrame.from_ndarray(np.ascontiguousarray(dados), format=formato_amostra,
                                                layout=layout)
            quadro.sample_rate = taxa
            quadro.pts = ini
            for pacote in fluxo_audio.encode(quadro):
                saida.mux(pacote)
        for pacote in fluxo_audio.encode(None):
            saida.mux(pacote)
    if fluxo_video is not None:
        for i in range(int(segundos * 25)):
            imagem = np.full((48, 64, 3), (i * 7) % 255, dtype=np.uint8)
            quadro = av.VideoFrame.from_ndarray(imagem, format="rgb24")
            quadro.pts = i
            for pacote in fluxo_video.encode(quadro):
                saida.mux(pacote)
        for pacote in fluxo_video.encode(None):
            saida.mux(pacote)
    saida.close()
    return caminho


def frequencia_dominante(audio: np.ndarray, taxa: int = TAXA) -> float:
    meio = audio[len(audio) // 4: 3 * len(audio) // 4]
    espectro = np.abs(np.fft.rfft(meio * np.hanning(meio.size)))
    return float(np.fft.rfftfreq(meio.size, 1 / taxa)[int(np.argmax(espectro))])


class _ComPyAV(unittest.TestCase):
    def setUp(self):
        try:
            import av  # noqa: F401
        except ImportError:
            self.skipTest("PyAV não instalado")
        self.pasta = Path(tempfile.mkdtemp(prefix="helestron-formatos-"))
        self.addCleanup(shutil.rmtree, self.pasta, True)


class TestDecodificacaoDePontaAPonta(_ComPyAV):
    # (nome, formato do PyAV, codificadores de áudio aceitos, codificadores de vídeo aceitos)
    CASOS = [
        ("audiencia.mp4", "mp4", ("aac",), ("mpeg4", "libx264", "h264")),
        ("audiencia.m4v", "mp4", ("aac",), ("mpeg4",)),
        ("audiencia.mov", "mov", ("aac",), ("mpeg4", "mjpeg")),
        ("audiencia.mkv", "matroska", ("libopus", "opus"), ("mpeg4", "libx264")),
        ("audiencia.webm", "webm", ("libvorbis", "vorbis"), ("libvpx", "vp8")),
        ("audiencia-opus.webm", "webm", ("libopus", "opus"), ("libvpx", "vp8")),
        ("audiencia.avi", "avi", ("mp2", "libmp3lame"), ("mpeg4", "mjpeg")),
        ("audiencia.ts", "mpegts", ("mp2", "aac"), ("mpeg2video", "mpeg4")),
        ("audiencia.wmv", "asf", ("wmav2",), ("wmv2", "msmpeg4v2")),
        ("audiencia.wma", "asf", ("wmav2",), None),
        ("audiencia.m4a", "ipod", ("aac",), None),
        ("audiencia.mp3", "mp3", ("libmp3lame", "mp3"), None),
        ("audiencia.ogg", "ogg", ("libopus", "opus", "libvorbis", "vorbis"), None),
        ("audiencia.opus", "opus", ("libopus", "opus"), None),
        ("audiencia.flac", "flac", ("flac",), None),
        ("audiencia.ac3", "ac3", ("ac3",), None),
        ("audiencia.wav", "wav", ("pcm_s16le",), None),
        ("audiencia.mka", "matroska", ("flac", "aac"), None),
    ]

    def test_audio_e_video_gerados_aqui_voltam_como_audio(self):
        for nome, formato, audios, videos in self.CASOS:
            with self.subTest(arquivo=nome):
                codec_audio = next((c for c in audios if _encoder(c)), None)
                codec_video = next((c for c in videos if _encoder(c)), None) if videos else None
                if codec_audio is None or (videos and codec_video is None):
                    self.skipTest(f"este PyAV não codifica {audios} / {videos}")
                caminho = gerar(self.pasta / nome, formato, codec_audio, codec_video)
                audio = decodificar(caminho)
                self.assertEqual(audio.dtype, np.float32)
                self.assertEqual(audio.ndim, 1)                       # mono
                self.assertAlmostEqual(audio.size / TAXA, SEGUNDOS, delta=0.15)
                self.assertAlmostEqual(frequencia_dominante(audio), TOM_HZ, delta=10)
                self.assertGreater(float(np.max(np.abs(audio))), 0.15)
                self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    def test_extensao_trocada_nao_importa(self):
        """Quem decide é o conteúdo: um MP4 com nome de .dat (ou sem extensão) é lido."""
        mp4 = gerar(self.pasta / "a.mp4", "mp4", "aac", "mpeg4")
        for nome in ("gravação da sala.dat", "sem_extensao"):
            with self.subTest(nome=nome):
                copia = self.pasta / nome
                shutil.copy(mp4, copia)
                self.assertAlmostEqual(decodificar(copia).size / TAXA, SEGUNDOS, delta=0.15)

    def test_mono_8_khz_e_estereo_44_khz(self):
        if not _encoder("aac"):
            self.skipTest("sem AAC")
        for taxa, layout in ((8000, "mono"), (44100, "stereo")):
            with self.subTest(taxa=taxa, layout=layout):
                caminho = gerar(self.pasta / f"t{taxa}.m4a", "ipod", "aac", taxa=taxa, layout=layout)
                audio = decodificar(caminho)
                self.assertAlmostEqual(audio.size / TAXA, SEGUNDOS, delta=0.15)
                self.assertAlmostEqual(frequencia_dominante(audio), TOM_HZ, delta=10)


class TestQuandoNaoDa(_ComPyAV):
    def test_video_sem_trilha_de_audio(self):
        video = gerar(self.pasta / "camera sem microfone.mp4", "mp4", None, "mpeg4")
        with self.assertRaises(SemTrilhaDeAudio) as erro:
            decodificar(video)
        self.assertIsInstance(erro.exception, AudioIlegivel)
        mensagem = str(erro.exception)
        self.assertIn("'camera sem microfone.mp4' é um vídeo sem trilha de áudio", mensagem)
        self.assertIn("não há som para transcrever", mensagem)

    def test_arquivo_cortado_ou_que_nao_e_midia(self):
        mp4 = gerar(self.pasta / "inteiro.mp4", "mp4", "aac", "mpeg4")
        cortado = self.pasta / "cortado.mp4"
        dados = mp4.read_bytes()
        cortado.write_bytes(dados[: len(dados) // 2])     # o MP4 guarda o índice no fim
        texto = self.pasta / "audiencia.mp3"
        texto.write_text("isto não é áudio", encoding="utf-8")
        vazio = self.pasta / "vazio.wav"
        vazio.write_bytes(b"")
        for caminho in (cortado, texto, vazio):
            with self.subTest(arquivo=caminho.name):
                with self.assertRaises(ArquivoDanificado) as erro:
                    decodificar(caminho)
                mensagem = str(erro.exception)
                self.assertIn(f"Não consegui ler '{caminho.name}' como áudio ou vídeo", mensagem)
                self.assertIn("cortado", mensagem)
                self.assertIn("corrompido", mensagem)
                # o caminho inteiro (que pode dizer o processo) não vai na frase
                self.assertNotIn(str(self.pasta), mensagem)

    def test_m4a_protegido_contra_copia(self):
        """A descrição da trilha de áudio trocada por 'enca' (CENC) ou 'drms'
        (FairPlay do iTunes): a frase do DRM, e não a de arquivo danificado."""
        if not _encoder("aac"):
            self.skipTest("sem AAC")
        original = gerar(self.pasta / "livre.m4a", "ipod", "aac").read_bytes()
        self.assertEqual(arquivo.protecao_drm(self.pasta / "livre.m4a"), "")
        posicao = original.index(b"stsd") + 12           # versão/sinais, quantidade, tamanho
        self.assertEqual(original[posicao + 4:posicao + 8], b"mp4a")
        for tipo in (b"enca", b"drms"):
            with self.subTest(tipo=tipo):
                caminho = self.pasta / f"protegido-{tipo.decode()}.m4a"
                caminho.write_bytes(original[:posicao + 4] + tipo + original[posicao + 8:])
                self.assertTrue(arquivo.protecao_drm(caminho))
                with self.assertRaises(ProtegidoPorDrm) as erro:
                    decodificar(caminho)
                self.assertIn("protegido contra cópia (DRM)", str(erro.exception))

    def test_video_com_so_o_video_cifrado_continua_legivel(self):
        """'encv' (vídeo cifrado) não impede o áudio: só a trilha de áudio importa."""
        if not (_encoder("aac") and _encoder("mpeg4")):
            self.skipTest("sem AAC ou MPEG-4")
        dados = gerar(self.pasta / "v.mp4", "mp4", "aac", "mpeg4").read_bytes()
        self.assertIn(b"mp4v", dados)
        caminho = self.pasta / "video-cifrado.mp4"
        caminho.write_bytes(dados.replace(b"mp4v", b"encv", 1))
        self.assertEqual(arquivo.protecao_drm(caminho), "")

    def test_wma_com_o_objeto_de_cifra_do_windows_media(self):
        """O cabeçalho ASF com o Content Encryption Object (Windows Media DRM)."""
        guid_cabecalho = uuid.UUID("75B22630-668E-11CF-A6D9-00AA0062CE6C").bytes_le
        guid_cifra = uuid.UUID("2211B3FB-BD23-11D2-B4B7-00A0C955FC6E").bytes_le
        objeto = guid_cifra + (40).to_bytes(8, "little") + bytes(16)
        cabecalho = (guid_cabecalho + (30 + len(objeto)).to_bytes(8, "little")
                     + (1).to_bytes(4, "little") + b"\x01\x02" + objeto)
        caminho = self.pasta / "musica protegida.wma"
        caminho.write_bytes(cabecalho + bytes(4096))
        self.assertEqual(arquivo.protecao_drm(caminho), "Windows Media DRM")
        with self.assertRaises(ProtegidoPorDrm):
            decodificar(caminho)
        # o WMA de verdade, sem cifra, não é confundido
        if _encoder("wmav2"):
            livre = gerar(self.pasta / "livre.wma", "asf", "wmav2")
            self.assertEqual(arquivo.protecao_drm(livre), "")
            self.assertAlmostEqual(decodificar(livre).size / TAXA, SEGUNDOS, delta=0.2)

    def test_protecao_drm_nunca_levanta(self):
        for conteudo in (b"", b"\x00" * 7, b"\x00\x00\x00\x01ftyp" + b"\xff" * 20,
                         b"\x00\x00\x00\x00moov", uuid.uuid4().bytes * 100):
            with self.subTest(conteudo=conteudo[:12]):
                caminho = self.pasta / "x.bin"
                caminho.write_bytes(conteudo)
                self.assertEqual(arquivo.protecao_drm(caminho), "")
        self.assertEqual(arquivo.protecao_drm(self.pasta / "nao-existe.mp4"), "")


if __name__ == "__main__":
    unittest.main()
