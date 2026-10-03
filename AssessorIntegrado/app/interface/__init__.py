"""A janela do Assessor Integrado (Tkinter + ttk, tema próprio).

    janela ............... a janela, a fila de eventos, o fechar seguro, o teste do CI
    estilo ............... paleta, fontes, escala de tela (DPI), botões arredondados
    componentes .......... barra lateral, cartões, faixas, tabelas, rolagem
    tarefas .............. recursos, tarefas em segundo plano, ContextoTela
    servicos ............. o único ponto que chama download, transcrição e verificação
    acessos .............. editor do acesso a um portal (modo, usuário, senha)
    dialogos ............. código de verificação, colar lista, link, assistente
    pagina_* ............. Início, Baixar, Transcrever, Compartilhar, Configurações, Ajuda
    recursos/ ............ ícones (gerados por ferramentas/gerar_icones.py)

Nada aqui importa biblioteca pesada no topo: a janela abre em menos de um
segundo mesmo sem faster-whisper, Playwright ou PyMuPDF instalados.
"""
