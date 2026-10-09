"""O 2º grau no compartilhamento: texto, índice, conector (MCP), pacote e espelho.

Os autos do 2º grau ("<número> (2G).pdf", manifesto com "grau": "2g") e os do
1º grau do mesmo número (a apelação sobe com o número da origem) são arquivos
distintos, com numeração própria. Antes, o acervo os juntava numa chave só
("o mais recente vence"): um dos dois sumia do índice e do conector, e o
texto do 2º grau gravado pelo "baixar --texto" era apagado no preparo
seguinte. E o "como citar" do 1º grau ("cite a folha carimbada") levaria a
IA a citar a folha da origem, carimbada na peça trazida à Pasta Digital do
2º grau, como folha do 2º grau.

Números do Anexo B do desenho (dígito verificador conferido).
"""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from helestron.compartilhar import chatgpt, mcp_servidor, nuvem, preparo, textos
from helestron.nucleo import cnj, config, paginacao, sigilo
from testes.test_compartilhar import _docx, _pdf

A = "0700001-93.2024.8.02.0058"          # apelação: o mesmo número nos dois graus
A2G = f"{A} (2G)"
S = "0700002-78.2024.8.02.0058"          # público no 1º grau, sigiloso no 2º
H = "0803061-28.2025.8.02.0000"          # HC originário (órgão 0000): só no 2º grau
P = "0706265-50.2017.8.02.0001"          # o principal dos embargos
E = f"{P}/50000"                         # embargos de declaração (recurso interno)
E2G = f"{P}-50000 (2G)"                  # a chave dos autos deles
CAB = textos.CABECA
QUANDO = 1_700_000_000                   # data fixa dos arquivos (o índice a mostra)

# O "como citar" do e-SAJ do 1º grau, como a 1.0.2 o grava: não muda.
COMO_CITAR_ESAJ_1_0_2 = (
    "[Como citar: \"fl. N\", pela marca [fl. N] que abre cada página. A folha marcada "
    "[folha não disponível no e-SAJ: …] não veio do e-SAJ (há só uma página de aviso no "
    "lugar): não a use como prova; diga que a folha não está disponível. Se a folha "
    "carimbada na própria página divergir da marca, cite a carimbada e avise o magistrado.]")


def _m_esaj(numero: str, ultima: int, grau: str = "1g", ausentes=None) -> dict:
    return paginacao.manifesto_esaj(numero, ultima, ausentes or {}, origem="servidor",
                                    tribunal="TJAL", grau=grau)


def _docs():
    return [{"evento": 1, "rotulo": "INIC1", "descricao": "PETIÇÃO INICIAL", "origem": "pdf",
             "situacao": "ok", "inicio": 1, "paginas": 2},
            {"evento": 3, "rotulo": "DESPADEC1", "descricao": "DECISÃO", "origem": "html",
             "situacao": "ok", "inicio": 3, "paginas": 1}]


def _datar(*arquivos: Path, quando: float = QUANDO) -> None:
    for p in arquivos:
        os.utime(p, (quando, quando))


