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
os.makedirs(os.environ["HELESTRON_LOCAL"], exist_ok=True)
os.makedirs(os.environ["HELESTRON_DADOS"], exist_ok=True)
PASTA_ISOLADA = _RAIZ
