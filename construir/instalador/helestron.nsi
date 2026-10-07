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
;    * a pasta escolhida é conferida antes de copiar: dá para gravar nela? E
;      ela já tem coisas de outro programa (ou do usuário)? Nesse caso o
;      Helestron vai para uma pasta própria dentro dela, <pasta>\Helestron,
;      e nada se mistura;
;    * instalado em OUTRA pasta (o /D= ou o Procurar escolheram outra que não
;      a da instalação registrada), o Helestron de lá é fechado e o programa
;      dele sai, como numa atualização: nada fica aberto nem órfão (sem
;      entrada em Aplicativos, com um desinstalador que apagaria a chave e os
;      atalhos desta). E o desinstalador de uma cópia que não é a registrada
;      não mexe na chave, nos atalhos nem nos conectores da registrada;
;    * HKCU\Software\Helestron diz onde está o programa ("InstallLocation"),
;      o Python dele ("Python") e a versão ("Versao"), e a pasta tem o
;      helestron.cmd ("python.exe -I -m helestron ..."): quem chama o
;      Helestron de fora (a skill do Claude, scripts da TI) o acha sem
;      depender do PATH, que o instalador não altera;
;    * a atualização e a desinstalação apagam SÓ os arquivos que a instalação
;      pôs na pasta, um a um, pela lista gravada nela (arquivos-instalados.txt)
;      - nunca uma pasta inteira: o que o usuário tiver posto lá fica;
;    * para quem usava o Assessor Integrado (a versão anterior), tira o atalho
;      antigo da Área de Trabalho e do Menu Iniciar e os conectores antigos do
;      Claude Desktop e do Codex;
;    * no fim, roda "Helestron.exe --verificar-instalacao" (confere o
;      SHA-256 de cada arquivo e importa todos os módulos) e, se algo faltar,
;      diz o que é e onde está o relatório - em vez de o programa quebrar na
;      primeira tela, como o "No module named 'app.interface.pagina_config'";
;    * desinstalador que apaga sempre as sessões dos portais e os perfis do
;      navegador (%LOCALAPPDATA%\Helestron\perfis: não são configuração, e
;      nas instalações antigas guardavam cópia do perfil do Chrome, com
;      senhas e cookies), pergunta antes de apagar configurações e senhas e
;      NUNCA apaga Documentos\Helestron (processos, transcrições, pauta);
;    * modo silencioso para o CI: Helestron-Setup.exe /S [/D=pasta].
;
;  Códigos de saída: 0 = instalado; 2 = a conferência final encontrou
;  problemas; 3 = a pasta escolhida (e a subpasta Helestron dentro dela) já
;  tem coisas de outro programa ou do usuário: nada foi copiado; 4 = o
;  Helestron (ou o que prende os arquivos) continuou aberto; 5 = outro
;  instalador aberto; 6 = Windows não suportado;
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
; onde está o programa, para quem o chama de fora (Python, Versao, InstallLocation)
!define CHAVE_PROGRAMA "Software\Helestron"
!define EXE "Helestron.exe"
!define DESINSTALADOR "Desinstalar.exe"
; o --encerrar com uma audiência sendo transcrita (aplicativo/instancia.py)
!define AUDIENCIA_EM_ANDAMENTO 10
; o --verificar-instalacao sem como abrir a janela (aplicativo/verificacao.py)
!define SEM_JANELA 9
!define PASTA_ANTIGOS "$INSTDIR\.antigos"
!define CHAVE_RUNONCE "Software\Microsoft\Windows\CurrentVersion\RunOnce"
; a limpeza de <pasta>\.antigos no próximo logon (sem console nem administrador)
!define LIMPEZA_ANTIGOS '"$SYSDIR\rundll32.exe" advpack.dll,DelNodeRunDLL32'
; A lista do que a instalação pôs na pasta (construir.gerar_registro): uma
; linha por item, "A <arquivo>" ou "P <pasta>", em UTF-16, depois do
; cabeçalho "Helestron <versão> ...". A atualização e o desinstalador apagam
; só o que está nela.
!define REGISTRO "arquivos-instalados.txt"
; o código de saída da pasta recusada (com coisas de outro programa ou do usuário)
!define PASTA_OCUPADA 3
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
Var PastaEscolhida  ; a pasta que o usuário (ou o /D=) escolheu, antes da conferência
Var EraDoHelestron  ; 1 = a pasta já tinha uma instalação do Helestron (atualização)
Var Registrada      ; a pasta da instalação registrada (InstallLocation), se for OUTRA e tiver o Helestron
Var PastaNova       ; $INSTDIR guardado enquanto a instalação de outra pasta é removida

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
; Com a caixa "Abrir o Helestron", o MUI2 dá ao texto 40 unidades de altura
; (5 linhas) e corta o que passar; com TEXT_LARGE, 60 (7,5 linhas). As
; unidades acompanham a fonte: a conta vale em 100 % e em 125 %. O texto
; ocupa 5 a 6 linhas (sem o "Clique em Concluir...", que só repetia o botão).
!define MUI_FINISHPAGE_TEXT_LARGE
!define MUI_FINISHPAGE_TEXT "O Helestron está instalado. Para abri-lo depois, use o atalho no Menu Iniciar ou na Área de Trabalho.$\r$\n$\r$\nNa primeira vez, cadastre o seu acesso ao e-SAJ e ao eProc em Ajustes."
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
; A lista desta versão (a mesma que vai para $INSTDIR\${REGISTRO}), para a
; instalação anterior que não tem a dela.
!macro ExtrairRegistro DESTINO
  File "/oname=${DESTINO}" "@REGISTRO@"
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
; RemoverArquivo). Se o próprio Helestron não fechou, espera 20 s e pergunta.
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

