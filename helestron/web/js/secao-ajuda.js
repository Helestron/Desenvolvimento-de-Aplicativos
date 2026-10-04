/* Helestron — Ajuda (especificação 7.2).
 *
 * "Como fazer" de cada função, perguntas frequentes e atalhos de teclado,
 * com busca que ignora acentos e maiúsculas e marca o trecho encontrado.
 * O conteúdo é o do manual (docs/MANUAL.md), em versão curta para a tela.
 */
(function () {
  "use strict";

  const H = window.Helestron;
  const { el, icone, botao, cartao, vazio, trocar, blocoIcone } = H.ui;

  const GUIAS = [
    {
      id: "baixar", icone: "doc-baixar", cor: "navy", titulo: "Baixar processos", rota: "processos",
      passos: [
        "Abra Processos e arraste a relação para a tela — ou clique em Escolher arquivo, Colar lista ou Link.",
        "Confira a revisão: o tribunal e o sistema saem do próprio número; números com dígito errado ou corrompidos pelo Excel aparecem à parte.",
        "Dê um nome ao lote (vira o nome da pasta) e confira as opções.",
        "Clique em Baixar. Se o portal pedir o código de verificação, uma janela pede que você o digite.",
      ],
      nota: "Sai um PDF por processo, com o número como nome, em Acervo\\Processos\\<nome do lote>. O relatório fica em _controle\\relatorio.csv.",
    },
    {
      id: "transcrever", icone: "microfone", cor: "azul", titulo: "Transcrever uma audiência", rota: "audiencias",
      passos: [
        "Em Audiências, informe o número do processo — ou clique numa audiência de hoje, sugerida pela pauta.",
        "Escolha o microfone e clique em Testar: as barras do medidor devem se mexer quando você fala.",
        "Confira os nomes dos participantes (teclas F1 a F8) e, se for o caso, ligue Segredo de justiça.",
        "Clique no botão vermelho. Durante a audiência, use F1 a F8 para indicar quem está falando.",
        "No fim, clique em Encerrar: o documento do Word é salvo com o número do processo como nome.",
      ],
      nota: "Tudo roda no computador, sem internet. O documento é salvo sozinho a cada poucos segundos.",
    },
    {
      id: "pauta", icone: "calendario", cor: "ciano", titulo: "Acompanhar a pauta", rota: "pauta",
      passos: [
        "Cadastre o acesso ao e-SAJ ou ao eProc em Ajustes › Acessos aos portais.",
        "Na Pauta, clique em Sincronizar e escolha o portal: o Helestron entra, encontra a pauta de audiências e a traz.",
        "Se a pauta do tribunal fica numa tela própria, use Capturar no portal: vá até a tela e clique em “Capturar esta tela” na barra do Helestron.",
        "Deixe o Monitoramento ligado: a pauta é conferida sozinha, e o que mudar aparece em Alterações recentes e no selo da barra lateral.",
      ],
      nota: "Também dá para importar o relatório de audiências exportado do SAJ ou do eProc (planilha, PDF ou HTML).",
    },
    {
      id: "excel", icone: "planilha", cor: "celeste", titulo: "Exportar a pauta para o Excel", rota: "pauta",
      passos: [
        "Na Pauta, escolha o período e, se quiser, filtre por sistema, situação ou busca.",
        "Clique em Exportar Excel, confira as datas e clique em Exportar.",
        "Abra a planilha pelo aviso que aparece no canto da tela.",
      ],
      nota: "A planilha tem as abas Pauta, Resumo e Alterações e fica em Documentos\\Helestron\\Pauta, fora do acervo da IA. As partes dos processos sigilosos saem como “(segredo de justiça)”, salvo se você pedir o contrário.",
    },
    {
      id: "ia", icone: "brilho", cor: "cobalto", titulo: "Compartilhar com a IA", rota: "compartilhar",
      passos: [
        "Em Compartilhar, clique em Preparar acervo para a IA: o texto dos autos, o índice e as regras de trabalho ficam prontos.",
        "Escolha onde trabalhar: Claude Code, Claude Cowork, ChatGPT Work ou Codex.",
        "Use Copiar pedido inicial e cole na conversa para a IA começar pelas instruções do acervo.",
      ],
      nota: "A IA indica a fonte de cada informação: a folha, no e-SAJ, ou o evento e o documento, no eProc.",
    },
    {
      id: "sigilo", icone: "cadeado", cor: "ardosia", titulo: "Processos em segredo de justiça", rota: "ajustes/pastas",
      passos: [
        "Com Separar os sigilosos ligado (o padrão), o processo sigiloso baixado vai para a pasta dos sigilosos, fora do acervo.",
        "Na audiência de processo sigiloso, ligue Segredo de justiça: a transcrição e a gravação também vão para lá.",
        "Nada da pasta dos sigilosos vai para a IA, para o pacote, para a nuvem ou para o índice.",
      ],
      nota: "O relatório do lote que fica no acervo não identifica os sigilosos; o completo fica na pasta dos sigilosos.",
    },
  ];

  const PERGUNTAS = [
    { p: "O portal pediu um código. Onde eu digito?", r: ["Numa janela do próprio Helestron, que aparece sozinha: o código enviado por e-mail, no e-SAJ, ou o código do aplicativo autenticador, no eProc. Se você estiver em outro programa, o Helestron pisca na barra de tarefas; aberto no Edge ou no navegador, o título da aba alterna até você responder. No e-SAJ, se o código não chegar, use “Pedir novo código”."] },
    { p: "Posso fechar a janela durante o download?", r: ["Melhor não: fechar a janela encerra o Helestron e interrompe o download. O que já foi baixado fica na pasta; o que faltou é baixado quando você usar a mesma relação de novo — o que já existe é pulado."] },
    { p: "O download parou num processo. E agora?", r: ["Confira a situação na lista do andamento: “Sem acesso” e “Não encontrado” costumam ser senha errada ou processo de outro sistema. Se o portal mudou, o Helestron guarda uma imagem e o HTML da tela em Logs\\diagnostico — envie-os ao suporte.", "Senha trocada no portal? Atualize em Ajustes › Acessos aos portais."] },
    { p: "O que acontece com os processos em segredo de justiça?", r: ["Ficam na pasta dos sigilosos, fora do acervo. Nunca vão para a IA, para o pacote do ChatGPT, para o espelho na nuvem nem para o índice. A transcrição de audiência sigilosa também vai para lá, com a gravação."] },
    { p: "O medidor do microfone não se mexe.", r: ["Clique em Testar e fale perto do microfone. Se as barras continuarem paradas, confira se o microfone certo está escolhido e se o Windows permite o acesso: Configurações › Privacidade e segurança › Microfone › “Permitir que aplicativos da área de trabalho acessem o microfone”."] },
    { p: "A transcrição está atrasada em relação à fala.", r: ["Nada se perde: o áudio é gravado e a fila é transcrita. Para a próxima audiência, escolha o modelo “base” em Ajustes › Transcrição, ou feche programas pesados durante a audiência."] },
    { p: "O computador desligou no meio da audiência.", r: ["Abra o Helestron e vá a Audiências: aparece o aviso de transcrição interrompida, com o botão Recuperar. O que já tinha sido transcrito volta para o documento, e a gravação é reparada."] },
    { p: "Como mudo os nomes dos botões F1 a F8?", r: ["Na preparação da audiência, edite os nomes dos participantes: eles ficam guardados para as próximas. Também dá para mudar em Ajustes › Transcrição."] },
    { p: "A sincronização não trouxe a pauta.", r: ["Alguns tribunais mostram a pauta numa tela própria. Use Capturar no portal: o navegador abre já com o seu acesso; vá até a pauta e clique em “Capturar esta tela”, em cada página. Ao concluir, o endereço fica lembrado e o monitoramento passa a usá-lo.", "Outra saída é exportar o relatório de audiências no portal e usar Importar relatório."] },
    { p: "O monitoramento pediu para eu entrar no portal.", r: ["O portal pediu um código de verificação enquanto o Helestron conferia a pauta sozinho. Clique em Sincronizar, digite o código quando ele chegar, e o monitoramento continua normalmente."] },
    { p: "Onde ficam os meus arquivos?", r: ["Em Documentos\\Helestron: Acervo (Processos e Transcricoes, compartilhados com a IA), Sigilosos (nunca compartilhados) e Pauta (planilhas exportadas). Se a pasta Documentos estiver no OneDrive, a base passa a ser a pasta do seu usuário, para a sincronização não travar arquivos em uso. Tudo pode ser mudado em Ajustes › Pastas."] },
    { p: "Preciso de internet?", r: ["Para baixar processos, sincronizar a pauta e usar a IA, sim. A transcrição de audiências funciona sem internet: o modelo vem com o instalador e roda no próprio computador."] },
    { p: "Onde ficam as minhas senhas?", r: ["No arquivo de credenciais do Helestron, cifradas pelo Windows (DPAPI): só a sua conta, neste computador, consegue lê-las. Elas só são usadas para entrar nos portais."] },
    { p: "Algo parou de funcionar depois de uma atualização do Windows.", r: ["Abra Ajustes › Sobre e diagnóstico e clique em Verificar a instalação. Se apontar falha, rode o instalador do Helestron de novo: ele refaz o programa sem tocar nos seus arquivos nem nas suas configurações."] },
    { p: "Como desinstalo o Helestron?", r: ["Em Configurações do Windows › Aplicativos › Aplicativos instalados › Helestron › Desinstalar. O desinstalador pergunta se você quer apagar também as configurações e as senhas; a pasta Documentos\\Helestron nunca é apagada."] },
    { p: "A IA pode decidir por mim?", r: ["Não. O Helestron é ferramenta de apoio: autos baixados, transcrições, resumos e minutas são material de trabalho para conferência e decisão do magistrado (Resolução CNJ nº 615/2025)."] },
  ];

  const ATALHOS = [
    [["Ctrl", "1"], "Início"], [["Ctrl", "2"], "Processos"], [["Ctrl", "3"], "Audiências"], [["Ctrl", "4"], "Pauta"],
    [["Ctrl", "5"], "Compartilhar"], [["Ctrl", "6"], "Ajustes"], [["Ctrl", "7"], "Ajuda"],
    [["F1", "…", "F8"], "Quem está falando, durante a audiência"], [["Ctrl", "Enter"], "Começar a gravar a audiência"],
    [["Ctrl", "V"], "Colar a lista de processos, em Processos"], [["Esc"], "Fechar a janela de diálogo"],
  ];

  // ------------------------------------------------------------ busca
  /** Texto com o termo marcado (<mark>), sem considerar acento nem caixa. */
  function marcar(texto, termo) {
    if (!termo) return [texto];
    const alvo = H.normalizar(termo);
    // Mapa: posição no texto normalizado → posição no original (os acentos somem na normalização).
    let norm = "";
    const mapa = [];
    for (let i = 0; i < texto.length; i++) {
      const n = H.normalizar(texto[i]);
      for (let k = 0; k < n.length; k++) { norm += n[k]; mapa.push(i); }
    }
    const partes = [];
    let desde = 0;
    let i = norm.indexOf(alvo);
    while (i >= 0 && alvo) {
      const ini = mapa[i], fim = mapa[i + alvo.length - 1] + 1;
      if (ini > desde) partes.push(texto.slice(desde, ini));
      partes.push(el("mark", { texto: texto.slice(ini, fim) }));
      desde = fim;
      i = norm.indexOf(alvo, i + alvo.length);
    }
    if (desde < texto.length) partes.push(texto.slice(desde));
    return partes;
  }

  function contem(textos, termo) {
    if (!termo) return true;
    const alvo = H.normalizar(termo);
    return textos.some((t) => H.normalizar(t).includes(alvo));
  }

  H.secoes = H.secoes || {};
  H.secoes.ajuda = {
    async montar(ctx) {
      const raiz = ctx.raiz;
      const campo = el("input", { type: "search", classe: "campo", id: "busca-ajuda", placeholder: "Buscar na ajuda — por exemplo, “código”, “sigiloso”, “Excel”", aria: { label: "Buscar na ajuda" }, autocomplete: "off" });
      const cab = H.ui.cabecalho({
        titulo: "Ajuda",
        subtitulo: "Como fazer cada coisa, as dúvidas mais comuns e os atalhos de teclado.",
      });
      const resultado = el("div", { "aria-live": "polite" });
      raiz.append(cab, el("div", { classe: "busca ajuda-busca" }, icone("busca"), campo), resultado);

      const desenhar = () => {
        const termo = campo.value.trim();
        const guias = GUIAS.filter((g) => contem([g.titulo, g.nota].concat(g.passos), termo));
        const perguntas = PERGUNTAS.filter((q) => contem([q.p].concat(q.r), termo));
        const atalhos = ATALHOS.filter(([teclas, o]) => contem([o, teclas.join(" ")], termo));
        const blocos = [];
        if (guias.length) {
          blocos.push(el("h2", { classe: "secao-titulo", estilo: { marginTop: "4px" }, texto: "Como fazer" }),
            el("div", { classe: "guias" }, guias.map((g) => cartao({ classe: "guia", tag: "article", id: "guia-" + g.id },
              el("div", { classe: "guia-topo" }, blocoIcone(g.icone, g.cor),
                el("h3", { classe: "guia-titulo" }, marcar(g.titulo, termo)),
                el("span", { estilo: { marginLeft: "auto" } }, botao({ rotulo: "Abrir", tipo: "texto", tamanho: "pequeno", acao: () => H.app.ir(g.rota) }))),
              el("ol", {}, g.passos.map((p) => el("li", {}, marcar(p, termo)))),
              el("p", { classe: "guia-nota" }, marcar(g.nota, termo))))));
        }
        if (perguntas.length) {
          blocos.push(el("h2", { classe: "secao-titulo", texto: "Perguntas frequentes" }),
            cartao({ classe: "perguntas", estilo: { padding: "4px 0" } }, perguntas.map((q) => {
              const d = el("details", { classe: "pergunta-frequente" },
                el("summary", {}, el("span", {}, marcar(q.p, termo)), icone("chevron-baixo")),
                el("div", { classe: "pergunta-resposta" }, q.r.map((t) => el("p", {}, marcar(t, termo)))));
              if (termo) d.open = true;
              return d;
            })));
        }
        if (atalhos.length) {
          blocos.push(el("h2", { classe: "secao-titulo", texto: "Atalhos de teclado" }),
            cartao({ classe: "atalhos-cartao" }, el("div", { classe: "atalhos" }, atalhos.map(([teclas, o]) =>
              el("div", { classe: "atalho" }, el("span", {}, marcar(o, termo)),
                el("span", { classe: "atalho-teclas" }, teclas.map((t) => (t === "…" ? el("span", { texto: "a" }) : el("kbd", { classe: "tecla", texto: t })))))))));
        }
        if (!blocos.length) {
          blocos.push(cartao({}, vazio({
            icone: "busca", titulo: `Nada encontrado para “${termo}”`,
            texto: "Tente outra palavra — por exemplo, “pauta”, “microfone” ou “senha”.",
            acoes: [botao({ rotulo: "Limpar a busca", tipo: "tonal", acao: () => { campo.value = ""; desenhar(); campo.focus(); } })],
          })));
        }
        trocar(resultado, blocos);
      };
      campo.addEventListener("input", H.ui.debounce(desenhar, 120));
      desenhar();
    },
  };
})();
