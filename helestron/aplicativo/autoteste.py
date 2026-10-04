"""O autoteste da janela de verdade (python -m helestron --autoteste PASTA).

A interface, aberta com ?autoteste=1, percorre todas as seções sozinha e,
a cada uma já desenhada, avisa o servidor (POST /api/autoteste/passo
{secao}); o programa captura a janela (PNG) e, no fim (POST
/api/autoteste/fim {erros?}), grava o autoteste.json e fecha. É o que o CI
do Windows usa para provar que cada tela abre e desenha sem erro.

A captura usa o retângulo da janela (PIL.ImageGrab) e só existe no
Windows; fora dele o percurso é feito e registrado, sem as imagens. Se a
página não terminar no prazo, o autoteste falha sozinho - o CI nunca fica
esperando para sempre.
"""

from __future__ import annotations

import json
import logging
import platform
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import NOME, __version__

log = logging.getLogger("aplicativo.autoteste")

PRAZO_S = 240.0
ASSENTAR_S = 0.5
NO_WINDOWS = sys.platform == "win32"


class Autoteste:
    def __init__(self, app, pasta: Path, prazo_s: float = PRAZO_S, capturar: bool | None = None):
        self.app = app
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.prazo_s = prazo_s
        self.capturar_telas = NO_WINDOWS if capturar is None else capturar
        self.inicio = datetime.now()
        self.passos: list[dict] = []
        self.erros: list[str] = []
        self.interface: list = []
        self.terminou = threading.Event()
        self.codigo = 1
        self._trava = threading.Lock()
        self._vigia: threading.Timer | None = None

    @property
    def arquivo(self) -> Path:
        return self.pasta / "autoteste.json"

    def vigiar(self) -> None:
        self._vigia = threading.Timer(self.prazo_s, self._tempo_esgotado)
        self._vigia.daemon = True
        self._vigia.start()

    def _tempo_esgotado(self) -> None:
        if self.terminou.is_set():
            return
        with self._trava:
            self.erros.append(f"tempo esgotado: a interface não terminou o percurso em "
                              f"{int(self.prazo_s)} s")
            self.codigo = 1
            self._gravar(final=True)
        self.terminou.set()
        log.error("autoteste: tempo esgotado")
        self.app.encerrar_em_segundo_plano()

    # -------------------------------------------------------------- passos
    def passo(self, secao: str, dados: dict | None = None) -> dict:
        """Uma seção desenhada: captura (no Windows) e registra."""
        time.sleep(ASSENTAR_S)               # a animação de entrada termina
        registro = {"secao": secao, "quando": datetime.now().isoformat(timespec="seconds"),
                    "captura": None}
        if dados and dados.get("erro"):
            registro["erro"] = str(dados["erro"])[:500]
            self.erros.append(f"{secao}: {registro['erro']}")
        if self.capturar_telas:
            try:
                registro["captura"] = self._capturar(secao)
            except Exception as erro:
                registro["erro_captura"] = f"{type(erro).__name__}: {erro}"
                log.warning("autoteste: captura de %s falhou: %s", secao, erro)
        with self._trava:
            self.passos.append(registro)
            self._gravar()
        log.info("autoteste: %s", secao)
        return {"captura": registro["captura"]}

    def _capturar(self, secao: str) -> str | None:
        from PIL import ImageGrab

        janela = self.app.janela
        retangulo = janela.retangulo() if janela is not None else None
        extra = {"all_screens": True} if NO_WINDOWS else {}
        if retangulo is not None and retangulo[2] > 10 and retangulo[3] > 10:
            x, y, largura, altura = retangulo
            imagem = ImageGrab.grab(bbox=(x, y, x + largura, y + altura), **extra)
        else:
            imagem = ImageGrab.grab(**extra)
        nome = f"captura-{secao}.png"
        imagem.save(self.pasta / nome)
        return nome

    def fim(self, dados: dict | None = None) -> dict:
        dados = dados or {}
        with self._trava:
            for erro in dados.get("erros") or []:
                self.erros.append(str(erro)[:500])
            if isinstance(dados.get("secoes"), list):
                self.interface = dados["secoes"][:50]      # o que a página viu de cada seção
            capturas = [p for p in self.passos if p.get("captura")]
            ok = (bool(dados.get("ok", True)) and not self.erros and bool(self.passos)
                  and (not self.capturar_telas or len(capturas) == len(self.passos)))
            self.codigo = 0 if ok else 1
            self._gravar(final=True)
        self.terminou.set()
        if self._vigia is not None:
            self._vigia.cancel()
        log.info("autoteste concluído: %d seção(ões), %s", len(self.passos),
                 "sem falhas" if self.codigo == 0 else f"{len(self.erros)} falha(s)")
        return {"resultado": "ok" if self.codigo == 0 else "falha", "passos": len(self.passos)}

    def _gravar(self, final: bool = False) -> None:
        dados = {
            "programa": NOME, "versao": __version__, "plataforma": platform.platform(),
            "modo": getattr(self.app, "modo", ""), "inicio": self.inicio.isoformat(timespec="seconds"),
            "fim": datetime.now().isoformat(timespec="seconds") if final else None,
            "capturas": self.capturar_telas, "passos": self.passos, "erros": self.erros,
            "interface": self.interface,
            "resultado": ("ok" if self.codigo == 0 else "falha") if final else "em andamento",
        }
        tmp = self.arquivo.with_name(self.arquivo.name + ".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.arquivo)
