"""A fachada da pauta para a API (seção 8.10 da especificação).

O servidor (helestron/servidor/api_pauta.py) só conhece esta classe; a
linha de comando (pauta/cli.py) e o monitor do aplicativo também. Ela junta
o banco (armazem), o reconhecimento (tabelas), a leitura no portal
(navegacao, captura), a importação e a exportação.

O que vale para todas as entradas:

* sincronizar e capturar usam o login, o perfil do navegador e as
  perguntas do DOWNLOAD (helestron.download.motor: as mesmas fábricas de
  navegador e de portal, o mesmo cofre de senhas - mais a senha digitada
  com "Lembrar neste computador" desligado, que vale até fechar o
  Helestron: 'credenciais_sessao', o mesmo dicionário do download). Sem
  senha no modo "senha", o navegador abre na tela de entrada para o
  usuário entrar - como no download. No monitoramento (ninguém olhando)
  isso não acontece: só a senha GUARDADA vale, e sem ela a fonte fica
  pendente, com o aviso "Entre no portal para continuar o monitoramento",
  em vez de abrir uma janela do nada. Por isso a fonte com certificado,
  entrada manual ou senha não guardada não é "monitorada" (fontes(),
  exige_presenca(), motivo_presenca()): o monitor a deixa de fora;
* uma fonte que falha não derruba as outras (cada uma que falhou vira um
  aviso); só quando todas falham a tarefa termina como "falhou", com o
  motivo de cada uma no erro (sem o aviso por fonte, que só o repetiria);
* SIGILO é do PROCESSO, não da linha: a audiência é sigilosa se o portal
  (ou o relatório) disse segredo de justiça em QUALQUER audiência daquele
  processo, ou se os autos do processo estão na pasta de sigilosos - a
  mesma regra do compartilhamento e da transcrição. Vale para a lista, o
  histórico e a planilha, que mascara as partes por padrão (inclusive nas
  alterações e no texto da busca) e nunca é gravada dentro do acervo;
* o sigilo que a pauta REVELA (processo que o programa ainda não tratava como
  sigiloso, nem pela pauta nem pela pasta dos sigilosos) vale na hora: a
  sincronização, a captura e a importação o informam em 'sigilosos_novos' e a
  quem pediu (quando_revelar_sigilo: o servidor tira do acervo o que houver
  dele e avisa o usuário; a linha de comando faz o mesmo por conta própria).
"""

from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from ..nucleo import caminhos, cnj
from . import exportacao, importacao, modelos
from . import regras as regras_mod
from .armazem import Armazem
from .modelos import JA_PASSOU, SEM_AUDIENCIA, como_dict, normalizar_texto
from .monitor import (INTERVALO_MAX_H, INTERVALO_MIN_H, Agenda, ConfigMonitoramento,
                      ler_flag)
from .tabelas import Reconhecedor

log = logging.getLogger("pauta.servico")

DICA_INSTALAR = ("Instale o Helestron de novo com o Helestron-Setup: ele conserta a instalação "
                 "sem apagar os seus dados.")
MENSAGEM_LOGIN = ("Entre no portal para continuar o monitoramento: sem a senha guardada (ou no "
                  "login por certificado), o {nome} só pode ser aberto com você à frente. Na tela "
                  "Pauta, clique em Sincronizar.")
# Por que o login de uma fonte só acontece com a pessoa à frente (o
# monitoramento automático a deixa de fora; a tela mostra o motivo).
PRESENCA_CERTIFICADO = "a entrada no portal é pelo certificado digital"
PRESENCA_MANUAL = "a entrada no portal é manual"
PRESENCA_SEM_SENHA = "o usuário e a senha do portal não estão guardados neste computador"
CACHE_SIGILOSOS_S = 15.0
DIAS_DA_SEMANA = 7            # "nos próximos 7 dias": hoje e os 6 seguintes


class ErroPauta(RuntimeError):
    """Falha da pauta com a frase pronta para o usuário."""


def _agora() -> datetime:
    return datetime.now().replace(microsecond=0)


def _iso(momento: datetime | None) -> str | None:
    return momento.replace(microsecond=0).isoformat() if momento else None


def _frase(erro: BaseException) -> str:
    texto = str(erro).strip() or type(erro).__name__
    return texto[:1].upper() + texto[1:]


# ====================================================== sigilo revelado
MAX_NUMEROS_NO_AVISO = 3


def no_acervo(cfg, numeros) -> list[str]:
    """Dos processos 'numeros' (como a pauta os mostra), os que têm alguma coisa
    no acervo compartilhado com a IA: autos ou transcrição fora da pasta dos
    sigilosos, ou o texto dos autos em _ia/texto. Nunca levanta: na dúvida
    (acervo ilegível), todos contam."""
    nomes: dict[str, str] = {}
    for numero in numeros or []:
        try:
            nomes[cnj.ler(str(numero)).nome_arquivo] = str(numero)
        except cnj.NumeroInvalido:
            continue
    if not nomes:
        return []
    try:
        from ..compartilhar.mcp_servidor import Acervo

        acervo = Acervo(Path(cfg.pasta_acervo), sigilosos=cfg.pasta_sigilosos)
        achados = {chave for chave in nomes if (acervo.cache / f"{chave}.txt").is_file()}
        for sufixo in (".pdf", ".docx"):
            achados |= {chave for chave, _p in acervo.numerados(sufixo) if chave in nomes}
    except Exception as erro:
        log.warning("não consegui conferir o acervo dos processos sigilosos: %s", erro)
        return list(nomes.values())
    return [numero for chave, numero in nomes.items() if chave in achados]


def quem_corre(numeros: list[str]) -> str:
    """"o processo X corre", "os processos X e Y correm", "5 processos (X, Y, Z
    e mais 2) correm" - o começo do aviso do sigilo revelado."""
    if len(numeros) == 1:
        return f"o processo {numeros[0]} corre"
    if len(numeros) <= MAX_NUMEROS_NO_AVISO:
        return f"os processos {', '.join(numeros[:-1])} e {numeros[-1]} correm"
    mostrar = ", ".join(numeros[:MAX_NUMEROS_NO_AVISO])
    return (f"{len(numeros)} processos ({mostrar} e mais "
            f"{len(numeros) - MAX_NUMEROS_NO_AVISO}) correm")


