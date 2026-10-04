/* Helestron — Compartilhar com IA (especificação 7.2).
 *
 * O acervo é uma pasta comum do computador; daqui ele é preparado (texto dos
 * autos, índice, regras de trabalho) e aberto no Claude Code, no Cowork, no
 * ChatGPT Work ou no Codex; o conector do acervo é registrado no Claude
 * Desktop; o pacote para anexar e o espelho na nuvem também saem daqui.
 * Os processos sigilosos nunca entram em nada disso.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, botao, cartao, faixa, trocar, folha, aviso, blocoIcone } = H.ui;
  const { fmt, api } = H;

  function mostrarResposta(titulo, r) {
    const mensagem = (r && r.mensagem) || "Pronto.";
    if (mensagem.length > 110) {
      return folha.informar({ titulo, mensagem, icone: "brilho" });
    }
    aviso({ titulo, mensagem, tipo: "sucesso" });
    return null;
  }

  function estadoLinha(texto, cor) {
    return el("span", { classe: "estado-linha" }, el("span", { classe: "ponto ponto-" + cor }), texto);
  }

  H.secoes = H.secoes || {};
  H.secoes.compartilhar = {
    async montar(ctx) {
      const raiz = ctx.raiz;
      const pastas = (H.loja.estado && H.loja.estado.pastas) || {};

      const botaoPreparar = botao({ rotulo: "Preparar acervo para a IA", icone: "brilho", tipo: "primario", acao: async () => {
        const r = await api.compartilhar.preparar();
        acompanharPreparo(r.tarefa);
      } });
      botaoPreparar.id = "botao-preparar";
      const copiarPedido = botao({ rotulo: "Copiar pedido inicial", icone: "copiar", acao: async () => {
        const r = await api.compartilhar.prompt();
        await H.ui.copiar((r && r.texto) || "", "Pedido inicial copiado");
      } });
      const cab = H.ui.cabecalho({
        titulo: "Compartilhar com IA",
        subtitulo: "O acervo é uma pasta do seu computador: a IA lê direto dela, com as regras de trabalho já escritas.",
        acoes: [copiarPedido, botaoPreparar],
      });

      const acervo = cartao({ classe: "acervo" }, H.ui.esqueleto(1));
      const sigilo = faixa({
        tipo: "sigilo", icone: "cadeado", titulo: "Sigilo e responsabilidade",
        texto: "Processos em segredo de justiça ficam na pasta dos sigilosos e nunca vão para a IA, para o pacote nem para a nuvem. A IA é ferramenta de apoio: resumos e minutas são sugestões para conferência e decisão do magistrado (Resolução CNJ nº 615/2025).",
      });
      const destinos = el("div", { classe: "destinos", id: "destinos" });
      raiz.append(cab, acervo, el("div", { estilo: { height: "14px" } }), sigilo,
        el("h2", { classe: "secao-titulo" }, "Onde usar o acervo"), destinos);

      let estado = null;
      let nuvens = [];
      let tarefaPreparo = null;

      // ------------------------------------------------ acervo
      function desenharAcervo() {
        const a = (estado && estado.acervo) || {};
        const status = el("p", { classe: "cartao-sub", "aria-live": "polite" });
        const t = tarefaPreparo ? H.loja.tarefas.get(tarefaPreparo) : null;
        let progresso = null;
        if (t && t.estado === "rodando") {
          const anel = H.ui.anel({ tamanho: 22, espessura: 4.5 });
          anel.definir(t.progresso && typeof t.progresso.percentual === "number" ? t.progresso.percentual : null);
          progresso = el("span", { classe: "estado-linha" }, anel, t.status || "Preparando…");
        }
        status.append(a.preparado ? `Preparado para a IA ${fmt.relativo(a.preparado)}` : "Ainda não preparado para a IA");
        botaoPreparar.disabled = !!(t && t.estado === "rodando");
        trocar(acervo,
          el("div", { classe: "acervo-topo" },
            blocoIcone("pasta", "azul", true),
            el("div", { classe: "linha-texto" },
              el("h2", { classe: "cartao-titulo", texto: "Acervo" }),
              el("p", { classe: "caminho", texto: pastas.acervo || "—" }),
              progresso || status),
            el("div", { classe: "acervo-numeros" },
              el("div", { classe: "acervo-numero" }, el("strong", { texto: fmt.numero(a.processos || 0) }), el("span", { texto: a.processos === 1 ? "processo" : "processos" })),
              el("div", { classe: "acervo-numero" }, el("strong", { texto: fmt.numero(a.transcricoes || 0) }), el("span", { texto: a.transcricoes === 1 ? "transcrição" : "transcrições" })))),
          el("div", { classe: "grupo-botoes", estilo: { marginTop: "14px", paddingTop: "14px", borderTop: "1px solid var(--separador)" } },
            botao({ rotulo: "Abrir a pasta", icone: "pasta", tamanho: "pequeno", acao: () => api.abrir("pasta", pastas.acervo) }),
            botao({ rotulo: "Copiar o caminho", icone: "copiar", tamanho: "pequeno", tipo: "texto", acao: () => H.ui.copiar(pastas.acervo || "", "Caminho copiado") })));
      }

      function acompanharPreparo(id) {
        tarefaPreparo = id;
        desenharAcervo();
      }
      ctx.on("tarefa", (t) => {
        if (t.tipo === "preparo") {
          if (!tarefaPreparo && t.estado === "rodando") tarefaPreparo = t.id;
          if (t.id === tarefaPreparo) {
            if (t.estado !== "rodando") { tarefaPreparo = null; carregar(); }
            else desenharAcervo();
          }
        }
      });
      const emCurso = Array.from(H.loja.tarefas.values()).find((t) => t.tipo === "preparo" && t.estado === "rodando");
      if (emCurso) tarefaPreparo = emCurso.id;

      // ------------------------------------------------ destinos
      function destino({ id, nomeIcone, cor, nome, situacao, texto, acoes, largo }) {
        return cartao({ classe: "destino" + (largo ? " largo" : ""), id, tag: "article" },
          el("div", { classe: "destino-topo" },
            blocoIcone(nomeIcone, cor),
            el("div", { classe: "linha-texto" }, el("h3", { classe: "destino-nome", texto: nome }), situacao)),
          el("p", { classe: "destino-texto", texto }),
          el("div", { classe: "grupo-botoes" }, acoes));
      }

      function desenharDestinos() {
        const e = estado || {};
        const claude = e.claude || {};
        const chatgpt = e.chatgpt || {};
        const appChatgpt = e.chatgpt_desktop !== undefined && e.chatgpt_desktop !== null ? e.chatgpt_desktop : chatgpt.app;
        const conectado = !!(e.mcp_acervo || claude.mcp);
        const executar = (titulo, fn) => async () => mostrarResposta(titulo, await fn());

        const selecaoNuvem = el("select", { classe: "campo campo-pequeno", id: "destino-nuvem", aria: { label: "Pasta na nuvem" } });
        const salva = String(H.app.valorConfig("compartilhar", "pasta_nuvem", "") || "");
        const opcoes = nuvens.map((n) => [n.caminho, n.rotulo]);
        if (salva && !opcoes.some(([c]) => c === salva)) opcoes.unshift([salva, salva.split(/[\\/]/).pop() || salva]);
        if (opcoes.length) {
          opcoes.forEach(([caminho, rotulo]) => selecaoNuvem.appendChild(el("option", { value: caminho, texto: rotulo, title: caminho })));
          if (salva) selecaoNuvem.value = salva;
        } else {
          selecaoNuvem.appendChild(el("option", { value: "", texto: "Nenhuma pasta de nuvem encontrada" }));
          selecaoNuvem.disabled = true;
        }
        const escolherOutra = botao({ rotulo: "Outra pasta…", tipo: "texto", tamanho: "pequeno", acao: async () => {
          let caminho = null;
          try {
            caminho = await api.escolherPasta({ titulo: "Escolha a pasta na nuvem", inicial: selecaoNuvem.value || "" });
          } catch (erro) {
            if (erro.codigo !== "sem_dialogo") throw erro;
            caminho = await folha.entrada({ titulo: "Pasta na nuvem", rotulo: "Caminho da pasta", mensagem: "Cole o caminho de uma pasta do OneDrive ou do Google Drive.", placeholder: "C:\\Users\\…\\OneDrive" });
          }
          if (!caminho) return;
          await api.config.gravar("compartilhar", "pasta_nuvem", caminho);
          await H.app.carregarConfig(true);
          desenharDestinos();
        } });

        trocar(destinos,
          destino({
            id: "destino-claude-code", nomeIcone: "terminal", cor: "navy", nome: "Claude Code",
            situacao: claude.claude_code ? estadoLinha("Instalado neste computador", "verde") : estadoLinha("Não instalado · exige plano pago do Claude", "cinza"),
            texto: "Abre um terminal já dentro do acervo. O Claude lê sozinho o CLAUDE.md, com as regras de trabalho, e o índice.",
            acoes: [botao({ rotulo: "Abrir no Claude Code", tipo: "tonal", tamanho: "pequeno", acao: executar("Claude Code", api.compartilhar.claudeCode) })],
          }),
          destino({
            id: "destino-cowork", nomeIcone: "brilho", cor: "indigo", nome: "Claude Cowork",
            situacao: claude.desktop ? estadoLinha("Claude Desktop instalado", "verde") : estadoLinha("Claude Desktop não instalado", "cinza"),
            texto: "No app Claude Desktop, o Cowork trabalha na pasta do acervo. O pedido inicial vai copiado: é só colar.",
            acoes: [botao({ rotulo: "Abrir no Cowork", tipo: "tonal", tamanho: "pequeno", acao: executar("Claude Cowork", api.compartilhar.cowork) })],
          }),
          destino({
            id: "destino-claude-desktop", nomeIcone: "computador", cor: "azul", nome: "Claude Desktop",
            situacao: conectado ? estadoLinha("Acervo conectado", "verde") : claude.desktop ? estadoLinha("Acervo ainda não conectado", "ambar") : estadoLinha("Claude Desktop não instalado", "cinza"),
            texto: "Registra o conector do acervo: no chat e no Cowork, o Claude passa a listar, ler e buscar nos processos — só leitura.",
            acoes: [botao({ rotulo: conectado ? "Reconectar o acervo" : "Conectar o acervo", tipo: conectado ? null : "tonal", tamanho: "pequeno", acao: async () => {
              mostrarResposta("Claude Desktop", await api.compartilhar.claudeDesktop());
              await carregar();
            } })],
          }),
          destino({
            id: "destino-chatgpt-work", nomeIcone: "conversa", cor: "ciano", nome: "ChatGPT Work",
            situacao: appChatgpt === true ? estadoLinha("App do ChatGPT instalado", "verde") : appChatgpt === false ? estadoLinha("App do ChatGPT não instalado", "cinza") : estadoLinha("App do ChatGPT: não verificado", "cinza"),
            texto: "O app do ChatGPT trabalha em pastas locais no modo Work: tecle Ctrl+O e cole o caminho do acervo, que já vai copiado.",
            acoes: [botao({ rotulo: "Abrir no ChatGPT Work", tipo: "tonal", tamanho: "pequeno", acao: executar("ChatGPT Work", api.compartilhar.chatgptWork) })],
          }),
          destino({
            id: "destino-codex", nomeIcone: "codigo", cor: "ardosia", nome: "Codex",
            situacao: chatgpt.codex ? estadoLinha("Instalado neste computador", "verde") : estadoLinha("Não instalado", "cinza"),
            texto: "O agente da OpenAI no terminal, dentro do acervo. Lê o AGENTS.md, com as mesmas regras do Claude.",
            acoes: [botao({ rotulo: "Abrir no Codex", tipo: "tonal", tamanho: "pequeno", acao: executar("Codex", api.compartilhar.codex) })],
          }),
          destino({
            id: "destino-pacote", nomeIcone: "pacote", cor: "ambar", nome: "Pacote para o ChatGPT",
            situacao: estadoLinha("Sigilosos ficam de fora", "azul"),
            texto: "Uma pasta e um .zip com os autos, os textos, as transcrições, o índice e as instruções, para anexar numa conversa ou num Projeto.",
            acoes: [botao({ rotulo: "Gerar o pacote", tipo: "tonal", tamanho: "pequeno", acao: async () => {
              await api.compartilhar.pacote();
              aviso({ titulo: "Gerando o pacote", mensagem: "Acompanhe na barra lateral; a pasta abre quando terminar.", tipo: "info" });
            } })],
          }),
          destino({
            id: "destino-nuvem", nomeIcone: "nuvem", cor: "celeste", nome: "Nuvem", largo: true,
            situacao: nuvens.length ? estadoLinha(nuvens.map((n) => n.rotulo).join(" · "), "verde") : estadoLinha("Nenhum OneDrive ou Google Drive encontrado", "cinza"),
            texto: "Uma cópia do acervo no OneDrive ou no Google Drive, para usar a IA pela web e no celular. Só o que mudou é copiado; as gravações não vão.",
            acoes: [
              selecaoNuvem,
              botao({ rotulo: "Espelhar agora", tipo: "tonal", tamanho: "pequeno", desativado: !opcoes.length, acao: async () => {
                if (!selecaoNuvem.value) return;
                await api.compartilhar.espelhar(selecaoNuvem.value);
                aviso({ titulo: "Espelhando o acervo", mensagem: "Acompanhe na barra lateral.", tipo: "info" });
              } }),
              escolherOutra,
            ],
          }));
      }

      async function carregar() {
        try { await H.app.carregarConfig(); } catch (_e) { /* padrões */ }
        const [e, n] = await Promise.all([
          api.compartilhar.estado().catch((erro) => { aviso({ titulo: "Não consegui conferir o Claude e o ChatGPT", mensagem: erro.message, tipo: "alerta" }); return {}; }),
          api.compartilhar.nuvens().catch(() => []),
        ]);
        if (!ctx.vivo) return;
        estado = e || {};
        nuvens = Array.isArray(n) ? n : [];
        desenharAcervo();
        desenharDestinos();
      }

      await carregar();
    },
  };
})();
