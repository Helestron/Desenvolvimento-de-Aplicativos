"""Peças da interface usadas por várias páginas.

    Pagina ............ base de cada página (eventos, tarefas, indicador)
    estrutura ......... cabeçalho + corpo rolável + rodapé fixo de uma página
    coluna_rolavel .... coluna que rola quando o conteúdo passa da altura
    BarraLateral ...... a navegação, com indicador de tarefa em cada item
    Cartao ............ quadro de cantos macios, clicável, com realce
    Faixa ............. recado colorido (atenção, sucesso, erro, informação)
    EstadoLinha ....... ponto colorido + frase curta ("Microfone pronto")
    Medidor ........... nível do microfone
    Detalhes .......... registro técnico recolhível, com limite de linhas
    tabela ............ Treeview com rolagem, num quadro de cantos macios
    copiar ............ área de transferência
"""

from __future__ import annotations

import logging
import tkinter as tk
import weakref
from tkinter import ttk

from . import estilo
from .estilo import px

log = logging.getLogger("interface")

MAX_LINHAS_REGISTRO = 2000


# =================================================================== página
class Pagina(ttk.Frame):
    """Base das páginas. Cada página roda o próprio trabalho (Tarefa) e
    recebe os eventos dele pela fila da janela, na thread do Tk."""

    nome = ""
    titulo = ""
    icone = ""
    marca_log = ""            # "[baixar]": linhas do registro que esta página mostra

    def __init__(self, pai, janela):
        super().__init__(pai, style="TFrame")
        self.janela = janela
        self.tarefas: list = []
        self.detalhes: Detalhes | None = None
        self.montar()

    # --------------------------------------------------------- a preencher
    def montar(self) -> None:                                  # pragma: no cover
        raise NotImplementedError

    def ao_mostrar(self) -> None:
        """A página acabou de aparecer (atualize o que for barato)."""

    def ao_esconder(self) -> None:
        """Outra página tomou o lugar desta."""

    def ao_evento(self, tipo: str, dado) -> None:
        """Evento postado por uma thread de trabalho (já na thread do Tk)."""

    def indicador(self) -> tuple[str, str] | None:
        """(texto, cor) à direita do item na barra lateral; None = nada."""
        if self.ocupada:
            return ("", estilo.AZUL)
        return None

    def trabalho_em_andamento(self) -> list[str]:
        """O que se perderia ao fechar agora (para a pergunta ao sair)."""
        return [t.nome for t in self.tarefas if t.ativa]

    def antes_de_fechar(self) -> None:
        """Pede a parada de tudo (a janela espera depois)."""
        for t in self.tarefas:
            if t.ativa:
                t.pedir_parada()

    def atalho(self, evento) -> bool:
        """Tecla de função (F1...F12) com esta página aberta."""
        return False

    # -------------------------------------------------------------- apoio
    @property
    def cfg(self):
        return self.janela.cfg

    @property
    def ocupada(self) -> bool:
        return any(t.ativa for t in self.tarefas)

    def nova_tarefa(self, nome: str, recursos: tuple = ()):
        from .tarefas import Tarefa

        t = Tarefa(nome, recursos, self.janela.recursos,
                   ao_terminar=lambda tarefa: self.postar("_tarefa_fim", tarefa))
        self.tarefas.append(t)
        return t

    def postar(self, tipo: str, dado=None) -> None:
        """Seguro em qualquer thread: o evento chega em ao_evento()."""
        self.janela.postar(self.nome, tipo, dado)

    def em_segundo_plano(self, tarefa, alvo, *args, ao_concluir=None, ao_falhar=None) -> bool:
        """Roda alvo(*args) na tarefa; o resultado volta pela fila.

        ao_concluir(resultado) e ao_falhar(erro) rodam na thread do Tk. Se a
        tarefa não puder começar (recurso ocupado), avisa e devolve False.
        """
        def corpo():
            try:
                resultado = alvo(*args)
            except BaseException as erro:              # noqa: BLE001
                if ao_falhar is not None:
                    self.postar("_chamar", (ao_falhar, erro))
                else:
                    log.exception("falha em segundo plano")
                    self.postar("_chamar", (self.janela.erro_inesperado, erro))
                return
            if ao_concluir is not None:
                self.postar("_chamar", (ao_concluir, resultado))

        recusa = tarefa.iniciar(corpo)
        if recusa:
            from . import dialogos

            dialogos.informar(self.janela.raiz, "Aguarde um instante", recusa)
            return False
        return True

    def receber_log(self, linhas: list[str]) -> None:
        if self.detalhes is not None:
            self.detalhes.escrever(linhas)

    def tratar_evento(self, tipo: str, dado) -> None:
        """Despacho interno: '_chamar' executa uma função na thread do Tk."""
        if tipo == "_chamar":
            funcao, argumento = dado
            funcao(argumento)
            return
        if tipo == "_tarefa_fim":
            self.janela.atualizar_indicadores()
            self.ao_evento(tipo, dado)
            return
        self.ao_evento(tipo, dado)


