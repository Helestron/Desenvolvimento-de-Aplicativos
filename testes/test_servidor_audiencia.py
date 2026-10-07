"""Audiências pela API: transcrição ao vivo (sessão simulada), gravação, microfone e modelos."""

from __future__ import annotations

import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from helestron.transcricao.documento import Fala, MetaAudiencia
from helestron.transcricao.microfone import Entrada, MicrofoneIndisponivel

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
        self.meta = MetaAudiencia(numero=numero.formatado, tipo=tipo,
                                  participantes=dict(participantes or {}))
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

    def test_microfone_pelo_nome(self):
        """Ajustes guarda o NOME do microfone: o número muda quando se liga ou
        desliga um aparelho USB. O nome que não existe mais é erro claro - antes,
        o número velho gravava a audiência por outro aparelho, em silêncio."""
        lista = [Entrada(2, "Microfone (Realtek(R) Audio)", True, 48000),
                 Entrada(5, "Microfone de mesa (USB)", False, 48000)]
        with mock.patch("helestron.transcricao.microfone.listar_entradas", return_value=lista):
            self.cliente.dados("POST", "/api/transcricao/iniciar", {
                "processo": NUMERO, "dispositivo": "Microfone de mesa (USB)"})
            self.assertEqual(SessaoFalsa.criadas[-1].kw["dispositivo"], "Microfone de mesa (USB)")
            self.cliente.dados("POST", "/api/transcricao/encerrar")
            status, env = self.cliente.post("/api/transcricao/iniciar", {
                "processo": NUMERO, "dispositivo": "Fone Jabra Evolve"})
            self.assertEqual(status, 409)
            self.assertEqual(env["erro"]["codigo"], "microfone_indisponivel")
            self.assertEqual(env["erro"]["mensagem"],
                             "O microfone “Fone Jabra Evolve” não foi encontrado. Escolha outro "
                             "em Audiências ou Ajustes › Transcrição.")
            self.assertEqual(len(SessaoFalsa.criadas), 1)
            self.assertIsNone(self.app.recursos.quem_tem("microfone"))
            # sem a chave, vale o da configuração (o nome), conferido do mesmo jeito
            self.cfg.definir("transcricao", "dispositivo", "Microfone de mesa (USB)")
            self.cliente.dados("POST", "/api/transcricao/iniciar", {"processo": NUMERO})
            self.assertEqual(SessaoFalsa.criadas[-1].kw["dispositivo"], "Microfone de mesa (USB)")
            self.cliente.dados("POST", "/api/transcricao/encerrar")
            self.cfg.definir("transcricao", "dispositivo", "Fone que sumiu")
            status, env = self.cliente.post("/api/transcricao/iniciar", {"processo": NUMERO})
            self.assertEqual((status, env["erro"]["codigo"]), (409, "microfone_indisponivel"))
            self.assertIn("“Fone que sumiu”", env["erro"]["mensagem"])

    def test_padrao_do_windows_escolhido_na_tela_nao_herda_a_configuracao(self):
        """A tela mostra "Padrão do Windows" e manda "": a sessão recebe "" - e
        não None, que a fazia cair no microfone (velho) do config.ini."""
        self.cfg.definir("transcricao", "dispositivo", "3")
        self.cliente.dados("POST", "/api/transcricao/iniciar",
                           {"processo": NUMERO, "dispositivo": ""})
        self.assertEqual(SessaoFalsa.criadas[-1].kw["dispositivo"], "")
        self.cliente.dados("POST", "/api/transcricao/encerrar")

    def test_sigilo_pela_pauta(self):
        """A pauta sabe que o processo corre em segredo de justiça (o portal
        disse): a transcrição sai sigilosa mesmo com o interruptor desligado,
        e a resposta diz por quê (a tela liga o interruptor e mostra o motivo)."""
        pauta = mock.Mock()
        pauta.processo_sigiloso.side_effect = lambda n: n == NUMERO
        with mock.patch.object(self.app, "pauta_ou_none", return_value=pauta):
            dados = self.cliente.dados("POST", "/api/transcricao/iniciar",
                                       {"processo": NUMERO, "sigiloso": False})
            self.assertTrue(dados["sigiloso"])
            self.assertTrue(dados["sigiloso_forcado"])
            self.assertIn("pauta", dados["motivo"])
            self.assertTrue(SessaoFalsa.criadas[-1].kw["sigiloso"])
            self.cliente.dados("POST", "/api/transcricao/encerrar")
            # pedido sigiloso: nada a forçar
            dados = self.cliente.dados("POST", "/api/transcricao/iniciar",
                                       {"processo": NUMERO, "sigiloso": True})
            self.assertEqual((dados["sigiloso"], dados["sigiloso_forcado"]), (True, False))
            self.assertNotIn("motivo", dados)
            self.cliente.dados("POST", "/api/transcricao/encerrar")
            # outro processo, que a pauta não marca
            dados = self.cliente.dados("POST", "/api/transcricao/iniciar",
                                       {"processo": "0700124-68.2024.8.02.0001",
                                        "sigiloso": False})
            self.assertEqual((dados["sigiloso"], dados["sigiloso_forcado"]), (False, False))
            self.cliente.dados("POST", "/api/transcricao/encerrar")
        # pauta que falha não impede a audiência
        pauta.processo_sigiloso.side_effect = RuntimeError("banco ocupado")
        with mock.patch.object(self.app, "pauta_ou_none", return_value=pauta):
            dados = self.cliente.dados("POST", "/api/transcricao/iniciar", {"processo": NUMERO})
        self.assertFalse(dados["sigiloso"])
        self.cliente.dados("POST", "/api/transcricao/encerrar")

    def test_encerrar_com_o_tipo_e_revisar_mantem_a_ficha(self):
        """"Revisar" mandava só {revisao: true}: o documento revisado saía com
        "Tipo de audiência: —" e sem os participantes."""
        self.cliente.dados("POST", "/api/transcricao/iniciar", {
            "processo": NUMERO, "tipo": "Conciliação",
            "participantes": {"F1": "Juiz(a)", "F2": "Autor(a)"}})
        sessao = SessaoFalsa.criadas[-1]
        # o tipo escolhido na tela ao encerrar vale para o documento
        self.cliente.dados("POST", "/api/transcricao/encerrar",
                           {"refinar": False, "tipo": "Instrução e julgamento"})
        self.assertEqual(sessao.meta.tipo, "Instrução e julgamento")
        self.assertEqual(self.app.audiencia.ultima["tipo"], "Instrução e julgamento")
        chamadas = []

        def transcrever(origem, numero, cfg, progresso, cancelado, **kw):
            chamadas.append(kw)
            return Path(cfg.pasta_transcricoes) / "rev.docx"

        with mock.patch("helestron.servicos.transcrever_gravacao", side_effect=transcrever), \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar"):
            self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/transcricao/gravacao", {"revisao": True})["tarefa"])
            self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/transcricao/gravacao", {"revisao": True, "tipo": "Una"})["tarefa"])
        self.assertEqual(chamadas[0]["tipo"], "Instrução e julgamento")
        # A ficha é a da sessão (uma cópia), e o mapa das teclas F1-F8 não é
        # lista de presença: não vira "participantes" da revisão (achado 38).
        meta = chamadas[0]["meta"]
        self.assertIsInstance(meta, MetaAudiencia)
        self.assertIsNot(meta, sessao.meta)
        self.assertEqual(meta.tipo, "Instrução e julgamento")
        self.assertEqual(meta.participantes, {})
        self.assertIsNone(chamadas[0]["participantes"])
        self.assertEqual(self.app.audiencia.ultima["botoes"], {"F1": "Juiz(a)", "F2": "Autor(a)"})
        self.assertTrue(chamadas[0]["rotulos_manuais"])
        self.assertEqual(chamadas[1]["tipo"], "Una")

    def test_revisar_leva_a_ficha_da_sessao_ao_vivo(self):
        """Achado 38: a revisão pelo "Revisar" recebia só o tipo e os
        participantes - perdia o início e o término da audiência e punha na
        Data a da modificação do FLAC (o dia seguinte, numa audiência que passa
        da meia-noite). Agora a ficha da sessão (cópia) vai a
        servicos.transcrever_gravacao, como na revisão automática ao encerrar."""

        class SessaoComFicha(SessaoFalsa):
            """Separa os botões dos participantes, como a SessaoAoVivo."""

            def __init__(self, numero, cfg, eventos, **kw):
                super().__init__(numero, cfg, eventos, **kw)
                todos = dict(kw.get("participantes") or {})
                self.botoes = {k: v for k, v in todos.items() if k.startswith("F")}
                self.meta = MetaAudiencia(
                    numero=numero.formatado, tipo=kw.get("tipo", ""), unidade="2ª Vara Cível",
                    magistrado="Camila Duarte Albuquerque",
                    participantes={k: v for k, v in todos.items() if not k.startswith("F")})

            def iniciar(self):
                super().iniciar()
                self.meta.inicio = self.meta.data = datetime(2026, 9, 16, 23, 40)

            def encerrar(self, refinar=False):
                self.meta.fim = datetime(2026, 9, 17, 0, 25)
                return super().encerrar(refinar)

        recebidas = []

        def transcrever_arquivo(origem, numero, cfg, progresso=None, cancelado=None,
                                rotulos_manuais=None, destino=None, *, meta=None, **kw):
            recebidas.append(meta)
            return Path(cfg.pasta_transcricoes) / "rev.docx"

        with mock.patch("helestron.servicos.nova_sessao", side_effect=SessaoComFicha):
            self.cliente.dados("POST", "/api/transcricao/iniciar", {
                "processo": NUMERO, "tipo": "Instrução e julgamento",
                "participantes": {"F1": "Juiz(a)", "F2": "Testemunha",
                                  "Juiz(a)": "Camila Duarte Albuquerque"}})
            sessao = SessaoFalsa.criadas[-1]
            self.cliente.dados("POST", "/api/transcricao/encerrar", {"refinar": False})
        ultima = self.app.audiencia.ultima
        self.assertEqual(ultima["botoes"], {"F1": "Juiz(a)", "F2": "Testemunha"})
        self.assertEqual(ultima["participantes"], {"Juiz(a)": "Camila Duarte Albuquerque"})
        self.assertIsNot(ultima["meta"], sessao.meta)          # cópia
        with mock.patch("helestron.transcricao.arquivo.transcrever_arquivo",
                        side_effect=transcrever_arquivo), \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar"):
            tarefa = self.esperar_tarefa(self.cliente.dados(
                "POST", "/api/transcricao/gravacao", {"revisao": True, "tipo": "Una"})["tarefa"])
        self.assertEqual(tarefa["estado"], "concluida", tarefa)
        meta = recebidas[0]
        self.assertEqual((meta.inicio, meta.fim), (datetime(2026, 9, 16, 23, 40),
                                                   datetime(2026, 9, 17, 0, 25)))
        self.assertEqual(meta.data, datetime(2026, 9, 16, 23, 40))
        self.assertEqual(meta.origem, "revisão")
        self.assertEqual(meta.tipo, "Una")                     # o da tela prevalece
        self.assertEqual(meta.participantes, {"Juiz(a)": "Camila Duarte Albuquerque"})
        self.assertEqual((meta.unidade, meta.magistrado),
                         ("2ª Vara Cível", "Camila Duarte Albuquerque"))
        # a ficha guardada não foi mexida pela revisão
        self.assertEqual(ultima["meta"].tipo, "Instrução e julgamento")
        self.assertEqual(ultima["meta"].origem, "ao vivo")

    def test_dependente_digitado_com_hifen_ou_barra(self):
        """Achado 33: "...0001-01" (como o nome dos arquivos) era lido como o
        principal pelo cnj.ler, e a audiência do incidente virava a do principal."""
        for digitado in (f"{NUMERO}-01", f"{NUMERO}/01", f"{NUMERO}/0001"):
            with self.subTest(digitado=digitado):
                dados = self.cliente.dados("POST", "/api/transcricao/iniciar",
                                           {"processo": digitado})
                self.assertEqual(dados["processo"], f"{NUMERO}/01")
                self.assertEqual(SessaoFalsa.criadas[-1].numero.dependente, "01")
                self.cliente.dados("POST", "/api/transcricao/encerrar", {"refinar": False})

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
                        destino=None, tipo="", participantes=None, sigiloso=False, **kw):
            recebidos.append({"existe": Path(origem).exists(), "numero": numero.formatado,
                              "sigiloso": sigiloso, "tipo": tipo, "origem": Path(origem),
                              "gravacao": kw.get("gravacao"), "data": kw.get("data")})
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
        # a ficha leva o nome do arquivo do usuário, e não o do temporário
        self.assertEqual(recebidos[0]["gravacao"], f"audiencia {NUMERO}.wav")
        self.assertTrue(tarefa["resultado"]["documento"].endswith(".docx"))
        self.assertFalse(tarefa["resultado"]["sigiloso"])

    def test_numero_da_gravacao_mantem_o_dependente_do_nome_ou_da_pasta(self):
        """Achado 33: o número digitado sem o dependente não apaga o "-01" que
        o programa pôs no nome da gravação (ou na pasta da mídia dos autos)."""
        from helestron.servidor.audiencia import numero_da_gravacao

        nome = f"{NUMERO}-01 2026-09-16 14h00.flac"
        self.assertEqual(numero_da_gravacao(nome, NUMERO).formatado, f"{NUMERO}/01")
        self.assertEqual(numero_da_gravacao(nome, None).formatado, f"{NUMERO}/01")
        midia = Path("Acervo") / "Processos" / "_controle" / "midias" / f"{NUMERO}-01" / \
            "video_audiencia.mp4"
        self.assertEqual(numero_da_gravacao(midia, None).formatado, f"{NUMERO}/01")
        self.assertEqual(numero_da_gravacao(str(midia), NUMERO).formatado, f"{NUMERO}/01")
        # o dependente digitado vale ("/02" ou "-02"), e outro processo é outro
        self.assertEqual(numero_da_gravacao(nome, f"{NUMERO}/02").formatado, f"{NUMERO}/02")
        self.assertEqual(numero_da_gravacao(nome, f"{NUMERO}-02").formatado, f"{NUMERO}/02")
        outro = "0700124-68.2024.8.02.0001"
        self.assertEqual(numero_da_gravacao(nome, outro).formatado, outro)
        # sem dependente em lugar nenhum: o principal
        self.assertEqual(numero_da_gravacao(f"{NUMERO} 2026.flac", None).formatado, NUMERO)

    def test_gravacao_pelo_caminho_acha_o_numero_na_pasta(self):
        """O diálogo do Windows manda o caminho inteiro: a mídia baixada com os
        autos tem o número (com o dependente) só na pasta."""
        pasta = self.amb.dados / "Acervo" / "Processos" / "_controle" / "midias" / f"{NUMERO}-01"
        pasta.mkdir(parents=True)
        video = pasta / "video_audiencia.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        with mock.patch("helestron.servicos.transcrever_gravacao",
                        return_value=self.amb.raiz / "x.docx") as transcrever, \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar"):
            for processo in (None, NUMERO):
                with self.subTest(processo=processo):
                    corpo = {"caminho": str(video)}
                    if processo:
                        corpo["processo"] = processo
                    self.esperar_tarefa(self.cliente.dados(
                        "POST", "/api/transcricao/gravacao", corpo)["tarefa"])
                    self.assertEqual(transcrever.call_args.args[1].formatado, f"{NUMERO}/01")

    def test_envio_pelo_nome_original_mantem_o_dependente(self):
        recebidos = []

        def transcrever(origem, numero, cfg, progresso, cancelado, **kw):
            recebidos.append(numero.formatado)
            return Path(cfg.pasta_transcricoes) / "x.docx"

        with mock.patch("helestron.servicos.transcrever_gravacao", side_effect=transcrever), \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar"):
            status, env = self.cliente.enviar(
                "/api/transcricao/gravacao", "envio.wav", b"RIFF....WAVE",
                {"processo": NUMERO, "nome_original": f"{NUMERO}-01 2026-09-16 14h00.wav"})
            self.assertEqual(status, 200, env)
            self.esperar_tarefa(env["dados"]["tarefa"])
        self.assertEqual(recebidos, [f"{NUMERO}/01"])

    def test_video_sem_audio_enviado_diz_o_nome_do_arquivo_do_usuario(self):
        """O motor de verdade (PyAV), com um vídeo sem trilha de áudio enviado
        pela página: a tarefa falha com a frase certa e com o nome do arquivo
        do usuário - e não o do temporário "envio-3f6e….mp4" -, e o
        temporário não fica no disco. O servidor não recusou pela extensão."""
        try:
            from testes.test_transcricao_formatos import gerar
            import av  # noqa: F401
        except ImportError:
            self.skipTest("PyAV não instalado")
        video = gerar(self.amb.raiz / "camera.dat", "mp4", None, "mpeg4")
        nome = f"{NUMERO} câmera da sala 2.mp4"
        leitor = self.eventos()
        status, env = self.cliente.enviar("/api/transcricao/gravacao", nome, video.read_bytes())
        self.assertEqual(status, 200, env)
        tarefa = self.esperar_tarefa(env["dados"]["tarefa"], espera=60)
        self.assertEqual(tarefa["estado"], "falhou", tarefa)
        self.assertIn(f"'{nome}' é um vídeo sem trilha de áudio", tarefa["erro"])
        self.assertNotIn("envio-", tarefa["erro"])
        # o andamento ("Lendo o áudio de …") também diz o nome do usuário
        lendo = leitor.esperar("tarefa", lambda d: d.get("id") == tarefa["id"]
                               and "Lendo o áudio" in str(d.get("status")))
        self.assertIn(nome, lendo["status"])
        self.assertFalse([d for t, d in leitor.recebidos
                          if t == "tarefa" and "envio-" in str(d.get("status"))])
        envios = self.app.pasta_envios()
        self.assertEqual(list(envios.glob("envio-*")) if envios.exists() else [], [])

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

    def test_envio_pela_pagina_guarda_nome_data_e_sigilo_da_pasta(self):
        """Modos Edge e navegador: a gravação chega por envio, como um
        temporário de hoje, fora da pasta dos sigilosos. O nome e a data vão
        para a ficha, e a gravação guardada na pasta dos sigilosos (mesmo nome
        e tamanho) continua sigilosa - antes ia para o acervo."""
        recebidos = []

        def transcrever(origem, numero, cfg, progresso, cancelado, **kw):
            recebidos.append(kw)
            doc = Path(cfg.pasta_transcricoes) / f"{numero.nome_arquivo}.docx"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_bytes(b"PK")
            return doc

        conteudo = b"RIFF....WAVE-sala-2"
        guardada = self.amb.dados / "Sigilosos" / "Gravacoes" / "sala 2.wav"
        guardada.parent.mkdir(parents=True)
        guardada.write_bytes(conteudo)
        quando = datetime(2026, 9, 15, 10, 30)
        with mock.patch("helestron.servicos.transcrever_gravacao", side_effect=transcrever):
            status, env = self.cliente.enviar(
                "/api/transcricao/gravacao", "sala 2.wav", conteudo,
                {"processo": NUMERO, "sigiloso": "false",
                 "data_arquivo": str(int(quando.timestamp() * 1000))})
            self.assertEqual(status, 200, env)
            self.esperar_tarefa(env["dados"]["tarefa"])
            self.assertTrue(env["dados"]["sigiloso"])
            self.assertTrue(env["dados"]["sigiloso_forcado"])
            self.assertIn("pasta dos sigilosos", env["dados"]["motivo"])
            self.assertTrue(recebidos[-1]["sigiloso"])
            self.assertEqual(recebidos[-1]["gravacao"], "sala 2.wav")
            self.assertEqual(recebidos[-1]["data"], quando)
            # mesmo nome, outro conteúdo: não é a gravação guardada
            status, env = self.cliente.enviar(
                "/api/transcricao/gravacao", "sala 2.wav", b"RIFF-outra-gravacao-maior",
                {"processo": "0700124-68.2024.8.02.0001", "sigiloso": "false"})
            self.esperar_tarefa(env["dados"]["tarefa"])
            self.assertFalse(recebidos[-1]["sigiloso"])
            # a gravação de audiência sigilosa (o _audio da pasta dos sigilosos),
            # retranscrita sem os autos lá: o número já está na pasta - e a data
            # sai do nome que o Helestron deu ao arquivo
            audio = (self.amb.dados / "Sigilosos" / "Transcricoes" / "_audio"
                     / f"{NUMERO} 2026-09-15 14h00.flac")
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"fLaC-original")
            status, env = self.cliente.enviar(
                "/api/transcricao/gravacao", audio.name, b"fLaC-copia", {"sigiloso": "false"})
            self.esperar_tarefa(env["dados"]["tarefa"])
        self.assertTrue(recebidos[-1]["sigiloso"])
        self.assertTrue(env["dados"]["sigiloso_forcado"])
        self.assertEqual(recebidos[-1]["data"], datetime(2026, 9, 15, 14, 0))

    def test_data_da_gravacao_no_formato_que_a_pagina_manda(self):
        """A página manda o File.lastModified em ISO 8601 com o fuso (o
        toISOString do navegador, em UTC): na ficha vai a hora local, sem fuso."""
        from datetime import timezone

        from helestron.servidor.api_audiencias import data_da_gravacao

        quando = datetime(2026, 9, 15, 10, 30)
        iso = quando.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.assertEqual(data_da_gravacao(iso, "sala 2.wav"), quando)
        self.assertEqual(data_da_gravacao(str(int(quando.timestamp() * 1000))), quando)
        self.assertEqual(data_da_gravacao("2026-09-15T10:30:00"), quando)
        # sem a data da página: a do nome que o Helestron dá à gravação; sem nada, None
        self.assertEqual(data_da_gravacao("", f"{NUMERO} 2026-09-15 14h00.flac"),
                         datetime(2026, 9, 15, 14, 0))
        self.assertIsNone(data_da_gravacao(None, "sala 2.wav"))

    def test_gravacao_sigilosa_pela_pauta(self):
        audio = self.amb.raiz / "gravacao.mp3"
        audio.write_bytes(b"ID3")
        pauta = mock.Mock()
        pauta.processo_sigiloso.return_value = True
        with mock.patch.object(self.app, "pauta_ou_none", return_value=pauta), \
                mock.patch("helestron.servicos.transcrever_gravacao",
                           return_value=self.amb.raiz / "x.docx") as transcrever:
            dados = self.cliente.dados("POST", "/api/transcricao/gravacao",
                                       {"caminho": str(audio), "processo": NUMERO,
                                        "sigiloso": False})
            self.esperar_tarefa(dados["tarefa"])
        self.assertTrue(transcrever.call_args.kwargs["sigiloso"])
        self.assertEqual((dados["sigiloso"], dados["sigiloso_forcado"]), (True, True))
        self.assertIn("pauta", dados["motivo"])
        pauta.processo_sigiloso.assert_called_with(NUMERO)

    def test_recuperar_refaz_o_indice_e_o_espelho(self):
        diario = self.amb.dados / "Acervo" / "Transcricoes" / "_audio" / f"{NUMERO} 2026.jsonl"
        diario.parent.mkdir(parents=True)
        diario.write_text("{}", encoding="utf-8")
        documento = self.amb.dados / "Acervo" / "Transcricoes" / f"{NUMERO}.docx"
        with mock.patch("helestron.servicos.recuperaveis", return_value=[diario]), \
                mock.patch("helestron.servicos.recuperar", return_value=documento), \
                mock.patch("helestron.servidor.api_compartilhar.depois_de_salvar") as depois:
            self.cliente.dados("POST", "/api/transcricao/recuperar", {"arquivo": str(diario)})
        depois.assert_called_once_with(self.app, documento)

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


