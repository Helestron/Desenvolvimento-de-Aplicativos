"""Tela inicial: as três funções do programa, à vista, em três cartões.

Requisito do usuário: o layout inicial mostra de forma APARENTE as três
funções principais - Baixar processos, Transcrever audiência e Compartilhar
com IA - e o acesso é simples. Cada cartão traz o ícone, o nome, uma frase
do que faz, o botão e uma linha de estado que já responde "está pronto?"
("Microfone pronto · modelo small instalado"). O cartão inteiro é clicável.

Abaixo, a atividade recente (últimos lotes e transcrições, com Abrir) e, se
faltar algo da instalação, um aviso amarelo com o botão que corrige.

O estado dos cartões é apurado numa thread (procura arquivos, consulta o
PortAudio): a tela aparece na hora e as linhas se completam em seguida.
"""

from __future__ import annotations

import logging
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from ..nucleo import caminhos, sistema
from . import componentes, dialogos, estilo, servicos
from .componentes import Cartao, EstadoLinha, Faixa, Pagina, plural, quando
from .estilo import px

log = logging.getLogger("interface.inicio")

CARTOES = (
    ("baixar", "cartao-baixar", "Baixar processos",
     "Abra a relação (Excel, Word, PDF…) e baixe os autos do e-SAJ ou do eProc com o seu "
     "acesso: um PDF por processo, nomeado pelo número.",
     "Baixar processos"),
    ("transcrever", "cartao-transcrever", "Transcrever audiência",
     "Transcrição simultânea pelo microfone, com quem fala marcado por você. Sai em Word, "
     "com o número do processo no nome.",
     "Iniciar transcrição"),
    ("compartilhar", "cartao-compartilhar", "Compartilhar com IA",
     "Leve o acervo ao Claude Code, ao Claude (Cowork) e ao ChatGPT Work, já com as "
     "instruções de trabalho.",
     "Compartilhar acervo"),
)

INTERVALO_MICROFONE_S = 60     # listar microfones acorda o PortAudio: não a cada visita


