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
;      anterior (nunca os dados do usuário). Com uma audiência sendo
;      transcrita, o --encerrar recusa (código 10): o instalador pede que
;      ela seja encerrada antes e, no modo silencioso, desiste (código 7) -
;      a atualização fica para depois, a transcrição não é cortada;
;    * o servidor MCP do acervo, que o Claude Desktop (ou o Codex) mantém
;      aberto com o python.exe daqui, prende arquivos do programa: eles são
;      RENOMEADOS para $INSTDIR\.antigos (o Windows deixa renomear um
;      programa em uso, não apagar) e apagados depois - no próximo logon
;      (RunOnce) ou na próxima abertura do Helestron. Nenhum processo é
;      encerrado: o Claude reabre o conector, já com a versão nova;
;    * a pasta escolhida é conferida (dá para gravar nela?) antes de copiar;
;    * no fim, roda "Helestron.exe --verificar-instalacao" (confere o
;      SHA-256 de cada arquivo e importa todos os módulos) e, se algo faltar,
;      diz o que é e onde está o relatório - em vez de o programa quebrar na
;      primeira tela, como o "No module named 'app.interface.pagina_config'";
;    * desinstalador que pergunta antes de apagar configurações e senhas e
;      NUNCA apaga Documentos\Helestron (processos, transcrições, pauta);
;    * modo silencioso para o CI: Helestron-Setup.exe /S [/D=pasta].
;
;  Códigos de saída: 0 = instalado; 2 = a conferência final encontrou
;  problemas; 4 = o Helestron (ou o que prende os arquivos) continuou
;  aberto; 5 = outro instalador aberto; 6 = Windows não suportado;
;  7 = audiência sendo transcrita no Helestron (rode de novo depois);
;  8 = sem permissão para gravar na pasta escolhida; 9 = instalado, mas o
;  computador não tem como abrir a janela (falta o WebView2 Runtime).
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
; o --encerrar com uma audiência sendo transcrita (aplicativo/instancia.py)
!define AUDIENCIA_EM_ANDAMENTO 10
; o --verificar-instalacao sem como abrir a janela (aplicativo/verificacao.py)
!define SEM_JANELA 9
!define PASTA_ANTIGOS "$INSTDIR\.antigos"
!define CHAVE_RUNONCE "Software\Microsoft\Windows\CurrentVersion\RunOnce"
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
!include "FileFunc.nsh"

Var Encerrou        ; 1 = o --encerrar fechou o Helestron (ou não havia nenhum aberto)
Var Afastar         ; 1 = arquivos presos por outro processo do programa: renomear
Var PastaAfastados  ; ${PASTA_ANTIGOS}\<instante>
Var NumAfastados

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
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE ConferirPasta
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

; Textos do arquivo de idioma do NSIS que aparecem nestas páginas. Os botões
; das caixas de mensagem vêm do Windows, no idioma dele: em português do Brasil,
; MB_ABORTRETRYIGNORE mostra Anular, Repetir e Ignorar (o Wine, o ReactOS e o
; PortugueseBR.nlf dizem “Abortar”, que não existe na tela), e MB_RETRYCANCEL
; mostra Repetir e Cancelar.
LangString ^Completed ${LANG_PORTUGUESEBR} "Concluído"
LangString ^ClickNext ${LANG_PORTUGUESEBR} "Clique em Próximo para continuar."
LangString ^ClickInstall ${LANG_PORTUGUESEBR} "Clique em Instalar para começar."
LangString ^ClickUninstall ${LANG_PORTUGUESEBR} "Clique em Desinstalar para começar."
LangString ^SpaceRequired ${LANG_PORTUGUESEBR} "Espaço necessário: "
LangString ^SpaceAvailable ${LANG_PORTUGUESEBR} "Espaço disponível: "
LangString ^CopyDetails ${LANG_PORTUGUESEBR} "Copiar os detalhes para a Área de Transferência"
LangString ^FileError ${LANG_PORTUGUESEBR} "Não foi possível gravar o arquivo:$\r$\n$\r$\n$0$\r$\n$\r$\nSe o Helestron (ou o Claude Desktop) estiver aberto, feche-o e clique em Repetir. Se a pasta escolhida exigir administrador, clique em Anular e instale na pasta sugerida. Ignorar pula este arquivo."
LangString ^FileError_NoIgnore ${LANG_PORTUGUESEBR} "Não foi possível gravar o arquivo:$\r$\n$\r$\n$0$\r$\n$\r$\nSe o Helestron (ou o Claude Desktop) estiver aberto, feche-o e clique em Repetir. Se a pasta escolhida exigir administrador, clique em Cancelar e instale na pasta sugerida."

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

