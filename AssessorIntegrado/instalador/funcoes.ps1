# ============================================================================
#  Assessor Integrado - funções comuns do instalador e do desinstalador
#
#  Carregado ("dot-sourced") por instalar.ps1, desinstalar.ps1 e
#  empacotar.ps1. Ao ser carregado, só DEFINE funções: nada é executado.
#  Por isso as funções puras (formatação, aspas da linha de comando, leitura
#  do resultado da verificação, leitura do config.ini) são testadas também
#  fora do Windows, pelo testes/test_instalador.py.
#
#  Regras de todos os .ps1 do instalador (o teste confere):
#   * UTF-8 COM BOM e fim de linha CRLF. O Windows PowerShell 5.1 lê UTF-8
#     sem BOM como ANSI (cp1252): "ç", "ã", aspas curvas e travessões viram
#     lixo, e uma aspa curva chega a ser lida como aspa de verdade;
#   * somente sintaxe do PowerShell 5.1, o que vem em todo Windows 10/11:
#     nada de ??, ?., operador ternário, && e || entre comandos;
#   * Join-Path com no máximo dois pedaços (o terceiro só existe no 6+).
# ============================================================================

# ------------------------------------------------------------ formatação

function Formatar-Duracao {
    # "45 s", "2 min 05 s", "1 h 03 min".
    param([double]$Segundos)
    $s = [int][math]::Round([math]::Max(0, $Segundos))
    if ($s -lt 60) { return ('{0} s' -f $s) }
    if ($s -lt 3600) {
        return ('{0} min {1:00} s' -f [int][math]::Floor($s / 60), ($s % 60))
    }
    return ('{0} h {1:00} min' -f [int][math]::Floor($s / 3600), [int][math]::Floor(($s % 3600) / 60))
}

function Formatar-Tamanho {
    # Vírgula decimal, como se escreve em português ("41,9 MB"). Não usa a
    # cultura pt-BR do sistema de propósito: num Windows em inglês (ou no
    # PowerShell sem ICU) ela não existe ou formata com ponto.
    param([double]$Bytes)
    $inv = [Globalization.CultureInfo]::InvariantCulture
    if ($Bytes -ge 1GB) { return (($Bytes / 1GB).ToString('0.0', $inv).Replace('.', ',') + ' GB') }
    if ($Bytes -ge 1MB) { return (($Bytes / 1MB).ToString('0.0', $inv).Replace('.', ',') + ' MB') }
    if ($Bytes -ge 1KB) { return (($Bytes / 1KB).ToString('0', $inv) + ' KB') }
    return ('{0} bytes' -f [int64]$Bytes)
}

function Barra-DeProgresso {
    # [######..................]  25%
    param([int]$Percentual, [int]$Largura = 24)
    $p = [math]::Min(100, [math]::Max(0, $Percentual))
    $cheios = [int][math]::Floor($Largura * $p / 100)
    return ('[' + ('#' * $cheios) + ('.' * ($Largura - $cheios)) + '] ' + ('{0,3}%' -f $p))
}

function Estimar-Minutos {
    # Faixa de tempo para baixar e instalar $MB megabytes: do otimista
    # (cerca de 5 MB/s) ao pessimista (cerca de 1 MB/s, comum em rede de
    # tribunal com proxy), mais o tempo fixo de extrair e instalar.
    param([double]$MB)
    if ($MB -le 0) { return @(1, 2) }
    $minimo = [int][math]::Ceiling($MB / 300) + 2
    $maximo = [int][math]::Ceiling($MB / 60) + 5
    return @($minimo, $maximo)
}

# ------------------------------------------------- linha de comando (aspas)

function Citar-Argumento {
    # Aspas segundo a regra do Windows (CommandLineToArgvW / runtime do C):
    # barras invertidas só são especiais antes de aspas. Um caminho como
    # "C:\Teste Área\" mal citado faria a aspa final virar parte do texto.
    param([AllowEmptyString()][AllowNull()][string]$Valor)
    if ($null -eq $Valor) { $Valor = '' }
    if ($Valor.Length -gt 0 -and $Valor -notmatch '[\s"]') { return $Valor }
    $escapado = [regex]::Replace($Valor, '(\\*)"', '$1$1\"')
    $escapado = [regex]::Replace($escapado, '(\\+)$', '$1$1')
    return ('"' + $escapado + '"')
}

