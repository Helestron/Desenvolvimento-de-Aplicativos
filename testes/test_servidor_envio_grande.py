"""Envio de arquivo grande (a gravação de audiência em vídeo) e o erro 500 discreto.

* O limite do envio é por rota: a gravação aceita até 20 GB; a relação de
  processos e o relatório da pauta continuam com 500 MB.
* O arquivo vai para o disco em blocos (nunca inteiro na memória), e só
  depois de conferido o espaço livre: sem espaço, 507 com a frase de quanto
  há e quanto o arquivo tem, sem gravar nada; disco cheio no meio, 507 e o
  pedaço gravado apagado.
* Com uma transcrição de gravação rodando, o envio é recusado ANTES de ler os
  gigabytes.
* O 500 genérico leva à página só o tipo da exceção; o texto e o rastro
  (caminhos, números de processo) ficam no registro.
"""

from __future__ import annotations

import errno
import hashlib
import http.client
import json
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from helestron.servidor import multipart, rede
from testes.test_servidor_base import ServidorDeTeste

NUMERO = "0700123-83.2024.8.02.0001"


def anunciar(app, caminho: str, tamanho: int, tipo: str = "multipart/form-data; boundary=x"):
    """Manda só os cabeçalhos (Content-Length = 'tamanho') e lê a resposta."""
    conexao = http.client.HTTPConnection("127.0.0.1", app.porta, timeout=20)
    conexao.putrequest("POST", caminho)
    conexao.putheader("X-Helestron-Token", app.token)
    conexao.putheader("Content-Type", tipo)
    conexao.putheader("Content-Length", str(tamanho))
    conexao.endheaders()
    resposta = conexao.getresponse()
    corpo = json.loads(resposta.read())
    conexao.close()
    return resposta, corpo


