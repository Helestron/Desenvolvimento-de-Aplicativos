"""Gera os ícones do Assessor Integrado (rode de novo só se mudar o desenho).

    python ferramentas/gerar_icones.py

Grava em app/interface/recursos/:

    assessor.ico ............ ícone do programa, de 16 a 256 px (atalhos,
                              barra de tarefas, barra de título)
    assessor.png ............ o mesmo, 256 px (iconphoto do Tk)
    cartao-*.png ............ os três cartões da tela inicial (192 px)
    nav-*.png, nav-*-ativo .. a barra lateral, cinza e azul (80 px)
    bloco-*.png ............. os blocos da página Compartilhar (96 px)
    sinal-*.png ............. aviso, ok, erro e informação (64 px)

Os arquivos gerados são VERSIONADOS: o programa não depende deste script
para abrir. Ele existe para o desenho ser reproduzível e corrigível.

Todo desenho é feito numa grade de 24 unidades (a dos ícones do Material
Design), em escala 8x, e reduzido com LANCZOS: é o que dá borda macia sem
depender de nenhum arquivo de fonte - os traços são geometria pura, e o
resultado é idêntico no Windows, no Linux e no CI.

Os ícones são de uma cor só, em traço (como os do Chrome), e nenhum usa
marca de terceiros: um produto que atende vários tribunais e duas empresas
de IA não deve vestir o brasão de um nem o logotipo de outra.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "app" / "interface" / "recursos"

# Mesma paleta de app/interface/estilo.py (copiada para o script não
# importar o Tk).
AZUL = (26, 115, 232)
AZUL_PALIDO = (232, 240, 254)
AZUL_ESCURO = (23, 78, 166)
TINTA_FRACA = (95, 99, 104)
AMBAR = (249, 171, 0)
AMBAR_FUNDO = (254, 247, 224)
VERDE = (24, 128, 56)
VINHO = (197, 34, 31)
BRANCO = (255, 255, 255)

SS = 8          # supersampling


class Tela:
    """Uma máscara (L) em escala SS, com coordenadas da grade de 24."""

    def __init__(self, tamanho: int, grade: float = 24.0, margem: float = 0.0):
        self.tamanho = tamanho
        self.lado = tamanho * SS
        self.mascara = Image.new("L", (self.lado, self.lado), 0)
        self.d = ImageDraw.Draw(self.mascara)
        # 'margem' encolhe o desenho para dentro (fração do lado): o glifo
        # dentro do círculo do cartão ocupa só o miolo.
        self.escala = self.lado * (1 - 2 * margem) / grade
        self.desvio = self.lado * margem

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (self.desvio + x * self.escala, self.desvio + y * self.escala)

    def w(self, largura: float) -> int:
        return max(1, round(largura * self.escala))

    # ------------------------------------------------------------- traços
    def linha(self, pontos, largura=2.0, fechar=False):
        pts = [self.p(*q) for q in pontos]
        if fechar:
            pts.append(pts[0])
        lw = self.w(largura)
        self.d.line(pts, fill=255, width=lw, joint="curve")
        # pontas redondas: o Pillow faz ponta reta; um disco em cada
        # extremidade dá o acabamento dos ícones do Material.
        r = lw / 2
        for x, y in (pts[0], pts[-1]):
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=255)

    def caixa(self, x0, y0, x1, y1, raio, largura=2.0, cheio=False):
        a, b = self.p(x0, y0), self.p(x1, y1)
        if cheio:
            self.d.rounded_rectangle((*a, *b), radius=raio * self.escala, fill=255)
        else:
            self.d.rounded_rectangle((*a, *b), radius=raio * self.escala, outline=255,
                                     width=self.w(largura))

    def circulo(self, cx, cy, r, largura=2.0, cheio=False):
        a, b = self.p(cx - r, cy - r), self.p(cx + r, cy + r)
        if cheio:
            self.d.ellipse((*a, *b), fill=255)
        else:
            self.d.ellipse((*a, *b), outline=255, width=self.w(largura))

    def arco(self, cx, cy, r, inicio, fim, largura=2.0):
        """Arco com o traço CENTRADO no raio e pontas redondas.

        O Pillow desenha a espessura do arco para dentro da caixa; a caixa
        cresce meia espessura para o traço ficar sobre o raio pedido.
        Ângulos em graus, 0 = três horas, crescendo no sentido horário.
        """
        lw = self.w(largura)
        cxp, cyp = self.p(cx, cy)
        rp = r * self.escala
        caixa = (cxp - rp - lw / 2, cyp - rp - lw / 2, cxp + rp + lw / 2, cyp + rp + lw / 2)
        self.d.arc(caixa, inicio, fim, fill=255, width=lw)
        for ang in (inicio, fim):
            x = cxp + rp * math.cos(math.radians(ang))
            y = cyp + rp * math.sin(math.radians(ang))
            self.d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=255)

    def ponto_do_arco(self, cx, cy, r, ang) -> tuple[float, float]:
        """O ponto da grade sobre o arco (para emendar uma linha nele)."""
        return (cx + r * math.cos(math.radians(ang)), cy + r * math.sin(math.radians(ang)))

    def poligono(self, pontos):
        self.d.polygon([self.p(*q) for q in pontos], fill=255)

    def apagar_circulo(self, cx, cy, r):
        a, b = self.p(cx - r, cy - r), self.p(cx + r, cy + r)
        self.d.ellipse((*a, *b), fill=0)

    def final(self) -> Image.Image:
        return self.mascara.resize((self.tamanho, self.tamanho), Image.LANCZOS)


def estrela(t: Tela, cx: float, cy: float, r: float, curva: float = 0.62) -> None:
    """Brilho de quatro pontas (o sinal universal de 'inteligência
    artificial'), com os lados côncavos."""
    pts = []
    passos = 120
    for i in range(passos):
        ang = 2 * math.pi * i / passos
        # superelipse com expoente < 1 vira uma estrela de lados curvos
        c, s = math.cos(ang), math.sin(ang)
        e = curva
        x = math.copysign(abs(c) ** (2 / e) if c else 0, c)
        y = math.copysign(abs(s) ** (2 / e) if s else 0, s)
        pts.append((cx + r * x, cy + r * y))
    t.poligono(pts)


# --------------------------------------------------------------- glifos
def glifo_baixar(t: Tela) -> None:
    """Folha de autos com a orelha dobrada e uma seta para baixo."""
    t.linha([(14, 3), (6.5, 3), (5, 4.5), (5, 19.5), (6.5, 21), (17.5, 21), (19, 19.5),
             (19, 8), (14, 3)], largura=1.9)
    t.linha([(14, 3.4), (14, 8), (18.6, 8)], largura=1.9)
    t.linha([(12, 10.5), (12, 17.2)], largura=1.9)
    t.linha([(8.8, 14.2), (12, 17.4), (15.2, 14.2)], largura=1.9)


def glifo_microfone(t: Tela) -> None:
    t.caixa(8.8, 2.5, 15.2, 14.2, 3.2, largura=1.9)
    t.arco(12, 10.5, 6.6, 0, 180, largura=1.9)
    t.linha([(12, 17.3), (12, 21)], largura=1.9)
    t.linha([(8.6, 21), (15.4, 21)], largura=1.9)


def glifo_ia(t: Tela) -> None:
    estrela(t, 10.0, 13.6, 8.6)
    estrela(t, 18.6, 5.2, 3.9)


def glifo_inicio(t: Tela) -> None:
    t.linha([(3.2, 11.2), (12, 3.6), (20.8, 11.2)], largura=1.9)
    t.linha([(5.6, 9.6), (5.6, 20.4), (18.4, 20.4), (18.4, 9.6)], largura=1.9)
    t.linha([(10, 20.2), (10, 14.6), (14, 14.6), (14, 20.2)], largura=1.9)


def glifo_engrenagem(t: Tela) -> None:
    cx = cy = 12
    t.circulo(cx, cy, 6.6, cheio=True)
    for i in range(8):
        ang = math.radians(i * 45)
        c, s = math.cos(ang), math.sin(ang)
        # dente: trapézio do raio 5,8 ao 9,6
        r0, r1, l0, l1 = 5.8, 9.7, 1.9, 1.45
        px, py = -s, c
        pts = [(cx + c * r0 + px * l0, cy + s * r0 + py * l0),
               (cx + c * r1 + px * l1, cy + s * r1 + py * l1),
               (cx + c * r1 - px * l1, cy + s * r1 - py * l1),
               (cx + c * r0 - px * l0, cy + s * r0 - py * l0)]
        t.poligono(pts)
    t.apagar_circulo(cx, cy, 2.9)


def glifo_ajuda(t: Tela) -> None:
    t.circulo(12, 12, 9.2, largura=1.9)
    t.arco(12, 9.5, 2.9, 180, 405, largura=1.9)
    t.linha([t.ponto_do_arco(12, 9.5, 2.9, 45), (12, 13.0), (12, 13.9)], largura=1.9)
    t.circulo(12, 17.1, 1.25, cheio=True)


def glifo_terminal(t: Tela) -> None:
    t.caixa(2.8, 4.2, 21.2, 19.8, 2.4, largura=1.9)
    t.linha([(7, 9.4), (10, 12), (7, 14.6)], largura=1.9)
    t.linha([(12.4, 15), (16.8, 15)], largura=1.9)


def glifo_pasta(t: Tela) -> None:
    t.linha([(3, 18), (3, 6.6), (4.4, 5.2), (9.2, 5.2), (11.2, 7.4), (19.6, 7.4),
             (21, 8.8), (21, 18), (19.6, 19.4), (4.4, 19.4), (3, 18)], largura=1.9)
    estrela(t, 12, 13.4, 4.0)


def glifo_conversa(t: Tela) -> None:
    t.linha([(5, 4.2), (19, 4.2), (20.8, 6), (20.8, 14.2), (19, 16), (10.4, 16),
             (6.4, 19.8), (6.4, 16), (5, 16), (3.2, 14.2), (3.2, 6), (5, 4.2)], largura=1.9)
    t.linha([(7.6, 8.6), (16.4, 8.6)], largura=1.7)
    t.linha([(7.6, 11.8), (13.4, 11.8)], largura=1.7)


def glifo_nuvem(t: Tela) -> None:
    """Contorno da união de três círculos e uma base: as formas são
    desenhadas cheias meia espessura MAIORES e depois apagadas meia
    espessura MENORES - sobra só o contorno da união, sem filtro de imagem
    (que, em escala 8x, levava minutos)."""
    meia = 0.95
    formas = [(8.6, 13.4, 4.6), (13.2, 10.4, 5.9), (17.6, 14.0, 3.9)]
    base = (5.0, 13.4, 20.4, 17.9)
    for cor, delta in ((255, meia), (0, -meia)):
        for cx, cy, r in formas:
            a, b = t.p(cx - r - delta, cy - r - delta), t.p(cx + r + delta, cy + r + delta)
            t.d.ellipse((*a, *b), fill=cor)
        x0, y0, x1, y1 = base
        raio = (y1 - y0) / 2 + delta
        a, b = t.p(x0 - delta, y0 - delta), t.p(x1 + delta, y1 + delta)
        t.d.rounded_rectangle((*a, *b), radius=raio * t.escala, fill=cor)


def glifo_aviso(t: Tela) -> None:
    t.poligono([(12, 2.6), (22.4, 20.6), (1.6, 20.6)])
    t.d.line([t.p(12, 9), t.p(12, 14.2)], fill=0, width=t.w(2.2))
    for y in (9, 14.2):
        x, yy = t.p(12, y)
        r = t.w(2.2) / 2
        t.d.ellipse((x - r, yy - r, x + r, yy + r), fill=0)
    t.apagar_circulo(12, 17.6, 1.3)


def glifo_ok(t: Tela) -> None:
    t.circulo(12, 12, 10, cheio=True)
    lw = t.w(2.4)
    pts = [t.p(7.4, 12.4), t.p(10.6, 15.6), t.p(16.8, 9.2)]
    t.d.line(pts, fill=0, width=lw, joint="curve")
    for x, y in (pts[0], pts[-1]):
        t.d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=0)


