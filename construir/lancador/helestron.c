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
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define NOME_DLL L"python312.dll"

/* Códigos de saída do próprio lançador (o resto vem do Python). */
#define SAIDA_SEM_DLL 3
#define SAIDA_DLL_ESTRANHO 4
#define SAIDA_SEM_MEMORIA 5

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
    wchar_t mensagem[1400];
    _snwprintf(mensagem, sizeof(mensagem) / sizeof(mensagem[0]) - 1,
               L"%ls\n\n"
               L"Isso costuma acontecer quando o antivírus põe um arquivo do programa em "
               L"quarentena, ou quando a instalação foi interrompida.\n\n"
               L"O que fazer: instale o Helestron de novo com o Helestron-Setup. Ele conserta "
               L"a instalação sem apagar os seus dados (configurações, senhas, processos e "
               L"transcrições). Se o problema voltar, peça ao suporte que libere a pasta do "
               L"programa no antivírus.\n\n(código do Windows: %lu)",
               texto, (unsigned long)codigo);
    mensagem[sizeof(mensagem) / sizeof(mensagem[0]) - 1] = L'\0';
    MessageBoxW(NULL, mensagem, L"O Helestron não pôde abrir",
                MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST);
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

    int codigo = py_main(n, novo);

    /* O processo termina aqui: não há o que liberar com cuidado. */
    return codigo;
}
