"""Baixar processos: relação → acesso → destino → um PDF por processo.

Três passos numerados, na ordem em que o usuário pensa, e um rodapé fixo
com o botão principal ("Baixar 37 processos") e, durante o lote, a barra
de progresso, o processo atual e o Parar. A tabela mostra a situação de
cada processo ao vivo.

Da base (aba_baixar) ficam o leitor de relação, a validação CNJ, o aviso do
Excel que corrompe o número e a injeção de "cancelado"/"status" no motor -
agora por um Contexto (tarefas.ContextoTela). Saem os oito botões e três
caixas de marcar de jargão (dossiês, ofício, conferência, importar...): o
que sobra cabe em "Destino e opções".

Nada lento roda na thread do Tk: a leitura da relação (um PDF de pauta
pode ter centenas de páginas) e o download do link vão para uma Tarefa.
"""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..nucleo import caminhos, cnj, sistema, tribunais
from . import componentes, dialogos, estilo, servicos
from .acessos import EditorAcesso, portais_da_lista
from .componentes import Detalhes, Faixa, Pagina, plural, secao
from .estilo import px
from .tarefas import NAVEGADOR, NUVEM, ContextoTela

# "download" no nome: as linhas deste registro vão para os Detalhes da
# página (registro.marca), junto com as do motor.
log = logging.getLogger("interface.download")

COLUNAS = [("n", "Nº", 46, "e", False), ("processo", "Processo", 214, "w", False),
           ("tribunal", "Tribunal", 150, "w", False), ("situacao", "Situação", 160, "w", False),
           ("folhas", "Folhas", 62, "e", False), ("obs", "Observação", 220, "w", True)]

_FALHAS = {"ERRO", "NAO_ENCONTRADO", "SEM_ACESSO", "NAO_SUPORTADO", "SIGILOSO_SEM_SENHA"}
OPCOES = (("pular_baixados", "Pular os que já estão na pasta"),
          ("separar_sigilosos", "Separar os sigilosos (pasta Sigilosos, fora do acervo)"),
          ("baixar_midias", "Baixar também as gravações de audiência"),
          ("mostrar_navegador", "Mostrar o navegador enquanto baixa"))
# Título do ctx.avisar do motor quando o portal recusa o login (motor._grupo).
PREFIXO_LOGIN_RECUSADO = "Não foi possível entrar"


