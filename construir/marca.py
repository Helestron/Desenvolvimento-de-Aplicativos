"""Gera a marca do Helestron: o ícone "H" e as imagens do instalador.

    python construir/marca.py              grava tudo nas pastas do pacote
    python construir/marca.py --previa DIR também grava folhas de conferência

Arquivos gerados (VERSIONADOS: o programa e a construção usam os do
repositório; este script existe para o desenho ser reproduzível e
corrigível):

    helestron/recursos/helestron.ico ............. 16, 20, 24, 32, 40, 48, 64,
                                                    128 e 256 px (atalhos, barra
                                                    de tarefas, Helestron.exe)
    helestron/recursos/helestron.png ............. 512 px
    helestron/recursos/helestron-64.png .......... 64 px
    helestron/recursos/instalador-boas-vindas.bmp  164 x 314 (assistente, 1ª e
                                                    última páginas)
    helestron/recursos/instalador-cabecalho.bmp .. 150 x 57 (cabeçalho das demais)
    helestron/web/img/marca/helestron.svg ........ o mesmo desenho, vetorial
    helestron/web/img/marca/helestron-64.png ..... ícone da aba e reserva do SVG

O desenho: "squircle" do iOS (superelipse), navy em gradiente com reflexo
de vidro e borda interna clara, uma placa cinza translúcida (vidro fosco que
deixa ver, desfocado, o brilho azul de trás) e um "H" geométrico em
branco→cinza-claro, com sombra suave. Cantos transparentes.

Por que cada tamanho tem desenho próprio, e não uma redução do de 256 px:
reduzido, o reflexo e a borda viram borrão e o H perde contraste. De 16 a
24 px o desenho é simplificado (sem reflexo nem placa, H mais grosso) e o H
cai em pixels inteiros; de 32 a 64 px a placa e o reflexo ficam, mas o H
também é alinhado à grade de pixels - é o que deixa as bordas nítidas na
barra de tarefas. Tudo é desenhado em escala maior e reduzido (LANCZOS),
só com o Pillow: nada de arquivo de fonte, resultado igual no Windows, no
Linux e no CI.

O .ico é gravado à mão (BMP de 32 bits até 128 px e PNG no de 256 px, o
formato do Visual Studio): o salvador do Pillow grava PNG em todos os
tamanhos, que o compilador de recursos e alguns pontos do Windows antigos
não leem.
"""

from __future__ import annotations

import argparse
import io
import math
import struct
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

RAIZ = Path(__file__).resolve().parents[1]
RECURSOS = RAIZ / "helestron" / "recursos"
WEB_MARCA = RAIZ / "helestron" / "web" / "img" / "marca"

TAMANHOS_ICO = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# Paleta (a mesma dos tokens da interface, docs/ESPECIFICACAO.md, seção 7.1).
NAVY_900 = (11, 26, 51)        # #0B1A33
NAVY_800 = (18, 40, 74)        # #12284A
NAVY_700 = (27, 53, 96)        # #1B3560
AZUL = (10, 102, 232)          # #0A66E8
AZUL_CLARO = (76, 141, 255)    # #4C8DFF
AZUL_GELO = (232, 241, 255)    # #E8F1FF
CINZA_H = (197, 205, 216)      # #C5CDD8 (base do H)
CINZA_PLACA = (161, 167, 179)  # #A1A7B3
BRANCO = (255, 255, 255)
SOMBRA = (4, 10, 22)

# Expoente da superelipse: 5 é o desenho do ícone do iOS ("squircle").
EXPOENTE = 5.0


