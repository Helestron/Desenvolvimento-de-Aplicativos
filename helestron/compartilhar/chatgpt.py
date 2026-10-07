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
* PACOTE: uma pasta (e um .zip) com os autos, o texto com a marca de
  citação de cada página, as transcrições de audiência (quando houver), o
  índice e as instruções, pronta para arrastar para uma conversa ou um
  Projeto do ChatGPT.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import urllib.parse
import zipfile
from datetime import date, datetime, time as _hora
from pathlib import Path

from ..nucleo import cnj, sigilo, sistema
from . import preparo
from .claude import _abrir_terminal, entrada_mcp
from .mcp_servidor import Acervo

log = logging.getLogger("compartilhar.chatgpt")

URL_CHATGPT = "https://chatgpt.com/"
URL_DOWNLOAD_APP = "https://openai.com/chatgpt/download/"
LOJA_APP = "ms-windows-store://pdp/?productid=9PLM9XGG6VKS"
COMANDO_INSTALAR_CODEX = "irm https://chatgpt.com/codex/install.ps1 | iex"
NOME_MCP = "helestron"
# Os da versão anterior (Assessor Integrado - o desinstalador dela procurava
# os dois): saem ao registrar, ao remover e na limpeza do instalador.
NOMES_ANTIGOS = ("assessor_integrado", "assessor-integrado")
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
            "Use “Abrir no ChatGPT Work” ou, no cartão “Pacote para o ChatGPT”, "
            "“Gerar o pacote”.")
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


_CHAVE_NUA = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_chave(chave: str) -> str:
    return chave if _CHAVE_NUA.match(chave) else json.dumps(chave, ensure_ascii=False)


def _toml_valor(valor) -> str:
    """Um valor lido pelo tomllib, de volta em TOML (tabelas como inline)."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, float) and not math.isfinite(valor):
        return "nan" if math.isnan(valor) else ("inf" if valor > 0 else "-inf")
    if isinstance(valor, (int, float)):
        return repr(valor)
    if isinstance(valor, str):
        return _toml_texto(valor)
    if isinstance(valor, (list, tuple)):
        return "[" + ", ".join(_toml_valor(v) for v in valor) + "]"
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        return "{ " + ", ".join(f"{_toml_chave(str(k))} = {_toml_valor(v)}"
                                for k, v in valor.items()) + " }"
    if isinstance(valor, (date, _hora)):         # datetime é date
        return valor.isoformat()
    raise ValueError(f"valor TOML não suportado: {type(valor).__name__}")


def bloco_toml(pasta_acervo: Path, manter: dict | None = None) -> str:
    """O bloco do conector no config.toml. 'manter': o bloco que já estava
    lá, cujas outras chaves ficam (o reapontamento da instalação que mudou
    de pasta só troca o comando: o 'enabled = false' de quem desligou o
    conector, os prazos e as permissões das ferramentas continuam)."""
    e = entrada_mcp(pasta_acervo)
    args = ", ".join(_toml_texto(a) for a in e["args"])
    linhas = [f"[mcp_servers.{NOME_MCP}]",
              f"command = {_toml_texto(e['command'])}",
              f"args = [{args}]"]
    if e.get("env"):
        env = ", ".join(f"{k} = {_toml_texto(v)}" for k, v in e["env"].items())
        linhas.append(f"env = {{ {env} }}")
    outras = {str(k): v for k, v in (manter or {}).items() if k not in e}
    linhas.append(f"enabled = {_toml_valor(outras.pop('enabled', True))}")
    linhas += [f"{_toml_chave(k)} = {_toml_valor(v)}" for k, v in outras.items()]
    return "\n".join(linhas) + "\n"


def _sem_bloco(texto: str, nomes: tuple[str, ...] = (NOME_MCP, *NOMES_ANTIGOS)) -> str:
    """O config.toml sem o nosso bloco (e suas subtabelas), nem o da versão
    anterior ('nomes': os blocos que saem)."""
    linhas = texto.splitlines()
    saida, dentro = [], False
    nomes = "|".join(re.escape(n) for n in nomes)
    cab = re.compile(r"^\s*\[\s*mcp_servers\.(?:\"?)(?:" + nomes + r")(?:\"?)\s*(\.|\])")
    for linha in linhas:
        if linha.lstrip().startswith("["):
            dentro = bool(cab.match(linha))
        if not dentro:
            saida.append(linha)
    while saida and not saida[-1].strip():
        saida.pop()
    return "\n".join(saida)


def registrar_mcp_codex(pasta_acervo: Path, arquivo: Path | None = None,
                        manter: dict | None = None) -> Path:
    """Registra o conector do acervo para o ChatGPT Work e o Codex.

    Preserva o resto do config.toml, guarda cópia do anterior e confere que
    o resultado é TOML válido antes de trocar o arquivo. 'manter': o bloco
    atual do conector, cujas outras chaves ficam (bloco_toml).
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
    novo = (base + "\n\n" if base.strip() else "") + bloco_toml(pasta_acervo, manter)
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


