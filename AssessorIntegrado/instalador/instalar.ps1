<#
    Assessor Integrado - instalador de um clique.

    Chamado pelo INSTALAR.bat (duplo clique). Instala tudo DENTRO da pasta do
    programa (runtime\), sem administrador e sem alterar o Windows: Python
    3.12 portátil, bibliotecas, modelo de transcrição, componente opcional de
    separação de falantes, config.ini, pastas de trabalho e atalhos. Termina
    com a verificação completa e um resumo verde, amarelo ou vermelho.

    Pode ser rodado quantas vezes for preciso: cada etapa confere se já está
    feita e pula; downloads interrompidos continuam de onde pararam (.part e
    cache do pip em runtime\). É também o "consertar instalação".

    Parâmetros (todos opcionais):
      -Silencioso        sem perguntas nem pausas (CI, implantação pela TI)
      -SemModelo         não baixa o modelo de transcrição agora
      -SemFalantes       não instala a separação automática de falantes
      -ModeloAoVivo X    base, small (padrão), medium ou large-v3-turbo
      -Pasta X           copia o programa para a pasta X e instala lá
      -SemAtalhos        não cria atalhos

    Códigos de saída: 0 = instalado (talvez com avisos); 10 = falhou algo
    obrigatório; 11 = impedido antes de começar (Windows incompatível, outra
    instalação em andamento, programa aberto).

    Arquivo em UTF-8 com BOM e CRLF; somente sintaxe do PowerShell 5.1.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$Silencioso,
    [switch]$SemModelo,
    [switch]$SemFalantes,
    [string]$ModeloAoVivo = '',
    [string]$Pasta = '',
    [switch]$SemAtalhos,
    [switch]$NaoMover,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Outros = @()
)

$ErrorActionPreference = 'Stop'
# Sem isto o Invoke-WebRequest do PowerShell 5.1 fica dezenas de vezes mais
# lento (redesenha a barra de progresso a cada pacote recebido).
$ProgressPreference = 'SilentlyContinue'

$Raiz = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'funcoes.ps1')

# --------------------------------------------------------------- constantes
# Python portátil (python-build-standalone, "install_only"): um .tar.gz com
# python.exe, pythonw.exe, Tkinter, pip e o runtime do Visual C++. Não grava
# nada no registro - o que elimina, de uma vez, as falhas do instalador
# oficial vistas no Assessor SAJ (reinstalar depois de apagar a pasta, modo
# "modify" quando já há outro Python, pedido de administrador do launcher).
$PythonVersao = '3.12.10'
$PythonUrl = 'https://github.com/astral-sh/python-build-standalone/releases/download/20250409/cpython-3.12.10%2B20250409-x86_64-pc-windows-msvc-install_only.tar.gz'
$PythonSha256 = '5ac66ae49a2104efeba985c1dc1cb40987757ee81cc6c7f218d10b801f3276ed'
$PythonArquivo = 'cpython-3.12.10-windows-x64.tar.gz'
$PythonMB = 42
# Reserva, se o GitHub estiver bloqueado: o instalador oficial, por usuário,
# com a pasta de destino forçada (hash conferido no manifesto do winget).
$PythonOficialUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$PythonOficialSha256 = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb'

$TamanhoModelos = @{ 'base' = 145; 'small' = 484; 'medium' = 1530; 'large-v3-turbo' = 1620 }
$BibliotecasMB = 200
$FalantesMB = 60
$ChromiumMB = 170
$TotalEtapas = 10

$Runtime = Join-Path $Raiz 'runtime'
$PyDir = Join-Path $Runtime 'python'
$PythonExe = Join-Path $PyDir 'python.exe'
$PythonwExe = Join-Path $PyDir 'pythonw.exe'
$Downloads = Join-Path $Runtime 'downloads'
$Logs = Join-Path $Raiz 'Logs'
$ArquivoEstado = Join-Path $Runtime 'estado.json'
$ArquivoVerificacao = Join-Path $Runtime 'verificacao.json'
$Trava = Join-Path $Runtime '.instalando'
$Requisitos = Join-Path $PSScriptRoot 'requisitos.txt'
$RequisitosFalantes = Join-Path $PSScriptRoot 'requisitos-falantes.txt'
$Iniciar = Join-Path $Raiz 'iniciar.pyw'
$Versao = Ler-VersaoDoPrograma $Raiz

# Opções do pip: só pacotes binários (nada de compilar no computador do
# usuário), versões e hashes travados, várias retentativas, sem atualizar o
# próprio pip (um antivírus segurando o pip.exe no meio da atualização
# deixava o pip quebrado na base).
$OpcoesPip = @('--require-hashes', '--only-binary=:all:', '--prefer-binary',
               '--no-warn-script-location', '--disable-pip-version-check', '--no-input',
               '--retries', '10', '--timeout', '60')

# Bibliotecas que têm de carregar no fim da etapa 3 (as que trazem DLL própria
# entram aqui: é onde aparece o "DLL load failed").
$TesteBibliotecas = 'import faster_whisper, ctranslate2, onnxruntime, av, numpy, sounddevice, soundfile, docx, pymupdf, pypdf, openpyxl, xlrd, playwright, PIL, huggingface_hub, requests'

# ------------------------------------------------------------------- estado
$script:ModoSilencioso = [bool]$Silencioso
$script:EntradaRedirecionada = $false
$script:Etapas = New-Object System.Collections.ArrayList
$script:Bloqueio = $null
$script:Interrupcao = $null
$script:TravaTomada = $false
$script:Transcrevendo = $false
$script:CodigoEncaminhado = $null
$script:Verificacao = $null
$script:Curl = Programa-DoWindows 'curl.exe'
$script:Tar = Programa-DoWindows 'tar.exe'
$script:Inicio = Get-Date
$script:Carimbo = Get-Date -Format 'yyyyMMdd-HHmmss'
$script:ArquivoLog = Join-Path $Logs ('instalacao-' + $script:Carimbo + '.log')
$script:ArquivoLogPip = Join-Path $Logs ('instalacao-' + $script:Carimbo + '-pip.log')
$script:ArgumentosIgnorados = @()
$script:Modelo = 'small'
$script:Pendencias = @()
# Copiado para um nome que nenhuma função usa como parâmetro: com o escopo
# dinâmico do PowerShell, um "$Pasta" local de quem chama esconderia este.
$script:PastaPedida = $Pasta

foreach ($o in @($Outros)) {
    if (-not $o) { continue }
    if (@('/s', '/silencioso', '-s', '/q', '--silencioso') -contains $o.ToLowerInvariant()) {
        $script:ModoSilencioso = $true
    } else {
        $script:ArgumentosIgnorados += $o
    }
}

# ======================================================== funções da etapa

function Bloquear {
    # Impede a instalação antes de ela mexer em qualquer coisa (código 11).
    param([string]$Motivo, [string]$OQueFazer)
    $script:Bloqueio = [pscustomobject]@{ Motivo = $Motivo; OQueFazer = $OQueFazer }
    throw ('BLOQUEIO: ' + $Motivo)
}