# ================================================================ geometria
class Desenho:
    """A geometria do ícone, em unidades do quadrado [0, 1].

    Uma instância por tamanho: 'simples' liga o desenho de 16-24 px, e até
    64 px o H é alinhado aos pixels inteiros do tamanho final.
    """

    def __init__(self, tamanho: int):
        self.tamanho = tamanho
        self.simples = tamanho <= 24
        # Margem do squircle: no grande, o respiro dos ícones do Windows 11;
        # no pequeno, ocupa quase tudo (cada pixel conta).
        if tamanho <= 16:
            self.margem = 0.0
        elif tamanho <= 24:
            self.margem = 0.5 / tamanho
        elif tamanho <= 64:
            self.margem = 1.0 / tamanho
        else:
            self.margem = 0.035
        # A placa de vidro (um quadrado de cantos contínuos, centrado).
        self.placa_lado = 0.60
        self.placa_n = 4.2
        # O H: caixa, espessura das hastes e da barra.
        if self.simples:
            self.h_largura, self.h_altura = 0.625, 0.625
            self.h_haste, self.h_barra = 0.1875, 0.135
        elif tamanho <= 64:
            # 32-64 px: H maior dentro de uma placa maior (a placa estreita
            # e o H pequeno somem na barra de tarefas)
            self.h_largura, self.h_altura = 0.47, 0.47
            self.h_haste, self.h_barra = 0.135, 0.11
            self.placa_lado = 0.70
        else:
            self.h_largura, self.h_altura = 0.40, 0.42
            self.h_haste, self.h_barra = 0.118, 0.10
        self.h_centro_y = 0.50

    # ------------------------------------------------------------- o H
    def retangulos_h(self) -> list[tuple[float, float, float, float]]:
        """As três peças do H (haste esq., haste dir., barra), em unidades.

        Nos tamanhos até 64 px as bordas caem em pixels inteiros: largura das
        hastes e do vão arredondadas, H centrado no pixel (com ajuste de meio
        pixel quando a paridade não fecha).
        """
        t = self.tamanho
        if t <= 64:
            haste = max(2, round(self.h_haste * t))
            barra = max(2, round(self.h_barra * t))
            largura = round(self.h_largura * t)
            altura = round(self.h_altura * t)
            vao = max(2, largura - 2 * haste)
            largura = 2 * haste + vao
            if (t - largura) % 2:          # centraliza em pixel inteiro
                vao += 1
                largura += 1
            if (t - altura) % 2:
                altura += 1
            if (altura - barra) % 2:
                barra += 1
            x0 = (t - largura) // 2
            y0 = (t - altura) // 2
            yb = y0 + (altura - barra) // 2
            pecas_px = [(x0, y0, x0 + haste, y0 + altura),
                        (x0 + largura - haste, y0, x0 + largura, y0 + altura),
                        (x0 + haste, yb, x0 + largura - haste, yb + barra)]
            return [tuple(v / t for v in p) for p in pecas_px]
        x0 = 0.5 - self.h_largura / 2
        x1 = 0.5 + self.h_largura / 2
        y0 = self.h_centro_y - self.h_altura / 2
        y1 = self.h_centro_y + self.h_altura / 2
        yb0 = self.h_centro_y - self.h_barra / 2
        return [(x0, y0, x0 + self.h_haste, y1),
                (x1 - self.h_haste, y0, x1, y1),
                (x0 + self.h_haste, yb0, x1 - self.h_haste, yb0 + self.h_barra)]

    def raio_h(self) -> float:
        """Arredondamento dos cantos das hastes (zero nos pequenos: nitidez)."""
        return 0.0 if self.tamanho <= 64 else 0.016


def superelipse(cx: float, cy: float, rx: float, ry: float, n: float = EXPOENTE,
                pontos: int = 720) -> list[tuple[float, float]]:
    """Os pontos de |x/rx|^n + |y/ry|^n = 1 (o contorno do squircle)."""
    saida = []
    for i in range(pontos):
        a = 2 * math.pi * i / pontos
        c, s = math.cos(a), math.sin(a)
        x = math.copysign(abs(c) ** (2 / n), c)
        y = math.copysign(abs(s) ** (2 / n), s)
        saida.append((cx + rx * x, cy + ry * y))
    return saida


# ================================================================ pintura
def _mascara_poligono(lado: int, pontos: list[tuple[float, float]]) -> Image.Image:
    m = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(m).polygon([(x * lado, y * lado) for x, y in pontos], fill=255)
    return m


