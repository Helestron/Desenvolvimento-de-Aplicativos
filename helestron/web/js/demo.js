/* Helestron — modo demonstração (index.html?demo=1).
 *
 * Responde a TODA a API (as mesmas rotas de api.js) com dados realistas e
 * simula os eventos do servidor — download andando processo a processo com
 * uma pergunta de código no meio, falas da audiência chegando, nível do
 * microfone, sincronização da pauta —, sem servidor nenhum.
 *
 * Serve para desenhar a interface, para as capturas de tela e para os testes
 * da interface (testes/test_web_interface.py). Os números CNJ são válidos
 * (dígito verificador calculado); nomes e processos são fictícios.
 *
 * Variações pela URL: &pauta=vazia (pauta sem nada, sem fontes),
 * &sem_dialogo=1 (sem diálogo nativo: usa o <input type=file>),
 * &lote=falhas (nenhum processo do lote é baixado),
 * &claude_code=ausente (o Claude Code não está instalado),
 * &microfone=<nome> (o microfone guardado em Ajustes, pelo nome),
 * &presenca=certificado (as fontes da pauta entram pelo certificado digital:
 *   o monitoramento não as sincroniza sozinho),
 * &sigilo=arquivos (a minuta de um processo sigiloso, aberta no Word, ficou
 *   no acervo: a pendência “sigilo-arquivos” do Início e a faixa âmbar da tela
 *   Compartilhar, que só avisa),
 * &sigilo=autos (os autos dele ficaram presos no acervo: a pendência “sigilo”
 *   e a faixa vermelha; até saírem, o compartilhamento responde 409),
 * &modo=edge|navegador (a página aberta no Edge ou no navegador padrão, sem a
 *   janela do aplicativo).
 */