def estrutura(pagina: ttk.Frame, titulo: str, subtitulo: str = "", rolavel: bool = True,
              rodape: bool = False, acoes_cabecalho: bool = False):
    """Monta o esqueleto padrão de uma página.

    Devolve (corpo, rodape, acoes): 'corpo' é onde vão as seções (rola se
    preciso), 'rodape' é a faixa fixa embaixo (ou None) e 'acoes' é um
    quadro à direita do título (ou None).
    """
    margem = px(32)
    pagina.columnconfigure(0, weight=1)
    pagina.rowconfigure(1, weight=1)

    topo = ttk.Frame(pagina)
    topo.grid(row=0, column=0, sticky="ew", padx=margem, pady=(px(24), px(10)))
    topo.columnconfigure(0, weight=1)
    ttk.Label(topo, text=titulo, font=estilo.FONTE_PAGINA).grid(row=0, column=0, sticky="w")
    if subtitulo:
        sub = ttk.Label(topo, text=subtitulo, foreground=estilo.TINTA_FRACA, justify="left")
        sub.grid(row=1, column=0, sticky="ew", pady=(px(2), 0))
        estilo.acompanhar_largura(sub)
    acoes = None
    if acoes_cabecalho:
        acoes = ttk.Frame(topo)
        acoes.grid(row=0, column=1, rowspan=2, sticky="e", padx=(px(12), 0))

    if rolavel:
        quadro, corpo = coluna_rolavel(pagina, margem=margem)
        quadro.grid(row=1, column=0, sticky="nsew")
    else:
        corpo = ttk.Frame(pagina)
        corpo.grid(row=1, column=0, sticky="nsew", padx=margem)

    base = None
    if rodape:
        linha = divisoria(pagina)
        linha.grid(row=2, column=0, sticky="ew")
        base = ttk.Frame(pagina)
        base.grid(row=3, column=0, sticky="ew", padx=margem, pady=(px(12), px(16)))
    return corpo, base, acoes


def secao(pai, titulo: str, numero: str | int | None = None, nota: str = "") -> ttk.Frame:
    """Título de seção (com o número do passo num círculo azul-pálido)."""
    quadro = ttk.Frame(pai)
    if numero is not None:
        bolinha = tk.Canvas(quadro, width=px(26), height=px(26), highlightthickness=0,
                            background=estilo.PAPEL, borderwidth=0)
        bolinha.create_oval(1, 1, px(26) - 1, px(26) - 1, fill=estilo.AZUL_PALIDO,
                            outline=estilo.AZUL_PALIDO)
        bolinha.create_text(px(13), px(13), text=str(numero), fill=estilo.AZUL_PROFUNDO,
                            font=estilo.FONTE_NEGRITO)
        bolinha.grid(row=0, column=0, sticky="w", padx=(0, px(10)))
    ttk.Label(quadro, text=titulo, font=estilo.FONTE_SECAO).grid(row=0, column=1, sticky="w")
    quadro.columnconfigure(1, weight=1)
    if nota:
        n = ttk.Label(quadro, text=nota, foreground=estilo.TINTA_FRACA, justify="left")
        n.grid(row=1, column=1, sticky="ew", pady=(px(2), 0))
        estilo.acompanhar_largura(n)
    return quadro


# ============================================================ rolagem
_rolaveis: "weakref.WeakSet[tk.Canvas]" = weakref.WeakSet()
_ROLAM_SOZINHOS = ("Text", "Treeview", "Listbox", "TCombobox", "Scrollbar", "TScrollbar")