def _gradiente_vertical(lado: int, cima: tuple, baixo: tuple,
                        inicio: float = 0.0, fim: float = 1.0) -> Image.Image:
    """Imagem RGB com gradiente de 'cima' para 'baixo' entre as frações
    'inicio' e 'fim' da altura."""
    g = Image.linear_gradient("L").resize((1, 256))
    faixa = Image.new("L", (1, lado))
    altura = max(1, int(round((fim - inicio) * lado)))
    faixa.paste(0, (0, 0, 1, max(0, int(inicio * lado))))
    faixa.paste(g.resize((1, altura)), (0, int(inicio * lado)))
    if int(inicio * lado) + altura < lado:
        faixa.paste(255, (0, int(inicio * lado) + altura, 1, lado))
    mascara = faixa.resize((lado, lado))
    return Image.composite(Image.new("RGB", (lado, lado), baixo),
                           Image.new("RGB", (lado, lado), cima), mascara)


def _alfa_vertical(lado: int, cima: float, baixo: float) -> Image.Image:
    """Máscara L que vai de 'cima' (0..1) a 'baixo' (0..1), de cima para baixo."""
    g = Image.linear_gradient("L").resize((1, lado))
    tabela = [int(round(255 * (cima + (baixo - cima) * v / 255))) for v in range(256)]
    return g.point(tabela).resize((lado, lado))


def _brilho_radial(lado: int, cx: float, cy: float, raio: float, cor: tuple,
                   intensidade: float) -> Image.Image:
    """Mancha de luz RGBA (centro forte, borda zero), em unidades.

    Um disco desfocado, e não o radial_gradient do Pillow: aquele, ampliado
    de 256 px, deixa degraus visíveis na luz fraca do fundo.
    """
    alfa = Image.new("L", (lado, lado), 0)
    r = raio * lado * 0.5
    ImageDraw.Draw(alfa).ellipse((cx * lado - r, cy * lado - r, cx * lado + r, cy * lado + r),
                                 fill=int(255 * intensidade))
    alfa = alfa.filter(ImageFilter.GaussianBlur(raio * lado * 0.32))
    camada = Image.new("RGBA", (lado, lado), cor + (0,))
    camada.putalpha(alfa)
    return camada


def _mascara_h(lado: int, d: Desenho) -> Image.Image:
    """O H numa máscara só: as hastes com os cantos externos arredondados e a
    barra entrando metade da haste em cada lado - sem emenda visível."""
    m = Image.new("L", (lado, lado), 0)
    desenho = ImageDraw.Draw(m)
    raio = d.raio_h() * lado
    esquerda, direita, barra = d.retangulos_h()
    for x0, y0, x1, y1 in (esquerda, direita):
        caixa = (x0 * lado, y0 * lado, x1 * lado - 1, y1 * lado - 1)
        if raio > 0:
            desenho.rounded_rectangle(caixa, radius=raio, fill=255)
        else:
            desenho.rectangle(caixa, fill=255)
    entra = (esquerda[2] - esquerda[0]) / 2
    x0, y0, x1, y1 = barra
    desenho.rectangle(((x0 - entra) * lado, y0 * lado, (x1 + entra) * lado - 1, y1 * lado - 1),
                      fill=255)
    return m


def _com_alfa(cor: tuple, mascara: Image.Image, fator: float = 1.0) -> Image.Image:
    camada = Image.new("RGBA", mascara.size, cor + (0,))
    camada.putalpha(mascara if fator == 1.0 else mascara.point(lambda v: int(v * fator)))
    return camada


