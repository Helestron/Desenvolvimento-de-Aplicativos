# Helestron

Programa para Windows, de uso em gabinete judicial, que reúne numa só janela
as tarefas que mais tomam tempo do magistrado e da equipe:

1. **Baixar processos** do **e-SAJ** e do **eProc**, com o login do próprio
   usuário, a partir de uma relação em Excel, Word, PDF, texto ou link: **um
   PDF por processo**, nomeado com o número CNJ, com a **mesma numeração do
   portal**: no e-SAJ, a página N do PDF é sempre a folha N (a folha que não
   veio tem uma página de aviso no lugar, com o motivo); no eProc, sem capa
   nem páginas inseridas, cada documento conserva a paginação própria
   (“evento N, RÓTULO, p. Y”). O PDF leva dentro um manifesto da paginação,
   e a capa completa do processo vai ao lado, em texto e em JSON.
2. **Transcrever audiências ao vivo**, pelo microfone, no próprio computador
   e sem internet: um **DOCX nomeado com o número do processo**, com o
   falante e a hora de cada fala. Gravações de áudio ou vídeo já existentes
   (até 20 GB pelo envio da página, sem limite pelo diálogo do Windows)
   também podem ser transcritas.
3. **Acompanhar a pauta de audiências** do e-SAJ e do eProc: sincronização
   com os portais, captura assistida em qualquer tela, importação do
   relatório, monitoramento das alterações e **exportação para o Excel**.
4. **Compartilhar o acervo com IA** (Claude Code, Claude Cowork, Claude
   Desktop, ChatGPT Work e Codex): texto dos autos com a marca de citação
   de cada página (`fl. N` no e-SAJ; `evento N, RÓTULO, p. Y` no eProc),
   regras de trabalho (`CLAUDE.md`/`AGENTS.md`, mantidos em dia), conector
   MCP só de leitura, pacote para o ChatGPT e espelho no OneDrive ou no
   Google Drive.
5. **Automação pela linha de comando**, para scripts e para skills do
   Claude Code: `baixar` com acompanhamento em JSON, eventos legíveis por
   máquina, retomada do que falhou e códigos de saída estáveis
   (veja [docs/INTEGRACAO-CLAUDE.md](docs/INTEGRACAO-CLAUDE.md)).

Processos em **segredo de justiça** ficam numa pasta própria, **fora** do
acervo, e nunca vão para a IA, para o pacote, para a nuvem nem para o
conector. A regra é uma só, no download, na transcrição e no
compartilhamento: é sigiloso o processo com autos, transcrição ou gravação
na pasta dos sigilosos, ou que a pauta de audiências marca em segredo de
justiça (só a indicação positiva conta, como o selo “Segredo de Justiça”;
“Nível 1” no local da audiência ou “Segredo de justiça: não” não marcam), e
também o incidente de um processo sigiloso. Com a separação dos sigilosos
ligada (o padrão), o que ainda estiver no acervo de um processo sigiloso é
levado para a pasta dos sigilosos antes de o acervo ser entregue a qualquer
ferramenta; quando é a pauta que revela o segredo, isso acontece na hora, com
um aviso. O Helestron é a reconstrução do antigo **Assessor Integrado**, com
instalador de um só arquivo, interface nova e a pauta de audiências.

> O Helestron é ferramenta de apoio: autos, transcrições, pautas e o que a IA
> produzir são material de trabalho para conferência e decisão do magistrado
> (Resolução CNJ nº 615/2025).

## Instalação

