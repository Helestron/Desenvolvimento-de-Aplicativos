"""Integração com o Claude: Claude Code (terminal) e Claude Desktop/Cowork.

Duas portas de entrada, que se completam:

* CLAUDE CODE abre DENTRO da pasta do acervo e lê sozinho o CLAUDE.md e a
  habilidade .claude/skills/acervo-judicial - não há nada a "enviar": a
  pasta inteira fica ao alcance dele, local, no próprio computador.

* CLAUDE DESKTOP (chat e Cowork) recebe o acervo como um conector MCP
  local: o programa registra no claude_desktop_config.json o servidor
  'assessor-integrado' (app/compartilhar/mcp_servidor.py), que dá ao
  Claude as ferramentas listar_acervo, ler_processo, buscar e
  ler_transcricao - só de leitura. No Cowork, além disso, o usuário pode
  conceder a pasta do acervo diretamente.

Armadilha herdada da base: com ANTHROPIC_API_KEY no ambiente, o Claude Code
usa a chave em vez da conta logada, e o usuário passa a pagar por uso sem
perceber. O terminal é aberto SEM essas variáveis.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path

from ..nucleo import caminhos, sistema

log = logging.getLogger("compartilhar.claude")

NOME_MCP = "assessor-integrado"
URL_DOWNLOAD_DESKTOP = "https://claude.ai/download"
# Instalador do Claude Desktop para Windows (pacote MSIX, por usuário).
URL_INSTALADOR_DESKTOP = "https://claude.ai/api/desktop/win32/x64/setup/latest/redirect"
URL_DOC_CODE = "https://docs.claude.com/pt-BR/docs/claude-code/overview"
# Instalador oficial (nativo) do Claude Code para Windows, por usuário.
COMANDO_INSTALAR_CODE = "irm https://claude.ai/install.ps1 | iex"


# ------------------------------------------------------------- Claude Code
def _candidatos_code() -> list[Path]:
    env = os.environ
    casa = Path.home()
    lista = [casa / ".local" / "bin" / "claude.exe"]
    if env.get("LOCALAPPDATA"):
        lista.append(Path(env["LOCALAPPDATA"]) / "Programs" / "claude" / "claude.exe")
    if env.get("APPDATA"):
        lista.append(Path(env["APPDATA"]) / "npm" / "claude.cmd")
    return lista


def achar_claude_code() -> Path | None:
    """Onde está o executável do Claude Code, ou None."""
    achado = shutil.which("claude")
    if achado:
        return Path(achado)
    for c in _candidatos_code():
        if c.is_file():
            return c
    # Cópia baixada pelo Claude Desktop: uma subpasta por versão. A mais
    # nova é a de data mais recente (ordem alfabética erra: 0.2.10 < 0.2.9).
    if os.environ.get("APPDATA"):
        pasta = Path(os.environ["APPDATA"]) / "Claude" / "claude-code"
        versoes = sorted(pasta.glob("*/claude.exe"), key=lambda p: p.stat().st_mtime)
        if versoes:
            return versoes[-1]
    extensoes = Path.home() / ".vscode" / "extensions"
    binarios = sorted(extensoes.glob("anthropic.claude-code-*/resources/native-binary/claude.exe"),
                      key=lambda p: p.stat().st_mtime)
    return binarios[-1] if binarios else None


def linha_console(pasta: Path, exe: str, titulo: str) -> str:
    """A linha de comando do console clássico (sem o Windows Terminal).

    Vai pronta, como TEXTO: numa lista, o Python escaparia as aspas internas
    com \\", que o cmd.exe não entende (o executável não abriria). Com /s, o
    cmd tira só a primeira e a última aspa e mantém as do meio, o que protege
    caminho com espaço, "&" ou parênteses. O pushd entra na pasta mesmo que
    seja de rede (\\\\servidor\\...), que o cmd.exe não aceita como pasta
    atual: sem ele, o agente trabalharia em C:\\Windows.
    """
    return f'cmd.exe /s /k "title {titulo}& pushd "{pasta}" && "{exe}""'


def _abrir_terminal(pasta: Path, executavel: Path, titulo: str) -> None:
    """Abre um terminal novo na pasta, rodando o executável.

    Windows Terminal quando houver (fica melhor), senão o console clássico.
    O ambiente vai sem chaves de API (ver docstring do módulo).
    """
    pasta = Path(pasta)
    env = sistema.ambiente_sem_chaves()
    exe = str(executavel)
    if not sistema.NO_WINDOWS:  # desenvolvimento/testes fora do Windows
        subprocess.Popen([exe], cwd=str(pasta), env=env)
        return
    wt = shutil.which("wt.exe") or shutil.which("wt")
    if wt:
        # Um item por palavra: o Windows Terminal remonta a linha e põe aspas
        # no que tem espaço. O pushd cobre a pasta de rede (ver linha_console);
        # nela, o "-d" só faria o cmd.exe reclamar antes de chegar ao pushd.
        args = [wt, "-w", "new", "--title", titulo]
        if not str(pasta).startswith("\\\\"):
            args += ["-d", str(pasta)]
        subprocess.Popen(args + ["cmd.exe", "/k", "pushd", str(pasta), "&&", exe], env=env)
        return
    subprocess.Popen(linha_console(pasta, exe, titulo), env=env,
                     creationflags=sistema.NOVO_CONSOLE)


def abrir_claude_code(pasta: Path) -> None:
    exe = achar_claude_code()
    if exe is None:
        raise FileNotFoundError(
            "O Claude Code não está instalado neste computador. Use o botão "
            "\"Instalar o Claude Code\" (instalação oficial, sem administrador).")
    _abrir_terminal(pasta, exe, "Claude Code - Acervo")


def instalar_claude_code() -> None:
    """Abre o PowerShell com o instalador oficial, à vista do usuário.

    A instalação é da Anthropic, por usuário e sem administrador; o programa
    só a dispara, para o usuário acompanhar (e fazer o login ao final).
    """
    if not sistema.NO_WINDOWS:
        raise OSError("a instalação automática só existe no Windows")
    comando = (f"Write-Host 'Instalando o Claude Code (instalador oficial da Anthropic)...';"
               f" {COMANDO_INSTALAR_CODE};"
               " Write-Host ''; Write-Host 'Pronto. Feche esta janela e volte ao Assessor Integrado.'")
    subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                      "-NoExit", "-Command", comando], creationflags=sistema.NOVO_CONSOLE)


# ---------------------------------------------------- Claude Desktop/Cowork
def arquivos_config_desktop() -> list[Path]:
    """Os claude_desktop_config.json possíveis neste computador.

    O instalador clássico usa %APPDATA%\\Claude. O pacote da Microsoft Store
    (MSIX) virtualiza o AppData: o arquivo de verdade fica em
    %LOCALAPPDATA%\\Packages\\Claude_<id>\\LocalCache\\Roaming\\Claude.
    """
    saida = []
    if os.environ.get("APPDATA"):
        saida.append(Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json")
    if os.environ.get("LOCALAPPDATA"):
        pacotes = Path(os.environ["LOCALAPPDATA"]) / "Packages"
        for p in sorted(pacotes.glob("Claude_*")):
            saida.append(p / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
    return saida


def claude_desktop_instalado() -> bool:
    """O app está instalado? Pelo pacote ou pelo executável - nunca pela pasta
    %APPDATA%\\Claude: o próprio registrar_mcp a cria ao gravar o
    claude_desktop_config.json, e ela continua lá depois de desinstalar."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        if any((Path(local) / "Packages").glob("Claude_*")):     # MSIX (o atual)
            return True
        if (Path(local) / "AnthropicClaude" / "claude.exe").is_file():   # instalador antigo
            return True
    return False


