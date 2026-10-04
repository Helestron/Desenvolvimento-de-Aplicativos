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


# ======================================================= revisão adversarial
def _tabela(*linhas, **extra) -> Tabela:
    return Tabela.de_textos([list(x) for x in linhas], **extra)


def _relatorio(*tabelas, contexto=""):
    return Reconhecedor(R, "arquivo", estrito=False, agora=datetime(2026, 10, 3, 9, 0)) \
        .reconhecer(list(tabelas), contexto)


class TestDataEmUmaLinhaSo(unittest.TestCase):
    """A data escrita uma vez para as audiências do dia (rowspan, célula mesclada,
    "suprimir se duplicado", linha de grupo com a contagem): nenhuma se perde."""

    N = [ap.numero(f"070090{i}") for i in range(1, 5)]

    def esperado(self):
        n = self.N
        return [(date(2026, 10, 5), "09:00", n[0]), (date(2026, 10, 5), "10:00", n[1]),
                (date(2026, 10, 5), "11:00", n[2]), (date(2026, 10, 6), "09:00", n[3])]

    def test_rowspan_na_data(self):
        n = self.N
        html = ("<table><tr><th>Data</th><th>Hora</th><th>Processo</th><th>Tipo</th>"
                "<th>Partes</th></tr>"
                f"<tr><td rowspan='3'>05/10/2026</td><td>09:00</td><td>{n[0]}</td>"
                "<td>Conciliação</td><td>A x B</td></tr>"
                f"<tr><td>10:00</td><td>{n[1]}</td><td>Una</td><td>C x D</td></tr>"
                f"<tr><td>11:00</td><td>{n[2]}</td><td>Instrução</td><td>E x F</td></tr>"
                f"<tr><td>06/10/2026</td><td>09:00</td><td>{n[3]}</td><td>Una</td>"
                "<td>G x H</td></tr></table>")
        for estrito in (True, False):
            with self.subTest(estrito=estrito):
                r = reconhecer_html(html, "esaj", estrito=estrito)
                self.assertEqual([(a.data, a.hora, a.processo) for a in r.audiencias],
                                 self.esperado())
                self.assertEqual([a.partes for a in r.audiencias],
                                 ["A x B", "C x D", "E x F", "G x H"], "nada escorregou de coluna")
                self.assertEqual(r.ignoradas, 0)

    def test_rowspan_na_hora_nao_desloca_as_colunas(self):
        n = self.N
        html = ("<table><tr><th>Data</th><th>Hora</th><th>Processo</th><th>Tipo</th>"
                "<th>Partes</th></tr>"
                f"<tr><td>05/10/2026</td><td rowspan='2'>09:00</td><td>{n[0]}</td>"
                "<td>Conciliação</td><td>A x B</td></tr>"
                f"<tr><td>05/10/2026</td><td>{n[1]}</td><td>Una</td><td>C x D</td></tr>"
                "</table>")
        r = reconhecer_html(html, "esaj")
        self.assertEqual([(a.hora, a.processo, a.tipo, a.partes) for a in r.audiencias], [
            ("09:00", n[0], "Conciliação", "A x B"), ("09:00", n[1], "Una", "C x D")])

    def test_rowspan_vindo_do_navegador_e_moldura_que_nao_se_repete(self):
        dados = {"linhas": [
            [{"texto": "Data"}, {"texto": "Hora"}, {"texto": "Processo"}],
            [{"texto": "05/10/2026", "rowspan": 2}, {"texto": "09:00"}, {"texto": self.N[0]}],
            [{"texto": "10:00"}, {"texto": self.N[1]}],
            [{"texto": "menu", "rowspan": 2, "aninhada": True}, {"texto": "x"}],
            [{"texto": "y"}]]}
        t = Tabela.de_js(dados)
        self.assertEqual([c.texto for c in t.linhas[2]], ["05/10/2026", "10:00", self.N[1]])
        self.assertEqual([(c.texto, c.aninhada) for c in t.linhas[4]], [("", False), ("y", False)])

    def test_data_so_na_primeira_linha_do_dia(self):
        """Planilha com a coluna Data mesclada (o openpyxl devolve None) ou com a data
        escrita uma vez por dia."""
        n = self.N
        r = _relatorio(_tabela(
            ["Data", "Hora", "Processo", "Tipo"],
            [datetime(2026, 10, 5), "09:00", n[0], "Conciliação"],
            [None, "10:00", n[1], "Una"],
            ["", "11:00", n[2], "Instrução"],
            [datetime(2026, 10, 6), "09:00", n[3], "Una"]))
        self.assertEqual([(a.data, a.hora, a.processo) for a in r.audiencias], self.esperado())
        self.assertEqual((r.ignoradas, r.avisos), (0, []))

    def test_continuacao_da_linha_de_cima_nao_vira_audiencia(self):
        n = self.N
        r = _relatorio(_tabela(["Data", "Hora", "Processo", "Partes"],
                               ["05/10/2026", "09:00", n[0], "Maria x Banco do"],
                               ["", "", "", "Brasil S.A."],
                               ["", "10:00", n[1], "C x D"]))
        self.assertEqual([(a.data, a.processo) for a in r.audiencias],
                         [(date(2026, 10, 5), n[0]), (date(2026, 10, 5), n[1])])

    def test_texto_que_nao_e_data_nao_herda_a_de_cima(self):
        n = self.N
        r = _relatorio(_tabela(["Data", "Processo", "Tipo"],
                               ["05/10/2026", n[0], "Una"],
                               ["a definir", n[1], "Una"]))
        self.assertEqual([a.processo for a in r.audiencias], [n[0]])
        self.assertEqual(r.ignoradas, 1)

    def test_linha_de_grupo_com_a_contagem_ao_lado(self):
        n = self.N
        for grupo in (["05/10/2026 - Segunda-feira", "", "3 audiências", ""],
                      ["Segunda-feira", "", "", "05/10/2026"],
                      ["Data: 05/10/2026", "Total: 3", "", ""],
                      ["05/10/2026", "(3)", "", ""]):
            with self.subTest(grupo=grupo):
                r = _relatorio(_tabela(
                    ["Data", "Hora", "Partes", "Processo"], grupo,
                    ["", "09:00", "A x B", n[0]], ["", "10:00", "C x D", n[1]],
                    ["", "11:00", "E x F", n[2]],
                    ["06/10/2026 - Terça-feira", "", "1 audiência", ""],
                    ["", "09:00", "G x H", n[3]]))
                self.assertEqual([(a.data, a.hora, a.processo) for a in r.audiencias],
                                 self.esperado())
                self.assertFalse(any("audiênc" in a.partes for a in r.audiencias),
                                 "a contagem não vira audiência")


