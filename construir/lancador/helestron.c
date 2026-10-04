/*
 * Helestron.exe - o lançador do programa (ícone H na barra de tarefas).
 *
 * Fica na pasta do programa, ao lado do python312.dll, e faz o mesmo que
 *
 *     python.exe -I -m helestron [argumentos]
 *
 * mas sem console (subsistema "windows") e com o nome, o ícone e as
 * informações de versão do Helestron - é ele que aparece no Gerenciador de
 * Tarefas, na barra de tarefas e no "Abrir com".
 *
 * Por que carregar o python312.dll à mão (LoadLibraryExW + GetProcAddress)
 * em vez de ligar o executável a ele: ligado, um DLL ausente (antivírus,
 * instalação interrompida) faz o Windows mostrar "O sistema não pode
 * executar o programa porque python312.dll está faltando" - em inglês em
 * muitas máquinas e sem dizer o que fazer. Aqui a mensagem é nossa, em
 * português, com a solução (reinstalar sem perder os dados).
 *
 * O "-I" (modo isolado): PYTHONPATH, PYTHONHOME e a pasta "site" do usuário
 * são ignorados, e a pasta atual não entra no caminho de importação. Uma
 * variável deixada por outro programa (ArcGIS, outro Python) não derruba o
 * Helestron, nem um arquivo "helestron.py" esquecido na pasta de trabalho.
 *
 * O Python acha a própria biblioteca (Lib\os.py) a partir da pasta deste
 * executável: o lançador PRECISA morar na raiz da pasta do Python.
 *
 * Antes do Py_Main, confere os arquivos sem os quais nem a tela de erro do
 * programa abre (o Python sem Lib\encodings não inicia; sem o __main__.py,
 * o registro.py ou o caminhos.py do pacote, ele fecha sem dizer nada): se
 * faltar algum, a mensagem diz qual e o que fazer. E, aberto pelo atalho
 * (sem argumentos), se o programa fechar com erro em menos de
 * PRAZO_SAIDA_RAPIDA_MS sem ter mostrado janela nenhuma, a mensagem aponta o
 * registro do programa (Logs) - em vez de o clique no atalho não dar em nada.
 *
 * Compilação (construir.py faz isto):
 *   x86_64-w64-mingw32-windres helestron.rc -O coff -o recursos.o
 *   x86_64-w64-mingw32-gcc -municode -mwindows -O2 -s helestron.c recursos.o -o Helestron.exe
 */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define NOME_DLL L"python312.dll"

/* Códigos de saída do próprio lançador (o resto vem do Python). */
#define SAIDA_SEM_DLL 3
#define SAIDA_DLL_ESTRANHO 4
#define SAIDA_SEM_MEMORIA 5
#define SAIDA_FALTA_ARQUIVO 6

/* O programa que fecha com erro antes disto, sem ter mostrado janela, ganha
   a mensagem que aponta o registro (Logs). */
#define PRAZO_SAIDA_RAPIDA_MS 20000

/* Os módulos sem os quais nem a tela de erro do programa abre (relativos à
   pasta do programa, sem a extensão): cada um vale como .py ou como .pyc ao
   lado - o que o Python consegue importar (o .pyc de __pycache__ sozinho,
   sem o .py, ele não usa). */
static const wchar_t *const ESSENCIAIS[] = {
    L"Lib\\encodings\\__init__",
    L"Lib\\site-packages\\helestron\\__init__",
    L"Lib\\site-packages\\helestron\\__main__",
    L"Lib\\site-packages\\helestron\\nucleo\\__init__",
    L"Lib\\site-packages\\helestron\\nucleo\\caminhos",
    L"Lib\\site-packages\\helestron\\nucleo\\registro",
    L"Lib\\site-packages\\helestron\\aplicativo\\__init__",
    L"Lib\\site-packages\\helestron\\aplicativo\\inicio",
    L"Lib\\site-packages\\helestron\\aplicativo\\integridade",
    L"Lib\\site-packages\\helestron\\aplicativo\\erro",
    NULL
};

typedef int (*FuncaoPyMain)(int argc, wchar_t **argv);

