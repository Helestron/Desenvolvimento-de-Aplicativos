@echo off
rem ==========================================================================
rem  Assessor Integrado - abre o programa (sem janela preta).
rem  Os atalhos criados pelo instalador fazem o mesmo.
rem
rem  -E e -s: o Python do programa ignora PYTHONHOME e PYTHONPATH deixados
rem  por outros programas e os pacotes instalados para outro Python neste
rem  computador, e abre sempre com as bibliotecas instaladas nesta pasta.
rem
rem  Somente ASCII e fim de linha CRLF (ver INSTALAR.bat).
rem ==========================================================================
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0"

if not exist "%~dp0iniciar.pyw" goto :faltam_arquivos
if not exist "%~dp0runtime\python\pythonw.exe" goto :nao_instalado

start "" "%~dp0runtime\python\pythonw.exe" -E -s "%~dp0iniciar.pyw"
popd
endlocal & exit /b 0

:nao_instalado
echo.
echo   Primeiro instale o programa: abra o arquivo INSTALAR.bat
echo   desta pasta (duplo clique) e aguarde a mensagem final.
echo.
pause
popd
endlocal & exit /b 1

:faltam_arquivos
echo.
echo   Faltam arquivos do programa nesta pasta. Extraia de novo o
echo   arquivo ZIP inteiro: clique nele com o lado direito do mouse e
echo   escolha "Extrair Tudo".
echo.
pause
popd
endlocal & exit /b 1
