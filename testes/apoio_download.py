"""Dublês para os testes do download: sem rede, sem navegador, sem tela.

* números CNJ válidos (dígito verificador calculado) de qualquer tribunal;
* PDFs de verdade, pequenos, feitos com o PyMuPDF;
* ContextoGravador: guarda tudo o que o motor diz e responde o código;
* NavegadorFalso e PortalFalso: seguem o contrato do motor, com roteiro
  por processo ("ok", "erro", "sessao", ...).
"""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helestron.download import modelos
from helestron.download.contexto import Contexto
from helestron.nucleo import cnj

# Os avisos que o motor dá ao usuário (por exemplo, "login falhou") são
# esperados nos testes; sem isto, o logging os despejaria no terminal.
logging.getLogger("download").addHandler(logging.NullHandler())


def numero_valido(seq: str = "0700123", ano: str = "2024", j: str = "8",
                  tr: str = "02", origem: str = "0001", dependente: str = "") -> str:
    """Número CNJ com o dígito verificador certo (Res. CNJ 65/2008)."""
    corpo = seq + ano + j + tr + origem
    dv = 98 - int(corpo + "00") % 97
    texto = f"{seq}-{dv:02d}.{ano}.{j}.{tr}.{origem}"
    return f"{texto}/{dependente}" if dependente else texto


def numero(seq: str = "0700123", tr: str = "02", origem: str = "0001", j: str = "8",
           dependente: str = "") -> cnj.Numero:
    return cnj.ler(numero_valido(seq=seq, j=j, tr=tr, origem=origem, dependente=dependente))


def pdf_bytes(paginas: int = 1, texto: str = "página") -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for i in range(paginas):
        doc.new_page().insert_text((72, 72), f"{texto} {i + 1}")
    dados = doc.tobytes()
    doc.close()
    return dados


def png_bytes(largura: int = 60, altura: int = 30) -> bytes:
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, largura, altura), 0)
    pix.clear_with(180)
    return pix.tobytes("png")


