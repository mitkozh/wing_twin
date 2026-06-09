#include "watchdog.h"
#include <esp_task_wdt.h>

void watchdog_init(unsigned long timeout_s) {
    esp_task_wdt_init(timeout_s, true);
    esp_task_wdt_add(NULL);
}

void watchdog_feed(void) {
    esp_task_wdt_reset();
}