; Apaga um arquivo do programa ($R9 = caminho). Preso por um processo do
; programa (o servidor MCP do Claude Desktop) e com $Afastar, renomeia-o para
; $PastaAfastados (o Windows deixa renomear um arquivo em uso, não apagar).
Function ${UN}RemoverArquivo
  Push $R7
  ClearErrors
  Delete "$R9"
  ${If} ${Errors}
  ${AndIf} $Afastar == 1
  ${AndIf} ${FileExists} "$R9"
    ${GetFileName} "$R9" $R7
    IntOp $NumAfastados $NumAfastados + 1
    ClearErrors
    Rename "$R9" "$PastaAfastados\$NumAfastados-$R7"
    ${If} ${Errors}
      DetailPrint "Não foi possível apagar nem renomear: $R9"
    ${EndIf}
  ${EndIf}
  ClearErrors
  Pop $R7
FunctionEnd

; Remove o PROGRAMA: os arquivos e as pastas que a instalação pôs aqui, um a
; um, pela lista dela ($INSTDIR\${REGISTRO}); sem a lista (uma instalação de
; antes dela), pela lista desta versão. Nunca uma pasta inteira: o que não
; estiver na lista (do usuário, de outro programa) fica, e uma pasta só sai
; se ficar vazia - menos as __pycache__ do programa, onde só o Python grava.
Function ${UN}RemoverPrograma
  Push $0
  Push $1
  Push $2
  Push $3
  Push $R9
  ${If} ${FileExists} "$INSTDIR\${REGISTRO}"
    StrCpy $3 "$INSTDIR\${REGISTRO}"
  ${Else}
    InitPluginsDir
    !insertmacro ExtrairRegistro "$PLUGINSDIR\${REGISTRO}"
    StrCpy $3 "$PLUGINSDIR\${REGISTRO}"
  ${EndIf}
  ClearErrors
  FileOpen $0 "$3" r
  ${IfNot} ${Errors}
    FileReadUTF16LE $0 $1         ; o cabeçalho
    ${Do}
      ClearErrors
      FileReadUTF16LE $0 $1
      ${If} ${Errors}
        ${Break}
      ${EndIf}
      ; sem a quebra de linha do fim
      StrCpy $2 $1 1 -1
      ${If} $2 == "$\n"
        StrCpy $1 $1 -1
      ${EndIf}
      StrCpy $2 $1 1 -1
      ${If} $2 == "$\r"
        StrCpy $1 $1 -1
      ${EndIf}
      StrCpy $2 $1 2
      StrCpy $1 $1 "" 2
      ${If} $1 == ""
        ${Continue}
      ${EndIf}
      ${If} $2 == "A "
        ; a própria lista sai por último, depois de lida
        ${If} $1 != "${REGISTRO}"
          StrCpy $R9 "$INSTDIR\$1"
          Call ${UN}RemoverArquivo
        ${EndIf}
      ${ElseIf} $2 == "P "
        StrCpy $2 $1 "" -12
        ${If} $2 == "\__pycache__"
          RMDir /r "$INSTDIR\$1"
        ${Else}
          RMDir "$INSTDIR\$1"
        ${EndIf}
      ${EndIf}
    ${Loop}
    FileClose $0
  ${EndIf}
  StrCpy $R9 "$INSTDIR\${REGISTRO}"
  Call ${UN}RemoverArquivo
  ClearErrors
  Pop $R9
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

