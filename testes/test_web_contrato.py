"""Interface web (helestron/web): o que dá para conferir sem abrir o navegador.

Arquivos que o index.html carrega, nada de fora (funciona sem internet e
passa pela Content-Security-Policy do servidor), a fonte Inter com a licença
OFL, os tokens de cor da especificação, o contraste AA dos pares de cor que a
interface usa, a paleta em tons de azul, cinza e branco (verde, âmbar e
vermelho só dizem estado), os ícones citados pelo código e o JavaScript dentro
do ES2020 (o WebView2 mais antigo que o Windows 10 traz).
"""

from __future__ import annotations

import colorsys
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "helestron" / "web"
CSS = WEB / "css" / "helestron.css"


class _Referencias(HTMLParser):
    """src/href do index.html, scripts em linha e atributos on*."""

    def __init__(self):
        super().__init__()
        self.referencias: list[str] = []
        self.scripts_em_linha = 0
        self.manipuladores: list[str] = []
        self._em_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for chave in ("src", "href"):
            if a.get(chave):
                self.referencias.append(a[chave])
        self.manipuladores += [k for k in a if k.startswith("on")]
        self._em_script = tag == "script" and not a.get("src")

    def handle_data(self, data):
        if self._em_script and data.strip():
            self.scripts_em_linha += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self._em_script = False


def _index() -> _Referencias:
    leitor = _Referencias()
    leitor.feed((WEB / "index.html").read_text(encoding="utf-8"))
    return leitor


def _tokens() -> dict[str, str]:
    raiz = re.search(r":root\s*\{(.*?)\n\}", CSS.read_text(encoding="utf-8"), re.S).group(1)
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+):\s*([^;]+);", raiz)}


def _rgb(cor: str, tokens: dict[str, str]) -> tuple[float, float, float, float]:
    cor = cor.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", cor)
    if m:
        return _rgb(tokens[m.group(1)], tokens)
    if cor.startswith("#"):
        h = cor[1:]
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    m = re.fullmatch(r"rgba?\(([^)]+)\)", cor)
    partes = [float(x) for x in m.group(1).split(",")]
    return partes[0], partes[1], partes[2], partes[3] if len(partes) > 3 else 1.0


def _sobre(frente, fundo):
    """Cor translúcida composta sobre um fundo opaco."""
    r, g, b, a = frente
    return (r * a + fundo[0] * (1 - a), g * a + fundo[1] * (1 - a), b * a + fundo[2] * (1 - a), 1.0)


