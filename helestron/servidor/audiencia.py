"""A audiência ao vivo vista pela API: uma sessão por vez, e o teste do microfone.

A sessão (helestron.transcricao.ao_vivo.SessaoAoVivo) roda numa thread
própria: iniciar() reserva o DOCX e liga o microfone; a thread então
espera o Encerrar; encerrar() transcreve o que ficou na fila, grava o
documento final e fecha o áudio. Os eventos da sessão viram o evento
'transcricao' da seção 6.4:

    estado   {texto, estado}        nivel  {nivel}       fala   {inicio, fim, falante, texto}
    atraso   {segundos}             aviso  {texto}       erro   {texto}
    salvo    {arquivo}              fim    {documento}

O medidor de nível chega a cada bloco de áudio (100 ms); vai para a página
no máximo LIMITE_NIVEL_HZ vezes por segundo.

Ao fim, como na versão anterior: o INDICE.md do acervo é refeito (a IA lê o
índice primeiro) e, se ligado, o acervo é espelhado na nuvem - nunca com
audiência sigilosa, que fica fora do acervo.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import servicos
from ..nucleo import cnj
from ..tarefas import MICROFONE, NOMES, frase_ocupado
from .rede import ErroApi, erro_400

log = logging.getLogger("servidor.audiencia")

LIMITE_NIVEL_HZ = 10
ESPERA_ENCERRAR_S = 20 * 60
TESTE_MICROFONE_S = 60
QUEM_SESSAO = "Audiência ao vivo"
QUEM_TESTE = "Teste do microfone"


def _hora(segundos: float) -> str:
    s = int(max(0, segundos))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class GerenteAudiencia:
    def __init__(self, app):
        self.app = app
        self._trava = threading.RLock()
        self.sessao = None
        self.id_sessao: str | None = None
        self.numero = None
        self.estado = "parada"         # parada | iniciando | gravando | pausada | encerrando | encerrada | erro
        self.texto_estado = ""
        self.documento: Path | None = None
        self.erro: str | None = None
        self.sigiloso = False
        self._thread: threading.Thread | None = None
        self._controle = threading.Event()
        self._refinar = False
        self._ultimo_nivel = 0.0
        # A última sessão encerrada: a "revisão" retranscreve a gravação dela
        # com o modelo preciso, usando os falantes marcados ao vivo.
        self.ultima: dict | None = None
        # teste do microfone
        self._captura_teste = None
        self._fim_teste: threading.Timer | None = None

    # ------------------------------------------------------------- estado
    @property
    def ativa(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def como_dict(self) -> dict:
        with self._trava:
            sessao = self.sessao
            falas = []
            segundos = 0.0
            if sessao is not None:
                try:
                    falas = [self._fala(f) for f in list(getattr(sessao, "falas", []) or [])]
                    segundos = float(getattr(sessao, "tempo", 0.0) or 0.0)
                except Exception:              # pragma: no cover - leitura defensiva
                    pass
            return {
                "sessao": self.id_sessao if sessao is not None else None,
                "estado": self.estado, "texto_estado": self.texto_estado,
                "segundos": round(segundos, 1),
                "processo": self.numero.formatado if self.numero is not None else None,
                "sigiloso": self.sigiloso,
                "documento": str(self.documento) if self.documento else None,
                "modelo": getattr(sessao, "modelo", None) if sessao is not None else None,
                "pendentes": getattr(sessao, "pendentes", 0) if sessao is not None else 0,
                "falante": getattr(sessao, "falante", "") if sessao is not None else "",
                "erro": self.erro, "falas": falas,
            }

    @staticmethod
    def _fala(f) -> dict:
        if hasattr(f, "como_dict"):
            d = f.como_dict()
        else:
            d = {"inicio": float(getattr(f, "inicio", 0.0)), "fim": float(getattr(f, "fim", 0.0)),
                 "falante": getattr(f, "falante", "") or "", "texto": getattr(f, "texto", "")}
        d["hora"] = _hora(d.get("inicio", 0.0))
        return d

    # ------------------------------------------------------------ eventos
    def _publicar(self, tipo: str, dados: dict) -> None:
        self.app.hub.publicar("transcricao", {"tipo": tipo, "dados": dados})

    def _evento(self, tipo: str, dado) -> None:
        """O 'eventos(tipo, dado)' da SessaoAoVivo (chamado de várias threads)."""
        if tipo == "nivel":
            agora = time.monotonic()
            if agora - self._ultimo_nivel < 1.0 / LIMITE_NIVEL_HZ:
                return
            self._ultimo_nivel = agora
            try:
                self._publicar("nivel", {"nivel": round(max(0.0, min(1.0, float(dado))), 3)})
            except (TypeError, ValueError):
                pass
            return
        if tipo == "estado":
            self.texto_estado = str(dado or "")
            sessao = self.sessao
            interno = getattr(sessao, "estado", "") if sessao is not None else ""
            if interno in ("gravando", "pausada", "encerrando", "encerrada"):
                self.estado = interno
            self._publicar("estado", {"texto": self.texto_estado, "estado": self.estado})
        elif tipo == "fala":
            self._publicar("fala", self._fala(dado))
        elif tipo == "atraso":
            try:
                self._publicar("atraso", {"segundos": round(float(dado), 1)})
            except (TypeError, ValueError):
                pass
        elif tipo in ("aviso", "erro"):
            self._publicar(tipo, {"texto": str(dado)})
        elif tipo == "salvo":
            self._publicar("salvo", {"arquivo": str(dado)})
        elif tipo == "fim":
            self._publicar("fim", {"documento": str(dado)})
        else:
            self._publicar(tipo, {"valor": dado})

    # ------------------------------------------------------------ iniciar
    def iniciar(self, dados: dict) -> dict:
        texto = str(dados.get("processo") or "").strip()
        if not texto:
            raise erro_400("Informe o número do processo: é ele que dá nome ao documento.",
                           "numero_ausente")
        try:
            numero = cnj.ler(texto)
        except cnj.NumeroInvalido as erro:
            raise erro_400(f"“{texto}” não é um número de processo no padrão CNJ "
                           "(0000000-00.0000.0.00.0000).", "numero_invalido") from erro
        cfg = self.app.cfg
        dispositivo = dados.get("dispositivo")
        if isinstance(dispositivo, str) and dispositivo.strip().lstrip("-").isdigit():
            dispositivo = int(dispositivo)
        if dispositivo in ("",):
            dispositivo = None
        sigiloso = dados.get("sigiloso")
        sigiloso = servicos.processo_sigiloso(cfg, numero) if sigiloso is None else bool(sigiloso)
        participantes = dados.get("participantes") or {}
        if not isinstance(participantes, dict):
            raise erro_400("Os participantes devem vir como {\"F1\": \"Juiz(a)\", ...}.")
        participantes = {str(k): str(v) for k, v in participantes.items() if str(v).strip()}
        tipo = str(dados.get("tipo") or "").strip()
        falante = str(dados.get("falante") or "").strip()

        with self._trava:
            if self.ativa:
                raise ErroApi(409, "sessao_ativa",
                              "Já há uma audiência sendo transcrita. Encerre-a antes de começar "
                              "outra.")
            self.parar_teste()
            dono = self.app.recursos.tomar(QUEM_SESSAO, (MICROFONE,))
            if dono is not None:
                raise ErroApi(409, "ocupado", frase_ocupado(dono, [NOMES[MICROFONE]]))
            try:
                sessao = servicos.nova_sessao(numero, cfg, self._evento, tipo=tipo,
                                              participantes=participantes, falante=falante,
                                              sigiloso=sigiloso, dispositivo=dispositivo)
            except BaseException:
                self.app.recursos.soltar(QUEM_SESSAO)
                raise
            self.sessao = sessao
            self.id_sessao = secrets.token_hex(6)
            self.numero = numero
            self.sigiloso = sigiloso
            self.estado = "iniciando"
            self.texto_estado = "Preparando a gravação…"
            self.documento = None
            self.erro = None
            self._controle = threading.Event()
            self._refinar = cfg.flag("transcricao", "refinar_ao_encerrar")
            self._thread = threading.Thread(target=self._rodar, args=(sessao, self._controle),
                                            name="audiencia-ao-vivo", daemon=True)
            self._thread.start()
        for chave, valor in (("ultimo_processo", numero.formatado), ("tipo_audiencia", tipo)):
            try:
                cfg.definir("interface", chave, valor)
            except Exception as erro:          # lembrar não impede a audiência
                log.debug("não consegui lembrar %s: %s", chave, erro)
        self._publicar("estado", {"texto": self.texto_estado, "estado": self.estado})
        self.app.hub.publicar("estado", {})
        return {"sessao": self.id_sessao, "processo": numero.formatado, "sigiloso": sigiloso}

    def _rodar(self, sessao, controle: threading.Event) -> None:
        try:
            try:
                sessao.iniciar()
            except Exception as erro:
                texto = str(erro) or type(erro).__name__
                log.error("a audiência não pôde começar: %s", texto)
                with self._trava:
                    self.estado = "erro"
                    self.erro = texto[:1].upper() + texto[1:]
                # O estado "erro" diz à tela que a gravação NÃO começou (sem
                # microfone, microfone ocupado, permissão negada): ela volta à
                # preparação e mostra o motivo, em vez de um cronômetro andando.
                self._publicar("estado", {"texto": self.erro, "estado": "erro", "fase": "inicio"})
                self._publicar("erro", {"texto": self.erro})
                return
            with self._trava:
                if self.estado == "iniciando":
                    self.estado = getattr(sessao, "estado", "gravando") or "gravando"
            self._publicar("estado", {"texto": self.texto_estado or "Gravando",
                                      "estado": self.estado})
            controle.wait()
            with self._trava:
                self.estado = "encerrando"
            self._publicar("estado", {"texto": "Concluindo a transcrição…",
                                      "estado": "encerrando"})
            try:
                documento = sessao.encerrar(refinar=self._refinar)
            except Exception as erro:
                log.exception("falha ao encerrar a audiência")
                texto = str(erro) or type(erro).__name__
                with self._trava:
                    self.estado = "erro"
                    self.erro = texto[:1].upper() + texto[1:]
                self._publicar("estado", {"texto": self.erro, "estado": "erro", "fase": "fim"})
                self._publicar("erro", {"texto": self.erro})
                return
            with self._trava:
                self.documento = Path(documento)
                self.estado = "encerrada"
                self.ultima = {
                    "numero": self.numero, "audio": getattr(sessao, "caminho_audio", None),
                    "falas": list(getattr(sessao, "falas", []) or []),
                    "sigiloso": bool(getattr(sessao, "sigiloso", self.sigiloso)),
                    "documento": self.documento,
                }
            self._depois_de_salvar(self.documento)
        finally:
            self.app.recursos.soltar(QUEM_SESSAO)
            self.app.hub.publicar("estado", {})

    def _depois_de_salvar(self, documento: Path) -> None:
        """O índice do acervo em dia e, se ligado, o espelho na nuvem.

        Nunca durante o fechamento (o espelho do acervo inteiro seguraria o
        programa) e nunca com sigiloso preso no acervo.
        """
        if self.app.fechando:
            return
        try:
            from .api_compartilhar import depois_de_salvar
        except ImportError:                    # pragma: no cover
            return
        depois_de_salvar(self.app, documento)

    # ---------------------------------------------------------- controles
    def _sessao_ativa(self):
        with self._trava:
            if not self.ativa or self.sessao is None:
                raise ErroApi(409, "sem_sessao", "Não há audiência sendo transcrita agora.")
            return self.sessao

    def pausar(self) -> dict:
        self._sessao_ativa().pausar()
        return self.como_dict()

    def retomar(self) -> dict:
        self._sessao_ativa().retomar()
        return self.como_dict()

    def definir_falante(self, falante: str) -> dict:
        self._sessao_ativa().definir_falante(str(falante or "").strip())
        return {"falante": str(falante or "").strip()}

    def encerrar(self, refinar: bool | None = None, espera_s: float = ESPERA_ENCERRAR_S) -> dict:
        """Pede o fim e espera o documento final (o encerramento transcreve a
        fila atrasada; num computador lento leva minutos). Se demorar mais
        que 'espera_s', responde sem o documento - ele chega pelo evento
        'transcricao' {tipo: "fim"}."""
        with self._trava:
            thread = self._thread
            if thread is None or not thread.is_alive():
                if self.documento is not None:
                    return {"documento": str(self.documento)}
                raise ErroApi(409, "sem_sessao", "Não há audiência sendo transcrita agora.")
            if refinar is not None:
                self._refinar = bool(refinar)
            self._controle.set()
        thread.join(timeout=max(0.0, espera_s))
        with self._trava:
            if self.estado == "erro":
                raise ErroApi(500, "erro_ao_encerrar", self.erro or "A audiência não pôde ser "
                                                                    "encerrada.")
            return {"documento": str(self.documento) if self.documento else None,
                    "encerrando": thread.is_alive()}

    def encerrar_para_fechar(self, espera_s: float) -> None:
        """O programa está fechando: salva a audiência (sem a revisão demorada)."""
        self.parar_teste()
        with self._trava:
            thread = self._thread
            if thread is None or not thread.is_alive():
                return
            self._refinar = False
            sessao = self.sessao
            self._controle.set()
        try:
            sessao.cancelar()                  # interrompe a revisão, se tiver começado
        except Exception:
            pass
        thread.join(timeout=max(0.0, espera_s))

    # ---------------------------------------------------- teste do microfone
    def testar_microfone(self, dispositivo) -> dict:
        if isinstance(dispositivo, str) and dispositivo.strip().lstrip("-").isdigit():
            dispositivo = int(dispositivo)
        with self._trava:
            if self.ativa:
                raise ErroApi(409, "sessao_ativa", "O microfone está em uso pela audiência.")
            self.parar_teste()
            dono = self.app.recursos.tomar(QUEM_TESTE, (MICROFONE,))
            if dono is not None:
                raise ErroApi(409, "ocupado", frase_ocupado(dono, [NOMES[MICROFONE]]))
            try:
                captura = servicos.abrir_teste_microfone(
                    dispositivo, self._nivel_teste,
                    lambda texto: self.app.hub.publicar("aviso", {
                        "titulo": "Microfone", "mensagem": str(texto), "nivel": "aviso"}))
            except BaseException:
                self.app.recursos.soltar(QUEM_TESTE)
                raise
            self._captura_teste = captura
            # Esquecido ligado, o teste prenderia o microfone para sempre.
            self._fim_teste = threading.Timer(TESTE_MICROFONE_S, self.parar_teste)
            self._fim_teste.daemon = True
            self._fim_teste.start()
        return {"testando": True, "segundos": TESTE_MICROFONE_S}

    def _nivel_teste(self, nivel) -> None:
        agora = time.monotonic()
        if agora - self._ultimo_nivel < 1.0 / LIMITE_NIVEL_HZ:
            return
        self._ultimo_nivel = agora
        try:
            self.app.hub.publicar("microfone_nivel", {"nivel": round(max(0.0, min(1.0, float(nivel))), 3)})
        except (TypeError, ValueError):
            pass

    def parar_teste(self) -> dict:
        with self._trava:
            captura, self._captura_teste = self._captura_teste, None
            temporizador, self._fim_teste = self._fim_teste, None
        if temporizador is not None:
            temporizador.cancel()
        if captura is not None:
            try:
                captura.parar()
            except Exception as erro:
                log.warning("falha ao desligar o teste do microfone: %s", erro)
            self.app.hub.publicar("microfone_nivel", {"nivel": 0.0})
        self.app.recursos.soltar(QUEM_TESTE)
        return {"testando": False}

    @property
    def testando(self) -> bool:
        return self._captura_teste is not None


def numero_da_gravacao(nome: str, processo: str | None):
    """O número do processo da gravação: o informado, ou o do nome do arquivo."""
    if processo:
        try:
            return cnj.ler(str(processo))
        except cnj.NumeroInvalido as erro:
            raise erro_400(f"“{processo}” não é um número de processo no padrão CNJ.",
                           "numero_invalido") from erro
    numero = servicos.numero_no_nome(Path(nome))
    if numero is None:
        raise erro_400("O nome do arquivo não traz o número do processo. Informe o número: ele "
                       "dá nome ao documento.", "numero_ausente")
    return numero


def quando(caminho: Path) -> str | None:
    try:
        return datetime.fromtimestamp(Path(caminho).stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None
