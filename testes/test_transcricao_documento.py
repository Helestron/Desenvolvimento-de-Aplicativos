"""Documento DOCX: ficha com o processo, falas agrupadas, legenda só com
rótulos automáticos, gravação atômica e o Word segurando o arquivo."""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from helestron.nucleo import sistema
from helestron.transcricao import documento
from helestron.transcricao.documento import (Fala, MetaAudiencia, agrupar, automatico, gerar_docx,
                                       hms)
from testes.apoio_transcricao import NUMERO, PastaTemporaria, ficha, ler_docx


def meta_exemplo(**kw) -> MetaAudiencia:
    base = dict(numero=NUMERO, tipo="Instrução e julgamento", data=datetime(2026, 9, 16, 14, 0),
                unidade="1ª Vara Cível, Maceió, TJAL", magistrado="Fulana de Tal (Juíza de Direito)",
                participantes={"Juiz(a)": "Fulana de Tal", "Testemunha": "Beltrano"},
                inicio=datetime(2026, 9, 16, 14, 2), fim=datetime(2026, 9, 16, 15, 10),
                modelo="small", origem="ao vivo", gravacao="audiencia.flac", duracao=3725.0)
    base.update(kw)
    return MetaAudiencia(**base)


class TestUtilidades(unittest.TestCase):
    def test_hms(self):
        self.assertEqual(hms(0), "00:00:00")
        self.assertEqual(hms(3725.9), "01:02:05")
        self.assertEqual(hms(-3), "00:00:00")

    def test_automatico(self):
        self.assertTrue(automatico("FALANTE 1"))
        self.assertTrue(automatico("FALANTE 12"))
        self.assertFalse(automatico("Juiz(a)"))
        self.assertFalse(automatico(""))

    def test_agrupar_respeita_pausa_e_falante(self):
        falas = [Fala(0, 2, "Juiz(a)", "Bom dia."), Fala(2.5, 4, "Juiz(a)", "Vamos começar."),
                 Fala(8, 9, "Juiz(a)", "Depois da pausa longa."),
                 Fala(9.5, 11, "Testemunha", "Sim."), Fala(11.2, 12, "", "(marca)"),
                 Fala(12.1, 13, "", "(outra marca)"), Fala(13, 14, "Testemunha", "  ")]
        g = agrupar(falas)
        self.assertEqual([f.texto for f in g], ["Bom dia. Vamos começar.", "Depois da pausa longa.",
                                                "Sim.", "(marca)", "(outra marca)"])
        self.assertEqual(g[0].fim, 4)
        self.assertEqual(falas[0].texto, "Bom dia.")   # não altera a lista original

    def test_meta_ida_e_volta_em_dicionario(self):
        meta = meta_exemplo()
        de_volta = MetaAudiencia.de_dict(meta.como_dict())
        self.assertEqual(de_volta, meta)
        self.assertEqual(MetaAudiencia.de_dict({"numero": "x", "desconhecido": 1}).numero, "x")

    def test_fala_ida_e_volta(self):
        f = Fala(1.234, 2.5, "Juiz(a)", "Texto")
        self.assertEqual(Fala.de_dict(f.como_dict()), Fala(1.23, 2.5, "Juiz(a)", "Texto"))