def _copia_de_seguranca(arquivo: Path) -> Path:
    """Guarda o config.toml como está, ao lado, antes de mexer nele."""
    copia = arquivo.with_name(f"config.antes-do-helestron-{datetime.now():%Y%m%d-%H%M%S}.toml")
    n = 2
    while copia.exists():
        copia = arquivo.with_name(
            f"config.antes-do-helestron-{datetime.now():%Y%m%d-%H%M%S}-{n}.toml")
        n += 1
    shutil.copy2(arquivo, copia)
    return copia


def remover_mcp_codex(arquivo: Path | None = None,
                      nomes: tuple[str, ...] = (NOME_MCP, *NOMES_ANTIGOS)) -> bool:
    """Tira do config.toml o conector do acervo - e o da versão anterior
    (NOMES_ANTIGOS) -, guardando antes uma cópia do arquivo. O resto fica.
    Devolve se o arquivo mudou."""
    arquivo = Path(arquivo or arquivo_config_codex())
    try:
        atual = arquivo.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return False
    novo = _sem_bloco(atual, nomes) + "\n"
    if novo.strip() == atual.strip():
        return False
    _copia_de_seguranca(arquivo)
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(novo, encoding="utf-8", newline="\n")
    os.replace(tmp, arquivo)
    log.info("Conector retirado do ChatGPT/Codex em %s.", arquivo)
    return True


def remover_conectores_antigos_codex(arquivo: Path | None = None) -> bool:
    """Só o conector da versão anterior (Assessor Integrado); o do Helestron
    fica. Arquivo com TOML inválido não é tocado. Devolve se o arquivo mudou."""
    import tomllib

    arquivo = Path(arquivo or arquivo_config_codex())
    try:
        atual = arquivo.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError):
        return False
    try:
        tomllib.loads(atual)
    except tomllib.TOMLDecodeError as erro:
        log.warning("não mexi em %s: o TOML é inválido (%s)", arquivo, erro)
        return False
    novo = _sem_bloco(atual, NOMES_ANTIGOS) + "\n"
    try:
        tomllib.loads(novo)          # nunca gravar um arquivo que o app não leria
    except tomllib.TOMLDecodeError:
        return False
    return remover_mcp_codex(arquivo, NOMES_ANTIGOS)


def _config():
    try:
        from ..nucleo import config

        return config.carregar(criar=False)
    except Exception:
        return None


NOTA_PASTAS_DO_PACOTE = (
    "> **Neste pacote, as pastas têm outro nome:** os autos (`Processos/`) estão em "
    "`autos/`, o texto com a marca de citação de cada página (`_ia/texto/`) em `texto/` e "
    "as transcrições de audiência (`Transcricoes/`) em `audiencias/`. Os nomes dos "
    "arquivos são os mesmos.\n\n")
PREFIXO_PACOTE = "Pacote para o ChatGPT"
_RE_NUMERO_CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?:-\d{2})?")


