#include "RGB_control.h"

// =====================================================
// [KEEP IN RGB_control.cpp]
// 正式保留：三个 feedback RGB / LED 的命名和 GPIO 定义
//
// 1 = LED1 / tip
// 2 = LED2 / span
// 3 = LED3 / root
//
// 每个灯都有 red 和 green 两个 channel。
// yellow = red + green 同时亮。
//
// 输入格式必须是三个灯的完整状态：
// 1_green,2_yellow,3_red
// =====================================================

const int LED1_STATUS_GREEN = 16;   // D16 / GPIO16, green feedback LED
const int LED1_STATUS_RED   = 4;   // D4 / red

const int LED2_STATUS_RED   = 5;   // D5 / GPIO5, red channel
const int LED2_STATUS_GREEN = 19;   // D19 / GPIO19, green channel

const int LED3_STATUS_GREEN = 17;   // D13 / green**just change to 17 for test on june 5th
const int LED3_STATUS_RED   = 22;   // D22 / GPIO22, red feedback LED


// =====================================================
// [KEEP IN RGB_control.cpp]
// 内部函数：控制单个灯
//
// ledNumber:
// 1 = tip
// 2 = span
// 3 = root
//
// colour:
// green / yellow / red
// =====================================================

void set_single_led_internal(int ledNumber, String colour) {
    colour.trim();
    colour.toLowerCase();

    if (ledNumber == 1) {
        digitalWrite(LED1_STATUS_GREEN, LOW);
        digitalWrite(LED1_STATUS_RED, LOW);

        if (colour == "green") {
            digitalWrite(LED1_STATUS_GREEN, HIGH);
        }
        else if (colour == "yellow") {
            digitalWrite(LED1_STATUS_GREEN, HIGH);
            digitalWrite(LED1_STATUS_RED, HIGH);
        }
        else if (colour == "red") {
            digitalWrite(LED1_STATUS_RED, HIGH);
        }
    }
    else if (ledNumber == 2) {
        digitalWrite(LED2_STATUS_GREEN, LOW);
        digitalWrite(LED2_STATUS_RED, LOW);

        if (colour == "green") {
            digitalWrite(LED2_STATUS_GREEN, HIGH);
        }
        else if (colour == "yellow") {
            digitalWrite(LED2_STATUS_GREEN, HIGH);
            digitalWrite(LED2_STATUS_RED, HIGH);
        }
        else if (colour == "red") {
            digitalWrite(LED2_STATUS_RED, HIGH);
        }
    }
    else if (ledNumber == 3) {
        digitalWrite(LED3_STATUS_GREEN, LOW);
        digitalWrite(LED3_STATUS_RED, LOW);

        if (colour == "green") {
            digitalWrite(LED3_STATUS_GREEN, HIGH);
        }
        else if (colour == "yellow") {
            digitalWrite(LED3_STATUS_GREEN, HIGH);
            digitalWrite(LED3_STATUS_RED, HIGH);
        }
        else if (colour == "red") {
            digitalWrite(LED3_STATUS_RED, HIGH);
        }
    }
}


// =====================================================
// [KEEP IN RGB_control.cpp]
// 内部函数：检查颜色是否合法
// =====================================================

bool is_valid_colour(String colour) {
    colour.trim();
    colour.toLowerCase();

    return (
        colour == "green" ||
        colour == "yellow" ||
        colour == "red"
    );
}


// =====================================================
// [KEEP IN RGB_control.cpp]
// 内部函数：解析单个指令
//
// 输入示例：
// 1_green
// 2_yellow
// 3_red
// =====================================================

bool parse_single_command(String singleCommand, int &ledNumber, String &colour) {
    singleCommand.trim();
    singleCommand.toLowerCase();

    int underscoreIndex = singleCommand.indexOf('_');

    if (underscoreIndex <= 0) {
        return false;
    }

    String ledString = singleCommand.substring(0, underscoreIndex);
    colour = singleCommand.substring(underscoreIndex + 1);

    ledString.trim();
    colour.trim();

    ledNumber = ledString.toInt();

    if (ledNumber < 1 || ledNumber > 3) {
        return false;
    }

    if (!is_valid_colour(colour)) {
        return false;
    }

    return true;
}


// =====================================================
// [KEEP IN RGB_control.cpp]
// 正式保留：RGB 初始化
//
// 默认常态：三个灯全 green
// =====================================================

