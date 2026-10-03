"""Configuração do programa: o config.ini, comentado, editável no Bloco de Notas.

Quase tudo se ajusta pela tela de Configurações; o ini existe para quem quer
mexer direto e para guardar as escolhas entre uma abertura e outra.

Duas armadilhas do Assessor SAJ ficam resolvidas aqui:
  * o ConfigParser com interpolação quebrava valor com '%' (uma senha, um
    caminho do Windows com %USERPROFILE%) - aqui a interpolação é desligada;
  * o comentário no fim da linha (';') cortava valores que tinham ';' -
    aqui comentário só no começo da linha.

A gravação (definir) altera só a linha da chave e preserva todos os
comentários, para o arquivo continuar legível depois que a tela o salva.
"""

from __future__ import annotations

import configparser
import logging
import os
import re
import threading
from pathlib import Path

from . import caminhos

log = logging.getLogger("nucleo.config")

# (seção, chave, padrão, comentário). A ordem aqui é a ordem do arquivo.
ESQUEMA: list[tuple[str, str, str, str]] = [
    ("geral", "pasta_acervo", "Acervo",
     "Pasta com tudo o que o programa produz e compartilha com a IA:\n"
     "Processos (os PDFs), Transcricoes (os DOCX) e os arquivos de contexto.\n"
     "Caminho relativo a esta pasta, ou absoluto (ex.: D:\\Gabinete\\Acervo).\n"
     "Evite pasta dentro do OneDrive: a sincronização atrapalha arquivo em uso."),
    ("geral", "pasta_sigilosos", "Sigilosos",
     "Processos em segredo de justiça vão para cá, FORA do acervo\n"
     "compartilhado com a IA. Mesma regra de caminho."),
    ("geral", "nome_usuario", "", "Como o programa chama você na tela inicial."),

    ("unidade", "magistrado", "", "Aparecem no cabeçalho das transcrições."),
    ("unidade", "cargo", "", ""),
    ("unidade", "vara", "", ""),
    ("unidade", "comarca", "", ""),
    ("unidade", "tribunal", "", ""),

    ("download", "pular_baixados", "true",
     "Processo cujo PDF já está na pasta de destino não é baixado de novo."),
    ("download", "separar_sigilosos", "true",
     "Processo em segredo de justiça vai para a pasta_sigilosos (recomendado)."),
    ("download", "baixar_midias", "false",
     "Baixar também as gravações de audiência (ficam em _controle\\midias, dentro\n"
     "da pasta do lote)."),
    ("download", "mostrar_navegador", "false",
     "Mostrar a janela do navegador durante o download. O login por\n"
     "certificado e o login manual sempre mostram."),
    ("download", "navegador", "auto",
     "auto (Chrome, senão Edge, senão o Chromium do programa), chrome,\n"
     "msedge ou chromium."),
    ("download", "pausa_entre_processos", "3",
     "Segundos entre um processo e outro. Não zere em listas grandes: rajada\n"
     "de acessos pode ser lida pelo portal como abuso."),
    ("download", "tentativas", "2", "Quantas vezes tentar um processo que falhou por instabilidade."),
    ("download", "espera_segundos", "60", "Quanto esperar cada resposta do portal."),
    ("download", "espera_login_minutos", "10",
     "Quanto esperar você concluir o login (código por e-mail, certificado)."),
    ("download", "salvar_diagnostico", "true",
     "Guardar print e HTML da tela quando algo der errado (Logs\\diagnostico)."),

    ("esaj", "login", "senha", "Como entrar no e-SAJ: senha, certificado ou manual."),
    ("eproc", "login", "senha", "Como entrar no eProc: senha ou manual."),
    ("eproc", "modo", "documentos",
     "Como montar o PDF: documentos (baixa peça por peça, na ordem dos eventos,\n"
     "com marcadores - padrão) ou completo (usa o \"Download Completo\" do\n"
     "eProc, que o tribunal gera em segundo plano; se demorar, volta para\n"
     "documentos)."),
    ("eproc", "espera_completo_minutos", "8",
     "No modo completo, quanto esperar o tribunal gerar o arquivo."),
    ("eproc", "perfil", "",
     "Perfil a escolher depois do login, quando o usuário tem mais de um\n"
     "(ex.: MAGISTRADO). Em branco = o programa pergunta na janela."),

    ("transcricao", "modelo_ao_vivo", "small",
     "Modelo da transcrição ao vivo: base (computador fraco), small\n"
     "(recomendado) ou medium (computador forte, 8 núcleos ou mais)."),
    ("transcricao", "modelo_revisao", "medium",
     "Modelo da revisão final e das gravações: small, medium ou large-v3-turbo."),
    ("transcricao", "refinar_ao_encerrar", "false",
     "Ao encerrar a audiência, refazer a transcrição inteira com o modelo de\n"
     "revisão (mais precisa; leva alguns minutos)."),
    ("transcricao", "separar_falantes", "true",
     "Na revisão final, separar as vozes automaticamente (se o componente\n"
     "estiver instalado)."),
    ("transcricao", "dispositivo", "", "Microfone. Em branco = o padrão do Windows."),
    ("transcricao", "salvar_audio", "true",
     "Guardar a gravação (FLAC) ao lado da transcrição, em _audio."),
    ("transcricao", "marcar_tempo", "true", "Mostrar [hh:mm:ss] em cada fala."),
    ("transcricao", "falantes",
     "Juiz(a);Promotor(a);Defensor(a);Advogado(a) do autor;Advogado(a) do réu;"
     "Testemunha;Parte;Outro",
     "Botões de quem está falando (F1, F2...), separados por ponto e vírgula."),
    ("transcricao", "contexto",
     "Transcrição de audiência judicial. Participam o Juiz de Direito, o "
     "Ministério Público, advogados, partes e testemunhas. Vocabulário "
     "forense: Meritíssimo, Excelência, contraditado, compromissada, "
     "depoimento, oitiva, instrução, exordial, preposto, reclamante, "
     "reclamado, autor, réu, petição inicial, contestação, sentença, agravo, "
     "tutela de urgência.",
     "Texto que orienta vocabulário e pontuação. MANTENHA ACENTUADO: o modelo\n"
     "imita a grafia do contexto; sem acento, a transcrição sai sem acento."),
    ("transcricao", "threads", "0", "Núcleos usados. 0 = metade dos disponíveis."),

    ("interface", "assistente_concluido", "false",
     "As chaves desta seção são gravadas pela própria tela."),
    ("interface", "tribunal", "", ""),
    ("interface", "pasta_relacoes", "", ""),
    ("interface", "ultimo_processo", "", ""),
    ("interface", "tipo_audiencia", "", ""),

    ("compartilhar", "pasta_nuvem", "",
     "Pasta do OneDrive ou do Google Drive para espelhar o acervo (os\n"
     "conectores do ChatGPT e do Claude leem de lá). Em branco = não espelha."),
    ("compartilhar", "espelhar_automaticamente", "false",
     "Espelhar sozinho ao fim de cada download e de cada transcrição."),
    ("compartilhar", "incluir_texto", "true",
     "Gerar a versão em texto dos autos (com a página e o documento marcados),\n"
     "que a IA lê muito melhor e mais barato que o PDF."),
]

