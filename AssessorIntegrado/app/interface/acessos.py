"""Editor do acesso a um portal: forma de entrar, usuário, senha e "Lembrar".

Usado em três lugares - o assistente de primeiro uso, o passo 2 da página
Baixar processos e a aba Acessos das Configurações - para a regra ser uma
só: tudo é salvo NA HORA (sem botão Salvar; na base, o modo de login salvava
ao clicar, usuário e senha exigiam botão e as pastas exigiam reiniciar).

A senha só vai para o disco com "Lembrar neste computador" marcado, e
então cifrada pela DPAPI do Windows (nucleo.cofre_senhas). Desmarcado, ela
vale só enquanto o programa estiver aberto (janela.credenciais_sessao).
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from . import estilo
from .componentes import EstadoLinha
from .estilo import px

log = logging.getLogger("interface.acessos")

MODOS = (
    ("senha", "Usuário e senha"),
    ("certificado", "Certificado digital"),
    ("manual", "Entrar manualmente"),
)
EXPLICACAO = {
    "senha": "O programa entra por você. Se o portal pedir o código enviado por e-mail "
             "ou do aplicativo autenticador, uma janela pede que você o digite.",
    "certificado": "O navegador abre à vista: conecte o token (ou o cartão) e digite o PIN "
                   "quando o Web Signer pedir.",
    "manual": "O navegador abre na tela de entrada do portal: entre como de costume, e o "
              "programa continua sozinho depois que você entrar.",
}


def modos_do_sistema(sistema: str) -> list[tuple[str, str]]:
    # O eProc não tem o Web Signer do e-SAJ: certificado ali é "manual".
    return [m for m in MODOS if not (sistema == "eproc" and m[0] == "certificado")]


class EditorAcesso(ttk.Frame):
    """Acesso a um portal ('esaj:TJAL'). 'janela' dá cfg, cofre e a sessão."""

    def __init__(self, pai, janela, tribunal, rotulo: str = "", nota: str = "",
                 ao_mudar=None, largura_campo: int = 26):
        super().__init__(pai)
        self.janela = janela
        self.tribunal = tribunal
        self.portal = tribunal.portal
        self.sistema = tribunal.sistema
        self.ao_mudar = ao_mudar
        self.columnconfigure(0, weight=1)

        cabeca = ttk.Frame(self)
        cabeca.grid(row=0, column=0, sticky="ew")
        cabeca.columnconfigure(1, weight=1)
        ttk.Label(cabeca, text=rotulo or f"{tribunal.sigla} · {tribunal.nome_sistema}",
                  font=estilo.FONTE_NEGRITO).grid(row=0, column=0, sticky="w")
        self.estado = EstadoLinha(cabeca, "", "neutro")
        self.estado.grid(row=0, column=1, sticky="w", padx=(px(10), 0))
        if nota:
            n = ttk.Label(self, text=nota, foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA,
                          justify="left")
            n.grid(row=1, column=0, sticky="ew", pady=(px(1), 0))
            estilo.acompanhar_largura(n)

        modo_atual = (janela.cfg.texto(self.sistema, "login") or "senha").lower()
        modos = modos_do_sistema(self.sistema)
        if modo_atual not in [m for m, _ in modos]:
            modo_atual = "senha" if self.sistema == "eproc" else modo_atual
        self.modo = tk.StringVar(value=modo_atual)
        linha_modos = ttk.Frame(self)
        linha_modos.grid(row=2, column=0, sticky="w", pady=(px(6), 0))
        for i, (valor, texto) in enumerate(modos):
            ttk.Radiobutton(linha_modos, text=texto, value=valor, variable=self.modo,
                            command=self._modo_mudou).grid(row=0, column=i, sticky="w",
                                                           padx=(0 if i == 0 else px(18), 0))

        # --- usuário e senha
        self.credenciais = ttk.Frame(self)
        self.credenciais.columnconfigure((0, 1), weight=1, uniform="cred")
        usuario, senha = self._guardadas()
        self._senha_guardada = senha
        self.usuario = tk.StringVar(value=usuario or janela.credenciais_sessao.get(
            self.portal, ("", ""))[0])
        self.senha = tk.StringVar(value=janela.credenciais_sessao.get(self.portal, ("", ""))[1])
        self.lembrar = tk.BooleanVar(value=bool(usuario and senha) or not
                                     janela.credenciais_sessao.get(self.portal))
        rot_usuario = "CPF ou usuário" if self.sistema == "esaj" else "Usuário (CPF ou sigla)"
        q1, self.e_usuario = _campo(self.credenciais, rot_usuario, self.usuario, largura_campo)
        q1.grid(row=0, column=0, sticky="ew", padx=(0, px(12)))
        q2, self.e_senha = _campo(self.credenciais, "Senha", self.senha, largura_campo, show="•")
        q2.grid(row=0, column=1, sticky="ew")
        self.mostrar = tk.BooleanVar(value=False)
        opcoes = ttk.Frame(self.credenciais)
        opcoes.grid(row=1, column=0, columnspan=2, sticky="w", pady=(px(6), 0))
        ttk.Checkbutton(opcoes, text="Lembrar neste computador (senha cifrada pelo Windows)",
                        variable=self.lembrar, command=self.salvar).pack(side="left")
        ttk.Checkbutton(opcoes, text="Mostrar a senha", variable=self.mostrar,
                        command=self._mostrar).pack(side="left", padx=(px(18), 0))
        for e in (self.e_usuario, self.e_senha):
            e.bind("<FocusOut>", lambda _e: self.salvar(), add="+")
            e.bind("<Return>", lambda _e: self.salvar(), add="+")

        self.explicacao = ttk.Label(self, text="", foreground=estilo.TINTA_FRACA,
                                    font=estilo.FONTE_NOTA, justify="left")
        estilo.acompanhar_largura(self.explicacao)
        self._aplicar_modo()

    # ------------------------------------------------------------- dados
    def _guardadas(self) -> tuple[str, str]:
        try:
            return self.janela.cofre().obter(self.portal)
        except Exception as erro:
            log.debug("cofre ilegível para %s: %s", self.portal, erro)
            return "", ""

    def _senha_conhecida(self) -> str:
        """A digitada agora, a guardada no cofre ou a "só por agora" da sessão
        (posta por OUTRO editor do mesmo portal, ex.: nas Configurações)."""
        sessao = self.janela.credenciais_sessao.get(self.portal) or ("", "")
        return self.senha.get() or self._senha_guardada or sessao[1]

    def tem_credenciais(self) -> bool:
        if self.modo.get() != "senha":
            return True
        return bool(self.usuario.get().strip() and self._senha_conhecida())

    def credenciais_atuais(self) -> tuple[str, str] | None:
        usuario = self.usuario.get().strip()
        senha = self._senha_conhecida()
        return (usuario, senha) if usuario and senha else None

    def recarregar(self) -> None:
        """Relê forma de entrar, cofre e sessão sem perder o que está digitado.

        O mesmo portal aparece em até três editores (assistente, Baixar,
        Configurações). Sem reler, o editor que ficou montado guardava o
        estado antigo: mandava "Falta a senha" com a senha já guardada, ou -
        pior - regravava no cofre, ao clicar em Baixar, a senha que o usuário
        tinha acabado de mandar esquecer.
        """
        modo = (self.janela.cfg.texto(self.sistema, "login") or "senha").lower()
        if modo in [m for m, _ in modos_do_sistema(self.sistema)] and modo != self.modo.get():
            self.modo.set(modo)
        usuario, senha = self._guardadas()
        self._senha_guardada = senha
        sessao = self.janela.credenciais_sessao.get(self.portal)
        if usuario and senha:
            self.lembrar.set(True)
        elif sessao:
            self.lembrar.set(False)
            usuario = usuario or sessao[0]
        if usuario and not self.usuario.get().strip():
            self.usuario.set(usuario)
        self._aplicar_modo()

    # ------------------------------------------------------------ salvar
    def _modo_mudou(self) -> None:
        self.janela.cfg.definir(self.sistema, "login", self.modo.get())
        self._aplicar_modo()
        if self.ao_mudar:
            self.ao_mudar()

    def salvar(self) -> None:
        """Grava o que estiver nos campos (chamado a cada saída de campo)."""
        usuario = self.usuario.get().strip()
        senha = self._senha_conhecida()
        sessao = self.janela.credenciais_sessao
        try:
            if self.lembrar.get():
                # Só troca a sessão pelo cofre quando há o que guardar: um
                # editor vazio não apaga a senha "só por agora" de outro.
                if usuario and senha:
                    self.janela.cofre().guardar(self.portal, usuario, senha)
                    self._senha_guardada = senha
                    self.senha.set("")
                    sessao.pop(self.portal, None)
            else:
                if self._senha_guardada:
                    self.janela.cofre().apagar(self.portal)
                    self._senha_guardada = ""
                if usuario and senha:
                    sessao[self.portal] = (usuario, senha)
        except Exception as erro:
            log.warning("não consegui guardar a senha de %s: %s", self.portal, erro)
            self.estado.definir("Não consegui guardar a senha neste computador.", "erro")
            return
        self._atualizar_estado()
        if self.ao_mudar:
            self.ao_mudar()

    def _mostrar(self) -> None:
        self.e_senha.configure(show="" if self.mostrar.get() else "•")

    def _aplicar_modo(self) -> None:
        modo = self.modo.get()
        if modo == "senha":
            self.credenciais.grid(row=3, column=0, sticky="ew", pady=(px(10), 0))
        else:
            self.credenciais.grid_remove()
        self.explicacao.configure(text=EXPLICACAO.get(modo, ""))
        self.explicacao.grid(row=4, column=0, sticky="ew", pady=(px(8), 0))
        self._atualizar_estado()

    def _atualizar_estado(self) -> None:
        modo = self.modo.get()
        if modo != "senha":
            texto, tipo = "", "neutro"
        elif self._senha_guardada:
            texto, tipo = "Senha guardada neste computador", "ok"
        elif self.portal in self.janela.credenciais_sessao:
            texto, tipo = "Senha só por agora (não guardada)", "info"
        else:
            texto, tipo = "Falta informar a senha", "aviso"
        self.estado.definir(texto, tipo)


def _campo(pai, titulo, variavel, largura, **extra):
    quadro = ttk.Frame(pai)
    quadro.columnconfigure(0, weight=1)
    ttk.Label(quadro, text=titulo, foreground=estilo.TINTA_FRACA, font=estilo.FONTE_NOTA).grid(
        row=0, column=0, sticky="w", pady=(0, px(3)))
    e = ttk.Entry(quadro, textvariable=variavel, width=largura, **extra)
    e.grid(row=1, column=0, sticky="ew")
    return quadro, e


def portais_da_lista(numeros) -> list:
    """Os portais (tribunal + sistema) que uma relação vai usar, na ordem.

    Tribunal em transição (TJAL, TJSP, TJAC) entra duas vezes: o sistema
    principal e o alternativo, que o motor usa para o que não achar no
    primeiro.
    """
    from ..nucleo import tribunais

    vistos, saida = set(), []
    for n in numeros:
        t = tribunais.por_numero(n)
        if t is None or not t.suportado:
            continue
        for alvo in (t, t.alternativo):
            if alvo is not None and alvo.suportado and alvo.portal not in vistos:
                vistos.add(alvo.portal)
                saida.append(alvo)
    return saida
