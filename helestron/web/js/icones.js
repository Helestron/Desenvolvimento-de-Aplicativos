/* Helestron — ícones da interface.
 *
 * Desenho próprio, no espírito dos SF Symbols: grade de 24 px, traço de
 * 1,75 px com pontas e junções arredondadas (o traço, a cor e a espessura vêm
 * do CSS, classe .icone). Ficam todos num "sprite" embutido no documento, e
 * cada ícone é um <svg><use href="#i-nome"></svg>: nenhum arquivo a mais para
 * baixar, nada que possa faltar na instalação, e a cor acompanha o texto
 * (currentColor).
 *
 * Por que em JavaScript e não num .svg separado: o <use> com arquivo externo
 * depende do servidor entregar o tipo certo, e um ícone faltando deixaria um
 * buraco no botão. Aqui, se o script carregou, todos os ícones existem.
 */
(function () {
  "use strict";

  const ICONES = {
    // ---------------------------------------------------------- navegação
    casa: '<path d="M3.2 11.2 12 3.8l8.8 7.4"/><path d="M5.6 9.4V19a1.6 1.6 0 0 0 1.6 1.6h3.1v-5.4a.8.8 0 0 1 .8-.8h1.8a.8.8 0 0 1 .8.8v5.4h3.1a1.6 1.6 0 0 0 1.6-1.6V9.4"/>',
    "doc-baixar": '<path d="M14 3.2H7.6A2.6 2.6 0 0 0 5 5.8v12.4a2.6 2.6 0 0 0 2.6 2.6h8.8a2.6 2.6 0 0 0 2.6-2.6V8.2z"/><path d="M14 3.2v3.4a1.6 1.6 0 0 0 1.6 1.6H19"/><path d="M12 10.8v6.4M9.4 14.7l2.6 2.6 2.6-2.6"/>',
    microfone: '<rect x="9" y="3" width="6" height="11.2" rx="3"/><path d="M5.6 11a6.4 6.4 0 0 0 12.8 0M12 17.4v3.4M9.2 20.8h5.6"/>',
    calendario: '<rect x="3.6" y="5" width="16.8" height="15.6" rx="3.2"/><path d="M3.6 9.6h16.8M8.2 3v3.6M15.8 3v3.6"/><path d="M8 13.4h.01M12 13.4h.01M16 13.4h.01M8 17h.01M12 17h.01" stroke-width="2.3"/>',
    compartilhar: '<path d="M12 3.2v11.6M8.2 6.8 12 3.2l3.8 3.6"/><path d="M8.6 9.8H7.4a2.4 2.4 0 0 0-2.4 2.4v6.2a2.4 2.4 0 0 0 2.4 2.4h9.2a2.4 2.4 0 0 0 2.4-2.4v-6.2a2.4 2.4 0 0 0-2.4-2.4h-1.2"/>',
    engrenagem: '<path d="M19.06 10.37 21.4 10.6v2.8l-2.34.23-.91 2.21 1.49 1.81-1.99 1.99-1.81-1.49-2.21.91-.23 2.34h-2.8l-.23-2.34-2.21-.91-1.81 1.49-1.99-1.99 1.49-1.81-.91-2.21L2.6 13.4v-2.8l2.34-.23.91-2.21-1.49-1.81 1.99-1.99 1.81 1.49 2.21-.91.23-2.34h2.8l.23 2.34 2.21.91 1.81-1.49 1.99 1.99-1.49 1.81z"/><circle cx="12" cy="12" r="3.1"/>',
    ajuda: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.4a2.6 2.6 0 0 1 5 .9c0 1.8-2.5 2.3-2.5 3.9"/><path d="M12 17.1h.01" stroke-width="2.3"/>',

    // ------------------------------------------------------------- ações
    busca: '<circle cx="10.8" cy="10.8" r="6.6"/><path d="m20 20-4.4-4.4"/>',
    mais: '<path d="M12 5v14M5 12h14"/>',
    menos: '<path d="M5 12h14"/>',
    "chevron-direita": '<path d="m9.5 5.8 6.2 6.2-6.2 6.2"/>',
    "chevron-esquerda": '<path d="m14.5 5.8-6.2 6.2 6.2 6.2"/>',
    "chevron-baixo": '<path d="m5.8 9.5 6.2 6.2 6.2-6.2"/>',
    "chevron-cima": '<path d="m5.8 14.5 6.2-6.2 6.2 6.2"/>',
    check: '<path d="m5 12.6 4.6 4.6L19 7.6"/>',
    "check-circulo": '<circle cx="12" cy="12" r="9"/><path d="m8 12.4 2.8 2.8 5.3-5.6"/>',
    x: '<path d="m6.6 6.6 10.8 10.8M17.4 6.6 6.6 17.4"/>',
    "x-circulo": '<circle cx="12" cy="12" r="9"/><path d="m9.2 9.2 5.6 5.6M14.8 9.2l-5.6 5.6"/>',
    circulo: '<circle cx="12" cy="12" r="9"/>',
    aviso: '<path d="M10.3 4.3a2 2 0 0 1 3.4 0l7.5 13.1a2 2 0 0 1-1.7 3H4.5a2 2 0 0 1-1.7-3z"/><path d="M12 9.4v4.4"/><path d="M12 17.1h.01" stroke-width="2.3"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.4"/><path d="M12 7.7h.01" stroke-width="2.4"/>',
    pasta: '<path d="M3.4 7.6A2.6 2.6 0 0 1 6 5h3.4c.5 0 1 .2 1.3.6l1.3 1.6H18a2.6 2.6 0 0 1 2.6 2.6v7.6A2.6 2.6 0 0 1 18 20H6a2.6 2.6 0 0 1-2.6-2.6z"/><path d="M3.4 10.2h17.2"/>',
    documento: '<path d="M14 3.2H7.6A2.6 2.6 0 0 0 5 5.8v12.4a2.6 2.6 0 0 0 2.6 2.6h8.8a2.6 2.6 0 0 0 2.6-2.6V8.2z"/><path d="M14 3.2v3.4a1.6 1.6 0 0 0 1.6 1.6H19"/><path d="M8.8 12.4h6.4M8.8 16h4.2"/>',
    bandeja: '<path d="M12 3.4v10.2M8.2 9.8l3.8 3.8 3.8-3.8"/><path d="M3.8 13.6v3.6a2.8 2.8 0 0 0 2.8 2.8h10.8a2.8 2.8 0 0 0 2.8-2.8v-3.6"/>',
    colar: '<rect x="5" y="4.6" width="14" height="16.4" rx="2.6"/><path d="M9.2 3.2h5.6a.8.8 0 0 1 .8.8v1.2a1.4 1.4 0 0 1-1.4 1.4h-4.4a1.4 1.4 0 0 1-1.4-1.4V4a.8.8 0 0 1 .8-.8z"/><path d="M8.8 11h6.4M8.8 14.4h6.4M8.8 17.8h3.6"/>',
    link: '<path d="M10.2 13.8a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M13.8 10.2a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    copiar: '<rect x="8.6" y="8.6" width="12" height="12" rx="2.6"/><path d="M15.4 8.6V6a2.6 2.6 0 0 0-2.6-2.6H6A2.6 2.6 0 0 0 3.4 6v6.8A2.6 2.6 0 0 0 6 15.4h2.6"/>',
    parar: '<rect x="6.2" y="6.2" width="11.6" height="11.6" rx="2.6" fill="currentColor" stroke="none"/>',
    pausa: '<rect x="6.8" y="5.4" width="3.6" height="13.2" rx="1.3" fill="currentColor" stroke="none"/><rect x="13.6" y="5.4" width="3.6" height="13.2" rx="1.3" fill="currentColor" stroke="none"/>',
    tocar: '<path d="M8 6.1v11.8a1.1 1.1 0 0 0 1.7.9l9.3-5.9a1.1 1.1 0 0 0 0-1.8L9.7 5.2A1.1 1.1 0 0 0 8 6.1z" fill="currentColor" stroke="none"/>',
    gravar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.6" fill="currentColor" stroke="none"/>',
    relogio: '<circle cx="12" cy="12" r="9"/><path d="M12 7.2V12l3.2 2"/>',
    pessoa: '<circle cx="12" cy="8.2" r="3.8"/><path d="M4.8 20.2a7.2 7.2 0 0 1 14.4 0"/>',
    pessoas: '<circle cx="9" cy="8.4" r="3.4"/><path d="M2.8 19.6a6.2 6.2 0 0 1 12.4 0"/><path d="M15.4 5.2a3.4 3.4 0 0 1 0 6.4M17.4 13.8a6.2 6.2 0 0 1 3.8 5.8"/>',
    cadeado: '<rect x="5" y="10.4" width="14" height="10.2" rx="2.6"/><path d="M8 10.4V7.6a4 4 0 0 1 8 0v2.8"/><path d="M12 14.4v2.2"/>',
    sincronizar: '<path d="M4.6 11.2a7.4 7.4 0 0 1 13-4.4l1.8 1.9"/><path d="M19.4 4.2v4.5h-4.5"/><path d="M19.4 12.8a7.4 7.4 0 0 1-13 4.4l-1.8-1.9"/><path d="M4.6 19.8v-4.5h4.5"/>',
    planilha: '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="2.8"/><path d="M3.4 9.4h17.2M3.4 14.4h17.2M9.4 9.4v10.2"/>',
    importar: '<path d="M12 3.2v11M8.2 10.4l3.8 3.8 3.8-3.8"/><path d="M8.6 7.6H7.4A2.4 2.4 0 0 0 5 10v8.2a2.4 2.4 0 0 0 2.4 2.4h9.2a2.4 2.4 0 0 0 2.4-2.4V10a2.4 2.4 0 0 0-2.4-2.4h-1.2"/>',
    capturar: '<path d="M4 8.6V6.6A2.6 2.6 0 0 1 6.6 4h2M15.4 4h2A2.6 2.6 0 0 1 20 6.6v2M20 15.4v2a2.6 2.6 0 0 1-2.6 2.6h-2M8.6 20h-2A2.6 2.6 0 0 1 4 17.4v-2"/><circle cx="12" cy="12" r="3.2"/>',
    sino: '<path d="M6 16.4V11a6 6 0 0 1 12 0v5.4l1.6 2.1H4.4z"/><path d="M10 20.6a2.1 2.1 0 0 0 4 0"/>',
    terminal: '<rect x="3" y="4.4" width="18" height="15.2" rx="3"/><path d="m7.4 9.8 2.6 2.3-2.6 2.3M12.6 14.8h4"/>',
    conversa: '<path d="M20 11.4c0 4.1-3.6 7.4-8 7.4a8.8 8.8 0 0 1-3.3-.6L4 19.8l1.4-3.7A7 7 0 0 1 4 11.4C4 7.3 7.6 4 12 4s8 3.3 8 7.4z"/>',
    computador: '<rect x="3" y="4" width="18" height="12.6" rx="2.6"/><path d="M8.8 20.4h6.4M12 16.6v3.8"/>',
    nuvem: '<path d="M7.2 19a4.6 4.6 0 0 1-.7-9.1 6 6 0 0 1 11.5-.8A5 5 0 0 1 17.4 19z"/>',
    pacote: '<path d="M12 3.2 4 7.2v9.6l8 4 8-4V7.2z"/><path d="M4.2 7.3 12 11.2l7.8-3.9M12 11.2v9.4M8 5.2l7.8 4"/>',
    codigo: '<path d="m8.4 7.4-4.8 4.6 4.8 4.6M15.6 7.4l4.8 4.6-4.8 4.6M13.6 4.8l-3.2 14.4"/>',
    brilho: '<path d="M11 3.6c.5 3.9 2.6 6 6.6 6.6-4 .5-6.1 2.6-6.6 6.6-.5-4-2.6-6.1-6.6-6.6 4-.6 6.1-2.7 6.6-6.6z"/><path d="M18.2 14.6c.2 1.5 1 2.3 2.4 2.5-1.4.2-2.2 1-2.4 2.5-.2-1.5-1-2.3-2.5-2.5 1.5-.2 2.3-1 2.5-2.5z"/>',
    chave: '<circle cx="8" cy="15.4" r="4.2"/><path d="m11 12.4 8.4-8.4M16 7.4l2.6 2.6M13.6 9.8l1.9 1.9"/>',
    predio: '<path d="M3.4 9.2 12 4.2l8.6 5z"/><path d="M5.8 9.6v7.8M9.9 9.6v7.8M14.1 9.6v7.8M18.2 9.6v7.8M3.6 20.6h16.8M4.6 17.4h14.8"/>',
    ondas: '<path d="M3.6 12h.8M7 9v6M10.4 5.4v13.2M13.8 8v8M17.2 10v4M20.4 12h.1"/>',
    lixeira: '<path d="M4.4 6.6h15.2M9.4 6.6V5a1.6 1.6 0 0 1 1.6-1.6h2A1.6 1.6 0 0 1 14.6 5v1.6M6.4 6.6l.8 12.1a2 2 0 0 0 2 1.9h5.6a2 2 0 0 0 2-1.9l.8-12.1M10 10.6v5.8M14 10.6v5.8"/>',
    olho: '<path d="M2.6 12S6 5.6 12 5.6 21.4 12 21.4 12 18 18.4 12 18.4 2.6 12 2.6 12z"/><circle cx="12" cy="12" r="3"/>',
    video: '<rect x="3" y="6.4" width="12.6" height="11.2" rx="2.6"/><path d="m15.6 10.4 4.3-2.6a.7.7 0 0 1 1.1.6v7.2a.7.7 0 0 1-1.1.6l-4.3-2.6z"/>',
    local: '<path d="M12 21s-6.6-5.6-6.6-11a6.6 6.6 0 0 1 13.2 0c0 5.4-6.6 11-6.6 11z"/><circle cx="12" cy="10" r="2.5"/>',
    filtro: '<path d="M4 7h16M7 12h10M10 17h4"/>',
    lista: '<path d="M9 6.6h11M9 12h11M9 17.4h11"/><path d="M4.6 6.6h.01M4.6 12h.01M4.6 17.4h.01" stroke-width="2.4"/>',
    livro: '<path d="M12 6.6C10.4 5 8.2 4.4 3.8 4.4v14c4.4 0 6.6.6 8.2 2.2 1.6-1.6 3.8-2.2 8.2-2.2v-14c-4.4 0-6.6.6-8.2 2.2z"/><path d="M12 6.6v14"/>',
    raio: '<path d="M13.2 3 5.6 13.4H12l-1.2 7.6 7.6-10.4H12z"/>',
    recuperar: '<path d="M4.6 12a7.4 7.4 0 1 0 2.2-5.2L4.6 9"/><path d="M4.6 4.4V9h4.6"/>',
    externo: '<path d="M13.6 4.4h6v6M19.6 4.4l-8.4 8.4"/><path d="M17.6 13.6v3.8a2.6 2.6 0 0 1-2.6 2.6H7a2.6 2.6 0 0 1-2.6-2.6v-8A2.6 2.6 0 0 1 7 6.8h3.8"/>',
    texto: '<path d="M4 6h16M4 10h11M4 14h16M4 18h9"/>',
    teclado: '<rect x="2.6" y="6" width="18.8" height="12" rx="2.6"/><path d="M6.4 10h.01M9.8 10h.01M13.2 10h.01M16.6 10h.01" stroke-width="2.2"/><path d="M8 14.4h8"/>',
    chip: '<rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.2"/><rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1"/><path d="M9.6 3.4v3M14.4 3.4v3M9.6 17.6v3M14.4 17.6v3M3.4 9.6h3M3.4 14.4h3M17.6 9.6h3M17.6 14.4h3"/>',
    baixar: '<circle cx="12" cy="12" r="9"/><path d="M12 7.4v8.4M8.6 12.6 12 16l3.4-3.4"/>',
    envelope: '<rect x="3" y="5.4" width="18" height="13.2" rx="2.6"/><path d="m3.6 7.2 8.4 6 8.4-6"/>',
    celular: '<rect x="6.4" y="2.8" width="11.2" height="18.4" rx="2.8"/><path d="M10.8 18h2.4"/>',
    reticencias: '<path d="M6 12h.01M12 12h.01M18 12h.01" stroke-width="2.6"/>',
    "seta-direita": '<path d="M4.8 12h14.4M13.4 6.2l5.8 5.8-5.8 5.8"/>',
    energia: '<path d="M12 3.4v8"/><path d="M7.2 6.2a7.4 7.4 0 1 0 9.6 0"/>',
    escudo: '<path d="M12 3.2 5 5.9v5.3c0 4.4 2.9 8.2 7 9.6 4.1-1.4 7-5.2 7-9.6V5.9z"/><path d="m9.2 12.1 2 2 3.8-4"/>',
    lapis: '<path d="M15.6 4.6a2.2 2.2 0 0 1 3.1 0l.7.7a2.2 2.2 0 0 1 0 3.1L9 18.8l-4.6 1 1-4.6z"/><path d="m13.8 6.4 3.8 3.8"/>',
    martelo: '<path d="m13.6 3.8 6.6 6.6M11.4 6l6.6 6.6M15.8 6.2l-4.2 4.2M12.6 9.4 4.2 17.8a1.6 1.6 0 0 0 2.3 2.3l8.4-8.4"/>',
    alvo: '<circle cx="12" cy="12" r="8.6"/><circle cx="12" cy="12" r="4.6"/><circle cx="12" cy="12" r="1" fill="currentColor"/>',
    grafico: '<path d="M4 20V4M4 20h16"/><path d="M8 16v-4M12 16V8M16 16v-6"/>',
    ampulheta: '<path d="M6.6 3.6h10.8M6.6 20.4h10.8M7.6 3.6c0 4.8 4.4 5.6 4.4 8.4S7.6 15.6 7.6 20.4M16.4 3.6c0 4.8-4.4 5.6-4.4 8.4s4.4 3.6 4.4 8.4"/>',
  };

  const NS = "http://www.w3.org/2000/svg";

  /** Põe o sprite no documento (uma vez só). */
  function instalar() {
    if (document.getElementById("helestron-icones")) return;
    const sprite = document.createElementNS(NS, "svg");
    sprite.setAttribute("id", "helestron-icones");
    sprite.setAttribute("aria-hidden", "true");
    sprite.setAttribute("style", "position:absolute;width:0;height:0;overflow:hidden");
    sprite.innerHTML = Object.entries(ICONES)
      .map(([nome, corpo]) => `<symbol id="i-${nome}" viewBox="0 0 24 24">${corpo}</symbol>`)
      .join("");
    document.body.prepend(sprite);
  }

  /**
   * Um ícone pronto para pôr na página.
   * 'rotulo' (opcional) torna o ícone legível pelo leitor de tela; sem ele,
   * o ícone é decorativo (aria-hidden), e o texto ao lado diz o que é.
   */
  function icone(nome, opcoes = {}) {
    if (!ICONES[nome]) {
      // Nome errado é defeito do programa: avisa no console, mas não quebra a tela.
      console.warn("Ícone desconhecido:", nome);
      nome = "circulo";
    }
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "icone" + (opcoes.classe ? " " + opcoes.classe : ""));
    svg.setAttribute("viewBox", "0 0 24 24");
    if (opcoes.tamanho) {
      svg.setAttribute("width", opcoes.tamanho);
      svg.setAttribute("height", opcoes.tamanho);
    }
    if (opcoes.rotulo) {
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", opcoes.rotulo);
    } else {
      svg.setAttribute("aria-hidden", "true");
    }
    svg.setAttribute("focusable", "false");
    const uso = document.createElementNS(NS, "use");
    uso.setAttribute("href", "#i-" + nome);
    svg.appendChild(uso);
    return svg;
  }

  window.Helestron = window.Helestron || {};
  window.Helestron.icones = { instalar, icone, nomes: Object.keys(ICONES) };
})();