CABECALHO = """\
; ============================================================
;  Assessor Integrado - configuração
;  Quase tudo aqui também se ajusta pela tela de Configurações.
;  Edite com o Bloco de Notas e salve. Comentário: linha com ';'.
; ============================================================
"""

_trava = threading.Lock()


def modelo_ini() -> str:
    """O config.ini inicial, com os comentários."""
    linhas = [CABECALHO]
    secao_atual = None
    for secao, chave, padrao, comentario in ESQUEMA:
        if secao != secao_atual:
            linhas.append(f"\n[{secao}]")
            secao_atual = secao
        if comentario:
            linhas.extend(f"; {c}" if c else ";" for c in comentario.split("\n"))
        linhas.append(f"{chave} = {padrao}")
    return "\n".join(linhas) + "\n"


PADROES = {(s, c): p for s, c, p, _ in ESQUEMA}


def _ler_texto(arquivo: Path) -> str:
    """O config.ini como texto, qualquer que seja a codificação.

    O cabeçalho manda editar no Bloco de Notas: o arquivo pode voltar em
    ANSI (cp1252) ou em UTF-16 (Out-File do PowerShell 5.1). Lido só como
    UTF-8, ele seria descartado em silêncio e todas as chaves - a pasta do
    acervo inclusive - voltariam ao padrão. A gravação é sempre em UTF-8.
    """
    dados = arquivo.read_bytes()
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return dados.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    # Linha a linha: um arquivo em UTF-8 com uma linha editada em ANSI não
    # estraga o acento das outras.
    log.warning("O %s não está todo em UTF-8: as linhas em outra codificação foram lidas "
                "como ANSI (Windows-1252), e a próxima gravação converte o arquivo.",
                arquivo.name)
    linhas = []
    for linha in dados.split(b"\n"):
        try:
            linhas.append(linha.decode("utf-8"))
        except UnicodeDecodeError:
            linhas.append(linha.decode("cp1252", errors="replace"))
    return "\n".join(linhas).lstrip("\ufeff")


