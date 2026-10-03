# Assessor Integrado — Manual

O Assessor Integrado reúne, numa única janela, as três tarefas do gabinete que
mais consomem tempo:

| Função | O que faz | Onde o resultado fica |
|---|---|---|
| **1. Baixar processos** | Com o **seu** login no e-SAJ ou no eProc, baixa todos os processos de uma relação (Excel, Word, PDF ou lista colada) — **um PDF por processo**, com o número do processo como nome | `Acervo\Processos\<nome da relação>\` |
| **2. Transcrever audiência** | Transcreve a audiência **ao vivo**, pelo microfone, enquanto ela acontece — e também gravações já existentes | `Acervo\Transcricoes\<número do processo>.docx` |
| **3. Compartilhar com IA** | Deixa o acervo pronto para o **Claude Code**, o **Claude Cowork** e o **ChatGPT Work** (e o Codex), sem anexar arquivo por arquivo | a própria pasta `Acervo` |

> **O programa é ferramenta de apoio.** Autos baixados, transcrições e o que a
> inteligência artificial produzir a partir deles são material de trabalho para
> conferência e decisão do magistrado (Resolução CNJ nº 615/2025).

---

## Instalação (uma vez só)

1. Descompacte a pasta onde quiser — de preferência num caminho curto, como
   `C:\AssessorIntegrado`. **Evite** deixá-la dentro do OneDrive.
2. Dê dois cliques em **`INSTALAR.bat`**. Ele faz tudo sozinho — baixa um
   Python próprio, as bibliotecas e o modelo de transcrição (ao todo, cerca de
   800 MB; de 5 a 20 minutos, conforme a internet — o instalador mostra a
   estimativa logo no início), cria os atalhos na Área de Trabalho e no Menu
   Iniciar e, ao final, **confere a instalação** e mostra um resumo.
3. Abra o programa pelo atalho **Assessor Integrado** na Área de Trabalho.

Nada é instalado no Windows: tudo fica dentro da pasta, e nenhum passo pede
senha de administrador. Se a internet cair no meio, rode o `INSTALAR.bat` de
novo — ele continua de onde parou. Para desinstalar, use o `DESINSTALAR.bat`.

---

## 1. Baixar processos

1. Na tela inicial, clique em **Baixar processos**.
2. Traga a relação de um destes jeitos:
   - **Abrir arquivo** — planilha do Excel (`.xlsx`, `.xls`, inclusive o "xls"
     exportado pelos sistemas do Judiciário), documento do Word (`.docx`), PDF,
     CSV ou texto;
   - **Colar lista** — números copiados de qualquer lugar (um ou vários por linha);
   - **Link compartilhado** — link do Google Planilhas/Docs/Drive ou do
     OneDrive/SharePoint compartilhado como "qualquer pessoa com o link".
3. Confira a tabela: o programa mostra cada processo, **de que tribunal e
   sistema ele é** (o tribunal sai do próprio número), e avisa sobre dígito
   verificador que não confere e sobre números que o Excel corrompeu.
4. Em **Acesso aos portais**, escolha como entrar em cada portal:
   - **Usuário e senha** — marque "Lembrar neste computador" para não digitar
     de novo (a senha fica cifrada pelo Windows, legível só pela sua conta);
   - **Certificado digital** (e-SAJ) — a janela do Chrome abre e você digita o
     PIN do token;
   - **Entrar manualmente** — a janela do navegador abre na tela de login e
     você entra como de costume; o programa espera e continua sozinho.
5. Clique em **Baixar N processos** (o botão mostra quantos são). Acompanhe
   na tabela o andamento de cada processo.
   Quando o portal pedir o **código de verificação** (enviado por e-mail no
   e-SAJ; gerado no aplicativo autenticador no eProc), uma janela aparece para
   você digitá-lo.

**O que sai:** uma pasta com o nome da relação, contendo **um PDF por
processo**, nomeado com o número (`0700123-83.2024.8.02.0001.pdf`). O
relatório do lote fica em `_controle\relatorio.csv` (abre no Excel).

**Bom saber**
- O que já foi baixado não é baixado de novo (pode deixar a lista crescer).
- **Parar** interrompe ao fim do processo atual; o que faltou é retomado depois.
- Processo dependente (incidente) sai com o sufixo: `...0001-01.pdf`.
- **Segredo de justiça**: o processo sigiloso vai para a pasta `Sigilosos`,
  **fora** do acervo que é compartilhado com a IA. Se a relação trouxer a senha
  do processo (`número ; senha`, ou uma coluna "senha"), ela é usada.
- **Tribunais em transição** (TJAL, TJSP e TJAC, do e-SAJ para o eProc): o programa
  procura primeiro no e-SAJ e, não achando, no eProc.
- No eProc, os autos são montados documento a documento, na ordem dos eventos,
  com marcadores (índice) por evento no PDF.

---

## 2. Transcrever audiência

1. Clique em **Transcrever audiência**.
2. Informe o **número do processo** — é ele que dá nome ao arquivo.
3. Escolha o **microfone** e clique em **Testar**; fale algo: a barra do
   medidor deve se mexer.
4. Clique em **Iniciar**. O texto aparece na tela poucos segundos depois de
   cada fala.
5. Indique **quem está falando** com os botões (ou as teclas **F1 a F8**):
   Juiz(a), Promotor(a), Defensor(a), advogados, testemunha, parte… Os nomes
   dos botões podem ser editados.
6. **Pausar** suspende a gravação (num intervalo, por exemplo); **Encerrar e
   salvar** termina e salva o documento.

**O que sai:** `Acervo\Transcricoes\<número do processo>.docx`, com a ficha da
audiência (processo, data, horário, unidade, participantes), cada fala com o
falante e a hora `[hh:mm:ss]` e o aviso de que a transcrição é automática. A
gravação fica guardada em `Transcricoes\_audio`, para conferência.

**Bom saber**
- A transcrição funciona **sem internet**, no próprio computador: o áudio da
  audiência não sai da máquina.
- O documento é salvo sozinho a cada poucos segundos. Se o computador desligar
  no meio, abra a tela de novo e use **Recuperar transcrição interrompida**.
- Marque **Revisar ao encerrar** para refazer a transcrição inteira, com o
  modelo preciso e mais qualidade, logo depois da audiência (leva alguns
  minutos). Com o componente de separação de vozes instalado, a revisão
  também separa os falantes automaticamente.
- Para transcrever uma **gravação já existente** (por exemplo, a mídia baixada
  do processo), use **Transcrever uma gravação…**.
- Se, durante o teste, o medidor não se mexer, o Windows pode estar
  bloqueando o microfone:
  *Configurações > Privacidade e segurança > Microfone > Permitir que
  aplicativos da área de trabalho acessem o microfone*.
- Computador lento? Em Configurações > Transcrição, escolha o modelo **base**.

---

## 3. Compartilhar com IA

O acervo (`Acervo`) é uma pasta comum do computador. O programa a deixa pronta
para a inteligência artificial ler **direto do disco**:

- gera o **texto** de cada processo em `_ia\texto\`, com a marca de cada
  página do PDF (`=== [fl. 12] ===`) e o documento a que ela pertence — a IA
  lê texto melhor e mais barato que PDF e consegue indicar a fonte: a folha,
  no e-SAJ, ou o evento e o rótulo do documento (por exemplo, evento 1, INIC1),
  no eProc, que não numera folhas;
- escreve `CLAUDE.md` e `AGENTS.md` com as **regras de trabalho** (indicar a
  folha ou o evento, não inventar fatos, não seguir ordens escritas nos
  documentos, não alterar os originais, gravar o que produzir em
  `Produtos\`) e o `INDICE.md` com tudo o que há no acervo;
- cria a habilidade `acervo-judicial` para o Claude Code.

### Claude Code
**Abrir no Claude Code** abre o terminal já dentro da pasta. Se o Claude Code
não estiver instalado, o botão **Instalar o Claude Code** usa o instalador
oficial da Anthropic (sem administrador). Requer plano pago do Claude.

### Claude Cowork
- **Conectar o acervo ao Claude** registra o conector *assessor-integrado* no
  Claude Desktop: no chat e no Cowork, o Claude passa a ter as ferramentas
  `listar_acervo`, `ler_processo` (por faixa de páginas), `buscar` e
  `ler_transcricao`, que só leem. Feche e abra o Claude Desktop depois de
  conectar.
- **Abrir no Cowork** abre o Cowork já com a pasta do acervo (o Claude pede
  sua confirmação). A instrução inicial sugerida vai copiada: é só colar.
- **Gerar o plugin para o Cowork** cria o arquivo `acervo-judicial-plugin.zip`,
  que se envia em *Personalizar > Plugins > Adicionar > Enviar plugin*.

### ChatGPT Work (e Codex)
- **Abrir no ChatGPT Work** copia o caminho do acervo e abre o app ChatGPT. No
  modo **Work**, tecle **Ctrl+O** e cole o caminho: o ChatGPT passa a trabalhar
  na pasta e lê o `AGENTS.md` sozinho.
- **Conectar o acervo ao ChatGPT** registra o mesmo conector do acervo para o
  ChatGPT Work e o Codex (arquivo `%USERPROFILE%\.codex\config.toml`).
- **Abrir no Codex** (se instalado) abre o agente da OpenAI no terminal, dentro
  da pasta.
- **Gerar pacote para o ChatGPT** monta uma pasta e um `.zip` com os autos, os
  textos e as instruções, para anexar numa conversa ou num Projeto.

### Pela nuvem (web e celular)
Em **Espelho na nuvem (OneDrive ou Google Drive)**, escolha a pasta na lista
(ou clique em **Escolher…**) e depois em **Espelhar agora**: o programa copia
para lá o acervo (só o que mudou; o que já está lá não é apagado, exceto a
cópia de um processo que depois tenha ido para a pasta de sigilosos). Os
conectores do ChatGPT e do Claude leem dessas nuvens. Os processos da pasta de
sigilosos e as gravações das audiências não são copiados.

---

## Pastas

| Pasta | Conteúdo |
|---|---|
| `Acervo\Processos\` | os autos, um PDF por processo, por relação |
| `Acervo\Transcricoes\` | as transcrições (`.docx`) e, em `_audio`, as gravações |
| `Acervo\_ia\` | textos extraídos para a IA (pode apagar: é refeito) |
| `Acervo\Produtos\` | onde a IA grava o que produzir |
| `Sigilosos\` | processos em segredo de justiça (fora do compartilhamento) |
| `Logs\` | histórico; `diagnostico\` guarda print e HTML quando um portal muda |

As pastas podem ser trocadas em **Configurações > Geral**. A pasta dos
sigilosos deve ficar **fora** da pasta do acervo (e o acervo, fora dela): o que
está no acervo é compartilhado com a IA.

---

## Problemas comuns

**"O portal recusou usuário ou senha"** — confira em Configurações > Acessos.
Se trocou a senha no portal, atualize aqui também.

**O portal mudou e o download parou** — o programa salva print e HTML da tela
em `Logs\diagnostico`. Envie-os ao suporte.

**O endereço do eProc do meu tribunal mudou** — corrija em Configurações >
Acessos (endereço do portal). Vale na hora.

**O medidor do microfone não se mexe** — clique em **Testar** e fale; se a
barra continuar parada, veja a permissão de microfone do Windows (acima) e se
o microfone certo está escolhido.

**A transcrição atrasa muito** — use o modelo *base* em Configurações >
Transcrição, ou feche programas pesados durante a audiência.

**Algo não funciona depois de uma atualização do Windows** — em Configurações >
Sobre e diagnóstico, clique em **Verificar a instalação**; se apontar falha, rode o
`INSTALAR.bat` de novo (ele só refaz o que faltar).