; O que ficou em ${PASTA_ANTIGOS} (ainda em uso) some no próximo logon, sem
; console e sem administrador; o Helestron também apaga ao abrir.
Function ${UN}AgendarLimpeza
  RMDir /r "${PASTA_ANTIGOS}"
  ${If} ${FileExists} "${PASTA_ANTIGOS}\*.*"
    WriteRegStr HKCU "${CHAVE_RUNONCE}" "HelestronLimpeza" '${LIMPEZA_ANTIGOS} "${PASTA_ANTIGOS}"'
  ${EndIf}
FunctionEnd

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

!macro FuncoesDeInstalacoes UN
; A pasta $R0 tem uma instalação do Helestron? A lista dela (o cabeçalho
; "Helestron <versão> ...") ou o manifesto.json do Helestron (o de uma
; instalação de antes da lista: {"nome": "Helestron", ...}). Empurra 1 ou 0.
Function ${UN}EhDoHelestron
  Exch $R0
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  Push $R5
  StrCpy $R3 0
  ClearErrors
  FileOpen $R1 "$R0\${REGISTRO}" r
  ${IfNot} ${Errors}
    FileReadUTF16LE $R1 $R2
    FileClose $R1
    StrCpy $R2 $R2 10
    ${If} $R2 S== "Helestron "
      StrCpy $R3 1
    ${EndIf}
  ${EndIf}
  ClearErrors
  ${If} $R3 == 0
    FileOpen $R1 "$R0\manifesto.json" r
    ${IfNot} ${Errors}
      ${For} $R4 1 4
        ClearErrors
        FileRead $R1 $R2
        ${If} ${Errors}
          ${Break}
        ${EndIf}
        ; sem o recuo
        ${Do}
          StrCpy $R5 $R2 1
          ${If} $R5 != " "
          ${AndIf} $R5 != "$\t"
            ${Break}
          ${EndIf}
          StrCpy $R2 $R2 "" 1
        ${Loop}
        StrCpy $R2 $R2 19
        ${If} $R2 S== '"nome": "Helestron"'
          StrCpy $R3 1
          ${Break}
        ${EndIf}
      ${Next}
      FileClose $R1
    ${EndIf}
  ${EndIf}
  ClearErrors
  StrCpy $R0 $R3
  Pop $R5
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
  Exch $R0
FunctionEnd

; A instalação registrada (o InstallLocation da chave de desinstalação) está
; em OUTRA pasta que não $INSTDIR e ainda tem o Helestron? Empurra essa pasta,
; ou "" (nenhuma registrada, a registrada é $INSTDIR, ou a pasta registrada
; já não tem o Helestron - apagada à mão). Sem diferença de maiúsculas e de
; minúsculas (o == do NSIS) nem da barra do fim.
Function ${UN}OutraInstalacao
  Push $R0
  Push $R1
  Push $R2
  ClearErrors
  ReadRegStr $R0 HKCU "${CHAVE_DESINSTALAR}" "InstallLocation"
  StrCpy $R1 $R0 1 -1
  ${If} $R1 == "\"
    StrCpy $R0 $R0 -1          ; C:\ -> C:
  ${EndIf}
  StrCpy $R2 $INSTDIR
  StrCpy $R1 $R2 1 -1
  ${If} $R1 == "\"
    StrCpy $R2 $R2 -1
  ${EndIf}
  ${If} $R0 == $R2
    StrCpy $R0 ""
  ${ElseIf} $R0 != ""
    Push $R0
    Call ${UN}EhDoHelestron
    Pop $R1
    ${If} $R1 != 1
      StrCpy $R0 ""
    ${EndIf}
  ${EndIf}
  ClearErrors
  Pop $R2
  Pop $R1
  Exch $R0