def icone(tamanho: int) -> Image.Image:
    """O ícone RGBA no tamanho pedido (desenho próprio de cada faixa)."""
    d = Desenho(tamanho)
    escala = 4 if tamanho >= 128 else 8
    lado = tamanho * escala
    m = d.margem
    meio = 0.5 - m
    contorno = superelipse(0.5, 0.5, meio, meio)
    forma = _mascara_poligono(lado, contorno)

    # 1. Fundo: navy em gradiente (#1B3560 -> #0B1A33), com um brilho azul no
    #    alto à esquerda (a "luz" que o vidro deixa ver) e o canto de baixo
    #    à direita mais escuro.
    fundo = _gradiente_vertical(lado, NAVY_700, NAVY_900).convert("RGBA")
    if not d.simples:
        fundo.alpha_composite(_brilho_radial(lado, 0.20, 0.14, 0.70, AZUL_CLARO, 0.36))
        fundo.alpha_composite(_brilho_radial(lado, 0.74, 0.76, 0.52, AZUL, 0.50))
    else:
        fundo.alpha_composite(_brilho_radial(lado, 0.25, 0.15, 0.75, AZUL_CLARO, 0.22))

    # 2. Placa de vidro fosco, cinza translúcida, atrás do H: o fundo dela é
    #    o próprio fundo desfocado e clareado (é o que dá a transparência: a
    #    luz azul de baixo aparece borrada através dela).
    if not d.simples:
        lp = d.placa_lado / 2
        placa = _mascara_poligono(lado, superelipse(0.5, 0.5, lp, lp, d.placa_n))
        fosco = fundo.filter(ImageFilter.GaussianBlur(lado * 0.06))
        fosco.alpha_composite(_com_alfa(CINZA_PLACA, Image.new("L", (lado, lado), 255), 0.20))
        # mais clara em cima: a luz bate no vidro
        fosco.alpha_composite(_com_alfa(BRANCO, _alfa_vertical(lado, 0.16, 0.0)))
        fundo.paste(fosco, (0, 0), placa)
        # borda da placa: fio claro e translúcido, mais forte em cima
        e = max(1.0, lado * (0.007 if tamanho >= 128 else 0.016)) / lado
        miolo = _mascara_poligono(lado, superelipse(0.5, 0.5, lp - e, lp - e, d.placa_n))
        fio = ImageChops.multiply(ImageChops.subtract(placa, miolo),
                                  _alfa_vertical(lado, 0.80, 0.18))
        fundo.alpha_composite(_com_alfa(BRANCO, fio))

    # 3. Sombra suave do H (deslocada para baixo, desfocada).
    mh = _mascara_h(lado, d)
    if not d.simples:
        sombra = mh.filter(ImageFilter.GaussianBlur(lado * 0.022))
        deslocada = Image.new("L", (lado, lado), 0)
        deslocada.paste(sombra, (0, int(lado * 0.016)))
        fundo.alpha_composite(_com_alfa(SOMBRA, deslocada, 0.62))
    elif tamanho >= 20:
        deslocada = Image.new("L", (lado, lado), 0)
        deslocada.paste(mh, (0, escala))       # 1 px de sombra dura, discreta
        fundo.alpha_composite(_com_alfa(SOMBRA, deslocada, 0.45))

    # 4. O H: branco em cima, cinza-claro embaixo.
    if d.simples:
        cor_h = _gradiente_vertical(lado, BRANCO, (226, 231, 238)).convert("RGBA")
    else:
        y0 = min(r[1] for r in d.retangulos_h())
        y1 = max(r[3] for r in d.retangulos_h())
        cor_h = _gradiente_vertical(lado, BRANCO, CINZA_H, y0, y1).convert("RGBA")
    cor_h.putalpha(mh)
    fundo.alpha_composite(cor_h)

    # 5. Vidro do ícone: reflexo suave no alto (luz branca translúcida que
    #    some antes do meio, sem linha de corte) e borda interna clara.
    if not d.simples:
        reflexo = Image.new("L", (lado, lado), 0)
        ImageDraw.Draw(reflexo).ellipse(
            (-0.30 * lado, -0.80 * lado, 1.30 * lado, 0.36 * lado), fill=255)
        reflexo = reflexo.filter(ImageFilter.GaussianBlur(lado * 0.035))
        reflexo = ImageChops.multiply(reflexo, _alfa_vertical(lado, 0.17, -0.04))
        fundo.alpha_composite(_com_alfa(BRANCO, reflexo))
    e = (max(1.0, lado * 0.011) if not d.simples else float(escala)) / lado
    miolo = _mascara_poligono(lado, superelipse(0.5, 0.5, meio - e, meio - e))
    borda = ImageChops.subtract(forma, miolo)
    alfas = (0.55, 0.08) if not d.simples else (0.32, 0.04)
    borda = ImageChops.multiply(borda, _alfa_vertical(lado, *alfas))
    fundo.alpha_composite(_com_alfa(BRANCO, borda))

    # 6. Recorte no squircle (cantos transparentes) e redução. O LANCZOS
    #    deixa um resto de alfa (1 ou 2) fora da forma: vira transparente de
    #    vez, para o canto não ter "poeira" nem a máscara do .ico errar.
    fundo.putalpha(ImageChops.multiply(fundo.getchannel("A"), forma))
    final = fundo.resize((tamanho, tamanho), Image.LANCZOS)
    alfa = final.getchannel("A").point(lambda v: 0 if v <= 2 else v)
    vazio = Image.new("RGBA", final.size, (0, 0, 0, 0))
    final = Image.composite(final, vazio, alfa.point(lambda v: 255 if v else 0))
    final.putalpha(alfa)
    return final


