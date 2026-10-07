"""O laço do servidor MCP (compartilhar/mcp_servidor.servir) não cai com a
mensagem que ele não consegue escrever.

Regressão (1.0.2, achado R23): um pedido JSON válido com o escape "\\ud800"
(surrogate isolado) no 'termo', no 'id' ou num 'method' desconhecido, que a
resposta repete, fazia o .encode("utf-8") da resposta levantar
UnicodeEncodeError FORA da proteção de cada mensagem. O laço terminava, o
processo do conector morria (o Claude Desktop o mostrava desconectado até
ser reiniciado) e as mensagens seguintes ficavam sem resposta.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helestron.compartilhar import mcp_servidor


class TestSurrogateIsolado(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name) / "Acervo"
        self.raiz.mkdir()

    def conversar(self, linhas: list[bytes]) -> list[dict]:
        saida = io.BytesIO()
        mcp_servidor.servir(self.raiz, entrada=io.BytesIO(b"\n".join(linhas) + b"\n"),
                            saida=saida)
        bruto = saida.getvalue()
        bruto.decode("utf-8")                       # a saída continua UTF-8 válido
        return [json.loads(l) for l in bruto.splitlines() if l.strip()]

    def test_servidor_responde_e_continua(self):
        respostas = self.conversar([
            b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"buscar",'
            b'"arguments":{"termo":"\\ud800"}}}',
            b'{"jsonrpc":"2.0","id":"a\\ud800","method":"ping"}',
            b'{"jsonrpc":"2.0","id":3,"method":"x\\udfff"}',
            b'{"jsonrpc":"2.0","id":4,"method":"ping"}',
        ])
        self.assertEqual([r["id"] for r in respostas], [1, "a\ud800", 3, 4])
        self.assertEqual(respostas[1]["result"], {})        # o 'id' volta igual ao do pedido
        self.assertIn("error", respostas[2])                # método desconhecido
        self.assertEqual(respostas[3]["result"], {})

    def test_acentos_continuam_em_utf8(self):
        saida = io.BytesIO()
        mcp_servidor.servir(self.raiz, entrada=io.BytesIO(
            b'{"jsonrpc":"2.0","id":"a\\u00e7\\u00e3o","method":"ping"}\n'), saida=saida)
        self.assertIn("ação".encode("utf-8"), saida.getvalue())

    def test_resposta_que_nao_vira_json_vira_erro_interno(self):
        with mock.patch.object(mcp_servidor.Servidor, "tratar", side_effect=lambda msg: {
                    "jsonrpc": "2.0", "id": msg["id"], "result": object()}), \
                self.assertLogs("mcp", "ERROR"):
            respostas = self.conversar([b'{"jsonrpc":"2.0","id":7,"method":"ping"}',
                                        b'{"jsonrpc":"2.0","id":8,"method":"ping"}'])
        self.assertEqual([(r["id"], r["error"]["code"]) for r in respostas],
                         [(7, -32603), (8, -32603)])


if __name__ == "__main__":
    unittest.main()
