# Helestron — especificação técnica (versão 1.0.0)

Documento de referência para a reconstrução do antigo "Assessor Integrado" como
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
   rodou) e o erro **"Esta parte do programa não abriu — No module named
   'app.interface.pagina_config'"**.
7. Ícone com a letra **"H"**, design moderno, cores **navy e cinza**, com
   **efeito de transparência**.
8. Tudo disponível para download no Claude e copiado para o GitHub, substituindo
   todo o conteúdo do repositório.

## 2. Diagnóstico da versão anterior e como o Helestron o elimina

| Problema | Causa | Solução no Helestron |
|---|---|---|
| Instalação por `INSTALAR.bat` + PowerShell, baixando ~800 MB na hora | rede do tribunal (proxy, bloqueio de PyPI/Hugging Face), GPO que bloqueia scripts, janela de console | **Um só `Helestron-Setup-1.0.0.exe`** (NSIS, assistente gráfico em português), **offline**: Python, bibliotecas e modelo de transcrição vão dentro. Sem PowerShell, sem console, sem administrador. |
| `No module named 'app.interface.pagina_config'` | um arquivo do programa sumiu depois da extração (antivírus que põe em quarentena arquivo que lida com senhas, extração parcial) e as telas eram importadas por nome em tempo de execução (`importlib`) | (a) interface em HTML: não há mais módulo Python por tela; (b) **imports estáticos** em todo o pacote; (c) **manifesto de integridade** conferido na abertura, com mensagem clara e botão "Reparar"; (d) o instalador roda `Helestron.exe --verificar-instalacao` ao final e avisa se algo faltar; (e) Python isolado (`-I`): variáveis `PYTHONPATH`/`PYTHONHOME` da máquina não interferem. |
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
   4. janela: pywebview (EdgeChromium/WebView2)
        └ reserva 1: Edge em modo aplicativo (msedge --app=URL)
        └ reserva 2: navegador padrão
   5. monitor da pauta (thread) e demais serviços sob demanda
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
helestron/                     o pacote Python (vai inteiro para o instalador)
  __init__.py  __main__.py
  aplicativo/                  inicialização, janela, instância única, integridade, autoteste
  servidor/                    servidor HTTP, API, eventos, perguntas, tarefas web
  servicos.py  tarefas.py      ponte entre a API e o motor (sem interface gráfica)
  nucleo/  download/  transcricao/  compartilhar/   o motor (já existente)
  pauta/                       NOVO: pauta de audiências
  verificar.py                 diagnóstico da instalação
  dados/                       tribunais.json, seletores, pauta.json
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
python.exe pythonw.exe python312.dll python3.dll vcruntime140*.dll msvcp140*.dll
DLLs\  Lib\  Lib\site-packages\helestron\ ...   (bibliotecas + o pacote, com .pyc pré-compilados)
modelos\faster-whisper-small\   modelo de transcrição ao vivo (embutido)
modelos\falantes\               modelos da separação de falantes (embutidos, se disponíveis)
helestron.ico  manifesto.json  Desinstalar.exe
```

Dados do usuário (nunca apagados pela desinstalação sem perguntar):

| O quê | Onde |
|---|---|
| configuração `config.ini`, `Logs\`, `perfis\` (navegador), `credenciais.json` (DPAPI), `pauta.sqlite3`, `instancia.json`, `modelos\` baixados depois, `temp\` | `%LOCALAPPDATA%\Helestron\` |
| Acervo (processos, transcrições) — compartilhado com a IA | `Documentos\Helestron\Acervo\` (`Processos\`, `Transcricoes\`) |
| Sigilosos (segredo de justiça) — nunca compartilhado | `Documentos\Helestron\Sigilosos\` |
| Pauta exportada (Excel) — **fora do acervo** (traz partes de processos sigilosos) | `Documentos\Helestron\Pauta\` |

Se a pasta Documentos estiver dentro do OneDrive (redirecionamento de pastas
conhecidas), a base passa a ser `%USERPROFILE%\Helestron\` — a sincronização
trava arquivo em uso (lição do Assessor SAJ). Tudo configurável em Ajustes.

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
BASE_USUARIO   = env HELESTRON_DADOS  ou  Documentos\Helestron  (ou %USERPROFILE%\Helestron se Documentos estiver no OneDrive)
python_exe(janela=False) -> INSTALACAO/python.exe | pythonw.exe | sys.executable
```