def instalar_roda(raiz: tk.Misc) -> None:
    """Uma ligação só para a roda do mouse, na janela inteira.

    A base ligava a roda ao entrar na coluna e desligava ao sair - mas sair
    da tela para um filho dela também gera <Leave>, e a roda parava de
    funcionar justamente sobre o conteúdo. Aqui, a cada giro, procura-se o
    que está sob o ponteiro: tabela e caixa de texto rolam a si mesmas (pela
    ligação de classe do Tk); o resto rola a coluna que o contém.
    """
    def girar(evento, passos: int | None = None):
        try:
            alvo = raiz.winfo_containing(evento.x_root, evento.y_root)
        except (tk.TclError, KeyError):
            return None
        if passos is None:
            delta = getattr(evento, "delta", 0) or 0
            if not delta:
                return None
            # Windows: múltiplos de 120; macOS: valores pequenos
            passos = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        w = alvo
        while w is not None:
            if w in _rolaveis:
                caixa = w.bbox("all")
                if caixa and caixa[3] > w.winfo_height() + 2:
                    w.yview_scroll(passos * 3, "units")
                return "break"
            if w.winfo_class() in _ROLAM_SOZINHOS:
                return None
            w = getattr(w, "master", None)
        return None

    raiz.bind_all("<MouseWheel>", girar, add="+")
    raiz.bind_all("<Button-4>", lambda e: girar(e, -1), add="+")
    raiz.bind_all("<Button-5>", lambda e: girar(e, 1), add="+")


def coluna_rolavel(pai, margem: int = 0, fundo: str = estilo.PAPEL):
    """Uma coluna que rola quando o conteúdo passa da altura disponível.

    Devolve (quadro, dentro): ponha o quadro no pai e os filhos em 'dentro'.
    A barra de rolagem é SOBREPOSTA à margem direita (place), e não uma
    coluna do grid: assim mostrá-la ou escondê-la não muda a largura do
    conteúdo - o que, com texto que quebra linha pela largura, entrava em
    laço (a barra aparece, o texto quebra, a altura muda, a barra some...).
    """
    quadro = tk.Frame(pai, background=fundo, borderwidth=0, highlightthickness=0)
    quadro.columnconfigure(0, weight=1)
    quadro.rowconfigure(0, weight=1)

    tela = tk.Canvas(quadro, highlightthickness=0, borderwidth=0, background=fundo,
                     yscrollincrement=px(20))
    tela.grid(row=0, column=0, sticky="nsew")
    _rolaveis.add(tela)

    barra = ttk.Scrollbar(quadro, orient="vertical", command=tela.yview)
    tela.configure(yscrollcommand=barra.set)

    # À direita, espaço para a barra sobreposta não cobrir o conteúdo.
    dentro = ttk.Frame(tela, padding=(margem, 0, max(margem, px(20)), px(24)))
    janela = tela.create_window((0, 0), window=dentro, anchor="nw")

    def ajustar(_evento=None):
        tela.configure(scrollregion=(0, 0, tela.winfo_width(), dentro.winfo_reqheight()))
        precisa = dentro.winfo_reqheight() > tela.winfo_height() + 2
        if precisa and not barra.winfo_ismapped():
            barra.place(relx=1.0, rely=0, relheight=1.0, anchor="ne", x=-px(4))
        elif not precisa and barra.winfo_ismapped():
            barra.place_forget()
            tela.yview_moveto(0)

    def acompanhar_largura(evento):
        tela.itemconfigure(janela, width=evento.width)
        ajustar()

    dentro.bind("<Configure>", ajustar, add="+")
    tela.bind("<Configure>", acompanhar_largura, add="+")
    quadro.tela = tela             # type: ignore[attr-defined]
    quadro.topo = lambda: tela.yview_moveto(0)  # type: ignore[attr-defined]
    return quadro, dentro


def mostrar_no_rolavel(widget) -> None:
    """Rola a coluna que contém o widget até ele ficar visível."""
    w = widget
    while w is not None and w not in _rolaveis:
        w = getattr(w, "master", None)
    if w is None:
        return
    tela = w
    try:
        tela.update_idletasks()
        y = widget.winfo_rooty() - tela.winfo_rooty() + tela.canvasy(0)
        total = max(1, tela.bbox("all")[3])
        tela.yview_moveto(max(0.0, (y - px(40)) / total))
    except (tk.TclError, TypeError):
        pass