; Os arquivos que o RemoverPrograma não conseguiu apagar (presos por um
; processo do programa: o servidor MCP do Claude Desktop) - renomeados para
; ${PASTA_ANTIGOS}. A lista vem da construção, como a do RemoverPrograma.
!macro AfastarPasta UN NOME
  ${If} ${FileExists} "$INSTDIR\${NOME}\*.*"
    ${Locate} "$INSTDIR\${NOME}" "/L=F /M=*.*" "${UN}AfastarUm"
    RMDir /r "$INSTDIR\${NOME}"
  ${EndIf}
!macroend
!macro AfastarArquivo UN NOME
  ${If} ${FileExists} "$INSTDIR\${NOME}"
    StrCpy $R9 "$INSTDIR\${NOME}"
    StrCpy $R7 "${NOME}"
    Call ${UN}AfastarUm
    Pop $R9
  ${EndIf}
!macroend

!macro FuncoesDeArquivos UN
; Pede à instância aberta que feche (ela salva o que estiver fazendo). Com
; uma audiência sendo transcrita, o --encerrar recusa e nada é fechado:
; aqui se pede que a audiência seja encerrada antes (no silencioso, desiste).
Function ${UN}FecharHelestron
  Push $0
  StrCpy $Encerrou 1
  ${If} ${FileExists} "$INSTDIR\${EXE}"
  ${AndIf} ${FileExists} "$INSTDIR\python312.dll"
    DetailPrint "Fechando o Helestron, se estiver aberto..."
    tentar:
    ; sem "Executar: ..." na tela: a frase acima é o que o usuário lê
    SetDetailsPrint none
    ClearErrors
    StrCpy $0 ""
    ExecWait '"$INSTDIR\${EXE}" --encerrar' $0
    SetDetailsPrint both
    ${If} ${Errors}
      StrCpy $Encerrou 0
    ${ElseIf} $0 == ${AUDIENCIA_EM_ANDAMENTO}
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Há uma audiência sendo transcrita no Helestron.$\r$\n$\r$\nPara não interromper a transcrição, encerre a audiência no Helestron (botão Encerrar: o documento é salvo) e clique em Repetir.$\r$\n$\r$\nCancelar deixa para depois: nada é alterado agora." /SD IDCANCEL IDRETRY tentar
      SetErrorLevel 7
      Abort "Há uma audiência sendo transcrita no Helestron: encerre-a e tente de novo."
    ${ElseIf} $0 != 0
      StrCpy $Encerrou 0
    ${EndIf}
  ${EndIf}
  Pop $0
FunctionEnd

; Espera os arquivos do programa ficarem livres: tenta abrir o python312.dll
; para gravação. Se o Helestron fechou e outro processo do programa ainda os
; prende (o servidor MCP aberto pelo Claude Desktop ou pelo Codex), depois de
; 10 s marca $Afastar - os arquivos presos serão renomeados (LiberarArquivos,
; AfastarPresos). Se o próprio Helestron não fechou, espera 20 s e pergunta.
Function ${UN}EsperarArquivosLivres
  Push $0
  Push $1
  StrCpy $Afastar 0
  StrCpy $1 0
  ${DoWhile} ${FileExists} "$INSTDIR\python312.dll"
    ClearErrors
    FileOpen $0 "$INSTDIR\python312.dll" a
    ${IfNot} ${Errors}
      FileClose $0
      ${Break}
    ${EndIf}
    IntOp $1 $1 + 1
    ${If} $Encerrou == 1
    ${AndIf} $1 >= 20
      StrCpy $Afastar 1
      ${Break}
    ${EndIf}
    ${If} $1 >= 40
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "O Helestron ainda está aberto e prende os arquivos da instalação.$\r$\n$\r$\nFeche-o e clique em Repetir." /SD IDCANCEL IDRETRY repetir
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

