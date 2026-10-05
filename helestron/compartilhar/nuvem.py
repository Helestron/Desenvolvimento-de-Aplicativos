"""Espelha o acervo numa pasta do OneDrive ou do Google Drive.

Os conectores do ChatGPT e do Claude (na web, no celular e no Cowork) leem
arquivos do OneDrive/SharePoint e do Google Drive. Pôr o acervo numa dessas
pastas é, portanto, o jeito de deixá-lo ao alcance dessas ferramentas sem
anexar arquivo por arquivo.

O acervo de trabalho NÃO mora na pasta sincronizada - a sincronização
atrapalha arquivo em uso (lição do Assessor SAJ). O que se faz é uma CÓPIA
de mão única, ao fim de cada lote ou quando o usuário pede: só o que é novo
ou mudou é copiado, e nada é apagado no destino - com uma exceção, de
propósito: a cópia de um processo que o programa hoje sabe sigiloso (segredo
de justiça: autos, transcrição ou gravação na pasta de sigilosos, ou a pauta
de audiências marcando o sigilo - a regra única de nucleo/sigilo.py) é
retirada do espelho.

Falha não fica escondida no registro: o resultado (Espelho) traz os arquivos
que não foram copiados, e a cópia de sigiloso que não pôde sair da nuvem
encerra o espelho com erro (SigilosoNaNuvem), depois de feito o resto.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import string
from pathlib import Path

from ..nucleo import cnj, sigilo
from .mcp_servidor import _DO_CONFIG, Recorte, chaves_sigilosas, pasta_sigilosos_configurada

log = logging.getLogger("compartilhar.nuvem")

SUBPASTA = "Helestron - Acervo"
# A subpasta do espelho da versão anterior (Assessor Integrado). Ninguém mais
# copia para lá, mas o que ficou continua ao alcance dos conectores do
# OneDrive e do Google Drive: dela também sai a cópia do processo que depois
# foi para a pasta de sigilosos.
SUBPASTAS_ANTIGAS = ("Assessor Integrado - Acervo",)
_IGNORAR_PASTAS = {"_controle", "_audio", "__pycache__"}
_IGNORAR_SUFIXOS = (".parcial", ".tmp", ".part", ".lock")


def detectar() -> dict[str, Path]:
    """Pastas de nuvem encontradas neste computador: {rótulo: caminho}."""
    achadas: dict[str, Path] = {}
    for var, rotulo in (("OneDriveCommercial", "OneDrive (instituição)"),
                        ("OneDriveConsumer", "OneDrive (pessoal)"),
                        ("OneDrive", "OneDrive")):
        valor = os.environ.get(var)
        if valor and Path(valor).is_dir():
            p = Path(valor)
            if p not in achadas.values():
                achadas[rotulo] = p
    # Google Drive para computador: unidade virtual com "Meu Drive"/"My Drive",
    # ou a pasta antiga do Backup and Sync no perfil.
    candidatos = []
    if os.name == "nt":
        for letra in string.ascii_uppercase[3:]:
            candidatos += [Path(f"{letra}:/Meu Drive"), Path(f"{letra}:/My Drive")]
    casa = Path.home()
    candidatos += [casa / "Google Drive" / "Meu Drive", casa / "Google Drive" / "My Drive",
                   casa / "Google Drive", casa / "Meu Drive", casa / "My Drive"]
    for c in candidatos:
        try:
            if c.is_dir():
                achadas.setdefault("Google Drive", c)
                break
        except OSError:
            continue
    return achadas


class Espelho(tuple):
    """O resultado do espelho: desempacota como (copiados, iguais), como
    antes, e traz também as falhas - os arquivos que NÃO foram copiados
    ('nao_copiados': [(arquivo, motivo)]) e as cópias de processo sigiloso que
    NÃO puderam sair da nuvem ('sigilosos_restantes': [(arquivo, motivo)])."""

    def __new__(cls, copiados: int, iguais: int, nao_copiados=(), sigilosos_restantes=()):
        obj = super().__new__(cls, (copiados, iguais))
        obj.copiados = copiados
        obj.iguais = iguais
        obj.nao_copiados = list(nao_copiados)
        obj.sigilosos_restantes = list(sigilosos_restantes)
        return obj

    @property
    def resumo(self) -> str:
        """"3 copiados, 4 sem mudança, 1 NÃO copiado (X.pdf: motivo)"."""
        frase = (f"{self.copiados} copiado{'s' if self.copiados != 1 else ''}, "
                 f"{self.iguais} sem mudança")
        if self.nao_copiados:
            k = len(self.nao_copiados)
            lista = "; ".join(f"{a.name}: {m}" for a, m in self.nao_copiados[:5])
            if k > 5:
                lista += f"; e mais {k - 5}"
            frase += f", {k} NÃO copiado{'s' if k != 1 else ''} ({lista})"
        return frase


class SigilosoNaNuvem(RuntimeError):
    """Ficou na nuvem cópia de processo em segredo de justiça que o espelho
    não conseguiu apagar: quem chamou encerra com erro visível, com o
    arquivo e a pasta a limpar à mão. 'espelho' traz o resto do resultado."""

    def __init__(self, espelho: Espelho, destino: Path):
        self.espelho = espelho
        lista = "; ".join(f"{a} ({m})" for a, m in espelho.sigilosos_restantes[:5])
        k = len(espelho.sigilosos_restantes)
        if k > 5:
            lista += f"; e mais {k - 5}"
        super().__init__(
            ("Ficou na nuvem cópia de processo em segredo de justiça que não pôde ser apagada: "
             if k == 1 else
             f"Ficaram na nuvem {k} cópias de processo em segredo de justiça que não puderam "
             "ser apagadas: ")
            + f"{lista}. Apague-a{'s' if k != 1 else ''} à mão, na pasta {destino} (o arquivo "
              "pode estar aberto, ou o OneDrive/Google Drive o estava sincronizando). O resto do "
              f"espelho foi feito: {espelho.resumo}.")


def _longo(p: Path) -> str:
    """O caminho como o Windows aceita acima de 260 caracteres ("\\\\?\\"):
    "OneDrive - <instituição>\\Helestron - Acervo\\Processos\\<lote>\\...parcial"
    passa disso com facilidade. Fora do Windows, o caminho como está."""
    texto = os.path.abspath(str(p))
    if os.name != "nt" or len(texto) < 240 or texto.startswith("\\\\?\\"):
        return texto
    if texto.startswith("\\\\"):
        return "\\\\?\\UNC\\" + texto[2:]
    return "\\\\?\\" + texto


def _liberar_e(acao, caminho: str) -> None:
    """Faz 'acao(caminho)'; se o Windows recusar (arquivo somente leitura),
    tira o atributo e tenta de novo uma vez."""
    try:
        acao(caminho)
    except PermissionError:
        try:
            os.chmod(caminho, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            raise
        acao(caminho)


def _apagar(p: Path) -> None:
    _liberar_e(os.unlink, _longo(p))


def _copiar(origem: Path, alvo: Path) -> None:
    """Cópia atômica (".parcial" e troca) que não leva o atributo somente
    leitura da origem para a nuvem: com ele, o próximo espelho (e a retirada
    de um processo que virou sigiloso) não conseguiria trocar nem apagar a
    cópia. A data de modificação vai junto (é o que _deve_copiar compara)."""
    st = origem.stat()
    os.makedirs(_longo(alvo.parent), exist_ok=True)
    tmp = _longo(alvo.with_name(alvo.name + ".parcial"))
    destino = _longo(alvo)
    try:
        shutil.copyfile(_longo(origem), tmp)
        os.utime(tmp, (st.st_atime, st.st_mtime))
        try:
            os.replace(tmp, destino)
        except PermissionError:
            if not os.path.exists(destino):
                raise
            os.chmod(destino, stat.S_IWRITE | stat.S_IREAD)
            os.replace(tmp, destino)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _deve_copiar(origem: Path, destino: Path) -> bool:
    try:
        a = origem.stat()
    except OSError:
        return False
    try:
        b = os.stat(_longo(destino))
    except OSError:
        return True
    # mtime com folga de 2 s: FAT/exFAT e alguns clientes de nuvem arredondam.
    return a.st_size != b.st_size or a.st_mtime > b.st_mtime + 2


def _chave(nome: str) -> str | None:
    try:
        return cnj.ler_nome_arquivo(Path(nome).stem).nome_arquivo
    except cnj.NumeroInvalido:
        return None


def espelhar(origem: Path, destino_raiz: Path, progresso=None, cancelado=None,
             sigilosos=_DO_CONFIG, pauta=sigilo.PAUTA_DO_PROGRAMA) -> Espelho:
    """Copia o acervo para '<destino_raiz>/Helestron - Acervo'.

    Devolve o Espelho, que desempacota como (copiados, iguais) e traz os
    arquivos que não puderam ser copiados. Não apaga nada no destino, exceto
    a cópia de processo sigiloso pela regra única - na pasta de sigilosos
    ('sigilosos'; por padrão, a do config.ini) ou marcado na pauta ('pauta';
    por padrão, o banco do programa): PDF, texto extraído, transcrição ou
    minuta com o número dele. O processo sigiloso também não é copiado. Se a
    cópia de um sigiloso não puder sair da nuvem, o resto do espelho é feito
    e, no fim, levanta SigilosoNaNuvem: segredo de justiça na nuvem não pode
    terminar como sucesso.
    """
    origem = Path(origem)
    destino = Path(destino_raiz) / SUBPASTA
    if _dentro_ou_igual(destino, origem) or _dentro_ou_igual(origem, destino):
        # Defesa final (a API já recusa essa pasta): o espelho dentro do
        # acervo copiaria a cópia anterior a cada vez, sem fim.
        raise ValueError("a pasta da nuvem não pode ficar dentro do acervo, nem conter o acervo")
    if sigilosos is _DO_CONFIG:
        sigilosos = pasta_sigilosos_configurada()
    # Pasta de sigilosos e pastas do programa postas (por engano) dentro do
    # acervo, e link ou junção para fora dele: ficam de fora
    recorte = Recorte(origem, sigilosos)
    sigilosas = chaves_sigilosas(sigilosos, origem, pauta)
    arquivos = []
    for p in origem.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(origem).parts
        partes = set(rel[:-1])
        if partes & _IGNORAR_PASTAS or p.name.startswith("~$") \
                or p.name.endswith(_IGNORAR_SUFIXOS):
            continue
        if not recorte.aceita(p):
            continue
        if sigilosas and _chave(p.name) in sigilosas:
            continue
        arquivos.append(p)
    restantes = _retirar_sigilosos(destino, sigilosas)
    for antiga in SUBPASTAS_ANTIGAS:
        restantes += _retirar_sigilosos(Path(destino_raiz) / antiga, sigilosas)
    copiados = iguais = 0
    nao_copiados: list[tuple[Path, str]] = []
    total = len(arquivos)
    for i, p in enumerate(arquivos, 1):
        if cancelado and cancelado():
            break
        alvo = destino / p.relative_to(origem)
        if not _deve_copiar(p, alvo):
            iguais += 1
            continue
        if progresso:
            progresso(i, total, p.name)
        try:
            _copiar(p, alvo)
            copiados += 1
        except OSError as erro:
            nao_copiados.append((p, _motivo(erro)))
            log.error("NÃO copiei %s para a nuvem: %s", p.name, erro)
    resultado = Espelho(copiados, iguais, nao_copiados, restantes)
    log.info("Espelho na nuvem (%s): %s.", destino, resultado.resumo)
    if restantes:
        raise SigilosoNaNuvem(resultado, destino)
    return resultado


def _motivo(erro: OSError) -> str:
    if getattr(erro, "winerror", None) == 206 or getattr(erro, "errno", None) == 36:
        return "caminho longo demais"
    if isinstance(erro, PermissionError):
        return "arquivo aberto ou sem permissão"
    return str(getattr(erro, "strerror", "") or erro)[:120]


def _dentro_ou_igual(filho: Path, pai: Path) -> bool:
    def normal(p: Path) -> str:
        try:
            p = Path(p).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            p = Path(os.path.abspath(p))
        return os.path.normcase(str(p))

    f, p = normal(filho), normal(pai)
    return f == p or f.startswith(p.rstrip(os.sep) + os.sep)


def _retirar_sigilosos(destino: Path, sigilosas: set[str]) -> list[tuple[Path, str]]:
    """Apaga do espelho as cópias dos processos sigilosos (a regra única).

    Elas chegaram lá antes de se saber do sigilo (a separação falhou e foi
    refeita à mão, ou o segredo foi decretado depois e a pauta o mostrou);
    segredo de justiça não pode continuar na nuvem. Devolve as cópias que
    NÃO puderam ser apagadas, com o motivo.
    """
    ficaram: list[tuple[Path, str]] = []
    if not sigilosas or not destino.is_dir():
        return ficaram
    for p in destino.rglob("*"):
        try:
            if p.is_file() and _chave(p.name) in sigilosas:
                _apagar(p)
                log.warning("Retirei do espelho na nuvem %s: o processo é sigiloso (segredo "
                            "de justiça).", p.relative_to(destino))
        except OSError as erro:
            ficaram.append((p, _motivo(erro)))
            log.error("ATENÇÃO: não consegui retirar do espelho na nuvem %s, de processo "
                      "sigiloso (%s). Apague-o à mão.", p, erro)
    return ficaram
