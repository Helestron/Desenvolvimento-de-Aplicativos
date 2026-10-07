"""API de Audiências: microfone, modelos, transcrição ao vivo e de gravação."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from .. import servicos
from ..nucleo import caminhos
from ..tarefas import MODELO_REVISAO
from .audiencia import numero_da_gravacao, quando, sigilo_da_audiencia
from .rede import ErroApi, Pedido, Roteador, erro_400

log = logging.getLogger("servidor.audiencias")

ROTULOS_MODELO = {"base": "Base", "small": "Small", "medium": "Medium",
                  "large-v3-turbo": "Large v3 Turbo"}
RECOMENDADO = {"base": ["ao_vivo"], "small": ["ao_vivo"], "medium": ["revisao"],
               "large-v3-turbo": ["revisao"]}
# O envio da gravação pela página (Edge, navegador, ou arrastada para a tela):
# o vídeo de uma audiência longa tem gigabytes. O arquivo vai para o disco em
# blocos, depois de conferido o espaço livre (rede.Pedido.envio). Escolhido
# pelo diálogo do Windows, nada é enviado: vai só o caminho.
LIMITE_ENVIO_GRAVACAO = 20 * 1024 ** 3


def registrar(r: Roteador) -> None:
    r.adicionar("GET", "/api/transcricao/microfones", microfones)
    r.adicionar("POST", "/api/transcricao/microfone/teste", testar_microfone)
    r.adicionar("POST", "/api/transcricao/microfone/parar", parar_microfone)
    r.adicionar("GET", "/api/transcricao/modelos", modelos)
    r.adicionar("POST", "/api/transcricao/modelos/baixar", baixar_modelo)
    r.adicionar("GET", "/api/transcricao/falantes", falantes)
    r.adicionar("POST", "/api/transcricao/falantes/baixar", baixar_falantes)
    r.adicionar("POST", "/api/transcricao/iniciar", iniciar)
    r.adicionar("POST", "/api/transcricao/pausar", pausar)
    r.adicionar("POST", "/api/transcricao/retomar", retomar)
    r.adicionar("POST", "/api/transcricao/falante", falante)
    r.adicionar("POST", "/api/transcricao/encerrar", encerrar)
    r.adicionar("GET", "/api/transcricao/estado", estado)
    r.adicionar("GET", "/api/transcricao/recuperaveis", recuperaveis)
    r.adicionar("POST", "/api/transcricao/recuperar", recuperar)
    r.adicionar("POST", "/api/transcricao/gravacao", gravacao,
                limite_envio=LIMITE_ENVIO_GRAVACAO)
    r.adicionar("GET", "/api/transcricao/recentes", recentes)


# ================================================================= microfone
def microfones(p: Pedido) -> list[dict]:
    lista = servicos.listar_microfones()
    return [{"indice": getattr(e, "indice", None), "nome": getattr(e, "nome", str(e)),
             "padrao": bool(getattr(e, "padrao", False))} for e in lista]


def testar_microfone(p: Pedido) -> dict:
    return p.app.audiencia.testar_microfone(p.campo("dispositivo", padrao=None))


def parar_microfone(p: Pedido) -> dict:
    return p.app.audiencia.parar_teste()


# ==================================================================== modelos
def _embutido(nome: str) -> bool:
    pasta = getattr(caminhos, "MODELOS_EMBUTIDOS", None)
    if pasta is None:
        return False
    alvo = Path(pasta) / f"faster-whisper-{nome}"
    return (alvo / "model.bin").is_file()


def modelos(p: Pedido) -> list[dict]:
    saida = []
    for m in servicos.modelos_disponiveis():
        nome = m.get("nome", "")
        saida.append({"nome": nome, "rotulo": ROTULOS_MODELO.get(nome, nome),
                      "tamanho_mb": m.get("mb") or m.get("tamanho_mb") or 0,
                      "instalado": bool(m.get("instalado")),
                      "embutido": bool(m["embutido"]) if "embutido" in m else _embutido(nome),
                      "recomendado_para": RECOMENDADO.get(nome, []),
                      "descricao": m.get("descricao", "")})
    return saida


def baixar_modelo(p: Pedido) -> dict:
    nome = p.campo("nome", obrigatorio=True, tipo=str).strip()
    conhecidos = {m.get("nome") for m in servicos.modelos_disponiveis()}
    if conhecidos and nome not in conhecidos:
        raise erro_400(f"Modelo desconhecido: {nome}.", "valor_invalido")

    def alvo(tw):
        tw.definir_status(f"Baixando o modelo {nome}…")
        pasta = servicos.baixar_modelo(nome, lambda f, t="": tw.definir_fracao(f, t))
        tw.definir_fracao(1.0, "Modelo pronto.")
        return {"nome": nome, "pasta": str(pasta)}

    tw = p.app.tarefas.iniciar("modelo", f"Baixar o modelo {nome}", alvo, chave=f"modelo:{nome}")
    return {"tarefa": tw.id}


# ================================================== separação de falantes
def falantes(p: Pedido) -> dict:
    return servicos.falantes_estado()


def baixar_falantes(p: Pedido) -> dict:
    """Os modelos de voz da separação de falantes, quando a construção não os
    embutiu (a biblioteca vem sempre no instalador)."""
    estado = servicos.falantes_estado()
    if not estado.get("biblioteca"):
        raise ErroApi(409, "componente_ausente",
                      "A separação de falantes não está nesta instalação (falta o componente "
                      "sherpa-onnx). " + servicos.DICA_INSTALAR)

    def alvo(tw):
        tw.definir_fracao(0.0, f"Baixando os modelos de voz (cerca de {estado.get('tamanho_mb', 47)} MB)…")
        servicos.instalar_falantes(lambda f, t="": tw.definir_fracao(f, t), cancelado=tw.cancelado)
        tw.definir_fracao(1.0, "Separação de falantes pronta.")
        return servicos.falantes_estado()

    tw = p.app.tarefas.iniciar("modelo", "Baixar os modelos de voz", alvo, chave="falantes")
    return {"tarefa": tw.id}


# ================================================================== ao vivo
def iniciar(p: Pedido) -> dict:
    return p.app.audiencia.iniciar(p.json())


def pausar(p: Pedido) -> dict:
    return p.app.audiencia.pausar()


def retomar(p: Pedido) -> dict:
    return p.app.audiencia.retomar()


def falante(p: Pedido) -> dict:
    return p.app.audiencia.definir_falante(p.campo("falante", padrao="", tipo=str))


def encerrar(p: Pedido) -> dict:
    dados = p.json()
    refinar = dados.get("refinar")
    tipo = dados.get("tipo")
    return p.app.audiencia.encerrar(None if refinar is None else bool(refinar),
                                    tipo=str(tipo).strip() if tipo else None)


def estado(p: Pedido) -> dict:
    return p.app.audiencia.como_dict()


def recuperaveis(p: Pedido) -> list[dict]:
    saida = []
    for diario in servicos.recuperaveis(p.app.cfg):
        numero = servicos.numero_no_nome(Path(diario))
        saida.append({"arquivo": str(diario),
                      "processo": numero.formatado if numero is not None else None,
                      "quando": quando(diario)})
    return saida


def recuperar(p: Pedido) -> dict:
    alvo = p.campo("arquivo", obrigatorio=True, tipo=str)
    # Só o que a própria busca achou: o caminho não vem livre da página.
    validos = {str(Path(x)) for x in servicos.recuperaveis(p.app.cfg)}
    if str(Path(alvo)) not in validos:
        raise ErroApi(404, "nao_recuperavel",
                      "Esta transcrição não está entre as interrompidas (já foi recuperada?).")
    documento = Path(servicos.recuperar(Path(alvo)))
    # Como ao fim da audiência: o INDICE.md em dia (a IA o lê primeiro) e, se
    # ligado, o espelho na nuvem. Não bloqueia (tarefa ou thread própria).
    from .api_compartilhar import depois_de_salvar

    depois_de_salvar(p.app, documento)
    p.app.hub.publicar("estado", {})
    return {"documento": str(documento)}


# ================================================================== gravação
_RE_DATA_NO_NOME = re.compile(r"(20\d\d)-(\d\d)-(\d\d)(?:[ _T]+(\d\d)h(\d\d))?")
MOTIVO_PASTA = "A gravação está guardada na pasta dos sigilosos."
MOTIVO_ULTIMA = "A audiência ao vivo foi gravada como sigilosa."


def data_da_gravacao(valor, nome: str = "") -> datetime | None:
    """A data da gravação que o envio pela página perderia (o arquivo chega
    como um temporário de hoje): o 'data_arquivo' da página (File.lastModified,
    em milissegundos, ou ISO 8601) ou, na falta dele, a data no nome do
    arquivo ("<número> 2026-09-15 14h00.flac", como o Helestron grava)."""
    texto = str(valor if valor is not None else "").strip()
    if texto:
        try:
            numero = float(texto)
            return datetime.fromtimestamp(numero / 1000 if numero > 1e11 else numero)
        except (ValueError, OverflowError, OSError):
            pass
        try:
            momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            momento = None
        if momento is not None:
            # com fuso (o toISOString do navegador): na hora local, sem fuso
            return momento.astimezone().replace(tzinfo=None) if momento.tzinfo else momento
    m = _RE_DATA_NO_NOME.search(nome or "")
    if m:
        try:
            ano, mes, dia = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hora, minuto = (int(m.group(4)), int(m.group(5))) if m.group(4) else (0, 0)
            return datetime(ano, mes, dia, hora, minuto)
        except ValueError:
            return None
    return None


def _com_outro_nome(erro: Exception, temporario: str, nome: str) -> Exception:
    """A mesma exceção (o mesmo tipo: a tarefa e o registro a reconhecem por
    ele), com o nome do temporário trocado pelo do arquivo do usuário."""
    texto = str(erro).replace(temporario, nome)
    try:
        return type(erro)(texto)
    except Exception:                          # tipo que não se cria só com a frase
        return RuntimeError(texto)


def _transcricao_em_andamento(app) -> str:
    """O título da transcrição de gravação (ou revisão) que está rodando, ou ""."""
    try:
        tarefa = app.tarefas.ativa("transcricao_arquivo")
    except Exception:                          # a conferência é só um adianto
        return ""
    return str(getattr(tarefa, "titulo", "") or "Transcrever a gravação") if tarefa else ""


def gravacao(p: Pedido) -> dict:
    """Transcreve uma gravação: {caminho} (escolhida pelo diálogo do Windows:
    nada é copiado), o envio da página (multipart, campo "arquivo", até
    LIMITE_ENVIO_GRAVACAO) ou {revisao: true} (a última audiência ao vivo).

    O arquivo não é recusado pela extensão: a decodificação (PyAV) é que
    diz, na tarefa, se há trilha de áudio, se o arquivo está cortado ou se é
    protegido por DRM.
    """
    app = p.app
    cfg = app.cfg
    enviado: Path | None = None
    tamanho = None
    if p.tipo_corpo == "multipart/form-data":
        # Uma transcrição de cada vez: com outra rodando, recusa ANTES de
        # receber gigabytes que seriam jogados fora.
        ocupada = _transcricao_em_andamento(app)
        if ocupada:
            raise ErroApi(409, "ocupado", f"Este trabalho já está em andamento: {ocupada}. "
                                          "Espere ele terminar para transcrever outra gravação.")
        envio = p.envio(app.pasta_envios(), LIMITE_ENVIO_GRAVACAO)
        arquivo = envio.arquivo("arquivo")
        dados = dict(envio.campos)
        if arquivo is None:
            envio.apagar()
            raise erro_400("Envie a gravação no campo “arquivo”.", "campo_ausente")
        # O motor vê só o temporário (envio-<hex>.wav, de hoje, fora da pasta
        # dos sigilosos): o nome e a data que vão para a ficha, e o sigilo pela
        # pasta de origem, saem daqui.
        origem, enviado = arquivo.caminho, arquivo.caminho
        nome = str(dados.get("nome_original") or arquivo.nome or arquivo.caminho.name).strip()
        nome = Path(nome.replace("\\", "/")).name or arquivo.caminho.name
        try:
            tamanho = arquivo.caminho.stat().st_size
        except OSError:
            tamanho = None
    else:
        dados = p.json()
        origem = None
        nome = ""
        caminho = str(dados.get("caminho") or "").strip().strip('"')
        if caminho:
            origem = Path(caminho)
            nome = origem.name
    try:
        revisao = str(dados.get("revisao", "")).strip().lower() in ("1", "true", "sim", "on") \
            if not isinstance(dados.get("revisao"), bool) else dados["revisao"]
        rotulos = None
        participantes = None
        meta = None
        tipo = str(dados.get("tipo") or "").strip()
        data = None
        if revisao:
            ultima = app.audiencia.ultima
            if not ultima:
                raise ErroApi(409, "sem_audiencia", "Não há audiência encerrada para revisar.")
            if origem is None:
                origem = Path(ultima["audio"]) if ultima.get("audio") else None
                nome = origem.name if origem is not None else ""
            if origem is None or not origem.exists():
                raise ErroApi(409, "sem_gravacao",
                              "A gravação da última audiência não está disponível para a "
                              "revisão.")
            numero = ultima["numero"]
            rotulos = ultima.get("falas")
            # A ficha da revisão é a da audiência (a MetaAudiencia da sessão
            # ao vivo: início, término, data, unidade, magistrado e os
            # participantes - nunca o mapa das teclas F1-F8), com o tipo
            # escolhido agora na tela, ou o da sessão.
            tipo = tipo or str(ultima.get("tipo") or "").strip()
            meta = ultima.get("meta")
            if meta is None:
                participantes = dict(ultima.get("participantes") or {}) or None
            # a revisão de audiência sigilosa continua fora do acervo
            extra = MOTIVO_ULTIMA if ultima.get("sigiloso") else ""
        else:
            if origem is None:
                raise erro_400("Escolha a gravação da audiência.", "campo_ausente")
            if enviado is None and not origem.is_file():
                raise ErroApi(404, "arquivo_inexistente", f"Não encontrei o arquivo {origem.name}.")
            # O caminho inteiro (o número pode estar na pasta: as mídias dos
            # autos ficam em _controle/midias/<número>/) ou, no envio, o nome
            # original - com o dependente "-NN" do nome ou da pasta.
            numero = numero_da_gravacao(origem if enviado is None else nome,
                                        str(dados.get("processo") or "").strip() or None)
            if enviado is None:
                extra = MOTIVO_PASTA if servicos.na_pasta_dos_sigilosos(cfg, origem) else ""
            else:
                extra = MOTIVO_PASTA if servicos.copia_na_pasta_dos_sigilosos(
                    cfg, nome, tamanho) else ""
                data = data_da_gravacao(dados.get("data_arquivo"), nome)
        sigiloso, forcado, motivo = sigilo_da_audiencia(app, numero, dados.get("sigiloso"), extra)
        if forcado:
            log.info("Gravação de %s transcrita como sigilosa: %s", numero.formatado, motivo)
    except BaseException:
        if enviado is not None:
            enviado.unlink(missing_ok=True)
        raise

    def alvo(tw):
        def progresso(fracao, texto=""):
            # "Lendo o áudio de envio-3f6e….mp4": na tela, o nome do usuário
            if enviado is not None and nome and texto:
                texto = texto.replace(enviado.name, nome)
            tw.definir_fracao(fracao, texto)

        try:
            tw.definir_fracao(0.0, f"{nome} → {numero.nome_arquivo}.docx")
            extra = {"meta": meta} if meta is not None else {}
            documento = servicos.transcrever_gravacao(
                origem, numero, cfg, progresso, tw.cancelado,
                rotulos_manuais=rotulos, tipo=tipo, participantes=participantes,
                sigiloso=sigiloso, gravacao=nome if enviado is not None else "", data=data,
                **extra)
        except Exception as erro:
            # O motor só conhece o temporário do envio: a frase ("'envio-3f6e….mp4'
            # é um vídeo sem trilha de áudio") diz o nome do arquivo do usuário.
            if enviado is not None and nome and enviado.name in str(erro):
                raise _com_outro_nome(erro, enviado.name, nome) from erro
            raise
        finally:
            if enviado is not None:
                try:
                    enviado.unlink(missing_ok=True)
                except OSError:
                    log.warning("não consegui apagar a gravação enviada %s", enviado.name)
        documento = Path(documento)
        fora = servicos.na_pasta_dos_sigilosos(cfg, documento)
        tw.definir_fracao(1.0, "Transcrição pronta.")
        from .api_compartilhar import depois_de_salvar

        depois_de_salvar(app, documento)
        return {"documento": str(documento), "processo": numero.formatado, "sigiloso": fora,
                "mensagem": documento.name + (" — na pasta dos sigilosos, fora do acervo "
                                              "compartilhado." if fora else "")}

    titulo = "Revisar a audiência" if revisao else "Transcrever a gravação"
    try:
        tw = app.tarefas.iniciar("transcricao_arquivo", titulo, alvo, (MODELO_REVISAO,),
                                 chave="transcricao_arquivo")
    except BaseException:
        if enviado is not None:
            enviado.unlink(missing_ok=True)
        raise
    resposta = {"tarefa": tw.id, "sigiloso": sigiloso, "sigiloso_forcado": forcado}
    if forcado:
        resposta["motivo"] = motivo
    return resposta


def recentes(p: Pedido) -> list[dict]:
    cfg = p.app.cfg
    saida = []
    for doc in servicos.transcricoes_recentes(cfg, 20, incluir_sigilosas=True):
        numero = servicos.numero_no_nome(doc)
        saida.append({"numero": numero.formatado if numero is not None else doc.stem,
                      "arquivo": str(doc), "quando": quando(doc),
                      "sigiloso": servicos.na_pasta_dos_sigilosos(cfg, doc)})
    return saida