def _luminancia(c) -> float:
    def canal(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(c[0]) + 0.7152 * canal(c[1]) + 0.0722 * canal(c[2])


def contraste(a, b) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ArquivosDaInterface(unittest.TestCase):
    def test_referencias_do_index_existem(self):
        for ref in _index().referencias:
            if ref.startswith("#"):
                continue
            with self.subTest(ref=ref):
                self.assertFalse(re.match(r"^[a-z]+:", ref), f"recurso de fora: {ref}")
                if ref.startswith("img/marca/"):
                    continue        # conferidos em MarcaEFontes (são da construção)
                self.assertTrue((WEB / ref.split("?")[0]).is_file(), f"falta {ref}")

    def test_um_arquivo_por_secao(self):
        for secao in ("inicio", "processos", "audiencias", "pauta", "compartilhar", "ajustes", "ajuda"):
            with self.subTest(secao=secao):
                self.assertTrue((WEB / "js" / f"secao-{secao}.js").is_file())
                self.assertIn(f"js/secao-{secao}.js", _index().referencias)
        for nome in ("api.js", "app.js", "componentes.js", "demo.js", "icones.js"):
            self.assertIn(f"js/{nome}", _index().referencias)

    def test_sem_script_em_linha_nem_manipulador_em_atributo(self):
        # A política do servidor é script-src 'self': nada disso rodaria.
        leitor = _index()
        self.assertEqual(leitor.scripts_em_linha, 0)
        self.assertEqual(leitor.manipuladores, [])
        for arquivo in sorted((WEB / "js").glob("*.js")):
            texto = arquivo.read_text(encoding="utf-8")
            with self.subTest(arquivo=arquivo.name):
                self.assertNotRegex(texto, r"\beval\s*\(|new Function\s*\(")

    def test_nada_de_fora(self):
        css = CSS.read_text(encoding="utf-8")
        self.assertNotRegex(css, r"@import")
        self.assertNotRegex(css, r"url\(\s*['\"]?https?:")
        for arquivo in sorted((WEB / "js").glob("*.js")):
            texto = arquivo.read_text(encoding="utf-8")
            with self.subTest(arquivo=arquivo.name):
                self.assertNotRegex(texto, r"(fetch|EventSource)\(\s*['\"`]https?:")
                self.assertNotRegex(texto, r"\bimport\s*\(|^\s*import\s|^\s*export\s")

    def test_javascript_ate_o_es2020(self):
        # Recursos de 2021 em diante (o WebView2 de um Windows 10 sem
        # atualização pode não ter): atribuição lógica, replaceAll, at(),
        # Object.hasOwn, campos privados, structuredClone.
        proibidos = [r"\?\?=", r"\|\|=", r"&&=", r"\.replaceAll\(", r"\.at\(", r"Object\.hasOwn\(",
                     r"structuredClone\(", r"(^|[\s{;])#[a-z]\w*\s*[=;(]"]
        for arquivo in sorted((WEB / "js").glob("*.js")):
            texto = arquivo.read_text(encoding="utf-8")
            for padrao in proibidos:
                with self.subTest(arquivo=arquivo.name, recurso=padrao):
                    self.assertIsNone(re.search(padrao, texto, re.M))

    def test_icones_usados_existem(self):
        icones = (WEB / "js" / "icones.js").read_text(encoding="utf-8")
        definidos = set(re.findall(r'^\s{4}"?([\w-]+)"?:\s*\'', icones, re.M))
        self.assertGreater(len(definidos), 50)
        usados: set[str] = set()
        for arquivo in sorted((WEB / "js").glob("*.js")):
            texto = arquivo.read_text(encoding="utf-8")
            usados |= set(re.findall(r'\bicone\("([\w-]+)"', texto))
            usados |= set(re.findall(r'\bicone: "([\w-]+)"', texto))
            usados |= set(re.findall(r'\bblocoIcone\("([\w-]+)"', texto))
            usados |= set(re.findall(r'\bnomeIcone: "([\w-]+)"', texto))
        self.assertTrue(usados)
        self.assertEqual(sorted(usados - definidos), [])

    def test_portugues_do_brasil_no_documento(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="pt-BR">', html)
        self.assertIn("<title>Helestron</title>", html)


class TextosQueOUsuarioLe(unittest.TestCase):
    """O que a tela diz confere com a própria tela e com as regras do programa."""

    # Citações entre aspas que não são rótulos de botão ou de faixa desta
    # interface (e por quê).
    CITACOES_DE_FORA = {
        "qualquer pessoa com o link",       # opção de compartilhamento do OneDrive/Google
        ".xls",                             # extensão de arquivo
        "(segredo de justiça)",             # o que a planilha da pauta mostra
        "Permitir que aplicativos da área de trabalho acessem o microfone",  # Windows
        "base",                             # nome de modelo de transcrição
        "senha", "pauta", "microfone", "sigiloso", "código", "Excel",        # dicas de busca da Ajuda
    }

    @staticmethod
    def _js_da_interface() -> dict[str, str]:
        return {a.name: a.read_text(encoding="utf-8") for a in sorted((WEB / "js").glob("*.js"))
                if a.name != "demo.js"}

    def _rotulos(self) -> set[str]:
        """Todo texto que a interface põe sozinho num elemento (string literal
        inteira), as opções de Ajustes que o servidor descreve e a barra que a
        captura da pauta injeta no portal."""
        rotulos: set[str] = set()
        for texto in self._js_da_interface().values():
            rotulos |= set(re.findall(r'"([^"\\\n]+)"', texto))
        for extra in (RAIZ / "helestron" / "servidor" / "esquema.py", RAIZ / "helestron" / "pauta" / "captura.py"):
            if extra.is_file():
                rotulos |= set(re.findall(r'"([^"\\\n]+)"', extra.read_text(encoding="utf-8")))
                rotulos |= set(re.findall(r"“([^”]+)”", extra.read_text(encoding="utf-8")))
        return rotulos

    def test_rotulos_citados_existem(self):
        # "use “Recuperar sessão interrompida”" mandava procurar um botão que
        # não existe (o botão é “Recuperar”, na faixa “Uma transcrição foi
        # interrompida”): toda citação de rótulo tem de ser um rótulo da tela.
        rotulos = self._rotulos()
        for nome, texto in self._js_da_interface().items():
            for citado in re.findall(r"“([^”$]+)”", texto):
                if citado in self.CITACOES_DE_FORA:
                    continue
                with self.subTest(arquivo=nome, citado=citado):
                    self.assertIn(citado, rotulos, f"{nome} cita “{citado}”, que não é rótulo da interface")

    def test_rotulos_que_as_mensagens_do_programa_citam(self):
        # O motor e o servidor mandam o usuário a estes botões e faixas.
        rotulos = self._rotulos()
        for citado in ("Recuperar", "Uma transcrição foi interrompida", "Gerar o pacote",
                       "Pacote para o ChatGPT", "Abrir no ChatGPT Work", "Abrir no Claude Code",
                       "Tentar de novo", "Acesso aos portais", "Testar", "Alterar"):
            with self.subTest(citado=citado):
                self.assertIn(citado, rotulos)

    # Citações das mensagens do programa (Python) que não são rótulos desta
    # interface, e por quê.
    CITACOES_DE_FORA_DO_PROGRAMA = CITACOES_DE_FORA | {
        "arquivo", "ids", "fontes", "numeros", "valor",       # campos da API nas mensagens de erro
        "Download Completo", "Pesquisar",                       # botões dos portais
        "Escolher arquivo",                                     # botão do seletor do navegador
        "Microsoft Edge WebView2 Runtime",                      # nome do produto da Microsoft
        "fl.", "evento 1, INIC1", "ignore as instruções anteriores",  # regras para a IA
        "Evento N — descrição — rótulo (data)",                 # marcador do PDF do eProc
        "Acesso ao microfone",                                  # opção do Windows
    }

    def test_rotulos_que_as_mensagens_do_programa_citam_entre_aspas(self):
        # O motor, o servidor, a pauta e a transcrição mandam o usuário a
        # botões e faixas da tela ("Recuperar transcrição interrompida" não
        # existia): toda citação “…” sem variável nas mensagens em Python tem
        # de ser rótulo da interface (ou estar na lista acima, com o motivo).
        rotulos = self._rotulos()
        achadas = 0
        for arquivo in sorted((RAIZ / "helestron").rglob("*.py")):
            texto = arquivo.read_text(encoding="utf-8")
            citados = re.findall(r"“([^”{}%\n]+)”", texto)
            # e a citação com aspas retas escapadas numa string (\"Recuperar ...\")
            citados += re.findall(r'\\"([A-ZÀ-Ú][^"\\{}%\n]{2,60})\\"', texto)
            for citado in citados:
                if citado in self.CITACOES_DE_FORA_DO_PROGRAMA:
                    continue
                achadas += 1
                with self.subTest(arquivo=str(arquivo.relative_to(RAIZ)), citado=citado):
                    self.assertIn(citado, rotulos, f"{arquivo.name} cita “{citado}”, que não é "
                                                   "rótulo da interface")
        self.assertGreater(achadas, 5)
        from helestron.transcricao import ao_vivo

        for citado in (ao_vivo.BOTAO_RECUPERAR, ao_vivo.FAIXA_INTERROMPIDA):
            self.assertIn(citado, rotulos)

    def test_numeros_de_exemplo_com_digito_certo(self):
        # Exemplo que o próprio Helestron recusaria ("dígito verificador
        # errado") não ensina o formato: todo número CNJ escrito na interface
        # passa no módulo 97.
        cnj = re.compile(r"(?<!\d)(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})(?!\d)")
        textos = dict(self._js_da_interface())
        textos["index.html"] = (WEB / "index.html").read_text(encoding="utf-8")
        achados = 0
        for nome, texto in textos.items():
            for m in cnj.finditer(texto):
                n, dv, ano, j, tr, origem = m.groups()
                if set(n + ano + j + tr + origem) == {"0"}:
                    continue            # a máscara 0000000-00.0000.0.00.0000
                achados += 1
                with self.subTest(arquivo=nome, numero=m.group(0)):
                    self.assertEqual(int(n + ano + j + tr + origem + dv) % 97, 1)
        self.assertGreater(achados, 0)

    def test_concordancia_dos_lotes(self):
        # "0 de 1 processo baixados": o particípio concorda com o total.
        for nome, texto in self._js_da_interface().items():
            with self.subTest(arquivo=nome):
                self.assertNotRegex(texto, r'"processo", "processos"\)\} baixados')


class MarcaEFontes(unittest.TestCase):
    def test_fonte_inter_embutida_com_a_licenca(self):
        fonte = WEB / "fontes" / "InterVariable.woff2"
        self.assertTrue(fonte.is_file())
        self.assertEqual(fonte.read_bytes()[:4], b"wOF2")
        licenca = (WEB / "fontes" / "LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("SIL Open Font License", licenca)
        css = CSS.read_text(encoding="utf-8")
        self.assertIn('url("../fontes/InterVariable.woff2") format("woff2")', css)
        self.assertRegex(css, r'--fonte:\s*"Inter", "Segoe UI Variable", "Segoe UI", system-ui')

    def test_marca_gerada_pela_construcao(self):
        # helestron.svg e helestron-64.png vêm de construir/marca.py (área do
        # instalador); a barra lateral, o favicon e "Sobre" usam os dois.
        for nome in ("helestron.svg", "helestron-64.png"):
            with self.subTest(arquivo=nome):
                self.assertTrue((WEB / "img" / "marca" / nome).is_file(),
                                f"falta helestron/web/img/marca/{nome} (gerado por construir/marca.py)")


class CoresEContraste(unittest.TestCase):
    def test_tokens_da_especificacao(self):
        tokens = _tokens()
        esperados = {
            "--navy-900": "#0B1A33", "--navy-800": "#12284A", "--navy-700": "#1B3560",
            "--azul": "#0A66E8", "--azul-claro": "#4C8DFF", "--azul-fundo": "#E8F1FF",
            "--cinza-900": "#1C1C1E", "--cinza-600": "#6B7280", "--cinza-400": "#A1A7B3",
            "--cinza-200": "#E5E7EB", "--cinza-100": "#F2F4F7", "--branco": "#FFFFFF",
            "--verde": "#1F9D55", "--ambar": "#C27C0E", "--vermelho": "#D93A3A",
        }
        for chave, valor in esperados.items():
            with self.subTest(token=chave):
                self.assertEqual(tokens.get(chave, "").upper(), valor)
        self.assertIn("blur(24px) saturate(180%)", tokens["--vidro-desfoque"])

    def test_contraste_aa_dos_textos(self):
        t = _tokens()
        branco = (255, 255, 255, 1.0)
        # O vidro (branco a 62 %) sobre a parte mais azulada do fundo da janela.
        fundo_janela = _rgb("#E8EFFA", t)
        vidro = _sobre(_rgb(t["--vidro"], t), fundo_janela)
        pares = [
            ("texto sobre branco", "--texto", branco),
            ("texto secundário sobre branco", "--texto-2", branco),
            ("texto secundário sobre o vidro", "--texto-2", vidro),
            ("texto terciário sobre branco", "--texto-3", branco),
            ("título navy sobre o vidro", "--navy-900", vidro),
            ("link azul sobre branco", "--azul-texto", branco),
            ("link azul sobre o vidro", "--azul-texto", vidro),
            ("botão tonal", "--azul-texto", _rgb(t["--azul-fundo"], t)),
            ("pílula verde", "--verde-texto", _sobre((31, 157, 85, 0.13), branco)),
            ("pílula âmbar", "--ambar-texto", _sobre((194, 124, 14, 0.14), branco)),
            ("pílula vermelha", "--vermelho-texto", _sobre((217, 58, 58, 0.11), branco)),
        ]
        for nome, frente, fundo in pares:
            with self.subTest(par=nome):
                self.assertGreaterEqual(contraste(_rgb(t[frente], t), fundo), 4.5)
        # Texto branco nos botões cheios.
        for fundo in ("--azul", "--vermelho", "--navy-800"):
            with self.subTest(botao=fundo):
                self.assertGreaterEqual(contraste(branco, _rgb(t[fundo], t)), 4.5)

    def test_movimento_reduzido_e_foco_visivel(self):
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("backdrop-filter", css)


def _mistura(a, b, t: float):
    """O ponto t (0 = topo, 1 = base) de um gradiente de a para b."""
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3)) + (1.0,)


def azul_ou_cinza(c) -> bool:
    """Tom de azul (do ciano ao cobalto, matiz de 195° a 230°) ou cinza neutro.

    É a paleta que o usuário pediu (seção 1, item 2: azul, cinza e branco;
    navy e ardósia são azuis escuros ou acinzentados). Verde, âmbar,
    vermelho, índigo e roxo ficam de fora.
    """
    matiz, _luz, saturacao = colorsys.rgb_to_hls(c[0] / 255, c[1] / 255, c[2] / 255)
    return saturacao < 0.05 or 195 <= matiz * 360 <= 230


def _blocos_do_css() -> dict[str, tuple]:
    """.cor-NOME dos blocos de ícone (e o padrão do .bloco-icone) → (topo, base)."""
    css = CSS.read_text(encoding="utf-8")
    t = _tokens()
    blocos = {}
    for nome, topo, base in re.findall(
            r"^\.cor-([\w-]+)\s*\{\s*background:\s*linear-gradient\(180deg,\s*([^,]+),\s*([^)]+?)\);", css, re.M):
        blocos[nome] = (_rgb(topo, t), _rgb(base, t))
    padrao = re.search(r"^\.bloco-icone\s*\{[^}]*?background:\s*linear-gradient\(180deg,\s*([^,]+),\s*(var\([^)]+\)|[^)]+?)\);",
                       css, re.M | re.S)
    blocos["(padrão)"] = (_rgb(padrao.group(1), t), _rgb(padrao.group(2), t))
    return blocos


def _js(nome: str) -> str:
    return (WEB / "js" / nome).read_text(encoding="utf-8")


class PaletaAzulCinzaBranco(unittest.TestCase):
    """Ícones em tons de azul, navy e cinza; verde, âmbar e vermelho só dizem estado.

    O usuário pediu tons de azul, cinza e branco. Os quadrados de ícone
    (Ajustes, Início, Compartilhar, Ajuda…) variam o tom, como os Ajustes do
    iOS em monocromia azul; as cores de estado (verde = pronto, âmbar =
    atenção, vermelho = erro e gravar) ficam nos pontos, nas pílulas, nas
    faixas e avisos, no anel e no botão de gravar.
    """

    def test_blocos_de_icone_em_azul_navy_e_cinza(self):
        blocos = _blocos_do_css()
        self.assertGreaterEqual(len(blocos), 8, sorted(blocos))
        for nome, (topo, base) in blocos.items():
            with self.subTest(bloco=nome):
                self.assertTrue(azul_ou_cinza(topo) and azul_ou_cinza(base),
                                f".cor-{nome} fora dos tons de azul e cinza")

    def test_icone_branco_legivel_em_todo_bloco(self):
        # WCAG 1.4.11 (contraste de elementos gráficos, 3:1): o traço branco
        # do ícone ocupa do 20 % ao 80 % da altura do quadrado; o ponto mais
        # claro que ele toca é o de 20 % do gradiente.
        branco = (255, 255, 255, 1.0)
        for nome, (topo, base) in _blocos_do_css().items():
            with self.subTest(bloco=nome):
                self.assertGreaterEqual(contraste(branco, _mistura(topo, base, 0.2)), 3.0)

    def test_telas_usam_so_blocos_da_paleta(self):
        # Download em verde, Transcrição em vermelho, Compartilhar em índigo,
        # Pacote em âmbar: o nome de cor de um quadrado de ícone tem de ser um
        # bloco azul ou cinza da paleta (um nome sem .cor-NOME cairia no azul
        # padrão sem ninguém perceber).
        definidos = {nome for nome, (topo, base) in _blocos_do_css().items()
                     if nome != "(padrão)" and azul_ou_cinza(topo) and azul_ou_cinza(base)}
        usados: dict[str, set[str]] = {}
        for arquivo in sorted((WEB / "js").glob("*.js")):
            texto = arquivo.read_text(encoding="utf-8")
            nomes: set[str] = set()
            for trecho in re.findall(r"\bcor:\s*([^,}\n]+)", texto):
                nomes |= set(re.findall(r'"([\w-]+)"', trecho))
            for argumentos in re.findall(r"\bblocoIcone\(([^()]*)\)", texto):
                nomes |= set(re.findall(r'"([\w-]+)"', argumentos.split(",", 1)[1])) if "," in argumentos else set()
            nomes |= set(re.findall(r"(?<![\w-])cor-([a-z]+)\b", texto))
            if nomes:
                usados[arquivo.name] = nomes
        self.assertIn("secao-ajustes.js", usados)
        for nome, cores in usados.items():
            with self.subTest(arquivo=nome):
                self.assertEqual(sorted(cores - definidos), [])

    def test_pontos_do_tipo_de_audiencia_sem_cor_de_estado(self):
        # Custódia em vermelho, Justificação em âmbar e Mediação em verde
        # pareciam erro, aviso e "pronto" na lista da pauta.
        bloco = re.search(r"const COR_TIPO = \{(.*?)\};", _js("componentes.js"), re.S).group(1)
        cores = dict(re.findall(r'"([^"]+)":\s*"(#[0-9A-Fa-f]{6})"', bloco))
        self.assertEqual(len(cores), 7, cores)
        for tipo, cor in cores.items():
            with self.subTest(tipo=tipo, cor=cor):
                self.assertTrue(azul_ou_cinza(_rgb(cor, {})))
        self.assertEqual(len(set(cores.values())), len(cores), "dois tipos com a mesma cor")

    def test_cores_dos_falantes_em_azul_e_cinza_com_contraste_aa(self):
        # O nome do falante (12,5 px, negrito) vai na cor dele sobre o
        # branco e o vidro; o botão F1–F8 apertado põe letra branca sobre ela.
        t = _tokens()
        branco = (255, 255, 255, 1.0)
        vidro = _sobre(_rgb(t["--vidro"], t), _rgb("#E8EFFA", t))
        cores = re.findall(r"#[0-9A-Fa-f]{6}", re.search(r"const CORES = \[(.*?)\];", _js("secao-audiencias.js")).group(1))
        self.assertEqual(len(cores), 8)
        self.assertEqual(len(set(c.upper() for c in cores)), 8, "dois falantes com a mesma cor")
        for i, cor in enumerate(cores, 1):
            c = _rgb(cor, t)
            with self.subTest(falante=f"F{i}", cor=cor):
                self.assertTrue(azul_ou_cinza(c), "fora dos tons de azul e cinza")
                self.assertGreaterEqual(contraste(c, branco), 4.5)
                self.assertGreaterEqual(contraste(c, vidro), 4.5)


if __name__ == "__main__":
    unittest.main()