def _novo_parser() -> configparser.ConfigParser:
    return configparser.ConfigParser(
        interpolation=None, comment_prefixes=(";", "#"),
        inline_comment_prefixes=None, strict=False)


class Config:
    """Leitura tolerante: chave ausente ou inválida vira o padrão.

    'criar=False' só lê: não cria o config.ini se ele faltar (uso do servidor
    MCP, que roda a pedido do Claude Desktop e não deve gravar nada).
    """

    def __init__(self, arquivo: Path | None = None, criar: bool = True):
        self.arquivo = Path(arquivo or caminhos.ARQUIVO_CONFIG)
        self._criar = criar
        self._cp = _novo_parser()
        self.recarregar()

    def recarregar(self) -> None:
        if self._criar and not self.arquivo.exists():
            try:
                self.arquivo.parent.mkdir(parents=True, exist_ok=True)
                self.arquivo.write_text(modelo_ini(), encoding="utf-8")
            except OSError:
                pass
        # O parser novo é montado à parte e só então posto no lugar: as
        # threads de trabalho leem a configuração sem trava e, durante a
        # leitura, veriam um parser vazio (tudo no padrão) ou valores ainda
        # em montagem (listas em vez de texto).
        cp = _novo_parser()
        try:
            cp.read_string(_ler_texto(self.arquivo), source=str(self.arquivo))
        except OSError:
            pass  # sem arquivo: tudo no padrão
        except configparser.Error as erro:
            # arquivo estragado: o que não pôde ser lido fica no padrão, e a
            # tela regrava
            log.warning("O %s tem erro de formato (%s); as chaves afetadas ficam no padrão.",
                        self.arquivo.name, (str(erro).splitlines() or [""])[0][:160])
        self._cp = cp

    # ------------------------------------------------------------- leitura
    def texto(self, secao: str, chave: str) -> str:
        padrao = PADROES.get((secao, chave), "")
        try:
            valor = self._cp.get(secao, chave)
        except (configparser.Error, KeyError):
            return padrao
        return valor.strip()

    def flag(self, secao: str, chave: str) -> bool:
        v = self.texto(secao, chave).lower()
        if v in ("1", "true", "sim", "s", "yes", "on"):
            return True
        if v in ("0", "false", "nao", "não", "n", "no", "off"):
            return False
        return PADROES.get((secao, chave), "false").lower() == "true"

    def inteiro(self, secao: str, chave: str) -> int:
        try:
            return int(float(self.texto(secao, chave).replace(",", ".")))
        except ValueError:
            return int(PADROES.get((secao, chave), "0") or 0)

    def real(self, secao: str, chave: str) -> float:
        try:
            return float(self.texto(secao, chave).replace(",", "."))
        except ValueError:
            return float(PADROES.get((secao, chave), "0") or 0)

    def lista(self, secao: str, chave: str, sep: str = ";") -> list[str]:
        return [x.strip() for x in self.texto(secao, chave).split(sep) if x.strip()]

    # ------------------------------------------------------- atalhos usados
    @property
    def pasta_acervo(self) -> Path:
        return caminhos.resolver(self.texto("geral", "pasta_acervo"), "Acervo")

    @property
    def pasta_processos(self) -> Path:
        return self.pasta_acervo / "Processos"

    @property
    def pasta_transcricoes(self) -> Path:
        return self.pasta_acervo / "Transcricoes"

    @property
    def pasta_sigilosos(self) -> Path:
        return caminhos.resolver(self.texto("geral", "pasta_sigilosos"), "Sigilosos")

    def conflito_de_pastas(self) -> str:
        return conflito_de_pastas(self.pasta_acervo, self.pasta_sigilosos)

    def criar_pastas(self) -> None:
        for p in (self.pasta_processos, self.pasta_transcricoes,
                  self.pasta_sigilosos, caminhos.LOGS):
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ gravação
    def definir(self, secao: str, chave: str, valor) -> None:
        """Grava uma chave preservando comentários e a ordem do arquivo."""
        if isinstance(valor, bool):
            valor = "true" if valor else "false"
        valor = str(valor).replace("\r", " ").replace("\n", " ").strip()
        with _trava:
            definir_no_arquivo(self.arquivo, secao, chave, valor)
            self.recarregar()


