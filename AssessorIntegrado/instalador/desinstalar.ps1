<#
    Assessor Integrado - desinstalador (chamado pelo DESINSTALAR.bat).

    Remove o que a instalação criou: os atalhos, o conector do acervo no
    Claude Desktop e no ChatGPT/Codex, e a pasta runtime\ (Python,
    bibliotecas, modelos, navegador). Os dados do usuário só saem se ele
    confirmar, um a um:
      * Acervo e Sigilosos (processos baixados e transcrições) - vão para a
        Lixeira, de onde ainda podem ser recuperados;
      * %LOCALAPPDATA%\AssessorIntegrado (senhas guardadas e perfis do
        navegador com as sessões dos portais).

    -Silencioso   não pergunta nada e MANTÉM os dados do usuário
    -ApagarDados  (com -Silencioso) apaga também os dados, sem Lixeira

    Códigos de saída: 0 = removido; 10 = algo não pôde ser removido;
    11 = cancelado ou impedido (programa aberto).

    Arquivo em UTF-8 com BOM e CRLF; somente sintaxe do PowerShell 5.1.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$Silencioso,
    [switch]$ApagarDados,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Outros = @()
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Raiz = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'funcoes.ps1')

$Runtime = Join-Path $Raiz 'runtime'
$PythonExe = Join-Path (Join-Path $Runtime 'python') 'python.exe'
$Logs = Join-Path $Raiz 'Logs'
$NomesConector = @('assessor-integrado', 'assessor_integrado')

$script:ModoSilencioso = [bool]$Silencioso
$script:EntradaRedirecionada = $false
$script:Problemas = @()
$script:Feitos = @()
$script:Transcrevendo = $false
foreach ($o in @($Outros)) {
    if ($o -and (@('/s', '/silencioso', '-s', '/q', '--silencioso') -contains $o.ToLowerInvariant())) {
        $script:ModoSilencioso = $true
    }
}

function Pastas-DeDados {
    # Onde estão o Acervo e os Sigilosos (o usuário pode tê-los posto em
    # outro disco, pelo config.ini ou pela tela de Configurações).
    $texto = ''
    $ini = Join-Path $Raiz 'config.ini'
    if (Test-Path -LiteralPath $ini) {
        try { $texto = [IO.File]::ReadAllText($ini, [Text.Encoding]::UTF8) } catch { }
    }
    return [pscustomobject]@{
        Acervo    = Resolver-Pasta (Ler-ValorDoIni $texto 'geral' 'pasta_acervo') 'Acervo' $Raiz
        Sigilosos = Resolver-Pasta (Ler-ValorDoIni $texto 'geral' 'pasta_sigilosos') 'Sigilosos' $Raiz
    }
}

function Descrever-Pasta {
    # "37 arquivos, 812,4 MB" - para o usuário saber o que está apagando.
    param([string]$Pasta)
    $arquivos = @(Get-ChildItem -LiteralPath $Pasta -Recurse -File -Force -ErrorAction SilentlyContinue)
    $bytes = 0
    foreach ($a in $arquivos) { $bytes += $a.Length }
    return (Contar-Texto $arquivos.Count 'arquivo' 'arquivos' 'nenhum arquivo') + ', ' + (Formatar-Tamanho $bytes)
}

function Fechar-Programa {
    $abertos = @(Processos-DoPrograma $Runtime)
    if ($abertos.Count -eq 0) { return $true }
    Mostrar-Aviso 'O Assessor Integrado está aberto (ou o Claude ou o ChatGPT está usando o conector).'
    if (-not (Perguntar 'Fechar agora?' $true)) { return $false }
    foreach ($p in $abertos) { try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch { } }
    Start-Sleep -Seconds 2
    return (@(Processos-DoPrograma $Runtime).Count -eq 0)
}

function Remover-ConectoresPeloPython {
    # O caminho preferido: as próprias funções do programa, que sabem onde o
    # registro foi feito e guardam cópia de segurança antes de mudar.
    if (-not (Test-Path -LiteralPath $PythonExe)) { return $false }
    $codigo = 'from app.compartilhar import claude, chatgpt; ' +
              'claude.remover_mcp(); ' +
              'f = getattr(chatgpt, "remover_mcp_codex", None); ' +
              'f() if f else None'
    $r = Capturar $PythonExe @('-c', $codigo) -Pasta $Raiz -LimiteSegundos 120
    return ($r.Codigo -eq 0)
}