# ============================================================ barra lateral
class _CachePilulas:
    """Fundo arredondado dos itens da barra (Pillow), sem vazar memória ao
    redimensionar: uma imagem por (largura, altura, cor)."""

    def __init__(self):
        self._fotos: dict = {}

    def obter(self, largura: int, altura: int, cor: str, fundo: str):
        chave = (largura, altura, cor, fundo)
        if chave not in self._fotos:
            try:
                from PIL import Image, ImageDraw, ImageTk

                e = 4
                img = Image.new("RGBA", (largura * e, altura * e), fundo)
                ImageDraw.Draw(img).rounded_rectangle(
                    (0, 0, largura * e - 1, altura * e - 1), radius=altura * e // 2, fill=cor)
                self._fotos[chave] = ImageTk.PhotoImage(img.resize((largura, altura),
                                                                   Image.LANCZOS))
            except Exception:
                self._fotos[chave] = None
        return self._fotos[chave]


_pilulas = _CachePilulas()
estilo._ao_trocar_interpretador.append(_pilulas._fotos.clear)


class ItemNav(tk.Canvas):
    """Um item da barra lateral: ícone, rótulo e, à direita, o indicador."""

    def __init__(self, pai, nome: str, rotulo: str, icone: str, ao_clicar):
        super().__init__(pai, height=px(40), highlightthickness=0, borderwidth=0,
                         background=estilo.MOLDURA, cursor="hand2", takefocus=0)
        self.nome, self.rotulo, self.icone = nome, rotulo, icone
        self.ao_clicar = ao_clicar
        self.selecionado = False
        self.sobre = False
        self.indicador: tuple[str, str] | None = None
        self.bind("<Configure>", lambda _e: self.desenhar())
        self.bind("<Enter>", lambda _e: self._sobre(True))
        self.bind("<Leave>", lambda _e: self._sobre(False))
        self.bind("<Button-1>", lambda _e: self.ao_clicar(self.nome))

    def _sobre(self, valor: bool) -> None:
        self.sobre = valor
        self.desenhar()

    def definir(self, selecionado: bool | None = None, indicador=False) -> None:
        mudou = False
        if selecionado is not None and selecionado != self.selecionado:
            self.selecionado = selecionado
            mudou = True
        if indicador is not False and indicador != self.indicador:
            self.indicador = indicador
            mudou = True
        if mudou:
            self.desenhar()

    def desenhar(self) -> None:
        self.delete("all")
        largura, altura = self.winfo_width(), self.winfo_height()
        if largura <= 1:
            return
        fundo = None
        if self.selecionado:
            fundo = estilo.SELECAO
        elif self.sobre:
            fundo = estilo.SOBRE_MOLDURA
        if fundo:
            foto = _pilulas.obter(largura, altura, fundo, estilo.MOLDURA)
            if foto is not None:
                self.create_image(0, 0, anchor="nw", image=foto)
            else:
                self.create_rectangle(0, 0, largura, altura, fill=fundo, outline=fundo)
        cor_selo = self.indicador[1] if self.indicador else None
        nome_icone = f"nav-{self.icone}-ativo" if self.selecionado else f"nav-{self.icone}"
        foto_icone = estilo.imagem(nome_icone, px(20), selo=cor_selo)
        x = px(16)
        if foto_icone is not None:
            self.create_image(x + px(10), altura // 2, image=foto_icone)
        cor = estilo.AZUL_PROFUNDO if self.selecionado else estilo.TINTA
        fonte = estilo.FONTE_NEGRITO if self.selecionado else estilo.FONTE
        self.create_text(x + px(34), altura // 2, text=self.rotulo, anchor="w", fill=cor,
                         font=fonte)
        if self.indicador and self.indicador[0]:
            texto, cor_ind = self.indicador
            self.create_text(largura - px(14), altura // 2, text=texto, anchor="e",
                             fill=cor_ind, font=estilo.FONTE_NOTA_NEGRITO)


class BarraLateral(tk.Frame):
    """A navegação à esquerda: marca do programa, páginas, rodapé de estado."""

    def __init__(self, pai, ao_escolher, versao: str):
        super().__init__(pai, background=estilo.MOLDURA, width=px(236))
        self.grid_propagate(False)
        self.pack_propagate(False)
        self.ao_escolher = ao_escolher
        self.itens: dict[str, ItemNav] = {}

        marca = tk.Frame(self, background=estilo.MOLDURA)
        marca.pack(fill="x", padx=px(18), pady=(px(20), px(18)))
        logo = estilo.imagem("assessor-64", px(34))
        if logo is not None:
            tk.Label(marca, image=logo, background=estilo.MOLDURA).pack(side="left")
        textos = tk.Frame(marca, background=estilo.MOLDURA)
        textos.pack(side="left", padx=(px(10), 0))
        tk.Label(textos, text="Assessor Integrado", font=estilo.FONTE_MARCA,
                 background=estilo.MOLDURA, foreground=estilo.TINTA).pack(anchor="w")
        tk.Label(textos, text=f"versão {versao}", font=estilo.FONTE_NOTA,
                 background=estilo.MOLDURA, foreground=estilo.TINTA_FRACA).pack(anchor="w")

        self.lista = tk.Frame(self, background=estilo.MOLDURA)
        self.lista.pack(fill="x", padx=px(10))

        self.rodape = tk.Label(self, text="", font=estilo.FONTE_NOTA, justify="left",
                               background=estilo.MOLDURA, foreground=estilo.TINTA_FRACA,
                               anchor="w", wraplength=px(200))
        self.rodape.pack(side="bottom", fill="x", padx=px(22), pady=(0, px(18)))

    def adicionar(self, nome: str, rotulo: str, icone: str) -> ItemNav:
        item = ItemNav(self.lista, nome, rotulo, icone, self.ao_escolher)
        item.pack(fill="x", pady=(0, px(2)))
        self.itens[nome] = item
        return item

    def separador(self) -> None:
        tk.Frame(self.lista, height=1, background=estilo.LINHA).pack(
            fill="x", padx=px(14), pady=px(10))

    def selecionar(self, nome: str) -> None:
        for chave, item in self.itens.items():
            item.definir(selecionado=(chave == nome))

    def indicar(self, nome: str, indicador: tuple[str, str] | None) -> None:
        item = self.itens.get(nome)
        if item is not None:
            item.definir(indicador=indicador)

    def estado(self, texto: str) -> None:
        if self.rodape.cget("text") != texto:
            self.rodape.configure(text=texto)


# =================================================================== cartões
class Cartao(ttk.Frame):
    """Quadro branco de cantos macios, com sombra; clicável se houver
    comando (o cartão inteiro, não só o botão, leva à função)."""

    def __init__(self, pai, comando=None, padding=None, estilo_quadro: str = "Cartao"):
        super().__init__(pai, style=f"{estilo_quadro}.TFrame",
                         padding=padding if padding is not None else px(18))
        self.comando = comando
        self._sobre = False
        if comando is not None:
            self.configure(cursor="hand2")
        self.bind("<Enter>", self._entrou, add="+")
        self.bind("<Leave>", self._saiu, add="+")
        if comando is not None:
            self.bind("<Button-1>", lambda _e: comando(), add="+")

    def ligar_filhos(self) -> None:
        """Repassa realce e clique dos rótulos ao cartão (chame após montar)."""
        def ligar(w):
            for filho in w.winfo_children():
                classe = filho.winfo_class()
                if classe in ("TButton", "Button", "TEntry", "Entry", "TCombobox"):
                    continue
                filho.bind("<Enter>", self._entrou, add="+")
                filho.bind("<Leave>", self._saiu, add="+")
                if self.comando is not None:
                    try:
                        filho.configure(cursor="hand2")
                    except tk.TclError:
                        pass
                    filho.bind("<Button-1>", lambda _e: self.comando(), add="+")
                ligar(filho)
        ligar(self)

    def _entrou(self, _evento=None) -> None:
        if not self._sobre:
            self._sobre = True
            self.state(["hover"])

    def _saiu(self, _evento=None) -> None:
        # Sair do cartão para um filho dele também gera <Leave>: confere se o
        # ponteiro ainda está dentro antes de apagar o realce.
        def conferir():
            try:
                x, y = self.winfo_pointerxy()
                dentro = (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                          and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height())
            except tk.TclError:
                return
            if not dentro and self._sobre:
                self._sobre = False
                self.state(["!hover"])
        self.after(15, conferir)


# ===================================================================== faixas
_CORES_FAIXA = {
    "Aviso": (estilo.AMBAR_FUNDO, "sinal-aviso", estilo.TINTA),
    "Sucesso": (estilo.VERDE_FUNDO, "sinal-ok", estilo.TINTA),
    "Erro": (estilo.VINHO_FUNDO, "sinal-erro", estilo.TINTA),
    "Info": (estilo.AZUL_PALIDO, "sinal-info", estilo.TINTA),
}


class Faixa(ttk.Frame):
    """Recado colorido de largura inteira, com ícone e até dois botões."""

    def __init__(self, pai, tipo: str = "Info", texto: str = "", titulo: str = ""):
        super().__init__(pai, style=f"{tipo}.TFrame", padding=(px(14), px(10)))
        self.tipo = tipo
        self.columnconfigure(1, weight=1)
        cor, icone, letra = _CORES_FAIXA.get(tipo, _CORES_FAIXA["Info"])
        self._icone = tk.Label(self, background=cor, image=estilo.imagem(icone, px(20)) or "")
        self._icone.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, px(12)), pady=(px(1), 0))
        self._titulo = tk.Label(self, text=titulo, font=estilo.FONTE_NEGRITO, background=cor,
                                foreground=letra, anchor="w", justify="left")
        self._texto = tk.Label(self, text=texto, font=estilo.FONTE, background=cor,
                               foreground=letra, anchor="w", justify="left")
        self._acoes = tk.Frame(self, background=cor)
        self._acoes.grid(row=0, column=2, rowspan=2, sticky="e", padx=(px(12), 0))
        estilo.acompanhar_largura(self._texto)
        estilo.acompanhar_largura(self._titulo)
        self._posicionar()

    def _posicionar(self) -> None:
        tem_titulo = bool(self._titulo.cget("text"))
        if tem_titulo:
            self._titulo.grid(row=0, column=1, sticky="ew")
            self._texto.grid(row=1, column=1, sticky="ew", pady=(px(1), 0))
        else:
            self._titulo.grid_remove()
            self._texto.grid(row=0, column=1, rowspan=2, sticky="ew")

    def definir(self, texto: str | None = None, titulo: str | None = None) -> None:
        if texto is not None:
            self._texto.configure(text=texto)
        if titulo is not None:
            self._titulo.configure(text=titulo)
        self._posicionar()

    def acao(self, texto: str, comando, familia: str = "apoio") -> ttk.Button:
        b = estilo.botao(self._acoes, texto, comando, familia, superficie=self.tipo)
        b.pack(side="left", padx=(px(8) if self._acoes.winfo_children()[:-1] else 0, 0))
        return b

    def limpar_acoes(self) -> None:
        for w in self._acoes.winfo_children():
            w.destroy()