def frase_sigilo_revelado(cfg, numeros: list[str], preso_no_acervo: bool = False) -> str:
    """O aviso ao usuário quando a pauta revela que processos com arquivos no
    acervo correm em segredo de justiça, e o programa os está tirando dali (o
    preparo rápido do acervo, que o servidor acabou de pedir)."""
    um = len(numeros) == 1
    dele, ele = ("dele", "ele") if um else ("deles", "eles")
    sai = "sai" if um else "saem"
    frase = f"A pauta indica que {quem_corre(numeros)} em segredo de justiça. "
    if preso_no_acervo:
        # o preparo espera: há arquivo de processo sigiloso que não pôde sair do acervo
        return frase + (f"{ele.capitalize()} {sai} do acervo e da IA quando o Helestron puder "
                        "preparar o acervo de novo: antes, feche o arquivo de processo "
                        "sigiloso que ficou preso no acervo (veja em Compartilhar).")
    try:
        separar = bool(cfg.flag("download", "separar_sigilosos"))
    except Exception:
        separar = True
    if separar:
        frase += (f"O Helestron está levando os autos e as transcrições {dele} para a pasta dos "
                  f"sigilosos, e {ele} {sai} do índice e do texto lidos pela IA")
    else:
        frase += (f"Com a separação dos sigilosos desligada, os arquivos {dele} continuam no "
                  f"acervo, mas {ele} {sai} do índice e do texto lidos pela IA")
    nuvem, automatico = "", False
    try:
        nuvem = str(cfg.texto("compartilhar", "pasta_nuvem") or "").strip()
        automatico = bool(cfg.flag("compartilhar", "espelhar_automaticamente"))
        if nuvem:
            from .. import servicos

            if servicos.conflito_da_nuvem(nuvem, cfg.pasta_acervo):
                nuvem = ""
    except Exception:
        nuvem = ""
    if nuvem and automatico:
        frase += " e do espelho na nuvem."
    elif nuvem:
        frase += (f". A cópia {dele} na nuvem sai no próximo espelho (Compartilhar › Espelhar "
                  "agora).")
    else:
        frase += "."
    return frase


