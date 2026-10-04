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
from pathlib import Path

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
    def abrir(self, largura=1280, altura=820, escala=1.0, extra="", secao="inicio"):
        contexto = self.nav.chromium.new_context(
            viewport={"width": largura, "height": altura}, device_scale_factor=escala,
            locale="pt-BR", timezone_id="America/Maceio")
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
        self.assertEqual(sorted(iniciou["opcoes"]), ["navegador_visivel", "rebaixar", "separar_sigilosos"])
        self.assertEqual(len(iniciou["processos"]), 3)
        self.capturar(pagina, "fluxo-lote-concluido")
        self.sem_problemas(pagina)

    def test_audiencia_gravada_ate_o_documento(self):
        pagina = self.abrir(secao="audiencias")
        self.assertTrue(pagina.locator("#botao-gravar").is_disabled())
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
        pagina.click("#botao-pausar")
        pagina.wait_for_selector(".selo-gravando.pausado")
        pagina.click("#botao-pausar")
        pagina.wait_for_selector(".selo-gravando:not(.pausado)")
        pagina.click("#botao-encerrar")
        pagina.click(".folha button:has-text('Encerrar e salvar')")
        pagina.wait_for_selector(".documento-pronto", timeout=10000)
        self.assertIn("0700231-15.2024.8.02.0001.docx", pagina.locator(".documento-pronto").inner_text())
        self.capturar(pagina, "fluxo-documento")
        iniciou = pagina.evaluate(
            "Helestron.demo.chamadas.find(c => c.rota === 'POST /api/transcricao/iniciar').corpo")
        self.assertEqual(iniciou["processo"], "0700231-15.2024.8.02.0001")
        self.assertEqual(iniciou["participantes"]["F1"], "Juiz(a)")
        self.assertIs(iniciou["sigiloso"], False)
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


if __name__ == "__main__":
    unittest.main()