function Interromper {
    # Uma etapa obrigatória falhou: não adianta seguir (código 10).
    param([string]$Motivo, [string]$OQueFazer)
    $script:Interrupcao = [pscustomobject]@{ Motivo = $Motivo; OQueFazer = $OQueFazer }
    Mostrar-Falha $Motivo
    if ($OQueFazer) { Mostrar-Dica ('O que fazer: ' + $OQueFazer) }
    $null = Registrar-Etapa 'falha' $Motivo $OQueFazer
    throw ('INTERROMPIDA: ' + $Motivo)
}

function Iniciar-Etapa {
    param([int]$Numero, [string]$Titulo, [string]$Explicacao = '')
    $script:EtapaNumero = $Numero
    $script:EtapaTitulo = $Titulo
    $script:EtapaInicio = Get-Date
    $pct = [int][math]::Floor(100 * ($Numero - 1) / $TotalEtapas)
    if ($Numero -ge $TotalEtapas) { $pct = 100 }
    Write-Host ''
    Write-Host ('  [' + $Numero + '/' + $TotalEtapas + '] ' + $Titulo) -ForegroundColor Cyan
    if ($Explicacao) { Write-Host ('        ' + $Explicacao) -ForegroundColor DarkGray }
    Write-Host ('        Progresso geral ' + (Barra-DeProgresso $pct)) -ForegroundColor DarkGray
    Definir-Titulo ('Instalando o Assessor Integrado - etapa ' + $Numero + ' de ' + $TotalEtapas + ' (' + $pct + '%)')
}

function Registrar-Etapa {
    param([string]$Situacao, [string]$Detalhe, [string]$OQueFazer = '')
    $segundos = 0
    if ($script:EtapaInicio) { $segundos = ((Get-Date) - $script:EtapaInicio).TotalSeconds }
    [void]$script:Etapas.Add([pscustomobject]@{
        Numero = $script:EtapaNumero; Titulo = $script:EtapaTitulo; Situacao = $Situacao
        Detalhe = $Detalhe; OQueFazer = $OQueFazer; Segundos = $segundos
    })
    return $segundos
}

function Concluir-Etapa {
    param([string]$Situacao, [string]$Detalhe, [string]$OQueFazer = '')
    $segundos = Registrar-Etapa $Situacao $Detalhe $OQueFazer
    $texto = $Detalhe + ' (' + (Formatar-Duracao $segundos) + ')'
    if ($Situacao -eq 'ok') { Mostrar-Ok $texto }
    elseif ($Situacao -eq 'pulado') { Mostrar-Info ('PULADO  ' + $texto) }
    elseif ($Situacao -eq 'aviso') { Mostrar-Aviso $texto }
    else { Mostrar-Falha $texto }
    if ($OQueFazer) { Mostrar-Dica ('O que fazer: ' + $OQueFazer) }
}

function Ler-Estado {
    param([string]$Chave)
    $e = Ler-Json $ArquivoEstado
    if ($null -ne $e -and (@($e.PSObject.Properties.Name) -contains $Chave)) { return [string]$e.$Chave }
    return ''
}

function Gravar-Estado {
    # runtime\estado.json: o que já foi feito (para pular na próxima vez).
    param([string]$Chave, $Valor)
    $dados = [ordered]@{}
    $e = Ler-Json $ArquivoEstado
    if ($null -ne $e) { foreach ($p in $e.PSObject.Properties) { $dados[$p.Name] = $p.Value } }
    $dados[$Chave] = $Valor
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    Gravar-Json $ArquivoEstado $dados
}

function Python-Funciona {
    # O Python do runtime abre, é 3.12 de 64 bits e tem Tkinter, SSL e
    # SQLite. Uma cópia pela metade (extração interrompida) falha aqui.
    if (-not (Test-Path -LiteralPath $PythonExe)) { return $false }
    $codigo = 'import sys, tkinter, ssl, sqlite3, ctypes; tkinter.Tcl(); ' +
              'assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32; ' +
              'print(sys.version.split()[0])'
    $r = Capturar $PythonExe @('-c', $codigo) -Pasta $Raiz -LimiteSegundos 120
    if ($r.Codigo -eq 0) {
        $script:VersaoPython = $r.Saida
        return $true
    }
    return $false
}

function Bibliotecas-Erro {
    # '' se todas as bibliotecas carregam; senão, a última linha do erro.
    if (-not (Test-Path -LiteralPath $PythonExe)) { return 'o Python não está instalado' }
    $r = Capturar $PythonExe @('-c', $TesteBibliotecas) -Pasta $Raiz -LimiteSegundos 300
    if ($r.Codigo -eq 0) { return '' }
    $linhas = @(($r.Erro + "`n" + $r.Saida) -split "`r?`n" | Where-Object { $_.Trim() })
    if ($linhas.Count -eq 0) { return ('o Python terminou com o código ' + $r.Codigo) }
    return $linhas[$linhas.Count - 1].Trim()
}

