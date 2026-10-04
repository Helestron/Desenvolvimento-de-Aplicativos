; ============================================================================
;  Helestron - instalador para Windows (NSIS 3, Unicode, MUI2)
;
;  MODELO: construir.py troca os marcadores entre arrobas (versão, pastas, a
;  lista dos arquivos do programa) e roda o makensis. Não rode este arquivo
;  direto.
;
;  O que este instalador garante (os problemas da versão anterior):
;    * um só arquivo .exe, OFFLINE: Python, bibliotecas e o modelo de
;      transcrição vão dentro. Nada de PowerShell, de console ou de
;      administrador - instala por usuário, em %LOCALAPPDATA%\Programs;
;    * antes de copiar, pede ao Helestron aberto que feche (--encerrar) e
;      espera os arquivos ficarem livres; remove o PROGRAMA da versão
;      anterior (nunca os dados do usuário);
;    * no fim, roda "Helestron.exe --verificar-instalacao" (confere o
;      SHA-256 de cada arquivo e importa todos os módulos) e, se algo faltar,
;      diz o que é e onde está o relatório - em vez de o programa quebrar na
;      primeira tela, como o "No module named 'app.interface.pagina_config'";
;    * desinstalador que pergunta antes de apagar configurações e senhas e
;      NUNCA apaga Documentos\Helestron (processos, transcrições, pauta);
;    * modo silencioso para o CI: Helestron-Setup.exe /S [/D=pasta].
;
;  Textos: todos os que o usuário lê são definidos aqui, em português
;  correto - o arquivo de idioma do NSIS usa "pra" e "guiará você através".
; ============================================================================

Unicode true
ManifestDPIAware true
ManifestSupportedOS Win10
RequestExecutionLevel user
SetCompressor /SOLID /FINAL lzma
SetCompressorDictSize 64
SetDatablockOptimize on
CRCCheck force

!define NOME "Helestron"
!define VERSAO "@VERSAO@"
!define CHAVE_DESINSTALAR "Software\Microsoft\Windows\CurrentVersion\Uninstall\Helestron"
!define EXE "Helestron.exe"
!define DESINSTALADOR "Desinstalar.exe"
; o que a conferência final grava (o mesmo arquivo padrão do programa)
!define RELATORIO "$LOCALAPPDATA\Helestron\Logs\verificacao-instalacao.txt"

Name "${NOME}"
Caption "Instalação do ${NOME} ${VERSAO}"
UninstallCaption "Desinstalação do ${NOME}"
BrandingText "${NOME} ${VERSAO}"
OutFile "@SAIDA@"
InstallDir "$LOCALAPPDATA\Programs\Helestron"
; atualização: a mesma pasta da instalação anterior
InstallDirRegKey HKCU "${CHAVE_DESINSTALAR}" "InstallLocation"
ShowInstDetails hide
ShowUninstDetails hide

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

; ------------------------------------------------------------------ visual
!define MUI_ICON "@ICONE@"
!define MUI_UNICON "@ICONE@"
!define MUI_WELCOMEFINISHPAGE_BITMAP "@BOAS_VINDAS@"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "@BOAS_VINDAS@"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "@CABECALHO@"
!define MUI_HEADERIMAGE_UNBITMAP "@CABECALHO@"
!define MUI_BGCOLOR "FFFFFF"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "Deseja mesmo cancelar a instalação do Helestron?"
!define MUI_UNABORTWARNING
!define MUI_UNABORTWARNING_TEXT "Deseja mesmo cancelar a desinstalação do Helestron?"
!define MUI_COMPONENTSPAGE_SMALLDESC

; ------------------------------------------------------------------ páginas
!define MUI_WELCOMEPAGE_TITLE "Bem-vindo ao Helestron"
!define MUI_WELCOMEPAGE_TEXT "Este assistente instala o Helestron ${VERSAO} neste computador.$\r$\n$\r$\nO Helestron baixa processos do e-SAJ e do eProc, transcreve audiências, monitora a pauta de audiências e prepara o acervo para a inteligência artificial.$\r$\n$\r$\nA instalação não precisa de internet nem de administrador. Se o Helestron estiver aberto, ele será fechado; os seus dados são mantidos.$\r$\n$\r$\nClique em Próximo para continuar."
!insertmacro MUI_PAGE_WELCOME