/* A pasta deste executável, com a barra no fim. NULL se não couber. */
static wchar_t *pasta_do_programa(void)
{
    DWORD capacidade = MAX_PATH;
    for (;;) {
        wchar_t *caminho = (wchar_t *)malloc(capacidade * sizeof(wchar_t));
        if (caminho == NULL)
            return NULL;
        DWORD n = GetModuleFileNameW(NULL, caminho, capacidade);
        if (n == 0) {
            free(caminho);
            return NULL;
        }
        if (n < capacidade - 1) {
            wchar_t *barra = wcsrchr(caminho, L'\\');
            if (barra != NULL)
                barra[1] = L'\0';
            return caminho;
        }
        free(caminho);
        if (capacidade >= 32768)
            return NULL;
        capacidade *= 2;            /* caminho longo (longPathAware) */
    }
}

/*
 * Chamadas feitas pelo instalador (--encerrar antes de copiar, a conferência
 * no fim) não mostram janela: quem informa o usuário é o próprio
 * instalador, pelo código de saída. Uma caixa de mensagem ali travaria a
 * instalação silenciosa.
 */
static int chamada_do_instalador(int argc, wchar_t **argv)
{
    for (int i = 1; i < argc; i++) {
        if (wcscmp(argv[i], L"--encerrar") == 0 ||
            wcscmp(argv[i], L"--verificar-instalacao") == 0)
            return 1;
    }
    return 0;
}

static void avisar(const wchar_t *texto, DWORD codigo)
{
    wchar_t mensagem[2400];
    _snwprintf(mensagem, sizeof(mensagem) / sizeof(mensagem[0]) - 1,
               L"%ls\n\n"
               L"Isso costuma acontecer quando o antivírus põe um arquivo do programa em "
               L"quarentena, ou quando a instalação foi interrompida.\n\n"
               L"O que fazer: reinstale o Helestron com o Helestron-Setup. Ele conserta "
               L"a instalação sem apagar os seus dados (configurações, senhas, processos e "
               L"transcrições). Se o problema voltar, peça ao suporte que libere a pasta do "
               L"programa no antivírus.\n\n(código do Windows: %lu)",
               texto, (unsigned long)codigo);
    mensagem[sizeof(mensagem) / sizeof(mensagem[0]) - 1] = L'\0';
    MessageBoxW(NULL, mensagem, L"O Helestron não pôde abrir",
                MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST);
}

/* O primeiro arquivo essencial que falta (caminho completo, em achado),
   ou 0 se estão todos lá. */
static int falta_essencial(const wchar_t *pasta, wchar_t *achado, size_t capacidade,
                           DWORD *erro)
{
    for (int i = 0; ESSENCIAIS[i] != NULL; i++) {
        wchar_t py[1200], pyc[1200];
        _snwprintf(py, 1199, L"%ls%ls.py", pasta, ESSENCIAIS[i]);
        _snwprintf(pyc, 1199, L"%ls%ls.pyc", pasta, ESSENCIAIS[i]);
        py[1199] = pyc[1199] = L'\0';
        if (GetFileAttributesW(py) != INVALID_FILE_ATTRIBUTES ||
            GetFileAttributesW(pyc) != INVALID_FILE_ATTRIBUTES)
            continue;
        *erro = GetLastError();
        wcsncpy(achado, py, capacidade - 1);
        achado[capacidade - 1] = L'\0';
        return 1;
    }
    return 0;
}

/*
 * Vigia de janelas: o programa (qualquer thread deste processo) mostrou
 * alguma janela? A janela do Helestron, a tela de erro, a caixa de mensagem
 * do próprio Python... Um gancho de eventos fora de contexto, numa thread
 * com fila de mensagens própria (a principal fica presa no Py_Main).
 */
static volatile LONG abriu_janela = 0;

static void CALLBACK ao_mostrar(HWINEVENTHOOK gancho, DWORD evento, HWND janela, LONG objeto,
                                LONG filho, DWORD thread, DWORD quando)
{
    (void)gancho; (void)evento; (void)filho; (void)thread; (void)quando;
    if (janela != NULL && objeto == OBJID_WINDOW)
        InterlockedExchange(&abriu_janela, 1);
}

