#include <Arduino.h>

// =====================================================
// [TEST ONLY]
// 这个文件只用于单独测试一个 HX711 channel。
// final demo 时不要编译这个文件。
// 
// 测试目标：
// 1. 单个 HX711 是否 ready
// 2. raw count 是否能读出来
// 3. 转动 potentiometer / 改变输入后 raw 是否变化
//
// 注意：这个 test 不使用 9+1 channel array。
// 9+1 channel array 在 Hx711_control.cpp 里，是 final-ready 版本。
// =====================================================


// =====================================================
// [TEST ONLY]
// 单通道测试 pin
//
// 如果单通道测试成功，并且你决定 final 也用这些 pin，
// 再把对应 pin 同步到 Hx711_control.cpp 的 channel pin 定义里。
// =====================================================

const int TEST_HX711_DT  = 35;  
const int TEST_HX711_SCK = 18;  // D27 / GPIO27


// =====================================================
// [TEST ONLY]
// 单通道测试变量
// =====================================================

long testRaw = 0;
long testZeroOffset = 0;


// =====================================================
// [TEST ONLY]
// 检查单个 HX711 是否 ready
// =====================================================

bool test_hx711_ready() {
    return digitalRead(TEST_HX711_DT) == LOW;
}


// =====================================================
// [TEST ONLY]
// 单通道 SCK pulse
// =====================================================

void test_hx711_pulse() {
    digitalWrite(TEST_HX711_SCK, HIGH);
    delayMicroseconds(1);
    digitalWrite(TEST_HX711_SCK, LOW);
    delayMicroseconds(1);
}


// =====================================================
// [TEST ONLY]
// 读取单个 HX711 raw count
// =====================================================

bool test_hx711_read_raw(long &value) {
    unsigned long startTime = millis();

    while (!test_hx711_ready()) {
        if (millis() - startTime > 1000) {
            return false;
        }
    }

    value = 0;

    for (int bit = 23; bit >= 0; bit--) {
        digitalWrite(TEST_HX711_SCK, HIGH);
        delayMicroseconds(1);

        if (digitalRead(TEST_HX711_DT) == HIGH) {
            value |= (1L << bit);
        }

        digitalWrite(TEST_HX711_SCK, LOW);
        delayMicroseconds(1);
    }

    // 25th pulse: gain 128
    test_hx711_pulse();

    // Sign extend
    if (value & 0x800000) {
        value |= 0xFF000000;
    }

    return true;
}


// =====================================================
// [TEST ONLY]
// setup()
// 只用于 Hx711_test.cpp。
// final demo 时只有 main.cpp 有 setup()。
// =====================================================

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("=== Single HX711 Channel Test ===");

    pinMode(TEST_HX711_SCK, OUTPUT);
    digitalWrite(TEST_HX711_SCK, LOW);

    pinMode(TEST_HX711_DT, INPUT_PULLUP);

    Serial.print("TEST HX711 DT  -> GPIO ");
    Serial.println(TEST_HX711_DT);

    Serial.print("TEST HX711 SCK -> GPIO ");
    Serial.println(TEST_HX711_SCK);

    Serial.println("Waiting for single HX711...");

    while (!test_hx711_ready()) {
        Serial.println("Single HX711 not ready. Check DT/SCK/VCC/GND.");
        delay(500);
    }

    Serial.println("Single HX711 ready.");

    Serial.println("Taring single channel...");
    delay(1000);

    long sum = 0;
    int validSamples = 0;

    for (int i = 0; i < 10; i++) {
        long value = 0;

        if (test_hx711_read_raw(value)) {
            sum += value;
            validSamples++;
        }

        delay(50);
    }

    if (validSamples > 0) {
        testZeroOffset = sum / validSamples;
    }

    Serial.print("Single channel zero offset = ");
    Serial.println(testZeroOffset);

    Serial.println("Start reading single HX711 channel...");
}


// =====================================================
// [TEST ONLY]
// loop()
// 单通道测试：持续打印 raw / diff
// final demo 不需要这部分。
// =====================================================

void loop() {
    long raw = 0;

    if (test_hx711_read_raw(raw)) {
        long diff = raw - testZeroOffset;

        Serial.print("Raw count: ");
        Serial.print(raw);

        Serial.print(" | Diff count: ");
        Serial.println(diff);
    }
    else {
        Serial.println("Single HX711 read timeout.");
    }

    delay(200);
}