!define MUI_PAGE_HEADER_TEXT "Pasta do programa"
!define MUI_PAGE_HEADER_SUBTEXT "Escolha onde instalar o Helestron."
!define MUI_DIRECTORYPAGE_TEXT_TOP "O Helestron será instalado na pasta abaixo, só para o seu usuário. Para usar outra pasta, clique em Procurar.$\r$\n$\r$\nAs configurações, os processos, as transcrições e a pauta ficam em outras pastas e não são apagados quando o programa é atualizado."
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "Pasta do programa"
!insertmacro MUI_PAGE_DIRECTORY

!define MUI_PAGE_HEADER_TEXT "Opções"
!define MUI_PAGE_HEADER_SUBTEXT "Escolha o que instalar."
!define MUI_COMPONENTSPAGE_TEXT_TOP "O programa é obrigatório. Desmarque o atalho se não quiser o ícone na Área de Trabalho. Clique em Instalar para começar."
!define MUI_COMPONENTSPAGE_TEXT_COMPLIST "Instalar:"
!define MUI_COMPONENTSPAGE_TEXT_DESCRIPTION_TITLE "Descrição"
!define MUI_COMPONENTSPAGE_TEXT_DESCRIPTION_INFO "Passe o mouse sobre um item para ver a descrição."
!insertmacro MUI_PAGE_COMPONENTS

!define MUI_PAGE_HEADER_TEXT "Instalando"
!define MUI_PAGE_HEADER_SUBTEXT "Aguarde: o Helestron está sendo copiado e conferido."
!define MUI_INSTFILESPAGE_FINISHHEADER_TEXT "Instalação concluída"
!define MUI_INSTFILESPAGE_FINISHHEADER_SUBTEXT "O Helestron foi instalado."
!define MUI_INSTFILESPAGE_ABORTHEADER_TEXT "Instalação interrompida"
!define MUI_INSTFILESPAGE_ABORTHEADER_SUBTEXT "O Helestron não foi instalado por completo."
!insertmacro MUI_PAGE_INSTFILES
; o MUI2 esquece de desfazer estes dois (desfaz os ABORTWARNING no lugar)
!undef MUI_INSTFILESPAGE_ABORTHEADER_TEXT
!undef MUI_INSTFILESPAGE_ABORTHEADER_SUBTEXT

!define MUI_FINISHPAGE_TITLE "Pronto!"
!define MUI_FINISHPAGE_TEXT "O Helestron está instalado. Para abri-lo depois, use o atalho no Menu Iniciar ou na Área de Trabalho.$\r$\n$\r$\nNa primeira vez, cadastre o seu acesso ao e-SAJ e ao eProc em Ajustes.$\r$\n$\r$\nClique em Concluir para fechar este assistente."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o Helestron"
!define MUI_FINISHPAGE_RUN_FUNCTION AbrirHelestron
!insertmacro MUI_PAGE_FINISH

!define MUI_PAGE_HEADER_TEXT "Desinstalar o Helestron"
!define MUI_PAGE_HEADER_SUBTEXT "Remover o Helestron deste computador."
!define MUI_UNCONFIRMPAGE_TEXT_TOP "O programa Helestron será removido da pasta abaixo. Os processos, as transcrições e a pauta exportada (pasta Documentos\Helestron) não são apagados. Clique em Desinstalar para continuar."
!define MUI_UNCONFIRMPAGE_TEXT_LOCATION "Pasta do programa:"
!insertmacro MUI_UNPAGE_CONFIRM
!define MUI_PAGE_HEADER_TEXT "Desinstalando"
!define MUI_PAGE_HEADER_SUBTEXT "Aguarde enquanto o Helestron é removido."
!define MUI_INSTFILESPAGE_FINISHHEADER_TEXT "Desinstalação concluída"
!define MUI_INSTFILESPAGE_FINISHHEADER_SUBTEXT "O Helestron foi removido."
!define MUI_INSTFILESPAGE_ABORTHEADER_TEXT "Desinstalação interrompida"
!define MUI_INSTFILESPAGE_ABORTHEADER_SUBTEXT "O Helestron não foi removido por completo."
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "PortugueseBR"

