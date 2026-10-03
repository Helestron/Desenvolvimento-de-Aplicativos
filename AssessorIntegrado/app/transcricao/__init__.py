"""Transcrição de audiências: ao vivo (microfone) e de gravações.

Módulos (nenhum importa biblioteca pesada no topo: a janela abre rápido e
cada função ausente explica o que fazer):
  segmentador  corta o som contínuo em trechos de fala (numpy puro)
  microfone    captura do microfone; CapturaDeArquivo para testes e CI
  modelos      baixa e carrega o Whisper; filtro de alucinações
  ao_vivo      SessaoAoVivo: grava, transcreve, salva e recupera
  arquivo      transcrição de gravação inteira (e revisão da ao vivo)
  falantes     separação automática de vozes (opcional, sherpa-onnx)
  documento    DOCX com ficha da audiência; Fala e MetaAudiencia
  cli          linha de comando (python -m app transcrever/modelos/falantes)
"""