def conflito_de_pastas(acervo: Path, sigilosos: Path) -> str:
    """Por que essas pastas não servem juntas; texto vazio se estão separadas.

    Tudo o que está dentro do acervo é compartilhado com a IA (e espelhado
    na nuvem). Se uma pasta ficar dentro da outra, os processos em segredo
    de justiça passam a estar ao alcance da IA.
    """
    try:
        a = Path(acervo).expanduser().resolve()
        s = Path(sigilosos).expanduser().resolve()
    except (OSError, RuntimeError):
        return ""
    if a == s:
        return ("A pasta dos sigilosos não pode ser a mesma do acervo: o acervo é "
                "compartilhado com a IA. Escolha pastas separadas.")
    if s.is_relative_to(a):
        return ("A pasta dos sigilosos não pode ficar dentro da pasta do acervo: tudo o que "
                "está no acervo é compartilhado com a IA. Escolha uma pasta fora dele.")
    if a.is_relative_to(s):
        return ("A pasta do acervo não pode ficar dentro da pasta dos sigilosos: os processos "
                "em segredo de justiça ficariam junto do que é compartilhado com a IA. "
                "Escolha pastas separadas.")
    return ""


_RE_SECAO = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def definir_no_arquivo(arquivo: Path, secao: str, chave: str, valor: str) -> None:
    try:
        linhas = _ler_texto(arquivo).splitlines()
    except FileNotFoundError:
        linhas = modelo_ini().splitlines()
    re_chave = re.compile(rf"^\s*{re.escape(chave)}\s*[=:]", re.I)

    inicio = fim = None
    for i, linha in enumerate(linhas):
        m = _RE_SECAO.match(linha)
        if m:
            if inicio is not None and fim is None:
                fim = i
            if m.group(1).strip().lower() == secao.lower():
                inicio = i
    if inicio is not None and fim is None:
        fim = len(linhas)

    nova = f"{chave} = {valor}"
    if inicio is None:
        linhas += ["", f"[{secao}]", nova]
    else:
        for i in range(inicio + 1, fim):
            if re_chave.match(linhas[i]):
                linhas[i] = nova
                # Valor que continuava nas linhas de baixo (indentadas) sai
                # junto; senão o ConfigParser leria o resto como parte dele.
                j = i + 1
                while j < fim and linhas[j][:1] in (" ", "\t") and linhas[j].strip():
                    del linhas[j]
                    fim -= 1
                break
        else:
            # depois da última linha não vazia da seção
            j = fim
            while j - 1 > inicio and not linhas[j - 1].strip():
                j -= 1
            linhas.insert(j, nova)

    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    os.replace(tmp, arquivo)


def carregar(criar: bool = True) -> Config:
    return Config(criar=criar)
