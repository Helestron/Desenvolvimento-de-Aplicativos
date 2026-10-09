# Helestron — especificação técnica (versão 1.1.0)

Documento de referência para a reconstrução do antigo “Assessor Integrado” como
**Helestron**. Tudo o que for dúvida de comportamento se decide aqui; o que não
estiver aqui segue o código já existente do motor (download, transcrição,
compartilhamento), que foi testado e deve ser preservado.

## 1. O que o usuário pediu (literal, resumido)

1. Instalação **direta no Windows**, sem executar comandos no PowerShell ou no
   terminal.
2. Layout **claro, intuitivo e limpo**, aparência clara, com **transparências e
   elementos gráficos similares ao iOS**, em tons de **azul, cinza e branco**.
3. O programa se chama **Helestron**.
4. Nova função: **monitoramento da pauta de audiências** integrada com o **e-SAJ
   (SAJ)** e o **eProc**, com **extração da pauta em Excel** (o sistema acessa o
   gerenciamento/pauta de audiências dos portais).
5. Mantidas as funções anteriores: baixar processos de uma relação (um PDF por
   processo, nomeado pelo número), transcrição simultânea de audiências (DOCX
   nomeado pelo número) e compartilhamento das pastas com Claude Code, Cowork e
   ChatGPT Work.
6. Problemas da versão anterior a eliminar: instalação deficiente (o sistema não
   rodou) e o erro **“Esta parte do programa não abriu — No module named
   'app.interface.pagina_config'”**.
7. Ícone com a letra **“H”**, design moderno, cores **navy e cinza**, com
   **efeito de transparência**.
8. Tudo disponível para download no Claude e copiado para o GitHub, substituindo
   todo o conteúdo do repositório.

## 2. Diagnóstico da versão anterior e como o Helestron o elimina

| Problema | Causa | Solução no Helestron |
|---|---|---|
| Instalação por `INSTALAR.bat` + PowerShell, baixando ~800 MB na hora | rede do tribunal (proxy, bloqueio de PyPI/Hugging Face), GPO que bloqueia scripts, janela de console | **Um só `Helestron-Setup-1.1.0.exe`** (NSIS, assistente gráfico em português), **offline**: Python, bibliotecas e modelo de transcrição vão dentro. Sem PowerShell, sem console, sem administrador. |
| `No module named 'app.interface.pagina_config'` | um arquivo do programa sumiu depois da extração (antivírus que põe em quarentena arquivo que lida com senhas, extração parcial) e as telas eram importadas por nome em tempo de execução (`importlib`) | (a) interface em HTML: não há mais módulo Python por tela; (b) **imports estáticos** em todo o pacote; (c) **manifesto de integridade** conferido na abertura, com mensagem clara e botão “Reparar” (procura o `Helestron-Setup-X.Y.Z.exe` na pasta Downloads registrada no Windows, confere que é o instalador do Helestron e o abre só com a confirmação do usuário — o instalador não deixa cópia de si —, ou explica como baixá-lo de novo; seção 3.4); (d) o instalador roda `Helestron.exe --verificar-instalacao` ao final e avisa se algo faltar; (e) Python isolado (`-I`): variáveis `PYTHONPATH`/`PYTHONHOME` da máquina não interferem; (f) o lançador confere, antes de iniciar o Python, os arquivos sem os quais nem a tela de erro abre e diz qual falta (seção 10, etapa 6). |
| Janela Tkinter datada | limitação do Tk | Interface web local (HTML/CSS/JS) numa janela nativa (WebView2), com vidro translúcido e componentes no estilo iOS. |

## 3. Arquitetura

```
Helestron.exe (lançador C, ícone H)  ──►  python312.dll  ──►  python -I -m helestron
        │
        ▼
helestron.aplicativo.inicio.main()
   1. instância única (trava em %LOCALAPPDATA%\Helestron\instancia.json)
   2. integridade (manifesto.json)            → tela de erro própria se faltar arquivo
   3. servidor HTTP local (127.0.0.1, porta livre, token)  ← helestron.servidor
   4. janela: pywebview (EdgeChromium/WebView2 ≥ 101.0.1210.39, com vigia de carregamento)
        └ reserva 1: Edge em modo aplicativo (msedge --app=URL)
        └ reserva 2: navegador padrão (nunca o Internet Explorer nem o Edge antigo)
        └ nenhuma: caixa de mensagem com o caminho para o WebView2 (saída 1)
   5. monitor da pauta (thread), limpeza de .antigos e demais serviços sob demanda
```

A interface (pasta `helestron/web`) conversa **só** com a API HTTP (seção 6).
O motor (download, transcrição, compartilhamento, pauta) nunca conhece a
interface: fala por eventos (seção 6.4) e perguntas (seção 6.5).

### 3.1 Estrutura do repositório

```
README.md                      apresentação e instalação
.gitignore  .gitattributes
.github/workflows/helestron.yml  CI: testes, construção do instalador, instalação real no Windows, publicação
docs/ESPECIFICACAO.md          este documento
docs/MANUAL.md                 manual do usuário
docs/INTEGRACAO-CLAUDE.md      como uma skill do Claude Code (ou um script) chama a linha de comando
helestron/                     o pacote Python (vai inteiro para o instalador)
  __init__.py  __main__.py
  aplicativo/                  inicialização, janela, instância única, integridade, autoteste
  servidor/                    servidor HTTP, API, eventos, perguntas, tarefas web
  servicos.py  tarefas.py      ponte entre a API e o motor (sem interface gráfica)
  nucleo/  download/  transcricao/  compartilhar/   o motor (já existente)
  pauta/                       NOVO: pauta de audiências
  verificar.py                 diagnóstico da instalação
  dados/                       tribunais.json, pauta.json, seletores de reserva (a correção vale em LOCAL)
  recursos/                    helestron.ico, helestron.png, imagens do instalador
  web/                         a interface (index.html, css/, js/, fontes/, img/)
testes/                        unittest (Linux e Windows)
construir/                     construção do instalador (roda em Linux e no CI)
  construir.py  requisitos-windows.in/.txt  requisitos-teste.txt
  instalador/helestron.nsi     modelo do script NSIS
  lancador/helestron.c  helestron.rc  helestron.manifest
  marca.py                     gera ícone e imagens do instalador
```

### 3.2 O que fica instalado no Windows

Instalação **por usuário** (sem administrador) em
`%LOCALAPPDATA%\Programs\Helestron\` — a própria pasta do Python:

```
Helestron.exe          lançador (ícone H); roda python -I -m helestron
helestron.cmd          a linha de comando: "%~dp0python.exe" -I -m helestron %* (só ASCII, CRLF;
                       o código de saída é o do Python)
python.exe pythonw.exe python312.dll python3.dll vcruntime140*.dll msvcp140*.dll
DLLs\  Lib\  Lib\site-packages\helestron\ ...   (bibliotecas + o pacote, com .pyc pré-compilados)
modelos\faster-whisper-small\   modelo de transcrição ao vivo (embutido)
modelos\falantes\               modelos da separação de falantes (embutidos; numa construção
                       --sem-falantes, Ajustes › Transcrição oferece "Baixar os modelos de voz")
helestron.ico  manifesto.json  Desinstalar.exe
arquivos-instalados.txt  a lista do que a instalação pôs na pasta (UTF-16; depois do cabeçalho
                       "Helestron <versão> ...", "A <arquivo>" para cada arquivo e "P <pasta>"
                       para cada pasta): a atualização e o desinstalador apagam só o que está nela
.antigos\<instante>\  só depois de uma atualização: arquivos da versão anterior que estavam
                       presos (servidor MCP aberto pelo Claude Desktop ou pelo Codex), renomeados
                       pelo instalador; apagados no próximo logon (RunOnce) ou na próxima abertura
```

A pasta do programa é só do Helestron: o instalador nunca o põe no meio de
outros arquivos (seção 10, item 1), e a atualização e o desinstalador apagam
só o que a lista registra, arquivo por arquivo, e as pastas só se ficarem
vazias. Arquivos e pastas do usuário (ou de outro programa) que estiverem lá
ficam.

No registro do Windows, além da chave de desinstalação
(`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Helestron`), a
chave `HKCU\Software\Helestron` traz `Python` (`<pasta>\python.exe`),
`Versao` e `InstallLocation`: é por ela que quem chama o programa de fora
(a skill do Claude, scripts da TI) o encontra. O PATH não é alterado.

Dados do usuário (nunca apagados pela desinstalação sem perguntar, salvo
`perfis\`, que sai sempre):

| O quê | Onde |
|---|---|
| configuração `config.ini`, `Logs\` (com `execucoes\`, os registros do `baixar --json`), `perfis\` (só as sessões dos portais, cifradas pela DPAPI, e, no modo certificado, a cópia do Web Signer: seção 12; uma pasta por portal, `Tribunal.perfil`: `esaj-TJAL`, `eproc-TJAL`, `eproc2g-TJAL`, seção 14), `credenciais.json` (DPAPI), `pauta.sqlite3`, `pauta.sigilo.json` (o sigilo que a pauta já apurou, fora do banco: seção 12), `instancia.json`, `modelos\` baixados depois, `temp\`, `webview\` e `edge-app\` (perfis da janela), e as correções locais que a atualização não apaga: `enderecos-locais.json`, `seletores.json` e `seletores-eproc.json` (valem por cima do que vem em `dados\`, que fica de reserva) | `%LOCALAPPDATA%\Helestron\` |
| Acervo (processos, transcrições) — compartilhado com a IA | `Documentos\Helestron\Acervo\` (`Processos\`, `Transcricoes\`) |
| Sigilosos (segredo de justiça) — nunca compartilhado | `Documentos\Helestron\Sigilosos\` |
| Pauta exportada (Excel) — **fora do acervo** (traz partes de processos sigilosos) | `Documentos\Helestron\Pauta\` |

Se a pasta Documentos estiver dentro do OneDrive (redirecionamento de pastas
conhecidas) ou do Google Drive (`caminhos.no_google_drive`: a unidade virtual
ou o modo espelho, `%USERPROFILE%\Meu Drive`), a base passa a ser
`%USERPROFILE%\Helestron\` — a sincronização trava arquivo em uso (lição do
Assessor SAJ), e os sigilosos e a pauta não podem ficar numa pasta
sincronizada. Tudo configurável em Ajustes.

### 3.3 A janela (`helestron/aplicativo/janela.py`)

* **WebView2 com versão mínima.** A pywebview 6 usa uma interface do WebView2
  (`ICoreWebView2Environment10`) que só existe a partir do runtime
  **101.0.1210.39** (`VERSAO_MINIMA_WEBVIEW2`); vale a maior versão (“pv”)
  das chaves que a pywebview lê. Um runtime mais antigo (86 a 100) conta
  como ausente: a janela abriria vazia, e o programa vai direto para o
  Edge. O diagnóstico
  (`verificar.avaliar_webview2`) usa a mesma régua: abaixo dela, o item é
  **aviso**, com a orientação de atualizar o runtime.
* **Vigia de carregamento.** Mesmo aprovado, o WebView2 pode falhar ao
  iniciar (runtime danificado, política da empresa): a pywebview só registra
  o erro e deixa a janela cinza. Depois que a janela aparece (prazo de
  `PRAZO_APARECER_S` = 120 s para aparecer), a página tem
  `PRAZO_CARREGAR_S` = 30 s para dar sinal: o evento `loaded` da pywebview
  ou a página conectada ao canal de eventos (`/api/eventos`, que só a página
  abre: o `EventSource` de `web/js/api.js` e o da tela de erro, seção 3.4).
  Pedidos à API não contam: a segunda abertura do programa (o duplo clique de
  novo no atalho diante da janela cinza, que pede `/api/ping` e
  `/api/janela/mostrar`) e o `--encerrar` do instalador também falam com o
  servidor, e a janela vazia passaria por carregada. Sem sinal, a janela
  vazia é fechada, `abrir()` devolve False e o programa passa para o Edge. A
  janela vazia fechada pelo usuário também cai no Edge. (Uma página cujo
  canal de eventos nunca se conecta, embora os pedidos à API funcionem,
  conta como não carregada.)
* **Reservas.** O Edge em modo aplicativo (perfil próprio em
  `LOCAL\edge-app`) e, sem ele, o navegador padrão, numa aba. O navegador
  padrão é lido da escolha do usuário (`UserChoice`, ProgId) ou, sem ela, do
  comando do `http`; o Internet Explorer (`IE.*`) e o Edge antigo (EdgeHTML)
  nunca são usados, porque não rodam a interface (ES2020). O sinal é o
  mesmo: a página conectada ao canal de eventos. O Edge ou o navegador que
  nunca dão sinal em `PRIMEIRO_SINAL_S` = 120 s contam como falha, e a
  próxima reserva é tentada. Depois do sinal, o programa encerra quando o
  processo do Edge sai e a página se desconecta, ou quando o canal fica
  `SEM_SINAL_S` = 60 s sem contato (o ping dele vem a cada 15 s).
* **Sem nenhuma janela.** `inicio.py` mostra uma caixa de mensagem (“O
  Helestron não pôde abrir”) com `janela.motivo_sem_janela()`: falta o
  Microsoft Edge WebView2 Runtime (ou ele é antigo, com a versão
  encontrada), como instalá-lo (o endereço oficial; não precisa de
  administrador) e a alternativa do Google Chrome como navegador padrão. O
  processo sai com o código 1, em vez de sumir.
* **Tamanho que cabe na tela.** `area_util_dip()` lê a área útil do monitor
  do ponteiro (`GetMonitorInfoW.rcWork`) em pixels lógicos
  (`GetDpiForMonitor`). `tamanho_inicial()` devolve largura, altura, mínimo
  e `maximized`: se 1280×820 mais a folga de 16 DIP não couber (Full HD a
  150 % dá 1280×672 úteis; 1366×768), a janela abre **maximizada**, com o
  tamanho restaurado e o mínimo cortados para caber. O Edge recebe o
  `--window-size` coerente e, nesse caso, `--start-maximized`.
* **Atenção nas perguntas** (contrato C3, seção 6.6): a `JanelaWebview`
  registra `chamar_atencao` no servidor; a cada pergunta, a janela
  minimizada é restaurada, vem para a frente e pisca na barra de tarefas.
* **Sem AppUserModelID explícito**: o Windows usa o implícito do
  `Helestron.exe`, o mesmo dos atalhos do instalador (o Helestron fixado na
  barra de tarefas reconhece a janela aberta); o ícone vem do `.exe`.

### 3.4 Tela de erro e “Reparar” (`aplicativo/erro.py`, `aplicativo/integridade.py`)

Arquivo do programa ausente ou alterado (manifesto): em vez de abrir, o
programa mostra uma tela própria, no mesmo servidor local (modo de erro,
poucas rotas) e na mesma janela, com o que falta, a hipótese mais provável
(antivírus, instalação interrompida), a garantia de que os dados não foram
afetados e os botões **Reparar**, **Abrir os registros** e **Fechar**. A
tela grava o `instancia.json`, como a abertura normal: o `--encerrar` do
instalador e a segunda abertura falam com ela. E abre o canal de eventos
(`/api/eventos`, que no modo de erro só manda o ping): é o sinal de que ela
carregou, para a vigia da janela (seção 3.3), e, no Edge e no navegador, o
de que continua aberta.

**Reparar** tem dois cliques. No primeiro (pedido `/api/integridade/reparar`,
sem corpo), o programa procura o instalador e devolve
`{confirmar: true, arquivo, mensagem}`, com o nome, o tamanho, a data e a
pasta do arquivo encontrado; a tela mostra o botão **Abrir o instalador**. O
segundo clique (`{arquivo}`) só abre o arquivo se ele ainda for o mesmo que
a busca acha agora. A busca (`integridade.procurar_instalador`):

* olha a pasta Downloads registrada no Windows
  (`SHGetKnownFolderPath(FOLDERID_Downloads)`, que segue o redirecionamento
  de pastas da TI) e, de reserva, `%USERPROFILE%\Downloads`, sem repetir;
  também `LOCAL` e a pasta do programa;
* só aceita o nome publicado, `Helestron-Setup-X.Y.Z.exe` (ou com “ (n)”,
  quando baixado de novo), nunca de versão mais velha que a instalada; a
  versão mais nova vem primeiro e, na mesma versão, o arquivo mais recente;
* confere cada candidato (`conferir_instalador`): começa com `MZ`, tem o
  cabeçalho NSIS (`0xDEADBEEF` + `NullsoftInst` num limite de 512 bytes), a
  descrição “Instalador do Helestron” (UTF-16) e, se houver o `.sha256` ao
  lado, o SHA-256 batendo. Não há conferência de assinatura Authenticode:
  o instalador ainda não é assinado.

Sem instalador aceitável, a tela explica como baixá-lo de novo na página de
versões.

## 4. Caminhos (`helestron/nucleo/caminhos.py`)

```python
PACOTE      = Path(__file__).resolve().parents[1]          # .../helestron
INSTALADO   = (Path(sys.prefix) / "manifesto.json").exists()
INSTALACAO  = Path(sys.prefix) if INSTALADO else PACOTE.parent   # pasta do programa (ou o repositório)
DADOS       = PACOTE / "dados"
RECURSOS    = PACOTE / "recursos"
WEB         = PACOTE / "web"
MODELOS_EMBUTIDOS = INSTALACAO / "modelos"
LOCAL       = env HELESTRON_LOCAL  ou  %LOCALAPPDATA%\Helestron  (fora do Windows: ~/.helestron)
ARQUIVO_CONFIG = LOCAL / "config.ini";  LOGS = LOCAL / "Logs";  PERFIS = LOCAL / "perfis"
ARQUIVO_SENHAS = LOCAL / "credenciais.json";  TEMP = LOCAL / "temp";  MODELOS = LOCAL / "modelos"
ARQUIVO_PAUTA  = LOCAL / "pauta.sqlite3";  ARQUIVO_INSTANCIA = LOCAL / "instancia.json"
BASE_USUARIO   = env HELESTRON_DADOS  ou  Documentos\Helestron  (ou %USERPROFILE%\Helestron se Documentos estiver no OneDrive ou no Google Drive)
python_exe(janela=False) -> INSTALACAO/python.exe | pythonw.exe | sys.executable
```

O registro do sigilo apurado pela pauta fica ao lado do banco
(`sigilo.arquivo_apurado`: `pauta.sqlite3` → `pauta.sigilo.json`), e o do
apurado pelo download também (`sigilo.arquivo_do_download`:
`download.sigilo.json`). O download grava os registros do `baixar --json`
sem `--log` em `LOGS/execucoes/baixar-<data>-<pid>.log`
(`download/cli.log_padrao`).

Os testes isolam tudo com `HELESTRON_LOCAL` e `HELESTRON_DADOS` apontando para
pastas temporárias (ou com `mock.patch` nas constantes, como já fazem). A
base `testes/apoio_download.PastaTemporaria` põe também `ARQUIVO_PAUTA` (e
com ele os registros do sigilo apurado) na pasta de cada teste: o sigilo
que o download de um teste registra não vale para o seguinte.

## 5. Linha de comando (`python -m helestron`)

| Comando | O que faz |
|---|---|
| *(sem argumentos)* | abre o programa (servidor + janela) |
| `--verificar-instalacao [--relatorio ARQ]` | sem janela: confere o manifesto (hash de todos os arquivos), importa **todos** os módulos do pacote, roda as checagens de `helestron.verificar` (bibliotecas, componentes nativos, modelo embutido carregado de verdade, navegador, pastas, cofre, regras da pauta, conector MCP...) e confere WebView2/Edge. A importação e as checagens rodam em **processos à parte**: uma biblioteca nativa que derrube o processo vira um item de falha com o nome da checagem, e as demais seguem num processo novo. O relatório (UTF-8, em `ARQ`; padrão `LOCAL/Logs/verificacao-instalacao.txt`) é regravado a cada item, com a marca “Verificação em andamento” até o fim: o instalador sempre tem relatório. O item da janela fica em ordem com o WebView2 101 ou mais recente; sem ele, com o Edge (aviso) ou com um navegador padrão que rode a interface (aviso); sem nenhum (o padrão é o Internet Explorer ou o Edge antigo), é falha de código `sem_janela`. Código de saída 0 = ok (talvez com avisos), 1 = falha, 9 = a única falha é `sem_janela` (os arquivos estão certos, mas não há como abrir a janela). Usado pelo instalador, que nesse caso sai com o seu próprio código 9 (seção 10). Sem o registro do programa (`nucleo/registro.py`) ou outra parte de partida, grava um relatório mínimo (“FALHA  Falta uma parte do programa: <módulo>”, com o módulo inteiro, como `helestron.aplicativo.instancia`), sem caixa de mensagem: o instalador mostra o que falta. |
| `--autoteste PASTA` | abre a janela de verdade, a interface percorre todas as telas sozinha (`?autoteste=1`), o programa salva capturas (PNG) e `autoteste.json` em `PASTA` e fecha. Roda em **pastas de dados novas e vazias** (`PastasDoAutoteste`: `HELESTRON_LOCAL` e `HELESTRON_DADOS` apontam para uma pasta temporária antes do registro, da instância e do servidor), nunca na configuração, na pauta e no acervo de quem o roda, e sem o monitor da pauta; no fim, o registro (`Logs`) da rodada vai para `PASTA\Logs`, e a pasta temporária é apagada. Só o retângulo da janela é capturado: sem ele (a interface numa aba do navegador), não há captura, e o `autoteste.json` diz por quê. Usado no CI do Windows. |
| `--servidor [--porta N] [--sem-janela] [--token T]` | só o servidor (testes e desenvolvimento); imprime `URL=...` na saída |
| `--encerrar` | pede à instância aberta que feche e espera ela sair (usado pelo instalador e pelo desinstalador antes de mexer nos arquivos). Antes, consulta `GET /api/transcricao/estado` da instância: com a audiência em `iniciando`, `gravando` ou `pausada`, **não fecha nada** e sai com **10**. Enquanto a instância responder que está fechando (a fila da audiência recém-encerrada sendo transcrita), espera até `ESPERA_FECHANDO_S` = 18 min. Código 0 = fechou (ou não havia nenhuma aberta), 1 = continua aberta, 10 = audiência em andamento. Atende também a tela de erro da integridade. |
| `mcp [--pasta ACERVO]` | servidor MCP do acervo (stdio), como hoje. A cada pedido (`tools/call`), a listagem do acervo, a pasta dos sigilosos e a regra do sigilo são apuradas uma vez só (`Acervo.pedido()`; fora de um pedido, nada fica guardado), e `buscar` lista os PDFs uma vez: no acervo inteiro, com 3.000 PDFs, leva cerca de 0,3 s |
| `--version` (ou `--versao`) | imprime `Helestron <versão>` e sai com 0 |
| `baixar ...` | o download pela linha de comando, com o mesmo motor e os mesmos ajustes da janela (salvo o grau: sem `--grau`, 1º grau), e as opções para automação (seção 5.1; o 2º grau, seção 14) |
| `caminhos [--json]` | onde o programa guarda cada coisa e o que esta versão oferece (seção 5.2); não cria nada |
| `preparar [--sem-texto] [--json]` e `preparar --pasta PASTA [--texto-em DIR] [--incluir-sigilosos] [--json]` | o preparo do acervo para a IA, ou só o texto dos autos de uma pasta de lote (seção 5.2) |
| `transcrever ARQUIVO [--processo N] [--destino DESTINO] ...` | transcreve uma gravação. `--processo` aceita o dependente como `/01` ou `-01` (`cnj.ler_nome_arquivo`). `--destino` pode ser uma pasta (existente ou terminada em separador: o DOCX vai como `<pasta>/<número>.docx`, com nome livre) ou um arquivo (sem extensão, ganha `.docx`); um pai que é arquivo, ou uma pasta sem número do processo, é erro de uso (2). Se gravar no destino falhar (`OSError`), o documento vai para a pasta das transcrições (a dos sigilosos, se for sigiloso), e a saída diz onde ficou; outro `OSError` sai com 1 e a frase, sem rastro de pilha |
| `modelos ...`, `microfones`, `verificar`, `preparar-pastas` | como hoje (`preparar-pastas` e `caminhos` usam o `ArgumentParser`: `-h` sai com 0 e opção desconhecida com 2, antes de qualquer efeito) |
| `pauta sincronizar|exportar|importar|listar|fontes ...` | linha de comando da pauta (seção 8.9); em `exportar`, `--incluir-partes-sigilosos` ou `--sem-partes-sigilosos` (exclusivas); sem nenhuma das duas, vale `[pauta] incluir_partes_sigilosos`. `importar` e `sincronizar` aplicam na hora o sigilo que a pauta revelar (seção 12) e dizem o que saiu do acervo, também quando interrompidos (Ctrl+C) ou quando falham no meio. `listar` mascara as partes e as observações dos sigilosos como “(segredo de justiça)”, no texto e no `--json`, e a busca não olha esses campos neles, salvo `--incluir-partes-sigilosos`. `fontes --adicionar` com tribunal ou sistema inválido sai com 2; `fontes --remover` de fonte inexistente sai com 1 (“A fonte X não existe”) |

**Em português, do uso aos erros.** Toda linha de comando do projeto
(`__main__.py` e os subcomandos `baixar`, `transcrever`, `modelos`,
`falantes`, `mcp` e `pauta`, e também `construir/construir.py` e
`construir/marca.py`) usa o `ArgumentParser` de `nucleo/argumentos.py`, uma
subclasse do `argparse.ArgumentParser` com o que o usuário lê traduzido: o
“uso:” da primeira linha, os títulos “argumentos” e “opções”, o “-h, --help”
(“mostra esta ajuda e sai”) e o “(padrão: …)”. As mensagens de erro do argparse
são traduzidas por modelo de frase inteira, nunca palavra por palavra
(argumento obrigatório que falta, argumento não reconhecido, no singular e
no plural, escolha inválida, valor inválido com o tipo esperado, falta do
valor…), e o subcomando desconhecido vira “comando desconhecido: 'x'
(opções: …)”. O formato é `<prog>: erro: <mensagem>`, depois da linha de
uso (por exemplo, “python -m helestron baixar: erro: argumento não
reconhecido: --xyz”), e o código de saída continua 2. `traduzir()` e
`mensagem_de_erro()` são públicos (a transcrição devolve o código em vez de
encerrar o processo). Quem carrega o módulo pelo arquivo (a construção) tem
o `argparse` de reserva. Na linha de comando principal:

* `-h`, `--help`, `--ajuda` e `ajuda` mostram a ajuda, com a lista de
  comandos; cada comando tem a sua (`python -m helestron <comando> -h`);
* `--verificar-instalacao`, `--autoteste`, `--servidor` e `--encerrar` são
  mutuamente exclusivas; `--relatorio` só vale com `--verificar-instalacao`,
  e `--porta`, `--sem-janela` e `--token` só com `--servidor` (senão, erro
  com o código 2, como “--relatorio só vale com --verificar-instalacao”);
* o import do registro do programa é protegido: faltando uma parte de
  partida, a abertura mostra a caixa “O Helestron não pôde abrir” (“Falta uma
  parte do programa (<módulo>)”, com o módulo inteiro, e não só o pacote), e
  o `--verificar-instalacao` grava o relatório mínimo, sem caixa;
* um erro inesperado em `inicio.main` vai para o registro (`Logs`), que é
  para onde aponta a caixa de saída rápida do lançador (seção 10, etapa 6).

Quem chama o programa de fora (a skill do Claude Code, scripts da TI) o
encontra por `HKCU\Software\Helestron` (`Python`, `Versao`,
`InstallLocation`) ou pelo `helestron.cmd` da pasta do programa (seções 3.2
e 10); o guia de uso está em `docs/INTEGRACAO-CLAUDE.md`. A saída padrão e
a de erro são UTF-8 (`registro.preparar_saidas`). Compatibilidade: opções
novas são opcionais, os códigos de saída 0/1/2 não mudam de sentido, as
colunas do `relatorio.csv` só se acrescentam no fim, e os campos do JSON só
se acrescentam.

### 5.1 `baixar` para automação (`download/cli.py`, `download/acompanhamento.py`)

```
python -m helestron baixar [NÚMEROS...] [--lista ARQ|URL] [--destino PASTA] [--completar J.TR.OOOO]
       [--login senha|certificado|manual] [--grau 1g|2g] [--sem-cofre] [--visivel] [--rebaixar]
       [--rebaixar-incompletos] [--midias] [--sem-ia] [--texto] [--retomar] [--esperar-navegador MIN]
       [--json ARQ] [--eventos] [--log ARQ] [--desanexar]
