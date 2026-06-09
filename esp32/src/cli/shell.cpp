#include "shell.h"
#include <Arduino.h>

#define MAX_CMD  16
#define MAX_ARGS 8
#define LINE_LEN 128

typedef struct {
    const char*   name;
    const char*   help;
    shell_cmd_fn_t fn;
} cmd_entry_t;

static cmd_entry_t s_cmds[MAX_CMD];
static int s_numCmds = 0;
static char s_line[LINE_LEN];
static int s_pos = 0;

static void cmd_help(int, char**) {
    Serial.println("Commands:");
    for (int i = 0; i < s_numCmds; i++)
        Serial.printf("  %s %s\n", s_cmds[i].name, s_cmds[i].help);
}

void shell_init(void) {
    shell_register("help", "print this help", cmd_help);
    Serial.println("[SHELL] ready - type help");
}

void shell_register(const char* name, const char* help, shell_cmd_fn_t fn) {
    if (s_numCmds >= MAX_CMD) return;
    s_cmds[s_numCmds].name = name;
    s_cmds[s_numCmds].help = help;
    s_cmds[s_numCmds].fn   = fn;
    s_numCmds++;
}

void shell_loop(void) {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            s_line[s_pos] = '\0';
            if (s_pos > 0) {
                char* argv[MAX_ARGS];
                int argc = 0;
                char* tok = strtok(s_line, " ");
                while (tok && argc < MAX_ARGS) {
                    argv[argc++] = tok;
                    tok = strtok(NULL, " ");
                }
                if (argc > 0) {
                    bool found = false;
                    for (int i = 0; i < s_numCmds; i++) {
                        if (strcmp(argv[0], s_cmds[i].name) == 0) {
                            s_cmds[i].fn(argc, argv);
                            found = true;
                            break;
                        }
                    }
                    if (!found) Serial.printf("unknown: %s\n", argv[0]);
                }
            }
            s_pos = 0;
            Serial.print("> ");
        } else if (c == 127 || c == '\b') {
            if (s_pos > 0) s_pos--;
        } else if (s_pos < LINE_LEN - 1) {
            s_line[s_pos++] = c;
        }
    }
}
