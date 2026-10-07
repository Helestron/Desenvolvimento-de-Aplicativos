/* Helestron — cliente da API local (especificação, seção 6).
 *
 * A interface conversa SÓ por aqui com o programa. Cada endpoint aparece uma
 * única vez, na tabela ROTAS, escrito exatamente como na especificação
 * ("MÉTODO /api/caminho/{parametro}"): o teste test_web_interface confere que
 * esta tabela só usa endpoints que existem no contrato, e as telas nunca
 * montam um caminho de API por conta própria.
 *
 * Segurança (6.1): o token vem na URL (?t=), vai para o sessionStorage e sai
 * da barra de endereço; segue em todo pedido no cabeçalho X-Helestron-Token
 * e, no EventSource (que não manda cabeçalho), em ?t=.
 *
 * Envelope (6.2): {ok: true, dados} ou {ok: false, erro: {codigo, mensagem,
 * detalhe}}. Erro vira ErroApi, com a 'mensagem' pronta para o usuário.
 *
 * Modo demonstração (?demo=1): o demo.js se registra em Helestron.demo e
 * responde no lugar do servidor; o resto da interface nem fica sabendo.
 */
(function () {
  "use strict";

  const H = (window.Helestron = window.Helestron || {});

  // ------------------------------------------------------------- rotas
  // Nome interno → "MÉTODO /api/caminho". Parâmetros entre chaves.
  const ROTAS = {
    // geral
    estado: "GET /api/estado",
    configLer: "GET /api/config",
    configGravar: "POST /api/config",
    tribunais: "GET /api/tribunais",
    acessosListar: "GET /api/acessos",
    acessosGravar: "POST /api/acessos",
    acessosApagar: "DELETE /api/acessos/{portal}",
    enderecosCorrigidos: "GET /api/tribunais/enderecos",
    enderecosDoPortal: "GET /api/tribunais/enderecos/{portal}",
    enderecoCorrigir: "POST /api/tribunais/enderecos",
    acessosTestar: "POST /api/acessos/testar",
    dialogoArquivo: "POST /api/dialogo/arquivo",
    dialogoPasta: "POST /api/dialogo/pasta",
    abrir: "POST /api/abrir",
    verificacao: "GET /api/verificacao",
    verificacaoCompleta: "POST /api/verificacao/completa",
    encerrar: "POST /api/encerrar",
    // tarefas e perguntas
    tarefasListar: "GET /api/tarefas",
    tarefaObter: "GET /api/tarefas/{id}",
    tarefaParar: "POST /api/tarefas/{id}/parar",
    perguntaResponder: "POST /api/perguntas/{id}/responder",
    perguntaCancelar: "POST /api/perguntas/{id}/cancelar",
    // processos (download)
    relacaoArquivo: "POST /api/relacao/arquivo",
    relacaoTexto: "POST /api/relacao/texto",
    relacaoLink: "POST /api/relacao/link",
    downloadIniciar: "POST /api/download/iniciar",
    downloadLotes: "GET /api/download/lotes",
    // audiências (transcrição)
    microfones: "GET /api/transcricao/microfones",
    microfoneTeste: "POST /api/transcricao/microfone/teste",
    microfoneParar: "POST /api/transcricao/microfone/parar",
    modelos: "GET /api/transcricao/modelos",
    modeloBaixar: "POST /api/transcricao/modelos/baixar",
    falantes: "GET /api/transcricao/falantes",
    falantesBaixar: "POST /api/transcricao/falantes/baixar",
    transcricaoIniciar: "POST /api/transcricao/iniciar",
    transcricaoPausar: "POST /api/transcricao/pausar",
    transcricaoRetomar: "POST /api/transcricao/retomar",
    transcricaoFalante: "POST /api/transcricao/falante",
    transcricaoEncerrar: "POST /api/transcricao/encerrar",
    transcricaoEstado: "GET /api/transcricao/estado",
    recuperaveis: "GET /api/transcricao/recuperaveis",
    recuperar: "POST /api/transcricao/recuperar",
    gravacao: "POST /api/transcricao/gravacao",
    transcricoesRecentes: "GET /api/transcricao/recentes",
    // pauta
    pautaListar: "GET /api/pauta",
    pautaFontes: "GET /api/pauta/fontes",
    pautaFonteSalvar: "POST /api/pauta/fontes",
    pautaFonteRemover: "DELETE /api/pauta/fontes/{id}",
    pautaSincronizar: "POST /api/pauta/sincronizar",
    pautaCapturar: "POST /api/pauta/capturar",
    pautaImportar: "POST /api/pauta/importar",
    pautaExportar: "POST /api/pauta/exportar",
    pautaAlteracoes: "GET /api/pauta/alteracoes",
    pautaAlteracoesVistas: "POST /api/pauta/alteracoes/vistas",
    pautaMonitoramento: "POST /api/pauta/monitoramento",
    pautaBaixarAutos: "POST /api/pauta/baixar-autos",
    // compartilhar com IA
    compartilharEstado: "GET /api/compartilhar/estado",
    compartilharPreparar: "POST /api/compartilhar/preparar",
    compartilharClaudeDesktop: "POST /api/compartilhar/claude-desktop",
    compartilharCowork: "POST /api/compartilhar/cowork",
    compartilharClaudeCode: "POST /api/compartilhar/claude-code",
    compartilharChatgptWork: "POST /api/compartilhar/chatgpt-work",
    compartilharCodex: "POST /api/compartilhar/codex",
    compartilharPacote: "POST /api/compartilhar/pacote",
    compartilharNuvem: "GET /api/compartilhar/nuvem",
    compartilharEspelhar: "POST /api/compartilhar/nuvem/espelhar",
    compartilharPrompt: "GET /api/compartilhar/prompt",
    // autoteste (seção 7.3)
    autotestePasso: "POST /api/autoteste/passo",
    autotesteFim: "POST /api/autoteste/fim",
  };

  // Eventos do servidor (6.4). "conexao" é nosso: avisa a interface quando o
  // canal cai ou volta (para reler o estado e mostrar a faixa "sem conexão").
  const EVENTOS = ["tarefa", "item", "log", "pergunta", "pergunta_fechada", "aviso",
    "transcricao", "microfone_nivel", "pauta", "estado", "ping"];
  const ROTA_EVENTOS = "/api/eventos";

  const CHAVE_TOKEN = "helestron.token";

  // ------------------------------------------------------------- erros
  /** Erro da API com a frase para o usuário em 'message'. */
  class ErroApi extends Error {
    constructor(codigo, mensagem, detalhe, status) {
      super(mensagem || "Algo deu errado.");
      this.name = "ErroApi";
      this.codigo = codigo || "erro";
      this.detalhe = detalhe || "";
      this.status = status || 0;
    }
  }

  // ------------------------------------------------------------- token
  const params = new URLSearchParams(location.search);
  const DEMO = params.get("demo") === "1";

  function lerToken() {
    const daUrl = params.get("t");
    let guardado = null;
    try {
      if (daUrl) sessionStorage.setItem(CHAVE_TOKEN, daUrl);
      guardado = sessionStorage.getItem(CHAVE_TOKEN);
    } catch (_e) {
      // sessionStorage bloqueado: o token fica só na memória desta página.
    }
    if (daUrl) {
      // O token não fica à vista na barra nem no histórico.
      params.delete("t");
      const resto = params.toString();
      try {
        history.replaceState(null, "", location.pathname + (resto ? "?" + resto : "") + location.hash);
      } catch (_e) { /* nada a fazer */ }
    }
    return daUrl || guardado || "";
  }
  const token = lerToken();

  // ------------------------------------------------------------- pedidos
  /** Troca {id} e {portal} pelos valores (codificados) e separa método e caminho. */
  function montar(nome, valores) {
    const rota = ROTAS[nome];
    if (!rota) throw new Error("Rota desconhecida: " + nome);
    const [metodo, modelo] = rota.split(" ");
    const caminho = modelo.replace(/\{(\w+)\}/g, (_m, chave) => {
      const v = valores && valores[chave];
      if (v === undefined || v === null || v === "") throw new Error(`Falta '${chave}' em ${rota}`);
      return encodeURIComponent(String(v));
    });
    return { metodo, caminho, rota };
  }

  function comConsulta(caminho, consulta) {
    if (!consulta) return caminho;
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(consulta)) {
      if (v !== undefined && v !== null && v !== "") q.set(k, v);
    }
    const s = q.toString();
    return s ? caminho + "?" + s : caminho;
  }

  async function lerEnvelope(resposta) {
    let corpo = null;
    try {
      corpo = await resposta.json();
    } catch (_e) {
      throw new ErroApi("resposta_invalida",
        "O Helestron respondeu de um jeito inesperado. Tente de novo; se continuar, feche e abra o programa.",
        `HTTP ${resposta.status}`, resposta.status);
    }
    if (corpo && corpo.ok === true) return corpo.dados;
    const e = (corpo && corpo.erro) || {};
    if (resposta.status === 403 && !e.mensagem) {
      throw new ErroApi("proibido",
        "A sessão desta janela expirou. Feche e abra o Helestron pelo atalho.", "", 403);
    }
    throw new ErroApi(e.codigo, e.mensagem || "Algo deu errado.", e.detalhe, resposta.status);
  }

  /**
   * Chama uma rota. 'opcoes': {params, consulta, corpo, formulario}.
   * 'corpo' vai como JSON; 'formulario' (FormData) vai como multipart.
   */
  async function chamar(nome, opcoes = {}) {
    const { metodo, caminho, rota } = montar(nome, opcoes.params);
    const url = comConsulta(caminho, opcoes.consulta);
    if (DEMO && H.demo) {
      // A demonstração recebe a rota como está na tabela (com {id}), mais os valores.
      return H.demo.responder(rota, {
        params: opcoes.params || {}, consulta: opcoes.consulta || {},
        corpo: opcoes.corpo, formulario: opcoes.formulario,
      });
    }
    const init = { method: metodo, headers: { "X-Helestron-Token": token }, cache: "no-store" };
    if (opcoes.formulario) {
      init.body = opcoes.formulario;
    } else if (opcoes.corpo !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opcoes.corpo);
    } else if (metodo === "POST") {
      init.headers["Content-Type"] = "application/json";
      init.body = "{}";
    }
    let resposta;
    try {
      resposta = await fetch(url, init);
    } catch (erro) {
      throw new ErroApi("sem_conexao",
        "Não consegui falar com o Helestron. Se a janela ficou aberta depois de o programa fechar, abra-o de novo pelo atalho.",
        String(erro), 0);
    }
    return lerEnvelope(resposta);
  }

  // ------------------------------------------------------------- eventos
  const ouvintes = new Map();   // tipo → Set(função)

  function on(tipo, fn) {
    if (!ouvintes.has(tipo)) ouvintes.set(tipo, new Set());
    ouvintes.get(tipo).add(fn);
    return () => ouvintes.get(tipo) && ouvintes.get(tipo).delete(fn);
  }

  function emitir(tipo, dados) {
    const lista = ouvintes.get(tipo);
    if (!lista) return;
    for (const fn of Array.from(lista)) {
      try {
        fn(dados);
      } catch (erro) {
        // Um ouvinte com defeito não pode calar os outros.
        console.error("Erro ao tratar o evento", tipo, erro);
      }
    }
  }

  let fonte = null;
  let tentativas = 0;
  let reconectar = null;
  let vigia = null;
  let ultimoSinal = 0;
  let conectado = false;

  function marcarConexao(ok) {
    if (ok === conectado) return;
    conectado = ok;
    emitir("conexao", { conectado: ok });
  }

  /**
   * Abre o canal de eventos. O EventSource já reconecta sozinho quando a
   * rede pisca; mas, se o servidor responder com erro (403, 500), ele desiste
   * (readyState CLOSED). Aqui tentamos de novo com espera crescente (1 s, 2 s,
   * 4 s… até 15 s), e um vigia recria o canal se ficar 40 s sem nem o ping.
   */
  function conectarEventos() {
    if (DEMO && H.demo) {
      H.demo.ligarEventos(emitir);
      marcarConexao(true);
      return;
    }
    if (fonte) fonte.close();
    clearTimeout(reconectar);
    fonte = new EventSource(ROTA_EVENTOS + "?t=" + encodeURIComponent(token));
    fonte.onopen = () => {
      tentativas = 0;
      ultimoSinal = Date.now();
      marcarConexao(true);
    };
    fonte.onerror = () => {
      if (fonte && fonte.readyState === EventSource.CLOSED) {
        marcarConexao(false);
        agendarReconexao();
      } else {
        // Reconectando por conta própria; se demorar, o vigia avisa.
        setTimeout(() => {
          if (fonte && fonte.readyState !== EventSource.OPEN) marcarConexao(false);
        }, 3000);
      }
    };
    for (const tipo of EVENTOS) {
      fonte.addEventListener(tipo, (ev) => {
        ultimoSinal = Date.now();
        if (!conectado) marcarConexao(true);
        let dados = {};
        try {
          dados = ev.data ? JSON.parse(ev.data) : {};
        } catch (_e) {
          dados = { texto: ev.data };
        }
        emitir(tipo, dados);
      });
    }
    clearInterval(vigia);
    vigia = setInterval(() => {
      if (Date.now() - ultimoSinal > 40000) {
        marcarConexao(false);
        conectarEventos();
      }
    }, 10000);
  }

  function agendarReconexao() {
    clearTimeout(reconectar);
    const espera = Math.min(15000, 1000 * Math.pow(2, tentativas));
    tentativas += 1;
    reconectar = setTimeout(conectarEventos, espera);
  }

  // --------------------------------------------- escolher arquivo/pasta
  /**
   * Abre o diálogo nativo de arquivo (pywebview). Fora da janela do programa
   * (Edge, navegador) o servidor responde 'sem_dialogo' e usamos o
   * <input type=file> do próprio navegador. Devolve {caminho} ou {arquivo}
   * (File), ou null se o usuário desistir.
   */
  async function escolherArquivo({ titulo, tipos, aceitar }) {
    try {
      const r = await chamar("dialogoArquivo", { corpo: { titulo, tipos } });
      if (r && r.caminho) return { caminho: r.caminho, nome: nomeDoCaminho(r.caminho), tamanho: r.tamanho };
      return null;
    } catch (erro) {
      if (erro.codigo !== "sem_dialogo") throw erro;
    }
    const arquivo = await escolherPeloNavegador(aceitar);
    return arquivo ? { arquivo, nome: arquivo.name } : null;
  }

  function escolherPeloNavegador(aceitar) {
    return new Promise((resolver) => {
      const entrada = document.createElement("input");
      entrada.type = "file";
      if (aceitar) entrada.accept = aceitar;
      entrada.style.display = "none";
      document.body.appendChild(entrada);
      let resolvido = false;
      const fim = (valor) => {
        if (resolvido) return;
        resolvido = true;
        entrada.remove();
        resolver(valor);
      };
      entrada.addEventListener("change", () => fim(entrada.files && entrada.files[0] ? entrada.files[0] : null));
      entrada.addEventListener("cancel", () => fim(null));
      entrada.click();
    });
  }

  /** Diálogo nativo de pasta; {caminho} | null | lança ErroApi('sem_dialogo'). */
  async function escolherPasta({ titulo, inicial }) {
    const r = await chamar("dialogoPasta", { corpo: { titulo, inicial } });
    return r && r.caminho ? r.caminho : null;
  }

  function nomeDoCaminho(caminho) {
    return String(caminho).split(/[\\/]/).pop();
  }

  /**
   * Envia o que veio de escolherArquivo (ou de arrastar e soltar) para uma
   * rota que aceita multipart (campo 'arquivo') ou JSON {caminho}.
   * 'campos' são os demais dados do pedido (processo, sigiloso...).
   */
  function enviarEscolha(nome, escolha, campos = {}) {
    if (escolha.arquivo) {
      const fd = new FormData();
      fd.append("arquivo", escolha.arquivo, escolha.arquivo.name);
      for (const [k, v] of Object.entries(campos)) {
        if (v !== undefined && v !== null) fd.append(k, typeof v === "boolean" ? (v ? "true" : "false") : String(v));
      }
      return chamar(nome, { formulario: fd });
    }
    return chamar(nome, { corpo: Object.assign({ caminho: escolha.caminho }, campos) });
  }

  // ------------------------------------------------------------- fachada
  const api = {
    ErroApi,
    demo: DEMO,
    token: () => token,
    on,
    emitir,
    conectarEventos,
    conectado: () => conectado,
    escolherArquivo,
    escolherPasta,
    rotas: ROTAS,

    // geral
    estado: () => chamar("estado"),
    config: {
      ler: () => chamar("configLer"),
      gravar: (secao, chave, valor) => chamar("configGravar", { corpo: { secao, chave, valor } }),
    },
    tribunais: () => chamar("tribunais"),
    acessos: {
      listar: () => chamar("acessosListar"),
      gravar: (portal, usuario, senha, extras) =>
        chamar("acessosGravar", { corpo: Object.assign({ portal, usuario, senha }, extras || {}) }),
      apagar: (portal) => chamar("acessosApagar", { params: { portal } }),
      enderecos: () => chamar("enderecosCorrigidos"),
      enderecosDoPortal: (portal) => chamar("enderecosDoPortal", { params: { portal } }),
      corrigirEndereco: (portal, grau, url) => chamar("enderecoCorrigir", { corpo: { portal, grau, url } }),
      // O portal exato da linha (esaj ou eproc): no TJAL, no TJSP e no TJAC os
      // dois existem, e só a sigla testaria o principal (o e-SAJ).
      testar: (tribunal, sistema) => chamar("acessosTestar", { corpo: sistema ? { tribunal, sistema } : { tribunal } }),
    },
    abrir: (tipo, alvo) => chamar("abrir", { corpo: { tipo, alvo } }),
    verificacao: {
      listar: () => chamar("verificacao"),
      completa: () => chamar("verificacaoCompleta"),
    },
    encerrar: () => chamar("encerrar"),

    // tarefas e perguntas
    tarefas: {
      listar: () => chamar("tarefasListar"),
      obter: (id) => chamar("tarefaObter", { params: { id } }),
      parar: (id) => chamar("tarefaParar", { params: { id } }),
    },
    perguntas: {
      responder: (id, valor) => chamar("perguntaResponder", { params: { id }, corpo: { valor } }),
      cancelar: (id) => chamar("perguntaCancelar", { params: { id } }),
    },

    // processos
    relacao: {
      arquivo: (escolha) => enviarEscolha("relacaoArquivo", escolha),
      texto: (texto) => chamar("relacaoTexto", { corpo: { texto } }),
      link: (url) => chamar("relacaoLink", { corpo: { url } }),
    },
    download: {
      iniciar: (pedido) => chamar("downloadIniciar", { corpo: pedido }),
      lotes: () => chamar("downloadLotes"),
    },

    // audiências
    transcricao: {
      microfones: () => chamar("microfones"),
      testarMicrofone: (dispositivo) => chamar("microfoneTeste", { corpo: { dispositivo } }),
      pararMicrofone: () => chamar("microfoneParar"),
      modelos: () => chamar("modelos"),
      baixarModelo: (nome) => chamar("modeloBaixar", { corpo: { nome } }),
      falantes: () => chamar("falantes"),
      baixarFalantes: () => chamar("falantesBaixar"),
      iniciar: (pedido) => chamar("transcricaoIniciar", { corpo: pedido }),
      pausar: () => chamar("transcricaoPausar"),
      retomar: () => chamar("transcricaoRetomar"),
      falante: (falante) => chamar("transcricaoFalante", { corpo: { falante } }),
      encerrar: (pedido) => chamar("transcricaoEncerrar", { corpo: pedido || {} }),
      estado: () => chamar("transcricaoEstado"),
      recuperaveis: () => chamar("recuperaveis"),
      recuperar: (arquivo) => chamar("recuperar", { corpo: { arquivo } }),
      gravacao: (escolha, campos) => enviarEscolha("gravacao", escolha, campos),
      recentes: () => chamar("transcricoesRecentes"),
    },

    // pauta
    pauta: {
      listar: (filtros) => chamar("pautaListar", { consulta: filtros }),
      fontes: () => chamar("pautaFontes"),
      salvarFonte: (fonte) => chamar("pautaFonteSalvar", { corpo: fonte }),
      removerFonte: (id) => chamar("pautaFonteRemover", { params: { id } }),
      sincronizar: (pedido) => chamar("pautaSincronizar", { corpo: pedido || {} }),
      capturar: (tribunal, sistema) => chamar("pautaCapturar", { corpo: { tribunal, sistema } }),
      importar: (escolha) => enviarEscolha("pautaImportar", escolha),
      exportar: (pedido) => chamar("pautaExportar", { corpo: pedido }),
      alteracoes: (desde) => chamar("pautaAlteracoes", { consulta: { desde } }),
      marcarVistas: () => chamar("pautaAlteracoesVistas"),
      monitoramento: (ativo, intervalo_horas) =>
        chamar("pautaMonitoramento", { corpo: { ativo, intervalo_horas } }),
      baixarAutos: (pedido) => chamar("pautaBaixarAutos", { corpo: pedido }),
    },

    // compartilhar
    compartilhar: {
      estado: () => chamar("compartilharEstado"),
      preparar: () => chamar("compartilharPreparar"),
      claudeDesktop: () => chamar("compartilharClaudeDesktop"),
      cowork: () => chamar("compartilharCowork"),
      claudeCode: () => chamar("compartilharClaudeCode"),
      chatgptWork: () => chamar("compartilharChatgptWork"),
      codex: () => chamar("compartilharCodex"),
      pacote: (numeros) => chamar("compartilharPacote", { corpo: numeros && numeros.length ? { numeros } : {} }),
      nuvens: () => chamar("compartilharNuvem"),
      espelhar: (destino) => chamar("compartilharEspelhar", { corpo: { destino } }),
      prompt: () => chamar("compartilharPrompt"),
    },

    autoteste: {
      passo: (secao, extras) => chamar("autotestePasso", { corpo: Object.assign({ secao }, extras || {}) }),
      fim: (resultado) => chamar("autotesteFim", { corpo: resultado || {} }),
    },
  };

  H.api = api;
})();