static DWORD WINAPI vigiar_janelas(LPVOID pronto)
{
    MSG msg;
    PeekMessageW(&msg, NULL, WM_USER, WM_USER, PM_NOREMOVE);   /* cria a fila */
    HWINEVENTHOOK gancho = SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, NULL,
                                           ao_mostrar, GetCurrentProcessId(), 0,
                                           WINEVENT_OUTOFCONTEXT);
    if (gancho == NULL)
        InterlockedExchange(&abriu_janela, 1);    /* sem vigia, nada de aviso a mais */
    SetEvent((HANDLE)pronto);
    while (GetMessageW(&msg, NULL, 0, 0) > 0)
        DispatchMessageW(&msg);
    if (gancho != NULL)
        UnhookWinEvent(gancho);
    return 0;
}

/* A pasta do registro do programa (helestron/nucleo/caminhos.py: LOCAL\Logs). */
static void pasta_dos_registros(wchar_t *destino, DWORD capacidade)
{
    wchar_t local[1024];
    DWORD n = GetEnvironmentVariableW(L"HELESTRON_LOCAL", local, 1024);
    if (n > 0 && n < 1024)
        _snwprintf(destino, capacidade - 1, L"%ls\\Logs", local);
    else if (ExpandEnvironmentStringsW(L"%LOCALAPPDATA%\\Helestron\\Logs", destino,
                                       capacidade) == 0)
        wcsncpy(destino, L"%LOCALAPPDATA%\\Helestron\\Logs", capacidade - 1);
    destino[capacidade - 1] = L'\0';
}

static void avisar_saida_rapida(int codigo)
{
    wchar_t logs[1100], mensagem[2400];
    pasta_dos_registros(logs, 1100);
    _snwprintf(mensagem, sizeof(mensagem) / sizeof(mensagem[0]) - 1,
               L"O Helestron fechou logo depois de começar, sem abrir a janela "
               L"(código %d).\n\n"
               L"O motivo ficou anotado no registro do programa, na pasta:\n%ls\n\n"
               L"Abra o Helestron de novo. Se ele fechar outra vez, reinstale-o com o "
               L"Helestron-Setup (os seus dados são mantidos) ou envie ao suporte os arquivos "
               L"dessa pasta.\n\nDeseja abrir a pasta do registro agora?",
               codigo, logs);
    mensagem[sizeof(mensagem) / sizeof(mensagem[0]) - 1] = L'\0';
    if (MessageBoxW(NULL, mensagem, L"O Helestron não pôde abrir",
                    MB_YESNO | MB_DEFBUTTON2 | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST)
            == IDYES) {
        SHCreateDirectoryExW(NULL, logs, NULL);     /* o programa pode nem ter chegado a criá-la */
        ShellExecuteW(NULL, L"open", logs, NULL, NULL, SW_SHOWNORMAL);
    }
}