```

| Opção | Efeito |
|---|---|
| `--completar J.TR.OOOO` | completa os números curtos da linha de comando (`NNNNNNN-DD.AAAA`, com ou sem `/NN`) com segmento, tribunal e foro. Argumento que não dá número nenhum não some em silêncio: vai para `ignorados` (`{argumento, motivo}`) e é impresso como “ignorado” |
| `--grau 1g\|2g` | o grau do lote (`cli._grau`: `cnj.normalizar_grau`, que aceita também `1`, `2`, `1º` e `2º`; outro valor é erro de uso do argparse, código 2: “'3' não é grau: use 1g (1º grau) ou 2g (2º grau)”). Depois do `OpcoesDownload.de_config`, `opcoes.grau = --grau` ou, sem ele, `1g` (`cli._grau_dos_argumentos`): a linha de comando **não** lê `[download] grau`, que vale só para a janela (seção 14.1). Os grupos para as credenciais (`_pedir_credenciais`) são os Tribunais no grau (`t.no_grau(cnj.grau_do_processo(n, opcoes.grau))`): o eProc do 2º grau pergunta por `eproc2g:<SIGLA>` (“Acesso ao eProc do TJAL (2º grau)”), e o e-SAJ dos dois graus é uma pergunta só (`esaj:<SIGLA>`) |
| `--sem-cofre` | não usa o cofre (`OpcoesDownload.usar_cofre = False`) nem pergunta senha: no modo `senha`, o grupo entra como `manual` (`motor._opcoes_do_grupo`), com o navegador visível na tela de entrada |
| `--rebaixar-incompletos` | baixa de novo o PDF que já está na pasta só se ele tem `incompleto`, não tem o manifesto de paginação ou tem um que não o descreve, porque foi alterado depois do download (seção 13) |
| `--texto` | depois do lote, `textos.garantir_texto` de cada PDF OK ou JA_BAIXADO: fora do acervo, em `<pasta do PDF>/_texto/<nome>.txt` (o do sigiloso fica na própria pasta de sigilosos); dentro do acervo, em `<acervo>/_ia/texto`. Autos de sigiloso presos no acervo não viram texto (`sigiloso_ignorado`). `textos.analisar` dá as páginas sem texto extraível de cada um (`paginas_sem_texto`, impressas e no JSON) |
| `--retomar` | com a relação, ou só com `--destino`: baixa os números da relação que o relatório da pasta do lote (`motor.ler_relatorio_do_lote`, que lê também o relatório completo da pasta de sigilosos) não tem ou cuja linha `pede_nova_tentativa`, o `SIGILOSO_SEM_SENHA` cuja senha a relação agora traz e as linhas do relatório que pedem nova tentativa. Da linha OK ou JA_BAIXADO, volta o que o motor baixaria de novo (`cli._baixado_que_volta`, com as mesmas regras de `_registro_anterior` e `_baixar_de_novo`): o PDF que já não está na pasta do lote nem na de sigilosos dele; com `--rebaixar-incompletos`, o que tem `incompleto`, não tem o manifesto ou tem a paginação não garantida; o do e-SAJ de versão anterior com sinal de numeração deslocada; e o PDF cujo manifesto é de outro grau. Tudo pela chave dos autos (`cnj.nome_dos_autos`): a linha só é retomada se o grau dela (`motor._grau_da_linha`) for o que a regra dá ao número nesta chamada (`cnj.grau_do_processo` com o `--grau`); a de outro grau vai para `ignorados_por_retomar`, com o `--grau` que a retoma (“do 2º grau: para retomá-la, use --grau 2g”) ou, para o número que só é procurado num grau, “nenhum --grau a retoma” (`cli._fora_do_grau`). O que fica de fora é impresso e vai para `ignorados_por_retomar`, com o porquê (o que só `--rebaixar-incompletos` refaria diz isso); sem nada a retomar, sai com 0. Só com `--destino` e sem o relatório de um lote em `_controle` (caminho errado), sai com 2 (`causa_erro` `sem_processos`) |
| `--esperar-navegador MIN` | o `NavegadorOcupado` (outro download usa o perfil do navegador do portal; ou a subclasse `CopiaAntigaPresa`, do modo certificado: a cópia antiga do perfil inteiro do Chrome ainda não pôde ser apagada) antes de o grupo começar: tenta de novo a cada `ESPERA_NAVEGADOR_S` (30 s) até o prazo, com o evento `navegador_ocupado` e o aviso do motivo real (`motivo` `outro_download` ou `copia_antiga_presa`: “ocupado por outro download”, ou a cópia antiga e o que fechar); sem a opção, o grupo termina em ERRO com a causa `navegador_ocupado`, e o detalhe diz qual dos dois. MIN é finito, de 0 a 1440 (`MAX_ESPERA_NAVEGADOR_MIN`, um dia); fora disso, erro de uso |
| `--json ARQ` | o acompanhamento em JSON (abaixo) |
| `--eventos` | cada evento numa linha `HELESTRON-EVENTO {json}` da saída padrão (`contexto.linha_de_evento`) |
| `--log ARQ` | duplica a saída padrão e a de erro no arquivo (UTF-8, `flush` a cada escrita) e acrescenta ao registro um handler INFO com `FiltroSegredos`, retirado no fim. Com `--json` e sem `--log`, vale `LOGS/execucoes/baixar-<data>-<pid>.log`. O arquivo que não pode ser aberto encerra com 2, com o JSON concluído (`causa_erro` `uso`, `log` vazio) |
| `--desanexar` | exige `--json`. Confere antes se o log pode ser aberto (senão, sai com 2 e conclui o JSON, como acima). Começa o lote num processo à parte, sem console (Windows: `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP \| CREATE_BREAKAWAY_FROM_JOB`, repetido sem o último se o job de quem chamou o recusar; fora do Windows, `start_new_session`), com `--log` (o padrão, se faltar), grava o JSON inicial com o `pid` do filho, imprime `HELESTRON-EXECUCAO {"pid", "json", "log"}` e sai com 0. O desfecho é o `codigo_saida` do JSON. O filho recebe a mesma linha sem `--desanexar`; por isso as opções do `baixar` não aceitam abreviação (`allow_abbrev=False`): um `--desa` faria cada filho se desanexar de novo |

Regras:

* **O JSON e o log trazem os números reais dos sigilosos.** Dentro do
  acervo, são recusados com o código 2, antes de qualquer efeito.
* **O código do e-SAJ, sem terminal.** Sem terminal interativo, com algum
  tribunal do lote no e-SAJ (também como sistema alternativo) e o e-SAJ no
  modo `senha`, a linha de comando liga `mostrar_navegador` e avisa
  (“Código do e-SAJ na janela do navegador”, com o prazo): o código enviado
  por e-mail é digitado no campo do próprio portal. Se `pedir_codigo`
  devolve `None` com a janela visível, o portal espera o login nela até o
  fim do prazo (`login_aguardando` com `motivo` `codigo`); sem janela, o
  `LoginFalhou` orienta a usar `--visivel`. O eProc, cuja janela abre sempre
  visível, faz o mesmo com o código do aplicativo autenticador
  (`eproc._esperar_codigo_na_janela`): espera, até o fim do prazo do login,
  a página sair da tela do código e volta ao laço do login (logado, perfil
  ou, com o código recusado, o novo pedido, até `MAX_CODIGOS`); prazo
  esgotado é `LoginFalhou` com o diagnóstico `eproc-codigo-prazo`. Senha e
  código nunca são lidos de arquivo.
* **Um download por pasta de lote.** A trava `_controle/.executando`
  (`motor.TravaDoLote`, `{pid, inicio, criado}`) recusa o segundo download
  na mesma pasta com `LoteEmAndamento` (código 2, `causa_erro`
  `lote_em_andamento`). Trava de processo morto (`motor.processo_vivo`:
  `OpenProcess` e `GetExitCodeProcess` no Windows) ou com mais de 48 h é
  desfeita, e também a do número que o sistema deu a outro programa depois
  que o download morreu: o processo com esse número começou noutro momento
  (`motor.momento_de_criacao`: `GetProcessTimes` no Windows,
  `/proc/<pid>/stat` no Linux) que o `criado` da trava ou, na trava sem
  ele, depois do `inicio` e da data do arquivo.
* **A pasta de sigilosos do lote** (`motor.pasta_sigilosos_do_lote`): o lote
  de `Processos/<nome>` usa `<sigilosos>/<nome>`, como sempre; o lote em
  outra pasta usa `<sigilosos>/<nome> (<8 hex do SHA-1 do caminho>)` e
  grava em `_controle/origem.txt` o lote de que é. A `<sigilosos>/<nome>`
  de versão anterior, sem o marcador, só é adotada pelo lote dono
  (conferido pelo relatório). O JSON diz qual é (`sigilosos_do_lote`).
* **O preparo do acervo ao fim** não roda quando o destino está fora do
  acervo, salvo se algo saiu do acervo durante o lote.
* **Códigos de saída:** 0 tudo certo; 1 parte falhou ou ficou pendente (ou
  Ctrl+C, também o que o motor engole no meio do lote e marca como
  `interrompido`: `causa_erro` `interrompido`); 2 nada pôde ser feito (uso
  errado, relação inválida, nenhum número, destino que não pode ser criado,
  pastas em conflito, lote em andamento, nenhum processo baixado nem já na
  pasta, erro inesperado). O `codigo_saida` do JSON é o código com que o processo sai:
  o erro inesperado não é relançado (sairia com 1); o rastro vai para o
  registro e para o `--log`, e quem chamou recebe a frase.

**O JSON (`helestron.baixar/1`).** O formato completo está no docstring de
`download/acompanhamento.py`; campos novos podem aparecer, e os existentes
não mudam de sentido. A gravação é atômica (`ARQ.parcial` + `os.replace`,
repetido se quem lê prende o arquivo), no máximo uma por segundo
(`INTERVALO_S`) e imediata em cada evento; a última traz `concluido: true` e
`codigo_saida`. Também é gravado na saída antecipada (uso errado, relação
inválida, sem processos, destino, pastas em conflito, lote em andamento,
Ctrl+C, erro inesperado), com `erro` e `causa_erro` (`uso`, `relacao_invalida`,
`sem_processos`, `destino`, `pastas_em_conflito`, `lote_em_andamento`,
`interrompido`, `inesperado`). No topo: `formato`, `versao`, `pid`, `inicio`,
`atualizado_em`, `concluido`, `codigo_saida`, `erro`, `causa_erro`, `grau`
(o do lote, `1g` ou `2g`, desde o primeiro JSON gravado: o construtor do
`Acompanhamento` começa com `1g`, e a CLI passa o do lote a todo
acompanhamento que cria, inclusive o primeiro do `--desanexar`, o da saída
sem relação e o do registro inacessível),
`destino`, `sigilosos_do_lote`, `relatorio`, `relatorio_completo`, `log`,
`status`, `navegador_visivel`, `progresso` (`feitos`, `total`,
`em_curso`), `aguardando` (o evento que espera o usuário, ou `null`),
`ultimo_evento`, `ignorados`, `ignorados_por_retomar`, `avisos`,
`sigilosos_no_acervo`, `resumo` (`total`, `baixados`, `ja_baixados`,
`falhas`, `pendentes`, `sigilosos`, `a_refazer`) e `processos`, na ordem da
relação. Cada processo: `ordem`, `numero` (o real, mesmo sigiloso),
`nome_arquivo` (o nome dos autos, sem extensão: o do PDF ou, sem PDF,
`cnj.nome_dos_autos`; no 2º grau, com ` (2G)`), `tribunal`, `sistema`,
`grau` (o dos autos, `1g` ou `2g`, sempre), `situacao` (`OK`, `JA_BAIXADO`,
`ERRO`, `NAO_ENCONTRADO`, `SEM_ACESSO`, `SIGILOSO_SEM_SENHA`,
`NAO_SUPORTADO`, `CANCELADO`, `PENDENTE`), `rotulo`, `sigiloso`, `pdf`,
`capa`, `capa_json`, `meta`, `texto`, `texto_situacao` (`novo`, `em_dia`,
`falhou`, `sigiloso_ignorado`, `nao_pedido`), `texto_erro`,
`paginas_sem_texto`, `paginas_sem_texto_pdf`, `paginas`, `documentos`,
`incompleto`, `paginacao` (`null` sem PDF; senão `garantida` e o essencial
do manifesto, `motor.essencial_da_paginacao`: `sistema`, `paginacao`,
`resumo`, `ultima` e `ausentes` e, no e-SAJ, `folhas_ausentes` e `origem`;
no eProc, `modo`, `documentos` e, no modo completo, `partes`; sem o
manifesto, ou com um que não descreve o PDF, `garantida` é `false`, com o
`resumo` e o resto `null`; no 2º grau, também `grau: "2g"`), `causa`,
`refazer`, `consultas` (no 2º grau, cada uma com `grau: "2g"`),
`detalhe`, `midias`, `segundos` e `data_hora`.

**Eventos** (`contexto.EVENTOS`; `Contexto.evento()` não faz nada na base e
nunca levanta; o `ContextoTerminal` os imprime com `--eventos` e os repassa
ao acompanhamento, cuja falha nunca derruba o lote):

| Evento | Dados |
|---|---|
| `lote_inicio` | `destino`, `relatorio`, `sigilosos_do_lote`, `total` |
| `grupo_inicio` | `sistema`, `tribunal`, `alternativo`, `ordens` |
| `navegador_ocupado` | `sistema`, `tribunal`, `ate` (ISO), `motivo` (`outro_download`: outro download usa o navegador; `copia_antiga_presa`: no modo certificado, a cópia antiga do perfil do Chrome ainda não pôde ser apagada): esperando o navegador do portal abrir |
| `login_aguardando` | `sistema`, `tribunal`, `modo`, `prazo_min`, `ate`, `motivo` (`certificado`, `manual`, `codigo`): publicado ANTES de esperar o usuário na janela |
| `acao_na_janela` | `sistema`, `tribunal`, `modo`, `prazo_min`, `ate`, `motivo` (`captcha`, `perfil`; eProc) |
| `login_concluido` | `sistema`, `tribunal` (só depois de um evento de espera) |
| `login_falhou` | `sistema`, `tribunal`, `detalhe` |
| `sessao_caiu` | `sistema`, `tribunal`, `ordem` |
| `fim` | `total`, `baixados`, `ja_baixados`, `falhas`, `pendentes`, `sigilosos`, `sigilosos_no_acervo` |

Cada linha leva também `tipo` e `momento` e, nos grupos do 2º grau, os
eventos `grupo_inicio`, `navegador_ocupado`, `login_aguardando`,
`acao_na_janela`, `login_concluido`, `login_falhou` e `sessao_caiu` levam
`grau: "2g"` (no 1º grau, o campo não vai; os dos portais o acrescentam
no `_evento` do `PortalESAJ` e do `PortalEProc`). `aguardando` (no JSON) é
preenchido em `login_aguardando`, `acao_na_janela` e `navegador_ocupado` e
limpo em `login_concluido`, `login_falhou`, `grupo_inicio`, `fim` ou quando
um item termina.

**O relatório e as causas.** `relatorio.csv` tem as colunas `ordem`,
`processo`, `tribunal`, `sistema`, `situacao`, `paginas`, `documentos`,
`arquivo`, `sigiloso`, `incompleto`, `detalhe`, `data_hora`, `causa`
(também nas linhas mascaradas; o CSV antigo, sem ela, continua lido e
mesclado) e, no fim, `grau` (1.1.0: `1g` ou `2g`, também na linha
mascarada; vazia no CSV de versão anterior, vale `cnj.grau_do_numero(n)
or "1g"`, `motor._grau_da_linha`, e a linha regravada a ganha). As linhas
se casam pela chave dos autos (`motor._chave_da_linha`: o processo e o
grau): o mesmo número no 1º e no 2º grau são duas linhas (seção 14.5). A
situação diz o que houve; a causa (`modelos.CAUSAS`), por quê:

| Causa | Quando |
|---|---|
| `login` | login recusado ou não concluído no prazo (o grupo inteiro) |
| `sessao` | a sessão caiu e não voltou depois das novas entradas |
| `portal` | portal fora do ar, sem rede, navegador que não abre (`motor.portal_fora`: só erro de conexão, `net::ERR_*`, tempo esgotado de navegação, `ECONN*`) |
| `portal_parou` | o portal parou de responder no meio do grupo (`MAX_INDISPONIVEL_SEGUIDOS`) |
| `navegador_ocupado` | outro download usa o navegador do portal, ou (no modo certificado) a cópia antiga do perfil do Chrome ainda não pôde ser apagada: o detalhe diz qual |
| `falha` | falha passageira que esgotou as tentativas (inclusive o arquivo provisório preso pelo antivírus) |
| `inesperado` | erro do programa (vai para o registro) |
| `pdf_aberto` | o PDF do lote está aberto noutro programa |
| `gravacao` | não foi possível gravar na pasta do lote ou na de sigilosos |
| `pdf_invalido` | o portal disse que baixou, mas o PDF não veio |
| `interrompido` | “Parar”, Ctrl+C ou lote encerrado antes |
| `sigilo_no_acervo` | processo sigiloso com autos presos no acervo |

`pede_nova_tentativa(situacao, causa)` (o `refazer` do JSON, da API e de
`ResultadoProcesso`) é verdadeiro para o pendente, o interrompido, todo
ERRO e o NAO_ENCONTRADO com causa (o sistema alternativo nem pôde ser
consultado: `consultas` traz `{sistema, consultado: false, causa,
detalhe}`); falso para OK, JA_BAIXADO, NAO_ENCONTRADO nos dois sistemas,
SEM_ACESSO, SIGILOSO_SEM_SENHA e NAO_SUPORTADO. (`ResumoLote.a_refazer`, que
alimenta “Tentar de novo” na janela, continua com a regra de antes.)

**O registro do download (`_controle/<número>_meta.json`).** Depois de
cada OK, `motor.gravar_meta` grava, ao lado do PDF final, `{formato:
"helestron.meta/1", versao, numero, sistema, tribunal, paginas, documentos,
incompleto, detalhe, paginacao, sigiloso, consultas, baixado_em}` (e
`grau: "2g"`, só nos autos do 2º grau, gravados como
`_controle/<número> (2G)_meta.json`). O
processo que já está na pasta (JA_BAIXADO) conserva o registro, das três
fontes, da menos para a mais confiável: a linha anterior do relatório, o
`_meta.json` e o manifesto do PDF (`paginacao.ler_do_pdf`, a fonte primária
do sistema, da paginação e, no e-SAJ, do `incompleto`). O manifesto que
não descreve o PDF (`textos.manifesto_confere`: página incluída ou
apagada depois do download) dá a paginação `{garantida: false, resumo}`
(`textos.resumo_da_paginacao`), a mesma do texto, que sai
`nao_garantida`; com `--rebaixar-incompletos`, esse PDF é baixado de
novo. O detalhe vira “já
estava na pasta (não baixei de novo); <detalhe anterior>”, sem os trechos
que só valiam para a rodada anterior; sem registro nenhum, “sem registro
do download anterior: paginação não conferida”. O PDF do e-SAJ sem
manifesto e sem `_meta.json` cuja linha anterior mostra sinal de numeração
deslocada (`incompleto` preenchido, “peça a peça” ou “confira” no detalhe)
é baixado de novo, com o detalhe “PDF de versão anterior com numeração
possivelmente deslocada”. A rodada que não troca o PDF que já estava na
pasta (falha ao baixá-lo de novo, item interrompido, grupo sem login, item
ainda pendente quando o programa é fechado à força) não apaga esse
registro: a linha dela leva o `incompleto` e os `documentos` da anterior e,
depois de “o PDF anterior continua na pasta”, o detalhe dela
(`_Lote._pdf_que_fica`), e a rodada seguinte a lê como a de um download que
deu certo. `SUFIXOS_CONTROLE` (`_capa.txt`, `_capa.json`,
`_meta.json`) acompanham o PDF quando ele muda de pasta
(`_levar_arquivos`, `retirar_do_acervo`).

### 5.2 `caminhos`, `--version` e `preparar`

* **`caminhos [--json]`** (`__main__._caminhos`): lê a configuração com
  `config.carregar(criar=False)` e não cria nada (nem o `config.ini`, nem
  `Logs`). Traz `versao`, `recursos`, `python` (`caminhos.python_exe()`),
  `instalacao`, `instalado`, `config`, `config_existe`, `logs`, `acervo`,
  `processos`, `transcricoes`, `sigilosos`, `pauta`, `separar_sigilosos`,
  `login` (`{esaj, eproc}`: `senha`, `certificado` ou `manual`, como o
  download lê), `espera_login_min`, `conflito_de_pastas` (a frase de
  `servicos.problema_nas_pastas`, a mesma com que o `baixar` recusa
  começar, ou vazio), `comando` (o `helestron.cmd` da pasta do programa,
  ou vazio) e `grau` (1.1.0: `cnj.normalizar_grau([download] grau)` ou
  `1g`, o grau padrão **da janela**; o `baixar` sem `--grau` usa `1g`, e a
  ajuda do `caminhos` o diz). Não expõe `PERFIS`, o cofre, a sessão nem a
  pasta `LOCAL`.
  `recursos` (`__main__.RECURSOS`) diz o que esta versão oferece a quem a
  automatiza; recurso novo vai no fim, e nenhum sai nem muda de sentido:
  `versao`, `caminhos`, `baixar.json`, `baixar.eventos`, `baixar.log`,
  `baixar.texto`, `baixar.retomar`, `baixar.completar`,
  `baixar.esperar-navegador`, `baixar.rebaixar-incompletos`,
  `baixar.sem-cofre`, `baixar.desanexar`, `relatorio.causa`,
  `relatorio.meta`, `paginacao.manifesto`, `preparar.pasta`,
  `preparar.json`, `folhas.fieis`, `texto.v2`, `capa.v2`,
  `texto.paginas-sem-texto`, `baixar.codigo-na-janela`,
  `baixar.pastas-em-conflito`, `comando.cmd`, `registro.hkcu` e, na 1.1.0,
  `baixar.grau` (o `--grau`, os campos `grau` do JSON, do CSV e do
  `caminhos`, os autos `<número> (2G).pdf`), `esaj.2g` (o 2º grau do e-SAJ,
  com o acesso do 1º) e `eproc.2g` (o eProc do 2º grau, com acesso
  próprio, `eproc2g:<SIGLA>`).
* **`--version`** (ou `--versao`): `Helestron <versão>`, código 0.
* **`preparar [--sem-texto] [--json]`**: `preparo.atualizar_contexto`. Os
  erros vão para a saída de erro (inclusive a frase dos sigilosos presos), e
  os avisos saem como “aviso: …”. Códigos: 0 tudo certo; 1 algum arquivo
  com problema; 2 uso errado; 3 autos de processo sigiloso presos no
  acervo (`SAIDA_SIGILOSO_NO_ACERVO`: não compartilhe até movê-los). O JSON
  traz `acervo`, `resumo`, `processos`, `transcricoes`, `textos_novos`,
  `sigilosos_levados`, `sigilosos_no_acervo`, `sigilosos_avisos`,
  `motivos`, `erros`, `avisos`, `pode_compartilhar` e `codigo_saida`.
* **`preparar --pasta PASTA [--texto-em DIR] [--incluir-sigilosos]
  [--json]`**: só o texto dos autos dos PDFs da pasta de lote, em
  `<PASTA>/_texto` (ou `--texto-em`, relativo à pasta ou absoluto); não
  grava `CLAUDE.md`, `AGENTS.md`, `INDICE.md` nem `Produtos`. Com a pasta
  ou o destino do texto (`--texto-em`) dentro do acervo, o processo
  sigiloso pela regra única fica de fora (`sigiloso_ignorado`); fora dele,
  o texto é gerado, e o item diz `sigiloso: true`. `--incluir-sigilosos`
  inclui os PDFs da pasta de sigilosos do lote, com o texto em
  `<sigilosos do lote>/_texto` (ou na subpasta relativa de `--texto-em`
  que fique dentro dela; nunca no acervo). Cada item: `pdf`, `grau` (1.1.0:
  `paginacao.grau` do manifesto do PDF e, sem manifesto válido,
  `cnj.grau_do_nome`), `texto`, `situacao`, `erro`,
  `sigiloso`, `paginas`, `paginacao` (sempre com `garantida`, que é
  `false`, com o `resumo`, sem o manifesto ou com um que não descreve o
  PDF: a mesma conferência do texto, `textos.manifesto_confere`),
  `paginas_sem_texto` e `paginas_sem_texto_pdf`. Códigos: 0, 1 (algum PDF
  falhou) ou 2 (pasta que não existe; `--texto-em` ou
  `--incluir-sigilosos` sem `--pasta`; `--sem-texto` com `--pasta`).

## 6. Servidor e API

### 6.1 Segurança

* Escuta **só em 127.0.0.1**, porta livre escolhida pelo sistema.
* **Token** aleatório (`secrets.token_urlsafe(32)`) por execução. A janela abre
  `http://127.0.0.1:PORTA/?t=TOKEN`; a página guarda o token em
  `sessionStorage`, remove-o da barra (`history.replaceState`) e o envia em
  **todo** pedido à API no cabeçalho `X-Helestron-Token` (no `EventSource`, que
  não manda cabeçalho, vai em `?t=`). Comparação em tempo constante.
* Recusa (403) pedido cujo `Host` não seja `127.0.0.1:PORTA` ou `localhost:PORTA`
  (contra DNS rebinding) e pedido com `Origin` diferente da própria origem.
  Sem CORS.
* Arquivos estáticos (`/`, `/css`, `/js`, `/img`, `/fontes`) sem token, só de
  dentro de `helestron/web` (normalizar caminho; recusar `..`).