class TestLimitePorRota(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        p = mock.patch("helestron.servicos.atualizar_indice")
        p.start()
        self.addCleanup(p.stop)

    def test_rota_da_gravacao_tem_o_proprio_limite(self):
        from helestron.servidor import api_audiencias

        rota, _, _ = self.app.servidor.roteador.achar("POST", "/api/transcricao/gravacao")
        self.assertEqual(rota.limite_envio, api_audiencias.LIMITE_ENVIO_GRAVACAO)
        self.assertEqual(api_audiencias.LIMITE_ENVIO_GRAVACAO, 20 * 1024 ** 3)
        for caminho in ("/api/relacao/arquivo", "/api/pauta/importar"):
            with self.subTest(caminho=caminho):
                rota, _, _ = self.app.servidor.roteador.achar("POST", caminho)
                self.assertIsNone(rota.limite_envio)
        self.assertEqual(rede.LIMITE_ENVIO, 500 * 1024 * 1024)
        self.assertEqual(multipart.LIMITE_PADRAO, rede.LIMITE_ENVIO)

    def test_gravacao_acima_de_500_mb_passa_do_limite_das_outras_rotas(self):
        # 600 MB anunciados: a relação recusa (413); a gravação vai adiante até
        # conferir o disco - aqui, sem espaço (507), sem ler o corpo.
        resposta, corpo = anunciar(self.app, "/api/relacao/arquivo", 600 * 1024 ** 2)
        self.assertEqual((resposta.status, corpo["erro"]["codigo"]), (413, "envio_grande_demais"))
        self.assertIn("500 MB", corpo["erro"]["mensagem"])
        with mock.patch("helestron.servidor.rede.espaco_livre", return_value=300 * 1024 ** 2):
            resposta, corpo = anunciar(self.app, "/api/transcricao/gravacao", 600 * 1024 ** 2)
        self.assertEqual((resposta.status, corpo["erro"]["codigo"]), (507, "espaco_insuficiente"))
        self.assertEqual(resposta.getheader("Connection"), "close")
        mensagem = corpo["erro"]["mensagem"]
        self.assertIn("600 MB", mensagem)
        self.assertIn("300 MB livres", mensagem)
        self.assertIn("“Escolher arquivo”", mensagem)
        envios = self.app.pasta_envios()
        self.assertEqual(list(envios.glob("*")) if envios.exists() else [], [])

    def test_gravacao_acima_de_20_gb_e_recusada_sem_ler(self):
        resposta, corpo = anunciar(self.app, "/api/transcricao/gravacao", 21 * 1024 ** 3)
        self.assertEqual((resposta.status, corpo["erro"]["codigo"]), (413, "envio_grande_demais"))
        self.assertIn("20 GB", corpo["erro"]["mensagem"])
        self.assertIn("“Escolher arquivo”", corpo["erro"]["mensagem"])

    def test_o_limite_vale_o_da_rota_e_nao_o_global(self):
        """Com o limite global baixo (1 KB), a relação recusa um envio de 8 KB e
        a gravação, com o limite dela, o recebe inteiro."""
        conteudo = bytes(range(256)) * 32                       # 8 KB
        recebidos = []

        def transcrever(origem, numero, cfg, progresso, cancelado, **kw):
            recebidos.append(hashlib.sha256(Path(origem).read_bytes()).hexdigest())
            return Path(cfg.pasta_transcricoes) / "x.docx"

        with mock.patch("helestron.servidor.rede.LIMITE_ENVIO", 1024), \
                mock.patch("helestron.servicos.transcrever_gravacao", side_effect=transcrever), \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar"):
            status, env = self.cliente.enviar("/api/relacao/arquivo", "relação.csv", conteudo)
            self.assertEqual((status, env["erro"]["codigo"]), (413, "envio_grande_demais"))
            self.assertIn("1 KB", env["erro"]["mensagem"])
            status, env = self.cliente.enviar("/api/transcricao/gravacao", f"{NUMERO}.wav",
                                              conteudo)
            self.assertEqual(status, 200, env)
            self.esperar_tarefa(env["dados"]["tarefa"])
        self.assertEqual(recebidos, [hashlib.sha256(conteudo).hexdigest()])

    def test_envio_de_varios_mb_chega_inteiro_em_blocos(self):
        """3 MB (o delimitador cai entre blocos de 1 MB): o arquivo chega
        idêntico, e o leitor nunca pede mais que um bloco de cada vez."""
        conteudo = uuid.uuid4().bytes * (3 * 1024 * 1024 // 16) + b"fim"
        pedidos: list[int] = []
        original = multipart._Leitor.ler

        def ler(leitor, n=multipart.PEDACO):
            pedidos.append(n)
            return original(leitor, n)

        recebidos = []

        def transcrever(origem, numero, cfg, progresso, cancelado, **kw):
            recebidos.append(Path(origem).read_bytes() == conteudo)
            return Path(cfg.pasta_transcricoes) / "x.docx"

        with mock.patch.object(multipart._Leitor, "ler", ler), \
                mock.patch("helestron.servicos.transcrever_gravacao", side_effect=transcrever), \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar"):
            status, env = self.cliente.enviar("/api/transcricao/gravacao", f"{NUMERO}.mp4",
                                              conteudo, {"tipo": "Una"})
            self.assertEqual(status, 200, env)
            self.esperar_tarefa(env["dados"]["tarefa"])
        self.assertEqual(recebidos, [True])
        self.assertLessEqual(max(pedidos), multipart.PEDACO_ARQUIVO)
        self.assertGreater(pedidos.count(multipart.PEDACO_ARQUIVO), 1)

    def test_disco_cheio_no_meio_desfaz_o_envio(self):
        reais = []
        abrir = open
        conteudo = b"x" * (3 * 1024 * 1024)

        class Cheio:
            """O disco enche na última escrita: o corpo já foi lido inteiro (o
            cliente não é cortado no meio do envio), e o que foi gravado tem de
            sumir."""

            def __init__(self, arquivo):
                self.arquivo = arquivo
                self.escritos = 0

            def write(self, dados):
                if self.escritos + len(dados) >= len(conteudo):
                    raise OSError(errno.ENOSPC, "No space left on device")
                self.escritos += len(dados)
                return self.arquivo.write(dados)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.arquivo.close()

        def abrir_cheio(caminho, modo="r", *a, **kw):
            arquivo = abrir(caminho, modo, *a, **kw)
            if "w" in modo:
                reais.append(Path(caminho))
                return Cheio(arquivo)
            return arquivo

        with mock.patch("helestron.servidor.multipart.open", abrir_cheio, create=True), \
                mock.patch("helestron.servicos.transcrever_gravacao") as transcrever:
            status, env = self.cliente.enviar("/api/transcricao/gravacao", f"{NUMERO}.wav",
                                              conteudo)
        self.assertEqual((status, env["erro"]["codigo"]), (507, "espaco_insuficiente"))
        self.assertIn("disco encheu", env["erro"]["mensagem"])
        transcrever.assert_not_called()
        self.assertTrue(reais)
        self.assertFalse(any(p.exists() for p in reais))

    def test_com_transcricao_rodando_recusa_antes_de_receber(self):
        liberar = threading.Event()

        def transcrever(origem, numero, cfg, progresso, cancelado, **kw):
            liberar.wait(10)
            return Path(cfg.pasta_transcricoes) / "x.docx"

        audio = self.amb.raiz / f"{NUMERO}.mp3"
        audio.write_bytes(b"ID3")
        with mock.patch("helestron.servicos.transcrever_gravacao", side_effect=transcrever), \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar"):
            primeira = self.cliente.dados("POST", "/api/transcricao/gravacao",
                                          {"caminho": str(audio)})["tarefa"]
            try:
                with mock.patch("helestron.servidor.multipart.ler") as ler:
                    status, env = self.cliente.enviar("/api/transcricao/gravacao",
                                                      f"{NUMERO}.wav", b"RIFF" * 1000)
                self.assertEqual((status, env["erro"]["codigo"]), (409, "ocupado"))
                self.assertIn("Transcrever a gravação", env["erro"]["mensagem"])
                ler.assert_not_called()
            finally:
                liberar.set()
            self.esperar_tarefa(primeira)


class TestEspacoLivre(unittest.TestCase):
    def test_pasta_que_ainda_nao_existe_usa_a_mais_proxima(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            livre = rede.espaco_livre(Path(tmp) / "temp" / "envios")
        self.assertIsInstance(livre, int)
        self.assertGreater(livre, 0)

    def test_tamanho_legivel(self):
        self.assertEqual(rede.tamanho_legivel(0), "0 bytes")
        self.assertEqual(rede.tamanho_legivel(1536), "1,5 KB")
        self.assertEqual(rede.tamanho_legivel(500 * 1024 ** 2), "500 MB")
        self.assertEqual(rede.tamanho_legivel(20 * 1024 ** 3), "20 GB")
        self.assertEqual(rede.tamanho_legivel(int(4.25 * 1024 ** 3)), "4,2 GB")


class TestErroInternoDiscreto(ServidorDeTeste):
    def test_500_leva_so_o_tipo_e_o_registro_guarda_o_resto(self):
        segredo = f"/Sigilosos/{NUMERO} - Fulano de Tal/autos.pdf"
        with mock.patch("helestron.servidor.api_geral.listar_tribunais",
                        side_effect=RuntimeError(f"não abri {segredo}")):
            from helestron.servidor import rotas

            self.app.servidor.roteador = rotas.montar()
            with self.assertLogs("servidor.http", "ERROR") as registro:
                status, env = self.cliente.get("/api/tribunais")
        self.assertEqual(status, 500)
        self.assertEqual(env["erro"]["codigo"], "erro_interno")
        self.assertEqual(env["erro"]["detalhe"], "RuntimeError")
        self.assertNotIn(segredo, json.dumps(env, ensure_ascii=False))
        self.assertNotIn("Traceback", json.dumps(env))
        texto = "\n".join(registro.output)
        self.assertIn(segredo, texto)
        self.assertIn("Traceback", texto)


if __name__ == "__main__":
    unittest.main()
