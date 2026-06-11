#ifndef MQTT_H
#define MQTT_H

void mqtt_init(const char* server, int port, const char* subscribe_topics);
void mqtt_loop(void);
bool mqtt_is_connected(void);
bool mqtt_publish(const char* topic, const char* payload);
void mqtt_set_callback(void (*cb)(const char* topic, const char* payload));

#endif
