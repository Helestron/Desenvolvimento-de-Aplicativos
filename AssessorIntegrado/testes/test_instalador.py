"""Testes do instalador: .bat, .ps1, funções do PowerShell, ZIP e iniciar.pyw.

O instalador é a parte que o usuário vê primeiro, e o Windows tem armadilhas
que só aparecem lá (fim de linha dos .bat, BOM dos .ps1, sintaxe do
PowerShell 5.1, aspas da linha de comando). Por isso:

* as regras de arquivo (ASCII + CRLF nos .bat; UTF-8 com BOM + CRLF nos
  .ps1) são conferidas byte a byte, em qualquer sistema;
* os .ps1 passam pelo analisador do próprio PowerShell. No CI do Windows é
  o Windows PowerShell 5.1 - o mesmo do computador do usuário -, que recusa
  sintaxe do PowerShell 7; fora dele, o pwsh 7 analisa e os testes procuram
  os operadores que só o 7 tem;
* as funções puras do funcoes.ps1 rodam de verdade, no PowerShell que houver
  (sem nenhum, esses testes se pulam).

Para apontar outro PowerShell: variável ASSESSOR_PWSH.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
INSTALADOR = RAIZ / "instalador"
BATS = [RAIZ / "INSTALAR.bat", RAIZ / "Assessor Integrado.bat", RAIZ / "DESINSTALAR.bat"]
PS1 = sorted(INSTALADOR.glob("*.ps1"))
WORKFLOW = RAIZ.parent / ".github" / "workflows" / "windows.yml"
BOM = b"\xef\xbb\xbf"


def achar_powershell() -> str | None:
    if os.environ.get("ASSESSOR_PWSH"):
        return os.environ["ASSESSOR_PWSH"]
    if sys.platform == "win32":
        # O Windows PowerShell 5.1 - o que o INSTALAR.bat usa - é o alvo real.
        return shutil.which("powershell.exe") or shutil.which("powershell")
    return shutil.which("pwsh")


POWERSHELL = achar_powershell()


def rodar_ps(script: str, *args: str, timeout: float = 180) -> subprocess.CompletedProcess:
    """Roda um script do PowerShell (gravado com BOM e CRLF, como os de verdade)."""
    with tempfile.TemporaryDirectory() as tmp:
        arquivo = Path(tmp) / "teste.ps1"
        arquivo.write_bytes(BOM + script.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(arquivo), *args],
            capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


def ps_json(script: str, *args: str) -> object:
    """Roda o script, que grava um JSON em $Saida (UTF-8), e devolve o JSON lido.

    A saída vem por arquivo, e não pelo stdout, porque o PowerShell 5.1 com
    saída redirecionada escreve na página de código do console (acentos se
    perdem).
    """
    with tempfile.TemporaryDirectory() as tmp:
        saida = Path(tmp) / "saida.json"
        cabeca = ("param([string]$Funcoes, [string]$Saida, [string]$Extra = '')\n"
                  "$ErrorActionPreference = 'Stop'\n"
                  ". $Funcoes\n"
                  "function Gravar-Saida { param($Obj) "
                  "[IO.File]::WriteAllText($Saida, ($Obj | ConvertTo-Json -Depth 8), "
                  "(New-Object System.Text.UTF8Encoding $false)) }\n")
        r = rodar_ps(cabeca + script, "-Funcoes", str(INSTALADOR / "funcoes.ps1"), "-Saida", str(saida),
                     *args)
        if r.returncode != 0 or not saida.exists():
            raise AssertionError("PowerShell falhou:\n" + r.stdout.decode("utf-8", "replace")
                                 + r.stderr.decode("utf-8", "replace"))
        return json.loads(saida.read_text(encoding="utf-8-sig"))


def dividir_linha_windows(linha: str) -> list[str]:
    """Como o Windows (runtime do C) divide uma linha de comando em argumentos."""
    args: list[str] = []
    atual: list[str] = []
    em_aspas = tem = False
    i, n = 0, len(linha)
    while i < n:
        c = linha[i]
        if c == "\\":
            j = i
            while j < n and linha[j] == "\\":
                j += 1
            barras = j - i
            if j < n and linha[j] == '"':
                atual.append("\\" * (barras // 2))
                if barras % 2:
                    atual.append('"')
                    j += 1
                i = j
            else:
                atual.append("\\" * barras)
                i = j
            tem = True
            continue
        if c == '"':
            if em_aspas and i + 1 < n and linha[i + 1] == '"':
                atual.append('"')
                i += 2
                continue
            em_aspas = not em_aspas
            tem = True
            i += 1
            continue
        if c in " \t" and not em_aspas:
            if tem:
                args.append("".join(atual))
                atual, tem = [], False
            i += 1
            continue
        atual.append(c)
        tem = True
        i += 1
    if tem:
        args.append("".join(atual))
    return args


def carregar_iniciar():
    """Carrega o iniciar.pyw como módulo (a extensão .pyw não é importável)."""
    caminho = RAIZ / "iniciar.pyw"
    carregador = importlib.machinery.SourceFileLoader("iniciar_assessor_teste", str(caminho))
    spec = importlib.util.spec_from_loader(carregador.name, carregador)
    modulo = importlib.util.module_from_spec(spec)
    carregador.exec_module(modulo)
    return modulo


# ======================================================== regras de arquivo

class TestArquivosBat(unittest.TestCase):
    def test_existem(self):
        for bat in BATS:
            self.assertTrue(bat.is_file(), bat)

    def test_ascii_e_crlf(self):
        for bat in BATS:
            dados = bat.read_bytes()
            dados.decode("ascii")  # acento num .bat sai trocado na tela do cmd
            self.assertNotIn(b"\r\r", dados, bat.name)
            sem_crlf = dados.replace(b"\r\n", b"")
            self.assertNotIn(b"\n", sem_crlf, f"{bat.name}: linha terminada só com LF")
            self.assertNotIn(b"\r", sem_crlf, f"{bat.name}: CR solto")
            self.assertTrue(dados.endswith(b"\r\n"), bat.name)

    def test_rotulos_existem(self):
        for bat in BATS:
            texto = bat.read_text(encoding="ascii")
            rotulos = {m.lower() for m in re.findall(r"(?m)^:(\w+)", texto)}
            for alvo in re.findall(r"(?i)\bgoto\s+:?(\w+)", texto):
                if alvo.lower() == "eof":
                    continue
                self.assertIn(alvo.lower(), rotulos, f"{bat.name}: goto {alvo} sem rótulo")

    def test_pushd_e_sem_cd(self):
        for bat in BATS:
            texto = bat.read_text(encoding="ascii")
            self.assertIn('pushd "%~dp0"', texto, bat.name)
            self.assertNotRegex(texto, r"(?im)^\s*cd\s+/d", bat.name)
            self.assertTrue(texto.lower().startswith("@echo off"), bat.name)

    def test_instalar_chama_o_powershell_certo(self):
        texto = (RAIZ / "INSTALAR.bat").read_text(encoding="ascii")
        self.assertIn('-NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\\instalar.ps1" %*', texto)
        self.assertIn("Sysnative", texto)
        self.assertIn("MachinePolicy", texto)
        self.assertIn("LanguageMode", texto)
        self.assertIn("Unblock-File", texto)
        self.assertIn("if not defined SILENCIOSO pause", texto)

    def test_abrir_usa_pythonw_e_iniciar(self):
        texto = (RAIZ / "Assessor Integrado.bat").read_text(encoding="ascii")
        self.assertIn('start "" "%~dp0runtime\\python\\pythonw.exe" -E -s "%~dp0iniciar.pyw"', texto)
        self.assertIn("INSTALAR.bat", texto)

    def test_desinstalar_chama_o_script(self):
        texto = (RAIZ / "DESINSTALAR.bat").read_text(encoding="ascii")
        self.assertIn('-File "%~dp0instalador\\desinstalar.ps1" %*', texto)

    def test_parenteses_so_fora_de_blocos(self):
        # Dentro de um bloco "( ... )", um ")" num echo fecha o bloco antes da
        # hora. Os textos com parênteses ficam fora de blocos.
        for bat in BATS:
            profundidade = 0
            for numero, linha in enumerate(bat.read_text(encoding="ascii").splitlines(), 1):
                s = linha.strip()
                if s.lower().startswith("rem") or s.startswith("::"):
                    continue
                if profundidade > 0 and s.lower().startswith("echo") and ")" in s:
                    self.fail(f"{bat.name}:{numero}: ')' dentro de bloco")
                sem_aspas = re.sub(r'"[^"]*"', "", s)
                profundidade += sem_aspas.count("(") - sem_aspas.count(")")
                self.assertGreaterEqual(profundidade, 0, f"{bat.name}:{numero}")
            self.assertEqual(profundidade, 0, bat.name)


class TestArquivosPs1(unittest.TestCase):
    PROIBIDOS = [r"Join-String", r"-Parallel\b", r"utf8NoBOM", r"-AsHashtable", r"-SkipCertificateCheck",
                 r"\$IsWindows\b", r"\$IsLinux\b", r"-AsByteStream", r"-LeafBase", r"\bGet-Error\b",
                 r"-AsArray\b", r"\bTest-Json\b", r"-ResponseHeadersVariable", r"-SkipHttpErrorCheck",
                 r"-MaximumRetryCount", r"-NoProxy\b", r"-SslProtocol", r"\$PSStyle", r"GetRelativePath",
                 r"-AdditionalChildPath", r"(?i)Start-Process[^\n]*-Environment\b", r"-Resume\b"]

    def test_existem(self):
        nomes = {p.name for p in PS1}
        self.assertTrue({"instalar.ps1", "desinstalar.ps1", "funcoes.ps1", "empacotar.ps1"} <= nomes)

    def test_bom_utf8_e_crlf(self):
        for ps in PS1:
            dados = ps.read_bytes()
            self.assertTrue(dados.startswith(BOM), f"{ps.name}: sem BOM (o PowerShell 5.1 leria como ANSI)")
            dados[3:].decode("utf-8")
            sem_crlf = dados.replace(b"\r\n", b"")
            self.assertNotIn(b"\n", sem_crlf, f"{ps.name}: linha terminada só com LF")

    def test_sem_recursos_do_powershell_7(self):
        for ps in PS1:
            texto = ps.read_text(encoding="utf-8-sig")
            codigo = re.sub(r"(?s)<#.*?#>", "", texto)
            codigo = "\n".join(l for l in codigo.splitlines() if not l.lstrip().startswith("#"))
            for padrao in self.PROIBIDOS:
                self.assertIsNone(re.search(padrao, codigo), f"{ps.name}: {padrao} não existe no PowerShell 5.1")

    def test_constantes_do_python_portatil(self):
        texto = (INSTALADOR / "instalar.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("cpython-3.12.10%2B20250409-x86_64-pc-windows-msvc-install_only.tar.gz", texto)
        self.assertIn("5ac66ae49a2104efeba985c1dc1cb40987757ee81cc6c7f218d10b801f3276ed", texto)
        for trecho in ("--require-hashes", "--only-binary=:all:", "PIP_CACHE_DIR", "Start-Transcript",
                       "'.instalando'", "verificar', '--completo', '--json'", "preparar-pastas",
                       "'modelos', 'baixar'", "'falantes', 'instalar'", "requisitos-falantes.txt",
                       "PYTHONNOUSERSITE", "estado.json"):
            self.assertIn(trecho, texto)
        self.assertNotIn("install --upgrade pip", texto)
        funcoes = (INSTALADOR / "funcoes.ps1").read_text(encoding="utf-8-sig")
        for trecho in ("3072", "Unblock-File", "Start-BitsTransfer", "Invoke-WebRequest", "'-C', '-'",
                       "GetSystemWebProxy", "Get-FileHash"):
            self.assertIn(trecho, funcoes)

    def test_requisitos_travados(self):
        # Os arquivos são gerados à parte (uv pip compile); aqui só se confere
        # que continuam instaláveis com --require-hashes.
        for nome in ("requisitos.txt", "requisitos-falantes.txt"):
            linhas = (INSTALADOR / nome).read_text(encoding="utf-8").splitlines()
            pacotes = [l for l in linhas if re.match(r"^[A-Za-z0-9]", l)]
            self.assertTrue(pacotes, nome)
            for p in pacotes:
                self.assertRegex(p, r"^[A-Za-z0-9_.\-\[\],]+==[^\s]+", f"{nome}: {p} sem versão fixa")
            texto = "\n".join(linhas)
            blocos = re.split(r"(?m)^(?=[A-Za-z0-9])", texto)[1:]
            for bloco in blocos:
                self.assertIn("--hash=sha256:", bloco, f"{nome}: {bloco.splitlines()[0]} sem hash")
        self.assertIn("msvc-runtime==", (INSTALADOR / "requisitos.txt").read_text(encoding="utf-8"))


class TestOutrosArquivos(unittest.TestCase):
    def test_leia_me(self):
        dados = (RAIZ / "LEIA-ME.txt").read_bytes()
        self.assertTrue(dados.startswith(BOM), "o Bloco de Notas antigo precisa do BOM")
        self.assertNotIn(b"\n", dados.replace(b"\r\n", b""))
        texto = dados[3:].decode("utf-8")
        for trecho in ("INSTALAR.bat", "Assessor Integrado.bat", "DESINSTALAR.bat",
                       "1. INSTALE", "2. ABRA", "3. USE", "Área de Trabalho"):
            self.assertIn(trecho, texto)

    def test_gitattributes(self):
        texto = (RAIZ / ".gitattributes").read_text(encoding="utf-8")
        for regra in ("*.bat           text eol=crlf", "*.ps1           text eol=crlf", "*.png           binary"):
            self.assertIn(regra, texto)

    def test_gitignore(self):
        texto = (RAIZ / ".gitignore").read_text(encoding="utf-8")
        for regra in ("/runtime/", "/Acervo/", "/Sigilosos/", "/Logs/", "/config.ini", "__pycache__/"):
            self.assertIn(regra, texto)


# ===================================================== análise do PowerShell

_ANALISE = r"""
param([string]$Pasta, [string]$Saida)
$ErrorActionPreference = 'Stop'
$definidas = @{}
$dados = @{}
foreach ($f in Get-ChildItem -LiteralPath $Pasta -Filter '*.ps1') {
    $tokens = $null; $erros = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$erros)
    $dados[$f.Name] = @{ Ast = $ast; Tokens = $tokens; Erros = $erros }
    foreach ($fd in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
        $definidas[$fd.Name.ToLowerInvariant()] = $true
    }
}
$saidaObj = @{ erros = @(); ps7 = @(); joinpath = @(); comandos = @(); variaveis = @() }
$atribuidas = @{}
foreach ($nome in $dados.Keys) {
    $a = $dados[$nome]
    foreach ($e in $a.Erros) { $saidaObj.erros += ($nome + ':' + $e.Extent.StartLineNumber + ': ' + $e.Message) }
    foreach ($t in $a.Tokens) {
        $k = [string]$t.Kind
        if (@('AndAnd', 'OrOr', 'QuestionQuestion', 'QuestionQuestionEquals', 'QuestionDot', 'QuestionLBracket', 'QuestionMark') -contains $k) {
            $saidaObj.ps7 += ($nome + ':' + $t.Extent.StartLineNumber + ': ' + $k)
        }
    }
    foreach ($c in $a.Ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)) {
        $cn = $c.GetCommandName()
        if (-not $cn) { continue }
        if ($cn -eq 'Join-Path') {
            $pos = @($c.CommandElements | Select-Object -Skip 1 | Where-Object { $_ -isnot [System.Management.Automation.Language.CommandParameterAst] })
            if ($pos.Count -gt 2) { $saidaObj.joinpath += ($nome + ':' + $c.Extent.StartLineNumber) }
        }
        if (-not $definidas.ContainsKey($cn.ToLowerInvariant())) { $saidaObj.comandos += $cn }
    }
    foreach ($x in $a.Ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true)) {
        foreach ($v in $x.Left.FindAll({ param($n) $n -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)) {
            $atribuidas[($v.VariablePath.UserPath.ToLowerInvariant() -replace '^script:', '')] = $true
        }
    }
    foreach ($p in $a.Ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.ParameterAst] }, $true)) {
        $atribuidas[$p.Name.VariablePath.UserPath.ToLowerInvariant()] = $true
    }
    foreach ($fe in $a.Ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.ForEachStatementAst] }, $true)) {
        $atribuidas[$fe.Variable.VariablePath.UserPath.ToLowerInvariant()] = $true
    }
}
$automaticas = @('_', 'true', 'false', 'null', 'pid', 'host', 'psscriptroot', 'lastexitcode', 'matches',
                 'args', 'input', 'executioncontext', 'erroractionpreference', 'progresspreference', 'this', 'psitem', 'error')
