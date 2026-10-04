"""Espelha o acervo numa pasta do OneDrive ou do Google Drive.

Os conectores do ChatGPT e do Claude (na web, no celular e no Cowork) leem
arquivos do OneDrive/SharePoint e do Google Drive. Pôr o acervo numa dessas
pastas é, portanto, o jeito de deixá-lo ao alcance dessas ferramentas sem
anexar arquivo por arquivo.

O acervo de trabalho NÃO mora na pasta sincronizada - a sincronização
atrapalha arquivo em uso (lição do Assessor SAJ). O que se faz é uma CÓPIA
de mão única, ao fim de cada lote ou quando o usuário pede: só o que é novo
ou mudou é copiado, e nada é apagado no destino - com uma exceção, de
propósito: a cópia de um processo que hoje está na pasta de sigilosos
(segredo de justiça) é retirada do espelho.
"""

from __future__ import annotations

import logging
import os
import shutil
import string
from pathlib import Path

from ..nucleo import cnj
from .mcp_servidor import _DO_CONFIG, Recorte, chaves_sigilosas, pasta_sigilosos_configurada

log = logging.getLogger("compartilhar.nuvem")

SUBPASTA = "Helestron - Acervo"
# A subpasta do espelho da versão anterior (Assessor Integrado). Ninguém mais
# copia para lá, mas o que ficou continua ao alcance dos conectores do
# OneDrive e do Google Drive: dela também sai a cópia do processo que depois
# foi para a pasta de sigilosos.
SUBPASTAS_ANTIGAS = ("Assessor Integrado - Acervo",)
_IGNORAR_PASTAS = {"_controle", "_audio", "__pycache__"}
_IGNORAR_SUFIXOS = (".parcial", ".tmp", ".part", ".lock")


def detectar() -> dict[str, Path]:
    """Pastas de nuvem encontradas neste computador: {rótulo: caminho}."""
    achadas: dict[str, Path] = {}
    for var, rotulo in (("OneDriveCommercial", "OneDrive (instituição)"),
                        ("OneDriveConsumer", "OneDrive (pessoal)"),
                        ("OneDrive", "OneDrive")):
        valor = os.environ.get(var)
        if valor and Path(valor).is_dir():
            p = Path(valor)
            if p not in achadas.values():
                achadas[rotulo] = p
    # Google Drive para computador: unidade virtual com "Meu Drive"/"My Drive",
    # ou a pasta antiga do Backup and Sync no perfil.
    candidatos = []
    if os.name == "nt":
        for letra in string.ascii_uppercase[3:]:
            candidatos += [Path(f"{letra}:/Meu Drive"), Path(f"{letra}:/My Drive")]
    casa = Path.home()
    candidatos += [casa / "Google Drive" / "Meu Drive", casa / "Google Drive" / "My Drive",
                   casa / "Google Drive", casa / "Meu Drive", casa / "My Drive"]
    for c in candidatos:
        try:
            if c.is_dir():
                achadas.setdefault("Google Drive", c)
                break
        except OSError:
            continue
    return achadas


def _deve_copiar(origem: Path, destino: Path) -> bool:
    try:
        a = origem.stat()
    except OSError:
        return False
    try:
        b = destino.stat()
    except OSError:
        return True
    # mtime com folga de 2 s: FAT/exFAT e alguns clientes de nuvem arredondam.
    return a.st_size != b.st_size or a.st_mtime > b.st_mtime + 2


def _chave(nome: str) -> str | None:
    try:
        return cnj.ler_nome_arquivo(Path(nome).stem).nome_arquivo
    except cnj.NumeroInvalido:
        return None


def espelhar(origem: Path, destino_raiz: Path, progresso=None, cancelado=None,
             sigilosos=_DO_CONFIG) -> tuple[int, int]:
    """Copia o acervo para '<destino_raiz>/Helestron - Acervo'.

    Devolve (copiados, iguais). Não apaga nada no destino, exceto a cópia de
    processo que está na pasta de sigilosos ('sigilosos'; por padrão, a do
    config.ini): PDF, texto extraído, transcrição ou minuta com o número dele.
    """
    origem = Path(origem)
    destino = Path(destino_raiz) / SUBPASTA
    if _dentro_ou_igual(destino, origem) or _dentro_ou_igual(origem, destino):
        # Defesa final (a API já recusa essa pasta): o espelho dentro do
        # acervo copiaria a cópia anterior a cada vez, sem fim.
        raise ValueError("a pasta da nuvem não pode ficar dentro do acervo, nem conter o acervo")
    if sigilosos is _DO_CONFIG:
        sigilosos = pasta_sigilosos_configurada()
    # Pasta de sigilosos e pastas do programa postas (por engano) dentro do
    # acervo, e link ou junção para fora dele: ficam de fora
    recorte = Recorte(origem, sigilosos)
    sigilosas = chaves_sigilosas(sigilosos, origem)
    arquivos = []
    for p in origem.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(origem).parts
        partes = set(rel[:-1])
        if partes & _IGNORAR_PASTAS or p.name.startswith("~$") \
                or p.name.endswith(_IGNORAR_SUFIXOS):
            continue
        if not recorte.aceita(p):
            continue
        if sigilosas and _chave(p.name) in sigilosas:
            continue
        arquivos.append(p)
    _retirar_sigilosos(destino, sigilosas)
    for antiga in SUBPASTAS_ANTIGAS:
        _retirar_sigilosos(Path(destino_raiz) / antiga, sigilosas)
    copiados = iguais = 0
    total = len(arquivos)
    for i, p in enumerate(arquivos, 1):
        if cancelado and cancelado():
            break
        alvo = destino / p.relative_to(origem)
        if not _deve_copiar(p, alvo):
            iguais += 1
            continue
        if progresso:
            progresso(i, total, p.name)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_name(alvo.name + ".parcial")
        try:
            shutil.copy2(p, tmp)
            os.replace(tmp, alvo)
            copiados += 1
        except OSError as erro:
            log.warning("não copiei %s para a nuvem: %s", p.name, erro)
            try:
                tmp.unlink()
            except OSError:
                pass
    log.info("Espelho na nuvem (%s): %d copiado(s), %d sem mudança.", destino, copiados, iguais)
    return copiados, iguais


def _dentro_ou_igual(filho: Path, pai: Path) -> bool:
    def normal(p: Path) -> str:
        try:
            p = Path(p).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            p = Path(os.path.abspath(p))
        return os.path.normcase(str(p))

    f, p = normal(filho), normal(pai)
    return f == p or f.startswith(p.rstrip(os.sep) + os.sep)


def _retirar_sigilosos(destino: Path, sigilosas: set[str]) -> None:
    """Apaga do espelho as cópias dos processos que estão na pasta de sigilosos.

    Elas chegaram lá antes da separação (que falhou e foi refeita à mão, por
    exemplo); segredo de justiça não pode continuar na nuvem.
    """
    if not sigilosas or not destino.is_dir():
        return
    for p in destino.rglob("*"):
        try:
            if p.is_file() and _chave(p.name) in sigilosas:
                p.unlink()
                log.warning("Retirei do espelho na nuvem %s: o processo está na pasta de "
                            "sigilosos.", p.relative_to(destino))
        except OSError as erro:
            log.warning("ATENÇÃO: não consegui retirar do espelho na nuvem %s, de processo "
                        "sigiloso (%s). Apague-o à mão.", p.name, erro)
