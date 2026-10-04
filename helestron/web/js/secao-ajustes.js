/* Helestron — Ajustes (especificação 7.2).
 *
 * Listas agrupadas no estilo dos Ajustes do iOS, com um índice à esquerda:
 * Acessos aos portais, Pastas, Unidade, Download, Transcrição, Pauta,
 * Compartilhar e Sobre e diagnóstico. Os campos vêm do esquema que o servidor
 * manda (/api/config): a tela não precisa mudar quando uma chave nova
 * aparecer. Tudo é salvo na hora (sem botão Salvar), como no iOS; o que o
 * programa recusar (pastas conflitantes, número inválido) volta ao valor
 * anterior e a explicação aparece numa folha.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, botao, cartao, vazio, interruptor, trocar, folha, aviso, blocoIcone, pilula, linha, grupo, nomeSistema } = H.ui;
  const { fmt, api } = H;

  // 'curto' é o nome no índice (cabe na coluna estreita); 'titulo', o da página.
  const GRUPOS = [
    { id: "acessos", curto: "Acessos", titulo: "Acessos aos portais", icone: "chave", cor: "azul", sub: "Usuário e senha do e-SAJ e do eProc, e como o Helestron entra em cada um." },
    { id: "pastas", curto: "Pastas", titulo: "Pastas", icone: "pasta", cor: "celeste", sub: "Onde ficam o acervo, os processos sigilosos e a pauta exportada." },
    { id: "unidade", curto: "Unidade", titulo: "Unidade", icone: "predio", cor: "navy", sub: "Os dados que aparecem no cabeçalho das transcrições." },
    { id: "download", curto: "Download", titulo: "Download", icone: "doc-baixar", cor: "verde", sub: "Como os processos são baixados dos portais." },
    { id: "transcricao", curto: "Transcrição", titulo: "Transcrição", icone: "microfone", cor: "vermelho", sub: "Modelos, participantes e o que vai no documento." },
    { id: "pauta", curto: "Pauta", titulo: "Pauta", icone: "calendario", cor: "ciano", sub: "Fontes da pauta, monitoramento e exportação." },
    { id: "compartilhar", curto: "Compartilhar", titulo: "Compartilhar", icone: "brilho", cor: "indigo", sub: "Preparo do acervo e espelho na nuvem." },
    { id: "sobre", curto: "Diagnóstico", titulo: "Sobre e diagnóstico", icone: "info", cor: "cinza", sub: "Versão, verificação da instalação e registros." },
  ];

  /** Em que grupo da tela cada chave do config.ini aparece (null = escondida). */
  function grupoDoCampo(c) {
    const k = c.secao + "." + c.chave;
    if (c.secao === "interface") return null;
    if (c.secao === "esaj" || k === "eproc.login" || k === "eproc.perfil" || k === "download.espera_login_minutos") return "acessos";
    if (c.tipo === "pasta" && c.secao !== "compartilhar") return "pastas";
    if (c.secao === "geral" || c.secao === "unidade") return "unidade";
    if (c.secao === "download" || c.secao === "eproc") return "download";
    if (c.secao === "transcricao") return "transcricao";
    if (c.secao === "pauta") return "pauta";
    if (c.secao === "compartilhar") return "compartilhar";
    return "sobre";
  }

  const RODAPES = {
    acessos: "As senhas ficam cifradas pelo Windows (DPAPI): só a sua conta, neste computador, consegue lê-las. Com “Entrar manualmente”, o navegador abre na tela de entrada do portal e o Helestron continua depois que você entrar.",
    pastas: "A pasta dos sigilosos fica fora do acervo (e o acervo, fora dela): tudo o que está no acervo é lido pela IA e copiado para a nuvem. A pauta exportada também fica fora, porque traz as partes dos processos sigilosos.",
    download: "Não zere a pausa entre processos em listas grandes: rajada de acessos pode ser lida pelo portal como abuso.",
    transcricao: "A transcrição roda no próprio computador, sem internet: o áudio da audiência não sai da máquina.",
  };

  // ================================================================ acessos
  /**
   * Folha para cadastrar ou trocar o usuário e a senha de um portal.
   * Devolve true se gravou ou apagou (quem chamou recarrega a lista).
   * Usada aqui e na revisão do lote (Processos).
   */
  async function editarAcesso({ portal, rotulo, usuario, sistema, temSenha, novo }) {
    let escolhaPortal = null;
    const conteudo = [];
    if (novo) {
      let tribunais = [];
      try { tribunais = await api.tribunais(); } catch (_e) { tribunais = []; }
      const opcoes = [];
      for (const t of tribunais) {
        if (t.sistema === "esaj" || t.sistema === "eproc") opcoes.push([`${t.sistema}:${t.sigla}`, `${t.sigla} · ${nomeSistema(t.sistema)}`, t.sistema]);
        if (t.alternativo === "esaj" || t.alternativo === "eproc") opcoes.push([`${t.alternativo}:${t.sigla}`, `${t.sigla} · ${nomeSistema(t.alternativo)}`, t.alternativo]);
      }
      escolhaPortal = el("select", { classe: "campo", id: "acesso-portal" }, opcoes.map(([v, r]) => el("option", { value: v, texto: r })));
      escolhaPortal._opcoes = opcoes;
      conteudo.push(el("div", {}, el("label", { classe: "rotulo", for: "acesso-portal", texto: "Portal" }), escolhaPortal));
    }
    const sistemaAtual = () => (escolhaPortal ? String(escolhaPortal.value).split(":")[0] : sistema || String(portal).split(":")[0]);
    const rotuloUsuario = el("label", { classe: "rotulo", for: "acesso-usuario" });
    const campoUsuario = el("input", { classe: "campo", id: "acesso-usuario", autocomplete: "username", spellcheck: "false" });
    campoUsuario.value = usuario || "";
    const campoSenha = el("input", { classe: "campo", id: "acesso-senha", type: "password", autocomplete: "current-password", placeholder: temSenha ? "Digite a senha de novo para trocar" : "" });
    const mostrar = botao({ icone: "olho", titulo: "Mostrar a senha", tamanho: "pequeno", tipo: "texto", acao: () => {
      campoSenha.type = campoSenha.type === "password" ? "text" : "password";
      mostrar.setAttribute("aria-pressed", String(campoSenha.type === "text"));
    } });
    const ajuda = el("p", { classe: "ajuda-campo erro", hidden: true, "aria-live": "polite" });
    const lembrar = interruptor({ marcado: true, rotulo: "Lembrar neste computador", id: "acesso-lembrar" });
    const atualizarRotulo = () => { rotuloUsuario.textContent = sistemaAtual() === "eproc" ? "Usuário (CPF ou sigla)" : "CPF ou usuário"; };
    if (escolhaPortal) escolhaPortal.addEventListener("change", atualizarRotulo);
    atualizarRotulo();
    conteudo.push(
      el("div", {}, rotuloUsuario, campoUsuario),
      el("div", {}, el("label", { classe: "rotulo", for: "acesso-senha", texto: "Senha" }),
        el("div", { classe: "microfone-linha" }, campoSenha, mostrar)),
      ajuda,
      el("label", { classe: "linha-sigilo", for: "acesso-lembrar" },
        icone("cadeado"),
        el("span", { classe: "linha-texto" },
          el("span", { classe: "linha-titulo", texto: "Lembrar neste computador" }),
          el("span", { classe: "linha-sub", texto: "Cifrada pelo Windows, só a sua conta lê. Desligado, a senha vale até fechar o Helestron." })),
        lembrar));

    const botoes = [];
    if (!novo && (temSenha || usuario)) {
      botoes.push({ rotulo: "Apagar", tipo: "texto", espaco: true, acao: async () => {
        const ok = await folha.confirmar({ titulo: `Apagar o acesso ao ${rotulo}?`, mensagem: "O usuário e a senha guardados neste computador são apagados. Na próxima vez, o navegador abre para você entrar.", confirmar: "Apagar", perigo: true });
        if (!ok) return false;
        await api.acessos.apagar(portal);
        aviso({ titulo: "Acesso apagado", mensagem: rotulo, tipo: "sucesso" });
        return true;
      } });
    }
    botoes.push({ rotulo: "Cancelar", valor: false }, { rotulo: "Salvar", tipo: "primario", padrao: true, acao: async () => {
      const u = campoUsuario.value.trim(), s = campoSenha.value;
      if (!u || !s) {
        ajuda.textContent = !u ? "Informe o usuário." : "Informe a senha.";
        ajuda.hidden = false;
        (!u ? campoUsuario : campoSenha).focus();
        return false;
      }
      const alvo = escolhaPortal ? escolhaPortal.value : portal;
      await api.acessos.gravar(alvo, u, s, { lembrar: !!lembrar.checked });
      aviso({ titulo: "Acesso guardado", mensagem: escolhaPortal ? escolhaPortal.selectedOptions[0].textContent : rotulo, tipo: "sucesso" });
      return true;
    } });
    const f = folha.abrir({
      titulo: novo ? "Novo acesso a um portal" : `Acesso ao ${rotulo}`, icone: "chave", conteudo, botoes,
      mensagem: novo ? "Escolha o portal e informe o usuário e a senha que você usa nele." : null,
    });
    campoSenha.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); f.rodape.querySelector("[data-padrao]").click(); } });
    const r = await f.resultado;
    return r === true;
  }
  H.acessos = { editar: editarAcesso };

  // ================================================================ campos do config
  function valorDe(c) {
    const v = H.loja.config && H.loja.config.valores && H.loja.config.valores[c.secao];
    return v && v[c.chave] !== undefined && v[c.chave] !== null ? v[c.chave] : "";
  }

  async function gravar(c, valor) {
    const r = await api.config.gravar(c.secao, c.chave, valor);
    const final = r && r.valor !== undefined ? r.valor : valor;
    const v = H.loja.config.valores;
    v[c.secao] = v[c.secao] || {};
    v[c.secao][c.chave] = final;
    return final;
  }

  function marcaSalvo(caixa) {
    trocar(caixa, el("span", { classe: "valor-salvo" }, icone("check"), "Salvo"));
    clearTimeout(caixa._t);
    caixa._t = setTimeout(() => trocar(caixa), 1800);
  }

  function opcoesDe(c) {
    return (c.opcoes || []).map((o) => (typeof o === "object" ? { valor: String(o.valor), rotulo: o.rotulo || String(o.valor) } : { valor: String(o), rotulo: String(o) }));
  }

  /**
   * O microfone das audiências: uma lista com os microfones deste
   * computador, guardado pelo NOME (o número muda quando se liga ou desliga
   * um aparelho USB). A regra é a mesma da tela Audiências
   * (H.app.resolverMicrofone): um nome guardado que não está mais ligado
   * aparece como "Não encontrado" - nunca troca em silêncio pelo padrão do
   * Windows -, e o número antigo que sumiu não aparece como se fosse um nome.
   */
  function campoMicrofone(c) {
    const id = `cfg-${c.secao}-${c.chave}`;
    const salvo = el("span");
    const sel = el("select", { classe: "campo campo-pequeno campo-microfone", id, aria: { label: "Microfone" } },
      el("option", { value: "", texto: "Carregando os microfones…" }));
    const NOTA = "Guardado pelo nome: trocar a porta USB não muda a escolha.";
    const nota = el("span", { id: "nota-microfone", texto: NOTA });
    const titulo = () => { sel.title = sel.selectedOptions.length ? sel.selectedOptions[0].textContent : ""; };
    let antes = String(valorDe(c) || "");
    (async () => {
      let lista = [];
      try {
        lista = await api.transcricao.microfones();
      } catch (erro) {
        // Sem a lista, o guardado continua escolhido; o padrão só sem nada guardado.
        trocar(sel, antes ? el("option", { value: antes, texto: /^\d+$/.test(antes) ? "Microfone escolhido antes" : antes }) : null,
          el("option", { value: "", texto: "Padrão do Windows" }));
        sel.value = antes;
        titulo();
        nota.textContent = erro.message;
        nota.classList.add("erro");
        return;
      }
      const escolha = H.app.resolverMicrofone(lista, valorDe(c));
      if (escolha.regravar) gravar(c, escolha.regravar).catch(() => {});
      trocar(sel, escolha.opcoes.map((o) => el("option", { value: o.valor, texto: o.rotulo })));
      sel.value = escolha.valor;
      titulo();
      nota.classList.toggle("erro", !!escolha.problema);
      nota.textContent = escolha.problema || NOTA;
      antes = escolha.valor;
    })();
    sel.addEventListener("change", async () => {
      titulo();
      try {
        antes = String(await gravar(c, sel.value));
        nota.classList.remove("erro");
        nota.textContent = NOTA;
        marcaSalvo(salvo);
      } catch (erro) {
        sel.value = antes;
        titulo();
        folha.erro(erro);
      }
    });
    return linha({ titulo: "Microfone", sub: nota, classe: "linha-microfone", acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } }, salvo, sel) });
  }

  /** Uma linha de ajuste, conforme o tipo do campo. */
  function campo(c, ctx) {
    if (c.secao === "transcricao" && c.chave === "dispositivo") return campoMicrofone(c);
    const id = `cfg-${c.secao}-${c.chave}`;
    const valor = valorDe(c);
    const salvo = el("span");
    if (c.tipo === "flag") {
      return linha({ titulo: c.rotulo, sub: c.ajuda, acessorio: interruptor({ marcado: H.app.flag(valor), rotulo: c.rotulo, id, aoMudar: (v) => gravar(c, v) }) });
    }
    if (c.tipo === "inteiro") {
      const entrada = el("input", { type: "number", id, inputmode: "numeric", min: "0", aria: { label: c.rotulo } });
      entrada.value = String(valor);
      let anterior = String(valor);
      const salvar = H.ui.debounce(async () => {
        if (entrada.value === anterior) return;
        try {
          const final = await gravar(c, Number(entrada.value));
          anterior = String(final);
          entrada.value = anterior;
          marcaSalvo(salvo);
        } catch (erro) {
          entrada.value = anterior;
          folha.erro(erro);
        }
      }, 600);
      const minimo = typeof c.minimo === "number" ? c.minimo : 0;
      const maximo = typeof c.maximo === "number" ? c.maximo : Infinity;
      entrada.min = String(minimo);
      if (maximo !== Infinity) entrada.max = String(maximo);
      const passo = (d) => { entrada.value = String(Math.min(maximo, Math.max(minimo, (Number(entrada.value) || 0) + d))); salvar(); };
      entrada.addEventListener("change", salvar);
      const stepper = el("span", { classe: "passo-numero" },
        el("button", { type: "button", aria: { label: "Diminuir" }, on: { click: () => passo(-1) } }, icone("menos")),
        entrada,
        el("button", { type: "button", aria: { label: "Aumentar" }, on: { click: () => passo(1) } }, icone("mais")));
      return linha({ titulo: c.rotulo, sub: c.ajuda, acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } }, salvo, stepper) });
    }
    if (c.tipo === "escolha") {
      const opcoes = opcoesDe(c);
      const curtas = opcoes.length <= 3 && opcoes.every((o) => o.rotulo.length <= 18);
      if (curtas) {
        const seg = H.ui.segmentado({ opcoes, valor: String(valor), rotulo: c.rotulo, aoMudar: async (v) => {
          const antes = String(valorDe(c));
          try { await gravar(c, v); marcaSalvo(salvo); } catch (erro) { seg.definir(antes); folha.erro(erro); }
        } });
        seg.id = id;
        return linha({ titulo: c.rotulo, sub: c.ajuda, acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } }, salvo, seg) });
      }
      const sel = el("select", { classe: "campo campo-pequeno", id, aria: { label: c.rotulo }, estilo: { width: "auto", maxWidth: "340px" } }, opcoes.map((o) => el("option", { value: o.valor, texto: o.rotulo })));
      sel.value = String(valor);
      let antes = sel.value;
      sel.addEventListener("change", async () => {
        try { await gravar(c, sel.value); antes = sel.value; marcaSalvo(salvo); } catch (erro) { sel.value = antes; folha.erro(erro); }
      });
      return linha({ titulo: c.rotulo, sub: c.ajuda, acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } }, salvo, sel) });
    }
    if (c.tipo === "pasta") {
      const caminho = el("span", { classe: "caminho", texto: valor || "(não definida)" });
      const alterar = botao({ rotulo: "Alterar…", tamanho: "pequeno", acao: async () => {
        let novo = null;
        try {
          novo = await api.escolherPasta({ titulo: c.rotulo, inicial: valor || "" });
        } catch (erro) {
          if (erro.codigo !== "sem_dialogo") throw erro;
          novo = await folha.entrada({ titulo: c.rotulo, rotulo: "Caminho da pasta", valor: valorDe(c), mensagem: c.ajuda, icone: "pasta", confirmar: "Usar esta pasta" });
        }
        if (!novo) return;
        const final = await gravar(c, novo);
        caminho.textContent = final;
        aviso({ titulo: "Pasta alterada", mensagem: final, tipo: "sucesso" });
        H.app.recarregarEstado().catch(() => {});
      } });
      return linha({
        titulo: c.rotulo, sub: el("span", {}, c.ajuda ? el("span", { estilo: { display: "block" }, texto: c.ajuda }) : null, caminho),
        acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } },
          valor ? botao({ icone: "externo", titulo: "Abrir a pasta", tamanho: "pequeno", tipo: "texto", acao: () => api.abrir("pasta", valorDe(c)) }) : null,
          alterar),
      });
    }
    // texto
    const longo = String(valor).length > 60 || c.chave === "contexto" || c.chave === "falantes";
    const entrada = longo
      ? el("textarea", { classe: "campo", id, rows: c.chave === "contexto" ? "4" : "2", aria: { label: c.rotulo } })
      : el("input", { classe: "campo campo-pequeno", id, aria: { label: c.rotulo }, estilo: { textAlign: "right", maxWidth: "300px" }, spellcheck: "false" });
    entrada.value = String(valor);
    let anterior = entrada.value;
    const salvar = async () => {
      if (entrada.value === anterior) return;
      try {
        const final = await gravar(c, entrada.value);
        anterior = String(final);
        marcaSalvo(salvo);
        if (c.secao === "geral" && c.chave === "nome_usuario") H.app.recarregarEstado().catch(() => {});
      } catch (erro) {
        entrada.value = anterior;
        folha.erro(erro);
      }
    };
    entrada.addEventListener("blur", salvar);
    entrada.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !longo) { ev.preventDefault(); entrada.blur(); } });
    if (longo) {
      const bloco = el("div", { classe: "linha linha-bloco" },
        el("label", { classe: "linha-titulo", for: id, estilo: { display: "flex", justifyContent: "space-between" } }, c.rotulo, salvo),
        c.ajuda ? el("span", { classe: "linha-sub", estilo: { marginBottom: "8px" }, texto: c.ajuda }) : null,
        entrada);
      return bloco;
    }
    return linha({ titulo: c.rotulo, sub: c.ajuda, acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } }, salvo, entrada) });
  }

  // ================================================================ cada grupo
  async function telaAcessos(ctx, campos) {
    const lista = el("div", {}, H.ui.esqueleto(2));
    // O teste de cada portal (portal → id da tarefa), vivo enquanto a janela
    // estiver aberta. O resultado aparece na própria linha, ao lado do botão,
    // e não num aviso por cima da lista.
    const testes = H.loja.testesAcesso || (H.loja.testesAcesso = new Map());
    const naTela = H.loja.resultadosNaTela || new Set();
    for (const id of testes.values()) naTela.add(id);
    ctx.aoSair(() => { for (const id of testes.values()) naTela.delete(id); });
    let acessos = [];

    function situacaoDoTeste(portal) {
      const id = testes.get(portal);
      if (!id) return null;
      const t = H.loja.tarefas.get(id) || { estado: "rodando" };
      if (t.estado === "rodando") {
        return el("span", { classe: "resultado-teste" }, el("span", { classe: "girando", estilo: { width: "12px", height: "12px", borderWidth: "1.5px" } }), "Testando o acesso…");
      }
      if (t.estado === "concluida") {
        const hora = t.fim ? fmt.hora(t.fim) : "";
        return el("span", { classe: "resultado-teste ok" }, icone("check-circulo", { tamanho: 14 }), hora ? `Acesso confirmado às ${hora}.` : "Acesso confirmado.");
      }
      if (t.estado === "falhou") {
        return el("span", { classe: "resultado-teste erro" }, icone("aviso", { tamanho: 14 }), `O teste falhou. ${t.erro || t.status || "O portal não respondeu."}`);
      }
      return el("span", { classe: "resultado-teste" }, "Teste interrompido.");
    }

    const desenhar = () => {
      const linhas = acessos.map((a) => {
        const [sistema, tribunal] = String(a.portal).split(":");
        const rotulo = a.rotulo || a.portal;
        const id = testes.get(a.portal);
        const t = id ? H.loja.tarefas.get(id) : null;
        const testando = !!id && (!t || t.estado === "rodando");
        // Testar e Alterar são botões irmãos numa linha que não é botão: um
        // botão dentro de outro abria a folha da senha junto com o teste.
        const testar = a.tem_senha ? botao({ rotulo: testando ? "Testando…" : "Testar", tamanho: "pequeno", tipo: "texto", desativado: testando,
          atributos: { "aria-label": `Testar o acesso ao ${rotulo}` }, acao: async () => {
            const r = await api.acessos.testar(tribunal, sistema);
            testes.set(a.portal, r.tarefa);
            naTela.add(r.tarefa);
            desenhar();
          } }) : null;
        const temAlgo = a.tem_senha || a.usuario;
        const alterar = botao({ rotulo: temAlgo ? "Alterar" : "Cadastrar", tamanho: "pequeno", tipo: temAlgo ? "texto" : "tonal",
          atributos: { "aria-label": `${temAlgo ? "Alterar" : "Cadastrar"} o acesso ao ${rotulo}` },
          acao: async () => {
            if (await editarAcesso({ portal: a.portal, rotulo, usuario: a.usuario, sistema, temSenha: a.tem_senha })) {
              testes.delete(a.portal);        // o resultado era da senha anterior
              carregar();
            }
          } });
        const sub = a.so_agora ? `Senha só até fechar o Helestron${a.usuario ? " · " + a.usuario : ""}`
          : a.tem_senha ? `Senha guardada${a.usuario ? " · " + a.usuario : ""}` : "Sem senha guardada";
        const teste = a.tem_senha ? situacaoDoTeste(a.portal) : null;
        const l = linha({
          icone: a.tem_senha ? "chave" : "pessoa", cor: a.tem_senha ? "verde" : "cinza",
          titulo: rotulo,
          sub: teste ? el("span", {}, el("span", { estilo: { display: "block" }, texto: sub }), teste) : sub,
          acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } }, testar, alterar),
        });
        l.dataset.portal = a.portal;
        return l;
      });
      const adicionar = el("button", { type: "button", classe: "linha com-icone", id: "adicionar-acesso", on: { click: async () => { if (await editarAcesso({ novo: true })) carregar(); } } },
        el("span", { classe: "bloco-icone cor-azul" }, icone("mais")),
        el("span", { classe: "linha-texto" }, el("span", { classe: "linha-titulo", estilo: { color: "var(--azul-texto)" }, texto: "Adicionar acesso" })));
      trocar(lista, grupo({ titulo: "Portais", linhas: linhas.concat([adicionar]), rodape: RODAPES.acessos }));
    };
    const carregar = async () => {
      try { acessos = await api.acessos.listar(); } catch (erro) { trocar(lista, H.ui.faixa({ tipo: "erro", texto: erro.message })); return; }
      if (!ctx.vivo) return;
      desenhar();
    };
    ctx.on("tarefa", (t) => {
      if (t && t.tipo === "teste_login" && Array.from(testes.values()).includes(t.id)) desenhar();
    });
    await carregar();
    return [lista, campos.length ? grupo({ titulo: "Como entrar", linhas: campos.map((c) => campo(c, ctx)) }) : null, grupoEnderecos(ctx)];
  }

  // ================================================================ endereços dos portais
  /**
   * Quando o tribunal muda o endereço do portal antes de o Helestron ser
   * atualizado: a correção fica neste computador (enderecos-locais.json) e
   * vale por cima do catálogo. Em branco, volta ao endereço do catálogo.
   */
  async function corrigirEndereco(portalInicial) {
    let tribunais = [];
    try { tribunais = await api.tribunais(); } catch (_e) { tribunais = []; }
    const portais = [];
    for (const t of tribunais) {
      for (const s of [t.sistema, t.alternativo]) {
        if (s === "esaj" || s === "eproc") portais.push([`${s}:${t.sigla}`, `${t.sigla} · ${nomeSistema(s)}`]);
      }
    }
    const escolha = el("select", { classe: "campo", id: "endereco-portal" }, portais.map(([v, r]) => el("option", { value: v, texto: r })));
    if (portalInicial) escolha.value = portalInicial;
    const campos = el("div", { classe: "formulario", estilo: { gap: "12px" } });
    let atuais = [];
    const desenhar = async () => {
      trocar(campos, H.ui.esqueleto(1));
      let dados = null;
      try { dados = await api.acessos.enderecosDoPortal(escolha.value); } catch (erro) { trocar(campos, H.ui.faixa({ tipo: "erro", texto: erro.message })); return; }
      atuais = dados.enderecos || [];
      trocar(campos, atuais.map((e, i) => {
        const entrada = el("input", { classe: "campo", id: "endereco-" + i, spellcheck: "false", placeholder: e.padrao || "https://", dados: { grau: e.grau } });
        entrada.value = e.corrigido ? e.url : "";
        return el("div", {},
          el("label", { classe: "rotulo", for: "endereco-" + i, texto: e.rotulo }),
          entrada,
          el("p", { classe: "ajuda-campo", texto: e.corrigido ? `Corrigido. O do catálogo é ${e.padrao || "—"}.` : `Em branco: vale o do catálogo (${e.padrao || "—"}).` }));
      }));
    };
    escolha.addEventListener("change", desenhar);
    await desenhar();
    const f = folha.abrir({
      titulo: "Endereço do portal", icone: "link",
      mensagem: "Use só quando o tribunal mudar o endereço do e-SAJ ou do eProc e o Helestron ainda não souber. Deixe em branco para voltar ao endereço que vem com o programa.",
      conteudo: [el("div", {}, el("label", { classe: "rotulo", for: "endereco-portal", texto: "Portal" }), escolha), campos],
      botoes: [{ rotulo: "Cancelar", valor: false }, { rotulo: "Salvar", tipo: "primario", padrao: true, acao: async () => {
        const portal = escolha.value;
        let mudou = 0;
        for (const entrada of campos.querySelectorAll("input[data-grau]")) {
          const atual = atuais.find((e) => e.grau === entrada.dataset.grau) || {};
          const novo = entrada.value.trim();
          const antes = atual.corrigido ? atual.url : "";
          if (novo === antes) continue;
          await api.acessos.corrigirEndereco(portal, entrada.dataset.grau, novo);
          mudou++;
        }
        if (mudou) aviso({ titulo: "Endereço do portal salvo", mensagem: (portais.find(([v]) => v === portal) || [portal, portal])[1], tipo: "sucesso" });
        return true;
      } }],
    });
    return (await f.resultado) === true;
  }

  function grupoEnderecos(ctx) {
    const caixa = el("div", { id: "grupo-enderecos" });
    const carregar = async () => {
      let lista = [];
      try { lista = await api.acessos.enderecos(); } catch (_e) { lista = []; }
      if (!ctx.vivo) return;
      const linhas = lista.map((e) => linha({
        icone: "link", cor: "ambar", titulo: `${e.rotulo_portal || e.portal} — ${e.rotulo}`,
        sub: el("span", { classe: "caminho", texto: e.url }),
        acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } },
          botao({ rotulo: "Alterar", tamanho: "pequeno", tipo: "texto", acao: async () => { if (await corrigirEndereco(e.portal)) carregar(); } }),
          botao({ rotulo: "Restaurar", tamanho: "pequeno", tipo: "texto", acao: async () => {
            await api.acessos.corrigirEndereco(e.portal, e.grau, "");
            aviso({ titulo: "Endereço restaurado", mensagem: `${e.rotulo_portal || e.portal}: vale de novo o do catálogo.`, tipo: "sucesso" });
            carregar();
          } })),
      }));
      const corrigir = el("button", { type: "button", classe: "linha com-icone", id: "corrigir-endereco", on: { click: async () => { if (await corrigirEndereco()) carregar(); } } },
        el("span", { classe: "bloco-icone cor-azul" }, icone("link")),
        el("span", { classe: "linha-texto" }, el("span", { classe: "linha-titulo", estilo: { color: "var(--azul-texto)" }, texto: "Corrigir o endereço de um portal" })));
      trocar(caixa, grupo({
        titulo: "Endereço do portal", linhas: linhas.concat([corrigir]),
        rodape: "Raramente é preciso: o Helestron já conhece os endereços do e-SAJ e do eProc de cada tribunal. Use quando uma mensagem disser que o endereço do portal mudou.",
      }));
    };
    carregar();
    return caixa;
  }

  async function telaPastas(ctx, campos) {
    const pastas = (H.loja.estado && H.loja.estado.pastas) || {};
    const ROTULOS = [["processos", "Processos baixados", "doc-baixar", "navy"], ["transcricoes", "Transcrições", "microfone", "azul"], ["pauta", "Pauta exportada", "planilha", "ciano"], ["logs", "Registros do programa", "lista", "cinza"]];
    const atalhos = ROTULOS.filter(([k]) => pastas[k]).map(([k, rotulo, nomeIcone, cor]) => linha({
      icone: nomeIcone, cor, titulo: rotulo, sub: el("span", { classe: "caminho", texto: pastas[k] }),
      acessorio: botao({ rotulo: "Abrir", tamanho: "pequeno", tipo: "tonal", acao: () => api.abrir("pasta", pastas[k]) }),
    }));
    return [
      campos.length ? grupo({ titulo: "Pastas principais", linhas: campos.map((c) => campo(c, ctx)), rodape: RODAPES.pastas }) : null,
      atalhos.length ? grupo({ titulo: "Atalhos", linhas: atalhos }) : null,
    ];
  }

  // O servidor manda 'descricao' (frase pronta) e 'recomendado_para' (códigos).
  const PARA = { ao_vivo: "a audiência ao vivo", revisao: "a revisão e as gravações" };
  function sobreModelo(m) {
    if (m.descricao) return m.descricao;
    const lista = Array.isArray(m.recomendado_para) ? m.recomendado_para : (m.recomendado_para ? [m.recomendado_para] : []);
    const textos = lista.map((x) => PARA[x] || String(x).replace(/_/g, " "));
    return textos.length ? "para " + textos.join(" e ") : "";
  }

  /** Separação automática de falantes: situação e, se faltarem os modelos de voz, o botão para baixá-los. */
  function grupoFalantes(ctx) {
    const caixa = el("div", { id: "grupo-falantes" });
    let tarefa = null;
    const carregar = async () => {
      let e = null;
      try { e = await api.transcricao.falantes(); } catch (_e) { e = null; }
      if (!ctx.vivo) return;
      if (!e) { trocar(caixa); return; }
      const rodando = tarefa && H.loja.tarefas.get(tarefa) && H.loja.tarefas.get(tarefa).estado === "rodando";
      let sub, acessorio;
      if (e.disponivel) {
        sub = e.embutidos ? "Os modelos de voz vieram com o instalador." : "Os modelos de voz estão neste computador.";
        acessorio = pilula("Pronta", "verde", "check");
      } else if (e.biblioteca) {
        sub = `Faltam os modelos de voz (cerca de ${fmt.mb(e.tamanho_mb || 47)}, baixados uma vez do GitHub). Sem eles, a revisão não separa as vozes sozinha; os falantes marcados durante a audiência continuam valendo.`;
        acessorio = rodando
          ? el("span", { classe: "valor-salvo" }, el("span", { classe: "girando" }), "Baixando…")
          : botao({ rotulo: "Baixar os modelos de voz", tamanho: "pequeno", tipo: "tonal", acao: async () => {
            const r = await api.transcricao.baixarFalantes();
            tarefa = r.tarefa;
            aviso({ titulo: "Baixando os modelos de voz", mensagem: "Acompanhe na barra lateral.", tipo: "info" });
            carregar();
          } });
      } else {
        sub = "O componente da separação de vozes não está nesta instalação. Instale o Helestron de novo com o instalador Helestron-Setup: os seus dados ficam.";
        acessorio = pilula("Indisponível", "ambar", "aviso");
      }
      trocar(caixa, grupo({
        titulo: "Separação de falantes",
        linhas: [linha({ icone: "pessoas", cor: e.disponivel ? "azul" : "cinza", titulo: "Separação automática das vozes", sub, acessorio })],
        rodape: "Usada na revisão final: identifica as trocas de voz e atribui cada fala a um participante.",
      }));
    };
    ctx.on("tarefa", (t) => { if (t.tipo === "modelo" && (!tarefa || t.id === tarefa) && t.estado !== "rodando") { tarefa = null; carregar(); } });
    carregar();
    return caixa;
  }

  async function telaTranscricao(ctx, campos) {
    const modelos = el("div", {}, H.ui.esqueleto(2));
    const carregar = async () => {
      let lista = [];
      try { lista = await api.transcricao.modelos(); } catch (_e) { lista = []; }
      if (!ctx.vivo) return;
      if (!lista.length) { trocar(modelos); return; }
      trocar(modelos, grupo({
        titulo: "Modelos de transcrição",
        rodape: "O modelo small vem com o instalador e basta para a transcrição ao vivo. Os maiores, mais precisos, servem para a revisão e para as gravações.",
        linhas: lista.map((m) => linha({
          icone: "chip", cor: m.instalado || m.embutido ? "azul" : "cinza",
          titulo: m.rotulo || m.nome,
          sub: [fmt.mb(m.tamanho_mb || 0), sobreModelo(m)].filter(Boolean).join(" · "),
          acessorio: m.instalado || m.embutido
            ? pilula(m.embutido ? "Embutido" : "Instalado", "verde", "check")
            : botao({ rotulo: "Baixar", tamanho: "pequeno", tipo: "tonal", acao: async () => {
              await api.transcricao.baixarModelo(m.nome);
              aviso({ titulo: `Baixando o modelo ${m.rotulo || m.nome}`, mensagem: "Acompanhe na barra lateral.", tipo: "info" });
            } }),
        })),
      }));
    };
    ctx.on("tarefa", (t) => { if (t.tipo === "modelo" && t.estado !== "rodando") carregar(); });
    await carregar();
    const curtos = campos.filter((c) => !(c.tipo === "texto" && (c.chave === "contexto" || c.chave === "falantes")));
    const longos = campos.filter((c) => !curtos.includes(c));
    return [
      curtos.length ? grupo({ titulo: "Transcrição", linhas: curtos.map((c) => campo(c, ctx)), rodape: RODAPES.transcricao }) : null,
      longos.length ? grupo({ titulo: "Participantes e vocabulário", linhas: longos.map((c) => campo(c, ctx)) }) : null,
      modelos,
      grupoFalantes(ctx),
    ];
  }

  async function telaPauta(ctx, campos) {
    const lista = el("div", {}, H.ui.esqueleto(2));
    const carregar = async () => {
      let fontes = [];
      try { fontes = await api.pauta.fontes(); } catch (_e) { fontes = []; }
      if (!ctx.vivo) return;
      const linhas = fontes.map((f) => linha({
        icone: f.modo === "capturado" ? "capturar" : "sincronizar", cor: f.ultimo_erro ? "ambar" : "ciano",
        titulo: f.rotulo || `${nomeSistema(f.sistema)} · ${f.tribunal}`,
        sub: el("span", {},
          el("span", { estilo: { display: "block" }, texto: [
            f.modo === "capturado" ? "Endereço capturado no portal" : f.url ? "Pauta encontrada pelo Helestron" : "Pauta ainda não encontrada",
            f.ultima_sincronizacao ? "sincronizada " + fmt.quando(f.ultima_sincronizacao) : "ainda não sincronizada",
          ].join(" · ") }),
          f.menu ? el("span", { estilo: { display: "block" }, texto: "Caminho no portal: " + f.menu }) : null,
          // Certificado, entrada manual ou senha não guardada: o portal só abre
          // com a pessoa à frente, e o monitoramento não a sincroniza.
          el("span", { estilo: { display: "block" }, texto: f.monitorada
            ? "Entra no monitoramento automático."
            : f.exige_presenca
              ? `Fica fora do monitoramento automático: ${f.motivo_presenca || "o login exige você à frente"}. Sincronize na tela Pauta quando quiser, ou use a entrada por usuário e senha, com a senha guardada, em Acessos aos portais.`
              : "Fica fora do monitoramento até a primeira sincronização bem-sucedida (ou uma captura)." }),
          f.ultimo_erro ? el("span", { estilo: { display: "block", color: "var(--ambar-texto, var(--ambar))" }, texto: "Último erro: " + f.ultimo_erro }) : null),
        acessorio: el("span", { classe: "grupo-botoes", estilo: { flexWrap: "nowrap" } },
          f.monitorada ? pilula("Monitorada", "verde", "sino") : f.exige_presenca ? pilula("Só com você", "ambar", "pessoa") : pilula("Sem endereço salvo", "cinza"),
          botao({ icone: "lixeira", titulo: "Remover esta fonte", tamanho: "pequeno", tipo: "texto", acao: async () => {
          const ok = await folha.confirmar({ titulo: "Remover esta fonte?", mensagem: "As audiências já trazidas continuam na pauta; só deixam de ser conferidas no portal.", confirmar: "Remover", perigo: true });
          if (!ok) return;
          await api.pauta.removerFonte(f.id);
          carregar();
        } })),
      }));
      const adicionar = el("button", { type: "button", classe: "linha com-icone", id: "adicionar-fonte", on: { click: async () => {
        const escolha = await H.pauta.escolherFonte({ titulo: "Nova fonte da pauta", confirmar: "Adicionar", comRotulo: true, mensagem: "O Helestron entra no portal com o acesso cadastrado e procura a pauta de audiências." });
        if (!escolha) return;
        try { await api.pauta.salvarFonte(escolha); } catch (erro) { folha.erro(erro); return; }
        carregar();
      } } },
      el("span", { classe: "bloco-icone cor-azul" }, icone("mais")),
      el("span", { classe: "linha-texto" }, el("span", { classe: "linha-titulo", estilo: { color: "var(--azul-texto)" }, texto: "Adicionar fonte" })));
      trocar(lista, grupo({
        titulo: "Fontes da pauta", linhas: linhas.concat([adicionar]),
        rodape: "Cada fonte é um portal (e-SAJ ou eProc de um tribunal). Quando a descoberta automática não acha a pauta, use “Capturar no portal”, na tela Pauta: o endereço fica lembrado aqui.",
      }));
    };
    await carregar();
    return [campos.length ? grupo({ titulo: "Monitoramento e exportação", linhas: campos.map((c) => campo(c, ctx)) }) : null, lista];
  }

  async function telaSobre(ctx, campos) {
    const e = H.loja.estado || {};
    const modo = { janela: "Janela do aplicativo (WebView2)", edge: "Microsoft Edge em modo aplicativo", navegador: "Navegador padrão", servidor: "Só o servidor (sem janela)" }[e.modo] || e.modo || "—";
    const verificacao = el("div", {}, H.ui.esqueleto(4));
    let tarefaVerificacao = null;
    const carregar = async () => {
      let itens = [];
      try { itens = await api.verificacao.listar(); } catch (erro) { trocar(verificacao, H.ui.faixa({ tipo: "erro", texto: erro.message })); return; }
      if (!ctx.vivo) return;
      const nomesIcone = { ok: "check-circulo", aviso: "aviso", falha: "x-circulo" };
      const rotulos = { ok: "Em ordem", aviso: "Aviso", falha: "Falha" };
      trocar(verificacao, grupo({
        titulo: "Verificação da instalação",
        linhas: itens.map((i) => linha({
          titulo: i.nome,
          // O que fazer vai embaixo do detalhe: ao lado, um texto longo espremia o título.
          sub: el("span", {},
            el("span", { texto: i.detalhe || "" }),
            i.acao && i.situacao !== "ok" ? el("span", { classe: "verificacao-acao", texto: "O que fazer: " + i.acao }) : null),
          acessorio: icone(nomesIcone[i.situacao] || "info", { classe: "verificacao-icone situacao-" + (i.situacao || "info"), rotulo: rotulos[i.situacao] || i.situacao }),
        })),
      }));
    };
    ctx.on("tarefa", (t) => { if (t.tipo === "verificacao" && (t.id === tarefaVerificacao || !tarefaVerificacao) && t.estado !== "rodando") carregar(); });
    await carregar();
    const encerrar = async () => {
      const ok = await folha.confirmar({ titulo: "Encerrar o Helestron?", mensagem: "Downloads e transcrições em andamento são interrompidos. A gravação de uma audiência em curso é salva antes de fechar.", confirmar: "Encerrar", perigo: true, icone: "energia" });
      if (!ok) return;
      await api.encerrar();
      trocar(document.getElementById("pagina"), el("div", { classe: "pagina" }, cartao({ classe: "erro-secao" },
        vazio({ icone: "energia", titulo: "O Helestron foi encerrado", texto: "Pode fechar esta janela. Para abrir de novo, use o atalho na Área de Trabalho ou no Menu Iniciar." }))));
    };
    return [
      el("div", { classe: "sobre-topo" },
        H.ui.logo(72),
        el("div", {},
          el("p", { classe: "sobre-nome", texto: e.nome || "Helestron" }),
          el("p", { classe: "cartao-sub", texto: `Versão ${e.versao || "—"} · ${modo}` }))),
      el("div", { classe: "grupo-botoes", estilo: { marginBottom: "22px" } },
        botao({ rotulo: "Verificar a instalação", icone: "escudo", tipo: "primario", acao: async () => {
          const r = await api.verificacao.completa();
          tarefaVerificacao = r.tarefa;
          aviso({ titulo: "Verificação completa", mensagem: "Conferindo os arquivos, os módulos, o modelo e o navegador. Leva alguns segundos.", tipo: "info" });
        } }),
        e.pastas && e.pastas.logs ? botao({ rotulo: "Abrir os registros", icone: "lista", acao: () => api.abrir("pasta", e.pastas.logs) }) : null),
      verificacao,
      campos.length ? grupo({ titulo: "Outros ajustes", linhas: campos.map((c) => campo(c, ctx)) }) : null,
      grupo({
        titulo: "Sobre",
        linhas: [
          linha({ icone: "escudo", cor: "navy", titulo: "Ferramenta de apoio", sub: "Autos baixados, transcrições e o que a IA produzir são material de trabalho para conferência e decisão do magistrado (Resolução CNJ nº 615/2025)." }),
          linha({ icone: "texto", cor: "cinza", titulo: "Fonte Inter", sub: "© The Inter Project Authors · SIL Open Font License 1.1" }),
        ],
      }),
      grupo({ linhas: [el("button", { type: "button", classe: "linha", id: "encerrar-helestron", on: { click: () => encerrar().catch((x) => folha.erro(x)) } },
        el("span", { classe: "linha-texto" }, el("span", { classe: "linha-titulo", estilo: { color: "var(--vermelho-texto)" }, texto: "Encerrar o Helestron" })))] }),
    ];
  }

  // ================================================================ tela
  H.secoes = H.secoes || {};
  H.secoes.ajustes = {
    async montar(ctx) {
      const raiz = ctx.raiz;
      const cab = H.ui.cabecalho({ titulo: "Ajustes", subtitulo: "Tudo é salvo na hora." });
      const indice = cartao({ classe: "ajustes-indice", tag: "nav", aria: { label: "Grupos de ajustes" } });
      const detalhe = el("div", { classe: "ajustes-detalhe" });
      raiz.append(cab, el("div", { classe: "ajustes" }, indice, detalhe));

      try { await H.app.carregarConfig(true); } catch (erro) {
        trocar(detalhe, H.ui.faixa({ tipo: "erro", titulo: "Não consegui ler a configuração", texto: erro.message }));
        return;
      }
      const esquema = (H.loja.config && H.loja.config.esquema) || [];
      const porGrupo = new Map(GRUPOS.map((g) => [g.id, []]));
      for (const c of esquema) {
        const g = grupoDoCampo(c);
        if (g && porGrupo.has(g)) porGrupo.get(g).push(c);
      }

      const links = new Map();
      for (const g of GRUPOS) {
        const a = el("a", { classe: "linha com-icone", href: "#/ajustes/" + g.id, dados: { grupo: g.id } },
          blocoIcone(g.icone, g.cor), el("span", { classe: "linha-texto" }, el("span", { classe: "linha-titulo", texto: g.curto })));
        a.title = g.titulo;
        links.set(g.id, a);
        indice.appendChild(a);
      }

      let grupoCtx = null;
      const mostrar = async (id) => {
        const g = GRUPOS.find((x) => x.id === id) || GRUPOS[0];
        for (const [k, a] of links) {
          if (k === g.id) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
        }
        if (grupoCtx) grupoCtx.limpar();
        grupoCtx = H.contextoFilho(ctx);
        const campos = porGrupo.get(g.id) || [];
        const telas = { acessos: telaAcessos, pastas: telaPastas, transcricao: telaTranscricao, pauta: telaPauta, sobre: telaSobre };
        trocar(detalhe,
          el("h2", { classe: "ajustes-detalhe-titulo", id: "ajustes-" + g.id, texto: g.titulo }),
          el("p", { classe: "ajustes-detalhe-sub", texto: g.sub }),
          H.ui.esqueleto(3));
        let partes;
        if (telas[g.id]) {
          partes = await telas[g.id](grupoCtx, campos);
        } else {
          partes = [campos.length ? grupo({ linhas: campos.map((c) => campo(c, grupoCtx)), rodape: RODAPES[g.id] }) : vazio({ compacto: true, icone: "info", titulo: "Nada para ajustar aqui" })];
        }
        if (!grupoCtx.vivo) return;
        trocar(detalhe,
          el("h2", { classe: "ajustes-detalhe-titulo", id: "ajustes-" + g.id, texto: g.titulo }),
          el("p", { classe: "ajustes-detalhe-sub", texto: g.sub }),
          partes);
      };
      ctx.aoSair(() => grupoCtx && grupoCtx.limpar());

      await mostrar(ctx.rota.sub || "acessos");
      H.secoes.ajustes.rota = async (c) => { await mostrar(c.rota.sub || "acessos"); };
    },
  };
})();
