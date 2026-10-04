"""Testes do Helestron (unittest).

Isolamento global: antes de qualquer teste importar o pacote helestron, as
pastas de dados do programa (HELESTRON_LOCAL: configuração, registros,
senhas, pauta) e dos documentos do usuário (HELESTRON_DADOS: acervo,
sigilosos, pauta exportada) passam a apontar para uma pasta temporária,
apagada no fim. helestron.nucleo.caminhos lê essas variáveis ao ser
importado; os processos-filhos (servidor, verificação, conector MCP) as
herdam. Assim, nenhum teste - nem um que esqueça o próprio isolamento -
grava em ~/.helestron, em Documentos\\Helestron, em %LOCALAPPDATA% ou na
raiz do repositório.

Os testes que precisam de pastas próprias continuam a criá-las (ou a trocar
as constantes de caminhos com mock.patch), como sempre.

O conector do Codex (CODEX_HOME\\config.toml) também vai para a pasta
isolada: um teste que chegue ao registro de verdade não mexe no
~/.codex/config.toml de quem roda os testes. No Linux, o XDG_CONFIG_HOME e
o XDG_CACHE_HOME também (o Chromium e o onnxruntime gravam neles).

Na descoberta (python -m unittest discover -s testes -t .), o último teste
(load_tests, abaixo) confere que a rodada não deixou nada novo na raiz do
repositório nem nas pastas do programa dentro do HOME. Uma pasta "tmpXXXX"
com config.ini, pauta.sqlite3 e Pauta/*.xlsx apareceu na raiz uma vez: veio
de um script avulso de reprodução que fazia tempfile.mkdtemp(dir=".") rodando
na raiz - nenhum teste da suíte cria temporário fora da pasta do sistema.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

if "helestron" in sys.modules or any(m.startswith("helestron.") for m in sys.modules):
    # Alguém importou o pacote antes dos testes (ex.: -m unittest com outro
    # módulo à frente): o isolamento ainda vale para os processos-filhos.
    print("Aviso: o pacote helestron foi importado antes de testes/__init__.py; "
          "o isolamento das pastas vale só a partir daqui.", file=sys.stderr)

# Um processo-filho de um teste que importe o pacote 'testes' (e que pode
# morrer sem rodar o atexit, como o da "queda de energia") herda a pasta do
# pai pelo ambiente e não cria outra: quem a criou é quem a apaga.
_HERDADA = os.environ.get("HELESTRON_TESTES_PASTA", "")
if _HERDADA and os.path.isdir(_HERDADA):
    _RAIZ = _HERDADA
else:
    _RAIZ = tempfile.mkdtemp(prefix="helestron-testes-")
    os.environ["HELESTRON_TESTES_PASTA"] = _RAIZ

    def _apagar() -> None:
        shutil.rmtree(_RAIZ, ignore_errors=True)

    atexit.register(_apagar)
os.environ["HELESTRON_LOCAL"] = os.path.join(_RAIZ, "local")
os.environ["HELESTRON_DADOS"] = os.path.join(_RAIZ, "documentos")
os.environ["CODEX_HOME"] = os.path.join(_RAIZ, "codex")
if sys.platform.startswith("linux"):
    # Bibliotecas de terceiros também gravam no HOME: o Chromium dos testes,
    # o "Crash Reports" em ~/.config/chromium; o onnxruntime, um banco em
    # ~/.cache/Microsoft. As duas seguem as variáveis do XDG, que durante os
    # testes apontam para a pasta isolada. Sem PLAYWRIGHT_BROWSERS_PATH, o
    # Playwright procura o navegador no XDG_CACHE_HOME: fica apontado para
    # onde ele já está instalado.
    _cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.join(_cache, "ms-playwright"))
    os.environ["XDG_CONFIG_HOME"] = os.path.join(_RAIZ, "xdg-config")
    os.environ["XDG_CACHE_HOME"] = os.path.join(_RAIZ, "xdg-cache")
os.makedirs(os.environ["HELESTRON_LOCAL"], exist_ok=True)
os.makedirs(os.environ["HELESTRON_DADOS"], exist_ok=True)
PASTA_ISOLADA = _RAIZ

# ------------------------------------------------- nada fica para trás
REPOSITORIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CASA = os.path.expanduser("~")
# O que o programa criaria no HOME se um teste escapasse do isolamento.
_DO_PROGRAMA_NO_HOME = [os.path.join(_CASA, *partes) for partes in (
    (".helestron",), ("Helestron",), ("Documents", "Helestron"), ("Documentos", "Helestron"),
    (".codex", "config.toml"), ("AppData", "Local", "Helestron"),
)]


def _no_home() -> set[str]:
    return {c for c in _DO_PROGRAMA_NO_HOME if os.path.lexists(c)}


def _previstos_na_raiz() -> set[str]:
    """O que a rodada pode criar na raiz de propósito: a pasta das capturas
    de tela (HELESTRON_CAPTURAS), quando o CI a põe no repositório."""
    previstos = set()
    capturas = os.environ.get("HELESTRON_CAPTURAS", "").strip()
    if capturas:
        relativo = os.path.relpath(os.path.abspath(capturas), REPOSITORIO)
        if not relativo.startswith(os.pardir) and not os.path.isabs(relativo):
            previstos.add(relativo.split(os.sep)[0])
    return previstos


RAIZ_NO_INICIO = frozenset(os.listdir(REPOSITORIO))
HOME_NO_INICIO = frozenset(_no_home())


def load_tests(loader, testes, padrao):
    """Descoberta pelo pacote: todos os módulos e, no fim, a conferência de
    que nada ficou na raiz do repositório nem nas pastas do programa no HOME."""
    import unittest

    pasta = os.path.dirname(os.path.abspath(__file__))
    testes.addTests(loader.discover(start_dir=pasta, pattern=padrao or "test*.py"))

    class NadaFicaParaTras(unittest.TestCase):
        def test_raiz_do_repositorio_e_home_sem_restos_dos_testes(self):
            novos = sorted(set(os.listdir(REPOSITORIO)) - RAIZ_NO_INICIO - _previstos_na_raiz())
            self.assertEqual(novos, [], "os testes deixaram isto na raiz do repositório "
                                        "(use uma pasta temporária do sistema)")
            criados = sorted(_no_home() - HOME_NO_INICIO)
            self.assertEqual(criados, [], "os testes criaram isto no HOME, fora do isolamento")

    testes.addTest(NadaFicaParaTras("test_raiz_do_repositorio_e_home_sem_restos_dos_testes"))
    return testes