(function () {
  "use strict";

  const H = (window.Helestron = window.Helestron || {});
  const params = new URLSearchParams(location.search);
  if (params.get("demo") !== "1") return;

  const PAUTA_VAZIA = params.get("pauta") === "vazia";
  const SEM_DIALOGO = params.get("sem_dialogo") === "1";
  const LOTE_FALHA = params.get("lote") === "falhas";
  const SEM_CLAUDE_CODE = params.get("claude_code") === "ausente";
  // Fontes que só entram com a pessoa à frente (ServicoPauta.motivo_presenca).
  const MOTIVO_PRESENCA = params.get("presenca") === "certificado" ? "a entrada no portal é pelo certificado digital" : "";
  const MODO_JANELA = ["edge", "navegador"].includes(params.get("modo")) ? params.get("modo") : "janela";
  // &falantes=ausentes: construção sem os modelos de voz (a tela oferece baixá-los)
  let falantesProntos = params.get("falantes") !== "ausentes";

  // ------------------------------------------------------- aleatório estável
  // Semente fixa: a mesma pauta a cada abertura (capturas comparáveis).
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const aleatorio = mulberry32(20261003);
  const escolher = (lista) => lista[Math.floor(aleatorio() * lista.length)];
  const entre = (a, b) => a + Math.floor(aleatorio() * (b - a + 1));

  // ------------------------------------------------------------ datas
  const p2 = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
  const isoHora = (d) => `${iso(d)}T${p2(d.getHours())}:${p2(d.getMinutes())}:00`;
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const dia = (n) => { const d = new Date(hoje); d.setDate(d.getDate() + n); return d; };
  const agoraMenos = (min) => new Date(Date.now() - min * 60000);

  // ------------------------------------------------------------ CNJ
  /** Número CNJ com o dígito verificador certo (módulo 97). */
  function cnj(sequencial, ano, j, tr, origem) {
    const n = String(sequencial).padStart(7, "0");
    const resto = `${ano}${j}${p2(tr)}${String(origem).padStart(4, "0")}`;
    const dv = 98n - (BigInt(n + resto + "00") % 97n);
    return `${n}-${p2(Number(dv))}.${ano}.${j}.${p2(tr)}.${String(origem).padStart(4, "0")}`;
  }

  const USUARIO = "C:\\Users\\camila.albuquerque";
  const DOCS = USUARIO + "\\Documents\\Helestron";
  const PASTAS = {
    acervo: DOCS + "\\Acervo",
    processos: DOCS + "\\Acervo\\Processos",
    transcricoes: DOCS + "\\Acervo\\Transcricoes",
    sigilosos: DOCS + "\\Sigilosos",
    pauta: DOCS + "\\Pauta",
    logs: USUARIO + "\\AppData\\Local\\Helestron\\Logs",
  };

  // ============================================================== pauta
  const TIPOS = ["Conciliação", "Instrução e julgamento", "Una", "Justificação", "Mediação", "Outra"];
  const HORAS = ["08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00"];
  const CASOS = [
    { partes: "Maria José dos Santos x Banco do Brasil S.A.", classe: "Procedimento Comum Cível" },
    { partes: "José Carlos Ferreira Lima x Equatorial Alagoas Distribuidora de Energia S.A.", classe: "Procedimento do Juizado Especial Cível" },
    { partes: "Ana Paula Cavalcante Rocha x Município de Maceió", classe: "Procedimento Comum Cível" },
    { partes: "Condomínio Residencial Jatiúca Park x Ricardo Alves Brandão", classe: "Execução de Título Extrajudicial" },
    { partes: "Francisca Helena Tenório x Companhia de Saneamento de Alagoas – Casal", classe: "Procedimento do Juizado Especial Cível" },
    { partes: "Lucas Gabriel Monteiro x Unimed Maceió Cooperativa de Trabalho Médico", classe: "Procedimento Comum Cível" },
    { partes: "Josefa Lúcia de Oliveira x Telemar Norte Leste S.A.", classe: "Procedimento do Juizado Especial Cível" },
    { partes: "Ministério Público do Estado de Alagoas x Wellington Souza da Silva", classe: "Ação Penal - Procedimento Ordinário" },
    { partes: "Ministério Público do Estado de Alagoas x Jefferson Lima Barros e outro", classe: "Ação Penal - Procedimento Ordinário" },
    { partes: "Pedro Henrique Wanderley x Ebazar.com.br Ltda.", classe: "Procedimento do Juizado Especial Cível" },
    { partes: "Antônio Marcos Bezerra x Banco Bradesco Financiamentos S.A.", classe: "Busca e Apreensão em Alienação Fiduciária" },
    { partes: "Associação dos Moradores do Vergel x Estado de Alagoas", classe: "Ação Civil Pública" },
    { partes: "Rosângela Maria Pimentel x Azul Linhas Aéreas Brasileiras S.A.", classe: "Procedimento do Juizado Especial Cível" },
    { partes: "Cícero Augusto Nascimento x Seguradora Líder dos Consórcios do Seguro DPVAT", classe: "Procedimento Comum Cível" },
    { partes: "Construtora Litoral Norte Ltda. x Marcelo Vieira Tavares", classe: "Monitória" },
    { partes: "Ministério Público do Estado de Alagoas x Daniel Ferreira dos Anjos", classe: "Ação Penal - Procedimento Sumário" },
  ];
  const SIGILOSOS = [
    { partes: "M. A. S. x J. R. S.", classe: "Alimentos - Lei Especial Nº 5.478/68" },
    { partes: "L. C. P. x R. M. P.", classe: "Divórcio Litigioso" },
    { partes: "A. B. F. x T. G. F.", classe: "Guarda" },
    { partes: "Ministério Público do Estado de Alagoas x E. P. G.", classe: "Medidas Protetivas de Urgência (Lei Maria da Penha)" },
  ];
  const FLAGRANTEADOS = ["Erivaldo Pereira Gomes", "Thiago Henrique Lins", "Jonas da Silva Freitas", "Kleber Rodrigues Melo", "Alexsandro Batista Costa"];
  const LOCAIS = ["Sala de audiências — 2ª Vara Cível da Capital", "Virtual (videoconferência)", "Cejusc — sala 2", "Sala de audiências — 2ª Vara Cível da Capital", "Virtual (videoconferência)"];
  const MAGISTRADOS = ["Dra. Camila Duarte Albuquerque", "Dra. Camila Duarte Albuquerque", "Conciliador Rafael Teixeira Lopes", "Dra. Camila Duarte Albuquerque"];

  let sequencial = 700120;

  function novaAudiencia(data, hora, opcoes = {}) {
    const eproc = opcoes.sistema ? opcoes.sistema === "eproc" : aleatorio() < 0.3;
    const sistema = eproc ? "eproc" : "esaj";
    sequencial += entre(37, 911);
    const ano = escolher([2023, 2024, 2024, 2025, 2025, 2026]);
    const processo = eproc ? cnj(5000000 + (sequencial % 90000), ano, 8, 2, 1) : cnj(sequencial, ano, 8, 2, 1);
    let tipo = opcoes.tipo || escolher(TIPOS.concat(["Conciliação", "Instrução e julgamento", "Conciliação"]));
    let caso = escolher(CASOS);
    let sigiloso = false;
    if (tipo === "Custódia") {
      caso = { partes: "Justiça Pública x " + escolher(FLAGRANTEADOS), classe: "Auto de Prisão em Flagrante" };
    } else if (aleatorio() < 0.1) {
      caso = escolher(SIGILOSOS);
      sigiloso = true;
    }
    if (/Penal/.test(caso.classe) && tipo === "Conciliação") tipo = "Instrução e julgamento";
    const passado = data < hoje;
    let situacao = "Designada";
    const r = aleatorio();
    if (passado) {
      situacao = r < 0.62 ? "Realizada" : r < 0.76 ? "Não realizada" : r < 0.86 ? "Redesignada" : r < 0.95 ? "Cancelada" : "Suspensa";
    } else if (r < 0.06) {
      situacao = "Cancelada";
    } else if (r < 0.11) {
      situacao = "Redesignada";
    } else if (r < 0.14) {
      situacao = "Suspensa";
    }
    if (opcoes.situacao) situacao = opcoes.situacao;
    const local = tipo === "Custódia" ? "Central de Custódia — Fórum da Capital" : escolher(LOCAIS);
    const virtual = /Virtual/.test(local);
    return {
      id: Math.floor(aleatorio() * 1e16).toString(16).padStart(16, "0").slice(0, 16),
      sistema,
      tribunal: "TJAL",
      processo,
      data: iso(data),
      hora,
      tipo,
      situacao,
      local,
      link: virtual ? `https://videoconferencia.tjal.jus.br/sala/2vcivel-${entre(100, 999)}` : "",
      classe: caso.classe,
      partes: caso.partes,
      magistrado: tipo === "Conciliação" || tipo === "Mediação" ? "Conciliador Rafael Teixeira Lopes" : escolher(MAGISTRADOS.slice(0, 2)),
      sigiloso,
      observacoes: situacao === "Redesignada" ? "Redesignada a pedido da parte ré." : "",
      origem: eproc ? "eProc TJAL — Gerenciar audiências" : "e-SAJ TJAL — Agenda de audiências",
      capturada_em: isoHora(agoraMenos(95)),
      tipo_original: tipo,
      situacao_original: situacao,
    };
  }

  function gerarPauta() {
    const lista = [];
    for (let n = -6; n <= 15; n++) {
      const d = dia(n);
      const fimDeSemana = d.getDay() === 0 || d.getDay() === 6;
      if (fimDeSemana) {
        // Plantão: só custódia.
        const qtd = n === 0 ? 3 : (n > 0 && n < 9 ? 1 : 0);
        ["09:00", "10:00", "11:30"].slice(0, qtd).forEach((h) => lista.push(novaAudiencia(d, h, { tipo: "Custódia", sistema: "eproc" })));
        continue;
      }
      const qtd = n === 0 ? 4 : entre(1, 3);
      const horas = HORAS.slice().sort(() => aleatorio() - 0.5).slice(0, qtd).sort();
      for (const h of horas) lista.push(novaAudiencia(d, h));
    }
    return lista.sort((a, b) => (a.data + a.hora).localeCompare(b.data + b.hora));
  }

  const pauta = PAUTA_VAZIA ? [] : gerarPauta();
  // Uma audiência em segredo de justiça sempre presente (amanhã, 15:30): a
  // pauta sabe do sigilo, e a tela Audiências liga o interruptor sozinha.
  const PROCESSO_SIGILOSO = cnj(700888, 2025, 8, 2, 1);
  if (!PAUTA_VAZIA) {
    const amanha = dia(1);
    pauta.push({
      id: "a0f5e1c2d3b4a596", sistema: "esaj", tribunal: "TJAL", processo: PROCESSO_SIGILOSO, data: iso(amanha), hora: "15:30",
      tipo: "Conciliação", situacao: "Designada", local: "Cejusc — sala 2", link: "", classe: "Guarda", partes: "R. S. M. x A. P. M.",
      magistrado: "Conciliador Rafael Teixeira Lopes", sigiloso: true, observacoes: "", origem: "e-SAJ TJAL — Agenda de audiências",
      capturada_em: isoHora(agoraMenos(95)), tipo_original: "Conciliação", situacao_original: "Designada",
    });
    pauta.sort((a, b) => (a.data + a.hora).localeCompare(b.data + b.hora));
  }
  const MOTIVO_PAUTA = "A pauta de audiências indica que este processo corre em segredo de justiça.";
  const MOTIVO_AUTOS = "Os autos deste processo (ou uma transcrição ou gravação dele) estão na pasta dos sigilosos.";
  /** Por que o programa já sabe que o processo é sigiloso ("" = não sabe). */
  function sigiloConhecido(numero) {
    if (recentes.some((r) => r.sigiloso && r.numero === numero)) return MOTIVO_AUTOS;
    if (pauta.some((a) => a.sigiloso && a.processo === numero)) return MOTIVO_PAUTA;
    return "";
  }

  // ----------------------------------- o que do sigiloso ficou no acervo
  // As frases são as do servidor (preparo.frase_sigilosos_no_acervo): a
  // pendência do Início e a faixa da tela Compartilhar dizem o mesmo.
  const SIGILO = ["arquivos", "autos"].includes(params.get("sigilo")) ? params.get("sigilo") : "";
  const LOTE_DO_SIGILOSO = "Pauta da semana";
  const NO_ACERVO = {
    arquivos: {
      arquivos: [PASTAS.acervo + "\\Minutas\\" + PROCESSO_SIGILOSO + ".docx"],
      titulo: "Arquivo de processo sigiloso no acervo",
      mensagem: `Um arquivo do processo ${PROCESSO_SIGILOSO}, que corre em segredo de justiça, ficou no acervo: Minutas\\${PROCESSO_SIGILOSO}.docx (está aberto em outro programa?). Feche-o e prepare o acervo para a IA de novo, ou mova-o você mesmo para a pasta dos sigilosos (${PASTAS.sigilosos}\\Minutas). O compartilhamento continua: o índice, o conector, o pacote e a nuvem já deixam o processo de fora, mas o Claude Code, o Cowork e o ChatGPT, que abrem a pasta inteira, ainda podem vê-lo.`,
    },
    autos: {
      arquivos: [PASTAS.processos + "\\" + LOTE_DO_SIGILOSO + "\\" + PROCESSO_SIGILOSO + ".pdf"],
      titulo: "Processo sigiloso no acervo",
      mensagem: `Os autos do processo ${PROCESSO_SIGILOSO}, que corre em segredo de justiça, não puderam sair do acervo: Processos\\${LOTE_DO_SIGILOSO}\\${PROCESSO_SIGILOSO}.pdf (está aberto em outro programa?). Feche o arquivo e tente de novo, ou mova-o para a pasta dos sigilosos (${PASTAS.sigilosos}\\${LOTE_DO_SIGILOSO}). Até ele sair, nada do acervo é compartilhado: os botões da tela Compartilhar, o pacote e o espelho na nuvem ficam suspensos.`,
    },
  };
  // Com os autos presos, todo compartilhamento é recusado (409), como no
  // servidor (api_compartilhar.exigir_sem_sigiloso).
  const SUSPENSOS_COM_OS_AUTOS = new Set([
    "POST /api/compartilhar/preparar", "POST /api/compartilhar/claude-desktop", "POST /api/compartilhar/cowork",
    "POST /api/compartilhar/claude-code", "POST /api/compartilhar/chatgpt-work", "POST /api/compartilhar/codex",
    "POST /api/compartilhar/pacote", "POST /api/compartilhar/nuvem/espelhar",
  ]);
  function exigirSemSigiloso(rota) {
    if (SIGILO === "autos" && SUSPENSOS_COM_OS_AUTOS.has(rota)) {
      throw new H.api.ErroApi("sigiloso_no_acervo", NO_ACERVO.autos.mensagem, rota, 409);
    }
  }

  // Alterações recentes (as três primeiras ainda não vistas).
  function gerarAlteracoes() {
    if (!pauta.length) return [];
    const futuras = pauta.filter((a) => a.data >= iso(hoje));
    const pega = (i) => futuras[Math.min(i, futuras.length - 1)];
    const lista = [
      { quando: isoHora(agoraMenos(42)), tipo: "nova", audiencia: pega(6), campos: [], vista: false },
      { quando: isoHora(agoraMenos(42)), tipo: "alterada", audiencia: pega(3), campos: [{ campo: "hora", antes: pega(3).hora === "08:30" ? "10:00" : "08:30", depois: pega(3).hora }], vista: false },
      { quando: isoHora(agoraMenos(42)), tipo: "cancelada", audiencia: Object.assign({}, pega(9), { situacao: "Cancelada" }), campos: [{ campo: "situacao", antes: "Designada", depois: "Cancelada" }], vista: false },
      { quando: isoHora(agoraMenos(60 * 26)), tipo: "alterada", audiencia: pega(12), campos: [{ campo: "local", antes: "Sala de audiências — 2ª Vara Cível da Capital", depois: "Virtual (videoconferência)" }], vista: true },
      { quando: isoHora(agoraMenos(60 * 27)), tipo: "nova", audiencia: pega(14), campos: [], vista: true },
      { quando: isoHora(agoraMenos(60 * 50)), tipo: "removida", audiencia: Object.assign({}, pega(1), { processo: cnj(700777, 2024, 8, 2, 1) }), campos: [], vista: true },
    ];
    const canc = pauta.find((a) => a.id === pega(9).id);
    if (canc) canc.situacao = "Cancelada";
    return lista;
  }
  const alteracoes = gerarAlteracoes();

  let fontes = PAUTA_VAZIA ? [] : [
    { id: "f-esaj-tjal", tribunal: "TJAL", sistema: "esaj", rotulo: "e-SAJ · TJAL — 2ª Vara Cível da Capital", modo: "automatico", url: "https://www2.tjal.jus.br/sajcas/agendaAudiencias", menu: "Agenda › Audiências", monitorada: !MOTIVO_PRESENCA, exige_presenca: !!MOTIVO_PRESENCA, motivo_presenca: MOTIVO_PRESENCA, ultima_sincronizacao: isoHora(agoraMenos(42)), ultimo_erro: "" },
    { id: "f-eproc-tjal", tribunal: "TJAL", sistema: "eproc", rotulo: "eProc · TJAL", modo: "capturado", url: "https://eproc1g.tjal.jus.br/eproc/controlador.php?acao=audiencia_listar", menu: "", monitorada: !MOTIVO_PRESENCA, exige_presenca: !!MOTIVO_PRESENCA, motivo_presenca: MOTIVO_PRESENCA, ultima_sincronizacao: isoHora(agoraMenos(42)), ultimo_erro: "" },
  ];
  let monitoramento = { ativo: !PAUTA_VAZIA, intervalo_horas: 6, proxima: MOTIVO_PRESENCA ? null : isoHora(new Date(Date.now() + 5.3 * 3600000)) };
  let ultimaSincronizacao = PAUTA_VAZIA ? null : isoHora(agoraMenos(42));
  let pautaImportada = false;

  // ============================================================== acervo
  const lotes = [
    { nome: "Relação de setembro", quando: isoHora(agoraMenos(60 * 20)), total: 48, baixados: 45, falhas: 3, pasta: PASTAS.processos + "\\Relação de setembro", relatorio: PASTAS.processos + "\\Relação de setembro\\_controle\\relatorio.csv" },
    { nome: "Conclusos para sentença", quando: isoHora(agoraMenos(60 * 24 * 4)), total: 22, baixados: 22, falhas: 0, pasta: PASTAS.processos + "\\Conclusos para sentença", relatorio: PASTAS.processos + "\\Conclusos para sentença\\_controle\\relatorio.csv" },
    { nome: "Metas CNJ 2026", quando: isoHora(agoraMenos(60 * 24 * 9)), total: 61, baixados: 58, falhas: 3, pasta: PASTAS.processos + "\\Metas CNJ 2026", relatorio: PASTAS.processos + "\\Metas CNJ 2026\\_controle\\relatorio.csv" },
  ];
  const recentes = [
    { numero: cnj(702318, 2024, 8, 2, 1), arquivo: PASTAS.transcricoes + "\\" + cnj(702318, 2024, 8, 2, 1) + ".docx", quando: isoHora(agoraMenos(60 * 3)), sigiloso: false },
    { numero: cnj(700954, 2023, 8, 2, 1), arquivo: PASTAS.sigilosos + "\\Transcricoes\\" + cnj(700954, 2023, 8, 2, 1) + ".docx", quando: isoHora(agoraMenos(60 * 26)), sigiloso: true },
    { numero: cnj(5001377, 2025, 8, 2, 1), arquivo: PASTAS.transcricoes + "\\" + cnj(5001377, 2025, 8, 2, 1) + ".docx", quando: isoHora(agoraMenos(60 * 49)), sigiloso: false },
    { numero: cnj(701822, 2024, 8, 2, 1), arquivo: PASTAS.transcricoes + "\\" + cnj(701822, 2024, 8, 2, 1) + ".docx", quando: isoHora(agoraMenos(60 * 24 * 5)), sigiloso: false },
  ];
  let recuperaveis = [
    { arquivo: PASTAS.transcricoes + "\\_sessoes\\" + cnj(700412, 2024, 8, 2, 1) + ".jsonl", processo: cnj(700412, 2024, 8, 2, 1), quando: isoHora(agoraMenos(60 * 22)) },
  ];

  // ============================================================== ajustes
  const ESQUEMA = [
    ["geral", "pasta_acervo", "pasta", "Pasta do acervo", "O que fica aqui é compartilhado com a IA: processos, transcrições e arquivos de contexto."],
    ["geral", "pasta_sigilosos", "pasta", "Pasta dos sigilosos", "Processos em segredo de justiça. Fica fora do acervo e nunca vai para a IA."],
    ["pauta", "pasta", "pasta", "Pasta da pauta exportada", "Onde ficam as planilhas da pauta. Fora do acervo: trazem partes de processos sigilosos."],
    ["geral", "nome_usuario", "texto", "Como chamar você", "Aparece na saudação da tela inicial."],
    ["unidade", "magistrado", "texto", "Magistrado(a)", "Aparece no cabeçalho das transcrições."],
    ["unidade", "cargo", "texto", "Cargo", ""],
    ["unidade", "vara", "texto", "Vara", ""],
    ["unidade", "comarca", "texto", "Comarca", ""],
    ["unidade", "tribunal", "texto", "Tribunal", ""],
    ["esaj", "login", "escolha", "Entrar no e-SAJ com", "Com certificado digital, o navegador abre à vista para você digitar o PIN.", [["senha", "Usuário e senha"], ["certificado", "Certificado digital"], ["manual", "Manualmente"]]],
    ["eproc", "login", "escolha", "Entrar no eProc com", "O código do aplicativo autenticador é pedido numa janela do Helestron.", [["senha", "Usuário e senha"], ["manual", "Manualmente"]]],
    ["eproc", "perfil", "texto", "Perfil no eProc", "Quando você tem mais de um perfil (ex.: MAGISTRADO). Em branco, o Helestron pergunta."],
    ["download", "espera_login_minutos", "inteiro", "Esperar o login até (min)", "Tempo para você concluir o login (código por e-mail, certificado)."],
    ["download", "pular_baixados", "flag", "Pular o que já foi baixado", "Processo cujo PDF já está na pasta do lote não é baixado de novo."],
    ["download", "separar_sigilosos", "flag", "Separar os sigilosos", "Processo em segredo de justiça vai para a pasta dos sigilosos, fora do acervo."],
    ["download", "baixar_midias", "flag", "Baixar também as gravações de audiência", "Ficam em _controle\\midias, dentro da pasta do lote."],
    ["download", "mostrar_navegador", "flag", "Mostrar o navegador enquanto baixa", "O login por certificado e o login manual sempre mostram."],
    ["download", "navegador", "escolha", "Navegador dos portais", "O Helestron usa o Google Chrome ou o Microsoft Edge deste computador (o Edge vem com o Windows) e não baixa navegador próprio.", [["auto", "Automático (Chrome, senão Edge)"], ["chrome", "Google Chrome"], ["msedge", "Microsoft Edge"], ["chromium", "Chromium já instalado no computador"]]],
    ["download", "pausa_entre_processos", "inteiro", "Pausa entre processos (s)", "Não zere em listas grandes: rajada de acessos pode ser lida pelo portal como abuso."],
    ["download", "tentativas", "inteiro", "Tentativas por processo", "Quantas vezes tentar um processo que falhou por instabilidade."],
    ["eproc", "modo", "escolha", "Montagem do PDF no eProc", "Peça por peça (com marcadores por evento) ou pelo “Download Completo” do eProc.", [["documentos", "Peça por peça"], ["completo", "Download completo"]]],
    ["transcricao", "modelo_ao_vivo", "escolha", "Modelo ao vivo", "Base para computador mais simples; small é o recomendado.", [["base", "Base"], ["small", "Small"], ["medium", "Medium"]]],
    ["transcricao", "modelo_revisao", "escolha", "Modelo da revisão", "Usado na revisão final e nas gravações.", [["small", "Small"], ["medium", "Medium"], ["large-v3-turbo", "Large v3 turbo"]]],
    ["transcricao", "refinar_ao_encerrar", "flag", "Revisar ao encerrar", "Refaz a transcrição inteira com o modelo de revisão (leva alguns minutos)."],
    ["transcricao", "dispositivo", "texto", "Dispositivo", "Microfone. Em branco = o padrão do Windows."],
    ["transcricao", "separar_falantes", "flag", "Separar as vozes na revisão", "Os modelos de voz vêm com o instalador."],
    ["transcricao", "salvar_audio", "flag", "Guardar a gravação", "Arquivo FLAC ao lado da transcrição, na pasta _audio."],
    ["transcricao", "marcar_tempo", "flag", "Marcar o tempo de cada fala", "Mostra [hh:mm:ss] no documento."],
    ["transcricao", "falantes", "texto", "Participantes (F1 a F8)", "Nomes dos botões de quem está falando, separados por ponto e vírgula."],
    ["transcricao", "contexto", "texto", "Vocabulário da audiência", "Texto que orienta o vocabulário e a pontuação. Mantenha acentuado."],
    ["pauta", "monitorar", "flag", "Monitorar a pauta", "Sincroniza sozinho com o e-SAJ e o eProc e avisa o que mudou."],
    ["pauta", "intervalo_horas", "inteiro", "Intervalo (horas)", "De quanto em quanto tempo conferir a pauta."],
    ["pauta", "dias_atras", "inteiro", "Dias para trás", "Período que a sincronização confere antes de hoje."],
    ["pauta", "dias_a_frente", "inteiro", "Dias à frente", "Período que a sincronização confere depois de hoje."],
    ["pauta", "incluir_partes_sigilosos", "flag", "Incluir as partes dos sigilosos no Excel", "Desligado, a planilha mostra “(segredo de justiça)” no lugar das partes."],
    ["compartilhar", "pasta_nuvem", "pasta", "Pasta na nuvem", "OneDrive ou Google Drive para espelhar o acervo. Em branco, não espelha."],
    ["compartilhar", "espelhar_automaticamente", "flag", "Espelhar sozinho", "Ao fim de cada download e de cada transcrição."],
    ["compartilhar", "incluir_texto", "flag", "Gerar o texto dos autos para a IA", "Com a página e o documento marcados; a IA lê melhor e gasta menos."],
  ];
  const valores = {
    geral: { pasta_acervo: PASTAS.acervo, pasta_sigilosos: PASTAS.sigilosos, nome_usuario: "Dra. Camila" },
    unidade: { magistrado: "Camila Duarte Albuquerque", cargo: "Juíza de Direito", vara: "2ª Vara Cível da Capital", comarca: "Maceió", tribunal: "Tribunal de Justiça de Alagoas" },
    esaj: { login: "senha" },
    eproc: { login: "senha", perfil: "MAGISTRADO", modo: "documentos" },
    download: { espera_login_minutos: "10", pular_baixados: "true", separar_sigilosos: "true", baixar_midias: "false", mostrar_navegador: "false", navegador: "auto", pausa_entre_processos: "3", tentativas: "2" },
    transcricao: {
      modelo_ao_vivo: "small", modelo_revisao: "medium", refinar_ao_encerrar: "false", separar_falantes: "true",
      dispositivo: params.get("microfone") || "",
      salvar_audio: "true", marcar_tempo: "true",
      falantes: "Juiz(a);Promotor(a);Defensor(a);Advogado(a) do autor;Advogado(a) do réu;Testemunha;Parte;Outro",
      contexto: "Transcrição de audiência judicial. Participam o Juiz de Direito, o Ministério Público, advogados, partes e testemunhas. Vocabulário forense: Meritíssimo, Excelência, contraditado, compromissada, depoimento, oitiva, instrução.",
    },
    pauta: { pasta: PASTAS.pauta, monitorar: String(!PAUTA_VAZIA), intervalo_horas: "6", dias_atras: "7", dias_a_frente: "60", incluir_partes_sigilosos: "false" },
    compartilhar: { pasta_nuvem: "", espelhar_automaticamente: "false", incluir_texto: "true" },
  };

  // Endereços dos portais: o do catálogo e as correções do usuário.
  const ENDERECOS_CATALOGO = {
    "esaj:TJAL": { base: "https://www2.tjal.jus.br" },
    "eproc:TJAL": { "1g": "https://eproc1g.tjal.jus.br/eproc/", "2g": "https://eproc2g.tjal.jus.br/eproc/" },
    "esaj:TJSP": { base: "https://esaj.tjsp.jus.br" },
    "eproc:TRF4": { "1g_70": "https://eproc.jfpr.jus.br/eprocV2/", "1g_71": "https://eproc.jfrs.jus.br/eprocV2/", "1g_72": "https://eproc.jfsc.jus.br/eprocV2/", "2g": "https://eproc.trf4.jus.br/eproc2trf4/" },
  };
  const enderecosLocais = {};
  const rotuloGrau = (g) => (g === "base" ? "Endereço do portal" : ({ "1g": "1º grau", "2g": "2º grau" }[g.split("_")[0]] || g) + (g.includes("_") ? " — " + ({ 70: "Paraná", 71: "Rio Grande do Sul", 72: "Santa Catarina" }[g.split("_")[1]] || "seção " + g.split("_")[1]) : ""));
  const rotuloPortal = (portal) => { const [s, sigla] = portal.split(":"); return `${sigla} · ${s === "eproc" ? "eProc" : "e-SAJ"}`; };
  function enderecosDe(portal) {
    const catalogo = ENDERECOS_CATALOGO[portal] || (portal.startsWith("esaj:") ? { base: "https://esaj." + portal.split(":")[1].toLowerCase() + ".jus.br" } : { "1g": "https://eproc1g." + portal.split(":")[1].toLowerCase() + ".jus.br/eproc/" });
    const locais = enderecosLocais[portal] || {};
    return {
      portal, rotulo: rotuloPortal(portal),
      enderecos: Object.keys(Object.assign({}, catalogo, locais)).map((grau) => ({ grau, rotulo: rotuloGrau(grau), url: locais[grau] || catalogo[grau] || "", padrao: catalogo[grau] || "", corrigido: !!locais[grau] })),
    };
  }

  let acessos = [
    { portal: "esaj:TJAL", rotulo: "e-SAJ · TJAL", usuario: "camila.albuquerque", tem_senha: true },
    { portal: "eproc:TJAL", rotulo: "eProc · TJAL", usuario: "", tem_senha: false },
    { portal: "esaj:TJSP", rotulo: "e-SAJ · TJSP", usuario: "", tem_senha: false },
  ];

  const TRIBUNAIS = [
    { sigla: "TJAL", nome: "Tribunal de Justiça — Alagoas", sistema: "esaj", alternativo: "eproc" },
    { sigla: "TJAC", nome: "Tribunal de Justiça — Acre", sistema: "esaj", alternativo: "eproc" },
    { sigla: "TJAM", nome: "Tribunal de Justiça — Amazonas", sistema: "esaj", alternativo: "" },
    { sigla: "TJMS", nome: "Tribunal de Justiça — Mato Grosso do Sul", sistema: "esaj", alternativo: "" },
    { sigla: "TJSP", nome: "Tribunal de Justiça — São Paulo", sistema: "esaj", alternativo: "eproc" },
    { sigla: "TJRS", nome: "Tribunal de Justiça — Rio Grande do Sul", sistema: "eproc", alternativo: "" },
    { sigla: "TJSC", nome: "Tribunal de Justiça — Santa Catarina", sistema: "eproc", alternativo: "" },
    { sigla: "TJTO", nome: "Tribunal de Justiça — Tocantins", sistema: "eproc", alternativo: "" },
    { sigla: "TRF2", nome: "Tribunal Regional Federal da 2ª Região", sistema: "eproc", alternativo: "" },
    { sigla: "TRF4", nome: "Tribunal Regional Federal da 4ª Região", sistema: "eproc", alternativo: "" },
  ];

  // ============================================================== eventos
  let emitir = () => {};
  const tarefas = new Map();
  const perguntasAbertas = new Map();
  let contador = 0;

  function novaTarefa(tipo, titulo, total) {
    const t = {
      id: "t" + (++contador), tipo, titulo, estado: "rodando", inicio: isoHora(new Date()), fim: null,
      progresso: { feitos: 0, total: total || 0, atual: "", percentual: total ? 0 : null },
      status: "Começando…", resultado: null, erro: null, _parar: false,
    };
    tarefas.set(t.id, t);
    publicar(t);
    return t;
  }

  /** A tarefa como o servidor a mostra (sem os campos de controle da demonstração). */
  function semInternos(t) {
    const copia = Object.assign({}, t);
    delete copia._parar;
    delete copia._itens;
    return copia;
  }

  function publicar(t) {
    emitir("tarefa", semInternos(t));
  }

  function atualizar(t, mudancas) {
    const progresso = mudancas.progresso ? Object.assign({}, t.progresso, mudancas.progresso) : t.progresso;
    Object.assign(t, mudancas, { progresso });
    publicar(t);
  }

  function concluir(t, estado, mudancas) {
    atualizar(t, Object.assign({ estado, fim: isoHora(new Date()) }, mudancas));
    emitir("estado", {});
  }

  const pausa = (ms) => new Promise((r) => setTimeout(r, ms));

  /** Pergunta ao "usuário" e espera a resposta (como o motor de verdade). */
  function perguntar(tarefa, dados) {
    const id = "p" + (++contador);
    return new Promise((resolver) => {
      perguntasAbertas.set(id, resolver);
      emitir("pergunta", Object.assign({ id, tarefa: tarefa.id }, dados));
    });
  }

  // ------------------------------------------------------- download
  const RELACAO = [
    cnj(700231, 2024, 8, 2, 1), cnj(701118, 2023, 8, 2, 1), cnj(703456, 2025, 8, 2, 58), cnj(700089, 2022, 8, 2, 1),
    cnj(702770, 2024, 8, 2, 1), cnj(1004512, 2024, 8, 26, 100), cnj(1023877, 2023, 8, 26, 224), cnj(1001902, 2025, 8, 26, 100),
    cnj(5004417, 2024, 8, 21, 1), cnj(5012003, 2025, 8, 21, 10), cnj(5021345, 2024, 4, 4, 7100), cnj(5003318, 2023, 4, 4, 7200),
  ];

  function tribunalDe(numero) {
    const m = /\.(\d)\.(\d{2})\.\d{4}$/.exec(numero);
    if (!m) return ["", "outro"];
    const chave = m[1] + "." + m[2];
    const mapa = { "8.02": ["TJAL", "esaj"], "8.26": ["TJSP", "esaj"], "8.21": ["TJRS", "eproc"], "4.04": ["TRF4", "eproc"], "8.17": ["TJPE", "outro"] };
    const [sigla, sistema] = mapa[chave] || [chave, "outro"];
    return [sigla, sistema];
  }

  function leituraDe(numeros, extras = {}) {
    const processos = numeros.map((n) => {
      const [tribunal, sistema] = tribunalDe(n);
      return { numero: n, tribunal, sistema, tem_senha: false };
    });
    return Object.assign({ formato: "lista", origem: "", processos, avisos: [], corrompidos: [], sem_suporte: [] }, extras);
  }

  function leituraDoArquivo(nome) {
    const l = leituraDe(RELACAO, {
      formato: "xlsx", origem: nome || "Relação de outubro.xlsx",
      avisos: [`Linha 9: o dígito verificador de 0712345-11.2023.8.02.0001 não confere. Confira o número na planilha.`],
      corrompidos: ["7,00456E+18 (linha 14): o Excel transformou o número em notação científica."],
      sem_suporte: [{ numero: cnj(51234, 2024, 8, 17, 1), motivo: "O TJPE usa o PJe, que o Helestron ainda não baixa." }],
    });
    l.processos[3].tem_senha = true;
    return l;
  }

  function lerTexto(texto) {
    const achados = [];
    const avisos = [];
    const re = /(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})/g;
    let m;
    while ((m = re.exec(texto))) {
      const numero = `${m[1]}-${m[2]}.${m[3]}.${m[4]}.${m[5]}.${m[6]}`;
      const valido = BigInt(m[1] + m[3] + m[4] + m[5] + m[6] + m[2]) % 97n === 1n;
      if (!valido) { avisos.push(`O dígito verificador de ${numero} não confere: ele ficou de fora.`); continue; }
      if (!achados.includes(numero)) achados.push(numero);
    }
    const l = leituraDe(achados, { formato: "texto", origem: "Lista colada", avisos });
    const sem = l.processos.filter((p) => p.sistema === "outro");
    l.processos = l.processos.filter((p) => p.sistema !== "outro");
    l.sem_suporte = sem.map((p) => ({ numero: p.numero, motivo: `O ${p.tribunal} não usa o e-SAJ nem o eProc.` }));
    return l;
  }

  const relatoriosDosLotes = {};   // pasta do lote → {número: situação}

  async function simularDownload(t, numeros, nomeLote, opcoes) {
    const pasta = PASTAS.processos + "\\" + nomeLote;
    // Como o servidor: a tarefa guarda os itens (GET /api/tarefas/{id} os devolve).
    t._itens = {};
    const emitirItem = (dados) => {
      dados.ordem = numeros.indexOf(dados.numero);
      t._itens[dados.numero] = dados;
      emitir("item", dados);
    };
    let baixados = 0, falhas = 0, jaTinha = 0, sigilosos = 0;
    let perguntou = false;
    for (const n of numeros) emitirItem({ tarefa: t.id, numero: n, situacao: "", mensagem: "", arquivo: "", sigiloso: false });
    await pausa(500);
    for (let i = 0; i < numeros.length; i++) {
      if (t._parar) break;
      const n = numeros[i];
      const [tribunal, sistema] = tribunalDe(n);
      const portal = `${sistema === "eproc" ? "eProc" : "e-SAJ"} (${tribunal})`;
      if (!perguntou && sistema === "esaj") {
        perguntou = true;
        atualizar(t, { status: `Entrando no ${portal}…`, progresso: { atual: n } });
        await pausa(700);
        let codigo = "";
        while (codigo === "") {
          // "" = o usuário pediu um código novo: o portal manda outro e pergunta de novo.
          codigo = await perguntar(t, {
            tipo: "codigo", titulo: `Código de verificação do e-SAJ (${tribunal})`,
            mensagem: "O e-SAJ enviou um código de verificação para o seu e-mail (o cadastrado no portal). Digite-o aqui. O código vale cerca de 3 minutos; se não chegar, peça outro.",
            prazo_s: 600, reenviavel: true,
          });
          if (codigo === "") emitir("aviso", { titulo: "Novo código pedido", mensagem: "O e-SAJ enviou outro código para o seu e-mail.", nivel: "info" });
        }
        if (codigo === null) {
          concluir(t, "falhou", { erro: "Login cancelado: o código de verificação não foi informado.", status: "Login cancelado." });
          return;
        }
      }
      emitirItem({ tarefa: t.id, numero: n, situacao: "BAIXANDO", mensagem: "Abrindo a pasta digital…", arquivo: "", sigiloso: false });
      atualizar(t, { status: `Baixando ${n} no ${portal}`, progresso: { atual: n } });
      await pausa(650 + (i % 3) * 180);
      let item = { tarefa: t.id, numero: n, situacao: "OK", mensagem: `${entre(18, 412)} páginas`, arquivo: pasta + "\\" + n + ".pdf", sigiloso: false };
      if (LOTE_FALHA) item = Object.assign(item, { situacao: "ERRO", mensagem: "O portal não respondeu (tempo esgotado).", arquivo: "" });
      else if (i === 2) item = Object.assign(item, { situacao: "JA_BAIXADO", mensagem: "O PDF já estava na pasta do lote." });
      if (i === 4 && opcoes.separar_sigilosos !== false) item = Object.assign(item, { sigiloso: true, mensagem: "Segredo de justiça: salvo na pasta dos sigilosos.", arquivo: PASTAS.sigilosos + "\\" + nomeLote + "\\" + n + ".pdf" });
      if (i === 7) item = Object.assign(item, { situacao: "NAO_ENCONTRADO", mensagem: "Não achei o processo no e-SAJ do TJSP.", arquivo: "" });
      emitirItem(item);
      if (item.situacao === "OK") baixados++;
      if (item.situacao === "JA_BAIXADO") jaTinha++;
      if (item.situacao === "NAO_ENCONTRADO" || item.situacao === "ERRO") falhas++;
      if (item.sigiloso) sigilosos++;
      atualizar(t, { progresso: { feitos: i + 1, percentual: (100 * (i + 1)) / numeros.length } });
    }
    const partes = [`${baixados} ${baixados === 1 ? "baixado" : "baixados"}`];
    if (jaTinha) partes.push(`${jaTinha} ${jaTinha === 1 ? "já existia" : "já existiam"}`);
    if (falhas) partes.push(`${falhas} com falha`);
    const aRefazer = LOTE_FALHA ? numeros.slice() : numeros.filter((_n, i) => i === 7);
    const resultado = { texto: partes.join(", "), pasta, relatorio: pasta + "\\_controle\\relatorio.csv", total: numeros.length, baixados, pulados: jaTinha, falhas, sigilosos, a_refazer: aRefazer };
    if (t._parar) {
      concluir(t, "parada", { status: "Parado a seu pedido: " + partes.join(", ") + ".", resultado });
    } else {
      // Como o programa (C9): refazer parte de um lote na mesma pasta junta as
      // linhas novas às do relatório do lote, sem apagar as dos já baixados.
      const relatorio = (relatoriosDosLotes[pasta] = relatoriosDosLotes[pasta] || {});
      for (const n of numeros) relatorio[n] = (t._itens[n] || {}).situacao || "";
      const situacoes = Object.values(relatorio);
      const linha = {
        nome: nomeLote, quando: isoHora(new Date()), total: situacoes.length,
        baixados: situacoes.filter((x) => x === "OK" || x === "JA_BAIXADO").length,
        falhas: situacoes.filter((x) => x !== "OK" && x !== "JA_BAIXADO").length, pasta, relatorio: resultado.relatorio,
      };
      const antes = lotes.findIndex((l) => l.pasta === pasta);
      if (antes >= 0) lotes.splice(antes, 1);
      lotes.unshift(linha);
      concluir(t, "concluida", { status: partes.join(" · "), resultado });
    }
  }

  // ------------------------------------------------------- transcrição
  const ROTEIRO = [
    ["Juiz(a)", "Bom dia a todos. Declaro aberta a audiência de instrução e julgamento. Presentes o autor, acompanhado de seu advogado, e a preposta da ré, com sua advogada."],
    ["Juiz(a)", "Antes de iniciarmos a instrução, pergunto às partes se há possibilidade de acordo."],
    ["Advogado(a) do réu", "Excelência, a empresa apresentou proposta de três mil reais, em parcela única, mas o autor não aceitou."],
    ["Advogado(a) do autor", "Isso mesmo, Excelência. O valor não cobre sequer os prejuízos materiais comprovados nos autos."],
    ["Juiz(a)", "Sem acordo, passo à oitiva da testemunha arrolada pelo autor. A senhora pode se aproximar e dizer o seu nome completo."],
    ["Testemunha", "Rosimere da Conceição Barbosa."],
    ["Juiz(a)", "A senhora é parente, amiga íntima ou inimiga de alguma das partes?"],
    ["Testemunha", "Não, senhora. Sou vizinha do seu José há uns dez anos, só isso."],
    ["Juiz(a)", "Então a senhora presta o compromisso de dizer a verdade, sob pena de responder por falso testemunho. Com a palavra o advogado do autor."],
    ["Advogado(a) do autor", "A senhora presenciou o dia em que faltou energia na residência do autor?"],
    ["Testemunha", "Presenciei. A luz ficou cortada por quatro dias, e a geladeira dele, com os remédios de insulina, ficou desligada esse tempo todo."],
    ["Advogado(a) do autor", "O autor procurou a empresa nesse período?"],
    ["Testemunha", "Procurou, sim. Eu mesma emprestei o telefone pra ele ligar, e deram um protocolo, mas ninguém apareceu."],
    ["Juiz(a)", "Com a palavra a advogada da ré."],
    ["Advogado(a) do réu", "A senhora sabe dizer se havia débito em aberto na conta de energia do autor naquela época?"],
    ["Testemunha", "Isso eu não sei dizer, doutora. Sei que ele sempre foi muito certinho com as contas."],
    ["Juiz(a)", "Nada mais havendo, dispenso a testemunha. As partes têm outras provas a produzir?"],
    ["Advogado(a) do autor", "Não, Excelência. Requeiro prazo para alegações finais por memoriais."],
    ["Juiz(a)", "Defiro o prazo sucessivo de quinze dias para as alegações finais. Saem os presentes intimados."],
  ];

  const sessao = { id: null, estado: "parada", segundos: 0, processo: "", falas: [], falante: "", timers: [], inicio: 0, acumulado: 0 };

  function tempoSessao() {
    return sessao.acumulado + (sessao.estado === "gravando" ? (Date.now() - sessao.inicio) / 1000 : 0);
  }

  function pararTimers() {
    sessao.timers.forEach((t) => clearInterval(t));
    sessao.timers = [];
  }

  function emitirTranscricao(tipo, dados) {
    emitir("transcricao", { tipo, dados });
  }

  function iniciarSessao(pedido) {
    sessao.id = "s" + (++contador);
    sessao.estado = "gravando";
    sessao.processo = pedido.processo;
    sessao.falas = [];
    sessao.falante = pedido.falante || "Juiz(a)";
    sessao.acumulado = 0;
    sessao.inicio = Date.now();
    sessao.sigiloso = !!pedido.sigiloso;
    let i = 0;
    emitirTranscricao("estado", { texto: "Carregando o modelo small…", estado: "iniciando" });
    setTimeout(() => emitirTranscricao("estado", { texto: "Gravando", estado: "gravando" }), 600);
    if (pedido.sigiloso) {
      setTimeout(() => emitirTranscricao("aviso", { texto: "Processo em segredo de justiça: a transcrição e a gravação ficam na pasta dos sigilosos, fora do acervo." }), 900);
    }
    let fase = 0;
    sessao.timers.push(setInterval(() => {
      if (sessao.estado !== "gravando") { emitirTranscricao("nivel", { nivel: 0 }); return; }
      fase += 0.35;
      const nivel = Math.max(0, 0.12 + 0.22 * Math.sin(fase) + 0.18 * Math.sin(fase * 2.7) + 0.12 * aleatorio());
      emitirTranscricao("nivel", { nivel: Math.min(1, nivel) });
    }, 110));
    sessao.timers.push(setInterval(() => {
      if (sessao.estado !== "gravando" || i >= ROTEIRO.length) return;
      const [falante, texto] = ROTEIRO[i++];
      const fim = tempoSessao();
      const fala = { inicio: Math.max(0, fim - 2.8), fim, falante, texto };
      sessao.falas.push(fala);
      emitirTranscricao("fala", fala);
      emitirTranscricao("atraso", { segundos: Math.round((1.2 + aleatorio()) * 10) / 10 });
      if (i % 4 === 0) emitirTranscricao("salvo", { arquivo: PASTAS.transcricoes + "\\" + sessao.processo + ".docx" });
    }, 1700));
  }

  // ------------------------------------------------------- respostas
  const atraso = () => pausa(70 + Math.floor(Math.random() * 120));
  const erro = (codigo, mensagem, detalhe) => new H.api.ErroApi(codigo, mensagem, detalhe, 400);

  let codexConectado = false;     // o conector do Codex (config.toml), registrado no clique

  const MICROFONES = [
    { indice: 1, nome: "Microfone (Realtek(R) Audio)", padrao: true },
    { indice: 3, nome: "Microfone de mesa USB (Jabra Speak 510)", padrao: false },
    { indice: 5, nome: "Matriz de microfones (Intel® Smart Sound)", padrao: false },
  ];
  /**
   * Como o servidor (C2): o microfone vem pelo NOME (ou pelo número; "" é o
   * padrão do Windows). Nome que não está mais ligado é erro claro, nunca
   * outro aparelho em silêncio.
   */
  function conferirMicrofone(dispositivo) {
    const texto = String(dispositivo === undefined || dispositivo === null ? "" : dispositivo).trim();
    if (!texto || /^\d+$/.test(texto)) return;
    if (MICROFONES.some((m) => m.nome === texto)) return;
    throw new H.api.ErroApi("microfone_indisponivel",
      `O microfone “${texto}” não foi encontrado. Escolha outro em Audiências ou Ajustes › Transcrição.`, "", 409);
  }

  function filtrarPauta(c) {
    const de = c.de || "0000-00-00", ate = c.ate || "9999-99-99";
    const busca = (c.busca || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    return pauta.filter((a) => {
      if (a.data < de || a.data > ate) return false;
      if (c.sistema && a.sistema !== c.sistema) return false;
      if (c.situacao && a.situacao !== c.situacao) return false;
      if (busca) {
        const alvo = [a.processo, a.partes, a.tipo, a.local, a.classe, a.magistrado].join(" ").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
        if (!alvo.includes(busca) && !a.processo.replace(/\D/g, "").includes(busca.replace(/\D/g, "") || "#")) return false;
      }
      return true;
    });
  }

  // Como o servidor (ServicoPauta.resumo): "hoje" e "nos próximos 7 dias"
  // (de hoje a hoje + 6, os dias da visão Semana) contam só as audiências que
  // acontecem - as canceladas e as redesignadas ficam de fora.
  const SEM_AUDIENCIA = ["Cancelada", "Redesignada"];
  const acontecem = (lista) => lista.filter((a) => !SEM_AUDIENCIA.includes(a.situacao));
  const contarHoje = (lista) => acontecem(lista).filter((a) => a.data === iso(hoje)).length;
  const contarSemana = (lista) => acontecem(lista).filter((a) => a.data >= iso(hoje) && a.data <= iso(dia(6))).length;

  function resumoPauta(lista) {
    const por_situacao = {}, por_tipo = {};
    for (const a of lista) {
      por_situacao[a.situacao] = (por_situacao[a.situacao] || 0) + 1;
      por_tipo[a.tipo] = (por_tipo[a.tipo] || 0) + 1;
    }
    return {
      total: lista.length,
      hoje: contarHoje(lista),
      semana: contarSemana(lista),
      por_situacao, por_tipo,
    };
  }

  function estadoGeral() {
    const h = iso(hoje);
    const designadas = pauta.filter((a) => a.situacao === "Designada");
    const agora = new Date();
    const horaAgora = `${p2(agora.getHours())}:${p2(agora.getMinutes())}`;
    const proxima = designadas.find((a) => a.data > h || (a.data === h && a.hora >= horaAgora)) || null;
    const pendencias = [];
    if (acessos.some((a) => a.portal === "eproc:TJAL" && !a.tem_senha)) {
      pendencias.push({ chave: "acessos", titulo: "Cadastre o acesso ao eProc do TJAL", mensagem: "Sem a senha, o navegador abre para você entrar a cada lote.", acao: "ajustes#acessos" });
    }
    // Como o servidor (api_geral._pendencias): o sigiloso no acervo vem antes.
    if (SIGILO) {
      const n = NO_ACERVO[SIGILO];
      pendencias.unshift({ chave: SIGILO === "autos" ? "sigilo" : "sigilo-arquivos", titulo: n.titulo, mensagem: n.mensagem, acao: "compartilhar", arquivos: n.arquivos.slice() });
    }
    return {
      nome: "Helestron", versao: "1.0.1", modo: MODO_JANELA, usuario: valores.geral.nome_usuario, pastas: PASTAS, pendencias,
      audiencia: { ativa: !!sessao.id && sessao.estado !== "encerrada", estado: sessao.estado, processo: sessao.id ? sessao.processo : null },
      resumo: {
        processos: 312, transcricoes: 47,
        ultimos_lotes: lotes.slice(0, 5),
        transcricoes_recentes: recentes.map((r) => ({ numero: r.numero, arquivo: r.arquivo, quando: r.quando })),
        pauta: {
          hoje: contarHoje(pauta),
          semana: contarSemana(pauta),
          proxima, ultima_sincronizacao: ultimaSincronizacao,
          alteracoes_nao_vistas: alteracoes.filter((a) => !a.vista).length,
          // Como o servidor (C5): quantas fontes há, e se a pauta já foi
          // configurada (fonte cadastrada, sincronização ou importação).
          fontes: fontes.length, configurada: fontes.length > 0 || !!ultimaSincronizacao || pautaImportada,
        },
      },
      tarefas: Array.from(tarefas.values()).filter((t) => t.estado === "rodando").map(semInternos),
    };
  }

  const PROMPT_INICIAL = "Você vai trabalhar no acervo judicial desta pasta. Leia primeiro o CLAUDE.md (ou o AGENTS.md) e o INDICE.md. Depois, aguarde a minha tarefa.";

  function caminhoArquivo(nome) {
    return USUARIO + "\\Downloads\\" + nome;
  }

  const ROTAS = {
    // -------------------------------------------------------------- geral
    "GET /api/estado": () => estadoGeral(),
    "GET /api/config": () => ({
      valores,
      esquema: ESQUEMA.map(([secao, chave, tipo, rotulo, ajuda, opcoes]) => ({
        secao, chave, tipo, rotulo, ajuda,
        opcoes: opcoes ? opcoes.map(([valor, r]) => ({ valor, rotulo: r })) : undefined,
      })),
    }),
    "POST /api/config": ({ corpo }) => {
      const { secao, chave } = corpo;
      let valor = corpo.valor;
      if (typeof valor === "boolean") valor = valor ? "true" : "false";
      if (secao === "geral" && chave === "pasta_sigilosos" && String(valor).startsWith(valores.geral.pasta_acervo)) {
        throw erro("pastas_conflitantes", "A pasta dos processos em segredo de justiça não pode ficar dentro do acervo: tudo o que está no acervo é lido pela IA e copiado para a nuvem. Escolha uma pasta fora dele.");
      }
      if (ESQUEMA.some((e) => e[0] === secao && e[1] === chave && e[2] === "inteiro") && !/^\d+$/.test(String(valor))) {
        throw erro("valor_invalido", "Use só números inteiros neste campo.");
      }
      valores[secao] = valores[secao] || {};
      valores[secao][chave] = String(valor);
      return { valor: String(valor) };
    },
    "GET /api/tribunais": () => TRIBUNAIS,
    "GET /api/acessos": () => acessos,
    "POST /api/acessos": ({ corpo }) => {
      const [sistema, sigla] = String(corpo.portal).split(":");
      const rotulo = `${sistema === "eproc" ? "eProc" : "e-SAJ"} · ${sigla}`;
      const novo = { portal: corpo.portal, rotulo, usuario: corpo.usuario || "", tem_senha: !!corpo.senha };
      acessos = acessos.filter((a) => a.portal !== corpo.portal).concat([novo]);
      emitir("estado", {});
      return novo;
    },
    "DELETE /api/acessos/{portal}": ({ params: p }) => {
      acessos = acessos.map((a) => (a.portal === p.portal ? Object.assign({}, a, { usuario: "", tem_senha: false }) : a));
      emitir("estado", {});
      return {};
    },
    "GET /api/tribunais/enderecos": () => Object.entries(enderecosLocais).flatMap(([portal, graus]) =>
      Object.entries(graus).map(([grau, url]) => ({ portal, grau, rotulo: rotuloGrau(grau), url, rotulo_portal: rotuloPortal(portal) }))),
    "GET /api/tribunais/enderecos/{portal}": ({ params: p }) => enderecosDe(p.portal),
    "POST /api/tribunais/enderecos": ({ corpo }) => {
      if (corpo.url && !/^https?:\/\/\S+/i.test(corpo.url)) throw erro("valor_invalido", "Informe o endereço completo do portal, começando com https://.");
      const graus = enderecosLocais[corpo.portal] || {};
      if (corpo.url) graus[corpo.grau] = corpo.url; else delete graus[corpo.grau];
      if (Object.keys(graus).length) enderecosLocais[corpo.portal] = graus; else delete enderecosLocais[corpo.portal];
      return enderecosDe(corpo.portal);
    },
    "POST /api/acessos/testar": ({ corpo }) => {
      // Como o servidor: com 'sistema', testa exatamente aquele portal; sem
      // ele, o sistema principal do tribunal.
      const sigla = String(corpo.tribunal || "").toUpperCase();
      const trib = TRIBUNAIS.find((x) => x.sigla === sigla);
      const sistema = corpo.sistema || (trib ? trib.sistema : "esaj");
      const nome = rotuloPortal(`${sistema}:${sigla}`);
      const t = novaTarefa("teste_login", `Testar o acesso ao ${nome}`, 0);
      (async () => {
        atualizar(t, { status: "Abrindo o portal…" });
        await pausa(900);
        atualizar(t, { status: "Entrando com o usuário e a senha…" });
        await pausa(1100);
        concluir(t, "concluida", { status: `Acesso ao ${nome} confirmado.` });
      })();
      return { tarefa: t.id };
    },
    "POST /api/dialogo/arquivo": ({ corpo }) => {
      if (SEM_DIALOGO) throw erro("sem_dialogo", "Esta janela não tem o diálogo de arquivos do Windows.");
      const t = (corpo && corpo.titulo) || "";
      if (/grava/i.test(t)) return { caminho: caminhoArquivo("Audiência 0701234 - 18-09-2026.mp3") };
      if (/pauta|relat/i.test(t)) return { caminho: caminhoArquivo("Agenda de audiências - outubro.xls") };
      return { caminho: caminhoArquivo("Relação de outubro.xlsx") };
    },
    "POST /api/dialogo/pasta": ({ corpo }) => {
      if (SEM_DIALOGO) throw erro("sem_dialogo", "Esta janela não tem o diálogo de pastas do Windows.");
      return { caminho: (corpo && corpo.inicial) || DOCS };
    },
    "POST /api/abrir": ({ corpo }) => {
      console.info("[demonstração] abriria:", corpo.tipo, corpo.alvo);
      return {};
    },
    "GET /api/verificacao": () => [
      { nome: "Windows 64 bits", situacao: "ok", detalhe: "Windows 11 (compilação 22631), 64 bits; Python 3.12.10.", acao: "" },
      { nome: "Bibliotecas", situacao: "ok", detalhe: "As 19 bibliotecas estão presentes (faster-whisper 1.1.1, playwright 1.55.0, pymupdf 1.26.4, pywebview 6.2.1).", acao: "" },
      { nome: "Componentes nativos (DLLs)", situacao: "ok", detalhe: "Os 9 componentes carregaram (PyAV 15.1.0, CTranslate2 4.6.0, onnxruntime 1.22.1).", acao: "" },
      { nome: "Modelo de transcrição", situacao: "ok", detalhe: "Ao vivo: small, embutido no programa (modelos\\faster-whisper-small, pasta do programa).", acao: "" },
      { nome: "Navegador dos portais", situacao: "ok", detalhe: "Disponível: Google Chrome, Microsoft Edge.", acao: "" },
      { nome: "WebView2 (janela do programa)", situacao: "ok", detalhe: "Microsoft Edge WebView2 Runtime 129.0.2792.89 instalado.", acao: "" },
      { nome: "Microfone", situacao: "ok", detalhe: "3 entradas de áudio; padrão: Microfone (Realtek Audio).", acao: "" },
      { nome: "Pastas de trabalho", situacao: "ok", detalhe: "Acervo, sigilosos e pauta separados e graváveis.", acao: "" },
      { nome: "Cofre de senhas", situacao: "ok", detalhe: "As senhas ficam cifradas pela proteção de dados do Windows (DPAPI).", acao: "" },
      { nome: "Separação de falantes (opcional)", situacao: "ok", detalhe: "Instalada.", acao: "" },
      { nome: "Conector do acervo (MCP)", situacao: "aviso", detalhe: "O conector responde (4 ferramentas); ainda não foi ligado ao Claude Desktop nem ao ChatGPT (opcional: tela Compartilhar).", acao: "" },
    ],
    "POST /api/verificacao/completa": () => {
      const t = novaTarefa("verificacao", "Verificação completa", 6);
      (async () => {
        const etapas = ["Conferindo os arquivos", "Importando os módulos", "Carregando o modelo", "Testando o navegador", "Testando o microfone", "Conferindo as pastas"];
        for (let i = 0; i < etapas.length; i++) {
          atualizar(t, { status: etapas[i] + "…", progresso: { feitos: i, percentual: (100 * i) / etapas.length } });
          await pausa(450);
        }
        concluir(t, "concluida", { status: "Tudo certo: 9 itens em ordem e 1 aviso.", progresso: { feitos: 6, percentual: 100 } });
      })();
      return { tarefa: t.id };
    },
    "POST /api/encerrar": () => ({}),

    // --------------------------------------------------- tarefas e perguntas
    "GET /api/tarefas": () => Array.from(tarefas.values()).map(semInternos),
    "GET /api/tarefas/{id}": ({ params: p }) => {
      const t = tarefas.get(p.id);
      if (!t) throw erro("nao_encontrada", "Esta tarefa não existe mais.");
      const c = Object.assign({}, t, { itens: Object.values(t._itens || {}) }); delete c._parar; delete c._itens; return c;
    },
    "POST /api/tarefas/{id}/parar": ({ params: p }) => {
      const t = tarefas.get(p.id);
      if (t) {
        t._parar = true;
        atualizar(t, { status: "Parando ao fim do processo atual…" });
        for (const [id, resolver] of perguntasAbertas) {
          perguntasAbertas.delete(id);
          resolver(null);
          emitir("pergunta_fechada", { id, motivo: "tarefa_parada" });
        }
      }
      return {};
    },
    "POST /api/perguntas/{id}/responder": ({ params: p, corpo }) => {
      const r = perguntasAbertas.get(p.id);
      if (!r) throw erro("pergunta_fechada", "Esta pergunta já foi respondida ou o prazo acabou.");
      perguntasAbertas.delete(p.id);
      emitir("pergunta_fechada", { id: p.id, motivo: "respondida" });
      setTimeout(() => r(corpo.valor === null || corpo.valor === undefined ? "" : String(corpo.valor).replace(/\s/g, "")), 50);
      return {};
    },
    "POST /api/perguntas/{id}/cancelar": ({ params: p }) => {
      const r = perguntasAbertas.get(p.id);
      if (r) { perguntasAbertas.delete(p.id); r(null); emitir("pergunta_fechada", { id: p.id, motivo: "cancelada" }); }
      return {};
    },

    // ------------------------------------------------------------ processos
    "POST /api/relacao/arquivo": ({ corpo, formulario }) => {
      const nome = formulario ? (formulario.get("arquivo") || {}).name : String((corpo && corpo.caminho) || "").split("\\").pop();
      return leituraDoArquivo(nome);
    },
    "POST /api/relacao/texto": ({ corpo }) => {
      const l = lerTexto(corpo.texto || "");
      if (!l.processos.length && !l.sem_suporte.length) throw erro("sem_processos", "Não encontrei nenhum número de processo no texto colado. Confira se os números estão completos (20 dígitos).");
      return l;
    },
    "POST /api/relacao/link": ({ corpo }) => {
      if (!/^https:\/\//.test(corpo.url || "")) throw erro("link_invalido", "Use o link completo, começando com https://.");
      return Object.assign(leituraDoArquivo("Planilha compartilhada"), { formato: "link", origem: corpo.url });
    },
    "POST /api/download/iniciar": ({ corpo }) => {
      const numeros = corpo.processos || [];
      const nome = corpo.nome_lote || "Lote";
      const t = novaTarefa("download", `Baixar “${nome}”`, numeros.length);
      simularDownload(t, numeros, nome, corpo.opcoes || {});
      return { tarefa: t.id, pasta: PASTAS.processos + "\\" + nome };
    },
    "GET /api/download/lotes": () => lotes,

    // ----------------------------------------------------------- audiências
    "GET /api/transcricao/microfones": () => MICROFONES,
    "POST /api/transcricao/microfone/teste": ({ corpo }) => {
      conferirMicrofone(corpo && corpo.dispositivo);
      clearInterval(sessao.teste);
      let f = 0;
      sessao.teste = setInterval(() => {
        f += 0.4;
        emitir("microfone_nivel", { nivel: Math.max(0, 0.1 + 0.2 * Math.sin(f) + 0.15 * Math.sin(f * 3.1) + 0.1 * Math.random()) });
      }, 90);
      return {};
    },
    "POST /api/transcricao/microfone/parar": () => {
      clearInterval(sessao.teste);
      emitir("microfone_nivel", { nivel: 0 });
      return {};
    },
    "GET /api/transcricao/modelos": () => [
      { nome: "base", rotulo: "Base", tamanho_mb: 145, instalado: false, embutido: false, recomendado_para: ["ao_vivo"], descricao: "rápido, para computador modesto (qualidade razoável)" },
      { nome: "small", rotulo: "Small", tamanho_mb: 484, instalado: true, embutido: true, recomendado_para: ["ao_vivo"], descricao: "recomendado para a audiência ao vivo" },
      { nome: "medium", rotulo: "Medium", tamanho_mb: 1530, instalado: false, embutido: false, recomendado_para: ["revisao"], descricao: "mais preciso; bom para a revisão final" },
      { nome: "large-v3-turbo", rotulo: "Large v3 Turbo", tamanho_mb: 1620, instalado: false, embutido: false, recomendado_para: ["revisao"], descricao: "o mais preciso; revisão em computador forte" },
    ],
    "GET /api/transcricao/falantes": () => ({
      disponivel: falantesProntos, situacao: falantesProntos ? "instalada" : "incompleta (faltam os modelos de voz)",
      biblioteca: true, modelos: falantesProntos, embutidos: falantesProntos, tamanho_mb: 47,
    }),
    "POST /api/transcricao/falantes/baixar": () => {
      const t = novaTarefa("modelo", "Baixar os modelos de voz", 100);
      (async () => {
        for (let p = 0; p <= 100; p += 20) {
          atualizar(t, { status: `Baixando os modelos de voz: ${p}%`, progresso: { feitos: p, percentual: p } });
          await pausa(200);
        }
        falantesProntos = true;
        concluir(t, "concluida", { status: "Separação de falantes pronta." });
      })();
      return { tarefa: t.id };
    },
    "POST /api/transcricao/modelos/baixar": ({ corpo }) => {
      const t = novaTarefa("modelo", `Baixar o modelo ${corpo.nome}`, 100);
      (async () => {
        for (let p = 0; p <= 100; p += 10) {
          atualizar(t, { status: `${p}% baixado`, progresso: { feitos: p, percentual: p } });
          await pausa(250);
        }
        concluir(t, "concluida", { status: `Modelo ${corpo.nome} pronto para uso.` });
      })();
      return { tarefa: t.id };
    },
    "POST /api/transcricao/iniciar": ({ corpo }) => {
      if (sessao.id && sessao.estado !== "encerrada") throw erro("sessao_ativa", "Já há uma audiência sendo transcrita. Encerre-a antes de começar outra.");
      conferirMicrofone("dispositivo" in corpo ? corpo.dispositivo : valores.transcricao.dispositivo);
      // O pedido só ACRESCENTA sigilo (C4): o que o programa já sabe vale
      // mesmo com o interruptor desligado, e a resposta diz por quê.
      const motivo = corpo.sigiloso ? "" : sigiloConhecido(corpo.processo);
      const pedido = Object.assign({}, corpo, { sigiloso: !!corpo.sigiloso || !!motivo });
      sessao.documento = null;
      sessao.tipo = corpo.tipo || "";
      clearInterval(sessao.teste);
      iniciarSessao(pedido);
      const resposta = { sessao: sessao.id, processo: corpo.processo, sigiloso: pedido.sigiloso, sigiloso_forcado: !!motivo };
      if (motivo) resposta.motivo = motivo;
      return resposta;
    },
    "POST /api/transcricao/pausar": () => {
      sessao.acumulado = tempoSessao();
      sessao.estado = "pausada";
      emitirTranscricao("estado", { texto: "Pausado", estado: "pausada" });
      return {};
    },
    "POST /api/transcricao/retomar": () => {
      sessao.inicio = Date.now();
      sessao.estado = "gravando";
      emitirTranscricao("estado", { texto: "Gravando", estado: "gravando" });
      return {};
    },
    "POST /api/transcricao/falante": ({ corpo }) => {
      sessao.falante = corpo.falante;
      return {};
    },
    "POST /api/transcricao/encerrar": async ({ corpo }) => {
      if (corpo && corpo.tipo) sessao.tipo = corpo.tipo;
      sessao.acumulado = tempoSessao();
      sessao.estado = "encerrando";
      emitirTranscricao("estado", { texto: "Concluindo a transcrição: 1 trecho na fila…", estado: "encerrando" });
      await pausa(1400);
      pararTimers();
      const pasta = sessao.sigiloso ? PASTAS.sigilosos + "\\Transcricoes" : PASTAS.transcricoes;
      const documento = pasta + "\\" + sessao.processo + ".docx";
      sessao.estado = "encerrada";
      sessao.documento = documento;
      emitirTranscricao("salvo", { arquivo: documento });
      emitirTranscricao("estado", { texto: "Concluído", estado: "encerrada" });
      emitirTranscricao("fim", { documento });
      recentes.unshift({ numero: sessao.processo, arquivo: documento, quando: isoHora(new Date()), sigiloso: !!sessao.sigiloso });
      sessao.ultima = { processo: sessao.processo, sigiloso: sessao.sigiloso, tipo: sessao.tipo || "" };
      emitir("estado", {});
      return { documento };
    },
    "GET /api/transcricao/estado": () => (sessao.id ? {
      sessao: sessao.id, estado: sessao.estado,
      texto_estado: { gravando: "Gravando", pausada: "Pausado", encerrando: "Concluindo a transcrição…", encerrada: "Concluído" }[sessao.estado] || "",
      segundos: Math.round(tempoSessao() * 10) / 10, processo: sessao.processo, sigiloso: !!sessao.sigiloso,
      documento: sessao.documento || null, falante: sessao.falante, falas: sessao.falas,
    } : { sessao: null, estado: "parada", texto_estado: "", segundos: 0, processo: null, sigiloso: false, documento: null, falante: "", falas: [] }),
    "GET /api/transcricao/recuperaveis": () => recuperaveis,
    "POST /api/transcricao/recuperar": ({ corpo }) => {
      const r = recuperaveis.find((x) => x.arquivo === corpo.arquivo);
      recuperaveis = recuperaveis.filter((x) => x.arquivo !== corpo.arquivo);
      return { documento: PASTAS.transcricoes + "\\" + (r ? r.processo : "audiencia") + ".docx" };
    },
    "POST /api/transcricao/gravacao": ({ corpo, formulario }) => {
      const campo = (k) => (formulario ? formulario.get(k) : corpo && corpo[k]);
      const revisao = !formulario && corpo && corpo.revisao === true;
      if (revisao && !sessao.ultima) throw Object.assign(erro("sem_audiencia", "Não há audiência encerrada para revisar."), { status: 409 });
      const processo = revisao ? sessao.ultima.processo : campo("processo");
      // A ficha da revisão leva o tipo da audiência (o da tela, ou o da sessão).
      const tipo = String(campo("tipo") || (revisao ? sessao.ultima.tipo : "") || "");
      const pedido = campo("sigiloso");
      const marcado = pedido === true || pedido === "true";
      const motivo = marcado ? "" : revisao ? (sessao.ultima.sigiloso ? "A audiência ao vivo foi gravada como sigilosa." : "") : sigiloConhecido(processo);
      const sigiloso = marcado || !!motivo;
      const t = novaTarefa("transcricao_arquivo", revisao ? "Revisar a audiência" : "Transcrever a gravação", 100);
      (async () => {
        for (let p = 0; p <= 100; p += 5) {
          atualizar(t, { status: p < 10 ? "Carregando o modelo medium…" : `${revisao ? "Revisando" : "Transcrevendo"}: ${p}%`, progresso: { feitos: p, percentual: p } });
          await pausa(220);
        }
        const documento = (sigiloso ? PASTAS.sigilosos + "\\Transcricoes" : PASTAS.transcricoes) + "\\" + processo + ".docx";
        recentes.unshift({ numero: processo, arquivo: documento, quando: isoHora(new Date()), sigiloso });
        concluir(t, "concluida", { status: "Transcrição pronta.", resultado: { documento, tipo } });
      })();
      const resposta = { tarefa: t.id, sigiloso, sigiloso_forcado: !!motivo };
      if (motivo) resposta.motivo = motivo;
      return resposta;
    },
    "GET /api/transcricao/recentes": () => recentes,

    // ---------------------------------------------------------------- pauta
    "GET /api/pauta": ({ consulta }) => {
      const lista = filtrarPauta(consulta || {});
      return { audiencias: lista, resumo: resumoPauta(lista), ultima_sincronizacao: ultimaSincronizacao, monitoramento };
    },
    "GET /api/pauta/fontes": () => fontes,
    "POST /api/pauta/fontes": ({ corpo }) => {
      const f = { id: "f-" + corpo.sistema + "-" + String(corpo.tribunal).toLowerCase(), tribunal: corpo.tribunal, sistema: corpo.sistema, rotulo: corpo.rotulo || `${corpo.sistema === "eproc" ? "eProc" : "e-SAJ"} · ${corpo.tribunal}`, modo: corpo.url ? "capturado" : "automatico", url: corpo.url || "", menu: "", monitorada: !!corpo.url && !MOTIVO_PRESENCA, exige_presenca: !!MOTIVO_PRESENCA, motivo_presenca: MOTIVO_PRESENCA, ultima_sincronizacao: null, ultimo_erro: "" };
      fontes = fontes.filter((x) => x.id !== f.id).concat([f]);
      return f;
    },
    "DELETE /api/pauta/fontes/{id}": ({ params: p }) => {
      fontes = fontes.filter((f) => f.id !== p.id);
      return {};
    },
    "POST /api/pauta/sincronizar": () => {
      if (!fontes.length) throw erro("sem_fontes", "Nenhuma fonte da pauta configurada. Escolha o tribunal e o sistema primeiro.");
      const t = novaTarefa("pauta_sincronizar", "Sincronizar a pauta", fontes.length * 3);
      (async () => {
        let feitos = 0;
        for (const f of fontes) {
          const nome = `${f.sistema === "eproc" ? "eProc" : "e-SAJ"} (${f.tribunal})`;
          for (const etapa of [`Entrando no ${nome}…`, `Lendo a pauta do ${nome} (página 2 de 3)…`, `Gravando as audiências do ${nome}…`]) {
            if (t._parar) break;
            atualizar(t, { status: etapa, progresso: { feitos, percentual: (100 * feitos) / (fontes.length * 3) } });
            await pausa(600);
            feitos++;
          }
          f.ultima_sincronizacao = isoHora(new Date());
          f.monitorada = !f.exige_presenca;
          if (!f.url) f.url = "https://www2.tjal.jus.br/sajcas/agendaAudiencias";
        }
        ultimaSincronizacao = isoHora(new Date());
        monitoramento.proxima = isoHora(new Date(Date.now() + monitoramento.intervalo_horas * 3600000));
        concluir(t, "concluida", {
          status: `${pauta.length} audiências conferidas · 1 alterada.`, progresso: { feitos, percentual: 100 },
          resultado: { novas: 0, atualizadas: 1, canceladas: 0, removidas: 0, total: pauta.length, alteracoes: 1, fontes: fontes.map((f) => ({ fonte: f.id, rotulo: f.rotulo })), erros: [], avisos: [] },
        });
        const futura = pauta.find((a) => a.data > iso(dia(2)) && a.situacao === "Designada");
        if (futura) {
          const antes = futura.hora;
          futura.hora = antes === "14:00" ? "15:00" : "14:00";
          alteracoes.unshift({ quando: isoHora(new Date()), tipo: "alterada", audiencia: futura, campos: [{ campo: "hora", antes, depois: futura.hora }], vista: false });
        }
        emitir("pauta", { tipo: "atualizada", dados: {} });
        emitir("pauta", { tipo: "alteracoes", dados: { novas: 1 } });
      })();
      return { tarefa: t.id };
    },
    "POST /api/pauta/capturar": ({ corpo }) => {
      const nome = `${corpo.sistema === "eproc" ? "eProc" : "e-SAJ"} (${corpo.tribunal})`;
      const t = novaTarefa("pauta_capturar", `Capturar a pauta no ${nome}`, 0);
      (async () => {
        atualizar(t, { status: "Abrindo o portal no navegador…" });
        await pausa(900);
        atualizar(t, { status: "Vá até a pauta de audiências e clique em “Capturar esta tela” na barra do Helestron." });
        await pausa(4200);
        if (t._parar) { concluir(t, "parada", { status: "Captura interrompida." }); return; }
        concluir(t, "concluida", {
          status: "Captura concluída: 12 audiências. O endereço ficou lembrado para o monitoramento.",
          resultado: { novas: 12, atualizadas: 0, capturadas: 12, telas: 2, url: "https://eproc1g.tjal.jus.br/eproc/controlador.php?acao=audiencia_listar", motivo: "concluida" },
        });
        emitir("pauta", { tipo: "atualizada", dados: {} });
      })();
      return { tarefa: t.id };
    },
    "POST /api/pauta/importar": () => {
      pautaImportada = true;
      emitir("estado", {});
      return { novas: 6, atualizadas: 2, ignoradas: 1, total: 8, arquivo: "Pauta de outubro.xlsx", avisos: ["Linha 14: data ilegível (“32/10/2026”); a linha foi ignorada."] };
    },
    "POST /api/pauta/exportar": ({ corpo }) => ({ arquivo: `${PASTAS.pauta}\\Pauta de audiências ${corpo.de} a ${corpo.ate}.xlsx`, pasta: PASTAS.pauta }),
    "GET /api/pauta/alteracoes": ({ consulta }) => alteracoes
      .filter((a) => !consulta.desde || a.quando >= consulta.desde)
      .map((a) => ({ quando: a.quando, tipo: a.tipo, audiencia: a.audiencia, campos: a.campos, vista: a.vista })),
    "POST /api/pauta/alteracoes/vistas": () => {
      alteracoes.forEach((a) => { a.vista = true; });
      emitir("estado", {});
      return {};
    },
    "POST /api/pauta/monitoramento": ({ corpo }) => {
      monitoramento = { ativo: !!corpo.ativo, intervalo_horas: Number(corpo.intervalo_horas) || 6, proxima: corpo.ativo ? isoHora(new Date(Date.now() + (Number(corpo.intervalo_horas) || 6) * 3600000)) : null };
      valores.pauta.monitorar = String(!!corpo.ativo);
      valores.pauta.intervalo_horas = String(monitoramento.intervalo_horas);
      return monitoramento;
    },
    "POST /api/pauta/baixar-autos": ({ corpo }) => {
      let lista = corpo.ids && corpo.ids.length ? pauta.filter((a) => corpo.ids.includes(a.id)) : filtrarPauta({ de: corpo.de, ate: corpo.ate });
      const numeros = Array.from(new Set(lista.map((a) => a.processo)));
      const nome = numeros.length === 1 ? `Pauta — ${numeros[0]}` : `Pauta ${corpo.de || ""} a ${corpo.ate || ""}`.trim();
      const t = novaTarefa("download", `Baixar os autos da pauta`, numeros.length);
      simularDownload(t, numeros, nome, {});
      return { tarefa: t.id };
    },

    // --------------------------------------------------------- compartilhar
    "GET /api/compartilhar/estado": () => ({
      claude: { claude_code: USUARIO + "\\.local\\bin\\claude.exe", desktop: true, mcp: true, chave_no_ambiente: false },
      chatgpt: { codex: "", app: true, mcp: codexConectado },
      chatgpt_desktop: true,
      tem_registrar_codex: true,
      nuvens: { "OneDrive (instituição)": USUARIO + "\\OneDrive - Tribunal de Justiça de Alagoas", "Google Drive": "G:\\Meu Drive" },
      mcp_acervo: true,
      acervo: { processos: 312, transcricoes: 47, preparado: isoHora(agoraMenos(60 * 26)) },
      pasta_acervo: PASTAS.acervo,
      sigilosos_no_acervo: SIGILO === "autos" ? NO_ACERVO.autos.arquivos.slice() : [],
      sigilosos_avisos: SIGILO === "arquivos" ? NO_ACERVO.arquivos.arquivos.slice() : [],
      sigilosos_mensagem: SIGILO === "autos" ? NO_ACERVO.autos.mensagem : "",
      sigilosos_avisos_mensagem: SIGILO === "arquivos" ? NO_ACERVO.arquivos.mensagem : "",
    }),
    "POST /api/compartilhar/preparar": () => {
      const t = novaTarefa("preparo", "Preparar o acervo para a IA", 312);
      (async () => {
        for (let i = 0; i <= 312; i += 26) {
          atualizar(t, { status: `Extraindo o texto dos autos (${i} de 312)…`, progresso: { feitos: i, percentual: (100 * i) / 312 } });
          await pausa(200);
        }
        if (SIGILO === "arquivos") {
          // O que o preparo conta (preparo.atualizar_contexto): a cópia que ele
          // levou para a pasta dos sigilosos e o arquivo que não pôde levar.
          const avisos = [
            `Processo ${PROCESSO_SIGILOSO}, em segredo de justiça: Produtos\\${PROCESSO_SIGILOSO}.docx foi levado para a pasta dos sigilosos (${PASTAS.sigilosos}\\Produtos\\${PROCESSO_SIGILOSO}.docx).`,
            NO_ACERVO.arquivos.mensagem,
          ];
          concluir(t, "concluida", { status: "312 processos, 47 transcrições, 1 arquivo de processo sigiloso ficou no acervo.", resultado: { resumo: "312 processos, 47 transcrições, 1 arquivo de processo sigiloso ficou no acervo", processos: 312, transcricoes: 47, erros: [], avisos } });
          return;
        }
        concluir(t, "concluida", { status: "Acervo pronto: 312 processos, 47 transcrições, índice e instruções atualizados.", resultado: { pasta: PASTAS.acervo, processos: 312, transcricoes: 47, erros: [], avisos: [] } });
      })();
      return { tarefa: t.id };
    },
    "POST /api/compartilhar/claude-desktop": () => ({ mensagem: "Conector do acervo registrado no Claude Desktop. Feche e abra o Claude Desktop para ele aparecer.", abriu: false }),
    "POST /api/compartilhar/cowork": () => ({
      abriu: true, resultado: "cowork", copiar: `Pasta do acervo: ${PASTAS.acervo}\n\n${PROMPT_INICIAL}`,
      mensagem: "Abrindo o Cowork. O Claude vai pedir para confirmar o acesso à pasta do acervo; depois, cole o pedido inicial (Ctrl+V).",
    }),
    "POST /api/compartilhar/claude-code": () => (SEM_CLAUDE_CODE ? {
      abriu: false, instalado: false, pagina_aberta: true, url: "https://docs.claude.com/pt-BR/docs/claude-code/overview",
      mensagem: "O Claude Code não está instalado neste computador. Abri no navegador a página oficial que explica como instalá-lo (sem administrador). Depois de instalar, clique de novo em “Abrir no Claude Code”.",
    } : { abriu: true, mensagem: "O Claude Code abriu numa janela própria, já na pasta do acervo. No primeiro uso, entre com a sua conta." }),
    "POST /api/compartilhar/chatgpt-work": () => ({
      abriu: true, resultado: "app", copiar: PASTAS.acervo,
      mensagem: "No app do ChatGPT, escolha Work, tecle Ctrl+O e cole o caminho do acervo (Ctrl+V). O ChatGPT lê o AGENTS.md da pasta.",
    }),
    // Como o servidor (api_compartilhar.codex): sem o Codex, o conector fica
    // registrado e a resposta é {abriu: false, mensagem} - nunca um erro -, com
    // os botões que existem na tela (C6).
    "POST /api/compartilhar/codex": () => {
      codexConectado = true;
      return {
        abriu: false,
        mensagem: `Conector de leitura do acervo registrado em ${USUARIO}\\.codex\\config.toml. O Codex (agente da OpenAI) não está instalado neste computador. Use “Abrir no ChatGPT Work” ou, no cartão “Pacote para o ChatGPT”, “Gerar o pacote”.`,
      };
    },
    "POST /api/compartilhar/pacote": () => {
      const t = novaTarefa("pacote", "Gerar o pacote para o ChatGPT", 0);
      (async () => {
        atualizar(t, { status: "Copiando os autos e os textos…" });
        await pausa(1200);
        atualizar(t, { status: "Compactando…" });
        await pausa(900);
        concluir(t, "concluida", { status: "Pacote pronto (186 MB). Os sigilosos ficaram de fora.", resultado: { pasta: DOCS + "\\Pacotes para IA", arquivo: DOCS + "\\Pacotes para IA\\Acervo para o ChatGPT.zip" } });
      })();
      return { tarefa: t.id };
    },
    "GET /api/compartilhar/nuvem": () => [
      { rotulo: "OneDrive (instituição)", caminho: USUARIO + "\\OneDrive - Tribunal de Justiça de Alagoas" },
      { rotulo: "Google Drive", caminho: "G:\\Meu Drive" },
    ],
    "POST /api/compartilhar/nuvem/espelhar": ({ corpo }) => {
      const t = novaTarefa("nuvem", "Espelhar o acervo na nuvem", 100);
      (async () => {
        for (let p = 0; p <= 100; p += 20) {
          atualizar(t, { status: `Copiando o que mudou (${p}%)…`, progresso: { feitos: p, percentual: p } });
          await pausa(300);
        }
        concluir(t, "concluida", { status: "Espelho em dia: 14 arquivos novos ou alterados.", resultado: { pasta: corpo.destino } });
      })();
      return { tarefa: t.id };
    },
    "GET /api/compartilhar/prompt": () => ({ texto: `Pasta do acervo: ${PASTAS.acervo}\n\n${PROMPT_INICIAL}` }),

    // ------------------------------------------------------------ autoteste
    "POST /api/autoteste/passo": () => ({}),
    "POST /api/autoteste/fim": () => ({}),
  };

  // Registro das chamadas (os testes da interface conferem o que a tela pediu).
  const chamadas = [];

  /** Os campos de um envio multipart; o arquivo vira {nome, tamanho}. */
  function camposDoFormulario(fd) {
    const campos = {};
    for (const [k, v] of fd.entries()) campos[k] = typeof v === "string" ? v : { nome: v.name, tamanho: v.size };
    return campos;
  }

  async function responder(rota, pedido) {
    const fn = ROTAS[rota];
    const corpo = pedido.corpo !== undefined ? pedido.corpo : pedido.formulario ? camposDoFormulario(pedido.formulario) : null;
    chamadas.push({ rota, params: pedido.params, corpo, multipart: !!pedido.formulario });
    if (chamadas.length > 500) chamadas.splice(0, 100);
    await atraso();
    if (!fn) throw new H.api.ErroApi("nao_encontrado", "Esta função não existe na demonstração.", rota, 404);
    exigirSemSigiloso(rota);
    // Cópia profunda: a tela não pode mexer nos dados guardados aqui.
    const r = await fn(pedido);
    return r === undefined ? {} : JSON.parse(JSON.stringify(r));
  }

  function ligarEventos(fn) {
    emitir = fn;
    setInterval(() => emitir("ping", {}), 15000);
  }

  H.demo = { responder, ligarEventos, rotas: Object.keys(ROTAS), chamadas, ativo: true };
})();
