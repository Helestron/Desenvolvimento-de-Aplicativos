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

from ..nucleo import caminhos, cnj


# ------------------------------------------------------------------ exceções
class LoginFalhou(RuntimeError):
    """Credencial recusada, senha expirada, prazo do código ou do certificado
    esgotado. Repetir com a mesma credencial não resolve."""


class PortalIndisponivel(RuntimeError):
    """O portal não pôde ser usado: sem rede, em manutenção, layout novo,
    navegador ausente ou que não abre."""


class NavegadorOcupado(PortalIndisponivel):
    """O perfil do navegador do portal já está em uso por outra janela do
    programa (outro download em andamento). Passa sozinho quando o outro
    termina: o motor pode esperar (opção "esperar o navegador")."""


class CopiaAntigaPresa(NavegadorOcupado):
    """O navegador do modo certificado não abre porque a cópia do perfil
    inteiro do Chrome, das versões anteriores, ainda não pôde ser apagada
    (um arquivo dela preso pelo antivírus, pelo Explorador ou por uma janela
    do navegador do programa). Não há outro download: costuma passar sozinho,
    e o motor espera como pelo navegador ocupado, dizendo o motivo real."""


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

# A causa de um desfecho que não é OK, legível por máquina (coluna "causa" do
# relatório e campo do JSON da linha de comando). A situação diz O QUE houve;
# a causa, POR QUÊ - quem automatiza o programa decide por ela, sem adivinhar
# pelo texto do detalhe.
CAUSA_LOGIN = "login"                    # login recusado ou não concluído no prazo
CAUSA_SESSAO = "sessao"                  # a sessão caiu e não voltou
CAUSA_PORTAL = "portal"                  # portal fora do ar, sem rede, navegador que não abre
CAUSA_PORTAL_PAROU = "portal_parou"      # o portal parou de responder no meio do grupo
CAUSA_NAVEGADOR_OCUPADO = "navegador_ocupado"   # outro download usa o navegador do portal
CAUSA_FALHA = "falha"                    # falha passageira que esgotou as tentativas
CAUSA_INESPERADO = "inesperado"          # erro do programa (vai para o registro)
CAUSA_PDF_ABERTO = "pdf_aberto"          # o PDF do lote está aberto noutro programa
CAUSA_GRAVACAO = "gravacao"              # não se conseguiu gravar na pasta do lote/sigilosos
CAUSA_PDF_INVALIDO = "pdf_invalido"      # o portal disse que baixou, mas o PDF não veio
CAUSA_INTERROMPIDO = "interrompido"      # "Parar", Ctrl+C ou lote encerrado antes
CAUSA_SIGILO_NO_ACERVO = "sigilo_no_acervo"     # sigiloso com autos presos no acervo
CAUSAS = {CAUSA_LOGIN, CAUSA_SESSAO, CAUSA_PORTAL, CAUSA_PORTAL_PAROU, CAUSA_NAVEGADOR_OCUPADO,
          CAUSA_FALHA, CAUSA_INESPERADO, CAUSA_PDF_ABERTO, CAUSA_GRAVACAO, CAUSA_PDF_INVALIDO,
          CAUSA_INTERROMPIDO, CAUSA_SIGILO_NO_ACERVO}


def pede_nova_tentativa(situacao: str, causa: str = "") -> bool:
    """Uma nova rodada pode mudar o desfecho? (o "refazer" do relatório)

    Sim para o que ficou pendente ou interrompido, para toda falha (ERRO) - a
    de login também: depois que o usuário entra, o grupo inteiro pode ser
    refeito - e para o "não encontrado" cujo sistema alternativo nem pôde ser
    consultado (a causa diz por quê). Não para o que é definitivo: baixado,
    já na pasta, não encontrado nos dois sistemas, sem acesso, sigiloso sem
    a senha, tribunal não suportado.
    """
    situacao = (situacao or "").strip().upper()
    if situacao in ("", "PENDENTE", CANCELADO, ERRO):
        return True
    return situacao == NAO_ENCONTRADO and bool((causa or "").strip())

MODOS_LOGIN = ("senha", "certificado", "manual")

