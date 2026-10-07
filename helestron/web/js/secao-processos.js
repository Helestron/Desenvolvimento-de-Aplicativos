/* Helestron — Processos: baixar os autos de uma relação (especificação 7.2).
 *
 * Fluxo em etapas: (1) a relação — arrastar e soltar, escolher arquivo,
 * colar a lista ou um link; (2) a revisão do que foi reconhecido, com os
 * selos do tribunal e do sistema, os avisos e os números rejeitados; (3) as
 * opções do lote; (4) o andamento, processo a processo.
 *
 * O rascunho (relação lida, opções) fica em Helestron.loja.processos: sair
 * da tela e voltar não perde nada. Um download em curso — começado aqui ou
 * pela Pauta ("Baixar autos") — é sempre mostrado no andamento.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, botao, cartao, cabecalhoCartao, vazio, faixa, pilula, interruptor, trocar, folha, aviso, situacaoDownload, nomeSistema } = H.ui;
  const { fmt, api } = H;

  // As mesmas extensões de nucleo/listas.py (EXTENSOES): test_web_contrato confere.
  const TIPOS_RELACAO = ["Relações de processos|*.xlsx;*.xlsm;*.xls;*.ods;*.csv;*.docx;*.pdf;*.txt;*.html;*.htm", "Todos os arquivos|*.*"];
  const ACEITAR = ".xlsx,.xlsm,.xls,.ods,.csv,.docx,.pdf,.txt,.html,.htm";

  function rascunho() {
    if (!H.loja.processos) H.loja.processos = { etapa: "relacao", leitura: null, removidos: new Set(), nomeLote: "", opcoes: null, tarefaId: null, numeros: [] };
    return H.loja.processos;
  }

  function downloadEmCurso() {
    return Array.from(H.loja.tarefas.values()).filter((t) => t.tipo === "download" && t.estado === "rodando")
      .sort((a, b) => String(b.inicio).localeCompare(String(a.inicio)))[0] || null;
  }

  function nomePadraoDoLote(leitura) {
    const origem = String((leitura && leitura.origem) || "");
    if (leitura && leitura.formato !== "texto" && leitura.formato !== "link" && origem) {
      const nome = origem.split(/[\\/]/).pop().replace(/\.[^.]+$/, "").trim();
      if (nome) return nome.slice(0, 80);
    }
    return "Lote de " + fmt.data(new Date()).slice(0, 5).replace("/", "-");
  }

  // ------------------------------------------------------------ etapas
  function etapas(atual) {
    const nomes = ["Relação", "Revisão", "Opções", "Andamento"];
    const ordem = { relacao: [0], revisao: [1, 2], andamento: [3] }[atual] || [0];
    const caixa = el("ol", { classe: "etapas", aria: { label: "Etapas" }, estilo: { listStyle: "none", padding: "0", margin: "0 0 18px" } });
    nomes.forEach((nome, i) => {
      const feita = i < ordem[0];
      const corrente = ordem.includes(i);
      if (i > 0) caixa.appendChild(el("li", { classe: "etapa-traco", "aria-hidden": "true" }));
      caixa.appendChild(el("li", { classe: "etapa" + (corrente ? " atual" : "") + (feita ? " feita" : ""), aria: { current: corrente ? "step" : null } },
        el("span", { classe: "etapa-numero" }, feita ? icone("check", { tamanho: 13 }) : String(i + 1)),
        nome));
    });
    return caixa;
  }

  // =========================================================== 1. relação
  function telaRelacao(ctx, desenhar) {
    const r = rascunho();
    const ler = async (promessa) => {
      const leitura = await promessa;
      r.leitura = leitura;
      r.removidos = new Set();
      r.nomeLote = nomePadraoDoLote(leitura);
      r.etapa = "revisao";
      if (!(leitura.processos || []).length) {
        aviso({ titulo: "Nenhum processo reconhecido", mensagem: "Confira a relação: os números precisam estar completos (20 dígitos).", tipo: "alerta" });
      }
      desenhar();
    };

    const escolherArquivo = async () => {
      const escolha = await api.escolherArquivo({ titulo: "Escolha a relação de processos", tipos: TIPOS_RELACAO, aceitar: ACEITAR });
      if (escolha) await ler(api.relacao.arquivo(escolha));
    };

    const colarLista = async () => {
      const texto = await folha.entrada({
        titulo: "Colar a lista de processos", icone: "colar", multilinha: true,
        mensagem: "Cole os números, um ou vários por linha. Pode copiar direto do Excel, do e-mail ou do SAJ; o que não for número de processo é ignorado.",
        placeholder: "0700123-83.2024.8.02.0001\n1004512-63.2024.8.26.0100", confirmar: "Ler a lista",
        validar: (v) => (v ? "" : "Cole ao menos um número de processo."),
      });
      if (texto) await ler(api.relacao.texto(texto));
    };

    const usarLink = async () => {
      const url = await folha.entrada({
        titulo: "Relação por link", icone: "link", tipo: "url", confirmar: "Ler o link",
        mensagem: "Link do Google Planilhas, Google Docs, Google Drive, OneDrive ou SharePoint, compartilhado como “qualquer pessoa com o link”.",
        placeholder: "https://",
        validar: (v) => (/^https:\/\/\S+$/.test(v) ? "" : "Use o link completo, começando com https://."),
      });
      if (url) await ler(api.relacao.link(url));
    };

    const zona = el("div", { classe: "area-soltar", id: "area-soltar" },
      el("div", { classe: "vazio-icone" }, icone("bandeja")),
      el("p", { classe: "area-soltar-titulo", texto: "Arraste a relação de processos para cá" }),
      el("p", { classe: "area-soltar-texto", texto: "Planilha do Excel, documento do Word, PDF, CSV ou texto — inclusive o “.xls” exportado pelo SAJ e pelo eProc. O tribunal e o sistema saem do próprio número." }),
      el("div", { classe: "grupo-botoes" },
        botao({ rotulo: "Escolher arquivo", icone: "documento", tipo: "primario", acao: escolherArquivo }),
        botao({ rotulo: "Colar lista", icone: "colar", acao: colarLista }),
        botao({ rotulo: "Link", icone: "link", acao: usarLink })));

    // Arrastar e soltar: a zona acende; soltar em qualquer lugar da tela também vale.
    let profundidade = 0;
    const temArquivo = (ev) => ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes("Files");
    const aoEntrar = (ev) => { if (!temArquivo(ev)) return; ev.preventDefault(); profundidade++; zona.classList.add("sobre"); };
    const aoSair = () => { profundidade = Math.max(0, profundidade - 1); if (!profundidade) zona.classList.remove("sobre"); };
    const aoPassar = (ev) => { if (temArquivo(ev)) { ev.preventDefault(); ev.dataTransfer.dropEffect = "copy"; } };
    const aoSoltar = (ev) => {
      if (!temArquivo(ev)) return;
      ev.preventDefault();
      profundidade = 0;
      zona.classList.remove("sobre");
      const arquivo = ev.dataTransfer.files[0];
      if (arquivo) ler(api.relacao.arquivo({ arquivo, nome: arquivo.name })).catch((e) => folha.erro(e));
    };
    document.addEventListener("dragenter", aoEntrar);
    document.addEventListener("dragleave", aoSair);
    document.addEventListener("dragover", aoPassar);
    document.addEventListener("drop", aoSoltar);
    // Ctrl+V com números na área de transferência: lê direto, sem abrir a folha.
    const aoColar = (ev) => {
      if (ev.target.closest && ev.target.closest("input, textarea")) return;
      const texto = ev.clipboardData && ev.clipboardData.getData("text");
      if (texto && /\d{7}-?\d{2}\.?\d{4}/.test(texto)) {
        ev.preventDefault();
        ler(api.relacao.texto(texto)).catch((e) => folha.erro(e));
      }
    };
    document.addEventListener("paste", aoColar);
    ctx.aoSair(() => {
      document.removeEventListener("dragenter", aoEntrar);
      document.removeEventListener("dragleave", aoSair);
      document.removeEventListener("dragover", aoPassar);
      document.removeEventListener("drop", aoSoltar);
      document.removeEventListener("paste", aoColar);
    });

    const lotes = el("div", { id: "ultimos-lotes" }, H.ui.esqueleto(2));
    const conteudo = el("div", {},
      cartao({ classe: "etapa-relacao" }, zona),
      el("h2", { classe: "secao-titulo" }, "Últimos lotes",
        botao({ rotulo: "Abrir a pasta", tipo: "texto", tamanho: "pequeno", icone: "pasta", acao: () => api.abrir("pasta", ((H.loja.estado && H.loja.estado.pastas) || {}).processos || "") })),
      lotes);

    const carregarLotes = async () => {
      let lista = [];
      try { lista = await api.download.lotes(); } catch (_e) { lista = []; }
      if (!ctx.vivo) return;
      if (!lista.length) {
        trocar(lotes, cartao({}, vazio({ compacto: true, icone: "pasta", titulo: "Nenhum lote ainda", texto: "Os lotes baixados aparecem aqui, com o relatório de cada um." })));
        return;
      }
      trocar(lotes, H.ui.grupo({
        linhas: lista.slice(0, 8).map((l) => H.ui.linha({
          icone: "pasta", cor: "celeste", titulo: l.nome,
          sub: `${fmt.numero(l.baixados)} de ${fmt.plural(l.total, "processo baixado", "processos baixados")}` + (l.falhas ? ` · ${fmt.plural(l.falhas, "falha", "falhas")}` : "") + ` · ${fmt.quando(l.quando)}`,
          acessorio: el("span", { classe: "grupo-botoes" },
            l.relatorio ? botao({ icone: "planilha", titulo: "Abrir o relatório do lote", tamanho: "pequeno", tipo: "texto", acao: () => api.abrir("arquivo", l.relatorio) }) : null,
            botao({ rotulo: "Abrir", icone: "pasta", tamanho: "pequeno", tipo: "tonal", acao: () => api.abrir("pasta", l.pasta) })),
        })),
      }));
    };
    return { conteudo, pronto: carregarLotes() };
  }

  // =========================================================== 2–3. revisão e opções
  function telaRevisao(ctx, desenhar) {
    const r = rascunho();
    const l = r.leitura || { processos: [] };
    const ativos = () => (l.processos || []).filter((p) => !r.removidos.has(p.numero));
    if (!r.opcoes) {
      r.opcoes = {
        separar_sigilosos: H.app.flag(H.app.valorConfig("download", "separar_sigilosos", "true")),
        rebaixar: !H.app.flag(H.app.valorConfig("download", "pular_baixados", "true")),
        navegador_visivel: H.app.flag(H.app.valorConfig("download", "mostrar_navegador", "false")),
      };
    }

    // --- resumo por tribunal
    const porPortal = new Map();
    for (const p of l.processos || []) {
      const chave = `${p.tribunal}|${p.sistema}`;
      porPortal.set(chave, (porPortal.get(chave) || 0) + 1);
    }
    const contagem = el("p", { classe: "cartao-sub" });
    const atualizarContagem = () => {
      const n = ativos().length;
      contagem.textContent = `${fmt.plural(n, "processo reconhecido", "processos reconhecidos")}` +
        (l.origem ? ` · ${String(l.origem).split(/[\\/]/).pop()}` : "");
      botaoBaixar.disabled = n === 0;
      botaoBaixar.querySelector("span").textContent = n === 1 ? "Baixar 1 processo" : `Baixar ${fmt.numero(n)} processos`;
      textoRodape.replaceChildren(el("strong", { texto: fmt.plural(n, "processo", "processos") }),
        ` · ${fmt.plural(new Set(ativos().map((p) => p.tribunal)).size, "tribunal", "tribunais")}`);
    };

    const chips = el("div", { classe: "grupo-botoes", estilo: { margin: "4px 0 2px", gap: "8px" } },
      Array.from(porPortal.entries()).map(([chave, n]) => {
        const [tribunal, sistema] = chave.split("|");
        return el("span", { classe: "selo selo-contorno", estilo: { height: "26px", padding: "0 10px", fontSize: "13px" } },
          `${tribunal} · ${nomeSistema(sistema)}`, el("strong", { estilo: { marginLeft: "4px", color: "var(--navy-900)" }, texto: String(n) }));
      }));

    // --- avisos e rejeitados
    const avisos = [];
    if ((l.avisos || []).length) {
      avisos.push(faixa({ tipo: "aviso", titulo: l.avisos.length === 1 ? "Um aviso" : `${l.avisos.length} avisos`,
        texto: el("ul", { classe: "lista-avisos" }, l.avisos.map((a) => el("li", { texto: a }))) }));
    }
    if ((l.corrompidos || []).length) {
      avisos.push(faixa({ tipo: "erro", titulo: "Números que o Excel corrompeu",
        texto: el("div", {},
          el("ul", { classe: "lista-avisos" }, l.corrompidos.map((c) => el("li", { texto: c }))),
          el("p", { classe: "ajuda-campo", texto: "No Excel, formate a coluna dos números como Texto, digite-os de novo e salve. Estes ficaram de fora." })) }));
    }
    if ((l.sem_suporte || []).length) {
      avisos.push(faixa({ tipo: "sigilo", icone: "info", titulo: "Fora do alcance do Helestron",
        texto: el("ul", { classe: "lista-avisos" }, l.sem_suporte.map((s) => el("li", {}, el("span", { classe: "numero", texto: s.numero }), " — ", s.motivo))) }));
    }

    // --- tabela
    const corpo = el("tbody");
    (l.processos || []).forEach((p, i) => {
      const remover = botao({ icone: "x", titulo: `Tirar ${p.numero} do lote`, tamanho: "pequeno", tipo: "texto" });
      const linha = el("tr", {},
        el("td", { classe: "tabular", estilo: { color: "var(--texto-2)", width: "36px" }, texto: String(i + 1) }),
        el("td", { classe: "numero", texto: p.numero }),
        el("td", {}, el("span", { classe: "selo selo-contorno", texto: p.tribunal || "—" })),
        el("td", {}, el("span", { classe: "selo", texto: nomeSistema(p.sistema) })),
        el("td", {}, p.tem_senha ? pilula("Senha na relação", "navy", "chave") : null),
        el("td", { estilo: { textAlign: "right", width: "44px" } }, remover));
      const aplicar = () => {
        const fora = r.removidos.has(p.numero);
        linha.style.opacity = fora ? "0.42" : "";
        linha.querySelector(".numero").style.textDecoration = fora ? "line-through" : "";
        remover.replaceChildren(icone(fora ? "recuperar" : "x"));
        remover.title = fora ? `Devolver ${p.numero} ao lote` : `Tirar ${p.numero} do lote`;
        remover.setAttribute("aria-label", remover.title);
      };
      remover.addEventListener("click", () => {
        if (r.removidos.has(p.numero)) r.removidos.delete(p.numero); else r.removidos.add(p.numero);
        aplicar();
        atualizarContagem();
      });
      aplicar();
      corpo.appendChild(linha);
    });
    const tabela = el("div", { classe: "tabela-rolagem" },
      el("table", { classe: "tabela" },
        el("thead", {}, el("tr", {},
          el("th", { texto: "#" }), el("th", { texto: "Processo" }), el("th", { texto: "Tribunal" }),
          el("th", { texto: "Sistema" }), el("th", { texto: "Senha" }), el("th", {}, el("span", { classe: "oculto-visual", texto: "Ações" })))),
        corpo));

    const revisao = cartao({ classe: "revisao" },
      el("div", { classe: "cartao-cabecalho" },
        el("div", {},
          el("h2", { classe: "cartao-titulo" }, icone("lista"), "Revisão"),
          contagem),
        botao({ rotulo: "Trocar a relação", icone: "recuperar", tamanho: "pequeno", acao: () => { r.etapa = "relacao"; r.leitura = null; r.opcoes = null; desenhar(); } })),
      chips,
      avisos.length ? el("div", { classe: "formulario", estilo: { gap: "10px", margin: "14px 0 6px" } }, avisos) : null,
      (l.processos || []).length ? el("div", { estilo: { marginTop: "14px" } }, tabela)
        : vazio({ compacto: true, icone: "busca", titulo: "Nenhum processo reconhecido", texto: "Troque a relação ou cole os números." }));

    // --- opções
    const nome = el("input", { classe: "campo", id: "nome-lote", maxlength: "80", autocomplete: "off" });
    nome.value = r.nomeLote || nomePadraoDoLote(l);
    nome.addEventListener("input", () => { r.nomeLote = nome.value; });
    const opcao = (chave, titulo, sub) => H.ui.linha({
      titulo, sub,
      acessorio: interruptor({ marcado: r.opcoes[chave], rotulo: titulo, aoMudar: (v) => { r.opcoes[chave] = v; } }),
    });
    const acessosCaixa = el("div", {}, H.ui.esqueleto(1));
    const opcoes = cartao({ classe: "opcoes" },
      cabecalhoCartao("Opções do lote", "engrenagem"),
      el("label", { classe: "rotulo", for: "nome-lote", texto: "Nome do lote (vira o nome da pasta)" }),
      nome,
      el("div", { classe: "grupo-lista", estilo: { marginTop: "16px", boxShadow: "none" } },
        opcao("separar_sigilosos", "Separar os sigilosos", "Processo em segredo de justiça vai para a pasta dos sigilosos, fora do acervo da IA."),
        opcao("rebaixar", "Baixar de novo o que já existe", "Desligado, o processo cujo PDF já está na pasta é pulado."),
        opcao("navegador_visivel", "Mostrar o navegador enquanto baixa", "Útil para acompanhar ou quando o portal pede alguma confirmação.")),
      el("h3", { classe: "grupo-titulo", estilo: { padding: "20px 4px 8px" }, texto: "Acesso aos portais" }),
      acessosCaixa);

    const carregarAcessos = async () => {
      let acessos = [];
      try { acessos = await api.acessos.listar(); } catch (_e) { acessos = []; }
      if (!ctx.vivo) return;
      const portais = Array.from(porPortal.keys()).map((k) => k.split("|")).filter(([, s]) => s === "esaj" || s === "eproc");
      if (!portais.length) { trocar(acessosCaixa); return; }
      trocar(acessosCaixa, el("div", { classe: "grupo-lista", estilo: { boxShadow: "none" } }, portais.map(([tribunal, sistema]) => {
        const portal = `${sistema}:${tribunal}`;
        const a = acessos.find((x) => x.portal === portal);
        const ok = a && a.tem_senha;
        return H.ui.linha({
          icone: ok ? "chave" : "pessoa", cor: ok ? "aco" : "cinza",
          titulo: `${nomeSistema(sistema)} · ${tribunal}`,
          sub: ok ? (a.so_agora ? "Senha só até fechar o Helestron" : "Senha guardada") + (a.usuario ? " · " + a.usuario : "")
            : "Sem senha guardada: o navegador abre para você entrar.",
          acessorio: botao({ rotulo: ok ? "Alterar" : "Cadastrar", tipo: ok ? "texto" : "tonal", tamanho: "pequeno",
            acao: async () => { if (await H.acessos.editar({ portal, rotulo: `${nomeSistema(sistema)} · ${tribunal}`, usuario: a ? a.usuario : "", sistema })) carregarAcessos(); } }),
        });
      })));
    };

    // --- rodapé com a ação principal
    const textoRodape = el("span", { classe: "rodape-acao-texto" });
    const botaoBaixar = botao({
      rotulo: "Baixar", icone: "baixar", tipo: "primario", tamanho: "grande",
      acao: async () => {
        const numeros = ativos().map((p) => p.numero);
        if (!numeros.length) return;
        const nomeLote = (nome.value || "").trim() || nomePadraoDoLote(l);
        const resposta = await api.download.iniciar({ processos: numeros, nome_lote: nomeLote, opcoes: Object.assign({}, r.opcoes) });
        r.tarefaId = resposta.tarefa;
        r.numeros = numeros;
        r.nomeLote = nomeLote;
        r.etapa = "andamento";
        desenhar();
      },
    });
    botaoBaixar.id = "botao-baixar";
    const rodape = el("div", { classe: "rodape-acao" }, textoRodape, botaoBaixar);
    atualizarContagem();

    return {
      conteudo: el("div", { classe: "formulario", estilo: { gap: "16px" } }, revisao, opcoes, rodape),
      pronto: carregarAcessos(),
    };
  }

  // =========================================================== 4. andamento
  function telaAndamento(ctx, desenhar) {
    const r = rascunho();
    const id = r.tarefaId;
    const tarefa = () => H.loja.tarefas.get(id) || { estado: "rodando", progresso: {} };
    const itens = () => {
      const mapa = H.loja.itens.get(id) || new Map();
      const ordem = r.numeros && r.numeros.length ? r.numeros : Array.from(mapa.keys());
      return ordem.map((n) => mapa.get(n) || { numero: n, situacao: "" });
    };

    const anel = H.ui.anel({ tamanho: 88, espessura: 3.2, rotulo: true });
    const titulo = el("h2", { classe: "andamento-titulo" });
    const status = el("p", { classe: "andamento-status", "aria-live": "polite" });
    const contadores = el("div", { classe: "contadores" });
    const acoes = el("div", { classe: "grupo-botoes" });
    const topo = cartao({ classe: "andamento" },
      el("div", { classe: "andamento-topo" }, anel,
        el("div", { classe: "andamento-texto" }, titulo, status, contadores), acoes));

    const corpo = el("tbody");
    const linhas = new Map();
    // Abaixo de 1240 px a coluna Detalhe sai, e a frase vai para baixo da
    // situação (CSS): a tabela cabe sem rolar e o "Abrir o PDF" fica à vista.
    // Se ainda assim rolar, a coluna do botão fica presa à direita, com fundo
    // ('rola'), para não passar por cima do texto sem cobri-lo.
    const rolagem = el("div", { classe: "tabela-rolagem", estilo: { maxHeight: "none" } },
      el("table", { classe: "tabela" },
        el("thead", {}, el("tr", {},
          el("th", { texto: "#" }), el("th", { texto: "Processo" }), el("th", { texto: "Tribunal" }),
          el("th", { texto: "Situação" }), el("th", { classe: "coluna-detalhe", texto: "Detalhe" }), el("th", { classe: "coluna-abrir" }, el("span", { classe: "oculto-visual", texto: "Abrir" })))),
        corpo));
    const marcarRolagem = () => rolagem.classList.toggle("rola", rolagem.scrollWidth > rolagem.clientWidth + 1);
    if (window.ResizeObserver) {
      const observador = new ResizeObserver(marcarRolagem);
      observador.observe(rolagem);
      ctx.aoSair(() => observador.disconnect());
    }
    const tabela = cartao({ classe: "itens-lote" }, cabecalhoCartao("Processos do lote", "lista"), rolagem);

    function desenharItem(item, i) {
      let tr = linhas.get(item.numero);
      if (!tr) {
        tr = el("tr", { dados: { numero: item.numero } });
        linhas.set(item.numero, tr);
        corpo.appendChild(tr);
      }
      const [rotulo, cor] = situacaoDownload(item.situacao);
      const andando = cor === "azul" && !["OK"].includes(String(item.situacao).toUpperCase());
      const sit = el("span", { classe: "pilula pilula-" + cor },
        andando ? el("span", { classe: "girando", estilo: { width: "11px", height: "11px", borderWidth: "1.5px" } }) : null, rotulo);
      trocar(tr,
        el("td", { classe: "tabular", estilo: { color: "var(--texto-2)", width: "36px" }, texto: String(i + 1) }),
        el("td", { classe: "numero" }, item.numero, item.sigiloso ? [" ", icone("cadeado", { tamanho: 14, rotulo: "Segredo de justiça" })] : null),
        el("td", {}, el("span", { classe: "selo selo-contorno", texto: H.cnj.tribunal(item.numero) || "—" })),
        el("td", {}, sit, item.mensagem ? el("span", { classe: "mensagem-item mensagem-sob", texto: item.mensagem }) : null),
        el("td", { classe: "coluna-detalhe" }, el("span", { classe: "mensagem-item", texto: item.mensagem || "" })),
        el("td", { classe: "coluna-abrir" }, item.arquivo
          ? botao({ icone: "externo", titulo: "Abrir o PDF", tamanho: "pequeno", tipo: "texto", acao: () => api.abrir("arquivo", item.arquivo) }) : null));
    }

    function contar(lista) {
      const c = { ok: 0, ja: 0, falhas: 0, sigilosos: 0 };
      for (const it of lista) {
        const s = String(it.situacao || "").toUpperCase();
        if (s === "OK") c.ok++;
        else if (s === "JA_BAIXADO") c.ja++;
        else if (["ERRO", "NAO_ENCONTRADO", "SEM_ACESSO", "NAO_SUPORTADO", "SIGILOSO_SEM_SENHA"].includes(s)) c.falhas++;
        if (it.sigiloso) c.sigilosos++;
      }
      return c;
    }

    function atualizar() {
      const t = tarefa();
      const lista = itens();
      lista.forEach(desenharItem);
      marcarRolagem();
      const p = t.progresso || {};
      const total = p.total || lista.length;
      const feitos = p.feitos || 0;
      const pct = typeof p.percentual === "number" ? p.percentual : total ? (100 * feitos) / total : null;
      const c = contar(lista);
      if (t.estado === "rodando") {
        anel.definir(pct);
        titulo.textContent = total ? `Baixando ${fmt.numero(Math.min(feitos + 1, total))} de ${fmt.numero(total)}` : "Baixando…";
        status.textContent = t.status || "Começando…";
      } else {
        // O anel e o título dizem o mesmo que o aviso do fim: verde só se
        // tudo deu certo; âmbar com falhas; vermelho se nada foi baixado.
        const res0 = t.resultado || {};
        const falhas = Math.max(c.falhas, Number(res0.falhas) || 0);
        const obtidos = Math.max(c.ok + c.ja, (Number(res0.baixados) || 0) + (Number(res0.pulados) || 0));
        const nenhum = t.estado === "concluida" && falhas > 0 && obtidos === 0;
        const comFalhas = t.estado === "concluida" && falhas > 0 && !nenhum;
        anel.definir(100, t.estado === "falhou" || nenhum ? "falhou" : comFalhas ? "alerta" : t.estado === "concluida" ? "concluida" : null);
        titulo.textContent = nenhum ? "Nenhum processo baixado" : comFalhas ? "Lote concluído com falhas"
          : { concluida: "Lote concluído", parada: "Lote interrompido", falhou: "O lote não terminou" }[t.estado] || "Lote encerrado";
        status.textContent = t.estado === "falhou" ? (t.erro || t.status || "") : (t.status || "");
        topo.classList.add("lote-concluido");
      }
      trocar(contadores,
        // Nada baixado num lote que terminou com falhas: sem a pílula verde.
        c.ok || t.estado === "rodando" || !c.falhas ? pilula(`${fmt.numero(c.ok)} ${c.ok === 1 ? "baixado" : "baixados"}`, "verde", "check") : null,
        c.ja ? pilula(`${fmt.numero(c.ja)} já ${c.ja === 1 ? "existia" : "existiam"}`, "cinza") : null,
        c.sigilosos ? pilula(`${fmt.numero(c.sigilosos)} ${c.sigilosos === 1 ? "sigiloso" : "sigilosos"}`, "navy", "cadeado") : null,
        c.falhas ? pilula(`${fmt.numero(c.falhas)} com falha`, "vermelho", "aviso") : null);
      const res = t.resultado || {};
      const pastaLote = res.pasta || (H.loja.estado && H.loja.estado.pastas ? H.loja.estado.pastas.processos : "");
      trocar(acoes,
        t.estado === "rodando"
          ? botao({ rotulo: "Parar", icone: "parar", classe: "botao-perigo-texto", acao: async () => {
            const ok = await folha.confirmar({ titulo: "Parar o download?", mensagem: "O processo atual termina de baixar; o que faltar fica para depois (é retomado no próximo lote com a mesma relação).", confirmar: "Parar", perigo: true });
            if (ok) await api.tarefas.parar(id);
          } }) : null,
        pastaLote ? botao({ rotulo: "Abrir pasta", icone: "pasta", tipo: t.estado === "rodando" ? null : "tonal", acao: () => api.abrir("pasta", pastaLote) }) : null,
        t.estado !== "rodando" && res.relatorio ? botao({ rotulo: "Relatório", icone: "planilha", acao: () => api.abrir("arquivo", res.relatorio) }) : null,
        t.estado !== "rodando" && Array.isArray(res.a_refazer) && res.a_refazer.length
          ? botao({ rotulo: `Tentar de novo (${res.a_refazer.length})`, icone: "recuperar", acao: async () => {
            // O MESMO lote (a mesma pasta, pelo nome dela): o que já foi
            // baixado é pulado, e o programa junta as linhas refeitas ao
            // relatório do lote, sem apagar as dos que já estavam baixados.
            // O nome vem da pasta do lote que terminou, e não do rascunho -
            // que pode ser de outro lote (um começado pela Pauta, por exemplo).
            const nomeLote = String(res.pasta || "").split(/[\\/]/).filter(Boolean).pop() || r.nomeLote;
            const resposta = await api.download.iniciar({ processos: res.a_refazer, nome_lote: nomeLote, opcoes: Object.assign({}, r.opcoes || {}, { rebaixar: false }) });
            r.tarefaId = resposta.tarefa;
            r.numeros = res.a_refazer.slice();
            r.nomeLote = nomeLote;
            desenhar();
          } }) : null,
        t.estado !== "rodando" ? botao({ rotulo: "Novo lote", icone: "mais", tipo: "primario", acao: () => {
          r.etapa = "relacao"; r.leitura = null; r.opcoes = null; r.tarefaId = null; r.numeros = [];
          desenhar();
        } }) : null);
    }

    ctx.on("item", (it) => { if (it.tarefa === id) atualizar(); });
    ctx.on("tarefa", (t) => { if (t.id === id) atualizar(); });
    atualizar();
    // Itens que chegaram antes da tela abrir (ou se a página foi recarregada).
    // A tarefa completa traz os itens que já andaram (página recarregada, ou
    // lote começado pela Pauta antes de esta tela abrir).
    const pronto = (async () => {
      try {
        const t = await api.tarefas.obter(id);
        H.loja.tarefas.set(id, Object.assign({}, H.loja.tarefas.get(id) || {}, t));
        if (Array.isArray(t.itens)) {
          if (!H.loja.itens.has(id)) H.loja.itens.set(id, new Map());
          const mapa = H.loja.itens.get(id);
          t.itens.slice().sort((a, b) => (a.ordem || 0) - (b.ordem || 0))
            .forEach((it) => mapa.set(it.numero, Object.assign({}, mapa.get(it.numero) || {}, it)));
        }
      } catch (_e) { /* a tarefa sumiu: fica o que temos */ }
      if (ctx.vivo) atualizar();
    })();
    return { conteudo: el("div", { classe: "formulario", estilo: { gap: "16px" } }, topo, tabela), pronto };
  }

  // ---------------------------------------------------------------- tela
  H.secoes = H.secoes || {};
  H.secoes.processos = {
    async montar(ctx) {
      const raiz = ctx.raiz;
      const r = rascunho();
      const corrente = downloadEmCurso();
      if (corrente && (r.tarefaId !== corrente.id)) {
        r.tarefaId = corrente.id;
        r.numeros = Array.from((H.loja.itens.get(corrente.id) || new Map()).keys());
        r.etapa = "andamento";
      }
      const cab = H.ui.cabecalho({
        titulo: "Processos",
        subtitulo: "Os autos de uma relação inteira: um PDF por processo, nomeado pelo número.",
      });
      const zonaEtapas = el("div");
      const zona = el("div");
      raiz.append(cab, zonaEtapas, zona);

      let telaCtx = null;
      const desenhar = () => {
        // Cada etapa tem o seu sub-contexto: ao trocar, os ouvintes da anterior saem.
        if (telaCtx) telaCtx.limpar();
        telaCtx = filho(ctx);
        trocar(zonaEtapas, etapas(r.etapa));
        const tela = r.etapa === "andamento" && r.tarefaId ? telaAndamento(telaCtx, desenhar)
          : r.etapa === "revisao" && r.leitura ? telaRevisao(telaCtx, desenhar)
            : telaRelacao(telaCtx, desenhar);
        trocar(zona, tela.conteudo);
        document.getElementById("conteudo").scrollTop = 0;
        return tela.pronto;
      };
      ctx.aoSair(() => telaCtx && telaCtx.limpar());
      // Um download começado em outra tela (Pauta) puxa esta para o andamento.
      ctx.on("tarefa", (t) => {
        if (t.tipo === "download" && t.estado === "rodando" && r.tarefaId !== t.id && r.etapa !== "revisao") {
          r.tarefaId = t.id;
          r.numeros = [];
          r.etapa = "andamento";
          desenhar();
        }
      });
      await desenhar();
    },
  };

  /** Contexto filho: as inscrições morrem com ele ou com o pai. */
  function filho(pai) {
    const desfazer = [];
    const c = {
      vivo: true,
      on(tipo, fn) { const off = pai.on(tipo, (d) => { if (c.vivo) fn(d); }); desfazer.push(off); return off; },
      aoSair(fn) { desfazer.push(fn); },
      limpar() { c.vivo = false; desfazer.splice(0).forEach((f) => { try { f(); } catch (_e) { /* nada */ } }); },
    };
    Object.defineProperty(c, "vivo", { get: () => c._vivo !== false && pai.vivo, set: (v) => { c._vivo = v; } });
    return c;
  }
  H.contextoFilho = filho;
})();
