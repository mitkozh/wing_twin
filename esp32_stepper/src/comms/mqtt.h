#ifndef MQTT_H
#define MQTT_H

typedef void (*mqtt_msg_cb_t)(const char* topic, const char* payload);

void mqtt_init(const char* server, int port, const char* subscribe_topic);
void mqtt_loop(void);
bool mqtt_is_connected(void);
bool mqtt_publish(const char* topic, const char* payload);
void mqtt_set_callback(mqtt_msg_cb_t cb);

#endif
