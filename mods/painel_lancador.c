/* Painel do pipeline (Linux) - abre o painel com dois cliques no gerenciador
 * de arquivos. Fica na pasta do projeto; chama mods/abrir_painel.py com o
 * Python gravado em mods/.python_painel (criado por "mods/painel.sh atalho").
 * Código-fonte: mods/painel_lancador.c */
#include <libgen.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
    char exe[PATH_MAX], pasta[PATH_MAX], py[PATH_MAX] = "python3", script[PATH_MAX + 32];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n < 0) return 1;
    exe[n] = 0;
    strncpy(pasta, dirname(exe), sizeof pasta - 1);
    pasta[sizeof pasta - 1] = 0;
    if (chdir(pasta) != 0) return 1;
    FILE *f = fopen("mods/.python_painel", "r");
    if (f) {
        if (fgets(py, sizeof py, f)) py[strcspn(py, "\r\n")] = 0;
        fclose(f);
    }
    snprintf(script, sizeof script, "%s/mods/abrir_painel.py", pasta);
    char *args[] = {py, script, NULL};
    execvp(py, args);
    char *aviso[] = {"notify-send", "Painel do pipeline",
                     "Não encontrei o Python do pipeline. No terminal, na pasta do projeto, rode: "
                     "bash mods/painel.sh atalho", NULL};
    execvp("notify-send", aviso);
    return 1;
}