; Antes de remover: com $Afastar, renomeia o python312.dll preso. Se nem isso
; for possível, volta ao caminho de sempre (esperar e perguntar) - nada foi
; apagado ainda.
Function ${UN}LiberarArquivos
  Push $0
  ${If} $Afastar == 1
    System::Call 'kernel32::GetTickCount() i .r0'
    StrCpy $PastaAfastados "${PASTA_ANTIGOS}\$0"
    StrCpy $NumAfastados 0
    CreateDirectory "$PastaAfastados"
    ClearErrors
    Rename "$INSTDIR\python312.dll" "$PastaAfastados\python312.dll"
    ${If} ${Errors}
      StrCpy $Afastar 0
      StrCpy $Encerrou 0
      Call ${UN}EsperarArquivosLivres
    ${Else}
      DetailPrint "Arquivos do programa em uso pelo conector do acervo (aberto pelo Claude Desktop ou pelo Codex): renomeados para ${PASTA_ANTIGOS} e apagados depois."
    ${EndIf}
  ${EndIf}
  Pop $0
FunctionEnd

; Um arquivo que sobrou depois do RemoverPrograma ($R9 = caminho, $R7 = nome):
; apaga ou, preso, renomeia para $PastaAfastados. Chamado pelo ${Locate}.
Function ${UN}AfastarUm
  ClearErrors
  Delete "$R9"
  ${If} ${Errors}
    IntOp $NumAfastados $NumAfastados + 1
    ClearErrors
    Rename "$R9" "$PastaAfastados\$NumAfastados-$R7"
    ${If} ${Errors}
      DetailPrint "Não foi possível apagar nem renomear: $R9"
    ${EndIf}
  ${EndIf}
  ClearErrors
  Push "continuar"
FunctionEnd

Function ${UN}AfastarPresos
  ${If} $Afastar == 1
    Push $R7
    Push $R9
    !insertmacro AfastarLista "${UN}"
    Pop $R9
    Pop $R7
  ${EndIf}
FunctionEnd

; O que ficou em ${PASTA_ANTIGOS} (ainda em uso) some no próximo logon, sem
; console e sem administrador; o Helestron também apaga ao abrir.
Function ${UN}AgendarLimpeza
  RMDir /r "${PASTA_ANTIGOS}"
  ${If} ${FileExists} "${PASTA_ANTIGOS}\*.*"
    WriteRegStr HKCU "${CHAVE_RUNONCE}" "HelestronLimpeza" '"$SYSDIR\rundll32.exe" advpack.dll,DelNodeRunDLL32 "${PASTA_ANTIGOS}"'
  ${EndIf}
FunctionEnd

!macroend

!macro AfastarLista UN
@AFASTAR_PRESOS@
!macroend

!insertmacro FuncoesDeArquivos ""
!insertmacro FuncoesDeArquivos "un."

; Dá para gravar na pasta escolhida? Empurra "ok" ou "erro".
Function PodeGravarNaPasta
  Push $0
  Push $1
  StrCpy $1 ""
  ${IfNot} ${FileExists} "$INSTDIR\*.*"
    ClearErrors
    CreateDirectory "$INSTDIR"
    StrCpy $1 "criada"
  ${EndIf}
  ClearErrors
  FileOpen $0 "$INSTDIR\.helestron-teste.tmp" w
  ${If} ${Errors}
    StrCpy $0 "erro"
  ${Else}
    FileClose $0
    Delete "$INSTDIR\.helestron-teste.tmp"
    StrCpy $0 "ok"
  ${EndIf}
  ${If} $1 == "criada"
    RMDir "$INSTDIR"
  ${EndIf}
  Pop $1
  Exch $0
FunctionEnd

; A página da pasta: só segue com uma pasta em que dê para gravar (o
; instalador roda sem administrador; C:\Program Files não serve).
Function ConferirPasta
  Call PodeGravarNaPasta
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Não há permissão para gravar na pasta:$\r$\n$INSTDIR$\r$\n$\r$\nEscolha uma pasta do seu usuário. A pasta sugerida ($LOCALAPPDATA\Programs\Helestron) não precisa de administrador."
    Abort
  ${EndIf}