1. Baixe o **`Helestron-Setup-1.0.2.exe`** na
   [página de versões](https://github.com/Helestron/Desenvolvimento-de-Aplicativos/releases)
   (a versão mais recente, em **Assets**).
2. Dê dois cliques no arquivo. Se o Windows mostrar “O Windows protegeu o
   computador”, clique em **Mais informações** e em **Executar assim
   mesmo**: o aviso aparece porque o instalador ainda não é assinado
   digitalmente.
3. Siga o assistente (**Próximo**, **Instalar**, **Concluir**) e abra o
   Helestron pelo atalho. Na primeira vez, cadastre o acesso aos portais em
   **Ajustes › Acessos aos portais**.

A instalação é **offline** (Python, bibliotecas e modelo de transcrição vão
dentro do instalador), **sem administrador** (por usuário, em
`%LOCALAPPDATA%\Programs\Helestron`) e termina com uma **conferência** de
todos os arquivos. O programa nunca se mistura com outros arquivos: se a
pasta escolhida já tiver coisas de outro programa ou do usuário, ele vai
para uma pasta própria dentro dela (`<pasta>\Helestron`), e a atualização e
o desinstalador apagam só o que a instalação pôs lá, um arquivo por vez,
pela lista `arquivos-instalados.txt`. Para quem usava o Assessor Integrado,
o instalador tira o atalho antigo e os conectores antigos do Claude Desktop
e do Codex. Numa atualização, uma audiência sendo transcrita nunca é
interrompida (o instalador pede que ela seja encerrada antes), e o conector
do acervo aberto pelo Claude Desktop ou pelo Codex não trava a cópia. Para a
equipe de informática, há o modo silencioso,
`Helestron-Setup-1.0.2.exe /S [/D=pasta]` (com `/D=` numa pasta que já tem
outros arquivos, o Helestron vai para `<pasta>\Helestron`), com códigos de
saída próprios: 0 (instalado), 2 (a conferência encontrou problema), 3 (a
pasta escolhida e a subpasta `Helestron` dentro dela já têm arquivos de
outro programa ou do usuário: nada foi copiado), 4 (o Helestron não
fechou), 5 (outro instalador aberto), 6 (Windows incompatível), 7 (audiência
em andamento: nada foi alterado), 8 (sem permissão na pasta) e 9 (instalado,
mas falta o WebView2 Runtime para abrir a janela). Instalar numa pasta
diferente da registrada **muda** o programa de pasta: o Helestron da pasta
anterior é fechado e removido, como numa atualização.

O PATH não é alterado. Para a linha de comando, a pasta do programa traz o
`helestron.cmd` (`"%~dp0python.exe" -I -m helestron %*`, que devolve o
código de saída do programa), e a chave `HKCU\Software\Helestron` do
registro guarda `Python` (o `python.exe` da pasta do programa), `Versao` e
`InstallLocation`: é assim que scripts e skills do Claude acham o programa.

O desinstalador retira os conectores do acervo do Claude Desktop e do
Codex/ChatGPT Work, remove só os arquivos do programa, apaga sempre as
sessões dos portais e os perfis do navegador (`%LOCALAPPDATA%\Helestron\perfis`)
e os valores de `HKCU\Software\Helestron`, pergunta antes de apagar
configurações e senhas e nunca apaga `Documentos\Helestron`.

O passo a passo completo, com cada função, os ajustes, a desinstalação e os
problemas comuns, está no **[manual do usuário](docs/MANUAL.md)**.

### Requisitos

- Windows 10 (versão 1809 ou mais recente) ou Windows 11, **64 bits**;
- cerca de 1 GB livre em disco para o programa;
- Google Chrome ou Microsoft Edge (o Edge já vem no Windows), para os
  portais;
- Microsoft Edge WebView2 Runtime 101 ou mais recente, que já vem no
  Windows 11 e no Windows 10 atualizado (sem ele, ou com um mais antigo, o
  Helestron abre no Edge em modo aplicativo e, sem o Edge, no navegador
  padrão, nunca no Internet Explorer; sem nenhum deles, explica como
  instalar o WebView2 em vez de abrir uma janela em branco);
- microfone, para a transcrição;
- acesso aos portais (e-SAJ e eProc) para baixar processos e ler a pauta.

## Estrutura do repositório

```
README.md                         esta apresentação
docs/MANUAL.md                    manual do usuário
docs/ESPECIFICACAO.md             especificação técnica (referência de comportamento)
docs/INTEGRACAO-CLAUDE.md         como uma skill do Claude Code (ou um script) chama o Helestron
helestron/                        o pacote Python (vai inteiro para o instalador)
  __main__.py                     linha de comando: python -m helestron ...
  aplicativo/                     abertura, janela (WebView2), instância única, integridade, autoteste
  servidor/                       servidor HTTP local (127.0.0.1), API, eventos e perguntas
  servicos.py  tarefas.py         ponte entre a API e o motor
  nucleo/                         caminhos, configuração, cofre de senhas, tribunais, listas, sigilo,
                                  argumentos da linha de comando (em português)
  download/                       download no e-SAJ e no eProc (Playwright, Chrome ou Edge)
  transcricao/                    transcrição ao vivo e de gravações (faster-whisper)
  compartilhar/                   preparo do acervo, Claude, ChatGPT, conector MCP, nuvem
  pauta/                          pauta de audiências (sincronização, captura, importação, Excel)
  verificar.py                    diagnóstico da instalação
  dados/                          tribunais.json, pauta.json
  recursos/                       ícone e imagens do instalador
  web/                            a interface (HTML, CSS e JavaScript puros, sem CDN)
testes/                           testes (unittest), em Linux e no Windows
construir/                        construção do instalador
  construir.py                    as oito etapas, do Python para Windows ao Setup.exe
  marca.py                        gera o ícone e as imagens da marca
  requisitos-*.in / .txt          dependências, travadas com hash
  instalador/helestron.nsi        modelo do script NSIS
  lancador/                       o Helestron.exe (C, compilado com MinGW); o helestron.cmd
                                  é gerado pelo construir.py
.github/workflows/helestron.yml   CI: testes, construção, instalação real no Windows, publicação
```

## Desenvolver e testar

Os testes rodam em Linux, sem rede e sem Windows; o que é só do Windows é
pulado. Com Python 3.12:

```bash
sudo apt-get install -y libportaudio2 libsndfile1 xvfb
python -m pip install --require-hashes -r construir/requisitos-teste.txt
python -m playwright install --with-deps chromium   # testes da interface

xvfb-run -a python -m unittest discover -s testes -t .
xvfb-run -a python -m unittest testes.test_pauta_servico     # um módulo só
```

Os testes não tocam na pasta pessoal: o programa usa as variáveis
`HELESTRON_LOCAL` (configuração, registros, senhas) e `HELESTRON_DADOS`
(acervo, sigilosos, pauta), que podem apontar para pastas temporárias também
quando você roda o programa à mão.

Para ver a interface:

```bash
# modo demonstração: o demo.js responde a toda a API, sem servidor
python -m http.server -d helestron/web 8000
#   http://127.0.0.1:8000/?demo=1
#   variantes: &pauta=vazia, &sem_dialogo=1, &lote=falhas,
#              &claude_code=ausente, &microfone=<nome>, &presenca=certificado,
#              &modo=edge (ou navegador), &falantes=ausentes

# o servidor de verdade, sem janela: imprime URL=... para abrir no navegador
python -m helestron --servidor --sem-janela
```

Outros comandos úteis: `python -m helestron --ajuda` lista a linha de
comando inteira (`baixar`, `transcrever`, `pauta sincronizar|exportar|importar|listar|fontes`,
`mcp`, `verificar`, `preparar`, `caminhos`, `--version`,
`--verificar-instalacao`, `--autoteste`…), e cada comando tem a própria
ajuda (`python -m helestron <comando> -h`). A ajuda e as mensagens de erro
saem em português (por exemplo, “erro: argumento não reconhecido: --xyz”),
com o código de saída 2 nos erros de uso. O `--autoteste PASTA` abre a
janela de verdade, percorre as telas e salva as capturas em `PASTA`, sempre
em pastas de dados temporárias e vazias: as imagens nunca mostram a
configuração, a pauta ou o acervo de quem o roda.

Para automação (scripts, a skill do Claude), a linha de comando é estável e
legível por máquina:

- `caminhos --json`: onde ficam o acervo, os sigilosos, a pauta, a
  configuração e os registros, o Python do programa, o modo de entrada em
  cada portal e a lista `recursos` do que esta versão oferece (não cria
  nada; não expõe senhas, perfis nem sessões);
- `baixar` com `--json ARQ` (andamento e resultado em JSON, formato
  `helestron.baixar/1`, descrito em `helestron/download/acompanhamento.py`),
  `--eventos` (linhas `HELESTRON-EVENTO {…}`), `--log ARQ`, `--texto`,
  `--retomar`, `--completar J.TR.OOOO`, `--esperar-navegador MIN`,
  `--rebaixar-incompletos`, `--sem-cofre` e `--desanexar`; o relatório do
  lote ganhou, no fim, a coluna `causa`, e cada PDF tem ao lado o
  `_controle\<número>_meta.json`. Códigos de saída: 0 tudo certo, 1 parte
  falhou ou ficou pendente, 2 nada pôde ser feito;
- `preparar [--sem-texto] [--json]` (0, 1, 2 ou 3, autos de processo
  sigiloso presos no acervo) e `preparar --pasta PASTA [--texto-em DIR]
  [--incluir-sigilosos] [--json]`, só o texto dos autos de uma pasta de
  lote.

O guia completo está em [docs/INTEGRACAO-CLAUDE.md](docs/INTEGRACAO-CLAUDE.md).

Regras do projeto (detalhes em [docs/ESPECIFICACAO.md](docs/ESPECIFICACAO.md)):
código, comentários e textos em português do Brasil correto; nenhuma
dependência nova sem necessidade; imports estáticos nas partes essenciais;
os invariantes de sigilo (seção 12 da especificação) não podem regredir.

## Construir o instalador

`construir/construir.py` gera `dist/Helestron-Setup-<versão>.exe` e o
`.sha256`. Roda em Linux (e no CI) e no Windows e precisa de Python 3.12 com
`installer` e `pillow`, do MinGW-w64 e do NSIS:

```bash
sudo apt-get install -y mingw-w64 nsis
python -m pip install installer pillow
python construir/construir.py --modelo PASTA  # o faster-whisper-small em int8 (veja COMANDOS_CONVERSAO em construir.py)
python construir/construir.py --sem-modelo    # sem o modelo (baixado no primeiro uso)
python construir/construir.py --versao        # só imprime a versão que será construída
```

Uma das duas, `--modelo PASTA` ou `--sem-modelo`, é obrigatória. O modelo
tem de estar já convertido para int8 (o `model.bin` com ~250 MB): o
publicado no Hugging Face é float16, e com ele o instalador passaria de
500 MiB, o limite para entrega por anexo. Os comandos da conversão, os
mesmos do CI, estão em `COMANDOS_CONVERSAO`, no `construir.py`, que recusa
um `model.bin` fora da faixa do int8 e um Setup acima de 500 MiB.

As oito etapas: (1) Python 3.12 para Windows (python-build-standalone,
SHA-256 conferido); (2) rodas `win_amd64`/`cp312` de
`requisitos-windows.txt`, travadas com hash; (3) instalação das rodas e do
pacote `helestron` inteiro; (4) limpeza e pré-compilação dos `.pyc`; (5)
modelo de transcrição e modelos de voz (a falha ao obter os modelos de voz
interrompe a construção, salvo com `--sem-falantes`); (6) lançadores: o
`Helestron.exe` e o `helestron.cmd`, a linha de comando; (7)
`manifesto.json` com os componentes embutidos e o tamanho e o SHA-256 de
cada arquivo; (8) a lista do que a instalação põe na pasta do programa
(`arquivos-instalados.txt`), o script NSIS e o `makensis`. Outras opções:
`--sem-falantes`, `--saida`, `--cache` (downloads reaproveitados),
`--python-tar` e `--marca` (gera de novo o ícone e as imagens).

## Integração contínua

O workflow [`.github/workflows/helestron.yml`](.github/workflows/helestron.yml)
roda a cada envio:

- **Testes (Linux):** a suíte inteira, com a interface no Chromium em modo
  demonstração; as capturas de tela viram artefato.
- **Construir o instalador:** NSIS e MinGW no Ubuntu. Primeiro, numa tag,
  confere que ela é `v<versão do programa>` (`construir.py --versao`);
  depois converte o whisper-small oficial para int8 (os mesmos comandos de
  `COMANDOS_CONVERSAO`), constrói com `--modelo` e confere que o Setup.exe
  cabe em 500 MiB; o Setup.exe vira artefato.
- **Instalação real no Windows:** num Windows limpo, faz o que o usuário faz:
  confere o SHA-256, simula os restos do Assessor Integrado (o atalho e o
  conector antigos, ao lado de um atalho de mesmo nome e de um conector que
  não são dele), instala em silêncio numa pasta com espaço e acento,
  confere arquivos (inclusive o `helestron.cmd` e os modelos de voz),
  atalhos e registro (a chave de desinstalação e `HKCU\Software\Helestron`,
  e que o PATH não mudou; e que só os restos antigos saíram), roda
  `--verificar-instalacao`, chama a linha de comando como a skill do Claude
  a chama (pelo `helestron.cmd` e pelo Python do registro: `--version`,
  `caminhos --json`, `baixar --help`, uma opção inválida com o código 2 e
  `pauta listar --json`), abre a janela de verdade (`--autoteste`, com
  capturas), transcreve uma fala sintetizada, conversa com o conector MCP,
  importa e exporta a pauta, usa o cofre de senhas (DPAPI), reinstala por
  cima com o conector MCP aberto (os arquivos presos vão para `.antigos`, e
  a limpeza fica agendada) e desinstala, conferindo que os documentos do
  usuário e a configuração ficaram, que as sessões dos portais, a chave
  `HKCU\Software\Helestron` e os conectores do Claude Desktop e do Codex
  saíram. Por fim, instala e desinstala numa pasta que já tem arquivos do
  usuário (com pastas `Lib`, `Scripts`, `share` e `modelos` dele),
  conferindo que o Helestron foi para a subpasta própria e que nada do
  usuário saiu. As capturas da janela real também vão para o registro,
  reduzidas e em base64.
- **Publicar a versão:** nas tags `v*`, depois dos testes e da instalação no
  Windows, cria a versão no GitHub com o instalador e o `.sha256`. A versão
  sai do nome do único `Helestron-Setup-*.exe` testado, e uma tag diferente
  dela reprova a publicação.

## Licenças de terceiros

O instalador leva componentes de terceiros, cada um com a sua licença; as
das bibliotecas Python vão junto, nas pastas `*.dist-info` de
`Lib\site-packages`, na pasta do programa. Os principais:

| Componente | Licença |
|---|---|
| Fonte Inter (`helestron/web/fontes`, com a licença ao lado) | SIL Open Font License 1.1 |
| Python 3.12 | Python Software Foundation License |
| faster-whisper, CTranslate2 e o modelo faster-whisper-small (derivado do Whisper, da OpenAI) | MIT |
| ONNX Runtime | MIT |
| sherpa-onnx | Apache 2.0 |
| Modelos de voz da separação de falantes (pyannote segmentation 3.0; 3D-Speaker ERes2Net) | MIT; Apache 2.0 |
| PyMuPDF | GNU AGPL 3.0 (ou licença comercial da Artifex) |
| pypdf, python-docx, openpyxl, xlrd | BSD / MIT |
| Playwright | Apache 2.0 |
| pywebview, pythonnet, bottle | BSD / MIT |
| NumPy, Pillow, PyAV, sounddevice, soundfile | BSD / MIT e afins (o PyAV traz o FFmpeg, LGPL) |
| requests, huggingface_hub | Apache 2.0 |
| msvc-runtime (bibliotecas do Visual C++) | licença de redistribuição da Microsoft |
