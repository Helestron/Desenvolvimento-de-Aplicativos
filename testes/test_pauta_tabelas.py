"""Pauta: reconhecer a tabela de audiências no HTML do eProc, do e-SAJ e de relatórios."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from helestron.pauta import regras
from helestron.pauta.tabelas import (Celula, Reconhecedor, Tabela, campo_do_cabecalho, reconhecer,
                                     tabelas_do_html, total_da_legenda)

from testes import apoio_pauta as ap

R = regras.carregar()


def reconhecer_html(html: str, sistema: str = "eproc", tribunal: str = "TJAL", estrito=True,
                    contexto: str = ""):
    return reconhecer(tabelas_do_html(html, "teste.html"), R, sistema, tribunal, estrito=estrito,
                      contexto=contexto, agora=datetime(2026, 10, 3, 9, 0))


class TestCabecalho(unittest.TestCase):
    def test_sinonimos(self):
        casos = {"Data": "data", "Data/Hora": "data", "Data da Audiência": "data", "DIA": "data",
                 "Hora": "hora", "Horário": "hora", "Início": "hora",
                 "Processo": "processo", "Nº do Processo": "processo", "Número": "processo",
                 "Autos": "processo", "N. do processo:": "processo",
                 "Tipo": "tipo", "Tipo de Audiência": "tipo", "Natureza": "tipo",
                 "Audiência": "tipo", "Situação": "situacao", "Status": "situacao",
                 "Andamento": "situacao", "Local": "local", "Sala": "local", "Vara": "local",
                 "Órgão Julgador": "local", "Classe": "classe", "Classe Processual": "classe",
                 "Partes": "partes", "Autor": "autor", "Polo Ativo": "autor", "Réu": "reu",
                 "Polo Passivo": "reu", "Magistrado": "magistrado", "Juiz(a)": "magistrado",
                 "Conciliador": "magistrado", "Responsável": "magistrado", "Link": "link",
                 "Sala virtual": "link", "Observações": "observacoes",
                 "Data da audiência designada": "data", "Magistrado/Conciliador": "magistrado"}
        for texto, campo in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(campo_do_cabecalho(texto, R), campo)
        for texto in ("Dia da semana", "Sistema", "Ações", "", "Uma frase comprida que não é "
                      "rótulo de coluna nenhuma, só texto do portal explicando alguma coisa"):
            with self.subTest(texto=texto):
                self.assertIsNone(campo_do_cabecalho(texto, R))

    def test_legenda(self):
        self.assertEqual(total_da_legenda("Lista de Audiências (25 registros - 1 a 10):", R), 25)
        self.assertEqual(total_da_legenda("Audiências encontradas: 7", R), 7)
        self.assertEqual(total_da_legenda("12 registro(s)", R), 12)
        self.assertIsNone(total_da_legenda("Pauta do dia", R))


class TestEProc(unittest.TestCase):
    def test_tabela_infra_com_legenda_e_sigilo(self):
        lista = ap.no_periodo(ap.audiencias_padrao("21"), ap.INICIO, ap.FIM)
        html = ap.pagina("<div id='divInfraAreaTela'>" + ap.html_intimacoes("21")
                         + ap.html_eproc(lista[:4], total=8) + "</div>")
        r = reconhecer_html(html, "eproc", "TJRS")
        self.assertEqual(r.tabelas, 1, "as intimações (data + processo + prazo) não são pauta")
        self.assertEqual(r.total_informado, 8)
        self.assertEqual(len(r.audiencias), 4)
        a = r.audiencias[0]
        self.assertEqual((a.sistema, a.tribunal, a.processo, a.data, a.hora, a.tipo, a.situacao),
                         ("eproc", "TJRS", lista[0].processo, date(2026, 10, 5), "09:00",
                          "Conciliação", "Designada"))
        self.assertEqual(a.magistrado, "Dra. Camila Albuquerque")
        self.assertEqual(a.partes, "Maria José dos Santos x Banco do Brasil S.A.")
        self.assertEqual(r.audiencias[1].tipo, "Una")
        self.assertEqual(r.audiencias[2].situacao, "Redesignada")
        self.assertEqual(r.audiencias[3].tipo, "Custódia")
        self.assertFalse(any(x.sigiloso for x in r.audiencias))

        sig = reconhecer_html(ap.html_eproc([lista[4]]), "eproc", "TJRS").audiencias[0]
        self.assertTrue(sig.sigiloso, "o ícone 'Segredo de Justiça' marca o sigilo")
        self.assertEqual(sig.partes, "", "a máscara do portal não vira nome de parte")

    def test_link_virtual(self):
        lista = ap.audiencias_padrao("21")
        a = reconhecer_html(ap.html_eproc([lista[5]]), "eproc", "TJRS").audiencias[0]
        self.assertEqual(a.link, "https://teams.microsoft.com/l/meetup-join/sala-2vcivel")
        self.assertEqual(a.tipo, "Mediação")
        b = reconhecer_html(ap.html_eproc([lista[0]]), "eproc", "TJRS").audiencias[0]
        self.assertEqual(b.link, "", "o link do processo no eProc não é sala virtual")

    def test_vazia_ainda_e_pauta(self):
        r = reconhecer_html(ap.html_eproc([], total=0))
        self.assertTrue(r.reconhecida)
        self.assertEqual(r.audiencias, [])
        self.assertEqual(r.ignoradas, 0, "'Nenhum registro encontrado' não é linha ignorada")


class TestESAJ(unittest.TestCase):
    def test_data_e_hora_juntas(self):
        lista = ap.no_periodo(ap.audiencias_padrao(), ap.INICIO, ap.FIM)
        r = reconhecer_html(ap.html_esaj(lista, "Audiências encontradas: 8"), "esaj")
        self.assertEqual(len(r.audiencias), 8)
        self.assertEqual(r.total_informado, 8)
        por_processo = {a.processo: a for a in r.audiencias}
        a = por_processo[lista[1].processo]
        self.assertEqual((a.data, a.hora, a.classe), (date(2026, 10, 5), "14:30",
                                                      "Procedimento do Juizado Especial Cível"))
        self.assertTrue(por_processo[lista[4].processo].sigiloso)
        self.assertEqual(por_processo[lista[6].processo].situacao, "Cancelada")
        self.assertEqual(por_processo[lista[5].processo].link,
                         "https://teams.microsoft.com/l/meetup-join/sala-2vcivel")
        self.assertEqual(por_processo[lista[5].processo].local,
                         "Virtual (videoconferência) Entrar na sala")


class TestVariacoes(unittest.TestCase):
    def test_colunas_separadas_autor_reu_e_dd_mm_aa(self):
        n1, n2 = ap.numero("0700201"), ap.numero("0700202")
        html = ("<table><tr><td><b>Dt. Audiência</b></td><td><b>Horário</b></td>"
                "<td><b>Nº dos autos</b></td><td><b>Natureza</b></td><td><b>Autor</b></td>"
                "<td><b>Réu</b></td><td><b>Status</b></td><td><b>Sala</b></td></tr>"
                f"<tr><td>05/10/26</td><td>14h00</td><td>{n1}</td><td>Instrução</td>"
                "<td>Fulano</td><td>Beltrano</td><td>Agendada</td><td>Sala 3</td></tr>"
                f"<tr><td>06.10.2026</td><td>9h</td><td>{n2}</td><td>Justificação</td>"
                "<td>Ciclano</td><td></td><td>Suspensa</td><td></td></tr></table>")
        r = reconhecer_html(html, "esaj")
        a, b = r.audiencias
        self.assertEqual((a.data, a.hora, a.tipo, a.partes, a.situacao, a.local),
                         (date(2026, 10, 5), "14:00", "Instrução e julgamento", "Fulano x Beltrano",
                          "Designada", "Sala 3"))
        self.assertEqual((b.data, b.hora, b.partes, b.situacao),
                         (date(2026, 10, 6), "09:00", "Ciclano", "Suspensa"))

    def test_linha_de_grupo_por_dia_e_linha_sem_processo(self):
        n1, n2 = ap.numero("0700301"), ap.numero("0700302")
        html = ("<table><tr><th>Dia</th><th>Hora</th><th>Processo</th><th>Tipo</th></tr>"
                "<tr><td colspan='4'>Segunda-feira, 05/10/2026</td></tr>"
                f"<tr><td></td><td>09:00</td><td>{n1}</td><td>Conciliação</td></tr>"
                "<tr><td></td><td>10:00</td><td></td><td>Pauta concentrada do Cejusc</td></tr>"
                "<tr><td colspan='4'>Terça-feira, 06/10/2026</td></tr>"
                f"<tr><td></td><td>11:00</td><td>{n2}</td><td>Una</td></tr>"
                "<tr><td colspan='4'>Total: 3 audiências</td></tr></table>")
        r = reconhecer_html(html, "esaj")
        self.assertEqual([(a.data, a.hora, a.processo, a.tipo) for a in r.audiencias], [
            (date(2026, 10, 5), "09:00", n1, "Conciliação"),
            (date(2026, 10, 5), "10:00", "", "Mediação"),
            (date(2026, 10, 6), "11:00", n2, "Una")])

    def test_linha_sem_data_e_ignorada_com_aviso(self):
        n1, n2 = ap.numero("0700401"), ap.numero("0700402")
        html = ("<table><tr><th>Data</th><th>Processo</th><th>Tipo</th></tr>"
                f"<tr><td>05/10/2026</td><td>{n1}</td><td>Una</td></tr>"
                f"<tr><td>a definir</td><td>{n2}</td><td>Una</td></tr></table>")
        r = reconhecer_html(html, "esaj")
        self.assertEqual(len(r.audiencias), 1)
        self.assertEqual(r.ignoradas, 1)
        self.assertIn(n2, r.avisos[0])

    def test_cabecalho_repetido_e_coluna_processo_classe(self):
        n1, n2 = ap.numero("0700501"), ap.numero("0700502")
        cab = "<tr><th>Data</th><th>Hora</th><th>Processo/Classe</th><th>Situação</th></tr>"
        html = (f"<table>{cab}<tr><td>05/10/2026</td><td>09:00</td>"
                f"<td>{n1} - Procedimento Comum Cível</td><td>Designada</td></tr>{cab}"
                f"<tr><td>05/10/2026</td><td>10:00</td><td>{n2} - Monitória</td>"
                "<td>Realizada</td></tr></table>")
        r = reconhecer_html(html, "esaj")
        self.assertEqual([(a.processo, a.classe, a.situacao) for a in r.audiencias], [
            (n1, "Procedimento Comum Cível", "Designada"), (n2, "Monitória", "Realizada")])
        self.assertEqual(r.ignoradas, 0)


class TestNaoEPauta(unittest.TestCase):
    def test_tabelas_que_nao_sao_pauta(self):
        n = ap.numero("0700601")
        casos = {
            "intimações": ap.html_intimacoes(),
            "movimentações": ("<table><tr><th>Data</th><th>Movimentação</th><th>Processo</th></tr>"
                              f"<tr><td>05/10/2026</td><td>Conclusos</td><td>{n}</td></tr></table>"),
            "prazos": ("<table><tr><th>Data</th><th>Processo</th><th>Prazo</th></tr>"
                       f"<tr><td>05/10/2026 10:00</td><td>{n}</td><td>5 dias</td></tr></table>"),
            "sem data": ("<table><tr><th>Processo</th><th>Classe</th></tr>"
                         f"<tr><td>{n}</td><td>Monitória</td></tr></table>"),
            "moldura de layout": (f"<table><tr><td><p>Data 05/10/2026 processo {n}</p>"
                                  f"<table><tr><th>Usuário</th></tr><tr><td>x</td></tr></table>"
                                  "</td></tr></table>"),
            "texto sem tabela": f"<p>Audiência em 05/10/2026 às 14:00 no processo {n}</p>",
            "documentos": ("<table><tr><td>05/10/2026</td><td>Petição</td><td>" + n +
                           "</td></tr><tr><td>06/10/2026</td><td>Documento</td><td>" + n +
                           "</td></tr></table>"),
        }
        for nome, html in casos.items():
            with self.subTest(nome=nome):
                r = reconhecer_html(html, "esaj", contexto="Painel do usuário")
                self.assertFalse(r.reconhecida, nome)
                self.assertEqual(r.audiencias, [])

    def test_sem_cabecalho_regra_dos_50_por_cento(self):
        n1, n2, n3 = ap.numero("0700701"), ap.numero("0700702"), ap.numero("0700703")
        html = ("<table>"
                f"<tr><td>05/10/2026 09:00</td><td>{n1}</td><td>Audiência de Conciliação</td>"
                "<td>A x B</td></tr>"
                f"<tr><td>05/10/2026 10:00</td><td>{n2}</td><td>Audiência Una</td>"
                "<td>Cancelada</td></tr>"
                f"<tr><td>06/10/2026 11:00</td><td>{n3}</td><td>Custódia</td><td></td></tr>"
                "<tr><td colspan='4'>Fim da lista</td></tr></table>")
        r = reconhecer_html(html, "esaj")
        self.assertTrue(r.reconhecida)
        self.assertEqual([(a.processo, a.hora, a.tipo) for a in r.audiencias], [
            (n1, "09:00", "Conciliação"), (n2, "10:00", "Una"), (n3, "11:00", "Custódia")])
        self.assertEqual(r.audiencias[0].partes, "A x B")
        self.assertEqual(r.audiencias[1].situacao, "Cancelada")
        # sem hora e sem "audiência" por perto, a página do portal não basta (estrito)...
        sem_hora = html.replace(" 09:00", "").replace(" 10:00", "").replace(" 11:00", "") \
            .replace("Audiência de ", "").replace("Audiência ", "")
        self.assertFalse(reconhecer_html(sem_hora, "esaj").reconhecida)
        # ...mas o relatório que o usuário importou como pauta, sim
        self.assertTrue(reconhecer_html(sem_hora, "arquivo", "", estrito=False).reconhecida)
        self.assertTrue(reconhecer_html(sem_hora, "esaj", contexto="Pauta de audiências")
                        .reconhecida)


class TestParserHTML(unittest.TestCase):
    def test_aninhadas_entidades_e_html_cortado(self):
        n = ap.numero("0700801")
        html = ("<html><body><script>var t = '<table><tr><td>05/10/2026</td></tr></table>';</script>"
                "<table id='fora'><tr><td>Menu</td><td><table class='dentro'>"
                "<tr><th>Data</th><th>Processo</th><th>Tipo&nbsp;de&nbsp;Audi&ecirc;ncia</th></tr>"
                f"<tr><td>05/10/2026<br>14:00</td><td>{n}</td><td>Concilia&ccedil;&atilde;o</td>"
                "</tr></table></td></tr></table><table><tr><td>cortada")
        tabelas = tabelas_do_html(html)
        self.assertEqual(len(tabelas), 3, "o <table> do script não conta")
        dentro = next(t for t in tabelas if "dentro" in t.identificador)
        self.assertEqual(dentro.linhas[0][2].texto, "Tipo de Audiência")
        r = reconhecer(tabelas, R, "esaj", "TJAL")
        self.assertEqual(len(r.audiencias), 1, "a moldura de fora não duplica a audiência")
        self.assertEqual((r.audiencias[0].hora, r.audiencias[0].tipo), ("14:00", "Conciliação"))

    def test_celulas_de_planilha_tipadas(self):
        n = ap.numero("0700802")
        t = Tabela.de_textos([["Data", "Hora", "Processo", "Tipo"],
                              [datetime(2026, 10, 5), 0.625, n, "Una"],
                              [Celula(texto="06/10/2026"), "08:00", None, "Conciliação"]])
        r = Reconhecedor(R, "arquivo", estrito=False).reconhecer([t])
        self.assertEqual([(a.data, a.hora, a.processo) for a in r.audiencias], [
            (date(2026, 10, 5), "15:00", n), (date(2026, 10, 6), "08:00", "")])
        self.assertEqual(r.audiencias[0].tribunal, "TJAL", "o tribunal vem do número")


if __name__ == "__main__":
    unittest.main()