FunctionEnd

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

  ; 0. dá para gravar na pasta? (no modo silencioso, /D=, não há a página)
  Call PodeGravarNaPasta
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_OK|MB_ICONSTOP "Não há permissão para gravar na pasta:$\r$\n$INSTDIR$\r$\n$\r$\nInstale numa pasta do seu usuário. A pasta sugerida ($LOCALAPPDATA\Programs\Helestron) não precisa de administrador." /SD IDOK
    SetErrorLevel 8
    Abort "Sem permissão para gravar em $INSTDIR."
  ${EndIf}

  ; 1. fecha o Helestron aberto e espera os arquivos ficarem livres
  Call FecharHelestron
  Call EsperarArquivosLivres

  ; 2. remove o programa da versão anterior (só o programa; os dados ficam
  ;    em %LOCALAPPDATA%\Helestron e em Documentos\Helestron). Restos de uma
  ;    atualização anterior que já não estão em uso saem antes.
  RMDir /r "${PASTA_ANTIGOS}"
  ${If} ${FileExists} "$INSTDIR\manifesto.json"
  ${OrIf} ${FileExists} "$INSTDIR\${EXE}"
    Call LiberarArquivos
    DetailPrint "Removendo a versão anterior do programa..."
    SetDetailsPrint listonly
    !insertmacro RemoverPrograma
    Call AfastarPresos
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

  Call AgendarLimpeza
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
  StrCpy $0 ""
  ExecWait '"$INSTDIR\${EXE}" --verificar-instalacao --relatorio "${RELATORIO}"' $0
  SetDetailsPrint both
  ${If} ${Errors}
    StrCpy $0 "?"
  ${EndIf}
  ${If} $0 == ${SEM_JANELA}
    ; os arquivos estão certos, mas sem WebView2, sem Edge e com o Internet
    ; Explorer de navegador padrão a janela não tem como abrir
    SetErrorLevel 9
    DetailPrint "Falta o Microsoft Edge WebView2 Runtime para abrir a janela do Helestron."
    MessageBox MB_OK|MB_ICONEXCLAMATION "O Helestron foi instalado, mas este computador não tem como abrir a janela dele: falta o Microsoft Edge WebView2 Runtime (e o Microsoft Edge), e o Internet Explorer não é compatível.$\r$\n$\r$\nPeça ao suporte de informática que instale o “Microsoft Edge WebView2 Runtime” (gratuito, da Microsoft; não precisa de administrador) e depois abra o Helestron.$\r$\n$\r$\nO relatório está em:$\r$\n${RELATORIO}" /SD IDOK
  ${ElseIf} $0 != 0
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

  Call un.FecharHelestron
  Call un.EsperarArquivosLivres

  ; os conectores do acervo no Claude Desktop e no Codex/ChatGPT Work
  ; (%USERPROFILE%\.codex\config.toml) apontam para o python.exe daqui: sem
  ; o programa, eles só dariam erro. Um de cada vez: a falha de um não
  ; impede o outro.
  ${If} ${FileExists} "$INSTDIR\python.exe"
    DetailPrint "Removendo os conectores do Claude Desktop e do Codex/ChatGPT Work..."
    nsExec::Exec '"$INSTDIR\python.exe" -I -c "from helestron.compartilhar import claude; claude.remover_mcp()"'
    Pop $0
    nsExec::Exec '"$INSTDIR\python.exe" -I -c "from helestron.compartilhar import chatgpt; chatgpt.remover_mcp_codex()"'
    Pop $0
  ${EndIf}

  DetailPrint "Removendo o programa..."
  SetDetailsPrint listonly
  RMDir /r "${PASTA_ANTIGOS}"
  Call un.LiberarArquivos
  !insertmacro RemoverPrograma
  Call un.AfastarPresos
  Delete "$INSTDIR\${DESINSTALADOR}"
  SetDetailsPrint both
  Call un.AgendarLimpeza
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