; Textos do arquivo de idioma do NSIS que aparecem nestas páginas.
LangString ^Completed ${LANG_PORTUGUESEBR} "Concluído"
LangString ^ClickNext ${LANG_PORTUGUESEBR} "Clique em Próximo para continuar."
LangString ^ClickInstall ${LANG_PORTUGUESEBR} "Clique em Instalar para começar."
LangString ^ClickUninstall ${LANG_PORTUGUESEBR} "Clique em Desinstalar para começar."
LangString ^SpaceRequired ${LANG_PORTUGUESEBR} "Espaço necessário: "
LangString ^SpaceAvailable ${LANG_PORTUGUESEBR} "Espaço disponível: "
LangString ^CopyDetails ${LANG_PORTUGUESEBR} "Copiar os detalhes para a Área de Transferência"
LangString ^FileError ${LANG_PORTUGUESEBR} "Não foi possível gravar o arquivo:$\r$\n$\r$\n$0$\r$\n$\r$\nFeche o Helestron (e o Claude Desktop, se estiver aberto) e clique em Repetir. Abortar interrompe a instalação; Ignorar pula este arquivo."
LangString ^FileError_NoIgnore ${LANG_PORTUGUESEBR} "Não foi possível gravar o arquivo:$\r$\n$\r$\n$0$\r$\n$\r$\nFeche o Helestron (e o Claude Desktop, se estiver aberto) e clique em Repetir, ou em Cancelar para interromper a instalação."

; Propriedades > Detalhes do Helestron-Setup.exe
VIProductVersion "@VERSAO_WIN@"
VIFileVersion "@VERSAO_WIN@"
VIAddVersionKey /LANG=${LANG_PORTUGUESEBR} "ProductName" "Helestron"
VIAddVersionKey /LANG=${LANG_PORTUGUESEBR} "FileDescription" "Instalador do Helestron"
VIAddVersionKey /LANG=${LANG_PORTUGUESEBR} "CompanyName" "Helestron"
VIAddVersionKey /LANG=${LANG_PORTUGUESEBR} "LegalCopyright" "© @ANO@ Helestron"
VIAddVersionKey /LANG=${LANG_PORTUGUESEBR} "FileVersion" "${VERSAO}"
VIAddVersionKey /LANG=${LANG_PORTUGUESEBR} "ProductVersion" "${VERSAO}"

; ============================================================== utilidades
; Remove os arquivos e pastas do PROGRAMA (a lista vem da construção: o que
; esta versão instala, mais nomes de versões anteriores). Nunca um
; "RMDir /r $INSTDIR": se o usuário tiver escolhido uma pasta com outras
; coisas, elas ficam.
!macro RemoverPrograma
@REMOVER_PROGRAMA@
!macroend

; Espera os arquivos do programa ficarem livres (o Helestron, o servidor MCP
; aberto pelo Claude Desktop ou um python.exe do programa os prendem): tenta
; abrir o python312.dll para gravação por até 20 s; depois, pergunta.
!macro EsperarArquivosLivres UN
Function ${UN}EsperarArquivosLivres
  Push $0
  Push $1
  StrCpy $1 0
  ${DoWhile} ${FileExists} "$INSTDIR\python312.dll"
    ClearErrors
    FileOpen $0 "$INSTDIR\python312.dll" a
    ${IfNot} ${Errors}
      FileClose $0
      ${Break}
    ${EndIf}
    IntOp $1 $1 + 1
    ${If} $1 >= 40
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "O Helestron (ou um programa que o usa, como o Claude Desktop) ainda está aberto e prende os arquivos da instalação.$\r$\n$\r$\nFeche-o e clique em Repetir." /SD IDCANCEL IDRETRY repetir
      SetErrorLevel 4
      Abort "O Helestron continua aberto; feche-o e tente de novo."
      repetir:
      StrCpy $1 0
    ${EndIf}
    Sleep 500
  ${Loop}
  Pop $1
  Pop $0
FunctionEnd
!macroend
!insertmacro EsperarArquivosLivres ""
!insertmacro EsperarArquivosLivres "un."

