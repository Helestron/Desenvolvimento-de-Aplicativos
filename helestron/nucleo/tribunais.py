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
# Endereços corrigidos pelo usuário (ou pelo suporte). Ficam fora do
# catálogo - na pasta de dados, e não na do programa - para uma atualização
# do Helestron não apagá-los.
ARQUIVO_LOCAL = caminhos.LOCAL / "enderecos-locais.json"
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


# Por que o catálogo não pôde ser lido (vazio quando foi lido).
_PROBLEMAS: dict[str, str] = {}


def _ler_json(caminho: Path):
    """JSON editado à mão no Windows: o Bloco de Notas e o PowerShell 5.1
    gravam "UTF-8 com BOM", e o Bloco de Notas antigo, ANSI (cp1252)."""
    dados = Path(caminho).read_bytes()
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = dados.decode("cp1252", errors="replace")
    return json.loads(texto)


def problema(arquivo: Path | None = None) -> str:
    """Frase para o usuário quando o catálogo não pôde ser lido; "" se pôde."""
    p = Path(arquivo or ARQUIVO)
    carregar(p)
    return _PROBLEMAS.get(str(p), "")


@lru_cache(maxsize=4)
def _carregar(arquivo: str, _mtime: float) -> tuple[Tribunal, ...]:
    try:
        dados = _ler_json(Path(arquivo))
        if not isinstance(dados, dict):
            raise ValueError("o conteúdo não é um objeto JSON")
    except (OSError, ValueError) as erro:
        log.error("catálogo de tribunais ilegível (%s): %s", arquivo, erro)
        if isinstance(erro, json.JSONDecodeError):
            motivo = f"erro de formatação na linha {erro.lineno}, coluna {erro.colno}"
        elif isinstance(erro, OSError):
            motivo = erro.strerror or "arquivo inacessível"
        else:
            motivo = str(erro)
        nome = "dados\\tribunais.json" if Path(arquivo) == ARQUIVO else arquivo
        _PROBLEMAS[arquivo] = (f"o catálogo de tribunais ({nome}) não pôde ser lido: {motivo}. "
                               "Corrija o arquivo ou instale o programa de novo")
        return ()
    _PROBLEMAS.pop(arquivo, None)
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


# As entradas do enderecos-locais.json que não puderam valer na última
# leitura ('eproc:TJAL', 'eproc:TJAL/1g'), para a Verificação mostrar.
_DESCARTADOS: list[str] = []


def _ler_locais() -> dict[str, dict[str, str]]:
    """As correções do usuário, só as bem-formadas: {portal: {grau: url}}.

    O arquivo é editado à mão (o suporte manda corrigir ali). Uma entrada
    fora do formato - a URL como texto no lugar do objeto por grau, um
    número, uma lista - derrubava toda consulta de tribunal (TypeError em
    carregar(), para QUALQUER tribunal) e a própria tela que corrige o
    endereço. Aqui ela é deixada de fora, com aviso no registro, e o resto
    vale. A próxima correção pela tela regrava o arquivo sem ela.
    """
    try:
        dados = _ler_json(ARQUIVO_LOCAL)
    except FileNotFoundError:
        _anotar_descartados([])
        return {}
    except (OSError, ValueError) as erro:
        _anotar_descartados([ARQUIVO_LOCAL.name], str(erro))
        return {}
    if not isinstance(dados, dict):
        _anotar_descartados([ARQUIVO_LOCAL.name], "o conteúdo não é um objeto JSON")
        return {}
    limpos: dict[str, dict[str, str]] = {}
    descartados: list[str] = []
    for portal, graus in dados.items():
        if not isinstance(graus, dict):
            descartados.append(str(portal))
            continue
        bons = {str(g): u.strip() for g, u in graus.items() if isinstance(u, str) and u.strip()}
        descartados += [f"{portal}/{g}" for g, u in graus.items()
                        if not isinstance(u, str)]
        if bons:
            limpos[str(portal)] = bons
    _anotar_descartados(descartados)
    return limpos


