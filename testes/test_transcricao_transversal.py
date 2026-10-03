"""Regressões da revisão transversal da transcrição.

Cada teste prende um defeito que só aparecia cruzando módulos: o aviso do
documento que afirmava uma marcação de falantes inexistente, o pip do
componente de falantes herdando PYTHONHOME e pip.ini do usuário, a
transcrição de processo em segredo de justiça gravada no acervo
compartilhado com a IA e a nuvem, e uma segunda janela do programa
oferecendo "recuperar" a audiência que a primeira está gravando.
"""

from __future__ import annotations

import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from helestron.nucleo import cnj
from helestron.transcricao import ao_vivo, cli, documento, falantes
from helestron.transcricao.ao_vivo import SessaoAoVivo, recuperar, recuperaveis
from helestron.transcricao.arquivo import transcrever_arquivo
from helestron.transcricao.documento import Fala, MetaAudiencia, gerar_docx
from testes.apoio_transcricao import (NUMERO, ModeloDuble, PastaTemporaria, gravar_wav,
                                     ler_docx, montar)


class _CapturaParada:
    """Fonte de áudio que não entrega nada."""

    tempo_real = True

    def iniciar(self):
        pass

    def parar(self):
        pass


def _aviso(paragrafos: list[str]) -> str:
    return next(p for p in paragrafos if p.startswith("Transcrição produzida automaticamente"))


