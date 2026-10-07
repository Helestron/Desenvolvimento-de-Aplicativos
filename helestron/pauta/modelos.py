"""A audiência da pauta e a normalização do que vem dos portais e dos relatórios.

Cada portal escreve do seu jeito: "05/10/2026 14:30" numa célula só,
"05.10.26" e "14h30" em duas, "Audiência de Conciliação, Instrução e
Julgamento", "AUDIÊNCIA UNA", "Redesignada a pedido". Aqui tudo vira a
mesma coisa - data, "HH:MM", um dos tipos e uma das situações da seção 8.1
da especificação -, e o texto original fica guardado ao lado
(tipo_original, situacao_original), para ninguém perder informação.

A identidade da audiência (id) é estável: sha1 de sistema, tribunal,
processo, data, hora e tipo NORMALIZADOS. A mesma audiência lida de novo
amanhã (ou por outra tela do mesmo portal) cai no mesmo registro, e o que
mudar nela vira "alteração" - não uma audiência nova.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta

from ..nucleo import cnj

SISTEMAS = ("esaj", "eproc", "arquivo")
NOMES_SISTEMA = {"esaj": "e-SAJ", "eproc": "eProc", "arquivo": "Relatório importado"}
TIPOS = ("Conciliação", "Instrução e julgamento", "Una", "Custódia", "Justificação",
         "Mediação", "Outra")
SITUACOES = ("Designada", "Realizada", "Cancelada", "Redesignada", "Não realizada", "Suspensa")
# Situações em que a audiência não acontece (não contam em "hoje" nem em "próxima").
SEM_AUDIENCIA = ("Cancelada", "Redesignada")
JA_PASSOU = ("Realizada", "Não realizada")
MASCARA_SIGILO = "(segredo de justiça)"
# Os campos mascarados nos processos em segredo de justiça - os que identificam
# as partes (a planilha e a lista em JSON da linha de comando, salvo escolha do
# usuário): o portal costuma pôr nas observações o réu preso, a vítima, o advogado.
CAMPOS_MASCARADOS = ("partes", "observacoes")


def mascarar_sigiloso(a: dict) -> dict:
    """A audiência (dict da API) de um processo em segredo de justiça, numa
    cópia com as partes e as observações trocadas por MASCARA_SIGILO: as
    partes sempre (a coluna diz de quem é a audiência), as observações quando
    há alguma. A de processo público volta como está."""
    if not a.get("sigiloso"):
        return a
    a = dict(a)
    a["partes"] = MASCARA_SIGILO
    if a.get("observacoes"):
        a["observacoes"] = MASCARA_SIGILO
    return a


# Campos que, quando mudam, contam como alteração da audiência.
CAMPOS_COMPARADOS = ("processo", "data", "hora", "tipo", "situacao", "local", "link", "classe",
                     "partes", "magistrado", "observacoes")


@dataclass
class Audiencia:
    """Uma audiência da pauta (seção 8.1 da especificação)."""

    id: str
    sistema: str                # "esaj" | "eproc" | "arquivo"
    tribunal: str               # sigla (TJAL...) ou ""
    processo: str               # CNJ formatado; "" se não reconhecido
    data: date
    hora: str = ""              # "HH:MM" ou ""
    tipo: str = "Outra"
    situacao: str = "Designada"
    local: str = ""
    link: str = ""
    classe: str = ""
    partes: str = ""
    magistrado: str = ""
    sigiloso: bool = False
    observacoes: str = ""
    origem: str = ""            # URL ou arquivo de onde veio
    capturada_em: datetime = field(default_factory=lambda: datetime.now().replace(microsecond=0))
    tipo_original: str = ""
    situacao_original: str = ""
    fonte: str = ""             # id da fonte que a trouxe ("arquivo" na importação)

    @property
    def data_hora(self) -> str:
        """'2026-10-05 14:30' - para ordenar."""
        return f"{self.data.isoformat()} {self.hora or '99:99'}"


def gerar_id(sistema: str, tribunal: str, processo: str, data_: date, hora: str, tipo: str) -> str:
    """sha1(sistema|tribunal|processo|data|hora|tipo)[:16] - seção 8.1."""
    chave = "|".join([sistema or "", (tribunal or "").upper(), processo or "",
                      data_.isoformat() if isinstance(data_, date) else str(data_ or ""),
                      hora or "", tipo or ""])
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16]


def como_dict(a: Audiencia) -> dict:
    """A audiência para a API: data em ISO, hora "HH:MM", capturada_em em ISO."""
    d = asdict(a)
    d["data"] = a.data.isoformat()
    d["capturada_em"] = (a.capturada_em.isoformat(timespec="seconds")
                         if isinstance(a.capturada_em, datetime) else str(a.capturada_em or ""))
    return d


_NOMES_CAMPOS = {f.name for f in fields(Audiencia)}


def de_dict(d: dict) -> Audiencia:
    """O inverso de como_dict (o que o banco e a API guardam)."""
    dados = {k: v for k, v in dict(d).items() if k in _NOMES_CAMPOS}
    dados["data"] = ler_data(dados.get("data")) or date.today()
    momento = dados.get("capturada_em")
    if isinstance(momento, str):
        try:
            dados["capturada_em"] = datetime.fromisoformat(momento)
        except ValueError:
            dados["capturada_em"] = datetime.now().replace(microsecond=0)
    elif not isinstance(momento, datetime):
        dados["capturada_em"] = datetime.now().replace(microsecond=0)
    dados["sigiloso"] = bool(dados.get("sigiloso"))
    for nome in ("id", "sistema", "tribunal", "processo", "hora", "tipo", "situacao", "local",
                 "link", "classe", "partes", "magistrado", "observacoes", "origem",
                 "tipo_original", "situacao_original", "fonte"):
        dados[nome] = "" if dados.get(nome) is None else str(dados.get(nome))
    if not dados["id"]:
        dados["id"] = gerar_id(dados["sistema"], dados["tribunal"], dados["processo"],
                               dados["data"], dados["hora"], dados["tipo"])
    return Audiencia(**dados)


# ================================================================== textos
def sem_acento(texto) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto or ""))
                   if not unicodedata.combining(c))


_ESPACOS = re.compile(r"\s+")
# Os caracteres de controle que não são espaço (os outros viram espaço em
# _ESPACOS): chegam do PDF, do HTML, do CSV e do XLS e o Excel não os aceita.
_CONTROLE = re.compile(r"[\x00-\x08\x0e-\x1b\x7f]")


def limpar(texto) -> str:
    """Espaços colapsados (inclusive o &nbsp; das tabelas do portal), sem
    caracteres de controle."""
    return _ESPACOS.sub(" ", _CONTROLE.sub("", str(texto or "")).replace("\xa0", " ")).strip()


def normalizar_texto(texto) -> str:
    """Minúsculas, sem acento, sem 'º'/'ª', espaços colapsados, sem ':' no fim.

    É a forma em que cabeçalhos, menus e situações são comparados: "Nº do
    Processo:" e "n do processo" são a mesma coisa.
    """
    t = str(texto or "").replace("º", "").replace("°", "").replace("ª", "")
    t = sem_acento(t).lower()
    t = re.sub(r"(?<=\b[a-z])\.(?=\s|$)", "", t)        # "n. do processo" -> "n do processo"
    t = limpar(t)
    return t.strip(" :;,.-*").strip()


# =================================================================== datas
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
         "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
         "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
         "set": 9, "out": 10, "nov": 11, "dez": 12}
DIAS_DA_SEMANA = ("Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira",
                  "Sábado", "Domingo")
NOMES_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
               "setembro", "outubro", "novembro", "dezembro")

_RE_DATA_BR = re.compile(r"(?<!\d)(\d{1,2})\s*([/.\-])\s*(\d{1,2})\s*\2\s*(\d{4}|\d{2})(?!\d)")
_RE_DATA_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_RE_DATA_EXTENSO = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:de\s+|/\s*)?(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro|jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\.?"
    r"\s*(?:de\s+|/\s*)?(\d{4})(?!\d)", re.I)
_RE_HORA = re.compile(r"(?<![\d/.:])([01]?\d|2[0-3])\s*(?::|h|hs|H)\s*([0-5]\d)(?:\s*:\s*[0-5]\d)?"
                      r"(?!\s*[/.]\d)(?![\d])")
_RE_HORA_CHEIA = re.compile(r"(?<![\d/.:])([01]?\d|2[0-3])\s*(?:h|hs)(?![\w])", re.I)

ANO_MIN, ANO_MAX = 1990, 2100
# Número de série do Excel (dias desde 30/12/1899) que cabe numa data de audiência.
SERIE_MIN, SERIE_MAX = 32874, 73051      # 1990-01-01 .. 2099-12-31


def _data_valida(ano: int, mes: int, dia: int) -> date | None:
    if not ANO_MIN <= ano <= ANO_MAX:
        return None
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _ano(texto: str) -> int:
    ano = int(texto)
    if len(texto) == 2:
        # "05/10/26": a pauta é deste século (e não de 1926)
        ano += 2000 if ano < 70 else 1900
    return ano


def ler_data(valor) -> date | None:
    """A data de uma célula: datetime/date, número de série do Excel ou texto.

    Texto: dd/mm/aaaa, dd/mm/aa, dd.mm.aaaa, dd-mm-aaaa, ISO (aaaa-mm-dd) e
    por extenso ("5 de outubro de 2026", "05/out/2026"). Devolve a PRIMEIRA
    data válida do texto; None se não houver.
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, datetime):
        return valor.date() if ANO_MIN <= valor.year <= ANO_MAX else None
    if isinstance(valor, date):
        return valor if ANO_MIN <= valor.year <= ANO_MAX else None
    if isinstance(valor, (int, float)):
        if SERIE_MIN <= float(valor) <= SERIE_MAX:
            return date(1899, 12, 30) + timedelta(days=int(float(valor)))
        return None
    texto = str(valor)
    candidatos: list[tuple[int, date]] = []
    for m in _RE_DATA_ISO.finditer(texto):
        d = _data_valida(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            candidatos.append((m.start(), d))
    for m in _RE_DATA_BR.finditer(texto):
        d = _data_valida(_ano(m.group(4)), int(m.group(3)), int(m.group(1)))
        if d:
            candidatos.append((m.start(), d))
    if not candidatos:
        sem = sem_acento(texto).lower()
        for m in _RE_DATA_EXTENSO.finditer(sem):
            d = _data_valida(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))
            if d:
                candidatos.append((m.start(), d))
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: c[0])[1]


