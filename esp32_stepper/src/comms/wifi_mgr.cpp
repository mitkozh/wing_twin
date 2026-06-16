#include "wifi_mgr.h"
#include "../config.h"
#include <WiFi.h>
#include <esp_wpa2.h>
#include "../secrets.h"

static bool s_connected = false;
static bool s_pending = false;
static unsigned long s_lastAttempt = 0;
static unsigned int s_retryMs = WIFI_CONNECT_COOLDOWN_MS;
static unsigned int s_maxRetryMs = WIFI_MAX_RETRY_MS;

void wifi_mgr_init(void) {
    WiFi.mode(WIFI_STA);
#ifdef WIFI_EAP_IDENTITY
    esp_wifi_sta_wpa2_ent_set_identity((uint8_t *)WIFI_EAP_IDENTITY, strlen(WIFI_EAP_IDENTITY));
    esp_wifi_sta_wpa2_ent_set_username((uint8_t *)WIFI_EAP_USERNAME, strlen(WIFI_EAP_USERNAME));
    esp_wifi_sta_wpa2_ent_set_password((uint8_t *)WIFI_EAP_PASSWORD, strlen(WIFI_EAP_PASSWORD));
    esp_wifi_sta_wpa2_ent_enable();
#endif
    Serial.printf("[WIFI] Starting, SSID=%s\n", WIFI_SSID);
}

void wifi_mgr_loop(void) {
    wl_status_t st = WiFi.status();
    if (st == WL_CONNECTED) {
        if (!s_connected) {
            s_connected = true;
            s_pending = false;
            s_retryMs = WIFI_CONNECT_COOLDOWN_MS;
            Serial.printf("[WIFI] Connected, IP=%s\n", WiFi.localIP().toString().c_str());
        }
        return;
    }
    if (s_connected) {
        s_connected = false;
        s_pending = false;
        Serial.println("[WIFI] Disconnected");
    }
    unsigned long now = millis();
    if (st == WL_IDLE_STATUS) {
        if (s_pending && (now - s_lastAttempt > WIFI_TIMEOUT_MS)) {
            Serial.println("[WIFI] Timeout - resetting");
            WiFi.disconnect(true);
            s_pending = false;
            s_lastAttempt = now;
        }
        return;
    }
    if (st == WL_CONNECT_FAILED || st == WL_NO_SSID_AVAIL) {
        s_pending = false;
        s_retryMs = min(s_retryMs * 2, s_maxRetryMs);
    }
    if (s_pending) return;
    if (now - s_lastAttempt < s_retryMs) return;
    Serial.printf("[WIFI] Connecting to %s...\n", WIFI_SSID);
#ifdef WIFI_EAP_IDENTITY
    esp_wifi_sta_wpa2_ent_enable();
    WiFi.begin(WIFI_SSID);
#else
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
#endif
    s_lastAttempt = now;
    s_pending = true;
}

bool wifi_mgr_is_connected(void) {
    return s_connected;
}
