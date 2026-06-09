#ifndef SHELL_H
#define SHELL_H

typedef void (*shell_cmd_fn_t)(int argc, char** argv);

void shell_init(void);
void shell_loop(void);
void shell_register(const char* name, const char* help, shell_cmd_fn_t fn);

#endif