Os testes isolam tudo com `HELESTRON_LOCAL` e `HELESTRON_DADOS` apontando para
pastas temporárias (ou com `mock.patch` nas constantes, como já fazem).

## 5. Linha de comando (`python -m helestron`)

| Comando | O que faz |
|---|---|
| *(sem argumentos)* | abre o programa (servidor + janela) |
| `--verificar-instalacao [--relatorio ARQ]` | sem janela: confere o manifesto (hash de todos os arquivos), importa **todos** os módulos do pacote, testa o modelo embutido (carrega), WebView2/Edge. Código de saída 0 = ok, 1 = falha. Grava relatório em texto (UTF-8) em `ARQ` (padrão `LOCAL/Logs/verificacao-instalacao.txt`). Usado pelo instalador. |
| `--autoteste PASTA` | abre a janela de verdade, a interface percorre todas as telas sozinha (`?autoteste=1`), o programa salva capturas (PNG) e `autoteste.json` em `PASTA` e fecha. Usado no CI do Windows. |
| `--servidor [--porta N] [--sem-janela] [--token T]` | só o servidor (testes e desenvolvimento); imprime `URL=...` na saída |
| `--encerrar` | pede à instância aberta que feche (usado pelo instalador antes de atualizar) |
| `mcp [--pasta ACERVO]` | servidor MCP do acervo (stdio), como hoje |
| `baixar ...`, `transcrever ...`, `modelos ...`, `microfones`, `verificar`, `preparar`, `preparar-pastas` | como hoje |
| `pauta sincronizar|exportar|importar ...` | linha de comando da pauta (seção 8.9) |

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
  sigilosos, pauta, Logs) e URLs `https://`.
* Corpo JSON até 2 MB; envio de arquivo (relação, gravação, relatório de pauta)
  até 500 MB, gravado em `LOCAL/temp` e apagado depois.

### 6.2 Envelope

Sucesso: `{"ok": true, "dados": ...}`. Erro: `{"ok": false, "erro": {"codigo":
"texto_curto", "mensagem": "frase para o usuário, em português", "detalhe":
"técnico, opcional"}}` com HTTP 400/403/404/409/500. A interface mostra sempre a
`mensagem`. Datas em ISO 8601 (`2026-10-03`, `2026-10-03T14:30:00`).

### 6.3 Endpoints

**Geral**
* `GET /api/estado` → `{nome, versao, modo: "janela"|"edge"|"navegador", pastas: {acervo, processos, transcricoes, sigilosos, pauta, logs}, pendencias: [{chave, titulo, mensagem, acao: "ajustes#acessos"|...}], resumo: {processos, transcricoes, ultimos_lotes: [{nome, quando, total, baixados, falhas, pasta}], transcricoes_recentes: [{numero, arquivo, quando}], pauta: {hoje, semana, proxima: Audiencia|null, ultima_sincronizacao, alteracoes_nao_vistas}}, tarefas: [Tarefa]}`
* `GET /api/config` → `{valores: {secao: {chave: valor}}, esquema: [{secao, chave, tipo: "texto"|"flag"|"inteiro"|"pasta"|"escolha", rotulo, ajuda, opcoes?}]}`
* `POST /api/config` `{secao, chave, valor}` → `{valor}` (valida; pastas conflitantes → erro com a frase de `problema_nas_pastas`)
* `GET /api/tribunais` → `[{sigla, nome, sistema, alternativo}]`
* `GET /api/acessos` → `[{portal, rotulo, usuario, tem_senha}]`; `POST /api/acessos` `{portal, usuario, senha}`; `DELETE /api/acessos/{portal}`; `POST /api/acessos/testar` `{tribunal}` → `{tarefa}`
* `POST /api/dialogo/arquivo` `{titulo, tipos: ["Planilhas|*.xlsx;*.xls", ...]}` e `POST /api/dialogo/pasta` `{titulo, inicial}` → `{caminho|null}` (diálogo nativo pela pywebview; fora dela → erro `sem_dialogo`, e a interface usa `<input type=file>`)
* `POST /api/abrir` `{tipo: "pasta"|"arquivo"|"url", alvo}`
* `GET /api/verificacao` → `[{nome, situacao: "ok"|"aviso"|"falha", detalhe, acao}]`; `POST /api/verificacao/completa` → `{tarefa}`
* `POST /api/encerrar`