class TestTexto2G(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_esaj_do_2g_primeira_linha_abertura_e_como_citar(self):
        pdf = _pdf(self.base / f"{A2G}.pdf", ["Apelação", "aviso", "Contrarrazões"],
                   manifesto=_m_esaj(A, 3, "2g", {2: "N"}))
        texto = textos.texto_pdf(pdf)
        self.assertEqual(texto.split("\n", 1)[0],
                         f"{CAB} | sistema=esaj | paginacao=folhas | paginas=3 | ausentes=2 | "
                         "grau=2g")
        cabeca = textos.preambulo(texto)
        self.assertIn(f"[Processo {A} — autos do e-SAJ do TJAL, 2º grau (Pasta Digital do "
                      "processo no Tribunal). A página N deste PDF é sempre a folha N destes "
                      "autos (fls. 1 a 3).]", cabeca)
        self.assertIn(textos.COMO_CITAR_ESAJ_2G, cabeca)
        self.assertNotIn(textos.COMO_CITAR_ESAJ, cabeca)
        self.assertNotIn("cite a carimbada", cabeca)
        # as marcas são as de sempre: a folha N é a da Pasta Digital do 2º grau
        self.assertIn("=== [fl. 1] ===\nApelação\n=== [fl. 2] ===\n[folha não disponível", texto)
        self.assertEqual(textos.buscar_citando(texto, "contrarrazoes")[0][0], "fl. 3")
        cab = textos.cabecalho(texto)
        self.assertEqual((cab["grau"], cab["sistema"], cab["ausentes"]), ("2g", "esaj", "2"))
        info = textos.info_do_texto(texto)
        self.assertEqual(info["grau"], "2g")
        self.assertEqual(textos.analisar(pdf)[1], info)
        destino = textos.garantir_texto(pdf, self.base / "_ia" / f"{A2G}.txt")
        self.assertEqual(textos.versao_do_texto(destino), textos.VERSAO_TEXTO)
        self.assertEqual(textos.analisar(destino)[1], info)

    def test_esaj_do_1g_byte_a_byte(self):
        """O texto do 1º grau é o da 1.0.2: nada a reextrair nem a reenviar."""
        pdf = _pdf(self.base / f"{A}.pdf", ["Petição inicial", "aviso",
                                             "Contestação: alega prescrição"],
                   manifesto=_m_esaj(A, 3, ausentes={2: "N"}))
        motivo = paginacao.MOTIVOS["N"]
        self.assertEqual(textos.texto_pdf(pdf), (
            f"{CAB} | sistema=esaj | paginacao=folhas | paginas=3 | ausentes=2\n"
            f"[Processo {A} — autos do e-SAJ do TJAL. A página N deste PDF é sempre a folha N "
            "dos autos (fls. 1 a 3).]\n"
            + COMO_CITAR_ESAJ_1_0_2 + "\n"
            f"[Folhas com página de aviso no lugar: 2 ({motivo}).]\n"
            "=== [fl. 1] ===\nPetição inicial\n"
            f"=== [fl. 2] ===\n[folha não disponível no e-SAJ: {motivo}]\n"
            "=== [fl. 3] ===\nContestação: alega prescrição\n"))
        self.assertEqual(textos.COMO_CITAR_ESAJ, COMO_CITAR_ESAJ_1_0_2)
        self.assertEqual(textos.cabecalho(textos.texto_pdf(pdf))["grau"], "1g")
        self.assertEqual(textos.analisar(pdf)[1]["grau"], "1g")

    def test_eproc_do_2g(self):
        pdf = _pdf(self.base / f"{H} (2G).pdf", ["impetração", "pedido liminar", "DECISÃO"],
                   manifesto=paginacao.manifesto_eproc(H, _docs(), tribunal="TJAL", grau="2g"))
        texto = textos.texto_pdf(pdf)
        self.assertEqual(texto.split("\n", 1)[0],
                         f"{CAB} | sistema=eproc | paginacao=documento | paginas=3 | ausentes= | "
                         "grau=2g")
        cabeca = textos.preambulo(texto)
        self.assertIn(f"[Processo {H} — autos do eProc do TJAL, 2º grau, documento a documento",
                      cabeca)
        self.assertIn(textos.COMO_CITAR_EPROC_2G, cabeca)
        self.assertIn("evento do processo de origem (1º grau) não está neste PDF: cite-o como "
                      "\"evento N, RÓTULO, do processo de origem\"", cabeca)
        self.assertIn("=== [evento 1, INIC1, p. 2] (pág. 2 do PDF) ===", texto)
        self.assertNotIn("[fl.", texto)                 # no eProc, nunca "fl."
        # o eProc do 1º grau continua o de sempre
        um = textos.texto_pdf(_pdf(self.base / "1g.pdf", ["a", "b", "c"],
                                   manifesto=paginacao.manifesto_eproc(H, _docs(),
                                                                       tribunal="TJAL")))
        self.assertNotIn("grau", um.split("\n", 1)[0])
        self.assertIn(textos.COMO_CITAR_EPROC + "\n", um)
        self.assertNotIn("2º grau", um)

    def test_eproc_completo_do_2g(self):
        m = paginacao.manifesto_eproc(H, [], modo="completo", tribunal="TJAL", grau="2g",
                                      partes=[{"inicio": 1, "paginas": 2}])
        texto = textos.texto_pdf(_pdf(self.base / "c.pdf", ["um", "dois"], manifesto=m))
        self.assertTrue(texto.split("\n", 1)[0].endswith(" | grau=2g"))
        self.assertIn("arquivo completo gerado pelo próprio eProc do TJAL, 2º grau", texto)
        self.assertIn(textos.EVENTOS_DO_2G, textos.preambulo(texto))

    def test_sem_manifesto_o_grau_vem_do_nome(self):
        texto = textos.texto_pdf(_pdf(self.base / f"{A2G}.pdf", ["peça sem manifesto"]))
        self.assertEqual(texto.split("\n", 1)[0],
                         f"{CAB} | sistema=desconhecido | paginacao=nao_garantida | paginas=1 | "
                         "ausentes= | grau=2g")
        # a "folha carimbada" pode ser a dos autos de origem: não se manda citá-la
        cabeca = textos.preambulo(texto)
        self.assertIn(textos.COMO_CITAR_NAO_GARANTIDA_2G, cabeca)
        self.assertNotIn(textos.COMO_CITAR_NAO_GARANTIDA, cabeca)
        self.assertNotIn("Cite a folha carimbada", cabeca)
        for nome in (f"{A}.pdf", f"{A} (2).pdf", "sem numero.pdf"):
            with self.subTest(nome=nome):
                texto = textos.texto_pdf(_pdf(self.base / nome, ["peça"]))
                self.assertNotIn("grau", texto.split("\n", 1)[0])
                self.assertIn(textos.COMO_CITAR_NAO_GARANTIDA, texto)
        # o manifesto vale mais que o nome (arquivo renomeado à mão)
        texto = textos.texto_pdf(_pdf(self.base / "renomeado.pdf", ["x"],
                                      manifesto=_m_esaj(A, 1, "2g")))
        self.assertTrue(texto.split("\n", 1)[0].endswith(" | grau=2g"))
        self.assertEqual(textos.grau_dos_autos(_m_esaj(A, 1), f"{A2G}.pdf"), "1g")
        self.assertEqual(textos.grau_dos_autos(None, f"{A2G}.pdf"), "2g")
        self.assertEqual(textos.grau_dos_autos(None, f"{E2G}_capa.json"), "2g")

    def test_alterado_depois_do_download_no_2g(self):
        with self.assertLogs("helestron.compartilhar.textos", "WARNING"):
            texto = textos.texto_pdf(_pdf(self.base / f"{A2G}.pdf", ["um", "dois"],
                                          manifesto=_m_esaj(A, 3, "2g")))
        self.assertIn("paginacao=nao_garantida", texto.split("\n", 1)[0])
        self.assertIn("autos do e-SAJ do TJAL, 2º grau: o manifesto de paginação diz 3 folhas",
                      texto)
        self.assertIn(textos.COMO_CITAR_NAO_GARANTIDA_2G, textos.preambulo(texto))
        self.assertNotIn("Cite a folha carimbada", textos.preambulo(texto))
        # o eProc do 2º grau alterado: a regra do eProc (nunca "fl.") e os eventos do 2º grau
        with self.assertLogs("helestron.compartilhar.textos", "WARNING"):
            texto = textos.texto_pdf(_pdf(self.base / f"{H} (2G).pdf", ["um"],
                                          manifesto=paginacao.manifesto_eproc(
                                              H, _docs(), tribunal="TJAL", grau="2g")))
        cabeca = textos.preambulo(texto)
        self.assertIn(textos.COMO_CITAR_EPROC_NAO_GARANTIDA_2G, cabeca)
        self.assertIn("autos do eProc do TJAL, 2º grau: o manifesto de paginação descreve",
                      cabeca)
        self.assertNotIn("folha carimbada", cabeca)

    def test_como_citar_do_2g_nao_manda_citar_o_carimbo(self):
        """No 2º grau, a apelação tem o mesmo número dos autos de origem: o
        carimbo "fls. 120" da origem numa página marcada [fl. 735] não se
        distingue pelo número, e "cite a carimbada" levaria a IA a citar a
        folha da origem como folha do 2º grau."""
        self.assertNotIn("folha carimbada", textos.COMO_CITAR_NAO_GARANTIDA_2G)
        regra = textos.COMO_CITAR_ESAJ_2G
        self.assertNotIn("cite-o", regra)
        self.assertNotIn("cite a carimbada", regra)
        self.assertIn("autos de origem, que têm o mesmo número", regra)
        self.assertIn("nunca o cite como folha destes autos", regra)
        self.assertIn("fl. N dos autos de origem", regra)
        self.assertIn("Pasta Digital do 2º grau", regra)
        self.assertNotIn("\n", regra)
        self.assertTrue(regra.startswith("[Como citar:") and regra.endswith("]"))

    def test_cabecalho_sem_formato_2(self):
        self.assertEqual(textos.cabecalho("texto qualquer"), {})
        self.assertEqual(textos.info_do_texto("texto qualquer")["grau"], "1g")
        cab = textos.cabecalho(f"{CAB} | sistema=esaj | paginacao=folhas | paginas=1 | ausentes=")
        self.assertEqual(cab["grau"], "1g")


class Base2G(unittest.TestCase):
    """Acervo com os autos do 1º e do 2º grau da apelação A, os embargos E
    (só no 2º grau) e a transcrição da audiência de A."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.raiz = self.base / "Acervo"
        self.lote1 = self.raiz / "Processos" / "Lote 1G"
        self.lote2 = self.raiz / "Processos" / "Lote 2G"
        self.pdf_1g = _pdf(self.lote1 / f"{A}.pdf",
                           ["Petição inicial", "Contestação: alega prescrição", "Sentença"],
                           manifesto=_m_esaj(A, 3))
        self.pdf_2g = _pdf(self.lote2 / f"{A2G}.pdf",
                           ["Apelação: alega prescrição", "Contrarrazões"],
                           manifesto=_m_esaj(A, 2, "2g"))
        self.pdf_e = _pdf(self.lote2 / f"{E2G}.pdf", ["Embargos de declaração: omissão"],
                          manifesto=_m_esaj(E, 1, "2g"))
        self.docx = _docx(self.raiz / "Transcricoes" / f"{A}.docx",
                          ["TESTEMUNHA [00:01:02] — não houve prescrição"])
        _datar(self.pdf_1g, self.pdf_2g, self.pdf_e, self.docx)

    def acervo(self) -> mcp_servidor.Acervo:
        return mcp_servidor.Acervo(self.raiz, sigilosos=None, pauta=None)


class TestAcervo2G(Base2G):
    def test_os_dois_graus_sao_autos_distintos(self):
        ac = self.acervo()
        self.assertEqual(set(ac.pdfs()), {A, A2G, E2G})
        self.assertEqual(ac.pdfs()[A], self.pdf_1g)
        self.assertEqual(ac.pdfs()[A2G], self.pdf_2g)
        # numerados e transcrições continuam pela chave do PROCESSO (sigilo, pauta)
        self.assertEqual(sorted(k for k, _p in ac.numerados(".pdf")),
                         sorted([A, A, f"{P}-50000"]))
        self.assertEqual(set(ac.transcricoes()), {A})

    def test_o_mais_recente_vence_so_entre_os_mesmos_autos(self):
        copia = _pdf(self.raiz / "Processos" / "Lote 3" / f"{A2G}.pdf", ["Apelação de novo"],
                     manifesto=_m_esaj(A, 1, "2g"))
        _datar(copia, quando=QUANDO + 100)
        ac = self.acervo()
        self.assertEqual(ac.pdfs()[A2G], copia)
        self.assertEqual(ac.pdfs()[A], self.pdf_1g)      # o 1º grau não é tocado
        self.assertEqual(preparo.contar_processos(ac.pdfs()), 2)


class TestIndice2G(Base2G):
    def test_indice_com_uma_linha_por_grau(self):
        rel = preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=True)
        self.assertEqual((rel.processos, rel.transcricoes, rel.textos_novos), (2, 1, 3))
        indice = (self.raiz / "INDICE.md").read_text(encoding="utf-8")
        self.assertIn("| Processo | Tribunal | Sistema | Páginas | Paginação | Ausentes | Grau | "
                      "Lote | Autos | Texto | Transcrições |", indice)
        self.assertIn("|---|---|---|---:|---|---|---|---|---|---|---|", indice)
        self.assertIn("2 processos e 1 transcrição.", indice)
        self.assertIn(preparo.FRASE_DO_2G, indice)
        linhas = [l for l in indice.splitlines() if l.startswith("| 07")]
        self.assertEqual([l.split(" | ")[0][2:] for l in linhas], [A, A2G, E2G])
        um, dois, embargos = linhas
        self.assertIn("| e-SAJ | 3 | página N = folha N (fls. 1 a 3) | — | 1º grau | Lote 1G |",
                      um)
        self.assertIn("| e-SAJ | 2 | página N = folha N (fls. 1 a 2) | — | 2º grau | Lote 2G |",
                      dois)
        self.assertIn("| 2º grau | Lote 2G |", embargos)
        self.assertIn("[texto](_ia/texto/0700001-93.2024.8.02.0058%20(2G).txt)", dois)
        self.assertIn("[PDF](Processos/Lote%202G/0700001-93.2024.8.02.0058%20(2G).pdf)", dois)
        # a transcrição é do processo: aparece na linha de cada grau dele
        for linha in (um, dois):
            self.assertIn(f"[{A}.docx](Transcricoes/{A}.docx)", linha)
        self.assertTrue(embargos.endswith("| — |"))
        self.assertNotIn("sem autos no acervo", indice)
        # um texto por autos, cada um com o seu grau
        texto = self.raiz / "_ia" / "texto"
        self.assertEqual(sorted(p.name for p in texto.glob("*.txt")),
                         sorted([f"{A}.txt", f"{A2G}.txt", f"{E2G}.txt"]))
        self.assertTrue((texto / f"{A2G}.txt").read_text(encoding="utf-8")
                        .split("\n", 1)[0].endswith(" | grau=2g"))
        self.assertNotIn("grau", (texto / f"{A}.txt").read_text(encoding="utf-8")
                         .split("\n", 1)[0])

    def test_acervo_so_do_1g_ganha_so_a_coluna(self):
        for p in (self.pdf_2g, self.pdf_e):
            p.unlink()
        preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        indice = (self.raiz / "INDICE.md").read_text(encoding="utf-8")
        self.assertNotIn(preparo.FRASE_DO_2G, indice)
        self.assertNotIn("(2G)", indice)
        linha = next(l for l in indice.splitlines() if l.startswith(f"| {A} |"))
        self.assertIn("| — | 1º grau | Lote 1G |", linha)

    def test_texto_do_2g_gravado_pelo_baixar_nao_e_orfao(self):
        """Achado: o texto "X (2G).txt" que o baixar --texto grava (pelo nome
        do PDF) era apagado no preparo seguinte, e o campo "texto" do JSON da
        skill apontava para um arquivo que sumiu."""
        cache = self.raiz / "_ia" / "texto"
        feito = textos.garantir_texto(self.pdf_2g, cache / f"{A2G}.txt")
        orfao = cache / f"{H} (2G).txt"
        orfao.write_text("autos que saíram do acervo", encoding="utf-8")
        preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        self.assertTrue(feito.exists())
        self.assertFalse(orfao.exists())

    def test_transcricao_sem_autos_pela_chave_do_processo(self):
        _docx(self.raiz / "Transcricoes" / f"{H}.docx", ["AUDIÊNCIA"])
        _docx(self.raiz / "Transcricoes" / f"{P}.docx", ["AUDIÊNCIA DO PRINCIPAL"])
        preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        indice = (self.raiz / "INDICE.md").read_text(encoding="utf-8")
        sem_autos = indice.split("## Transcrições de processos sem autos no acervo", 1)[1]
        self.assertIn(f"- {H}: [{H}.docx]", sem_autos)
        # o principal dos embargos não tem autos no acervo (os embargos são outro processo)
        self.assertIn(f"- {P}: [{P}.docx]", sem_autos)
        self.assertNotIn(f"- {A}:", sem_autos)

    def test_grau_do_manifesto_diferente_do_nome_e_avisado(self):
        renomeado = _pdf(self.lote1 / f"{H}.pdf", ["HC"], manifesto=_m_esaj(H, 1, "2g"))
        _datar(renomeado)
        preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        indice = (self.raiz / "INDICE.md").read_text(encoding="utf-8")
        linha = next(l for l in indice.splitlines() if l.startswith(f"| {H} |"))
        self.assertIn("| 2º grau (pelo manifesto do PDF; o nome do arquivo diz 1º grau) |", linha)


class TestModelos2G(Base2G):
    def _antigo(self, molde: str, versao: str = "1.0.2") -> str:
        return molde.format(nome="Helestron", versao=versao, unidade="", quando="04/10/2026",
                            regra_sigilo=preparo.REGRA_SIGILO_SEPARADOS)

    def test_modelo_da_1_0_2_reconhecido_e_regravado(self):
        (self.raiz / "CLAUDE.md").write_text(self._antigo(preparo.CONTEXTO_1_0_2),
                                             encoding="utf-8")
        # o AGENTS.md salvo com CRLF por um editor do Windows
        (self.raiz / "AGENTS.md").write_bytes(
            self._antigo(preparo.CONTEXTO_1_0_2).replace("\n", "\r\n").encode("utf-8"))
        skill = self.raiz / ".claude" / "skills" / "acervo-judicial" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(preparo.SKILL_1_0_2, encoding="utf-8")
        rel = preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        for arq in (self.raiz / "CLAUDE.md", self.raiz / "AGENTS.md", skill):
            self.assertIn(arq, rel.arquivos)
            texto = arq.read_text(encoding="utf-8")
            self.assertIn("(2G)", texto, arq.name)
            self.assertIn("fl. N dos autos de origem", texto, arq.name)
        self.assertEqual(skill.read_text(encoding="utf-8"), preparo.SKILL)
        self.assertFalse([a for a in rel.avisos if "editad" in a], rel.avisos)

    def test_modelos_da_1_0_2_congelados_e_o_novo_com_o_2g(self):
        self.assertIn(preparo.CONTEXTO_1_0_2, preparo.MODELOS_CONTEXTO_ANTERIORES)
        self.assertIn(preparo.CONTEXTO_1_0_1, preparo.MODELOS_CONTEXTO_ANTERIORES)
        self.assertEqual(preparo.MODELOS_SKILL_ANTERIORES,
                         (preparo.SKILL_1_0_2, preparo.SKILL_1_0_1))
        self.assertNotIn("(2G)", preparo.CONTEXTO_1_0_2)
        self.assertNotIn("(2G)", preparo.SKILL_1_0_2)
        for nome, texto in (("CONTEXTO", preparo.CONTEXTO), ("SKILL", preparo.SKILL),
                            ("conector", mcp_servidor.INSTRUCOES)):
            with self.subTest(nome):
                plano = " ".join(texto.split())
                self.assertIn("(2G)", plano)
                self.assertIn("fl. N dos autos de origem", plano)
                self.assertIn("pág. M do PDF", plano)
        plano = " ".join(preparo.CONTEXTO.split())
        self.assertIn("`Processos/<lote>/<número CNJ> (2G).pdf`", plano)
        self.assertIn("`-50000`", plano)
        self.assertIn("**não o cite** como folha destes", plano)
        # a regra do carimbo do 1º grau continua, só para o 1º grau
        self.assertIn("Nos autos do 1º grau, se a folha carimbada", plano)
        # a habilidade continua com o cabeçalho que o Claude Code lê
        self.assertTrue(preparo.SKILL.startswith("---\nname: acervo-judicial\ndescription: "))
        descricao = preparo.SKILL.split("\n")[2]
        self.assertNotIn(": ", descricao[len("description: "):])     # YAML simples

    def test_marca_da_regra_nova(self):
        self.assertEqual(preparo._MARCA_REGRA_NOVA, ("pág. M do PDF", "(2G)"))
        skill = self.raiz / ".claude" / "skills" / "acervo-judicial" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        # editado com a regra da 1.0.2 e sem a do 2º grau: avisa
        (self.raiz / "CLAUDE.md").write_text("# Minhas regras\n\nNunca cite a pág. M do PDF.\n",
                                             encoding="utf-8")
        skill.write_text("# minha habilidade com pág. M do PDF\n", encoding="utf-8")
        rel = preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        aviso = next(a for a in rel.avisos if "CLAUDE.md foi editado" in a)
        self.assertIn("pág. M do PDF", aviso)
        self.assertIn("(2G)", aviso)
        self.assertTrue(any("SKILL.md foi editada" in a for a in rel.avisos), rel.avisos)
        # com as duas: não avisa
        (self.raiz / "CLAUDE.md").write_text(
            "# Minhas regras\n\nNunca cite a pág. M do PDF; os autos (2G) são outros.\n",
            encoding="utf-8")
        skill.write_text("# minha: pág. M do PDF e (2G)\n", encoding="utf-8")
        rel = preparo.atualizar_contexto(raiz=self.raiz, extrair_texto=False)
        self.assertFalse([a for a in rel.avisos if "CLAUDE.md foi editado" in a], rel.avisos)
        self.assertFalse([a for a in rel.avisos if "SKILL.md foi editada" in a], rel.avisos)

    def test_nao_garantida_nos_modelos_com_a_excecao_do_2g(self):
        """Achado C4: o item de paginacao=nao_garantida do CLAUDE.md/AGENTS.md,
        da habilidade e das instruções do conector mandava "citar a folha
        carimbada" sem excetuar os autos do 2º grau, onde o carimbo pode ser o
        dos autos de origem, de mesmo número - o contrário do que o texto
        gravado (COMO_CITAR_NAO_GARANTIDA_2G) e o cabeçalho do ler_processo dizem."""
        excecao = ("nos autos do 2º grau, não cite o carimbo: pode ser o dos autos de origem; "
                   "cite o documento e avise o magistrado")
        for nome, texto in (("CONTEXTO", preparo.CONTEXTO), ("SKILL", preparo.SKILL),
                            ("conector", mcp_servidor.INSTRUCOES)):
            with self.subTest(nome):
                plano = " ".join(texto.replace("*", "").split())
                item = plano[plano.index("paginacao=nao_garantida"):]
                item = item[:item.index(". ") + 1]          # só o item da nao_garantida
                self.assertIn("cite a folha carimbada", item)   # a regra geral continua
                self.assertIn(excecao, item)
        # a mesma regra do texto gravado nos autos do 2º grau
        self.assertIn("não o cite como folha destes autos; cite o documento",
                      textos.COMO_CITAR_NAO_GARANTIDA_2G)
        self.assertIn("avise o magistrado", textos.COMO_CITAR_NAO_GARANTIDA_2G)
        # os modelos congelados não mudam
        for nome, texto in (("CONTEXTO_1_0_2", preparo.CONTEXTO_1_0_2),
                            ("SKILL_1_0_2", preparo.SKILL_1_0_2),
                            ("CONTEXTO_1_0_1", preparo.CONTEXTO_1_0_1),
                            ("SKILL_1_0_1", preparo.SKILL_1_0_1)):
            with self.subTest(nome):
                self.assertNotIn("não cite o carimbo", texto)
                self.assertNotIn("(2G)", texto)


class TestConector2G(Base2G):
    def test_listar_acervo(self):
        lista = self.acervo().listar_acervo()
        self.assertIn("Autos (3):", lista)
        self.assertIn(f"\n- {A} — 3 pág. — Processos/Lote 1G/{A}.pdf — página N = folha N "
                      "(fls. 1 a 3)\n", lista)
        self.assertIn(f"\n- {A2G} — 2º grau — 2 pág. — Processos/Lote 2G/{A2G}.pdf — página N = "
                      "folha N (fls. 1 a 2)\n", lista)
        self.assertIn(f"\n- {E2G} — 2º grau — 1 pág. —", lista)

    def test_ler_sem_grau_com_os_dois_graus_pergunta(self):
        ac = self.acervo()
        with self.assertRaises(ValueError) as erro:
            ac.ler_processo(A)
        self.assertEqual(str(erro.exception),
                         f"o processo {A} tem autos dos dois graus no acervo ({A} e {A2G}): "
                         f"informe grau=\"1g\" ou grau=\"2g\" (ou peça \"{A} (1º grau)\" ou "
                         f"\"{A2G}\")")
        # as duas formas que a frase sugere escolhem os autos de um grau
        self.assertIn("e-SAJ, 2º grau", ac.ler_processo(A2G))
        self.assertIn("(1º grau — autos de origem", ac.ler_processo(f"{A} (1º grau)"))

    def test_ler_o_2g(self):
        ac = self.acervo()
        for pedido in ({"numero": A, "grau": "2g"}, {"numero": A2G}, {"numero": A, "grau": "2"},
                       {"numero": f"{A} (2º grau)"}):
            with self.subTest(**pedido):
                texto = ac.ler_processo(**pedido)
                self.assertTrue(texto.startswith(
                    f"Processo {A} — e-SAJ, 2º grau: 2 páginas no PDF. Página N = folha N (da "
                    "Pasta Digital do 2º grau); carimbo \"fls.\" diferente da marca é de outros "
                    "autos (inclusive dos de origem, de mesmo número): não o cite como folha "
                    "destes. Mostrando as fls. 1 a 2.\n"), texto[:400])
                self.assertIn("Apelação: alega prescrição", texto)
                self.assertNotIn("Sentença", texto)
                self.assertIn(textos.COMO_CITAR_ESAJ_2G, texto)

    def test_ler_o_1g_diz_que_sao_os_autos_de_origem(self):
        ac = self.acervo()
        for pedido in ({"numero": A, "grau": "1g"}, {"numero": f"{A} (1º grau)"}):
            with self.subTest(**pedido):
                texto = ac.ler_processo(**pedido, folha_inicial=2, folha_final=2)
                self.assertTrue(texto.startswith(
                    f"Processo {A} (1º grau — autos de origem do {A2G}) — e-SAJ: 3 páginas no "
                    "PDF. Página N = folha N. Quem redige no 2º grau cita estas folhas como "
                    "\"fl. N dos autos de origem\". Mostrando as fls. 2 a 2.\n"), texto[:400])
                self.assertIn("Contestação", texto)
                self.assertNotIn("Apelação", texto)

    def test_ler_por_numero_que_so_existe_no_2g(self):
        ac = self.acervo()
        texto = ac.ler_processo(E)                    # "/50000" acha "-50000 (2G)"
        self.assertTrue(texto.startswith(f"Processo {E} — e-SAJ, 2º grau: 1 página no PDF."))
        self.assertIn("Embargos de declaração", texto)
        self.assertIn("Embargos", ac.ler_processo(E2G))
        with self.assertRaises(LookupError) as erro:
            ac.ler_processo(E, grau="1g")
        self.assertIn("os autos do 1º grau do processo", str(erro.exception))
        self.assertIn(f"há os do 2º grau ({E2G})", str(erro.exception))
        with self.assertRaises(LookupError):
            ac.ler_processo(P)                        # o principal não está no acervo

    def test_grau_invalido_ou_contraditorio(self):
        ac = self.acervo()
        with self.assertRaises(ValueError):
            ac.ler_processo(A, grau="3")
        with self.assertRaises(ValueError):
            ac.ler_processo(A2G, grau="1g")

    def test_buscar_rotula_os_autos_de_cada_grau(self):
        ac = self.acervo()
        achados = ac.buscar("prescrição")
        self.assertIn(f"{A} (1º grau), fl. 2: …", achados)
        self.assertIn(f"{A2G}, fl. 1: …", achados)
        self.assertNotIn(f"\n{A}, fl.", "\n" + achados)
        self.assertIn(f"{A}, transcrição {A}.docx: …", achados)   # a audiência, do processo
        so_2g = ac.buscar("prescrição", A, "2g")
        self.assertIn(f"{A2G}, fl. 1: …", so_2g)
        self.assertNotIn("(1º grau), fl.", so_2g)
        dos_dois = ac.buscar("prescrição", A)
        self.assertIn(f"{A} (1º grau), fl. 2: …", dos_dois)
        self.assertIn(f"{A2G}, fl. 1: …", dos_dois)
        self.assertIn(f"{E2G}, fl. 1: …", ac.buscar("omissão", E))
        # só o 2º grau, no acervo inteiro (as transcrições, que são do processo, vêm)
        so_2g = ac.buscar("prescrição", grau="2g")
        self.assertIn(f"{A2G}, fl. 1: …", so_2g)
        self.assertNotIn(", fl. 2:", so_2g)
        self.assertNotIn("(1º grau)", so_2g)
        # o que não está no acervo: a frase de sempre e, com o grau, a que diz o outro
        self.assertEqual(ac.buscar("prescrição", H), f"o processo {H} não está no acervo")
        self.assertEqual(ac.buscar("omissão", E, "1g"),
                         f"os autos do 1º grau do processo {E} não estão no acervo; há os do "
                         f"2º grau ({E2G})")

    def test_servidor_com_o_parametro_grau(self):
        ferramentas = {f["name"]: f for f in mcp_servidor.FERRAMENTAS}
        for nome in ("ler_processo", "buscar"):
            with self.subTest(nome):
                grau = ferramentas[nome]["inputSchema"]["properties"]["grau"]
                self.assertEqual(grau["enum"], ["1g", "2g"])
                self.assertIn("2º grau", ferramentas[nome]["description"])
        servidor = mcp_servidor.Servidor(self.acervo())

        def chamar(nome, **args):
            r = servidor.tratar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": nome, "arguments": args}})
            return r["result"]

        r = chamar("ler_processo", numero=A)
        self.assertTrue(r["isError"])
        self.assertIn("informe grau=", r["content"][0]["text"])
        r = chamar("ler_processo", numero=A, grau="2g")
        self.assertFalse(r["isError"])
        self.assertIn("e-SAJ, 2º grau", r["content"][0]["text"])
        r = chamar("buscar", termo="prescrição", numero=A, grau="1g")
        self.assertIn(f"{A} (1º grau), fl. 2", r["content"][0]["text"])
        self.assertNotIn(A2G, r["content"][0]["text"])
        r = chamar("ler_processo", numero=A, grau="ambos")
        self.assertTrue(r["isError"])

    def test_so_com_o_1g_a_saida_e_a_de_hoje(self):
        """Acervo sem autos do 2º grau: o conector responde byte a byte como
        na 1.0.2 (o cabeçalho, a listagem, a busca)."""
        for p in (self.pdf_2g, self.pdf_e):
            p.unlink()
        ac = self.acervo()
        texto = ac.ler_processo(A)
        self.assertTrue(texto.startswith(
            f"Processo {A} — e-SAJ: 3 página(s) no PDF. Página N = folha N. Mostrando as fls. 1 "
            f"a 3.\n{CAB} | sistema=esaj | paginacao=folhas | paginas=3 | ausentes=\n"), texto[:300])
        self.assertIn(COMO_CITAR_ESAJ_1_0_2, texto)
        achados = ac.buscar("prescrição").split("\n")
        self.assertTrue(achados[0].startswith(f"{A}, fl. 2: …"), achados)
        self.assertTrue(achados[1].startswith(f"{A}, transcrição {A}.docx: …"), achados)
        self.assertIn(f"\n- {A} — 3 pág. — Processos/Lote 1G/{A}.pdf — página N = folha N "
                      "(fls. 1 a 3)\n", ac.listar_acervo())
        self.assertNotIn("grau", ac.listar_acervo())


class TestPacote2G(Base2G):
    def _arquivos(self, pacote) -> list[str]:
        with zipfile.ZipFile(pacote.arquivo_zip) as z:
            return sorted(z.namelist())

    def test_numero_leva_os_autos_dos_dois_graus(self):
        pacote = chatgpt.gerar_pacote(self.raiz, self.base / "Pacotes", numeros=[A])
        self.assertEqual(pacote.faltaram, [])
        self.assertEqual(self._arquivos(pacote), sorted([
            "INDICE.md", "LEIA-ME - instrucoes.md", f"audiencias/{A}.docx",
            f"autos/{A}.pdf", f"autos/{A2G}.pdf", f"texto/{A}.txt", f"texto/{A2G}.txt"]))
        indice = (pacote.pasta / "INDICE.md").read_text(encoding="utf-8")
        self.assertIn("[PDF](autos/0700001-93.2024.8.02.0058%20(2G).pdf)", indice)
        self.assertIn("| 2º grau |", indice)
        self.assertNotIn(E2G, indice)

    def test_sufixo_do_2g_leva_so_o_2g(self):
        pacote = chatgpt.gerar_pacote(self.raiz, self.base / "Pacotes",
                                      numeros=[A2G, f"{H} (2G)", E])
        self.assertEqual(pacote.faltaram, [f"{H} (2G)"])
        nomes = self._arquivos(pacote)
        self.assertIn(f"autos/{A2G}.pdf", nomes)
        self.assertNotIn(f"autos/{A}.pdf", nomes)
        self.assertIn(f"autos/{E2G}.pdf", nomes)
        self.assertIn(f"audiencias/{A}.docx", nomes)       # a audiência é do processo

    def test_o_que_o_pacote_leva(self):
        ac = self.acervo()
        self.assertEqual(
            chatgpt.conteudo_do_pacote(ac.pdfs(), ac.transcricoes()),
            "2 processos (autos e texto com a marca de citação de cada página; 1 com os autos "
            "dos dois graus), 1 transcrição de audiência, o índice e as instruções")

    def test_numero_do_embargo_no_indice_de_pacote_antigo(self):
        """O número com "-50000" era lido "-50" (dependente de 2 dígitos): a
        linha dos embargos sigilosos ficava no índice de um pacote antigo."""
        self.assertEqual(chatgpt._RE_NUMERO_CNJ.findall(f"| {E2G} | x | {P} |"),
                         [f"{P}-50000", P])
        self.assertEqual(chatgpt._RE_NUMERO_CNJ.findall(f"{P}-123456"), [P])
        antigo = self.base / "Pacotes" / f"{chatgpt.PREFIXO_PACOTE} 2026-01-01 10h00"
        indice = (f"| {A} | e-SAJ | 1º grau |\n| {E2G} | e-SAJ | 2º grau |\n"
                  f"| {P} | e-SAJ | 1º grau |\n")
        (antigo / "autos").mkdir(parents=True)
        (antigo / "INDICE.md").write_text(indice, encoding="utf-8")
        (antigo / "autos" / f"{E2G}.pdf").write_bytes(b"%PDF dos embargos")
        (antigo / "autos" / f"{A2G}.pdf").write_bytes(b"%PDF")
        with zipfile.ZipFile(antigo.with_suffix(".zip"), "w") as z:
            z.writestr("INDICE.md", indice)
            z.writestr(f"autos/{E2G}.pdf", b"%PDF dos embargos")
            z.writestr(f"autos/{A2G}.pdf", b"%PDF")
        sigilosas = sigilo.Sigilosas({f"{P}-50000"})          # só os embargos
        self.assertEqual(chatgpt.retirar_sigilosos_dos_pacotes(self.base / "Pacotes", sigilosas),
                         [])
        self.assertEqual((antigo / "INDICE.md").read_text(encoding="utf-8"),
                         f"| {A} | e-SAJ | 1º grau |\n| {P} | e-SAJ | 1º grau |\n")
        self.assertFalse((antigo / "autos" / f"{E2G}.pdf").exists())
        self.assertTrue((antigo / "autos" / f"{A2G}.pdf").exists())
        with zipfile.ZipFile(antigo.with_suffix(".zip")) as z:
            self.assertEqual(sorted(z.namelist()), ["INDICE.md", f"autos/{A2G}.pdf"])
            self.assertNotIn("50000", z.read("INDICE.md").decode("utf-8"))


class TestSigilo2G(Base2G):
    """S: público no 1º grau e sigiloso no 2º (os autos do 2º grau estão na
    pasta dos sigilosos). O sigilo é do processo: os autos do 1º grau também
    saem do índice, do conector, do pacote e do espelho."""

    def setUp(self):
        super().setUp()
        self.sig = self.base / "Sigilosos"
        _pdf(self.sig / "Lote 2G" / f"{S} (2G).pdf", ["SEGREDO do 2º grau"],
             manifesto=_m_esaj(S, 1, "2g"))
        self.pdf_s = _pdf(self.lote1 / f"{S}.pdf", ["público no 1º grau"],
                          manifesto=_m_esaj(S, 1))
        cache = self.raiz / "_ia" / "texto"
        cache.mkdir(parents=True)
        (cache / f"{S}.txt").write_text("texto antigo dos autos do 1º grau", encoding="utf-8")
        self.cfg = config.Config(self.base / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.raiz))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.sig))
        # Separação desligada: os autos ficam no acervo, e só os filtros os escondem
        self.cfg.definir("download", "separar_sigilosos", False)

    def test_sigiloso_no_2g_some_de_tudo_tambem_no_1g(self):
        ac = mcp_servidor.Acervo(self.raiz, sigilosos=self.sig, pauta=None)
        self.assertIn(S, ac.sigilosas())
        self.assertIn(f"{S} (2G)", ac.sigilosas())          # a chave dos autos também
        self.assertEqual(set(ac.pdfs()), {A, A2G, E2G})
        self.assertNotIn(S, ac.listar_acervo())
        with self.assertRaises(LookupError):
            ac.ler_processo(S)
        self.assertNotIn(S, ac.buscar("público"))
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertEqual(rel.processos, 2)
        self.assertNotIn(S, (self.raiz / "INDICE.md").read_text(encoding="utf-8"))
        self.assertFalse((self.raiz / "_ia" / "texto" / f"{S}.txt").exists())
        pacote = chatgpt.gerar_pacote(self.raiz, self.base / "Pacotes", cfg=self.cfg)
        with zipfile.ZipFile(pacote.arquivo_zip) as z:
            self.assertEqual([n for n in z.namelist() if S in n], [])
            self.assertIn(f"autos/{A2G}.pdf", z.namelist())
        pacote = chatgpt.gerar_pacote(self.raiz, self.base / "Pacotes", numeros=[S, A2G],
                                      cfg=self.cfg)
        self.assertEqual(pacote.faltaram, [S])

    def test_espelho_sem_nada_do_sigiloso(self):
        destino = self.base / "Nuvem"
        espelho = destino / nuvem.SUBPASTA / "Processos"
        # cópias de antes de se saber do sigilo, dos dois graus
        _pdf(espelho / "Lote 1G" / f"{S}.pdf", ["antigo"])
        _pdf(espelho / "Lote 2G" / f"{S} (2G).pdf", ["antigo"])
        (destino / nuvem.SUBPASTA / "_ia" / "texto").mkdir(parents=True)
        (destino / nuvem.SUBPASTA / "_ia" / "texto" / f"{S} (2G).txt").write_text(
            "antigo", encoding="utf-8")
        nuvem.espelhar(self.raiz, destino, sigilosos=self.sig, pauta=None)
        self.assertEqual(sorted(p.name for p in destino.rglob(f"{S}*")), [])
        self.assertTrue((espelho / "Lote 1G" / f"{A}.pdf").exists())
        self.assertTrue((espelho / "Lote 2G" / f"{A2G}.pdf").exists())
        self.assertTrue((espelho / "Lote 2G" / f"{E2G}.pdf").exists())

    def test_contem_com_a_chave_dos_autos_nos_filtros(self):
        """A regra do sigilo é por processo: a chave dos autos ("X (2G)") é
        normalizada antes de comparar, e o incidente herda do principal."""
        sigilosas = sigilo.Sigilosas({A})
        for chave in (A, A2G, f"{A}-01 (2G)", f"{A2G}.pdf"):
            with self.subTest(chave=chave):
                self.assertIn(chave, sigilosas)
        self.assertNotIn(E2G, sigilo.Sigilosas({A}))
        self.assertIn(E2G, sigilo.Sigilosas({P}))            # o recurso interno herda
        self.assertNotIn(A2G, sigilo.Sigilosas({f"{A}-01"}))  # o principal não herda
        # A sigiloso pelos autos do 1º grau na pasta dos sigilosos: os do 2º saem também
        _pdf(self.sig / "Lote 1G" / f"{A}.pdf", ["SEGREDO"])
        ac = mcp_servidor.Acervo(self.raiz, sigilosos=self.sig, pauta=None)
        self.assertEqual(set(ac.pdfs()), {E2G})
        # só os embargos sigilosos: o principal e a apelação ficam
        for p in self.sig.rglob("*.pdf"):
            p.unlink()
        _pdf(self.sig / "Lote 2G" / f"{E2G}.pdf", ["SEGREDO"])
        ac = mcp_servidor.Acervo(self.raiz, sigilosos=self.sig, pauta=None)
        self.assertEqual(set(ac.pdfs()), {A, A2G, S})


class TestEspelho2G(Base2G):
    def test_os_nomes_do_2g_sao_copiados_como_sao(self):
        destino = self.base / "Nuvem"
        copiados, _iguais = nuvem.espelhar(self.raiz, destino, sigilosos=None, pauta=None)
        self.assertEqual(copiados, 4)
        pasta = destino / nuvem.SUBPASTA / "Processos"
        self.assertTrue((pasta / "Lote 1G" / f"{A}.pdf").exists())
        self.assertTrue((pasta / "Lote 2G" / f"{A2G}.pdf").exists())
        self.assertTrue((pasta / "Lote 2G" / f"{E2G}.pdf").exists())


class TestChaves(unittest.TestCase):
    def test_numeros_de_exemplo_com_digito_certo(self):
        for numero in (A, S, H, P):
            with self.subTest(numero=numero):
                self.assertEqual(cnj.ler(numero).formatado, numero)
        self.assertEqual(cnj.chave_dos_autos(f"{E2G}.pdf"), E2G)
        self.assertEqual(cnj.chave_dos_autos(f"{A2G}.pdf"), A2G)


if __name__ == "__main__":
    unittest.main()
