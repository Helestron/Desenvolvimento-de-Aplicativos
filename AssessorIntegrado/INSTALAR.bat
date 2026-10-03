@echo off
rem ==========================================================================
rem  Assessor Integrado - instalador
rem
rem  Um duplo clique aqui faz tudo. O trabalho fica com o
rem  instalador\instalar.ps1 (PowerShell); este arquivo apenas:
rem    1. confere se os outros arquivos do programa vieram junto;
rem    2. retira dos scripts a marca de arquivo baixado da internet e
rem       confere se uma regra do setor de TI bloqueia o PowerShell;
rem    3. chama o instalar.ps1 com os mesmos argumentos (ex.: -Silencioso).
rem
rem  Regras deste arquivo: somente ASCII e fim de linha CRLF. Com fim de
rem  linha LF, o cmd.exe erra saltos (goto) em arquivos maiores que 512
rem  bytes; e acentos aqui sairiam trocados na tela. As mensagens com
rem  acento ficam no instalar.ps1.
rem ==========================================================================
setlocal EnableExtensions DisableDelayedExpansion
title Assessor Integrado - Instalador

rem pushd funciona inclusive em pasta de rede (\\servidor\...), onde cd /d falha.
pushd "%~dp0"

set "SILENCIOSO="
for %%A in (%*) do (
    if /i "%%~A"=="-Silencioso" set "SILENCIOSO=1"
    if /i "%%~A"=="/s" set "SILENCIOSO=1"
)

if not exist "%~dp0instalador\instalar.ps1" goto :faltam_arquivos
if not exist "%~dp0app\__main__.py" goto :faltam_arquivos

rem PowerShell de 64 bits mesmo se este cmd for de 32 bits (Sysnative).
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

rem Teste inicial, por comando (que nenhuma regra de scripts bloqueia):
rem   - retira a marca da internet dos .ps1 (com a regra RemoteSigned da TI,
rem     um script marcado seria recusado mesmo com -ExecutionPolicy Bypass);
rem   - 4 = PowerShell em modo restrito (AppLocker ou WDAC);
rem   - 3 = regra da TI (GPO) que vence o -ExecutionPolicy Bypass.
rem Uma aspa simples no nome de alguma pasta quebraria o comando se o
rem caminho fosse escrito dentro dele; por isso ele passa pelo ambiente
rem (ASSESSOR_RAIZ).
set "ASSESSOR_RAIZ=%~dp0"
"%PS%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "try { Get-ChildItem -LiteralPath (Join-Path $env:ASSESSOR_RAIZ 'instalador') -Filter '*.ps1' | Unblock-File } catch { }; if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { exit 4 }; $p = @((Get-ExecutionPolicy -Scope MachinePolicy), (Get-ExecutionPolicy -Scope UserPolicy)); if (($p -contains 'AllSigned') -or ($p -contains 'Restricted')) { exit 3 }; exit 0"
set "TESTE=%ERRORLEVEL%"
if "%TESTE%"=="9009" goto :sem_powershell
if "%TESTE%"=="4" goto :modo_restrito
if "%TESTE%"=="3" goto :politica
if not "%TESTE%"=="0" (
    echo.
    echo   O PowerShell deste computador falhou no teste inicial, erro %TESTE%.
    echo   Mesmo assim, o instalador vai tentar seguir.
    echo.
)

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\instalar.ps1" %*
set "CODIGO=%ERRORLEVEL%"

rem 0, 10 e 11: o instalar.ps1 mostrou o resultado e esperou o Enter.
rem Outros valores indicam erro do PowerShell antes do script (mensagem
rem acima), por isso a pausa.
if "%CODIGO%"=="0" goto :fim
if "%CODIGO%"=="10" goto :fim
if "%CODIGO%"=="11" goto :fim
goto :pausar

:faltam_arquivos
echo.
echo   Faltam arquivos do programa ao lado deste INSTALAR.bat.
echo.
echo   Isso acontece ao abrir o INSTALAR.bat de dentro do arquivo ZIP,
echo   sem extrair. Clique no arquivo ZIP com o lado direito do mouse,
echo   escolha "Extrair Tudo" e, na pasta nova, abra o INSTALAR.bat.
echo.
set "CODIGO=11"
goto :pausar

:sem_powershell
echo.
echo   O Windows PowerShell, de que o instalador precisa, falta neste
echo   computador ou foi bloqueado pelo setor de TI.
echo.
echo   Fale com o suporte de TI e mostre esta mensagem.
echo.
set "CODIGO=11"
goto :pausar

:modo_restrito
echo.
echo   O PowerShell deste computador funciona em modo restrito
echo   (ConstrainedLanguage), por uma regra do setor de TI, e o
echo   instalador precisa do modo completo.
echo.
echo   Fale com o suporte de TI e mostre esta mensagem.
echo   Detalhe para o suporte: AppLocker ou WDAC ativo para o PowerShell.
echo.
set "CODIGO=11"
goto :pausar

:politica
echo.
echo   O PowerShell deste computador foi impedido de executar scripts
echo   por uma regra do setor de TI, e o instalador precisa disso.
echo.
echo   Fale com o suporte de TI e mostre esta mensagem. Eles podem
echo   liberar o arquivo instalador\instalar.ps1 desta pasta.
echo.
echo   Detalhe para o suporte: ExecutionPolicy definida por GPO
echo   (MachinePolicy ou UserPolicy) como AllSigned ou Restricted.
echo.
set "CODIGO=11"
goto :pausar

:pausar
if not defined SILENCIOSO pause

:fim
popd
endlocal & exit /b %CODIGO%