**Tarefas e perguntas**
* `GET /api/tarefas`, `GET /api/tarefas/{id}` → `Tarefa = {id, tipo: "download"|"teste_login"|"transcricao_arquivo"|"modelo"|"preparo"|"pacote"|"nuvem"|"pauta_sincronizar"|"pauta_capturar"|"verificacao", titulo, estado: "rodando"|"concluida"|"falhou"|"parada", inicio, fim, progresso: {feitos, total, atual, percentual}, status, resultado, erro}`
* `POST /api/tarefas/{id}/parar`
* `POST /api/perguntas/{id}/responder` `{valor}`; `POST /api/perguntas/{id}/cancelar`

**Processos (download)**
* `POST /api/relacao/arquivo` — corpo `multipart/form-data` (campo `arquivo`) **ou** JSON `{caminho}` → `Leitura = {formato, origem, processos: [{numero, tribunal, sistema, tem_senha}], avisos: [], corrompidos: [], sem_suporte: [{numero, motivo}]}`
* `POST /api/relacao/texto` `{texto}` → `Leitura`; `POST /api/relacao/link` `{url}` → `Leitura`
* `POST /api/download/iniciar` `{processos: [numero], senhas?: {numero: senha}, nome_lote, opcoes: {separar_sigilosos, rebaixar, navegador_visivel}}` → `{tarefa}` (eventos `item` por processo)
* `GET /api/download/lotes` → `[{nome, quando, total, baixados, falhas, pasta, relatorio}]`

**Audiências (transcrição)**
* `GET /api/transcricao/microfones` → `[{indice, nome, padrao}]`
* `POST /api/transcricao/microfone/teste` `{dispositivo}` (eventos `microfone_nivel`) ; `POST /api/transcricao/microfone/parar`
* `GET /api/transcricao/modelos` → `[{nome, rotulo, tamanho_mb, instalado, embutido, recomendado_para}]`; `POST /api/transcricao/modelos/baixar` `{nome}` → `{tarefa}`
* `POST /api/transcricao/iniciar` `{processo, dispositivo, sigiloso, tipo, participantes: {"F1": "Juiz(a)", ...}, falante}` → `{sessao}`
* `POST /api/transcricao/pausar` · `/retomar` · `/falante` `{falante}` · `/encerrar` → `{documento}` (a sessão é única)
* `GET /api/transcricao/estado` → `{sessao|null, estado, segundos, processo, falas: [...]}`
* `GET /api/transcricao/recuperaveis` → `[{arquivo, processo, quando}]`; `POST /api/transcricao/recuperar` `{arquivo}` → `{documento}`
* `POST /api/transcricao/gravacao` (multipart `arquivo` ou JSON `{caminho}`, mais `processo`, `sigiloso`, `revisao`) → `{tarefa}`
* `GET /api/transcricao/recentes` → `[{numero, arquivo, quando, sigiloso}]`

**Pauta** (seção 8)
* `GET /api/pauta?de=&ate=&sistema=&situacao=&busca=` → `{audiencias: [Audiencia], resumo: {total, hoje, semana, por_situacao: {}, por_tipo: {}}, ultima_sincronizacao, monitoramento: {ativo, intervalo_horas, proxima}}`
* `GET /api/pauta/fontes`; `POST /api/pauta/fontes` `{tribunal, sistema, rotulo, url?}`; `DELETE /api/pauta/fontes/{id}`
* `POST /api/pauta/sincronizar` `{fontes?: [id], de?, ate?}` → `{tarefa}`
* `POST /api/pauta/capturar` `{tribunal, sistema}` → `{tarefa}` (captura assistida, seção 8.4)
* `POST /api/pauta/importar` (multipart `arquivo` ou JSON `{caminho}`) → `{novas, atualizadas, ignoradas, avisos}`
* `POST /api/pauta/exportar` `{de, ate, sistema?, situacao?, busca?}` → `{arquivo}`
* `GET /api/pauta/alteracoes?desde=` → `[{quando, tipo: "nova"|"alterada"|"cancelada"|"removida", audiencia, campos: [{campo, antes, depois}]}]`; `POST /api/pauta/alteracoes/vistas`
* `POST /api/pauta/monitoramento` `{ativo, intervalo_horas}`
* `POST /api/pauta/baixar-autos` `{ids?: [], de?, ate?}` → `{tarefa}` (lote de download com os processos)

