"""Ajuda: o passo a passo das três funções, atalhos e o que fazer quando algo falha.

Texto curto e direto (o usuário é magistrado, não técnico), e sempre com o
caminho para resolver: o botão que abre o manual, a pasta de registros ou a
verificação da instalação.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..nucleo import caminhos, sistema
from . import componentes, dialogos, estilo
from .componentes import Pagina
from .estilo import px

GUIAS = (
    ("cartao-baixar", "Baixar processos", (
        "Abra a relação: planilha do Excel, documento do Word, PDF, CSV, texto ou um link "
        "compartilhado. Os números são encontrados em qualquer coluna ou parágrafo.",
        "Confira o acesso: usuário e senha, certificado digital ou entrada manual. Se o portal "
        "pedir um código (e-mail ou aplicativo autenticador), uma janela pede que você o digite.",
        "Clique em “Baixar”. Cada processo vira um PDF com o número no nome, na pasta do lote. "
        "Os sigilosos vão para a pasta Sigilosos, fora do acervo.",
    )),
    ("cartao-transcrever", "Transcrever audiência", (
        "Digite o número do processo e escolha o microfone (Testar mostra o nível do som).",
        "Clique no botão redondo para iniciar. Marque quem está falando com os botões F1 a F8 "
        "— clique duas vezes num botão para trocar o nome.",
        "Ao encerrar, o documento do Word fica na pasta Transcricoes, com o número do processo "
        "no nome. A gravação fica guardada para conferência.",
    )),
    ("cartao-compartilhar", "Compartilhar com IA", (
        "Clique em “Preparar arquivos para IA”: o programa extrai o texto dos autos (com a "
        "folha marcada) e escreve as instruções de trabalho na pasta do acervo.",
        "Abra o acervo no Claude Code, no Cowork ou no ChatGPT Work. O caminho e o pedido "
        "inicial vão copiados — cole com Ctrl+V.",
        "A IA é apoio: confira sempre as folhas citadas e revise o que ela sugerir.",
    )),
)

ATALHOS = (("Ctrl+1 … Ctrl+6", "ir para cada página (Início, Baixar, Transcrever…)"),
           ("F1 … F8", "na página Transcrever: quem está falando"),
           ("F1", "nas outras páginas: esta Ajuda"),
           ("Enter", "confirmar o código de verificação"))

PROBLEMAS = (
    ("O login no portal falhou", "Confira usuário e senha em Configurações › Acessos e use "
     "“Testar login”. Senha expirada se troca no próprio portal."),
    ("Um processo ficou “não encontrado”", "Confira o número. Em tribunal que está mudando de "
     "sistema (TJAL, TJSP, TJAC), o programa procura também no eProc."),
    ("O microfone não mostra nível", "No Windows: Configurações › Privacidade e segurança › "
     "Microfone › permita o acesso aos aplicativos da área de trabalho."),
    ("A transcrição atrasa muito", "Use o modelo “base” para a audiência ao vivo (Configurações "
     "› Transcrição) e revise depois com o modelo preciso."),
    ("A luz caiu no meio da audiência", "Abra Transcrever audiência e use “Recuperar transcrição "
     "interrompida”: o que foi falado até a queda está salvo."),
    ("Algo não funciona", "Use “Verificar a instalação” e, se preciso, rode o INSTALAR.bat de "
     "novo: ele completa o que faltar sem apagar nada."),
)


class PaginaAjuda(Pagina):
    nome = "ajuda"
    titulo = "Ajuda"
    icone = "ajuda"

    def montar(self) -> None:
        corpo, _, _ = componentes.estrutura(
            self, "Ajuda", "O essencial de cada função, em três passos. O manual completo está "
                           "na pasta do programa (MANUAL.md).")
        corpo.columnconfigure(0, weight=1)

        guias = ttk.Frame(corpo)
        guias.grid(row=0, column=0, sticky="ew")
        guias.columnconfigure((0, 1, 2), weight=1, uniform="guias")
        for i, (icone, titulo, passos) in enumerate(GUIAS):
            cartao = componentes.Cartao(guias, padding=(px(20), px(18)))
            cartao.grid(row=0, column=i, sticky="nsew",
                        padx=(0 if i == 0 else px(8), 0 if i == 2 else px(8)))
            cartao.columnconfigure(1, weight=1)
            cab = ttk.Frame(cartao)
            cab.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(12)))
            tk.Label(cab, image=estilo.imagem(icone, px(32)) or "",
                     background=estilo.PAPEL).pack(side="left")
            ttk.Label(cab, text=titulo, font=estilo.FONTE_SECAO).pack(side="left", padx=(px(10), 0))
            for k, passo in enumerate(passos, 1):
                ttk.Label(cartao, text=f"{k}.", font=estilo.FONTE_NEGRITO,
                          foreground=estilo.AZUL).grid(row=k, column=0, sticky="nw",
                                                       padx=(0, px(8)), pady=(0, px(8)))
                r = ttk.Label(cartao, text=passo, justify="left", foreground=estilo.TINTA)
                r.grid(row=k, column=1, sticky="new", pady=(0, px(8)))
                estilo.acompanhar_largura(r)

        componentes.secao(corpo, "Quando algo não sai como esperado").grid(
            row=1, column=0, sticky="ew", pady=(px(28), px(10)))
        lista = ttk.Frame(corpo, style="Bloco.TFrame", padding=(px(6), px(4)))
        lista.grid(row=2, column=0, sticky="ew")
        lista.columnconfigure(1, weight=1)
        for i, (problema, solucao) in enumerate(PROBLEMAS):
            if i:
                componentes.divisoria(lista).grid(row=2 * i - 1, column=0, columnspan=2,
                                                  sticky="ew", padx=px(12))
            ttk.Label(lista, text=problema, font=estilo.FONTE_NEGRITO, justify="left",
                      wraplength=px(230)).grid(row=2 * i, column=0, sticky="nw",
                                               padx=(px(12), px(18)), pady=px(10))
            r = ttk.Label(lista, text=solucao, foreground=estilo.TINTA_FRACA, justify="left")
            r.grid(row=2 * i, column=1, sticky="new", padx=(0, px(12)), pady=px(10))
            estilo.acompanhar_largura(r)

        componentes.secao(corpo, "Atalhos do teclado").grid(row=3, column=0, sticky="ew",
                                                            pady=(px(28), px(10)))
        atalhos = ttk.Frame(corpo)
        atalhos.grid(row=4, column=0, sticky="ew")
        for i, (tecla, efeito) in enumerate(ATALHOS):
            tk.Label(atalhos, text=tecla, font=estilo.FONTE_MONO, background=estilo.SUPERFICIE,
                     foreground=estilo.TINTA, padx=px(8), pady=px(2)).grid(
                row=i, column=0, sticky="w", pady=px(3))
            ttk.Label(atalhos, text=efeito, foreground=estilo.TINTA_FRACA).grid(
                row=i, column=1, sticky="w", padx=(px(12), 0))

        botoes = ttk.Frame(corpo)
        botoes.grid(row=5, column=0, sticky="w", pady=(px(28), 0))
        estilo.botao(botoes, "Abrir o manual", self._manual, "tonal").pack(side="left")
        estilo.botao(botoes, "Verificar a instalação", self._verificar).pack(side="left",
                                                                           padx=(px(8), 0))
        estilo.botao(botoes, "Abrir a pasta de registros",
                     lambda: self._abrir(caminhos.LOGS, pasta=True)).pack(side="left",
                                                                          padx=(px(8), 0))

    def _manual(self) -> None:
        for nome in ("MANUAL.md", "LEIA-ME.txt", "README.md"):
            alvo = caminhos.RAIZ / nome
            if alvo.exists():
                self._abrir(alvo)
                return
        dialogos.informar(self.janela.raiz, "Manual", "O manual não foi encontrado na pasta do "
                                                     "programa.")

    def _verificar(self) -> None:
        config = self.janela.paginas.get("config")
        self.janela.mostrar("config")
        if config is not None and hasattr(config, "abas"):
            config.abas.select(len(config.abas.tabs()) - 1)
            if hasattr(config, "verificar"):
                config.verificar()

    def _abrir(self, alvo, pasta: bool = False) -> None:
        try:
            sistema.abrir_pasta(alvo) if pasta else sistema.abrir_arquivo(alvo)
        except Exception as erro:
            dialogos.erro(self.janela.raiz, "Abrir", str(erro))
