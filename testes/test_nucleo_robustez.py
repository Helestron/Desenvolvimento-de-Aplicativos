"""Núcleo à prova do arquivo real: número com texto depois da barra, CNJ
corrompido pelo Excel que ainda confere, cofre de senhas que falha por um
instante, endereço corrigido fora do formato, número gigante no config.ini e
pasta dos sigilosos ou da pauta dentro da nuvem."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from helestron.nucleo import cnj, cofre_senhas, config, listas, tribunais


def cnj_valido(sequencial: int, ano: int = 2024, tr: str = "02", origem: int = 1) -> str:
    """Um número CNJ (só os 20 dígitos) com o dígito verificador certo."""
    seq, oooo = f"{sequencial:07d}", f"{origem:04d}"
    dv = 98 - (int(f"{seq}{ano}8{tr}{oooo}00") % 97)
    return f"{seq}{dv:02d}{ano}8{tr}{oooo}"


# ======================================================================= CNJ
class TestDependenteComTexto(unittest.TestCase):
    """Achado 43: '/ 1ª Vara' depois do número virava o incidente /01."""

    def test_barra_seguida_de_texto_nao_e_dependente(self):
        base = "0700123-45.2024.8.02.0001"
        casos = {
            f"{base} / 1ª Vara Cível da Capital": "",
            f"{base}/2ª Vara": "",
            f"{base} / 3 réus": "",
            f"{base}/1º": "",
            f"{base}/1°": "",
            f"{base}/01": "01",
            f"{base}/0003": "03",
            f"{base}/1": "01",
            f"{base}/1 fim": "01",
            f"{base} / 01": "01",
            f"{base} /01": "01",
            f"{base}/01 Cumprimento de sentença": "01",
            f"{base}/01.": "01",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(cnj.ler(texto).dependente, esperado)
                self.assertEqual([n.dependente for n in cnj.extrair_todos(texto)], [esperado])

    def test_nome_do_arquivo_do_principal(self):
        n = cnj.ler("0700123-45.2024.8.02.0001 / 1ª Vara Cível da Capital")
        self.assertEqual(n.nome_arquivo, "0700123-45.2024.8.02.0001")

    def test_relacao_colada(self):
        lei = listas.ler_texto("0700123-45.2024.8.02.0001 / 1ª Vara Cível da Capital\n"
                               "0700124-45.2024.8.02.0001/2ª Vara\n"
                               "0700125-45.2024.8.02.0001 / 3 réus\n"
                               "0700126-45.2024.8.02.0001/01\n")
        self.assertEqual([n.formatado for n in lei.processos],
                         ["0700123-45.2024.8.02.0001", "0700124-45.2024.8.02.0001",
                          "0700125-45.2024.8.02.0001", "0700126-45.2024.8.02.0001/01"])


# ==================================================================== listas
class TestCnjComoNumeroNoExcel(unittest.TestCase):
    """Achado 44: o CNJ corrompido pelo double que ainda confere o dígito."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.d = Path(self.dir.name)

    def test_celula_float_grande_nunca_entra(self):
        # Exemplo do relato: o float de 19387448520248020022 vira um CNJ de
        # outro foro (0992) com o dígito verificador certo.
        valor = float(int("19387448520248020022"))
        corrompido = cnj.ler(listas._texto_da_celula(valor))
        self.assertTrue(corrompido.digito_confere)          # o DV não bastava
        col = listas._Coletor()
        col.celula(valor)
        self.assertEqual(col.leitura.processos, [])
        self.assertEqual(col.leitura.corrompidos, [corrompido.formatado])

    def test_numero_com_dois_zeros_na_frente_e_contado(self):
        col = listas._Coletor()
        col.celula(5.123452024802e17)          # "00..." - 18 dígitos
        self.assertEqual(col.leitura.processos, [])
        self.assertEqual(len(col.leitura.corrompidos), 1)

    def test_inteiro_exato_continua_pelo_digito(self):
        col = listas._Coletor()
        col.celula(int(cnj_valido(800072, origem=56)))
        col.celula(8000721320248020056)        # DV errado
        self.assertEqual([n.formatado for n in col.leitura.processos],
                         ["0800072-12.2024.8.02.0056"])
        self.assertEqual(col.leitura.corrompidos, ["0800072-13.2024.8.02.0056"])

    def test_numero_pequeno_segue_o_caminho_comum(self):
        col = listas._Coletor()
        col.celula(12.0)
        col.celula(1e25)
        self.assertEqual((col.leitura.processos, col.leitura.corrompidos), ([], []))

    def test_planilha_toda_numerica_e_recusada_mesmo_com_falsos_acertos(self):
        from openpyxl import Workbook

        # Números válidos do TJAL; entre eles, os que o arredondamento do
        # double transforma em outro número que AINDA confere o dígito.
        validos, falsos = [], []
        for i in range(1, 4000):
            digitos = cnj_valido(700000 + i * 37, origem=1 + i % 90)
            validos.append(digitos)
            lido = cnj.ler(listas._texto_da_celula(float(int(digitos))))
            if lido.digito_confere and lido.digitos != digitos:
                falsos.append(digitos)
        self.assertTrue(falsos, "a amostra precisa ter ao menos um falso acerto")
        wb = Workbook()
        ws = wb.active
        ws.append(["Processo"])
        for digitos in validos:
            ws.append([int(digitos)])          # o openpyxl grava como número
        wb.save(self.d / "numeros.xlsx")
        with self.assertRaises(listas.ListaInvalida) as ctx:
            listas.ler_arquivo(self.d / "numeros.xlsx")
        self.assertIn("formate a coluna", str(ctx.exception))
        # cada linha contada uma vez só (a segunda leitura, a das fórmulas,
        # não dobra a conta)
        self.assertIn(f"aconteceu com {len(validos)} linha(s)", str(ctx.exception))

    def test_planilha_com_texto_e_numero_so_aceita_o_texto(self):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["Processo"])
        ws.append(["0800072-12.2024.8.02.0056"])
        ws.append([float(int("19387448520248020022"))])
        wb.save(self.d / "misto.xlsx")
        lei = listas.ler_arquivo(self.d / "misto.xlsx")
        self.assertEqual([n.formatado for n in lei.processos], ["0800072-12.2024.8.02.0056"])
        self.assertEqual(lei.corrompidos, ["1938744-85.2024.8.02.0992"])