FunctionEnd
!macroend

!insertmacro FuncoesDeInstalacoes ""
!insertmacro FuncoesDeInstalacoes "un."

; A pasta $R0 não existe ou está vazia? Empurra 1 ou 0. A .antigos que a
; limpeza agendada pelo Helestron vai apagar (o RunOnce desta pasta: uma
; desinstalação com o conector do acervo aberto) não conta.
Function PastaVazia
  Exch $R0
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  StrCpy $R3 1
  ReadRegStr $R4 HKCU "${CHAVE_RUNONCE}" "HelestronLimpeza"
  ClearErrors
  FindFirst $R1 $R2 "$R0\*.*"
  ${IfNot} ${Errors}
    ${Do}
      ${If} $R2 != "."
      ${AndIf} $R2 != ".."
        ${If} $R2 != ".antigos"
        ${OrIf} $R4 != '${LIMPEZA_ANTIGOS} "$R0\.antigos"'
          StrCpy $R3 0
          ${Break}
        ${EndIf}
      ${EndIf}
      ClearErrors
      FindNext $R1 $R2
      ${If} ${Errors}
        ${Break}
      ${EndIf}
    ${Loop}
    FindClose $R1
  ${EndIf}
  ClearErrors
  StrCpy $R0 $R3
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
  Exch $R0
FunctionEnd

; A pasta escolhida ($INSTDIR) pode receber o Helestron? Sim se não existe,
; se está vazia ou se já tem o Helestron (atualização). Com outras coisas (do
; usuário, de outro programa), o Helestron vai para uma pasta própria dentro
; dela, <pasta>\Helestron - o que o botão Procurar do assistente já faz -,
; para nada se misturar: a atualização e a desinstalação só apagam o que a
; instalação pôs lá, mas uma pasta "Lib" ou "modelos" do usuário receberia
; arquivos do programa. Empurra "nova", "atualizacao", "ajustada" ($INSTDIR
; passou a <pasta>\Helestron) ou "recusada" (a subpasta Helestron também tem
; outras coisas). $PastaEscolhida guarda a pasta de antes.
Function ConferirDestino
  Push $R0
  Push $R1
  Push $R2
  StrCpy $PastaEscolhida $INSTDIR
  StrCpy $R0 $INSTDIR
  StrCpy $R1 $R0 1 -1
  ${If} $R1 == "\"
    StrCpy $R0 $R0 -1          ; C:\ -> C:
  ${EndIf}
  Push $R0
  Call EhDoHelestron
  Pop $R1
  ${If} $R1 == 1
    StrCpy $R2 "atualizacao"
  ${Else}
    Push $R0
    Call PastaVazia
    Pop $R1
    ${If} $R1 == 1
      StrCpy $R2 "nova"
    ${Else}
      StrCpy $R0 "$R0\Helestron"
      Push $R0
      Call EhDoHelestron
      Pop $R1
      ${If} $R1 == 1
        StrCpy $R2 "ajustada"
      ${Else}
        Push $R0
        Call PastaVazia
        Pop $R1
        ${If} $R1 == 1
          StrCpy $R2 "ajustada"
        ${Else}
          StrCpy $R2 "recusada"
        ${EndIf}
      ${EndIf}
      ${If} $R2 == "ajustada"
        StrCpy $INSTDIR $R0
      ${EndIf}
    ${EndIf}
  ${EndIf}
  StrCpy $R0 $R2
  Pop $R2
  Pop $R1
  Exch $R0
FunctionEnd