# ================================================================ ICO
def ico_bytes(imagens: list[Image.Image]) -> bytes:
    """Um .ico com cada imagem RGBA: BMP de 32 bits (com máscara AND) até
    128 px e PNG no de 256 px - o formato do Visual Studio, que o windres,
    o NSIS e todas as versões do Windows leem."""
    imagens = sorted(imagens, key=lambda im: im.width)
    corpos = []
    for im in imagens:
        im = im.convert("RGBA")
        w, h = im.size
        if w >= 256:
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            corpos.append(buf.getvalue())
            continue
        linha_mascara = ((w + 31) // 32) * 4
        cabecalho = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                                w * h * 4 + linha_mascara * h, 0, 0, 0, 0)
        b, g, r, a = im.split()[2], im.split()[1], im.split()[0], im.split()[3]
        bgra = Image.merge("RGBA", (b, g, r, a)).transpose(Image.FLIP_TOP_BOTTOM).tobytes()
        mascara = bytearray()
        alfa = a.transpose(Image.FLIP_TOP_BOTTOM).load()
        for y in range(h):
            bits = bytearray(linha_mascara)
            for x in range(w):
                if alfa[x, y] == 0:          # 1 = transparente (Windows antigos)
                    bits[x // 8] |= 0x80 >> (x % 8)
            mascara += bits
        corpos.append(cabecalho + bgra + bytes(mascara))
    saida = struct.pack("<HHH", 0, 1, len(imagens))
    deslocamento = 6 + 16 * len(imagens)
    for im, corpo in zip(imagens, corpos):
        w, h = im.size
        saida += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(corpo),
                             deslocamento)
        deslocamento += len(corpo)
    return saida + b"".join(corpos)


