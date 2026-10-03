"""Diálogos: código de verificação, colar lista, link, número do processo,
assistente de primeiro uso e o aviso de "salvando" ao fechar.

Todos usam o mesmo esqueleto (Dialogo): janela modal centrada sobre a
principal, botões do tema (na base, os diálogos usavam ttk.Button cru e
destoavam - bug B12), Esc cancela, Enter confirma. Nenhum bloqueia o laço
do Tk (não há wait_window): a resposta volta por função de retorno, e as
threads de trabalho continuam sendo atendidas enquanto o diálogo está aberto.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import estilo
from .estilo import px

log = logging.getLogger("interface.dialogos")


# ------------------------------------------------------------ mensagens
def informar(raiz, titulo: str, texto: str) -> None:
    messagebox.showinfo(titulo, texto, parent=raiz)


def avisar(raiz, titulo: str, texto: str) -> None:
    messagebox.showwarning(titulo, texto, parent=raiz)


def erro(raiz, titulo: str, texto: str) -> None:
    messagebox.showerror(titulo, texto, parent=raiz)


def confirmar(raiz, titulo: str, texto: str) -> bool:
    return bool(messagebox.askyesno(titulo, texto, parent=raiz))


def escolher_pasta(raiz, titulo: str, inicial: Path | None = None) -> Path | None:
    escolhida = filedialog.askdirectory(parent=raiz, title=titulo, mustexist=False,
                                        initialdir=str(inicial) if inicial else None)
    return Path(escolhida) if escolhida else None


# ------------------------------------------------------------ esqueleto
class Dialogo(tk.Toplevel):
    """Janela modal sobre a principal. Subclasses preenchem self.corpo e
    chamam self.botoes(...)."""

    largura = 520

    def __init__(self, raiz, titulo: str, subtitulo: str = "", icone: str | None = None):
        super().__init__(raiz)
        self.withdraw()
        self.raiz = raiz
        self.title(titulo)
        self.configure(background=estilo.PAPEL)
        self.resizable(False, False)
        self.transient(raiz)
        self.protocol("WM_DELETE_WINDOW", self.cancelar)
        self.bind("<Escape>", lambda _e: self.cancelar())
        self._fechado = False

        externo = ttk.Frame(self, padding=(px(28), px(24), px(28), px(20)))
        externo.pack(fill="both", expand=True)
        externo.columnconfigure(1, weight=1)
        coluna = 0
        if icone:
            foto = estilo.imagem(icone, px(40))
            if foto is not None:
                tk.Label(externo, image=foto, background=estilo.PAPEL).grid(
                    row=0, column=0, rowspan=2, sticky="nw", padx=(0, px(16)))
                coluna = 1
        ttk.Label(externo, text=titulo, font=estilo.FONTE_SECAO).grid(
            row=0, column=coluna, columnspan=2 - coluna, sticky="w")
        if subtitulo:
            sub = ttk.Label(externo, text=subtitulo, foreground=estilo.TINTA_FRACA,
                            justify="left", wraplength=px(self.largura - 60 - (56 if coluna else 0)))
            sub.grid(row=1, column=coluna, columnspan=2 - coluna, sticky="w", pady=(px(4), 0))
        self.corpo = ttk.Frame(externo)
        self.corpo.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(px(16), 0))
        self.corpo.columnconfigure(0, weight=1)
        self.rodape = ttk.Frame(externo)
        self.rodape.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(px(20), 0))
        self.rodape.columnconfigure(0, weight=1)

    def botoes(self, *definicoes, esquerda=None) -> list[ttk.Button]:
        """definicoes: (texto, comando, família), da esquerda para a direita."""
        if esquerda is not None:
            texto, comando, familia = esquerda
            estilo.botao(self.rodape, texto, comando, familia).grid(row=0, column=0, sticky="w")
        caixa = ttk.Frame(self.rodape)
        caixa.grid(row=0, column=1, sticky="e")
        feitos = []
        for i, (texto, comando, familia) in enumerate(definicoes):
            b = estilo.botao(caixa, texto, comando, familia)
            b.pack(side="left", padx=(px(8) if i else 0, 0))
            feitos.append(b)
        return feitos

    def mostrar(self, foco=None) -> None:
        """Centra sobre a principal, mostra e prende o foco (modal)."""
        self.update_idletasks()
        largura = max(px(self.largura), self.winfo_reqwidth())
        altura = self.winfo_reqheight()
        try:
            x = self.raiz.winfo_rootx() + (self.raiz.winfo_width() - largura) // 2
            y = self.raiz.winfo_rooty() + max(px(40), (self.raiz.winfo_height() - altura) // 3)
        except tk.TclError:
            x = y = px(100)
        x = max(0, min(x, self.winfo_screenwidth() - largura))
        y = max(0, min(y, self.winfo_screenheight() - altura - px(40)))
        self.geometry(f"{largura}x{altura}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.after(60, self._prender)
        # Os textos só quebram linha depois de saber a largura real: a
        # altura certa é a medida DEPOIS de a janela aparecer.
        self.after(30, self.ajustar_altura)
        if foco is not None:
            self.after(80, foco.focus_set)

    def ajustar_altura(self) -> None:
        if self._fechado:
            return
        try:
            self.update_idletasks()
            altura = self.winfo_reqheight()
            if abs(altura - self.winfo_height()) <= 2:
                return
            y = self.raiz.winfo_rooty() + max(px(40), (self.raiz.winfo_height() - altura) // 3)
            y = max(0, min(y, self.winfo_screenheight() - altura - px(40)))
            self.geometry(f"{self.winfo_width()}x{altura}+{self.winfo_x()}+{y}")
        except tk.TclError:
            pass

    def _prender(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            # janela ainda não visível (sem gerenciador de janelas): tenta de novo
            if not self._fechado:
                self.after(100, self._prender)

    def fechar(self) -> None:
        if self._fechado:
            return
        self._fechado = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        # O diálogo e suas variáveis do Tk formam ciclos de referência. Se o
        # coletor de lixo os recolhesse numa thread de trabalho, o tkinter
        # chamaria o Tcl fora da thread principal ("main thread is not in
        # main loop"). Recolhe aqui, na thread da janela.
        import gc

        gc.collect()

    def cancelar(self) -> None:
        self.fechar()


# ======================================================= código de verificação
class DialogoCodigo(Dialogo):
    """O portal mandou um código (e-mail do e-SAJ, autenticador do eProc).

    Corrige a base em três pontos: aparece por um evento explícito (e não
    pelo texto do log), é modal e vem para a frente - a caixa antiga ficava
    no rodapé, às vezes fora de vista -, e mostra quanto tempo resta para
    digitar (o prazo da espera do programa, que não é a validade do código).
    "Pedir novo código" devolve "" ao motor, que pede outro ao portal; o
    código do aplicativo autenticador (eProc) não se pede: ele muda sozinho
    a cada 30 segundos, e o botão não aparece.
    """

    largura = 500

    def __init__(self, raiz, pedido, ao_responder=None):
        super().__init__(raiz, pedido.titulo or "Código de verificação",
                         pedido.mensagem or "Digite o código que o portal enviou.",
                         icone="sinal-info")
        self.pedido = pedido
        self.ao_responder = ao_responder
        self.codigo = tk.StringVar()
        self.entrada = ttk.Entry(self.corpo, textvariable=self.codigo, font=estilo.FONTE_CODIGO,
                                 justify="center", width=12, style="Codigo.TEntry")
        self.entrada.grid(row=0, column=0, sticky="ew")
        self.entrada.bind("<Return>", lambda _e: self.confirmar())
        self.barra = ttk.Progressbar(self.corpo, mode="determinate", maximum=1000)
        self.barra.grid(row=1, column=0, sticky="ew", pady=(px(14), px(6)))
        self.tempo = ttk.Label(self.corpo, text="", foreground=estilo.TINTA_FRACA,
                               font=estilo.FONTE_NOTA, justify="left",
                               wraplength=px(self.largura - 60))
        self.tempo.grid(row=2, column=0, sticky="w")
        self.reenviavel = _reenviavel(pedido)
        _, self.ok = self.botoes(("Cancelar", self.cancelar, "apoio"),
                                 ("Confirmar", self.confirmar, "principal"),
                                 esquerda=(("Pedir novo código", self.novo, "texto")
                                           if self.reenviavel else None))
        self.codigo.trace_add("write", lambda *_: self._habilitar())
        self._habilitar()
        self.mostrar(foco=self.entrada)
        self._chamar_atencao()
        self._contar()

    def _chamar_atencao(self) -> None:
        # O magistrado pode estar em outro programa: traz a janela e pisca.
        try:
            self.raiz.deiconify()
            self.raiz.lift()
            self.lift()
            self.attributes("-topmost", True)
            self.after(1500, lambda: self._sem_topo())
        except tk.TclError:
            pass
        estilo.piscar_na_barra(self.raiz)

    def _sem_topo(self) -> None:
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _habilitar(self) -> None:
        limpo = self.codigo.get().strip()
        self.ok.state(["!disabled"] if limpo else ["disabled"])

    def _contar(self) -> None:
        if self._fechado:
            return
        if not self.pedido.aberto:
            # o trabalho desistiu (Parar, prazo do lado do motor)
            self.fechar()
            return
        resta = self.pedido.restante
        total = max(1, self.pedido.prazo_s)
        self.barra.configure(value=1000 * resta / total)
        minutos, segundos = divmod(int(resta + 0.5), 60)
        if resta <= 0:
            self.pedido.responder(None)
            self._avisar_retorno(None)
            self.fechar()
            return
        texto = f"Tempo para digitar: {minutos}:{segundos:02d}."
        if self.reenviavel:
            texto += " Se o código não chegou, peça outro."
        else:
            texto += " Digite o código que estiver na tela do aplicativo; ele muda a cada 30 segundos."
        self.tempo.configure(text=texto)
        self.after(500, self._contar)

    def _avisar_retorno(self, valor) -> None:
        if self.ao_responder is not None:
            try:
                self.ao_responder(valor)
            except Exception:
                log.exception("falha ao tratar a resposta do código")

    def confirmar(self) -> None:
        # O código não tem espaço; o e-mail às vezes vem "123 456".
        valor = "".join(self.codigo.get().split())
        if not valor:
            return
        self.pedido.responder(valor)
        self._avisar_retorno(valor)
        self.fechar()

    def novo(self) -> None:
        self.pedido.responder("")
        self._avisar_retorno("")
        self.fechar()

    def cancelar(self) -> None:
        self.pedido.responder(None)
        self._avisar_retorno(None)
        self.fechar()


def _reenviavel(pedido) -> bool:
    """Dá para pedir outro código? Sim para o enviado por e-mail (e-SAJ);
    não para o do aplicativo autenticador (eProc), que muda sozinho.

    Vale o que o portal disser (PedidoCodigo.reenviavel); enquanto ele não
    disser, reconhece o autenticador pelo pedido.
    """
    valor = getattr(pedido, "reenviavel", None)
    if valor is not None:
        return bool(valor)
    texto = f"{getattr(pedido, 'titulo', '')} {getattr(pedido, 'mensagem', '')}".lower()
    return "autenticador" not in texto


# ============================================================ colar a lista
class DialogoColar(Dialogo):
    largura = 600

    def __init__(self, raiz, ao_confirmar):
        super().__init__(raiz, "Colar a relação de processos",
                         "Cole os números, um por linha — também serve a coluna copiada do "
                         "Excel ou um texto qualquer que contenha os números. Para processo "
                         "em segredo de justiça, acrescente a senha depois de ponto e vírgula.")
        self.ao_confirmar = ao_confirmar
        self.caixa = tk.Text(self.corpo, height=12, font=estilo.FONTE_MONO, wrap="word",
                             relief="flat", borderwidth=0, padx=px(10), pady=px(8),
                             highlightthickness=1, highlightbackground=estilo.LINHA_FORTE,
                             highlightcolor=estilo.AZUL, undo=True)
        self.caixa.grid(row=0, column=0, sticky="nsew")
        exemplo = ttk.Label(self.corpo, text="Exemplo:  0700123-83.2024.8.02.0001   ou   "
                                             "0700123-83.2024.8.02.0001 ; senha123",
                            foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA)
        exemplo.grid(row=1, column=0, sticky="w", pady=(px(6), 0))
        self.botoes(("Cancelar", self.cancelar, "apoio"), ("Usar esta lista", self.confirmar,
                                                             "principal"))
        self.caixa.bind("<Control-Return>", lambda _e: self.confirmar())
        try:
            colado = raiz.clipboard_get()
            if colado and any(c.isdigit() for c in colado) and len(colado) < 200_000:
                self.caixa.insert("1.0", colado)
        except tk.TclError:
            pass
        self.mostrar(foco=self.caixa)

    def confirmar(self) -> None:
        texto = self.caixa.get("1.0", "end").strip()
        if not texto:
            return
        self.fechar()
        self.ao_confirmar(texto)


# ================================================================ link
class DialogoLink(Dialogo):
    largura = 600

    def __init__(self, raiz, ao_confirmar):
        super().__init__(raiz, "Abrir a relação por um link",
                         "Cole o link de compartilhamento da planilha ou do documento (Google "
                         "Drive, Google Planilhas, OneDrive ou SharePoint). Ele precisa estar "
                         "compartilhado como \u201cqualquer pessoa com o link\u201d.")
        self.ao_confirmar = ao_confirmar
        self.url = tk.StringVar()
        try:
            colado = raiz.clipboard_get().strip()
            if colado.startswith(("http://", "https://")) and len(colado) < 2000:
                self.url.set(colado)
        except tk.TclError:
            pass
        e = ttk.Entry(self.corpo, textvariable=self.url)
        e.grid(row=0, column=0, sticky="ew")
        e.bind("<Return>", lambda _e: self.confirmar())
        self.botoes(("Cancelar", self.cancelar, "apoio"), ("Baixar a relação", self.confirmar,
                                                             "principal"))
        self.mostrar(foco=e)

    def confirmar(self) -> None:
        url = self.url.get().strip()
        if not url.startswith(("http://", "https://")):
            erro(self, "Link", "O link deve começar com https://")
            return
        self.fechar()
        self.ao_confirmar(url)


# ========================================================= número do processo
class DialogoNumero(Dialogo):
    """Pede o número do processo (gravação cujo nome não traz o número)."""

    largura = 520

    def __init__(self, raiz, titulo: str, mensagem: str, ao_confirmar, inicial: str = ""):
        super().__init__(raiz, titulo, mensagem)
        from ..nucleo import cnj

        self._cnj = cnj
        self.ao_confirmar = ao_confirmar
        self.texto = tk.StringVar(value=inicial)
        self.e = ttk.Entry(self.corpo, textvariable=self.texto, font=estilo.FONTE_TRANSCRICAO)
        self.e.grid(row=0, column=0, sticky="ew")
        self.e.bind("<Return>", lambda _e: self.confirmar())
        self.dica = ttk.Label(self.corpo, text="No padrão CNJ: 0000000-00.0000.0.00.0000",
                              foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA)
        self.dica.grid(row=1, column=0, sticky="w", pady=(px(6), 0))
        self.ok, = self.botoes(("Cancelar", self.cancelar, "apoio"),
                               ("Continuar", self.confirmar, "principal"))[1:]
        self.texto.trace_add("write", lambda *_: self._validar())
        self._validar()
        self.mostrar(foco=self.e)

    def _validar(self):
        try:
            n = self._cnj.ler(self.texto.get())
        except self._cnj.NumeroInvalido:
            self.ok.state(["disabled"])
            self.dica.configure(text="No padrão CNJ: 0000000-00.0000.0.00.0000",
                                foreground=estilo.TINTA_FRACA)
            return None
        self.ok.state(["!disabled"])
        if n.digito_confere:
            self.dica.configure(text=f"{n.formatado} · número conferido", foreground=estilo.VERDE)
        else:
            self.dica.configure(text=f"{n.formatado}: o dígito verificador não confere — "
                                     "confira o número.", foreground=estilo.AMBAR_TINTA)
        return n

    def confirmar(self) -> None:
        n = self._validar()
        if n is None:
            return
        self.fechar()
        self.ao_confirmar(n)


# ======================================================== salvando ao fechar
class DialogoAguarde(Dialogo):
    """Sem botões: só a frase e a barra animada (ex.: salvando a transcrição
    antes de fechar o programa)."""

    largura = 440

    def __init__(self, raiz, titulo: str, texto: str):
        super().__init__(raiz, titulo, texto)
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.unbind("<Escape>")
        barra = ttk.Progressbar(self.corpo, mode="indeterminate")
        barra.grid(row=0, column=0, sticky="ew")
        barra.start(12)
        self.mostrar()


# ===================================================== assistente de 1º uso
class Assistente(Dialogo):
    """Três passos curtos, que podem ser pulados: (1) tribunal e forma de
    entrar; (2) pasta do acervo; (3) como o programa chama você e a unidade.

    Na base, a falta da senha só era descoberta ao clicar em Baixar, como
    erro (problema de usabilidade 2). Tudo aqui é salvo a cada passo.
    """

    largura = 640

    def __init__(self, janela, ao_concluir=None):
        super().__init__(janela.raiz, "Bem-vindo ao Assessor Integrado",
                         "Três passos rápidos para deixar tudo pronto. Você pode pular e "
                         "ajustar depois em Configurações.", icone="assessor-64")
        self.janela = janela
        self.cfg = janela.cfg
        self.ao_concluir = ao_concluir
        self.passo = 0
        self.indicador = tk.Canvas(self.corpo, height=px(6), highlightthickness=0,
                                   background=estilo.PAPEL, borderwidth=0)
        self.indicador.grid(row=0, column=0, sticky="ew")
        self.indicador.bind("<Configure>", lambda _e: self._desenhar_indicador())
        self.rotulo_passo = ttk.Label(self.corpo, text="", foreground=estilo.TINTA_FRACA,
                                      font=estilo.FONTE_NOTA)
        self.rotulo_passo.grid(row=1, column=0, sticky="w", pady=(px(6), px(10)))
        self.area = ttk.Frame(self.corpo)
        self.area.grid(row=2, column=0, sticky="nsew")
        self.area.columnconfigure(0, weight=1)
        # altura mínima comum aos passos: o diálogo não "pula" ao avançar
        self.corpo.rowconfigure(2, minsize=px(330))
        self.voltar, self.avancar = self.botoes(
            ("Voltar", self.anterior, "apoio"), ("Avançar", self.proximo, "principal"),
            esquerda=("Pular por agora", self.pular, "texto"))
        self._paginas = [self._passo_tribunal, self._passo_pasta, self._passo_unidade]
        self._mostrar_passo()
        self.mostrar()

    # ----------------------------------------------------------- moldura
    def _desenhar_indicador(self) -> None:
        c = self.indicador
        c.delete("all")
        largura = c.winfo_width()
        n = len(self._paginas)
        vao = px(8)
        cada = (largura - vao * (n - 1)) / n
        for i in range(n):
            x0 = i * (cada + vao)
            cor = estilo.AZUL if i <= self.passo else estilo.SUPERFICIE
            c.create_rectangle(x0, 0, x0 + cada, px(6), fill=cor, outline="")

    def _mostrar_passo(self) -> None:
        for w in self.area.winfo_children():
            w.destroy()
        # O passo 3 divide a área em duas colunas iguais; voltando dele, os
        # passos 1 e 2 ficavam espremidos na metade esquerda.
        self.area.columnconfigure(0, weight=1, uniform="")
        self.area.columnconfigure(1, weight=0, uniform="")
        titulos = ("Onde você trabalha", "Pasta do acervo", "Seus dados")
        self.rotulo_passo.configure(
            text=f"Passo {self.passo + 1} de {len(self._paginas)} · {titulos[self.passo]}")
        self._paginas[self.passo]()
        self.voltar.state(["disabled"] if self.passo == 0 else ["!disabled"])
        ultimo = self.passo == len(self._paginas) - 1
        self.avancar.configure(text="Concluir" if ultimo else "Avançar")
        self._desenhar_indicador()
        if self.winfo_ismapped():
            self.after(30, self.ajustar_altura)

    def anterior(self) -> None:
        self._salvar_passo()
        if self.passo > 0:
            self.passo -= 1
            self._mostrar_passo()

    def proximo(self) -> None:
        self._salvar_passo()
        if self.passo < len(self._paginas) - 1:
            self.passo += 1
            self._mostrar_passo()
        else:
            self._concluir()

    def pular(self) -> None:
        self._salvar_passo()
        self._concluir()

    def cancelar(self) -> None:
        self.pular()

    def _concluir(self) -> None:
        # Fecha mesmo que o config.ini não aceite a gravação: antes, a exceção
        # vinha antes do fechar(), e Pular, Esc e o X não fechavam mais o
        # diálogo, que segurava a janela inteira (grab).
        try:
            self.cfg.definir("interface", "assistente_concluido", True)
        except (OSError, ValueError) as erro:
            log.warning("não consegui marcar o assistente como concluído: %s", erro)
        finally:
            self.fechar()
        if self.ao_concluir:
            self.ao_concluir()

    def _salvar_passo(self) -> None:
        salvar = getattr(self, "_salvar_atual", None)
        if salvar:
            try:
                salvar()
            except Exception:
                log.exception("falha ao salvar o passo do assistente")
        self._salvar_atual = None

    # ------------------------------------------------------------ passo 1
    def _passo_tribunal(self) -> None:
        from ..nucleo import tribunais
        from .acessos import EditorAcesso

        lista = [t for t in tribunais.carregar() if t.suportado]
        lista.sort(key=lambda t: t.sigla)
        rotulos = [f"{t.sigla} — {t.nome.split('—')[-1].strip()} ({_sistemas(t)})" for t in lista]
        ttk.Label(self.area, text="Tribunal", foreground=estilo.TINTA_FRACA,
                  font=estilo.FONTE_NOTA).grid(row=0, column=0, sticky="w", pady=(0, px(3)))
        # A variável fica no objeto: se for coletada, o combo aparece vazio.
        self._escolha = tk.StringVar()
        combo = ttk.Combobox(self.area, textvariable=self._escolha, values=rotulos,
                             state="readonly", height=14)
        combo.grid(row=1, column=0, sticky="ew")
        atual = (self.cfg.texto("interface", "tribunal") or self.cfg.texto("unidade", "tribunal")
                 or "TJAL").upper()
        indice = next((i for i, t in enumerate(lista) if t.sigla == atual), 0)
        if lista:
            combo.current(indice)
        caixa = ttk.Frame(self.area)
        caixa.grid(row=2, column=0, sticky="nsew", pady=(px(16), 0))
        caixa.columnconfigure(0, weight=1)
        editores: list = []

        def montar(*_):
            for w in caixa.winfo_children():
                w.destroy()
            editores.clear()
            if not lista:
                return
            t = lista[combo.current()]
            self.cfg.definir("interface", "tribunal", t.sigla)
            ed = EditorAcesso(caixa, self.janela, t,
                              rotulo=f"Como você entra no {t.nome_sistema} do {t.sigla}?")
            ed.grid(row=0, column=0, sticky="ew")
            editores.append(ed)
            if t.alternativo is not None:
                nota = ttk.Label(caixa, text=f"O {t.sigla} também usa o {t.alternativo.nome_sistema}: "
                                             "o acesso a ele se informa em Configurações › Acessos "
                                             "(ou na hora de baixar).",
                                 foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA,
                                 justify="left")
                nota.grid(row=1, column=0, sticky="ew", pady=(px(12), 0))
                estilo.acompanhar_largura(nota)

        combo.bind("<<ComboboxSelected>>", montar)
        montar()
        self._salvar_atual = lambda: [e.salvar() for e in editores]

    # ------------------------------------------------------------ passo 2
    def _passo_pasta(self) -> None:
        from ..nucleo import caminhos

        texto = ttk.Label(self.area, justify="left", text=(
            "É nesta pasta que ficam os PDFs dos processos e as transcrições das "
            "audiências — e é ela que o Claude e o ChatGPT vão ler. Por padrão, os "
            "processos em segredo de justiça ficam numa pasta separada, fora do acervo."))
        texto.grid(row=0, column=0, sticky="ew")
        estilo.acompanhar_largura(texto)
        linha = ttk.Frame(self.area, style="Faixa.TFrame", padding=(px(14), px(10)))
        linha.grid(row=1, column=0, sticky="ew", pady=(px(16), 0))
        linha.columnconfigure(0, weight=1)
        caminho = tk.Label(linha, text=str(self.cfg.pasta_acervo), font=estilo.FONTE_MONO,
                           background=estilo.FAIXA_CLARA, foreground=estilo.TINTA, anchor="w",
                           justify="left")
        caminho.grid(row=0, column=0, sticky="ew")
        estilo.acompanhar_largura(caminho)
        aviso = ttk.Label(self.area, text="", foreground=estilo.AMBAR_TINTA, justify="left")
        aviso.grid(row=2, column=0, sticky="ew", pady=(px(10), 0))
        estilo.acompanhar_largura(aviso)

        def conferir():
            p = self.cfg.pasta_acervo
            caminho.configure(text=str(p))
            if caminhos.dentro_do_onedrive(p):
                aviso.configure(text="Esta pasta está dentro do OneDrive. A sincronização "
                                     "atrapalha arquivos em uso; prefira uma pasta local, "
                                     "como C:\\AssessorIntegrado\\Acervo.")
            else:
                aviso.configure(text="")

        def alterar():
            from . import servicos

            nova = escolher_pasta(self, "Escolha a pasta do acervo", self.cfg.pasta_acervo)
            if nova:
                problema = servicos.problema_nas_pastas(nova, self.cfg.pasta_sigilosos)
                if problema:
                    avisar(self, "Pasta não aceita", problema)
                    return
                self.cfg.definir("geral", "pasta_acervo", str(nova))
                conferir()

        estilo.botao(linha, "Alterar…", alterar, "apoio", superficie="Faixa").grid(
            row=0, column=1, padx=(px(12), 0))
        conferir()

    # ------------------------------------------------------------ passo 3
    def _passo_unidade(self) -> None:
        campos = [("geral", "nome_usuario", "Como devo chamar você? (ex.: Dra. Helena)"),
                  ("unidade", "magistrado", "Nome completo do(a) magistrado(a), para as transcrições"),
                  ("unidade", "vara", "Vara ou juízo"),
                  ("unidade", "comarca", "Comarca")]
        variaveis = []
        self.area.columnconfigure((0, 1), weight=1, uniform="u")
        for i, (secao, chave, titulo) in enumerate(campos):
            var = tk.StringVar(value=self.cfg.texto(secao, chave))
            quadro = ttk.Frame(self.area)
            quadro.columnconfigure(0, weight=1)
            ttk.Label(quadro, text=titulo, foreground=estilo.TINTA_FRACA,
                      font=estilo.FONTE_NOTA).grid(row=0, column=0, sticky="w", pady=(0, px(3)))
            ttk.Entry(quadro, textvariable=var).grid(row=1, column=0, sticky="ew")
            if i < 2:
                quadro.grid(row=i, column=0, columnspan=2, sticky="ew", pady=(0, px(14)))
            else:
                quadro.grid(row=2, column=i - 2, sticky="ew", padx=(0 if i == 2 else px(12), 0))
            variaveis.append((secao, chave, var))

        def salvar():
            for secao, chave, var in variaveis:
                if var.get().strip() != self.cfg.texto(secao, chave):
                    self.cfg.definir(secao, chave, var.get().strip())
            sigla = self.cfg.texto("interface", "tribunal")
            if sigla and not self.cfg.texto("unidade", "tribunal"):
                self.cfg.definir("unidade", "tribunal", sigla)

        self._salvar_atual = salvar


def _sistemas(t) -> str:
    if t.alternativo is not None:
        return f"{t.nome_sistema} e {t.alternativo.nome_sistema}"
    return t.nome_sistema