function Remover-ConectorClaudeJson {
    # Reserva, sem Python: tira "assessor-integrado" do claude_desktop_config.json
    # (instalação clássica e a da Microsoft Store), com cópia de segurança.
    $arquivos = @()
    if ($env:APPDATA) { $arquivos += (Join-Path (Join-Path $env:APPDATA 'Claude') 'claude_desktop_config.json') }
    if ($env:LOCALAPPDATA) {
        $pacotes = Join-Path $env:LOCALAPPDATA 'Packages'
        foreach ($p in @(Get-ChildItem -LiteralPath $pacotes -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue)) {
            $arquivos += (Join-Path $p.FullName 'LocalCache\Roaming\Claude\claude_desktop_config.json')
        }
    }
    foreach ($arq in $arquivos) {
        $dados = Ler-Json $arq
        if ($null -eq $dados -or $null -eq $dados.mcpServers) { continue }
        $nomes = @($dados.mcpServers.PSObject.Properties.Name)
        $mudou = $false
        foreach ($n in $NomesConector) {
            if ($nomes -contains $n) {
                $dados.mcpServers.PSObject.Properties.Remove($n)
                $mudou = $true
            }
        }
        if ($mudou) {
            Copy-Item -LiteralPath $arq -Destination ($arq + '.antes-da-desinstalacao.json') -Force
            Gravar-Json $arq $dados
        }
    }
}

function Remover-ConectorCodexToml {
    # Reserva, sem Python: tira a tabela [mcp_servers.assessor-integrado] do
    # config.toml do Codex/ChatGPT, com cópia de segurança.
    if (-not $env:USERPROFILE) { return }
    $arq = Join-Path (Join-Path $env:USERPROFILE '.codex') 'config.toml'
    if (-not (Test-Path -LiteralPath $arq)) { return }
    $texto = [IO.File]::ReadAllText($arq, [Text.Encoding]::UTF8)
    $novo = Remover-SecaoToml $texto $NomesConector
    if ($novo.Trim() -ne $texto.Trim()) {
        Copy-Item -LiteralPath $arq -Destination ($arq + '.antes-da-desinstalacao') -Force
        Gravar-Texto $arq $novo
    }
}

