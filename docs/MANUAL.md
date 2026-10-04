# Helestron — Manual do usuário

Versão 1.0.0 · para Windows 10 e 11 (64 bits)

O Helestron reúne, numa única janela, as tarefas do gabinete que mais tomam
tempo:

| Função | O que faz | Onde o resultado fica |
|---|---|---|
| **1. Baixar processos** | Com o **seu** login no e-SAJ ou no eProc, baixa todos os processos de uma relação (Excel, Word, PDF, lista colada ou link): **um PDF por processo**, com o número do processo como nome | `Acervo\Processos\<nome do lote>\` |
| **2. Transcrever audiência** | Transcreve a audiência **ao vivo**, pelo microfone, no próprio computador; transcreve também gravações já existentes | `Acervo\Transcricoes\<número do processo>.docx` |
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
| **Início** | saudação, as quatro funções, "Hoje na pauta", "Atividade recente" e "Primeiros passos" | Ctrl+1 |
| **Processos** | baixar os autos de uma relação | Ctrl+2 |
| **Audiências** | transcrever a audiência | Ctrl+3 |
| **Pauta** | a pauta de audiências | Ctrl+4 |
| **Compartilhar** | entregar o acervo à IA | Ctrl+5 |
| **Ajustes** | acessos, pastas e preferências | Ctrl+6 |
| **Ajuda** | passo a passo, perguntas frequentes e atalhos | Ctrl+7 |

No rodapé da barra lateral aparecem os trabalhos em andamento (um download,
uma sincronização da pauta, o preparo do acervo), cada um com um anel de
progresso; clique neles para ir à tela que os acompanha. Ali também ficam a
versão do programa e a indicação "ligado" (ou "sem conexão").

### Para quem usava o Assessor Integrado

O Helestron substitui o antigo Assessor Integrado. O que mudou:

- a instalação é feita por **um único arquivo**, `Helestron-Setup-1.0.0.exe`,
  sem o `INSTALAR.bat`, sem PowerShell e sem baixar nada durante a
  instalação;
- as pastas de trabalho passaram para `Documentos\Helestron`; os arquivos do
  Assessor Integrado continuam onde estavam e podem ser copiados para as
  novas pastas, se você quiser;
- as **senhas** guardadas no Assessor Integrado **não são aproveitadas**:
  cadastre-as de novo em **Ajustes › Acessos aos portais**;
- o conector do acervo no Claude Desktop passou a se chamar **helestron**; o
  antigo (*assessor-integrado*) é retirado sozinho quando você conecta o
  acervo de novo;
- há uma função nova: a **Pauta de audiências**.

---

## Instalação

### Do que você precisa

- **Windows 10 (versão 1809 ou mais recente) ou Windows 11, de 64 bits.**
- Espaço em disco: o programa ocupa pouco mais de 1 GB. O assistente mostra
  o espaço necessário antes de copiar.
- Para baixar processos e ler a pauta, o **Google Chrome** ou o **Microsoft
  Edge** (o Edge já vem no Windows).
- Para transcrever, um **microfone** (o do notebook serve; um microfone de
  mesa capta melhor a sala de audiências).
- Para a janela do programa, o componente **WebView2** da Microsoft, que já
  vem no Windows 11 e no Windows 10 atualizado. Sem ele, o Helestron abre no
  Edge (veja [Problemas comuns](#a-janela-abriu-no-microsoft-edge)).

### Passo a passo

1. **Baixe o instalador.** Na página de versões do Helestron
   (<https://github.com/Helestron/Desenvolvimento-de-Aplicativos/releases>),
   abra a versão mais recente e, na lista de arquivos (**Assets**), clique em
   **`Helestron-Setup-1.0.0.exe`** (cerca de 600 MB). Deixe-o na pasta
   **Downloads**: é lá que o botão **Reparar** o procura, se um dia for
   preciso (veja [Problemas comuns](#o-helestron-não-pôde-abrir-antivírus)).

   O navegador pode avisar que o arquivo "não é baixado com frequência". No
   Edge, clique nos três pontos ao lado do aviso, em **Manter** e, se ele
   perguntar de novo, confirme que deseja manter o arquivo.

2. **Dê dois cliques no arquivo baixado.** Na primeira vez, o Windows mostra
   a tela azul **"O Windows protegeu o computador"**. Clique em
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
   | **Pasta do programa** | deixe a pasta sugerida e clique em **Próximo** (para usar outra, clique em **Procurar**) |
   | **Opções** | o programa é obrigatório; desmarque **Atalho na Área de Trabalho** se não quiser o ícone ali; clique em **Instalar** |
   | **Instalando** | aguarde: o Helestron é copiado e, no fim, conferido (pode levar até um minuto) |
   | **Pronto!** | deixe marcado **Abrir o Helestron** e clique em **Concluir** |

Se o Helestron estiver aberto (numa atualização, por exemplo), o instalador o
fecha antes de copiar; a transcrição de uma audiência em curso é salva antes.

### Onde o Helestron é instalado

Na pasta `%LOCALAPPDATA%\Programs\Helestron`, que é
`C:\Users\<seu usuário>\AppData\Local\Programs\Helestron`. O instalador cria
o atalho **Helestron** no Menu Iniciar e na Área de Trabalho e registra o
programa em **Aplicativos instalados**, de onde ele pode ser desinstalado.

Os seus dados (configurações, senhas, processos, transcrições e pauta) ficam
**em outras pastas** e não são tocados quando o programa é atualizado ou
reinstalado.

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
- confere se o componente da janela (WebView2) ou, na falta dele, o Edge
  está disponível.

Se tudo estiver em ordem, aparece "Instalação conferida: tudo certo." Se algo
faltar (quase sempre, um arquivo que o antivírus pôs em quarentena), o
assistente diz o que aconteceu e onde está o relatório:

```
%LOCALAPPDATA%\Helestron\Logs\verificacao-instalacao.txt
```

Quase sempre resolve instalar de novo. Se o problema continuar, peça à equipe
de informática que libere, no antivírus, a pasta do programa.

Além disso, **a cada abertura** o Helestron confere rapidamente se os seus
arquivos essenciais estão lá. Se faltar algum, ele mostra uma tela própria em
vez de quebrar no meio do uso (veja
[Problemas comuns](#o-helestron-não-pôde-abrir-antivírus)).

### Instalação silenciosa (para a equipe de informática)

O instalador aceita o modo silencioso do NSIS:

```bat
Helestron-Setup-1.0.0.exe /S
Helestron-Setup-1.0.0.exe /S /D=D:\Programas\Helestron
```

- `/S` instala sem nenhuma tela, na pasta padrão
  (`%LOCALAPPDATA%\Programs\Helestron`) ou, numa atualização, na mesma pasta
  da instalação anterior.
- `/D=` escolhe a pasta. Tem de ser o **último** argumento e vai **sem
  aspas**, mesmo que o caminho tenha espaços.
- A instalação é **por usuário**: rode o instalador **na conta de quem vai
  usar o programa**, e não como SYSTEM nem com outra conta, senão o Helestron
  vai para o perfil errado.
- Para esperar o fim num script do `cmd`, use
  `start /wait "" Helestron-Setup-1.0.0.exe /S` e leia o `%ERRORLEVEL%`.
- A conferência final roda também no modo silencioso, e o relatório fica em
  `%LOCALAPPDATA%\Helestron\Logs\verificacao-instalacao.txt`.

Códigos de saída:

| Código | Significado |
|---|---|
| 0 | instalado e conferido |
| 2 | copiado, mas a conferência final encontrou problema (veja o relatório) |
| 4 | o Helestron (ou o Claude Desktop, usando o conector do acervo) continuou aberto e prendeu os arquivos; feche-o e rode de novo |
| 5 | outro instalador do Helestron já estava aberto |
| 6 | Windows incompatível (32 bits, ou anterior ao Windows 10) |

Para conferir a impressão digital do instalador, no PowerShell:
`Get-FileHash .\Helestron-Setup-1.0.0.exe -Algorithm SHA256`, e compare com o
arquivo `.sha256` da página de versões.

A desinstalação silenciosa é descrita em [Desinstalar](#desinstalar).

---

## Primeiro uso

Abra o Helestron pelo atalho **Helestron**, na Área de Trabalho ou no Menu
Iniciar. Se ele já estiver aberto, o atalho só traz a janela para a frente.

A tela **Início** mostra a saudação, os quatro cartões das funções e, à
direita, os **Primeiros passos**: uma lista de verificação com o que ainda
falta configurar (o acesso aos portais, as pastas, o modelo de transcrição e
a pauta de audiências). Cada item pendente tem o botão **Resolver**, que leva
direto ao lugar certo; o que já está em ordem aparece marcado.

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
   Desligado, a senha vale só até fechar o Helestron.
5. Clique em **Salvar**.

Cada portal cadastrado aparece na lista com "Senha guardada" e o botão
**Testar**, que entra no portal e diz se o acesso funcionou. Para trocar a
senha, clique no nome do portal; para apagar o acesso, clique no nome e, na
janela que se abre, em **Apagar**.

Logo abaixo, o grupo **Como entrar** define o modo de entrada em cada
sistema:

- **Como entrar no e-SAJ**: **Usuário e senha**, **Certificado digital**
  (a janela do navegador abre e você digita o PIN do token) ou
  **Entrar manualmente** (o navegador abre na tela de entrada do portal; você
  entra como de costume, e o Helestron continua sozinho depois);
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
> Helestron recusa uma escolha que quebre essa regra.

### Seu nome e os dados da unidade

Em **Ajustes › Unidade**:

- **Como o Helestron chama você**: o nome que aparece na saudação do Início
  ("Boa tarde, …");
- **Magistrado(a)**, **Cargo**, **Vara**, **Comarca** e **Tribunal**: vão no
  cabeçalho das transcrições. O **Tribunal** (sigla, como TJAL) também é o
  sugerido quando você escolhe o portal da pauta.

### Como a janela conversa com você

- **Perguntas.** Quando um portal pede o código de verificação (enviado por
  e-mail, no e-SAJ, ou gerado no aplicativo autenticador, no eProc), uma
  janela aparece no meio da tela, com um campo grande. Digite o código: com
  seis dígitos, ele é enviado sozinho. Se o código por e-mail não chegar, use
  **Pedir novo código**. A janela mostra o prazo ("Responda em até 4:59",
  por exemplo).
- **Avisos.** Os avisos (um lote que terminou, uma planilha pronta) aparecem
  no canto superior direito, às vezes com um botão, como **Abrir pasta**.
- **Fechar.** Se você fechar a janela com trabalho em andamento, o Helestron
  pergunta antes (**Fechar mesmo assim** ou **Continuar**). Ao fechar, a
  transcrição de uma audiência em curso é salva antes.
- **Sem conexão.** Se a faixa "Sem conexão com o Helestron. Tentando de novo…"
  aparecer, a janela perdeu contato com o programa por um instante; ela
  volta sozinha.

---

## 1. Baixar processos

### Passo a passo

1. Abra **Processos** (ou clique em **Baixar processos**, no Início).
2. **Traga a relação**, de um destes jeitos:
   - **arraste** o arquivo para a área "Arraste a relação de processos para
     cá" (planilha do Excel, documento do Word, PDF, CSV ou texto, inclusive
     o ".xls" exportado pelo SAJ e pelo eProc);
   - clique em **Escolher arquivo**;
   - clique em **Colar lista** e cole os números, um ou vários por linha (do
     Excel, do e-mail ou do SAJ; o que não for número de processo é
     ignorado). Também dá para teclar **Ctrl+V** direto na tela;
   - clique em **Link** e cole o link de uma planilha ou documento do Google
     Planilhas, Google Docs, Google Drive, OneDrive ou SharePoint,
     compartilhado como "qualquer pessoa com o link".
3. **Confira a revisão.** A tabela mostra cada processo reconhecido, com o
   **tribunal** e o **sistema** (eles saem do próprio número). À parte
   aparecem os avisos, os **Números que o Excel corrompeu** (formate a
   coluna como Texto, digite-os de novo e salve) e os números **Fora do
   alcance do Helestron** (tribunal ou sistema que ele não atende). Para
   tirar um processo do lote, clique no **×** da linha; para desfazer, clique
   de novo. **Trocar a relação** recomeça.
4. **Confira as opções do lote**:
   - **Nome do lote (vira o nome da pasta)**;
   - **Separar os sigilosos** (ligado: o processo em segredo de justiça vai
     para a pasta dos sigilosos, fora do acervo da IA);
   - **Baixar de novo o que já existe** (desligado: o processo cujo PDF já
     está na pasta é pulado);
   - **Mostrar o navegador enquanto baixa** (útil para acompanhar, ou quando
     o portal pede alguma confirmação).

   Em **Acesso aos portais**, logo abaixo, aparece cada portal da relação:
   "Senha guardada" ou "Sem senha guardada: o navegador abre para você
   entrar". Use **Cadastrar** ou **Alterar** para resolver ali mesmo.
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
   | Falhou | outro problema; o detalhe aparece na linha |
   | Interrompido | o lote foi parado antes |

   **Parar** interrompe depois do processo atual. No fim aparecem **Abrir
   pasta**, **Relatório**, **Tentar de novo (N)** (baixa de novo só os que
   falharam) e **Novo lote**.

Abaixo da área da relação, **Últimos lotes** lista os lotes já baixados, com
**Abrir** (a pasta) e o ícone do relatório.

### O que sai

Uma pasta com o nome do lote, em `Acervo\Processos\`, contendo **um PDF por
processo**, nomeado com o número (`0700123-83.2024.8.02.0001.pdf`). O
relatório do lote fica em `_controle\relatorio.csv`, que abre no Excel.

### Bom saber

- O que já foi baixado não é baixado de novo: pode deixar a relação crescer e
  baixar outra vez.
- Processo dependente (incidente) sai com o sufixo: `...0001-01.pdf`.
- Se a relação trouxer a **senha do processo** (`número ; senha`, ou uma
  coluna "senha"), ela é usada, e a linha mostra **Senha na relação**.
- **Tribunais em transição** do e-SAJ para o eProc (TJAL, TJSP e TJAC): o
  Helestron procura primeiro no e-SAJ e, não achando, no eProc.
- No eProc, os autos são montados documento a documento, na ordem dos
  eventos, com marcadores (índice) por evento no PDF.
- Em **Ajustes › Download** há outras opções, como **Baixar também as
  gravações de audiência** e a **Pausa entre processos (segundos)**. Não
  zere a pausa em listas grandes: uma rajada de acessos pode ser lida pelo
  portal como abuso.
- Um lote também pode começar pela **Pauta** ("Baixar os autos"); o
  andamento aparece aqui do mesmo jeito.

### Segredo de justiça

Com **Separar os sigilosos** ligado (o padrão):

- o processo sigiloso vai para `Sigilosos\<nome do lote>\`, **fora** do
  acervo compartilhado com a IA. Vai para lá também o processo público que
  tenha alguma **peça sigilosa** (no e-SAJ, a peça marcada como sigilosa na
  Pasta Digital), porque o PDF a traz inteira;
- o relatório do lote que fica no acervo **não identifica** os sigilosos: no
  lugar do número, a linha diz "(processo sigiloso)". O relatório completo,
  com os números, fica em `Sigilosos\<nome do lote>\_controle\relatorio.csv`;
- a transcrição de audiência que já estava no acervo quando o download
  descobriu o sigilo é levada para `Sigilosos\Transcricoes`, com a gravação.

---

## 2. Transcrever audiência

A transcrição roda **no próprio computador, sem internet**: o áudio da
audiência não sai da máquina.

### Antes de começar

Em **Audiências**, no cartão **Nova audiência**:

1. **Número do processo**: é ele que dá nome ao documento. O Helestron
   confere o dígito verificador ("Número válido · TJAL", ou "O dígito
   verificador não confere"). Se houver audiências de hoje na pauta, elas
   aparecem logo abaixo ("Hoje na pauta:"): um clique preenche o número, o
   tipo e o sigilo.
2. **Tipo de audiência**: Conciliação, Instrução e julgamento, Una,
   Custódia, Justificação, Mediação ou Outra.
3. **Segredo de justiça**: ligue para processo sigiloso (veja abaixo).
4. **Microfone**: escolha o microfone e clique em **Testar**; fale algo, e
   as barras do medidor devem se mexer. Clique em **Parar teste** quando
   terminar.
5. **Participantes**: os nomes dos botões de quem está falando, um para cada
   tecla de **F1 a F8**. O padrão é Juiz(a), Promotor(a), Defensor(a),
   Advogado(a) do autor, Advogado(a) do réu, Testemunha, Parte e Outro.
   Edite à vontade: os nomes ficam guardados para as próximas audiências.

Abaixo do botão de gravar, o Helestron diz se o modelo de transcrição está
pronto ("Modelo … pronto").

### Durante a audiência

1. Clique no **botão vermelho grande** (**Gravar**) ou tecle **Ctrl+Enter**.
2. O texto aparece poucos segundos depois de cada fala, com o horário e o
   nome de quem falou.
3. Indique **quem está falando** com os botões ou com as teclas **F1 a F8**.
4. **Pausar** suspende a gravação (num intervalo, por exemplo); **Retomar**
   continua.
5. Se você subir o texto para reler um trecho, a rolagem automática fica
   suspensa; o botão **Ir para o fim** volta ao ponto atual.
6. Para terminar, clique em **Encerrar** e confirme em **Encerrar e salvar**.
   O que ainda estiver na fila é transcrito antes de salvar.

No alto da tela ficam o cronômetro e a situação (**Gravando**, **Pausado**).
Se o computador ficar para trás, aparece "Atraso de N s": nada se perde, o
áudio está gravado e a fila é transcrita. No rodapé, "Salvo automaticamente
às …" mostra o último salvamento.

Você pode sair da tela de Audiências durante a gravação: ela continua, e uma
bolinha vermelha em **Audiências**, na barra lateral, indica que a audiência
está sendo gravada. Ao voltar, o texto e o tempo estão lá.

### Depois: o documento

Ao encerrar, aparece **Transcrição salva**, com **Abrir documento**, **Abrir
pasta** e **Nova audiência**.

**O que sai:** `Acervo\Transcricoes\<número do processo>.docx`, com a ficha
da audiência (processo, data, horário, unidade, participantes), cada fala com
o falante e a hora `[hh:mm:ss]`, e o aviso de que a transcrição é
automática. A gravação fica em `Transcricoes\_audio`, para conferência. Se já
houver uma transcrição do mesmo processo, a nova sai como
`<número> (2).docx`: nada é sobrescrito.

**Revisar com o modelo preciso**: o botão **Revisar** refaz o texto inteiro
com um modelo maior e mais preciso, a partir da gravação e dos falantes que
você marcou. Leva alguns minutos; acompanhe ali mesmo ou na barra lateral. No
fim, o botão vira **Abrir a revisão**. Para que a revisão aconteça sempre ao
encerrar, ligue **Revisar ao encerrar a audiência** em **Ajustes ›
Transcrição**; com **Separar as vozes na revisão** ligado, ela também separa
os falantes automaticamente.

> A transcrição é automática: confira o texto antes de usá-lo em qualquer
> ato, especialmente nas passagens decisivas, com a gravação.

### Segredo de justiça

Com **Segredo de justiça** ligado, a transcrição e a gravação vão para
`Sigilosos\Transcricoes` (e `Sigilosos\Transcricoes\_audio`), **fora** do
acervo compartilhado com a IA. Se os autos do processo já estiverem na pasta
dos sigilosos, a transcrição vai para lá mesmo com o interruptor desligado.

### Transcrever uma gravação

Para transcrever uma gravação já existente (por exemplo, a mídia baixada do
processo, ou um arquivo de áudio ou vídeo), clique em **Transcrever uma
gravação**, escolha o arquivo, confira o **Número do processo** (o Helestron
o lê do nome do arquivo, quando ele está lá) e o **Segredo de justiça**, e
clique em **Transcrever**. A transcrição usa o modelo preciso e pode levar
alguns minutos; acompanhe na barra lateral.

### Recuperar uma transcrição interrompida

O documento é salvo sozinho a cada poucos segundos. Se o computador desligar
ou o programa fechar no meio, ao abrir **Audiências** de novo aparece o aviso
"Uma transcrição foi interrompida", com o botão **Recuperar**: o que já tinha
sido transcrito volta para o documento, e a gravação é reparada.

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
- Em **Ajustes › Transcrição** também ficam **Participantes padrão**,
  **Vocabulário da transcrição** (mantenha o texto acentuado: o modelo imita
  a grafia dele) e **Guardar a gravação da audiência**.
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
   como "2ª Vara Cível da Capital". Clique em **Sincronizar**.
3. O Helestron entra no portal e procura a pauta de audiências. Se o portal
   pedir código, a janela de sempre pede que você o digite. Uma faixa no alto
   da tela mostra o andamento, com **Parar**.
4. No fim, um aviso resume o que mudou, por exemplo: "8 audiências
   conferidas · 1 nova, 2 alteradas, 1 saiu da pauta."

O endereço da pauta que funcionou fica **lembrado** na fonte e é usado nas
próximas vezes e pelo monitoramento. Para acrescentar outro portal (o eProc
do mesmo tribunal, por exemplo), use **Ajustes › Pauta › Adicionar fonte**.
**Sincronizar** confere todas as fontes de uma vez; se uma falhar, as outras
seguem.

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
   reconheceu ("12 audiências reconhecidas nesta tela. Total: 12. …").
5. Se a pauta tiver mais de uma página, vá à próxima e capture de novo. As
   repetidas não contam duas vezes.
6. No fim, clique em **Concluir**. A barra confirma ("Pronto: 25 audiências
   gravadas no Helestron. Pode fechar esta janela."), e o endereço fica
   lembrado para o monitoramento.

Se a barra disser "Não encontrei a tabela de audiências nesta tela", abra a
pauta com a lista à vista e clique de novo. O botão **–** recolhe a barra,
se ela atrapalhar. Para desistir, use **Cancelar a captura**, na faixa do
alto da tela Pauta. Sem **Concluir**, o que já foi capturado é gravado quando
você fecha o navegador ou depois de meia hora.

### Importar relatório do SAJ ou do eProc

Se você exporta o relatório de audiências no portal (ou no SAJ instalado no
computador), clique em **Importar relatório** e escolha o arquivo. O
Helestron lê:

- planilhas `.xlsx`, `.xls` (inclusive o ".xls" que, na verdade, é uma página
  HTML), `.ods` e `.csv`;
- páginas `.html`;
- `.pdf` (a tabela é lida pelo texto da página);
- `.docx`.

No fim, aparece **Relatório importado**, com quantas audiências são novas,
quantas foram atualizadas e quantas linhas foram ignoradas (com os avisos,
se houver). Uma audiência que já tinha vindo do portal não é duplicada: o
relatório só completa o que faltava nela.

### A tela da pauta

- **Período**: **Hoje**, **Semana**, **Mês** ou **Período** (de uma data a
  outra). As setas ao lado do período avançam e voltam.
- **Filtros**: sistema (**Todos os sistemas**, e-SAJ, eProc), situação
  (**Todas as situações**, Designada, Realizada, Cancelada, Redesignada, Não
  realizada, Suspensa) e a busca (**Buscar processo, parte ou local**).
- **Resumo**: quatro números, que também servem de filtro rápido: **no
  período**, **hoje**, **nos próximos 7 dias** e **canceladas ou
  redesignadas**.
- **Lista por dia** ("Segunda-feira, 5 de outubro"), com a hora, o número do
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
de antes e o de depois, por exemplo "Hora: 09:00 → 14:30"), **Audiência
cancelada** e **Saiu da pauta** (a audiência que sumiu do portal não é
apagada: fica marcada). O número de alterações não vistas aparece num selo
vermelho em **Pauta**, na barra lateral. Clique em **Marcar como vistas**
depois de conferir; **Ver todas** abre o histórico completo.

Na primeira sincronização de uma fonte, a pauta inteira entra sem aparecer
como alteração.

### Exportar para o Excel

1. Escolha o período e, se quiser, os filtros.
2. Clique em **Exportar Excel**, confira as datas **De** e **Até** e clique
   em **Exportar**.
3. Abra a planilha pelo aviso **Planilha pronta** (**Abrir** ou **Abrir
   pasta**).

A planilha `Pauta de audiências AAAA-MM-DD a AAAA-MM-DD.xlsx` vai para a
pasta da pauta (`Documentos\Helestron\Pauta`), **fora do acervo da IA**. Se o
nome já existir (ou o arquivo estiver aberto no Excel), sai com "(2)". Ela tem
três abas:

- **Pauta**: data, dia da semana, hora, processo, classe, partes, tipo de
  audiência, situação, local, magistrado ou conciliador, sistema, tribunal,
  link e observações, com filtro, cabeçalho fixo, as audiências de hoje
  destacadas e as canceladas riscadas, pronta para imprimir;
- **Resumo**: quantidade por dia, por tipo e por situação;
- **Alterações**: o histórico do período.

**Partes dos processos sigilosos**: por padrão, a coluna Partes dos
processos em segredo de justiça sai como "(segredo de justiça)". Para
mostrá-las, ligue **Incluir as partes dos sigilosos** na janela de
exportação. (A posição inicial desse interruptor vem de **Mostrar as partes
dos processos sigilosos na planilha**, em **Ajustes › Pauta**; o recomendado
é deixá-lo desligado.) O sigilo vale quando o portal indica segredo de
justiça **ou** quando os autos do processo estão na pasta dos sigilosos.

### Monitoramento automático

No quadro **Monitoramento**, o interruptor **Conferir sozinho** ("e avisar o
que mudar"), ligado por padrão, faz o Helestron sincronizar a pauta sozinho, na
**Frequência** escolhida (de "a cada hora" a "a cada 24 horas"; o padrão é a
cada 6 horas), e também ao abrir o programa, se a última conferência já
passou do intervalo. O quadro mostra a **Última sincronização** e a
**Próxima**.

Para o monitoramento funcionar, é preciso:

- **o Helestron aberto**: ele confere a pauta enquanto o programa está
  aberto (pode ficar minimizado);
- **uma fonte com endereço lembrado**, o que acontece depois da primeira
  sincronização bem-sucedida ou de uma captura concluída. Em **Ajustes ›
  Pauta**, cada fonte mostra **Monitorada** ou **Sem rota** (esta ainda fica
  fora do monitoramento);
- **a senha guardada** em **Ajustes › Acessos aos portais**, com
  **Lembrar neste computador** ligado e a entrada por **Usuário e senha**.
  Sem senha guardada, ou com a entrada por certificado ou manual, o
  monitoramento não abre o navegador sozinho, para não surgir uma janela do
  nada.

Se o portal pedir um código de verificação durante a conferência automática,
o Helestron **não fica esperando**: aparece o aviso **"Entre no portal para
continuar o monitoramento"**, também na lista do Início. Clique em
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

- gera o **texto** de cada processo em `_ia\texto\`, com a marca de cada
  página do PDF (`=== [fl. 12] ===`) e o documento a que ela pertence. A IA
  lê texto melhor e mais barato que PDF e consegue indicar a fonte: a folha,
  no e-SAJ, ou o evento e o rótulo do documento (por exemplo, "evento 1,
  INIC1"), no eProc, que não numera folhas;
- escreve o `CLAUDE.md` e o `AGENTS.md` com as **regras de trabalho**:
  indicar a folha ou o evento de cada afirmação, não presumir fatos, não
  inventar julgados, não seguir ordens escritas nos documentos, não alterar
  os originais e gravar o que produzir em `Produtos\`;
- escreve o `INDICE.md`, com tudo o que há no acervo;
- cria a habilidade `acervo-judicial` para o Claude Code.

O botão **Copiar pedido inicial** copia um pedido pronto para colar na
conversa, para a IA começar pelas regras e pelo índice do acervo. O quadro
**Acervo** mostra o caminho da pasta, quantos processos e transcrições há, e
os botões **Abrir a pasta** e **Copiar o caminho**.

### Onde usar o acervo

| Cartão | Botão | O que acontece |
|---|---|---|
| **Claude Code** | **Abrir no Claude Code** | abre o Claude Code numa janela própria, já na pasta do acervo; ele lê sozinho o `CLAUDE.md` e o índice. Se não estiver instalado, abre a página oficial que explica como instalá-lo (sem administrador). Exige plano pago do Claude. |
| **Claude Cowork** | **Abrir no Cowork** | abre o Cowork, no app Claude Desktop, com a pasta do acervo; o Claude pede que você confirme o acesso à pasta. O pedido inicial vai copiado: é só colar (Ctrl+V). Exige o Claude Desktop e plano pago. |
| **Claude Desktop** | **Conectar o acervo** | registra no Claude Desktop o conector **helestron**, com as ferramentas `listar_acervo`, `ler_processo`, `buscar` e `ler_transcricao`, que **só leem**. Feche o Claude Desktop pela bandeja do Windows (perto do relógio) e abra de novo para ele carregar o conector. Depois de conectado, o botão vira **Reconectar o acervo**. |
| **ChatGPT Work** | **Abrir no ChatGPT Work** | copia o caminho do acervo e abre o app do ChatGPT. No modo **Work**, tecle **Ctrl+O** e cole o caminho: o ChatGPT passa a trabalhar na pasta e lê o `AGENTS.md`. O ChatGPT do navegador não lê pastas do computador: instale o app do ChatGPT para Windows ou use o pacote. |
| **Codex** | **Abrir no Codex** | registra o conector do acervo para o Codex (no arquivo `%USERPROFILE%\.codex\config.toml`) e abre o agente da OpenAI numa janela própria, dentro do acervo; ele lê o `AGENTS.md`, com as mesmas regras do Claude. |
| **Pacote para o ChatGPT** | **Gerar o pacote** | monta uma pasta e um `.zip` com os autos, os textos, as transcrições, o índice e as instruções, em `Documentos\Helestron\Pacotes para IA`, para anexar numa conversa ou num Projeto. No fim, o aviso traz o botão **Abrir pasta**. |
| **Nuvem** | **Espelhar agora** | copia o acervo para a subpasta `Helestron - Acervo` da pasta do OneDrive ou do Google Drive escolhida na lista (ou em **Outra pasta…**), para usar a IA pela web e no celular. Só o que mudou é copiado; as gravações das audiências não vão. |

Para que a cópia na nuvem se atualize sozinha, ligue **Espelhar sozinho ao
fim de cada download e de cada transcrição** em **Ajustes › Compartilhar**.

### Regras de sigilo

- O que está na pasta dos sigilosos **nunca** vai para a IA, para o pacote,
  para a nuvem, para o conector ou para o índice.
- Se um processo em segredo de justiça **ficar preso no acervo** (por
  exemplo, o PDF estava aberto quando o download tentou levá-lo para a pasta
  dos sigilosos), o Helestron **suspende** o preparo, o pacote, os botões das
  ferramentas e o espelho na nuvem até ele sair. O Início mostra o aviso
  **Processo sigiloso no acervo**: feche o PDF e mova-o para a pasta dos
  sigilosos.
- O espelho na nuvem apaga a cópia de um processo que depois tenha ido para a
  pasta dos sigilosos; fora isso, não apaga nada do que já está lá.
- A pauta exportada nunca fica no acervo.
- A IA é ferramenta de apoio: resumos e minutas são sugestões para
  conferência e decisão do magistrado.

---

## Ajustes

Os Ajustes são organizados em grupos (o índice fica à esquerda da tela):

| Grupo | O que tem |
|---|---|
| **Acessos aos portais** | usuário e senha de cada portal (**Adicionar acesso**, **Testar**), e o grupo **Como entrar**: modo de entrada no e-SAJ e no eProc, **Esperar o login até (minutos)** e **Perfil do eProc** |
| **Pastas** | **Pasta do acervo**, **Pasta dos processos sigilosos**, **Pasta da pauta exportada** e os **Atalhos** para abri-las |
| **Unidade** | **Como o Helestron chama você** e os dados do cabeçalho das transcrições (**Magistrado(a)**, **Cargo**, **Vara**, **Comarca**, **Tribunal**) |
| **Download** | pular os já baixados, separar os sigilosos, baixar as gravações, mostrar o navegador, **Navegador dos portais** (o padrão usa o Chrome e, sem ele, o Edge), pausa, tentativas, esperas, guardar a imagem da tela quando algo der errado e a montagem do PDF no eProc |
| **Transcrição** | modelos ao vivo e de revisão, revisar ao encerrar, separar as vozes, guardar a gravação, horário de cada fala, participantes padrão, vocabulário, núcleos do processador, a lista **Modelos de transcrição** e a **Separação de falantes** |
| **Pauta** | **Monitorar a pauta**, intervalo, dias para trás e à frente, **Mostrar as partes dos processos sigilosos na planilha** e as **Fontes da pauta** (**Adicionar fonte**, a situação de cada fonte e a lixeira para remover) |
| **Compartilhar** | **Pasta da nuvem**, espelhar sozinho e **Gerar a versão em texto dos autos** |
| **Sobre e diagnóstico** | versão e modo da janela, **Verificar a instalação**, **Abrir os registros**, a lista da verificação e **Encerrar o Helestron** |

Remover uma fonte da pauta não apaga as audiências já trazidas; elas só
deixam de ser conferidas no portal.

---

## Onde ficam os arquivos

| O quê | Onde |
|---|---|
| **Programa** | `%LOCALAPPDATA%\Programs\Helestron\` (ou a pasta escolhida na instalação) |
| **Configuração e registros** | `%LOCALAPPDATA%\Helestron\`: `config.ini` (a configuração), `Logs\` (registros, `diagnostico\` e o relatório da conferência da instalação), `credenciais.json` (senhas cifradas pelo Windows), `perfis\` (perfil do navegador dos portais), `pauta.sqlite3` (a pauta e o histórico de alterações), `modelos\` (modelos de transcrição baixados depois) e `temp\` |
| **Acervo** (compartilhado com a IA) | `Documentos\Helestron\Acervo\`: `Processos\<nome do lote>\` (os PDFs e, em `_controle\`, o relatório), `Transcricoes\` (os DOCX e, em `_audio\`, as gravações), `_ia\` (textos para a IA; pode apagar, é refeito), `Produtos\` (o que a IA produzir), `CLAUDE.md`, `AGENTS.md` e `INDICE.md` |
| **Sigilosos** (nunca compartilhados) | `Documentos\Helestron\Sigilosos\`: `<nome do lote>\` (processos em segredo de justiça) e `Transcricoes\` (as transcrições das audiências deles) |
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

O instalador fecha o Helestron, se estiver aberto (uma audiência em gravação
é salva antes), troca **só o programa**, na mesma pasta da instalação anterior, e
confere a instalação no fim. Configurações, senhas, processos, transcrições e
pauta continuam onde estavam. A versão instalada aparece em **Ajustes › Sobre
e diagnóstico**.

---

## Desinstalar

- **Windows 11:** **Configurações › Aplicativos › Aplicativos instalados**,
  clique nos três pontos ao lado de **Helestron** e em **Desinstalar**.
- **Windows 10:** **Configurações › Aplicativos › Aplicativos e recursos ›
  Helestron › Desinstalar**.

O desinstalador fecha o Helestron, remove o programa e os atalhos e retira o
conector do acervo do Claude Desktop (que, sem o programa, só daria erro).
Depois, ele **pergunta** se você quer apagar também as configurações e as
senhas guardadas (`%LOCALAPPDATA%\Helestron`: configurações, registros,
senhas dos portais, perfis do navegador e a pauta monitorada). A resposta
já vem em **Não**, que é o que convém se você pretende instalar o Helestron
de novo.

A pasta **`Documentos\Helestron`** (processos, transcrições, sigilosos e
pauta exportada) **nunca é apagada**, em nenhum caso.

Para a equipe de informática, a desinstalação silenciosa é:

```bat
"%LOCALAPPDATA%\Programs\Helestron\Desinstalar.exe" /S
```

No modo silencioso, as configurações e as senhas são mantidas.

---

## Problemas comuns

### "O Helestron não pôde abrir" (antivírus)

Se, ao abrir, aparecer a tela **"O Helestron não pôde abrir"**, com a lista
dos arquivos que faltam ou foram alterados, quase sempre o antivírus pôs um
arquivo do programa em quarentena logo depois da instalação, ou a instalação
foi interrompida no meio. **Os seus dados não foram afetados.**

- Clique em **Reparar**: o Helestron procura o instalador
  (`Helestron-Setup-….exe`) na pasta **Downloads** e o abre. Siga o
  assistente: ele conserta a instalação sem apagar nada. Se o instalador não
  estiver lá, a tela explica como baixá-lo de novo na página de versões. (O
  instalador não deixa cópia de si no computador; por isso vale guardá-lo em
  Downloads.)
- **Abrir os registros** abre a pasta com o histórico do programa, útil para
  o suporte.
- Se o problema voltar, peça à equipe de informática que libere, no
  antivírus, a pasta do programa (`%LOCALAPPDATA%\Programs\Helestron`) e
  reinstale.

Se nem essa tela puder ser mostrada, aparece uma caixa de mensagem do
Windows com a mesma orientação.

### A janela abriu no Microsoft Edge

O Helestron usa o componente **WebView2** da Microsoft para desenhar a
própria janela. Se ele faltar ou estiver danificado (Windows 10 sem
atualizações, ou bloqueado pela política da empresa), o Helestron abre no
**Microsoft Edge em modo aplicativo**: uma janela sem barra de endereço,
quase igual. Se nem o Edge abrir, ele usa o navegador padrão, numa aba.

Tudo funciona, com três diferenças:

- para escolher um arquivo, aparece a janela de escolha de arquivo do
  navegador;
- para escolher uma pasta em Ajustes, uma janela pede que você cole o
  caminho da pasta;
- o Helestron encerra pouco depois que você fecha a janela do Edge (no
  máximo, cerca de um minuto).

O modo em uso aparece em **Ajustes › Sobre e diagnóstico** (por exemplo,
"Microsoft Edge em modo aplicativo"). Para voltar à janela própria, peça à
equipe de informática que instale ou repare o **Microsoft Edge WebView2
Runtime** (gratuito, da Microsoft).

### O portal recusou o usuário ou a senha

Confira em **Ajustes › Acessos aos portais** e use **Testar**. Se trocou a
senha no portal, atualize aqui também.

### O portal mudou e o download parou

Os portais mudam de tempos em tempos. Quando algo dá errado numa tela do
portal, o Helestron guarda uma imagem e o HTML da tela em
`%LOCALAPPDATA%\Helestron\Logs\diagnostico` (é o padrão; a opção é
**Guardar imagem da tela quando algo der errado**, em **Ajustes ›
Download**). Envie esses arquivos ao suporte.

Se o **endereço** do eProc do seu tribunal mudou, a mensagem de erro diz onde
corrigi-lo; a equipe de informática pode ajustá-lo no arquivo
`%LOCALAPPDATA%\Helestron\enderecos-locais.json`.

Na **pauta**, se a sincronização deixar de achar a tela, use **Capturar no
portal** ou **Importar relatório** (veja [O que esperar](#o-que-esperar-limites)).

### O medidor do microfone não se mexe

Clique em **Testar** e fale perto do microfone. Se as barras continuarem
paradas:

- confira se o microfone certo está escolhido;
- confira se o Windows permite o acesso ao microfone: em **Configurações ›
  Privacidade e segurança › Microfone** (no Windows 10, **Configurações ›
  Privacidade › Microfone**), ligue o acesso ao microfone e a opção que
  permite aos **aplicativos da área de trabalho** acessar o microfone;
- se aparecer "Nenhum microfone encontrado", confira se ele está conectado.

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

### "Esta tela não abriu"

Se uma seção mostrar "Esta tela não abriu", clique em **Tentar de novo**. Se
continuar, clique em **Verificar a instalação**.

### Algo parou de funcionar depois de uma atualização do Windows

Abra **Ajustes › Sobre e diagnóstico** e clique em **Verificar a
instalação**: a lista mostra cada item ("Em ordem", "Aviso" ou "Falha") e o
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