class PastaTemporaria(unittest.TestCase):
    """Base de testes com uma pasta temporária limpa a cada teste.

    O banco da pauta e os registros do sigilo apurado, ao lado dele
    (pauta.sigilo.json, download.sigilo.json), também ficam nela: o sigilo
    que o download de um teste registra não vale para o teste seguinte, que
    usa os mesmos números."""

    def setUp(self) -> None:
        # No Windows, o navegador recém-fechado ainda segura arquivos do
        # perfil por um instante; a limpeza não pode reprovar o teste.
        self._tmp = tempfile.TemporaryDirectory(prefix="helestron-teste-",
                                                ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        from helestron.nucleo import caminhos, sigilo

        p = mock.patch.object(caminhos, "ARQUIVO_PAUTA", self.tmp / "local" / "pauta.sqlite3")
        p.start()
        self.addCleanup(p.stop)
        sigilo.esquecer_pauta()
        self.addCleanup(sigilo.esquecer_pauta)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class ContextoGravador(Contexto):
    """Guarda status, itens, avisos; responde pedir_codigo com uma fila."""

    def __init__(self, codigos=None, cancelar_em=None):
        self.status_ = []
        self.progressos = []
        self.itens = []           # cópias (situação, número) de cada item publicado
        self.avisos = []
        self.pedidos_codigo = []
        self.reenviaveis = []     # o 'reenviavel' de cada pedido, na mesma ordem
        self.codigos = list(codigos or [])
        self._cancelado = False
        self.cancelar_em = cancelar_em    # número formatado: cancela quando ele começar

    def status(self, texto):
        self.status_.append(texto)

    def progresso(self, feitos, total, atual):
        self.progressos.append((feitos, total, atual))
        if self.cancelar_em and atual == self.cancelar_em:
            self._cancelado = True

    def item(self, r):
        self.itens.append((r.numero, r.situacao))

    def cancelado(self):
        return self._cancelado

    def cancelar(self):
        self._cancelado = True

    def pedir_codigo(self, titulo, mensagem, prazo_s=600, reenviavel=True):
        self.pedidos_codigo.append((titulo, mensagem, prazo_s))
        self.reenviaveis.append(reenviavel)
        return self.codigos.pop(0) if self.codigos else None

    def avisar(self, titulo, mensagem):
        self.avisos.append((titulo, mensagem))


class NavegadorFalso:
    """Faz as vezes do Navegador: só conta aberturas e fechamentos."""

    instancias: list["NavegadorFalso"] = []

    def __init__(self, tribunal=None, opcoes=None):
        self.tribunal = tribunal
        self.opcoes = opcoes
        self.aberto = False
        self.fechado = False
        self.diagnosticos = []
        self.perfil = Path(tempfile.gettempdir()) / "perfil-falso"
        NavegadorFalso.instancias.append(self)

    def __enter__(self):
        self.aberto = True
        return self

    def __exit__(self, *_):
        self.fechado = True
        return False

    def diagnosticar(self, rotulo, pagina=None):
        self.diagnosticos.append(rotulo)

    def esquecer_sessao(self):
        pass


class CofreFalso:
    def __init__(self, dados=None):
        self.dados = dict(dados or {})
        self.pedidos = []

    def obter(self, portal):
        self.pedidos.append(portal)
        return self.dados.get(portal, ("", ""))

    def guardar(self, portal, usuario, senha):
        self.dados[portal] = (usuario, senha)


class PortalFalso:
    """Segue o roteiro de cada processo (lista de ações, uma por chamada).

    Ações: ok | ok_sigiloso | ok_sigiloso_e_parar | erro | pdf_aberto | sessao |
    indisponivel | cancelar |
    nao_encontrado | nao_encontrado_sem_acesso (SemAcesso levantado) |
    sem_acesso | sigiloso_sem_senha | login | teclado.
    Processo sem roteiro: "ok".
    """

    todos: list["PortalFalso"] = []

    def __init__(self, nav, tribunal, opcoes, ctx, credenciais, roteiro=None,
                 falha_entrar=None, sistema="esaj"):
        self.nav = nav
        self.tribunal = tribunal
        self.opcoes = opcoes
        self.ctx = ctx
        self.credenciais = credenciais
        self.roteiro = roteiro if roteiro is not None else {}
        self.falha_entrar = list(falha_entrar or [])
        self.sistema = tribunal.sistema
        self.entradas = 0
        self.chamadas = []      # (número formatado, senha)
        PortalFalso.todos.append(self)

    def entrar(self):
        self.entradas += 1
        if self.falha_entrar:
            erro = self.falha_entrar.pop(0)
            if erro is not None:
                raise erro

    def baixar(self, numero, destino_pdf, senha=None):
        self.chamadas.append((numero.formatado, senha))
        acoes = self.roteiro.get(numero.formatado)
        acao = acoes.pop(0) if acoes else "ok"
        r = modelos.ResultadoProcesso(ordem=0, numero=numero.formatado,
                                      tribunal=self.tribunal.sigla, sistema=self.sistema)
        destino_pdf = Path(destino_pdf)
        if acao == "ok_sigiloso_e_parar":
            # o usuário clica "Parar" enquanto este processo terminava
            self.ctx.cancelar()
            acao = "ok_sigiloso"
        if acao in ("ok", "ok_sigiloso"):
            destino_pdf.parent.mkdir(parents=True, exist_ok=True)
            tmp = destino_pdf.with_name(destino_pdf.name + ".parcial")
            tmp.write_bytes(pdf_bytes(2))
            os.replace(tmp, destino_pdf)
            controle = destino_pdf.parent / "_controle"
            controle.mkdir(exist_ok=True)
            (controle / f"{numero.nome_arquivo}_capa.txt").write_text("capa", encoding="utf-8")
            r.situacao, r.paginas, r.documentos = modelos.OK, 2, 1
            r.arquivo = str(destino_pdf)
            if acao == "ok_sigiloso":
                r.sigiloso = True
                midias = controle / "midias" / numero.nome_arquivo
                midias.mkdir(parents=True, exist_ok=True)
                (midias / "audiencia.mp3").write_bytes(b"x" * 300)
                r.midias = [str(midias / "audiencia.mp3")]
            return r
        if acao == "erro":
            raise RuntimeError("o portal demorou demais")
        if acao == "pdf_aberto":
            raise PermissionError(13, "Acesso negado", str(destino_pdf))
        if acao == "sessao":
            raise modelos.SessaoPerdida("sessão expirada")
        if acao == "indisponivel":
            raise modelos.PortalIndisponivel("o portal não respondeu")
        if acao == "cancelar":
            self.ctx.cancelar()
            raise modelos.Cancelado()
        if acao == "teclado":
            raise KeyboardInterrupt()
        if acao == "login":
            raise modelos.LoginFalhou("a senha expirou")
        if acao == "nao_encontrado":
            raise modelos.ProcessoNaoEncontrado("não encontrado no 1º grau")
        if acao == "nao_encontrado_sem_acesso":
            raise modelos.SemAcesso("o portal não liberou os autos")
        if acao == "sem_acesso":
            r.situacao, r.detalhe = modelos.SEM_ACESSO, "sem acesso"
            return r
        if acao == "sigiloso_sem_senha":
            r.situacao, r.detalhe, r.sigiloso = modelos.SIGILOSO_SEM_SENHA, "falta senha", True
            return r
        raise AssertionError(f"ação desconhecida: {acao}")


def fabricas(roteiro=None, falha_entrar=None):
    """(fabrica_portal, fabrica_navegador) prontas para o motor.executar.

    ``falha_entrar``: {sigla: [exceção ou None, ...]} - o que cada entrar()
    faz, na ordem.
    """
    PortalFalso.todos.clear()
    NavegadorFalso.instancias.clear()
    roteiro = {k: list(v) for k, v in (roteiro or {}).items()}
    falhas = {k: list(v) for k, v in (falha_entrar or {}).items()}

    def fabrica_portal(nav, tribunal, opcoes, ctx, credenciais):
        return PortalFalso(nav, tribunal, opcoes, ctx, credenciais, roteiro,
                           falhas.get(tribunal.sigla))

    def fabrica_navegador(tribunal, opcoes):
        return NavegadorFalso(tribunal, opcoes)

    return fabrica_portal, fabrica_navegador


def opcoes_de_teste(pasta: Path, **mudar) -> modelos.OpcoesDownload:
    """Opções rápidas: sem pausa, sem preparo de IA, pastas no temporário."""
    base = dict(pausa=0, tentativas=2, atualizar_ia=False,
                pasta_sigilosos=pasta / "Sigilosos", pasta_diagnostico=pasta / "diag",
                pasta_provisoria=pasta / "provisorio")
    base.update(mudar)
    return modelos.OpcoesDownload(**base)