# ============================================================ linha de estado
_CORES_ESTADO = {"ok": estilo.VERDE, "aviso": estilo.AMBAR, "erro": estilo.VINHO,
                 "ocupado": estilo.AZUL, "neutro": estilo.APAGADO, "info": estilo.AZUL}


class EstadoLinha(tk.Frame):
    """● Frase curta. O ponto diz o tom: verde, âmbar, vermelho, azul ou cinza."""

    def __init__(self, pai, texto: str = "", tipo: str = "neutro", fundo: str = estilo.PAPEL,
                 fonte=estilo.FONTE_NOTA):
        super().__init__(pai, background=fundo)
        self.ponto = tk.Label(self, text="●" if texto else "", font=estilo.FONTE_NOTA, background=fundo,
                              foreground=_CORES_ESTADO.get(tipo, estilo.APAGADO))
        self.ponto.pack(side="left", anchor="n")
        self.texto = tk.Label(self, text=texto, font=fonte, background=fundo,
                              foreground=estilo.TINTA_FRACA, justify="left", anchor="w")
        self.texto.pack(side="left", fill="x", expand=True, padx=(px(4), 0))
        estilo.acompanhar_largura(self.texto)

    def definir(self, texto: str, tipo: str = "neutro") -> None:
        self.texto.configure(text=texto)
        self.ponto.configure(foreground=_CORES_ESTADO.get(tipo, estilo.APAGADO),
                             text="●" if texto else "")

    def bind_filhos(self, sequencia, funcao) -> None:
        for w in (self, self.ponto, self.texto):
            w.bind(sequencia, funcao, add="+")


