/* Helestron — Audiências: transcrição simultânea (especificação 7.2).
 *
 * Preparação: número do processo (com validação do dígito e sugestões da
 * pauta de hoje), tipo de audiência, segredo de justiça, microfone com
 * medidor de nível e os participantes F1–F8. O botão de gravar grande
 * começa a sessão; durante a audiência: cronômetro, texto ao vivo com tempo
 * e falante, rolagem automática, Pausar/Retomar, botões (e teclas F1–F8) de
 * quem está falando e Encerrar, que entrega o DOCX.
 *
 * A sessão vive no servidor (é única). Sair desta tela não para a gravação:
 * ao voltar, /api/transcricao/estado devolve as falas e o tempo, e a barra
 * lateral mostra uma bolinha vermelha em Audiências enquanto ela durar.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, botao, cartao, cabecalhoCartao, vazio, faixa, interruptor, trocar, folha, aviso, blocoIcone, pilula } = H.ui;
  const { fmt, api, cnj } = H;

  const TIPOS = ["Conciliação", "Instrução e julgamento", "Una", "Custódia", "Justificação", "Mediação", "Outra"];
  const PADRAO_FALANTES = ["Juiz(a)", "Promotor(a)", "Defensor(a)", "Advogado(a) do autor", "Advogado(a) do réu", "Testemunha", "Parte", "Outro"];
  const CORES = ["#0A66E8", "#1B3560", "#1584C2", "#4352D6", "#B26B00", "#1F8A4C", "#6B7280", "#B03A62"];
  const TIPOS_GRAVACAO = ["Áudio e vídeo|*.mp3;*.wav;*.m4a;*.ogg;*.flac;*.wma;*.aac;*.mp4;*.mkv;*.avi;*.mov;*.wmv;*.webm", "Todos os arquivos|*.*"];
  const ACEITAR_GRAVACAO = "audio/*,video/*,.mp3,.wav,.m4a,.ogg,.flac,.wma,.aac,.mp4,.mkv,.avi,.mov,.wmv,.webm";

  function lerLocal(chave, padrao) {
    try { return localStorage.getItem("helestron." + chave) || padrao; } catch (_e) { return padrao; }
  }
  function gravarLocal(chave, valor) {
    try { localStorage.setItem("helestron." + chave, valor); } catch (_e) { /* só conveniência */ }
  }

  function participantesDaConfig() {
    const texto = String(H.app.valorConfig("transcricao", "falantes", "") || "");
    const nomes = texto ? texto.split(";").map((s) => s.trim()) : PADRAO_FALANTES.slice();
    while (nomes.length < 8) nomes.push("");
    return nomes.slice(0, 8);
  }

  function rascunho() {
    if (!H.loja.audiencia) {
      H.loja.audiencia = { processo: "", tipo: lerLocal("tipo_audiencia", "Instrução e julgamento"), sigiloso: false, dispositivo: null, participantes: null, documento: null, falas: [] };
    }
    return H.loja.audiencia;
  }

  // ===================================================================== preparo
  function telaPreparo(ctx, irParaAoVivo) {
    const r = rascunho();
    if (!r.participantes) r.participantes = participantesDaConfig();
    const p = ctx.rota.params;
    if (p.get("processo")) {
      r.processo = cnj.mascarar(p.get("processo"));
      if (p.get("tipo")) r.tipo = p.get("tipo");
      r.sigiloso = p.get("sigiloso") === "1";
    }

    // --- processo
    const campoProcesso = el("input", {
      classe: "campo numero", id: "processo-audiencia", inputmode: "numeric", autocomplete: "off",
      placeholder: "0000000-00.0000.0.00.0000", maxlength: "25", spellcheck: "false",
    });
    campoProcesso.value = r.processo;
    const ajudaProcesso = el("p", { classe: "ajuda-campo", id: "ajuda-processo", "aria-live": "polite" });
    campoProcesso.setAttribute("aria-describedby", "ajuda-processo");

    const validar = () => {
      const d = cnj.digitos(campoProcesso.value);
      ajudaProcesso.classList.remove("erro", "ok");
      campoProcesso.classList.remove("invalido");
      if (!d.length) {
        ajudaProcesso.textContent = "É ele que dá nome ao documento.";
      } else if (d.length < 20) {
        ajudaProcesso.textContent = `Faltam ${20 - d.length} ${20 - d.length === 1 ? "dígito" : "dígitos"}.`;
      } else if (!cnj.valido(d)) {
        ajudaProcesso.textContent = "O dígito verificador não confere. Confira o número.";
        ajudaProcesso.classList.add("erro");
        campoProcesso.classList.add("invalido");
      } else {
        const trib = cnj.tribunal(d);
        ajudaProcesso.textContent = `Número válido${trib ? " · " + trib : ""}.`;
        ajudaProcesso.classList.add("ok");
      }
      r.processo = campoProcesso.value;
      botaoGravar.disabled = !(d.length === 20 && cnj.valido(d));
    };
    campoProcesso.addEventListener("input", () => {
      // Máscara que não briga com o cursor: só reformata quando se digita no fim.
      const noFim = campoProcesso.selectionStart === campoProcesso.value.length;
      if (noFim) campoProcesso.value = cnj.mascarar(campoProcesso.value);
      validar();
    });
    campoProcesso.addEventListener("paste", () => setTimeout(() => { campoProcesso.value = cnj.mascarar(campoProcesso.value); validar(); }, 0));

    // --- tipo
    const campoTipo = el("select", { classe: "campo", id: "tipo-audiencia" }, TIPOS.map((t) => el("option", { value: t, texto: t })));
    campoTipo.value = TIPOS.includes(r.tipo) ? r.tipo : "Outra";
    campoTipo.addEventListener("change", () => { r.tipo = campoTipo.value; gravarLocal("tipo_audiencia", r.tipo); });

    // --- sugestões da pauta de hoje
    const sugestoes = el("div", { classe: "sugestoes", aria: { label: "Audiências de hoje na pauta" } });
    const sigilo = interruptor({ marcado: r.sigiloso, rotulo: "Segredo de justiça", id: "sigilo-audiencia", aoMudar: (v) => { r.sigiloso = v; } });
    const carregarSugestoes = async () => {
      const hoje = fmt.iso(new Date());
      let lista = [];
      try { lista = ((await api.pauta.listar({ de: hoje, ate: hoje })).audiencias || []); } catch (_e) { lista = []; }
      lista = lista.filter((a) => a.processo && a.situacao !== "Cancelada" && a.situacao !== "Realizada");
      if (!ctx.vivo || !lista.length) return;
      trocar(sugestoes, el("span", { classe: "ajuda-campo", estilo: { margin: "0 4px 0 2px", alignSelf: "center" }, texto: "Hoje na pauta:" }),
        lista.slice(0, 6).map((a) => el("button", {
          type: "button", classe: "sugestao", title: [a.tipo, a.partes].filter(Boolean).join(" · "),
          on: { click: () => {
            campoProcesso.value = cnj.mascarar(a.processo);
            if (TIPOS.includes(a.tipo)) { campoTipo.value = a.tipo; r.tipo = a.tipo; }
            sigilo.checked = !!a.sigiloso;
            r.sigiloso = !!a.sigiloso;
            validar();
            campoProcesso.focus();
          } },
        }, icone("relogio", { tamanho: 13 }), `${a.hora} · ${a.processo}`)));
    };

    // --- microfone
    const campoMic = el("select", { classe: "campo", id: "microfone", aria: { label: "Microfone" } }, el("option", { value: "", texto: "Carregando os microfones…" }));
    const medidor = H.ui.medidor(22);
    const legendaMedidor = el("span", { texto: "Clique em Testar e fale algo: as barras devem se mexer." });
    let testando = false;
    const botaoTestar = botao({ rotulo: "Testar", icone: "ondas", acao: async () => {
      if (testando) await pararTeste(); else await iniciarTeste();
    } });
    botaoTestar.id = "testar-microfone";
    async function iniciarTeste() {
      await api.transcricao.testarMicrofone(valorDispositivo());
      testando = true;
      botaoTestar.querySelector("span").textContent = "Parar teste";
      legendaMedidor.textContent = "Fale algo: as barras devem se mexer.";
    }
    async function pararTeste() {
      testando = false;
      botaoTestar.querySelector("span").textContent = "Testar";
      medidor.definir(0);
      try { await api.transcricao.pararMicrofone(); } catch (_e) { /* já parou */ }
    }
    const valorDispositivo = () => (campoMic.value === "" ? "" : Number(campoMic.value));
    ctx.on("microfone_nivel", (d) => { if (testando) medidor.definir(d && d.nivel); });
    ctx.aoSair(() => { if (testando) api.transcricao.pararMicrofone().catch(() => {}); });
    campoMic.addEventListener("change", async () => {
      r.dispositivo = campoMic.value;
      api.config.gravar("transcricao", "dispositivo", campoMic.value === "" ? "" : String(campoMic.value)).catch(() => {});
      if (testando) { await pararTeste(); await iniciarTeste(); }
    });
    const carregarMicrofones = async () => {
      let lista = [];
      try { lista = await api.transcricao.microfones(); } catch (erro) {
        trocar(campoMic, el("option", { value: "", texto: "Microfone padrão do Windows" }));
        legendaMedidor.textContent = erro.message;
        return;
      }
      if (!ctx.vivo) return;
      const padrao = lista.find((m) => m.padrao);
      trocar(campoMic,
        el("option", { value: "", texto: "Padrão do Windows" + (padrao ? ` — ${padrao.nome}` : "") }),
        lista.map((m) => el("option", { value: String(m.indice), texto: m.nome })));
      const salvo = r.dispositivo !== null && r.dispositivo !== undefined ? r.dispositivo : H.app.valorConfig("transcricao", "dispositivo", "");
      if (salvo !== "" && lista.some((m) => String(m.indice) === String(salvo))) campoMic.value = String(salvo);
      if (!lista.length) legendaMedidor.textContent = "Nenhum microfone encontrado. Confira se ele está conectado e se o Windows permite o acesso.";
    };

    // --- participantes
    const salvarFalantes = H.ui.debounce(() => {
      api.config.gravar("transcricao", "falantes", r.participantes.map((s) => s.trim()).join(";")).catch(() => {});
    }, 900);
    const participantes = el("div", { classe: "participantes" }, r.participantes.map((nome, i) => {
      const campo = el("input", { classe: "campo", value: nome, maxlength: "40", aria: { label: `Participante da tecla F${i + 1}` }, placeholder: "(sem uso)" });
      campo.value = nome;
      campo.addEventListener("input", () => { r.participantes[i] = campo.value; salvarFalantes(); });
      return el("label", { classe: "participante" }, el("span", { classe: "tecla", texto: "F" + (i + 1) }), campo);
    }));

    // --- gravar
    const botaoGravar = el("button", { type: "button", classe: "botao-gravar", id: "botao-gravar", aria: { label: "Gravar e transcrever a audiência" }, disabled: true });
    const gravar = async () => {
      if (botaoGravar.disabled) return;
      const d = cnj.digitos(campoProcesso.value);
      if (!(d.length === 20 && cnj.valido(d))) { campoProcesso.focus(); return; }
      if (testando) await pararTeste();
      const participantesMapa = {};
      r.participantes.forEach((n, i) => { if (n.trim()) participantesMapa["F" + (i + 1)] = n.trim(); });
      const primeiro = Object.values(participantesMapa)[0] || "";
      botaoGravar.disabled = true;
      try {
        await api.transcricao.iniciar({
          processo: cnj.mascarar(d), dispositivo: valorDispositivo(), sigiloso: !!sigilo.checked,
          tipo: campoTipo.value, participantes: participantesMapa, falante: primeiro,
        });
      } catch (erro) {
        botaoGravar.disabled = false;
        folha.erro(erro, "A gravação não começou");
        return;
      }
      r.documento = null;
      r.falas = [];
      r.falante = primeiro;
      r.processo = cnj.mascarar(d);
      r.tipo = campoTipo.value;
      r.sigiloso = !!sigilo.checked;
      irParaAoVivo({ segundos: 0, estado: "iniciando", texto_estado: "Preparando a gravação…", falas: [], falante: primeiro });
    };
    botaoGravar.addEventListener("click", gravar);
    const teclaGravar = (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter" && !document.querySelector(".folha-fundo")) { ev.preventDefault(); gravar(); }
    };
    document.addEventListener("keydown", teclaGravar);
    ctx.aoSair(() => document.removeEventListener("keydown", teclaGravar));

    // --- modelo
    const estadoModelo = el("div", { classe: "estado-linha", estilo: { justifyContent: "center" } }, el("span", { classe: "girando" }), "Conferindo o modelo de transcrição…");
    const carregarModelo = async () => {
      let modelos = [];
      try { modelos = await api.transcricao.modelos(); } catch (_e) { modelos = []; }
      if (!ctx.vivo) return;
      const nome = H.app.valorConfig("transcricao", "modelo_ao_vivo", "small");
      const m = modelos.find((x) => x.nome === nome) || modelos.find((x) => x.embutido) || null;
      if (!m) { trocar(estadoModelo); return; }
      if (m.instalado || m.embutido) {
        trocar(estadoModelo, el("span", { classe: "ponto ponto-verde" }), `Modelo ${m.rotulo || m.nome} pronto`);
        estadoModelo.title = "A transcrição funciona sem internet, no próprio computador.";
      } else {
        trocar(estadoModelo, el("span", { classe: "ponto ponto-ambar" }), `Modelo ${m.rotulo || m.nome} ainda não baixado (${fmt.mb(m.tamanho_mb)})`,
          botao({ rotulo: "Baixar", tipo: "texto", tamanho: "pequeno", acao: async () => {
            await api.transcricao.baixarModelo(m.nome);
            aviso({ titulo: "Baixando o modelo", mensagem: "Acompanhe na barra lateral. A gravação pode começar mesmo antes: o áudio fica guardado.", tipo: "info" });
          } }));
      }
    };

    const formulario = cartao({ classe: "nova-audiencia" },
      cabecalhoCartao("Nova audiência", "microfone"),
      el("div", { classe: "formulario" },
        el("div", {},
          el("div", { classe: "linha-campos" },
            el("div", {}, el("label", { classe: "rotulo", for: "processo-audiencia", texto: "Número do processo" }), campoProcesso, ajudaProcesso),
            el("div", {}, el("label", { classe: "rotulo", for: "tipo-audiencia", texto: "Tipo de audiência" }), campoTipo)),
          sugestoes),
        el("label", { classe: "linha-sigilo", for: "sigilo-audiencia" },
          icone("cadeado"),
          el("span", { classe: "linha-texto" },
            el("span", { classe: "linha-titulo", texto: "Segredo de justiça" }),
            el("span", { classe: "linha-sub", texto: "A transcrição e a gravação ficam na pasta dos sigilosos, fora do acervo da IA." })),
          sigilo),
        el("div", {},
          el("label", { classe: "rotulo", for: "microfone", texto: "Microfone" }),
          el("div", { classe: "microfone-linha" }, campoMic, botaoTestar),
          el("div", { classe: "medidor-caixa" }, medidor, legendaMedidor)),
        el("div", {},
          el("span", { classe: "rotulo", texto: "Participantes — teclas F1 a F8 durante a audiência" }),
          participantes)));

    const areaGravar = cartao({ classe: "gravar-cartao" },
      el("div", { classe: "gravar-area" },
        botaoGravar,
        el("p", { classe: "gravar-rotulo", texto: "Gravar" }),
        el("p", { classe: "gravar-dica", texto: "Ou tecle Ctrl+Enter. O texto aparece poucos segundos depois de cada fala." }),
        estadoModelo));

    // --- lateral: gravação, recuperar, recentes
    const tarefaArquivo = el("div");
    const recuperar = el("div");
    const recentes = el("div", {}, H.ui.esqueleto(3));

    const transcreverGravacao = async () => {
      const escolha = await api.escolherArquivo({ titulo: "Escolha a gravação da audiência", tipos: TIPOS_GRAVACAO, aceitar: ACEITAR_GRAVACAO });
      if (!escolha) return;
      const doNome = String(escolha.nome || "").match(/\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}/);
      const campo = el("input", { classe: "campo numero", id: "processo-gravacao", placeholder: "0000000-00.0000.0.00.0000", inputmode: "numeric" });
      campo.value = doNome ? cnj.mascarar(doNome[0]) : cnj.mascarar(campoProcesso.value);
      const ajuda = el("p", { classe: "ajuda-campo" });
      campo.addEventListener("input", () => { campo.value = cnj.mascarar(campo.value); ajuda.textContent = ""; campo.classList.remove("invalido"); });
      const sig = interruptor({ marcado: !!sigilo.checked, rotulo: "Segredo de justiça" });
      const f = folha.abrir({
        titulo: "Transcrever a gravação", icone: "ondas",
        mensagem: `Arquivo: ${escolha.nome}. A transcrição usa o modelo preciso, roda no computador e pode levar alguns minutos; acompanhe na barra lateral.`,
        conteudo: [
          el("div", {}, el("label", { classe: "rotulo", for: "processo-gravacao", texto: "Número do processo" }), campo, ajuda),
          el("div", { classe: "grupo-lista", estilo: { boxShadow: "none" } },
            H.ui.linha({ icone: "cadeado", cor: "navy", titulo: "Segredo de justiça", sub: "O documento vai para a pasta dos sigilosos.", acessorio: sig })),
        ],
        botoes: [
          { rotulo: "Cancelar" },
          { rotulo: "Transcrever", tipo: "primario", padrao: true, acao: async () => {
            const d = cnj.digitos(campo.value);
            if (!(d.length === 20 && cnj.valido(d))) {
              ajuda.textContent = "Informe um número de processo válido: ele dá nome ao documento.";
              ajuda.classList.add("erro");
              campo.classList.add("invalido");
              campo.focus();
              return false;
            }
            const resposta = await api.transcricao.gravacao(escolha, { processo: cnj.mascarar(d), sigiloso: !!sig.checked, tipo: campoTipo.value });
            mostrarTarefaArquivo(resposta.tarefa);
            return true;
          } },
        ],
      });
      return f.resultado;
    };

    function mostrarTarefaArquivo(id) {
      const anel = H.ui.anel({ tamanho: 40, espessura: 4 });
      const titulo = el("span", { classe: "acao-item-titulo" });
      const status = el("span", { classe: "acao-item-sub" });
      const caixa = cartao({ classe: "tarefa-arquivo" }, el("div", { classe: "monitor-linha" }, anel, el("div", { classe: "linha-texto" }, titulo, status)));
      const atualizar = () => {
        const t = H.loja.tarefas.get(id);
        if (!t) return;
        const p = t.progresso || {};
        anel.definir(t.estado === "rodando" ? (typeof p.percentual === "number" ? p.percentual : null) : 100, t.estado === "falhou" ? "falhou" : t.estado === "concluida" ? "concluida" : null);
        titulo.textContent = t.titulo || "Transcrever a gravação";
        status.textContent = t.estado === "falhou" ? (t.erro || "Não deu certo.") : (t.status || "");
        if (t.estado === "concluida" && t.resultado && t.resultado.documento && !caixa.querySelector(".botao")) {
          caixa.querySelector(".monitor-linha").appendChild(botao({ rotulo: "Abrir", tipo: "tonal", tamanho: "pequeno", acao: () => api.abrir("arquivo", t.resultado.documento) }));
          carregarRecentes();
        }
      };
      ctx.on("tarefa", (t) => { if (t.id === id) atualizar(); });
      trocar(tarefaArquivo, caixa);
      atualizar();
    }

    const carregarRecuperaveis = async () => {
      let lista = [];
      try { lista = await api.transcricao.recuperaveis(); } catch (_e) { lista = []; }
      if (!ctx.vivo) return;
      if (!lista.length) { trocar(recuperar); return; }
      trocar(recuperar, faixa({
        tipo: "aviso", icone: "recuperar",
        titulo: lista.length === 1 ? "Uma transcrição foi interrompida" : `${lista.length} transcrições foram interrompidas`,
        texto: el("div", {},
          el("span", { texto: "O computador desligou ou o programa fechou no meio. O que já tinha sido transcrito pode ser recuperado." }),
          el("div", { classe: "lista-simples", estilo: { marginTop: "6px" } }, lista.map((x) => el("div", { classe: "item-simples", estilo: { padding: "6px 0" } },
            el("span", { classe: "item-texto" },
              el("span", { classe: "item-titulo numero", texto: x.processo || x.arquivo }),
              el("span", { classe: "item-sub", texto: "Interrompida " + fmt.quando(x.quando) })),
            botao({ rotulo: "Recuperar", tipo: "tonal", tamanho: "pequeno", acao: async () => {
              const r2 = await api.transcricao.recuperar(x.arquivo);
              aviso({ titulo: "Transcrição recuperada", mensagem: r2.documento, tipo: "sucesso", acoes: [{ rotulo: "Abrir documento", acao: () => api.abrir("arquivo", r2.documento) }] });
              carregarRecuperaveis();
              carregarRecentes();
            } }))))),
      }));
    };

    const carregarRecentes = async () => {
      let lista = [];
      try { lista = await api.transcricao.recentes(); } catch (_e) { lista = []; }
      if (!ctx.vivo) return;
      const caixa = cartao({ classe: "transcricoes-recentes" }, cabecalhoCartao("Transcrições recentes", "documento"));
      if (!lista.length) {
        caixa.appendChild(vazio({ compacto: true, icone: "documento", titulo: "Nenhuma ainda", texto: "As audiências transcritas aparecem aqui." }));
      } else {
        caixa.appendChild(el("div", { classe: "lista-simples" }, lista.slice(0, 6).map((t) =>
          el("button", { type: "button", classe: "item-simples", on: { click: () => api.abrir("arquivo", t.arquivo).catch((e) => folha.erro(e)) }, aria: { label: `Abrir a transcrição de ${t.numero}` } },
            blocoIcone(t.sigiloso ? "cadeado" : "documento", t.sigiloso ? "navy" : "azul"),
            el("span", { classe: "item-texto" },
              el("span", { classe: "item-titulo numero", texto: t.numero }),
              el("span", { classe: "item-sub", texto: (t.sigiloso ? "Segredo de justiça · " : "") + fmt.quando(t.quando) })),
            icone("chevron-direita", { classe: "linha-chevron" })))));
      }
      trocar(recentes, caixa);
    };

    const lateral = el("div", { classe: "coluna" },
      areaGravar,
      cartao({ classe: "mais-opcoes" },
        el("div", { classe: "acao-lista" },
          el("button", { type: "button", classe: "acao-item", id: "transcrever-gravacao", on: { click: () => transcreverGravacao().catch((e) => folha.erro(e)) } },
            blocoIcone("ondas", "ciano"),
            el("span", { classe: "linha-texto" },
              el("span", { classe: "acao-item-titulo", texto: "Transcrever uma gravação" }),
              el("span", { classe: "acao-item-sub", texto: "A mídia baixada do processo ou um arquivo de áudio ou vídeo." }))))),
      tarefaArquivo, recuperar, recentes);

    // Tarefa de gravação já rodando (veio de antes): mostra o andamento.
    const emCurso = Array.from(H.loja.tarefas.values()).find((t) => t.tipo === "transcricao_arquivo" && t.estado === "rodando");
    if (emCurso) mostrarTarefaArquivo(emCurso.id);

    validar();
    const pronto = Promise.all([carregarSugestoes(), carregarMicrofones(), carregarModelo(), carregarRecuperaveis(), carregarRecentes()]);
    return { conteudo: el("div", { classe: "audiencia-grade" }, el("div", { classe: "coluna" }, formulario), lateral), pronto };
  }

  // ===================================================================== ao vivo
  function telaAoVivo(ctx, inicial, aoTerminar, aoFalhar) {
    const r = rascunho();
    const participantes = (r.participantes || participantesDaConfig()).map((n) => n.trim());
    const corDe = corDoFalante;

    // --- relógio local, acertado pelo servidor
    let base = Number(inicial.segundos) || 0;
    let desde = performance.now();
    let rodando = false;
    const segundos = () => base + (rodando ? (performance.now() - desde) / 1000 : 0);
    const cronometro = el("span", { classe: "cronometro", role: "timer", aria: { label: "Tempo de gravação" }, texto: fmt.duracao(base) });
    const selo = el("span", { classe: "selo-gravando", "aria-live": "polite" });
    const medidor = H.ui.medidor(14);
    const statusLinha = el("span", { classe: "ajuda-campo", estilo: { margin: "0" } });

    /**
     * Estado da sessão. Chega do servidor como {texto, estado} — 'estado' é o
     * interno (iniciando, gravando, pausada, encerrando, encerrada, erro) e
     * 'texto' a frase do motor ("Carregando o modelo small...", "Revisão: 40%").
     * Também aceita só a frase (versões antigas do evento).
     */
    function definirEstado(info) {
      const texto = typeof info === "string" ? info : String((info && info.texto) || "");
      const interno = typeof info === "string" ? "" : String((info && info.estado) || "");
      const t = H.normalizar(texto);
      const e = H.normalizar(interno);
      const agora = segundos();
      if (e === "erro") {
        // A sessão acabou com erro (não começou, ou não conseguiu salvar):
        // volta à preparação com o motivo, em vez de um cronômetro andando.
        rodando = false;
        if (!terminou && aoFalhar) { terminou = true; aoFalhar(texto, (info && info.fase) || "", r.falas.length); }
        return;
      }
      if (e === "pausada" || t.startsWith("pausad")) {
        base = agora; rodando = false;
        selo.className = "selo-gravando pausado";
        selo.textContent = "Pausado";
        botaoPausar.replaceChildren(icone("tocar"), el("span", { texto: "Retomar" }));
        botaoPausar.setAttribute("aria-label", "Retomar a gravação");
        medidor.definir(0);
        statusLinha.textContent = "";
      } else if (t.startsWith("revis")) {
        base = agora; rodando = false;
        selo.className = "selo-gravando concluindo";
        selo.textContent = "Revisando";
        statusLinha.textContent = texto;
      } else if (e === "encerrando" || (t.startsWith("conclu") && t !== "concluido")) {
        base = agora; rodando = false;
        selo.className = "selo-gravando concluindo";
        selo.textContent = "Concluindo";
        statusLinha.textContent = texto || "Concluindo a transcrição…";
        botaoPausar.disabled = true;
        botaoEncerrar.disabled = true;
      } else if (e === "encerrada" || e === "parada" || t === "concluido") {
        rodando = false;
      } else if (e === "iniciando" || t.startsWith("carregando") || t.startsWith("preparando")) {
        // O áudio já está sendo gravado enquanto o modelo carrega.
        if (!rodando) { base = agora; desde = performance.now(); rodando = true; }
        selo.className = "selo-gravando";
        selo.textContent = "Gravando";
        statusLinha.textContent = "Preparando a transcrição… o áudio já está sendo gravado.";
      } else if (e === "gravando" || t.startsWith("gravando")) {
        if (!rodando) { base = agora; desde = performance.now(); rodando = true; }
        selo.className = "selo-gravando";
        selo.textContent = "Gravando";
        botaoPausar.replaceChildren(icone("pausa"), el("span", { texto: "Pausar" }));
        botaoPausar.setAttribute("aria-label", "Pausar a gravação");
        statusLinha.textContent = "";
      }
    }

    ctx.cada(250, () => { cronometro.textContent = fmt.duracao(segundos()); });
    // De tempos em tempos, o relógio do servidor manda (pausas, atrasos da janela).
    const conferirServidor = async () => {
      try {
        const e = await api.transcricao.estado();
        if (!ctx.vivo) return;
        if (e && e.estado === "erro") {
          // O erro pode ter chegado antes de esta tela se inscrever nos eventos.
          definirEstado({ estado: "erro", texto: e.erro || e.texto_estado || "", fase: (e.falas || []).length ? "fim" : "inicio" });
          return;
        }
        if (e && e.sessao && typeof e.segundos === "number") { base = e.segundos; desde = performance.now(); }
      } catch (_e) { /* fica o local */ }
    };
    ctx.cada(15000, conferirServidor);
    setTimeout(() => { if (ctx.vivo) conferirServidor(); }, 1500);

    // --- botões
    const botaoPausar = botao({ rotulo: "Pausar", icone: "pausa", tamanho: "grande", acao: async () => {
      if (selo.textContent === "Pausado") await api.transcricao.retomar(); else await api.transcricao.pausar();
    } });
    botaoPausar.id = "botao-pausar";
    const botaoEncerrar = botao({ rotulo: "Encerrar", icone: "parar", tipo: "perigo", tamanho: "grande", acao: () => encerrar() });
    botaoEncerrar.id = "botao-encerrar";

    // --- falantes
    let falanteAtual = r.falante || participantes.find(Boolean) || "";
    const botoesFalantes = [];
    const barraFalantes = el("div", { classe: "falantes", role: "group", aria: { label: "Quem está falando (F1 a F8)" } });
    participantes.forEach((nome, i) => {
      if (!nome) return;
      const b = el("button", {
        type: "button", classe: "falante", aria: { pressed: String(nome === falanteAtual), keyshortcuts: "F" + (i + 1) },
        estilo: { "--cor-falante": CORES[i] }, title: `${nome} (F${i + 1})`,
      }, el("span", { classe: "tecla", texto: "F" + (i + 1) }), el("span", { texto: nome }));
      b.addEventListener("click", () => trocarFalante(nome));
      b.dataset.nome = nome;
      botoesFalantes.push(b);
      barraFalantes.appendChild(b);
    });
    async function trocarFalante(nome) {
      if (!nome) return;
      falanteAtual = nome;
      r.falante = nome;
      for (const b of botoesFalantes) b.setAttribute("aria-pressed", String(b.dataset.nome === nome));
      try { await api.transcricao.falante(nome); } catch (erro) { folha.erro(erro); }
    }
    const teclas = (ev) => {
      if (document.querySelector(".folha-fundo")) return;
      const m = /^F([1-8])$/.exec(ev.key);
      if (m) {
        ev.preventDefault();
        trocarFalante(participantes[Number(m[1]) - 1]);
      } else if (ev.key === "F5" || ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "r")) {
        // Recarregar a página no meio da audiência só assusta: a gravação segue no servidor.
        ev.preventDefault();
      }
    };
    document.addEventListener("keydown", teclas, true);
    ctx.aoSair(() => document.removeEventListener("keydown", teclas, true));

    // --- texto ao vivo
    const rolagem = el("div", { classe: "texto-ao-vivo-rolagem", role: "log", aria: { label: "Texto da audiência", live: "polite" }, tabindex: "0" });
    const ouvindo = el("div", { classe: "ouvindo" }, el("span", { classe: "ouvindo-pontos", "aria-hidden": "true" }, el("i"), el("i"), el("i")), "Ouvindo…");
    const irAoFim = botao({ rotulo: "Ir para o fim", icone: "chevron-baixo", tipo: "primario", tamanho: "pequeno", classe: "ir-ao-fim" });
    irAoFim.hidden = true;
    irAoFim.addEventListener("click", () => { rolagem.scrollTop = rolagem.scrollHeight; irAoFim.hidden = true; });
    const vazioTexto = el("div", { classe: "vazio compacto", estilo: { paddingTop: "40px" } },
      el("div", { classe: "vazio-icone" }, icone("ondas")),
      el("p", { classe: "vazio-titulo", texto: "O texto aparece aqui" }),
      el("p", { classe: "vazio-texto", texto: "Poucos segundos depois de cada fala. Use F1 a F8 para indicar quem está falando." }));
    rolagem.append(vazioTexto, ouvindo);
    let ultimoFalante = null;

    function noFim() {
      return rolagem.scrollHeight - rolagem.scrollTop - rolagem.clientHeight < 90;
    }
    rolagem.addEventListener("scroll", () => { if (noFim()) irAoFim.hidden = true; });

    function adicionarFala(f, animar = true) {
      if (vazioTexto.isConnected) vazioTexto.remove();
      const estavaNoFim = noFim();
      const mesmo = f.falante && f.falante === ultimoFalante;
      ultimoFalante = f.falante;
      const no = el("div", { classe: "fala", estilo: { "--cor-falante": corDe(f.falante || "") } },
        el("span", { classe: "fala-tempo", texto: fmt.duracao(f.inicio) }),
        el("div", {},
          f.falante && !mesmo ? el("span", { classe: "fala-falante", texto: f.falante }) : null,
          el("p", { classe: "fala-texto", texto: f.texto })));
      if (!animar) no.style.animation = "none";
      if (mesmo) no.style.borderTop = "0";
      if (mesmo) no.style.paddingTop = "2px";
      rolagem.insertBefore(no, ouvindo);
      if (estavaNoFim) rolagem.scrollTop = rolagem.scrollHeight;
      else irAoFim.hidden = false;
    }
    (inicial.falas || []).forEach((f) => adicionarFala(f, false));
    r.falas = (inicial.falas || []).slice();

    // --- eventos da sessão
    const salvoEm = el("span");
    const atrasoChip = el("span");
    let terminou = false;
    ctx.on("transcricao", (ev) => {
      const d = ev.dados;
      switch (ev.tipo) {
        case "estado": definirEstado(d); break;
        case "nivel": if (rodando) medidor.definir(typeof d === "number" ? d : d && d.nivel); break;
        case "fala": if (d) { r.falas.push(d); adicionarFala(d); } break;
        case "atraso": {
          const s = typeof d === "number" ? d : Number(d && d.segundos) || 0;
          trocar(atrasoChip, s >= 6 ? pilula(`Atraso de ${Math.round(s)} s`, "ambar", "relogio") : null);
          break;
        }
        case "aviso": aviso({ titulo: "Transcrição", mensagem: textoDe(d), tipo: "alerta" }); break;
        case "erro": aviso({ titulo: "Problema na transcrição", mensagem: textoDe(d), tipo: "erro", duracao: 15000 }); break;
        case "salvo": salvoEm.textContent = "Salvo automaticamente às " + fmt.hora(new Date()); break;
        case "fim": if (!terminou) { terminou = true; aoTerminar(typeof d === "string" ? d : d && (d.documento || d.arquivo || d.caminho)); } break;
        default: break;
      }
    });

    async function encerrar() {
      const ok = await folha.confirmar({
        titulo: "Encerrar a audiência?", icone: "parar", perigo: true,
        mensagem: "A gravação para e o documento é salvo com tudo o que foi transcrito. O que ainda estiver na fila é transcrito antes de salvar.",
        confirmar: "Encerrar e salvar",
      });
      if (!ok) return;
      definirEstado("Concluindo a transcrição…");
      botaoPausar.disabled = true;
      botaoEncerrar.disabled = true;
      try {
        const resposta = await api.transcricao.encerrar();
        // Num computador lento o encerramento demora: sem o documento na
        // resposta, ele chega pelo evento 'fim'.
        if (!terminou && resposta && resposta.documento) { terminou = true; aoTerminar(resposta.documento); }
      } catch (erro) {
        botaoPausar.disabled = false;
        botaoEncerrar.disabled = false;
        folha.erro(erro, "Não consegui encerrar");
      }
    }

    const sub = el("span", { classe: "ao-vivo-sub" },
      r.tipo ? el("span", { texto: r.tipo }) : null,
      r.sigiloso ? pilula("Segredo de justiça", "navy", "cadeado") : null,
      atrasoChip);
    const topo = cartao({ classe: "ao-vivo-topo" },
      selo, cronometro,
      el("div", { classe: "ao-vivo-info" }, el("span", { classe: "ao-vivo-processo", texto: inicial.processo || r.processo }), sub),
      medidor,
      el("div", { classe: "grupo-botoes" }, botaoPausar, botaoEncerrar));
    const texto = cartao({ classe: "texto-ao-vivo" }, rolagem, irAoFim);
    const rodape = el("div", { classe: "ao-vivo-barra" },
      el("span", { classe: "ajuda-campo", estilo: { margin: "0" } }, salvoEm), statusLinha);

    definirEstado(inicial.estado !== undefined || inicial.texto_estado !== undefined
      ? { estado: inicial.estado, texto: inicial.texto_estado || "" } : "Gravando");
    if (inicial.falante) {
      falanteAtual = inicial.falante;
      for (const b of botoesFalantes) b.setAttribute("aria-pressed", String(b.dataset.nome === falanteAtual));
    }
    return { conteudo: el("div", { classe: "ao-vivo" }, topo, barraFalantes, texto, rodape) };
  }

  /** A mesma cor do falante na gravação e no texto final. */
  function corDoFalante(nome) {
    const participantes = ((H.loja.audiencia && H.loja.audiencia.participantes) || participantesDaConfig()).map((n) => n.trim());
    const i = participantes.indexOf(nome);
    return CORES[i >= 0 ? i : (Math.abs(hash(nome || "")) % CORES.length)];
  }

  function textoDe(d) {
    if (typeof d === "string") return d;
    return String((d && (d.texto || d.mensagem || d.valor)) || "");
  }

  function hash(s) {
    let h = 0;
    for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) | 0;
    return h;
  }

  // ===================================================================== documento pronto
  function telaDocumento(ctx, documento, novaAudiencia) {
    const r = rascunho();
    const nome = String(documento || "").split(/[\\/]/).pop();
    const pasta = String(documento || "").replace(/[\\/][^\\/]*$/, "");
    const resultado = cartao({ classe: "documento-pronto-cartao" },
      el("div", { classe: "documento-pronto" },
        blocoIcone("check", "verde"),
        el("div", { classe: "linha-texto" },
          el("h2", { classe: "andamento-titulo", texto: "Transcrição salva" }),
          el("p", { classe: "andamento-status numero", texto: nome || "Documento do Word" }),
          r.sigiloso ? el("p", { classe: "ajuda-campo" }, icone("cadeado", { tamanho: 14 }), " Na pasta dos sigilosos, fora do acervo da IA.") : null),
        el("div", { classe: "grupo-botoes" },
          botao({ rotulo: "Abrir documento", icone: "documento", tipo: "primario", acao: () => api.abrir("arquivo", documento) }),
          pasta ? botao({ rotulo: "Abrir pasta", icone: "pasta", acao: () => api.abrir("pasta", pasta) }) : null,
          botao({ rotulo: "Nova audiência", icone: "mais", tipo: "tonal", acao: novaAudiencia }))));
    // Revisão: refaz o texto com o modelo preciso, a partir da gravação e
    // dos falantes marcados ao vivo (POST /api/transcricao/gravacao {revisao}).
    const estadoRevisao = el("span", { classe: "acao-item-sub", "aria-live": "polite", texto: "Refaz o texto com o modelo preciso, a partir da gravação e dos falantes marcados. Leva alguns minutos." });
    const anelRevisao = H.ui.anel({ tamanho: 30, espessura: 4 });
    anelRevisao.hidden = true;
    let tarefaRevisao = null;
    const botaoRevisar = botao({ rotulo: "Revisar", icone: "brilho", tipo: "tonal", tamanho: "pequeno", acao: async () => {
      const resposta = await api.transcricao.gravacao({}, { revisao: true });
      tarefaRevisao = resposta.tarefa;
      botaoRevisar.hidden = true;
      anelRevisao.hidden = false;
      anelRevisao.definir(null);
      estadoRevisao.textContent = "Revisando… acompanhe aqui ou na barra lateral.";
    } });
    botaoRevisar.id = "botao-revisar";
    ctx.on("tarefa", (t) => {
      if (t.id !== tarefaRevisao) return;
      const p = t.progresso || {};
      anelRevisao.definir(t.estado === "rodando" ? (typeof p.percentual === "number" ? p.percentual : null) : 100, t.estado === "falhou" ? "falhou" : t.estado === "concluida" ? "concluida" : null);
      estadoRevisao.textContent = t.estado === "falhou" ? (t.erro || "A revisão não deu certo.") : (t.status || "");
      if (t.estado === "concluida" && t.resultado && t.resultado.documento) {
        botaoRevisar.replaceWith(botao({ rotulo: "Abrir a revisão", icone: "documento", tipo: "tonal", tamanho: "pequeno", acao: () => api.abrir("arquivo", t.resultado.documento) }));
      }
    });
    const revisar = cartao({ classe: "revisar-cartao" },
      el("div", { classe: "monitor-linha" },
        blocoIcone("brilho", "indigo"),
        el("div", { classe: "linha-texto" }, el("span", { classe: "acao-item-titulo", texto: "Revisar com o modelo preciso" }), estadoRevisao),
        anelRevisao, botaoRevisar));

    const falas = r.falas || [];
    const texto = falas.length ? cartao({ classe: "texto-final" },
      cabecalhoCartao("Texto da audiência", "texto", el("span", { classe: "progresso-passos", texto: fmt.plural(falas.length, "fala", "falas") })),
      el("div", {}, falas.map((f) => el("div", { classe: "fala", estilo: { animation: "none", "--cor-falante": corDoFalante(f.falante) } },
        el("span", { classe: "fala-tempo", texto: fmt.duracao(f.inicio) }),
        el("div", {}, f.falante ? el("span", { classe: "fala-falante", texto: f.falante }) : null, el("p", { classe: "fala-texto", texto: f.texto })))))) : null;
    return { conteudo: el("div", { classe: "formulario", estilo: { gap: "16px" } }, resultado, revisar, faixa({ tipo: "sigilo", icone: "info", texto: "A transcrição é automática: confira o texto antes de usá-lo em qualquer ato. A gravação fica guardada ao lado do documento, na pasta _audio." }), texto) };
  }

  // ===================================================================== tela
  H.secoes = H.secoes || {};
  H.secoes.audiencias = {
    async montar(ctx) {
      const raiz = ctx.raiz;
      const r = rascunho();
      try { await H.app.carregarConfig(); } catch (_e) { /* usa os padrões */ }
      const cab = H.ui.cabecalho({
        titulo: "Audiências",
        subtitulo: "Transcrição simultânea, no próprio computador. O áudio não sai da máquina.",
      });
      const zona = el("div");
      raiz.append(cab, zona);

      let telaCtx = null;
      const mostrar = (fn) => {
        if (telaCtx) telaCtx.limpar();
        telaCtx = H.contextoFilho(ctx);
        telaCtx.rota = ctx.rota;
        telaCtx.cada = (ms, f) => { const id = setInterval(() => { if (telaCtx && telaCtx.vivo) f(); }, ms); telaCtx.aoSair(() => clearInterval(id)); return id; };
        const tela = fn(telaCtx);
        trocar(zona, tela.conteudo);
        return tela.pronto;
      };
      ctx.aoSair(() => telaCtx && telaCtx.limpar());

      const preparo = () => mostrar((c) => telaPreparo(c, aoVivo));
      const aoVivo = (inicial) => {
        cab.subtitulo.textContent = "Audiência em gravação. F1 a F8 indicam quem está falando.";
        H.loja.gravando = true;
        return mostrar((c) => telaAoVivo(c, inicial, documento, falhou));
      };
      const falhou = (motivo, fase, falas) => {
        H.loja.gravando = false;
        cab.subtitulo.textContent = "Transcrição simultânea, no próprio computador. O áudio não sai da máquina.";
        preparo();
        const comeco = fase === "inicio" || !falas;
        folha.informar({
          titulo: comeco ? "A gravação não começou" : "A audiência foi interrompida",
          icone: "aviso",
          mensagem: motivo || "O microfone não respondeu.",
          conteudo: comeco ? null : el("p", { classe: "ajuda-campo", texto: "O áudio gravado até aqui foi guardado: use “Recuperar sessão interrompida” para gerar o documento." }),
        });
      };
      const documento = (caminho) => {
        r.documento = caminho;
        H.loja.gravando = false;
        cab.subtitulo.textContent = "Transcrição concluída.";
        mostrar((c) => telaDocumento(c, caminho, () => {
          r.documentoVisto = caminho;
          r.documento = null;
          r.falas = [];
          cab.subtitulo.textContent = "Transcrição simultânea, no próprio computador. O áudio não sai da máquina.";
          preparo();
        }));
      };

      let estado = null;
      try { estado = await api.transcricao.estado(); } catch (_e) { estado = null; }
      if (!ctx.vivo) return;
      const situacao = H.normalizar(estado && estado.estado);
      const ativa = estado && estado.sessao && !/^(conclu|encerrad|parad|erro)/.test(situacao);
      // Audiência encerrada enquanto esta tela estava fechada: mostra o documento.
      const terminada = estado && situacao === "encerrada" && estado.documento && estado.documento !== r.documentoVisto ? estado.documento : null;
      if (ativa) {
        r.processo = estado.processo || r.processo;
        if (typeof estado.sigiloso === "boolean") r.sigiloso = estado.sigiloso;
        if (estado.falas && estado.falas.length) r.falas = estado.falas.slice();
        await aoVivo(estado);
      } else if ((r.documento || terminada) && !ctx.rota.params.get("processo")) {
        if (terminada && !r.documento && estado.falas) r.falas = estado.falas.slice();
        documento(r.documento || terminada);
      } else {
        await preparo();
      }
    },
  };
})();
