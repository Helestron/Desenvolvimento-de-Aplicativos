# Desenvolvimento de Aplicativos

## Assessor Integrado (`AssessorIntegrado/`)

Sistema para Windows, de uso em gabinete judicial, que reúne numa só janela:

1. **Baixar processos** do **e-SAJ** ou do **eProc**, com o login do próprio
   usuário, a partir de uma relação em Excel, Word, PDF ou texto — **um PDF
   único por processo**, nomeado com o número CNJ, numa única pasta;
2. **Transcrever audiências ao vivo**, pelo microfone, gerando **DOCX nomeado
   com o número do processo** em pasta dedicada (e transcrever gravações já
   existentes);
3. **Compartilhar o acervo com IA** — Claude Code, Claude Desktop/Cowork e
   ChatGPT Work/Codex —, com texto dos autos marcado por folha, arquivos de
   contexto (`CLAUDE.md`/`AGENTS.md`), habilidade do Claude Code, conector MCP
   somente de leitura, pacote para o ChatGPT e espelho em OneDrive/Google Drive.

Evolução do **Assessor SAJ** (e-SAJ/TJAL): passa a falar com o eProc (inclusive
nos tribunais em transição, como TJAL e TJSP), detecta o tribunal pelo número,
transcreve em tempo real, guarda senhas cifradas pela DPAPI do Windows e
instala-se com **um duplo clique**, sem administrador.

- Instalação e uso: [`AssessorIntegrado/LEIA-ME.txt`](AssessorIntegrado/LEIA-ME.txt)
  e [`AssessorIntegrado/MANUAL.md`](AssessorIntegrado/MANUAL.md).
- Testes: `python -m unittest discover -s testes -t .` (na pasta do programa);
  o CI do GitHub Actions instala e testa o programa num Windows limpo a cada push.
