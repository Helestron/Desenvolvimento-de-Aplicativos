"""Abre o Assessor Integrado: é o alvo dos atalhos (pythonw.exe, sem console).

Sob o pythonw não existe console: um erro antes de a janela abrir morreria em
silêncio, e o usuário veria apenas que "clicou e nada aconteceu" - a queixa
mais comum do Assessor SAJ. Aqui, todo erro vira uma mensagem na tela, com a
orientação de rodar o INSTALAR.bat de novo, e fica registrado em
Logs\\erro-ao-abrir.log para o suporte.

Também resolve o "No module named app" de quem abria o programa a partir de
outra pasta (ou de uma pasta de rede): a pasta do programa entra no
sys.path e vira a pasta atual antes de qualquer import do programa.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ARQUIVO_ERRO = RAIZ / "Logs" / "erro-ao-abrir.log"
TITULO = "Assessor Integrado"
CONSERTO = ("Rode o INSTALAR.bat de novo (dois cliques nele, nesta pasta): ele "
            "conserta a instalação sem apagar os seus arquivos.")


def preparar() -> None:
    """Pasta do programa no sys.path e como pasta atual; ambiente previsível."""
    os.chdir(RAIZ)
    raiz = str(RAIZ)
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    # Pacotes instalados "só para o usuário" por OUTRO Python 3.12 deste
    # computador (%APPDATA%\Python\Python312) entrariam no caminho e
    # passariam na frente das versões testadas. Os atalhos já usam -s; isto
    # cobre quem abre o arquivo por outro caminho (duplo clique no .pyw).
    try:
        import site

        do_usuario = os.path.normcase(os.path.abspath(site.getusersitepackages()))
        sys.path[:] = [p for p in sys.path
                       if os.path.normcase(os.path.abspath(p or ".")) != do_usuario]
    except Exception:
        pass
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(RAIZ / "runtime" / "navegador"))


def mensagem_amigavel(erro: BaseException) -> str:
    """O que dizer ao usuário (o detalhe técnico vai para o arquivo de log)."""
    if isinstance(erro, ModuleNotFoundError):
        nome = erro.name or ""
        if nome == "app" or nome.startswith("app."):
            return ("Faltam arquivos do programa nesta pasta.\n\n"
                    "Extraia de novo o arquivo ZIP inteiro e rode o INSTALAR.bat.")
        return f"Falta a biblioteca “{nome}”.\n\n{CONSERTO}"
    texto = str(erro)
    if isinstance(erro, ImportError) or "DLL" in texto:
        return f"Um componente do programa não carregou:\n{texto}\n\n{CONSERTO}"
    return ("O programa encontrou um erro ao abrir:\n"
            f"{type(erro).__name__}: {texto}\n\n{CONSERTO}")


def registrar_erro(detalhes: str) -> Path | None:
    """Acrescenta o erro ao Logs\\erro-ao-abrir.log; devolve o arquivo (ou None)."""
    try:
        ARQUIVO_ERRO.parent.mkdir(parents=True, exist_ok=True)
        with open(ARQUIVO_ERRO, "a", encoding="utf-8") as arq:
            arq.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            arq.write(f"Python {sys.version.split()[0]} em {sys.executable}\n")
            arq.write(f"Pasta: {RAIZ}\nArgumentos: {sys.argv[1:]}\n")
            arq.write(detalhes.rstrip() + "\n\n")
        return ARQUIVO_ERRO
    except OSError:
        return None


def mostrar_erro(texto: str) -> None:
    """Caixa de mensagem; sem Tk (instalação quebrada), a do próprio Windows."""
    try:
        import tkinter
        from tkinter import messagebox

        raiz = tkinter.Tk()
        raiz.withdraw()
        messagebox.showerror(TITULO, texto, parent=raiz)
        raiz.destroy()
        return
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, texto, TITULO, 0x10)  # MB_ICONERROR
            return
        except Exception:
            pass
    try:
        if sys.stderr is not None:
            sys.stderr.write(texto + "\n")
    except Exception:
        pass


def _carregar_main():
    """O ponto de entrada do programa (separado para os testes trocarem)."""
    from app.__main__ import main

    return main


def principal(argv: list[str] | None = None) -> int:
    try:
        preparar()
        main = _carregar_main()
        return int(main(list(sys.argv[1:] if argv is None else argv)) or 0)
    except SystemExit as saida:
        codigo = saida.code
        if codigo is None or isinstance(codigo, int):
            return codigo or 0
        return 1
    except KeyboardInterrupt:
        return 130
    except BaseException as erro:  # noqa: BLE001 - qualquer erro vira mensagem
        arquivo = registrar_erro(traceback.format_exc())
        texto = mensagem_amigavel(erro)
        if arquivo is not None:
            texto += f"\n\nSe o problema continuar, envie ao suporte o arquivo:\n{arquivo}"
        mostrar_erro(texto)
        return 1


if __name__ == "__main__":
    sys.exit(principal())
