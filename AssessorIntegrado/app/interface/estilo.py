"""Aparência do programa: paleta, tipografia, escala de tela e botões.

    O PADRÃO É A PÁGINA INICIAL DO CHROME

Herdado do Assessor SAJ: página branca, uma cor de destaque só, formas
macias. A regra continua valendo:

    A COR INFORMA, NÃO ENFEITA.

O azul aparece só onde há decisão (o botão principal, a página aberta, o
foco de um campo, a linha escolhida). Verde, âmbar e vermelho só aparecem
para dizer "deu certo", "atenção" e "deu errado".

Pesos de botão:

    principal   azul cheio, letra branca       a ação central da tela (uma por tela)
    tonal       azul-pálido, letra azul-escura  a ação central de um cartão
    apoio       branco, fio suave, letra azul  todo o resto
    texto       sem fundo, letra azul           ação discreta, tipo link
    cuidado     cinza-escuro, letra branca     só o que interrompe (Parar, Encerrar)

Os cantos arredondados são imagens desenhadas pelo Pillow em tempo de
execução, em escala 4x e reduzidas (borda macia), usadas como elementos
"9 fatias" do ttk: o ttk.Button continua por baixo, e .state(), teclado e
foco funcionam como sempre. Sem o Pillow, cai no tema reto com as mesmas
cores - nada quebra.

ESCALA (DPI). O Assessor SAJ fixava `tk scaling 1.2` com o processo
declarado "DPI-aware": a 125% as letras saíam menores que as do Windows e
as pílulas de 44x36 px não cresciam. Aqui o processo é "system aware"
(SetProcessDpiAwareness(1) - o modo 2, por monitor, exigiria tratar
WM_DPICHANGED, que o Tk 8.6 não trata), o `tk scaling` vem do DPI real e
tudo o que é medido em pixels (imagens, margens) passa por px().
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

log = logging.getLogger("interface.estilo")

RECURSOS = Path(__file__).resolve().parent / "recursos"

# ------------------------------------------------------------------- paleta
AZUL = "#1a73e8"
AZUL_CLARO = "#1967d2"       # sob o mouse
AZUL_ESCURO = "#185abc"      # apertado
AZUL_PROFUNDO = "#174ea6"    # letra sobre o azul-pálido
AZUL_PALIDO = "#e8f0fe"      # linha selecionada, botão tonal
AZUL_TONAL_SOBRE = "#d2e3fc"
AZUL_TONAL_APERTADO = "#c6dafc"
AZUL_TINTA = "#f6fafe"       # o botão de apoio sob o mouse
AZUL_FIO = "#aecbfa"         # contorno do cartão sob o mouse

PAPEL = "#ffffff"            # a página e os cartões
MOLDURA = "#f6f8fc"          # o fundo da janela, atrás da página e da barra lateral
SELECAO = "#d3e3fd"          # o item aberto da barra lateral
SOBRE_MOLDURA = "#e9eef6"    # item da barra lateral sob o mouse
FAIXA_CLARA = "#f8f9fa"      # registro de andamento, caixas de leitura
SUPERFICIE = "#f1f3f4"       # botão desabilitado, trilho de barra
LINHA = "#dadce0"            # o fio quase invisível
LINHA_FORTE = "#bdc1c6"
TINTA = "#202124"
TINTA_FRACA = "#5f6368"
APAGADO = "#9aa0a6"
ESCURO = "#3c4043"           # o botão de cuidado
ESCURO_CLARO = "#5f6368"
ESCURO_FUNDO = "#202124"

VINHO = "#c5221f"            # erro
VINHO_FUNDO = "#fce8e6"
VERDE = "#188038"            # sucesso
VERDE_FUNDO = "#e6f4ea"
AMBAR = "#f9ab00"            # atenção
AMBAR_FUNDO = "#fef7e0"
AMBAR_TINTA = "#8a5a00"      # letra de atenção sobre o branco (legível)

REGISTRO_FUNDO = FAIXA_CLARA

# Por família: (fundo, sob o mouse, apertado, contorno, letra).
FAMILIAS = {
    "principal": (AZUL, AZUL_CLARO, AZUL_ESCURO, None, "#ffffff"),
    "tonal": (AZUL_PALIDO, AZUL_TONAL_SOBRE, AZUL_TONAL_APERTADO, None, AZUL_PROFUNDO),
    "apoio": (PAPEL, AZUL_TINTA, AZUL_PALIDO, LINHA, AZUL),
    "texto": (None, AZUL_PALIDO, AZUL_TONAL_SOBRE, None, AZUL),
    "cuidado": (ESCURO, ESCURO_CLARO, ESCURO_FUNDO, None, "#ffffff"),
}
# Nomes antigos da base, aceitos nas chamadas.
SINONIMOS = {"guardar": "apoio", "mover": "apoio"}

# (sufixo do estilo, fonte, espaço interno em px a 96 dpi)
TAMANHOS = {
    "": ("AI.Botao", (16, 7)),
    "Grande.": ("AI.BotaoGrande", (22, 10)),
    "Pequeno.": ("AI.Nota", (10, 4)),
}

# Superfícies sobre as quais um botão pode ficar: o ttk pinta o fundo do
# estilo atrás dos cantos transparentes da pílula, e ele tem de ser a cor
# de quem está atrás - senão o botão ganha "orelhas" brancas.
SUPERFICIES = {"": PAPEL, "Moldura.": MOLDURA, "Aviso.": AMBAR_FUNDO, "Sucesso.": VERDE_FUNDO,
               "Erro.": VINHO_FUNDO, "Info.": AZUL_PALIDO, "Faixa.": FAIXA_CLARA}

ESPACO = 8                     # entre botões de uma fileira

# ---------------------------------------------------------------- tipografia
# Nomes de fontes do Tk. São criadas por preparar_fontes() com a família
# que existir no computador; os widgets usam o NOME, e assim uma troca de
# família ou tamanho vale para a janela inteira.
FONTE = "AI.Texto"
FONTE_NEGRITO = "AI.Negrito"
FONTE_NOTA = "AI.Nota"
FONTE_NOTA_NEGRITO = "AI.NotaNegrito"
FONTE_BOTAO = "AI.Botao"
FONTE_BOTAO_GRANDE = "AI.BotaoGrande"
FONTE_SECAO = "AI.Secao"
FONTE_CARTAO = "AI.Cartao"
FONTE_PAGINA = "AI.Pagina"
FONTE_SAUDACAO = "AI.Saudacao"
FONTE_RELOGIO = "AI.Relogio"
FONTE_MONO = "AI.Mono"
FONTE_CODIGO = "AI.Codigo"
FONTE_TRANSCRICAO = "AI.Transcricao"
FONTE_TRANSCRICAO_NEGRITO = "AI.TranscricaoNegrito"
FONTE_MARCA = "AI.Marca"

# Segoe UI é a fonte do Windows. Open Sans (do mesmo desenhista) e as
# demais só entram fora do Windows - desenvolvimento e capturas no Linux.
_FAMILIAS_TEXTO = ("Segoe UI", "Open Sans", "Liberation Sans", "Arimo", "DejaVu Sans",
                   "Arial", "Helvetica")
_FAMILIAS_MONO = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono",
                  "Courier New", "Courier")

FATOR = 1.0                    # pixels de tela por pixel "de projeto" (96 dpi)
_imagens: list = []            # o Tk descarta a imagem se ninguém guardar a referência
_cache_imagens: dict = {}
_fontes: dict = {}             # fontes nomeadas (referência viva: ver preparar_fontes)
_familia_texto = ""


def px(valor: float) -> int:
    """Converte uma medida de projeto (pixels a 96 dpi) para a tela atual."""
    return int(round(valor * FATOR))


def pxs(*valores: float) -> tuple[int, ...]:
    return tuple(px(v) for v in valores)


# -------------------------------------------------------------- DPI e janela
def consciencia_de_dpi() -> None:
    """Declara o processo "system DPI aware" ANTES de criar a janela.

    Sem isso, o Windows a 125% ou 150% estica a janela como bitmap e tudo
    sai borrado.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def preparar_escala(raiz: tk.Misc) -> float:
    """Ajusta o `tk scaling` ao DPI real e calcula FATOR."""
    global FATOR
    try:
        dpi = float(raiz.winfo_fpixels("1i"))
    except tk.TclError:
        dpi = 96.0
    if not 60 <= dpi <= 480:      # monitor que informa tamanho absurdo
        dpi = 96.0
    raiz.tk.call("tk", "scaling", dpi / 72.0)
    FATOR = max(1.0, dpi / 96.0)
    return FATOR