class PaginaBaixar(Pagina):
    nome = "baixar"
    titulo = "Baixar processos"
    icone = "baixar"
    marca_log = "[baixar]"

    # ================================================================ montagem
    def montar(self) -> None:
        self.leitura = None                 # nucleo.listas.Leitura
        self.nome_lote = ""
        self.destino_escolhido: Path | None = None
        self.resumo = None
        self.estado = "vazio"               # vazio | lendo | pronto | baixando | fim
        self.progresso = (0, 0, "")
        self.status_texto = ""
        self.editores: list[EditorAcesso] = []
        self._vars: dict[str, tk.BooleanVar] = {}
        self._falhas_login: list[tuple[str, str]] = []   # (título, texto) do lote em curso
        self._destino_lote: Path | None = None
        self.tarefa_ler = self.nova_tarefa("Ler a relação")
        self.tarefa = self.nova_tarefa("Baixar processos", (NAVEGADOR,))
        self.tarefa_nuvem = self.nova_tarefa("Espelho na nuvem (download)", (NUVEM,))

        corpo, rodape, _ = componentes.estrutura(
            self, "Baixar processos",
            "Os autos completos, com o seu acesso ao e-SAJ ou ao eProc: um PDF por processo, "
            "nomeado pelo número, todos numa única pasta.", rodape=True)
        corpo.columnconfigure(0, weight=1)
        self.corpo = corpo

        # recado do portal ("Conclua o login na janela do navegador")
        self.faixa_portal = Faixa(corpo, "Info")
        self.faixa_portal.grid(row=0, column=0, sticky="ew", pady=(0, px(16)))
        self.faixa_portal.grid_remove()

        # ------------------------------------------------------- passo 1
        secao(corpo, "Relação de processos", 1,
              "Excel, Word, PDF, CSV ou texto: o programa encontra os números sozinho, em "
              "qualquer coluna ou parágrafo.").grid(row=1, column=0, sticky="ew")
        barra = ttk.Frame(corpo)
        barra.grid(row=2, column=0, sticky="ew", pady=(px(12), px(10)))
        barra.columnconfigure(3, weight=1)
        estilo.botao(barra, "Abrir arquivo (Excel, Word, PDF…)", self.abrir_arquivo,
                     "tonal").grid(row=0, column=0)
        estilo.botao(barra, "Colar lista", self.colar).grid(row=0, column=1, padx=(px(8), 0))
        estilo.botao(barra, "Link compartilhado", self.link).grid(row=0, column=2,
                                                                  padx=(px(8), 0))
        self.btn_limpar = estilo.botao(barra, "Limpar a lista", self.limpar, "texto")
        self.btn_limpar.grid(row=0, column=4, sticky="e")

        self.info_lista = ttk.Label(corpo, text="", foreground=estilo.TINTA_FRACA, justify="left")
        self.info_lista.grid(row=3, column=0, sticky="ew")
        estilo.acompanhar_largura(self.info_lista)
        self.faixa_lista = Faixa(corpo, "Aviso")
        self.faixa_lista.grid(row=4, column=0, sticky="ew", pady=(px(8), 0))

        self.vazio = ttk.Frame(corpo, style="Faixa.TFrame", padding=(px(20), px(18)))
        self.vazio.columnconfigure(1, weight=1)
        foto = estilo.imagem("cartao-baixar", px(44))
        tk.Label(self.vazio, image=foto or "", background=estilo.FAIXA_CLARA).grid(
            row=0, column=0, rowspan=2, padx=(0, px(16)))
        tk.Label(self.vazio, text="Nenhuma relação aberta", font=estilo.FONTE_NEGRITO,
                 background=estilo.FAIXA_CLARA, foreground=estilo.TINTA, anchor="w").grid(
            row=0, column=1, sticky="ew")
        tk.Label(self.vazio, text="Abra a planilha ou o documento com os números dos processos, "
                                  "ou cole a lista. Processo em segredo de justiça: ponha a "
                                  "senha na mesma linha, depois de ponto e vírgula.",
                 background=estilo.FAIXA_CLARA, foreground=estilo.TINTA_FRACA, anchor="w",
                 justify="left", wraplength=px(560)).grid(row=1, column=1, sticky="ew")
        self.quadro_tabela, self.arvore = componentes.tabela(corpo, COLUNAS, altura=8)
        self.arvore.bind("<Double-1>", self._abrir_linha)
        componentes.DicaTabela(self.arvore, ("obs", "situacao", "tribunal"))
        self._notas: dict[str, str] = {}    # observação fixa de cada linha (lista)

        # ------------------------------------------------------- passo 2
        secao(corpo, "Acesso aos portais", 2,
              "O programa reconhece o tribunal pelo número e entra com o SEU acesso. "
              "Nada é enviado a terceiros.").grid(row=6, column=0, sticky="ew", pady=(px(28), 0))
        self.area_acessos = ttk.Frame(corpo)
        self.area_acessos.grid(row=7, column=0, sticky="ew", pady=(px(12), 0))
        self.area_acessos.columnconfigure(0, weight=1)

        # ------------------------------------------------------- passo 3
        secao(corpo, "Destino e opções", 3).grid(row=8, column=0, sticky="ew", pady=(px(28), 0))
        destino = ttk.Frame(corpo, style="Faixa.TFrame", padding=(px(14), px(10)))
        destino.grid(row=9, column=0, sticky="ew", pady=(px(12), 0))
        destino.columnconfigure(1, weight=1)
        tk.Label(destino, text="Pasta:", background=estilo.FAIXA_CLARA,
                 foreground=estilo.TINTA_FRACA).grid(row=0, column=0, sticky="w",
                                                     padx=(0, px(8)))
        self.rotulo_destino = tk.Label(destino, text="", font=estilo.FONTE_MONO, anchor="w",
                                       background=estilo.FAIXA_CLARA, foreground=estilo.TINTA,
                                       justify="left")
        self.rotulo_destino.grid(row=0, column=1, sticky="ew")
        estilo.acompanhar_largura(self.rotulo_destino)
        estilo.botao(destino, "Alterar…", self.alterar_destino, superficie="Faixa").grid(
            row=0, column=2, padx=(px(10), 0))
        estilo.botao(destino, "Abrir", self.abrir_destino, superficie="Faixa").grid(
            row=0, column=3, padx=(px(8), 0))
        opcoes = ttk.Frame(corpo)
        opcoes.grid(row=10, column=0, sticky="ew", pady=(px(10), 0))
        opcoes.columnconfigure((0, 1), weight=1, uniform="op")
        for i, (chave, texto) in enumerate(OPCOES):
            var = tk.BooleanVar(value=self.cfg.flag("download", chave))
            self._vars[chave] = var
            ttk.Checkbutton(opcoes, text=texto, variable=var,
                            command=lambda c=chave: self._opcao(c)).grid(
                row=i // 2, column=i % 2, sticky="w", pady=px(2))

        self.detalhes = Detalhes(corpo, "Detalhes técnicos do download")
        self.detalhes.grid(row=11, column=0, sticky="ew", pady=(px(24), 0))

        # ------------------------------------------------------- rodapé
        rodape.columnconfigure(0, weight=1)
        esquerda = ttk.Frame(rodape)
        esquerda.grid(row=0, column=0, sticky="ew")
        esquerda.columnconfigure(1, weight=1)
        self.icone_rodape = tk.Label(esquerda, background=estilo.PAPEL)
        self.icone_rodape.grid(row=0, column=0, rowspan=2, padx=(0, px(10)))
        self.texto_rodape = ttk.Label(esquerda, text="", justify="left")
        self.texto_rodape.grid(row=0, column=1, sticky="ew")
        estilo.acompanhar_largura(self.texto_rodape)
        self.barra_rodape = ttk.Progressbar(esquerda, mode="determinate", maximum=1000)
        self.acoes_rodape = ttk.Frame(rodape)
        self.acoes_rodape.grid(row=0, column=1, sticky="e", padx=(px(16), 0))

        self._atualizar_tudo()

    # ============================================================ a relação
    def abrir_arquivo(self) -> None:
        from ..nucleo import listas

        inicial = self.cfg.texto("interface", "pasta_relacoes") or str(Path.home())
        caminho = filedialog.askopenfilename(parent=self.janela.raiz,
                                             title="Abrir a relação de processos",
                                             filetypes=listas.TIPOS_ARQUIVO, initialdir=inicial)
        if not caminho:
            return
        caminho = Path(caminho)
        self.gravar("interface", "pasta_relacoes", str(caminho.parent))
        self._ler(lambda: listas.ler_arquivo(caminho), caminho.stem)

    def colar(self) -> None:
        from ..nucleo import listas

        def usar(texto: str):
            self._ler(lambda: listas.ler_texto(texto), f"Lista {datetime.now():%Y-%m-%d %Hh%M}")
        dialogos.DialogoColar(self.janela.raiz, usar)

    def link(self) -> None:
        from ..nucleo import listas

        def usar(url: str):
            def baixar_e_ler():
                arquivo = listas.baixar_link(url, caminhos.TEMP / "listas")
                try:
                    leitura = listas.ler_arquivo(arquivo)
                finally:
                    # A relação pode trazer as senhas dos sigilosos: lida, não
                    # fica no disco (só o nome do arquivo segue, para o lote).
                    try:
                        arquivo.unlink()
                    except OSError:
                        log.warning("não consegui apagar a relação baixada %s", arquivo.name)
                leitura.origem = leitura.origem or str(arquivo)
                return leitura
            self._ler(baixar_e_ler, None)
        dialogos.DialogoLink(self.janela.raiz, usar)

    def _ler(self, funcao, nome: str | None) -> None:
        if self.tarefa.ativa:
            dialogos.informar(self.janela.raiz, "Download em andamento",
                              "Espere o lote atual terminar (ou clique em Parar) antes de "
                              "abrir outra relação.")
            return
        estado_antes = self.estado
        self.estado = "lendo"
        self._atualizar_rodape()

        def lida(leitura):
            self.estado = estado_antes if estado_antes != "lendo" else "vazio"
            lote = nome or Path(leitura.origem or "Relação").stem
            self._usar_leitura(leitura, lote)
            # Também quando o usuário cancela a troca da relação: sem isto,
            # o rodapé ficava em "Lendo a relação…", com a barra girando e o
            # botão de baixar desativado.
            self._atualizar_rodape()

        def falhou(erro):
            self.estado = estado_antes if estado_antes != "lendo" else "vazio"
            self._atualizar_rodape()
            if type(erro).__name__ == "ListaInvalida":
                dialogos.erro(self.janela.raiz, "Não consegui usar esta relação",
                              _maiuscula(str(erro)))
            else:
                log.exception("falha ao ler a relação", exc_info=erro)
                dialogos.erro(self.janela.raiz, "Não consegui ler a relação",
                              f"{erro}\n\nOs detalhes ficaram no registro (pasta Logs).")

        self.em_segundo_plano(self.tarefa_ler, funcao, ao_concluir=lida, ao_falhar=falhou)

    def _usar_leitura(self, leitura, lote: str) -> None:
        if self.leitura is not None and self.leitura.processos and self.estado != "fim":
            resposta = messagebox.askyesnocancel(
                "Já há uma relação aberta",
                f"A lista atual tem {plural(len(self.leitura.processos), 'processo')}.\n\n"
                "Sim: SUBSTITUIR pela nova relação.\nNão: ACRESCENTAR os novos à lista atual.",
                parent=self.janela.raiz)
            if resposta is None:
                return
            if resposta is False:
                antes = len(self.leitura.processos)
                self.leitura.juntar(leitura)
                log.info("Relação acrescentada: %d processo(s) novo(s).",
                         len(self.leitura.processos) - antes)
                self._atualizar_tudo()
                return
        self.leitura = leitura
        self.nome_lote = sistema.nome_seguro(lote, "Relação")
        self.destino_escolhido = None
        self.resumo = None
        self.estado = "pronto" if leitura.processos else "vazio"
        log.info("Relação %s: %s.", lote, plural(len(leitura.processos), "processo"))
        self._atualizar_tudo()

    def limpar(self) -> None:
        if self.tarefa.ativa:
            return
        self.leitura = None
        self.nome_lote = ""
        self.resumo = None
        self.destino_escolhido = None
        self.estado = "vazio"
        self.faixa_portal.grid_remove()
        self._atualizar_tudo()

    # ============================================================ desenho
    def _atualizar_tudo(self) -> None:
        self._preencher_tabela()
        self._resumir_lista()
        self._montar_acessos()
        self._atualizar_destino()
        self._atualizar_rodape()

    @property
    def numeros(self) -> list:
        return list(self.leitura.processos) if self.leitura is not None else []

    def _preencher_tabela(self) -> None:
        arv = self.arvore
        arv.delete(*arv.get_children())
        numeros = self.numeros
        if not numeros:
            self.quadro_tabela.grid_remove()
            self.vazio.grid(row=5, column=0, sticky="ew", pady=(px(10), 0))
            self.btn_limpar.state(["disabled"])
            return
        self.vazio.grid_remove()
        self.quadro_tabela.grid(row=5, column=0, sticky="ew", pady=(px(10), 0))
        self.btn_limpar.state(["!disabled"])
        # Uma consulta ao catálogo por TRIBUNAL, não por processo: com
        # endereços corrigidos pelo usuário, cada consulta relê um JSON, e uma
        # pauta de mil processos travava a janela por segundos.
        catalogo: dict[str, tuple] = {}
        for i, n in enumerate(numeros, 1):
            if n.chave_tribunal not in catalogo:
                catalogo[n.chave_tribunal] = (tribunais.por_numero(n), tribunais.descrever(n))
            t, descricao = catalogo[n.chave_tribunal]
            situacao, tag, obs = "aguardando", "aguardando", ""
            if t is None or not t.suportado:
                situacao, tag = "tribunal não suportado", "aviso"
            if not n.digito_confere:
                obs, tag = "dígito verificador não confere", "aviso"
            if self.leitura.senhas.get(n.formatado):
                obs = (obs + "; " if obs else "") + "senha informada na lista"
            self._notas[n.formatado] = obs
            arv.insert("", "end", iid=n.formatado, tags=(tag,),
                       values=(i, n.formatado, descricao, situacao, "", obs))

    def _resumir_lista(self) -> None:
        if self.leitura is None or not self.leitura.processos:
            self.info_lista.configure(text="")
            self.info_lista.grid_remove()
            self.faixa_lista.grid_remove()
            return
        leitura = self.leitura
        numeros = leitura.processos
        por_tribunal: dict[str, int] = {}
        nao_suportados = 0
        catalogo: dict[str, object] = {}
        for n in numeros:
            if n.chave_tribunal not in catalogo:
                catalogo[n.chave_tribunal] = tribunais.por_numero(n)
            t = catalogo[n.chave_tribunal]
            if t is None or not t.suportado:
                nao_suportados += 1
                continue
            por_tribunal[t.sigla] = por_tribunal.get(t.sigla, 0) + 1
        partes = [plural(len(numeros), "processo")]
        if por_tribunal:
            partes.append(", ".join(f"{q} do {s}" for s, q in por_tribunal.items()))
        dependentes = sum(1 for n in numeros if n.e_dependente)
        if dependentes:
            partes.append(plural(dependentes, "incidente"))
        origem = Path(leitura.origem).name if leitura.origem else "lista colada"
        formato = f" ({leitura.formato})" if leitura.formato and leitura.formato != "texto colado" else ""
        self.info_lista.configure(text=f"{origem}{formato} · " + " · ".join(partes))
        self.info_lista.grid()

        avisos = []
        errados = leitura.digito_errado
        if errados:
            exemplos = ", ".join(n.formatado for n in errados[:3])
            mais = "…" if len(errados) > 3 else ""
            avisos.append(f"{plural(len(errados), 'número tem', 'números têm')} o dígito "
                          f"verificador errado — provável erro de digitação ({exemplos}{mais}). "
                          "Confira na relação antes de baixar.")
        if leitura.corrompidos:
            uma = len(leitura.corrompidos) == 1
            avisos.append(f"{plural(len(leitura.corrompidos), 'linha')} da planilha "
                          f"{'guarda' if uma else 'guardam'} o número como NÚMERO, e o Excel "
                          "corrompe os últimos dígitos: "
                          f"{'ficou' if uma else 'ficaram'} de fora de propósito. Formate a "
                          "coluna como Texto e abra de novo.")
        if nao_suportados:
            avisos.append(f"{plural(nao_suportados, 'processo é', 'processos são')} de tribunal "
                          "cujo sistema o programa ainda não baixa (PJe, Projudi): "
                          + ("fica marcado" if nao_suportados == 1 else "ficam marcados")
                          + " na tabela.")
        avisos += [_maiuscula(a) for a in leitura.avisos[:3]]
        if avisos:
            self.faixa_lista.definir(texto="\n".join(f"•  {a}" for a in avisos),
                                     titulo="Confira antes de baixar")
            self.faixa_lista.grid()
        else:
            self.faixa_lista.grid_remove()

    def _montar_acessos(self) -> None:
        for w in self.area_acessos.winfo_children():
            w.destroy()
        self.editores = []
        portais = portais_da_lista(self.numeros)
        if not portais:
            texto = ("Os portais aparecem aqui quando você abrir a relação." if not self.numeros
                     else "Nenhum processo desta relação é de tribunal com e-SAJ ou eProc.")
            r = ttk.Label(self.area_acessos, text=texto, foreground=estilo.TINTA_FRACA)
            r.grid(row=0, column=0, sticky="w")
            return
        for i, t in enumerate(portais):
            quadro = ttk.Frame(self.area_acessos, style="Bloco.TFrame", padding=(px(18), px(14)))
            quadro.grid(row=i, column=0, sticky="ew", pady=(0 if i == 0 else px(10), 0))
            quadro.columnconfigure(0, weight=1)
            principal = tribunais.por_sigla(t.sigla)
            alternativo = principal is not None and principal.sistema != t.sistema
            nota = (f"Usado para os processos que não forem achados no "
                    f"{principal.nome_sistema}." if alternativo else "")
            ed = EditorAcesso(quadro, self.janela, t, rotulo=f"{t.sigla} · {t.nome_sistema}",
                              nota=nota, ao_mudar=self._atualizar_rodape)
            ed.grid(row=0, column=0, sticky="ew")
            self.editores.append(ed)

    def _destino(self) -> Path:
        if self.destino_escolhido is not None:
            return self.destino_escolhido
        return self.cfg.pasta_processos / (self.nome_lote or "Nova relação")

    def _atualizar_destino(self) -> None:
        self.rotulo_destino.configure(text=str(self._destino()))

    # ============================================================ rodapé
    def _atualizar_rodape(self) -> None:
        """Texto, barra e botões do rodapé conforme o estado.

        Chamado a cada evento 'status' e 'progresso' do motor (vários por
        processo). Os botões só são refeitos quando MUDAM: destruí-los e
        recriá-los a cada evento fazia o "Parar" piscar e perder o clique
        (o botão apertado sumia antes de o mouse ser solto).
        """
        estado = self.estado
        n = len(self.numeros)
        imagem = ""
        barra = None                         # None | ("indeterminate",) | ("determinate", valor, linha)
        if estado == "lendo":
            texto, cor = "Lendo a relação…", estilo.TINTA
            barra = ("indeterminate", 0, 1)
            acoes = ("principal", n, False)
        elif estado == "baixando":
            feitos, total, atual = self.progresso
            total = total or n
            texto = f"{min(feitos + 1, total)} de {total}"
            if atual:
                texto += f" · {atual}"
            if self.status_texto:
                texto += f"\n{self.status_texto}"
            cor = estilo.TINTA
            barra = ("determinate", 1000 * feitos / total if total else 0, 2)
            acoes = ("parar", self.tarefa.parar.is_set())
        elif estado == "fim" and self.resumo is not None:
            r = self.resumo
            falhas = r.a_refazer()
            ok = not r.falhas and not r.pendentes
            imagem = estilo.imagem("sinal-ok" if ok else "sinal-aviso", px(22)) or ""
            minutos = getattr(r, "minutos", 0) or 0
            duracao = f" Em {minutos:.0f} min." if minutos >= 1 else ""
            texto, cor = _maiuscula(r.texto()) + duracao, estilo.TINTA
            acoes = ("fim", len(falhas))
        else:
            if n:
                falta = [e for e in self.editores if not e.tem_credenciais()]
                texto = (f"Pronto para baixar {plural(n, 'processo')} para a pasta "
                         f"“{self._destino().name}”.")
                if falta:
                    nomes = ", ".join(f"{e.tribunal.sigla} · {e.tribunal.nome_sistema}"
                                      for e in falta)
                    texto += (f"\nFalta a senha de {nomes} (passo 2): sem ela, você entra "
                              "manualmente na janela do navegador.")
                cor = estilo.TINTA
            else:
                texto, cor = "Abra a relação de processos para começar.", estilo.TINTA_FRACA
            acoes = ("principal", n, bool(n) and not self.tarefa.ativa)

        self.icone_rodape.configure(image=imagem)
        self.texto_rodape.configure(text=texto, foreground=cor)
        self._barra(barra)
        if acoes != getattr(self, "_chave_acoes", None):
            self._chave_acoes = acoes
            self._montar_acoes(acoes)

    def _barra(self, definicao) -> None:
        b = self.barra_rodape
        if definicao is None:
            if getattr(self, "_modo_barra", None) is not None:
                b.stop()
                b.grid_remove()
            self._modo_barra = None
            return
        modo, valor, linha = definicao
        if modo != getattr(self, "_modo_barra", None):
            b.stop()
            b.configure(mode=modo, value=0)
            b.grid(row=linha, column=1, sticky="ew", pady=(px(6), 0))
            if modo == "indeterminate":
                b.start(12)
            self._modo_barra = modo
        if modo == "determinate":
            b.configure(value=valor)

    def _montar_acoes(self, acoes: tuple) -> None:
        for w in self.acoes_rodape.winfo_children():
            w.destroy()
        tipo = acoes[0]
        if tipo == "parar":
            parar = estilo.botao(self.acoes_rodape, "Parar", self.parar, "cuidado", grande=True)
            parar.pack(side="left")
            if acoes[1]:
                parar.state(["disabled"])
        elif tipo == "fim":
            estilo.botao(self.acoes_rodape, "Abrir a pasta", self.abrir_destino,
                         "principal").pack(side="left")
            if acoes[1]:
                estilo.botao(self.acoes_rodape, f"Tentar de novo ({acoes[1]})",
                             self.tentar_de_novo).pack(side="left", padx=(px(8), 0))
            estilo.botao(self.acoes_rodape, "Compartilhar com IA  →",
                         lambda: self.janela.mostrar("compartilhar")).pack(
                side="left", padx=(px(8), 0))
        else:
            self._botao_principal(acoes[1], habilitado=acoes[2])

    def _botao_principal(self, n: int, habilitado: bool) -> None:
        texto = f"Baixar {plural(n, 'processo')}" if n else "Baixar processos"
        b = estilo.botao(self.acoes_rodape, texto, self.iniciar, "principal", grande=True)
        b.pack(side="left")
        if not habilitado:
            b.state(["disabled"])

    # ============================================================ ações
    def _opcao(self, chave: str) -> None:
        if chave == "separar_sigilosos" and not self._vars[chave].get() and not dialogos.confirmar(
                self.janela.raiz, "Separar os sigilosos",
                "Sem a separação, os processos em segredo de justiça ficam na pasta do lote, "
                "junto com os demais. No acervo, eles passam a ser lidos pela IA e copiados "
                "para a nuvem, se o espelho estiver ligado.\n\nDesmarcar mesmo assim?"):
            self._vars[chave].set(True)
            return
        self.cfg.definir("download", chave, self._vars[chave].get())

    def alterar_destino(self) -> None:
        nova = dialogos.escolher_pasta(self.janela.raiz, "Pasta onde salvar os PDFs",
                                       self._destino().parent)
        if nova:
            self.destino_escolhido = nova
            self._atualizar_destino()
            self._atualizar_rodape()

    def abrir_destino(self) -> None:
        try:
            sistema.abrir_pasta(self._destino())
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Abrir a pasta", str(erro))

    def _abrir_linha(self, _evento=None) -> None:
        item = self.arvore.focus()
        if not item:
            return
        alvo = self._destino() / f"{cnj.ler(item).nome_arquivo}.pdf"
        if alvo.exists():
            try:
                sistema.abrir_arquivo(alvo)
            except Exception as erro:
                dialogos.erro(self.janela.raiz, "Abrir o PDF", str(erro))

    def iniciar(self, numeros: list | None = None, pular_baixados: bool = False) -> None:
        if self.tarefa.ativa:
            return
        numeros = list(numeros if numeros is not None else self.numeros)
        if not numeros:
            return
        for ed in self.editores:
            ed.salvar()
        errados = [n for n in numeros if not n.digito_confere]
        if errados:
            resposta = messagebox.askyesnocancel(
                "Dígito verificador",
                f"{plural(len(errados), 'número tem', 'números têm')} o dígito verificador "
                "errado — provavelmente erro de digitação, e o portal pode abrir OUTRO processo "
                "ou nenhum.\n\nSim: baixar todos mesmo assim.\nNão: deixar "
                f"{'esse número' if len(errados) == 1 else 'esses números'} de fora.",
                parent=self.janela.raiz)
            if resposta is None:
                return
            if resposta is False:
                numeros = [n for n in numeros if n.digito_confere]
                if not numeros:
                    return
        falta = [e for e in self.editores if not e.tem_credenciais()]
        if falta:
            nomes = ", ".join(f"{e.tribunal.sigla} · {e.tribunal.nome_sistema}" for e in falta)
            if not dialogos.confirmar(
                    self.janela.raiz, "Falta a senha",
                    f"Falta a senha de {nomes}.\n\nSem ela, o navegador abre na tela de entrada "
                    "e você entra manualmente; depois o programa continua sozinho. Continuar?"):
                return
        try:
            opcoes = servicos.opcoes_download(self.cfg)
        except Exception as erro:
            self.janela.erro_inesperado(erro)
            return
        if pular_baixados:
            opcoes.pular_baixados = True
        destino = self._destino()
        senhas = dict(self.leitura.senhas) if self.leitura is not None else {}
        cofre = servicos.CofreMisto(self.janela.cofre(), self.janela.credenciais_sessao)
        ctx = ContextoTela(self.postar, self.tarefa.parar)
        recusa = self.tarefa.iniciar(self._trabalhar, numeros, destino, opcoes, ctx, senhas, cofre)
        if recusa:
            dialogos.informar(self.janela.raiz, "Aguarde um instante", recusa)
            return
        for n in numeros:
            if self.arvore.exists(n.formatado):
                valores = list(self.arvore.item(n.formatado, "values"))
                valores[3], valores[4] = "na fila", ""
                self.arvore.item(n.formatado, values=valores, tags=("aguardando",))
        self.estado = "baixando"
        self.resumo = None
        self.progresso = (0, len(numeros), "")
        self.status_texto = "Preparando o navegador…"
        self._destino_lote = destino
        self._falhas_login = []
        self.faixa_portal.grid_remove()
        self._atualizar_rodape()
        self.janela.atualizar_indicadores()

    def _trabalhar(self, numeros, destino, opcoes, ctx, senhas, cofre) -> None:
        try:
            resumo = servicos.baixar_lote(numeros, destino, opcoes, ctx, senhas, cofre, self.cfg)
        except Exception as erro:            # LoginFalhou, PortalIndisponivel, componente...
            log.error("o lote não pôde ser baixado: %s", erro)
            self.postar("falhou", erro)
            return
        self.postar("fim", resumo)

    def parar(self) -> None:
        if self.tarefa.ativa:
            self.tarefa.pedir_parada()
            self.status_texto = "Parando depois do processo atual…"
            self._atualizar_rodape()

    def tentar_de_novo(self) -> None:
        """Roda a relação INTEIRA de novo, pulando o que já está na pasta.

        Rodar só os que falharam regravaria o relatório do lote só com eles;
        assim ele continua completo, e os baixados passam em segundos.
        """
        if self.resumo is None or not self.resumo.a_refazer():
            return
        self.iniciar(pular_baixados=True)

    # ============================================================ eventos
    def ao_evento(self, tipo: str, dado) -> None:
        if tipo == "status":
            self.status_texto = str(dado or "")
            if self.estado == "baixando":
                self._atualizar_rodape()
        elif tipo == "progresso":
            feitos, total, atual = dado
            self.progresso = (feitos, total, atual)
            if atual and self.arvore.exists(atual):
                valores = list(self.arvore.item(atual, "values"))
                valores[3] = "baixando…"
                self.arvore.item(atual, values=valores, tags=("andamento",))
                self.arvore.see(atual)
            self._atualizar_rodape()
        elif tipo == "item":
            self._atualizar_linha(dado)
            # um processo concluído = o login já passou: o recado sai de cena
            if dado.situacao:
                self._recolher_recado_portal()
        elif tipo == "avisar":
            titulo, mensagem = dado
            if str(titulo).startswith(PREFIXO_LOGIN_RECUSADO):
                self._falhas_login.append((str(titulo), str(mensagem)))
            self.faixa_portal.definir(texto=mensagem, titulo=titulo)
            self.faixa_portal.grid()
            componentes.mostrar_no_rolavel(self.faixa_portal)
            estilo.piscar_na_barra(self.janela.raiz)
        elif tipo == "pedir_codigo":
            # Com a audiência gravando na tela, a página fica onde está: o
            # diálogo aparece por cima e F1 a F8 continuam marcando quem fala
            # (trocar de página no meio da audiência desligava os atalhos, e
            # F1 abria a Ajuda).
            if not self.janela.audiencia_na_tela():
                self.janela.mostrar(self.nome)
            dialogos.DialogoCodigo(self.janela.raiz, dado)
        elif tipo == "fim":
            self._terminou(dado)
        elif tipo == "falhou":
            self.estado = "pronto" if self.numeros else "vazio"
            self.status_texto = ""
            self._atualizar_rodape()
            if isinstance(dado, servicos.ComponenteAusente):
                dialogos.erro(self.janela.raiz, "Componente ausente", str(dado))
            else:
                dialogos.erro(self.janela.raiz, "O download não pôde ser feito",
                              f"{_maiuscula(str(dado))}\n\nVeja os detalhes técnicos, no fim "
                              "desta página.")
        elif tipo == "_tarefa_fim":
            if self.estado == "baixando" and not self.tarefa.ativa and dado is self.tarefa:
                # terminou sem 'fim' nem 'falhou' (não deveria): destrava a tela
                self.after(300, self._destravar)

    def _destravar(self) -> None:
        if self.estado == "baixando" and not self.tarefa.ativa:
            self.estado = "pronto" if self.numeros else "vazio"
            self._atualizar_rodape()

    def _atualizar_linha(self, r) -> None:
        iid = r.numero
        if not self.arvore.exists(iid):
            return
        situacao = r.situacao or ""
        if situacao in ("OK", "JA_BAIXADO"):
            tag = "ok"
        elif situacao in _FALHAS:
            tag = "falha"
        else:
            tag = "aguardando"
        obs = [self._notas[iid]] if self._notas.get(iid) else []
        if r.sigiloso:
            obs.append(self._nota_sigilo(r))
        if r.incompleto:
            # o eProc não numera folhas: o que falta são documentos de eventos
            obs.append(f"faltam documentos: {r.incompleto}" if r.sistema == "eproc"
                       else f"faltam as folhas {r.incompleto}")
        if r.detalhe:
            obs.append(r.detalhe)
        valores = list(self.arvore.item(iid, "values"))
        valores[2] = f"{r.tribunal} · {tribunais.NOMES_SISTEMA.get(r.sistema, r.sistema)}" \
            if r.tribunal and r.sistema else valores[2]
        valores[3] = r.rotulo
        valores[4] = r.paginas or ""
        valores[5] = "; ".join(obs)
        self.arvore.item(iid, values=valores, tags=(tag,))

    def _nota_sigilo(self, r) -> str:
        """Onde o sigiloso está DE FATO - e não onde deveria estar.

        Antes a tabela dizia "fora do acervo" sempre, também com a opção
        "Separar os sigilosos" desmarcada ou quando o arquivo, aberto em
        outro programa, não pôde ser movido.
        """
        if not r.arquivo:
            return "sigiloso"                      # não baixado (sem senha, erro…)
        pasta_lote = getattr(self, "_destino_lote", None) or self._destino()
        if Path(r.arquivo).parent != Path(pasta_lote):
            # o motor o levou para a pasta de sigilosos (ou já estava lá)
            return ("sigiloso" if "pasta de sigilosos" in (r.detalhe or "")
                    else "sigiloso (na pasta de sigilosos)")
        return "SIGILOSO: ficou na pasta do lote, com os demais"

    def _recolher_recado_portal(self) -> None:
        """O recado passageiro ("Conclua o login…") sai de cena; o de login
        recusado continua à vista, também depois do fim do lote.

        O motor publica os processos do grupo como ERRO, avisa que não
        conseguiu entrar e encerra; o 'fim' chegava no mesmo tique da fila
        e escondia a faixa antes que alguém a lesse - sobrava só "0
        baixados, 37 com problema".
        """
        falhas = getattr(self, "_falhas_login", [])
        if not falhas:
            self.faixa_portal.grid_remove()
            return
        if len(falhas) == 1:
            titulo, texto = falhas[0]
        else:
            titulo = "Não foi possível entrar em alguns portais"
            texto = "\n".join(f"•  {t}: {m}" for t, m in falhas)
        self.faixa_portal.definir(texto=texto, titulo=titulo)
        self.faixa_portal.grid()

    def _terminou(self, resumo) -> None:
        self.resumo = resumo
        self.estado = "fim"
        self.status_texto = ""
        for r in resumo.itens:
            self._atualizar_linha(r)
        self._recolher_recado_portal()
        self._atualizar_rodape()
        estilo.piscar_na_barra(self.janela.raiz)
        log.info("Lote concluído: %s", resumo.texto())
        if self.cfg.flag("compartilhar", "espelhar_automaticamente") and \
                self.cfg.texto("compartilhar", "pasta_nuvem"):
            self._espelhar()

    def _espelhar(self) -> None:
        # Nunca durante o fechamento (o lote interrompido ao fechar chega aqui
        # e a janela esperaria a cópia), e sempre interrompível.
        if getattr(self.janela, "_fechando", False):
            return
        from ..compartilhar import nuvem

        destino = Path(self.cfg.texto("compartilhar", "pasta_nuvem"))
        tarefa = self.tarefa_nuvem
        recusa = tarefa.iniciar(nuvem.espelhar, self.cfg.pasta_acervo, destino, None,
                                tarefa.parar.is_set)
        if recusa:
            log.info("espelho na nuvem adiado: %s", recusa)

    # ====================================================== janela e início
    def ao_mostrar(self) -> None:
        for chave, var in self._vars.items():
            var.set(self.cfg.flag("download", chave))
        # O mesmo portal pode ter sido mudado nas Configurações ou no
        # assistente enquanto esta página estava escondida.
        for ed in self.editores:
            ed.recarregar()
        if self.estado in ("vazio", "pronto"):
            self._atualizar_destino()
            self._atualizar_rodape()

    def ao_esconder(self) -> None:
        # Clicar na barra lateral não tira o foco do campo: sem isto, a senha
        # digitada e não "confirmada" (Tab/Enter) não chegava às outras páginas.
        for ed in self.editores:
            ed.salvar()

    def indicador(self):
        if self.tarefa.ativa:
            feitos, total, _ = self.progresso
            return (f"{min(feitos + 1, total)}/{total}" if total else "", estilo.AZUL)
        if self.estado == "fim" and self.resumo is not None and self.resumo.falhas:
            return ("", estilo.AMBAR)
        return None

    def resumo_ao_vivo(self):
        if self.tarefa.ativa:
            feitos, total, _ = self.progresso
            return (f"Baixando agora: {min(feitos + 1, total)} de {total}", "ocupado")
        if self.estado == "fim" and self.resumo is not None:
            return (_maiuscula(self.resumo.texto()), "ok" if not self.resumo.falhas else "aviso")
        return None

    def trabalho_em_andamento(self) -> list[str]:
        if self.tarefa.ativa:
            feitos, total, _ = self.progresso
            return [f"Baixar processos ({feitos} de {total} concluídos; o relatório é salvo)"]
        return [t.nome for t in (self.tarefa_ler, self.tarefa_nuvem) if t.ativa]


def _maiuscula(texto: str) -> str:
    texto = (texto or "").strip()
    return texto[:1].upper() + texto[1:]
