/* Helestron — a casca da interface: barra lateral, rotas, eventos globais,
 * tarefas em andamento, perguntas do motor e o modo autoteste.
 *
 * Rotas: #/secao[/subsecao][?chave=valor]. Cada seção é um objeto em
 * Helestron.secoes com montar(ctx) — que devolve uma promessa resolvida
 * quando a tela está pronta (dados carregados e desenhados) — e, opcional,
 * sair() e rota(ctx) (mudança de subsecão sem remontar).
 *
 * O 'ctx' dá à seção tudo de que ela precisa sem vazar nada quando o usuário
 * troca de tela: inscrições em eventos, intervalos e temporizadores feitos
 * por ele são desfeitos sozinhos ao sair.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, aviso, folha } = H.ui;
  const api = H.api;

  const SECOES = [
    { id: "inicio", rotulo: "Início", icone: "casa" },
    { id: "processos", rotulo: "Processos", icone: "doc-baixar" },
    { id: "audiencias", rotulo: "Audiências", icone: "microfone" },
    { id: "pauta", rotulo: "Pauta", icone: "calendario" },
    { id: "compartilhar", rotulo: "Compartilhar", icone: "compartilhar" },
    { id: "ajustes", rotulo: "Ajustes", icone: "engrenagem" },
    { id: "ajuda", rotulo: "Ajuda", icone: "ajuda" },
  ];

  // Que seção acompanha cada tipo de tarefa (clique na tarefa da barra lateral).
  const SECAO_DA_TAREFA = {
    download: "processos", teste_login: "ajustes/acessos", transcricao_arquivo: "audiencias",
    modelo: "audiencias", preparo: "compartilhar", pacote: "compartilhar", nuvem: "compartilhar",
    pauta_sincronizar: "pauta", pauta_capturar: "pauta", verificacao: "ajustes/sobre",
  };

  const params = new URLSearchParams(location.search);
  const AUTOTESTE = params.get("autoteste") === "1";

  // ============================================================== loja
  // O que mais de uma seção precisa saber, vivo enquanto a janela estiver aberta.
  const loja = {
    estado: null,            // último /api/estado
    config: null,            // último /api/config
    tarefas: new Map(),      // id → Tarefa
    itens: new Map(),        // id da tarefa → Map(numero → item)
    registros: [],           // últimos eventos 'log'
    gravando: false,         // há audiência sendo transcrita?
    processos: null,         // rascunho da seção Processos (relação lida, opções)
    // Tarefas cujo resultado a tela aberta mostra no próprio lugar (o teste de
    // um acesso, na linha do portal): o aviso do canto não o repete.
    resultadosNaTela: new Set(),
  };
  H.loja = loja;

  // ============================================================== barra lateral
  const nav = document.getElementById("navegacao");
  const linksNav = new Map();

  function montarNavegacao() {
    SECOES.forEach((s, i) => {
      const a = el("a", {
        classe: "nav-item", href: "#/" + s.id, dados: { secao: s.id },
        title: `${s.rotulo} (Ctrl+${i + 1})`,
        aria: { keyshortcuts: `Control+${i + 1}` },
      }, icone(s.icone), el("span", { texto: s.rotulo }));
      linksNav.set(s.id, a);
      nav.appendChild(a);
    });
  }

  function marcarNavegacao(id) {
    for (const [secao, a] of linksNav) {
      if (secao === id) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
  }

  /** Selo de alterações da pauta e bolinha de gravação na barra lateral. */
  function atualizarSelos() {
    const pauta = linksNav.get("pauta");
    const n = loja.estado && loja.estado.resumo && loja.estado.resumo.pauta
      ? Number(loja.estado.resumo.pauta.alteracoes_nao_vistas || 0) : 0;
    let selo = pauta.querySelector(".nav-selo");
    if (n > 0) {
      if (!selo) {
        selo = el("span", { classe: "nav-selo" });
        pauta.appendChild(selo);
      }
      selo.textContent = n > 99 ? "99+" : String(n);
      selo.setAttribute("aria-label", n === 1 ? "1 alteração não vista" : `${n} alterações não vistas`);
    } else if (selo) {
      selo.remove();
    }
    const aud = linksNav.get("audiencias");
    let ponto = aud.querySelector(".nav-gravando");
    if (loja.gravando && !ponto) {
      aud.appendChild(el("span", { classe: "nav-gravando", title: "Audiência em gravação", aria: { label: "Audiência em gravação" } }));
    } else if (!loja.gravando && ponto) {
      ponto.remove();
    }
  }

  // ------------------------------------------------- tarefas no rodapé
  const caixaTarefas = document.getElementById("tarefas-lateral");
  const aneisTarefas = new Map();

  function atualizarTarefasLateral() {
    const rodando = Array.from(loja.tarefas.values()).filter((t) => t.estado === "rodando");
    const ids = new Set(rodando.map((t) => t.id));
    for (const [id, no] of aneisTarefas) {
      if (!ids.has(id)) {
        no.remove();
        aneisTarefas.delete(id);
      }
    }
    for (const t of rodando) {
      let no = aneisTarefas.get(t.id);
      if (!no) {
        const anel = H.ui.anel({ tamanho: 30, espessura: 4 });
        no = el("button", { type: "button", classe: "tarefa-mini" }, anel,
          el("span", { classe: "tarefa-mini-texto" },
            el("span", { classe: "tarefa-mini-titulo" }), el("span", { classe: "tarefa-mini-status" })));
        no.anel = anel;
        no.addEventListener("click", () => ir(SECAO_DA_TAREFA[t.tipo] || "inicio"));
        aneisTarefas.set(t.id, no);
        caixaTarefas.appendChild(no);
      }
      const p = t.progresso || {};
      const pct = typeof p.percentual === "number" ? p.percentual
        : p.total ? (100 * (p.feitos || 0)) / p.total : null;
      no.anel.definir(pct);
      no.querySelector(".tarefa-mini-titulo").textContent = t.titulo || "Tarefa";
      const status = p.total ? `${p.feitos || 0} de ${p.total}` + (t.status ? " · " + t.status : "")
        : t.status || "Em andamento…";
      no.querySelector(".tarefa-mini-status").textContent = status;
      no.title = `${t.titulo || "Tarefa"} — ${status}`;
    }
  }

  // ============================================================== estado geral
  let recarregando = null;

  async function recarregarEstado() {
    if (recarregando) return recarregando;
    recarregando = (async () => {
      try {
        const estado = await api.estado();
        loja.estado = estado;
        if (estado.audiencia && typeof estado.audiencia.ativa === "boolean") loja.gravando = estado.audiencia.ativa;
        for (const t of estado.tarefas || []) loja.tarefas.set(t.id, Object.assign(loja.tarefas.get(t.id) || {}, t));
        document.getElementById("versao").textContent = `${estado.nome || "Helestron"} ${estado.versao || ""}`.trim();
        atualizarSelos();
        atualizarTarefasLateral();
        api.emitir("resumo", estado);
        return estado;
      } finally {
        setTimeout(() => { recarregando = null; }, 50);
      }
    })();
    return recarregando;
  }
  const recarregarDepois = H.ui.debounce(() => recarregarEstado().catch(() => {}), 400);

  async function carregarConfig(forcar) {
    if (loja.config && !forcar) return loja.config;
    loja.config = await api.config.ler();
    return loja.config;
  }

  /** Valor de uma chave do config (ou o padrão). */
  function valorConfig(secao, chave, padrao) {
    const v = loja.config && loja.config.valores && loja.config.valores[secao];
    if (!v || v[chave] === undefined || v[chave] === null) return padrao;
    return v[chave];
  }

  function flag(valor) {
    return valor === true || ["true", "1", "sim", "yes", "on"].includes(String(valor).toLowerCase());
  }

  // ============================================================== eventos
  const ESTADOS_FINAIS = new Set(["concluida", "falhou", "parada"]);

  function ligarEventosGlobais() {
    api.on("tarefa", (t) => {
      if (!t || !t.id) return;
      const antes = loja.tarefas.get(t.id);
      loja.tarefas.set(t.id, Object.assign({}, antes || {}, t));
      atualizarTarefasLateral();
      if (ESTADOS_FINAIS.has(t.estado) && (!antes || antes.estado === "rodando")) {
        avisarFimDeTarefa(t);
        recarregarDepois();
      }
    });

    api.on("item", (item) => {
      if (!item || !item.tarefa) return;
      if (!loja.itens.has(item.tarefa)) loja.itens.set(item.tarefa, new Map());
      const mapa = loja.itens.get(item.tarefa);
      mapa.set(item.numero, Object.assign({}, mapa.get(item.numero) || {}, item));
    });

    api.on("log", (registro) => {
      loja.registros.push(registro);
      if (loja.registros.length > 300) loja.registros.splice(0, loja.registros.length - 300);
    });

    api.on("aviso", (a) => {
      if (!a) return;
      // Na tela da Pauta, o que a sincronização ou a captura tem a dizer já
      // está na faixa de andamento e na de resultado (fontes com problema,
      // avisos): o mesmo texto não se repete num aviso por cima dos botões.
      const daTarefa = a.tarefa ? loja.tarefas.get(a.tarefa) : null;
      if (daTarefa && resultadoNaTela(daTarefa)) return;
      const tipo = { erro: "erro", aviso: "alerta", alerta: "alerta", sucesso: "sucesso" }[a.nivel] || "info";
      aviso({ titulo: a.titulo, mensagem: a.mensagem, tipo });
    });

    api.on("pergunta", (p) => perguntas.chegou(p));
    api.on("pergunta_fechada", (p) => perguntas.fechada(p));
    api.on("estado", () => recarregarDepois());
    api.on("pauta", () => recarregarDepois());

    api.on("transcricao", (ev) => {
      if (!ev) return;
      if (ev.tipo === "estado") {
        const d = ev.dados || {};
        const t = H.normalizar(typeof d === "string" ? d : (d.estado || d.texto || ""));
        if (/^(gravando|pausad|carregando|iniciando|encerrando)/.test(t)) loja.gravando = true;
        if (/^(encerrada|parada|erro)/.test(t) || t === "concluido") loja.gravando = false;
      } else if (ev.tipo === "fim") {
        loja.gravando = false;
      }
      atualizarSelos();
    });

    api.on("conexao", ({ conectado }) => {
      const faixa = document.getElementById("faixa-conexao");
      const marca = document.getElementById("conexao");
      marca.classList.toggle("desligada", !conectado);
      marca.textContent = conectado ? "ligado" : "sem conexão";
      marca.title = conectado ? "Ligado ao Helestron" : "Sem conexão com o Helestron";
      clearTimeout(faixa._t);
      if (conectado) {
        faixa.hidden = true;
        // Pode ter perdido eventos enquanto esteve fora: relê o resumo.
        recarregarDepois();
      } else {
        faixa._t = setTimeout(() => { faixa.hidden = false; }, 2500);
      }
    });
  }

  /**
   * A tela aberta mostra o resultado desta tarefa por conta própria? A Pauta
   * mostra o da sincronização e o da captura numa faixa que fica à vista até
   * ser fechada; o aviso do canto só repetiria a mesma frase.
   */
  function resultadoNaTela(t) {
    const tipo = t && t.tipo;
    if (t && loja.resultadosNaTela.has(t.id)) return true;
    return (tipo === "pauta_sincronizar" || tipo === "pauta_capturar") && document.documentElement.dataset.secao === "pauta";
  }

  function avisarFimDeTarefa(t) {
    if (resultadoNaTela(t)) return;
    const r = t.resultado || {};
    const acoes = [];
    if (r && typeof r === "object") {
      if (r.pasta) acoes.push({ rotulo: "Abrir pasta", acao: () => api.abrir("pasta", r.pasta) });
      if (r.arquivo) acoes.push({ rotulo: "Abrir", acao: () => api.abrir("arquivo", r.arquivo) });
      if (r.documento) acoes.push({ rotulo: "Abrir documento", acao: () => api.abrir("arquivo", r.documento) });
    }
    // Concluída, mas com itens que não deram certo (lote com falhas, fonte da
    // pauta que não respondeu): aviso âmbar, não o verde de "tudo certo".
    const comProblema = r && typeof r === "object" && ((Number(r.falhas) || 0) > 0 || (Array.isArray(r.erros) && r.erros.length > 0));
    if (t.estado === "concluida") {
      aviso({ titulo: t.titulo || "Concluído", mensagem: t.status || "Pronto.", tipo: comProblema ? "alerta" : "sucesso", acoes });
    } else if (t.estado === "falhou") {
      aviso({ titulo: (t.titulo || "Tarefa") + " — não deu certo", mensagem: t.erro || t.status || "", tipo: "erro" });
    } else if (t.estado === "parada") {
      aviso({ titulo: (t.titulo || "Tarefa") + " — interrompida", mensagem: t.status || "Você pediu para parar.", tipo: "info", acoes });
    }
  }

  // ============================================================== perguntas
  /**
   * Perguntas do motor (6.5): código por e-mail, código do autenticador,
   * confirmações e escolhas. Uma folha de cada vez, em ordem de chegada;
   * a resposta vai para /api/perguntas/{id}/responder.
   */
  const perguntas = {
    fila: [],
    atual: null,

    chegou(p) {
      if (!p || !p.id) return;
      if ((this.atual && this.atual.p.id === p.id) || this.fila.some((x) => x.id === p.id)) return;
      this.fila.push(p);
      this.proxima();
    },

    fechada({ id, motivo }) {
      this.fila = this.fila.filter((x) => x.id !== id);
      if (this.atual && this.atual.p.id === id) {
        const f = this.atual.folha;
        this.atual.respondida = true;
        f.fechar();
        // Fechada pelo programa (prazo, tarefa parada) com a folha à vista: explica.
        // Resposta e cancelamento do próprio usuário não precisam de aviso.
        const frase = { prazo: "O prazo para responder acabou.", tarefa_parada: "A tarefa foi interrompida." }[motivo];
        if (frase) aviso({ titulo: "Pergunta encerrada", mensagem: frase, tipo: "info" });
      }
    },

    proxima() {
      if (this.atual || !this.fila.length) return;
      const p = this.fila.shift();
      const estado = { p, respondida: false, folha: null };
      this.atual = estado;
      estado.folha = abrirPergunta(p, estado);
      estado.folha.resultado.then(() => {
        clearInterval(estado.relogio);
        if (this.atual === estado) this.atual = null;
        setTimeout(() => this.proxima(), 220);
      });
    },
  };
  H.perguntas = perguntas;

  function abrirPergunta(p, estado) {
    const tipo = p.tipo || "texto";
    const opcoes = p.opcoes || {};
    // Dá para pedir outro código? O portal diz (reenviavel); quando não diz
    // (null), deduz-se pelo pedido: código por e-mail sim, autenticador não.
    let reenviavel = p.reenviavel;
    if (reenviavel === null || reenviavel === undefined) reenviavel = opcoes && !Array.isArray(opcoes) ? opcoes.reenviavel : undefined;
    if (reenviavel === null || reenviavel === undefined) {
      const t = H.normalizar((p.titulo || "") + " " + (p.mensagem || ""));
      reenviavel = /e-?mail/.test(t) && !/autenticador/.test(t);
    }
    reenviavel = !!reenviavel;
    const responder = async (valor) => {
      await api.perguntas.responder(p.id, valor);
      estado.respondida = true;
    };
    const cancelar = () => {
      if (!estado.respondida) api.perguntas.cancelar(p.id).catch(() => {});
    };

    const prazo = el("p", { classe: "prazo", "aria-live": "off" });
    const conteudo = [];
    let botoes = [];
    let nomeIcone = "info";
    let cor = null;

    if (tipo === "codigo") {
      nomeIcone = /autentic/i.test((p.titulo || "") + (p.mensagem || "")) ? "celular" : "envelope";
      cor = "navy";
      const campo = el("input", {
        classe: "campo campo-codigo", inputmode: "numeric", autocomplete: "one-time-code",
        maxlength: "12", placeholder: "000000", spellcheck: "false", aria: { label: "Código de verificação" },
        id: "campo-codigo",
      });
      const erro = el("p", { classe: "ajuda-campo erro", hidden: true, "aria-live": "polite" });
      conteudo.push(campo, erro);
      const enviar = async () => {
        const v = campo.value.replace(/\s/g, "");
        if (v.length < 4) {
          erro.textContent = "Digite o código completo.";
          erro.hidden = false;
          campo.classList.add("invalido");
          campo.focus();
          return false;
        }
        await responder(v);
        return true;
      };
      campo.addEventListener("input", () => {
        // Só números e letras; o código de seis dígitos vai sozinho.
        campo.value = campo.value.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
        campo.classList.remove("invalido");
        erro.hidden = true;
        if (/^\d{6}$/.test(campo.value)) {
          const b = estado.folha && estado.folha.rodape.querySelector("[data-padrao]");
          if (b) setTimeout(() => b.click(), 120);
        }
      });
      campo.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          const b = estado.folha.rodape.querySelector("[data-padrao]");
          if (b) b.click();
        }
      });
      botoes = [
        reenviavel ? { rotulo: "Pedir novo código", tipo: "texto", acao: async () => { await responder(""); return true; } } : null,
        reenviavel ? "espaco" : null,
        { rotulo: "Cancelar", acao: () => { cancelar(); return true; } },
        { rotulo: "Enviar", tipo: "primario", padrao: true, acao: enviar, id: "enviar-codigo" },
      ].filter(Boolean);
    } else if (tipo === "confirmar") {
      nomeIcone = "aviso";
      cor = "alerta";
      botoes = [
        { rotulo: (opcoes && opcoes.nao) || "Não", acao: async () => { await responder(false); return true; } },
        { rotulo: (opcoes && opcoes.sim) || "Sim", tipo: "primario", padrao: true, acao: async () => { await responder(true); return true; } },
      ];
    } else if (tipo === "escolha") {
      const lista = Array.isArray(opcoes) ? opcoes : (opcoes.opcoes || opcoes.lista || []);
      let escolhida = null;
      const grupo = el("div", { classe: "opcoes-escolha", role: "radiogroup", aria: { label: p.titulo } });
      lista.forEach((op) => {
        const valor = typeof op === "object" ? op.valor : op;
        const rotulo = typeof op === "object" ? (op.rotulo || op.valor) : op;
        const b = el("button", { type: "button", classe: "opcao-escolha", role: "radio", aria: { checked: "false" } },
          icone("circulo"), el("span", { texto: rotulo }));
        b.addEventListener("click", () => {
          escolhida = valor;
          grupo.querySelectorAll(".opcao-escolha").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
        });
        b.addEventListener("dblclick", () => estado.folha.rodape.querySelector("[data-padrao]").click());
        grupo.appendChild(b);
      });
      conteudo.push(grupo);
      botoes = [
        { rotulo: "Cancelar", acao: () => { cancelar(); return true; } },
        { rotulo: "Escolher", tipo: "primario", padrao: true, acao: async () => { if (escolhida === null) return false; await responder(escolhida); return true; } },
      ];
    } else {
      const campo = el("input", { classe: "campo", type: "text", autocomplete: "off", aria: { label: p.titulo } });
      conteudo.push(campo);
      campo.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") { ev.preventDefault(); estado.folha.rodape.querySelector("[data-padrao]").click(); }
      });
      botoes = [
        { rotulo: "Cancelar", acao: () => { cancelar(); return true; } },
        { rotulo: "Enviar", tipo: "primario", padrao: true, acao: async () => { await responder(campo.value); return true; } },
      ];
    }
    if (p.prazo_s) conteudo.push(prazo);

    const f = folha.abrir({
      titulo: p.titulo || "O Helestron precisa de uma resposta",
      mensagem: p.mensagem, icone: nomeIcone, corIcone: cor, conteudo, botoes,
      fecharFora: false, aoCancelar: cancelar,
    });
    f.elemento.classList.add("folha-pergunta");
    f.elemento.dataset.pergunta = p.id;

    if (p.prazo_s) {
      const limite = Date.now() + p.prazo_s * 1000;
      const tic = () => {
        const s = Math.max(0, Math.round((limite - Date.now()) / 1000));
        H.ui.trocar(prazo, icone("relogio"), `Responda em até ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
        if (s <= 0) clearInterval(estado.relogio);
      };
      tic();
      estado.relogio = setInterval(tic, 1000);
    }
    return f;
  }

  // ============================================================== rotas
  const pagina = document.getElementById("pagina");
  let atual = null;           // {id, secao, ctx}

  /** "#/ajustes/acessos?x=1" → {secao, sub, params}. Aceita "ajustes#acessos" (pendências). */
  function lerRota(hash) {
    let h = String(hash || "").replace(/^#\/?/, "");
    if (!h.includes("/") && h.includes("#")) h = h.replace("#", "/");
    const [caminho, consulta] = h.split("?");
    const [secao, sub] = (caminho || "").split("/");
    const valida = SECOES.some((s) => s.id === secao);
    return {
      secao: valida ? secao : "inicio",
      sub: valida ? (sub || "") : "",
      params: new URLSearchParams(consulta || ""),
    };
  }

  function ir(destino) {
    const d = String(destino || "inicio").replace(/^#\/?/, "").replace("#", "/");
    const novo = "#/" + d;
    if (location.hash === novo) aoMudarRota();
    else location.hash = novo;
  }

  function novoContexto(rota) {
    const desfazer = [];
    const ctx = {
      rota,
      raiz: null,
      vivo: true,
      on(tipo, fn) {
        const off = api.on(tipo, (d) => { if (ctx.vivo) fn(d); });
        desfazer.push(off);
        return off;
      },
      cada(ms, fn) {
        const id = setInterval(() => { if (ctx.vivo) fn(); }, ms);
        desfazer.push(() => clearInterval(id));
        return id;
      },
      depois(ms, fn) {
        const id = setTimeout(() => { if (ctx.vivo) fn(); }, ms);
        desfazer.push(() => clearTimeout(id));
        return id;
      },
      aoSair(fn) {
        desfazer.push(fn);
      },
      ir,
      limpar() {
        ctx.vivo = false;
        for (const fn of desfazer.splice(0)) {
          try { fn(); } catch (_e) { /* nada */ }
        }
      },
    };
    return ctx;
  }

  async function aoMudarRota() {
    const rota = lerRota(location.hash);
    const def = H.secoes && H.secoes[rota.secao];
    marcarNavegacao(rota.secao);

    // Mesma seção, outra subsecão: a seção decide se remonta.
    if (atual && atual.id === rota.secao && def && def.rota) {
      atual.ctx.rota = rota;
      try {
        await def.rota(atual.ctx);
      } catch (erro) {
        folha.erro(erro);
      }
      return;
    }

    if (atual) {
      try { atual.secao.sair && atual.secao.sair(atual.ctx); } catch (_e) { /* nada */ }
      atual.ctx.limpar();
    }
    document.documentElement.dataset.pronta = "0";
    document.documentElement.dataset.secao = rota.secao;
    const ctx = novoContexto(rota);
    const raiz = el("div", { classe: "pagina", dados: { secao: rota.secao } });
    ctx.raiz = raiz;
    H.ui.trocar(pagina, raiz);
    document.getElementById("conteudo").scrollTop = 0;
    const info = SECOES.find((s) => s.id === rota.secao);
    document.title = info && rota.secao !== "inicio" ? `${info.rotulo} — Helestron` : "Helestron";
    atual = { id: rota.secao, secao: def, ctx };
    if (!def) {
      mostrarErroDeSecao(raiz, new Error("Esta parte do programa não foi encontrada."), rota);
      return;
    }
    try {
      await def.montar(ctx);
    } catch (erro) {
      if (!ctx.vivo) return;
      console.error(erro);
      mostrarErroDeSecao(raiz, erro, rota);
    }
    if (!ctx.vivo) return;
    // Foco no título (leitor de tela anuncia a nova tela), sem rolar.
    const h1 = raiz.querySelector(".titulo-grande");
    if (h1 && !document.querySelector(".folha-fundo")) h1.focus({ preventScroll: true });
    document.documentElement.dataset.pronta = "1";
    api.emitir("secao_pronta", rota.secao);
  }

  /** Uma seção que não abriu não derruba as outras: explica e oferece saída. */
  function mostrarErroDeSecao(raiz, erro, rota) {
    H.ui.trocar(raiz,
      H.ui.cabecalho({ titulo: (SECOES.find((s) => s.id === rota.secao) || {}).rotulo || "Helestron" }),
      H.ui.cartao({ classe: "erro-secao" }, H.ui.vazio({
        icone: "aviso",
        titulo: "Esta tela não abriu",
        texto: (erro && erro.message ? erro.message + " " : "") +
          "Tente de novo. Se continuar, abra Ajustes › Sobre e diagnóstico e clique em “Verificar a instalação”.",
        acoes: [
          H.ui.botao({ rotulo: "Tentar de novo", tipo: "primario", icone: "recuperar", acao: () => { atual = null; aoMudarRota(); } }),
          H.ui.botao({ rotulo: "Verificar a instalação", acao: () => ir("ajustes/sobre") }),
        ],
      })));
  }

  // ============================================================== teclado
  function ligarTeclado() {
    document.addEventListener("keydown", (ev) => {
      if (document.querySelector(".folha-fundo")) return;     // folha aberta: ela manda
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey && /^[1-7]$/.test(ev.key)) {
        ev.preventDefault();
        ir(SECOES[Number(ev.key) - 1].id);
      }
    });
  }

  // ============================================================== autoteste
  /**
   * Modo autoteste (?autoteste=1, usado por "Helestron.exe --autoteste"):
   * percorre as seções em ordem; em cada uma, espera ficar pronta e as
   * fontes carregarem, e pede ao servidor a captura (POST /api/autoteste/passo).
   * No fim, POST /api/autoteste/fim com o que aconteceu.
   */
  async function rodarAutoteste() {
    document.documentElement.classList.add("sem-movimento");
    const resultado = { secoes: [], erros: [] };
    window.addEventListener("error", (ev) => resultado.erros.push(String(ev.message || ev)));
    window.addEventListener("unhandledrejection", (ev) => resultado.erros.push(String(ev.reason && ev.reason.message || ev.reason)));
    for (const s of SECOES) {
      const pronta = esperarSecao(s.id);
      ir(s.id);
      const ok = await pronta;
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      await H.ui.esperar(450);
      const erroNaTela = document.querySelector(".erro-secao");
      resultado.secoes.push({ secao: s.id, pronta: ok, erro_na_tela: !!erroNaTela });
      const problema = !ok ? "a tela não ficou pronta a tempo"
        : erroNaTela ? (erroNaTela.textContent || "a tela mostrou erro").replace(/\s+/g, " ").trim() : "";
      try {
        await api.autoteste.passo(s.id, problema ? { erro: problema } : {});
      } catch (erro) {
        resultado.erros.push(`${s.id}: ${erro.message}`);
      }
    }
    try {
      await api.autoteste.fim(resultado);
    } catch (_e) { /* o servidor já pode estar fechando */ }
    document.documentElement.dataset.autoteste = "fim";
  }

  function esperarSecao(id, limite = 15000) {
    return new Promise((resolver) => {
      let feito = false;
      const off = api.on("secao_pronta", (s) => {
        if (s === id && !feito) { feito = true; off(); resolver(true); }
      });
      setTimeout(() => { if (!feito) { feito = true; off(); resolver(false); } }, limite);
    });
  }

  // ============================================================== início
  async function iniciar() {
    H.icones.instalar();
    montarNavegacao();
    ligarEventosGlobais();
    ligarTeclado();
    if (AUTOTESTE) document.documentElement.classList.add("sem-movimento");

    // A logo da barra lateral vem do instalador (img/marca). Se faltar (instalação
    // incompleta), fica a letra H desenhada aqui, sem buraco na barra.
    const logo = document.querySelector(".marca-logo");
    const semLogo = () => {
      if (!logo.isConnected) return;
      logo.replaceWith(el("span", { classe: "marca-logo bloco-icone cor-navy", "aria-hidden": "true", estilo: { width: "38px", height: "38px", borderRadius: "11px", fontWeight: "800", fontSize: "20px" }, texto: "H" }));
    };
    // A imagem pode ter falhado antes deste script rodar (ela vem antes no HTML).
    if (logo.complete && logo.naturalWidth === 0) semLogo();
    else logo.addEventListener("error", semLogo, { once: true });

    api.conectarEventos();
    try {
      await Promise.all([recarregarEstado(), carregarConfig().catch(() => null)]);
    } catch (erro) {
      console.error(erro);
    }
    if (!(loja.estado && loja.estado.audiencia)) {
      api.transcricao.estado().then((e) => {
        const t = H.normalizar(e && e.estado);
        loja.gravando = !!(e && e.sessao) && !/^(conclu|encerrad|parad|erro)/.test(t);
        atualizarSelos();
      }).catch(() => {});
    }

    window.addEventListener("hashchange", aoMudarRota);
    if (!location.hash || location.hash === "#" || location.hash === "#/") {
      history.replaceState(null, "", location.pathname + location.search + "#/inicio");
    }
    if (AUTOTESTE) {
      rodarAutoteste();
    } else {
      aoMudarRota();
    }
  }

  H.app = {
    ir, recarregarEstado, carregarConfig, valorConfig, flag, SECOES, lerRota,
    secaoAtual: () => (atual ? atual.id : null),
  };
  H.secoes = H.secoes || {};

  iniciar();
})();