def _colorref(hexa: str) -> int:
    """'#rrggbb' no formato COLORREF do Windows (0x00bbggrr)."""
    r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
    return (b << 16) | (g << 8) | r


def pintar_barra_de_titulo(raiz: tk.Misc, cor: str = MOLDURA, letra: str = TINTA) -> bool:
    """Pinta a barra de título do Windows 11 com a cor da moldura.

    Só o Windows 11 (build 22000+) aceita; nos outros nada muda e a função
    devolve False em silêncio.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        raiz.update_idletasks()
        # O id do Tk é a janela-filha; a moldura com a barra é a mãe dela.
        alvo = ctypes.windll.user32.GetParent(raiz.winfo_id()) or raiz.winfo_id()
        for atributo, valor in ((35, cor), (36, letra)):   # DWMWA_CAPTION/TEXT_COLOR
            dado = ctypes.c_int(_colorref(valor))
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    alvo, atributo, ctypes.byref(dado), ctypes.sizeof(dado)) != 0:
                return False
        return True
    except Exception as erro:
        log.debug("não pintei a barra de título: %s", erro)
        return False


def piscar_na_barra(raiz: tk.Misc) -> None:
    """Faz o botão do programa piscar na barra de tarefas (FlashWindowEx).

    Usado quando o portal pede o código de verificação ou um trabalho termina
    com a janela em segundo plano: o magistrado está em outro programa e
    precisa notar sem que a janela roube o foco.
    """
    if sys.platform != "win32":
        try:
            raiz.bell()
        except tk.TclError:
            pass
        return
    try:
        import ctypes
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                        ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                        ("dwTimeout", wintypes.DWORD)]

        alvo = ctypes.windll.user32.GetParent(raiz.winfo_id()) or raiz.winfo_id()
        # FLASHW_ALL | FLASHW_TIMERNOFG: pisca até a janela voltar ao primeiro plano
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), alvo, 0x3 | 0xC, 0, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception as erro:
        log.debug("não pisquei a janela: %s", erro)


def aplicar_icone(raiz: tk.Misc) -> bool:
    """Ícone próprio na barra de título, na barra de tarefas e nos diálogos."""
    posto = False
    ico, png = RECURSOS / "assessor.ico", RECURSOS / "assessor.png"
    if sys.platform == "win32" and ico.exists():
        try:
            raiz.iconbitmap(default=str(ico))
            posto = True
        except tk.TclError as erro:
            log.debug("ícone .ico recusado: %s", erro)
    # O .png cobre a barra de tarefas e os diálogos, onde o .ico às vezes
    # não chega (e é o único que funciona fora do Windows).
    imagens = [imagem(n, t) for n, t in (("assessor", 256), ("assessor-64", 64), ("assessor-64", 32))]
    imagens = [i for i in imagens if i is not None]
    if imagens:
        try:
            raiz.iconphoto(True, *imagens)
            posto = True
        except tk.TclError as erro:
            log.debug("ícone .png recusado: %s", erro)
    return posto


# ------------------------------------------------------------------- imagens
def _tem_pillow() -> bool:
    try:
        import PIL.Image  # noqa: F401
        import PIL.ImageTk  # noqa: F401
        return True
    except Exception:
        return False


def imagem(nome: str, tamanho: int, selo: str | None = None) -> tk.PhotoImage | None:
    """Ícone de recursos/<nome>.png no tamanho pedido (pixels de TELA).

    Com Pillow, redimensiona com LANCZOS (nítido em qualquer escala); sem
    ele, usa o PhotoImage do Tk com redução inteira. 'selo' desenha um
    ponto colorido no canto superior direito (tarefa em andamento).
    Devolve None se o arquivo faltar: ícone ausente nunca impede a janela.
    """
    chave = (nome, tamanho, selo)
    if chave in _cache_imagens:
        return _cache_imagens[chave]
    arquivo = RECURSOS / f"{nome}.png"
    foto = None
    if arquivo.exists():
        try:
            if _tem_pillow():
                from PIL import Image, ImageDraw, ImageTk

                img = Image.open(arquivo).convert("RGBA").resize((tamanho, tamanho), Image.LANCZOS)
                if selo:
                    grande = img.resize((tamanho * 4, tamanho * 4), Image.LANCZOS)
                    d = ImageDraw.Draw(grande)
                    r = tamanho * 4 * 0.2
                    cx, cy = tamanho * 4 - r - 1, r + 1
                    d.ellipse((cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5), fill=MOLDURA)
                    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=selo)
                    img = grande.resize((tamanho, tamanho), Image.LANCZOS)
                foto = ImageTk.PhotoImage(img, master=_raiz)
            else:
                foto = tk.PhotoImage(file=str(arquivo), master=_raiz)
                fator = max(1, round(foto.width() / max(1, tamanho)))
                if fator > 1:
                    foto = foto.subsample(fator, fator)
        except Exception as erro:
            log.debug("ícone %s indisponível: %s", nome, erro)
            foto = None
    _cache_imagens[chave] = foto
    return foto


def ponto(cor: str, fundo: str = PAPEL) -> tk.PhotoImage | None:
    """Bolinha colorida de 8 px (estado). Desenhada, e não um caractere '●':
    nem toda fonte tem o glifo, e sem ele o Tk mostra '\\u25cf'."""
    chave = ("ponto", cor, fundo)
    if chave in _cache_imagens:
        return _cache_imagens[chave]
    foto = None
    try:
        from PIL import Image, ImageDraw, ImageTk

        t, e = px(8), 4
        img = Image.new("RGBA", (t * e, t * e), fundo)
        ImageDraw.Draw(img).ellipse((0, 0, t * e - 1, t * e - 1), fill=cor)
        foto = ImageTk.PhotoImage(img.resize((t, t), Image.LANCZOS), master=_raiz)
    except Exception:
        foto = None
    _cache_imagens[chave] = foto
    return foto


def _pilula(largura: int, altura: int, fundo, contorno, raio: int | None = None,
            externo: str | None = None, sombra: bool = False, margem: int = 0):
    """Retângulo arredondado desenhado em 4x e reduzido (borda macia).

    'externo' pinta o lado de fora dos cantos com uma cor sólida em vez de
    transparência (cartões e painéis, que ficam sempre sobre a mesma cor);
    'sombra' acrescenta uma sombra suave embaixo (elevação do cartão).
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageTk

    e = 4
    L, A = largura * e, altura * e
    r = (raio if raio is not None else min(altura // 2, px(10))) * e
    m = margem * e
    if externo:
        img = Image.new("RGBA", (L, A), externo)
    else:
        img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    caixa = (m, m, L - 1 - m, A - 1 - m)
    if sombra and m:
        camada = Image.new("RGBA", (L, A), (0, 0, 0, 0))
        ImageDraw.Draw(camada).rounded_rectangle(
            (m, m + e * 1.5, L - 1 - m, A - 1 - m + e * 1.5), radius=r, fill=(60, 64, 67, 40))
        camada = camada.filter(ImageFilter.GaussianBlur(e * 2.2))
        img.alpha_composite(camada)
    d = ImageDraw.Draw(img)
    if fundo is not None or contorno:
        d.rounded_rectangle(caixa, radius=r, fill=fundo, outline=contorno,
                            width=max(1, round(e * FATOR)) if contorno else 0)
    foto = ImageTk.PhotoImage(img.resize((largura, altura), Image.LANCZOS), master=_raiz)
    _imagens.append(foto)
    return foto


def _elemento(estilo: ttk.Style, nome: str, imagens: list, **opcoes) -> None:
    """Cria o elemento de imagem uma vez; chamado de novo, deixa como está."""
    try:
        estilo.element_create(nome, "image", *imagens, **opcoes)
    except tk.TclError:
        pass


# ------------------------------------------------------------------- botões
def _familia_arredondada(estilo: ttk.Style, nome: str, fundo, sobre, apertado, contorno,
                         letra) -> None:
    tam = pxs(44, 36)
    raio = px(18)              # pílula de verdade: meia altura do botão padrão
    desab = SUPERFICIE if fundo is not None else None
    imagens = [_pilula(*tam, fundo, contorno, raio),
               ("disabled", _pilula(*tam, desab, None, raio)),
               ("pressed", _pilula(*tam, apertado, contorno, raio)),
               ("active", _pilula(*tam, sobre, contorno, raio)),
               ("focus", _pilula(*tam, fundo, AZUL if nome != "principal" else AZUL_ESCURO, raio))]
    borda = px(17)
    for sufixo, (fonte, espaco) in TAMANHOS.items():
        elemento = f"{nome}.{sufixo}pilula"
        _elemento(estilo, elemento, imagens, border=borda, sticky="nsew",
                  padding=pxs(*espaco))
        chave = f"{nome}.{sufixo}TButton"
        estilo.layout(chave, [(elemento, {"sticky": "nsew", "children": [
            ("Button.label", {"sticky": "nsew"})]})])
        estilo.configure(chave, foreground=letra, font=fonte, anchor="center",
                         background=PAPEL)
        estilo.map(chave, foreground=[("disabled", APAGADO)],
                   background=[("active", PAPEL), ("pressed", PAPEL)])


def _familia_reta(estilo: ttk.Style, nome: str, fundo, sobre, apertado, contorno, letra) -> None:
    """O plano B, sem Pillow: reto, com as mesmas cores."""
    fundo = fundo or PAPEL
    fio = contorno or fundo
    for sufixo, (fonte, espaco) in TAMANHOS.items():
        chave = f"{nome}.{sufixo}TButton"
        estilo.configure(chave, background=fundo, foreground=letra, font=fonte,
                         padding=pxs(*espaco), borderwidth=1, relief="solid",
                         bordercolor=fio, lightcolor=fundo, darkcolor=fundo,
                         focuscolor=fundo, anchor="center")
        estilo.map(chave,
                   background=[("pressed", apertado), ("active", sobre), ("disabled", SUPERFICIE)],
                   bordercolor=[("disabled", SUPERFICIE)],
                   lightcolor=[("pressed", apertado), ("active", sobre), ("disabled", SUPERFICIE)],
                   darkcolor=[("pressed", apertado), ("active", sobre), ("disabled", SUPERFICIE)],
                   foreground=[("disabled", APAGADO)])


def _superficies(estilo: ttk.Style) -> None:
    """Variantes de cada botão para cada cor de fundo ('Aviso.apoio.TButton').

    O ttk procura o layout pelo nome sem o primeiro pedaço, então a variante
    herda tudo de 'apoio.TButton' e só troca a cor de trás.
    """
    for prefixo, cor in SUPERFICIES.items():
        if not prefixo:
            continue
        for nome in FAMILIAS:
            for sufixo in TAMANHOS:
                chave = f"{prefixo}{nome}.{sufixo}TButton"
                estilo.configure(chave, background=cor)
                estilo.map(chave, background=[("active", cor), ("pressed", cor)])


# ------------------------------------------------------ cartões e painéis
def _molduras(estilo: ttk.Style) -> None:
    """Quadros de cantos macios: o painel branco da página, o cartão com
    sombra e as faixas coloridas de aviso."""
    def quadro(nome, imagens, borda, padding):
        _elemento(estilo, f"{nome}.moldura", imagens, border=borda, sticky="nsew",
                  padding=padding)
        estilo.layout(f"{nome}.TFrame", [(f"{nome}.moldura", {"sticky": "nsew"})])

    lado = px(64)
    # painel branco da página, sobre a moldura cinza-azulada
    quadro("Painel", [_pilula(lado, lado, PAPEL, None, px(18), externo=MOLDURA)],
           px(22), 0)
    estilo.configure("Painel.TFrame", background=PAPEL)

    # cartão: branco, fio suave, sombra; sob o mouse, fio azul
    sombra = px(5)
    normal = _pilula(lado, lado, PAPEL, LINHA, px(14), externo=PAPEL, sombra=True, margem=sombra)
    sobre = _pilula(lado, lado, PAPEL, AZUL_FIO, px(14), externo=PAPEL, sombra=True, margem=sombra)
    quadro("Cartao", [normal, ("hover", sobre)], px(24), px(6))
    estilo.configure("Cartao.TFrame", background=PAPEL)

    # cartão sem sombra (blocos internos, tabelas)
    quadro("Bloco", [_pilula(lado, lado, PAPEL, LINHA, px(12), externo=PAPEL)], px(16), px(2))
    estilo.configure("Bloco.TFrame", background=PAPEL)

    for nome, cor in (("Aviso", AMBAR_FUNDO), ("Sucesso", VERDE_FUNDO), ("Erro", VINHO_FUNDO),
                      ("Info", AZUL_PALIDO), ("Faixa", FAIXA_CLARA)):
        quadro(nome, [_pilula(lado, lado, cor, None, px(12), externo=PAPEL)], px(16), px(2))
        estilo.configure(f"{nome}.TFrame", background=cor)


def _molduras_retas(estilo: ttk.Style) -> None:
    estilo.configure("Painel.TFrame", background=PAPEL)
    estilo.configure("Cartao.TFrame", background=PAPEL, borderwidth=1, relief="solid",
                     bordercolor=LINHA, lightcolor=PAPEL, darkcolor=PAPEL)
    estilo.configure("Bloco.TFrame", background=PAPEL, borderwidth=1, relief="solid",
                     bordercolor=LINHA, lightcolor=PAPEL, darkcolor=PAPEL)
    for nome, cor in (("Aviso", AMBAR_FUNDO), ("Sucesso", VERDE_FUNDO), ("Erro", VINHO_FUNDO),
                      ("Info", AZUL_PALIDO), ("Faixa", FAIXA_CLARA)):
        estilo.configure(f"{nome}.TFrame", background=cor)


# ------------------------------------------------------- abas internas
def _abas(estilo: ttk.Style) -> None:
    """Abas no desenho do Material: texto plano, a aberta com um traço azul
    embaixo. O desenho do clam deslocava o texto da aba aberta para baixo."""
    from PIL import Image, ImageDraw, ImageTk

    L, A = px(40), px(36)
    traco = max(2, px(3))

    def aba(fundo: str, cor: str, espessura: int):
        img = Image.new("RGBA", (L, A), fundo)
        ImageDraw.Draw(img).rectangle((0, A - espessura, L, A), fill=cor)
        foto = ImageTk.PhotoImage(img, master=_raiz)
        _imagens.append(foto)
        return foto

    imagens = [aba(PAPEL, LINHA, 1), ("selected", aba(PAPEL, AZUL, traco)),
               ("active", aba(FAIXA_CLARA, LINHA, 1))]
    _elemento(estilo, "AI.aba", imagens, border=(2, 2, 2, traco + 1), sticky="nsew")
    estilo.layout("TNotebook.Tab", [("AI.aba", {"sticky": "nsew", "children": [
        ("Notebook.padding", {"sticky": "nsew", "children": [
            ("Notebook.label", {"sticky": ""})]})]})])
    estilo.configure("TNotebook.Tab", padding=pxs(16, 9, 16, 11))


# --------------------------------------------- caixas de marcar e de escolha
def _indicadores(estilo: ttk.Style) -> None:
    """Caixa de marcar e botão de escolha no desenho do Material (o do clam
    é de 1995)."""
    from PIL import Image, ImageDraw, ImageTk

    t = px(18)
    e = 4
    T = t * e

    def desenhar(tipo: str, marcado: bool, cor_borda: str, cor_cheia: str):
        img = Image.new("RGBA", (T, T), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        m = round(T * 0.1)
        w = max(e, round(T * 0.11))
        if tipo == "caixa":
            if marcado:
                d.rounded_rectangle((m, m, T - m, T - m), radius=T * 0.12, fill=cor_cheia)
                pts = [(T * 0.28, T * 0.52), (T * 0.44, T * 0.67), (T * 0.73, T * 0.36)]
                d.line(pts, fill="#ffffff", width=round(T * 0.11), joint="curve")
            else:
                d.rounded_rectangle((m, m, T - m, T - m), radius=T * 0.12, outline=cor_borda,
                                    width=w)
        else:
            if marcado:
                d.ellipse((m, m, T - m, T - m), outline=cor_cheia, width=w)
                c = T * 0.27
                d.ellipse((c, c, T - c, T - c), fill=cor_cheia)
            else:
                d.ellipse((m, m, T - m, T - m), outline=cor_borda, width=w)
        foto = ImageTk.PhotoImage(img.resize((t, t), Image.LANCZOS), master=_raiz)
        _imagens.append(foto)
        return foto

    for tipo, widget in (("caixa", "Checkbutton"), ("bolinha", "Radiobutton")):
        imagens = [desenhar(tipo, False, TINTA_FRACA, AZUL),
                   ("disabled selected", desenhar(tipo, True, APAGADO, APAGADO)),
                   ("disabled", desenhar(tipo, False, LINHA_FORTE, LINHA_FORTE)),
                   ("selected", desenhar(tipo, True, AZUL, AZUL)),
                   ("active", desenhar(tipo, False, TINTA, AZUL))]
        _elemento(estilo, f"AI.{tipo}", imagens, sticky="w", padding=(0, 0, px(8), 0))
        estilo.layout(f"T{widget}", [(f"{widget}.padding", {"sticky": "nsew", "children": [
            (f"AI.{tipo}", {"side": "left", "sticky": ""}),
            (f"{widget}.focus", {"side": "left", "sticky": "w", "children": [
                (f"{widget}.label", {"sticky": "nsew"})]})]})])


# --------------------------------------------------------------- tipografia
def _escolher(familias_existentes: set[str], preferidas: tuple[str, ...], padrao: str) -> str:
    minusculas = {f.lower(): f for f in familias_existentes}
    for f in preferidas:
        if f.lower() in minusculas:
            return minusculas[f.lower()]
    return padrao


def preparar_fontes(raiz: tk.Misc) -> str:
    """Cria as fontes nomeadas com a família disponível. Devolve a família."""
    global _familia_texto
    existentes = set(tkfont.families(raiz))
    padrao = tkfont.nametofont("TkDefaultFont", root=raiz).actual("family")
    texto = _escolher(existentes, _FAMILIAS_TEXTO, padrao)
    mono = _escolher(existentes, _FAMILIAS_MONO, "TkFixedFont")
    # O Windows tem os pesos intermediários como famílias à parte.
    seminegrito = "Segoe UI Semibold" if "Segoe UI Semibold" in existentes else None
    leve = "Segoe UI Light" if "Segoe UI Light" in existentes else None
    if seminegrito is None and texto == "Open Sans" and "Open Sans Semibold" in existentes:
        seminegrito = "Open Sans Semibold"
    _familia_texto = texto

    def criar(nome, familia, tamanho, peso="normal"):
        # O tkinter APAGA a fonte nomeada quando o objeto Font é coletado:
        # sem guardar a referência, os widgets voltavam à fonte padrão.
        if nome in _fontes:
            _fontes[nome].configure(family=familia, size=tamanho, weight=peso)
        else:
            _fontes[nome] = tkfont.Font(root=raiz, name=nome, family=familia, size=tamanho,
                                        weight=peso)

    def forte(tamanho, nome):
        if seminegrito:
            criar(nome, seminegrito, tamanho)
        else:
            criar(nome, texto, tamanho, "bold")

    criar(FONTE, texto, 10)
    criar(FONTE_NEGRITO, texto, 10, "bold")
    criar(FONTE_NOTA, texto, 9)
    criar(FONTE_NOTA_NEGRITO, texto, 9, "bold")
    criar(FONTE_BOTAO, texto, 10)
    forte(10, FONTE_BOTAO_GRANDE)
    forte(12, FONTE_SECAO)
    forte(13, FONTE_CARTAO)
    criar(FONTE_PAGINA, texto, 19)
    criar(FONTE_SAUDACAO, leve or texto, 24)
    criar(FONTE_RELOGIO, leve or texto, 26)
    criar(FONTE_MONO, mono, 9)
    criar(FONTE_CODIGO, mono, 20, "bold")
    criar(FONTE_TRANSCRICAO, texto, 11)
    criar(FONTE_TRANSCRICAO_NEGRITO, texto, 11, "bold")
    forte(11, FONTE_MARCA)

    # As fontes padrão do Tk (diálogos, listas dos combos, menus) também.
    for nome, tamanho in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10),
                          ("TkHeadingFont", 9), ("TkCaptionFont", 10), ("TkTooltipFont", 9)):
        try:
            tkfont.nametofont(nome, root=raiz).configure(family=texto, size=tamanho)
        except tk.TclError:
            pass
    raiz.option_add("*TCombobox*Listbox.font", FONTE)
    raiz.option_add("*TCombobox*Listbox.selectBackground", AZUL_PALIDO)
    raiz.option_add("*TCombobox*Listbox.selectForeground", TINTA)
    raiz.option_add("*Menu.font", FONTE)
    return texto


def familia_texto() -> str:
    return _familia_texto


# --------------------------------------------------------------------- tema
def _novo_interpretador(raiz: tk.Misc) -> None:
    """Imagens e fontes pertencem a um interpretador Tcl. Uma segunda janela
    Tk() no mesmo processo (os testes fazem isso) precisa das suas - e toda
    imagem é criada com master explícito: sem ele, o Tk usa a "janela padrão",
    que pode ser outra (e a imagem "não existe" na janela nova)."""
    global _interpretador, _raiz
    _raiz = raiz
    if _interpretador is not raiz.tk:
        _interpretador = raiz.tk
        _imagens.clear()
        _cache_imagens.clear()
        _fontes.clear()
        for limpar in _ao_trocar_interpretador:
            limpar()


_interpretador = None
_raiz: tk.Misc | None = None
_ao_trocar_interpretador: list = []


def aplicar(raiz: tk.Tk) -> ttk.Style:
    """Prepara escala, fontes e tema. Pode ser chamada mais de uma vez."""
    _novo_interpretador(raiz)
    preparar_escala(raiz)
    preparar_fontes(raiz)
    estilo = ttk.Style(raiz)
    try:
        estilo.theme_use("clam")        # o único dos temas padrão que aceita cor
    except tk.TclError:
        pass

    raiz.configure(background=MOLDURA)
    estilo.configure(".", background=PAPEL, foreground=TINTA, font=FONTE,
                     selectbackground=AZUL_PALIDO, selectforeground=TINTA,
                     troughcolor=SUPERFICIE, focuscolor=AZUL)
    estilo.configure("TFrame", background=PAPEL)
    estilo.configure("Moldura.TFrame", background=MOLDURA)
    estilo.configure("TLabel", background=PAPEL, foreground=TINTA)
    estilo.configure("Fraco.TLabel", foreground=TINTA_FRACA)
    estilo.configure("Nota.TLabel", foreground=TINTA_FRACA, font=FONTE_NOTA)
    estilo.configure("Secao.TLabel", font=FONTE_SECAO)
    estilo.configure("Pagina.TLabel", font=FONTE_PAGINA)
    estilo.configure("Erro.TLabel", foreground=VINHO)
    estilo.configure("Ok.TLabel", foreground=VERDE)

    estilo.configure("TLabelframe", background=PAPEL, borderwidth=1, relief="solid",
                     bordercolor=LINHA, lightcolor=PAPEL, darkcolor=PAPEL)
    estilo.configure("TLabelframe.Label", background=PAPEL, foreground=TINTA, font=FONTE_SECAO)

    for widget in ("TCheckbutton", "TRadiobutton"):
        estilo.configure(widget, background=PAPEL, foreground=TINTA, padding=(0, px(3)))
        estilo.map(widget, background=[("active", PAPEL)],
                   foreground=[("disabled", APAGADO)],
                   indicatorcolor=[("selected", AZUL), ("!selected", PAPEL)])

    # --- abas internas (Configurações): texto plano, a aberta em azul com
    # um traço embaixo; o clam desenha caixa em volta se o fio não for branco
    estilo.configure("TNotebook", background=PAPEL, borderwidth=0, tabmargins=(0, 0, 0, 0),
                     bordercolor=PAPEL, lightcolor=PAPEL, darkcolor=PAPEL)
    estilo.configure("TNotebook.Tab", padding=pxs(14, 8), font=FONTE, borderwidth=0,
                     background=PAPEL, bordercolor=PAPEL, lightcolor=PAPEL, darkcolor=PAPEL,
                     focuscolor=PAPEL, foreground=TINTA_FRACA)
    estilo.map("TNotebook.Tab",
               background=[("selected", PAPEL), ("active", FAIXA_CLARA), ("!selected", PAPEL)],
               foreground=[("selected", AZUL), ("!selected", TINTA_FRACA)],
               bordercolor=[("selected", PAPEL), ("!selected", PAPEL)],
               lightcolor=[("selected", PAPEL)], darkcolor=[("selected", PAPEL)],
               focuscolor=[("selected", PAPEL)],
               expand=[("selected", (0, 0, 0, 0))])

    # --- tabelas
    estilo.configure("Treeview", background=PAPEL, fieldbackground=PAPEL, foreground=TINTA,
                     rowheight=px(30), borderwidth=0, relief="flat",
                     bordercolor=LINHA, lightcolor=PAPEL, darkcolor=PAPEL, font=FONTE)
    estilo.configure("Treeview.Heading", background=FAIXA_CLARA, foreground=TINTA_FRACA,
                     font=FONTE_NOTA_NEGRITO, relief="flat", borderwidth=0,
                     padding=pxs(8, 7), bordercolor=LINHA, lightcolor=FAIXA_CLARA,
                     darkcolor=FAIXA_CLARA)
    estilo.map("Treeview.Heading", background=[("active", SUPERFICIE)])
    estilo.map("Treeview", background=[("selected", AZUL_PALIDO)],
               foreground=[("selected", TINTA)])
    # sem o contorno pontilhado do item em foco
    estilo.layout("Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
        ("Treeitem.indicator", {"side": "left", "sticky": ""}),
        ("Treeitem.image", {"side": "left", "sticky": ""}),
        ("Treeitem.text", {"side": "left", "sticky": ""})]})])

    # --- campos
    for campo in ("TEntry", "TCombobox", "TSpinbox"):
        estilo.configure(campo, fieldbackground=PAPEL, background=PAPEL, foreground=TINTA,
                         padding=pxs(8, 6), borderwidth=1, relief="solid", bordercolor=LINHA_FORTE,
                         lightcolor=PAPEL, darkcolor=PAPEL, arrowcolor=TINTA_FRACA,
                         insertcolor=TINTA, selectbackground=AZUL_PALIDO, selectforeground=TINTA)
        estilo.map(campo, bordercolor=[("focus", AZUL), ("hover", TINTA_FRACA)],
                   lightcolor=[("focus", AZUL)], darkcolor=[("focus", AZUL)],
                   fieldbackground=[("disabled", FAIXA_CLARA), ("readonly", PAPEL)],
                   foreground=[("disabled", APAGADO)])
    estilo.configure("Invalido.TEntry", bordercolor=VINHO)
    estilo.map("Invalido.TEntry", bordercolor=[("focus", VINHO), ("hover", VINHO)],
               lightcolor=[("focus", VINHO)], darkcolor=[("focus", VINHO)])
    estilo.configure("Codigo.TEntry", padding=pxs(10, 8))
    estilo.map("TCombobox", fieldbackground=[("readonly", PAPEL)],
               foreground=[("readonly", TINTA)], selectbackground=[("readonly", PAPEL)],
               selectforeground=[("readonly", TINTA)])

    # --- barras de rolagem discretas (sem setas)
    for orient in ("Vertical", "Horizontal"):
        barra = f"{orient}.TScrollbar"
        estilo.configure(barra, background=LINHA, troughcolor=PAPEL, bordercolor=PAPEL,
                         lightcolor=LINHA, darkcolor=LINHA, arrowcolor=TINTA_FRACA,
                         relief="flat", borderwidth=0, gripcount=0, arrowsize=px(9))
        estilo.map(barra, background=[("active", LINHA_FORTE), ("pressed", APAGADO)],
                   lightcolor=[("active", LINHA_FORTE)], darkcolor=[("active", LINHA_FORTE)])
        estilo.layout(barra, [(f"{orient}.Scrollbar.trough", {"sticky": "nsew", "children": [
            (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nsew"})]})])

    # --- barras de progresso finas, azuis
    # no clam, a espessura da barra é o 'arrowsize'
    estilo.configure("Horizontal.TProgressbar", troughcolor=SUPERFICIE, background=AZUL,
                     bordercolor=SUPERFICIE, lightcolor=AZUL, darkcolor=AZUL,
                     arrowsize=px(6), borderwidth=0)
    estilo.configure("Verde.Horizontal.TProgressbar", background=VERDE, lightcolor=VERDE,
                     darkcolor=VERDE)
    estilo.configure("TSeparator", background=LINHA)
    estilo.configure("TPanedwindow", background=PAPEL)
    estilo.configure("Sash", sashthickness=px(6), background=PAPEL, bordercolor=PAPEL,
                     lightcolor=PAPEL, darkcolor=PAPEL, gripcount=0)

    # ---------------------------------------------------- imagens (Pillow)
    try:
        if not _tem_pillow():
            raise ImportError("Pillow ausente")
        for nome, (fundo, sobre, apertado, contorno, letra) in FAMILIAS.items():
            _familia_arredondada(estilo, nome, fundo, sobre, apertado, contorno, letra)
        _molduras(estilo)
        _indicadores(estilo)
        _abas(estilo)
        estilo._arredondado = True  # type: ignore[attr-defined]
    except Exception as erro:
        # Sem Pillow (ou um Pillow que não fala com o Tk): o tema reto, com
        # as mesmas cores. O programa abre igual.
        log.debug("tema arredondado indisponível (%s); usando o reto", erro)
        for nome, (fundo, sobre, apertado, contorno, letra) in FAMILIAS.items():
            _familia_reta(estilo, nome, fundo, sobre, apertado, contorno, letra)
        _molduras_retas(estilo)
        estilo._arredondado = False  # type: ignore[attr-defined]
        return estilo
    # Só no tema arredondado: no reto, o 'background' É a cor do botão.
    _superficies(estilo)
    return estilo


def arredondado(estilo: ttk.Style) -> bool:
    return bool(getattr(estilo, "_arredondado", False))


# --------------------------------------------------------------- atalhos
def botao(pai, texto: str, comando=None, familia: str = "apoio", grande: bool = False,
          pequeno: bool = False, superficie: str = "", **extra) -> ttk.Button:
    """Um botão com o peso da família.

    'superficie' é a cor de trás quando não é o branco da página: "Moldura",
    "Aviso", "Sucesso", "Erro", "Info" ou "Faixa".
    """
    familia = SINONIMOS.get(familia, familia)
    familia = familia if familia in FAMILIAS else "apoio"
    tamanho = "Grande." if grande else ("Pequeno." if pequeno else "")
    prefixo = f"{superficie}." if superficie and f"{superficie}." in SUPERFICIES else ""
    estilo = f"{prefixo}{familia}.{tamanho}TButton"
    extra.setdefault("takefocus", True)
    return ttk.Button(pai, text=texto, command=comando, style=estilo, **extra)


def fileira(pai, *botoes_def, superficie: str = "", espaco: int = ESPACO, lado: str = "left",
            **pack) -> ttk.Frame:
    """Uma fileira de botões: cada item é (texto, comando, família)."""
    cor = SUPERFICIES.get(f"{superficie}.", PAPEL) if superficie else PAPEL
    quadro = tk.Frame(pai, background=cor)
    feitos = []
    for definicao in botoes_def:
        if definicao is None:
            continue
        texto, comando, *resto = definicao
        familia = resto[0] if resto else "apoio"
        b = botao(quadro, texto, comando, familia, superficie=superficie)
        # o espaço fica do lado de quem já está na fileira
        vao = px(espaco) if feitos else 0
        b.pack(side=lado, padx=(vao, 0) if lado == "left" else (0, vao))
        feitos.append(b)
    quadro.botoes = feitos  # type: ignore[attr-defined]
    return quadro


def titulo(pai, texto: str, **extra) -> ttk.Label:
    return ttk.Label(pai, text=texto, font=FONTE_SECAO, foreground=TINTA, **extra)


def nota(pai, texto: str, **extra) -> ttk.Label:
    """Texto de apoio, em tom discreto (quebra pela largura do pai)."""
    extra.setdefault("justify", "left")
    rotulo = ttk.Label(pai, text=texto, foreground=TINTA_FRACA, font=FONTE_NOTA, **extra)
    acompanhar_largura(rotulo)
    return rotulo


def acompanhar_largura(rotulo, folga: int = 4) -> None:
    """Faz o rótulo quebrar linha na largura que de fato tem.

    O wraplength fixo da base (820 px) cortava o texto em notebook de
    1366x768 e deixava linhas curtas em monitor grande.
    """
    def ajustar(evento):
        if evento.width <= 1:          # ainda não desenhado: nada a medir
            return
        largura = max(px(80), evento.width - px(folga))
        if abs(int(str(rotulo.cget("wraplength") or 0)) - largura) > 2:
            rotulo.configure(wraplength=largura)
    rotulo.bind("<Configure>", ajustar, add="+")