class TestNomeDoArquivoEnviadoNoErro(unittest.TestCase):
    """O erro da transcrição de um arquivo enviado cita o nome do arquivo do
    usuário, e não o do temporário; o erro do próprio Windows (com errno)
    segue intacto, para a página receber a frase geral e não o caminho."""

    def test_frase_do_programa_troca_o_nome_e_erro_do_windows_fica(self):
        from helestron.servidor import api_audiencias

        frase = ValueError("'envio-3f6e.mp4' é um vídeo sem trilha de áudio")
        novo = api_audiencias._com_outro_nome(frase, "envio-3f6e.mp4", "Audiência.mp4")
        self.assertIsInstance(novo, ValueError)
        self.assertEqual(str(novo), "'Audiência.mp4' é um vídeo sem trilha de áudio")
        preso = PermissionError(13, "Permission denied", r"C:\Users\x\temp\envio-3f6e.mp4")
        self.assertIs(api_audiencias._com_outro_nome(preso, "envio-3f6e.mp4", "Audiência.mp4"),
                      preso)


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

    def test_teste_do_microfone_ausente_ou_ocupado_tem_a_frase_do_motor(self):
        """Sem microfone, ou preso pelo Teams: a frase que diz o que fazer - e
        não "Algo deu errado no Helestron" (500)."""
        for frase in ("Nenhum microfone foi encontrado. Ligue o microfone (ou o fone com "
                      "microfone) e tente de novo.",
                      "Não consegui abrir o microfone. Outro programa (Teams, Zoom, gravador "
                      "da sala) pode estar usando-o com exclusividade."):
            with self.subTest(frase=frase[:30]):
                with mock.patch("helestron.transcricao.microfone.Captura._abrir",
                                side_effect=MicrofoneIndisponivel(frase)):
                    status, env = self.cliente.post("/api/transcricao/microfone/teste",
                                                    {"dispositivo": ""})
                    self.assertEqual(status, 409)
                    self.assertEqual(env["erro"]["codigo"], "microfone_indisponivel")
                    self.assertEqual(env["erro"]["mensagem"], frase)
                    # o microfone ficou livre: o segundo clique não diz "ocupado"
                    self.assertIsNone(self.app.recursos.quem_tem("microfone"))
                    status, env = self.cliente.post("/api/transcricao/microfone/teste",
                                                    {"dispositivo": ""})
                    self.assertEqual(env["erro"]["codigo"], "microfone_indisponivel")

    def test_teste_do_microfone_pelo_nome(self):
        lista = [Entrada(7, "Microfone de mesa (USB)", False, 48000)]
        recebidos = []

        def abrir(dispositivo, ao_nivel, ao_aviso=None):
            recebidos.append(dispositivo)
            return mock.Mock()

        with mock.patch("helestron.transcricao.microfone.listar_entradas", return_value=lista), \
                mock.patch("helestron.servicos.abrir_teste_microfone", side_effect=abrir):
            self.cliente.dados("POST", "/api/transcricao/microfone/teste",
                               {"dispositivo": "Microfone de mesa (USB)"})
            self.cliente.dados("POST", "/api/transcricao/microfone/parar")
            self.cliente.dados("POST", "/api/transcricao/microfone/teste", {"dispositivo": 7})
            self.cliente.dados("POST", "/api/transcricao/microfone/parar")
            status, env = self.cliente.post("/api/transcricao/microfone/teste",
                                            {"dispositivo": "Microfone que sumiu"})
        self.assertEqual(recebidos, ["Microfone de mesa (USB)", 7])
        self.assertEqual((status, env["erro"]["codigo"]), (409, "microfone_indisponivel"))
        self.assertIn("“Microfone que sumiu” não foi encontrado", env["erro"]["mensagem"])
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
