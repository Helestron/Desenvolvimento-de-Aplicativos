/* Helestron — peças da interface usadas por todas as seções.
 *
 * Sem biblioteca: um construtor de elementos (el), formatação de datas e
 * números em português, o número CNJ, e os componentes no estilo do iOS
 * (botão, interruptor, controle segmentado, anel de progresso, medidor de
 * nível, listas agrupadas, avisos e folhas modais).
 *
 * Regra de ouro: texto vindo do servidor entra sempre como TEXTO
 * (textContent), nunca como HTML. Nome de parte, mensagem de erro do portal
 * e afins não podem virar marcação na página.
 */
(function () {
  "use strict";

  const H = (window.Helestron = window.Helestron || {});
  const icone = (...a) => H.icones.icone(...a);

  // ============================================================ elementos
  /**
   * el("div", {classe: "cartao", on: {click: fn}, aria: {label: "..."}}, filhos...)
   * Filhos: nós, textos, números, listas (achatadas) e null/false (ignorados).
   */
  function el(tag, attrs, ...filhos) {
    const no = document.createElement(tag);
    if (attrs) {
      for (const [chave, valor] of Object.entries(attrs)) {
        if (valor === undefined || valor === null || valor === false) continue;
        if (chave === "classe") no.className = valor;
        else if (chave === "texto") no.textContent = valor;
        else if (chave === "on") {
          for (const [evento, fn] of Object.entries(valor)) no.addEventListener(evento, fn);
        } else if (chave === "aria") {
          for (const [k, v] of Object.entries(valor)) {
            if (v !== undefined && v !== null) no.setAttribute("aria-" + k, String(v));
          }
        } else if (chave === "dados") {
          for (const [k, v] of Object.entries(valor)) no.dataset[k] = v;
        } else if (chave === "estilo") {
          for (const [k, v] of Object.entries(valor)) {
            if (k.startsWith("--")) no.style.setProperty(k, v);
            else no.style[k] = v;
          }
        } else if (chave === "valor") {
          no.value = valor;
        } else if (chave === "marcado") {
          no.checked = !!valor;
        } else if (valor === true) {
          no.setAttribute(chave, "");
        } else {
          no.setAttribute(chave, String(valor));
        }
      }
    }
    anexar(no, filhos);
    return no;
  }

  function anexar(no, filhos) {
    for (const f of filhos) {
      if (f === null || f === undefined || f === false) continue;
      if (Array.isArray(f)) anexar(no, f);
      else if (f instanceof Node) no.appendChild(f);
      else no.appendChild(document.createTextNode(String(f)));
    }
    return no;
  }

  /** Esvazia e preenche de novo. */
  function trocar(no, ...filhos) {
    no.replaceChildren();
    anexar(no, filhos);
    return no;
  }

  // ============================================================ formatação
  const LOCALE = "pt-BR";
  const fmtDataLonga = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" });
  const fmtDataLongaAno = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const fmtData = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit", year: "numeric" });
  const fmtDataCurta = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" });
  const fmtHora = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" });
  const fmtNumero = new Intl.NumberFormat(LOCALE);
  const fmtRelativo = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });

  function maiuscula(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  /** "2026-10-05" → Date local (sem o fuso deslocar o dia). */
  function lerData(valor) {
    if (!valor) return null;
    if (valor instanceof Date) return valor;
    const s = String(valor);
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    const d = new Date(s);
    return isNaN(d) ? null : d;
  }

  /** Date → "2026-10-05" (data local). */
  function iso(d) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function somarDias(d, n) {
    const r = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    r.setDate(r.getDate() + n);
    return r;
  }

  function mesmoDia(a, b) {
    return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  }

  const fmt = {
    numero: (n) => fmtNumero.format(n || 0),
    /** "Segunda-feira, 5 de outubro" */
    diaLongo: (v) => { const d = lerData(v); return d ? maiuscula(fmtDataLonga.format(d)) : ""; },
    /** "Sábado, 3 de outubro de 2026" */
    diaLongoAno: (v) => { const d = lerData(v); return d ? maiuscula(fmtDataLongaAno.format(d)) : ""; },
    data: (v) => { const d = lerData(v); return d ? fmtData.format(d) : ""; },
    dataCurta: (v) => { const d = lerData(v); return d ? fmtDataCurta.format(d).replace(".", "") : ""; },
    hora: (v) => { const d = lerData(v); return d ? fmtHora.format(d) : ""; },
    /** "hoje, 14:05" · "ontem, 09:12" · "2 out, 18:40" */
    quando(v) {
      const d = lerData(v);
      if (!d) return "";
      const hoje = new Date();
      const h = fmtHora.format(d);
      if (mesmoDia(d, hoje)) return "hoje, " + h;
      if (mesmoDia(d, somarDias(hoje, -1))) return "ontem, " + h;
      if (mesmoDia(d, somarDias(hoje, 1))) return "amanhã, " + h;
      return fmtDataCurta.format(d).replace(".", "") + ", " + h;
    },
    /** "há 5 minutos", "em 3 horas" */
    relativo(v) {
      const d = lerData(v);
      if (!d) return "";
      const s = (d.getTime() - Date.now()) / 1000;
      const a = Math.abs(s);
      if (a < 45) return s < 0 ? "agora há pouco" : "em instantes";
      if (a < 3600) return fmtRelativo.format(Math.round(s / 60), "minute");
      if (a < 86400) return fmtRelativo.format(Math.round(s / 3600), "hour");
      return fmtRelativo.format(Math.round(s / 86400), "day");
    },
    /** segundos → "01:02:03" */
    duracao(seg) {
      seg = Math.max(0, Math.floor(seg || 0));
      const h = Math.floor(seg / 3600), m = Math.floor((seg % 3600) / 60), s = seg % 60;
      const p = (n) => String(n).padStart(2, "0");
      return `${p(h)}:${p(m)}:${p(s)}`;
    },
    /** "9:00" vira "9h00" no texto corrido */
    horaFalada: (h) => (h ? String(h).replace(":", "h") : ""),
    plural: (n, um, varios) => `${fmtNumero.format(n || 0)} ${n === 1 ? um : varios}`,
    mb: (n) => (n >= 1024 ? (n / 1024).toLocaleString(LOCALE, { maximumFractionDigits: 1 }) + " GB" : Math.round(n) + " MB"),
    maiuscula,
    lerData,
    iso,
    somarDias,
    mesmoDia,
  };

  /** Bom dia / Boa tarde / Boa noite. */
  function saudacao(agora = new Date()) {
    const h = agora.getHours();
    if (h >= 5 && h < 12) return "Bom dia";
    if (h >= 12 && h < 18) return "Boa tarde";
    return "Boa noite";
  }

  /** Comparação sem acento e sem caixa (busca). */
  function normalizar(s) {
    return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  // ============================================================ número CNJ
  // NNNNNNN-DD.AAAA.J.TR.OOOO; dígito verificador pelo módulo 97 (Res. CNJ 65/2008).
  const SIGLAS = {
    "8.01": "TJAC", "8.02": "TJAL", "8.03": "TJAP", "8.04": "TJAM", "8.05": "TJBA", "8.06": "TJCE",
    "8.07": "TJDFT", "8.08": "TJES", "8.09": "TJGO", "8.10": "TJMA", "8.11": "TJMT", "8.12": "TJMS",
    "8.13": "TJMG", "8.14": "TJPA", "8.15": "TJPB", "8.16": "TJPR", "8.17": "TJPE", "8.18": "TJPI",
    "8.19": "TJRJ", "8.20": "TJRN", "8.21": "TJRS", "8.22": "TJRO", "8.23": "TJRR", "8.24": "TJSC",
    "8.25": "TJSE", "8.26": "TJSP", "8.27": "TJTO",
    "4.01": "TRF1", "4.02": "TRF2", "4.03": "TRF3", "4.04": "TRF4", "4.05": "TRF5", "4.06": "TRF6",
  };

  const cnj = {
    digitos: (s) => String(s || "").replace(/\D/g, ""),
    /** Dígitos → "0700123-83.2024.8.02.0001" (aceita incompleto, para a máscara). */
    mascarar(s) {
      const d = cnj.digitos(s).slice(0, 20);
      const partes = [[0, 7], [7, 9], [9, 13], [13, 14], [14, 16], [16, 20]];
      const sep = ["", "-", ".", ".", ".", "."];
      let r = "";
      partes.forEach(([a, b], i) => {
        if (d.length > a) r += sep[i] + d.slice(a, b);
      });
      return r;
    },
    /** O dígito verificador confere? */
    valido(s) {
      const d = cnj.digitos(s);
      if (d.length !== 20) return false;
      const n = d.slice(0, 7), dv = d.slice(7, 9), resto = d.slice(9);
      try {
        return BigInt(n + resto + dv) % 97n === 1n;
      } catch (_e) {
        return false;
      }
    },
    /** "8.02" → "TJAL" (ou "J.TR" quando não conhecemos). */
    tribunal(s) {
      const d = cnj.digitos(s);
      if (d.length < 16) return "";
      const chave = d.charAt(13) + "." + d.slice(14, 16);
      return SIGLAS[chave] || chave;
    },
  };

  // ============================================================ rótulos
  const SISTEMAS = { esaj: "e-SAJ", eproc: "eProc", arquivo: "Arquivo", outro: "Outro" };
  const nomeSistema = (s) => SISTEMAS[String(s || "").toLowerCase()] || s || "";

  // Situações da pauta (8.1) → classe da pílula.
  const SITUACAO_PAUTA = {
    "Designada": "azul",
    "Realizada": "verde",
    "Cancelada": "cinza",
    "Redesignada": "ambar",
    "Não realizada": "vermelho",
    "Suspensa": "navy",
  };

  // Tipos de audiência (8.1) → cor do ponto do selo. Tons de azul e cinza:
  // o tipo não é estado (vermelho, âmbar e verde pareciam erro, aviso e
  // "pronto"), e o nome do tipo vai escrito ao lado.
  const COR_TIPO = {
    "Conciliação": "#4C8DFF",
    "Instrução e julgamento": "#1B3560",
    "Una": "#2747B8",
    "Custódia": "#0E6E9E",
    "Justificação": "#5A86B5",
    "Mediação": "#3DB0E0",
    "Outra": "#A1A7B3",
  };

  // Situações do download (download/modelos.py) → rótulo e cor.
  const SITUACAO_DOWNLOAD = {
    "": ["Aguardando", "cinza"],
    AGUARDANDO: ["Aguardando", "cinza"],
    BAIXANDO: ["Baixando", "azul"],
    ANDAMENTO: ["Baixando", "azul"],
    EM_ANDAMENTO: ["Baixando", "azul"],
    OK: ["Baixado", "verde"],
    JA_BAIXADO: ["Já estava na pasta", "cinza"],
    SIGILOSO_SEM_SENHA: ["Sigiloso: falta a senha", "ambar"],
    NAO_ENCONTRADO: ["Não encontrado", "vermelho"],
    SEM_ACESSO: ["Sem acesso", "vermelho"],
    NAO_SUPORTADO: ["Tribunal não suportado", "cinza"],
    ERRO: ["Falhou", "vermelho"],
    CANCELADO: ["Interrompido", "cinza"],
  };

  function situacaoDownload(s) {
    const chave = String(s || "").toUpperCase();
    return SITUACAO_DOWNLOAD[chave] || [maiuscula(String(s || "").toLowerCase().replace(/_/g, " ")), "azul"];
  }

  // ============================================================ componentes
  /**
   * Botão. tipo: primario | tonal | texto | perigo | (padrão: vidro).
   * tamanho: grande | pequeno. 'icone' sozinho (sem rótulo) pede 'titulo'.
   */
  function botao({ rotulo, icone: nomeIcone, tipo, tamanho, acao, titulo, desativado, classe, atributos }) {
    const classes = ["botao"];
    if (tipo) classes.push("botao-" + tipo);
    if (tamanho) classes.push("botao-" + tamanho);
    if (!rotulo && nomeIcone) classes.push("botao-icone");
    if (classe) classes.push(classe);
    const b = el("button", Object.assign({
      type: "button",
      classe: classes.join(" "),
      title: titulo,
      aria: !rotulo && titulo ? { label: titulo } : null,
      disabled: !!desativado,
    }, atributos || {}),
    nomeIcone ? icone(nomeIcone) : null,
    rotulo ? el("span", { texto: rotulo }) : null);
    if (acao) {
      b.addEventListener("click", (ev) => executarAcao(b, acao, ev));
    }
    return b;
  }

  /**
   * Roda a ação do botão; se ela devolver uma promessa, o botão fica
   * ocupado até terminar (sem clique duplo) e um erro vira folha de erro.
   */
  async function executarAcao(botaoEl, acao, ev) {
    if (botaoEl.dataset.ocupado === "1") return;
    let resultado;
    try {
      resultado = acao(ev);
    } catch (erro) {
      folha.erro(erro);
      return;
    }
    if (!resultado || typeof resultado.then !== "function") return;
    botaoEl.dataset.ocupado = "1";
    const estavaDesativado = botaoEl.disabled;
    botaoEl.disabled = true;
    botaoEl.setAttribute("aria-busy", "true");
    try {
      await resultado;
    } catch (erro) {
      folha.erro(erro);
    } finally {
      botaoEl.dataset.ocupado = "";
      botaoEl.removeAttribute("aria-busy");
      if (botaoEl.isConnected) botaoEl.disabled = estavaDesativado;
    }
  }

  /** Interruptor do iOS (checkbox com role=switch). */
  function interruptor({ marcado, rotulo, aoMudar, desativado, id }) {
    const i = el("input", {
      type: "checkbox", role: "switch", classe: "interruptor", id,
      marcado: !!marcado, disabled: !!desativado, aria: rotulo ? { label: rotulo } : null,
    });
    if (aoMudar) {
      i.addEventListener("change", async () => {
        const valor = i.checked;
        try {
          const r = aoMudar(valor);
          if (r && typeof r.then === "function") {
            i.disabled = true;
            await r;
          }
        } catch (erro) {
          i.checked = !valor;      // volta: o programa não aceitou
          folha.erro(erro);
        } finally {
          if (!desativado) i.disabled = false;
        }
      });
    }
    return i;
  }

  /** Controle segmentado com o "polegar" deslizando sob a opção marcada. */
  function segmentado({ opcoes, valor, aoMudar, rotulo }) {
    const polegar = el("span", { classe: "segmentado-polegar", "aria-hidden": "true" });
    const grupo = el("div", { classe: "segmentado", role: "radiogroup", aria: { label: rotulo } }, polegar);
    const botoes = opcoes.map((op) => {
      const b = el("button", {
        type: "button", role: "radio", texto: op.rotulo,
        aria: { checked: String(op.valor === valor) }, tabindex: op.valor === valor ? "0" : "-1",
        dados: { valor: op.valor },
      });
      b.addEventListener("click", () => escolher(op.valor, true));
      b.addEventListener("keydown", (ev) => {
        const i = opcoes.findIndex((o) => o.valor === grupo.valor);
        if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
          ev.preventDefault();
          const n = (i + (ev.key === "ArrowRight" ? 1 : -1) + opcoes.length) % opcoes.length;
          escolher(opcoes[n].valor, true);
          botoes[n].focus();
        }
      });
      grupo.appendChild(b);
      return b;
    });

    function posicionar() {
      const atual = botoes.find((b) => b.dataset.valor === String(grupo.valor));
      if (!atual || !atual.offsetWidth) return;
      polegar.style.width = atual.offsetWidth + "px";
      polegar.style.transform = `translateX(${atual.offsetLeft}px)`;
    }

    function escolher(v, avisar) {
      grupo.valor = v;
      for (const b of botoes) {
        const sim = b.dataset.valor === String(v);
        b.setAttribute("aria-checked", String(sim));
        b.tabIndex = sim ? 0 : -1;
      }
      posicionar();
      if (avisar && aoMudar) aoMudar(v);
    }

    grupo.valor = valor;
    grupo.definir = (v) => escolher(v, false);
    // Só dá para medir depois de entrar na página (e de a fonte carregar).
    requestAnimationFrame(posicionar);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(posicionar);
    new ResizeObserver(posicionar).observe(grupo);
    return grupo;
  }

  /**
   * Anel de progresso. definir(percentual | null = indeterminado, estado):
   * estado "concluida" (verde), "alerta" (âmbar: terminou com falhas) ou
   * "falhou" (vermelho).
   */
  function anel({ tamanho = 36, espessura = 3.5, rotulo = false } = {}) {
    const r = (36 - espessura) / 2;
    const circ = 2 * Math.PI * r;
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 36 36");
    svg.setAttribute("aria-hidden", "true");
    const trilho = document.createElementNS(NS, "circle");
    const valor = document.createElementNS(NS, "circle");
    for (const c of [trilho, valor]) {
      c.setAttribute("cx", "18");
      c.setAttribute("cy", "18");
      c.setAttribute("r", String(r));
      c.setAttribute("stroke-width", String(espessura));
    }
    trilho.setAttribute("class", "anel-trilho");
    valor.setAttribute("class", "anel-valor");
    valor.setAttribute("stroke-dasharray", String(circ));
    valor.setAttribute("stroke-dashoffset", String(circ));
    svg.append(trilho, valor);
    const texto = rotulo ? el("span", { classe: "anel-rotulo" }) : null;
    const caixa = el("span", {
      classe: "anel", role: "progressbar", estilo: { width: tamanho + "px", height: tamanho + "px" },
      "aria-valuemin": "0", "aria-valuemax": "100",
    }, svg, texto);
    if (texto) texto.style.fontSize = Math.round(tamanho * 0.24) + "px";
    caixa.definir = (p, estado) => {
      caixa.classList.toggle("concluido", estado === "concluida");
      caixa.classList.toggle("falhou", estado === "falhou");
      caixa.classList.toggle("alerta", estado === "alerta");
      if (p === null || p === undefined || isNaN(p)) {
        caixa.classList.add("indeterminado");
        valor.setAttribute("stroke-dashoffset", String(circ * 0.72));
        caixa.removeAttribute("aria-valuenow");
        if (texto) texto.textContent = "";
        return;
      }
      caixa.classList.remove("indeterminado");
      const v = Math.max(0, Math.min(100, p));
      valor.setAttribute("stroke-dashoffset", String(circ * (1 - v / 100)));
      caixa.setAttribute("aria-valuenow", String(Math.round(v)));
      if (texto) texto.textContent = Math.round(v) + "%";
    };
    caixa.definir(null);
    return caixa;
  }

  /** Medidor de nível do microfone (barras como no Gravador do iOS). */
  function medidor(barras = 18) {
    const caixa = el("div", { classe: "medidor", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", aria: { label: "Nível do microfone" } });
    const itens = [];
    for (let i = 0; i < barras; i++) {
      const s = el("span");
      if (i >= barras * 0.55) s.classList.add("medio");
      if (i >= barras * 0.75) s.classList.add("alto");
      if (i >= barras * 0.92) s.classList.add("pico");
      caixa.appendChild(s);
      itens.push(s);
    }
    caixa.definir = (nivel) => {
      // O nível chega linear (0..1); a escala visual é mais sensível em baixo,
      // como num medidor de áudio, para a fala comum acender metade das barras.
      const n = Math.max(0, Math.min(1, Number(nivel) || 0));
      const v = Math.sqrt(n);
      const acesas = Math.round(v * barras);
      itens.forEach((s, i) => s.classList.toggle("aceso", i < acesas));
      caixa.setAttribute("aria-valuenow", String(Math.round(v * 100)));
    };
    return caixa;
  }

  /** A marca do Helestron (img/marca), com a letra H desenhada se o arquivo faltar. */
  function logo(tamanho = 38) {
    const img = el("img", { src: "img/marca/helestron.svg", alt: "", width: String(tamanho), height: String(tamanho) });
    img.addEventListener("error", () => {
      img.replaceWith(el("span", {
        classe: "bloco-icone cor-navy", "aria-hidden": "true",
        estilo: { width: tamanho + "px", height: tamanho + "px", borderRadius: Math.round(tamanho * 0.28) + "px", fontWeight: "800", fontSize: Math.round(tamanho * 0.5) + "px" },
        texto: "H",
      }));
    }, { once: true });
    return img;
  }

  function pilula(texto, cor, nomeIcone) {
    return el("span", { classe: "pilula pilula-" + (cor || "cinza") }, nomeIcone ? icone(nomeIcone) : null, texto);
  }

  function pilulaSituacao(situacao) {
    const cor = SITUACAO_PAUTA[situacao] || "cinza";
    const p = pilula(situacao || "—", cor);
    if (situacao === "Cancelada") p.classList.add("pilula-tachada");
    return p;
  }

  function seloTipo(tipo) {
    return el("span", { classe: "selo selo-ponto", estilo: { "--cor-selo": COR_TIPO[tipo] || "#A1A7B3" } }, tipo || "Audiência");
  }

  function seloSistema(sistema, tribunal) {
    const partes = [tribunal, nomeSistema(sistema)].filter(Boolean);
    return el("span", { classe: "selo selo-contorno" }, partes.join(" · "));
  }

  function blocoIcone(nome, cor, grande) {
    return el("span", { classe: `bloco-icone cor-${cor || "azul"}${grande ? " grande" : ""}` }, icone(nome));
  }

  /** Linha de lista agrupada. */
  function linha({ icone: nomeIcone, cor, titulo, sub, detalhe, acessorio, acao, chevron, classe, id }) {
    const tag = acao ? "button" : "div";
    const l = el(tag, {
      classe: "linha" + (nomeIcone ? " com-icone" : "") + (classe ? " " + classe : ""),
      type: acao ? "button" : null, id,
    },
    nomeIcone ? blocoIcone(nomeIcone, cor) : null,
    el("span", { classe: "linha-texto" },
      el("span", { classe: "linha-titulo", texto: titulo }),
      sub ? (sub instanceof Node ? el("span", { classe: "linha-sub" }, sub) : el("span", { classe: "linha-sub", texto: sub })) : null),
    detalhe !== undefined && detalhe !== null && detalhe !== "" ? el("span", { classe: "linha-detalhe", texto: detalhe, title: detalhe }) : null,
    acessorio || null,
    chevron || (acao && chevron !== false) ? icone("chevron-direita", { classe: "linha-chevron" }) : null);
    if (acao) l.addEventListener("click", (ev) => executarAcao(l, acao, ev));
    return l;
  }

  function grupo({ titulo, rodape, linhas, id }) {
    return el("section", { classe: "grupo", id, aria: titulo ? { label: titulo } : null },
      titulo ? el("h3", { classe: "grupo-titulo", texto: titulo }) : null,
      el("div", { classe: "grupo-lista" }, linhas),
      rodape ? (rodape instanceof Node ? el("p", { classe: "grupo-rodape" }, rodape) : el("p", { classe: "grupo-rodape", texto: rodape })) : null);
  }

  function vazio({ icone: nomeIcone, titulo, texto, acoes, compacto }) {
    return el("div", { classe: "vazio" + (compacto ? " compacto" : "") },
      el("div", { classe: "vazio-icone" }, icone(nomeIcone || "info")),
      el("p", { classe: "vazio-titulo", texto: titulo }),
      texto ? (texto instanceof Node ? el("div", { classe: "vazio-texto" }, texto) : el("p", { classe: "vazio-texto", texto })) : null,
      acoes && acoes.length ? el("div", { classe: "grupo-botoes" }, acoes) : null);
  }

  function faixa({ tipo, icone: nomeIcone, titulo, texto, acoes }) {
    const padrao = { aviso: "aviso", erro: "x-circulo", ok: "check-circulo", sigilo: "cadeado" }[tipo] || "info";
    return el("div", { classe: "faixa" + (tipo ? " faixa-" + tipo : ""), role: tipo === "erro" ? "alert" : null },
      icone(nomeIcone || padrao),
      el("div", { classe: "faixa-texto" },
        titulo ? el("strong", { classe: "faixa-titulo", texto: titulo }) : null,
        texto ? (texto instanceof Node ? texto : el("span", { texto })) : null),
      acoes && acoes.length ? el("div", { classe: "grupo-botoes" }, acoes) : null);
  }

  function esqueleto(linhas = 3) {
    const caixa = el("div", { classe: "lista-simples", aria: { busy: "true", label: "Carregando" } });
    for (let i = 0; i < linhas; i++) {
      caixa.appendChild(el("div", { classe: "item-simples" },
        el("div", { classe: "esqueleto", estilo: { width: "42px", height: "14px" } }),
        el("div", { classe: "item-texto" },
          el("div", { classe: "esqueleto", estilo: { width: 60 + ((i * 17) % 30) + "%" } }),
          el("div", { classe: "esqueleto", estilo: { width: 35 + ((i * 11) % 25) + "%", height: "11px", marginTop: "7px" } }))));
    }
    return caixa;
  }

  function cartao(attrs, ...filhos) {
    const a = Object.assign({}, attrs || {});
    a.classe = "cartao" + (a.classe ? " " + a.classe : "");
    return el(a.tag || "section", a, ...filhos);
  }

  function cabecalhoCartao(titulo, nomeIcone, ...lado) {
    return el("div", { classe: "cartao-cabecalho" },
      el("h2", { classe: "cartao-titulo" }, nomeIcone ? icone(nomeIcone) : null, titulo),
      lado.length ? el("div", { classe: "grupo-botoes" }, lado) : null);
  }

  /** Cabeçalho de página: título grande, subtítulo e ações à direita. */
  function cabecalho({ titulo, subtitulo, acoes }) {
    const h1 = el("h1", { classe: "titulo-grande", tabindex: "-1", texto: titulo });
    const sub = el("p", { classe: "subtitulo" });
    if (subtitulo instanceof Node) sub.appendChild(subtitulo);
    else if (subtitulo) sub.textContent = subtitulo;
    const caixaAcoes = el("div", { classe: "cabecalho-acoes" }, acoes || []);
    const cab = el("header", { classe: "cabecalho" },
      el("div", { classe: "cabecalho-texto" }, h1, sub), caixaAcoes);
    cab.titulo = h1;
    cab.subtitulo = sub;
    cab.acoes = caixaAcoes;
    return cab;
  }

  // ============================================================ avisos (toasts)
  let caixaAvisos = null;
  const ALTURA_AVISO = 110;      // a altura típica de um aviso de duas linhas

  /**
   * Os avisos ficam no canto superior direito, mas sem cobrir as ações
   * principais da tela: descem para logo abaixo dos botões do cabeçalho da
   * página (Exportar Excel, Sincronizar...) e do que a tela marcar com
   * data-livre-de-avisos (a barra da audiência ao vivo, os botões de quem
   * está falando). Só conta o que está à vista, na faixa dos avisos.
   */
  function posicionarAvisos() {
    if (!caixaAvisos) return;
    const largura = Math.min(380, innerWidth - 32);
    const esquerda = innerWidth - 16 - largura;
    const alvos = Array.from(document.querySelectorAll("#pagina .cabecalho-acoes > *, #pagina [data-livre-de-avisos]"))
      .map((n) => n.getBoundingClientRect())
      .filter((r) => r.width && r.height && r.bottom > 0 && r.right > esquerda)
      .sort((a, b) => a.top - b.top);
    let topo = 16;
    for (const r of alvos) {
      if (r.top < topo + ALTURA_AVISO) topo = Math.max(topo, r.bottom + 10);
    }
    topo = Math.min(topo, Math.max(16, innerHeight - ALTURA_AVISO - 24));
    caixaAvisos.style.top = Math.round(topo) + "px";
  }
  let posicionando = 0;
  const reposicionar = () => {
    if (posicionando || !caixaAvisos || !caixaAvisos.childElementCount) return;
    posicionando = requestAnimationFrame(() => { posicionando = 0; posicionarAvisos(); });
  };
  addEventListener("resize", reposicionar);
  addEventListener("hashchange", () => setTimeout(reposicionar, 350));
  document.addEventListener("scroll", reposicionar, true);

  /**
   * Aviso discreto no canto superior direito.
   * tipo: info | sucesso | alerta | erro. acoes: [{rotulo, acao}].
   * A mesma mensagem que já está à vista não aparece duas vezes: o aviso
   * novo toma o lugar do antigo - também quando uma frase contém a outra (o
   * erro de uma fonte da pauta, "O portal não respondeu", e o do fim da
   * tarefa, "Não consegui ler a pauta: e-SAJ · TJAC — O portal não
   * respondeu.").
   */
  function aviso({ titulo, mensagem, tipo = "info", acoes, duracao }) {
    if (!caixaAvisos) caixaAvisos = document.getElementById("avisos");
    if (!caixaAvisos) return null;
    const normal = (t) => String(t || "").trim().replace(/[.\s]+$/, "");
    const chave = normal(mensagem) || normal(titulo);
    for (const antigo of Array.from(caixaAvisos.querySelectorAll(".aviso:not(.saindo)"))) {
      const velha = antigo.dataset.chave || "";
      const repete = chave && velha && (velha === chave ||
        (velha.length >= 25 && chave.includes(velha)) || (chave.length >= 25 && velha.includes(chave)));
      if (repete) antigo.remove();
    }
    const nome = { sucesso: "check", alerta: "aviso", erro: "x", info: "info" }[tipo] || "info";
    const fechar = el("button", { type: "button", classe: "aviso-fechar", aria: { label: "Fechar aviso" } }, icone("x"));
    const no = el("div", { classe: "aviso aviso-" + tipo, role: tipo === "erro" ? "alert" : "status", dados: { chave } },
      el("span", { classe: "aviso-icone" }, icone(nome)),
      el("div", { classe: "aviso-corpo" },
        titulo ? el("strong", { classe: "aviso-titulo", texto: titulo }) : null,
        mensagem ? el("span", { classe: "aviso-texto", texto: mensagem }) : null,
        acoes && acoes.length ? el("div", { classe: "aviso-acoes" },
          acoes.map((a) => botao({ rotulo: a.rotulo, tipo: "texto", tamanho: "pequeno", acao: async () => { await a.acao(); remover(); } }))) : null),
      fechar);
    let timer = null;
    function remover() {
      clearTimeout(timer);
      if (!no.isConnected || no.classList.contains("saindo")) return;
      no.classList.add("saindo");
      setTimeout(() => no.remove(), 230);
    }
    fechar.addEventListener("click", remover);
    const tempo = duracao || (tipo === "erro" ? 9000 : acoes && acoes.length ? 8000 : 5000);
    const agendar = () => { timer = setTimeout(remover, tempo); };
    no.addEventListener("mouseenter", () => clearTimeout(timer));
    no.addEventListener("mouseleave", agendar);
    posicionarAvisos();
    caixaAvisos.prepend(no);
    // No máximo três avisos à vista (mais que isso desce sobre a tela): o
    // mais antigo sai.
    const todos = caixaAvisos.querySelectorAll(".aviso:not(.saindo)");
    if (todos.length > 3) todos[todos.length - 1].remove();
    agendar();
    return { fechar: remover, elemento: no };
  }

  // ============================================================ folhas (sheets)
  const pilha = [];

  /**
   * Folha modal. Devolve {elemento, fechar(valor), resultado: Promise}.
   * 'aoCancelar' roda no Esc, no X e no clique fora (se permitido).
   */
  function abrirFolha({ titulo, mensagem, icone: nomeIcone, corIcone, conteudo, botoes, larga, fecharFora = true, aoCancelar, semFechar }) {
    const anterior = document.activeElement;
    const idTitulo = "folha-titulo-" + Math.random().toString(36).slice(2, 8);
    const corpo = el("div", { classe: "folha-corpo" }, conteudo || []);
    const rodape = el("div", { classe: "folha-botoes" });
    const caixa = el("div", {
      classe: "folha" + (larga ? " larga" : ""), role: "dialog", "aria-modal": "true",
      aria: { labelledby: idTitulo },
    },
    semFechar ? null : el("button", { type: "button", classe: "folha-fechar", aria: { label: "Fechar" }, on: { click: () => cancelar() } }, icone("x")),
    nomeIcone ? el("div", { classe: "folha-icone" + (corIcone ? " " + corIcone : "") }, icone(nomeIcone)) : null,
    el("h2", { classe: "folha-titulo", id: idTitulo, texto: titulo }),
    mensagem ? (mensagem instanceof Node ? el("div", { classe: "folha-mensagem" }, mensagem) : el("p", { classe: "folha-mensagem", texto: mensagem })) : null,
    conteudo ? corpo : null,
    rodape);
    const fundo = el("div", { classe: "folha-fundo" }, caixa);

    let resolver;
    const resultado = new Promise((r) => { resolver = r; });
    let fechada = false;

    function fechar(valor) {
      if (fechada) return;
      fechada = true;
      const i = pilha.indexOf(controle);
      if (i >= 0) pilha.splice(i, 1);
      fundo.classList.add("saindo");
      setTimeout(() => fundo.remove(), 190);
      document.removeEventListener("keydown", teclado, true);
      if (anterior && anterior.focus && anterior.isConnected) anterior.focus();
      resolver(valor);
    }

    function cancelar() {
      if (aoCancelar) aoCancelar();
      fechar(undefined);
    }

    function teclado(ev) {
      if (pilha[pilha.length - 1] !== controle) return;
      if (ev.key === "Escape" && !semFechar) {
        ev.preventDefault();
        ev.stopPropagation();
        cancelar();
      } else if (ev.key === "Tab") {
        // Foco preso na folha.
        const focaveis = Array.from(caixa.querySelectorAll(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'))
          .filter((n) => n.offsetParent !== null);
        if (!focaveis.length) return;
        const primeiro = focaveis[0], ultimo = focaveis[focaveis.length - 1];
        if (ev.shiftKey && document.activeElement === primeiro) { ev.preventDefault(); ultimo.focus(); }
        else if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primeiro.focus(); }
      }
    }

    if (fecharFora && !semFechar) {
      fundo.addEventListener("mousedown", (ev) => { if (ev.target === fundo) cancelar(); });
    }

    const controle = { elemento: caixa, fundo, fechar, cancelar, resultado, rodape, corpo };
    for (const b of botoes || []) {
      if (b === "espaco") { rodape.appendChild(el("span", { classe: "espaco" })); continue; }
      const bt = botao({
        rotulo: b.rotulo, tipo: b.tipo, icone: b.icone, classe: b.espaco ? "espaco" : null,
        acao: async () => {
          if (b.acao) {
            const r = await b.acao(controle);
            if (r === false) return;          // a ação pediu para manter a folha aberta
            fechar(b.valor !== undefined ? b.valor : r);
          } else {
            fechar(b.valor);
          }
        },
      });
      if (b.id) bt.id = b.id;
      if (b.padrao) bt.dataset.padrao = "1";
      rodape.appendChild(bt);
    }
    pilha.push(controle);
    document.body.appendChild(fundo);
    document.addEventListener("keydown", teclado, true);
    // Foco: o primeiro campo; senão, o botão padrão; senão, o último botão.
    requestAnimationFrame(() => {
      const alvo = caixa.querySelector("[autofocus], input:not([type=hidden]), textarea, select") ||
        rodape.querySelector("[data-padrao]") || rodape.querySelector("button:last-child");
      if (alvo) alvo.focus();
    });
    return controle;
  }

  const folha = {
    abrir: abrirFolha,

    /** Confirmação: Promise<boolean>. */
    confirmar({ titulo, mensagem, confirmar = "Continuar", cancelar = "Cancelar", perigo = false, icone: nomeIcone }) {
      const f = abrirFolha({
        titulo, mensagem, icone: nomeIcone || (perigo ? "aviso" : "info"), corIcone: perigo ? "alerta" : null,
        botoes: [
          { rotulo: cancelar, valor: false },
          { rotulo: confirmar, tipo: perigo ? "perigo" : "primario", valor: true, padrao: true },
        ],
      });
      return f.resultado.then((v) => v === true);
    },

    /** Informação com um botão "OK" ('corIcone' "erro" ou "alerta" muda a cor do ícone). */
    informar({ titulo, mensagem, icone: nomeIcone, corIcone, conteudo }) {
      return abrirFolha({
        titulo, mensagem, conteudo, icone: nomeIcone || "info", corIcone,
        botoes: [{ rotulo: "OK", tipo: "primario", padrao: true }],
      }).resultado;
    },

    /** Erro (ErroApi ou Error): mostra a 'mensagem' e, recolhido, o detalhe técnico. */
    erro(erro, titulo) {
      if (!erro) return Promise.resolve();
      // Recusa do programa (ErroApi) é resposta prevista, não defeito da tela.
      if (erro.name === "ErroApi") console.info("Helestron:", erro.codigo, erro.message);
      else console.error(erro);
      const mensagem = (erro && erro.message) || String(erro);
      const detalhe = erro && (erro.detalhe || (erro.name !== "ErroApi" && erro.stack) || "");
      const conteudo = detalhe ? el("details", { classe: "detalhes-tecnicos" },
        el("summary", { texto: "Detalhes técnicos" }), el("pre", { texto: detalhe })) : null;
      return abrirFolha({
        titulo: titulo || tituloDoErro(erro), mensagem, icone: "aviso", corIcone: "erro", conteudo,
        botoes: [{ rotulo: "OK", tipo: "primario", padrao: true }],
      }).resultado;
    },

    /** Pede um texto: Promise<string | undefined>. */
    entrada({ titulo, mensagem, rotulo, valor = "", placeholder, confirmar = "OK", tipo = "text", icone: nomeIcone, validar, multilinha }) {
      const campo = multilinha
        ? el("textarea", { classe: "campo", placeholder, rows: "6" })
        : el("input", { classe: "campo", type: tipo, placeholder, autocomplete: "off", spellcheck: "false" });
      campo.value = valor;
      const ajuda = el("p", { classe: "ajuda-campo erro", hidden: true, "aria-live": "polite" });
      const id = "entrada-" + Math.random().toString(36).slice(2, 8);
      campo.id = id;
      const conteudo = el("div", {},
        rotulo ? el("label", { classe: "rotulo", for: id, texto: rotulo }) : null, campo, ajuda);
      const f = abrirFolha({
        titulo, mensagem, icone: nomeIcone, conteudo,
        botoes: [
          { rotulo: "Cancelar" },
          {
            rotulo: confirmar, tipo: "primario", padrao: true, acao: () => {
              const v = campo.value.trim();
              const problema = validar ? validar(v) : (!v ? "Preencha o campo." : "");
              if (problema) {
                ajuda.textContent = problema;
                ajuda.hidden = false;
                campo.classList.add("invalido");
                campo.focus();
                return false;
              }
              return v;
            },
          },
        ],
      });
      if (!multilinha) {
        campo.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") {
            ev.preventDefault();
            f.rodape.querySelector("[data-padrao]").click();
          }
        });
      }
      return f.resultado;
    },
  };

  function tituloDoErro(erro) {
    const c = erro && erro.codigo;
    if (c === "sem_conexao") return "Sem conexão com o Helestron";
    if (c === "ocupado" || c === "recurso_ocupado") return "Espere um pouco";
    if (c === "navegador_nao_abriu") return "O navegador não abriu";
    return "Não deu certo";
  }

  // ============================================================ utilidades
  /**
   * Põe o texto na área de transferência, sem aviso: Promise<boolean>.
   * A escrita começa JÁ, na mesma volta do clique que a pediu (antes de
   * qualquer espera de rede): depois, a janela pode ter perdido o foco para
   * o app que se abriu, e o navegador recusa a cópia. Reserva para o
   * WebView antigo: a seleção de um campo escondido e o "copiar" do
   * documento.
   */
  function copiarTexto(texto) {
    let escrita;
    try {
      escrita = navigator.clipboard && navigator.clipboard.writeText
        ? navigator.clipboard.writeText(String(texto)) : Promise.reject(new Error("sem área de transferência"));
    } catch (erro) {
      escrita = Promise.reject(erro);
    }
    return escrita.then(() => true, () => {
      const t = el("textarea", { estilo: { position: "fixed", opacity: "0" } });
      t.value = String(texto);
      document.body.appendChild(t);
      t.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_e) { ok = false; }
      t.remove();
      return ok;
    });
  }

  /** Copia para a área de transferência e avisa (copiado, ou não deu). */
  async function copiar(texto, rotulo) {
    const ok = await copiarTexto(texto);
    aviso(ok
      ? { titulo: rotulo || "Copiado", mensagem: texto.length < 80 ? texto : "Cole com Ctrl+V onde precisar.", tipo: "sucesso", duracao: 2600 }
      : { titulo: "Não consegui copiar", mensagem: "Selecione o texto e use Ctrl+C.", tipo: "alerta" });
    return ok;
  }

  /** Espera um evento do DOM ou um tempo, o que vier primeiro. */
  function esperar(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function debounce(fn, ms) {
    let t = null;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  }

  H.ui = {
    el, anexar, trocar, icone, botao, logo, executarAcao, interruptor, segmentado, anel, medidor,
    pilula, pilulaSituacao, seloTipo, seloSistema, blocoIcone, linha, grupo, vazio, faixa,
    esqueleto, cartao, cabecalhoCartao, cabecalho, aviso, folha, copiar, copiarTexto, esperar, debounce,
    situacaoDownload, nomeSistema, COR_TIPO, SITUACAO_PAUTA,
  };
  H.fmt = fmt;
  H.cnj = cnj;
  H.saudacao = saudacao;
  H.normalizar = normalizar;
})();