def glifo_erro(t: Tela) -> None:
    t.circulo(12, 12, 10, cheio=True)
    lw = t.w(2.4)
    for a, b in (((8.4, 8.4), (15.6, 15.6)), ((15.6, 8.4), (8.4, 15.6))):
        pa, pb = t.p(*a), t.p(*b)
        t.d.line([pa, pb], fill=0, width=lw)
        for x, y in (pa, pb):
            t.d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=0)


def glifo_info(t: Tela) -> None:
    t.circulo(12, 12, 10, cheio=True)
    lw = t.w(2.4)
    a, b = t.p(12, 10.8), t.p(12, 17)
    t.d.line([a, b], fill=0, width=lw)
    for x, y in (a, b):
        t.d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=0)
    t.apagar_circulo(12, 7.2, 1.45)


# ------------------------------------------------------------ composição
def pintar(mascara: Image.Image, cor) -> Image.Image:
    """A máscara vira a transparência de uma chapa da cor pedida."""
    cheio = Image.new("RGBA", mascara.size, (*cor, 255))
    cheio.putalpha(mascara)
    return cheio


def glifo(desenho, tamanho: int, cor, margem: float = 0.0) -> Image.Image:
    t = Tela(tamanho, margem=margem)
    desenho(t)
    return pintar(t.final(), cor)


