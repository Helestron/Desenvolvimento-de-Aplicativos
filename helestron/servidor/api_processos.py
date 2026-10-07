"""API de Processos: ler a relação e baixar os autos (um PDF por processo).

A relação chega por envio de arquivo (multipart, campo 'arquivo'), pelo
caminho escolhido no diálogo da janela, por texto colado ou por link. A
leitura é a do motor (helestron.nucleo.listas): acha os números em
qualquer coluna ou parágrafo, avisa o dígito errado e a planilha que
corrompeu o número.

As senhas dos sigilosos que vierem na relação (coluna "senha") ficam só na
memória do servidor (Aplicacao.senhas_relacao) e seguem para o lote; a
página recebe apenas 'tem_senha'. O arquivo enviado é apagado logo depois
de lido: pode trazer essas senhas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .. import servicos
from ..nucleo import caminhos, cnj, sistema, tribunais
from ..tarefas import NAVEGADOR, NUVEM
from .api_audiencias import _com_outro_nome
from .api_geral import iso, maiuscula
from .rede import ErroApi, Pedido, Roteador, erro_400

log = logging.getLogger("servidor.processos")

FALHAS = {"ERRO", "NAO_ENCONTRADO", "SEM_ACESSO", "NAO_SUPORTADO", "SIGILOSO_SEM_SENHA"}
LIMITE_PROCESSOS = 5000


def registrar(r: Roteador) -> None:
    r.adicionar("POST", "/api/relacao/arquivo", relacao_arquivo)
    r.adicionar("POST", "/api/relacao/texto", relacao_texto)
    r.adicionar("POST", "/api/relacao/link", relacao_link)
    r.adicionar("POST", "/api/download/iniciar", iniciar_download)
    r.adicionar("GET", "/api/download/lotes", lotes)


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


# ==================================================================== relação
def leitura_para_json(app, leitura, nome_lote: str = "") -> dict:
    """A Leitura do motor no formato da API (seção 6.3)."""
    processos, sem_suporte = [], []
    catalogo: dict[str, object] = {}
    for n in leitura.processos:
        if n.chave_tribunal not in catalogo:
            catalogo[n.chave_tribunal] = tribunais.por_numero(n)
        t = catalogo[n.chave_tribunal]
        senha = leitura.senhas.get(n.formatado, "")
        if senha:
            app.senhas_relacao[n.formatado] = senha
        if t is None:
            sem_suporte.append({"numero": n.formatado,
                                "motivo": f"Tribunal {n.chave_tribunal} desconhecido."})
            continue
        if not t.suportado:
            sem_suporte.append({"numero": n.formatado,
                                "motivo": f"O {t.sigla} usa um sistema que o Helestron ainda "
                                          "não acessa (PJe, Projudi)."})
            continue
        alt = t.alternativo
        processos.append({
            "numero": n.formatado, "tribunal": t.sigla, "sistema": t.sistema,
            "alternativo": alt.sistema if alt is not None and alt.suportado else None,
            "descricao": tribunais.descrever(n), "tem_senha": bool(senha),
            "digito_confere": n.digito_confere, "dependente": n.e_dependente,
        })
    avisos = []
    # Só os que entram no lote: o de tribunal sem suporte já tem o seu aviso.
    errados = [cnj.ler(p["numero"]) for p in processos if not p["digito_confere"]]
    if errados:
        exemplos = ", ".join(n.formatado for n in errados[:3]) + ("…" if len(errados) > 3 else "")
        avisos.append(("1 número tem" if len(errados) == 1 else f"{len(errados)} números têm")
                      + " o dígito verificador errado — provável erro de digitação ("
                      + exemplos + "). Confira na relação antes de baixar.")
    if leitura.corrompidos:
        uma = len(leitura.corrompidos) == 1
        avisos.append(f"{_plural(len(leitura.corrompidos), 'linha')} da planilha "
                      f"{'guarda' if uma else 'guardam'} o número como NÚMERO, e o Excel "
                      f"corrompe os últimos dígitos: {'ficou' if uma else 'ficaram'} de fora de "
                      "propósito. Formate a coluna como Texto, digite "
                      f"{'o número' if uma else 'os números'} de novo e abra a relação "
                      "outra vez.")
    if sem_suporte:
        um = len(sem_suporte) == 1
        avisos.append(f"{_plural(len(sem_suporte), 'processo')} {'é' if um else 'são'} de "
                      "tribunal cujo sistema o Helestron ainda não acessa: "
                      f"{'fica' if um else 'ficam'} de fora do lote.")
    avisos += [maiuscula(a) for a in leitura.avisos[:5]]
    origem = Path(leitura.origem).name if leitura.origem else ""
    if not nome_lote:
        nome_lote = Path(origem).stem if origem else f"Lista {datetime.now():%Y-%m-%d %Hh%M}"
    return {"formato": leitura.formato, "origem": origem,
            "nome_lote": sistema.nome_seguro(nome_lote, "Relação"),
            "processos": processos, "avisos": avisos,
            "corrompidos": list(leitura.corrompidos), "sem_suporte": sem_suporte}


def _ler_arquivo(caminho: Path):
    from ..nucleo import listas

    return listas.ler_arquivo(caminho)


def relacao_arquivo(p: Pedido) -> dict:
    app = p.app
    if p.tipo_corpo == "multipart/form-data":
        with p.envio(app.pasta_envios()) as envio:
            arquivo = envio.arquivo("arquivo")
            if arquivo is None:
                raise erro_400("Envie o arquivo da relação no campo “arquivo”.", "campo_ausente")
            try:
                leitura = _ler_arquivo(arquivo.caminho)
            except Exception as erro:
                # O leitor só conhece o temporário do envio: a frase ("o arquivo
                # envio-3f6e….xlsx parece danificado") diz o nome do arquivo do
                # usuário.
                if arquivo.caminho.name in str(erro):
                    raise _com_outro_nome(erro, arquivo.caminho.name, arquivo.nome) from erro
                raise
            leitura.origem = arquivo.nome
        return leitura_para_json(app, leitura, Path(arquivo.nome).stem)
    caminho = Path(p.campo("caminho", obrigatorio=True, tipo=str).strip().strip('"'))
    if not caminho.is_absolute():
        raise erro_400("Informe o caminho completo do arquivo.", "valor_invalido")
    if not caminho.is_file():
        raise ErroApi(404, "arquivo_inexistente", f"Não encontrei o arquivo {caminho.name}.")
    leitura = _ler_arquivo(caminho)
    try:
        app.cfg.definir("interface", "pasta_relacoes", str(caminho.parent))
    except Exception:
        pass
    return leitura_para_json(app, leitura, caminho.stem)


def relacao_texto(p: Pedido) -> dict:
    from ..nucleo import listas

    texto = p.campo("texto", obrigatorio=True, tipo=str)
    if len(texto) > 1_000_000:
        raise erro_400("O texto colado é grande demais. Use “Escolher arquivo”.")
    leitura = listas.ler_texto(texto)
    if not leitura.processos:
        raise erro_400("Não achei nenhum número de processo no texto colado. Confira se os "
                       "números estão no padrão CNJ (0000000-00.0000.0.00.0000).",
                       "relacao_invalida")
    return leitura_para_json(p.app, leitura, f"Lista {datetime.now():%Y-%m-%d %Hh%M}")


def relacao_link(p: Pedido) -> dict:
    from ..nucleo import listas

    url = p.campo("url", obrigatorio=True, tipo=str).strip()
    if not url.lower().startswith(("https://", "http://")):
        raise erro_400("Cole o link completo (começando por https://).", "valor_invalido")
    arquivo = listas.baixar_link(url, Path(caminhos.TEMP) / "listas")
    try:
        leitura = listas.ler_arquivo(arquivo)
    finally:
        # A relação pode trazer as senhas dos sigilosos: lida, não fica no disco.
        try:
            arquivo.unlink()
        except OSError:
            log.warning("não consegui apagar a relação baixada %s", arquivo.name)
    leitura.origem = arquivo.name
    return leitura_para_json(p.app, leitura, arquivo.stem)


# =================================================================== download
def _numeros(lista) -> list:
    if not isinstance(lista, list) or not lista:
        raise erro_400("Informe ao menos um processo.", "processos_ausentes")
    if len(lista) > LIMITE_PROCESSOS:
        raise erro_400(f"Lotes de até {LIMITE_PROCESSOS} processos.", "valor_invalido")
    numeros, invalidos, vistos = [], [], set()
    for item in lista:
        try:
            n = cnj.ler(str(item))
        except cnj.NumeroInvalido:
            invalidos.append(str(item))
            continue
        if cnj.chave(n) not in vistos:
            vistos.add(cnj.chave(n))
            numeros.append(n)
    if invalidos:
        raise erro_400("Números fora do padrão CNJ: " + ", ".join(invalidos[:5])
                       + ("…" if len(invalidos) > 5 else "") + ".", "numero_invalido")
    return numeros


def _observacao(r, destino: Path) -> str:
    """O que a linha do processo diz além da situação (sigilo, folhas, detalhe)."""
    obs = []
    if r.sigiloso:
        if not r.arquivo:
            obs.append("sigiloso")
        elif Path(r.arquivo).parent == Path(destino):
            obs.append("SIGILOSO: ficou na pasta do lote, com os demais")
        else:
            obs.append("sigiloso (na pasta dos sigilosos)")
    if r.incompleto:
        obs.append(f"faltam documentos: {r.incompleto}" if r.sistema == "eproc"
                   else f"faltam as folhas {r.incompleto}")
    if r.detalhe:
        obs.append(r.detalhe)
    return "; ".join(obs)


def item_json(tw, r, destino: Path) -> dict:
    """A linha do processo no formato da API. 'causa' (por que não deu OK, um
    código de modelos.CAUSAS) e 'refazer' (uma nova rodada pode mudar o
    desfecho?) são os mesmos do relatorio.csv e do JSON da linha de comando:
    quem acompanha o lote pela API decide por eles, sem adivinhar pelo texto."""
    causa = getattr(r, "causa", "")
    refazer = getattr(r, "refazer", False)
    return {"tarefa": tw.id, "numero": r.numero, "situacao": r.situacao or "",
            "rotulo": r.rotulo, "mensagem": _observacao(r, destino), "arquivo": r.arquivo or "",
            "sigiloso": bool(r.sigiloso), "paginas": r.paginas or 0, "tribunal": r.tribunal,
            "sistema": r.sistema, "ordem": r.ordem,
            "causa": causa if isinstance(causa, str) else "",
            "refazer": refazer if isinstance(refazer, bool) else False}


def exigir_pastas_separadas(app) -> None:
    """Recusa (409) o lote enquanto a pasta dos sigilosos ou a da pauta
    estiver dentro do acervo (ou o acervo dentro dela) - a regra única de
    servicos.problema_nas_pastas, a mesma do Compartilhar
    (api_compartilhar.exigir_pastas_separadas) e das pendências do Início.

    Com as pastas assim, o processo sigiloso baixado iria para a pasta dos
    sigilosos DENTRO do acervo - lido pela IA e copiado para a nuvem com o
    resto -, e o motor ainda diria que ele ficou "na pasta dos sigilosos"."""
    cfg = app.cfg
    frase = servicos.problema_nas_pastas(cfg.pasta_acervo, cfg.pasta_sigilosos,
                                         servicos.pasta_pauta(cfg))
    if frase:
        raise ErroApi(409, "pastas_em_conflito",
                      frase + " Corrija em Ajustes › Pastas antes de baixar os processos.")


def iniciar_lote(app, numeros: list, nome_lote: str, opcoes_pedido: dict | None = None,
                 senhas_pedido: dict | None = None, titulo: str = "") -> object:
    """Começa o lote de download (usado também pela pauta: "Baixar autos").
    Com as pastas em conflito, recusa (409) antes de abrir o navegador."""
    exigir_pastas_separadas(app)
    cfg = app.cfg
    opcoes = servicos.opcoes_download(cfg)
    extra = opcoes_pedido or {}
    if "separar_sigilosos" in extra:
        opcoes.separar_sigilosos = bool(extra["separar_sigilosos"])
    if "rebaixar" in extra:
        opcoes.pular_baixados = not bool(extra["rebaixar"])
    if "navegador_visivel" in extra:
        opcoes.mostrar_navegador = bool(extra["navegador_visivel"])
    nome = sistema.nome_seguro(nome_lote or f"Lote {datetime.now():%Y-%m-%d %Hh%M}", "Lote")
    destino = Path(cfg.pasta_processos) / nome
    senhas = {n.formatado: app.senhas_relacao[n.formatado]
              for n in numeros if n.formatado in app.senhas_relacao}
    for chave, valor in (senhas_pedido or {}).items():
        if valor:
            senhas[str(chave)] = str(valor)
    cofre = servicos.CofreMisto(servicos.cofre(), app.credenciais_sessao)

    def preparar(tw) -> None:
        def ao_item(r) -> None:
            dados = item_json(tw, r, destino)
            tw.itens[r.numero] = dados
            app.hub.publicar("item", dados)

        def ao_progresso(feitos, total, atual) -> None:
            if atual and atual in tw.itens and not tw.itens[atual].get("situacao"):
                dados = dict(tw.itens[atual], situacao="BAIXANDO", rotulo="baixando…")
                tw.itens[atual] = dados
                app.hub.publicar("item", dados)

        tw.ao_item = ao_item
        tw.ao_progresso = ao_progresso
        tw.dados["destino"] = str(destino)
        tw.definir_progresso(0, len(numeros), "")
        tw.status = "Preparando o navegador…"

    def alvo(tw):
        resumo = servicos.baixar_lote(numeros, destino, opcoes, tw.contexto(), senhas, cofre, cfg)
        presos = [Path(x) for x in (getattr(resumo, "sigilosos_no_acervo", None) or [])]
        for p in presos:
            if p not in app.sigilosos_presos:
                app.sigilosos_presos.append(p)
        # O resto do sigiloso que ficou no acervo (a transcrição aberta, a
        # minuta): não trava o compartilhamento, mas fica avisado no Início.
        avisos = getattr(resumo, "sigilosos_avisos", None) or []
        if not isinstance(getattr(app, "sigilosos_avisos", None), list):
            app.sigilosos_avisos = []
        for p in (Path(x) for x in avisos):
            if p not in app.sigilosos_avisos:
                app.sigilosos_avisos.append(p)
        motivos = getattr(resumo, "sigilosos_motivos", None)
        if isinstance(motivos, dict):
            if not isinstance(getattr(app, "sigilosos_motivos", None), dict):
                app.sigilosos_motivos = {}
            app.sigilosos_motivos.update({Path(k): str(v) for k, v in motivos.items()})
        for r in resumo.itens:
            dados = item_json(tw, r, destino)
            tw.itens[r.numero] = dados
        tw.definir_status(maiuscula(resumo.texto()))
        if not tw.parar.is_set():
            _espelhar_ao_fim(app)
        return {"texto": maiuscula(resumo.texto()), "pasta": str(resumo.destino),
                "relatorio": str(resumo.relatorio), "total": len(resumo.itens),
                "baixados": len(resumo.baixados), "pulados": len(resumo.pulados),
                "falhas": len(resumo.falhas), "pendentes": len(resumo.pendentes),
                "sigilosos": len(resumo.sigilosos),
                "a_refazer": list(resumo.a_refazer()),
                "sigilosos_no_acervo": [str(p) for p in presos],
                "minutos": round(float(getattr(resumo, "minutos", 0) or 0), 1)}

    titulo = titulo or f"Baixar {_plural(len(numeros), 'processo')}"
    tw = app.tarefas.iniciar("download", titulo, alvo, (NAVEGADOR,), chave="download",
                             preparar=preparar)
    return tw


def _espelhar_ao_fim(app) -> None:
    """Espelho automático na nuvem ao fim do lote, se ligado e sem sigiloso preso.

    Como no "Espelhar agora", o preparo rápido vem antes da cópia: o INDICE.md
    passa a listar o lote que acabou de chegar e o processo que o programa já
    sabe sigiloso (a pasta dos sigilosos, a pauta - que pode tê-lo revelado
    durante o lote) sai do acervo antes de a nuvem receber a cópia. Se os
    autos dele não puderem sair, a cópia não acontece: a tarefa termina com a
    frase da tela Compartilhar, e o Início mostra a pendência."""
    cfg = app.cfg
    destino = cfg.texto("compartilhar", "pasta_nuvem")
    if not (destino and cfg.flag("compartilhar", "espelhar_automaticamente")) or app.fechando:
        return
    if any(Path(p).exists() for p in app.sigilosos_presos):
        log.warning("Espelho na nuvem NÃO feito: há processo sigiloso no acervo.")
        return
    from .api_compartilhar import concluir_espelho, nuvem_sem_conflito, preparar_e_conferir

    if not nuvem_sem_conflito(cfg, destino):
        return
    from ..compartilhar import nuvem

    def alvo(tw):
        tw.definir_status("Atualizando o índice do acervo…")
        preparar_e_conferir(app, extrair_texto=False)
        if tw.cancelado():
            return {"copiados": 0, "iguais": 0}
        tw.definir_status("Copiando o acervo para a nuvem…")
        resultado = nuvem.espelhar(cfg.pasta_acervo, Path(destino),
                                   lambda f, t, n: tw.definir_progresso(f, t, n), tw.cancelado)
        # O resumo do Espelho ("K NÃO copiados") no status, e o aviso na tela
        return concluir_espelho(tw, resultado, cfg.pasta_acervo, destino)

    try:
        app.tarefas.iniciar("nuvem", "Espelhar o acervo na nuvem", alvo, (NUVEM,), chave="nuvem")
    except Exception as erro:
        log.info("espelho na nuvem adiado: %s", erro)


def iniciar_download(p: Pedido) -> dict:
    numeros = _numeros(p.campo("processos", obrigatorio=True, tipo=list))
    senhas = p.campo("senhas", padrao={}, tipo=dict)
    opcoes = p.campo("opcoes", padrao={}, tipo=dict)
    nome_lote = p.campo("nome_lote", padrao="", tipo=str)
    tw = iniciar_lote(p.app, numeros, nome_lote, opcoes, senhas)
    return {"tarefa": tw.id, "pasta": tw.dados.get("destino")}


def lotes(p: Pedido) -> list[dict]:
    saida = []
    for info in servicos.ultimos_lotes(p.app.cfg, 30):
        saida.append({"nome": info.nome, "quando": iso(info.quando), "total": info.total,
                      "baixados": info.baixados, "falhas": info.falhas,
                      "pasta": str(info.pasta), "relatorio": str(info.relatorio)})
    return saida