# =================================================================== medidor
class Medidor(tk.Canvas):
    """Nível do microfone (0 a 1), com queda suave e marca de saturação."""

    def __init__(self, pai, largura: int = 200, altura: int | None = None,
                 fundo: str = estilo.PAPEL):
        altura = altura or px(8)
        super().__init__(pai, width=largura, height=altura, highlightthickness=0, borderwidth=0,
                         background=fundo)
        self._nivel = 0.0
        self._pico = 0.0
        self.bind("<Configure>", lambda _e: self._desenhar())

    def definir(self, nivel: float) -> None:
        nivel = max(0.0, min(1.0, float(nivel or 0.0)))
        # sobe na hora, desce devagar: o olho acompanha a fala sem tremer
        self._nivel = nivel if nivel > self._nivel else self._nivel * 0.7 + nivel * 0.3
        self._pico = max(nivel, self._pico * 0.95)
        self._desenhar()

    def zerar(self) -> None:
        self._nivel = self._pico = 0.0
        self._desenhar()

    def _desenhar(self) -> None:
        self.delete("all")
        L, A = self.winfo_width(), self.winfo_height()
        if L <= 2:
            return
        self.create_rectangle(0, 0, L, A, fill=estilo.SUPERFICIE, outline="")
        cor = estilo.VINHO if self._nivel > 0.92 else (estilo.VERDE if self._nivel > 0.08
                                                       else estilo.APAGADO)
        if self._nivel > 0.002:
            self.create_rectangle(0, 0, int(L * self._nivel), A, fill=cor, outline="")
        if self._pico > 0.02:
            x = int(L * self._pico)
            self.create_line(x, 0, x, A, fill=estilo.TINTA_FRACA)