# ===================================================================== cofre
class TestCofreNaoPerdeSenhas(unittest.TestCase):
    """Achado 42: uma falha momentânea de leitura apagava o cofre inteiro."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.arq = Path(self.dir.name) / "credenciais.json"
        self.cofre = cofre_senhas.CofreSenhas(self.arq)
        self.cofre.guardar("esaj:TJAL", "111", "a")
        self.cofre.guardar("eproc:TJAL", "222", "b")

    def _arquivos(self) -> list[str]:
        return sorted(p.name for p in self.arq.parent.iterdir())

    def test_leitura_que_falha_uma_vez_nao_apaga_os_outros(self):
        original = Path.read_bytes
        falhas = [PermissionError(13, "Acesso negado")]

        def ler(caminho):
            if caminho == self.arq and falhas:
                raise falhas.pop()
            return original(caminho)

        with mock.patch.object(Path, "read_bytes", ler), \
                mock.patch.object(cofre_senhas.time, "sleep") as dormir:
            self.cofre.guardar("esaj:TJSP", "333", "c")
        self.assertEqual(dormir.call_count, 1)
        self.assertEqual(self.cofre.portais(), ["eproc:TJAL", "esaj:TJAL", "esaj:TJSP"])
        self.assertEqual(self.cofre.obter("esaj:TJAL"), ("111", "a"))

    def test_leitura_presa_de_vez_nao_grava_nada(self):
        antes = self.arq.read_bytes()
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError(13, "negado")), \
                mock.patch.object(cofre_senhas.time, "sleep") as dormir:
            with self.assertRaises(cofre_senhas.CofreIndisponivel) as ctx:
                self.cofre.guardar("esaj:TJSP", "333", "c")
            with self.assertRaises(PermissionError):
                self.cofre.apagar("esaj:TJAL")
        self.assertEqual(dormir.call_count, 2 * (cofre_senhas.TENTATIVAS - 1))
        self.assertIn("Nada foi alterado", str(ctx.exception))
        self.assertEqual(self.arq.read_bytes(), antes)
        self.assertEqual(self._arquivos(), ["credenciais.json"])

    def test_arquivo_estragado_vai_para_o_lado(self):
        self.arq.write_text('{"esaj:TJAL": "dpapi:xx", ', encoding="utf-8")
        estragado = self.arq.read_bytes()
        self.cofre.apagar("eproc:TJAL")
        nomes = self._arquivos()
        self.assertEqual(len(nomes), 1)
        self.assertTrue(nomes[0].startswith("credenciais.json.ilegivel-"), nomes)
        self.assertEqual((self.arq.parent / nomes[0]).read_bytes(), estragado)
        self.cofre.guardar("esaj:TJSP", "333", "c")
        self.assertEqual(self.cofre.portais(), ["esaj:TJSP"])

    def test_json_que_nao_e_objeto_tambem_vai_para_o_lado(self):
        self.arq.write_text('["esaj:TJAL"]', encoding="utf-8")
        self.assertEqual(self.cofre.portais(), [])
        self.assertEqual(self.cofre.obter("esaj:TJAL"), ("", ""))
        self.cofre.guardar("esaj:TJSP", "333", "c")
        self.assertEqual(self.cofre.portais(), ["esaj:TJSP"])
        self.assertTrue(any(n.startswith("credenciais.json.ilegivel-") for n in self._arquivos()))

    def test_valor_que_nao_e_texto_nao_derruba(self):
        self.arq.write_text('{"esaj:TJAL": 123}', encoding="utf-8")
        self.assertEqual(self.cofre.obter("esaj:TJAL"), ("", ""))

    def test_gravacoes_ao_mesmo_tempo_nao_se_perdem(self):
        original = cofre_senhas.gravar_privado

        def devagar(arquivo, texto):
            time.sleep(0.002)          # alarga a janela entre ler e gravar
            original(arquivo, texto)

        erros: list[BaseException] = []

        def guardar(i):
            try:
                cofre_senhas.CofreSenhas(self.arq).guardar(f"esaj:T{i:02d}", str(i), "s")
            except BaseException as erro:   # noqa: BLE001
                erros.append(erro)

        with mock.patch.object(cofre_senhas, "gravar_privado", devagar):
            threads = [threading.Thread(target=guardar, args=(i,)) for i in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(len(self.cofre.portais()), 18)
        self.assertEqual(self._arquivos(), ["credenciais.json"])

    def test_trava_de_outro_processo(self):
        trava = self.arq.with_name(self.arq.name + ".trava")
        trava.write_text("999999", encoding="ascii")
        with mock.patch.object(cofre_senhas, "ESPERA_TRAVA_S", 0.2):
            with self.assertRaises(cofre_senhas.CofreIndisponivel):
                self.cofre.guardar("esaj:TJSP", "333", "c")
        self.assertTrue(trava.exists())          # a trava viva não é de quem esperou
        self.assertNotIn("esaj:TJSP", self.cofre.portais())
        # esquecida (o processo que a tinha caiu): deixa de valer
        velho = time.time() - cofre_senhas.TRAVA_ABANDONADA_S - 5
        os.utime(trava, (velho, velho))
        self.cofre.guardar("esaj:TJSP", "333", "c")
        self.assertIn("esaj:TJSP", self.cofre.portais())
        self.assertEqual(self._arquivos(), ["credenciais.json"])

    def test_troca_insiste_quando_o_arquivo_esta_preso(self):
        original = os.replace
        falhas = [PermissionError(13, "Acesso negado")] * 2

        def replace(origem, destino):
            if falhas:
                raise falhas.pop()
            return original(origem, destino)

        with mock.patch.object(cofre_senhas.os, "replace", replace), \
                mock.patch.object(cofre_senhas.time, "sleep") as dormir:
            self.cofre.guardar("esaj:TJSP", "333", "c")
        self.assertEqual(dormir.call_count, 2)
        self.assertIn("esaj:TJSP", self.cofre.portais())
        self.assertEqual(self._arquivos(), ["credenciais.json"])

    def test_troca_presa_de_vez_nao_deixa_resto(self):
        antes = self.arq.read_bytes()
        with mock.patch.object(cofre_senhas.os, "replace",
                               side_effect=PermissionError(13, "Acesso negado")), \
                mock.patch.object(cofre_senhas.time, "sleep"):
            with self.assertRaises(PermissionError) as ctx:
                self.cofre.guardar("esaj:TJSP", "333", "c")
        self.assertIn("preso por outro programa", str(ctx.exception))
        self.assertEqual(self.arq.read_bytes(), antes)
        self.assertEqual(self._arquivos(), ["credenciais.json"])

    def test_apagar_o_que_nao_existe_nao_cria_arquivo(self):
        outro = cofre_senhas.CofreSenhas(Path(self.dir.name) / "novo" / "c.json")
        outro.apagar("esaj:TJAL")
        self.assertFalse(outro.arquivo.exists())


# ================================================================ tribunais
class TestEnderecosLocaisMalformados(unittest.TestCase):
    """Achado 47: uma entrada fora do formato derrubava toda consulta."""

    NUMERO_TJAL = "0700123-45.2024.8.02.0001"
    NUMERO_TJSP = "1000001-02.2024.8.26.0100"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.arq = Path(self.dir.name) / "enderecos-locais.json"
        p = mock.patch.object(tribunais, "ARQUIVO_LOCAL", self.arq)
        p.start()
        self.addCleanup(p.stop)
        tribunais._DESCARTADOS.clear()
        self.addCleanup(tribunais._DESCARTADOS.clear)

    def _escrever(self, dados) -> None:
        self.arq.write_text(json.dumps(dados), encoding="utf-8")

    def test_entradas_fora_do_formato_ficam_de_fora(self):
        url = "https://eproc1g.tjal.jus.br/eproc/"
        for dados, descartado in (({"eproc:TJAL": url}, "eproc:TJAL"),
                                  ({"eproc:TJAL": {"1g": 123}}, "eproc:TJAL/1g"),
                                  ({"eproc:TJAL": [url]}, "eproc:TJAL"),
                                  ([url], self.arq.name)):
            with self.subTest(dados=dados):
                self._escrever(dados)
                for numero in (self.NUMERO_TJAL, self.NUMERO_TJSP):
                    t = tribunais.por_numero(cnj.ler(numero))
                    self.assertIsNotNone(t)
                    self.assertTrue(t.url_para(cnj.ler(numero)))
                    if t.alternativo is not None:
                        self.assertTrue(t.alternativo.urls_para(cnj.ler(numero)))
                self.assertTrue(tribunais.descrever(cnj.ler(self.NUMERO_TJAL)))
                self.assertTrue(tribunais.enderecos("eproc:TJAL"))
                self.assertEqual(tribunais.enderecos_corrigidos(), [])
                self.assertIn(descartado, tribunais.problema_locais())
                # a tela de Ajustes ainda corrige (e regrava sem o estragado)
                tribunais.definir_endereco("eproc:TJAL", "1g", url)
                self.assertEqual(json.loads(self.arq.read_text(encoding="utf-8")),
                                 {"eproc:TJAL": {"1g": url}})
                self.assertEqual(tribunais.problema_locais(), "")
                tribunais.definir_endereco("eproc:TJAL", "1g", "")
                self.assertEqual(json.loads(self.arq.read_text(encoding="utf-8")), {})

    def test_o_que_esta_certo_continua_valendo(self):
        url = "https://eproc1g.tjal.jus.br/eproc/"
        self._escrever({"eproc:TJAL": {"1g": url, "2g": 5}, "esaj:TJSP": "x"})
        self.assertEqual(tribunais.enderecos_corrigidos(),
                         [{"portal": "eproc:TJAL", "grau": "1g", "rotulo": "1º grau",
                           "url": url}])
        problema = tribunais.problema_locais()
        self.assertIn("eproc:TJAL/2g", problema)
        self.assertIn("esaj:TJSP", problema)

    def test_sem_arquivo_nao_ha_problema(self):
        self.assertEqual(tribunais.problema_locais(), "")

    def test_aviso_no_registro_uma_vez_so(self):
        self._escrever({"eproc:TJAL": "https://x/"})
        with self.assertLogs(tribunais.log, "WARNING") as registro:
            for _ in range(5):
                tribunais.por_numero(cnj.ler(self.NUMERO_TJSP))
        self.assertEqual(len(registro.records), 1)


# ==================================================================== config
class TestNumeroGiganteNoConfig(unittest.TestCase):
    """Achado 48: '1e999' (infinito) derrubava o download e os Ajustes."""

    def test_para_inteiro(self):
        self.assertEqual(config.para_inteiro("3"), 3)
        self.assertEqual(config.para_inteiro(" 2,7 "), 2)
        self.assertEqual(config.para_inteiro(4.0), 4)
        self.assertEqual(config.para_inteiro(7), 7)
        for ruim in ("1e999", "-1e999", "inf", "Infinity", "nan", float("inf"), float("nan"),
                     "abc", "", None, True):
            with self.subTest(valor=ruim):
                with self.assertRaises(ValueError):
                    config.para_inteiro(ruim)

    def test_ini_com_infinito_volta_ao_padrao(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "config.ini"
            arq.write_text("[download]\nespera_segundos = 1e999\ntentativas = -inf\n"
                           "pausa_entre_processos = inf\n", encoding="utf-8")
            c = config.Config(arq)
            padrao = int(config.PADROES[("download", "espera_segundos")])
            self.assertEqual(c.inteiro("download", "espera_segundos"), padrao)
            self.assertEqual(c.inteiro("download", "tentativas"),
                             int(config.PADROES[("download", "tentativas")]))
            self.assertEqual(c.real("download", "pausa_entre_processos"),
                             float(config.PADROES[("download", "pausa_entre_processos")]))

    def test_opcoes_do_download_com_infinito(self):
        from helestron.download.modelos import OpcoesDownload

        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "config.ini"
            arq.write_text("[download]\nespera_segundos = 1e999\npausa_entre_processos = nan\n",
                           encoding="utf-8")
            OpcoesDownload.de_config(config.Config(arq))      # não levanta


class TestSigilososNaNuvem(unittest.TestCase):
    """Achado 41: sigilosos e pauta nunca dentro da pasta da nuvem."""

    def test_regra(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            nuvem = base / "OneDrive"
            self.assertEqual(config.conflito_com_a_nuvem("", base / "OneDrive" / "S"), "")
            self.assertEqual(config.conflito_com_a_nuvem(nuvem, base / "Sig", base / "Pauta"), "")
            for sig in (nuvem, nuvem / "Gabinete" / "Sigilosos",
                        nuvem / "Helestron - Acervo" / "Sig"):
                with self.subTest(sigilosos=sig):
                    self.assertIn("segredo de justiça",
                                  config.conflito_com_a_nuvem(nuvem, sig, base / "Pauta"))
            self.assertIn("dentro da pasta dos processos em segredo",
                          config.conflito_com_a_nuvem(base / "Sig" / "OD", base / "Sig"))
            self.assertIn("pauta exportada",
                          config.conflito_com_a_nuvem(nuvem, base / "Sig", nuvem / "Pauta"))
            self.assertIn("pauta exportada",
                          config.conflito_com_a_nuvem(base / "Pauta" / "OD", base / "Sig",
                                                      base / "Pauta"))
            # pasta vizinha com o mesmo começo de nome não é "dentro"
            self.assertEqual(config.conflito_com_a_nuvem(nuvem, base / "OneDrive2"), "")


if __name__ == "__main__":
    unittest.main()
