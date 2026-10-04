/* Helestron — Início (especificação 7.2).
 *
 * Saudação e data; os quatro cartões grandes das funções; "Hoje na pauta",
 * "Atividade recente" (lotes e transcrições) e "Primeiros passos" (o que
 * ainda falta configurar), como lista de verificação.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, botao, cartao, cabecalhoCartao, vazio, blocoIcone, pilulaSituacao, seloTipo, trocar } = H.ui;
  const { fmt, api } = H;

  // Os passos de configuração que o Início acompanha. Cada um está feito
  // enquanto o servidor não manda uma pendência com a mesma chave.
  const PASSOS = [
    { chave: "acessos", titulo: "Cadastrar o acesso aos portais", sub: "Usuário e senha do e-SAJ e do eProc, guardados cifrados pelo Windows.", acao: "ajustes/acessos" },
    { chave: "pastas", titulo: "Conferir as pastas", sub: "O acervo vai para a IA; os sigilosos ficam sempre fora dele.", acao: "ajustes/pastas" },
    { chave: "modelo", titulo: "Preparar a transcrição", sub: "Modelo de transcrição instalado neste computador.", acao: "ajustes/transcricao" },
    { chave: "pauta", titulo: "Configurar a pauta de audiências", sub: "Sincronizada com o e-SAJ e o eProc.", acao: "pauta" },
  ];

  function rotaDaAcao(acao) {
    return String(acao || "inicio").replace("#", "/");
  }

  function nomeUsuario() {
    const nome = H.app.valorConfig("geral", "nome_usuario", "") || (H.loja.estado && H.loja.estado.usuario) || "";
    return String(nome || "").trim();
  }

  // ------------------------------------------------------------ cartões
  function cartoesFuncoes(resumo) {
    const r = resumo || {};
    const pauta = r.pauta || {};
    const definicoes = [
      {
        rota: "processos", icone: "doc-baixar", cor: "navy",
        titulo: "Baixar processos",
        texto: "Os autos de uma relação inteira, um PDF por processo, com o número no nome.",
        meta: [el("strong", { texto: fmt.numero(r.processos || 0) }), r.processos === 1 ? " processo no acervo" : " processos no acervo"],
        botao: "Baixar",
      },
      {
        rota: "audiencias", icone: "microfone", cor: "azul",
        titulo: "Transcrever audiência",
        texto: "Transcrição simultânea, feita no próprio computador, sem enviar o áudio a ninguém.",
        meta: [el("strong", { texto: fmt.numero(r.transcricoes || 0) }), r.transcricoes === 1 ? " transcrição" : " transcrições"],
        botao: "Transcrever",
      },
      {
        rota: "pauta", icone: "calendario", cor: "ciano",
        titulo: "Pauta de audiências",
        texto: "A pauta do e-SAJ e do eProc acompanhada de perto, com exportação para o Excel.",
        meta: [el("strong", { texto: fmt.numero(pauta.hoje || 0) }), " hoje · ", el("strong", { texto: fmt.numero(pauta.semana || 0) }), " nos próximos 7 dias"],
        botao: "Ver a pauta",
      },
      {
        rota: "compartilhar", icone: "brilho", cor: "indigo",
        titulo: "Compartilhar com IA",
        texto: "O acervo pronto para o Claude e o ChatGPT, sem anexar arquivo por arquivo.",
        meta: [icone("cadeado", { tamanho: 14 }), " Sigilosos nunca vão para a IA"],
        botao: "Compartilhar",
      },
    ];
    return el("div", { classe: "funcoes" }, definicoes.map((d) =>
      el("a", {
        classe: "cartao cartao-funcao", href: "#/" + d.rota, dados: { funcao: d.rota },
      },
      blocoIcone(d.icone, d.cor, true),
      el("span", { classe: "cartao-funcao-titulo", texto: d.titulo }),
      el("span", { classe: "cartao-funcao-texto", texto: d.texto }),
      el("span", { classe: "cartao-funcao-rodape" },
        el("span", { classe: "cartao-funcao-meta" }, d.meta),
        el("span", { classe: "botao botao-tonal botao-pequeno", "aria-hidden": "true" }, d.botao, icone("chevron-direita"))))));
  }

  // ------------------------------------------------------- hoje na pauta
  function hojeNaPauta(dados, resumo) {
    const caixa = cartao({ classe: "hoje-na-pauta", aria: { label: "Hoje na pauta" } },
      cabecalhoCartao("Hoje na pauta", "calendario",
        botao({ rotulo: "Ver a pauta", tipo: "texto", tamanho: "pequeno", acao: () => H.app.ir("pauta") })));
    const pauta = (resumo && resumo.pauta) || {};
    if (dados === null) {
      caixa.appendChild(H.ui.esqueleto(3));
      return caixa;
    }
    const lista = (dados.audiencias || []).slice().sort((a, b) => String(a.hora).localeCompare(String(b.hora)));
    if (!lista.length) {
      const nuncaSincronizou = !pauta.ultima_sincronizacao && !(dados.resumo && dados.resumo.total);
      if (nuncaSincronizou && !pauta.proxima) {
        caixa.appendChild(vazio({
          compacto: true, icone: "calendario", titulo: "A pauta ainda não foi configurada",
          texto: "Sincronize com o e-SAJ e o eProc para ver aqui as audiências do dia.",
          acoes: [botao({ rotulo: "Configurar a pauta", tipo: "tonal", tamanho: "pequeno", acao: () => H.app.ir("pauta") })],
        }));
      } else {
        const p = pauta.proxima;
        const texto = p ? `Próxima: ${fmt.diaLongo(p.data).toLowerCase()}, às ${fmt.horaFalada(p.hora)} — ${p.tipo}.` : "Nenhuma audiência designada nos próximos dias.";
        caixa.appendChild(vazio({ compacto: true, icone: "check-circulo", titulo: "Nenhuma audiência hoje", texto }));
      }
      return caixa;
    }
    const itens = el("div", { classe: "lista-simples" });
    for (const a of lista.slice(0, 5)) {
      const transcrever = () => H.app.ir(`audiencias?processo=${encodeURIComponent(a.processo)}&tipo=${encodeURIComponent(a.tipo || "")}${a.sigiloso ? "&sigiloso=1" : ""}`);
      itens.appendChild(el("button", {
        type: "button", classe: "item-simples", on: { click: transcrever },
        aria: { label: `Transcrever a audiência das ${a.hora}, processo ${a.processo}` },
      },
      el("span", { classe: "item-hora", texto: a.hora || "—" }),
      el("span", { classe: "item-texto" },
        el("span", { classe: "item-titulo numero" }, a.processo || "Processo não identificado",
          a.sigiloso ? [" ", icone("cadeado", { tamanho: 14, rotulo: "Segredo de justiça" })] : null),
        el("span", { classe: "item-sub", texto: [a.tipo, a.partes].filter(Boolean).join(" · ") })),
      pilulaSituacao(a.situacao)));
    }
    caixa.appendChild(itens);
    if (lista.length > 5) {
      caixa.appendChild(el("p", { classe: "cartao-sub", estilo: { marginTop: "8px" } },
        `E mais ${lista.length - 5} ${lista.length - 5 === 1 ? "audiência" : "audiências"} hoje.`));
    }
    return caixa;
  }

  // ---------------------------------------------------- primeiros passos
  function primeirosPassos(estado) {
    const pendencias = (estado && estado.pendencias) || [];
    const porChave = new Map(pendencias.map((p) => [p.chave, p]));
    const extras = pendencias.filter((p) => !PASSOS.some((s) => s.chave === p.chave));
    if (!pendencias.length) return null;
    const itens = [];
    for (const p of extras) itens.push({ feito: false, titulo: p.titulo || "Atenção", sub: p.mensagem, acao: p.acao, rotuloAcao: "Resolver" });
    for (const s of PASSOS) {
      const p = porChave.get(s.chave);
      itens.push(p
        ? { feito: false, titulo: p.titulo || s.titulo, sub: p.mensagem || s.sub, acao: p.acao || s.acao, rotuloAcao: "Resolver" }
        : { feito: true, titulo: s.titulo, sub: s.sub });
    }
    const feitos = itens.filter((i) => i.feito).length;
    return cartao({ classe: "primeiros-passos", aria: { label: "Primeiros passos" } },
      cabecalhoCartao("Primeiros passos", "check-circulo",
        el("span", { classe: "progresso-passos", texto: `${feitos} de ${itens.length}` })),
      el("div", { classe: "passos" }, itens.map((i) =>
        el("div", { classe: "passo" + (i.feito ? " feito" : "") },
          el("span", { classe: "passo-marca", "aria-hidden": "true" }, i.feito ? icone("check") : null),
          el("span", { classe: "passo-texto" },
            el("span", { classe: "passo-titulo", texto: i.titulo }),
            el("span", { classe: "oculto-visual", texto: i.feito ? "Feito." : "Pendente." }),
            i.sub ? el("span", { classe: "passo-sub", texto: i.sub }) : null),
          i.feito ? null : botao({ rotulo: i.rotuloAcao, tipo: "tonal", tamanho: "pequeno", acao: () => H.app.ir(rotaDaAcao(i.acao)) })))));
  }

  // --------------------------------------------------- atividade recente
  function atividadeRecente(resumo) {
    const r = resumo || {};
    const itens = [];
    for (const l of r.ultimos_lotes || []) {
      const sub = `${fmt.numero(l.baixados)} de ${fmt.plural(l.total, "processo", "processos")} baixados` + (l.falhas ? ` · ${fmt.plural(l.falhas, "falha", "falhas")}` : "");
      itens.push({
        quando: l.quando, icone: "doc-baixar", cor: "navy", titulo: `Lote “${l.nome}”`, sub,
        acao: () => api.abrir("pasta", l.pasta), rotulo: `Abrir a pasta do lote ${l.nome}`,
      });
    }
    for (const t of r.transcricoes_recentes || []) {
      itens.push({
        quando: t.quando, icone: "microfone", cor: "azul", titulo: "Audiência transcrita", sub: t.numero,
        acao: () => api.abrir("arquivo", t.arquivo), rotulo: `Abrir a transcrição do processo ${t.numero}`, numero: true,
      });
    }
    itens.sort((a, b) => String(b.quando).localeCompare(String(a.quando)));
    const caixa = cartao({ classe: "atividade-recente", aria: { label: "Atividade recente" } },
      cabecalhoCartao("Atividade recente", "relogio"));
    if (!itens.length) {
      caixa.appendChild(vazio({ compacto: true, icone: "relogio", titulo: "Nada por aqui ainda", texto: "Os lotes baixados e as audiências transcritas aparecem aqui." }));
      return caixa;
    }
    caixa.appendChild(el("div", { classe: "lista-simples" }, itens.slice(0, 5).map((i) =>
      el("button", { type: "button", classe: "item-simples", on: { click: () => i.acao().catch((e) => H.ui.folha.erro(e)) }, aria: { label: i.rotulo } },
        blocoIcone(i.icone, i.cor),
        el("span", { classe: "item-texto" },
          el("span", { classe: "item-titulo", texto: i.titulo }),
          el("span", { classe: "item-sub" + (i.numero ? " numero" : ""), texto: i.sub })),
        el("span", { classe: "item-quando", texto: fmt.relativo(i.quando) })))));
    return caixa;
  }

  // ---------------------------------------------------------------- tela
  H.secoes = H.secoes || {};
  H.secoes.inicio = {
    async montar(ctx) {
      const raiz = ctx.raiz;
      let estado = H.loja.estado;
      if (!estado) estado = await H.app.recarregarEstado();
      try {
        await H.app.carregarConfig();
      } catch (_e) { /* a saudação fica sem o nome */ }

      const nome = nomeUsuario();
      const cab = H.ui.cabecalho({
        titulo: H.saudacao() + (nome ? ", " + nome : ""),
        subtitulo: fmt.diaLongoAno(new Date()),
      });
      const zonaCartoes = el("div");
      const esquerda = el("div", { classe: "coluna" });
      const direita = el("div", { classe: "coluna" });
      raiz.append(cab, zonaCartoes, el("div", { classe: "inicio-baixo" }, esquerda, direita));

      let pautaHoje = null;
      const desenhar = () => {
        const e = H.loja.estado || estado;
        trocar(zonaCartoes, cartoesFuncoes(e.resumo));
        trocar(esquerda, hojeNaPauta(pautaHoje, e.resumo));
        trocar(direita, primeirosPassos(e), atividadeRecente(e.resumo));
      };

      const carregarPauta = async () => {
        const hoje = fmt.iso(new Date());
        try {
          pautaHoje = await api.pauta.listar({ de: hoje, ate: hoje });
        } catch (_e) {
          pautaHoje = { audiencias: [], resumo: { total: 0 } };
        }
      };

      desenhar();
      await carregarPauta();
      if (!ctx.vivo) return;
      desenhar();

      ctx.on("resumo", () => desenhar());
      ctx.on("pauta", async () => { await carregarPauta(); desenhar(); });
      // A saudação acompanha o relógio (a janela fica aberta o dia todo).
      ctx.cada(60000, () => {
        cab.titulo.textContent = H.saudacao() + (nomeUsuario() ? ", " + nomeUsuario() : "");
        cab.subtitulo.textContent = fmt.diaLongoAno(new Date());
      });
    },
  };
})();
