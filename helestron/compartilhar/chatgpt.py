"""Integração com o ChatGPT (OpenAI): ChatGPT Work, Codex, nuvem e pacote.

O "GPT Work" é o modo Work do novo app ChatGPT para Windows (lançado em
julho de 2026, ao lado dos modos Chat e Codex). Ele trabalha numa pasta do
computador ("projeto local": ChatGPT > Work > Ctrl+O), lê o AGENTS.md da
pasta e aceita servidores MCP locais. Caminhos que a tela oferece, do mais
integrado ao mais simples:

* CHATGPT WORK: o programa copia o caminho do acervo e tenta abrir o app
  direto na pasta; registra também o conector MCP do acervo no
  %USERPROFILE%\\.codex\\config.toml, que o Work e o Codex leem;
* CODEX (agente da OpenAI no terminal): abre DENTRO do acervo e lê sozinho
  o AGENTS.md - o equivalente ao Claude Code;
* ESPELHO NA NUVEM (nuvem.py): o acervo copiado para o OneDrive/Google
  Drive, que os conectores do ChatGPT leem;
* PACOTE: uma pasta (e um .zip) com os autos, o texto com as folhas
  marcadas, as transcrições de audiência (quando houver), o índice e as
  instruções, pronta para arrastar para uma conversa ou um Projeto do
  ChatGPT.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

from ..nucleo import cnj, sistema
from . import preparo
from .claude import _abrir_terminal, entrada_mcp
from .mcp_servidor import Acervo

log = logging.getLogger("compartilhar.chatgpt")

URL_CHATGPT = "https://chatgpt.com/"
URL_DOWNLOAD_APP = "https://openai.com/chatgpt/download/"
LOJA_APP = "ms-windows-store://pdp/?productid=9PLM9XGG6VKS"
COMANDO_INSTALAR_CODEX = "irm https://chatgpt.com/codex/install.ps1 | iex"
NOME_MCP = "helestron"
NOMES_ANTIGOS = ("assessor_integrado",)    # o da versão anterior: sai ao registrar
LIMITE_ARQUIVO_MB = 500     # o ChatGPT recusa arquivo acima de ~512 MB


def achar_codex() -> Path | None:
    achado = shutil.which("codex")
    if achado:
        return Path(achado)
    if os.environ.get("APPDATA"):
        c = Path(os.environ["APPDATA"]) / "npm" / "codex.cmd"
        if c.is_file():
            return c
    return None


def abrir_codex(pasta: Path) -> None:
    exe = achar_codex()
    if exe is None:
        raise FileNotFoundError(
            "O Codex (agente da OpenAI) não está instalado neste computador. "
            "Use “Abrir no ChatGPT Work” ou “Gerar pacote para o ChatGPT”.")
    _abrir_terminal(pasta, exe, "Codex - Acervo")


def abrir_chatgpt() -> None:
    sistema.abrir_endereco(URL_CHATGPT)


def chatgpt_desktop_instalado() -> bool:
    """O app ChatGPT (Microsoft Store) está instalado?"""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return False
    pacotes = Path(local) / "Packages"
    return any(pacotes.glob("OpenAI.ChatGPT*")) or any(pacotes.glob("*ChatGPT*"))


def instalar_chatgpt_desktop() -> None:
    """Abre a página do app na Microsoft Store (sem administrador)."""
    if sistema.NO_WINDOWS:
        try:
            os.startfile(LOJA_APP)  # type: ignore[attr-defined]
            return
        except OSError:
            pass
    sistema.abrir_endereco(URL_DOWNLOAD_APP)


def url_work(pasta: Path, prompt: str = "") -> str:
    """codex://threads/new?path=...: nova tarefa no app, já na pasta.

    É o link que o próprio app registra; no Windows ele ainda falha em
    algumas versões - por isso a tela sempre mostra também o caminho manual
    (Work > Ctrl+O > colar o caminho, que já vai copiado).
    """
    consulta = [("path", str(Path(pasta).resolve()))]
    if prompt:
        consulta.append(("prompt", prompt))
    return "codex://threads/new?" + urllib.parse.urlencode(consulta, quote_via=urllib.parse.quote)


def abrir_chatgpt_work(pasta: Path, prompt: str = "") -> bool:
    """Tenta abrir o ChatGPT Work na pasta. False = sem o app (abre a web)."""
    if sistema.NO_WINDOWS and chatgpt_desktop_instalado():
        try:
            os.startfile(url_work(pasta, prompt))  # type: ignore[attr-defined]
            return True
        except OSError:
            log.info("o link codex:// não abriu; o usuário segue pelo Ctrl+O")
            return True
    abrir_chatgpt()
    return False


# ------------------------------------------------ conector MCP (config.toml)
def arquivo_config_codex() -> Path:
    """%CODEX_HOME%\\config.toml, ou %USERPROFILE%\\.codex\\config.toml."""
    base = os.environ.get("CODEX_HOME")
    pasta = Path(base) if base else Path.home() / ".codex"
    return pasta / "config.toml"


def _toml_texto(valor: str) -> str:
    # Literal ('...') não interpreta barra invertida - ideal para caminho do
    # Windows; se o texto tiver aspas simples, usa-se a forma com escape.
    if "'" not in valor and "\n" not in valor:
        return f"'{valor}'"
    return json.dumps(valor, ensure_ascii=False)


def bloco_toml(pasta_acervo: Path) -> str:
    e = entrada_mcp(pasta_acervo)
    args = ", ".join(_toml_texto(a) for a in e["args"])
    linhas = [f"[mcp_servers.{NOME_MCP}]",
              f"command = {_toml_texto(e['command'])}",
              f"args = [{args}]"]
    if e.get("env"):
        env = ", ".join(f"{k} = {_toml_texto(v)}" for k, v in e["env"].items())
        linhas.append(f"env = {{ {env} }}")
    linhas.append("enabled = true")
    return "\n".join(linhas) + "\n"


def _sem_bloco(texto: str) -> str:
    """O config.toml sem o nosso bloco (e suas subtabelas), nem o da versão
    anterior."""
    linhas = texto.splitlines()
    saida, dentro = [], False
    nomes = "|".join(re.escape(n) for n in (NOME_MCP, *NOMES_ANTIGOS))
    cab = re.compile(r"^\s*\[\s*mcp_servers\.(?:\"?)(?:" + nomes + r")(?:\"?)\s*(\.|\])")
    for linha in linhas:
        if linha.lstrip().startswith("["):
            dentro = bool(cab.match(linha))
        if not dentro:
            saida.append(linha)
    while saida and not saida[-1].strip():
        saida.pop()
    return "\n".join(saida)


def registrar_mcp_codex(pasta_acervo: Path, arquivo: Path | None = None) -> Path:
    """Registra o conector do acervo para o ChatGPT Work e o Codex.

    Preserva o resto do config.toml, guarda cópia do anterior e confere que
    o resultado é TOML válido antes de trocar o arquivo.
    """
    import tomllib

    arquivo = Path(arquivo or arquivo_config_codex())
    try:
        atual = arquivo.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        atual = ""
    if atual.strip():
        try:
            tomllib.loads(atual)
        except tomllib.TOMLDecodeError as erro:
            raise ValueError(f"o arquivo {arquivo} tem TOML inválido ({erro}); corrija-o "
                             "ou apague-o e tente de novo") from erro
    base = _sem_bloco(atual)
    novo = (base + "\n\n" if base.strip() else "") + bloco_toml(pasta_acervo)
    tomllib.loads(novo)          # nunca gravar um arquivo que o app não leria
    if novo == atual:
        return arquivo
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if arquivo.exists():
        shutil.copy2(arquivo, arquivo.with_name(
            f"config.antes-do-helestron-{datetime.now():%Y%m%d-%H%M%S}.toml"))
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(novo, encoding="utf-8", newline="\n")
    os.replace(tmp, arquivo)
    log.info("Conector do acervo registrado para o ChatGPT/Codex em %s.", arquivo)
    return arquivo


def mcp_codex_registrado(arquivo: Path | None = None, pasta_acervo: Path | None = None) -> bool:
    """O conector está no config.toml? Com 'pasta_acervo', só conta se ele
    aponta para essa pasta (depois de trocar o acervo, é preciso reconectar)."""
    import tomllib

    try:
        dados = tomllib.loads(Path(arquivo or arquivo_config_codex()).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    entrada = (dados.get("mcp_servers") or {}).get(NOME_MCP)
    if not isinstance(entrada, dict):
        return False
    if pasta_acervo is None:
        return True
    return str(Path(pasta_acervo).resolve()) in (entrada.get("args") or [])


def remover_mcp_codex(arquivo: Path | None = None) -> bool:
    arquivo = Path(arquivo or arquivo_config_codex())
    try:
        atual = arquivo.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return False
    novo = _sem_bloco(atual) + "\n"
    if novo.strip() == atual.strip():
        return False
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(novo, encoding="utf-8", newline="\n")
    os.replace(tmp, arquivo)
    return True


def _config():
    try:
        from ..nucleo import config

        return config.carregar(criar=False)
    except Exception:
        return None


NOTA_PASTAS_DO_PACOTE = (
    "> **Neste pacote, as pastas têm outro nome:** os autos (`Processos/`) estão em "
    "`autos/`, o texto com as folhas marcadas (`_ia/texto/`) em `texto/` e as "
    "transcrições de audiência (`Transcricoes/`) em `audiencias/`. Os nomes dos "
    "arquivos são os mesmos.\n\n")


def gerar_pacote(acervo: Path, destino: Path, numeros: list[str] | None = None,
                 incluir_pdf: bool = True, incluir_texto: bool | None = None,
                 progresso=None, cfg=None) -> tuple[Path, Path]:
    """Monta a pasta e o .zip para levar ao ChatGPT: os autos (autos/), o
    texto com as páginas marcadas (texto/), as transcrições de audiência,
    quando houver (audiencias/), o índice e as instruções.

    'numeros' restringe aos processos indicados (padrão: o acervo inteiro).
    'incluir_texto' em branco segue a configuração ([compartilhar]
    incluir_texto). Devolve (pasta, zip). Os textos são atualizados antes
    (preparo).
    """
    acervo = Path(acervo)
    if cfg is None:
        cfg = _config()
    if incluir_texto is None:
        incluir_texto = cfg.flag("compartilhar", "incluir_texto") if cfg is not None else True
    preparo.atualizar_contexto(cfg, raiz=acervo, extrair_texto=incluir_texto)
    ac = Acervo(acervo) if cfg is None else Acervo(acervo, sigilosos=cfg.pasta_sigilosos)
    pdfs = ac.pdfs()
    trans = ac.transcricoes()
    if numeros:
        escolhidos = {cnj.ler_nome_arquivo(n).nome_arquivo for n in numeros}
        pdfs = {k: v for k, v in pdfs.items() if k in escolhidos}
        trans = {k: v for k, v in trans.items() if k in escolhidos}
    if not pdfs and not trans:
        raise LookupError("não há processo nem transcrição no acervo para empacotar")

    nome = f"Pacote para o ChatGPT {datetime.now():%Y-%m-%d %Hh%M}"
    pasta = Path(destino) / nome
    n = 2
    while pasta.exists() or pasta.with_suffix(".zip").exists():
        pasta = Path(destino) / f"{nome} ({n})"
        n += 1
    pasta.mkdir(parents=True)
    arquivos: list[tuple[Path, str]] = []
    for chave, pdf in sorted(pdfs.items()):
        if incluir_pdf:
            arquivos.append((pdf, f"autos/{chave}.pdf"))
        txt = ac.cache / f"{chave}.txt"
        if incluir_texto and txt.exists():
            arquivos.append((txt, f"texto/{chave}.txt"))
    for chave, lista in sorted(trans.items()):
        for t in lista:
            arquivos.append((t, f"audiencias/{t.name}"))
    for nome_ctx in ("AGENTS.md", "INDICE.md"):
        if (acervo / nome_ctx).exists():
            arquivos.append((acervo / nome_ctx,
                             "LEIA-ME - instrucoes.md" if nome_ctx == "AGENTS.md" else nome_ctx))

    grandes = []
    total = len(arquivos)
    for i, (origem, rel) in enumerate(arquivos, 1):
        alvo = pasta / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".md"):
            # As instruções e o índice falam das pastas do acervo; aqui elas
            # têm outro nome.
            # (em bytes: o Windows não troca as quebras de linha)
            texto = origem.read_bytes().decode("utf-8-sig", errors="replace")
            alvo.write_bytes((NOTA_PASTAS_DO_PACOTE + texto).encode("utf-8"))
        else:
            shutil.copy2(origem, alvo)
        if origem.stat().st_size > LIMITE_ARQUIVO_MB * 1024 * 1024:
            grandes.append(origem.name)
        if progresso:
            progresso(i, total, origem.name)
    if grandes:
        log.warning("Arquivos acima de %d MB (o ChatGPT pode recusar): %s",
                    LIMITE_ARQUIVO_MB, ", ".join(grandes))

    arquivo_zip = pasta.with_suffix(".zip")
    with zipfile.ZipFile(arquivo_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for f in sorted(pasta.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(pasta).as_posix())
    log.info("Pacote para o ChatGPT: %s (%d arquivo(s)). Leva %s.", pasta, total,
             conteudo_do_pacote(pdfs, trans, incluir_pdf, incluir_texto))
    return pasta, arquivo_zip


def _contar(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def conteudo_do_pacote(pdfs: dict, trans: dict, incluir_pdf: bool = True,
                       incluir_texto: bool = True) -> str:
    """O que o pacote leva, numa frase: "2 processos (autos e texto com as
    páginas marcadas), 1 transcrição de audiência, o índice e as instruções"."""
    itens = []
    if pdfs:
        leva = " e ".join(o for o, sim in (("autos", incluir_pdf),
                                           ("texto com as páginas marcadas", incluir_texto)) if sim)
        itens.append(_contar(len(pdfs), "processo", "processos") + (f" ({leva})" if leva else ""))
    n = sum(len(v) for v in trans.values())
    if n:
        itens.append(_contar(n, "transcrição de audiência", "transcrições de audiência"))
    itens += ["o índice", "as instruções"]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def estado(pasta_acervo: Path | None = None) -> dict:
    """Resumo para a tela. "mcp" só é verdadeiro se o conector aponta para o
    acervo atual ('pasta_acervo'; em branco, o do config.ini)."""
    if pasta_acervo is None:
        cfg = _config()
        pasta_acervo = cfg.pasta_acervo if cfg is not None else None
    codex = achar_codex()
    return {"codex": str(codex) if codex else "",
            "app": chatgpt_desktop_instalado(),
            "mcp": mcp_codex_registrado(pasta_acervo=pasta_acervo)}
