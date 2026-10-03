"""Configurações: cinco abas, tudo salvo na hora.

    Geral ............ pastas, nome, unidade
    Acessos .......... por tribunal: forma de entrar, usuário e senha, endereço
                       do portal, [Testar login]; navegador e ritmo do download
    Transcrição ...... modelos (com download e progresso), separação de
                       falantes, falantes padrão, contexto, áudio
    Compartilhamento . nuvem e texto para a IA
    Sobre ............ versão, caminhos, [Verificar instalação], registros

Na base havia três maneiras de salvar (ao clicar, com botão, e "feche e
abra o programa"). Aqui cada campo grava ao sair dele (ou ao marcar), e o
programa lê a configuração de novo a cada trabalho: nada pede reinício.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from .. import NOME, __version__
from ..nucleo import caminhos, sistema, tribunais
from . import componentes, dialogos, estilo, servicos
from .acessos import EditorAcesso
from .componentes import EstadoLinha, Faixa, Pagina, plural
from .estilo import px
from .tarefas import NAVEGADOR, MODELO_REVISAO, ContextoTela

log = logging.getLogger("interface.config")

NAVEGADORES = (("auto", "Automático (Chrome, senão Edge)"), ("chrome", "Google Chrome"),
               ("msedge", "Microsoft Edge"), ("chromium", "Chromium do programa"))
MODELOS_AO_VIVO = ("base", "small", "medium")
MODELOS_REVISAO = ("small", "medium", "large-v3-turbo")


class PaginaConfig(Pagina):
    nome = "config"
    titulo = "Configurações"
    icone = "config"

    def montar(self) -> None:
        self._vars: dict = {}
        self.editores: list[EditorAcesso] = []
        self.tarefa_login = self.nova_tarefa("Testar o login", (NAVEGADOR,))
        self.tarefa_modelo = self.nova_tarefa("Baixar o modelo de transcrição")
        self.tarefa_falantes = self.nova_tarefa("Instalar a separação de falantes", (MODELO_REVISAO,))
        self.tarefa_verificar = self.nova_tarefa("Verificar a instalação", essencial=False)
        self.tarefa_conferir = self.nova_tarefa("Conferir os componentes", essencial=False)
        corpo, _, _ = componentes.estrutura(
            self, "Configurações", "Tudo é salvo na hora em que você muda — não é preciso "
            "reiniciar o programa.", rolavel=False)
        corpo.columnconfigure(0, weight=1)
        corpo.rowconfigure(0, weight=1)
        self.abas = ttk.Notebook(corpo)
        self.abas.grid(row=0, column=0, sticky="nsew")
        for titulo, montar in (("Geral", self._aba_geral), ("Acessos", self._aba_acessos),
                               ("Transcrição", self._aba_transcricao),
                               ("Compartilhamento", self._aba_compartilhamento),
                               ("Sobre e diagnóstico", self._aba_sobre)):
            quadro, dentro = componentes.coluna_rolavel(self.abas, margem=px(4))
            dentro.columnconfigure(0, weight=1)
            self.abas.add(quadro, text=titulo)
            try:
                montar(dentro)
            except Exception as erro:          # uma aba quebrada não esconde as outras
                log.exception("a aba %s não abriu", titulo)
                Faixa(dentro, "Erro", titulo="Esta aba não abriu", texto=str(erro)).grid(
                    row=0, column=0, sticky="ew", pady=px(16))

    # ============================================================ apoio
    def _texto(self, pai, secao: str, chave: str, titulo: str, linha: int, coluna: int = 0,
               largura: int = 30, colspan: int = 1, ao_salvar=None) -> ttk.Entry:
        var = tk.StringVar(value=self.cfg.texto(secao, chave))
        self._vars[(secao, chave)] = var
        quadro, entrada = componentes.campo(pai, titulo, var, largura)
        quadro.grid(row=linha, column=coluna, columnspan=colspan, sticky="ew",
                    padx=(0 if coluna == 0 else px(14), 0), pady=(0, px(12)))

        def salvar(_evento=None):
            valor = var.get().strip()
            if valor != self.cfg.texto(secao, chave):
                self.cfg.definir(secao, chave, valor)
                if ao_salvar:
                    ao_salvar(valor)
        entrada.bind("<FocusOut>", salvar, add="+")
        entrada.bind("<Return>", salvar, add="+")
        return entrada

    def _marcar(self, pai, secao: str, chave: str, texto: str, linha: int, coluna: int = 0,
                colspan: int = 2) -> ttk.Checkbutton:
        var = tk.BooleanVar(value=self.cfg.flag(secao, chave))
        self._vars[(secao, chave)] = var
        c = ttk.Checkbutton(pai, text=texto, variable=var,
                            command=lambda: self.cfg.definir(secao, chave, var.get()))
        c.grid(row=linha, column=coluna, columnspan=colspan, sticky="w", pady=px(3))
        return c

    def _titulo(self, pai, texto: str, linha: int, nota: str = "", primeiro: bool = False) -> None:
        q = componentes.secao(pai, texto, nota=nota)
        q.grid(row=linha, column=0, columnspan=2, sticky="ew",
               pady=(px(14) if primeiro else px(26), px(12)))

    def _pasta(self, pai, secao: str, chave: str, titulo: str, linha: int, atual) -> None:
        quadro = ttk.Frame(pai, style="Faixa.TFrame", padding=(px(14), px(10)))
        quadro.grid(row=linha, column=0, columnspan=2, sticky="ew", pady=(0, px(10)))
        quadro.columnconfigure(0, weight=1)
        tk.Label(quadro, text=titulo, font=estilo.FONTE_NOTA, background=estilo.FAIXA_CLARA,
                 foreground=estilo.TINTA_FRACA).grid(row=0, column=0, sticky="w")
        rotulo = tk.Label(quadro, text=str(atual()), font=estilo.FONTE_MONO, anchor="w",
                          justify="left", background=estilo.FAIXA_CLARA, foreground=estilo.TINTA)
        rotulo.grid(row=1, column=0, sticky="ew")
        estilo.acompanhar_largura(rotulo)
        aviso = tk.Label(quadro, text="", font=estilo.FONTE_NOTA, anchor="w", justify="left",
                         background=estilo.FAIXA_CLARA, foreground=estilo.AMBAR_TINTA)
        estilo.acompanhar_largura(aviso)

        def conferir():
            p = atual()
            rotulo.configure(text=str(p))
            if caminhos.dentro_do_onedrive(p):
                aviso.configure(text="Dentro do OneDrive: a sincronização atrapalha arquivos em "
                                     "uso. Prefira uma pasta local.")
                aviso.grid(row=2, column=0, sticky="ew", pady=(px(4), 0))
            else:
                aviso.grid_remove()

        def alterar():
            nova = dialogos.escolher_pasta(self.janela.raiz, titulo, atual())
            if nova:
                self.cfg.definir(secao, chave, str(nova))
                try:
                    self.cfg.criar_pastas()
                except OSError as erro:
                    dialogos.erro(self.janela.raiz, "Pasta", f"Não consegui criar a pasta: {erro}")
                conferir()

        def abrir():
            try:
                sistema.abrir_pasta(atual())
            except Exception as erro:
                dialogos.erro(self.janela.raiz, "Abrir a pasta", str(erro))

        estilo.botao(quadro, "Alterar…", alterar, superficie="Faixa").grid(
            row=0, column=1, rowspan=2, padx=(px(12), 0))
        estilo.botao(quadro, "Abrir", abrir, superficie="Faixa").grid(
            row=0, column=2, rowspan=2, padx=(px(8), 0))
        conferir()

    # ============================================================ Geral
    def _aba_geral(self, pai) -> None:
        pai.columnconfigure((0, 1), weight=1, uniform="geral")
        self._titulo(pai, "Pastas", 0, "O acervo é a pasta compartilhada com a IA. Os sigilosos "
                                       "ficam fora dele.", primeiro=True)
        self._pasta(pai, "geral", "pasta_acervo", "Pasta do acervo (processos e transcrições)", 1,
                    lambda: self.cfg.pasta_acervo)
        self._pasta(pai, "geral", "pasta_sigilosos", "Pasta dos processos em segredo de justiça",
                    2, lambda: self.cfg.pasta_sigilosos)
        self._titulo(pai, "Você e a unidade", 3, "Aparecem na tela inicial e no cabeçalho das "
                                                 "transcrições.")
        self._texto(pai, "geral", "nome_usuario", "Como o programa chama você (ex.: Dra. Helena)", 4)
        self._texto(pai, "unidade", "magistrado", "Magistrado(a) — nome completo", 4, 1)
        self._texto(pai, "unidade", "cargo", "Cargo (ex.: Juíza de Direito)", 5)
        self._texto(pai, "unidade", "vara", "Vara ou juízo", 5, 1)
        self._texto(pai, "unidade", "comarca", "Comarca", 6)
        self._texto(pai, "unidade", "tribunal", "Tribunal (sigla)", 6, 1)

    # ============================================================ Acessos
    def _aba_acessos(self, pai) -> None:
        pai.columnconfigure((0, 1), weight=1, uniform="acessos")
        self._titulo(pai, "Acesso aos portais", 0, "Escolha o tribunal. O programa já reconhece o "
                                                   "tribunal de cada processo pelo número.",
                     primeiro=True)
        self.lista_tribunais = sorted((t for t in tribunais.carregar() if t.suportado),
                                      key=lambda t: t.sigla)
        rotulos = [f"{t.sigla} — {t.nome.split('—')[-1].strip()}" for t in self.lista_tribunais]
        self.var_tribunal = tk.StringVar()
        combo = ttk.Combobox(pai, textvariable=self.var_tribunal, values=rotulos,
                             state="readonly", height=14, width=40)
        combo.grid(row=1, column=0, sticky="w", pady=(0, px(14)))
        atual = (self.cfg.texto("interface", "tribunal") or "TJAL").upper()
        indice = next((i for i, t in enumerate(self.lista_tribunais) if t.sigla == atual), 0)
        if self.lista_tribunais:
            combo.current(indice)
        self.combo_tribunal = combo
        self.area_tribunal = ttk.Frame(pai)
        self.area_tribunal.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.area_tribunal.columnconfigure(0, weight=1)
        combo.bind("<<ComboboxSelected>>", lambda _e: self._montar_tribunal())
        self._montar_tribunal()

        self._titulo(pai, "Navegador e ritmo do download", 3)
        ttk.Label(pai, text="Navegador usado nos portais", foreground=estilo.TINTA_FRACA,
                  font=estilo.FONTE_NOTA).grid(row=4, column=0, sticky="w", pady=(0, px(3)))
        var_nav = tk.StringVar()
        nav = ttk.Combobox(pai, textvariable=var_nav, state="readonly",
                           values=[r for _, r in NAVEGADORES], width=34)
        nav.grid(row=5, column=0, sticky="w", pady=(0, px(12)))
        atual_nav = self.cfg.texto("download", "navegador") or "auto"
        var_nav.set(dict(NAVEGADORES).get(atual_nav, NAVEGADORES[0][1]))
        self._vars["navegador"] = var_nav
        nav.bind("<<ComboboxSelected>>", lambda _e: self.cfg.definir(
            "download", "navegador", {r: c for c, r in NAVEGADORES}[var_nav.get()]))
        ritmo = ttk.Frame(pai)
        ritmo.grid(row=6, column=0, columnspan=2, sticky="ew")
        for i, (chave, titulo, de, ate) in enumerate((
                ("pausa_entre_processos", "Pausa entre processos (s)", 0, 60),
                ("tentativas", "Tentativas por processo", 1, 5),
                ("espera_login_minutos", "Esperar o login até (min)", 1, 30))):
            q = ttk.Frame(ritmo)
            q.grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else px(18), 0))
            ttk.Label(q, text=titulo, foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA).pack(
                anchor="w", pady=(0, px(3)))
            var = tk.StringVar(value=self.cfg.texto("download", chave))
            self._vars[("download", chave)] = var
            caixa = ttk.Spinbox(q, from_=de, to=ate, textvariable=var, width=8,
                                command=lambda c=chave, v=var: self._salvar_numero(c, v))
            caixa.pack(anchor="w")
            caixa.bind("<FocusOut>", lambda _e, c=chave, v=var: self._salvar_numero(c, v))
        self._marcar(pai, "download", "salvar_diagnostico",
                     "Guardar a imagem e o código da tela quando algo der errado (ajuda o suporte)", 7)

    def _salvar_numero(self, chave: str, var: tk.StringVar) -> None:
        texto = var.get().strip().replace(",", ".")
        try:
            float(texto)
        except ValueError:
            var.set(self.cfg.texto("download", chave))
            return
        if texto != self.cfg.texto("download", chave):
            self.cfg.definir("download", chave, texto)

    def _tribunal(self):
        if not self.lista_tribunais:
            return None
        return self.lista_tribunais[max(0, self.combo_tribunal.current())]

    def _montar_tribunal(self) -> None:
        for w in self.area_tribunal.winfo_children():
            w.destroy()
        self.editores = []
        t = self._tribunal()
        if t is None:
            return
        self.cfg.definir("interface", "tribunal", t.sigla)
        linha = 0
        if t.observacao:
            nota = ttk.Label(self.area_tribunal, text=t.observacao, foreground=estilo.TINTA_FRACA,
                             font=estilo.FONTE_NOTA, justify="left")
            nota.grid(row=linha, column=0, sticky="ew", pady=(0, px(10)))
            estilo.acompanhar_largura(nota)
            linha += 1
        for alvo in (t, t.alternativo):
            if alvo is None or not alvo.suportado:
                continue
            quadro = ttk.Frame(self.area_tribunal, style="Bloco.TFrame", padding=(px(18), px(14)))
            quadro.grid(row=linha, column=0, sticky="ew", pady=(0, px(12)))
            quadro.columnconfigure(0, weight=1)
            linha += 1
            ed = EditorAcesso(quadro, self.janela, alvo, rotulo=f"{alvo.sigla} · {alvo.nome_sistema}",
                              nota=("Usado para o que não for achado no "
                                    f"{t.nome_sistema}." if alvo is not t else ""))
            ed.grid(row=0, column=0, sticky="ew")
            self.editores.append(ed)
            self._endereco(quadro, alvo, 1)
            rodape = ttk.Frame(quadro)
            rodape.grid(row=2, column=0, sticky="ew", pady=(px(12), 0))
            rodape.columnconfigure(1, weight=1)
            estado = EstadoLinha(rodape, "", "neutro")
            estado.grid(row=0, column=1, sticky="ew", padx=(px(12), 0))
            estilo.botao(rodape, "Testar login", lambda a=alvo, e=ed, s=estado:
                         self._testar_login(a, e, s), "apoio").grid(row=0, column=0, sticky="w")

    def _endereco(self, pai, t, linha: int) -> None:
        grau = "base" if t.sistema == "esaj" else "1g"
        atual = t.url_para(None, "1g") if t.sistema != "esaj" else t.url_para()
        var = tk.StringVar(value=atual)
        self._vars[("endereco", t.portal)] = var
        q = ttk.Frame(pai)
        q.grid(row=linha, column=0, sticky="ew", pady=(px(12), 0))
        q.columnconfigure(0, weight=1)
        ttk.Label(q, text="Endereço do portal (1º grau) — corrija se o tribunal mudar",
                  foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA).grid(
            row=0, column=0, sticky="w", pady=(0, px(3)))
        e = ttk.Entry(q, textvariable=var)
        e.grid(row=1, column=0, sticky="ew")

        # Compara com o ÚLTIMO valor gravado, e não com o da montagem: sem
        # isto, corrigir A→B e depois voltar B→A não gravava a volta.
        gravado = [atual]

        def salvar(_evento=None):
            novo = var.get().strip()
            if novo == gravado[0]:
                return
            try:
                tribunais.definir_endereco(t.portal, grau, novo)
                gravado[0] = novo
                log.info("Endereço de %s corrigido para %s.", t.portal, novo or "o do catálogo")
            except OSError as erro:
                dialogos.erro(self.janela.raiz, "Endereço", str(erro))
        e.bind("<FocusOut>", salvar, add="+")
        e.bind("<Return>", salvar, add="+")

    def _testar_login(self, t, editor: EditorAcesso, estado: EstadoLinha) -> None:
        editor.salvar()
        tarefa = self.tarefa_login
        try:
            opcoes = servicos.opcoes_download(self.cfg)
        except Exception as erro:
            self.janela.erro_inesperado(erro)
            return
        ctx = ContextoTela(self.postar, tarefa.parar)
        credenciais = editor.credenciais_atuais() if editor.modo.get() == "senha" else None
        self._estado_login = estado

        def pronto(_):
            estado.definir(f"Login confirmado no {t.sigla} · {t.nome_sistema}.", "ok")

        def falhou(erro):
            estado.definir(_maiuscula(str(erro)) or "O login não foi concluído.", "erro")

        if self.em_segundo_plano(tarefa, servicos.testar_login, t, opcoes, ctx, credenciais,
                                 ao_concluir=pronto, ao_falhar=falhou):
            estado.definir("Abrindo o portal… (o navegador pode aparecer)", "ocupado")

    # ============================================================ Transcrição
    def _aba_transcricao(self, pai) -> None:
        pai.columnconfigure((0, 1), weight=1, uniform="transcricao")
        self._titulo(pai, "Modelos de transcrição", 0,
                     "Ficam neste computador: a audiência não sai dele. O modelo menor é mais "
                     "rápido; o maior, mais preciso.", primeiro=True)
        catalogo = {m["nome"]: m for m in servicos.modelos_disponiveis()}
        self.linhas_modelo: dict[str, tuple] = {}
        for i, (chave, titulo, opcoes) in enumerate((
                ("modelo_ao_vivo", "Ao vivo (durante a audiência)", MODELOS_AO_VIVO),
                ("modelo_revisao", "Revisão e gravações (mais preciso)", MODELOS_REVISAO))):
            q = ttk.Frame(pai)
            q.grid(row=1, column=i, sticky="new", padx=(0 if i == 0 else px(14), 0))
            q.columnconfigure(0, weight=1)
            ttk.Label(q, text=titulo, foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA).grid(
                row=0, column=0, sticky="w", pady=(0, px(3)))
            var = tk.StringVar(value=self.cfg.texto("transcricao", chave))
            self._vars[("transcricao", chave)] = var
            combo = ttk.Combobox(q, textvariable=var, state="readonly", values=opcoes)
            combo.grid(row=1, column=0, sticky="ew")
            estado = EstadoLinha(q, "", "neutro")
            estado.grid(row=2, column=0, sticky="ew", pady=(px(6), 0))
            botao = estilo.botao(q, "Baixar este modelo", lambda c=chave: self.baixar_modelo(c),
                                 pequeno=True)
            botao.grid(row=3, column=0, sticky="w", pady=(px(6), 0))
            self.linhas_modelo[chave] = (var, estado, botao, catalogo)
            combo.bind("<<ComboboxSelected>>", lambda _e, c=chave: self._modelo_mudou(c))
            self._mostrar_modelo(chave)
        self.barra_modelo = ttk.Progressbar(pai, mode="determinate", maximum=1000)
        self.texto_modelo = ttk.Label(pai, text="", foreground=estilo.TINTA_FRACA,
                                      font=estilo.FONTE_NOTA)

        self._titulo(pai, "Separação automática de falantes", 4,
                     "Na revisão final, separa as vozes e dá a cada uma o nome marcado durante a "
                     "audiência. Componente opcional (cerca de 50 MB).")
        self._marcar(pai, "transcricao", "separar_falantes",
                     "Separar as vozes na revisão final, se o componente estiver instalado", 5)
        linha = ttk.Frame(pai)
        linha.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(px(4), 0))
        linha.columnconfigure(1, weight=1)
        self.btn_falantes = estilo.botao(linha, "Instalar o componente", self.instalar_falantes,
                                         pequeno=True)
        self.btn_falantes.grid(row=0, column=0, sticky="w")
        self.estado_falantes = EstadoLinha(linha, "Conferindo…", "neutro")
        self.estado_falantes.grid(row=0, column=1, sticky="ew", padx=(px(12), 0))

        self._titulo(pai, "Audiência", 7)
        self._texto(pai, "transcricao", "falantes",
                    "Botões de quem fala (F1, F2…), separados por ponto e vírgula", 8, colspan=2,
                    ao_salvar=self._falantes_mudaram)
        ttk.Label(pai, text="Contexto para o modelo (vocabulário e grafia; mantenha acentuado)",
                  foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(0, px(3)))
        self.caixa_contexto = tk.Text(pai, height=4, wrap="word", font=estilo.FONTE, relief="flat",
                                      borderwidth=0, padx=px(8), pady=px(6),
                                      highlightthickness=1, highlightbackground=estilo.LINHA_FORTE,
                                      highlightcolor=estilo.AZUL)
        self.caixa_contexto.insert("1.0", self.cfg.texto("transcricao", "contexto"))
        self.caixa_contexto.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(0, px(12)))
        self.caixa_contexto.bind("<FocusOut>", lambda _e: self._salvar_contexto())
        self._marcar(pai, "transcricao", "salvar_audio",
                     "Guardar a gravação (FLAC) ao lado da transcrição, na pasta _audio", 11)
        self._marcar(pai, "transcricao", "marcar_tempo", "Mostrar a hora [hh:mm:ss] em cada fala", 12)
        self._marcar(pai, "transcricao", "refinar_ao_encerrar",
                     "Ao encerrar a audiência, revisar com o modelo preciso", 13)

    def _mostrar_modelo(self, chave: str) -> None:
        var, estado, botao, catalogo = self.linhas_modelo[chave]
        nome = var.get() or ("small" if chave == "modelo_ao_vivo" else "medium")
        info = catalogo.get(nome, {})
        instalado = servicos.modelo_instalado(nome)
        tamanho = f"{info.get('mb', 0) / 1000:.1f} GB".replace(".", ",") if info.get("mb", 0) >= 1000 \
            else f"{info.get('mb', 0)} MB"
        descricao = info.get("descricao", "")
        if instalado:
            estado.definir(f"Instalado · {descricao}" if descricao else "Instalado", "ok")
            botao.grid_remove()
        else:
            estado.definir(f"Não baixado ({tamanho})" + (f" · {descricao}" if descricao else ""),
                           "aviso")
            botao.grid()

    def _modelo_mudou(self, chave: str) -> None:
        var = self.linhas_modelo[chave][0]
        self.cfg.definir("transcricao", chave, var.get())
        self._mostrar_modelo(chave)

    def baixar_modelo_ao_vivo(self) -> None:
        """Chamado pelo aviso da tela inicial."""
        self.abas.select(2)
        self.baixar_modelo("modelo_ao_vivo")

    def baixar_modelo(self, chave: str) -> None:
        var = self.linhas_modelo[chave][0]
        nome = var.get()
        tarefa = self.tarefa_modelo

        def progresso(fracao, texto=""):
            self.postar("modelo", (float(fracao or 0), str(texto or "")))

        def pronto(_):
            self.barra_modelo.grid_remove()
            self.texto_modelo.configure(text=f"Modelo {nome} instalado.", foreground=estilo.VERDE)
            for c in self.linhas_modelo:
                self._mostrar_modelo(c)

        def falhou(erro):
            self.barra_modelo.grid_remove()
            self.texto_modelo.configure(text=_maiuscula(str(erro)), foreground=estilo.VINHO)

        if self.em_segundo_plano(tarefa, servicos.baixar_modelo, nome, progresso,
                                 ao_concluir=pronto, ao_falhar=falhou):
            self.barra_modelo.configure(value=0)
            self.barra_modelo.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(px(14), px(4)))
            self.texto_modelo.grid(row=3, column=0, columnspan=2, sticky="w")
            self.texto_modelo.configure(text=f"Baixando o modelo {nome}…",
                                        foreground=estilo.TINTA_FRACA)

    def instalar_falantes(self) -> None:
        tarefa = self.tarefa_falantes

        def progresso(fracao, texto=""):
            self.postar("falantes", (float(fracao or 0), str(texto or "")))

        def pronto(_):
            self._conferir_falantes()

        def falhou(erro):
            self.btn_falantes.state(["!disabled"])
            self.estado_falantes.definir(_maiuscula(str(erro)), "erro")

        if self.em_segundo_plano(tarefa, servicos.instalar_falantes, progresso, tarefa.parar.is_set,
                                 ao_concluir=pronto, ao_falhar=falhou):
            self.btn_falantes.state(["disabled"])
            self.estado_falantes.definir("Instalando…", "ocupado")

    def _conferir_falantes(self) -> None:
        def mostrar(resultado):
            ok, texto = resultado
            self.estado_falantes.definir(_maiuscula(texto), "ok" if ok else "neutro")
            if ok:
                self.btn_falantes.grid_remove()
            else:
                self.btn_falantes.grid()
                self.btn_falantes.state(["!disabled"])
        if self.tarefa_conferir.ativa:
            return
        self.em_segundo_plano(self.tarefa_conferir, servicos.falantes_situacao,
                              ao_concluir=mostrar, ao_falhar=lambda e: None)

    def _falantes_mudaram(self, _valor: str) -> None:
        pagina = self.janela.paginas.get("transcrever")
        grade = getattr(pagina, "grade", None)
        if grade is not None:
            grade.nomes = (self.cfg.lista("transcricao", "falantes") + [""] * 8)[:8]
            for k in range(8):
                grade._desenhar(k)

    def _salvar_contexto(self) -> None:
        texto = " ".join(self.caixa_contexto.get("1.0", "end").split())
        if texto and texto != self.cfg.texto("transcricao", "contexto"):
            self.cfg.definir("transcricao", "contexto", texto)

    # ============================================================ Compartilhamento
    def _aba_compartilhamento(self, pai) -> None:
        pai.columnconfigure((0, 1), weight=1, uniform="comp")
        self._titulo(pai, "Texto para a IA", 0, primeiro=True)
        self._marcar(pai, "compartilhar", "incluir_texto",
                     "Gerar a versão em texto dos autos, com a folha marcada (a IA lê melhor e "
                     "cita a folha)", 1)
        self._titulo(pai, "Espelho na nuvem", 2, "Cópia do acervo numa pasta do OneDrive ou do "
                                                 "Google Drive. Em branco: não espelha.")
        self._texto(pai, "compartilhar", "pasta_nuvem", "Pasta da nuvem", 3, colspan=2)
        self._marcar(pai, "compartilhar", "espelhar_automaticamente",
                     "Espelhar sozinho ao fim de cada download e de cada transcrição", 4)
        estilo.botao(pai, "Ir para Compartilhar com IA  →",
                     lambda: self.janela.mostrar("compartilhar"), "texto").grid(
            row=5, column=0, sticky="w", pady=(px(14), 0))

    # ============================================================ Sobre
    def _aba_sobre(self, pai) -> None:
        pai.columnconfigure(0, weight=1)
        cab = ttk.Frame(pai)
        cab.grid(row=0, column=0, sticky="ew", pady=(px(14), px(16)))
        foto = estilo.imagem("assessor", px(56))
        tk.Label(cab, image=foto or "", background=estilo.PAPEL).pack(side="left")
        textos = ttk.Frame(cab)
        textos.pack(side="left", padx=(px(16), 0))
        ttk.Label(textos, text=NOME, font=estilo.FONTE_CARTAO).pack(anchor="w")
        ttk.Label(textos, text=f"Versão {__version__} · Python {_python()}",
                  foreground=estilo.TINTA_FRACA).pack(anchor="w")

        caminhos_ = ttk.Frame(pai, style="Faixa.TFrame", padding=(px(14), px(10)))
        caminhos_.grid(row=1, column=0, sticky="ew")
        caminhos_.columnconfigure(1, weight=1)
        for i, (rotulo, valor) in enumerate((("Programa", caminhos.RAIZ),
                                             ("Configuração", self.cfg.arquivo),
                                             ("Acervo", self.cfg.pasta_acervo),
                                             ("Registros", caminhos.LOGS),
                                             ("Senhas e perfis", caminhos.LOCAL))):
            tk.Label(caminhos_, text=rotulo, font=estilo.FONTE_NOTA, background=estilo.FAIXA_CLARA,
                     foreground=estilo.TINTA_FRACA, anchor="w").grid(row=i, column=0, sticky="w",
                                                                     padx=(0, px(14)), pady=px(1))
            valor_rotulo = tk.Label(caminhos_, text=str(valor), font=estilo.FONTE_MONO, anchor="w",
                                    justify="left", background=estilo.FAIXA_CLARA,
                                    foreground=estilo.TINTA)
            valor_rotulo.grid(row=i, column=1, sticky="ew", pady=px(1))
            estilo.acompanhar_largura(valor_rotulo)

        botoes = ttk.Frame(pai)
        botoes.grid(row=2, column=0, sticky="w", pady=(px(16), 0))
        self.btn_verificar = estilo.botao(botoes, "Verificar a instalação", self.verificar,
                                          "tonal")
        self.btn_verificar.pack(side="left")
        estilo.botao(botoes, "Abrir a pasta de registros",
                     lambda: self._abrir(caminhos.LOGS, pasta=True)).pack(side="left",
                                                                         padx=(px(8), 0))
        estilo.botao(botoes, "Abrir o config.ini",
                     lambda: self._abrir(self.cfg.arquivo)).pack(side="left", padx=(px(8), 0))
        estilo.botao(botoes, "Refazer o assistente inicial", self.janela.abrir_assistente,
                     "texto").pack(side="left", padx=(px(8), 0))

        self.estado_verificar = EstadoLinha(pai, "", "neutro")
        self.estado_verificar.grid(row=3, column=0, sticky="ew", pady=(px(12), 0))
        self.quadro_verif, self.arvore_verif = componentes.tabela(
            pai, [("item", "Item", 260, "w", False), ("situacao", "Situação", 90, "w", False),
                  ("detalhe", "Detalhe", 360, "w", True)], altura=8)
        self.quadro_verif.grid(row=4, column=0, sticky="ew", pady=(px(8), 0))
        self.quadro_verif.grid_remove()
        componentes.DicaTabela(self.arvore_verif, ("detalhe", "item"))

    def _abrir(self, alvo, pasta: bool = False) -> None:
        # Sem try, a falha sumia em silêncio (pythonw não tem console).
        try:
            sistema.abrir_pasta(alvo) if pasta else sistema.abrir_arquivo(alvo)
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Abrir", f"Não consegui abrir {alvo}:\n{erro}")

    def verificar(self) -> None:
        def pronto(itens):
            self.btn_verificar.state(["!disabled"])
            arv = self.arvore_verif
            arv.delete(*arv.get_children())
            falhas = avisos = 0
            for item in itens:
                situacao = str(getattr(item, "situacao", "")).lower()
                tag = {"ok": "ok", "aviso": "aviso", "falha": "falha"}.get(situacao, "aguardando")
                falhas += situacao == "falha"
                avisos += situacao == "aviso"
                rotulo = {"ok": "OK", "aviso": "Atenção", "falha": "Falha"}.get(situacao, situacao)
                detalhe = str(getattr(item, "detalhe", "") or "")
                acao = str(getattr(item, "acao", "") or "")
                if acao and situacao != "ok":
                    detalhe = f"{detalhe} — {acao}" if detalhe else acao
                arv.insert("", "end", values=(getattr(item, "nome", ""), rotulo, detalhe),
                           tags=(tag,))
            self.quadro_verif.grid()
            if falhas:
                self.estado_verificar.definir(f"{plural(falhas, 'item', 'itens')} com falha. "
                                              "Rode o INSTALAR.bat de novo.", "erro")
            elif avisos:
                self.estado_verificar.definir(
                    f"Tudo o que é essencial funciona; "
                    f"{plural(avisos, 'item pede', 'itens pedem')} atenção.", "aviso")
            else:
                self.estado_verificar.definir("Tudo certo com a instalação.", "ok")

        def falhou(erro):
            self.btn_verificar.state(["!disabled"])
            self.estado_verificar.definir(f"A verificação falhou: {erro}", "erro")

        if self.em_segundo_plano(self.tarefa_verificar,
                                 lambda: servicos.verificar_instalacao(False, self.cfg),
                                 ao_concluir=pronto, ao_falhar=falhou):
            self.btn_verificar.state(["disabled"])
            self.estado_verificar.definir("Verificando…", "ocupado")

    # ============================================================ eventos
    def ao_mostrar(self) -> None:
        # Outra página (ou o assistente) pode ter mudado a configuração:
        # as caixas de marcar acompanham.
        for chave, var in self._vars.items():
            if isinstance(chave, tuple) and isinstance(var, tk.BooleanVar):
                var.set(self.cfg.flag(*chave))
        if hasattr(self, "estado_falantes") and not self.tarefa_falantes.ativa:
            self._conferir_falantes()
        # o mesmo portal pode ter mudado na página Baixar ou no assistente
        for ed in self.editores:
            ed.recarregar()

    def ao_esconder(self) -> None:
        # a barra lateral não tira o foco do campo: grava a senha digitada
        for ed in self.editores:
            ed.salvar()

    def ao_evento(self, tipo: str, dado) -> None:
        if tipo == "modelo":
            fracao, texto = dado
            self.barra_modelo.configure(value=1000 * fracao)
            if texto:
                self.texto_modelo.configure(text=texto, foreground=estilo.TINTA_FRACA)
        elif tipo == "falantes":
            fracao, texto = dado
            self.estado_falantes.definir(f"{texto} ({fracao:.0%})", "ocupado")
        elif tipo == "pedir_codigo":
            dialogos.DialogoCodigo(self.janela.raiz, dado)
        elif tipo == "avisar":
            titulo, mensagem = dado
            estado = getattr(self, "_estado_login", None)
            if estado is not None:
                estado.definir(f"{titulo}: {mensagem}", "aviso")
            estilo.piscar_na_barra(self.janela.raiz)
        elif tipo == "status":
            estado = getattr(self, "_estado_login", None)
            if estado is not None and self.tarefa_login.ativa:
                estado.definir(str(dado), "ocupado")

    def indicador(self):
        if self.tarefa_modelo.ativa or self.tarefa_falantes.ativa or self.tarefa_login.ativa:
            return ("", estilo.AZUL)
        return None


def _python() -> str:
    import platform

    return platform.python_version()


def _maiuscula(texto: str) -> str:
    texto = (texto or "").strip()
    return texto[:1].upper() + texto[1:]