class PaginaInicio(Pagina):
    nome = "inicio"
    titulo = "Início"
    icone = "inicio"

    def montar(self) -> None:
        self._ultima_consulta = 0.0
        self._microfones: tuple[float, list | None, str] = (0.0, None, "")
        self.tarefa_estado = self.nova_tarefa("Atualizar a tela inicial", essencial=False)
        self.tarefa_modelo = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        quadro, corpo = componentes.coluna_rolavel(self, margem=px(36))
        quadro.grid(row=0, column=0, sticky="nsew")
        corpo.columnconfigure(0, weight=1)
        self.corpo = corpo

        # --- saudação
        topo = ttk.Frame(corpo)
        topo.grid(row=0, column=0, sticky="ew", pady=(px(26), px(20)))
        self.saudacao = ttk.Label(topo, text="", font=estilo.FONTE_SAUDACAO)
        self.saudacao.pack(anchor="w")
        frase = ttk.Label(topo, foreground=estilo.TINTA_FRACA, justify="left",
                          text="O que vamos fazer agora? Tudo o que o programa produz fica "
                               "reunido na pasta do acervo.")
        frase.pack(anchor="w", fill="x", pady=(px(4), 0))
        estilo.acompanhar_largura(frase)

        # --- os três cartões
        linha = ttk.Frame(corpo)
        linha.grid(row=1, column=0, sticky="ew")
        linha.columnconfigure((0, 1, 2), weight=1, uniform="cartoes")
        self.estados: dict[str, EstadoLinha] = {}
        self.botoes: dict[str, ttk.Button] = {}
        for i, (destino, icone, titulo, descricao, acao) in enumerate(CARTOES):
            cartao = self._cartao(linha, destino, icone, titulo, descricao, acao)
            cartao.grid(row=0, column=i, sticky="nsew",
                        padx=(0 if i == 0 else px(8), 0 if i == 2 else px(8)))

        # --- aviso de instalação (aparece só quando falta algo)
        self.aviso = Faixa(corpo, "Aviso", titulo="", texto="")
        self.aviso.grid(row=2, column=0, sticky="ew", pady=(px(20), 0))
        self.aviso.grid_remove()
        self._pendencias: list = []

        # --- atividade recente
        titulo = ttk.Frame(corpo)
        titulo.grid(row=3, column=0, sticky="ew", pady=(px(26), px(8)))
        titulo.columnconfigure(0, weight=1)
        ttk.Label(titulo, text="Atividade recente", font=estilo.FONTE_SECAO).grid(
            row=0, column=0, sticky="w")
        estilo.botao(titulo, "Abrir a pasta do acervo", self._abrir_acervo, "texto",
                     pequeno=True).grid(row=0, column=1, sticky="e")
        self.recentes = ttk.Frame(corpo, style="Bloco.TFrame", padding=(px(6), px(4)))
        self.recentes.grid(row=4, column=0, sticky="ew")
        self.recentes.columnconfigure(0, weight=1)
        self._preencher_recentes([], carregando=True)

    # -------------------------------------------------------------- cartões
    def _cartao(self, pai, destino, icone, titulo, descricao, acao) -> Cartao:
        ir = lambda d=destino: self.janela.mostrar(d)  # noqa: E731
        cartao = Cartao(pai, comando=ir, padding=(px(24), px(22), px(24), px(20)))
        cartao.columnconfigure(0, weight=1)
        cartao.rowconfigure(3, weight=1)
        foto = estilo.imagem(icone, px(56))
        tk.Label(cartao, image=foto or "", background=estilo.PAPEL, borderwidth=0).grid(
            row=0, column=0, sticky="w")
        nome = ttk.Label(cartao, text=titulo, font=estilo.FONTE_CARTAO, justify="left")
        nome.grid(row=1, column=0, sticky="ew", pady=(px(16), px(6)))
        estilo.acompanhar_largura(nome)
        texto = ttk.Label(cartao, text=descricao, foreground=estilo.TINTA_FRACA, justify="left")
        texto.grid(row=2, column=0, sticky="new")
        estilo.acompanhar_largura(texto)
        estado = EstadoLinha(cartao, "Verificando…", "neutro")
        estado.grid(row=4, column=0, sticky="ew", pady=(px(16), px(14)))
        self.estados[destino] = estado
        botao = estilo.botao(cartao, acao, ir, "principal")
        botao.grid(row=5, column=0, sticky="w")
        self.botoes[destino] = botao
        cartao.ligar_filhos()
        return cartao

    # ---------------------------------------------------------- ciclo de vida
    def ao_mostrar(self) -> None:
        nome = self.cfg.texto("geral", "nome_usuario")
        hora = datetime.now().hour
        cumprimento = "Bom dia" if 5 <= hora < 12 else ("Boa tarde" if 12 <= hora < 18
                                                         else "Boa noite")
        self.saudacao.configure(text=f"{cumprimento}, {nome}" if nome else cumprimento)
        self._estados_ao_vivo()
        if time.monotonic() - self._ultima_consulta > 3 and not self.tarefa_estado.ativa:
            self._ultima_consulta = time.monotonic()
            self.em_segundo_plano(self.tarefa_estado, self._apurar, ao_concluir=self._aplicar,
                                  ao_falhar=lambda e: log.warning("estado da tela inicial: %s", e))

    def indicador(self):
        return None            # a tela inicial não roda trabalho próprio visível

    def _estados_ao_vivo(self) -> None:
        """O que as outras páginas estão fazendo agora sobrepõe o estado
        apurado (ex.: 'Baixando: 12 de 37')."""
        for nome in ("baixar", "transcrever", "compartilhar"):
            pagina = self.janela.paginas.get(nome)
            resumo = getattr(pagina, "resumo_ao_vivo", None)
            if callable(resumo):
                try:
                    atual = resumo()
                except Exception:
                    atual = None
                if atual:
                    self.estados[nome].definir(*atual)

    # --------------------------------------------------------- em segundo plano
    def _apurar(self) -> dict:
        cfg = self.cfg
        dados: dict = {}

        # Cada consulta por si: um relatório ilegível (salvo pelo Excel, por
        # exemplo) não pode deixar os três cartões em "Verificando…" e esconder
        # o aviso de pendências.
        def consultar(chave, funcao, padrao):
            try:
                dados[chave] = funcao()
            except Exception as erro:
                log.warning("tela inicial: não consegui apurar %s: %s", chave, erro)
                dados[chave] = padrao

        consultar("lotes", lambda: servicos.ultimos_lotes(cfg, 4), [])
        consultar("transcricoes", lambda: servicos.transcricoes_recentes(cfg, 4), [])
        modelo = cfg.texto("transcricao", "modelo_ao_vivo") or "small"
        consultar("modelo", lambda: (modelo, servicos.modelo_instalado(modelo)), (modelo, False))
        momento, lista, erro = self._microfones
        transcrever = self.janela.paginas.get("transcrever")
        gravando = bool(transcrever is not None and transcrever.tarefa_sessao.ativa)
        # com a audiência gravando, o microfone está em uso: não mexe no PortAudio
        if not gravando and (lista is None or time.monotonic() - momento > INTERVALO_MICROFONE_S):
            try:
                lista, erro = servicos.listar_microfones(), ""
            except Exception as e:
                lista, erro = [], str(e)
            self._microfones = (time.monotonic(), lista, erro)
        dados["microfones"] = (lista or [], erro)
        consultar("ia", lambda: servicos.estado_ia(cfg), {})
        consultar("pendencias", lambda: servicos.pendencias(cfg), [])
        consultar("recuperaveis", lambda: len(servicos.recuperaveis(cfg)), 0)
        return dados

    def _aplicar(self, dados: dict) -> None:
        # --- Baixar
        lotes = dados.get("lotes") or []
        if lotes:
            ultimo = lotes[0]
            texto = f"Último lote: {plural(ultimo.total, 'processo')}, {quando(ultimo.quando)}"
            tipo = "ok"
            if ultimo.falhas:
                texto += f" · {ultimo.falhas} com problema"
                tipo = "aviso"
        else:
            texto, tipo = "Nenhum lote baixado ainda", "neutro"
        self.estados["baixar"].definir(texto, tipo)

        # --- Transcrever
        modelo, instalado = dados.get("modelo", ("small", False))
        lista, erro = dados.get("microfones", ([], ""))
        partes = []
        if erro:
            partes.append("Microfone indisponível")
            tipo = "erro"
        elif not lista:
            partes.append("Nenhum microfone encontrado")
            tipo = "erro"
        else:
            partes.append("Microfone pronto")
            tipo = "ok"
        if instalado:
            partes.append(f"modelo {modelo} instalado")
        else:
            partes.append(f"modelo {modelo} ainda não baixado")
            tipo = "aviso" if tipo == "ok" else tipo
        if dados.get("recuperaveis"):
            partes.append("há transcrição interrompida a recuperar")
            tipo = "aviso"
        self.estados["transcrever"].definir(" · ".join(partes), tipo)

        # --- Compartilhar
        ia = dados.get("ia") or {}
        claude = ia.get("claude") or {}
        code = "instalado" if claude.get("claude_code") else "não instalado"
        if ia.get("mcp_acervo"):
            desktop = "conectado"
        elif claude.get("desktop"):
            desktop = "instalado"
        else:
            desktop = "não instalado"
        tipo = "ok" if claude.get("claude_code") or claude.get("desktop") else "neutro"
        self.estados["compartilhar"].definir(f"Claude Code: {code} · Claude Desktop: {desktop}",
                                             tipo)

        self._estados_ao_vivo()
        self._preencher_recentes(self._juntar_recentes(dados))
        self._mostrar_pendencias(dados.get("pendencias") or [])

    # --------------------------------------------------------- atividade
    def _juntar_recentes(self, dados) -> list[tuple]:
        itens = []
        for lote in dados.get("lotes") or []:
            detalhe = f"{plural(lote.baixados, 'processo')} na pasta"
            if lote.falhas:
                detalhe += f" · {lote.falhas} com problema"
            itens.append((lote.quando, "nav-baixar", f"Lote “{lote.nome}”", detalhe,
                          "Abrir pasta", lambda p=lote.pasta: self._abrir(p, pasta=True)))
        for doc in dados.get("transcricoes") or []:
            try:
                momento = datetime.fromtimestamp(doc.stat().st_mtime)
            except OSError:
                continue
            itens.append((momento, "nav-transcrever", f"Audiência · {doc.stem}",
                          "Transcrição em Word", "Abrir",
                          lambda p=doc: self._abrir(p)))
        itens.sort(key=lambda i: i[0], reverse=True)
        return itens[:5]

    def _preencher_recentes(self, itens: list, carregando: bool = False) -> None:
        for w in self.recentes.winfo_children():
            w.destroy()
        if not itens:
            vazio = ttk.Frame(self.recentes, padding=(px(14), px(16)))
            vazio.grid(row=0, column=0, sticky="ew")
            texto = ("Procurando…" if carregando else
                     "Nada por aqui ainda. Os lotes baixados e as transcrições das audiências "
                     "aparecem nesta lista, para abrir com um clique.")
            r = ttk.Label(vazio, text=texto, foreground=estilo.TINTA_FRACA, justify="left")
            r.pack(anchor="w", fill="x")
            estilo.acompanhar_largura(r)
            return
        for i, (momento, icone, titulo, detalhe, acao, comando) in enumerate(itens):
            if i:
                componentes.divisoria(self.recentes).grid(row=2 * i - 1, column=0, sticky="ew",
                                                          padx=px(12))
            linha = ttk.Frame(self.recentes, padding=(px(12), px(9)))
            linha.grid(row=2 * i, column=0, sticky="ew")
            linha.columnconfigure(1, weight=1)
            foto = estilo.imagem(icone, px(20))
            tk.Label(linha, image=foto or "", background=estilo.PAPEL).grid(
                row=0, column=0, rowspan=2, padx=(0, px(14)))
            ttk.Label(linha, text=titulo, font=estilo.FONTE_NEGRITO).grid(row=0, column=1,
                                                                           sticky="w")
            ttk.Label(linha, text=f"{quando(momento)} · {detalhe}", foreground=estilo.TINTA_FRACA,
                      font=estilo.FONTE_NOTA).grid(row=1, column=1, sticky="w")
            estilo.botao(linha, acao, comando, "apoio", pequeno=True).grid(
                row=0, column=2, rowspan=2, sticky="e")

    # ----------------------------------------------------------- pendências
    def _mostrar_pendencias(self, pendencias: list) -> None:
        self._pendencias = pendencias
        if not pendencias:
            self.aviso.grid_remove()
            return
        primeira = pendencias[0]
        if primeira.chave == "pastas":
            titulo = "Confira as pastas do acervo e dos sigilosos"
        else:
            titulo = ("Falta uma coisa na instalação" if len(pendencias) == 1
                      else f"Faltam {len(pendencias)} coisas na instalação")
        texto = "\n".join(p.texto for p in pendencias)
        self.aviso.definir(texto=texto, titulo=titulo)
        self.aviso.limpar_acoes()
        if primeira.chave == "modelo":
            self.aviso.acao(primeira.acao, self._baixar_modelo)
        elif primeira.chave == "pacotes":
            self.aviso.acao(primeira.acao, lambda: self._abrir(caminhos.RAIZ, pasta=True))
        elif primeira.chave == "pastas":
            self.aviso.acao(primeira.acao, self._abrir_geral)
        self.aviso.grid()

    def _abrir_geral(self) -> None:
        self.janela.mostrar("config")
        config = self.janela.paginas.get("config")
        if config is not None and hasattr(config, "abas"):
            config.abas.select(0)

    def _baixar_modelo(self) -> None:
        config = self.janela.pagina("config")
        if config is not None and hasattr(config, "baixar_modelo_ao_vivo"):
            self.janela.mostrar("config")
            config.baixar_modelo_ao_vivo()

    # --------------------------------------------------------------- ações
    def _abrir(self, caminho: Path, pasta: bool = False) -> None:
        try:
            if pasta:
                sistema.abrir_pasta(caminho)
            else:
                sistema.abrir_arquivo(caminho)
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Abrir", f"Não consegui abrir {caminho}:\n{erro}")

    def _abrir_acervo(self) -> None:
        self._abrir(self.cfg.pasta_acervo, pasta=True)
