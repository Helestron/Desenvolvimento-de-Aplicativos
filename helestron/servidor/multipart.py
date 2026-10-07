"""Leitura de envio de arquivo (multipart/form-data), sem o módulo cgi.

O cgi saiu da biblioteca padrão no Python 3.13, e o email.parser leria o
corpo inteiro na memória - uma gravação de audiência tem centenas de MB, e
o vídeo dela, gigabytes. Este leitor anda pelo corpo em pedaços (64 KB; 1 MB
dentro de um arquivo): cada arquivo vai direto para o disco (em
LOCAL\\temp\\envios, com nome aleatório), sem nunca estar inteiro na memória,
e os campos de texto ficam na memória, com limite.

O tamanho máximo do corpo é de quem chama ('limite'): o servidor o define
por rota (rede.Roteador.adicionar) - LIMITE_PADRAO para a relação e a
pauta, bem mais para a gravação de audiência.

Quem recebe o Envio apaga os arquivos ao terminar (Envio.apagar(), ou o
'with'): a relação de processos pode trazer as senhas dos sigilosos, e a
gravação é de audiência - nada disso fica esquecido no disco.

O nome do arquivo que veio do navegador nunca vira caminho: serve só para
mostrar ("origem") e para achar o número do processo; no disco o arquivo
tem nome aleatório, com a extensão original (os leitores da relação e da
pauta reconhecem o formato por ela) limpa de qualquer caractere estranho.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("servidor.multipart")

PEDACO = 64 * 1024
# Dentro de um arquivo, blocos maiores: 20 GB em blocos de 64 KB são 320 mil
# voltas do laço em Python; em 1 MB, 20 mil (a memória continua pequena).
PEDACO_ARQUIVO = 1024 * 1024
LIMITE_PADRAO = 500 * 1024 * 1024
LIMITE_CABECALHOS = 16 * 1024
LIMITE_CAMPO = 1024 * 1024
LIMITE_PARTES = 50


class EnvioInvalido(ValueError):
    """O corpo não é um multipart/form-data legível."""


class EnvioGrandeDemais(ValueError):
    """O corpo passou do limite de tamanho."""


@dataclass
class ArquivoEnviado:
    campo: str
    nome: str               # como veio do navegador (só para mostrar)
    caminho: Path           # onde ficou no disco (nome aleatório)
    tamanho: int = 0
    tipo: str = ""

    @property
    def extensao(self) -> str:
        return self.caminho.suffix


@dataclass
class Envio:
    campos: dict[str, str] = field(default_factory=dict)
    arquivos: dict[str, ArquivoEnviado] = field(default_factory=dict)

    def arquivo(self, nome: str = "arquivo") -> ArquivoEnviado | None:
        return self.arquivos.get(nome)

    def apagar(self) -> None:
        for a in self.arquivos.values():
            try:
                a.caminho.unlink(missing_ok=True)
            except OSError as erro:
                log.warning("não consegui apagar o arquivo enviado %s: %s", a.caminho.name, erro)

    def __enter__(self) -> "Envio":
        return self

    def __exit__(self, *_exc) -> None:
        self.apagar()


def fronteira(content_type: str) -> bytes:
    """O 'boundary' do cabeçalho Content-Type, ou EnvioInvalido."""
    tipo, _, resto = (content_type or "").partition(";")
    if tipo.strip().lower() != "multipart/form-data":
        raise EnvioInvalido("o envio não é multipart/form-data")
    params = _parametros(resto)
    valor = params.get("boundary", "")
    if not valor or len(valor) > 200:
        raise EnvioInvalido("o envio não traz o separador (boundary)")
    return valor.encode("latin-1")


def _parametros(texto: str) -> dict[str, str]:
    """'a=1; b="x y"; filename*=UTF-8''nome.xlsx' -> dict (chaves minúsculas)."""
    saida: dict[str, str] = {}
    for m in re.finditer(r';?\s*([\w*.-]+)\s*=\s*("((?:[^"\\]|\\.)*)"|[^;]*)', texto):
        chave = m.group(1).lower()
        valor = m.group(3) if m.group(3) is not None else m.group(2).strip()
        if m.group(3) is not None:
            valor = re.sub(r"\\(.)", r"\1", valor)
        if chave.endswith("*"):
            # RFC 5987: charset''texto-codificado
            from urllib.parse import unquote

            charset, _, codificado = valor.partition("''")
            try:
                valor = unquote(codificado, encoding=charset or "utf-8", errors="replace")
            except LookupError:
                valor = unquote(codificado)
            chave = chave[:-1]
        saida[chave] = valor
    return saida


def _cabecalhos(bloco: bytes) -> dict[str, str]:
    saida: dict[str, str] = {}
    for linha in bloco.split(b"\r\n"):
        if not linha.strip():
            continue
        nome, sep, valor = linha.partition(b":")
        if not sep:
            raise EnvioInvalido("cabeçalho de parte malformado")
        # O navegador manda o nome do arquivo em UTF-8 cru.
        try:
            texto = valor.decode("utf-8").strip()
        except UnicodeDecodeError:
            texto = valor.decode("latin-1").strip()
        saida[nome.decode("latin-1").strip().lower()] = texto
    return saida


def extensao_segura(nome: str) -> str:
    """A extensão do nome enviado, só com letras e números (máx. 10)."""
    ext = Path(nome.replace("\\", "/").split("/")[-1]).suffix.lower()
    ext = re.sub(r"[^a-z0-9]", "", ext)[:10]
    return f".{ext}" if ext else ""


def nome_exibivel(nome: str) -> str:
    """O nome enviado sem pastas (o IE antigo mandava o caminho inteiro)."""
    nome = (nome or "").replace("\\", "/").split("/")[-1]
    nome = re.sub(r"[\x00-\x1f]", "", nome).strip()
    return nome[:200] or "arquivo"


class _Leitor:
    """Lê o corpo do pedido em pedaços, sem passar do Content-Length."""

    def __init__(self, fluxo, tamanho: int):
        self.fluxo = fluxo
        self.restante = tamanho

    def ler(self, n: int = PEDACO) -> bytes:
        if self.restante <= 0:
            return b""
        dados = self.fluxo.read(min(n, self.restante))
        if not dados:
            raise EnvioInvalido("o envio terminou antes do esperado (conexão interrompida)")
        self.restante -= len(dados)
        return dados

    def descartar(self) -> None:
        while self.restante > 0:
            self.ler()


def ler(fluxo, tamanho: int, content_type: str, pasta: Path,
        limite: int = LIMITE_PADRAO) -> Envio:
    """Lê o multipart inteiro de 'fluxo' (exatamente 'tamanho' bytes).

    Arquivos vão para 'pasta', em blocos; em qualquer erro (inclusive o
    disco cheio no meio), o que já foi gravado é apagado antes de a exceção
    subir.
    """
    if tamanho > limite:
        raise EnvioGrandeDemais(f"o envio tem {tamanho} bytes; o limite é {limite}")
    marca = b"--" + fronteira(content_type)
    delimitador = b"\r\n" + marca
    leitor = _Leitor(fluxo, tamanho)
    envio = Envio()
    try:
        _analisar(leitor, marca, delimitador, Path(pasta), envio)
        leitor.descartar()                # epílogo depois do fim
    except BaseException:
        envio.apagar()
        raise
    return envio


def _analisar(leitor: _Leitor, marca: bytes, delimitador: bytes, pasta: Path,
              envio: Envio) -> None:
    buf = b""
    # Preâmbulo: tudo até a primeira marca (normalmente nada).
    while True:
        pos = buf.find(marca)
        if pos >= 0:
            buf = buf[pos + len(marca):]
            break
        if len(buf) > LIMITE_CABECALHOS:
            raise EnvioInvalido("o envio não começa pelo separador")
        pedaco = leitor.ler()
        if not pedaco:
            raise EnvioInvalido("o envio não traz nenhuma parte")
        buf += pedaco
    partes = 0
    while True:
        # Depois da marca: "--" (fim) ou CRLF (outra parte).
        while len(buf) < 2:
            pedaco = leitor.ler()
            if not pedaco:
                raise EnvioInvalido("o envio terminou no meio de um separador")
            buf += pedaco
        if buf.startswith(b"--"):
            return
        if not buf.startswith(b"\r\n"):
            raise EnvioInvalido("separador malformado")
        buf = buf[2:]
        partes += 1
        if partes > LIMITE_PARTES:
            raise EnvioInvalido("partes demais no envio")
        # Cabeçalhos da parte.
        while True:
            fim = buf.find(b"\r\n\r\n")
            if fim >= 0:
                cab, buf = buf[:fim], buf[fim + 4:]
                break
            if len(buf) > LIMITE_CABECALHOS:
                raise EnvioInvalido("cabeçalhos de parte grandes demais")
            pedaco = leitor.ler()
            if not pedaco:
                raise EnvioInvalido("o envio terminou nos cabeçalhos de uma parte")
            buf += pedaco
        cabecalhos = _cabecalhos(cab)
        disposicao = cabecalhos.get("content-disposition", "")
        tipo, _, resto = disposicao.partition(";")
        if tipo.strip().lower() != "form-data":
            raise EnvioInvalido("parte sem Content-Disposition: form-data")
        params = _parametros(resto)
        nome_campo = params.get("name", "")
        nome_arquivo = params.get("filename")
        if nome_arquivo is not None:
            # Campo de arquivo repetido: a segunda parte tomaria o lugar da
            # primeira no dicionário, e o arquivo da primeira (a relação pode
            # trazer senhas) ficaria esquecido no disco - o apagar() só vê o
            # que está no dicionário. Recusa-se o envio: a primeira parte
            # ainda está lá, e o ler() a apaga antes de a exceção subir.
            if nome_campo in envio.arquivos:
                raise EnvioInvalido(f"o campo de arquivo {nome_campo!r} veio repetido")
            destino = _novo_destino(pasta, nome_arquivo)
            enviado = ArquivoEnviado(nome_campo, nome_exibivel(nome_arquivo), destino,
                                     tipo=cabecalhos.get("content-type", ""))
            envio.arquivos[nome_campo] = enviado
            with open(destino, "wb") as saida:
                buf = _copiar_ate(leitor, buf, delimitador, saida.write, enviado,
                                  PEDACO_ARQUIVO)
        else:
            pedacos: list[bytes] = []
            contador = ArquivoEnviado(nome_campo, "", Path())

            def guardar(dados: bytes) -> None:
                if contador.tamanho > LIMITE_CAMPO:
                    raise EnvioGrandeDemais(f"o campo {nome_campo} é grande demais")
                pedacos.append(dados)

            buf = _copiar_ate(leitor, buf, delimitador, guardar, contador)
            envio.campos[nome_campo] = b"".join(pedacos).decode("utf-8", errors="replace")


def _novo_destino(pasta: Path, nome: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / f"envio-{secrets.token_hex(8)}{extensao_segura(nome)}"


def _copiar_ate(leitor: _Leitor, buf: bytes, delimitador: bytes, escrever, conta,
                pedaco_max: int = PEDACO) -> bytes:
    """Entrega o conteúdo da parte até o delimitador; devolve o que sobra
    depois dele (que começa logo após a marca: "--" ou CRLF).

    Guarda sempre os últimos len(delimitador)-1 bytes no buffer: o
    delimitador pode chegar partido entre dois pedaços. Lê no máximo
    'pedaco_max' bytes por vez: a memória usada não depende do tamanho do
    arquivo.
    """
    reserva = len(delimitador) - 1
    while True:
        pos = buf.find(delimitador)
        if pos >= 0:
            if pos:
                conta.tamanho += pos
                escrever(buf[:pos])
            return buf[pos + len(delimitador):]
        if len(buf) > reserva:
            corte = len(buf) - reserva
            conta.tamanho += corte
            escrever(buf[:corte])
            buf = buf[corte:]
        pedaco = leitor.ler(pedaco_max)
        if not pedaco:
            raise EnvioInvalido("o envio terminou sem o separador final")
        buf += pedaco


def apagar_antigos(pasta: Path, idade_s: float = 3600, agora: float | None = None) -> int:
    """Apaga os envios que sobraram de uma execução que caiu no meio."""
    import time

    agora = time.time() if agora is None else agora
    apagados = 0
    try:
        arquivos = [p for p in Path(pasta).iterdir() if p.is_file() and p.name.startswith("envio-")]
    except OSError:
        return 0
    for p in arquivos:
        try:
            if agora - p.stat().st_mtime > idade_s:
                os.unlink(p)
                apagados += 1
        except OSError:
            pass
    return apagados