def _anotar_descartados(lista: list[str], ilegivel: str = "") -> None:
    # carregar() lê o arquivo a cada consulta: o aviso vai para o registro
    # só quando o que foi descartado muda, e não a cada processo da lista.
    if lista != _DESCARTADOS:
        if ilegivel:
            log.warning("endereços corrigidos ilegíveis (%s): %s", ARQUIVO_LOCAL, ilegivel)
        elif lista:
            log.warning("Endereços corrigidos ignorados em %s (fora do formato "
                        "{\"portal\": {\"grau\": \"https://...\"}}): %s",
                        ARQUIVO_LOCAL, ", ".join(lista))
        _DESCARTADOS[:] = lista


def problema_locais() -> str:
    """Frase para a Verificação quando parte do enderecos-locais.json foi
    deixada de fora; "" se tudo valeu (ou se não há correções)."""
    _ler_locais()
    if not _DESCARTADOS:
        return ""
    if _DESCARTADOS == [ARQUIVO_LOCAL.name]:
        return (f"as correções de endereço ({ARQUIVO_LOCAL}) não puderam ser lidas e foram "
                "ignoradas; vale o endereço do catálogo")
    return (f"parte das correções de endereço ({ARQUIVO_LOCAL}) está fora do formato e foi "
            f"ignorada: {', '.join(_DESCARTADOS)}; vale o endereço do catálogo")


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
    if _DESCARTADOS:
        log.warning("A gravação do endereço corrigido retira de %s o que estava fora do "
                    "formato: %s", ARQUIVO_LOCAL.name, ", ".join(_DESCARTADOS))
    entrada = locais.setdefault(portal, {})
    if url.strip():
        entrada[grau] = url.strip()
    else:
        entrada.pop(grau, None)
        if not entrada:
            locais.pop(portal, None)
    ARQUIVO_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQUIVO_LOCAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(locais, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    import os
    os.replace(tmp, ARQUIVO_LOCAL)


# Os graus que a tela de Ajustes mostra para cada chave de 'urls'.
SECOES_JF = {"70": "Paraná", "71": "Rio Grande do Sul", "72": "Santa Catarina",
             "50": "Rio de Janeiro", "51": "Espírito Santo"}


def rotulo_do_grau(grau: str) -> str:
    """'base' -> 'Endereço do portal'; '1g' -> '1º grau'; '1g_71' -> '1º grau — Rio Grande do Sul'."""
    if grau == "base":
        return "Endereço do portal"
    numero, _, secao = grau.partition("_")
    texto = {"1g": "1º grau", "2g": "2º grau"}.get(numero, numero)
    if secao:
        texto += f" — {SECOES_JF.get(secao, 'seção ' + secao)}"
    return texto


def _do_portal(lista: tuple[Tribunal, ...], portal: str) -> Tribunal | None:
    sistema, _, sigla = (portal or "").partition(":")
    for t in lista:
        if t.sigla.upper() == sigla.upper():
            for alvo in (t, t.alternativo):
                if alvo is not None and alvo.sistema == sistema:
                    return alvo
    return None


def enderecos(portal: str) -> list[dict]:
    """Os endereços do portal ('esaj:TJAL'), grau a grau, para a tela de Ajustes:
    [{grau, rotulo, url, padrao, corrigido}] - 'padrao' é o do catálogo, 'url' o
    que vale (a correção do usuário, se houver)."""
    base = _do_portal(_carregar(str(ARQUIVO), _mtime(ARQUIVO)), portal)
    if base is None:
        raise KeyError(portal)
    locais = _ler_locais().get(base.portal, {})
    saida = []
    for grau in list(base.urls) + [g for g in locais if g not in base.urls]:
        valor = base.urls.get(grau, "")
        padrao = valor if isinstance(valor, str) else ", ".join(v for v in valor or [] if v)
        corrigido = str(locais.get(grau) or "")
        primeiro = valor if isinstance(valor, str) else next((v for v in valor or [] if v), "")
        saida.append({"grau": grau, "rotulo": rotulo_do_grau(grau), "url": corrigido or primeiro,
                      "padrao": padrao, "corrigido": bool(corrigido)})
    return saida


def enderecos_corrigidos() -> list[dict]:
    """[{portal, grau, rotulo, url}] - só o que o usuário corrigiu."""
    saida = []
    for portal, graus in sorted(_ler_locais().items()):
        if not isinstance(graus, dict):
            continue
        for grau, url in sorted(graus.items()):
            if isinstance(url, str) and url.strip():
                saida.append({"portal": portal, "grau": grau, "rotulo": rotulo_do_grau(grau),
                              "url": url.strip()})
    return saida


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