class TestCabecalhoDepoisDoPreambulo(unittest.TestCase):
    N = [ap.numero(f"070091{i}") for i in range(1, 4)]

    def linhas(self):
        n = self.N
        return [["Data", "Hora", "Processo", "Tipo de audiência", "Partes"],
                ["05/10/2026", "09:00", n[0], "Conciliação", "A x B"],
                ["05/10/2026", "10:00", n[1], "Una", "C x D"],
                ["06/10/2026", "11:00", n[2], "Instrução", "E x F"]]

    def confere(self, r):
        self.assertTrue(r.reconhecida)
        self.assertEqual([a.processo for a in r.audiencias], self.N)
        self.assertEqual(r.audiencias[1].tipo, "Una")

    def test_preambulo_rotulo_e_valor(self):
        for preambulo in ([["Relatório de audiências"],
                           ["Data:", "03/10/2026", "Hora:", "10:15"]],
                          [["Vara:", "2ª Vara Cível", "Data de emissão:", "03/10/2026"]],
                          [["Data:", datetime(2026, 10, 3), "Emitido por:", "Fulano"]]):
            with self.subTest(preambulo=preambulo):
                self.confere(_relatorio(_tabela(*preambulo, [], *self.linhas())))

    def test_preambulo_longo(self):
        titulo = [["Poder Judiciário"], ["Tribunal de Justiça de Alagoas"],
                  ["Comarca de Maceió"], [], ["2ª Vara Cível da Capital"],
                  ["Pauta de audiências"], [],
                  ["Período: 05/10/2026 a 16/10/2026"], ["Emitido em 03/10/2026 por Fulano"]]
        self.confere(_relatorio(_tabela(*titulo, *self.linhas())))
        # sem o cabeçalho: a regra dos 50 % não conta as linhas do título
        sem_cabecalho = _relatorio(_tabela(*titulo, *self.linhas()[1:]))
        self.assertEqual([a.processo for a in sem_cabecalho.audiencias], self.N)
        self.assertEqual(sem_cabecalho.ignoradas, 0)

    def test_cabecalho_em_duas_linhas(self):
        html = ("<table><tr><th colspan='2'>Audiência</th><th rowspan='2'>Processo</th>"
                "<th rowspan='2'>Partes</th><th rowspan='2'>Situação</th></tr>"
                "<tr><th>Data</th><th>Hora</th></tr>"
                + "".join(f"<tr><td>{d}</td><td>{h}</td><td>{p}</td><td>{x}</td><td>Designada</td>"
                          "</tr>" for d, h, p, _t, x in self.linhas()[1:]) + "</table>")
        r = reconhecer_html(html, "arquivo", "", estrito=False)
        self.assertEqual([(a.data, a.hora, a.processo, a.partes) for a in r.audiencias], [
            (date(2026, 10, 5), "09:00", self.N[0], "A x B"),
            (date(2026, 10, 5), "10:00", self.N[1], "C x D"),
            (date(2026, 10, 6), "11:00", self.N[2], "E x F")])
        # sem o rowspan (planilha: célula vazia embaixo dos rótulos de cima)
        r = _relatorio(_tabela(["Audiência", "", "Processo", "Partes"], ["Data", "Hora", "", ""],
                               *[[d, h, p, x] for d, h, p, _t, x in self.linhas()[1:]]))
        self.assertEqual([a.processo for a in r.audiencias], self.N)

    def test_intimacoes_continuam_fora(self):
        r = _relatorio(*tabelas_do_html(ap.html_intimacoes()))
        self.assertFalse(r.reconhecida)


