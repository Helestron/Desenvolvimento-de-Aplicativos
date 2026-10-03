"""Guarda usuário e senha dos portais sem deixá-los legíveis no disco.

O Assessor SAJ gravava a senha do e-SAJ em texto puro no credenciais.ini.
Aqui ela vai cifrada pela DPAPI do Windows (CryptProtectData), a mesma
proteção que o Chrome e o Edge usam para as senhas salvas: só a mesma conta
do Windows, no mesmo computador, consegue decifrar. Copiar a pasta para um
pendrive leva o arquivo, mas não a senha.

Fora do Windows (testes, desenvolvimento) não há DPAPI; o conteúdo é apenas
codificado, e o arquivo diz isso no próprio prefixo ('b64:').
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_ENTROPIA = b"AssessorIntegrado/credenciais/v1"


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

    def _cifrar(dados: bytes) -> str:
        entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(entrada), "AssessorIntegrado", ctypes.byref(entropia),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
        if not ok:
            raise OSError(ctypes.GetLastError(), "CryptProtectData falhou")
        return "dpapi:" + base64.b64encode(_ler_blob(saida)).decode("ascii")

    def _decifrar(texto: str) -> bytes:
        if texto.startswith("b64:"):
            return base64.b64decode(texto[4:])
        bruto = base64.b64decode(texto.removeprefix("dpapi:"))
        entrada, entropia, saida = _blob(bruto), _blob(_ENTROPIA), _BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(entrada), None, ctypes.byref(entropia),
            None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
        if not ok:
            raise OSError(ctypes.GetLastError(), "CryptUnprotectData falhou")
        return _ler_blob(saida)
else:
    def _cifrar(dados: bytes) -> str:
        return "b64:" + base64.b64encode(dados).decode("ascii")

    def _decifrar(texto: str) -> bytes:
        if texto.startswith("dpapi:"):
            raise OSError("credencial cifrada no Windows; não dá para ler aqui")
        return base64.b64decode(texto.removeprefix("b64:"))


class CofreSenhas:
    """Um arquivo JSON com uma entrada por portal: {'esaj:8.02': '...'}.

    Cada valor é o par {'usuario', 'senha'} serializado e cifrado. Uma
    entrada que não decifra (outro usuário do Windows, outro computador) é
    tratada como ausente: o programa pede de novo, em vez de quebrar.
    """

    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)

    def _carregar(self) -> dict[str, str]:
        try:
            return json.loads(self.arquivo.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.warning("cofre de senhas ilegível; começando vazio")
            return {}

    def _gravar(self, dados: dict[str, str]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.arquivo)

    def obter(self, portal: str) -> tuple[str, str]:
        """(usuario, senha) do portal, ou ('', '') se não houver."""
        valor = self._carregar().get(portal)
        if not valor:
            return "", ""
        try:
            par = json.loads(_decifrar(valor).decode("utf-8"))
            return par.get("usuario", ""), par.get("senha", "")
        except (OSError, ValueError) as erro:
            log.warning("credencial de %s não pôde ser lida (%s)", portal, erro)
            return "", ""

    def guardar(self, portal: str, usuario: str, senha: str) -> None:
        dados = self._carregar()
        if not usuario and not senha:
            dados.pop(portal, None)
        else:
            par = json.dumps({"usuario": usuario, "senha": senha})
            dados[portal] = _cifrar(par.encode("utf-8"))
        self._gravar(dados)

    def apagar(self, portal: str) -> None:
        self.guardar(portal, "", "")

    def portais(self) -> list[str]:
        return sorted(self._carregar())