# ================================================================ SVG
def svg() -> str:
    """O ícone em SVG (barra lateral da interface): a geometria do de 256 px
    com gradientes, a sombra e o reflexo desfocados por filtros do SVG. A
    placa é translúcida de verdade (opacidade): o fundo aparece através dela."""
    d = Desenho(1024)
    lado = 1024

    def caminho(pontos: list[tuple[float, float]]) -> str:
        p = [f"{x * lado:.1f},{y * lado:.1f}" for x, y in pontos]
        return "M" + " L".join(p) + " Z"

    def hexa(c: tuple) -> str:
        return "#%02X%02X%02X" % c

    def luz(nome: str, cx: float, cy: float, raio: float, cor: tuple, forca: float) -> str:
        # o disco desfocado do bitmap (raio/2 + 2 sigmas) em gradiente radial
        alcance = raio * (0.5 + 0.64)
        return (f'    <radialGradient id="{nome}" gradientUnits="userSpaceOnUse" '
                f'cx="{cx * lado:.1f}" cy="{cy * lado:.1f}" r="{alcance * lado:.1f}">\n'
                f'      <stop offset="0" stop-color="{hexa(cor)}" stop-opacity="{forca:.2f}"/>\n'
                f'      <stop offset="0.42" stop-color="{hexa(cor)}" stop-opacity="{forca * 0.55:.2f}"/>\n'
                f'      <stop offset="1" stop-color="{hexa(cor)}" stop-opacity="0"/>\n'
                f'    </radialGradient>')

    meio = 0.5 - d.margem
    squircle = caminho(superelipse(0.5, 0.5, meio, meio, pontos=240))
    lp = d.placa_lado / 2
    placa = caminho(superelipse(0.5, 0.5, lp, lp, d.placa_n, pontos=200))
    raio = d.raio_h() * lado
    esquerda, direita, barra = d.retangulos_h()
    entra = (esquerda[2] - esquerda[0]) / 2
    barra = (barra[0] - entra, barra[1], barra[2] + entra, barra[3])
    y0 = esquerda[1] * lado
    y1 = esquerda[3] * lado
    pecas = []
    for x0, ya, x1, yb in (esquerda, direita, barra):
        r = raio if (x0, ya, x1, yb) != barra else 0
        pecas.append(f'      <rect x="{x0 * lado:.1f}" y="{ya * lado:.1f}" width="{(x1 - x0) * lado:.1f}" '
                     f'height="{(yb - ya) * lado:.1f}" rx="{r:.1f}"/>')
    rects = "\n".join(pecas)
    borda = 0.011 * lado * 2      # metade fica fora do recorte

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}" width="{lado}" height="{lado}" role="img" aria-label="Helestron">
  <title>Helestron</title>
  <defs>
    <linearGradient id="fundo" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{hexa(NAVY_700)}"/>
      <stop offset="1" stop-color="{hexa(NAVY_900)}"/>
    </linearGradient>
{luz("luz-alto", 0.20, 0.14, 0.70, AZUL_CLARO, 0.36)}
{luz("luz-baixo", 0.74, 0.76, 0.52, AZUL, 0.50)}
    <linearGradient id="placa" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.30"/>
      <stop offset="1" stop-color="{hexa(CINZA_PLACA)}" stop-opacity="0.20"/>
    </linearGradient>
    <linearGradient id="fio-placa" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.80"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0.18"/>
    </linearGradient>
    <linearGradient id="letra" gradientUnits="userSpaceOnUse" x1="0" y1="{y0:.1f}" x2="0" y2="{y1:.1f}">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="{hexa(CINZA_H)}"/>
    </linearGradient>
    <linearGradient id="reflexo" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="{0.81 * lado:.1f}">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.17"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="borda" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.55"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0.08"/>
    </linearGradient>
    <clipPath id="recorte"><path d="{squircle}"/></clipPath>
    <filter id="desfoque" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="36"/>
    </filter>
    <filter id="sombra" x="-25%" y="-25%" width="150%" height="160%" color-interpolation-filters="sRGB">
      <feGaussianBlur in="SourceAlpha" stdDeviation="22" result="desfocada"/>
      <feOffset in="desfocada" dy="16" result="deslocada"/>
      <feFlood flood-color="{hexa(SOMBRA)}" flood-opacity="0.62"/>
      <feComposite in2="deslocada" operator="in" result="sombra"/>
      <feMerge><feMergeNode in="sombra"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <g clip-path="url(#recorte)">
    <rect width="{lado}" height="{lado}" fill="url(#fundo)"/>
    <rect width="{lado}" height="{lado}" fill="url(#luz-alto)"/>
    <rect width="{lado}" height="{lado}" fill="url(#luz-baixo)"/>
    <path d="{placa}" fill="url(#placa)"/>
    <path d="{placa}" fill="none" stroke="url(#fio-placa)" stroke-width="7"/>
    <g fill="url(#letra)" filter="url(#sombra)">
{rects}
    </g>
    <ellipse cx="{0.5 * lado:.1f}" cy="{-0.22 * lado:.1f}" rx="{0.80 * lado:.1f}" ry="{0.58 * lado:.1f}" fill="url(#reflexo)" filter="url(#desfoque)"/>
    <path d="{squircle}" fill="none" stroke="url(#borda)" stroke-width="{borda:.1f}"/>
  </g>