class TestSoAPropriaTabelaDizQueEPauta(unittest.TestCase):
    """O título da página ("Pauta de Audiências") não transforma em pauta a tabela
    de intimações ao lado; a fila de processos e o "Último movimento" não são pauta."""

    N = [ap.numero(f"070092{i}") for i in range(1, 3)]

    def test_intimacoes_na_pagina_da_pauta(self):
        lista = ap.no_periodo(ap.audiencias_padrao("21"), ap.INICIO, ap.FIM)
        html = ap.pagina(ap.html_intimacoes("21") + ap.html_eproc(lista[:4], total=8))
        r = reconhecer_html(html, "eproc", "TJRS", contexto="Audiência > Pauta de Audiências")
        self.assertEqual(r.tabelas, 1)
        self.assertEqual(len(r.audiencias), 4, "as duas intimações não viraram audiência")
        self.assertNotIn(ap.numero("0700901", "21"), {a.processo for a in r.audiencias})
        sozinha = reconhecer_html(ap.html_intimacoes(), "esaj", contexto="Pauta de Audiências")
        self.assertFalse(sozinha.reconhecida)

    def test_fila_de_processos_e_ultimo_movimento(self):
        n = self.N
        casos = {
            "fila": ("<table><tr><th>Processo</th><th>Classe</th><th>Assunto</th>"
                     "<th>Data de recebimento</th><th>Local físico</th></tr>"
                     f"<tr><td>{n[0]}</td><td>Monitória</td><td>Cobrança</td>"
                     "<td>01/10/2026</td><td>Cartório</td></tr>"
                     f"<tr><td>{n[1]}</td><td>Alimentos</td><td>Fixação</td>"
                     "<td>02/10/2026</td><td>Gabinete</td></tr></table>"),
            "último movimento": ("<table><tr><th>Data</th><th>Último movimento</th>"
                                 f"<th>Processo</th></tr><tr><td>01/10/2026</td><td>Conclusos</td>"
                                 f"<td>{n[0]}</td></tr></table>"),
            "só data e processo": ("<table><tr><th>Data</th><th>Processo</th><th>Partes</th></tr>"
                                   f"<tr><td>01/10/2026</td><td>{n[0]}</td><td>A x B</td></tr>"
                                   "</table>"),
        }
        for nome, html in casos.items():
            with self.subTest(nome=nome):
                self.assertFalse(reconhecer_html(html, "esaj").reconhecida)
        for nome in ("fila", "último movimento"):
            with self.subTest(nome=nome, relatorio=True):
                self.assertFalse(reconhecer_html(casos[nome], "arquivo", "", estrito=False)
                                 .reconhecida)
        # data e processo, numa página (ou legenda) de pauta: é pauta
        self.assertTrue(reconhecer_html(casos["só data e processo"], "esaj",
                                        contexto="Pauta de Audiências").reconhecida)
        self.assertTrue(reconhecer_html(casos["só data e processo"].replace(
            "<table>", "<table><caption>Audiências do dia</caption>"), "esaj").reconhecida)


