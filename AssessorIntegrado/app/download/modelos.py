"""Tipos comuns do download: exceções, situações, opções e resultados.

Este módulo é a "língua" falada entre o motor (motor.py), os portais
(esaj.py, eproc.py) e a tela. Não importa nada pesado: a janela o carrega ao
abrir.

Contrato de um portal (e-SAJ, eProc ou qualquer outro que venha depois):

    portal = Portal(nav, tribunal, opcoes, ctx, credenciais)
    portal.entrar()                                  # login (idempotente)
    r = portal.baixar(numero, destino_pdf, senha)    # -> ResultadoProcesso

``baixar`` devolve o resultado com a situação preenchida quando o desfecho
é DEFINITIVO (OK, NAO_ENCONTRADO, SEM_ACESSO, SIGILOSO_SEM_SENHA) - repetir
não mudaria nada. Falha que PODE ser passageira (rede, portal lento, tela
que escapou) sai como exceção comum, e o motor tenta de novo. Três
exceções têm sentido próprio para o motor:

* ``SessaoPerdida`` - o motor chama ``entrar()`` de novo e repete o item;
* ``LoginFalhou`` - não adianta insistir: o grupo do tribunal é encerrado;
* ``Cancelado`` - o usuário pediu para parar; o item volta para a fila.

``destino_pdf`` é uma pasta provisória, fora do acervo: a capa e as
gravações vão para ``destino_pdf.parent / "_controle"``, e o motor leva tudo
para o lote (ou para a pasta de sigilosos) só depois de saber se o processo
é sigiloso. O portal pode expor ``sigilosos_apurados`` (conjunto de
``Numero.nome_arquivo``): o sigilo que ele apurou vale mesmo para uma
tentativa que terminou em exceção.

Por conveniência, um portal também pode LEVANTAR ``ProcessoNaoEncontrado``,
``SemAcesso`` ou ``SigilosoSemSenha`` em vez de devolver o resultado: o
motor converte cada uma na situação correspondente, sem repetir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..nucleo import caminhos


# ------------------------------------------------------------------ exceções
class LoginFalhou(RuntimeError):
    """Credencial recusada, senha expirada, prazo do código ou do certificado
    esgotado. Repetir com a mesma credencial não resolve."""


class PortalIndisponivel(RuntimeError):
    """O portal não pôde ser usado: sem rede, em manutenção, layout novo,
    navegador ausente ou que não abre."""


class SessaoPerdida(RuntimeError):
    """A sessão no portal caiu no meio do trabalho; entrar de novo resolve."""


class Cancelado(RuntimeError):
    """O usuário pediu para parar. Não é erro: o item interrompido fica
    pendente e é baixado na próxima vez."""

    def __init__(self, mensagem: str = "interrompido pelo usuário"):
        super().__init__(mensagem)


class ProcessoNaoEncontrado(RuntimeError):
    """A consulta do portal não achou o número informado."""


class SemAcesso(RuntimeError):
    """O portal achou o processo, mas não liberou os autos para este usuário."""


class SigilosoSemSenha(RuntimeError):
    """Processo em segredo de justiça e a senha não veio (ou não serviu)."""


# ---------------------------------------------------------------- situações
OK = "OK"
JA_BAIXADO = "JA_BAIXADO"
SIGILOSO_SEM_SENHA = "SIGILOSO_SEM_SENHA"
NAO_ENCONTRADO = "NAO_ENCONTRADO"
SEM_ACESSO = "SEM_ACESSO"
NAO_SUPORTADO = "NAO_SUPORTADO"
ERRO = "ERRO"
CANCELADO = "CANCELADO"

SITUACOES = {OK, JA_BAIXADO, SIGILOSO_SEM_SENHA, NAO_ENCONTRADO, SEM_ACESSO,
             NAO_SUPORTADO, ERRO, CANCELADO}

# Como cada situação aparece para o usuário (tabela da tela e terminal).
ROTULOS = {
    "": "aguardando",
    OK: "baixado",
    JA_BAIXADO: "já estava na pasta",
    SIGILOSO_SEM_SENHA: "sigiloso: falta a senha",
    NAO_ENCONTRADO: "não encontrado",
    SEM_ACESSO: "sem acesso",
    NAO_SUPORTADO: "tribunal não suportado",
    ERRO: "falhou",
    CANCELADO: "interrompido",
}

# Situações que pedem providência do usuário (ou nova tentativa).
FALHAS = {ERRO, NAO_ENCONTRADO, SEM_ACESSO, NAO_SUPORTADO, SIGILOSO_SEM_SENHA}

MODOS_LOGIN = ("senha", "certificado", "manual")

# Rótulos da tela que as mensagens dos portais citam: têm de ser os mesmos
# da tela, ou o usuário procura uma opção que não existe.
MOSTRAR_NAVEGADOR = "Mostrar o navegador enquanto baixa"
CAMPO_PRAZO_LOGIN = "Configurações > Acessos, campo 'Esperar o login até (min)'"


def rotulo(situacao: str) -> str:
    return ROTULOS.get(situacao, situacao.lower())


# ----------------------------------------------------------------- resultado
@dataclass
class ResultadoProcesso:
    """Uma linha da tabela (e do relatório). Situação vazia = ainda na fila."""
    ordem: int
    numero: str
    tribunal: str
    sistema: str
    situacao: str = ""
    arquivo: str = ""
    paginas: int = 0
    documentos: int = 0
    sigiloso: bool = False
    incompleto: str = ""          # folhas que o portal não ofereceu ("12-15, 40")
    detalhe: str = ""
    midias: list[str] = field(default_factory=list)
    segundos: float = 0.0
    data_hora: str = ""           # quando o item foi concluído (AAAA-MM-DD HH:MM:SS)

    @property
    def pendente(self) -> bool:
        return self.situacao in ("", CANCELADO)

    @property
    def concluido(self) -> bool:
        return not self.pendente

    @property
    def rotulo(self) -> str:
        return rotulo(self.situacao)

    def absorver(self, outro: "ResultadoProcesso") -> None:
        """Copia o que o portal apurou, mantendo a ordem e o número da lista."""
        for nome in ("situacao", "arquivo", "paginas", "documentos", "sigiloso",
                     "incompleto", "detalhe", "midias"):
            setattr(self, nome, getattr(outro, nome))
        if outro.tribunal:
            self.tribunal = outro.tribunal
        if outro.sistema:
            self.sistema = outro.sistema

    def carimbar(self) -> None:
        self.data_hora = f"{datetime.now():%Y-%m-%d %H:%M:%S}"


# ------------------------------------------------------------------- opções
def _modo_login(valor: str) -> str:
    v = (valor or "").strip().lower()
    return v if v in MODOS_LOGIN else "senha"


@dataclass
class OpcoesDownload:
    pular_baixados: bool = True
    separar_sigilosos: bool = True
    baixar_midias: bool = False
    mostrar_navegador: bool = False
    navegador: str = "auto"               # auto | chrome | msedge | chromium | caminho do .exe
    pausa: float = 3.0                    # segundos entre um processo e outro
    tentativas: int = 2
    espera_s: int = 60                    # resposta de cada página do portal
    espera_login_min: int = 10            # código por e-mail, certificado, manual
    salvar_diagnostico: bool = True
    pasta_sigilosos: Path = field(default_factory=lambda: caminhos.RAIZ / "Sigilosos")
    pasta_diagnostico: Path = field(default_factory=lambda: caminhos.LOGS / "diagnostico")
    login: dict[str, str] = field(default_factory=lambda: {"esaj": "senha", "eproc": "senha"})
    espera_tela_codigo_s: int = 45        # quanto esperar o portal abrir a tela do código
    atualizar_ia: bool = True             # ao fim, preparar os arquivos para a IA
    # onde o portal grava o processo antes de o motor saber se é sigiloso
    pasta_provisoria: Path = field(default_factory=lambda: caminhos.TEMP / "baixando")

    def modo_login(self, sistema: str) -> str:
        return _modo_login(self.login.get(sistema, "senha"))

    def navegador_visivel(self, sistema: str) -> bool:
        """Certificado e login manual precisam da janela: é nela que o
        usuário digita o PIN do token ou a senha."""
        return self.mostrar_navegador or self.modo_login(sistema) in ("certificado", "manual")

    @classmethod
    def de_config(cls, cfg) -> "OpcoesDownload":
        navegador = (cfg.texto("download", "navegador") or "auto").strip().strip('"')
        if navegador.lower() in ("auto", "chrome", "msedge", "chromium"):
            navegador = navegador.lower()
        elif not Path(navegador).is_file():     # aceita o caminho de um navegador
            navegador = "auto"
        return cls(
            pular_baixados=cfg.flag("download", "pular_baixados"),
            separar_sigilosos=cfg.flag("download", "separar_sigilosos"),
            baixar_midias=cfg.flag("download", "baixar_midias"),
            mostrar_navegador=cfg.flag("download", "mostrar_navegador"),
            navegador=navegador,
            pausa=max(0.0, cfg.real("download", "pausa_entre_processos")),
            tentativas=max(1, cfg.inteiro("download", "tentativas")),
            espera_s=max(10, cfg.inteiro("download", "espera_segundos")),
            espera_login_min=max(1, cfg.inteiro("download", "espera_login_minutos")),
            salvar_diagnostico=cfg.flag("download", "salvar_diagnostico"),
            pasta_sigilosos=cfg.pasta_sigilosos,
            pasta_diagnostico=caminhos.LOGS / "diagnostico",
            login={"esaj": _modo_login(cfg.texto("esaj", "login")),
                   "eproc": _modo_login(cfg.texto("eproc", "login"))},
        )


# ------------------------------------------------------------------- resumo
@dataclass
class ResumoLote:
    itens: list[ResultadoProcesso]
    destino: Path
    relatorio: Path
    minutos: float = 0.0
    # Cópias de processos sigilosos que NÃO puderam sair do acervo (arquivo
    # aberto em outro programa): com isto não vazio, não espelhe o acervo.
    sigilosos_no_acervo: list[str] = field(default_factory=list)

    def _com(self, *situacoes: str) -> list[ResultadoProcesso]:
        return [r for r in self.itens if r.situacao in situacoes]

    @property
    def baixados(self) -> list[ResultadoProcesso]:
        return self._com(OK)

    @property
    def pulados(self) -> list[ResultadoProcesso]:
        return self._com(JA_BAIXADO)

    @property
    def falhas(self) -> list[ResultadoProcesso]:
        return [r for r in self.itens if r.situacao in FALHAS]

    @property
    def sigilosos(self) -> list[ResultadoProcesso]:
        return [r for r in self.itens if r.sigiloso]

    @property
    def pendentes(self) -> list[ResultadoProcesso]:
        """O que não chegou a ser feito (interrompido ou nunca alcançado)."""
        return [r for r in self.itens if r.pendente]

    @property
    def cancelado(self) -> bool:
        return bool(self.pendentes)

    def a_refazer(self) -> list[str]:
        """Números para "Tentar de novo": falhas que podem mudar e pendentes.

        Tribunal não suportado fica de fora: repetir não muda nada.
        """
        return [r.numero for r in self.itens
                if r.pendente or (r.situacao in FALHAS and r.situacao != NAO_SUPORTADO)]

    def numeros_a_refazer(self) -> list:
        """O mesmo que a_refazer(), já como Numero (pronto para executar())."""
        from ..nucleo import cnj
        return [cnj.ler(n) for n in self.a_refazer()]

    def texto(self) -> str:
        """Uma frase para o fim do lote: '35 baixados, 2 já estavam na pasta…'."""
        partes = []
        n = len(self.baixados)
        partes.append(f"{n} baixado{'s' if n != 1 else ''}")
        if self.pulados:
            n = len(self.pulados)
            partes.append(f"{n} já estava{'m' if n != 1 else ''} na pasta")
        if self.falhas:
            n = len(self.falhas)
            partes.append(f"{n} com problema")
        if self.pendentes:
            n = len(self.pendentes)
            partes.append(f"{n} não baixado{'s' if n != 1 else ''} (interrompido)")
        sig = [r for r in self.sigilosos if r.situacao in (OK, JA_BAIXADO)]
        if sig:
            partes.append(f"{len(sig)} em segredo de justiça")
        return ", ".join(partes) + "."
