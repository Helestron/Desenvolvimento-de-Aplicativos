"""O banco da pauta: SQLite em LOCAL/pauta.sqlite3 (seção 8.2 da especificação).

Três tabelas:

    audiencias   o estado atual de cada audiência (upsert pelo id estável)
    alteracoes   o histórico: nova, alterada, cancelada, removida - com os
                 campos antes -> depois, quando, e se o usuário já viu
    fontes       cada portal (tribunal + sistema), com a rota lembrada (a
                 URL da pauta que funcionou), a última sincronização e o
                 último erro

Por que assim:

* WAL e uma transação por gravação: o monitor grava enquanto a tela lê, e
  uma queda de luz no meio da sincronização não deixa meia pauta;
* a audiência que some da pauta de uma fonte, dentro do período conferido,
  é marcada como REMOVIDA, não apagada - o histórico continua dizendo o que
  havia, e se ela voltar, volta com o mesmo registro;
* a audiência cujo horário mudou ganha outro id (a hora faz parte da
  identidade). Quando, na mesma sincronização, some uma audiência de um
  processo e aparece outra do MESMO processo (uma só de cada lado), é a
  mesma audiência remarcada: vira uma "alteração" com hora antes -> depois,
  e não um par "nova" + "removida";
* campo que veio vazio não apaga o que já se sabia (a captura de uma tela
  com menos colunas não "altera" o local para nada); sigilo, uma vez
  apurado, fica;
* banco corrompido (disco cheio, cópia pela metade) é posto de lado com
  outro nome e um novo é criado: a pauta se refaz na próxima sincronização,
  e o programa não deixa de abrir por causa dela.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import modelos
from .modelos import CAMPOS_COMPARADOS, Audiencia

log = logging.getLogger("pauta.armazem")

VERSAO_ESQUEMA = 1
LIMITE_ALTERACOES = 500

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS audiencias (
    id TEXT PRIMARY KEY,
    fonte TEXT NOT NULL DEFAULT '',
    sistema TEXT NOT NULL DEFAULT '',
    tribunal TEXT NOT NULL DEFAULT '',
    processo TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL,
    hora TEXT NOT NULL DEFAULT '',
    tipo TEXT NOT NULL DEFAULT '',
    situacao TEXT NOT NULL DEFAULT '',
    local TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    classe TEXT NOT NULL DEFAULT '',
    partes TEXT NOT NULL DEFAULT '',
    magistrado TEXT NOT NULL DEFAULT '',
    sigiloso INTEGER NOT NULL DEFAULT 0,
    observacoes TEXT NOT NULL DEFAULT '',
    origem TEXT NOT NULL DEFAULT '',
    capturada_em TEXT NOT NULL DEFAULT '',
    tipo_original TEXT NOT NULL DEFAULT '',
    situacao_original TEXT NOT NULL DEFAULT '',
    removida INTEGER NOT NULL DEFAULT 0,
    removida_em TEXT NOT NULL DEFAULT '',
    atualizada_em TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audiencias_data ON audiencias (data, hora);
CREATE INDEX IF NOT EXISTS audiencias_fonte ON audiencias (fonte, data);
CREATE INDEX IF NOT EXISTS audiencias_processo ON audiencias (processo);

CREATE TABLE IF NOT EXISTS alteracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TEXT NOT NULL,
    tipo TEXT NOT NULL,
    audiencia_id TEXT NOT NULL DEFAULT '',
    data_audiencia TEXT NOT NULL DEFAULT '',
    audiencia TEXT NOT NULL DEFAULT '{}',
    campos TEXT NOT NULL DEFAULT '[]',
    vista INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alteracoes_quando ON alteracoes (quando);
CREATE INDEX IF NOT EXISTS alteracoes_vista ON alteracoes (vista);

CREATE TABLE IF NOT EXISTS fontes (
    id TEXT PRIMARY KEY,
    tribunal TEXT NOT NULL,
    sistema TEXT NOT NULL,
    rotulo TEXT NOT NULL DEFAULT '',
    modo TEXT NOT NULL DEFAULT 'automatico',
    url TEXT NOT NULL DEFAULT '',
    menu TEXT NOT NULL DEFAULT '',
    ultima_sincronizacao TEXT NOT NULL DEFAULT '',
    ultimo_erro TEXT NOT NULL DEFAULT '',
    criada_em TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL DEFAULT ''
);
"""

_COLUNAS_AUDIENCIA = ("id", "fonte", "sistema", "tribunal", "processo", "data", "hora", "tipo",
                      "situacao", "local", "link", "classe", "partes", "magistrado", "sigiloso",
                      "observacoes", "origem", "capturada_em", "tipo_original",
                      "situacao_original")
_COMPLETAVEIS = ("local", "link", "classe", "partes", "magistrado", "observacoes")


def _agora() -> datetime:
    return datetime.now().replace(microsecond=0)


def _iso(momento: datetime | None) -> str:
    return momento.replace(microsecond=0).isoformat() if momento else ""


@dataclass
class Balanco:
    """O que uma gravação mudou."""

    novas: int = 0
    atualizadas: int = 0
    canceladas: int = 0
    removidas: int = 0
    inalteradas: int = 0
    alteracoes: int = 0          # registros de histórico criados (não vistos)
    ids: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {"novas": self.novas, "atualizadas": self.atualizadas,
                "canceladas": self.canceladas, "removidas": self.removidas,
                "inalteradas": self.inalteradas, "alteracoes": self.alteracoes,
                "total": len(self.ids)}


class Armazem:
    """Acesso ao banco. Seguro entre threads (uma conexão, uma trava)."""

    def __init__(self, arquivo: Path | str):
        self.arquivo = Path(arquivo)
        self._trava = threading.RLock()
        self._con: sqlite3.Connection | None = None
        self._abrir()

    # ------------------------------------------------------------- ciclo
    def _conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.arquivo), timeout=15, isolation_level=None,
                              check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 15000")
        try:
            con.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass                    # disco de rede sem memória compartilhada: fica no padrão
        con.execute("PRAGMA synchronous = NORMAL")
        con.executescript(_ESQUEMA)
        con.execute("INSERT OR IGNORE INTO meta (chave, valor) VALUES ('versao', ?)",
                    (str(VERSAO_ESQUEMA),))
        return con

    def _abrir(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._con = self._conectar()
            self._con.execute("SELECT count(*) FROM audiencias").fetchone()
        except sqlite3.DatabaseError as erro:
            if self._con is not None:
                try:
                    self._con.close()
                except sqlite3.Error:
                    pass
                self._con = None
            if isinstance(erro, sqlite3.OperationalError) and "locked" in str(erro).lower():
                raise
            marca = f"{datetime.now():%Y%m%d-%H%M%S}"
            destino = self.arquivo.with_name(
                f"{self.arquivo.stem}.corrompido-{marca}{self.arquivo.suffix}")
            log.error("O banco da pauta (%s) está ilegível (%s); guardei-o como %s e comecei "
                      "um novo - a pauta se refaz na próxima sincronização.",
                      self.arquivo, erro, destino.name)
            for sufixo in ("", "-wal", "-shm"):
                origem = Path(str(self.arquivo) + sufixo)
                if origem.exists():
                    try:
                        origem.replace(Path(str(destino) + sufixo))
                    except OSError:
                        try:
                            origem.unlink()
                        except OSError:
                            pass
            self._con = self._conectar()

    def fechar(self) -> None:
        with self._trava:
            if self._con is not None:
                try:
                    self._con.close()
                except sqlite3.Error:
                    pass
                self._con = None

    def _c(self) -> sqlite3.Connection:
        if self._con is None:
            self._con = self._conectar()
        return self._con

    # ============================================================ audiências
    @staticmethod
    def _linha_para_audiencia(linha: sqlite3.Row) -> Audiencia:
        d = dict(linha)
        d["sigiloso"] = bool(d.get("sigiloso"))
        return modelos.de_dict(d)

    @staticmethod
    def _valores(a: Audiencia) -> tuple:
        return (a.id, a.fonte, a.sistema, a.tribunal, a.processo, a.data.isoformat(), a.hora,
                a.tipo, a.situacao, a.local, a.link, a.classe, a.partes, a.magistrado,
                1 if a.sigiloso else 0, a.observacoes, a.origem, _iso(a.capturada_em),
                a.tipo_original, a.situacao_original)

    def gravar(self, audiencias: list[Audiencia], fonte: str,
               periodo: tuple[date, date] | None = None, registrar_novas: bool = True,
               agora: datetime | None = None) -> Balanco:
        """Grava o que uma fonte trouxe, numa transação.

        'periodo': o intervalo que a fonte CONFERIU; o que dela estava no
        banco nesse intervalo e não veio é marcado como removido (None: nada
        se remove - captura de algumas telas, importação de relatório).
        'registrar_novas': False na primeira sincronização da fonte, para a
        pauta inteira não aparecer como "audiências novas".
        """
        agora = agora or _agora()
        balanco = Balanco()
        unicas: dict[str, Audiencia] = {}
        for a in audiencias:
            a.fonte = a.fonte or fonte
            unicas[a.id] = a
        with self._trava:
            con = self._c()
            con.execute("BEGIN IMMEDIATE")
            try:
                existentes = self._por_ids(con, list(unicas))
                novas_agora: list[Audiencia] = []
                hist_novas: dict[str, int] = {}
                for a in unicas.values():
                    balanco.ids.append(a.id)
                    antigo = existentes.get(a.id)
                    if antigo is None:
                        self._inserir(con, a, agora)
                        balanco.novas += 1
                        novas_agora.append(a)
                        if registrar_novas:
                            hist_novas[a.id] = self._historico(con, "nova", a, [], agora)
                            balanco.alteracoes += 1
                        continue
                    removida = bool(antigo["removida"])
                    velho = self._linha_para_audiencia(antigo)
                    final, campos = self._mesclar(velho, a)
                    self._atualizar(con, final, agora)
                    if removida:
                        # voltou à pauta depois de ter saído
                        balanco.novas += 1
                        self._historico(con, "nova", final, [], agora)
                        balanco.alteracoes += 1
                    elif campos:
                        balanco.atualizadas += 1
                        tipo = "alterada"
                        if final.situacao == "Cancelada" and velho.situacao != "Cancelada":
                            tipo = "cancelada"
                            balanco.canceladas += 1
                        self._historico(con, tipo, final, campos, agora)
                        balanco.alteracoes += 1
                    else:
                        balanco.inalteradas += 1
                if periodo is not None:
                    self._remover_ausentes(con, fonte, periodo, set(unicas), novas_agora,
                                           hist_novas, balanco, agora)
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        return balanco

    def _por_ids(self, con, ids: list[str]) -> dict[str, sqlite3.Row]:
        saida = {}
        for i in range(0, len(ids), 400):
            parte = ids[i:i + 400]
            marcas = ",".join("?" * len(parte))
            for linha in con.execute(f"SELECT * FROM audiencias WHERE id IN ({marcas})", parte):
                saida[linha["id"]] = linha
        return saida

    def _inserir(self, con, a: Audiencia, agora: datetime) -> None:
        colunas = ",".join(_COLUNAS_AUDIENCIA)
        marcas = ",".join("?" * len(_COLUNAS_AUDIENCIA))
        con.execute(f"INSERT INTO audiencias ({colunas}, removida, removida_em, atualizada_em) "
                    f"VALUES ({marcas}, 0, '', ?)", (*self._valores(a), _iso(agora)))

    def _atualizar(self, con, a: Audiencia, agora: datetime) -> None:
        sets = ",".join(f"{c} = ?" for c in _COLUNAS_AUDIENCIA[1:])
        con.execute(f"UPDATE audiencias SET {sets}, removida = 0, removida_em = '', "
                    "atualizada_em = ? WHERE id = ?",
                    (*self._valores(a)[1:], _iso(agora), a.id))

    @staticmethod
    def _mesclar(velho: Audiencia, novo: Audiencia) -> tuple[Audiencia, list[dict]]:
        """O registro final e a lista de campos que mudaram (antes -> depois)."""
        campos = []
        for nome in _COMPLETAVEIS:
            if not getattr(novo, nome) and getattr(velho, nome):
                setattr(novo, nome, getattr(velho, nome))     # vazio não apaga
        novo.sigiloso = bool(novo.sigiloso or velho.sigiloso)
        if not novo.fonte:
            novo.fonte = velho.fonte
        for nome in CAMPOS_COMPARADOS:
            antes = modelos.valor_para_comparar(velho, nome)
            depois = modelos.valor_para_comparar(novo, nome)
            if antes != depois:
                campos.append({"campo": nome, "antes": antes, "depois": depois})
        return novo, campos

    def _remover_ausentes(self, con, fonte: str, periodo, recebidos: set[str],
                          novas_agora: list[Audiencia], hist_novas: dict[str, int],
                          balanco: Balanco, agora: datetime) -> None:
        de, ate = periodo
        faltam = [linha for linha in con.execute(
            "SELECT * FROM audiencias WHERE fonte = ? AND removida = 0 AND data BETWEEN ? AND ?",
            (fonte, de.isoformat(), ate.isoformat())) if linha["id"] not in recebidos]
        if not faltam:
            return
        # Mesma audiência remarcada: uma que sumiu e uma que apareceu, do mesmo
        # processo (e mesmo portal), uma só de cada lado.
        por_processo_novas: dict[tuple, list[Audiencia]] = {}
        for a in novas_agora:
            if a.processo:
                por_processo_novas.setdefault((a.sistema, a.tribunal, a.processo), []).append(a)
        por_processo_faltas: dict[tuple, list] = {}
        for linha in faltam:
            if linha["processo"]:
                chave = (linha["sistema"], linha["tribunal"], linha["processo"])
                por_processo_faltas.setdefault(chave, []).append(linha)
        pareadas: set[str] = set()
        for chave, linhas in por_processo_faltas.items():
            candidatas = por_processo_novas.get(chave) or []
            if len(linhas) != 1 or len(candidatas) != 1:
                continue
            velho = self._linha_para_audiencia(linhas[0])
            nova = candidatas[0]
            final, campos = self._mesclar(velho, nova)
            self._atualizar(con, final, agora)
            con.execute("DELETE FROM audiencias WHERE id = ?", (velho.id,))
            pareadas.add(velho.id)
            balanco.novas -= 1
            balanco.atualizadas += 1
            tipo = "alterada"
            if final.situacao == "Cancelada" and velho.situacao != "Cancelada":
                tipo, balanco.canceladas = "cancelada", balanco.canceladas + 1
            if nova.id in hist_novas:
                con.execute("UPDATE alteracoes SET tipo = ?, campos = ?, audiencia = ? "
                            "WHERE id = ?", (tipo, json.dumps(campos, ensure_ascii=False),
                                             json.dumps(modelos.como_dict(final),
                                                        ensure_ascii=False),
                                             hist_novas[nova.id]))
            else:
                self._historico(con, tipo, final, campos, agora)
                balanco.alteracoes += 1
        for linha in faltam:
            if linha["id"] in pareadas:
                continue
            con.execute("UPDATE audiencias SET removida = 1, removida_em = ?, atualizada_em = ? "
                        "WHERE id = ?", (_iso(agora), _iso(agora), linha["id"]))
            self._historico(con, "removida", self._linha_para_audiencia(linha), [], agora)
            balanco.removidas += 1
            balanco.alteracoes += 1

    def _historico(self, con, tipo: str, a: Audiencia, campos: list[dict],
                   agora: datetime) -> int:
        cur = con.execute(
            "INSERT INTO alteracoes (quando, tipo, audiencia_id, data_audiencia, audiencia, "
            "campos, vista) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (_iso(agora), tipo, a.id, a.data.isoformat(),
             json.dumps(modelos.como_dict(a), ensure_ascii=False),
             json.dumps(campos, ensure_ascii=False)))
        return int(cur.lastrowid)

    # ------------------------------------------------------------ consulta
    def listar(self, de: date, ate: date, incluir_removidas: bool = False) -> list[Audiencia]:
        filtro = "" if incluir_removidas else " AND removida = 0"
        with self._trava:
            linhas = self._c().execute(
                "SELECT * FROM audiencias WHERE data BETWEEN ? AND ?" + filtro +
                " ORDER BY data, CASE hora WHEN '' THEN '99:99' ELSE hora END, processo",
                (de.isoformat(), ate.isoformat())).fetchall()
        return [self._linha_para_audiencia(x) for x in linhas]

    def obter(self, id_audiencia: str) -> Audiencia | None:
        with self._trava:
            linha = self._c().execute("SELECT * FROM audiencias WHERE id = ?",
                                      (id_audiencia,)).fetchone()
        return self._linha_para_audiencia(linha) if linha else None

    def removida(self, id_audiencia: str) -> bool:
        with self._trava:
            linha = self._c().execute("SELECT removida FROM audiencias WHERE id = ?",
                                      (id_audiencia,)).fetchone()
        return bool(linha and linha["removida"])

    def futuras(self, a_partir: date, limite: int = 50) -> list[Audiencia]:
        with self._trava:
            linhas = self._c().execute(
                "SELECT * FROM audiencias WHERE removida = 0 AND data >= ? ORDER BY data, "
                "CASE hora WHEN '' THEN '99:99' ELSE hora END LIMIT ?",
                (a_partir.isoformat(), int(limite))).fetchall()
        return [self._linha_para_audiencia(x) for x in linhas]

    def contar(self) -> int:
        with self._trava:
            return int(self._c().execute(
                "SELECT count(*) FROM audiencias WHERE removida = 0").fetchone()[0])

    # ----------------------------------------------------------- histórico
    def alteracoes(self, desde: datetime | None = None, de: date | None = None,
                   ate: date | None = None, limite: int = LIMITE_ALTERACOES) -> list[dict]:
        """O histórico, do mais novo ao mais antigo.

        'desde': só o registrado a partir deste momento; 'de'/'ate': só o das
        audiências marcadas nesse intervalo (a aba Alterações da planilha).
        """
        sql, args = "SELECT * FROM alteracoes WHERE 1 = 1", []
        if desde is not None:
            if desde.tzinfo is not None:      # "2026-10-03T10:00:00Z" da página: hora local
                desde = desde.astimezone().replace(tzinfo=None)
            sql += " AND quando >= ?"
            args.append(_iso(desde))
        if de is not None:
            sql += " AND data_audiencia >= ?"
            args.append(de.isoformat())
        if ate is not None:
            sql += " AND data_audiencia <= ?"
            args.append(ate.isoformat())
        sql += " ORDER BY quando DESC, id DESC LIMIT ?"
        args.append(int(limite))
        with self._trava:
            linhas = self._c().execute(sql, args).fetchall()
        saida = []
        for x in linhas:
            try:
                audiencia = json.loads(x["audiencia"] or "{}")
            except ValueError:
                audiencia = {}
            try:
                campos = json.loads(x["campos"] or "[]")
            except ValueError:
                campos = []
            saida.append({"id": x["id"], "quando": x["quando"], "tipo": x["tipo"],
                          "audiencia": audiencia, "campos": campos, "vista": bool(x["vista"])})
        return saida

    def marcar_vistas(self) -> int:
        with self._trava:
            cur = self._c().execute("UPDATE alteracoes SET vista = 1 WHERE vista = 0")
            return cur.rowcount or 0

    def nao_vistas(self) -> int:
        with self._trava:
            return int(self._c().execute(
                "SELECT count(*) FROM alteracoes WHERE vista = 0").fetchone()[0])

    # -------------------------------------------------------------- fontes
    @staticmethod
    def id_fonte(tribunal: str, sistema: str) -> str:
        return f"{(sistema or '').strip().lower()}-{(tribunal or '').strip().lower()}"

    @staticmethod
    def _fonte_dict(linha: sqlite3.Row) -> dict:
        d = dict(linha)
        d["ultima_sincronizacao"] = d.get("ultima_sincronizacao") or None
        d["monitorada"] = bool(d.get("url"))
        return d

    def fontes(self) -> list[dict]:
        with self._trava:
            linhas = self._c().execute(
                "SELECT * FROM fontes ORDER BY tribunal, sistema").fetchall()
        return [self._fonte_dict(x) for x in linhas]

    def fonte(self, id_fonte: str) -> dict | None:
        with self._trava:
            linha = self._c().execute("SELECT * FROM fontes WHERE id = ?",
                                      (id_fonte,)).fetchone()
        return self._fonte_dict(linha) if linha else None

    def salvar_fonte(self, tribunal: str, sistema: str, rotulo: str = "", url: str = "",
                     modo: str | None = None) -> dict:
        """Cria ou atualiza (a fonte é única por tribunal + sistema).

        A rota já lembrada não se perde quando a fonte é salva de novo sem
        endereço (a tela salva a fonte antes de cada primeira sincronização).
        """
        tribunal, sistema = (tribunal or "").strip().upper(), (sistema or "").strip().lower()
        id_ = self.id_fonte(tribunal, sistema)
        with self._trava:
            con = self._c()
            atual = con.execute("SELECT * FROM fontes WHERE id = ?", (id_,)).fetchone()
            if atual is None:
                con.execute(
                    "INSERT INTO fontes (id, tribunal, sistema, rotulo, modo, url, criada_em) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (id_, tribunal, sistema, rotulo or "", modo or ("capturado" if url else
                                                                  "automatico"),
                     url or "", _iso(_agora())))
            else:
                novo_rotulo = rotulo or atual["rotulo"]
                novo_url = url or atual["url"]
                novo_modo = modo or ("capturado" if url else atual["modo"])
                con.execute("UPDATE fontes SET rotulo = ?, url = ?, modo = ? WHERE id = ?",
                            (novo_rotulo, novo_url, novo_modo, id_))
        return self.fonte(id_)

    def atualizar_fonte(self, id_fonte: str, **campos) -> dict | None:
        validos = {k: v for k, v in campos.items()
                   if k in ("rotulo", "modo", "url", "menu", "ultima_sincronizacao",
                            "ultimo_erro")}
        if validos:
            for k, v in list(validos.items()):
                if isinstance(v, datetime):
                    validos[k] = _iso(v)
                elif v is None:
                    validos[k] = ""
            sets = ",".join(f"{k} = ?" for k in validos)
            with self._trava:
                self._c().execute(f"UPDATE fontes SET {sets} WHERE id = ?",
                                  (*validos.values(), id_fonte))
        return self.fonte(id_fonte)

    def remover_fonte(self, id_fonte: str) -> bool:
        """Tira a fonte; as audiências que ela trouxe continuam na pauta."""
        with self._trava:
            cur = self._c().execute("DELETE FROM fontes WHERE id = ?", (id_fonte,))
            return bool(cur.rowcount)

    # ---------------------------------------------------------------- meta
    def meta(self, chave: str) -> str:
        with self._trava:
            linha = self._c().execute("SELECT valor FROM meta WHERE chave = ?",
                                      (chave,)).fetchone()
        return linha["valor"] if linha else ""

    def definir_meta(self, chave: str, valor) -> None:
        if isinstance(valor, datetime):
            valor = _iso(valor)
        with self._trava:
            self._c().execute("INSERT INTO meta (chave, valor) VALUES (?, ?) ON CONFLICT(chave) "
                              "DO UPDATE SET valor = excluded.valor", (chave, str(valor or "")))
