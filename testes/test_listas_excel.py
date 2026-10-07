"""Relação de processos em planilha do Excel: as variantes que o mundo real
manda (exportação de sistemas, arquivo que o openpyxl recusa, .xlsb, planilha
com senha) - e a que deixava o 'Baixar processos' recusar o Excel."""

import re
import tempfile
import unittest
import zipfile
from pathlib import Path

import openpyxl

from helestron.nucleo import listas

N1 = "0700001-70.2024.8.02.0058"
N2 = "0700002-55.2024.8.02.0058"


class TestRelacaoNoExcel(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        livro = openpyxl.Workbook()
        aba = livro.active
        aba.append(["Processo", "Classe"])
        aba.append([N1, "Procedimento Comum"])
        aba.append([N2, "Execução"])
        self.base = self.tmp / "base.xlsx"
        livro.save(self.base)

    def _variante(self, nome, trocar, alvo="xl/worksheets/sheet"):
        destino = self.tmp / nome
        with zipfile.ZipFile(self.base) as zi, zipfile.ZipFile(destino, "w") as zo:
            for item in zi.infolist():
                dados = zi.read(item.filename)
                if item.filename.startswith(alvo):
                    dados = trocar(dados)
                zo.writestr(item, dados)
        return destino

    def _numeros(self, caminho):
        return [n.formatado for n in listas.ler_arquivo(caminho).processos]

    def test_planilha_comum(self):
        self.assertEqual(self._numeros(self.base), [N1, N2])

    def test_dimensao_declarada_errada_como_nas_exportacoes(self):
        # O defeito relatado: a planilha exportada declara a dimensão "A1",
        # e o modo read_only lia só a primeira linha (o cabeçalho).
        arq = self._variante("exportada.xlsx", lambda d: re.sub(
            rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1"/>', d))
        self.assertEqual(self._numeros(arq), [N1, N2])

    def test_sem_dimensao(self):
        arq = self._variante("sem-dimensao.xlsx", lambda d: re.sub(
            rb'<dimension ref="[^"]*"/>', b"", d))
        self.assertEqual(self._numeros(arq), [N1, N2])

    def test_openpyxl_recusa_e_le_pelo_xml(self):
        arq = self._variante("variante.xlsx", lambda d: b"<lixo>", alvo="xl/workbook.xml")
        self.assertEqual(self._numeros(arq), [N1, N2])

    def test_xlsb_explica_o_que_fazer(self):
        arq = self.tmp / "binaria.xlsb"
        with zipfile.ZipFile(arq, "w") as z:
            z.writestr("[Content_Types].xml", "<x/>")
            z.writestr("xl/workbook.bin", b"\x00")
        with self.assertRaises(listas.ListaInvalida) as ctx:
            listas.ler_arquivo(arq)
        self.assertIn(".xlsx", str(ctx.exception))

    def test_planilha_com_senha_de_abertura(self):
        arq = self.tmp / "senha.xlsx"
        arq.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
                        + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 512)
        with self.assertRaises(listas.ListaInvalida) as ctx:
            listas.ler_arquivo(arq)
        self.assertIn("senha", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
