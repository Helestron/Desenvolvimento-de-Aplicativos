"""Guarda usuário e senha dos portais sem deixá-los legíveis no disco.

O Assessor SAJ gravava a senha do e-SAJ em texto puro no credenciais.ini.
Aqui ela vai cifrada pela DPAPI do Windows (CryptProtectData), a mesma
proteção que o Chrome e o Edge usam para as senhas salvas: só a mesma conta
do Windows, no mesmo computador, consegue decifrar. Copiar a pasta para um
pendrive leva o arquivo, mas não a senha.

Fora do Windows (testes, desenvolvimento) não há DPAPI; o conteúdo é apenas
codificado, e o arquivo diz isso no próprio prefixo ('b64:').

Um arquivo só guarda as senhas de todos os portais, e cada gravação o
reescreve inteiro. Por isso a gravação (guardar, apagar) nunca parte de uma
leitura que falhou: se o arquivo não pôde ser lido por um instante (o
antivírus o segurava), ela insiste e, se não der, desiste sem gravar; se ele
está estragado, é posto de lado (credenciais.json.ilegivel-<data>) antes de
o cofre recomeçar. E duas gravações ao mesmo tempo (duas requisições da
janela, ou a janela e o "baixar" da linha de comando) passam uma de cada vez,
para uma não apagar o que a outra acabou de guardar.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_ENTROPIA = b"Helestron/credenciais/v1"

# Arquivo preso por um instante (antivírus, indexador, OneDrive): insiste-se
# como o config.ini insiste (config.TENTATIVAS_TROCA e ESPERA_TROCA_S).
TENTATIVAS = 6
ESPERA_S = 0.4
# A trava entre processos (a janela e o "baixar" da linha de comando): quanto
# se espera por ela, e a idade em que uma trava esquecida (o processo que a
# tinha caiu) deixa de valer. Uma gravação leva milissegundos; mesmo
# insistindo na leitura e na troca do arquivo, menos de 6 s.
ESPERA_TRAVA_S = 10.0
TRAVA_ABANDONADA_S = 30.0
_trava = threading.Lock()


class CofreIndisponivel(PermissionError):
    """O cofre não pôde ser lido ou gravado agora; nada foi alterado.

    É PermissionError de propósito: a API a traduz como "arquivo preso"
    (409) com esta frase, e quem já trata OSError continua tratando.
    """


# --------------------------------------------------------------- DPAPI
if sys.platform == "win32":  # pragma: no cover - exercitado no CI do Windows
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def _blob(dados: bytes) -> _BLOB:
        buf = ctypes.create_string_buffer(dados, len(dados))
        return _BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _ler_blob(b: _BLOB) -> bytes:
        try:
            return ctypes.string_at(b.pbData, b.cbData)
        finally:
            _kernel32.LocalFree(b.pbData)

    def _cifrar(dados: bytes, extra: bytes = _ENTROPIA) -> str:
        entrada, entropia, saida = _blob(dados), _blob(extra), _BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(entrada), "Helestron", ctypes.byref(entropia),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
        if not ok:
            raise OSError(ctypes.GetLastError(), "CryptProtectData falhou")
        return "dpapi:" + base64.b64encode(_ler_blob(saida)).decode("ascii")

    def _decifrar(texto: str, extra: bytes = _ENTROPIA) -> bytes:
        if texto.startswith("b64:"):
            return base64.b64decode(texto[4:])
        bruto = base64.b64decode(texto.removeprefix("dpapi:"))
        entrada, entropia, saida = _blob(bruto), _blob(extra), _BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(entrada), None, ctypes.byref(entropia),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
        if not ok:
            raise OSError(ctypes.GetLastError(), "CryptUnprotectData falhou")
        return _ler_blob(saida)
else:
    def _cifrar(dados: bytes, extra: bytes = _ENTROPIA) -> str:
        return "b64:" + base64.b64encode(dados).decode("ascii")

    def _decifrar(texto: str, extra: bytes = _ENTROPIA) -> bytes:
        if texto.startswith("dpapi:"):
            raise OSError("credencial cifrada no Windows; não dá para ler aqui")
        return base64.b64decode(texto.removeprefix("b64:"))


def cifrar(dados: bytes, finalidade: str) -> str:
    """Cifra para ESTA conta do Windows (DPAPI), com uma entropia por
    finalidade: o que se cifrou para a sessão do navegador não se decifra
    como senha, e vice-versa."""
    return _cifrar(dados, b"Helestron/" + finalidade.encode("utf-8"))


def decifrar(texto: str, finalidade: str) -> bytes:
    return _decifrar(texto, b"Helestron/" + finalidade.encode("utf-8"))


def gravar_privado(arquivo: Path, texto: str) -> None:
    """Grava por inteiro (temporário + troca) e só para o dono: 0600 fora do
    Windows; no Windows, a pasta em %LOCALAPPDATA% já é só do usuário.

    O temporário tem nome único (duas gravações ao mesmo tempo não dividem o
    mesmo arquivo), vai ao disco antes da troca (uma queda de energia não
    deixa o arquivo pela metade) e a troca insiste quando o destino está
    preso por um instante. Se não der, o temporário é apagado e o erro sobe.
    """
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp cria o arquivo só para o dono (0600) e com O_EXCL.
    fd, nome = tempfile.mkstemp(dir=arquivo.parent, prefix=arquivo.name + ".", suffix=".tmp")
    tmp = Path(nome)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        _trocar(tmp, arquivo)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _trocar(tmp: Path, arquivo: Path) -> None:
    """os.replace com paciência para o Windows (como o config._trocar)."""
    for tentativa in range(TENTATIVAS):
        try:
            os.replace(tmp, arquivo)
            return
        except PermissionError as erro:
            if tentativa < TENTATIVAS - 1:
                time.sleep(ESPERA_S)
                continue
            raise PermissionError(
                f"Não consegui gravar {arquivo.name}: o arquivo está preso por outro programa "
                "(antivírus, OneDrive ou outro que o tenha aberto). Nada foi alterado: espere "
                "alguns segundos e repita.") from erro


def _trava_abandonada(trava: Path) -> bool:
    try:
        return time.time() - trava.stat().st_mtime > TRAVA_ABANDONADA_S
    except OSError:
        return False


@contextmanager
def _travado(arquivo: Path):
    """Uma gravação do cofre de cada vez: entre as threads deste processo
    (_trava) e entre processos (o arquivo '<cofre>.trava', criado com O_EXCL
    e apagado ao fim - nada fica na pasta)."""
    with _trava:
        trava = arquivo.with_name(arquivo.name + ".trava")
        trava.parent.mkdir(parents=True, exist_ok=True)
        limite = time.monotonic() + ESPERA_TRAVA_S
        while True:
            try:
                fd = os.open(trava, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except (FileExistsError, PermissionError):
                # PermissionError: no Windows, a trava que outro processo
                # acabou de apagar ainda está "saindo" por um instante.
                if _trava_abandonada(trava):
                    try:
                        trava.unlink()
                        log.warning("trava do cofre de senhas esquecida (%s); retirada",
                                    trava.name)
                        continue
                    except OSError:
                        pass            # não saiu: espera-se como por uma trava viva
                if time.monotonic() >= limite:
                    raise CofreIndisponivel(
                        "Não consegui gravar o cofre de senhas agora: outra janela do Helestron "
                        "(ou o download pela linha de comando) está gravando nele, ou a pasta "
                        f"{arquivo.parent} não aceita gravação. Nada foi alterado; repita em "
                        "alguns segundos.") from None
                time.sleep(0.05)
        try:
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            yield
        finally:
            try:
                trava.unlink()
            except OSError as erro:
                log.warning("não consegui retirar a trava do cofre de senhas (%s)", erro)


class CofreSenhas:
    """Um arquivo JSON com uma entrada por portal: {'esaj:8.02': '...'}.

    Cada valor é o par {'usuario', 'senha'} serializado e cifrado. Uma
    entrada que não decifra (outro usuário do Windows, outro computador) é
    tratada como ausente: o programa pede de novo, em vez de quebrar.
    """

    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)

    def _carregar(self) -> dict[str, str]:
        """Para LER (obter, portais): o que não pôde ser lido é tratado como
        vazio - quem mostra ou usa a senha pede de novo, e nada é gravado."""
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as erro:
            log.warning("cofre de senhas ilegível agora (%s); lido como vazio", erro)
            return {}
        if not isinstance(dados, dict):
            log.warning("cofre de senhas ilegível (o conteúdo não é um objeto JSON); lido como "
                        "vazio")
            return {}
        return dados

    def _carregar_para_gravar(self) -> dict[str, str]:
        """Para GRAVAR (guardar, apagar): a gravação reescreve o arquivo
        inteiro, então nunca parte de uma leitura que falhou.

        * sem arquivo: o cofre começa vazio;
        * arquivo preso (antivírus, OneDrive): insiste-se por ~2 s; se
          continuar preso, CofreIndisponivel - e nada é gravado (antes, as
          senhas dos outros portais sumiam sem aviso);
        * arquivo estragado (não é JSON, ou não é um objeto): ele é posto de
          lado como '<nome>.ilegivel-AAAAmmdd-HHMMSS', para o suporte, e o
          cofre recomeça; se nem isso der, CofreIndisponivel.
        """
        for tentativa in range(TENTATIVAS):
            try:
                bruto = self.arquivo.read_bytes()
                break
            except FileNotFoundError:
                return {}
            except OSError as erro:
                if tentativa < TENTATIVAS - 1:
                    time.sleep(ESPERA_S)
                    continue
                raise CofreIndisponivel(
                    f"Não consegui ler o cofre de senhas ({self.arquivo.name}): o arquivo está "
                    "preso por outro programa (antivírus, OneDrive ou outro que o tenha aberto). "
                    "Nada foi alterado, e as senhas guardadas continuam lá: espere alguns "
                    "segundos e repita.") from erro
        try:
            dados = json.loads(bruto.decode("utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("o conteúdo não é um objeto JSON")
        except ValueError as erro:          # inclui UnicodeDecodeError e JSONDecodeError
            self._por_de_lado(erro)
            return {}
        return dados

    def _por_de_lado(self, motivo: Exception) -> None:
        """Guarda o arquivo estragado com outro nome (não apaga nada)."""
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = self.arquivo.with_name(f"{self.arquivo.name}.ilegivel-{carimbo}")
        n = 1
        while destino.exists():
            n += 1
            destino = self.arquivo.with_name(f"{self.arquivo.name}.ilegivel-{carimbo}-{n}")
        try:
            os.replace(self.arquivo, destino)
        except FileNotFoundError:
            return
        except OSError as erro:
            raise CofreIndisponivel(
                f"O cofre de senhas ({self.arquivo.name}) está ilegível, e não consegui guardá-lo "
                "à parte antes de recomeçar. Nada foi alterado.") from erro
        log.error("Cofre de senhas ilegível (%s): guardado como %s; o cofre recomeça vazio e "
                  "as senhas dos portais serão pedidas de novo.", motivo, destino.name)

    def _gravar(self, dados: dict[str, str]) -> None:
        gravar_privado(self.arquivo, json.dumps(dados, indent=1, ensure_ascii=False))

    def obter(self, portal: str) -> tuple[str, str]:
        """(usuario, senha) do portal, ou ('', '') se não houver."""
        valor = self._carregar().get(portal)
        if not valor or not isinstance(valor, str):
            return "", ""
        try:
            par = json.loads(_decifrar(valor).decode("utf-8"))
            return par.get("usuario", ""), par.get("senha", "")
        except (OSError, ValueError, AttributeError) as erro:
            log.warning("credencial de %s não pôde ser lida (%s)", portal, erro)
            return "", ""

    def guardar(self, portal: str, usuario: str, senha: str) -> None:
        """Guarda (ou, com usuário e senha em branco, apaga) a do portal.

        Ler, alterar e gravar acontecem sob a trava: as senhas dos outros
        portais nunca se perdem. Se o cofre não puder ser lido ou gravado
        agora, CofreIndisponivel (PermissionError) e nada muda.
        """
        with _travado(self.arquivo):
            dados = self._carregar_para_gravar()
            if not usuario and not senha:
                if portal not in dados:
                    return
                dados.pop(portal, None)
            else:
                par = json.dumps({"usuario": usuario, "senha": senha})
                dados[portal] = _cifrar(par.encode("utf-8"))
            self._gravar(dados)

    def apagar(self, portal: str) -> None:
        self.guardar(portal, "", "")

    def portais(self) -> list[str]:
        return sorted(self._carregar())
