"""Portal e-SAJ (Softplan): login e download do PDF único de cada processo.

Porte do Assessor SAJ - login de app/esaj/navegador.py e download de
app/esaj/baixador.py -, que funcionava no TJAL. O motor do e-SAJ é o mesmo
em todos os tribunais que o usam (TJSP, TJMS, TJCE, TJAC, TJAM, TJAL): muda
só o endereço, que vem do catálogo (dados/tribunais.json).

O que foi corrigido em relação à base (cada item apanhado em uso real ou
na leitura do código):

* o foro do processo vinha FIXO (processo.foro=56) na abertura de
  incidentes; agora vem do próprio número (OOOO);
* o PDF era gravado direto sobre o anterior (queda no meio = autos
  corrompidos); agora a gravação é atômica;
* se o servidor não montasse o PDF único, o processo ficava sem autos;
  agora ele é montado peça a peça (getPDF.do);
* a página N do PDF é SEMPRE a folha N da Pasta Digital: a folha que não
  veio (não oferecida, peça que não baixou, arquivo inválido ou com páginas
  a menos) tem uma página de aviso no lugar, uma por folha, e o manifesto
  de paginação (nucleo.paginacao) vai dentro do PDF dizendo quais e por
  quê; o PDF do servidor que não confere com o índice nunca é gravado - o
  processo é montado peça a peça;
* erro 5xx e tempo esgotado não eram repetidos; agora são, com espera
  crescente, antes de trocar de canal;
* a checagem de segredo custava ~4,8 s em TODO processo; agora espera a
  página carregar e olha uma vez (mais uma, 0,6 s depois);
* o código de verificação chegava por arquivo e a tela o pedia lendo o
  texto do log; agora é pedido por Contexto.pedir_codigo;
* "Não existem informações disponíveis" (a frase real do portal para
  número inexistente) não era reconhecida, e o processo inexistente virava
  "sem acesso", novo login e nova tentativa; agora vira NAO_ENCONTRADO;
* senha errada só era percebida depois de esperar 45 s pela tela do código.

Nada de dossiê, OCR, anonimizador ou índice da triagem: o produto aqui é o
PDF único. De acessório fica só a capa (_controle/<número>_capa.txt, e o
mesmo em _capa.json para máquina), que é barata - sai da página do processo
que o download já abre - e dá à IA classe, partes, juiz, marcas (prioridade,
justiça gratuita...), todas as movimentações, incidentes, audiências e as
folhas do PDF sem abrir o portal nem o PDF.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..nucleo import caminhos, paginacao, sistema
from ..nucleo.cnj import Numero
from . import pdf
from .contexto import Contexto
from .modelos import (AJUSTES_ACESSOS, CAMPO_PRAZO_LOGIN, ENTRAR_MANUALMENTE,
                      MOSTRAR_NAVEGADOR, OK, ONDE_CADASTRAR_ACESSO, TENTAR_DE_NOVO, Cancelado,
                      LoginFalhou, NAO_ENCONTRADO, PortalIndisponivel, ProcessoNaoEncontrado,
                      ResultadoProcesso, SEM_ACESSO, SemAcesso, SessaoPerdida,
                      SIGILOSO_SEM_SENHA, SigilosoSemSenha)
from .navegador import (DICA_DIAGNOSTICO, DICA_SEM_DIAGNOSTICO, diagnosticar_processo,
                        explicar_erro, primeiro_visivel, recusou_credenciais, sem_acento,
                        tem_web_signer)

log = logging.getLogger("download.esaj")

# Porta de entrada do portal. Com "gateway=true" o próprio e-SAJ manda para
# a tela de login quando ainda não há sessão, e volta sozinho para a
# consulta quando já há.
URL_ENTRADA = "{base}/cpopg/open.do?servico=190101&gateway=true"
ESPERA_PDF_S = 600            # até 10 min para o servidor montar um PDF grande
INTERVALO_POLL_S = 3
ESPERA_CONFIRMA_CODIGO_S = 25
MAX_PECAS_SEGUIDAS_FALHANDO = 5   # peça a peça: desiste se as primeiras não vêm

SELETORES_PADRAO: dict[str, list[str]] = {
    "login_usuario": ["#usernameForm", "input[name='username']", "#username",
                      "input[name='usuario']"],
    "login_senha": ["#passwordForm", "input[name='password']", "#password",
                    "input[name='senha']", "input[type='password']"],
    "login_botao": ["#pbEntrar", "input[type='submit'][value*='Entrar']",
                    "button:has-text('Entrar')", "input[name='submit']"],
    "logado": ["#usuarioLogado", ".usuario-logado"],
    "login_token": ["#tokenInformado", "input[name='tokenInformado']",
                    "#modalTokenDuploFator input[type='text']"],
    "login_token_enviar": ["#btnEnviarToken", "#modalTokenDuploFator button:has-text('Enviar')"],
    "login_token_novo": ["#btnReceberToken",
                         "#modalTokenDuploFator button:has-text('Receber novo')"],
    "login_senha_expirada": ["#modalSenhaExpirada"],
    "processo_senha": ["#senhaProcesso"],
    "processo_senha_enviar": ["#btEnviarSenha"],
}


def arquivos_de_seletores(*nomes: str) -> list[Path]:
    """Onde se lê a correção dos seletores, da reserva para a que vale mais.

    A correção mora na pasta de dados do Helestron (%LOCALAPPDATA%\\Helestron,
    como o enderecos-locais.json): a pasta do programa é trocada inteira a
    cada atualização, e a correção sumiria com ela. A de dentro do programa
    (dados\\) ainda é lida, de reserva, para a que vier numa versão nova.
    """
    nomes = nomes or ("seletores.json",)
    return [*(caminhos.DADOS / n for n in nomes), *(caminhos.LOCAL / n for n in nomes)]


def carregar_seletores(arquivo: Path | None = None) -> dict[str, list[str]]:
    """Seletores padrão, com os do usuário na frente (seletores.json).

    Formato: {"esaj": {"login_usuario": ["#novoCampo"], ...}}. Serve para
    o dia em que o portal mudar um campo de lugar: corrige-se no arquivo
    seletores.json da pasta de dados do Helestron, sem esperar nova versão
    do programa. Os padrões ficam atrás, de reserva.
    """
    sel = {k: list(v) for k, v in SELETORES_PADRAO.items()}
    fontes = [Path(arquivo)] if arquivo else arquivos_de_seletores("seletores.json")
    for alvo in fontes:
        try:
            dados = json.loads(alvo.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as erro:
            log.warning("%s ilegível (%s); uso os seletores padrão.", alvo, erro)
            continue
        if not isinstance(dados, dict):
            continue
        for chave, lista in (dados.get("esaj") or {}).items():
            if isinstance(lista, str):
                lista = [lista]
            if isinstance(lista, list):
                proprios = [s for s in lista if isinstance(s, str) and s.strip()]
                sel[chave] = proprios + [s for s in sel.get(chave, []) if s not in proprios]
    return sel


# ======================================================== funções puras
_RE_CODIGO = re.compile(r"processo\.codigo=([A-Z0-9]+)")


def foro_sem_zeros(numero: Numero) -> str:
    return numero.origem.lstrip("0") or "0"


def url_busca(base: str, numero: Numero) -> str:
    """Consulta do CPOPG pelo número unificado (foro vindo do próprio número)."""
    consulta = [
        ("conversationId", ""), ("cbPesquisa", "NUMPROC"),
        ("numeroDigitoAnoUnificado", numero.unificado),
        ("foroNumeroUnificado", numero.foro),
        ("dadosConsulta.valorConsultaNuUnificado", numero.principal),
        ("dadosConsulta.valorConsultaNuUnificado", "UNIFICADO"),
        ("dadosConsulta.valorConsulta", ""),
        ("dadosConsulta.tipoNuProcesso", "UNIFICADO"),
    ]
    return f"{base}/cpopg/search.do?" + urllib.parse.urlencode(consulta)


def url_processo(base: str, codigo: str, numero: Numero | None = None,
                 foro: str | None = None) -> str:
    """A página do processo (show.do). O foro sai do número - na base ele
    estava fixo em 56, e só funcionava porque o código interno manda."""
    partes = [f"processo.codigo={codigo}"]
    foro = foro or (foro_sem_zeros(numero) if numero is not None else "")
    if foro:
        partes.append(f"processo.foro={foro}")
    if numero is not None and not numero.e_dependente:
        partes.append(f"processo.numero={numero.principal}")
    return f"{base}/cpopg/show.do?" + "&".join(partes)


def codigo_incidente(cd_principal: str, ordem: int) -> str:
    """O código do incidente é o do principal com os 4 últimos dígitos
    trocados pela ordem: 1K0000RXW0000 -> 1K0000RXW0001."""
    if not cd_principal or len(cd_principal) <= 4:
        raise ValueError(f"código de processo inesperado: {cd_principal!r}")
    return cd_principal[:-4] + f"{int(ordem):04d}"


def marca_do_incidente(ordem: int) -> "re.Pattern[str]":
    """Como a página do principal se refere ao incidente de ordem N:
    "(01)", "00001", "/0001" e, colado ao número do processo, "...0001/01"
    ou "...0001/1" - mas não "/0100" nem "/10".

    O "/01" solto NÃO vale: o texto da linha do incidente traz datas
    ("Recebido em 15/01/2024"), e "/01" casaria com qualquer data de
    janeiro - o programa abriria OUTRO incidente e gravaria autos trocados
    com o nome deste. Por isso a forma curta só conta logo depois dos 4
    dígitos do foro, e nunca seguida de outra barra (como numa data).
    """
    n = int(ordem)
    return re.compile(rf"\(0*{n:02d}\)|(?<!\d)0*{n:05d}(?!\d)"
                      rf"|/0*{n:04d}(?![\d/])|(?<=\d{{4}})/0*{n}(?![\d/])")


def codigo_na(texto: str) -> str | None:
    m = _RE_CODIGO.search(texto or "")
    return m.group(1) if m else None


_FRASES_NAO_ENCONTRADO = ("nao existem informacoes disponiveis", "nao encontrado",
                          "nenhum processo encontrado", "processo nao localizado",
                          "nao foram encontrados")
_FRASES_SEM_ACESSO = ("nao foi possivel validar o seu acesso", "nao possui permissao",
                      "acesso negado", "nao tem permissao", "sem permissao de acesso",
                      "acesso nao autorizado")


def diz_nao_encontrado(texto: str) -> bool:
    t = sem_acento(texto)
    return any(f in t for f in _FRASES_NAO_ENCONTRADO)


def diz_sem_acesso(texto: str) -> bool:
    t = sem_acento(texto)
    return any(f in t for f in _FRASES_SEM_ACESSO)


def texto_indica_sigilo(texto: str) -> bool:
    """A página do processo se declara em segredo de justiça?

    Procura-se só "segredo de justiça" (sem a cedilha, que às vezes chega
    estragada). "Sigilo" sozinho, não: "quebra de sigilo bancário" é
    andamento comum em processo público.
    """
    return "segredo de justi" in sem_acento(texto)


def falha_de_rede(msg: str) -> bool:
    """O arquivo não chegou por problema de caminho (rede, proxy, TLS), e
    não por recusa do portal: vale tentar de novo ou por outro canal."""
    return bool(re.search(
        r"ETIMEDOUT|ECONNRESET|ECONNREFUSED|ECONNABORTED|EHOSTUNREACH"
        r"|ENETUNREACH|socket hang up|EAI_AGAIN|ERR_NETWORK|ERR_CONNECTION"
        r"|connect ENOENT|tunneling socket|ERR_PROXY|Timeout \d+ms exceeded"
        r"|timed out", msg or "", re.I)) or falha_de_caminho(msg)


def falha_de_caminho(msg: str) -> bool:
    """Falha que repetir pelo MESMO canal não resolve: passa-se direto ao
    próximo (proxy do sistema, e por fim a própria janela do navegador).

    Na rede do fórum é o caso comum. O canal direto do Playwright não usa o
    proxy nem os certificados do Windows: o nome do portal não resolve fora
    do proxy (ENOTFOUND) e a inspeção de TLS da rede apresenta um
    certificado que só o navegador conhece. Na base, esses erros nem eram
    reconhecidos como de rede, e o download falhava sem tentar os outros
    caminhos.
    """
    return bool(re.search(
        r"ENOTFOUND|ERR_NAME_NOT_RESOLVED|getaddrinfo|ERR_PROXY|tunneling socket"
        r"|certificate|CERT_|ERR_SSL|EPROTO|ERR_TLS|SSL routines",
        msg or "", re.I))


def erro_transitorio(msg: str) -> bool:
    """Erro de quem mexeu na janela, ou de página que trocou no meio."""
    return bool(re.search(
        r"Execution context was destroyed|Target closed|Target page"
        r"|Session closed|has been closed|net::ERR_ABORTED"
        r"|Navigation failed because|frame was detached", msg or "", re.I))


def cheira_a_sessao(msg: str) -> bool:
    t = sem_acento(msg)
    return bool(re.search(
        r"abrir a pasta digital|sem acesso|sessao|expirou|sajcas/login"
        r"|nao consegui identificar o processo|lista de pecas|http 401|http 403", t))


def proxy_do_sistema() -> str | None:
    """O proxy configurado no Windows (rede do fórum), se houver."""
    try:
        px = urllib.request.getproxies()
    except Exception:
        return None
    alvo = px.get("https") or px.get("http")
    if not alvo:
        return None
    return alvo if "://" in alvo else "http://" + alvo


def mascarar(usuario: str) -> str:
    """CPF/usuário no log só pela metade: o log não é lugar de dado pessoal."""
    u = (usuario or "").strip()
    return (u[:3] + "***") if u else "(sem usuário)"


def _parametros(par: str) -> dict[str, str]:
    return dict(re.findall(r"(?:^|&)([^=&]+)=([^&]*)", par or ""))


def _marcado(valor) -> bool:
    """Bandeira do JSON da Pasta Digital: true, "S", "true", 1 - e não a
    simples presença do campo ("N" e "false" também são texto)."""
    if isinstance(valor, str):
        return valor.strip().lower() in ("s", "sim", "true", "1", "y", "yes")
    return valor is True or (isinstance(valor, (int, float)) and valor == 1)


def extrair_pecas(arvore) -> list[dict]:
    """Achata a árvore da Pasta Digital (a variável 'requestScope').

    Uma entrada por bloco de páginas - o que a própria tela marca ao
    "selecionar tudo". Forma da árvore: doc.data{title, cdDocumento,
    dtInclusao, flPeticaoInicial} e doc.children[].data{parametros,
    nuPaginas, flAssinado, documentoSigiloso, urlMidiaDigital}.
    """
    pecas: list[dict] = []
    if not isinstance(arvore, list):
        return pecas
    for doc in arvore:
        if not isinstance(doc, dict):
            continue
        d = doc.get("data") or {}
        for filho in (doc.get("children") or []):
            fd = (filho or {}).get("data") or {}
            par = fd.get("parametros")
            if not par:
                continue
            q = _parametros(par)
            pecas.append({
                "parametros": par,
                "cdDocumento": str(d.get("cdDocumento") or q.get("cdDocumento") or ""),
                "tipo": (d.get("title") or urllib.parse.unquote_plus(q.get("deTipoDocConsulta", ""))
                         or "Documento").strip(),
                "data": d.get("dtInclusao") or "",
                "pagina_inicial": q.get("numInicial") or "",
                "pagina_final": q.get("numFinal") or "",
                "num_paginas": fd.get("nuPaginas") or "",
                "sigiloso": _marcado(fd.get("documentoSigiloso")),
            })
    return pecas


def nome_da_midia(url: str) -> str:
    q = _parametros(urllib.parse.urlsplit(url or "").query)
    bruto = urllib.parse.unquote(q.get("gravacaoAudiencia", ""))
    return bruto.replace("\\", "/").rsplit("/", 1)[-1]


def extrair_midias(arvore) -> list[dict]:
    """Gravações de audiência e demais mídias, com a folha a que se ligam."""
    saida: list[dict] = []
    if not isinstance(arvore, list):
        return saida
    for doc in arvore:
        if not isinstance(doc, dict):
            continue
        d = doc.get("data") or {}
        folha = ""
        for filho in (doc.get("children") or []):
            fd = (filho or {}).get("data") or {}
            if fd.get("parametros") and not folha:
                folha = _parametros(fd["parametros"]).get("numInicial") or ""
        for filho in (doc.get("children") or []):
            fd = (filho or {}).get("data") or {}
            url = fd.get("urlMidiaDigital")
            if url:
                saida.append({"peca": d.get("title") or "", "data": d.get("dtInclusao") or "",
                              "folha": folha, "arquivo": nome_da_midia(url), "url": url})
    return saida


def _inteiro(valor) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def descrever_buracos(buracos) -> str:
    """[(6, 7), (10, 10)] -> "6-7, 10"."""
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in buracos)


def contar_documentos(pecas: list[dict]) -> int:
    vistos, n = set(), 0
    for i, p in enumerate(pecas):
        chave = p.get("cdDocumento") or f"#{i}"
        if chave not in vistos:
            vistos.add(chave)
            n += 1
    return n


def titulo_da_peca(p: dict, ini=None, fim=None) -> str:
    ini = p.get("pagina_inicial") if ini is None else ini
    fim = p.get("pagina_final") if fim is None else fim
    titulo = (p.get("tipo") or "Documento").strip()
    if ini and fim:
        titulo += f" (fl. {ini})" if str(ini) == str(fim) else f" (fls. {ini}-{fim})"
    data = (p.get("data") or "").strip()
    return f"{titulo} - {data}" if data else titulo


def _fls(folhas) -> str:
    """{8} -> "fl. 8"; {6, 7, 40} -> "fls. 6-7, 40"."""
    lista = sorted(set(folhas))
    return (f"fl. {lista[0]}" if len(lista) == 1
            else f"fls. {paginacao.descrever_folhas(lista)}")


# ------------------------------------------------ página N = folha N
# A Pasta Digital numera as folhas dos autos; o PDF do Helestron reproduz essa
# numeração: a página N é sempre a folha N. O plano diz que bloco da árvore
# fornece cada folha, de 1 até a última que a Pasta Digital oferece; a folha
# que nenhum bloco fornece ganha uma página de aviso no lugar.
LIMITE_FAIXA = 100_000       # folhas num bloco só: acima disso o índice está estragado


@dataclass
class Bloco:
    """Um bloco de folhas da Pasta Digital (um filho da árvore)."""
    peca: dict
    ini: int
    fim: int
    ordem: int                                          # posição na árvore
    proprias: list[int] = field(default_factory=list)   # as folhas que ele fornece

    @property
    def n(self) -> int:
        return self.fim - self.ini + 1

    @property
    def documento(self) -> str:
        return str(self.peca.get("cdDocumento") or f"#{self.ordem}")


class ListaDeEnvio(list):
    """As peças pedidas ao servidor, em ordem de folha. Leva o cdDocumento
    da última peça DA ÁRVORE, que vai no pedido como a própria página o
    manda (a ordem mudou; o pedido, não)."""
    cd_documento = ""


def _cd_do_pedido(pecas: list[dict]) -> str:
    """O cdDocumento que vai no pedido do PDF único: o da última peça da
    árvore (a lista pode estar em ordem de folha), como a página manda."""
    return getattr(pecas, "cd_documento", "") or str(pecas[-1].get("cdDocumento") or "")


@dataclass
class PlanoFolhas:
    """Que bloco fornece cada folha, de 1 a ``ultima``."""
    pecas: list[dict]                                   # as da árvore, como vieram
    blocos: list[Bloco]                                 # em ordem de folha, sem repetidos
    ultima: int
    dono: dict[int, int]                                # folha -> índice em blocos
    nao_oferecidas: dict[int, tuple[str, str]]          # folha -> ("N" | "S", título)
    sem_numeracao: list[dict]                           # peças que ficaram de fora
    anomalias: list[str]

    def pecas_envio(self) -> ListaDeEnvio:
        lista = ListaDeEnvio(b.peca for b in self.blocos)
        lista.cd_documento = str((self.pecas[-1] if self.pecas else {}).get("cdDocumento") or "")
        return lista

    def faixas(self) -> list[tuple[int, int, list[int]]]:
        return [(b.ini, b.fim, list(b.proprias)) for b in self.blocos]

    def no_documento(self, i: int) -> tuple[int, int]:
        """(folhas do documento inteiro do bloco i, onde o bloco começa nele):
        para quando o getPDF.do devolve o documento todo, e não só o bloco."""
        alvo = self.blocos[i]
        mesmos = [b for b in self.blocos if b.documento == alvo.documento]
        antes = sum(b.n for b in mesmos[:mesmos.index(alvo)])
        return sum(b.n for b in mesmos), antes


def _posicionar_sem_numeracao(pecas: list[dict], sem: list[int], numerados: list[Bloco],
                              anomalias: list[str]) -> tuple[list[Bloco], dict[int, str]]:
    """Peças sem numeração de folhas: só entram no PDF quando o lugar delas
    é inequívoco - entre dois blocos numerados (na ordem da árvore), o vão
    livre tem exatamente as páginas que elas declaram. Senão ficam de fora,
    e as folhas do vão ganham aviso com o motivo "S".

    Devolve (blocos posicionados, folha -> título das folhas "S").
    """
    if not sem:
        return [], {}
    ocupadas: set[int] = set()
    for b in numerados:
        ocupadas.update(range(b.ini, b.fim + 1))
    por_ordem = {b.ordem: b for b in numerados}
    posicionados: list[Bloco] = []
    folhas_s: dict[int, str] = {}
    fora = 0
    grupos: list[list[int]] = []
    for i in sem:
        if grupos and grupos[-1][-1] == i - 1:
            grupos[-1].append(i)
        else:
            grupos.append([i])
    for grupo in grupos:
        antes = next((por_ordem[j] for j in range(grupo[0] - 1, -1, -1) if j in por_ordem), None)
        depois = next((por_ordem[j] for j in range(grupo[-1] + 1, len(pecas)) if j in por_ordem),
                      None)
        de = antes.fim + 1 if antes else 1
        ate = depois.ini - 1 if depois else None
        declarados = [_inteiro(pecas[j].get("num_paginas")) for j in grupo]
        vao = list(range(de, ate + 1)) if ate is not None and ate >= de else []
        if (vao and all(d is not None and d >= 1 for d in declarados)
                and sum(declarados) == len(vao) and not ocupadas.intersection(vao)):
            inicio = de
            for j, d in zip(grupo, declarados):
                posicionados.append(Bloco(pecas[j], inicio, inicio + d - 1, j))
                inicio += d
            continue
        fora += len(grupo)
        titulo = titulo_da_peca(pecas[grupo[0]], "", "")
        for f in vao:
            if f not in ocupadas:
                folhas_s.setdefault(f, titulo)
    if fora:
        anomalias.append("1 peça listada sem numeração de folhas ficou fora do PDF" if fora == 1
                         else f"{fora} peças listadas sem numeração de folhas ficaram fora do PDF")
    return posicionados, folhas_s


def planejar_folhas(pecas: list[dict]) -> PlanoFolhas:
    """O plano página = folha a partir das peças da Pasta Digital.

    * blocos em ordem de folha (a árvore pode vir fora de ordem), sem o
      bloco repetido;
    * cada folha tem UM dono - o primeiro bloco que a traz; faixas
      sobrepostas não a repetem;
    * a última folha é a maior que algum bloco fornece; as folhas de 1 até
      ela que nenhum bloco fornece são "não oferecidas" (aviso "N", ou "S"
      quando o vão é de uma peça listada sem numeração).

    Sem bloco numerado nenhum, ``blocos`` sai vazio: quem chama não pode
    garantir a numeração e não grava.
    """
    anomalias: list[str] = []
    numerados: list[Bloco] = []
    sem: list[int] = []
    vistos: set = set()
    invalidas = 0
    for i, p in enumerate(pecas):
        ini, fim = _inteiro(p.get("pagina_inicial")), _inteiro(p.get("pagina_final"))
        if ini is None or fim is None or ini < 1 or fim < ini or fim - ini >= LIMITE_FAIXA:
            if ini is not None or fim is not None:
                invalidas += 1
            sem.append(i)
            continue
        chave = (ini, fim, p.get("cdDocumento") or p.get("parametros"))
        if chave in vistos:
            anomalias.append(f"{_fls(range(ini, fim + 1))} "
                             f"{'listada' if ini == fim else 'listadas'} duas vezes na Pasta "
                             "Digital (entrou uma)")
            continue
        vistos.add(chave)
        declarado = _inteiro(p.get("num_paginas"))
        if declarado is not None and declarado != fim - ini + 1:
            anomalias.append(f"{_fls(range(ini, fim + 1))}: a Pasta Digital diz {declarado} "
                             f"página{'s' if declarado != 1 else ''}")
        numerados.append(Bloco(p, ini, fim, i))
    if invalidas:
        anomalias.append("1 peça com numeração de folhas inválida" if invalidas == 1
                         else f"{invalidas} peças com numeração de folhas inválida")
    inferidos, folhas_s = _posicionar_sem_numeracao(pecas, sem, numerados, anomalias)
    posicionados = {b.ordem for b in inferidos}
    blocos: list[Bloco] = []
    dono: dict[int, int] = {}
    for b in sorted(numerados + inferidos, key=lambda x: (x.ini, x.fim, x.ordem)):
        proprias = [f for f in range(b.ini, b.fim + 1) if f not in dono]
        if len(proprias) < b.n:
            repetidas = [f for f in range(b.ini, b.fim + 1) if f not in proprias]
            anomalias.append(f"{_fls(repetidas)} também na faixa de outra peça (entrou a "
                             "primeira)")
        if not proprias:
            continue
        b.proprias = proprias
        blocos.append(b)
        for f in proprias:
            dono[f] = len(blocos) - 1
    ultima = max(dono) if dono else 0
    nao_oferecidas = {f: (("S", folhas_s[f]) if f in folhas_s else ("N", ""))
                      for f in range(1, ultima + 1) if f not in dono}
    return PlanoFolhas(list(pecas), blocos, ultima, dono, nao_oferecidas,
                       [pecas[i] for i in sem if i not in posicionados], anomalias)


def marcadores_de(plano: PlanoFolhas, ausentes: dict[int, str]) -> list[list]:
    """Sumário do PDF em folhas: a página de cada marcador é a folha.

    Um marcador por trecho seguido de folhas de um mesmo documento, e um
    para cada trecho seguido de páginas de aviso (de um mesmo motivo e de
    uma mesma peça): sem ele, a página de aviso seria tomada pela peça do
    marcador anterior.
    """
    trechos: list[list] = []                 # [chave, primeira, última, bloco]
    for f in range(1, plano.ultima + 1):
        i = plano.dono.get(f)
        bloco = plano.blocos[i] if i is not None else None
        documento = bloco.documento if bloco is not None else None
        if f in ausentes or bloco is None:
            chave = ("aviso", ausentes.get(f, "N"), documento)
        else:
            chave = ("doc", documento)
        if trechos and trechos[-1][0] == chave:
            trechos[-1][2] = f
        else:
            trechos.append([chave, f, f, bloco])
    marcas = []
    for chave, a, b, bloco in trechos:
        if chave[0] == "doc":
            marcas.append([1, titulo_da_peca(bloco.peca, a, b), a])
            continue
        titulo = (f"Fl. {a} — não disponibilizada pelo e-SAJ" if a == b
                  else f"Fls. {a}-{b} — não disponibilizadas pelo e-SAJ")
        peca = (titulo_da_peca(bloco.peca, "", "") if bloco is not None
                else plano.nao_oferecidas.get(a, ("", ""))[1])
        marcas.append([1, f"{titulo} ({peca})" if peca else titulo, a])
    return marcas


def frases_das_ausencias(plano: PlanoFolhas, ausentes: dict[int, str]) -> list[str]:
    """Uma frase por motivo, para o detalhe do relatório."""
    por_codigo: dict[str, list[int]] = {}
    for f, codigo in ausentes.items():
        por_codigo.setdefault(codigo, []).append(f)
    frases = []
    for codigo in paginacao.ORDEM_MOTIVOS:
        folhas = por_codigo.get(codigo)
        if not folhas:
            continue
        fls = _fls(folhas)
        if codigo == "N":
            frases.append(f"{fls} não {'oferecida' if len(folhas) == 1 else 'oferecidas'} pela "
                          "Pasta Digital (página de aviso no lugar)")
            continue
        if codigo == "S":
            frases.append(f"{fls}: a Pasta Digital listou peça sem numeração de folhas "
                          "(página de aviso no lugar)")
            continue
        k = len({plano.blocos[plano.dono[f]].documento for f in folhas if f in plano.dono}) or 1
        if codigo == "B":
            frases.append(f"{fls}: " + ("1 peça não veio e tem página de aviso no lugar" if k == 1
                                        else f"{k} peças não vieram e têm página de aviso no lugar"))
        elif codigo == "I":
            frases.append(f"{fls}: " + ("o arquivo de 1 peça veio inválido" if k == 1
                                        else f"os arquivos de {k} peças vieram inválidos")
                          + " (página de aviso no lugar)")
        else:
            frases.append(f"{fls}: " + ("o arquivo de 1 peça veio" if k == 1
                                        else f"os arquivos de {k} peças vieram")
                          + " com páginas a menos (página de aviso no lugar)")
    return frases


# ------------------------------------------------------------- capa (v2)
# A capa sai da página do processo (CPOPG) que o download já abre: a IA e a
# skill do Claude leem classe, partes, marcas, andamentos, incidentes e
# audiências sem abrir o portal. Vai em _controle/<número>_capa.txt (para ler)
# e _capa.json (para máquina); o motor leva os dois junto com o PDF.
FORMATO_CAPA = "helestron.capa/2"
# As seções da página do processo achadas pelo TÍTULO (h2 "Audiências"...),
# não pelo id: o título muda menos que o HTML em volta.
SECOES_CAPA = (("incidentes", "Incidentes, ações incidentais, recursos e execuções de sentenças"),
               ("apensos", "Apensos, entranhados e unificados"),
               ("audiencias", "Audiências"),
               ("historico_classes", "Histórico de classes"),
               ("peticoes_diversas", "Petições diversas"))
EXTRAS_CAPA = (("outros_numeros", "Outros números"), ("processo_principal", "Processo principal"),
               ("local_fisico", "Local físico"), ("outros_assuntos", "Outros assuntos"))
# (chave no capa.json, padrão sem acento, como escrever na lista de marcas)
MARCAS_CAPA = (("prioridade", r"priorit|prioridade", "Prioridade"),
               ("justica_gratuita", r"justica gratuita|gratuidade|assistencia judiciaria",
                "Justiça gratuita"),
               ("segredo", r"segredo de justica|sigilos", "Segredo de justiça"),
               ("idoso", r"\bidos[oa]s?\b", "Idoso"))
_RE_DATA_CAPA = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_RE_CNJ_CAPA = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?:/\d+)?")


def _limpo(texto, limite: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()[:limite]


# No capa.json, os campos da capa com chaves de máquina, tiradas dos rótulos
# da página do e-SAJ ("Juiz" -> "juiz"): não são as do eProc ("magistrado",
# "orgao", "autuacao"), e cada sistema documenta as suas. No capa.txt ficam os
# rótulos da página. O que é igual nos dois é "paginacao" (objeto com
# "resumo" e "ultima", só com o manifesto).
CHAVES_CAPA = {"Classe": "classe", "Assunto": "assunto", "Foro": "foro", "Vara": "vara",
               "Juiz": "juiz", "Distribuição": "distribuicao", "Valor da ação": "valor",
               "Situação": "situacao", "Área": "area", "Controle": "controle"}


def _chave_da_capa(rotulo) -> str:
    rotulo = _limpo(rotulo, 80)
    return CHAVES_CAPA.get(rotulo) or re.sub(r"[^a-z0-9]+", "_", sem_acento(rotulo)).strip("_")


def marcas_da_capa(info: dict, sigiloso: bool = False) -> tuple[list[str], dict[str, bool]]:
    """As marcas do cabeçalho do processo (as etiquetas .unj-tag e o que o
    cabeçalho escreve por extenso) e, delas, prioridade, justiça gratuita,
    segredo de justiça e idoso. O cabeçalho chega sem os valores da capa
    (classe, assunto...): um assunto "Estatuto do Idoso" não faz o processo
    ter a prioridade do idoso."""
    etiquetas = list(dict.fromkeys(t for t in (_limpo(x, 200) for x in info.get("marcas") or [])
                                   if t))
    base = sem_acento(" ".join(etiquetas) + " " + _limpo(info.get("cabecalho")))
    sinais = {chave: bool(re.search(padrao, base)) for chave, padrao, _ in MARCAS_CAPA}
    sinais["segredo"] = sinais["segredo"] or bool(sigiloso)
    marcas = list(etiquetas)
    for chave, padrao, rotulo in MARCAS_CAPA:
        if sinais[chave] and not any(re.search(padrao, sem_acento(t)) for t in etiquetas):
            marcas.append(rotulo)
    return marcas, sinais


def linhas_da_secao(chave: str, linhas) -> list[dict]:
    """As linhas de uma seção da página do processo (as células de cada uma
    e o código do processo do link, quando houver), com a data e o número
    do processo separados; nos incidentes, também recebido_em e classe."""
    saida = []
    for linha in linhas or []:
        if not isinstance(linha, dict):
            continue
        celulas = [c for c in (_limpo(x, 1000) for x in linha.get("celulas") or []) if c]
        if not celulas:
            continue
        texto = " ".join(celulas)
        if len(celulas) == 1 and re.match(r"(?i)n[aã]o h[aá]\b|nenhum", celulas[0]):
            continue                      # "Não há incidentes... vinculados a este processo."
        data = next((c for c in celulas if _RE_DATA_CAPA.fullmatch(c)), "")
        if not data:
            achada = _RE_DATA_CAPA.search(texto)
            data = achada.group(0) if achada else ""
        resto = [c for c in celulas if c != data]
        item = {"data": data, "texto": " - ".join(resto), "celulas": celulas}
        numero = _RE_CNJ_CAPA.search(texto)
        if numero:
            item["numero"] = numero.group(0)
        if linha.get("codigo"):
            item["codigo"] = _limpo(linha["codigo"], 40)
        if chave == "incidentes":
            classe = " - ".join(c for c in (_limpo(_RE_CNJ_CAPA.sub(" ", c)) for c in resto) if c)
            item.update(recebido_em=data, classe=classe)
        saida.append(item)
    return saida


def dados_da_capa(info: dict, numero: Numero, sigla: str, sigiloso: bool = False,
                  manifesto: dict | None = None, quando: datetime | None = None) -> dict:
    """_controle/<número>_capa.json: a capa v2, legível por máquina (a skill do
    Claude a lê pelo "capa_json" do --json do baixar)."""
    quando = quando or datetime.now()
    marcas, sinais = marcas_da_capa(info, sigiloso)
    extras = info.get("extras") if isinstance(info.get("extras"), dict) else {}
    secoes = info.get("secoes") if isinstance(info.get("secoes"), dict) else {}
    dados = {
        "formato": FORMATO_CAPA,
        "sistema": "esaj",
        "tribunal": sigla,
        "processo": numero.formatado,
        "extraido_em": quando.isoformat(timespec="seconds"),
        "sigiloso": bool(sigiloso),
        "capa": {_chave_da_capa(k): _limpo(v, 500) for k, v in (info.get("capa") or {}).items()
                 if _limpo(v)},
        "partes": [p for p in (_limpo(x, 2000) for x in info.get("partes") or []) if p],
        "marcas": marcas,
        **sinais,
        "outros_numeros": _limpo(extras.get("outros_numeros"), 500),
        "processo_principal": _limpo(extras.get("processo_principal"), 200),
        "local_fisico": _limpo(extras.get("local_fisico"), 300),
        "outros_assuntos": _limpo(extras.get("outros_assuntos"), 500),
        "movimentacoes": [{"data": _limpo(m.get("data"), 20), "texto": _limpo(m.get("texto"))}
                          for m in info.get("movs") or [] if isinstance(m, dict)],
        "codigo_processo": _limpo(info.get("codigo"), 40),
        "url": _limpo(info.get("url"), 500),
    }
    for chave, _titulo in SECOES_CAPA:
        dados[chave] = linhas_da_secao(chave, secoes.get(chave))
    if paginacao.valido(manifesto):
        dados["paginacao"] = {"resumo": paginacao.resumo(manifesto),
                              "ultima": int(manifesto.get("ultima") or 0),
                              "ausentes": dict(manifesto.get("ausentes") or {}),
                              "folhas_ausentes": paginacao.descrever_folhas(
                                  paginacao.ausentes(manifesto))}
    return dados


def formatar_capa(info: dict, numero: Numero, sigla: str, sigiloso: bool = False,
                  manifesto: dict | None = None, quando: datetime | None = None) -> str:
    """_controle/<número>_capa.txt: a capa v2 para ler (os títulos "== Capa ==",
    "== Partes ==" e "== Movimentações (N) ==" ficam como na 1.0.1). Todas as
    movimentações - só as da tabela de movimentações, sem limite de 60 -, as
    marcas, os incidentes, apensos, audiências, o histórico de classes, as
    petições diversas e, com o ``manifesto``, as folhas do PDF.

    "SEGREDO DE JUSTIÇA" vai no topo: o motor o procura nos primeiros 2000
    caracteres para manter o processo fora do acervo nas próximas rodadas.
    """
    quando = quando or datetime.now()
    d = dados_da_capa(info, numero, sigla, sigiloso, manifesto, quando)
    linhas =[f"Processo {numero.formatado} - {sigla} (e-SAJ, 1º grau)",
              f"Capa extraída da consulta em {quando:%d/%m/%Y %H:%M}", ""]
    if sigiloso:
        linhas += ["SEGREDO DE JUSTIÇA - processo sigiloso. Não compartilhe.", ""]
    capa = [f"{k}: {_limpo(v, 500)}" for k, v in (info.get("capa") or {}).items() if _limpo(v)]
    capa += [f"{rotulo}: {d[chave]}" for chave, rotulo in EXTRAS_CAPA if d.get(chave)]
    if capa:
        linhas += ["== Capa =="] + capa + [""]
    if d["marcas"]:
        linhas += ["== Marcas =="] + d["marcas"] + [""]
    if d["partes"]:
        linhas += ["== Partes =="] + d["partes"] + [""]
    if d.get("paginacao"):
        p = d["paginacao"]
        linhas += ["== Arquivo ==",
                   f"Folhas 1 a {p['ultima']} (última oferecida pela Pasta Digital)",
                   f"Paginação: {p['resumo']}",
                   "Como citar: \"fl. N\" - a página N do PDF é sempre a folha N da Pasta Digital; "
                   "a folha com página de aviso não veio do e-SAJ (não a use como prova).", ""]
    movs = d["movimentacoes"]
    linhas.append(f"== Movimentações ({len(movs)}) ==")
    if movs:
        linhas += [f"{m['data']}  {m['texto']}" for m in movs]
    else:
        linhas.append("(nenhuma movimentação localizada na página - confira no portal)")
    for chave, titulo in SECOES_CAPA:
        itens = d[chave]
        if not itens:
            continue
        linhas += ["", f"== {titulo} ({len(itens)}) =="]
        linhas += [(f"{x['data']}  {x['texto']}" if x["data"] else x["texto"]) for x in itens]
    return "\n".join(linhas) + "\n"


# --------------------------------------------------------- JS da página
_JS_PAGINA_PROCESSO = r"""() => {
    const limpa = s => (s || '').replace(/\s+/g, ' ').trim();
    const semAcento = s => limpa(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    const texto = el => limpa(el ? (el.innerText || el.textContent) : '');
    // Texto para detectar segredo - o essencial, lido primeiro e fora dos
    // extras: a página inteira MENOS as movimentações ("retirado o segredo de
    // justiça" não faz o processo sigiloso) e menos o modal de senha, que
    // existe escondido em toda página.
    let resto = (document.body && document.body.innerText) || '';
    document.querySelectorAll(
        '#tabelaUltimasMovimentacoes, #tabelaTodasMovimentacoes, #popupSenha, ' +
        '#senhaProcesso, [id*="Movimentac"], .modal'
    ).forEach(el => {
        const t = el.innerText || '';
        if (t) resto = resto.split(t).join(' ');
    });
    const capa = {};
    const campos = {
        'Classe': '#classeProcesso', 'Assunto': '#assuntoProcesso',
        'Foro': '#foroProcesso', 'Vara': '#varaProcesso', 'Juiz': '#juizProcesso',
        'Distribuição': '#dataHoraDistribuicaoProcesso',
        'Valor da ação': '#valorAcaoProcesso', 'Situação': '#situacaoProcesso',
        'Área': '#areaProcesso', 'Controle': '#numeroControleProcesso',
    };
    for (const [rot, sel] of Object.entries(campos)) {
        const v = texto(document.querySelector(sel));
        if (v) capa[rot] = v;
    }
    // Partes: a tabela de todas; sem ela, a das principais (juntar as duas
    // repetia cada parte)
    const partes = [];
    let tabPartes = document.querySelector('#tableTodasPartes');
    if (!tabPartes || !tabPartes.querySelector('td'))
        tabPartes = document.querySelector('#tablePartesPrincipais');
    if (tabPartes) tabPartes.querySelectorAll('tr').forEach(tr => {
        const c = Array.from(tr.cells || []).map(td => texto(td)).filter(Boolean);
        if (c.length >= 2) partes.push(c.join(' '));
    });
    // Seções achadas pelo título; de cada uma, a primeira tabela depois do
    // título (e antes do título seguinte). Extra: o que falhar aqui não leva
    // a capa, as movimentações nem o texto do segredo junto.
    const secoes = {};
    const tabelasDeSecao = new Set();
    try {
        const SECOES = {incidentes: /^incidentes/, apensos: /^apensos/, audiencias: /^audiencias/,
                        historico_classes: /^historico de classes/,
                        peticoes_diversas: /^peticoes diversas/};
        const titulos = Array.from(document.querySelectorAll(
            'h1, h2, h3, h4, h5, .subtitle, .tituloDoBloco'));
        const ehTitulo = new Set(titulos);
        for (const h of titulos) {
            const t = semAcento(h.innerText || h.textContent);
            const chave = Object.keys(SECOES).find(k => SECOES[k].test(t));
            if (!chave || secoes[chave]) continue;
            const w = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
            w.currentNode = h;
            let tabela = null, n;
            while ((n = w.nextNode())) {
                if (h.contains(n)) continue;
                if (ehTitulo.has(n)) break;
                if (n.tagName === 'TABLE') { tabela = n; break; }
            }
            const linhas = [];
            if (tabela) {
                tabelasDeSecao.add(tabela);
                tabela.querySelectorAll('tr').forEach(tr => {
                    if (tr.closest('table') !== tabela) return;     // tabela aninhada
                    const tds = Array.from(tr.cells || []).filter(c => c.tagName === 'TD');
                    if (!tds.length) return;
                    const a = tr.querySelector('a[href*="processo.codigo="]');
                    const m = a ? /processo\.codigo=([A-Za-z0-9]+)/.exec(a.getAttribute('href') || '')
                                : null;
                    linhas.push({celulas: tds.map(td => texto(td)), codigo: m ? m[1] : ''});
                });
            }
            secoes[chave] = linhas;
        }
    } catch (e) { /* seções são extras */ }
    // Movimentações: só da tabela delas (todas; sem ela, as últimas). A regra
    // antiga - toda linha que começa por data - trazia audiências, histórico
    // de classes e petições; e sem repetir "data|texto", porque duas
    // movimentações iguais no mesmo dia são duas movimentações.
    const movimento = tr => {
        const c = Array.from(tr.cells || []).map(td => texto(td));
        if (c.length < 2 || !/^\d{2}\/\d{2}\/\d{4}$/.test(c[0])) return null;
        const t = c.slice(1).filter(Boolean).join(' - ');
        return t.length >= 3 ? {data: c[0], texto: t} : null;
    };
    let movs = [];
    for (const sel of ['#tabelaTodasMovimentacoes', '#tabelaUltimasMovimentacoes']) {
        const tab = document.querySelector(sel);
        if (!tab) continue;
        const lidas = [];
        tab.querySelectorAll('tr').forEach(tr => { const m = movimento(tr); if (m) lidas.push(m); });
        if (lidas.length) { movs = lidas; break; }
    }
    if (!movs.length) {
        // layout sem as tabelas conhecidas: a regra antiga, fora das seções
        const vistos = new Set();
        document.querySelectorAll('tr').forEach(tr => {
            const dona = tr.closest('table');
            if (dona && tabelasDeSecao.has(dona)) return;
            const m = movimento(tr);
            if (!m || vistos.has(m.data + '|' + m.texto)) return;
            vistos.add(m.data + '|' + m.texto);
            movs.push(m);
        });
    }
    const marcas = [];
    let cabecalho = '';
    const extras = {};
    let codigo = '', url = '';
    try {
        // Marcas: as etiquetas do cabeçalho e o texto dele, sem os valores da
        // capa (um assunto "Estatuto do Idoso" não é prioridade de idoso)
        document.querySelectorAll('.unj-tag').forEach(el => {
            const t = texto(el);
            if (t && !marcas.includes(t)) marcas.push(t);
        });
        cabecalho = texto(document.querySelector('#containerDadosPrincipaisProcesso'));
        for (const v of Object.values(capa)) if (v) cabecalho = cabecalho.split(v).join(' ');
        // Outros números, processo principal...: o rótulo e o valor ao lado
        const EXTRAS = {outros_numeros: /^outros numeros/, local_fisico: /^local fisico/,
                        outros_assuntos: /^outros assuntos/,
                        processo_principal: /^processo principal/};
        document.querySelectorAll('.unj-label, label, th, dt, span.label, td.label').forEach(el => {
            const t = semAcento(el.innerText || el.textContent).replace(/:$/, '');
            if (t.length > 40) return;
            const chave = Object.keys(EXTRAS).find(k => EXTRAS[k].test(t));
            if (!chave || extras[chave]) return;
            let v = texto(el.nextElementSibling);
            if (!v && el.parentElement)
                v = limpa(texto(el.parentElement).replace(texto(el), ''));
            if (v) extras[chave] = v.slice(0, 500);
        });
        if (!extras.processo_principal) {
            const m = /Processo principal:?\s*(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?:\/\d+)?)/i
                .exec(texto(document.body));
            if (m) extras.processo_principal = m[1];
        }
        // O endereço só com o que identifica o processo (nada de sessão ou senha)
        const u = new URL(location.href);
        if (/^https?:$/.test(u.protocol)) {
            const fica = ['processo.codigo', 'processo.foro', 'processo.numero'];
            const busca = new URLSearchParams();
            for (const [k, v] of u.searchParams) if (fica.includes(k)) busca.append(k, v);
            codigo = busca.get('processo.codigo') || '';
            url = u.origin + u.pathname + (busca.toString() ? '?' + busca.toString() : '');
        }
    } catch (e) { /* extras */ }
    return {capa, partes: [...new Set(partes)], movs, marcas, cabecalho, secoes, extras,
            codigo, url, texto: resto.slice(0, 200000)};
}"""

_JS_MODAL_SENHA = r"""() => {
    const el = document.querySelector('#senhaProcesso, #popupSenha');
    if (!el) return false;
    const e = getComputedStyle(el);
    if (e.display === 'none' || e.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
}"""

_JS_BUSCAR_TEXTO = r"""async (a) => {
    const r = await fetch(a.url, {method: a.metodo || 'GET', credentials: 'include',
        headers: a.cabecalhos || {}, body: a.corpo || undefined});
    return {status: r.status, texto: (await r.text()).trim()};
}"""


# ============================================================== o portal
class PortalESAJ:
    """Login e download no e-SAJ de um tribunal (1º grau, CPOPG)."""

    sistema = "esaj"

    def __init__(self, nav, tribunal, opcoes, ctx: Contexto | None,
                 credenciais: tuple[str, str] | None):
        self.nav = nav
        self.tribunal = tribunal
        self.opcoes = opcoes
        self.ctx = ctx or Contexto()
        self.base = (tribunal.urls.get("base") or "").rstrip("/")
        if not self.base:
            raise PortalIndisponivel(
                f"o catálogo de tribunais não traz o endereço do e-SAJ do {tribunal.sigla}. "
                "Corrija o arquivo dados\\tribunais.json (campo urls.base).")
        self.usuario, self.senha = (credenciais or ("", ""))
        self.modo = opcoes.modo_login("esaj")
        self.sel = carregar_seletores()
        self.numero_atual: Numero | None = None
        self._pagina_token = None
        self._canal_proxy = None
        # Processos cujo sigilo esta sessão já apurou (Numero.nome_arquivo).
        # Depois de liberado pela senha, o modal pode não voltar na tentativa
        # seguinte: sem esta memória, ela gravaria o processo como público.
        self.sigilosos_apurados: set[str] = set()
        # o processo que baixar() está buscando agora, e o resultado dele
        self._em_curso: tuple[Numero, ResultadoProcesso] | None = None
        # o manifesto de paginação do último PDF gravado (para a capa)
        self._manifesto: dict | None = None

    # ----------------------------------------------------------- atalhos
    @property
    def nome(self) -> str:
        return f"e-SAJ do {self.tribunal.sigla}"

    @property
    def pg(self):
        return self.nav.pagina

    @property
    def espera_ms(self) -> int:
        return max(5, int(self.opcoes.espera_s)) * 1000

    def _checar_cancelado(self) -> None:
        if self.ctx.cancelado():
            raise Cancelado()

    def _dormir(self, segundos: float) -> None:
        """Pausa que atende o "Parar" em menos de meio segundo."""
        limite = time.monotonic() + segundos
        while True:
            self._checar_cancelado()
            falta = limite - time.monotonic()
            if falta <= 0:
                return
            time.sleep(min(0.25, falta))

    def _texto_da_pagina(self, pagina=None) -> str:
        try:
            return (pagina or self.pg).inner_text("body", timeout=5000) or ""
        except Exception:
            return ""

    def _html(self, pagina=None) -> str:
        try:
            return (pagina or self.pg).content() or ""
        except Exception:
            return ""

    def _esperar_carga(self, pagina=None, ms: int = 10000) -> None:
        try:
            (pagina or self.pg).wait_for_load_state("load", timeout=min(ms, self.espera_ms))
        except Exception:
            pass

    # ===================================================== sessão e login
    def sessao_ativa(self) -> bool:
        """Sinal POSITIVO de sessão, perguntado ao servidor e não à tela.

        A consulta sai pelo canal do contexto (que leva os cookies) com
        cache-buster: a resposta anônima lida antes do login ficava em cache
        e negava a sessão para sempre. Só 'usuarioLogado' vale - os demais
        campos vêm preenchidos até para anônimos.
        """
        caminho = f"/esaj/api/auth/session?_={int(time.time() * 1000)}"
        try:
            resp = self.nav.contexto.request.get(
                self.base + caminho, timeout=20000, headers={"Cache-Control": "no-cache"})
            if resp.status == 200:
                dados = resp.json()
                return isinstance(dados, dict) and dados.get("usuarioLogado") is True
            return False
        except Exception as erro:
            log.debug("  sessao_ativa: %s", str(erro)[:120])
            if not falha_de_rede(str(erro)):
                return False
        # O canal do contexto sai DIRETO, sem o proxy e sem os certificados
        # do Windows: na rede do fórum ele nem alcança o portal, e a sessão
        # pareceria sempre perdida (Pasta Digital recusada viraria "sessão
        # caiu" e novo login, em vez de "sem acesso"). A aba usa o proxy.
        try:
            if not (self.pg.url or "").startswith(self.base):
                return False
            status, texto = self._buscar_texto(caminho, cabecalhos={"Cache-Control": "no-cache"})
            if status == 200:
                dados = json.loads(texto)
                return isinstance(dados, dict) and dados.get("usuarioLogado") is True
        except Exception as erro:
            log.debug("  sessao_ativa pela aba: %s", str(erro)[:120])
        return False

    def _estado_sessao(self, pagina) -> bool | None:
        """True/False quando a página informa o estado; None quando não diz.

        Quem sabe a verdade é o script sajcas/verificarLogin.js. O link
        "Sair" aparece até para visitante e NÃO prova nada.
        """
        if pagina is None:
            return None
        try:
            if "sajcas/login" in (pagina.url or ""):
                return False
            return pagina.evaluate(
                "() => (window.sajcas && typeof window.sajcas.usuarioLogadoNoCasServer"
                " !== 'undefined') ? !!window.sajcas.usuarioLogadoNoCasServer : null")
        except Exception:
            return None

    def _esta_logado(self, pagina=None) -> bool:
        pagina = pagina or self.pg
        estado = self._estado_sessao(pagina)
        if estado is not None:
            return estado
        return primeiro_visivel(pagina, self.sel["logado"], espera_ms=1500) is not None

    def _sessao_no_contexto(self) -> bool:
        """Alguma aba já está logada? O e-SAJ costuma concluir o login numa
        janela NOVA, deixando a aba original parada na tela do código."""
        return any(self._estado_sessao(aba) is True for aba in self.nav.abas())

    def _sondar_sessao(self) -> bool:
        """Pergunta ao portal, numa aba própria, se já existe sessão.

        A porta de entrada tem "gateway=true": quem não está autenticado é
        mandado ao CAS. O endereço em que a aba para já responde.
        """
        try:
            with self.nav.nova_aba() as aba:
                aba.goto(URL_ENTRADA.format(base=self.base), wait_until="domcontentloaded",
                         timeout=self.espera_ms)
                try:
                    aba.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                flag = self._estado_sessao(aba)
                if flag is not None:
                    return flag
                return "sajcas/login" not in (aba.url or "")
        except Exception as erro:
            log.debug("  sondagem falhou: %s", str(erro)[:160])
            return False

    def _senha_expirada(self) -> str:
        """Quando a senha vence, o CAS abre o modal "Senha expirada" no lugar
        do modal do código. Esperar código aí é esperar para sempre."""
        for aba in self.nav.abas():
            alvo = primeiro_visivel(aba, self.sel["login_senha_expirada"], espera_ms=0)
            if alvo is not None:
                try:
                    return " ".join((alvo.inner_text() or "").split())[:220] or "senha expirada"
                except Exception:
                    return "senha expirada"
        return ""

    def _recusa_na_tela(self) -> bool:
        """A tela de login está dizendo "usuário ou senha inválidos"?

        Código recusado ("código inválido") não conta: a tela do código
        também mostra o rótulo "Senha", e a mensagem seria confundida.
        """
        for aba in self.nav.abas():
            try:
                if "sajcas/login" not in (aba.url or ""):
                    continue
            except Exception:
                continue
            texto = self._texto_da_pagina(aba)
            limpo = sem_acento(texto)
            if re.search(r"(codigo|token)\W+(\w+\W+)?(invalid|incorret)", limpo):
                continue
            if recusou_credenciais(texto):
                return True
        return False

    def _falha_de_credencial(self) -> LoginFalhou:
        self.nav.diagnosticar("esaj-login-recusado")
        self.nav.esquecer_sessao()
        return LoginFalhou(
            f"o {self.nome} recusou o usuário ou a senha. Confira-os {ONDE_CADASTRAR_ACESSO} "
            "e tente de novo.")

    def _tela_do_codigo(self, espera_s: int = 45):
        """Espera o portal abrir a tela do código e diz em que aba ela abriu.

        O modal do código só nasce DEPOIS que o CAS aceita usuário e senha,
        às vezes em outra aba. Devolve (aba, campo); (None, None) quando a
        tela não apareceu - o login se resolveu sem código, ou não se
        resolveu de todo (quem chama confere).
        """
        limite = time.monotonic() + max(5, espera_s)
        avisou = False
        inicio = time.monotonic()
        while True:
            self._checar_cancelado()
            expirada = self._senha_expirada()
            if expirada:
                self.nav.diagnosticar("esaj-senha-expirada")
                raise LoginFalhou(
                    f"o {self.nome} diz que a sua senha expirou ({expirada}). Troque a "
                    f"senha no próprio portal e atualize-a em {AJUSTES_ACESSOS}.")
            for aba in self.nav.abas():
                campo = primeiro_visivel(aba, self.sel["login_token"], espera_ms=700)
                if campo is not None:
                    return aba, campo
            if self._recusa_na_tela():
                raise self._falha_de_credencial()
            if self._sessao_no_contexto():
                return None, None
            if time.monotonic() >= limite:
                return None, None
            if not avisou and time.monotonic() - inicio > 8:
                avisou = True
                self.ctx.status("Aguardando o portal abrir a tela do código...")
            self._dormir(1.5)

    def _enviar_codigo(self, codigo: str) -> bool:
        """Digita o código, envia e confere se o portal aceitou.

        A conferência é feita nas abas que já existem, com folga: o e-SAJ
        leva alguns segundos para fechar o fluxo do CAS, e abrir aba nova
        antes disso atrapalha o próprio fluxo. Só depois se sonda.
        """
        pagina = self._pagina_token or self.pg
        campo = primeiro_visivel(pagina, self.sel["login_token"], espera_ms=4000)
        if campo is None:
            aba, campo = self._tela_do_codigo(espera_s=10)
            if campo is None:
                return self._sessao_no_contexto()
            self._pagina_token = pagina = aba
        campo.fill(codigo)
        botao = primeiro_visivel(pagina, self.sel["login_token_enviar"], espera_ms=3000)
        if botao is not None:
            botao.click()
        else:
            campo.press("Enter")
        try:
            pagina.wait_for_load_state("networkidle", timeout=self.espera_ms)
        except Exception:
            pass
        limite = time.monotonic() + ESPERA_CONFIRMA_CODIGO_S
        while time.monotonic() < limite:
            if self._sessao_no_contexto():
                return True
            self._dormir(2)
        if self._sondar_sessao():
            return True
        log.warning("  o portal respondeu: %s", self._recado_da_tela() or "(nada)")
        self.nav.diagnosticar("esaj-codigo-recusado")
        return False

    def _recado_da_tela(self) -> str:
        pagina = self._pagina_token or self.pg
        for seletor in (".mensagem", ".erro", ".alert", "#mensagemRetorno",
                        "[class*='erro']", "[class*='invalid']"):
            try:
                alvo = pagina.locator(seletor).first
                if alvo.count() and alvo.is_visible():
                    texto = " ".join((alvo.inner_text() or "").split())
                    if texto:
                        return texto[:200]
            except Exception:
                continue
        return ""

    def _pedir_codigo_novo(self) -> bool:
        """Clica em 'Receber novo código' - o anterior vale cerca de 3 minutos."""
        botao = primeiro_visivel(self._pagina_token or self.pg, self.sel["login_token_novo"],
                                 espera_ms=3000)
        if botao is None:
            return False
        try:
            botao.click()
            log.info("Pedi um código novo ao portal.")
            return True
        except Exception:
            return False

    def _resolver_codigo(self) -> bool:
        """Atende o código de verificação que o e-SAJ manda por e-mail.

        Devolve False quando a tela do código não apareceu (e quem chama
        confere a sessão); True quando o código foi aceito. Levanta
        LoginFalhou ou Cancelado no resto.
        """
        aba, campo = self._tela_do_codigo(self.opcoes.espera_tela_codigo_s)
        if campo is None:
            self._pagina_token = None
            return False
        self._pagina_token = aba
        log.info("O %s enviou um código de verificação para o e-mail do usuário.", self.nome)
        limite = time.monotonic() + max(1, int(self.opcoes.espera_login_min)) * 60
        recado = ""
        for _ in range(5):
            restante = int(limite - time.monotonic())
            if restante <= 0:
                break
            codigo = self.ctx.pedir_codigo(
                f"Código de verificação do {self.nome}",
                recado + f"O {self.nome} enviou um código de verificação para o seu e-mail "
                "(o cadastrado no portal). Digite-o aqui. O código vale cerca de 3 minutos; "
                "se não chegar, peça outro.",
                min(restante, 600), reenviavel=True)
            if codigo is None:
                if self.ctx.cancelado():
                    raise Cancelado()
                # pode ter sido digitado direto na janela do navegador
                if self._sessao_no_contexto() or self._sondar_sessao():
                    log.info("Código aceito na janela do navegador.")
                    return True
                if getattr(self.nav, "visivel", False) and limite > time.monotonic():
                    # Sem quem digite o código aqui (a linha de comando sem
                    # terminal, como a da skill do Claude, ou o diálogo
                    # fechado): com a janela do navegador à vista, o usuário
                    # o digita lá, no campo do próprio portal, dentro do prazo.
                    self._esperar_login_na_janela(
                        f"Digite o código na janela do {self.nome}",
                        f"O {self.nome} enviou um código de verificação para o seu e-mail "
                        "(o cadastrado no portal). Digite-o na janela do navegador que se "
                        "abriu, no campo do código, e clique em Enviar.",
                        "esaj-codigo-prazo", motivo="codigo", limite=limite)
                    log.info("Código aceito na janela do navegador.")
                    return True
                self.nav.diagnosticar("esaj-codigo-nao-informado")
                raise LoginFalhou(
                    "o código de verificação enviado por e-mail não foi informado. "
                    f"Clique em “{TENTAR_DE_NOVO}” quando estiver com ele em mãos (pela linha "
                    "de comando sem terminal, use --visivel e digite o código na janela do "
                    "navegador).")
            codigo = re.sub(r"\s+", "", codigo)
            if not codigo:
                recado = ("Pedi um código novo ao portal; confira o e-mail. "
                          if self._pedir_codigo_novo() else
                          "Não achei o botão de pedir outro código; use o último que chegou. ")
                continue
            self.ctx.status("Conferindo o código no portal...")
            try:
                aceito = self._enviar_codigo(codigo)
            except (Cancelado, LoginFalhou):
                raise
            except Exception as erro:      # a tela trocou no meio do envio
                log.info("  envio do código: %s", str(erro)[:160])
                aceito = self._sessao_no_contexto() or self._sondar_sessao()
            if aceito:
                log.info("Código aceito.")
                return True
            log.warning("O portal não aceitou esse código (errado ou vencido).")
            recado = ("O portal não aceitou o código anterior (errado ou vencido). "
                      + ("Pedi outro; confira o e-mail. " if self._pedir_codigo_novo()
                         else "Confira o código no e-mail e digite de novo. "))
        self.nav.diagnosticar("esaj-codigo-recusado")
        raise LoginFalhou(
            "não consegui concluir a verificação por código: o portal recusou os códigos "
            "informados, ou o prazo acabou. Tente de novo em alguns minutos.")

    def _preencher_login(self) -> None:
        usuario = primeiro_visivel(self.pg, self.sel["login_usuario"], espera_ms=8000)
        senha = primeiro_visivel(self.pg, self.sel["login_senha"], espera_ms=3000) \
            if usuario is not None else None
        if usuario is None or senha is None:
            # Sem diagnóstico aqui: quem chama ainda confere a sessão e
            # insiste. Só a desistência final merece captura de tela.
            raise _CamposNaoApareceram("a tela aberta não trazia os campos de usuário e senha")
        usuario.fill(self.usuario)
        senha.fill(self.senha)
        # No portal novo o "Entrar" nasce DESABILITADO e só acende com os dois
        # campos preenchidos. Clicar antes disso trava até estourar o prazo.
        botao = primeiro_visivel(self.pg, self.sel["login_botao"], espera_ms=5000)
        if botao is not None:
            try:
                botao.click(timeout=15000)
            except Exception as erro:
                log.info("  o botão Entrar não aceitou o clique (%s); enviando pelo teclado.",
                         type(erro).__name__)
                senha.press("Enter")
        else:
            senha.press("Enter")
        try:
            self.pg.wait_for_load_state("networkidle", timeout=self.espera_ms)
        except Exception:
            pass

    def entrar(self) -> None:
        """Garante uma sessão autenticada. Reaproveita a anterior se valer."""
        self._checar_cancelado()
        # O canal pelo proxy leva uma CÓPIA dos cookies de quando foi criado:
        # depois de um novo login, ele baixaria com a sessão velha.
        self._descartar_canal_proxy()
        try:
            if self.modo == "certificado":
                self._entrar_por_certificado()
            elif self.modo == "manual":
                self._entrar_manualmente()
            else:
                self._entrar_com_senha()
        except (Cancelado, LoginFalhou, PortalIndisponivel):
            raise
        except Exception as erro:
            # erro do navegador no meio do login (aba fechada, página que
            # trocou): o grupo para com uma explicação, não com um rastro
            if self.ctx.cancelado():
                raise Cancelado() from erro
            self.nav.diagnosticar("esaj-login-erro")
            raise PortalIndisponivel(
                f"o login no {self.nome} não pôde ser concluído "
                f"({explicar_erro(str(erro))}). Tente de novo; se persistir, ligue "
                f"“{MOSTRAR_NAVEGADOR}” para acompanhar.") from erro

    def _entrar_com_senha(self) -> None:
        self.ctx.status(f"Abrindo o {self.nome}...")
        self.nav.ir(URL_ENTRADA.format(base=self.base))
        if self._esta_logado() or self.sessao_ativa():
            log.info("Sessão do %s ainda válida - login dispensado.", self.nome)
            return
        if not (self.usuario and self.senha):
            raise LoginFalhou(
                f"não há usuário e senha do {self.nome} guardados neste computador. "
                f"Cadastre-os {ONDE_CADASTRAR_ACESSO} - ou escolha “{ENTRAR_MANUALMENTE}” "
                f"em {AJUSTES_ACESSOS}.")
        log.info("Fazendo login no %s como %s...", self.nome, mascarar(self.usuario))
        self.ctx.status(f"Entrando no {self.nome}...")
        if "sajcas/login" not in (self.pg.url or ""):
            self.nav.ir(f"{self.base}/sajcas/login")

        # A tela de login às vezes escapa no meio do preenchimento (o portal
        # troca de página sozinho, ou devolve a home). Vale recomeçar.
        ultimo: Exception | None = None
        sem_campos = False
        for tentativa in range(1, 4):
            self._checar_cancelado()
            try:
                self._preencher_login()
                break
            except _CamposNaoApareceram as erro:
                # Quem já entrou não recebe formulário: em 14/09/2026 a base
                # derrubou o lote pedindo para ajustar seletores que estavam
                # certos - a sessão já valia.
                if self._esta_logado() or self.sessao_ativa():
                    log.info("Sessão já estava válida - o portal nem pediu a senha.")
                    return
                ultimo, sem_campos = erro, True
                log.warning("  a tela de login veio sem os campos; recomeçando (%d/3).", tentativa)
            except Cancelado:
                raise
            except Exception as erro:
                ultimo, sem_campos = erro, False
                log.warning("  a tela de login escapou (%s); recomeçando (%d/3).",
                            type(erro).__name__, tentativa)
            try:
                self.nav.ir(f"{self.base}/sajcas/login")
            except Exception:
                pass
        else:
            if sem_campos:
                self.nav.diagnosticar("esaj-login-sem-campos")
                raise PortalIndisponivel(
                    "a tela de login do e-SAJ não trouxe os campos de usuário e senha em "
                    "três tentativas. Veja a captura em Logs\\diagnostico: se mostrar a "
                    "tela de login normal, o portal mudou (os seletores se ajustam em "
                    f"{caminhos.LOCAL / 'seletores.json'}); se mostrar outra página, o portal está "
                    "instável - tente mais tarde.")
            self.nav.diagnosticar("esaj-login-instavel")
            raise PortalIndisponivel(
                "a tela de login do e-SAJ trocou de página sozinha durante o preenchimento, "
                f"nas três tentativas ({str(ultimo)[:120]}). O portal parece instável: tente "
                "de novo em alguns minutos.")

        pediu_codigo = self._resolver_codigo()
        # Pergunta-se ao servidor, e não à tela: a página em que o login
        # termina nem sempre carrega o verificarLogin.js.
        if not (self._sessao_no_contexto() or self._sondar_sessao()):
            texto = self._texto_da_pagina(self._pagina_token or self.pg)
            if recusou_credenciais(texto) or self._recusa_na_tela():
                raise self._falha_de_credencial()
            self.nav.diagnosticar("esaj-login-incompleto")
            if not pediu_codigo:
                raise LoginFalhou(
                    "o portal aceitou o formulário, mas não abriu a tela do código de "
                    f"verificação nem a sessão. Ligue “{MOSTRAR_NAVEGADOR}” para "
                    f"acompanhar, ou escolha “{ENTRAR_MANUALMENTE}” em {AJUSTES_ACESSOS}.")
            raise LoginFalhou(
                "o login não foi concluído (pode haver aviso, troca de senha obrigatória "
                f"ou instabilidade). Ligue “{MOSTRAR_NAVEGADOR}” para ver a tela, ou "
                f"escolha “{ENTRAR_MANUALMENTE}” em {AJUSTES_ACESSOS}.")
        log.info("Login concluído.")

    def _evento(self, tipo: str, **dados) -> None:
        """Evento legível por máquina para quem acompanha (a skill do Claude,
        pela linha de comando): "login_aguardando", "login_concluido"...
        Contexto sem ``evento`` (versão anterior) não recebe nada."""
        ev = getattr(self.ctx, "evento", None)
        if not callable(ev):
            return
        try:
            ev(tipo, **dados)
        except Exception as erro:          # o evento é aviso, nunca derruba o login
            log.debug("evento %s não publicado: %s", tipo, erro)

    def _esperar_login_na_janela(self, titulo: str, mensagem: str, rotulo: str,
                                 motivo: str = "", limite: float | None = None) -> None:
        """Espera o usuário concluir o login na janela do navegador.

        ``limite`` (time.monotonic) é o fim do prazo, quando ele já corre
        (o código por e-mail); sem ele, o prazo é o dos Ajustes, a contar daqui.
        """
        minutos = max(1, int(self.opcoes.espera_login_min))
        if limite is None:
            limite = time.monotonic() + minutos * 60
        restante = max(1, -int(-(limite - time.monotonic()) // 60))     # minutos, para cima
        prazo = f"{restante} minuto{'s' if restante != 1 else ''}"
        self._evento("login_aguardando", sistema=self.sistema, tribunal=self.tribunal.sigla,
                     modo=self.modo, prazo_min=restante,
                     ate=(datetime.now() + timedelta(seconds=max(0.0, limite - time.monotonic())))
                     .isoformat(timespec="seconds"),
                     motivo=motivo or self.modo)
        self.ctx.avisar(titulo, f"{mensagem} Aguardo até {prazo} e sigo sozinho.")
        while time.monotonic() < limite:
            self._dormir(3)
            if self.sessao_ativa() or self._sessao_no_contexto():
                log.info("Login concluído.")
                self.ctx.status("Login concluído.")
                self._evento("login_concluido", sistema=self.sistema,
                             tribunal=self.tribunal.sigla)
                return
        self.nav.diagnosticar(rotulo)
        prazo = f"{minutos} minuto{'s' if minutos != 1 else ''}"
        raise LoginFalhou(
            f"{'passou-se' if minutos == 1 else 'passaram-se'} {prazo} sem o login na janela "
            f"do navegador. Tente de novo (o prazo se ajusta em {CAMPO_PRAZO_LOGIN}).")

    def _entrar_por_certificado(self) -> None:
        # Como no login manual: primeiro a porta de entrada do portal, e só
        # então a pergunta pela sessão. Na rede do fórum, o canal direto não
        # alcança o portal, e a aba em about:blank também não responde - a
        # sessão válida pareceria perdida, e o magistrado receberia um pedido
        # de login falso a cada chamada.
        self.ctx.status(f"Abrindo o {self.nome}...")
        self.nav.ir(URL_ENTRADA.format(base=self.base))
        if self._esta_logado() or self.sessao_ativa():
            log.info("Sessão do %s ainda válida - login dispensado.", self.nome)
            return
        if "sajcas/login" not in (self.pg.url or ""):
            self.nav.ir(f"{self.base}/sajcas/login")
        mensagem = (f"Na janela do Chrome que se abriu, entre no {self.nome} com o "
                    "certificado digital: aba 'Certificado digital', escolha o certificado "
                    "e digite o PIN do token.")
        ativo = getattr(self.nav, "web_signer_ativo", None)
        if not (ativo() if callable(ativo) else tem_web_signer(self.nav.perfil)):
            mensagem = ("Falta a extensão Web Signer no navegador do programa: instale-a "
                        "pela Chrome Web Store na janela que se abriu (procure "
                        "'Web Signer'). " + mensagem)
        self._esperar_login_na_janela("Entre com o certificado digital", mensagem,
                                      "esaj-certificado-prazo", motivo="certificado")

    def _entrar_manualmente(self) -> None:
        self.nav.ir(URL_ENTRADA.format(base=self.base))
        if self._esta_logado() or self.sessao_ativa():
            log.info("Sessão do %s ainda válida - login dispensado.", self.nome)
            return
        if "sajcas/login" not in (self.pg.url or ""):
            self.nav.ir(f"{self.base}/sajcas/login")
        self._esperar_login_na_janela(
            f"Entre no {self.nome}",
            "Conclua o login na janela do navegador que se abriu (usuário e senha, "
            "código por e-mail ou certificado, como de costume).",
            "esaj-manual-prazo", motivo="manual")

    # ------------------------------------------------------- diagnóstico
    def _tela_sigilosa(self, numero: Numero | None = None,
                       r: ResultadoProcesso | None = None) -> bool:
        """A tela em curso é de processo em segredo de justiça - apurado
        agora, numa tentativa anterior, ou já sabido pelo motor (pasta de
        sigilosos, pauta)?"""
        em_curso = getattr(self, "_em_curso", None)
        if em_curso is not None:
            numero = numero or em_curso[0]
            r = r or em_curso[1]
        return bool(getattr(self.nav, "sigiloso_em_curso", False)
                    or (r is not None and r.sigiloso)
                    or (numero is not None and numero.nome_arquivo in self.sigilosos_apurados))

    def _diagnosticar_processo(self, rotulo: str, numero: Numero | None = None,
                               r: ResultadoProcesso | None = None) -> str:
        """Guarda a tela do processo em Logs\\diagnostico - menos a de processo
        sigiloso, que traz as partes (o registro diz por quê). Devolve a dica
        para a mensagem de erro: onde ver a tela, ou que ela não foi guardada."""
        sigiloso = self._tela_sigilosa(numero, r)
        diagnosticar_processo(self.nav, rotulo, sigiloso)
        return DICA_SEM_DIAGNOSTICO if sigiloso else DICA_DIAGNOSTICO

    # ======================================================== download
    def baixar(self, numero: Numero, destino_pdf: Path, senha: str | None = None) -> ResultadoProcesso:
        destino_pdf = Path(destino_pdf)
        r = ResultadoProcesso(ordem=0, numero=numero.formatado, tribunal=self.tribunal.sigla,
                              sistema=self.sistema)
        inicio = time.monotonic()
        self._em_curso = (numero, r)
        try:
            self._baixar(numero, destino_pdf, senha, r)
            r.situacao = OK
            r.arquivo = str(destino_pdf)
        except ProcessoNaoEncontrado as erro:
            r.situacao, r.detalhe = NAO_ENCONTRADO, str(erro)
            self.limpar_estado()
        except SemAcesso as erro:
            r.situacao, r.detalhe = SEM_ACESSO, str(erro)
            self.limpar_estado()
        except SigilosoSemSenha as erro:
            r.situacao, r.detalhe, r.sigiloso = SIGILOSO_SEM_SENHA, str(erro), True
            self.limpar_estado()
        except (Cancelado, LoginFalhou, SessaoPerdida, PortalIndisponivel, PermissionError):
            raise
        except Exception as erro:
            if self.ctx.cancelado():
                raise Cancelado() from erro
            msg = str(erro) or type(erro).__name__
            if cheira_a_sessao(msg) and not self.sessao_ativa():
                raise SessaoPerdida(f"a sessão do {self.nome} caiu ({msg[:160]})") from erro
            if not erro_transitorio(msg):
                self._diagnosticar_processo(f"esaj-falha-{numero.nome_arquivo}", numero, r)
            self.limpar_estado()
            raise
        finally:
            r.segundos = round(time.monotonic() - inicio, 1)
            self._em_curso = None
            # uma vez sigiloso, sempre sigiloso (também na tentativa que falhou)
            if numero.nome_arquivo in self.sigilosos_apurados:
                r.sigiloso = True
            elif r.sigiloso:
                self.sigilosos_apurados.add(numero.nome_arquivo)
        return r

    def _baixar(self, numero: Numero, destino: Path, senha: str | None,
                r: ResultadoProcesso) -> None:
        self.numero_atual = numero
        self._manifesto = None
        rotulo = numero.formatado
        self._checar_cancelado()
        self.ctx.status(f"{rotulo}: consultando o {self.nome}...")
        cd = self.achar_codigo(numero)
        if numero.e_dependente:
            ordem = int(numero.dependente)
            log.info("    principal: %s; abrindo o incidente %04d...", cd, ordem)
            cd_principal = cd
            cd = self.achar_codigo_incidente(ordem, cd, senha, numero)
        else:
            cd_principal = None
        log.info("    código interno: %s", cd)

        # Segredo de justiça (Res. 121/CNJ): o modal de senha só conta se
        # VISÍVEL - ele existe escondido no HTML de toda página.
        if self.precisa_senha():
            self._liberar(senha, r, numero, cd_principal)
        info = self.ler_pagina_processo()
        if not r.sigiloso and not info.get("movs") and self.modal_senha_visivel():
            # o modal apareceu depois da primeira olhada (página lenta)
            self._liberar(senha, r, numero, cd_principal)
            info = self.ler_pagina_processo()
        if texto_indica_sigilo(info.get("texto", "")):
            r.sigiloso = True
        if r.sigiloso:
            log.info("    processo em segredo de justiça.")

        try:
            arvore = self.abrir_pasta(cd)
        except SemAcesso:
            # Pasta recusada com o modal de senha na tela: é segredo de
            # justiça, não falta de acesso - e com a senha da relação, abre.
            if r.sigiloso or not self.modal_senha_visivel():
                raise
            self._liberar(senha, r, numero, cd_principal)
            info = self.ler_pagina_processo() or info
            arvore = self.abrir_pasta(cd)
        pecas = extrair_pecas(arvore)
        if not pecas:
            raise RuntimeError("a Pasta Digital abriu, mas não trouxe nenhuma peça")
        # Peça marcada como sigilosa (quebra de sigilo bancário, laudo
        # psicossocial...) num processo público: o PDF a traz inteira, e ele
        # não pode ir para o acervo da IA - vai para a pasta de sigilosos.
        pecas_sigilosas = self._marcar_sigilosas(pecas, r)
        r.documentos = contar_documentos(pecas)
        plano = planejar_folhas(pecas)
        if not plano.blocos:
            # Sem a numeração não há como pôr a folha N na página N: gravar
            # assim mesmo daria à IA folhas erradas para citar.
            raise RuntimeError(
                "a Pasta Digital não informou a numeração das folhas: não é possível garantir "
                "que a página N do PDF seja a folha N (o portal mudou?)")
        self._registrar_plano(plano)
        inicial = plano
        celula = {"plano": plano}

        def reabrir(_n=numero, _cd=cd, _s=senha):
            principal = self.achar_codigo(_n)
            if _n.e_dependente:
                self.achar_codigo_incidente(int(_n.dependente), principal, _s, _n)
            # o índice reaberto pode ter peça nova: o plano (e a conferência
            # do PDF) passa a ser o dele
            novo = planejar_folhas(extrair_pecas(self.abrir_pasta(_cd)))
            if novo.blocos:
                celula["plano"] = novo
            return celula["plano"].pecas_envio()

        detalhes: list[str] = []
        try:
            url = self.gerar_pdf(plano.pecas_envio(), cd, reabrir)
            plano = celula["plano"]
            self.ctx.status(f"{rotulo}: baixando o PDF...")
            dados = self.pedir_arquivo(url)
            if not pdf.e_pdf(dados):
                pista = " (veio uma página da web: a sessão pode ter caído)" if pdf.e_html(dados) else ""
                raise RuntimeError("o arquivo entregue pelo servidor não é um PDF" + pista)
            montagem = pdf.gravar_alinhado(destino, dados, plano.faixas(), plano.ultima,
                                           plano.nao_oferecidas,
                                           self._acabamento(plano, numero, "servidor"))
            log.info("    salvo: %s (%.1f MB)", destino.name, len(dados) / 1048576)
        except (Cancelado, SessaoPerdida, LoginFalhou, SemAcesso, PortalIndisponivel):
            raise
        except Exception as erro:
            if isinstance(erro, PermissionError) and self._na_gravacao(erro, destino):
                # O arquivo que se estava gravando ficou preso: o próprio PDF
                # (aberto no leitor, quando o destino é uma pasta que o usuário
                # vê) ou o provisório dele, recém-gravado, que o antivírus ou o
                # indexador seguram por uns segundos. Peça a peça grava no mesmo
                # lugar e daria no mesmo: o erro sobe, e o motor diz qual é
                # (leitor de PDF) ou tenta de novo, com espera (área provisória).
                raise
            motivo = str(erro) or type(erro).__name__
            if cheira_a_sessao(motivo) and not self.sessao_ativa():
                raise SessaoPerdida(f"a sessão do {self.nome} caiu ({motivo[:160]})") from erro
            if isinstance(erro, pdf.Desalinhado):
                log.warning("    o PDF único do servidor não confere com o índice (%s); "
                            "montando peça a peça.", motivo[:200])
                detalhes.append(f"montado peça a peça ({motivo[:160]})")
            else:
                log.warning("    o servidor não entregou o PDF único (%s); montando peça a peça.",
                            motivo[:200])
                detalhes.append("montado peça a peça (o PDF único do servidor falhou)")
            plano = celula["plano"]
            montagem = self.montar_peca_a_peca(plano, destino, rotulo,
                                               self._acabamento(plano, numero, "peca_a_peca"))
        if plano is not inicial:          # a Pasta Digital foi reaberta no meio
            self._registrar_plano(plano)
            pecas_sigilosas = max(pecas_sigilosas, self._marcar_sigilosas(plano.pecas, r))
            r.documentos = contar_documentos(plano.pecas)
        if pecas_sigilosas:
            detalhes.insert(0, "contém 1 peça sigilosa" if pecas_sigilosas == 1
                            else f"contém {pecas_sigilosas} peças sigilosas")
        r.paginas = montagem.paginas
        r.incompleto = paginacao.descrever_folhas(montagem.ausentes)
        if r.incompleto:
            log.warning("    ATENÇÃO: as folhas %s não vieram; o PDF tem página de aviso no "
                        "lugar delas (a página N continua sendo a folha N).", r.incompleto)
        detalhes += frases_das_ausencias(plano, montagem.ausentes)
        detalhes += montagem.notas + plano.anomalias
        midias = extrair_midias(arvore)
        if midias:
            fls = ", ".join(str(m["folha"]) for m in midias if m["folha"])
            log.info("    %d gravação(ões) de audiência nos autos%s.", len(midias),
                     f" (fls. {fls})" if fls else "")
            if self.opcoes.baixar_midias:
                pasta = destino.parent / "_controle" / "midias" / numero.nome_arquivo
                r.midias = self.baixar_midias(midias, pasta)
            else:
                detalhes.append("1 gravação de audiência nos autos, não baixada"
                                if len(midias) == 1 else
                                f"{len(midias)} gravações de audiência nos autos, não baixadas")
        r.detalhe = "; ".join(detalhes)
        self._gravar_capa(info, numero, destino, r.sigiloso)

    def _gravar_capa(self, info: dict, numero: Numero, destino: Path, sigiloso: bool) -> None:
        """_controle/<número>_capa.txt e _capa.json (o motor os leva junto com o
        PDF), com as folhas do PDF gravado. Capa é conveniência, não dever:
        falha vai só para o log."""
        controle = destino.parent / "_controle"
        quando = datetime.now()
        manifesto = getattr(self, "_manifesto", None)
        try:
            texto = formatar_capa(info, numero, self.tribunal.sigla, sigiloso, manifesto, quando)
            sistema.gravar_atomico(controle / f"{numero.nome_arquivo}_capa.txt",
                                   texto.encode("utf-8"))
        except Exception as erro:
            log.debug("capa não gravada: %s", erro)
        try:
            dados = dados_da_capa(info, numero, self.tribunal.sigla, sigiloso, manifesto, quando)
            sistema.gravar_atomico(controle / f"{numero.nome_arquivo}_capa.json",
                                   json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8"))
        except Exception as erro:
            log.debug("capa (JSON) não gravada: %s", erro)

    @staticmethod
    def _na_gravacao(erro: OSError, destino: Path) -> bool:
        """O PermissionError é do arquivo que se estava gravando - o destino ou
        um provisório dele (".parcial", ".parcial2"), na mesma pasta? Sem nome
        de arquivo (o Windows nega o acesso a um soquete, por exemplo, quando o
        firewall barra o canal de download), não é: foi a rota do servidor que
        falhou, e o peça a peça pode dar certo."""
        destino = Path(destino)
        for nome in (getattr(erro, "filename", None), getattr(erro, "filename2", None)):
            if not nome:
                continue
            alvo = Path(str(nome))
            pares = [(alvo, destino)]
            try:
                pares.append((alvo.resolve(), destino.resolve()))
            except (OSError, ValueError):
                pass
            if any(a.parent == d.parent and a.name.startswith(d.name) for a, d in pares):
                return True
        return False

    @staticmethod
    def _marcar_sigilosas(pecas: list[dict], r: ResultadoProcesso) -> int:
        """Quantas peças a Pasta Digital marca como sigilosas; com alguma, o
        processo passa a ser tratado como sigiloso."""
        n = len({p["cdDocumento"] or p["parametros"] for p in pecas if p.get("sigiloso")})
        if n:
            r.sigiloso = True
            log.info("    %d peça(s) marcada(s) como sigilosa(s) na Pasta Digital.", n)
        return n

    @staticmethod
    def _registrar_plano(plano: PlanoFolhas) -> None:
        if plano.nao_oferecidas:
            log.warning("    ATENÇÃO: a Pasta Digital não ofereceu as folhas %s; no PDF elas "
                        "têm página de aviso no lugar.",
                        paginacao.descrever_folhas(plano.nao_oferecidas))
        for anomalia in plano.anomalias:
            log.warning("    índice da Pasta Digital: %s", anomalia)
        log.info("    %d documento(s), folhas 1 a %d no índice",
                 contar_documentos(plano.pecas), plano.ultima)

    def _acabamento(self, plano: PlanoFolhas, numero: Numero, origem: str):
        """O sumário (em folhas) e o manifesto de paginação, que só se fazem
        depois de saber que folhas ficaram com página de aviso."""
        def acabar(ausentes: dict[int, str], notas: list[str]):
            sumario = marcadores_de(plano, ausentes)
            manifesto = paginacao.manifesto_esaj(
                numero.formatado, plano.ultima, ausentes, origem=origem,
                tribunal=self.tribunal.sigla, notas=[*notas, *plano.anomalias])
            self._manifesto = manifesto        # a capa diz as folhas do PDF
            return sumario, manifesto
        return acabar

    def _liberar(self, senha: str | None, r: ResultadoProcesso, numero: Numero,
                 cd_principal: str | None) -> None:
        """O e-SAJ pediu a senha do processo: usa a da relação, ou desiste
        deste processo (SIGILOSO_SEM_SENHA) com a orientação certa."""
        r.sigiloso = True
        if not senha:
            raise SigilosoSemSenha(
                "processo em segredo de justiça: o e-SAJ pede a senha do processo. "
                "Ponha-a na relação, ao lado do número (número ; senha), e baixe de novo.")
        self.ctx.status(f"{numero.formatado}: processo em segredo; enviando a senha informada...")
        if not self.liberar_segredo(senha):
            raise SigilosoSemSenha(
                "processo em segredo de justiça: a senha informada não liberou o "
                "acesso. Confira-a no ofício.")
        log.info("    acesso liberado pela senha.")
        if cd_principal:
            self.conferir_incidente(cd_principal, int(numero.dependente))

    # ------------------------------------------------------------ consulta
    def ir_para(self, url: str, timeout: int = 60000, tentativas: int = 3) -> None:
        for k in range(tentativas):
            self._checar_cancelado()
            try:
                self.pg.goto(url, wait_until="domcontentloaded", timeout=timeout)
                return
            except Exception:
                try:
                    if url.rstrip("/") in (self.pg.url or "").rstrip("/"):
                        return
                except Exception:
                    pass
                if k == tentativas - 1:
                    raise
                self._dormir(2)

    def limpar_estado(self) -> None:
        """Volta ao portal para desfazer modal ou estado preso do CPOPG."""
        try:
            self.ir_para(f"{self.base}/esaj/", timeout=45000, tentativas=2)
        except Cancelado:
            pass
        except Exception:
            pass

    def _codigo_na_lista(self, numero: Numero) -> str | None:
        """Na lista de resultados, o link cujo texto traz ESTE número."""
        try:
            pares = self.pg.evaluate(r"""() => Array.from(document.querySelectorAll('a'))
                .map(a => ({h: a.getAttribute('href') || '',
                            t: ((a.closest('tr,li,div') || a).innerText || '')}))
                .filter(x => /processo\.codigo=/.test(x.h))""")
        except Exception:
            pares = []
        achados = []
        for par in pares or []:
            if numero.principal in (par.get("t") or ""):
                cd = codigo_na(par.get("h"))
                if cd and cd not in achados:
                    achados.append(cd)
        # Principal e incidentes têm o mesmo número; o código do principal
        # termina em 0000 (o do incidente N troca os 4 últimos por N). Pegar
        # o primeiro da lista podia gravar um incidente com o nome do principal.
        return next((c for c in achados if c.endswith("0000")), achados[0] if achados else None)

    def achar_codigo(self, numero: Numero) -> str:
        url = url_busca(self.base, numero)
        corpo = ""
        for tentativa in range(1, 4):
            # O CPOPG recusa uma consulta enquanto a anterior está aberta
            # ("múltiplas consultas simultâneas"); passar pelo formulário a encerra.
            try:
                self.pg.goto(f"{self.base}/cpopg/open.do", wait_until="domcontentloaded",
                             timeout=45000)
            except Exception:
                pass
            self.ir_para(url)
            cd = codigo_na(self.pg.url or "")
            if cd:
                return cd
            corpo = self._html()
            # A busca devolveu LISTA: o processo nunca foi aberto, e a Pasta
            # Digital recusa ("Não foi possível validar o seu acesso"). Vale o
            # link que traz ESTE número; "o primeiro código da página" (como
            # na base) só quando a página inteira fala de um processo só -
            # senão, seriam autos alheios gravados com este número.
            codigos = set(_RE_CODIGO.findall(corpo))
            cd = self._codigo_na_lista(numero) or (next(iter(codigos)) if len(codigos) == 1 else None)
            if cd:
                self.abrir_processo(cd, numero)
                self._conferir_numero(numero)
                return cd
            if len(codigos) > 1:
                raise RuntimeError("a consulta devolveu vários processos e nenhum traz exatamente "
                                   "este número; não baixei, para não gravar autos trocados")
            if re.search(r"m[úu]ltiplas\s+consultas", corpo, re.I):
                log.info("    o e-SAJ recusou (consultas simultâneas); repetindo %d/3", tentativa)
                self._dormir(2)
                continue
            break
        texto = self._texto_da_pagina() or corpo
        if diz_nao_encontrado(texto):
            raise ProcessoNaoEncontrado(
                f"não encontrado no 1º grau do {self.nome}. Confira o número; se o "
                "processo estiver no 2º grau ou em outro sistema, baixe-o pelo portal.")
        self._diagnosticar_processo(f"esaj-consulta-{numero.nome_arquivo}", numero)
        raise RuntimeError("não consegui identificar o processo na consulta "
                           "(sem acesso, ou sessão expirada?)")

    def _conferir_numero(self, numero: Numero) -> None:
        """A página aberta é mesmo a deste processo? (pelos 20 dígitos, que
        sobrevivem a qualquer formatação). Com o modal de senha na frente
        não há o que ler: a conferência fica para a Pasta Digital."""
        self._esperar_carga()
        if self.modal_senha_visivel():
            return
        digitos = re.sub(r"\D", "", self._texto_da_pagina()) + re.sub(r"\D", "", self._html())
        if numero.digitos not in digitos:
            raise RuntimeError("a página aberta pela consulta não traz este número de processo; "
                               "não baixei, para não gravar autos trocados")

    def abrir_processo(self, cd: str, numero: Numero) -> str:
        """Garante que estamos NA página do processo, e não na lista da busca."""
        if f"processo.codigo={cd}" in (self.pg.url or ""):
            return cd
        self.ir_para(url_processo(self.base, cd, numero))
        return cd

    # ---------------------------------------------------------- incidente
    def conferir_incidente(self, cd_principal: str, ordem: int) -> None:
        """Garante que a página aberta é o INCIDENTE, não o principal - para
        nunca gravar autos trocados com o nome do incidente."""
        self._esperar_carga()
        if self.modal_senha_visivel():
            return            # conferido depois de liberada a senha
        try:
            dados = self.pg.evaluate(
                "() => ({temPrincipal: /processo principal/i.test("
                "(document.body.innerText || '').replace(/\\s+/g, ' ')), url: location.href})")
        except Exception:
            return
        if f"processo.codigo={cd_principal}" in (dados.get("url") or ""):
            raise RuntimeError(
                f"ao abrir o incidente {ordem:04d} o e-SAJ devolveu o processo PRINCIPAL; "
                "não baixei, para não gravar autos trocados")
        if not dados.get("temPrincipal"):
            raise RuntimeError(
                f"a página aberta para o incidente {ordem:04d} não se declara incidente "
                "(não menciona 'processo principal'); não baixei, para não gravar autos trocados")

    def achar_codigo_incidente(self, ordem: int, cd_principal: str, senha: str | None,
                               numero: Numero) -> str:
        """Na página do principal, abre o incidente de ordem `ordem`.

        O caminho confiável é o CÓDIGO: o do incidente é o do principal com
        os quatro últimos dígitos trocados. Com senha, vai-se direto a ele
        (o link pode nem aparecer para quem não tem acesso).
        """
        foro = foro_sem_zeros(numero)
        esperado = codigo_incidente(cd_principal, ordem) if len(cd_principal or "") > 4 else None
        marca = marca_do_incidente(ordem)

        if senha and esperado:
            try:
                self.ir_para(url_processo(self.base, esperado, foro=foro))
                self._esperar_carga()
                if self.modal_senha_visivel():
                    if not self.liberar_segredo(senha):
                        raise SigilosoSemSenha(
                            f"processo em segredo de justiça: a senha informada não liberou "
                            f"o incidente {ordem:04d}")
                    log.info("    incidente %04d liberado pela senha.", ordem)
                self.conferir_incidente(cd_principal, ordem)
                return esperado
            except (SigilosoSemSenha, Cancelado):
                raise
            except Exception as erro:
                log.info("    acesso direto ao incidente não deu certo (%s); tentando pela "
                         "página do principal", str(erro)[:80])
                # a varredura abaixo lê os links da página do PRINCIPAL
                self.ir_para(url_processo(self.base, cd_principal, numero))

        if esperado:
            for _ in range(20):
                self._checar_cancelado()
                try:
                    pares = self.pg.evaluate(
                        r"""(pref) => {
                            const limpa = s => (s || '').replace(/\s+/g, ' ').trim();
                            const out = [];
                            document.querySelectorAll('a').forEach(a => {
                                const h = a.getAttribute('href') || '';
                                const m = h.match(/processo\.codigo=([A-Z0-9]+)/);
                                if (!m || !m[1].startsWith(pref) || m[1] === pref + '0000') return;
                                const tr = a.closest('tr');
                                out.push({cod: m[1], ctx: limpa(a.innerText) + ' ' +
                                          limpa(tr ? tr.innerText : '')});
                            });
                            return out;
                        }""", cd_principal[:-4])
                except Exception:
                    pares = []
                alvo = next((c for c in pares if marca.search(c["ctx"])), None)
                if alvo is None and any(c["cod"] == esperado for c in pares):
                    alvo = {"cod": esperado}
                if alvo is not None:
                    if alvo["cod"] != esperado:
                        log.info("    o link do incidente %04d aponta para %s, e não para o "
                                 "código esperado; sigo o link da página", ordem, alvo["cod"])
                    self.ir_para(url_processo(self.base, alvo["cod"], foro=foro))
                    self.conferir_incidente(cd_principal, ordem)
                    return alvo["cod"]
                self.pg.wait_for_timeout(500)

            # o link não apareceu: tenta o código esperado e confere a página
            try:
                self.ir_para(url_processo(self.base, esperado, foro=foro))
                self._esperar_carga()
                if self.modal_senha_visivel():
                    return esperado          # sigiloso: quem chama trata a senha
                confere = self.pg.evaluate(
                    "(alvo) => { const t = (document.body.innerText || '').replace(/\\s+/g, ' ');"
                    " return t.includes(alvo) && /processo principal/i.test(t); }",
                    numero.principal)
            except Cancelado:
                raise
            except Exception:
                confere = False
            if confere:
                return esperado

        raise RuntimeError(f"não localizei o incidente {ordem:04d} na página do processo "
                           "principal (confira se o número do incidente está certo)")

    # ------------------------------------------------------------- segredo
    def modal_senha_visivel(self) -> bool:
        try:
            return bool(self.pg.evaluate(_JS_MODAL_SENHA))
        except Exception:
            return False

    def precisa_senha(self) -> bool:
        """O e-SAJ está pedindo a senha do processo?

        A base perguntava 12 vezes a cada 400 ms (4,8 s em TODO processo).
        O modal é aberto pelo script da página ao carregar: espera-se o
        "load" e olha-se duas vezes, com 0,6 s de intervalo.
        """
        self._esperar_carga()
        if self.modal_senha_visivel():
            return True
        try:
            self.pg.wait_for_timeout(600)
        except Exception:
            pass
        return self.modal_senha_visivel()

    def liberar_segredo(self, senha: str) -> bool:
        """Preenche o modal da Res. 121/CNJ. A senha NUNCA vai para o log."""
        try:
            campo = primeiro_visivel(self.pg, self.sel["processo_senha"], espera_ms=15000)
            if campo is None:
                return False
            campo.fill(senha)
            botao = primeiro_visivel(self.pg, self.sel["processo_senha_enviar"], espera_ms=5000)
            if botao is not None:
                botao.click(timeout=15000)
            else:
                campo.press("Enter")
            try:
                self.pg.wait_for_load_state("domcontentloaded", timeout=self.espera_ms)
            except Exception:
                pass
            self.pg.wait_for_timeout(2500)
        except Cancelado:
            raise
        except Exception as erro:
            log.debug("liberar_segredo: %s", type(erro).__name__)
            return False
        return not self.precisa_senha()

    def ler_pagina_processo(self) -> dict:
        """Capa, partes, movimentações e o texto que denuncia o segredo."""
        info: dict = {}
        for _ in range(4):
            try:
                info = self.pg.evaluate(_JS_PAGINA_PROCESSO) or {}
            except Exception:
                info = {}
            if info.get("movs"):
                break
            try:
                self.pg.wait_for_timeout(500)
            except Exception:
                break
        return info

    # ------------------------------------------------------- pasta digital
    def _buscar_texto(self, url: str, metodo: str = "GET", corpo: str | None = None,
                      cabecalhos: dict | None = None) -> tuple[int, str]:
        """fetch DENTRO da aba (leva cookies e origem da página)."""
        resp = self.pg.evaluate(_JS_BUSCAR_TEXTO, {"url": url, "metodo": metodo, "corpo": corpo,
                                                   "cabecalhos": cabecalhos or {}})
        return int((resp or {}).get("status") or 0), str((resp or {}).get("texto") or "")

    def abrir_pasta(self, cd_processo: str):
        """Abre a Pasta Digital e devolve a árvore de documentos."""
        status, url = self._buscar_texto(
            f"/cpopg/abrirPastaDigital.do?processo.codigo={cd_processo}&_={int(time.time() * 1000)}")
        if not url.startswith("http"):
            if diz_sem_acesso(url):
                if self.sessao_ativa():
                    raise SemAcesso(f"o {self.nome} não liberou a Pasta Digital deste processo "
                                    "para o seu usuário")
                raise SessaoPerdida("a Pasta Digital pediu login de novo")
            raise RuntimeError(f"não consegui abrir a Pasta Digital (HTTP {status}: "
                               f"{' '.join(url.split())[:120]})")
        self.ir_para(url, timeout=90000)
        for _ in range(60):
            self._checar_cancelado()
            try:
                pronto = self.pg.evaluate(
                    "() => typeof requestScope !== 'undefined' && Array.isArray(requestScope)"
                    " && requestScope.length > 0")
            except Exception:
                pronto = False
            if pronto:
                return self.pg.evaluate("() => requestScope")
            self.pg.wait_for_timeout(500)
        texto = self._texto_da_pagina()
        if diz_sem_acesso(texto):
            if self.sessao_ativa():
                raise SemAcesso(f"o {self.nome} não liberou a Pasta Digital deste processo "
                                "para o seu usuário")
            raise SessaoPerdida("a Pasta Digital pediu login de novo")
        raise RuntimeError("a lista de peças da Pasta Digital não carregou a tempo")

    def _pedir_localizador(self, pecas: list[dict], cd_processo: str) -> tuple[int, str]:
        # o corpo reproduz, byte a byte, o que a própria página envia
        corpo = "&".join("itensPdfSelecionados=" + urllib.parse.quote(p["parametros"], safe="-_.!~*'()")
                         .replace("%20", "+") for p in pecas)
        corpo += (f"&cdProcesso={cd_processo}&cdDocumento={_cd_do_pedido(pecas)}"
                  "&separarDocumentos=false&acessoPeloPetsg=")
        return self._buscar_texto(
            "/pastadigital/salvarDocumentoPreparado.do", "POST", corpo,
            {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
             "X-Requested-With": "XMLHttpRequest"})

    def gerar_pdf(self, pecas: list[dict], cd_processo: str, reabrir=None) -> str:
        """Pede ao servidor o PDF único ("selecionar tudo > salvar") e espera
        ficar pronto. Devolve o endereço do arquivo."""
        status, localizador = self._pedir_localizador(pecas, cd_processo)
        if "expirou" in sem_acento(localizador) and reabrir:
            log.info("    a sessão da pasta expirou; reabrindo e tentando de novo")
            pecas = reabrir()
            status, localizador = self._pedir_localizador(pecas, cd_processo)
        if status >= 400 or not re.match(r"^[0-9a-f-]{20,}$", localizador or ""):
            raise RuntimeError(f"o servidor não devolveu o localizador do PDF (HTTP {status}: "
                               f"{' '.join((localizador or '').split())[:120]})")
        corpo = (f"localizador={localizador}&cdProcesso={cd_processo}"
                 f"&cdDocumento={_cd_do_pedido(pecas)}")
        inicio = time.monotonic()
        erros = 0
        rotulo = self.numero_atual.formatado if self.numero_atual else ""
        while time.monotonic() - inicio < ESPERA_PDF_S:
            self._checar_cancelado()
            st, resp = self._buscar_texto(
                "/pastadigital/buscarDocumentoFinalizado.do", "POST", corpo,
                {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
            if resp.startswith("http"):
                return resp
            if st >= 400:
                erros += 1
                if erros >= 3:
                    raise RuntimeError(f"o servidor falhou ao montar o PDF (HTTP {st})")
            else:
                erros = 0
            if "sajcas/login" in resp or "expirou" in sem_acento(resp[:400]):
                raise RuntimeError("a sessão da Pasta Digital expirou enquanto o PDF era montado")
            self.ctx.status(f"{rotulo}: o servidor está montando o PDF "
                            f"({int(time.monotonic() - inicio)} s)...")
            self._dormir(INTERVALO_POLL_S)
        raise RuntimeError(f"o servidor demorou mais de {ESPERA_PDF_S // 60} minutos para "
                           "montar o PDF")

    # ---------------------------------------------------------------- rede
    def canal_pelo_proxy(self):
        """Canal de download pelo proxy do Windows (rede do fórum).

        O canal normal do Playwright (contexto.request) sai DIRETO, sem o
        proxy do sistema que o navegador usa; numa rede que exige proxy, o
        download falha mesmo com a página funcionando.
        """
        if self._canal_proxy is not None:
            return self._canal_proxy
        self._canal_proxy = False
        proxy = proxy_do_sistema()
        if not proxy or getattr(self.nav, "playwright", None) is None:
            return False
        try:
            self._canal_proxy = self.nav.playwright.request.new_context(
                proxy={"server": proxy}, storage_state=self.nav.contexto.storage_state())
            log.info("    (preparado um canal alternativo pelo proxy %s)", proxy)
        except Exception as erro:
            log.info("    (não consegui preparar o canal pelo proxy: %s)", str(erro)[:120])
        return self._canal_proxy

    def _descartar_canal_proxy(self) -> None:
        canal, self._canal_proxy = self._canal_proxy, None
        if canal:
            try:
                canal.dispose()
            except Exception:
                pass

    def baixar_pelo_navegador(self, url: str) -> bytes:
        """Último recurso: buscar o arquivo dentro da própria aba."""
        b64 = self.pg.evaluate(
            """async (u) => {
                const r = await fetch(u, {credentials: 'include'});
                if (!r.ok) return {erro: 'HTTP ' + r.status};
                const b = new Uint8Array(await r.arrayBuffer());
                let s = '';
                for (let i = 0; i < b.length; i += 8192)
                    s += String.fromCharCode.apply(null, b.subarray(i, i + 8192));
                return {dados: btoa(s)};
            }""", url)
        if not isinstance(b64, dict) or b64.get("erro"):
            raise RuntimeError(f"download pela janela falhou "
                               f"({(b64 or {}).get('erro', 'resposta vazia')})")
        return base64.b64decode(b64["dados"])

    def _canais(self):
        yield "normal", self.nav.contexto.request
        alt = self.canal_pelo_proxy()
        if alt:
            yield "pelo proxy da rede", alt

    def pedir_arquivo(self, url: str, timeout_ms: int = 300000) -> bytes:
        """Baixa um arquivo, insistindo - e, se a rede falhar, por outro caminho.

        Repete erro de rede, tempo esgotado e resposta 5xx/408/429 (com
        espera crescente); HTTP 4xx é recusa do portal e não se repete.
        """
        if url.startswith("/"):
            url = self.base + url
        ultimo: Exception | None = None
        for nome, canal in self._canais():
            for tentativa in (1, 2, 3):
                self._checar_cancelado()
                try:
                    resp = canal.get(url, timeout=timeout_ms)
                except Exception as erro:
                    if not falha_de_rede(str(erro)):
                        raise
                    ultimo = erro
                    if falha_de_caminho(str(erro)):
                        # nome que não resolve, certificado da rede: insistir
                        # no mesmo canal só gasta tempo
                        log.info("    o canal %s não alcança o portal (%s); tentando outro "
                                 "caminho...", nome, explicar_erro(str(erro))[:120])
                        break
                    log.info("    falha de conexão no canal %s (tentativa %d/3); repetindo...",
                             nome, tentativa)
                    self._dormir(3 * tentativa)
                    continue
                if resp.status == 200:
                    return resp.body()
                if resp.status >= 500 or resp.status in (408, 429):
                    ultimo = RuntimeError(f"o servidor do tribunal respondeu com erro "
                                          f"(HTTP {resp.status})")
                    log.info("    HTTP %d no download (tentativa %d/3); repetindo...",
                             resp.status, tentativa)
                    self._dormir(3 * tentativa)
                    continue
                raise RuntimeError(f"o portal recusou o arquivo (HTTP {resp.status})")
            if ultimo is not None and not falha_de_rede(str(ultimo)):
                break            # 5xx: outro canal não muda a resposta do servidor
        if ultimo is not None and falha_de_rede(str(ultimo)):
            try:
                log.info("    tentando pela própria janela do navegador...")
                return self.baixar_pelo_navegador(url)
            except Cancelado:
                raise
            except Exception as erro:
                ultimo = erro
        raise RuntimeError(f"não consegui baixar o arquivo do tribunal: {str(ultimo)[:200]}")

    # --------------------------------------------------------- peça a peça
    def baixar_peca(self, parametros: str) -> bytes | None:
        """Uma peça avulsa, pelo endereço de documento da Pasta Digital."""
        for molde in ("{base}/pastadigital/getPDF.do?{p}", "{base}/pastadigital/getArquivo.do?{p}"):
            try:
                dados = self.pedir_arquivo(molde.format(base=self.base, p=parametros),
                                           timeout_ms=120000)
            except Cancelado:
                raise
            except Exception as erro:
                log.debug("  peça não veio por %s: %s", molde.split("/")[-1], str(erro)[:100])
                continue
            if len(dados) >= 200 and pdf.e_pdf(dados):
                return dados
        return None

    def montar_peca_a_peca(self, plano: PlanoFolhas, destino: Path, rotulo: str = "",
                           acabamento=None) -> pdf.Montagem:
        """Baixa cada bloco da Pasta Digital e monta o PDF com a página N = folha N.

        A peça que não vem, o arquivo que não abre ou que tem páginas a
        menos deixam página de aviso no lugar de cada folha (pdf.juntar_folhas).
        Quando o getPDF.do devolve o documento inteiro, e não só o bloco, os
        demais blocos do documento usam o mesmo arquivo, sem baixá-lo de novo.
        """
        itens: list[pdf.PecaDeFolhas] = []
        inteiros: dict[str, bytes] = {}        # cdDocumento -> o documento inteiro
        vieram = faltaram = 0
        total = len(plano.blocos)
        for i, bloco in enumerate(plano.blocos):
            self._checar_cancelado()
            self.ctx.status(f"{rotulo}: baixando peça {i + 1} de {total}...")
            no_documento, deslocamento = plano.no_documento(i)
            dados = inteiros.get(bloco.documento)
            if dados is None:
                dados = self.baixar_peca(bloco.peca["parametros"])
                if dados and no_documento > bloco.n \
                        and pdf.contar_paginas_de(dados) == no_documento:
                    inteiros[bloco.documento] = dados
            if dados:
                vieram += 1
            else:
                faltaram += 1
                if not vieram and faltaram >= MAX_PECAS_SEGUIDAS_FALHANDO \
                        and total > MAX_PECAS_SEGUIDAS_FALHANDO:
                    # Servidor fora: cada peça custa até ~40 s de insistência
                    # (dois endereços, três tentativas). Num processo de 200
                    # peças seriam horas para concluir que nada vem.
                    raise RuntimeError(
                        f"nem o PDF único nem as peças avulsas puderam ser baixados (as "
                        f"{faltaram} primeiras peças falharam; o servidor do tribunal "
                        "parece fora do ar)")
            itens.append(pdf.PecaDeFolhas(
                proprias=list(bloco.proprias), ini=bloco.ini, fim=bloco.fim,
                titulo=titulo_da_peca(bloco.peca, bloco.ini, bloco.fim), dados=dados or None,
                total_documento=no_documento, deslocamento=deslocamento))
        if faltaram == total:
            raise RuntimeError("nem o PDF único nem as peças avulsas puderam ser baixados")
        return pdf.juntar_folhas(itens, plano.ultima, destino, plano.nao_oferecidas, acabamento)

    # -------------------------------------------------------------- mídias
    def baixar_midias(self, midias: list[dict], pasta: Path) -> list[str]:
        """Gravações de audiência para _controle/midias/<processo>/.

        "Parar" aqui interrompe só as gravações, sem exceção: o PDF já está
        gravado, e o processo precisa terminar o ciclo - inclusive a ida do
        sigiloso para fora do acervo, que o motor faz em seguida.
        """
        salvas: list[str] = []
        for m in midias:
            if self.ctx.cancelado():
                break
            nome = sistema.nome_seguro(m.get("arquivo") or "", "")
            if not nome:
                nome = hashlib.sha1(m["url"].encode()).hexdigest()[:10] + ".bin"
            alvo = pasta / nome
            if alvo.exists():
                salvas.append(str(alvo))
                continue
            try:
                dados = self.pedir_arquivo(m["url"])
            except Cancelado:
                break
            except Exception as erro:
                log.warning("    gravação %s não veio: %s", nome, str(erro)[:100])
                continue
            if len(dados) < 200 or pdf.e_html(dados):
                log.warning("    gravação %s: resposta vazia ou tela de erro", nome)
                continue
            try:
                sistema.gravar_atomico(alvo, dados)
            except OSError as erro:
                # Disco cheio ou nome recusado: o PDF já está gravado. Deixar o
                # erro subir marcaria o processo como ERRO com o PDF na pasta -
                # e, se sigiloso, ele nunca iria para a pasta de sigilosos.
                log.warning("    gravação %s não pôde ser salva: %s", nome, erro)
                continue
            salvas.append(str(alvo))
            log.info("    gravação: %s (%.1f MB)", nome, len(dados) / 1048576)
        return salvas


class _CamposNaoApareceram(PortalIndisponivel):
    """A tela aberta não trazia os campos de usuário e senha.

    Nem sempre é defeito de seletor: quem já tem sessão válida não recebe
    formulário, e o portal às vezes devolve a home no lugar do login.
    """
