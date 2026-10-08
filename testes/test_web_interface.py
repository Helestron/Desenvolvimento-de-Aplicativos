"""Interface web (helestron/web) de ponta a ponta, no Chromium, em modo demonstração.

Um servidor HTTP simples serve a pasta web numa thread (com a mesma
Content-Security-Policy do servidor do programa); o Playwright abre
index.html?demo=1 — o demo.js responde a toda a API sem servidor — e percorre
as seções em três tamanhos de janela: a padrão (1280x820, também em tela de
alta densidade), a mínima (1100x720) e a de um notebook 1366x768 com zoom de
125 % (1093x614 pixels CSS). Qualquer erro no console, exceção na página ou
pedido com 404 reprova. Os fluxos principais (lote com pergunta de código,
audiência gravada até o documento, pauta filtrada e exportada, pauta vazia,
autoteste) são exercitados como o usuário faria.

As capturas vão para a pasta de HELESTRON_CAPTURAS, se definida (o CI as
guarda como artefato), ou para uma pasta temporária.

Sem o Chromium do Playwright, os testes do navegador são pulados; o que não
depende dele (contrato da API com a especificação) roda sempre.
"""

from __future__ import annotations

import functools
import glob
import http.server
import os
import re
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from testes.test_web_contrato import azul_ou_cinza

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "helestron" / "web"
ESPECIFICACAO = RAIZ / "docs" / "ESPECIFICACAO.md"
SECOES = ["inicio", "processos", "audiencias", "pauta", "compartilhar", "ajustes", "ajuda"]

# A mesma política do servidor do programa (helestron/servidor/rede.py): a
# interface não pode depender de script em linha nem de nada de fora.
try:
    from helestron.servidor.rede import CSP
except Exception:  # pragma: no cover - servidor ausente nesta árvore
    CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
           "media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
           "form-action 'none'")

# Números de processo (ou o da audiência ao vivo) à vista e mais largos que a
# caixa: cortados ("07001…"). Especificação 7.1: tudo cabe em 1100x720 e em
# 1366x768 com zoom de 125 %.
CORTADOS = """(() => [...document.querySelectorAll('#pagina .numero, #pagina .ao-vivo-processo')]
  .filter(e => e.offsetParent && e.getClientRects().length && e.scrollWidth > e.clientWidth + 1)
  .map(e => e.textContent.trim() + ' (' + e.clientWidth + '/' + e.scrollWidth + ')'))()"""

# Pares de caixas da barra da audiência ao vivo que se sobrepõem (o texto do
# tipo e o selo de sigilo passavam por cima do medidor e do botão Pausar).
SOBREPOSTOS = """(() => { const t = document.querySelector('.ao-vivo-topo'); if (!t) return ['sem barra'];
  const cx = [...t.querySelectorAll('.ao-vivo-sub > *, .ao-vivo-processo, .medidor, .grupo-botoes button, .cronometro, .selo-gravando')];
  const r = [];
  for (let i = 0; i < cx.length; i++) for (let j = i + 1; j < cx.length; j++) {
    if (cx[i].contains(cx[j]) || cx[j].contains(cx[i])) continue;
    const a = cx[i].getBoundingClientRect(), b = cx[j].getBoundingClientRect();
    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left), y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (x > 1 && y > 1) r.push(cx[i].className + ' × ' + cx[j].className);
  }
  return r; })()"""


# Fundo de cada quadrado de ícone à vista (o gradiente e a cor), com o texto
# da linha ou do cartão em que está, para dizer qual saiu da paleta.
CORES_DOS_BLOCOS = """(() => [...document.querySelectorAll('#pagina .bloco-icone, #pagina .alteracao-icone')]
  .filter(e => e.getClientRects().length)
  .map(e => [((e.closest('.linha, .destino, .guia, .acao-item, .alteracao, .cartao') || e).textContent || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 50),
    getComputedStyle(e).backgroundImage + ' ' + getComputedStyle(e).backgroundColor]))()"""


def numero_cnj(sequencial: int, ano: int, j: int, tr: int, origem: int) -> str:
    """O número CNJ com o dígito verificador certo (como o cnj() do demo.js)."""
    n, resto = f"{sequencial:07d}", f"{ano}{j}{tr:02d}{origem:04d}"
    dv = 98 - int(n + resto + "00") % 97
    return f"{n}-{dv:02d}.{ano}.{j}.{tr:02d}.{origem:04d}"


# O processo que a pauta da demonstração marca como sigiloso (demo.js).
PROCESSO_SIGILOSO = numero_cnj(700888, 2025, 8, 2, 1)
# O 2º grau (dígito verificador conferido): a apelação existe nos dois graus;
# o HC (órgão 0000) e os embargos de declaração (/50000) só no 2º.
APELACAO = "0700001-93.2024.8.02.0058"
HC = "0803061-28.2025.8.02.0000"
EMBARGOS = "0706265-50.2017.8.02.0001/50000"

# Palavras que, sem acento, denunciam texto mal escrito na tela.
SEM_ACENTO = re.compile(
    r"\b(nao|voce|audiencias?|sessao|transcricao|transcricoes|relacao|sincronizacao|"
    r"configuracoes|situacao|numero|codigo|informacoes|ate|tambem|ja|so|pagina|"
    r"possivel|automatico|proximos?|ultim[ao]s?|pericia|juizo|orgao|acao|acoes)\b")


# ====================================================== contrato da API
def rotas_da_especificacao() -> set[str]:
    """'MÉTODO /api/caminho' de cada endpoint das seções 6.3, 6.4 e 7.3.

    Entende a forma abreviada da especificação: "`POST /api/x/a` · `/b` ·
    `/c`" quer dizer POST em /api/x/a, /api/x/b e /api/x/c.
    """
    texto = ESPECIFICACAO.read_text(encoding="utf-8")
    rotas: set[str] = set()
    for linha in texto.splitlines():
        trechos = re.findall(r"`([^`]+)`", linha)
        base_metodo, base_pasta = None, None
        for trecho in trechos:
            m = re.match(r"^(GET|POST|DELETE|PUT)\s+(/api/[^\s?`]*)", trecho)
            if m:
                base_metodo, caminho = m.group(1), m.group(2).rstrip("/")
                rotas.add(f"{base_metodo} {caminho}")
                base_pasta = caminho.rsplit("/", 1)[0]
                continue
            m = re.match(r"^(/[a-z][\w-]*)$", trecho)
            if m and base_metodo and base_pasta:
                rotas.add(f"{base_metodo} {base_pasta}{m.group(1)}")
    # 7.3: o autoteste avisa o servidor a cada seção e, no fim, encerra (o
    # /fim é o par do /passo: o servidor o implementa e a tarefa da interface
    # o pede; a 7.3 cita só o passo). 6.4: o canal de eventos.
    for caminho in re.findall(r"POST (/api/autoteste/\w+)", texto):
        rotas.add(f"POST {caminho}")
    if "POST /api/autoteste/passo" in rotas:
        rotas.add("POST /api/autoteste/fim")
    if "/api/eventos" in texto:
        rotas.add("GET /api/eventos")
    return rotas


def rotas_do_cliente() -> set[str]:
    texto = (WEB / "js" / "api.js").read_text(encoding="utf-8")
    return set(re.findall(r'"((?:GET|POST|DELETE|PUT) /api/[^"]+)"', texto))