; Pede à instância aberta que feche (ela salva o que estiver fazendo).
!macro FecharHelestron
  ${If} ${FileExists} "$INSTDIR\${EXE}"
  ${AndIf} ${FileExists} "$INSTDIR\python312.dll"
    DetailPrint "Fechando o Helestron, se estiver aberto..."
    ; sem "Executar: ..." na tela: a frase acima é o que o usuário lê
    SetDetailsPrint none
    ExecWait '"$INSTDIR\${EXE}" --encerrar' $0
    SetDetailsPrint both
  ${EndIf}
!macroend

; ============================================================== instalação
Function .onInit
  ; um instalador por vez
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "HelestronSetup") p .r1 ?e'
  Pop $0
  ${If} $0 = 183
    MessageBox MB_OK|MB_ICONINFORMATION "O instalador do Helestron já está aberto." /SD IDOK
    SetErrorLevel 5
    Abort
  ${EndIf}
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "O Helestron precisa do Windows de 64 bits (Windows 10 ou 11)." /SD IDOK
    SetErrorLevel 6
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "O Helestron precisa do Windows 10 ou do Windows 11." /SD IDOK
    SetErrorLevel 6
    Abort
  ${EndIf}
  SetShellVarContext current
FunctionEnd

Section "Helestron (programa)" SecPrograma
  SectionIn RO
  SetShellVarContext current
  SetDetailsPrint both

  ; 1. fecha o Helestron aberto e espera os arquivos ficarem livres
  !insertmacro FecharHelestron
  Call EsperarArquivosLivres

  ; 2. remove o programa da versão anterior (só o programa; os dados ficam
  ;    em %LOCALAPPDATA%\Helestron e em Documentos\Helestron)
  ${If} ${FileExists} "$INSTDIR\manifesto.json"
  ${OrIf} ${FileExists} "$INSTDIR\${EXE}"
    DetailPrint "Removendo a versão anterior do programa..."
    SetDetailsPrint listonly
    !insertmacro RemoverPrograma
    SetDetailsPrint both
  ${EndIf}

  ; 3. copia o programa
  DetailPrint "Copiando o Helestron..."
  SetDetailsPrint listonly
  SetOutPath "$INSTDIR"
  File /r "@ARVORE@/*"
  SetDetailsPrint both

  WriteUninstaller "$INSTDIR\${DESINSTALADOR}"

  ; 4. Menu Iniciar (direto em Programas, como no Windows 10 e 11)
  SetOutPath "$INSTDIR"
  CreateShortcut "$SMPROGRAMS\Helestron.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0 SW_SHOWNORMAL "" "Baixar processos, transcrever audiências, monitorar a pauta e compartilhar com a IA"

  ; 5. Programas e Recursos / Aplicativos instalados
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "DisplayName" "Helestron"
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "DisplayIcon" "$INSTDIR\${EXE},0"
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "Publisher" "Helestron"
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "UninstallString" '"$INSTDIR\${DESINSTALADOR}"'
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "QuietUninstallString" '"$INSTDIR\${DESINSTALADOR}" /S'
  WriteRegStr HKCU "${CHAVE_DESINSTALAR}" "URLInfoAbout" "@URL_PROJETO@"
  WriteRegDWORD HKCU "${CHAVE_DESINSTALAR}" "EstimatedSize" @TAMANHO_KB@
  WriteRegDWORD HKCU "${CHAVE_DESINSTALAR}" "NoModify" 1
  WriteRegDWORD HKCU "${CHAVE_DESINSTALAR}" "NoRepair" 1
SectionEnd

Section "Atalho na Área de Trabalho" SecAtalho
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  CreateShortcut "$DESKTOP\Helestron.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0 SW_SHOWNORMAL "" "Baixar processos, transcrever audiências, monitorar a pauta e compartilhar com a IA"
SectionEnd

