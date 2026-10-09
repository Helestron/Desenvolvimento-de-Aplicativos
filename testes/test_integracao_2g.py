"""Integração do 2º grau (rodada de integração, §5 do desenho da 1.1.0).

O que só se testa com as cinco frentes juntas: o motor e as fábricas de
verdade (F3) chamando o e-SAJ do 2º grau de verdade (F2) contra o e-SAJ de
mentira (testes/apoio_esaj2g.py: CAS, cpopg, cposg5 e Pasta Digital), com o
Chromium dos testes; depois o preparo, o texto, o índice e o conector MCP
(F4) lendo o que o motor gravou; a linha de comando (F3) com --grau e o JSON
e o CSV; e a API (F5) testando, apagando e baixando pelo caminho real.

O que é de mentira aqui: o servidor do e-SAJ, o eProc (apoio_eproc, quando o
teste o quer) e o canal do navegador (o Navegador de verdade, com o Chromium
dos testes e sem janela). O eProc alternativo do catálogo do TJAL é um portal
de verdade: nos testes ele é neutralizado (endereços .invalid e um portal que
não acha nada), salvo onde o teste põe o eProc de mentira no lugar.

Números do Anexo B do desenho (dígito verificador conferido): A, a apelação
que existe nos dois graus; H, o HC originário (órgão 0000); P e E, o
principal e os embargos de declaração (/50000); S, público no 1º grau e
sigiloso no 2º; A2, um número do TJAL que o e-SAJ de mentira não tem; AM,
um do TJAM (e-SAJ sem o 2º grau no Helestron).

Os casos que abrem o Chromium pulam sem ele (rodam no CI); os da API sem
navegador e o do sigilo sabido pela pasta rodam sempre.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

from helestron import servicos
from helestron.compartilhar import chatgpt, mcp_servidor, nuvem, preparo, textos
from helestron.download import cli, contexto, eproc, esaj, modelos, motor, navegador
from helestron.nucleo import caminhos, cnj, config, paginacao, sigilo, tribunais
from helestron.nucleo.cofre_senhas import CofreSenhas

from testes import apoio_download as apoio
from testes import apoio_eproc as ae
from testes import apoio_esaj2g as falso
from testes.apoio_esaj2g import CODIGO, NUMEROS, SENHA, SENHA_S_2G, USUARIO
from testes.test_servidor_base import ServidorDeTeste

A, H, E, P, S = (NUMEROS[k] for k in ("A", "H", "E", "P", "S"))
A2 = cnj.ler("0700002-78.2024.8.02.0058")        # o e-SAJ de mentira não o tem
E2 = cnj.ler("0706265-50.2017.8.02.0001/50001")   # agravo interno: também não
AM = apoio.numero("0700001", tr="04", origem="0001")   # TJAM: e-SAJ sem o 2º grau
A_2G = cnj.nome_dos_autos(A, "2g")                 # "0700001-93.2024.8.02.0058 (2G)"
E_2G = cnj.nome_dos_autos(E, "2g")                 # "...0001-50000 (2G)"

# A fábrica de portais de verdade (o teste a envolve para neutralizar o eProc).
_FABRICA_PORTAL = motor.fabrica_portal_padrao


def _chromium() -> tuple[str, str | None] | None:
    return ae.navegador_de_teste()


def ler_csv(arquivo: Path) -> list[dict]:
    texto = Path(arquivo).read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def primeira_linha(arquivo: Path) -> str:
    return Path(arquivo).read_text(encoding="utf-8").split("\n", 1)[0]


class EProcNeutro:
    """O eProc do catálogo nos testes: nunca sai para a rede (o do TJAL é um
    portal de verdade). Registra o portal, o grau e as credenciais que o
    motor lhe deu e não acha nada - o "não encontrado" dos dois sistemas."""

    sistema = "eproc"

    def __init__(self, tribunal, credenciais, registro: list):
        self.tribunal = tribunal
        self.grau = tribunal.grau
        self.sigilosos_apurados: set[str] = set()
        registro.append((tribunal.portal, tribunal.grau, credenciais))

    def entrar(self) -> None:
        pass

    def baixar(self, numero, destino_pdf, senha=None):
        sufixo = " (2º grau)" if self.grau == "2g" else ""
        raise modelos.ProcessoNaoEncontrado(
            f"não encontrado no eProc do {self.tribunal.sigla}{sufixo}")


class Contexto2G(apoio.ContextoGravador):
    """Responde o código de verificação (o do e-mail do e-SAJ, o do
    aplicativo do eProc) e guarda os eventos."""

    def __init__(self):
        super().__init__()
        self.eventos: list[tuple[str, dict]] = []

    def pedir_codigo(self, titulo, mensagem, prazo_s=600, reenviavel=True):
        self.pedidos_codigo.append((titulo, mensagem, prazo_s))
        return ae.CODIGO if "eProc" in titulo else CODIGO

    def evento(self, tipo, **dados):
        self.eventos.append((tipo, dados))


class _PortaisDeMentira:
    """O e-SAJ de mentira no catálogo (enderecos-locais.json), as fábricas
    verdadeiras do motor com o Chromium dos testes (sem janela) e o eProc do
    catálogo neutralizado - ou o eProc de mentira, se o teste o puser em
    ``eproc_falso``. ``abertos``: os perfis de navegador abertos, na ordem;
    ``eproc_neutro``: (portal, grau, credenciais) de cada eProc neutralizado."""

    eproc_falso = None
    neutralizar_eproc = True

    def ligar_portais(self, local: Path) -> None:
        self.abertos: list[Path] = []
        self.eproc_neutro: list[tuple] = []
        self.eproc_falso = None
        self.neutralizar_eproc = True
        canal, exe = _chromium() or ("chromium", None)
        real = navegador.Navegador

        def fabrica_navegador(perfil, **k):
            perfil = Path(perfil)
            self.abertos.append(perfil)
            k.update(visivel=False, canal=canal, executavel=exe)
            if perfil.name.startswith("eproc"):
                if self.eproc_falso is None:
                    return apoio.NavegadorFalso()
                return ae.NavegadorComEProc(self.eproc_falso, perfil, **k)
            return real(perfil, **k)

        def fabrica_portal(nav, tribunal, opcoes, ctx, credenciais):
            if tribunal.sistema == "eproc" and self.neutralizar_eproc \
                    and self.eproc_falso is None:
                return EProcNeutro(tribunal, credenciais, self.eproc_neutro)
            return _FABRICA_PORTAL(nav, tribunal, opcoes, ctx, credenciais)

        self.arquivo_local = local / "enderecos-locais.json"
        for p in (mock.patch.object(navegador, "Navegador", fabrica_navegador),
                  mock.patch.object(motor, "fabrica_portal_padrao", fabrica_portal),
                  mock.patch.object(tribunais, "ARQUIVO_LOCAL", self.arquivo_local),
                  mock.patch.object(esaj, "INTERVALO_POLL_S", 0.2),
                  mock.patch.object(esaj, "ESPERA_CONFIRMA_CODIGO_S", 2),
                  mock.patch.object(motor, "ESPERA_ENTRE_TENTATIVAS_S", 0.0),
                  mock.patch.object(eproc, "PAUSA_DOCUMENTOS_S", 0)):
            p.start()
            self.addCleanup(p.stop)
        self.apontar_para(self.servidor)

    def apontar_para(self, servidor) -> None:
        """O TJAL do catálogo no e-SAJ de mentira; o eProc dele em hosts que
        não existem (o de mentira responde neles, quando o teste o põe)."""
        enderecos = {**servidor.enderecos_locais(),
                     "eproc:TJAL": {"1g": ae.BASE, "2g": ae.BASE_2G},
                     # um tribunal só de e-SAJ e sem o 2º grau no Helestron
                     "esaj:TJAM": {"base": servidor.base}}
        self.arquivo_local.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo_local.write_text(json.dumps(enderecos), encoding="utf-8")
        t = tribunais.por_sigla("TJAL")
        assert t.urls_para() == [servidor.base] and t.no_grau("2g").urls_para() == \
            [servidor.app_2g], "o catálogo não apontou para o e-SAJ de mentira"


# ====================================================== motor e preparo
class _ComMotor(_PortaisDeMentira, apoio.PastaTemporaria):
    """O motor de verdade (motor.executar sem fábricas: as padrão) contra o
    e-SAJ de mentira, com o acervo, os sigilosos e os perfis no temporário."""

    @classmethod
    def setUpClass(cls):
        if _chromium() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")
        cls.servidor = falso.servidor_esaj()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()

    def setUp(self):
        super().setUp()
        local = self.tmp / "local"
        self.cfg = config.Config(self.tmp / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.tmp / "Acervo"))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.tmp / "Sigilosos"))
        for p in (mock.patch.object(config, "carregar", lambda *a, **k: self.cfg),
                  mock.patch.object(caminhos, "PERFIS", local / "perfis"),
                  mock.patch.object(caminhos, "TEMP", local / "temp"),
                  mock.patch.object(caminhos, "LOGS", local / "Logs"),
                  mock.patch.object(caminhos, "ARQUIVO_SENHAS", local / "credenciais.json")):
            p.start()
            self.addCleanup(p.stop)
        self.ligar_portais(local)
        self.acervo = self.tmp / "Acervo"
        self.sigilosos = self.tmp / "Sigilosos"
        self.cofre = apoio.CofreFalso({"esaj:TJAL": (USUARIO, SENHA),
                                       "eproc:TJAL": ("usuario-1g", "senha-1g"),
                                       "eproc2g:TJAL": ("usuario-2g", "senha-2g")})
        self.ctx = Contexto2G()

    def lote(self, nome: str) -> Path:
        return self.acervo / "Processos" / nome

    def baixar(self, numeros, destino: Path, grau: str = "1g", senhas=None, tentativas=1,
               **mudar):
        opcoes = apoio.opcoes_de_teste(self.tmp, grau=grau, tentativas=tentativas, espera_s=20,
                                       espera_tela_codigo_s=15, espera_login_min=1,
                                       pasta_provisoria=self.tmp / "local" / "baixando",
                                       **mudar)
        return motor.executar(list(numeros), destino, opcoes, self.ctx, senhas=senhas,
                              cofre=self.cofre, cfg=self.cfg)

    @staticmethod
    def por_numero(resumo) -> dict:
        return {r.numero: r for r in resumo.itens}

    def perfis(self) -> list[str]:
        return [p.name for p in self.abertos]


class TestMotorNosDoisGraus(_ComMotor):
    def test_a_nos_dois_graus_na_mesma_pasta_e_o_que_a_ia_le(self):
        """A apelação A no 1º e no 2º grau, na mesma pasta de lote: dois
        autos, cada um com a sua árvore, a sua capa, o seu registro e a sua
        linha no relatório; nenhum é JA_BAIXADO do outro. Depois, o preparo:
        o índice com uma linha por grau, os textos, o conector."""
        lote = self.lote("Gabinete")
        r1 = self.baixar([A], lote, "1g").itens[0]
        r2 = self.baixar([A], lote, "2g").itens[0]
        self.assertEqual((r1.situacao, r2.situacao), (modelos.OK, modelos.OK),
                         (r1.detalhe, r2.detalhe))
        self.assertEqual((r1.grau, r2.grau), ("1g", "2g"))
        self.assertEqual((r1.paginas, r2.paginas), (4, 8), "cada grau com a sua árvore")
        self.assertEqual((Path(r1.arquivo).name, Path(r2.arquivo).name),
                         (f"{A.nome_arquivo}.pdf", f"{A_2G}.pdf"))
        # um login só (a sessão do e-SAJ vale para os dois graus), no perfil
        # esaj-TJAL; a consulta do 2º grau passou pela porta de entrada dela
        self.assertEqual(len(self.ctx.pedidos_codigo), 1)
        self.assertEqual(self.perfis(), ["esaj-TJAL", "esaj-TJAL"])
        self.assertTrue((caminhos.PERFIS / "esaj-TJAL" / "sessao.json").is_file())
        self.assertIn("/cposg5/open.do?gateway=true", [c for _, c in self.servidor.pedidos])
        self.assertEqual(self.eproc_neutro, [], "achado no e-SAJ: o eProc nem é consultado")

        # os manifestos: o do 1º grau é o de sempre; o do 2º diz o grau
        m1 = paginacao.ler_do_pdf(lote / f"{A.nome_arquivo}.pdf")
        m2 = paginacao.ler_do_pdf(lote / f"{A_2G}.pdf")
        self.assertNotIn("grau", m1)
        self.assertEqual((paginacao.grau(m1), paginacao.grau(m2)), ("1g", "2g"))
        # capa e registro, pelo nome dos autos
        controle = lote / "_controle"
        c1 = json.loads((controle / f"{A.nome_arquivo}_capa.json").read_text("utf-8"))
        c2 = json.loads((controle / f"{A_2G}_capa.json").read_text("utf-8"))
        self.assertNotIn("grau", c1)
        self.assertEqual((c2["grau"], c2["capa"]["classe"]), ("2g", "Apelação Criminal"))
        self.assertEqual([x["numero"] for x in c2["numeros_1a_instancia"]], [A.formatado])
        self.assertTrue((controle / f"{A_2G}_capa.txt").read_text("utf-8").startswith(
            f"Processo {A.formatado} - TJAL (e-SAJ, 2º grau)\n"))
        meta1 = json.loads((controle / f"{A.nome_arquivo}_meta.json").read_text("utf-8"))
        meta2 = json.loads((controle / f"{A_2G}_meta.json").read_text("utf-8"))
        self.assertNotIn("grau", meta1)
        self.assertEqual(meta2["grau"], "2g")
        self.assertEqual(meta2["consultas"][-1], {"sistema": "esaj", "situacao": "OK",
                                                  "grau": "2g"})
        # o relatório: uma linha por grau, com a coluna grau no fim
        linhas = ler_csv(controle / "relatorio.csv")
        self.assertEqual(list(linhas[0])[-1], "grau")
        self.assertEqual([(l["processo"], l["grau"], l["arquivo"]) for l in linhas],
                         [(A.formatado, "1g", f"{A.nome_arquivo}.pdf"),
                          (A.formatado, "2g", f"{A_2G}.pdf")])
        # de novo: cada grau acha os seus autos (e não os do outro)
        r1 = self.baixar([A], lote, "1g").itens[0]
        r2 = self.baixar([A], lote, "2g").itens[0]
        self.assertEqual((r1.situacao, r2.situacao), (modelos.JA_BAIXADO, modelos.JA_BAIXADO))
        self.assertEqual((Path(r1.arquivo).name, Path(r2.arquivo).name),
                         (f"{A.nome_arquivo}.pdf", f"{A_2G}.pdf"))
        self.assertEqual(len(ler_csv(controle / "relatorio.csv")), 2)
        self.assertEqual(len(self.ctx.pedidos_codigo), 1, "a sessão guardada dispensa o login")

        # ---- o que a IA lê: o preparo, o texto, o índice e o conector
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertEqual(rel.processos, 1, "A e A (2G) são um processo só")
        self.assertEqual(servicos.resumo_acervo(self.cfg)["processos"], 1)
        indice = (self.acervo / "INDICE.md").read_text(encoding="utf-8")
        self.assertIn("| Processo | Tribunal | Sistema | Páginas | Paginação | Ausentes | Grau |",
                      indice)
        self.assertIn(preparo.FRASE_DO_2G, indice)
        nossas = [l for l in indice.splitlines() if l.startswith(f"| {A.formatado}")]
        self.assertEqual([l.split(" | ")[0][2:] for l in nossas], [A.nome_arquivo, A_2G])
        self.assertIn("| e-SAJ | 4 | página N = folha N (fls. 1 a 4) | — | 1º grau | Gabinete |",
                      nossas[0])
        self.assertIn("| e-SAJ | 8 | página N = folha N (fls. 1 a 8) | — | 2º grau | Gabinete |",
                      nossas[1])
        # os textos: um por autos; o do 2º grau diz o grau na 1ª linha e cita
        # a folha da Pasta Digital do 2º grau
        pasta_texto = self.acervo / "_ia" / "texto"
        t1, t2 = pasta_texto / f"{A.nome_arquivo}.txt", pasta_texto / f"{A_2G}.txt"
        self.assertNotIn("grau", primeira_linha(t1))
        self.assertTrue(primeira_linha(t2).endswith(" | grau=2g"), primeira_linha(t2))
        texto2 = t2.read_text(encoding="utf-8")
        self.assertIn("autos do e-SAJ do TJAL, 2º grau (Pasta Digital do processo no Tribunal)",
                      texto2)
        self.assertIn(textos.COMO_CITAR_ESAJ_2G, texto2)
        self.assertIn("=== [fl. 8] ===", texto2)
        self.assertEqual((textos.cabecalho(t1.read_text("utf-8"))["grau"],
                          textos.cabecalho(texto2)["grau"]), ("1g", "2g"))
        # o conector (MCP): lista os dois, pede o grau, rotula a busca
        ac = mcp_servidor.Acervo(self.acervo, sigilosos=self.sigilosos)
        self.assertEqual(set(ac.pdfs()), {A.nome_arquivo, A_2G})
        lista = ac.listar_acervo()
        self.assertIn(f"\n- {A_2G} — 2º grau — 8 pág. — Processos/Gabinete/{A_2G}.pdf", lista)
        self.assertIn(f"\n- {A.nome_arquivo} — 4 pág. — Processos/Gabinete/", lista)
        with self.assertRaises(ValueError) as erro:
            ac.ler_processo(A.formatado)
        self.assertIn('informe grau="1g" ou grau="2g"', str(erro.exception))
        self.assertIn(f'(ou peça "{A.nome_arquivo} (1º grau)" ou "{A_2G}")', str(erro.exception))
        dois = ac.ler_processo(A.formatado, grau="2g")
        self.assertTrue(dois.startswith(f"Processo {A.formatado} — e-SAJ, 2º grau: 8 páginas no "
                                        "PDF. Página N = folha N (da Pasta Digital do 2º grau)"),
                        dois[:300])
        self.assertIn("servidor 2g 1", dois)
        self.assertNotIn("página(s)", dois)
        um = ac.ler_processo(A_2G.replace(" (2G)", " (1º grau)"))
        self.assertTrue(um.startswith(f"Processo {A.formatado} (1º grau — autos de origem do "
                                      f"{A_2G}) — e-SAJ: 4 páginas no PDF."), um[:300])
        achados = ac.buscar("servidor", A.formatado)
        self.assertIn(f"{A.nome_arquivo} (1º grau), fl. 1: …", achados)
        self.assertIn(f"{A_2G}, fl. 1: …", achados)
        so_2g = ac.buscar("servidor", A.formatado, "2g")
        self.assertNotIn("(1º grau)", so_2g)
        # pelo protocolo do conector (JSON-RPC), com o parâmetro grau
        resposta = mcp_servidor.Servidor(ac).tratar(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "ler_processo", "arguments": {"numero": A.formatado,
                                                              "grau": "2g"}}})["result"]
        self.assertFalse(resposta["isError"])
        self.assertIn("e-SAJ, 2º grau", resposta["content"][0]["text"])
        # o pacote do ChatGPT: o número leva os autos (e os textos) dos dois graus
        pacote = chatgpt.gerar_pacote(self.acervo, self.tmp / "Pacotes",
                                      numeros=[A.formatado])
        self.assertEqual(pacote.faltaram, [])
        with zipfile.ZipFile(pacote.arquivo_zip) as z:
            nomes = set(z.namelist())
        self.assertTrue({f"autos/{A.nome_arquivo}.pdf", f"autos/{A_2G}.pdf",
                         f"texto/{A.nome_arquivo}.txt", f"texto/{A_2G}.txt"} <= nomes, nomes)

    def test_hc_e_embargos_num_lote_do_1o_grau(self):
        """Num lote do 1º grau, o HC (órgão 0000) e os embargos (/50000) vão
        sozinhos ao 2º grau; o principal dos embargos fica no 1º. Os embargos
        são escolhidos no modal pelo número exato (nunca a apelação). O que
        nenhum sistema acha volta com a frase do grau dele, e o eProc de cada
        grau recebe só as credenciais do seu acesso."""
        lote = self.lote("Lote do 1º grau")
        resumo = self.baixar([P, H, E, A2, E2], lote, "1g")
        r = self.por_numero(resumo)
        self.assertEqual({n: x.grau for n, x in r.items()},
                         {P.formatado: "1g", H.formatado: "2g", E.formatado: "2g",
                          A2.formatado: "1g", E2.formatado: "2g"})
        for n in (P, H, E):
            self.assertEqual(r[n.formatado].situacao, modelos.OK, r[n.formatado].detalhe)
        self.assertEqual((r[P.formatado].paginas, r[H.formatado].paginas,
                          r[E.formatado].paginas), (3, 5, 3),
                         "os embargos (3 folhas), e não a apelação (6)")
        self.assertEqual(sorted(p.name for p in lote.glob("*.pdf")),
                         sorted([f"{P.nome_arquivo}.pdf", f"{H.nome_arquivo} (2G).pdf",
                                 f"{E_2G}.pdf"]))
        cd = {l["cd"] for l in self.servidor.localizadores.values() if l["grau"] == "2g"}
        self.assertIn(falso.COD_E_2G, cd)
        self.assertNotIn(falso.COD_P_2G, cd, "o principal no 2º grau não foi pedido")
        capa_e = json.loads((lote / "_controle" / f"{E_2G}_capa.json").read_text("utf-8"))
        self.assertEqual((capa_e["processo"], capa_e["codigo_processo"]),
                         (E.formatado, falso.COD_E_2G))
        # dois grupos do TJAL (um por grau), cada um seguido do eProc do mesmo
        # grau para o que o e-SAJ não achou: o perfil do eProc do 2º grau é o dele
        self.assertEqual(self.perfis(), ["esaj-TJAL", "eproc-TJAL", "esaj-TJAL", "eproc2g-TJAL"])
        inicios = [d for t, d in self.ctx.eventos if t == "grupo_inicio" and not d["alternativo"]]
        self.assertEqual([d.get("grau") for d in inicios], [None, "2g"])
        # o que ninguém achou: a frase do 1º grau como sempre; a do 2º com a dica
        self.assertEqual(r[A2.formatado].situacao, modelos.NAO_ENCONTRADO)
        self.assertEqual(r[A2.formatado].detalhe,
                         "não encontrado no e-SAJ nem no eProc do TJAL; confira o número")
        self.assertEqual(r[E2.formatado].situacao, modelos.NAO_ENCONTRADO)
        self.assertEqual(r[E2.formatado].detalhe,
                         "não encontrado no e-SAJ nem no eProc do TJAL (2º grau); confira o "
                         "número; " + modelos.dica_de_grau(E2, "2g"))
        self.assertEqual(self.eproc_neutro,
                         [("eproc:TJAL", "1g", ("usuario-1g", "senha-1g")),
                          ("eproc2g:TJAL", "2g", ("usuario-2g", "senha-2g"))],
                         "a senha do eProc do 1º grau nunca vai ao 2º")
        # o relatório com o grau de cada linha
        linhas = {l["processo"]: l for l in ler_csv(lote / "_controle" / "relatorio.csv")}
        self.assertEqual({k: v["grau"] for k, v in linhas.items()},
                         {P.formatado: "1g", H.formatado: "2g", E.formatado: "2g",
                          A2.formatado: "1g", E2.formatado: "2g"})
        self.assertEqual(linhas[E.formatado]["arquivo"], f"{E_2G}.pdf")
        # o que a IA lê: os embargos são outros autos (e outro processo) que
        # os do principal, e o número com /50000 os acha
        preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        indice = (self.acervo / "INDICE.md").read_text(encoding="utf-8")
        self.assertIn("3 processos", indice, "P, os embargos dele e o HC")
        self.assertIn(f"| {E_2G} | TJAL · e-SAJ ou eProc | e-SAJ | 3 | página N = folha N "
                      "(fls. 1 a 3) | — | 2º grau |", indice)
        self.assertIn(f"| {H.nome_arquivo} (2G) | TJAL · e-SAJ ou eProc | e-SAJ | 5 |", indice)
        ac = mcp_servidor.Acervo(self.acervo, sigilosos=self.sigilosos)
        self.assertEqual(set(ac.pdfs()), {P.nome_arquivo, f"{H.nome_arquivo} (2G)", E_2G})
        embargos = ac.ler_processo(E.formatado)
        self.assertTrue(embargos.startswith(f"Processo {E.formatado} — e-SAJ, 2º grau: 3 páginas "
                                            "no PDF."), embargos[:200])
        principal = ac.ler_processo(P.formatado)
        self.assertTrue(principal.startswith(f"Processo {P.formatado} — e-SAJ:"), principal[:200])
        self.assertNotIn("2º grau", principal.split("\n", 1)[0])
        self.assertIn(f"{H.nome_arquivo} (2G), fl. 1: …", ac.buscar("servidor 2g", H.formatado))

    def test_sigiloso_so_no_2o_grau_vale_para_os_dois_e_para_o_hc(self):
        """S é público no 1º grau e sigiloso no 2º. O sigilo é do processo:
        apurado no 2º grau, os autos do 1º grau saem do acervo (com a capa),
        o texto dele sai de _ia/texto e a linha do relatório é mascarada. O
        HC cuja ação de origem é S herda o sigilo pela capa do 2º grau
        ("Números de 1ª Instância")."""
        um = self.lote("Lote 1G")
        r = self.baixar([S], um, "1g").itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.OK, False), r.detalhe)
        preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        texto_1g = self.acervo / "_ia" / "texto" / f"{S.nome_arquivo}.txt"
        self.assertTrue(texto_1g.is_file())
        self.assertIn(f"| {S.nome_arquivo} |", (self.acervo / "INDICE.md").read_text("utf-8"))

        dois = self.lote("Lote 2G")
        # sem a senha do 2º grau: os autos do 2º grau não vêm, mas o sigilo
        # apurado já vale para os do 1º grau, que saem do acervo
        r = self.baixar([S], dois, "2g").itens[0]
        self.assertEqual((r.situacao, r.grau, r.sigiloso),
                         (modelos.SIGILOSO_SEM_SENHA, "2g", True), r.detalhe)
        sig = self.sigilosos
        self.assertFalse((um / f"{S.nome_arquivo}.pdf").exists())
        self.assertTrue((sig / "Lote 1G" / f"{S.nome_arquivo}.pdf").is_file())
        self.assertFalse(texto_1g.exists(), "o texto do 1º grau sai de _ia/texto")
        # com a senha: os autos do 2º grau, direto para a pasta dos sigilosos
        r = self.baixar([S], dois, "2g", senhas={S.formatado: SENHA_S_2G}).itens[0]
        self.assertEqual((r.situacao, r.grau, r.sigiloso), (modelos.OK, "2g", True), r.detalhe)
        self.assertTrue((sig / "Lote 2G" / f"{S.nome_arquivo} (2G).pdf").is_file())
        self.assertFalse((dois / f"{S.nome_arquivo} (2G).pdf").exists())
        # os autos do 1º grau, de outro lote do acervo, saem também, com a capa
        self.assertFalse((um / f"{S.nome_arquivo}.pdf").exists())
        self.assertTrue((sig / "Lote 1G" / f"{S.nome_arquivo}.pdf").is_file())
        self.assertTrue((sig / "Lote 1G" / "_controle" / f"{S.nome_arquivo}_capa.json").is_file())
        self.assertFalse((um / "_controle" / f"{S.nome_arquivo}_capa.json").exists())
        self.assertFalse(texto_1g.exists(), "o texto do 1º grau sai de _ia/texto")
        self.assertFalse((self.acervo / "_ia" / "texto" / f"{S.nome_arquivo} (2G).txt").exists())
        # as linhas dos dois graus mascaradas no acervo; completas nos sigilosos
        for pasta in (um, dois):
            linhas = ler_csv(pasta / "_controle" / "relatorio.csv")
            self.assertEqual([l["processo"] for l in linhas], [motor.MASCARA_SIGILOSO], pasta.name)
        completo = ler_csv(sig / "Lote 2G" / "_controle" / "relatorio.csv")
        self.assertEqual([(l["processo"], l["grau"]) for l in completo], [(S.formatado, "2g")])
        self.assertTrue(sigilo.motivo_do_download(S))
        preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertNotIn(S.nome_arquivo, (self.acervo / "INDICE.md").read_text("utf-8"))
        self.assertEqual(mcp_servidor.Acervo(self.acervo, sigilosos=sig).pdfs(), {})

        # o HC cuja ação de origem é S: sigiloso pela capa do 2º grau
        info = self.servidor.processos_2g[falso.COD_H_2G]
        antes = info["numeros_1a"]
        self.addCleanup(info.__setitem__, "numeros_1a", antes)
        info["numeros_1a"] = [(S.formatado, "Foro de Maceió", "1ª Vara Criminal da Capital",
                               "Juiz Fulano de Tal", "-", True)]
        hc = self.lote("HC")
        r = self.baixar([H], hc, "1g").itens[0]
        self.assertEqual((r.situacao, r.grau, r.sigiloso), (modelos.OK, "2g", True), r.detalhe)
        self.assertIn(f"tratado como sigiloso: o processo de origem {S.formatado} é sigiloso",
                      r.detalhe)
        self.assertTrue((sig / "HC" / f"{H.nome_arquivo} (2G).pdf").is_file())
        self.assertFalse(list(hc.glob("*.pdf")))
        self.assertTrue(sigilo.motivo_do_download(H), "o HC entra na regra única")
        # e o próximo download de S, no 1º grau, já nasce sigiloso
        r = self.baixar([S], self.lote("Novo"), "1g").itens[0]
        self.assertTrue(r.sigiloso)
        self.assertTrue((sig / "Novo" / f"{S.nome_arquivo}.pdf").is_file())

    def test_hc_de_origem_publica_fica_publico(self):
        hc = self.lote("HC")
        r = self.baixar([H], hc, "2g").itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.OK, False), r.detalhe)
        self.assertTrue((hc / f"{H.nome_arquivo} (2G).pdf").is_file())
        self.assertFalse(sigilo.motivo_do_download(H))

    def test_pasta_do_2o_grau_duplicada_nao_e_suportada(self):
        with falso.servidor_esaj(("A",), pasta_2g_duplicada=True) as outro:
            self.apontar_para(outro)
            lote = self.lote("Duplicada")
            r = self.baixar([A], lote, "2g").itens[0]
            self.assertFalse([l for l in outro.localizadores.values() if l["grau"] == "2g"])
        self.assertEqual((r.situacao, r.causa, r.refazer), (modelos.NAO_SUPORTADO, "", False))
        self.assertIn("numera folhas em duplicidade", r.detalhe)
        self.assertFalse(list(lote.glob("*.pdf")))
        self.assertEqual(self.eproc_neutro, [], "não suportado não vai ao eProc")
        linha = ler_csv(lote / "_controle" / "relatorio.csv")[0]
        self.assertEqual((linha["situacao"], linha["grau"], linha["causa"]),
                         (modelos.NAO_SUPORTADO, "2g", ""))

    def test_mais_de_um_processo_do_mesmo_numero_nao_e_suportado(self):
        """Achado da revisão: o modal com dois principais do mesmo número saía
        como ERRO passageiro (causa "falha", "Tentar de novo", busca repetida
        no mesmo lote). É definitivo, como a pasta em duplicidade."""
        with falso.servidor_esaj(("A",)) as outro:
            a = outro.processos_2g[falso.COD_A_2G]
            outro.processos_2g["P0000BBBB0000"] = dict(a, dependentes=[], arvore=list(a["arvore"]))
            outro.respostas_2g[A.principal] = ("modal", [falso.COD_A_2G, "P0000BBBB0000"])
            self.apontar_para(outro)
            lote = self.lote("Ambiguo")
            resumo = self.baixar([A], lote, "2g", tentativas=2)
            self.assertEqual(len(outro.pedidos_de("/cposg5/search.do")), 1,
                             "repetir a busca daria o mesmo modal")
            self.assertFalse([l for l in outro.localizadores.values() if l["grau"] == "2g"])
        r = resumo.itens[0]
        self.assertEqual((r.situacao, r.causa, r.refazer), (modelos.NAO_SUPORTADO, "", False))
        self.assertEqual(r.detalhe, "o 2º grau do e-SAJ tem mais de um processo com este número "
                                    f"({A.formatado}); não baixei, para não gravar autos trocados")
        self.assertEqual(resumo.a_refazer(), [], "não entra em Tentar de novo")
        self.assertFalse(list(lote.glob("*.pdf")))
        self.assertEqual(self.eproc_neutro, [], "não suportado não vai ao eProc")
        linha = ler_csv(lote / "_controle" / "relatorio.csv")[0]
        self.assertEqual((linha["situacao"], linha["grau"], linha["causa"]),
                         (modelos.NAO_SUPORTADO, "2g", ""))

    def test_recurso_interno_de_processo_em_segredo_nao_e_suportado(self):
        """Achado da verificação: a busca pelo /50000 de S cai na página em
        segredo do principal (sem número) e saía como "devolveu processos e
        nenhum traz exatamente este número", falso. É recusa definitiva, com
        a frase certa, e a linha nasce sigilosa: o número fica fora do
        relatório do acervo."""
        s50 = cnj.ler(S.principal + "/50000")
        with falso.servidor_esaj(("S",)) as outro:
            self.apontar_para(outro)
            lote = self.lote("Segredo 50000")
            resumo = self.baixar([s50], lote, "2g", senhas={s50.formatado: SENHA_S_2G},
                                 tentativas=2)
            self.assertEqual(len(outro.pedidos_de("/cposg5/search.do")), 1,
                             "repetir a busca abriria a mesma página")
            self.assertFalse([l for l in outro.localizadores.values() if l["grau"] == "2g"])
        r = resumo.itens[0]
        self.assertEqual((r.situacao, r.causa, r.refazer, r.grau, r.sigiloso),
                         (modelos.NAO_SUPORTADO, "", False, "2g", True), r.detalhe)
        self.assertEqual(r.detalhe, "a consulta de 2º grau abriu a página do processo principal "
                                    f"em segredo de justiça, sem o número; o recurso interno "
                                    f"{s50.formatado} de processo em segredo não é escolhido pelo "
                                    "Helestron: baixe-o pelo portal do tribunal")
        self.assertEqual(resumo.a_refazer(), [], "não entra em Tentar de novo")
        self.assertFalse(list(lote.glob("*.pdf")))
        self.assertEqual(self.eproc_neutro, [], "não suportado não vai ao eProc")
        acervo = lote / "_controle" / "relatorio.csv"
        self.assertNotIn(S.principal, acervo.read_text(encoding="utf-8-sig"))
        linha = ler_csv(acervo)[0]
        self.assertEqual((linha["processo"], linha["situacao"], linha["sigiloso"], linha["grau"]),
                         (motor.MASCARA_SIGILOSO, modelos.NAO_SUPORTADO, "sim", "2g"))
        completo = ler_csv(self.sigilosos / "Segredo 50000" / "_controle" / "relatorio.csv")
        self.assertEqual([(l["processo"], l["situacao"]) for l in completo],
                         [(s50.formatado, modelos.NAO_SUPORTADO)])

    def test_recurso_interno_em_segredo_tira_do_acervo_o_principal_ja_baixado(self):
        """Achado W1: S, baixado público no 1º grau, está no acervo; depois
        só S/50000, cuja consulta abre a página de S em segredo de justiça. O
        portal apura S também, e o motor o trata como sigiloso: S.pdf vai
        para a pasta de sigilosos, a linha dele é mascarada, e o registro do
        download (a regra única: o índice, o MCP, a nuvem) guarda S."""
        s50 = cnj.ler(S.principal + "/50000")
        with falso.servidor_esaj(("S",)) as outro:
            self.apontar_para(outro)
            lote = self.lote("Segredo principal")
            r = self.baixar([S], lote, "1g").itens[0]
            self.assertEqual((r.situacao, r.sigiloso), (modelos.OK, False), r.detalhe)
            r = self.baixar([s50], lote, "2g", senhas={s50.formatado: SENHA_S_2G}).itens[0]
        self.assertEqual((r.situacao, r.sigiloso), (modelos.NAO_SUPORTADO, True), r.detalhe)
        self.assertFalse(list(lote.glob("*.pdf")))
        self.assertTrue((self.sigilosos / lote.name / f"{S.nome_arquivo}.pdf").is_file())
        self.assertIn(f"o processo principal {S.formatado} passa a ser tratado como sigiloso: "
                      "1 cópia dos autos dele levada para a pasta de sigilosos", r.detalhe)
        self.assertNotIn(S.principal, (lote / "_controle" / "relatorio.csv")
                         .read_text(encoding="utf-8-sig"))
        self.assertEqual([(l["processo"], l["sigiloso"], l["grau"])
                          for l in ler_csv(lote / "_controle" / "relatorio.csv")],
                         [(motor.MASCARA_SIGILOSO, "sim", "1g"),
                          (motor.MASCARA_SIGILOSO, "sim", "2g")])
        self.assertTrue(sigilo.motivo_do_download(S) and sigilo.motivo_do_download(s50))
        self.assertTrue(sigilo.contem(sigilo.chaves_sigilosas(self.sigilosos, raiz=self.acervo),
                                      S.nome_arquivo))

    def test_tribunal_sem_o_2o_grau_nao_manda_escolher_o_2o_grau(self):
        """Achado da integração: o "não encontrado" do 1º grau mandava todo
        tribunal escolher “2º grau” nas Opções do lote - e o lote do 2º grau
        de um tribunal sem ele (o e-SAJ do TJAM) é recusado pelo motor (não
        suportado). Nele, a dica manda ao portal do tribunal."""
        self.cofre.guardar("esaj:TJAM", USUARIO, SENHA)
        r = self.baixar([AM], self.lote("TJAM"), "1g").itens[0]
        self.assertEqual((r.situacao, r.tribunal, r.grau), (modelos.NAO_ENCONTRADO, "TJAM", "1g"))
        self.assertEqual(r.detalhe, "não encontrado no 1º grau do e-SAJ do TJAM. Confira o "
                                    f"número; {modelos.DICA_SEM_2G}.")
        self.assertNotIn(modelos.DICA_GRAU_2G, r.detalhe)
        # e é verdade: o 2º grau dele não é baixado
        r = self.baixar([AM], self.lote("TJAM 2G"), "2g").itens[0]
        self.assertEqual(r.situacao, modelos.NAO_SUPORTADO)
        self.assertEqual(r.detalhe, "o 2º grau do e-SAJ do TJAM ainda não é baixado pelo "
                                    "Helestron; baixe-o pelo portal do tribunal")
        # no TJAL, que tem o 2º grau, a frase do e-SAJ sugere a opção
        portal = esaj.PortalESAJ(None, self.servidor.tribunal(), apoio.opcoes_de_teste(self.tmp),
                                 self.ctx, None)
        self.assertTrue(tribunais.baixa_o_2o_grau(portal.tribunal))
        self.assertIn(modelos.DICA_GRAU_2G, modelos.dica_de_grau(A2, "1g"))


class TestEProcDoSegundoGrau(_ComMotor):
    def test_acesso_perfil_e_sessao_proprios(self):
        """O número que o e-SAJ do 2º grau não tem vai ao eProc do 2º grau
        (eproc2g:TJAL): o cofre, o perfil do navegador e a sessão guardada
        são os dele, e a senha do eProc do 1º grau nunca é enviada."""
        evento = ae.EventoFalso(1, "10/01/2025 14:00:00", "PETIÇÃO INICIAL", [
            ae.DocFalso("INIC1", "pdf", apoio.pdf_bytes(2, "INIC1"), "application/pdf")])
        self.eproc_falso = ae.EProcFalso(grau="2g", processos={
            A2.digitos: ae.ProcessoFalso(A2, [evento])})
        self.cofre = apoio.CofreFalso({"esaj:TJAL": (USUARIO, SENHA),
                                       "eproc:TJAL": ("RS999999", "senha do 1º grau"),
                                       "eproc2g:TJAL": (ae.USUARIO, ae.SENHA)})
        lote = self.lote("eProc 2G")
        r = self.baixar([A2], lote, "2g").itens[0]
        self.assertEqual((r.situacao, r.sistema, r.grau), (modelos.OK, "eproc", "2g"), r.detalhe)
        self.assertEqual(self.cofre.pedidos, ["esaj:TJAL", "eproc2g:TJAL"])
        self.assertEqual(self.perfis(), ["esaj-TJAL", "eproc2g-TJAL"])
        self.assertTrue((caminhos.PERFIS / "eproc2g-TJAL" / "sessao.json").is_file())
        self.assertFalse((caminhos.PERFIS / "eproc-TJAL").exists())
        self.assertTrue(all(ae.HOST_2G in url or ae.HOST_SSO in url
                            for _, url in self.eproc_falso.pedidos))
        pdf = lote / f"{A2.nome_arquivo} (2G).pdf"
        m = paginacao.ler_do_pdf(pdf)
        self.assertEqual((m["grau"], m["portal"]), ("2g", "eProc do TJAL (2º grau)"))
        capa = json.loads((lote / "_controle" / f"{A2.nome_arquivo} (2G)_capa.json")
                          .read_text("utf-8"))
        self.assertEqual(capa["grau"], "2g")
        linha = ler_csv(lote / "_controle" / "relatorio.csv")[0]
        self.assertEqual((linha["sistema"], linha["grau"]), ("eproc", "2g"))
        # o texto do eProc do 2º grau: o grau na 1ª linha, a abertura e os eventos
        preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        texto = self.acervo / "_ia" / "texto" / f"{A2.nome_arquivo} (2G).txt"
        self.assertTrue(primeira_linha(texto).endswith(" | grau=2g"), primeira_linha(texto))
        corpo = texto.read_text(encoding="utf-8")
        self.assertIn("autos do eProc do TJAL, 2º grau", corpo)
        self.assertIn("evento do processo de origem (1º grau) não está", " ".join(corpo.split()))


# ==================================== o sigilo sabido fora do download
def pdf_com_manifesto(caminho: Path, manifesto: dict, paginas: int, rotulo: str) -> Path:
    import pymupdf
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(stream=apoio.pdf_bytes(paginas, rotulo), filetype="pdf")
    paginacao.gravar_no_doc(doc, manifesto)
    doc.save(str(caminho))
    doc.close()
    return caminho


class TestSigiloSabidoPelaPasta(apoio.PastaTemporaria):
    """Sem navegador: o preparo (F4) tira do acervo, pelo motor (F3), os autos
    dos DOIS graus do processo que a regra única (F1) já sabe sigiloso pela
    pasta dos sigilosos - e os do recurso interno dele (/50000) -, com os
    textos; o índice, o conector e o pacote deixam de vê-los."""

    def setUp(self):
        super().setUp()
        self.cfg = config.Config(self.tmp / "config.ini")
        self.cfg.definir("geral", "pasta_acervo", str(self.tmp / "Acervo"))
        self.cfg.definir("geral", "pasta_sigilosos", str(self.tmp / "Sigilosos"))
        p = mock.patch.object(config, "carregar", lambda *a, **k: self.cfg)
        p.start()
        self.addCleanup(p.stop)
        self.acervo = self.tmp / "Acervo"
        self.lote = self.acervo / "Processos" / "Gabinete"
        for n, grau, paginas in ((A, "1g", 4), (A, "2g", 8), (P, "1g", 3), (E, "2g", 3),
                                 (H, "2g", 5)):
            nome = cnj.nome_dos_autos(n, grau)
            pdf_com_manifesto(self.lote / f"{nome}.pdf",
                              paginacao.manifesto_esaj(n.formatado, paginas, tribunal="TJAL",
                                                       origem="servidor", grau=grau),
                              paginas, f"autos {nome}")
            (self.lote / "_controle").mkdir(exist_ok=True)
            (self.lote / "_controle" / f"{nome}_capa.txt").write_text("capa", encoding="utf-8")

    def test_os_dois_graus_e_o_recurso_interno_saem_do_acervo(self):
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertEqual(rel.processos, 4, "A (dois graus), P, os embargos de P e o HC")
        textos_ia = self.acervo / "_ia" / "texto"
        self.assertEqual(len(list(textos_ia.glob("*.txt"))), 5)
        # A e P passam a ser sabidos sigilosos pela pasta dos sigilosos
        for n in (A, P):
            pdf_com_manifesto(self.tmp / "Sigilosos" / "Outro lote" / f"{n.nome_arquivo}.pdf",
                              paginacao.manifesto_esaj(n.formatado, 1, tribunal="TJAL"), 1, "x")
        with self.assertLogs(level="WARNING") as registro:
            rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertTrue(any("levada para a pasta dos sigilosos" in r for r in registro.output))
        self.assertEqual(rel.sigilosos_no_acervo, [])
        self.assertEqual(sorted(p.name for p in self.lote.glob("*.pdf")),
                         [f"{H.nome_arquivo} (2G).pdf"])
        sig = self.tmp / "Sigilosos" / "Gabinete"
        for nome in (A.nome_arquivo, A_2G, P.nome_arquivo, E_2G):
            self.assertTrue((sig / f"{nome}.pdf").is_file(), nome)
            self.assertTrue((sig / "_controle" / f"{nome}_capa.txt").is_file(), nome)
        self.assertEqual([p.name for p in textos_ia.glob("*.txt")], [f"{H.nome_arquivo} (2G).txt"])
        indice = (self.acervo / "INDICE.md").read_text(encoding="utf-8")
        for nome in (A.nome_arquivo, P.nome_arquivo):
            self.assertNotIn(nome, indice)
        self.assertEqual(set(mcp_servidor.Acervo(self.acervo).pdfs()),
                         {f"{H.nome_arquivo} (2G)"})
        with self.assertLogs(level="WARNING"):
            pacote = chatgpt.gerar_pacote(self.acervo, self.tmp / "Pacotes",
                                          numeros=[A.formatado, H.formatado])
        self.assertEqual(pacote.faltaram, [A.formatado])

    def test_a_origem_que_vira_sigilosa_depois_leva_o_hc(self):
        """Achado C3 da revisão: o HC foi baixado quando a ação de origem A
        ainda era pública, e A vira sigilosa depois (os autos dela na pasta
        dos sigilosos). O HC, que traz cópia de A, sai do acervo pela capa
        guardada em _controle - do índice, de _ia/texto, do conector, do
        pacote e da nuvem -, e o originário de origem pública (PL, do
        plantão do 2º grau) continua servido."""
        PL = NUMEROS["PL"]
        pl_2g, h_2g = cnj.nome_dos_autos(PL, "2g"), cnj.nome_dos_autos(H, "2g")
        pdf_com_manifesto(self.lote / f"{pl_2g}.pdf",
                          paginacao.manifesto_esaj(PL.formatado, 2, tribunal="TJAL",
                                                   origem="servidor", grau="2g"), 2, "plantão")
        controle = self.lote / "_controle"
        for n, origem in ((H, A), (PL, S), (A, A)):          # a apelação lista a si mesma
            (controle / f"{cnj.nome_dos_autos(n, '2g')}_capa.json").write_text(json.dumps(
                {"processo": n.formatado, "grau": "2g",
                 "numeros_1a_instancia": [{"numero": origem.formatado, "foro": "Maceió"}]}),
                encoding="utf-8")
        rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertEqual(rel.processos, 5, "A (dois graus), P, os embargos de P, o HC e PL")
        textos_ia = self.acervo / "_ia" / "texto"
        self.assertTrue((textos_ia / f"{h_2g}.txt").is_file())
        destino = self.tmp / "Nuvem"
        nuvem.espelhar(self.acervo, destino)
        self.assertEqual(sorted(p.name for p in destino.rglob(f"{h_2g}*")),
                         [f"{h_2g}.pdf", f"{h_2g}.txt"])
        # A passa a ser sabida sigilosa pela pasta dos sigilosos
        pdf_com_manifesto(self.tmp / "Sigilosos" / "Outro lote" / f"{A.nome_arquivo}.pdf",
                          paginacao.manifesto_esaj(A.formatado, 1, tribunal="TJAL"), 1, "x")
        with self.assertLogs(level="WARNING") as registro:
            rel = preparo.atualizar_contexto(self.cfg, extrair_texto=True)
        self.assertTrue(any(f"Processo sigiloso {H.nome_arquivo}: cópia no acervo levada" in r
                            for r in registro.output), registro.output)
        self.assertEqual(rel.sigilosos_no_acervo, [])
        self.assertEqual(rel.processos, 3, "P, os embargos de P e PL")
        self.assertEqual(sorted(p.name for p in self.lote.glob("*.pdf")),
                         sorted([f"{P.nome_arquivo}.pdf", f"{E_2G}.pdf", f"{pl_2g}.pdf"]))
        sig = self.tmp / "Sigilosos" / "Gabinete"
        self.assertTrue((sig / f"{h_2g}.pdf").is_file())
        self.assertTrue((sig / "_controle" / f"{h_2g}_capa.json").is_file())
        self.assertTrue(sigilo.motivo_do_download(H), "uma vez apurado, fica")
        indice = (self.acervo / "INDICE.md").read_text(encoding="utf-8")
        self.assertNotIn(H.nome_arquivo, indice)
        self.assertIn(f"| {pl_2g} |", indice)
        self.assertEqual(sorted(p.name for p in textos_ia.glob("*.txt")),
                         sorted([f"{P.nome_arquivo}.txt", f"{E_2G}.txt", f"{pl_2g}.txt"]))
        ac = mcp_servidor.Acervo(self.acervo)
        self.assertEqual(set(ac.pdfs()), {P.nome_arquivo, E_2G, pl_2g})
        self.assertNotIn(H.nome_arquivo, ac.listar_acervo())
        with self.assertRaises(LookupError):
            ac.ler_processo(H.formatado)
        self.assertTrue(ac.ler_processo(PL.formatado).startswith(
            f"Processo {PL.formatado} — e-SAJ, 2º grau:"))
        with self.assertLogs(level="WARNING"):
            pacote = chatgpt.gerar_pacote(self.acervo, self.tmp / "Pacotes",
                                          numeros=[H.formatado, PL.formatado])
        self.assertEqual(pacote.faltaram, [H.formatado])
        with zipfile.ZipFile(pacote.arquivo_zip) as z:
            self.assertIn(f"autos/{pl_2g}.pdf", z.namelist())
        # a nuvem tira a cópia de antes e não leva o HC de novo
        nuvem.espelhar(self.acervo, destino)
        self.assertEqual([p.name for p in destino.rglob(f"{H.nome_arquivo}*")], [])
        self.assertTrue(any(p.name == f"{pl_2g}.pdf" for p in destino.rglob("*.pdf")))


# ======================================================== linha de comando
class TestLinhaDeComando(_ComMotor):
    def setUp(self):
        super().setUp()
        CofreSenhas(caminhos.ARQUIVO_SENHAS).guardar("esaj:TJAL", USUARIO, SENHA)
        for chave, valor in (("pausa_entre_processos", "0"), ("tentativas", "1"),
                             ("espera_segundos", "20"), ("espera_login_minutos", "1")):
            self.cfg.definir("download", chave, valor)
        p = mock.patch.object(contexto.ContextoTerminal, "pedir_codigo",
                              lambda *a, **k: CODIGO)
        p.start()
        self.addCleanup(p.stop)

    def baixar_pelo_terminal(self, argv: list[str]) -> tuple[int, dict]:
        saida = self.tmp / "baixar.json"
        with mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()), \
                mock.patch("sys.stdin", io.StringIO("")):
            codigo = cli.main(["baixar", *argv, "--json", str(saida)], configurar_log=False)
        return codigo, json.loads(saida.read_text(encoding="utf-8"))

    def test_grau_no_json_no_csv_no_texto_e_no_retomar(self):
        lote = self.lote("Pelo terminal")
        # --grau 2g: os autos do 2º grau, o JSON e o CSV com o grau, o texto
        codigo, dados = self.baixar_pelo_terminal([A.formatado, "--grau", "2g", "--destino",
                                                    str(lote), "--texto"])
        self.assertEqual(codigo, 0, dados)
        self.assertEqual(dados["grau"], "2g")
        p = dados["processos"][0]
        self.assertEqual((p["numero"], p["grau"], p["situacao"], p["nome_arquivo"]),
                         (A.formatado, "2g", "OK", A_2G))
        self.assertEqual(Path(p["pdf"]), lote / f"{A_2G}.pdf")
        self.assertEqual(Path(p["capa_json"]).name, f"{A_2G}_capa.json")
        self.assertEqual(Path(p["meta"]).name, f"{A_2G}_meta.json")
        self.assertEqual(p["paginacao"]["grau"], "2g")
        self.assertEqual(p["consultas"][-1].get("grau"), "2g")
        self.assertEqual(Path(p["texto"]), self.acervo / "_ia" / "texto" / f"{A_2G}.txt")
        self.assertTrue(primeira_linha(p["texto"]).endswith(" | grau=2g"))
        self.assertIn(textos.COMO_CITAR_ESAJ_2G, Path(p["texto"]).read_text(encoding="utf-8"))
        linhas = ler_csv(lote / "_controle" / "relatorio.csv")
        self.assertEqual([(l["processo"], l["grau"]) for l in linhas], [(A.formatado, "2g")])

        # sem --grau, com os Ajustes em 2º grau: a linha de comando vai ao 1º
        self.cfg.definir("download", "grau", "2g")
        codigo, dados = self.baixar_pelo_terminal([A.formatado, "--destino", str(lote),
                                                    "--sem-ia"])
        self.assertEqual(codigo, 0, dados)
        self.assertEqual(dados["grau"], "1g")
        p = dados["processos"][0]
        self.assertEqual((p["grau"], p["situacao"], Path(p["pdf"]).name),
                         ("1g", "OK", f"{A.nome_arquivo}.pdf"), p["detalhe"])
        self.assertEqual([(l["processo"], l["grau"])
                          for l in ler_csv(lote / "_controle" / "relatorio.csv")],
                         [(A.formatado, "2g"), (A.formatado, "1g")])
        # o texto do 2º grau, gravado pelo baixar, sobrevive ao preparo
        preparo.atualizar_contexto(self.cfg, extrair_texto=False)
        self.assertTrue((self.acervo / "_ia" / "texto" / f"{A_2G}.txt").is_file())

        # --retomar: os autos do 2º grau sumiram; só o --grau 2g os retoma
        (lote / f"{A_2G}.pdf").unlink()
        instante = (lote / f"{A.nome_arquivo}.pdf").stat().st_mtime_ns
        codigo, dados = self.baixar_pelo_terminal(["--retomar", "--destino", str(lote),
                                                    "--sem-ia"])
        self.assertEqual(codigo, 0, dados)
        self.assertEqual(dados["processos"], [])
        self.assertEqual([(i["numero"], i["motivo"]) for i in dados["ignorados_por_retomar"]],
                         [(A.formatado, "do 2º grau: para retomá-la, use --grau 2g")])
        codigo, dados = self.baixar_pelo_terminal(["--retomar", "--grau", "2g", "--destino",
                                                    str(lote), "--sem-ia"])
        self.assertEqual(codigo, 0, dados)
        self.assertEqual([(p["numero"], p["grau"], p["situacao"]) for p in dados["processos"]],
                         [(A.formatado, "2g", "OK")])
        self.assertTrue((lote / f"{A_2G}.pdf").is_file())
        self.assertEqual((lote / f"{A.nome_arquivo}.pdf").stat().st_mtime_ns, instante,
                         "os autos do 1º grau não foram tocados")
        self.assertEqual(len(ler_csv(lote / "_controle" / "relatorio.csv")), 2)


# ================================================================== a API
class _ApiComPortais(_PortaisDeMentira, ServidorDeTeste):
    """O servidor de verdade (a API da tela) com o e-SAJ de mentira no
    catálogo; o cofre é o de verdade (no temporário)."""

    precisa_do_chromium = True

    @classmethod
    def setUpClass(cls):
        if cls.precisa_do_chromium and _chromium() is None:
            raise unittest.SkipTest("nenhum navegador (Chromium, Chrome ou Edge) abre aqui")
        cls.servidor = falso.servidor_esaj()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()

    def setUp(self):
        super().setUp()
        self.ligar_portais(self.amb.local)
        for chave, valor in (("pausa_entre_processos", "0"), ("tentativas", "1"),
                             ("espera_segundos", "20"), ("espera_login_minutos", "1")):
            self.cfg.definir("download", chave, valor)
        self.cfg.definir("unidade", "tribunal", "TJAL")

    def guardar_acesso(self, portal: str, usuario: str, senha: str) -> dict:
        return self.cliente.dados("POST", "/api/acessos", {"portal": portal, "usuario": usuario,
                                                           "senha": senha})

    def responder_codigos(self, leitor, id_tarefa: str, espera: float = 90.0) -> dict:
        """Espera a tarefa terminar respondendo o código do e-SAJ, como o
        usuário na tela."""
        limite = time.monotonic() + espera
        respondidas: set[str] = set()
        while time.monotonic() < limite:
            for tipo, dados in list(leitor.recebidos):
                if tipo == "pergunta" and dados.get("tarefa") == id_tarefa \
                        and dados.get("id") not in respondidas:
                    respondidas.add(dados["id"])
                    self.cliente.dados("POST", f"/api/perguntas/{dados['id']}/responder",
                                       {"valor": CODIGO})
            tarefa = self.cliente.dados("GET", f"/api/tarefas/{id_tarefa}")
            if tarefa["estado"] != "rodando":
                return tarefa
            time.sleep(0.1)
        raise AssertionError(f"a tarefa {id_tarefa} não terminou")


class TestApiPeloCaminhoReal(_ApiComPortais):
    def test_testar_o_esaj_do_2o_grau_passa_pela_consulta_do_2o_grau(self):
        self.guardar_acesso("esaj:TJAL", USUARIO, SENHA)
        leitor = self.eventos()
        antes = len(self.servidor.pedidos)
        id_tarefa = self.cliente.dados("POST", "/api/acessos/testar",
                                       {"tribunal": "TJAL", "sistema": "esaj",
                                        "grau": "2g"})["tarefa"]
        tarefa = self.responder_codigos(leitor, id_tarefa)
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(tarefa["titulo"], "Testar o acesso ao TJAL · e-SAJ (2º grau)")
        self.assertEqual(tarefa["resultado"]["grau"], "2g")
        pedidos = [c for _, c in self.servidor.pedidos[antes:]]
        login = max(i for i, c in enumerate(pedidos) if c.startswith("/sajcas/"))
        self.assertIn("/cposg5/open.do?gateway=true", pedidos[login:],
                      "o Testar 2º grau prova a consulta do 2º grau, depois do login")
        self.assertEqual([p.name for p in self.abertos], ["esaj-TJAL"])
        # o Testar do 1º grau (o corpo de sempre) não passa por ela
        antes = len(self.servidor.pedidos)
        id_tarefa = self.cliente.dados("POST", "/api/acessos/testar",
                                       {"tribunal": "TJAL", "sistema": "esaj"})["tarefa"]
        tarefa = self.responder_codigos(leitor, id_tarefa)
        self.assertEqual((tarefa["estado"], tarefa["titulo"]),
                         ("concluida", "Testar o acesso ao TJAL · e-SAJ"), tarefa)
        self.assertNotIn("/cposg5/open.do?gateway=true",
                         [c for _, c in self.servidor.pedidos[antes:]])

    def test_lote_com_grau_e_o_tentar_de_novo_no_grau_do_lote(self):
        """O lote de 2º grau pela API: cada linha com o grau; o "Tentar de
        novo" (que a tela manda com o grau do lote, res.grau) refaz no 2º
        grau mesmo com os Ajustes no 1º."""
        self.guardar_acesso("esaj:TJAL", USUARIO, SENHA)
        leitor = self.eventos()
        corpo = {"processos": [A.formatado, H.formatado], "nome_lote": "Câmara",
                 "opcoes": {"grau": "2g"}}
        tarefa = self.responder_codigos(
            leitor, self.cliente.dados("POST", "/api/download/iniciar", corpo)["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(tarefa["resultado"]["grau"], "2g")
        itens = {i["numero"]: i for i in tarefa["itens"]}
        self.assertEqual({n: (i["situacao"], i["grau"]) for n, i in itens.items()},
                         {A.formatado: ("OK", "2g"), H.formatado: ("OK", "2g")})
        pasta = self.cfg.pasta_processos / "Câmara"
        self.assertEqual(Path(itens[A.formatado]["arquivo"]), pasta / f"{A_2G}.pdf")
        # "Tentar de novo": o pedido da tela, com o grau do lote que terminou
        corpo = {"processos": [A.formatado], "nome_lote": "Câmara",
                 "opcoes": {"rebaixar": False, "grau": tarefa["resultado"]["grau"]}}
        de_novo = self.responder_codigos(
            leitor, self.cliente.dados("POST", "/api/download/iniciar", corpo)["tarefa"])
        self.assertEqual(de_novo["resultado"]["grau"], "2g")
        self.assertEqual([(i["situacao"], i["grau"]) for i in de_novo["itens"]],
                         [("JA_BAIXADO", "2g")])
        self.assertFalse((pasta / f"{A.nome_arquivo}.pdf").exists(),
                         "nenhum auto de origem baixado como se fosse do lote de 2º grau")


class TestApiSemNavegador(_ApiComPortais):
    precisa_do_chromium = False

    def test_testar_o_eproc_do_2o_grau_com_o_perfil_e_a_senha_dele(self):
        self.guardar_acesso("eproc:TJAL", "usuario-1g", "senha-1g")
        self.guardar_acesso("eproc2g:TJAL", "usuario-2g", "senha-2g")
        self.neutralizar_eproc = False          # o PortalEProc de verdade
        entradas = []

        def entrar(portal):
            entradas.append((portal.tribunal.portal, portal.grau, portal.usuario, portal.senha,
                             portal.nome, portal.tribunal.urls_para()))
        with mock.patch.object(eproc.PortalEProc, "entrar", entrar):
            for corpo in ({"tribunal": "TJAL", "sistema": "eproc", "grau": "2g"},
                          {"tribunal": "TJAL", "sistema": "eproc"}):
                tarefa = self.esperar_tarefa(
                    self.cliente.dados("POST", "/api/acessos/testar", corpo)["tarefa"])
                self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(entradas, [
            ("eproc2g:TJAL", "2g", "usuario-2g", "senha-2g", "eProc do TJAL (2º grau)",
             [ae.BASE_2G]),
            ("eproc:TJAL", "1g", "usuario-1g", "senha-1g", "eProc do TJAL", [ae.BASE])])
        self.assertEqual(self.abertos, [caminhos.PERFIS / "eproc2g-TJAL",
                                        caminhos.PERFIS / "eproc-TJAL"])

    def test_apagar_e_trocar_o_acesso_do_eproc_do_2o_grau(self):
        def criar(*nomes):
            for nome in nomes:
                pasta = caminhos.PERFIS / nome
                pasta.mkdir(parents=True, exist_ok=True)
                (pasta / "sessao.json").write_text("{}", encoding="utf-8")

        def existentes():
            return sorted(p.name for p in caminhos.PERFIS.iterdir() if p.is_dir())

        dos_dois = ("eproc-TJAL", "eproc2g-TJAL", "eproc2g-TJAL-certificado", "esaj-TJAL")
        criar(*dos_dois)
        self.guardar_acesso("eproc:TJAL", "usuario-1g", "senha-1g")
        self.guardar_acesso("eproc2g:TJAL", "usuario-2g", "senha-2g")
        self.cliente.dados("DELETE", "/api/acessos/eproc2g:TJAL")
        self.assertEqual(existentes(), ["eproc-TJAL", "esaj-TJAL"])
        cofre = servicos.cofre()
        self.assertEqual(cofre.obter("eproc2g:TJAL"), ("", ""))
        self.assertEqual(cofre.obter("eproc:TJAL"), ("usuario-1g", "senha-1g"))
        # o inverso: apagar o do 1º grau não toca no do 2º
        criar(*dos_dois)
        self.guardar_acesso("eproc2g:TJAL", "usuario-2g", "senha-2g")
        self.cliente.dados("DELETE", "/api/acessos/eproc:TJAL")
        self.assertEqual(existentes(), ["eproc2g-TJAL", "eproc2g-TJAL-certificado", "esaj-TJAL"])
        self.assertEqual(servicos.cofre().obter("eproc2g:TJAL"), ("usuario-2g", "senha-2g"))
        # outra pessoa no eProc do 2º grau: só a sessão do 2º grau sai
        criar(*dos_dois)
        self.guardar_acesso("eproc:TJAL", "usuario-1g", "senha-1g")
        self.cliente.dados("POST", "/api/acessos", {"portal": "eproc2g:TJAL",
                                                    "usuario": "outra-pessoa"})
        self.assertEqual(existentes(), ["eproc-TJAL", "esaj-TJAL"])
        self.assertEqual(servicos.cofre().obter("eproc2g:TJAL"), ("outra-pessoa", "senha-2g"))
        self.assertEqual(servicos.cofre().obter("eproc:TJAL"), ("usuario-1g", "senha-1g"))

    def test_baixar_autos_da_pauta_chega_ao_motor_no_1o_grau(self):
        from testes.test_servidor_pauta import ServicoPautaFalso, modulo_falso

        ServicoPautaFalso.instancias = []
        p = mock.patch.dict(sys.modules, modulo_falso())
        p.start()
        self.addCleanup(p.stop)
        self.cfg.definir("download", "grau", "2g")
        recebidas = []

        def executar(numeros, destino, opcoes, ctx, senhas=None, cofre=None, **_):
            recebidas.append(opcoes)
            return modelos.ResumoLote([], Path(destino), Path(destino) / "_controle" /
                                      "relatorio.csv")
        hoje = date.today().isoformat()
        with mock.patch.object(motor, "executar", executar):
            dados = self.cliente.dados("POST", "/api/pauta/baixar-autos",
                                       {"ids": ["a1"], "de": hoje, "ate": hoje})
            tarefa = self.esperar_tarefa(dados["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual([o.grau for o in recebidas], ["1g"])
        self.assertEqual(tarefa["resultado"]["grau"], "1g")


if __name__ == "__main__":
    unittest.main()
