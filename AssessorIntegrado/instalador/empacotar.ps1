<#
    Assessor Integrado - gera o ZIP de distribuição (usado pelo CI).

        powershell -NoProfile -ExecutionPolicy Bypass -File instalador\empacotar.ps1 -Destino C:\saida

    Cria AssessorIntegrado-<versão>.zip (e o .sha256 ao lado) com o programa
    pronto para o usuário extrair e dar dois cliques no INSTALAR.bat: sem
    runtime\, sem dados (Acervo, Sigilosos, Logs, config.ini) e sem restos
    do Python (__pycache__). Tudo fica numa pasta AssessorIntegrado\ dentro
    do ZIP.

    As entradas do ZIP são gravadas aqui, uma a uma, com "/" como separador:
    o Compress-Archive do PowerShell 5.1 grava "\", fora da especificação do
    formato, e outros descompactadores criam arquivos com "\" no nome.
    Os bytes vão como estão no disco - os .bat continuam com CRLF.

    Funciona no Windows PowerShell 5.1 e no PowerShell 7 (Linux nos testes).
#>
[CmdletBinding()]
param(
    [string]$Destino = '',
    [string]$Origem = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'funcoes.ps1')

if (-not $Origem) { $Origem = Split-Path -Parent $PSScriptRoot }
$Origem = (Resolve-Path -LiteralPath $Origem).ProviderPath.TrimEnd('\', '/')
if (-not $Destino) { $Destino = Join-Path $Origem 'dist' }
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$Destino = (Resolve-Path -LiteralPath $Destino).ProviderPath

$versao = Ler-VersaoDoPrograma $Origem
$arquivoZip = Join-Path $Destino ('AssessorIntegrado-' + $versao + '.zip')

# Pastas e arquivos do primeiro nível que não vão para o usuário.
$foraDaRaiz = @('runtime', 'acervo', 'sigilosos', 'logs', 'dist', '.git', '.github', '.pytest_cache',
                '.vscode', '.idea', 'config.ini', 'enderecos-locais.json', '.gitignore', '.gitattributes')
# Nomes que não vão em nível nenhum.
$foraSempre = @('__pycache__', '.mypy_cache', '.ruff_cache')

function Incluir {
    param([string]$Relativo)
    $partes = $Relativo -split '[\\/]'
    if ($foraDaRaiz -contains $partes[0].ToLowerInvariant()) { return $false }
    foreach ($p in $partes) { if ($foraSempre -contains $p.ToLowerInvariant()) { return $false } }
    $nome = $partes[$partes.Count - 1]
    if ($nome -match '\.(pyc|pyo|parcial|tmp|part|log)$' -or $nome.StartsWith('~$')) { return $false }
    return $true
}

try { Add-Type -AssemblyName System.IO.Compression } catch { }
try { Add-Type -AssemblyName System.IO.Compression.FileSystem } catch { }

$arquivos = @(Get-ChildItem -LiteralPath $Origem -Recurse -File -Force | Sort-Object FullName)
if (Test-Path -LiteralPath $arquivoZip) { Remove-Item -LiteralPath $arquivoZip -Force }
$zip = [IO.Compression.ZipFile]::Open($arquivoZip, [IO.Compression.ZipArchiveMode]::Create)
$n = 0
try {
    foreach ($f in $arquivos) {
        if ($f.FullName -eq $arquivoZip) { continue }
        $relativo = $f.FullName.Substring($Origem.Length).TrimStart('\', '/')
        if (-not (Incluir $relativo)) { continue }
        $entrada = 'AssessorIntegrado/' + ($relativo -replace '\\', '/')
        $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $f.FullName, $entrada, [IO.Compression.CompressionLevel]::Optimal)
        $n++
    }
} finally {
    $zip.Dispose()
}

$hash = Hash-DoArquivo $arquivoZip
$nomeZip = Split-Path -Leaf $arquivoZip
[IO.File]::WriteAllText($arquivoZip + '.sha256', ($hash + '  ' + $nomeZip + "`n"), (New-Object System.Text.UTF8Encoding $false))
Write-Host ('ZIP de distribuição: ' + $arquivoZip + ' (' + $n + ' arquivos, ' + (Formatar-Tamanho (Get-Item -LiteralPath $arquivoZip).Length) + ')')
Write-Host ('SHA-256: ' + $hash)
Write-Output $arquivoZip
