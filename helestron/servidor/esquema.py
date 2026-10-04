"""Os campos de Ajustes: rótulo, tipo, opções e validação de cada chave do config.ini.

GET /api/config devolve {valores, esquema}: a interface monta os grupos de
Ajustes a partir do esquema, sem conhecer o config.ini. POST /api/config
grava UMA chave, depois de validá-la aqui - um número fora da faixa, uma
opção que não existe ou uma pasta que poria os sigilosos ao alcance da IA
são recusados com a frase para o usuário, e o arquivo não muda.

Chave que o núcleo acrescentar ao config.ini e que não estiver descrita
aqui entra como texto, com o comentário do próprio ini como ajuda: nada
precisa ser sincronizado à mão para a chave aparecer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .. import servicos
from ..nucleo import config
from .rede import ErroApi, erro_400


@dataclass(frozen=True)
class Campo:
    secao: str
    chave: str
    tipo: str                  # texto | flag | inteiro | pasta | escolha
    rotulo: str
    ajuda: str = ""
    opcoes: tuple[tuple[str, str], ...] = ()      # (valor, rótulo)
    minimo: int | None = None
    maximo: int | None = None
    padrao: str = ""

    def como_dict(self) -> dict:
        d = {"secao": self.secao, "chave": self.chave, "tipo": self.tipo, "rotulo": self.rotulo,
             "ajuda": self.ajuda}
        if self.opcoes:
            d["opcoes"] = [{"valor": v, "rotulo": r} for v, r in self.opcoes]
        if self.minimo is not None:
            d["minimo"] = self.minimo
        if self.maximo is not None:
            d["maximo"] = self.maximo
        return d


NAVEGADORES = (("auto", "Automático (Chrome, senão Edge)"), ("chrome", "Google Chrome"),
               ("msedge", "Microsoft Edge"), ("chromium", "Chromium do programa"))
LOGIN_ESAJ = (("senha", "Usuário e senha"), ("certificado", "Certificado digital"),
              ("manual", "Entrar manualmente"))
LOGIN_EPROC = (("senha", "Usuário e senha"), ("manual", "Entrar manualmente"))
MODELOS_AO_VIVO = (("base", "Base — rápido, para computador modesto"),
                   ("small", "Small — recomendado"),
                   ("medium", "Medium — computador forte"))
MODELOS_REVISAO = (("small", "Small"), ("medium", "Medium — recomendado"),
                   ("large-v3-turbo", "Large v3 Turbo — o mais preciso"))

CAMPOS: tuple[Campo, ...] = (
    # ------------------------------------------------------------ pastas
    Campo("geral", "pasta_acervo", "pasta", "Pasta do acervo",
          "Processos e transcrições que o Helestron compartilha com a IA."),
    Campo("geral", "pasta_sigilosos", "pasta", "Pasta dos processos sigilosos",
          "Processos em segredo de justiça: fica fora do acervo e nunca vai para a IA."),
    Campo("pauta", "pasta", "pasta", "Pasta da pauta exportada",
          "Onde ficam as planilhas da pauta. Fora do acervo: elas trazem as partes dos "
          "processos sigilosos."),
    Campo("geral", "nome_usuario", "texto", "Como o Helestron chama você",
          "Aparece na saudação da tela Início."),
    # ----------------------------------------------------------- unidade
    Campo("unidade", "magistrado", "texto", "Magistrado(a)",
          "Aparece no cabeçalho das transcrições."),
    Campo("unidade", "cargo", "texto", "Cargo", "Ex.: Juiz de Direito."),
    Campo("unidade", "vara", "texto", "Vara", "Ex.: 2ª Vara Cível."),
    Campo("unidade", "comarca", "texto", "Comarca", "Ex.: Maceió."),
    Campo("unidade", "tribunal", "texto", "Tribunal",
          "Sigla do tribunal da unidade (ex.: TJAL)."),
    # ----------------------------------------------------------- download
    Campo("download", "pular_baixados", "flag", "Pular os processos que já estão na pasta"),
    Campo("download", "separar_sigilosos", "flag", "Separar os processos sigilosos",
          "Processo em segredo de justiça vai para a pasta dos sigilosos, fora do acervo "
          "(recomendado)."),
    Campo("download", "baixar_midias", "flag", "Baixar também as gravações de audiência"),
    Campo("download", "mostrar_navegador", "flag", "Mostrar o navegador enquanto baixa"),
    Campo("download", "navegador", "escolha", "Navegador dos portais", opcoes=NAVEGADORES),
    Campo("download", "pausa_entre_processos", "inteiro", "Pausa entre processos (segundos)",
          "Não zere em listas grandes: rajada de acessos pode ser lida pelo portal como abuso.",
          minimo=0, maximo=60),
    Campo("download", "tentativas", "inteiro", "Tentativas por processo", minimo=1, maximo=5),
    Campo("download", "espera_segundos", "inteiro", "Espera por página do portal (segundos)",
          minimo=10, maximo=600),
    Campo("download", "espera_login_minutos", "inteiro", "Esperar o login até (minutos)",
          "Tempo para concluir o login (código por e-mail, certificado).", minimo=1, maximo=60),
    Campo("download", "salvar_diagnostico", "flag", "Guardar imagem da tela quando algo der errado",
          "Fica na pasta Logs\\diagnostico, para o suporte."),
    # ------------------------------------------------------------ acesso
    Campo("esaj", "login", "escolha", "Como entrar no e-SAJ", opcoes=LOGIN_ESAJ),
    Campo("eproc", "login", "escolha", "Como entrar no eProc", opcoes=LOGIN_EPROC),
    Campo("eproc", "modo", "escolha", "Montagem do PDF no eProc",
          "Documentos: peça por peça, com marcadores. Completo: o “Download Completo” do "
          "tribunal.", opcoes=(("documentos", "Documentos (recomendado)"),
                               ("completo", "Download completo"))),
    Campo("eproc", "espera_completo_minutos", "inteiro", "Espera do download completo (minutos)",
          minimo=1, maximo=60),
    Campo("eproc", "perfil", "texto", "Perfil do eProc",
          "Perfil a escolher depois do login (ex.: MAGISTRADO). Em branco, o Helestron "
          "pergunta."),
    # -------------------------------------------------------- transcrição
    Campo("transcricao", "modelo_ao_vivo", "escolha", "Modelo da transcrição ao vivo",
          opcoes=MODELOS_AO_VIVO),
    Campo("transcricao", "modelo_revisao", "escolha", "Modelo da revisão e das gravações",
          opcoes=MODELOS_REVISAO),
    Campo("transcricao", "refinar_ao_encerrar", "flag", "Revisar ao encerrar a audiência",
          "Refaz a transcrição com o modelo de revisão (mais precisa; leva alguns minutos)."),
    Campo("transcricao", "separar_falantes", "flag", "Separar as vozes na revisão"),
    Campo("transcricao", "salvar_audio", "flag", "Guardar a gravação da audiência",
          "Arquivo FLAC ao lado da transcrição, na pasta _audio."),
    Campo("transcricao", "marcar_tempo", "flag", "Mostrar o horário de cada fala"),
    Campo("transcricao", "falantes", "texto", "Participantes padrão",
          "Separados por ponto e vírgula; viram os botões F1 a F8."),
    Campo("transcricao", "contexto", "texto", "Vocabulário da transcrição",
          "Texto que orienta o vocabulário e a pontuação. Mantenha acentuado."),
    Campo("transcricao", "threads", "inteiro", "Núcleos do processador",
          "0 = metade dos disponíveis.", minimo=0, maximo=64),
    # ------------------------------------------------------- compartilhar
    Campo("compartilhar", "pasta_nuvem", "pasta", "Pasta da nuvem",
          "OneDrive ou Google Drive para espelhar o acervo. Em branco, não espelha."),
    Campo("compartilhar", "espelhar_automaticamente", "flag",
          "Espelhar sozinho ao fim de cada download e de cada transcrição"),
    Campo("compartilhar", "incluir_texto", "flag", "Gerar a versão em texto dos autos",
          "A IA lê o texto muito melhor e mais barato que o PDF."),
    # -------------------------------------------------------------- pauta
    Campo("pauta", "monitorar", "flag", "Monitorar a pauta",
          "Sincroniza sozinho com o e-SAJ e o eProc e avisa as alterações.", padrao="false"),
    Campo("pauta", "intervalo_horas", "inteiro", "Intervalo do monitoramento (horas)",
          minimo=1, maximo=72, padrao="6"),
    Campo("pauta", "dias_atras", "inteiro", "Dias para trás na sincronização",
          minimo=0, maximo=90, padrao="7"),
    Campo("pauta", "dias_a_frente", "inteiro", "Dias à frente na sincronização",
          minimo=1, maximo=365, padrao="60"),
)

POR_CHAVE = {(c.secao, c.chave): c for c in CAMPOS}
# Gravadas pela própria interface (último processo, tipo de audiência...):
# aceitas no POST, mas não aparecem em Ajustes.
SECOES_INTERNAS = ("interface",)
PASTAS_DO_SIGILO = (("geral", "pasta_acervo"), ("geral", "pasta_sigilosos"), ("pauta", "pasta"))


def _padroes_ini() -> dict[tuple[str, str], str]:
    return {(s, c): p for s, c, p, _ in getattr(config, "ESQUEMA", [])}


def _comentarios_ini() -> dict[tuple[str, str], str]:
    return {(s, c): " ".join(x.strip() for x in comentario.split("\n"))
            for s, c, _, comentario in getattr(config, "ESQUEMA", [])}


def campos() -> list[Campo]:
    """Os campos de Ajustes: os descritos aqui e os que o ini tiver a mais."""
    saida = list(CAMPOS)
    comentarios = _comentarios_ini()
    for (secao, chave) in _padroes_ini():
        if (secao, chave) in POR_CHAVE or secao in SECOES_INTERNAS:
            continue
        saida.append(Campo(secao, chave, "texto", chave.replace("_", " ").capitalize(),
                           comentarios.get((secao, chave), "")))
    return saida


def campo(secao: str, chave: str) -> Campo | None:
    if (secao, chave) in POR_CHAVE:
        return POR_CHAVE[(secao, chave)]
    if (secao, chave) in _padroes_ini():
        return Campo(secao, chave, "texto", chave)
    return None


def _texto(cfg, c: Campo) -> str:
    valor = cfg.texto(c.secao, c.chave)
    if not valor and c.padrao and (c.secao, c.chave) not in _padroes_ini():
        return c.padrao
    return valor


def valor_atual(cfg, c: Campo):
    """O valor da chave no tipo do campo (pastas já resolvidas)."""
    if (c.secao, c.chave) == ("geral", "pasta_acervo"):
        return str(cfg.pasta_acervo)
    if (c.secao, c.chave) == ("geral", "pasta_sigilosos"):
        return str(cfg.pasta_sigilosos)
    if (c.secao, c.chave) == ("pauta", "pasta"):
        return str(servicos.pasta_pauta(cfg))
    texto = _texto(cfg, c)
    if c.tipo == "flag":
        return texto.strip().lower() in ("1", "true", "sim", "s", "yes", "on")
    if c.tipo == "inteiro":
        try:
            return int(float(texto.replace(",", ".")))
        except ValueError:
            try:
                return int(c.padrao or _padroes_ini().get((c.secao, c.chave), "0") or 0)
            except ValueError:
                return 0
    return texto


def valores(cfg) -> dict:
    saida: dict[str, dict] = {}
    for c in campos():
        saida.setdefault(c.secao, {})[c.chave] = valor_atual(cfg, c)
    for (secao, chave) in _padroes_ini():
        if secao in SECOES_INTERNAS:
            saida.setdefault(secao, {})[chave] = cfg.texto(secao, chave)
    return saida


def normalizar(c: Campo, valor) -> str:
    """O valor a gravar no ini, ou ErroApi 400 com a frase."""
    if c.tipo == "flag":
        if isinstance(valor, str):
            v = valor.strip().lower()
            if v not in ("1", "0", "true", "false", "sim", "não", "nao", "s", "n", "on", "off",
                         "yes", "no"):
                raise erro_400(f"“{c.rotulo}” é ligado ou desligado.", "valor_invalido")
            return "true" if v in ("1", "true", "sim", "s", "on", "yes") else "false"
        return "true" if bool(valor) else "false"
    if c.tipo == "inteiro":
        try:
            numero = int(float(str(valor).replace(",", ".").strip()))
        except (TypeError, ValueError) as erro:
            raise erro_400(f"“{c.rotulo}” deve ser um número inteiro.", "valor_invalido") from erro
        if (c.minimo is not None and numero < c.minimo) or \
                (c.maximo is not None and numero > c.maximo):
            raise erro_400(f"“{c.rotulo}” deve ficar entre {c.minimo} e {c.maximo}.",
                           "valor_invalido")
        return str(numero)
    texto = "" if valor is None else str(valor)
    texto = texto.replace("\r", " ").replace("\n", " ").strip()
    if c.tipo == "escolha":
        validos = [v for v, _ in c.opcoes]
        if validos and texto not in validos:
            raise erro_400(f"Opção inválida para “{c.rotulo}”.", "valor_invalido")
        return texto
    if c.tipo == "pasta":
        texto = texto.strip('"')
        if texto and not Path(os.path.expandvars(texto)).expanduser().is_absolute():
            raise erro_400(f"Escolha uma pasta completa para “{c.rotulo}” (ex.: "
                           "C:\\Users\\voce\\Documents\\Helestron).", "valor_invalido")
        if len(texto) > 400:
            raise erro_400("O caminho da pasta é longo demais.", "valor_invalido")
        return texto
    if len(texto) > 4000:
        raise erro_400(f"O texto de “{c.rotulo}” é longo demais.", "valor_invalido")
    return texto


def conferir_pastas(cfg, secao: str, chave: str, valor: str) -> None:
    """Recusa a pasta que poria os sigilosos (ou a pauta) ao alcance da IA."""
    if (secao, chave) not in PASTAS_DO_SIGILO:
        return
    acervo, sigilosos, pauta = cfg.pasta_acervo, cfg.pasta_sigilosos, servicos.pasta_pauta(cfg)
    novo = Path(os.path.expandvars(valor)).expanduser() if valor else None
    if (secao, chave) == ("geral", "pasta_acervo") and novo is not None:
        acervo = novo
    elif (secao, chave) == ("geral", "pasta_sigilosos") and novo is not None:
        sigilosos = novo
    elif (secao, chave) == ("pauta", "pasta"):
        pauta = novo if novo is not None else servicos.base_usuario() / "Pauta"
    frase = servicos.problema_nas_pastas(acervo, sigilosos, pauta)
    if frase:
        raise ErroApi(400, "pastas_em_conflito", frase)


def gravar(cfg, secao: str, chave: str, valor):
    """Valida e grava; devolve o valor como GET /api/config o mostraria."""
    secao, chave = str(secao or "").strip(), str(chave or "").strip()
    if secao in SECOES_INTERNAS and (secao, chave) in _padroes_ini():
        c = Campo(secao, chave, "texto", chave)
    else:
        c = campo(secao, chave)
    if c is None:
        raise ErroApi(404, "chave_inexistente", "Esta configuração não existe.",
                      f"[{secao}] {chave}")
    texto = normalizar(c, valor)
    conferir_pastas(cfg, secao, chave, texto)
    cfg.definir(secao, chave, texto)
    return valor_atual(cfg, c) if secao not in SECOES_INTERNAS else cfg.texto(secao, chave)
