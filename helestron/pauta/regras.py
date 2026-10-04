"""As regras da pauta: sinônimos de cabeçalho, tipos, situações, menus e rotas.

Moram em dados/pauta.json, editável: se o portal trocar "Pauta de
Audiências" por "Agenda de audiências", ou a coluna "Data/Hora" por "Quando",
ajusta-se ali, sem mexer no programa (como o tribunais.json do download).

As mesmas regras estão embutidas aqui (PADROES). Elas valem quando o arquivo
falta ou foi estragado por uma edição à mão - a pauta continua funcionando,
e o registro diz o que houve. O que o arquivo traz substitui o embutido
chave a chave; um teste confere que os dois andam iguais.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..nucleo import caminhos

log = logging.getLogger("pauta.regras")

ARQUIVO = Path(caminhos.DADOS) / "pauta.json"

PADROES: dict = {
    "versao": 1,
    "cabecalhos": {
        "data": ["data", "dia", "data/hora", "data / hora", "data - hora", "data e hora",
                 "data hora", "data da audiencia", "data audiencia", "dt audiencia", "dt. audiencia",
                 "data designada", "data de realizacao", "data/hora da audiencia",
                 "data e hora da audiencia", "data/horario", "data e horario"],
        "hora": ["hora", "horario", "inicio", "hora inicio", "hora de inicio", "hora da audiencia",
                 "horario da audiencia", "hr", "hora/inicio"],
        "processo": ["processo", "numero", "numero do processo", "n do processo", "no do processo",
                     "num processo", "numero processo", "n processo", "autos", "n dos autos",
                     "processo/classe", "processo judicial", "numero dos autos", "processo n"],
        "tipo": ["tipo", "tipo de audiencia", "tipo da audiencia", "tipo audiencia", "natureza",
                 "audiencia", "especie", "finalidade", "tipo/natureza"],
        "situacao": ["situacao", "status", "andamento", "situacao da audiencia", "estado",
                     "status da audiencia"],
        "local": ["local", "sala", "vara", "orgao", "orgao julgador", "unidade", "juizo",
                  "local da audiencia", "foro", "sala de audiencia", "sala de audiencias"],
        "classe": ["classe", "classe processual", "classe judicial", "classe do processo"],
        "partes": ["partes", "parte", "envolvidos", "interessados", "nome das partes",
                   "partes do processo"],
        "autor": ["autor", "autores", "requerente", "requerentes", "polo ativo", "reclamante",
                  "exequente", "promovente", "parte autora", "ativo", "vitima"],
        "reu": ["reu", "reus", "requerido", "requeridos", "polo passivo", "reclamado", "executado",
                "promovido", "parte re", "passivo", "acusado", "denunciado", "investigado"],
        "magistrado": ["magistrado", "magistrada", "juiz", "juiza", "juiz(a)", "conciliador",
                       "conciliadora", "conciliador(a)", "responsavel", "presidente", "mediador",
                       "magistrado/conciliador", "presidida por"],
        "link": ["link", "link da audiencia", "link da sala", "url", "sala virtual",
                 "endereco virtual", "videoconferencia", "link de acesso", "acesso virtual"],
        "observacoes": ["observacoes", "observacao", "obs", "complemento", "detalhes", "anotacoes"],
        "sigilo": ["sigilo", "segredo", "segredo de justica", "sigiloso", "nivel de sigilo"],
        "tribunal": ["tribunal"],
    },
    "ignorar_cabecalhos": ["dia da semana", "dia semana", "sistema", "ordem", "seq", "sequencia",
                           "item", "acoes", "opcoes", "selecionar", "marcar"],
    "tipos": [
        ["Custódia", "custodia|apresentacao do preso|audiencia de apresentacao"],
        ["Una", "\\buna\\b|concilia\\w*,?\\s+(e\\s+)?instru"],
        ["Conciliação", "concilia"],
        ["Mediação", "\\bmedia(cao|dor|dora)\\b|cejusc"],
        ["Justificação", "justifica"],
        ["Instrução e julgamento",
         "instru|julgamento|\\boitiva|depoimento|interrogatorio|\\bjuri\\b"],
    ],
    "tipo_padrao": "Outra",
    "situacoes": [
        ["Não realizada",
         "nao[\\s-]*realizad|frustrad|prejudicad|nao ocorr|nao houve|nao compareci|ausencia d"],
        ["Redesignada", "redesigna|remarcad|adiad|reagendad|transferid"],
        ["Cancelada", "cancelad|cancelament|desmarcad|retirad[ao] de pauta|excluid|sem efeito"],
        ["Suspensa", "suspens|sobrestad"],
        ["Realizada", "realizad|concluid|cumprid|encerrad|ocorrid|finalizad"],
        ["Designada", "designad|agendad|marcad|pendente|a realizar|aguardando|confirmad|prevista|"
                      "em aberto|aberta"],
    ],
    "situacao_padrao": "Designada",
    "sigilo": "segredo de justica|sigilos[oa]|\\bem sigilo\\b|sigilo\\s*\\(?\\s*nivel\\s*[1-9]|"
              "nivel\\s*[1-9]",
    "sem_sigilo": "sem sigilo|nivel\\s*0|nao sigilos|\\bpublic[oa]\\b",
    "negativos": ["prazo", "evento", "intimac", "movimentac", "publicac", "expedi", "peticao",
                  "documento", "distribuic", "conclus", "juntada", "mandado", "citac", "remessa"],
    "contexto_audiencia": "audienc|pauta",
    "link_virtual": "teams\\.microsoft|teams\\.live|meet\\.google|zoom\\.us|webex|whereby|jitsi|"
                    "videoconferencia|sala.?virtual|balcao.?virtual|\\bvirtual\\b",
    "legenda_total": ["\\((\\d+)\\s+registros?", "(\\d+)\\s+registro\\(s\\)",
                      "total(?:\\s+de\\s+registros)?\\s*:?\\s*(\\d+)",
                      "(\\d+)\\s+audiencias?\\s+encontrad", "encontrad[ao]s?\\s*:?\\s*(\\d+)"],
    "menu": {
        "procurar": [
            ["pauta d[ea]s? audiencias?", 100],
            ["agenda d[ea]s? audiencias?", 90],
            ["gerenciar audiencias?|gerenciamento de audiencias?", 85],
            ["consultar audiencias?|consulta de audiencias?", 80],
            ["audiencias? (designadas|agendadas|marcadas)", 75],
            ["relatorio de audiencias?|audiencias? do periodo", 70],
            ["\\bpauta\\b", 60],
            ["\\baudienci", 40],
        ],
        "excluir": "designar|redesignar|cadastr|incluir|\\bnova\\b|\\bnovo\\b|excluir|cancelar|"
                   "alterar|editar|remarcar|agendar|realizar|registrar|\\bata\\b|\\btermo\\b|"
                   "minuta|gravac|\\bvideo|\\bsair\\b|ajuda|manual|tutorial|pauta de julgamento|"
                   "sessao de julgamento|\\bmedia\\b",
        "paginas": {"esaj": ["/esaj/portal.do", "/"], "eproc": []},
        "max_paginas_visitadas": 8,
    },
    "rotas": {
        "esaj": [],
        "eproc": ["audiencia_pauta", "audiencia_listar", "audiencia_consultar",
                  "pauta_audiencia_listar", "relatorio_audiencias", "audiencias_listar"],
        "tribunais": {},
    },
    "periodo": {
        "data": "data|\\bdt|periodo|\\bde\\b|\\bate\\b|inicio|inicial|final|\\bfim\\b|dd/mm",
        "inicio": "ini(cio|cial)?\\b|ini[a-z]*$|dt\\w*ini|data\\w*ini|\\bde\\b|desde|\\bfrom\\b|"
                  "periodo\\s*de",
        "fim": "\\bfi(m|nal)\\b|fi(m|nal)$|dt\\w*fi[mn]|data\\w*fi[mn]|\\bate\\b|termino|\\bto\\b|"
               "periodo\\s*ate",
        "botao": "pesquisar|consultar|filtrar|buscar|listar|exibir|gerar|aplicar|atualizar|^ok$|"
                 "procurar|ver pauta",
    },
    "paginacao": {
        "proxima": "^(proxim[ao]|seguinte|avancar|next)(\\s+pagina)?\\s*[>»›]*$|^[>»›]{1,2}$|"
                   "^proxima\\s+pagina$|pagina seguinte",
        "limite_paginas": 50,
    },
}


def _mesclar(base: dict, extra: dict) -> dict:
    """O que o arquivo traz substitui o embutido; dicionários, chave a chave."""
    saida = copy.deepcopy(base)
    for chave, valor in (extra or {}).items():
        if chave.startswith("_"):
            continue
        if isinstance(valor, dict) and isinstance(saida.get(chave), dict):
            saida[chave] = _mesclar(saida[chave], valor)
        else:
            saida[chave] = copy.deepcopy(valor)
    return saida


def _regex(padrao, nome: str, reserva: str) -> re.Pattern:
    """Compila; padrão estragado por edição à mão vira o embutido (e o aviso)."""
    try:
        return re.compile(str(padrao), re.I)
    except re.error as erro:
        log.warning("pauta.json: o padrão de %s é inválido (%s); usei o embutido.", nome, erro)
        return re.compile(reserva, re.I)


@dataclass
class Regras:
    """As regras já compiladas, prontas para o reconhecimento e a navegação."""

    dados: dict
    problema: str = ""          # por que o arquivo não pôde ser lido ("" se pôde)
    cabecalhos: dict[str, list[str]] = field(default_factory=dict)
    ignorar: set[str] = field(default_factory=set)
    tipos: list[tuple[str, re.Pattern]] = field(default_factory=list)
    situacoes: list[tuple[str, re.Pattern]] = field(default_factory=list)
    sigilo: re.Pattern | None = None
    sem_sigilo: re.Pattern | None = None
    link_virtual: re.Pattern | None = None
    contexto_audiencia: re.Pattern | None = None
    legenda_total: list[re.Pattern] = field(default_factory=list)
    menu_procurar: list[tuple[re.Pattern, int]] = field(default_factory=list)
    menu_excluir: re.Pattern | None = None

    def __post_init__(self) -> None:
        d, p = self.dados, PADROES
        from .modelos import normalizar_texto   # sem ciclo: modelos não importa regras no topo

        self.cabecalhos = {campo: [normalizar_texto(s) for s in (lista or [])]
                           for campo, lista in (d.get("cabecalhos") or {}).items()}
        self.ignorar = {normalizar_texto(s) for s in d.get("ignorar_cabecalhos") or []}
        self.tipos = self._pares(d.get("tipos"), p["tipos"], "tipos")
        self.situacoes = self._pares(d.get("situacoes"), p["situacoes"], "situacoes")
        for nome in ("sigilo", "sem_sigilo", "link_virtual", "contexto_audiencia"):
            setattr(self, nome, _regex(d.get(nome, p[nome]), nome, p[nome]))
        self.legenda_total = [_regex(x, "legenda_total", "(?!x)x")
                              for x in d.get("legenda_total") or p["legenda_total"]]
        menu = d.get("menu") or {}
        self.menu_procurar = []
        for item in menu.get("procurar") or p["menu"]["procurar"]:
            try:
                padrao, peso = item[0], int(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            self.menu_procurar.append((_regex(padrao, "menu.procurar", "(?!x)x"), peso))
        self.menu_excluir = _regex(menu.get("excluir", p["menu"]["excluir"]), "menu.excluir",
                                   p["menu"]["excluir"])

    @staticmethod
    def _pares(lista, reserva, nome: str) -> list[tuple[str, re.Pattern]]:
        saida = []
        for item in lista or reserva:
            try:
                rotulo, padrao = str(item[0]), item[1]
            except (TypeError, IndexError):
                continue
            saida.append((rotulo, _regex(padrao, nome, "(?!x)x")))
        return saida or [(str(r), re.compile(x, re.I)) for r, x in reserva]

    # ------------------------------------------------------------ atalhos
    @property
    def tipo_padrao(self) -> str:
        return str(self.dados.get("tipo_padrao") or "Outra")

    @property
    def situacao_padrao(self) -> str:
        return str(self.dados.get("situacao_padrao") or "Designada")

    @property
    def negativos(self) -> list[str]:
        from .modelos import normalizar_texto

        return [normalizar_texto(x) for x in self.dados.get("negativos") or []]

    @property
    def periodo(self) -> dict[str, str]:
        return {**PADROES["periodo"], **(self.dados.get("periodo") or {})}

    @property
    def proxima(self) -> str:
        return str((self.dados.get("paginacao") or {}).get("proxima")
                   or PADROES["paginacao"]["proxima"])

    @property
    def limite_paginas(self) -> int:
        try:
            return max(1, int((self.dados.get("paginacao") or {}).get("limite_paginas", 50)))
        except (TypeError, ValueError):
            return 50

    @property
    def max_paginas_visitadas(self) -> int:
        try:
            return max(1, int((self.dados.get("menu") or {}).get("max_paginas_visitadas", 8)))
        except (TypeError, ValueError):
            return 8

    def paginas_de_menu(self, sistema: str) -> list[str]:
        paginas = (self.dados.get("menu") or {}).get("paginas") or {}
        return [str(x) for x in paginas.get(sistema) or [] if str(x).strip()]

    def rotas(self, sistema: str, tribunal: str = "") -> list[str]:
        """As rotas conhecidas: as do tribunal primeiro, depois as do sistema."""
        rotas = self.dados.get("rotas") or {}
        proprias = ((rotas.get("tribunais") or {}).get((tribunal or "").upper()) or {})
        saida: list[str] = []
        for x in list(proprias.get(sistema) or []) + list(rotas.get(sistema) or []):
            x = str(x).strip()
            if x and x not in saida:
                saida.append(x)
        return saida


def _ler(arquivo: Path) -> tuple[dict, str]:
    try:
        dados = arquivo.read_bytes()
    except FileNotFoundError:
        return {}, f"o arquivo {arquivo.name} não existe"
    except OSError as erro:
        return {}, f"o arquivo {arquivo.name} não pôde ser aberto ({erro.strerror or erro})"
    try:
        try:
            texto = dados.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = dados.decode("cp1252", errors="replace")   # Bloco de Notas antigo
        conteudo = json.loads(texto)
        if not isinstance(conteudo, dict):
            raise ValueError("o conteúdo não é um objeto JSON")
    except json.JSONDecodeError as erro:
        return {}, (f"o arquivo {arquivo.name} tem erro de formatação na linha {erro.lineno}, "
                    f"coluna {erro.colno}")
    except ValueError as erro:
        return {}, f"o arquivo {arquivo.name} é inválido ({erro})"
    return conteudo, ""


@lru_cache(maxsize=4)
def _carregar(arquivo: str, _mtime: float) -> Regras:
    extra, problema = _ler(Path(arquivo))
    if problema:
        log.warning("Regras da pauta: %s; usei as regras embutidas no programa.", problema)
    return Regras(_mesclar(PADROES, extra), problema)


def carregar(arquivo: Path | str | None = None) -> Regras:
    """As regras em vigor (relidas quando o arquivo muda)."""
    p = Path(arquivo or ARQUIVO)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _carregar(str(p), mtime)


def de_dicionario(extra: dict | None = None) -> Regras:
    """Regras montadas na hora (testes e ajustes pontuais): embutidas + extra."""
    return Regras(_mesclar(PADROES, extra or {}))
