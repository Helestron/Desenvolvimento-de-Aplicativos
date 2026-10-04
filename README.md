# Helestron

Programa para Windows, de uso em gabinete judicial, que reúne numa só janela
as tarefas que mais tomam tempo do magistrado e da equipe:

1. **Baixar processos** do **e-SAJ** e do **eProc**, com o login do próprio
   usuário, a partir de uma relação em Excel, Word, PDF, texto ou link: **um
   PDF por processo**, nomeado com o número CNJ.
2. **Transcrever audiências ao vivo**, pelo microfone, no próprio computador
   e sem internet: um **DOCX nomeado com o número do processo**, com o
   falante e a hora de cada fala. Gravações já existentes também podem ser
   transcritas.
3. **Acompanhar a pauta de audiências** do e-SAJ e do eProc: sincronização
   com os portais, captura assistida em qualquer tela, importação do
   relatório, monitoramento das alterações e **exportação para o Excel**.
4. **Compartilhar o acervo com IA** (Claude Code, Claude Cowork, Claude
   Desktop, ChatGPT Work e Codex): texto dos autos marcado por folha ou
   evento, regras de trabalho (`CLAUDE.md`/`AGENTS.md`), conector MCP só de
   leitura, pacote para o ChatGPT e espelho no OneDrive ou no Google Drive.

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

1. Baixe o **`Helestron-Setup-1.0.1.exe`** na
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
`Helestron-Setup-1.0.1.exe /S [/D=pasta]` (com `/D=` numa pasta que já tem
outros arquivos, o Helestron vai para `<pasta>\Helestron`), com códigos de
saída próprios: 0 (instalado), 2 (a conferência encontrou problema), 3 (a
pasta escolhida e a subpasta `Helestron` dentro dela já têm arquivos de
outro programa ou do usuário: nada foi copiado), 4 (o Helestron não
fechou), 5 (outro instalador aberto), 6 (Windows incompatível), 7 (audiência
em andamento: nada foi alterado), 8 (sem permissão na pasta) e 9 (instalado,
mas falta o WebView2 Runtime para abrir a janela). O desinstalador retira os
conectores do acervo do Claude Desktop e do Codex/ChatGPT Work, remove só os
arquivos do programa e nunca apaga `Documentos\Helestron`.

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
  lancador/                       o Helestron.exe (C, compilado com MinGW)
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
comando inteira (`baixar`, `transcrever`, `pauta sincronizar|exportar|importar`,
`mcp`, `verificar`, `--verificar-instalacao`, `--autoteste`…), e cada comando
tem a própria ajuda (`python -m helestron <comando> -h`). A ajuda e as
mensagens de erro saem em português (por exemplo, “erro: argumento não
reconhecido: --xyz”), com o código de saída 2 nos erros de uso. O
`--autoteste PASTA` abre a janela de verdade, percorre as telas e salva as
capturas em `PASTA`, sempre em pastas de dados temporárias e vazias: as
imagens nunca mostram a configuração, a pauta ou o acervo de quem o roda.

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
python construir/construir.py                 # baixa o modelo do Hugging Face
python construir/construir.py --sem-modelo    # sem o modelo (baixado no primeiro uso)
```

As oito etapas: (1) Python 3.12 para Windows (python-build-standalone,
SHA-256 conferido); (2) rodas `win_amd64`/`cp312` de
`requisitos-windows.txt`, travadas com hash; (3) instalação das rodas e do
pacote `helestron`; (4) limpeza e pré-compilação dos `.pyc`; (5) modelo de
transcrição e modelos de voz; (6) lançador `Helestron.exe`; (7)
`manifesto.json` com o tamanho e o SHA-256 de cada arquivo; (8) a lista do
que a instalação põe na pasta do programa (`arquivos-instalados.txt`), o
script NSIS e o `makensis`. Outras opções: `--modelo PASTA` (modelo já baixado),
`--sem-falantes`, `--saida`, `--cache` (downloads reaproveitados),
`--python-tar` e `--marca` (gera de novo o ícone e as imagens).

## Integração contínua

O workflow [`.github/workflows/helestron.yml`](.github/workflows/helestron.yml)
roda a cada envio:

- **Testes (Linux):** a suíte inteira, com a interface no Chromium em modo
  demonstração; as capturas de tela viram artefato.
- **Construir o instalador:** NSIS e MinGW no Ubuntu, com o modelo de
  transcrição baixado do Hugging Face; o Setup.exe vira artefato.
- **Instalação real no Windows:** num Windows limpo, faz o que o usuário faz:
  confere o SHA-256, simula os restos do Assessor Integrado (o atalho e o
  conector antigos, ao lado de um atalho de mesmo nome e de um conector que
  não são dele), instala em silêncio numa pasta com espaço e acento,
  confere arquivos, atalhos e registro (e que só os restos antigos saíram),
  roda `--verificar-instalacao`, abre a
  janela de verdade (`--autoteste`, com capturas), transcreve uma fala
  sintetizada, conversa com o conector MCP, importa e exporta a pauta, usa o
  cofre de senhas (DPAPI), reinstala por cima com o conector MCP aberto (os
  arquivos presos vão para `.antigos`, e a limpeza fica agendada) e
  desinstala, conferindo que os documentos do usuário ficaram e que os
  conectores do Claude Desktop e do Codex saíram. Por fim, instala e
  desinstala numa pasta que já tem arquivos do usuário (com pastas `Lib`,
  `Scripts`, `share` e `modelos` dele), conferindo que o Helestron foi para a
  subpasta própria e que nada do usuário saiu. As capturas da janela real
  também vão para o registro, reduzidas e em base64.
- **Publicar a versão:** nas tags `v*`, depois dos testes e da instalação no
  Windows, cria a versão no GitHub com o instalador e o `.sha256`.

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
