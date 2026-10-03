"""Compartilhar com IA: o acervo no Claude Code, no Claude (Cowork) e no ChatGPT.

O acervo é uma pasta comum do computador. Nada é "enviado" pelo programa:
cada ferramenta abre a pasta, e lê sozinha as instruções que o preparo
deixa nela (CLAUDE.md, AGENTS.md, INDICE.md e o texto dos autos com a folha
marcada). A página só faz o que o usuário faria à mão - e o que não dá para
automatizar (escolher a pasta no Cowork, Ctrl+O no ChatGPT Work) vira uma
instrução curta, com o caminho ou o pedido já copiado.

Funções que o módulo de compartilhamento pode ainda não ter (url_cowork,
abrir_chatgpt_work, registrar_mcp_codex...) são chamadas por servicos.py,
que cai num plano B quando faltam.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..nucleo import sistema
from . import componentes, dialogos, estilo, servicos
from .componentes import Cartao, EstadoLinha, Faixa, Pagina, plural, quando
from .estilo import px

log = logging.getLogger("interface.compartilhar")

PASTA_PACOTES = "Pacotes para IA"


class PaginaCompartilhar(Pagina):
    nome = "compartilhar"
    titulo = "Compartilhar com IA"
    icone = "compartilhar"
    marca_log = "[compartilhar]"

    def montar(self) -> None:
        self.estado: dict = {}
        self._consultado = False
        self._vars: dict = {}
        self.tarefa_estado = self.nova_tarefa("Conferir o Claude e o ChatGPT")
        self.tarefa = self.nova_tarefa("Preparar o acervo para a IA")
        self.tarefa_nuvem = self.nova_tarefa("Espelhar o acervo na nuvem")
        self.tarefa_abrir = self.nova_tarefa("Abrir a ferramenta de IA")

        corpo, _, _ = componentes.estrutura(
            self, "Compartilhar com IA",
            "O acervo é uma pasta do seu computador. Daqui você a abre no Claude Code, no "
            "Claude (Cowork) ou no ChatGPT Work - cada um lê sozinho as instruções de "
            "trabalho que o programa deixa na pasta.")
        corpo.columnconfigure(0, weight=1)
        self.corpo = corpo

        # ------------------------------------------------ a pasta do acervo
        topo = ttk.Frame(corpo, style="Faixa.TFrame", padding=(px(18), px(14)))
        topo.grid(row=0, column=0, sticky="ew")
        topo.columnconfigure(1, weight=1)
        foto = estilo.imagem("bloco-pasta", px(40))
        tk.Label(topo, image=foto or "", background=estilo.FAIXA_CLARA).grid(
            row=0, column=0, rowspan=2, sticky="n", padx=(0, px(14)))
        tk.Label(topo, text="Pasta do acervo", font=estilo.FONTE_NEGRITO,
                 background=estilo.FAIXA_CLARA, foreground=estilo.TINTA).grid(row=0, column=1,
                                                                             sticky="w")
        self.rotulo_pasta = tk.Label(topo, text="", font=estilo.FONTE_MONO, anchor="w",
                                     justify="left", background=estilo.FAIXA_CLARA,
                                     foreground=estilo.TINTA)
        self.rotulo_pasta.grid(row=1, column=1, sticky="ew", pady=(px(2), 0))
        estilo.acompanhar_largura(self.rotulo_pasta)
        botoes = tk.Frame(topo, background=estilo.FAIXA_CLARA)
        botoes.grid(row=0, column=2, rowspan=2, sticky="e", padx=(px(12), 0))
        estilo.botao(botoes, "Abrir", self.abrir_pasta, superficie="Faixa").pack(side="left")
        estilo.botao(botoes, "Copiar caminho", self.copiar_caminho,
                     superficie="Faixa").pack(side="left", padx=(px(8), 0))
        linha = tk.Frame(topo, background=estilo.FAIXA_CLARA)
        linha.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(px(12), 0))
        linha.columnconfigure(0, weight=1)
        self.estado_acervo = EstadoLinha(linha, "Conferindo o acervo…", "neutro",
                                         fundo=estilo.FAIXA_CLARA)
        self.estado_acervo.grid(row=0, column=0, sticky="ew")
        self.btn_preparar = estilo.botao(linha, "Preparar arquivos para IA", self.preparar,
                                         "principal", superficie="Faixa")
        self.btn_preparar.grid(row=0, column=1, sticky="e", padx=(px(12), 0))

        self.faixa = Faixa(corpo, "Info")
        self.faixa.grid(row=1, column=0, sticky="ew", pady=(px(14), 0))
        self.faixa.grid_remove()

        # ------------------------------------------------ os três blocos
        self.grade = ttk.Frame(corpo)
        self.grade.grid(row=2, column=0, sticky="ew", pady=(px(18), 0))
        self.blocos = [self._bloco_code(), self._bloco_cowork(), self._bloco_chatgpt()]
        self._colunas = 0
        self.grade.bind("<Configure>", self._rearranjar, add="+")
        self._rearranjar()

        # ------------------------------------------------ nuvem
        self._bloco_nuvem(corpo).grid(row=3, column=0, sticky="ew", pady=(px(18), 0))

        # ------------------------------------------------ sigilo
        nota = Faixa(corpo, "Info", titulo="Sigilo e responsabilidade", texto=(
            "Os processos em segredo de justiça ficam na pasta Sigilosos, fora do acervo, e "
            "não são compartilhados. A IA é ferramenta de apoio: resumos e minutas são "
            "sugestões para revisão, e a decisão é sempre do magistrado (Resolução CNJ "
            "nº 615/2025)."))
        nota.grid(row=4, column=0, sticky="ew", pady=(px(18), 0))
        self.detalhes = componentes.Detalhes(corpo, "Detalhes técnicos")
        self.detalhes.grid(row=5, column=0, sticky="ew", pady=(px(18), 0))
        self._atualizar_pasta()

    # ============================================================ blocos
    def _bloco(self, icone: str, titulo: str, texto: str):
        cartao = Cartao(self.grade, padding=(px(20), px(18), px(20), px(18)))
        cartao.columnconfigure(0, weight=1)
        cab = ttk.Frame(cartao)
        cab.grid(row=0, column=0, sticky="ew")
        foto = estilo.imagem(icone, px(36))
        tk.Label(cab, image=foto or "", background=estilo.PAPEL).pack(side="left")
        ttk.Label(cab, text=titulo, font=estilo.FONTE_CARTAO).pack(side="left", padx=(px(12), 0))
        estado = EstadoLinha(cartao, "Conferindo…", "neutro")
        estado.grid(row=1, column=0, sticky="ew", pady=(px(12), 0))
        descricao = ttk.Label(cartao, text=texto, foreground=estilo.TINTA_FRACA, justify="left")
        descricao.grid(row=2, column=0, sticky="ew", pady=(px(8), px(14)))
        estilo.acompanhar_largura(descricao)
        acoes = ttk.Frame(cartao)
        acoes.grid(row=3, column=0, sticky="ew")
        acoes.columnconfigure(0, weight=1)
        cartao.rowconfigure(4, weight=1)
        nota = ttk.Label(cartao, text="", foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA,
                         justify="left")
        nota.grid(row=5, column=0, sticky="sew", pady=(px(12), 0))
        estilo.acompanhar_largura(nota)
        cartao.estado, cartao.acoes, cartao.nota = estado, acoes, nota  # type: ignore[attr-defined]
        return cartao

    def _acao(self, bloco, texto: str, comando, familia: str = "apoio") -> ttk.Button:
        n = len(bloco.acoes.winfo_children())
        b = estilo.botao(bloco.acoes, texto, comando, familia)
        b.grid(row=n, column=0, sticky="ew", pady=(0 if n == 0 else px(8), 0))
        return b

    def _bloco_code(self):
        b = self._bloco("bloco-terminal", "Claude Code",
                        "Abre um terminal já dentro do acervo. O Claude lê sozinho o CLAUDE.md "
                        "e trabalha com os autos e as transcrições.")
        self.btn_code = self._acao(b, "Abrir o acervo no Claude Code", self.abrir_code, "tonal")
        self.btn_instalar_code = self._acao(b, "Instalar o Claude Code", self.instalar_code)
        return b

    def _bloco_cowork(self):
        b = self._bloco("bloco-pasta", "Claude Cowork",
                        "No app Claude Desktop, o Cowork trabalha na pasta do acervo; o conector "
                        "dá ao chat do Claude acesso de leitura aos autos.")
        self._acao(b, "Abrir no Cowork", self.abrir_cowork, "tonal")
        self.btn_conectar = self._acao(b, "Conectar o acervo ao Claude", self.conectar_claude)
        self.btn_claude = self._acao(b, "Abrir o Claude", self.abrir_claude, "texto")
        self._acao(b, "Gerar o plugin para o Cowork", self.plugin_cowork, "texto")
        b.nota.configure(text="No Cowork, confirme a pasta quando o Claude perguntar. O pedido "
                              "inicial vai copiado: cole com Ctrl+V.")
        return b

    def _bloco_chatgpt(self):
        b = self._bloco("bloco-conversa", "ChatGPT Work",
                        "O app do ChatGPT para Windows trabalha em pastas locais (modo Work) e "
                        "lê o AGENTS.md do acervo.")
        self._acao(b, "Abrir no ChatGPT Work", self.abrir_work, "tonal")
        self.btn_codex = self._acao(b, "Abrir no Codex", self.abrir_codex)
        self._acao(b, "Gerar pacote para o ChatGPT", self.pacote)
        self.btn_instalar_chatgpt = self._acao(b, "Instalar o app do ChatGPT",
                                               servicos.instalar_chatgpt_desktop, "texto")
        b.nota.configure(text="No ChatGPT, escolha Work, tecle Ctrl+O e cole o caminho do "
                              "acervo (já copiado).")
        return b

    def _rearranjar(self, _evento=None) -> None:
        """Três colunas em tela larga; uma embaixo da outra em tela estreita
        (os botões não quebram linha e seriam cortados)."""
        largura = self.grade.winfo_width()
        colunas = 3 if largura >= px(840) or largura <= 1 else 1
        if colunas == self._colunas:
            return
        self._colunas = colunas
        for c in range(3):
            self.grade.columnconfigure(c, weight=0, uniform="")
        for i, bloco in enumerate(self.blocos):
            if colunas == 3:
                bloco.grid(row=0, column=i, sticky="nsew",
                           padx=(0 if i == 0 else px(8), 0 if i == 2 else px(8)), pady=0)
                self.grade.columnconfigure(i, weight=1, uniform="blocos")
            else:
                bloco.grid(row=i, column=0, sticky="ew", padx=0,
                           pady=(0 if i == 0 else px(14), 0))
                self.grade.columnconfigure(0, weight=1)

    def _bloco_nuvem(self, pai):
        quadro = ttk.Frame(pai, style="Bloco.TFrame", padding=(px(20), px(18)))
        quadro.columnconfigure(1, weight=1)
        foto = estilo.imagem("bloco-nuvem", px(36))
        tk.Label(quadro, image=foto or "", background=estilo.PAPEL).grid(
            row=0, column=0, rowspan=2, sticky="nw", padx=(0, px(14)))
        ttk.Label(quadro, text="Espelho na nuvem (OneDrive ou Google Drive)",
                  font=estilo.FONTE_CARTAO).grid(row=0, column=1, sticky="w")
        texto = ttk.Label(quadro, foreground=estilo.TINTA_FRACA, justify="left", text=(
            "Uma cópia do acervo numa pasta sincronizada, para usar o ChatGPT ou o Claude pela "
            "web e pelo celular (conectores do OneDrive e do Google Drive). Só o que mudou é "
            "copiado, e nada é apagado lá. Confira antes se a política do tribunal permite."))
        texto.grid(row=1, column=1, sticky="ew", pady=(px(4), px(12)))
        estilo.acompanhar_largura(texto)
        linha = ttk.Frame(quadro)
        linha.grid(row=2, column=1, sticky="ew")
        linha.columnconfigure(0, weight=1)
        self.var_nuvem = tk.StringVar(value=self.cfg.texto("compartilhar", "pasta_nuvem"))
        self.c_nuvem = ttk.Combobox(linha, textvariable=self.var_nuvem, height=8)
        self.c_nuvem.grid(row=0, column=0, sticky="ew")
        self.c_nuvem.bind("<<ComboboxSelected>>", lambda _e: self._salvar_nuvem())
        self.c_nuvem.bind("<FocusOut>", lambda _e: self._salvar_nuvem())
        estilo.botao(linha, "Escolher…", self.escolher_nuvem).grid(row=0, column=1,
                                                                   padx=(px(8), 0))
        self.btn_espelhar = estilo.botao(linha, "Espelhar agora", self.espelhar, "tonal")
        self.btn_espelhar.grid(row=0, column=2, padx=(px(8), 0))
        self._vars["auto"] = tk.BooleanVar(value=self.cfg.flag("compartilhar",
                                                                "espelhar_automaticamente"))
        ttk.Checkbutton(quadro, text="Espelhar sozinho ao fim de cada download e de cada "
                                     "transcrição", variable=self._vars["auto"],
                        command=lambda: self.cfg.definir("compartilhar", "espelhar_automaticamente",
                                                         self._vars["auto"].get())).grid(
            row=3, column=1, sticky="w", pady=(px(10), 0))
        self.estado_nuvem = EstadoLinha(quadro, "", "neutro")
        self.estado_nuvem.grid(row=4, column=1, sticky="ew", pady=(px(6), 0))
        return quadro

    # ============================================================ estado
    def ao_mostrar(self) -> None:
        self._atualizar_pasta()
        if not self.tarefa_estado.ativa:
            self.em_segundo_plano(self.tarefa_estado, servicos.estado_ia, self.cfg,
                                  ao_concluir=self._aplicar_estado,
                                  ao_falhar=lambda e: log.warning("estado da IA: %s", e))

    def _atualizar_pasta(self) -> None:
        self.rotulo_pasta.configure(text=str(self.cfg.pasta_acervo))

    def _aplicar_estado(self, estado: dict) -> None:
        self.estado = estado
        code, cowork, chatgpt = self.blocos
        if estado.get("claude_code"):
            code.estado.definir("Instalado neste computador", "ok")
            self.btn_instalar_code.grid_remove()
            self.btn_code.state(["!disabled"])
        else:
            code.estado.definir("Não instalado (requer plano pago do Claude)", "neutro")
            self.btn_instalar_code.grid()
        nota = ""
        if estado.get("chave_no_ambiente"):
            nota = ("Há uma chave ANTHROPIC_API_KEY no Windows: o terminal abre sem ela, para "
                    "usar a sua assinatura (e não cobrança por uso).")
        code.nota.configure(text=nota)

        if estado.get("mcp_acervo"):
            cowork.estado.definir("Instalado · acervo conectado", "ok")
            self.btn_conectar.configure(text="Reconectar o acervo")
        elif estado.get("desktop"):
            cowork.estado.definir("Instalado · acervo ainda não conectado", "aviso")
            self.btn_conectar.configure(text="Conectar o acervo ao Claude")
        else:
            cowork.estado.definir("Claude Desktop não instalado", "neutro")
        self.btn_claude.configure(text="Abrir o Claude" if estado.get("desktop")
                                  else "Instalar o Claude Desktop")

        desktop = estado.get("chatgpt_desktop")
        partes = []
        if desktop:
            partes.append("App do ChatGPT instalado")
            self.btn_instalar_chatgpt.grid_remove()
        elif desktop is False:
            partes.append("App do ChatGPT não instalado")
            self.btn_instalar_chatgpt.grid()
        else:
            partes.append("App do ChatGPT: não verificado")
        if estado.get("codex"):
            partes.append("Codex instalado")
            self.btn_codex.grid()
        else:
            self.btn_codex.grid_remove()
        chatgpt.estado.definir(" · ".join(partes), "ok" if desktop or estado.get("codex")
                               else "neutro")

        acervo = estado.get("acervo") or {}
        texto = (f"{plural(acervo.get('processos', 0), 'processo')} e "
                 f"{plural(acervo.get('transcricoes', 0), 'transcrição', 'transcrições')}")
        if acervo.get("preparado"):
            texto += f" · preparado para IA {quando(acervo['preparado'])}"
            tipo = "ok"
        else:
            texto += " · ainda não preparado para IA"
            tipo = "aviso"
        self.estado_acervo.definir(texto, tipo)
        nuvens = estado.get("nuvens") or {}
        self.c_nuvem.configure(values=[str(p) for p in nuvens.values()])
        if not self.var_nuvem.get() and nuvens:
            self.estado_nuvem.definir("Encontrei: " + ", ".join(nuvens) + ". Escolha a pasta "
                                      "acima para ligar o espelho.", "info")
        elif not nuvens and not self.var_nuvem.get():
            self.estado_nuvem.definir("Nenhum OneDrive ou Google Drive encontrado neste "
                                      "computador.", "neutro")

    # ============================================================ ações
    def _recado(self, tipo: str, titulo: str, texto: str, acoes=()) -> None:
        self.faixa.destroy()
        self.faixa = Faixa(self.corpo, tipo, texto=texto, titulo=titulo)
        self.faixa.grid(row=1, column=0, sticky="ew", pady=(px(14), 0))
        for rotulo, comando in acoes:
            self.faixa.acao(rotulo, comando)
        componentes.mostrar_no_rolavel(self.faixa)

    def abrir_pasta(self) -> None:
        try:
            sistema.abrir_pasta(self.cfg.pasta_acervo)
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Abrir a pasta", str(erro))

    def copiar_caminho(self) -> None:
        if componentes.copiar(self.janela.raiz, str(self.cfg.pasta_acervo)):
            self.estado_acervo.definir("Caminho copiado. Cole com Ctrl+V onde precisar.", "ok")

    def preparar(self) -> None:
        from ..compartilhar import preparo

        tarefa = self.tarefa

        def progresso(feitos, total, descricao):
            self.postar("preparo", (feitos, total, descricao))

        def pronto(rel):
            self.btn_preparar.state(["!disabled"])
            tipo = "aviso" if rel.erros else "ok"
            self.estado_acervo.definir(f"Pronto: {rel.resumo}.", tipo)
            if rel.erros:
                self._recado("Aviso", "Alguns arquivos não puderam ser lidos",
                             "\n".join(rel.erros[:5]))
            self.ao_mostrar()

        def falhou(erro):
            self.btn_preparar.state(["!disabled"])
            self.estado_acervo.definir(f"Não consegui preparar: {erro}", "erro")

        if self.em_segundo_plano(tarefa, lambda: preparo.atualizar_contexto(
                self.cfg, progresso=progresso, cancelado=tarefa.parar.is_set),
                ao_concluir=pronto, ao_falhar=falhou):
            self.btn_preparar.state(["disabled"])
            self.estado_acervo.definir("Preparando o acervo…", "ocupado")

    def _preparar_rapido(self) -> None:
        """Garante CLAUDE.md, AGENTS.md e INDICE.md antes de abrir uma ferramenta
        (sem extrair o texto dos PDFs, que é o que demora)."""
        from ..compartilhar import preparo

        preparo.atualizar_contexto(self.cfg, extrair_texto=False)

    def _abrir_em_segundo_plano(self, funcao, ao_concluir=None) -> None:
        def trabalho():
            self._preparar_rapido()
            return funcao()
        self.em_segundo_plano(self.tarefa_abrir, trabalho, ao_concluir=ao_concluir or (lambda _r: None),
                              ao_falhar=self._falha_ao_abrir)

    def _falha_ao_abrir(self, erro) -> None:
        if isinstance(erro, FileNotFoundError):
            dialogos.informar(self.janela.raiz, "Não instalado", str(erro))
        else:
            dialogos.erro(self.janela.raiz, "Não consegui abrir", str(erro))

    def abrir_code(self) -> None:
        from ..compartilhar import claude

        acervo = self.cfg.pasta_acervo
        self._abrir_em_segundo_plano(lambda: claude.abrir_claude_code(acervo))

    def instalar_code(self) -> None:
        from ..compartilhar import claude

        try:
            claude.instalar_claude_code()
        except Exception as erro:
            componentes.copiar(self.janela.raiz, claude.COMANDO_INSTALAR_CODE)
            dialogos.informar(self.janela.raiz, "Instalar o Claude Code",
                              f"Não consegui abrir o instalador ({erro}).\n\nAbra o PowerShell e "
                              f"cole o comando (já copiado):\n\n{claude.COMANDO_INSTALAR_CODE}")
            return
        self._recado("Info", "Instalação do Claude Code",
                     "O instalador oficial abriu numa janela do PowerShell. Ao terminar, feche-a "
                     "e clique em “Abrir o acervo no Claude Code”; no primeiro uso, entre com a "
                     "sua conta do Claude.")

    def abrir_cowork(self) -> None:
        acervo = self.cfg.pasta_acervo
        pedido = f"Pasta do acervo: {acervo}\n\n{servicos.prompt_inicial()}"
        componentes.copiar(self.janela.raiz, pedido)

        def feito(resultado):
            if resultado == "cowork":
                self._recado("Info", "Abrindo o Cowork",
                             "O Claude vai pedir para confirmar o acesso à pasta do acervo. "
                             "Depois, cole o pedido inicial (Ctrl+V): ele já está copiado.")
            elif resultado == "baixar":
                self._recado("Aviso", "O Claude Desktop não está instalado",
                             "Abri a página de download. Instale, entre com a sua conta (o "
                             "Cowork exige plano pago) e clique de novo em “Abrir no Cowork”.")
            else:
                self._recado("Info", "Abrindo o Claude",
                             "No Cowork, escolha a pasta do acervo (o caminho e o pedido "
                             "inicial estão copiados: cole com Ctrl+V).")
        self._abrir_em_segundo_plano(lambda: servicos.abrir_no_cowork(acervo), feito)

    def conectar_claude(self) -> None:
        from ..compartilhar import claude

        acervo = self.cfg.pasta_acervo

        def pronto(alterados):
            if alterados:
                self._recado("Sucesso", "Acervo conectado ao Claude Desktop",
                             "Feche e abra o Claude Desktop para ele carregar o conector "
                             "“assessor-integrado” (ferramentas de leitura dos autos, só leitura).")
            else:
                self._recado("Info", "O acervo já estava conectado",
                             "Se o conector não aparece, feche o Claude Desktop pela bandeja do "
                             "Windows (perto do relógio) e abra de novo.")
            self.ao_mostrar()

        def falhou(erro):
            dialogos.erro(self.janela.raiz, "Não consegui conectar", _maiuscula(str(erro)))

        self.em_segundo_plano(self.tarefa_abrir, claude.registrar_mcp, acervo,
                              ao_concluir=pronto, ao_falhar=falhou)

    def abrir_claude(self) -> None:
        from ..compartilhar import claude

        try:
            if self.estado.get("desktop"):
                claude.abrir_claude_desktop()
            else:
                claude.instalar_claude_desktop()
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Claude Desktop", str(erro))

    def plugin_cowork(self) -> None:
        destino = self.cfg.pasta_acervo.parent / PASTA_PACOTES

        def pronto(arquivo):
            if arquivo is None:
                dialogos.informar(self.janela.raiz, "Plugin para o Cowork",
                                  "Esta versão do programa ainda não gera o plugin.")
                return
            sistema.abrir_pasta(Path(arquivo).parent, Path(arquivo))
            self._recado("Sucesso", "Plugin gerado",
                         f"{Path(arquivo).name}. No Claude: Personalizar › Plugins › Adicionar › "
                         "Enviar plugin, e escolha este arquivo. Ele ensina o Cowork a trabalhar "
                         "com o acervo (citar as folhas, conferir as transcrições).")
        self.em_segundo_plano(self.tarefa_abrir, servicos.gerar_plugin_cowork, destino,
                              ao_concluir=pronto, ao_falhar=self._falha_ao_abrir)

    def abrir_work(self) -> None:
        acervo = self.cfg.pasta_acervo
        componentes.copiar(self.janela.raiz, str(acervo))

        def feito(resultado):
            if resultado == "web":
                self._recado("Info", "ChatGPT aberto no navegador",
                             "Pelo navegador, o ChatGPT não lê pastas do computador. Instale o "
                             "app do ChatGPT para Windows para usar o modo Work com o acervo - "
                             "ou use “Gerar pacote para o ChatGPT”.",
                             [("Instalar o app do ChatGPT", servicos.instalar_chatgpt_desktop)])
            else:
                self._recado("Info", "Abrindo o ChatGPT",
                             "No app do ChatGPT, escolha Work, tecle Ctrl+O e cole o caminho do "
                             "acervo (Ctrl+V; ele já está copiado). O ChatGPT lê o AGENTS.md "
                             "da pasta.")
        self._abrir_em_segundo_plano(lambda: servicos.abrir_chatgpt_work(acervo), feito)

    def abrir_codex(self) -> None:
        from ..compartilhar import chatgpt

        acervo = self.cfg.pasta_acervo
        self._abrir_em_segundo_plano(lambda: chatgpt.abrir_codex(acervo))

    def pacote(self) -> None:
        from ..compartilhar import chatgpt

        acervo = self.cfg.pasta_acervo
        destino = acervo.parent / PASTA_PACOTES

        def pronto(resultado):
            pasta, arquivo = resultado
            sistema.abrir_pasta(Path(arquivo).parent, Path(arquivo))
            self._recado("Sucesso", "Pacote pronto",
                         f"{Path(arquivo).name}. Arraste o .zip para uma conversa ou um Projeto "
                         "do ChatGPT. Ele leva os autos, o texto com as folhas e as instruções.")

        def falhou(erro):
            if isinstance(erro, LookupError):
                dialogos.informar(self.janela.raiz, "Acervo vazio",
                                  "Ainda não há processo nem transcrição no acervo.")
            else:
                dialogos.erro(self.janela.raiz, "Não consegui gerar o pacote", str(erro))

        if self.em_segundo_plano(self.tarefa, chatgpt.gerar_pacote, acervo, destino,
                                 ao_concluir=pronto, ao_falhar=falhou):
            self._recado("Info", "Gerando o pacote…", "Copiando os autos e os textos. Pode "
                                                       "continuar usando o programa.")

    # ------------------------------------------------------------- nuvem
    def _salvar_nuvem(self) -> None:
        valor = self.var_nuvem.get().strip()
        if valor != self.cfg.texto("compartilhar", "pasta_nuvem"):
            self.cfg.definir("compartilhar", "pasta_nuvem", valor)

    def escolher_nuvem(self) -> None:
        nova = dialogos.escolher_pasta(self.janela.raiz, "Pasta da nuvem (OneDrive ou Google Drive)",
                                       Path(self.var_nuvem.get()) if self.var_nuvem.get() else None)
        if nova:
            self.var_nuvem.set(str(nova))
            self._salvar_nuvem()

    def espelhar(self) -> None:
        from ..compartilhar import nuvem

        self._salvar_nuvem()
        destino = self.var_nuvem.get().strip()
        if not destino:
            dialogos.informar(self.janela.raiz, "Espelho na nuvem",
                              "Escolha antes a pasta do OneDrive ou do Google Drive.")
            return
        tarefa = self.tarefa_nuvem

        def progresso(feitos, total, nome):
            self.postar("nuvem", (feitos, total, nome))

        def pronto(resultado):
            copiados, iguais = resultado
            self.btn_espelhar.state(["!disabled"])
            self.estado_nuvem.definir(f"{plural(copiados, 'arquivo copiado', 'arquivos copiados')}"
                                      f", {iguais} sem mudança · pasta "
                                      f"“{nuvem.SUBPASTA}”", "ok")

        def falhou(erro):
            self.btn_espelhar.state(["!disabled"])
            self.estado_nuvem.definir(f"Não consegui espelhar: {erro}", "erro")

        if self.em_segundo_plano(tarefa, nuvem.espelhar, self.cfg.pasta_acervo, Path(destino),
                                 progresso, tarefa.parar.is_set, ao_concluir=pronto,
                                 ao_falhar=falhou):
            self.btn_espelhar.state(["disabled"])
            self.estado_nuvem.definir("Copiando…", "ocupado")

    # ============================================================ eventos
    def ao_evento(self, tipo: str, dado) -> None:
        if tipo == "preparo":
            feitos, total, descricao = dado
            self.estado_acervo.definir(f"Preparando: {descricao} ({min(feitos + 1, total)} de "
                                       f"{total})" if total else "Preparando…", "ocupado")
        elif tipo == "nuvem":
            feitos, total, nome = dado
            self.estado_nuvem.definir(f"Copiando {feitos} de {total}: {nome}", "ocupado")

    def indicador(self):
        if self.tarefa.ativa or self.tarefa_nuvem.ativa:
            return ("", estilo.AZUL)
        return None

    def resumo_ao_vivo(self):
        if self.tarefa.ativa:
            return ("Preparando o acervo para a IA…", "ocupado")
        if self.tarefa_nuvem.ativa:
            return ("Espelhando o acervo na nuvem…", "ocupado")
        return None


def _maiuscula(texto: str) -> str:
    texto = (texto or "").strip()
    return texto[:1].upper() + texto[1:]