def rotas_da_demonstracao() -> set[str]:
    texto = (WEB / "js" / "demo.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"((?:GET|POST|DELETE|PUT) /api/[^"]+)":', texto, re.M))


def sem_comentarios(js: str) -> str:
    """O código sem os comentários (que podem citar um endpoint à vontade)."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", js)


class ContratoDaApi(unittest.TestCase):
    """api.js só usa o que a especificação define, e a demonstração cobre tudo."""

    def test_especificacao_lida(self):
        rotas = rotas_da_especificacao()
        # Uma amostra de cada grupo: se a leitura da especificação quebrar, o
        # teste abaixo passaria por vacuidade.
        for rota in ("GET /api/estado", "POST /api/transcricao/retomar",
                     "POST /api/compartilhar/codex", "DELETE /api/pauta/fontes/{id}",
                     "POST /api/autoteste/passo", "GET /api/eventos"):
            self.assertIn(rota, rotas)

    def test_api_js_usa_so_endpoints_da_especificacao(self):
        cliente = rotas_do_cliente()
        self.assertGreater(len(cliente), 50)
        fora = sorted(cliente - rotas_da_especificacao())
        self.assertEqual(fora, [], f"api.js usa endpoints que a especificação não tem: {fora}")

    def test_api_js_cobre_os_endpoints_da_interface(self):
        # Tudo o que a especificação lista (menos o canal de eventos, que é
        # EventSource) tem função no cliente: nenhuma tela inventa caminho.
        faltam = sorted(rotas_da_especificacao() - rotas_do_cliente() - {"GET /api/eventos"})
        self.assertEqual(faltam, [], f"endpoints da especificação sem função em api.js: {faltam}")

    def test_eventos_do_cliente_sao_os_da_especificacao(self):
        texto = (WEB / "js" / "api.js").read_text(encoding="utf-8")
        lista = re.search(r"const EVENTOS = \[([^\]]+)\]", texto).group(1)
        eventos = set(re.findall(r'"(\w+)"', lista))
        espec = ESPECIFICACAO.read_text(encoding="utf-8")
        tabela = espec.split("### 6.4", 1)[1].split("### 6.5", 1)[0]
        da_espec = set(re.findall(r"^\| `(\w+)` \|", tabela, re.M))
        self.assertEqual(eventos, da_espec)

    def test_demonstracao_responde_a_toda_a_api(self):
        faltam = sorted(rotas_do_cliente() - rotas_da_demonstracao())
        self.assertEqual(faltam, [], f"demo.js não responde a: {faltam}")

    def test_telas_nao_montam_caminho_de_api(self):
        for arquivo in sorted((WEB / "js").glob("*.js")):
            if arquivo.name in ("api.js", "demo.js"):
                continue
            with self.subTest(arquivo=arquivo.name):
                self.assertNotIn("/api/", sem_comentarios(arquivo.read_text(encoding="utf-8")))

    def test_token_e_cabecalho_do_contrato(self):
        texto = (WEB / "js" / "api.js").read_text(encoding="utf-8")
        self.assertIn('"X-Helestron-Token"', texto)
        self.assertIn("sessionStorage", texto)
        self.assertIn("history.replaceState", texto)
        self.assertIn('"/api/eventos"', texto)
        self.assertIn('?t=" + encodeURIComponent(token)', texto)
        self.assertIn('"sem_dialogo"', texto)
        self.assertIn('fd.append("arquivo"', texto)


# ============================================================ navegador
# A marca (img/marca/helestron.svg e helestron-64.png) é gerada pela
# construção (construir/marca.py). Se ainda não estiver na árvore, o servidor
# de teste entrega uma provisória: estes testes cuidam da interface, e
# test_web_contrato.MarcaEFontes cobra os arquivos de verdade.
MARCA_PROVISORIA_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                        b'<rect width="64" height="64" rx="14" fill="#12284A"/></svg>')
MARCA_PROVISORIA_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf00000301010018dd8db00000000049454e44ae426082")


class _Manipulador(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        caminho = self.path.split("?")[0]
        if caminho.startswith("/img/marca/") and not (WEB / caminho.lstrip("/")).is_file():
            corpo, tipo = (MARCA_PROVISORIA_SVG, "image/svg+xml") if caminho.endswith(".svg") \
                else (MARCA_PROVISORIA_PNG, "image/png")
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        super().do_GET()

    def end_headers(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def _executavel_chromium() -> str | None:
    """O Chromium do Playwright: o da versão instalada ou outro da mesma pasta."""
    pastas = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), "/opt/pw-browsers",
              str(Path.home() / ".cache" / "ms-playwright")]
    for pasta in filter(None, pastas):
        for padrao in ("chromium-*/chrome-linux/chrome", "chromium-*/chrome-win/chrome.exe",
                       "chromium_headless_shell-*/chrome-linux/headless_shell"):
            achados = sorted(glob.glob(os.path.join(pasta, padrao)))
            if achados:
                return achados[-1]
    return None


class _Navegador:
    """Playwright + Chromium + servidor da pasta web, para a classe toda."""

    def __init__(self):
        from playwright.sync_api import sync_playwright

        self.servidor = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(_Manipulador, directory=str(WEB)))
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.servidor.server_address[1]}/index.html"
        self.pw = sync_playwright().start()
        try:
            try:
                self.chromium = self.pw.chromium.launch()
            except Exception as erro:
                if "Executable doesn't exist" not in str(erro):
                    raise
                exe = _executavel_chromium()
                if exe is None:
                    raise unittest.SkipTest("Chromium do Playwright não instalado") from erro
                self.chromium = self.pw.chromium.launch(executable_path=exe)
        except BaseException:
            self.pw.stop()
            self.servidor.shutdown()
            raise

    def fechar(self):
        try:
            self.chromium.close()
        finally:
            self.pw.stop()
            self.servidor.shutdown()
            self.servidor.server_close()


class InterfaceNoNavegador(unittest.TestCase):
    nav: _Navegador | None = None

    @classmethod
    def setUpClass(cls):
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError as erro:
            raise unittest.SkipTest("Playwright não instalado") from erro
        cls.nav = _Navegador()
        destino = os.environ.get("HELESTRON_CAPTURAS")
        if destino:
            cls.capturas = Path(destino)
            cls._capturas_temporarias = False
        else:
            cls.capturas = Path(tempfile.mkdtemp(prefix="helestron-capturas-"))
            cls._capturas_temporarias = True
        cls.capturas.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.nav is not None:
            cls.nav.fechar()
        if getattr(cls, "_capturas_temporarias", False):
            shutil.rmtree(cls.capturas, ignore_errors=True)

    # ---------------------------------------------------------- apoio
    def abrir(self, largura=1280, altura=820, escala=1.0, extra="", secao="inicio", permissoes=None):
        contexto = self.nav.chromium.new_context(
            viewport={"width": largura, "height": altura}, device_scale_factor=escala,
            locale="pt-BR", timezone_id="America/Maceio", permissions=permissoes or [])
        pagina = contexto.new_page()
        problemas: list[str] = []
        pagina.on("console", lambda m: problemas.append(f"console.{m.type}: {m.text}")
                  if m.type in ("error", "warning") else None)
        pagina.on("pageerror", lambda e: problemas.append(f"exceção: {e}"))
        pagina.on("response", lambda r: problemas.append(f"HTTP {r.status}: {r.url}")
                  if r.status >= 400 else None)
        pagina.on("requestfailed", lambda r: problemas.append(f"falhou: {r.url}"))
        self.addCleanup(contexto.close)
        pagina.goto(f"{self.nav.base}?demo=1{extra}#/{secao}")
        self.esperar_secao(pagina, secao)
        pagina.problemas = problemas
        return pagina

    def esperar_secao(self, pagina, secao):
        pagina.wait_for_function(
            "s => document.documentElement.dataset.secao === s && "
            "document.documentElement.dataset.pronta === '1'", arg=secao, timeout=15000)
        pagina.evaluate("document.fonts.ready")

    def ir(self, pagina, secao):
        pagina.evaluate("s => { location.hash = '#/' + s; }", secao)
        self.esperar_secao(pagina, secao)

    def capturar(self, pagina, nome):
        pagina.wait_for_timeout(350)       # animação de entrada
        pagina.screenshot(path=str(self.capturas / f"{nome}.png"))

    def sem_problemas(self, pagina):
        self.assertEqual(pagina.problemas, [], "erros no navegador:\n" + "\n".join(pagina.problemas))

    def conferir_secao(self, pagina, secao):
        """Os elementos que cada seção precisa ter."""
        q = pagina.locator
        self.assertEqual(q(".titulo-grande").count(), 1)
        # Botão dentro de botão (ou de link) é HTML inválido, e o clique no de
        # dentro dispara também o de fora (o "Testar" abria a folha da senha).
        aninhados = pagina.evaluate(
            "document.querySelectorAll('button button, button a[href], a[href] button, a[href] a[href]').length")
        self.assertEqual(aninhados, 0, f"elemento interativo dentro de outro em {secao}")
        self.assertEqual(q(".nav-item[aria-current='page']").get_attribute("data-secao"), secao)
        if secao == "inicio":
            self.assertEqual(q(".cartao-funcao").count(), 4)
            for rotulo in ("Hoje na pauta", "Atividade recente", "Primeiros passos"):
                self.assertEqual(q(f"section[aria-label='{rotulo}']").count(), 1, rotulo)
        elif secao == "processos":
            self.assertTrue(q("#area-soltar").is_visible())
            for rotulo in ("Escolher arquivo", "Colar lista", "Link"):
                self.assertTrue(q(f"#area-soltar button:has-text('{rotulo}')").is_visible(), rotulo)
            self.assertGreater(q("#ultimos-lotes .linha").count(), 0)
        elif secao == "audiencias":
            # os dois modos no topo: ao vivo e arquivo de áudio ou vídeo
            self.assertEqual(q("#modo-audiencia [role='radio']").count(), 2)
            self.assertTrue(q("#botao-gravar").is_visible())
            self.assertTrue(q("#processo-audiencia").is_visible())
            self.assertEqual(q(".participante").count(), 8)
            self.assertEqual(q(".medidor").count(), 1)
            self.assertEqual(q("#sigilo-audiencia[role='switch']").count(), 1)
        elif secao == "pauta":
            self.assertEqual(q("#periodo-pauta [role='radio']").count(), 4)
            self.assertGreaterEqual(q(".pauta-dia").count(), 3)
            self.assertGreaterEqual(q(".audiencia").count(), 5)
            self.assertEqual(q("#chips-pauta .chip").count(), 4)
            for seletor in ("#botao-sincronizar", "#botao-exportar", "#acao-capturar", "#acao-importar",
                            "#monitorar-pauta"):
                self.assertEqual(q(seletor).count(), 1, seletor)
        elif secao == "compartilhar":
            self.assertEqual(q(".destino").count(), 7)
            self.assertEqual(q("#botao-preparar").count(), 1)
        elif secao == "ajustes":
            self.assertEqual(q(".ajustes-indice .linha").count(), 8)
            self.assertGreaterEqual(q("[data-portal]").count(), 1)
        elif secao == "ajuda":
            self.assertTrue(q("#busca-ajuda").is_visible())
            self.assertGreaterEqual(q(".guia").count(), 5)
            self.assertGreaterEqual(q(".pergunta-frequente").count(), 10)

    def texto_em_portugues(self, pagina, secao):
        texto = pagina.evaluate("document.querySelector('#pagina').innerText")
        # Caminhos (Acervo\Transcricoes) têm o nome da pasta, que é sem acento mesmo.
        texto = re.sub(r"\S*\\\S*", " ", texto)
        achado = SEM_ACENTO.search(texto.lower())
        self.assertIsNone(achado, f"texto sem acento em {secao}: …{achado and texto.lower()[max(0, achado.start() - 40):achado.end() + 40]}…")

    def numeros_inteiros(self, pagina, secao):
        """Nenhum número de processo à vista cortado com reticências."""
        cortados = pagina.evaluate(CORTADOS)
        self.assertEqual(cortados, [], f"números de processo cortados em {secao}")

    def blocos_fora_da_paleta(self, pagina) -> list[str]:
        """Quadrados de ícone à vista com alguma cor fora dos tons de azul e cinza."""
        fora = []
        for rotulo, fundo in pagina.evaluate(CORES_DOS_BLOCOS):
            for m in re.finditer(r"rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)", fundo):
                if m.group(4) is not None and float(m.group(4)) == 0:
                    continue            # fundo transparente (o do gradiente)
                cor = tuple(int(m.group(i)) for i in (1, 2, 3))
                if not azul_ou_cinza(cor):
                    fora.append(f"{rotulo} → rgb{cor}")
        return fora

    def sem_rolagem_horizontal(self, pagina, secao):
        larguras = pagina.evaluate(
            "[document.documentElement.scrollWidth, innerWidth, document.getElementById('conteudo').scrollWidth,"
            " document.getElementById('conteudo').clientWidth]")
        self.assertLessEqual(larguras[0], larguras[1], f"rolagem horizontal na página em {secao}")
        self.assertLessEqual(larguras[2], larguras[3] + 1, f"conteúdo mais largo que a área em {secao}")

    # ---------------------------------------------------------- testes
    def test_todas_as_secoes_nos_tres_tamanhos(self):
        tamanhos = [("1280x820", 1280, 820, 1), ("1280x820@2x", 1280, 820, 2),
                    ("1100x720", 1100, 720, 1), ("1366x768-zoom125", 1093, 614, 1.25)]
        for nome, largura, altura, escala in tamanhos:
            with self.subTest(tamanho=nome):
                pagina = self.abrir(largura, altura, escala)
                for i, secao in enumerate(SECOES):
                    # Metade pelo menu, metade pelo atalho Ctrl+N.
                    if i % 2:
                        pagina.keyboard.press(f"Control+{i + 1}")
                    else:
                        pagina.click(f".nav-item[data-secao='{secao}']")
                    self.esperar_secao(pagina, secao)
                    self.conferir_secao(pagina, secao)
                    self.sem_rolagem_horizontal(pagina, secao)
                    self.numeros_inteiros(pagina, secao)
                    if nome == "1280x820":
                        self.texto_em_portugues(pagina, secao)
                    self.capturar(pagina, f"{nome}-{secao}")
                self.sem_problemas(pagina)

    def test_lote_com_pergunta_de_codigo(self):
        pagina = self.abrir(secao="processos")
        pagina.click("#area-soltar button:has-text('Colar lista')")
        pagina.fill(".folha textarea", "Processos para hoje:\n0700231-15.2024.8.02.0001\n"
                                       "1004512-63.2024.8.26.0100; 5004417-09.2024.8.21.0001\n"
                                       "0700231-99.2024.8.02.0001 (dígito errado)")
        pagina.click(".folha button:has-text('Ler a lista')")
        pagina.wait_for_selector(".revisao")
        self.assertEqual(pagina.locator(".revisao tbody tr").count(), 3)
        self.assertIn("dígito verificador", pagina.locator(".revisao .faixa-aviso").inner_text())
        self.capturar(pagina, "fluxo-revisao")
        pagina.click("#botao-baixar")
        pagina.wait_for_selector(".folha-pergunta")
        self.assertTrue(pagina.locator("#campo-codigo").is_visible())
        self.assertTrue(pagina.locator(".folha button:has-text('Pedir novo código')").is_visible())
        self.capturar(pagina, "fluxo-folha-codigo")
        pagina.fill("#campo-codigo", "482193")         # seis dígitos: envia sozinho
        pagina.wait_for_selector(".folha-pergunta", state="detached")
        pagina.wait_for_selector(".lote-concluido", timeout=20000)
        texto = pagina.locator(".andamento").inner_text()
        self.assertIn("Lote concluído", texto)
        self.assertEqual(pagina.locator(".itens-lote tbody tr").count(), 3)
        respondidas = pagina.evaluate(
            "Helestron.demo.chamadas.filter(c => c.rota.endsWith('/responder')).map(c => c.corpo.valor)")
        self.assertEqual(respondidas, ["482193"])
        iniciou = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/download/iniciar').corpo")
        # o grau do lote vai sempre (o dos Ajustes, se ninguém o trocou)
        self.assertEqual(sorted(iniciou["opcoes"]), ["grau", "navegador_visivel", "rebaixar", "separar_sigilosos"])
        self.assertEqual(iniciou["opcoes"]["grau"], "1g")
        self.assertEqual(len(iniciou["processos"]), 3)
        self.capturar(pagina, "fluxo-lote-concluido")
        self.sem_problemas(pagina)

    def test_audiencia_gravada_ate_o_documento(self):
        pagina = self.abrir(secao="audiencias")
        self.assertTrue(pagina.locator("#botao-gravar").is_disabled())
        pagina.select_option("#tipo-audiencia", "Conciliação")
        pagina.fill("#processo-audiencia", "07002311520248020001")
        self.assertIn("Número válido", pagina.locator("#ajuda-processo").inner_text())
        pagina.click("#testar-microfone")
        pagina.wait_for_function("() => document.querySelectorAll('.medidor span.aceso').length > 0")
        pagina.click("#botao-gravar")
        pagina.wait_for_selector(".ao-vivo")
        pagina.wait_for_selector(".fala", timeout=10000)
        pagina.keyboard.press("F3")
        self.assertEqual(pagina.locator(".falante[aria-pressed='true']").inner_text().strip(), "F3\nDefensor(a)")
        pagina.wait_for_function("() => document.querySelectorAll('.fala').length >= 3", timeout=10000)
        self.capturar(pagina, "fluxo-gravando")
        falantes = pagina.evaluate(
            "Helestron.demo.chamadas.filter(c => c.rota === 'POST /api/transcricao/falante').map(c => c.corpo.falante)")
        self.assertEqual(falantes, ["Defensor(a)"])
        # "Ouvindo…" só enquanto o áudio é captado: pausada, nada é gravado.
        self.assertTrue(pagina.locator(".ouvindo").is_visible())
        pagina.click("#botao-pausar")
        pagina.wait_for_selector(".selo-gravando.pausado")
        self.assertTrue(pagina.locator(".ouvindo").is_hidden(), "“Ouvindo…” à vista com a gravação pausada")
        self.capturar(pagina, "fluxo-pausado")
        pagina.click("#botao-pausar")
        pagina.wait_for_selector(".selo-gravando:not(.pausado)")
        self.assertTrue(pagina.locator(".ouvindo").is_visible())
        pagina.click("#botao-encerrar")
        pagina.click(".folha button:has-text('Encerrar e salvar')")
        pagina.wait_for_selector(".documento-pronto", timeout=10000)
        self.assertTrue(pagina.locator(".ouvindo").count() == 0 or pagina.locator(".ouvindo").is_hidden())
        self.assertIn("0700231-15.2024.8.02.0001.docx", pagina.locator(".documento-pronto").inner_text())
        self.capturar(pagina, "fluxo-documento")
        # "Transcrição salva" (era verde) e "Revisar com o modelo preciso"
        # (era índigo): quadrados de ícone em azul; o estado está no título.
        self.assertEqual(self.blocos_fora_da_paleta(pagina), [])
        iniciou = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/transcricao/iniciar').corpo")
        self.assertEqual(iniciou["processo"], "0700231-15.2024.8.02.0001")
        self.assertEqual(iniciou["participantes"]["F1"], "Juiz(a)")
        self.assertIs(iniciou["sigiloso"], False)
        self.assertEqual(iniciou["tipo"], "Conciliação")
        # O tipo escolhido vai para a ficha do documento e da revisão.
        encerrou = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/transcricao/encerrar').corpo")
        self.assertEqual(encerrou, {"tipo": "Conciliação"})
        pagina.click("#botao-revisar")
        pagina.wait_for_function(
            "() => Helestron.demo.chamadas.some(c => c.rota === 'POST /api/transcricao/gravacao')")
        revisou = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/transcricao/gravacao').corpo")
        self.assertIs(revisou["revisao"], True)
        self.assertEqual(revisou["tipo"], "Conciliação")
        pagina.wait_for_selector("button:has-text('Abrir a revisão')", timeout=15000)
        self.sem_problemas(pagina)

    def test_pauta_filtros_alteracoes_e_exportacao(self):
        pagina = self.abrir(secao="pauta")
        pagina.click("#periodo-pauta [role='radio']:has-text('Mês')")
        pagina.wait_for_function("() => document.querySelector('.pauta-intervalo').textContent.includes(' de 20')")
        pagina.fill("#busca-pauta", "Custódia")
        pagina.wait_for_function("() => [...document.querySelectorAll('.audiencia')].every(a => a.textContent.includes('Custódia'))")
        pagina.fill("#busca-pauta", "")
        pagina.select_option("#filtro-sistema", "eproc")
        pagina.wait_for_function("() => [...document.querySelectorAll('.audiencia')].every(a => a.textContent.includes('eProc'))")
        pagina.select_option("#filtro-sistema", "")
        pagina.wait_for_timeout(400)
        self.capturar(pagina, "fluxo-pauta-mes")
        pagina.click("#botao-exportar")
        pagina.wait_for_selector(".folha")
        self.capturar(pagina, "fluxo-pauta-exportar")
        pagina.click(".folha button:has-text('Exportar')")
        pagina.wait_for_selector(".aviso:has-text('Planilha pronta')")
        exportou = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/pauta/exportar').corpo")
        self.assertRegex(exportou["de"], r"^\d{4}-\d{2}-01$")
        self.assertIs(exportou["incluir_partes_sigilosos"], False)
        # Baixar os autos de uma audiência manda o id e o dia dela.
        pagina.locator(".audiencia button[title='Baixar os autos']").first.click()
        pagina.wait_for_selector(".aviso:has-text('Baixando os autos')")
        pedido = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/pauta/baixar-autos').corpo")
        self.assertEqual(len(pedido["ids"]), 1)
        self.assertEqual(pedido["de"], pedido["ate"])
        # Alterações: o selo da barra lateral some quando marcadas como vistas.
        self.assertEqual(pagina.locator(".nav-item[data-secao='pauta'] .nav-selo").inner_text(), "3")
        pagina.click(".alteracoes button:has-text('Marcar como vistas')")
        pagina.wait_for_selector(".nav-item[data-secao='pauta'] .nav-selo", state="detached")
        self.sem_problemas(pagina)

    def test_pauta_vazia_explica_como_comecar(self):
        pagina = self.abrir(extra="&pauta=vazia", secao="pauta")
        vazio = pagina.locator(".pauta-vazia-cartao")
        self.assertTrue(vazio.is_visible())
        texto = vazio.inner_text()
        self.assertIn("Sua pauta ainda está vazia", texto)
        for rotulo in ("Sincronizar", "Capturar no portal", "Importar relatório"):
            self.assertIn(rotulo, texto)
        self.capturar(pagina, "pauta-vazia")
        # Sem fonte, Sincronizar pergunta o portal antes.
        vazio.locator("button:has-text('Sincronizar')").click()
        pagina.wait_for_selector(".folha:has-text('De onde vem a sua pauta?')")
        pagina.click(".folha button:has-text('Sincronizar')")
        pagina.wait_for_selector(".folha", state="detached")
        rotas = pagina.evaluate("Helestron.demo.chamadas.map(c => c.rota)")
        self.assertIn("POST /api/pauta/fontes", rotas)
        self.assertIn("POST /api/pauta/sincronizar", rotas)
        self.sem_problemas(pagina)

    def test_sem_dialogo_nativo_usa_o_seletor_do_navegador(self):
        pagina = self.abrir(extra="&sem_dialogo=1", secao="processos")
        relacao = Path(tempfile.mkdtemp(prefix="helestron-relacao-")) / "Relação de outubro.csv"
        self.addCleanup(shutil.rmtree, relacao.parent, True)
        relacao.write_text("processo\n0700231-15.2024.8.02.0001\n", encoding="utf-8")
        with pagina.expect_file_chooser() as escolha:
            pagina.click("#area-soltar button:has-text('Escolher arquivo')")
        escolha.value.set_files(str(relacao))
        pagina.wait_for_selector(".revisao")
        self.assertEqual(pagina.locator("#nome-lote").input_value(), "Relação de outubro")
        self.sem_problemas(pagina)

    def test_autoteste_percorre_as_secoes_em_ordem(self):
        pagina = self.abrir(extra="&autoteste=1")
        pagina.wait_for_function("() => document.documentElement.dataset.autoteste === 'fim'", timeout=60000)
        passos = pagina.evaluate(
            "Helestron.demo.chamadas.filter(c => c.rota === 'POST /api/autoteste/passo').map(c => c.corpo.secao)")
        self.assertEqual(passos, SECOES)
        fim = pagina.evaluate(
            "Helestron.demo.chamadas.filter(c => c.rota === 'POST /api/autoteste/fim').map(c => c.corpo)")
        self.assertEqual(len(fim), 1)
        self.assertTrue(all(s["pronta"] and not s["erro_na_tela"] for s in fim[0]["secoes"]))
        self.sem_problemas(pagina)

    def test_ajustes_salva_na_hora(self):
        pagina = self.abrir(secao="ajustes")
        pagina.click(".ajustes-indice a[data-grupo='download']")
        pagina.wait_for_selector("#cfg-download-mostrar_navegador")
        pagina.click("#cfg-download-mostrar_navegador")
        pagina.wait_for_function("() => Helestron.demo.chamadas.some(c => c.rota === 'POST /api/config')")
        gravou = pagina.evaluate(
            "Helestron.demo.chamadas.filter(c => c.rota === 'POST /api/config').map(c => c.corpo)")
        self.assertEqual(gravou[-1], {"secao": "download", "chave": "mostrar_navegador", "valor": True})
        # Pasta dos sigilosos dentro do acervo: recusada, com a explicação.
        pagina.click(".ajustes-indice a[data-grupo='pastas']")
        pagina.wait_for_selector("text=Pasta dos sigilosos")
        self.capturar(pagina, "ajustes-pastas")
        pagina.click(".ajustes-indice a[data-grupo='sobre']")
        pagina.wait_for_selector("text=Verificação da instalação")
        self.capturar(pagina, "ajustes-sobre")
        self.sem_problemas(pagina)

    def test_foco_visivel_no_teclado(self):
        pagina = self.abrir(secao="pauta")
        vistos = 0
        for _ in range(12):
            pagina.keyboard.press("Tab")
            pagina.wait_for_timeout(260)       # a transição da sombra termina
            foco = pagina.evaluate(
                "() => { const a = document.activeElement; const c = getComputedStyle(a);"
                " return [a.tagName, a.className, a.matches(':focus-visible'), c.boxShadow, c.outlineStyle]; }")
            if foco[0] == "BODY":
                continue
            vistos += 1
            with self.subTest(elemento=f"{foco[0]}.{foco[1]}"):
                self.assertTrue(foco[2])
                self.assertTrue(foco[3] != "none" or foco[4] != "none", f"sem anel de foco: {foco}")
        self.assertGreaterEqual(vistos, 8)
        self.sem_problemas(pagina)

    def test_ajuda_pesquisavel(self):
        pagina = self.abrir(secao="ajuda")
        pagina.fill("#busca-ajuda", "codigo")      # sem acento também acha "código"
        pagina.wait_for_function("() => document.querySelectorAll('mark').length > 0")
        self.assertIn("código", pagina.locator("mark").first.inner_text().lower())
        pagina.fill("#busca-ajuda", "xyzzy")
        pagina.wait_for_selector("text=Nada encontrado")
        self.sem_problemas(pagina)


    # ------------------------------------------------- correções da revisão
    def chamadas(self, pagina, rota):
        return pagina.evaluate("r => Helestron.demo.chamadas.filter(c => c.rota === r).map(c => c.corpo)", rota)

    def avisos_por_cima(self, pagina, seletor):
        """Os elementos de 'seletor' que algum aviso (toast) cobre."""
        return pagina.evaluate("""s => { const av = [...document.querySelectorAll('.aviso:not(.saindo)')].map(a => a.getBoundingClientRect());
          return [...document.querySelectorAll(s)].filter(e => { const r = e.getBoundingClientRect();
            return r.width && av.some(a => Math.min(a.right, r.right) - Math.max(a.left, r.left) > 1 && Math.min(a.bottom, r.bottom) - Math.max(a.top, r.top) > 1); })
          .map(e => e.textContent.trim().slice(0, 40)); }""", seletor)

    def test_testar_o_acesso_do_eproc(self):
        """Ajustes › Acessos: o Testar da linha do eProc do TJAL testa o eProc
        (vai o sistema, e não só a sigla) e não abre a folha da senha junto."""
        pagina = self.abrir(secao="ajustes")
        linha = pagina.locator("[data-portal='eproc:TJAL']")
        linha.wait_for()
        linha.locator("button:has-text('Cadastrar')").click()
        pagina.wait_for_selector(".folha:has-text('Acesso ao eProc · TJAL')")
        pagina.fill("#acesso-usuario", "AL123")
        pagina.fill("#acesso-senha", "senha do eproc")
        pagina.click(".folha button:has-text('Salvar')")
        pagina.wait_for_selector(".folha-fundo", state="detached")
        linha = pagina.locator("[data-portal='eproc:TJAL']:has-text('Senha guardada')")
        linha.wait_for()
        linha.locator("button:has-text('Testar')").click()
        pagina.wait_for_selector("[data-portal='eproc:TJAL'] .resultado-teste")
        pagina.wait_for_timeout(300)
        self.assertEqual(pagina.locator(".folha-fundo").count(), 0, "o Testar abriu também a folha da senha")
        self.assertEqual(self.chamadas(pagina, "POST /api/acessos/testar"), [{"tribunal": "TJAL", "sistema": "eproc"}])
        tarefa = pagina.evaluate("[...Helestron.loja.tarefas.values()].filter(t => t.tipo === 'teste_login').map(t => t.titulo)")
        self.assertEqual(tarefa, ["Testar o acesso ao TJAL · eProc"])
        # O resultado aparece na linha do portal, ao lado do botão, e não num
        # aviso por cima da lista.
        pagina.wait_for_selector("[data-portal='eproc:TJAL'] .resultado-teste.ok", timeout=10000)
        self.assertIn("Acesso confirmado", pagina.locator("[data-portal='eproc:TJAL']").inner_text())
        pagina.wait_for_timeout(300)
        self.assertEqual(pagina.locator(".aviso:has-text('Testar o acesso')").count(), 0)
        self.capturar(pagina, "ajustes-acesso-testado")
        self.sem_problemas(pagina)

    def test_primeiros_passos_da_pauta(self):
        """A pauta só aparece como configurada quando está: sem fonte e sem
        sincronização, o passo fica por fazer, com o botão para resolver."""
        pagina = self.abrir(extra="&pauta=vazia")
        passo = pagina.locator(".passo[data-passo='pauta']")
        self.assertEqual(passo.count(), 1)
        self.assertNotIn("feito", passo.get_attribute("class"))
        self.assertTrue(passo.locator("button:has-text('Configurar')").is_visible())
        texto = pagina.locator("#pagina").inner_text()
        self.assertNotIn("Sincronizada com o e-SAJ e o eProc", texto)
        self.assertIn("A pauta ainda não foi configurada", texto)
        passo.locator("button:has-text('Configurar')").click()
        self.esperar_secao(pagina, "pauta")
        self.sem_problemas(pagina)
        # Sincronizada: feito, com a data de verdade.
        pagina = self.abrir()
        passo = pagina.locator(".passo[data-passo='pauta']")
        self.assertIn("feito", passo.get_attribute("class"))
        self.assertIn("Última sincronização", passo.inner_text())
        self.sem_problemas(pagina)

    def test_audiencia_ao_vivo_no_tamanho_minimo(self):
        """Em 1100x720 e em 1366x768 a 125 %, o número do processo gravado e
        os das listas laterais aparecem inteiros, e nada da barra ao vivo
        passa por cima do medidor ou dos botões, nem os avisos."""
        for nome, largura, altura, escala in (("1100x720", 1100, 720, 1), ("1366x768-zoom125", 1093, 614, 1.25)):
            with self.subTest(tamanho=nome):
                pagina = self.abrir(largura, altura, escala, secao="audiencias")
                pagina.wait_for_selector(".transcricoes-recentes .item-titulo")
                self.numeros_inteiros(pagina, "audiências")
                pagina.fill("#processo-audiencia", "07002311520248020001")
                pagina.click("#sigilo-audiencia")
                pagina.click("#botao-gravar")
                pagina.wait_for_selector(".ao-vivo")
                pagina.wait_for_selector(".fala", timeout=10000)
                pagina.wait_for_selector(".aviso")          # "Processo em segredo de justiça…"
                self.numeros_inteiros(pagina, "audiência ao vivo")
                self.assertEqual(pagina.evaluate(SOBREPOSTOS), [])
                self.assertEqual(self.avisos_por_cima(pagina, ".ao-vivo-topo button, .falante"), [])
                self.capturar(pagina, f"{nome}-ao-vivo-sigilosa")
                self.sem_problemas(pagina)

    def test_avisos_da_pauta_sem_repeticao_e_sem_cobrir_botoes(self):
        pagina = self.abrir(secao="pauta")
        pagina.click("#botao-sincronizar")
        pagina.wait_for_function("() => [...Helestron.loja.tarefas.values()].some(t => t.tipo === 'pauta_sincronizar')")
        # Um aviso da própria sincronização (fonte com problema): na Pauta, ele
        # vai para a faixa, não para um aviso por cima dos botões.
        pagina.evaluate("""() => { const t = [...Helestron.loja.tarefas.values()].find(t => t.tipo === 'pauta_sincronizar');
            Helestron.api.emitir('aviso', { titulo: 'Pauta: e-SAJ · TJAL', mensagem: 'O portal não respondeu.', nivel: 'aviso', tarefa: t.id }); }""")
        pagina.wait_for_selector("#resultado-pauta .faixa", timeout=15000)
        pagina.wait_for_timeout(500)
        self.assertEqual(pagina.locator(".aviso").count(), 0, "o resultado da sincronização repetido num aviso")
        # O aviso de fim da exportação não cobre Exportar Excel nem Sincronizar.
        pagina.click("#botao-exportar")
        pagina.click(".folha button:has-text('Exportar')")
        pagina.wait_for_selector(".aviso:has-text('Planilha pronta')")
        pagina.wait_for_timeout(400)
        self.assertEqual(self.avisos_por_cima(pagina, "#botao-exportar, #botao-sincronizar"), [])
        self.capturar(pagina, "pauta-aviso-abaixo-do-cabecalho")
        # A mesma frase não aparece duas vezes.
        pagina.evaluate("""() => { Helestron.ui.aviso({ titulo: 'Pauta: e-SAJ · TJAL', mensagem: 'Frase repetida de teste.', tipo: 'alerta' });
            Helestron.ui.aviso({ titulo: 'Sincronizar a pauta — não deu certo', mensagem: 'Frase repetida de teste.', tipo: 'erro' }); }""")
        self.assertEqual(pagina.locator(".aviso:not(.saindo):has-text('Frase repetida de teste.')").count(), 1)
        # Nem quando o erro do fim da tarefa traz a frase da fonte dentro dele.
        pagina.evaluate("""() => { Helestron.ui.aviso({ titulo: 'Pauta: e-SAJ · TJAC', mensagem: 'O portal não respondeu (tempo esgotado)', tipo: 'alerta' });
            Helestron.ui.aviso({ titulo: 'Sincronizar a pauta — não deu certo', tipo: 'erro',
              mensagem: 'Não consegui ler a pauta: e-SAJ · TJAC — O portal não respondeu (tempo esgotado).' }); }""")
        self.assertEqual(pagina.locator(".aviso:not(.saindo):has-text('O portal não respondeu (tempo esgotado)')").count(), 1)
        self.sem_problemas(pagina)

    def test_lote_sem_nenhum_pdf_nao_aparece_como_sucesso(self):
        pagina = self.abrir(extra="&lote=falhas", secao="processos")
        pagina.click("#area-soltar button:has-text('Colar lista')")
        pagina.fill(".folha textarea", "5004417-09.2024.8.21.0001\n" + numero_cnj(5012003, 2025, 8, 21, 10))
        pagina.click(".folha button:has-text('Ler a lista')")
        pagina.wait_for_selector(".revisao")
        pagina.click("#botao-baixar")
        pagina.wait_for_selector(".lote-concluido", timeout=20000)
        texto = pagina.locator(".andamento").inner_text()
        self.assertIn("Nenhum processo baixado", texto)
        self.assertNotIn("Lote concluído", texto)
        classes = pagina.locator(".andamento .anel").get_attribute("class")
        self.assertIn("falhou", classes)
        self.assertNotIn("concluido", classes)
        self.capturar(pagina, "lote-sem-nenhum-pdf")
        self.sem_problemas(pagina)

    def test_lote_de_um_processo_concorda(self):
        pagina = self.abrir(secao="processos")
        pagina.click("#area-soltar button:has-text('Colar lista')")
        pagina.fill(".folha textarea", "5004417-09.2024.8.21.0001")
        pagina.click(".folha button:has-text('Ler a lista')")
        pagina.wait_for_selector(".revisao")
        pagina.click("#botao-baixar")
        pagina.wait_for_selector(".lote-concluido", timeout=20000)
        self.assertIn("1 baixado", pagina.locator(".andamento").inner_text())
        pagina.click(".andamento button:has-text('Novo lote')")
        pagina.wait_for_selector("#ultimos-lotes .linha")
        lotes = pagina.locator("#ultimos-lotes").inner_text()
        self.assertIn("1 de 1 processo baixado", lotes)
        self.assertNotIn("processo baixados", lotes)
        self.ir(pagina, "inicio")
        self.assertNotIn("processo baixados", pagina.locator("#pagina").inner_text())
        self.sem_problemas(pagina)

    def test_tentar_de_novo_no_mesmo_lote(self):
        """'Tentar de novo' refaz os que falharam NO MESMO lote (a mesma pasta,
        cujo relatório o programa completa), mesmo quando o lote veio da Pauta
        e o rascunho da tela Processos guarda o nome de outra relação."""
        pagina = self.abrir(secao="processos")
        pagina.click("#area-soltar button:has-text('Colar lista')")
        pagina.fill(".folha textarea", "5004417-09.2024.8.21.0001")
        pagina.click(".folha button:has-text('Ler a lista')")
        pagina.wait_for_selector(".revisao")
        self.ir(pagina, "pauta")
        pagina.click("#acao-baixar-periodo")
        pagina.click(".folha button:has-text('Baixar')")
        pagina.wait_for_selector(".folha-pergunta", timeout=15000)
        pagina.fill("#campo-codigo", "482193")
        pagina.wait_for_selector(".folha-pergunta", state="detached")
        self.ir(pagina, "processos")
        pagina.wait_for_selector(".lote-concluido", timeout=30000)
        pedido = self.chamadas(pagina, "POST /api/pauta/baixar-autos")[0]
        lote = f"Pauta {pedido['de']} a {pedido['ate']}"
        botao_refazer = pagina.locator(".andamento button:has-text('Tentar de novo')")
        self.assertEqual(botao_refazer.count(), 1)
        botao_refazer.click()
        pagina.wait_for_function(
            "() => Helestron.demo.chamadas.filter(c => c.rota === 'POST /api/download/iniciar').length === 1")
        refazer = self.chamadas(pagina, "POST /api/download/iniciar")[0]
        self.assertEqual(refazer["nome_lote"], lote)
        self.assertEqual(len(refazer["processos"]), 1)
        self.assertIs(refazer["opcoes"]["rebaixar"], False)
        pagina.wait_for_selector(".lote-concluido", timeout=20000)
        self.sem_problemas(pagina)

    # ------------------------------------------------------------- 2º grau
    def colar_relacao(self, pagina, texto):
        pagina.click("#area-soltar button:has-text('Colar lista')")
        pagina.fill(".folha textarea", texto)
        pagina.click(".folha button:has-text('Ler a lista')")
        pagina.wait_for_selector(".revisao")

    def graus_da_revisao(self, pagina) -> dict:
        """{número: o grau que o selo da linha mostra}, na revisão."""
        return pagina.evaluate("""() => Object.fromEntries([...document.querySelectorAll('.revisao tbody tr')]
            .map(tr => [tr.querySelector('.numero').textContent, tr.querySelector('.selo-grau').textContent]))""")

    def entrar_com_codigo(self, pagina):
        pagina.wait_for_selector(".folha-pergunta", timeout=15000)
        pagina.fill("#campo-codigo", "482193")
        pagina.wait_for_selector(".folha-pergunta", state="detached")

    def test_grau_do_lote_e_coluna_grau(self):
        """Opções do lote › Grau: o segmentado (com o grau dos Ajustes) muda o
        selo das linhas cujo número não diz o grau; o HC (órgão 0000) e os
        embargos (/50000) ficam no 2º grau. O pedido leva o grau, e o
        andamento mostra o selo do 2º grau."""
        pagina = self.abrir(secao="processos")
        self.colar_relacao(pagina, f"{APELACAO}\n{HC}\n{EMBARGOS}")
        self.assertEqual(pagina.locator(".revisao tbody tr").count(), 3)    # a coluna Grau é coluna
        self.assertIn("Grau", pagina.evaluate("document.querySelector('.revisao thead').textContent"))
        self.assertEqual(self.graus_da_revisao(pagina),
                         {APELACAO: "1º grau", HC: "2º grau", EMBARGOS: "2º grau"})
        for numero in (HC, EMBARGOS):
            selo = pagina.locator(f".revisao tbody tr:has-text('{numero}') .selo-grau")
            self.assertEqual(selo.get_attribute("title"), "Só existe no 2º grau")
        self.assertEqual(pagina.locator("#grau-lote [role='radio']").count(), 2)
        self.assertEqual(pagina.locator("#grau-lote [aria-checked='true']").inner_text(), "1º grau")
        self.assertIn("TJAL · e-SAJ (2º grau)", pagina.locator(".revisao").inner_text())   # pílula do 2º grau
        pagina.click("#grau-lote button:has-text('2º grau')")
        self.assertEqual(self.graus_da_revisao(pagina),
                         {APELACAO: "2º grau", HC: "2º grau", EMBARGOS: "2º grau"})
        pagina.click("#grau-lote button:has-text('1º grau')")
        self.assertEqual(self.graus_da_revisao(pagina)[APELACAO], "1º grau")
        pagina.click("#grau-lote button:has-text('2º grau')")
        self.numeros_inteiros(pagina, "revisão do 2º grau")
        self.sem_rolagem_horizontal(pagina, "revisão do 2º grau")
        self.capturar(pagina, "grau-revisao")
        pagina.click("#botao-baixar")
        self.entrar_com_codigo(pagina)
        pagina.wait_for_selector(".lote-concluido", timeout=20000)
        iniciou = self.chamadas(pagina, "POST /api/download/iniciar")[0]
        self.assertEqual(iniciou["opcoes"]["grau"], "2g")
        self.assertEqual(iniciou["processos"], [APELACAO, HC, EMBARGOS])
        for numero in (APELACAO, HC, EMBARGOS):
            with self.subTest(numero=numero):
                selo = pagina.locator(f".itens-lote tr[data-numero='{numero}'] .selo-contorno")
                self.assertEqual(selo.inner_text(), "TJAL · 2º grau")
        self.numeros_inteiros(pagina, "andamento do 2º grau")
        self.capturar(pagina, "grau-andamento")
        self.sem_problemas(pagina)

    def test_grau_cabe_nas_janelas_pequenas(self):
        """A coluna Grau, o segmentado e os dois Testar cabem em 1024 px, em
        1100x720 e em 1366x768 a 125 %, sem cortar o número dos embargos."""
        for nome, largura, altura, escala in self.TAMANHOS_PEQUENOS:
            with self.subTest(tamanho=nome):
                pagina = self.abrir(largura, altura, escala, secao="processos")
                self.colar_relacao(pagina, f"{APELACAO}\n{HC}\n{EMBARGOS}")
                pagina.click("#grau-lote button:has-text('2º grau')")
                self.numeros_inteiros(pagina, "revisão")
                self.sem_rolagem_horizontal(pagina, "revisão")
                self.capturar(pagina, f"{nome}-grau-revisao")
                self.ir(pagina, "ajustes")
                pagina.locator("[data-portal='esaj:TJAL'] button:has-text('Testar 2º grau')").wait_for()
                self.sem_rolagem_horizontal(pagina, "ajustes")
                self.capturar(pagina, f"{nome}-grau-acessos")
                self.sem_problemas(pagina)

    def test_lote_do_primeiro_grau_com_o_hc(self):
        """Lote do 1º grau: a apelação no 1º grau (selo como sempre); o HC, no 2º."""
        pagina = self.abrir(secao="processos")
        self.colar_relacao(pagina, f"{APELACAO}\n{HC}")
        pagina.click("#botao-baixar")
        self.entrar_com_codigo(pagina)
        pagina.wait_for_selector(".lote-concluido", timeout=20000)
        self.assertEqual(self.chamadas(pagina, "POST /api/download/iniciar")[0]["opcoes"]["grau"], "1g")
        self.assertEqual(pagina.locator(f".itens-lote tr[data-numero='{APELACAO}'] .selo-contorno").inner_text(), "TJAL")
        self.assertEqual(pagina.locator(f".itens-lote tr[data-numero='{HC}'] .selo-contorno").inner_text(),
                         "TJAL · 2º grau")
        self.sem_problemas(pagina)

    def test_testar_o_primeiro_e_o_segundo_grau(self):
        """Ajustes › Acessos: a linha do e-SAJ do TJAL testa os dois graus (o
        mesmo acesso); o eProc do 2º grau tem linha e acesso próprios. Ajustes ›
        Download: Grau dos processos, que vira o grau do próximo lote."""
        pagina = self.abrir(secao="ajustes")
        esaj = pagina.locator("[data-portal='esaj:TJAL']")
        esaj.wait_for()
        self.assertEqual(esaj.locator("button:has-text('Testar')").count(), 2)
        # sem senha (e entrando com senha): sem Testar, como antes
        self.assertEqual(pagina.locator("[data-portal='eproc:TJAL'] button:has-text('Testar')").count(), 0)
        segundo = pagina.locator("[data-portal='eproc2g:TJAL']")
        self.assertIn("eProc (2º grau) · TJAL", segundo.inner_text())
        esaj.locator("button:has-text('Testar 2º grau')").click()
        pagina.wait_for_selector("[data-portal='esaj:TJAL'] .resultado-teste.ok", timeout=10000)
        self.assertIn("2º grau: Acesso confirmado", esaj.inner_text())
        esaj.locator("button:has-text('Testar 1º grau')").click()
        pagina.wait_for_function(
            "() => document.querySelectorAll(\"[data-portal='esaj:TJAL'] .resultado-teste.ok\").length === 2",
            timeout=10000)
        self.assertIn("1º grau: Acesso confirmado", esaj.inner_text())
        self.assertEqual(pagina.locator(".folha-fundo").count(), 0, "o Testar abriu também a folha da senha")
        self.assertEqual(self.chamadas(pagina, "POST /api/acessos/testar"),
                         [{"tribunal": "TJAL", "sistema": "esaj", "grau": "2g"},
                          {"tribunal": "TJAL", "sistema": "esaj"}])     # o 1º grau, como antes
        titulos = pagina.evaluate(
            "[...Helestron.loja.tarefas.values()].filter(t => t.tipo === 'teste_login').map(t => t.titulo)")
        self.assertEqual(titulos, ["Testar o acesso ao TJAL · e-SAJ (2º grau)", "Testar o acesso ao TJAL · e-SAJ"])
        self.capturar(pagina, "ajustes-acessos-dois-graus")
        # O eProc do 2º grau: acesso próprio, com o Testar dele.
        segundo.locator("button:has-text('Cadastrar')").click()
        pagina.wait_for_selector(".folha:has-text('Acesso ao eProc (2º grau) · TJAL')")
        self.assertEqual(pagina.locator("label[for='acesso-usuario']").inner_text(), "Usuário (CPF ou sigla)")
        pagina.fill("#acesso-usuario", "AL123")
        pagina.fill("#acesso-senha", "senha do 2º grau")
        pagina.click(".folha button:has-text('Salvar')")
        pagina.wait_for_selector(".folha-fundo", state="detached")
        self.assertEqual(self.chamadas(pagina, "POST /api/acessos")[-1]["portal"], "eproc2g:TJAL")
        segundo = pagina.locator("[data-portal='eproc2g:TJAL']:has-text('Senha guardada')")
        segundo.wait_for()
        self.assertEqual(segundo.locator("button:has-text('Testar')").count(), 1)
        segundo.locator("button:has-text('Testar')").click()
        pagina.wait_for_selector("[data-portal='eproc2g:TJAL'] .resultado-teste.ok", timeout=10000)
        self.assertEqual(self.chamadas(pagina, "POST /api/acessos/testar")[-1],
                         {"tribunal": "TJAL", "sistema": "eproc", "grau": "2g"})
        # "Adicionar acesso" oferece o eProc do 2º grau onde o Helestron o baixa
        pagina.click("#adicionar-acesso")
        pagina.wait_for_selector("#acesso-portal")
        opcoes = pagina.locator("#acesso-portal option").evaluate_all("os => os.map(o => o.value)")
        for valor in ("esaj:TJAL", "eproc:TJAL", "eproc2g:TJAL", "eproc2g:TRF4"):
            self.assertIn(valor, opcoes)
        self.assertNotIn("eproc2g:TJSP", opcoes)
        self.assertNotIn("esaj2g:TJAL", " ".join(opcoes))
        pagina.click(".folha button:has-text('Cancelar')")
        pagina.wait_for_selector(".folha-fundo", state="detached")
        self.assertIn("O acesso ao e-SAJ vale para o 1º e o 2º grau", pagina.locator("#pagina").inner_text())
        # Ajustes › Download › Grau dos processos: o padrão do próximo lote
        pagina.click(".ajustes-indice a[data-grupo='download']")
        pagina.wait_for_selector("#cfg-download-grau")
        self.assertEqual(pagina.locator("#cfg-download-grau [role='radio']").count(), 2)
        pagina.click("#cfg-download-grau button:has-text('2º grau')")
        pagina.wait_for_function(
            "() => Helestron.demo.chamadas.some(c => c.rota === 'POST /api/config' && c.corpo.chave === 'grau')")
        self.assertEqual(self.chamadas(pagina, "POST /api/config")[-1],
                         {"secao": "download", "chave": "grau", "valor": "2g"})
        self.ir(pagina, "processos")
        self.colar_relacao(pagina, APELACAO)
        self.assertEqual(pagina.locator("#grau-lote [aria-checked='true']").inner_text(), "2º grau")
        self.assertEqual(self.graus_da_revisao(pagina), {APELACAO: "2º grau"})
        self.sem_problemas(pagina)

    def test_tentar_de_novo_continua_no_grau_do_lote(self):
        """O "Tentar de novo" de um lote do 2º grau refaz no 2º grau, mesmo
        depois de recarregar a página (o rascunho das opções some) com os
        Ajustes no 1º grau."""
        pagina = self.abrir(extra="&lote=falhas", secao="processos")
        self.colar_relacao(pagina, APELACAO)
        pagina.click("#grau-lote button:has-text('2º grau')")
        pagina.click("#botao-baixar")
        self.entrar_com_codigo(pagina)
        pagina.wait_for_selector(".lote-concluido", timeout=20000)
        self.assertEqual(pagina.evaluate("Helestron.app.valorConfig('download', 'grau', '')"), "1g")
        pagina.evaluate("() => { Helestron.loja.processos.opcoes = null; }")   # a página recarregada
        pagina.click(".andamento button:has-text('Tentar de novo')")
        pagina.wait_for_function(
            "() => Helestron.demo.chamadas.filter(c => c.rota === 'POST /api/download/iniciar').length === 2")
        refazer = self.chamadas(pagina, "POST /api/download/iniciar")[1]
        self.assertEqual(refazer["opcoes"]["grau"], "2g")
        self.assertEqual(refazer["processos"], [APELACAO])
        self.assertIs(refazer["opcoes"]["rebaixar"], False)
        self.sem_problemas(pagina)

    def test_lote_da_pauta_refeito_continua_no_primeiro_grau(self):
        """O lote da Pauta é do 1º grau: refeito pelo "Tentar de novo" com o
        rascunho da tela Processos no 2º grau, continua no 1º."""
        pagina = self.abrir(secao="processos")
        self.colar_relacao(pagina, APELACAO)
        pagina.click("#grau-lote button:has-text('2º grau')")          # o rascunho no 2º grau
        self.ir(pagina, "pauta")
        pagina.click("#acao-baixar-periodo")
        pagina.click(".folha button:has-text('Baixar')")
        self.entrar_com_codigo(pagina)
        self.ir(pagina, "processos")
        pagina.wait_for_selector(".lote-concluido", timeout=30000)
        self.assertEqual(pagina.evaluate("Helestron.loja.processos.opcoes.grau"), "2g")
        pagina.locator(".andamento button:has-text('Tentar de novo')").click()
        pagina.wait_for_function(
            "() => Helestron.demo.chamadas.filter(c => c.rota === 'POST /api/download/iniciar').length === 1")
        self.assertEqual(self.chamadas(pagina, "POST /api/download/iniciar")[0]["opcoes"]["grau"], "1g")
        self.sem_problemas(pagina)

    def test_numero_com_o_recurso_interno_do_segundo_grau(self):
        """O dependente de 5 dígitos (/50000) não some nem encolhe: na máscara,
        no número tirado do nome do arquivo (com o sufixo (2G)) e no campo da
        audiência."""
        pagina = self.abrir(secao="audiencias")
        valores = pagina.evaluate("""() => [Helestron.cnj.formatar('0706265-50.2017.8.02.0001/50000'),
            Helestron.cnj.mascarar('07062655020178020001/50000'),
            Helestron.cnj.doNome('0706265-50.2017.8.02.0001-50000 (2G).pdf'),
            Helestron.cnj.doNome('0706265-50.2017.8.02.0001-50000 (2G)_capa.json'),
            Helestron.cnj.formatar('0706265-50.2017.8.02.0001 / 50001'),
            Helestron.cnj.doNome('0700001-93.2024.8.02.0058 (2G).pdf'),
            Helestron.cnj.formatar('0700001-93.2024.8.02.0058/0003'),
            Helestron.cnj.formatar('0700001-93.2024.8.02.0058/123456')]""")
        self.assertEqual(valores, [EMBARGOS, EMBARGOS, EMBARGOS, EMBARGOS,
                                   "0706265-50.2017.8.02.0001/50001", APELACAO,
                                   APELACAO + "/03", APELACAO])
        pagina.fill("#processo-audiencia", EMBARGOS)
        self.assertEqual(pagina.input_value("#processo-audiencia"), EMBARGOS)
        pagina.wait_for_function("() => /dependente 50000/.test(document.querySelector('#pagina').innerText)")
        self.numeros_inteiros(pagina, "audiências")
        self.sem_problemas(pagina)

    def test_microfone_pelo_nome(self):
        nome = "Microfone de mesa USB (Jabra Speak 510)"
        pagina = self.abrir(extra="&microfone=" + quote(nome), secao="audiencias")
        pagina.wait_for_function("() => document.querySelector('#microfone').options.length > 1")
        self.assertEqual(pagina.locator("#microfone").input_value(), nome)
        pagina.click("#testar-microfone")
        pagina.wait_for_function("() => document.querySelectorAll('.medidor span.aceso').length > 0")
        self.assertEqual(self.chamadas(pagina, "POST /api/transcricao/microfone/teste"), [{"dispositivo": nome}])
        pagina.click("#testar-microfone")
        outro = "Matriz de microfones (Intel® Smart Sound)"
        pagina.select_option("#microfone", outro)
        pagina.wait_for_function("() => Helestron.demo.chamadas.some(c => c.rota === 'POST /api/config')")
        self.assertEqual(self.chamadas(pagina, "POST /api/config")[-1],
                         {"secao": "transcricao", "chave": "dispositivo", "valor": outro})
        pagina.fill("#processo-audiencia", "07002311520248020001")
        pagina.click("#botao-gravar")
        pagina.wait_for_selector(".ao-vivo")
        self.assertEqual(self.chamadas(pagina, "POST /api/transcricao/iniciar")[0]["dispositivo"], outro)
        self.sem_problemas(pagina)

    def test_microfone_que_sumiu_nao_vira_o_padrao_em_silencio(self):
        pagina = self.abrir(extra="&microfone=" + quote("Fone que foi desligado"), secao="audiencias")
        pagina.wait_for_function("() => document.querySelector('#microfone').options.length > 1")
        self.assertEqual(pagina.locator("#microfone").input_value(), "Fone que foi desligado")
        self.assertIn("não foi encontrado", pagina.locator(".medidor-caixa").inner_text())
        pagina.fill("#processo-audiencia", "07002311520248020001")
        pagina.click("#botao-gravar")
        folha = pagina.locator(".folha:has-text('A gravação não começou')")
        folha.wait_for()
        self.assertIn("O microfone “Fone que foi desligado” não foi encontrado. Escolha outro em Audiências "
                      "ou Ajustes › Transcrição.", folha.inner_text())
        self.assertNotIn("Algo deu errado", folha.inner_text())
        self.sem_problemas(pagina)
        # Configuração antiga, pelo número: vira o nome do mesmo aparelho.
        pagina = self.abrir(extra="&microfone=3", secao="audiencias")
        pagina.wait_for_function("() => document.querySelector('#microfone').options.length > 1")
        self.assertEqual(pagina.locator("#microfone").input_value(), "Microfone de mesa USB (Jabra Speak 510)")
        pagina.wait_for_function("() => Helestron.demo.chamadas.some(c => c.rota === 'POST /api/config')")
        self.assertEqual(self.chamadas(pagina, "POST /api/config")[-1]["valor"], "Microfone de mesa USB (Jabra Speak 510)")
        # Ajustes › Transcrição: a mesma escolha, pelo nome.
        self.ir(pagina, "ajustes")
        pagina.click(".ajustes-indice a[data-grupo='transcricao']")
        campo = pagina.locator("#cfg-transcricao-dispositivo")
        campo.wait_for()
        pagina.wait_for_function("() => document.querySelector('#cfg-transcricao-dispositivo').options.length > 1")
        self.assertEqual(campo.evaluate("e => e.tagName"), "SELECT")
        self.assertEqual(campo.input_value(), "Microfone de mesa USB (Jabra Speak 510)")
        self.sem_problemas(pagina)

    def test_compartilhar_copia_na_hora_do_clique(self):
        pagina = self.abrir(secao="compartilhar", permissoes=["clipboard-read", "clipboard-write"])
        pagina.evaluate("""() => { window.__ordem = [];
            const escrever = navigator.clipboard.writeText.bind(navigator.clipboard);
            navigator.clipboard.writeText = (t) => { window.__ordem.push('copia'); return escrever(t); };
            const responder = Helestron.demo.responder;
            Helestron.demo.responder = (rota, pedido) => { window.__ordem.push(rota); return responder(rota, pedido); }; }""")
        pagina.click("#destino-cowork button:has-text('Abrir no Cowork')")
        pagina.wait_for_selector(".folha:has-text('cole o pedido inicial')")
        copiado = pagina.evaluate("navigator.clipboard.readText()")
        self.assertTrue(copiado.startswith("Pasta do acervo: C:\\Users\\"), copiado)
        self.assertIn("Leia primeiro o CLAUDE.md", copiado)
        ordem = pagina.evaluate("window.__ordem")
        self.assertLess(ordem.index("copia"), ordem.index("POST /api/compartilhar/cowork"), ordem)
        pagina.click(".folha button:has-text('OK')")
        pagina.wait_for_selector(".folha-fundo", state="detached")
        pagina.evaluate("window.__ordem = []")
        pagina.click("#destino-chatgpt-work button:has-text('Abrir no ChatGPT Work')")
        pagina.wait_for_selector(".folha:has-text('cole o caminho do acervo')")
        self.assertEqual(pagina.evaluate("navigator.clipboard.readText()"),
                         "C:\\Users\\camila.albuquerque\\Documents\\Helestron\\Acervo")
        ordem = pagina.evaluate("window.__ordem")
        self.assertLess(ordem.index("copia"), ordem.index("POST /api/compartilhar/chatgpt-work"), ordem)
        pagina.click(".folha button:has-text('OK')")
        pagina.wait_for_selector(".folha-fundo", state="detached")
        # Sem área de transferência: a folha mostra o texto para copiar à mão.
        pagina.evaluate("""() => { navigator.clipboard.writeText = () => Promise.reject(new Error('negado'));
            document.execCommand = () => false; }""")
        pagina.click("#destino-cowork button:has-text('Abrir no Cowork')")
        caixa = pagina.locator("#texto-para-copiar")
        caixa.wait_for()
        self.assertTrue(caixa.input_value().startswith("Pasta do acervo:"))
        self.assertIn("Não consegui pôr o pedido inicial na área de transferência", pagina.locator(".folha").inner_text())
        self.capturar(pagina, "compartilhar-copia-a-mao")
        self.sem_problemas(pagina)

    def test_claude_code_ausente_abre_a_pagina_oficial(self):
        pagina = self.abrir(extra="&claude_code=ausente", secao="compartilhar")
        pagina.click("#destino-claude-code button:has-text('Abrir no Claude Code')")
        folha = pagina.locator(".folha:has-text('Claude Code')")
        folha.wait_for()
        self.assertIn("Abri no navegador a página oficial", folha.inner_text())
        pagina.click(".folha button:has-text('OK')")
        pagina.wait_for_selector(".folha-fundo", state="detached")
        # O programa não conseguiu abrir o navegador: a folha oferece o botão.
        pagina.evaluate("""() => { const responder = Helestron.demo.responder;
            Helestron.demo.responder = (rota, pedido) => rota === 'POST /api/compartilhar/claude-code'
              ? Promise.resolve({ abriu: false, instalado: false, pagina_aberta: false, url: 'https://docs.claude.com/pt-BR/docs/claude-code/overview',
                  mensagem: 'O Claude Code não está instalado neste computador. A página oficial explica como instalá-lo (sem administrador): https://docs.claude.com/pt-BR/docs/claude-code/overview' })
              : responder(rota, pedido); }""")
        pagina.click("#destino-claude-code button:has-text('Abrir no Claude Code')")
        pagina.click(".folha button:has-text('Abrir a página')")
        pagina.wait_for_function("() => Helestron.demo.chamadas.some(c => c.rota === 'POST /api/abrir')")
        self.assertEqual(self.chamadas(pagina, "POST /api/abrir")[-1],
                         {"tipo": "url", "alvo": "https://docs.claude.com/pt-BR/docs/claude-code/overview"})
        self.sem_problemas(pagina)

    def test_sigilo_que_a_pauta_conhece(self):
        """O número de um processo que a pauta marca como sigiloso liga o
        segredo de justiça sozinho, com o motivo; desligado à mão, o programa
        liga de novo ao começar e a tela mostra por quê."""
        pagina = self.abrir(secao="audiencias")
        pagina.fill("#processo-audiencia", PROCESSO_SIGILOSO.replace("-", "").replace(".", ""))
        pagina.wait_for_function("() => document.querySelector('#sigilo-audiencia').checked")
        self.assertIn("A pauta de audiências indica", pagina.locator("#motivo-sigilo").inner_text())
        pagina.click("#sigilo-audiencia")
        self.assertFalse(pagina.locator("#sigilo-audiencia").is_checked())
        pagina.click("#botao-gravar")
        pagina.wait_for_selector(".ao-vivo")
        self.assertIs(self.chamadas(pagina, "POST /api/transcricao/iniciar")[0]["sigiloso"], False)
        self.assertIn("Segredo de justiça", pagina.locator(".ao-vivo-sub").inner_text())
        self.assertIn("A pauta de audiências indica", pagina.locator("#motivo-sigilo-ao-vivo").inner_text())
        self.capturar(pagina, "ao-vivo-sigilo-da-pauta")
        self.sem_problemas(pagina)
        # A gravação (modo arquivo): o número sigiloso liga o interruptor, e o tipo vai junto.
        pagina = self.abrir(secao="audiencias")
        pagina.click("#modo-audiencia [data-valor='arquivo']")
        pagina.click("#escolher-gravacao")
        pagina.wait_for_selector("#arquivo-escolhido:not([hidden])")
        pagina.fill("#processo-gravacao", PROCESSO_SIGILOSO.replace("-", "").replace(".", ""))
        pagina.wait_for_function("() => document.querySelector('#sigilo-gravacao').checked")
        pagina.select_option("#tipo-gravacao", "Conciliação")
        pagina.click("#sigilo-gravacao")            # desligado à mão: o programa liga de novo
        pagina.click("#botao-transcrever")
        pagina.wait_for_selector("#motivo-sigilo-gravacao")
        pedido = self.chamadas(pagina, "POST /api/transcricao/gravacao")[0]
        self.assertEqual(pedido["tipo"], "Conciliação")
        self.assertIs(pedido["sigiloso"], False)
        self.assertIn("A pauta de audiências indica", pagina.locator("#motivo-sigilo-gravacao").inner_text())
        self.sem_problemas(pagina)

    def test_gravacao_enviada_pela_pagina_leva_o_nome_e_a_data(self):
        """Nos modos Edge e navegador (sem o diálogo do Windows), a gravação vai
        por envio e chega ao programa como um temporário de hoje: o nome do
        arquivo e a data dele (File.lastModified, em ISO 8601) vão junto, para
        a ficha do documento."""
        pasta = Path(tempfile.mkdtemp(prefix="helestron-gravacao-"))
        self.addCleanup(shutil.rmtree, pasta, True)
        audio = pasta / "Audiência sala 2.wav"
        audio.write_bytes(b"RIFF....WAVEfmt ")
        quando = datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc)
        os.utime(audio, (quando.timestamp(), quando.timestamp()))
        pagina = self.abrir(secao="audiencias", extra="&sem_dialogo=1")
        pagina.click("#modo-audiencia [data-valor='arquivo']")
        with pagina.expect_file_chooser() as escolha:
            pagina.click("#escolher-gravacao")
        escolha.value.set_files(str(audio))
        pagina.wait_for_selector("#arquivo-escolhido:not([hidden])")
        pagina.fill("#processo-gravacao", "07002311520248020001")
        pagina.click("#botao-transcrever")
        pagina.wait_for_function(
            "() => Helestron.demo.chamadas.some(c => c.rota === 'POST /api/transcricao/gravacao')")
        pedido = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/transcricao/gravacao')")
        self.assertTrue(pedido["multipart"])
        corpo = pedido["corpo"]
        self.assertEqual(corpo["arquivo"]["nome"], audio.name)
        self.assertEqual(corpo["nome_original"], audio.name)
        self.assertEqual(corpo["data_arquivo"], "2026-09-15T13:30:00.000Z")
        self.assertEqual(corpo["processo"], "0700231-15.2024.8.02.0001")
        self.sem_problemas(pagina)

    # ------------------------------------------------ atenção à pergunta
    SEM_FOCO = "() => { document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }"
    COM_FOCO = "() => { document.hasFocus = () => true; window.dispatchEvent(new Event('focus')); }"

    def pedir_codigo(self, pagina):
        pagina.click("#area-soltar button:has-text('Colar lista')")
        pagina.fill(".folha textarea", "0700231-15.2024.8.02.0001\n1004512-63.2024.8.26.0100")
        pagina.click(".folha button:has-text('Ler a lista')")
        pagina.wait_for_selector(".revisao")
        pagina.click("#botao-baixar")

    def test_pergunta_pisca_o_titulo_no_edge_e_no_navegador(self):
        """Fora da janela do aplicativo (Edge ou navegador), a página não
        alcança a janela: com a página sem foco, o título da aba alterna
        enquanto a pergunta espera, volta ao normal com o foco e para de vez
        quando a pergunta é respondida."""
        for modo in ("edge", "navegador"):
            with self.subTest(modo=modo):
                pagina = self.abrir(secao="processos", extra=f"&modo={modo}")
                self.assertEqual(pagina.title(), "Processos — Helestron")
                self.pedir_codigo(pagina)
                pagina.evaluate(self.SEM_FOCO)      # o usuário foi para outro programa
                pagina.wait_for_selector(".folha-pergunta")
                pagina.wait_for_function("() => document.title === 'Código pedido — Helestron'",
                                         timeout=5000)
                pagina.wait_for_function("() => document.title === 'Processos — Helestron'",
                                         timeout=5000)
                pagina.wait_for_function("() => document.title === 'Código pedido — Helestron'",
                                         timeout=5000)
                pagina.evaluate(self.COM_FOCO)      # voltou: o título normal, sem alternar
                self.assertEqual(pagina.title(), "Processos — Helestron")
                pagina.wait_for_timeout(2300)
                self.assertEqual(pagina.title(), "Processos — Helestron")
                pagina.evaluate(self.SEM_FOCO)      # saiu de novo, sem responder
                pagina.wait_for_function("() => document.title === 'Código pedido — Helestron'",
                                         timeout=5000)
                pagina.fill("#campo-codigo", "482193")      # respondeu: para de vez
                pagina.wait_for_selector(".folha-pergunta", state="detached")
                pagina.wait_for_function("() => document.title === 'Processos — Helestron'",
                                         timeout=5000)
                pagina.wait_for_timeout(2300)
                self.assertEqual(pagina.title(), "Processos — Helestron")
                self.assertIsNone(pagina.evaluate("Helestron.atencao.relogio"))
                self.sem_problemas(pagina)

    def test_pergunta_com_a_pagina_em_foco_ou_na_janela_do_aplicativo_nao_pisca(self):
        # Na janela do aplicativo, quem chama a atenção é o lado nativo (a
        # janela pisca na barra de tarefas); com a página em foco, ninguém
        # precisa ser chamado.
        for extra, foco in (("", False), ("&modo=edge", True)):
            with self.subTest(extra=extra, foco=foco):
                pagina = self.abrir(secao="processos", extra=extra)
                self.pedir_codigo(pagina)
                if not foco:
                    pagina.evaluate(self.SEM_FOCO)
                pagina.wait_for_selector(".folha-pergunta")
                pagina.wait_for_timeout(2300)
                self.assertEqual(pagina.title(), "Processos — Helestron")
                self.assertIsNone(pagina.evaluate("Helestron.atencao.relogio"))
                self.sem_problemas(pagina)

    # ------------------------------------------------ pauta: fontes só com a pessoa
    def test_fonte_que_exige_a_pessoa_nao_aparece_como_monitorada(self):
        """Com o certificado digital (ou a entrada manual, ou a senha não
        guardada), o monitoramento não entra sozinho: a fonte não leva o selo
        “Monitorada”, e a tela diz por quê."""
        pagina = self.abrir(secao="ajustes", extra="&presenca=certificado")
        pagina.click(".ajustes-indice a[data-grupo='pauta']")
        pagina.wait_for_selector(".grupo[aria-label='Fontes da pauta'] .linha")
        lista = pagina.locator(".grupo[aria-label='Fontes da pauta']").inner_text()
        self.assertNotIn("Monitorada", lista)
        self.assertIn("Só com você", lista)
        self.assertIn("Fica fora do monitoramento automático: a entrada no portal é pelo "
                      "certificado digital", lista)
        self.capturar(pagina, "ajustes-pauta-fonte-so-com-voce")
        self.ir(pagina, "pauta")
        pagina.wait_for_selector("#monitor-sem-fontes")
        texto = pagina.locator("#monitor-sem-fontes").inner_text()
        self.assertIn("O monitoramento não entra sozinho no portal: a entrada no portal é pelo "
                      "certificado digital (e-SAJ TJAL e eProc TJAL).", texto)
        cartao = pagina.locator(".cartao:has-text('Conferir sozinho')").inner_text()
        self.assertIn("(só com você)", cartao)
        pagina.locator("#monitor-sem-fontes").scroll_into_view_if_needed()
        self.capturar(pagina, "pauta-monitor-so-com-voce")
        self.sem_problemas(pagina)
        # Sem a variação, as fontes da demonstração são monitoradas.
        pagina = self.abrir(secao="pauta")
        self.assertEqual(pagina.locator("#monitor-sem-fontes").count(), 0)
        self.sem_problemas(pagina)

    def test_semana_conta_os_mesmos_dias_da_visao_semana(self):
        """“Nos próximos 7 dias” (Pauta e Início) conta de hoje a hoje + 6 - os
        dias da visão Semana -, sem as canceladas e as redesignadas."""
        pagina = self.abrir(secao="pauta")
        pagina.wait_for_selector("#lista-pauta .audiencia")
        na_lista = pagina.evaluate("""() => [...document.querySelectorAll('#lista-pauta .audiencia')]
            .map(a => a.querySelector('.audiencia-lado .pilula').textContent.trim())
            .filter(situacao => !['Cancelada', 'Redesignada'].includes(situacao)).length""")
        chip = int(pagina.locator("#chip-semana strong").inner_text())
        self.assertEqual(chip, na_lista)
        self.ir(pagina, "inicio")
        cartao = pagina.locator("text=nos próximos 7 dias").first.locator("xpath=..").inner_text()
        self.assertIn(f"{chip} nos próximos 7 dias", cartao.replace("\n", " "))
        self.sem_problemas(pagina)

    # ------------------------------------------------ revisão 2 da interface
    TAMANHOS_PEQUENOS = (("1024x768", 1024, 768, 1), ("1100x720", 1100, 720, 1),
                         ("1366x768-zoom125", 1093, 614, 1.25))

    def segurar_rota(self, pagina, rota):
        """A rota da demonstração só responde quando window.__liberar() for chamada."""
        pagina.evaluate("""r => { const pronto = new Promise(ok => { window.__liberar = ok; });
            const responder = Helestron.demo.responder;
            Helestron.demo.responder = (rota, pedido) => rota === r
              ? pronto.then(() => responder(rota, pedido)) : responder(rota, pedido); }""", rota)

    def responder_com(self, pagina, rota, valor):
        pagina.evaluate("""([r, v]) => { const responder = Helestron.demo.responder;
            Helestron.demo.responder = (rota, pedido) => rota === r
              ? Promise.resolve(JSON.parse(JSON.stringify(v))) : responder(rota, pedido); }""", [rota, valor])

    def test_gravar_espera_a_lista_de_microfones(self):
        """Com o número já preenchido (botão “Transcrever” da Pauta ou do
        Início), Gravar e Ctrl+Enter ficavam ativos antes de a lista de
        microfones chegar: o seletor tinha só “Carregando…” (""), e o "" é a
        escolha explícita do padrão do Windows (C2) - a audiência ia inteira
        pelo microfone errado, sem aviso."""
        nome = "Microfone de mesa USB (Jabra Speak 510)"
        pagina = self.abrir(extra="&microfone=" + quote(nome), secao="ajuda")
        self.segurar_rota(pagina, "GET /api/transcricao/microfones")
        pagina.evaluate("location.hash = '#/audiencias?processo=0700231-15.2024.8.02.0001&tipo=Una'")
        pagina.wait_for_selector("#botao-gravar")
        pagina.wait_for_function("() => document.querySelector('#ajuda-processo').textContent.includes('Número válido')")
        self.assertIn("Carregando", pagina.locator("#microfone").inner_text())
        self.assertTrue(pagina.locator("#botao-gravar").is_disabled())
        self.assertTrue(pagina.locator("#testar-microfone").is_disabled())
        pagina.keyboard.press("Control+Enter")
        pagina.wait_for_timeout(400)
        self.assertEqual(self.chamadas(pagina, "POST /api/transcricao/iniciar"), [])
        self.assertEqual(self.chamadas(pagina, "POST /api/transcricao/microfone/teste"), [])
        pagina.evaluate("window.__liberar()")
        pagina.wait_for_function("() => !document.querySelector('#botao-gravar').disabled")
        self.assertFalse(pagina.locator("#testar-microfone").is_disabled())
        self.assertEqual(pagina.locator("#microfone").input_value(), nome)
        pagina.keyboard.press("Control+Enter")
        pagina.wait_for_selector(".ao-vivo")
        self.assertEqual(self.chamadas(pagina, "POST /api/transcricao/iniciar")[0]["dispositivo"], nome)
        self.sem_problemas(pagina)

    def test_microfone_com_a_mesma_regra_em_audiencias_e_ajustes(self):
        """Configuração antiga com um número que não existe mais: Audiências
        mostrava “Padrão do Windows” com o aviso, e Ajustes “7 (não
        encontrado)”, como se o número fosse o nome. E o nome que sumiu vinha
        com a marca no fim, cortada pela caixa (“… (não en”)."""
        pagina = self.abrir(extra="&microfone=7", secao="audiencias")
        pagina.wait_for_function("() => document.querySelector('#microfone').options.length > 1")
        frase = "O microfone escolhido antes não está mais na lista. Confira a escolha."
        self.assertEqual(pagina.locator("#microfone").input_value(), "")
        self.assertIn(frase, pagina.locator(".medidor-caixa").inner_text())
        self.ir(pagina, "ajustes")
        pagina.click(".ajustes-indice a[data-grupo='transcricao']")
        pagina.wait_for_function("() => (document.querySelector('#cfg-transcricao-dispositivo') || {options: []}).options.length > 1")
        campo = pagina.locator("#cfg-transcricao-dispositivo")
        self.assertEqual(campo.input_value(), "")
        self.assertNotIn("7", campo.evaluate("e => e.selectedOptions[0].text"))
        self.assertEqual(pagina.locator("#nota-microfone").inner_text(), frase)
        self.sem_problemas(pagina)
        # O nome que sumiu: a marca no início, a mesma nas duas telas, e cabe.
        nome = "Headset USB (Logitech H390)"
        pagina = self.abrir(extra="&microfone=" + quote(nome), secao="audiencias")
        pagina.wait_for_function("() => document.querySelector('#microfone').options.length > 1")
        rotulo = f"Não encontrado: {nome}"
        self.assertEqual(pagina.locator("#microfone").evaluate("e => e.selectedOptions[0].text"), rotulo)
        self.assertEqual(pagina.locator("#microfone").get_attribute("title"), rotulo)
        self.assertIn(f"O microfone “{nome}” não foi encontrado", pagina.locator(".medidor-caixa").inner_text())
        self.ir(pagina, "ajustes")
        pagina.click(".ajustes-indice a[data-grupo='transcricao']")
        pagina.wait_for_function("() => (document.querySelector('#cfg-transcricao-dispositivo') || {options: []}).options.length > 1")
        campo = pagina.locator("#cfg-transcricao-dispositivo")
        self.assertEqual(campo.input_value(), nome)
        self.assertEqual(campo.evaluate("e => e.selectedOptions[0].text"), rotulo)
        self.assertIn(f"O microfone “{nome}” não foi encontrado", pagina.locator("#nota-microfone").inner_text())
        sobra = campo.evaluate("""e => { const c = document.createElement('canvas').getContext('2d'); const s = getComputedStyle(e);
            c.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
            return e.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight) - c.measureText(e.selectedOptions[0].text).width; }""")
        self.assertGreaterEqual(sobra, 0, "o rótulo do microfone não encontrado cortado em Ajustes")
        self.sem_problemas(pagina)

    def test_falha_ao_comecar_tem_o_vermelho_do_testar(self):
        """O mesmo erro de microfone aparecia vermelho no “Testar” e com o
        ícone azul de informação no “Gravar” (a falha chega pelo evento de
        estado “erro”, fase “inicio”)."""
        pagina = self.abrir(extra="&microfone=" + quote("Fone que foi desligado"), secao="audiencias")
        pagina.click("#testar-microfone")
        testar = pagina.locator(".folha:has-text('O microfone não respondeu') .folha-icone")
        testar.wait_for()
        self.assertIn("erro", testar.get_attribute("class").split())
        pagina.click(".folha button:has-text('OK')")
        pagina.wait_for_selector(".folha-fundo", state="detached")
        pagina.select_option("#microfone", "")
        pagina.fill("#processo-audiencia", "07002311520248020001")
        pagina.click("#botao-gravar")
        pagina.wait_for_selector(".ao-vivo")
        pagina.evaluate("""() => Helestron.api.emitir('transcricao', { tipo: 'estado', dados: { estado: 'erro', fase: 'inicio',
            texto: 'Nenhum microfone foi encontrado. Ligue o microfone (ou o fone com microfone) e tente de novo.' } })""")
        gravar = pagina.locator(".folha:has-text('A gravação não começou') .folha-icone")
        gravar.wait_for()
        self.assertIn("erro", gravar.get_attribute("class").split())
        self.capturar(pagina, "gravar-falhou-vermelho")
        self.sem_problemas(pagina)

    def test_documento_salvo_mostra_o_nome_inteiro(self):
        """No cartão “Transcrição salva”, o nome do documento (o número do
        processo) saía cortado pelo limite de duas linhas em 1024 e em 1366 a
        125 % (“0700231- / 15.2024.8.0…”), e o “(2)” da segunda transcrição
        sumia; o título quebrava em “Transcrição / salva”."""
        for nome, largura, altura, escala in self.TAMANHOS_PEQUENOS:
            for arquivo in ("0700231-15.2024.8.02.0001.docx", "0700231-15.2024.8.02.0001 (2).docx"):
                with self.subTest(tamanho=nome, arquivo=arquivo):
                    pagina = self.abrir(largura, altura, escala, secao="ajuda")
                    self.responder_com(pagina, "GET /api/transcricao/estado", {
                        "sessao": None, "estado": "encerrada", "processo": "0700231-15.2024.8.02.0001",
                        "documento": "C:\\Users\\camila.albuquerque\\Documents\\Helestron\\Acervo\\Transcricoes\\" + arquivo,
                        "falas": []})
                    self.ir(pagina, "audiencias")
                    nome_doc = pagina.locator(".documento-pronto .documento-nome")
                    self.assertEqual(nome_doc.inner_text().replace("\n", ""), arquivo)
                    self.assertEqual(nome_doc.get_attribute("title"), arquivo)
                    cabe = nome_doc.evaluate("e => e.scrollHeight <= e.clientHeight + 1 && e.scrollWidth <= e.clientWidth + 1")
                    self.assertTrue(cabe, "o nome do documento cortado")
                    titulo = pagina.locator(".documento-pronto .andamento-titulo")
                    linhas = titulo.evaluate("e => Math.round(e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight || 26))")
                    self.assertLessEqual(linhas, 1, "“Transcrição salva” quebrado em duas linhas")
                    self.numeros_inteiros(pagina, "documento")
                    self.sem_problemas(pagina)

    def test_lote_mostra_o_detalhe_inteiro_e_o_abrir_o_pdf(self):
        """A tabela “Processos do lote” precisava de 922 px (Detalhe sem
        quebra de linha): na janela mínima, o “Abrir o PDF” de cada processo
        ficava fora da vista e o Detalhe era cortado no meio
        (“Segredo de justiça: salvo na pasta d”)."""
        pagina = self.abrir(secao="processos")
        pagina.click("#area-soltar button:has-text('Escolher arquivo')")
        pagina.wait_for_selector(".revisao")
        pagina.click("#botao-baixar")
        pagina.wait_for_selector(".folha-pergunta", timeout=15000)
        pagina.fill("#campo-codigo", "482193")
        pagina.wait_for_selector(".lote-concluido", timeout=60000)
        # As frases do programa de verdade são mais longas que as da demonstração.
        pagina.evaluate("""() => { const t = [...Helestron.loja.tarefas.values()].find(x => x.tipo === 'download');
            const n = [...document.querySelectorAll('.itens-lote tbody tr')].map(tr => tr.dataset.numero);
            Helestron.api.emitir('item', { tarefa: t.id, numero: n[0], situacao: 'OK', sigiloso: true, arquivo: 'C:\\\\Sigilosos\\\\x.pdf',
              mensagem: 'sigiloso (na pasta dos sigilosos); guardado na pasta de sigilosos' });
            Helestron.api.emitir('item', { tarefa: t.id, numero: n[1], situacao: 'NAO_ENCONTRADO', arquivo: '',
              mensagem: 'não encontrado no e-SAJ nem no eProc do TJAL; confira o número' }); }""")
        pagina.wait_for_function("() => document.querySelector('.itens-lote').textContent.includes('confira o número')")
        medir = """() => { const t = document.querySelector('.itens-lote .tabela-rolagem'); const r = t.getBoundingClientRect();
            const fora = [...t.querySelectorAll('td.coluna-abrir button')].filter(b => b.getBoundingClientRect().right > r.right + 1).length;
            const cortadas = [...t.querySelectorAll('.mensagem-item')].filter(m => m.getClientRects().length)
              .filter(m => m.scrollWidth > m.clientWidth + 1 || m.getBoundingClientRect().right > r.right + 1
                || [...t.querySelectorAll('td.coluna-abrir')].some(c => { const a = c.getBoundingClientRect(), b = m.getBoundingClientRect();
                     return Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1; }))
              .map(m => m.textContent);
            const visiveis = [...t.querySelectorAll('.mensagem-item')].filter(m => m.getClientRects().length).map(m => m.textContent);
            return { rola: t.scrollWidth > t.clientWidth + 1, fora, botoes: t.querySelectorAll('td.coluna-abrir button').length, cortadas, visiveis }; }"""
        for nome, largura, altura in (("1280x820", 1280, 820), ("1100x720", 1100, 720),
                                      ("1024x768", 1024, 768), ("1366x768-zoom125", 1093, 614)):
            with self.subTest(tamanho=nome):
                pagina.set_viewport_size({"width": largura, "height": altura})
                pagina.wait_for_timeout(250)
                m = pagina.evaluate(medir)
                self.assertGreater(m["botoes"], 0)
                self.assertEqual((m["rola"], m["fora"], m["cortadas"]), (False, 0, []), m)
                for frase in ("Segredo de justiça: salvo na pasta dos sigilosos.",
                              "não encontrado no e-SAJ nem no eProc do TJAL; confira o número"):
                    self.assertIn(frase, m["visiveis"])
                self.numeros_inteiros(pagina, "lote")
        pagina.locator(".itens-lote").scroll_into_view_if_needed()
        self.capturar(pagina, "lote-detalhe-inteiro-1366x768-zoom125")
        self.sem_problemas(pagina)

    def test_resultado_de_mais_acoes_da_pauta_fica_a_vista(self):
        """“Importar relatório” e “Capturar no portal” ficam no pé da página
        (cartão “Mais ações”) e o resultado vai para a faixa do topo: sem
        rolar até ela, nada mudava onde a pessoa olhava - e, com a Pauta
        aberta, o aviso do canto não se repete."""
        for nome, largura, altura, escala in (("1100x720", 1100, 720, 1), ("1280x820", 1280, 820, 1)):
            for acao in ("importar", "capturar"):
                with self.subTest(tamanho=nome, acao=acao):
                    pagina = self.abrir(largura, altura, escala, secao="pauta")
                    # Rolagem instantânea até o pé (a da tela, ao trazer a faixa, continua suave).
                    pagina.evaluate("document.getElementById('conteudo').style.scrollBehavior = 'auto'")
                    pagina.locator("#acao-" + acao).scroll_into_view_if_needed()
                    faixa = pagina.evaluate("document.querySelector('#resultado-pauta').getBoundingClientRect().top")
                    self.assertLess(faixa, 0, "o botão já estava perto da faixa: o teste não prova nada")
                    pagina.click("#acao-" + acao)
                    if acao == "capturar":
                        pagina.click(".folha button:has-text('Abrir o portal')")
                    pagina.wait_for_function("() => document.querySelector('#resultado-pauta').textContent.trim().length > 0",
                                             timeout=40000)
                    pagina.wait_for_function("""() => { const r = document.querySelector('#resultado-pauta .faixa').getBoundingClientRect();
                        return r.top >= 0 && r.bottom <= innerHeight; }""", timeout=5000)
                    self.sem_problemas(pagina)

    def test_fim_do_monitoramento_nao_mexe_na_rolagem_da_pauta(self):
        """A tela adota a sincronização do monitoramento automático (mesmo
        tipo de tarefa): no fim, o resultado vai para a faixa, mas quem está
        lendo a lista lá embaixo não é levado ao topo a cada ciclo. Só o que
        a pessoa clicou nesta tela (Sincronizar, Importar, Capturar) vem à vista."""
        rolante = ("(() => { const c = document.getElementById('conteudo'); "
                   "return c && c.scrollHeight > c.clientHeight ? c : document.scrollingElement; })()")
        topo_da_faixa = "document.querySelector('#resultado-pauta').getBoundingClientRect().top"
        pagina = self.abrir(1100, 720, secao="pauta")
        pagina.evaluate("document.getElementById('conteudo').style.scrollBehavior = 'auto'")
        pagina.locator("#acao-importar").scroll_into_view_if_needed()
        self.assertGreater(pagina.evaluate(f"{rolante}.scrollTop"), 200, "a lista não rola: o teste não prova nada")
        self.assertLess(pagina.evaluate(topo_da_faixa), 0)
        # O que a pessoa lê fica no mesmo lugar da janela (a faixa que cresce
        # lá em cima é compensada pela ancoragem da rolagem do navegador).
        lido = "document.querySelector('#acao-importar').getBoundingClientRect().top"
        antes = pagina.evaluate(lido)
        pagina.evaluate("""() => {
            const t = { id: 'monitor-1', tipo: 'pauta_sincronizar', titulo: 'Monitoramento da pauta', estado: 'rodando', progresso: {} };
            Helestron.api.emitir('tarefa', t);
            Helestron.api.emitir('tarefa', Object.assign({}, t, { estado: 'concluida', status: 'Pauta atualizada.',
              resultado: { novas: 0, atualizadas: 0, removidas: 0, erros: [], avisos: [] } })); }""")
        pagina.wait_for_function("() => document.querySelector('#resultado-pauta').textContent.includes('Pauta sincronizada')",
                                 timeout=5000)
        pagina.wait_for_timeout(900)          # a rolagem suave, se houvesse, já teria andado
        self.assertAlmostEqual(pagina.evaluate(lido), antes, delta=2)
        self.assertLess(pagina.evaluate(topo_da_faixa), 0)
        # A sincronização que a pessoa pediu (o evento da tarefa chega antes da
        # resposta do pedido e a tela a adota primeiro): o resultado vem à vista.
        pagina.evaluate(f"{rolante}.scrollTop = 0")
        pagina.click("#botao-sincronizar")
        pagina.wait_for_function("() => [...Helestron.loja.tarefas.values()].some(t => t.tipo === 'pauta_sincronizar' "
                                 "&& t.id !== 'monitor-1' && t.estado === 'rodando')")
        pagina.locator("#acao-importar").scroll_into_view_if_needed()
        self.assertLess(pagina.evaluate(topo_da_faixa), 0)
        pagina.wait_for_function("""() => { const f = document.querySelector('#resultado-pauta .faixa');
            if (!f || !f.textContent.includes('Pauta sincronizada')) return false;
            const r = f.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }""", timeout=30000)
        # A que termina antes da resposta do pedido (os eventos chegam
        # primeiro): o resultado já mostrado não é apagado pela tela.
        pagina.evaluate("""() => { const responder = Helestron.demo.responder;
            Helestron.demo.responder = async (r, p) => {
              if (r !== 'POST /api/pauta/sincronizar') return responder(r, p);
              const t = { id: 'rapida-1', tipo: 'pauta_sincronizar', titulo: 'Sincronizar a pauta', estado: 'rodando', progresso: {} };
              Helestron.api.emitir('tarefa', t);
              Helestron.api.emitir('tarefa', Object.assign({}, t, { estado: 'falhou', erro: 'O portal recusou o acesso.' }));
              return { tarefa: t.id }; }; }""")
        pagina.evaluate(f"{rolante}.scrollTop = 0")
        pagina.click("#botao-sincronizar")
        pagina.wait_for_function("() => document.querySelector('#resultado-pauta').textContent.includes('O portal recusou o acesso.')",
                                 timeout=5000)
        pagina.wait_for_timeout(500)
        self.assertIn("Não consegui sincronizar a pauta", pagina.inner_text("#resultado-pauta"))
        self.assertFalse(pagina.is_disabled("#botao-sincronizar"))
        self.sem_problemas(pagina)

    def test_hoje_na_pauta_sem_fonte_nao_fala_de_fonte(self):
        """Pauta configurada só por um relatório importado (C5), sem audiência
        futura: o Início dizia “A fonte está cadastrada” sem fonte nenhuma."""
        pagina = self.abrir(extra="&pauta=vazia", secao="ajuda")
        pagina.evaluate("""async () => { const responder = Helestron.demo.responder;
            Helestron.demo.responder = async (r, p) => { const v = await responder(r, p);
              if (r === 'GET /api/estado') v.resumo.pauta = Object.assign({}, v.resumo.pauta,
                { hoje: 0, semana: 0, proxima: null, ultima_sincronizacao: null, fontes: 0, configurada: true });
              if (r === 'GET /api/pauta') { v.audiencias = []; v.resumo = Object.assign({}, v.resumo, { total: 0 }); }
              return v; };
            // Uma releitura já em curso (ou que acabou de terminar) devolve o
            // resumo de antes: relê até chegar o novo.
            for (let i = 0; i < 30; i++) {
              const e = await Helestron.app.recarregarEstado();
              if (e && e.resumo && e.resumo.pauta && e.resumo.pauta.configurada === true) break;
              await new Promise((ok) => setTimeout(ok, 100));
            } }""")
        self.assertIs(pagina.evaluate("Helestron.loja.estado.resumo.pauta.configurada"), True)
        self.ir(pagina, "inicio")
        cartao = pagina.locator("section[aria-label='Hoje na pauta']").inner_text()
        self.assertNotIn("fonte", cartao.lower())
        self.assertNotIn("não foi sincronizada", cartao)
        self.assertIn("Nenhuma audiência hoje", cartao)
        self.assertIn("Nenhuma audiência designada nos próximos dias.", cartao)
        self.sem_problemas(pagina)

    def test_codex_ausente_na_demonstracao_como_no_programa(self):
        """A demonstração lançava um erro “nao_instalado” (folha “Não deu
        certo”, “Instale-o pelo site da OpenAI”) que o programa nunca dá: ele
        responde {abriu: false, mensagem} com os botões que existem (C6)."""
        pagina = self.abrir(secao="compartilhar")
        pagina.click("#destino-codex button:has-text('Abrir no Codex')")
        folha = pagina.locator(".folha")
        folha.wait_for()
        texto = folha.inner_text()
        self.assertEqual(folha.locator(".folha-titulo").inner_text(), "Codex")
        self.assertNotIn("Não deu certo", texto)
        self.assertNotIn("site da OpenAI", texto)
        for trecho in ("Conector de leitura do acervo registrado em", "“Abrir no ChatGPT Work”", "“Gerar o pacote”"):
            self.assertIn(trecho, texto)
        self.sem_problemas(pagina)

    def test_abrir_a_pagina_que_falha_de_novo_diz_o_endereco(self):
        """Sem navegador, a folha oferece “Abrir a página” e também “Copiar o
        endereço”; se abrir falhar de novo, aparece a folha de erro com o
        endereço, em vez de nada."""
        url = "https://docs.claude.com/pt-BR/docs/claude-code/overview"
        pagina = self.abrir(secao="compartilhar", permissoes=["clipboard-read", "clipboard-write"])
        pagina.evaluate("""u => { const responder = Helestron.demo.responder;
            Helestron.demo.responder = (rota, pedido) => rota === 'POST /api/compartilhar/claude-code'
              ? Promise.resolve({ abriu: false, instalado: false, pagina_aberta: false, url: u,
                  mensagem: 'O Claude Code não está instalado neste computador. A página oficial explica como instalá-lo (sem administrador): ' + u })
              : rota === 'POST /api/abrir'
                ? Promise.reject(new Helestron.api.ErroApi('navegador_nao_abriu',
                    'Não consegui abrir o navegador. Copie o endereço e cole-o no navegador: ' + pedido.corpo.alvo, '', 409))
                : responder(rota, pedido); }""", url)
        pagina.click("#destino-claude-code button:has-text('Abrir no Claude Code')")
        pagina.click(".folha button:has-text('Copiar o endereço')")
        pagina.wait_for_selector(".aviso:has-text('Endereço copiado')")
        self.assertEqual(pagina.evaluate("navigator.clipboard.readText()"), url)
        pagina.click(".folha button:has-text('Abrir a página')")
        erro = pagina.locator(".folha:has-text('Não consegui abrir o navegador')")
        erro.wait_for()
        self.assertIn(url, erro.inner_text())
        self.sem_problemas(pagina)

    def test_resto_de_sigiloso_no_acervo_avisado_no_inicio_e_no_compartilhar(self):
        """A pendência “sigilo-arquivos” do Início leva à tela Compartilhar,
        que mostra a mesma frase (o arquivo, o motivo, o que fazer) sem travar
        nada; o preparo conta o que fez numa faixa que fica até ser fechada."""
        pagina = self.abrir(1100, 720, extra="&sigilo=arquivos")
        passo = pagina.locator(".primeiros-passos .passo:has-text('Arquivo de processo sigiloso no acervo')")
        self.assertEqual(passo.count(), 1)
        self.assertIn("ficou no acervo", passo.inner_text())
        passo.locator("button:has-text('Resolver')").click()
        self.esperar_secao(pagina, "compartilhar")
        faixa = pagina.locator("#sigilosos-no-acervo .faixa")
        faixa.wait_for()
        self.assertEqual(faixa.count(), 1)
        self.assertIn("faixa-aviso", faixa.get_attribute("class"))
        texto = faixa.inner_text()
        for trecho in ("Arquivo de processo sigiloso no acervo", f"Minutas\\{PROCESSO_SIGILOSO}.docx",
                       "está aberto em outro programa?", "O compartilhamento continua"):
            self.assertIn(trecho, texto)
        for rotulo in ("Preparar de novo", "Abrir a pasta do arquivo", "Abrir a pasta dos sigilosos"):
            self.assertEqual(faixa.locator(f"button:has-text('{rotulo}')").count(), 1, rotulo)
        # não trava: os destinos continuam funcionando
        self.assertFalse(pagina.locator("#destino-codex button").is_disabled())
        self.capturar(pagina, "compartilhar-sigiloso-arquivos")
        faixa.locator("button:has-text('Preparar de novo')").click()
        resultado = pagina.locator("#resultado-preparo .faixa")
        resultado.wait_for(timeout=15000)
        # o aviso do que ficou não se repete embaixo: já está no alto
        self.assertEqual(resultado.count(), 1)
        texto = resultado.inner_text()
        self.assertIn("Um aviso do preparo", texto)
        self.assertIn("foi levado para a pasta dos sigilosos", texto)
        self.assertNotIn("O compartilhamento continua", texto)
        self.capturar(pagina, "compartilhar-resultado-do-preparo")
        resultado.locator("button[title='Fechar este aviso']").click()
        self.assertEqual(pagina.locator("#resultado-preparo .faixa").count(), 0)
        self.assertEqual(pagina.locator("#sigilosos-no-acervo .faixa").count(), 1)
        self.texto_em_portugues(pagina, "compartilhar")
        self.sem_problemas(pagina)

    def test_autos_de_sigiloso_presos_suspendem_o_compartilhamento(self):
        pagina = self.abrir(1100, 720, extra="&sigilo=autos", secao="compartilhar")
        faixa = pagina.locator("#sigilosos-no-acervo .faixa")
        faixa.wait_for()
        self.assertIn("faixa-erro", faixa.get_attribute("class"))
        texto = faixa.inner_text()
        for trecho in ("Processo sigiloso no acervo", "não puderam sair do acervo",
                       f"{PROCESSO_SIGILOSO}.pdf", "ficam suspensos"):
            self.assertIn(trecho, texto)
        self.assertEqual(faixa.locator("button:has-text('Tentar de novo')").count(), 1)
        self.capturar(pagina, "compartilhar-sigiloso-autos")
        # a recusa (409) vira a folha de erro com a mesma frase
        pagina.click("#destino-claude-code button:has-text('Abrir no Claude Code')")
        folha = pagina.locator(".folha:has-text('não puderam sair do acervo')")
        folha.wait_for()
        self.assertIn(f"{PROCESSO_SIGILOSO}.pdf", folha.inner_text())
        self.ir(pagina, "inicio")
        self.assertEqual(pagina.locator(
            ".primeiros-passos .passo:has-text('Processo sigiloso no acervo')").count(), 1)
        self.sem_problemas(pagina)

    def test_fonte_sem_endereco_salvo_sem_jargao(self):
        """“Sem rota” é o nome interno (a URL guardada da pauta): a tela diz
        o que isso quer dizer para quem usa."""
        pagina = self.abrir(secao="ajuda")
        pagina.evaluate("""() => { const responder = Helestron.demo.responder;
            Helestron.demo.responder = async (r, p) => { const v = await responder(r, p);
              if (r === 'GET /api/pauta/fontes') v.push({ id: 'f-esaj-tjsp', tribunal: 'TJSP', sistema: 'esaj', rotulo: 'e-SAJ · TJSP',
                modo: 'automatico', url: '', menu: '', monitorada: false, exige_presenca: false, motivo_presenca: '',
                ultima_sincronizacao: null, ultimo_erro: '' });
              return v; }; }""")
        self.ir(pagina, "ajustes")
        pagina.click(".ajustes-indice a[data-grupo='pauta']")
        pagina.wait_for_selector(".grupo[aria-label='Fontes da pauta'] .linha:has-text('TJSP')")
        lista = pagina.locator(".grupo[aria-label='Fontes da pauta']").inner_text()
        self.assertIn("Sem endereço salvo", lista)
        self.assertNotIn("rota", lista.lower())
        self.ir(pagina, "pauta")
        cartao = pagina.locator(".cartao:has-text('Conferir sozinho')").inner_text()
        self.assertIn("e-SAJ TJSP (sem endereço salvo)", cartao)
        self.assertNotIn("rota", cartao.lower())
        self.sem_problemas(pagina)

    def test_textos_que_cortados_mudam_o_sentido(self):
        """Em 1024 px (janela maximizada numa tela pequena), o rodapé do cartão
        “Compartilhar com IA” mostrava só “Sigilosos nunca vão para”."""
        for nome, largura, altura, escala in self.TAMANHOS_PEQUENOS:
            with self.subTest(tamanho=nome):
                pagina = self.abrir(largura, altura, escala)
                cortadas = pagina.evaluate("""() => [...document.querySelectorAll('.cartao-funcao-meta')]
                    .filter(e => e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1).map(e => e.textContent.trim())""")
                self.assertEqual(cortadas, [])
                self.assertIn("Sigilosos nunca vão para a IA",
                              pagina.locator(".cartao-funcao[data-funcao='compartilhar'] .cartao-funcao-meta").inner_text())
                self.sem_problemas(pagina)

    def test_quadrados_de_icone_so_em_azul_navy_e_cinza(self):
        """Quadrados de ícone só em azul, navy e cinza (o pedido: azul, cinza e branco).

        Ajustes tinha Download em verde, Transcrição em vermelho e
        Compartilhar em índigo; Compartilhar, o Cowork em índigo e o Pacote em
        âmbar; a fonte da pauta com erro e o endereço corrigido ficavam em
        âmbar, o acesso com senha em verde. O estado continua à vista, no
        ponto e na pílula."""
        pagina = self.abrir()
        pagina.evaluate("""() => { const responder = Helestron.demo.responder;
            Helestron.demo.responder = async (r, p) => {
              const v = await responder(r, p);
              if (r === 'GET /api/pauta/fontes' && v.length) v[v.length - 1].ultimo_erro = 'O portal não respondeu.';
              if (r === 'GET /api/tribunais/enderecos') return [{ portal: 'esaj:TJAL', grau: '1', rotulo: '1º grau',
                url: 'https://www2.tjal.jus.br/esaj-novo', rotulo_portal: 'e-SAJ · TJAL' }];
              return v; }; }""")
        rotas = SECOES[:5] + [f"ajustes/{s}" for s in ("acessos", "pastas", "unidade", "download", "transcricao",
                                                         "pauta", "compartilhar", "sobre")] + ["ajuda"]
        for rota in rotas:
            with self.subTest(tela=rota):
                pagina.evaluate("s => { location.hash = '#/' + s; }", rota)
                secao, _, grupo = rota.partition("/")
                self.esperar_secao(pagina, secao)
                if grupo:
                    pagina.wait_for_selector(f"#ajustes-{grupo}")
                    pagina.wait_for_function("() => !document.querySelector('.ajustes-detalhe [aria-busy=\"true\"]')")
                pagina.wait_for_timeout(300)        # as listas que chegam depois
                self.assertEqual(self.blocos_fora_da_paleta(pagina), [])
                if rota == "ajustes/acessos":
                    pagina.wait_for_selector("#grupo-enderecos .linha:has-text('esaj-novo')")
                    self.assertEqual(self.blocos_fora_da_paleta(pagina), [])
        # A fonte com erro diz o estado no ponto âmbar, ao lado do texto.
        pagina.evaluate("location.hash = '#/ajustes/pauta'")
        erro = pagina.locator(".linha:has-text('Último erro: O portal não respondeu.')")
        erro.wait_for()
        self.assertEqual(erro.locator(".ponto.ponto-ambar").count(), 1)
        self.sem_problemas(pagina)


if __name__ == "__main__":
    unittest.main()
