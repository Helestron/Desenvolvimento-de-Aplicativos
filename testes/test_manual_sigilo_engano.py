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
    def lote(self, numeros, grau, roteiro=None):
        fp, fn = apoio.fabricas(roteiro)
        opcoes = apoio.opcoes_de_teste(self.tmp, grau=grau)
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

    def marcar_e_desfazer(self, graus=("1g", "2g"), capa_como_estava=False):
        """A baixada sigilosa nos dois graus, no mesmo lote, e os passos 4 a 7
        do manual. ``graus``: as linhas de A que o usuário troca no passo 5;
        ``capa_como_estava``: o passo 6 leva as capas sem apagar a linha."""
        for grau in cnj.GRAUS:
            r = self.lote([A], grau, {A.formatado: ["ok_sigiloso"]}).itens[0]
            self.assertTrue(r.sigiloso)
        self.sig = self.tmp / "Sigilosos" / self.destino.name
        self.completo = self.sig / "_controle" / "relatorio.csv"
        self.do_acervo = self.destino / "_controle" / "relatorio.csv"
        for grau in cnj.GRAUS:           # a capa como o e-SAJ a grava para o sigiloso
            capa = self.sig / "_controle" / f"{cnj.nome_dos_autos(A, grau)}_capa.txt"
            capa.write_text(esaj.formatar_capa({}, A, "TJAL", True, grau=grau),
                            encoding="utf-8")
            self.assertIn(FRASE_DA_CAPA, capa.read_text(encoding="utf-8")[:2000])
        self.assertEqual([(l["processo"], l["grau"]) for l in self.relatorio(self.do_acervo)],
                         [(motor.MASCARA_SIGILOSO, "1g"), (motor.MASCARA_SIGILOSO, "2g")])

        # 4. o download.sigilo.json fora
        sigilo.arquivo_do_download().unlink()
        # 5. "não" em todas as linhas dele no completo; no relatório do acervo,
        # cada linha "(processo sigiloso)" trocada pela de mesma ordem do completo
        linhas = self.relatorio(self.completo)
        trocadas = {}
        for linha in linhas:
            if linha["processo"] == A.formatado and linha["grau"] in graus:
                linha["sigiloso"] = "não"
                trocadas[linha["ordem"]] = linha
        self.gravar(self.completo, linhas)
        self.gravar(self.do_acervo, [
            trocadas.get(l["ordem"], l) if l["processo"] == motor.MASCARA_SIGILOSO else l
            for l in self.relatorio(self.do_acervo)])
        # 6. os autos dos dois graus e o que mais tiver o número dele de volta
        # ao lote de mesmo nome; da capa, antes, sai a linha "SEGREDO DE JUSTIÇA"
        for pasta in (self.sig, self.sig / "_controle", self.sig / "_controle" / "midias"):
            for p in list(pasta.glob(f"{A.nome_arquivo}*")):
                if p.name.endswith("_capa.txt") and not capa_como_estava:
                    texto = p.read_text(encoding="utf-8").splitlines(keepends=True)
                    p.write_text("".join(l for l in texto if FRASE_DA_CAPA not in l),
                                 encoding="utf-8")
                novo = self.destino / p.relative_to(self.sig)
                novo.parent.mkdir(parents=True, exist_ok=True)
                p.replace(novo)
        self.assertEqual(list(self.sig.glob("*.pdf")), [])
        # 7. Preparar acervo para a IA
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=False)
        self.assertEqual(rel.sigilosos_levados, 0)
        self.assertFalse(self.sigilosa())

    def test_o_manual_fala_das_linhas_dos_dois_graus_e_da_capa(self):
        p5, p6 = passo(5), passo(6)
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
        for frase in ("os autos dos dois graus (`<número>.pdf` e `<número> (2G).pdf`), de "
                      "cada `Sigilosos\\<nome do lote>\\` em que estiverem",
                      "(`_controle\\<número>_capa.txt` e `_controle\\<número> (2G)_capa.txt`)",
                      "traz no começo a linha “SEGREDO DE JUSTIÇA - processo sigiloso. Não "
                      "compartilhe.”",
                      "antes de levá-la de volta, apague essa linha (no Bloco de Notas) ou a "
                      "capa inteira",
                      "sem isso, o próximo download dele no lote o marca de novo"):
            self.assertIn(frase, p6)

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
        # por que o passo 6 manda apagar a linha da capa
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
