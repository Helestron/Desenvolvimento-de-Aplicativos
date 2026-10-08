"""O 2º grau pela API: a leitura da relação, o lote, o Testar e os acessos.

O grau (1g ou 2g) é decidido pela regra única (cnj.grau_do_processo): o
número que só existe no 2º grau (o originário do tribunal, órgão 0000; o
plantão e a turma, 9xxx; o recurso interno, /50000) vai ao 2º grau; o resto,
ao grau do lote - a opção Grau das Opções do lote ou, sem ela, o Grau dos
processos dos Ajustes ([download] grau). O e-SAJ usa o mesmo acesso nos dois
graus (esaj:TJAL); o eProc do 2º grau tem o seu (eproc2g:TJAL).

Os portais, o navegador e o motor são dublês que conferem os argumentos: o
caminho real (fábricas, perfis no disco, gateway do cposg5) é testado depois
da mescla (test_integracao_2g.py).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest import mock

from helestron import servicos
from helestron.download.modelos import OK, ResultadoProcesso, ResumoLote
from helestron.nucleo import cnj

from testes.test_servidor_api import CofreFalso
from testes.test_servidor_base import ServidorDeTeste
from testes.test_servidor_pauta import ServicoPautaFalso, modulo_falso

# Os números de exemplo (dígito verificador conferido).
A = "0700001-93.2024.8.02.0058"            # apelação: existe nos dois graus
H = "0803061-28.2025.8.02.0000"            # HC originário (órgão 0000)
E = "0706265-50.2017.8.02.0001/50000"      # embargos de declaração (recurso interno do 2º grau)
P = "0706265-50.2017.8.02.0001"            # o principal dos embargos
I = "0700001-93.2024.8.02.0058/01"         # incidente do 1º grau
PL = "0800103-29.2025.8.02.9002"           # plantão do 2º grau (órgão 9xxx)
TJSP = "1001234-20.2025.8.26.0100"         # e-SAJ sem o 2º grau no Helestron
TRF4 = "5001234-46.2025.4.04.7100"         # eProc com o 2º grau no catálogo
GRAU_INVALIDO = "Grau inválido (use 1g ou 2g)."


class MotorComGrau:
    """Faz as vezes de servicos.baixar_lote: guarda as opções recebidas e
    devolve cada processo no grau da regra única (o que o motor faz)."""

    def __init__(self):
        self.chamadas: list = []

    def __call__(self, numeros, destino, opcoes, ctx, senhas, cofre, cfg):
        self.chamadas.append({"numeros": [n.formatado for n in numeros], "opcoes": opcoes})
        itens = []
        for i, n in enumerate(numeros):
            grau = cnj.grau_do_processo(n, opcoes.grau)
            r = ResultadoProcesso(i + 1, n.formatado, "TJAL", "esaj", grau=grau)
            r.situacao, r.paginas = OK, 10
            r.arquivo = str(Path(destino) / f"{cnj.nome_dos_autos(n, grau)}.pdf")
            ctx.item(r)
            itens.append(r)
        return ResumoLote(itens, Path(destino), Path(destino) / "_controle" / "relatorio.csv")


# ======================================================== leitura da relação
class TestLeituraComGrau(ServidorDeTeste):
    def test_grau_fixo_e_graus(self):
        texto = "\n".join((A, H, E, I, PL, TJSP, TRF4))
        leitura = self.cliente.dados("POST", "/api/relacao/texto", {"texto": texto})
        por_numero = {p["numero"]: p for p in leitura["processos"]}
        self.assertEqual(list(por_numero), [A, H, E, I, PL, TJSP, TRF4])
        esperados = {A: (None, ["1g", "2g"]), H: ("2g", ["1g", "2g"]), E: ("2g", ["1g", "2g"]),
                     I: (None, ["1g", "2g"]), PL: ("2g", ["1g", "2g"]), TJSP: (None, ["1g"]),
                     TRF4: (None, ["1g", "2g"])}
        for numero, (fixo, graus) in esperados.items():
            with self.subTest(numero=numero):
                self.assertEqual(por_numero[numero]["grau_fixo"], fixo)
                self.assertEqual(por_numero[numero]["graus"], graus)
        # o recurso interno do 2º grau não é lido como o principal
        self.assertTrue(por_numero[E]["dependente"])
        self.assertNotIn(P, por_numero)


# ===================================================================== lote
class TestLoteComGrau(ServidorDeTeste):
    def _baixar(self, opcoes: dict | None, processos=(A,)):
        motor = MotorComGrau()
        corpo = {"processos": list(processos), "nome_lote": "Gabinete"}
        if opcoes is not None:
            corpo["opcoes"] = opcoes
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            dados = self.cliente.dados("POST", "/api/download/iniciar", corpo)
            tarefa = self.esperar_tarefa(dados["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        return motor, tarefa

    def test_grau_do_pedido_chega_ao_motor(self):
        for pedido, grau in (("1g", "1g"), ("2g", "2g"), ("2", "2g"), ("2º grau", "2g"),
                             (1, "1g"), ("1G", "1g")):
            with self.subTest(pedido=pedido):
                motor, tarefa = self._baixar({"grau": pedido})
                self.assertEqual(motor.chamadas[0]["opcoes"].grau, grau)
                self.assertEqual(tarefa["resultado"]["grau"], grau)

    def test_sem_grau_vale_o_dos_ajustes(self):
        motor, tarefa = self._baixar({"rebaixar": True})
        self.assertEqual(motor.chamadas[0]["opcoes"].grau, "1g")          # o padrão
        self.assertEqual(tarefa["resultado"]["grau"], "1g")
        self.cfg.definir("download", "grau", "2g")
        for opcoes in ({}, {"grau": ""}, {"grau": None}, None):
            with self.subTest(opcoes=opcoes):
                motor, tarefa = self._baixar(opcoes)
                self.assertEqual(motor.chamadas[0]["opcoes"].grau, "2g")
                self.assertEqual(tarefa["resultado"]["grau"], "2g")
        # o grau do pedido vence o dos Ajustes
        motor, tarefa = self._baixar({"grau": "1g"})
        self.assertEqual(motor.chamadas[0]["opcoes"].grau, "1g")

    def test_grau_invalido_400(self):
        for valor in ("3", "ambos", "2h", True, [], {"g": 2}):
            with self.subTest(valor=valor), \
                    mock.patch("helestron.servicos.baixar_lote") as motor:
                status, env = self.cliente.post("/api/download/iniciar", {
                    "processos": [A], "opcoes": {"grau": valor}})
                self.assertEqual(status, 400)
                self.assertEqual(env["erro"]["codigo"], "valor_invalido")
                self.assertEqual(env["erro"]["mensagem"], GRAU_INVALIDO)
                motor.assert_not_called()
        self.assertEqual(self.cliente.dados("GET", "/api/tarefas"), [])

    def test_itens_com_o_grau_de_cada_um(self):
        # lote do 1º grau: a apelação e o incidente ficam no 1º; o HC, o
        # plantão e os embargos (/50000) vão ao 2º; o principal dos embargos
        # é outro processo, no grau do lote
        leitor = self.eventos()
        _, tarefa = self._baixar({"grau": "1g"}, (A, H, E, P, I, PL))
        detalhe = self.cliente.dados("GET", f"/api/tarefas/{tarefa['id']}")
        graus = {it["numero"]: it["grau"] for it in detalhe["itens"]}
        self.assertEqual(graus, {A: "1g", H: "2g", E: "2g", P: "1g", I: "1g", PL: "2g"})
        evento = leitor.esperar("item", lambda d: d["numero"] == E and d["situacao"] == "OK")
        self.assertEqual(evento["grau"], "2g")
        self.assertTrue(evento["arquivo"].endswith("0706265-50.2017.8.02.0001-50000 (2G).pdf"))
        # lote do 2º grau: só a apelação, o principal e o incidente mudam
        _, tarefa = self._baixar({"grau": "2g"}, (A, H, E, P, I))
        detalhe = self.cliente.dados("GET", f"/api/tarefas/{tarefa['id']}")
        self.assertEqual({it["numero"]: it["grau"] for it in detalhe["itens"]},
                         {A: "2g", H: "2g", E: "2g", P: "2g", I: "2g"})

    def test_item_sempre_traz_o_grau(self):
        # o motor de antes (ResultadoProcesso sem grau decidido) é do 1º grau
        from helestron.servidor import api_processos

        tw = mock.Mock(id="t1")
        r = ResultadoProcesso(1, A, "TJAL", "esaj")
        self.assertEqual(api_processos.item_json(tw, r, Path("."))["grau"], "1g")
        r.grau = "2g"
        self.assertEqual(api_processos.item_json(tw, r, Path("."))["grau"], "2g")
        r.grau = None
        self.assertEqual(api_processos.item_json(tw, r, Path("."))["grau"], "1g")


class TestPautaBaixaNoPrimeiroGrau(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        ServicoPautaFalso.instancias = []
        p = mock.patch.dict(sys.modules, modulo_falso())
        p.start()
        self.addCleanup(p.stop)

    def test_baixar_autos_da_pauta_vai_ao_primeiro_grau(self):
        # a pauta é de audiências do 1º grau: o lote dela é do 1º grau mesmo
        # com os Ajustes no 2º
        self.cfg.definir("download", "grau", "2g")
        motor = MotorComGrau()
        hoje = date.today().isoformat()
        with mock.patch("helestron.servicos.baixar_lote", side_effect=motor):
            dados = self.cliente.dados("POST", "/api/pauta/baixar-autos",
                                       {"ids": ["a1"], "de": hoje, "ate": hoje})
            tarefa = self.esperar_tarefa(dados["tarefa"])
        self.assertEqual(motor.chamadas[0]["opcoes"].grau, "1g")
        self.assertEqual(tarefa["resultado"]["grau"], "1g")


# ================================================================ acessos
class _ComCofre(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        self.cofre = CofreFalso()
        p = mock.patch("helestron.servicos.cofre", return_value=self.cofre)
        p.start()
        self.addCleanup(p.stop)


class TestAcessosComGrau(_ComCofre):
    def test_linha_propria_do_eproc_do_segundo_grau(self):
        self.cfg.definir("unidade", "tribunal", "TJAL")
        self.cfg.definir("eproc", "login", "manual")
        lista = {a["portal"]: a for a in self.cliente.dados("GET", "/api/acessos")}
        self.assertEqual(list(lista), ["esaj:TJAL", "eproc:TJAL", "eproc2g:TJAL"])
        esperado = {
            "esaj:TJAL": ("esaj", "1g", ["1g", "2g"], "TJAL · e-SAJ", "senha"),
            "eproc:TJAL": ("eproc", "1g", ["1g"], "TJAL · eProc", "manual"),
            # a forma de entrar é do sistema: [eproc] login vale para os dois graus
            "eproc2g:TJAL": ("eproc", "2g", ["2g"], "TJAL · eProc (2º grau)", "manual"),
        }
        for portal, (sistema, grau, graus, rotulo, modo) in esperado.items():
            with self.subTest(portal=portal):
                a = lista[portal]
                self.assertEqual((a["sistema"], a["grau"], a["graus"], a["rotulo"], a["modo"]),
                                 (sistema, grau, graus, rotulo, modo))
                self.assertEqual(a["tribunal"], "TJAL")
                self.assertFalse(a["tem_senha"])

    def test_portais_da_unidade_por_tribunal(self):
        for sigla, portais in (("TJSP", ["esaj:TJSP", "eproc:TJSP"]),    # o e-SAJ do TJSP sem 2º grau
                               ("TRF4", ["eproc:TRF4", "eproc2g:TRF4"]),
                               ("TJAM", ["esaj:TJAM"])):
            with self.subTest(sigla=sigla):
                self.cfg.definir("unidade", "tribunal", sigla)
                self.assertEqual([a["portal"] for a in self.cliente.dados("GET", "/api/acessos")],
                                 portais)

    def test_guardar_e_apagar_so_o_segundo_grau(self):
        self.cofre.guardar("eproc:TJAL", "u1", "s1")
        self.app.credenciais_sessao["eproc:TJAL"] = ("u1", "s1-agora")
        dados = self.cliente.dados("POST", "/api/acessos", {"portal": "eproc2g:TJAL",
                                                            "usuario": "u2", "senha": "s2"})
        self.assertEqual((dados["portal"], dados["grau"], dados["sistema"]),
                         ("eproc2g:TJAL", "2g", "eproc"))
        self.assertTrue(dados["guardada"])
        self.assertEqual(self.cofre.obter("eproc2g:TJAL"), ("u2", "s2"))
        # sem a unidade, a linha aparece pelo cofre
        self.assertIn("eproc2g:TJAL", [a["portal"] for a in self.cliente.dados("GET", "/api/acessos")])
        esquecidos = []
        with mock.patch("helestron.download.navegador.esquecer_portal",
                        side_effect=lambda portal: esquecidos.append(portal) or True):
            # outra pessoa no eProc do 2º grau: só a sessão do 2º grau sai
            self.cliente.dados("POST", "/api/acessos", {"portal": "eproc2g:TJAL", "usuario": "u3"})
            self.assertEqual(esquecidos, ["eproc2g:TJAL"])
            self.assertEqual(self.cofre.obter("eproc2g:TJAL"), ("u3", "s2"))
            self.cliente.dados("DELETE", "/api/acessos/eproc2g:TJAL")
        self.assertEqual(esquecidos, ["eproc2g:TJAL", "eproc2g:TJAL"])
        self.assertEqual(self.cofre.obter("eproc2g:TJAL"), ("", ""))
        # o eProc do 1º grau continua como estava
        self.assertEqual(self.cofre.obter("eproc:TJAL"), ("u1", "s1"))
        self.assertEqual(self.app.credenciais_sessao["eproc:TJAL"], ("u1", "s1-agora"))

    def test_so_agora_e_forma_de_entrar_do_segundo_grau(self):
        dados = self.cliente.dados("POST", "/api/acessos", {"portal": "eproc2g:TJAL", "usuario": "u",
                                                            "senha": "p", "lembrar": False})
        self.assertTrue(dados["so_agora"])
        self.assertEqual(self.cofre.dados, {})
        self.assertEqual(self.app.credenciais_sessao, {"eproc2g:TJAL": ("u", "p")})
        self.cliente.dados("POST", "/api/acessos", {"portal": "eproc2g:TJAL", "modo": "manual"})
        self.cfg.recarregar()
        self.assertEqual(self.cfg.texto("eproc", "login"), "manual")
        status, env = self.cliente.post("/api/acessos", {"portal": "eproc2g:TJAL",
                                                         "modo": "certificado"})
        self.assertEqual(status, 400)

    def test_portal_do_segundo_grau_invalido(self):
        for portal, frase in (("eproc2g:TJAM", "O TJAM não tem o eProc do 2º grau no Helestron."),
                              ("eproc2g:TJXX", "Tribunal desconhecido: TJXX."),
                              ("esaj2g:TJAL", "Portal inválido")):
            with self.subTest(portal=portal):
                status, env = self.cliente.post("/api/acessos", {"portal": portal, "usuario": "u"})
                self.assertEqual(status, 400)
                self.assertEqual(env["erro"]["codigo"], "portal_invalido")
                self.assertIn(frase, env["erro"]["mensagem"])
        status, _ = self.cliente.delete("/api/acessos/esaj2g:TJAL")
        self.assertEqual(status, 400)

    def test_tribunais_com_os_graus(self):
        lista = {t["sigla"]: t for t in self.cliente.dados("GET", "/api/tribunais")}
        self.assertEqual((lista["TJAL"]["graus"], lista["TJAL"]["graus_alternativo"]),
                         (["1g", "2g"], ["1g", "2g"]))
        # o eProc do TJSP tem o 2º grau no catálogo, mas o e-SAJ (o principal)
        # não: o 2º grau do TJSP não é baixado
        self.assertEqual((lista["TJSP"]["graus"], lista["TJSP"]["graus_alternativo"]),
                         (["1g"], ["1g"]))
        self.assertEqual((lista["TRF4"]["graus"], lista["TRF4"]["graus_alternativo"]),
                         (["1g", "2g"], []))


class TestTestarComGrau(_ComCofre):
    def setUp(self):
        super().setUp()
        self.cofre.guardar("esaj:TJAL", "us", "ps")
        self.cofre.guardar("eproc:TJAL", "ue", "pe")
        self.cofre.guardar("eproc2g:TJAL", "ue2", "pe2")
        self.chamadas: list = []

        def falso(tribunal, opcoes, ctx, credenciais):
            self.chamadas.append((tribunal.portal, tribunal.grau, tribunal.sistema, credenciais))

        p = mock.patch("helestron.servicos.testar_login", side_effect=falso)
        p.start()
        self.addCleanup(p.stop)

    def _testar(self, corpo):
        self.chamadas.clear()
        tarefa = self.esperar_tarefa(self.cliente.dados("POST", "/api/acessos/testar", corpo)["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        return tarefa

    def test_primeiro_grau_como_antes(self):
        for corpo in ({"tribunal": "TJAL"}, {"tribunal": "TJAL", "sistema": "esaj"},
                      {"tribunal": "TJAL", "sistema": "esaj", "grau": "1g"}):
            with self.subTest(corpo=corpo):
                tarefa = self._testar(corpo)
                self.assertEqual(self.chamadas, [("esaj:TJAL", "1g", "esaj", ("us", "ps"))])
                self.assertEqual(tarefa["titulo"], "Testar o acesso ao TJAL · e-SAJ")
                self.assertEqual(tarefa["resultado"]["mensagem"], "Acesso ao TJAL · e-SAJ confirmado.")
        tarefa = self._testar({"tribunal": "TJAL", "sistema": "eproc"})
        self.assertEqual(self.chamadas, [("eproc:TJAL", "1g", "eproc", ("ue", "pe"))])
        self.assertEqual(tarefa["titulo"], "Testar o acesso ao TJAL · eProc")

    def test_segundo_grau_do_esaj_usa_o_acesso_do_esaj(self):
        tarefa = self._testar({"tribunal": "TJAL", "sistema": "esaj", "grau": "2g"})
        self.assertEqual(self.chamadas, [("esaj:TJAL", "2g", "esaj", ("us", "ps"))])
        self.assertEqual(tarefa["titulo"], "Testar o acesso ao TJAL · e-SAJ (2º grau)")
        self.assertEqual(tarefa["resultado"]["mensagem"],
                         "Acesso ao TJAL · e-SAJ (2º grau) confirmado.")
        self.assertEqual(tarefa["resultado"]["grau"], "2g")

    def test_segundo_grau_do_eproc_usa_o_acesso_proprio(self):
        for corpo in ({"tribunal": "TJAL", "sistema": "eproc", "grau": "2g"},
                      {"tribunal": "TJAL", "sistema": "eproc", "grau": "2"},
                      {"tribunal": "eproc2g:TJAL"}):
            with self.subTest(corpo=corpo):
                tarefa = self._testar(corpo)
                # a senha do eProc do 1º grau nunca vai ao 2º grau
                self.assertEqual(self.chamadas, [("eproc2g:TJAL", "2g", "eproc", ("ue2", "pe2"))])
                self.assertEqual(tarefa["titulo"], "Testar o acesso ao TJAL · eProc (2º grau)")

    def test_segundo_grau_do_eproc_sem_senha_testa_sem_credenciais(self):
        self.cofre.apagar("eproc2g:TJAL")
        self._testar({"tribunal": "TJAL", "sistema": "eproc", "grau": "2g"})
        self.assertEqual(self.chamadas, [("eproc2g:TJAL", "2g", "eproc", None)])

    def test_grau_invalido_ou_que_o_portal_nao_tem(self):
        for corpo, frase in (
                ({"tribunal": "TJAL", "grau": "3"}, GRAU_INVALIDO),
                ({"tribunal": "TJAL", "sistema": "esaj", "grau": "ambos"}, GRAU_INVALIDO),
                ({"tribunal": "TJSP", "grau": "2g"}, "O TJSP · e-SAJ não tem o 2º grau no Helestron."),
                ({"tribunal": "TJSP", "sistema": "esaj", "grau": "2g"},
                 "O TJSP · e-SAJ não tem o 2º grau no Helestron.")):
            with self.subTest(corpo=corpo):
                status, env = self.cliente.post("/api/acessos/testar", corpo)
                self.assertEqual(status, 400)
                self.assertEqual(env["erro"]["codigo"], "valor_invalido")
                self.assertEqual(env["erro"]["mensagem"], frase)
        self.assertEqual(self.chamadas, [])


# ============================================================== endereços
class TestEnderecosDoEprocDoSegundoGrau(ServidorDeTeste):
    def test_linha_eproc2g_abre_os_enderecos_do_eproc(self):
        from helestron.nucleo import tribunais

        arquivo = self.amb.local / "enderecos-locais.json"
        with mock.patch.object(tribunais, "ARQUIVO_LOCAL", arquivo):
            dados = self.cliente.dados("GET", "/api/tribunais/enderecos/eproc2g:TJAL")
            self.assertEqual((dados["portal"], dados["rotulo"]), ("eproc:TJAL", "TJAL · eProc"))
            self.assertEqual([(e["grau"], e["url"]) for e in dados["enderecos"]],
                             [("1g", "https://eproc1g.tjal.jus.br/eproc/"),
                              ("2g", "https://eproc2g.tjal.jus.br/eproc/")])
            # pela linha do 2º grau, sem dizer o grau: corrige o do 2º grau
            novo = "https://novo-eproc2g.tjal.jus.br/eproc/"
            dados = self.cliente.dados("POST", "/api/tribunais/enderecos",
                                       {"portal": "eproc2g:TJAL", "url": novo})
            self.assertEqual(dados["portal"], "eproc:TJAL")
            self.assertEqual([(e["grau"], e["corrigido"]) for e in dados["enderecos"]],
                             [("1g", False), ("2g", True)])
            self.assertEqual(tribunais.por_portal("eproc2g:TJAL").urls_para(), [novo])
            self.assertEqual(tribunais.por_portal("eproc:TJAL").urls_para(),
                             ["https://eproc1g.tjal.jus.br/eproc/"])
            self.assertEqual(self.cliente.dados("GET", "/api/tribunais/enderecos"),
                             [{"portal": "eproc:TJAL", "grau": "2g", "rotulo": "2º grau", "url": novo,
                               "rotulo_portal": "TJAL · eProc"}])
            # o do 2º grau do e-SAJ (cposg5), pelo grau
            dados = self.cliente.dados("POST", "/api/tribunais/enderecos",
                                       {"portal": "esaj:TJAL", "grau": "2g",
                                        "url": "https://www3.tjal.jus.br/cposg5"})
            self.assertEqual(tribunais.por_sigla("TJAL").no_grau("2g").urls_para(),
                             ["https://www3.tjal.jus.br/cposg5"])
            self.assertEqual(tribunais.por_sigla("TJAL").urls_para(), ["https://www2.tjal.jus.br"])


# ================================================================ Ajustes
class TestAjusteDoGrau(ServidorDeTeste):
    def test_campo_no_esquema(self):
        dados = self.cliente.dados("GET", "/api/config")
        campo = next(c for c in dados["esquema"] if (c["secao"], c["chave"]) == ("download", "grau"))
        self.assertEqual((campo["tipo"], campo["rotulo"]), ("escolha", "Grau dos processos"))
        self.assertEqual(campo["opcoes"], [{"valor": "1g", "rotulo": "1º grau"},
                                           {"valor": "2g", "rotulo": "2º grau"}])
        self.assertIn("Processos", campo["ajuda"])
        self.assertEqual(dados["valores"]["download"]["grau"], "1g")

    def test_grava_e_valida(self):
        for valor, gravado in (("2g", "2g"), ("1g", "1g"), ("2", "2g"), ("2º grau", "2g")):
            with self.subTest(valor=valor):
                self.assertEqual(self.cliente.dados("POST", "/api/config", {
                    "secao": "download", "chave": "grau", "valor": valor}), {"valor": gravado})
                self.cfg.recarregar()
                self.assertEqual(self.cfg.texto("download", "grau"), gravado)
        for valor in ("3", "ambos", ""):
            with self.subTest(valor=valor):
                status, env = self.cliente.post("/api/config", {"secao": "download", "chave": "grau",
                                                                "valor": valor})
                self.assertEqual(status, 400)
                self.assertEqual(env["erro"]["codigo"], "valor_invalido")

    def test_valor_editado_a_mao_como_o_download_le(self):
        for no_ini, mostrado in (("2", "2g"), ("2º", "2g"), ("xyz", "1g"), ("", "1g")):
            with self.subTest(no_ini=no_ini):
                self.cfg.definir("download", "grau", no_ini)
                valores = self.cliente.dados("GET", "/api/config")["valores"]
                self.assertEqual(valores["download"]["grau"], mostrado)
                self.assertEqual(servicos.opcoes_download(self.cfg).grau, mostrado)


# ================================================================== Início
class TestResumoDoAcervo(ServidorDeTeste):
    def test_processo_com_os_dois_graus_conta_uma_vez(self):
        # Acervo.pdfs() por chave dos autos (compartilhar): 'A' e 'A (2G)' são
        # dois arquivos do mesmo processo
        p = Path("x.pdf")
        pdfs = {A: p, f"{A} (2G)": p, f"{cnj.ler(I).nome_arquivo}": p,
                f"{cnj.ler(E).nome_arquivo} (2G)": p, P: p, f"{H} (2G)": p}
        self.assertEqual(servicos._processos_distintos(pdfs), 5)
        with mock.patch("helestron.compartilhar.mcp_servidor.Acervo.pdfs", return_value=pdfs), \
                mock.patch("helestron.compartilhar.mcp_servidor.Acervo.transcricoes",
                           return_value={}):
            self.assertEqual(servicos.resumo_acervo(self.cfg)["processos"], 5)
            self.assertEqual(self.cliente.dados("GET", "/api/estado")["resumo"]["processos"], 5)
        self.assertEqual(servicos._processos_distintos({A: p, "B": p}), 2)
