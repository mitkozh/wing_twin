#ifndef WATCHDOG_H
#define WATCHDOG_H

void watchdog_init(unsigned long timeout_s);
void watchdog_feed(void);

#endif