</svg>
"""


# ================================================================ instalador
def _fundo_claro(largura: int, altura: int) -> Image.Image:
    """O fundo da interface (seção 7.1 da especificação): branco em cima,
    azul-gelo embaixo, com manchas desfocadas de azul e navy em baixa
    opacidade - o mesmo "céu" sobre o qual o vidro da janela aparece."""
    escala = 2
    w, h = largura * escala, altura * escala
    lado = max(w, h)
    painel = _gradiente_vertical(lado, BRANCO, AZUL_GELO).convert("RGBA")
    painel.alpha_composite(_brilho_radial(lado, 0.28, 0.82, 0.55, AZUL_CLARO, 0.42))
    painel.alpha_composite(_brilho_radial(lado, 0.62, 0.30, 0.42, NAVY_700, 0.16))
    painel.alpha_composite(_brilho_radial(lado, 0.60, 0.98, 0.40, AZUL, 0.30))
    painel = painel.crop(((lado - w) // 2, 0, (lado - w) // 2 + w, h))
    return painel.resize((largura, altura), Image.LANCZOS)


def _com_sombra(painel: Image.Image, ic: Image.Image, x: int, y: int, desfoque: float,
                deslocamento: int, forca: float) -> None:
    base = Image.new("L", painel.size, 0)
    base.paste(ic.getchannel("A"), (x, y + deslocamento))
    sombra = Image.new("RGBA", painel.size, NAVY_900 + (0,))
    sombra.putalpha(base.filter(ImageFilter.GaussianBlur(desfoque)).point(lambda v: int(v * forca)))
    painel.alpha_composite(sombra)
    painel.alpha_composite(ic, (x, y))


def boas_vindas() -> Image.Image:
    """164 x 314, BMP de 24 bits (MUI_WELCOMEFINISHPAGE_BITMAP): o fundo
    claro da interface, uma placa de vidro fosco e, sobre ela, o ícone."""
    largura, altura = 164, 314
    painel = _fundo_claro(largura, altura)
    # placa de vidro (branco translúcido, fio claro), como os cartões da janela
    escala = 4
    vidro = Image.new("RGBA", (largura * escala, altura * escala), (0, 0, 0, 0))
    ImageDraw.Draw(vidro).rounded_rectangle(
        (22 * escala, 58 * escala, (largura - 22) * escala, 178 * escala), radius=26 * escala,
        fill=(255, 255, 255, 120), outline=(255, 255, 255, 230), width=escala)
    sombra = vidro.getchannel("A").filter(ImageFilter.GaussianBlur(10 * escala))
    camada = Image.new("RGBA", vidro.size, NAVY_900 + (0,))
    camada.putalpha(sombra.point(lambda v: int(v * 0.10)))
    camada.alpha_composite(vidro)
    painel.alpha_composite(camada.resize((largura, altura), Image.LANCZOS))
    lado = 88
    _com_sombra(painel, icone(lado), (largura - lado) // 2, 74, 6, 5, 0.40)
    return painel.convert("RGB")


def cabecalho() -> Image.Image:
    """150 x 57, BMP de 24 bits (MUI_HEADERIMAGE_BITMAP, à direita): fundo
    branco - o do cabeçalho do assistente - e o ícone encostado à direita."""
    largura, altura = 150, 57
    fundo = Image.new("RGBA", (largura, altura), BRANCO + (255,))
    lado = 44
    _com_sombra(fundo, icone(lado), largura - lado - 10, (altura - lado) // 2 - 1, 3, 2, 0.30)
    return fundo.convert("RGB")


# ================================================================ tudo
def gerar(recursos: Path = RECURSOS, web: Path = WEB_MARCA) -> list[Path]:
    """Grava todos os arquivos da marca e devolve a lista."""
    recursos.mkdir(parents=True, exist_ok=True)
    web.mkdir(parents=True, exist_ok=True)
    gravados = []
    imagens = [icone(t) for t in TAMANHOS_ICO]
    destino = recursos / "helestron.ico"
    destino.write_bytes(ico_bytes(imagens))
    gravados.append(destino)
    grande = icone(512)
    for caminho, imagem in ((recursos / "helestron.png", grande),
                            (recursos / "helestron-64.png", imagens[TAMANHOS_ICO.index(64)]),
                            (web / "helestron-64.png", imagens[TAMANHOS_ICO.index(64)])):
        imagem.save(caminho, format="PNG", optimize=True)
        gravados.append(caminho)
    for caminho, imagem in ((recursos / "instalador-boas-vindas.bmp", boas_vindas()),
                            (recursos / "instalador-cabecalho.bmp", cabecalho())):
        imagem.save(caminho, format="BMP")
        gravados.append(caminho)
    destino = web / "helestron.svg"
    destino.write_text(svg(), encoding="utf-8", newline="\n")
    gravados.append(destino)
    return gravados


def previa(pasta: Path) -> list[Path]:
    """Folhas de conferência: todos os tamanhos, em tamanho real e ampliados
    (vizinho mais próximo, para ver cada pixel), sobre fundo claro e escuro."""
    pasta.mkdir(parents=True, exist_ok=True)
    saida = []
    for nome, cor in (("claro", (242, 244, 247)), ("escuro", (28, 28, 30))):
        folha = Image.new("RGBA", (1400, 900), cor + (255,))
        x = 20
        for t in TAMANHOS_ICO:
            folha.alpha_composite(icone(t), (x, 20))
            x += t + 16
        x = 20
        for t in (16, 20, 24, 32, 40, 48):
            fator = 8 if t <= 24 else 5
            ampliado = icone(t).resize((t * fator, t * fator), Image.NEAREST)
            folha.alpha_composite(ampliado, (x, 320))
            x += t * fator + 16
        folha.alpha_composite(icone(512).resize((256, 256), Image.LANCZOS), (1120, 600))
        caminho = pasta / f"previa-{nome}.png"
        folha.save(caminho)
        saida.append(caminho)
    instalador = Image.new("RGB", (164 + 40 + 150, 314), (200, 200, 200))
    instalador.paste(boas_vindas(), (0, 0))
    instalador.paste(cabecalho(), (204, 0))
    caminho = pasta / "previa-instalador.png"
    instalador.resize((instalador.width * 2, instalador.height * 2), Image.NEAREST).save(caminho)
    saida.append(caminho)
    return saida


def _classe_do_analisador() -> type:
    """O ArgumentParser em português do programa (helestron/nucleo/argumentos.py),
    carregado pelo arquivo; sem ele, o do argparse."""
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(
            "helestron_argumentos", RAIZ / "helestron" / "nucleo" / "argumentos.py")
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.ArgumentParser
    except (OSError, ImportError, AttributeError, SyntaxError):
        return argparse.ArgumentParser


def main(argv: list[str] | None = None) -> int:
    p = _classe_do_analisador()(prog="python construir/marca.py",
                                description="Gera o ícone e as imagens do instalador.")
    p.add_argument("--recursos", type=Path, default=RECURSOS, metavar="PASTA",
                   help="onde gravar o ícone e as imagens do instalador (padrão: helestron/recursos)")
    p.add_argument("--web", type=Path, default=WEB_MARCA, metavar="PASTA",
                   help="onde gravar a marca da interface (padrão: helestron/web/img/marca)")
    p.add_argument("--previa", type=Path, metavar="PASTA", help="grava também as folhas de conferência")
    a = p.parse_args(argv)
    for arquivo in gerar(a.recursos, a.web):
        print(arquivo)
    if a.previa:
        for arquivo in previa(a.previa):
            print(arquivo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