**Compartilhar com IA**
* `GET /api/compartilhar/estado` → estado de cada destino (`servicos.estado_ia`)
* `POST /api/compartilhar/preparar` → `{tarefa}`
* `POST /api/compartilhar/claude-desktop` (conectar o acervo) · `/cowork` · `/claude-code` · `/chatgpt-work` · `/codex` → `{mensagem, abriu}`
* `POST /api/compartilhar/pacote` `{numeros?}` → `{tarefa}`
* `GET /api/compartilhar/nuvem` → `[{rotulo, caminho}]`; `POST /api/compartilhar/nuvem/espelhar` `{destino}` → `{tarefa}`
* `GET /api/compartilhar/prompt` → `{texto}`

### 6.4 Eventos (`GET /api/eventos?t=TOKEN`, Server-Sent Events)

Cada evento: `event: <tipo>` + `data: <json>`. Tipos:

| tipo | dados |
|---|---|
| `tarefa` | `Tarefa` (sempre que muda) |
| `item` | `{tarefa, numero, situacao, mensagem, arquivo, sigiloso}` (download) |
| `log` | `{tarefa?, nivel: "info"|"aviso"|"erro", texto, hora}` |
| `pergunta` | `{id, tarefa, tipo: "codigo"|"confirmar"|"texto"|"escolha", titulo, mensagem, opcoes?, prazo_s}` |
| `pergunta_fechada` | `{id, motivo}` |
| `aviso` | `{titulo, mensagem, nivel}` |
| `transcricao` | `{tipo: "estado"|"nivel"|"fala"|"atraso"|"aviso"|"erro"|"salvo"|"fim", dados}` (`fala` = `{inicio, fim, falante, texto}`) |
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
fecham a pergunta (`pergunta_fechada`).

## 7. Interface (`helestron/web`)

### 7.1 Princípios

* **iOS / iPadOS**: barra lateral translúcida (vidro), títulos grandes, cartões
  com cantos de 20 px, listas agrupadas ("inset grouped"), controles segmentados,
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
  (azul e navy em baixa opacidade), para o vidro "aparecer".
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
  1366×768 com zoom 125 %.

### 7.2 Estrutura

Barra lateral (vidro, 248 px): logotipo H + "Helestron"; seções **Início**,
**Processos**, **Audiências** (transcrição), **Pauta**, **Compartilhar**,
**Ajustes**, **Ajuda**; no rodapé, tarefas em andamento (anel de progresso) e a
versão. Conteúdo: título grande + subtítulo + ações à direita.

* **Início** — saudação ("Boa tarde") e data; **quatro cartões grandes** com as
  funções principais (Baixar processos · Transcrever audiência · Pauta de
  audiências · Compartilhar com IA), cada um com ícone, frase e botão; abaixo,
  "Hoje na pauta" (próximas audiências), "Atividade recente" (lotes e
  transcrições) e "Primeiros passos" (pendências: acessos, pastas, modelo) como
  lista de verificação.
* **Processos** — fluxo em etapas: (1) relação: área de soltar arquivo
  (arrastar e soltar), botão "Escolher arquivo", "Colar lista" e "Link"; (2)
  revisão: processos reconhecidos com selos do tribunal/sistema, avisos e
  números rejeitados; (3) opções (nome do lote, separar sigilosos, baixar de novo
  o que já existe, mostrar o navegador); (4) andamento: anel de progresso, lista
  de itens com situação, botões Parar e Abrir pasta. Mais "Últimos lotes".
* **Audiências** — preparação (número do processo com validação e sugestões da
  pauta de hoje, microfone com medidor de nível, participantes F1–F8, interruptor
  "Segredo de justiça"); **botão de gravar** grande (círculo vermelho); durante a
  gravação: cronômetro, texto ao vivo com marcação de tempo e falante, rolagem
  automática, Pausar/Retomar, botões de falante, Encerrar → documento DOCX
  ("Abrir documento"). Também "Transcrever gravação", "Recuperar sessão
  interrompida" e "Transcrições recentes".
* **Pauta** — seção 8.8.
* **Compartilhar** — botão principal "Preparar acervo para a IA"; cartões:
  Claude Code, Claude Cowork, Claude Desktop (conector), ChatGPT Work, Codex,
  Pacote para o ChatGPT, Nuvem (OneDrive/Google Drive); cada um com situação e
  ação; "Copiar pedido inicial".
* **Ajustes** — listas agrupadas: Acessos aos portais (usuário/senha por
  portal, testar), Pastas, Unidade, Download, Transcrição, Pauta (fontes,
  monitoramento), Compartilhar, Sobre e diagnóstico (versão, verificar
  instalação, abrir registros).
