# Helestron — Manual do usuário

Versão 1.0.2 · para Windows 10 e 11 (64 bits)

O Helestron reúne, numa única janela, as tarefas do gabinete que mais tomam
tempo:

| Função | O que faz | Onde o resultado fica |
|---|---|---|
| **1. Baixar processos** | Com o **seu** login no e-SAJ ou no eProc, baixa todos os processos de uma relação (Excel, Word, PDF, lista colada ou link): **um PDF por processo**, com o número do processo como nome | `Acervo\Processos\<nome do lote>\` |
| **2. Transcrever audiência** | Transcreve a audiência **ao vivo**, pelo microfone, no próprio computador; transcreve também gravações de áudio ou vídeo já existentes | `Acervo\Transcricoes\<número do processo>.docx` |
| **3. Pauta de audiências** | Traz a pauta do e-SAJ e do eProc, acompanha as mudanças e exporta tudo para o Excel | `Pauta\` (fora do acervo) |
| **4. Compartilhar com IA** | Deixa o acervo pronto para o Claude Code, o Claude Cowork, o Claude Desktop, o ChatGPT Work e o Codex, sem anexar arquivo por arquivo | a própria pasta `Acervo` |

As pastas `Acervo`, `Sigilosos` e `Pauta` ficam em `Documentos\Helestron`
(veja [Onde ficam os arquivos](#onde-ficam-os-arquivos)).

> **O Helestron é ferramenta de apoio.** Autos baixados, transcrições, pautas
> e o que a inteligência artificial produzir a partir deles são material de
> trabalho para conferência e decisão do magistrado (Resolução CNJ
> nº 615/2025).

## Sumário

- [O que é o Helestron](#o-que-é-o-helestron)
- [Instalação](#instalação)
- [Primeiro uso](#primeiro-uso)
- [1. Baixar processos](#1-baixar-processos)
- [2. Transcrever audiência](#2-transcrever-audiência)
- [3. Pauta de audiências](#3-pauta-de-audiências)
- [4. Compartilhar com IA](#4-compartilhar-com-ia)
- [Segredo de justiça](#segredo-de-justiça)
- [Ajustes](#ajustes)
- [Onde ficam os arquivos](#onde-ficam-os-arquivos)
- [Atualizar](#atualizar)
- [Desinstalar](#desinstalar)
- [Problemas comuns](#problemas-comuns)
- [Aviso de uso](#aviso-de-uso)

---

## O que é o Helestron

O Helestron é um programa para Windows, de uso em gabinete judicial. Ele roda
no seu computador, com o seu acesso aos portais, e guarda tudo em pastas
comuns do Windows, que você abre pelo Explorador de Arquivos como qualquer
outra.

A janela tem, à esquerda, a barra lateral com as seções:

| Seção | Para quê | Atalho |
|---|---|---|
| **Início** | saudação, as quatro funções, “Hoje na pauta”, “Atividade recente” e “Primeiros passos” | Ctrl+1 |
| **Processos** | baixar os autos de uma relação | Ctrl+2 |
| **Audiências** | transcrever a audiência | Ctrl+3 |
| **Pauta** | a pauta de audiências | Ctrl+4 |
| **Compartilhar** | entregar o acervo à IA | Ctrl+5 |
| **Ajustes** | acessos, pastas e preferências | Ctrl+6 |
| **Ajuda** | passo a passo, perguntas frequentes e atalhos | Ctrl+7 |

No rodapé da barra lateral aparecem os trabalhos em andamento (um download,
uma sincronização da pauta, o preparo do acervo), cada um com um anel de
progresso; clique neles para ir à tela que os acompanha. Ali também ficam a
versão do programa e a indicação “ligado” (ou “sem conexão”).

As cores seguem uma regra simples. Os ícones são sempre em tons de azul e
cinza, e cada assunto tem o seu tom em todas as telas (o download, por
exemplo, é sempre azul-marinho, e a pauta, azul-ciano). Verde, âmbar e
vermelho ficam reservados para dizer como as coisas estão (pronto, atenção,
erro), para o botão de gravar e para os botões que encerram ou apagam algo.

### Para quem usava o Assessor Integrado

O Helestron substitui o antigo Assessor Integrado. O que mudou:

- a instalação é feita por **um único arquivo**, `Helestron-Setup-1.0.2.exe`,
  sem o `INSTALAR.bat`, sem PowerShell e sem baixar nada durante a
  instalação;
- as pastas de trabalho passaram para `Documentos\Helestron`; os arquivos do
  Assessor Integrado continuam onde estavam e podem ser copiados para as
  novas pastas, se você quiser;
- as **senhas** guardadas no Assessor Integrado **não são aproveitadas**:
  cadastre-as de novo em **Ajustes › Acessos aos portais**;
- o conector do acervo no Claude Desktop passou a se chamar **helestron**;
- ao instalar o Helestron, o instalador **tira sozinho os restos do Assessor
  Integrado**: o atalho **Assessor Integrado** da Área de Trabalho e do Menu
  Iniciar (só o que abre mesmo o Assessor Integrado; um atalho de mesmo nome
  que abra outra coisa fica) e o conector antigo do acervo
  (*assessor-integrado*) no Claude Desktop e no Codex/ChatGPT Work. Os seus
  outros conectores ficam, e o arquivo de configuração de cada programa é
  guardado antes, ao lado, com “antes-do-helestron” e a data no nome. Se o
  Claude Desktop estiver aberto, feche-o pela bandeja do Windows (perto do
  relógio) e abra de novo para ele deixar de mostrar o conector antigo. Se a
  verificação da instalação (**Ajustes › Sobre e diagnóstico › Verificar a
  instalação**) acusar que “o Claude Desktop ainda tem o conector da
  versão anterior (Assessor Integrado)”, clique em **Conectar o acervo** (ou
  **Reconectar o acervo**), na tela Compartilhar: o antigo sai junto;
- há uma função nova: a **Pauta de audiências**.

---

## Instalação

### Do que você precisa

- **Windows 10 (versão 1809 ou mais recente) ou Windows 11, de 64 bits.**
- Espaço em disco: o programa ocupa cerca de 850 MB. O assistente mostra
  o espaço necessário antes de copiar.
- Para baixar processos e ler a pauta, o **Google Chrome** ou o **Microsoft
  Edge** (o Edge já vem no Windows).
- Para transcrever, um **microfone** (o do notebook serve; um microfone de
  mesa capta melhor a sala de audiências).
- Para a janela do programa, o componente **WebView2** da Microsoft (versão
  101 ou mais recente), que já vem no Windows 11 e no Windows 10 atualizado.
  Sem ele, ou com uma versão mais antiga, o Helestron abre no Edge (veja
  [Problemas comuns](#a-janela-abriu-no-microsoft-edge)).

### Passo a passo

1. **Baixe o instalador.** Na página de versões do Helestron
   (<https://github.com/Helestron/Desenvolvimento-de-Aplicativos/releases>),
   abra a versão mais recente e, na lista de arquivos (**Assets**), clique em
   **`Helestron-Setup-1.0.2.exe`** (cerca de 400 MB). Deixe-o na pasta
   **Downloads**: é lá que o botão **Reparar** o procura, se um dia for
   preciso (veja [Problemas comuns](#o-helestron-não-pôde-abrir-antivírus)).

   O navegador pode avisar que o arquivo “não é baixado com frequência”. No
   Edge, clique nos três pontos ao lado do aviso, em **Manter** e, se ele
   perguntar de novo, confirme que deseja manter o arquivo.

2. **Dê dois cliques no arquivo baixado.** Na primeira vez, o Windows mostra
   a tela azul **“O Windows protegeu o computador”**. Clique em
   **Mais informações** e depois em **Executar assim mesmo**.

   > O aviso do SmartScreen aparece porque o instalador ainda não tem
   > assinatura digital de código (um certificado comprado de uma autoridade
   > certificadora), não porque haja algo de errado com ele. Se a equipe de
   > informática quiser conferir que o arquivo é o publicado, a página de
   > versões traz, ao lado do instalador, o arquivo `.sha256` com a
   > impressão digital (SHA-256) dele.

3. **Siga o assistente**, todo em português:

   | Tela | O que fazer |
   |---|---|
   | **Bem-vindo ao Helestron** | clique em **Próximo** |
   | **Pasta do programa** | deixe a pasta sugerida e clique em **Próximo**. Para usar outra, clique em **Procurar**. Se não houver permissão para gravar nela, como em `C:\Program Files`, o assistente avisa e continua nesta tela. Se a pasta escolhida já tiver outros arquivos (seus ou de outro programa), o assistente avisa que o Helestron será instalado numa pasta própria dentro dela, `<pasta>\Helestron`: **OK** aceita, e o campo passa a mostrar o caminho novo; **Cancelar** volta para você escolher outra. Se até essa subpasta já tiver outros arquivos, ele pede uma pasta vazia. Se o Helestron já estiver instalado em **outra** pasta, o assistente avisa que ele será fechado e removido de lá e instalado na pasta escolhida (as configurações, as senhas, os processos e as transcrições são mantidos): **OK** confirma; **Cancelar** volta para a escolha |
   | **Opções** | o programa é obrigatório; desmarque **Atalho na Área de Trabalho** se não quiser o ícone ali; clique em **Instalar** |
   | **Instalando** | aguarde: o Helestron é copiado e, no fim, conferido (pode levar até um minuto) |
   | **Pronto!** | a página lembra que o Helestron abre pelo atalho no Menu Iniciar ou na Área de Trabalho e que, na primeira vez, o acesso ao e-SAJ e ao eProc é cadastrado em **Ajustes**; deixe marcado **Abrir o Helestron** e clique em **Concluir** |

Se o Helestron estiver aberto (numa atualização, por exemplo), o instalador o
fecha antes de copiar. Uma audiência sendo transcrita **não é interrompida**:
o instalador pede que você a encerre no Helestron (botão **Encerrar**: o
documento é salvo) e clique em **Repetir**; **Cancelar** deixa a instalação
para depois, sem mudar nada (veja [Atualizar](#atualizar)).

Se, durante a cópia, aparecer **“Não foi possível gravar o arquivo”**, há
duas causas possíveis: o Helestron (ou o Claude Desktop) ainda está aberto
— feche-o e clique em **Repetir** — ou a pasta escolhida exige
administrador — clique em **Anular** e instale na pasta sugerida. **Ignorar**
pula aquele arquivo, e a conferência final vai acusar a falta dele.

### Onde o Helestron é instalado

Na pasta `%LOCALAPPDATA%\Programs\Helestron`, que é
`C:\Users\<seu usuário>\AppData\Local\Programs\Helestron`. O instalador cria
o atalho **Helestron** no Menu Iniciar e na Área de Trabalho e registra o
programa em **Aplicativos instalados**, de onde ele pode ser desinstalado.
Ele também anota no registro do Windows, na chave
`HKCU\Software\Helestron`, onde o programa está, para quem o chama pela
linha de comando (veja [Linha de comando](#linha-de-comando-para-a-equipe-de-informática)).

Só há um Helestron por usuário: se você instalar a versão nova numa pasta
diferente da anterior, o programa **muda de pasta**. O Helestron da pasta
anterior é fechado e removido de lá (só os arquivos que a instalação pôs
na pasta), e a instalação nova passa a ser a registrada.

Os seus dados (configurações, senhas, processos, transcrições e pauta) ficam
**em outras pastas** e não são tocados quando o programa é atualizado ou
reinstalado.

A pasta do programa é **só do Helestron**. Nela fica a lista
`arquivos-instalados.txt`, com tudo o que a instalação pôs lá. A atualização
e o desinstalador apagam **só os arquivos dessa lista**, um por vez, e uma
pasta só sai se ficar vazia: nada do que você ou outro programa tiver posto
ali é apagado (mesmo assim, guarde os seus arquivos em outro lugar). Pelo
mesmo motivo, o instalador nunca põe o programa no meio de outros arquivos
(veja a tela **Pasta do programa**, acima).

### Sem administrador

A instalação é **só para o seu usuário**: não pede senha de administrador e
não mexe em pastas do sistema. Outro usuário do mesmo computador que quiser
usar o Helestron instala na própria conta.

### Sem internet

Tudo vai dentro do instalador: o Python, as bibliotecas, o modelo de
transcrição e os modelos da separação de vozes. Nada é baixado durante a
instalação, que funciona inclusive em computador sem internet ou numa rede
que bloqueia downloads. Nenhuma janela preta de comandos se abre.

### A conferência final

No fim da instalação, o assistente roda a **conferência da instalação**:

- confere **cada arquivo** do programa (o tamanho e a impressão digital
  SHA-256) contra a lista do que esta versão instala;
- **abre todos os módulos** do programa, um por um;
- **carrega o modelo de transcrição**;
- confere se o componente da janela (WebView2, versão 101 ou mais recente)
  ou, na falta dele, o Edge está disponível.

Se tudo estiver em ordem, aparece “Instalação conferida: tudo certo.” Se algo
faltar (quase sempre, um arquivo que o antivírus pôs em quarentena), o
assistente diz o que aconteceu e onde está o relatório:

```
%LOCALAPPDATA%\Helestron\Logs\verificacao-instalacao.txt
```

Quase sempre resolve instalar de novo. Se o problema continuar, peça à equipe
de informática que libere, no antivírus, a pasta do programa.

Há um caso à parte: o computador não tem o WebView2 nem o Microsoft Edge, e o
navegador padrão é o Internet Explorer, que não abre o Helestron. O programa
fica instalado, mas o assistente avisa que falta o **Microsoft Edge WebView2
Runtime** (gratuito, da Microsoft) e pede que a equipe de informática o
instale antes de abrir o Helestron.

Além disso, **a cada abertura** o Helestron confere rapidamente se os seus
arquivos essenciais estão lá. Se faltar algum, ele mostra uma tela própria
(ou, se faltar um dos arquivos sem os quais nem essa tela abre, uma caixa de
mensagem que diz qual é) em vez de quebrar no meio do uso (veja
[Problemas comuns](#o-helestron-não-pôde-abrir-antivírus)).

### Instalação silenciosa (para a equipe de informática)

O instalador aceita o modo silencioso do NSIS:

```bat
Helestron-Setup-1.0.2.exe /S
Helestron-Setup-1.0.2.exe /S /D=D:\Programas\Helestron
```

- `/S` instala sem nenhuma tela, na pasta padrão
  (`%LOCALAPPDATA%\Programs\Helestron`) ou, numa atualização, na mesma pasta
  da instalação anterior.
- `/D=` escolhe a pasta. Tem de ser o **último** argumento e vai **sem
  aspas**, mesmo que o caminho tenha espaços. Se a pasta já tiver outros
  arquivos (do usuário ou de outro programa), o Helestron vai, sem
  perguntar, para `<pasta>\Helestron`; se essa subpasta também tiver outros
  arquivos, nada é copiado, e o instalador sai com o código 3. Se o
  Helestron já estiver instalado em outra pasta, ele é fechado e removido de
  lá, sem perguntar, como numa atualização (com uma audiência sendo
  transcrita, o instalador desiste com o código 7).
- A instalação é **por usuário**: rode o instalador **na conta de quem vai
  usar o programa**, e não como SYSTEM nem com outra conta, senão o Helestron
  vai para o perfil errado.
- Para esperar o fim num script do `cmd`, use
  `start /wait "" Helestron-Setup-1.0.2.exe /S` e leia o `%ERRORLEVEL%`.
- A conferência final roda também no modo silencioso, e o relatório fica em
  `%LOCALAPPDATA%\Helestron\Logs\verificacao-instalacao.txt`.
- Numa atualização, o Claude Desktop e o Codex podem continuar abertos, mesmo
  usando o conector do acervo: os arquivos do programa que eles prendem são
  renomeados para a pasta `.antigos`, dentro da pasta do programa, e
  apagados no próximo logon do usuário (pela chave RunOnce do Windows) ou na
  próxima abertura do Helestron. Nenhum programa é encerrado.

Códigos de saída:

| Código | Significado |
|---|---|
| 0 | instalado e conferido |
| 2 | copiado, mas a conferência final encontrou problema (veja o relatório) |
| 3 | a pasta escolhida já tem arquivos de outro programa (ou do usuário), e a subpasta `Helestron` dentro dela também: nada foi copiado; use uma pasta vazia, como a padrão |
| 4 | o Helestron não fechou a tempo e continuou prendendo os arquivos do programa; feche-o e rode de novo |
| 5 | outro instalador do Helestron já estava aberto |
| 6 | Windows incompatível (32 bits, ou anterior ao Windows 10) |
| 7 | havia uma audiência sendo transcrita no Helestron: nada foi alterado, para não interromper a transcrição; rode de novo depois que ela for encerrada |
| 8 | sem permissão para gravar na pasta escolhida (por exemplo, `/D=C:\Program Files\Helestron`); use uma pasta do usuário, como a padrão |
| 9 | instalado e conferido, mas o computador não tem como abrir a janela do Helestron: falta o Microsoft Edge WebView2 Runtime (e o Edge), e o navegador padrão é o Internet Explorer; instale o WebView2 Runtime |

Para conferir a impressão digital do instalador, no PowerShell:
`Get-FileHash .\Helestron-Setup-1.0.2.exe -Algorithm SHA256`, e compare com o
arquivo `.sha256` da página de versões.

A desinstalação silenciosa é descrita em [Desinstalar](#desinstalar).

### Linha de comando (para a equipe de informática)

O `Helestron.exe` abre a janela e não escreve texto. Para a linha de comando
(diagnóstico, scripts, a automação pela skill do Claude), use o
`helestron.cmd`, que fica na pasta do programa e roda o Python que vem com
o Helestron, em modo isolado:

```bat
"%LOCALAPPDATA%\Programs\Helestron\helestron.cmd" --ajuda
"%LOCALAPPDATA%\Programs\Helestron\helestron.cmd" --version
"%LOCALAPPDATA%\Programs\Helestron\helestron.cmd" verificar
"%LOCALAPPDATA%\Programs\Helestron\helestron.cmd" pauta importar "C:\Relatorios\pauta.xlsx"
```

- **Onde está o programa.** O instalador **não mexe no PATH**. Quem chama o
  Helestron de fora o encontra pela chave `HKCU\Software\Helestron` do
  registro do Windows, que traz três valores: `Python` (o `python.exe` da
  pasta do programa), `Versao` (por exemplo, `1.0.2`) e `InstallLocation`
  (a pasta do programa, onde está o `helestron.cmd`). O `helestron.cmd`
  equivale a `"<pasta do programa>\python.exe" -I -m helestron`, e o código
  de saída dele é o do programa. A desinstalação apaga os três valores.
- `--ajuda` (ou `-h`) lista os comandos; cada comando tem a própria ajuda,
  com `-h` (por exemplo, `pauta importar -h`). `--version` (ou `--versao`)
  mostra a versão (“Helestron 1.0.2”).
- A ajuda e as mensagens de erro saem em português, e um erro de uso termina
  com o código 2, por exemplo:

  ```
  python -m helestron baixar: erro: argumento não reconhecido: --xyz
  python -m helestron pauta: erro: comando desconhecido: 'xpto' (opções: sincronizar, exportar, importar, listar, fontes)
  ```
- `caminhos` (ou `caminhos --json`, para programas) mostra onde ficam o
  acervo, os processos, as transcrições, os sigilosos, a pauta exportada, a
  configuração e os registros, o modo de entrada em cada portal e o que esta
  versão oferece. Não cria nada, nem mesmo o `config.ini`, e não mostra
  senhas, perfis do navegador nem sessões.
- `pauta importar` e `pauta sincronizar` aplicam o sigilo na hora, como a
  janela: se a pauta mostrar em segredo de justiça um processo que tem
  arquivos no acervo, a saída diz “Segredo de justiça: a pauta indica que o
  processo … corre em segredo de justiça, e ele tinha arquivos no acervo.
  Preparando o acervo...” e, depois, o que saiu (veja [Segredo de justiça na
  pauta](#segredo-de-justiça-na-pauta)). Isso vale também quando o comando é
  interrompido (Ctrl+C) ou falha no meio.
- `pauta listar` mostra as partes e as observações dos processos em segredo
  de justiça como “(segredo de justiça)”, também na saída em JSON (`--json`),
  e a busca não procura nesses campos deles; só `--incluir-partes-sigilosos`
  os mostra. `pauta fontes --adicionar` com tribunal ou sistema que não
  existe sai com o código 2; `pauta fontes --remover` de uma fonte que não
  existe sai com o código 1.
- `transcrever ARQUIVO --processo NÚMERO` transcreve uma gravação. O número
  aceita o dependente como `/01` ou `-01`. `--destino` pode ser o arquivo
  `.docx` (sem a extensão, ela é acrescentada) ou uma pasta, onde o
  documento vai com o número do processo no nome; se não der para gravar no
  destino, o documento vai para a pasta das transcrições, e a saída diz
  onde ficou. Um destino dentro do acervo é recusado para processo sigiloso.

**Baixar processos pela linha de comando.** O `baixar` usa o mesmo motor e
os mesmos ajustes da tela Processos:

```bat
"%LOCALAPPDATA%\Programs\Helestron\helestron.cmd" baixar --lista "C:\Relacoes\semana.xlsx"
"%LOCALAPPDATA%\Programs\Helestron\helestron.cmd" baixar 0700123-83.2024.8.02.0001 --destino "D:\Lotes\Semana 41"
```

| Opção | O que faz |
|---|---|
| `--lista ARQ` (ou os números na própria linha) | a relação: planilha, documento, PDF, CSV, texto ou link compartilhado |
| `--destino PASTA` | a pasta do lote (padrão: `Acervo\Processos\<nome da relação>`) |
| `--completar J.TR.OOOO` | completa os números curtos (`0700123-83.2024`) com segmento, tribunal e foro, por exemplo `--completar 8.02.0001`; o argumento que não vira número aparece como “ignorado”, com o motivo |
| `--login senha`, `certificado` ou `manual` | o modo de entrada nos portais (padrão: o dos Ajustes) |
| `--sem-cofre` | não usa as senhas guardadas: no modo **Usuário e senha**, o navegador abre na tela de entrada, e você entra |
| `--visivel` | mostra a janela do navegador |
| `--rebaixar` | baixa de novo o que já está na pasta |
| `--rebaixar-incompletos` | baixa de novo só o que tem folhas (ou documentos) ausentes, ou o PDF de versão anterior, sem o manifesto de paginação |
| `--midias` | baixa também as gravações de audiência |
| `--texto` | ao fim, extrai o texto de cada PDF, com a marca de cada página (em `_texto`, ao lado dos PDFs; dentro do acervo, em `_ia\texto`) |
| `--retomar` | refaz só o que o relatório da pasta do lote diz que pede nova tentativa (falhou, ficou pendente ou foi interrompido) e os números que ainda não estão nele; com `--destino`, dispensa a relação |
| `--esperar-navegador MIN` | se outro download estiver usando o navegador do portal, espera até MIN minutos (tentando a cada 30 segundos), em vez de desistir |
| `--json ARQ` | grava o andamento e o resultado num arquivo JSON, para programas |
| `--eventos` | imprime cada acontecimento (o login que espera você, o fim…) numa linha `HELESTRON-EVENTO {…}` |
| `--log ARQ` | guarda num arquivo tudo o que sai na tela e o registro detalhado (com `--json` e sem `--log`, o registro vai para `%LOCALAPPDATA%\Helestron\Logs\execucoes`) |
| `--desanexar` | deixa o lote rodando sozinho, sem janela de console, e devolve o controle na hora (exige `--json`) |

- **Códigos de saída do `baixar`:** 0, tudo certo; 1, parte falhou ou ficou
  pendente; 2, nada pôde ser feito: nenhum processo foi baixado nem estava
  na pasta (o login recusado, por exemplo), ou o lote nem começou (relação
  ilegível ou sem números, uso errado, pasta do lote que não pode ser
  criada, outro download já usando a mesma pasta de lote).
- **O código do e-SAJ e o do eProc.** Num terminal, o código enviado por
  e-mail (e-SAJ) ou o do aplicativo autenticador (eProc) é pedido ali mesmo.
  Sem terminal (um script, a skill do Claude), a janela do navegador fica
  visível (a do eProc já abre assim), e o código é digitado nela, no campo
  do próprio portal, dentro do prazo do login. A senha e o código nunca são
  lidos de arquivo.
- **O JSON e o registro trazem os números reais** dos processos sigilosos:
  por isso, o Helestron recusa gravá-los dentro do acervo (sai com o código
  2).
- **Sigilosos de um lote fora de `Processos`.** O lote baixado em outra
  pasta (`--destino`) põe os processos em segredo de justiça em
  `Sigilosos\<nome da pasta> (<código>)`, em que o código, de oito
  caracteres, vem do caminho do lote: dois lotes de mesmo nome em pastas
  diferentes não se misturam. O lote de `Acervo\Processos` continua usando
  `Sigilosos\<nome do lote>`.
- **Preparar o acervo:** `preparar` faz o mesmo que o botão **Preparar
  acervo para a IA** (`--sem-texto` pula o texto dos autos; `--json`, para
  programas). Sai com 0 (tudo certo), 1 (algum arquivo com problema), 2
  (uso errado) ou 3 (autos de processo sigiloso presos no acervo: não
  compartilhe o acervo até movê-los). `preparar --pasta PASTA` só extrai o
  texto dos autos de uma pasta de lote (em `_texto`, dentro dela, ou na
  pasta indicada em `--texto-em`), sem mexer no `CLAUDE.md`, no
  `AGENTS.md`, no `INDICE.md` nem em `Produtos`.

O guia técnico de como uma skill do Claude Code chama o Helestron está em
`docs/INTEGRACAO-CLAUDE.md`, no repositório do programa.

---

## Primeiro uso

Abra o Helestron pelo atalho **Helestron**, na Área de Trabalho ou no Menu
Iniciar. Se ele já estiver aberto, o atalho só traz a janela para a frente.

A tela **Início** mostra a saudação, os quatro cartões das funções e, à
direita, os **Primeiros passos**: uma lista de verificação com o que ainda
falta configurar (o acesso aos portais, as pastas, o modelo de transcrição e
a pauta de audiências). Cada item pendente tem um botão que leva direto ao
lugar certo (**Resolver** ou, na pauta, **Configurar**); o que já está em
ordem aparece marcado, e o quadro sai da tela quando tudo estiver feito. A
pauta só conta como configurada depois que você cadastra uma fonte,
sincroniza ou importa um relatório: abrir a tela da Pauta não basta.

O quadro **Hoje na pauta**, no Início, mostra as audiências do dia (um
clique abre Audiências com o número, o tipo e o sigilo já preenchidos).
Sem audiências, ele diz o que falta: “A pauta ainda não foi configurada”
(com o botão **Configurar a pauta**), “A pauta ainda não foi sincronizada”
(a fonte está cadastrada, mas ainda não foi sincronizada) ou “Nenhuma
audiência hoje”, com a próxima.

Nos **Ajustes**, as opções valem na hora, sem botão para salvar: ao lado do
campo alterado aparece **Salvo**. O que o programa recusa (por exemplo, uma pasta
que poria os processos sigilosos ao alcance da IA) volta ao valor anterior, e
a explicação aparece numa janela.

> No índice à esquerda dos Ajustes, alguns grupos têm nome curto:
> **Acessos** abre **Acessos aos portais**, e **Diagnóstico** abre **Sobre e
> diagnóstico**.

### Acessos aos portais

Em **Ajustes › Acessos aos portais**:

1. Clique em **Adicionar acesso**.
2. Escolha o **Portal** (por exemplo, `TJAL · e-SAJ` ou `TJAL · eProc`).
3. Preencha o usuário (**CPF ou usuário**, no e-SAJ; **Usuário (CPF ou
   sigla)**, no eProc) e a **Senha**.
4. Deixe ligado **Lembrar neste computador**: a senha fica cifrada pelo
   Windows (DPAPI) e só a sua conta, neste computador, consegue lê-la.
   Desligado, a senha vale só até fechar o Helestron: serve para baixar
   processos e para sincronizar ou capturar a pauta, mas não para o
   monitoramento automático, que só usa a senha guardada.
5. Clique em **Salvar**.

Cada portal aparece na lista com a situação da senha (“Senha guardada”,
“Senha só até fechar o Helestron” ou “Sem senha guardada”) e, ao lado, os
botões **Testar** (quando há senha) e **Alterar** (ou **Cadastrar**, se o
acesso ainda não foi cadastrado). **Testar** entra exatamente no portal
daquela linha (no TJAL, no TJSP e no TJAC, o e-SAJ e o eProc são testados
cada um no seu botão) e mostra o resultado na própria linha: “Testando o
acesso…”, “Acesso confirmado às 14:32.” ou “O teste falhou.”, com o motivo.
Para trocar a senha, clique em **Alterar**; para apagar o acesso, clique em
**Alterar** e, na janela que se abre, em **Apagar**.

Depois de entrar num portal, o Helestron guarda a sessão por até 12 horas,
para não pedir o login a cada lote: só os cookies dos portais dos
tribunais, cifrados pelo Windows para a sua conta. **Apagar** o acesso, ou
trocar o usuário de um portal, apaga também a sessão guardada e o perfil do
navegador daquele portal. Se o arquivo das senhas se estragar (um
desligamento no meio da gravação, por exemplo), o Helestron o guarda como
`credenciais.json.ilegivel-<data>`, em `%LOCALAPPDATA%\Helestron` (é esse
arquivo que se envia ao suporte), e as senhas precisam ser cadastradas de
novo.

Logo abaixo, o grupo **Como entrar** define o modo de entrada em cada
sistema:

- **Como entrar no e-SAJ**: **Usuário e senha**, **Certificado digital**
  (a janela do navegador abre e você digita o PIN do token) ou
  **Entrar manualmente** (o navegador abre na tela de entrada do portal; você
  entra como de costume, e o Helestron continua sozinho depois). Para o
  certificado, o navegador do Helestron precisa da extensão **Web Signer**:
  ele copia do seu Google Chrome **só essa extensão** (nada das suas
  senhas, cookies, histórico ou outras extensões) e, se ela não estiver no
  Chrome, a janela explica como instalá-la pela Chrome Web Store. A cópia
  do perfil inteiro do Chrome feita pelas versões anteriores é apagada
  sozinha;
- **Como entrar no eProc**: **Usuário e senha** ou **Entrar manualmente**;
- **Esperar o login até (minutos)**: quanto tempo o Helestron espera você
  concluir a entrada (código por e-mail, certificado);
- **Perfil do eProc**: o perfil a escolher depois da entrada, quando você tem
  mais de um (por exemplo, MAGISTRADO). Em branco, o Helestron pergunta.

> A pauta monitorada automaticamente só consegue entrar no portal sozinha com
> **Usuário e senha** e com a senha **guardada** (veja
> [Monitoramento automático](#monitoramento-automático)).

### Pastas

Em **Ajustes › Pastas**, confira:

- **Pasta do acervo**: processos e transcrições que o Helestron compartilha
  com a IA;
- **Pasta dos processos sigilosos**: processos em segredo de justiça; fica
  fora do acervo e nunca vai para a IA;
- **Pasta da pauta exportada**: as planilhas da pauta, também fora do acervo,
  porque trazem as partes dos processos sigilosos.

O padrão é `Documentos\Helestron\Acervo`, `Documentos\Helestron\Sigilosos` e
`Documentos\Helestron\Pauta`. Para trocar, clique em **Alterar…**. O grupo
**Atalhos** abre, com um clique, as pastas dos processos baixados, das
transcrições, da pauta exportada e dos registros do programa.

> A pasta dos sigilosos tem de ficar **fora** do acervo (e o acervo, fora
> dela): tudo o que está no acervo é lido pela IA e copiado para a nuvem. O
> Helestron recusa uma escolha que quebre essa regra. Pelo mesmo motivo, a
> pasta dos sigilosos e a da pauta exportada não podem ficar dentro da
> pasta da nuvem escolhida em **Ajustes › Compartilhar** (nem ser ela, nem
> contê-la). Em branco, cada pasta volta ao padrão, que também é conferido.
> Se a pasta dos sigilosos ou a da pauta estiver no OneDrive ou no Google
> Drive, **Verificar a instalação** avisa.

### Seu nome e os dados da unidade

Em **Ajustes › Unidade**:

- **Como o Helestron chama você**: o nome que aparece na saudação do Início
  (“Boa tarde, …”);
- **Magistrado(a)**, **Cargo**, **Vara**, **Comarca** e **Tribunal**: vão no
  cabeçalho das transcrições. O **Tribunal** (sigla, como TJAL) também é o
  sugerido quando você escolhe o portal da pauta.

### Como a janela conversa com você

- **Perguntas.** Quando um portal pede o código de verificação (enviado por
  e-mail, no e-SAJ, ou gerado no aplicativo autenticador, no eProc), uma
  janela aparece no meio da tela, com um campo grande. Digite o código: com
  seis dígitos, ele é enviado sozinho. Se o código por e-mail não chegar, use
  **Pedir novo código**. A janela mostra o prazo (“Responda em até 4:59”,
  por exemplo). Se o Helestron estiver minimizado ou atrás de outro
  programa, a janela dele volta para a frente e pisca na barra de tarefas,
  para o pedido não passar despercebido. No Edge em modo aplicativo ou no
  navegador, o título da janela alterna com “Código pedido — Helestron” até
  você responder.
- **Avisos.** Os avisos (um lote que terminou, uma planilha pronta) aparecem
  no canto superior direito, logo abaixo dos botões da tela, sem cobri-los,
  às vezes com um botão, como **Abrir pasta**. A mesma mensagem não aparece
  repetida, e ficam no máximo três à vista.
- **Tamanho.** A janela abre com 1280 × 820 pontos. Numa tela menor (um
  notebook de 1366 × 768, ou uma tela Full HD com a escala do Windows em
  150 %), ela abre maximizada, e nada fica escondido atrás da barra de
  tarefas.
- **Fechar.** Se você fechar a janela com trabalho em andamento, o Helestron
  pergunta antes (**Fechar mesmo assim** ou **Continuar**). Ao fechar, a
  transcrição de uma audiência em curso é salva antes.
- **Sem conexão.** Se a faixa “Sem conexão com o Helestron. Tentando de novo…”
  aparecer, a janela perdeu contato com o programa por um instante; ela
  volta sozinha.

---

## 1. Baixar processos

### Passo a passo

1. Abra **Processos** (ou clique em **Baixar processos**, no Início).
2. **Traga a relação**, de um destes jeitos:
   - **arraste** o arquivo para a área “Arraste a relação de processos para
     cá” (planilha do Excel, documento do Word, PDF, CSV ou texto, inclusive
     o “.xls” exportado pelo SAJ e pelo eProc);
   - clique em **Escolher arquivo**;
   - clique em **Colar lista** e cole os números, um ou vários por linha (do
     Excel, do e-mail ou do SAJ; o que não for número de processo é
     ignorado). Também dá para teclar **Ctrl+V** direto na tela;
   - clique em **Link** e cole o link de uma planilha ou documento do Google
     Planilhas, Google Docs, Google Drive, OneDrive ou SharePoint,
     compartilhado como “qualquer pessoa com o link”.

   As planilhas `.xlsx` geradas por outros sistemas (relatórios exportados
   pelo próprio SAJ, por exemplo) são lidas inteiras, mesmo quando o arquivo
   declara um tamanho menor que o real. Duas exceções têm mensagem própria:
   a pasta de trabalho binária do Excel (`.xlsb`), que o Helestron não lê
   (no Excel, use **Salvar como › Pasta de Trabalho do Excel (.xlsx)**, ou
   CSV, e escolha de novo), e a planilha protegida por **senha de
   abertura** (tire a senha no Excel, em **Arquivo › Informações ›
   Proteger pasta de trabalho › Criptografar com senha**, salve e escolha de
   novo).
3. **Confira a revisão.** A tabela mostra cada processo reconhecido, com o
   **tribunal** e o **sistema** (eles saem do próprio número). À parte
   aparecem os avisos, os **Números que o Excel corrompeu** (formate a
   coluna como Texto, digite-os de novo e salve) e os números **Fora do
   alcance do Helestron** (tribunal ou sistema que ele não atende). O número
   de processo gravado como **número**, e não como texto, numa célula do
   Excel perde os últimos algarismos (o Excel guarda só 15) e nunca entra no
   lote, mesmo que o dígito verificador pareça conferir: ele aparece entre
   os corrompidos. Para tirar um processo do lote, clique no **×** da linha;
   para desfazer, clique de novo. **Trocar a relação** recomeça.
4. **Confira as opções do lote**:
   - **Nome do lote (vira o nome da pasta)**;
   - **Separar os sigilosos** (ligado: o processo em segredo de justiça vai
     para a pasta dos sigilosos, fora do acervo da IA);
   - **Baixar de novo o que já existe** (desligado: o processo cujo PDF já
     está na pasta é pulado);
   - **Mostrar o navegador enquanto baixa** (útil para acompanhar, ou quando
     o portal pede alguma confirmação).

   Em **Acesso aos portais**, logo abaixo, aparece cada portal da relação:
   “Senha guardada” ou “Sem senha guardada: o navegador abre para você
   entrar”. Use **Cadastrar** ou **Alterar** para resolver ali mesmo.
5. Clique em **Baixar N processos** (o botão mostra quantos são).
6. **Acompanhe o andamento.** O anel mostra o progresso, e a lista
   **Processos do lote** mostra a situação de cada um:

   | Situação | O que quer dizer |
   |---|---|
   | Aguardando | ainda na fila |
   | Baixando | em curso |
   | Baixado | pronto; o ícone ao lado abre o PDF |
   | Já estava na pasta | pulado, porque o PDF já existia |
   | Sigiloso: falta a senha | o processo é sigiloso e a relação não trouxe a senha dele |
   | Não encontrado | o portal não achou o processo (número errado, ou processo de outro sistema) |
   | Sem acesso | o portal recusou o acesso (senha, perfil ou permissão) |
   | Tribunal não suportado | tribunal ou sistema que o Helestron não atende |
   | Falhou | outro problema; o detalhe aparece na linha (em telas estreitas, logo abaixo da situação) |
   | Interrompido | o lote foi parado antes |

   **Parar** interrompe depois do processo atual. No fim, o título resume o
   lote: **Lote concluído**, **Lote concluído com falhas** (anel âmbar) ou
   **Nenhum processo baixado** (anel vermelho). Aparecem então **Abrir
   pasta**, **Relatório**, **Tentar de novo (N)** e **Novo lote**.
   **Tentar de novo** baixa de novo só os que falharam, no mesmo lote (a
   mesma pasta), e atualiza o relatório dele: as linhas refeitas tomam o
   lugar das antigas, e as dos processos que já estavam baixados continuam
   lá.

Abaixo da área da relação, **Últimos lotes** lista os lotes já baixados, com
**Abrir** (a pasta) e o ícone do relatório.

### O que sai

Uma pasta com o nome do lote, em `Acervo\Processos\`, contendo **um PDF por
processo**, nomeado com o número (`0700123-83.2024.8.02.0001.pdf`). Na
subpasta `_controle\` ficam:

- `relatorio.csv`, o relatório do lote, que abre no Excel: a situação de
  cada processo, o número de páginas, o que não veio (coluna
  `incompleto`), o detalhe e, na última coluna, `causa`, um código curto do
  motivo do que não deu certo (por exemplo, `login`, `portal` ou
  `pdf_aberto`), para quem automatiza o programa. Se o relatório estiver
  aberto no Excel quando o lote terminar, o Helestron grava ao lado
  `relatorio (atualizado).csv`;
- `<número>_capa.txt`, a **capa** do processo, para ler sem abrir o portal
  nem o PDF: classe, assunto, juiz, partes, as marcas do processo
  (prioridade, justiça gratuita, idoso, segredo de justiça), **todas** as
  movimentações e, no e-SAJ, os incidentes, os apensos, as audiências, o
  histórico de classes, as petições diversas e as folhas do PDF (“Folhas 1
  a 245”); no eProc, como citar, o **mapa de todos os documentos** (no PDF
  montado documento a documento, com a página em que cada um começa) e a
  lista de todos os eventos. O mesmo vai em `<número>_capa.json`, para
  programas;
- `<número>_meta.json`, o registro do download (sistema, páginas, o que não
  veio): quando você roda a mesma relação de novo e o processo já está na
  pasta, a linha dele no relatório continua dizendo o que dizia.

A capa e o registro acompanham o PDF quando ele vai para a pasta dos
sigilosos.

### As páginas do PDF: folhas e eventos

O PDF reproduz a numeração do próprio sistema do tribunal, para que a
citação feita a partir dele seja a mesma do portal.

- **No e-SAJ, a página N do PDF é sempre a folha N** da Pasta Digital. Se
  uma folha não veio (a Pasta Digital não a ofereceu ao seu usuário, por
  ser de peça sigilosa, de acesso restrito ou cancelada; a peça não pôde ser
  baixada; o arquivo dela veio inválido ou com páginas a menos), o lugar
  dela é ocupado por uma **página de aviso**, uma por folha, com moldura
  vermelha, que começa por “Folha N — não disponibilizada pelo e-SAJ” e diz
  o motivo e, quando se sabe, a peça. A página de aviso **não é prova**: ela
  só marca que a folha está faltando, e a numeração das seguintes não se
  desloca. Os marcadores do PDF (o índice lateral do leitor) seguem as
  peças, e os avisos em sequência têm marcador próprio, como
  “Fls. 6-7 — não disponibilizadas pelo e-SAJ”. A coluna `incompleto` do
  relatório lista todas as folhas com aviso (“12-15, 40”).
- **No eProc, que não numera folhas**, o PDF traz os documentos na ordem
  dos eventos, **sem capa e sem página nenhuma antes ou entre eles**, e
  cada documento conserva a paginação própria, igual à do eProc. Cita-se
  “evento N, RÓTULO, p. Y” (por exemplo, “evento 1, INIC1, p. 2”): o leitor
  de PDF mostra isso na caixa do número da página (“Ev. 1 INIC1 p. 2”). O
  documento escrito no próprio eProc (despacho, decisão, certidão) não tem
  páginas e se cita “evento N, RÓTULO”. O documento que não veio e a
  gravação de áudio ou vídeo têm **uma** página de aviso no lugar, marcada
  “[NÃO INCLUÍDO]” ou “[GRAVAÇÃO — fora do PDF]” no índice lateral, que não
  é página dos autos. Os dados da capa, que antes iam nas primeiras páginas
  do PDF, estão agora na capa em `_controle\` (veja acima), com o mapa dos
  documentos e a página do PDF em que cada um começa.
- Com **Montagem do PDF no eProc** em **Download completo** (em **Ajustes ›
  Download**), o arquivo que o próprio eProc gera entra **intacto**: a
  página M do PDF é a página M desse arquivo, com os marcadores dele. Se o
  download completo falhar ou demorar, o processo é montado documento a
  documento.

O PDF leva dentro dele um registro dessa numeração (o “manifesto de
paginação”), que o acompanha para onde for e que o texto para a IA usa
(veja [Preparar o acervo](#preparar-o-acervo)). O PDF baixado por uma
versão anterior à 1.0.2 não tem esse registro, e a página dele pode não
ser a folha. Quando o relatório do lote mostra que o download antigo de um
processo do e-SAJ teve folhas ausentes ou foi montado peça a peça, o
Helestron o baixa de novo sozinho na próxima vez que a relação for
baixada; para refazer os demais, use **Baixar de novo o que já existe**
(ou, na linha de comando, `--rebaixar-incompletos`).

### Bom saber

- O que já foi baixado não é baixado de novo: pode deixar a relação crescer e
  baixar outra vez.
- Processo dependente (incidente) sai com o sufixo: `...0001-01.pdf`. O
  incidente de um processo sigiloso também é sigiloso.
- Se a relação trouxer a **senha do processo** (`número ; senha`, ou uma
  coluna “senha”), ela é usada, e a linha mostra **Senha na relação**.
- **Tribunais em transição** do e-SAJ para o eProc (TJAL, TJSP e TJAC): o
  Helestron procura primeiro no e-SAJ e, não achando, no eProc.
- No eProc, os autos são montados documento a documento, na ordem dos
  eventos, com um marcador (índice) por documento no PDF e o rótulo de cada
  página (veja [As páginas do PDF](#as-páginas-do-pdf-folhas-e-eventos)).
- **Dois downloads ao mesmo tempo.** Se um download estiver usando o
  navegador de um portal (pela janela ou pela linha de comando), outro
  download no mesmo portal não consegue abri-lo: os processos dele saem como
  **Falhou**, com o detalhe “o navegador do programa já está aberto em
  outra janela (outro download em andamento?)”; espere o primeiro terminar
  e use **Tentar de novo**. A mesma pasta de lote nunca é baixada por dois
  downloads ao mesmo tempo.
- Em **Ajustes › Download** há outras opções, como **Baixar também as
  gravações de audiência** e a **Pausa entre processos (segundos)**. Não
  zere a pausa em listas grandes: uma rajada de acessos pode ser lida pelo
  portal como abuso.
- Um lote também pode começar pela **Pauta** (“Baixar os autos”); o
  andamento aparece aqui do mesmo jeito.

### Segredo de justiça no download

Com **Separar os sigilosos** ligado (o padrão):

- o processo sigiloso vai para `Sigilosos\<nome do lote>\`, **fora** do
  acervo compartilhado com a IA. Vai para lá também o processo público que
  tenha alguma **peça sigilosa** (no e-SAJ, a peça marcada como sigilosa na
  Pasta Digital), porque o PDF a traz inteira;
- o relatório do lote que fica no acervo **não identifica** os sigilosos: no
  lugar do número, a linha diz “(processo sigiloso)”. O relatório completo,
  com os números, fica em `Sigilosos\<nome do lote>\_controle\relatorio.csv`.
  Vale também para o processo que se revela sigiloso depois do download:
  quando o Helestron o leva para a pasta dos sigilosos, a linha dele no
  relatório do acervo passa a dizer “(processo sigiloso)”, e a linha
  completa vai para o relatório do lote na pasta dos sigilosos;
- a transcrição de audiência que já estava no acervo quando o download
  descobriu o sigilo é levada para `Sigilosos\Transcricoes`, com a gravação.
  Se ela não puder sair (aberta no Word, ou a audiência sendo gravada
  agora), o processo **não** é dado como falha: a linha dele mostra
  “atenção: …”, com o arquivo e o que fazer, e o lote avisa **Arquivo de
  processo sigiloso no acervo** (veja [Regras de sigilo](#regras-de-sigilo));
- o processo que o Helestron **já sabe sigiloso** (os autos, uma transcrição
  ou uma gravação dele na pasta dos sigilosos, ou a pauta de audiências
  indicando segredo de justiça) vai para a pasta dos sigilosos mesmo que a
  página do portal não mostre o selo, e o mesmo vale para os incidentes dele
  (`...0001-01`); e o que um lote já deu como sigiloso continua sigiloso
  quando você usa **Tentar de novo**.

A regra completa está em [Segredo de justiça](#segredo-de-justiça).

---

## 2. Transcrever audiência

A transcrição roda **no próprio computador, sem internet**: o áudio da
audiência não sai da máquina.

No alto da tela **Audiências** há dois modos, lado a lado: **Ao vivo**, para
transcrever a audiência pelo microfone enquanto ela acontece, e **Arquivo
de áudio ou vídeo**, para transcrever uma gravação que já existe (veja
[Transcrever uma gravação](#transcrever-uma-gravação)). O Helestron lembra
o último modo usado.

### Antes de começar

No modo **Ao vivo**, no cartão **Nova audiência**:

1. **Número do processo**: é ele que dá nome ao documento. O Helestron
   confere o dígito verificador (“Número válido · TJAL”, ou “O dígito
   verificador não confere”). O processo dependente (incidente) pode ser
   digitado com o sufixo, como `/01` ou `-01`, e o documento sai com ele
   (`...0001-01.docx`). Se houver audiências de hoje na pauta, elas
   aparecem logo abaixo (“Hoje na pauta:”): um clique preenche o número e o
   tipo e, se a audiência for sigilosa, liga o **Segredo de justiça**.
2. **Tipo de audiência**: Conciliação, Instrução e julgamento, Una,
   Custódia, Justificação, Mediação ou Outra.
3. **Segredo de justiça**: ligue para processo sigiloso. Se a pauta de
   audiências indicar que o processo corre em segredo de justiça, o
   Helestron liga o interruptor sozinho e diz por quê (veja abaixo).
4. **Microfone**: escolha o microfone (ou **Padrão do Windows**) e clique em
   **Testar**; fale algo, e as barras do medidor devem se mexer. Clique em
   **Parar teste** quando terminar. Enquanto a lista mostra “Carregando os
   microfones…”, **Gravar** e **Testar** ficam desativados por um instante.
   A escolha fica guardada pelo **nome** do microfone, e não pela posição na
   lista: ligar o fone USB em outra porta não troca o microfone. Se o
   microfone guardado não estiver ligado, ele aparece na lista como “Não
   encontrado: …”, seguido do nome dele, com o aviso em vermelho “O
   microfone ‘…’ não foi encontrado neste computador. Ligue-o ou escolha
   outro.”, e o Helestron não grava por outro aparelho sem avisar: ligue-o
   ou escolha outro.
5. **Participantes**: os nomes dos botões de quem está falando, um para cada
   tecla de **F1 a F8**. O padrão é Juiz(a), Promotor(a), Defensor(a),
   Advogado(a) do autor, Advogado(a) do réu, Testemunha, Parte e Outro.
   Edite à vontade: os nomes ficam guardados para as próximas audiências.

Abaixo do botão de gravar, o Helestron diz se o modelo de transcrição está
pronto (“Modelo … pronto”).

### Durante a audiência

1. Clique no **botão vermelho grande** (**Gravar**) ou tecle **Ctrl+Enter**.
2. O texto aparece poucos segundos depois de cada fala, com o horário e o
   nome de quem falou.
3. Indique **quem está falando** com os botões ou com as teclas **F1 a F8**.
4. **Pausar** suspende a gravação (num intervalo, por exemplo): pausada,
   nada é captado, e o “Ouvindo…” some da tela. **Retomar** continua.
5. Se você subir o texto para reler um trecho, a rolagem automática fica
   suspensa; o botão **Ir para o fim** volta ao ponto atual.
6. Para terminar, clique em **Encerrar** e confirme em **Encerrar e salvar**.
   O que ainda estiver na fila é transcrito antes de salvar.

No alto da tela ficam o cronômetro e a situação (**Gravando**, **Pausado**).
Se o computador ficar para trás, aparece “Atraso de N s”: nada se perde, o
áudio está gravado e a fila é transcrita. No rodapé, “Salvo automaticamente
às …” mostra o último salvamento. Se o microfone escolhido deixar de abrir
no meio da audiência (desligado, ou tomado por outro programa) e outro
aparelho continuar a gravação, o Helestron avisa na hora (“O microfone ‘…’
não abriu (desligado, ou em uso por outro programa); a gravação segue pelo
‘…’. Confira o microfone em Audiências.”): confira o microfone.

Se a gravação nem chegar a começar (sem microfone, por exemplo), aparece a
janela **A gravação não começou**, com o motivo, e a tela volta à
preparação. Se a audiência cair no meio, a janela é **A audiência foi
interrompida**: o áudio gravado até ali fica guardado, e o botão
**Recuperar**, na faixa “Uma transcrição foi interrompida”, gera o
documento (veja [Recuperar uma transcrição
interrompida](#recuperar-uma-transcrição-interrompida)).

Você pode sair da tela de Audiências durante a gravação: ela continua, e uma
bolinha vermelha em **Audiências**, na barra lateral, indica que a audiência
está sendo gravada. Ao voltar, o texto e o tempo estão lá.

### Depois: o documento

Ao encerrar, aparece **Transcrição salva**, com **Abrir documento**, **Abrir
pasta** e **Nova audiência**.

**O que sai:** `Acervo\Transcricoes\<número do processo>.docx`, com a ficha
da audiência (processo, data, horário, unidade, participantes), cada fala com
o falante e a hora `[hh:mm:ss]`, e o aviso de que a transcrição é
automática. Em **Participantes**, a ficha lista quem de fato falou, na ordem
em que apareceu (com o nome informado para o papel, quando houver), e depois
os demais participantes informados; os papéis dos botões que ninguém usou
não entram. A gravação fica em `Transcricoes\_audio`, para conferência. Se já
houver uma transcrição do mesmo processo, a nova sai como
`<número> (2).docx`: nada é sobrescrito.

As propriedades do arquivo (no Word, **Arquivo › Informações**; no
Explorador de Arquivos, **Propriedades › Detalhes**) são do próprio
documento: o autor e o “modificado por” são **Helestron**, o título é
“Transcrição de audiência — Processo nº …”, as palavras-chave trazem o
número do processo, as datas de criação e de modificação são as do momento
em que ele foi gerado, e o programa indicado é o Helestron. Nenhum dado
herdado de outro programa aparece ali, o que importa num documento que pode
ir aos autos.

**Revisar com o modelo preciso**: o botão **Revisar** refaz o texto inteiro
com um modelo maior e mais preciso, a partir da gravação e dos falantes que
você marcou; a ficha mantém a data, o início e o término, o tipo de
audiência e os participantes da audiência ao vivo. Leva
alguns minutos; acompanhe ali mesmo ou na barra lateral. No fim, o botão vira
**Abrir a revisão**. Para que a revisão aconteça sempre ao encerrar, ligue
**Revisar ao encerrar a audiência** em **Ajustes › Transcrição**; com
**Separar as vozes na revisão** ligado, ela também separa os falantes
automaticamente. A revisão feita ao encerrar toma o lugar do documento, e a
versão ao vivo fica guardada em `_audio`; se o documento estiver aberto no
Word nessa hora, a revisada é gravada ao lado, com “(revisada)” no nome, e
um aviso diz onde ela está.

> A transcrição é automática: confira o texto antes de usá-lo em qualquer
> ato, especialmente nas passagens decisivas, com a gravação.

### Segredo de justiça na transcrição

Com **Segredo de justiça** ligado, a transcrição e a gravação vão para
`Sigilosos\Transcricoes` (e `Sigilosos\Transcricoes\_audio`), **fora** do
acervo compartilhado com a IA.

O Helestron também grava como sigilosa, mesmo com o interruptor desligado, a
audiência de um processo que ele já sabe ser sigiloso:

- os autos do processo estão na pasta dos sigilosos, ou uma transcrição ou
  gravação anterior dele já foi para lá;
- a pauta de audiências indica segredo de justiça em alguma audiência desse
  processo (vinda do portal ou de um relatório importado);
- o processo é **incidente** (`...0001-01`) de um processo que se enquadra
  num dos casos acima: a tela diz “Este processo é incidente de um processo
  sigiloso: …”.

É a regra única do Helestron, descrita em [Segredo de
justiça](#segredo-de-justiça). Nesses casos, o interruptor se liga sozinho
(pela pauta, logo que o número é digitado; nos outros casos, ao começar a
gravação), e a tela mostra o motivo (por exemplo, “A pauta de audiências
indica que este processo corre em segredo de justiça.”). O Helestron nunca
desliga o sigilo que você ligou; o que ele ligou sozinho volta a ficar
desligado se você trocar o número do processo.

### Transcrever uma gravação

Para transcrever uma gravação já existente (a mídia baixada com os autos,
ou qualquer arquivo de áudio ou vídeo da audiência), escolha o modo
**Arquivo de áudio ou vídeo**, no alto da tela **Audiências**. No cartão
**Transcrever uma gravação**:

1. **Traga a gravação**: arraste o arquivo para a área “Arraste a gravação
   para cá” ou clique em **Escolher arquivo**. Soltar uma gravação em
   qualquer ponto da tela, mesmo no modo **Ao vivo**, também serve (o
   Helestron passa ao modo de arquivo); uma pasta não é aceita. O cartão
   mostra o nome e o tamanho do arquivo; escolhido pelo botão, na janela do
   Helestron, mostra também a pasta, com a indicação de que ele é “lido de
   onde está, sem cópia”. **Trocar** escolhe outro, e o **×** o tira.
2. Confira o **Número do processo**: o Helestron o lê do nome do arquivo ou,
   se não estiver ali, do nome da pasta, mantendo o dependente (`-01`).
3. Escolha o **Tipo de audiência** e confira o **Segredo de justiça**, que
   se liga sozinho quando a pauta indica o sigilo (também para o incidente
   de um processo sigiloso).
4. Clique em **Transcrever** (ou tecle **Ctrl+Enter**). Se o botão estiver
   desligado, a frase logo ao lado diz o que falta.

Os formatos aceitos são os de áudio e vídeo que o Windows reproduz: MP3,
WAV, WMA, M4A, AAC, FLAC, OGG, OPUS, MP4, WMV, AVI, MKV, MOV, MPG, WebM,
3GP, TS e outros. O arquivo não é recusado pela extensão: o que diz se ele
serve é a leitura do som, e o Helestron explica, com uma frase própria,
quando o vídeo não tem trilha de áudio, quando o arquivo está cortado ou
danificado (ou não é uma gravação) e quando ele é protegido contra cópia
(DRM).

Escolhido pelo botão, na janela do Helestron, o arquivo é lido de onde
está, sem limite de tamanho. Arrastado para a tela (ou escolhido no Edge
ou no navegador), ele é **enviado** ao programa: o cartão mostra o
andamento do envio, em porcentagem, com **Cancelar envio**, e o envio
continua se você sair da tela e voltar. O envio aceita até **20 GB** (acima
disso, use o botão **Escolher arquivo**, na janela do Helestron), e o
Helestron confere antes se há espaço livre no disco (com 512 MB de folga);
sem espaço, ele diz o tamanho do arquivo e o espaço livre e sugere o mesmo
botão, que não copia nada.

Uma gravação é transcrita de cada vez: enquanto uma está em andamento,
**Transcrever** e **Trocar** ficam desligados. No fim, o cartão mostra
**Abrir documento** e **Abrir pasta**, ou o motivo da falha, em vermelho;
com o documento pronto, a gravação e o número saem da tela.

O sigilo segue as mesmas regras da audiência ao vivo e vale também quando a
gravação escolhida está na pasta dos sigilosos. O nome e a data do arquivo
de áudio vão para a ficha do documento. A transcrição usa o modelo preciso
e pode levar alguns minutos; acompanhe no cartão ou na barra lateral.

### Recuperar uma transcrição interrompida

O documento é salvo sozinho a cada poucos segundos. Se o computador desligar
ou o programa fechar no meio, ao abrir **Audiências** de novo aparece o aviso
“Uma transcrição foi interrompida”, com o botão **Recuperar**: o que já tinha
sido transcrito volta para o documento, e a gravação é reparada. Como no fim
de uma audiência, o índice do acervo é atualizado e, se o espelho automático
estiver ligado, a cópia na nuvem também.

As **Transcrições recentes** ficam na lateral da tela; um clique abre o
documento.

### Bom saber

- Computador lento? Em **Ajustes › Transcrição**, escolha o modelo **Base**
  em **Modelo da transcrição ao vivo**, ou feche programas pesados durante a
  audiência.
- O modelo **Small** vem com o instalador e basta para a transcrição ao
  vivo. Os maiores (para a revisão e as gravações) aparecem em **Modelos de
  transcrição**, em **Ajustes › Transcrição**, com o botão **Baixar** (exige
  internet, uma única vez).
- Em **Ajustes › Transcrição** também ficam o **Microfone** (a mesma escolha
  da tela Audiências, guardada pelo nome), **Participantes padrão**,
  **Vocabulário da transcrição** (mantenha o texto acentuado: o modelo imita
  a grafia dele) e **Guardar a gravação da audiência**. Mesmo com esta
  última desligada, a gravação é guardada quando algum trecho de fala não
  pôde ser transcrito (ou o modelo de transcrição não carregou): um aviso
  diz isso, com o caminho do arquivo, e a ficha do documento aponta a
  gravação. Transcreva-a pela opção **Transcrever uma gravação** e, depois,
  apague-a, se quiser.
- A **Separação de falantes** (no fim de **Ajustes › Transcrição**) mostra se
  a separação automática das vozes, usada na revisão, está **Pronta**. Os
  modelos de voz vêm com o instalador; se faltarem, o botão **Baixar os
  modelos de voz** os baixa uma vez (exige internet). Sem eles, a revisão não
  separa as vozes sozinha, mas os falantes marcados durante a audiência
  continuam valendo.

---

## 3. Pauta de audiências

A tela **Pauta** reúne as audiências do e-SAJ e do eProc, mostra o que mudou
e exporta tudo para o Excel.

### De onde vem a pauta: as fontes

Cada **fonte** é um portal: o e-SAJ ou o eProc de um tribunal. Há três jeitos
de trazer a pauta:

| Jeito | Quando usar |
|---|---|
| **Sincronizar** | o Helestron entra no portal com o seu acesso, procura a pauta de audiências e a traz sozinho |
| **Capturar no portal** | quando a sincronização não acha a pauta, ou o tribunal tem tela própria: você mostra a pauta, o Helestron lê |
| **Importar relatório** | quando você já tem o relatório de audiências exportado do SAJ ou do eProc |

Antes de tudo, cadastre o acesso ao portal em **Ajustes › Acessos aos
portais** (veja [Primeiro uso](#acessos-aos-portais)).

### Sincronizar

1. Na **Pauta**, clique em **Sincronizar**.
2. Na primeira vez, a janela **De onde vem a sua pauta?** pede o **Portal**
   (tribunal e sistema) e, se quiser, um **Nome para reconhecer (opcional)**,
   como “2ª Vara Cível da Capital”. Clique em **Sincronizar**.
3. O Helestron entra no portal e procura a pauta de audiências. Se o portal
   pedir código, a janela de sempre pede que você o digite. Uma faixa no alto
   da tela mostra o andamento, com **Parar**.
4. No fim, uma faixa que fica à vista até você fechá-la resume o que mudou,
   por exemplo: “8 audiências conferidas · 1 nova, 2 alteradas, 1 saiu da
   pauta.”, com as fontes que tiveram problema e os avisos. (Se você estiver
   em outra tela, o resultado chega num aviso.)

O endereço da pauta que funcionou fica **lembrado** na fonte e é usado nas
próximas vezes e pelo monitoramento. Para acrescentar outro portal (o eProc
do mesmo tribunal, por exemplo), use **Ajustes › Pauta › Adicionar fonte**.
**Sincronizar** confere todas as fontes de uma vez; se uma falhar, as outras
seguem. A senha digitada com **Lembrar neste computador** desligado também
vale aqui, até você fechar o Helestron.

**Nada sai da pauta por engano.** Uma audiência só é marcada como **Saiu da
pauta** quando o Helestron leu a pauta do portal inteira. Se a leitura ficar
incompleta (a página seguinte não abriu a tempo ou não mostrou a tabela, o
portal voltou a uma página já lida, a pauta passou de 50 páginas, ou o
portal informou mais audiências do que vieram), o resultado avisa que a
leitura “ficou incompleta” e que “nenhuma audiência foi dada como fora da
pauta”: as novas e as alteradas são gravadas, e nenhuma é dada como
removida. Sincronize de novo mais tarde (ou escolha um período menor). Se a
sessão cair no meio da leitura, o Helestron entra de novo e relê tudo. E, se
o portal não aceitar o período pedido (ou mostrar outro), só as datas que
vieram na tela são conferidas, e o resultado também avisa.

### Capturar no portal (a barra do Helestron)

Para quando a sincronização não acha a pauta, ou o tribunal mostra a pauta
numa tela própria:

1. Clique em **Capturar no portal** (no quadro **Mais ações**, à direita).
2. Escolha o **Portal** e clique em **Abrir o portal**.
3. O portal abre no navegador, **já com o seu acesso**. No topo da página
   aparece uma barra discreta:

   > **H** Helestron — vá até a pauta de audiências e clique em
   > **Capturar esta tela**. · [Capturar esta tela] [Concluir] [–]

4. Navegue até a pauta de audiências, como faria normalmente, com a lista na
   tela, e clique em **Capturar esta tela**. A barra diz quantas audiências
   reconheceu (“12 audiências reconhecidas nesta tela. Total: 12. …”).
5. Se a pauta tiver mais de uma página, vá à próxima e capture de novo. As
   repetidas não contam duas vezes.
6. No fim, clique em **Concluir**. A barra confirma (“Pronto: 25 audiências
   gravadas no Helestron. Pode fechar esta janela.”), e o endereço fica
   lembrado para o monitoramento. Na tela Pauta, a faixa **Captura
   concluída** diz quantas audiências vieram e de quantas telas, com “O
   endereço ficou lembrado: a fonte entra no monitoramento automático.” (se
   a entrada nesse portal exigir você à frente, a faixa diz que o
   monitoramento não entra sozinho nele).

Se a barra disser “Não encontrei a tabela de audiências nesta tela”, abra a
pauta com a lista à vista e clique de novo. O botão **–** recolhe a barra,
se ela atrapalhar. Para desistir, use **Cancelar a captura**, na faixa do
alto da tela Pauta. Sem **Concluir**, o que já foi capturado é gravado quando
você fecha o navegador ou depois de meia hora.

### Importar relatório do SAJ ou do eProc

Se você exporta o relatório de audiências no portal (ou no SAJ instalado no
computador), clique em **Importar relatório** e escolha o arquivo. O
Helestron lê:

- planilhas `.xlsx`, `.xls` (inclusive o “.xls” que, na verdade, é uma página
  HTML), `.ods` e `.csv`;
- páginas `.html`;
- `.pdf` (a tabela é lida pelo texto da página);
- `.docx`.

O relatório pode vir como o sistema o gera: com título, vara, período e a
data de emissão no alto (o cabeçalho das colunas é procurado nas primeiras
15 linhas), com o cabeçalho em duas linhas, com células mescladas (a data
escrita uma vez para todas as audiências do dia, inclusive nas planilhas
`.xlsx`, `.xls` e `.ods`) e com linhas de grupo por dia (“Segunda-feira,
05/10/2026”, com ou sem a contagem ao lado). Tabelas que não são de
audiências (intimações, prazos, movimentações, fila de processos) são
deixadas de lado.

No fim, aparece **Relatório importado**, com quantas audiências são novas,
quantas foram atualizadas e quantas linhas foram ignoradas (com os avisos,
se houver). Uma audiência que já tinha vindo do portal não é duplicada: o
relatório só completa o que faltava nela. O contrário também vale: se você
importa o relatório e depois sincroniza, a audiência que o portal trouxer
(mesmo processo, data e hora) toma o lugar da importada, e o que só o
relatório sabia, como o sigilo, continua valendo.

### A tela da pauta

- **Período**: **Hoje**, **Semana**, **Mês** ou **Período** (de uma data a
  outra). As setas ao lado do período avançam e voltam.
- **Filtros**: sistema (**Todos os sistemas**, e-SAJ, eProc), situação
  (**Todas as situações**, Designada, Realizada, Cancelada, Redesignada, Não
  realizada, Suspensa) e a busca (**Buscar processo, parte ou local**).
- **Resumo**: quatro números, que também servem de filtro rápido: **no
  período**, **hoje**, **nos próximos 7 dias** (hoje e os seis dias
  seguintes, os mesmos da visão **Semana**) e **canceladas ou
  redesignadas**.
- **Lista por dia** (“Segunda-feira, 5 de outubro”), com a hora, o número do
  processo (clique nele para **copiar**), o tipo, o sistema e o tribunal, o
  selo **Sigiloso**, as partes, o local e a situação. Em cada audiência:
  - **Baixar os autos** (o ícone de documento): baixa o processo, num lote
    que aparece em Processos;
  - **Transcrever a audiência** (o microfone): abre Audiências com o número,
    o tipo e o sigilo já preenchidos;
  - **Abrir o link da audiência** (a câmera), quando a audiência é virtual.
- **Baixar os autos do período**, em **Mais ações**: um lote com todos os
  processos das audiências listadas (as canceladas ficam de fora).

### Alterações

O quadro **Alterações recentes**, à direita, mostra o que mudou desde a
última conferência: **Nova audiência**, **Audiência alterada** (com o campo
de antes e o de depois, por exemplo “Hora: 09:00 → 14:30”), **Audiência
cancelada** e **Saiu da pauta** (a audiência que sumiu do portal não é
apagada: fica marcada; e só é dada como fora da pauta depois de uma leitura
completa, veja [Sincronizar](#sincronizar)). O número de alterações não
vistas aparece num selo vermelho em **Pauta**, na barra lateral. Clique em
**Marcar como vistas** depois de conferir; **Ver todas** abre o histórico
completo.

Na primeira sincronização de uma fonte, a pauta inteira entra sem aparecer
como alteração.

A audiência **remarcada** aparece como uma alteração só, com a data e a
hora de antes e de depois, quando, na mesma sincronização, some uma
audiência que ainda ia acontecer e aparece outra do mesmo processo e do
mesmo tipo. A audiência que já passou (a conciliação realizada, que sai da
lista das designadas) e a de outro tipo (a instrução marcada na própria
conciliação) não se confundem com a remarcação: aparecem como **Saiu da
pauta** e **Nova audiência**.

### Exportar para o Excel

1. Escolha o período e, se quiser, os filtros.
2. Clique em **Exportar Excel**, confira as datas **De** e **Até** e clique
   em **Exportar**.
3. Abra a planilha pelo aviso **Planilha pronta** (**Abrir** ou **Abrir
   pasta**).

A planilha `Pauta de audiências AAAA-MM-DD a AAAA-MM-DD.xlsx` vai para a
pasta da pauta (`Documentos\Helestron\Pauta`), **fora do acervo da IA**. Se o
nome já existir (ou o arquivo estiver aberto no Excel), sai com “(2)”. Ela tem
três abas:

- **Pauta**: data, dia da semana, hora, processo, classe, partes, tipo de
  audiência, situação, local, magistrado ou conciliador, sistema, tribunal,
  link e observações, com filtro, cabeçalho fixo, as audiências de hoje
  destacadas e as canceladas riscadas, pronta para imprimir;
- **Resumo**: quantidade por dia, por tipo e por situação;
- **Alterações**: o histórico do período inteiro, com os mesmos filtros da
  aba Pauta (a linha 2 diz quais filtros foram aplicados). A audiência
  remarcada aparece também na planilha da semana da data antiga, que diz
  para quando ela foi.

**Partes e observações dos processos sigilosos**: por padrão, as colunas
Partes e Observações dos processos em segredo de justiça saem como
“(segredo de justiça)”, também na aba Alterações. Para mostrá-las, ligue
**Incluir as partes e as observações dos sigilosos** na janela de
exportação; a escolha feita ali vale para aquela planilha, nos dois
sentidos: desligado, elas saem mascaradas mesmo que o ajuste esteja
ligado. (A posição inicial desse interruptor vem de **Mostrar as partes dos
processos sigilosos na planilha**, em **Ajustes › Pauta**; o recomendado é
deixá-lo desligado.)

O sigilo é do **processo**, e não de uma linha só: vale quando o portal ou um
relatório importado indica segredo de justiça em **qualquer** audiência
daquele processo, **ou** quando os autos do processo estão na pasta dos
sigilosos. Com as partes mascaradas e algum processo sigiloso no resultado,
o texto de uma busca não é escrito no alto da planilha (aparece “busca por
texto (omitido por causa do segredo de justiça)”), porque poderia ser o nome
de uma parte. E um texto que começa com “=” (num nome de parte ou numa
observação) vai para a planilha como texto, nunca como fórmula.

### Segredo de justiça na pauta

Pela pauta, o Helestron só marca um processo como sigiloso quando ela **diz
claramente** que ele corre em segredo de justiça. A marcação tem
consequência séria (o processo sai do acervo e da IA de vez, como se vê
abaixo), por isso a dúvida não marca:

| Marca o processo como sigiloso | Não marca |
|---|---|
| o ícone “Segredo de Justiça” na linha da audiência | “Nível 1” ou “Nível 2” no **Local** (é o andar ou o bloco do fórum) |
| “(Segredo de Justiça)” no lugar das partes | “Segredo de justiça: não”, “Segredo de Justiça? NÃO”, “Sem segredo de justiça” |
| “Ação Civil Pública - Segredo de Justiça” | “Não sigiloso”, “Processo não é sigiloso”, “não corre em segredo de justiça” |
| “Processo em segredo de justiça” | “Nível 0”, “Público”, “Sigilo retirado”, “Sigilo levantado” |
| “Sigiloso” sozinho numa célula | “Pedido de segredo de justiça” (uma menção que não afirma nada) |
| “Sim”, “X” ou “Nível 1” na coluna **Sigilo** | “Oitiva de testemunha sigilosa” (o sigilo é de outra coisa) |

Cada célula vale por si: “Ministério Público” ou “Defensoria Pública” ao lado
do selo não tiram o sigilo, e o “não” de uma célula não vale para outra. A
regra é a mesma na sincronização, na captura e no relatório importado.

**Quando a pauta revela o segredo de um processo do acervo.** Se a
sincronização (inclusive a do monitoramento automático), a captura ou um
relatório importado mostrar em segredo de justiça um processo que tem
arquivos no acervo, o Helestron age **na hora**, sem esperar o próximo
compartilhamento:

- leva os autos e as transcrições dele (com as gravações) para a pasta dos
  sigilosos;
- apaga o texto dele que a IA lia (`_ia\texto`) e o tira do índice do acervo
  (`INDICE.md`);
- com **Espelhar sozinho ao fim de cada download e de cada transcrição**
  ligado, tira também a cópia dele da nuvem; sem isso, ela sai no próximo
  **Espelhar agora** (tela Compartilhar);
- mostra o aviso **Processo em segredo de justiça** (ou **Processos em
  segredo de justiça**), com o número e o que foi feito, por exemplo: “A
  pauta indica que o processo 0700123-83.2024.8.02.0001 corre em segredo de
  justiça. O Helestron está levando os autos e as transcrições dele para a
  pasta dos sigilosos, e ele sai do índice e do texto lidos pela IA e do
  espelho na nuvem.”

Com **Separar os processos sigilosos** desligado, os arquivos continuam no
acervo, mas o processo sai do índice e do texto lidos pela IA, e o aviso diz
isso. Se houver arquivo de processo sigiloso preso no acervo (veja [Regras
de sigilo](#regras-de-sigilo)), o aviso pede que você o feche primeiro: o
processo sai assim que o acervo puder ser preparado de novo.

O sigilo que a pauta indicou fica gravado, mesmo que a audiência saia da
pauta, e também num registro à parte, fora do banco da pauta
(`pauta.sigilo.json`), que continua valendo se o banco se perder ou for
refeito: veja [Se um processo foi marcado como sigiloso por
engano](#se-um-processo-foi-marcado-como-sigiloso-por-engano).

### Monitoramento automático

No quadro **Monitoramento**, o interruptor **Conferir sozinho** (“e avisar o
que mudar”), ligado por padrão, faz o Helestron sincronizar a pauta sozinho, na
**Frequência** escolhida (de “a cada hora” a “a cada 24 horas”; o padrão é a
cada 6 horas), e também ao abrir o programa, se a última conferência já
passou do intervalo. O quadro mostra a **Última sincronização** e, quando
alguma fonte entra no portal sozinha, a **Próxima**. Se nenhuma entra
sozinha (todas são “só com você” ou ainda não têm o endereço salvo), não há
conferência automática a anunciar, e a linha **Próxima** não aparece, nem
depois de uma sincronização feita por você. Logo abaixo, o quadro lista as
fontes, com “(só com você)” ou “(sem endereço salvo)” ao lado das que o
monitoramento não confere.

Para o monitoramento funcionar, é preciso:

- **o Helestron aberto**: ele confere a pauta enquanto o programa está
  aberto (pode ficar minimizado);
- **uma fonte com endereço lembrado**, o que acontece depois da primeira
  sincronização bem-sucedida ou de uma captura concluída;
- **a senha guardada** em **Ajustes › Acessos aos portais**, com
  **Lembrar neste computador** ligado e a entrada por **Usuário e senha**.

Em **Ajustes › Pauta**, cada fonte mostra se entra no monitoramento:
**Monitorada** (o endereço está lembrado, e o Helestron entra no portal
sozinho), **Sem endereço salvo** (a pauta ainda não foi encontrada:
sincronize ou capture uma vez) ou **Só com você**. Este último é o caso
da fonte que só abre com você à frente: entrada por **Certificado digital**
ou **Entrar manualmente**, ou sem a senha guardada (inclusive quando a
senha foi digitada com **Lembrar neste computador** desligado). Ela **fica de fora**
da conferência automática, e a linha da fonte diz por quê: o monitoramento
não abre o navegador sozinho, para não surgir uma janela do nada, e não
insiste a cada ciclo. O Início também mostra, uma vez a cada abertura do
programa, o aviso **Monitoramento da pauta**, que diz em que fontes o
monitoramento não entra sozinho e o que fazer: clicar em **Sincronizar**, na
tela Pauta, quando quiser atualizar; guardar o usuário e a senha em
**Ajustes › Acessos aos portais**; ou desligar **Conferir sozinho**. As
outras fontes continuam sendo conferidas normalmente.

Se o portal pedir um código de verificação durante a conferência automática,
o Helestron **não fica esperando**: aparece o aviso **“Entre no portal para
continuar o monitoramento”**, também na lista do Início. Clique em
**Sincronizar**, digite o código quando ele chegar, e o monitoramento
continua normalmente. Se houver um download em andamento, a conferência
espera 15 minutos e tenta de novo.

O período conferido vai de 7 dias para trás a 60 dias à frente; isso se
ajusta em **Ajustes › Pauta** (**Dias para trás na sincronização** e **Dias
à frente na sincronização**).

### O que esperar (limites)

- As telas de pauta do e-SAJ e do eProc **variam de tribunal para tribunal**
  e mudam com o tempo. A sincronização procura a pauta pelo menu do portal e
  reconhece a tabela pelos títulos das colunas, mas não há como garantir que
  ela ache a tela de todos os tribunais. Quando não acha, ela diz isso numa
  frase, e nada do que já estava na pauta se perde.
- As saídas garantidas são a **captura assistida** (funciona em qualquer tela
  que mostre a lista de audiências) e a **importação do relatório**.
- Em alguns tribunais, a pauta do magistrado fica só no SAJ instalado no
  computador (SAJ/PG5), e não no e-SAJ da internet. Nesse caso, exporte o
  relatório no SAJ e use **Importar relatório**.
- No eProc dos tribunais com um endereço por seção judiciária (TRF2 e TRF4),
  comece por **Capturar no portal**: o endereço fica lembrado e a
  sincronização passa a funcionar.

---

## 4. Compartilhar com IA

O acervo é uma pasta comum do computador. Na tela **Compartilhar**, o
Helestron a deixa pronta para a inteligência artificial ler **direto do
disco**, e abre cada ferramenta já dentro dela.

### Preparar o acervo

Clique em **Preparar acervo para a IA**. O Helestron:

- gera o **texto** de cada processo em `_ia\texto\`, com a marca de citação
  de cada página e o documento a que ela pertence. A IA lê texto melhor e
  mais barato que PDF e consegue indicar a fonte exatamente como o portal a
  numera (veja [As páginas do PDF](#as-páginas-do-pdf-folhas-e-eventos)):
  - no e-SAJ, `=== [fl. 12] ===`: a página 12 do PDF é a folha 12. A folha
    que não veio traz, logo abaixo da marca, a linha
    `[folha não disponível no e-SAJ: …]`, com o motivo, e nada da página de
    aviso;
  - no eProc, `=== [evento 1, INIC1, p. 2] (pág. 2 do PDF) ===`: cita-se o
    que está entre colchetes; a “pág. … do PDF” é só a posição no arquivo,
    para navegar. O documento que não veio e a gravação aparecem como
    `NÃO INCLUÍDO` e `gravação fora do PDF`;
  - a primeira linha do texto (`# helestron-texto 2 | sistema=… |
    paginacao=… | …`) diz o sistema, o tipo de paginação, o total de
    páginas e as páginas de aviso, e as linhas seguintes, entre colchetes,
    dizem como citar e, no eProc, trazem a capa e os eventos sem documento;
  - a página sem texto que se extraia (imagem digitalizada sem
    reconhecimento de texto) recebe a linha `[página sem texto extraível …]`:
    a IA sabe que precisa ver a página no PDF;
  - o PDF baixado por versão anterior à 1.0.2 só é marcado por folha quando
    os marcadores dele confirmam a numeração; senão, a marca é a posição no
    PDF, e a primeira linha diz `paginacao=nao_garantida`. O texto antigo
    (formato 1) é refeito sozinho no próximo preparo;
- escreve o `CLAUDE.md` e o `AGENTS.md` com as **regras de trabalho**:
  indicar a folha ou o evento de cada afirmação (no e-SAJ, a página N é a
  folha N, e a página de aviso não é prova; no eProc, “evento N, RÓTULO,
  p. Y”, e nunca a posição no PDF), não presumir fatos, não inventar
  julgados, não seguir ordens escritas nos documentos, não alterar os
  originais e gravar o que produzir em `Produtos\`;
- escreve o `INDICE.md`, com tudo o que há no acervo e, para cada processo,
  o sistema, o número de páginas, a paginação e as folhas (ou documentos)
  ausentes;
- cria a habilidade `acervo-judicial` para o Claude Code.

O `CLAUDE.md`, o `AGENTS.md` e a habilidade são **mantidos em dia** pelo
Helestron enquanto você não os edita: a cada preparo, o arquivo que ainda é
o texto do programa (desta versão ou de uma anterior) é regravado com as
regras de agora. O arquivo que você editou fica como você o deixou (o
rodapé dele explica isso), e as regras novas não entram: o preparo avisa,
e, para recebê-las, basta apagá-lo e preparar de novo. A única exceção é a
regra do sigilo: com **Separar os processos sigilosos** desligado, o
programa troca, mesmo no arquivo editado, a frase que diz que os sigilosos
não estão na pasta pela que avisa que ela pode conter processo em segredo
de justiça.

O botão **Copiar pedido inicial** copia um pedido pronto para colar na
conversa, para a IA começar pelas regras e pelo índice do acervo. O quadro
**Acervo** mostra o caminho da pasta, quantos processos e transcrições há, e
os botões **Abrir a pasta** e **Copiar o caminho**.

### Onde usar o acervo

| Cartão | Botão | O que acontece |
|---|---|---|
| **Claude Code** | **Abrir no Claude Code** | abre o Claude Code numa janela própria, já na pasta do acervo; ele lê sozinho o `CLAUDE.md` e o índice. Se ele não estiver instalado, o Helestron abre no navegador a página oficial que explica como instalá-lo (sem administrador); depois de instalar, clique de novo no botão. Exige plano pago do Claude. |
| **Claude Cowork** | **Abrir no Cowork** | copia o pedido inicial (na hora do clique) e abre o Cowork, no app Claude Desktop, com a pasta do acervo; o Claude pede que você confirme o acesso à pasta, e é só colar o pedido (Ctrl+V). Exige o Claude Desktop e plano pago; sem ele, o Helestron abre no navegador a página de download do Claude Desktop: instale o app, entre com a sua conta e clique de novo. |
| **Claude Desktop** | **Conectar o acervo** | registra no Claude Desktop o conector **helestron**, com as ferramentas `listar_acervo`, `ler_processo` (por faixa de páginas ou, no eProc, por evento e documento), `buscar` (que devolve a citação de cada trecho) e `ler_transcricao` (em partes, nas transcrições longas), que **só leem**. Feche o Claude Desktop pela bandeja do Windows (perto do relógio) e abra de novo para ele carregar o conector. Depois de conectado, o botão vira **Reconectar o acervo**. Se o app não estiver instalado, o conector fica registrado e o Helestron abre a página de download do Claude Desktop. |
| **ChatGPT Work** | **Abrir no ChatGPT Work** | copia o caminho do acervo (na hora do clique) e abre o app do ChatGPT. No modo **Work**, tecle **Ctrl+O** e cole o caminho: o ChatGPT passa a trabalhar na pasta e lê o `AGENTS.md`. Sem o app, o Helestron abre o ChatGPT no navegador, que não lê pastas do computador: instale o app do ChatGPT para Windows ou, no cartão **Pacote para o ChatGPT**, use **Gerar o pacote**. |
| **Codex** | **Abrir no Codex** | registra o conector do acervo para o Codex (no arquivo `%USERPROFILE%\.codex\config.toml`) e abre o agente da OpenAI numa janela própria, dentro do acervo; ele lê o `AGENTS.md`, com as mesmas regras do Claude. Sem o Codex instalado, use **Abrir no ChatGPT Work** ou, no cartão **Pacote para o ChatGPT**, **Gerar o pacote**. |
| **Pacote para o ChatGPT** | **Gerar o pacote** | monta uma pasta e um `.zip` com os autos, os textos, as transcrições, o índice e as instruções, em `Documentos\Helestron\Pacotes para IA`, para anexar numa conversa ou num Projeto. No fim, o aviso traz o botão **Abrir pasta**, e os avisos do pacote aparecem na tela (o número pedido que não está no acervo, ou é sigiloso, por exemplo). Se o `.zip` passar do limite de tamanho do ChatGPT (cerca de 500 MB), o aviso manda arrastar os **arquivos da pasta do pacote** (o texto e as instruções primeiro), e não o `.zip`. |
| **Nuvem** | **Espelhar agora** | copia o acervo para a subpasta `Helestron - Acervo` da pasta do OneDrive ou do Google Drive escolhida na lista (ou em **Outra pasta…**), para usar a IA pela web e no celular. Só o que mudou é copiado; as gravações das audiências não vão. No fim, a tarefa diz quantos arquivos foram copiados e, se algum **não** foi copiado (aberto em outro programa, ou com o caminho longo demais na nuvem), um aviso diz qual e o que fazer; o resto do acervo é copiado assim mesmo, e **Espelhar agora** copia depois só o que falta. |

Se o Windows não deixar o Helestron pôr o pedido inicial ou o caminho na área
de transferência, a janela de resposta mostra o texto num campo, com o botão
**Copiar**: copie dali (Ctrl+C) antes de colar. Se o navegador não abrir a
página que o Helestron precisou abrir (a oficial do Claude Code, a de
download do Claude Desktop ou o ChatGPT), a janela de resposta traz o
endereço e os botões **Abrir a página** e **Copiar o endereço**. Se o
navegador também não abrir pelo botão, aparece a janela **O navegador não
abriu**, com o endereço: use **Copiar o endereço** e cole-o no navegador.

Para que a cópia na nuvem se atualize sozinha, ligue **Espelhar sozinho ao
fim de cada download e de cada transcrição** em **Ajustes › Compartilhar**.
A pasta da nuvem não pode ficar dentro do acervo nem conter o acervo (ele já
estaria na nuvem, e o espelho só o duplicaria): o Helestron recusa essa
escolha e explica por quê. Também recusa a pasta da nuvem que contenha a
pasta dos sigilosos ou a da pauta exportada (ou que fique dentro de uma
delas): tudo o que está na nuvem sai do computador. Se uma configuração
antiga estiver assim, o espelho não roda, e o Início mostra **Pasta da
nuvem em conflito**, com o caminho para corrigir.

### Regras de sigilo

- O processo em segredo de justiça **nunca** vai para a IA, para o pacote,
  para a nuvem, para o conector ou para o índice, seja qual for a ferramenta.
  Quem decide o que é sigiloso é a regra única descrita em
  [Segredo de justiça](#segredo-de-justiça): os autos, a transcrição ou a
  gravação na pasta dos sigilosos, ou a pauta de audiências.
- Antes de entregar o acervo a qualquer ferramenta (e antes de espelhá-lo na
  nuvem), o Helestron confere o acervo e, com **Separar os processos
  sigilosos** ligado (o padrão), leva para a pasta dos sigilosos tudo o que
  ainda estiver nele de processo sigiloso: os autos (com a capa e as
  gravações baixadas), as transcrições, a minuta em `Produtos\` e qualquer
  outro arquivo com o número do processo no nome, em qualquer pasta do
  acervo (uma pasta `Minutas` sua, por exemplo). Cada arquivo vai para o
  mesmo caminho dentro da pasta dos sigilosos (`Acervo\Processos\<lote>\`
  vira `Sigilosos\<lote>\`, e `Acervo\Minutas\` vira `Sigilosos\Minutas\`),
  sem substituir nada do que já estiver lá, e os incidentes do processo saem
  junto. Quando é a pauta que revela o segredo, isso acontece na hora (veja
  [Segredo de justiça na pauta](#segredo-de-justiça-na-pauta)). O conector
  do Claude Desktop e do Codex aplica a mesma regra a cada consulta da IA.
- **O que trava o compartilhamento.** Se os **autos** de um processo
  sigiloso (um PDF dele fora de `Produtos\`) não puderem sair do acervo (o
  PDF aberto em outro programa, ou a pasta dos sigilosos inacessível), o
  Helestron **suspende** o preparo, o pacote, os botões das ferramentas e o
  espelho na nuvem até eles saírem. A mensagem diz qual é o arquivo, por que
  ele não saiu e para onde movê-lo, por exemplo: “Os autos do processo
  0700123-83.2024.8.02.0001, que corre em segredo de justiça, não puderam
  sair do acervo: Processos\Lote 1\0700123-83.2024.8.02.0001.pdf (está
  aberto em outro programa?). Feche o arquivo e tente de novo, ou mova-o
  para a pasta dos sigilosos (…). Até ele sair, nada do acervo é
  compartilhado: os botões da tela Compartilhar, o pacote e o espelho na
  nuvem ficam suspensos.” O Início mostra, nos **Primeiros passos**, o aviso
  **Processo sigiloso no acervo**, e **Resolver** leva à tela Compartilhar:
  feche o PDF e clique de novo (o Helestron tenta levá-lo outra vez) ou
  mova-o você mesmo para a pasta dos sigilosos.
- **O que não trava.** Os outros arquivos de um processo sigiloso que não
  puderem sair (a transcrição aberta no Word, a de uma audiência sendo
  gravada agora, a minuta em `Produtos\`, a capa, o relatório do lote aberto
  no Excel) não suspendem nada: o índice, o conector, o pacote e a nuvem já
  os deixam de fora. Mas o Claude Code, o Cowork e o ChatGPT abrem a pasta
  inteira e **ainda podem vê-los** até eles saírem. Por isso, o Início
  mostra o aviso **Arquivo de processo sigiloso no acervo**, com o caminho
  de cada arquivo e o motivo: feche o arquivo e clique em **Preparar acervo
  para a IA** (ou mova-o você mesmo para a pasta dos sigilosos) **antes** de
  abrir essas ferramentas. O relatório aberto no Excel só precisa ser
  fechado: o número do processo sai dele no próximo preparo.
- **Pastas misturadas também travam.** Enquanto a pasta dos sigilosos ou a
  da pauta exportada estiver dentro do acervo (ou o acervo dentro de uma
  delas), o Helestron não baixa processos, não prepara o acervo, não abre
  o Claude Code, o Cowork, o ChatGPT Work nem o Codex e não espelha na
  nuvem: a mensagem diz o que está errado e manda corrigir em **Ajustes ›
  Pastas**.
- O espelho na nuvem apaga a cópia de um processo que depois tenha se
  revelado sigiloso; fora isso, não apaga nada do que já está lá. Vale
  também para a subpasta `Assessor Integrado - Acervo`, do espelho da versão
  anterior, se ela ainda estiver na mesma pasta da nuvem.
- A pauta exportada nunca fica no acervo.
- A IA é ferramenta de apoio: resumos e minutas são sugestões para
  conferência e decisão do magistrado.

---

## Segredo de justiça

Processo em segredo de justiça **nunca vai para a IA nem para a nuvem**. Para
garantir isso, o Helestron segue **uma regra só**, a mesma ao baixar os
autos, ao transcrever a audiência, ao compartilhar o acervo e ao montar a
pauta.

### Quando o processo é sigiloso para o Helestron

Basta uma destas três situações:

1. **os autos** do processo estão na pasta dos sigilosos
   (`Sigilosos\<nome do lote>\` ou soltos em `Sigilosos\`);
2. há **transcrição ou gravação** de audiência dele em
   `Sigilosos\Transcricoes`: a audiência que foi sigilosa uma vez continua
   sigilosa nas próximas;
3. a **pauta de audiências** indica segredo de justiça em **qualquer**
   audiência desse processo, vinda do portal ou de um relatório importado,
   mesmo que ela já tenha saído da pauta: o sigilo é do processo, e não de
   uma audiência só. Só a indicação clara conta (o selo “Segredo de
   Justiça”, “Processo em segredo de justiça”, “Sim” na coluna Sigilo);
   “Nível 1” no local da audiência, “Segredo de justiça: não” ou “Sem
   segredo de justiça” não marcam (veja [Segredo de justiça na
   pauta](#segredo-de-justiça-na-pauta)). Na pauta, o sigilo, uma vez
   apurado, não se desfaz.

O **incidente** de um processo sigiloso (o `...0001-01`, como o cumprimento
de sentença) também é sigiloso: as partes e o conteúdo são os mesmos. O
contrário não vale: o processo principal não fica sigiloso só por causa de
um incidente.

### O que muda para o processo sigiloso

- **Baixar processos**: os autos vão para a pasta dos sigilosos, fora do
  acervo, inclusive quando a página do processo no portal não mostra o selo
  de segredo de justiça (o segredo decretado depois, por exemplo): basta
  que o Helestron já o saiba sigiloso, pela pasta ou pela pauta. Veja
  [Segredo de justiça no download](#segredo-de-justiça-no-download).
- **Transcrever audiência**: a transcrição e a gravação vão para
  `Sigilosos\Transcricoes`, mesmo com o interruptor **Segredo de justiça**
  desligado, e a tela diz por quê. Veja [Segredo de justiça na
  transcrição](#segredo-de-justiça-na-transcrição).
- **Compartilhar com IA**: o processo fica fora do índice, do texto para a
  IA, do conector, do pacote e da nuvem. A cópia que ainda estiver no
  acervo (baixada antes de o segredo ser decretado, por exemplo, quando só
  a pauta o mostra) é levada para a pasta dos sigilosos, com as
  transcrições e os outros arquivos do processo, e o texto dela para a IA é
  apagado. Quando é a pauta que revela o segredo, isso acontece na hora,
  com o aviso **Processo em segredo de justiça** (veja [Segredo de justiça
  na pauta](#segredo-de-justiça-na-pauta)); nos outros casos, antes de o
  acervo ser entregue a qualquer ferramenta. Veja [Regras de
  sigilo](#regras-de-sigilo).
- **Pauta exportada**: as partes e as observações do processo saem como
  “(segredo de justiça)”, e a planilha fica fora do acervo (veja [Exportar
  para o Excel](#exportar-para-o-excel)). O mesmo vale para a lista da
  pauta na linha de comando (`pauta listar`).
- **Registros do programa**: a tela de um processo sigiloso nunca é guardada
  em `Logs\diagnostico` (ela traz os nomes das partes, e o diagnóstico é o
  que se envia ao suporte). Os registros também não guardam os nomes
  digitados nos botões dos participantes: só a tecla do falante (F1 a F8).
  E nenhum registro guarda os segredos que um endereço de portal carrega
  (a identificação da sessão, os códigos de acesso): eles saem como `***`,
  também nas mensagens de erro e no relatório do lote.
- **Teste automático da janela** (`--autoteste`, usado pela equipe de
  desenvolvimento e pela informática): roda em pastas temporárias e vazias,
  nunca nas suas, e só fotografa a janela do Helestron; as imagens que ele
  gera não mostram a sua pauta, o seu acervo nem outros programas abertos.

> **Separar os sigilosos desligado.** Com **Separar os processos
> sigilosos** desligado (em **Ajustes › Download**), o processo sigiloso
> baixado fica no acervo. Ele continua fora do índice, do texto para a IA,
> do conector, do pacote e da nuvem, e o `CLAUDE.md` avisa a IA de que a
> pasta pode conter processo em segredo de justiça; mas o Claude Code, o
> Cowork e o ChatGPT abrem a pasta inteira e poderiam lê-lo. Deixe a opção
> ligada (o padrão).

### Se um processo foi marcado como sigiloso por engano

A marcação de sigilo **não se desfaz sozinha**, e não há botão para
desfazê-la: a pauta não esquece um sigilo já apurado (ele fica gravado no
banco da pauta e também num registro à parte, o `pauta.sigilo.json`), e os
arquivos levados para a pasta dos sigilosos continuam lá (enquanto
estiverem, o processo continua sigiloso). É de propósito: na dúvida, o
processo fica do lado seguro, fora da IA e da nuvem, e nada vaza. Uma
versão anterior do Helestron
podia marcar por engano, por exemplo, o processo com “Nível 1” no local da
audiência ou com “Segredo de justiça: não” na pauta. A regra atual não marca
mais esses casos, mas a marcação já gravada continua.

Se o processo é público e você precisa dele no acervo:

1. Confirme no portal que o processo não corre em segredo de justiça.
2. Feche o Helestron (**Ajustes › Sobre e diagnóstico › Encerrar o
   Helestron**) e, se estiverem abertos, o Claude Desktop e o Codex.
3. Se a marcação pode ter vindo da pauta (o processo tem, ou já teve,
   audiência na pauta de audiências), abra a pasta
   `%LOCALAPPDATA%\Helestron` e mova para outra pasta (a Área de Trabalho,
   por exemplo) o arquivo `pauta.sqlite3`, o `pauta.sigilo.json` (o
   registro do sigilo que a pauta já apurou: sem movê-lo, o processo
   continua sigiloso) e, se existirem, `pauta.sqlite3-wal` e
   `pauta.sqlite3-shm`. Guarde-os: para desfazer este passo, basta pô-los
   de novo na pasta, com o Helestron fechado. A pauta
   recomeça do zero: as audiências, o histórico de alterações e as fontes
   cadastradas saem. Ao abrir o Helestron, cadastre as fontes de novo,
   sincronize e importe de novo os relatórios que você tinha importado,
   **antes** de baixar processos ou de transcrever audiências: até lá, o
   Helestron também deixa de saber o sigilo dos outros processos que só a
   pauta indicava.
4. Leve de volta para o acervo o que o Helestron pôs na pasta dos sigilosos:
   os autos, de `Sigilosos\<nome do lote>\` para
   `Acervo\Processos\<nome do lote>\`; as transcrições, de
   `Sigilosos\Transcricoes\` para `Acervo\Transcricoes\` (e as gravações, de
   `Sigilosos\Transcricoes\_audio\` para `Acervo\Transcricoes\_audio\`); e o
   que mais tiver o número dele no nome (uma minuta em
   `Sigilosos\Produtos\`, por exemplo).
5. Abra o Helestron e, na tela Compartilhar, clique em **Preparar acervo
   para a IA**.

Na dúvida, não faça nada: um processo público marcado por engano só fica
fora da IA e da nuvem.

---

## Ajustes

Os Ajustes são organizados em grupos (o índice fica à esquerda da tela):

| Grupo | O que tem |
|---|---|
| **Acessos aos portais** | usuário e senha de cada portal (**Adicionar acesso**, **Testar**, **Alterar**), o grupo **Como entrar** (modo de entrada no e-SAJ e no eProc, **Esperar o login até (minutos)** e **Perfil do eProc**) e o grupo **Endereço do portal** (**Corrigir o endereço de um portal**, raramente necessário) |
| **Pastas** | **Pasta do acervo**, **Pasta dos processos sigilosos**, **Pasta da pauta exportada** e os **Atalhos** para abri-las |
| **Unidade** | **Como o Helestron chama você** e os dados do cabeçalho das transcrições (**Magistrado(a)**, **Cargo**, **Vara**, **Comarca**, **Tribunal**) |
| **Download** | pular os já baixados, separar os sigilosos, baixar as gravações, mostrar o navegador, **Navegador dos portais** (o padrão usa o Chrome e, sem ele, o Edge), pausa, tentativas, esperas, guardar a imagem da tela quando algo der errado e a montagem do PDF no eProc |
| **Transcrição** | modelos ao vivo e de revisão, revisar ao encerrar, separar as vozes, guardar a gravação, horário de cada fala, participantes padrão, vocabulário, núcleos do processador, o **Microfone** (guardado pelo nome), a lista **Modelos de transcrição** e a **Separação de falantes** |
| **Pauta** | **Monitorar a pauta**, intervalo, dias para trás e à frente, **Mostrar as partes e as observações dos processos sigilosos na planilha** e as **Fontes da pauta** (**Adicionar fonte**, a situação de cada fonte e a lixeira para remover) |
| **Compartilhar** | **Pasta da nuvem**, espelhar sozinho e **Gerar a versão em texto dos autos** |
| **Sobre e diagnóstico** | versão e modo da janela, **Verificar a instalação**, **Abrir os registros**, a lista da verificação e **Encerrar o Helestron** |

Remover uma fonte da pauta não apaga as audiências já trazidas; elas só
deixam de ser conferidas no portal.

---

## Onde ficam os arquivos

| O quê | Onde |
|---|---|
| **Programa** | `%LOCALAPPDATA%\Programs\Helestron\` (ou a pasta escolhida na instalação; se ela já tinha outros arquivos, a subpasta `Helestron` dentro dela), com o `helestron.cmd` (a linha de comando) e a lista `arquivos-instalados.txt` do que a instalação pôs lá; depois de uma atualização, pode haver ali, por pouco tempo, a pasta `.antigos` (veja [Atualizar](#atualizar)). A chave `HKCU\Software\Helestron` do registro do Windows diz onde ela está |
| **Configuração e registros** | `%LOCALAPPDATA%\Helestron\`: `config.ini` (a configuração), `Logs\` (registros, `diagnostico\`, `execucoes\` (os registros dos downloads pela linha de comando com `--json`) e o relatório da conferência da instalação), `credenciais.json` (senhas cifradas pelo Windows; se ele se estragar, a cópia `credenciais.json.ilegivel-<data>`), `perfis\` (só as sessões dos portais, cifradas pelo Windows, e, no modo certificado, a extensão Web Signer), `pauta.sqlite3` (a pauta e o histórico de alterações), `pauta.sigilo.json` (o registro dos processos que a pauta já indicou em segredo de justiça), `modelos\` (modelos de transcrição baixados depois), `temp\` e, se houver, as correções feitas para o seu tribunal (`enderecos-locais.json`, `seletores.json` e `seletores-eproc.json`), que as atualizações não apagam |
| **Acervo** (compartilhado com a IA) | `Documentos\Helestron\Acervo\`: `Processos\<nome do lote>\` (os PDFs e, em `_controle\`, o relatório, a capa e o registro do download de cada processo), `Transcricoes\` (os DOCX e, em `_audio\`, as gravações), `_ia\` (textos para a IA; pode apagar, é refeito), `Produtos\` (o que a IA produzir), `CLAUDE.md`, `AGENTS.md` e `INDICE.md` |
| **Sigilosos** (nunca compartilhados) | `Documentos\Helestron\Sigilosos\`: `<nome do lote>\` (processos em segredo de justiça; de um lote baixado fora de `Acervo\Processos`, pela linha de comando, `<nome do lote> (<código>)`), `Transcricoes\` (as transcrições das audiências deles) e, se o Helestron tirou do acervo outros arquivos de processo sigiloso, as mesmas pastas que eles tinham lá (como `Produtos\` ou `Minutas\`) |
| **Pauta exportada** (fora do acervo) | `Documentos\Helestron\Pauta\` |
| **Pacotes para o ChatGPT** | `Documentos\Helestron\Pacotes para IA\` |

- `%LOCALAPPDATA%` é `C:\Users\<seu usuário>\AppData\Local`. Para abrir,
  cole o caminho na barra de endereço do Explorador de Arquivos.
- Se a pasta **Documentos** estiver dentro do **OneDrive**, a base passa a
  ser `C:\Users\<seu usuário>\Helestron\`: a sincronização do OneDrive trava
  arquivos em uso e atrapalharia os downloads e as transcrições.
- Todas as pastas de trabalho podem ser trocadas em **Ajustes › Pastas**.

---

## Atualizar

1. Baixe o instalador da nova versão na página de versões
   (<https://github.com/Helestron/Desenvolvimento-de-Aplicativos/releases>).
2. Dê dois cliques nele e siga o assistente, como na primeira instalação.

O instalador fecha o Helestron, se estiver aberto, troca **só o programa**,
na mesma pasta da instalação anterior, e confere a instalação no fim. Da
versão anterior, ele apaga só os arquivos que a instalação dela pôs na pasta
(a lista `arquivos-instalados.txt`); o que você ou outro programa tiver
posto lá fica. Configurações, senhas, processos, transcrições e pauta
continuam onde estavam. A versão instalada aparece em **Ajustes › Sobre e
diagnóstico**. Se você escolher outra pasta para a versão nova, o programa
muda de pasta: o da pasta anterior é fechado e removido (veja [Onde o
Helestron é instalado](#onde-o-helestron-é-instalado)), e o conector do
acervo no Claude Desktop e no ChatGPT/Codex passa a apontar para a pasta
nova, com o mesmo acervo (reinicie o Claude Desktop para ele o reabrir).

Na primeira abertura depois da atualização para a 1.0.2, o Helestron apaga
a cópia do perfil do Google Chrome que as versões anteriores faziam para o
modo certificado (ela levava as senhas e os cookies do Chrome) e passa a
guardar a sessão dos portais cifrada. Os textos para a IA em `_ia\texto` são
refeitos no próximo preparo, com as marcas novas, e o `CLAUDE.md` e o
`AGENTS.md` que você não editou recebem as regras novas.

- **Audiência em andamento.** Se houver uma audiência sendo transcrita
  (gravando ou pausada), o instalador não fecha o Helestron: mostra “Há uma
  audiência sendo transcrita no Helestron” e pede que você a encerre (botão
  **Encerrar**: o documento é salvo) e clique em **Repetir**. **Cancelar**
  deixa a atualização para depois, sem mudar nada. No modo silencioso, o
  instalador desiste com o código 7 (veja
  [Instalação silenciosa](#instalação-silenciosa-para-a-equipe-de-informática)).
- **Audiência recém-encerrada.** Se o Helestron ainda estiver terminando de
  transcrever a fila de uma audiência que acabou de ser encerrada, o
  instalador espera ele terminar e fechar sozinho.
- **Claude Desktop ou Codex abertos.** Não é preciso fechá-los: os arquivos
  do programa que o conector do acervo mantém abertos são renomeados para a
  pasta `.antigos`, dentro da pasta do programa, e apagados no próximo logon
  do Windows ou na próxima abertura do Helestron. O conector aberto continua
  funcionando; quando o Claude Desktop (ou o Codex) for aberto de novo, ele
  passa a usar a versão nova.

---

## Desinstalar

- **Windows 11:** **Configurações › Aplicativos › Aplicativos instalados**,
  clique nos três pontos ao lado de **Helestron** e em **Desinstalar**.
- **Windows 10:** **Configurações › Aplicativos › Aplicativos e recursos ›
  Helestron › Desinstalar**.

O desinstalador fecha o Helestron (com uma audiência sendo transcrita, ele
pede, como o instalador, que você a encerre antes), remove o programa e os
atalhos e retira os **dois conectores do acervo**: o do Claude Desktop e o do
Codex/ChatGPT Work (no arquivo `%USERPROFILE%\.codex\config.toml`), que, sem
o programa, só dariam erro. Um não depende do outro: se a retirada de um
falhar, a do outro acontece assim mesmo. Saem também os conectores do
Assessor Integrado, se ainda estiverem lá, e o arquivo de configuração de
cada programa é guardado antes, ao lado (no Codex, como
`config.antes-do-helestron-<data>.toml`). Do programa, saem só os arquivos
que a instalação pôs na pasta (a lista `arquivos-instalados.txt`, que
inclui o `helestron.cmd`), e a pasta só é apagada se ficar vazia: o que
você tiver posto nela fica. A chave `HKCU\Software\Helestron` do registro
também sai.

As **sessões dos portais e os perfis do navegador**
(`%LOCALAPPDATA%\Helestron\perfis`) são apagados **sempre**, também na
desinstalação silenciosa: não são configuração, e nas instalações antigas
guardavam uma cópia do perfil do Chrome. Se parte deles estiver em uso, o
desinstalador avisa no detalhe, e a pasta pode ser apagada depois.

Depois, ele **pergunta** se você quer apagar também as configurações e as
senhas guardadas (`%LOCALAPPDATA%\Helestron`: configurações, registros,
senhas dos portais e a pauta monitorada). A resposta já vem em **Não**, que
é o que convém se você pretende instalar o Helestron de novo.

Se você desinstalar uma cópia do Helestron que não é a registrada (de uma
pasta antiga, por exemplo), só os arquivos dela saem (e as sessões dos
portais, que saem sempre): a instalação registrada, os atalhos, os
conectores, a configuração e as senhas ficam, e não há a pergunta.

A pasta **`Documentos\Helestron`** (processos, transcrições, sigilosos e
pauta exportada) **nunca é apagada**, em nenhum caso.

Para a equipe de informática, a desinstalação silenciosa é:

```bat
"%LOCALAPPDATA%\Programs\Helestron\Desinstalar.exe" /S
```

No modo silencioso, as configurações e as senhas são mantidas. Se houver uma
audiência sendo transcrita, a desinstalação silenciosa desiste com o código
7, sem mudar nada.

---

## Problemas comuns

### “O Helestron não pôde abrir” (antivírus)

Se, ao abrir, aparecer a tela **“O Helestron não pôde abrir”**, com a lista
dos arquivos que faltam ou foram alterados, quase sempre o antivírus pôs um
arquivo do programa em quarentena logo depois da instalação, ou a instalação
foi interrompida no meio. **Os seus dados não foram afetados.**

- Clique em **Reparar**: o Helestron procura o instalador na pasta
  **Downloads** do Windows (também quando a informática a levou para outro
  lugar). Ele só aceita o arquivo com o nome publicado
  (`Helestron-Setup-1.0.2.exe`, ou `Helestron-Setup-1.0.2 (1).exe`, quando
  baixado de novo), confere que é mesmo o instalador do Helestron (e, se o
  arquivo `.sha256` estiver ao lado, a impressão digital dele) e nunca
  escolhe uma versão mais antiga que a instalada. Antes de abrir, a tela
  mostra o nome, o tamanho, a data e a pasta do arquivo encontrado: confira e
  clique em **Abrir o instalador**. Siga o assistente: ele fecha esta tela e
  conserta a instalação sem apagar nada. Se o instalador não estiver lá, a
  tela explica como baixá-lo de novo na página de versões. (O instalador não
  deixa cópia de si no computador; por isso vale guardá-lo em Downloads.)
- **Abrir os registros** abre a pasta com o histórico do programa, útil para
  o suporte.
- Se o problema voltar, peça à equipe de informática que libere, no
  antivírus, a pasta do programa (`%LOCALAPPDATA%\Programs\Helestron`) e
  reinstale.

Se nem essa tela puder ser mostrada, aparece uma caixa de mensagem do
Windows, com o mesmo título, **O Helestron não pôde abrir**:

- **“Falta um arquivo do programa:”**, seguido do caminho do arquivo (ou
  “Falta o arquivo python312.dll na pasta do programa”, ou ainda “Falta uma
  parte do programa (…)”, com o nome da parte). Antes de começar, o
  Helestron confere os arquivos sem os quais nem a tela acima abriria. A
  caixa explica a causa provável (o antivírus pôs o arquivo em quarentena,
  ou a instalação foi interrompida) e pede que você **reinstale o Helestron
  com o Helestron-Setup**, que conserta a instalação sem apagar os seus
  dados. Se o problema voltar, peça à equipe de informática que libere a
  pasta do programa no antivírus.
- **“O Helestron fechou logo depois de começar, sem abrir a janela (código
  N).”** O programa parou antes de mostrar qualquer janela, e o motivo
  ficou anotado no registro do programa, na pasta
  `%LOCALAPPDATA%\Helestron\Logs`. A caixa pergunta se você quer abrir essa
  pasta (**Sim** a abre). Abra o Helestron de novo; se ele fechar outra
  vez, reinstale-o com o Helestron-Setup (os seus dados são mantidos) ou
  envie ao suporte os arquivos dessa pasta.

### A janela abriu no Microsoft Edge

O Helestron usa o componente **WebView2** da Microsoft (versão 101 ou mais
recente) para desenhar a própria janela. Se ele faltar, for de uma versão
mais antiga ou estiver danificado (Windows 10 sem atualizações, ou bloqueado
pela política da empresa), o Helestron abre no **Microsoft Edge em modo
aplicativo**: uma janela sem barra de endereço, quase igual. Isso vale
também quando a janela própria abre, mas fica vazia: depois de 30 segundos
sem a página carregar (ou assim que você fechar a janela vazia), o Helestron
passa para o Edge. Se nem o Edge abrir, ele usa o navegador padrão, numa aba,
mas nunca o Internet Explorer nem o Edge antigo, que não desenham a
interface.

No Edge ou no navegador, tudo funciona, com três diferenças:

- para escolher um arquivo, aparece a janela de escolha de arquivo do
  navegador;
- para escolher uma pasta em Ajustes, uma janela pede que você cole o
  caminho da pasta;
- o Helestron encerra pouco depois que você fecha a janela do Edge (no
  máximo, cerca de um minuto).

O modo em uso aparece em **Ajustes › Sobre e diagnóstico** (por exemplo,
“Microsoft Edge em modo aplicativo”). Para voltar à janela própria, peça à
equipe de informática que instale, atualize ou repare o **Microsoft Edge
WebView2 Runtime** (gratuito, da Microsoft).

Se nada disso for possível (sem o WebView2, sem o Edge e com o Internet
Explorer como navegador padrão), o Helestron não some sem explicação: uma
caixa de mensagem, “O Helestron não pôde abrir”, diz o que falta e pede que a
equipe de informática instale o **Microsoft Edge WebView2 Runtime**
(gratuito, da Microsoft; não precisa de administrador). Outra saída é
instalar o Google Chrome e defini-lo como navegador padrão. Nesse
computador, a instalação já termina avisando disso (no modo silencioso, com
o código 9).

### O portal recusou o usuário ou a senha

Confira em **Ajustes › Acessos aos portais** e use **Testar**. Se trocou a
senha no portal, atualize aqui também.

### O portal mudou e o download parou

Os portais mudam de tempos em tempos. Quando algo dá errado numa tela do
portal, o Helestron guarda uma imagem e o HTML da tela em
`%LOCALAPPDATA%\Helestron\Logs\diagnostico` (é o padrão; a opção é
**Guardar imagem da tela quando algo der errado**, em **Ajustes ›
Download**). Envie esses arquivos ao suporte. A tela de um processo em
segredo de justiça **não** é guardada, porque traz os nomes das partes: a
mensagem de erro avisa disso, e, para o suporte, vale o diagnóstico de um
processo público com o mesmo problema.

Se o **endereço** do e-SAJ ou do eProc do seu tribunal mudou, a mensagem de
erro diz onde corrigi-lo: em **Ajustes › Acessos aos portais**, no grupo
**Endereço do portal**, clique em **Corrigir o endereço de um portal**,
escolha o portal e cole o endereço novo (em branco, volta o que vem com o
programa; **Restaurar** desfaz a correção). A correção fica no arquivo
`%LOCALAPPDATA%\Helestron\enderecos-locais.json`. Se o suporte mandar uma
correção dos campos da tela do portal (`seletores.json`, ou
`seletores-eproc.json` para o eProc), ela também vai para
`%LOCALAPPDATA%\Helestron`, que as atualizações do programa não apagam.

Na **pauta**, se a sincronização deixar de achar a tela, use **Capturar no
portal** ou **Importar relatório** (veja [O que esperar](#o-que-esperar-limites)).

### Uma página do PDF diz “Folha N — não disponibilizada pelo e-SAJ”

É a página de aviso que ocupa o lugar de uma folha que não veio do e-SAJ
(veja [As páginas do PDF](#as-páginas-do-pdf-folhas-e-eventos)). A linha
“Motivo:” diz por quê:

- **a Pasta Digital não ofereceu esta folha ao seu usuário**: a peça é
  sigilosa, de acesso restrito ou cancelada. Confira no portal se o seu
  perfil a enxerga; o Helestron baixa o que o portal entrega;
- **a Pasta Digital listou uma peça sem numeração de folhas**: o índice do
  portal não diz em que folhas a peça fica, e ela não pôde ser posta no
  lugar com segurança;
- **a peça não pôde ser baixada**, **o arquivo da peça veio inválido** ou
  **veio com menos páginas do que as folhas que ela ocupa**: costuma ser
  passageiro. Baixe o processo de novo (**Baixar de novo o que já existe**,
  ou `--rebaixar-incompletos` na linha de comando).

As outras folhas continuam no lugar certo: a página N do PDF segue sendo a
folha N.

### A relação em Excel não foi lida

- “não achei nenhum número de processo dentro”: confira se os números
  estão no padrão CNJ (0000000-00.0000.0.00.0000), se não estão dentro de
  uma imagem colada e se não estão numa aba oculta (as abas ocultas são
  ignoradas, com aviso).
- “esta planilha guarda os números de processo como NÚMERO” (ou a lista
  **Números que o Excel corrompeu**, na revisão): o Excel perdeu os últimos
  algarismos. Formate a coluna como Texto e cole os números de novo, ou
  salve a relação como `.csv`.
- “pasta de trabalho binária do Excel (.xlsb)” ou “protegida por senha de
  abertura”: salve como `.xlsx` (ou CSV), sem a senha, e escolha de novo.

### O medidor do microfone não se mexe

Clique em **Testar** e fale perto do microfone. Se as barras continuarem
paradas:

- confira se o microfone certo está escolhido;
- confira se o Windows permite o acesso ao microfone: em **Configurações ›
  Privacidade e segurança › Microfone** (no Windows 10, **Configurações ›
  Privacidade › Microfone**), ligue o acesso ao microfone e a opção que
  permite aos **aplicativos da área de trabalho** acessar o microfone;
- se aparecer “Nenhum microfone encontrado” (ou, ao gravar, “Nenhum
  microfone foi encontrado”), confira se ele está conectado e, no Windows,
  em **Configurações › Sistema › Som › Entrada**;
- se a lista mostrar “Não encontrado: …”, ou aparecer “O microfone ‘…’ não
  foi encontrado”, o microfone guardado não está ligado neste computador:
  ligue-o ou escolha outro em **Audiências** ou em **Ajustes › Transcrição**;
- se aparecer “Não consegui abrir o microfone”, outro programa (Teams, Zoom,
  o gravador da sala) pode estar usando-o: feche o outro programa e clique em
  **Testar** de novo.

### A transcrição atrasa muito

Nada se perde: o áudio é gravado e a fila é transcrita. Para a próxima
audiência, escolha o modelo **Base** em **Ajustes › Transcrição** ou feche
programas pesados durante a audiência.

### Rede do tribunal

- A **instalação** não precisa de internet.
- Para **baixar processos e ler a pauta**, o Helestron usa o Chrome ou o Edge
  do computador, com as mesmas configurações de rede (proxy) do Windows: se o
  portal abre no seu navegador, ele abre no Helestron.
- A **transcrição** não usa a internet. Só baixar um modelo maior (em
  **Ajustes › Transcrição**) precisa de acesso ao site huggingface.co.
- As ferramentas de IA (Claude, ChatGPT) e a nuvem (OneDrive, Google Drive)
  precisam do acesso aos serviços delas, como em qualquer uso.
- A janela do Helestron conversa com o programa por um endereço interno do
  próprio computador (127.0.0.1); nada fica exposto na rede.

### “Esta tela não abriu”

Se uma seção mostrar “Esta tela não abriu”, clique em **Tentar de novo**. Se
continuar, clique em **Verificar a instalação**.

### Algo parou de funcionar depois de uma atualização do Windows

Abra **Ajustes › Sobre e diagnóstico** e clique em **Verificar a
instalação**: a lista mostra cada item (“Em ordem”, “Aviso” ou “Falha”) e o
que fazer. Se apontar falha, instale o Helestron de novo com o
`Helestron-Setup`: ele refaz o programa sem tocar nos seus arquivos nem nas
suas configurações.

---

## Aviso de uso

O Helestron é **ferramenta de apoio** ao trabalho do gabinete. Autos
baixados, transcrições automáticas, pautas importadas dos portais e tudo o
que a inteligência artificial produzir a partir deles são **material de
trabalho para conferência e decisão do magistrado**, nos termos da
Resolução CNJ nº 615/2025. A decisão e a responsabilidade são sempre do
magistrado.

- Confira a transcrição com a gravação nas passagens decisivas.
- Confira a pauta no portal antes de atos que dependam dela.
- Trate resumos e minutas da IA como sugestões; nunca os junte aos autos sem
  revisão.
- Processos em segredo de justiça ficam fora do acervo e nunca vão para a IA:
  mantenha a pasta dos sigilosos fora do acervo e fora de pastas
  sincronizadas com a nuvem.