def entrada_mcp(pasta_acervo: Path) -> dict:
    """A entrada do servidor no formato do claude_desktop_config.json."""
    return {
        "command": str(caminhos.python_exe(janela=False)),
        # -s e PYTHONNOUSERSITE: pacote instalado pelo usuário em outro
        # Python (pasta "site" do perfil) não pode se misturar com o nosso.
        "args": ["-s", "-m", "helestron.compartilhar.mcp_servidor", "--pasta",
                 str(Path(pasta_acervo).resolve())],
        "env": {"PYTHONPATH": str(caminhos.RAIZ), "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1"},
    }


def _ler_json(arquivo: Path) -> dict:
    try:
        texto = arquivo.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    if not texto.strip():
        return {}
    dados = json.loads(texto)          # JSON inválido: quem chama decide
    if not isinstance(dados, dict):
        raise ValueError("o arquivo não contém um objeto JSON")
    return dados


def _gravar_json(arquivo: Path, dados: dict) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if arquivo.exists():
        copia = arquivo.with_name(f"{arquivo.stem}.antes-do-assessor-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(arquivo, copia)
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, arquivo)


def registrar_mcp(pasta_acervo: Path, arquivos: list[Path] | None = None) -> list[Path]:
    """Registra (ou atualiza) o conector do acervo no Claude Desktop.

    Mescla com o que já existe - outros servidores do usuário ficam intactos
    - e guarda uma cópia do arquivo anterior. Arquivo com JSON inválido não é
    tocado (seria apagar a configuração do usuário): levanta ValueError.
    Devolve os arquivos alterados.
    """
    alvos = arquivos if arquivos is not None else arquivos_config_desktop()
    # Grava em TODOS os locais candidatos: o app da Microsoft Store (MSIX) lê
    # o arquivo de dentro de Packages, mas o botão "Edit Config" dele abre o
    # de %APPDATA% - registrando só num, o conector "some" (problema aberto
    # no repositório da Anthropic, issues 26073 e 25579).
    alterados = []
    for arq in alvos:
        try:
            dados = _ler_json(arq)
        except ValueError as erro:
            raise ValueError(f"o arquivo {arq} tem JSON inválido ({erro}); corrija-o "
                             "ou apague-o e tente de novo") from erro
        servidores = dados.setdefault("mcpServers", {})
        if not isinstance(servidores, dict):
            raise ValueError(f"'mcpServers' em {arq} não é um objeto")
        nova = entrada_mcp(pasta_acervo)
        if servidores.get(NOME_MCP) == nova:
            continue
        servidores[NOME_MCP] = nova
        _gravar_json(arq, dados)
        alterados.append(arq)
        log.info("Conector do acervo registrado em %s.", arq)
    return alterados


