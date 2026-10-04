"""Interface web (helestron/web): o que dá para conferir sem abrir o navegador.

Arquivos que o index.html carrega, nada de fora (funciona sem internet e
passa pela Content-Security-Policy do servidor), a fonte Inter com a licença
OFL, os tokens de cor da especificação, o contraste AA dos pares de cor que a
interface usa, os ícones citados pelo código e o JavaScript dentro do ES2020
(o WebView2 mais antigo que o Windows 10 traz).
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
