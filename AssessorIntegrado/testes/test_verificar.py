"""Testes da verificação da instalação (app/verificar.py).

Rodam em qualquer sistema: o que só existe no Windows (DPAPI, privacidade do
microfone) tem de sair como aviso "não se aplica" fora dele, e nunca quebrar.
As sondas em processo à parte são exercitadas com módulos de mentira que
falham, derrubam o processo ou travam - os três jeitos de uma DLL dar errado.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app import verificar
from app.nucleo import config
from app.verificar import AVISO, FALHA, OK, Item


def cfg_temporaria(pasta: Path) -> config.Config:
    """Config num arquivo temporário, com o acervo e os sigilosos dentro de `pasta`."""
    cfg = config.Config(pasta / "config.ini")
    cfg.definir("geral", "pasta_acervo", str(pasta / "Acervo"))
    cfg.definir("geral", "pasta_sigilosos", str(pasta / "Sigilosos"))
    return cfg


class TestResumo(unittest.TestCase):
    def test_resultado(self):
        ok = Item("A", OK)
        aviso = Item("B", AVISO, obrigatorio=False)
        falha_opcional = Item("C", FALHA, obrigatorio=False)
        falha = Item("D", FALHA)
        self.assertEqual(verificar.resumir([ok])["resultado"], OK)
        self.assertEqual(verificar.resumir([ok, aviso])["resultado"], AVISO)
        self.assertEqual(verificar.resumir([ok, falha_opcional])["resultado"], AVISO)
        r = verificar.resumir([ok, aviso, falha_opcional, falha])
        self.assertEqual((r["resultado"], r[OK], r[AVISO], r[FALHA]), (FALHA, 1, 1, 2))
        self.assertEqual(verificar.resumir([])["resultado"], FALHA)

    def test_frase_final_em_bom_portugues(self):
        f = verificar.frase_final(verificar.resumir([Item("A", OK)]))
        self.assertIn("1 OK, nenhum aviso e nenhuma falha", f)
        self.assertIn("Tudo certo", f)
        f = verificar.frase_final(verificar.resumir([Item("A", AVISO), Item("B", AVISO), Item("C", FALHA)]))
        self.assertIn("0 OK, 2 avisos e 1 falha", f)
        self.assertIn("INSTALAR.bat", f)

    def test_formatar_item(self):
        texto = verificar.formatar_item(Item("Microfone", AVISO, "Nenhum.", False,
                                             acao="Conecte um microfone de cerca de 60 MB " * 4))
        self.assertIn("AVISO", texto)
        self.assertIn("O que fazer:", texto)
        self.assertNotIn("60\n", texto.replace("\u00a0", " ").replace("60 MB", ""))
        self.assertNotIn("O que fazer", verificar.formatar_item(Item("A", OK, "certo", acao="x")))
        self.assertIn("FALHA*", verificar.formatar_item(Item("A", FALHA, obrigatorio=False)))

    def test_json(self):
        dados = verificar.para_json([Item("A", OK, "d", codigo="a"), Item("B", AVISO, obrigatorio=False)], True)
        self.assertEqual(dados["resultado"], AVISO)
        self.assertTrue(dados["completo"])
        self.assertEqual(dados["resumo"], {OK: 1, AVISO: 1, FALHA: 0})
        self.assertEqual(set(dados["itens"][0]), {"nome", "situacao", "detalhe", "obrigatorio", "codigo", "acao"})


class TestPrivacidadeDoMicrofone(unittest.TestCase):
    def test_permitido(self):
        self.assertEqual(verificar.avaliar_privacidade(None, None, None).situacao, OK)
        self.assertEqual(verificar.avaliar_privacidade("Allow", "Allow", "Allow").situacao, OK)

    def test_negado_para_programas_da_area_de_trabalho(self):
        item = verificar.avaliar_privacidade("Allow", "Deny", None)
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("muda", item.detalhe)
        self.assertIn("Permitir que aplicativos da área de trabalho", item.acao)
        self.assertFalse(item.obrigatorio)

    def test_negado_em_geral_e_no_computador(self):
        self.assertIn("configurações de privacidade", verificar.avaliar_privacidade("Deny", None, None).detalhe)
        self.assertIn("todo o computador", verificar.avaliar_privacidade(None, None, "Deny").detalhe)

    def test_fora_do_windows_nao_se_aplica(self):
        if sys.platform == "win32":
            self.skipTest("só fora do Windows")
        item = verificar.checar_privacidade_microfone()
        self.assertEqual(item.situacao, AVISO)
        self.assertIn("Não se aplica", item.detalhe)


class TestSonda(unittest.TestCase):
    """O processo à parte: erro de import, queda e trava."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        pasta = Path(self.tmp.name)
        (pasta / "queda_assessor_teste.py").write_text("import os\nos._exit(3)\n", encoding="utf-8")
        (pasta / "trava_assessor_teste.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        self.extra = [str(pasta)]

    def tearDown(self):
        self.tmp.cleanup()

    def test_ok_e_erro(self):
        r = verificar.sondar_importacoes(["json", "modulo_que_nao_existe_assessor"])
        self.assertTrue(r["json"]["ok"])
        self.assertFalse(r["modulo_que_nao_existe_assessor"]["ok"])
        self.assertIn("ModuleNotFoundError", r["modulo_que_nao_existe_assessor"]["erro"])

    def test_queda_aponta_o_culpado_e_segue(self):
        r = verificar.sondar_importacoes(["json", "queda_assessor_teste", "csv"], extra_pythonpath=self.extra)
        self.assertTrue(r["json"]["ok"])
        self.assertFalse(r["queda_assessor_teste"]["ok"])
        self.assertTrue(r["queda_assessor_teste"]["queda"])
        self.assertIn("caiu", r["queda_assessor_teste"]["erro"])
        self.assertTrue(r["csv"]["ok"], "o módulo depois da queda tem de ser tentado de novo")

    def test_trava_vira_diagnostico(self):
        r = verificar.sondar_importacoes(["trava_assessor_teste", "json"], limite_s=3,
                                         extra_pythonpath=self.extra)
        self.assertFalse(r["trava_assessor_teste"]["ok"])
        self.assertIn("travou", r["trava_assessor_teste"]["erro"])
        self.assertTrue(r["json"]["ok"])

    def test_explicar_queda(self):
        self.assertIn("AVX", verificar.explicar_queda(0xC000001D))
        self.assertIn("DLL não encontrada", verificar.explicar_queda(-1073741515))  # 0xC0000135 com sinal
        self.assertIn("violação", verificar.explicar_queda(-11))
        self.assertIn("travou", verificar.explicar_queda(None))
        self.assertIn("0xC0001234", verificar.explicar_queda(0xC0001234))
        self.assertIn("código 5", verificar.explicar_queda(5))


class TestChecagens(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)
        self.cfg = cfg_temporaria(self.pasta)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pastas_gravaveis(self):
        item = verificar.checar_pastas(self.cfg)
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertTrue((self.pasta / "Acervo" / "Processos").is_dir())
        self.assertTrue((self.pasta / "Acervo" / "Transcricoes").is_dir())
        self.assertTrue((self.pasta / "Sigilosos").is_dir())
        self.assertEqual(list((self.pasta / "Acervo").glob(".teste-*")), [], "o arquivo de teste ficou para trás")

    @unittest.skipIf(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "permissão de pasta só se testa assim como usuário comum no POSIX")
    def test_pasta_sem_permissao(self):
        bloqueada = self.pasta / "bloqueada"
        bloqueada.mkdir()
        os.chmod(bloqueada, 0o500)
        try:
            self.cfg.definir("geral", "pasta_acervo", str(bloqueada / "Acervo"))
            item = verificar.checar_pastas(self.cfg)
        finally:
            os.chmod(bloqueada, 0o700)
        self.assertEqual(item.situacao, FALHA)
        self.assertTrue(item.obrigatorio)
        self.assertIn("Acesso controlado a pastas", item.acao)

    def test_modelo_presente_ou_ausente(self):
        try:
            from app.transcricao import modelos
        except ImportError:
            self.skipTest("módulo de modelos indisponível")
        antes = modelos.PASTA
        modelos.PASTA = self.pasta / "modelos"
        try:
            item = verificar.checar_modelo(self.cfg)
            self.assertEqual(item.situacao, AVISO)
            self.assertFalse(item.obrigatorio)
            self.assertIn("small", item.detalhe)
            self.assertIn("484 MB", item.acao)
            teste = verificar.checar_teste_transcricao(self.cfg)
            self.assertEqual(teste.situacao, AVISO)
            self.assertIn("Pulado", teste.detalhe)

            pasta = modelos.PASTA / "whisper-small"
            pasta.mkdir(parents=True)
            (pasta / "model.bin").write_bytes(b"\0" * 1_100_000)
            (pasta / "config.json").write_text("{}", encoding="utf-8")
            (pasta / "tokenizer.json").write_text("{}", encoding="utf-8")
            item = verificar.checar_modelo(self.cfg)
            self.assertEqual(item.situacao, OK, item.detalhe)
            self.assertIn("medium", item.detalhe)   # o da revisão, ainda por baixar
        finally:
            modelos.PASTA = antes

    def test_cofre(self):
        item = verificar.checar_cofre()
        if sys.platform == "win32":
            self.assertEqual(item.situacao, OK, item.detalhe)
            self.assertIn("DPAPI", item.detalhe)
        else:
            self.assertEqual(item.situacao, AVISO)
            self.assertIn("Não se aplica", item.detalhe)
        self.assertFalse(item.obrigatorio)

    def test_tribunais(self):
        item = verificar.checar_tribunais()
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertRegex(item.detalhe, r"^\d+ tribunais no catálogo; \d+ com e-SAJ ou eProc\.$")

    def test_bibliotecas_faltando(self):
        falsas = verificar.BIBLIOTECAS + (("modulo_inexistente_assessor", "pacote-inexistente", "teste"),)
        with mock.patch.object(verificar, "BIBLIOTECAS", falsas):
            item = verificar.checar_bibliotecas()
        self.assertEqual(item.situacao, FALHA)
        self.assertIn("pacote-inexistente (teste)", item.detalhe)
        self.assertIn("INSTALAR.bat", item.acao)

    def test_nativos_com_modulo_simples(self):
        with mock.patch.object(verificar, "NATIVOS", ("json",)):
            item = verificar.checar_nativos()
        self.assertEqual(item.situacao, OK, item.detalhe)
        self.assertEqual(item.detalhe, "O componente carregou.")

    def test_sem_navegador(self):
        with mock.patch.object(verificar, "_navegadores_instalados", return_value=("", "")), \
                mock.patch.object(verificar, "_chromium_proprio", return_value=""):
            item = verificar.checar_navegador(self.cfg)
        if sys.platform == "win32":
            self.assertEqual((item.situacao, item.obrigatorio), (FALHA, True))
            self.assertIn("Microsoft Edge", item.acao)
        else:
            self.assertEqual(item.situacao, AVISO)

    def test_navegador_encontrado(self):
        with mock.patch.object(verificar, "_navegadores_instalados", return_value=("", "C:/edge/msedge.exe")), \
                mock.patch.object(verificar, "_chromium_proprio", return_value=""):
            item = verificar.checar_navegador(self.cfg)
        self.assertEqual(item.situacao, OK)
        self.assertEqual(item.detalhe, "Disponível: Microsoft Edge.")

    def test_falantes(self):
        with mock.patch.object(verificar, "_falantes_situacao",
                               return_value=(False, "não instalada (falta o componente sherpa-onnx)")):
            item = verificar.checar_falantes()
        self.assertEqual((item.situacao, item.obrigatorio), (AVISO, False))
        self.assertTrue(item.detalhe.startswith("Não instalada (falta o componente sherpa-onnx):"), item.detalhe)
        with mock.patch.object(verificar, "_falantes_situacao", return_value=(True, "instalada")):
            self.assertEqual(verificar.checar_falantes().situacao, OK)

    def test_checagem_que_quebra_vira_item(self):
        def quebra():
            raise RuntimeError("inesperado")

        with self.assertLogs("verificar", level="ERROR"):
            item = verificar._protegido("Teste", quebra)
        self.assertEqual((item.nome, item.situacao, item.obrigatorio), ("Teste", FALHA, False))
        self.assertIn("RuntimeError: inesperado", item.detalhe)


class TestVerificacaoInteira(unittest.TestCase):
    """A verificação de verdade, neste computador: nunca quebra, nunca trava."""

    def test_roda_e_devolve_itens_validos(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_temporaria(Path(tmp))
            recebidos: list[Item] = []
            itens = verificar.verificar(cfg=cfg, ao_item=recebidos.append)
        self.assertEqual(itens, recebidos, "ao_item recebe tudo, na ordem")
        nomes = [i.nome for i in itens]
        self.assertEqual(len(nomes), len(set(nomes)))
        for esperado in ("Python e janela (Tk)", "Bibliotecas", "Componentes nativos (DLLs)",
                         "Modelo de transcrição", "Navegador", "Microfone", "Permissão do microfone",
                         "Pastas de trabalho", "Local da pasta", "Espaço em disco", "Cofre de senhas",
                         "Catálogo de tribunais", "Separação de falantes (opcional)"):
            self.assertIn(esperado, nomes)
        for i in itens:
            self.assertIn(i.situacao, verificar.SITUACOES, i)
            self.assertTrue(i.detalhe, i)
            if i.situacao != OK and i.acao:
                self.assertTrue(i.acao.rstrip().endswith((".", ")")), i.acao)
        if sys.platform != "win32":
            # Fora do Windows nada que é só do Windows pode reprovar.
            for i in itens:
                if i.nome in ("Cofre de senhas", "Permissão do microfone"):
                    self.assertEqual(i.situacao, AVISO)

    def test_pode_rodar_fora_da_thread_principal(self):
        # A janela chama a verificação de uma thread de trabalho.
        resultado: list = []
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cfg_temporaria(Path(tmp))
            with mock.patch.object(verificar, "_etapas",
                                   return_value=[("Pastas de trabalho", lambda: verificar.checar_pastas(cfg)),
                                                 ("Python e janela (Tk)", verificar.checar_python)]):
                t = threading.Thread(target=lambda: resultado.extend(verificar.verificar(cfg=cfg)))
                t.start()
                t.join(120)
        self.assertEqual([i.nome for i in resultado], ["Pastas de trabalho", "Python e janela (Tk)"])


class TestLinhaDeComando(unittest.TestCase):
    def _main(self, argv, itens=None):
        saida = io.StringIO()
        patches = [mock.patch("app.nucleo.registro.configurar")]
        if itens is not None:
            def falso(completo=False, cfg=None, ao_item=None):
                for i in itens:
                    if ao_item:
                        ao_item(i)
                return list(itens)
            patches.append(mock.patch.object(verificar, "verificar", side_effect=falso))
        with contextlib.ExitStack() as pilha:
            for p in patches:
                pilha.enter_context(p)
            pilha.enter_context(contextlib.redirect_stdout(saida))
            codigo = verificar.main(argv)
        return codigo, saida.getvalue()

    def test_opcoes_invalidas(self):
        self.assertEqual(self._main(["--nao-existe"])[0], 2)
        codigo, texto = self._main(["--json"])
        self.assertEqual(codigo, 2)
        self.assertIn("Faltou o nome do arquivo", texto)

    def test_ajuda_em_portugues(self):
        codigo, texto = self._main(["--ajuda"])
        self.assertEqual(codigo, 0)
        self.assertIn("Uso: python -m app verificar", texto)
        self.assertIn("Código de saída", texto)

    def test_json_e_codigo_de_saida(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "sub" / "verificacao.json"
            codigo, texto = self._main(["--completo", "--json", str(destino)],
                                       [Item("A", OK, "certo"), Item("B", AVISO, "atenção", False, acao="Faça x.")])
            self.assertEqual(codigo, 0)
            dados = json.loads(destino.read_text(encoding="utf-8"))
            self.assertEqual(dados["resultado"], AVISO)
            self.assertTrue(dados["completo"])
            self.assertEqual([i["nome"] for i in dados["itens"]], ["A", "B"])
            self.assertEqual(dados["itens"][1]["detalhe"], "atenção")
        self.assertIn("verificação completa", texto)
        self.assertIn("O que fazer: Faça x.", texto)
        self.assertIn("A instalação está pronta, com avisos", texto)

    def test_falha_obrigatoria_reprova(self):
        codigo, texto = self._main([], [Item("A", FALHA, "quebrado", acao="Conserte.")])
        self.assertEqual(codigo, 1)
        self.assertIn("A instalação tem problemas", texto)
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "v.json"
            codigo, _ = self._main([f"--json={destino}"], [Item("A", FALHA, "opcional", obrigatorio=False)])
            self.assertEqual(json.loads(destino.read_text(encoding="utf-8"))["resultado"], AVISO)
        self.assertEqual(codigo, 0)


if __name__ == "__main__":
    unittest.main()