def ler_hora(valor) -> str:
    """'HH:MM' de uma célula: time/datetime, fração de dia do Excel ou texto.

    Texto: 14:30, 14:30:00, 14h30, 14 h 30, 9h (hora cheia). "" se não houver.
    O texto de uma data (05.10.2026) não é lido como hora.
    """
    if valor is None or isinstance(valor, bool):
        return ""
    if isinstance(valor, datetime):
        return f"{valor.hour:02d}:{valor.minute:02d}" if (valor.hour or valor.minute) else ""
    if isinstance(valor, time):
        return f"{valor.hour:02d}:{valor.minute:02d}"
    if isinstance(valor, date):
        return ""
    if isinstance(valor, (int, float)):
        v = float(valor)
        if 0 <= v < 1:
            minutos = int(round(v * 1440)) % 1440
            return f"{minutos // 60:02d}:{minutos % 60:02d}"
        return ""
    texto = str(valor)
    # tira as datas antes: "05.10.2026" teria um "10.20" no meio
    texto = _RE_DATA_BR.sub(" ", _RE_DATA_ISO.sub(lambda m: " ", texto))
    m = _RE_HORA.search(texto)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    m = _RE_HORA_CHEIA.search(texto)
    if m:
        return f"{int(m.group(1)):02d}:00"
    return ""


