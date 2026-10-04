"""O servidor local do Helestron: a ponte entre a interface (helestron/web) e o motor.

    rede.py              servidor HTTP (127.0.0.1, token, Host/Origin), envelope, estáticos
    rotas.py             todas as rotas da API (seção 6.3 da especificação)
    api_*.py             os tratadores, por assunto (geral, processos, audiências, pauta,
                         compartilhar)
    aplicacao.py         o estado do programa aberto (configuração, tarefas, sessão...)
    eventos.py           o hub dos eventos SSE (seção 6.4)
    perguntas.py         as perguntas abertas do motor à interface (seção 6.5)
    trabalhos.py         as tarefas da API (helestron.tarefas com id, estado e eventos)
    audiencia.py         a audiência ao vivo e o teste do microfone
    esquema.py           os campos de Ajustes e a validação do config.ini
    multipart.py         leitura de envio de arquivo, sem o módulo cgi
"""
