"""O acompanhamento do download em JSON: ``python -m helestron baixar --json ARQ``.

Quem automatiza o programa (a skill do Claude que monta minutas, um script
da informática) lê este arquivo em vez de adivinhar pelo texto da tela: ele
é regravado durante o lote (no máximo uma vez por segundo, e sempre que um
evento importa: login esperando o usuário, fim) e uma última vez ao sair,
com ``concluido: true`` e o código de saída. A gravação é atômica (arquivo
provisório + troca): quem lê nunca pega o JSON pela metade.

O arquivo traz os números REAIS dos processos sigilosos e o caminho dos PDFs
na pasta de sigilosos - por isso a linha de comando recusa gravá-lo dentro
do acervo compartilhado com a IA (sai com código 2).

Formato ``helestron.baixar/1`` (UTF-8; campos novos podem aparecer em versões
futuras, os existentes não mudam de sentido)::

    {
      "formato": "helestron.baixar/1",
      "versao": "1.0.2",                  # versão do Helestron
      "pid": 4321,                        # processo que está baixando
      "inicio": "2026-10-04T10:00:00",
      "atualizado_em": "2026-10-04T10:03:12",
      "concluido": false,                 # true só na última gravação
      "codigo_saida": null,               # 0, 1 ou 2 quando concluido (como o do processo)
      "erro": "",                         # por que nada pôde ser feito (saída antecipada)
      "causa_erro": "",                   # uso | relacao_invalida | sem_processos | destino |
                                          # lote_em_andamento | interrompido | inesperado
      "destino": "C:\\...\\Lote 2026-10-04 10h00",
      "sigilosos_do_lote": "C:\\...\\Sigilosos\\Lote 2026-10-04 10h00",
      "relatorio": "...\\_controle\\relatorio.csv",      # o do lote (sigilosos mascarados)
      "relatorio_completo": "...\\Sigilosos\\...\\_controle\\relatorio.csv",   # ou ""
      "log": "C:\\...\\baixar-....log",   # --log (ou o padrão de --json), "" sem ele
      "status": "Entrando no e-SAJ do TJAL...",   # a última frase da tela
      "navegador_visivel": true,          # a janela do navegador fica à vista (--visivel,
                                          # os Ajustes, ou sem terminal com o e-SAJ por
                                          # senha: o código do e-mail é digitado nela)
      "progresso": {"feitos": 3, "total": 10,     # processos terminados e o em curso
                    "em_curso": "0700004-..."},
      "aguardando": null,                 # ou o evento que espera o usuário: {"tipo":
                                          # "login_aguardando", "sistema", "tribunal",
                                          # "modo", "prazo_min", "ate", "motivo"}, ou
                                          # "acao_na_janela" / "navegador_ocupado"
      "ultimo_evento": {"tipo": "grupo_inicio", "momento": "...", ...},
      "ignorados": [{"argumento": "0700001-70.2024", "motivo": "..."}],
      "ignorados_por_retomar": [{"numero": "...", "situacao": "OK", "motivo": "..."}],
      "avisos": [{"titulo": "...", "mensagem": "..."}],
      "sigilosos_no_acervo": ["...pdf"],  # autos de sigiloso presos no acervo: não compartilhe
      "resumo": {"total": 10, "baixados": 7, "ja_baixados": 1, "falhas": 1,
                 "pendentes": 1, "sigilosos": 1, "a_refazer": 2},
      "processos": [ { ... um por processo, na ordem da relação ... } ]
    }

Cada processo::

    {
      "ordem": 1,
      "numero": "0700001-70.2024.8.02.0058",   # o número REAL, mesmo se sigiloso
      "nome_arquivo": "0700001-70.2024.8.02.0058",
      "tribunal": "TJAL",
      "sistema": "esaj",                  # onde foi achado: "esaj" ou "eproc"
      "situacao": "OK",                   # OK | JA_BAIXADO | ERRO | NAO_ENCONTRADO |
                                          # SEM_ACESSO | SIGILOSO_SEM_SENHA |
                                          # NAO_SUPORTADO | CANCELADO | PENDENTE
      "rotulo": "baixado",
      "sigiloso": false,
      "pdf": "C:\\...\\0700001-70.2024.8.02.0058.pdf",   # "" se não há PDF
      "capa": "...\\_controle\\..._capa.txt",           # "" se não há
      "capa_json": "...\\_controle\\..._capa.json",     # "" se não há
      "meta": "...\\_controle\\..._meta.json",          # registro do download, "" se não há
      "texto": "...\\_texto\\....txt",    # com --texto; "" sem ele
      "texto_situacao": "novo",           # novo | em_dia | falhou | sigiloso_ignorado |
                                          # nao_pedido
      "texto_erro": "",
      "paginas_sem_texto": "30-41",       # com --texto: páginas sem texto extraível
                                          # (imagem sem OCR; confira no PDF). e-SAJ: as
                                          # folhas; eProc: a citação ("evento 4, PET1,
                                          # p. 1-2 (págs. 5-6 do PDF)"); "" se nenhuma
      "paginas_sem_texto_pdf": "30-41",   # as mesmas, como páginas do PDF ("" se nenhuma)
      "paginas": 245,                     # páginas do PDF
      "documentos": 31,
      "incompleto": "12-15",              # e-SAJ: TODAS as folhas com página de aviso
                                          # (não oferecidas, peça que não veio, arquivo
                                          # inválido ou com páginas a menos);
                                          # eProc: documentos que não vieram ("ev. 4 PET1")
      "paginacao": {                      # null se não há PDF
        "garantida": true,                # o PDF traz o manifesto (1.0.2+)
        "resumo": "página N = folha N (fls. 1 a 245); folhas com página de aviso: 12-15",
        "sistema": "esaj",
        "paginacao": "folhas",            # e-SAJ: página N = folha N
        "ultima": 245,                    # última folha oferecida pela Pasta Digital
        "ausentes": {"N": "12-15"},       # código do motivo (N, S, B, I, C) -> folhas
        "folhas_ausentes": "12-15",
        "origem": "servidor"              # servidor | peca_a_peca
      },
      #   no eProc: "paginacao": "documento", "modo": "documentos" | "completo",
      #   "ultima": <páginas do PDF>, "ausentes": [{"evento": 4, "rotulo": "PET1"}],
      #   "documentos": [{"evento", "rotulo", "descricao", "data", "origem",
      #                   "situacao", "inicio", "paginas"}], "partes" (modo completo)
      #   sem manifesto (PDF de versão anterior): {"garantida": false, "resumo":
      #   "paginação não conferida ...", "paginacao": null, "ultima": null,
      #   "ausentes": null}
      "causa": "",                        # por que não deu OK (modelos.CAUSAS): login,
                                          # sessao, portal, portal_parou, navegador_ocupado,
                                          # falha, inesperado, pdf_aberto, gravacao,
                                          # pdf_invalido, interrompido, sigilo_no_acervo
      "refazer": false,                   # uma nova rodada pode mudar o desfecho?
      "consultas": [{"sistema": "esaj", "situacao": "NAO_ENCONTRADO"},
                    {"sistema": "eproc", "consultado": false, "causa": "login",
                     "detalhe": "..."}],
      "detalhe": "...",
      "midias": [],
      "segundos": 41.2,
      "data_hora": "2026-10-04 10:01:40"
    }
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from ..nucleo import paginacao
from .modelos import FALHAS, JA_BAIXADO, OK, ResultadoProcesso, rotulo

log = logging.getLogger("download.acompanhamento")

FORMATO = "helestron.baixar/1"
INTERVALO_S = 1.0
MAX_AVISOS = 30
# Os eventos que deixam o lote esperando o usuário (ou outro download), e os
# que encerram a espera.
ESPERAS = ("login_aguardando", "acao_na_janela", "navegador_ocupado")
FIM_DA_ESPERA = ("login_concluido", "login_falhou", "grupo_inicio", "fim")


def _versao() -> str:
    try:
        from .. import __version__
        return __version__
    except Exception:  # pragma: no cover - o pacote sempre tem versão
        return "?"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _se_existe(caminho: Path | None) -> str:
    try:
        return str(caminho) if caminho is not None and caminho.is_file() else ""
    except OSError:
        return ""


def _nome_arquivo(r: ResultadoProcesso) -> str:
    if r.arquivo:
        return Path(r.arquivo).stem
    try:
        from ..nucleo import cnj
        return cnj.ler_nome_arquivo(r.numero).nome_arquivo
    except Exception:
        return ""


def paginacao_json(r: ResultadoProcesso) -> dict | None:
    """O campo "paginacao" de um processo (ver o formato acima)."""
    if r.paginacao:
        saida = {"garantida": True, "resumo": "", "paginacao": None, "ultima": None,
                 "ausentes": None}
        saida.update(copy.deepcopy(r.paginacao))
        return saida
    if not r.arquivo:
        return None
    return {"garantida": False, "resumo": paginacao.resumo(None), "paginacao": None,
            "ultima": None, "ausentes": None}


def processo_json(r: ResultadoProcesso, extra: dict | None = None) -> dict:
    """Um processo do JSON (ver o formato acima)."""
    extra = extra or {}
    nome = _nome_arquivo(r)
    controle = Path(r.arquivo).parent / "_controle" if r.arquivo else None
    return {
        "ordem": r.ordem,
        "numero": r.numero,
        "nome_arquivo": nome,
        "tribunal": r.tribunal,
        "sistema": r.sistema,
        "situacao": r.situacao or "PENDENTE",
        "rotulo": rotulo(r.situacao),
        "sigiloso": bool(r.sigiloso),
        "pdf": str(r.arquivo or ""),
        "capa": _se_existe(controle / f"{nome}_capa.txt") if controle else "",
        "capa_json": _se_existe(controle / f"{nome}_capa.json") if controle else "",
        "meta": _se_existe(controle / f"{nome}_meta.json") if controle else "",
        "texto": extra.get("texto", ""),
        "texto_situacao": extra.get("texto_situacao", "nao_pedido"),
        "texto_erro": extra.get("texto_erro", ""),
        "paginas_sem_texto": extra.get("paginas_sem_texto", ""),
        "paginas_sem_texto_pdf": extra.get("paginas_sem_texto_pdf", ""),
        "paginas": int(r.paginas or 0),
        "documentos": int(r.documentos or 0),
        "incompleto": r.incompleto or "",
        "paginacao": paginacao_json(r),
        "causa": r.causa or "",
        "refazer": bool(r.refazer),
        "consultas": copy.deepcopy(list(r.consultas or [])),
        "detalhe": r.detalhe or "",
        "midias": list(r.midias or []),
        "segundos": float(r.segundos or 0.0),
        "data_hora": r.data_hora or "",
    }


def _copia(r: ResultadoProcesso) -> ResultadoProcesso:
    """Cópia do item: o motor continua mexendo no objeto."""
    c = copy.copy(r)
    c.midias = list(r.midias or [])
    c.consultas = copy.deepcopy(list(r.consultas or []))
    c.paginacao = copy.deepcopy(dict(r.paginacao or {}))
    return c


class Acompanhamento:
    """Mantém o estado do lote e o grava em JSON (ver o formato acima).

    Recebe o que o ContextoTerminal repassa (``item``, ``evento``, ``aviso``)
    e o que a linha de comando sabe (``definir``, ``texto``, ``concluir``).
    Sem ``arquivo``, só guarda o estado (``dados()``). Nada aqui derruba o
    lote: falha de gravação vira registro no log e nova tentativa depois.
    """

    def __init__(self, arquivo: Path | str | None, intervalo: float = INTERVALO_S, **campos):
        self.arquivo = Path(arquivo) if arquivo else None
        self.intervalo = max(0.0, float(intervalo))
        self._trava = threading.RLock()
        self._itens: dict[int, ResultadoProcesso] = {}
        self._extras: dict[str, dict] = {}
        self._ultima = 0.0
        self._agendado: threading.Timer | None = None
        self._fechado = False
        self._dados: dict = {
            "formato": FORMATO, "versao": _versao(), "pid": os.getpid(), "inicio": _agora(),
            "atualizado_em": "", "concluido": False, "codigo_saida": None, "erro": "",
            "causa_erro": "", "destino": "", "sigilosos_do_lote": "", "relatorio": "",
            "relatorio_completo": "", "log": "", "status": "", "navegador_visivel": False,
            "progresso": {"feitos": 0, "total": 0, "em_curso": ""},
            "aguardando": None, "ultimo_evento": None,
            "ignorados": [], "ignorados_por_retomar": [], "avisos": [],
            "sigilosos_no_acervo": [],
        }
        self.definir(**campos)

    # ------------------------------------------------------------ entrada
    def definir(self, **campos) -> None:
        """Campos do topo do JSON (destino, log, ignorados...)."""
        with self._trava:
            for chave, valor in campos.items():
                self._dados[chave] = str(valor) if isinstance(valor, Path) else valor

    def item(self, r: ResultadoProcesso) -> None:
        with self._trava:
            anterior = self._itens.get(r.ordem)
            self._itens[r.ordem] = _copia(r)
            mudou = anterior is None or anterior.situacao != r.situacao
            if r.situacao and mudou:
                # um item terminou: o login (se esperava) já passou
                self._dados["aguardando"] = None
        self.gravar(forcar=False)

    def evento(self, tipo: str, **dados) -> None:
        corpo = {"tipo": tipo, "momento": _agora()}
        corpo.update({k: v for k, v in dados.items() if k not in corpo})
        with self._trava:
            self._dados["ultimo_evento"] = corpo
            if tipo in ESPERAS:
                self._dados["aguardando"] = corpo
            elif tipo in FIM_DA_ESPERA:
                self._dados["aguardando"] = None
            if tipo == "lote_inicio":
                for chave in ("destino", "relatorio", "sigilosos_do_lote"):
                    if dados.get(chave):
                        self._dados[chave] = str(dados[chave])
        # esperar o usuário é justamente o que quem acompanha precisa saber já
        self.gravar(forcar=True)

    def status(self, texto: str) -> None:
        with self._trava:
            self._dados["status"] = str(texto or "")
        self.gravar(forcar=False)

    def progresso(self, feitos: int, total: int, atual: str) -> None:
        with self._trava:
            self._dados["progresso"] = {"feitos": int(feitos), "total": int(total),
                                        "em_curso": str(atual or "")}
        self.gravar(forcar=False)

    def aviso(self, titulo: str, mensagem: str) -> None:
        with self._trava:
            avisos = self._dados["avisos"]
            avisos.append({"titulo": str(titulo), "mensagem": str(mensagem)})
            del avisos[:-MAX_AVISOS]
        self.gravar(forcar=False)

    def texto(self, r: ResultadoProcesso, caminho, situacao: str, erro: str = "",
              info: dict | None = None) -> None:
        """O texto extraído (baixar --texto) do processo 'r'; 'info' é a de
        textos.analisar (as páginas sem texto extraível)."""
        info = info or {}
        with self._trava:
            self._extras[r.numero] = {
                "texto": str(caminho or ""), "texto_situacao": situacao,
                "texto_erro": str(erro or ""),
                "paginas_sem_texto": str(info.get("paginas_sem_texto") or ""),
                "paginas_sem_texto_pdf": str(info.get("paginas_sem_texto_pdf") or "")}

    def concluir(self, codigo_saida: int, resumo=None, erro: str = "",
                 causa_erro: str = "") -> None:
        """A última gravação: concluido, o código de saída e o resumo do lote."""
        with self._trava:
            if resumo is not None:
                for r in getattr(resumo, "itens", []) or []:
                    self._itens[r.ordem] = _copia(r)
                self._dados["destino"] = str(getattr(resumo, "destino", "") or
                                             self._dados["destino"])
                self._dados["relatorio"] = str(getattr(resumo, "relatorio", "") or
                                               self._dados["relatorio"])
                pasta = getattr(resumo, "pasta_sigilosos", None)
                if pasta:
                    self._dados["sigilosos_do_lote"] = str(pasta)
                completo = getattr(resumo, "relatorio_completo", None)
                self._dados["relatorio_completo"] = str(completo) if completo else ""
                self._dados["sigilosos_no_acervo"] = [
                    str(p) for p in (getattr(resumo, "sigilosos_no_acervo", None) or [])]
            if erro:
                self._dados["erro"] = str(erro)
            if causa_erro:
                self._dados["causa_erro"] = causa_erro
            self._dados["concluido"] = True
            self._dados["codigo_saida"] = int(codigo_saida)
            self._dados["aguardando"] = None
            self._cancelar_agendado()
        self.gravar(forcar=True)
        with self._trava:
            self._fechado = True

    # ------------------------------------------------------------- saída
    def dados(self) -> dict:
        """O JSON inteiro, como seria gravado agora."""
        with self._trava:
            itens = [self._itens[k] for k in sorted(self._itens)]
            processos = [processo_json(r, self._extras.get(r.numero)) for r in itens]
            corpo = copy.deepcopy(self._dados)
        corpo["atualizado_em"] = _agora()
        corpo["resumo"] = {
            "total": len(itens),
            "baixados": sum(1 for r in itens if r.situacao == OK),
            "ja_baixados": sum(1 for r in itens if r.situacao == JA_BAIXADO),
            "falhas": sum(1 for r in itens if r.situacao in FALHAS),
            "pendentes": sum(1 for r in itens if r.pendente),
            "sigilosos": sum(1 for r in itens if r.sigiloso and r.situacao in (OK, JA_BAIXADO)),
            "a_refazer": sum(1 for r in itens if r.refazer),
        }
        corpo["processos"] = processos
        return corpo

    def gravar(self, forcar: bool = True) -> None:
        """Grava agora (forcar) ou, no máximo, uma vez por 'intervalo'."""
        if self.arquivo is None:
            return
        with self._trava:
            if self._fechado:
                return
            espera = self.intervalo - (time.monotonic() - self._ultima)
            if not forcar and espera > 0:
                if self._agendado is None:
                    self._agendado = threading.Timer(espera, self._gravar_agendado)
                    self._agendado.daemon = True
                    self._agendado.start()
                return
            self._cancelar_agendado()
            self._escrever()

    def _gravar_agendado(self) -> None:
        with self._trava:
            self._agendado = None
            if not self._fechado:
                self._escrever()

    def _cancelar_agendado(self) -> None:
        if self._agendado is not None:
            self._agendado.cancel()
            self._agendado = None

    def _escrever(self) -> None:
        dados = json.dumps(self.dados(), ensure_ascii=False, indent=1, default=str)
        destino = self.arquivo
        tmp = destino.with_name(destino.name + ".parcial")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(dados.encode("utf-8"))
            # Quem lê pode estar com o arquivo aberto (Windows): insiste um pouco
            for tentativa in range(5):
                try:
                    os.replace(tmp, destino)
                    break
                except PermissionError:
                    if tentativa == 4:
                        raise
                    time.sleep(0.1)
            self._ultima = time.monotonic()
        except OSError as erro:
            log.debug("acompanhamento JSON não gravado agora (%s)", erro)
            try:
                tmp.unlink()
            except OSError:
                pass

    def fechar(self) -> None:
        with self._trava:
            self._cancelar_agendado()
            self._fechado = True