class TestGerarDocx(unittest.TestCase):
    def setUp(self):
        self.pasta = PastaTemporaria()
        self.destino = self.pasta.raiz / f"{NUMERO}.docx"

    def tearDown(self):
        self.pasta.apagar()

    def test_ficha_corpo_e_rodape(self):
        falas = [Fala(5, 7, "Juiz(a)", "Está aberta a audiência."),
                 Fala(7.5, 9, "Juiz(a)", "Qualifique-se."),
                 Fala(10, 12, "Testemunha", "Meu nome é Beltrano.")]
        caminho = gerar_docx(self.destino, falas, meta_exemplo())
        self.assertEqual(caminho, self.destino)
        paragrafos, tabelas, rodape = ler_docx(caminho)
        self.assertEqual(paragrafos[0], "TRANSCRIÇÃO DE AUDIÊNCIA")
        self.assertIn(f"Processo nº {NUMERO}", paragrafos)
        f = ficha(tabelas)
        self.assertEqual(f["Processo nº"], NUMERO)
        self.assertEqual(f["Tipo de audiência"], "Instrução e julgamento")
        self.assertEqual(f["Data"], "16/09/2026")
        self.assertEqual(f["Início e término"], "14:02 às 15:10")
        self.assertEqual(f["Duração da gravação"], "01:02:05")
        self.assertEqual(f["Unidade"], "1ª Vara Cível, Maceió, TJAL")
        self.assertEqual(f["Magistrado(a)"], "Fulana de Tal (Juíza de Direito)")
        self.assertEqual(f["Participantes"], "Juiz(a): Fulana de Tal\nTestemunha: Beltrano")
        self.assertEqual(f["Forma da transcrição"], "Simultânea (ao vivo, pelo microfone)")
        self.assertEqual(f["Modelo de transcrição"], "Whisper small (português)")
        self.assertEqual(f["Gravação"], "audiencia.flac")
        self.assertIn("Juiz(a) [00:00:05] — Está aberta a audiência. Qualifique-se.", paragrafos)
        self.assertIn("Testemunha [00:00:10] — Meu nome é Beltrano.", paragrafos)
        # rótulos manuais: sem legenda, com o aviso próprio
        self.assertNotIn("IDENTIFICAÇÃO DOS FALANTES", paragrafos)
        self.assertEqual(len(tabelas), 1)
        self.assertTrue(any("marcada durante a audiência" in p for p in paragrafos))
        self.assertIn(f"Processo nº {NUMERO}", rodape)
        self.assertIn("página", rodape)
        self.assertFalse(Path(str(self.destino) + ".parcial").exists())

    def test_legenda_so_com_rotulos_automaticos(self):
        falas = [Fala(0, 2, "FALANTE 2", "Primeiro a falar?"), Fala(3, 4, "FALANTE 1", "Sim."),
                 Fala(5, 6, "Juiz(a)", "Marcado à mão."), Fala(7, 8, "FALANTE 2", "De novo.")]
        caminho = gerar_docx(self.destino, falas, meta_exemplo(origem="revisão"))
        paragrafos, tabelas, _ = ler_docx(caminho)
        self.assertIn("IDENTIFICAÇÃO DOS FALANTES", paragrafos)
        legenda = tabelas[1]
        self.assertEqual(legenda[0], ["Rótulo", "Quem é (preencher)"])
        self.assertEqual([linha[0] for linha in legenda[1:]], ["FALANTE 1", "FALANTE 2"])
        self.assertTrue(any("similaridade de voz" in p for p in paragrafos))
        self.assertEqual(ficha(tabelas)["Forma da transcrição"],
                         "Revisão da gravação, depois da audiência")

    def test_legenda_automatica_forcada_lista_todos(self):
        falas = [Fala(0, 2, "Voz A", "Um."), Fala(3, 4, "Voz B", "Dois.")]
        paragrafos, tabelas, _ = ler_docx(gerar_docx(self.destino, falas, meta_exemplo(),
                                                     legenda_automatica=True))
        self.assertEqual([linha[0] for linha in tabelas[1][1:]], ["Voz A", "Voz B"])

    def test_sem_tempo_sem_falas_e_campos_vazios(self):
        meta = MetaAudiencia(numero=NUMERO)
        paragrafos, tabelas, _ = ler_docx(gerar_docx(self.destino, [], meta, marcar_tempo=False))
        self.assertIn("(Nenhuma fala transcrita até o momento.)", paragrafos)
        f = ficha(tabelas)
        self.assertEqual(f["Tipo de audiência"], "—")
        self.assertEqual(f["Duração da gravação"], "—")
        falas = [Fala(1, 2, "Juiz(a)", "Sem marca de tempo.")]
        paragrafos, _, _ = ler_docx(gerar_docx(self.destino, falas, meta, marcar_tempo=False))
        self.assertIn("Juiz(a) — Sem marca de tempo.", paragrafos)

    def test_marca_sem_falante_sai_sem_rotulo(self):
        falas = [Fala(3, 3, "", "(Gravação pausada às 10:00:00 e retomada às 10:05:00.)")]
        paragrafos, _, _ = ler_docx(gerar_docx(self.destino, falas, meta_exemplo()))
        self.assertIn("[00:00:03] — (Gravação pausada às 10:00:00 e retomada às 10:05:00.)",
                      paragrafos)

    def test_observacao_entra_na_ficha(self):
        _, tabelas, _ = ler_docx(gerar_docx(self.destino, [], meta_exemplo(observacao="Teste.")))
        self.assertEqual(ficha(tabelas)["Observação"], "Teste.")

    def test_regravar_substitui(self):
        gerar_docx(self.destino, [Fala(0, 1, "Juiz(a)", "Primeira versão.")], meta_exemplo())
        gerar_docx(self.destino, [Fala(0, 1, "Juiz(a)", "Segunda versão.")], meta_exemplo())
        paragrafos, _, _ = ler_docx(self.destino)
        self.assertIn("Juiz(a) [00:00:00] — Segunda versão.", paragrafos)
        self.assertEqual(sorted(p.name for p in self.pasta.raiz.glob("*.docx")), [self.destino.name])

    def test_propriedades_do_documento_sao_do_helestron(self):
        """Regressão: o modelo do python-docx deixava autor "python-docx", o
        comentário "generated by python-docx", criado e modificado em
        23/12/2013, título vazio, o aplicativo "Microsoft Macintosh Word" e a
        miniatura do modelo - num documento que pode ir aos autos."""
        import io
        import zipfile
        from datetime import timezone

        import docx

        antes = datetime.now(timezone.utc).replace(microsecond=0)
        caminho = gerar_docx(self.destino, [Fala(0, 2, "Juiz(a)", "Bom dia.")], meta_exemplo())
        dados = caminho.read_bytes()
        cp = docx.Document(io.BytesIO(dados)).core_properties
        self.assertEqual((cp.author, cp.last_modified_by), ("Helestron", "Helestron"))
        self.assertIn(NUMERO, cp.title)
        self.assertEqual(cp.title, f"Transcrição de audiência — Processo nº {NUMERO}")
        self.assertEqual(cp.comments, "")
        self.assertEqual(cp.keywords, NUMERO)
        for quando in (cp.created, cp.modified):
            self.assertGreaterEqual(quando.replace(tzinfo=timezone.utc), antes)
            self.assertLess((quando.replace(tzinfo=timezone.utc) - antes).total_seconds(), 120)
        pacote = zipfile.ZipFile(io.BytesIO(dados))
        self.assertNotIn("python-docx", pacote.read("docProps/core.xml").decode("utf-8"))
        app = pacote.read("docProps/app.xml").decode("utf-8")
        self.assertIn("<Application>Helestron", app)
        self.assertNotIn("Macintosh", app)
        self.assertFalse([n for n in pacote.namelist() if "thumbnail" in n])
        # sem número (gravação avulsa), o título não fica vazio
        sem = documento.montar_docx([], MetaAudiencia(numero=""))
        self.assertEqual(docx.Document(io.BytesIO(sem)).core_properties.title,
                         "Transcrição de audiência")

    def test_aberto_no_word_grava_copia_ao_lado(self):
        original = sistema.gravar_atomico

        def tranca(destino, dados):
            if Path(destino) == self.destino:
                Path(str(destino) + ".parcial").write_bytes(b"x")
                raise PermissionError(13, "O arquivo está aberto em outro programa")
            return original(destino, dados)

        with mock.patch.object(documento.sistema, "gravar_atomico", side_effect=tranca), \
                self.assertLogs("transcricao.documento", "WARNING"):
            caminho = gerar_docx(self.destino, [Fala(0, 1, "Juiz(a)", "Oi.")], meta_exemplo())
            self.assertEqual(caminho.name, f"{NUMERO} (cópia).docx")
            # de novo: reaproveita a mesma cópia (o salvamento automático não espalha arquivos)
            caminho2 = gerar_docx(self.destino, [Fala(0, 1, "Juiz(a)", "Oi.")], meta_exemplo())
            self.assertEqual(caminho2, caminho)
        self.assertFalse(Path(str(self.destino) + ".parcial").exists())
        self.assertTrue(caminho.exists())