def em_circulo(desenho, tamanho: int, fundo, cor, margem: float = 0.25) -> Image.Image:
    """Glifo dentro de um disco de cor clara (os cartões e os blocos)."""
    lado = tamanho * SS
    disco = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(disco).ellipse((0, 0, lado - 1, lado - 1), fill=255)
    disco = disco.resize((tamanho, tamanho), Image.LANCZOS)
    base = Image.new("RGBA", (tamanho, tamanho), (*fundo, 0))
    cheio = Image.new("RGBA", (tamanho, tamanho), (*fundo, 255))
    base.paste(cheio, (0, 0), disco)
    base.alpha_composite(glifo(desenho, tamanho, cor, margem=margem))
    return base


def icone_programa(tamanho: int) -> Image.Image:
    """Quadrado azul de cantos macios, folha branca e um brilho âmbar.

    Nos tamanhos pequenos (até 24 px) o brilho e as linhas de texto somem:
    no 16 px eles viram borrão, e a folha sozinha se lê melhor.
    """
    lado = tamanho * SS
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = lado / 24
    d.rounded_rectangle((0.6 * u, 0.6 * u, 23.4 * u, 23.4 * u), radius=5.4 * u, fill=(*AZUL, 255))
    pequeno = tamanho <= 24
    # a folha, com a orelha dobrada
    x0, y0, x1, y1, orelha = 6.2, 3.8, 17.4, 20.2, 3.6
    if pequeno:
        x0, y0, x1, y1, orelha = 5.6, 3.4, 18.4, 20.6, 4.2
    d.polygon([(x0 * u, y0 * u), ((x1 - orelha) * u, y0 * u), (x1 * u, (y0 + orelha) * u),
               (x1 * u, y1 * u), (x0 * u, y1 * u)], fill=(*BRANCO, 255))
    d.polygon([((x1 - orelha) * u, y0 * u), ((x1 - orelha) * u, (y0 + orelha) * u),
               (x1 * u, (y0 + orelha) * u)], fill=(210, 227, 252, 255))
    if not pequeno:
        for i, fim in enumerate((14.6, 14.6, 11.6)):
            y = (10.4 + i * 2.7) * u
            d.rounded_rectangle((8.4 * u, y, fim * u, y + 1.15 * u), radius=0.55 * u,
                                fill=(*AZUL, 255))
        # o brilho, sobre o canto inferior direito da folha, com um aro
        # azul (a mesma estrela, maior) que o separa do branco da folha
        for raio, cor in ((8.4, AZUL), (6.4, AMBAR)):
            t = Tela(tamanho)
            estrela(t, 17.4, 17.2, raio)
            img.paste(Image.new("RGBA", (lado, lado), (*cor, 255)), (0, 0), t.mascara)
    return img.resize((tamanho, tamanho), Image.LANCZOS)