function Mandar-ParaLixeira {
    param([string]$Pasta)
    Add-Type -AssemblyName Microsoft.VisualBasic
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
        $Pasta,
        [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
        [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
}

function Apagar-DadosDoUsuario {
    param([string]$Pasta, [string]$Descricao)
    if (-not (Test-Path -LiteralPath $Pasta)) { return }
    $resumo = Descrever-Pasta $Pasta
    $apagar = $false
    if ($script:ModoSilencioso) {
        $apagar = [bool]$ApagarDados
    } else {
        Write-Host ''
        Write-Host ('   ' + $Descricao + ': ' + $Pasta + ' (' + $resumo + ')')
        $apagar = Perguntar 'Apagar também esta pasta? Ela vai para a Lixeira.' $false
    }
    if (-not $apagar) {
        Mostrar-Info ('Mantida: ' + $Pasta)
        return
    }
    try {
        if ($script:ModoSilencioso) {
            if (-not (Remover-Pasta $Pasta)) { throw 'arquivo em uso' }
        } else {
            Mandar-ParaLixeira $Pasta
        }
        $script:Feitos += $Descricao
        Mostrar-Ok ('Apagada: ' + $Pasta)
    } catch {
        $script:Problemas += ('Não foi possível apagar ' + $Pasta + ': ' + $_.Exception.Message)
        Mostrar-Aviso ('Não foi possível apagar ' + $Pasta + '.')
    }
}

function Desinstalar {
    Definir-Titulo 'Desinstalação do Assessor Integrado'
    Mostrar-Faixa 'ASSESSOR INTEGRADO - desinstalação' 'DarkBlue'
    Write-Host ''
    Write-Host ('   Pasta: ' + $Raiz)
    Write-Host ''
    Write-Host '   Serão removidos os atalhos, o conector do acervo no Claude e no ChatGPT'
    Write-Host '   e a pasta runtime (Python, bibliotecas e modelos). Os processos baixados,'
    Write-Host '   as transcrições e as senhas guardadas só serão apagados se você confirmar,'
    Write-Host '   um a um, logo adiante.'
    # No modo silencioso, quem chamou já decidiu: segue sem perguntar.
    if (-not $script:ModoSilencioso -and -not (Perguntar 'Continuar com a desinstalação?' $false)) {
        Mostrar-Info 'Nada foi alterado.'
        return 11
    }

    Write-Host ''
    if (-not (Fechar-Programa)) {
        Mostrar-Falha 'O programa continua aberto. Feche-o e rode o DESINSTALAR.bat de novo.'
        return 11
    }
    $dados = Pastas-DeDados

    # Conectores de IA (antes de apagar o runtime: o Python faz melhor).
    $viaPython = $false
    try { $viaPython = Remover-ConectoresPeloPython } catch { }
    if (-not $viaPython) {
        try { Remover-ConectorClaudeJson } catch { $script:Problemas += ('Conector do Claude: ' + $_.Exception.Message) }
        try { Remover-ConectorCodexToml } catch { $script:Problemas += ('Conector do ChatGPT: ' + $_.Exception.Message) }
    }
    Mostrar-Ok 'Conector do acervo removido do Claude Desktop e do ChatGPT (se existia).'

    # Atalhos - só os que apontam para esta pasta.
    $removidos = 0
    foreach ($arq in @(Arquivos-DoAtalho)) {
        if (Atalho-DestaPasta $arq $Raiz) {
            try { Remove-Item -LiteralPath $arq -Force -ErrorAction Stop; $removidos++ } catch {
                $script:Problemas += ('Atalho ' + $arq + ': ' + $_.Exception.Message)
            }
        }
    }
    Mostrar-Ok ('Atalhos removidos: ' + $removidos + '.')

    # Runtime.
    if (Test-Path -LiteralPath $Runtime) {
        Mostrar-Info 'Apagando a pasta runtime (pode levar um minuto)...'
        if (Remover-Pasta $Runtime) {
            Mostrar-Ok 'Pasta runtime apagada.'
        } else {
            $script:Problemas += 'A pasta runtime não pôde ser apagada por inteiro (arquivo em uso). Reinicie o computador e apague-a.'
            Mostrar-Aviso 'A pasta runtime não pôde ser apagada por inteiro.'
        }
    } else {
        Mostrar-Ok 'A pasta runtime já não existia.'
    }

    # Dados do usuário, só com confirmação.
    Apagar-DadosDoUsuario $dados.Acervo 'Acervo (processos baixados e transcrições)'
    Apagar-DadosDoUsuario $dados.Sigilosos 'Processos sigilosos'
    if ($env:LOCALAPPDATA) {
        $local = Join-Path $env:LOCALAPPDATA 'AssessorIntegrado'
        if (Test-Path -LiteralPath $local) {
            $apagar = [bool]$ApagarDados
            if (-not $script:ModoSilencioso) {
                Write-Host ''
                Write-Host ('   Senhas guardadas e sessões do navegador: ' + $local)
                $apagar = Perguntar 'Apagar também? (Recomendado se o computador for passar para outra pessoa.)' $false
            }
            if ($apagar) {
                if (Remover-Pasta $local) { Mostrar-Ok 'Senhas e sessões apagadas.' }
                else { $script:Problemas += ('Não foi possível apagar ' + $local + ' (navegador do programa aberto?).') }
            } else {
                Mostrar-Info ('Mantida: ' + $local)
            }
        }
    }

    if ($script:Problemas.Count -eq 0) {
        Mostrar-Faixa 'O Assessor Integrado foi removido deste computador.' 'DarkGreen'
    } else {
        Mostrar-Faixa 'DESINSTALAÇÃO PARCIAL: veja abaixo.' 'DarkYellow'
        foreach ($p in $script:Problemas) { Write-Host ('   - ' + $p) -ForegroundColor Yellow }
    }
    Write-Host ''
    Write-Host ('   A pasta ' + $Raiz + ' ainda guarda os arquivos do')
    Write-Host '   programa (e os dados que você decidiu manter). Quando não precisar mais'
    Write-Host '   deles, apague a pasta inteira.'
    if ($script:Problemas.Count -gt 0) { return 10 }
    return 0
}

# Ponto de teste (ver instalar.ps1): dublês para rodar fora do Windows.
if ($env:ASSESSOR_INSTALADOR_DUBLES -and (Test-Path -LiteralPath $env:ASSESSOR_INSTALADOR_DUBLES)) {
    . $env:ASSESSOR_INSTALADOR_DUBLES
}

$codigoSaida = 0
try {
    Preparar-Console
    New-Item -ItemType Directory -Force -Path $Logs | Out-Null
    try {
        $log = Join-Path $Logs ('desinstalacao-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
        Start-Transcript -LiteralPath $log -Force | Out-Null
        $script:Transcrevendo = $true
    } catch { }
    $codigoSaida = Desinstalar
} catch {
    Write-Host ''
    Write-Host ('   Erro inesperado na desinstalação: ' + $_.Exception.Message) -ForegroundColor Red
    $codigoSaida = 10
} finally {
    if ($script:Transcrevendo) { try { Stop-Transcript | Out-Null } catch { } }
}
Aguardar-Enter
exit $codigoSaida