# Rótulos da interface que as mensagens dos portais citam: têm de ser os
# mesmos da tela (helestron/web e os campos de Ajustes descritos pelo
# servidor), ou o usuário procura uma opção que não existe. O teste
# test_download_motor.TestRotulosCitados confere cada um de ROTULOS_CITADOS.
MOSTRAR_NAVEGADOR = "Mostrar o navegador enquanto baixa"
TENTAR_DE_NOVO = "Tentar de novo"
ENTRAR_MANUALMENTE = "Entrar manualmente"
AJUSTES_ACESSOS = "Ajustes › Acessos aos portais"
PRAZO_LOGIN = "Esperar o login até (minutos)"
PERFIL_EPROC = "Perfil do eProc"
CAMPO_PRAZO_LOGIN = f"{AJUSTES_ACESSOS}, campo “{PRAZO_LOGIN}”"
# Onde cadastrar ou corrigir usuário e senha de um portal.
ONDE_CADASTRAR_ACESSO = (f"em {AJUSTES_ACESSOS} (ou na revisão do lote, na tela Processos, "
                         "em “Acesso aos portais”)")
# Endereço de portal errado: Ajustes › Acessos aos portais, "Endereço do
# portal" (a correção fica no enderecos-locais.json da pasta de dados e vale
# por cima do catálogo dados\\tribunais.json).
ENDERECO_DO_PORTAL = "Endereço do portal"
ONDE_CORRIGIR_ENDERECO = (f"em {AJUSTES_ACESSOS}, “{ENDERECO_DO_PORTAL}” (a correção fica "
                          "no arquivo enderecos-locais.json da pasta de dados do Helestron, "
                          "%LOCALAPPDATA%\\Helestron) - ou peça ao suporte")
ROTULOS_CITADOS = (MOSTRAR_NAVEGADOR, TENTAR_DE_NOVO, ENTRAR_MANUALMENTE, "Ajustes",
                   "Acessos aos portais", "Acesso aos portais", PRAZO_LOGIN, PERFIL_EPROC,
                   "Pastas", ENDERECO_DO_PORTAL)
# Onde trocar o grau do lote: na tela (Opções do lote) e na linha de comando.
# Um só texto para o e-SAJ, o eProc e o motor. (O rótulo da opção só passa a
# ser citado entre aspas - e a entrar em ROTULOS_CITADOS - quando a tela o
# tiver.)
DICA_GRAU_2G = "escolha 2º grau nas Opções do lote (na linha de comando, --grau 2g)"
DICA_GRAU_1G = "escolha 1º grau nas Opções do lote (na linha de comando, --grau 1g)"