# ================================================================ documento
class TestAvisoDoDocumento(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria()
        self.destino = self.tmp.raiz / f"{NUMERO}.docx"

    def tearDown(self):
        self.tmp.apagar()

    def test_gravacao_sem_rotulos_nao_diz_que_a_marcacao_foi_feita(self):
        falas = [Fala(1.0, 3.0, "", "Fala sem separação de vozes."),
                 Fala(4.0, 6.0, "", "Outra fala.")]
        meta = MetaAudiencia(numero=NUMERO, origem="gravação")
        paragrafos, _, _ = ler_docx(gerar_docx(self.destino, falas, meta))
        aviso = _aviso(paragrafos)
        self.assertEqual(aviso, documento.AVISO_SEM_FALANTE)
        self.assertNotIn("marcada durante a audiência", aviso)
        self.assertIn("sem indicação de quem fala", aviso)

    def test_so_a_marca_de_pausa_tambem_e_sem_falante(self):
        falas = [Fala(3.0, 3.0, "", "(Gravação pausada às 10:00:00 e retomada às 10:05:00.)")]
        paragrafos, _, _ = ler_docx(gerar_docx(self.destino, falas, MetaAudiencia(numero=NUMERO)))
        self.assertEqual(_aviso(paragrafos), documento.AVISO_SEM_FALANTE)

    def test_rotulos_marcados_mantem_o_aviso_da_marcacao(self):
        falas = [Fala(1.0, 2.0, "Juiz(a)", "Aberta a audiência."),
                 Fala(3.0, 4.0, "", "Sem rótulo.")]
        paragrafos, _, _ = ler_docx(gerar_docx(self.destino, falas, MetaAudiencia(numero=NUMERO)))
        self.assertEqual(_aviso(paragrafos), documento.AVISO_MANUAL)

    def test_rotulos_automaticos_mantem_o_aviso_da_similaridade(self):
        falas = [Fala(1.0, 2.0, "FALANTE 1", "Um."), Fala(3.0, 4.0, "FALANTE 2", "Dois.")]
        meta = MetaAudiencia(numero=NUMERO, origem="gravação")
        paragrafos, _, _ = ler_docx(gerar_docx(self.destino, falas, meta))
        self.assertEqual(_aviso(paragrafos), documento.AVISO_AUTOMATICO)


# ================================================================= falantes
class TestComponenteDeFalantes(unittest.TestCase):
    def test_mensagens_citam_o_botao_como_ele_se_chama(self):
        with mock.patch.object(falantes, "PASTA", Path("/caminho/que/nao/existe")):
            with self.assertRaises(falantes.ComponenteAusente) as ctx:
                falantes.diarizar(np.zeros(16000, dtype=np.float32))
        self.assertIn("Configurações > Transcrição > Instalar o componente", str(ctx.exception))

    def test_ajuda_da_cli_usa_o_tamanho_unico(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["falantes", "--help"])
        self.assertIn(f"cerca de {falantes.TAMANHO_MB} MB", saida.getvalue())
        self.assertNotIn("47 MB", saida.getvalue())

    def test_pip_nao_herda_pythonhome_nem_pip_ini_do_usuario(self):
        chamadas = []

        def rodar(cmd, **kw):
            chamadas.append((cmd, kw["env"]))
            return mock.Mock(returncode=0, stdout="", stderr="")

        sujo = {"PYTHONHOME": r"C:\ArcGIS\Pro\bin\Python", "PYTHONPATH": r"C:\outro",
                "PIP_USER": "1", "PIP_TARGET": r"C:\alvo", "PIP_PREFIX": r"C:\prefixo",
                "PIP_CONFIG_FILE": r"C:\Users\x\pip.ini", "VIRTUAL_ENV": r"C:\venv"}
        with mock.patch.dict(os.environ, sujo), \
                mock.patch.object(falantes.subprocess, "run", side_effect=rodar):
            falantes._instalar_biblioteca(lambda f, t: None)
            # o ambiente do próprio programa não muda
            self.assertEqual(os.environ.get("PYTHONHOME"), sujo["PYTHONHOME"])
        (cmd, env), = chamadas
        for variavel in ("PYTHONHOME", "PYTHONPATH", "PIP_USER", "PIP_TARGET", "PIP_PREFIX",
                         "VIRTUAL_ENV"):
            self.assertNotIn(variavel, env)
        self.assertEqual(env["PIP_CONFIG_FILE"], os.devnull)
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(cmd[1:4], ["-s", "-m", "pip"])
        self.assertIn("--require-hashes", cmd)


# ================================================================== sigilo
class BaseSigilo(unittest.TestCase):
    def setUp(self):
        self.tmp = PastaTemporaria(salvar_audio="true")
        self.cfg = self.tmp.config()
        self.sigilosas = self.cfg.pasta_sigilosos / "Transcricoes"

    def tearDown(self):
        self.tmp.apagar()

    def autos_sigilosos(self, nome: str = NUMERO, lote: str | None = "Lote 1") -> Path:
        pasta = self.cfg.pasta_sigilosos / lote if lote else self.cfg.pasta_sigilosos
        pasta.mkdir(parents=True, exist_ok=True)
        pdf = pasta / f"{nome}.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        return pdf

    def sessao(self, eventos=None, **kw):
        return SessaoAoVivo(NUMERO, self.cfg, eventos or (lambda t, d: None),
                            captura_fabrica=lambda *a: _CapturaParada(),
                            motor_fabrica=lambda: ModeloDuble(), falante="Juiz(a)", **kw)

    def nada_no_acervo(self):
        acervo = self.cfg.pasta_acervo
        sobras = [p for p in acervo.rglob("*") if p.is_file()] if acervo.exists() else []
        self.assertEqual(sobras, [])


class TestSigiloAoVivo(BaseSigilo):
    def test_autos_na_pasta_de_sigilosos_levam_a_audiencia_para_la(self):
        self.autos_sigilosos()
        eventos = []
        s = self.sessao(lambda t, d: eventos.append((t, d)))
        s.iniciar()
        final = s.encerrar()
        self.assertTrue(s.sigiloso)
        self.assertEqual(final, self.sigilosas / f"{NUMERO}.docx")
        self.assertEqual(s.caminho_audio.parent, self.sigilosas / "_audio")
        self.assertEqual(s.caminho_diario.parent, self.sigilosas / "_audio")
        self.assertTrue(s.caminho_audio.exists() and s.caminho_diario.exists())
        self.nada_no_acervo()
        avisos = [d for t, d in eventos if t == "aviso"]
        self.assertTrue(any("segredo de justiça" in a and "pasta dos sigilosos" in a
                            for a in avisos), avisos)

    def test_pdf_solto_na_pasta_de_sigilosos_tambem_conta(self):
        self.autos_sigilosos(lote=None)
        s = self.sessao()
        s.iniciar()
        self.assertEqual(s.encerrar().parent, self.sigilosas)

    def test_informado_na_tela_sem_autos_baixados(self):
        s = self.sessao(sigiloso=True)
        s.iniciar()
        self.assertEqual(s.encerrar().parent, self.sigilosas)
        self.nada_no_acervo()

    def test_incidente_sigiloso_nao_muda_o_principal(self):
        self.autos_sigilosos(f"{NUMERO}-01")
        s = self.sessao()
        s.iniciar()
        self.assertEqual(s.encerrar(), self.cfg.pasta_transcricoes / f"{NUMERO}.docx")
        self.assertFalse(s.sigiloso)
        self.assertTrue(documento.processo_sigiloso(self.cfg,
                                                    cnj.ler_nome_arquivo(f"{NUMERO}-01")))

    def test_interrompida_na_pasta_de_sigilosos_e_recuperavel_la(self):
        self.autos_sigilosos()
        s = self.sessao()
        s.iniciar()
        try:
            s._flac.write(np.full(16000, 1e-3, dtype=np.float32))   # 1 s gravado
            s._registrar(Fala(1.0, 2.0, "Juiz(a)", "Aberta a audiência."))
            # "queda": o diário fica sem o registro de fim e a trava é solta
            s._diario.close()
            s._diario = None
            with ao_vivo._trava_ativos:
                ao_vivo._ativos.discard(ao_vivo._chave(s.caminho_diario))
            ao_vivo._soltar(s._trava_processo)
            s._trava_processo = None
        finally:
            s._fila.put(None)
            s._trabalhador.join(10)
            s._fechar_audio()
        self.assertEqual(recuperaveis(self.cfg), [s.caminho_diario])
        caminho = recuperar(s.caminho_diario)
        self.assertEqual(caminho, self.sigilosas / f"{NUMERO}.docx")
        self.assertIn("Juiz(a) [00:00:01] — Aberta a audiência.", ler_docx(caminho)[0])
        self.assertEqual(recuperaveis(self.cfg), [])
        self.assertFalse(s.caminho_diario.with_suffix(ao_vivo.SUFIXO_TRAVA).exists())
        self.nada_no_acervo()


class TestSigiloGravacao(BaseSigilo):
    def setUp(self):
        super().setUp()
        self.audio = montar([("silencio", 0.5), ("fala", 2.0, 200), ("silencio", 1.0)])
        self.wav = gravar_wav(self.tmp.raiz / f"{NUMERO}.wav", self.audio)

    def test_gravacao_de_processo_sigiloso_vai_para_a_pasta_dos_sigilosos(self):
        self.autos_sigilosos()
        caminho = transcrever_arquivo(self.wav, None, self.cfg, separar=False,
                                      motor_fabrica=lambda: ModeloDuble())
        self.assertEqual(caminho, self.sigilosas / f"{NUMERO}.docx")
        self.nada_no_acervo()

    def test_gravacao_informada_como_sigilosa(self):
        caminho = transcrever_arquivo(self.wav, None, self.cfg, separar=False, sigiloso=True,
                                      motor_fabrica=lambda: ModeloDuble())
        self.assertEqual(caminho.parent, self.sigilosas)

    def test_gravacao_guardada_na_pasta_dos_sigilosos_e_sigilosa(self):
        # o "Revisar agora" de uma audiência sigilosa: a gravação está lá
        pasta = self.sigilosas / "_audio"
        pasta.mkdir(parents=True)
        wav = gravar_wav(pasta / f"{NUMERO} 2026-09-16 14h00.wav", self.audio)
        caminho = transcrever_arquivo(wav, None, self.cfg, separar=False,
                                      motor_fabrica=lambda: ModeloDuble())
        self.assertEqual(caminho, self.sigilosas / f"{NUMERO}.docx")
        self.nada_no_acervo()

    def test_gravacao_comum_continua_no_acervo(self):
        caminho = transcrever_arquivo(self.wav, None, self.cfg, separar=False,
                                      motor_fabrica=lambda: ModeloDuble())
        self.assertEqual(caminho, self.cfg.pasta_transcricoes / f"{NUMERO}.docx")
        self.assertFalse(self.sigilosas.exists())


# ======================================================= duas instâncias
class TestOutraJanelaDoPrograma(BaseSigilo):
    """A sessão aberta em outro processo: o _ativos de cada processo não a vê,
    e a trava do sistema operacional, sim (no mesmo processo, outra abertura
    do arquivo conflita do mesmo jeito: flock no Linux, LockFile no Windows)."""

    def test_audiencia_em_gravacao_noutra_janela_nao_e_recuperavel(self):
        s = self.sessao()
        s.iniciar()
        try:
            # a segunda janela não tem esta sessão no seu registro
            with ao_vivo._trava_ativos:
                ao_vivo._ativos.discard(ao_vivo._chave(s.caminho_diario))
            self.assertTrue(ao_vivo._em_uso(s.caminho_diario))
            self.assertEqual(recuperaveis(self.cfg), [])
            antes = s.caminho_diario.read_bytes()
            with self.assertRaises(RuntimeError) as ctx:
                recuperar(s.caminho_diario)
            self.assertIn("outra janela", str(ctx.exception))
            self.assertEqual(s.caminho_diario.read_bytes(), antes)   # nenhum "fim" no meio
        finally:
            with ao_vivo._trava_ativos:
                ao_vivo._ativos.add(ao_vivo._chave(s.caminho_diario))
            s.encerrar()
        trava = s.caminho_diario.with_suffix(ao_vivo.SUFIXO_TRAVA)
        self.assertFalse(trava.exists())
        self.assertFalse(ao_vivo._em_uso(s.caminho_diario))

    def test_trava_velha_de_programa_que_caiu_nao_impede_recuperar(self):
        s = self.sessao()
        s.iniciar()
        try:
            s._flac.write(np.full(16000, 1e-3, dtype=np.float32))   # 1 s gravado
            s._diario.close()
            s._diario = None
            with ao_vivo._trava_ativos:
                ao_vivo._ativos.discard(ao_vivo._chave(s.caminho_diario))
            ao_vivo._soltar(s._trava_processo)       # o sistema solta ao matar o processo
            s._trava_processo = None
        finally:
            s._fila.put(None)
            s._trabalhador.join(10)
            s._fechar_audio()
        trava = s.caminho_diario.with_suffix(ao_vivo.SUFIXO_TRAVA)
        self.assertTrue(trava.exists())
        self.assertFalse(ao_vivo._em_uso(s.caminho_diario))
        self.assertEqual(recuperaveis(self.cfg), [s.caminho_diario])
        recuperar(s.caminho_diario)
        self.assertFalse(trava.exists())

    def test_inicio_que_falha_solta_a_trava(self):
        class SemMicrofone(_CapturaParada):
            def iniciar(self):
                raise RuntimeError("sem microfone")

        s = SessaoAoVivo(NUMERO, self.cfg, lambda t, d: None,
                         captura_fabrica=lambda *a: SemMicrofone(),
                         motor_fabrica=lambda: ModeloDuble())
        with self.assertRaises(RuntimeError):
            s.iniciar()
        self.assertIsNone(s._trava_processo)
        self.assertFalse(s.caminho_diario.with_suffix(ao_vivo.SUFIXO_TRAVA).exists())


if __name__ == "__main__":
    unittest.main()