# ================================================================= detalhes
class Detalhes(ttk.Frame):
    """O registro técnico de uma tarefa, recolhido por padrão.

    Limitado a MAX_LINHAS_REGISTRO linhas e inserido em lote: na base, o
    registro crescia sem limite e cada linha alternava o estado do widget
    (bug B10), o que pesava em lotes longos.
    """

    def __init__(self, pai, titulo: str = "Detalhes técnicos", aberto: bool = False, altura: int = 8):
        super().__init__(pai)
        self.columnconfigure(0, weight=1)
        self._aberto = aberto
        self._titulo = titulo
        self.botao = estilo.botao(self, "", self.alternar, "texto", pequeno=True)
        self.botao.grid(row=0, column=0, sticky="w")
        self.caixa = tk.Text(self, height=altura, font=estilo.FONTE_MONO, wrap="word",
                             relief="flat", borderwidth=0, padx=px(10), pady=px(8),
                             background=estilo.REGISTRO_FUNDO, foreground=estilo.TINTA,
                             highlightthickness=1, highlightbackground=estilo.LINHA,
                             highlightcolor=estilo.LINHA, state="disabled", cursor="arrow")
        self.caixa.tag_configure("aviso", foreground=estilo.AMBAR_TINTA)
        self.caixa.tag_configure("erro", foreground=estilo.VINHO)
        self._linhas = 0
        self._aplicar()

    def _aplicar(self) -> None:
        seta = "▾" if self._aberto else "▸"
        self.botao.configure(text=f"{seta}  {self._titulo}")
        if self._aberto:
            self.caixa.grid(row=1, column=0, sticky="nsew", pady=(px(4), 0))
            self.caixa.see("end")
        else:
            self.caixa.grid_remove()

    def alternar(self) -> None:
        self._aberto = not self._aberto
        self._aplicar()
        if self._aberto:
            mostrar_no_rolavel(self.caixa)

    def escrever(self, linhas: list) -> None:
        """linhas: textos ou (texto, nível do logging)."""
        if not linhas:
            return
        self.caixa.configure(state="normal")
        for item in linhas:
            texto, nivel = (item, 20) if isinstance(item, str) else item
            tag = "erro" if nivel >= 40 else ("aviso" if nivel >= 30 else "")
            self.caixa.insert("end", texto + "\n", tag)
            self._linhas += 1
        excesso = self._linhas - MAX_LINHAS_REGISTRO
        if excesso > 0:
            self.caixa.delete("1.0", f"{excesso + 1}.0")
            self._linhas -= excesso
        self.caixa.configure(state="disabled")
        if self._aberto:
            self.caixa.see("end")

    def limpar(self) -> None:
        self.caixa.configure(state="normal")
        self.caixa.delete("1.0", "end")
        self.caixa.configure(state="disabled")
        self._linhas = 0