def gerar(destino: Path = DESTINO) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    feitos: list[Path] = []

    def salvar(img: Image.Image, nome: str) -> None:
        caminho = destino / nome
        img.save(caminho, optimize=True)
        feitos.append(caminho)

    # --- o ícone do programa
    tamanhos = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imagens = [icone_programa(t) for t in tamanhos]
    grande = imagens[-1]
    ico = destino / "assessor.ico"
    grande.save(ico, format="ICO", sizes=[(t, t) for t in tamanhos],
                append_images=imagens[:-1])
    feitos.append(ico)
    salvar(grande, "assessor.png")
    salvar(imagens[tamanhos.index(64)], "assessor-64.png")

    # --- os cartões da tela inicial: glifo azul num disco azul-pálido
    for nome, desenho in (("baixar", glifo_baixar), ("transcrever", glifo_microfone),
                          ("compartilhar", glifo_ia)):
        salvar(em_circulo(desenho, 192, AZUL_PALIDO, AZUL, margem=0.24), f"cartao-{nome}.png")

    # --- a barra lateral: cinza (normal) e azul (página aberta)
    for nome, desenho in (("inicio", glifo_inicio), ("baixar", glifo_baixar),
                          ("transcrever", glifo_microfone), ("compartilhar", glifo_ia),
                          ("config", glifo_engrenagem), ("ajuda", glifo_ajuda)):
        salvar(glifo(desenho, 80, TINTA_FRACA), f"nav-{nome}.png")
        salvar(glifo(desenho, 80, AZUL_ESCURO), f"nav-{nome}-ativo.png")

    # --- os blocos da página Compartilhar
    for nome, desenho in (("terminal", glifo_terminal), ("pasta", glifo_pasta),
                          ("conversa", glifo_conversa), ("nuvem", glifo_nuvem)):
        salvar(em_circulo(desenho, 96, AZUL_PALIDO, AZUL, margem=0.25), f"bloco-{nome}.png")

    # --- sinais (avisos e estados)
    salvar(glifo(glifo_aviso, 64, AMBAR), "sinal-aviso.png")
    salvar(glifo(glifo_ok, 64, VERDE), "sinal-ok.png")
    salvar(glifo(glifo_erro, 64, VINHO), "sinal-erro.png")
    salvar(glifo(glifo_info, 64, AZUL), "sinal-info.png")
    return feitos


if __name__ == "__main__":
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else DESTINO
    for p in gerar(pasta):
        print(p.relative_to(RAIZ) if p.is_relative_to(RAIZ) else p)