void rgb_init() {
    pinMode(LED1_STATUS_GREEN, OUTPUT);
    pinMode(LED1_STATUS_RED, OUTPUT);

    pinMode(LED2_STATUS_RED, OUTPUT);
    pinMode(LED2_STATUS_GREEN, OUTPUT);

    pinMode(LED3_STATUS_GREEN, OUTPUT);
    pinMode(LED3_STATUS_RED, OUTPUT);

    all_leds_off();

    // set_single_led_internal(1, "green");
    // set_single_led_internal(2, "green");
    // set_single_led_internal(3, "green");
}


// =====================================================
// [KEEP IN RGB_control.cpp]
// 正式保留：关闭所有 feedback lights
// =====================================================

void all_leds_off() {
    digitalWrite(LED1_STATUS_GREEN, LOW);
    digitalWrite(LED1_STATUS_RED, LOW);

    digitalWrite(LED2_STATUS_RED, LOW);
    digitalWrite(LED2_STATUS_GREEN, LOW);

    digitalWrite(LED3_STATUS_GREEN, LOW);
    digitalWrite(LED3_STATUS_RED, LOW);
}


// =====================================================
// [KEEP IN RGB_control.cpp]
// 正式保留：根据 server / MQTT 指令控制灯光
//
// 必须输入三个灯的完整状态。
// 正确示例：
// 1_green,2_yellow,3_red
// 1_red,2_red,3_green
// 1_yellow,2_green,3_yellow
//
// 不再支持：
// green
// yellow
// red
// =====================================================

void set_leds(String command) {
    command.trim();
    command.toLowerCase();

    int ledNumbers[3] = {0, 0, 0};
    String colours[3] = {"", "", ""};

    bool ledSeen[4] = {false, false, false, false};

    int commandCount = 0;
    int startIndex = 0;

    while (startIndex < command.length() && commandCount < 3) {
        int commaIndex = command.indexOf(',', startIndex);
        String singleCommand;

        if (commaIndex == -1) {
            singleCommand = command.substring(startIndex);
            startIndex = command.length();
        }
        else {
            singleCommand = command.substring(startIndex, commaIndex);
            startIndex = commaIndex + 1;
        }

        singleCommand.trim();

        int ledNumber = 0;
        String colour = "";

        if (!parse_single_command(singleCommand, ledNumber, colour)) {
            Serial.print("Invalid RGB command: ");
            Serial.println(singleCommand);
            Serial.println("Use full format: 1_green,2_yellow,3_red");
            return;
        }

        if (ledSeen[ledNumber]) {
            Serial.print("Duplicate LED command for LED ");
            Serial.println(ledNumber);
            Serial.println("Use one command for each LED: 1_x,2_x,3_x");
            return;
        }

        ledSeen[ledNumber] = true;
        ledNumbers[commandCount] = ledNumber;
        colours[commandCount] = colour;

        commandCount++;
    }

    if (commandCount != 3 || startIndex < command.length()) {
        Serial.println("Invalid RGB command count.");
        Serial.println("Use exactly three commands: 1_green,2_yellow,3_red");
        return;
    }

    if (!ledSeen[1] || !ledSeen[2] || !ledSeen[3]) {
        Serial.println("Invalid RGB command.");
        Serial.println("Command must include LED1, LED2, and LED3.");
        Serial.println("Example: 1_green,2_yellow,3_red");
        return;
    }

    all_leds_off();

    for (int i = 0; i < 3; i++) {
        set_single_led_internal(ledNumbers[i], colours[i]);
    }

    Serial.print("RGB state updated: ");
    Serial.println(command);
}


// =====================================================
// [KEEP IN RGB_control.cpp]
// 正式保留/可选：打印当前 RGB pin 信息，方便 debug
// =====================================================

void print_rgb_pin_info() {
    Serial.println("RGB feedback pin mapping:");

    Serial.print("LED1 / tip green -> GPIO ");
    Serial.println(LED1_STATUS_GREEN);

    Serial.print("LED1 / tip red   -> GPIO ");
    Serial.println(LED1_STATUS_RED);

    Serial.print("LED2 / span green -> GPIO ");
    Serial.println(LED2_STATUS_GREEN);

    Serial.print("LED2 / span red   -> GPIO ");
    Serial.println(LED2_STATUS_RED);

    Serial.print("LED3 / root green -> GPIO ");
    Serial.println(LED3_STATUS_GREEN);

    Serial.print("LED3 / root red   -> GPIO ");
    Serial.println(LED3_STATUS_RED);
}