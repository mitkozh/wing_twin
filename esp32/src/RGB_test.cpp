#include <Arduino.h>
#include "RGB_control.h"

// =====================================================
// [TEST ONLY]
// 这个文件只用于单独测试 RGB feedback module。
// final demo 时不要编译这个文件。
// 
// 测试目标：
// 1. 确认 RGB_control.cpp 是否能正确解析完整三灯状态指令
// 2. 确认三个灯的 GPIO 接线是否正确
// 3. 用 Serial Monitor 模拟 server 指令
//
// 新的 RGB_control 只接受完整三灯状态：
// 1_colour,2_colour,3_colour
//
// colour 支持：
// green
// yellow
// red
//
// 正确输入示例：
// 1_green,2_green,3_green
// 1_red,2_yellow,3_green
// 1_yellow,2_red,3_red
// =====================================================


// =====================================================
// [TEST ONLY]
// 自动测试每一步的停留时间。
// 如果你觉得太快，可以把 5000 改成 8000 或 10000。
// =====================================================

const unsigned long TEST_STEP_DELAY_MS = 5000;


// =====================================================
// [TEST ONLY]
// 打印测试菜单。
// =====================================================

void print_test_menu() {
    Serial.println();
    Serial.println("Type one full command in Serial Monitor:");
    Serial.println("1_green,2_green,3_green     -> all LEDs green");
    Serial.println("1_yellow,2_yellow,3_yellow  -> all LEDs yellow");
    Serial.println("1_red,2_red,3_red           -> all LEDs red");
    Serial.println("1_red,2_yellow,3_green      -> LED1 red, LED2 yellow, LED3 green");
    Serial.println("1_green,2_red,3_yellow      -> LED1 green, LED2 red, LED3 yellow");
    Serial.println("1_yellow,2_green,3_red      -> LED1 yellow, LED2 green, LED3 red");
    Serial.println();
    Serial.println("Special commands:");
    Serial.println("default  -> return to normal green state");
    Serial.println("auto     -> run automatic test sequence");
    Serial.println("help     -> print this menu again");
    Serial.println();
    Serial.println("Important:");
    Serial.println("Do not use only 'red' or 'green'.");
    Serial.println("Use full format: 1_colour,2_colour,3_colour");
    Serial.println();
}


// =====================================================
// [TEST ONLY]
// 执行一条完整三灯状态指令。
// 这里直接调用 RGB_control.cpp 里的 set_leds(command)。
// 如果灯不对，优先检查 RGB_control.cpp 的解析逻辑和 GPIO。
// =====================================================

void run_rgb_command(String command) {
    command.trim();
    command.toLowerCase();

    Serial.println();
    Serial.print("[RGB test command sent to RGB_control]: ");
    Serial.println(command);

    set_leds(command);

    Serial.println("[RGB test] Command executed.");
}


// =====================================================
// [TEST ONLY]
// 自动测试序列。
//
// 注意：这个 auto 只是为了检查灯和颜色。
// 手动输入时不会受这个 delay 影响。
// =====================================================

void run_auto_rgb_test() {
    Serial.println();
    Serial.println("Running automatic RGB control test...");

    run_rgb_command("1_green,2_green,3_green");
    delay(TEST_STEP_DELAY_MS);

    run_rgb_command("1_yellow,2_yellow,3_yellow");
    delay(TEST_STEP_DELAY_MS);

    run_rgb_command("1_red,2_red,3_red");
    delay(TEST_STEP_DELAY_MS);

    run_rgb_command("1_red,2_yellow,3_green");
    delay(TEST_STEP_DELAY_MS);

    run_rgb_command("1_green,2_red,3_yellow");
    delay(TEST_STEP_DELAY_MS);

    run_rgb_command("1_yellow,2_green,3_red");
    delay(TEST_STEP_DELAY_MS);

    run_rgb_command("1_green,2_green,3_green");
    delay(TEST_STEP_DELAY_MS);

    Serial.println("Automatic RGB control test finished.");
    print_test_menu();
}


// =====================================================
// [TEST ONLY]
// setup()
// RGB_test.cpp 里面的 setup 只用于单独测试。
// final demo 时只有 main.cpp 保留 setup()。
// =====================================================

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("=== RGB Feedback Test ===");

    rgb_init();
    print_rgb_pin_info();

    Serial.println();
    Serial.println("Default state: 1_green,2_green,3_green");
    set_leds("1_green,2_green,3_green");

    print_test_menu();

    Serial.println("Waiting for your input...");
}


// =====================================================
// [TEST ONLY]
// loop()
// 从 Serial Monitor 读取完整指令。
// 
// 你可以慢慢输入，例如：
// 1_red,2_yellow,3_green
//
// 只有按 Enter 后才会执行。
// 所以手速慢不会影响测试。
// =====================================================

void loop() {
    if (Serial.available() > 0) {
        String command = Serial.readStringUntil('\n');
        command.trim();
        command.toLowerCase();

        if (command.length() == 0) {
            return;
        }

        if (command == "auto") {
            run_auto_rgb_test();
        }
        else if (command == "help") {
            print_test_menu();
        }
        else if (command == "default") {
            run_rgb_command("1_green,2_green,3_green");
        }
        else {
            run_rgb_command(command);
        }

        Serial.println();
        Serial.println("Waiting for next input...");
    }
}