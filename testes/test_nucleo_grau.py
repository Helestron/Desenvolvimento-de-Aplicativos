"""O 2º grau no núcleo: número com dependente de 5 dígitos, a regra única do
grau, as duas chaves (do processo e dos autos), o sigilo nos dois graus, o
grau dentro do Tribunal, o catálogo, as opções do download e o manifesto de
paginação.

Os números de exemplo têm o dígito verificador certo (o próprio Helestron
recusaria um exemplo errado):
  A  = apelação/RESE, o mesmo número nos dois graus
  H  = habeas corpus originário (órgão 0000)
  PL = plantão do 2º grau (órgão 9002)
  P  = principal dos embargos; E = P/50000 (embargos de declaração, recurso
       interno do 2º grau); E2 = P/50001 (agravo interno)
  I  = A/01 (incidente do 1º grau)
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helestron
from helestron.download import modelos
from helestron.nucleo import cnj, config, paginacao, sigilo, tribunais

A = "0700001-93.2024.8.02.0058"
A2 = "0700002-78.2024.8.02.0058"
H = "0803061-28.2025.8.02.0000"
H2 = "0803062-13.2025.8.02.0000"
PL = "0800103-29.2025.8.02.9002"
P = "0706265-50.2017.8.02.0001"
E = P + "/50000"
E2 = P + "/50001"
I = A + "/01"
X = "0700003-40.2024.8.02.0001"

_RE_CNJ = re.compile(r"(?<!\d)(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})(?!\d)")


def _dv_confere(texto: str) -> bool:
    n, dv, ano, j, tr, origem = _RE_CNJ.search(texto).groups()
    return int(n + ano + j + tr + origem + dv) % 97 == 1


class TestNumerosDeExemplo(unittest.TestCase):
    def test_digito_verificador_dos_exemplos(self):
        for texto in (A, A2, H, H2, PL, P, E, E2, I, X):
            with self.subTest(numero=texto):
                self.assertTrue(cnj.ler(texto).digito_confere)
                self.assertTrue(_dv_confere(texto))
        # o número do enunciado não confere o dígito (o certo é o de A)
        self.assertFalse(cnj.ler("0700001-70.2024.8.02.0058").digito_confere)

    def test_numeros_no_codigo_do_cnj_com_digito_certo(self):
        # Exemplo nas docstrings e comentários do cnj.py ensina o formato: só
        # números que o próprio programa aceitaria (o de nome_dos_autos,
        # inclusive).
        fonte = Path(cnj.__file__).read_text(encoding="utf-8")
        achados = [m.group(0) for m in _RE_CNJ.finditer(fonte)
                   if set("".join(m.groups())) != {"0"}]
        self.assertTrue(achados)
        for numero in achados:
            with self.subTest(numero=numero):
                self.assertTrue(_dv_confere(numero))
        doc = inspect.getdoc(cnj.nome_dos_autos)
        self.assertIn(f"{A} (2G)", doc)
        for m in _RE_CNJ.finditer(doc):
            self.assertTrue(_dv_confere(m.group(0)), m.group(0))


class TestDependenteDeCincoDigitos(unittest.TestCase):
    """A tabela da §1.1: o /50000 do 2º grau, sem mudar o que já valia."""

    def test_tabela(self):
        casos = (
            (f"{P}/50000", f"{P}/50000", f"{P}-50000", "50000"),
            (f"{A} / 50000", f"{A}/50000", f"{A}-50000", "50000"),
            (f"{P}/50001", f"{P}/50001", f"{P}-50001", "50001"),
            (f"{P}/0003", f"{P}/03", f"{P}-03", "03"),
            (f"{P}/3", f"{P}/03", f"{P}-03", "03"),
            (f"{P}/01", f"{P}/01", f"{P}-01", "01"),
            (f"{P}/0001", f"{P}/01", f"{P}-01", "01"),
            # nunca encolhe o de 5 dígitos; o de 4 é o do 1º grau, como sempre
            (f"{P}/05000", f"{P}/5000", f"{P}-5000", "5000"),
        )
        for texto, formatado, nome, dependente in casos:
            with self.subTest(texto=texto):
                n = cnj.ler(texto)
                self.assertEqual(n.formatado, formatado)
                self.assertEqual(n.nome_arquivo, nome)
                self.assertEqual(n.dependente, dependente)
                self.assertEqual(n.principal, texto.split("/")[0].strip())

    def test_continua_principal(self):
        for texto in (f"{P}/123456", f"{P}/50000ª", f"{P} / 1ª Vara", f"{P}/2ª Vara",
                      f"{P} / 3 réus", f"{P}/1º", f"{P}/1°", f"{P}-2024", f"{P} - 2ª Vara"):
            with self.subTest(texto=texto):
                n = cnj.ler(texto)
                self.assertEqual(n.formatado, P)
                self.assertEqual(n.nome_arquivo, P)
                self.assertEqual(n.dependente, "")

    def test_numero_maior_nao_casa(self):
        corrido = P.replace("-", "").replace(".", "")
        with self.assertRaises(cnj.NumeroInvalido):
            cnj.ler("9" + corrido + "1")

    def test_ler_lista_e_extrair_todos_distinguem_os_recursos(self):
        lidos = cnj.ler_lista(f"{X}\n{X}/50000\n{X}/50001\n{X}/50000\n# {X}/50002")
        self.assertEqual([n.formatado for n in lidos], [X, f"{X}/50000", f"{X}/50001"])
        self.assertEqual(len({cnj.chave(n) for n in lidos}), 3)
        achados = cnj.extrair_todos(f"principal {P}; embargos {E}; agravo interno {E2}")
        self.assertEqual([n.formatado for n in achados], [P, E, E2])
        # Numero continua sem grau: igualdade e hash como antes
        self.assertEqual(cnj.ler(E), cnj.ler(f"{P} / 50000"))
        self.assertNotIn("grau", {f.name for f in dataclasses.fields(cnj.Numero)})

    def test_nome_de_arquivo_com_dependente_de_cinco_digitos(self):
        for nome, esperado in ((f"{P}-50000.pdf", f"{P}-50000"),
                               (f"{P}-50000 (2G).pdf", f"{P}-50000"),
                               (f"{P}-inc50000.pdf", f"{P}-50000"),
                               (f"{P}-50001 (2).pdf", f"{P}-50001"),
                               (f"{P}-123456.pdf", P),
                               (f"{P}-01 (2G)_capa.json", f"{P}-01"),
                               (f"{P}/50000", f"{P}-50000")):
            with self.subTest(nome=nome):
                self.assertEqual(cnj.ler_nome_arquivo(nome).nome_arquivo, esperado)


class TestGrau(unittest.TestCase):
    def test_constantes(self):
        self.assertEqual(cnj.GRAUS, ("1g", "2g"))
        self.assertEqual(cnj.SUFIXO_2G, " (2G)")

    def test_normalizar_grau(self):
        for valor in ("1", "1g", "1G", "1º", "1°", "1° grau", "1º grau", "1o", " 1 ", 1):
            with self.subTest(valor=valor):
                self.assertEqual(cnj.normalizar_grau(valor), "1g")
        for valor in ("2", "2g", "2G", "2º", "2° grau", "2º grau", "2o", " 2 g ", 2):
            with self.subTest(valor=valor):
                self.assertEqual(cnj.normalizar_grau(valor), "2g")
        for valor in (None, "", "3", "3g", "ambos", "12", "1gg", "g", "2ª", "segundo", "1g2g"):
            with self.subTest(valor=valor):
                self.assertEqual(cnj.normalizar_grau(valor), "")

    def test_grau_do_numero(self):
        casos = {A: "", A2: "", I: "", P: "", X: "", f"{P}/0003": "", f"{P}/5000": "",
                 f"{P}/60000": "", H: "2g", H2: "2g", PL: "2g", E: "2g", E2: "2g",
                 "0800103-29.2025.8.02.9002/01": "2g"}
        for texto, esperado in casos.items():
            with self.subTest(numero=texto):
                self.assertEqual(cnj.grau_do_numero(cnj.ler(texto)), esperado)

    def test_grau_do_processo_a_regra_unica(self):
        # §1.9: o número; senão o grau do lote; senão 1g
        for lote in ("", "1g", "2g", "1", "2", "xyz", None):
            with self.subTest(lote=lote):
                for so_no_2g in (H, PL, E, E2):
                    self.assertEqual(cnj.grau_do_processo(cnj.ler(so_no_2g), lote), "2g")
                esperado = cnj.normalizar_grau(lote) or "1g"
                for do_lote in (A, I, P, X):
                    self.assertEqual(cnj.grau_do_processo(cnj.ler(do_lote), lote), esperado)
        self.assertEqual(cnj.grau_do_processo(cnj.ler(A)), "1g")
        self.assertEqual(cnj.grau_do_processo(cnj.ler(A), "2"), "2g")
        self.assertEqual(cnj.grau_do_processo(cnj.ler(I), "2g"), "2g")

    def test_nome_dos_autos(self):
        casos = ((A, "1g", A), (A, "2g", f"{A} (2G)"), (A, "2", f"{A} (2G)"),
                 (A, "", A), (A, "xyz", A), (I, "1g", f"{A}-01"), (I, "2g", f"{A}-01 (2G)"),
                 (E, "2g", f"{P}-50000 (2G)"), (H, "2g", f"{H} (2G)"), (PL, "2g", f"{PL} (2G)"))
        for texto, grau, esperado in casos:
            with self.subTest(numero=texto, grau=grau):
                self.assertEqual(cnj.nome_dos_autos(cnj.ler(texto), grau), esperado)
        self.assertEqual(cnj.nome_dos_autos(cnj.ler(A)), A)
        # o sufixo vem depois do -NN, separado por espaço: nunca "-2G" colado
        self.assertNotIn("-2G", cnj.nome_dos_autos(cnj.ler(I), "2g"))

    def test_grau_do_nome_e_chave_dos_autos(self):
        # tabela da §1.1: (texto, chave do PROCESSO, grau_do_nome, chave dos AUTOS)
        casos = (
            (f"{X}.pdf", X, "1g", X),
            (f"{X} (2G).pdf", X, "2g", f"{X} (2G)"),
            (f"{X} (2G) (2).pdf", X, "2g", f"{X} (2G)"),
            (f"{X} (2g).pdf", X, "2g", f"{X} (2G)"),
            (f"{X} - 2g.pdf", X, "2g", f"{X} (2G)"),
            (f"{X} (2º grau).pdf", X, "2g", f"{X} (2G)"),
            (f"{X}-50000 (2G).pdf", f"{X}-50000", "2g", f"{X}-50000 (2G)"),
            (f"{X}-01 (2G)_capa.json", f"{X}-01", "2g", f"{X}-01 (2G)"),
            (f"{X} (2G).txt", X, "2g", f"{X} (2G)"),
            (f"{X} (2).pdf", X, "1g", X),
            (f"{X} - 2ª Vara.pdf", X, "1g", X),
            (f"{X}-01 (2).pdf", f"{X}-01", "1g", f"{X}-01"),
            (f"Minuta {X} (2G) - acórdão.docx", X, "2g", f"{X} (2G)"),
            # um nome vale pelo que diz: sem o sufixo, 1º grau - também o HC e o /50000
            (f"{H}.pdf", H, "1g", H),
            (f"{X}-50000.pdf", f"{X}-50000", "1g", f"{X}-50000"),
        )
        for texto, processo, grau, autos in casos:
            with self.subTest(texto=texto):
                self.assertEqual(cnj.ler_nome_arquivo(texto).nome_arquivo, processo)
                self.assertEqual(cnj.grau_do_nome(texto), grau)
                self.assertEqual(cnj.chave_dos_autos(texto), autos)
                # a chave dos autos é ela mesma uma chave dos autos (ida e volta)
                self.assertEqual(cnj.chave_dos_autos(autos), autos)
                self.assertEqual(cnj.grau_do_nome(autos), grau)
                # e a chave do processo de uma chave dos autos é a do processo
                self.assertEqual(cnj.ler_nome_arquivo(autos).nome_arquivo, processo)
                if grau == "1g":       # no 1º grau, as duas chaves são a mesma
                    self.assertEqual(autos, processo)

    def test_chave_dos_autos_de_um_numero(self):
        # um Numero não traz nome: o grau é o que o número diz, e 1g no resto
        casos = ((A, A), (I, f"{A}-01"), (H, f"{H} (2G)"), (PL, f"{PL} (2G)"),
                 (E, f"{P}-50000 (2G)"), (P, P))
        for texto, esperado in casos:
            with self.subTest(numero=texto):
                self.assertEqual(cnj.chave_dos_autos(cnj.ler(texto)), esperado)

    def test_sem_numero(self):
        for texto in ("", None, "INDICE", "Minuta - acórdão.docx"):
            with self.subTest(texto=texto):
                with self.assertRaises(cnj.NumeroInvalido):
                    cnj.grau_do_nome(texto)
                with self.assertRaises(cnj.NumeroInvalido):
                    cnj.chave_dos_autos(texto)


class TestDicaDeGrau(unittest.TestCase):
    """As frases de troca de grau (§1.5): uma só fonte, que cita entre aspas
    curvas os rótulos da tela (§5.4: o segmentado “Grau” das Opções do lote)."""

    def test_constantes(self):
        self.assertEqual(modelos.DICA_GRAU_2G,
                         "escolha “2º grau” em “Grau”, nas Opções do lote (na linha de comando, "
                         "--grau 2g)")
        self.assertEqual(modelos.DICA_GRAU_1G,
                         "escolha “1º grau” em “Grau”, nas Opções do lote (na linha de comando, "
                         "--grau 1g)")

    def test_exemplos(self):
        no_1g = "se o processo estiver no 2º grau, " + modelos.DICA_GRAU_2G
        subiu = "se o recurso ainda não subiu, os autos estão no 1º grau: " + modelos.DICA_GRAU_1G
        sem_efeito = "trocar o grau do lote não muda a busca"
        casos = (
            (A, "1g", no_1g), (I, "1g", no_1g), (H, "1g", no_1g), (PL, "1g", no_1g),
            (E, "1g", no_1g),
            (A, "2g", subiu), (I, "2g", subiu), (A2, "2g", subiu),
            (H, "2g", "o processo originário do tribunal (órgão 0000) só existe no 2º grau: "
                      + sem_efeito),
            (PL, "2g", "o órgão 9002 (plantão do 2º grau ou turma recursal) só é procurado no "
                       "2º grau: " + sem_efeito),
            (E, "2g", "o recurso interno do 2º grau (/50000) só existe no 2º grau: " + sem_efeito),
            (E2, "2g", "o recurso interno do 2º grau (/50001) só existe no 2º grau: "
                       + sem_efeito),
        )
        for texto, grau, esperado in casos:
            with self.subTest(numero=texto, grau=grau):
                self.assertEqual(modelos.dica_de_grau(texto, grau), esperado)
                self.assertEqual(modelos.dica_de_grau(cnj.ler(texto), grau), esperado)

    def test_tribunal_sem_o_2o_grau_nao_manda_escolher_o_2o_grau(self):
        # o e-SAJ do TJSP e o do TJAM não têm o 2º grau no Helestron: a opção
        # “2º grau” daria “não suportado” (a dica manda ao portal do tribunal)
        self.assertEqual(modelos.dica_de_grau(A, "1g", com_o_2o_grau=False),
                         modelos.DICA_SEM_2G)
        self.assertNotIn("“", modelos.DICA_SEM_2G)
        self.assertEqual(modelos.dica_de_grau(A, "2g", com_o_2o_grau=False),
                         modelos.dica_de_grau(A, "2g"))
        for sigla, tem in (("TJAL", True), ("TJRS", True), ("TRF4", True), ("TJSP", False),
                           ("TJAM", False), ("TJAC", False)):
            with self.subTest(sigla=sigla):
                t = tribunais.por_sigla(sigla)
                self.assertEqual(tribunais.baixa_o_2o_grau(t), tem)
                if t.alternativo is not None:
                    # o eProc do TJSP tem o 2º grau no catálogo, mas o principal não
                    self.assertEqual(tribunais.baixa_o_2o_grau(t.alternativo), tem)
                if tem:
                    self.assertTrue(tribunais.baixa_o_2o_grau(t.no_grau("2g")))

    def test_grau_e_numero_em_qualquer_forma(self):
        self.assertEqual(modelos.dica_de_grau(A, "2"), modelos.dica_de_grau(A, "2g"))
        self.assertEqual(modelos.dica_de_grau(A, ""), modelos.dica_de_grau(A, "1g"))
        self.assertEqual(modelos.dica_de_grau(H, "2º grau"), modelos.dica_de_grau(H, "2g"))
        # o número pode vir de um nome de arquivo; sem número, a dica geral
        self.assertEqual(modelos.dica_de_grau(f"{H} (2G).pdf", "2g"),
                         modelos.dica_de_grau(H, "2g"))
        self.assertIn(modelos.DICA_GRAU_1G, modelos.dica_de_grau("sem número", "2g"))
        self.assertIn(modelos.DICA_GRAU_1G, modelos.dica_de_grau(None, "2g"))

    def test_cabe_na_frase_de_nao_encontrado(self):
        frases = [modelos.DICA_GRAU_2G, modelos.DICA_GRAU_1G]
        frases += [modelos.dica_de_grau(n, g) for n in (A, I, H, PL, E) for g in cnj.GRAUS]
        for frase in frases:
            with self.subTest(frase=frase):
                detalhe = f"não encontrado no e-SAJ do TJAL (2º grau). Confira o número; {frase}."
                self.assertNotIn("..", detalhe)
                self.assertFalse(frase.endswith("."))
                self.assertEqual(frase, frase.strip())
                # sem aspas retas e sem "(s)"; aspas curvas só em volta de
                # rótulo da tela (os de ROTULOS_CITADOS, conferidos contra a
                # interface por test_download_motor.TestRotulosCitados)
                for marca in ('"', "(s)"):
                    self.assertNotIn(marca, frase)
                for citado in re.findall(r"“([^”]+)”", frase):
                    self.assertIn(citado, modelos.ROTULOS_CITADOS)
        for rotulo in ("Grau", "1º grau", "2º grau"):
            self.assertIn(rotulo, modelos.ROTULOS_CITADOS)
            self.assertIn(f"“{rotulo}”", modelos.DICA_GRAU_2G + modelos.DICA_GRAU_1G)


class TestSigiloNosDoisGraus(unittest.TestCase):
    """§1.2: o sigilo é do processo e vale para os autos dos dois graus."""

    def test_contem_com_a_chave_dos_autos(self):
        Xi = f"{X}-01"
        Xe = f"{X}-50000"
        for tipo in (set, frozenset, sigilo.Sigilosas, list):
            with self.subTest(tipo=tipo.__name__):
                self.assertTrue(sigilo.contem(tipo({X}), f"{X} (2G)"))
                self.assertTrue(sigilo.contem(tipo({X}), X))
                self.assertTrue(sigilo.contem(tipo({Xi}), f"{Xi} (2G)"))
                self.assertTrue(sigilo.contem(tipo({X}), f"{Xi} (2G)"))
                self.assertTrue(sigilo.contem(tipo({X}), f"{Xe} (2G)"))   # herda do principal
                self.assertTrue(sigilo.contem(tipo({X}), Xe))
                self.assertTrue(sigilo.contem(tipo({X}), cnj.ler(f"{X}/50000")))
                self.assertTrue(sigilo.contem(tipo({X}), f"{X} (2G).pdf"))
                self.assertTrue(sigilo.contem(tipo({X}), f"{X} (2G)_capa.json"))
                self.assertTrue(sigilo.contem(tipo({X}), Path(f"{X} (2G).pdf")))
                # o principal não fica sigiloso por causa do recurso ou do incidente
                self.assertFalse(sigilo.contem(tipo({Xe}), f"{X} (2G)"))
                self.assertFalse(sigilo.contem(tipo({Xi}), f"{X} (2G)"))
                self.assertFalse(sigilo.contem(tipo({Xe}), X))
                # outro processo
                self.assertFalse(sigilo.contem(tipo({X}), f"{A} (2G)"))
                self.assertFalse(sigilo.contem(tipo({X}), "INDICE"))
        self.assertFalse(sigilo.contem(set(), f"{X} (2G)"))
        self.assertFalse(sigilo.contem({X}, ""))
        self.assertFalse(sigilo.contem({X}, None))

    def test_sigilosas_in(self):
        s = sigilo.Sigilosas({X, f"{P}-50000"})
        self.assertIn(f"{X} (2G)", s)
        self.assertIn(f"{X}-01 (2G)", s)
        self.assertIn(f"{P}-50000 (2G)", s)
        self.assertNotIn(f"{P} (2G)", s)
        self.assertNotIn(P, s)
        self.assertIsInstance(s, frozenset)

    def test_nome_do_processo_ignora_o_grau(self):
        self.assertEqual(sigilo.nome_do_processo(f"{X} (2G).pdf"), X)
        self.assertEqual(sigilo.nome_do_processo(f"{P}-50000 (2G)"), f"{P}-50000")
        self.assertEqual(sigilo.principal(f"{P}-50000 (2G)"), P)
        self.assertEqual(sigilo.principal(f"{P}-50000"), P)


class _ComEnderecosLocais(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.arq = Path(self.dir.name) / "enderecos-locais.json"
        p = mock.patch.object(tribunais, "ARQUIVO_LOCAL", self.arq)
        p.start()
        self.addCleanup(p.stop)


class TestTribunalNoGrau(_ComEnderecosLocais):
    """§1.3: o grau viaja dentro do Tribunal."""

    def test_tjal_no_catalogo(self):
        t = tribunais.por_sigla("TJAL")
        self.assertEqual((t.portal, t.perfil, t.grau, t.tem_grau("2g"), t.tem_grau("1g")),
                         ("esaj:TJAL", "esaj-TJAL", "1g", True, True))
        self.assertEqual(t.portal_do_sistema, "esaj:TJAL")
        self.assertEqual(t.rotulo, "TJAL · e-SAJ")
        self.assertEqual(t.urls_para(), ["https://www2.tjal.jus.br"])
        self.assertEqual(t.url_para(), "https://www2.tjal.jus.br")
        self.assertEqual(t.urls_para(None, "2g"), ["https://www2.tjal.jus.br/cposg5"])
        alt = t.alternativo
        self.assertEqual((alt.portal, alt.perfil, alt.grau, alt.rotulo),
                         ("eproc:TJAL", "eproc-TJAL", "1g", "TJAL · eProc"))
        self.assertEqual(alt.urls_para(), ["https://eproc1g.tjal.jus.br/eproc/"])
        self.assertEqual(tribunais.descrever(cnj.ler(A)), "TJAL · e-SAJ ou eProc")

    def test_tjal_no_segundo_grau(self):
        t = tribunais.por_sigla("TJAL")
        t2 = t.no_grau("2g")
        self.assertEqual((t2.portal, t2.rotulo, t2.urls_para()),
                         ("esaj:TJAL", "TJAL · e-SAJ (2º grau)",
                          ["https://www2.tjal.jus.br/cposg5"]))
        # o e-SAJ do 2º grau usa o login, o cofre e o perfil do 1º
        self.assertEqual((t2.perfil, t2.grau, t2.portal_do_sistema),
                         ("esaj-TJAL", "2g", "esaj:TJAL"))
        self.assertEqual(t2.url_para(), "https://www2.tjal.jus.br/cposg5")
        self.assertEqual(t2.urls_para(None, "1g"), ["https://www2.tjal.jus.br"])
        self.assertEqual(t2.urls["base"], "https://www2.tjal.jus.br")
        alt = t2.alternativo
        self.assertEqual((alt.portal, alt.perfil, alt.urls_para()),
                         ("eproc2g:TJAL", "eproc2g-TJAL", ["https://eproc2g.tjal.jus.br/eproc/"]))
        self.assertEqual((alt.grau, alt.rotulo, alt.portal_do_sistema),
                         ("2g", "TJAL · eProc (2º grau)", "eproc:TJAL"))

    def test_no_grau_identidade_igualdade_e_volta(self):
        t = tribunais.por_sigla("TJAL")
        for grau in ("1g", "1", "", "xyz"):
            self.assertIs(t.no_grau(grau), t)
        t2 = t.no_grau("2g")
        self.assertIs(t2.no_grau("2g"), t2)
        self.assertEqual(t.no_grau("2"), t2)
        self.assertNotEqual(t2, t)                       # o grau entra na igualdade
        self.assertEqual(len({t, t2, t.no_grau("2g")}), 2)   # e no hash
        volta = t2.no_grau("1g")
        self.assertEqual(volta, t)
        self.assertEqual(volta.alternativo.portal, "eproc:TJAL")

    def test_outros_tribunais(self):
        sp = tribunais.por_sigla("TJSP")
        self.assertFalse(sp.tem_grau("2g"))       # e-SAJ sem cposg no catálogo
        self.assertEqual(sp.no_grau("2g").urls_para(), [])
        # o alternativo vai junto só se tiver o grau
        self.assertEqual(sp.no_grau("2g").alternativo.portal, "eproc2g:TJSP")
        am = tribunais.por_sigla("TJAM")
        self.assertFalse(am.tem_grau("2g"))
        self.assertIsNone(am.no_grau("2g").alternativo)
        trf4 = tribunais.por_sigla("TRF4")
        self.assertEqual(trf4.no_grau("2g").portal, "eproc2g:TRF4")
        self.assertEqual(trf4.no_grau("2g").perfil, "eproc2g-TRF4")
        self.assertTrue(trf4.tem_grau("2g"))
        n = cnj.ler("5001234-56.2023.4.04.7100")
        self.assertIn("jfrs", trf4.url_para(n))                      # 1º grau por seção
        self.assertIn("trf4", trf4.no_grau("2g").url_para(n))       # 2º grau do TRF
        self.assertFalse(tribunais.por_numero(cnj.ler("0001234-56.2023.8.05.0001"))
                         .tem_grau("1g"))       # não suportado

    def test_eproc_estrito_no_segundo_grau(self):
        so_1g = tribunais.Tribunal(chave="8.99", sigla="TJXX", nome="Teste", sistema="eproc",
                                   urls={"1g": "https://eproc1g.tjxx.jus.br/eproc/"})
        self.assertEqual(so_1g.urls_para(None, "2g"), [])
        self.assertEqual(so_1g.url_para(None, "2g"), "")
        self.assertFalse(so_1g.tem_grau("2g"))
        self.assertEqual(so_1g.no_grau("2g").urls_para(), [])
        self.assertEqual(so_1g.no_grau("2g").urls_para(cnj.ler(X)), [])
        # o 1º grau sem '1g' continua caindo no primeiro do catálogo (1.0.2)
        so_2g = tribunais.Tribunal(chave="8.99", sigla="TJXX", nome="Teste", sistema="eproc",
                                   urls={"2g": ["https://eproc2g.tjxx.jus.br/eproc/"]})
        self.assertEqual(so_2g.urls_para(), ["https://eproc2g.tjxx.jus.br/eproc/"])
        self.assertTrue(so_2g.tem_grau("1g"))
        esaj = tribunais.Tribunal(chave="8.99", sigla="TJXX", nome="Teste", sistema="esaj",
                                  urls={"base": "https://esaj.tjxx.jus.br"})
        self.assertEqual(esaj.urls_para(None, "2g"), [])
        self.assertFalse(esaj.tem_grau("2g"))
        self.assertTrue(esaj.tem_grau("1g"))

    def test_por_portal_e_perfis(self):
        self.assertEqual(tribunais.PREFIXO_EPROC_2G, "eproc2g")
        for portal in ("esaj:TJAL", "eproc:TJAL", "eproc2g:TJAL", "eproc2g:TRF4"):
            self.assertTrue(tribunais.RE_PORTAL.match(portal), portal)
        for portal in ("eproc3g:TJAL", "esaj2g:TJAL", "eproc:TJAL:2g", "eproc2g:../x",
                       "esaj:../../x", "eproc2g:", ""):
            self.assertIsNone(tribunais.RE_PORTAL.match(portal), portal)
        e = tribunais.por_portal("esaj:TJAL")
        self.assertEqual((e.portal, e.grau, e.sistema), ("esaj:TJAL", "1g", "esaj"))
        p1 = tribunais.por_portal("eproc:TJAL")
        self.assertEqual((p1.portal, p1.grau, p1.sistema), ("eproc:TJAL", "1g", "eproc"))
        p2 = tribunais.por_portal("eproc2g:TJAL")
        self.assertEqual((p2.portal, p2.grau, p2.rotulo, p2.urls_para()),
                         ("eproc2g:TJAL", "2g", "TJAL · eProc (2º grau)",
                          ["https://eproc2g.tjal.jus.br/eproc/"]))
        self.assertEqual(tribunais.por_portal(" eproc2g:tjal ").portal, "eproc2g:TJAL")
        self.assertEqual(tribunais.por_portal("eproc2g:TRF4").portal, "eproc2g:TRF4")
        for portal in ("eproc2g:TJAM", "eproc:TJAM", "esaj:TJMG", "esaj:TJXX", "xx:TJAL",
                       "esaj:../x", "", None):
            self.assertIsNone(tribunais.por_portal(portal), portal)
        self.assertEqual(tribunais.nome_do_perfil("eproc2g:TJAL"), "eproc2g-TJAL")
        self.assertEqual(tribunais.nome_do_perfil("esaj:tjal"), "esaj-TJAL")
        self.assertEqual(tribunais.nome_do_perfil("eproc:TRF4"), "eproc-TRF4")
        self.assertEqual(tribunais.rotulo_do_grau("2g"), "2º grau")
        self.assertEqual(tribunais.rotulo_do_grau("1g"), "1º grau")

    def test_endereco_corrigido_do_segundo_grau(self):
        url = "https://eproc2g-novo.tjal.jus.br/eproc/"
        tribunais.definir_endereco("eproc2g:TJAL", "2g", url)
        self.assertEqual(json.loads(self.arq.read_text(encoding="utf-8")),
                         {"eproc:TJAL": {"2g": url}})
        t = tribunais.por_sigla("TJAL")
        self.assertEqual(t.no_grau("2g").alternativo.urls_para(), [url])
        self.assertEqual(tribunais.por_portal("eproc2g:TJAL").urls_para(), [url])
        # o 1º grau do eProc não muda
        self.assertEqual(t.alternativo.urls_para(), ["https://eproc1g.tjal.jus.br/eproc/"])
        linhas = {d["grau"]: d for d in tribunais.enderecos("eproc2g:TJAL")}
        self.assertEqual(linhas["2g"]["url"], url)
        self.assertTrue(linhas["2g"]["corrigido"])
        self.assertEqual(tribunais.enderecos("eproc2g:TJAL"), tribunais.enderecos("eproc:TJAL"))
        # o e-SAJ do 2º grau
        cposg = "https://www2.tjal.jus.br/cposg-novo"
        tribunais.definir_endereco("esaj:TJAL", "2g", cposg)
        t = tribunais.por_sigla("TJAL")
        self.assertEqual(t.no_grau("2g").urls_para(), [cposg])
        self.assertEqual(t.urls_para(), ["https://www2.tjal.jus.br"])
        # apagar a correção volta ao catálogo
        tribunais.definir_endereco("eproc2g:TJAL", "2g", "")
        tribunais.definir_endereco("esaj:TJAL", "2g", "")
        self.assertEqual(json.loads(self.arq.read_text(encoding="utf-8")), {})
        t = tribunais.por_sigla("TJAL")
        self.assertEqual(t.no_grau("2g").urls_para(), ["https://www2.tjal.jus.br/cposg5"])
        self.assertEqual(t.no_grau("2g").alternativo.urls_para(),
                         ["https://eproc2g.tjal.jus.br/eproc/"])

    def test_enderecos_do_esaj_listam_o_segundo_grau(self):
        self.assertEqual(tribunais.enderecos("esaj:TJAL"), [
            {"grau": "base", "rotulo": "Endereço do portal", "url": "https://www2.tjal.jus.br",
             "padrao": "https://www2.tjal.jus.br", "corrigido": False},
            {"grau": "2g", "rotulo": "2º grau", "url": "https://www2.tjal.jus.br/cposg5",
             "padrao": "https://www2.tjal.jus.br/cposg5", "corrigido": False}])


class TestCatalogo(unittest.TestCase):
    """§1.4: só o TJAL (e o _leia) mudam."""

    def setUp(self):
        self.texto = tribunais.ARQUIVO.read_text(encoding="utf-8")
        self.dados = json.loads(self.texto)

    def test_tjal(self):
        self.assertEqual(self.dados["versao"], 2)
        tjal = next(t for t in self.dados["tribunais"] if t["sigla"] == "TJAL")
        self.assertEqual(tjal["urls"], {"base": "https://www2.tjal.jus.br",
                                        "2g": "https://www2.tjal.jus.br/cposg5"})
        self.assertEqual(tjal["alternativo"]["urls"],
                         {"1g": ["https://eproc1g.tjal.jus.br/eproc/"],
                          "2g": ["https://eproc2g.tjal.jus.br/eproc/"]})
        self.assertNotIn("eproc.tjal.jus.br", self.texto)
        self.assertIn("no mesmo grau (1º ou 2º)", tjal["observacao"])
        self.assertIn("'2g'", self.dados["_leia"])

    def test_so_o_tjal_tem_o_segundo_grau_do_esaj(self):
        com_2g = [t["sigla"] for t in self.dados["tribunais"]
                  if t.get("sistema") == "esaj" and "2g" in (t.get("urls") or {})]
        self.assertEqual(com_2g, ["TJAL"])
        for t in tribunais.carregar():
            if t.suportado:
                self.assertTrue(t.url_para(), t.sigla)


class TestOpcoesEConfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.arq = Path(self.dir.name) / "config.ini"

    def test_esquema(self):
        chaves = [(s, c) for s, c, _, _ in config.ESQUEMA]
        i = chaves.index(("download", "grau"))
        self.assertEqual(chaves[i - 1], ("download", "salvar_diagnostico"))
        _, _, padrao, comentario = config.ESQUEMA[i]
        self.assertEqual(padrao, "1g")
        self.assertIn("--grau", comentario)
        # o que vai sempre ao 2º grau: a regra do número (cnj.grau_do_numero)
        for trecho in ("órgão 0000", "órgão começando por 9", "/50000"):
            self.assertIn(trecho, comentario)
        self.assertNotIn("(s)", comentario)
        self.assertIn("grau = 1g", config.modelo_ini())

    def test_de_config_le_o_grau(self):
        cfg = config.Config(self.arq)
        self.assertEqual(modelos.OpcoesDownload.de_config(cfg).grau, "1g")
        for valor, esperado in (("2", "2g"), ("2g", "2g"), ("2º grau", "2g"), ("1", "1g"),
                                ("xyz", "1g"), ("", "1g"), ("3", "1g")):
            with self.subTest(valor=valor):
                cfg.definir("download", "grau", valor)
                self.assertEqual(modelos.OpcoesDownload.de_config(cfg).grau, esperado)

    def test_config_da_versao_anterior_sem_o_grau(self):
        self.arq.write_text("[download]\npular_baixados = true\n", encoding="utf-8")
        cfg = config.Config(self.arq)
        self.assertEqual(modelos.OpcoesDownload.de_config(cfg).grau, "1g")

    def test_campos_novos_no_fim(self):
        self.assertEqual(dataclasses.fields(modelos.OpcoesDownload)[-1].name, "grau")
        self.assertEqual(dataclasses.fields(modelos.ResultadoProcesso)[-1].name, "grau")
        self.assertEqual(modelos.OpcoesDownload().grau, "1g")
        r = modelos.ResultadoProcesso(1, A, "TJAL", "esaj")
        self.assertEqual(r.grau, "1g")

    def test_absorver_nao_troca_o_grau(self):
        r = modelos.ResultadoProcesso(1, A, "TJAL", "esaj", grau="2g")
        outro = modelos.ResultadoProcesso(0, A, "TJAL", "eproc", situacao=modelos.OK,
                                          arquivo=f"{A} (2G).pdf", paginas=10)
        self.assertEqual(outro.grau, "1g")
        r.absorver(outro)
        self.assertEqual(r.grau, "2g")
        self.assertEqual((r.situacao, r.arquivo, r.paginas, r.sistema),
                         (modelos.OK, f"{A} (2G).pdf", 10, "eproc"))

    def test_versao(self):
        self.assertEqual(helestron.__version__, "1.1.0")


class TestPaginacaoGrau(unittest.TestCase):
    """§1.6: o grau só vai no manifesto do 2º grau; o do 1º, como na 1.0.2."""

    CAMPOS_ESAJ = ["formato", "programa", "sistema", "paginacao", "tribunal", "processo",
                   "ultima", "ausentes", "origem", "notas", "gerado_em"]
    CAMPOS_EPROC = ["formato", "programa", "sistema", "paginacao", "tribunal", "processo",
                    "modo", "documentos", "gerado_em"]

    def test_constantes(self):
        self.assertEqual(paginacao.SEGUNDO_GRAU, "2g")
        self.assertEqual(paginacao.FORMATO, 1)

    def test_esaj(self):
        m1 = paginacao.manifesto_esaj(A, 8, {6: "N", 7: "N", 8: "B"}, origem="servidor",
                                      tribunal="TJAL")
        self.assertEqual(list(m1), self.CAMPOS_ESAJ)        # 1º grau: o de sempre
        self.assertEqual(paginacao.manifesto_esaj(A, 8, {6: "N", 7: "N", 8: "B"},
                                                  origem="servidor", tribunal="TJAL",
                                                  grau="1g") | {"gerado_em": m1["gerado_em"]},
                         m1)
        self.assertEqual(paginacao.palavras_chave(m1),
                         "helestron;sistema=esaj;paginacao=folhas;formato=1;ultima=8;"
                         "ausentes=N:6-7|B:8")
        self.assertEqual(paginacao.grau(m1), "1g")
        m2 = paginacao.manifesto_esaj(f"{A} (2G)", 8, {6: "N", 7: "N", 8: "B"},
                                      origem="servidor", tribunal="TJAL", grau="2g")
        self.assertEqual(list(m2), self.CAMPOS_ESAJ + ["grau"])
        self.assertEqual(m2["grau"], "2g")
        self.assertEqual(paginacao.grau(m2), "2g")
        self.assertEqual(paginacao.palavras_chave(m2),
                         paginacao.palavras_chave(m1) + ";grau=2g")
        self.assertEqual(paginacao.resumo(m2), paginacao.resumo(m1))
        self.assertTrue(paginacao.valido(m2))

    def test_eproc(self):
        docs = [{"evento": 1, "rotulo": "INIC1", "situacao": "ok", "inicio": 1, "paginas": 2}]
        m1 = paginacao.manifesto_eproc(A, docs, tribunal="TJAL", capa={"x": 1})
        self.assertEqual(list(m1), self.CAMPOS_EPROC + ["capa"])
        self.assertEqual(paginacao.palavras_chave(m1),
                         "helestron;sistema=eproc;paginacao=documento;formato=1;modo=documentos")
        m2 = paginacao.manifesto_eproc(A, docs, tribunal="TJAL", grau="2g", capa={"x": 1})
        self.assertEqual(list(m2), self.CAMPOS_EPROC + ["grau", "capa"])
        self.assertEqual(paginacao.grau(m2), "2g")
        self.assertTrue(paginacao.palavras_chave(m2).endswith(";modo=documentos;grau=2g"))
        self.assertEqual(paginacao.resumo(m2), paginacao.resumo(m1))

    def test_grau_de_manifesto_qualquer(self):
        for m in (None, {}, {"grau": "1g"}, {"grau": "2"}, {"grau": None}, "2g", []):
            self.assertEqual(paginacao.grau(m), "1g", m)
        self.assertEqual(paginacao.grau({"grau": "2g"}), "2g")

    def test_ida_e_volta_no_pdf(self):
        try:
            import pymupdf
        except ImportError:  # pragma: no cover - PyMuPDF faz parte da instalação
            self.skipTest("sem PyMuPDF")
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / f"{A} (2G).pdf"
            doc = pymupdf.open()
            for i in range(3):
                doc.new_page().insert_text((72, 72), f"página {i + 1}")
            doc.save(str(arq))
            doc.close()
            m = paginacao.manifesto_esaj(A, 3, origem="servidor", tribunal="TJAL", grau="2g")
            with pymupdf.open(str(arq)) as doc:
                paginacao.gravar_no_doc(doc, m)
                doc.saveIncr()
            lido = paginacao.ler_do_pdf(arq)
            self.assertEqual(paginacao.grau(lido), "2g")
            with pymupdf.open(str(arq)) as doc:
                self.assertTrue(doc.metadata["keywords"].endswith(";grau=2g"))


if __name__ == "__main__":
    unittest.main()
