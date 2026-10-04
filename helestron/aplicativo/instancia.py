"""Instância única: um Helestron aberto por usuário.

Duas cópias abertas brigariam pelo microfone, pelos perfis do navegador (o
Chrome não abre o mesmo perfil duas vezes) e pelo banco da pauta. Dois
marcadores, em LOCAL:

  * instancia.trava - um arquivo com trava exclusiva do sistema, presa
    enquanto o programa estiver aberto. O sistema a solta quando o processo
    termina, mesmo numa queda: não há trava "esquecida";
  * instancia.json - {pid, porta, token} do servidor aberto, para a segunda
    abertura pedir à primeira que apareça (POST /api/janela/mostrar) e para
    o instalador pedir que feche (--encerrar).

Quem acha a trava presa confere a primeira instância por GET /api/ping: se
ela responde, pede que apareça e sai; se não responde ainda (está abrindo),
espera um pouco; se está fechando, espera ela sair e abre.

Os pedidos a 127.0.0.1 ignoram o proxy do sistema de propósito: na rede do
tribunal, a variável HTTP_PROXY mandaria o pedido local para o proxy.

O --encerrar (que o instalador e o desinstalador rodam antes de mexer nos
arquivos) NÃO fecha o programa no meio de uma audiência sendo transcrita:
sai com o código AUDIENCIA_EM_ANDAMENTO (10), sem tocar em nada. O
instalador então pede ao usuário que encerre a audiência (o documento é
salvo) e clique em Repetir; no modo silencioso (/S, a atualização empurrada
pela TI), ele desiste com o código 7 e a audiência segue - melhor uma
atualização adiada que a transcrição cortada no meio da sessão. Fora disso,
pede que feche e espera: enquanto a instância responder que está fechando
(a fila da audiência recém-encerrada sendo transcrita leva minutos num
computador lento), espera até ESPERA_FECHANDO_S, em vez de desistir com ela
salvando.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("aplicativo.instancia")

CABECALHO_TOKEN = "X-Helestron-Token"
# Códigos de saída do --encerrar (o 3, o 4 e o 5 são do lançador
# Helestron.exe: python312.dll ausente ou estranho, sem memória).
ENCERROU, CONTINUA_ABERTA, AUDIENCIA_EM_ANDAMENTO = 0, 1, 10
# A audiência ao vivo em curso (GerenteAudiencia.estado): não se fecha.
ESTADOS_AUDIENCIA = ("iniciando", "gravando", "pausada")
# Quanto se espera por uma instância que responde "fechando" (a audiência
# termina de transcrever a fila: servidor.aplicacao.ESPERA_AUDIENCIA_S, mais
# a parada das tarefas).
ESPERA_FECHANDO_S = 18 * 60.0


def _pasta_local() -> Path:
    from ..nucleo import caminhos

    return Path(caminhos.LOCAL)


def arquivo_registro() -> Path:
    from ..nucleo import caminhos

    arquivo = getattr(caminhos, "ARQUIVO_INSTANCIA", None)
    return Path(arquivo) if arquivo is not None else _pasta_local() / "instancia.json"


def arquivo_trava() -> Path:
    return arquivo_registro().with_name("instancia.trava")


# ===================================================================== trava
class Trava:
    """Trava exclusiva entre processos, sem esperar."""

    def __init__(self, arquivo: Path | None = None):
        self.arquivo = Path(arquivo) if arquivo is not None else arquivo_trava()
        self._f = None

    def tomar(self) -> bool:
        if self._f is not None:
            return True
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.arquivo, "a+b")
        try:
            f.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def soltar(self) -> None:
        f, self._f = self._f, None
        if f is None:
            return
        try:
            f.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (OSError, ValueError):
            pass
        finally:
            f.close()

    @property
    def presa(self) -> bool:
        return self._f is not None

    def __enter__(self) -> "Trava":
        return self

    def __exit__(self, *_exc) -> None:
        self.soltar()


def outra_aberta(espera_s: float = 0.0) -> bool:
    """A trava está com outro processo? (Toma e solta na hora para conferir.)"""
    limite = time.monotonic() + espera_s
    while True:
        t = Trava()
        if t.tomar():
            t.soltar()
            return False
        if time.monotonic() >= limite:
            return True
        time.sleep(0.2)


# ================================================================== registro
def gravar_registro(porta: int, token: str) -> Path:
    arquivo = arquivo_registro()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "porta": int(porta), "token": token}),
                   encoding="utf-8")
    os.replace(tmp, arquivo)
    return arquivo


def ler_registro() -> dict | None:
    try:
        dados = json.loads(arquivo_registro().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(dados, dict) or not dados.get("porta") or not dados.get("token"):
        return None
    try:
        dados["porta"] = int(dados["porta"])
    except (TypeError, ValueError):
        return None
    return dados


def apagar_registro(pid: int | None = None) -> None:
    """Apaga o instancia.json - só se ainda for deste processo."""
    dados = ler_registro()
    if dados is not None and pid is not None and int(dados.get("pid") or 0) != pid:
        return
    try:
        arquivo_registro().unlink(missing_ok=True)
    except OSError:
        pass


# ==================================================================== contato
_SEM_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def pedir(registro: dict, caminho: str, metodo: str = "GET", corpo: dict | None = None,
          espera_s: float = 3.0) -> dict | None:
    """Pedido à instância aberta. Devolve os 'dados' do envelope, ou None."""
    url = f"http://127.0.0.1:{registro['porta']}{caminho}"
    dados = json.dumps(corpo or {}).encode("utf-8") if metodo != "GET" else None
    pedido = urllib.request.Request(url, data=dados, method=metodo, headers={
        CABECALHO_TOKEN: str(registro["token"]), "Content-Type": "application/json"})
    try:
        with _SEM_PROXY.open(pedido, timeout=espera_s) as resposta:
            envelope = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        try:
            envelope = json.loads(erro.read().decode("utf-8"))
        except Exception:
            return None
        return {"_erro": (envelope.get("erro") or {}).get("codigo", str(erro.code))}
    except (OSError, ValueError):
        return None
    if not isinstance(envelope, dict) or not envelope.get("ok"):
        return None
    return envelope.get("dados") if envelope.get("dados") is not None else {}


def responde(registro: dict | None) -> dict | None:
    """O /api/ping da instância registrada, se ela responder."""
    if registro is None:
        return None
    dados = pedir(registro, "/api/ping", espera_s=2.0)
    if dados is None or "_erro" in dados:
        return None
    return dados


def chamar_a_aberta(espera_s: float = 20.0) -> str:
    """A outra instância está com a trava: pede que ela apareça.

    Devolve "mostrou" (pode sair), "fechou" (a outra saiu: pode abrir) ou
    "muda" (a outra não responde nem sai - travada).
    """
    limite = time.monotonic() + espera_s
    while time.monotonic() < limite:
        registro = ler_registro()
        ping = responde(registro)
        if ping is not None and not ping.get("fechando"):
            resposta = pedir(registro, "/api/janela/mostrar", "POST")
            if resposta is not None and "_erro" not in resposta:
                log.info("O Helestron já está aberto: pedi que a janela aparecesse.")
                return "mostrou"
        if not outra_aberta():
            return "fechou"
        time.sleep(0.5)
    return "fechou" if not outra_aberta() else "muda"


def audiencia_em_andamento(registro: dict | None) -> bool:
    """A instância registrada está transcrevendo uma audiência ao vivo?

    (A tela de erro não tem a rota: 404, e a resposta é "não".)
    """
    if registro is None:
        return False
    dados = pedir(registro, "/api/transcricao/estado", espera_s=5.0)
    if not dados or "_erro" in dados:
        return False
    return str(dados.get("estado") or "") in ESTADOS_AUDIENCIA


def encerrar_aberta(espera_s: float = 60.0, recusar_audiencia: bool = True,
                    espera_fechando_s: float = ESPERA_FECHANDO_S) -> int:
    """--encerrar: pede à instância aberta que feche e espera ela sair.

    0 = fechou (ou não havia nenhuma); 1 = continua aberta (não respondeu
    ou demorou demais - o instalador avisa o usuário); 10 = há uma audiência
    sendo transcrita, e nada foi fechado (recusar_audiencia).
    """
    if not outra_aberta():
        apagar_registro()
        return ENCERROU
    registro = ler_registro()
    if registro is not None:
        if recusar_audiencia and audiencia_em_andamento(registro):
            log.warning("--encerrar recusado: há uma audiência sendo transcrita no Helestron aberto")
            return AUDIENCIA_EM_ANDAMENTO
        pedir(registro, "/api/encerrar", "POST")
    if not outra_aberta(espera_s):
        return ENCERROU
    # Ainda aberta: se ela responde que está fechando (salvando a audiência,
    # parando as tarefas), espera mais - ela sai sozinha quando terminar.
    limite = time.monotonic() + max(0.0, espera_fechando_s - espera_s)
    while registro is not None and time.monotonic() < limite:
        ping = responde(registro)
        if ping is None or not ping.get("fechando"):
            break
        if not outra_aberta(min(5.0, max(0.0, limite - time.monotonic()))):
            return ENCERROU
    # (o servidor dela para um instante antes de o processo sair)
    if not outra_aberta(min(10.0, espera_s)):
        return ENCERROU
    log.warning("o Helestron aberto não fechou em %d s", int(espera_s))
    return CONTINUA_ABERTA