; A conferência final: depois de tudo copiado (as seções acima já rodaram).
Section "-Conferir a instalação" SecConferir
  DetailPrint "Conferindo a instalação (pode levar até um minuto)..."
  ; o relatório de uma instalação anterior não pode passar por este
  Delete "${RELATORIO}"
  ClearErrors
  SetDetailsPrint none
  ExecWait '"$INSTDIR\${EXE}" --verificar-instalacao --relatorio "${RELATORIO}"' $0
  SetDetailsPrint both
  ${If} ${Errors}
  ${OrIf} $0 != 0
    SetErrorLevel 2
    ${If} ${FileExists} "${RELATORIO}"
      DetailPrint "A conferência encontrou problemas (código $0). Relatório: ${RELATORIO}"
      MessageBox MB_YESNO|MB_ICONEXCLAMATION "O Helestron foi copiado, mas a conferência final encontrou problemas na instalação (código $0).$\r$\n$\r$\nO relatório, com o que falta e o que fazer, está em:$\r$\n${RELATORIO}$\r$\n$\r$\nQuase sempre resolve instalar de novo. Se o antivírus tiver posto um arquivo em quarentena, peça ao suporte que libere a pasta do programa:$\r$\n$INSTDIR$\r$\n$\r$\nDeseja abrir o relatório agora?" /SD IDNO IDNO fim
      ExecShell "open" "${RELATORIO}"
    ${Else}
      ; o próprio Python não chegou a rodar (ou caiu antes de gravar o relatório)
      DetailPrint "A conferência não terminou (código $0)."
      MessageBox MB_OK|MB_ICONEXCLAMATION "O Helestron foi copiado, mas a conferência final não conseguiu terminar (código $0).$\r$\n$\r$\nIsso costuma acontecer quando o antivírus bloqueia ou põe em quarentena arquivos do programa. Instale de novo; se o problema continuar, peça ao suporte que libere a pasta do programa:$\r$\n$INSTDIR" /SD IDOK
    ${EndIf}
    fim:
  ${Else}
    DetailPrint "Instalação conferida: tudo certo."
  ${EndIf}
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecPrograma} "O Helestron, com tudo de que precisa: Python, bibliotecas e o modelo de transcrição."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAtalho} "Um atalho do Helestron na Área de Trabalho."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function AbrirHelestron
  ; o instalador roda sem administrador: o programa abre como o próprio usuário
  Exec '"$INSTDIR\${EXE}"'
FunctionEnd

; ============================================================== desinstalação
Function un.onInit
  SetShellVarContext current
FunctionEnd

Section "Uninstall"
  SetShellVarContext current
  SetDetailsPrint both

  !insertmacro FecharHelestron
  Call un.EsperarArquivosLivres

  ; o conector do acervo no Claude Desktop aponta para o python.exe daqui:
  ; sem o programa, ele só daria erro no Claude
  ${If} ${FileExists} "$INSTDIR\python.exe"
    DetailPrint "Removendo o conector do Claude Desktop..."
    nsExec::Exec '"$INSTDIR\python.exe" -I -c "from helestron.compartilhar import claude; claude.remover_mcp()"'
    Pop $0
  ${EndIf}

  DetailPrint "Removendo o programa..."
  SetDetailsPrint listonly
  !insertmacro RemoverPrograma
  Delete "$INSTDIR\${DESINSTALADOR}"
  SetDetailsPrint both
  ; só some se ficou vazia (nada do usuário é apagado aqui)
  RMDir "$INSTDIR"

  Delete "$SMPROGRAMS\Helestron.lnk"
  Delete "$DESKTOP\Helestron.lnk"
  DeleteRegKey HKCU "${CHAVE_DESINSTALAR}"

  ; Configurações e senhas: só com o sim do usuário (no modo silencioso, não).
  ; Documentos\Helestron (processos, transcrições, pauta) nunca é apagado.
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Apagar também as configurações e as senhas guardadas do Helestron?$\r$\n$\r$\nElas ficam em $LOCALAPPDATA\Helestron (configurações, registros, senhas dos portais, perfis do navegador e a pauta monitorada). Se você pretende instalar o Helestron de novo, responda Não.$\r$\n$\r$\nOs processos, as transcrições e a pauta exportada (Documentos\Helestron) não são apagados em nenhum caso." /SD IDNO IDNO manter
    DetailPrint "Apagando as configurações e as senhas..."
    RMDir /r "$LOCALAPPDATA\Helestron"
  manter:
SectionEnd