* **Ajuda** — perguntas frequentes pesquisáveis e "como fazer" de cada função.

Folhas (sheets) para perguntas (código de 6 dígitos com campo grande),
confirmações e erros. Avisos (toasts) no canto superior direito.

### 7.3 Arquivos

`web/index.html`, `web/css/helestron.css`, `web/js/` (`api.js` — cliente com
token e reconexão do SSE; `app.js` — rotas por `#/secao`; um arquivo por seção;
`componentes.js`; `demo.js`), `web/img/` (logotipo, ícones SVG), `web/fontes/`.

**Modo demonstração** (`index.html?demo=1`): `demo.js` responde a todas as
chamadas da API com dados realistas e simula eventos (download andando, texto da
audiência chegando, pauta com 40 audiências), **sem servidor**. Serve para
desenvolver o visual, para as capturas de tela e para testes da interface.
**Modo autoteste** (`?autoteste=1`): percorre as seções, espera cada uma
carregar e avisa o servidor (`POST /api/autoteste/passo {secao}`) para a captura.

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
    sigiloso: bool     # portal indicou segredo de justiça, ou processo está na pasta de sigilosos
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
(e não a apaga).

### 8.3 Extração automática (e-SAJ e eProc)

Reaproveita o login e o perfil de navegador do download (`download/esaj.py`,
`download/eproc.py`, `download/navegador.py`): mesma sessão, mesmo código por
e-mail/dois fatores via perguntas. Depois de entrar:

1. **Rota lembrada** da fonte (URL capturada antes), se houver.
2. **Rotas conhecidas** em `dados/pauta.json` (por sistema e, se preciso, por
   tribunal) — candidatos de URL relativos ao portal.
3. **Descoberta pelo menu**: procura links/itens de menu cujo texto case com
   `pauta|audiênci|agenda de audi|gerenciar audi|consultar audi` (regex em
   `pauta.json`), abre o primeiro e confere se a página tem tabela de audiências.
4. Preenche o **período** se a página tiver campos de data (rótulos/nomes como
   `Data inicial/final`, `dataInicio`, `txtDataInicio`, `de`/`até`) e envia.
5. Lê **todas as tabelas** da página (inclusive em frames), reconhece a de
   audiências pelo cabeçalho (seção 8.5) e **pagina** (link/botão "Próxima",
   `infraAcaoPaginar` do eProc, seletor de página) até o fim (limite 50 páginas).
6. Normaliza, grava e registra a URL que funcionou como rota lembrada.