; A página da pasta: só segue com uma pasta que possa receber o Helestron
; (ConferirDestino) e em que dê para gravar (o instalador roda sem
; administrador; C:\Program Files não serve).
Function ConferirPasta
  Call ConferirDestino
  Pop $0
  ${If} $0 == "recusada"
    MessageBox MB_OK|MB_ICONEXCLAMATION "A pasta escolhida já tem outros arquivos, e a pasta Helestron dentro dela também:$\r$\n$PastaEscolhida$\r$\n$\r$\nPara não misturar o Helestron com arquivos de outros programas (ou seus), escolha uma pasta vazia. A pasta sugerida ($LOCALAPPDATA\Programs\Helestron) serve."
    Abort
  ${ElseIf} $0 == "ajustada"
    ${If} ${Cmd} `MessageBox MB_OKCANCEL|MB_ICONINFORMATION "A pasta escolhida já tem outros arquivos:$\r$\n$PastaEscolhida$\r$\n$\r$\nPara não misturar o Helestron com eles, ele será instalado numa pasta própria dentro dela:$\r$\n$INSTDIR$\r$\n$\r$\nClique em OK para continuar ou em Cancelar para escolher outra pasta." IDCANCEL`
      StrCpy $INSTDIR $PastaEscolhida
      Abort
    ${EndIf}
  ${EndIf}
  ; o Helestron já instalado em outra pasta muda para esta (o programa sai
  ; de lá; os dados do usuário não estão em nenhuma das duas)
  Call OutraInstalacao
  Pop $1
  ${If} $1 != ""
    ${If} ${Cmd} `MessageBox MB_OKCANCEL|MB_ICONINFORMATION "O Helestron já está instalado em outra pasta:$\r$\n$1$\r$\n$\r$\nEle será fechado e removido de lá e instalado na pasta escolhida:$\r$\n$INSTDIR$\r$\n$\r$\nAs configurações, as senhas, os processos e as transcrições são mantidos.$\r$\n$\r$\nClique em OK para continuar ou em Cancelar para escolher outra pasta." IDCANCEL`
      StrCpy $INSTDIR $PastaEscolhida
      Abort
    ${EndIf}
  ${EndIf}
  ${If} $0 == "ajustada"
    ; a página relê a pasta do campo depois desta função (e o mostra de
    ; novo no Voltar): o campo passa a ter a pasta própria
    FindWindow $1 "#32770" "" $HWNDPARENT
    GetDlgItem $1 $1 1019
    SendMessage $1 ${WM_SETTEXT} 0 "STR:$INSTDIR"
  ${EndIf}
  Call PodeGravarNaPasta
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Não há permissão para gravar na pasta:$\r$\n$INSTDIR$\r$\n$\r$\nEscolha uma pasta do seu usuário. A pasta sugerida ($LOCALAPPDATA\Programs\Helestron) não precisa de administrador."
    StrCpy $INSTDIR $PastaEscolhida
    Abort
  ${EndIf}
FunctionEnd