def ler_data_hora(valor) -> tuple[date | None, str]:
    """Célula com data e hora juntas ("05/10/2026 14:30", "2026-10-05T14:30")."""
    if isinstance(valor, datetime):
        return ler_data(valor), ler_hora(valor)
    data_ = ler_data(valor)
    if isinstance(valor, str) and "T" in valor and _RE_DATA_ISO.search(valor):
        valor = valor.replace("T", " ")
    return data_, ler_hora(valor) if isinstance(valor, str) else ""


def dia_da_semana(d: date) -> str:
    return DIAS_DA_SEMANA[d.weekday()]


def data_por_extenso(d: date) -> str:
    """'Segunda-feira, 5 de outubro' (cabeçalho do dia, como na tela)."""
    return f"{dia_da_semana(d)}, {d.day} de {NOMES_MESES[d.month - 1]}"


# ============================================================ tipo e situação
def normalizar_tipo(texto, regras=None) -> str:
    """Um dos TIPOS da especificação, pelo texto que o portal mostra."""
    from . import regras as _regras

    r = regras or _regras.carregar()
    alvo = normalizar_texto(texto)
    if not alvo:
        return r.tipo_padrao
    for rotulo, padrao in r.tipos:
        if padrao.search(alvo):
            return rotulo
    return r.tipo_padrao


def normalizar_situacao(texto, regras=None) -> str:
    """Uma das SITUACOES da especificação; vazio ou desconhecido = Designada.

    A ordem das regras importa e está no pauta.json: "Não realizada" antes
    de "Realizada", "Redesignada" antes de "Designada".
    """
    from . import regras as _regras

    r = regras or _regras.carregar()
    alvo = normalizar_texto(texto)
    if alvo:
        for rotulo, padrao in r.situacoes:
            if padrao.search(alvo):
                return rotulo
    return r.situacao_padrao


def situacao_reconhecida(texto, regras=None) -> str:
    """Como normalizar_situacao, mas "" quando o texto não diz situação nenhuma."""
    from . import regras as _regras

    r = regras or _regras.carregar()
    alvo = normalizar_texto(texto)
    if not alvo:
        return ""
    for rotulo, padrao in r.situacoes:
        if padrao.search(alvo):
            return rotulo
    return ""