# =================================================================== tabelas
def tabela(pai, colunas: list[tuple], altura: int = 8):
    """Treeview num quadro de cantos macios, com rolagem vertical.

    colunas: (id, título, largura em px de projeto, âncora, estica).
    Devolve (quadro, arvore).
    """
    quadro = ttk.Frame(pai, style="Bloco.TFrame", padding=px(2))
    quadro.columnconfigure(0, weight=1)
    quadro.rowconfigure(0, weight=1)
    arvore = ttk.Treeview(quadro, columns=[c[0] for c in colunas], show="headings",
                          height=altura, selectmode="extended")
    for ident, titulo, largura, ancora, estica in colunas:
        arvore.heading(ident, text=titulo, anchor=ancora)
        arvore.column(ident, width=px(largura), minwidth=px(min(largura, 40)), anchor=ancora,
                      stretch=estica)
    arvore.grid(row=0, column=0, sticky="nsew", padx=(px(4), 0), pady=px(4))
    barra = ttk.Scrollbar(quadro, orient="vertical", command=arvore.yview)
    barra.grid(row=0, column=1, sticky="ns", pady=px(8), padx=(0, px(4)))
    arvore.configure(yscrollcommand=barra.set)
    for tag, cor in (("ok", estilo.VERDE), ("falha", estilo.VINHO), ("andamento", estilo.AZUL),
                     ("aguardando", estilo.TINTA_FRACA), ("aviso", estilo.AMBAR_TINTA)):
        arvore.tag_configure(tag, foreground=cor)
    arvore.tag_configure("par", background=estilo.PAPEL)
    arvore.tag_configure("impar", background="#fbfbfc")
    return quadro, arvore


# =========================================================== miudezas
def divisoria(pai, **grid) -> tk.Frame:
    """Fio horizontal de 1 px na cor LINHA (o ttk.Separator do clam sai escuro)."""
    return tk.Frame(pai, height=1, background=estilo.LINHA, borderwidth=0)


def copiar(raiz: tk.Misc, texto: str) -> bool:
    try:
        raiz.clipboard_clear()
        raiz.clipboard_append(texto)
        raiz.update_idletasks()      # no Windows, sem isto a cópia pode se perder
        return True
    except tk.TclError:
        return False


def rotulo(pai, texto: str = "", fraco: bool = False, nota: bool = False, negrito: bool = False,
           quebra: bool = True, **extra) -> ttk.Label:
    fonte = estilo.FONTE_NOTA if nota else (estilo.FONTE_NEGRITO if negrito else estilo.FONTE)
    cor = estilo.TINTA_FRACA if (fraco or nota) else estilo.TINTA
    extra.setdefault("justify", "left")
    r = ttk.Label(pai, text=texto, font=fonte, foreground=cor, **extra)
    if quebra:
        estilo.acompanhar_largura(r)
    return r


def campo(pai, titulo: str, variavel: tk.Variable | None = None, largura: int = 30,
          **extra) -> tuple[ttk.Frame, ttk.Entry]:
    """Rótulo em cima, campo embaixo (o padrão dos formulários do Google)."""
    quadro = ttk.Frame(pai)
    quadro.columnconfigure(0, weight=1)
    ttk.Label(quadro, text=titulo, foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA).grid(
        row=0, column=0, sticky="w", pady=(0, px(3)))
    entrada = ttk.Entry(quadro, textvariable=variavel, width=largura, **extra)
    entrada.grid(row=1, column=0, sticky="ew")
    return quadro, entrada


def quando(momento) -> str:
    """'hoje, 14:32', 'ontem, 09:05', '12/09, 16:40' ou '12/09/2025'."""
    from datetime import datetime

    if momento is None:
        return ""
    agora = datetime.now()
    dias = (agora.date() - momento.date()).days
    if dias == 0:
        return f"hoje, {momento:%H:%M}"
    if dias == 1:
        return f"ontem, {momento:%H:%M}"
    if momento.year == agora.year:
        return f"{momento:%d/%m}, {momento:%H:%M}"
    return f"{momento:%d/%m/%Y}"


def plural(n: int, singular: str, plural_: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural_ or singular + 's')}"
