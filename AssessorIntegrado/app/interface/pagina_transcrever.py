"""Transcrever audiência: ao vivo, pelo microfone, com quem fala marcado.

    ┌ painel de controle ─────────┐ ┌ quem está falando (F1…F8) ───────────┐
    │ Processo  [0700123-45…] ✓   │ │ [F1 Juiz(a)] [F2 Promotor(a)] …       │
    │ Tipo      [Instrução…  ▾]   │ ├───────────────────────────────────────┤
    │ Microfone [Padrão     ▾]    │ │ JUIZ(A)  00:01:12                     │
    │ ▁▂▃▅▂▁  [Testar]            │ │ Declaro aberta a audiência…           │
    │      ( ● )   00:12:34       │ │ …a transcrição rola aqui…             │
    │     Iniciar  ● Gravando     │ │                                       │
    │ [Encerrar e salvar]         │ ├───────────────────────────────────────┤
    │ ☐ revisar ao encerrar       │ │ modelo small · atraso 2 s · salvo …   │
    └─────────────────────────────┘ └───────────────────────────────────────┘

A sessão (transcricao.ao_vivo.SessaoAoVivo) roda numa Tarefa que segura o
MICROFONE do começo ao fim: iniciar(), depois espera o "Encerrar" (ou o
fechamento do programa) e chama encerrar() na própria thread - que grava o
DOCX final. Assim, fechar a janela no meio da audiência salva a transcrição
antes de destruir a tela (na base, o join de 2 s não bastava: bug B11).

Os eventos da sessão chegam de várias threads e só são enfileirados; quem
mexe no texto é a thread do Tk. Os atalhos F1 a F8 só valem nesta página.
"""

from __future__ import annotations

import collections
import logging
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

from ..nucleo import cnj, sistema, tribunais
from . import componentes, dialogos, estilo, servicos
from .componentes import Detalhes, Faixa, Medidor, Pagina
from .estilo import px
from .tarefas import MICROFONE, MODELO_REVISAO, NUVEM

# "transcricao" no nome: as linhas deste registro vão para os Detalhes da
# página (registro.marca), junto com as do módulo de transcrição.
log = logging.getLogger("interface.transcricao")

TIPOS = ("Instrução e julgamento", "Conciliação", "Mediação", "Custódia", "Justificação",
         "Oitiva de testemunha", "Interrogatório", "Depoimento especial", "Admonitória",
         "Una", "Outra")
EXTENSOES_AUDIO = [("Gravações de áudio e vídeo",
                    "*.mp3 *.wav *.m4a *.wma *.ogg *.flac *.aac *.opus *.mp4 *.wmv *.asf *.avi "
                    "*.mkv *.mov *.webm"), ("Todos os arquivos", "*.*")]
PADRAO_MICROFONE = "Microfone padrão do Windows"
TESTE_MAXIMO_S = 20
PLACEHOLDER = ("A transcrição aparece aqui enquanto a audiência acontece.\n\n"
               "Antes de começar: confira o número do processo e o microfone (o botão Testar "
               "mostra o nível do som). Durante a audiência, marque quem está falando com os "
               "botões acima ou com as teclas F1 a F8.")


