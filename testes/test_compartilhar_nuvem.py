"""O espelho na nuvem e a retirada do processo que virou sigiloso, com
caminhos longos.

Regressão (1.0.2, achado R22): o espelho copia para a nuvem com o prefixo
"\\\\?\\" (acima de 260 caracteres), mas a retirada do sigiloso varria a
pasta sem ele. No Windows sem caminhos longos liberados, a cópia longa
ficava invisível para a varredura (Path.is_file() dá False quando o
caminho passa do limite, e as pastas além dele nem são lidas): o segredo
de justiça continuava no OneDrive e o espelho terminava como sucesso.

Fora do Windows o limite não existe; o teste o imita: sem o "prefixo"
(aqui, o "//" inicial, que no Linux leva ao mesmo arquivo), o caminho da
nuvem acima do limite "não existe" para os.stat, os.lstat e os.scandir.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helestron.compartilhar import nuvem

X = "0700123-45.2024.8.02.0001"


class TestRetiradaComCaminhoLongo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.acervo = tmp / "Acervo"
        self.sigilosos = tmp / "Sigilosos"
        self.nuvem = tmp / "OneDrive - Tribunal"
        self.lote = "Lote " + "da vara de família " * 4
        for rel in (f"Processos/{self.lote}/{X}.pdf",
                    f"Processos/{self.lote}/Minutas/Sentença {X}.docx",
                    "Processos/Outro lote/0700555-25.2024.8.02.0001.pdf"):
            arquivo = self.acervo / rel
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_bytes(b"autos")
        espelho = self.nuvem / nuvem.SUBPASTA / "Processos" / self.lote
        self.copias = (espelho / f"{X}.pdf", espelho / "Minutas" / f"Sentença {X}.docx")
        # o limite fica entre a pasta do lote (que se lê) e o que está nela
        self.limite = len(str(espelho)) + 1

    def _windows_sem_caminho_longo(self):
        """Imita o Windows sem caminhos longos liberados, só na pasta da nuvem."""
        raiz, limite = str(self.nuvem), self.limite

        def longo(p, sempre=False):
            texto = os.path.abspath(str(p))
            if texto.startswith("//") or not (sempre or len(texto) >= limite):
                return texto
            return "/" + texto                 # o "\\?\" do teste: o mesmo arquivo

        def restrito(original):
            def chamada(caminho, *a, **k):
                texto = os.fsdecode(os.fspath(caminho)) if not isinstance(caminho, int) else ""
                if texto.startswith(raiz) and len(texto) > limite:
                    raise FileNotFoundError(2, "O sistema não pode encontrar o caminho "
                                               "especificado", texto)
                return original(caminho, *a, **k)
            return chamada

        return (mock.patch.object(nuvem, "_longo", longo),
                mock.patch.object(os, "stat", restrito(os.stat)),
                mock.patch.object(os, "lstat", restrito(os.lstat)),
                mock.patch.object(os, "scandir", restrito(os.scandir)))

    def test_copia_longa_do_sigiloso_sai_da_nuvem(self):
        remendos = self._windows_sem_caminho_longo()
        for r in remendos:
            r.start()
            self.addCleanup(r.stop)
        # 1º espelho: o processo ainda é público, e as cópias longas são criadas
        resultado = nuvem.espelhar(self.acervo, self.nuvem, sigilosos=None, pauta=None)
        self.assertEqual(resultado.copiados, 3)
        for copia in self.copias:
            self.assertTrue(os.path.exists("/" + str(copia)), copia)
            self.assertFalse(copia.is_file(), "o teste não imita o limite do Windows")
        # o processo virou sigiloso: os autos foram para a pasta dos sigilosos
        (self.sigilosos / "Lote 1").mkdir(parents=True)
        (self.sigilosos / "Lote 1" / f"{X}.pdf").write_bytes(b"autos")
        with self.assertLogs("compartilhar.nuvem", "WARNING") as registro:
            resultado = nuvem.espelhar(self.acervo, self.nuvem, sigilosos=self.sigilosos,
                                       pauta=None)
        self.assertEqual(resultado.sigilosos_restantes, [])
        for copia in self.copias:
            self.assertFalse(os.path.exists("/" + str(copia)),
                             f"a cópia do sigiloso ficou na nuvem: {copia.name}")
        self.assertEqual(sum("Retirei do espelho na nuvem" in linha
                             for linha in registro.output), 2)
        outro = (self.nuvem / nuvem.SUBPASTA / "Processos" / "Outro lote"
                 / "0700555-25.2024.8.02.0001.pdf")
        self.assertTrue(outro.is_file(), "o processo público continua no espelho")

    def test_copia_longa_presa_vira_erro(self):
        remendos = self._windows_sem_caminho_longo()
        for r in remendos:
            r.start()
            self.addCleanup(r.stop)
        nuvem.espelhar(self.acervo, self.nuvem, sigilosos=None, pauta=None)
        (self.sigilosos / "Lote 1").mkdir(parents=True)
        (self.sigilosos / "Lote 1" / f"{X}.pdf").write_bytes(b"autos")
        apagar = os.unlink

        def unlink(caminho, *a, **k):
            if str(caminho).endswith(f"{X}.pdf"):
                raise PermissionError(13, "Acesso negado")
            return apagar(caminho, *a, **k)

        with mock.patch.object(nuvem.os, "unlink", unlink), \
                self.assertLogs("compartilhar.nuvem", "WARNING"), \
                self.assertRaises(nuvem.SigilosoNaNuvem) as caso:
            nuvem.espelhar(self.acervo, self.nuvem, sigilosos=self.sigilosos, pauta=None)
        restantes = caso.exception.espelho.sigilosos_restantes
        self.assertEqual([(a, m) for a, m in restantes],
                         [(self.copias[0], "arquivo aberto ou sem permissão")])
        self.assertIn(f"{X}.pdf", str(caso.exception))


if __name__ == "__main__":
    unittest.main()