; O atalho "Assessor Integrado" da versão anterior ($R0 = o .lnk): apagado só
; se for mesmo dela - o alvo é o pythonw.exe do runtime antigo
; (<pasta>\runtime\python\pythonw.exe) e o argumento, o iniciar.pyw. Um
; atalho de mesmo nome que aponte para outra coisa fica. A leitura é a do
; Windows (IShellLinkW e IPersistFile::Load).
!define CLSID_SHELLLINK "{00021401-0000-0000-C000-000000000046}"
!define IID_ISHELLLINKW "{000214F9-0000-0000-C000-000000000046}"
!define IID_IPERSISTFILE "{0000010B-0000-0000-C000-000000000046}"
Function ApagarAtalhoAntigo
  Exch $R0
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  Push $R5
  ${If} ${FileExists} "$R0"
    StrCpy $R3 ""
    StrCpy $R4 ""
    System::Call 'ole32::CoCreateInstance(g "${CLSID_SHELLLINK}", p 0, i 1, g "${IID_ISHELLLINKW}", *p .R1) i .R5'
    ${If} $R5 = 0
      ; QueryInterface(IPersistFile), Load(arquivo, STGM_READ), GetPath, GetArguments
      System::Call '$R1->0(g "${IID_IPERSISTFILE}", *p .R2) i .R5'
      ${If} $R5 = 0
        System::Call '$R2->5(w R0, i 0) i .R5'
        ${If} $R5 = 0
          System::Call '$R1->3(w .R3, i ${NSIS_MAX_STRLEN}, p 0, i 0)'
          System::Call '$R1->10(w .R4, i ${NSIS_MAX_STRLEN})'
        ${EndIf}
        System::Call '$R2->2()'
      ${EndIf}
      System::Call '$R1->2()'
    ${EndIf}
    ; o alvo termina em \runtime\python\pythonw.exe; os argumentos, em iniciar.pyw (com ou sem aspas)
    StrCpy $R1 $R3 "" -27
    StrCpy $R2 $R4 1 -1
    ${If} $R2 == '"'
      StrCpy $R4 $R4 -1
    ${EndIf}
    StrCpy $R2 $R4 "" -12
    ${If} $R1 == "\runtime\python\pythonw.exe"
    ${AndIf} $R2 == "\iniciar.pyw"
      Delete "$R0"
      DetailPrint "Atalho da versão anterior (Assessor Integrado) removido: $R0"
    ${EndIf}
  ${EndIf}
  ClearErrors
  Pop $R5
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
  Pop $R0
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

  ; 0. a pasta escolhida: nada se mistura com o que não é do Helestron (no
  ;    modo silencioso, /D=, não há a página; na interativa, ela já ajustou)
  Call ConferirDestino
  Pop $0
  ${If} $0 == "recusada"
    MessageBox MB_OK|MB_ICONSTOP "A pasta escolhida já tem outros arquivos, e a pasta Helestron dentro dela também:$\r$\n$PastaEscolhida$\r$\n$\r$\nPara não misturar o Helestron com arquivos de outros programas (ou do usuário), instale numa pasta vazia. A pasta sugerida ($LOCALAPPDATA\Programs\Helestron) serve." /SD IDOK
    SetErrorLevel ${PASTA_OCUPADA}
    Abort "A pasta escolhida tem arquivos de outros programas; nada foi copiado."
  ${ElseIf} $0 == "ajustada"
    DetailPrint "A pasta escolhida ($PastaEscolhida) já tem outros arquivos: o Helestron vai para $INSTDIR."
  ${EndIf}
  ; atualização é a pasta FINAL já ter o Helestron: também a "ajustada" do
  ; /D=<pasta> repetido na versão seguinte (o Helestron já na subpasta)
  StrCpy $EraDoHelestron 0
  ${If} $0 == "atualizacao"
    StrCpy $EraDoHelestron 1
  ${ElseIf} $0 == "ajustada"
    Push $INSTDIR
    Call EhDoHelestron
    Pop $1
    ${If} $1 == 1
      StrCpy $EraDoHelestron 1
    ${EndIf}
  ${EndIf}

  ; ...e dá para gravar nela?
  Call PodeGravarNaPasta
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_OK|MB_ICONSTOP "Não há permissão para gravar na pasta:$\r$\n$INSTDIR$\r$\n$\r$\nInstale numa pasta do seu usuário. A pasta sugerida ($LOCALAPPDATA\Programs\Helestron) não precisa de administrador." /SD IDOK
    SetErrorLevel 8
    Abort "Sem permissão para gravar em $INSTDIR."
  ${EndIf}

  ; 1. o Helestron registrado em OUTRA pasta: fechado e removido de lá, como
  ;    numa atualização (a mesma audiência em andamento adia tudo, código 7,
  ;    antes de qualquer mudança). Sem isso, ele ficava aberto - a instância
  ;    é por usuário, e o "Abrir o Helestron" do fim só traria o antigo para
  ;    a frente -, sem entrada em Aplicativos, com uns 850 MB, e o
  ;    desinstalador dele apagaria a chave e os atalhos desta instalação.
  Call OutraInstalacao
  Pop $Registrada
  ${If} $Registrada != ""
    DetailPrint "O Helestron estava instalado em $Registrada: ele é fechado e removido de lá."
    StrCpy $PastaNova $INSTDIR
    StrCpy $INSTDIR $Registrada
    Call FecharHelestron
    Call EsperarArquivosLivres
    RMDir /r "${PASTA_ANTIGOS}"
    Call LiberarArquivos
    SetDetailsPrint listonly
    Call RemoverPrograma
    Delete "$INSTDIR\${DESINSTALADOR}"
    SetDetailsPrint both
    Call AgendarLimpeza
    ; só some se ficou vazia (nada do usuário é apagado aqui)
    RMDir "$INSTDIR"
    ; os atalhos eram dela (os desta instalação são criados abaixo)
    Delete "$SMPROGRAMS\Helestron.lnk"
    Delete "$DESKTOP\Helestron.lnk"
    StrCpy $INSTDIR $PastaNova
  ${EndIf}

  ; 2. fecha o Helestron aberto e espera os arquivos ficarem livres
  Call FecharHelestron
  Call EsperarArquivosLivres

  ; 3. remove o programa da versão anterior: só os arquivos que ela pôs aqui
  ;    (os dados ficam em %LOCALAPPDATA%\Helestron e em Documentos\Helestron).
  ;    Restos de uma atualização anterior que já não estão em uso saem antes.
  ${If} $EraDoHelestron == 1
    RMDir /r "${PASTA_ANTIGOS}"
    Call LiberarArquivos
    DetailPrint "Removendo a versão anterior do programa..."
    SetDetailsPrint listonly
    Call RemoverPrograma
    SetDetailsPrint both
  ${EndIf}

  ; 4. copia o programa - a lista dele antes de tudo: uma cópia interrompida
  ;    ainda é reconhecida (e removida) pela próxima instalação
  DetailPrint "Copiando o Helestron..."
  SetDetailsPrint listonly
  SetOutPath "$INSTDIR"
  !insertmacro ExtrairRegistro "$INSTDIR\${REGISTRO}"
  File /r "@ARVORE@/*"
  SetDetailsPrint both

  WriteUninstaller "$INSTDIR\${DESINSTALADOR}"

  ; 5. Menu Iniciar (direto em Programas, como no Windows 10 e 11)
  SetOutPath "$INSTDIR"
  CreateShortcut "$SMPROGRAMS\Helestron.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0 SW_SHOWNORMAL "" "Baixar processos, transcrever audiências, monitorar a pauta e compartilhar com a IA"

  ; 6. Programas e Recursos / Aplicativos instalados
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

  ; 7. onde está o programa, para quem o chama de fora (a skill do Claude,
  ;    scripts da TI): o python.exe ("python.exe" -I -m helestron ...), a
  ;    versão e a pasta - que também tem o helestron.cmd. O PATH não é
  ;    alterado: outro Python do computador não é afetado, nem afeta este.
  WriteRegStr HKCU "${CHAVE_PROGRAMA}" "Python" "$INSTDIR\python.exe"
  WriteRegStr HKCU "${CHAVE_PROGRAMA}" "Versao" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE_PROGRAMA}" "InstallLocation" "$INSTDIR"

  ; 8. quem usava o Assessor Integrado (a versão anterior): o atalho dele sai
  ;    da Área de Trabalho e do Menu Iniciar, e os conectores dele, do Claude
  ;    Desktop e do Codex - num processo à parte, sem console e sem esperar:
  ;    a limpeza nunca segura nem derruba a instalação
  Push "$DESKTOP\Assessor Integrado.lnk"
  Call ApagarAtalhoAntigo
  Push "$SMPROGRAMS\Assessor Integrado.lnk"
  Call ApagarAtalhoAntigo
  ${If} ${FileExists} "$INSTDIR\pythonw.exe"
    ClearErrors
    Exec '"$INSTDIR\pythonw.exe" -I -c "from helestron.compartilhar import migracao; migracao.limpar_restos_antigos()"'
    ClearErrors
  ${EndIf}

  ${If} $EraDoHelestron == 1
    Call AgendarLimpeza
  ${EndIf}
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
  !insertmacro MUI_DESCRIPTION_TEXT ${SecPrograma} "O Helestron, com tudo de que precisa: Python, bibliotecas, os modelos de transcrição e a linha de comando (helestron.cmd)."
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

  ; Esta é a instalação registrada? Uma cópia em outra pasta (a de antes de
  ; uma instalação noutro lugar que não chegou a removê-la, uma cópia à mão)
  ; sai sem levar a chave, os atalhos e os conectores da registrada - que
  ; apontam para o python.exe dela, não daqui.
  Call un.OutraInstalacao
  Pop $Registrada

  Call un.FecharHelestron
  Call un.EsperarArquivosLivres

  ; Sessões dos portais e perfis do navegador (em instalações antigas, cópia
  ; do perfil do Chrome com senhas e cookies): não são configuração, saem
  ; sempre - antes da pergunta sobre os dados, e também no modo silencioso.
  ; No máximo, pedem um novo login no portal.
  DetailPrint "Apagando as sessões dos portais e os perfis do navegador..."
  RMDir /r "$LOCALAPPDATA\Helestron\perfis"
  ${If} ${FileExists} "$LOCALAPPDATA\Helestron\perfis\*.*"
    DetailPrint "Parte dos perfis do navegador estava em uso e ficou em $LOCALAPPDATA\Helestron\perfis: apague essa pasta depois."
  ${EndIf}

  ; os conectores do acervo no Claude Desktop e no Codex/ChatGPT Work
  ; (%USERPROFILE%\.codex\config.toml) apontam para o python.exe daqui: sem
  ; o programa, eles só dariam erro. Um de cada vez: a falha de um não
  ; impede o outro. As duas funções tiram o "helestron" e também os nomes
  ; da versão anterior (assessor-integrado e assessor_integrado), caso a
  ; limpeza da instalação não tenha rodado.
  ${If} $Registrada != ""
    DetailPrint "O Helestron continua instalado em $Registrada: os conectores, os atalhos e o registro dele ficam."
  ${ElseIf} ${FileExists} "$INSTDIR\python.exe"
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
  ; só o que a instalação pôs aqui (a lista dela, com o helestron.cmd): o resto fica
  Call un.RemoverPrograma
  Delete "$INSTDIR\${DESINSTALADOR}"
  SetDetailsPrint both
  Call un.AgendarLimpeza
  ; só some se ficou vazia (nada do usuário é apagado aqui)
  RMDir "$INSTDIR"

  ${If} $Registrada == ""
    Delete "$SMPROGRAMS\Helestron.lnk"
    Delete "$DESKTOP\Helestron.lnk"
    DeleteRegKey HKCU "${CHAVE_DESINSTALAR}"
    ; só os valores que a instalação gravou; a chave só sai se ficou vazia
    DeleteRegValue HKCU "${CHAVE_PROGRAMA}" "Python"
    DeleteRegValue HKCU "${CHAVE_PROGRAMA}" "Versao"
    DeleteRegValue HKCU "${CHAVE_PROGRAMA}" "InstallLocation"
    DeleteRegKey /ifempty HKCU "${CHAVE_PROGRAMA}"

    ; Configurações e senhas: só com o sim do usuário (no modo silencioso,
    ; não) - e só quando o Helestron sai do computador: com outra instalação
    ; registrada, elas são dela. Documentos\Helestron (processos,
    ; transcrições, pauta) nunca é apagado.
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Apagar também as configurações e as senhas guardadas do Helestron?$\r$\n$\r$\nElas ficam em $LOCALAPPDATA\Helestron (configurações, registros, senhas dos portais e a pauta monitorada). Se você pretende instalar o Helestron de novo, responda Não.$\r$\n$\r$\nAs sessões dos portais e os perfis do navegador já foram apagados. Os processos, as transcrições e a pauta exportada (Documentos\Helestron) não são apagados em nenhum caso." /SD IDNO IDNO manter
      DetailPrint "Apagando as configurações e as senhas..."
      RMDir /r "$LOCALAPPDATA\Helestron"
    manter:
  ${EndIf}
SectionEnd