class TestPublicoNaoDesfazOSigilo(unittest.TestCase):
    """"Ministério Público", "Defensoria Pública", "Ação Civil Pública" ao lado do
    selo de segredo de justiça: o sigilo fica."""

    N = ap.numero("0700931")

    def com_cabecalho(self, processo="", partes="", classe="", local="", sigilo=None):
        cab = "<th>Data</th><th>Hora</th><th>Processo</th><th>Classe</th><th>Partes</th>" \
              "<th>Local</th>" + ("<th>Sigilo</th>" if sigilo is not None else "")
        linha = (f"<td>05/10/2026</td><td>09:00</td><td>{self.N}{processo}</td><td>{classe}</td>"
                 f"<td>{partes}</td><td>{local}</td>"
                 + (f"<td>{sigilo}</td>" if sigilo is not None else ""))
        return reconhecer_html(f"<table><tr>{cab}</tr><tr>{linha}</tr></table>", "esaj") \
            .audiencias[0]

    def test_com_cabecalho(self):
        icone = "<img src='data:,' title='Segredo de Justiça'>"
        casos = {
            "ícone nas partes do MP": dict(partes=f"Ministério Público do Estado de Alagoas x "
                                                  f"João da Silva {icone}"),
            "classe da ACP": dict(classe="Ação Civil Pública - Segredo de Justiça"),
            "Defensoria no local": dict(local=f"Sala da Defensoria Pública {icone}"),
            "ícone no processo, MP nas partes": dict(processo=f" {icone}",
                                                     partes="Ministério Público x João"),
            "coluna Sigilo": dict(sigilo="Segredo de Justiça",
                                  partes="Ministério Público x João"),
            "nível 1": dict(sigilo="Nível 1"),
        }
        for nome, campos in casos.items():
            with self.subTest(nome=nome):
                self.assertTrue(self.com_cabecalho(**campos).sigiloso)
        for nome, campos in {"coluna Sigilo: Público": dict(sigilo="Público"),
                             "sem sigilo": dict(sigilo="Sem sigilo (Nível 0)"),
                             "só o MP": dict(partes="Ministério Público x João")}.items():
            with self.subTest(nome=nome):
                self.assertFalse(self.com_cabecalho(**campos).sigiloso)

    def test_sem_cabecalho_e_linhas_soltas(self):
        rec = Reconhecedor(R, "esaj", "TJAL")
        for outra in ("Ministério Público x João da Silva", "Sala da Defensoria Pública",
                      "Fazenda Pública do Estado x Fulano"):
            with self.subTest(outra=outra):
                linha = [Celula(texto="05/10/2026 09:00"), Celula(texto=self.N),
                         Celula(texto="Segredo de Justiça"), Celula(texto=outra)]
                self.assertTrue(rec.linha_livre(linha).sigiloso)
                linha[2] = Celula(texto="Público")
                self.assertFalse(rec.linha_livre(linha).sigiloso)
        html = ("<table>" + "".join(
            f"<tr><td>05/10/2026 0{i}:00</td><td>{ap.numero(f'070094{i}')}</td>"
            "<td>Segredo de Justiça</td><td>Ministério Público x Adolescente</td></tr>"
            for i in range(1, 4)) + "</table>")
        r = reconhecer_html(html, "esaj", contexto="Pauta de audiências")
        self.assertEqual(len(r.audiencias), 3)
        self.assertTrue(all(a.sigiloso for a in r.audiencias))

    def test_regras_do_arquivo_e_embutidas_iguais(self):
        self.assertEqual(R.dados["sem_sigilo"], regras.PADROES["sem_sigilo"])
        self.assertEqual(R.dados["negativos"], regras.PADROES["negativos"])


if __name__ == "__main__":
    unittest.main()
