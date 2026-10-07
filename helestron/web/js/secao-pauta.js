/* Helestron — Pauta de audiências (especificação 8.8).
 *
 * Cabeçalho com o período (Hoje · Semana · Mês · Período), filtros de
 * sistema e situação e a busca; resumo em "chips"; lista agrupada por dia,
 * cada audiência com hora, número (copiável), tipo, partes, local e situação,
 * e as ações Baixar autos, Transcrever e Abrir link. Ao lado: monitoramento,
 * alterações recentes e as outras formas de trazer a pauta (capturar no
 * portal, importar relatório). Sincronizar e Exportar Excel no topo.
 *
 * Os filtros ficam em Helestron.loja.pautaFiltro: voltar à tela mantém o
 * que estava escolhido.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, botao, cartao, cabecalhoCartao, vazio, faixa, interruptor, trocar, folha, aviso, blocoIcone, pilula, pilulaSituacao, seloTipo, nomeSistema } = H.ui;
  const { fmt, api } = H;

  const SITUACOES = ["Designada", "Realizada", "Cancelada", "Redesignada", "Não realizada", "Suspensa"];
  const INTERVALOS = [1, 2, 3, 6, 12, 24];
  const TIPOS_RELATORIO = ["Relatórios da pauta|*.xlsx;*.xls;*.ods;*.csv;*.html;*.htm;*.pdf;*.docx", "Todos os arquivos|*.*"];
  const ACEITAR_RELATORIO = ".xlsx,.xls,.ods,.csv,.html,.htm,.pdf,.docx";
  const NOME_CAMPO = { data: "Data", hora: "Hora", tipo: "Tipo", situacao: "Situação", local: "Local", link: "Link", partes: "Partes", magistrado: "Magistrado", classe: "Classe", observacoes: "Observações", processo: "Processo" };

  // ------------------------------------------------------------ período
  function filtro() {
    if (!H.loja.pautaFiltro) {
      H.loja.pautaFiltro = { periodo: "semana", base: fmt.iso(new Date()), de: "", ate: "", sistema: "", situacao: "", busca: "", soMudancas: false };
    }
    return H.loja.pautaFiltro;
  }

  /** De e até do período escolhido, a partir da data-base (que as setas movem). */
  function intervalo(f) {
    const base = fmt.lerData(f.base) || new Date();
    if (f.periodo === "hoje") return [base, base];
    if (f.periodo === "semana") return [base, fmt.somarDias(base, 6)];
    if (f.periodo === "mes") {
      return [new Date(base.getFullYear(), base.getMonth(), 1), new Date(base.getFullYear(), base.getMonth() + 1, 0)];
    }
    const de = fmt.lerData(f.de) || base;
    const ate = fmt.lerData(f.ate) || fmt.somarDias(de, 30);
    return de <= ate ? [de, ate] : [ate, de];
  }

  function mover(f, sentido) {
    const base = fmt.lerData(f.base) || new Date();
    if (f.periodo === "hoje") f.base = fmt.iso(fmt.somarDias(base, sentido));
    else if (f.periodo === "semana") f.base = fmt.iso(fmt.somarDias(base, 7 * sentido));
    else if (f.periodo === "mes") f.base = fmt.iso(new Date(base.getFullYear(), base.getMonth() + sentido, 1));
  }

  function rotuloPeriodo(f) {
    const [de, ate] = intervalo(f);
    const hoje = new Date();
    if (f.periodo === "hoje") {
      const s = fmt.diaLongo(de);
      return fmt.mesmoDia(de, hoje) ? "Hoje, " + s.charAt(0).toLowerCase() + s.slice(1) : s;
    }
    if (f.periodo === "mes") return fmt.maiuscula(new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(de));
    if (de.getMonth() === ate.getMonth() && de.getFullYear() === ate.getFullYear()) {
      return `${de.getDate()} a ${ate.getDate()} de ${new Intl.DateTimeFormat("pt-BR", { month: "long" }).format(ate)}`;
    }
    return `${fmt.dataCurta(de)} a ${fmt.dataCurta(ate)}`;
  }

  // ------------------------------------------------------------ escolher a fonte
  /** Tribunal + sistema (para sincronizar a primeira vez ou capturar). */
  async function escolherFonte({ titulo, mensagem, confirmar, comRotulo }) {
    let tribunais = [];
    try { tribunais = await api.tribunais(); } catch (_e) { tribunais = []; }
    const opcoes = [];
    for (const t of tribunais) {
      if (t.sistema === "esaj" || t.sistema === "eproc") opcoes.push([t.sigla, t.sistema, t.nome]);
      if (t.alternativo === "esaj" || t.alternativo === "eproc") opcoes.push([t.sigla, t.alternativo, t.nome]);
    }
    if (!opcoes.length) opcoes.push(["TJAL", "esaj", "Tribunal de Justiça — Alagoas"], ["TJAL", "eproc", "Tribunal de Justiça — Alagoas"]);
    const preferido = String(H.app.valorConfig("unidade", "tribunal", "") || "");
    const campo = el("select", { classe: "campo", id: "fonte-portal" }, opcoes.map(([sigla, sistema, nome], i) =>
      el("option", { value: String(i), texto: `${sigla} · ${nomeSistema(sistema)} — ${nome}` })));
    const iPreferido = opcoes.findIndex(([sigla, , nome]) => preferido && (preferido.includes(sigla) || preferido === nome));
    if (iPreferido >= 0) campo.value = String(iPreferido);
    const rotulo = el("input", { classe: "campo", id: "fonte-rotulo", placeholder: "Ex.: 2ª Vara Cível da Capital", maxlength: "80" });
    const conteudo = [el("div", {}, el("label", { classe: "rotulo", for: "fonte-portal", texto: "Portal" }), campo)];
    if (comRotulo) conteudo.push(el("div", {}, el("label", { classe: "rotulo", for: "fonte-rotulo", texto: "Nome para reconhecer (opcional)" }), rotulo));
    const f = folha.abrir({
      titulo, mensagem, icone: "predio", conteudo,
      botoes: [{ rotulo: "Cancelar" }, { rotulo: confirmar, tipo: "primario", padrao: true, acao: () => {
        const [sigla, sistema] = opcoes[Number(campo.value)];
        return { tribunal: sigla, sistema, rotulo: rotulo.value.trim() || `${nomeSistema(sistema)} · ${sigla}` };
      } }],
    });
    return f.resultado;
  }

  // ------------------------------------------------------------ linha da audiência
  function linhaAudiencia(a, acoes) {
    const cancelada = a.situacao === "Cancelada";
    const copiar = el("button", {
      type: "button", classe: "numero-processo", title: "Copiar o número",
      aria: { label: `Processo ${a.processo}. Copiar o número` },
      on: { click: () => H.ui.copiar(a.processo, "Número copiado") },
    }, a.processo || "Processo não identificado", icone("copiar"));
    const local = a.local ? el("span", {}, icone(/virtual/i.test(a.local) ? "video" : "local"), a.local) : null;
    const meta = el("div", { classe: "audiencia-meta" },
      local,
      a.classe ? el("span", { texto: a.classe }) : null,
      a.observacoes ? el("span", { estilo: { fontStyle: "italic" }, texto: a.observacoes }) : null);
    const botoes = el("div", { classe: "audiencia-acoes" },
      a.processo ? botao({ icone: "doc-baixar", tipo: "texto", tamanho: "pequeno", titulo: "Baixar os autos", acao: () => acoes.baixar(a) }) : null,
      a.processo && !cancelada ? botao({ icone: "microfone", tipo: "texto", tamanho: "pequeno", titulo: "Transcrever a audiência", acao: () => acoes.transcrever(a) }) : null,
      a.link ? botao({ icone: "video", tipo: "texto", tamanho: "pequeno", titulo: "Abrir o link da audiência", acao: () => api.abrir("url", a.link) }) : null);
    return el("div", { classe: "audiencia" + (cancelada ? " cancelada" : ""), dados: { id: a.id }, role: "listitem" },
      el("span", { classe: "audiencia-hora", texto: a.hora || "—" }),
      el("div", { classe: "audiencia-corpo" },
        el("div", { classe: "audiencia-linha1" },
          copiar, seloTipo(a.tipo),
          el("span", { classe: "selo selo-contorno", texto: nomeSistema(a.sistema) + (a.tribunal ? " · " + a.tribunal : "") }),
          a.sigiloso ? el("span", { classe: "selo", title: "Segredo de justiça" }, icone("cadeado", { tamanho: 13 }), "Sigiloso") : null),
        a.partes ? el("div", { classe: "audiencia-partes", title: a.partes, texto: a.partes }) : null,
        meta.childNodes.length ? meta : null),
      el("div", { classe: "audiencia-lado" }, pilulaSituacao(a.situacao), botoes));
  }

  // ------------------------------------------------------------ alterações
  function descricaoAlteracao(alt) {
    const a = alt.audiencia || {};
    const quando = [a.data ? fmt.dataCurta(a.data) : "", a.hora].filter(Boolean).join(", ");
    const base = [a.processo, quando].filter(Boolean).join(" · ");
    const campos = (alt.campos || []).map((c) => `${NOME_CAMPO[c.campo] || fmt.maiuscula(c.campo)}: ${c.antes || "—"} → ${c.depois || "—"}`);
    return { titulo: { nova: "Nova audiência", alterada: "Audiência alterada", cancelada: "Audiência cancelada", removida: "Saiu da pauta" }[alt.tipo] || "Alteração", sub: [base, a.tipo].filter(Boolean).join(" · "), campos };
  }

  const COR_ALTERACAO = { nova: ["mais", "cor-azul"], alterada: ["lapis", "cor-navy"], cancelada: ["x", "cor-cinza"], removida: ["lixeira", "cor-ardosia"] };

  function itemAlteracao(alt, naoVista) {
    const d = descricaoAlteracao(alt);
    const [nomeIcone, cor] = COR_ALTERACAO[alt.tipo] || ["info", "cor-cinza"];
    return el("div", { classe: "alteracao" + (naoVista ? " nao-vista" : "") },
      el("span", { classe: "alteracao-icone " + cor }, icone(nomeIcone)),
      el("div", { classe: "alteracao-texto" },
        el("span", { classe: "alteracao-titulo", texto: d.titulo }),
        el("span", { classe: "alteracao-sub", texto: d.sub }),
        d.campos.map((c) => el("span", { classe: "alteracao-sub", texto: c })),
        el("span", { classe: "alteracao-sub", estilo: { marginTop: "2px" }, texto: fmt.relativo(alt.quando) })));
  }

  H.pauta = { escolherFonte };

  // ================================================================= tela
  H.secoes = H.secoes || {};
  H.secoes.pauta = {
    async montar(ctx) {
      const raiz = ctx.raiz;
      const f = filtro();
      try { await H.app.carregarConfig(); } catch (_e) { /* padrões */ }

      let dados = null;           // último GET /api/pauta
      let alteracoes = [];
      let fontes = [];
      let tarefaSinc = null;      // id da sincronização/captura acompanhada
      // A pessoa começou a tarefa acompanhada com um clique nesta tela? Só
      // então o resultado é trazido à vista: a do monitoramento automático
      // (mesmo tipo) termina sem mexer na rolagem de quem está lendo a lista.
      let trazerResultado = false;
      let ultimaMostrada = null;  // a tarefa cujo resultado já foi para a faixa

      // ---------------------------------------------- cabeçalho
      const botaoSincronizar = botao({ rotulo: "Sincronizar", icone: "sincronizar", tipo: "primario", acao: () => sincronizar() });
      botaoSincronizar.id = "botao-sincronizar";
      const botaoExportar = botao({ rotulo: "Exportar Excel", icone: "planilha", acao: () => exportar() });
      botaoExportar.id = "botao-exportar";
      const cab = H.ui.cabecalho({ titulo: "Pauta", subtitulo: "Audiências do e-SAJ e do eProc, acompanhadas de perto.", acoes: [botaoExportar, botaoSincronizar] });

      // ---------------------------------------------- barra de filtros
      const periodo = H.ui.segmentado({
        rotulo: "Período", valor: f.periodo,
        opcoes: [{ valor: "hoje", rotulo: "Hoje" }, { valor: "semana", rotulo: "Semana" }, { valor: "mes", rotulo: "Mês" }, { valor: "periodo", rotulo: "Período" }],
        aoMudar: (v) => {
          if (v === "periodo" && !f.de) {
            const [de, ate] = intervalo(f);
            f.de = fmt.iso(de);
            f.ate = fmt.iso(ate);
          }
          f.periodo = v;
          if (v !== "periodo") f.base = fmt.iso(new Date());
          desenharFiltros();
          carregar();
        },
      });
      periodo.id = "periodo-pauta";
      const anterior = botao({ icone: "chevron-esquerda", tamanho: "pequeno", tipo: "texto", titulo: "Período anterior", acao: () => { mover(f, -1); desenharFiltros(); carregar(); } });
      const proximo = botao({ icone: "chevron-direita", tamanho: "pequeno", tipo: "texto", titulo: "Próximo período", acao: () => { mover(f, 1); desenharFiltros(); carregar(); } });
      const rotuloIntervalo = el("strong", { classe: "pauta-intervalo", estilo: { fontSize: "14px", color: "var(--navy-900)", whiteSpace: "nowrap" } });
      const datas = el("span", { classe: "periodo-livre" });
      const deCampo = el("input", { type: "date", classe: "campo campo-data", aria: { label: "De" } });
      const ateCampo = el("input", { type: "date", classe: "campo campo-data", aria: { label: "Até" } });
      const aoMudarData = () => { f.de = deCampo.value; f.ate = ateCampo.value; if (f.de && f.ate) { desenharFiltros(); carregar(); } };
      deCampo.addEventListener("change", aoMudarData);
      ateCampo.addEventListener("change", aoMudarData);
      datas.append(deCampo, "a", ateCampo);
      const navegacao = el("span", { classe: "periodo-livre" }, anterior, rotuloIntervalo, proximo);

      const sistema = el("select", { classe: "campo", id: "filtro-sistema", aria: { label: "Sistema" } },
        el("option", { value: "", texto: "Todos os sistemas" }), el("option", { value: "esaj", texto: "e-SAJ" }), el("option", { value: "eproc", texto: "eProc" }));
      sistema.value = f.sistema;
      sistema.addEventListener("change", () => { f.sistema = sistema.value; carregar(); });
      const situacao = el("select", { classe: "campo", id: "filtro-situacao", aria: { label: "Situação" } },
        el("option", { value: "", texto: "Todas as situações" }), SITUACOES.map((s) => el("option", { value: s, texto: s })));
      situacao.value = f.situacao;
      situacao.addEventListener("change", () => { f.situacao = situacao.value; f.soMudancas = false; carregar(); });
      const busca = el("input", { type: "search", classe: "campo", id: "busca-pauta", placeholder: "Buscar processo, parte ou local", aria: { label: "Buscar na pauta" } });
      busca.value = f.busca;
      busca.addEventListener("input", H.ui.debounce(() => { f.busca = busca.value.trim(); carregar(); }, 260));
      const barra = cartao({ classe: "barra-ferramentas", role: "search" },
        periodo, navegacao, datas, sistema, situacao, el("div", { classe: "busca" }, icone("busca"), busca));

      function desenharFiltros() {
        periodo.definir(f.periodo);
        const livre = f.periodo === "periodo";
        datas.hidden = !livre;
        navegacao.hidden = livre;
        if (livre) { deCampo.value = f.de; ateCampo.value = f.ate; }
        rotuloIntervalo.textContent = rotuloPeriodo(f);
      }

      // ---------------------------------------------- resumo, lista, lateral
      const faixaTarefa = el("div");
      // scroll-margin: trazida à vista (trazerAVista), a faixa não cola no topo da janela.
      const faixaResultado = el("div", { id: "resultado-pauta", aria: { live: "polite" }, estilo: { scrollMarginTop: "18px" } });
      const chips = el("div", { classe: "chips", id: "chips-pauta" });
      const lista = el("div", { classe: "pauta-lista", id: "lista-pauta", role: "list", aria: { label: "Audiências" } }, H.ui.esqueleto(5));
      const monitor = cartao({ classe: "monitoramento" });
      const painelAlteracoes = cartao({ classe: "alteracoes" });
      const trazer = cartao({ classe: "trazer-pauta" });
      const lateral = el("aside", { classe: "pauta-lateral", aria: { label: "Monitoramento e alterações" } }, monitor, painelAlteracoes, trazer);
      // Em janela estreita, a coluna das alterações vai para baixo da lista: um
      // lembrete no topo avisa que há novidade e leva até ela.
      const lembrete = el("div", { classe: "so-estreito" });
      const principal = el("div", { classe: "pauta-principal" }, lembrete, chips, el("div", { estilo: { height: "14px" } }), lista);
      const grade = el("div", { classe: "pauta-grade" }, principal, lateral);
      raiz.append(cab, barra, faixaTarefa, faixaResultado, grade);
      desenharFiltros();

      // ---------------------------------------------- ações
      const acoesLinha = {
        baixar: async (a) => {
          const r = await api.pauta.baixarAutos({ ids: [a.id], de: a.data, ate: a.data });
          aviso({ titulo: "Baixando os autos", mensagem: a.processo, tipo: "info", acoes: [{ rotulo: "Ver o andamento", acao: () => H.app.ir("processos") }] });
          return r;
        },
        transcrever: (a) => H.app.ir(`audiencias?processo=${encodeURIComponent(a.processo)}&tipo=${encodeURIComponent(a.tipo || "")}${a.sigiloso ? "&sigiloso=1" : ""}`),
      };

      async function sincronizar() {
        let lista_ = fontes;
        try { lista_ = await api.pauta.fontes(); fontes = lista_; } catch (_e) { /* tenta assim mesmo */ }
        if (!lista_.length) {
          const escolha = await escolherFonte({
            titulo: "De onde vem a sua pauta?", confirmar: "Sincronizar", comRotulo: true,
            mensagem: "Escolha o portal. O Helestron entra com o acesso cadastrado em Ajustes, procura a pauta de audiências e a traz para cá. Se o portal pedir código, uma janela pede que você o digite.",
          });
          if (!escolha) return;
          await api.pauta.salvarFonte(escolha);
        }
        const r = await api.pauta.sincronizar({});
        acompanhar(r.tarefa, true);
      }

      async function capturar() {
        const escolha = await escolherFonte({
          titulo: "Capturar a pauta no portal", confirmar: "Abrir o portal",
          mensagem: "O portal abre no navegador, já com o seu acesso. No topo da página aparece a barra do Helestron: vá até a pauta de audiências e clique em “Capturar esta tela” (em cada página, se houver mais de uma). No fim, clique em “Concluir” — o endereço fica lembrado para o monitoramento.",
        });
        if (!escolha) return;
        const r = await api.pauta.capturar(escolha.tribunal, escolha.sistema);
        acompanhar(r.tarefa, true);
      }

      async function importar() {
        const escolha = await api.escolherArquivo({ titulo: "Escolha o relatório da pauta", tipos: TIPOS_RELATORIO, aceitar: ACEITAR_RELATORIO });
        if (!escolha) return;
        const r = await api.pauta.importar(escolha);
        const total = typeof r.total === "number" ? r.total : (r.novas || 0) + (r.atualizadas || 0);
        const partes = [fmt.plural(total, "audiência lida", "audiências lidas"), fmt.plural(r.novas || 0, "nova", "novas"), fmt.plural(r.atualizadas || 0, "atualizada", "atualizadas")];
        if (r.ignoradas) partes.push(`${fmt.plural(r.ignoradas, "linha ignorada", "linhas ignoradas")}`);
        const resumo = (r.arquivo ? r.arquivo + ": " : "") + partes.join(" · ") + ".";
        const avisos = r.avisos || [];
        mostrarResultado({
          tipo: total ? (avisos.length ? "aviso" : "ok") : "aviso", icone: "importar",
          titulo: total ? "Relatório importado" : "Nenhuma audiência no relatório",
          texto: total ? resumo : (r.arquivo ? r.arquivo + ": " : "") + "o Helestron não reconheceu nenhuma audiência neste arquivo. Confira se é o relatório da pauta (com as colunas de data e processo).",
          lista: avisos,
          tituloLista: avisos.length === 1 ? "Um aviso" : `${avisos.length} avisos`,
          trazer: true,
        });
        await carregar();
      }

      async function exportar() {
        const [de0, ate0] = intervalo(f);
        const de = el("input", { type: "date", classe: "campo", id: "exportar-de" });
        const ate = el("input", { type: "date", classe: "campo", id: "exportar-ate" });
        de.value = fmt.iso(de0);
        ate.value = fmt.iso(ate0);
        const partesSig = interruptor({ marcado: H.app.flag(H.app.valorConfig("pauta", "incluir_partes_sigilosos", "false")), rotulo: "Incluir as partes e as observações dos processos sigilosos" });
        const filtrosAtivos = [
          f.sistema ? "sistema " + nomeSistema(f.sistema) : "",
          f.situacao ? "situação " + f.situacao : "",
          f.busca ? `busca “${f.busca}”` : "",
        ].filter(Boolean);
        const pastaPauta = H.loja.estado && H.loja.estado.pastas ? H.loja.estado.pastas.pauta : "";
        const fo = folha.abrir({
          titulo: "Exportar a pauta para o Excel", icone: "planilha",
          mensagem: "Planilha com as abas Pauta, Resumo e Alterações, pronta para imprimir ou filtrar.",
          conteudo: [
            el("div", { classe: "linha-campos", estilo: { gridTemplateColumns: "1fr 1fr" } },
              el("div", {}, el("label", { classe: "rotulo", for: "exportar-de", texto: "De" }), de),
              el("div", {}, el("label", { classe: "rotulo", for: "exportar-ate", texto: "Até" }), ate)),
            filtrosAtivos.length ? el("p", { classe: "ajuda-campo", texto: "Com os filtros da tela: " + filtrosAtivos.join(", ") + "." }) : null,
            el("div", { classe: "grupo-lista", estilo: { boxShadow: "none" } },
              H.ui.linha({ icone: "cadeado", cor: "navy", titulo: "Incluir as partes e as observações dos sigilosos", sub: "Desligado, a planilha mostra “(segredo de justiça)” no lugar das partes e das observações.", acessorio: partesSig })),
            pastaPauta ? el("div", { classe: "ajuda-campo" },
              el("span", { texto: "A planilha fica fora do acervo da IA, em:" }),
              el("span", { classe: "caminho", estilo: { display: "block", marginTop: "2px" }, texto: pastaPauta })) : null,
          ],
          botoes: [{ rotulo: "Cancelar" }, { rotulo: "Exportar", tipo: "primario", padrao: true, acao: async () => {
            if (!de.value || !ate.value) return false;
            const r = await api.pauta.exportar({
              de: de.value <= ate.value ? de.value : ate.value, ate: de.value <= ate.value ? ate.value : de.value,
              sistema: f.sistema || undefined, situacao: f.situacao || undefined, busca: f.busca || undefined,
              incluir_partes_sigilosos: !!partesSig.checked,
            });
            const pasta = r.pasta || String(r.arquivo || "").replace(/[\\/][^\\/]*$/, "");
            aviso({
              titulo: "Planilha pronta", mensagem: String(r.arquivo || "").split(/[\\/]/).pop(), tipo: "sucesso",
              acoes: [{ rotulo: "Abrir", acao: () => api.abrir("arquivo", r.arquivo) }, { rotulo: "Abrir pasta", acao: () => api.abrir("pasta", pasta) }],
            });
            return true;
          } }],
        });
        return fo.resultado;
      }

      async function baixarPeriodo() {
        const audiencias = ((dados && dados.audiencias) || []).filter((a) => a.processo && a.situacao !== "Cancelada");
        const numeros = new Set(audiencias.map((a) => a.processo));
        if (!numeros.size) {
          aviso({ titulo: "Nada para baixar", mensagem: "Não há audiências com número de processo neste período.", tipo: "info" });
          return;
        }
        const ok = await folha.confirmar({
          titulo: "Baixar os autos do período?", icone: "doc-baixar", confirmar: numeros.size === 1 ? "Baixar 1 processo" : `Baixar ${numeros.size} processos`,
          mensagem: `${rotuloPeriodo(f)}: ${fmt.plural(numeros.size, "processo", "processos")} das audiências listadas (as canceladas ficam de fora). Os autos vão para uma pasta de lote em Processos, um PDF por processo.`,
        });
        if (!ok) return;
        const [de, ate] = intervalo(f);
        await api.pauta.baixarAutos({ ids: audiencias.map((a) => a.id), de: fmt.iso(de), ate: fmt.iso(ate) });
        aviso({ titulo: "Download começou", mensagem: "Acompanhe em Processos.", tipo: "info", acoes: [{ rotulo: "Ver o andamento", acao: () => H.app.ir("processos") }] });
      }

      // ---------------------------------------------- resultado (fica à vista até fechar)
      function mostrarResultado({ tipo, icone: nomeIcone, titulo, texto, lista, tituloLista, acoes, trazer }) {
        const itens = (lista || []).filter(Boolean);
        const corpo = el("div", {},
          texto ? el("span", { estilo: { display: "block" }, texto }) : null,
          itens.length ? el("details", { classe: "resultado-detalhes", open: itens.length <= 4 },
            el("summary", { texto: tituloLista || fmt.plural(itens.length, "observação", "observações") }),
            el("ul", { classe: "lista-avisos" }, itens.map((x) => el("li", { texto: x })))) : null);
        const fechar = botao({ icone: "x", titulo: "Fechar este aviso", tamanho: "pequeno", tipo: "texto", acao: () => trocar(faixaResultado) });
        trocar(faixaResultado, el("div", { estilo: { marginBottom: "14px" } },
          faixa({ tipo, icone: nomeIcone, titulo, texto: corpo, acoes: (acoes || []).concat([fechar]) })));
        if (trazer) trazerAVista(faixaResultado);
      }

      /**
       * A faixa fica no topo da página, e "Importar relatório" e "Capturar no
       * portal" (cartão "Mais ações") ficam no pé: sem rolar até ela, o
       * resultado aparecia mil pixels acima de onde a pessoa olhava — e, com a
       * Pauta aberta, o aviso do canto não se repete. Só para o que a pessoa
       * pediu nesta tela: o fim do monitoramento automático não a tira do
       * lugar onde ela está lendo.
       */
      function trazerAVista(no) {
        if (!no.isConnected || !no.firstChild) return;
        const caixa = no.getBoundingClientRect();
        const area = (document.getElementById("conteudo") || document.documentElement).getBoundingClientRect();
        const topo = Math.max(0, area.top);
        const fundo = Math.min(window.innerHeight, area.bottom || window.innerHeight);
        if (caixa.top >= topo && caixa.bottom <= fundo) return;
        let suave = true;
        try { suave = !window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_e) { /* sem matchMedia */ }
        no.scrollIntoView({ block: "start", behavior: suave ? "smooth" : "auto" });
      }

      const acoesDeSaida = () => [
        botao({ rotulo: "Capturar no portal", icone: "capturar", tamanho: "pequeno", tipo: "tonal", acao: () => capturar().catch((e) => folha.erro(e)) }),
        botao({ rotulo: "Importar relatório", icone: "importar", tamanho: "pequeno", tipo: "texto", acao: () => importar().catch((e) => folha.erro(e)) }),
        botao({ rotulo: "Acessos aos portais", icone: "chave", tamanho: "pequeno", tipo: "texto", acao: () => H.app.ir("ajustes/acessos") }),
      ];

      /** O que a sincronização ou a captura trouxe (ou por que não trouxe). */
      function resultadoDaTarefa(t, trazer) {
        const r = (t.resultado && typeof t.resultado === "object") ? t.resultado : {};
        ultimaMostrada = t.id;
        if (t.estado === "parada") {
          mostrarResultado({ tipo: "", icone: "info", titulo: t.tipo === "pauta_capturar" ? "Captura cancelada" : "Sincronização interrompida", texto: "Nada foi perdido: o que já estava na pauta continua aqui.", trazer });
          return;
        }
        if (t.estado === "falhou") {
          mostrarResultado({
            tipo: "erro", titulo: t.tipo === "pauta_capturar" ? "A captura não deu certo" : "Não consegui sincronizar a pauta",
            texto: t.erro || t.status || "O portal não respondeu como esperado.",
            acoes: acoesDeSaida(), trazer,
          });
          return;
        }
        if (t.tipo === "pauta_capturar") {
          const n = r.capturadas || 0;
          const telas = r.telas ? " em " + fmt.plural(r.telas, "tela", "telas") : "";
          const motivo = {
            fechada: "O navegador foi fechado antes de “Concluir”.",
            prazo: "O tempo da captura acabou antes de “Concluir”.",
          }[r.motivo] || "";
          // O status do programa ("Captura concluída: 12 audiências. O endereço
          // ficou lembrado…") repetia o título e a frase do endereço: fica só
          // o que o título não diz. Fonte que só entra com a pessoa à frente
          // (certificado) não vai para o monitoramento automático.
          const fonte = fontes.find((x) => x.id === r.fonte);
          const lembrou = !r.url ? ""
            : fonte && fonte.exige_presenca ? "O endereço ficou lembrado. O monitoramento não entra sozinho neste portal: sincronize aqui quando quiser."
              : "O endereço ficou lembrado: a fonte entra no monitoramento automático.";
          mostrarResultado({
            tipo: n ? "ok" : "aviso", icone: "capturar",
            titulo: n ? `Captura concluída: ${fmt.plural(n, "audiência", "audiências")}${telas}` : "Nenhuma audiência capturada",
            texto: [motivo, n ? lembrou : "Na barra do Helestron, no topo do portal, clique em “Capturar esta tela” com a pauta à vista e, no fim, em “Concluir”."].filter(Boolean).join(" "),
            trazer,
          });
          return;
        }
        const erros = (r.erros || []).map((e) => `${e.rotulo || e.fonte}: ${e.mensagem}`);
        const avisos = r.avisos || [];
        const lista = erros.concat(avisos);
        mostrarResultado({
          tipo: erros.length ? "aviso" : "ok", icone: "sincronizar",
          titulo: erros.length ? "Pauta sincronizada em parte" : "Pauta sincronizada",
          texto: t.status || "Pauta atualizada.",
          lista,
          tituloLista: erros.length ? fmt.plural(erros.length, "fonte com problema", "fontes com problema") + (avisos.length ? " e " + fmt.plural(avisos.length, "aviso", "avisos") : "") : fmt.plural(avisos.length, "aviso", "avisos"),
          acoes: erros.length ? acoesDeSaida() : [], trazer,
        });
      }

      // ---------------------------------------------- tarefa de sincronização/captura
      /** trazer: a pessoa começou a tarefa agora, com um clique nesta tela. */
      function acompanhar(id, trazer) {
        const t = H.loja.tarefas.get(id);
        if (t && t.estado !== "rodando") {
          // Terminou antes da resposta do pedido (os eventos chegam primeiro):
          // o resultado fica na faixa (sem apagá-lo), e à vista se foi a pessoa.
          if (tarefaSinc === id) tarefaSinc = null;
          if (ultimaMostrada !== id) terminou(t, !!trazer);
          else if (trazer) trazerAVista(faixaResultado);
          desenharTarefa();
          return;
        }
        tarefaSinc = id;
        trazerResultado = !!trazer;
        trocar(faixaResultado);
        desenharTarefa();
      }
      function desenharTarefa() {
        const t = tarefaSinc ? H.loja.tarefas.get(tarefaSinc) : null;
        const sincronizando = t && t.estado === "rodando" && t.tipo === "pauta_sincronizar";
        botaoSincronizar.disabled = !!sincronizando;
        botaoSincronizar.replaceChildren(sincronizando ? el("span", { classe: "girando", estilo: { borderColor: "rgba(255,255,255,.35)", borderTopColor: "#fff" } }) : icone("sincronizar"),
          el("span", { texto: sincronizando ? "Sincronizando…" : "Sincronizar" }));
        if (!t || t.estado !== "rodando") { trocar(faixaTarefa); return; }
        const anel = H.ui.anel({ tamanho: 28, espessura: 4 });
        const p = t.progresso || {};
        anel.definir(typeof p.percentual === "number" ? p.percentual : null);
        trocar(faixaTarefa, el("div", { classe: "faixa", estilo: { marginBottom: "14px", alignItems: "center" }, role: "status" },
          anel,
          el("div", { classe: "faixa-texto" }, el("strong", { classe: "faixa-titulo", texto: t.titulo || "Pauta" }), el("span", { texto: t.status || "" })),
          botao({ rotulo: t.tipo === "pauta_capturar" ? "Cancelar a captura" : "Parar", tamanho: "pequeno", acao: () => api.tarefas.parar(t.id) })));
      }
      ctx.on("tarefa", (t) => {
        if (t.tipo === "pauta_sincronizar" || t.tipo === "pauta_capturar") {
          // Adotada (o monitoramento automático, ou a de outra tela): o
          // resultado aparece na faixa, mas a rolagem fica onde está.
          if (t.estado === "rodando" && !tarefaSinc) { tarefaSinc = t.id; trazerResultado = false; }
          if (t.id === tarefaSinc) {
            desenharTarefa();
            if (t.estado !== "rodando") {
              const trazer = trazerResultado;
              tarefaSinc = null;
              trazerResultado = false;
              terminou(t, trazer);
            }
          }
        }
      });
      function terminou(t, trazer) {
        resultadoDaTarefa(t, trazer);
        Promise.all([carregarFontes(), carregarAlteracoes()]).then(() => { carregar(); desenharAlteracoes(); });
      }
      const emCurso = Array.from(H.loja.tarefas.values()).find((t) => (t.tipo === "pauta_sincronizar" || t.tipo === "pauta_capturar") && t.estado === "rodando");
      if (emCurso) acompanhar(emCurso.id);

      // ---------------------------------------------- desenho
      function desenharChips() {
        const resumoGeral = (H.loja.estado && H.loja.estado.resumo && H.loja.estado.resumo.pauta) || {};
        const r = (dados && dados.resumo) || {};
        const ps = r.por_situacao || {};
        const mudancas = (ps["Cancelada"] || 0) + (ps["Redesignada"] || 0);
        const chip = (n, rotulo, ativo, acao, id) => el("button", {
          type: "button", classe: "chip", id, aria: { pressed: String(!!ativo) }, on: { click: acao },
        }, el("strong", { texto: fmt.numero(n) }), el("span", { texto: rotulo, title: rotulo }));
        trocar(chips,
          chip(r.total || 0, "no período", false, () => { f.soMudancas = false; f.situacao = ""; situacao.value = ""; desenharLista(); desenharChips(); }, "chip-total"),
          chip(resumoGeral.hoje !== undefined ? resumoGeral.hoje : (r.hoje || 0), "hoje", f.periodo === "hoje" && fmt.mesmoDia(fmt.lerData(f.base), new Date()), () => { f.periodo = "hoje"; f.base = fmt.iso(new Date()); desenharFiltros(); carregar(); }, "chip-hoje"),
          chip(resumoGeral.semana !== undefined ? resumoGeral.semana : (r.semana || 0), "nos próximos 7 dias", f.periodo === "semana" && fmt.mesmoDia(fmt.lerData(f.base), new Date()), () => { f.periodo = "semana"; f.base = fmt.iso(new Date()); desenharFiltros(); carregar(); }, "chip-semana"),
          chip(mudancas, "canceladas ou redesignadas", f.soMudancas, () => { f.soMudancas = !f.soMudancas; desenharLista(); desenharChips(); }, "chip-mudancas"));
      }

      function desenharLista() {
        const todas = ((dados && dados.audiencias) || []).slice()
          .filter((a) => !f.soMudancas || a.situacao === "Cancelada" || a.situacao === "Redesignada")
          .sort((a, b) => (String(a.data) + String(a.hora || "99:99")).localeCompare(String(b.data) + String(b.hora || "99:99")));
        const nuncaSincronizou = !dados || (!dados.ultima_sincronizacao && !((H.loja.estado || {}).resumo || {}).pauta?.ultima_sincronizacao);
        const semFiltro = !f.sistema && !f.situacao && !f.busca && !f.soMudancas;
        if (!todas.length) {
          if (nuncaSincronizou && semFiltro && !fontes.length) {
            trocar(lista, estadoVazio());
            grade.classList.add("pauta-vazia");
          } else {
            grade.classList.remove("pauta-vazia");
            trocar(lista, cartao({}, vazio({
              icone: "calendario", titulo: semFiltro ? "Nenhuma audiência neste período" : "Nada encontrado com estes filtros",
              texto: semFiltro ? "Escolha outro período ou sincronize para conferir se há novidades no portal." : "Tire algum filtro ou mude o período.",
              acoes: semFiltro
                ? [botao({ rotulo: "Ver o mês", tipo: "tonal", acao: () => { f.periodo = "mes"; f.base = fmt.iso(new Date()); desenharFiltros(); carregar(); } })]
                : [botao({ rotulo: "Limpar os filtros", tipo: "tonal", acao: () => { f.sistema = ""; f.situacao = ""; f.busca = ""; f.soMudancas = false; sistema.value = ""; situacao.value = ""; busca.value = ""; carregar(); } })],
            })));
          }
          return;
        }
        grade.classList.remove("pauta-vazia");
        const dias = new Map();
        for (const a of todas) {
          if (!dias.has(a.data)) dias.set(a.data, []);
          dias.get(a.data).push(a);
        }
        const hoje = fmt.iso(new Date());
        const amanha = fmt.iso(fmt.somarDias(new Date(), 1));
        trocar(lista, Array.from(dias.entries()).map(([data, itens]) => {
          const etiqueta = data === hoje ? pilula("Hoje", "azul") : data === amanha ? pilula("Amanhã", "cinza") : null;
          return el("section", { classe: "pauta-dia" + (data < hoje ? " passado" : ""), dados: { data }, aria: { label: fmt.diaLongo(data) } },
            el("header", { classe: "pauta-dia-cabecalho" },
              el("h2", { classe: "pauta-dia-titulo", texto: fmt.diaLongo(data) }), etiqueta,
              el("span", { classe: "pauta-dia-conta", texto: fmt.plural(itens.length, "audiência", "audiências") })),
            el("div", { classe: "grupo-lista", role: "list" }, itens.map((a) => linhaAudiencia(a, acoesLinha))));
        }));
      }

      function estadoVazio() {
        return cartao({ classe: "pauta-vazia-cartao" }, vazio({
          icone: "calendario", titulo: "Sua pauta ainda está vazia",
          texto: el("div", {},
            el("p", { texto: "O Helestron lê a pauta de audiências do e-SAJ e do eProc com o seu acesso, acompanha as mudanças e exporta tudo para o Excel. Para começar:" }),
            el("ol", { classe: "lista-avisos", estilo: { textAlign: "left", margin: "12px auto 0", maxWidth: "430px", color: "var(--texto)" } },
              el("li", { texto: "Cadastre o acesso ao portal em Ajustes › Acessos aos portais." }),
              el("li", { texto: "Clique em Sincronizar. Se a pauta do seu tribunal fica numa tela própria, use Capturar no portal." }),
              el("li", { texto: "Ou importe o relatório de audiências exportado do SAJ ou do eProc." }))),
          acoes: [
            botao({ rotulo: "Sincronizar", icone: "sincronizar", tipo: "primario", acao: () => sincronizar() }),
            botao({ rotulo: "Capturar no portal", icone: "capturar", acao: () => capturar() }),
            botao({ rotulo: "Importar relatório", icone: "importar", acao: () => importar() }),
            botao({ rotulo: "Cadastrar acesso", icone: "chave", tipo: "texto", acao: () => H.app.ir("ajustes/acessos") }),
          ],
        }));
      }

      function desenharMonitor() {
        const m = (dados && dados.monitoramento) || { ativo: false, intervalo_horas: 6 };
        const ultima = (dados && dados.ultima_sincronizacao) || null;
        const intervaloSel = el("select", { classe: "campo campo-pequeno", id: "intervalo-monitor", aria: { label: "Intervalo do monitoramento" }, estilo: { width: "auto" } },
          INTERVALOS.map((h) => el("option", { value: String(h), texto: h === 1 ? "a cada hora" : `a cada ${h} horas` })));
        intervaloSel.value = String(m.intervalo_horas || 6);
        if (!INTERVALOS.includes(Number(m.intervalo_horas))) intervaloSel.appendChild(el("option", { value: String(m.intervalo_horas), texto: `a cada ${m.intervalo_horas} horas` }));
        intervaloSel.value = String(m.intervalo_horas || 6);
        intervaloSel.disabled = !m.ativo;
        const chave = interruptor({
          marcado: !!m.ativo, rotulo: "Monitorar a pauta", id: "monitorar-pauta",
          aoMudar: async (v) => {
            const r = await api.pauta.monitoramento(v, Number(intervaloSel.value));
            if (dados) dados.monitoramento = Object.assign({}, m, r || {}, { ativo: v });
            desenharMonitor();
          },
        });
        intervaloSel.addEventListener("change", async () => {
          try {
            const r = await api.pauta.monitoramento(true, Number(intervaloSel.value));
            if (dados) dados.monitoramento = Object.assign({}, m, r || {}, { intervalo_horas: Number(intervaloSel.value) });
            desenharMonitor();
          } catch (erro) { folha.erro(erro); }
        });
        trocar(monitor,
          cabecalhoCartao("Monitoramento", "sino"),
          el("div", { classe: "monitor-linha" },
            el("label", { classe: "linha-texto", for: "monitorar-pauta" },
              el("span", { classe: "linha-titulo", estilo: { fontSize: "14.5px" }, texto: "Conferir sozinho" }),
              el("span", { classe: "linha-sub", texto: "e avisar o que mudar" })),
            chave),
          el("div", { classe: "monitor-linha" }, el("span", { classe: "linha-texto", texto: "Frequência" }), intervaloSel),
          el("div", { classe: "monitor-linha", estilo: { flexDirection: "column", alignItems: "stretch", gap: "2px", marginTop: "14px", paddingTop: "12px", borderTop: "1px solid var(--separador)" } },
            el("span", { classe: "ajuda-campo", estilo: { margin: "0" } }, "Última sincronização: ", el("strong", { texto: ultima ? fmt.quando(ultima) : "nunca" })),
            m.ativo && m.proxima ? el("span", { classe: "ajuda-campo", estilo: { margin: "0" } }, "Próxima: ", el("strong", { texto: fmt.quando(m.proxima) })) : null,
            el("span", { classe: "ajuda-campo", estilo: { margin: "0" } },
              fontes.length ? fmt.plural(fontes.length, "fonte", "fontes") + ": " + fontes.map((x) => `${nomeSistema(x.sistema)} ${x.tribunal}${x.monitorada ? "" : x.exige_presenca ? " (só com você)" : " (sem endereço salvo)"}`).join(", ") + " · " : "Nenhuma fonte ainda · ",
              el("a", { href: "#/ajustes/pauta", texto: "gerenciar" })),
            m.ativo && fontes.length && !fontes.some((x) => x.monitorada) ? avisoSemMonitoradas(fontes) : null));
      }

      /** Monitoramento ligado sem nenhuma fonte que ele sincronize: diz por quê. */
      function avisoSemMonitoradas(fontes) {
        // As fontes agrupadas pelo motivo: "a entrada no portal é pelo
        // certificado digital (e-SAJ TJAL e eProc TJAL)".
        const porMotivo = new Map();
        for (const x of fontes.filter((f) => f.exige_presenca)) {
          const motivo = x.motivo_presenca || "o login exige você à frente";
          porMotivo.set(motivo, (porMotivo.get(motivo) || []).concat([`${nomeSistema(x.sistema)} ${x.tribunal}`]));
        }
        const lista = (nomes) => (nomes.length > 1 ? nomes.slice(0, -1).join(", ") + " e " + nomes[nomes.length - 1] : nomes[0]);
        const texto = porMotivo.size
          ? `O monitoramento não entra sozinho no portal: ${[...porMotivo].map(([motivo, nomes]) => `${motivo} (${lista(nomes)})`).join("; ")}. Sincronize aqui quando quiser, ou use a entrada por usuário e senha, com a senha guardada, em Ajustes › Acessos aos portais.`
          : "O monitoramento começa quando uma fonte tiver a pauta encontrada: sincronize ou capture no portal uma vez.";
        return el("span", { classe: "ajuda-campo", id: "monitor-sem-fontes", estilo: { margin: "4px 0 0" }, texto });
      }

      function desenharAlteracoes() {
        const naoVistas = Number(((H.loja.estado || {}).resumo || {}).pauta?.alteracoes_nao_vistas || 0);
        trocar(lembrete, naoVistas ? el("div", { estilo: { marginBottom: "12px" } }, H.ui.faixa({
          icone: "sino", titulo: naoVistas === 1 ? "1 alteração na pauta" : `${naoVistas} alterações na pauta`,
          texto: "Desde a última vez que você conferiu.",
          acoes: [botao({ rotulo: "Ver", tipo: "tonal", tamanho: "pequeno", acao: () => painelAlteracoes.scrollIntoView({ behavior: "smooth", block: "start" }) })],
        })) : null);
        const itens = alteracoes.slice(0, 5);
        const marcar = naoVistas ? botao({ rotulo: "Marcar como vistas", tipo: "texto", tamanho: "pequeno", acao: async () => {
          await api.pauta.marcarVistas();
          alteracoes.forEach((a) => { a.vista = true; });
          await H.app.recarregarEstado();
          desenharAlteracoes();
        } }) : null;
        const verTodas = alteracoes.length > 5 ? botao({ rotulo: `Ver todas (${alteracoes.length})`, tipo: "texto", tamanho: "pequeno", acao: () => folha.abrir({
          titulo: "Alterações da pauta", icone: "lapis", larga: true,
          conteudo: el("div", {}, alteracoes.map((a, i) => itemAlteracao(a, a.vista === false || (a.vista === undefined && i < naoVistas)))),
          botoes: [{ rotulo: "Fechar", tipo: "primario", padrao: true }],
        }).resultado }) : null;
        trocar(painelAlteracoes,
          cabecalhoCartao("Alterações recentes", "lapis", naoVistas ? el("span", { classe: "nav-selo", estilo: { marginLeft: "0" }, texto: String(naoVistas), aria: { label: `${naoVistas} não ${naoVistas === 1 ? "vista" : "vistas"}` } }) : null),
          itens.length
            ? el("div", {}, itens.map((a, i) => itemAlteracao(a, a.vista === false || (a.vista === undefined && i < naoVistas))),
              marcar || verTodas ? el("div", { classe: "grupo-botoes", estilo: { justifyContent: "space-between", marginTop: "6px", paddingTop: "8px", borderTop: "1px solid var(--separador)" } }, marcar, verTodas) : null)
            : el("p", { classe: "ajuda-campo", estilo: { margin: "0" }, texto: "Nenhuma alteração por enquanto. Quando a pauta mudar no portal, aparece aqui." }));
      }

      function desenharTrazer() {
        const acao = (id, nomeIcone, cor, titulo, sub, fn) => el("button", { type: "button", classe: "acao-item", id, on: { click: () => Promise.resolve(fn()).catch((e) => folha.erro(e)) } },
          blocoIcone(nomeIcone, cor), el("span", { classe: "linha-texto" }, el("span", { classe: "acao-item-titulo", texto: titulo }), el("span", { classe: "acao-item-sub", texto: sub })));
        trocar(trazer,
          cabecalhoCartao("Mais ações", "reticencias"),
          el("div", { classe: "acao-lista" },
            acao("acao-capturar", "capturar", "azul", "Capturar no portal", "Para a tela de pauta própria do tribunal.", capturar),
            acao("acao-importar", "importar", "ciano", "Importar relatório", "Planilha, PDF ou HTML exportado do SAJ ou do eProc.", importar),
            acao("acao-baixar-periodo", "doc-baixar", "navy", "Baixar os autos do período", "Um PDF por processo das audiências listadas.", baixarPeriodo)));
      }

      async function carregarAlteracoes() {
        try { alteracoes = await api.pauta.alteracoes(); } catch (_e) { alteracoes = []; }
      }

      async function carregarFontes() {
        try { fontes = await api.pauta.fontes(); } catch (_e) { fontes = []; }
      }

      let pedido = 0;
      async function carregar() {
        const meu = ++pedido;
        const [de, ate] = intervalo(f);
        try {
          const r = await api.pauta.listar({ de: fmt.iso(de), ate: fmt.iso(ate), sistema: f.sistema, situacao: f.situacao, busca: f.busca });
          if (meu !== pedido || !ctx.vivo) return;
          dados = r;
        } catch (erro) {
          if (meu !== pedido || !ctx.vivo) return;
          trocar(lista, cartao({}, vazio({ icone: "aviso", titulo: "Não consegui ler a pauta", texto: erro.message, acoes: [botao({ rotulo: "Tentar de novo", tipo: "tonal", acao: () => carregar() })] })));
          trocar(chips);
          desenharMonitor();
          return;
        }
        desenharChips();
        desenharLista();
        desenharMonitor();
      }

      ctx.on("pauta", async () => { await Promise.all([carregarAlteracoes(), carregarFontes()]); await carregar(); desenharAlteracoes(); });
      ctx.on("resumo", () => { desenharAlteracoes(); desenharChips(); });

      desenharTrazer();
      desenharAlteracoes();
      await Promise.all([carregarAlteracoes(), carregarFontes()]);
      await carregar();
      desenharAlteracoes();
      desenharTarefa();
    },
  };
})();