class Pacote(tuple):
    """(pasta, zip) do pacote - desempacota como antes -, com o que mais quem
    chamou precisa mostrar: 'faltaram' (números pedidos que não estão no
    acervo, ou são sigilosos), 'avisos' (frases para a tela) e 'tamanho_zip'
    (bytes)."""

    def __new__(cls, pasta: Path, arquivo_zip: Path, faltaram=(), avisos=(), tamanho_zip=0):
        obj = super().__new__(cls, (pasta, arquivo_zip))
        obj.faltaram = list(faltaram)
        obj.avisos = list(avisos)
        obj.tamanho_zip = int(tamanho_zip)
        return obj

    @property
    def pasta(self) -> Path:
        return self[0]

    @property
    def arquivo_zip(self) -> Path:
        return self[1]

    @property
    def grande_demais(self) -> bool:
        return self.tamanho_zip > LIMITE_ARQUIVO_MB * 1024 * 1024


def _frase_faltaram(faltaram: list[str]) -> str:
    if len(faltaram) == 1:
        return (f"O processo {faltaram[0]} não está no acervo (ou corre em segredo de justiça) "
                "e não foi para o pacote.")
    return (f"Os processos {', '.join(faltaram)} não estão no acervo (ou correm em segredo "
            "de justiça) e não foram para o pacote.")


