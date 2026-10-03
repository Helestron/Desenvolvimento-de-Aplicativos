"""Catálogo de tribunais: de que portal é cada processo, pelo próprio número.

O "J.TR" do número CNJ diz o tribunal (8.02 = TJAL, 8.21 = TJRS, 4.04 =
TRF4). Com isso o programa escolhe sozinho entre e-SAJ e eProc e o endereço
certo, e uma relação que mistura tribunais é baixada grupo a grupo - o
usuário não precisa dizer de onde é cada processo.

O catálogo mora em dados/tribunais.json, editável: se um portal mudar de
endereço, corrige-se ali, sem mexer no código.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import caminhos
from .cnj import Numero

log = logging.getLogger(__name__)

ARQUIVO = caminhos.DADOS / "tribunais.json"
# Endereços corrigidos pelo usuário (tela de Configurações). Ficam fora do
# catálogo para uma atualização do programa não apagá-los.
ARQUIVO_LOCAL = caminhos.RAIZ / "enderecos-locais.json"
SUPORTADOS = ("esaj", "eproc")
NOMES_SISTEMA = {"esaj": "e-SAJ", "eproc": "eProc", "outro": "não suportado"}


@dataclass(frozen=True)
class Tribunal:
    chave: str                 # "8.02"
    sigla: str                 # "TJAL"
    nome: str
    sistema: str               # "esaj" | "eproc" | "outro"
    urls: dict = field(default_factory=dict, hash=False, compare=False)
    observacao: str = ""
    # Segundo sistema do tribunal em transição (TJAL e TJSP: e-SAJ -> eProc).
    alternativo: "Tribunal | None" = field(default=None, hash=False, compare=False)

    @property
    def suportado(self) -> bool:
        return self.sistema in SUPORTADOS

    @property
    def nome_sistema(self) -> str:
        return NOMES_SISTEMA.get(self.sistema, self.sistema)

    @property
    def portal(self) -> str:
        """Chave do cofre de senhas e do perfil do navegador: 'esaj:TJAL'."""
        return f"{self.sistema}:{self.sigla}"

    def urls_para(self, numero: Numero | None = None, grau: str = "1g") -> list[str]:
        """Endereços candidatos do portal, na ordem de tentativa.

        e-SAJ: 'base'. eProc: por grau e, na Justiça Federal, pela seção
        judiciária (dois primeiros dígitos da origem). Um valor do catálogo
        pode ser uma lista - endereço ainda não confirmado, com reservas.
        """
        def lista(valor) -> list[str]:
            if isinstance(valor, str):
                return [valor] if valor else []
            return [v for v in (valor or []) if v]

        if self.sistema == "esaj":
            return lista(self.urls.get("base"))
        if numero is not None:
            secao = f"{grau}_{numero.origem[:2]}"
            if secao in self.urls:
                return lista(self.urls[secao])
        if grau in self.urls:
            return lista(self.urls[grau])
        for chave, valor in self.urls.items():
            if chave.startswith(grau):
                return lista(valor)
        return lista(next(iter(self.urls.values()), ""))

    def url_para(self, numero: Numero | None = None, grau: str = "1g") -> str:
        candidatos = self.urls_para(numero, grau)
        return candidatos[0] if candidatos else ""


@lru_cache(maxsize=4)
def _carregar(arquivo: str, _mtime: float) -> tuple[Tribunal, ...]:
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        log.error("catálogo de tribunais ilegível (%s): %s", arquivo, erro)
        return ()
    saida = []
    for t in dados.get("tribunais", []):
        try:
            alt = None
            if isinstance(t.get("alternativo"), dict) and t["alternativo"].get("sistema"):
                alt = Tribunal(chave=t["chave"], sigla=t["sigla"], nome=t.get("nome", t["sigla"]),
                               sistema=t["alternativo"]["sistema"],
                               urls=dict(t["alternativo"].get("urls") or {}),
                               observacao=t.get("observacao", ""))
            saida.append(Tribunal(chave=t["chave"], sigla=t["sigla"], nome=t.get("nome", t["sigla"]),
                                  sistema=t.get("sistema", "outro"), urls=dict(t.get("urls") or {}),
                                  observacao=t.get("observacao", ""), alternativo=alt))
        except KeyError:
            continue
    return tuple(saida)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _ler_locais() -> dict:
    try:
        return json.loads(ARQUIVO_LOCAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _com_locais(t: Tribunal, locais: dict) -> Tribunal:
    """Aplica {'eproc:TJAL': {'1g': 'https://...'}} sobre o catálogo."""
    from dataclasses import replace

    alt = t.alternativo
    if alt is not None and alt.portal in locais:
        alt = replace(alt, urls={**alt.urls, **locais[alt.portal]})
    urls = {**t.urls, **locais.get(t.portal, {})}
    return replace(t, urls=urls, alternativo=alt)


def carregar(arquivo: Path | None = None) -> tuple[Tribunal, ...]:
    p = Path(arquivo or ARQUIVO)
    base = _carregar(str(p), _mtime(p))
    locais = _ler_locais()
    if not locais:
        return base
    return tuple(_com_locais(t, locais) for t in base)


def definir_endereco(portal: str, grau: str, url: str) -> None:
    """Grava o endereço corrigido pelo usuário ('eproc:TJAL', '1g', url).

    Endereço em branco apaga a correção (volta o do catálogo).
    """
    locais = _ler_locais()
    entrada = locais.setdefault(portal, {})
    if url.strip():
        entrada[grau] = url.strip()
    else:
        entrada.pop(grau, None)
        if not entrada:
            locais.pop(portal, None)
    tmp = ARQUIVO_LOCAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(locais, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    import os
    os.replace(tmp, ARQUIVO_LOCAL)


def por_chave(chave: str) -> Tribunal | None:
    for t in carregar():
        if t.chave == chave:
            return t
    return None


def por_sigla(sigla: str) -> Tribunal | None:
    for t in carregar():
        if t.sigla.upper() == (sigla or "").upper():
            return t
    return None


def por_numero(numero: Numero) -> Tribunal | None:
    return por_chave(numero.chave_tribunal)


def descrever(numero: Numero) -> str:
    """'TJAL · e-SAJ' - para a tabela da tela."""
    t = por_numero(numero)
    if t is None:
        return f"tribunal {numero.chave_tribunal} desconhecido"
    if t.alternativo is not None:
        return f"{t.sigla} · {t.nome_sistema} ou {t.alternativo.nome_sistema}"
    return f"{t.sigla} · {t.nome_sistema}"
