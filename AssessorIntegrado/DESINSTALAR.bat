@echo off
rem ==========================================================================
rem  Assessor Integrado - desinstalador
rem
rem  Chama o instalador\desinstalar.ps1, que remove atalhos, conectores e a
rem  pasta runtime, e pergunta antes de apagar os processos baixados e as
rem  senhas guardadas. Argumentos: -Silencioso (sem perguntas, e os dados
rem  ficam) e -ApagarDados.
rem
rem  Somente ASCII e fim de linha CRLF (ver INSTALAR.bat).
rem ==========================================================================
setlocal EnableExtensions DisableDelayedExpansion
title Assessor Integrado - Desinstalador
pushd "%~dp0"

set "SILENCIOSO="
for %%A in (%*) do (
    if /i "%%~A"=="-Silencioso" set "SILENCIOSO=1"
    if /i "%%~A"=="/s" set "SILENCIOSO=1"
)

if not exist "%~dp0instalador\desinstalar.ps1" goto :faltam_arquivos

set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

rem Mesmo teste inicial do INSTALAR.bat: tira a marca da internet dos .ps1
rem e confere se uma regra do setor de TI impede o PowerShell de rodar
rem scripts (3) ou o deixa em modo restrito (4).
set "ASSESSOR_RAIZ=%~dp0"
"%PS%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "try { Get-ChildItem -LiteralPath (Join-Path $env:ASSESSOR_RAIZ 'instalador') -Filter '*.ps1' | Unblock-File } catch { }; if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { exit 4 }; $p = @((Get-ExecutionPolicy -Scope MachinePolicy), (Get-ExecutionPolicy -Scope UserPolicy)); if (($p -contains 'AllSigned') -or ($p -contains 'Restricted')) { exit 3 }; exit 0" >nul 2>&1
set "TESTE=%ERRORLEVEL%"
if "%TESTE%"=="3" goto :bloqueado
if "%TESTE%"=="4" goto :bloqueado

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\desinstalar.ps1" %*
set "CODIGO=%ERRORLEVEL%"

rem 0, 10 e 11: o desinstalar.ps1 mostrou o resultado e esperou o Enter.
if "%CODIGO%"=="0" goto :fim
if "%CODIGO%"=="10" goto :fim
if "%CODIGO%"=="11" goto :fim
goto :pausar

:faltam_arquivos
echo.
echo   Faltam arquivos do programa ao lado deste DESINSTALAR.bat.
echo   Para remover o programa, apague a pasta inteira e os atalhos
echo   com o nome Assessor Integrado.
echo.
set "CODIGO=11"
goto :pausar

:bloqueado
echo.
echo   Uma regra do setor de TI impede o PowerShell deste computador de
echo   rodar o desinstalador. Para remover o programa sem ele: apague os
echo   atalhos Assessor Integrado da Area de Trabalho e do Menu Iniciar e,
echo   depois, a pasta inteira do programa (antes, copie para outro lugar
echo   a pasta Acervo, se quiser guardar os processos e as transcricoes).
echo.
set "CODIGO=11"

:pausar
if not defined SILENCIOSO pause

:fim
popd
endlocal & exit /b %CODIGO%
