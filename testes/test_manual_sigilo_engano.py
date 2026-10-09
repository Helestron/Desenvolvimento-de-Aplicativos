"""O manual "Se um processo foi marcado como sigiloso por engano" seguido à
letra com os dois graus (achados X7 e X8 da quarta verificação do 2º grau).

Desde a 1.1.0, o processo tem uma linha por grau no relatório do lote, e
basta uma com "sim" para o motor refazer a marcação nos dois graus ("uma vez
sigiloso, sempre sigiloso"). E a capa que o download grava para o processo
que achou sigiloso traz "SEGREDO DE JUSTIÇA" no começo, e o motor a relê.
Os passos 5 e 6 falavam de "a linha dele" e "os autos", no singular, e
mandavam levar a capa de volta como estava: seguidos assim, A voltava à
pasta dos sigilosos no primeiro download dela no lote. Agora mandam trocar
todas as linhas dele, de cada lote, trazer os autos dos dois graus e apagar
essa linha da capa antes de levá-la de volta.

Achado Y5 da quinta verificação: com a separação dos sigilosos desligada, os
autos e a capa nem saem do acervo, e o passo 6 só falava da capa que volta
da pasta dos sigilosos; a que ficou no _controle do lote, com a linha,
refazia a marcação. Agora a capa tem passo próprio (o 7), onde ela estiver.
E o achado Y4: o passo 4 fala do principal que só o recurso interno apurou.

Com portal e navegador de mentira (testes/apoio_download.py) e a capa como
o e-SAJ de verdade a grava (esaj.formatar_capa).
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from helestron.compartilhar import preparo
from helestron.download import esaj, modelos, motor
from helestron.nucleo import cnj, sigilo

from testes import apoio_download as apoio
from testes.test_download_motor import BaseMotor

A = cnj.ler("0700001-93.2024.8.02.0058")       # existe nos dois graus
A2 = cnj.ler("0700002-78.2024.8.02.0058")

MANUAL = Path(__file__).resolve().parents[1] / "docs" / "MANUAL.md"
FRASE_DA_CAPA = "SEGREDO DE JUSTIÇA"


def passo(n: int) -> str:
    """O passo n de "Se um processo foi marcado como sigiloso por engano",
    com os espaços e as quebras de linha reduzidos a um espaço."""
    secao = MANUAL.read_text(encoding="utf-8").split(
        "### Se um processo foi marcado como sigiloso por engano", 1)[1]
    texto = secao.split(f"\n{n}. ", 1)[1].split(f"\n{n + 1}. ", 1)[0]
    return re.sub(r"\s+", " ", texto)


class TestManualSigiloEngano(BaseMotor):
    separar = True          # Separar os processos sigilosos (Ajustes › Download)

    def lote(self, numeros, grau, roteiro=None):
        fp, fn = apoio.fabricas(roteiro)
        opcoes = apoio.opcoes_de_teste(self.tmp, grau=grau, separar_sigilosos=self.separar)
        return motor.executar(numeros, self.destino, opcoes, self.ctx,
                              fabrica_portal=fp, fabrica_navegador=fn)

    def relatorio(self, arquivo: Path) -> list[dict]:
        texto = arquivo.read_bytes().decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(texto), delimiter=";"))

    def gravar(self, arquivo: Path, linhas: list[dict]) -> None:
        """Como o Excel, no mesmo formato."""
        with open(arquivo, "w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=list(linhas[0]), delimiter=";",
                                      lineterminator="\r\n")
            escritor.writeheader()
            escritor.writerows(linhas)

    def sigilosa(self) -> bool:
        return sigilo.contem(sigilo.chaves_sigilosas(self.tmp / "Sigilosos",
                                                     self.tmp / "Acervo"), A.nome_arquivo)

    def desligar_a_separacao(self):
        self.separar = False
        self.cfg.definir("download", "separar_sigilosos", False)

    def marcar_e_desfazer(self, graus=("1g", "2g"), capa_como_estava=False):
        """A baixada sigilosa nos dois graus, no mesmo lote, e os passos 4 a 8
        do manual. ``graus``: as linhas de A que o usuário troca no passo 5;
        ``capa_como_estava``: o passo 7 deixa as capas como estavam."""
        for grau in cnj.GRAUS:
            r = self.lote([A], grau, {A.formatado: ["ok_sigiloso"]}).itens[0]
            self.assertTrue(r.sigiloso)
        self.sig = self.tmp / "Sigilosos" / self.destino.name
        self.completo = self.sig / "_controle" / "relatorio.csv"
        self.do_acervo = self.destino / "_controle" / "relatorio.csv"
        # os autos e a capa ficam na pasta dos sigilosos ou, com a separação
        # desligada, no acervo; a capa, como o e-SAJ a grava para o sigiloso
        guardados = self.sig if self.separar else self.destino
        for grau in cnj.GRAUS:
            self.assertTrue((guardados / f"{cnj.nome_dos_autos(A, grau)}.pdf").is_file())
            capa = guardados / "_controle" / f"{cnj.nome_dos_autos(A, grau)}_capa.txt"
            capa.write_text(esaj.formatar_capa({}, A, "TJAL", True, grau=grau),
                            encoding="utf-8")
            self.assertIn(FRASE_DA_CAPA, capa.read_text(encoding="utf-8")[:2000])
        numero = motor.MASCARA_SIGILOSO if self.separar else A.formatado
        self.assertEqual([(l["processo"], l["grau"], l["sigiloso"])
                          for l in self.relatorio(self.do_acervo)],
                         [(numero, "1g", "sim"), (numero, "2g", "sim")])
        self.assertEqual(self.completo.is_file(), self.separar)

        # 4. o download.sigilo.json fora
        sigilo.arquivo_do_download().unlink()
        # 5. "não" em todas as linhas dele, no completo (se existir) e no do
        # acervo; neste, cada linha "(processo sigiloso)" trocada pela de mesma
        # ordem do completo
        trocadas = {}
        if self.completo.is_file():
            linhas = self.relatorio(self.completo)
            for linha in linhas:
                if linha["processo"] == A.formatado and linha["grau"] in graus:
                    linha["sigiloso"] = "não"
                    trocadas[linha["ordem"]] = linha
            self.gravar(self.completo, linhas)
        linhas = self.relatorio(self.do_acervo)
        for linha in linhas:
            if linha["processo"] == A.formatado and linha["grau"] in graus:
                linha["sigiloso"] = "não"
        self.gravar(self.do_acervo, [
            trocadas.get(l["ordem"], l) if l["processo"] == motor.MASCARA_SIGILOSO else l
            for l in linhas])
        # 6. os autos dos dois graus e o que mais tiver o número dele de volta
        # ao lote de mesmo nome
        for pasta in (self.sig, self.sig / "_controle", self.sig / "_controle" / "midias"):
            for p in list(pasta.glob(f"{A.nome_arquivo}*")):
                novo = self.destino / p.relative_to(self.sig)
                novo.parent.mkdir(parents=True, exist_ok=True)
                p.replace(novo)
        self.assertEqual(list(self.sig.glob("*.pdf")), [])
        # 7. a capa dele, onde estiver (a que voltou e a que nem saiu do
        # acervo), sem a linha "SEGREDO DE JUSTIÇA"
        capas = sorted((self.destino / "_controle").glob(f"{A.nome_arquivo}*_capa.txt"))
        self.assertEqual(len(capas), 2)
        for p in () if capa_como_estava else capas:
            texto = p.read_text(encoding="utf-8").splitlines(keepends=True)
            p.write_text("".join(l for l in texto if FRASE_DA_CAPA not in l), encoding="utf-8")
        # 8. Preparar acervo para a IA
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=False)
        self.assertEqual(rel.sigilosos_levados, 0)
        self.assertFalse(self.sigilosa())

    def test_o_manual_fala_das_linhas_dos_dois_graus_e_da_capa(self):
        p5, p6, p7 = passo(5), passo(6), passo(7)
        for frase in ("No relatório de cada lote em que ele foi baixado",
                      "de todas as linhas dele", "uma linha por grau",
                      "(coluna `grau`: `1g` e `2g`)", "pode estar em mais de um lote",
                      "basta uma linha com “sim” para ele voltar a ser sigiloso, nos dois "
                      "graus",
                      "Troque cada uma dessas linhas inteira pela linha de mesma ordem copiada "
                      "do relatório completo",
                      "o Excel pode não abrir ao mesmo tempo dois arquivos com o mesmo nome",
                      "copie a linha no relatório completo, feche-o e abra o do acervo"):
            self.assertIn(frase, p5)
        self.assertIn("os autos dos dois graus (`<número>.pdf` e `<número> (2G).pdf`), de "
                      "cada `Sigilosos\\<nome do lote>\\` em que estiverem", p6)
        for frase in ("(`_controle\\<número>_capa.txt` e `_controle\\<número> (2G)_capa.txt`)",
                      "traz no começo a linha “SEGREDO DE JUSTIÇA - processo sigiloso. Não "
                      "compartilhe.”",
                      "apague essa linha (no Bloco de Notas) ou a capa inteira",
                      "sem isso, o próximo download dele no lote o marca de novo"):
            self.assertIn(frase, p7)

    def test_o_passo_4_fala_do_principal_apurado_pelo_recurso_interno(self):
        # Achado Y4 da quinta verificação: o principal que só a consulta do
        # recurso interno (/50000) apurou não tem linha própria no relatório,
        # e o passo 4 prometia que todo apurado continuava sigiloso sem o
        # download.sigilo.json. Desde a correção, a linha "sim" do recurso
        # interno marca também o principal; o passo diz isso e a exceção.
        regra = re.sub(r"\s+", " ", MANUAL.read_text(encoding="utf-8"))
        self.assertIn("o recurso interno sigiloso, por qualquer das situações acima, torna "
                      "sigiloso também o processo principal", regra)
        p4 = passo(4)
        for frase in ("Vale também para o processo principal que a consulta de um recurso "
                      "interno dele no 2º grau (`...0001-50000`) achou em segredo",
                      "a linha “sim” do recurso interno o marca também",
                      "A exceção é o principal que nunca foi baixado, com a separação ligada",
                      "baixe de novo o recurso interno no 2º grau: a consulta o apura de novo"):
            self.assertIn(frase, p4)

    def test_separacao_desligada_seguido_a_letra_continua_publico(self):
        # Os autos e a capa nem saem do acervo: o passo 7 manda apagar a linha
        # da capa também ali, e A continua pública nas rodadas seguintes.
        p7 = passo(7)
        for frase in ("Confira a capa dele em cada lote em que ele foi baixado, onde ela "
                      "estiver: em `Acervo\\Processos\\<nome do lote>\\_controle\\`",
                      "a que nem saiu do acervo (com **Separar os processos sigilosos** "
                      "desligado, os autos e a capa ficam no acervo)"):
            self.assertIn(frase, p7)
        self.desligar_a_separacao()
        self.marcar_e_desfazer()
        for grau in cnj.GRAUS:
            r = self.lote([A], grau).itens[0]
            autos = self.destino / f"{cnj.nome_dos_autos(A, grau)}.pdf"
            self.assertEqual((r.situacao, r.sigiloso, r.arquivo),
                             (modelos.JA_BAIXADO, False, str(autos)), grau)
            self.assertFalse(self.sigilosa(), grau)
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio(self.do_acervo)],
                         [(A.formatado, "não"), (A.formatado, "não")])
        self.assertNotIn(A.nome_arquivo, sigilo.apuradas_no_download())

    def test_separacao_desligada_a_capa_que_ficou_no_acervo_marca_de_novo(self):
        # por que o passo 7 vale também para a capa que não saiu do acervo
        self.desligar_a_separacao()
        self.marcar_e_desfazer(capa_como_estava=True)
        r = self.lote([A], "1g").itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.JA_BAIXADO, True))
        self.assertTrue(self.sigilosa())
        self.assertIn(A.nome_arquivo, sigilo.apuradas_no_download())

    def test_seguido_a_letra_com_os_dois_graus_continua_publico(self):
        self.marcar_e_desfazer()
        # a rodada seguinte do lote, com outro processo, não o marca de novo...
        self.lote([A2], "1g")
        for arquivo in (self.do_acervo, self.completo):
            self.assertEqual([(l["processo"], l["grau"], l["sigiloso"])
                              for l in self.relatorio(arquivo)],
                             [(A.formatado, "1g", "não"), (A.formatado, "2g", "não"),
                              (A2.formatado, "1g", "não")], arquivo)
        # ... e as que o têm na relação, num grau e no outro, não o levam de
        # volta aos sigilosos
        for grau in cnj.GRAUS:
            r = self.lote([A], grau).itens[0]
            autos = self.destino / f"{cnj.nome_dos_autos(A, grau)}.pdf"
            self.assertEqual((r.situacao, r.sigiloso, r.arquivo),
                             (modelos.JA_BAIXADO, False, str(autos)), grau)
            self.assertFalse(self.sigilosa(), grau)
        self.assertEqual(list(self.sig.glob("*.pdf")), [])
        self.assertEqual([(l["processo"], l["sigiloso"]) for l in self.relatorio(self.do_acervo)],
                         [(A.formatado, "não"), (A.formatado, "não"), (A2.formatado, "não")])
        self.assertNotIn(A.nome_arquivo, sigilo.apuradas_no_download())

    def test_a_capa_levada_como_estava_marca_de_novo(self):
        # por que o passo 7 manda apagar a linha da capa
        self.marcar_e_desfazer(capa_como_estava=True)
        r = self.lote([A], "1g").itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.JA_BAIXADO, True))
        self.assertTrue((self.sig / f"{A.nome_arquivo}.pdf").is_file())
        self.assertTrue(self.sigilosa())

    def test_so_a_linha_de_um_grau_trocada_marca_de_novo(self):
        # por que o passo 5 manda trocar todas as linhas dele
        self.marcar_e_desfazer(graus=("1g",))
        r = self.lote([A], "1g").itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.JA_BAIXADO, True))
        self.assertTrue((self.sig / f"{A.nome_arquivo}.pdf").is_file())
        self.assertTrue(self.sigilosa())