class TestSigiloPelaPasta(unittest.TestCase):
    """processo_sigiloso: o que já está na pasta dos sigilosos decide."""

    def setUp(self):
        self.pasta = PastaTemporaria()
        self.addCleanup(self.pasta.apagar)
        self.cfg = self.pasta.config()
        self.sig = self.pasta.raiz / "Sigilosos"
        from helestron.nucleo import cnj

        self.numero = cnj.ler(NUMERO)

    def test_autos_na_pasta_dos_sigilosos(self):
        self.assertFalse(documento.processo_sigiloso(self.cfg, self.numero))
        (self.sig / "Lote 1").mkdir(parents=True)
        (self.sig / "Lote 1" / f"{self.numero.nome_arquivo}-01.pdf").write_bytes(b"%PDF")
        self.assertFalse(documento.processo_sigiloso(self.cfg, self.numero))   # o incidente
        (self.sig / "Lote 1" / f"{self.numero.nome_arquivo}.pdf").write_bytes(b"%PDF")
        self.assertTrue(documento.processo_sigiloso(self.cfg, self.numero))

    def test_transcricao_ou_gravacao_ja_sigilosa(self):
        """A audiência marcada sigilosa só pelo interruptor (sem os autos na
        pasta): a retranscrição - inclusive pelo envio da página, que perde a
        pasta de origem - continua fora do acervo."""
        transcricoes = self.sig / "Transcricoes"
        audio = transcricoes / "_audio" / f"{self.numero.nome_arquivo} 2026-09-15 14h00.flac"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"fLaC")
        self.assertTrue(documento.processo_sigiloso(self.cfg, self.numero))
        self.assertEqual(documento.pasta_das_transcricoes(self.cfg, self.numero), transcricoes)
        audio.unlink()
        self.assertFalse(documento.processo_sigiloso(self.cfg, self.numero))
        (transcricoes / f"{self.numero.nome_arquivo} (2).docx").write_bytes(b"PK")
        self.assertTrue(documento.processo_sigiloso(self.cfg, self.numero))
        # outro processo não é contaminado
        from helestron.nucleo import cnj

        outro = cnj.ler("0700124-68.2024.8.02.0001")
        self.assertFalse(documento.processo_sigiloso(self.cfg, outro))
        self.assertEqual(documento.pasta_das_transcricoes(self.cfg, outro),
                         self.cfg.pasta_transcricoes)

    def test_pauta_tambem_decide_onde_fica_a_transcricao(self):
        """A regra única do sigilo: o processo que a pauta marca em segredo de
        justiça é transcrito na pasta dos sigilosos - pela tela, pela linha de
        comando ou pela recuperação. processo_sigiloso continua sendo só a
        parte da pasta (a tela distingue os dois motivos)."""
        from helestron.nucleo import caminhos, sigilo
        from testes.test_nucleo import pauta_com_sigiloso

        pauta = self.pasta.raiz / "local" / "pauta.sqlite3"
        pauta.parent.mkdir(parents=True)
        pauta_com_sigiloso(pauta, self.numero)
        self.addCleanup(sigilo.esquecer_pauta)
        with mock.patch.object(caminhos, "ARQUIVO_PAUTA", pauta):
            self.assertFalse(documento.processo_sigiloso(self.cfg, self.numero))
            self.assertEqual(documento.pasta_das_transcricoes(self.cfg, self.numero),
                             self.sig / "Transcricoes")
        self.assertEqual(documento.pasta_das_transcricoes(self.cfg, self.numero),
                         self.cfg.pasta_transcricoes)


if __name__ == "__main__":
    unittest.main()