* `/api/abrir` só abre pastas/arquivos dentro das pastas do usuário (acervo,
  sigilosos, pauta, Logs e a pasta da nuvem, mas nunca a raiz de uma
  unidade, como `D:\`) e URLs `https://`.
* Corpo JSON até 2 MB; envio de arquivo (multipart) com limite por rota
  (`Rota.limite_envio`, `Roteador.adicionar(..., limite_envio=)`): 500 MB
  (`rede.LIMITE_ENVIO` = `multipart.LIMITE_PADRAO`) para a relação e o
  relatório da pauta, e 20 GB (`api_audiencias.LIMITE_ENVIO_GRAVACAO`) para
  a gravação a transcrever. Antes de ler o corpo, o tamanho acima do limite
  dá 413 `envio_grande_demais`, com o limite legível (“passa de 20 GB”) e a
  orientação de escolher o arquivo pelo diálogo do Windows, que manda só o
  caminho; e o espaço livre do disco da pasta de envios
  (`rede.espaco_livre`) é conferido com `FOLGA_DISCO` (512 MB) de folga:
  sem espaço, 507 `espaco_insuficiente`, com o tamanho e o espaço livre. O
  disco que enche no meio também dá 507, e o pedaço gravado é apagado. O
  arquivo é gravado em `LOCAL/temp/envios`, em blocos de até 1 MB
  (`multipart.PEDACO_ARQUIVO`), nunca na memória, e apagado depois; um
  campo de arquivo repetido no mesmo envio é recusado
  (`multipart.EnvioInvalido`) sem deixar resto.
* O registro do servidor mascara o token (`rede.mascarar_token`,
  `Tratador.caminho_seguro`): `?t=***`, também no `log_message` e no
  `log_error`.

### 6.2 Envelope

Sucesso: `{"ok": true, "dados": ...}`. Erro: `{"ok": false, "erro": {"codigo":
"texto_curto", "mensagem": "frase para o usuário, em português", "detalhe":
"técnico, opcional"}}` com HTTP 400/403/404/409/500. A interface mostra sempre a
`mensagem`. Datas em ISO 8601 (`2026-10-03`, `2026-10-03T14:30:00`).

### 6.3 Endpoints

**Geral**
* `GET /api/estado` → `{nome, versao, modo: "janela"|"edge"|"navegador", pastas: {acervo, processos, transcricoes, sigilosos, pauta, logs}, pendencias: [{chave, titulo, mensagem, acao: "ajustes#acessos"|...}], resumo: {processos, transcricoes, ultimos_lotes: [{nome, quando, total, baixados, falhas, pasta}], transcricoes_recentes: [{numero, arquivo, quando}], pauta: {hoje, semana, proxima: Audiencia|null, ultima_sincronizacao, alteracoes_nao_vistas, fontes, configurada}}, tarefas: [Tarefa]}` (`semana` = de hoje a hoje + 6; `fontes` = quantas fontes cadastradas; `configurada`: contrato C5, seção 6.6). A `acao` de cada pendência é uma rota da interface (`pauta`, `ajustes#<grupo>`, com o grupo existente em Ajustes: a “Instalação incompleta” leva a `ajustes#sobre`); a pendência da pauta (`chave` `pauta_login`) é a do monitoramento (seção 8.7). As pendências do sigilo (seção 12) levam à tela Compartilhar (`acao` `compartilhar`) e trazem a lista `arquivos`: `sigilo` (“Processo sigiloso no acervo”, ou “Processos sigilosos no acervo”: autos presos, que travam o compartilhamento) e `sigilo-arquivos` (“Arquivo de processo sigiloso no acervo”, ou “Arquivos de processos sigilosos no acervo”: os outros arquivos presos, que só avisam). A pendência `nuvem` (“Pasta da nuvem em conflito”) traz a frase de `config.conflito_com_a_nuvem` (a pasta dos sigilosos ou a da pauta dentro da pasta da nuvem, igual a ela ou contendo-a; `acao` `ajustes#pastas`, ou `ajustes#compartilhar` quando é a nuvem que está dentro delas) ou a de `servicos.conflito_da_nuvem` (a nuvem dentro do acervo ou contendo-o: o espelho não roda).
* `GET /api/config` → `{valores: {secao: {chave: valor}}, esquema: [{secao, chave, tipo: "texto"|"flag"|"inteiro"|"pasta"|"escolha", rotulo, ajuda, opcoes?}]}`
* `POST /api/config` `{secao, chave, valor}` → `{valor}` (valida; pastas conflitantes → erro com a frase de `problema_nas_pastas`; a pasta da nuvem dentro do acervo ou contendo-o, e o acervo movido para dentro da nuvem já escolhida → 400 `pastas_em_conflito`, com a frase de `servicos.conflito_da_nuvem`; a pasta dos sigilosos ou a da pauta dentro da pasta da nuvem, igual a ela ou contendo-a, ou a nuvem dentro delas → 400 `pastas_em_conflito`, com a frase de `config.conflito_com_a_nuvem` — cada chave confere só a sua pasta. A pasta em branco é conferida como a pasta padrão que ela passa a valer, `caminhos.resolver(valor, "Acervo"|"Sigilosos"|"Pauta", base)`; a `pasta_nuvem` em branco continua sendo “não espelhar”. Número `inf`, `nan` ou `1e999` → 400 `valor_invalido`, e o `GET` com um desses no `config.ini` devolve o padrão)
* `GET /api/tribunais` → `[{sigla, nome, sistema, nome_sistema, suportado, alternativo, chave, graus, graus_alternativo}]` (`graus`: os graus em que o Helestron baixa do sistema principal, `["1g", "2g"]` onde `Tribunal.tem_grau("2g")`, senão `["1g"]`; `graus_alternativo`: os do sistema alternativo, só entre os do principal, porque o motor recusa o grau que o principal não tem: no TJSP, `["1g"]`. A tela os usa no “Adicionar acesso”, que oferece o eProc do 2º grau só onde o Helestron o baixa)
* `GET /api/acessos` → `[{portal, tribunal, sistema, grau, graus, rotulo, usuario, tem_senha, guardada, so_agora, modo}]` (`so_agora`: a senha foi digitada com “Lembrar neste computador” desligado e vale até fechar o programa, para o download e para a pauta; `portal` é `esaj:TJAL`, `eproc:TJAL` ou `eproc2g:TJAL`, a chave de `tribunais.RE_PORTAL`; `sistema`, `esaj` ou `eproc`, também na linha `eproc2g`; `grau`, o da credencial; `graus`, os que o “Testar” da linha testa: `esaj:TJAL` → `["1g", "2g"]`, `eproc:TJAL` → `["1g"]`, `eproc2g:TJAL` → `["2g"]`; `rotulo`, `Tribunal.rotulo`, como “TJAL · eProc (2º grau)”; `modo`, o de `[esaj] login` ou `[eproc] login`, que vale para os dois graus do sistema. A lista traz os portais do tribunal da unidade, os do 2º grau dele quando ele o tem e os do cofre: seção 14.4); `POST /api/acessos` `{portal, usuario, senha, lembrar?, modo?}` (aceita `eproc2g:<SIGLA>`; o tribunal sem o eProc do 2º grau dá 400 “O TJAM não tem o eProc do 2º grau no Helestron.”); `DELETE /api/acessos/{portal}` (o de `eproc2g:TJAL` apaga só o cofre, a sessão e os perfis do 2º grau); `POST /api/acessos/testar` `{tribunal, sistema?, grau?}` → `{tarefa}` (tipo `teste_login`; testa exatamente o portal pedido, no grau pedido, contrato C1: `grau` ausente é o 1º grau, e o corpo do 1º grau continua `{tribunal, sistema}`; grau inválido dá 400 `valor_invalido`, “Grau inválido (use 1g ou 2g).”, e o grau que o portal não tem, 400 `valor_invalido`, “O TJSP · e-SAJ não tem o 2º grau no Helestron.”; as credenciais são as de `Tribunal.portal` no grau: `esaj:TJAL` nos dois graus do e-SAJ, `eproc2g:TJAL` no eProc do 2º grau). Apagar o acesso, ou gravá-lo com outro usuário, apaga também a sessão guardada e os perfis do navegador do portal (`navegador.esquecer_portal`; o navegador aberto antes disso, também o de outro processo, não regrava a sessão ao fechar). Com o cofre preso ou em uso por outro processo (`cofre_senhas.CofreIndisponivel`), a resposta é 409 `arquivo_preso`, com a frase
* `GET /api/tribunais/enderecos` → `[{portal, grau, rotulo, url, rotulo_portal}]` (só os endereços corrigidos pelo usuário); `GET /api/tribunais/enderecos/{portal}` → `{portal, rotulo, enderecos: [{grau, rotulo, url, padrao, corrigido}]}`; `POST /api/tribunais/enderecos` `{portal, grau, url}` → o mesmo (url em branco volta ao catálogo). Os endereços são do sistema (`Tribunal.portal_do_sistema`): a linha `eproc2g:TJAL` abre os do eProc do TJAL (o `portal` da resposta é `eproc:TJAL`), e a correção sem `grau` feita por ela vale para o `2g`; o e-SAJ do TJAL lista, depois da `base`, o endereço da consulta de 2º grau (`2g`). É o “Endereço do portal” de Ajustes › Acessos aos portais: a correção fica em `LOCAL/enderecos-locais.json` e vale por cima de `dados/tribunais.json`, para o download e a pauta; as mensagens do motor sobre endereço mudado apontam para ela.
* `POST /api/dialogo/arquivo` `{titulo, tipos: ["Planilhas|*.xlsx;*.xls", ...]}` e `POST /api/dialogo/pasta` `{titulo, inicial}` → `{caminho|null}` (o de arquivo também `tamanho`, em bytes, ou `null`; diálogo nativo pela pywebview; fora dela → erro `sem_dialogo`, e a interface usa `<input type=file>`)
* `POST /api/abrir` `{tipo: "pasta"|"arquivo"|"url", alvo}`
* `GET /api/verificacao` → `[{nome, situacao: "ok"|"aviso"|"falha", detalhe, acao}]`; `POST /api/verificacao/completa` → `{tarefa}`
* `POST /api/encerrar`

**Tarefas e perguntas**
* `GET /api/tarefas`, `GET /api/tarefas/{id}` → `Tarefa = {id, tipo: "download"|"teste_login"|"transcricao_arquivo"|"modelo"|"preparo"|"pacote"|"nuvem"|"pauta_sincronizar"|"pauta_capturar"|"verificacao", titulo, estado: "rodando"|"concluida"|"falhou"|"parada", inicio, fim, progresso: {feitos, total, atual, percentual}, status, resultado, erro}`
* `POST /api/tarefas/{id}/parar`
* `POST /api/perguntas/{id}/responder` `{valor}`; `POST /api/perguntas/{id}/cancelar`

**Processos (download)**
* `POST /api/relacao/arquivo` — corpo `multipart/form-data` (campo `arquivo`) **ou** JSON `{caminho}` → `Leitura = {formato, origem, processos: [{numero, tribunal, sistema, alternativo, descricao, tem_senha, digito_confere, dependente, grau_fixo, graus}], avisos: [], corrompidos: [], sem_suporte: [{numero, motivo}]}` (`grau_fixo`: `"2g"` quando o próprio número impõe o 2º grau, `cnj.grau_do_numero`, senão `null`; `graus`: os graus que o Helestron baixa do sistema principal do processo)
* `POST /api/relacao/texto` `{texto}` → `Leitura`; `POST /api/relacao/link` `{url}` → `Leitura`
* `POST /api/download/iniciar` `{processos: [numero], senhas?: {numero: senha}, nome_lote, opcoes: {separar_sigilosos, rebaixar, navegador_visivel, grau}}` → `{tarefa}` (eventos `item` por processo). `opcoes.grau` é o grau do lote (`api_processos.grau_do_pedido`: `1g`, `2g`, `1`, `2`, `1º`, `2º`…); ausente ou em branco, vale o `[download] grau` dos Ajustes; outro valor dá 400 `valor_invalido`, “Grau inválido (use 1g ou 2g).”, antes de abrir a tarefa. A tela manda sempre o `grau` (também no “Tentar de novo”, contrato C9), e o `resultado` da tarefa traz `grau` (o do lote). Enquanto a pasta dos sigilosos ou a da pauta estiver dentro do acervo (ou o acervo dentro dela), recusa com 409 `pastas_em_conflito` (`api_processos.exigir_pastas_separadas`, com a frase de `servicos.problema_nas_pastas` e “Corrija em Ajustes › Pastas antes de baixar os processos.”); vale também para `POST /api/pauta/baixar-autos`, que passa por `iniciar_lote`. Cada item (`item_json`) traz também `causa` e `refazer`, os mesmos do relatório e do JSON da linha de comando (seção 5.1), e `grau`, o dos autos daquele processo (`1g` ou `2g`, sempre)
* `GET /api/download/lotes` → `[{nome, quando, total, baixados, falhas, pasta, relatorio}]`

**Audiências (transcrição)**
* `GET /api/transcricao/microfones` → `[{indice, nome, padrao}]` (a interface usa o `nome`: contrato C2)
* `POST /api/transcricao/microfone/teste` `{dispositivo}` (nome, número ou `""` = padrão do Windows; sem a chave, o da configuração; eventos `microfone_nivel`; microfone que não existe mais, ocupado ou ausente → 409 `microfone_indisponivel` com a frase do motor; durante a audiência → 409 `sessao_ativa`) ; `POST /api/transcricao/microfone/parar`
* `GET /api/transcricao/modelos` → `[{nome, rotulo, tamanho_mb, instalado, embutido, recomendado_para, descricao}]`; `POST /api/transcricao/modelos/baixar` `{nome}` → `{tarefa}`
* `GET /api/transcricao/falantes` → `{disponivel, situacao, biblioteca, modelos, embutidos, tamanho_mb}` (separação automática de falantes); `POST /api/transcricao/falantes/baixar` → `{tarefa}` (tipo `modelo`: baixa do GitHub, uma vez, os modelos de voz que faltarem, por `servicos.instalar_falantes`; a biblioteca `sherpa-onnx` vem sempre no instalador, e sem ela a resposta é 409 pedindo a reinstalação). Os modelos de voz vão embutidos pela construção; a tela Ajustes › Transcrição mostra o botão “Baixar os modelos de voz” só quando faltarem (construção `--sem-falantes`).
* `POST /api/transcricao/iniciar` `{processo, dispositivo, sigiloso, tipo, participantes: {"F1": "Juiz(a)", ...}, falante}` → `{sessao, processo, sigiloso, sigiloso_forcado, motivo?}` (`dispositivo` como no teste do microfone, conferido antes de gravar; `sigiloso_forcado`/`motivo`: contrato C4; já há sessão → 409 `sessao_ativa`; `processo` aceita o dependente como `/01` ou `-01`, lido por `cnj.ler_nome_arquivo`, e a tela o manda com o sufixo, `…/01`)
* `POST /api/transcricao/pausar` · `/retomar` · `/falante` `{falante}` · `/encerrar` `{tipo?, refinar?}` → `{documento}` (a sessão é única; o `tipo` do encerrar vai para a ficha do documento e da revisão, contrato C8)
* `GET /api/transcricao/estado` → `{sessao|null, estado, segundos, processo, falas: [...]}`
* `GET /api/transcricao/recuperaveis` → `[{arquivo, processo, quando}]`; `POST /api/transcricao/recuperar` `{arquivo}` → `{documento}` (como no fim da audiência, refaz o `INDICE.md` e, se ligado, o espelho na nuvem)
* `POST /api/transcricao/gravacao` (multipart `arquivo` ou JSON `{caminho}`, mais `processo`, `sigiloso`, `tipo`, `revisao`; no multipart, também `nome_original` e `data_arquivo`) → `{tarefa, sigiloso, sigiloso_forcado, motivo?}` (contratos C4 e C8; a revisão leva a ficha da sessão ao vivo, `meta`: data, início e término, com o tipo do pedido prevalecendo). O envio pela página vai até 20 GB (`LIMITE_ENVIO_GRAVACAO`, seção 6.1); com outra transcrição de gravação rodando, o multipart é recusado com 409 `ocupado` ANTES de o corpo ser lido. O diálogo do Windows manda só o `caminho`, sem limite. O arquivo não é recusado pela extensão: a decodificação (PyAV) diz, na tarefa, se falta a trilha de áudio, se o arquivo está cortado ou não é mídia, ou se é protegido por DRM (seção 7.2). O número aceita o dependente (`/01` ou `-01`; `audiencia.numero_da_gravacao`: o número do nome do arquivo ou da pasta, mantendo o dependente quando o digitado é o mesmo principal sem ele). Na tarefa e no andamento, o nome do temporário do envio é trocado pelo nome original do arquivo
* `GET /api/transcricao/recentes` → `[{numero, arquivo, quando, sigiloso}]`

**Pauta** (seção 8)
* `GET /api/pauta?de=&ate=&sistema=&situacao=&busca=` → `{audiencias: [Audiencia], resumo: {total, hoje, semana, por_situacao: {}, por_tipo: {}}, ultima_sincronizacao, monitoramento: {ativo, intervalo_horas, proxima}}`
* `GET /api/pauta/fontes` → `[{id, tribunal, sistema, rotulo, modo, url, menu, monitorada, exige_presenca, motivo_presenca, ultima_sincronizacao, ultimo_erro, criada_em}]` (`monitorada` = tem rota lembrada e entra no portal sozinha, logo entra no monitoramento; `exige_presenca`/`motivo_presenca` = o login só acontece com a pessoa à frente, e por quê: seção 8.7); `POST /api/pauta/fontes` `{tribunal, sistema, rotulo, url?}`; `DELETE /api/pauta/fontes/{id}`
* `POST /api/pauta/sincronizar` `{fontes?: [id], de?, ate?}` → `{tarefa}`; o `resultado` da tarefa é `{novas, atualizadas, canceladas, removidas, total, alteracoes, fontes: [...], erros: [{fonte, rotulo, mensagem}], avisos: [texto], periodo}` (cada item de `fontes` traz também `paginas`, `url`, `periodo_aplicado` e `incompleta`, o motivo de a leitura ter parado antes do fim, `""` se leu tudo: seção 8.3) e o `status` final, a frase pronta (“8 audiências conferidas · 1 nova…”). Quando a sincronização revela processos em segredo de justiça que o programa ainda não tratava como sigilosos, o `resultado` traz também `sigilosos_novos` (os números, como a pauta os mostra), e o servidor tira do acervo o que houver deles (seção 12). Uma fonte que falha não derruba as outras (e, se outras deram certo, vira também um aviso com o motivo); só quando todas falham a tarefa termina como `falhou`, com cada fonte e o motivo no erro. A tela da Pauta mostra o resultado numa faixa que fica à vista (fontes com problema, avisos e as saídas: Capturar no portal, Importar relatório, Acessos aos portais).
* `POST /api/pauta/capturar` `{tribunal, sistema}` → `{tarefa}` (captura assistida, seção 8.4); `resultado` = `{novas, atualizadas, capturadas, telas, url, motivo: "concluida"|"fechada"|"prazo", fonte}`, mais `sigilosos_novos`, como na sincronização
* `POST /api/pauta/importar` (multipart `arquivo` ou JSON `{caminho}`) → `{novas, atualizadas, ignoradas, avisos, total, arquivo}` (`arquivo` = o nome que o usuário escolheu), mais `sigilosos_novos`, como na sincronização
* `POST /api/pauta/exportar` `{de, ate, sistema?, situacao?, busca?, incluir_partes_sigilosos?}` → `{arquivo}` (`incluir_partes_sigilosos` presente vale como veio, `true` ou `false`, inclusive o `false` com o ajuste ligado; ausente, vale `[pauta] incluir_partes_sigilosos`)
* `GET /api/pauta/alteracoes?desde=` → `[{quando, tipo: "nova"|"alterada"|"cancelada"|"removida", audiencia, campos: [{campo, antes, depois}]}]`; `POST /api/pauta/alteracoes/vistas`
* `POST /api/pauta/monitoramento` `{ativo, intervalo_horas}`
* `POST /api/pauta/baixar-autos` `{ids?: [], de?, ate?}` → `{tarefa}` (lote de download com os processos, sempre do 1º grau: a pauta é de audiências do 1º grau, e o lote vai com `grau: "1g"`, seja qual for o dos Ajustes; o número que só existe no 2º grau vai ao 2º)

**Compartilhar com IA** (as ações recusam com 409 `sigiloso_no_acervo` enquanto os **autos** de um processo sigiloso, um PDF dele fora de `Produtos\`, estiverem presos no acervo, e os outros arquivos presos só avisam; as que entregam o acervo — preparar, abrir o Cowork, o Claude Code, o ChatGPT Work ou o Codex, o pacote e o espelho na nuvem — começam pelo preparo, que tira do acervo o processo sigiloso, e, nas tarefas, o que não puder sair faz a tarefa falhar com a mesma frase: seção 12. Antes disso, preparar, Cowork, Claude Code, ChatGPT Work, Codex e o espelho recusam com 409 `pastas_em_conflito` enquanto a pasta dos sigilosos ou a da pauta estiver dentro do acervo, ou o acervo dentro delas — `api_compartilhar.exigir_pastas_separadas`, com a frase de `servicos.problema_nas_pastas` —, e nenhuma abertura nem preparo acontece: as ferramentas que leem a pasta direto leriam os sigilosos, e o `CLAUDE.md` diria que eles não estão ali; o espelho automático também pula, com aviso no registro)
* `GET /api/compartilhar/estado` → estado de cada destino (`servicos.estado_ia`), mais `sigilosos_avisos` (os arquivos de processo sigiloso que ficaram no acervo sem travar nada)
* `POST /api/compartilhar/preparar` → `{tarefa}`; o `resultado` da tarefa `preparo` traz também `avisos` (as frases sobre os arquivos que só avisam)
* `POST /api/compartilhar/claude-desktop` (conectar o acervo) · `/cowork` · `/claude-code` · `/chatgpt-work` · `/codex` → `{mensagem, abriu}`, mais `copiar` no Cowork (o pedido inicial) e no ChatGPT Work (o caminho do acervo), e `{pagina_aberta, url}` quando o programa precisou abrir uma página no navegador: o Claude Code ausente e o Claude Desktop ausente (também no Cowork), com `instalado: false`, e o ChatGPT Work sem o app, com `resultado: "web"` (contratos C6 e C7)
* `POST /api/compartilhar/pacote` `{numeros?}` → `{tarefa}`; o `resultado` (`api_compartilhar.concluir_pacote`, a partir de `chatgpt.Pacote`) é `{pasta, arquivo, mensagem, avisos, faltaram, grande_demais, tamanho_mb}`: os avisos (o número pedido que não está no acervo, ou é sigiloso; o arquivo ou o `.zip` acima de `LIMITE_ARQUIVO_MB`, 500 MB; o pacote antigo que não pôde perder o sigiloso) vão para a tela (`tw.avisar`, “Pacote para o ChatGPT”) e para a mensagem; com `grande_demais`, a mensagem e o status mandam arrastar os arquivos da pasta do pacote, e não o `.zip`. O status é “Pacote pronto.” ou “Pacote pronto, com N avisos.”
* `GET /api/compartilhar/nuvem` → `[{rotulo, caminho}]`; `POST /api/compartilhar/nuvem/espelhar` `{destino}` → `{tarefa}` (o destino só é gravado em `[compartilhar] pasta_nuvem` depois de todas as conferências; dentro do acervo ou contendo-o, ou com a pasta dos sigilosos ou a da pauta dentro dele, igual a ele ou contendo-o → 400 `pastas_em_conflito`). O `resultado` (`api_compartilhar.concluir_espelho`, a partir de `nuvem.Espelho`) é `{copiados, iguais, resumo, nao_copiados: [{arquivo, motivo}], pasta}`; o status é o resumo (“2 copiados, 5 sem mudança, 1 NÃO copiado (X.pdf: motivo)”), e os arquivos não copiados geram um aviso na tela, com o caminho dentro do acervo e a dica (fechar o arquivo aberto; encurtar o nome da pasta do lote, se o caminho ficou longo demais na nuvem), terminando por “Espelhar agora”. O mesmo vale para o espelho automático, do fim do lote e da transcrição
* `GET /api/compartilhar/prompt` → `{texto}`

### 6.4 Eventos (`GET /api/eventos?t=TOKEN`, Server-Sent Events)

Cada evento: `event: <tipo>` + `data: <json>`. Tipos:

| tipo | dados |
|---|---|
| `tarefa` | `Tarefa` (sempre que muda) |
| `item` | `{tarefa, numero, situacao, rotulo, mensagem, arquivo, sigiloso, paginas, tribunal, sistema, ordem, causa, refazer, grau}` (download; `causa` e `refazer`: seção 5.1; `grau`: o dos autos, seção 14) |
| `log` | `{tarefa?, nivel: "info"|"aviso"|"erro", texto, hora}` |
| `pergunta` | `{id, tarefa, tipo: "codigo"|"confirmar"|"texto"|"escolha", titulo, mensagem, opcoes?, prazo_s}` |
| `pergunta_fechada` | `{id, motivo}` |
| `aviso` | `{titulo, mensagem, nivel, tarefa?}` (`tarefa`: o aviso é de uma tarefa; a interface não o repete quando a tela aberta já mostra o resultado dela). Quando a pauta revela o sigilo de processo com arquivos no acervo, o título é “Processo em segredo de justiça” (ou “Processos em segredo de justiça”), com `nivel` “aviso” e a frase de `frase_sigilo_revelado` (seção 12) |
| `transcricao` | `{tipo: "estado"|"nivel"|"fala"|"atraso"|"aviso"|"erro"|"salvo"|"fim", dados}` (`fala` = `{inicio, fim, falante, texto}`; `estado` = `{texto, estado}`, e `estado: "erro"` com `fase: "inicio"|"fim"` quando a sessão acaba com erro — sem microfone, a gravação não começa e a tela volta à preparação com o motivo) |
| `microfone_nivel` | `{nivel}` (0..1) |
| `pauta` | `{tipo: "atualizada"|"alteracoes", dados}` |
| `estado` | `{}` — algo do resumo mudou; a interface relê `/api/estado` |
| `ping` | a cada 15 s |

### 6.5 Perguntas

O motor pede um dado ao usuário (código enviado por e-mail, código de dois
fatores, confirmação) chamando o contexto da tarefa, que **bloqueia** a thread de
trabalho num `threading.Event` (padrão de `helestron/tarefas.py`). O servidor
publica `pergunta`; a interface abre uma folha (sheet) e responde em
`/api/perguntas/{id}/responder`. Prazo esgotado, tarefa parada ou cancelamento
fecham a pergunta (`pergunta_fechada`). A cada `pergunta` publicada, o
servidor também chama quem pediu para saber (`Aplicacao.registrar_atencao`,
contrato C3): a janela própria vem para a frente e pisca na barra de tarefas;
no Edge e no navegador, a página alterna o título enquanto a pergunta espera.

### 6.6 Contratos entre a interface, o servidor e o motor (C1–C9)

Combinados na revisão da versão 1.0.0; cada lado tolera a falta do outro
(campo ausente, função ausente), e os testes conferem os dois lados.

* **C1 — Testar o acesso certo.** `POST /api/acessos/testar` recebe
  `{tribunal, sistema?}`, com `sistema` “esaj” ou “eproc”; outro valor → 400
  `valor_invalido`; sem `sistema`, vale o portal principal do tribunal (o
  e-SAJ no TJAL). A tela manda o sistema da linha (no TJAL, no TJSP e no
  TJAC os dois portais existem), e a tarefa `teste_login` tem o título do
  portal exato (“Testar o acesso ao TJAL · eProc”). Em Ajustes › Acessos
  aos portais, “Testar” e “Alterar” (ou “Cadastrar”) são botões irmãos numa
  linha que não é botão, e o resultado aparece na própria linha (“Testando o
  acesso…”, “Acesso confirmado às HH:MM.”, “O teste falhou. …”); o aviso do
  fim dessa tarefa não aparece enquanto a tela está aberta. Desde a 1.1.0,
  o pedido aceita também `grau` (`1g` ou `2g`; ausente, o 1º grau, com o
  corpo e o título de antes), e o teste roda no Tribunal do portal no grau
  pedido (`api_geral.no_grau_pedido`, `Tribunal.no_grau`), pelas mesmas
  fábricas do motor: o 2º grau do e-SAJ entra pelo login de sempre e abre a
  consulta de 2º grau (o `entrar()` do `PortalESAJ` no 2º grau passa pela
  porta de entrada dela e confere que ela abriu); o do eProc abre o perfil
  `eproc2g-<SIGLA>` com a senha de `eproc2g:<SIGLA>`. A linha com `graus` de
  dois itens (o e-SAJ do TJAL) tem os botões “Testar 1º grau” e “Testar 2º
  grau”, e o resultado é guardado por portal e grau (“2º grau: Acesso
  confirmado às HH:MM.”); a de um item tem “Testar”, como antes. A tela só
  manda `grau` no 2º grau, usa `sistema` e `tribunal` da resposta do
  `GET /api/acessos` (a chave `eproc2g:TJAL` não diz o sistema pelo
  prefixo) e oferece “Testar” também nos modos certificado e manual (o
  navegador abre e espera o usuário entrar). O título do 2º grau é “Testar
  o acesso ao TJAL · e-SAJ (2º grau)”, e a mensagem, “Acesso ao TJAL · e-SAJ
  (2º grau) confirmado.”.
* **C2 — Microfone pelo nome.** `[transcricao] dispositivo` guarda o
  **nome** do microfone (`""` = padrão do Windows): o número muda quando se
  liga ou desliga um aparelho USB. A configuração antiga, só com dígitos, é
  convertida no nome do mesmo aparelho e regravada. Em `iniciar` e no teste,
  `dispositivo` é nome, número ou `""`; sem a chave, vale o da configuração; o
  `""` vai explícito para a sessão (não herda o `config.ini`).
  `microfone.conferir` confere antes de gravar: nome que não existe mais →
  `MicrofoneNaoEncontrado` (“O microfone ‘X’ não foi encontrado. Escolha
  outro em Audiências ou Ajustes › Transcrição.”; aqui, as aspas simples
  marcam as aspas “ ” que a frase põe no nome); sem nenhum microfone, a
  frase `SEM_MICROFONE` (“Nenhum microfone foi encontrado. Ligue o microfone
  (ou o fone com microfone) e tente de novo. Se ele estiver ligado, confira
  em Configurações do Windows › Sistema › Som › Entrada.”); o servidor
  traduz os dois (e o microfone ocupado) em 409 `microfone_indisponivel`, e
  a tela mostra a frase e recarrega a lista. A tela mostra o nome que sumiu
  como “Não encontrado: X” (no início do rótulo: no fim, a caixa estreita o
  cortava), com a nota “O microfone ‘X’ não foi encontrado neste computador.
  Ligue-o ou escolha outro.”, e nunca o troca em silêncio pelo padrão.
  Enquanto a lista mostra “Carregando os microfones…”, Gravar e Testar ficam
  desativados. A `Captura` procura o nome de novo a cada abertura e, se
  outro aparelho abrir no lugar do escolhido, avisa (evento `transcricao` de
  tipo `aviso`: “O microfone ‘X’ não abriu (desligado, ou em uso por outro
  programa); a gravação segue pelo ‘Y’. Confira o microfone em
  Audiências.”). Ajustes › Transcrição tem a lista “Microfone”, com a mesma
  regra e a mesma nota.
* **C3 — Pedido de código que chama atenção.**
  `Aplicacao.registrar_atencao(funcao)` guarda a função (sem repetir); a
  cada `pergunta`, cada função registrada roda numa thread própria, dentro
  de `try` (uma que falha não impede as outras; `pergunta_fechada` não
  chama). A `JanelaWebview` registra `chamar_atencao`, que só age se ainda
  for a janela ativa: `IsIconic` → `ShowWindowAsync(SW_RESTORE)`,
  `SetForegroundWindow` e `FlashWindowEx(FLASHW_ALL | FLASHW_TIMERNOFG)`. No
  Edge e no navegador (modo diferente de “janela”), a página não alcança a
  janela: com pergunta pendente e a página sem foco, o título alterna a cada
  segundo com “Código pedido — Helestron” (ou “Pergunta à espera —
  Helestron”) até a pergunta ser respondida ou fechada.
* **C4 — Sigilo vindo da pauta.** `ServicoPauta.processo_sigiloso(numero)`
  (número em texto, em qualquer grafia, ou `Numero`) é verdadeiro se alguma
  audiência daquele processo, em qualquer registro (do portal, do relatório
  importado, já fora da pauta), está marcada sigilosa (`Armazem.sigilosas`).
  Ela compara o número exato, sem a herança do incidente: na transcrição, a
  herança vem da regra única (seção 12), que
  `servidor/audiencia.sigilo_conhecido` consulta por último e que diz quando
  o sigilo vem do principal (“Este processo é incidente de um processo
  sigiloso: …”).
  Na transcrição (`servidor/audiencia.py`, `sigilo_da_audiencia`), o pedido da
  página só **acrescenta** sigilo: vale `servicos.processo_sigiloso` (autos,
  transcrição, gravação ou diário do processo na pasta dos sigilosos), a
  pauta, ou a gravação guardada na pasta dos sigilosos (no envio pela página,
  um arquivo de mesmo nome e tamanho lá): é a regra única do sigilo
  (seção 12), mais a gravação. A resposta de `iniciar` e de `gravacao` traz
  `{sigiloso, sigiloso_forcado, motivo?}`; se a pauta falhar, a audiência
  segue. A tela consulta a pauta (`GET /api/pauta` com `busca` = número, de um
  ano para trás a um ano para a frente) quando o número fica válido e, se ele
  for sigiloso, liga o interruptor com o motivo (“A pauta de audiências indica
  que este processo corre em segredo de justiça.”); só desliga o que ela mesma
  ligou, quando o número muda. Com `sigiloso_forcado`, a tela liga o
  interruptor e mostra o motivo na barra ao vivo (ou no cartão da gravação
  enviada).
* **C5 — Primeiros passos da pauta.** `resumo_inicio()` devolve também
  `fontes` (quantas cadastradas) e `configurada`: verdadeiro se há fonte
  cadastrada, se já houve sincronização, captura ou importação (meta
  `ultima_importacao`) ou se o banco já tem alguma audiência.
  `GET /api/estado` repassa os dois em `resumo.pauta` (com uma pauta antiga,
  sem os campos, completa `fontes` por `fontes()` e `configurada` por fonte ou
  sincronização). O Início só dá o passo “Configurar a pauta de audiências”
  por feito com `configurada`; pendente, ele tem o botão “Configurar”. O
  cartão “Primeiros passos” aparece mesmo sem pendência do servidor e sai
  quando tudo está feito. “Hoje na pauta” usa o mesmo critério: sem audiência
  e sem pauta configurada, “A pauta ainda não foi configurada”, com o botão
  “Configurar a pauta”; configurada, mas nunca sincronizada, “A pauta ainda
  não foi sincronizada” só com fonte cadastrada (a pauta configurada só por um
  relatório importado não tem fonte para sincronizar); fora disso, “Nenhuma
  audiência hoje”, com a próxima.
* **C6 — Ferramenta ausente abre a página oficial.**
  `POST /api/compartilhar/claude-code` sem o Claude Code abre
  `claude.URL_DOC_CODE` no navegador padrão (`sistema.abrir_endereco` devolve
  se abriu) e responde
  `{abriu: false, instalado: false, pagina_aberta, mensagem, url}`; sem
  navegador, a mensagem traz o endereço. O Claude Desktop ausente faz o mesmo
  com a página de download (`claude.URL_DOWNLOAD_DESKTOP`), no “Conectar o
  acervo” e no “Abrir no Cowork”. O Cowork responde
  `{abriu: false, resultado: "baixar", instalado: false, pagina_aberta}`, mais
  `url`, `mensagem` e `copiar`: “O Claude Desktop não está instalado: abri no
  navegador a página de download. Instale o app, entre com a sua conta (o
  Cowork exige plano pago) e tente de novo.” ou, sem navegador, “O Claude
  Desktop não está instalado. Baixe-o em https://claude.ai/download,
  instale-o, entre com a sua conta (o Cowork exige plano pago) e tente de
  novo.”. O ChatGPT Work sem o app do ChatGPT para Windows abre
  `chatgpt.URL_CHATGPT` aqui mesmo e responde
  `{abriu, resultado: "web", pagina_aberta, url, copiar, mensagem}`: “O
  ChatGPT abriu no navegador, que não lê pastas do computador. Instale o app
  do ChatGPT para Windows para usar o modo Work com o acervo — ou, no cartão
  ‘Pacote para o ChatGPT’, ‘Gerar o pacote’.” ou, sem navegador, “Não consegui
  abrir o ChatGPT no navegador (https://chatgpt.com/). Pelo navegador, ele não
  lê pastas do computador. …”. Com `pagina_aberta: false`, a folha da tela
  oferece os botões “Abrir a página” (`POST /api/abrir` com `tipo` “url”) e
  “Copiar o endereço” (que funciona sem navegador nenhum); se “Abrir a página”
  também não abrir o navegador, o servidor responde 409 `navegador_nao_abriu`
  (“Não consegui abrir o navegador. Copie o endereço e cole-o no navegador:
  …”, com o endereço), e a folha de erro tem o título “O navegador não abriu”.
  As mensagens só citam botões que existem (o Codex ausente aponta “Abrir no
  ChatGPT Work” e “Gerar o pacote”).
* **C7 — Cowork e ChatGPT Work copiam na hora do clique.** A tela lê o
  pedido inicial (`GET /api/compartilhar/prompt`) ao abrir. No clique de
  “Abrir no Cowork” (o pedido inicial) e de “Abrir no ChatGPT Work” (o
  caminho do acervo), `navigator.clipboard.writeText` começa antes de
  qualquer espera de rede, com reserva por `execCommand("copy")`; só depois
  a API é chamada (o app externo toma o foco, e o navegador recusaria a
  cópia). Sem o texto à mão, vale o `copiar` da resposta; se nada der certo,
  a folha mostra o texto num campo, com o botão “Copiar”.
* **C8 — A ficha da audiência.** `POST /api/transcricao/encerrar` aceita
  `{tipo}` e o grava em `sessao.meta.tipo`; `GerenteAudiencia.ultima` guarda
  o tipo e os participantes. A revisão (`gravacao` com `revisao`) usa o `tipo` do pedido
  ou o da sessão, mais os participantes. A tela manda o tipo com que ela
  começou a sessão (depois de recarregar a página, nada: vale o do
  servidor). O modo “Arquivo de áudio ou vídeo” (cartão “Transcrever uma
  gravação”, seção 7.2) tem o seletor “Tipo de
  audiência” e, no envio pela página (o servidor só vê um temporário), manda
  `nome_original` e `data_arquivo` (a data da última modificação do
  arquivo, em ISO 8601; o servidor aceita também milissegundos); sem
  `data_arquivo`, a data vem do nome do arquivo
  (`<número> 2026-09-15 14h00.flac`). `servicos.transcrever_gravacao` recebe
  `gravacao`, `data` e, na revisão, `meta` (a ficha da sessão ao vivo,
  guardada por `audiencia._ficha_da_ultima` em `ultima["meta"]`, com as
  teclas F1–F8 à parte, em `ultima["botoes"]`) e monta a `MetaAudiencia`
  (`_ficha_da_revisao`: a ficha copiada, com a origem “revisão”; tipo,
  gravação e data informados prevalecem; os participantes se somam; a
  ficha guardada não muda). A ficha do DOCX lista em “Participantes” quem
  falou, na ordem em que apareceu, com o nome informado para o papel, e
  depois os demais papéis informados (`documento.participantes_da_ficha`);
  chave de tecla (`F1`…`F8`) nunca vai à ficha.
* **C9 — Relatório do lote mesclado.** “Tentar de novo” manda o **mesmo**
  `nome_lote` (o da pasta do lote que terminou, não o do rascunho da tela),
  só os `a_refazer` e `rebaixar: false`. O motor (`download/motor.py`,
  `_Lote`) lê o relatório anterior da pasta (o mais recente entre
  `relatorio.csv` e `relatorio (atualizado).csv`; a linha mascarada
  “(processo sigiloso)” é casada, pela ordem, com a do relatório completo da
  pasta de sigilosos) e grava a mescla: as linhas refeitas no lugar das
  antigas, as demais como estavam e as novas no fim, com a ordem
  renumerada. O relatório do acervo continua mascarado, e o completo vai
  para a pasta de sigilosos do lote (`pasta_sigilosos_do_lote`, seção 5.1).
  A coluna `causa` vai no fim (desde a 1.1.0, seguida só de `grau`), também
  nas linhas mascaradas, e o relatório antigo sem ela é lido e mesclado.
  Desde a 1.1.0, o “Tentar de novo”
  manda também o grau do lote que terminou (`grau: res.grau`, o `grau` do
  `resultado` da tarefa), e não o do rascunho da tela: depois de recarregar
  a página o rascunho é nulo (o servidor usaria o dos Ajustes), e o lote da
  Pauta, sempre do 1º grau, refeito com o rascunho em 2º grau iria ao 2º.
  As linhas se casam pela chave dos autos (o processo e o grau: seção
  5.1).

## 7. Interface (`helestron/web`)

### 7.1 Princípios

* **iOS / iPadOS**: barra lateral translúcida (vidro), títulos grandes, cartões
  com cantos de 20 px, listas agrupadas (“inset grouped”), controles segmentados,
  interruptores, folhas modais com fundo desfocado, avisos discretos (toasts),
  ícones de traço arredondado.
* **Cores** (tokens CSS em `:root`):
  `--navy-900 #0B1A33`, `--navy-800 #12284A`, `--navy-700 #1B3560`,
  `--azul #0A66E8` (ação principal), `--azul-claro #4C8DFF`, `--azul-fundo #E8F1FF`,
  `--cinza-900 #1C1C1E`, `--cinza-600 #6B7280`, `--cinza-400 #A1A7B3`,
  `--cinza-200 #E5E7EB`, `--cinza-100 #F2F4F7`, `--branco #FFFFFF`,
  `--verde #1F9D55`, `--ambar #C27C0E`, `--vermelho #D93A3A` (gravar, erro).
  Vidro: `background: rgba(255,255,255,.62); backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid rgba(255,255,255,.7); box-shadow: 0 8px 32px rgba(11,26,51,.08)`.
  Fundo da janela: gradiente suave branco→azul-gelo com 2–3 manchas desfocadas
  (azul e navy em baixa opacidade), para o vidro “aparecer”.
* **Quadrados de ícone só em azul e cinza** (como os Ajustes do iOS em
  monocromia azul). Os blocos `.cor-*` do CSS (`bloco-icone`) são só azuis,
  navy e cinzas: `cor-azul`, `cor-celeste`, `cor-ciano`, `cor-cobalto`,
  `cor-aco`, `cor-navy`, `cor-ardosia` e `cor-cinza` (não há mais índigo,
  verde, âmbar nem vermelho). O ícone branco tem contraste de 3:1 ou mais
  (WCAG 1.4.11) na faixa de 20 % a 80 % da altura do quadrado, por onde
  passa o traço. O tom distingue o assunto e é o mesmo em todas as telas:
  Baixar (download) navy, Transcrever azul, Pauta ciano, Compartilhar/IA
  cobalto, Pastas celeste, Acessos aço, Unidade e sigilo ardósia,
  Diagnóstico cinza; as oito seções de Ajustes têm tons diferentes entre si.
* **Verde, âmbar e vermelho só dizem estado** (ou ação destrutiva): pontos,
  pílulas, faixas de aviso, erro e ok, avisos (toasts), o anel do resultado
  do lote, as folhas de erro (“A gravação não começou”, com o ícone
  vermelho) e de alerta, o medidor de nível, o selo vermelho de alterações
  não vistas, os passos feitos (verde) dos Primeiros passos, o botão de
  gravar, o Encerrar e os botões de perigo. O ponto do selo do tipo de
  audiência (`COR_TIPO`, em `componentes.js`) é em tons de azul e cinza, sem
  cor de estado: antes, Custódia vermelha, Justificação âmbar e Mediação
  verde pareciam erro, aviso e “pronto” na lista da Pauta. Os testes
  `PaletaAzulCinzaBranco` (`testes/test_web_contrato.py`) e
  `test_quadrados_de_icone_so_em_azul_navy_e_cinza`
  (`testes/test_web_interface.py`) conferem a regra.
* **Tipografia**: Inter (variável, embutida em `web/fontes/`, licença OFL junto),
  com reserva `"Segoe UI Variable", "Segoe UI", system-ui`. Título grande 32–34 px
  semibold; corpo 15 px; números de processo em `font-variant-numeric: tabular-nums`.
* **Claro e limpo**: um assunto por tela; ação principal sempre visível; textos
  curtos em português correto (acentos, crase, maiúsculas só onde cabe).
* **Sem dependências externas**: nada de CDN; JS puro (ES2020), sem etapa de
  construção. Funciona offline.
* **Acessível**: foco visível, rótulos `aria-*`, navegação por teclado
  (Ctrl+1…7 para as seções), contraste AA, `prefers-reduced-motion` respeitado.
* Janela padrão 1280×820, mínima 1100×720; a interface deve caber também em
  1366×768 com zoom 125 %. Quando a área útil do monitor não comporta a
  janela padrão, ela abre maximizada (seção 3.3). Números de processo nunca
  são cortados: nas listas laterais quebram depois do ano (`<wbr>`), e na
  barra da audiência ao vivo ganham linha própria abaixo de 1240 px. Também
  abaixo de 1240 px, a tabela do lote (Processos) deixa a coluna “Detalhe”,
  e a frase vai para baixo da pílula de situação; e o cartão “Transcrição
  salva” mostra o nome do documento inteiro, com os botões numa linha
  própria.

### 7.2 Estrutura

Barra lateral (vidro, 248 px): logotipo H + “Helestron”; seções **Início**,
**Processos**, **Audiências** (transcrição), **Pauta**, **Compartilhar**,
**Ajustes**, **Ajuda**; no rodapé, tarefas em andamento (anel de progresso) e a
versão. Conteúdo: título grande + subtítulo + ações à direita.

* **Início** — saudação (“Boa tarde”) e data; **quatro cartões grandes** com as
  funções principais (Baixar processos · Transcrever audiência · Pauta de
  audiências · Compartilhar com IA), cada um com ícone, frase e botão; abaixo,
  “Hoje na pauta” (próximas audiências), “Atividade recente” (lotes e
  transcrições, com a concordância certa: “1 de 1 processo baixado”) e
  “Primeiros passos” (acessos, pastas e modelo, feitos enquanto o servidor
  não manda a pendência; a pauta, feita só com `resumo.pauta.configurada`,
  contrato C5) como lista de verificação. As pendências do servidor entram
  na mesma lista, com o botão “Resolver”: as do sigilo (“Processo sigiloso
  no acervo” e “Arquivo de processo sigiloso no acervo”, seção 12) levam à
  tela Compartilhar.
* **Processos** — fluxo em etapas: (1) relação: área de soltar arquivo
  (arrastar e soltar), botão “Escolher arquivo”, “Colar lista” e “Link”; (2)
  revisão: processos reconhecidos com selos do tribunal/sistema, avisos e
  números rejeitados; (3) opções (nome do lote, separar sigilosos, baixar de novo
  o que já existe, mostrar o navegador); (4) andamento: anel de progresso, lista
  de itens com situação, botões Parar e Abrir pasta; no fim, o título e o
  anel dizem o resultado (“Lote concluído”, verde; “Lote concluído com
  falhas”, âmbar; “Nenhum processo baixado”, vermelho), e “Tentar de novo”
  refaz os que falharam no mesmo lote (contrato C9). Mais “Últimos lotes”.
  O processo que o programa já sabe sigiloso (seção 12) vai para a pasta
  dos sigilosos mesmo que a página do portal não mostre o selo. O 2º grau
  (seção 14.9): nas opções, o segmentado “Grau” (`#grau-lote`, “1º grau” |
  “2º grau”), que começa com o `[download] grau` dos Ajustes e vai sempre
  no pedido; na revisão, a coluna “Grau” (selo sem clique: o grau do lote
  ou o `grau_fixo`, com contorno e o título “Só existe no 2º grau”; em
  âmbar, o grau que o Helestron não baixa daquele tribunal), as pílulas por
  tribunal, sistema e grau e o “Acesso aos portais” no grau de cada linha;
  no andamento, o selo “TJAL · 2º grau”.
* **Audiências** — preparação (número do processo com validação e sugestões da
  pauta de hoje, microfone escolhido pelo nome com medidor de nível — Gravar
  e Testar desativados enquanto a lista carrega —, participantes F1–F8,
  interruptor “Segredo de justiça”, que se liga sozinho com o motivo quando
  o programa já sabe que o processo é sigiloso: contratos C2 e C4);
  **botão de gravar** grande (círculo vermelho); se a gravação não começa
  (sem microfone, por exemplo), a folha de erro “A gravação não começou”,
  com o ícone vermelho, diz o motivo, e a audiência que cai no meio mostra
  “A audiência foi interrompida”; durante a gravação: cronômetro, texto
  ao vivo com marcação de tempo e falante, “Ouvindo…” só enquanto grava (não
  na pausa), rolagem automática, Pausar/Retomar, botões de falante (F1 a F8,
  cada um com uma cor em tons de azul, navy e cinza, todas com contraste AA
  no nome, sobre o branco e o vidro, e na letra branca do botão apertado),
  Encerrar → documento DOCX (“Abrir documento”). Também a faixa “Uma
  transcrição foi interrompida”, com o botão “Recuperar”, e “Transcrições
  recentes”.

  No topo, dois modos do mesmo tamanho (controle segmentado
  `#modo-audiencia`, `radiogroup` com setas do teclado e `aria-controls`):
  **Ao vivo** (o que está acima) e **Arquivo de áudio ou vídeo** (o cartão
  “Transcrever uma gravação”, que substituiu a folha “Transcrever a
  gravação”). O modo é lembrado (`localStorage`), e o subtítulo da página o
  acompanha. No modo arquivo: a área de arrastar e soltar (soltar uma mídia
  em qualquer lugar da tela, até no modo ao vivo, passa ao modo arquivo;
  pasta solta é recusada com aviso), o botão “Escolher arquivo” (o diálogo
  do Windows, quando há, que manda só o caminho; senão, o seletor do
  navegador), o nome e o tamanho do arquivo (pelo diálogo: a pasta e “lido
  de onde está, sem cópia”), “Trocar” e o “×”, o número do processo tirado
  do nome do arquivo ou da pasta, mantendo o dependente, o tipo, o
  “Segredo de justiça” (que se liga sozinho pela pauta, também para o
  incidente de principal sigiloso), “Transcrever” (com a dica do que falta)
  e o andamento: do envio (`XMLHttpRequest`, com porcentagem e “Cancelar
  envio”; o envio sobrevive a sair e voltar à tela), da tarefa e o
  resultado (“Abrir documento”/“Abrir pasta”, ou o motivo da falha em
  vermelho). Uma gravação de cada vez (“Transcrever” e “Trocar” desligados
  durante a transcrição); com o documento pronto, a escolha e o número
  saem da tela. Ctrl+Enter grava (ao vivo) ou transcreve (arquivo). Abaixo
  de 760 px de largura (o Edge em meia tela), uma coluna só, sem rolagem
  horizontal. Os formatos são uma lista ÚNICA, `transcricao/arquivo.EXTENSOES`
  (áudio: `.mp3 .wav .wma .aac .adt .adts .m4a .m4b .flac .ogg .oga .opus
  .aif .aiff .aifc .amr .awb .ac3 .ec3 .mka .weba .caf .au .snd .mp2 .mpa
  .3ga`; vídeo: `.mp4 .m4v .mov .qt .avi .wmv .wm .asf .mkv .webm .mpg
  .mpeg .mpe .m1v .m2v .ts .m2t .m2ts .mts .3gp .3g2 .flv .f4v .vob .ogv
  .dvr-ms .wtv .divx .mxf`), igual a `EXTENSOES_MIDIA` de
  `secao-audiencias.js` (um teste confere item a item, e também o limite do
  envio, JS = servidor); dela saem o filtro do diálogo nativo e o `accept`
  (com `audio/*` e `video/*`). O `.dvr-ms` não passa no filtro da
  pywebview (só `\w`) e entra por “Todos os arquivos”. A extensão só
  orienta: a decodificação tem frases próprias (`SemTrilhaDeAudio`,
  `ArquivoDanificado`, `ProtegidoPorDrm`, todas `AudioIlegivel`) para o
  vídeo sem trilha de áudio, o arquivo cortado, corrompido ou que não é
  mídia (sem o caminho nem o texto do FFmpeg na frase) e o DRM, detectado
  pela estrutura antes de abrir (objetos de cifra do cabeçalho ASF; `stsd`
  de áudio `enca`/`drms` no MP4, M4A e MOV); com várias trilhas, vale
  `streams.best("audio")`, e a leitura que para no meio guarda o que veio.
  O modo demonstração (`?demo=1`) simula o diálogo (a mídia de um incidente
  em `_controle\midias\<número>-01\`), a falha (“… sem som.mp4”) e uma
  gravação de cada vez.
* **Pauta** — seção 8.8.
* **Compartilhar** — botão principal “Preparar acervo para a IA”; cartões:
  Claude Code, Claude Cowork, Claude Desktop (conector), ChatGPT Work, Codex,
  Pacote para o ChatGPT, Nuvem (OneDrive/Google Drive); cada um com situação e
  ação; “Copiar pedido inicial”. Cowork e ChatGPT Work copiam o texto na hora
  do clique (contrato C7); sem o Claude Code, o Claude Desktop ou o app do
  ChatGPT, a página oficial abre no navegador (contrato C6). A faixa
  “Sigilo e responsabilidade” lembra a regra do sigilo (seção 12).
* **Ajustes** — listas agrupadas: Acessos aos portais (usuário/senha por
  portal, com os botões irmãos “Testar” e “Alterar”/“Cadastrar” e o
  resultado do teste na linha: contrato C1; no e-SAJ do TJAL, “Testar 1º
  grau” e “Testar 2º grau”; o eProc do 2º grau numa linha própria, também
  oferecida no “Adicionar acesso”; o rodapé diz que o acesso ao e-SAJ vale
  para os dois graus e que o eProc do 2º grau tem acesso próprio), Pastas,
  Unidade, Download (com “Grau dos processos”), Transcrição (com a lista
  “Microfone”, pelo nome), Pauta (fontes,
  monitoramento; a fonte cuja última sincronização falhou mostra “Último
  erro: …” com um ponto âmbar, e o ícone dela não muda de cor),
  Compartilhar, Sobre e diagnóstico (versão, verificar instalação, abrir
  registros). Nenhum botão fica dentro de outro.
* **Ajuda** — perguntas frequentes pesquisáveis e “como fazer” de cada função.

Folhas (sheets) para perguntas (código de 6 dígitos com campo grande),
confirmações e erros. Avisos (toasts) no canto superior direito, mas abaixo
das ações do cabeçalho da página e do que a tela marcar com
`data-livre-de-avisos` (a barra da audiência ao vivo, os botões de falante);
no máximo três à vista; a mesma mensagem (ou uma contida noutra) substitui a
anterior em vez de se repetir; o aviso do fim de uma tarefa cujo resultado a
tela aberta já mostra (a sincronização e a captura na Pauta, o teste de
acesso em Ajustes) não aparece.

### 7.3 Arquivos

`web/index.html`, `web/css/helestron.css`, `web/js/` (`api.js` — cliente com
token e reconexão do SSE; `app.js` — rotas por `#/secao`; um arquivo por seção;
`componentes.js`; `demo.js`), `web/img/` (logotipo, ícones SVG), `web/fontes/`.

**Modo demonstração** (`index.html?demo=1`): `demo.js` responde a todas as
chamadas da API com dados realistas e simula eventos (download andando, texto da
audiência chegando, pauta com 40 audiências, uma delas sigilosa), **sem
servidor**, nos mesmos formatos do servidor (contratos C1–C9). Serve para
desenvolver o visual, para as capturas de tela e para testes da interface.
Variações pela URL: `&pauta=vazia`, `&sem_dialogo=1`, `&lote=falhas` (nenhum
processo do lote é baixado), `&claude_code=ausente`, `&microfone=<nome>` (o
microfone guardado em Ajustes), `&presenca=certificado` (as fontes da pauta
só entram com a pessoa à frente), `&modo=edge` ou `&modo=navegador` (o modo
da janela) e `&falantes=ausentes` (construção sem os modelos de voz).

**Modo autoteste** (`?autoteste=1`): percorre as seções, espera cada uma
carregar e avisa o servidor (`POST /api/autoteste/passo {secao}`) para a captura;
no fim, manda o balanço (`POST /api/autoteste/fim {secoes, erros}`). O
`--autoteste` (seção 5) roda em pastas de dados temporárias e vazias: as
capturas, que saem do computador, nunca mostram a pauta, o acervo ou a
configuração de quem o roda (seção 12).

## 8. Pauta de audiências (`helestron/pauta`)

### 8.1 Modelo

```python
@dataclass
class Audiencia:
    id: str            # sha1(sistema|tribunal|processo|data|hora|tipo)[:16]
    sistema: str       # "esaj" | "eproc" | "arquivo"
    tribunal: str      # sigla (TJAL...) ou ""
    processo: str      # CNJ formatado (nucleo.cnj); "" se não reconhecido
    data: date
    hora: str          # "HH:MM" ou ""
    tipo: str          # normalizado: "Conciliação", "Instrução e julgamento", "Una", "Custódia", "Justificação", "Mediação", "Outra" (+ texto original em tipo_original)
    situacao: str      # "Designada", "Realizada", "Cancelada", "Redesignada", "Não realizada", "Suspensa"
    local: str         # sala/vara/"Virtual"
    link: str          # link de audiência virtual, se houver
    classe: str
    partes: str        # "Autor x Réu" (como vier)
    magistrado: str
    sigiloso: bool     # o portal (ou o relatório) indicou segredo de justiça nesta ou em outra
                       # audiência do mesmo processo, ou o processo está na pasta de sigilosos
    observacoes: str
    origem: str        # URL/arquivo de onde veio
    capturada_em: datetime
    tipo_original: str
    situacao_original: str
```

### 8.2 Armazenamento

SQLite em `LOCAL/pauta.sqlite3` (stdlib `sqlite3`, WAL). Tabelas `audiencias`
(estado atual), `alteracoes` (histórico: nova/alterada/cancelada/removida,
campos antes→depois, quando, vista) e `fontes` (id, tribunal, sistema, rótulo,
modo automático/capturado, URL lembrada, última sincronização, último erro).
Gravar em transação; `upsert` por `id`; a sincronização de uma fonte num período
marca como **removida** a audiência daquela fonte e período que não veio mais
(e não a apaga) — só quando a leitura cobriu o período inteiro
(`Leitura.cobertura`, seção 8.3): leitura incompleta não marca nada como
removida nem pareia remarcadas, e, sem o período aceito pelo portal, a
cobertura se limita às datas que vieram. A audiência remarcada (a data e a
hora fazem parte do `id`) é reconhecida quando, na mesma sincronização, some
uma audiência **ainda por acontecer** de um processo e aparece outra do
**mesmo** processo, do mesmo portal e do **mesmo tipo**, uma só de cada
lado: vira “alterada”, com a data e a hora antes→depois, e não um par
“nova” + “removida”. A que já passou (data anterior a hoje, ou hoje com a
hora vazia ou já passada: a Conciliação realizada, que sai da lista das
designadas) e a de outro tipo (a Instrução marcada na própria Conciliação)
não se pareiam. O registro antigo não é apagado (nada de `DELETE`): fica
com `removida = 1`, e o histórico tem uma alteração só; `alteracoes(de,
ate)` traz também a remarcada cuja data antiga cai no período (a planilha
da semana antiga diz para quando ela foi). A que volta à pauta também entra
no pareamento. Campo vazio não apaga o que já se sabia, e o sigilo, uma vez
apurado, fica (`a.sigiloso or velha.sigiloso`), também fora do banco: o
processo marcado sigiloso entra no registro ao lado dele
(`sigilo.lembrar_da_pauta`, `pauta.sigilo.json`), alimentado ao gravar
audiência sigilosa e ao abrir o banco (o de uma versão anterior). Não há
como desmarcá-lo pelo programa (seção 12, “Uma marcação errada não se
desfaz sozinha”).

O banco só é posto de lado (`pauta.corrompido-<data>.sqlite3`, com o `-wal`
e o `-shm`) quando o SQLite diz que o **arquivo** está estragado
(`SQLITE_CORRUPT` ou `SQLITE_NOTADB`, `armazem.banco_estragado`); os
processos sigilosos que ainda se possam ler da cópia vão para o registro
do sigilo (`sigilo.lembrar_do_banco`). Erro do ambiente com o banco bom
(disco cheio, sem permissão, E/S, ocupado, só leitura:
`OperationalError`) sobe, e o banco fica como está. O banco nunca é
apagado: se não puder sair do lugar, o que já foi movido volta e o erro
sobe; o `-wal` e o `-shm` que não saem são apagados, para o banco novo não
herdar páginas.

A audiência que o portal traz e que já estava na pauta por um relatório
**importado** (mesmo processo, data e hora) não fica em dobro: na mesma
transação, o registro do relatório (`sistema` “arquivo”) é absorvido pelo
do portal (`Armazem._absorver_importadas`) — o que só o relatório sabia
completa o registro do portal, o sigilo de um vale para o outro, e a
absorvida não conta como “nova”; se o portal mudou a situação, a mudança
vira alteração (“cancelada”, por exemplo). O par é **um a um, pelo tipo**
(`modelos.parear_mesmo_horario`, a mesma regra da importação no sentido
inverso): primeiro o do mesmo tipo (havendo mais de um, o da mesma
situação); o que sobra só se pareia quando sobra **um de cada lado**. Com
duas audiências do processo no mesmo horário (uma Conciliação cancelada e
uma Instrução designada), cada uma fica com a sua, e o registro do
relatório sem par fica onde está. A do portal que já estava no banco só
absorve o do mesmo tipo (ela já foi pareada antes).

`Armazem.sigilosas()` devolve as chaves CNJ e os ids marcados sigilosos em
**qualquer** registro (o sigilo é do processo), e
`Armazem.processos_sigilosos()`, `{chave: número}` (o número como a pauta o
mostra), com que o serviço compara os sigilosos antes e depois de gravar
(seção 8.10). A importação grava a meta `ultima_importacao`.

### 8.3 Extração automática (e-SAJ e eProc)

Reaproveita o login e o perfil de navegador do download (`download/esaj.py`,
`download/eproc.py`, `download/navegador.py`): mesma sessão, mesmo código por
e-mail/dois fatores via perguntas e as mesmas senhas — a do cofre e a
digitada com “Lembrar neste computador” desligado, que vale até fechar o
programa (`app.credenciais_sessao`, o mesmo dicionário do download, entregue
ao `ServicoPauta.credenciais_sessao` em sincronizar e capturar; a da sessão
tem precedência). No monitoramento (segundo plano), só vale a senha
guardada (seção 8.7). Depois de entrar:

1. **Rota lembrada** da fonte (URL capturada antes), se houver.
2. **Rotas conhecidas** em `dados/pauta.json` (por sistema e, se preciso, por
   tribunal) — candidatos de URL relativos ao portal.
3. **Descoberta pelo menu**: procura links/itens de menu cujo texto case com
   `pauta|audiênci|agenda de audi|gerenciar audi|consultar audi` (regex em
   `pauta.json`), abre o primeiro e confere se a página tem tabela de audiências.
4. Preenche o **período** se a página tiver campos de data (rótulos/nomes como
   `Data inicial/final`, `dataInicio`, `txtDataInicio`, `de`/`até`) e envia.
   O período só conta como **aplicado** (`periodo_aplicado`) se a página
   mudou depois do envio e os campos não mostram outro período (portal que
   recusa ou encurta o pedido); senão, a cobertura se limita às datas que
   vieram, e o resultado traz o aviso (“O e-SAJ do TJAL não aceitou o
   período…”, “O eProc do TJAL mostrou o período de … e não o pedido…”).
5. Lê **todas as tabelas** da página (inclusive em frames), reconhece a de
   audiências pelo cabeçalho (seção 8.5) e **pagina** (link/botão “Próxima”,
   `infraAcaoPaginar` do eProc, seletor de página) até o fim (limite 50 páginas).
   A leitura fica **incompleta** (`Leitura.incompleta`, com o motivo) quando a
   página seguinte não abre a tempo ou não mostra a tabela, quando o portal
   volta a uma página já lida, quando bate o limite de páginas, ou quando
   foram lidas menos linhas do que o total que o portal informa (“Lista de …
   (N registros)”). Nesse caso, nada é dado como removido (seção 8.2), e o
   aviso diz “A leitura da pauta do … ficou incompleta: [motivo]. Por isso,
   nenhuma audiência foi dada como fora da pauta; sincronize de novo mais
   tarde.” A sessão que cai no meio da paginação (o portal pede a senha de
   novo) lança `SessaoPerdida`, também depois da 1ª página: o serviço entra
   de novo e relê tudo, uma vez.
6. Normaliza, grava e registra a URL que funcionou como rota lembrada.

eProc usa o framework “Infra” (tabelas `table.infraTable`, legenda “Lista de …
(N registros)”, paginação `infraAreaPaginacao`). As rotas e regexes ficam em
`pauta.json` para ajuste sem mexer no código.

### 8.4 Captura assistida (funciona em qualquer tela)

Para quando a descoberta falha, ou o tribunal tem tela própria: o Helestron abre
o portal no navegador **visível** (perfil do usuário), já logado, e injeta (via
`add_init_script` + `expose_binding`) uma **barra flutuante** discreta no topo da
página: “Helestron — vá até a pauta de audiências e clique em **Capturar esta
tela**” · [Capturar esta tela] [Concluir]. Cada clique lê as tabelas da página
atual (e frames), mostra na barra quantas audiências reconheceu e acumula; o
usuário pode mudar de página e capturar de novo. “Concluir” grava tudo e
**lembra a URL** como rota da fonte, para o monitoramento automático.

### 8.5 Reconhecimento de tabela

Cabeçalhos por sinônimos (sem acento, minúsculas), em `pauta.json`:
data (`data`, `dia`, `data/hora`, `data da audiencia`), hora (`hora`, `horario`,
`inicio`), processo (`processo`, `numero`, `autos`, `n do processo`), tipo
(`tipo`, `tipo de audiencia`, `natureza`, `audiencia`), situação (`situacao`,
`status`, `andamento`), local (`local`, `sala`, `vara`, `orgao`), classe,
partes (`partes`, `autor`/`reu` combinados, `polo ativo`/`polo passivo`),
magistrado (`magistrado`, `juiz`, `conciliador`, `responsavel`), link. Uma
tabela é de audiências se tiver ao menos **data** e (**processo** ou **tipo**),
ou se ≥ 50 % das linhas tiverem data e número CNJ. Célula com data e hora juntas
é separada. Datas `dd/mm/aaaa`, `dd/mm/aa`, `dd.mm.aaaa`, ISO; horas `HH:MM`,
`HHhMM`. Além disso (`pauta/tabelas.py`):

* **Cabeçalho depois do preâmbulo.** O cabeçalho é procurado nas primeiras
  15 linhas (`MAX_LINHAS_CABECALHO`). Linha com valores (uma data ou um
  número CNJ, como “Data: | 03/10/2026 | Hora: | 10:15”, da emissão do
  relatório) é preâmbulo, não cabeçalho, e não encerra a busca. Duas linhas
  de cabeçalho seguidas (“Audiência” mesclada sobre “Data | Hora”) são
  juntadas coluna a coluna. Um cabeçalho de outra coisa (intimações) só
  barra a tabela se nenhum cabeçalho de pauta vier abaixo dele. Na regra dos
  50 %, as linhas antes do primeiro dado (título, vara, período) não contam.
* **Só a própria tabela diz que é pauta.** Os sinais de audiência (coluna de
  hora, “audiência”/“pauta” no cabeçalho, na legenda ou no nome da tabela)
  vêm da própria tabela; o título da página nunca desfaz um cabeçalho com
  negativos (`prazo`, `evento`, `intimac`, `movimentac`, `movimento`,
  `publicac`, `expedi`, `peticao`, `documento`, `distribuic`, `distribuid`,
  `recebimento`, `conclus`, `juntada`, `mandado`, `citac`, `remessa`,
  `ultimo andamento`): a página da pauta costuma ter, ao lado, o painel de
  intimações. A **única exceção** é a tabela que já tem a cara da pauta —
  data com hora (pelo rótulo “Data/Hora” ou porque ao menos metade das
  datas vem com o horário), processo, tipo e situação, com tipos de
  audiência na coluna Tipo em ao menos metade das linhas (“Conciliação”,
  “Audiência de Instrução”, e não “Intimação eletrônica” ou “Citação”) — e,
  ao lado, uma coluna “Documento” (a ata), “Intimação das partes”,
  “Mandados”…: na página da pauta (“audiência” ou “pauta” no título), ela é
  a pauta, a menos que a legenda ou o nome da própria tabela fale de
  intimações, prazos etc. (o painel “Intimações” com Tipo e Situação). No
  portal (modo estrito), a tabela só com data e processo, sem hora, tipo nem
  situação, precisa de “audiência” ou “pauta” na tabela ou na página (a fila
  de processos também tem data e número).
* **Células mescladas.** O `rowspan` (HTML e a leitura no navegador) vale
  em todas as linhas que cobre, na mesma coluna, e as células seguintes não
  escorregam; o `colspan` ocupa as colunas seguintes, vazias. A cópia que a
  mescla põe nas linhas de baixo fica marcada como **herdada**: a linha
  cuja data, hora e processo são só os herdados (a audiência em duas
  linhas, com as partes embaixo) completa a audiência de cima e não vira
  outra — a menos que traga o tipo ou a situação dela (um tipo ou uma
  situação das regras, ou os dois em colunas próprias), que é outra
  audiência do mesmo processo no mesmo horário (a Conciliação cancelada e,
  embaixo, a Instrução designada). As partes numa célula larga sobre o Tipo
  e a Situação, o selo de sigilo ou o processo apensado continuam detalhe
  da audiência de cima.
* **Data em uma linha só.** Linha de grupo (“Segunda-feira, 05/10/2026”,
  sozinha ou só com a contagem ou o dia da semana: “2 audiências”, “Total:
  3”, “(3)”) dá a data às linhas de baixo; nunca é linha de grupo a que tem
  número de processo. A célula de data **vazia** repete a data da linha de
  cima (o relatório com a data só na primeira audiência do dia) só se a
  linha é mesmo outra audiência: com hora própria ou a hora mesclada de
  cima ou, numa tabela sem coluna de hora, com o número na própria coluna
  Processo. A hora sozinha na coluna Data/Hora (“10:00” embaixo de
  “05/10/2026 09:00”) também usa o dia de cima. O número em outra célula
  (“Apensado ao processo…”) e a linha sem hora numa tabela que tem a coluna
  Hora (“Aguardando designação”) não herdam o dia de ninguém; com outro
  texto na célula de data (“a designar”), só a data da linha de grupo vale.
* **Sigilo por célula: só a indicação positiva marca.** Marcar um processo
  como sigiloso o tira do acervo e da IA de vez (seção 12), e a marcação não
  se desfaz (seção 8.2); por isso, só a indicação positiva e inequívoca
  marca. O selo é procurado célula a célula (também na tabela sem
  cabeçalho, na linha de baixo e no PDF), e o texto e o `title`/`alt` de
  cada ícone são julgados separadamente: as dicas dos ícones de uma célula
  são guardadas separadas por “ | ” (`SEPARADOR_DICAS`, no leitor de HTML e
  no JavaScript de `pauta/navegacao.py`) e julgadas uma a uma. O número CNJ
  sai do texto antes do julgamento. Uma célula marca se casa com `sigilo` e
  não casa com `sem_sigilo` (em `dados/pauta.json`, iguais à regra embutida
  de `pauta/regras.py`, e um teste confere; a chave `_sigilo` do JSON é só
  um comentário, ignorado pelo programa).
  * **Marcam:** o ícone “Segredo de Justiça”; as partes “(Segredo de
    Justiça)”; “Ação Civil Pública - Segredo de Justiça”; “Processo em
    segredo de justiça” (e “Autos sigilosos”, “Audiência sigilosa”,
    “Processo sob sigilo”, “Tramita em sigilo”); “Sigiloso” ou “Em sigilo”
    sozinho na célula; o nível com contexto de sigilo (“Segredo
    de Justiça (Nível 1)”, “Nível de sigilo 1”); “Sigilo: sim”. Na coluna
    **Sigilo** (cabeçalho `sigilo`, `segredo`, `segredo de justica`,
    `sigiloso` ou `nivel de sigilo`), também “Sim”, “X” e o nível puro
    (“Nível 1”, “2”).
  * **Não marcam:** “Nível 1” ou “Nível 2” fora da coluna Sigilo (no Local,
    é o andar ou o bloco do fórum); as negações, também na coluna Sigilo
    (“Segredo de justiça: não”, “Segredo de Justiça? NÃO”, “Sem segredo de
    justiça”, “Não sigiloso”, “Processo não é sigiloso”, “não corre” ou “não
    tramita em segredo”); o nível 0 e “Público” sozinho; o sigilo retirado,
    levantado, revogado, afastado, indeferido, inexistente ou ausente; a
    menção que não afirma nada (“Pedido de segredo de justiça…”,
    “requer…”, “verificar se há segredo de justiça”); e o “sigiloso” solto
    de outra coisa (“Oitiva de testemunha sigilosa”).

  “Público” só desfaz o selo quando é o rótulo do nível, sozinho na célula —
  “Ministério Público”, “Defensoria Pública”, “Ação Civil Pública” ou
  “Fazenda Pública” ao lado de “Segredo de Justiça” não tiram o sigilo de
  ninguém —, e a negação de uma célula não vale para outra. Nas partes,
  “Segredo de justiça: não” não é máscara (`_tirar_mascara`); na linha de
  baixo de uma mescla (`rowspan`), a negação fica como observação e não
  marca. `TestSigiloSoComIndicacaoPositiva` (`testes/test_pauta_tabelas.py`)
  confere os casos por coluna.

### 8.6 Importação de relatório

`POST /api/pauta/importar`: planilha (xlsx/xls/ods/csv), HTML (inclusive o
`.xls` que é HTML), PDF (tabela por texto) ou DOCX exportados do SAJ/eProc —
mesmas regras de 8.5, aproveitando os leitores de `nucleo/listas.py`. As
células mescladas na vertical das planilhas valem em todas as linhas que
cobrem, na primeira coluna da mescla: `.xlsx` (openpyxl sem `read_only`, que
é o que conta as mescladas), `.xls` (xlrd com `formatting_info`) e `.ods`
(`number-rows-spanned`). No `.ods`, as células cobertas
(`covered-table-cell`) valem **coluna a coluna**: cada uma herda o valor da
mescla da sua coluna (o LibreOffice junta numa só as cobertas vizinhas de
mesclas diferentes). Como no `rowspan` do HTML, a cópia é herdada (seção
8.5). No PDF, a linha “Data: … Hora: …” da emissão não é tomada como
cabeçalho. Importar e depois sincronizar não duplica (seção 8.2), e
importar o que já veio do portal só completa o que faltava, com o mesmo
par um a um, pelo tipo. O sigilo do relatório segue a mesma regra da
seção 8.5 (só a indicação positiva marca), e o que ele revela vale na hora
(seção 12); `TestRelatorioSoMarcaSigiloComSelo` confere com um CSV e com
`sigilo.chaves_da_pauta`, a regra única.

### 8.7 Monitoramento

Thread do aplicativo: com `[pauta] monitorar = true`, sincroniza as fontes com
rota a cada `intervalo_horas` (padrão 6) e ao abrir o programa (se a última
sincronização passou do intervalo), no período `dias_atras` (7) a `dias_a_frente`
(60). Se o portal pedir código, **não bloqueia**: registra e avisa (“Entre no
portal para continuar o monitoramento”). Alterações viram eventos `pauta` e
contam em “alterações não vistas” (selo na barra lateral). Com um download em
andamento (o navegador dos portais ocupado), tenta de novo em 15 minutos.

**Fontes que exigem a pessoa à frente** (`ServicoPauta.exige_presenca` e
`motivo_presenca`, a mesma regra de `_acesso` no segundo plano; o monitor a
consulta por `MonitorPauta.exige_presenca`): login por certificado digital
ou pela entrada manual, ou sem senha **guardada**
(`_credenciais(sessao=False)`: a senha “só por agora” não vale em segundo
plano). Essas fontes ficam de
fora da sincronização automática — nada de tarefa que falha nem de aviso
“não deu certo” a cada ciclo — e viram a pendência `pauta_login`
(“Monitoramento da pauta”, `MENSAGEM_PRESENCA`), uma vez por execução do
programa: diz em que fontes o monitoramento não entra sozinho e o que fazer
(Sincronizar à mão; guardar o usuário e a senha em Ajustes › Acessos aos
portais; ou desligar “Conferir sozinho”). Se nenhuma fonte entra sozinha,
nem há tarefa, nem **próxima sincronização** anunciada: `monitoramento()`
(e `MonitorPauta.proxima`) devolvem `proxima` nula, inclusive depois de uma
sincronização feita à mão, e o quadro Monitoramento da tela Pauta só mostra
a linha “Próxima: …” com o monitoramento ligado e alguma fonte que entre no
portal sozinha. A presença descoberta só durante a sincronização recebe a mesma frase; a de
“código” (`MENSAGEM_LOGIN`) fica só para quando o portal pediu o código de
fato (`ContextoMonitor.motivo` = “codigo”; a presença descoberta no
`_acesso` marca “presenca”). Em `fontes()`, a fonte que exige a pessoa vem
com `monitorada` falso, `exige_presenca` verdadeiro e o `motivo_presenca`
(“a entrada no portal é pelo certificado digital”, “a entrada no portal é
manual”, “o usuário e a senha do portal não estão guardados neste
computador”); Ajustes › Pauta mostra o selo “Só com você” e o motivo, e o
quadro Monitoramento da Pauta diz por que nenhuma fonte entra sozinha, se
for o caso. A fonte sem rota lembrada (e que não exige a pessoa) tem o selo
“Sem endereço salvo”, em Ajustes › Pauta, e aparece como “(sem endereço
salvo)” na lista de fontes do quadro Monitoramento (a que exige a pessoa,
como “(só com você)”). `monitoramento()` conta em `fontes_monitoradas` só
as que o monitor sincroniza de fato.

### 8.8 Tela da Pauta

Cabeçalho: período (controle segmentado **Hoje · Semana · Mês · Período**),
filtro de sistema (e-SAJ · eProc · Todos), situação, busca. Resumo em
“chips”: total, hoje, próximos 7 dias (de hoje a hoje + 6, os mesmos dias da
visão Semana), canceladas/redesignadas. O resultado da sincronização, da
captura e da importação fica numa faixa que dura até ser fechada; a página
só rola até ela quando a pessoa começou a tarefa com um clique nesta tela
(o fim do monitoramento automático não tira do lugar quem está lendo a
lista), e os avisos dessas tarefas não se repetem no canto enquanto a Pauta
está aberta. A faixa da captura tem o título “Captura concluída: N
audiências em N telas” e, no texto, só o que o título não diz: “O endereço
ficou lembrado: a fonte entra no monitoramento automático.” (ou, na fonte
que exige a pessoa, que o monitoramento não entra sozinho nela), mais o
motivo, se o navegador foi fechado ou o tempo acabou antes de “Concluir”.
Lista agrupada por dia (cabeçalho do dia “Segunda-feira, 5 de outubro”),
cada audiência com hora, número do processo (copiável), selo do tipo,
partes, local e pílula de situação; ações por linha: Baixar autos,
Transcrever (abre Audiências com o número), Abrir link. Botões: **Sincronizar** (com e-SAJ/eProc), **Capturar no
portal**, **Importar relatório**, **Exportar Excel**. Painel “Alterações
recentes”. Interruptor de monitoramento e intervalo. Estado vazio explica como
começar (configurar acesso + sincronizar ou capturar).

### 8.9 Exportação Excel (`openpyxl`)

Arquivo `Documentos\Helestron\Pauta\Pauta de audiências AAAA-MM-DD a AAAA-MM-DD.xlsx`
(nome livre se já existir). Abas:
* **Pauta** — título e período nas linhas 1–2, cabeçalho na 4 (fundo navy,
  letra branca, negrito), colunas: Data · Dia da semana · Hora · Processo ·
  Classe · Partes · Tipo de audiência · Situação · Local · Magistrado/Conciliador
  · Sistema · Tribunal · Link · Observações. Datas como data do Excel
  (`dd/mm/aaaa`), hora `hh:mm`; filtro automático; painel congelado; larguras
  ajustadas; linhas zebradas leves; situação colorida (Cancelada cinza e
  tachada, Redesignada âmbar, hoje em azul-claro). Processos sigilosos com as
  colunas Partes e Observações como “(segredo de justiça)” (as Observações,
  quando houver alguma) **a menos** que o usuário marque “Incluir as partes
  e as observações dos sigilosos”, na folha de exportação.
* **Resumo** — quantidade por dia, por tipo e por situação.
* **Alterações** — histórico do período inteiro (`alteracoes(limite=None)`,
  com a remarcada cuja data antiga cai no período), com os mesmos filtros
  da aba Pauta (`ServicoPauta._filtro(sistema, situação, busca)`, aplicado
  também ao retrato de cada alteração); o A2 diz quais filtros foram
  aplicados. As observações dos sigilosos são mascaradas como as partes.
Rodapé com “Gerado pelo Helestron em dd/mm/aaaa hh:mm”.

Regras da planilha:

* **Sigilo por processo.** É sigiloso o processo com autos ou transcrição
  na pasta dos sigilosos ou com **qualquer** audiência marcada sigilosa no
  banco ou no registro do apurado (`ServicoPauta._sigilosas()`: o banco já
  aberto, `sigilo.apuradas_da_pauta` e `sigilo.chaves_na_pasta(pasta,
  acervo)`, com cache de 15 s; a regra única da seção 12, com a herança do
  incidente e as gravações em `_audio`). `_dicts`, `_marcar_sigilo` e
  `_sigilosos_conhecidos`/`_revelados` testam com `sigilo.contem`. Vale
  para a lista, o Início, a planilha e o histórico: cada alteração é
  marcada sigilosa (`_marcar_sigilo`) se o processo é sigiloso hoje ou se a
  audiência daquele id está sigilosa, ainda que o retrato da alteração seja
  de antes do sigilo. (`processo_sigiloso`, o contrato C4, continua
  comparando o número exato.)
* **A escolha da janela vale.** `incluir_partes_sigilosos` presente no
  pedido (ou `--incluir-partes-sigilosos`/`--sem-partes-sigilosos` na linha
  de comando) vale nos dois sentidos; ausente, vale
  `[pauta] incluir_partes_sigilosos`; a string “false” é falsa.
* **Busca omitida.** Com as partes mascaradas e algum processo sigiloso no
  resultado, a linha 2 das abas Pauta e Resumo diz “busca por texto
  (omitido por causa do segredo de justiça)”, e não o texto procurado (que
  pode ser o nome de uma parte).
* **Texto, nunca fórmula.** Toda célula das três abas passa por
  `exportacao._escrever`: texto que começa com “=” fica com `data_type` “s”
  e `quotePrefix`, ou seja, como texto (`=WEBSERVICE(…)`, `=HYPERLINK(…)`
  vindos do nome de uma parte não são calculados ao abrir).
* **Sem caractere de controle.** `modelos.limpar` remove `\x00`–`\x08`,
  `\x0e`–`\x1b` e `\x7f` (os demais controles viram espaço), e
  `exportacao._seguro` passa em todas as células, no A2 das três abas e no
  link. Erro inesperado na exportação vira `ErroPauta` com uma frase limpa
  (o registro guarda só o tipo e o arquivo:linha), e a API responde 500
  `planilha_falhou`, sem o texto da célula.

CLI: `python -m helestron pauta exportar --de 2026-10-01 --ate 2026-10-31`
(mais `--incluir-partes-sigilosos` ou `--sem-partes-sigilosos`, se quiser).
A linha de comando da pauta (`pauta/cli.py`: `sincronizar`, `exportar`,
`importar`, `listar` e `fontes`) usa o `ArgumentParser` em português da
seção 5, com a ajuda e os erros sem inglês (o “choose from” do argparse
virou “opções: …”). `pauta importar` e `pauta sincronizar` que revelam o
sigilo de processo com arquivos no acervo fazem o preparo rápido por conta
própria (`servicos.atualizar_indice`) e dizem o que saiu: “Segredo de
justiça: a pauta indica que o processo X corre em segredo de justiça, e
ele tinha arquivos no acervo. Preparando o acervo...” e, depois, “1
processo levado para a pasta dos sigilosos; fora do índice e do texto
lidos pela IA.” (ou “N processos levados…”). O arquivo que não pôde sair
vai para o erro padrão (“ATENÇÃO: não consegui levar para a pasta dos
sigilosos: …”), e, com pasta da nuvem escolhida, a saída lembra que “A
cópia na nuvem sai no próximo espelho (na janela: Compartilhar › Espelhar
agora).” O preparo vale também quando o comando é interrompido (Ctrl+C) ou
falha no meio: um coletor registrado com `quando_revelar_sigilo` recebe os
revelados na hora, e `sincronizar` (com o laço dentro de `try/except
BaseException`), `capturar` e `importar` entregam o que já foi revelado
antes de repassar o erro. `pauta listar` mascara as partes e as observações
dos sigilosos no texto e no `--json` (`ServicoPauta.listar(...,
mascarar_sigilosos=True)`, `modelos.mascarar_sigiloso`; `"sigiloso": true`
continua no JSON), e a busca não procura nesses campos deles, salvo
`--incluir-partes-sigilosos`. `pauta fontes --adicionar` valida o tribunal
e o sistema pelo catálogo e grava a sigla canônica (inválido: código 2);
`--remover` de fonte inexistente sai com 1.

### 8.10 Fachada para a API (`helestron/pauta/servico.py`)

```python
class ServicoPauta:
    def __init__(self, cfg, arquivo_banco: Path | None = None, eventos: Callable[[str, dict], None] | None = None): ...
    def listar(self, de: date, ate: date, sistema="", situacao="", busca="",
               mascarar_sigilosos: bool = False) -> dict      # {audiencias:[dict], resumo:{...}}
    def fontes(self) -> list[dict]
    def salvar_fonte(self, tribunal, sistema, rotulo, url="") -> dict   # valida pelo catálogo (ValueError)
    def remover_fonte(self, id_fonte) -> bool                           # False: a fonte não existia
    def sincronizar(self, ctx, fontes: list[str] | None, de: date, ate: date) -> dict   # ctx = Contexto da tarefa (status, progresso, cancelado, pedir_codigo)
    def capturar(self, ctx, tribunal: str, sistema: str) -> dict
    def importar(self, caminho: Path) -> dict
    def exportar(self, de, ate, destino_pasta: Path, **filtros) -> Path   # filtros: sistema, situacao, busca, incluir_partes_sigilosos (None/ausente = o ajuste)
    def alteracoes(self, desde: datetime | None = None) -> list[dict]
    def marcar_vistas(self) -> None
    def monitoramento(self) -> dict ; def configurar_monitoramento(self, ativo: bool, intervalo_horas: int) -> dict
    def ultima_sincronizacao(self) -> datetime | None
    def configurada(self) -> bool      # há fonte, ou já houve sincronização/captura/importação, ou há audiência no banco
    def resumo_inicio(self) -> dict    # {hoje, semana, proxima, ultima_sincronizacao, alteracoes_nao_vistas, fontes, configurada}
    def processo_sigiloso(self, numero) -> bool   # alguma audiência do processo, em qualquer registro, está sigilosa (C4)
    def motivo_presenca(self, fonte) -> str       # por que o login da fonte exige a pessoa ("" = entra sozinha; seção 8.7)
    def exige_presenca(self, fonte) -> bool
    credenciais_sessao: dict[str, tuple[str, str]] | None   # {portal: (usuário, senha)} digitados sem "Lembrar" (o servidor entrega o da sessão)
    def quando_revelar_sigilo(self, funcao: Callable[[list[str]], None] | None) -> None   # quem aplica o sigilo revelado (o servidor)
    ao_revelar_sigilo: Callable[[list[str]], None] | None   # propriedade: a função registrada

# funções do módulo (o aviso e a linha de comando do sigilo revelado)
def no_acervo(cfg, numeros) -> list[str]        # dos números, os que têm autos, transcrição ou _ia/texto no acervo (na dúvida, todos)
def quem_corre(numeros: list[str]) -> str       # "o processo X corre", "os processos X e Y correm", "5 processos (X, Y, Z e mais 2) correm"
def frase_sigilo_revelado(cfg, numeros: list[str], preso_no_acervo: bool = False) -> str
```

**Sigilo revelado.** `sincronizar` (mesmo com fontes que falharam),
`capturar` e `importar` comparam os processos sigilosos do banco antes e
depois de gravar (`Armazem.processos_sigilosos()`); os que a pauta acaba de
revelar vão para `resultado["sigilosos_novos"]` (os números como a pauta os
mostra; a chave só aparece quando há algum) e para a função registrada com
`quando_revelar_sigilo`. O que se revela antes do registro (pelo monitor,
por exemplo) fica guardado e é entregue uma vez, no registro; a função que
falha não derruba a sincronização nem a importação. O serviço só informa:
quem aplica no acervo é o servidor (`api_pauta.servico_da_pauta`, seção 12)
ou a linha de comando (seção 8.9); usado sozinho, sem nenhum dos dois, ele
não tira nada do acervo.

`semana` (em `resumo` e em `resumo_inicio`) conta de hoje a hoje + 6
(`DIAS_DA_SEMANA` = 7).

`Audiencia` vira dict com `data` em ISO e `hora` “HH:MM”.

## 9. Ícone e marca

`construir/marca.py` (Pillow) gera, a partir de desenho vetorial próprio:
`helestron/recursos/helestron.ico` (16, 20, 24, 32, 40, 48, 64, 128, 256),
`helestron.png` (512), `helestron-64.png`, `web/img/marca/helestron.svg` e
`web/img/marca/helestron-64.png` (para a interface) e as imagens do instalador
(`instalador-boas-vindas.bmp` 164×314, `instalador-cabecalho.bmp` 150×57).

Desenho: “squircle” do iOS (superelipse), **navy** em gradiente
(#1B3560 → #0B1A33) com **reflexo de vidro** (faixa branca translúcida no topo,
borda interna clara e translúcida) e um **“H”** geométrico moderno em
branco→cinza-claro (#FFFFFF → #C5CDD8), com sombra suave; detrás do H, uma
placa **cinza translúcida** (efeito vidro/transparência). Cantos transparentes
(RGBA). Nos tamanhos 16–24 o desenho é simplificado (sem reflexo; H mais grosso)
para ficar nítido.

## 10. Construção e instalador (`construir/`)

`python construir/construir.py (--modelo PASTA | --sem-modelo) [--sem-falantes] [--saida PASTA] [--cache PASTA] [--python-tar ARQ] [--marca]`
(roda em Linux — aqui e no CI — e no Windows); `python construir/construir.py
--versao` só imprime a versão que será construída (`helestron.__version__`),
que o CI compara com a tag. Uma das duas, `--modelo` ou `--sem-modelo`, é
obrigatória: sem elas, a mensagem traz `COMANDOS_CONVERSAO`.

1. Baixa o Python Windows (python-build-standalone 3.12.10, SHA-256 conferido).
2. Baixa as rodas **win_amd64/cp312** de `requisitos-windows.txt` (travado com
   hash). Pacote só em código-fonte e puro Python (ex.: `proxy_tools`) é
   convertido em roda localmente.
3. Instala as rodas na pasta do Python (biblioteca `installer`, esquema Windows;
   arquivos de dados de `msvc-runtime` na raiz). Copia o pacote `helestron`
   **inteiro** para `Lib/site-packages` (a pasta toda, sem lista de
   módulos: um módulo novo, como `nucleo/paginacao.py` ou
   `download/acompanhamento.py`, entra sem mexer aqui) e confere que nenhum
   `.py` ficou para trás; se faltar algum, a construção para.
4. Enxuga (remove `*.pdb`, `Lib/test`, `idlelib`, `__pycache__` estranhos,
   `Scripts` desnecessários) e **pré-compila** tudo em `.pyc`
   (`UNCHECKED_HASH`).
5. Modelo `faster-whisper-small` **em int8** em `modelos/`, de `--modelo
   PASTA`; `--sem-modelo` gera instalador sem ele (o programa baixa no
   primeiro uso). `conferir_modelo` roda antes do trabalho pesado: exige
   `model.bin`, `config.json`, `tokenizer.json` e `vocabulary.*` e recusa um
   `model.bin` fora de 150 a 350 MB (`LIMITES_MODELO`: o float16 publicado
   no Hugging Face tem ~484 MB e estouraria o limite do Setup; abaixo, a
   cópia interrompida). Os comandos que convertem o whisper-small oficial
   para int8 são `COMANDOS_CONVERSAO`, os mesmos do CI (um teste confere).
   Depois, os modelos da separação de falantes (GitHub, SHA-256 conferido):
   a falha deles **interrompe** a construção (sai com 1, citando
   `--sem-falantes`), porque o manual promete a separação de vozes sem
   internet; só `--sem-falantes` gera, de propósito, um instalador sem
   eles.
6. Compila o lançador `Helestron.exe` (MinGW: `lancador/helestron.c` +
   `.rc` com ícone, informações de versão e manifesto: DPI PerMonitorV2,
   longPathAware, Windows 10/11). O lançador carrega `python312.dll` pelo
   caminho completo (`LoadLibraryExW`; se faltar ou não carregar, mostra
   mensagem clara em português) e, **antes do `Py_Main`**, confere os
   arquivos de partida, sem os quais nem a tela de erro do programa abre (o
   Python sem `Lib\encodings` não inicia; sem o `__main__`, o `registro` ou
   o `caminhos` do pacote, ele fecharia sem dizer nada): `Lib\encodings\__init__`
   e, em `Lib\site-packages\helestron\`, `__init__`, `__main__`,
   `nucleo\__init__`, `nucleo\caminhos`, `nucleo\registro`,
   `aplicativo\__init__`, `aplicativo\inicio`, `aplicativo\integridade` e
   `aplicativo\erro`, cada um como `.py` ou como `.pyc` ao lado. Se faltar
   algum, a caixa “O Helestron não pôde abrir” diz “Falta um arquivo do
   programa:” com o caminho, a hipótese do antivírus (ou da instalação
   interrompida) e a orientação de reinstalar com o Helestron-Setup, sem
   perder os dados. Depois, chama `Py_Main` com `-I -m helestron` +
   argumentos. Aberto sem argumentos (pelo atalho), o lançador vigia as
   janelas do processo (`SetWinEventHook`): se o programa sair com código
   diferente de 0 em menos de 20 s (`PRAZO_SAIDA_RAPIDA_MS`) sem ter
   mostrado janela nenhuma, a caixa “O Helestron fechou logo depois de
   começar, sem abrir a janela (código N).” aponta `%LOCALAPPDATA%\Helestron\Logs`
   (ou `HELESTRON_LOCAL\Logs`) e pergunta “Deseja abrir a pasta do registro
   agora?”. Nas chamadas do instalador (`--encerrar`, `--verificar-instalacao`)
   nunca há caixa: quem informa é o instalador, pelo código de saída.
   Códigos de saída do próprio lançador (o resto vem do Python): 3 (o
   `python312.dll` falta ou não carrega), 4 (o DLL não é o esperado: sem
   `Py_Main`), 5 (sem memória, ou a pasta do programa não foi localizada) e
   6 (falta um arquivo de partida). Arquivo solto sobre o ícone: quando
   todos os argumentos são caminhos completos (`C:\…`, `\\servidor\…`) de
   arquivos ou pastas que existem, o lançador abre o programa como pelo
   atalho, com a mesma vigia de saída rápida; comando, opção, caminho
   relativo e arquivo que não existe seguem para a linha de comando, como
   antes. Na mesma etapa, `gravar_comando` grava na raiz da árvore o
   `helestron.cmd` (`CONTEUDO_COMANDO`: só ASCII, CRLF, `@echo off` e, como
   último comando, `"%~dp0python.exe" -I -m helestron %*`, para o código de
   saída do `.cmd` ser o do Python). Por estar na árvore, ele entra no
   manifesto (a `--verificar-instalacao` confere o SHA-256) e na lista
   `arquivos-instalados.txt` (a desinstalação o apaga).
7. Gera `manifesto.json`: versão, `componentes` (`{modelo_transcricao:
   "faster-whisper-small" ou "", falantes: bool}`, lidos da própria árvore,
   para a verificação saber se a falta de um modelo é defeito ou uma
   construção sem ele: o modelo ou os modelos de voz declarados e ausentes
   da pasta do programa são FALHA no Diagnóstico, com a ação de reinstalar;
   `integridade.py` ignora a chave) e o SHA-256 e o tamanho de cada arquivo.
8. Gera as imagens da marca, a lista do que a instalação põe na pasta do
   programa (`construir.gerar_registro`, a partir de
   `construir.linhas_do_registro`: `arquivos-instalados.txt`, em UTF-16 com
   BOM e CRLF, que o `FileReadUTF16LE` do NSIS lê com qualquer caractere; o
   cabeçalho “Helestron <versão> - arquivos instalados nesta pasta…”, uma
   linha `A <arquivo>` por arquivo, com o `Desinstalar.exe`, o
   `manifesto.json` e a própria lista por último, e depois `P <pasta>`, das
   mais fundas para as de cima) e o script NSIS (`@REGISTRO@`: a lista desta
   versão vai embutida no instalador), e roda `makensis` →
   `dist/Helestron-Setup-1.1.0.exe` + `.sha256`. O Setup acima de 500 MiB
   (`LIMITE_SETUP`, o limite para entrega por anexo) é recusado e apagado
   de `dist`.

Instalador NSIS (`instalador/helestron.nsi`): Unicode, MUI2, **Português do
Brasil**, `RequestExecutionLevel user`, pasta padrão
`$LOCALAPPDATA\Programs\Helestron`, LZMA sólido. Páginas: boas-vindas (imagem da
marca), pasta, opções, instalação e concluir (“Pronto!”, com ☑ “Abrir o
Helestron”; com `MUI_FINISHPAGE_TEXT_LARGE`, o texto aparece inteiro a 100 %
e a 125 %, e saiu dele a frase “Clique em Concluir para fechar este
assistente.”, que só repetia o botão). Seções: programa (obrigatória) e
atalho na Área de Trabalho (marcada). Atalho no Menu Iniciar e na Área de
Trabalho com o ícone. Registro em `HKCU\...\Uninstall\Helestron` (nome,
ícone, versão, editor, tamanho, `InstallLocation`) e em
`HKCU\Software\Helestron` (`CHAVE_PROGRAMA`: `Python` = `$INSTDIR\python.exe`,
`Versao` e `InstallLocation`), para quem chama o programa de fora; o PATH
não é alterado. Modo silencioso (`/S`, `/D=`) para a TI e o CI.

1. **Pasta só do Helestron e com permissão.** Ao sair da página da pasta
   (`MUI_PAGE_CUSTOMFUNCTION_LEAVE ConferirPasta`) e de novo no começo da
   seção do programa (para o `/S /D=`, que não tem a página),
   `ConferirDestino` vem antes do teste de permissão. A pasta escolhida
   serve se não existe, se está vazia (`PastaVazia`; a `.antigos` que o
   RunOnce do próprio Helestron vai apagar não conta) ou se já é do
   Helestron (`EhDoHelestron`: tem a `arquivos-instalados.txt` com o
   cabeçalho “Helestron …” ou, numa instalação de antes da lista, o
   `manifesto.json` com `"nome": "Helestron"`), e então é uma atualização.
   Se ela existe, tem outras coisas e não é do Helestron, o programa vai
   para `<pasta>\Helestron`, para nada se misturar (uma pasta `Lib`,
   `Scripts` ou `modelos` do usuário receberia arquivos do programa): na
   página, o assistente pergunta antes (“A pasta escolhida já tem outros
   arquivos: … Para não misturar o Helestron com eles, ele será instalado
   numa pasta própria dentro dela: … Clique em OK para continuar ou em
   Cancelar para escolher outra pasta.”), e o campo passa a mostrar o
   caminho novo (por `WM_SETTEXT`: o NSIS relê o campo depois da função de
   saída e o mostra de novo no Voltar); no `/S /D=`, ajusta sem perguntar e
   registra no detalhe. Se a subpasta `Helestron` já tem o Helestron (o
   mesmo `/D=<pasta>` repetido na versão seguinte), é uma atualização como
   as outras: a seção decide pela pasta final (`EhDoHelestron` de
   `$INSTDIR`), e a versão anterior sai pela lista dela. Se a subpasta
   `Helestron` também tiver outras coisas, a instalação é recusada: na página, com a mensagem “A pasta
   escolhida já tem outros arquivos, e a pasta Helestron dentro dela
   também: …”, e a página continua; no `/S`, com o código **3**, sem copiar
   nada. Depois, `PodeGravarNaPasta` cria a pasta e grava um arquivo de
   teste; sem permissão, a mensagem “Não há permissão para gravar na
   pasta…” (a sugerida não precisa de administrador) e a página continua. O
   mesmo teste abre a seção do programa, para o `/S /D=`: sem permissão,
   código **8** e nada copiado. As mensagens de erro de arquivo
   (`^FileError` e `^FileError_NoIgnore`) citam as duas causas e os botões
   que o Windows mostra de fato: “Se o Helestron (ou o Claude Desktop)
   estiver aberto, feche-o e clique em Repetir. Se a pasta escolhida exigir
   administrador, clique em Anular e instale na pasta sugerida. Ignorar
   pula este arquivo.” (na caixa sem Ignorar, “clique em Cancelar”). O
   `MB_ABORTRETRYIGNORE` do Windows em português mostra **Anular**,
   **Repetir** e **Ignorar**; o “Abortar” do `PortugueseBR.nlf` (e do Wine)
   não existe na tela. (No Wine em inglês, os botões das caixas aparecem
   como “Cancel”, “Yes” e “No”; os textos citam só os nomes do Windows em
   português.)
2. **Fechar o Helestron sem cortar a audiência.** `FecharHelestron` roda
   `Helestron.exe --encerrar` (seção 5). Código 10 (audiência em
   andamento): no modo interativo, “Há uma audiência sendo transcrita no
   Helestron…”, com Repetir/Cancelar (“encerre a audiência no Helestron
   (botão Encerrar: o documento é salvo) e clique em Repetir”); no `/S`, ou
   com Cancelar, desiste com o código **7**, sem mexer em nada.
3. **Arquivos presos, sem matar processo.** `EsperarArquivosLivres` tenta
   abrir o `python312.dll` para gravação. Se o Helestron fechou e outro
   processo do programa ainda prende os arquivos (o servidor MCP do acervo,
   aberto pelo Claude Desktop ou pelo Codex com o `python.exe` daqui), depois
   de 10 s marca `$Afastar`: `LiberarArquivos` renomeia o `python312.dll`
   para `.antigos\<instante>` (o Windows deixa renomear um arquivo em uso,
   não apagar) e, na remoção, `RemoverArquivo` renomeia para lá cada arquivo
   da lista que não puder ser apagado. Se nem a renomeação do
   `python312.dll` der certo, volta ao caminho de sempre (esperar e
   perguntar) antes de apagar qualquer coisa. `AgendarLimpeza` grava em
   `HKCU\...\RunOnce` o `rundll32 advpack.dll,DelNodeRunDLL32` da pasta
   `.antigos` (sem console nem administrador), e `inicio.limpar_antigos`
   apaga os restos na próxima abertura. Nenhum processo é encerrado (nada de
   `taskkill`/`TerminateProcess`). Se o próprio Helestron não fechou, espera
   20 s e pergunta; no `/S`, código **4**.
4. **Remove a versão anterior do programa, pela lista dela** (nunca os
   dados; nenhuma pasta é apagada inteira pelo nome, como `Lib`, `DLLs`,
   `modelos`, `Scripts`, `share`, `tcl`, `include` ou `libs`). Só numa
   atualização (`ConferirDestino` devolveu `atualizacao`),
   `RemoverPrograma` lê `$INSTDIR\arquivos-instalados.txt` (sem ela, numa
   instalação de antes da lista, usa a lista desta versão, que vai embutida
   no instalador) e apaga, um a um, os arquivos das linhas `A`
   (`RemoverArquivo`); as pastas das linhas `P` só saem se ficarem vazias,
   com exceção das `__pycache__` do programa, onde só o Python grava. A
   própria lista sai por último. Depois, copia a nova: primeiro a lista
   desta versão (uma cópia interrompida ainda é reconhecida e removida pela
   próxima instalação), depois os arquivos. Arquivos e pastas do usuário que
   estiverem na pasta ficam. Limitação conhecida: numa instalação feita por
   uma construção anterior à lista, os arquivos que só aquela construção
   tinha (módulos renomeados entre construções da 1.0.0) podem ficar na
   pasta; nada do usuário é apagado, e a próxima atualização já parte da
   lista gravada. A atualização com a lista leva cerca de 12 s a mais (8.192
   linhas).

   **Instalação registrada em outra pasta.** `OutraInstalacao` (macro com a
   versão `un.`) lê o `InstallLocation` da chave de desinstalação, compara
   com `$INSTDIR` sem diferença de maiúsculas e sem a barra do fim e
   confere `EhDoHelestron`. Se o Helestron registrado está em OUTRA pasta
   (o `/D=` ou o Procurar escolheram outra), logo depois de
   `PodeGravarNaPasta` ele passa pelo caminho de uma atualização, na pasta
   dele: `FecharHelestron` (a audiência em andamento dá o código 7 antes de
   qualquer mudança), `EsperarArquivosLivres`, `.antigos`,
   `LiberarArquivos` e `RemoverPrograma` pela lista dele; depois saem o
   `Desinstalar.exe`, a pasta (só se ficar vazia) e os atalhos dela, e
   `$INSTDIR` volta à pasta nova. Sem isso, o antigo ficava aberto e órfão
   (sem entrada em Aplicativos, e com um desinstalador que apagaria a chave
   e os atalhos da nova). No modo interativo, `ConferirPasta` avisa antes
   (“O Helestron já está instalado em outra pasta: … Ele será fechado e
   removido de lá e instalado na pasta escolhida…”, com OK/Cancelar).
5. **Restos do Assessor Integrado** (a versão anterior). Depois de copiar,
   `ApagarAtalhoAntigo` tira “Assessor Integrado.lnk” da Área de Trabalho
   (`$DESKTOP`) e do Menu Iniciar (`$SMPROGRAMS`), só quando o atalho, lido
   pelo próprio Windows (`IShellLinkW` e `IPersistFile::Load`), aponta para
   `…\runtime\python\pythonw.exe` com o `iniciar.pyw` nos argumentos; um
   atalho de mesmo nome que aponte para outra coisa fica. Em seguida, roda
   num processo à parte, sem console e sem esperar (`Exec`),
   `pythonw.exe -I -c "from helestron.compartilhar import migracao; migracao.limpar_restos_antigos()"`:
   `migracao.limpar_restos_antigos()` tira só os conectores da versão
   anterior (`assessor-integrado` e `assessor_integrado`, nomes em
   `claude.NOMES_ANTIGOS` e `chatgpt.NOMES_ANTIGOS`) do Claude Desktop
   (`claude_desktop_config.json`) e do Codex/ChatGPT Work
   (`%USERPROFILE%\.codex\config.toml`), guarda antes uma cópia de cada
   arquivo ao lado (`…antes-do-helestron-<data>`), não toca arquivo com JSON
   ou TOML inválido, nunca levanta e devolve o que fez, em frases. Ela também
   chama `migracao.reapontar_conectores()`: no programa instalado, o conector
   `helestron` registrado com o `python.exe` de outra pasta (a instalação que
   mudou de lugar) passa a usar o desta, com a mesma pasta do acervo (o
   `--pasta` da entrada antiga); com o comando já certo, nada muda. No Codex,
   só o comando e os argumentos mudam: as outras chaves do bloco ficam
   (`chatgpt.bloco_toml(..., manter=)`), e o conector que o usuário desligou
   (`enabled = false`) continua desligado. A limpeza
   nunca segura nem derruba a instalação. A mesma função existe como linha
   de comando, `python -I -m helestron.compartilhar.migracao` (sai sempre
   com 0, em cerca de 0,1 s), e como `helestron.compartilhar.limpar_restos_antigos()`,
   de importação leve. O conector antigo que sobrar aparece no Diagnóstico
   (“o Claude Desktop ainda tem o conector da versão anterior (Assessor
   Integrado)”, e o mesmo para o ChatGPT/Codex), e conectar o acervo de novo
   também o tira.
6. **Conferência final.** `Helestron.exe --verificar-instalacao`. Saída 0:
   “Instalação conferida: tudo certo.”; saída 9 (os arquivos estão certos,
   mas sem WebView2, sem Edge e com o Internet Explorer de navegador padrão
   não há como abrir a janela): código **9** e uma mensagem própria (“O
   Helestron foi instalado, mas este computador não tem como abrir a janela
   dele…”, com o pedido de instalar o Microsoft Edge WebView2 Runtime);
   qualquer outra: código **2**, o resumo e onde está o relatório.

Códigos de saída do instalador:

| Código | Significado |
|---|---|
| 0 | instalado e conferido |
| 2 | copiado, mas a conferência final encontrou problemas (ou não terminou) |
| 3 | a pasta escolhida e a subpasta `Helestron` dentro dela já têm arquivos de outro programa ou do usuário: nada foi copiado (`PASTA_OCUPADA`) |
| 4 | o Helestron não fechou e continuou prendendo os arquivos do programa |
| 5 | outro instalador do Helestron já estava aberto (mutex `HelestronSetup`) |
| 6 | Windows não suportado (32 bits ou anterior ao Windows 10) |
| 7 | audiência sendo transcrita no Helestron (o `--encerrar` devolveu 10): nada foi alterado; rodar de novo depois |
| 8 | sem permissão para gravar na pasta escolhida |
| 9 | instalado e conferido, mas o computador não tem como abrir a janela (falta o WebView2 Runtime) |

Desinstalador: fecha o programa (`FecharHelestron`, com a mesma recusa e o
mesmo código 7 durante uma audiência), retira **os dois conectores** do
acervo, que apontam para o `python.exe` daqui e, sem o programa, só dariam
erro — `claude.remover_mcp()` (Claude Desktop) e
`chatgpt.remover_mcp_codex()` (Codex/ChatGPT Work,
`%USERPROFILE%\.codex\config.toml`), em dois processos separados, para a
falha de um não impedir o outro; os dois tiram também os nomes da versão
anterior e guardam antes uma cópia do arquivo
(`claude_desktop_config.antes-do-helestron-<data>.json`,
`config.antes-do-helestron-<data>.toml`) —, remove o programa só pela lista
da instalação (`RemoverPrograma`, com a mesma renomeação dos arquivos
presos) e os atalhos, apaga a pasta do programa só se ela ficar vazia,
apaga os valores `Python`, `Versao` e `InstallLocation` de
`HKCU\Software\Helestron` (a chave, com `DeleteRegKey /ifempty`),
pergunta se apaga também configurações e senhas (padrão: não; no `/S`,
mantém) e **nunca** apaga `Documentos\Helestron`. As sessões dos portais e
os perfis do navegador (`$LOCALAPPDATA\Helestron\perfis`) saem **sempre**,
também no `/S`, depois de `un.EsperarArquivosLivres` e antes da pergunta
(que não os cita mais e diz que eles já foram apagados); o que ficar em uso
é avisado no detalhe. O desinstalador de uma cópia que não é a registrada
(`un.OutraInstalacao`) tira só o programa dela: a chave de desinstalação,
os atalhos, `HKCU\Software\Helestron`, os conectores e a pergunta sobre os
dados ficam com a instalação registrada.

## 11. CI (`.github/workflows/helestron.yml`)

* **testes** (ubuntu): unittest completo (+ Playwright Chromium para a
  interface em modo demonstração e para `testes/test_ponta_a_ponta.py`, que
  sobe o programa real e percorre a interface contra portais falsos locais;
  capturas de `HELESTRON_CAPTURAS` como artefato).
* **construir** (ubuntu): o primeiro passo reprova, numa tag, a que não é
  `v<versão>` (`construir.py --versao`), antes do trabalho pesado; apt
  `nsis` e `mingw-w64`; converte o whisper-small oficial para int8 com o
  mesmo CTranslate2 do instalador (os comandos de `COMANDOS_CONVERSAO`) e
  confere o `model.bin` (150 a 350 MB) e que ele carrega em int8;
  `construir.py --modelo` (sem `--sem-falantes`: a falha dos modelos de voz
  reprova); confere que o Setup cabe em 500 MiB; artefato
  `Helestron-Setup`. O CI não instala mais o `huggingface_hub`.
* **windows** (windows-latest, depende de construir): antes de instalar,
  cria os restos do Assessor Integrado (o atalho antigo, que aponta para o
  `pythonw.exe` do runtime dele com o `iniciar.pyw`; um atalho de mesmo nome
  que não é dele; e o conector `assessor-integrado` no Claude Desktop, ao
  lado de um servidor “outro”); instala em silêncio (`/S`), confere arquivos
  (também a `arquivos-instalados.txt`, o `helestron.cmd`, `nucleo\paginacao.py`,
  `download\acompanhamento.py` e os dois `.onnx` da separação de falantes),
  o `manifesto.componentes`, os atalhos, a chave de desinstalação e
  `HKCU\Software\Helestron` (`Python`, `Versao` e `InstallLocation` iguais
  aos da instalação; o PATH sem a pasta do programa) e que o atalho e o
  conector antigos saíram, mas o atalho alheio e o servidor “outro”
  ficaram; `--verificar-instalacao`; a linha de comando como a skill do
  Claude a chama (passo “Linha de comando”: pelo `helestron.cmd` e pelo
  Python do registro, com a saída em UTF-8, `--version` igual ao do
  registro, `caminhos --json` com `python` e `instalacao` iguais aos do
  registro e `instalado` verdadeiro, `baixar --help` com 0, uma opção
  inválida com 2 e `pauta listar --json` com 0); `--autoteste`
  (capturas da janela real, também copiadas para o registro em JPEG reduzido
  e base64), transcrição de ponta a ponta com fala sintetizada
  (System.Speech) pela linha de comando, servidor MCP por JSON-RPC (e o
  conector registrado também no Codex), exportação da pauta, cofre DPAPI;
  reinstalação por cima **com o servidor MCP aberto** (exige código 0, o MCP
  vivo, os arquivos presos em `.antigos`, o RunOnce agendado e o
  `limpar_antigos` apagando os restos depois que o MCP sai); desinstalação
  silenciosa (dados e configuração preservados; conectores do Claude
  Desktop e do Codex, `HKCU\Software\Helestron`, o `helestron.cmd` e uma
  sessão de portal criada antes, em `perfis\`, retirados); por fim,
  instalação e desinstalação com `/D=` numa pasta que
  já tem arquivos do usuário, em pastas `share`, `Scripts`, `Lib` e
  `modelos` (o Helestron vai para `<pasta>\Helestron`, e nada do usuário
  sai nem muda). Os cenários dos códigos 3, 7, 8 e 9, do servidor MCP
  aberto, da desinstalação com os dois conectores, da pasta nova, da pasta
  com arquivos do usuário, da atualização (da 1.0.0 para a 1.0.1 e de uma
  instalação sem a lista) e da migração do Assessor Integrado têm também um
  teste no Wine, com o `.nsi` de verdade e um programa falso
  (`testes/test_construir.py`, `TestInstaladorNoWine`; roda quando há o
  makensis, o MinGW-w64 e o Wine de 64 bits), e o lançador tem os seus
  (`TestLancadorNoWine`: os arquivos de partida e a saída rápida sem janela,
  inclusive os casos em que nenhuma caixa deve aparecer: o programa mostrou
  a janela, foi chamado com argumentos ou pelo instalador).
* **publicar** (tags `v*`, ou o disparo manual “publicar” no `main`): cria a
  versão no GitHub com o instalador e o `.sha256`. A versão sai sempre do
  nome do único `Helestron-Setup-*.exe` testado (com dois ou nenhum, falha),
  e a tag que não bate com ela reprova a publicação (a `v1.0.2` com o
  Setup da 1.0.1 publicaria a versão errada e ocuparia a tag). No disparo
  manual, a tag que já existe em outro commit (empurrada antes, com o run
  reprovado) também reprova: o `gh release create` ignora o `--target`
  quando a tag existe, e penduraria o instalador deste commit na tag de
  outro código; sem conseguir consultar a tag na API, não publica. Os testes
  rodam os scripts reais desses passos no bash, com um `gh` falso.

## 12. Regras transversais (valem para todos)

* **Sigilo** (invariantes do motor, não podem regredir).
  * **Uma regra só** (`nucleo/sigilo.py`). O processo é sigiloso se
    qualquer uma destas fontes o diz: (1) os **autos** estão na pasta dos
    sigilosos (`<sigilosos>\<número>.pdf` ou `<sigilosos>\<lote>\<número>.pdf`,
    como o download grava); (2) há **transcrição, gravação ou diário** de
    audiência dele em `<sigilosos>\Transcricoes` (ou em `Transcricoes\_audio`):
    a audiência que já foi sigilosa uma vez continua sigilosa; (3) a
    **pauta** o marca sigiloso em qualquer registro (do portal, do
    relatório importado, já fora da pauta: `Armazem.sigilosas`, contrato
    C4) — o sigilo é do processo, não da linha —, e a pauta só marca com
    indicação positiva e inequívoca (seção 8.5); (4) um **download** já o
    apurou: o portal mostrou o selo (o resultado sigiloso, o
    `SigilosoSemSenha`, os `sigilosos_apurados` do portal) ou um relatório
    anterior do lote o deu como sigiloso. O motor o guarda
    (`sigilo.lembrar_do_download`, em `LOCAL/download.sigilo.json`, ao lado
    do registro da pauta: `arquivo_do_download`, `apuradas_no_download`)
    antes de levar o PDF para o lote; com a separação dos sigilosos
    desligada, os autos ficam no acervo, e é por esse registro que o
    preparo, o MCP, o pacote, a nuvem e a transcrição o deixam de fora. O
    sigilo que vem só do relatório anterior do lote (ou da capa) vai para
    o registro só quando nem a pasta dos sigilosos nem a pauta o dão
    (`motor._sigilo_so_do_relatorio`): o relatório marca também o que o lote
    só TRATOU como sigiloso por elas, e o registro diria que o portal o
    apurou. Se o registro não puder ser gravado (`_lembrar_sigilo` devolve
    `False`), o motor falha para o lado seguro: os autos vão para a pasta de
    sigilosos mesmo com a separação desligada (`_separar`), com
    `SEM_REGISTRO_DO_SIGILO` no detalhe, e a regra os vê pela pasta. A
    gravação dos dois registros (`_acrescentar`) passa uma de cada vez
    também entre processos (a janela, o `baixar`, o conector:
    `cofre_senhas.travado`, a trava `<registro>.trava` com O_EXCL, que vale
    por até `ESPERA_TRAVA_S` e é abandonada depois de `TRAVA_ABANDONADA_S`)
    e insiste no arquivo preso, na leitura e na troca (`TENTATIVAS` ×
    `ESPERA_S`, `cofre_senhas.gravar_privado`); (5) com o acervo (`raiz`),
    o **relatório de um lote** dentro dele o dá como sigiloso
    (`sigilo.sigilosos_dos_relatorios`: `relatorio.csv` e
    `relatorio (atualizado).csv` de cada `<lote>/_controle`, em largura até
    `PROFUNDIDADE_LOTES` = 3 níveis abaixo do acervo, sem `_ia`, `_audio`,
    pastas ocultas e atalhos; os dois primeiros níveis e as pastas dos lotes
    de `Processos` inteiros e, abaixo deles, no máximo `MAX_PASTAS`, com
    `Processos` primeiro; cada relatório
    relido só quando muda a data ou o tamanho; “sim” na coluna `sigiloso`,
    UTF-8 com BOM ou, salvo pelo Excel, cp1252; a linha mascarada não
    conta). É o que cobre o lote baixado com a separação desligada antes do
    registro (versão anterior) ou depois de ele se perder (LOCAL apagada,
    acervo noutro computador); `chaves_sigilosas` acrescenta ao registro
    do download o que só o relatório conhece (não o que a pasta ou a pauta
    já dão), e o `preparar --pasta` soma o relatório da própria pasta; (6)
    com o acervo, a **capa do 2º grau de um originário** (HC, MS, AI de
    órgão `0000`; originário de turma recursal, `9xxx`), guardada em
    `<lote>/_controle/<número> (2G)_capa.json`, lista em
    `numeros_1a_instancia` uma ação de origem sigilosa por qualquer das
    fontes anteriores (`sigilo.herdadas_das_origens`: as mesmas pastas
    `_controle` e o mesmo limite de acervo grande; só as capas de
    originários são abertas — não a da apelação nem a do recurso interno
    dela, cuja origem é o próprio número —, cada uma relida só quando muda
    a data ou o tamanho). O motor já trata o originário como sigiloso no
    download, se a origem já se sabe sigilosa; esta fonte cobre a origem
    que vira sigilosa depois. `chaves_sigilosas` acrescenta o originário ao
    registro do download, e o `preparar --pasta` soma as capas da própria
    pasta.
    `sigilo.chaves_sigilosas` dá todos; `sigilo.motivo` diz por quê (“os
    autos, uma transcrição ou uma gravação dele estão na pasta dos
    sigilosos”, “a pauta de audiências indica que ele corre em segredo de
    justiça” ou “um download anterior apurou que ele corre em segredo de
    justiça”). O banco da
    pauta só é lido se já existir e só para consulta: `chaves_da_pauta` não
    abre o `Armazem`, mas o SQLite em `file:…?mode=ro` (a URI montada à
    mão, com `%XX`, para servir a `C:/` e a `\\servidor`), com `PRAGMA
    query_only` e um `SELECT` direto — não roda o esquema, não grava, não
    renomeia nem põe de lado o banco estragado (isso é com a pauta, ao
    abrir). O resultado fica guardado enquanto o banco (e o WAL) não muda,
    por até 30 s; banco ilegível ou ocupado não derruba quem pergunta: vale
    o que se leu da última vez, e o registro diz que a pauta não pôde ser
    lida. Ao banco soma-se o registro do apurado, **fora** dele
    (`LOCAL/pauta.sigilo.json`: `arquivo_apurado`, `apuradas_da_pauta`,
    `lembrar_da_pauta`, `lembrar_do_banco`), que só recebe acréscimos
    (gravação atômica; o registro ilegível não é sobrescrito) e vale mesmo
    sem o banco, perdido, estragado ou refeito: o sigilo, uma vez apurado,
    fica. A pasta dos sigilosos é procurada em largura até
    `PROFUNDIDADE_MAX` = 4 níveis: os dois primeiros inteiros e, abaixo
    deles, no máximo `MAX_PASTAS` = 2000 pastas (com aviso no registro),
    sem as `_controle` abaixo do 1º nível, as pastas ocultas e os atalhos
    ou junções. Contam o PDF em qualquer subpasta, o DOCX em
    `Transcricoes\**` e tudo o que estiver em `Transcricoes\**\_audio`
    (inclusive pastas); o número sai do nome inteiro (`p.name`, e não
    `p.stem`, que quebrava nome de pasta com pontos), em qualquer posição
    dele, também na consulta de um número só (`na_pasta`):
    “Audiência - <número>.docx” e os 20 dígitos contam. Consultam essa mesma regra o compartilhamento
    (`INDICE.md`, `CLAUDE.md`/`AGENTS.md`, `_ia/texto`, o MCP, o pacote e o
    espelho na nuvem), o download e a transcrição (tela, linha de comando e
    gravação enviada). O MCP apura a listagem do acervo e a regra uma vez
    por pedido (`Acervo.pedido()`, seção 5).
  * **O incidente herda o sigilo do principal.** O incidente (`…0001-01`, o
    cumprimento de sentença, por exemplo) tem as partes e o conteúdo do
    principal: se o principal é sigiloso, ele também é. O contrário não
    vale: o principal não fica sigiloso só por causa de um incidente.
    `sigilo.principal()` dá o principal de um incidente, e `sigilo.contem()`
    e a classe `Sigilosas` (um `frozenset` em que `chave in sigilosas` vale
    também para `<principal>-NN`) fazem a herança; `chaves_sigilosas`,
    `chaves_na_pasta` e `chaves_da_pauta` devolvem `Sigilosas`, e `na_pasta`
    e `na_pauta` herdam (o parâmetro `herdar=False` desliga). Os motivos
    dizem quando o sigilo vem do principal (`motivo_da_pasta`,
    `motivo_da_pauta`, `MOTIVO_PASTA_PRINCIPAL`, `MOTIVO_PAUTA_PRINCIPAL`):
    na tela, “Este processo é incidente de um processo sigiloso: …”; na
    linha de comando e no relatório do lote, “é incidente de um processo
    sigiloso: …”. Com isso, o índice, o MCP, a nuvem, o pacote, o preparo, o
    download (`motor._motivo_sigilo` e os relatórios anteriores do lote) e a
    transcrição herdam, e retirar do acervo o principal leva também os
    incidentes (o recurso interno do 2º grau, `…-50000`, é incidente do
    principal para a regra).
  * **O sigilo vale nos dois graus** (1.1.0). A regra continua por
    processo, sem grau: `sigilo.contem` normaliza a chave dos autos
    (`X (2G)`, `X-01 (2G)`, um `Numero` ou um nome de arquivo) para a do
    processo antes de comparar, e o sigilo apurado num grau tira do acervo,
    do índice, do MCP, do pacote e da nuvem os autos dos dois
    (`motor.retirar_do_acervo` leva `X` e `X (2G)` de cada lote, com capa,
    registro e gravações; `_motivo_sigilo` lê a capa guardada dos dois
    graus; `_apagar_texto_da_ia` apaga de `_ia/texto` todo texto do
    processo e dos incidentes dele, nos dois graus, mesmo com o PDF do
    incidente fora do 1º nível das pastas de lote). O originário do 2º grau
    (órgão `0000`, e o originário de turma recursal, `9xxx`), que tem número
    próprio, herda o sigilo da ação de origem: com o item OK no 2º grau e
    antes de os autos irem para o lote, o motor lê a lista
    `numeros_1a_instancia` do nível de cima do `_capa.json`
    do 2º grau (só o e-SAJ a traz) e, se algum desses números já se sabe
    sigiloso pela regra única, marca o item (`r.sigiloso`, “tratado como
    sigiloso: o processo de origem X é sigiloso”) e o registra
    (`_lembrar_sigilo`). A herança vale também depois do download: com o
    acervo, `chaves_sigilosas` relê a capa guardada em `_controle` (a
    fonte 6, acima), e a origem que só vira sigilosa mais tarde — a
    apelação dela baixada com o selo, os autos levados à pasta dos
    sigilosos, a pauta — leva o originário à pasta dos sigilosos no
    próximo preparo e o tira do índice, do MCP, do pacote e da nuvem.
    **Risco aceito:** o sigilo sabido só em outro
    computador (o da vara) não chega ao do gabinete do 2º grau; o manual o
    diz.
  * **Nada sigiloso vai para a IA nem para a nuvem.** Processo sigiloso
    nunca vai para a IA, o pacote, o espelho na nuvem (nem na subpasta
    antiga `Assessor Integrado - Acervo`), o MCP, o texto em `_ia/texto` ou
    o índice e, com a separação dos sigilosos ligada (o padrão), não fica
    no acervo; a pasta da nuvem nunca fica dentro do acervo nem o contém,
    e a pasta dos sigilosos (e a da pauta exportada) nunca fica dentro do
    acervo, nem o acervo dentro dela. A pasta dos sigilosos e a da pauta
    também não ficam dentro da pasta da nuvem, não são ela nem a contêm
    (`config.conflito_com_a_nuvem`, que usa só a pasta da nuvem escolhida):
    a regra vale em `esquema.conferir_pastas` (cada chave confere só a sua
    pasta, para um conflito antigo editado à mão não travar a correção de
    outra), no `POST …/nuvem/espelhar` (400 `pastas_em_conflito`, e o
    destino não fica gravado), no espelho automático (`nuvem_sem_conflito`
    pula, com aviso no registro), na pendência `nuvem` do Início, na
    verificação (`checar_pastas`; `checar_local` aponta, primeiro e como
    regra, não como recomendação, a pasta dos sigilosos ou da pauta em
    qualquer pasta do OneDrive ou do Google Drive, `verificar.nuvem_da_pasta`:
    aviso, como os conflitos de `checar_pastas`, com “Corrija:” e os
    conselhos de conforto depois) e, por último, no próprio `nuvem.espelhar`
    (`_recusar_sigilosos_na_nuvem`, antes de copiar ou apagar qualquer
    coisa, também para a subpasta antiga). Além disso, a pasta dos
    sigilosos e a da pauta não ficam em NENHUMA pasta do OneDrive ou do
    Google Drive (`servicos.sigilo_na_nuvem`, pelo caminho, com a regra de
    `verificar.nuvem_da_pasta` sem varrer as unidades; o caminho cobre tudo
    o que `nuvem.detectar` procura, inclusive `%USERPROFILE%\Meu Drive` ou
    `My Drive`, a do Google Drive no modo espelho, e por isso a verificação
    e a regra dizem o mesmo): `problema_nas_pastas` a inclui (o `baixar` e o
    `caminhos --json` também), e `esquema.conferir_pastas` a aplica só à
    pasta que está sendo trocada, com a frase da escolha (`ao_escolher`: a
    pasta recusada não é gravada, e a frase não manda mover o que está na
    atual).
    Enquanto as pastas estiverem misturadas, o download, o preparo, as
    ferramentas e o espelho recusam com 409 `pastas_em_conflito` (seção 6.3). O espelho que não consegue
    apagar da nuvem a cópia de um processo sigiloso faz o resto e depois
    levanta `SigilosoNaNuvem`, com o arquivo e a pasta a limpar à mão (antes
    de desistir, tira o atributo somente leitura e tenta de novo); o
    resultado (`nuvem.Espelho`, que ainda desempacota como `(copiados,
    iguais)`) traz `nao_copiados`, `sigilosos_restantes` e `resumo`; a cópia usa
    `copyfile` e `utime`, para não levar o somente leitura para a nuvem, e
    o caminho longo usa o prefixo `\\?\` no Windows, na cópia e na
    varredura que retira o sigiloso (sem ele, a cópia longa ficaria
    invisível para a retirada).
  * **O que ainda estiver no acervo sai.** Todo compartilhamento começa
    pelo preparo (`preparo.atualizar_contexto`), que varre o acervo uma vez
    só (`motor.processos_no_acervo`: arquivo com o número no nome, pasta de
    gravações ou linha no relatório de um lote). Com a separação dos
    sigilosos ligada (`[download] separar_sigilosos`, o padrão), o que for
    de processo sigiloso (baixado antes de o segredo ser decretado, por
    exemplo, quando só a pauta o mostra) é levado para a pasta dos
    sigilosos como o download faria (`motor.retirar_do_acervo`): os autos
    de `Processos\<lote>` para `Sigilosos\<lote>`, com capa e gravações — o
    que já estiver lá vence; a capa e as gravações saem mesmo sem os autos —,
    as transcrições para `Sigilosos\Transcricoes`, a minuta em `Produtos\`
    para `Sigilosos\Produtos\` e qualquer outro arquivo com o número do
    processo em outra pasta do acervo (subpasta do lote, `Minutas\`…) para
    o mesmo caminho relativo dentro da pasta dos sigilosos
    (`motor.destino_na_pasta_dos_sigilosos`: sem o `Processos\` do começo;
    nunca sobrescreve, usa um nome livre). Os incidentes saem com o
    principal. O texto dele em `_ia/texto` é apagado, e a linha dele no
    `relatorio.csv` de cada lote do acervo é mascarada como no download
    (“(processo sigiloso)”, arquivo vazio, sigiloso “sim”); a linha
    completa, com “(na pasta de sigilosos)”, vai mesclada para
    `Sigilosos\<lote>\_controle\relatorio.csv`, que o motor relê no “Tentar
    de novo”. O espelho na nuvem refaz o índice antes de copiar, não copia
    o processo sigiloso e apaga do destino a cópia que tenha chegado lá
    antes de se saber do sigilo. Com a separação desligada, o sigiloso fica
    no acervo, mas continua fora do índice, do texto, do MCP, do pacote e
    da nuvem, e o `CLAUDE.md` avisa a IA de que a pasta pode conter
    processo em segredo de justiça.
  * **Só os autos travam o compartilhamento.** O que não puder sair fica
    entre os “presos”, e `motor.bloqueia()` decide: só os **autos** (PDF
    fora de `Produtos\`) travam. Até eles saírem, nada se compartilha
    (`SigilosoNoAcervo`; na API, 409 `sigiloso_no_acervo`; no Início, a
    pendência `sigilo`, “Processo sigiloso no acervo”), e antes de recusar
    o programa tenta levá-los de novo (o arquivo pode ter sido fechado). A
    frase (`preparo.frase_sigilosos_no_acervo`, com `trava` verdadeiro)
    conta processos, não arquivos, diz “arquivo”, não “PDF”, e dá o
    caminho relativo ao acervo, o motivo real e a pasta de destino: “Os
    autos do processo X, que corre em segredo de justiça, não puderam sair
    do acervo: <caminho dentro do acervo> (<motivo>). Feche o arquivo e
    tente de novo, ou mova-o para a pasta dos sigilosos (<pasta>). Até ele
    sair, nada do acervo é compartilhado: os botões da tela Compartilhar, o
    pacote e o espelho na nuvem ficam suspensos.” Os motivos
    são “está aberto em outro programa?”, “a pasta dos sigilosos não está
    acessível…”, “a audiência está sendo gravada agora” e “está aberto no
    Excel?”. O resto (a transcrição aberta no Word, a gravação em curso, a
    minuta em `Produtos\`, a capa, o relatório aberto no Excel) **não
    trava**, porque o índice, o MCP, o pacote e a nuvem já o deixam de
    fora: vira aviso — a pendência `sigilo-arquivos` (“Arquivo de processo
    sigiloso no acervo”), `sigilosos_avisos` no estado do Compartilhar e
    no resumo do lote (`ResumoLote.sigilosos_avisos` e `sigilosos_motivos`)
    e `avisos` no resultado do preparo; `sigilosos_no_acervo` traz só os
    autos. As duas pendências levam à tela Compartilhar. **Risco aceito:**
    até sair, esse arquivo fica ao alcance do Claude Code, do Cowork e do
    ChatGPT, que abrem a pasta inteira, e o aviso diz isso; para voltar a travar com a
    transcrição presa, basta mudar `motor.bloqueia()`. (A tela Compartilhar
    ainda não mostra os `avisos` do preparo nem os `sigilosos_avisos`, e o
    modo demonstração não tem a pendência `sigilo-arquivos`; o Início
    mostra as duas pendências.) No download, a transcrição presa ou a
    gravação em curso de um sigiloso não marcam mais o processo como ERRO:
    o item mostra “atenção: …”, e o lote avisa “Arquivo de processo
    sigiloso no acervo”.
  * **O sigilo revelado pela pauta vale na hora.** Quando a sincronização
    (inclusive a do monitor), a captura ou a importação revela em segredo
    de justiça um processo que o programa ainda não tratava como sigiloso
    (`sigilosos_novos`, seção 8.10) e ele tem arquivos no acervo
    (`pauta.servico.no_acervo`: autos ou transcrição fora da pasta dos
    sigilosos, ou o texto em `_ia/texto`), o servidor pede o preparo rápido
    na hora (`api_pauta.sigilo_revelado` → `api_compartilhar.depois_de_salvar`,
    em segundo plano): o processo sai do acervo (autos e transcrições para a
    pasta dos sigilosos), do `_ia/texto`, do `INDICE.md` e, com o espelho
    automático ligado (`[compartilhar] espelhar_automaticamente`), da nuvem
    (a tarefa `nuvem`, que apaga a cópia do destino); sem ele, a cópia na
    nuvem sai no próximo espelho. A janela recebe o evento `aviso` com o
    título “Processo em segredo de justiça” (ou “Processos em segredo de
    justiça”) e a frase de `frase_sigilo_revelado`, que varia com a
    separação dos sigilosos, a nuvem automática ou manual e o arquivo preso
    no acervo (então, o processo sai quando o acervo puder ser preparado de
    novo). Exemplo: “A pauta indica que o processo X corre em segredo de
    justiça. O Helestron está levando os autos e as transcrições dele para
    a pasta dos sigilosos, e ele sai do índice e do texto lidos pela IA e
    do espelho na nuvem.” (sem o espelho automático: “… e ele sai do índice
    e do texto lidos pela IA. A cópia dele na nuvem sai no próximo espelho
    (Compartilhar › Espelhar agora).”). Processo sem nada no acervo não gera
    aviso. O servidor liga o gancho (`api_pauta.servico_da_pauta`, usado em
    todos os pedidos à API da pauta) no `ServicoPauta` do programa, que é o
    mesmo do monitor; o que o monitor revelou antes do primeiro pedido fica
    pendente no serviço e é tratado nele (o Início lê a pauta ao abrir). Sem
    nenhuma janela (`--servidor --sem-janela`), esse pendente só vale no
    próximo preparo ou compartilhamento, como antes. A linha de comando
    (`pauta importar` e `pauta sincronizar`) faz o mesmo preparo por conta
    própria (seção 8.9).
  * **Uma marcação errada não se desfaz sozinha.** O sigilo apurado na pauta
    não se desfaz (`a.sigiloso or velha.sigiloso`, seção 8.2), e os
    arquivos levados para a pasta dos sigilosos ficam lá, mantendo o
    processo sigiloso pela regra (1) ou (2). Uma marcação falsa gravada por
    uma versão anterior da regra da pauta (“Nível 1” no Local, “Segredo de
    justiça: não”) continua valendo. Não há comando nem botão “não é
    sigiloso” (mexeria na interface, na pasta dos sigilosos, no download e
    no preparo). O manual (Segredo de justiça › Se um processo foi marcado
    como sigiloso por engano) dá o caminho manual: fechar o programa,
    afastar o `pauta.sqlite3` **e o `pauta.sigilo.json`** (o registro do
    apurado, que sozinho manteria o processo sigiloso; a pauta recomeça: é
    preciso cadastrar as fontes, sincronizar e importar de novo antes de
    baixar ou transcrever), o `download.sigilo.json` se o sigilo veio de um
    download, trocar “sim” por “não” na linha dele no relatório do lote
    (fonte 5, e “uma vez sigiloso, sempre sigiloso” do motor) e trazer os
    arquivos de volta da pasta dos sigilosos para o acervo.
  * **Download.** O processo que o programa já sabe sigiloso pela regra
    única vai para a pasta dos sigilosos mesmo que a página do portal não
    mostre o selo (segredo decretado depois, leiaute que a leitura não
    pega), e uma vez sigiloso, sempre sigiloso (relatórios anteriores do
    lote, a capa guardada). A tela de processo sigiloso nunca é guardada em
    `Logs\diagnostico` (ela traz as partes, e o diagnóstico é o que se envia
    ao suporte): o registro diz por quê, e a mensagem de erro diz que a tela
    não foi guardada. O processo sigiloso de um lote fora de `Processos` vai
    para a pasta de sigilosos daquele lote (`<nome> (<marca>)`, seção 5.1),
    e o JSON e o log da linha de comando, que trazem os números reais, são
    recusados dentro do acervo. Com o índice reaberto (a Pasta Digital
    recarregada no meio), a peça sigilosa é reapurada.
  * **Transcrição.** O interruptor da tela e o `--sigiloso` da linha de
    comando só **acrescentam** sigilo: o que o programa já sabe sigiloso
    pela regra única (ou a gravação guardada na pasta dos sigilosos) é
    transcrito como sigiloso mesmo com o interruptor desligado, e a tela (ou
    a saída da linha de comando) diz o motivo. A transcrição de sigiloso vai
    para `Sigilosos\Transcricoes` (com a gravação e o diário em `_audio`);
    na linha de comando, um `--destino` dentro do acervo é recusado (o
    sigilo efetivo é apurado também quando há destino, e sobre o caminho já
    resolvido: um processo sigiloso nunca cai no acervo, nem quando a
    gravação no destino falha e o documento vai para a pasta das
    transcrições). O incidente digitado com `-NN` ou `/NN` herda o sigilo
    como o `/NN` sempre herdou (`cnj.ler_nome_arquivo` na linha de comando,
    na sessão ao vivo, na gravação e na API). Os registros do programa
    guardam só a posição do falante (F1–F8), nunca o rótulo digitado, que
    costuma trazer o nome de quem depõe (e a repetição descartada pelo
    filtro de alucinação vai para o registro só com o instante, nunca com o
    texto). Com “Guardar a gravação da audiência” desligado, o áudio é
    mantido mesmo assim quando há fala não transcrita ou o modelo não
    carregou (`ao_vivo.encerrar`: `manter_por_falha`): a ficha aponta a
    gravação em `_audio`, e um evento `aviso` cita “Guardar a gravação da
    audiência” e “Transcrever uma gravação” e traz o caminho do FLAC.
  * **Pauta exportada.** Fica fora do acervo e mascara as partes e as
    observações dos sigilosos por padrão (também nas alterações e no texto
    da busca); `pauta listar` mascara do mesmo jeito, também no `--json`.
  * **Privacidade do navegador e dos registros.** O modo certificado não
    copia mais o perfil do Chrome do usuário: só o Web Signer (as pastas
    `Extensions`, `Local Extension Settings`, `Sync Extension Settings` e
    `Managed Extension Settings` da extensão, sem o `LOCK`, e, das
    preferências, só o ramo dela e o MAC que o Chrome confere,
    `navegador.so_da_extensao`), com a marca `helestron-perfil.json`
    (`VERSAO_PERFIL_CERT` = 2); a extensão é atualizada a partir do Chrome
    quando ele tem uma versão mais nova. A cópia do perfil inteiro feita
    até a 1.0.1 (senhas, cookies, autopreenchimento, histórico, outras
    extensões e o `Local State`) é apagada na abertura do programa
    (`inicio.limpar_perfis` → `navegador.limpar_perfis_antigos`) ou, se
    não puder sair agora (aberta, ou um arquivo dela preso pelo antivírus,
    pelo backup ou pelo Explorador), na próxima vez; enquanto ela não sai, o
    modo certificado recusa abrir o navegador sobre ela (`NavegadorOcupado`,
    `navegador.COPIA_ANTIGA_PRESA`). A sessão guardada (`perfis\<portal>\sessao.json`)
    leva só os cookies dos portais (`.jus.br` e os hosts do tribunal no
    catálogo e nas correções: `cookie_do_portal`), cifrados pela DPAPI
    (`cofre_senhas.cifrar`, finalidade `sessao/v1`), nada de
    `localStorage`, e vale por até 12 h (`SESSAO_VALIDA_S`); a sessão em
    texto puro da 1.0.1 é regravada no formato novo (`migrar_sessao`).
    Apagar o acesso, ou trocar o usuário, apaga a sessão e os perfis do
    portal (`esquecer_portal`; o do eProc do 2º grau, `eproc2g:TJAL`, apaga
    só `perfis\eproc2g-TJAL` e `perfis\eproc2g-TJAL-certificado`), e o
    navegador aberto antes disso não a
    regrava ao fechar e apaga o próprio perfil, também o de outro processo
    (o `baixar` da linha de comando): o instante fica ainda na marca
    `perfis\<portal>.esquecido`, que a abertura do programa apaga depois de
    7 dias. O desinstalador apaga `perfis\` sempre (seção 10).
    O registro do programa censura os segredos de URL
    (`registro.censurar`, `FiltroSegredos` nos handlers do disco, da tela e
    do `--log`: `;jsessionid=`, `hash`, `ticket`, `token`, `code`,
    `session_state`, `state`, `key`, `sid`, `access_token`, `id_token`,
    `refresh_token`, `senha`, `password` e o `usuário:senha@` de um proxy
    viram `***`), também nas mensagens de erro do navegador que vão para a
    tela e para o `relatorio.csv` (`explicar_erro`); o servidor mascara o
    token (`?t=***`).
  * **Cofre de senhas.** Ler, alterar e gravar o `credenciais.json` passam
    por uma trava de thread e uma entre processos
    (`credenciais.json.trava`, criada com `O_EXCL` e apagada no fim;
    trava com mais de 30 s é retirada; esperar mais de 10 s dá
    `CofreIndisponivel`, que a API traduz em 409 `arquivo_preso`). O
    arquivo ilegível (JSON ou UTF-8 inválido, conteúdo que não é objeto)
    vai para `credenciais.json.ilegivel-AAAAmmdd-HHMMSS` (para o suporte), e
    o cofre recomeça; a gravação é atômica, com temporário único, `fsync` e
    troca que insiste.
  * **Autoteste.** O `--autoteste` (seção 5) roda em pastas de dados novas e
    vazias (`PastasDoAutoteste`) e captura só o retângulo da janela: as
    capturas, que o CI publica, nunca mostram a configuração, a pauta (com
    as partes dos sigilosos), o acervo ou outros programas abertos de quem
    o roda.
* **Documentos gerados.** O DOCX da transcrição (`transcricao/documento.py`,
  `montar_docx`, o único gerador de DOCX do programa) sai com as
  propriedades do próprio documento (`propriedades_do_documento`): autor e
  “modificado por” Helestron, criado e modificado na hora da geração (UTC),
  título “Transcrição de audiência — Processo nº <número>”, assunto
  “Transcrição de audiência”, palavras-chave com o número, comentários e
  categoria vazios, revisão 1, o aplicativo “Helestron <versão>” no
  `docProps/app.xml` e sem a miniatura do modelo. O modelo do python-docx
  deixava o autor “python-docx”, a data de 2013 e o aplicativo “Microsoft
  Macintosh Word” num documento que pode ir aos autos.
* **Português do Brasil** correto em tudo o que o usuário lê (acentos, crase,
  concordância). Código e comentários em português, no estilo do código
  existente.
* Nada de dependência nova além de: `pywebview`, `pythonnet` (e dependências),
  `bottle`, `proxy_tools`, `typing_extensions` (Windows), `installer` (só na
  construção). Biblioteca padrão para HTTP, SQLite, threads.
* Testes com `unittest`, rodando em Linux sem rede e sem Windows (o que é só do
  Windows é pulado com `skipUnless`), sem tocar em `~` ou `%LOCALAPPDATA%` reais:
  `testes/__init__.py` aponta `HELESTRON_LOCAL` e `HELESTRON_DADOS` para uma
  pasta temporária antes de qualquer import de `helestron` (e a apaga no fim);
  depois da suíte, a raiz do repositório e o HOME não ganham arquivos.
* Nada de `importlib.import_module` com nome montado em tempo de execução para
  partes essenciais do programa.

## 13. Paginação dos autos, capa e texto para a IA

O PDF de cada processo reproduz **exatamente** a numeração do sistema do
tribunal, para que a citação feita a partir dele (pelo magistrado, pela IA,
pela skill do Claude) seja a do portal. Isso vale desde a 1.0.2; o PDF de
versão anterior não traz o manifesto, e a paginação dele não é garantida.

### 13.1 O manifesto de paginação (`nucleo/paginacao.py`)

O manifesto vai dentro do PDF, como arquivo anexo (`helestron-paginacao.json`,
`gravar_no_doc`) e, resumido, nas palavras-chave (`/Keywords`:
`helestron;sistema=esaj;paginacao=folhas;formato=1;ultima=245;ausentes=N:12-15|B:40`,
ou `…;modo=documentos` no eProc), que qualquer leitor de PDF mostra. Ele
acompanha o arquivo para onde ele for (pasta do lote, pasta dos sigilosos,
acervo). O módulo não depende do download nem do compartilhamento; usam-no
quem grava o PDF, quem extrai o texto, o servidor MCP e o motor que confere
o que já foi baixado. API: `manifesto_esaj`, `manifesto_eproc`,
`gravar_no_doc`, `ler_do_doc`, `ler_do_pdf` (PyMuPDF; sem ele, os anexos
pelo `pypdf`), `ausentes`, `descrever_folhas`, `ler_faixas`, `faixas`,
`valido`, `palavras_chave` e `resumo` (a linha para o relatório, a capa e o
índice: “página N = folha N (fls. 1 a 245); folhas com página de aviso:
12-15”, “paginação de cada documento igual à do eProc (31 documentos)”,
no modo completo “arquivo completo do eProc (Download Completo), sem
página acrescentada: página M do PDF = página M do arquivo” (com várias
partes, “…, em 2 partes, sem página acrescentada: cada parte recomeça na
página 1”) ou “paginação não conferida (PDF de versão anterior à 1.0.2)”).

* **e-SAJ** (`paginacao = "folhas"`): `{formato: 1, programa, sistema:
  "esaj", paginacao, tribunal, processo, ultima, ausentes: {código:
  faixas}, origem: "servidor" | "peca_a_peca", notas, gerado_em}`. A página
  N do PDF é SEMPRE a folha N, de 1 a `ultima` (a última folha oferecida
  pela Pasta Digital: folhas depois dela, ocultas, não aparecem em índice
  nenhum e não podem ser detectadas). Os motivos (`MOTIVOS`, na ordem
  `ORDEM_MOTIVOS` = `NSBIC`):

  | Código | Motivo |
  |---|---|
  | `N` | a Pasta Digital não ofereceu esta folha ao usuário (peça sigilosa, de acesso restrito ou cancelada) |
  | `S` | a Pasta Digital listou uma peça sem numeração de folhas |
  | `B` | a peça não pôde ser baixada do e-SAJ |
  | `I` | o arquivo da peça veio inválido (não abre, protegido ou sem páginas) |
  | `C` | o arquivo da peça veio com menos páginas do que as folhas que ela ocupa |

* **eProc** (`paginacao = "documento"`): `{…, sistema: "eproc", modo:
  "documentos" | "completo", documentos: [{evento, rotulo, descricao, data,
  origem: "pdf" | "imagem" | "html" | "texto" | "midia", situacao: "ok" |
  "ausente" | "midia", inicio, paginas, motivo?, arquivo?}], capa: {classe,
  competencia, autuacao, situacao, orgao, magistrado, assunto, valor,
  partes: [texto]}, eventos_sem_documento: [{evento, descricao, data}],
  eventos_nao_listados, portal, extraido_em, sigiloso}`. `inicio` é a página
  do PDF em que o documento começa; `motivo`, por que o ausente não veio;
  `arquivo`, a mídia salva (caminho relativo POSIX,
  `_controle/midias/<número>/Evento 7 - VIDEO1.mp4`). No modo completo,
  `documentos = []` e `partes = [{inicio: 1, paginas: n}, …]`.
* **Grau** (1.1.0): o manifesto dos autos do 2º grau leva `grau: "2g"`
  (`manifesto_esaj(..., grau=)`, `manifesto_eproc(..., grau=)`;
  `SEGUNDO_GRAU`) e as palavras-chave terminam em `;grau=2g`; no 1º grau,
  o campo não vai, e o manifesto é byte a byte o da 1.0.2.
  `paginacao.grau(m)` dá `2g` se o manifesto o diz e `1g` em qualquer
  outro caso (inclusive o PDF da 1.0.2). `FORMATO` continua 1.

### 13.2 e-SAJ: página N = folha N (`download/esaj.py`, `download/pdf.py`)

* **O plano das folhas** (`esaj.planejar_folhas` → `PlanoFolhas`): a partir
  do índice da Pasta Digital, cada folha tem um dono (a peça) ou um motivo
  para não ter. Trata buracos na numeração, índice que começa depois da
  fl. 1, árvore fora de ordem (tudo em ordem de folha), peças repetidas,
  sobreposição (a folha fica com o primeiro dono) e o bloco sem numeração
  ou invertido, que só é posicionado quando o vão bate exatamente com o
  `nuPaginas` dele (senão, as folhas do vão levam o código `S`; o
  `nuPaginas` divergente vira anomalia, anotada no detalhe). O índice sem
  numeração nenhuma falha fechado (“a Pasta Digital não informou a
  numeração das folhas”). Se a Pasta Digital é reaberta no meio (sessão
  que caiu), o plano é refeito, e a peça sigilosa, reapurada. O pedido ao
  servidor vai em ordem de folha.
* **O PDF do servidor** (`pdf.gravar_alinhado`): só é aceito se confere —
  a contagem de páginas e os carimbos (“fls. N” sozinho na linha, que só
  valem quando ao menos 90 % das páginas o trazem). A página confere quando
  a folha esperada está entre os carimbos dela: a que reproduz uma folha de
  outro processo do e-SAJ (a sentença do principal no cumprimento de
  sentença, o processo redistribuído) traz o carimbo antigo antes do deste
  processo, que o e-SAJ desenha por cima, no fim do conteúdo
  (`pdf.carimbos`; `pdf.carimbo` é o último). Conferido, as páginas
  são mapeadas para as folhas (com `select` na sobreposição) e as páginas
  de aviso inseridas em ordem crescente; com o mapa identidade, o arquivo
  é salvo por `saveIncr`, e os bytes do servidor ficam intactos.
  Desalinhado (`pdf.Desalinhado`, um `ValueError`), o processo é montado
  peça a peça, com o detalhe “montado peça a peça (o PDF do servidor tem X
  páginas para Y folhas)” ou “folha carimbada não confere”. Um PDF
  desalinhado nunca é gravado como OK, e não sobra `.parcial` nem
  `.parcial2`.
* **Peça a peça** (`pdf.juntar_folhas`): uma página por folha. A peça que
  não veio tem `B`; o arquivo que não abre, tem senha ou zero páginas, `I`;
  o que veio com páginas a menos, `C`. Com páginas a mais: se o `getPDF.do`
  devolveu o documento inteiro, vale a fatia certa (e o arquivo é baixado
  uma vez só, com cache por `cdDocumento`); senão, os carimbos; senão, as
  n primeiras, com anotação. Com páginas a menos e o arquivo carimbado,
  cada folha fica com a página que traz o carimbo dela, falte a do começo,
  a do meio ou a do fim, e o `C` vai para a folha que faltou (com
  anotação); sem carimbo, as páginas vão para as primeiras folhas, e o
  `C`, para as do fim. Nos dois casos vale o carimbo deste processo, o
  último da página. As páginas de aviso saem de um PDF único
  (`paginas_de_aviso`) e são inseridas por trechos (300 avisos em cerca de
  meio segundo). Continuam valendo `MAX_PECAS_SEGUIDAS_FALHANDO` e “todas
  falharam = erro”.
* **A página de aviso**: a primeira linha é EXATAMENTE “Folha N — não
  disponibilizada pelo e-SAJ”; depois, “Motivo: <MOTIVOS[código]>.”,
  “Peça: <título>.” quando houver, a explicação e a moldura vermelha.
  Marcadores: um por trecho do mesmo documento, e um próprio para cada
  sequência de avisos (“Fls. 6-7 — não disponibilizadas pelo e-SAJ”, “Fl.
  8 — não disponibilizada pelo e-SAJ (Termo de Audiência - 20/04/2024)”).
* **No resultado**: `paginas` é a última folha; `incompleto`, todas as
  folhas com aviso (`descrever_folhas`, códigos `N`, `S`, `B`, `I` e `C`); o
  detalhe traz uma frase por motivo (mantendo “1 peça não veio e tem
  página de aviso no lugar”), as notas e as anomalias.
* **Arquivo preso**: o `PermissionError` só sobe sem montar peça a peça
  quando é do arquivo que se estava gravando (o destino ou o
  `.parcial`/`.parcial2` na mesma pasta: PDF aberto no leitor, provisório
  preso pelo antivírus, que o motor repete); sem nome de arquivo (o
  soquete negado pelo firewall, `WinError 10013`), vai para o peça a peça.
  A troca do provisório insiste com espera crescente (`pdf._trocar`:
  0,25/0,5/1/2/3/3 s).

### 13.3 eProc: a paginação de cada documento (`download/eproc.py`)

* **Modo documentos** (o padrão; Ajustes › Download, “Montagem do PDF no
  eProc”): o PDF traz os documentos do evento mais antigo ao mais novo,
  **sem capa e sem página nenhuma antes ou entre eles**. Cada documento é
  uma `pdf.Parte` com o rótulo de página (`rotulo_de_pagina`, em ASCII
  simples, `pdf.rotulo_seguro`: o PyMuPDF grava errado acento e
  parênteses): “Ev. 1 INIC1 p. 2” (PDF e imagem, numerado), “Ev. 3
  DESPADEC1” (HTML e texto do editor do eProc, sem número), “Ev. 4 PET1 nao
  incluido” e “Ev. 7 VIDEO1 gravacao” (páginas de aviso). O documento que
  não veio e a mídia têm UMA página de aviso no lugar, que diz não ser
  página dos autos, com o marcador terminado em “ [NÃO INCLUÍDO]” ou
  “ [GRAVAÇÃO — fora do PDF]”. O PDF que não abre é conferido antes
  (`pdf.contar_paginas_de`) e vira falha com motivo. O sumário próprio de
  um documento entra como nível 2. O PDF leva metadados (título, assunto,
  “Helestron <versão>” como criador e produtor, data) e o manifesto;
  `paginas` conta só as páginas dos documentos.
* **Citação** (`eproc.citacao`, a mesma marca do texto dos autos): “evento
  1, INIC1, p. 2” (a página Y é a do próprio documento, igual à do eProc);
  “evento 3, DESPADEC1” (sem páginas); a página de aviso não se cita.
* **Modo completo** (`[eproc] modo = completo`): o arquivo do próprio eProc
  (Download Completo) entra intacto (`pdf.gravar` com o marcador
  `TITULO_COMPLETO` na página 1, `preservar_sumario=True`, manifesto do
  modo completo): a página M do PDF é a página M dele, e o sumário nativo
  fica. O ZIP com k partes é juntado com o rótulo “Parte i p. ” e o
  sumário de cada parte como nível 2; o arquivo que não abre cai no modo
  documentos. Os eventos são lidos ANTES do Download Completo (a falha da
  paginação deles não impede o completo, e a capa avisa “lista
  incompleta”), e são reaproveitados se o completo falhar.
* **2º grau**: o `PortalEProc` no Tribunal do 2º grau (outra instalação
  do eProc, com acesso próprio: seção 14.4) monta o PDF pelas mesmas
  regras; os eventos são os do processo no 2º grau. O e-SAJ do 2º grau
  segue a seção 13.2, com a Pasta Digital do 2º grau (seção 14.3).

### 13.4 A capa (`_controle/<número>_capa.txt` e `_capa.json`)

A capa não vai mais dentro do PDF. Vai em `_capa.txt`, para ler, e em
`_capa.json` (formato `helestron.capa/2`), para máquina (a skill do Claude a
acha pelo `capa_json` do JSON do `baixar`). As duas acompanham o PDF
(`motor.SUFIXOS_CONTROLE`). O “SEGREDO DE JUSTIÇA - processo sigiloso. Não
compartilhe.” vai no topo do `.txt`: o motor o procura nos primeiros 2000
caracteres para manter o processo fora do acervo nas próximas rodadas.

* **e-SAJ** (`esaj.formatar_capa`, `esaj.dados_da_capa`), da página do
  processo que o download já abre (`_JS_PAGINA_PROCESSO`): as
  movimentações só da tabela de todas (`#tabelaTodasMovimentacoes`; sem
  ela, a das últimas), sem limite e sem tirar repetidas; as partes de
  `#tableTodasPartes` (sem ela, `#tablePartesPrincipais`); as seções
  achadas pelo título (incidentes, apensos, audiências, histórico de
  classes, petições diversas: a primeira tabela depois do título, com as
  células e o código do processo do link); as marcas (`.unj-tag` e o
  cabeçalho, sem os valores da capa: um assunto “Estatuto do Idoso” não dá
  a prioridade do idoso); outros números, processo principal, local físico
  e outros assuntos. O texto do segredo é lido primeiro, e os extras ficam
  em `try/catch`: um erro neles não derruba a detecção do sigilo. O `.txt`
  mantém “== Capa ==”, “== Partes ==” e “== Movimentações (N) ==” e
  acrescenta “== Marcas ==”, “== Arquivo ==” (“Folhas 1 a U (última
  oferecida pela Pasta Digital)”, “Paginação: <resumo>” e como citar) e as
  seções, com a contagem. O JSON: `formato`, `sistema`, `tribunal`,
  `processo`, `extraido_em`, `sigiloso`, `capa` (chaves de máquina:
  `classe`, `assunto`, `foro`, `vara`, `juiz`, `distribuicao`, `valor`,
  `situacao`, `area`, `controle`…), `partes`, `marcas`, `prioridade`,
  `justica_gratuita`, `segredo`, `idoso`, `outros_numeros`,
  `processo_principal`, `local_fisico`, `outros_assuntos`, `movimentacoes`
  (`[{data, texto}]`), `codigo_processo`, `url`, `incidentes` (com
  `numero`, `classe`, `recebido_em` e `codigo`), `apensos`, `audiencias`,
  `historico_classes`, `peticoes_diversas` e `paginacao` (`resumo`,
  `ultima`, `ausentes`, `folhas_ausentes`).
* **eProc** (`eproc.texto_capa_txt`, `eproc.dados_da_capa`): “== Capa ==”,
  “== Partes ==”, “== Arquivo ==” (como foi montado; eventos, documentos e
  páginas; a paginação; os eventos não listados, os não incluídos, as
  gravações e os eventos sem documento), “== Como citar ==”, “== Mapa de
  documentos (N) ==” com TODOS os documentos e a posição de cada um no PDF
  (“págs. 1–2 do PDF (2 págs.; p. 1–2 no eProc)”; no modo completo, sem
  posição) e “== Eventos (N) ==”, sem limite. O JSON: `formato`,
  `sistema`, `tribunal`, `portal`, `processo`, `extraido_em`, `sigiloso`,
  `capa`, `partes`, `modo`, `paginacao` (`resumo`, `ultima`,
  `documentos_ausentes`), `paginas_pdf`, `como_citar`,
  `eventos_completos`, `eventos_nao_listados`, `eventos_sem_documento`,
  `eventos` (todos: `evento`, `data`, `hora`, `descricao`, `documentos`),
  `documentos` (os do manifesto) e, no modo completo,
  `partes_do_arquivo`. Nos dois sistemas, `paginacao` é um objeto, só com
  o manifesto, e `resumo` e `ultima` (a última página do PDF) valem para
  ambos; as chaves de `capa` são as de cada sistema. Os seletores `capa_assunto` (`#txtAssunto`) e
  `capa_valor` (`#txtValorCausa`) ainda não foram confirmados em portal
  real.
* **2º grau** (1.1.0): os dois sistemas gravam a capa pelo nome do destino
  (`<destino.stem>_capa.*`: `<número> (2G)_capa.txt` e `_capa.json`), com
  `grau: "2g"` no JSON; a do e-SAJ do 2º grau tem campos e seções próprios
  (seção 14.3). No 1º grau, `_capa.txt` e `_capa.json` são byte a byte os
  da 1.0.2.

### 13.5 O texto dos autos, formato 2 (`compartilhar/textos.py`)

O texto em `_ia/texto/<número>.txt` (e o do `baixar --texto` e do
`preparar --pasta`; o nome é sempre o do PDF: nos autos do 2º grau,
`<número> (2G).txt`) é um cache, refeito quando o PDF muda ou quando a
primeira linha não é do formato 2 (`versao_do_texto`). A gravação é atômica
(`gravar_atomico`: temporário de nome único e, no Windows, nova tentativa
do `os.replace`).

* **1ª linha**, legível por máquina: `# helestron-texto 2 |
  sistema=<esaj|eproc|desconhecido> | paginacao=<folhas|documento|nao_garantida>
  | paginas=<n> | ausentes=<faixas>` (`ausentes`: as páginas do PDF que são
  aviso; no e-SAJ, as próprias folhas) e, só nos autos do 2º grau,
  `| grau=2g` no fim (o grau dos autos é o do manifesto, `paginacao.grau`,
  e, sem manifesto, o do nome do arquivo, `cnj.grau_do_nome`:
  `textos.grau_dos_autos`). O texto do 1º grau é byte a byte o da 1.0.2
  (nada a reextrair nem a reenviar à nuvem). `cabecalho()` e
  `info_do_texto()` devolvem também `grau` (`1g` ou `2g`).
* **Preâmbulo**: linhas entre colchetes, tiradas do manifesto — o que o
  arquivo é, como citar (`COMO_CITAR_ESAJ`, `COMO_CITAR_EPROC`,
  `COMO_CITAR_NAO_GARANTIDA` e, no eProc cujo manifesto não descreve o
  PDF, `COMO_CITAR_EPROC_NAO_GARANTIDA`: nunca “fl.”, nem o carimbo
  “fls. N” de documento vindo de outro sistema; cita-se o evento e o
  documento, sem a página), as folhas com aviso e o motivo, as notas do
  download e, no eProc, a capa, as partes, os documentos não incluídos, as
  gravações e os eventos sem documento. Nenhuma delas contém `=== [`. Nos
  autos do 2º grau, a abertura e o como citar são os do 2º grau
  (`COMO_CITAR_ESAJ_2G`, `COMO_CITAR_EPROC_2G`,
  `COMO_CITAR_EPROC_NAO_GARANTIDA_2G`, `COMO_CITAR_NAO_GARANTIDA_2G`:
  seção 14.7).
* **Marcas** (o que vai entre os colchetes é o que se cita):
  - e-SAJ: `=== [fl. N] ===`; a folha com aviso tem logo abaixo
    `[folha não disponível no e-SAJ: <MOTIVOS[código]>]` e não leva o texto
    da página de aviso. Se o manifesto diz um número de folhas diferente
    das páginas do PDF, o texto sai `nao_garantida`;
  - eProc: `=== [evento N, RÓTULO, p. Y] (pág. M do PDF) ===`; documento
    HTML ou texto, `=== [evento N, RÓTULO] (pág. M do PDF) ===`; o que não
    veio, `… — NÃO INCLUÍDO`, e a gravação, `… — gravação fora do PDF` (sem
    o texto da página de aviso, só uma linha com o motivo ou o arquivo);
    modo completo, `=== [arquivo completo do eProc, pág. M] ===` (com várias
    partes, `parte j, pág. Y` e `(pág. M do PDF)`). Como no e-SAJ, se a
    última página que o manifesto descreve (documentos ou partes do arquivo)
    não é a última do PDF (arquivo alterado depois do download), o texto
    sai `nao_garantida`, com o aviso, a instrução de citação do eProc e a
    capa no preâmbulo. A conferência é uma só, `manifesto_confere(m, n)`,
    que o índice, o conector, o `preparar --pasta` e o JA_BAIXADO do motor
    também usam, com a frase de `resumo_da_paginacao(m, n)`;
  - sem paginação garantida: `=== [pág. M do PDF] ===`.
  “(pág. M do PDF)” é só a posição no arquivo, para navegar: nunca se cita.
  Abaixo da marca, `[documento: …]` (o marcador do PDF da página).
* **Página sem texto extraível** (vazia, ilegível ou, no e-SAJ, só com o
  carimbo da Pasta Digital e o “fls. N”): a linha
  `[página sem texto extraível …]` antes do conteúdo (o carimbo continua no
  texto); a página curta com texto de verdade não é marcada.
* **Marca forjada**: linha do conteúdo que imita a estrutura (`=== [`,
  `[documento:`, `[folha não disponível`, `# helestron-texto`…) recebe “· ”
  na frente; um documento das partes não consegue forjar uma folha.
* **PDF de versão anterior**, sem manifesto: do e-SAJ, vale `fl. N`
  (`folhas`) só se todos os marcadores “(fls. A-B)” começam na página A e
  o PDF termina na última folha B deles; a página “Documento não incluído”
  de uma folha só vira folha ausente; senão, `[pág. M do PDF]` e
  `nao_garantida`. Do eProc antigo (1º marcador “Capa — dados do
  processo” na página 1), as páginas da capa viram
  `[capa gerada pelo Helestron — não é página dos autos]`, e as demais são
  citadas pelos marcadores dos eventos (os avisos são reconhecidos pela
  frase com o rótulo e o evento). Sem manifesto nem marcadores:
  `sistema=desconhecido` e `nao_garantida`.
* **Funções**: `marcas`, `cabecalho`, `preambulo`, `citacao_na_posicao`,
  `buscar_citando` (a busca ignora o cabeçalho, as marcas e as linhas do
  programa, e preserva a posição para o acento), `faixa_do_documento`,
  `eventos_do_rotulo`, `info_pdf`, `manifesto_confere`,
  `resumo_da_paginacao`, `recortar_paginas` e `folha_na_posicao`
  (página do PDF), `analisar(caminho) → (texto, info)` (PDF, `.txt` ou
  `.docx`) e `info_do_texto` (`versao`, `sistema`, `paginacao`, `paginas`,
  `ausentes`, `grau`, `paginas_sem_texto` — citadas como os autos as citam:
  folhas em faixas no e-SAJ; “evento 1, INIC1, p. 2-3 (págs. 2-3 do PDF)”
  no eProc; “págs. 2-3 do PDF” sem garantia —, `paginas_sem_texto_pdf` e
  `total_sem_texto`; as páginas de aviso não contam).

### 13.6 O conector MCP (`compartilhar/mcp_servidor.py`)

As quatro ferramentas continuam com os mesmos nomes, todas só de leitura
(o 2º grau, desde a 1.1.0: seção 14.7):

* `listar_acervo`: os autos, pela chave dos autos (os do 2º grau com
  ` (2G)` e “— 2º grau —” na linha), com as páginas, o caminho e
  `textos.resumo_da_paginacao` de cada PDF (o `paginacao.resumo` do
  manifesto que descreve o arquivo; “NÃO garantida…” se ele não o
  descreve), e as transcrições, com o tamanho em caracteres;
* `ler_processo {numero, folha_inicial?, folha_final?, evento?,
  documento?, grau?}`: o texto pela faixa de páginas do PDF (no e-SAJ, as
  folhas) ou, no eProc, pelo evento e o documento (o rótulo que aparece em
  mais de um evento pede o evento). A resposta começa por um cabeçalho (sistema,
  páginas, “Página N = folha N.”, as folhas ausentes, ou como citar no
  eProc, ou o aviso de paginação não garantida, que no eProc manda citar o
  evento e o documento, nunca “fl.”) e pelo preâmbulo do texto.
  A faixa além do fim ou invertida dá `isError` (“o PDF tem só N
  página(s)…”); `folha_final` maior que o total é cortada no total. A
  resposta acima de `LIMITE_CARACTERES` (90.000) é cortada no começo de uma
  página (`\n=== [`) e diz com que `folha_inicial` continuar — a
  continuação recomeça exatamente na página seguinte;
* `buscar {termo, numero?, grau?}`: devolve a citação (“fl. N”, ou
  “evento N, RÓTULO, p. Y (pág. M do PDF)”), com os autos de onde ela saiu
  quando eles são do 2º grau ou o processo tem os dois graus no acervo, e
  o trecho;
* `ler_transcricao {numero, inicio?, arquivo?}`: o texto com o total de
  caracteres, cortado no fim de uma linha com
  `[Resposta cortada …: continue com inicio=N]`; `arquivo` lê uma
  transcrição só.

Mensagem que não é objeto, ou lote vazio, dá `-32600`; `params` que não é
objeto, `-32602`; `tools/call` com `name` ou `arguments` inválidos,
`-32602`; qualquer outro defeito vira `-32603`, e o laço continua. A
resposta que repete um texto sem forma em UTF-8 (o escape `\ud800` no
`id` ou no `termo`) vai com escapes `\uXXXX`; a que não vira JSON vira
`-32603`.

### 13.7 Arquivos de contexto, índice e pacote (`compartilhar/preparo.py`, `compartilhar/chatgpt.py`)

* **`CLAUDE.md`, `AGENTS.md` e `.claude/skills/acervo-judicial/SKILL.md`**
  são criados se faltam e **mantidos em dia** enquanto o usuário não os
  edita: o modelo (`CONTEXTO`, `SKILL`) vira expressão regular, com os
  campos restritos aos valores que o programa grava; o arquivo que casa com
  o modelo de agora é regravado se mudou algum valor (a regra do sigilo, a
  unidade, a versão; a data sozinha não regrava); o que casa com um modelo
  antigo (o da 1.0.2, `CONTEXTO_1_0_2` e `SKILL_1_0_2`; o da 1.0.0/1.0.1,
  `CONTEXTO_1_0_1` e `SKILL_1_0_1`; e o do programa anterior, derivado
  deles com o nome e o conector de `migracao.py`) é trocado pelo novo. O
  editado fica como está, com duas exceções: com a separação dos sigilosos desligada, a frase
  `REGRA_SIGILO_SEPARADOS` é trocada por `REGRA_SIGILO_JUNTOS` (e, se o
  arquivo não fala de sigilo, vai um aviso); e, com autos de sigiloso
  presos no acervo (cautela), “pode conter” não volta para “não estão”.
  Sem a regra de citação nova (`_MARCA_REGRA_NOVA`: `pág. M do PDF`, da
  1.0.2, e `(2G)`, da 1.1.0; falta de qualquer uma), `rel.avisos` explica
  como recebê-la. O rodapé diz que o programa mantém o arquivo em dia. O
  conteúdo traz as regras: no e-SAJ, página N = folha N, e a página de
  aviso não é prova; no eProc, cita-se evento, rótulo e p. Y;
  “(pág. M do PDF)” nunca se cita; o que fazer com `nao_garantida` (PDF
  de versão anterior ou alterado depois do download; no eProc, nunca
  “fl.”); e, desde a 1.1.0, os autos do 2º grau: `<número CNJ> (2G).pdf`,
  o recurso interno `-50000`, a numeração própria do 2º grau, “fl. N dos
  autos de origem” e o carimbo divergente que não se cita (seção 14.7).
* **`INDICE.md`**: as colunas Processo, Tribunal, **Sistema**, Páginas,
  **Paginação** (`textos.resumo_da_paginacao`: o `paginacao.resumo` do
  manifesto que descreve o arquivo; “NÃO garantida…”, sem as ausentes, se
  ele não o descreve, como o texto; para PDF sem manifesto, vem da 1ª
  linha do texto em dia), **Ausentes**, **Grau** (1.1.0: “1º grau” ou
  “2º grau”, pelo manifesto e, sem ele, pelo nome; se o nome do arquivo
  disser outro, a célula avisa), Lote, Autos, Texto e Transcrições, e uma
  linha com a regra de citação. Uma linha por PDF de autos: a coluna
  Processo é a chave dos autos (`X`, `X (2G)`), e as transcrições, que são
  do processo, aparecem na linha de cada grau dele. Com autos do 2º grau no acervo, vem
  antes da tabela a frase `preparo.FRASE_DO_2G` (“Autos do 2º grau têm
  "(2G)" no nome e numeração própria …”); a contagem do cabeçalho e
  `RelatorioPreparo.processos` contam processos distintos
  (`preparo.contar_processos`). Aceita um mapeador de caminhos (o
  pacote usa `autos/`, `texto/` e `audiencias/`, e lista só o que foi
  empacotado). As gravações dos arquivos de contexto e do índice passam
  por uma trava, e os erros de disco vão para `rel.erros`.
* **Pacote para o ChatGPT** (`chatgpt.gerar_pacote` → `Pacote`, que
  desempacota como `(pasta, zip)`, com `faltaram`, `avisos` e
  `tamanho_zip`): os números pedidos que não estão no acervo geram aviso
  (o número leva os autos dos dois graus do processo, e o número com
  ` (2G)`, só os do 2º grau: `chatgpt._escolher`; os arquivos levam a chave
  dos autos, `autos/X (2G).pdf`, e a mensagem conta processos, dizendo
  quantos levam os autos dos dois graus); o
  `.zip` é medido contra `LIMITE_ARQUIVO_MB`; os pacotes antigos da pasta
  de destino perdem os arquivos e as linhas de índice de processo que
  virou sigiloso (`servicos.retirar_sigilosos_dos_pacotes`, chamado por
  `servicos.atualizar_indice`, inclusive quando o preparo falha), e o
  `.zip` é refeito sem carregar os autos inteiros na memória.

## 14. O 2º grau (1.1.0)

Desde a 1.1.0, o download (a janela, a linha de comando e a pauta), o
compartilhamento e a interface tratam os autos do **2º grau**: no TJAL, o
**e-SAJ do 2º grau** (a consulta de 2º grau do portal, o CPOSG, em
`https://www2.tjal.jus.br/cposg5`) e o **eProc do 2º grau**
(`https://eproc2g.tjal.jus.br/eproc/`, outra instalação, com acesso próprio);
nos tribunais só de eProc que têm o endereço `2g` no catálogo, o eProc do
2º grau pelo mesmo código. O grau (`"1g"` ou `"2g"`) é decidido por uma
regra única e **viaja dentro do `Tribunal`** (`Tribunal.no_grau("2g")`):
nenhuma assinatura de fábrica, de portal, de `servicos.testar_login` ou da
pauta mudou. O 1º grau continua byte a byte o da 1.0.2, salvo os
acréscimos da seção 14.10.

### 14.1 A regra do grau (`nucleo/cnj.py`)

`cnj.GRAUS = ("1g", "2g")`. `normalizar_grau(valor)`: `1`, `1g`, `1G`,
`1º`, `1° grau`, `1o` → `1g` (o mesmo com 2 → `2g`); outra coisa → `""`
(quem chama decide: a linha de comando recusa, o `config.ini` vale `1g`, a
API devolve 400). `grau_do_numero(n)` → `"2g"` quando o número só existe no
2º grau, `""` quando não diz. `grau_do_processo(n, grau_do_lote)` é **a
regra única** (`grau_do_numero(n) or normalizar_grau(grau_do_lote) or
"1g"`), usada pelo motor (`_Lote`), pela linha de comando (`--retomar`,
credenciais) e pela API (`grau_fixo` da leitura); ninguém mais decide grau.

| Situação | Exemplo | Grau | Quem decide |
|---|---|---|---|
| órgão `0000` (competência originária do tribunal: HC, MS, agravo de instrumento, revisão criminal) | `0803061-28.2025.8.02.0000` | 2g | o número |
| órgão começando por `9` (plantão do 2º grau, turma recursal) | `0800103-29.2025.8.02.9002` | 2g | o número |
| dependente de 5 algarismos começando por `5` (recurso interno do e-SAJ 2º grau: embargos de declaração, agravo interno) | `0706265-50.2017.8.02.0001/50000` | 2g | o número |
| os demais, com o grau do lote | a apelação `0700001-93.2024.8.02.0058`, o incidente `…/01` | o do lote | a opção Grau do lote, o `opcoes.grau` da API, o `--grau` |
| os demais, pela janela, sem grau no pedido | idem | `[download] grau` (padrão `1g`) | os Ajustes |
| os demais, pela linha de comando sem `--grau` | idem | `1g` (como na 1.0.2) | a linha de comando |

Não há troca automática de grau (a apelação existe nos dois graus, com o
mesmo número; trocar entregaria autos errados); a troca de sistema e-SAJ →
eProc continua, dentro do mesmo grau. A última linha da tabela é de
propósito: a linha de comando **não** lê `[download] grau`, para que a skill
que chama o `baixar` sem `--grau` (o contrato da 1.0.2) não passe a receber
os autos do 2º grau quando alguém põe os Ajustes em 2º grau na mesma
máquina; a `docs/INTEGRACAO-CLAUDE.md` manda toda skill passar `--grau`.

O número aceita dependente de 1 a 5 algarismos (`_PADRAO`: colado à barra,
de 1 a 5; com espaço em volta da barra, de 2 a 5; nunca seguido de letra,
ordinal ou grau), guardado sem encolher (`/0003` → `03`, `/50000` →
`50000`); no nome de arquivo, `-50000` (`_DEPENDENTE_NO_NOME`). As mesmas
faixas valem em `cli._RE_CURTO` (o `--completar` aceita
`0706265-50.2017/50000`), em `chatgpt._RE_NUMERO_CNJ` (`-\d{2,5}`) e nos
padrões da interface (`componentes.js`: `DEPENDENTE_DIGITADO`,
`DEPENDENTE_COM_ESPACO`, `NUMERO_NO_NOME`; `secao-audiencias.js`, com o
campo do número em 31 caracteres; `demo.js`). `Numero` não ganhou campo de
grau: a igualdade, o `hash` e `cnj.chave` são os de antes.

### 14.2 Os nomes dos autos e as duas chaves

`cnj.SUFIXO_2G = " (2G)"`. `nome_dos_autos(n, grau)` é o único lugar que
escreve o sufixo: `n.nome_arquivo` no 1º grau (o nome de sempre) e
`n.nome_arquivo + " (2G)"` no 2º, depois do número e do `-NN` (nunca colado
com hífen, que apagaria o incidente do nome), em ASCII. Vale para o PDF, a
capa, o `_meta.json`, as mídias e o texto: `X (2G).pdf`,
`_controle/X (2G)_capa.json`, `_controle/midias/X (2G)/`, `_ia/texto/X (2G).txt`;
o recurso interno, `X-50000 (2G).pdf`. `grau_do_nome(texto)` → `"2g"` se,
logo depois do número (e do `-NN`), vem ` (2G)` (na leitura, também
` (2g)`, ` (2º grau)` e ` - 2g`; não casa a cópia do Windows ` (2)` nem
` - 2ª Vara`), senão `"1g"`; `NumeroInvalido` sem número.

| Chave | O que é | Quem usa |
|---|---|---|
| **do processo** | `Numero.nome_arquivo` = `cnj.ler_nome_arquivo(t).nome_arquivo` (ignora o sufixo do grau): `X`, `X-01`, `X-50000` | o sigilo (registros, pasta, pauta), o motor (`chave_do_nome`, `processos_no_acervo`, `retirar_do_acervo`, `sigilosos_apurados`), as transcrições, o mascaramento do relatório |
| **dos autos** | `cnj.chave_dos_autos(t)` ou `cnj.nome_dos_autos(n, grau)`: `X`, `X-01`, `X (2G)`, `X-50000 (2G)` | tudo o que é por arquivo: o nome do PDF e dos arquivos ao lado, `Acervo.pdfs()`, o índice, `_ia/texto`, o MCP, o pacote, as linhas do relatório, o `--retomar`, o `JA_BAIXADO` |

No 1º grau, as duas chaves são iguais (nada muda nos acervos de antes).
`chave_dos_autos` de um **texto** vale pelo que o nome diz (sem o sufixo,
1º grau: um arquivo `H.pdf` posto à mão é outro arquivo, diferente de
`H (2G).pdf`); de um **`Numero`**, pelo que o número diz
(`nome_dos_autos(n, grau_do_numero(n) or "1g")`: o HC e o `/50000` só têm
autos no 2º grau).

### 14.3 O e-SAJ do 2º grau (`download/esaj.py`)

* **Catálogo**: no e-SAJ, `urls["base"]` é o portal (o login e o 1º grau)
  e `urls["2g"]` a consulta de 2º grau (no TJAL, `.../cposg5`); sem `2g`, o
  2º grau do e-SAJ daquele tribunal não é baixado (`Tribunal.tem_grau`:
  hoje, só o TJAL o tem). A correção do endereço (`enderecos-locais.json`)
  vale também para o `2g`.
* **Um portal, duas tabelas de rotas** (`RotasESAJ(grau, base, app)`, e não
  uma classe derivada): `busca`, `processo`, `abertura`, `gateway`, `pasta`
  e o prefixo das capturas de diagnóstico (`esaj-…` ou `esaj2g-…`). No 1º
  grau, os endereços de sempre. O grau tem uma fonte só, o Tribunal
  (`PortalESAJ(nav, tribunal, opcoes, ctx, credenciais, *, grau=None)`: um
  `grau=` diferente de `tribunal.grau` é `ValueError`, “passe
  tribunal.no_grau(…)”, porque a credencial e o perfil saem de
  `tribunal.portal`). Sem o endereço do 2º grau, `PortalIndisponivel` (“o
  catálogo de tribunais não traz o endereço do 2º grau do e-SAJ do …”).
  `nome`: “e-SAJ do TJAL (2º grau)”.
* **Login**: o mesmo `entrar()` do 1º grau (CAS, cofre `esaj:TJAL`, perfil
  `esaj-TJAL`, código por e-mail, certificado, manual), que no 2º grau
  termina passando pela porta de entrada da consulta de 2º grau
  (`{app}/open.do?gateway=true`) e conferindo que ela abriu (é o que o
  “Testar 2º grau” prova). A passagem se repete antes da 1ª busca quando a
  sessão foi refeita, e a Pasta Digital que recusa com a sessão de pé
  ganha uma passada pela porta de entrada e nova tentativa antes do “sem
  acesso” (o “SSO por webapp”: sem isso, a consulta ainda não reconhece o
  login, e o processo viraria `SEM_ACESSO`, definitivo). Os eventos do
  portal (`login_aguardando`, `login_concluido`) levam `grau: "2g"`.
* **Busca**: `url_busca_2g(app, numero)`: `search.do` com `cbPesquisa=NUMPROC`,
  `tipoNuProcesso=UNIFICADO`, `numeroDigitoAnoUnificado`,
  `foroNumeroUnificado` (o OOOO do próprio número: `0000` nos originários,
  o da origem nas apelações) e `dePesquisaNuUnificado`, sempre pelo
  **principal**. A consulta responde de **três formas**, lidas de uma vez
  (`_JS_RESPOSTA_2G`): a página do processo (o `input[name=cdProcesso]` e
  os links da tabela de incidentes terminados em `- 50000`), o modal
  “Selecione o processo” (`#modalIncidentes`, um rádio
  `processoSelecionado` por processo, os recursos internos com o título
  “50000 - Embargos de Declaração…”) e a lista (`#listagemDeProcessos`). A
  escolha é sempre pelo **número exato** (`escolher_processo_2g(candidatos,
  numero)`: os 20 dígitos e o dependente; sem dependente, o principal; com
  `/50000`, a opção “50000 - …”): devolve o código, `None` se nenhuma opção
  é do número pedido, e `RuntimeError` se mais de uma é (“o 2º grau do
  e-SAJ tem mais de um processo com este número (…); não baixei, para não
  gravar autos trocados”). A página em segredo que vem sem número, só com o
  código e o pedido de senha, vale só para o pedido do principal, com um
  candidato único (`_pagina_com_senha_2g`). O incidente `/01` do 1º grau não
  existe no 2º: sem opção exata, `ProcessoNaoEncontrado`.
* **Página do processo**: `show.do?processo.codigo=<cd>`, só com o código (o
  foro interno do 2º grau não é o OOOO do número). `conferir_pagina_2g`
  confere os 20 dígitos, o código e, no recurso interno, que a página se
  declara ele (pelo número, pelo título ou, sem eles, pelo código do 2º
  grau, cujos quatro últimos caracteres são o dependente em base 36); para
  o principal, que ela não é a de um recurso interno. No 2º grau não se usa
  a aritmética do incidente do 1º grau (`codigo_incidente`,
  `marca_do_incidente`).
* **Pasta Digital**: `verificarAcessoPastaDigital.do?cdProcesso=<cd>&_=<ms>`
  (o que o botão “Visualizar autos” chama), pedido de dentro da aba: o texto
  que começa por `http` é o endereço da pasta; erro HTTP é falta de acesso
  ou pedido de senha (com o modal de senha à vista, segue pela senha; com a
  sessão caída, `SessaoPerdida`; com a sessão de pé, o “SSO por webapp”
  acima e, recusando de novo, `SemAcesso`). O caminho da pasta sai do
  endereço devolvido (`prefixo_da_pasta`: `/pastadigital` no 1º grau,
  `/pastadigital/sg`, por exemplo, no 2º) e é usado em
  `salvarDocumentoPreparado.do`, `buscarDocumentoFinalizado.do`, `getPDF.do`
  e `getArquivo.do`. Daí em diante, tudo como no 1º grau (seção 13.2):
  **página N = folha N da Pasta Digital do 2º grau**.
* **Guarda da numeração**: no 2º grau, se o plano de folhas tiver folha
  reivindicada por peças de `cdDocumento` diferentes (duas numerações, a da
  origem e a do 2º grau; `folhas_em_duplicidade`), o portal **não monta o
  PDF**: `NAO_SUPORTADO`, sem `causa`, `refazer` falso, com o detalhe “a
  Pasta Digital do 2º grau numera folhas em duplicidade (fls. X–Y em mais
  de uma peça); não gravei os autos, para não perder peças: baixe-os pelo
  portal do tribunal”. Conferido sobre o plano, antes de baixar qualquer
  peça, também na pasta reaberta. A mesma peça listada duas vezes continua
  como antes. No 1º grau, nada muda (a sobreposição fica só anotada).
* **Segredo**: `processo_senha_enviar` soma `#botaoEnviarSenha` ao
  `#btEnviarSenha`; o modal visível `#popupSenhaProcesso` conta em
  `_JS_MODAL_SENHA`; e `#popupSenhaProcesso` sai do texto usado para
  detectar segredo (o texto dele diz “segredo de justiça”: sem isso, todo
  processo do 2º grau seria sigiloso).
* **Capa** (`dados_da_capa`/`formatar_capa(..., grau=)`, `helestron.capa/2`):
  no 2º grau, `grau: "2g"`; em `capa`, também `secao`, `orgao_julgador`,
  `relator` e `origem` (`CHAVES_CAPA`); as listas `numeros_1a_instancia`
  (`[{numero, foro, vara, juiz, obs, principal}]`, com o `numero` no
  formato CNJ, ou `""` sem número legível; é nela, no nível de cima do
  `_capa.json`, que o motor procura a ação de origem para o sigilo — o
  objeto `capa` traz só rótulo e texto), `composicao` (`[{papel, nome}]`), `julgamentos` (`[{data,
  situacao, decisao}]`) e `subprocessos` (as linhas de “Incidentes, ações
  incidentais, recursos…”, as mesmas de `incidentes`). O `_capa.txt`
  começa por “Processo X - TJAL (e-SAJ, 2º grau)”, diz em “== Arquivo ==”
  que a página N é a folha N da Pasta Digital do 2º grau (a dos autos de
  origem pode ser outra) e tem no fim as seções “Números de 1ª Instância”,
  “Composição do Julgamento” e “Julgamentos”. Capa e mídias são gravadas
  pelo nome do destino (`destino.stem`). No 1º grau, a capa é byte a byte a
  da 1.0.2.
* **Não encontrado**: 1º grau, “não encontrado no 1º grau do e-SAJ do TJAL.
  Confira o número; ” e a dica de `modelos.dica_de_grau(n, "1g")` (que
  manda escolher o 2º grau); 2º grau, “não encontrado no e-SAJ do TJAL (2º
  grau). Confira o número; ” e `dica_de_grau(n, "2g")` (o recurso pode não
  ter subido: escolher o 1º grau; para o número que só existe no 2º grau, a
  dica diz que trocar o grau do lote não muda a busca). As frases de troca
  de grau têm uma fonte só (`modelos.DICA_GRAU_2G`, `DICA_GRAU_1G`,
  `dica_de_grau`), para o e-SAJ, o eProc e o motor.
* **Manifesto**: `manifesto_esaj(..., grau=self.grau)`.

### 14.4 O eProc do 2º grau e a chave `eproc2g` (`nucleo/tribunais.py`, `download/eproc.py`)

O `Tribunal` ganhou `grau` (último campo, padrão `"1g"`) e:

| Membro | Valor |
|---|---|
| `portal` | `esaj:TJAL` (o e-SAJ nos dois graus: o mesmo login), `eproc:TJAL` (eProc, 1º grau), `eproc2g:TJAL` (eProc, 2º grau): a chave do cofre, do perfil do navegador e da sessão |
| `portal_do_sistema` | `esaj:TJAL` ou `eproc:TJAL`, sem o grau: a chave dos endereços corrigidos e da folha “Endereço do portal” |
| `perfil` | `nome_do_perfil(portal)`: `esaj-TJAL`, `eproc-TJAL`, `eproc2g-TJAL` (o do certificado, com `-certificado`) |
| `rotulo` | `TJAL · e-SAJ`; no 2º grau, `TJAL · e-SAJ (2º grau)`, `TJAL · eProc (2º grau)` |
| `tem_grau(grau)` | o Helestron baixa deste sistema neste grau? (e-SAJ: `base` ou `urls["2g"]`; eProc: o endereço do grau) |
| `no_grau(grau)` | o Tribunal no grau, com o alternativo no mesmo grau (ou sem alternativo, se ele não o tiver); chamado sempre no Tribunal do catálogo |
| `urls_para(numero, grau)` | sem `grau`, o do Tribunal; no eProc, **estrito no 2º grau**: sem endereço do 2º grau, `[]`, nunca o do 1º |

Também `tribunais.RE_PORTAL` (`esaj`, `eproc` ou `eproc2g`, dois-pontos e a
sigla: a regra única das chaves, que a API e o navegador usam),
`PREFIXO_EPROC_2G`, `por_portal(portal)` (o Tribunal do portal, o de
`eproc2g:` já no 2º grau; `None` se o tribunal não tem aquele sistema ou o
2º grau dele) e `nome_do_perfil`. No catálogo do TJAL, o eProc tem `1g`
(`eproc1g`) e `2g` (`eproc2g`); o `eproc.tjal.jus.br`, que não resolve,
saiu.

A senha do eProc do 1º grau **nunca** é usada no 2º grau. A chave
`eproc2g:<SIGLA>` vale em todo lugar:

| Lugar | Como |
|---|---|
| cofre de senhas | `motor._credenciais(tribunal)` → `cofre.obter(tribunal.portal)` (o Tribunal do grupo já está no 2º grau); sem a senha no modo senha, o grupo vira manual (a janela abre para o usuário entrar) |
| linha de comando | `cli._pedir_credenciais` pergunta por `t.portal` dos Tribunais no grau (“Acesso ao eProc do TJAL (2º grau)”) |
| perfil do navegador e sessão | `motor.fabrica_navegador_padrao` abre `caminhos.PERFIS / tribunal.perfil` (`perfis/eproc2g-TJAL`, com o `sessao.json` dentro) |
| esquecer o acesso | `navegador.pastas_do_portal("eproc2g:TJAL")` → `perfis/eproc2g-TJAL` e `perfis/eproc2g-TJAL-certificado`; `esquecer_portal` não toca no 1º grau |
| API e Ajustes › Acessos | a linha própria `eproc2g:TJAL` (seção 6.3), “Adicionar acesso” com “TJAL · eProc (2º grau)”, o apagar e o “Testar” do 2º grau |
| endereços | continuam sob `eproc:TJAL`, grau `2g` (`definir_endereco("eproc2g:TJAL", "2g", url)` grava sob `eproc:TJAL`) |

O `PortalEProc` lê o grau **só** do Tribunal (`grau=` divergente é
`ValueError`, como no e-SAJ); sem o endereço do grau, `PortalIndisponivel`
(“o catálogo de tribunais não traz o endereço do eProc do TJAL (2º grau)”).
`nome`: “eProc do TJAL (2º grau)”. Não encontrado: no 2º grau, “não
encontrado no eProc do TJAL (2º grau). Confira o número; ” e
`dica_de_grau(n, "2g")`; no 1º, a frase de antes com a dica de
`dica_de_grau(n, "1g")`. Os eventos (`login_aguardando`, `acao_na_janela`,
`login_concluido`), o manifesto (`manifesto_do_processo(..., grau=)`) e o
`_capa.json` levam `grau: "2g"` só no 2º grau; capa e mídias são gravadas
pelo nome do destino. O perfil do usuário (`[eproc] perfil`) e o modo de
entrada (`[eproc] login`) valem para os dois graus. Os eventos “de outro
grau” (os do processo de origem que o eProc do 2º grau mostra) ficam de
fora nesta versão: o PDF traz os eventos do próprio processo no 2º grau.

### 14.5 Motor, relatório e linha de comando (`download/motor.py`, `cli.py`, `acompanhamento.py`)

* **Lote**: para cada número, `grau = cnj.grau_do_processo(n, opcoes.grau)`;
  o `ResultadoProcesso` sai com `grau` (que `absorver()` não troca), e o
  lote guarda `graus` e `autos` (a chave dos autos de cada item). A
  deduplicação continua por `cnj.chave(n)` (num lote, o grau é função do
  número).
* **Grupos**: por tribunal e grau (`f"{t.chave}|{grau}"`, na ordem da
  primeira aparição), com o Tribunal do grupo já `no_grau(grau)`. Se o
  sistema **principal** não tem o grau (`not t.tem_grau(grau)`: o e-SAJ do
  TJSP), `NAO_SUPORTADO`, sem causa: “o 2º grau do e-SAJ do TJSP ainda não
  é baixado pelo Helestron; baixe-o pelo portal do tribunal”. Nesses
  tribunais, o “não encontrado” do 1º grau não manda escolher o 2º grau
  nas Opções do lote: a dica é `modelos.DICA_SEM_2G` (“se o processo
  estiver no 2º grau, baixe-o pelo portal do tribunal...”), escolhida por
  `tribunais.baixa_o_2o_grau(t)` e passada a `modelos.dica_de_grau(...,
  com_o_2o_grau=False)` pelo e-SAJ e pelo eProc. O
  alternativo do 2º grau é o eProc do 2º grau, se houver. O nome do grupo
  diz o grau (“e-SAJ do TJAL (2º grau)”), e a frase de quando nenhum dos
  dois sistemas achou o processo no 2º grau é “não encontrado no e-SAJ nem
  no eProc do TJAL (2º grau); confira o número; ” e
  `dica_de_grau(n, "2g")` (no 1º grau, a de antes).
* **Nomes pela chave dos autos**: `_ja_baixado`, a área provisória
  (`provisorio/<chave dos autos>`), `_limpar_parcial`, o alvo do item,
  `_guardar`, `_levar` e `_retirar_do_acervo`; `_registro_anterior` lê o
  `_meta.json` pelo nome do PDF. O PDF do 1º grau na pasta não é
  `JA_BAIXADO` de um pedido do 2º grau, nem o contrário. `_baixar_de_novo`:
  o PDF com o nome destes autos cujo manifesto diz outro grau é baixado de
  novo (“o PDF na pasta é do outro grau …”).
* **Relatório**: `COLUNAS` ganha `grau`, a última. A linha leva `r.grau`
  (a mascarada também: não identifica ninguém). As linhas se casam pela
  chave dos autos (`_chave_da_linha`), em `_mesclar_relatorios`,
  `_linhas_csv`, `_pdf_que_fica`, `_linha_anterior`,
  `ler_relatorio_do_lote` (que devolve pares de chave dos autos, ou `None`,
  e linha) e na deduplicação do `_mascarar_relatorios`; `_chave_relatorio`
  continua a do processo. O grau vazio (CSV de versão anterior) é
  `cnj.grau_do_numero(n) or "1g"` (`_grau_da_linha`): a 1.0.2 procurava o
  HC de órgão `0000` no 1º grau e gravava a linha sem grau, e lida como 1º
  grau ela nunca seria substituída pela nova nem retomada.
* **Registros**: `_meta.json`, `consultas[]`, `essencial_da_paginacao` e os
  eventos do motor (`grupo_inicio`, `navegador_ocupado`, `login_falhou`,
  `sessao_caiu`) levam `grau: "2g"` só no 2º grau (`_do_grau`).
* **Sigilo**: seção 12 (“O sigilo vale nos dois graus”).
* **Linha de comando**: `--grau` (seção 5.1); `_RE_CURTO` com `/50000`; as
  credenciais pelos Tribunais no grau; o `--retomar` por chave dos autos e
  por grau (seção 5.1); `--texto` como antes (`<pdf.stem>.txt`: no 2º grau,
  `X (2G).txt`). O `Acompanhamento` grava `grau` no topo desde o primeiro
  JSON e em cada processo (`processo_json`), e o `nome_arquivo` sem PDF é
  `cnj.nome_dos_autos(ler_nome_arquivo(numero), r.grau)`.
* **`__main__.py`**: `RECURSOS` termina em `baixar.grau`, `esaj.2g` e
  `eproc.2g`; o `caminhos --json` traz `grau` (o padrão da janela); o
  `preparar --pasta` dá o `grau` de cada item (seção 5.2).

### 14.6 O campo `grau` em cada formato

| Onde | 1º grau | 2º grau | Ausente |
|---|---|---|---|
| JSON `helestron.baixar/1`: topo e cada processo | `"1g"` | `"2g"` | — (sempre presente, desde o primeiro JSON gravado) |
| `relatorio.csv`: coluna `grau`, a última, depois de `causa` | `1g` | `2g` | vazia (CSV de versão anterior) = `cnj.grau_do_numero(n) or "1g"` |
| API: `item`, `resultado` da tarefa de download, leitura da relação (`grau_fixo`, `graus`), acessos (`grau`, `graus`) | `"1g"` | `"2g"` | — |
| `caminhos --json`: `grau` (o padrão da janela; o `baixar` sem `--grau` usa `1g`) | `"1g"` | `"2g"` | — |
| `preparar --pasta --json`: `grau` de cada item | `"1g"` | `"2g"` | — |
| `textos.cabecalho()`, `textos.info_do_texto()` | `"1g"` | `"2g"` | — |
| manifesto do PDF, `_meta.json`, `_capa.json`, `consultas[]`, `paginacao` do JSON | não vai | `"grau": "2g"` | 1g |
| eventos (`ctx.evento`) de grupo e de login, os do motor e os dos portais, e com eles o `aguardando` e o `ultimo_evento` do JSON | não vai | `"grau": "2g"` | 1g |
| texto (1ª linha) | sem nada | termina em `grau=2g` | 1g |

### 14.7 Texto, índice, MCP e pacote no 2º grau (`compartilhar/`)

* **Texto** (`textos.py`, formato 2, marcas iguais): o grau dos autos é o do
  manifesto e, sem ele, o do nome (`grau_dos_autos`). No 2º grau, a 1ª linha
  termina em `grau=2g`; a abertura do e-SAJ diz “autos do e-SAJ do TJAL, 2º
  grau (Pasta Digital do processo no Tribunal). A página N deste PDF é
  sempre a folha N destes autos (fls. 1 a U).”, e o como citar é
  `COMO_CITAR_ESAJ_2G`: cita-se a marca `[fl. N]`, a folha da Pasta Digital
  do 2º grau; os autos de origem são outro arquivo, sem `(2G)`, com folhas
  próprias (“fl. N dos autos de origem”); e o carimbo “fls.” diferente da
  marca é de outros autos, inclusive dos de origem, de mesmo número: não se
  cita como folha destes, cita-se a marca e avisa-se o magistrado. É **o
  contrário do 1º grau de propósito** (`COMO_CITAR_ESAJ` manda citar a
  folha carimbada que diverge, porque lá o carimbo de outro processo traz
  outro número): no 2º grau, a peça da origem trazida à Pasta Digital com o
  carimbo “fls. 120”, numa página marcada `[fl. 735]`, não se distingue
  pelo número. No eProc do 2º grau, `COMO_CITAR_EPROC_2G` e
  `COMO_CITAR_EPROC_NAO_GARANTIDA_2G` acrescentam `EVENTOS_DO_2G` (os eventos
  são os do processo no 2º grau; o da origem cita-se “evento N, RÓTULO, do
  processo de origem”); sem paginação garantida, `COMO_CITAR_NAO_GARANTIDA_2G`
  não manda citar a folha carimbada (ela pode ser a da origem).
* **Índice e contexto** (`preparo.py`): `INDICE.md` com uma linha por PDF
  de autos e a coluna **Grau** (seção 13.7); `CLAUDE.md`, `AGENTS.md` e a
  habilidade com a estrutura `Processos/<lote>/<número CNJ> (2G).pdf`, o
  `-50000` e a regra de citação do 2º grau (os modelos da 1.0.2 congelados
  em `CONTEXTO_1_0_2` e `SKILL_1_0_2` são regravados com o novo). Os textos
  órfãos são apagados pela chave dos autos: o `X (2G).txt` do
  `baixar --texto` fica enquanto o PDF dele estiver no acervo.
* **MCP** (`mcp_servidor.py`): `Acervo.pdfs()` é `{chave dos autos: Path}`
  (“o mais recente vence” só entre arquivos dos mesmos autos; os do 1º e do
  2º grau do mesmo número ficam os dois), filtrado pelo sigilo da chave do
  processo; `Acervo.numerados()` e `transcricoes()` continuam pela chave do
  processo. `listar_acervo`: `- X (2G) — 2º grau — N pág. — <caminho> —
  <paginação>` (o 1º grau, como antes). `ler_processo(numero, …, grau=None)`:
  `numero` aceita a chave da listagem (`X (2G)`), o número (`X`,
  `X/50000`), `X (1º grau)` e, com `grau` (`"1g"`/`"2g"`), o grau; com os
  dois graus no acervo e sem grau, erro: “o processo X tem autos dos dois
  graus no acervo (X e X (2G)): informe grau="1g" ou grau="2g" (ou peça
  "X (1º grau)" ou "X (2G)")”; com um grau só, serve-o. O cabeçalho do 2º grau diz
  “Processo X — e-SAJ, 2º grau: …” e que a página N é a folha N da Pasta
  Digital do 2º grau, e que o carimbo “fls.” diferente da marca é de outros
  autos; o dos autos do 1º grau, quando o acervo tem também os do 2º, diz
  “Processo X (1º grau — autos de origem do X (2G)) — …” e lembra que, no 2º
  grau, a folha se cita “fl. N dos autos de origem”. Nos cabeçalhos novos,
  o plural é escrito por extenso (“1 página no PDF”, “2 páginas no PDF”); o
  do acervo só de 1º grau é o de antes. `buscar(termo, numero=None,
  grau=None)`: com `numero`, os autos dos dois graus (ou do pedido); cada
  achado diz de que autos saiu (`X (2G), fl. 12` e, com os dois graus do
  processo no acervo, `X (1º grau), fl. 12`). `FERRAMENTAS`: `grau`
  (`enum ["1g", "2g"]`) em `ler_processo` e `buscar`, e a regra do 2º grau
  nas descrições e em `INSTRUCOES`. Acervo só de 1º grau: a saída é a de
  antes, byte a byte.
* **Pacote** (`chatgpt.py`): seção 13.7. **Espelho** (`nuvem.py`): nada
  mudou (a chave é a do processo, para o sigilo, e os nomes `(2G)` são
  copiados como são).

### 14.8 Sigilo nos dois graus

Seção 12 (“O sigilo vale nos dois graus”). Em resumo: o sigilo é do
processo; `sigilo.contem` normaliza a chave dos autos; o apurado num grau
tira os autos dos dois do acervo, do índice, do MCP, do pacote e da nuvem;
o originário do 2º grau herda o sigilo da ação de origem pela capa do 2º
grau, no download e depois dele (a capa guardada em `_controle` é uma das
fontes da regra única); e o sigilo sabido só em outro computador não chega
a este (risco aceito, no manual).

### 14.9 Interface e API

* **Ajustes** (`servidor/esquema.py`): `Campo("download", "grau",
  "escolha", "Grau dos processos", …, opcoes=(("1g", "1º grau"), ("2g",
  "2º grau")))`, o primeiro do grupo Download; o valor mostrado e o gravado
  passam por `cnj.normalizar_grau` (`2` e `2º` editados à mão viram `2g`; o
  que não for grau aparece como `1g`). No `config.ini`, `[download] grau`,
  padrão `1g`, com o comentário de que a linha de comando não o lê.
* **API**: seção 6.3 (leitura com `grau_fixo` e `graus`; `opcoes.grau` do
  download, com o 400 “Grau inválido (use 1g ou 2g).”; `grau` no `item` e
  no `resultado`; a pauta sempre em `1g`; os acessos com `eproc2g`, `grau`
  e `graus`; o testar com `grau`; os endereços pelo sistema; os tribunais
  com `graus` e `graus_alternativo`). `servicos.resumo_acervo` conta
  processos distintos (o “N processos” do Início não conta duas vezes o
  processo com os autos dos dois graus).
* **Tela Processos** (`secao-processos.js`): seção 7.2. O grau do lote é o
  rascunho da tela (`r.opcoes.grau`), pré-preenchido pelos Ajustes; o grau
  de cada linha é `grau_fixo` ou o do lote; o “Acesso aos portais” mostra
  uma linha por portal do sistema principal de cada linha, no grau dela (o
  e-SAJ com a mesma chave nos dois graus; o eProc do 2º grau,
  `eproc2g:<SIGLA>`); o “Tentar de novo” manda `grau: res.grau`
  (contrato C9).
* **Ajustes › Acessos** (`secao-ajustes.js`, `api.js`): contrato C1. O
  rodapé: “O acesso ao e-SAJ vale para o 1º e o 2º grau; o eProc do 2º grau
  tem acesso próprio.”
* **Demonstração** (`demo.js`): versão 1.1.0; `grau` nos itens, na leitura
  e no resultado; a linha `eproc2g:TJAL`; `download.grau` nos Ajustes; o
  testar com grau; o lote da Pauta em 1º grau; `NAO_SUPORTADO` no 2º grau
  de tribunal sem ele.

### 14.10 Compatibilidade: o que mudou para o 1º grau

Só acréscimos: o `grau` do JSON do `baixar` (no topo e em cada processo),
do `caminhos --json` (e os três recursos no fim de `recursos`), do
`preparar --pasta --json` e da API; a coluna `grau` no fim do
`relatorio.csv` (a linha de versão anterior de um número que só existe no
2º grau, como o HC de órgão `0000`, passa a valer como do 2º grau); a
coluna Grau do `INDICE.md` (e a frase do 2º grau, só com autos do 2º grau
no acervo); a dica final da frase de “não encontrado” do 1º grau (que
agora manda escolher o 2º grau); o endereço do 2º grau do e-SAJ do TJAL na
folha “Endereço do portal” e o fim do `eproc.tjal.jus.br`; o campo “Grau
dos processos” nos Ajustes; o pedido da tela ao download, que leva sempre
`grau`; a versão 1.1.0. Não mudaram: os nomes de arquivo, a capa, o
`_meta.json`, o manifesto, o texto (1ª linha e corpo), os eventos, as
`consultas`, as chaves do cofre e os perfis, o `numero` e o
`nome_arquivo` de tudo o que não é dependente de cinco algarismos, a saída
do MCP num acervo só de 1º grau e o grau do `baixar` sem `--grau` (1g, como
na 1.0.2, mesmo com os Ajustes em 2º grau).

### 14.11 Fora desta versão e pontos abertos

* Os eventos “de outro grau” do eProc (os do processo de origem): fora.
* A pauta de sessões de julgamento do 2º grau: fora (a Pauta é a das
  audiências do 1º grau, e o “Baixar os autos” dela vai em 1º grau).
* Uma coluna “Grau” na relação: não é lida (o grau é o do lote).
* O dependente de 1 a 4 algarismos (`/01`, incidente do 1º grau) não entra
  na regra do número: num lote de 2º grau, ele é procurado no 2º grau e
  volta “não encontrado” com a dica do 1º grau (não grava autos errados).
* O órgão começando por `9` vai ao 2º grau em todo tribunal. Na Justiça
  Federal, a turma recursal fica no eProc das seções (1º grau), e esses
  originários não são achados; no TJAL, as turmas recursais do e-SAJ estão
  na consulta de 2º grau, mas a base do eProc da Turma Recursal (o do 1º ou
  o do 2º grau) ainda não foi confirmada em caso real.
* A numeração da Pasta Digital do 2º grau (se a apelação traz as peças da
  origem e se as folhas continuam as dela) só um caso real confirma; a
  guarda da seção 14.3 transforma duas numerações em `NAO_SUPORTADO`.