def dica_de_grau(numero, grau: str) -> str:
    """O fim da frase de "não encontrado", depois de "Confira o número; " (sem
    ponto final): onde mais procurar os autos. No 1º grau, escolher o 2º; no
    2º, escolher o 1º (o recurso pode não ter subido) - salvo quando o próprio
    número só existe no 2º grau (cnj.grau_do_numero): aí trocar o grau do lote
    não muda a busca, e a frase o diz. 'numero': um cnj.Numero ou um texto."""
    if (cnj.normalizar_grau(grau) or "1g") == "1g":
        return f"se o processo estiver no 2º grau, {DICA_GRAU_2G}"
    n = numero
    if not isinstance(n, cnj.Numero):
        try:
            n = cnj.ler(str(numero or ""))
        except cnj.NumeroInvalido:
            n = None
    if n is not None and cnj.grau_do_numero(n) == "2g":
        sem_efeito = "trocar o grau do lote não muda a busca"
        if n.origem == "0000":
            return ("o processo originário do tribunal (órgão 0000) só existe no 2º grau: "
                    + sem_efeito)
        if n.origem.startswith("9"):
            return (f"o órgão {n.origem} (plantão do 2º grau ou turma recursal) só é procurado "
                    "no 2º grau: " + sem_efeito)
        return f"o recurso interno do 2º grau (/{n.dependente}) só existe no 2º grau: " + sem_efeito
    return f"se o recurso ainda não subiu, os autos estão no 1º grau: {DICA_GRAU_1G}"


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
    # O que falta nos autos do PDF. No e-SAJ, TODAS as folhas que têm página
    # de aviso no lugar ("12-15, 40"), qualquer que seja o motivo: a Pasta
    # Digital não as ofereceu (ou listou a peça sem numeração), a peça não
    # veio do portal, o arquivo dela era inválido ou veio com páginas a menos
    # (os códigos N, S, B, I e C de nucleo/paginacao.MOTIVOS) - e não só as não
    # oferecidas. No eProc, os documentos que não vieram ("ev. 4 PET1").
    # Vazio: nada falta (ou ainda sem PDF).
    incompleto: str = ""
    detalhe: str = ""
    midias: list[str] = field(default_factory=list)
    segundos: float = 0.0
    data_hora: str = ""           # quando o item foi concluído (AAAA-MM-DD HH:MM:SS)
    causa: str = ""               # por que não deu OK (CAUSAS); vazio quando a situação basta
    # Cada consulta a um sistema do tribunal, na ordem: {"sistema", "situacao",
    # "causa"} - ou {"sistema", "consultado": False, "causa", "detalhe"} quando
    # o sistema (o alternativo, por exemplo) nem pôde ser consultado.
    consultas: list[dict] = field(default_factory=list)
    # O essencial do manifesto de paginação gravado no PDF (nucleo/paginacao.py):
    # {"paginacao", "sistema", "ultima", "ausentes", ...}; vazio = PDF sem
    # manifesto (versão anterior) ou ainda sem PDF.
    paginacao: dict = field(default_factory=dict)
    # O grau dos autos deste processo: "1g" ou "2g" (cnj.grau_do_processo).
    # Quem o decide é o motor, ao montar o lote; absorver() não o troca.
    grau: str = "1g"

    @property
    def pendente(self) -> bool:
        return self.situacao in ("", CANCELADO)

    @property
    def refazer(self) -> bool:
        """Uma nova rodada pode mudar o desfecho? (pede_nova_tentativa)"""
        return pede_nova_tentativa(self.situacao, self.causa)

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
        if getattr(outro, "causa", ""):
            self.causa = outro.causa
        if getattr(outro, "paginacao", None):
            self.paginacao = dict(outro.paginacao)

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
    pasta_sigilosos: Path = field(default_factory=lambda: caminhos.BASE_USUARIO / "Sigilosos")
    pasta_diagnostico: Path = field(default_factory=lambda: caminhos.LOGS / "diagnostico")
    login: dict[str, str] = field(default_factory=lambda: {"esaj": "senha", "eproc": "senha"})
    espera_tela_codigo_s: int = 45        # quanto esperar o portal abrir a tela do código
    atualizar_ia: bool = True             # ao fim, preparar os arquivos para a IA
    # onde o portal grava o processo antes de o motor saber se é sigiloso
    pasta_provisoria: Path = field(default_factory=lambda: caminhos.TEMP / "baixando")
    # Baixar de novo o que já está na pasta, mas só se o PDF tiver folhas
    # (ou documentos) ausentes ou não trouxer o manifesto de paginação.
    rebaixar_incompletos: bool = False
    # Com o navegador do portal ocupado por outro download, esperar até
    # tantos segundos (tentando a cada 30 s) em vez de desistir do grupo.
    esperar_navegador_s: float = 0.0
    # Ler as senhas guardadas no cofre (modo "senha"). Desligado, o portal no
    # modo "senha" abre na tela de entrada para o usuário entrar à mão.
    usar_cofre: bool = True
    # O grau do lote, "1g" ou "2g": na tela, a opção Grau do lote (sem ela, o
    # [download] grau dos Ajustes, que é o que de_config lê); na linha de
    # comando, --grau (sem ele, 1g: a CLI troca o valor de de_config). O número
    # que só existe no 2º grau vai ao 2º grau assim mesmo (cnj.grau_do_processo).
    grau: str = "1g"

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
            grau=cnj.normalizar_grau(cfg.texto("download", "grau")) or "1g",
        )


# ------------------------------------------------------------------- resumo
@dataclass
class ResumoLote:
    itens: list[ResultadoProcesso]
    destino: Path
    relatorio: Path
    minutos: float = 0.0
    # Autos de processos sigilosos que NÃO puderam sair do acervo (arquivo
    # aberto em outro programa): com isto não vazio, não espelhe o acervo.
    sigilosos_no_acervo: list[str] = field(default_factory=list)
    # O resto de processo sigiloso que ficou no acervo (a transcrição aberta
    # no Word, a gravação em curso, a minuta, a capa): não trava o
    # compartilhamento - o índice, o conector, o pacote e a nuvem já o
    # deixam de fora -, mas é avisado.
    sigilosos_avisos: list[str] = field(default_factory=list)
    sigilosos_motivos: dict[str, str] = field(default_factory=dict)   # arquivo -> por que ficou
    # A pasta de sigilosos deste lote (fora do acervo) e o relatório completo
    # dela, com os números dos sigilosos (None: o lote não tem pasta de sigilosos).
    pasta_sigilosos: Path | None = None
    relatorio_completo: Path | None = None

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