foreach ($nome in $dados.Keys) {
    foreach ($v in $dados[$nome].Ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)) {
        $vn = $v.VariablePath.UserPath.ToLowerInvariant() -replace '^script:', ''
        if ($vn.StartsWith('env:') -or $automaticas -contains $vn) { continue }
        if (-not $atribuidas.ContainsKey($vn)) { $saidaObj.variaveis += ($nome + ':' + $v.Extent.StartLineNumber + ': $' + $vn) }
    }
}
$saidaObj.comandos = @($saidaObj.comandos | Sort-Object -Unique)
[IO.File]::WriteAllText($Saida, ($saidaObj | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
"""

# Cmdlets que os scripts podem usar: todos existem no Windows PowerShell 5.1.
# Um cmdlet novo nos .ps1 obriga a conferir isso e a pô-lo aqui.
CMDLETS_PERMITIDOS = {
    "Add-Type", "ConvertFrom-Json", "ConvertTo-Json", "Copy-Item", "Get-ChildItem", "Get-Date",
    "Get-FileHash", "Get-Item", "Get-ItemProperty", "Get-Process", "Import-Module", "Invoke-WebRequest",
    "Join-Path", "Move-Item", "New-Item", "New-Object", "Out-Null", "Read-Host", "Remove-Item",
    "Resolve-Path", "Sort-Object", "Split-Path", "Start-BitsTransfer", "Start-Process", "Start-Sleep",
    "Start-Transcript", "Stop-Process", "Stop-Transcript", "Test-Path", "Unblock-File", "Where-Object",
    "Write-Host", "Write-Output",
}


@unittest.skipUnless(POWERSHELL, "PowerShell não encontrado (defina ASSESSOR_PWSH)")
class TestAnalisePowerShell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "analise.json"
            r = rodar_ps(_ANALISE, "-Pasta", str(INSTALADOR), "-Saida", str(saida))
            if r.returncode != 0 or not saida.exists():
                raise AssertionError("análise falhou: " + r.stderr.decode("utf-8", "replace"))
            cls.analise = json.loads(saida.read_text(encoding="utf-8-sig"))

    def _lista(self, chave):
        valor = self.analise.get(chave) or []
        return [valor] if isinstance(valor, str) else list(valor)

    def test_sem_erros_de_sintaxe(self):
        self.assertEqual(self._lista("erros"), [])

    def test_sem_operadores_do_powershell_7(self):
        self.assertEqual(self._lista("ps7"), [])

    def test_join_path_com_dois_pedacos(self):
        self.assertEqual(self._lista("joinpath"), [])

    def test_so_cmdlets_conhecidos(self):
        # Pega erro de digitação em nome de função (que só estouraria no
        # Windows, no meio da instalação) e cmdlet que não existe no 5.1.
        desconhecidos = set(self._lista("comandos")) - CMDLETS_PERMITIDOS
        self.assertEqual(desconhecidos, set())

    def test_toda_variavel_tem_atribuicao(self):
        self.assertEqual(self._lista("variaveis"), [])


# ================================================= funções puras do PowerShell

@unittest.skipUnless(POWERSHELL, "PowerShell não encontrado (defina ASSESSOR_PWSH)")
class TestFuncoesPowerShell(unittest.TestCase):
    def test_aspas_da_linha_de_comando(self):
        casos = ["simples", "com espaço", r"C:\Teste Área\Assessor Integrado", "termina\\",
                 "C:\\pasta com espaço\\", 'aspas "dentro"', 'barra antes \\" da aspa', "",
                 "import sys; print(\"oi\")", "tab\taqui", "\\\\servidor\\c$\\x y"]
        with tempfile.TemporaryDirectory() as tmp:
            entrada = Path(tmp) / "casos.json"
            entrada.write_text(json.dumps(casos, ensure_ascii=False), encoding="utf-8")
            r = ps_json("$casos = [IO.File]::ReadAllText($Extra, [Text.Encoding]::UTF8) | ConvertFrom-Json\n"
                        "$lista = @(); foreach ($c in $casos) { $lista += [string]$c }\n"
                        "Gravar-Saida @{ linha = (Montar-LinhaDeComando $lista); "
                        "simples = (Citar-Argumento 'simples'); vazio = (Montar-LinhaDeComando @()) }",
                        "-Extra", str(entrada))
        self.assertEqual(dividir_linha_windows(r["linha"]), casos)
        self.assertEqual(r["simples"], "simples")
        self.assertEqual(r["vazio"], "")

    def test_formatacao(self):
        r = ps_json("Gravar-Saida @{\n"
                    " d0 = (Formatar-Duracao 0); d45 = (Formatar-Duracao 45); d125 = (Formatar-Duracao 125);\n"
                    " d3780 = (Formatar-Duracao 3780);\n"
                    " t1 = (Formatar-Tamanho 43958272); t2 = (Formatar-Tamanho 1610612736);\n"
                    " t3 = (Formatar-Tamanho 2048); t4 = (Formatar-Tamanho 500);\n"
                    " b25 = (Barra-DeProgresso 25 8); b0 = (Barra-DeProgresso -5 4); b100 = (Barra-DeProgresso 130 4);\n"
                    " e900 = @(Estimar-Minutos 900); e0 = @(Estimar-Minutos 0);\n"
                    " c0 = (Contar-Texto 0 'aviso' 'avisos' 'nenhum aviso'); c1 = (Contar-Texto 1 'aviso' 'avisos' 'x');\n"
                    " c3 = (Contar-Texto 3 'falha' 'falhas' 'x') }")
        self.assertEqual((r["d0"], r["d45"], r["d125"], r["d3780"]), ("0 s", "45 s", "2 min 05 s", "1 h 03 min"))
        self.assertEqual((r["t1"], r["t2"], r["t3"], r["t4"]), ("41,9 MB", "1,5 GB", "2 KB", "500 bytes"))
        self.assertEqual(r["b25"], "[##......]  25%")
        self.assertEqual(r["b0"], "[....]   0%")
        self.assertEqual(r["b100"], "[####] 100%")
        self.assertEqual(r["e900"], [5, 20])
        self.assertEqual(r["e0"], [1, 2])
        self.assertEqual((r["c0"], r["c1"], r["c3"]), ("nenhum aviso", "1 aviso", "3 falhas"))

    def test_respostas(self):
        r = ps_json("Gravar-Saida @{ vazio_s = (Interpretar-Resposta '' $true); vazio_n = (Interpretar-Resposta ' ' $false);\n"
                    " s = (Interpretar-Resposta 'S' $false); sim = (Interpretar-Resposta ' Sim ' $false);\n"
                    " nao = (Interpretar-Resposta 'não' $true); n = (Interpretar-Resposta 'N' $true);\n"
                    " talvez = (Interpretar-Resposta 'talvez' $true) }")
        self.assertEqual((r["vazio_s"], r["vazio_n"], r["s"], r["sim"], r["nao"], r["n"]),
                         (True, False, True, True, False, False))
        self.assertIsNone(r["talvez"])

    def test_local_da_instalacao(self):
        longo = "C:\\" + "\\".join(["pasta-com-nome-comprido"] * 5)
        r = ps_json(
            "$od = @('C:\\Users\\ana\\OneDrive - Tribunal de Justiça')\n"
            f"$longo = '{longo}'\n"
            "Gravar-Saida @{\n"
            " a = (Esta-NoOneDrive 'C:\\Users\\ana\\OneDrive - Tribunal de Justiça\\Downloads\\AI' $od);\n"
            " b = (Esta-NoOneDrive 'C:\\Users\\ana\\OneDrive\\Docs\\AI' @());\n"
            " c = (Esta-NoOneDrive 'C:\\AssessorIntegrado' $od);\n"
            " d = (Esta-NoOneDrive 'C:\\Users\\ana\\OneDriveX\\AI' @());\n"
            " e = (Esta-NoOneDrive 'D:\\Sync\\AI' @('D:\\Sync\\'));\n"
            " curto = (Avaliar-Local 'C:\\AssessorIntegrado' $od $false);\n"
            " longo = (Avaliar-Local $longo @() $false);\n"
            " longo_ok = (Avaliar-Local $longo @() $true);\n"
            " rede = (Avaliar-Local '\\\\servidor\\gabinete\\AI' @() $false) }")
        self.assertEqual((r["a"], r["b"], r["c"], r["d"], r["e"]), (True, True, False, False, True))
        self.assertFalse(r["curto"]["Mover"])
        self.assertTrue(r["longo"]["Longo"] and r["longo"]["Mover"])
        self.assertEqual(r["longo"]["Comprimento"], len(longo))
        self.assertFalse(r["longo_ok"]["Mover"])
        self.assertTrue(r["rede"]["Rede"] and r["rede"]["Mover"])

    def test_local_sem_gravacao_ou_com_acento_sem_nome_curto(self):
        r = ps_json(r"""
Gravar-Saida @{
 sem = (Avaliar-Local 'C:\AssessorIntegrado' @() $false 100 $false);
 curto = (Avaliar-Local 'C:\Teste Área' @() $false 100 $true $true);
 normal = (Avaliar-Local 'C:\Teste Área' @() $false 100 $true $false);
 acento = (Tem-Acento 'C:\Users\João'); ascii = (Tem-Acento 'C:\AssessorIntegrado');
 inexistente = (Acento-SemNomeCurto 'C:\Pasta Que Não Existe\Área');
 so_ascii = (Acento-SemNomeCurto 'C:\AssessorIntegrado') }""")
        self.assertTrue(r["sem"]["SemGravacao"] and r["sem"]["Mover"])
        self.assertTrue(r["curto"]["SemNomeCurto"] and r["curto"]["Mover"])
        self.assertFalse(r["normal"]["Mover"])
        self.assertTrue(r["acento"])
        self.assertFalse(r["ascii"])
        self.assertFalse(r["inexistente"], "na dúvida, não avisa")
        self.assertFalse(r["so_ascii"])

    def test_nome_do_modelo(self):
        r = ps_json("Gravar-Saida @{ a = (Nome-DoModelo 'Médio'); b = (Nome-DoModelo ' TURBO ');\n"
                    " c = (Nome-DoModelo 'small'); d = (Nome-DoModelo 'gigante'); e = (Nome-DoModelo $null);\n"
                    " f = (Nome-DoModelo 'basico') }")
        self.assertEqual((r["a"], r["b"], r["c"], r["d"], r["e"], r["f"]),
                         ("medium", "large-v3-turbo", "small", "gigante", "", "base"))

    def test_pastas_que_o_desinstalador_nao_apaga(self):
        r = ps_json(r"""
$prot = @('C:\Users\ana', 'C:\Users\ana\Documents', 'C:\Users\ana\OneDrive - TJ', '', $null)
$raiz = 'C:\Programas\Assessor Integrado'
Gravar-Saida @{
 disco = (Motivo-ParaNaoApagar 'D:\' $raiz $prot); disco2 = (Motivo-ParaNaoApagar 'd:' $raiz $prot);
 rede = (Motivo-ParaNaoApagar '\\servidor\gabinete\' $raiz $prot);
 docs = (Motivo-ParaNaoApagar 'C:\Users\ana\Documents\' $raiz $prot);
 usuarios = (Motivo-ParaNaoApagar 'c:\users' $raiz $prot);
 onedrive = (Motivo-ParaNaoApagar 'C:/Users/ana/OneDrive - TJ' $raiz $prot);
 acima = (Motivo-ParaNaoApagar 'C:\Programas' $raiz $prot);
 pontos = (Motivo-ParaNaoApagar 'C:\Programas\Assessor Integrado\..' $raiz $prot);
 raiz = (Motivo-ParaNaoApagar $raiz $raiz $prot);
 vazio = (Motivo-ParaNaoApagar '' $raiz $prot);
 proprio = (Motivo-ParaNaoApagar 'C:\Programas\Assessor Integrado\Acervo' $raiz $prot);
 dentro = (Motivo-ParaNaoApagar 'C:\Users\ana\Documents\Acervo' $raiz $prot);
 vizinho = (Motivo-ParaNaoApagar 'C:\Users\ana\Documents2' $raiz $prot);
 outro_disco = (Motivo-ParaNaoApagar 'D:\Gabinete\Acervo' $raiz $prot);
 n1 = (Normalizar-Caminho 'C:/a/./b/../c/'); n2 = (Normalizar-Caminho 'C:\..\x');
 n3 = (Normalizar-Caminho '\\srv\c$\..\..\y') }""")
        for chave in ("disco", "disco2", "rede", "docs", "usuarios", "onedrive", "acima", "pontos", "raiz", "vazio"):
            self.assertTrue(r[chave], f"{chave}: deveria ser protegida")
        for chave in ("proprio", "dentro", "vizinho", "outro_disco"):
            self.assertEqual(r[chave], "", f"{chave}: pode ser apagada")
        self.assertIn("programa", r["acima"])
        self.assertEqual((r["n1"], r["n2"], r["n3"]), ("C:\\a\\c", "C:\\x", "\\\\srv\\y"))

    def test_config_ini_e_pastas(self):
        ini = ("; comentário\n[geral]\npasta_acervo = D:\\Gabinete\\Acervo\n"
               "# outro\npasta_sigilosos=\n[Transcricao]\nmodelo_ao_vivo = Base\n")
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / "config.ini"
            arq.write_text(ini, encoding="utf-8")
            os.environ["ASSESSOR_TESTE_PASTA"] = "E:\\Dados"
            perfil_antes = os.environ.get("USERPROFILE")
            os.environ["USERPROFILE"] = "E:\\Perfil"
            try:
                r = ps_json(
                    "$t = [IO.File]::ReadAllText($Extra, [Text.Encoding]::UTF8)\n"
                    "$raiz = Split-Path -Parent $Extra\n"
                    "Gravar-Saida @{ acervo = (Ler-ValorDoIni $t 'geral' 'pasta_acervo');\n"
                    " sig = (Ler-ValorDoIni $t 'geral' 'pasta_sigilosos');\n"
                    " modelo = (Ler-ValorDoIni $t 'transcricao' 'MODELO_AO_VIVO');\n"
                    " falta = (Ler-ValorDoIni $t 'geral' 'nao_existe'); vazio = (Ler-ValorDoIni '' 'a' 'b');\n"
                    " abs = (Resolver-Pasta 'D:\\Gabinete\\Acervo' 'Acervo' $raiz);\n"
                    " padrao = (Resolver-Pasta '' 'Sigilosos' $raiz);\n"
                    " esperado = (Join-Path $raiz 'Sigilosos');\n"
                    " var = (Resolver-Pasta '%ASSESSOR_TESTE_PASTA%\\Acervo' 'Acervo' $raiz);\n"
                    " til = (Resolver-Pasta '~\\Acervo' 'Acervo' $raiz) }",
                    "-Extra", str(arq))
            finally:
                os.environ.pop("ASSESSOR_TESTE_PASTA", None)
                if perfil_antes is None:
                    os.environ.pop("USERPROFILE", None)
                else:
                    os.environ["USERPROFILE"] = perfil_antes
        self.assertEqual(r["acervo"], "D:\\Gabinete\\Acervo")
        self.assertEqual(r["sig"], "")
        self.assertEqual(r["modelo"], "Base")
        self.assertEqual((r["falta"], r["vazio"]), ("", ""))
        self.assertEqual(r["abs"], "D:\\Gabinete\\Acervo")
        self.assertEqual(r["padrao"], r["esperado"])
        self.assertEqual(r["var"], "E:\\Dados\\Acervo")
        self.assertEqual(r["til"], "E:\\Perfil\\Acervo")

    def test_resumo_da_verificacao(self):
        itens = [{"nome": "A", "situacao": "ok", "obrigatorio": True},
                 {"nome": "B", "situacao": "aviso", "obrigatorio": False},
                 {"nome": "C", "situacao": "falha", "obrigatorio": False},
                 {"nome": "D", "situacao": "falha", "obrigatorio": True}]
        with tempfile.TemporaryDirectory() as tmp:
            entrada = Path(tmp) / "v.json"
            entrada.write_text(json.dumps({"itens": itens}), encoding="utf-8")
            r = ps_json(
                "$d = [IO.File]::ReadAllText($Extra, [Text.Encoding]::UTF8) | ConvertFrom-Json\n"
                "$r1 = Resumir-Verificacao $d\n"
                "$d.itens = @($d.itens | Where-Object { $_.nome -ne 'D' })\n"
                "$r2 = Resumir-Verificacao $d\n"
                "$d.itens = @($d.itens | Where-Object { $_.nome -eq 'A' })\n"
                "$r3 = Resumir-Verificacao $d\n"
                "$r4 = Resumir-Verificacao $null\n"
                "Gravar-Saida @{ r1 = $r1.Resultado; a1 = $r1.Avisos.Count; f1 = $r1.Falhas.Count; ok1 = $r1.Ok;\n"
                " r2 = $r2.Resultado; r3 = $r3.Resultado; r4 = $r4.Resultado }",
                "-Extra", str(entrada))
        self.assertEqual((r["r1"], r["a1"], r["f1"], r["ok1"]), ("falha", 2, 1, 1))
        self.assertEqual((r["r2"], r["r3"], r["r4"]), ("aviso", "ok", "falha"))

    def test_remover_secao_toml(self):
        toml = ('model = "gpt-5"\n\n[mcp_servers.outro]\ncommand = "x"\n\n'
                '[mcp_servers.assessor-integrado]\ncommand = "C:\\\\AI\\\\python.exe"\nargs = ["-m", "a"]\n\n'
                '[mcp_servers.assessor-integrado.env]\nPYTHONPATH = "C:\\\\AI"\n\n[profiles.padrao]\nx = 1\n')
        with tempfile.TemporaryDirectory() as tmp:
            entrada = Path(tmp) / "config.toml"
            entrada.write_text(toml, encoding="utf-8")
            r = ps_json("$t = [IO.File]::ReadAllText($Extra, [Text.Encoding]::UTF8)\n"
                        "Gravar-Saida @{ novo = (Remover-SecaoToml $t @('assessor-integrado', 'assessor_integrado'));\n"
                        " igual = (Remover-SecaoToml 'a = 1' @('assessor-integrado')) }", "-Extra", str(entrada))
        novo = r["novo"].replace("\r\n", "\n")
        self.assertNotIn("assessor-integrado", novo)
        self.assertNotIn("PYTHONPATH", novo)
        for trecho in ('model = "gpt-5"', "[mcp_servers.outro]", 'command = "x"', "[profiles.padrao]", "x = 1"):
            self.assertIn(trecho, novo)
        self.assertEqual(r["igual"].strip(), "a = 1")

    def test_json_versao_e_hash(self):
        from app import __version__

        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / "estado.json"
            r = ps_json(f"$arq = '{arq}'\n"
                        "Gravar-Json $arq ([ordered]@{ nome = 'Transcrição'; n = 3 })\n"
                        "$lido = Ler-Json $arq\n"
                        f"Gravar-Saida @{{ versao = (Ler-VersaoDoPrograma '{RAIZ}'); nome = $lido.nome;\n"
                        " hash = (Hash-DoArquivo $arq); confere = (Confere-Hash $arq (Hash-DoArquivo $arq));\n"
                        " errado = (Confere-Hash $arq ('0' * 64)); ausente = (Hash-DoArquivo ($arq + '.x'));\n"
                        " invalido = ($null -eq (Ler-Json ($arq + '.x'))) }")
            bruto = arq.read_bytes()
        self.assertEqual(r["versao"], __version__)
        self.assertEqual(r["nome"], "Transcrição")
        self.assertFalse(bruto.startswith(BOM), "o Python leria o BOM como caractere")
        self.assertEqual(json.loads(bruto.decode("utf-8"))["nome"], "Transcrição")
        self.assertEqual(r["hash"], hashlib.sha256(bruto).hexdigest())
        self.assertTrue(r["confere"])
        self.assertFalse(r["errado"])
        self.assertEqual(r["ausente"], "")
        self.assertTrue(r["invalido"])

    def test_executar_e_capturar_preservam_argumentos(self):
        # Ponta a ponta: o que o PowerShell monta é exatamente o que o Python recebe.
        argumentos = ["com espaço", "C:\\Teste Área\\x\\", 'aspa "dentro"', "", "ç ã é"]
        with tempfile.TemporaryDirectory() as tmp:
            entrada = Path(tmp) / "args.json"
            entrada.write_text(json.dumps({"python": sys.executable, "args": argumentos}, ensure_ascii=False),
                               encoding="utf-8")
            codigo = ("import json, sys; print(json.dumps(sys.argv[1:])); "
                      "sys.exit(7 if sys.argv[1:] else 0)")
            r = ps_json(
                "$e = [IO.File]::ReadAllText($Extra, [Text.Encoding]::UTF8) | ConvertFrom-Json\n"
                "$lista = @('-c', '" + codigo.replace("'", "''") + "'); foreach ($a in $e.args) { $lista += [string]$a }\n"
                "$env:PYTHONIOENCODING = 'utf-8'\n"
                "$c = Capturar $e.python $lista\n"
                "$x = Executar $e.python @('-c', 'import sys; sys.exit(3)')\n"
                "Gravar-Saida @{ codigo = $c.Codigo; saida = $c.Saida; executar = $x }",
                "-Extra", str(entrada))
        self.assertEqual(r["codigo"], 7)
        self.assertEqual(json.loads(r["saida"]), argumentos)
        self.assertEqual(r["executar"], 3)

    def test_baixar_confere_hash_e_retoma(self):
        curl = (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
                if sys.platform == "win32" else shutil.which("curl"))
        if not curl or not os.path.exists(curl):
            self.skipTest("curl não disponível")
        with tempfile.TemporaryDirectory() as tmp:
            origem = Path(tmp) / "origem do teste.bin"
            dados = os.urandom(200_000)
            origem.write_bytes(dados)
            sha = hashlib.sha256(dados).hexdigest()
            destino = Path(tmp) / "baixados" / "arquivo.bin"
            # Um .part pela metade, como o de uma queda de rede: tem de ser completado.
            destino.parent.mkdir()
            (destino.parent / "arquivo.bin.part").write_bytes(dados[:50_000])
            r = ps_json(
                "$e = [IO.File]::ReadAllText($Extra, [Text.Encoding]::UTF8) | ConvertFrom-Json\n"
                "$script:Curl = $e.curl; $script:Proxy = ''\n"
                "function Start-Sleep { }  # as esperas entre tentativas não interessam aqui\n"
                "Baixar $e.url $e.destino $e.sha 'o teste'\n"
                "Baixar $e.url $e.destino $e.sha 'o teste'\n"
                "$falhou = $false\n"
                "try { Baixar $e.url ($e.destino + '.2') ('0' * 64) 'o teste errado' } catch { $falhou = $true }\n"
                "Gravar-Saida @{ existe = (Test-Path -LiteralPath $e.destino);\n"
                " parte = (Test-Path -LiteralPath ($e.destino + '.part')); falhou = $falhou;\n"
                " errado = (Test-Path -LiteralPath ($e.destino + '.2')) }",
                "-Extra", str(self._json(tmp, {"curl": curl, "url": origem.as_uri(), "destino": str(destino),
                                               "sha": sha})))
            self.assertTrue(r["existe"])
            self.assertFalse(r["parte"])
            self.assertTrue(r["falhou"])
            self.assertFalse(r["errado"])
            self.assertEqual(destino.read_bytes(), dados)

    @staticmethod
    def _json(pasta, dados) -> Path:
        arq = Path(pasta) / "entrada.json"
        arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        return arq


@unittest.skipUnless(POWERSHELL, "PowerShell não encontrado (defina ASSESSOR_PWSH)")
class TestEmpacotar(unittest.TestCase):
    def test_zip_de_distribuicao(self):
        with tempfile.TemporaryDirectory() as tmp:
            origem = Path(tmp) / "Assessor Integrado"
            (origem / "app" / "__pycache__").mkdir(parents=True)
            (origem / "app" / "__init__.py").write_text('__version__ = "9.8.7"\n', encoding="utf-8")
            (origem / "app" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"x")
            (origem / "INSTALAR.bat").write_bytes(b"@echo off\r\necho ok\r\n")
            (origem / "instalador").mkdir()
            shutil.copy2(INSTALADOR / "funcoes.ps1", origem / "instalador" / "funcoes.ps1")
            shutil.copy2(INSTALADOR / "empacotar.ps1", origem / "instalador" / "empacotar.ps1")
            for pasta in ("runtime/python", "Acervo/Processos", "Logs", "Sigilosos", "testes"):
                (origem / pasta).mkdir(parents=True)
            (origem / "runtime" / "python" / "python.exe").write_bytes(b"MZ")
            (origem / "Acervo" / "Processos" / "0700123-45.2024.8.02.0001.pdf").write_bytes(b"%PDF")
            (origem / "Logs" / "2026-10.log").write_text("x", encoding="utf-8")
            (origem / "config.ini").write_text("[geral]\n", encoding="utf-8")
            (origem / "testes" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
            (origem / "trabalho.tmp").write_text("x", encoding="utf-8")
            destino = Path(tmp) / "dist"
            r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-File", str(origem / "instalador" / "empacotar.ps1"), "-Destino", str(destino)],
                               capture_output=True, timeout=180, stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
            arquivo = destino / "AssessorIntegrado-9.8.7.zip"
            self.assertTrue(arquivo.is_file())
            with zipfile.ZipFile(arquivo) as z:
                nomes = sorted(z.namelist())
                self.assertEqual(z.read("AssessorIntegrado/INSTALAR.bat"), b"@echo off\r\necho ok\r\n")
            self.assertEqual(nomes, sorted([
                "AssessorIntegrado/INSTALAR.bat", "AssessorIntegrado/app/__init__.py",
                "AssessorIntegrado/instalador/empacotar.ps1", "AssessorIntegrado/instalador/funcoes.ps1",
                "AssessorIntegrado/testes/test_x.py"]))
            sha = (destino / "AssessorIntegrado-9.8.7.zip.sha256").read_text(encoding="utf-8").split()[0]
            self.assertEqual(sha, hashlib.sha256(arquivo.read_bytes()).hexdigest())


# ================================================ roteiro inteiro, com dublês

# Dublês das funções que mexem no Windows de verdade. O instalar.ps1 os
# carrega pela variável ASSESSOR_INSTALADOR_DUBLES, logo antes de começar:
# todo o resto - ordem das etapas, decisões, retomada, códigos de saída,
# estado.json - roda como no computador do usuário.
_DUBLES = r"""
$script:Tar = $PSCommandPath
$script:Curl = ''
function Start-Sleep { }
function Sim-Anotar { param([string]$Texto)
    [IO.File]::AppendAllText($env:ASSESSOR_SIM_REGISTRO, $Texto + "`n", (New-Object System.Text.UTF8Encoding $false)) }
function Sim-Marca { param([string]$Nome) return (Join-Path $Runtime ('sim-' + $Nome)) }
function Versao-DoWindows { return 19045 }
function Configurar-Rede { $script:Proxy = ''; return '' }
function Testar-Acesso { param([string]$Url, [int]$Segundos = 15) Sim-Anotar ('acesso ' + $Url); return '' }
function Desbloquear-Arquivos { param([string]$Pasta) return 0 }
function Caminhos-LongosAtivados { return $true }
function Esta-ComoAdministrador { return $false }
function Achar-Navegador { return [pscustomobject]@{ Nome = 'Microsoft Edge'; Caminho = 'msedge.exe' } }
function Processos-DoPrograma { param([string]$Runtime)
    if ($env:ASSESSOR_SIM_ABERTO) { return @([pscustomobject]@{ Id = 999999; ProcessName = 'pythonw' }) }
    return @() }
function Arquivos-DoAtalho {
    return @((Join-Path $env:ASSESSOR_SIM_ATALHOS 'Desktop.lnk'), (Join-Path $env:ASSESSOR_SIM_ATALHOS 'Programs.lnk')) }
function Criar-Atalho { param([string]$Arquivo, [string]$Alvo, [string]$Argumentos, [string]$PastaDeTrabalho,
                              [string]$Icone, [string]$Descricao)
    [IO.File]::WriteAllText($Arquivo, ($Alvo + '|' + $Argumentos + '|' + $PastaDeTrabalho + '|' + $Descricao)) }
function Atalho-DestaPasta { param([string]$Arquivo, [string]$Raiz)
    if (-not (Test-Path -LiteralPath $Arquivo)) { return $false }
    return ([IO.File]::ReadAllText($Arquivo).Contains($Raiz)) }
function Baixar { param([string]$Url, [string]$Destino, [string]$Sha256, [string]$Descricao)
    Sim-Anotar ('baixar ' + $Url)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destino) | Out-Null
    [IO.File]::WriteAllText($Destino, 'x') }
function Executar {
    param([string]$Programa, [string[]]$Argumentos = @(), [string]$Pasta = '', [int]$LimiteSegundos = 0,
          [string]$LinhaPronta = '')
    $linha = $LinhaPronta
    if (-not $linha) { $linha = Montar-LinhaDeComando $Argumentos }
    Sim-Anotar ('executar ' + (Split-Path -Leaf $Programa) + ' ' + $linha)
    if ($Programa -eq $script:Tar) {
        $py = Join-Path $Pasta 'python'
        New-Item -ItemType Directory -Force -Path $py | Out-Null
        [IO.File]::WriteAllText((Join-Path $py 'python.exe'), 'x')
        [IO.File]::WriteAllText((Join-Path $py 'pythonw.exe'), 'x')
        return 0
    }
    if ($Argumentos -contains 'pip') {
        if ($env:ASSESSOR_SIM_PIP_FALHA) { return 1 }
        $alvo = 'bibliotecas'
        if ($linha -like '*falantes*') { $alvo = 'falantes-pip' }
        [IO.File]::WriteAllText((Sim-Marca $alvo), 'x')
        return 0
    }
    if ($Argumentos -contains 'modelos') {
        if ($env:ASSESSOR_SIM_MODELO_FALHA) { return 1 }
        $m = Join-Path (Join-Path $Runtime 'modelos') ('whisper-' + $Argumentos[$Argumentos.Count - 1])
        New-Item -ItemType Directory -Force -Path $m | Out-Null
        [IO.File]::WriteAllText((Join-Path $m 'config.json'), '{}')
        [IO.File]::WriteAllText((Join-Path $m 'tokenizer.json'), '{}')
        [IO.File]::WriteAllBytes((Join-Path $m 'model.bin'), (New-Object byte[] 1100000))
        return 0
    }
    if ($Argumentos -contains 'falantes') { [IO.File]::WriteAllText((Sim-Marca 'falantes'), 'x'); return 0 }
    if ($Argumentos -contains 'verificar') {
        $i = [array]::IndexOf($Argumentos, '--json')
        $sit = $env:ASSESSOR_SIM_VERIFICACAO
        if (-not $sit) { $sit = 'ok' }
        $itens = @(@{ nome = 'Python e janela (Tk)'; situacao = 'ok'; detalhe = 'Python 3.12.10.'; obrigatorio = $true; acao = '' })
        if ($sit -eq 'aviso') {
            $itens += @{ nome = 'Microfone'; situacao = 'aviso'; detalhe = 'Nenhum microfone encontrado.'; obrigatorio = $false; acao = 'Conecte um microfone.' } }
        if ($sit -eq 'falha') {
            $itens += @{ nome = 'Componentes nativos (DLLs)'; situacao = 'falha'; detalhe = 'DLL load failed.'; obrigatorio = $true; acao = 'Rode o INSTALAR.bat de novo.' } }
        Gravar-Json $Argumentos[$i + 1] @{ resultado = $sit; itens = $itens }
        return 0
    }
    if ($Argumentos -contains 'preparar-pastas') {
        New-Item -ItemType Directory -Force -Path (Join-Path (Join-Path $Raiz 'Acervo') 'Transcricoes') | Out-Null
        return 0
    }
    return 0
}
function Capturar {
    param([string]$Programa, [string[]]$Argumentos = @(), [string]$Pasta = '', [int]$LimiteSegundos = 300)
    $codigo = [string]$Argumentos[$Argumentos.Count - 1]
    Sim-Anotar ('capturar ' + $codigo)
    if (-not (Test-Path -LiteralPath $Programa)) { return [pscustomobject]@{ Codigo = -1; Saida = ''; Erro = 'sem python' } }
    $ok = $true
    if ($codigo -like 'import faster_whisper*') {
        $ok = Test-Path -LiteralPath (Sim-Marca 'bibliotecas')
        if ($ok -and $env:ASSESSOR_SIM_IMPORT_FALHA) {
            return [pscustomobject]@{ Codigo = 1; Saida = ''; Erro = 'ImportError: DLL load failed while importing _ext' } }
    }
    elseif ($codigo -like '*falantes.disponivel*') { $ok = Test-Path -LiteralPath (Sim-Marca 'falantes') }
    if ($ok) { return [pscustomobject]@{ Codigo = 0; Saida = '3.12.10'; Erro = '' } }
    return [pscustomobject]@{ Codigo = 1; Saida = ''; Erro = "ModuleNotFoundError: No module named 'faster_whisper'" }
}
if ($env:ASSESSOR_SIM_SEM_GRAVACAO) {
    # A pasta do programa não aceita gravação (as outras, sim).
    function Pasta-Gravavel { param([string]$Pasta)
        return ((Normalizar-Caminho $Pasta) -ne (Normalizar-Caminho $Raiz)) }
}
"""


@unittest.skipUnless(POWERSHELL, "PowerShell não encontrado (defina ASSESSOR_PWSH)")
class TestRoteiroDoInstalador(unittest.TestCase):
    """O instalar.ps1 e o desinstalar.ps1 de ponta a ponta, numa cópia em pasta temporária."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.raiz = base / "Assessor Integrado"
        (self.raiz / "instalador").mkdir(parents=True)
        (self.raiz / "app").mkdir()
        for arq in list(INSTALADOR.glob("*.ps1")) + [INSTALADOR / "requisitos.txt",
                                                    INSTALADOR / "requisitos-falantes.txt"]:
            shutil.copy2(arq, self.raiz / "instalador" / arq.name)
        shutil.copy2(RAIZ / "app" / "__init__.py", self.raiz / "app" / "__init__.py")
        self.atalhos = base / "atalhos"
        self.atalhos.mkdir()
        self.registro = base / "registro.txt"
        # Perfil de usuário de mentira: o desinstalador mexe no %APPDATA% (conector
        # do Claude), no %LOCALAPPDATA% (senhas e perfis) e no %USERPROFILE%
        # (.codex) - num computador de desenvolvimento, os de verdade.
        self.perfil = base / "perfil"
        (self.perfil / "AppData" / "Roaming").mkdir(parents=True)
        (self.perfil / "AppData" / "Local").mkdir(parents=True)
        self.dubles = base / "dubles.ps1"
        self.dubles.write_bytes(BOM + _DUBLES.replace("\n", "\r\n").encode("utf-8"))
        self.runtime = self.raiz / "runtime"

    def tearDown(self):
        self.tmp.cleanup()

    def rodar(self, script: str = "instalar.ps1", *args: str, ambiente: dict | None = None,
              **simulacao: str) -> tuple[int, str, str]:
        if self.registro.exists():
            self.registro.unlink()
        env = dict(os.environ, ASSESSOR_INSTALADOR_DUBLES=str(self.dubles), NO_COLOR="1",
                   ASSESSOR_SIM_REGISTRO=str(self.registro), ASSESSOR_SIM_ATALHOS=str(self.atalhos))
        env.update(USERPROFILE=str(self.perfil), APPDATA=str(self.perfil / "AppData" / "Roaming"),
                   LOCALAPPDATA=str(self.perfil / "AppData" / "Local"))
        for variavel in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            env.pop(variavel, None)
        for chave, valor in simulacao.items():
            env[f"ASSESSOR_SIM_{chave.upper()}"] = valor
        env.update(ambiente or {})
        r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", str(self.raiz / "instalador" / script), *args],
                           capture_output=True, env=env, timeout=300, stdin=subprocess.DEVNULL)
        saida = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        registro = self.registro.read_text(encoding="utf-8") if self.registro.exists() else ""
        return r.returncode, saida, registro

    def estado(self) -> dict:
        return json.loads((self.runtime / "estado.json").read_text(encoding="utf-8"))

    def test_primeira_instalacao_e_a_segunda_que_nada_refaz(self):
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso")
        self.assertEqual(codigo, 0, saida)
        for trecho in ("baixar https://github.com/astral-sh/python-build-standalone/", "-m pip install",
                       "--require-hashes", "requisitos.txt", "requisitos-falantes.txt",
                       "-m app modelos baixar small", "-m app falantes instalar", "-m app preparar-pastas",
                       "-m app verificar --completo --json"):
            self.assertIn(trecho, registro)
        self.assertIn("[10/10]", saida)
        self.assertIn("PRONTO", saida)
        estado = self.estado()
        self.assertEqual(estado["resultado"], "ok")
        self.assertEqual(estado["modelo_ao_vivo"], "small")
        self.assertEqual(estado["bibliotecas"], hashlib.sha256((INSTALADOR / "requisitos.txt").read_bytes()).hexdigest())
        self.assertTrue(estado["falantes"])
        self.assertFalse((self.runtime / ".instalando").exists(), "a trava ficou para trás")
        self.assertTrue(list((self.raiz / "Logs").glob("instalacao-*.log")))
        atalho = (self.atalhos / "Desktop.lnk").read_text(encoding="utf-8")
        self.assertIn("pythonw.exe", atalho)
        self.assertIn('-E -s "', atalho)
        self.assertIn("iniciar.pyw", atalho)
        self.assertTrue((self.atalhos / "Programs.lnk").exists())

        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso")
        self.assertEqual(codigo, 0, saida)
        for trecho in ("baixar ", "pip install", "modelos baixar"):
            self.assertNotIn(trecho, registro, "a segunda instalação refez o que já estava feito")
        self.assertRegex(saida, r"Python 3\.12\.10 j.{1,3} instalado")
        self.assertRegex(saida, r"Tudo j.{1,3} est.{1,3} instalado")

    def test_falha_no_pip_interrompe_com_codigo_10(self):
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso", pip_falha="1")
        self.assertEqual(codigo, 10, saida)
        self.assertEqual(registro.count("-m pip install"), 3, "o pip deve ser tentado 3 vezes")
        self.assertIn("bibliotecas do programa", saida)
        self.assertNotIn("modelos baixar", registro)
        self.assertFalse((self.runtime / ".instalando").exists())

    def test_modelo_que_nao_baixa_vira_aviso(self):
        codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso", modelo_falha="1")
        self.assertEqual(codigo, 0, saida)
        self.assertEqual(self.estado()["resultado"], "aviso")
        self.assertIn("primeiro uso", saida)

    def test_verificacao_reprovada_da_codigo_10(self):
        codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso", verificacao="falha")
        self.assertEqual(codigo, 10, saida)
        self.assertEqual(self.estado()["resultado"], "falha")
        self.assertIn("DLL load failed", saida)
        codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso", verificacao="aviso")
        self.assertEqual(codigo, 0, saida)
        self.assertIn("Conecte um microfone.", saida)

    def test_programa_aberto_impede_no_modo_silencioso(self):
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso", aberto="1")
        self.assertEqual(codigo, 11, saida)
        self.assertNotIn("baixar ", registro)

    def test_parametros(self):
        codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso", "-ModeloAoVivo", "gigante")
        self.assertEqual(codigo, 11, saida)
        self.assertIn("large-v3-turbo", saida)
        codigo, saida, registro = self.rodar("instalar.ps1", "/s", "-SemModelo", "-SemFalantes", "-SemAtalhos",
                                             "-ModeloAoVivo", "base")
        self.assertEqual(codigo, 0, saida)
        self.assertNotIn("modelos baixar", registro)
        self.assertNotIn("falantes instalar", registro)
        self.assertIn("'modelo_ao_vivo', 'base'", registro)
        self.assertFalse((self.atalhos / "Desktop.lnk").exists())

    def test_instalar_em_outra_pasta(self):
        destino = Path(self.tmp.name) / "Nova Pasta"
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso", "-Pasta", str(destino))
        self.assertEqual(codigo, 0, saida)
        self.assertIn("robocopy", registro)
        self.assertIn("-NaoMover", registro)
        self.assertIn("-Silencioso", registro.split("-NaoMover", 1)[1])

    def test_trava_so_bloqueia_com_o_dono_vivo(self):
        # Regressão: o Windows reaproveita números de processo. Uma trava
        # esquecida (janela fechada no meio da instalação) que aponta para um
        # PowerShell aberto DEPOIS não pode impedir a instalação.
        outro = subprocess.Popen([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 120"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.5)
            self.runtime.mkdir(parents=True, exist_ok=True)
            trava = self.runtime / ".instalando"
            trava.write_text(str(outro.pid), encoding="ascii")
            codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso")
            self.assertEqual(codigo, 11, saida)
            self.assertIn("Outra instala", saida)
            self.assertNotIn("baixar ", registro)
            antiga = time.time() - 3600
            os.utime(trava, (antiga, antiga))
            codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso")
            self.assertEqual(codigo, 0, saida)
            self.assertFalse(trava.exists(), "a trava ficou para trás")
        finally:
            outro.kill()
            outro.wait()

    def test_bibliotecas_que_nao_carregam_nao_interrompem(self):
        # Regressão: uma DLL que não carrega interrompia tudo na etapa 3 -
        # sem pastas, sem atalhos e sem o diagnóstico da verificação final.
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso", import_falha="1")
        self.assertEqual(codigo, 10, saida)
        self.assertIn("DLL load failed", saida)
        for trecho in ("-m app preparar-pastas", "-m app verificar --completo --json"):
            self.assertIn(trecho, registro)
        self.assertTrue((self.atalhos / "Desktop.lnk").exists())
        estado = self.estado()
        self.assertEqual(estado["resultado"], "falha")
        self.assertFalse(estado.get("bibliotecas"), "bibliotecas que não carregam não podem ficar como prontas")
        self.assertFalse((self.runtime / ".instalando").exists())

    def test_python_refeito_reinstala_o_componente_de_falantes(self):
        # Regressão: com o Python refeito (cópia quebrada, antivírus), o
        # componente de falantes era dado como instalado pelo estado.json.
        codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso")
        self.assertEqual(codigo, 0, saida)
        shutil.rmtree(self.runtime / "python")
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso")
        self.assertEqual(codigo, 0, saida)
        self.assertIn("instalador" + os.sep + "requisitos.txt", registro)
        self.assertIn("requisitos-falantes.txt", registro)

    def test_pasta_sem_permissao_de_gravacao(self):
        # Regressão: o "New-Item Logs" derrubava o instalador com erro em
        # inglês. Agora: no modo silencioso, explica e para (código 11); com
        # o usuário (aqui, sem teclado: resposta padrão), copia para outra pasta.
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso", sem_gravacao="1")
        self.assertEqual(codigo, 11, saida)
        self.assertIn("-Pasta", saida)
        self.assertNotIn("baixar ", registro)
        self.assertNotIn("Erro inesperado", saida)
        # O disco do sistema de mentira: a pasta sugerida (<disco>\AssessorIntegrado)
        # nasce dentro da pasta temporária, e não em C:\ de verdade.
        disco = Path(self.tmp.name) / "disco"
        disco.mkdir()
        codigo, saida, registro = self.rodar("instalar.ps1", ambiente={"SystemDrive": str(disco)},
                                             sem_gravacao="1")
        self.assertEqual(codigo, 0, saida)
        self.assertIn("robocopy", registro)
        self.assertIn("-NaoMover", registro)
        self.assertIn(str(disco / "AssessorIntegrado"), registro)

    def test_modelo_por_apelido(self):
        codigo, saida, registro = self.rodar("instalar.ps1", "-Silencioso", "-SemFalantes", "-ModeloAoVivo", "medio")
        self.assertEqual(codigo, 0, saida)
        self.assertIn("-m app modelos baixar medium", registro)
        self.assertIn("'modelo_ao_vivo', 'medium'", registro)
        self.assertEqual(self.estado()["modelo_ao_vivo"], "medium")

    def test_desinstalar_nao_apaga_pasta_ampla(self):
        # Regressão: com o Acervo apontado (Configurações) para a pasta do
        # usuário ou para a pasta acima do programa, "-ApagarDados" apagava
        # tudo o que estava lá - inclusive o próprio programa.
        codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso")
        self.assertEqual(codigo, 0, saida)
        pessoal = self.perfil / "documento-pessoal.txt"
        pessoal.write_text("x", encoding="utf-8")
        (self.raiz / "config.ini").write_text(f"[geral]\npasta_acervo = {self.perfil}\n", encoding="utf-8")
        codigo, saida, _ = self.rodar("desinstalar.ps1", "-Silencioso", "-ApagarDados")
        self.assertEqual(codigo, 10, saida)
        self.assertTrue(pessoal.exists(), "apagou a pasta do usuário")
        self.assertIn("seguran", saida)
        (self.raiz / "config.ini").write_text("[geral]\npasta_acervo = ..\n", encoding="utf-8")
        codigo, saida, _ = self.rodar("desinstalar.ps1", "-Silencioso", "-ApagarDados")
        self.assertEqual(codigo, 10, saida)
        self.assertTrue((self.raiz / "instalador" / "desinstalar.ps1").exists(), "apagou o próprio programa")
        self.assertTrue(pessoal.exists())

    def test_desinstalar_mantem_os_dados_no_modo_silencioso(self):
        codigo, saida, _ = self.rodar("instalar.ps1", "-Silencioso")
        self.assertEqual(codigo, 0, saida)
        (self.raiz / "Acervo" / "Transcricoes" / "0700123-45.2024.8.02.0001.docx").write_bytes(b"PK")
        local = self.perfil / "AppData" / "Local" / "AssessorIntegrado"
        (local / "perfis").mkdir(parents=True)
        codigo, saida, _ = self.rodar("desinstalar.ps1", "-Silencioso")
        self.assertEqual(codigo, 0, saida)
        self.assertFalse(self.runtime.exists())
        self.assertFalse((self.atalhos / "Desktop.lnk").exists())
        self.assertTrue((self.raiz / "Acervo" / "Transcricoes" / "0700123-45.2024.8.02.0001.docx").exists())
        self.assertTrue(local.exists(), "no modo silencioso sem -ApagarDados, as senhas ficam")
        codigo, saida, _ = self.rodar("desinstalar.ps1", "-Silencioso", "-ApagarDados")
        self.assertEqual(codigo, 0, saida)
        self.assertFalse((self.raiz / "Acervo").exists())
        self.assertFalse(local.exists())


# ============================================================ iniciar.pyw

class TestIniciar(unittest.TestCase):
    def setUp(self):
        self.mod = carregar_iniciar()
        self.tmp = tempfile.TemporaryDirectory()
        self.mod.ARQUIVO_ERRO = Path(self.tmp.name) / "Logs" / "erro-ao-abrir.log"
        self.mostrado: list[str] = []
        self.mod.mostrar_erro = self.mostrado.append
        self.mod.preparar = lambda: None

    def tearDown(self):
        self.tmp.cleanup()

    def test_erro_vira_mensagem_e_log(self):
        def quebra():
            raise ImportError("DLL load failed while importing onnxruntime_pybind11_state")

        self.mod._carregar_main = quebra
        self.assertEqual(self.mod.principal([]), 1)
        self.assertEqual(len(self.mostrado), 1)
        self.assertIn("INSTALAR.bat", self.mostrado[0])
        self.assertIn("erro-ao-abrir.log", self.mostrado[0])
        log = self.mod.ARQUIVO_ERRO.read_text(encoding="utf-8")
        self.assertIn("Traceback", log)
        self.assertIn("onnxruntime", log)

    def test_codigos_de_saida(self):
        self.mod._carregar_main = lambda: (lambda argv: 0)
        self.assertEqual(self.mod.principal([]), 0)

        def sai(argv):
            raise SystemExit(3)

        self.mod._carregar_main = lambda: sai
        self.assertEqual(self.mod.principal([]), 3)
        recebidos = []
        self.mod._carregar_main = lambda: (lambda argv: recebidos.append(argv) or 0)
        self.mod.principal(["--teste-interface"])
        self.assertEqual(recebidos, [["--teste-interface"]])
        self.assertEqual(self.mostrado, [])

    def test_mensagens_amigaveis(self):
        falta = ModuleNotFoundError("No module named 'faster_whisper'", name="faster_whisper")
        self.assertIn("\u201cfaster_whisper\u201d", self.mod.mensagem_amigavel(falta))
        self.assertIn("INSTALAR.bat", self.mod.mensagem_amigavel(falta))
        sem_app = ModuleNotFoundError("No module named 'app'", name="app")
        self.assertIn("Faltam arquivos do programa", self.mod.mensagem_amigavel(sem_app))
        self.assertIn("ValueError", self.mod.mensagem_amigavel(ValueError("x")))

    def test_preparar_poe_a_pasta_no_caminho(self):
        mod = carregar_iniciar()
        antes_dir, antes_path = os.getcwd(), list(sys.path)
        antes_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        try:
            mod.preparar()
            self.assertEqual(Path(os.getcwd()).resolve(), RAIZ)
            self.assertIn(str(RAIZ), sys.path)
            self.assertTrue(os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
        finally:
            os.chdir(antes_dir)
            sys.path[:] = antes_path
            if antes_env is None:
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            else:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = antes_env


# ============================================================ CI

@unittest.skipUnless(WORKFLOW.is_file(), "fora do repositório (sem .github/workflows)")
class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.texto = WORKFLOW.read_text(encoding="utf-8")

    def test_passos_essenciais(self):
        for trecho in ("windows-latest", "ubuntu-latest", "workflow_dispatch", "pull_request",
                       "Teste \u00c1rea", "INSTALAR.bat -Silencioso", "verificar --completo",
                       "--teste-interface", "transcrever --ao-vivo --processo 0700123-45.2024.8.02.0001",
                       "System.Speech", "mcp_servidor", "CofreSenhas", "upload-artifact",
                       "empacotar.ps1", "DESINSTALAR.bat -Silencioso", "unittest discover"):
            self.assertIn(trecho, self.texto)
        self.assertGreaterEqual(self.texto.count("INSTALAR.bat -Silencioso"), 2, "falta a 2ª instalação")

    def test_scripts_dos_passos_em_ascii(self):
        # O runner grava cada "run:" num arquivo temporário; acento ali sai
        # trocado no cmd e no PowerShell 5.1. Texto acentuado vai por "env:".
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML não instalado")
        dados = yaml.safe_load(self.texto)
        gatilhos = dados.get("on", dados.get(True))
        self.assertTrue({"push", "pull_request", "workflow_dispatch"} <= set(gatilhos))
        for nome, job in dados["jobs"].items():
            for passo in job.get("steps", []):
                run = passo.get("run")
                if run:
                    try:
                        run.encode("ascii")
                    except UnicodeEncodeError:
                        self.fail(f"{nome}/{passo.get('name')}: script com caractere não ASCII")

    def test_scripts_dos_passos_sao_validos(self):
        # Os passos em PowerShell passam pelo analisador; o Python embutido
        # neles (here-strings @' ... '@) tem de compilar.
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML não instalado")
        dados = yaml.safe_load(self.texto)
        scripts = []
        for nome, job in dados["jobs"].items():
            for i, passo in enumerate(job.get("steps", [])):
                run = passo.get("run") or ""
                if passo.get("shell") == "powershell" and run:
                    scripts.append((f"{nome}-{i}", run))
                for m in re.finditer(r"@'\n(.*?)\n'@", run, re.S):
                    compile(m.group(1), f"{nome}-{i}", "exec")
        self.assertTrue(scripts)
        if not POWERSHELL:
            self.skipTest("PowerShell não encontrado")
        with tempfile.TemporaryDirectory() as tmp:
            for nome, run in scripts:
                (Path(tmp) / f"{nome}.ps1").write_text(run, encoding="utf-8")
            r = rodar_ps("param([string]$Pasta)\n$erros = @()\n"
                         "foreach ($f in Get-ChildItem -LiteralPath $Pasta -Filter '*.ps1') {\n"
                         " $t = $null; $e = $null\n"
                         " [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$t, [ref]$e)\n"
                         " foreach ($x in $e) { $erros += ($f.Name + ': ' + $x.Message) } }\n"
                         "if ($erros.Count -gt 0) { $erros | ForEach-Object { Write-Output $_ }; exit 1 }\n",
                         "-Pasta", tmp)
        self.assertEqual(r.returncode, 0, r.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
