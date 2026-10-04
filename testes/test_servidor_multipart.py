"""O leitor de multipart/form-data (sem o módulo cgi) e o hub de eventos."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from helestron.servidor import eventos, multipart


def corpo(partes: list[tuple[str, str | None, bytes]], fronteira: str = "XyZ") -> bytes:
    saida = b""
    for nome, arquivo, dados in partes:
        cab = f'Content-Disposition: form-data; name="{nome}"'
        if arquivo is not None:
            cab += f'; filename="{arquivo}"\r\nContent-Type: application/octet-stream'
        saida += f"--{fronteira}\r\n{cab}\r\n\r\n".encode("utf-8") + dados + b"\r\n"
    return saida + f"--{fronteira}--\r\n".encode("utf-8")


class FluxoEmPedacos(io.RawIOBase):
    """Entrega no máximo 'n' bytes por leitura: o delimitador cai partido."""

    def __init__(self, dados: bytes, n: int):
        self.dados, self.n, self.pos = dados, n, 0

    def read(self, tamanho=-1):
        fim = self.pos + min(self.n, tamanho if tamanho > 0 else self.n)
        pedaco = self.dados[self.pos:fim]
        self.pos = fim
        return pedaco


class TestMultipart(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.pasta, True)

    def ler(self, dados: bytes, pedaco: int = 1 << 20, tipo="multipart/form-data; boundary=XyZ",
            limite=500 * 1024 * 1024):
        return multipart.ler(FluxoEmPedacos(dados, pedaco), len(dados), tipo, self.pasta, limite)

    def test_campos_e_arquivo(self):
        # Parece o delimitador sem ser (o navegador escolhe um que não esteja no conteúdo).
        conteudo = bytes(range(256)) * 300 + b"\r\n--XYZ quase delimitador\r\n--Xy"
        dados = corpo([("processo", None, "0700123-83.2024.8.02.0001".encode()),
                       ("arquivo", "Relação ção.xlsx", conteudo),
                       ("sigiloso", None, b"true")])
        for pedaco in (1, 7, 64, 4096, 1 << 20):
            with self.subTest(pedaco=pedaco):
                envio = self.ler(dados, pedaco)
                a = envio.arquivo("arquivo")
                self.assertEqual(a.nome, "Relação ção.xlsx")
                self.assertEqual(a.caminho.suffix, ".xlsx")
                self.assertTrue(a.caminho.name.startswith("envio-"))
                self.assertEqual(a.caminho.read_bytes(), conteudo)
                self.assertEqual(a.tamanho, len(conteudo))
                self.assertEqual(envio.campos, {"processo": "0700123-83.2024.8.02.0001",
                                                "sigiloso": "true"})
                envio.apagar()
                self.assertFalse(a.caminho.exists())

    def test_nome_com_caminho_e_extensao_estranha(self):
        envio = self.ler(corpo([("arquivo", "C:\\\\Users\\\\x\\\\..\\\\pauta.X$L;s", b"1")]))
        a = envio.arquivo()
        self.assertEqual(a.caminho.parent, self.pasta)
        self.assertEqual(a.caminho.suffix, ".xls")
        self.assertNotIn("..", a.nome)
        envio.apagar()

    def test_corpo_invalido_apaga_o_que_gravou(self):
        dados = corpo([("arquivo", "a.txt", b"x" * 10000)])[:-30]      # cortado
        with self.assertRaises(multipart.EnvioInvalido):
            self.ler(dados, 512)
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_sem_fronteira_ou_tipo_errado(self):
        with self.assertRaises(multipart.EnvioInvalido):
            self.ler(b"abc", tipo="multipart/form-data")
        with self.assertRaises(multipart.EnvioInvalido):
            self.ler(b"abc", tipo="application/json")
        with self.assertRaises(multipart.EnvioInvalido):
            self.ler(b"--XyZ\r\nsem cabecalho de disposicao\r\n\r\nx\r\n--XyZ--\r\n")

    def test_limite(self):
        dados = corpo([("arquivo", "a.bin", b"x" * 1000)])
        with self.assertRaises(multipart.EnvioGrandeDemais):
            self.ler(dados, limite=100)

    def test_campo_de_texto_grande_demais(self):
        dados = corpo([("texto", None, b"x" * (multipart.LIMITE_CAMPO + 10))])
        with self.assertRaises(multipart.EnvioGrandeDemais):
            self.ler(dados, 65536)

    def test_nome_codificado_rfc5987(self):
        cab = ("--XyZ\r\nContent-Disposition: form-data; name=\"arquivo\"; "
               "filename*=UTF-8''Rela%C3%A7%C3%A3o.csv\r\n\r\n").encode()
        envio = self.ler(cab + b"1\r\n--XyZ--\r\n")
        self.assertEqual(envio.arquivo().nome, "Relação.csv")
        envio.apagar()

    def test_apagar_antigos(self):
        velho = self.pasta / "envio-velho.xlsx"
        novo = self.pasta / "envio-novo.xlsx"
        outro = self.pasta / "outro.txt"
        for p in (velho, novo, outro):
            p.write_bytes(b"x")
        agora = time.time()
        import os

        os.utime(velho, (agora - 7200, agora - 7200))
        self.assertEqual(multipart.apagar_antigos(self.pasta, agora=agora), 1)
        self.assertEqual(sorted(p.name for p in self.pasta.iterdir()),
                         ["envio-novo.xlsx", "outro.txt"])


class TestHub(unittest.TestCase):
    def test_difusao_para_todos(self):
        hub = eventos.HubEventos()
        a, b = hub.assinar(), hub.assinar()
        hub.publicar("estado", {"x": 1})
        self.assertEqual(a.proximo(0.1), ("estado", {"x": 1}))
        self.assertEqual(b.proximo(0.1), ("estado", {"x": 1}))
        self.assertIsNone(a.proximo(0.05))                 # hora do ping
        a.cancelar()
        self.assertEqual(hub.conectados, 1)

    def test_fila_cheia_descarta_o_mais_velho(self):
        hub = eventos.HubEventos()
        a = hub.assinar()
        a.fila.maxsize = 3
        for i in range(5):
            hub.publicar("nivel", {"i": i})
        self.assertEqual([a.proximo(0.1)[1]["i"] for _ in range(3)], [2, 3, 4])
        self.assertEqual(a.descartados, 2)

    def test_fechar_acorda_as_conexoes(self):
        hub = eventos.HubEventos()
        a = hub.assinar()
        hub.fechar()
        self.assertIs(a.proximo(1), eventos.FIM)
        self.assertIs(hub.assinar().proximo(1), eventos.FIM)
        hub.publicar("estado", {})                         # depois de fechado: nada

    def test_formato_sse_e_json(self):
        from datetime import date, datetime

        bruto = eventos.formatar_sse("tarefa", {"quando": datetime(2026, 10, 3, 14, 30),
                                                 "dia": date(2026, 10, 3), "pasta": Path("/a/b"),
                                                 "texto": "linha 1\nlinha 2"}).decode()
        self.assertTrue(bruto.startswith("event: tarefa\ndata: "))
        self.assertTrue(bruto.endswith("\n\n"))
        self.assertEqual(bruto.count("\n"), 3)             # uma linha de dados só
        dados = json.loads(bruto.split("data: ", 1)[1])
        self.assertEqual(dados, {"quando": "2026-10-03T14:30:00", "dia": "2026-10-03",
                                 "pasta": "/a/b", "texto": "linha 1\nlinha 2"})


if __name__ == "__main__":
    unittest.main()