def gerar_pacote(acervo: Path, destino: Path, numeros: list[str] | None = None,
                 incluir_pdf: bool = True, incluir_texto: bool | None = None,
                 progresso=None, cfg=None) -> Pacote:
    """Monta a pasta e o .zip para levar ao ChatGPT: os autos (autos/), o
    texto com a marca de citação de cada página (texto/), as transcrições de
    audiência, quando houver (audiencias/), o índice (só do que foi
    empacotado, com os caminhos do pacote) e as instruções.

    'numeros' restringe aos processos indicados (padrão: o acervo inteiro);
    o que foi pedido e não está no acervo (ou é sigiloso) volta em
    'faltaram', com um aviso. 'incluir_texto' em branco segue a configuração
    ([compartilhar] incluir_texto). Devolve o Pacote, que desempacota como
    (pasta, zip); 'avisos' traz o que a tela deve mostrar (número que
    faltou, arquivo ou .zip acima do limite do ChatGPT, pacote antigo que
    não pôde perder o sigiloso). Os textos são atualizados antes (preparo),
    e os pacotes antigos de 'destino' perdem o que for de processo que
    virou sigiloso.
    """
    acervo = Path(acervo)
    if cfg is None:
        cfg = _config()
    if incluir_texto is None:
        incluir_texto = cfg.flag("compartilhar", "incluir_texto") if cfg is not None else True
    rel = preparo.atualizar_contexto(cfg, raiz=acervo, extrair_texto=incluir_texto)
    presos = getattr(rel, "sigilosos_no_acervo", None)
    if isinstance(presos, list) and presos:
        # O pacote nunca levaria o sigiloso (o Acervo o tira), mas a regra é
        # uma só: com os autos de um sigiloso presos no acervo, nada se
        # compartilha.
        raise preparo.SigilosoNoAcervo(presos, cfg, getattr(rel, "motivos", None))
    ac = Acervo(acervo) if cfg is None else Acervo(acervo, sigilosos=cfg.pasta_sigilosos)
    with ac.pedido():
        pdfs = ac.pdfs()
        trans = ac.transcricoes()
        sigilosas = ac.sigilosas()
    avisos = retirar_sigilosos_dos_pacotes(Path(destino), sigilosas)
    faltaram: list[str] = []
    if numeros:
        escolhidos: dict[str, str] = {}
        for n in numeros:
            escolhidos.setdefault(cnj.ler_nome_arquivo(n).nome_arquivo, str(n))
        faltaram = [n for k, n in escolhidos.items() if k not in pdfs and k not in trans]
        pdfs = {k: v for k, v in pdfs.items() if k in escolhidos}
        trans = {k: v for k, v in trans.items() if k in escolhidos}
    if not pdfs and not trans:
        raise LookupError("não há processo nem transcrição no acervo para empacotar"
                          + (f" (pedidos e não encontrados: {', '.join(faltaram)})"
                             if faltaram else ""))
    if faltaram:
        avisos.append(_frase_faltaram(faltaram))

    nome = f"{PREFIXO_PACOTE} {datetime.now():%Y-%m-%d %Hh%M}"
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
    if (acervo / "AGENTS.md").exists():
        arquivos.append((acervo / "AGENTS.md", "LEIA-ME - instrucoes.md"))

    grandes = []
    total = len(arquivos)
    for i, (origem, rel_) in enumerate(arquivos, 1):
        alvo = pasta / rel_
        alvo.parent.mkdir(parents=True, exist_ok=True)
        if rel_.endswith(".md"):
            # As instruções falam das pastas do acervo; aqui elas têm outro nome.
            # (em bytes: o Windows não troca as quebras de linha)
            texto = origem.read_bytes().decode("utf-8-sig", errors="replace")
            alvo.write_bytes((NOTA_PASTAS_DO_PACOTE + texto).encode("utf-8"))
        else:
            shutil.copy2(origem, alvo)
        if origem.stat().st_size > LIMITE_ARQUIVO_MB * 1024 * 1024:
            grandes.append(origem.name)
        if progresso:
            progresso(i, total, origem.name)
    # O índice só do que foi empacotado, com os caminhos do pacote
    (pasta / "INDICE.md").write_bytes(
        _indice_do_pacote(ac, pdfs, trans, incluir_pdf, incluir_texto).encode("utf-8"))
    if grandes:
        avisos.append(f"Arquivos acima de {LIMITE_ARQUIVO_MB} MB, que o ChatGPT pode recusar: "
                      + ", ".join(grandes) + ".")

    arquivo_zip = pasta.with_suffix(".zip")
    with zipfile.ZipFile(arquivo_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for f in sorted(pasta.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(pasta).as_posix())
    tamanho = arquivo_zip.stat().st_size
    if tamanho > LIMITE_ARQUIVO_MB * 1024 * 1024:
        avisos.append(f"O .zip tem {tamanho / 1024 / 1024:.0f} MB, acima do que o ChatGPT aceita "
                      f"(cerca de {LIMITE_ARQUIVO_MB} MB): em vez dele, arraste os arquivos da "
                      "pasta do pacote (o texto e as instruções primeiro), ou gere pacotes "
                      "menores, com menos processos.")
    for frase in avisos:
        log.warning("Pacote para o ChatGPT: %s", frase)
    log.info("Pacote para o ChatGPT: %s (%d arquivo(s)). Leva %s.", pasta, total + 1,
             conteudo_do_pacote(pdfs, trans, incluir_pdf, incluir_texto))
    return Pacote(pasta, arquivo_zip, faltaram, avisos, tamanho)


def _indice_do_pacote(ac: Acervo, pdfs: dict, trans: dict, incluir_pdf: bool,
                      incluir_texto: bool) -> str:
    """O INDICE.md do pacote: só o que ele leva, com os caminhos dele."""
    def caminho(tipo, chave, arquivo):
        if tipo == "autos":
            return f"autos/{chave}.pdf" if incluir_pdf else None
        if tipo == "texto":
            return f"texto/{chave}.txt" if incluir_texto else None
        return f"audiencias/{Path(arquivo).name}"

    return preparo._indice(ac, pdfs, trans, caminho)


def _chave_do_nome(nome: str) -> str | None:
    """A chave do processo num nome de arquivo ("X-01.pdf") ou num número
    solto ("0700999-61.2024.8.02.0001": Path.stem cortaria o ".0001")."""
    try:
        return cnj.ler_nome_arquivo(str(nome)).nome_arquivo
    except cnj.NumeroInvalido:
        return None


def retirar_sigilosos_dos_pacotes(pasta_pacotes: Path, sigilosas) -> list[str]:
    """Tira dos pacotes já gerados (pastas e .zip "Pacote para o ChatGPT...")
    o que é de processo que hoje se sabe sigiloso: os autos, o texto, a
    transcrição e as linhas do índice e das instruções com o número dele.
    Devolve avisos do que não pôde ser tirado (arquivo aberto): o pacote
    antigo fica na pasta e poderia ser arrastado de novo para o ChatGPT."""
    avisos: list[str] = []
    if not sigilosas:
        return avisos
    try:
        itens = sorted(Path(pasta_pacotes).glob(f"{PREFIXO_PACOTE}*"))
    except OSError:
        return avisos

    def sigiloso(nome: str) -> bool:
        chave = _chave_do_nome(nome)
        return chave is not None and sigilo.contem(sigilosas, chave)

    for item in itens:
        try:
            if item.is_dir():
                for f in sorted(item.rglob("*")):
                    if not f.is_file():
                        continue
                    if sigiloso(f.name):
                        f.unlink()
                        log.warning("Retirei do pacote antigo %s: o processo é sigiloso.", f)
                    elif f.suffix.lower() == ".md":
                        _tirar_linhas_sigilosas(f, sigilosas)
            elif item.suffix.lower() == ".zip" and item.is_file():
                _refazer_zip_sem_sigilosos(item, sigiloso, sigilosas)
        except (OSError, zipfile.BadZipFile) as erro:
            avisos.append(f"Não consegui tirar do pacote antigo “{item.name}” o que é de processo "
                          f"em segredo de justiça ({erro}): apague-o à mão, em {item.parent}.")
            log.warning("ATENÇÃO: pacote antigo com processo sigiloso: %s (%s)", item, erro)
    return avisos


def _linhas_sem_sigilosos(texto: str, sigilosas) -> str:
    saida = []
    for linha in texto.split("\n"):
        chaves = {k for k in (_chave_do_nome(x) for x in _RE_NUMERO_CNJ.findall(linha)) if k}
        if any(sigilo.contem(sigilosas, k) for k in chaves):
            continue
        saida.append(linha)
    return "\n".join(saida)


def _tirar_linhas_sigilosas(arquivo: Path, sigilosas) -> None:
    texto = arquivo.read_bytes().decode("utf-8-sig", errors="replace")
    novo = _linhas_sem_sigilosos(texto, sigilosas)
    if novo != texto:
        arquivo.write_bytes(novo.encode("utf-8"))


def _refazer_zip_sem_sigilosos(arquivo: Path, sigiloso, sigilosas) -> None:
    """O .zip não se edita no lugar: é refeito sem os arquivos do sigiloso e
    com o índice sem as linhas dele, e troca o antigo."""
    with zipfile.ZipFile(arquivo) as z:
        infos = z.infolist()
        tirar = {i.filename for i in infos if sigiloso(Path(i.filename).name)}
        trocar = {}
        for i in infos:
            if i.filename.lower().endswith(".md") and i.filename not in tirar:
                texto = z.read(i.filename).decode("utf-8-sig", errors="replace")
                novo = _linhas_sem_sigilosos(texto, sigilosas)
                if novo != texto:
                    trocar[i.filename] = novo
        if not tirar and not trocar:
            return
        tmp = arquivo.with_name(arquivo.name + ".tmp")
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as saida:
                for i in infos:
                    if i.filename in tirar:
                        continue
                    if i.filename in trocar:
                        saida.writestr(i, trocar[i.filename].encode("utf-8"))
                        continue
                    # Os autos, um a um e sem carregá-los inteiros na memória
                    with z.open(i) as origem, saida.open(i, "w", force_zip64=True) as alvo:
                        shutil.copyfileobj(origem, alvo, 1024 * 1024)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    os.replace(tmp, arquivo)
    log.warning("Retirei do pacote antigo %s o que era de processo sigiloso.", arquivo.name)


def _contar(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def conteudo_do_pacote(pdfs: dict, trans: dict, incluir_pdf: bool = True,
                       incluir_texto: bool = True) -> str:
    """O que o pacote leva, numa frase: "2 processos (autos e texto com a
    marca de citação de cada página), 1 transcrição de audiência, o índice e
    as instruções"."""
    itens = []
    if pdfs:
        leva = " e ".join(o for o, sim in (("autos", incluir_pdf),
                                           ("texto com a marca de citação de cada página",
                                            incluir_texto)) if sim)
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