int WINAPI wWinMain(HINSTANCE instancia, HINSTANCE anterior, PWSTR linha, int mostrar)
{
    (void)instancia;
    (void)anterior;
    (void)linha;
    (void)mostrar;

    /* A linha de comando já separada pelo runtime do MinGW (as mesmas regras
       do CommandLineToArgvW, sem depender do shell32). */
    int argc = __argc;
    wchar_t **argv = __wargv;
    if (argv == NULL || argc < 1)
        return SAIDA_SEM_MEMORIA;
    int silencioso = chamada_do_instalador(argc, argv);

    wchar_t *pasta = pasta_do_programa();
    if (pasta == NULL) {
        if (!silencioso)
            avisar(L"Não foi possível localizar a pasta do programa.", GetLastError());
        return SAIDA_SEM_MEMORIA;
    }

    /* Caminho completo: nada de procurar o DLL em outras pastas do sistema
       (outro Python instalado). LOAD_WITH_ALTERED_SEARCH_PATH faz as
       dependências dele (vcruntime140.dll) virem da mesma pasta. */
    size_t tamanho = wcslen(pasta) + wcslen(NOME_DLL) + 1;
    wchar_t *dll = (wchar_t *)malloc(tamanho * sizeof(wchar_t));
    if (dll == NULL)
        return SAIDA_SEM_MEMORIA;
    wcscpy(dll, pasta);
    wcscat(dll, NOME_DLL);

    HMODULE python = LoadLibraryExW(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (python == NULL) {
        DWORD erro = GetLastError();
        if (!silencioso) {
            wchar_t texto[700];
            if (GetFileAttributesW(dll) == INVALID_FILE_ATTRIBUTES)
                _snwprintf(texto, sizeof(texto) / sizeof(texto[0]) - 1,
                           L"Falta o arquivo %ls na pasta do programa:\n%ls", NOME_DLL, pasta);
            else
                _snwprintf(texto, sizeof(texto) / sizeof(texto[0]) - 1,
                           L"O arquivo %ls da pasta do programa não pôde ser carregado "
                           L"(está danificado ou falta outro arquivo de que ele depende):\n%ls",
                           NOME_DLL, pasta);
            texto[sizeof(texto) / sizeof(texto[0]) - 1] = L'\0';
            avisar(texto, erro);
        }
        return SAIDA_SEM_DLL;
    }

    FuncaoPyMain py_main = (FuncaoPyMain)(void *)GetProcAddress(python, "Py_Main");
    if (py_main == NULL) {
        if (!silencioso)
            avisar(L"O arquivo python312.dll da pasta do programa não é o esperado "
                   L"(falta a função Py_Main).", GetLastError());
        return SAIDA_DLL_ESTRANHO;
    }

    /* Os arquivos de partida: sem eles, o Python fecharia sem dizer nada.
       (Nas chamadas do instalador, quem informa é ele, pelo código.) */
    if (!silencioso) {
        wchar_t faltando[1200], texto[1500];
        DWORD erro = 0;
        if (falta_essencial(pasta, faltando, 1200, &erro)) {
            _snwprintf(texto, sizeof(texto) / sizeof(texto[0]) - 1,
                       L"Falta um arquivo do programa:\n%ls", faltando);
            texto[sizeof(texto) / sizeof(texto[0]) - 1] = L'\0';
            avisar(texto, erro);
            return SAIDA_FALTA_ARQUIVO;
        }
    }

    /* [Helestron.exe, -I, -m, helestron, argumentos do usuário...] */
    wchar_t **novo = (wchar_t **)calloc((size_t)argc + 4, sizeof(wchar_t *));
    if (novo == NULL)
        return SAIDA_SEM_MEMORIA;
    int n = 0;
    novo[n++] = argv[0];
    novo[n++] = L"-I";
    novo[n++] = L"-m";
    novo[n++] = L"helestron";
    for (int i = 1; i < argc; i++)
        novo[n++] = argv[i];
    novo[n] = NULL;

    /* Aberto pelo atalho (sem argumentos): vigia se alguma janela aparece. */
    int pelo_atalho = (argc == 1);
    HANDLE vigia = NULL;
    DWORD id_vigia = 0;
    if (pelo_atalho) {
        HANDLE pronto = CreateEventW(NULL, TRUE, FALSE, NULL);
        if (pronto != NULL) {
            vigia = CreateThread(NULL, 0, vigiar_janelas, pronto, 0, &id_vigia);
            if (vigia != NULL)
                WaitForSingleObject(pronto, 2000);
            CloseHandle(pronto);
        }
    }
    ULONGLONG inicio = GetTickCount64();

    int codigo = py_main(n, novo);

    if (vigia != NULL) {
        ULONGLONG duracao = GetTickCount64() - inicio;
        PostThreadMessageW(id_vigia, WM_QUIT, 0, 0);
        WaitForSingleObject(vigia, 2000);
        if (codigo != 0 && duracao < PRAZO_SAIDA_RAPIDA_MS && !abriu_janela)
            avisar_saida_rapida(codigo);
    }

    /* O processo termina aqui: não há o que liberar com cuidado. */
    return codigo;
}
