"""Pauta de audiências: o e-SAJ e o eProc lidos, monitorados e exportados em Excel.

Seção 8 da especificação (docs/ESPECIFICACAO.md). As partes:

    modelos.py      a Audiencia e a normalização (datas, horas, tipos, situações, id estável)
    regras.py       sinônimos de cabeçalho, menus, rotas e padrões (dados/pauta.json)
    tabelas.py      reconhecer a tabela de audiências (portal, planilha, PDF...)
    armazem.py      o banco SQLite (audiências, histórico de alterações, fontes)
    navegacao.py    a extração automática no portal já logado (rotas, menu, período, páginas)
    captura.py      a captura assistida (barra flutuante no navegador)
    importacao.py   relatórios exportados do SAJ/eProc (xlsx, xls, ods, csv, html, docx, pdf)
    exportacao.py   a planilha Excel (Pauta, Resumo, Alterações)
    monitor.py      quando sincronizar sozinho (a decisão; a thread é do aplicativo)
    servico.py      ServicoPauta, a fachada que a API, a linha de comando e o monitor usam
    cli.py          python -m helestron pauta sincronizar|exportar|importar|listar|fontes

Nada pesado é importado aqui: o servidor carrega servico.py no primeiro uso,
e o Playwright, o openpyxl e o PyMuPDF só entram quando a função pede.
"""