def mcp_registrado(pasta_acervo: Path | None = None) -> bool:
    for arq in arquivos_config_desktop():
        try:
            entrada = _ler_json(arq).get("mcpServers", {}).get(NOME_MCP)
        except (OSError, ValueError):
            continue
        if not entrada:
            continue
        if pasta_acervo is None:
            return True
        args = entrada.get("args") or []
        if str(Path(pasta_acervo).resolve()) in args:
            return True
    return False


def remover_mcp() -> list[Path]:
    alterados = []
    for arq in arquivos_config_desktop():
        try:
            dados = _ler_json(arq)
        except (OSError, ValueError):
            continue
        if NOME_MCP in dados.get("mcpServers", {}):
            del dados["mcpServers"][NOME_MCP]
            _gravar_json(arq, dados)
            alterados.append(arq)
    return alterados


PROMPT_INICIAL = (
    "Você vai trabalhar no acervo judicial desta pasta. Leia primeiro o CLAUDE.md "
    "(ou o AGENTS.md) e o INDICE.md. Depois, aguarde a minha tarefa — por exemplo: "
    "\"faça o relatório do processo <número>, com as folhas (no eProc, os eventos)\" "
    "ou \"resuma os depoimentos da audiência do processo <número>\".")


def _link(esquema: str, pasta: Path, prompt: str = "", parametro_pasta: str = "folder") -> str:
    consulta = [(parametro_pasta, str(Path(pasta).resolve()))]
    if prompt:
        consulta.append(("q", prompt))
    return esquema + "?" + urllib.parse.urlencode(consulta, quote_via=urllib.parse.quote)


def url_cowork(pasta: Path, prompt: str = "") -> str:
    """claude://cowork/new?folder=...: abre o Cowork já com a pasta.

    O app sempre pede confirmação para pasta recebida por link. Atenção: com
    'folder' no link, o texto de 'q' se perde (falha conhecida do app) - por
    isso a tela copia o prompt para a área de transferência antes.
    """
    return _link("claude://cowork/new", pasta, prompt)


def url_code_desktop(pasta: Path, prompt: str = "") -> str:
    """claude://code/new?folder=...: a aba Code do Claude Desktop na pasta."""
    return _link("claude://code/new", pasta, prompt)


def abrir_cowork(pasta: Path, prompt: str = "") -> bool:
    """Abre o Cowork na pasta. Devolve False se o Claude Desktop não existe
    (a tela então oferece a instalação)."""
    if not claude_desktop_instalado():
        return False
    if sistema.NO_WINDOWS:
        os.startfile(url_cowork(pasta, prompt))  # type: ignore[attr-defined]
        return True
    sistema.abrir_endereco(url_cowork(pasta, prompt))
    return True


def gerar_plugin_cowork(destino: Path) -> Path:
    """O ZIP do plugin 'acervo-judicial' para enviar ao Cowork.

    O Cowork não lê a pasta .claude do computador: habilidades e plugins
    entram por upload (Personalizar > Plugins > Adicionar > Enviar plugin).
    O plugin leva a mesma habilidade que o Claude Code usa no acervo.
    """
    from .. import __version__
    from .preparo import SKILL

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / "acervo-judicial-plugin.zip"
    manifesto = {
        "name": "acervo-judicial",
        "version": __version__,
        "description": "Método de trabalho com o acervo judicial do Assessor Integrado: "
                       "autos em PDF nomeados pelo número CNJ, texto com a página marcada "
                       "e transcrições de audiência.",
        "author": {"name": "Assessor Integrado"},
    }
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(".claude-plugin/plugin.json", json.dumps(manifesto, ensure_ascii=False, indent=2))
        z.writestr("skills/acervo-judicial/SKILL.md", SKILL)
    os.replace(tmp, arquivo)
    return arquivo


def abrir_claude_desktop() -> None:
    """Abre o app do Claude; sem ele, a página de download."""
    if sistema.NO_WINDOWS and claude_desktop_instalado():
        try:
            os.startfile("claude://")  # type: ignore[attr-defined]
            return
        except OSError:
            local = os.environ.get("LOCALAPPDATA")
            exe = Path(local) / "AnthropicClaude" / "claude.exe" if local else None
            if exe and exe.exists():
                subprocess.Popen([str(exe)])
                return
    sistema.abrir_endereco(URL_DOWNLOAD_DESKTOP)


def instalar_claude_desktop() -> None:
    """Baixa o instalador oficial do Claude Desktop (MSIX) pelo navegador."""
    sistema.abrir_endereco(URL_INSTALADOR_DESKTOP)


def estado() -> dict:
    """Resumo para a tela: o que está instalado e conectado."""
    code = achar_claude_code()
    return {
        "claude_code": str(code) if code else "",
        "desktop": claude_desktop_instalado(),
        "mcp": mcp_registrado(),
        "chave_no_ambiente": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }
