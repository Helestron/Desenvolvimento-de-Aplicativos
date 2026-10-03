"""Servidor MCP (Model Context Protocol) do acervo, só de leitura.

É o que deixa o Claude Desktop - no chat e no Cowork - consultar os autos
baixados e as transcrições sem que o usuário tenha de anexar arquivo por
arquivo. O Claude Desktop inicia este programa sozinho (o registro fica no
claude_desktop_config.json, feito pela tela "Compartilhar com IA") e
conversa com ele pela entrada e saída padrão, uma mensagem JSON por linha.

Escrito sem a biblioteca 'mcp' de propósito: o protocolo usado aqui é
pequeno (initialize, tools/list, tools/call, ping), e uma dependência a
menos é uma falha de instalação a menos.

    python -m app.compartilhar.mcp_servidor --pasta "C:\\...\\Acervo"

Nada é gravado fora da pasta de cache do próprio acervo (_ia), e nenhuma
ferramenta altera ou apaga arquivo.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .. import __version__
from ..nucleo import cnj
from . import textos

log = logging.getLogger("mcp")

VERSOES = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
LIMITE_CARACTERES = 90_000   # por resposta; o resto vem por páginas
_PASTAS_FORA = {"_ia", "produtos", "_controle", ".claude", "_audio"}

INSTRUCOES = (
    "Acervo judicial local do Assessor Integrado: autos em PDF (um arquivo por "
    "processo, nomeado com o número CNJ) e transcrições de audiência em DOCX. "
    "Use listar_acervo para ver o que há, ler_processo para ler os autos por "
    "faixa de folhas, buscar para localizar termos e ler_transcricao para as "
    "audiências. Cite sempre a folha (fl.) de onde tirou cada informação e não "
    "afirme nada que não esteja nos autos."
)


class Acervo:
    """Acesso de leitura à pasta compartilhada."""

    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self.cache = self.raiz / "_ia" / "texto"

    # ------------------------------------------------------------ descoberta
    def _arquivos(self, sufixo: str) -> list[Path]:
        if not self.raiz.exists():
            return []
        saida = []
        for p in self.raiz.rglob(f"*{sufixo}"):
            partes = {q.lower() for q in p.relative_to(self.raiz).parts[:-1]}
            # _ia é cache; Produtos é o que a própria IA escreveu; _controle
            # guarda mídias e diagnóstico; ~$ é o arquivo-trava do Word.
            if partes & _PASTAS_FORA or p.name.startswith("~$") \
                    or p.name.endswith((".parcial", ".tmp")):
                continue
            saida.append(p)
        return sorted(saida)

    def pdfs(self) -> dict[str, Path]:
        achados: dict[str, Path] = {}
        for p in self._arquivos(".pdf"):
            try:
                n = cnj.ler(p.stem)
            except cnj.NumeroInvalido:
                continue
            # O mais recente vence, se o mesmo processo estiver em dois lotes
            atual = achados.get(n.nome_arquivo)
            if atual is None or p.stat().st_mtime > atual.stat().st_mtime:
                achados[n.nome_arquivo] = p
        return achados

    def transcricoes(self) -> dict[str, list[Path]]:
        achados: dict[str, list[Path]] = {}
        for p in self._arquivos(".docx"):
            try:
                n = cnj.ler(p.stem)
            except cnj.NumeroInvalido:
                continue
            achados.setdefault(n.nome_arquivo, []).append(p)
        return achados

    def _chave(self, numero: str) -> str:
        return cnj.ler(numero).nome_arquivo

    def texto_processo(self, numero: str) -> tuple[Path, str]:
        chave = self._chave(numero)
        pdf = self.pdfs().get(chave)
        if pdf is None:
            raise LookupError(f"o processo {numero} não está no acervo")
        txt = textos.garantir_texto(pdf, self.cache / f"{chave}.txt")
        return pdf, txt.read_text(encoding="utf-8", errors="replace")

    # ------------------------------------------------------------ ferramentas
    def listar_acervo(self) -> str:
        pdfs = self.pdfs()
        trans = self.transcricoes()
        linhas = [f"Acervo: {self.raiz}", ""]
        linhas.append(f"Autos ({len(pdfs)}):")
        for chave, p in sorted(pdfs.items()):
            pags = textos.contar_paginas(p)
            linhas.append(f"- {chave} — {pags} fl. — {p.relative_to(self.raiz)}")
        linhas.append("")
        linhas.append(f"Transcrições de audiência ({sum(len(v) for v in trans.values())}):")
        for chave, lista in sorted(trans.items()):
            for p in lista:
                linhas.append(f"- {chave} — {p.relative_to(self.raiz)}")
        return "\n".join(linhas)

    def ler_processo(self, numero: str, folha_inicial: int = 1,
                     folha_final: int | None = None) -> str:
        pdf, texto = self.texto_processo(numero)
        total = textos.contar_paginas(pdf)
        folha_inicial = max(1, int(folha_inicial or 1))
        folha_final = int(folha_final or total or folha_inicial)
        trecho = textos.recortar_paginas(texto, folha_inicial, folha_final)
        aviso = ""
        if len(trecho) > LIMITE_CARACTERES:
            corte = trecho.rfind("=== [fl.", 0, LIMITE_CARACTERES)
            corte = corte if corte > 0 else LIMITE_CARACTERES
            ultima = textos.folha_na_posicao(trecho, corte - 1) or folha_inicial
            trecho = trecho[:corte]
            aviso = (f"\n[Resposta cortada no limite de tamanho: leia a partir "
                     f"da fl. {ultima + 1} com folha_inicial={ultima + 1}.]")
        cab = (f"Processo {cnj.ler(numero).formatado} — {total} folhas no total. "
               f"Mostrando fl. {folha_inicial} a {min(folha_final, total or folha_final)}.\n")
        if not trecho.strip():
            trecho = "[sem texto nestas folhas — podem ser imagens digitalizadas]"
        return cab + trecho + aviso

    def buscar(self, termo: str, numero: str | None = None) -> str:
        alvos = ([self._chave(numero)] if numero else sorted(self.pdfs()))
        linhas = []
        for chave in alvos:
            try:
                _, texto = self.texto_processo(chave)
            except LookupError as erro:
                linhas.append(str(erro))
                continue
            except Exception as erro:  # um PDF estragado não impede a busca nos outros
                linhas.append(f"{chave}: não foi possível ler os autos ({erro})")
                continue
            for folha, trecho in textos.buscar(texto, termo, limite=15):
                linhas.append(f"{chave}, fl. {folha}: …{trecho}…")
        for chave, lista in sorted(self.transcricoes().items()):
            if numero and chave != self._chave(numero):
                continue
            for p in lista:
                for _, trecho in textos.buscar(textos.texto_docx(p), termo, limite=10):
                    linhas.append(f"{chave}, transcrição {p.name}: …{trecho}…")
        return "\n".join(linhas) if linhas else f"Nenhuma ocorrência de '{termo}'."

    def ler_transcricao(self, numero: str) -> str:
        chave = self._chave(numero)
        lista = self.transcricoes().get(chave)
        if not lista:
            raise LookupError(f"não há transcrição do processo {numero}")
        partes = []
        for p in lista:
            partes.append(f"##### {p.relative_to(self.raiz)}\n")
            partes.append(textos.texto_docx(p))
        texto = "\n".join(partes)
        return texto[:LIMITE_CARACTERES]


FERRAMENTAS = [
    {
        "name": "listar_acervo",
        "title": "Listar o acervo",
        "description": "Lista os processos baixados (PDF, com número de folhas) "
                       "e as transcrições de audiência disponíveis.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "ler_processo",
        "title": "Ler os autos",
        "description": "Texto dos autos de um processo, por faixa de folhas. "
                       "Cada página vem marcada '=== [fl. N] ==='. Respostas "
                       "longas são cortadas: continue pela folha indicada.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "numero": {"type": "string", "description": "número CNJ do processo"},
                "folha_inicial": {"type": "integer", "minimum": 1},
                "folha_final": {"type": "integer", "minimum": 1},
            },
            "required": ["numero"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "buscar",
        "title": "Buscar no acervo",
        "description": "Procura um termo (sem diferenciar acento e maiúsculas) "
                       "nos autos e nas transcrições; devolve folha e trecho.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "termo": {"type": "string"},
                "numero": {"type": "string",
                           "description": "opcional: restringe a um processo"},
            },
            "required": ["termo"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "ler_transcricao",
        "title": "Ler transcrição de audiência",
        "description": "Texto integral da(s) transcrição(ões) de audiência do processo.",
        "inputSchema": {
            "type": "object",
            "properties": {"numero": {"type": "string"}},
            "required": ["numero"],
        },
        "annotations": {"readOnlyHint": True},
    },
]


class Servidor:
    def __init__(self, acervo: Acervo):
        self.acervo = acervo

    def tratar(self, msg: dict) -> dict | None:
        """Responde uma mensagem JSON-RPC. Notificação não tem resposta."""
        metodo = msg.get("method")
        ident = msg.get("id")
        if ident is None:          # notificação (initialized, cancelled...)
            return None
        try:
            resultado = self._despachar(metodo, msg.get("params") or {})
        except _ErroRPC as erro:
            return {"jsonrpc": "2.0", "id": ident,
                    "error": {"code": erro.codigo, "message": str(erro)}}
        return {"jsonrpc": "2.0", "id": ident, "result": resultado}

    def _despachar(self, metodo: str, params: dict):
        if metodo == "initialize":
            pedida = params.get("protocolVersion")
            versao = pedida if pedida in VERSOES else VERSOES[0]
            return {
                "protocolVersion": versao,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "assessor-integrado",
                               "title": "Assessor Integrado — acervo judicial",
                               "version": __version__},
                "instructions": INSTRUCOES,
            }
        if metodo == "ping":
            return {}
        if metodo == "tools/list":
            return {"tools": FERRAMENTAS}
        if metodo == "tools/call":
            return self._chamar(params.get("name"), params.get("arguments") or {})
        if metodo in ("resources/list", "prompts/list"):
            chave = metodo.split("/")[0]
            return {chave: []}
        raise _ErroRPC(-32601, f"método desconhecido: {metodo}")

    def _chamar(self, nome: str, args: dict) -> dict:
        funcoes = {
            "listar_acervo": lambda: self.acervo.listar_acervo(),
            "ler_processo": lambda: self.acervo.ler_processo(
                args["numero"], args.get("folha_inicial", 1), args.get("folha_final")),
            "buscar": lambda: self.acervo.buscar(args["termo"], args.get("numero")),
            "ler_transcricao": lambda: self.acervo.ler_transcricao(args["numero"]),
        }
        if nome not in funcoes:
            raise _ErroRPC(-32602, f"ferramenta desconhecida: {nome}")
        try:
            texto = funcoes[nome]()
            return {"content": [{"type": "text", "text": texto}], "isError": False}
        except (LookupError, cnj.NumeroInvalido, ValueError) as erro:
            return {"content": [{"type": "text", "text": f"Erro: {erro}"}], "isError": True}
        except Exception as erro:  # nunca derrubar o servidor por um arquivo ruim
            log.exception("falha em %s", nome)
            return {"content": [{"type": "text", "text": f"Erro inesperado: {erro}"}],
                    "isError": True}


class _ErroRPC(Exception):
    def __init__(self, codigo: int, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


def servir(raiz: Path, entrada=None, saida=None) -> None:
    """Laço principal: uma mensagem JSON por linha, até a entrada fechar."""
    entrada = entrada or sys.stdin.buffer
    saida = saida or sys.stdout.buffer
    servidor = Servidor(Acervo(raiz))
    for bruta in entrada:
        linha = bruta.decode("utf-8", errors="replace").strip()
        if not linha:
            continue
        try:
            msg = json.loads(linha)
        except ValueError:
            resposta = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "JSON inválido"}}
        else:
            lote = msg if isinstance(msg, list) else [msg]
            respostas = [r for r in (servidor.tratar(m) for m in lote) if r]
            if not respostas:
                continue
            resposta = respostas if isinstance(msg, list) else respostas[0]
        saida.write(json.dumps(resposta, ensure_ascii=False).encode("utf-8") + b"\n")
        saida.flush()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="assessor-mcp")
    p.add_argument("--pasta", required=True, type=Path, help="raiz do acervo")
    args = p.parse_args(argv)
    # stdout é o canal do protocolo: todo log vai para stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Biblioteca que imprima aviso com print() não pode sujar o canal do
    # protocolo: o print comum passa a ir para o stderr, e só as respostas
    # vão para o stdout verdadeiro.
    # Também no nível do sistema operacional: biblioteca em C (o MuPDF, por
    # exemplo) escreve direto no descritor 1. O protocolo passa a usar uma
    # cópia dele, e o 1 vira o stderr.
    try:
        sys.stdout.flush()
        canal = os.fdopen(os.dup(1), "wb")
        os.dup2(2, 1)
    except (OSError, ValueError, AttributeError):
        canal = sys.stdout.buffer
    sys.stdout = sys.stderr
    try:
        import pymupdf

        pymupdf.TOOLS.mupdf_display_errors(False)
        pymupdf.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass
    servir(args.pasta, saida=canal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