# ================================================================ botão redondo
class BotaoRedondo(tk.Canvas):
    """O botão grande e circular: Iniciar → Pausar → Retomar."""

    ESTADOS = {
        # estado: (fundo, fundo sob o mouse, glifo, cor do glifo, rótulo)
        "iniciar": (estilo.AZUL, estilo.AZUL_CLARO, "microfone", "#ffffff", "Iniciar"),
        "pausar": (estilo.AZUL_PALIDO, estilo.AZUL_TONAL_SOBRE, "pausa", estilo.AZUL_PROFUNDO,
                   "Pausar"),
        "retomar": (estilo.AZUL, estilo.AZUL_CLARO, "microfone", "#ffffff", "Retomar"),
        "aguarde": (estilo.SUPERFICIE, estilo.SUPERFICIE, "reticencias", estilo.APAGADO,
                    "Aguarde…"),
    }

    def __init__(self, pai, comando, diametro: int = 84):
        self.d = px(diametro)
        super().__init__(pai, width=self.d, height=self.d + px(26), highlightthickness=0,
                         borderwidth=0, background=estilo.PAPEL, cursor="hand2", takefocus=1)
        self.comando = comando
        self.estado = "iniciar"
        self.sobre = False
        self._fotos: dict = {}
        self.bind("<Enter>", lambda _e: self._sobre(True))
        self.bind("<Leave>", lambda _e: self._sobre(False))
        self.bind("<Button-1>", lambda _e: self._clicar())
        self.bind("<Key-space>", lambda _e: self._clicar())
        self.bind("<Return>", lambda _e: self._clicar())
        self.desenhar()

    def _sobre(self, valor):
        self.sobre = valor
        self.desenhar()

    def _clicar(self):
        if self.estado != "aguarde":
            self.comando()

    def definir(self, estado: str) -> None:
        if estado != self.estado:
            self.estado = estado
            self.configure(cursor="watch" if estado == "aguarde" else "hand2")
            self.desenhar()

    def _foto(self, fundo: str, glifo: str, cor: str):
        chave = (fundo, glifo, cor)
        if chave in self._fotos:
            return self._fotos[chave]
        foto = None
        try:
            from PIL import Image, ImageDraw, ImageTk

            e = 4
            L = self.d * e
            img = Image.new("RGBA", (L, L), (255, 255, 255, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((0, 0, L - 1, L - 1), fill=fundo)
            if glifo == "microfone":
                origem = estilo.RECURSOS / "nav-transcrever.png"
                marca = Image.open(origem).convert("RGBA").resize((int(L * 0.46),) * 2,
                                                                   Image.LANCZOS)
                cheio = Image.new("RGBA", marca.size, cor)
                cheio.putalpha(marca.getchannel("A"))
                img.alpha_composite(cheio, ((L - marca.width) // 2, (L - marca.height) // 2))
            elif glifo == "pausa":
                w, h = L * 0.09, L * 0.34
                for cx in (L * 0.41, L * 0.59):
                    d.rounded_rectangle((cx - w / 2, (L - h) / 2, cx + w / 2, (L + h) / 2),
                                        radius=w / 2, fill=cor)
            else:
                r = L * 0.035
                for cx in (L * 0.38, L * 0.5, L * 0.62):
                    d.ellipse((cx - r, L / 2 - r, cx + r, L / 2 + r), fill=cor)
            foto = ImageTk.PhotoImage(img.resize((self.d, self.d), Image.LANCZOS), master=self)
        except Exception as erro:
            log.debug("botão redondo sem Pillow: %s", erro)
        self._fotos[chave] = foto
        return foto

    def desenhar(self) -> None:
        self.delete("all")
        fundo, sobre, glifo, cor, rotulo = self.ESTADOS[self.estado]
        foto = self._foto(sobre if self.sobre else fundo, glifo, cor)
        if foto is not None:
            self.create_image(self.d // 2, self.d // 2, image=foto)
        else:
            self.create_oval(1, 1, self.d - 1, self.d - 1, fill=sobre if self.sobre else fundo,
                             outline="")
            self.create_text(self.d // 2, self.d // 2, text=rotulo[:1], fill=cor,
                             font=estilo.FONTE_SECAO)
        self.create_text(self.d // 2, self.d + px(14), text=rotulo, fill=estilo.TINTA,
                         font=estilo.FONTE_NEGRITO)


# ==================================================================== falantes
class GradeFalantes(ttk.Frame):
    """Os oito botões de quem fala. Clique escolhe; duplo clique renomeia."""

    def __init__(self, pai, nomes: list[str], ao_escolher, ao_renomear):
        super().__init__(pai)
        self.ao_escolher, self.ao_renomear = ao_escolher, ao_renomear
        self.nomes = (list(nomes) + [""] * 8)[:8]
        self.ativo = -1
        self.chips: list[tk.Canvas] = []
        self.columnconfigure((0, 1, 2, 3), weight=1, uniform="falantes")
        for i in range(8):
            c = tk.Canvas(self, height=px(40), highlightthickness=0, borderwidth=0,
                          background=estilo.PAPEL, cursor="hand2")
            c.grid(row=i // 4, column=i % 4, sticky="ew",
                   padx=(0 if i % 4 == 0 else px(4), 0 if i % 4 == 3 else px(4)),
                   pady=(0, px(8)))
            c.bind("<Configure>", lambda _e, k=i: self._desenhar(k))
            c.bind("<Button-1>", lambda _e, k=i: self.escolher(k))
            c.bind("<Double-1>", lambda _e, k=i: self._renomear(k))
            c.bind("<Enter>", lambda _e, k=i: self._desenhar(k, sobre=True))
            c.bind("<Leave>", lambda _e, k=i: self._desenhar(k))
            self.chips.append(c)
        self._editor: ttk.Entry | None = None

    def escolher(self, indice: int) -> None:
        if not (0 <= indice < 8) or not self.nomes[indice]:
            return
        anterior, self.ativo = self.ativo, indice
        for k in {anterior, indice}:
            if 0 <= k < 8:
                self._desenhar(k)
        self.ao_escolher(self.nomes[indice])

    @property
    def nome_ativo(self) -> str:
        return self.nomes[self.ativo] if 0 <= self.ativo < 8 else ""

    def _desenhar(self, k: int, sobre: bool = False) -> None:
        c = self.chips[k]
        c.delete("all")
        L, A = c.winfo_width(), c.winfo_height()
        if L <= 2:
            return
        ativo = k == self.ativo
        if ativo:
            fundo, fio, letra = estilo.AZUL_PALIDO, estilo.AZUL, estilo.AZUL_PROFUNDO
        elif sobre:
            fundo, fio, letra = estilo.AZUL_TINTA, estilo.LINHA_FORTE, estilo.TINTA
        else:
            fundo, fio, letra = estilo.PAPEL, estilo.LINHA, estilo.TINTA
        foto = _moldura(L, A, fundo, fio)
        c._foto = foto  # type: ignore[attr-defined]  (viva enquanto estiver desenhada)
        if foto is not None:
            c.create_image(0, 0, anchor="nw", image=foto)
        else:
            c.create_rectangle(1, 1, L - 1, A - 1, fill=fundo, outline=fio)
        c.create_text(px(12), A // 2, text=f"F{k + 1}", anchor="w",
                      fill=estilo.AZUL if ativo else estilo.APAGADO, font=estilo.FONTE_NOTA_NEGRITO)
        nome = self.nomes[k] or "(vazio)"
        largura = L - px(46)
        fonte = estilo.FONTE_NEGRITO if ativo else estilo.FONTE
        if _medir(c, nome, fonte) > largura:
            # nome comprido ("Advogado(a) do autor"): letra menor, em até duas linhas
            fonte = estilo.FONTE_NOTA_NEGRITO if ativo else estilo.FONTE_NOTA
            nome = _caber_em_linhas(c, nome, fonte, largura, 2)
        c.create_text(px(38), A // 2, text=nome, anchor="w", width=largura,
                      fill=letra if self.nomes[k] else estilo.APAGADO, font=fonte)

    def _renomear(self, k: int) -> None:
        if self._editor is not None:
            self._editor.destroy()
        c = self.chips[k]
        var = tk.StringVar(value=self.nomes[k])
        e = ttk.Entry(c, textvariable=var)
        e.place(x=px(32), rely=0.5, anchor="w", relwidth=1.0, width=-px(40))
        e.select_range(0, "end")
        e.focus_set()
        self._editor = e
        e._var = var  # type: ignore[attr-defined]  (referência viva)

        def salvar(_evento=None):
            if self._editor is None:
                return
            novo = " ".join(var.get().replace(";", ",").split())[:40]
            self._editor = None
            e.destroy()
            if novo != self.nomes[k]:
                self.nomes[k] = novo
                self.ao_renomear(list(self.nomes))
                if k == self.ativo and novo:
                    self.ao_escolher(novo)
            self._desenhar(k)

        def cancelar(_evento=None):
            self._editor = None
            e.destroy()
            return "break"
        e.bind("<Return>", salvar)
        e.bind("<FocusOut>", salvar)
        e.bind("<Escape>", cancelar)


# Fundo arredondado dos botões de falante. A largura acompanha a janela: a
# cada redimensionamento nasce uma imagem por largura nova, e o cache sem
# limite crescia sem parar (megabytes de imagens do Tk que nunca voltavam).
# Limitado às mais recentes; a que está desenhada fica presa ao próprio
# botão (GradeFalantes._desenhar), então descartá-la daqui não a apaga.
MAX_MOLDURAS = 48
_molduras: "collections.OrderedDict" = collections.OrderedDict()
estilo._ao_trocar_interpretador.append(_molduras.clear)


def _moldura(largura: int, altura: int, fundo: str, fio: str):
    chave = (largura, altura, fundo, fio)
    if chave in _molduras:
        _molduras.move_to_end(chave)
    else:
        while len(_molduras) >= MAX_MOLDURAS:
            _molduras.popitem(last=False)
        try:
            from PIL import Image, ImageDraw, ImageTk

            e = 4
            img = Image.new("RGBA", (largura * e, altura * e), estilo.PAPEL)
            ImageDraw.Draw(img).rounded_rectangle(
                (0, 0, largura * e - 1, altura * e - 1), radius=px(10) * e, fill=fundo,
                outline=fio, width=max(e, round(e * estilo.FATOR)))
            _molduras[chave] = ImageTk.PhotoImage(img.resize((largura, altura), Image.LANCZOS),
                                                  master=estilo._raiz)
        except Exception:
            _molduras[chave] = None
    return _molduras[chave]


def _medir(widget, texto: str, fonte) -> int:
    from tkinter import font as tkfont

    try:
        return tkfont.nametofont(fonte, root=widget).measure(texto)
    except tk.TclError:
        return 0


def _caber_em_linhas(widget, texto: str, fonte, largura: int, linhas: int) -> str:
    """Quebra por palavras em até 'linhas' linhas; a última leva reticências."""
    palavras, saida, atual = texto.split(), [], ""
    for p in palavras:
        tentativa = f"{atual} {p}".strip()
        if _medir(widget, tentativa, fonte) <= largura or not atual:
            atual = tentativa
        else:
            saida.append(atual)
            atual = p
    saida.append(atual)
    if len(saida) > linhas:
        saida = saida[:linhas - 1] + [" ".join(saida[linhas - 1:])]
    saida[-1] = _caber(widget, saida[-1], fonte, largura)
    return "\n".join(saida)


def _caber(widget, texto: str, fonte, largura: int) -> str:
    """Encurta com reticências até caber na largura (em pixels)."""
    from tkinter import font as tkfont

    try:
        f = tkfont.nametofont(fonte, root=widget)
    except tk.TclError:
        return texto
    if f.measure(texto) <= largura:
        return texto
    while texto and f.measure(texto + "…") > largura:
        texto = texto[:-1]
    return texto.rstrip() + "…"


def _hms(segundos: float) -> str:
    s = int(max(0, segundos))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ===================================================================== página
class PaginaTranscrever(Pagina):
    nome = "transcrever"
    titulo = "Transcrever audiência"
    icone = "transcrever"
    marca_log = "[transcrever]"

    def montar(self) -> None:
        self.sessao = None
        self.numero_sessao: cnj.Numero | None = None
        self.situacao = "pronta"        # pronta | iniciando | gravando | pausada | encerrando | fim
        self.numero: cnj.Numero | None = None
        self.ultimo_docx: Path | None = None
        self.ultimo_audio: Path | None = None
        self.ultimas_falas: list = []
        self.ultimo_falante = None
        self._controle = threading.Event()
        self._refinar = False
        self._teste = None
        self._microfones: list = []
        self._microfones_lidos = False
        self._recuperaveis: list[Path] = []
        self._status = {"modelo": "", "atraso": "", "salvo": ""}
        self.tarefa_sessao = self.nova_tarefa("Transcrição da audiência", (MICROFONE,))
        self.tarefa_teste = self.nova_tarefa("Teste do microfone", (MICROFONE,))
        self.tarefa_arquivo = self.nova_tarefa("Transcrição de gravação", (MODELO_REVISAO,))
        self.tarefa_apoio = self.nova_tarefa("Preparar a transcrição")
        self.tarefa_nuvem = self.nova_tarefa("Espelho na nuvem (transcrição)", (NUVEM,))
        self._seguir_fim = True         # a transcrição acompanha a última fala
        self._relogio_id = None

        corpo, _, _ = componentes.estrutura(
            self, "Transcrever audiência",
            "Transcrição simultânea pelo microfone, salva em Word com o número do processo "
            "no nome.", rolavel=False)
        corpo.columnconfigure(1, weight=1)

        # ------------------------------------------- 1. preparação (uma linha)
        prep = ttk.Frame(corpo)
        prep.grid(row=0, column=0, columnspan=2, sticky="ew")
        prep.columnconfigure((0, 1, 2), weight=1, uniform="prep")
        self.prep = prep
        # Durante a audiência os campos acima ficam travados: no lugar deles,
        # uma linha só (processo, tipo e o nível do microfone). Em notebook de
        # 1366x768 a 125% (a janela tem ~540 px de altura útil), a preparação
        # mais um aviso deixavam a área da transcrição com ZERO linhas.
        self.linha_sessao = ttk.Frame(corpo)
        self.linha_sessao.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.linha_sessao.columnconfigure(0, weight=1)
        self.resumo_sessao = ttk.Label(self.linha_sessao, text="", font=estilo.FONTE_NEGRITO,
                                       anchor="w")
        self.resumo_sessao.grid(row=0, column=0, sticky="ew")
        ttk.Label(self.linha_sessao, text="Microfone", foreground=estilo.TINTA_FRACA,
                  font=estilo.FONTE_NOTA).grid(row=0, column=1, sticky="e", padx=(px(12), px(8)))
        self.medidor_sessao = Medidor(self.linha_sessao, largura=px(160), altura=px(6))
        self.medidor_sessao.grid(row=0, column=2, sticky="e")
        self.linha_sessao.grid_remove()

        q = ttk.Frame(prep)
        q.grid(row=0, column=0, sticky="new", padx=(0, px(16)))
        q.columnconfigure(0, weight=1)
        ttk.Label(q, text="Número do processo", foreground=estilo.TINTA_FRACA,
                  font=estilo.FONTE_NOTA).grid(row=0, column=0, sticky="w", pady=(0, px(3)))
        self.var_numero = tk.StringVar(value=self.cfg.texto("interface", "ultimo_processo"))
        self.e_numero = ttk.Entry(q, textvariable=self.var_numero)
        self.e_numero.grid(row=1, column=0, sticky="ew")
        self.e_numero.bind("<FocusOut>", lambda _e: self._formatar_numero())
        self.e_numero.bind("<Return>", lambda _e: self._formatar_numero())
        self.dica_numero = ttk.Label(q, text="", font=estilo.FONTE_NOTA, justify="left")
        self.dica_numero.grid(row=2, column=0, sticky="ew", pady=(px(4), 0))
        estilo.acompanhar_largura(self.dica_numero)
        self.var_numero.trace_add("write", lambda *_: self._validar_numero())

        q = ttk.Frame(prep)
        q.grid(row=0, column=1, sticky="new", padx=(0, px(16)))
        q.columnconfigure(0, weight=1)
        ttk.Label(q, text="Tipo de audiência", foreground=estilo.TINTA_FRACA,
                  font=estilo.FONTE_NOTA).grid(row=0, column=0, sticky="w", pady=(0, px(3)))
        self.var_tipo = tk.StringVar(value=self.cfg.texto("interface", "tipo_audiencia") or TIPOS[0])
        self.c_tipo = ttk.Combobox(q, textvariable=self.var_tipo, values=TIPOS, height=12)
        self.c_tipo.grid(row=1, column=0, sticky="ew")
        self.c_tipo.bind("<<ComboboxSelected>>", lambda _e: self._salvar_tipo())
        self.c_tipo.bind("<FocusOut>", lambda _e: self._salvar_tipo())

        q = ttk.Frame(prep)
        q.grid(row=0, column=2, sticky="new")
        q.columnconfigure(0, weight=1)
        ttk.Label(q, text="Microfone", foreground=estilo.TINTA_FRACA,
                  font=estilo.FONTE_NOTA).grid(row=0, column=0, sticky="w", pady=(0, px(3)))
        self.var_mic = tk.StringVar(value="Procurando microfones…")
        self.c_mic = ttk.Combobox(q, textvariable=self.var_mic, state="readonly", height=10)
        self.c_mic.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.c_mic.bind("<<ComboboxSelected>>", lambda _e: self._salvar_microfone())
        self.medidor = Medidor(q, largura=px(200), altura=px(6))
        self.medidor.grid(row=2, column=0, sticky="ew", pady=(px(6), 0))
        self.btn_testar = estilo.botao(q, "Testar", self.testar_microfone, "texto", pequeno=True)
        self.btn_testar.grid(row=2, column=1, sticky="e", padx=(px(6), 0), pady=(px(4), 0))
        self.dica_mic = ttk.Label(q, text="", font=estilo.FONTE_NOTA, foreground=estilo.TINTA_FRACA,
                                  justify="left")
        self.dica_mic.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(px(4), 0))
        estilo.acompanhar_largura(self.dica_mic)

        # ------------------------------------------- 2. quem está falando
        cab = ttk.Frame(corpo)
        cab.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(px(14), px(8)))
        cab.columnconfigure(0, weight=1)
        ttk.Label(cab, text="Quem está falando", font=estilo.FONTE_NEGRITO).grid(row=0, column=0,
                                                                               sticky="w")
        ttk.Label(cab, text="teclas F1 a F8 · duplo clique troca o nome",
                  foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA).grid(row=0, column=1,
                                                                              sticky="e")
        self.grade = GradeFalantes(corpo, self.cfg.lista("transcricao", "falantes"),
                                   self._falante_escolhido, self._falantes_renomeados)
        self.grade.grid(row=2, column=0, columnspan=2, sticky="ew")

        # ------------------------------------------- 3. controle e texto
        corpo.rowconfigure(3, weight=1)
        quadro_esq, esq = componentes.coluna_rolavel(corpo, margem=0, base=0)
        quadro_esq.configure(width=px(258))
        quadro_esq.grid(row=3, column=0, sticky="nsw", padx=(0, px(20)), pady=(px(6), px(14)))
        quadro_esq.grid_propagate(False)
        esq.columnconfigure(0, weight=1)

        controle = ttk.Frame(esq)
        controle.grid(row=0, column=0, sticky="ew", pady=(px(6), 0))
        controle.columnconfigure(1, weight=1)
        self.redondo = BotaoRedondo(controle, self._clique_redondo)
        self.redondo.grid(row=0, column=0, rowspan=2, sticky="w")
        self.relogio = ttk.Label(controle, text="00:00:00", font=estilo.FONTE_RELOGIO)
        self.relogio.grid(row=0, column=1, sticky="sw", padx=(px(14), 0))
        self.estado_sessao = componentes.EstadoLinha(controle, "Pronto", "neutro",
                                                     fonte=estilo.FONTE)
        self.estado_sessao.grid(row=1, column=1, sticky="nw", padx=(px(14), 0))
        self.btn_encerrar = estilo.botao(esq, "Encerrar e salvar", self.encerrar, "cuidado")
        self.btn_encerrar.grid(row=1, column=0, sticky="ew", pady=(px(12), 0))
        self.btn_encerrar.grid_remove()

        self.var_refinar = tk.BooleanVar(value=self.cfg.flag("transcricao", "refinar_ao_encerrar"))
        ttk.Checkbutton(esq, text="Revisar ao encerrar", variable=self.var_refinar,
                        command=lambda: self.cfg.definir("transcricao", "refinar_ao_encerrar",
                                                         self.var_refinar.get())).grid(
            row=2, column=0, sticky="w", pady=(px(14), 0))
        nota = ttk.Label(esq, text="Refaz tudo com o modelo preciso; leva alguns minutos.",
                         foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA, justify="left")
        nota.grid(row=3, column=0, sticky="ew", padx=(px(26), 0))
        estilo.acompanhar_largura(nota)

        componentes.divisoria(esq).grid(row=4, column=0, sticky="ew", pady=(px(14), px(8)))
        estilo.botao(esq, "Transcrever uma gravação…", self.transcrever_arquivo,
                     "texto", pequeno=True).grid(row=5, column=0, sticky="w")
        self.btn_recuperar = estilo.botao(esq, "Recuperar transcrição interrompida",
                                          self.recuperar, "texto", pequeno=True)
        self.btn_recuperar.grid(row=6, column=0, sticky="w", pady=(px(2), 0))
        self.btn_recuperar.grid_remove()
        estilo.botao(esq, "Abrir a pasta das transcrições", self._abrir_pasta, "texto",
                     pequeno=True).grid(row=7, column=0, sticky="w", pady=(px(2), 0))

        dir_ = ttk.Frame(corpo)
        dir_.grid(row=3, column=1, sticky="nsew", pady=(px(6), px(14)))
        dir_.columnconfigure(0, weight=1)
        dir_.rowconfigure(1, weight=1)
        self._pai_faixa = dir_
        self.faixa = Faixa(dir_, "Sucesso")
        self.faixa.grid(row=0, column=0, sticky="ew", pady=(0, px(10)))
        self.faixa.grid_remove()

        caixa = ttk.Frame(dir_, style="Bloco.TFrame", padding=px(2))
        caixa.grid(row=1, column=0, sticky="nsew")
        caixa.columnconfigure(0, weight=1)
        caixa.rowconfigure(0, weight=1)
        self.texto = tk.Text(caixa, wrap="word", font=estilo.FONTE_TRANSCRICAO, relief="flat",
                             borderwidth=0, padx=px(18), pady=px(14), background=estilo.PAPEL,
                             foreground=estilo.TINTA, highlightthickness=0, spacing1=px(2),
                             spacing3=px(6), cursor="arrow", state="disabled", height=6)
        self.texto.grid(row=0, column=0, sticky="nsew", padx=(px(2), 0), pady=px(2))
        rolagem = ttk.Scrollbar(caixa, orient="vertical", command=self._rolar_pela_barra)
        rolagem.grid(row=0, column=1, sticky="ns", pady=px(8), padx=(0, px(4)))
        self.texto.configure(yscrollcommand=componentes.rolagem_automatica(rolagem))
        # Acompanhar a última fala é decisão do USUÁRIO (rolar para cima para
        # reler; voltar ao fim para seguir), e não da geometria: quando um
        # aviso aparece em cima, os Detalhes se abrem ou a janela muda de
        # tamanho, a caixa encolhe presa pelo topo, a última linha sai de
        # vista e o teste "está no fim?" falhava - a transcrição parava de
        # rolar no meio da audiência.
        for sequencia in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<KeyRelease>",
                          "<ButtonRelease-1>"):
            self.texto.bind(sequencia, lambda _e: self._lembrar_posicao(), add="+")
        self.texto.bind("<Configure>", lambda _e: self._manter_no_fim(), add="+")
        self.texto.tag_configure("rotulo", font=estilo.FONTE_TRANSCRICAO_NEGRITO,
                                 foreground=estilo.AZUL_PROFUNDO, spacing1=px(10))
        self.texto.tag_configure("hora", font=estilo.FONTE_NOTA, foreground=estilo.APAGADO)
        self.texto.tag_configure("marca", font=estilo.FONTE_NOTA, foreground=estilo.TINTA_FRACA,
                                 justify="center", spacing1=px(10), spacing3=px(10))
        self.texto.tag_configure("vazio", foreground=estilo.TINTA_FRACA, font=estilo.FONTE)
        self._placeholder()

        base = ttk.Frame(dir_)
        base.grid(row=2, column=0, sticky="ew", pady=(px(6), 0))
        base.columnconfigure(0, weight=1)
        self.rodape = ttk.Label(base, text="", foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA,
                                justify="left")
        self.rodape.grid(row=0, column=0, sticky="ew")
        estilo.acompanhar_largura(self.rodape)
        self.detalhes = Detalhes(base, "Detalhes técnicos", altura=6)
        self.detalhes.grid(row=1, column=0, sticky="ew", pady=(px(2), 0))

        self._validar_numero()
        self._aplicar_situacao()

    # ============================================================ número
    def _validar_numero(self) -> cnj.Numero | None:
        texto = self.var_numero.get()
        if not texto.strip():
            self.numero = None
            self.dica_numero.configure(text="Obrigatório: dá nome ao documento.",
                                       foreground=estilo.TINTA_FRACA)
            self.e_numero.configure(style="TEntry")
            return None
        try:
            n = cnj.ler(texto)
        except cnj.NumeroInvalido:
            self.numero = None
            self.dica_numero.configure(text="Use o padrão CNJ: 0000000-00.0000.0.00.0000",
                                       foreground=estilo.VINHO)
            self.e_numero.configure(style="Invalido.TEntry")
            return None
        self.numero = n
        self.e_numero.configure(style="TEntry")
        t = tribunais.por_numero(n)
        onde = f" · {t.sigla}" if t else ""
        if n.digito_confere:
            self.dica_numero.configure(text=f"Número conferido{onde}", foreground=estilo.VERDE)
        else:
            self.dica_numero.configure(text=f"{n.formatado}{onde}: o dígito verificador não "
                                            "confere. Confira o número.",
                                       foreground=estilo.AMBAR_TINTA)
        return n

    def _formatar_numero(self) -> None:
        n = self._validar_numero()
        if n is not None and self.var_numero.get() != n.formatado:
            self.var_numero.set(n.formatado)

    def _salvar_tipo(self) -> None:
        tipo = self.var_tipo.get().strip()
        if tipo and tipo != self.cfg.texto("interface", "tipo_audiencia"):
            self.cfg.definir("interface", "tipo_audiencia", tipo)

    # ============================================================ microfone
    def ao_mostrar(self) -> None:
        if not self._microfones_lidos and not self.tarefa_apoio.ativa:
            self._microfones_lidos = True
            self.em_segundo_plano(self.tarefa_apoio, self._ler_ambiente,
                                  ao_concluir=self._ambiente_lido,
                                  ao_falhar=lambda e: self._ambiente_lido(([], str(e), [], None)))
        elif not self.tarefa_apoio.ativa and self.situacao in ("pronta", "fim"):
            # volta à página: o modelo pode ter sido baixado em Configurações,
            # e uma audiência interrompida pode ter aparecido
            def leve():
                modelo = self.cfg.texto("transcricao", "modelo_ao_vivo") or "small"
                return servicos.recuperaveis(self.cfg), (modelo, servicos.modelo_instalado(modelo))

            def aplicar(dados):
                recuperaveis, (nome, instalado) = dados
                self._mostrar_recuperaveis(recuperaveis)
                if self.situacao in ("pronta", "fim"):
                    self._status["modelo"] = f"modelo {nome}" + ("" if instalado else
                                                                 " (será baixado ao iniciar)")
                    self._atualizar_rodape()
            self.em_segundo_plano(self.tarefa_apoio, leve, ao_concluir=aplicar,
                                  ao_falhar=lambda e: None)

    def _ler_ambiente(self):
        erro = ""
        try:
            lista = servicos.listar_microfones()
        except Exception as e:
            lista, erro = [], str(e)
        recuperaveis = servicos.recuperaveis(self.cfg)
        modelo = self.cfg.texto("transcricao", "modelo_ao_vivo") or "small"
        return lista, erro, recuperaveis, (modelo, servicos.modelo_instalado(modelo))

    def _ambiente_lido(self, dados) -> None:
        lista, erro, recuperaveis, modelo = dados
        self._microfones = list(lista)
        padrao = next((e for e in lista if getattr(e, "padrao", False)), None)
        rotulo_padrao = PADRAO_MICROFONE + (f" ({padrao.nome})" if padrao else "")
        valores = [rotulo_padrao] + [e.nome for e in lista]
        self.c_mic.configure(values=valores)
        guardado = self.cfg.texto("transcricao", "dispositivo")
        if guardado and guardado in valores:
            self.var_mic.set(guardado)
        else:
            self.var_mic.set(rotulo_padrao)
        if erro:
            self.dica_mic.configure(text=_maiuscula(erro), foreground=estilo.VINHO)
        elif not lista:
            self.dica_mic.configure(
                text="Nenhum microfone encontrado. Confira se ele está ligado e se o Windows "
                     "permite o acesso (Privacidade › Microfone).", foreground=estilo.VINHO)
        else:
            self.dica_mic.configure(text="", foreground=estilo.TINTA_FRACA)
        if modelo is not None:
            nome, instalado = modelo
            self._status["modelo"] = f"modelo {nome}" + ("" if instalado else
                                                         " (será baixado ao iniciar)")
            self._atualizar_rodape()
        self._mostrar_recuperaveis(recuperaveis)

    def _mostrar_recuperaveis(self, lista) -> None:
        self._recuperaveis = list(lista or [])
        if self._recuperaveis:
            n = len(self._recuperaveis)
            self.btn_recuperar.configure(text="Recuperar transcrição interrompida"
                                         + (f" ({n})" if n > 1 else ""))
            self.btn_recuperar.grid()
        else:
            self.btn_recuperar.grid_remove()

    def _dispositivo(self):
        escolhido = self.var_mic.get()
        if not escolhido or escolhido.startswith(PADRAO_MICROFONE):
            return ""
        return escolhido

    def _salvar_microfone(self) -> None:
        self.cfg.definir("transcricao", "dispositivo", self._dispositivo())
        if self._teste is not None:
            self._parar_teste()

    def testar_microfone(self) -> None:
        if self.tarefa_teste.ativa:
            self._parar_teste()
            return
        if self.tarefa_sessao.ativa:
            return
        fim = threading.Event()
        self._teste = fim
        dispositivo = self._dispositivo()

        def trabalho():
            captura = servicos.abrir_teste_microfone(
                dispositivo, lambda v: self.postar("nivel_teste", v),
                lambda texto: self.postar("aviso_teste", texto))
            try:
                fim.wait(TESTE_MAXIMO_S)
            finally:
                captura.parar()

        def falhou(erro):
            self._teste = None
            self.btn_testar.configure(text="Testar")
            self.dica_mic.configure(text=f"O microfone não abriu: {erro}", foreground=estilo.VINHO)

        def terminou(_):
            self._teste = None
            self.btn_testar.configure(text="Testar")
            self.medidor.zerar()

        if self.em_segundo_plano(self.tarefa_teste, trabalho, ao_concluir=terminou,
                                 ao_falhar=falhou):
            self.btn_testar.configure(text="Parar o teste")
            self.dica_mic.configure(text="Fale normalmente: a barra deve ficar verde e se mexer "
                                         "com a voz.", foreground=estilo.TINTA_FRACA)

    def _parar_teste(self) -> None:
        if self._teste is not None:
            self._teste.set()

    # ============================================================ falantes
    def _falante_escolhido(self, nome: str) -> None:
        if self.sessao is not None and self.situacao in ("gravando", "pausada", "iniciando"):
            try:
                self.sessao.definir_falante(nome)
            except Exception as erro:
                log.warning("não consegui trocar o falante: %s", erro)

    def _falantes_renomeados(self, nomes: list[str]) -> None:
        self.cfg.definir("transcricao", "falantes", ";".join(n for n in nomes if n))

    def atalho(self, evento) -> bool:
        tecla = getattr(evento, "keysym", "")
        if tecla.startswith("F") and tecla[1:].isdigit():
            k = int(tecla[1:]) - 1
            if 0 <= k < 8:
                self.grade.escolher(k)
                return True
        return False

    # ============================================================ sessão
    def _clique_redondo(self) -> None:
        if self.situacao in ("pronta", "fim"):
            self.iniciar()
        elif self.situacao == "gravando":
            self._pausar()
        elif self.situacao == "pausada":
            self._retomar()

    def iniciar(self) -> None:
        self._formatar_numero()
        n = self.numero
        if n is None:
            dialogos.avisar(self.janela.raiz, "Número do processo",
                            "Informe o número do processo: é ele que dá nome ao documento.")
            self.e_numero.focus_set()
            return
        if not n.digito_confere and not dialogos.confirmar(
                self.janela.raiz, "Dígito verificador",
                f"O dígito verificador de {n.formatado} não confere — pode ser erro de "
                "digitação.\n\nComeçar assim mesmo?"):
            return
        self._parar_teste()
        if self.tarefa_teste.ativa:
            self.tarefa_teste.esperar(2)
        self._salvar_tipo()
        self.cfg.definir("interface", "ultimo_processo", n.formatado)
        try:
            sessao = servicos.nova_sessao(n, self.cfg, lambda t, d: self.postar("sessao", (t, d)),
                                          tipo=self.var_tipo.get().strip(),
                                          falante=self.grade.nome_ativo)
        except Exception as erro:
            self.janela.erro_inesperado(erro)
            return
        self._controle = threading.Event()
        controle = self._controle
        tarefa = self.tarefa_sessao

        def trabalho():
            try:
                sessao.iniciar()
            except Exception as erro:
                self.postar("erro_inicio", erro)
                return
            self.postar("iniciada", None)
            while not controle.wait(0.25):
                if tarefa.parar.is_set():      # o programa está fechando
                    self._refinar = False
                    break
            self.postar("encerrando", None)
            try:
                caminho = sessao.encerrar(refinar=self._refinar)
            except Exception as erro:
                log.exception("falha ao encerrar a audiência")
                self.postar("erro_fim", erro)
                return
            self.postar("encerrada", caminho)

        recusa = tarefa.iniciar(trabalho)
        if recusa:
            dialogos.informar(self.janela.raiz, "Aguarde um instante", recusa)
            return
        self.sessao = sessao
        self.numero_sessao = n
        self.ultimo_falante = None
        self._status.update(modelo=f"modelo {getattr(sessao, 'modelo', '')}".strip(), atraso="",
                            salvo="")
        self._limpar_texto()
        self.faixa.grid_remove()
        self.situacao = "iniciando"
        self._aplicar_situacao()
        if self._relogio_id is None:        # um cronômetro só, mesmo reiniciando depressa
            self._relogio()

    def _pausar(self) -> None:
        try:
            self.sessao.pausar()
        except Exception as erro:
            log.warning("não consegui pausar: %s", erro)
            return
        self.situacao = "pausada"
        self._aplicar_situacao()

    def _retomar(self) -> None:
        try:
            self.sessao.retomar()
        except Exception as erro:
            log.warning("não consegui retomar: %s", erro)
            return
        self.situacao = "gravando"
        self._aplicar_situacao()

    def encerrar(self) -> None:
        if self.situacao not in ("gravando", "pausada", "iniciando"):
            return
        self._refinar = bool(self.var_refinar.get())
        self.situacao = "encerrando"
        self._aplicar_situacao()
        self._controle.set()

    def _relogio(self) -> None:
        self._relogio_id = None
        if self.sessao is None or self.situacao in ("pronta", "fim"):
            return
        try:
            self.relogio.configure(text=_hms(self.sessao.tempo))
        except Exception:
            pass
        self._relogio_id = self.after(500, self._relogio)

    def _aplicar_situacao(self) -> None:
        s = self.situacao
        botao = {"pronta": "iniciar", "fim": "iniciar", "gravando": "pausar", "pausada": "retomar"}
        self.redondo.definir(botao.get(s, "aguarde"))
        textos = {"pronta": ("Pronto", "neutro"),
                  "iniciando": ("Abrindo o microfone…", "ocupado"),
                  "gravando": ("Gravando", "erro"),
                  "pausada": ("Pausado", "aviso"),
                  "encerrando": ("Revisando com o modelo preciso…" if self._refinar
                                 else "Salvando o documento…", "ocupado"),
                  "fim": ("Transcrição salva", "ok")}
        self.estado_sessao.definir(*textos.get(s, ("", "neutro")))
        ativa = s in ("iniciando", "gravando", "pausada")
        if ativa:
            self.btn_encerrar.grid()
        else:
            self.btn_encerrar.grid_remove()
        self._modo_audiencia(s in ("iniciando", "gravando", "pausada", "encerrando"))
        estado_campos = ["disabled"] if s in ("iniciando", "gravando", "pausada", "encerrando") \
            else ["!disabled"]
        for w in (self.e_numero, self.c_tipo, self.btn_testar):
            w.state(estado_campos)
        self.c_mic.state(estado_campos + (["readonly"] if "!disabled" in estado_campos else []))
        if s == "pronta":
            self.relogio.configure(text="00:00:00")
        self._atualizar_rodape()
        self.janela.atualizar_indicadores()

    def _modo_audiencia(self, ligado: bool) -> None:
        """Na audiência, a preparação (travada) vira uma linha e o subtítulo
        sai: a altura vai para a transcrição."""
        subtitulo = getattr(self, "_subtitulo", None)
        if ligado:
            n = self.numero_sessao
            partes = [f"Processo {n.formatado}" if n else "", self.var_tipo.get().strip()]
            self.resumo_sessao.configure(text=" · ".join(p for p in partes if p))
            self.prep.grid_remove()
            self.linha_sessao.grid()
            if subtitulo is not None:
                subtitulo.grid_remove()
        else:
            self.linha_sessao.grid_remove()
            self.prep.grid()
            if subtitulo is not None:
                subtitulo.grid()
            self.medidor_sessao.zerar()

    # ============================================================ eventos
    def ao_evento(self, tipo: str, dado) -> None:
        if tipo == "sessao":
            self._evento_sessao(*dado)
        elif tipo == "iniciada":
            if self.situacao == "iniciando":
                self.situacao = "gravando"
                self._aplicar_situacao()
            if self.grade.ativo < 0 and self.grade.nomes[0]:
                self.grade.escolher(0)
        elif tipo == "erro_inicio":
            self.sessao = None
            self.situacao = "pronta"
            self._aplicar_situacao()
            self._placeholder()
            dialogos.erro(self.janela.raiz, "A transcrição não começou",
                          f"{_maiuscula(str(dado))}\n\nConfira o microfone (botão Testar) e tente "
                          "de novo.")
        elif tipo == "encerrando":
            if self.situacao != "encerrando":
                self.situacao = "encerrando"
                self._aplicar_situacao()
        elif tipo == "encerrada":
            self._encerrada(Path(dado))
        elif tipo == "erro_fim":
            self.situacao = "fim"
            self._aplicar_situacao()
            self._faixa("Erro", "O documento final não pôde ser gravado",
                        f"{_maiuscula(str(dado)).rstrip('.')}. O áudio e o diário da audiência "
                        "estão na pasta _audio; use “Recuperar transcrição interrompida”.")
        elif tipo == "nivel_teste":
            self.medidor.definir(dado)
        elif tipo == "aviso_teste":
            self.dica_mic.configure(text=str(dado), foreground=estilo.AMBAR_TINTA)
        elif tipo == "arquivo_progresso":
            fracao, texto = dado
            self._status["salvo"] = f"{texto} ({fracao:.0%})"
            self._atualizar_rodape()
        elif tipo == "_tarefa_fim":
            if dado is self.tarefa_sessao and self.situacao in ("iniciando", "gravando", "pausada",
                                                                "encerrando"):
                self.janela.raiz.after(400, self._conferir_fim)

    def _conferir_fim(self) -> None:
        if not self.tarefa_sessao.ativa and self.situacao in ("iniciando", "gravando", "pausada",
                                                              "encerrando"):
            self.situacao = "fim" if self.ultimo_docx else "pronta"
            self._aplicar_situacao()

    def _evento_sessao(self, tipo: str, dado) -> None:
        if tipo == "nivel":
            self.medidor.definir(dado)
            self.medidor_sessao.definir(dado)
        elif tipo == "estado":
            texto = str(dado)
            if texto.lower().startswith(("gravando", "pausado")):
                return
            self._status["modelo"] = _maiuscula(texto)
            self._atualizar_rodape()
        elif tipo == "fala":
            self._escrever_fala(dado)
        elif tipo == "atraso":
            segundos = float(dado or 0)
            self._status["atraso"] = f"atraso de {segundos:.0f} s" if segundos >= 1 else ""
            self._atualizar_rodape(alerta=segundos > 10)
        elif tipo == "aviso":
            self._faixa("Aviso", "Atenção", str(dado))
        elif tipo == "erro":
            self._faixa("Erro", "Algo deu errado na transcrição", str(dado))
        elif tipo == "salvo":
            self._status["salvo"] = f"salvo às {datetime.now():%H:%M:%S}"
            self.ultimo_docx = Path(dado)
            self._atualizar_rodape()
        elif tipo == "fim":
            self.ultimo_docx = Path(dado)

    # ---------------------------------------------------------------- texto
    def _placeholder(self) -> None:
        self.texto.configure(state="normal")
        self.texto.delete("1.0", "end")
        self.texto.insert("1.0", PLACEHOLDER, "vazio")
        self.texto.configure(state="disabled")
        self._vazio = True

    def _limpar_texto(self) -> None:
        self.texto.configure(state="normal")
        self.texto.delete("1.0", "end")
        self.texto.configure(state="disabled")
        self._vazio = False
        self._seguir_fim = True
        self.ultimo_falante = None

    # ---------------------------------------------------------------- rolagem
    def _rolar_pela_barra(self, *args) -> None:
        self.texto.yview(*args)
        self._lembrar_posicao()

    def _lembrar_posicao(self) -> None:
        """Depois de uma rolagem do usuário: está no fim (segue as falas) ou
        subiu para reler (a tela não o arrasta de volta)?"""
        def medir():
            try:
                self._seguir_fim = self.texto.yview()[1] >= 0.999
            except tk.TclError:
                pass
        self.texto.after_idle(medir)

    def _manter_no_fim(self) -> None:
        if self._seguir_fim:
            self.texto.after_idle(lambda: self.texto.see("end"))

    def _escrever_fala(self, fala) -> None:
        if getattr(self, "_vazio", False):
            self._limpar_texto()
        no_fim = self._seguir_fim
        rotulo = (getattr(fala, "falante", "") or "").strip()
        texto = (getattr(fala, "texto", "") or "").strip()
        if not texto:
            return
        self.texto.configure(state="normal")
        if not rotulo and getattr(fala, "inicio", 0) == getattr(fala, "fim", -1):
            self.texto.insert("end", f"\n{texto}\n", "marca")    # pausa/retomada
            self.ultimo_falante = None
        elif rotulo == self.ultimo_falante and self.texto.index("end-1c") != "1.0":
            self.texto.insert("end-1c", " " + texto)
        else:
            if self.texto.index("end-1c") != "1.0":
                self.texto.insert("end", "\n")
            self.texto.insert("end", (rotulo or "Sem identificação").upper(), "rotulo")
            self.texto.insert("end", f"   {_hms(getattr(fala, 'inicio', 0))}\n", "hora")
            self.texto.insert("end", texto + "\n")
            self.ultimo_falante = rotulo
        self.texto.configure(state="disabled")
        if no_fim:
            self.texto.see("end")

    def _atualizar_rodape(self, alerta: bool = False) -> None:
        partes = [p for p in (self._status.get("modelo"), self._status.get("atraso"),
                              self._status.get("salvo")) if p]
        if self.sessao is not None and getattr(self.sessao, "caminho_docx", None) \
                and self.situacao != "pronta":
            partes.append(Path(self.sessao.caminho_docx).name)
        self.rodape.configure(text="  ·  ".join(partes),
                              foreground=estilo.AMBAR_TINTA if alerta else estilo.TINTA_FRACA)

    def _faixa(self, tipo: str, titulo: str, texto: str, acoes: list | None = None) -> None:
        self.faixa.destroy()
        self.faixa = Faixa(self._pai_faixa, tipo, texto=texto, titulo=titulo)
        self.faixa.grid(row=0, column=0, sticky="ew", pady=(0, px(10)))
        for rotulo, comando, familia in acoes or []:
            self.faixa.acao(rotulo, comando, familia)

    # ------------------------------------------------------------- fim
    def _encerrada(self, caminho: Path) -> None:
        sessao = self.sessao
        self.ultimo_docx = caminho
        self.ultimo_audio = getattr(sessao, "caminho_audio", None)
        self.ultimas_falas = list(getattr(sessao, "falas", []) or [])
        self.situacao = "fim"
        self._aplicar_situacao()
        self.medidor.zerar()
        acoes = [("Abrir o documento", lambda: self._abrir(caminho), "principal"),
                 ("Abrir a pasta", lambda: self._abrir_pasta(caminho), "apoio")]
        if self.ultimo_audio and Path(self.ultimo_audio).exists():
            acoes.append(("Revisar agora", self.revisar, "apoio"))
        self._faixa("Sucesso", "Transcrição salva", caminho.name, acoes)
        estilo.piscar_na_barra(self.janela.raiz)
        self._espelhar_se_preciso()

    def revisar(self) -> None:
        if not self.ultimo_audio or self.numero_sessao is None:
            return
        self._transcrever_gravacao(Path(self.ultimo_audio), self.numero_sessao,
                                   rotulos=self.ultimas_falas, titulo="Revisando com o modelo preciso")

    # ============================================================ gravação
    def transcrever_arquivo(self) -> None:
        if self.tarefa_arquivo.ativa:
            return
        caminho = filedialog.askopenfilename(parent=self.janela.raiz,
                                             title="Escolha a gravação da audiência",
                                             filetypes=EXTENSOES_AUDIO)
        if not caminho:
            return
        caminho = Path(caminho)
        numero = servicos.numero_no_nome(caminho)

        def seguir(n):
            self._transcrever_gravacao(caminho, n, titulo="Transcrevendo a gravação")
        if numero is not None:
            seguir(numero)
            return
        # Sem o número no nome do arquivo, PERGUNTA - com o do campo já
        # escrito, para confirmar com Enter. Antes ele era usado em silêncio, e
        # o campo quase sempre traz o processo da audiência ANTERIOR (é
        # lembrado entre as sessões): o documento saía com o número errado.
        atual = self._validar_numero()
        dialogos.DialogoNumero(self.janela.raiz, "De que processo é esta gravação?",
                               "O nome do arquivo não traz o número do processo. Ele dá "
                               "nome ao documento.", seguir,
                               inicial=atual.formatado if atual is not None else "")

    def _transcrever_gravacao(self, origem: Path, numero, rotulos=None, titulo: str = "") -> None:
        tarefa = self.tarefa_arquivo
        tipo = self.var_tipo.get().strip()

        def progresso(fracao, texto=""):
            self.postar("arquivo_progresso", (float(fracao or 0), str(texto or titulo)))

        def trabalho():
            return servicos.transcrever_gravacao(origem, numero, self.cfg, progresso,
                                                 tarefa.parar.is_set, rotulos_manuais=rotulos,
                                                 tipo=tipo)

        def pronto(caminho):
            self._status["salvo"] = ""
            self._atualizar_rodape()
            caminho = Path(caminho)
            self.ultimo_docx = caminho
            self._faixa("Sucesso", "Transcrição pronta", caminho.name,
                        [("Abrir o documento", lambda: self._abrir(caminho), "principal"),
                         ("Abrir a pasta", lambda: self._abrir_pasta(caminho), "apoio")])
            estilo.piscar_na_barra(self.janela.raiz)
            self._espelhar_se_preciso()

        def falhou(erro):
            self._status["salvo"] = ""
            self._atualizar_rodape()
            if servicos.excecao_cancelado(erro):
                self._faixa("Info", "Transcrição interrompida", "Nada foi gravado.")
                return
            self._faixa("Erro", "A gravação não pôde ser transcrita", _maiuscula(str(erro)))

        if self.em_segundo_plano(tarefa, trabalho, ao_concluir=pronto, ao_falhar=falhou):
            self._faixa("Info", titulo or "Transcrevendo",
                        f"{origem.name} → {numero.nome_arquivo}.docx. Pode continuar usando o "
                        "programa; o aviso aparece aqui quando terminar.",
                        [("Cancelar", tarefa.pedir_parada, "apoio")])

    def recuperar(self) -> None:
        if not self._recuperaveis:
            return
        alvo = self._recuperaveis[0]
        if not dialogos.confirmar(
                self.janela.raiz, "Recuperar transcrição",
                f"Encontrei uma audiência que foi interrompida antes de terminar:\n\n{alvo.stem}"
                "\n\nRefazer o documento com o que foi transcrito até a interrupção?"):
            return

        def pronto(caminho):
            caminho = Path(caminho)
            self._mostrar_recuperaveis(self._recuperaveis[1:])
            self._faixa("Sucesso", "Transcrição recuperada", caminho.name,
                        [("Abrir o documento", lambda: self._abrir(caminho), "principal")])

        self.em_segundo_plano(self.tarefa_apoio, servicos.recuperar, alvo, ao_concluir=pronto,
                              ao_falhar=lambda e: self._faixa("Erro", "Não consegui recuperar",
                                                              str(e)))

    # ============================================================ apoio
    def _abrir(self, caminho: Path) -> None:
        try:
            sistema.abrir_arquivo(caminho)
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Abrir o documento", str(erro))

    def _abrir_pasta(self, selecionar: Path | None = None) -> None:
        try:
            sistema.abrir_pasta(self.cfg.pasta_transcricoes, selecionar)
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Abrir a pasta", str(erro))

    def _espelhar_se_preciso(self) -> None:
        """Espelho automático na nuvem ao fim de cada transcrição.

        Tarefa própria (a de apoio podia estar ocupada lendo os microfones, e
        o espelho era descartado sem aviso), interrompível (o fechar do
        programa não espera a cópia do acervo inteiro) e nunca durante o
        fechamento (a audiência salva ao fechar não dispara cópia nova).
        """
        destino = self.cfg.texto("compartilhar", "pasta_nuvem")
        if not (destino and self.cfg.flag("compartilhar", "espelhar_automaticamente")):
            return
        if getattr(self.janela, "_fechando", False):
            return
        from ..compartilhar import nuvem

        tarefa = self.tarefa_nuvem
        recusa = tarefa.iniciar(nuvem.espelhar, self.cfg.pasta_acervo, Path(destino), None,
                                tarefa.parar.is_set)
        if recusa:
            log.info("espelho na nuvem adiado: %s", recusa)

    def indicador(self):
        if self.situacao in ("gravando", "iniciando") and self.sessao is not None:
            return (_hms(getattr(self.sessao, "tempo", 0))[-5:] if self.situacao == "gravando"
                    else "", estilo.VINHO)
        if self.situacao == "pausada":
            return ("pausa", estilo.AMBAR_TINTA)
        if self.tarefa_arquivo.ativa or self.situacao == "encerrando":
            return ("", estilo.AZUL)
        return None

    def resumo_ao_vivo(self):
        if self.situacao == "gravando" and self.sessao is not None:
            return (f"Gravando agora · {_hms(self.sessao.tempo)}", "erro")
        if self.situacao == "pausada":
            return ("Audiência pausada", "aviso")
        if self.tarefa_arquivo.ativa:
            return ("Transcrevendo uma gravação…", "ocupado")
        return None

    def trabalho_em_andamento(self) -> list[str]:
        itens = []
        if self.tarefa_sessao.ativa:
            n = getattr(self, "numero_sessao", None)
            itens.append(f"Transcrição da audiência{f' do processo {n.formatado}' if n else ''} "
                         "(será salva antes de fechar)")
        if self.tarefa_arquivo.ativa:
            itens.append("Transcrição de gravação (será interrompida)")
        return itens

    def antes_de_fechar(self) -> None:
        self._parar_teste()
        if self.sessao is not None and self.situacao == "encerrando":
            # Revisão final em curso: interrompe a revisão (o documento ao
            # vivo já está salvo) em vez de segurar o fechamento por minutos.
            try:
                self.sessao.cancelar()
            except Exception:
                pass
        super().antes_de_fechar()


def _maiuscula(texto: str) -> str:
    texto = (texto or "").strip()
    return texto[:1].upper() + texto[1:]
