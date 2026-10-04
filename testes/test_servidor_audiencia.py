"""Audiências pela API: transcrição ao vivo (sessão simulada), gravação, microfone e modelos."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest import mock

from helestron.transcricao.documento import Fala
from helestron.transcricao.microfone import Entrada

from testes.test_servidor_base import ServidorDeTeste

NUMERO = "0700123-83.2024.8.02.0001"


class SessaoFalsa:
    """Imita a SessaoAoVivo: mesmos métodos e os mesmos eventos."""

    criadas: list = []

    def __init__(self, numero, cfg, eventos, *, tipo="", participantes=None, falante="",
                 sigiloso=False, dispositivo=None):
        self.numero = numero
        self.cfg = cfg
        self.eventos = eventos
        self.kw = {"tipo": tipo, "participantes": participantes, "falante": falante,
                   "sigiloso": sigiloso, "dispositivo": dispositivo}
        self.falas: list[Fala] = []
        self.estado = "parada"
        self.tempo = 0.0
        self.modelo = "small"
        self.pendentes = 0
        self.falante = falante
        self.sigiloso = sigiloso
        self.refinar = None
        pasta = Path(cfg.pasta_sigilosos if sigiloso else cfg.pasta_transcricoes)
        self.pasta = pasta
        self.caminho_audio = pasta / "_audio" / f"{numero.nome_arquivo}.flac"
        SessaoFalsa.criadas.append(self)

    def iniciar(self):
        self.caminho_audio.parent.mkdir(parents=True, exist_ok=True)
        self.caminho_audio.write_bytes(b"fLaC")
        self.estado = "gravando"
        self.tempo = 2.5
        self.eventos("estado", "Gravando")
        self.eventos("nivel", 0.42)
        fala = Fala(0.5, 2.0, self.falante, "Bom dia a todos.")
        self.falas.append(fala)
        self.eventos("fala", fala)

    def pausar(self):
        self.estado = "pausada"
        self.eventos("estado", "Pausado")

    def retomar(self):
        self.estado = "gravando"
        self.eventos("estado", "Gravando")

    def definir_falante(self, rotulo):
        self.falante = rotulo

    def cancelar(self):
        pass

    def encerrar(self, refinar=False):
        self.refinar = refinar
        self.estado = "encerrando"
        documento = self.pasta / f"{self.numero.nome_arquivo}.docx"
        documento.write_bytes(b"PK docx")
        self.eventos("salvo", documento)
        self.estado = "encerrada"
        self.eventos("estado", "Concluído")
        self.eventos("fim", documento)
        return documento


class TestAoVivo(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        SessaoFalsa.criadas = []
        p = mock.patch("helestron.servicos.nova_sessao", side_effect=SessaoFalsa)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("helestron.servicos.atualizar_indice")
        self.indice = p.start()
        self.addCleanup(p.stop)

    def test_sessao_completa(self):
        leitor = self.eventos()
        dados = self.cliente.dados("POST", "/api/transcricao/iniciar", {
            "processo": "07001238320248020001", "dispositivo": "3", "sigiloso": False,
            "tipo": "Instrução e julgamento", "participantes": {"F1": "Juiz(a)", "F2": ""},
            "falante": "Juiz(a)"})
        self.assertEqual(dados["processo"], NUMERO)
        self.assertTrue(dados["sessao"])
        sessao = SessaoFalsa.criadas[0]
        self.assertEqual(sessao.kw["dispositivo"], 3)
        self.assertEqual(sessao.kw["participantes"], {"F1": "Juiz(a)"})
        fala = leitor.esperar("transcricao", lambda d: d["tipo"] == "fala")["dados"]
        self.assertEqual(fala["texto"], "Bom dia a todos.")
        self.assertEqual(fala["falante"], "Juiz(a)")
        self.assertEqual(set(fala) >= {"inicio", "fim", "falante", "texto"}, True)
        leitor.esperar("transcricao", lambda d: d["tipo"] == "nivel")
        leitor.esperar("transcricao", lambda d: d["tipo"] == "estado"
                       and d["dados"]["estado"] == "gravando")
        estado = self.cliente.dados("GET", "/api/transcricao/estado")
        self.assertEqual((estado["processo"], estado["segundos"]), (NUMERO, 2.5))
        self.assertEqual(estado["falas"][0]["hora"], "00:00:00")
        # uma sessão por vez
        status, env = self.cliente.post("/api/transcricao/iniciar", {"processo": NUMERO})
        self.assertEqual(status, 409)
        self.assertEqual(env["erro"]["codigo"], "sessao_ativa")
        # o microfone está com a audiência
        status, _ = self.cliente.post("/api/transcricao/microfone/teste", {})
        self.assertEqual(status, 409)
        self.cliente.dados("POST", "/api/transcricao/pausar")
        leitor.esperar("transcricao", lambda d: d["tipo"] == "estado"
                       and d["dados"]["estado"] == "pausada")
        self.cliente.dados("POST", "/api/transcricao/retomar")
        self.cliente.dados("POST", "/api/transcricao/falante", {"falante": "Testemunha"})
        self.assertEqual(sessao.falante, "Testemunha")
        fim = self.cliente.dados("POST", "/api/transcricao/encerrar", {"refinar": False})
        documento = self.amb.dados / "Acervo" / "Transcricoes" / "0700123-83.2024.8.02.0001.docx"
        self.assertEqual(fim["documento"], str(documento))
        self.assertIs(sessao.refinar, False)
        leitor.esperar("transcricao", lambda d: d["tipo"] == "fim"
                       and d["dados"]["documento"] == str(documento))
        self.assertTrue(self.app.audiencia.ultima)
        self.cfg.recarregar()
        self.assertEqual(self.cfg.texto("interface", "ultimo_processo"), NUMERO)
        # o índice do acervo é refeito depois de salvar
        limite = time.monotonic() + 5
        while not self.indice.called and time.monotonic() < limite:
            time.sleep(0.02)
        self.indice.assert_called()
        status, env = self.cliente.post("/api/transcricao/pausar")
        self.assertEqual(status, 409)
        # o microfone ficou livre
        self.assertIsNone(self.app.recursos.quem_tem("microfone"))

    def test_numero_invalido(self):
        status, env = self.cliente.post("/api/transcricao/iniciar", {"processo": "123"})
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "numero_invalido")
        status, env = self.cliente.post("/api/transcricao/iniciar", {})
        self.assertEqual(env["erro"]["codigo"], "numero_ausente")

    def test_sigilo_presumido_pelos_autos(self):
        with mock.patch("helestron.servicos.processo_sigiloso", return_value=True):
            dados = self.cliente.dados("POST", "/api/transcricao/iniciar", {"processo": NUMERO})
        self.assertTrue(dados["sigiloso"])
        self.assertTrue(SessaoFalsa.criadas[0].kw["sigiloso"])
        self.cliente.dados("POST", "/api/transcricao/encerrar")

    def test_falha_ao_iniciar_solta_o_microfone(self):
        class Quebra(SessaoFalsa):
            def iniciar(self):
                raise RuntimeError("microfone indisponível")

        with mock.patch("helestron.servicos.nova_sessao", side_effect=Quebra):
            leitor = self.eventos()
            self.cliente.dados("POST", "/api/transcricao/iniciar", {"processo": NUMERO})
            erro = leitor.esperar("transcricao", lambda d: d["tipo"] == "erro")
            # A tela sai do "Gravando": o estado diz que a gravação não começou.
            estado = leitor.esperar("transcricao", lambda d: d["tipo"] == "estado"
                                    and d["dados"].get("estado") == "erro")
        self.assertEqual(erro["dados"]["texto"], "Microfone indisponível")
        self.assertEqual(estado["dados"], {"texto": "Microfone indisponível", "estado": "erro",
                                           "fase": "inicio"})
        atual = self.cliente.dados("GET", "/api/transcricao/estado")
        self.assertEqual((atual["estado"], atual["erro"]), ("erro", "Microfone indisponível"))
        limite = time.monotonic() + 5
        while self.app.recursos.quem_tem("microfone") and time.monotonic() < limite:
            time.sleep(0.02)
        self.assertIsNone(self.app.recursos.quem_tem("microfone"))

    def test_fechar_o_programa_salva_a_audiencia(self):
        self.cliente.dados("POST", "/api/transcricao/iniciar", {"processo": NUMERO})
        sessao = SessaoFalsa.criadas[0]
        self.assertIn("Audiência", self.app.trabalho_em_andamento()[0])
        self.app.encerrar(espera_tarefas_s=5, espera_audiencia_s=5)
        self.assertEqual(sessao.estado, "encerrada")
        self.assertIs(sessao.refinar, False)


class TestGravacaoERecuperacao(ServidorDeTeste):
    def setUp(self):
        super().setUp()
        p = mock.patch("helestron.servicos.atualizar_indice")
        p.start()
        self.addCleanup(p.stop)

    def test_envio_de_gravacao(self):
        recebidos = []

        def transcrever(origem, numero, cfg, progresso, cancelado, *, rotulos_manuais=None,
                        destino=None, tipo="", participantes=None, sigiloso=False):
            recebidos.append({"existe": Path(origem).exists(), "numero": numero.formatado,
                              "sigiloso": sigiloso, "tipo": tipo, "origem": Path(origem)})
            progresso(0.5, "Transcrevendo…")
            doc = Path(cfg.pasta_transcricoes) / f"{numero.nome_arquivo}.docx"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_bytes(b"PK")
            return doc

        with mock.patch("helestron.servicos.transcrever_gravacao", side_effect=transcrever):
            status, env = self.cliente.enviar("/api/transcricao/gravacao",
                                              f"audiencia {NUMERO}.wav", b"RIFF....WAVE",
                                              {"tipo": "Conciliação"})
            self.assertEqual(status, 200, env)
            tarefa = self.esperar_tarefa(env["dados"]["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(tarefa["tipo"], "transcricao_arquivo")
        self.assertEqual(recebidos[0]["numero"], NUMERO)
        self.assertTrue(recebidos[0]["existe"])
        self.assertEqual(recebidos[0]["tipo"], "Conciliação")
        self.assertFalse(recebidos[0]["origem"].exists())      # o envio foi apagado
        self.assertTrue(tarefa["resultado"]["documento"].endswith(".docx"))
        self.assertFalse(tarefa["resultado"]["sigiloso"])

    def test_gravacao_sem_numero_400(self):
        status, env = self.cliente.enviar("/api/transcricao/gravacao", "audio.wav", b"RIFF")
        self.assertEqual(status, 400)
        self.assertEqual(env["erro"]["codigo"], "numero_ausente")
        envios = self.app.pasta_envios()
        self.assertEqual(list(envios.glob("*")) if envios.exists() else [], [])

    def test_gravacao_por_caminho_e_processo_informado(self):
        audio = self.amb.raiz / "gravacao.mp3"
        audio.write_bytes(b"ID3")
        with mock.patch("helestron.servicos.transcrever_gravacao",
                        return_value=self.amb.raiz / "x.docx") as transcrever:
            dados = self.cliente.dados("POST", "/api/transcricao/gravacao",
                                       {"caminho": str(audio), "processo": NUMERO,
                                        "sigiloso": True})
            self.esperar_tarefa(dados["tarefa"])
        args, kw = transcrever.call_args
        self.assertEqual(args[0], audio)
        self.assertTrue(kw["sigiloso"])
        self.assertTrue(audio.exists())                         # o do usuário fica

    def test_revisao_sem_audiencia_409(self):
        status, env = self.cliente.post("/api/transcricao/gravacao", {"revisao": True})
        self.assertEqual(status, 409)

    def test_recuperacao_so_dos_achados(self):
        diario = self.amb.dados / "Acervo" / "Transcricoes" / "_audio" / f"{NUMERO} 2026.jsonl"
        diario.parent.mkdir(parents=True)
        diario.write_text("{}", encoding="utf-8")
        with mock.patch("helestron.servicos.recuperaveis", return_value=[diario]), \
                mock.patch("helestron.servicos.recuperar",
                           return_value=self.amb.raiz / "rec.docx") as recuperar:
            lista = self.cliente.dados("GET", "/api/transcricao/recuperaveis")
            self.assertEqual(lista[0]["arquivo"], str(diario))
            self.assertEqual(set(lista[0]), {"arquivo", "processo", "quando"})
            status, _ = self.cliente.post("/api/transcricao/recuperar",
                                          {"arquivo": "/etc/passwd"})
            self.assertEqual(status, 404)
            dados = self.cliente.dados("POST", "/api/transcricao/recuperar",
                                       {"arquivo": str(diario)})
        self.assertEqual(dados["documento"], str(self.amb.raiz / "rec.docx"))
        recuperar.assert_called_once_with(diario)

    def test_recentes_com_sigilosas(self):
        acervo = self.amb.dados / "Acervo" / "Transcricoes"
        sig = self.amb.dados / "Sigilosos" / "Transcricoes"
        acervo.mkdir(parents=True)
        sig.mkdir(parents=True)
        (acervo / f"{NUMERO}.docx").write_bytes(b"PK")
        (sig / "0700124-68.2024.8.02.0001.docx").write_bytes(b"PK")
        lista = self.cliente.dados("GET", "/api/transcricao/recentes")
        self.assertEqual({x["numero"]: x["sigiloso"] for x in lista},
                         {NUMERO: False, "0700124-68.2024.8.02.0001": True})


class TestMicrofoneEModelos(ServidorDeTeste):
    def test_microfones(self):
        with mock.patch("helestron.servicos.listar_microfones", return_value=[
                Entrada(1, "Microfone (USB)", True, 48000)]):
            lista = self.cliente.dados("GET", "/api/transcricao/microfones")
        self.assertEqual(lista, [{"indice": 1, "nome": "Microfone (USB)", "padrao": True}])

    def test_teste_do_microfone(self):
        captura = mock.Mock()
        niveis = {}

        def abrir(dispositivo, ao_nivel, ao_aviso=None):
            niveis["f"] = ao_nivel
            return captura

        leitor = self.eventos()
        with mock.patch("helestron.servicos.abrir_teste_microfone", side_effect=abrir):
            self.cliente.dados("POST", "/api/transcricao/microfone/teste", {"dispositivo": 2})
            niveis["f"](0.7)
            self.assertEqual(leitor.esperar("microfone_nivel")["nivel"], 0.7)
            self.assertEqual(self.app.recursos.quem_tem("microfone"), "Teste do microfone")
            self.cliente.dados("POST", "/api/transcricao/microfone/parar")
        captura.parar.assert_called_once()
        self.assertIsNone(self.app.recursos.quem_tem("microfone"))

    def test_modelos(self):
        with mock.patch("helestron.servicos.modelos_disponiveis", return_value=[
                {"nome": "small", "mb": 484, "instalado": True, "descricao": "x"},
                {"nome": "medium", "mb": 1530, "instalado": False, "embutido": False}]):
            lista = self.cliente.dados("GET", "/api/transcricao/modelos")
            self.assertEqual(lista[0]["rotulo"], "Small")
            self.assertEqual(lista[0]["recomendado_para"], ["ao_vivo"])
            self.assertEqual(set(lista[0]) >= {"nome", "rotulo", "tamanho_mb", "instalado",
                                               "embutido", "recomendado_para"}, True)
            status, _ = self.cliente.post("/api/transcricao/modelos/baixar", {"nome": "enorme"})
            self.assertEqual(status, 400)

            def baixar(nome, progresso):
                progresso(0.5, "metade")
                return self.amb.raiz / nome

            with mock.patch("helestron.servicos.baixar_modelo", side_effect=baixar):
                tarefa = self.esperar_tarefa(self.cliente.dados(
                    "POST", "/api/transcricao/modelos/baixar", {"nome": "medium"})["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida")
        self.assertEqual(tarefa["tipo"], "modelo")
        self.assertEqual(tarefa["progresso"]["percentual"], 100.0)

    def test_falantes_estado_e_download_dos_modelos_de_voz(self):
        """Construção sem os modelos de voz (--sem-falantes): Ajustes oferece baixá-los."""
        faltando = {"disponivel": False, "situacao": "incompleta (faltam os modelos de voz)",
                    "biblioteca": True, "modelos": False, "embutidos": False, "tamanho_mb": 47}
        pronto = dict(faltando, disponivel=True, situacao="instalada", modelos=True)
        estados = [faltando, faltando, pronto]
        chamadas = []

        def instalar(progresso, cancelado=None):
            chamadas.append(cancelado)
            progresso(0.5, "Baixando o modelo de voz: 20 de 40 MB")

        with mock.patch("helestron.servicos.falantes_estado", side_effect=lambda: estados.pop(0)), \
                mock.patch("helestron.servicos.instalar_falantes", side_effect=instalar):
            self.assertEqual(self.cliente.dados("GET", "/api/transcricao/falantes"), faltando)
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/transcricao/falantes/baixar")["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        self.assertEqual(tarefa["tipo"], "modelo")
        self.assertEqual(tarefa["titulo"], "Baixar os modelos de voz")
        self.assertEqual(tarefa["resultado"], pronto)
        self.assertTrue(callable(chamadas[0]))        # o Parar chega ao download

    def test_falantes_sem_a_biblioteca_409(self):
        sem = {"disponivel": False, "situacao": "indisponível", "biblioteca": False,
               "modelos": False, "embutidos": False, "tamanho_mb": 47}
        with mock.patch("helestron.servicos.falantes_estado", return_value=sem), \
                mock.patch("helestron.servicos.instalar_falantes") as instalar:
            status, corpo = self.cliente.post("/api/transcricao/falantes/baixar")
        self.assertEqual(status, 409)
        self.assertIn("Helestron-Setup", corpo["erro"]["mensagem"])
        instalar.assert_not_called()

    def test_falantes_estado_de_verdade(self):
        from helestron import servicos

        estado = servicos.falantes_estado()
        self.assertEqual(set(estado), {"disponivel", "situacao", "biblioteca", "modelos",
                                       "embutidos", "tamanho_mb"})
        self.assertEqual(estado["disponivel"], estado["biblioteca"] and estado["modelos"])


if __name__ == "__main__":
    unittest.main()
