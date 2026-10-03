"""Espelha o acervo numa pasta do OneDrive ou do Google Drive.

Os conectores do ChatGPT e do Claude (na web, no celular e no Cowork) leem
arquivos do OneDrive/SharePoint e do Google Drive. Pôr o acervo numa dessas
pastas é, portanto, o jeito de deixá-lo ao alcance dessas ferramentas sem
anexar arquivo por arquivo.

O acervo de trabalho NÃO mora na pasta sincronizada - a sincronização
atrapalha arquivo em uso (lição do Assessor SAJ). O que se faz é uma CÓPIA
de mão única, ao fim de cada lote ou quando o usuário pede: só o que é novo
ou mudou é copiado, e nada é apagado no destino.
"""

from __future__ import annotations

import logging
import os
import shutil
import string
from pathlib import Path

log = logging.getLogger("compartilhar.nuvem")

SUBPASTA = "Assessor Integrado - Acervo"
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


def espelhar(origem: Path, destino_raiz: Path, progresso=None, cancelado=None) -> tuple[int, int]:
    """Copia o acervo para '<destino_raiz>/Assessor Integrado - Acervo'.

    Devolve (copiados, iguais). Nunca apaga nada no destino.
    """
    origem = Path(origem)
    destino = Path(destino_raiz) / SUBPASTA
    arquivos = []
    for p in origem.rglob("*"):
        if not p.is_file():
            continue
        partes = set(p.relative_to(origem).parts[:-1])
        if partes & _IGNORAR_PASTAS or p.name.startswith("~$") \
                or p.name.endswith(_IGNORAR_SUFIXOS):
            continue
        arquivos.append(p)
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
