#include <Arduino.h>

#include "RGB_control.h"
#include "Hx711_control.h"
#include "mqtt_control.h"


// =====================================================
// [MAIN SETTING]
// 主程序设置
//
// ESP32 会定时读取 HX711 的 10 个 channel，
// 并通过 MQTT 发送给 laptop / server。
// 同时 MQTT 也会持续接收 server 发回来的 RGB 指令。
// =====================================================

unsigned long lastPublishTime = 0;
const unsigned long PUBLISH_INTERVAL = 1000;   // 每 1 秒发送一次 sensor data


// =====================================================
// [SETUP]
// 初始化部分，只运行一次
// =====================================================

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("=================================");
    Serial.println(" ESP32 Final Main Program");
    Serial.println(" HX711 + MQTT + RGB Feedback");
    Serial.println("=================================");

    // 初始化 RGB feedback lights
    // 默认状态：三个灯全 green
    rgb_init();
    set_leds("1_green,2_green,3_green");

    // 初始化 HX711 模块
    // 这里应该包括 HX711 pin 设置、tare、offset 等
    hx711_init();

    // 初始化 WiFi + MQTT
    // mqtt_control.cpp 中会设置 broker 地址和 callback
    mqtt_init();

    Serial.println("System initialization finished.");
    Serial.println("ESP32 is ready to send sensor data and receive RGB commands.");

    // 可选 debug：打印 RGB 和 HX711 的 pin 信息
    print_rgb_pin_info();
    hx711_print_pin_info();
}


// =====================================================
// [LOOP]
// 主循环部分，会一直重复运行
// =====================================================

void loop() {
    // -------------------------------------------------
    // 1. MQTT loop 必须一直调用
    //
    // 作用：
    // - 保持 MQTT 连接
    // - 接收 server 发来的 wing/control 指令
    // - 收到指令后，mqtt_control.cpp 会自动调用 set_leds(message)
    //
    // 如果不调用 mqtt_loop()，
    // ESP32 就收不到 server 发来的 RGB 指令。
    // -------------------------------------------------
    mqtt_loop();


    // -------------------------------------------------
    // 2. 定时读取 HX711，并发送 JSON 到 server
    //
    // 重点：
    // 这里不使用 hx711_ready_all() 来阻止发送。
    //
    // 原因：
    // 如果 10 个 channel 里面只有 1 个没有 ready，
    // 我们仍然希望其他 9 个正常 channel 可以发送。
    //
    // 没有 ready / 没有输入的 channel，
    // 应该在 hx711_build_sensor_payload() 里面被写成 null。
    // -------------------------------------------------
    if (millis() - lastPublishTime >= PUBLISH_INTERVAL) {
        lastPublishTime = millis();

        // 尝试读取所有 HX711 channel
        //
        // 这个函数应该在 Hx711_control.cpp 里面逐个 channel 判断：
        // - ready 的 channel：读取并更新最新值
        // - not ready 的 channel：标记为 unavailable
        //
        // 注意：
        // 即使 readOk == false，也不要 return。
        // 因为 false 可能只是代表“不是所有 channel 都成功”。
        bool readOk = hx711_read_all_channels();

        if (!readOk) {
            Serial.println("[HX711] Warning: some channels are not ready or not readable.");
            Serial.println("[HX711] Continue sending payload. Unavailable channels should be null.");
        }

        // 对已经成功读取的 channel 做 dummy compensation
        //
        // Hx711_control.cpp 内部应该跳过 not ready 的 channel。
        // 不要让一个 not ready channel 影响其他 channel。
        hx711_compensate_dummy();

        // 打印当前最新值，方便在 Serial Monitor 里检查
        //
        // 注意：
        // 如果某些 channel 没 ready，这里可能仍显示旧值或 0。
        // 真正发给 server 的 null 逻辑应该看 payload。
        hx711_print_latest_values();

        // 构建 JSON payload
        //
        // 要求 hx711_build_sensor_payload() 内部实现：
        //
        // ready channel:
        // "root_0": 12345
        //
        // not ready / no output channel:
        // "root_45": null
        //
        // 注意 JSON 里面的 null 最好不要加引号。
        // 正确： "root_45": null
        // 不推荐： "root_45": "null"
        char payload[1000];
        hx711_build_sensor_payload(payload, sizeof(payload));

        // 每一轮都发送 JSON
        // 即使有 channel 是 null，也照常发给 server。
        mqtt_publish_payload(payload);
    }
}