class ServicoPauta:
    """A pauta de audiências: consulta, sincronização, captura, importação, exportação."""

    def __init__(self, cfg, arquivo_banco: Path | None = None,
                 eventos: Callable[[str, dict], None] | None = None, *,
                 regras=None, fabrica_navegador=None, fabrica_portal=None, cofre=None,
                 relogio: Callable[[], datetime] | None = None):
        self.cfg = cfg
        padrao = getattr(caminhos, "ARQUIVO_PAUTA", None) or Path(caminhos.LOCAL) / "pauta.sqlite3"
        self.arquivo_banco = Path(arquivo_banco or padrao)
        self.eventos = eventos
        self.armazem = Armazem(self.arquivo_banco)
        # Injetáveis (testes, ou outro portal): o padrão é o do download.
        self._regras = regras
        self.fabrica_navegador = fabrica_navegador
        self.fabrica_portal = fabrica_portal
        self.cofre = cofre
        self.relogio = relogio or _agora
        self.espera_pagina_s = 20.0
        self.limite_captura_s: float | None = None
        self._sigilosos: tuple[float, str, set[str]] = (0.0, "", set())
        # A senha digitada sem "Lembrar neste computador" ({portal: (usuário, senha)}):
        # o servidor entrega o dicionário da sessão (o mesmo do download).
        self.credenciais_sessao: dict[str, tuple[str, str]] | None = None
        # Quem quer saber do sigilo que a pauta revela (quando_revelar_sigilo) e o
        # que se revelou antes de alguém pedir.
        self._ao_revelar_sigilo: Callable[[list[str]], None] | None = None
        self._revelados_pendentes: list[str] = []
        self._trava_revelados = threading.Lock()

    # ================================================================ apoio
    @property
    def regras(self):
        return self._regras or regras_mod.carregar()

    def fechar(self) -> None:
        self.armazem.fechar()

    def _evento(self, tipo: str, dados: dict) -> None:
        if self.eventos is None:
            return
        try:
            self.eventos(tipo, dados)
        except Exception as erro:          # o evento é aviso; nunca derruba o trabalho
            log.debug("evento %s não publicado: %s", tipo, erro)

    def _hoje(self) -> date:
        return self.relogio().date()

    def _numeros_sigilosos(self) -> set[str]:
        """As chaves CNJ dos processos sigilosos: os da pasta de sigilosos e os
        que têm ALGUMA audiência marcada sigilosa no banco (em qualquer
        registro). Ver _sigilosos_do_banco."""
        return self._na_pasta_de_sigilosos() | self._sigilosos_do_banco()[0]

    def _sigilosos_do_banco(self) -> tuple[set[str], set[str]]:
        try:
            return self.armazem.sigilosas()
        except Exception as erro:          # banco ocupado: a pasta ainda vale
            log.warning("não consegui ler o sigilo da pauta no banco: %s", erro)
            return set(), set()

    def processo_sigiloso(self, numero) -> bool:
        """True se alguma audiência deste processo, em qualquer registro (do
        portal, do relatório, já fora da pauta), está marcada sigilosa.

        É o que a transcrição consulta: o processo que a pauta diz estar em
        segredo de justiça é transcrito como sigiloso.
        """
        chave = modelos.chave_processo(str(getattr(numero, "formatado", numero) or ""))
        return bool(chave) and chave in self._sigilosos_do_banco()[0]

    # ======================================================= sigilo revelado
    @property
    def ao_revelar_sigilo(self) -> Callable[[list[str]], None] | None:
        return self._ao_revelar_sigilo

    def quando_revelar_sigilo(self, funcao: Callable[[list[str]], None] | None) -> None:
        """'funcao(numeros)' é chamada quando a sincronização, a captura ou a
        importação revela processo em segredo de justiça que o programa ainda
        não tratava como sigiloso (nem pela pauta, nem pela pasta dos
        sigilosos). É o servidor: ele tira do acervo, na hora, o que houver do
        processo e avisa o usuário - sem esperar o próximo compartilhamento,
        download ou transcrição. O que se revelou antes (o monitor rodou antes
        de a janela abrir a Pauta) é entregue agora."""
        with self._trava_revelados:
            self._ao_revelar_sigilo = funcao
            pendentes, self._revelados_pendentes = self._revelados_pendentes, []
        if funcao is not None and pendentes:
            self._entregar_revelados(pendentes)

    def _sigilosos_conhecidos(self) -> set[str] | None:
        """Antes de gravar: as chaves dos processos que o programa já trata como
        sigilosos (a pauta e a pasta dos sigilosos). None: o banco não pôde ser
        lido - aí nada conta como revelado agora (o preparo seguinte, antes de
        qualquer compartilhamento, aplica a regra do mesmo jeito)."""
        try:
            conhecidos = set(self.armazem.processos_sigilosos())
        except Exception as erro:
            log.warning("não consegui ler na pauta os processos sigilosos: %s", erro)
            return None
        return conhecidos | self._na_pasta_de_sigilosos()

    def _revelados(self, conhecidos: set[str] | None, resultado: dict) -> list[str]:
        """Os processos que a gravação revelou sigilosos (números como a pauta os
        mostra): vão para resultado['sigilosos_novos'] e para quem pediu."""
        if conhecidos is None:
            return []
        try:
            depois = self.armazem.processos_sigilosos()
        except Exception as erro:
            log.warning("não consegui conferir na pauta os processos sigilosos: %s", erro)
            return []
        novos = sorted(numero for chave, numero in depois.items() if chave not in conhecidos)
        if not novos:
            return []
        resultado["sigilosos_novos"] = novos
        log.warning("A pauta indica segredo de justiça em %d processo%s que o programa ainda "
                    "não tratava como sigiloso%s.", len(novos), "s" if len(novos) != 1 else "",
                    "s" if len(novos) != 1 else "")
        self._entregar_revelados(novos)
        return novos

    def _entregar_revelados(self, numeros: list[str]) -> None:
        with self._trava_revelados:
            funcao = self._ao_revelar_sigilo
            if funcao is None:
                self._revelados_pendentes += [n for n in numeros
                                              if n not in self._revelados_pendentes]
                return
        try:
            funcao(list(numeros))
        except Exception as erro:          # o aviso nunca derruba a sincronização
            log.warning("não consegui aplicar na hora o sigilo revelado pela pauta: %s", erro)

    def _na_pasta_de_sigilosos(self) -> set[str]:
        """As chaves CNJ dos processos com autos (ou transcrição) na pasta de sigilosos.

        A regra do motor (transcricao.documento.processo_sigiloso): um PDF com
        o número em <sigilosos>/ ou <sigilosos>/<lote>/. Lida uma vez a cada
        poucos segundos, e não uma vez por audiência.
        """
        try:
            pasta = Path(self.cfg.pasta_sigilosos)
        except Exception:
            return set()
        quando, onde, numeros = self._sigilosos
        if onde == str(pasta) and _time.monotonic() - quando < CACHE_SIGILOSOS_S:
            return numeros
        numeros = set()
        try:
            arquivos = [*pasta.glob("*.pdf"), *pasta.glob("*/*.pdf"), *pasta.glob("*/*.docx")]
        except OSError:
            arquivos = []
        for p in arquivos:
            try:
                numeros.add(cnj.chave(cnj.ler_nome_arquivo(p.stem)))
            except cnj.NumeroInvalido:
                continue
        self._sigilosos = (_time.monotonic(), str(pasta), numeros)
        return numeros

    def _dicts(self, audiencias) -> list[dict]:
        sigilosos = self._numeros_sigilosos()
        saida = []
        for a in audiencias:
            d = como_dict(a)
            if not d["sigiloso"] and a.processo and modelos.chave_processo(a.processo) in sigilosos:
                d["sigiloso"] = True
            saida.append(d)
        return saida

    def _marcar_sigilo(self, alteracoes: list[dict]) -> list[dict]:
        """O retrato guardado em cada alteração é do momento da mudança: o
        processo que ficou sigiloso depois (ou que é sigiloso por outro
        registro, ou pela pasta) é sigiloso também no histórico."""
        chaves = self._na_pasta_de_sigilosos()
        do_banco, ids = self._sigilosos_do_banco()
        chaves = chaves | do_banco
        for alt in alteracoes:
            a = alt.get("audiencia")
            if not isinstance(a, dict):
                a = alt["audiencia"] = {}
            if a.get("sigiloso"):
                continue
            if (a.get("id") and a["id"] in ids) or (
                    a.get("processo") and modelos.chave_processo(a["processo"]) in chaves):
                a["sigiloso"] = True
        return alteracoes

    # ============================================================= consulta
    def listar(self, de: date, ate: date, sistema="", situacao="", busca="") -> dict:
        """{audiencias: [dict], resumo: {total, hoje, semana, por_situacao, por_tipo}}."""
        audiencias = self.armazem.listar(de, ate)
        sistema = (sistema or "").strip().lower().replace("-", "")
        if sistema in ("todos", "*"):
            sistema = ""
        if sistema:
            audiencias = [a for a in audiencias if a.sistema == sistema]
        situacao = (situacao or "").strip()
        if situacao:
            alvo = modelos.situacao_reconhecida(situacao, self.regras) or situacao
            audiencias = [a for a in audiencias
                          if normalizar_texto(a.situacao) == normalizar_texto(alvo)]
        busca = normalizar_texto(busca)
        if busca:
            digitos = "".join(ch for ch in busca if ch.isdigit())
            so_numero = bool(digitos) and len(digitos) >= 4 and not any(
                ch.isalpha() for ch in busca)

            def casa(a) -> bool:
                if so_numero and digitos in "".join(ch for ch in a.processo if ch.isdigit()):
                    return True
                texto = normalizar_texto(" ".join((a.processo, a.partes, a.classe, a.tipo,
                                                   a.tipo_original, a.local, a.magistrado,
                                                   a.observacoes, a.tribunal, a.situacao)))
                return all(p in texto for p in busca.split())

            audiencias = [a for a in audiencias if casa(a)]
        dicts = self._dicts(audiencias)
        return {"audiencias": dicts, "resumo": self.resumo(dicts)}

    def resumo(self, audiencias: list[dict]) -> dict:
        """'semana' = "nos próximos 7 dias": de hoje a hoje + 6, os mesmos dias
        da visão Semana da tela (que o chip abre)."""
        hoje = self._hoje()
        semana = hoje + timedelta(days=DIAS_DA_SEMANA - 1)
        acontecem = [a for a in audiencias if a.get("situacao") not in SEM_AUDIENCIA]
        por_situacao: dict[str, int] = {}
        por_tipo: dict[str, int] = {}
        for a in audiencias:
            por_situacao[a.get("situacao") or ""] = por_situacao.get(a.get("situacao") or "", 0) + 1
            por_tipo[a.get("tipo") or ""] = por_tipo.get(a.get("tipo") or "", 0) + 1
        return {"total": len(audiencias),
                "hoje": sum(1 for a in acontecem if a.get("data") == hoje.isoformat()),
                "semana": sum(1 for a in acontecem
                              if hoje.isoformat() <= str(a.get("data")) <= semana.isoformat()),
                "por_situacao": por_situacao, "por_tipo": por_tipo}

    def fontes(self) -> list[dict]:
        """As fontes cadastradas, com o que o monitoramento faz com cada uma:
        'monitorada' (tem a rota da pauta e entra no portal sozinha),
        'exige_presenca' e 'motivo_presenca' (o login só acontece com a
        pessoa à frente: certificado, entrada manual ou senha não guardada)."""
        lista = self.armazem.fontes()
        for fonte in lista:
            motivo = self.motivo_presenca(fonte)
            fonte["exige_presenca"] = bool(motivo)
            fonte["motivo_presenca"] = motivo
            fonte["monitorada"] = bool(fonte.get("url")) and not motivo
        return lista

    def motivo_presenca(self, fonte) -> str:
        """Por que o login desta fonte exige a pessoa à frente ("" se entra
        sozinha). É a regra de _acesso no segundo plano, onde só vale a senha
        GUARDADA no computador (a digitada "só por agora" não serve ao
        monitor). 'fonte': o dicionário da fonte ou o id dela. Na dúvida
        (tribunal desconhecido, componente ausente), "": a sincronização decide."""
        if not isinstance(fonte, dict):
            fonte = self.armazem.fonte(str(fonte)) or {}
        try:
            tribunal = self._tribunal(str(fonte.get("tribunal") or ""),
                                      str(fonte.get("sistema") or ""))
            opcoes = self._opcoes(tribunal)
            modo = opcoes.modo_login(tribunal.sistema)
            if modo == "certificado":
                return PRESENCA_CERTIFICADO
            if modo == "manual":
                return PRESENCA_MANUAL
            if self._credenciais(tribunal, opcoes, sessao=False) is None:
                return PRESENCA_SEM_SENHA
        except Exception as erro:
            log.debug("não sei se a fonte %s entra sozinha: %s", fonte.get("id"), erro)
        return ""

    def exige_presenca(self, fonte) -> bool:
        """O login desta fonte só acontece com a pessoa à frente? (O monitor
        a deixa fora da sincronização automática.)"""
        return bool(self.motivo_presenca(fonte))

    def salvar_fonte(self, tribunal, sistema, rotulo, url="") -> dict:
        sistema = (sistema or "").strip().lower()
        if sistema not in ("esaj", "eproc"):
            raise ValueError("Escolha o sistema da fonte: e-SAJ ou eProc.")
        if not (tribunal or "").strip():
            raise ValueError("Informe o tribunal da fonte (ex.: TJAL).")
        if url and not str(url).lower().startswith(("https://", "http://")):
            raise ValueError("O endereço da pauta deve começar por https://.")
        rotulo = (rotulo or "").strip() or \
            f"{str(tribunal).strip().upper()} · {modelos.NOMES_SISTEMA.get(sistema, sistema)}"
        return self.armazem.salvar_fonte(tribunal, sistema, rotulo, (url or "").strip())

    def remover_fonte(self, id_fonte) -> None:
        self.armazem.remover_fonte(str(id_fonte))

    def alteracoes(self, desde: datetime | None = None) -> list[dict]:
        return self._marcar_sigilo(self.armazem.alteracoes(desde))

    def marcar_vistas(self) -> None:
        self.armazem.marcar_vistas()

    def ultima_sincronizacao(self) -> datetime | None:
        texto = self.armazem.meta("ultima_sincronizacao")
        try:
            return datetime.fromisoformat(texto) if texto else None
        except ValueError:
            return None

    # ------------------------------------------------------- monitoramento
    def config_monitoramento(self) -> ConfigMonitoramento:
        return ConfigMonitoramento.de_config(self.cfg)

    def monitoramento(self) -> dict:
        conf = self.config_monitoramento()
        # só as que o monitor sincroniza de fato: com a rota e sem exigir a pessoa
        monitoradas = [f for f in self.fontes() if f.get("monitorada")]
        proxima = Agenda(self.relogio).proxima(conf, self.ultima_sincronizacao(),
                                               bool(monitoradas))
        return {"ativo": conf.ativo, "intervalo_horas": conf.intervalo_horas,
                "dias_atras": conf.dias_atras, "dias_a_frente": conf.dias_a_frente,
                "proxima": _iso(proxima), "fontes_monitoradas": len(monitoradas)}

    def configurar_monitoramento(self, ativo: bool, intervalo_horas: int) -> dict:
        try:
            horas = int(intervalo_horas)
        except (TypeError, ValueError) as erro:
            raise ValueError("O intervalo do monitoramento deve ser um número de horas.") from erro
        if not INTERVALO_MIN_H <= horas <= INTERVALO_MAX_H:
            raise ValueError(f"O intervalo deve ficar entre {INTERVALO_MIN_H} e "
                             f"{INTERVALO_MAX_H} horas.")
        self.cfg.definir("pauta", "monitorar", bool(ativo))
        self.cfg.definir("pauta", "intervalo_horas", horas)
        return self.monitoramento()

    def configurada(self) -> bool:
        """A pauta já foi posta para funcionar: há fonte cadastrada, ou já houve
        sincronização, captura ou importação (o passo "Pauta" dos Primeiros
        passos só se dá por feito assim - ter aberto a tela não basta)."""
        try:
            return bool(self.armazem.fontes() or self.ultima_sincronizacao()
                        or self.armazem.meta("ultima_importacao")
                        or self.armazem.contar(incluir_removidas=True))
        except Exception as erro:
            log.debug("configurada: %s", erro)
            return False

    def resumo_inicio(self) -> dict:
        """{hoje, semana, proxima, ultima_sincronizacao, alteracoes_nao_vistas, fontes,
        configurada} - a tela Início ('fontes': quantas cadastradas)."""
        agora = self.relogio()
        hoje = agora.date()
        lista = self._dicts(self.armazem.listar(hoje, hoje + timedelta(days=DIAS_DA_SEMANA - 1)))
        resumo = self.resumo(lista)
        agora_hm = f"{agora:%H:%M}"
        proxima = None
        for a in self._dicts(self.armazem.futuras(hoje, 200)):
            if a.get("situacao") in SEM_AUDIENCIA + JA_PASSOU:
                continue
            if a.get("data") == hoje.isoformat() and a.get("hora") and a["hora"] < agora_hm:
                continue
            proxima = a
            break
        return {"hoje": resumo["hoje"], "semana": resumo["semana"], "proxima": proxima,
                "ultima_sincronizacao": _iso(self.ultima_sincronizacao()),
                "alteracoes_nao_vistas": self.armazem.nao_vistas(),
                "fontes": len(self.armazem.fontes()), "configurada": self.configurada()}

    # ============================================================ o portal
    def _tribunal(self, sigla: str, sistema: str):
        from ..nucleo import tribunais

        t = tribunais.por_sigla(sigla)
        if t is None:
            raise ErroPauta(f"Tribunal desconhecido: {sigla}. Confira a fonte da pauta.")
        for candidato in (t, t.alternativo):
            if candidato is not None and candidato.sistema == sistema:
                return candidato
        raise ErroPauta(f"O {t.sigla} não usa o {modelos.NOMES_SISTEMA.get(sistema, sistema)}.")

    def _motor(self):
        try:
            from ..download import motor
        except ImportError as erro:
            raise ErroPauta(f"O componente de acesso aos portais não está instalado "
                            f"({getattr(erro, 'name', '') or erro}). {DICA_INSTALAR}") from erro
        return motor

    def _opcoes(self, tribunal, visivel: bool = False):
        from ..download.modelos import OpcoesDownload

        opcoes = OpcoesDownload.de_config(self.cfg)
        opcoes = replace(opcoes, atualizar_ia=False)
        if visivel:
            opcoes = replace(opcoes, mostrar_navegador=True)
        return opcoes

    def _credenciais(self, tribunal, opcoes, sessao: bool = True) -> tuple[str, str] | None:
        """Usuário e senha do portal: os digitados nesta sessão sem "Lembrar"
        (se 'sessao'), senão os guardados no cofre - a regra do download
        (servicos.CofreMisto)."""
        if opcoes.modo_login(tribunal.sistema) != "senha":
            return None
        if sessao:
            try:
                usuario, senha = (self.credenciais_sessao or {}).get(tribunal.portal) or ("", "")
            except (TypeError, ValueError):
                usuario, senha = "", ""
            if usuario and senha:
                return usuario, senha
        cofre = self.cofre
        if cofre is None:
            try:
                from ..nucleo.cofre_senhas import CofreSenhas

                cofre = CofreSenhas(caminhos.ARQUIVO_SENHAS)
            except Exception as erro:
                log.warning("o cofre de senhas não abriu: %s", erro)
                return None
        try:
            usuario, senha = cofre.obter(tribunal.portal)
        except Exception as erro:
            log.warning("não consegui ler a senha guardada de %s: %s", tribunal.portal, erro)
            return None
        return (usuario, senha) if usuario and senha else None

    @staticmethod
    def _em_segundo_plano(ctx) -> bool:
        """O Contexto de fundo do monitor (servidor.trabalhos.ContextoFundo)."""
        return getattr(ctx, "pediu_login", None) is not None

    def _acesso(self, tribunal, ctx, visivel: bool = False):
        """(opções, credenciais) - a regra do motor (_opcoes_do_grupo) para o login.

        No monitoramento (segundo plano) só vale a senha GUARDADA no
        computador; com alguém à frente, também a digitada nesta sessão.
        """
        opcoes = self._opcoes(tribunal, visivel)
        fundo = self._em_segundo_plano(ctx)
        credenciais = self._credenciais(tribunal, opcoes, sessao=not fundo)
        sistema = tribunal.sistema
        precisa_de_alguem = (opcoes.modo_login(sistema) in ("manual", "certificado")
                             or credenciais is None)
        if precisa_de_alguem and fundo:
            try:
                ctx.pediu_login = True
                # o motivo: o login exige a pessoa (e não "o portal pediu o
                # código", que o Contexto do monitor marca como "codigo")
                if getattr(ctx, "motivo", None) != "codigo":
                    ctx.motivo = "presenca"
            except Exception:
                pass
            raise ErroPauta(MENSAGEM_LOGIN.format(
                nome=f"{tribunal.nome_sistema} do {tribunal.sigla}"))
        if opcoes.modo_login(sistema) == "senha" and credenciais is None:
            log.info("Sem usuário e senha guardados para o %s do %s: o navegador abre na tela "
                     "de entrada para você entrar.", tribunal.nome_sistema, tribunal.sigla)
            opcoes = replace(opcoes, login={**opcoes.login, sistema: "manual"})
        return opcoes, credenciais

    def _navegador(self, tribunal, opcoes):
        fabrica = self.fabrica_navegador or self._motor().fabrica_navegador_padrao
        return fabrica(tribunal, opcoes)

    def _portal(self, nav, tribunal, opcoes, ctx, credenciais):
        fabrica = self.fabrica_portal or self._motor().fabrica_portal_padrao
        return fabrica(nav, tribunal, opcoes, ctx, credenciais)

    def _reconhecedor(self, tribunal_sigla: str, sistema: str, fonte: str) -> Reconhecedor:
        return Reconhecedor(self.regras, sistema, tribunal_sigla, fonte=fonte, estrito=True,
                            agora=self.relogio())

    # ========================================================= sincronizar
    def sincronizar(self, ctx, fontes: list[str] | None, de: date, ate: date) -> dict:
        """Lê a pauta de cada fonte no portal e grava. ctx = Contexto da tarefa."""
        from ..download.modelos import Cancelado

        todas = self.armazem.fontes()
        if fontes:
            pedidas = {str(x) for x in fontes}
            escolhidas = [f for f in todas if f["id"] in pedidas]
            if not escolhidas:
                raise ErroPauta("As fontes pedidas não existem mais. Confira as fontes da pauta "
                                "em Ajustes.")
        else:
            escolhidas = todas
        if not escolhidas:
            raise ErroPauta("Nenhuma fonte da pauta configurada. Escolha o tribunal e o sistema "
                            "(e-SAJ ou eProc) primeiro.")
        resultado = {"novas": 0, "atualizadas": 0, "canceladas": 0, "removidas": 0, "total": 0,
                     "alteracoes": 0, "fontes": [], "erros": [], "avisos": [],
                     "periodo": {"de": de.isoformat(), "ate": ate.isoformat()}}
        conhecidos = self._sigilosos_conhecidos()
        sucesso = False
        for i, fonte in enumerate(escolhidas):
            if ctx.cancelado():
                raise Cancelado()
            rotulo = fonte.get("rotulo") or fonte["id"]
            try:
                ctx.progresso(i, len(escolhidas), rotulo)
            except Exception:
                pass
            try:
                parcial = self._sincronizar_fonte(ctx, fonte, de, ate)
            except Cancelado:
                raise
            except Exception as erro:
                if ctx.cancelado():
                    raise Cancelado() from erro
                mensagem = _frase(erro)
                log.warning("Pauta - %s: %s", rotulo, mensagem,
                            exc_info=type(erro).__name__ not in (
                                "LoginFalhou", "PortalIndisponivel", "PautaNaoEncontrada",
                                "ErroPauta", "SessaoPerdida"))
                self.armazem.atualizar_fonte(fonte["id"], ultimo_erro=mensagem[:500])
                resultado["erros"].append({"fonte": fonte["id"], "rotulo": rotulo,
                                           "mensagem": mensagem})
                continue
            sucesso = True
            resultado["fontes"].append(parcial)
            for chave in ("novas", "atualizadas", "canceladas", "removidas", "total",
                          "alteracoes"):
                resultado[chave] += parcial.get(chave, 0)
            resultado["avisos"] += parcial.get("avisos", [])
        try:
            ctx.progresso(len(escolhidas), len(escolhidas), "")
        except Exception:
            pass
        # mesmo com fontes que falharam: o que as outras gravaram vale
        self._revelados(conhecidos, resultado)
        if sucesso:
            self.armazem.definir_meta("ultima_sincronizacao", self.relogio())
            self._publicar_mudancas(resultado)
            # Outras fontes deram certo: o fim da tarefa só diz "N fontes com
            # problema", e o aviso de cada uma diz qual e por quê. Quando
            # todas falham, o erro da tarefa já traz cada fonte com o motivo
            # (e a faixa da Pauta, também): o aviso por fonte só repetiria.
            for e in resultado["erros"]:
                try:
                    ctx.avisar(f"Pauta: {e['rotulo']}", e["mensagem"])
                except Exception:
                    pass
        if not sucesso:
            raise ErroPauta("Não consegui ler a pauta: " + "; ".join(
                f"{e['rotulo']} — {e['mensagem'].rstrip('.')}" for e in resultado["erros"]) + ".")
        ctx.status(self._frase_resultado(resultado))
        return resultado

    @staticmethod
    def _frase_resultado(r: dict) -> str:
        def plural(n, um, varios):
            return f"{n} {um if n == 1 else varios}"
        partes = [plural(r.get("total", 0), "audiência conferida", "audiências conferidas")]
        mudancas = r.get("novas", 0) + r.get("atualizadas", 0) + r.get("removidas", 0)
        if mudancas:
            detalhes = []
            if r.get("novas"):
                detalhes.append(plural(r["novas"], "nova", "novas"))
            if r.get("atualizadas"):
                detalhes.append(plural(r["atualizadas"], "alterada", "alteradas"))
            if r.get("removidas"):
                detalhes.append(plural(r["removidas"], "saiu da pauta", "saíram da pauta"))
            partes.append(", ".join(detalhes))
        else:
            partes.append("nenhuma mudança")
        if r.get("erros"):
            partes.append(plural(len(r["erros"]), "fonte com problema", "fontes com problema"))
        return " · ".join(partes) + "."

    def _publicar_mudancas(self, resultado: dict) -> None:
        self._evento("pauta", {"tipo": "atualizada", "dados": {
            k: resultado.get(k, 0) for k in ("novas", "atualizadas", "canceladas", "removidas",
                                              "total")}})
        if resultado.get("alteracoes"):
            self._evento("pauta", {"tipo": "alteracoes", "dados": {
                "novas": resultado["alteracoes"], "nao_vistas": self.armazem.nao_vistas()}})

    def _sincronizar_fonte(self, ctx, fonte: dict, de: date, ate: date) -> dict:
        from ..download.modelos import SessaoPerdida
        from .navegacao import ExtratorAutomatico

        tribunal = self._tribunal(fonte["tribunal"], fonte["sistema"])
        opcoes, credenciais = self._acesso(tribunal, ctx)
        nome = f"{tribunal.nome_sistema} do {tribunal.sigla}"
        primeira = not fonte.get("ultima_sincronizacao")
        with self._navegador(tribunal, opcoes) as nav:
            portal = self._portal(nav, tribunal, opcoes, ctx, credenciais)
            ctx.status(f"Entrando no {nome}…")
            portal.entrar()
            if not (getattr(portal, "base", "") or ""):
                # eProc com um endereço por seção judiciária (TRF4, TRF2): o login
                # espera um processo para saber a seção. A rota lembrada (da captura)
                # diz qual é.
                lembrada = fonte.get("url") or ""
                if not lembrada or not hasattr(portal, "_candidatos_atuais"):
                    raise ErroPauta(f"O {nome} tem um endereço por seção judiciária. Abra a "
                                    "pauta com “Capturar no portal”: o endereço fica lembrado.")
                portal._candidatos_atuais = [lembrada.split("controlador.php")[0]]
                portal.entrar()
            extrator = ExtratorAutomatico(
                nav, portal, self.regras,
                self._reconhecedor(tribunal.sigla, tribunal.sistema, fonte["id"]), ctx, fonte,
                self.espera_pagina_s)
            for tentativa in (1, 2):
                try:
                    leitura = extrator.extrair(de, ate)
                    break
                except SessaoPerdida:
                    if tentativa == 2:
                        raise
                    ctx.status(f"A sessão do {nome} caiu; entrando de novo…")
                    portal.entrar()
        ctx.status(f"Gravando a pauta do {nome}…")
        balanco = self.armazem.gravar(leitura.audiencias, fonte["id"], leitura.cobertura(de, ate),
                                      registrar_novas=not primeira, agora=self.relogio())
        self.armazem.atualizar_fonte(fonte["id"], url=leitura.url or fonte.get("url") or "",
                                     menu=leitura.menu or fonte.get("menu") or "",
                                     ultima_sincronizacao=self.relogio(), ultimo_erro="")
        parcial = balanco.como_dict()
        parcial.update({"fonte": fonte["id"], "rotulo": fonte.get("rotulo") or "",
                        "paginas": leitura.paginas, "url": leitura.url,
                        "periodo_aplicado": leitura.periodo_aplicado,
                        "incompleta": getattr(leitura, "incompleta", ""),
                        "avisos": [f"{fonte.get('rotulo') or nome}: {x}" for x in leitura.avisos]})
        return parcial

    # ============================================================ capturar
    def capturar(self, ctx, tribunal: str, sistema: str) -> dict:
        """Captura assistida: abre o portal visível, com a barra do Helestron (8.4)."""
        from .captura import LIMITE_PADRAO_S, CapturaAssistida
        from .navegacao import ExtratorAutomatico, parametros

        sistema = (sistema or "").strip().lower()
        t = self._tribunal((tribunal or "").strip().upper(), sistema)
        id_fonte = Armazem.id_fonte(t.sigla, sistema)
        fonte = self.armazem.fonte(id_fonte) or self.salvar_fonte(t.sigla, sistema, "")
        opcoes, credenciais = self._acesso(t, ctx, visivel=True)
        nome = f"{t.nome_sistema} do {t.sigla}"
        primeira = not fonte.get("ultima_sincronizacao")
        with self._navegador(t, opcoes) as nav:
            portal = self._portal(nav, t, opcoes, ctx, credenciais)
            ctx.status(f"Entrando no {nome}…")
            portal.entrar()
            reconhecedor = self._reconhecedor(t.sigla, sistema, id_fonte)
            cap = CapturaAssistida(nav, self.regras, reconhecedor, ctx,
                                   self.limite_captura_s or LIMITE_PADRAO_S, nome)
            cap.instalar()
            # poupa o caminho: abre a pauta lembrada (no eProc, pelo link assinado)
            extrator = ExtratorAutomatico(nav, portal, self.regras, reconhecedor, ctx, fonte,
                                          self.espera_pagina_s)
            url = fonte.get("url") or ""
            if url and sistema == "eproc":
                url = extrator.link_por_acao(parametros(url).get("acao", ""))
            if url:
                extrator.abrir(url)
            elif not (extrator.url_atual() or "").startswith("http"):
                inicio = getattr(portal, "base", "") or next(iter(t.urls_para(None)), "")
                if inicio:
                    extrator.abrir(inicio)
            ctx.status("O portal está aberto no navegador: vá até a pauta de audiências e "
                       "clique em “Capturar esta tela” na barra do Helestron; no fim, em "
                       "“Concluir”.")
            try:
                ctx.avisar("Captura da pauta",
                           f"O {nome} abriu no navegador. Vá até a pauta de audiências e clique em "
                           "“Capturar esta tela” (em cada página, se houver mais de uma); no fim, "
                           "clique em “Concluir”.")
            except Exception:
                pass
            resultado = cap.esperar()
        audiencias = resultado.audiencias
        conhecidos = self._sigilosos_conhecidos()
        balanco = self.armazem.gravar(audiencias, id_fonte, None, registrar_novas=not primeira,
                                      agora=self.relogio())
        campos = {}
        if resultado.url:
            campos.update(url=resultado.url, modo="capturado")
        if audiencias:
            campos.update(ultima_sincronizacao=self.relogio(), ultimo_erro="")
            self.armazem.definir_meta("ultima_sincronizacao", self.relogio())
        if campos:
            self.armazem.atualizar_fonte(id_fonte, **campos)
        dados = balanco.como_dict()
        dados.update({"capturadas": len(audiencias), "telas": resultado.telas,
                      "url": resultado.url, "motivo": resultado.motivo, "fonte": id_fonte})
        self._revelados(conhecidos, dados)
        if audiencias:
            self._publicar_mudancas(dados)
            ctx.status(f"Captura concluída: {len(audiencias)} audiência"
                       f"{'s' if len(audiencias) != 1 else ''}"
                       + (". O endereço ficou lembrado para o monitoramento." if resultado.url
                          else "."))
        else:
            ctx.status("Nenhuma audiência foi capturada.")
        return dados

    # ============================================================ importar
    def importar(self, caminho: Path) -> dict:
        """Relatório exportado do SAJ/eProc (planilha, HTML, PDF, DOCX) - seção 8.6."""
        try:
            rec = importacao.ler_relatorio(Path(caminho), self.regras, agora=self.relogio())
        except importacao.RelatorioInvalido as erro:
            raise ValueError(_frase(erro)) from erro
        audiencias = rec.audiencias
        conhecidos = self._sigilosos_conhecidos()
        # A mesma audiência já trazida do portal (processo, data e hora) não é
        # duplicada: o relatório só completa o que faltava nela. O par é um a um
        # (pelo tipo, como na sincronização): duas audiências do processo no
        # mesmo horário não trocam o local nem as partes entre si.
        existentes: dict[tuple, list[modelos.Audiencia]] = {}
        if audiencias:
            de = min(a.data for a in audiencias)
            ate = max(a.data for a in audiencias)
            for a in self.armazem.listar(de, ate):
                if a.sistema != "arquivo" and a.processo:
                    existentes.setdefault(
                        (modelos.chave_processo(a.processo), a.data, a.hora), []).append(a)
        do_relatorio: dict[tuple, list[modelos.Audiencia]] = {}
        novas_lista, completar = [], []
        for a in audiencias:
            chave = (modelos.chave_processo(a.processo), a.data, a.hora) if a.processo else None
            if chave and chave in existentes:
                do_relatorio.setdefault(chave, []).append(a)
            else:
                novas_lista.append(a)
        for chave, lista in do_relatorio.items():
            pares = modelos.parear_mesmo_horario(lista, existentes[chave])
            pareadas = {id(a) for a, _alvo in pares}
            novas_lista.extend(a for a in lista if id(a) not in pareadas)
            for a, alvo in pares:
                for campo in ("local", "link", "classe", "partes", "magistrado", "observacoes"):
                    if not getattr(alvo, campo) and getattr(a, campo):
                        setattr(alvo, campo, getattr(a, campo))
                alvo.sigiloso = alvo.sigiloso or a.sigiloso
                completar.append(alvo)
        balanco = self.armazem.gravar(novas_lista, "arquivo", None, registrar_novas=False,
                                      agora=self.relogio())
        atualizadas = balanco.atualizadas
        for alvo in completar:
            b = self.armazem.gravar([alvo], alvo.fonte, None, registrar_novas=False,
                                    agora=self.relogio())
            atualizadas += b.atualizadas
        self.armazem.definir_meta("ultima_importacao", self.relogio())
        resultado = {"novas": balanco.novas, "atualizadas": atualizadas,
                     "ignoradas": rec.ignoradas, "avisos": list(rec.avisos),
                     "total": len(audiencias), "arquivo": Path(caminho).name}
        self._revelados(conhecidos, resultado)
        self._evento("pauta", {"tipo": "atualizada", "dados": {
            "novas": resultado["novas"], "atualizadas": atualizadas, "total": len(audiencias)}})
        return resultado

    # ============================================================ exportar
    def _dentro_do_acervo(self, destino: Path) -> bool:
        try:
            acervo = Path(self.cfg.pasta_acervo)
        except Exception:
            return False
        try:
            from .. import servicos

            return bool(servicos.dentro_ou_igual(destino, acervo))
        except Exception:
            try:
                return destino.resolve().is_relative_to(acervo.resolve())
            except Exception:
                return False

    def exportar(self, de, ate, destino_pasta: Path, **filtros) -> Path:
        """A planilha do período (seção 8.9). Filtros: sistema, situacao, busca,
        incluir_partes_sigilosos (ausente ou None: o padrão [pauta]
        incluir_partes_sigilosos; False explícito MASCARA, mesmo com o
        Ajuste ligado - a escolha feita na hora vale)."""
        destino = Path(destino_pasta)
        if self._dentro_do_acervo(destino):
            raise ValueError("A planilha da pauta não pode ser gravada dentro do acervo: ela traz "
                             "as partes dos processos em segredo de justiça, e tudo o que está no "
                             "acervo é lido pela IA. Escolha outra pasta.")
        incluir = filtros.pop("incluir_partes_sigilosos", None)
        if isinstance(incluir, str):        # "false" vindo de um formulário não é verdadeiro
            incluir = incluir.strip().lower() in ("1", "true", "sim", "s", "yes", "on")
        if incluir is None:
            incluir = ler_flag(self.cfg, "incluir_partes_sigilosos", False)
        escolhidos = {k: str(filtros.get(k) or "").strip() for k in ("sistema", "situacao",
                                                                     "busca")}
        dados = self.listar(de, ate, **escolhidos)
        sistema = escolhidos["sistema"].lower().replace("-", "")
        saida_alt = []
        for alt in self._marcar_sigilo(self.armazem.alteracoes(de=de, ate=ate)):
            a = alt.get("audiencia") or {}
            if sistema and sistema not in ("todos", "*") and a.get("sistema") != sistema:
                continue
            saida_alt.append(alt)
        return exportacao.exportar(dados["audiencias"], saida_alt, de, ate, destino,
                                   incluir_partes_sigilosos=bool(incluir),
                                   filtros={k: v for k, v in escolhidos.items() if v},
                                   agora=self.relogio())