function Montar-LinhaDeComando {
    param([string[]]$Argumentos)
    if ($null -eq $Argumentos -or $Argumentos.Count -eq 0) { return '' }
    $partes = @()
    foreach ($a in $Argumentos) { $partes += (Citar-Argumento $a) }
    return ($partes -join ' ')
}

# ------------------------------------------------------- respostas S/N

function Interpretar-Resposta {
    # $true, $false, ou $null quando a resposta não é sim nem não.
    param([AllowEmptyString()][AllowNull()][string]$Texto, [bool]$Padrao)
    if ([string]::IsNullOrWhiteSpace($Texto)) { return $Padrao }
    $t = $Texto.Trim().ToLowerInvariant()
    if (@('s', 'sim', 'y', 'yes') -contains $t) { return $true }
    if (@('n', 'nao', 'não', 'no') -contains $t) { return $false }
    return $null
}

# ------------------------------------------------- local da instalação

function Esta-NoOneDrive {
    # A pasta está dentro do OneDrive? $Raizes são as variáveis OneDrive,
    # OneDriveCommercial e OneDriveConsumer (passadas por quem chama, para a
    # função continuar pura e testável).
    param([string]$Caminho, [string[]]$Raizes = @())
    if ([string]::IsNullOrWhiteSpace($Caminho)) { return $false }
    $separadores = [char[]]@('\', '/')
    $c = $Caminho.TrimEnd($separadores).ToLowerInvariant() + '\'
    foreach ($r in $Raizes) {
        if ([string]::IsNullOrWhiteSpace($r)) { continue }
        $rr = $r.TrimEnd($separadores).ToLowerInvariant() + '\'
        if ($c.StartsWith($rr)) { return $true }
    }
    # "OneDrive" ou "OneDrive - Tribunal de Justiça" em qualquer nível
    return ($c -match '\\onedrive( - [^\\]+)?\\')
}

function Avaliar-Local {
    # O que há de errado (se houver) com a pasta onde o programa está.
    # Limite de 100 caracteres: o arquivo mais fundo das bibliotecas
    # (onnxruntime\tools\...\__pycache__\...cpython-312.pyc) tem cerca de
    # 160 caracteres a partir da pasta do programa, e o Windows, sem o
    # "LongPathsEnabled" (que só o administrador liga), para em 260.
    param([string]$Caminho, [string[]]$RaizesOneDrive = @(), [bool]$CaminhosLongos = $false,
          [int]$Limite = 100)
    $noOneDrive = Esta-NoOneDrive $Caminho $RaizesOneDrive
    $longo = ($Caminho.Length -gt $Limite) -and (-not $CaminhosLongos)
    $rede = $Caminho.StartsWith('\\')
    return [pscustomobject]@{
        OneDrive    = $noOneDrive
        Comprimento = $Caminho.Length
        Longo       = $longo
        Rede        = $rede
        Mover       = ($noOneDrive -or $longo -or $rede)
    }
}

# ------------------------------------------------- arquivos de texto/JSON

function Ler-VersaoDoPrograma {
    param([string]$Raiz)
    try {
        $arquivo = Join-Path (Join-Path $Raiz 'app') '__init__.py'
        $texto = [IO.File]::ReadAllText($arquivo, [Text.Encoding]::UTF8)
        $m = [regex]::Match($texto, '__version__\s*=\s*[''"]([^''"]+)[''"]')
        if ($m.Success) { return $m.Groups[1].Value }
    } catch { }
    return '0.0.0'
}

function Ler-ValorDoIni {
    # Valor de uma chave do config.ini (texto já lido), ou '' se não houver.
    # Mesmas regras do app/nucleo/config.py: comentário só no começo da
    # linha (';' ou '#'), seção e chave sem diferença de maiúsculas.
    param([AllowEmptyString()][string]$Texto, [string]$Secao, [string]$Chave)
    if (-not $Texto) { return '' }
    $secaoAtual = ''
    $alvoSecao = $Secao.ToLowerInvariant()
    $alvoChave = $Chave.ToLowerInvariant()
    foreach ($linha in ($Texto -split "`r?`n")) {
        $l = $linha.Trim()
        if ($l.Length -eq 0 -or $l.StartsWith(';') -or $l.StartsWith('#')) { continue }
        $m = [regex]::Match($l, '^\[(.+)\]$')
        if ($m.Success) { $secaoAtual = $m.Groups[1].Value.Trim().ToLowerInvariant(); continue }
        if ($secaoAtual -ne $alvoSecao) { continue }
        $m = [regex]::Match($l, '^([^=:]+?)\s*[=:]\s*(.*)$')
        if ($m.Success -and $m.Groups[1].Value.Trim().ToLowerInvariant() -eq $alvoChave) {
            return $m.Groups[2].Value.Trim()
        }
    }
    return ''
}

function Resolver-Pasta {
    # Como caminhos.resolver(): relativo à pasta do programa, ou absoluto;
    # %VARIAVEIS% do Windows são expandidas.
    param([AllowEmptyString()][string]$Valor, [string]$Padrao, [string]$Raiz)
    $texto = [Environment]::ExpandEnvironmentVariables(([string]$Valor).Trim())
    if (-not $texto) { $texto = $Padrao }
    if ($texto -match '^[A-Za-z]:[\\/]' -or $texto.StartsWith('\\') -or $texto.StartsWith('/')) {
        return $texto
    }
    return (Join-Path $Raiz $texto)
}

function Ler-Json {
    param([string]$Arquivo)
    if (-not $Arquivo -or -not (Test-Path -LiteralPath $Arquivo)) { return $null }
    try {
        $texto = [IO.File]::ReadAllText($Arquivo, [Text.Encoding]::UTF8)
        if ([string]::IsNullOrWhiteSpace($texto)) { return $null }
        return ($texto | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Gravar-Texto {
    # UTF-8 SEM BOM (o Python lê sem tropeçar) e troca atômica: uma queda de
    # energia no meio não deixa o arquivo pela metade.
    param([string]$Arquivo, [AllowEmptyString()][string]$Texto)
    $tmp = $Arquivo + '.tmp'
    [IO.File]::WriteAllText($tmp, $Texto, (New-Object System.Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $Arquivo -Force
}

function Gravar-Json {
    param([string]$Arquivo, $Objeto)
    Gravar-Texto $Arquivo ($Objeto | ConvertTo-Json -Depth 8)
}

function Hash-DoArquivo {
    param([string]$Arquivo)
    if (-not $Arquivo -or -not (Test-Path -LiteralPath $Arquivo)) { return '' }
    return (Get-FileHash -LiteralPath $Arquivo -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Confere-Hash {
    param([string]$Arquivo, [string]$Esperado)
    if (-not $Esperado) { return $false }
    return ((Hash-DoArquivo $Arquivo) -eq $Esperado.ToLowerInvariant())
}

function Remover-SecaoToml {
    # Tira do config.toml do Codex/ChatGPT a tabela [mcp_servers.<nome>] e as
    # subtabelas dela ([mcp_servers.<nome>.env]), preservando todo o resto.
    # Devolve o texto novo (igual ao original se não havia nada a tirar).
    param([AllowEmptyString()][string]$Texto, [string[]]$Nomes)
    if (-not $Texto) { return $Texto }
    $saida = New-Object System.Collections.Generic.List[string]
    $pulando = $false
    foreach ($linha in ($Texto -split "`r?`n")) {
        $m = [regex]::Match($linha, '^\s*\[\s*([^\]]+?)\s*\]\s*(#.*)?$')
        if ($m.Success) {
            $tabela = $m.Groups[1].Value -replace '\s', ''
            $pulando = $false
            foreach ($n in $Nomes) {
                $base = 'mcp_servers.' + $n
                $baseCitada = 'mcp_servers."' + $n + '"'
                if ($tabela -eq $base -or $tabela.StartsWith($base + '.') -or
                    $tabela -eq $baseCitada -or $tabela.StartsWith($baseCitada + '.')) {
                    $pulando = $true
                }
            }
        }
        if (-not $pulando) { $saida.Add($linha) }
    }
    return (($saida -join "`r`n").TrimEnd() + "`r`n")
}

# ------------------------------------------------- resultado da verificação

function Resumir-Verificacao {
    # Lê o JSON de "python -m app verificar --json" e separa o que é aviso
    # (inclusive falha de item opcional) do que é falha de item obrigatório.
    param($Dados)
    $itens = @()
    if ($null -ne $Dados -and $null -ne $Dados.itens) { $itens = @($Dados.itens) }
    $ok = @($itens | Where-Object { $_.situacao -eq 'ok' }).Count
    $avisos = @($itens | Where-Object { $_.situacao -eq 'aviso' -or ($_.situacao -eq 'falha' -and -not $_.obrigatorio) })
    $falhas = @($itens | Where-Object { $_.situacao -eq 'falha' -and $_.obrigatorio })
    $resultado = 'ok'
    if ($avisos.Count -gt 0) { $resultado = 'aviso' }
    if ($falhas.Count -gt 0 -or $itens.Count -eq 0) { $resultado = 'falha' }
    return [pscustomobject]@{
        Total     = $itens.Count
        Ok        = $ok
        Avisos    = $avisos
        Falhas    = $falhas
        Resultado = $resultado
    }
}

function Contar-Texto {
    # "nenhum aviso", "1 aviso", "3 avisos".
    param([int]$N, [string]$Singular, [string]$Plural, [string]$Nenhum)
    if ($N -eq 0) { return $Nenhum }
    if ($N -eq 1) { return ('1 ' + $Singular) }
    return ([string]$N + ' ' + $Plural)
}

# ------------------------------------------------------------- console

function Mostrar-Ok { param([string]$Texto) Write-Host ('        OK      ' + $Texto) -ForegroundColor Green }
function Mostrar-Aviso { param([string]$Texto) Write-Host ('        AVISO   ' + $Texto) -ForegroundColor Yellow }
function Mostrar-Falha { param([string]$Texto) Write-Host ('        FALHA   ' + $Texto) -ForegroundColor Red }
function Mostrar-Info { param([string]$Texto) Write-Host ('        ' + $Texto) -ForegroundColor Gray }
function Mostrar-Dica { param([string]$Texto) Write-Host ('                ' + $Texto) -ForegroundColor DarkGray }

function Mostrar-Faixa {
    # Uma faixa colorida, bem visível no meio do texto do console.
    param([string]$Texto, [string]$Fundo = 'DarkBlue')
    $linha = '  ' + ('=' * 66)
    Write-Host ''
    Write-Host $linha -ForegroundColor White
    Write-Host ('   ' + $Texto.PadRight(64)) -ForegroundColor White -BackgroundColor $Fundo
    Write-Host $linha -ForegroundColor White
}

function Definir-Titulo {
    param([string]$Texto)
    try { $Host.UI.RawUI.WindowTitle = $Texto } catch { }
}

function Preparar-Console {
    # Acentos certos também quando a saída vai para arquivo ou para o log do
    # CI (no console de verdade o PowerShell já escreve em Unicode). Sem BOM:
    # o UTF8 padrão do .NET poria um BOM no começo da saída redirecionada.
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
    $script:EntradaRedirecionada = $false
    try { $script:EntradaRedirecionada = [Console]::IsInputRedirected } catch { }
}

function Perguntar {
    # Sim/não com padrão. No modo silencioso (ou sem teclado, como no CI),
    # devolve o padrão sem perguntar - nunca trava esperando resposta.
    param([string]$Pergunta, [bool]$Padrao = $true)
    if ($script:ModoSilencioso -or $script:EntradaRedirecionada) { return $Padrao }
    $opcoes = '[s/N]'
    if ($Padrao) { $opcoes = '[S/n]' }
    while ($true) {
        Write-Host ''
        $resposta = Read-Host ('        ' + $Pergunta + ' ' + $opcoes)
        $valor = Interpretar-Resposta $resposta $Padrao
        if ($null -ne $valor) { return $valor }
        Write-Host '        Responda S (sim) ou N (não).' -ForegroundColor Yellow
    }
}

function Aguardar-Enter {
    param([string]$Texto = 'Pressione Enter para fechar esta janela')
    if ($script:ModoSilencioso -or $script:EntradaRedirecionada) { return }
    Write-Host ''
    try { $null = Read-Host ('  ' + $Texto) } catch { }
}

# ------------------------------------------------------ outros programas

function Executar {
    # Roda um programa À VISTA no mesmo console (barras de progresso do pip
    # e do curl aparecem como devem) e devolve o código de saída.
    #
    # Por que Start-Process e não "& programa": no PowerShell 5.1, quando a
    # saída do próprio PowerShell está redirecionada (no CI, ou num log), o
    # que o programa escreve no stderr - avisos comuns do pip - vira
    # "NativeCommandError" e, com $ErrorActionPreference = 'Stop', derruba o
    # instalador no meio. Com Start-Process o filho herda o console (ou o
    # redirecionamento) diretamente, e o PowerShell nem vê essas linhas.
    # As aspas da linha de comando são montadas aqui (Citar-Argumento),
    # porque o Start-Process 5.1 junta os argumentos sem aspas.
    param(
        [Parameter(Mandatory = $true)][string]$Programa,
        [string[]]$Argumentos = @(),
        [string]$Pasta = '',
        [int]$LimiteSegundos = 0,
        [string]$LinhaPronta = ''
    )
    $parametros = @{ FilePath = $Programa; NoNewWindow = $true; PassThru = $true }
    $linha = $LinhaPronta
    if (-not $linha) { $linha = Montar-LinhaDeComando $Argumentos }
    if ($linha) { $parametros['ArgumentList'] = $linha }
    if ($Pasta) { $parametros['WorkingDirectory'] = $Pasta }
    $processo = Start-Process @parametros
    # Sem tocar no Handle logo de saída, o ExitCode pode vir vazio quando o
    # processo termina rápido (defeito conhecido do Start-Process).
    $null = $processo.Handle
    if ($LimiteSegundos -gt 0) {
        if (-not $processo.WaitForExit($LimiteSegundos * 1000)) {
            Encerrar-Arvore $processo.Id
            return -1
        }
    } else {
        $processo.WaitForExit()
    }
    return [int]$processo.ExitCode
}

function Capturar {
    # Como Executar, mas guarda a saída (para conferências curtas: versão do
    # Python, um "import" de teste). A saída passa por arquivos temporários
    # em UTF-8, sem depender da página de código do console.
    param(
        [Parameter(Mandatory = $true)][string]$Programa,
        [string[]]$Argumentos = @(),
        [string]$Pasta = '',
        [int]$LimiteSegundos = 300
    )
    $arqSaida = [IO.Path]::GetTempFileName()
    $arqErro = [IO.Path]::GetTempFileName()
    try {
        $parametros = @{
            FilePath = $Programa; NoNewWindow = $true; PassThru = $true
            RedirectStandardOutput = $arqSaida; RedirectStandardError = $arqErro
        }
        $linha = Montar-LinhaDeComando $Argumentos
        if ($linha) { $parametros['ArgumentList'] = $linha }
        if ($Pasta) { $parametros['WorkingDirectory'] = $Pasta }
        $codigo = -1
        try {
            $processo = Start-Process @parametros
            $null = $processo.Handle
            if ($processo.WaitForExit($LimiteSegundos * 1000)) {
                $processo.WaitForExit()
                $codigo = [int]$processo.ExitCode
            } else {
                Encerrar-Arvore $processo.Id
            }
        } catch {
            return [pscustomobject]@{ Codigo = -1; Saida = ''; Erro = $_.Exception.Message }
        }
        $saida = ''
        $erro = ''
        try { $saida = [IO.File]::ReadAllText($arqSaida, [Text.Encoding]::UTF8).Trim() } catch { }
        try { $erro = [IO.File]::ReadAllText($arqErro, [Text.Encoding]::UTF8).Trim() } catch { }
        return [pscustomobject]@{ Codigo = $codigo; Saida = $saida; Erro = $erro }
    } finally {
        Remove-Item -LiteralPath $arqSaida, $arqErro -Force -ErrorAction SilentlyContinue
    }
}

function Encerrar-Arvore {
    # Mata o processo e os filhos dele (o pip abre outros Pythons).
    param([int]$Id)
    try {
        $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        Start-Process -FilePath $taskkill -ArgumentList ('/T /F /PID ' + $Id) -WindowStyle Hidden -Wait
    } catch {
        try { Stop-Process -Id $Id -Force -ErrorAction Stop } catch { }
    }
}

function Remover-Pasta {
    # Apaga uma pasta inteira. Se o Remove-Item tropeçar em caminho longo
    # demais (acima de 260 caracteres), o rd do cmd com o prefixo \\?\ termina
    # o serviço. Devolve $true se a pasta deixou de existir.
    param([string]$Pasta)
    if (-not $Pasta -or -not (Test-Path -LiteralPath $Pasta)) { return $true }
    try { Remove-Item -LiteralPath $Pasta -Recurse -Force -ErrorAction Stop } catch { }
    if (Test-Path -LiteralPath $Pasta) {
        $alvo = $Pasta
        if (-not $Pasta.StartsWith('\\')) { $alvo = '\\?\' + $Pasta }
        $cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
        try { $null = Executar $cmd @('/d', '/c', 'rd', '/s', '/q', $alvo) } catch { }
    }
    return (-not (Test-Path -LiteralPath $Pasta))
}

# ------------------------------------------------------ rede e downloads

function Configurar-Rede {
    # TLS 1.2 (o .NET do Windows 10 antigo ainda oferece TLS 1.0, que o
    # GitHub e o PyPI recusam) e o proxy do sistema com as credenciais do
    # Windows. O endereço do proxy (inclusive o vindo de script PAC) vai para
    # HTTPS_PROXY/HTTP_PROXY, que o pip, o curl e o huggingface_hub entendem.
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072
    } catch { }
    $script:Proxy = ''
    try {
        $sistema = [Net.WebRequest]::GetSystemWebProxy()
        $sistema.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials
        [Net.WebRequest]::DefaultWebProxy = $sistema
        $alvo = New-Object System.Uri 'https://pypi.org/'
        $via = $sistema.GetProxy($alvo)
        if ($null -ne $via -and $via.AbsoluteUri -ne $alvo.AbsoluteUri) {
            $script:Proxy = $via.AbsoluteUri.TrimEnd('/')
        }
    } catch { }
    if ($script:Proxy) {
        if (-not $env:HTTPS_PROXY) { $env:HTTPS_PROXY = $script:Proxy }
        if (-not $env:HTTP_PROXY) { $env:HTTP_PROXY = $script:Proxy }
    }
    return $script:Proxy
}

function Testar-Acesso {
    # '' se o endereço responde; senão, o motivo. Qualquer resposta HTTP
    # conta como acesso (404 incluído), menos 403/407, que em rede de
    # tribunal costumam ser o proxy recusando o site.
    param([string]$Url, [int]$Segundos = 15)
    try {
        $pedido = [Net.HttpWebRequest]::Create($Url)
        $pedido.Method = 'HEAD'
        $pedido.Timeout = $Segundos * 1000
        $pedido.AllowAutoRedirect = $true
        $pedido.UserAgent = 'AssessorIntegrado-Instalador'
        $resposta = $pedido.GetResponse()
        $resposta.Close()
        return ''
    } catch [System.Net.WebException] {
        $r = $_.Exception.Response
        if ($null -ne $r) {
            $status = [int]$r.StatusCode
            $r.Close()
            if ($status -eq 403 -or $status -eq 407) { return ('recusado pelo proxy (HTTP ' + $status + ')') }
            return ''
        }
        return $_.Exception.Message
    } catch {
        return $_.Exception.Message
    }
}

function Argumentos-Curl {
    param([string]$Url, [string]$Saida, [bool]$Retomar)
    # --ssl-no-revoke: em rede corporativa a consulta de revogação do
    # certificado costuma ser bloqueada e o curl desiste (CRYPT_E_NO_REVOCATION_CHECK).
    # A integridade não depende disso: todo download tem o SHA-256 conferido.
    $a = @('-L', '--fail', '--retry', '5', '--retry-delay', '3', '--connect-timeout', '30',
           '--ssl-no-revoke', '-o', $Saida)
    if ($Retomar) { $a += @('-C', '-') }
    if ($script:Proxy) { $a += @('--proxy', $script:Proxy, '--proxy-anyauth', '--proxy-user', ':') }
    $a += $Url
    return $a
}

function Baixar {
    # Download robusto e retomável: pula se o arquivo já está aqui com o
    # hash certo; baixa em .part (o curl retoma de onde parou); se o curl
    # falhar, tenta o Invoke-WebRequest e depois o BITS (que usam o proxy do
    # Windows); confere o SHA-256 e só então dá o nome final.
    param([string]$Url, [string]$Destino, [string]$Sha256, [string]$Descricao)
    if ((Test-Path -LiteralPath $Destino) -and (Confere-Hash $Destino $Sha256)) {
        Mostrar-Info ($Descricao + ': já baixado antes (integridade conferida).')
        return
    }
    $pasta = Split-Path -Parent $Destino
    $nomeParte = (Split-Path -Leaf $Destino) + '.part'
    $parte = Join-Path $pasta $nomeParte
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    $metodos = @('curl', 'curl-do-zero', 'powershell', 'bits')
    foreach ($metodo in $metodos) {
        if ((Test-Path -LiteralPath $parte) -and (Confere-Hash $parte $Sha256)) { break }
        try {
            if ($metodo -eq 'curl' -or $metodo -eq 'curl-do-zero') {
                if (-not $script:Curl -or -not (Test-Path -LiteralPath $script:Curl)) { continue }
                if ($metodo -eq 'curl-do-zero') {
                    Remove-Item -LiteralPath $parte -Force -ErrorAction SilentlyContinue
                    Mostrar-Info 'Recomeçando o download do zero...'
                }
                # Caminho relativo e pasta de trabalho: o curl do Windows
                # antigo recebe os argumentos em ANSI, e um "Á" no caminho
                # absoluto poderia se perder.
                $null = Executar $script:Curl (Argumentos-Curl $Url $nomeParte ($metodo -eq 'curl')) -Pasta $pasta
            } elseif ($metodo -eq 'powershell') {
                Mostrar-Info 'Tentando outro método de download (PowerShell)...'
                for ($i = 1; $i -le 3; $i++) {
                    try {
                        Remove-Item -LiteralPath $parte -Force -ErrorAction SilentlyContinue
                        $p = @{ Uri = $Url; OutFile = $parte; UseBasicParsing = $true; TimeoutSec = 900 }
                        if ($script:Proxy) { $p['Proxy'] = $script:Proxy; $p['ProxyUseDefaultCredentials'] = $true }
                        Invoke-WebRequest @p
                        break
                    } catch {
                        Start-Sleep -Seconds (5 * $i)
                    }
                }
            } else {
                Mostrar-Info 'Tentando outro método de download (BITS do Windows)...'
                Remove-Item -LiteralPath $parte -Force -ErrorAction SilentlyContinue
                Import-Module BitsTransfer -ErrorAction Stop
                Start-BitsTransfer -Source $Url -Destination $parte -Priority Foreground -ErrorAction Stop
            }
        } catch {
            Mostrar-Dica ('(' + $metodo + ': ' + $_.Exception.Message + ')')
        }
        if ((Test-Path -LiteralPath $parte) -and -not (Confere-Hash $parte $Sha256)) {
            Mostrar-Dica '(o arquivo recebido está incompleto ou não confere; tentando de novo)'
        }
    }
    if ((Test-Path -LiteralPath $parte) -and (Confere-Hash $parte $Sha256)) {
        Move-Item -LiteralPath $parte -Destination $Destino -Force
        return
    }
    throw ('não foi possível baixar ' + $Descricao + ' de ' + $Url)
}

# ------------------------------------------------------- Windows: diversos

function Achar-Navegador {
    # Google Chrome ou Microsoft Edge instalados (o Edge vem em todo
    # Windows 10/11). Devolve $null se nenhum dos dois existir.
    $bases = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432, $env:LOCALAPPDATA)
    $tipos = @(
        @{ Nome = 'Google Chrome'; Relativo = 'Google\Chrome\Application\chrome.exe'; Exe = 'chrome.exe' },
        @{ Nome = 'Microsoft Edge'; Relativo = 'Microsoft\Edge\Application\msedge.exe'; Exe = 'msedge.exe' }
    )
    foreach ($t in $tipos) {
        foreach ($b in $bases) {
            if (-not $b) { continue }
            $c = Join-Path $b $t.Relativo
            if (Test-Path -LiteralPath $c) { return [pscustomobject]@{ Nome = $t.Nome; Caminho = $c } }
        }
        foreach ($chave in @('HKCU:', 'HKLM:')) {
            try {
                $reg = Get-ItemProperty -Path ($chave + '\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\' + $t.Exe) -ErrorAction Stop
                $c = [string]$reg.'(default)'
                if ($c -and (Test-Path -LiteralPath $c.Trim('"'))) {
                    return [pscustomobject]@{ Nome = $t.Nome; Caminho = $c.Trim('"') }
                }
            } catch { }
        }
    }
    return $null
}

function Processos-DoPrograma {
    # Processos que rodam o Python desta instalação: a janela do programa
    # (pythonw) e o conector do acervo iniciado pelo Claude Desktop ou pelo
    # ChatGPT (python). Com eles abertos, as DLLs ficam presas e a
    # reinstalação falharia com "acesso negado".
    param([string]$Runtime)
    $prefixo = $Runtime.TrimEnd('\') + '\'
    $lista = @()
    foreach ($p in @(Get-Process -ErrorAction SilentlyContinue)) {
        $caminho = $null
        try { $caminho = $p.Path } catch { }
        if ($caminho -and $caminho.StartsWith($prefixo, [StringComparison]::OrdinalIgnoreCase)) {
            $lista += $p
        }
    }
    return $lista
}

function Caminhos-LongosAtivados {
    try {
        $v = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name 'LongPathsEnabled' -ErrorAction Stop
        return ([int]$v.LongPathsEnabled -eq 1)
    } catch {
        return $false
    }
}

function Criar-Atalho {
    param([string]$Arquivo, [string]$Alvo, [string]$Argumentos, [string]$PastaDeTrabalho,
          [string]$Icone, [string]$Descricao)
    $shell = New-Object -ComObject WScript.Shell
    try {
        $atalho = $shell.CreateShortcut($Arquivo)
        $atalho.TargetPath = $Alvo
        $atalho.Arguments = $Argumentos
        $atalho.WorkingDirectory = $PastaDeTrabalho
        if ($Icone -and (Test-Path -LiteralPath $Icone)) { $atalho.IconLocation = $Icone + ',0' }
        $atalho.Description = $Descricao
        $atalho.Save()
        # Relê: um caminho com caractere fora do ANSI poderia ser gravado
        # trocado, e o atalho apontaria para lugar nenhum.
        $conferido = $shell.CreateShortcut($Arquivo)
        if ($conferido.TargetPath -ne $Alvo) {
            throw ('o atalho foi gravado apontando para ' + $conferido.TargetPath)
        }
    } finally {
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
    }
}

function Atalho-DestaPasta {
    # O atalho existe e aponta para esta instalação? (Outra cópia do programa
    # em outra pasta tem atalho de mesmo nome; esse não é nosso para apagar.)
    param([string]$Arquivo, [string]$Raiz)
    if (-not (Test-Path -LiteralPath $Arquivo)) { return $false }
    try {
        $shell = New-Object -ComObject WScript.Shell
        try {
            $atalho = $shell.CreateShortcut($Arquivo)
            $texto = ($atalho.TargetPath + ' ' + $atalho.Arguments + ' ' + $atalho.WorkingDirectory)
            return ($texto.IndexOf($Raiz, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        } finally {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
        }
    } catch {
        return $false
    }
}

function Arquivos-DoAtalho {
    # Onde ficam os atalhos: Área de Trabalho (respeita o redirecionamento do
    # OneDrive) e Menu Iniciar do usuário. Nenhum dos dois pede administrador.
    $lista = @()
    foreach ($pasta in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        if ($pasta) { $lista += (Join-Path $pasta 'Assessor Integrado.lnk') }
    }
    return $lista
}

function Desbloquear-Arquivos {
    # Tira a "marca da web" (Zone.Identifier) que o Windows põe em tudo o que
    # sai de um ZIP baixado: sem isso, cada .bat abre com aviso de segurança.
    # As pastas de dados e o runtime ficam de fora (milhares de arquivos, e
    # nenhum veio da internet pelo navegador).
    param([string]$Pasta)
    $ignorar = @('runtime', 'Acervo', 'Sigilosos', 'Logs', '.git')
    $n = 0
    foreach ($item in @(Get-ChildItem -LiteralPath $Pasta -Force -ErrorAction SilentlyContinue)) {
        if ($item.PSIsContainer) {
            if ($ignorar -contains $item.Name) { continue }
            $arquivos = @(Get-ChildItem -LiteralPath $item.FullName -Recurse -File -Force -ErrorAction SilentlyContinue)
        } else {
            $arquivos = @($item)
        }
        foreach ($a in $arquivos) {
            try {
                $marca = Get-Item -LiteralPath $a.FullName -Stream 'Zone.Identifier' -ErrorAction SilentlyContinue
                if ($null -ne $marca) {
                    Unblock-File -LiteralPath $a.FullName -ErrorAction Stop
                    $n++
                }
            } catch { }
        }
    }
    return $n
}

function Esta-ComoAdministrador {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal $id
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Pasta-Gravavel {
    # A pasta existe (ou pode ser criada) e aceita gravar um arquivo?
    # Desfaz o que criou se a pasta não existia antes.
    param([string]$Pasta)
    $existia = Test-Path -LiteralPath $Pasta
    try {
        New-Item -ItemType Directory -Force -Path $Pasta -ErrorAction Stop | Out-Null
        $teste = Join-Path $Pasta ('.teste-' + [guid]::NewGuid().ToString('N') + '.tmp')
        [IO.File]::WriteAllText($teste, 'ok')
        Remove-Item -LiteralPath $teste -Force
        if (-not $existia) { Remove-Item -LiteralPath $Pasta -Force -ErrorAction SilentlyContinue }
        return $true
    } catch {
        return $false
    }
}
