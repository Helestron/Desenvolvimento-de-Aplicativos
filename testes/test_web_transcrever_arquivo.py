"""Audiências › "Arquivo de áudio ou vídeo", no Chromium, em modo demonstração.

A tela tem dois modos no topo, do mesmo tamanho: "Ao vivo" (a transcrição
simultânea) e "Arquivo de áudio ou vídeo" (a gravação que já existe). No modo
arquivo: arrastar e soltar ou "Escolher arquivo" (o diálogo do Windows manda
só o caminho; o seletor do navegador e o arrastar mandam o arquivo), o nome e
o tamanho, o número do processo tirado do nome do arquivo ou da pasta com o
dependente ("-01" vira "/01"), o tipo, o sigilo, Transcrever, o andamento e o
resultado - ou o motivo, quando o arquivo não tem áudio.

Mesmo servidor de arquivos e mesmo Chromium dos testes da interface
(test_web_interface); pulado sem o Playwright ou sem o Chromium.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from testes.test_web_interface import CORTADOS, PROCESSO_SIGILOSO, _Navegador, numero_cnj

# A mídia do incidente que o diálogo da demonstração devolve (demo.js):
# _controle\midias\<número>-01\video_audiencia.mp4
DA_PASTA = numero_cnj(700412, 2024, 8, 2, 1)
VALIDO = "0700231-15.2024.8.02.0001"

SOLTAR = """([nome, tipo, tamanho, pasta]) => {
  const dt = new DataTransfer();
  if (nome) {
    const f = new File([new Uint8Array(Math.min(tamanho, 4096))], nome, { type: tipo, lastModified: Date.UTC(2026, 8, 16, 17, 0) });
    if (tamanho > 4096) Object.defineProperty(f, "size", { value: tamanho });
    dt.items.add(f);
  }
  const alvo = document.querySelector('#conteudo');
  for (const t of ['dragenter', 'dragover', 'drop']) alvo.dispatchEvent(new DragEvent(t, { bubbles: true, cancelable: true, dataTransfer: dt }));
}"""


class TranscreverArquivoNoNavegador(unittest.TestCase):
    nav: _Navegador | None = None

    @classmethod
    def setUpClass(cls):
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError as erro:
            raise unittest.SkipTest("Playwright não instalado") from erro
        cls.nav = _Navegador()

    @classmethod
    def tearDownClass(cls):
        if cls.nav is not None:
            cls.nav.fechar()

    # ---------------------------------------------------------- apoio
    def abrir(self, largura=1280, altura=820, escala=1.0, extra=""):
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
        self.addCleanup(contexto.close)
        pagina.goto(f"{self.nav.base}?demo=1{extra}#/audiencias")
        pagina.wait_for_function(
            "() => document.documentElement.dataset.secao === 'audiencias' && "
            "document.documentElement.dataset.pronta === '1'", timeout=15000)
        pagina.evaluate("document.fonts.ready")
        pagina.problemas = problemas
        return pagina

    def modo_arquivo(self, pagina):
        pagina.click("#modo-audiencia [data-valor='arquivo']")
        pagina.wait_for_selector("#painel-arquivo:not([hidden])")

    def chamadas(self, pagina, rota):
        return pagina.evaluate(
            "r => Helestron.demo.chamadas.filter(c => c.rota === r).map(c => Object.assign({ multipart: c.multipart }, c.corpo))",
            rota)

    def sem_problemas(self, pagina):
        self.assertEqual(pagina.problemas, [], "erros no navegador:\n" + "\n".join(pagina.problemas))

    def sem_rolagem_horizontal(self, pagina):
        larguras = pagina.evaluate(
            "[document.documentElement.scrollWidth, innerWidth, document.getElementById('conteudo').scrollWidth,"
            " document.getElementById('conteudo').clientWidth]")
        self.assertLessEqual(larguras[0], larguras[1], "rolagem horizontal na página")
        self.assertLessEqual(larguras[2], larguras[3] + 1, "conteúdo mais largo que a área")

    # ---------------------------------------------------------- testes
    def test_dois_modos_do_mesmo_tamanho_tambem_pelo_teclado(self):
        pagina = self.abrir()
        radios = pagina.locator("#modo-audiencia [role='radio']")
        self.assertEqual(radios.all_inner_texts(), ["Ao vivo", "Arquivo de áudio ou vídeo"])
        larguras = radios.evaluate_all("rs => rs.map(r => r.getBoundingClientRect().width)")
        self.assertAlmostEqual(larguras[0], larguras[1], delta=2)
        self.assertEqual(radios.nth(0).get_attribute("aria-checked"), "true")
        self.assertEqual(radios.nth(1).get_attribute("aria-controls"), "painel-arquivo")
        self.assertTrue(pagina.locator("#botao-gravar").is_visible())
        self.assertTrue(pagina.locator("#painel-arquivo").is_hidden())
        # pelo teclado: a seta passa ao outro modo, que leva o foco
        radios.nth(0).focus()
        pagina.keyboard.press("ArrowRight")
        pagina.wait_for_selector("#painel-arquivo:not([hidden])")
        self.assertEqual(radios.nth(1).get_attribute("aria-checked"), "true")
        self.assertTrue(pagina.locator("#botao-gravar").is_hidden())
        self.assertTrue(pagina.locator("#escolher-gravacao").is_visible())
        self.assertIn("gravações de áudio e vídeo", pagina.locator(".subtitulo").inner_text())
        # o modo escolhido fica para a próxima vez
        pagina.reload()
        pagina.wait_for_function("() => document.documentElement.dataset.pronta === '1'")
        self.assertTrue(pagina.locator("#painel-arquivo").is_visible())
        pagina.click("#modo-audiencia [data-valor='ao_vivo']")
        self.assertTrue(pagina.locator("#botao-gravar").is_visible())
        self.sem_problemas(pagina)

    def test_dialogo_do_windows_manda_so_o_caminho_com_o_dependente_da_pasta(self):
        pagina = self.abrir()
        self.modo_arquivo(pagina)
        self.assertTrue(pagina.locator("#botao-transcrever").is_disabled())
        pagina.click("#escolher-gravacao")
        pagina.wait_for_selector("#arquivo-escolhido:not([hidden])")
        self.assertEqual(pagina.locator("#nome-gravacao").inner_text(), "video_audiencia.mp4")
        self.assertIn("sem cópia", pagina.locator("#tamanho-gravacao").inner_text())
        # o número está na pasta da mídia (…-01): vira o dependente /01
        self.assertEqual(pagina.locator("#processo-gravacao").input_value(), f"{DA_PASTA}/01")
        self.assertIn("dependente 01", pagina.locator("#ajuda-processo-gravacao").inner_text())
        pagina.select_option("#tipo-gravacao", "Una")
        pagina.click("#botao-transcrever")
        pagina.wait_for_selector("#tarefa-gravacao")
        pedido = self.chamadas(pagina, "POST /api/transcricao/gravacao")[0]
        self.assertFalse(pedido["multipart"])
        self.assertTrue(pedido["caminho"].endswith(f"\\{DA_PASTA}-01\\video_audiencia.mp4"))
        self.assertEqual((pedido["processo"], pedido["tipo"], pedido["sigiloso"]),
                         (f"{DA_PASTA}/01", "Una", False))
        # uma gravação de cada vez: enquanto transcreve, nada de outra
        self.assertTrue(pagina.locator("#botao-transcrever").is_disabled())
        self.assertTrue(pagina.locator("#trocar-gravacao").is_disabled())
        self.assertIn("Transcrevendo esta gravação", pagina.locator("#dica-transcrever").inner_text())
        # o resultado: o documento (com "-01" no nome), e a tela pronta para outra
        pagina.wait_for_selector("#andamento-arquivo button:has-text('Abrir documento')", timeout=20000)
        self.assertIn(f"{DA_PASTA}-01.docx", pagina.locator("#status-gravacao").inner_text())
        self.assertTrue(pagina.locator("#soltar-gravacao").is_visible())
        self.assertEqual(pagina.locator("#processo-gravacao").input_value(), "")
        pagina.wait_for_selector(f".transcricoes-recentes .item-titulo[title='{DA_PASTA}/01']")
        self.sem_problemas(pagina)

    def test_arrastar_e_soltar_manda_o_arquivo_com_o_nome_e_a_data(self):
        pagina = self.abrir()
        # soltar no modo ao vivo passa para o modo arquivo
        pagina.evaluate(SOLTAR, [f"{VALIDO}-02 2026-09-16 14h00.wav", "audio/wav", 3000, False])
        pagina.wait_for_selector("#painel-arquivo:not([hidden])")
        self.assertEqual(pagina.locator("#nome-gravacao").inner_text(),
                         f"{VALIDO}-02 2026-09-16 14h00.wav")
        self.assertIn("2,9 KB", pagina.locator("#tamanho-gravacao").inner_text())
        self.assertEqual(pagina.locator("#processo-gravacao").input_value(), f"{VALIDO}/02")
        pagina.click("#botao-transcrever")
        pagina.wait_for_selector("#tarefa-gravacao")
        pedido = self.chamadas(pagina, "POST /api/transcricao/gravacao")[0]
        self.assertTrue(pedido["multipart"])
        self.assertEqual(pedido["arquivo"]["nome"], f"{VALIDO}-02 2026-09-16 14h00.wav")
        self.assertEqual(pedido["nome_original"], f"{VALIDO}-02 2026-09-16 14h00.wav")
        self.assertEqual(pedido["data_arquivo"], "2026-09-16T17:00:00.000Z")
        self.assertEqual(pedido["processo"], f"{VALIDO}/02")
        self.sem_problemas(pagina)

    def test_seletor_do_navegador_com_os_formatos_do_windows_e_sem_recusa(self):
        pasta = Path(tempfile.mkdtemp(prefix="helestron-midia-"))
        self.addCleanup(shutil.rmtree, pasta, True)
        estranho = pasta / "gravacao da sala.xyz"
        estranho.write_bytes(b"\x00" * 2048)
        quando = datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc)
        os.utime(estranho, (quando.timestamp(), quando.timestamp()))
        pagina = self.abrir(extra="&sem_dialogo=1")
        self.modo_arquivo(pagina)
        with pagina.expect_file_chooser() as escolha:
            pagina.click("#escolher-gravacao")
        aceitar = escolha.value.element.get_attribute("accept").split(",")
        for item in ("audio/*", "video/*", ".mp3", ".wma", ".m4b", ".wmv", ".asf", ".mkv",
                     ".dvr-ms", ".mxf", ".3gp", ".flac", ".opus"):
            self.assertIn(item, aceitar)
        escolha.value.set_files(str(estranho))
        pagina.wait_for_selector("#arquivo-escolhido:not([hidden])")
        # extensão fora da lista: avisa, mas não recusa
        self.assertIn("não parece ser de áudio", pagina.locator("#aviso-gravacao").inner_text())
        self.assertTrue(pagina.locator("#botao-transcrever").is_disabled())   # falta o número
        pagina.fill("#processo-gravacao", VALIDO.replace("-", "").replace(".", "") + "/1")
        self.assertEqual(pagina.locator("#processo-gravacao").input_value(), f"{VALIDO}/1")
        self.assertTrue(pagina.locator("#botao-transcrever").is_enabled())
        pagina.click("#botao-transcrever")
        pagina.wait_for_selector("#tarefa-gravacao")
        pedido = self.chamadas(pagina, "POST /api/transcricao/gravacao")[0]
        self.assertEqual(pedido["processo"], f"{VALIDO}/01")
        self.assertEqual(pedido["data_arquivo"], "2026-09-15T13:30:00.000Z")
        self.sem_problemas(pagina)

    def test_video_sem_audio_diz_por_que(self):
        pagina = self.abrir()
        self.modo_arquivo(pagina)
        pagina.evaluate(SOLTAR, [f"{VALIDO} audiência sem som.mp4", "video/mp4", 2048, False])
        pagina.wait_for_selector("#arquivo-escolhido:not([hidden])")
        pagina.click("#botao-transcrever")
        pagina.wait_for_selector("#tarefa-gravacao.falhou", timeout=15000)
        texto = pagina.locator("#tarefa-gravacao").inner_text()
        self.assertIn("A transcrição não deu certo", texto)
        self.assertIn("vídeo sem trilha de áudio", texto)
        # não deu certo: a gravação e o número ficam, para trocar ou corrigir
        self.assertTrue(pagina.locator("#arquivo-escolhido").is_visible())
        self.assertTrue(pagina.locator("#trocar-gravacao").is_enabled())
        self.assertEqual(pagina.locator("#processo-gravacao").input_value(), VALIDO)
        self.sem_problemas(pagina)

    def test_arquivo_maior_que_o_limite_do_envio_nem_sai(self):
        pagina = self.abrir()
        self.modo_arquivo(pagina)
        pagina.evaluate(SOLTAR, [f"{VALIDO} câmera da sala.mp4", "video/mp4", 21 * 1024 ** 3, False])
        pagina.wait_for_selector("#arquivo-escolhido:not([hidden])")
        self.assertIn("21 GB", pagina.locator("#tamanho-gravacao").inner_text())
        dica = pagina.locator("#dica-transcrever")
        self.assertIn("passa de 20 GB", dica.inner_text())
        self.assertIn("erro", dica.get_attribute("class"))
        self.assertTrue(pagina.locator("#botao-transcrever").is_disabled())
        self.assertEqual(self.chamadas(pagina, "POST /api/transcricao/gravacao"), [])
        # soltar uma pasta: pede o arquivo
        pagina.evaluate("""() => {
          const dt = new DataTransfer();
          Object.defineProperty(dt, 'items', { value: [{ webkitGetAsEntry: () => ({ isDirectory: true }) }] });
          Object.defineProperty(dt, 'types', { value: ['Files'] });
          document.querySelector('#conteudo').dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
        }""")
        pagina.wait_for_selector(".aviso:has-text('Arraste o arquivo, e não a pasta')")
        self.sem_problemas(pagina)

    def test_dependente_digitado_ao_vivo_vai_no_pedido(self):
        """Achado 33 na tela: o "-01" (ou "/01") digitado fica no campo e vai no
        pedido; a barra da audiência mostra o número inteiro, também no
        tamanho mínimo da janela."""
        for nome, largura, altura, escala in (("1280x820", 1280, 820, 1),
                                              ("1366x768-zoom125", 1093, 614, 1.25)):
            with self.subTest(tamanho=nome):
                pagina = self.abrir(largura, altura, escala)
                campo = pagina.locator("#processo-audiencia")
                campo.press_sequentially(VALIDO.replace("-", "").replace(".", "") + "-01", delay=5)
                self.assertEqual(campo.input_value(), f"{VALIDO}-01")
                pagina.wait_for_function(
                    "() => document.querySelector('#ajuda-processo').textContent.includes('dependente 01')")
                pagina.wait_for_function("() => !document.querySelector('#botao-gravar').disabled")
                pagina.click("#botao-gravar")
                pagina.wait_for_selector(".ao-vivo")
                self.assertEqual(self.chamadas(pagina, "POST /api/transcricao/iniciar")[0]["processo"],
                                 f"{VALIDO}/01")
                self.assertEqual(pagina.locator(".ao-vivo-processo").inner_text(), f"{VALIDO}/01")
                self.assertEqual(pagina.evaluate(CORTADOS), [])
                self.sem_problemas(pagina)

    def test_incidente_herda_o_sigilo_que_a_pauta_conhece(self):
        pagina = self.abrir()
        self.modo_arquivo(pagina)
        pagina.fill("#processo-gravacao", PROCESSO_SIGILOSO + "/01")
        pagina.wait_for_function("() => document.querySelector('#sigilo-gravacao').checked")
        self.assertIn("incidente de um processo sigiloso", pagina.locator("#motivo-sigilo-arquivo").inner_text())
        self.sem_problemas(pagina)

    def test_numero_cnj_com_o_dependente(self):
        pagina = self.abrir()
        casos = {
            "mascarar('07002311520248020001/01')": f"{VALIDO}/01",
            "mascarar('0700231-15.2024.8.02.0001-01')": f"{VALIDO}-01",
            "mascarar('0700231-15.2024.8.02.0001 - 1ª Vara')": VALIDO,
            "mascarar('0700231152024802000101')": VALIDO,
            "formatar('0700231-15.2024.8.02.0001-1')": f"{VALIDO}/01",
            "formatar('0700231-15.2024.8.02.0001/0003')": f"{VALIDO}/03",
            "principal('0700231-15.2024.8.02.0001/01')": VALIDO,
            "valido('0700231-15.2024.8.02.0001/01')": True,
            "doNome('0700231-15.2024.8.02.0001-01 2026-09-16 14h00.flac')": f"{VALIDO}/01",
            "doNome('0700231-15.2024.8.02.0001-2026-09-16.mp3')": VALIDO,
            "doNome('video_audiencia.mp4')": "",
            "doCaminho('C:\\\\Acervo\\\\_controle\\\\midias\\\\0700231-15.2024.8.02.0001-01\\\\video_audiencia.mp4')": f"{VALIDO}/01",
        }
        for expressao, esperado in casos.items():
            with self.subTest(expressao=expressao):
                self.assertEqual(pagina.evaluate(f"Helestron.cnj.{expressao}"), esperado)
        self.assertEqual(pagina.evaluate("[0, 1536, 20 * 1024 ** 3].map(Helestron.fmt.bytes)"),
                         ["0 bytes", "1,5 KB", "20 GB"])

    def test_cabe_em_janela_estreita_e_no_tamanho_minimo(self):
        for nome, largura, altura, escala in (("1100x720", 1100, 720, 1),
                                              ("1366x768-zoom125", 1093, 614, 1.25),
                                              ("edge-meia-tela", 683, 768, 1)):
            with self.subTest(tamanho=nome):
                pagina = self.abrir(largura, altura, escala)
                self.modo_arquivo(pagina)
                pagina.click("#escolher-gravacao")
                pagina.wait_for_selector("#arquivo-escolhido:not([hidden])")
                self.sem_rolagem_horizontal(pagina)
                self.assertEqual(pagina.evaluate(CORTADOS), [])
                larguras = pagina.locator("#modo-audiencia [role='radio']").evaluate_all(
                    "rs => rs.map(r => r.getBoundingClientRect().width)")
                self.assertAlmostEqual(larguras[0], larguras[1], delta=2)
                self.assertTrue(pagina.locator("#botao-transcrever").is_visible())
                self.sem_problemas(pagina)


if __name__ == "__main__":
    unittest.main()