eProc usa o framework "Infra" (tabelas `table.infraTable`, legenda "Lista de …
(N registros)", paginação `infraAreaPaginacao`). As rotas e regexes ficam em
`pauta.json` para ajuste sem mexer no código.

### 8.4 Captura assistida (funciona em qualquer tela)

Para quando a descoberta falha, ou o tribunal tem tela própria: o Helestron abre
o portal no navegador **visível** (perfil do usuário), já logado, e injeta (via
`add_init_script` + `expose_binding`) uma **barra flutuante** discreta no topo da
página: "Helestron — vá até a pauta de audiências e clique em **Capturar esta
tela**" · [Capturar esta tela] [Concluir]. Cada clique lê as tabelas da página
atual (e frames), mostra na barra quantas audiências reconheceu e acumula; o
usuário pode mudar de página e capturar de novo. "Concluir" grava tudo e
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
`HHhMM`.

### 8.6 Importação de relatório

`POST /api/pauta/importar`: planilha (xlsx/xls/ods/csv), HTML (inclusive o
`.xls` que é HTML), PDF (tabela por texto) ou DOCX exportados do SAJ/eProc —
mesmas regras de 8.5, aproveitando os leitores de `nucleo/listas.py`.

### 8.7 Monitoramento

Thread do aplicativo: com `[pauta] monitorar = true`, sincroniza as fontes com
rota a cada `intervalo_horas` (padrão 6) e ao abrir o programa (se a última
sincronização passou do intervalo), no período `dias_atras` (7) a `dias_a_frente`
(60). Se o portal pedir código, **não bloqueia**: registra e avisa ("Entre no
portal para continuar o monitoramento"). Alterações viram eventos `pauta` e
contam em "alterações não vistas" (selo na barra lateral).

### 8.8 Tela da Pauta

Cabeçalho: período (controle segmentado **Hoje · Semana · Mês · Período**),
filtro de sistema (e-SAJ · eProc · Todos), situação, busca. Resumo em
"chips": total, hoje, próximos 7 dias, canceladas/redesignadas. Lista agrupada
por dia (cabeçalho do dia "Segunda-feira, 5 de outubro"), cada audiência com
hora, número do processo (copiável), selo do tipo, partes, local e pílula de
situação; ações por linha: Baixar autos, Transcrever (abre Audiências com o
número), Abrir link. Botões: **Sincronizar** (com e-SAJ/eProc), **Capturar no
portal**, **Importar relatório**, **Exportar Excel**. Painel "Alterações
recentes". Interruptor de monitoramento e intervalo. Estado vazio explica como
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
  tachada, Redesignada âmbar, hoje em azul-claro). Processos sigilosos com a
  coluna Partes como "(segredo de justiça)" **a menos** que o usuário marque
  "incluir partes dos sigilosos".
* **Resumo** — quantidade por dia, por tipo e por situação.
* **Alterações** — histórico do período.
Rodapé com "Gerado pelo Helestron em dd/mm/aaaa hh:mm".

CLI: `python -m helestron pauta exportar --de 2026-10-01 --ate 2026-10-31`.

### 8.10 Fachada para a API (`helestron/pauta/servico.py`)

```python
class ServicoPauta:
    def __init__(self, cfg, arquivo_banco: Path | None = None, eventos: Callable[[str, dict], None] | None = None): ...
    def listar(self, de: date, ate: date, sistema="", situacao="", busca="") -> dict      # {audiencias:[dict], resumo:{...}}
    def fontes(self) -> list[dict]
    def salvar_fonte(self, tribunal, sistema, rotulo, url="") -> dict
    def remover_fonte(self, id_fonte) -> None
    def sincronizar(self, ctx, fontes: list[str] | None, de: date, ate: date) -> dict   # ctx = Contexto da tarefa (status, progresso, cancelado, pedir_codigo)
    def capturar(self, ctx, tribunal: str, sistema: str) -> dict
    def importar(self, caminho: Path) -> dict
    def exportar(self, de, ate, destino_pasta: Path, **filtros) -> Path
    def alteracoes(self, desde: datetime | None = None) -> list[dict]
    def marcar_vistas(self) -> None
    def monitoramento(self) -> dict ; def configurar_monitoramento(self, ativo: bool, intervalo_horas: int) -> dict
    def ultima_sincronizacao(self) -> datetime | None
    def resumo_inicio(self) -> dict    # {hoje, semana, proxima, ultima_sincronizacao, alteracoes_nao_vistas}
```

`Audiencia` vira dict com `data` em ISO e `hora` "HH:MM".

## 9. Ícone e marca

`construir/marca.py` (Pillow) gera, a partir de desenho vetorial próprio:
`helestron/recursos/helestron.ico` (16, 20, 24, 32, 40, 48, 64, 128, 256),
`helestron.png` (512), `helestron-64.png`, `web/img/helestron.svg` (SVG
equivalente para a interface) e as imagens do instalador
(`instalador-boas-vindas.bmp` 164×314, `instalador-cabecalho.bmp` 150×57).

Desenho: "squircle" do iOS (superelipse), **navy** em gradiente
(#1B3560 → #0B1A33) com **reflexo de vidro** (faixa branca translúcida no topo,
borda interna clara e translúcida) e um **"H"** geométrico moderno em
branco→cinza-claro (#FFFFFF → #C5CDD8), com sombra suave; detrás do H, uma
placa **cinza translúcida** (efeito vidro/transparência). Cantos transparentes
(RGBA). Nos tamanhos 16–24 o desenho é simplificado (sem reflexo; H mais grosso)
para ficar nítido.

## 10. Construção e instalador (`construir/`)

`python construir/construir.py [--sem-modelo] [--modelo DIR] [--saida dist]`
(roda em Linux — aqui e no CI — e no Windows):

1. Baixa o Python Windows (python-build-standalone 3.12.10, SHA-256 conferido).
2. Baixa as rodas **win_amd64/cp312** de `requisitos-windows.txt` (travado com
   hash). Pacote só em código-fonte e puro Python (ex.: `proxy_tools`) é
   convertido em roda localmente.
3. Instala as rodas na pasta do Python (biblioteca `installer`, esquema Windows;
   arquivos de dados de `msvc-runtime` na raiz). Copia o pacote `helestron`
   para `Lib/site-packages`.
4. Enxuga (remove `*.pdb`, `Lib/test`, `idlelib`, `__pycache__` estranhos,
   `Scripts` desnecessários) e **pré-compila** tudo em `.pyc`
   (`UNCHECKED_HASH`).
5. Modelo `faster-whisper-small` em `modelos/` (de `--modelo DIR` ou baixado do
   Hugging Face); `--sem-modelo` gera instalador sem ele (o programa baixa no
   primeiro uso). Modelos da separação de falantes, se disponíveis.
6. Compila o lançador `Helestron.exe` (MinGW: `lancador/helestron.c` +
   `.rc` com ícone, informações de versão e manifesto: DPI PerMonitorV2,
   longPathAware, Windows 10/11). O lançador carrega `python312.dll` por
   `LoadLibraryW` (se faltar, mostra mensagem clara em português) e chama
   `Py_Main` com `-I -m helestron` + argumentos.
7. Gera `manifesto.json` (versão + SHA-256 e tamanho de cada arquivo).
8. Gera as imagens da marca e o script NSIS e roda `makensis` →
   `dist/Helestron-Setup-1.0.0.exe` + `.sha256`.

Instalador NSIS (`instalador/helestron.nsi`): Unicode, MUI2, **Português do
Brasil**, `RequestExecutionLevel user`, pasta padrão
`$LOCALAPPDATA\Programs\Helestron`, LZMA sólido. Páginas: boas-vindas (imagem da
marca), pasta, instalação, concluir (☑ "Abrir o Helestron"). Seções: programa
(obrigatória) e atalho na Área de Trabalho (marcada). Antes de copiar: pede à
instância aberta que feche (`Helestron.exe --encerrar`) e remove a versão
anterior do **programa** (nunca os dados). Atalho no Menu Iniciar e na Área de
Trabalho com o ícone. Registro em `HKCU\...\Uninstall\Helestron` (nome, ícone,
versão, editor, tamanho). Ao final roda `Helestron.exe --verificar-instalacao`
e, se falhar, mostra o resumo e onde está o relatório. Desinstalador: fecha o
programa, remove programa e atalhos, pergunta se apaga também configurações e
senhas (padrão: não) e **nunca** apaga `Documentos\Helestron`. Modo silencioso
(`/S`, `/D=`) para o CI.

## 11. CI (`.github/workflows/helestron.yml`)

* **testes** (ubuntu): unittest completo (+ Playwright Chromium para a
  interface em modo demonstração, com capturas como artefato).
* **construir** (ubuntu): apt `nsis` e `mingw-w64`; `construir.py` com o modelo
  baixado do Hugging Face; artefato `Helestron-Setup`.
* **windows** (windows-latest, depende de construir): instala em silêncio
  (`/S`), confere arquivos e atalhos, `--verificar-instalacao`, `--autoteste`
  (capturas da janela real), transcrição de ponta a ponta com fala sintetizada
  (System.Speech) pela linha de comando, servidor MCP por JSON-RPC, exportação
  da pauta, cofre DPAPI, desinstalação silenciosa (dados preservados).
* **publicar** (tags `v*`): cria a versão no GitHub com o instalador e o `.sha256`.

## 12. Regras transversais (valem para todos)

* **Sigilo** (invariantes do motor, não podem regredir): processo em segredo de
  justiça nunca fica no acervo, nunca vai para a IA, o pacote, o espelho na
  nuvem, o MCP ou o índice; transcrição de sigiloso vai para
  `Sigilosos\Transcricoes`; a pauta exportada fica fora do acervo e mascara as
  partes dos sigilosos por padrão.
* **Português do Brasil** correto em tudo o que o usuário lê (acentos, crase,
  concordância). Código e comentários em português, no estilo do código
  existente.
* Nada de dependência nova além de: `pywebview`, `pythonnet` (e dependências),
  `bottle`, `proxy_tools`, `typing_extensions` (Windows), `installer` (só na
  construção). Biblioteca padrão para HTTP, SQLite, threads.
* Testes com `unittest`, rodando em Linux sem rede e sem Windows (o que é só do
  Windows é pulado com `skipUnless`), sem tocar em `~` ou `%LOCALAPPDATA%` reais.
* Nada de `importlib.import_module` com nome montado em tempo de execução para
  partes essenciais do programa.