# ================================================================== processo
def ler_processo(valor) -> tuple[str, bool]:
    """(CNJ formatado, confiável) de uma célula. ("", True) se não houver número.

    Célula NUMÉRICA de planilha só vale com o dígito verificador conferindo
    (o Excel corrompe os últimos dígitos de um CNJ guardado como número - a
    mesma regra de nucleo/listas.py): sem isso, a audiência iria para o
    processo de outra pessoa. 'confiável' = False nesse caso.
    """
    if valor is None or isinstance(valor, bool):
        return "", True
    numerico = isinstance(valor, (int, float))
    if numerico:
        if isinstance(valor, float) and (valor != valor or int(valor) != valor):
            return "", True
        digitos = str(abs(int(valor)))
        if len(digitos) == 19:
            digitos = "0" + digitos          # o Excel comeu o zero da frente
        texto = digitos
    else:
        texto = str(valor)
    achados = cnj.extrair_todos(texto)
    if not achados:
        return "", True
    n = achados[0]
    if numerico and not n.digito_confere:
        return "", False
    return n.formatado, True


def tribunal_do_processo(processo: str) -> str:
    """A sigla do tribunal pelo próprio número (8.02 -> TJAL), ou ""."""
    if not processo:
        return ""
    try:
        from ..nucleo import tribunais

        t = tribunais.por_numero(cnj.ler(processo))
    except Exception:
        return ""
    return t.sigla if t is not None else ""


def chave_processo(processo: str) -> str:
    """Identidade do processo (dígitos + dependente) para comparar grafias."""
    try:
        return cnj.chave(cnj.ler(processo))
    except cnj.NumeroInvalido:
        return ""


def parear_mesmo_horario(uns: list[Audiencia], outros: list[Audiencia],
                         reserva: list[Audiencia] | None = None
                         ) -> list[tuple[Audiencia, Audiencia]]:
    """Os pares (de 'uns', de 'outros') que são a mesma audiência, entre registros
    do MESMO processo, data e hora vindos de dois lugares (o portal e o
    relatório importado).

    Um a um: primeiro o do mesmo tipo (havendo mais de um, o da mesma situação);
    o que sobrar só se pareia se sobrar um de cada lado - com duas audiências do
    processo no mesmo horário (uma Conciliação cancelada e uma Instrução
    designada), cada uma fica com a sua. 'reserva': os de 'uns' que só valem
    para o mesmo tipo (já pareados antes, numa outra importação ou
    sincronização), e não para a sobra.
    """
    livres = list(outros)
    pares: list[tuple[Audiencia, Audiencia]] = []
    sobra: list[Audiencia] = []
    for um in uns:
        mesmo_tipo = [o for o in livres if o.tipo == um.tipo]
        if not mesmo_tipo:
            if not any(um is x for x in (reserva or ())):
                sobra.append(um)
            continue
        par = next((o for o in mesmo_tipo if o.situacao == um.situacao), mesmo_tipo[0])
        livres = [o for o in livres if o is not par]
        pares.append((um, par))
    if len(sobra) == 1 and len(livres) == 1:
        pares.append((sobra[0], livres[0]))
    return pares


# ================================================================== montagem
def nova(*, sistema: str, tribunal: str, data_: date, processo: str = "", hora: str = "",
         tipo_original: str = "", situacao_original: str = "", regras=None,
         **outros) -> Audiencia:
    """Monta a audiência já normalizada e com o id estável."""
    tipo = normalizar_tipo(tipo_original, regras)
    situacao = normalizar_situacao(situacao_original, regras)
    hora = ler_hora(hora) if hora else ""
    tribunal = (tribunal or "").upper()
    texto = {k: limpar(v) for k, v in outros.items()
             if k in ("local", "link", "classe", "partes", "magistrado", "observacoes", "origem",
                      "fonte")}
    a = Audiencia(id=gerar_id(sistema, tribunal, processo, data_, hora, tipo), sistema=sistema,
                  tribunal=tribunal, processo=processo, data=data_, hora=hora, tipo=tipo,
                  situacao=situacao, tipo_original=limpar(tipo_original),
                  situacao_original=limpar(situacao_original),
                  sigiloso=bool(outros.get("sigiloso")), **texto)
    if isinstance(outros.get("capturada_em"), datetime):
        a.capturada_em = outros["capturada_em"].replace(microsecond=0)
    return a


def com_novo_id(a: Audiencia) -> Audiencia:
    """Recalcula o id (depois de mudar sistema, tribunal, data, hora ou tipo)."""
    a.id = gerar_id(a.sistema, a.tribunal, a.processo, a.data, a.hora, a.tipo)
    return a


def valor_para_comparar(a: Audiencia | dict, campo: str) -> str:
    valor = a.get(campo) if isinstance(a, dict) else getattr(a, campo, "")
    if isinstance(valor, date):
        return valor.isoformat()
    return "" if valor is None else str(valor)