function Modelo-Instalado {
    param([string]$Nome)
    $pasta = Join-Path (Join-Path $Runtime 'modelos') ('whisper-' + $Nome)
    foreach ($arq in @('config.json', 'tokenizer.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $pasta $arq))) { return $false }
    }
    $bin = Join-Path $pasta 'model.bin'
    if (-not (Test-Path -LiteralPath $bin)) { return $false }
    return ((Get-Item -LiteralPath $bin).Length -gt 1MB)
}

function Chromium-Proprio {
    $pasta = Join-Path $Runtime 'navegador'
    if (-not (Test-Path -LiteralPath $pasta)) { return $false }
    return (@(Get-ChildItem -LiteralPath $pasta -Directory -Filter 'chromium*' -ErrorAction SilentlyContinue).Count -gt 0)
}

function Falantes-Disponivel {
    if (-not (Test-Path -LiteralPath $PythonExe)) { return $false }
    $codigo = 'import sys; from app.transcricao import falantes; sys.exit(0 if falantes.disponivel() else 1)'
    $r = Capturar $PythonExe @('-c', $codigo) -Pasta $Raiz -LimiteSegundos 120
    return ($r.Codigo -eq 0)
}

function Preparar-Ambiente {
    # Variáveis para todos os programas chamados daqui (pip, Python, curl).
    # PYTHONHOME/PYTHONPATH globais (deixados por outros programas, como o
    # ArcGIS) quebram um Python portátil logo na partida; a pasta de pacotes
    # "do usuário" de outro Python 3.12 misturaria versões; e um pip.ini do
    # usuário poderia mandar instalar em outro lugar (user = true).
    foreach ($v in @('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP', 'PIP_USER', 'PIP_TARGET',
                     'PIP_PREFIX', 'PIP_REQUIRE_VIRTUALENV', 'VIRTUAL_ENV', 'PIP_INDEX_URL')) {
        Remove-Item -LiteralPath ('Env:' + $v) -ErrorAction SilentlyContinue
    }
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PIP_CONFIG_FILE = 'nul'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PIP_NO_INPUT = '1'
    $env:PIP_CACHE_DIR = Join-Path $Runtime 'pip-cache'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Runtime 'navegador'
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $null = Configurar-Rede
}

function Mostrar-Abertura {
    Definir-Titulo 'Instalador do Assessor Integrado'
    Mostrar-Faixa ('ASSESSOR INTEGRADO ' + $Versao + ' - instalação') 'DarkBlue'
    Write-Host ''
    Write-Host '   Baixa processos do e-SAJ e do eProc, transcreve audiências ao vivo'
    Write-Host '   e compartilha o acervo com o Claude e o ChatGPT.'
    Write-Host ''
    Write-Host '   Tudo fica dentro desta pasta: nada é instalado no Windows e não é'
    Write-Host '   preciso ser administrador. Se a internet cair, rode o INSTALAR.bat'
    Write-Host '   de novo: ele continua de onde parou.'
    Write-Host ''
    Write-Host ('   Pasta: ' + $Raiz) -ForegroundColor DarkGray
    Write-Host ('   Registro desta instalação: ' + $script:ArquivoLog) -ForegroundColor DarkGray
    if ($script:ArgumentosIgnorados.Count -gt 0) {
        Write-Host ('   Argumentos não reconhecidos (ignorados): ' + ($script:ArgumentosIgnorados -join ' ')) -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------ etapa 1

function Conferir-Windows {
    if (-not [Environment]::Is64BitOperatingSystem) {
        Bloquear 'Este Windows é de 32 bits.' 'O Assessor Integrado precisa do Windows 10 ou 11 de 64 bits.'
    }
    $build = Versao-DoWindows
    if ($build -lt 17763) {
        Bloquear ('Esta versão do Windows é antiga demais (compilação ' + $build + ').') 'Atualize para o Windows 10 versão 1809 ou mais recente, ou para o Windows 11.'
    }
    if (-not $script:Tar -or -not (Test-Path -LiteralPath $script:Tar)) {
        Bloquear 'Falta o tar.exe do Windows (System32).' 'Atualize o Windows pelo Windows Update e rode o INSTALAR.bat de novo.'
    }
    if (-not $script:Curl -or -not (Test-Path -LiteralPath $script:Curl)) { $script:Curl = '' }
    Mostrar-Ok ('Windows de 64 bits, compilação ' + $build + '.')
    if (Esta-ComoAdministrador) {
        Mostrar-Dica 'Aberto como administrador. Não é necessário: da próxima vez, use o duplo clique comum.'
    }
}

function Avaliar-Pasta {
    # Devolve $true se a instalação foi encaminhada para outra pasta.
    if ($script:PastaPedida) {
        $destino = [IO.Path]::GetFullPath($script:PastaPedida).TrimEnd('\')
        if ($destino -ieq $Raiz) {
            Mostrar-Info 'A pasta pedida em -Pasta já é esta; seguindo aqui.'
        } else {
            return (Mover-Para $destino)
        }
    }
    $raizesOneDrive = @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer)
    $local = Avaliar-Local $Raiz $raizesOneDrive (Caminhos-LongosAtivados) 100 (Pasta-Gravavel $Raiz) (Acento-SemNomeCurto $Raiz)
    if (-not $local.Mover) {
        Mostrar-Ok 'Local adequado: fora do OneDrive e com caminho curto.'
        return $false
    }
    # Sem permissão de gravar, instalar aqui é impossível (o runtime fica
    # dentro da pasta): ou o programa vai para outra pasta, ou nada feito.
    $impedido = 'Não é possível gravar na pasta do programa.'
    if ($local.SemGravacao) {
        Mostrar-Aviso 'Não há permissão para gravar nesta pasta, e o programa guarda dentro dela o'
        Mostrar-Dica 'Python, as bibliotecas e os registros.'
    }
    if ($local.SemNomeCurto) {
        Mostrar-Aviso 'O caminho desta pasta tem acento, e este disco não oferece nome curto sem'
        Mostrar-Dica 'acento: o modelo de transcrição não conseguiria abrir os próprios arquivos.'
    }
    if ($local.OneDrive) {
        Mostrar-Aviso 'Esta pasta fica dentro do OneDrive. A sincronização trava arquivos em uso'
        Mostrar-Dica 'e pode corromper o programa e os processos baixados.'
    }
    if ($local.Longo) {
        Mostrar-Aviso ('O caminho desta pasta é longo (' + $local.Comprimento + ' caracteres). Acima de 100,')
        Mostrar-Dica 'algumas bibliotecas ultrapassam o limite de 260 caracteres do Windows.'
    }
    if ($local.Rede) {
        Mostrar-Aviso 'Esta pasta fica na rede; o programa precisa estar no próprio computador.'
    }
    if ($NaoMover) {
        if ($local.SemGravacao) { Bloquear $impedido 'Extraia o ZIP numa pasta sua, por exemplo C:\AssessorIntegrado, e rode o INSTALAR.bat de lá.' }
        return $false
    }
    $sugerida = ''
    $candidatas = @()
    foreach ($base in @($env:SystemDrive, $env:USERPROFILE)) {
        if ($base) { $candidatas += (Join-Path $base 'AssessorIntegrado') }
    }
    foreach ($candidata in $candidatas) {
        # Com acento sem nome curto, o destino tem de ser só ASCII (a pasta
        # do usuário, "C:\Users\João", teria o mesmo problema).
        if ($local.SemNomeCurto -and (Tem-Acento $candidata)) { continue }
        if (-not (Esta-NoOneDrive $candidata $raizesOneDrive) -and (Pasta-Gravavel $candidata)) {
            $sugerida = $candidata
            break
        }
    }
    if (-not $sugerida) {
        if ($local.SemGravacao) { Bloquear $impedido 'Extraia o ZIP numa pasta sua, por exemplo C:\AssessorIntegrado, e rode o INSTALAR.bat de lá.' }
        return $false
    }
    if ($script:ModoSilencioso) {
        if ($local.SemGravacao) { Bloquear $impedido ('Rode o instalador com -Pasta ' + $sugerida + ', ou extraia o ZIP numa pasta sua.') }
        Mostrar-Dica ('Seguindo aqui (modo silencioso). Para instalar em outra pasta, use -Pasta ' + $sugerida + '.')
        return $false
    }
    $pergunta = 'Instalar em ' + $sugerida + '? (O programa é copiado para lá; esta pasta pode ser apagada depois.)'
    if (-not (Perguntar $pergunta $true)) {
        if ($local.SemGravacao) { Bloquear $impedido ('Extraia o ZIP numa pasta sua, por exemplo ' + $sugerida + ', e rode o INSTALAR.bat de lá.') }
        Mostrar-Info 'Certo: a instalação continua nesta pasta.'
        return $false
    }
    return (Mover-Para $sugerida)
}

function Mover-Para {
    # Copia o programa para $Destino e roda o instalador de lá. O código de
    # saída daquela instalação vira o desta.
    param([string]$Destino)
    $raizBarra = $Raiz.TrimEnd('\') + '\'
    if (($Destino.TrimEnd('\') + '\').StartsWith($raizBarra, [StringComparison]::OrdinalIgnoreCase)) {
        Bloquear 'A pasta de destino fica dentro da pasta atual.' 'Escolha uma pasta fora desta, por exemplo, C:\AssessorIntegrado.'
    }
    if (-not (Pasta-Gravavel $Destino)) {
        Bloquear ('Não foi possível gravar em ' + $Destino + '.') 'Escolha outra pasta com -Pasta (por exemplo, dentro da sua pasta de usuário).'
    }
    Mostrar-Info ('Copiando o programa para ' + $Destino + '...')
    New-Item -ItemType Directory -Force -Path $Destino | Out-Null
    $robocopy = Programa-DoWindows 'robocopy.exe'
    $codigo = Executar $robocopy @($Raiz, $Destino, '/E', '/XD', $Runtime, $Logs, (Join-Path $Raiz '.git'),
                                   '/R:2', '/W:2', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    # robocopy: 0 a 7 = sucesso (com ou sem arquivos copiados); 8 ou mais = erro.
    if ($codigo -lt 0 -or $codigo -ge 8) {
        Bloquear ('A cópia para ' + $Destino + ' falhou (robocopy ' + $codigo + ').') 'Confira o espaço livre e as permissões da pasta de destino.'
    }
    Mostrar-Ok ('Programa copiado. Continuando a instalação em ' + $Destino + '.')
    Mostrar-Dica ('Depois de instalado, esta pasta (' + $Raiz + ') pode ser apagada.')
    $argumentos = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    (Join-Path (Join-Path $Destino 'instalador') 'instalar.ps1'), '-NaoMover')
    if ($script:ModoSilencioso) { $argumentos += '-Silencioso' }
    if ($SemModelo) { $argumentos += '-SemModelo' }
    if ($SemFalantes) { $argumentos += '-SemFalantes' }
    if ($SemAtalhos) { $argumentos += '-SemAtalhos' }
    if ($ModeloAoVivo) { $argumentos += @('-ModeloAoVivo', $ModeloAoVivo) }
    $powershell = Programa-DoWindows 'WindowsPowerShell\v1.0\powershell.exe'
    try {
        $proprio = (Get-Process -Id $PID).Path
        if ($proprio) { $powershell = $proprio }
    } catch { }
    $script:CodigoEncaminhado = Executar $powershell $argumentos -Pasta $Destino
    return $true
}

function Processo-AnteriorA {
    # O processo já existia quando o arquivo foi gravado? O Windows reaproveita
    # números de processo: a trava de uma instalação interrompida (janela
    # fechada no meio) pode apontar para um PowerShell aberto depois, que nada
    # tem com ela - e bloquearia a instalação sem motivo. Na dúvida (sem acesso
    # à hora de início), considera que sim.
    param($Processo, [string]$Arquivo)
    $inicio = $null
    try { $inicio = $Processo.StartTime } catch { }
    if ($null -eq $inicio) { return $true }
    $gravado = [IO.File]::GetLastWriteTime($Arquivo)
    return ($inicio -le $gravado.AddSeconds(5))
}

function Tomar-Trava {
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    if (Test-Path -LiteralPath $Trava) {
        $dono = 0
        try { $dono = [int]([IO.File]::ReadAllText($Trava).Trim()) } catch { }
        if ($dono -gt 0 -and $dono -ne $PID) {
            $outro = Get-Process -Id $dono -ErrorAction SilentlyContinue
            if ($null -ne $outro -and $outro.ProcessName -match '^(powershell|pwsh)' -and (Processo-AnteriorA $outro $Trava)) {
                Bloquear 'Outra instalação está em andamento nesta pasta.' 'Espere a outra janela do instalador terminar (ou feche-a) e tente de novo.'
            }
        }
    }
    [IO.File]::WriteAllText($Trava, [string]$PID)
    $script:TravaTomada = $true
}

function Conferir-ProgramaFechado {
    $abertos = @(Processos-DoPrograma $Runtime)
    if ($abertos.Count -eq 0) { return }
    Mostrar-Aviso 'O Assessor Integrado está aberto (ou o Claude ou o ChatGPT está usando o'
    Mostrar-Dica 'conector do acervo). É preciso fechá-lo para atualizar a instalação.'
    if ($script:ModoSilencioso) {
        Bloquear 'O programa está aberto.' 'Feche o Assessor Integrado (e o Claude Desktop, se estiver aberto) e rode o instalador de novo.'
    }
    $pergunta = 'Fechar agora? Se houver uma audiência sendo transcrita, encerre-a antes no programa.'
    if (-not (Perguntar $pergunta $true)) {
        Bloquear 'O programa está aberto.' 'Feche o Assessor Integrado e rode o INSTALAR.bat de novo.'
    }
    foreach ($p in $abertos) { try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch { } }
    Start-Sleep -Seconds 2
    if (@(Processos-DoPrograma $Runtime).Count -gt 0) {
        Bloquear 'Não foi possível fechar o programa.' 'Feche-o (e o Claude Desktop) manualmente e rode o INSTALAR.bat de novo.'
    }
    Mostrar-Ok 'Programa fechado.'
}

function Montar-Plano {
    # O que falta, para dizer ao usuário quanto vai baixar e quanto demora.
    $script:Pendencias = @()
    $script:PythonPronto = Python-Funciona
    if (-not $script:PythonPronto) {
        $script:Pendencias += [pscustomobject]@{ Nome = 'Python 3.12'; MB = $PythonMB; Hosts = @('github.com') }
    }
    $script:BibliotecasProntas = $false
    if ($script:PythonPronto -and (Ler-Estado 'bibliotecas') -eq (Hash-DoArquivo $Requisitos)) {
        $script:BibliotecasProntas = ((Bibliotecas-Erro) -eq '')
    }
    if (-not $script:BibliotecasProntas) {
        $script:Pendencias += [pscustomobject]@{ Nome = 'Bibliotecas do programa'; MB = $BibliotecasMB; Hosts = @('pypi.org', 'files.pythonhosted.org') }
    }
    if (-not (Achar-Navegador) -and -not (Chromium-Proprio)) {
        $script:Pendencias += [pscustomobject]@{ Nome = 'Navegador do programa (não há Chrome nem Edge)'; MB = $ChromiumMB; Hosts = @('cdn.playwright.dev') }
    }
    if (-not $SemModelo -and -not (Modelo-Instalado $script:Modelo)) {
        $script:Pendencias += [pscustomobject]@{ Nome = ('Modelo de transcrição ' + $script:Modelo); MB = $TamanhoModelos[$script:Modelo]; Hosts = @('huggingface.co') }
    }
    if (-not $SemFalantes -and ((Ler-Estado 'falantes') -ne (Hash-DoArquivo $RequisitosFalantes) -or -not $script:BibliotecasProntas -or -not (Falantes-Disponivel))) {
        $script:Pendencias += [pscustomobject]@{ Nome = 'Separação de falantes, opcional'; MB = $FalantesMB; Hosts = @('pypi.org', 'github.com') }
    }
}

function Mostrar-Plano {
    if ($script:Pendencias.Count -eq 0) {
        Mostrar-Ok 'Tudo já está instalado: falta só conferir e atualizar os atalhos (cerca de 1 minuto).'
        return
    }
    $total = 0
    Mostrar-Info 'O que falta instalar:'
    foreach ($p in $script:Pendencias) {
        Mostrar-Info ('  - ' + $p.Nome + ' (cerca de ' + $p.MB + ' MB)')
        $total += $p.MB
    }
    $faixa = Estimar-Minutos $total
    $totalTexto = [string]$total + ' MB'
    if ($total -ge 1024) { $totalTexto = Formatar-Tamanho ($total * 1MB) }
    Mostrar-Info ('Total a baixar: cerca de ' + $totalTexto + '. Tempo estimado: de ' +
                  $faixa[0] + ' a ' + $faixa[1] + ' minutos, conforme a internet.')
    Mostrar-Dica 'Pode usar o computador enquanto isso; só não feche esta janela.'
}

function Conferir-Espaco {
    $total = 0
    foreach ($p in $script:Pendencias) { $total += $p.MB }
    # Baixado + extraído + cache do pip, com folga.
    $necessario = ([double]$total * 2.5 + 300) * 1MB
    try {
        $disco = New-Object System.IO.DriveInfo ([IO.Path]::GetPathRoot($Raiz))
        $livre = [double]$disco.AvailableFreeSpace
    } catch {
        Mostrar-Dica 'Não foi possível medir o espaço livre desta unidade.'
        return
    }
    if ($livre -lt $necessario) {
        Bloquear ('Falta espaço em disco: há ' + (Formatar-Tamanho $livre) + ' livres, e a instalação precisa de cerca de ' + (Formatar-Tamanho $necessario) + '.') 'Libere espaço nesta unidade (ou instale em outra, com -Pasta D:\AssessorIntegrado) e rode o INSTALAR.bat de novo.'
    }
    if ($livre -lt 3GB) {
        Mostrar-Aviso ('Pouco espaço livre: ' + (Formatar-Tamanho $livre) + '. Os processos e as gravações também ocupam espaço.')
    } else {
        Mostrar-Ok ('Espaço livre: ' + (Formatar-Tamanho $livre) + '.')
    }
}

function Conferir-Internet {
    $hosts = @()
    foreach ($p in $script:Pendencias) { foreach ($h in $p.Hosts) { if ($hosts -notcontains $h) { $hosts += $h } } }
    if ($hosts.Count -eq 0) { return }
    if ($script:Proxy) { Mostrar-Info ('Proxy da rede: ' + $script:Proxy) }
    $bloqueados = @()
    foreach ($h in $hosts) {
        $motivo = Testar-Acesso ('https://' + $h + '/')
        if ($motivo) { $bloqueados += ($h + ' (' + $motivo + ')') }
    }
    if ($bloqueados.Count -eq 0) {
        Mostrar-Ok ('Internet: acesso a ' + ($hosts -join ', ') + '.')
        return
    }
    Mostrar-Aviso 'Sem acesso a alguns endereços de que a instalação precisa:'
    foreach ($b in $bloqueados) { Mostrar-Dica ('- ' + $b) }
    Mostrar-Dica 'A instalação tenta assim mesmo. Se falhar, confira a conexão ou peça ao suporte'
    Mostrar-Dica 'de TI a liberação desses endereços, e rode o INSTALAR.bat de novo.'
}

function Etapa-Verificacoes {
    Iniciar-Etapa 1 'Verificações iniciais' 'Windows, local da pasta, espaço em disco e acesso à internet.'
    Conferir-Windows
    $n = Desbloquear-Arquivos $Raiz
    if ($n -gt 0) { Mostrar-Ok ('Liberados ' + $n + ' arquivos marcados pelo Windows como baixados da internet.') }
    Mostrar-Info ('Pasta do programa: ' + $Raiz)
    if (Avaliar-Pasta) { return }
    Tomar-Trava
    Conferir-ProgramaFechado
    Montar-Plano
    Conferir-Espaco
    Conferir-Internet
    Mostrar-Plano
    Registrar-Etapa 'ok' 'Windows, pasta, espaço em disco e internet conferidos.' | Out-Null
}

# ------------------------------------------------------------ etapa 2

function Instalar-PythonPortatil {
    $arquivo = Join-Path $Downloads $PythonArquivo
    Mostrar-Info ('Baixando o Python ' + $PythonVersao + ' (' + $PythonMB + ' MB) do GitHub...')
    Baixar $PythonUrl $arquivo $PythonSha256 'o Python'
    Mostrar-Ok 'Download conferido (SHA-256).'
    $tmp = Join-Path $Runtime '_py.tmp'
    $null = Remover-Pasta $tmp
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    Mostrar-Info 'Extraindo...'
    # Caminho relativo ao tar (o tar.exe do Windows lê os argumentos em ANSI).
    $codigo = Executar $script:Tar @('-xzf', ('..\downloads\' + $PythonArquivo)) -Pasta $tmp
    if ($codigo -ne 0) { throw ('o tar.exe terminou com o código ' + $codigo) }
    $extraido = Join-Path $tmp 'python'
    if (-not (Test-Path -LiteralPath (Join-Path $extraido 'python.exe'))) { throw 'o pacote não contém python\python.exe' }
    Mover-ComPaciencia $extraido $PyDir
    $null = Remover-Pasta $tmp
}

function Instalar-PythonOficial {
    $arquivo = Join-Path $Downloads 'python-3.12.10-amd64.exe'
    Mostrar-Info 'Tentando o instalador oficial do Python (python.org), só para este usuário...'
    Baixar $PythonOficialUrl $arquivo $PythonOficialSha256 'o instalador oficial do Python'
    # Include_launcher=0: o "py launcher" é o que pedia administrador.
    $linha = '/quiet InstallAllUsers=0 PrependPath=0 Include_pip=1 Include_tcltk=1 Include_test=0 ' +
             'Include_doc=0 Include_dev=0 Include_launcher=0 InstallLauncherAllUsers=0 ' +
             'AssociateFiles=0 Shortcuts=0 TargetDir="' + $PyDir + '"'
    $codigo = Executar $arquivo -LinhaPronta $linha -LimiteSegundos 900
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw ('o instalador oficial terminou (código ' + $codigo + ') sem criar runtime\python')
    }
}

function Copiar-PythonExistente {
    # Último recurso: um Python 3.12 de 64 bits já instalado neste computador
    # (o instalador oficial recusa uma segunda instalação da mesma versão).
    # Copia sem os pacotes dele, para não misturar versões.
    $origem = ''
    foreach ($chave in @('HKCU:\Software\Python\PythonCore\3.12\InstallPath', 'HKLM:\Software\Python\PythonCore\3.12\InstallPath')) {
        try {
            $valor = [string](Get-ItemProperty -Path $chave -ErrorAction Stop).'(default)'
            if ($valor -and (Test-Path -LiteralPath (Join-Path $valor 'python.exe'))) { $origem = $valor.TrimEnd('\'); break }
        } catch { }
    }
    if (-not $origem) { throw 'nenhum Python 3.12 instalado neste computador' }
    Mostrar-Info ('Copiando o Python 3.12 já instalado em ' + $origem + '...')
    $robocopy = Programa-DoWindows 'robocopy.exe'
    $codigo = Executar $robocopy @($origem, $PyDir, '/E', '/XD', (Join-Path $origem 'Lib\site-packages'),
                                   '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if ($codigo -ge 8) { throw ('a cópia falhou (robocopy ' + $codigo + ')') }
    $null = Executar $PythonExe @('-m', 'ensurepip', '--default-pip') -Pasta $Raiz
}

function Etapa-Python {
    Iniciar-Etapa 2 'Python 3.12' 'Fica dentro da pasta do programa; não altera o Windows nem outros Pythons.'
    if ($script:PythonPronto -or (Python-Funciona)) {
        Concluir-Etapa 'ok' ('Python ' + $script:VersaoPython + ' já instalado.')
        return
    }
    if (Test-Path -LiteralPath $PyDir) {
        Mostrar-Info 'A cópia anterior do Python está incompleta; refazendo.'
        if (-not (Remover-Pasta $PyDir)) {
            Interromper 'Não foi possível apagar a cópia anterior do Python (arquivo em uso).' 'Reinicie o computador e rode o INSTALAR.bat de novo.'
        }
    }
    $metodos = @('Instalar-PythonPortatil', 'Instalar-PythonOficial', 'Copiar-PythonExistente')
    foreach ($metodo in $metodos) {
        try {
            & $metodo
            if (Python-Funciona) { break }
            Mostrar-Aviso 'O Python instalado não passou no teste; tentando outro caminho.'
        } catch {
            Mostrar-Aviso ('Não deu certo: ' + $_.Exception.Message + '.')
        }
        if (Test-Path -LiteralPath $PyDir) { $null = Remover-Pasta $PyDir }
    }
    if (-not (Python-Funciona)) {
        Interromper 'Não foi possível instalar o Python.' 'Confira a internet (o download vem de github.com) e rode o INSTALAR.bat de novo: o que já foi baixado é aproveitado.'
    }
    Gravar-Estado 'python' $script:VersaoPython
    # Python novo vem sem pacote nenhum: o que o estado dizia das bibliotecas
    # e da separação de falantes não vale mais (sem isto, o componente de
    # falantes não seria reinstalado pela etapa 6, que o confere pelo estado).
    Gravar-Estado 'bibliotecas' ''
    Gravar-Estado 'falantes' ''
    Concluir-Etapa 'ok' ('Python ' + $script:VersaoPython + ' instalado.')
}

# ------------------------------------------------------------ etapa 3

function Instalar-Requisitos {
    # pip com até 3 tentativas. O cache em runtime\pip-cache faz a tentativa
    # seguinte (ou a próxima execução do INSTALAR.bat) aproveitar o que já
    # chegou. Devolve o código de saída da última tentativa.
    param([string]$Arquivo)
    New-Item -ItemType Directory -Force -Path $env:PIP_CACHE_DIR | Out-Null
    $argumentos = @('-m', 'pip', 'install') + $OpcoesPip + @('--log', $script:ArquivoLogPip, '-r', $Arquivo)
    $codigo = 1
    for ($tentativa = 1; $tentativa -le 3; $tentativa++) {
        if ($tentativa -gt 1) {
            Mostrar-Aviso ('A instalação das bibliotecas falhou; tentando de novo (' + $tentativa + ' de 3)...')
            Start-Sleep -Seconds (10 * ($tentativa - 1))
        }
        $codigo = Executar $PythonExe $argumentos -Pasta $Raiz
        if ($codigo -eq 0) { break }
    }
    return $codigo
}

function Etapa-Bibliotecas {
    Iniciar-Etapa 3 'Bibliotecas do programa' ('Transcrição, PDF, Word, Excel e automação do navegador (cerca de ' + $BibliotecasMB + ' MB).')
    $hash = Hash-DoArquivo $Requisitos
    if ($script:BibliotecasProntas) {
        Concluir-Etapa 'ok' 'Bibliotecas já instaladas e conferidas.'
        return
    }
    Mostrar-Info 'Na primeira vez, esta é a etapa mais demorada.'
    $codigo = Instalar-Requisitos $Requisitos
    if ($codigo -ne 0) {
        Interromper 'As bibliotecas do programa não foram instaladas.' ('Confira a internet e rode o INSTALAR.bat de novo (o que já foi baixado é aproveitado). Se um antivírus estiver bloqueando, peça ao suporte para liberar a pasta ' + $Raiz + '. Detalhes em ' + $script:ArquivoLogPip + '.')
    }
    $erro = Bibliotecas-Erro
    if ($erro) {
        # Não interrompe: uma DLL que não carrega (processador antigo para a
        # transcrição, antivírus que reteve um arquivo) costuma afetar uma
        # função só. A instalação segue - pastas, atalhos - e a verificação
        # final aponta o componente e o que fazer. O estado não é gravado:
        # a próxima execução confere tudo de novo.
        Concluir-Etapa 'falha' ('As bibliotecas foram instaladas, mas não carregam: ' + $erro) 'Veja a verificação final, adiante. Se o erro falar em DLL, reinicie o computador e rode o INSTALAR.bat de novo; se persistir, envie o registro da instalação ao suporte.'
        return
    }
    $script:BibliotecasProntas = $true
    Gravar-Estado 'bibliotecas' $hash
    Concluir-Etapa 'ok' 'Bibliotecas instaladas e conferidas.'
}

# ------------------------------------------------------------ etapa 4

function Etapa-Navegador {
    Iniciar-Etapa 4 'Navegador para o e-SAJ e o eProc' 'O download dos processos usa o Google Chrome ou o Microsoft Edge já instalados.'
    $navegador = Achar-Navegador
    if ($null -ne $navegador) {
        Concluir-Etapa 'ok' ($navegador.Nome + ' encontrado.')
        return
    }
    if (Chromium-Proprio) {
        Concluir-Etapa 'ok' 'Navegador próprio do programa já instalado.'
        return
    }
    Mostrar-Info ('Nem o Chrome nem o Edge foram encontrados; baixando o navegador do programa (cerca de ' + $ChromiumMB + ' MB)...')
    $codigo = Executar $PythonExe @('-m', 'playwright', 'install', 'chromium') -Pasta $Raiz -LimiteSegundos 1800
    if ($codigo -eq 0 -and (Chromium-Proprio)) {
        Concluir-Etapa 'ok' 'Navegador do programa instalado.'
    } else {
        Concluir-Etapa 'aviso' 'Não foi possível baixar o navegador do programa.' 'Instale o Google Chrome ou o Microsoft Edge e rode o INSTALAR.bat de novo. Sem navegador, o download de processos não funciona.'
    }
}

# ------------------------------------------------------------ etapa 5

function Etapa-Modelo {
    $nome = $script:Modelo
    Iniciar-Etapa 5 ('Modelo de transcrição (' + $nome + ')') ('Reconhecimento de fala em português que roda no próprio computador (cerca de ' + $TamanhoModelos[$nome] + ' MB).')
    if ($SemModelo) {
        Concluir-Etapa 'pulado' 'Pulado a pedido (-SemModelo): o modelo será baixado no primeiro uso.'
        return
    }
    if (Modelo-Instalado $nome) {
        Concluir-Etapa 'ok' 'Modelo já instalado.'
        return
    }
    for ($tentativa = 1; $tentativa -le 2; $tentativa++) {
        if ($tentativa -gt 1) { Mostrar-Info 'Tentando de novo (o download continua de onde parou)...' }
        $null = Executar $PythonExe @('-m', 'app', 'modelos', 'baixar', $nome) -Pasta $Raiz
        if (Modelo-Instalado $nome) { break }
    }
    if (Modelo-Instalado $nome) {
        Gravar-Estado 'modelo' $nome
        Concluir-Etapa 'ok' 'Modelo baixado e conferido.'
    } else {
        Concluir-Etapa 'aviso' 'Não foi possível baixar o modelo agora.' 'Ele será baixado no primeiro uso da transcrição; ou rode o INSTALAR.bat de novo. Se a rede do tribunal bloquear huggingface.co, peça ao suporte a liberação.'
    }
}

# ------------------------------------------------------------ etapa 6

function Etapa-Falantes {
    Iniciar-Etapa 6 'Separação automática de falantes (opcional)' ('Identifica quem fala nas gravações, na revisão final (cerca de ' + $FalantesMB + ' MB).')
    if ($SemFalantes) {
        Concluir-Etapa 'pulado' 'Pulado a pedido (-SemFalantes). Pode ser instalado depois, em Configurações.'
        return
    }
    $hash = Hash-DoArquivo $RequisitosFalantes
    if ((Ler-Estado 'falantes') -ne $hash) {
        $codigo = Instalar-Requisitos $RequisitosFalantes
        if ($codigo -ne 0) {
            Concluir-Etapa 'aviso' 'O componente não foi instalado.' 'O programa funciona sem ele (os falantes são marcados pelos botões F1 a F8). Para tentar de novo: Configurações > Transcrição > Instalar componente, ou o INSTALAR.bat.'
            return
        }
        Gravar-Estado 'falantes' $hash
    }
    $codigo = Executar $PythonExe @('-m', 'app', 'falantes', 'instalar') -Pasta $Raiz -LimiteSegundos 1800
    if ($codigo -eq 0 -and (Falantes-Disponivel)) {
        Concluir-Etapa 'ok' 'Separação de falantes pronta.'
    } else {
        Concluir-Etapa 'aviso' 'Os modelos de voz do componente não foram baixados.' 'O programa funciona sem eles. Para tentar de novo: Configurações > Transcrição > Instalar componente, ou o INSTALAR.bat.'
    }
}

# ------------------------------------------------------------ etapa 7

function Etapa-Configuracao {
    Iniciar-Etapa 7 'Configuração e pastas de trabalho' 'config.ini e as pastas Acervo (Processos e Transcricoes), Sigilosos e Logs.'
    $codigo = Executar $PythonExe @('-m', 'app', 'preparar-pastas') -Pasta $Raiz -LimiteSegundos 300
    if ($codigo -ne 0) {
        Concluir-Etapa 'falha' 'O programa não conseguiu criar a configuração e as pastas.' 'Veja a mensagem acima; rode o INSTALAR.bat de novo e, se persistir, envie o registro ao suporte.'
        return
    }
    if ($ModeloAoVivo) {
        $codigoPy = "from app.nucleo import config; config.carregar().definir('transcricao', 'modelo_ao_vivo', '" + $script:Modelo + "')"
        $null = Executar $PythonExe @('-c', $codigoPy) -Pasta $Raiz -LimiteSegundos 120
    }
    Concluir-Etapa 'ok' 'Configuração e pastas prontas.'
}

# ------------------------------------------------------------ etapa 8

function Etapa-Atalhos {
    Iniciar-Etapa 8 'Atalhos' 'Na Área de Trabalho e no Menu Iniciar.'
    if ($SemAtalhos) {
        Concluir-Etapa 'pulado' 'Pulado a pedido (-SemAtalhos). Para abrir, use o "Assessor Integrado.bat".'
        return
    }
    # -E e -s: o programa ignora PYTHONHOME/PYTHONPATH globais e os pacotes
    # "do usuário" de outro Python - abre sempre com as versões instaladas aqui.
    $argumentos = '-E -s "' + $Iniciar + '"'
    $icone = Join-Path $Raiz 'app\interface\recursos\assessor.ico'
    $descricao = 'Baixa processos, transcreve audiências e compartilha o acervo com a IA'
    $criados = 0
    $erros = @()
    foreach ($arquivo in @(Arquivos-DoAtalho)) {
        try {
            Criar-Atalho $arquivo $PythonwExe $argumentos $Raiz $icone $descricao
            $criados++
        } catch {
            $erros += ($arquivo + ': ' + $_.Exception.Message)
        }
    }
    if ($erros.Count -eq 0 -and $criados -gt 0) {
        Concluir-Etapa 'ok' 'Atalho "Assessor Integrado" pronto na Área de Trabalho e no Menu Iniciar.'
    } else {
        foreach ($e in $erros) { Mostrar-Dica $e }
        Concluir-Etapa 'aviso' 'Não foi possível criar todos os atalhos.' 'O programa abre pelo arquivo "Assessor Integrado.bat", nesta pasta.'
    }
}

# ------------------------------------------------------------ etapa 9

function Etapa-Verificacao {
    Iniciar-Etapa 9 'Verificação final' 'Testa cada parte: bibliotecas, modelo, navegador, microfone, pastas e cofre de senhas.'
    Remove-Item -LiteralPath $ArquivoVerificacao -Force -ErrorAction SilentlyContinue
    $null = Executar $PythonExe @('-m', 'app', 'verificar', '--completo', '--json', $ArquivoVerificacao) -Pasta $Raiz -LimiteSegundos 900
    $dados = Ler-Json $ArquivoVerificacao
    if ($null -eq $dados) {
        Concluir-Etapa 'falha' 'A verificação não pôde ser concluída.' 'Veja as mensagens acima e rode o INSTALAR.bat de novo.'
        return
    }
    $script:Verificacao = Resumir-Verificacao $dados
    $texto = [string]$script:Verificacao.Ok + ' OK, ' +
             (Contar-Texto $script:Verificacao.Avisos.Count 'aviso' 'avisos' 'nenhum aviso') + ' e ' +
             (Contar-Texto $script:Verificacao.Falhas.Count 'falha' 'falhas' 'nenhuma falha') + '.'
    if ($script:Verificacao.Resultado -eq 'falha') { Concluir-Etapa 'falha' $texto }
    elseif ($script:Verificacao.Resultado -eq 'aviso') { Concluir-Etapa 'aviso' $texto }
    else { Concluir-Etapa 'ok' $texto }
}

# ------------------------------------------------------------ etapa 10

function Resultado-Geral {
    $resultado = 'ok'
    foreach ($e in $script:Etapas) {
        if ($e.Situacao -eq 'aviso' -and $resultado -eq 'ok') { $resultado = 'aviso' }
        if ($e.Situacao -eq 'falha') { $resultado = 'falha' }
    }
    return $resultado
}

function Mostrar-Resumo {
    param([string]$Resultado)
    $duracao = Formatar-Duracao ((Get-Date) - $script:Inicio).TotalSeconds
    if ($Resultado -eq 'ok') {
        Mostrar-Faixa 'PRONTO! O Assessor Integrado está instalado.' 'DarkGreen'
    } elseif ($Resultado -eq 'aviso') {
        Mostrar-Faixa 'INSTALADO, COM AVISOS: o programa funciona; veja abaixo.' 'DarkYellow'
    } else {
        Mostrar-Faixa 'A INSTALAÇÃO NÃO FOI CONCLUÍDA.' 'DarkRed'
    }
    Write-Host ''
    Write-Host '   Etapas:'
    foreach ($e in $script:Etapas) {
        $rotulo = 'OK     '
        $cor = 'Green'
        if ($e.Situacao -eq 'aviso') { $rotulo = 'AVISO  '; $cor = 'Yellow' }
        elseif ($e.Situacao -eq 'falha') { $rotulo = 'FALHA  '; $cor = 'Red' }
        elseif ($e.Situacao -eq 'pulado') { $rotulo = 'PULADO '; $cor = 'Gray' }
        Write-Host ('     ' + $rotulo + $e.Titulo + ' - ' + $e.Detalhe) -ForegroundColor $cor
        if ($e.OQueFazer -and $e.Situacao -ne 'ok') { Write-Host ('            O que fazer: ' + $e.OQueFazer) -ForegroundColor DarkGray }
    }
    if ($null -ne $script:Verificacao) {
        $itens = @($script:Verificacao.Falhas) + @($script:Verificacao.Avisos)
        if ($itens.Count -gt 0) {
            Write-Host ''
            Write-Host '   Pontos da verificação:'
            foreach ($i in $itens) {
                $cor = 'Yellow'
                if ($i.situacao -eq 'falha' -and $i.obrigatorio) { $cor = 'Red' }
                Write-Host ('     - ' + $i.nome + ': ' + $i.detalhe) -ForegroundColor $cor
                if ($i.acao) { Write-Host ('       O que fazer: ' + $i.acao) -ForegroundColor DarkGray }
            }
        }
    }
    Write-Host ''
    if ($Resultado -ne 'falha') {
        Write-Host '   Para abrir: atalho "Assessor Integrado" na Área de Trabalho ou no Menu'
        Write-Host '   Iniciar, ou o arquivo "Assessor Integrado.bat", nesta pasta.'
    } else {
        Write-Host '   O que fazer: confira a internet e rode o INSTALAR.bat de novo; ele continua'
        Write-Host '   de onde parou. Se o erro se repetir, envie ao suporte o registro abaixo.'
    }
    Write-Host ''
    Write-Host ('   Tempo total: ' + $duracao + '.') -ForegroundColor DarkGray
    Write-Host ('   Registro desta instalação: ' + $script:ArquivoLog) -ForegroundColor DarkGray
}

function Etapa-Conclusao {
    Iniciar-Etapa 10 'Conclusão' ''
    $resultado = Resultado-Geral
    try {
        Gravar-Estado 'versao' $Versao
        Gravar-Estado 'instalado_em' (Get-Date -Format 's')
        Gravar-Estado 'pasta' $Raiz
        Gravar-Estado 'resultado' $resultado
        Gravar-Estado 'modelo_ao_vivo' $script:Modelo
        Gravar-Estado 'registro' $script:ArquivoLog
    } catch {
        Mostrar-Dica ('(não foi possível gravar runtime\estado.json: ' + $_.Exception.Message + ')')
    }
    Definir-Titulo 'Instalador do Assessor Integrado - concluído'
    Mostrar-Resumo $resultado
    return $resultado
}

function Oferecer-Abrir {
    param([string]$Resultado)
    if ($script:ModoSilencioso -or $script:EntradaRedirecionada) { return }
    if ($Resultado -eq 'falha') {
        Aguardar-Enter
        return
    }
    if (Perguntar 'Abrir o Assessor Integrado agora?' $true) {
        try {
            Start-Process -FilePath $PythonwExe -ArgumentList ('-E -s "' + $Iniciar + '"') -WorkingDirectory $Raiz
        } catch {
            Mostrar-Aviso ('Não foi possível abrir: ' + $_.Exception.Message)
            Aguardar-Enter
        }
    }
}

# ================================================================ principal

function Instalar {
    $null = Etapa-Verificacoes
    if ($null -ne $script:CodigoEncaminhado) { return [int]$script:CodigoEncaminhado }
    $null = Etapa-Python
    $null = Etapa-Bibliotecas
    $null = Etapa-Navegador
    $null = Etapa-Modelo
    $null = Etapa-Falantes
    $null = Etapa-Configuracao
    $null = Etapa-Atalhos
    $null = Etapa-Verificacao
    $resultado = Etapa-Conclusao
    $null = Oferecer-Abrir $resultado
    if ($resultado -eq 'falha') { return 10 }
    return 0
}

function Tratar-Erro {
    param($Erro)
    if ($null -ne $script:Bloqueio) {
        Mostrar-Faixa 'A INSTALAÇÃO NÃO PÔDE COMEÇAR.' 'DarkRed'
        Write-Host ''
        Write-Host ('   ' + $script:Bloqueio.Motivo) -ForegroundColor Red
        Write-Host ('   O que fazer: ' + $script:Bloqueio.OQueFazer)
        Write-Host ''
        Write-Host ('   Registro: ' + $script:ArquivoLog) -ForegroundColor DarkGray
        Aguardar-Enter
        return 11
    }
    if ($null -eq $script:Interrupcao) {
        # Erro que nenhuma etapa previu: mostra tudo o que ajuda o suporte.
        $linha = ''
        try { $linha = ' (linha ' + $Erro.InvocationInfo.ScriptLineNumber + ')' } catch { }
        Write-Host ''
        Write-Host ('   Erro inesperado no instalador' + $linha + ': ' + $Erro.Exception.Message) -ForegroundColor Red
        try { Write-Host ([string]$Erro.ScriptStackTrace) -ForegroundColor DarkGray } catch { }
        if ($script:EtapaTitulo) { Registrar-Etapa 'falha' ('Erro inesperado: ' + $Erro.Exception.Message) '' | Out-Null }
    }
    $null = Mostrar-Resumo 'falha'
    Aguardar-Enter
    return 10
}

# Ponto de teste: o testes/test_instalador.py aponta esta variável para um
# arquivo que troca as funções que mexem no Windows de verdade (downloads,
# pip, atalhos) por dublês, e assim percorre o roteiro inteiro - inclusive
# fora do Windows. Sem a variável, nada muda.
if ($env:ASSESSOR_INSTALADOR_DUBLES -and (Test-Path -LiteralPath $env:ASSESSOR_INSTALADOR_DUBLES)) {
    . $env:ASSESSOR_INSTALADOR_DUBLES
}

$codigoSaida = 0
try {
    Preparar-Console
    # Numa pasta sem permissão de gravação não há registro - e isso não pode
    # derrubar o instalador com erro em inglês: a etapa 1 explica e oferece
    # outra pasta.
    try {
        New-Item -ItemType Directory -Force -Path $Logs | Out-Null
        Start-Transcript -LiteralPath $script:ArquivoLog -Force | Out-Null
        $script:Transcrevendo = $true
    } catch { }
    if ($ModeloAoVivo) {
        $script:Modelo = Nome-DoModelo $ModeloAoVivo
        if (-not $TamanhoModelos.ContainsKey($script:Modelo)) {
            Bloquear ('Modelo desconhecido: ' + $ModeloAoVivo + '.') 'Use -ModeloAoVivo com base, small, medium ou large-v3-turbo.'
        }
    } else {
        $ini = Join-Path $Raiz 'config.ini'
        if (Test-Path -LiteralPath $ini) {
            $configurado = Nome-DoModelo (Ler-ValorDoIni ([IO.File]::ReadAllText($ini, [Text.Encoding]::UTF8)) 'transcricao' 'modelo_ao_vivo')
            if ($TamanhoModelos.ContainsKey($configurado)) { $script:Modelo = $configurado }
        }
    }
    Preparar-Ambiente
    Mostrar-Abertura
    $codigoSaida = Instalar
} catch {
    $codigoSaida = Tratar-Erro $_
} finally {
    if ($script:TravaTomada) { Remove-Item -LiteralPath $Trava -Force -ErrorAction SilentlyContinue }
    if ($script:Transcrevendo) { try { Stop-Transcript | Out-Null } catch { } }
}
exit $codigoSaida
