"""A abertura do Helestron (python -m helestron, sem argumentos).

    1. instância única: se já houver um Helestron aberto, pede que ele
       apareça e sai;
    2. integridade: confere os arquivos do programa (manifesto.json); se
       faltar algum, mostra a tela de erro própria, com o arquivo que falta
       e o botão Reparar;
    3. servidor local (127.0.0.1, porta livre, token desta execução);
    4. monitor da pauta (thread);
    5. a janela (WebView2 → Edge em modo aplicativo → navegador padrão),
       que BLOQUEIA até ser fechada;
    6. encerramento seguro: salva a audiência, para as tarefas, apaga o
       registro da instância.

Sem AppUserModelID explícito: o Windows usa o implícito do Helestron.exe,
o mesmo dos atalhos que o instalador cria — o Helestron fixado na barra de
tarefas reconhece a janela aberta (com um ID só no processo, ela aparecia
como um segundo botão). O ícone vem do próprio Helestron.exe.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from .. import NOME
from ..nucleo import caminhos, registro
from . import integridade, instancia, mensagem_nativa

log = logging.getLogger("aplicativo.inicio")

IDADE_TEMP_S = 3600
# O encerramento espera a audiência ao vivo terminar de transcrever a fila
# (servidor.aplicacao.ESPERA_AUDIENCIA_S) e as tarefas pararem: o processo
# não pode sair antes (as threads de trabalho são "daemon").
FOLGA_ENCERRAR_S = 60
# Arquivos de uma versão anterior que estavam em uso na atualização (o
# servidor MCP aberto pelo Claude Desktop): o instalador os renomeia para
# esta pasta, dentro da pasta do programa, e eles são apagados depois.
PASTA_ANTIGOS = ".antigos"


def limpar_temporarios(agora: float | None = None) -> int:
    """Apaga as relações baixadas por link e os envios que sobraram.

    Podem trazer a coluna de senhas dos processos sigilosos, em texto puro.
    A API já os apaga logo depois de ler; isto recolhe o que ficou de uma
    queda no meio. Só o que tem mais de uma hora.
    """
    agora = time.time() if agora is None else agora
    apagados = 0
    temp = Path(caminhos.TEMP)
    for pasta in (temp / "listas", temp / "relacoes", temp / "envios"):
        try:
            arquivos = [p for p in pasta.iterdir() if p.is_file()]
        except OSError:
            continue
        for p in arquivos:
            try:
                if agora - p.stat().st_mtime > IDADE_TEMP_S:
                    p.unlink()
                    apagados += 1
            except OSError:
                pass
    if apagados:
        log.info("Apaguei %d arquivo(s) temporário(s) que tinham sobrado.", apagados)
    return apagados


def limpar_antigos(pasta: Path | None = None) -> int:
    """Apaga o que o instalador deixou em <programa>\\.antigos (arquivos da
    versão anterior presos por um processo na hora da atualização). O que
    ainda estiver em uso fica para a próxima vez."""
    if pasta is None:
        instalada = integridade.pasta_instalada()
        if instalada is None:
            return 0
        pasta = Path(instalada) / PASTA_ANTIGOS
    if not pasta.is_dir():
        return 0
    apagados = 0
    for arq in sorted(pasta.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if arq.is_dir():
                arq.rmdir()
            else:
                arq.unlink()
                apagados += 1
        except OSError:
            continue
    try:
        pasta.rmdir()
    except OSError:
        pass
    if apagados:
        log.info("Apaguei %d arquivo(s) da versão anterior do programa.", apagados)
    return apagados


def limpar_perfis() -> int:
    """As cópias antigas do perfil do Chrome (com senhas e cookies) e as
    sessões guardadas em texto puro, das versões até a 1.0.1."""
    try:
        from ..download import navegador
        return navegador.limpar_perfis_antigos()
    except Exception as erro:
        log.warning("limpeza dos perfis do navegador: %s", type(erro).__name__)
        return 0


def _espera_encerrar_s() -> float:
    try:
        from ..servidor import aplicacao

        return (float(getattr(aplicacao, "ESPERA_AUDIENCIA_S", 15 * 60))
                + float(getattr(aplicacao, "ESPERA_TAREFAS_S", 120)) + FOLGA_ENCERRAR_S)
    except Exception:                               # pragma: no cover
        return 20 * 60.0


def _instancia_unica(trava: instancia.Trava) -> int | None:
    """Toma a trava, ou resolve com a instância já aberta.

    None = pode abrir; um código de saída = esta abertura termina aqui.
    """
    if trava.tomar():
        return None
    registro_aberto = instancia.ler_registro()
    if registro_aberto and registro_aberto.get("pid"):
        from .janela import permitir_primeiro_plano

        permitir_primeiro_plano(int(registro_aberto["pid"]))
    situacao = instancia.chamar_a_aberta()
    if situacao == "mostrou":
        return 0
    if situacao == "fechou":
        limite = time.monotonic() + 30
        while time.monotonic() < limite:
            if trava.tomar():
                return None
            time.sleep(0.3)
    mensagem_nativa(NOME, f"O {NOME} já está aberto, mas não respondeu. Espere alguns segundos "
                          "e tente de novo; se continuar assim, reinicie o computador.")
    return 1


def main(autoteste: Path | None = None) -> int:
    """Abre o programa e espera ele fechar. Devolve o código de saída.

    Com 'autoteste', tudo roda em pastas de dados novas e vazias (antes do
    registro, da instância e do servidor): as capturas nunca mostram a
    configuração, a pauta ou o acervo de quem roda o comando.
    """
    registro.preparar_saidas()
    pastas = None
    if autoteste is not None:
        from .autoteste import PastasDoAutoteste

        pastas = PastasDoAutoteste(autoteste).isolar()
    try:
        try:
            registro.configurar(console=autoteste is not None)
        except Exception:                           # sem log, o programa abre mesmo assim
            pass
        trava = instancia.Trava()
        if autoteste is None:
            codigo = _instancia_unica(trava)
            if codigo is not None:
                return codigo
        try:
            return _abrir(autoteste)
        finally:
            if trava.presa:
                instancia.apagar_registro(os.getpid())
                trava.soltar()
    finally:
        if pastas is not None:
            pastas.desfazer()


def _abrir(autoteste: Path | None) -> int:
    problemas = integridade.conferir_rapido()
    if problemas:
        try:
            from . import erro

            # Grava o instancia.json também aqui: o --encerrar do instalador
            # (que esta tela manda rodar) e a segunda abertura falam com ela.
            return erro.mostrar(problemas, registrar=autoteste is None)
        except Exception as falha:
            log.exception("a tela de erro não abriu")
            mensagem_nativa(f"O {NOME} não pôde abrir",
                            "Faltam arquivos do programa:\n\n"
                            + integridade.descrever(problemas, 8)
                            + "\n\nIsso costuma acontecer quando o antivírus põe um arquivo em "
                              "quarentena, ou quando a instalação foi interrompida. Instale o "
                              f"{NOME} de novo com o Helestron-Setup: ele conserta a instalação "
                              f"sem apagar os seus dados.\n\n({type(falha).__name__})")
            return 1

    from ..servidor.aplicacao import Aplicacao
    from . import janela
    from .autoteste import Autoteste
    from .monitor import MonitorPauta

    try:
        app = Aplicacao().iniciar()
    except Exception as falha:
        log.exception("o servidor local não pôde começar")
        mensagem_nativa(f"O {NOME} não pôde abrir",
                        f"O {NOME} não conseguiu iniciar o seu servidor interno "
                        f"({type(falha).__name__}: {falha}).\n\nFeche e abra o programa de novo; "
                        "se persistir, reinicie o computador. Os detalhes ficaram na pasta Logs.")
        return 1
    teste = None
    if autoteste is not None:
        teste = Autoteste(app, autoteste)
        app.autoteste = teste
        teste.vigiar()
    else:
        try:
            instancia.gravar_registro(app.porta, app.token)
        except OSError as erro:
            log.warning("não consegui gravar o registro da instância: %s", erro)
    threading.Thread(target=limpar_temporarios, name="limpar-temp", daemon=True).start()
    threading.Thread(target=limpar_antigos, name="limpar-antigos", daemon=True).start()
    threading.Thread(target=limpar_perfis, name="limpar-perfis", daemon=True).start()
    if teste is None:
        # No autoteste, nada de sincronizar com os portais: a pauta é a das
        # pastas vazias, e o percurso não espera rede nem navegador.
        app.monitor = MonitorPauta(app).iniciar()
    url = app.url + ("&autoteste=1" if teste is not None else "")
    try:
        modo = janela.abrir(app, url)
        if not modo and not app.fechando:
            mensagem_nativa(f"O {NOME} não pôde abrir", janela.motivo_sem_janela())
    finally:
        app.encerrar()
        # Se o encerramento começou em outra thread (o "Fechar mesmo assim?"
        # da janela, o --encerrar), espera ele acabar — inclusive a audiência
        # terminando de transcrever: o processo não pode sair no meio.
        app.esperar(_espera_encerrar_s())
    if teste is not None:
        return teste.codigo
    return 0 if modo else 1
